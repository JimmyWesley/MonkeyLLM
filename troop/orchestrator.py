# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

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
- Stop (E.1.4): configurable `stop_policy` — "first" (the first answer that
  carries `answer_nodes` sets the stop flag; T03 documented the risk: the
  first confident answer can be wrong), "quorum" (stop only when
  ceil(n/2) monkeys have answered), or "none" (every monkey runs to its
  own answer/budget; the judge sees everything).
- Work-stealing (fork tier): the scout locates k=2n entry points; a monkey
  that answers its sub-chain pulls the next unclaimed entry and keeps
  hunting until the stop policy fires or the frontier is empty. The shared
  visited cache already dedups the work.
- Judge + post-session (E.1.5): one LLM call synthesizes the final answer
  from the harvests (skipped when a single monkey answered); on fork
  questions the harvests are complementary and the judge merges them.
  Only the winning trail is promoted to persistent heat, the losing
  session heat evaporates with the session.

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
    "You are the judge of a troop of monkeys that hunted the same question "
    "in parallel across a knowledge forest. Synthesize the final answer "
    "based ONLY on the harvests presented. When harvests are complementary "
    "(each covers a different part of the question), MERGE them into one "
    "complete answer; when they conflict, pick the best-supported one. "
    "If the question asks about ALL members of a set (which/who among...), "
    "your text MUST name every member any harvest supports, each with its "
    "attribute — dropping a member the evidence supports is a wrong answer. "
    "Never assert completeness or a negative the harvests do not prove. "
    'Reply with a single JSON object {"tool": "answer", "args": '
    '{"text": "...", "answer_nodes": ["..."]}} — reuse the answer_nodes of '
    "the monkey(s) whose harvests support the final answer."
)


PATIENCE = 2  # "patience": consecutive non-contributing harvests before stop


class _StopControl:
    """E.1.4 stop discipline. Policies:
    - "first"    legacy — the first confident harvest ends the hunt (T03
                 documented the risk: the first answer can be wrong)
    - "quorum"   ceil(n/2) harvests
    - "coverage" as many DISTINCT-contribution harvests as the question's
                 declared fork_width — oracle-informed (bench metadata),
                 an upper bound, not deployable on real questions
    - "patience" the deployable coverage analogue: keep hunting while
                 harvests contribute NEW nodes; stop after PATIENCE
                 consecutive harvests that add nothing (loop-until-dry)
    - "none"     everyone runs to their own budget"""

    def __init__(self, n: int, policy: str, fork_width: int = 1):
        if policy not in ("first", "quorum", "coverage", "patience", "none"):
            raise ValueError(f"unknown stop_policy: {policy!r}")
        self.policy = policy
        if policy == "first":
            self.needed = 1
        elif policy == "coverage":
            self.needed = max(fork_width, 1)
        else:
            self.needed = (n + 1) // 2
        self.event = threading.Event()
        self._count = 0
        self._dry = 0
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def harvested(self, answer_nodes: list[str] | None = None) -> None:
        with self._lock:
            nodes = set(answer_nodes or [])
            fresh = bool(nodes - self._seen)
            self._seen |= nodes
            if self.policy == "patience":
                self._dry = 0 if fresh else self._dry + 1
                if self._count >= 1 and self._dry >= PATIENCE:
                    self.event.set()
                self._count += 1
                return
            if self.policy == "coverage" and nodes and not fresh:
                # a harvest only counts toward coverage if it contributes a
                # node not already harvested — two monkeys answering the SAME
                # sub-chain must not satisfy the width requirement
                return
            self._count += 1
            if self.policy != "none" and self._count >= self.needed:
                self.event.set()

    def is_set(self) -> bool:
        return self.event.is_set()


def _sub_hunt(vine, chat, q: dict, idx: int, n: int, entry: dict | None,
              others: list[str], master_json: str, session: str,
              cache: dict, cache_lock: threading.Lock, stop: _StopControl,
              max_steps: int, verbose: bool, report: dict) -> tuple[str | None, list[str]]:
    """One monkey walking ONE entry point to an answer (or budget/stop)."""
    entry_blurb = json.dumps(entry, ensure_ascii=False) if entry else "none (small forest)"
    intro = (
        f"Master branch of the forest:\n{master_json}\n\n"
        f"Question: {q['question']}\n\n"
        f"You are monkey {idx + 1} of a troop of {n}. The helicopter has flown: "
        f"your assigned entry point is {entry_blurb}. "
        f"The other monkeys cover: {others or 'nothing yet'}. "
        "The question may need MORE than one region — answer for YOUR entry's "
        "part with what you can prove. Start from YOUR entry point (look/pick "
        "it) and follow the links; do not retrace the others' paths."
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
                             'Invalid format. Reply only with the JSON {"tool": ..., "args": ...}.'})
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
                 "hint": "Another troop monkey already made this call; result below. "
                         "Explore new frontier or answer with what you have.",
                 "result": cached}, ensure_ascii=False, default=str)})
            continue
        try:
            fn = tools.get(tool)
            if fn is None:
                result = {"error": {"code": "E_SCHEMA", "message": f"unknown tool: {tool}"}}
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
    return answer, answer_nodes


