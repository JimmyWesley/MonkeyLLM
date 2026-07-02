# T03 — Phase 1.5: Troop orchestrator

status: in-progress (orchestrator built + measured 2026-06-11; speedup
criterion FAILED on single-chain questions — see Results; fork tier built +
measured 2026-07-02 — criterion NOT met there either, but the accuracy-
amplifier finding is now confirmed on BOTH question classes and the stop-
policy trade-off is mapped; see "Fork-tier results". Design:
docs/design-troop-fork-tier.md)
depends-on: T01

## Goal

Parallel hunting by intra-session stigmergy (spec Part E): N monkeys, one
question, coordination only through session-scoped pheromone — no messages.

## Context

The storage side is ready: `trails.db` already supports session namespaces
(`promote_session`, `clear_session`; only the winning trail becomes persistent
heat). What does not exist is the client-side orchestrator.

## Steps

1. `troop/` module (orchestrator, asyncio): frontier partition via
   `locate(query, k=N)` — each monkey gets a distinct entry point.
2. Session pheromone: monkeys deposit `session_heat` on promising nodes;
   read primitives already apply `score x (1 + beta * session_heat)`.
3. Shared visited cache: a digest already fetched in the session is served
   from cache (zero cost) and the monkey is redirected to unexplored frontier.
4. Judge: aggregates harvests, synthesizes the answer, decides the winner.
5. Inference: llama.cpp parallel slots (`-np N`) on the 3090 so N=3-5 costs
   near N=1 wall-clock.
6. Extend Monkey Bench with N as a parameter; measure troop speedup.
7. **Head-to-head arm (explicit user requirement, 2026-06-11):** add a
   `troop` arm to `bench/run_bench.py` so the same run produces
   monkey (N=1) vs troop (N=3) vs topk vs iter on the SAME questions
   (use `bench/questions-v3.json` — the chained set), same per-question
   timing table and summary row. The troop must reuse `run_question`'s
   semantics (forced synthesis included) so the only variable is N.

## Acceptance criteria

- [ ] N=3 cuts median wall-clock >= 35% vs N=1 on hard bench questions
      (>= 4 hops), with total token cost <= 2.5x — **FAILED on questions-v3**
      (single-chain: nothing to partition) **and on questions-v4**
      (fork tier: sub-chains too shallow for serialization to dominate —
      see "Fork-tier results"). Precondition sharpened: needs sub-chains
      >= 4 hops EACH; blocked on a deeper corpus, not on orchestrator work.
- [x] `run_bench --arms monkey,troop,...` produces the side-by-side report
      (per-question table + summary) in one run (`--troop-n N`,
      `--stop-policy first|quorum|coverage|none`)
- [x] Zero duplicated `look` per session (verified by trace —
      tests/test_troop.py, shared visited cache seeded by the scout)
- [x] Speed x cost trade-off report per question class — measured
      2026-07-02: single-chain (v3, 2026-06-11) + fork tier (v4) with the
      per-class breakdown in run_bench and the stop-policy table in
      "Fork-tier results"

## Results (2026-06-11, gemma-4 12B, `serve_llm --parallel 3`, questions-v3)

| arm | correct | precision | tokens (med) | s/q (med) | s/q (p95) | total s |
| --- | --- | --- | --- | --- | --- | --- |
| monkey (N=1) | 10/11 | 0.91 | 1264 | 4.9 | 7.7 | 58.4 |
| troop (N=3) | **11/11** | **0.96** | 2903 (2.3x) | 16.4 (3.3x) | 27.1 | 198.6 |

Honest verdict — the troop as built is an **accuracy amplifier, not a speed
amplifier, on single-chain questions**:

- v3 questions pin ONE correct chain (e.g. "the project that shipped 4.6").
  Frontier partition hands monkeys 2-3 the *wrong* releases; they walk full
  wrong chains and answer confidently wrong. The **judge** then arbitrates 3
  harvests and picks the right one — that is how the troop got 11/11 while
  the solo monkey flaked once. Exactly spec E.2's warning: "o trade-off
  velocidade × custo deve ser medido, não assumido".
- Wall-clock worsens for two stacked reasons: 3 streams share GPU decode
  throughput (continuous batching helps prefill much more than generation),
  and the troop does ~3x the navigation work because there is nothing to
  fork.
