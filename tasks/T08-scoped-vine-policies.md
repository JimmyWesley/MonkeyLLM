# T08 ScopedVine: branch-level policies (the "RLS" of forests)

status: done (2026-08-08 prefix policies enforced across every primitive
and both surfaces; leak suite green)
depends-on: T07 Phase A (the host that consumes it). The J.3 enforcement
matrix is now contract: implement it, do not redesign it here.

## Goal

One enforcement core: `ScopedVine` wraps the ten primitives + `harvest`
with a deny-by-default policy (allow/deny branch prefixes + capability
set + optional dataset table allow-list), so that every Station surface
shares exactly one scoping implementation and forests gain governed
multi-principal access without any engine change.

## Context

- Policy object and per-primitive enforcement matrix: J.3 of
  `docs/monkeyllm-spec-v0.15.md` (normative).
- Two normative subtleties drive the design: scope filtering MUST precede
  budgeting (no truncation oracle), and out-of-scope MUST be
  byte-identical to `E_NOT_FOUND` (no existence oracle).
- Lives in `apps/station/` (host concern) `src/monkeyllm` stays
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
   `projects/` (F.18) including via `harvest` composites and
   truncation behavior (F.18).
4. Property tests: same query, scoped vs unscoped, identical response
   shape and budgets.

## Acceptance criteria

- [x] J.3 matrix implemented with one rule per primitive, documented
      inline against the spec section.
- [x] Leak suite green (`tests/test_station_scoping.py`, plus the REST and
      MCP surfaces in `test_station_api.py` / `test_station_mcp.py`).
      The load-bearing test walks the WHOLE response of every primitive
      rather than checking known fields that is what caught the leaks
      below.
- [x] No existence/truncation oracle (F.18). Out-of-scope reads reproduce
      the engine's own `E_NOT_FOUND` text, with a tripwire test that fails
      if that wording ever drifts apart.
- [x] Zero edits under `src/monkeyllm` (F.18).

## Leaks the sweep found (kept as a record none were on the checklist)

- `trail` on every locate/sniff hit carries ancestor ids, so a scoped
  principal was handed the master `_index`.
- `coverage` on a branch counts its real children, hidden ones included.
- `stats.degree` counts hidden edges.
- `scanned_nodes` from `sniff` reports how many bodies the engine opened —
  a forest-size oracle. It now reports what the caller can see.

## Out of scope

Per-node ACLs; row-level dataset filtering beyond table allow-lists;
policy UI (T09).
