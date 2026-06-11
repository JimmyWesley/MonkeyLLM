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
- The spec is the truth (`docs/monkeyllm-spec-v0.2.md`): contract changes
  require a new spec version *before* code, and that rule applies to tasks too.

| Task | Title | Status |
| --- | --- | --- |
| T01 | Phase 1 closeout: official Monkey Bench run | in-progress (3/4 criteria pass; token criterion re-measured after T06) |
| T02 | English normalization (PT -> EN) | todo |
| T03 | Phase 1.5: Troop orchestrator | todo |
| T04 | Phase 2: Living Bank (Gardener, Ranger, dataset writes) | todo |
| T05 | Publication readiness (GitHub + paper) | todo |
| T06 | Monkey Bench: multi-hop question hardening | todo |
