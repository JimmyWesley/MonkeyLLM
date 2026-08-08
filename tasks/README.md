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
- The spec is the truth (`docs/monkeyllm-spec-v0.14.md`): contract changes
  require a new spec version *before* code, and that rule applies to tasks too.

| Task | Title | Status |
| --- | --- | --- |
| T01 | Phase 1 closeout: official Monkey Bench run | in-progress (3/4 pass; 4th re-measured on v3 — passes as tokens-per-correct (0.58), criterion wording decision pending) |
| T02 | English normalization (PT -> EN) | done (spec v0.12 + roadmap + local-inference + remaining code strings translated 2026-07-02; protected PT test corpus/prompts intentionally untouched) |
| T03 | Phase 1.5: Troop orchestrator | in-progress (fork-tier built + measured 2026-07-02: 8/8 both arms after curator/prompt/budget hardening; speedup criterion still NOT met — sharpened precondition needs a deeper corpus) |
| T04 | Phase 2: Living Bank (Gardener, Ranger, dataset writes) | in-progress (tend v0.7; dataset birth v0.8; Gardener core v0.9; Ranger v0.10; curation measured 100%; tiered storage v0.11; DOCX built-in + edge proposals v0.12; convergence measured — criterion NOT met, floor-effect + cross-talk findings; ingest-tools.md + extending.md guidance done 2026-07-02; media extras + entity extraction remain, both need a spec bump) |
| T05 | Publication readiness (GitHub + paper) | todo |
| T06 | Monkey Bench: multi-hop question hardening | done (v3 set 100% min_hops>=3; first shouts fired via spec v0.6 trail_len) |
| T07 | Station: self-hostable host (REST + MCP over the registry) | in-progress (Phase A done 2026-08-08: `apps/station/` read-only REST, API keys, ScopedVine seam, Docker; Phase B = writes/audit/MCP) |
| T08 | ScopedVine: branch-level policies (the "RLS" of forests) | todo (unblocked — Part J normative as of spec v0.14) |
| T09 | Studio: the web face of the Station | todo |
