# Session report — 2026-08-08

Lab session on entry-search ranking, triggered by an engineering question
("are we using the SQLite FTS5 techniques from the video, and is there
anything left on the table?"). Answer: we already ship FTS5+BM25 in-process
(`catalog.py`), but `bm25()` was being called *flat* — a title hit ranked no
higher than the same hit in summary prose. This session implements
scent-weighted BM25, measures it at fixture and paper-benchmark scale,
validates end-to-end with `qwen3.5-flash` (OpenRouter), and lands the result
in the paper as §6.4. No commits were made — everything below is in the
working tree, uncommitted, for review.

## TL;DR

- **Full test suite: 276/276 green**, before and after every change.
- **One-line ranking change, measurable win**: per-column BM25 weights
  `title:aliases:tags:summary = 4:3:2:1` in `Catalog.fts_search`
  (`FTS_WEIGHTS`). On the paper's own benchmark (bench-forest, 153 nodes,
  18 v2 queries × 40 repeats): **R@1 0.667 → 0.778, R@5 0.889 → 1.00,
  MRR 0.752 → 0.866, latency unchanged (~1.3 ms p95)**. On the Phase-0
  fixture: R@1 0.9 → 1.0, MRR 0.95 → 1.0.
- **End-to-end validation (qwen3.5-flash via OpenRouter)**: demo agent
  10/10 on the fixture question set (avg 3.0 hops, precision 0.92,
  4.9 s/q) and 4/4 on the buried-answers set (precision 1.00) with the new
  ranking.
- **Two real bugs found in passing, both fixed**:
  1. `examples/demo/questions-buried.json` was an untranslated Portuguese
     remnant whose `expected_nodes` pointed at pre-translation node IDs
     (`projetos/mixerllm/log-experimentos`) that no longer exist — every
     bench run against it measured a structural 0.0. Translated and
     retargeted; each answer re-verified against the actual node bodies.
  2. `forests/scripts/build_bench_forest.py` never wrote
     `_meta/schema.md`, so a freshly rebuilt bench-forest is rejected by
     the current CLI ("not a forest"). Generator fixed (never the forest),
     bench-forest rebuilt: 153 nodes, `vine` accepts it again.
