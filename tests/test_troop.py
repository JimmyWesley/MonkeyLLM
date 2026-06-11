"""Troop orchestrator (spec Part E / T03): scripted monkeys, no LLM needed."""

import json
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from conftest import build_forest  # noqa: E402
from troop import hunt_troop  # noqa: E402

Q = {
    "id": "tq1",
    "question": "Quantas unidades de Sensor X foram devolvidas no Q1 2026?",
    "expected_nodes": ["vendas/devolucoes-q1"],
    "answer_contains": ["14"],
}

ANSWER = json.dumps({"tool": "answer", "args": {
    "text": "Foram devolvidas 14 unidades (lote 22-B).",
    "answer_nodes": ["vendas/devolucoes-q1"],
}})


def monkey_idx(messages) -> int:
    m = re.search(r"macaco (\d+) de uma tropa", messages[1]["content"])
    return int(m.group(1))


def steps_taken(messages) -> int:
    return sum(1 for x in messages if x["role"] == "assistant")


class TestTroop:
    def test_answer_cache_and_evaporation(self, tmp_path):
        forest = tmp_path / "tf"
        build_forest(forest)

        def chat(messages):
            if "juiz" in messages[0]["content"]:
                return ANSWER
            idx, step = monkey_idx(messages), steps_taken(messages)
            if step == 0:
                return '{"tool": "look", "args": {"id": "_index"}}'  # all 3: cache hit
            if idx == 1:
                return ANSWER
            time.sleep(0.05)  # monkeys 2-3 wander until the stop flag
            target = "conceitos/rag" if idx == 2 else "vendas/metas-2026"
            return json.dumps({"tool": "look", "args": {"id": target}})

        r = hunt_troop(forest, chat, Q, n=3, verbose=False)

        assert r["correct_text"] is True
        assert r["banana_precision"] == 1.0
        assert r["metrics"]["n"] == 3
        assert len(r["metrics"]["monkeys"]) == 3

        # E.1.3 zero duplicated look: all 3 monkeys asked for "_index", but the
        # scout's seeded result served them — the trace has exactly one event
        lines = [json.loads(l) for l in
                 Path(r["trace"]).read_text(encoding="utf-8").splitlines()]
        index_looks = [e for e in lines
                       if e.get("primitive") == "look" and e.get("id") == "_index"]
        assert len(index_looks) == 1

        # E.1.4 early stop: the wanderers never burned their full step budget
        wanderers = [m for m in r["metrics"]["monkeys"] if m["monkey"] != 1]
        assert all(m["steps"] < 10 for m in wanderers)

        # E.1.5: session heat evaporated; winning trail promoted to persistent
        conn = sqlite3.connect(forest / "_derived" / "trails.db")
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM heat WHERE scope != ''").fetchone()[0] == 0
            heat = conn.execute(
                "SELECT heat FROM heat WHERE scope = '' AND node_id = ?",
                ("vendas/devolucoes-q1",)).fetchone()
            assert heat and heat[0] > 0
        finally:
            conn.close()

    def test_judge_arbitrates_multiple_harvests(self, tmp_path):
        forest = tmp_path / "tf"
        build_forest(forest)
        barrier = threading.Barrier(2, timeout=10)

        def chat(messages):
            if "juiz" in messages[0]["content"]:
                return json.dumps({"tool": "answer", "args": {
                    "text": "Sintetizada pelo juiz: 14 unidades.",
                    "answer_nodes": ["vendas/devolucoes-q1"]}})
            barrier.wait()  # both monkeys answer simultaneously -> 2 harvests
            return ANSWER

        r = hunt_troop(forest, chat, Q, n=2, verbose=False)
        assert r["answer"].startswith("Sintetizada pelo juiz")
        assert r["correct_text"] is True
        assert r["answer_nodes"] == ["vendas/devolucoes-q1"]

    def test_no_answer_is_a_clean_failure(self, tmp_path):
        forest = tmp_path / "tf"
        build_forest(forest)

        def chat(messages):
            if steps_taken(messages) == 0:
                return '{"tool": "look", "args": {"id": "_index"}}'
            return '{"tool": "answer", "args": {"text": "", "answer_nodes": []}}'

        r = hunt_troop(forest, chat, Q, n=2, verbose=False)
        assert r["answer"] is None
        assert r["correct_text"] is False
        assert r["banana_precision"] == 0.0
