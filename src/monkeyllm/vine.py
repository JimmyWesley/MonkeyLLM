# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Vine — the navigation protocol (spec Part C).

Ten primitives over a markdown forest:
read: locate, look, move, pick, query, scan, sniff
write: plant, graft, tend (atomic, Git-committed, index-synced)

Every response fits its declared token budget; truncation is always
explicit (`truncated: true`), never silent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import inspect
import json
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path

from monkeyllm import indexer
from monkeyllm.canopy import CanopyIndex, cosine, rrf_fuse
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
from monkeyllm.fetch import PayloadCache, is_remote
from monkeyllm.forest import Forest, WriterLock
from monkeyllm.gitops import GitRepo
from monkeyllm.models import (
    MUTABLE_FRONTMATTER_FIELDS,
    GraftPatch,
    Link,
    NodeSpec,
    dataset_ddl,
    dataset_manual,
    validate_dataset_rows,
    validate_dataset_schema,
    validate_frontmatter,
    validate_summary,
)
from monkeyllm.parser import (
    ParsedNode,
    append_section,
    extract_outline,
    extract_section,
    parse_node,
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
BUDGET_SNIFF = 800
SNIFF_MAX_TERMS = 8
SNIFF_MAX_K = 20
SNIFF_MATCHES_PER_NODE = 3
SNIFF_SNIPPET_CHARS = 100  # ~25 tokens
PICK_MAX_BODY_TOKENS = 4000
NEIGHBOR_SUMMARY_TOKENS = 25
MAX_EDGES_SHOWN = 12
QUERY_DEFAULT_LIMIT = 200
QUERY_TIMEOUT_S = 2.0

_FORBIDDEN_SQL = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)
# tend (C.10) allows INSERT/UPDATE/DELETE but nothing structural or sneaky
_TEND_FORBIDDEN = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|DROP|ALTER|CREATE|VACUUM|REINDEX|BEGIN|COMMIT|TRANSACTION)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)
_HEADER_LINE_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


_FOLD_CACHE: dict[str, str] = {}


def _fold(text: str) -> str:
    """Length-preserving fold: lowercase + strip diacritics by keeping only
    the base character of each NFD decomposition. Positions found in the
    folded text map 1:1 back to the original (spec C.6b matching)."""
    cache = _FOLD_CACHE
    out = []
    for ch in text:
        f = cache.get(ch)
        if f is None:
            f = unicodedata.normalize("NFD", ch)[0].lower()
            cache[ch] = f
        out.append(f)
    return "".join(out)


# G.7: cheap detector for non-inline nodes (frontmatter `content:` marker);
# a body-text false positive only costs one harmless re-read via the parser
_CONTENT_MARKER_RE = re.compile(r"^content: (cached|reference)\s*$", re.MULTILINE)


def _raw_body(text: str) -> str:
    """Body of a node file without parsing the YAML frontmatter (same block
    boundaries as parser.split_frontmatter — sniff only needs the body)."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    nl = text.find("\n", end + 1)
    return text[nl + 1:].lstrip("\n") if nl != -1 else ""


def _sniff_snippet(line: str, pos: int) -> str:
    """Window of the line centered near the first occurrence (~25 tokens)."""
    line = line.rstrip()
    if len(line) <= SNIFF_SNIPPET_CHARS:
        return line.strip()
    start = max(0, pos - SNIFF_SNIPPET_CHARS // 3)
    end = min(len(line), start + SNIFF_SNIPPET_CHARS)
    start = max(0, end - SNIFF_SNIPPET_CHARS)
    out = line[start:end].strip()
    if start > 0:
        out = "…" + out
    if end < len(line):
        out += "…"
    return out


def _scan_lines(body: str, folded_terms: list[str]) -> list[list[list]]:
    """The memoizable unit of C.6b.1: for each term, every line it occurs
    in, as `[line_no, section, pos, line_text]`.

    Line granularity is not an implementation taste — the scan emits one
    match per line centred on the LEFTMOST term that hit it, so per-term
    results can only be recombined if each carries its own position.

    One pass over the body for all the terms: folding is proportional to
    the corpus, and doing it once per term made a three-term question fold
    the whole forest three times.
    """
    folded_body = _fold(body)
    out: list[list[list]] = [[] for _ in folded_terms]
    present = [t in folded_body for t in folded_terms]
    if not any(present):
        return out
    section: str | None = None
    # `_fold` preserves length, so a position found in the folded line
    # indexes the original line.
    for line_no, (line, folded) in enumerate(
        zip(body.splitlines(), folded_body.splitlines()), start=1
    ):
        h = _HEADER_LINE_RE.match(line)
        if h and len(h.group(1)) in (2, 3):
            section = h.group(2)
        for i, term in enumerate(folded_terms):
            if not present[i]:
                continue
            pos = folded.find(term)
            if pos != -1:
                out[i].append([line_no, section, pos, line])
    return out


def _sniff_lines(body: str, folded_term: str) -> list[list]:
    """One term's line records — the shape a memo row holds."""
    return _scan_lines(body, [folded_term])[0]


