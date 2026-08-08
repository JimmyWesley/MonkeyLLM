# T07 — Station: self-hostable host (REST + MCP over the forest registry)

status: in-progress (Phase A DONE 2026-08-08 — read-only REST + auth +
ScopedVine seam, live-verified; Phase B = writes, audit, MCP surface)
depends-on: nothing. Part J (spec v0.14) governs J.1 surfaces and J.6
deployment; scoping semantics come from T08.

## Goal

The Supabase shape for forests: an untouched engine wrapped by one
self-hostable service exposing REST + MCP (+ Studio later, T09) over a
multi-forest registry, deployable with `docker compose up`.

## Context

- `vine serve --root` already resolves a registry and speaks MCP over
  HTTP (`src/monkeyllm/server.py`) — the Station wraps that machinery,
  it does not reimplement it.
- Engine stays forest-agnostic; the Station is a new package under
  `apps/station/` (own pyproject; monorepo reorg beyond adding `apps/`
  is out of scope).
- Identity/tokens/policies live in a host registry (SQLite at
  `/registry`), never inside forests.

## Steps

1. **Phase A (read-only REST) — DONE 2026-08-08** (`apps/station/`):
   Starlette app (not FastAPI: `starlette`/`uvicorn` already ship with
   `mcp`, so the host adds zero runtime dependencies and J.6's
   one-image/no-external-database promise survives); API-key authn with
   digest-only storage; host registry (principals/keys/grants) in
   host-side SQLite; `ScopedVine` seam already in place so no surface
   holds an unscoped `Vine`; `/v1/health`, `/v1/forests`, and
   `/v1/forests/{id}/{primitive}` for `locate/look/move/pick/scan/sniff/
   harvest/query`; forest resolution reuses `ForestPool` unchanged;
   Dockerfile + compose with `/forests` and `/registry` volumes.
   MCP-behind-the-same-keys moved to Phase B (it needs the auth story
   settled for streamable-http, and Phase A already proves the seam).
2. **Phase B (governed writes + MCP):** `plant/graft/tend` + Gardener
   `adopt/sync` endpoints; commit messages carry the acting principal
   (`station(<principal>): ...`); read-audit log (J.4); MCP surface
   reusing `server.py` behind the same keys; per-forest worker threads
   (Phase A serialises all forest access on one thread).
3. OIDC (corporate SSO) as a second authn method; per-token quotas and
   rate limits.

## Acceptance criteria

- [ ] `docker compose up` + one API key = working REST + MCP against an
      example registry (J.7.1). *(REST verified live over uvicorn
      2026-08-08: health, 401 without key, granted-forest listing,
      `locate`, dataset `query`, 404 on ungranted. MCP pending Phase B;
      the image itself is written but not yet built in CI.)*
- [x] No surface can reach an unscoped `Vine` — the `ScopedVine` seam
      landed in Phase A rather than being retrofitted in Phase B.
- [x] Engine suite passes with zero engine edits (J.7.5) — `git status
      src/` clean; suite 310 green (294 engine + 16 Station).
- [x] Station test suite (authn, capability gates, endpoint contracts,
      error-envelope mapping, forest-level existence oracle).
      MCP parity moves with the MCP surface (Phase B).

## Out of scope

Studio UI (T09); policy semantics/leak suite (T08); moving
`src/monkeyllm` in the repo; multi-writer forests.