def _monkey_worker(idx: int, n: int, forest: Path, chat, q: dict, entry: dict | None,
                   others: list[str], master_json: str, session: str,
                   cache: dict, cache_lock: threading.Lock, stop: _StopControl,
                   max_steps: int, verbose: bool,
                   frontier_queue: list, frontier_lock: threading.Lock) -> dict:
    """One monkey's hunt. Creates its own Vine (thread-bound SQLite).

    Work-stealing (fork tier): after harvesting its entry's answer, if the
    stop policy hasn't fired and unclaimed frontier remains, the monkey
    pulls the next entry and hunts again; all harvests go to the judge."""
    vine = Vine(forest, writable=False, session=session, embedder=embedder_from_env())
    report = {"monkey": idx + 1, "entry": entry["id"] if entry else None,
              "answer": None, "answer_nodes": [], "steps": 0, "harvests": []}
    try:
        current = entry
        while True:
            answer, answer_nodes = _sub_hunt(
                vine, chat, q, idx, n, current, others, master_json, session,
                cache, cache_lock, stop, max_steps, verbose, report)
            if answer and answer_nodes:
                report["harvests"].append({"answer": answer, "answer_nodes": answer_nodes})
                stop.harvested(answer_nodes)
            if stop.is_set():
                break
            with frontier_lock:
                current = frontier_queue.pop(0) if frontier_queue else None
            if current is None:
                break
            if verbose:
                print(f"    [m{idx + 1}] stealing frontier: {current['id']}")

        # primary harvest kept on the legacy fields (bench/report compat)
        if report["harvests"]:
            report["answer"] = report["harvests"][0]["answer"]
            report["answer_nodes"] = report["harvests"][0]["answer_nodes"]
        report["tokens"] = sum(e["tokens_out"] for e in vine.tracer.events)
        report["calls"] = len(vine.tracer.events)
        all_nodes = [nid for h in report["harvests"] for nid in h["answer_nodes"]]
        report["metrics"] = vine.tracer.metrics(all_nodes)
        return report
    finally:
        vine.close()


def _judge(chat, q: dict, answered: list[dict], verbose: bool) -> tuple[str | None, list[str], int]:
    """Aggregate the harvests (E.1.5). Returns (answer, answer_nodes, est_tokens)."""
    if len(answered) == 1:  # nothing to arbitrate or merge
        r = answered[0]
        return r["answer"], r["answer_nodes"], 0
    evid = [{"monkey": r["monkey"], "answer": r["answer"], "answer_nodes": r["answer_nodes"]}
            for r in answered]
    content = (f"Question: {q['question']}\n\nTroop harvests:\n"
               f"{json.dumps(evid, ensure_ascii=False, indent=1)}")
    if verbose:
        print(f"    [judge] arbitrating {len(answered)} harvests")
    action = parse_action(chat([{"role": "system", "content": JUDGE_SYSTEM},
                                {"role": "user", "content": content}]))
    if action and action.get("tool") == "answer":
        args = action.get("args") or {}
        return (str(args.get("text", "")).strip() or None,
                list(args.get("answer_nodes") or []), estimate_tokens(content))
    return None, [], estimate_tokens(content)


def hunt_troop(forest: Path, chat, q: dict, n: int = 3, verbose: bool = True,
               max_steps: int = MAX_STEPS, stop_policy: str = "first") -> dict:
    """Run one troop hunt. Result dict is run_bench/run_demo compatible."""
    forest = Path(forest)
    session = f"troop-{q['id']}-{uuid.uuid4().hex[:6]}"
    scout = Vine(forest, writable=False, session=session, embedder=embedder_from_env())
    cache: dict[str, dict] = {}
    cache_lock = threading.Lock()
    stop = _StopControl(n, stop_policy, fork_width=q.get("fork_width", 1))
    try:
        master = scout.look("_index")
        master_json = json.dumps(master, ensure_ascii=False)
        # k=2n: the surplus is the work-stealing queue for fork questions
        # whose width exceeds the troop size
        frontier = scout.locate(q["question"], k=2 * n)["results"]
        # seed the shared cache with the scout's calls (E.1.3)
        cache['look:{"id": "_index"}'] = master

        entries: list[dict | None] = []
        for i in range(n):
            entries.append(frontier[i] if i < len(frontier) else None)
        frontier_queue = list(frontier[n:])
        frontier_lock = threading.Lock()
        ids = [e["id"] if e else None for e in entries]
        if verbose:
            print(f"    [troop n={n} stop={stop_policy}] frontier: {ids}"
                  + (f" (+{len(frontier_queue)} stealable)" if frontier_queue else ""))

        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [
                pool.submit(_monkey_worker, i, n, forest, chat, q, entries[i],
                            [x for j, x in enumerate(ids) if j != i and x], master_json,
                            session, cache, cache_lock, stop, max_steps, verbose,
                            frontier_queue, frontier_lock)
                for i in range(n)
            ]
            reports = [f.result() for f in futures]

        # one judge entry per HARVEST (a stealing monkey may carry several)
        answered = [{"monkey": r["monkey"], "answer": h["answer"],
                     "answer_nodes": h["answer_nodes"]}
                    for r in reports for h in r["harvests"]]
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
        winner_harvest = next((h for h in answered if set(h["answer_nodes"]) & harvested),
                              answered[0] if answered else None)
        winner = next((r for r in reports
                       if winner_harvest and r["monkey"] == winner_harvest["monkey"]), None)
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
                "stop_policy": stop_policy,
                "monkeys": [{k: r[k] for k in ("monkey", "entry", "steps", "tokens", "calls")}
                            | {"harvests": len(r["harvests"])} for r in reports],
            },
            "suggest_shortcuts": suggest,
            "shortcuts": [],
            "trace": str(scout.tracer.trace_path),
        }
    finally:
        scout.close()