def _combine_lines(per_term: list[list[list]]) -> tuple[list[dict], set[int]]:
    """Rebuild `_sniff_body`'s answer from per-term line records.

    Same output, by construction: one match per line, ordered by line
    number, its snippet centred on the smallest position among the terms
    that hit that line — which is what `first_pos` means in the direct
    scan.
    """
    best: dict[int, list] = {}
    terms_hit: set[int] = set()
    for i, lines in enumerate(per_term):
        if lines:
            terms_hit.add(i)
        for line_no, section, pos, line in lines:
            prev = best.get(line_no)
            if prev is None:
                best[line_no] = [section, pos, line]
            elif pos < prev[1]:
                prev[1] = pos
    matches = [
        {"section": section, "line": line_no,
         "snippet": _sniff_snippet(line, pos)}
        for line_no, (section, pos, line) in sorted(best.items())
    ]
    return matches, terms_hit


def _sniff_body(body: str, folded_terms: list[str]) -> tuple[list[dict], set[int]]:
    """All matching lines of a body, each attributed to its H2/H3 section.
    Returns (matches, indexes of the terms that hit anywhere in the body)."""
    folded_body = _fold(body)
    if not any(t in folded_body for t in folded_terms):
        return [], set()
    matches: list[dict] = []
    terms_hit: set[int] = set()
    section: str | None = None
    # _fold preserves length and never produces line breaks, so the folded
    # lines stay 1:1 with the original lines.
    for line_no, (line, folded) in enumerate(
        zip(body.splitlines(), folded_body.splitlines()), start=1
    ):
        h = _HEADER_LINE_RE.match(line)
        if h and len(h.group(1)) in (2, 3):
            section = h.group(2)
        first_pos: int | None = None
        for i, term in enumerate(folded_terms):
            pos = folded.find(term)
            if pos != -1:
                terms_hit.add(i)
                if first_pos is None or pos < first_pos:
                    first_pos = pos
        if first_pos is None:
            continue
        matches.append(
            {"section": section, "line": line_no, "snippet": _sniff_snippet(line, first_pos)}
        )
    return matches, terms_hit


