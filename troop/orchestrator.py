"""Troop orchestrator (spec Part E, Phase 1.5): N monkeys, one question.

Coordination is intra-session stigmergy only — the monkeys never exchange
messages, they smell each other's trails:

- Frontier partition (E.1.1): the scout runs `locate(query, k=N)` once and
  each monkey gets a distinct entry point.
- Session pheromone (E.1.2): a harvest (`pick`/`query`) deposits session
  heat on the harvested node's trail. Every read primitive already ranks
  with `score x (1 + beta * session_heat)` for the shared session id, so
  monkeys gravitate toward regions where others found signal. Harvesting IS
  the "this node is promising" judgment: the system prompt only allows
  `pick` once the summary confirms the target.
- Shared visited cache (E.1.3): identical calls are served from a
  troop-wide cache at zero cost — and zero duplicated trace events.
- Stop (E.1.4): the first answer that carries `answer_nodes` sets the stop
  flag; the other monkeys finish their current step and return.
- Judge + post-session (E.1.5): one LLM call synthesizes the final answer
  from the harvests (skipped when a single monkey answered); only the
  winning trail is promoted to persistent heat, the losing session heat
  evaporates with the session.

The troop is an orchestrator component (the MCP client side), not the bank:
nothing here changes Vine contracts. Each monkey gets its own read-only Vine
(SQLite connections are thread-bound); they share the forest, the trails db
and the session id.
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "examples" / "demo"))

from monkeyllm import Vine, VineError  # noqa: E402
from monkeyllm.canopy import embedder_from_env  # noqa: E402
from monkeyllm.tokens import estimate_tokens  # noqa: E402
from run_demo import FORCED_ANSWER_MSG, MAX_STEPS, SYSTEM_PROMPT, parse_action  # noqa: E402

SESSION_HEAT = 0.2  # deposited on a harvest's trail (E.1.2)
SHOUT_THRESHOLD = 4  # spec v0.6 Part D: trail_len >= 4 suggests a shortcut

JUDGE_SYSTEM = (
    "Você é o juiz de uma tropa de macacos que caçou a mesma resposta em "
    "paralelo numa floresta de conhecimento. Sintetize a resposta final com "
    "base SOMENTE nas colheitas apresentadas. Responda apenas com um único "
    'objeto JSON {"tool": "answer", "args": {"text": "...", '
    '"answer_nodes": ["..."]}} — reaproveite os answer_nodes do(s) macaco(s) '
    "que sustentam a resposta."
)


def _monkey_worker(idx: int, n: int, forest: Path, chat, q: dict, entry: dict | None,
                   others: list[str], master_json: str, session: str,
                   cache: dict, cache_lock: threading.Lock, stop: threading.Event,
                   max_steps: int, verbose: bool) -> dict:
    """One monkey's hunt. Creates its own Vine (thread-bound SQLite)."""
    vine = Vine(forest, writable=False, session=session, embedder=embedder_from_env())
    report = {"monkey": idx + 1, "entry": entry["id"] if entry else None,
              "answer": None, "answer_nodes": [], "steps": 0}
    try:
        entry_blurb = json.dumps(entry, ensure_ascii=False) if entry else "nenhum (floresta pequena)"
        intro = (
            f"Galho-mestre da floresta:\n{master_json}\n\n"
            f"Pergunta: {q['question']}\n\n"
            f"Você é o macaco {idx + 1} de uma tropa de {n}. O helicóptero já voou: "
            f"seu ponto de entrada designado é {entry_blurb}. "
            f"Os outros macacos cobrem: {others or 'nada ainda'}. "
            "Comece pelo SEU ponto de entrada (look/pick nele) e siga os links; "
            "não refaça o caminho dos outros."
        )
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": intro}]
        answer, answer_nodes = None, []
        tools = {"locate": vine.locate, "sniff": vine.sniff, "look": vine.look,
                 "move": vine.move, "pick": vine.pick, "query": vine.query,
                 "scan": vine.scan}
        for step in range(max_steps):
            if stop.is_set():
                break
            reply = chat(messages)
            messages.append({"role": "assistant", "content": reply})
            action = parse_action(reply)
            if action is None:
                messages.append({"role": "user", "content":
                                 'Formato inválido. Responda apenas com o JSON {"tool": ..., "args": ...}.'})
                continue
            tool, args = action.get("tool"), action.get("args") or {}
            report["steps"] += 1
            if verbose:
                print(f"    [m{idx + 1}.{step + 1}] {tool}({json.dumps(args, ensure_ascii=False)[:90]})")
            if tool == "answer":
                answer = str(args.get("text", "")).strip() or None
                answer_nodes = list(args.get("answer_nodes") or [])
                break
            key = f"{tool}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
            with cache_lock:
                cached = cache.get(key)
            if cached is not None:
                messages.append({"role": "user", "content": json.dumps(
                    {"cached": True,
                     "hint": "Outro macaco da tropa já fez esta chamada; resultado abaixo. "
                             "Explore fronteira nova ou responda com o que já tem.",
                     "result": cached}, ensure_ascii=False, default=str)})
                continue
            try:
                fn = tools.get(tool)
                if fn is None:
                    result = {"error": {"code": "E_SCHEMA", "message": f"ferramenta desconhecida: {tool}"}}
                else:
                    result = fn(**args)
                    with cache_lock:
                        cache[key] = result
                    if tool in ("pick", "query") and isinstance(args.get("id"), str):
                        nid = args["id"]
                        try:
                            vine.trails.add_heat(vine.forest.trail(nid) + [nid],
                                                 amount=SESSION_HEAT, scope=session)
                        except Exception:
                            pass  # pheromone is best-effort; the hunt goes on
            except VineError as e:
                result = e.to_dict()
            except TypeError as e:
                result = {"error": {"code": "E_SCHEMA", "message": str(e)}}
            messages.append({"role": "user", "content": json.dumps(result, ensure_ascii=False, default=str)})

        if answer is None and not stop.is_set() and report["steps"] > 0:
            # deadline synthesis, same policy as the solo harness
            messages.append({"role": "user", "content": FORCED_ANSWER_MSG})
            action = parse_action(chat(messages))
            if action and action.get("tool") == "answer":
                fargs = action.get("args") or {}
                answer = str(fargs.get("text", "")).strip() or None
                answer_nodes = list(fargs.get("answer_nodes") or [])

        report["answer"], report["answer_nodes"] = answer, answer_nodes
        if answer and answer_nodes:
            stop.set()  # E.1.4(a): confident harvest ends the hunt
        report["tokens"] = sum(e["tokens_out"] for e in vine.tracer.events)
        report["calls"] = len(vine.tracer.events)
        report["metrics"] = vine.tracer.metrics(answer_nodes)
        return report
    finally:
        vine.close()


