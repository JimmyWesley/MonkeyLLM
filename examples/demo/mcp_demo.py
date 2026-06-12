"""MCP-only demo — the hunt runs 100% through the MCP protocol.

Unlike run_demo.py (which imports Vine and calls primitives in-process),
this client never touches the forest directly: every locate/sniff/look/pick
goes through an MCP session, exactly like an external client would. It
validates the product path end to end: client LLM <-> MCP <-> Vine server.

Connection modes:

    --url http://127.0.0.1:8000/mcp     connect to a running `vine serve --transport http`
    --stdio                             spawn `vine serve` as a stdio subprocess

The LLM is resolved exactly like run_demo.py (MONKEYLLM_LLM_ENDPOINT /
OpenRouter / HF) — it plays the role of the client's own model.

    python examples/demo/mcp_demo.py --stdio --only q07
    python examples/demo/mcp_demo.py --url http://127.0.0.1:8000/mcp
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_demo import (  # noqa: E402
    FORCED_ANSWER_MSG,
    MAX_STEPS,
    SYSTEM_PROMPT,
    make_llm,
    parse_action,
    resolve_provider,
)

REPO = Path(__file__).resolve().parents[2]
MCP_TOOLS = {"locate", "sniff", "look", "move", "pick", "query", "scan"}


@contextlib.asynccontextmanager
async def open_mcp_session(url: str | None, forest: str | None):
    """MCP client session over streamable-http (--url) or a spawned stdio server."""
    from mcp import ClientSession

    if url:
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:
        from mcp.client.stdio import StdioServerParameters, stdio_client

        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "monkeyllm.cli", "serve", "--forest", str(forest), "--readonly"],
            env=env,
            cwd=str(REPO),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def call_tool(session, tool: str, args: dict) -> dict:
    """Tool call -> parsed JSON payload; MCP-level failures become the spec
    error envelope so the model sees the same shape either way."""
    r = await session.call_tool(tool, args)
    text = r.content[0].text if r.content else "{}"
    if r.isError:
        return {"error": {"code": "E_SCHEMA", "message": text[:300]}}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": {"code": "E_SCHEMA", "message": f"non-JSON tool result: {text[:200]}"}}


async def run_question(session, chat, q: dict, verbose: bool = True) -> dict:
    master = await call_tool(session, "look", {"id": "_index"})
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Galho-mestre da floresta:\n{json.dumps(master, ensure_ascii=False)}\n\nPergunta: {q['question']}",
        },
    ]
    answer, answer_nodes = None, []
    visited: set[str] = set()
    for step in range(MAX_STEPS):
        reply = await anyio.to_thread.run_sync(chat, messages)
        messages.append({"role": "assistant", "content": reply})
        action = parse_action(reply)
        if action is None:
            messages.append({"role": "user", "content": 'Formato inválido. Responda apenas com o JSON {"tool": ..., "args": ...}.'})
            continue
        tool, args = action.get("tool"), action.get("args") or {}
        if verbose:
            print(f"    [{step+1}] {tool}({json.dumps(args, ensure_ascii=False)[:110]})")
        if tool == "answer":
            answer = str(args.get("text", "")).strip()
            answer_nodes = list(args.get("answer_nodes") or [])
            break
        call_key = f"{tool}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
        if call_key in visited:
            messages.append({"role": "user", "content": json.dumps({
                "repeat": True,
                "hint": "Chamada idêntica à anterior — o resultado seria o mesmo. "
                        "Mude os termos, a ferramenta, ou responda com o que já tem.",
            }, ensure_ascii=False)})
            continue
        visited.add(call_key)
        if tool not in MCP_TOOLS:
            result = {"error": {"code": "E_SCHEMA", "message": f"ferramenta desconhecida: {tool}"}}
        else:
            result = await call_tool(session, tool, args)
        messages.append({"role": "user", "content": json.dumps(result, ensure_ascii=False, default=str)})

    if answer is None:
        messages.append({"role": "user", "content": FORCED_ANSWER_MSG})
        action = parse_action(await anyio.to_thread.run_sync(chat, messages))
        if action and action.get("tool") == "answer":
            fargs = action.get("args") or {}
            answer = str(fargs.get("text", "")).strip() or None
            answer_nodes = list(fargs.get("answer_nodes") or [])
            if verbose and answer:
                print("    [força] síntese após esgotar os passos")

    expected = set(q["expected_nodes"])
    harvested = set(answer_nodes)
    success = bool(answer) and bool(harvested & expected)
    outcome = await call_tool(session, "close_session", {"success": success, "answer_nodes": answer_nodes})
    correct_text = answer is not None and all(s.lower() in answer.lower() for s in q["answer_contains"])
    precision = (len(harvested & expected) / len(harvested)) if harvested else 0.0
    return {
        "id": q["id"],
        "question": q["question"],
        "answer": answer,
        "answer_nodes": answer_nodes,
        "correct_text": correct_text,
        "banana_precision": round(precision, 2),
        "metrics": outcome.get("metrics", {}),
    }


async def amain(args, chat) -> int:
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] == args.only]

    results = []
    async with open_mcp_session(args.url, args.forest) as session:
        tools = await session.list_tools()
        print(f"transporte: {'http ' + args.url if args.url else 'stdio (servidor próprio)'}")
        print(f"tools no servidor: {sorted(t.name for t in tools.tools)}")
        for q in questions:
            print(f"\n== {q['id']}: {q['question']}")
            t0 = time.perf_counter()
            r = await run_question(session, chat, q)
            r["wall_s"] = round(time.perf_counter() - t0, 1)
            results.append(r)
            print(f"    resposta: {str(r['answer'])[:160]}")
            m = r["metrics"]
            print(f"    correto={r['correct_text']}  precision={r['banana_precision']}  "
                  f"tokens={m.get('tokens_to_banana')}  tempo={r['wall_s']}s")

    ok = sum(1 for r in results if r["correct_text"])
    print(f"\n===== MCP DEMO: {ok}/{len(results)} corretas =====")
    return 0 if ok == len(results) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--url", help="MCP endpoint of a running server (http transport)")
    mode.add_argument("--stdio", action="store_true", help="spawn `vine serve` as a stdio subprocess")
    ap.add_argument("--forest", default=str(REPO / "forests" / "forest-fixture"),
                    help="forest for --stdio mode")
    ap.add_argument("--questions", default=str(Path(__file__).parent / "questions.json"))
    ap.add_argument("--only", help="run a single question id (ex: q07)")
    args = ap.parse_args()

    chat, model = make_llm()
    endpoint, _, _ = resolve_provider()
    print(f"modelo (lado cliente): {model}  endpoint: {endpoint or 'huggingface serverless'}")
    return anyio.run(amain, args, chat)


if __name__ == "__main__":
    sys.exit(main())
