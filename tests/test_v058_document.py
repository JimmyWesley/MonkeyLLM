# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.58 — the document has a past (engine half).

F.95: `transplant` moves a leaf whole and leaves a waymark.
F.97: `history` says what happened and who did it, across the move.
F.98: a batch is one plant — all validated, one commit, or nothing.
F.99: a replacement suppresses what it replaced, and says so.
F.100 (engine half): the Gardener records where a document came from.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from monkeyllm.errors import E_ANCHORED, E_MOVED, E_SCHEMA, VineError
from monkeyllm.forest import init_forest
from monkeyllm.gardener import Gardener
from monkeyllm.harvest import harvest
from monkeyllm.vine import Vine

NOTE = {"id": "notes/misplaced", "type": "note", "parent": "notes/_index",
        "title": "Misplaced", "summary": "A note planted under the wrong "
                                         "branch, to be transplanted.",
        "body": "# Misplaced\n\nThe body that must survive the move."}


def _git(root, *args) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


# -- F.95: the move that leaves a waymark ------------------------------------


class TestTransplant:
    def test_the_node_moves_whole_in_one_commit(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        created = vine_rw.look("notes/misplaced")["created"]
        before = _git(vine_rw.forest.root, "rev-list", "--count", "HEAD")

        out = vine_rw.transplant("notes/misplaced", "concepts/misplaced")
        assert out["id"] == "concepts/misplaced"
        assert out["moved_from"] == "notes/misplaced"
        after = _git(vine_rw.forest.root, "rev-list", "--count", "HEAD")
        assert int(after) == int(before) + 1, "one move, one commit"

        moved = vine_rw.look("concepts/misplaced")
        assert moved["title"] == "Misplaced"
        assert moved["created"] == created, "the passport keeps its birthday"
        assert "The body that must survive" in vine_rw.pick(
            "concepts/misplaced")["body"]
        assert not vine_rw.forest.exists("notes/misplaced")
        # Both indexes account for it: gone from one, listed in the other.
        assert "notes/misplaced" not in vine_rw.forest.read(
            "notes/_index").body
        assert "concepts/misplaced" in vine_rw.forest.read(
            "concepts/_index").body

    def test_the_old_address_still_finds_it_and_says_where_it_went(
            self, vine_rw):
        vine_rw.plant(dict(NOTE))
        vine_rw.transplant("notes/misplaced", "concepts/misplaced")

        with pytest.raises(VineError) as e:
            vine_rw.look("notes/misplaced")
        assert e.value.code == E_MOVED
        assert e.value.to_dict()["error"]["moved_to"] == "concepts/misplaced"

        hits = vine_rw.locate("notes/misplaced", k=3)["results"]
        assert hits and hits[0]["id"] == "concepts/misplaced", \
            "locate finds the node by the name it used to have"
        node = vine_rw.forest.read("concepts/misplaced")
        assert node.frontmatter["moved_from"] == ["notes/misplaced"]
        assert "notes/misplaced" in node.frontmatter["aliases"]

    def test_the_waymark_survives_a_reindex(self, vine_rw):
        # The files are the truth: `moved_from` rebuilds the redirect map,
        # so nothing about the waymark lives only in `_derived`.
        vine_rw.plant(dict(NOTE))
        vine_rw.transplant("notes/misplaced", "concepts/misplaced")
        vine_rw.catalog.reindex()
        with pytest.raises(VineError) as e:
            vine_rw.look("notes/misplaced")
        assert e.value.code == E_MOVED

    def test_every_backlink_follows(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        vine_rw.graft("concepts/rag", {
            "add_links": [{"rel": "related-to", "target": "notes/misplaced"}]})
        out = vine_rw.transplant("notes/misplaced", "concepts/misplaced")
        assert out["backlinks_rewritten"] == 1

        targets = [l["target"] for l in
                   vine_rw.forest.read("concepts/rag").frontmatter["links"]]
        assert "concepts/misplaced" in targets
        assert "notes/misplaced" not in targets
        incoming = [e["source"] for e in
                    vine_rw.look("concepts/misplaced")["edges_in"]]
        assert "concepts/rag" in incoming

    def test_a_planted_moved_from_is_refused(self, vine_rw):
        # C.15: the waymark is written by transplant and nothing else — a
        # planted one would forge a redirect over an address its writer
        # never held.
        with pytest.raises(VineError) as e:
            vine_rw.plant(dict(NOTE, id="notes/forger",
                               moved_from=["concepts/rag"]))
        assert e.value.code == E_SCHEMA and "transplant" in e.value.hint

    def test_branches_root_and_system_never_move(self, vine_rw):
        for src, dst in (("notes/_index", "archive/_index"),
                         ("_index", "root"),
                         ("_meta/schema", "notes/schema")):
            with pytest.raises(VineError) as e:
                vine_rw.transplant(src, dst)
            assert e.value.code == E_SCHEMA

    def test_a_taken_address_and_a_missing_parent_refuse(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        with pytest.raises(VineError) as taken:
            vine_rw.transplant("notes/misplaced", "concepts/rag")
        assert taken.value.code == E_SCHEMA
        with pytest.raises(VineError) as orphan:
            vine_rw.transplant("notes/misplaced", "nowhere/misplaced")
        assert orphan.value.code in (E_SCHEMA, "E_NOT_FOUND")
        # Nothing was written by either refusal.
        assert vine_rw.forest.exists("notes/misplaced")

    def test_heat_follows_the_node(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        vine_rw.trails.add_heat(["notes/misplaced"], amount=0.4)
        before = vine_rw.trails.get_heat("notes/misplaced")
        assert before > 0
        vine_rw.transplant("notes/misplaced", "concepts/misplaced")
        assert vine_rw.trails.get_heat("concepts/misplaced") == pytest.approx(
            before)
        assert vine_rw.trails.get_heat("notes/misplaced") == 0.0

    def test_a_payload_travels_with_its_passport(self, vine_rw):
        vine_rw.plant({
            "id": "sales/mover", "type": "dataset", "parent": "sales/_index",
            "title": "Mover", "summary": "A dataset whose payload must "
                                         "follow its passport.",
            "schema": {"rows": {"columns": {"a": "TEXT"}}}})
        assert (Path(vine_rw.forest.root) / "sales" / "mover.db").is_file()
        vine_rw.transplant("sales/mover", "projects/mover")
        assert (Path(vine_rw.forest.root) / "projects" / "mover.db").is_file()
        assert not (Path(vine_rw.forest.root) / "sales" / "mover.db").exists()
        assert vine_rw.query("projects/mover",
                             "SELECT * FROM rows")["columns"] == ["a"]


# -- F.97: the document's past ------------------------------------------------


class TestHistory:
    def test_it_lists_what_happened_newest_first(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        vine_rw.graft("notes/misplaced", {
            "set_frontmatter": {"tags": ["moved"]}})
        h = vine_rw.history("notes/misplaced")
        assert h["returned"] >= 2
        actions = [e["action"] for e in h["entries"]]
        assert actions[0] == "graft" and "plant" in actions
        first = h["entries"][0]
        assert len(first["commit"]) == 40
        # The intraday answer day-precision frontmatter could never give.
        assert "T" in first["at"] and ":" in first["at"]

    def test_it_crosses_the_move_unbroken(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        vine_rw.transplant("notes/misplaced", "concepts/misplaced")
        actions = [e["action"] for e in
                   vine_rw.history("concepts/misplaced")["entries"]]
        assert actions[0] == "transplant"
        assert "plant" in actions, "the past does not begin at the move"

    def test_the_trailer_is_read_back_as_by(self, vine_rw):
        vine_rw.commit_trailers = ["station-principal: alice"]
        try:
            vine_rw.plant(dict(NOTE))
        finally:
            vine_rw.commit_trailers = []
        vine_rw.graft("notes/misplaced", {"set_frontmatter": {"tags": ["x"]}})
        entries = vine_rw.history("notes/misplaced")["entries"]
        by = {e["action"]: e.get("by") for e in entries}
        assert by["plant"] == "alice"
        assert by["graft"] is None, "an unstamped write says so, honestly"

    def test_limit_and_the_budget_truncate_explicitly(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        for i in range(4):
            vine_rw.graft("notes/misplaced",
                          {"set_frontmatter": {"tags": [f"t{i}"]}})
        page = vine_rw.history("notes/misplaced", limit=2)
        assert page["returned"] == 2 and page["truncated"] is True
        assert page["oldest"] == page["entries"][-1]["commit"]
        whole = vine_rw.history("notes/misplaced", limit=50)
        assert whole["returned"] >= 5 and whole["truncated"] is False

    def test_an_absent_node_has_no_past_and_a_moved_one_redirects(
            self, vine_rw):
        with pytest.raises(VineError) as absent:
            vine_rw.history("notes/never-was")
        assert absent.value.code == "E_NOT_FOUND"
        vine_rw.plant(dict(NOTE))
        vine_rw.transplant("notes/misplaced", "concepts/misplaced")
        with pytest.raises(VineError) as moved:
            vine_rw.history("notes/misplaced")
        assert moved.value.code == E_MOVED


# -- F.98: a batch is one plant ----------------------------------------------


def _batch(n: int, prefix: str = "notes/batch") -> list[dict]:
    return [{"id": f"{prefix}-{i}", "type": "note", "parent": "notes/_index",
             "title": f"Batch {i}",
             "summary": f"Node {i} of a batch that lands whole or not at all.",
             "body": f"# Batch {i}\n\nBody {i}."} for i in range(n)]


class TestBatchPlant:
    def test_the_whole_batch_lands_in_one_commit(self, vine_rw):
        before = int(_git(vine_rw.forest.root, "rev-list", "--count", "HEAD"))
        out = vine_rw.plant(_batch(5))
        assert out["count"] == 5 and len(out["created"]) == 5
        after = int(_git(vine_rw.forest.root, "rev-list", "--count", "HEAD"))
        assert after == before + 1, "five nodes, one commit"
        for i in range(5):
            assert vine_rw.look(f"notes/batch-{i}")["title"] == f"Batch {i}"
        index_body = vine_rw.forest.read("notes/_index").body
        assert all(f"notes/batch-{i}" in index_body for i in range(5))

    def test_one_invalid_node_writes_nothing(self, vine_rw):
        nodes = _batch(4)
        nodes[2]["summary"] = ("word " * 80).strip()  # over A.4's 60 tokens
        before = _git(vine_rw.forest.root, "rev-parse", "HEAD")
        with pytest.raises(VineError) as e:
            vine_rw.plant(nodes)
        assert e.value.message.startswith("notes/batch-2:")
        assert _git(vine_rw.forest.root, "rev-parse", "HEAD") == before
        for i in range(4):
            assert not vine_rw.forest.exists(f"notes/batch-{i}"), \
                "a partial batch is the half-built graph this rule ends"

    def test_a_branch_and_its_children_share_one_batch(self, vine_rw):
        out = vine_rw.plant([
            {"id": "reports/_index", "type": "branch", "parent": "_index",
             "title": "Reports", "summary": "Test reports, planted with "
                                            "their branch in one batch."},
            {"id": "reports/one", "type": "note", "parent": "reports/_index",
             "title": "One", "summary": "The first report under a branch "
                                        "born in the same call."},
        ])
        assert out["count"] == 2
        assert vine_rw.look("reports/one")["title"] == "One"
        assert vine_rw.scan("reports/_index")["total"] == 1

    def test_if_absent_reports_the_taken_without_failing(self, vine_rw):
        vine_rw.plant(_batch(1))
        out = vine_rw.plant(_batch(3), if_absent=True)
        assert out["existing"] == ["notes/batch-0"]
        assert sorted(out["created"]) == ["notes/batch-1", "notes/batch-2"]
        # Without the flag, the taken id fails the batch as it fails a
        # single plant.
        with pytest.raises(VineError):
            vine_rw.plant(_batch(3))

    def test_dry_run_rehearses_the_whole_list(self, vine_rw):
        head = _git(vine_rw.forest.root, "rev-parse", "HEAD")
        out = vine_rw.plant(_batch(3), dry_run=True)
        assert out == {"valid": True, "count": 3, "dry_run": True}
        assert _git(vine_rw.forest.root, "rev-parse", "HEAD") == head
        assert not vine_rw.forest.exists("notes/batch-0")

    def test_duplicates_datasets_and_overflow_refuse(self, vine_rw):
        dup = _batch(2)
        dup[1]["id"] = dup[0]["id"]
        with pytest.raises(VineError) as e:
            vine_rw.plant(dup)
        assert "duplicate id" in e.value.message

        with pytest.raises(VineError) as ds:
            vine_rw.plant([{**_batch(1)[0], "type": "dataset",
                            "schema": {"rows": {"columns": {"a": "TEXT"}}}}])
        assert ds.value.code == E_SCHEMA

        with pytest.raises(VineError) as big:
            vine_rw.plant(_batch(21))
        assert "at most 20" in big.value.message

    def test_a_single_dict_keeps_the_old_shape(self, vine_rw):
        out = vine_rw.plant(dict(NOTE))
        assert out["created"] is True and "count" not in out


# -- F.99: a replacement suppresses what it replaced ---------------------------


TERM = "quokkaledger"


class TestSupersede:
    def _two_versions(self, vine):
        for nid, title in (("notes/policy-v1", "Policy v1"),
                           ("notes/policy-v2", "Policy v2")):
            vine.plant({"id": nid, "type": "note", "parent": "notes/_index",
                        "title": title,
                        "summary": f"{title}: the {TERM} rule.",
                        "body": f"# {title}\n\nThe {TERM} rule applies."})
        vine.graft("notes/policy-v2", {
            "add_links": [{"rel": "supersedes",
                           "target": "notes/policy-v1"}]})

    def test_the_replaced_leaves_the_sweep_and_is_named(self, vine_rw):
        self._two_versions(vine_rw)
        out = harvest(vine_rw, TERM, k=5)
        ids = [r["id"] for r in out["results"]]
        assert "notes/policy-v2" in ids
        assert "notes/policy-v1" not in ids
        assert out["superseded_excluded"] == [
            {"id": "notes/policy-v1", "by": ["notes/policy-v2"]}]

    def test_the_history_view_restores_it(self, vine_rw):
        self._two_versions(vine_rw)
        out = harvest(vine_rw, TERM, k=5, include_superseded=True)
        ids = [r["id"] for r in out["results"]]
        assert {"notes/policy-v1", "notes/policy-v2"} <= set(ids)
        assert "superseded_excluded" not in out
        v1 = next(r for r in out["results"] if r["id"] == "notes/policy-v1")
        assert v1["superseded_by"] == ["notes/policy-v2"]

    def test_the_seat_is_refilled(self, vine_rw):
        self._two_versions(vine_rw)
        vine_rw.plant({
            "id": "notes/policy-note", "type": "note",
            "parent": "notes/_index", "title": "Policy note",
            "summary": f"A third note that also mentions {TERM}.",
            "body": f"# Policy note\n\nAnother {TERM} mention."})
        suppressed = harvest(vine_rw, TERM, k=2)
        assert len(suppressed["results"]) == 2, "k is still met"
        assert "notes/policy-v1" not in [r["id"] for r in
                                         suppressed["results"]]

    def test_navigation_never_suppresses(self, vine_rw):
        self._two_versions(vine_rw)
        located = [r["id"] for r in vine_rw.locate(TERM, k=5)["results"]]
        assert "notes/policy-v1" in located
        scanned = [n["id"] for n in vine_rw.scan("notes/_index")["nodes"]]
        assert "notes/policy-v1" in scanned
        assert vine_rw.look("notes/policy-v1")["title"] == "Policy v1"

    def test_a_pruned_superseder_stops_suppressing(self, vine_rw):
        self._two_versions(vine_rw)
        vine_rw.prune("notes/policy-v2")
        ids = [r["id"] for r in harvest(vine_rw, TERM, k=5)["results"]]
        assert "notes/policy-v1" in ids, \
            "only a LIVE node supersedes (the edges died with it)"


# -- F.100: the Gardener records where it came from ---------------------------


SOURCE_MD = "# Adopted\n\nA document that exists outside the forest too.\n"


class TestIngestOrigin:
    def _adopt(self, tmp_path):
        root = tmp_path / "forest-origin"
        init_forest(root, title="Origins")
        src = tmp_path / "src-origin"
        src.mkdir()
        (src / "adopted.md").write_text(SOURCE_MD, encoding="utf-8")
        vine = Vine(root, writable=True)
        Gardener(vine, hooks=[]).adopt(src)
        return vine, src

    def test_adopt_records_the_source_uri(self, tmp_path):
        vine, src = self._adopt(tmp_path)
        origin = vine.look("adopted")["origin"]
        assert origin == (src / "adopted.md").resolve().as_uri()
        assert origin.startswith("file://")
        vine.close()

    def test_a_hand_set_origin_outranks_the_derived_one(self, tmp_path):
        vine, src = self._adopt(tmp_path)
        vine.graft("adopted", {
            "set_frontmatter": {"origin": "https://example.com/canonical"}})
        (src / "adopted.md").write_text(
            SOURCE_MD + "\nEdited.\n", encoding="utf-8")
        Gardener(vine, hooks=[]).sync()
        assert vine.look("adopted")["origin"] == \
            "https://example.com/canonical"
        vine.close()

    def test_a_forest_ingested_before_the_rule_gains_origins_on_sync(
            self, tmp_path):
        vine, src = self._adopt(tmp_path)
        # Strip the origin the way a pre-v0.58 forest has it: absent.
        from monkeyllm.parser import serialize_node

        node = vine.forest.read("adopted")
        fm = {k: v for k, v in node.frontmatter.items() if k != "origin"}
        vine.forest.write("adopted", serialize_node(fm, node.body))
        vine.catalog.upsert_node(vine.forest.read("adopted"))
        assert "origin" not in vine.look("adopted")

        report = Gardener(vine, hooks=[]).sync()
        assert "adopted" in report["updated"], "the fast-path backfills it"
        assert vine.look("adopted")["origin"].startswith("file://")
        # A second sync has nothing left to add.
        assert "adopted" in Gardener(vine, hooks=[]).sync()["unchanged"]
        vine.close()
