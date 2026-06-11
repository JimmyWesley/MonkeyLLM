"""End-to-end agent-loop test with a scripted model (no network, no GPU).

Proves the demo harness machinery: master-index priming, JSON action
parsing, primitive dispatch, error envelope feedback, session close and
metrics — everything except the actual LLM.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))

from run_demo import parse_action, run_question  # noqa: E402

Q2 = {
    "id": "q02",
    "question": "Qual região teve o maior total de vendas no Q1 2026?",
    "expected_nodes": ["vendas/relatorio-q1-2026"],
    "answer_contains": ["Sudeste"],
}


def scripted_chat_factory(script):
    replies = iter(script)

    def chat(messages):
        return next(replies)

    return chat


class TestParseAction:
    def test_plain_json(self):
        assert parse_action('{"tool": "look", "args": {"id": "x"}}')["tool"] == "look"

    def test_json_inside_prose(self):
        text = 'Vou olhar o índice.\n{"tool": "locate", "args": {"query": "vendas"}}\nPronto.'
        assert parse_action(text)["tool"] == "locate"

    def test_garbage_returns_none(self):
        assert parse_action("não sei o que fazer") is None


class TestScriptedHunt:
    def test_multihop_sql_question(self, forest_ro):
        script = [
            '{"tool": "locate", "args": {"query": "vendas região Q1 2026", "k": 3}}',
            '{"tool": "look", "args": {"id": "vendas/relatorio-q1-2026"}}',
            '{"tool": "query", "args": {"id": "vendas/relatorio-q1-2026", '
            '"sql": "SELECT regiao, SUM(valor) AS total FROM vendas GROUP BY regiao ORDER BY total DESC LIMIT 1"}}',
            '{"tool": "answer", "args": {"text": "A região com maior venda no Q1 2026 foi o Sudeste.", '
            '"answer_nodes": ["vendas/relatorio-q1-2026"]}}',
        ]
        r = run_question(forest_ro, scripted_chat_factory(script), Q2, verbose=False)
        assert r["correct_text"] is True
        assert r["banana_precision"] == 1.0
        m = r["metrics"]
        assert m["hops_to_banana"] == 2  # master-index look + dataset look before the query
        assert m["tokens_to_banana"] > 0
        # trace file exists with the outcome line
        lines = Path(r["trace"]).read_text(encoding="utf-8").splitlines()
        events = [json.loads(l) for l in lines]
        assert any("outcome" in e for e in events)

    def test_recovers_from_bad_tool_and_format(self, forest_ro):
        script = [
            "vou pensar primeiro...",  # invalid -> harness asks for JSON
            '{"tool": "telepatia", "args": {}}',  # unknown tool -> error envelope
            '{"tool": "look", "args": {"id": "nao/existe"}}',  # E_NOT_FOUND envelope
            '{"tool": "look", "args": {"id": "vendas/relatorio-q1-2026"}}',
            '{"tool": "answer", "args": {"text": "Sudeste lidera as vendas.", '
            '"answer_nodes": ["vendas/relatorio-q1-2026"]}}',
        ]
        r = run_question(forest_ro, scripted_chat_factory(script), Q2, verbose=False)
        assert r["correct_text"] is True
        assert r["answer_nodes"] == ["vendas/relatorio-q1-2026"]
