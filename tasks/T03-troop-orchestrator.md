# T03 — Phase 1.5: Troop orchestrator

status: in-progress (orchestrator built + measured 2026-06-11; speedup
criterion FAILED on single-chain questions — see Results; next lever is a
fork-class question tier)
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
      (see Results): single-chain questions give the troop nothing to
      partition. Needs a fork-class question tier before re-measuring.
- [x] `run_bench --arms monkey,troop,...` produces the side-by-side report
      (per-question table + summary) in one run (`--troop-n N`)
- [x] Zero duplicated `look` per session (verified by trace —
      tests/test_troop.py, shared visited cache seeded by the scout)
- [ ] Speed x cost trade-off report per question class (only the
      single-chain class measured so far)

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

## Out of scope

Adaptive troop sizing (Phase 2, only if 1.5 data justifies it).
