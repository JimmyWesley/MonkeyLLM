# Tasks

Backlog of pending work, one file per task: `T<NN>-<slug>.md`.

Conventions:

- Every task states **Goal**, **Context**, **Steps**, **Acceptance criteria** and
  **Out of scope**. A task is done when every acceptance criterion is checked.
- Status lives in the `status:` line at the top of each file
  (`todo | in-progress | done`). Keep it current.
- Language policy: **everything in English** — task files, code comments,
  docstrings, docs, CLI output. See `T02-english-normalization.md` for the
  one-time cleanup; new work must already comply.
- The spec is the truth (`docs/monkeyllm-spec-v0.7.md`): contract changes
  require a new spec version *before* code, and that rule applies to tasks too.

| Task | Title | Status |
| --- | --- | --- |
| T01 | Phase 1 closeout: official Monkey Bench run | in-progress (3/4 pass; 4th re-measured on v3 — passes as tokens-per-correct (0.58), criterion wording decision pending) |
| T02 | English normalization (PT -> EN) | in-progress (src/ + contract vocabulary done via spec v0.5; docs prose remains) |
| T03 | Phase 1.5: Troop orchestrator | in-progress (built + measured; accuracy 11/11 but speedup criterion failed on single-chain qs — fork-tier next) |
| T04 | Phase 2: Living Bank (Gardener, Ranger, dataset writes) | in-progress (tend primitive done via spec v0.7; Gardener/Ranger remain) |
| T05 | Publication readiness (GitHub + paper) | todo |
| T06 | Monkey Bench: multi-hop question hardening | done (v3 set 100% min_hops>=3; first shouts fired via spec v0.6 trail_len) |
