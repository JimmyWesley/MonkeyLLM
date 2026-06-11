"""Vine — the navigation protocol (spec Part C).

Eight primitives over a markdown forest:
read: locate, look, move, pick, query, scan
write: plant, graft (atomic, Git-committed, index-synced)

Every response fits its declared token budget; truncation is always
explicit (`truncated: true`), never silent.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import threading
import time
from pathlib import Path

from monkeyllm import indexer
from monkeyllm.canopy import CanopyIndex, rrf_fuse
from monkeyllm.catalog import Catalog
from monkeyllm.dialect import MAX_LINKS_PER_NODE
from monkeyllm.errors import (
    E_NOT_FOUND,
    E_QUERY_FORBIDDEN,
    E_READONLY,
    E_SCHEMA,
    E_TIMEOUT,
    VineError,
)
from monkeyllm.forest import Forest, WriterLock
from monkeyllm.gitops import GitRepo
from monkeyllm.models import (
    MUTABLE_FRONTMATTER_FIELDS,
    GraftPatch,
    Link,
    NodeSpec,
    validate_frontmatter,
    validate_summary,
)
from monkeyllm.parser import (
    ParsedNode,
    append_section,
    extract_section,
    replace_section,
    serialize_node,
)
from monkeyllm.telemetry import Tracer
from monkeyllm.tokens import (
    estimate_payload_tokens,
    estimate_tokens,
    shrink_list_to_budget,
    truncate_text,
)
from monkeyllm.trails import Trails

BUDGET_LOCATE = 800
BUDGET_LOOK = 500
BUDGET_MOVE = 600
BUDGET_SCAN = 800
PICK_MAX_BODY_TOKENS = 4000
NEIGHBOR_SUMMARY_TOKENS = 25
MAX_EDGES_SHOWN = 12
QUERY_DEFAULT_LIMIT = 200
QUERY_TIMEOUT_S = 2.0

_FORBIDDEN_SQL = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)


def _traced(fn):
    def wrapper(self: "Vine", *args, **kwargs):
        t0 = time.perf_counter()
        result = fn(self, *args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        node_id = kwargs.get("id") or (args[0] if args else None)
        self.tracer.record(
            fn.__name__,
            node_id if isinstance(node_id, str) else None,
            tokens_in=estimate_tokens(json.dumps([str(a) for a in args]) + json.dumps(kwargs, default=str)),
            tokens_out=estimate_payload_tokens(result),
            elapsed_ms=elapsed,
        )
        return result

    return wrapper


class Vine:
    def __init__(
        self,
        root: str | Path,
        writable: bool = True,
        session: str | None = None,
        alpha: float = 0.3,
        embedder=None,
        beta: float = 1.0,
    ):
        self.forest = Forest(root)
        self.catalog = Catalog(self.forest)
        self.trails = Trails(self.forest.derived_dir)
        self.tracer = Tracer(self.forest.derived_dir, self.trails, session)
        self.alpha = alpha
        self.beta = beta
        self.writable = writable
        self.git = GitRepo(self.forest.root)
        self._write_mutex = threading.Lock()
        self._lock: WriterLock | None = None
        if writable:
            self._lock = WriterLock(self.forest.root)
            self._lock.acquire()
        if self.catalog.count() == 0:
            self.catalog.reindex()
        # Canopy (optional vector layer, Phase 1). BM25-only unless BOTH a
        # built index and a query embedder are present (locate contract is
        # unchanged otherwise — arquitetura §3).
        self.embedder = embedder
        self.canopy = CanopyIndex.load(self.forest.derived_dir)

    @property
    def hybrid(self) -> bool:
        return self.embedder is not None and self.canopy is not None and len(self.canopy) > 0

    def build_canopy(self, embedder=None) -> dict:
        """Embed every node's summary and persist the vector index. Offline
        (Gardener territory): generous compute, runs out of the read path."""
        emb = embedder or self.embedder
        if emb is None:
            raise VineError(E_SCHEMA, "build_canopy needs an embedder")
        rows = self.catalog.conn.execute(
            "SELECT id, title, summary FROM nodes ORDER BY id"
        ).fetchall()
        pairs = [(r["id"], f"{r['title']}. {r['summary']}") for r in rows]
        idx = CanopyIndex.build(pairs, emb)
        idx.save(self.forest.derived_dir)
        self.canopy = idx
        self.catalog.clear_stale(self.catalog.stale_ids())
        return {"nodes": len(idx), "model": idx.model, "dim": idx.dim}

    def _refresh_canopy(self) -> None:
        """Lazy re-embedding (spec Fase 1): nodes marked stale by plant/graft
        get their vectors refreshed before the next hybrid search, so the
        dense layer reflects writes without an offline rebuild."""
        stale = self.catalog.stale_ids()
        if not stale:
            return
        rows = [self.catalog.get(i) for i in stale]
        pairs = [(r["id"], f"{r['title']}. {r['summary']}") for r in rows if r is not None]
        if pairs:
            vecs = self.embedder.embed([t for _, t in pairs])
            for (node_id, _), vec in zip(pairs, vecs):
                self.canopy.upsert(node_id, vec)
            self.canopy.save(self.forest.derived_dir)
        self.catalog.clear_stale(stale)

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        if self._lock:
            self._lock.release()
            self._lock = None
        self.catalog.close()
        self.trails.close()

    def __enter__(self) -> "Vine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def reindex(self) -> int:
        return self.catalog.reindex()

    def close_session(self, success: bool, answer_nodes: list[str]) -> dict:
        return self.tracer.close_session(success, answer_nodes, trail_of=self.forest.trail)

    # -- helpers -----------------------------------------------------------

    def _heat(self, node_id: str) -> float:
        return self.trails.get_heat(node_id, self.tracer.session)

    def _summary_of(self, node_id: str) -> str:
        row = self.catalog.get(node_id)
        return row["summary"] if row else ""

    def _row_or_raise(self, node_id: str) -> sqlite3.Row:
        row = self.catalog.get(node_id)
        if row is None:
            if self.forest.exists(node_id):
                self.catalog.upsert_node(self.forest.read(node_id))
                return self.catalog.get(node_id)
            raise VineError(
                E_NOT_FOUND,
                f"node not found: {node_id}",
                hint="Use locate() to find entry points.",
            )
        return row

    # =======================================================================
    # C.1 locate — the helicopter
    # =======================================================================

    @_traced
    def locate(
        self,
        query: str,
        k: int = 5,
        scope: str = "all",
        type_filter: str | None = None,
    ) -> dict:
        cand = max(k * 5, 25)
        rows = self.catalog.fts_search(query, limit=cand)
        by_id = {r["id"]: r for r in rows}

        # base strength per id, in [0, 1]. BM25-only by default (Phase 0);
        # RRF(vector, BM25) when the canopy layer is active (Phase 1).
        if self.hybrid:
            self._refresh_canopy()
            qvec = self.embedder.embed([query])[0]
            vec_hits = self.canopy.search(qvec, k=cand)
            for vid, _cos in vec_hits:
                if vid not in by_id:
                    extra = self.catalog.get(vid)
                    if extra is not None:
                        by_id[vid] = extra
            bm25_ids = [r["id"] for r in rows]
            vec_ids = [vid for vid, _ in vec_hits]
            fused = rrf_fuse(bm25_ids, vec_ids)
            top = max(fused.values()) if fused else 1.0
            strength_of = {i: (s / top if top else 0.0) for i, s in fused.items()}
        else:
            best = min((r["rank"] for r in rows), default=0.0)  # bm25: lower=better (<=0)
            strength_of = {
                r["id"]: ((r["rank"] / best) if best < 0 else 1.0) for r in rows
            }

        candidates = list(by_id.values())
        if scope == "branches":
            candidates = [r for r in candidates if r["kind"] == "branch"]
        elif scope == "bananas":
            candidates = [r for r in candidates if r["kind"] == "banana"]
        if type_filter:
            candidates = [r for r in candidates if r["type"] == type_filter]

        results = []
        for r in candidates:
            strength = strength_of.get(r["id"], 0.0)
            heat = self._heat(r["id"])
            score = strength * (1 + self.alpha * heat)
            item = {
                "id": r["id"],
                "kind": r["kind"],
                "type": r["type"],
                "title": r["title"],
                "summary": r["summary"],
                "trail": json.loads(r["trail"]),
                "score": round(score, 4),
                "heat": heat,
            }
            if r["kind"] == "branch" and r["coverage"]:
                item["coverage"] = r["coverage"]
            results.append(item)
        results.sort(key=lambda x: x["score"], reverse=True)
        payload = {"results": results[:k], "truncated": len(results) > k}
        return shrink_list_to_budget(payload, "results", BUDGET_LOCATE)

    # =======================================================================
    # C.2 look — the central operation (<= 500 tokens)
    # =======================================================================

    @_traced
    def look(self, id: str, fields: list[str] | None = None) -> dict:
        row = self._row_or_raise(id)
        node = self.forest.read(id)
        digest: dict = {
            "id": id,
            "type": row["type"],
            "title": row["title"],
            "summary": row["summary"],
            "tags": json.loads(row["tags"]),
            "confidence": row["confidence"],
            "updated": row["updated"],
        }

        edges_out = []
        for e in self.catalog.edges_out(id):
            edges_out.append(
                {
                    "rel": e["rel"],
                    "target": e["dst"],
                    "target_summary": truncate_text(
                        self._summary_of(e["dst"]), NEIGHBOR_SUMMARY_TOKENS
                    ),
                    "_heat": self._heat(e["dst"]),
                }
            )
        edges_out.sort(key=lambda e: e["_heat"], reverse=True)
        edges_in = []
        for e in self.catalog.edges_in(id):
            shown_rel = self.forest.dialect.inverse(e["rel"]) or e["rel"]
            edges_in.append({"rel": shown_rel, "source": e["src"], "_heat": self._heat(e["src"])})
        edges_in.sort(key=lambda e: e["_heat"], reverse=True)
        degree = len(edges_out) + len(edges_in)
        for e in edges_out + edges_in:
            e.pop("_heat", None)
        digest["edges_out"] = edges_out[:MAX_EDGES_SHOWN]
        digest["edges_in"] = edges_in[:MAX_EDGES_SHOWN]

        if row["kind"] == "branch":
            children = [
                {"id": c["id"], "summary": truncate_text(c["summary"], NEIGHBOR_SUMMARY_TOKENS)}
                for c in self.catalog.children(id)
            ]
            digest["children"] = children
            cross = extract_section(node.body, "Trilhas cruzadas")
            if cross:
                digest["cross_trails"] = [
                    ln.lstrip("- ").strip() for ln in cross.splitlines()[1:] if ln.strip().startswith("-")
                ]
            if row["coverage"]:
                digest["coverage"] = row["coverage"]
        else:
            digest["outline"] = json.loads(row["outline"])

        if row["type"] == "dataset" and row["payload_type"] == "sqlite":
            digest["query_manual"] = self._dataset_manual(node)
            digest["sample_rows"] = self._dataset_sample(node)

        digest["stats"] = {
            "body_tokens": row["body_tokens"],
            "degree": degree,
            "heat": self._heat(id),
        }

        if fields:
            keep = set(fields) | {"id"}
            digest = {k: v for k, v in digest.items() if k in keep}

        for key in ("edges_in", "edges_out", "children"):
            if key in digest:
                shrink_list_to_budget(digest, key, BUDGET_LOOK)
        if estimate_payload_tokens(digest) > BUDGET_LOOK:
            digest.pop("sample_rows", None)
            digest["truncated"] = True
        return digest

    def _dataset_db(self, node: ParsedNode) -> Path:
        db = self.forest.payload_path(node)
        if not db.is_file():
            raise VineError(E_NOT_FOUND, f"payload missing: {db.name}")
        return db

    def _dataset_manual(self, node: ParsedNode) -> dict:
        db = self._dataset_db(node)
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            tables = {}
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ):
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({name})")]
                tables[name] = cols
        finally:
            conn.close()
        manual_section = extract_section(node.body, "Manual de consulta") or ""
        example_queries = re.findall(r"`(SELECT[^`]+)`", manual_section, re.IGNORECASE)[:3]
        return {"tables": tables, "example_queries": example_queries}

    def _dataset_sample(self, node: ParsedNode, n: int = 3) -> dict:
        db = self._dataset_db(node)
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
            ).fetchone()
            if not row:
                return {"columns": [], "rows": []}
            cur = conn.execute(f"SELECT * FROM {row[0]} LIMIT {n}")
            return {
                "columns": [d[0] for d in cur.description],
                "rows": [list(r) for r in cur.fetchall()],
            }
        finally:
            conn.close()

    # =======================================================================
    # C.3 move — structural navigation (<= 600 tokens)
    # =======================================================================

    @_traced
    def move(self, id: str, rel: str | None = None, direction: str = "out") -> dict:
        self._row_or_raise(id)
        neighbors: list[dict] = []

        if rel == "children":
            for c in self.catalog.children(id):
                neighbors.append(
                    {
                        "id": c["id"],
                        "rel": "children",
                        "direction": "out",
                        "type": c["type"],
                        "summary": c["summary"],
                        "heat": self._heat(c["id"]),
                    }
                )
        else:
            if direction in ("out", "both"):
                for e in self.catalog.edges_out(id):
                    if rel and e["rel"] != rel:
                        continue
                    neighbors.append(
                        {
                            "id": e["dst"],
                            "rel": e["rel"],
                            "direction": "out",
                            "type": (self.catalog.get(e["dst"]) or {"type": "?"})["type"],
                            "summary": self._summary_of(e["dst"]),
                            "heat": self._heat(e["dst"]),
                        }
                    )
            if direction in ("in", "both"):
                for e in self.catalog.edges_in(id):
                    shown = self.forest.dialect.inverse(e["rel"]) or e["rel"]
                    if rel and rel not in (e["rel"], shown):
                        continue
                    neighbors.append(
                        {
                            "id": e["src"],
                            "rel": shown,
                            "direction": "in",
                            "type": (self.catalog.get(e["src"]) or {"type": "?"})["type"],
                            "summary": self._summary_of(e["src"]),
                            "heat": self._heat(e["src"]),
                        }
                    )

        neighbors.sort(key=lambda n: n["heat"], reverse=True)
        payload = {"neighbors": neighbors, "truncated": False}
        return shrink_list_to_budget(payload, "neighbors", BUDGET_MOVE)

    # =======================================================================
    # C.4 pick — harvest the banana
    # =======================================================================

    @_traced
    def pick(self, id: str, section: str | None = None) -> dict:
        node = self.forest.read(id)
        if section:
            content = extract_section(node.body, section)
            if content is None:
                raise VineError(
                    E_NOT_FOUND,
                    f"section '{section}' not found in {id}",
                    hint=f"Available sections: {node.outline}",
                )
            return {
                "id": id,
                "title": node.title,
                "section": section,
                "body": content,
                "body_tokens": estimate_tokens(content),
                "truncated": False,
            }
        if node.body_tokens > PICK_MAX_BODY_TOKENS:
            return {
                "id": id,
                "title": node.title,
                "outline": node.outline,
                "body_tokens": node.body_tokens,
                "truncated": True,
                "hint": "Body exceeds 4000 tokens. Use section=<header> to harvest one section.",
            }
        return {
            "id": id,
            "title": node.title,
            "body": node.body,
            "body_tokens": node.body_tokens,
            "truncated": False,
        }

    # =======================================================================
    # C.5 query — read-only SQL over dataset payloads
    # =======================================================================

    @_traced
    def query(self, id: str, sql: str) -> dict:
        row = self._row_or_raise(id)
        if row["type"] != "dataset" or row["payload_type"] != "sqlite":
            raise VineError(
                E_QUERY_FORBIDDEN,
                f"node {id} is not a sqlite dataset (type={row['type']})",
                hint="query() only works on type:dataset nodes with payload_type:sqlite.",
            )
        sql = sql.strip().rstrip(";").strip()
        if ";" in sql:
            raise VineError(E_QUERY_FORBIDDEN, "only a single SQL statement is allowed")
        first = sql.split(None, 1)[0].upper() if sql else ""
        if first not in ("SELECT", "WITH"):
            raise VineError(E_QUERY_FORBIDDEN, "statement must start with SELECT or WITH")
        m = _FORBIDDEN_SQL.search(sql)
        if m:
            raise VineError(E_QUERY_FORBIDDEN, f"forbidden keyword: {m.group(1).upper()}")

        limited_injected = False
        if not _LIMIT_RE.search(sql):
            sql = f"{sql} LIMIT {QUERY_DEFAULT_LIMIT}"
            limited_injected = True

        node = self.forest.read(id)
        db = self._dataset_db(node)
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        deadline = time.monotonic() + QUERY_TIMEOUT_S
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        t0 = time.perf_counter()
        try:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            columns = [d[0] for d in cur.description] if cur.description else []
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                raise VineError(E_TIMEOUT, f"query exceeded {QUERY_TIMEOUT_S}s") from e
            raise VineError(E_QUERY_FORBIDDEN, f"SQL error: {e}") from e
        finally:
            conn.close()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return {
            "columns": columns,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "limited": limited_injected and len(rows) == QUERY_DEFAULT_LIMIT,
            "elapsed_ms": round(elapsed_ms, 2),
        }

    # =======================================================================
    # C.6 scan — metadata queries via the Catalog (<= 800 tokens)
    # =======================================================================

    @_traced
    def scan(
        self,
        parent_id: str,
        filter: dict | None = None,
        fields: list[str] | None = None,
        recursive: bool = False,
        limit: int = 50,
    ) -> dict:
        self._row_or_raise(parent_id)
        filter = filter or {}
        fields = fields or ["id", "type", "summary"]
        limit = min(max(1, limit), 50)

        rows = self.catalog.children(parent_id, recursive=recursive)
        out = []
        for r in rows:
            if not self._match_filter(r, filter):
                continue
            item = {"id": r["id"]}
            for f in fields:
                if f == "id":
                    continue
                if f in ("tags", "aliases", "trail", "outline"):
                    item[f] = json.loads(r[f])
                elif f == "heat":
                    item[f] = self._heat(r["id"])
                elif f in r.keys():
                    item[f] = r[f]
            item["_heat"] = self._heat(r["id"])
            out.append(item)
        out.sort(key=lambda x: x["_heat"], reverse=True)
        for item in out:
            item.pop("_heat", None)
        payload = {"nodes": out[:limit], "truncated": len(out) > limit}
        return shrink_list_to_budget(payload, "nodes", BUDGET_SCAN)

    @staticmethod
    def _match_filter(row: sqlite3.Row, flt: dict) -> bool:
        for key, want in flt.items():
            if key == "tags_any":
                tags = set(json.loads(row["tags"]))
                if not tags & set(want):
                    return False
            elif key == "updated_after":
                if not row["updated"] or row["updated"] < str(want):
                    return False
            elif key == "updated_before":
                if not row["updated"] or row["updated"] > str(want):
                    return False
            elif key == "created_after":
                if not row["created"] or row["created"] < str(want):
                    return False
            elif key == "min_confidence":
                if row["confidence"] < float(want):
                    return False
            elif key in row.keys():
                if row[key] != want:
                    return False
            else:
                raise VineError(E_SCHEMA, f"unknown scan filter: {key}")
        return True

    # =======================================================================
    # C.7 plant — atomic create (file + index + git)
    # =======================================================================

    @_traced
    def plant(self, node: dict | NodeSpec) -> dict:
        self._require_writable()
        spec = node if isinstance(node, NodeSpec) else NodeSpec.model_validate(node)
        with self._write_mutex:
            return self._plant(spec)

    def _plant(self, spec: NodeSpec) -> dict:
        fm = spec.frontmatter_dict()
        validate_frontmatter(fm, self.forest.dialect)
        if self.forest.exists(spec.id):
            raise VineError(E_SCHEMA, f"id already exists: {spec.id}", hint="ids are immutable and unique.")
        parent_row = self.catalog.get(spec.parent)
        if parent_row is None or parent_row["kind"] != "branch":
            raise VineError(E_NOT_FOUND, f"parent branch not found: {spec.parent}")
        expected_parent = self.forest.parent_index_id(spec.id)
        if spec.parent != expected_parent:
            raise VineError(
                E_SCHEMA,
                f"id '{spec.id}' does not live under parent '{spec.parent}' "
                f"(expected parent: {expected_parent})",
            )

        body = spec.body.strip() or f"# {spec.title}"
        if not body.lstrip().startswith("#"):
            body = f"# {spec.title}\n\n{body}"
        content = serialize_node(fm, body)

        parent_node = self.forest.read(spec.parent)
        new_parent_body = indexer.add_entry(
            parent_node, spec.id, spec.summary, is_branch=(spec.type == "galho")
        )
        new_parent_content = indexer.render_index(parent_node, new_parent_body)

        written: list[tuple[Path, str | None]] = []
        try:
            node_path = self.forest.path_for(spec.id)
            written.append((node_path, None))
            self.forest.write(spec.id, content)
            assert parent_node.path is not None
            written.append((parent_node.path, parent_node.path.read_text(encoding="utf-8")))
            parent_node.path.write_text(new_parent_content, encoding="utf-8", newline="\n")
            commit = self.git.commit(
                [node_path, parent_node.path],
                f"plant({spec.id}): {spec.title} [source={spec.source}]",
            )
        except Exception:
            for path, original in reversed(written):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(original, encoding="utf-8", newline="\n")
            raise

        self.catalog.upsert_node(self.forest.read(spec.id))
        self.catalog.upsert_node(self.forest.read(spec.parent))
        self.catalog.mark_stale(spec.id)
        return {"id": spec.id, "commit": commit, "trail": self.forest.trail(spec.id)}

    # =======================================================================
    # C.8 graft — atomic edit with reinforce-before-create
    # =======================================================================

    @_traced
    def graft(self, id: str, patch: dict | GraftPatch) -> dict:
        self._require_writable()
        p = patch if isinstance(patch, GraftPatch) else GraftPatch.model_validate(patch)
        with self._write_mutex:
            return self._graft(id, p)

    def _graft(self, id: str, patch: GraftPatch) -> dict:
        node = self.forest.read(id)
        if patch.is_empty():
            raise VineError(E_SCHEMA, "empty graft patch")

        for field in patch.set_frontmatter:
            if field not in MUTABLE_FRONTMATTER_FIELDS:
                raise VineError(
                    E_READONLY,
                    f"frontmatter field '{field}' is immutable",
                    hint=f"Mutable fields: {sorted(MUTABLE_FRONTMATTER_FIELDS)}",
                )
        if "summary" in patch.set_frontmatter:
            validate_summary(str(patch.set_frontmatter["summary"]))

        fm = dict(node.frontmatter)
        body = node.body
        file_changed = False
        fortified: list[dict] = []

        if patch.set_frontmatter:
            fm.update(patch.set_frontmatter)
            file_changed = True

        links = [Link.model_validate(l) for l in (fm.get("links") or [])]
        existing = {l.key() for l in links}

        for link in patch.add_links:
            if link.rel not in self.forest.dialect.rels:
                raise VineError(E_SCHEMA, f"unknown rel '{link.rel}'")
            if link.key() in existing:
                # Reinforce-before-create: duplicate link -> fortification
                # (heat goes up; no new edge, no commit for this op).
                self.trails.add_heat([id, link.target], amount=0.1)
                fortified.append({"rel": link.rel, "target": link.target})
                continue
            extra = link.model_dump()
            if link.rel == "atalho-descoberto":
                extra.setdefault("confidence", 0.5)
                extra.setdefault("discovered_by", "agente")
            links.append(Link.model_validate(extra))
            existing.add(link.key())
            file_changed = True

        if patch.remove_links:
            removals = {l.key() for l in patch.remove_links}
            kept = [l for l in links if l.key() not in removals]
            if len(kept) != len(links):
                links = kept
                file_changed = True

        if len(links) > MAX_LINKS_PER_NODE:
            raise VineError(E_SCHEMA, f"node would have {len(links)} links (max {MAX_LINKS_PER_NODE})")
        fm["links"] = [l.model_dump(exclude_none=True) for l in links]
        if not fm["links"]:
            fm.pop("links")

        if patch.replace_section:
            new_body = replace_section(body, patch.replace_section.header, patch.replace_section.body)
            if new_body is None:
                raise VineError(
                    E_NOT_FOUND,
                    f"section '{patch.replace_section.header}' not found in {id}",
                    hint="Use append_section to add a new section.",
                )
            body = new_body
            file_changed = True
        if patch.append_section:
            body = append_section(body, patch.append_section.header, patch.append_section.body)
            file_changed = True

        if not file_changed:
            return {"id": id, "commit": None, "fortified": fortified, "trail": self.forest.trail(id)}

        fm["updated"] = dt.date.today().isoformat()
        validate_frontmatter(fm, self.forest.dialect, strict_summary=False)
        content = serialize_node(fm, body)

        touched: list[tuple[Path, str]] = []
        assert node.path is not None
        touched.append((node.path, node.path.read_text(encoding="utf-8")))
        paths = [node.path]
        try:
            node.path.write_text(content, encoding="utf-8", newline="\n")
            if "summary" in patch.set_frontmatter:
                paths += self._propagate_summary(id, str(patch.set_frontmatter["summary"]), touched)
            commit = self.git.commit(paths, f"graft({id}): {patch.summary_line()}")
        except Exception:
            for path, original in reversed(touched):
                path.write_text(original, encoding="utf-8", newline="\n")
            raise

        self.catalog.upsert_node(self.forest.read(id))
        self.catalog.mark_stale(id)
        for path in paths[1:]:
            idx_id = self.forest.id_for(path)
            self.catalog.upsert_node(self.forest.read(idx_id))
        return {"id": id, "commit": commit, "fortified": fortified, "trail": self.forest.trail(id)}

    def _propagate_summary(
        self, child_id: str, new_summary: str, touched: list[tuple[Path, str]]
    ) -> list[Path]:
        """Summary changes propagate VERBATIM to every index replicating it."""
        changed_paths: list[Path] = []
        for row in self.catalog.conn.execute("SELECT id FROM nodes WHERE kind = 'branch'"):
            idx_id = row[0]
            idx_node = self.forest.read(idx_id)
            new_body, changed = indexer.sync_summary(idx_node.body, child_id, new_summary)
            if changed:
                assert idx_node.path is not None
                touched.append((idx_node.path, idx_node.path.read_text(encoding="utf-8")))
                idx_node.path.write_text(
                    indexer.render_index(idx_node, new_body), encoding="utf-8", newline="\n"
                )
                changed_paths.append(idx_node.path)
        return changed_paths

    def _require_writable(self) -> None:
        if not self.writable:
            raise VineError(E_READONLY, "this Vine is read-only", hint="Start without --readonly to write.")
