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
    origin TEXT,
    -- A.3.2 (v0.75): a facet, never scent. It is a column and MUST NOT
    -- enter the FTS row: a language is what a result is filtered BY, and
    -- a tag indexed beside the title would make `pt` a word that ranks.
    lang TEXT
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
        # Same bargain again for `lang` (A.3.2, v0.75).
        if "lang" not in {
            r[1] for r in self.conn.execute("PRAGMA table_info(nodes)")
        }:
            self.conn.execute("ALTER TABLE nodes ADD COLUMN lang TEXT")
        # A.3.2 rule 5: the filter is a bare comparison on an INDEXED
        # column, which is the whole reason it can be applied where
        # candidates are chosen instead of after the cut. Created here
        # rather than in SCHEMA_SQL because on a pre-v0.75 catalog the
        # column does not exist until the ALTER above has run.
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_nodes_lang ON nodes(lang)")
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

    def group_counts(self, column: str, where: list[str] | None = None,
                     params: list | None = None) -> dict[str, int]:
        """`{value: count}` over one column, grouped by SQLite (C.17 rule 1).

        The counting happens in C, so a forest of forty thousand nodes
        answers with as many rows as it has distinct values. Empty and NULL
        are omitted rather than bucketed under a made-up name: a column with
        no value is not a category.
        """
        if column not in ("type", "source", "kind", "entity_kind",
                          "payload_type", "lang"):
            raise ValueError(f"not a groupable column: {column}")
        clauses = [f"{column} IS NOT NULL", f"{column} != ''"]
        clauses += [c.format(n="") for c in (where or [])]
        return {row[0]: int(row[1]) for row in self.conn.execute(
            f"SELECT {column}, count(*) FROM nodes WHERE "
            + " AND ".join(clauses) + f" GROUP BY {column} ORDER BY count(*) DESC",
            params or []).fetchall()}

    def tag_counts(self, where: list[str], params: list,
                   limit: int) -> tuple[list[tuple[str, int]], int | None]:
        """The tag vocabulary with counts, grouped by SQLite (J.5.18 rule 4).

        `limit` has no default here on purpose: the ceiling is stated once,
        in `vine.TAG_VOCABULARY_CAP`, and a second spelling of it in this
        signature would be a number two files could disagree about while
        both looked right.

        Returns `(rows, distinct)` where `rows` is at most `limit` pairs of
        `(tag, nodes)` ordered by count then name, and `distinct` is how many
        distinct tags the scope really holds — asked only when the cap
        actually clipped, so the ordinary answer costs one pass.

        Read off the stored `tags` array and NEVER off the FTS row's
        space-joined copy: `nodes_fts` is tokenized `unicode61
        remove_diacritics 2`, so a vocabulary read there would report
        `producao` for a passport that says `produção` — the exact spelling
        G.4.2 rule 2 exists to keep.

        The counting happens in C, for J.4.3's reason restated by J.5.18:
        a total computed from what is on screen changes when somebody
        changes the page size, and this one is the number a person uses to
        see that `invoice` and `invoices` are the same intent spelled twice.
        `count(DISTINCT nodes.id)`, because a passport carrying one tag
        twice is one node carrying it.

        The predicate is formatted with `nodes.` rather than the bare column
        `{n}` gets elsewhere: `json_each` brings its own `id` column into
        scope, and an unqualified one in a policy's `substr(id, 1, ?)` is
        ambiguous to SQLite rather than wrong to a reader.
        """
        clauses = [c.format(n="nodes.") for c in (where or [])]
        # A `tags` column the parser could not have written (hand-edited
        # `_derived`, a truncated file) must not take the whole vocabulary
        # down with it: json_each raises on malformed JSON, and it raises
        # while producing rows, so no WHERE clause can guard it.
        source = ("json_each(CASE WHEN json_valid(nodes.tags) "
                  "THEN nodes.tags ELSE '[]' END)")
        sql = (f"SELECT json_each.value AS tag, count(DISTINCT nodes.id) AS n "
               f"FROM nodes, {source}")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " GROUP BY tag ORDER BY n DESC, tag ASC LIMIT ?"
        # One more than the cap, so "there was more" is read off the query
        # rather than guessed from a full page.
        rows = [(str(r[0]), int(r[1])) for r in
                self.conn.execute(sql, [*(params or []), max(1, limit) + 1])]
        if len(rows) <= limit:
            return rows, None
        count_sql = f"SELECT count(DISTINCT json_each.value) FROM nodes, {source}"
        if clauses:
            count_sql += " WHERE " + " AND ".join(clauses)
        distinct = int(self.conn.execute(count_sql, params or []).fetchone()[0])
        return rows[:limit], distinct

    def subtree_stats(self, field: str, where: list[str],
                      params: list | None = None) -> dict:
        """One root's shape, in ONE statement (C.17 rules 1, 3 and 4).

        Everything `coverage` reports about a root comes back from a single
        aggregate: how many nodes, how many of them branches, the dates it
        spans, and — the interesting one — the two extremes of `origin`.

        The longest common prefix of a set of strings is the longest common
        prefix of its lexicographic minimum and maximum, so `min`/`max`
        answer "where did this material come from" without reading a single
        origin into Python. `without_origin` is counted in the same pass,
        because a root where one node in ten knows its source is not a root
        with an origin (rule 5).
        """
        if field not in ("created", "updated"):
            raise ValueError(f"not a date column: {field}")
        clauses = [c.format(n="") for c in where]
        row = self.conn.execute(
            "SELECT count(*), "
            "sum(CASE WHEN kind = 'branch' THEN 1 ELSE 0 END), "
            f"min(NULLIF({field}, '')), max(NULLIF({field}, '')), "
            "min(NULLIF(origin, '')), max(NULLIF(origin, '')), "
            "sum(CASE WHEN origin IS NULL OR origin = '' THEN 1 ELSE 0 END), "
            # A.3.2 rule 6: the nodes carrying no language are their own
            # group, counted in the pass that was already running.
            "sum(CASE WHEN lang IS NULL OR lang = '' THEN 1 ELSE 0 END) "
            "FROM nodes WHERE " + " AND ".join(clauses),
            params or []).fetchone()
        return {"nodes": int(row[0] or 0), "branches": int(row[1] or 0),
                "first": row[2], "last": row[3],
                "origin_min": row[4], "origin_max": row[5],
                "without_origin": int(row[6] or 0),
                "without_lang": int(row[7] or 0)}

    def local_payloads(self, where: list[str],
                       params: list | None = None) -> list[tuple[str, str]]:
        """(id, payload) for every node in scope declaring a payload.

        C.17 rule 11 counts the ones the filesystem does not have, and the
        list is bounded by how many nodes carry payloads at all — a handful
        beside the node count, which is why the integrity fact is affordable
        inside a primitive whose rule is that it opens no file.
        """
        clauses = [c.format(n="") for c in where]
        sql = ("SELECT id, payload FROM nodes "
               "WHERE payload IS NOT NULL AND payload != ''")
        if clauses:
            sql += " AND " + " AND ".join(clauses)
        return [(r[0], r[1]) for r in self.conn.execute(sql, params or [])]

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

    def sniff_memo_matches(self, term: str, where: list[str],
                           params: list) -> dict[str, str]:
        """The memo's MATCHING lines for one folded term (C.6b.1, v0.59).

        Until v0.59 the memo handed back a row per node in scope — on a
        two-thousand node forest that is two thousand rows of text out of
        SQLite on every read, to discover that ~95% of them are the empty
        marker. The empty
        rows still have to exist (the negative is what stops the rescan),
        but nothing has to carry them into Python: what the caller needs
        from them is the FACT of coverage, which `sniff_memo_uncovered`
        answers by naming the handful that lack it instead.
        """
        sql = ("SELECT m.node_id, m.lines FROM sniff_memo m "
               "JOIN nodes n ON n.id = m.node_id "
               "AND n.body_hash = m.body_hash AND n.body_hash != '' "
               "WHERE m.term = ? AND m.lines != '[]'")
        clauses = [c.format(n="n.") for c in where]
        if clauses:
            sql += " AND " + " AND ".join(clauses)
        return {r["node_id"]: r["lines"]
                for r in self.conn.execute(sql, [term, *params]).fetchall()}

    def sniff_memo_uncovered(self, term: str, where: list[str],
                             params: list) -> set[str]:
        """Nodes in scope this term was never scanned against, or was
        scanned against under a body that has since changed (C.6b.1).

        The complement of coverage, which is the cheap half to ask for: on
        a warm forest it is empty, and an empty answer is what makes the
        rest of the read proportional to the matches instead of to the
        corpus. Nodes with no `body_hash` are here too — the memo cannot
        cover them (C.6b.1's last rule), so they are scanned every time.
        """
        sql = ("SELECT n.id FROM nodes n WHERE (n.body_hash = '' "
               "OR n.body_hash IS NULL OR NOT EXISTS ("
               "SELECT 1 FROM sniff_memo m WHERE m.term = ? "
               "AND m.node_id = n.id AND m.body_hash = n.body_hash))")
        clauses = [c.format(n="n.") for c in where]
        if clauses:
            sql += " AND " + " AND ".join(clauses)
        return {r[0] for r in self.conn.execute(sql, [term, *params]).fetchall()}

    def rows_by_id(self, ids: list[str], where: list[str],
                   params: list) -> list:
        """The catalog rows for a named set, in id order (C.6b.1, v0.59).

        `SELECT *` over a whole forest to use five rows of it is the other
        half of the O(corpus) cost the memo was supposed to remove.
        """
        if not ids:
            return []
        clauses = [c.format(n="") for c in where]
        out = []
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            marks = ",".join("?" * len(chunk))
            sql = f"SELECT * FROM nodes WHERE id IN ({marks})"
            if clauses:
                sql += " AND " + " AND ".join(clauses)
            out.extend(self.conn.execute(sql, [*chunk, *params]).fetchall())
        return sorted(out, key=lambda r: r["id"])

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
                outline, stale, body_hash, origin, lang)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)""",
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
                fm.get("lang"),
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

    def uncertain_edges(self) -> list[sqlite3.Row]:
        """H.2's managed population, off the index instead of every file.

        The Ranger walks the passports once a cycle because it has to write
        them; a console asking "what is pending" must not, and `confidence`
        is indexed on this table for exactly that (it is what separates a
        proposal from an assertion). Ordered by (src, rel, dst) so a page is
        not reshuffled by another principal's vote mid-review (J.18).

        The files stay the truth: whoever reads this then reads the
        passports of the page's own sources.
        """
        return self.conn.execute(
            "SELECT src, rel, dst, confidence FROM edges WHERE confidence < 1.0 "
            "ORDER BY src, rel, dst"
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


def count_missing_payloads(catalog: Catalog, forest: Forest,
                           where: list[str] | None = None,
                           params: list | None = None) -> int:
    """Local payloads a passport names and the filesystem does not have.

    C.17 rule 11 counts this per root, and Part I's restore counts it over
    the whole forest to say what a snapshot did not bring (v0.74). One
    implementation, because two counts of one condition agree only where
    somebody compared them — and this one decides whether an operator is
    told their datasets are dead.

    One statement selects the nodes that declare a payload at all — a
    handful beside the node count — and each is a stat, never an open, so
    C.17 rule 1 stands. Remote payloads (G.9) are skipped: their bytes were
    never local, their absence is a fetch away, and counting them would
    report a hole that does not exist.
    """
    from monkeyllm.fetch import is_remote

    gone = 0
    for node_id, payload in catalog.local_payloads(where or [], params or []):
        if is_remote(payload):
            continue
        if not (forest.path_for(node_id).parent / payload).is_file():
            gone += 1
    return gone
