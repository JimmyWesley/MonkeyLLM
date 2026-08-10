# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Catalog (_derived/catalog.db, spec C.6.1).

One row per node: frontmatter + trail + degree. FTS5 over
title/aliases/tags/summary serves the lexical side of locate().
Never the source of truth: rebuildable from files via reindex().
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from monkeyllm.forest import Forest, tune_derived
from monkeyllm.parser import ParsedNode

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
    stale INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);

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
        self.conn.execute(
            """INSERT INTO nodes (id, kind, type, title, summary, tags, aliases,
                created, updated, confidence, source, entity_kind, payload,
                payload_type, payload_hash, parent, trail, coverage, body_tokens,
                outline, stale)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
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
        self.conn.execute("DELETE FROM edges WHERE src = ?", (node_id,))
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

    # bm25() per-column weights, positional over (id, title, aliases, tags,
    # summary). A hit on curated naming (title/aliases) outranks the same hit
    # in prose; id is UNINDEXED so its slot is 0.
    FTS_WEIGHTS = (0.0, 4.0, 3.0, 2.0, 1.0)

    def fts_search(self, query: str, limit: int = 50) -> list[sqlite3.Row]:
        """BM25 search. User query is sanitized into quoted terms (no FTS
        syntax injection); bm25 rank: lower = better."""
        terms = [t.replace('"', '""') for t in query.split() if t.strip()]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        weights = ", ".join(str(w) for w in self.FTS_WEIGHTS)
        return self.conn.execute(
            f"""SELECT n.*, bm25(nodes_fts, {weights}) AS rank
               FROM nodes_fts f JOIN nodes n ON n.id = f.id
               WHERE nodes_fts MATCH ?
               ORDER BY rank LIMIT ?""",
            (match, limit),
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
