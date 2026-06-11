"""MCP-only demo: a full hunt where the forest is touched ONLY through MCP.

Spawns `vine serve` as a real stdio subprocess and drives it with a scripted
chat — end-to-end protocol validation without an LLM or network.
"""

import sys
from pathlib import Path

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))

from mcp_demo import open_mcp_session, run_question  # noqa: E402

Q07 = {
    "id": "q07",
    "question": "Quanta VRAM tem a GPU da workstation de P&D?",
    "expected_nodes": ["infra/workstation-3090"],
    "answer_contains": ["24"],
}

SCRIPT = [
    '{"tool": "locate", "args": {"query": "workstation 3090", "k": 5}}',
    '{"tool": "pick", "args": {"id": "infra/workstation-3090"}}',
    '{"tool": "answer", "args": {"text": "A RTX 3090 da workstation tem 24 GB de VRAM.", '
    '"answer_nodes": ["infra/workstation-3090"]}}',
]


def scripted(replies):
    it = iter(replies)
    return lambda messages: next(it)


class TestMcpOnlyDemo:
    def test_full_hunt_over_stdio(self, forest_ro):
        async def go():
            async with open_mcp_session(None, str(forest_ro)) as session:
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert {"locate", "sniff", "harvest", "pick", "close_session"} <= names
                return await run_question(session, scripted(SCRIPT), Q07, verbose=False)

        r = anyio.run(go)
        assert r["correct_text"] is True
        assert r["banana_precision"] == 1.0
        assert r["metrics"].get("tokens_to_banana", 0) > 0
        assert r["answer_nodes"] == ["infra/workstation-3090"]
