"""Phase 0 demo (Part F criterion 5): an LLM navigates the forest with the
Vine primitives only, answering multi-hop questions with traces + metrics.

The model and endpoint are configurable; provider resolution order:

  1. MONKEYLLM_LLM_ENDPOINT set        -> that OpenAI-compatible endpoint
                                          (llama.cpp local, vLLM, LM Studio...)
  2. OPENROUTER_API_KEY set            -> OpenRouter (online, no local GPU)
  3. otherwise                         -> Hugging Face serverless (HF_TOKEN)

    MONKEYLLM_LLM_MODEL       model id (defaults per provider)
    MONKEYLLM_LLM_API_KEY     key for custom endpoints (default: no-key)
    MONKEYLLM_LLM_MAX_TOKENS  completion budget (default 600; raise for
                              reasoning models if thinking is enabled)

Examples:
    # Local llama.cpp (scripts/serve_llm.py)
    set MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1
    set MONKEYLLM_LLM_MODEL=gemma-4
    python examples/demo/run_demo.py

    # Online via OpenRouter (no local GPU needed)
    set OPENROUTER_API_KEY=sk-or-...
    set MONKEYLLM_LLM_MODEL=google/gemma-4-12b-it
    python examples/demo/run_demo.py --questions examples/demo/questions.json

Optional Phase 1 vector layer: if MONKEYLLM_EMBED_ENDPOINT is set and the
canopy is built (`vine canopy build`), locate runs hybrid (RRF vector+BM25)
instead of BM25-only — the rest of the demo is identical.

Each question runs in its own Vine session; traces land in
<forest>/_derived/traces/<session>.jsonl and the report prints
hops-to-banana, tokens-to-banana and banana precision.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from monkeyllm import Vine, VineError  # noqa: E402

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_STEPS = 14


def step_budget(q: dict) -> int:
    """Width-aware step budget. MAX_STEPS was calibrated on single-chain
    questions (v1-v3); a fork question does `fork_width` x the navigation
    work BY DEFINITION, so a fixed budget conflates "cannot navigate" with
    "ran out of steps". +3 steps per extra declared sub-chain keeps the
    per-chain budget constant. (The troop needs no scaling: each sub-hunt
    already gets a full MAX_STEPS for its one chain — this restores the
    same per-chain parity for the solo monkey.)"""
    return MAX_STEPS + 3 * (int(q.get("fork_width", 1)) - 1)

SYSTEM_PROMPT = """You are a navigator monkey in a knowledge forest. Answer the question \
using ONLY the tools below. Never invent facts: navigate, harvest and answer.

Tools (always respond with a SINGLE JSON object, nothing else):
- {"tool": "locate", "args": {"query": "...", "k": 5}}  -> entry points (the helicopter)
- {"tool": "sniff", "args": {"terms": ["..."], "scope": null}} -> literal grep on BODIES: exact term
  (code, name, number) -> node + section + snippet. optional scope restricts to a branch or node.
- {"tool": "look", "args": {"id": "..."}}               -> cheap digest of a node (summary, neighbors, outline)
- {"tool": "move", "args": {"id": "...", "rel": null}}  -> neighbors of a node (rel "children" lists branch children)
- {"tool": "pick", "args": {"id": "...", "section": null}} -> full body (only when summary confirms the target)
- {"tool": "query", "args": {"id": "...", "sql": "SELECT ..."}} -> read-only SQL on type:dataset nodes
- {"tool": "scan", "args": {"parent_id": "...", "filter": {}}}  -> filter children by metadata
- {"tool": "answer", "args": {"text": "...", "answer_nodes": ["id1", "id2"]}} -> final answer

Strategy: does the question have an EXACT rare term (code, proper name, number)? sniff first — it
lands directly in the right section and you harvest with pick(id, section). Conceptual question? locate
first; look to sniff around; pick/query only on the target. sniff returned too many? restrict with scope.
Question about ALL members of a set ("which of the...", "who among...", "which ... did NOT...")?
ENUMERATE, never sample: move(branch, rel "children") to list every member, then look each one —
a negative or a complete list is only provable after visiting the whole set. Save tokens.
Important rules:
- If a response has "truncated": true, the list was CUT by budget: do not conclude something does
  not exist — refine with locate (more specific terms) or scan(parent_id, filter).