def _traced(fn):
    # Only primitives whose first argument IS a node id may report one.
    # `locate("payroll")` passes a query string positionally, and recording
    # that as `id` filed a search term where every reader expects a node —
    # harmless to Part D's metrics (a query never matches an answer node),
    # but a lie to anything that displays a trace.
    takes_id = list(inspect.signature(fn).parameters)[1:2] == ["id"]

    def wrapper(self: "Vine", *args, **kwargs):
        t0 = time.perf_counter()
        result = fn(self, *args, **kwargs)
        elapsed = (time.perf_counter() - t0) * 1000
        node_id = kwargs.get("id") or (args[0] if takes_id and args else None)
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
        hybrid_locate: bool = False,
    ):
        self.forest = Forest(root)
        self.catalog = Catalog(self.forest)
        self.trails = Trails(self.forest.derived_dir)
        self.payload_cache = PayloadCache(self.forest.derived_dir)
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
        # unchanged otherwise — architecture doc §3).
        self.embedder = embedder
        self.canopy = CanopyIndex.load(self.forest.derived_dir)
        # The Gauntlet's goal (Part K): the vector of the most recent hunt.
        # `locate` embeds the query anyway when the dense layer is on, so
        # carrying it costs one embedding per hunt instead of one per hop.
        # Entry search stays lexical unless explicitly asked otherwise.
        # Measurement (Part K changelog) showed fusing a dense ranker into
        # an already-correct BM25 *degrades* it — so the dense layer being
        # available must not imply using it here.
        # Public and writable for the same reason `embedder` is (J.0): a host
        # offering the per-call switch K.3 requires must be able to flip it
        # without forking the pool. Off is the default and stays the default.
        self.hybrid_locate = hybrid_locate
        self._goal: list[float] | None = None
        self._goal_text: str | None = None

    @property
    def dense_ready(self) -> bool:
        """Whether a usable vector layer exists. NOT whether to use it: the
        two consumers — entry search and the Gauntlet — decide separately,
        because measurement says one is helped by it and the other harmed."""
        return (
            self.embedder is not None
            and self.canopy is not None
            and len(self.canopy) > 0
            # K.4: comparing a query embedded by one model against vectors
            # produced by another compares two unrelated spaces. That does
            # not rank badly, it ranks meaninglessly — and it fails silently,
            # because a dot product always returns a number. A mismatched
            # index is therefore treated as no index at all.
            and self.canopy.model == self.embedder.model
        )

    @property
    def hybrid(self) -> bool:
        """RRF fusion in `locate`. Off unless asked for, on purpose."""
        return self.hybrid_locate and self.dense_ready

    @property
    def canopy_status(self) -> dict:
        """Why the dense layer is or is not active (K.4), for validation and
        for any surface that shows index health."""
        index_model = self.canopy.model if self.canopy is not None else None
        query_model = self.embedder.model if self.embedder is not None else None
        if self.embedder is None:
            state = "no-embedder"
        elif self.canopy is None or len(self.canopy) == 0:
            state = "no-index"
        elif index_model != query_model:
            state = "model-mismatch"
        else:
            state = "active"
        return {"state": state, "active": state == "active",
                "index_model": index_model, "query_model": query_model,
                "vectors": len(self.canopy) if self.canopy is not None else 0,
                # K.4 (v0.42): what a refresh would cost, before it runs. A
                # layer quietly behind is indistinguishable from a current
                # one, and since v0.42 no read pays this debt down by
                # surprise — somebody has to choose to.
                "stale": len(self.catalog.stale_ids())}

    # -- the Gauntlet (Part K) ---------------------------------------------

    def _goal_for(self, toward: str | None, enabled: bool | None):
        """The goal vector for this call, or None to leave the order alone.

        Returns None whenever ANY precondition fails (K.1), because the
        contract is that an absent Gauntlet is not a degraded mode — it is
        v0.20 behaviour, byte for byte. Every caller therefore only has to
        check for None.
        """
        if enabled is False or not self.dense_ready:
            return None
        if toward:
            # An explicit goal costs its own embedding — once per distinct
            # text, since v0.42 (K.6). That is the price of testability, and
            # it is why it is not the default path.
            return self.embed_query(toward), toward
        if self._goal_text is None:
            return None
        if self._goal is None:
            # Paid once, on the first hop of the hunt — not in `locate`, and
            # never at all for a hunt that only ever reads the entry list.
            # Nothing is re-embedded here but the goal itself (K.2, v0.42).
            self._goal = self.embed_query(self._goal_text)
        return self._goal, self._goal_text

    def _rank_frontier(self, items, goal, id_of=lambda x: x["id"],
                       signal_of=lambda x: 0.0):
        """Order a frontier by proximity to the goal, in place.

        Proximity decides and the existing signal — heat, degree — breaks
        near-ties: rounding the cosine to three places makes "as close as
        each other" mean something, so a node the colony has found useful
        before still wins between equals. Heat stays a memory of past hunts
        (Part H depends on that); it simply stops being the only voice.
        """
        vectors = {i: v for i, v in zip(self.canopy.ids, self.canopy.vectors)}
        def key(item):
            vec = vectors.get(id_of(item))
            prox = cosine(goal, vec) if vec is not None else -1.0
            return (-round(prox, 3), -signal_of(item))
        items.sort(key=key)

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

    def embed_query(self, text: str) -> list[float]:
        """Embed ONE caller-supplied text, through the K.6 memo.

        `embed(model, text)` is pure, so the round trip is owed once per
        distinct question rather than once per asking. Node vectors do not
        come through here: the Canopy index is their home, and a second
        copy would be a second answer to "what is this node's vector".
        """
        key = " ".join(str(text).split())
        model = self.embedder.model
        cached = self.catalog.embed_memo(model, key)
        if cached is not None:
            self.catalog.embed_memo_touch(model, key)
            return cached
        vec = self.embedder.embed([text])[0]
        self.catalog.embed_memo_store(model, key, vec)
        return vec

    def refresh_canopy(self) -> dict:
        """Embed the nodes marked stale by plant/graft/ingest (J.13.4).

        Maintenance, never a read: this used to run inside `locate`, which
        meant the question that happened to arrive after an ingest paid for
        every document of it — unbounded work inside the primitive with the
        tightest budget in the spec (F.6). It is triggered now, and what it
        will cost is reported before it runs (K.4's `stale`).
        """
        if self.embedder is None:
            raise VineError(E_SCHEMA, "refreshing the dense layer needs an embedder",
                            hint="Bind an embedding model, then refresh.")
        if not self.dense_ready:
            raise VineError(
                E_SCHEMA, "the dense layer is not usable, so a partial "
                          "re-embed would leave it in two spaces at once",
                hint="Build the index first (K.4): a model change requires a "
                     "full build, never a refresh.")
        stale = self.catalog.stale_ids()
        self._refresh_canopy()
        return {"refreshed": len(stale), **self.canopy_status}

    def _refresh_canopy(self) -> None:
        """The re-embed itself. Called by `refresh_canopy` and by nothing in
        a read path — see K.2 as amended in v0.42."""
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

    def warm(self) -> None:
        """Pay the first call's start-up cost before there is a first call.

        Opening a forest is not free and neither is the first query through
        it — measured on a fresh process, `locate` costs several times what
        it costs from the second call on, all of it SQLite waking up. That
        is a fact about the process, not about the forest, and a caller who
        happens to be first should not be shown it as the cost of the call.

        Storage only, and never a primitive: a warm-up that went through
        `locate` would append a trace event and deposit heat, so the server
        would be forging the pheromone the Ranger later reads as evidence of
        where people went (Part D, Part H). Bodies are not touched either —
        that is the whole corpus off disk, which is a different trade.
        """
        self.catalog.warm()
        self.trails.warm()

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
        # The hunt's goal is REMEMBERED here and embedded later, on the first
        # hop that actually needs it (K.2). Embedding it now would put a
        # network round trip inside `locate`, whose budget is 100 ms p95 —
        # and would charge it to every hunt that never leaves the entry list.
        self._goal, self._goal_text = None, query
        if self.hybrid:
            # The query, and nothing else (K.2 as amended in v0.42). Node
            # vectors are refreshed by J.13.4, not by whoever asked next.
            qvec = self.embed_query(query)
            self._goal = qvec
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
    def look(self, id: str, fields: list[str] | None = None,
             gauntlet: bool | None = None, toward: str | None = None) -> dict:
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
        _defer_heat_pop = edges_out + edges_in
        # Part K: condition the frontier BEFORE the cap, which is the whole
        # point — reordering after the cut cannot recover what the cut hid.
        #
        # But not when the caller asked for fields that contain no frontier:
        # the `fields` filter below would drop the order anyway, and the goal
        # is embedded lazily, so ranking a discarded list meant a network
        # round trip for nothing. `harvest` does exactly that — one
        # `look(id, fields=["summary"])` per result — and it was charging
        # every harvest and every answer ~150 ms of embedding for output no
        # caller ever sees.
        wants_frontier = not fields or bool(
            {"edges_out", "edges_in", "frontier"} & set(fields))
        goal = self._goal_for(toward, gauntlet) if wants_frontier else None
        if goal is not None:
            self._rank_frontier(edges_out, goal[0],
                                id_of=lambda e: e["target"],
                                signal_of=lambda e: e["_heat"])
            self._rank_frontier(edges_in, goal[0],
                                id_of=lambda e: e["source"],
                                signal_of=lambda e: e["_heat"])
            digest["frontier"] = {"ranked": True, "toward": goal[1]}
        for e in _defer_heat_pop:
            e.pop("_heat", None)
        digest["edges_out"] = edges_out[:MAX_EDGES_SHOWN]
        digest["edges_in"] = edges_in[:MAX_EDGES_SHOWN]

        if row["kind"] == "branch":
            children = [
                {"id": c["id"], "summary": truncate_text(c["summary"], NEIGHBOR_SUMMARY_TOKENS)}
                for c in self.catalog.children(id)
            ]
            digest["children"] = children
            cross = extract_section(node.body, "Cross trails")
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

    def _dataset_db(self, node: ParsedNode, *, for_write: bool = False) -> Path:
        payload = node.frontmatter.get("payload")
        if is_remote(payload):
            if for_write:
                raise VineError(
                    E_QUERY_FORBIDDEN,
                    f"remote payload is read-only: {payload}",
                    hint="Datasets are local-first (spec G.9.4): bring the .db "
                         "local to tend it — editing a cached copy would fork it.",
                )
            # G.9: download-on-first-use, hash-validated, LRU-touched (H.6)
            return self.payload_cache.get(
                str(payload), node.frontmatter.get("payload_hash"))
        db = self.forest.payload_path(node)
        if not db.is_file():
            raise VineError(E_NOT_FOUND, f"payload missing: {db.name}")
        return db

    def prefetch(self, scope: str = "_index") -> dict:
        """G.9.5 — the parachute warms the camp: after locate drops the monkey
        on a region, pull every remote payload under it in one sweep so the
        following sniff/query hops run at local speed."""
        scope = scope.strip().strip("/")
        if scope in ("", "_index"):
            prefix = ""
        elif scope.endswith("/_index"):
            prefix = scope[: -len("_index")]
        else:
            prefix = scope + "/"
        fetched, local, errors = [], 0, []
        for row in self.catalog.conn.execute(
            "SELECT id, payload, payload_hash FROM nodes WHERE payload IS NOT NULL"
        ).fetchall():
            if prefix and not row["id"].startswith(prefix):
                continue
            if not is_remote(row["payload"]):
                local += 1
                continue
            try:
                self.payload_cache.get(row["payload"], row["payload_hash"])
                fetched.append(row["id"])
            except VineError as e:
                errors.append(f"{row['id']}: {e.message}")
        return {"scope": scope or "_index", "fetched": fetched,
                "already_local": local, "errors": errors}

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
        manual_section = extract_section(node.body, "Query manual") or ""
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
    def move(self, id: str, rel: str | None = None, direction: str = "out",
             gauntlet: bool | None = None, toward: str | None = None) -> dict:
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
        goal = self._goal_for(toward, gauntlet)
        if goal is not None:
            self._rank_frontier(neighbors, goal[0],
                                signal_of=lambda n: n.get("heat", 0.0))
        payload = {"neighbors": neighbors, "truncated": False}
        if goal is not None:
            payload["frontier"] = {"ranked": True, "toward": goal[1]}
        return shrink_list_to_budget(payload, "neighbors", BUDGET_MOVE)

    # =======================================================================
    # C.4 pick — harvest the banana
    # =======================================================================

    def _resolved_body(self, node: ParsedNode) -> str:
        """G.7 lazy FLESH resolution: cached -> _derived/bodies, reference ->
        the source file itself. Inline nodes return their own body."""
        mode = node.frontmatter.get("content")
        if mode == "cached":
            f = self.forest.body_cache_path(node.id)
            if not f.is_file():
                raise VineError(
                    E_NOT_FOUND,
                    f"cached body missing for {node.id}",
                    hint="Re-run `vine sync` with the sources reachable to rebuild "
                         "_derived/bodies. The map (locate/look/scan) keeps working.",
                )
            return f.read_text(encoding="utf-8")
        if mode == "reference":
            root = self.forest.gardener_source_root()
            sp = node.frontmatter.get("source_path")
            f = (root / str(sp)) if root and sp else None
            if f is not None and not f.resolve().is_relative_to(root.resolve()):
                # G.7: a reference body lives UNDER the adopted source root.
                # `source_path` is ordinary frontmatter (models.py allows
                # extras), so a planted `../../` would otherwise turn a read
                # primitive into arbitrary host reads with the Vine's
                # authority — reported as if the node owned the file.
                raise VineError(
                    E_NOT_FOUND,
                    f"reference body unreachable for {node.id}",
                    hint="source_path leaves the adopted source root. The map "
                         "(locate/look/scan) keeps working.",
                )
            if f is None or not f.is_file():
                raise VineError(
                    E_NOT_FOUND,
                    f"reference body unreachable for {node.id}",
                    hint=f"source file: {f}. The map (locate/look/scan) keeps working.",
                )
            return f.read_text(encoding="utf-8", errors="replace")
        return node.body

    @_traced
    def pick(self, id: str, section: str | None = None) -> dict:
        node = self.forest.read(id)
        body, outline = node.body, node.outline
        if node.frontmatter.get("content") in ("cached", "reference"):
            body = self._resolved_body(node)
            _, _, outline = extract_outline(body)
        body_tokens = estimate_tokens(body)
        if section:
            content = extract_section(body, section)
            if content is None:
                raise VineError(
                    E_NOT_FOUND,
                    f"section '{section}' not found in {id}",
                    hint=f"Available sections: {outline}",
                )
            return {
                "id": id,
                "title": node.title,
                "section": section,
                "body": content,
                "body_tokens": estimate_tokens(content),
                "truncated": False,
            }
        if body_tokens > PICK_MAX_BODY_TOKENS:
            return {
                "id": id,
                "title": node.title,
                "outline": outline,
                "body_tokens": body_tokens,
                "truncated": True,
                "hint": "Body exceeds 4000 tokens. Use section=<header> to harvest one section.",
            }
        return {
            "id": id,
            "title": node.title,
            "body": body,
            "body_tokens": body_tokens,
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
        gauntlet: bool | None = None,
        toward: str | None = None,
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
        # Part K: 60 children cut to 14 by the budget, ordered by heat, is the
        # forager seeing a quarter of the frontier chosen by something that
        # has nothing to do with the question. Rank first, then cut.
        goal = self._goal_for(toward, gauntlet)
        if goal is not None:
            self._rank_frontier(out, goal[0], signal_of=lambda x: x["_heat"])
        for item in out:
            item.pop("_heat", None)
        payload = {"nodes": out[:limit], "truncated": len(out) > limit}
        if goal is not None:
            payload["frontier"] = {"ranked": True, "toward": goal[1]}
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
    # C.6b sniff — the tracker (literal search over bodies)
    # =======================================================================

    @_traced
    def sniff(
        self,
        terms: str | list[str],
        scope: str | None = None,
        k: int = 5,
        type_filter: str | None = None,
    ) -> dict:
        if isinstance(terms, str):
            terms = [terms]
        if not isinstance(terms, list) or not terms or len(terms) > SNIFF_MAX_TERMS:
            raise VineError(
                E_SCHEMA,
                f"terms must be 1..{SNIFF_MAX_TERMS} literal strings",
                hint="Pass exact terms (codes, names, numbers); regex is not supported.",
            )
        folded_terms = []
        for t in terms:
            ft = _fold(str(t)).strip()
            if len(ft) < 2:
                raise VineError(
                    E_SCHEMA,
                    f"term too short after normalization: {t!r}",
                    hint="Literal terms need >= 2 characters; regex is not supported.",
                )
            folded_terms.append(ft)

        # scope: branch -> physical subtree; banana -> that single node
        # (grep-within-the-node, the natural follow-up to locate/look).
        if scope is not None and not isinstance(scope, str):
            raise VineError(
                E_SCHEMA,
                "scope must be a single node or branch id (string)",
                hint="Pass scope as one string: a branch id or a node id, not a list.",
            )
        prefix = None
        only_id = None
        if scope:
            scope = scope.strip().strip("/")
            row = self.catalog.get(scope)
            if row is not None and row["kind"] == "banana":
                only_id = scope
            else:
                scope_id = scope if scope == "_index" or scope.endswith("/_index") else f"{scope}/_index"
                self._row_or_raise(scope_id)
                if scope_id != "_index":
                    prefix = scope_id[: -len("_index")]  # "<branch>/_index" -> "<branch>/"

        k = min(max(1, k), SNIFF_MAX_K)
        # The scope is a WHERE, never a Python skip. Fetching every row to
        # discard all but one made a single-node sniff cost the whole
        # forest — and the sweep (C.6c) issues one per term per result.
        where: list[str] = []
        params: list = []
        if only_id:
            where.append("{n}id = ?")
            params.append(only_id)
        elif prefix:
            # substr, not LIKE: '_' is a single-character wildcard there and
            # node ids are full of them ('_index'), so LIKE would silently
            # widen the scope the caller asked to narrow.
            where.append("substr({n}id, 1, ?) = ?")
            params.extend([len(prefix), prefix])
        if type_filter:
            where.append("{n}type = ?")
            params.append(type_filter)
        clauses = [c.format(n="") for c in where]
        rows = self.catalog.conn.execute(
            "SELECT * FROM nodes"
            + (" WHERE " + " AND ".join(clauses) if clauses else "")
            + " ORDER BY id", params).fetchall()
        # C.6b.1: what the scan already knows, per term, still valid by hash.
        memo = [self.catalog.sniff_memo(t, where, params) for t in folded_terms]
        learned: list[tuple[str, str, str, str]] = []
        scanned = 0
        hits = []
        for r in rows:
            nid = r["id"]
            body_hash = r["body_hash"]
            remembered = [m.get(nid) for m in memo]
            if body_hash and all(lines is not None for lines in remembered):
                # Not one file opened for this node: the terms were all
                # scanned against this exact body before.
                scanned += 1
                matches, terms_hit = _combine_lines(
                    [json.loads(lines) for lines in remembered])
            else:
                try:
                    text = self.forest.path_for(nid).read_text(encoding="utf-8")
                except (VineError, OSError):
                    continue  # validate() reports broken nodes; sniff skips them
                body = _raw_body(text)
                if _CONTENT_MARKER_RE.search(text):
                    # G.7: non-inline node — grep the resolved FLESH instead
                    # of the stub; an unreachable body degrades to "no match".
                    # Its hash is empty by construction, so it is never
                    # memoized: the `.md` this hash covers is not this text.
                    try:
                        body = self._resolved_body(self.forest.read(nid))
                    except VineError:
                        continue
                scanned += 1
                if body_hash:
                    per_term = _scan_lines(body, folded_terms)
                    learned.extend(
                        (t, nid, body_hash, json.dumps(per_term[i]))
                        for i, t in enumerate(folded_terms)
                        if remembered[i] is None)
                    matches, terms_hit = _combine_lines(per_term)
                else:
                    matches, terms_hit = _sniff_body(body, folded_terms)
            if not matches:
                continue
            strength = len(terms_hit) / len(folded_terms)
            heat = self._heat(nid)
            hits.append(
                {
                    "id": nid,
                    "type": r["type"],
                    "title": r["title"],
                    "trail": json.loads(r["trail"]),
                    "score": round(strength * (1 + self.alpha * heat), 4),
                    "heat": heat,
                    "match_count": len(matches),
                    "truncated_matches": len(matches) > SNIFF_MATCHES_PER_NODE,
                    "matches": matches[:SNIFF_MATCHES_PER_NODE],
                }
            )
        # After the answer is decided, never before it: what the scan learned
        # is latency for the next caller, and it must not be able to change
        # this one's result.
        self.catalog.sniff_memo_store(learned)
        hits.sort(key=lambda h: (h["score"], h["match_count"]), reverse=True)
        payload = {
            "results": hits[:k],
            "scanned_nodes": scanned,
            "truncated": len(hits) > k,
        }
        return shrink_list_to_budget(payload, "results", BUDGET_SNIFF)

    # =======================================================================
    # C.10 tend — dataset writes (spec v0.7, Phase 2: the living bank)
    # =======================================================================

    @_traced
    def tend(self, id: str, sql: str) -> dict:
        self._require_writable()
        with self._write_mutex:
            return self._tend(id, sql)

    def _tend(self, id: str, sql: str) -> dict:
        row = self._row_or_raise(id)
        if row["type"] != "dataset" or row["payload_type"] != "sqlite":
            raise VineError(
                E_QUERY_FORBIDDEN,
                f"node {id} is not a sqlite dataset (type={row['type']})",
                hint="tend() only works on type:dataset nodes with payload_type:sqlite.",
            )
        sql = sql.strip().rstrip(";").strip()
        if ";" in sql:
            raise VineError(E_QUERY_FORBIDDEN, "only a single SQL statement is allowed")
        first = sql.split(None, 1)[0].upper() if sql else ""
        if first not in ("INSERT", "UPDATE", "DELETE"):
            raise VineError(
                E_QUERY_FORBIDDEN,
                "tend accepts INSERT, UPDATE or DELETE only",
                hint="Reads go through query(); schema changes are the Gardener's job.",
            )
        m = _TEND_FORBIDDEN.search(sql)
        if m:
            raise VineError(E_QUERY_FORBIDDEN, f"forbidden keyword: {m.group(1).upper()}")
        if first in ("UPDATE", "DELETE") and not re.search(r"\bWHERE\b", sql, re.IGNORECASE):
            raise VineError(
                E_QUERY_FORBIDDEN,
                f"{first} without WHERE is not allowed (mass-wipe guard)",
                hint="Target rows explicitly; full rewrites are the Gardener's job.",
            )

        node = self.forest.read(id)
        db = self._dataset_db(node, for_write=True)
        conn = sqlite3.connect(db)
        deadline = time.monotonic() + QUERY_TIMEOUT_S
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        t0 = time.perf_counter()
        try:
            cur = conn.execute(sql)
            conn.commit()
            rows_affected = cur.rowcount
        except sqlite3.OperationalError as e:
            conn.rollback()
            if "interrupted" in str(e).lower():
                raise VineError(E_TIMEOUT, f"tend exceeded {QUERY_TIMEOUT_S}s") from e
            raise VineError(E_QUERY_FORBIDDEN, f"SQL error: {e}") from e
        except sqlite3.Error as e:
            conn.rollback()
            raise VineError(E_QUERY_FORBIDDEN, f"SQL error: {e}") from e
        finally:
            conn.close()
        elapsed_ms = (time.perf_counter() - t0) * 1000

        # audit trail (spec C.10): the .md records what/when via payload_hash;
        # the binary itself never enters git (A.3.1)
        new_hash = hashlib.sha256(db.read_bytes()).hexdigest()
        fm = dict(node.frontmatter)
        fm["payload_hash"] = new_hash
        fm["updated"] = dt.date.today().isoformat()
        content = serialize_node(fm, node.body)
        assert node.path is not None
        original = node.path.read_text(encoding="utf-8")
        try:
            node.path.write_text(content, encoding="utf-8", newline="\n")
            commit = self.git.commit(
                [node.path], f"tend({id}): {first} {rows_affected} row(s)"
            )
        except Exception:
            # payload already committed: restore the .md and surface the error;
            # the hash drift is exactly what `vine validate` warns about
            node.path.write_text(original, encoding="utf-8", newline="\n")
            raise
        self.catalog.upsert_node(self.forest.read(id))
        return {
            "id": id,
            "rows_affected": rows_affected,
            "payload_hash": new_hash,
            "commit": commit,
            "elapsed_ms": round(elapsed_ms, 2),
        }

    # =======================================================================
    # C.7 plant — atomic create (file + index + git)
    # =======================================================================

    @_traced
    def plant(self, node: dict | NodeSpec) -> dict:
        self._require_writable()
        spec = node if isinstance(node, NodeSpec) else NodeSpec.model_validate(node)
        with self._write_mutex:
            return self._plant(spec)

    def _prepare_dataset_spec(self, spec: NodeSpec) -> None:
        """C.7.1: the schema is data, never DDL — validate it whole and
        default the payload fields before the frontmatter is built."""
        if spec.type != "dataset":
            raise VineError(
                E_SCHEMA,
                f"schema is only valid on type:dataset nodes (got type={spec.type})",
            )
        assert spec.table_schema is not None
        validate_dataset_schema(spec.table_schema)
        if spec.rows:
            validate_dataset_rows(spec.table_schema, spec.rows)
        if spec.payload is None:
            spec.payload = spec.id.rsplit("/", 1)[-1] + ".db"
        if "/" in spec.payload or "\\" in spec.payload or not spec.payload.endswith(".db"):
            raise VineError(
                E_SCHEMA,
                f"payload must be a bare filename ending in .db: {spec.payload}",
            )
        spec.payload_type = spec.payload_type or "sqlite"
        if spec.payload_type != "sqlite":
            raise VineError(E_SCHEMA, "schema requires payload_type: sqlite")

    def _plant(self, spec: NodeSpec) -> dict:
        if spec.rows and spec.table_schema is None:
            raise VineError(E_SCHEMA, "rows require a schema (C.7.1 rule 7)")
        if spec.table_schema is not None:
            self._prepare_dataset_spec(spec)
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

        # C.7.1 payload birth: create the SQLite BEFORE the .md so the hash
        # lands in the frontmatter; the binary itself never enters git (A.3.1)
        payload_db: Path | None = None
        if spec.table_schema is not None:
            assert spec.payload is not None
            payload_db = self.forest.path_for(spec.id).parent / spec.payload
            if payload_db.exists():
                raise VineError(
                    E_SCHEMA,
                    f"payload already exists: {spec.payload}",
                    hint="A newborn dataset never overwrites an existing payload.",
                )
            try:
                payload_db.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(payload_db)
                try:
                    for stmt in dataset_ddl(spec.table_schema):
                        conn.execute(stmt)
                    # C.7.1 rule 7: initial rows go in parameterized — values
                    # are data, never SQL text
                    for tname, table_rows in (spec.rows or {}).items():
                        if table_rows:
                            ph = ", ".join("?" * len(spec.table_schema[tname].columns))
                            conn.executemany(
                                f"INSERT INTO {tname} VALUES ({ph})",
                                [tuple(r) for r in table_rows],
                            )
                    conn.commit()
                finally:
                    conn.close()
                fm["payload_hash"] = hashlib.sha256(payload_db.read_bytes()).hexdigest()
            except sqlite3.Error as e:
                payload_db.unlink(missing_ok=True)
                raise VineError(E_SCHEMA, f"dataset birth failed: {e}") from e
            except Exception:
                payload_db.unlink(missing_ok=True)
                raise

        body = spec.body.strip() or f"# {spec.title}"
        if not body.lstrip().startswith("#"):
            body = f"# {spec.title}\n\n{body}"
        if spec.table_schema is not None and extract_section(body, "Query manual") is None:
            body = f"{body.rstrip()}\n\n{dataset_manual(spec.table_schema)}"
        content = serialize_node(fm, body)

        parent_node = self.forest.read(spec.parent)
        new_parent_body = indexer.add_entry(
            parent_node, spec.id, spec.summary, is_branch=(spec.type == "branch")
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
            if payload_db is not None:
                payload_db.unlink(missing_ok=True)
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

        # C.8 v0.43: one patch states one truth about the body — a whole-body
        # replace alongside section surgery is refused, never resolved by
        # precedence. And an index's body is the indexer's render: a
        # hand-written one would stop parsing as a map.
        if patch.replace_body is not None:
            if patch.replace_section or patch.append_section:
                raise VineError(
                    E_SCHEMA,
                    "replace_body cannot be combined with section operations",
                    hint="Send the whole body, or section patches — not both.",
                )
            if id == "_index" or id.endswith("/_index"):
                raise VineError(
                    E_SCHEMA,
                    f"'{id}' is an index: its body is the indexer's render",
                    hint="Indexes accept section operations only.",
                )

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
            if link.rel == "discovered-shortcut":
                extra.setdefault("confidence", 0.5)
                extra.setdefault("discovered_by", "agent")
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

        if patch.replace_body is not None:
            body = patch.replace_body
            file_changed = True
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
        if patch.replace_body is not None:
            # The write validates before it commits (v0.43): whatever the
            # next read would refuse is refused now, while the file on disk
            # is still the old one.
            parse_node(id, content)

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
        # Sub-branch entries carry a coverage suffix that the rewrite must
        # preserve (A.5, spec v0.13).
        child_row = self.catalog.get(child_id)
        coverage = None
        if child_row is not None and child_row["kind"] == "branch":
            coverage = child_row["coverage"] or None
        for row in self.catalog.conn.execute("SELECT id FROM nodes WHERE kind = 'branch'"):
            idx_id = row[0]
            idx_node = self.forest.read(idx_id)
            new_body, changed = indexer.sync_summary(
                idx_node.body, child_id, new_summary, coverage)
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
