"""Monkey Bench (locate slice): how fast and how accurately does the
helicopter drop the agent near the answer?

Measures, over the demo questions (each carries its `expected_nodes`):

  quality   recall@1/3/5  — is an answer node among the top-k landing points?
            MRR           — 1/rank of the first answer node
  speed     p50/p95/p99   — locate latency (spec Part F.6: locate p95 < 100ms)

Runs BM25-only by default (no network needed — this is the Phase 0 number).
If MONKEYLLM_EMBED_ENDPOINT is set AND the canopy is built, it also runs the
hybrid (RRF vector+BM25) configuration and prints both side by side, which
is the Phase 1 comparison.

    python scripts/bench_locate.py
    python scripts/bench_locate.py --repeats 50
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

from monkeyllm import Vine  # noqa: E402
from monkeyllm.canopy import embedder_from_env  # noqa: E402

KS = (1, 3, 5)


def pct(samples, q):
    if not samples:
        return 0.0
    s = sorted(samples)
    idx = min(len(s) - 1, int(round(q / 100 * (len(s) - 1))))
    return s[idx]


def first_hit_rank(result_ids, expected):
    for i, rid in enumerate(result_ids):
        if rid in expected:
            return i + 1
    return None


def run_config(forest: Path, questions, *, embedder, repeats: int, label: str) -> dict:
    vine = Vine(forest, writable=False, embedder=embedder, session=f"bench-{label}")
    try:
        if embedder is not None and not vine.hybrid:
            print(f"  [{label}] embedder set but canopy not built — run `vine canopy build` first. Skipping.")
            return {}
        recall = {k: 0 for k in KS}
        rr = []
        latencies = []
        per_q = []
        for q in questions:
            t0 = time.perf_counter()
            ids = [r["id"] for r in vine.locate(q["question"], k=max(KS))["results"]]
            first_ms = (time.perf_counter() - t0) * 1000
            expected = set(q["expected_nodes"])
            rank = first_hit_rank(ids, expected)
            for k in KS:
                if rank is not None and rank <= k:
                    recall[k] += 1
            rr.append(1.0 / rank if rank else 0.0)
            # timing: repeat the same call warm
            q_lat = [first_ms]
            for _ in range(repeats):
                t0 = time.perf_counter()
                vine.locate(q["question"], k=max(KS))
                q_lat.append((time.perf_counter() - t0) * 1000)
            latencies.extend(q_lat)
            per_q.append({
                "id": q["id"], "first_hit_rank": rank, "top": ids[:max(KS)],
                "latency_ms": {"first": round(first_ms, 2),
                               "p50": round(pct(q_lat, 50), 2),
                               "p95": round(pct(q_lat, 95), 2)},
            })
        n = len(questions)
        return {
            "label": label,
            "questions": n,
            "recall_at": {f"@{k}": round(recall[k] / n, 3) for k in KS},
            "mrr": round(sum(rr) / n, 3),
            "latency_ms": {
                "p50": round(pct(latencies, 50), 2),
                "p95": round(pct(latencies, 95), 2),
                "p99": round(pct(latencies, 99), 2),
                "samples": len(latencies),
            },
            "per_question": per_q,
        }
    finally:
        vine.close()


def print_report(reports):
    print("\n===== MONKEY BENCH — locate =====")
    head = f"{'config':<10} {'recall@1':>9} {'recall@3':>9} {'recall@5':>9} {'MRR':>6} {'p50ms':>7} {'p95ms':>7} {'p99ms':>7}"
    print(head)
    print("-" * len(head))
    for r in reports:
        if not r:
            continue
        ra, lat = r["recall_at"], r["latency_ms"]
        print(f"{r['label']:<10} {ra['@1']:>9} {ra['@3']:>9} {ra['@5']:>9} "
              f"{r['mrr']:>6} {lat['p50']:>7} {lat['p95']:>7} {lat['p99']:>7}")
    budget = 100.0
    for r in reports:
        if r and r["latency_ms"]["p95"] >= budget:
            print(f"\n⚠ {r['label']}: locate p95 {r['latency_ms']['p95']}ms ≥ {budget}ms budget (spec F.6)")

    # per-question breakdown: where the helicopter landed and how long it took
    for r in reports:
        if not r:
            continue
        print(f"\n-- per question [{r['label']}]  (rank of first hit; latency ms)")
        for pq in r["per_question"]:
            lat = pq["latency_ms"]
            rank = pq["first_hit_rank"] if pq["first_hit_rank"] is not None else "—"
            print(f"  {pq['id']}: rank={rank:<3} p50={lat['p50']:>7.2f}  p95={lat['p95']:>7.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forest", default=str(REPO / "forests" / "forest-fixture"))
    ap.add_argument("--questions", default=str(REPO / "examples" / "demo" / "questions.json"))
    ap.add_argument("--repeats", type=int, default=40, help="timing repeats per question")
    args = ap.parse_args()

    forest = Path(args.forest)
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))

    reports = [run_config(forest, questions, embedder=None, repeats=args.repeats, label="bm25")]
    emb = embedder_from_env()
    if emb is not None:
        reports.append(run_config(forest, questions, embedder=emb, repeats=args.repeats, label="hybrid"))
    else:
        print("  (set MONKEYLLM_EMBED_ENDPOINT + build canopy to add the hybrid row)")

    print_report(reports)
    out = forest / "_derived" / "bench-locate.json"
    out.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport saved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
