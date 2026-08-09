# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Part F criterion 2: plant/graft atomic, git-committed, index-synced."""

import shutil
import stat
import subprocess

import pytest

from monkeyllm.errors import E_NOT_FOUND, E_READONLY, E_SCHEMA, VineError


def git_log(forest, n=1) -> str:
    out = subprocess.run(
        ["git", "-C", str(forest), "log", f"-{n}", "--pretty=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def good_spec(**over):
    spec = {
        "id": "notes/test-learning",
        "type": "note",
        "title": "Test learning",
        "summary": "Note planted by the test suite to verify write atomicity and index synchronization.",
        "parent": "notes/_index",
        "body": "# Test learning\n\n## Content\n\nPlanted by the test.",
        "source": "agent",
    }
    spec.update(over)
    return spec


class TestPlant:
    def test_plant_creates_file_index_entry_and_commit(self, vine_rw, forest_rw):
        before = git_log(forest_rw)
        r = vine_rw.plant(good_spec())
        assert r["id"] == "notes/test-learning"
        assert r["trail"] == ["_index", "notes/_index"]
        assert (forest_rw / "notes" / "test-learning.md").is_file()

        # parent index got the entry with the VERBATIM summary
        idx = (forest_rw / "notes" / "_index.md").read_text(encoding="utf-8")
        assert "[[notes/test-learning]] — Note planted by the test suite" in idx

        # git commit with the standard message
        head = git_log(forest_rw)
        assert head != before
        assert head.startswith("plant(notes/test-learning):")
        assert "[source=agent]" in head
        assert r["commit"]

        # node is immediately navigable
        d = vine_rw.look("notes/test-learning")
        assert d["summary"].startswith("Note planted")

    def test_duplicate_id_rejected(self, vine_rw):
        vine_rw.plant(good_spec())
        with pytest.raises(VineError) as e:
            vine_rw.plant(good_spec())
        assert e.value.code == E_SCHEMA

    def test_unknown_type_rejected(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.plant(good_spec(type="meme"))
        assert e.value.code == E_SCHEMA

    def test_bad_summary_rejected(self, vine_rw):
        with pytest.raises(VineError):
            vine_rw.plant(good_spec(summary="This document describes a note."))

    def test_parent_must_exist_and_match_id_path(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.plant(good_spec(parent="nao/_index"))
        assert e.value.code == E_NOT_FOUND
        with pytest.raises(VineError) as e:
            vine_rw.plant(good_spec(parent="sales/_index"))
        assert e.value.code == E_SCHEMA

    def test_rollback_on_commit_failure(self, vine_rw, forest_rw):
        idx_before = (forest_rw / "notes" / "_index.md").read_text(encoding="utf-8")
        git_dir = forest_rw / ".git"
        moved = forest_rw / ".git-moved"
        git_dir.rename(moved)  # break git -> commit fails mid-transaction
        try:
            with pytest.raises(Exception):
                vine_rw.plant(good_spec())
        finally:
            moved.rename(git_dir)
        assert not (forest_rw / "notes" / "test-learning.md").exists()
        assert (forest_rw / "notes" / "_index.md").read_text(encoding="utf-8") == idx_before

    def test_readonly_vine_cannot_plant(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.plant(good_spec())
        assert e.value.code == E_READONLY


class TestGraft:
    def test_immutable_fields_rejected(self, vine_rw):
        for field in ("id", "type", "created"):
            with pytest.raises(VineError) as e:
                vine_rw.graft("concepts/rag", {"set_frontmatter": {field: "x"}})
            assert e.value.code == E_READONLY

    def test_set_title_and_commit(self, vine_rw, forest_rw):
        r = vine_rw.graft("concepts/rag", {"set_frontmatter": {"title": "Classic RAG"}})
        assert r["commit"]
        assert git_log(forest_rw).startswith("graft(concepts/rag):")
        assert vine_rw.look("concepts/rag")["title"] == "Classic RAG"

    def test_summary_change_propagates_verbatim_to_index(self, vine_rw, forest_rw):
        new_summary = "New RAG summary, rewritten by the test to verify verbatim propagation to the parent index."
        vine_rw.graft("concepts/rag", {"set_frontmatter": {"summary": new_summary}})
        idx = (forest_rw / "concepts" / "_index.md").read_text(encoding="utf-8")
        assert f"[[concepts/rag]] — {new_summary}" in idx

    def test_append_and_replace_section(self, vine_rw):
        vine_rw.graft(
            "concepts/rag",
            {"append_section": {"header": "Agent learnings", "body": "New observation."}},
        )
        p = vine_rw.pick("concepts/rag", section="Agent learnings")
        assert "New observation." in p["body"]

        vine_rw.graft(
            "concepts/rag",
            {"replace_section": {"header": "Agent learnings", "body": "Revised observation."}},
        )
        p = vine_rw.pick("concepts/rag", section="Agent learnings")
        assert "Revised observation." in p["body"]
        assert "New observation." not in p["body"]

    def test_replace_missing_section_not_found(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.graft("concepts/rag", {"replace_section": {"header": "Nothing", "body": "x"}})
        assert e.value.code == E_NOT_FOUND

    def test_add_link_then_duplicate_becomes_fortification(self, vine_rw, forest_rw):
        link = {"rel": "discovered-shortcut", "target": "sales/report-q1-2026"}
        r1 = vine_rw.graft("projects/monkeyllm/monkey-bench", {"add_links": [link]})
        assert r1["commit"] and r1["fortified"] == []
        node = vine_rw.forest.read("projects/monkeyllm/monkey-bench")
        planted = [l for l in node.frontmatter["links"] if l.get("rel") == "discovered-shortcut"]
        assert planted[0]["confidence"] == 0.5  # shout default
        assert planted[0]["discovered_by"] == "agent"

        heat_before = vine_rw.trails.get_heat("sales/report-q1-2026")
        head_before = git_log(forest_rw)
        r2 = vine_rw.graft("projects/monkeyllm/monkey-bench", {"add_links": [link]})
        # reinforce-before-create: no new edge, no commit, heat goes up
        assert r2["commit"] is None
        assert r2["fortified"] == [link]
        assert git_log(forest_rw) == head_before
        assert vine_rw.trails.get_heat("sales/report-q1-2026") > heat_before
        node = vine_rw.forest.read("projects/monkeyllm/monkey-bench")
        again = [l for l in node.frontmatter["links"] if l.get("rel") == "discovered-shortcut"]
        assert len(again) == 1  # never duplicated

    def test_remove_link(self, vine_rw):
        vine_rw.graft(
            "concepts/rag",
            {"remove_links": [{"rel": "compared-with", "target": "projects/monkeyllm/vision"}]},
        )
        node = vine_rw.forest.read("concepts/rag")
        assert not node.frontmatter.get("links")

    def test_unknown_rel_rejected(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.graft("concepts/rag", {"add_links": [{"rel": "hates", "target": "concepts/bm25"}]})
        assert e.value.code == E_SCHEMA

    def test_empty_patch_rejected(self, vine_rw):
        with pytest.raises(VineError):
            vine_rw.graft("concepts/rag", {})

    def test_updated_date_refreshed(self, vine_rw):
        import datetime as dt

        vine_rw.graft("concepts/rag", {"set_frontmatter": {"title": "RAG!"}})
        node = vine_rw.forest.read("concepts/rag")
        assert str(node.frontmatter["updated"]) == dt.date.today().isoformat()
