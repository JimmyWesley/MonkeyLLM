# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Harvest (spec C.6c): zero-LLM retrieval returns bananas + exact snippets."""

import pytest

from monkeyllm.errors import VineError
from monkeyllm.harvest import (BUDGET_HARVEST, clamp_k, derive_terms, harvest,
                               harvest_max_k)
from monkeyllm.tokens import estimate_payload_tokens


class TestDeriveTerms:
    def test_drops_stopwords_and_short_words(self):
        terms = derive_terms("What was the result of the experiment with seed 1045?")
        assert "seed" in terms and "1045" in terms
        assert "what" not in [t.lower() for t in terms]

    def test_caps_at_eight(self):
        q = " ".join(f"word{i:02d}" for i in range(20))
        assert len(derive_terms(q)) == 8


class TestHarvest:
    def test_buried_fact_returns_matched_section(self, vine_ro):
        # "1045" and "discarded" are only in the experiment-log body, not in the index
        out = harvest(vine_ro, "seed 1045 discarded")
        assert out["results"], "harvest must find the buried fact"
        exp = next((r for r in out["results"] if r["id"] == "projects/mixerllm/experiment-log"), None)
        assert exp is not None, "experiment-log must be in harvest results"
        assert "sniff" in exp["found_by"]
        # the body exceeds the per-node budget, so content = matched sections
        sections = [c["section"] for c in exp["content"]]
        assert "Experiment 45" in sections
        body = next(c["body"] for c in exp["content"] if c["section"] == "Experiment 45")
        assert "1045" in body and "discarded" in body

    def test_conceptual_query_returns_full_body(self, vine_ro):
        # "without approval" and "8%" are in the body of discount-policy, not just its summary
        out = harvest(vine_ro, "sales discount-policy direct without approval")
        disc = next((r for r in out["results"] if r["id"] == "sales/discount-policy"), None)
        assert disc is not None
        assert disc["content"][0]["section"] is None  # small body fits whole
        assert "8%" in disc["content"][0]["body"]

    def test_respects_k(self, vine_ro):
        out = harvest(vine_ro, "sales", k=2)
        assert len(out["results"]) <= 2

    def test_every_result_carries_trail_and_summary(self, vine_ro):
        out = harvest(vine_ro, "mixer-lang compression")
        for r in out["results"]:
            assert r["trail"] is not None
            assert r["summary"]

    def test_budget_enforced_with_explicit_truncation(self, vine_ro):
        # broad query, max k: response must fit the C.6c budget
        out = harvest(vine_ro, "experiment run compression sales project", k=5)
        assert estimate_payload_tokens(out) <= BUDGET_HARVEST
        assert "truncated" in out

    def test_k_is_capped(self, vine_ro):
        out = harvest(vine_ro, "sales", k=50)
        assert len(out["results"]) <= 5

    def test_cap_from_env_wins(self, vine_ro, monkeypatch):
        monkeypatch.setenv("MONKEYLLM_HARVEST_MAX_K", "1")
        out = harvest(vine_ro, "experiment run compression sales project", k=50)
        assert len(out["results"]) == 1

    def test_unset_env_keeps_the_old_cap(self, vine_ro, monkeypatch):
        monkeypatch.delenv("MONKEYLLM_HARVEST_MAX_K", raising=False)
        out = harvest(vine_ro, "sales", k=50)
        assert len(out["results"]) <= 5

    def test_raised_cap_still_respects_the_budget(self, vine_ro, monkeypatch):
        monkeypatch.setenv("MONKEYLLM_HARVEST_MAX_K", "12")
        out = harvest(vine_ro, "experiment run compression sales project", k=12)
        assert estimate_payload_tokens(out) <= BUDGET_HARVEST
        assert "truncated" in out

    def test_clamp_is_the_effective_k(self, monkeypatch):
        monkeypatch.setenv("MONKEYLLM_HARVEST_MAX_K", "8")
        assert clamp_k(50) == 8
        assert clamp_k(3) == 3
        assert clamp_k(0) == 1
        monkeypatch.delenv("MONKEYLLM_HARVEST_MAX_K")
        assert clamp_k(50) == 5

    @pytest.mark.parametrize("bad", ["0", "-3", "banana", "5.5"])
    def test_garbage_cap_is_refused_never_rounded(self, bad, monkeypatch):
        monkeypatch.setenv("MONKEYLLM_HARVEST_MAX_K", bad)
        with pytest.raises(VineError) as exc:
            harvest_max_k()
        assert "MONKEYLLM_HARVEST_MAX_K" in str(exc.value)

    def test_mcp_server_exposes_harvest(self, forest_ro):
        from monkeyllm.server import build_server

        mcp = build_server(forest_ro, writable=False)
        try:
            import anyio

            tools = anyio.run(mcp.list_tools)
            assert "harvest" in {t.name for t in tools}
        finally:
            mcp._close()


def test_a_dataset_carries_its_notes_into_the_sweep(tmp_path):
    """C.2.1 rule 6: `look` is on the walk's path and not the sweep's, so a
    teaching that only rides in the digest is invisible from the console's
    ordinary ask — which is where it will actually be written."""
    from monkeyllm.forest import init_forest
    from monkeyllm.gardener import Gardener
    from monkeyllm.harvest import harvest
    from monkeyllm.vine import Vine

    root = tmp_path / "forest"
    init_forest(root, title="T")
    src = tmp_path / "src"
    src.mkdir()
    (src / "leads.csv").write_text("cliente,total\nKATUN BRASIL,1200\nAcme,300\n",
                                   encoding="utf-8")
    vine = Vine(root, writable=True)
    Gardener(vine, hooks=[]).adopt(src)

    assert "notes" not in harvest(vine, "faturamento KATUN")["results"][0]

    vine.graft("leads", {"append_section": {
        "header": "Notes",
        "body": "Use LIKE on text columns — names carry suffixes."}})

    # Deliberately a question sharing no vocabulary with the note: whether
    # a person's instructions match today's terms is not a reason to
    # withhold them.
    item = harvest(vine, "faturamento KATUN")["results"][0]
    assert item["notes"] == "Use LIKE on text columns — names carry suffixes."
