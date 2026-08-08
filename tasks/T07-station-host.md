# T07 — Station: self-hostable host (REST + MCP over the forest registry)

status: todo (unblocked — Part J is normative as of spec v0.14)
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

1. **Phase A (read-only, no scoping):** FastAPI app mounting the
   registry; API-key authn; REST endpoints for `locate/look/move/pick/
   scan/sniff/harvest` per forest (`/v1/forests/{id}/...`); `/v1/forests`
   listing; MCP surface reusing `server.py` behind the same keys;
   Dockerfile + compose with `/forests` and `/registry` volumes.
2. **Phase B (governed writes):** principals/roles/policies in the host
   registry; `ScopedVine` (T08) wired under every surface; `plant/graft/
   tend/query` + Gardener `adopt/sync` endpoints; commit messages carry
   the acting principal (`station(<principal>): ...`); read-audit log.
3. OIDC (corporate SSO) as a second authn method; per-token quotas and
   rate limits.

## Acceptance criteria

- [ ] `docker compose up` + one API key = working REST + MCP against an
      example registry (J.7.1).
- [ ] No surface can reach an unscoped `Vine` once Phase B lands.
- [ ] Engine suite passes with zero engine edits (J.7.5).
- [ ] Station has its own test suite (authn, endpoint contracts, MCP
      parity with `vine serve`).

## Out of scope

Studio UI (T09); policy semantics/leak suite (T08); moving
`src/monkeyllm` in the repo; multi-writer forests.
