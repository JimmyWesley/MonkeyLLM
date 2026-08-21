# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Catalog (_derived/catalog.db, spec C.6.1).

One row per node: frontmatter + trail + degree. FTS5 over
title/aliases/tags/summary serves the lexical side of locate().
Never the source of truth: rebuildable from files via reindex().
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import struct
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from monkeyllm.forest import Forest, tune_derived
from monkeyllm.parser import ParsedNode

# G.7 policies whose scanned text is NOT the node's own `.md` body: a
# `reference` body is the source file, a `cached` one lives in
# `_derived/bodies`. Both can change with the `.md` byte-identical, so the
# hash below would say "unchanged" about text it never read.
_FOREIGN_BODY = ("cached", "reference")


def body_hash_of(node: ParsedNode) -> str:
    """The C.6.1 digest of the body **as `sniff` would scan it**, or `''`
    for a node whose body the `.md` does not carry.

    Empty is the honest answer, not a fallback: it reads as a miss
    everywhere (C.6b.1), which keeps those nodes on the direct scan
    forever instead of memoizing a body nobody hashed.
    """
    if str(node.frontmatter.get("content") or "") in _FOREIGN_BODY:
        return ""
    return hashlib.sha256(node.body.encode("utf-8")).hexdigest()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,              -- 'banana' | 'branch'
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    aliases TEXT NOT NULL DEFAULT '[]',
    created TEXT,
    updated TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    source TEXT,
    entity_kind TEXT,
    payload TEXT,
    payload_type TEXT,
    payload_hash TEXT,
    parent TEXT,
    trail TEXT NOT NULL DEFAULT '[]',
    coverage TEXT,
    body_tokens INTEGER NOT NULL DEFAULT 0,
    outline TEXT NOT NULL DEFAULT '[]',
    stale INTEGER NOT NULL DEFAULT 0,
    body_hash TEXT NOT NULL DEFAULT '',
    origin TEXT
);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
-- C.13 (v0.52): the two clocks a read may be windowed by. The predicates
-- are bare range comparisons on these columns for exactly this reason —
-- a `substr()` around one computes the same answer and cannot use the
-- index, which is the whole difference on a forest worth windowing.
CREATE INDEX IF NOT EXISTS idx_nodes_created ON nodes(created);
CREATE INDEX IF NOT EXISTS idx_nodes_updated ON nodes(updated);

-- C.6b.1: the memoized literal scan. One row per (folded term, node),
-- valid while `body_hash` still matches the node's. `lines` is the
-- complete per-line record, '[]' meaning "scanned, matched nothing" —
-- the negative is the whole point, since nearly every node is one.
CREATE TABLE IF NOT EXISTS sniff_memo (
    term TEXT NOT NULL,
    node_id TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    lines TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (term, node_id)
);
CREATE INDEX IF NOT EXISTS idx_sniff_memo_node ON sniff_memo(node_id);

-- K.6: one text embedded by one model. Caller-supplied texts only —
-- queries and `toward` goals. A node's vector lives in the Canopy index,
-- and storing it here too would be a second answer to the same question.
CREATE TABLE IF NOT EXISTS embed_memo (
    model TEXT NOT NULL,
    text TEXT NOT NULL,
    vector BLOB NOT NULL,
    used TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (model, text)
);

CREATE TABLE IF NOT EXISTS edges (
    src TEXT NOT NULL,
    rel TEXT NOT NULL,
    dst TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (src, rel, dst)
);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);

CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    id UNINDEXED, title, aliases, tags, summary,
    tokenize = "unicode61 remove_diacritics 2"
);

