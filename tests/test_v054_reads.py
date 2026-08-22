# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The wire is for machines (spec v0.54, engine half — F.69/F.70/F.71/F.72/F.74).

An LLM harness consumed this product through four measured rounds and
reported where the contract still assumed a human reader. The engine's share:
enums that fell back silently, a forest that could not be enumerated, sizes
absent where nodes are offered, a demotion invisible on the wire, a body edit
that ages the summary with nobody told, and the team's own vocabulary
(`BE-291`) resolving to nothing.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.forest import init_forest
from monkeyllm.gardener import MEDIA_STUB_SENTINEL, Gardener
from monkeyllm.harvest import harvest
from monkeyllm.ranger import Ranger
from monkeyllm.vine import Vine


# --- F.69: an enum refuses what it does not accept --------------------------

class TestEnumsRefuse:
    def test_move_direction_all_is_a_refusal_not_an_empty_list(self, vine_ro):
        # The observed mistake: "all" borrowed from locate's scope. On a
        # node with degree > 0 an empty list is byte-identical to an
        # isolated node.
        node = "projects/mixerllm/architecture"
        assert vine_ro.move(node, direction="both")["neighbors"]
        with pytest.raises(VineError) as e:
            vine_ro.move(node, direction="all")
        assert e.value.code == E_SCHEMA
        assert "direction" in e.value.message and "'all'" in e.value.message
        assert "both" in e.value.message  # the accepted set is named

    def test_every_accepted_direction_still_answers(self, vine_ro):
        node = "projects/mixerllm/architecture"
        for direction in ("out", "in", "both"):
            assert "neighbors" in vine_ro.move(node, direction=direction)

    def test_locate_scope_typo_is_refused_not_searched_as_all(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.locate("model", scope="everything")
        assert e.value.code == E_SCHEMA and "scope" in e.value.message

    def test_scan_unknown_field_is_refused_not_omitted(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.scan("projects/_index", fields=["id", "sumary"])
        assert e.value.code == E_SCHEMA and "sumary" in e.value.message

    def test_scan_fields_never_list_payload_locations(self, vine_ro):
        for private in ("payload", "payload_hash", "body_hash", "stale"):
            with pytest.raises(VineError):
                vine_ro.scan("projects/_index", fields=[private])


# --- F.70: the forest is enumerable ----------------------------------------

class TestScanEnumerates:
    def test_every_scan_says_total_and_returned(self, vine_ro):
        r = vine_ro.scan("_index", recursive=True, limit=50)
        assert r["total"] > r["returned"] > 0
        assert r["truncated"] is True

    def test_the_cursor_walks_the_whole_forest_once(self, vine_ro):
        ids, after = [], ""
        total = None
        for _ in range(50):  # a bound, not a hope
            page = vine_ro.scan("_index", recursive=True, limit=50,
                                after=after)
            total = page["total"]
            ids += [n["id"] for n in page["nodes"]]
            if "next" not in page:
                break
            assert page["next"] == page["nodes"][-1]["id"]
            after = page["next"]
        assert len(ids) == len(set(ids)) == total
        assert ids == sorted(ids)  # id order: stable, resumable

    def test_the_final_page_carries_no_next(self, vine_ro):
        page = vine_ro.scan("projects/_index", after="")
        assert "next" not in page and page["returned"] == page["total"]

    def test_a_cursor_beside_a_ranking_is_refused(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.scan("_index", recursive=True, after="", toward="sales")
        assert e.value.code == E_SCHEMA

    def test_without_after_the_shape_is_heat_ordered_as_before(self, vine_ro):
        r = vine_ro.scan("projects/_index")
        assert "next" not in r
        assert {"total", "returned", "nodes", "truncated"} <= set(r)

    def test_default_fields_carry_body_tokens(self, vine_ro):
        r = vine_ro.scan("projects/_index")
        assert all(isinstance(n.get("body_tokens"), int) for n in r["nodes"])

    def test_the_system_node_says_so(self, vine_ro):
        page = vine_ro.scan("_index", recursive=True, limit=50, after="_met")
        marked = {n["id"]: n.get("system") for n in page["nodes"]}
        assert marked.get("_meta/schema") is True
        assert all(v is None for i, v in marked.items() if i != "_meta/schema")


# --- F.70 (the other two reads): size travels with every discovery ----------

class TestBodyTokensEverywhere:
    def test_sniff_results_carry_body_tokens(self, vine_ro):
        r = vine_ro.sniff(["mixerllm"], k=10)
        assert r["results"]
        for hit in r["results"]:
            assert hit["body_tokens"] == vine_ro.look(
                hit["id"], fields=["stats"])["stats"]["body_tokens"]

    def test_harvest_items_carry_body_tokens(self, vine_ro):
        out = harvest(vine_ro, "stigmergy sales", k=3)
        assert out["results"]
        assert all(isinstance(i["body_tokens"], int) for i in out["results"])

    def test_the_demotion_is_visible_and_the_score_still_true(self, vine_ro):
        # "block-loop" lives in content bodies AND in index entry lines, so
        # the result set holds both kinds.
        r = vine_ro.sniff(["block-loop"], k=20)
        index_hits = [h for h in r["results"] if h["id"].endswith("_index")]
        content_hits = [h for h in r["results"]
                        if not h["id"].endswith("_index")]
        assert index_hits and content_hits, "the term must hit both kinds"
        assert all(h["demoted"] is True for h in index_hits)
        assert all("demoted" not in h for h in content_hits)
        # Demoted in the order, never in the score: every index hit sits
        # after every content hit, whatever the numbers say.
        first_index = r["results"].index(index_hits[0])
        assert all(r["results"].index(c) < first_index for c in content_hits)

    def test_coverage_is_counts_not_prose(self, vine_ro):
        loc = vine_ro.locate("inference projects", scope="branches", k=5)
        cov = loc["results"][0]["coverage"]
        assert set(cov) == {"notes", "branches"}
        assert all(isinstance(v, int) for v in cov.values())
        assert vine_ro.look("projects/_index")["coverage"] == {
            "notes": 1, "branches": 2}


# --- F.71: a write that outdates the scent says so --------------------------

class TestGraftSaysSo:
    def test_body_edit_without_summary_flags_summary_stale(self, vine_rw):
        r = vine_rw.graft("concepts/rag", {
            "append_section": {"header": "Update", "body": "New facts."}})
        assert r["summary_stale"] is True

    def test_body_edit_with_summary_in_the_same_patch_does_not(self, vine_rw):
        r = vine_rw.graft("concepts/rag", {
            "append_section": {"header": "Update", "body": "New facts."},
            "set_frontmatter": {"summary": "Retrieval-augmented generation, "
                                           "updated with new facts."}})
        assert "summary_stale" not in r

    def test_a_frontmatter_only_graft_does_not(self, vine_rw):
        r = vine_rw.graft("concepts/rag", {
            "set_frontmatter": {"tags": ["retrieval"]}})
        assert "summary_stale" not in r

    def test_aliases_are_mutable_and_locate_finds_them(self, vine_rw):
        vine_rw.graft("concepts/rag", {
            "set_frontmatter": {"aliases": ["ZZ-99", "concepts/99"]}})
        hits = vine_rw.locate("ZZ-99", k=3)["results"]
        assert hits and hits[0]["id"] == "concepts/rag"

    def test_alias_bounds_are_enforced(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.graft("concepts/rag", {
                "set_frontmatter": {"aliases": [f"A-{i}" for i in range(17)]}})
        assert e.value.code == E_SCHEMA
        with pytest.raises(VineError):
            vine_rw.graft("concepts/rag", {
                "set_frontmatter": {"aliases": ["ok", "  "]}})


# --- F.72: the team's own name for a document (G.2.6) -----------------------

TASK_MD = textwrap.dedent("""\
    # 291 — Provider budget enforcement

    Enforce the provider budget on every call and refuse past the ceiling.
    """)


def _adopted(tmp_path, with_map: bool):
    root = tmp_path / ("forest-map" if with_map else "forest-bare")
    init_forest(root, title="Aliases")
    if with_map:
        (root / "_meta" / "gardener.yaml").write_text(
            "aliases:\n  targets: BE\n", encoding="utf-8")
    src = tmp_path / ("src-map" if with_map else "src-bare")
    (src / "targets").mkdir(parents=True)
    (src / "targets" / "291-budget.md").write_text(TASK_MD, encoding="utf-8")
    vine = Vine(root, writable=True)
    Gardener(vine, hooks=[]).adopt(src)
    return vine


class TestIngestAliases:
    def test_the_declared_map_derives_both_spellings(self, tmp_path):
        vine = _adopted(tmp_path, with_map=True)
        node = vine.forest.read("targets/291-budget")
        # v0.59 (G.2.6 rule 2) added the bare number: it is how a document
        # is referred to inside its own folder, and it is free.
        assert node.frontmatter["aliases"] == ["BE-291", "targets/291", "291"]
        hits = vine.locate("BE-291", k=3)["results"]
        assert hits and hits[0]["id"] == "targets/291-budget"
        vine.close()

    def test_without_a_map_the_source_still_names_itself(self, tmp_path):
        """G.2.6 rule 1 (v0.59): the boundary is not "no map, no aliases" —
        it is who knows the name. `targets` is a single word, so no letter
        prefix is invented from it; the number and the path form are what
        the source itself states."""
        vine = _adopted(tmp_path, with_map=False)
        node = vine.forest.read("targets/291-budget")
        assert node.frontmatter["aliases"] == ["targets/291", "291"]
        assert vine.locate("targets/291", k=3)["results"]
        # The convention `targets` means `BE` is the operator's to declare.
        assert not vine.locate("BE-291", k=3)["results"]
        vine.close()

    def test_a_map_added_later_reaches_unchanged_files_via_sync(self, tmp_path):
        # G.2.6 rule 3 (v0.56): the operator's exact field sequence — adopt
        # with no map, add the map, run sync. The fast-path skips the
        # conversion, never the alias check, so the union lands anyway.
        vine = _adopted(tmp_path, with_map=False)
        cfg = Path(vine.forest.root) / "_meta" / "gardener.yaml"
        cfg.write_text(cfg.read_text(encoding="utf-8")
                       + "aliases:\n  targets: BE\n", encoding="utf-8")
        report = Gardener(vine, hooks=[]).sync()
        assert "targets/291-budget" in report["updated"]
        node = vine.forest.read("targets/291-budget")
        # Union, in the order the two passes ran: the derived forms landed
        # at adopt, the declared prefix joins them now.
        assert node.frontmatter["aliases"] == ["targets/291", "291", "BE-291"]
        assert vine.locate("BE-291", k=3)["results"]
        # A second sync has nothing to add: unchanged again, not rewritten.
        again = Gardener(vine, hooks=[]).sync()
        assert "targets/291-budget" in again["unchanged"]
        vine.close()

    def test_the_union_adds_and_never_removes(self, tmp_path):
        vine = _adopted(tmp_path, with_map=True)
        # Somebody curated their own name onto the node…
        vine.graft("targets/291-budget", {
            "set_frontmatter": {"aliases": ["BE-291", "targets/291", "291",
                                            "the-budget-task"]}})
        report = Gardener(vine, hooks=[]).sync()
        assert report["aliases_clipped"] == 0
        node = vine.forest.read("targets/291-budget")
        # …and the refresh left it exactly where they put it.
        assert node.frontmatter["aliases"] == ["BE-291", "targets/291", "291",
                                               "the-budget-task"]
        vine.close()


# --- F.74: an undescribed media node is counted -----------------------------

def test_health_counts_media_needing_description(tmp_path):
    root = tmp_path / "forest-media"
    init_forest(root, title="Media")
    src = tmp_path / "src-media"
    src.mkdir()
    (src / "team-photo.png").write_bytes(b"\x89PNG\r\n\x1a\nnot-really")
    vine = Vine(root, writable=True)
    Gardener(vine, hooks=[]).adopt(src)
    node = vine.forest.read("team-photo")
    assert node.frontmatter["type"] == "media"
    assert MEDIA_STUB_SENTINEL in node.body
    report = Ranger(vine).health()
    assert report["needs_description"] == ["team-photo"]
    # A described one leaves the list: the sentinel is the whole test.
    vine.graft("team-photo", {"replace_body": "# Team photo\n\n"
                              "Five people around a whiteboard."})
    assert Ranger(vine).health()["needs_description"] == []
    vine.close()
