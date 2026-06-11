# T01 — Phase 1 closeout: official Monkey Bench run

status: in-progress

## Goal

Close Phase 1 ("Complete Helicopter") with the official measurement the roadmap
requires. The machinery already exists (canopy, RRF hybrid locate, bench/ with
both mandatory RAG baselines); what is missing is the **measured run + report**
proving the four exit criteria.

## Context

- Roadmap Phase 1 exit criteria (docs/monkeyllm-roadmap.md):
  1. Vector locate: recall@5 >= 0.85 on bench questions.
  2. MonkeyLLM >= top-k RAG on banana precision AND <= 60% of the
     tokens-to-banana of iterative RAG on multi-hop questions.
  3. locate p95 < 100ms with vectors active.
  4. Lazy re-embedding pipeline tested (graft -> stale -> search reflects the
     change in < 60s). Already covered by tests/test_canopy_vector.py.
- Fairness rules: same corpus, same embedder (bge-m3), same LLM for all arms.

## Steps

1. Start both local servers: `python scripts/serve_llm.py` (chat :8090,
   embeddings :8091).
2. Build the bench forest: `python scripts/build_bench_forest.py`
   (writes `bench-forest/` + regenerates `bench/questions-v2.json`).
3. Build its vector layer: `python -m monkeyllm.cli canopy build --forest bench-forest`.
4. Locate quality + latency: `python scripts/bench_locate.py --forest bench-forest
   --questions bench/questions-v2.json` -> recall@5 and p95 for bm25 and hybrid.
5. Full comparison: `python bench/run_bench.py --forest bench-forest
   --questions bench/questions-v2.json` (arms: monkey, topk, iter).
6. Record results against the four criteria in this file; archive the report
   from `bench/_artifacts/`.

## Acceptance criteria

- [x] recall@5 >= 0.85 (hybrid) on bench questions — **1.0** (recall@3 also 1.0, MRR 0.88; bm25-only was 0.611)
- [x] monkey banana precision >= topk arm — **1.0 vs 0.68** (correct answers: 18/18 vs 12/18)
- [ ] monkey tokens <= 60% of iter arm on multi-hop questions — **FAILED as written**: monkey/iter token ratio is ~1.23x overall. Root cause: questions-v2 is mostly 1-2 hops, where one vector search is enough for iter (the roadmap's own "questions too trivial" risk). On the genuinely hard questions the picture flips: q13 ratio 0.71, q06 0.74, q01 0.83, and iter wall-clock explodes when it wanders (q11 34.7s vs monkey 4.2s; iter p95 15.9s vs monkey 5.1s). Follow-up: T06.
- [x] locate p95 < 100ms with vectors active — **61.5ms** (p50 48ms; p99 2.1s is first-call embedder warmup)
- [x] lazy re-embed criterion — covered by tests/test_canopy_vector.py (graft -> stale -> next hybrid search re-embeds; in-process, well under 60s)
- [x] results table committed — below + bench/_artifacts/report-bench-forest.json

## Results (2026-06-11, gemma-4 12B Q4 local, bge-m3 embedder, bench-forest 153 nodes)

| arm | correct | precision | tokens (med) | s/question (med) | s/question (p95) |
| --- | --- | --- | --- | --- | --- |
| monkey | **18/18** | **1.0** | 867 | 3.2 | 5.1 |
| topk | 12/18 | 0.68 | 849 | 2.2 | 2.7 |
| iter | 16/18 | 0.82 | 708 | 2.9 | **15.9** |

locate (18 questions, 40 repeats): bm25 recall@5 0.611 / p95 5.9ms; hybrid recall@5 **1.0** / p95 61.5ms.

Verdict: 3 of 4 exit criteria pass. The token criterion fails because the
question set is too shallow to exercise multi-hop economics — hardening the
set is T06, after which this criterion gets re-measured. Accuracy story is
already decisive: monkey is the only arm that gets everything right, at
bounded latency (no wandering tail).

## Out of scope

Troop (T03), any tuning that changes contracts (spec change required first).
If a criterion fails, investigate summaries first (roadmap principle #2) and
open a follow-up task instead of patching blindly.