-- C.15 (v0.58): the waymarks. DERIVED from `moved_from` on passports at
-- upsert time — the files are the truth and a reindex rebuilds this.
CREATE TABLE IF NOT EXISTS moves (
    old_id TEXT PRIMARY KEY,
    new_id TEXT NOT NULL
);
"""


class Catalog:
    def __init__(self, forest: Forest):
        self.forest = forest
        forest.derived_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = forest.derived_dir / "catalog.db"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        tune_derived(self.conn)
        self.conn.executescript(SCHEMA_SQL)
        # A catalog written before link-level confidence was indexed is a
        # valid catalog: it is derived, so the column is added in place and
        # filled by the next reindex rather than forcing one.
        if "confidence" not in {
            r[1] for r in self.conn.execute("PRAGMA table_info(edges)")
        }:
            self.conn.execute(
                "ALTER TABLE edges ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0")
        # Same bargain for the body hash (C.6.1, v0.40): the column is added
        # in place and stays empty until the next write or reindex fills it.
        # Empty is a miss, never a match — a blank hash that compared equal
        # would serve stale snippets forever.
        if "body_hash" not in {
            r[1] for r in self.conn.execute("PRAGMA table_info(nodes)")
        }:
            self.conn.execute(
                "ALTER TABLE nodes ADD COLUMN body_hash TEXT NOT NULL DEFAULT ''")
        # Same bargain for origin (A.3, v0.57): added in place, filled by
        # the next write or reindex — a catalog is derived, never migrated.
        if "origin" not in {
            r[1] for r in self.conn.execute("PRAGMA table_info(nodes)")
        }:
            self.conn.execute("ALTER TABLE nodes ADD COLUMN origin TEXT")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def warm(self) -> None:
        """Fault in the pages a search will want, without being a search.

        The first `locate` of a process is several times slower than every
        one after it, and none of that is the corpus: it is SQLite opening
        the FTS index, faulting b-tree pages off disk and compiling the
        ranking statement. A caller should not pay for the process having
        just started, so it is paid here instead.

        The probe term is taken from the corpus rather than written down,
        which is what keeps this forest-agnostic: a hardcoded word would be
        vocabulary in the engine, and would match nothing in a forest that
        does not speak that language. Read-only throughout — a warm-up that
        wrote would be inventing traffic.
        """
        self.conn.execute("SELECT count(*) FROM nodes").fetchone()
        self.conn.execute("SELECT count(*) FROM edges").fetchone()
        row = self.conn.execute(
            "SELECT title FROM nodes WHERE title != '' LIMIT 1").fetchone()
        # Through `fts_search`, not around it: the point is to compile and
        # run the statement `locate` runs, not a cheaper cousin of it.
        term = next((t for t in (row["title"] or "").split() if t), None) if row else None
        if term:
            self.fts_search(term, limit=1)

    # -- write -------------------------------------------------------------

    # -- counts and clocks (C.1.1, C.13) ------------------------------------

    def count_nodes(self, where: list[str] | None = None,
                    params: list | None = None) -> int:
        """How many nodes carry curated scent (C.1.1, v0.52).

        Asked only when an entry search came back empty, so the caller can
        tell "nothing matched" from "there was nothing to match" — and,
        with a window's predicate (C.13.2), "nothing was in that window"
        from "the window held material and the question missed it".
        """
        sql = "SELECT count(*) FROM nodes"
        if where:
            sql += " WHERE " + " AND ".join(c.format(n="") for c in where)
        return int(self.conn.execute(sql, params or []).fetchone()[0])

    def date_column(self, field: str, where: list[str] | None = None,
                    params: list | None = None) -> list[str]:
        """Every node's date, for the C.13.3 fold.

        Ids are not returned: this answers "when", never "what", and a
        count is the only thing built from it.
        """
        if field not in ("created", "updated"):  # never interpolated blind
            raise ValueError(f"not a date column: {field}")
        sql = f"SELECT {field} FROM nodes"
        if where:
            sql += " WHERE " + " AND ".join(c.format(n="") for c in where)
        return [r[0] for r in self.conn.execute(sql, params or []).fetchall()]

    def date_buckets(self, field: str, granularity: str,
                     where: list[str] | None = None,
                     params: list | None = None) -> list[tuple]:
        """(period_start, nodes, first, last) per period, grouped by SQLite
        (C.13.3).

        One row per period rather than one per node: the counting happens
        in C, and a forest of forty thousand nodes answers with a dozen
        rows. The period expression comes from `windows.period_sql` so the
        grouping and the labelling cannot drift apart.
        """
        from monkeyllm.windows import period_sql

        if field not in ("created", "updated"):
            raise ValueError(f"not a date column: {field}")
        expr = period_sql(field, granularity)
        clauses = [f"{field} != ''", f"{field} IS NOT NULL"]
        clauses += [c.format(n="") for c in (where or [])]
        return [tuple(r) for r in self.conn.execute(
            f"SELECT {expr} AS period, count(*), min({field}), max({field}) "
            f"FROM nodes WHERE " + " AND ".join(clauses) +
            " GROUP BY period ORDER BY period DESC", params or []).fetchall()]

    def dates_by_id(self, field: str, where: list[str] | None = None,
                    params: list | None = None) -> list[tuple[str, str]]:
        """(id, date) pairs — the scoped path's raw material (J.3): a policy
        filters ids, and only then are the dates counted."""
        if field not in ("created", "updated"):
            raise ValueError(f"not a date column: {field}")
        sql = f"SELECT id, {field} FROM nodes"
        if where:
            sql += " WHERE " + " AND ".join(c.format(n="") for c in where)
        return [(r["id"], r[field]) for r in
                self.conn.execute(sql, params or []).fetchall()]

    # -- the memoized scan (C.6b.1) -----------------------------------------

    def sniff_memo(self, term: str, where: list[str],
                   params: list) -> dict[str, str]:
        """Valid entries for one folded term: `{node_id: lines_json}`.

        Validity is the join condition, not a later check: an entry whose
        `body_hash` no longer equals the node's simply does not come back,
        and neither does one for a node the caller's scope excludes. An
        empty hash matches nothing on either side (C.6.1).
        """
        sql = ("SELECT m.node_id, m.lines FROM sniff_memo m "
               "JOIN nodes n ON n.id = m.node_id "
               "AND n.body_hash = m.body_hash AND n.body_hash != '' "
               "WHERE m.term = ?")
        clauses = [c.format(n="n.") for c in where]
        if clauses:
            sql += " AND " + " AND ".join(clauses)
        rows = self.conn.execute(sql, [term, *params]).fetchall()
        return {r["node_id"]: r["lines"] for r in rows}

    def sniff_memo_store(self, entries: list[tuple[str, str, str, str]]) -> None:
        """Record what a scan just learned: `(term, node_id, body_hash,
        lines_json)`, matches and non-matches alike."""
        if not entries:
            return
        self.conn.executemany(
            "INSERT INTO sniff_memo (term, node_id, body_hash, lines) "
            "VALUES (?,?,?,?) ON CONFLICT(term, node_id) DO UPDATE SET "
            "body_hash = excluded.body_hash, lines = excluded.lines",
            entries)
        self.conn.commit()

    def sniff_memo_clear(self) -> None:
        self.conn.execute("DELETE FROM sniff_memo")
        self.conn.commit()

    # -- the embedding memo (K.6) -------------------------------------------

    def embed_memo(self, model: str, text: str) -> list[float] | None:
        """One text's vector under one model, or None.

        The model is half the key because a vector from another model's
        space is the meaningless comparison K.4 exists to prevent — and it
        fails silently, since a dot product always returns a number.
        """
        row = self.conn.execute(
            "SELECT vector FROM embed_memo WHERE model = ? AND text = ?",
            (model, text)).fetchone()
        if row is None:
            return None
        blob = row["vector"]
        return list(struct.unpack(f"<{len(blob) // 4}f", blob))

    def embed_memo_store(self, model: str, text: str, vector: Sequence[float],
                         bound: int = 2000) -> None:
        """Keep the vector, and keep the table from growing forever.

        Eviction is least-recently-used by the same reasoning as H.6: the
        memo is a saving, and a saving that consumes the volume it lives on
        stopped being one.
        """
        self.conn.execute(
            "INSERT INTO embed_memo (model, text, vector, used) VALUES (?,?,?,?) "
            "ON CONFLICT(model, text) DO UPDATE SET vector = excluded.vector, "
            "used = excluded.used",
            (model, text,
             struct.pack(f"<{len(vector)}f", *[float(x) for x in vector]),
             datetime.now(timezone.utc).isoformat()))
        self.conn.execute(
            "DELETE FROM embed_memo WHERE rowid NOT IN "
            "(SELECT rowid FROM embed_memo ORDER BY used DESC LIMIT ?)",
            (int(bound),))
        self.conn.commit()

    def embed_memo_touch(self, model: str, text: str) -> None:
        """A hit is a use — otherwise the eviction above would drop exactly
        the entries that are earning their keep."""
        self.conn.execute(
            "UPDATE embed_memo SET used = ? WHERE model = ? AND text = ?",
            (datetime.now(timezone.utc).isoformat(), model, text))
        self.conn.commit()

    def embed_memo_clear(self) -> None:
        self.conn.execute("DELETE FROM embed_memo")
        self.conn.commit()

    def reindex(self) -> int:
        """Full rebuild from the files (the files always win)."""
        self.conn.execute("DELETE FROM nodes")
        self.conn.execute("DELETE FROM edges")
        self.conn.execute("DELETE FROM nodes_fts")
        n = 0
        for node_id in self.forest.iter_ids():
            try:
                node = self.forest.read(node_id)
            except Exception:
                continue  # validate() reports broken nodes; catalog skips them
            self._upsert(node)
            n += 1
        # A node that no longer has a file has no row either, and its memo
        # entries are now unreachable weight (C.6b.1). Per-node upsert only
        # prunes other generations of nodes that still exist; this is where
        # the departed are swept, and it is the only place that knows they
        # are gone.
        self.conn.execute(
            "DELETE FROM sniff_memo WHERE node_id NOT IN (SELECT id FROM nodes)")
        self.conn.commit()
        return n

    def upsert_node(self, node: ParsedNode) -> None:
        self._upsert(node)
        self.conn.commit()

    def _upsert(self, node: ParsedNode) -> None:
        fm = node.frontmatter
        kind = "branch" if node.is_branch else "banana"
        links = fm.get("links") or []
        trail = self.forest.trail(node.id)
        parent = self.forest.parent_index_id(node.id) if node.id != "_index" else None
        self.conn.execute("DELETE FROM nodes WHERE id = ?", (node.id,))
        self.conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node.id,))
        self.conn.execute("DELETE FROM edges WHERE src = ?", (node.id,))
        # Only the generations this body is NOT (C.6b.1). Dropping the
        # matching one too would make `reindex` — which upserts every node —
        # erase a memo that is still entirely valid, and the whole reason
        # validity is a content hash is that rewriting a file with the same
        # bytes changes nothing.
        body_hash = body_hash_of(node)
        self.conn.execute(
            "DELETE FROM sniff_memo WHERE node_id = ? AND body_hash != ?",
            (node.id, body_hash))
        # C.15: the waymarks this passport declares — and the address this
        # passport occupies stops being anybody's waymark (a replant over a
        # moved-away id makes the address live again).
        self.conn.execute("DELETE FROM moves WHERE old_id = ?", (node.id,))
        for old in (fm.get("moved_from") or []):
            if isinstance(old, str) and old and old != node.id:
                self.conn.execute(
                    "INSERT OR REPLACE INTO moves (old_id, new_id) "
                    "VALUES (?, ?)", (old, node.id))
        self.conn.execute(
            """INSERT INTO nodes (id, kind, type, title, summary, tags, aliases,
                created, updated, confidence, source, entity_kind, payload,
                payload_type, payload_hash, parent, trail, coverage, body_tokens,
                outline, stale, body_hash, origin)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (
                node.id,
                kind,
                node.type,
                node.title,
                node.summary,
                json.dumps(fm.get("tags") or [], ensure_ascii=False),
                json.dumps(fm.get("aliases") or [], ensure_ascii=False),
                str(fm.get("created") or ""),
                str(fm.get("updated") or ""),
                float(fm.get("confidence", 1.0)),
                fm.get("source"),
                fm.get("entity_kind"),
                fm.get("payload"),
                fm.get("payload_type"),
                fm.get("payload_hash"),
                parent,
                json.dumps(trail),
                fm.get("coverage"),
                node.body_tokens,
                json.dumps(node.outline, ensure_ascii=False),
                body_hash,
                fm.get("origin"),
            ),
        )
        self.conn.execute(
            "INSERT INTO nodes_fts (id, title, aliases, tags, summary) VALUES (?,?,?,?,?)",
            (
                node.id,
                node.title,
                " ".join(fm.get("aliases") or []),
                " ".join(fm.get("tags") or []),
                node.summary,
            ),
        )
        for link in links:
            if isinstance(link, dict) and link.get("rel") and link.get("target"):
                # Link-level confidence (G.4.2.1 proposals, C.8 shortcuts) is
                # what separates a proposal from an assertion. The Ranger reads
                # it from the files it manages; indexing it too lets a reader
                # tell them apart without opening every node.
                try:
                    confidence = float(link.get("confidence", 1.0))
                except (TypeError, ValueError):
                    confidence = 1.0
                self.conn.execute(
                    "INSERT OR IGNORE INTO edges (src, rel, dst, confidence) "
                    "VALUES (?,?,?,?)",
                    (node.id, link["rel"], link["target"], confidence),
                )

    def delete_node(self, node_id: str) -> None:
        self.conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        self.conn.execute("DELETE FROM nodes_fts WHERE id = ?", (node_id,))
        # Both directions: a deleted row must not keep answering edges_in
        # for its neighbours (C.14) — the catalog is rebuildable, never the
        # place a ghost lives on. Waymarks pointing at the deleted node die
        # with it (C.15): a redirect into a hole is worse than the hole.
        self.conn.execute("DELETE FROM edges WHERE src = ? OR dst = ?",
                          (node_id, node_id))
        self.conn.execute("DELETE FROM moves WHERE new_id = ?", (node_id,))
        self.conn.commit()

    def mark_stale(self, node_id: str) -> None:
        self.conn.execute("UPDATE nodes SET stale = 1 WHERE id = ?", (node_id,))
        self.conn.commit()

    def stale_ids(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT id FROM nodes WHERE stale = 1")]

    def clear_stale(self, node_ids: list[str]) -> None:
        self.conn.executemany(
            "UPDATE nodes SET stale = 0 WHERE id = ?", [(i,) for i in node_ids]
        )
        self.conn.commit()

    # -- read ----------------------------------------------------------------

    def get(self, node_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()

    def moved_to(self, old_id: str) -> str | None:
        """C.15: where a waymark points, or None for an id that never
        moved (or moved and was replanted — upsert clears the row)."""
        row = self.conn.execute(
            "SELECT new_id FROM moves WHERE old_id = ?", (old_id,)).fetchone()
        return row["new_id"] if row else None

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]

    def top_degrees(self, limit: int = 20) -> list[sqlite3.Row]:
        """Highest-degree non-branch nodes over the typed-edge table (H.7).
        Only nodes with degree >= 1 appear (the SELECT starts from edges)."""
        return self.conn.execute(
            """
            SELECT n.id, n.title, n.summary, d.degree FROM (
                SELECT node, SUM(cnt) AS degree FROM (
                    SELECT src AS node, COUNT(*) AS cnt FROM edges GROUP BY src
                    UNION ALL
                    SELECT dst AS node, COUNT(*) AS cnt FROM edges GROUP BY dst
                ) GROUP BY node
            ) d JOIN nodes n ON n.id = d.node
            WHERE n.kind != 'branch' AND n.id NOT LIKE '\\_meta/%' ESCAPE '\\'
            ORDER BY d.degree DESC, n.id LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def degree(self, node_id: str) -> int:
        return self.conn.execute(
            "SELECT (SELECT COUNT(*) FROM edges WHERE src = ?) + "
            "(SELECT COUNT(*) FROM edges WHERE dst = ?)",
            (node_id, node_id),
        ).fetchone()[0]

    def edges_out(self, node_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT rel, dst FROM edges WHERE src = ?", (node_id,)
        ).fetchall()

    def edges_in(self, node_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT src, rel FROM edges WHERE dst = ?", (node_id,)
        ).fetchall()

    def has_edge(self, src: str, rel: str, dst: str) -> bool:
        return (
            self.conn.execute(
                "SELECT 1 FROM edges WHERE src = ? AND rel = ? AND dst = ?",
                (src, rel, dst),
            ).fetchone()
            is not None
        )

    def dates_of(self, ids: list[str]) -> dict[str, tuple[str, str]]:
        """id -> (created, updated) for a result set (C.6c.3).

        Read off the rows already indexed — never a file open. Empty
        strings stay empty: an undated node states no time.
        """
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        return {
            r["id"]: (r["created"] or "", r["updated"] or "")
            for r in self.conn.execute(
                f"SELECT id, created, updated FROM nodes WHERE id IN ({marks})",
                ids,
            )
        }

    def superseded_by_map(self, ids: list[str]) -> dict[str, list[str]]:
        """target -> live superseders, for a candidate set (C.6c.4).

        Rows exist only while the superseder lives — `delete_node` removes
        its edges — so "a LIVE node supersedes" is the table's own
        invariant, never a second check.
        """
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        out: dict[str, list[str]] = {}
        for r in self.conn.execute(
                f"SELECT src, dst FROM edges WHERE rel = 'supersedes' "
                f"AND dst IN ({marks})", ids):
            out.setdefault(r["dst"], []).append(r["src"])
        return out

    def edges_among(self, ids: list[str], rel: str) -> list[sqlite3.Row]:
        """Edges of one rel whose BOTH endpoints are in `ids` (C.6c.3).

        Asked with a result set (k <= 5 items), never the forest: the
        sweep annotates successions inside what it already selected.
        """
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        return self.conn.execute(
            f"SELECT src, dst FROM edges WHERE rel = ? "
            f"AND src IN ({marks}) AND dst IN ({marks})",
            (rel, *ids, *ids),
        ).fetchall()

    # bm25() per-column weights, positional over (id, title, aliases, tags,
    # summary). A hit on curated naming (title/aliases) outranks the same hit
    # in prose; id is UNINDEXED so its slot is 0.
    FTS_WEIGHTS = (0.0, 4.0, 3.0, 2.0, 1.0)

    def fts_search(self, query: str, limit: int = 50,
                   where: list[str] | None = None,
                   params: list | None = None) -> list[sqlite3.Row]:
        """BM25 search. User query is sanitized into quoted terms (no FTS
        syntax injection); bm25 rank: lower = better.

        `where`/`params` are C.13.1's window, applied HERE rather than to
        the ranked result: a filter after the cut returns fewer than `k`
        while the forest still holds matches, and the caller reads a
        scarcity the implementation invented. Clauses carry `{n}` where the
        node table's alias belongs, so one predicate serves this join and
        the plain scans elsewhere.
        """
        terms = [t.replace('"', '""') for t in query.split() if t.strip()]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        weights = ", ".join(str(w) for w in self.FTS_WEIGHTS)
        extra = "".join(" AND " + c.format(n="n.") for c in (where or []))
        return self.conn.execute(
            f"""SELECT n.*, bm25(nodes_fts, {weights}) AS rank
               FROM nodes_fts f JOIN nodes n ON n.id = f.id
               WHERE nodes_fts MATCH ?{extra}
               ORDER BY rank LIMIT ?""",
            (match, *(params or []), limit),
        ).fetchall()

    def children(self, parent_id: str, recursive: bool = False) -> list[sqlite3.Row]:
        if recursive:
            prefix = parent_id[: -len("/_index")] + "/" if parent_id.endswith("/_index") else ""
            if parent_id == "_index":
                return self.conn.execute(
                    "SELECT * FROM nodes WHERE id != '_index'"
                ).fetchall()
            return self.conn.execute(
                "SELECT * FROM nodes WHERE id LIKE ? AND id != ?",
                (prefix + "%", parent_id),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM nodes WHERE parent = ?", (parent_id,)
        ).fetchall()
