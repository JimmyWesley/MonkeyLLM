# T03 — Phase 1.5: Troop orchestrator

status: todo
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

## Acceptance criteria

- [ ] N=3 cuts median wall-clock >= 35% vs N=1 on hard bench questions
      (>= 4 hops), with total token cost <= 2.5x
- [ ] Zero duplicated `look` per session (verified by trace)
- [ ] Speed x cost trade-off report per question class

## Out of scope

Adaptive troop sizing (Phase 2, only if 1.5 data justifies it).
