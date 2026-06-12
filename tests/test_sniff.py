"""C.6b sniff — literal search over bodies (spec v0.2, acceptance F.7)."""

import pytest

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.tokens import estimate_payload_tokens
from monkeyllm.vine import BUDGET_SNIFF, SNIFF_MATCHES_PER_NODE


class TestSniffContract:
    def test_finds_body_only_fact_invisible_to_locate(self, vine_ro):
        """'seed 1045' exists only inside experiment-log's body — locate
        (metadata-only) must miss it, sniff must land on the right node."""
        loc = vine_ro.locate("seed 1045")
        assert all(r["id"] != "projects/mixerllm/experiment-log" for r in loc["results"])

        r = vine_ro.sniff(["seed 1045"])
        assert r["results"], "sniff must find the buried fact"
        top = r["results"][0]
        assert top["id"] == "projects/mixerllm/experiment-log"
        assert "seed 1045" in top["matches"][0]["snippet"].lower()

    def test_result_fields(self, vine_ro):
        r = vine_ro.sniff(["@delega"])
        assert "results" in r and "truncated" in r and "scanned_nodes" in r
        top = r["results"][0]
        for key in ("id", "type", "title", "trail", "score", "heat",
                    "match_count", "truncated_matches", "matches"):
            assert key in top, key
        m = top["matches"][0]
        for key in ("section", "line", "snippet"):
            assert key in m, key

    def test_section_attribution(self, vine_ro):
        r = vine_ro.sniff(["@delega"], k=20)
        by_id = {x["id"]: x for x in r["results"]}
        arq = by_id["projects/mixerllm/architecture"]
        assert any(m["section"] == "Mixer-lang" for m in arq["matches"])

    def test_case_insensitive(self, vine_ro):
        folded = vine_ro.sniff(["AVERAGE COMPRESSION"])  # body says "Average compression"
        assert any(x["id"] == "projects/mixerllm/architecture" for x in folded["results"])

    def test_string_term_promoted_to_list(self, vine_ro):
        assert vine_ro.sniff("seed 1045")["results"]

    def test_multi_term_ranking_prefers_more_terms(self, vine_ro):
        r = vine_ro.sniff(["@delega", "64 symbols"], k=20)
        ids = [x["id"] for x in r["results"]]
        both = ids.index("projects/mixerllm/mixer-lang")  # has both terms
        one = ids.index("projects/mixerllm/architecture")  # only @delega
        assert both < one

    def test_matches_capped_per_node(self, vine_ro):
        r = vine_ro.sniff(["seed"], k=20)
        log = next(x for x in r["results"] if x["id"] == "projects/mixerllm/experiment-log")
        assert len(log["matches"]) <= SNIFF_MATCHES_PER_NODE
        assert log["truncated_matches"] is True
        assert log["match_count"] > SNIFF_MATCHES_PER_NODE


class TestSniffScope:
    def test_scope_restricts_to_subtree(self, vine_ro):
        r = vine_ro.sniff(["approval"], scope="sales", k=20)
        assert r["results"]
        assert all(x["id"].startswith("sales/") for x in r["results"])

    def test_scope_accepts_index_id(self, vine_ro):
        a = vine_ro.sniff(["approval"], scope="sales")
        b = vine_ro.sniff(["approval"], scope="sales/_index")
        assert [x["id"] for x in a["results"]] == [x["id"] for x in b["results"]]

    def test_scope_accepts_banana_id(self, vine_ro):
        """Banana scope = grep within that single node (spec C.6b)."""
        r = vine_ro.sniff(["hit-rate of 73"], scope="projects/mixerllm/experiment-log")
        assert [x["id"] for x in r["results"]] == ["projects/mixerllm/experiment-log"]
        assert r["scanned_nodes"] == 1
        assert any(m["section"] == "Experiment 43" for m in r["results"][0]["matches"])

    def test_scope_not_found(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.sniff(["x1"], scope="nonexistent-branch")
        assert e.value.code == E_NOT_FOUND

    def test_type_filter(self, vine_ro):
        r = vine_ro.sniff(["mixer-lang"], type_filter="event", k=20)
        assert r["results"]
        assert all(x["type"] == "event" for x in r["results"])


class TestSniffValidation:
    def test_rejects_empty_terms(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.sniff([])
        assert e.value.code == E_SCHEMA

    def test_rejects_too_many_terms(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.sniff([f"term{i}" for i in range(9)])
        assert e.value.code == E_SCHEMA

    def test_rejects_short_term(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.sniff(["a"])
        assert e.value.code == E_SCHEMA


class TestSniffBudgetAndHeat:
    def test_budget_with_explicit_truncation(self, vine_ro):
        r = vine_ro.sniff(["de"], k=20)  # ubiquitous term -> many nodes
        assert estimate_payload_tokens(r) <= BUDGET_SNIFF
        assert r["truncated"] is True

    def test_heat_reorders(self, vine_rw):
        cold = vine_rw.sniff(["mixer-lang"], k=10)
        assert len(cold["results"]) > 1
        target = cold["results"][-1]["id"]
        vine_rw.trails.add_heat([target], amount=0.9)
        hot = vine_rw.sniff(["mixer-lang"], k=10)
        t_cold = next(x for x in cold["results"] if x["id"] == target)
        t_hot = next(x for x in hot["results"] if x["id"] == target)
        assert t_hot["score"] > t_cold["score"]
