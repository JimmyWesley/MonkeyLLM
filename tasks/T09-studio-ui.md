# T09 — Studio: the web face of the Station

status: in-progress (2026-08-08 — second pass: nine consoles in three
groups, a real design system with light+dark, en/pt/es, forest creation and
the ingestion console; curation review queue, trails dashboard and health
remain)
depends-on: T07 (REST surface), T08 (policies, for the governance console).

## What shipped

`apps/studio/` — React 18 + Tailwind + Vite, built to static files the
Station serves. No server half of its own (J.5), so the deployment stays
one image.

**Second pass (spec v0.16).** The first pass was seven flat views styled
dark-only in English, and the governance form asked for capability sets and
comma-separated branch prefixes. What changed:

- **Design system** — semantic colour tokens (`surface`, `line`, `text`,
  `accent`…) resolving through CSS variables per theme, so no component
  carries a `dark:` variant and a raw palette class is a test failure
  (`test_no_dark_only_colour_classes_in_components`). Eleven shared
  components; an inline icon set, no new dependency.
- **Information architecture (J.5.1)** — nine consoles in Use / Build /
  Govern, each with an icon. Ask is the landing console; Browse and Search
  merged into **Explore** (they answered one question); **Overview**,
  **Playground** and **Ingest** are new.
- **Vocabulary rule (J.5.2)** — Access grants by *role*, picks scope from
  the *actual branch tree*, and restates the grant in a sentence before
  saving. Capabilities are shown as a consequence, still editable as an
  explicit deviation.
- **i18n + theme (J.5.3)** — English, Portuguese, Spanish, complete and
  test-enforced; light/dark/system, applied before first paint.
- **Forest creation** in the switcher (J.7) and the **ingestion console**
  with drag-and-drop (J.8).

Verified in a browser against a live Station with an admin key and a
`projects/`-scoped key, in both themes, with a real model bound.

### One correction worth recording

Overview first counted the forest with a recursive `scan`, which returned
**17 of 82 nodes** — the primitive answers under an 800-token budget. That
budget is right for an agent and wrong for a console reporting a size, so
the consoles now share one breadth-first walk (`useForestTree`) that keeps
every call inside the budget, and still marks the total `+` if a single
branch overflows. The tree, the scope picker, the ingest destinations and
the counters all come from that one traversal.

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

1. [x] **Overview** — what is in reach, what this key may do, where to
   start. Counted over the principal's own scope, never the forest.
2. [x] **Ask** — question in, grounded answer out, evidence clickable
   through to Explore (J.10.3).
3. [x] **Explore** — branch tree, node passport, body, edges, scope-aware
   breadcrumbs, and locate+sniff search in the same place.
4. [x] **Playground** — the primitives with the budgets an agent sees,
   round-trip timing, the request body, and the cURL/MCP equivalents.
5. [x] **Dataset console** — dataset discovery, query manual, read-only SQL
   runner (C.9 guards). `tend` forms still to come.
6. [x] **Models** — providers (write-only keys, connection test) and the
   per-forest ingest/answer bindings (J.10).
7. [x] **Access** — roles, tree-driven scope picker, plain-language
   restatement, key issuance (J.5.2).
8. [x] **Audit** — the host read log plus the commit each write produced.
9. [x] **Forest creation** — from the switcher (J.7).
9b. [x] **People** — one form onboards somebody (access + password + token),
    and their row owns every later change: replace or clear the password,
    issue or revoke tokens, remove access. A second tab lists tokens across
    people for credential-shaped audit. Login by username and password as
    an alternative to pasting a key (J.2.1/J.2.3/J.5.5).

    *This replaced separate Access and Tokens consoles.* Three governance
    objects had become three screens — the storage model wearing a
    navigation bar. Nobody administers a grant; they onboard a person, and
    that is one thought.

    *Third pass (spec v0.20): forests are a set, not a choice.* The picker
    was a `<select>`, so "this service reads all nine forests" meant nine
    trips through the same form and a person whose real reach was never
    visible in one place. It is now a bounded, scrollable checklist with
    select-all and a filter, the branch picker appears only when a single
    forest is ticked (branch names are forest-local), and unticking a
    forest the person holds revokes it — one request, `grant.forests` plus
    `revoke_access`, refused per forest by id.
10. [~] **Ingestion console** — drag-and-drop upload, folder mirror, sync,
    and the full Part G report (J.8). Converter status and the curation
    review queue (0.3-confidence edge proposals) remain.
11. [x] **Trails dashboard** — closed by T10: heat is drawn over the graph
    mode alongside shortcuts and proposals, and `GET /trails` exposes the
    persistent layer. Session replays from telemetry are not built; they
    need a telemetry endpoint and belong with Health below.
12. [ ] **Health** — Ranger reports, snapshot create/restore (Part I).

## Acceptance criteria

- [x] Every console works against a scoped principal and degrades
      correctly (a `projects/`-scoped reader sees a `projects/`-only
      world, with no trace of the rest), and a console the principal
      cannot use explains what is missing instead of failing on submit.
- [x] Three complete languages and both themes, enforced by
      `tests/test_studio_i18n.py` (missing key, stray key, empty string,
      dropped placeholder, undefined key in a view, raw palette colour).
- [x] Studio uses only documented REST endpoints — `api.js` is the only
      module that calls `fetch`.
- [x] Ships inside the Station image; `docker compose up` serves it.

## Out of scope

Mobile; realtime collaboration; WYSIWYG node editing beyond frontmatter
forms (forests are generated/ingested, not hand-authored in a browser).
