# T09 — Studio: the web face of the Station

status: todo
depends-on: T07 (REST surface), T08 (policies, for the governance console).

## Goal

The Supabase-Studio equivalent for forests: a web UI served by the
Station that lets humans browse, search, query, ingest, and govern —
without ever touching the filesystem.

## Context

- Studio is a pure REST client of the Station (J.5) — no privileged
  side-channel; whatever Studio can do, the API can do.
- Lives in `apps/studio/` (SPA; static build served by the Station
  container). Stack: keep it boring and self-contained — no external
  services at runtime.

## Consoles (J.5), in delivery order

1. **Forest browser** — tree by branch, node passport (frontmatter),
   body render, links/edges, git history of the node.
2. **Search console** — locate/sniff playground with the same budgets
   the agent sees (great for tuning scent).
3. **Dataset console** — `## Query manual` surfaced, read-only SQL
   runner (C.9 guards), `tend` as forms (C.10 guards).
4. **Ingestion console** — adopt/sync runs, converter status, stale
   report, curation review queue (0.3-confidence edge proposals:
   approve -> promote path, reject -> prune).
5. **Trails dashboard** — heat over the tree, shortcuts, promote/prune
   history, session replays from telemetry.
6. **Governance console** — members, roles, policies, tokens, audit log
   (writes from git, reads from the host registry).
7. **Health** — Ranger reports, snapshot create/restore (Part I).

## Acceptance criteria

- [ ] Every console works against a scoped principal and degrades
      correctly (a `projects/`-scoped reader sees a `projects/`-only
      world, with no trace of the rest).
- [ ] Studio uses only documented REST endpoints (verified by an
      API-coverage test in CI).
- [ ] Ships inside the Station image; `docker compose up` serves it.

## Out of scope

Mobile; realtime collaboration; WYSIWYG node editing beyond frontmatter
forms (forests are generated/ingested, not hand-authored in a browser).