def _judge(chat, q: dict, answered: list[dict], verbose: bool) -> tuple[str | None, list[str], int]:
    """Aggregate the harvests (E.1.5). Returns (answer, answer_nodes, est_tokens)."""
    if len(answered) == 1:  # nothing to arbitrate
        r = answered[0]
        return r["answer"], r["answer_nodes"], 0
    evid = [{"macaco": r["monkey"], "resposta": r["answer"], "answer_nodes": r["answer_nodes"]}
            for r in answered]
    content = (f"Pergunta: {q['question']}\n\nColheitas da tropa:\n"
               f"{json.dumps(evid, ensure_ascii=False, indent=1)}")
    if verbose:
        print(f"    [juiz] arbitrando {len(answered)} colheitas")
    action = parse_action(chat([{"role": "system", "content": JUDGE_SYSTEM},
                                {"role": "user", "content": content}]))
    if action and action.get("tool") == "answer":
        args = action.get("args") or {}
        return (str(args.get("text", "")).strip() or None,
                list(args.get("answer_nodes") or []), estimate_tokens(content))
    return None, [], estimate_tokens(content)


def hunt_troop(forest: Path, chat, q: dict, n: int = 3, verbose: bool = True,
               max_steps: int = MAX_STEPS) -> dict:
    """Run one troop hunt. Result dict is run_bench/run_demo compatible."""
    forest = Path(forest)
    session = f"troop-{q['id']}-{uuid.uuid4().hex[:6]}"
    scout = Vine(forest, writable=False, session=session, embedder=embedder_from_env())
    cache: dict[str, dict] = {}
    cache_lock = threading.Lock()
    stop = threading.Event()
    try:
        master = scout.look("_index")
        master_json = json.dumps(master, ensure_ascii=False)
        frontier = scout.locate(q["question"], k=n)["results"]
        # seed the shared cache with the scout's calls (E.1.3)
        cache['look:{"id": "_index"}'] = master

        entries: list[dict | None] = []
        for i in range(n):
            entries.append(frontier[i] if i < len(frontier) else None)
        ids = [e["id"] if e else None for e in entries]
        if verbose:
            print(f"    [tropa n={n}] fronteira: {ids}")

        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [
                pool.submit(_monkey_worker, i, n, forest, chat, q, entries[i],
                            [x for j, x in enumerate(ids) if j != i and x], master_json,
                            session, cache, cache_lock, stop, max_steps, verbose)
                for i in range(n)
            ]
            reports = [f.result() for f in futures]

        answered = [r for r in reports if r["answer"] and r["answer_nodes"]]
        answer, answer_nodes, judge_tokens = _judge(chat, q, answered, verbose) \
            if answered else (None, [], 0)

        expected = set(q["expected_nodes"])
        harvested = set(answer_nodes)
        correct_text = answer is not None and all(
            s.lower() in answer.lower() for s in q["answer_contains"])
        success = bool(answer) and bool(harvested & expected)
        precision = (len(harvested & expected) / len(harvested)) if harvested else 0.0

        # Post-session (E.1.5): only the winning trail becomes persistent heat;
        # losing session heat evaporates with the session.
        winner = next((r for r in answered if set(r["answer_nodes"]) & harvested),
                      answered[0] if answered else None)
        if success:
            for nid in answer_nodes:
                try:
                    scout.trails.add_heat(scout.forest.trail(nid) + [nid], amount=0.1)
                except Exception:
                    pass
        scout.trails.clear_session(session)

        winner_metrics = (winner or {}).get("metrics", {})
        total_tokens = (sum(r["tokens"] for r in reports)
                        + sum(e["tokens_out"] for e in scout.tracer.events)
                        + judge_tokens)
        suggest = (answer_nodes if winner_metrics.get("trail_len") is not None
                   and winner_metrics["trail_len"] >= SHOUT_THRESHOLD else [])
        return {
            "id": q["id"],
            "question": q["question"],
            "answer": answer,
            "answer_nodes": answer_nodes,
            "expected_nodes": q["expected_nodes"],
            "correct_text": correct_text,
            "banana_precision": round(precision, 2),
            "metrics": {
                "hops_to_banana": winner_metrics.get("hops_to_banana"),
                "trail_len": winner_metrics.get("trail_len"),
                "tokens_to_banana": total_tokens,
                "calls": sum(r["calls"] for r in reports) + len(scout.tracer.events),
                "answer_nodes": answer_nodes,
                "n": n,
                "monkeys": [{k: r[k] for k in ("monkey", "entry", "steps", "tokens", "calls")}
                            | {"answered": bool(r["answer"])} for r in reports],
            },
            "suggest_shortcuts": suggest,
            "shortcuts": [],
            "trace": str(scout.tracer.trace_path),
        }
    finally:
        scout.close()
