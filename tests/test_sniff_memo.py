# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""C.6b.1 — the memoized literal scan (spec v0.40, criterion F.40).

The memo is only allowed to change latency. Every test here asks the same
question twice, once cold and once warm, and insists the two answers are
the same answer.
"""

from __future__ import annotations

import json

import pytest

from monkeyllm.vine import _combine_lines, _sniff_body, _sniff_lines, _fold


def _reading(result: dict) -> list:
    """A sniff answer with the ranking held constant (heat moves between
    two identical calls by design — that is Part D working)."""
    return [
        {k: v for k, v in r.items() if k not in ("score", "heat")}
        for r in result["results"]
    ]


TERMS = ["experiment", "policy", "1045"]


def test_warm_equals_cold(vine_ro):
    """The memo is invisible in the answer, only in the clock."""
    vine_ro.catalog.sniff_memo_clear()
    cold = vine_ro.sniff(TERMS, k=20)
    warm = vine_ro.sniff(TERMS, k=20)
    assert _reading(cold) == _reading(warm)
    assert cold["scanned_nodes"] == warm["scanned_nodes"]
    assert cold["truncated"] == warm["truncated"]


def test_warm_reads_no_file(vine_ro, monkeypatch):
    """The second call must not open a single body — that is the feature."""
    vine_ro.catalog.sniff_memo_clear()
    vine_ro.sniff(TERMS, k=20)

    opened = []
    original = type(vine_ro.forest).path_for

    def spy(self, node_id):
        opened.append(node_id)
        return original(self, node_id)

    monkeypatch.setattr(type(vine_ro.forest), "path_for", spy)
    vine_ro.sniff(TERMS, k=20)
    # Only nodes the memo may not cover (G.7 foreign bodies) may be read.
    foreign = {r["id"] for r in vine_ro.catalog.conn.execute(
        "SELECT id FROM nodes WHERE body_hash = ''")}
    assert set(opened) <= foreign


def test_negatives_are_remembered(vine_ro):
    """A node that matched nothing is recorded, or the 95% that never match
    would be rescanned forever."""
    vine_ro.catalog.sniff_memo_clear()
    vine_ro.sniff(["zzzznotinanybody"], k=5)
    rows = vine_ro.catalog.conn.execute(
        "SELECT lines FROM sniff_memo WHERE term = ?",
        ("zzzznotinanybody",)).fetchall()
    assert rows, "the scan learned nothing from a term that matched nothing"
    assert all(json.loads(r["lines"]) == [] for r in rows)


def test_edit_invalidates_only_that_node(vine_rw):
    """The changed document is rescanned; the rest is served from the memo."""
    vine_rw.sniff(TERMS, k=20)
    target = vine_rw.catalog.conn.execute(
        "SELECT id FROM nodes WHERE kind = 'banana' AND body_hash != '' "
        "ORDER BY id LIMIT 1").fetchone()["id"]
    before = vine_rw.catalog.conn.execute(
        "SELECT count(*) c FROM sniff_memo WHERE node_id != ?",
        (target,)).fetchone()["c"]

    path = vine_rw.forest.path_for(target)
    path.write_text(path.read_text(encoding="utf-8")
                    + "\n\n## Addendum\n\nexperiment 1045 landed here.\n",
                    encoding="utf-8")
    vine_rw.catalog.upsert_node(vine_rw.forest.read(target))

    assert vine_rw.catalog.conn.execute(
        "SELECT count(*) c FROM sniff_memo WHERE node_id = ?",
        (target,)).fetchone()["c"] == 0
    assert vine_rw.catalog.conn.execute(
        "SELECT count(*) c FROM sniff_memo WHERE node_id != ?",
        (target,)).fetchone()["c"] == before

    found = vine_rw.sniff(["1045"], scope=target, k=5)
    assert found["results"] and found["results"][0]["id"] == target


def test_reindex_keeps_what_did_not_change(vine_rw):
    """Validity is content, not the clock: rewriting the same bytes — which
    is what reindex does — invalidates nothing."""
    vine_rw.sniff(TERMS, k=20)
    before = vine_rw.catalog.conn.execute(
        "SELECT term, node_id, body_hash, lines FROM sniff_memo "
        "ORDER BY term, node_id").fetchall()
    assert before
    vine_rw.catalog.reindex()
    after = vine_rw.catalog.conn.execute(
        "SELECT term, node_id, body_hash, lines FROM sniff_memo "
        "ORDER BY term, node_id").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_scoped_scan_feeds_a_later_global_one(vine_ro):
    """An entry is a fact about one node and one term, whatever the scope
    that learned it."""
    vine_ro.catalog.sniff_memo_clear()
    target = vine_ro.catalog.conn.execute(
        "SELECT id FROM nodes WHERE kind = 'banana' AND body_hash != '' "
        "ORDER BY id LIMIT 1").fetchone()["id"]
    vine_ro.sniff(["experiment"], scope=target, k=5)
    assert vine_ro.catalog.conn.execute(
        "SELECT count(*) c FROM sniff_memo WHERE node_id = ?",
        (target,)).fetchone()["c"] == 1
    # The global call reuses it rather than rescanning that node: what a
    # read asks the memo is which nodes it does NOT cover (C.6b.1, v0.59).
    assert target not in vine_ro.catalog.sniff_memo_uncovered(
        "experiment", [], [])


def test_foreign_bodies_are_never_memoized(vine_rw):
    """A `content: cached` body is not the `.md` the hash covers."""
    target = vine_rw.catalog.conn.execute(
        "SELECT id FROM nodes WHERE kind = 'banana' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    node = vine_rw.forest.read(target)
    node.frontmatter["content"] = "cached"
    vine_rw.catalog.upsert_node(node)
    assert vine_rw.catalog.conn.execute(
        "SELECT body_hash FROM nodes WHERE id = ?",
        (target,)).fetchone()["body_hash"] == ""
    vine_rw.sniff(TERMS, k=20)
    assert vine_rw.catalog.conn.execute(
        "SELECT count(*) c FROM sniff_memo WHERE node_id = ?",
        (target,)).fetchone()["c"] == 0


def test_dropping_the_memo_changes_nothing_but_speed(vine_ro):
    warm = vine_ro.sniff(TERMS, k=20)
    vine_ro.catalog.sniff_memo_clear()
    cold = vine_ro.sniff(TERMS, k=20)
    assert _reading(warm) == _reading(cold)


@pytest.mark.parametrize("terms", [
    ["experiment"],
    ["experiment", "policy"],
    ["policy", "experiment", "1045"],
    ["the", "a"],
])
def test_combiner_reproduces_the_direct_scan(vine_ro, terms):
    """The one way this could break silently: `_sniff_body` emits one match
    per LINE centred on the leftmost term, so per-term results only compose
    if each carries its own position."""
    folded = [_fold(t) for t in terms]
    for row in vine_ro.catalog.conn.execute(
            "SELECT id FROM nodes WHERE body_hash != '' ORDER BY id"):
        body = vine_ro.forest.read(row["id"]).body
        direct = _sniff_body(body, folded)
        composed = _combine_lines([_sniff_lines(body, t) for t in folded])
        assert composed == direct, row["id"]
