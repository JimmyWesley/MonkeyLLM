# T08 — ScopedVine: branch-level policies (the "RLS" of forests)

status: todo
depends-on: Part J normative (J.3 enforcement matrix is contract, spec
before code); T07 Phase A (the host that consumes it).

## Goal

One enforcement core: `ScopedVine` wraps the ten primitives + `harvest`
with a deny-by-default policy (allow/deny branch prefixes + capability
set + optional dataset table allow-list), so that every Station surface
shares exactly one scoping implementation and forests gain governed
multi-principal access without any engine change.

## Context

- Policy object and per-primitive enforcement matrix: J.3 of
  `docs/drafts/part-j-station-governance.md`.
- Two normative subtleties drive the design: scope filtering MUST precede
  budgeting (no truncation oracle), and out-of-scope MUST be
  byte-identical to `E_NOT_FOUND` (no existence oracle).
- Lives in `apps/station/` (host concern) — `src/monkeyllm` stays
  policy-free; ScopedVine composes the public `Vine`, never patches it.

## Steps

1. Policy model (pydantic) + registry storage + resolution
   (principal, forest) -> effective policy; deny wins over allow.
2. `ScopedVine` implementing the J.3 matrix; `move` edge filtering and
   `locate/scan/sniff` result filtering first (they are the leak
   surface), then write/query/tend capability gates.
3. **Leak suite** (the deliverable that makes this trustworthy):
   for each primitive × surface, prove a `projects/`-scoped principal
   cannot obtain id/title/summary/body/edge/snippet of any node outside
   `projects/` (J.7.2) — including via `harvest` composites and
   truncation behavior (J.7.3).
4. Property tests: same query, scoped vs unscoped, identical response
   shape and budgets.

## Acceptance criteria

- [ ] J.3 matrix implemented with one rule per primitive, documented
      inline against the spec section.
- [ ] Leak suite green (one test per primitive per surface minimum).
- [ ] No existence/truncation oracle (J.7.2, J.7.3).
- [ ] Zero edits under `src/monkeyllm` (J.7.5).

## Out of scope

Per-node ACLs; row-level dataset filtering beyond table allow-lists;
policy UI (T09).