- **Paper updated** (`paper/monkeyllm-paper.md`): mechanism in §3.3, new
  §5.1 table (three configurations), new finding §6.4 ("Curated naming is
  the strongest scent"), §4 models line, test count in Reproducibility.

## What changed (uncommitted, working tree only)

| File | What |
| --- | --- |
| `src/monkeyllm/catalog.py` | `FTS_WEIGHTS = (0, 4.0, 3.0, 2.0, 1.0)` applied in `fts_search` via `bm25(nodes_fts, …)`. Contract intact: still BM25-only over title/aliases/tags/summary (spec §3.3 wording); weights are ranking-internal. Curator inherits automatically (same function). |
| `examples/demo/questions-buried.json` | Translated to English; `expected_nodes` retargeted to existing IDs (`projects/mixerllm/experiment-log`, `sales/returns-q1`); answers verified against bodies (seed 1045 → discarded / 615 ms; first 73% hit-rate → seed 1013; run 27 → 127 delegations; casing supplier). |
| `forests/scripts/build_bench_forest.py` | Now writes `_meta/schema.md` (same dialect as the fixture generator), fixing "not a forest" on rebuild. |
| `paper/monkeyllm-paper.md` | §3.3 scent-weighted BM25 mechanism; §5.1 rewritten table + prose; §6 intro (three → four findings); new §6.4; §4 models note for the 2026-08-08 runs; Reproducibility test count 272 → 276. |

## The measurements

Fixture (82 nodes, 10 demo questions, `scripts/bench_locate.py`):

| Config | R@1 | R@3 | R@5 | MRR | p95 |
| --- | --- | --- | --- | --- | --- |
| flat | 0.9 | 1.0 | 1.0 | 0.95 | 1.3 ms |
| weighted | **1.0** | 1.0 | 1.0 | **1.0** | 1.7 ms |

Bench-forest (paper §5.1 setup: 153 nodes, 18 v2 queries × 40 repeats,
laptop CPU):

| Config | R@1 | R@3 | R@5 | MRR | p95 |
| --- | --- | --- | --- | --- | --- |
| flat | 0.667 | 0.833 | 0.889 | 0.752 | 1.3 ms |
| weighted | **0.778** | **0.944** | **1.00** | **0.866** | 1.3 ms |

Note on the previously published §5.1 flat row (0.556/0.583/0.611): it
predates the English translation of the corpus generators; the table now
carries values that regenerate from the committed scripts at head, as the
Reproducibility section promises. The hybrid row (bge-m3 under RRF) was
measured before the weighting and is kept with an explicit re-run TODO —
RRF consumes ranks, so a better BM25 list can only help it.

## Second lab: one-shot harvest + external LLM vs the navigating agent

Question: of the agent's 4.9 s/question, how much is *finding* the answer
text, and what happens if we hand the harvested region to an external LLM
in a single call? Measured on the fixture (14 questions = 10 demo +
4 buried), `qwen3.5-flash` via OpenRouter:

| Pipeline | Correct | Wall-clock/q | LLM calls/q | Context/q |
| --- | --- | --- | --- | --- |
| Navigating agent | 14/14 | 4.9 s | ~3–5 | ~1.6k tok obs. |
| `harvest` + 1 external call | 12/14 | ~3.0 s | 1 | ~1.3k tok bundle |

- **Finding is machine-time, thinking is LLM-time**: harvest retrieval runs
  at p50 ≈ 50 ms (locate itself ~1 ms); >95% of the agent's 4.9 s is LLM
  inference across hops, not searching.
- **Failure audit (bundle-level, zero-LLM)**: the one-shot misses are
  exactly the questions whose bundle lacked the answer — reading accuracy
  was 12/12 when the answer was present. The two failure classes are
  structural, not tuning artifacts:
  1. *Dataset-only facts* (q02: "Southeast" exists in no `.md`, only inside
     the SQLite dataset) — impossible for any text-retrieval one-shot;
     the agent answers via `query`.
  2. *Short numeric needles* (b02 "73%" → seed 1013; b03 run 27 → "127")
     buried in a 4k-token body: harvest's derived sniff terms require ≥4
     word-chars, so the discriminating literals are dropped and every run
     line matches the remaining terms equally. The agent wins by choosing
     its own literal probe for the next `sniff`.
- **Context sizing**: bundle avg ≈ 1.3k tok (budget cap 4000); largest
  fixture region ≈ 10k tok; full fixture text ≈ 22k tok; full bench-forest
  ≈ 23k tok (chars/4 heuristic). Whole-toy-forest stuffing fits a modern
  window, but does not survive scale (SCENT-only tiering exists precisely
  because corpora don't fit) and never covers datasets.
- **Deployment shape**: route one-shot harvest first; escalate to the
  agent when the bundle comes back dry or the question is aggregate
  (SQL-shaped). Added to the paper's §8 trade-offs paragraph with numbers.

## Addendum — MiniCPM5-1B local A/B (aborted: MacBook too slow)

Does the scent-weighting raise the tiny navigator's correct count?
Setup: MiniCPM5-1B Q8_0 via `llama-server` (Metal), `--ctx 32768`
(the 8192 default overflows the demo conversation: HTTP 400
`exceed_context_size` at ~9.7k tokens), temp 0.1, fixture demo set.
Completed 4 flat + 3 weighted runs (~65 s/question here; one question
pegged ~310 s in every run) before stopping — this eval belongs on the
3090 box.

| Arm | Correct (runs) | Mean | Precision (mean) | Tok-to-banana |
| --- | --- | --- | --- | --- |
| flat | 9, 8, 8, 10 | 8.75 | ~0.29 | ~2,550 |
| weighted | 8, 8, 7 | 7.67 | ~0.35 | ~2,170 |

**No correct-count gain** — the difference is within this model's
documented run-to-run swings. Weighted was consistently better on
harvest precision (+0.06) and ~15% cheaper in observation tokens.
Reading: the fixture set is near-saturated at locate level even flat
(R@1 0.9), and the 1B's failures are protocol collapse (locate-repetition
loops, stall rescues, forced synthesis) — not entry-search misses. Better
scent cannot substitute for navigation discipline below the capability
floor; this is §6.3's substitution thesis seen from the other side. The
weighting's end-to-end payoff should be sought where flat BM25 actually
misses (bench-forest, flat R@1 0.667), with repeats, on hardware fast
enough to afford them.

## Follow-ups

- Hybrid re-run with scent-weighted BM25 under RRF (needs the bge-m3
  embedder on the CUDA box; OpenRouter serves no `/v1/embeddings`).
- Sensitivity sweep over `FTS_WEIGHTS`; per-corpus tuning may recover part
  of the residual R@1 gap (the misses are anti-leakage paraphrases that
  avoid naming-field vocabulary by construction).
- tasks/T02 (full Portuguese sweep) remains open; this session cleared the
  two remnants it actually touched.
