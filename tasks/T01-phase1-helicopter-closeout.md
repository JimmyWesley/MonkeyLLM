# T01 Phase 1 closeout: official Monkey Bench run

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
2. Build the bench forest: `python forests/scripts/build_bench_forest.py`
   (writes `forests/bench-forest/` + regenerates `bench/questions-v2.json`).
3. Build its vector layer: `python -m monkeyllm.cli canopy build --forest forests/bench-forest`.
4. Locate quality + latency: `python scripts/bench_locate.py --forest forests/bench-forest
   --questions bench/questions-v2.json` -> recall@5 and p95 for bm25 and hybrid.
5. Full comparison: `python bench/run_bench.py --forest forests/bench-forest
   --questions bench/questions-v2.json` (arms: monkey, topk, iter).
6. Record results against the four criteria in this file; archive the report
   from `bench/_artifacts/`.

## Acceptance criteria

- [x] recall@5 >= 0.85 (hybrid) on bench questions **1.0** (recall@3 also 1.0, MRR 0.88; bm25-only was 0.611)
- [x] monkey banana precision >= topk arm **1.0 vs 0.68** (correct answers: 18/18 vs 12/18)
- [ ] monkey tokens <= 60% of iter arm on multi-hop questions **re-measured
      on questions-v3 (T06, all min_hops >= 3)**: raw median ratio is ~1.04
      (1433 vs 1384) still fails AS WRITTEN, but the raw comparison is now
      structurally misleading: iter "saves" tokens by *failing* (it answers
      only 7/11; its failures cost as little as 607 tokens because it gives
      up). **Tokens per CORRECT answer: monkey 1382 vs iter 2385 = 0.58 ✓**
      (and monkey is 11/11 vs iter 7/11, p95 8.4s vs 17.5s, total 62.5s vs
      115.9s). DECISION NEEDED (spec/roadmap owner): restate the criterion as
      tokens-per-correct-answer <= 60%, which v3 meets or keep the raw form
      and accept that an arm can pass it by failing cheaply.
- [x] locate p95 < 100ms with vectors active **61.5ms** (p50 48ms; p99 2.1s is first-call embedder warmup)
- [x] lazy re-embed criterion covered by tests/test_canopy_vector.py (graft -> stale -> next hybrid search re-embeds; in-process, well under 60s)
- [x] results table committed below + bench/_artifacts/report-bench-forest.json

## Results (2026-06-11, gemma-4 12B Q4 local, bge-m3 embedder, bench-forest 153 nodes)

| arm | correct | precision | tokens (med) | s/question (med) | s/question (p95) |
| --- | --- | --- | --- | --- | --- |
| monkey | **18/18** | **1.0** | 867 | 3.2 | 5.1 |
| topk | 12/18 | 0.68 | 849 | 2.2 | 2.7 |
| iter | 16/18 | 0.82 | 708 | 2.9 | **15.9** |

locate (18 questions, 40 repeats): bm25 recall@5 0.611 / p95 5.9ms; hybrid recall@5 **1.0** / p95 61.5ms.

## Re-measurement on questions-v3 (2026-06-11, T06 11 questions, 100% min_hops >= 3)

| arm | correct | precision | tokens (med) | s/question (med) | s/question (p95) | total s |
| --- | --- | --- | --- | --- | --- | --- |
| monkey | **11/11** | **1.0** | 1433 | 5.2 | 8.4 | 62.5 |
| topk | **0/11** | 0.64 | 803 | 2.1 | 2.7 | 21.8 |
| iter | 7/11 | 0.86 | 1384 | 9.2 | 17.5 | 115.9 |

Classic top-k RAG **collapses to zero** on chained questions (finds link 1 of
the chain, answers "context does not say"). Tokens per correct answer:
monkey 1382, iter 2385 (ratio **0.58**). Report archived as
bench/_artifacts/report-bench-forest.json (v2 run preserved as
report-bench-forest-v2.json).

Verdict: 3 of 4 exit criteria pass cleanly; the 4th passes under the
tokens-per-correct-answer reading (0.58 <= 0.60) and fails under the raw
median reading (1.04) see the criterion note above for the pending decision.
Accuracy story is decisive: monkey is the only arm that gets everything right,
at bounded latency (no wandering tail).

## Out of scope

Troop (T03), any tuning that changes contracts (spec change required first).
If a criterion fails, investigate summaries first (roadmap principle #2) and
open a follow-up task instead of patching blindly.
