"""Harvest (spec C.6c): zero-LLM retrieval returns bananas + exact snippets."""

from monkeyllm.harvest import BUDGET_HARVEST, derive_terms, harvest
from monkeyllm.tokens import estimate_payload_tokens


class TestDeriveTerms:
    def test_drops_stopwords_and_short_words(self):
        terms = derive_terms("Qual foi o resultado do experimento com semente 1045?")
        assert "semente" in terms and "1045" in terms
        assert "qual" not in [t.lower() for t in terms]

    def test_caps_at_eight(self):
        q = " ".join(f"palavra{i:02d}" for i in range(20))
        assert len(derive_terms(q)) == 8


class TestHarvest:
    def test_buried_fact_returns_matched_section(self, vine_ro):
        out = harvest(vine_ro, "resultado do experimento com semente 1045")
        assert out["results"], "harvest must find the buried fact"
        top = out["results"][0]
        assert top["id"] == "projetos/mixerllm/log-experimentos"
        assert "sniff" in top["found_by"]
        # the body exceeds the per-node budget, so content = matched sections
        sections = [c["section"] for c in top["content"]]
        assert "Experimento 45" in sections
        body = next(c["body"] for c in top["content"] if c["section"] == "Experimento 45")
        assert "1045" in body and "descartado" in body

    def test_conceptual_query_returns_full_body(self, vine_ro):
        out = harvest(vine_ro, "política de descontos canal direto")
        top = out["results"][0]
        assert top["id"] == "vendas/politica-descontos"
        assert top["content"][0]["section"] is None  # small body fits whole
        assert "8%" in top["content"][0]["body"]

    def test_respects_k(self, vine_ro):
        out = harvest(vine_ro, "vendas", k=2)
        assert len(out["results"]) <= 2

    def test_every_result_carries_trail_and_summary(self, vine_ro):
        out = harvest(vine_ro, "mixer-lang compressão")
        for r in out["results"]:
            assert r["trail"] is not None
            assert r["summary"]

    def test_budget_enforced_with_explicit_truncation(self, vine_ro):
        # broad query, max k: response must fit the C.6c budget
        out = harvest(vine_ro, "experimento rodada compressão vendas projeto", k=5)
        assert estimate_payload_tokens(out) <= BUDGET_HARVEST
        assert "truncated" in out

    def test_k_is_capped(self, vine_ro):
        out = harvest(vine_ro, "vendas", k=50)
        assert len(out["results"]) <= 5

    def test_mcp_server_exposes_harvest(self, forest_ro):
        from monkeyllm.server import build_server

        mcp = build_server(forest_ro, writable=False)
        try:
            import anyio

            tools = anyio.run(mcp.list_tools)
            assert "harvest" in {t.name for t in tools}
        finally:
            mcp._vine.close()
