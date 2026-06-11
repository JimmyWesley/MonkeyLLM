# T06 — Monkey Bench: multi-hop question hardening

status: todo
depends-on: T01 (motivating data)

## Goal

Make the bench question set actually multi-hop (>= 3 hops) and deep enough to
exercise the economics the Phase 1 token criterion measures — and to make
shouts (shortcut grafting) fire at all.

## Context

T01 measured: monkey 18/18 precision 1.0, but monkey/iter token ratio ~1.23x —
the <= 60% criterion assumes questions where flat retrieval wanders. In
questions-v2, ~80% resolve in 1-2 hops, so one vector search is enough for the
iter baseline. The roadmap flagged exactly this risk ("bench questions too
trivial / literal summary matches"). Separately, 28 hunts on forest-fixture
produced zero shouts (threshold >= 4 hops never reached) — same root cause.

## Steps

1. Extend `scripts/build_bench_forest.py` with deep chains: facts reachable
   only by composing 3+ nodes (A mentions B, B's body points to C, answer in
   C's dataset row), buried facts in >4k-token bodies, and cross-branch trails.
2. Author a `questions-v3.json` tier: each question annotated with
   `min_hops` ground truth; include buried-fact questions (sniff tier) and
   dataset-join questions (query tier).
3. Re-run T01 step 5 on v3; re-evaluate the token criterion on the
   `min_hops >= 3` subset.
4. Verify shouts fire: with `--learn`, expect > 0 shortcut grafts on v3;
   measure pass-2 hop reduction (feeds the Phase 2 convergence curve).

## Acceptance criteria

- [ ] >= 50% of v3 questions have min_hops >= 3
- [ ] token criterion re-measured and reported on the multi-hop subset
- [ ] at least one shout fires per --learn pass on v3 (the mechanism is
      finally exercised end to end)
- [ ] iter baseline regrades correctly on v3 (no scoring artifacts)

## Out of scope

Changing primitive contracts or budgets to game the metric; touching v1/v2
sets (keep them for longitudinal comparison).
