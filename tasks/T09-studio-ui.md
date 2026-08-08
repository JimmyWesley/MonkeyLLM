# T09 — Studio: the web face of the Station

status: in-progress (2026-08-08 — React/Tailwind/Vite SPA shipped with Ask,
Browse, Search, Datasets, Models, Governance and Audit; ingestion console
and trails dashboard remain)
depends-on: T07 (REST surface), T08 (policies, for the governance console).

## What shipped

`apps/studio/` — React 18 + Tailwind + Vite, built to static files the
Station serves. No server half of its own (J.5), so the deployment stays
one image. Verified in a browser against a live Station with both an admin
key and a `projects/`-scoped key: the scoped principal opens on its own
root, never the master `_index`, and Governance degrades to a plain
explanation instead of an empty admin form.

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

1. [x] **Ask** — question in, grounded answer out, with the evidence nodes
   clickable through to Browse (J.10.3).
2. [x] **Forest browser** — branch tree, node passport, body, edges,
   scope-aware breadcrumbs.
3. [x] **Search console** — locate/sniff/harvest with the same budgets
   the agent sees (great for tuning scent).
4. [x] **Dataset console** — dataset discovery, read-only SQL runner
   (C.9 guards). `tend` forms still to come.
5. [x] **Models** — providers (write-only keys, connection test) and the
   per-forest ingest/answer bindings (J.10).
6. [x] **Governance console** — principals, capabilities, allow/deny
   prefixes, key issuance.
7. [x] **Audit** — the host read log plus the commit each write produced.
8. [ ] **Ingestion console** — adopt/sync runs, converter status, stale
   report, curation review queue (0.3-confidence edge proposals).
9. [ ] **Trails dashboard** — heat over the tree, shortcuts, promote/prune
   history, session replays from telemetry.
10. [ ] **Health** — Ranger reports, snapshot create/restore (Part I).

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
