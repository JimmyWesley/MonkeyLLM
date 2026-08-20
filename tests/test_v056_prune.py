# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.56 C.14 — prune, the write you can take back (F.85).

The consumer team's probe nodes tagged `delete-me` were the measurement:
an agent that cannot undo writes to the disk instead, where `rm` exists.
These tests hold the four sides of the contract: what a prune removes,
what refuses it (anchors, children), what `force` may and may not do
under a scope, and that a pruned id is free again.
"""

from __future__ import annotations

import subprocess

import pytest

from monkeyllm.errors import VineError

NOTE = {"id": "notes/probe", "type": "note", "parent": "notes/_index",
        "title": "Probe", "summary": "A test artifact, safe to delete.",
        "body": "Evidence."}


def _git_log(root) -> str:
    return subprocess.run(["git", "-C", str(root), "log", "--format=%s"],
                          capture_output=True, text=True).stdout


class TestPruneRemoves:
    def test_a_leaf_leaves_whole(self, vine_rw, forest_rw):
        vine_rw.plant(dict(NOTE))
        r = vine_rw.prune("notes/probe")
        assert r["pruned"] is True and r["commit"]
        assert r["backlinks_removed"] == 0 and r["payload_moved"] is None
        # The passport is gone from the tree and from the catalog…
        assert not (forest_rw / "notes" / "probe.md").exists()
        assert vine_rw.catalog.get("notes/probe") is None
        with pytest.raises(VineError):
            vine_rw.look("notes/probe")
        # …the parent index no longer lists it…
        assert "notes/probe" not in vine_rw.forest.read("notes/_index").body
        # …and git history keeps every byte (soft by construction).
        assert "prune(notes/probe)" in _git_log(forest_rw)

    def test_a_pruned_id_is_free(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        vine_rw.prune("notes/probe")
        again = vine_rw.plant(dict(NOTE))
        assert again["created"] is True

    def test_a_dataset_payload_moves_to_the_graveyard(self, vine_rw, forest_rw):
        vine_rw.plant({
            "id": "notes/probe-data", "type": "dataset",
            "parent": "notes/_index", "title": "Probe data",
            "summary": "A throwaway dataset.",
            "schema": {"t": {"columns": {"a": "TEXT"}}},
        })
        r = vine_rw.prune("notes/probe-data")
        assert r["payload_moved"].startswith("_derived/graveyard/")
        assert (forest_rw / r["payload_moved"]).is_file()

    def test_the_root_and_system_nodes_refuse(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.prune("_index")
        assert e.value.code == "E_SCHEMA"
        with pytest.raises(VineError) as e:
            vine_rw.prune("_meta/schema")
        assert e.value.code == "E_SCHEMA"


class TestAnchorsRefuse:
    def _anchored(self, vine):
        vine.plant(dict(NOTE))
        vine.graft("sales/returns-q1",
                   {"add_links": [{"rel": "related-to",
                                   "target": "notes/probe"}]})

    def test_edges_in_refuse_and_name_the_anchors(self, vine_rw):
        self._anchored(vine_rw)
        with pytest.raises(VineError) as e:
            vine_rw.prune("notes/probe")
        assert e.value.code == "E_ANCHORED"
        env = e.value.to_dict()["error"]
        assert env["anchor_count"] == 1
        assert env["anchors"] == [{"source": "sales/returns-q1",
                                   "rel": "related-to"}]

    def test_force_strips_the_backlinks_in_the_same_commit(self, vine_rw,
                                                           forest_rw):
        self._anchored(vine_rw)
        r = vine_rw.prune("notes/probe", force=True)
        assert r["backlinks_removed"] == 1
        links = vine_rw.forest.read("sales/returns-q1").frontmatter.get(
            "links") or []
        assert all(l["target"] != "notes/probe" for l in links)
        # One commit did both: nothing points at the hole.
        assert vine_rw.catalog.edges_in("notes/probe") == []
        assert "prune(notes/probe)" in _git_log(forest_rw)

    def test_a_branch_with_children_never_prunes(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.prune("sales/_index", force=True)
        assert e.value.code == "E_ANCHORED"
        assert "children" in e.value.message

    def test_an_empty_branch_prunes(self, vine_rw, forest_rw):
        vine_rw.plant({"id": "empty/_index", "type": "branch",
                       "parent": "_index", "title": "Empty",
                       "summary": "A region with nothing in it."})
        r = vine_rw.prune("empty/_index")
        assert r["pruned"] is True
        assert not (forest_rw / "empty").exists()


class TestPruneUnderAPolicy:
    def _scoped(self, vine, prefixes, caps=("read", "write")):
        import sys
        from pathlib import Path
        station = Path(__file__).resolve().parents[1] / "apps" / "station"
        if str(station) not in sys.path:
            sys.path.insert(0, str(station))
        from monkeyllm_station.policy import Policy, ScopedVine
        return ScopedVine(vine, Policy(forest="f", caps=frozenset(caps),
                                       allow=tuple(prefixes)))

    def test_out_of_scope_answers_exactly_as_absent(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        scoped = self._scoped(vine_rw, ["sales/"])
        with pytest.raises(VineError) as hidden:
            scoped.prune("notes/probe")
        with pytest.raises(VineError) as absent:
            scoped.prune("sales/never-existed")
        # Byte-identical up to the id the caller itself supplied: same code,
        # same message template, same hint (J.3's no-existence-oracle).
        norm = lambda e, nid: str(e.to_dict()).replace(nid, "<id>")  # noqa: E731
        assert (norm(hidden.value, "notes/probe")
                == norm(absent.value, "sales/never-existed"))

    def test_force_refuses_when_an_anchor_is_outside_the_scope(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        vine_rw.graft("sales/returns-q1",
                      {"add_links": [{"rel": "related-to",
                                      "target": "notes/probe"}]})
        scoped = self._scoped(vine_rw, ["notes/"])
        with pytest.raises(VineError) as e:
            scoped.prune("notes/probe", force=True)
        assert e.value.code == "E_ANCHORED"
        env = e.value.to_dict()["error"]
        # The count is reported; the out-of-scope node is never named (J.3).
        assert "sales/returns-q1" not in str(env)

    def test_the_refusal_names_only_visible_anchors(self, vine_rw):
        vine_rw.plant(dict(NOTE))
        vine_rw.graft("sales/returns-q1",
                      {"add_links": [{"rel": "related-to",
                                      "target": "notes/probe"}]})
        scoped = self._scoped(vine_rw, ["notes/"])
        with pytest.raises(VineError) as e:
            scoped.prune("notes/probe")
        env = e.value.to_dict()["error"]
        assert env["anchors"] == [] and env["anchor_count"] == 1
        assert env["out_of_scope"] == 1