- Early-stop danger found: the FIRST confident answer sets the stop flag,
  and in v3-11 the first answer was a *wrong* monkey — had timing differed,
  the correct monkey would have been cut. Stop discipline (e.g. wait for
  quorum or judge-on-stop) is part of the fork-tier follow-up.

What is validated and stays: frontier partition, shared session pheromone
(monkeys rank with each other's heat), shared visited cache (zero duplicate
calls), judge synthesis, winner-trail promotion + session evaporation, the
`--parallel` serving path, and the bench arm. Follow-up: author a question
tier whose entry is genuinely ambiguous (multiple candidate regions must be
checked — scan/filter questions, "which of the N clients...", negations),
then re-measure the speedup criterion there.

## Fork-tier results (2026-07-02, qwen3.5-flash via OpenRouter, questions-v4)

Built per docs/design-troop-fork-tier.md: `build_questions_v4` (8 questions,
`fork_width` 2-4 — shared-feature forks, unions over recalls/portfolios,
filters, negation, cross-dataset), `stop_policy` in the orchestrator
(`first|quorum|coverage|none`), work-stealing over a k=2n frontier, bench
`--stop-policy` + per-class breakdown. Note the serving change vs the
2026-06-11 run: OpenRouter, so N streams do NOT share one GPU's decode —
the contention confound is gone; what remains is genuine navigation cost.

| arm (v4, n=3) | correct | precision | tokens (med) | s/q (med) | total s |
| --- | --- | --- | --- | --- | --- |
| monkey (N=1) | 7/8 | 0.89 | 1821 | 9.8 | 85.8 |
| troop quorum | 6/8 | 0.83 | 3144 (1.7x) | 8.8 (-10%) | 79.4 |
| troop coverage | **7/8** | **0.92** | 4013 (2.2x) | 11.1 (+13%) | 100.8 |
| troop none | 7/8 | 0.83 | 6242 (3.4x) | 22.4 (+129%) | 185.0 |

**Criterion (>= 35% median wall-clock cut at <= 2.5x tokens): NOT MET on
the fork tier either.** Best case (quorum) cuts only 10% — and pays for it
in coverage.

**Stop-policy trade-off (mapped, each error diagnosed):**
- `quorum` truncates coverage when `fork_width > ceil(n/2)`: v4-05/06
  (width 4) stopped at 2 harvests and answered incomplete — fast but wrong.
- `none` over-explores the stealable surplus (k=2n entries for width-4
  questions): full coverage, 3.4x tokens — over budget.
- `coverage` (stop at `fork_width` harvests — question metadata, so it is
  an oracle-informed upper bound, flagged as such) is the accuracy/cost
  sweet spot: best precision of any arm including solo, tokens within
  budget, wall-clock 13% WORSE than solo.
- Solo's one failure (v4-02, width 3) is the mirror image: it burned its
  step budget before finishing all three chains — exactly the failure mode
  the troop fixes.

### 8/8 hardening pass (2026-07-02, same day, later)

Both arms initially flaked on 1-2 v4 questions per run. Each failure was
diagnosed to a specific defect and fixed WITHOUT touching questions or
scoring:

1. **Recall summaries had no date** (corpus curation bug in the generator:
   contract/release summaries carry their month, recalls didn't) — locate
   could not match "February", costing the solo 4 wasted steps on v4-02.
   Fixed in `populate()`; corpus rebuilt.
2. **No enumeration strategy in the agent prompt** — on "which of the..."
   questions the monkey sampled (sniff guesses) instead of enumerating
   (`move(branch, children)` + look each member). One strategy line added
   to SYSTEM_PROMPT; helps both arms (troop monkeys share the prompt).
3. **Fixed step budget penalized wide questions structurally**: 14 steps
   was calibrated on single-chain sets; a width-4 question does 4x the
   navigation by definition. `step_budget(q) = 14 + 3*(fork_width-1)`
   (run_demo) restores per-chain parity with the troop, whose sub-hunts
   already get a full budget per chain.
4. **`coverage` stop double-counted harvests**: two monkeys answering the
   SAME sub-chain satisfied the width requirement and the hunt stopped
   under-covered (v4-05 failed with the right nodes but a member missing).
   Now only harvests contributing a NEW node count toward coverage; judge
   prompt also hardened for set-merging (name every supported member,
   never assert unproven negatives/completeness).

Post-fix full runs (qwen3.5-flash via OpenRouter):

| arm (v4, n=3) | correct | precision | tokens (med) | s/q (med) | total s |
| --- | --- | --- | --- | --- | --- |
| monkey (N=1) | **8/8** | 0.98 | 1639 | 8.4 | 84.0 |
| troop coverage | **8/8** | 0.82 | 4612 (2.8x) | 13.6 (+62%) | 123.3 |

Speedup verdict UNCHANGED (solo remains faster on this corpus — the
distinct-coverage stop makes the troop more correct AND slower, trading
wall-clock for coverage guarantees). Single runs; expect variance.

### Real-data generalization pass (2026-07-02, same day, later still)

The 8/8 fixes were then generalized off the hand-authored bench:

- **Curator date rule (src/monkeyllm/curator.py)** — the recall-summary bug
  class, fixed at the source for real ingests: dated content MUST carry its
  date (month+year minimum) in the A.4 summary, because locate matches
  summaries only. Measured on the 100-doc dump ingest
  (scripts/measure_curation.py, qwen3.5-flash): acceptance 100%
  (45 retries, 0 fallbacks — the validator pushes back on longer
  summaries until they fit), 0 lint errors, 1.89 s/doc, and **100% of the
  85 dated documents now carry their date in the curated summary**.
- **`stop_policy="patience"` (troop)** — the deployable replacement for
  the oracle-informed `coverage`: keep hunting while harvests contribute
  NEW nodes, stop after 2 consecutive dry harvests. No question metadata.
- **End-to-end real-pipeline check:** 5 hand-derived questions against the
  INGESTED `_measure-forest` (not a generated forest): **5/5**, including
  both original failure modes (date-scoped lookups; April-2026 enumeration).

| arm (v4, n=3) | correct | precision | tokens (med) | s/q (med) |
| --- | --- | --- | --- | --- |
| troop patience (deployable) | **8/8** | 0.93 | 5399 (3.3x) | 20.8 |

Patience pays for its generality in cost (explores until dry) — the
oracle `coverage` row above is the efficiency upper bound, patience is
what ships.

**Finding (paper material, completes the 2026-06-11 one):** the troop is an
accuracy/coverage amplifier on BOTH question classes, and a speed amplifier
on neither — on this corpus. Single-chain: nothing to partition. Fork-tier:
the sub-chains are 2-3 hops each in a 153-node forest, so the solo monkey
serializes them at API speed faster than the troop pays scout + judge +
coordination overhead. The speedup hypothesis now has a sharper
precondition: sub-chains individually deep enough (>= 4 hops each, or
high-latency reads) that serialization dominates coordination — this
corpus has no such tier (same floor-effect family as T04's convergence
finding). Re-measure only after a deeper corpus exists; do NOT keep tuning
the orchestrator against this one.

## Scientific finding (record for the paper) + future promotion

**Finding (2026-06-11):** with N=3 on single-chain questions, the troop is an
*accuracy amplifier* (11/11 + judge arbitration vs 10/11 solo) at 2.3x token
cost and 3.3x wall-clock — NOT a speed amplifier. Parallelism pays only when
the frontier genuinely forks; on pinned chains it buys reliability, not
speed. This is a result, not a failure — it defines WHEN to use the troop.

**Architecture note:** the troop is deliberately an orchestrator-side
component (spec Part E: client of MCP, not the bank). The bank provides the
physics (N-reader concurrency C.9, session-namespaced pheromone, per-session
telemetry); the strategy (N, partition, stop, judge) lives with whoever owns
the LLM calls. In bring-your-own-LLM mode that is necessarily the client;
`troop/` is the reference implementation.

**Future promotion (planned, not started):** in concierge mode (server-side
SLM) the troop can become an official composite MCP tool —
`troop_hunt(question, n)` as a "high-confidence mode" (pay ~2.3x for judge +
N opinions) — the same promotion path harvest took. REQUIRES a new spec
version first (contract change).

## Out of scope

Adaptive troop sizing (Phase 2, only if 1.5 data justifies it).
