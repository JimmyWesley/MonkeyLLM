# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.4.4 (spec v0.13): branch rollup — bottom-up branch summaries."""

import json
import subprocess
import textwrap

import pytest

from monkeyllm.curator import Curator
from monkeyllm.forest import init_forest
from monkeyllm.gardener import Gardener, derive_branch_summary
from monkeyllm.models import validate_summary
from monkeyllm.parser import extract_section
from monkeyllm.vine import Vine


@pytest.fixture()
def garden(tmp_path):
    root = tmp_path / "forest"
    init_forest(root, title="Rollup Forest")
    vine = Vine(root, writable=True)
    g = Gardener(vine, hooks=[])
    yield g, vine, root
    vine.close()


@pytest.fixture()
def nested_source(tmp_path):
    """dump/projects/alpha + dump/projects — two branch levels."""
    src = tmp_path / "dump"
    (src / "projects" / "alpha").mkdir(parents=True)
    (src / "projects" / "alpha" / "sensors.md").write_text(
        "# Sensors\n\nAlpha project field sensors and their calibration in 2026.",
        encoding="utf-8")
    (src / "projects" / "alpha" / "budget.md").write_text(
        "# Budget\n\nAlpha project budget: 120k for hardware, 40k for travel.",
        encoding="utf-8")
    (src / "projects" / "roadmap.md").write_text(
        "# Roadmap\n\nPortfolio roadmap for all 2026 projects.", encoding="utf-8")
    return src


def scripted_branch_chat(summaries):
    """One JSON reply per rollup call, recording each prompt."""
    replies = iter(summaries)
    calls = []

    def chat(messages):
        calls.append(messages)
        return json.dumps({"summary": next(replies)})

    chat.calls = calls
    return chat


class TestRollup:
    def test_replaces_ingest_branch_summaries_deepest_first(self, garden, nested_source):
        g, vine, root = garden
        g.adopt(nested_source)

        chat = scripted_branch_chat([
            "Alpha project region: sensors and budget for 2026.",
            "Project portfolio: the Alpha project plus the 2026 roadmap.",
        ])
        report = g.rollup(Curator(chat))

        assert report["rolled"] == ["projects/alpha/_index", "projects/_index"]
        assert report["fallbacks"] == []
        alpha = vine.forest.read("projects/alpha/_index")
        assert alpha.frontmatter["summary"].startswith("Alpha project region")

        # Deepest first: the parent's prompt already carries the child's
        # fresh summary (propagated into its Sub-branches entry line).
        parent_prompt = chat.calls[1][1]["content"]
        assert "Alpha project region" in parent_prompt

    def test_parent_entry_keeps_coverage_suffix(self, garden, nested_source):
        g, vine, root = garden
        g.adopt(nested_source)
        g.rollup(Curator(scripted_branch_chat([
            "Alpha project region: sensors and budget for 2026.",
            "Project portfolio: the Alpha project plus the 2026 roadmap.",
        ])))
        projects = vine.forest.read("projects/_index")
        sec = extract_section(projects.body, "Sub-branches")
        line = next(l for l in sec.splitlines() if "projects/alpha/_index" in l)
        assert "Alpha project region" in line
        assert "2 bananas, 0 sub-branches." in line  # A.5 v0.13: preserved

    def test_hand_authored_branches_untouched_by_default(self, garden, nested_source):
        g, vine, root = garden
        g.adopt(nested_source)
        vine.graft("projects/_index",
                   {"set_frontmatter": {"summary": "Hand-written portfolio scent."}})
        # graft does not change `source`; simulate a curated/hand branch
        path = root / "projects" / "_index.md"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "source: ingest", "source: manual"), encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True,
                       capture_output=True)
        subprocess.run(["git", "commit", "-m", "hand edit"], cwd=root,
                       check=True, capture_output=True)
        vine.catalog.upsert_node(vine.forest.read("projects/_index"))

        report = g.rollup(Curator(scripted_branch_chat([
            "Alpha project region: sensors and budget for 2026."])))
        assert "projects/_index" not in report["rolled"]
        assert report["skipped"] >= 1
        assert vine.forest.read("projects/_index").frontmatter["summary"] == \
            "Hand-written portfolio scent."

    def test_all_scope_rolls_hand_authored_too(self, garden, nested_source):
        g, vine, root = garden
        g.adopt(nested_source)
        report = g.rollup(
            Curator(scripted_branch_chat([
                "Alpha project region: sensors and budget for 2026.",
                "Project portfolio: Alpha plus the 2026 roadmap.",
                "Rollup Forest master: projects portfolio.",
            ])),
            only_ingest=False,
        )
        # master _index has entries (projects/_index) and is now in scope
        assert "_index" in report["rolled"]

    def test_llm_failure_falls_back_deterministically(self, garden, nested_source):
        g, vine, root = garden
        g.adopt(nested_source)

        def broken_chat(messages):
            raise RuntimeError("endpoint down")

        curator = Curator(broken_chat)
        report = g.rollup(curator)
        assert set(report["fallbacks"]) == set(report["rolled"])
        assert curator.stats["branch_fallbacks"] == len(report["fallbacks"])
        alpha = vine.forest.read("projects/alpha/_index")
        validate_summary(alpha.frontmatter["summary"])
        assert "Region 'alpha'" in alpha.frontmatter["summary"]

    def test_no_curator_means_deterministic_rollup(self, garden, nested_source):
        g, vine, root = garden
        g.adopt(nested_source)
        report = g.rollup(None)
        assert report["rolled"]  # deterministic summaries still land
        for branch_id in report["rolled"]:
            validate_summary(vine.forest.read(branch_id).frontmatter["summary"])

    def test_commits_are_md_only(self, garden, nested_source):
        g, vine, root = garden
        g.adopt(nested_source)
        g.rollup(None)
        tracked = subprocess.run(["git", "ls-files"], cwd=root, check=True,
                                 capture_output=True, text=True).stdout
        assert all(f.endswith((".md", ".gitignore")) for f in tracked.split())


class TestDeriveBranchSummary:
    def test_composes_from_titles_and_validates(self):
        s = derive_branch_summary("alpha", ["Sensors", "Budget"])
        validate_summary(s)
        assert "Sensors" in s and "Budget" in s

    def test_many_children_get_elided(self):
        titles = [f"A very long child title number {i}" for i in range(40)]
        s = derive_branch_summary("big", titles)
        validate_summary(s)
        assert "more)" in s

    def test_empty_children_never_raises(self):
        validate_summary(derive_branch_summary("empty", []))