- Repeating the SAME call with the SAME arguments returns the same result; change tool or terms.
- type:dataset nodes respond via SQL: read the manual in look and use query (aggregates are not in text).
The forest map (master index) is in the first user message."""

# Pre-sniff prompt (spec v0.1), kept VERBATIM for the A/B baseline arm
# (--no-sniff): measures the sniff gain against the 6-tool monkey.
SYSTEM_PROMPT_BASELINE = """You are a navigator monkey in a knowledge forest. Answer the question \
using ONLY the tools below. Never invent facts: navigate, harvest and answer.

Tools (always respond with a SINGLE JSON object, nothing else):
- {"tool": "locate", "args": {"query": "...", "k": 5}}  -> entry points (the helicopter)
- {"tool": "look", "args": {"id": "..."}}               -> cheap digest of a node (summary, neighbors, outline)
- {"tool": "move", "args": {"id": "...", "rel": null}}  -> neighbors of a node (rel "children" lists branch children)
- {"tool": "pick", "args": {"id": "...", "section": null}} -> full body (only when summary confirms the target)
- {"tool": "query", "args": {"id": "...", "sql": "SELECT ..."}} -> read-only SQL on type:dataset nodes
- {"tool": "scan", "args": {"parent_id": "...", "filter": {}}}  -> filter children by metadata
- {"tool": "answer", "args": {"text": "...", "answer_nodes": ["id1", "id2"]}} -> final answer

Strategy: locate first; look to sniff around; pick/query only on the target. Save tokens.
Important rules:
- If a response has "truncated": true, the list was CUT by budget: do not conclude something does
  not exist — refine with locate (more specific terms) or scan(parent_id, filter).
