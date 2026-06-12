"""Monkey Bench v1 — MonkeyLLM × the two mandatory RAG baselines.

Same corpus, same embedder, same LLM, same questions (roadmap fairness rules).
Arms:

  monkey  — the Vine agent (demo loop): locate/look/move/pick/query/scan
  troop   — N monkeys in parallel, intra-session stigmergy (spec Part E);
            serve the chat model with parallel slots: serve_llm.py --parallel N
  topk    — classic top-k RAG (one completion over the top-k chunks)
  iter    — iterative RAG (vector search as the only tool, no indexes/graph)

Requires the local servers up (scripts/serve_llm.py) and the env:

    export MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1 MONKEYLLM_LLM_MODEL=qwen2.5-7b
    export MONKEYLLM_EMBED_ENDPOINT=http://localhost:8091/v1 MONKEYLLM_EMBED_MODEL=bge-m3

    python bench/run_bench.py --questions bench/questions-v1.json
    python bench/run_bench.py --arms topk,iter        # subset
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "examples" / "demo"))
sys.path.insert(0, str(REPO))

from bench.baselines import rag_iter, rag_topk  # noqa: E402
from bench.chunks import ChunkStore  # noqa: E402
from monkeyllm.canopy import embedder_from_env  # noqa: E402
from run_demo import make_llm, run_question  # noqa: E402


def get_store(forest: Path, embedder) -> ChunkStore:
    out_dir = REPO / "bench" / "_artifacts" / forest.name
    store = ChunkStore.load(out_dir, embedder)
    if store is None:
        print(f"construindo chunk store em {out_dir} ...")
        store = ChunkStore.build(forest, embedder, out_dir)
        print(f"  {len(store)} chunks embedados com {embedder.model}")
    return store


def run_arm(arm: str, questions: list[dict], *, forest: Path, chat, store, embedder,
            troop_n: int = 3) -> list[dict]:
    results = []
    for q in questions:
        print(f"\n== [{arm}] {q['id']}: {q['question'][:90]}")
        t0 = time.perf_counter()
        if arm == "monkey":
            r = run_question(forest, chat, q, embedder=embedder)
        elif arm == "troop":
            from troop import hunt_troop

            r = hunt_troop(forest, chat, q, n=troop_n)
        elif arm == "topk":
            r = rag_topk(chat, store, q)
        elif arm == "iter":
            r = rag_iter(chat, store, q)
        else:
            raise SystemExit(f"braço desconhecido: {arm}")
        r["wall_s"] = round(time.perf_counter() - t0, 1)
        results.append(r)
        print(f"    resposta: {str(r['answer'])[:140]}")
        print(f"    correto={r['correct_text']}  precision={r['banana_precision']}  "
              f"tokens={r['metrics']['tokens_to_banana']}  {r['wall_s']}s")
    return results


def summarize(arm: str, results: list[dict]) -> dict:
    toks = [r["metrics"]["tokens_to_banana"] for r in results]
    walls = sorted(r["wall_s"] for r in results)
    p95 = walls[min(len(walls) - 1, int(round(0.95 * (len(walls) - 1))))]
    return {
        "arm": arm,
        "correct": sum(1 for r in results if r["correct_text"]),
        "n": len(results),
        "precision_mean": round(sum(r["banana_precision"] for r in results) / len(results), 2),
        "tokens_median": int(statistics.median(toks)),
        "tokens_mean": int(sum(toks) / len(toks)),
        "wall_s_median": round(statistics.median(walls), 1),
        "wall_s_p95": round(p95, 1),
        "wall_s_total": round(sum(walls), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forest", default=str(REPO / "forests" / "forest-fixture"))
    ap.add_argument("--questions", default=str(REPO / "bench" / "questions-v1.json"))
    ap.add_argument("--arms", default="monkey,topk,iter")
    ap.add_argument("--troop-n", type=int, default=3, help="monkeys in the troop arm")
    ap.add_argument("--only", help="run a single question id")
    args = ap.parse_args()

    forest = Path(args.forest).resolve()
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] == args.only]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]

    embedder = embedder_from_env()
    if embedder is None and ({"topk", "iter"} & set(arms)):
        raise SystemExit("os baselines precisam de MONKEYLLM_EMBED_ENDPOINT (mesmo embedder do MonkeyLLM).")
    chat, model = make_llm()
    print(f"modelo: {model}  |  braços: {arms}  |  {len(questions)} perguntas")

    store = get_store(forest, embedder) if {"topk", "iter"} & set(arms) else None

    # partial runs (--only / subset of arms) get their own file so they never
    # clobber the canonical full report
    partial = bool(args.only) or set(arms) != {"monkey", "topk", "iter"}
    suffix = "-partial" if partial else ""
    out = REPO / "bench" / "_artifacts" / f"report-{forest.name}{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    all_results: dict[str, list[dict]] = {}
    for arm in arms:
        all_results[arm] = run_arm(arm, questions, forest=forest, chat=chat,
                                   store=store, embedder=embedder, troop_n=args.troop_n)
        # incremental save: a crash in a later arm never loses finished arms
        out.write_text(json.dumps({"results": all_results}, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    print("\n===== MONKEY BENCH v1 =====")
    head = (f"{'braço':<8} {'corretas':>9} {'precision':>10} {'tokens (med)':>13} "
            f"{'s/perg (med)':>13} {'s/perg (p95)':>13} {'total s':>9}")
    print(head)
    print("-" * len(head))
    summaries = []
    for arm in arms:
        s = summarize(arm, all_results[arm])
        summaries.append(s)
        print(f"{arm:<8} {s['correct']}/{s['n']:<7} {s['precision_mean']:>10} "
              f"{s['tokens_median']:>13} {s['wall_s_median']:>13} {s['wall_s_p95']:>13} "
              f"{s['wall_s_total']:>9}")

    # per-question timing: how long each answer took, end to end, per arm
    print("\n-- tempo por pergunta (s, ponta a ponta)")
    qids = [r["id"] for r in all_results[arms[0]]]
    print(f"{'perg':<6}" + "".join(f"{a:>9}" for a in arms))
    for i, qid in enumerate(qids):
        row = f"{qid:<6}"
        for a in arms:
            row += f"{all_results[a][i]['wall_s']:>9}"
        print(row)

    out.write_text(json.dumps({"summaries": summaries, "results": all_results},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nrelatório salvo em {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
