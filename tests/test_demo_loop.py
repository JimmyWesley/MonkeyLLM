"""End-to-end agent-loop test with a scripted model (no network, no GPU).

Proves the demo harness machinery: master-index priming, JSON action
parsing, primitive dispatch, error envelope feedback, session close and
metrics — everything except the actual LLM.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "demo"))

from run_demo import parse_action, run_question  # noqa: E402

Q2 = {
    "id": "q02",
    "question": "Which region had the highest total sales in Q1 2026?",
    "expected_nodes": ["sales/report-q1-2026"],
    "answer_contains": ["Southeast"],
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
        text = 'Let me look at the index.\n{"tool": "locate", "args": {"query": "sales"}}\nDone.'
        assert parse_action(text)["tool"] == "locate"

    def test_garbage_returns_none(self):
        assert parse_action("no idea what to do") is None


class TestScriptedHunt:
    def test_multihop_sql_question(self, forest_ro):
        script = [
            '{"tool": "locate", "args": {"query": "sales region Q1 2026", "k": 3}}',
            '{"tool": "look", "args": {"id": "sales/report-q1-2026"}}',
            '{"tool": "query", "args": {"id": "sales/report-q1-2026", '
            '"sql": "SELECT region, SUM(value) AS total FROM sales GROUP BY region ORDER BY total DESC LIMIT 1"}}',
            '{"tool": "answer", "args": {"text": "The region with the highest sales in Q1 2026 was Southeast.", '
            '"answer_nodes": ["sales/report-q1-2026"], '
            '"confidence": 0.9, "proof": "[\\"Southeast\\", 12309378.91]"}}',
        ]
        r = run_question(forest_ro, scripted_chat_factory(script), Q2, verbose=False)
        assert r["correct_text"] is True
        assert r["banana_precision"] == 1.0
        m = r["metrics"]
        assert m["hops_to_banana"] is not None
        assert m["hops_to_banana"] <= 4  # eager digests may pre-open the banana
        assert m["tokens_to_banana"] > 0
        # trace file exists with the outcome line
        lines = Path(r["trace"]).read_text(encoding="utf-8").splitlines()
        events = [json.loads(l) for l in lines]
        assert any("outcome" in e for e in events)

    def test_recovers_from_bad_tool_and_format(self, forest_ro):
        script = [
            "thinking first...",  # invalid -> harness asks for JSON
            '{"tool": "telepathy", "args": {}}',  # unknown tool -> error envelope
            '{"tool": "look", "args": {"id": "does/not-exist"}}',  # E_NOT_FOUND envelope
            '{"tool": "look", "args": {"id": "sales/report-q1-2026"}}',
            # cites a dataset it never queried -> confidence gate rejects with a fix
            '{"tool": "answer", "args": {"text": "Southeast leads in sales.", '
            '"answer_nodes": ["sales/report-q1-2026"]}}',
            '{"tool": "query", "args": {"id": "sales/report-q1-2026", '
            '"sql": "SELECT region, SUM(value) AS total FROM sales GROUP BY region ORDER BY total DESC LIMIT 1"}}',
            '{"tool": "answer", "args": {"text": "Southeast leads in sales.", '
            '"answer_nodes": ["sales/report-q1-2026"], '
            '"confidence": 0.9, "proof": "[\\"Southeast\\", 12309378.91]"}}',
        ]
        r = run_question(forest_ro, scripted_chat_factory(script), Q2, verbose=False)
        assert r["correct_text"] is True
        assert r["answer_nodes"] == ["sales/report-q1-2026"]
        assert r["rejections"] == 1  # the ungrounded first answer was bounced
        assert r["confidence"] == 0.9