- Repeating the SAME call with the SAME arguments returns the same result; change tool or terms.
- type:dataset nodes respond via SQL: read the manual in look and use query (aggregates are not in text).
The forest map (master index) is in the first user message."""


# Deadline synthesis: a hunt that ends without an answer wastes every token
# it spent. When the step budget runs out, force ONE closing call — the
# evidence (sniff snippets, picked bodies) is already in the context.
FORCED_ANSWER_MSG = (
    "Step budget exhausted. Do NOT call more tools. Based ONLY on what you "
    "have already seen above (sniff snippets, picked bodies), answer now with "
    '{"tool": "answer", "args": {"text": "...", "answer_nodes": ["..."]}}. '
    "If evidence appeared in a snippet, use it literally."
)

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"
# Qwen 3.5 35B-A3B (MoE, ~3B active params: fast and cheap). Append ":free"
# for the gratis tier (rate-limited ~20 req/min; the client retries on 429).
OPENROUTER_DEFAULT_MODEL = "qwen/qwen3.5-35b-a3b"
RETRY_STATUS = {429, 500, 502, 503}  # rate limits / transient upstream errors


def resolve_provider() -> tuple[str | None, str, str]:
    """(endpoint, model, api_key) per the resolution order in the docstring."""
    model = os.environ.get("MONKEYLLM_LLM_MODEL")
    endpoint = os.environ.get("MONKEYLLM_LLM_ENDPOINT")
    api_key = os.environ.get("MONKEYLLM_LLM_API_KEY") or os.environ.get("HF_TOKEN") or "no-key"
    if not endpoint and os.environ.get("OPENROUTER_API_KEY"):
        endpoint = OPENROUTER_ENDPOINT
        api_key = os.environ["OPENROUTER_API_KEY"]
        model = model or OPENROUTER_DEFAULT_MODEL
    return endpoint, model or DEFAULT_MODEL, api_key


def make_llm():
    endpoint, model, api_key = resolve_provider()
    # reasoning models spend tokens thinking before the final content —
    # give them room (or disable thinking server-side) or content comes empty
    max_tokens = int(os.environ.get("MONKEYLLM_LLM_MAX_TOKENS", "600"))

    if endpoint:  # any OpenAI-compatible server: llama.cpp, OpenRouter, vLLM...
        import time as _t

        import httpx

        headers = {"Authorization": f"Bearer {api_key}"}
        if "openrouter" in endpoint:
            headers["HTTP-Referer"] = "https://monkeyllm.com"
            headers["X-Title"] = "MonkeyLLM"
        client = httpx.Client(base_url=endpoint.rstrip("/"), headers=headers, timeout=180.0)

        if model == DEFAULT_MODEL and "openrouter" not in endpoint:
            # Single-model servers (llama.cpp) ignore the request's `model`
            # field, so the placeholder default would be reported as if it ran.
            # Ask the endpoint what it actually serves.
            try:
                served = client.get("/models").json().get("data") or []
                if served:
                    model = served[0]["id"]
            except Exception:
                pass  # endpoint without /models: keep the placeholder name

        # lean by default (same policy as the local server): thinking off
        # unless MONKEYLLM_LLM_REASONING=on. OpenRouter normalizes the
        # `reasoning` param across providers.
        reasoning_on = os.environ.get("MONKEYLLM_LLM_REASONING", "off").lower() == "on"
        if reasoning_on:  # give the thinking tokens room beyond the content budget
            max_tokens += 1000

        def chat(messages: list[dict]) -> str:
            payload = {"model": model, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0.1}
            if "openrouter" in endpoint and not reasoning_on:
                payload["reasoning"] = {"enabled": False}
            for attempt in range(4):
                resp = client.post("/chat/completions", json=payload)
                if resp.status_code in RETRY_STATUS and attempt < 3:
                    _t.sleep(2 ** (attempt + 1))  # 2s, 4s, 8s
                    continue
                if resp.status_code >= 400:
                    # surface the provider's own message (model id errado, etc.)
                    raise RuntimeError(f"LLM endpoint {resp.status_code}: {resp.text[:400]}")
                return resp.json()["choices"][0]["message"].get("content") or ""
            raise RuntimeError("unreachable")

        return chat, model

    # no endpoint: Hugging Face serverless
    from huggingface_hub import InferenceClient

    hf = InferenceClient(token=api_key if api_key != "no-key" else None)

    def chat(messages: list[dict]) -> str:
        resp = hf.chat_completion(messages=messages, model=model, max_tokens=max_tokens, temperature=0.1)
        return resp.choices[0].message.content or ""

    return chat, model


def parse_action(text: str) -> dict | None:
    """Extract the first JSON object from the model output."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    for candidate in (m.group(0), text):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def run_question(forest: Path, chat, q: dict, verbose: bool = True, embedder=None,
                 use_sniff: bool = True, learn: bool = False) -> dict:
    vine = Vine(forest, writable=learn, session=f"demo-{q['id']}", embedder=embedder)
    try:
        master = vine.look("_index")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT if use_sniff else SYSTEM_PROMPT_BASELINE},
            {
                "role": "user",
                "content": f"Forest master index:\n{json.dumps(master, ensure_ascii=False)}\n\nQuestion: {q['question']}",
            },
        ]
        answer, answer_nodes = None, []
        entry_id: str | None = None  # landing zone: first node the monkey touches
        visited: set[str] = set()  # visited-cache (spec E.1.3): identical calls are not re-run
        for step in range(step_budget(q)):
            reply = chat(messages)
            messages.append({"role": "assistant", "content": reply})
            action = parse_action(reply)
            if action is None:
                messages.append({"role": "user", "content": 'Invalid format. Respond only with the JSON {"tool": ..., "args": ...}.'})
                continue
            tool, args = action.get("tool"), action.get("args") or {}
            if verbose:
                print(f"    [{step+1}] {tool}({json.dumps(args, ensure_ascii=False)[:110]})")
            if tool == "answer":
                answer = str(args.get("text", "")).strip()
                answer_nodes = list(args.get("answer_nodes") or [])
                break
            if entry_id is None and tool in ("look", "move", "pick", "query", "scan"):
                entry_id = args.get("id") or args.get("parent_id")
            call_key = f"{tool}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
            if call_key in visited:
                hint = ("Identical call to the previous one — the result would be the same. "
                        "Change the terms, the tool, or answer with what you already have.")
                if use_sniff:
                    hint += (' Hint: sniff({"terms": ["exact term"]}) searches the term '
                             "inside bodies and returns the right section.")
                messages.append({"role": "user", "content": json.dumps(
                    {"repeat": True, "hint": hint}, ensure_ascii=False)})
                continue
            visited.add(call_key)
            try:
                tools = {"locate": vine.locate, "look": vine.look, "move": vine.move,
                         "pick": vine.pick, "query": vine.query, "scan": vine.scan}
                if use_sniff:
                    tools["sniff"] = vine.sniff
                fn = tools.get(tool)
                if fn is None:
                    result = {"error": {"code": "E_SCHEMA", "message": f"unknown tool: {tool}"}}
                else:
                    result = fn(**args)
            except VineError as e:
                result = e.to_dict()
            except TypeError as e:
                result = {"error": {"code": "E_SCHEMA", "message": str(e)}}
            messages.append({"role": "user", "content": json.dumps(result, ensure_ascii=False, default=str)})

        if answer is None:
            messages.append({"role": "user", "content": FORCED_ANSWER_MSG})
            action = parse_action(chat(messages))
            if action and action.get("tool") == "answer":
                fargs = action.get("args") or {}
                answer = str(fargs.get("text", "")).strip() or None
                answer_nodes = list(fargs.get("answer_nodes") or [])
                if verbose and answer:
                    print("    [force] synthesis after exhausting steps")

        expected = set(q["expected_nodes"])
        harvested = set(answer_nodes)
        correct_text = answer is not None and all(
            s.lower() in answer.lower() for s in q["answer_contains"]
        )
        success = bool(answer) and bool(harvested & expected)
        outcome = vine.close_session(success, answer_nodes)

        # The shout (spec C.8 / Part D): close_session only SUGGESTS shortcuts;
        # acting on them is the orchestrator's call. With --learn we graft a
        # discovered-shortcut from the landing zone to each suggested banana —
        # graft's reinforce-before-create turns repeats into fortification.
        shortcuts = []
        if learn and entry_id:
            for nid in outcome.get("suggest_shortcuts", []):
                if nid == entry_id or not vine.forest.exists(nid):
                    continue
                try:
                    g = vine.graft(entry_id, {"add_links": [{"rel": "discovered-shortcut", "target": nid}]})
                    shortcuts.append({"from": entry_id, "to": nid,
                                      "fortified": bool(g["fortified"]), "commit": g["commit"]})
                except VineError as e:
                    shortcuts.append({"from": entry_id, "to": nid, "error": e.to_dict()["error"]["code"]})
        if verbose and shortcuts:
            for s in shortcuts:
                print(f"    SHOUT: shortcut {s['from']} -> {s['to']} "
                      f"({'fortified' if s.get('fortified') else s.get('error', 'planted')})")

        precision = (len(harvested & expected) / len(harvested)) if harvested else 0.0
        return {
            "id": q["id"],
            "question": q["question"],
            "answer": answer,
            "answer_nodes": answer_nodes,
            "expected_nodes": q["expected_nodes"],
            "correct_text": correct_text,
            "banana_precision": round(precision, 2),
            "metrics": outcome["metrics"],
            "shortcuts": shortcuts,
            "trace": str(vine.tracer.trace_path),
        }
    finally:
        vine.close()


