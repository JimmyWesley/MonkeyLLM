"""Part F criterion 3 (budgets with synthetic giant nodes) + Part D telemetry."""

import json

from monkeyllm.parser import serialize_node
from monkeyllm.tokens import estimate_payload_tokens
from monkeyllm.vine import BUDGET_LOOK, BUDGET_MOVE, MAX_EDGES_SHOWN, PICK_MAX_BODY_TOKENS


def plant_giant_node(vine, forest):
    """Write a pathological node directly (giant body, 30 edges) and reindex."""
    links = [
        {"rel": "relacionado-com", "target": f"conceitos/{c}"}
        for c in (
            "rag", "graphrag", "raptor", "speculative-decoding", "quantizacao",
            "estigmergia", "aco", "bm25", "rrf", "embeddings", "mcp", "slm",
            "wikilink", "frontmatter", "hierarchical-navigation",
            "continuous-batching", "hotpotqa", "memgpt", "sqlite-fts5", "token-budget",
        )
    ]
    fm = {
        "id": "notas/monstro",
        "type": "nota",
        "title": "Nó monstro sintético",
        "summary": "Nó sintético gigante usado para verificar que todos os orçamentos truncam explicitamente.",
        "created": "2026-06-01",
        "updated": "2026-06-10",
        "links": links,
        "source": "manual",
    }
    sections = "\n\n".join(
        f"## Bloco {i:03d}\n\n" + ("conteúdo denso de teste " * 60) for i in range(80)
    )
    path = forest / "notas" / "monstro.md"
    path.write_text(serialize_node(fm, f"# Monstro\n\n{sections}"), encoding="utf-8", newline="\n")
    vine.reindex()


class TestGiantNodeBudgets:
    def test_look_truncates_explicitly(self, vine_rw, forest_rw):
        plant_giant_node(vine_rw, forest_rw)
        d = vine_rw.look("notas/monstro")
        assert estimate_payload_tokens(d) <= BUDGET_LOOK
        assert len(d["edges_out"]) <= MAX_EDGES_SHOWN
        assert d["stats"]["degree"] >= 20  # excess indicated via degree

    def test_pick_giant_returns_outline_not_body(self, vine_rw, forest_rw):
        plant_giant_node(vine_rw, forest_rw)
        p = vine_rw.pick("notas/monstro")
        assert p["truncated"] is True and "body" not in p
        assert p["body_tokens"] > PICK_MAX_BODY_TOKENS

    def test_move_truncates_explicitly(self, vine_rw, forest_rw):
        plant_giant_node(vine_rw, forest_rw)
        r = vine_rw.move("notas/monstro", direction="both")
        assert estimate_payload_tokens(r) <= BUDGET_MOVE
        assert r["truncated"] is True  # 20 fat neighbors cannot fit 600 tokens


class TestTelemetry:
    def test_every_call_is_traced(self, vine_rw):
        vine_rw.locate("vendas")
        vine_rw.look("vendas/_index")
        vine_rw.pick("vendas/devolucoes-q1")
        lines = [
            json.loads(l)
            for l in vine_rw.tracer.trace_path.read_text(encoding="utf-8").splitlines()
        ]
        prims = [e["primitive"] for e in lines if "primitive" in e]
        assert prims == ["locate", "look", "pick"]
        for e in lines:
            if "primitive" in e:
                assert {"ts", "session", "id", "tokens_in", "tokens_out", "elapsed_ms"} <= set(e)

    def test_close_session_reinforces_winning_trail(self, vine_rw):
        vine_rw.locate("devoluções sensor")
        vine_rw.look("vendas/devolucoes-q1")
        vine_rw.pick("vendas/devolucoes-q1")
        before = vine_rw.trails.get_heat("vendas/_index")
        outcome = vine_rw.close_session(True, ["vendas/devolucoes-q1"])
        assert outcome["outcome"]["success"] is True
        assert vine_rw.trails.get_heat("vendas/_index") > before
        assert vine_rw.trails.get_heat("vendas/devolucoes-q1") > 0

    def test_metrics_hops_and_tokens(self, vine_rw):
        vine_rw.look("_index")
        vine_rw.move("vendas/_index", rel="children")
        vine_rw.pick("vendas/metas-2026")
        m = vine_rw.tracer.metrics()
        assert m["hops_to_banana"] == 2  # look + move before first pick
        assert m["tokens_to_banana"] > 0
        assert m["calls"] == 3

    def test_failed_session_does_not_reinforce(self, vine_rw):
        vine_rw.look("vendas/_index")
        outcome = vine_rw.close_session(False, [])
        assert outcome["outcome"]["success"] is False
        assert vine_rw.trails.get_heat("vendas/_index") == 0
