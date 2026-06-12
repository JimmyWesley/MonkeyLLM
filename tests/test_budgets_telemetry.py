"""Part F criterion 3 (budgets with synthetic giant nodes) + Part D telemetry."""

import json

from monkeyllm.parser import serialize_node
from monkeyllm.tokens import estimate_payload_tokens
from monkeyllm.vine import BUDGET_LOOK, BUDGET_MOVE, MAX_EDGES_SHOWN, PICK_MAX_BODY_TOKENS


def plant_giant_node(vine, forest):
    """Write a pathological node directly (giant body, 30 edges) and reindex."""
    links = [
        {"rel": "related-to", "target": f"concepts/{c}"}
        for c in (
            "rag", "graphrag", "raptor", "speculative-decoding", "quantization",
            "stigmergy", "aco", "bm25", "rrf", "embeddings", "mcp", "slm",
            "wikilink", "frontmatter", "hierarchical-navigation",
            "continuous-batching", "hotpotqa", "memgpt", "sqlite-fts5", "token-budget",
        )
    ]
    fm = {
        "id": "notes/monster",
        "type": "note",
        "title": "Synthetic monster node",
        "summary": "Giant synthetic node used to verify that every budget truncates explicitly.",
        "created": "2026-06-01",
        "updated": "2026-06-10",
        "links": links,
        "source": "manual",
    }
    sections = "\n\n".join(
        f"## Block {i:03d}\n\n" + ("dense test content " * 60) for i in range(80)
    )
    path = forest / "notes" / "monster.md"
    path.write_text(serialize_node(fm, f"# Monster\n\n{sections}"), encoding="utf-8", newline="\n")
    vine.reindex()


class TestGiantNodeBudgets:
    def test_look_truncates_explicitly(self, vine_rw, forest_rw):
        plant_giant_node(vine_rw, forest_rw)
        d = vine_rw.look("notes/monster")
        assert estimate_payload_tokens(d) <= BUDGET_LOOK
        assert len(d["edges_out"]) <= MAX_EDGES_SHOWN
        assert d["stats"]["degree"] >= 20  # excess indicated via degree

    def test_pick_giant_returns_outline_not_body(self, vine_rw, forest_rw):
        plant_giant_node(vine_rw, forest_rw)
        p = vine_rw.pick("notes/monster")
        assert p["truncated"] is True and "body" not in p
        assert p["body_tokens"] > PICK_MAX_BODY_TOKENS

    def test_move_truncates_explicitly(self, vine_rw, forest_rw):
        plant_giant_node(vine_rw, forest_rw)
        r = vine_rw.move("notes/monster", direction="both")
        assert estimate_payload_tokens(r) <= BUDGET_MOVE
        assert r["truncated"] is True  # 20 fat neighbors cannot fit 600 tokens


class TestTelemetry:
    def test_every_call_is_traced(self, vine_rw):
        vine_rw.locate("sales")
        vine_rw.look("sales/_index")
        vine_rw.pick("sales/returns-q1")
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
        vine_rw.locate("defects sensor")
        vine_rw.look("sales/returns-q1")
        vine_rw.pick("sales/returns-q1")
        before = vine_rw.trails.get_heat("sales/_index")
        outcome = vine_rw.close_session(True, ["sales/returns-q1"])
        assert outcome["outcome"]["success"] is True
        assert vine_rw.trails.get_heat("sales/_index") > before
        assert vine_rw.trails.get_heat("sales/returns-q1") > 0

    def test_metrics_hops_and_tokens(self, vine_rw):
        vine_rw.look("_index")
        vine_rw.move("sales/_index", rel="children")
        vine_rw.pick("sales/targets-2026")
        m = vine_rw.tracer.metrics()
        assert m["hops_to_banana"] == 2  # look + move before first pick
        assert m["tokens_to_banana"] > 0
        assert m["calls"] == 3

    def test_failed_session_does_not_reinforce(self, vine_rw):
        vine_rw.look("sales/_index")
        outcome = vine_rw.close_session(False, [])
        assert outcome["outcome"]["success"] is False
        assert vine_rw.trails.get_heat("sales/_index") == 0

    def test_shout_fires_on_long_pick_chain(self, vine_rw):
        """Spec v0.6: pick chains count toward the shout, not just look/move."""
        vine_rw.locate("defects sensor")
        vine_rw.pick("sales/returns-q1")
        vine_rw.locate("sensor x")
        vine_rw.pick("products/sensor-x")
        vine_rw.pick("people/jimmy-wesley")
        outcome = vine_rw.close_session(True, ["people/jimmy-wesley"])
        assert outcome["metrics"]["trail_len"] == 4
        assert outcome["metrics"]["hops_to_banana"] == 0  # unchanged metric
        assert outcome["suggest_shortcuts"] == ["people/jimmy-wesley"]

    def test_short_hunt_does_not_shout(self, vine_rw):
        vine_rw.locate("commercial targets")
        vine_rw.pick("sales/targets-2026")
        outcome = vine_rw.close_session(True, ["sales/targets-2026"])
        assert outcome["metrics"]["trail_len"] == 1
        assert outcome["suggest_shortcuts"] == []