def run_troop(forest: Path, chat, q: dict, troop: int, embedder=None,
              use_sniff: bool = True, learn: bool = False) -> dict:
    """Launch `troop` concurrent hunts for a single question; return the best result.

    Selection order: first hunt with correct_text=True (by banana precision desc),
    then highest precision among the rest. All individual runs are stored in
    result["troop_runs"] for analysis.
    """
    import concurrent.futures as _cf

    def hunt(monkey_idx: int) -> dict:
        return run_question(forest, chat, q, verbose=False, embedder=embedder,
                            use_sniff=use_sniff, learn=learn)

    with _cf.ThreadPoolExecutor(max_workers=troop) as pool:
        futures = [pool.submit(hunt, i) for i in range(troop)]
        runs = [f.result() for f in _cf.as_completed(futures)]

    correct = [r for r in runs if r["correct_text"]]
    best = max(correct or runs, key=lambda r: r["banana_precision"])

    # print all runs so the user can see what each monkey did
    for i, r in enumerate(runs):
        m = r["metrics"]
        tag = "WINNER" if r is best else "      "
        print(f"    monkey-{i+1} [{tag}] precision={r['banana_precision']}  "
              f"correct={r['correct_text']}  hops={m['hops_to_banana']}  "
              f"tokens={m['tokens_to_banana']}")
        print(f"             answer: {str(r['answer'])[:120]}")

    best["troop_runs"] = [
        {"monkey": i + 1, "answer": r["answer"],
         "correct_text": r["correct_text"], "banana_precision": r["banana_precision"],
         "metrics": r["metrics"]}
        for i, r in enumerate(runs)
    ]
    best["troop_size"] = troop
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forest", default=str(REPO / "forests" / "forest-fixture"))
    ap.add_argument("--questions", default=str(Path(__file__).parent / "questions.json"))
    ap.add_argument("--only", help="run a single question id (ex: q02)")
    ap.add_argument("--no-sniff", action="store_true",
                    help="baseline arm: hide the sniff tool (pre-v0.2 monkey) for A/B runs")
    ap.add_argument("--learn", action="store_true",
                    help="writable forest: graft suggested shortcuts (the shout) after each hunt")
    ap.add_argument("--troop", type=int, default=1, metavar="N",
                    help="run N monkeys per question in parallel and keep the best answer "
                         "(requires the llama-server to have been started with --parallel N)")
    ap.add_argument("--out", help="report path (default: <forest>/_derived/demo-report.json)")
    args = ap.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] == args.only]
    chat, model = make_llm()
    endpoint, _, _ = resolve_provider()
    print(f"model: {model}  endpoint: {endpoint or 'huggingface serverless'}")

    from monkeyllm.canopy import embedder_from_env

    embedder = embedder_from_env()
    print(f"locate: {'hybrid (vector+BM25)' if embedder else 'BM25-only'}")
    print(f"sniff: {'off (baseline)' if args.no_sniff else 'on'}")
    print(f"learn: {'on (shortcuts grafted via shout)' if args.learn else 'off'}")
    print(f"troop: {args.troop} monkey{'s' if args.troop > 1 else ''} per question")

    import time as _time

    results = []
    for q in questions:
        print(f"\n== {q['id']}: {q['question']}")
        t0 = _time.perf_counter()
        if args.troop > 1:
            r = run_troop(Path(args.forest), chat, q, troop=args.troop,
                          embedder=embedder, use_sniff=not args.no_sniff, learn=args.learn)
        else:
            r = run_question(Path(args.forest), chat, q, embedder=embedder,
                             use_sniff=not args.no_sniff, learn=args.learn)
        r["wall_s"] = round(_time.perf_counter() - t0, 1)
        results.append(r)
        m = r["metrics"]
        if args.troop <= 1:
            print(f"    answer: {str(r['answer'])[:160]}")
        print(
            f"    hops-to-banana={m['hops_to_banana']}  tokens-to-banana={m['tokens_to_banana']}  "
            f"precision={r['banana_precision']}  correct_text={r['correct_text']}  time={r['wall_s']}s"
        )

    ok = sum(1 for r in results if r["correct_text"])
    hops = [r["metrics"]["hops_to_banana"] for r in results if r["metrics"]["hops_to_banana"] is not None]
    toks = [r["metrics"]["tokens_to_banana"] for r in results]
    print("\n===== REPORT =====")
    print(f"correct questions: {ok}/{len(results)}")
    if hops:
        print(f"avg hops-to-banana: {sum(hops)/len(hops):.1f}")
    print(f"avg tokens-to-banana: {sum(toks)/len(toks):.0f}")
    print(f"avg banana precision: {sum(r['banana_precision'] for r in results)/len(results):.2f}")
    walls = [r["wall_s"] for r in results]
    print(f"time per question: avg {sum(walls)/len(walls):.1f}s  max {max(walls):.1f}s  total {sum(walls):.1f}s")
    out = Path(args.out) if args.out else Path(args.forest) / "_derived" / "demo-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report saved to {out}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
