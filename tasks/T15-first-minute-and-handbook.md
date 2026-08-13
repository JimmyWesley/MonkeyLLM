status: done (2026-08-13: spec v0.49 + Studio + trilingual handbook
shipped and committed (fe18600); five-lens adversarial review applied —
J.5.12 reworded so the skill teaches the write a paired key actually
carries (`ingest`), J.5.11/F.53 aligned to dismissed-once semantics,
J.5.1's stale Access example corrected, docs de-drifted from the UI.
Remaining: the user's real-browser pass, theirs.)

# T15 The first minute and the handbook: say what this is

## Goal

A person's first ten minutes in the Studio must leave the true belief:
the console is a window; the product is a knowledge forest external AIs
feed and read through MCP a brain they can grow. Three surfaces carry
it: the menu, the first access, and a handbook worth reading.

## Context

The Integrations console was the best page in the product and the worst
door: labelled with a lone abstract noun, admin-gated, at the bottom of
the govern group the one place the product's point was written was the
place a newcomer never looked. Nothing presented the deployment on first
sign-in, and the repo had reference docs (the spec) but no operator
handbook.

## What shipped (spec v0.49)

- **J.5.1 amended** the integration manual's entry MUST read
  **MCP / API / Integrations** (`MCP`/`API` untranslated); the console
  table now names every console the Studio ships.
- **J.5.11 First access** one-time, client-side presentation after the
  first sign-in ("A brain your AIs can grow"): once per browser, flag in
  browser storage only, spends nothing, never precedes identity; Overview
  restates it permanently and small ("Your AI can read this too").
- **J.5.12 The Skills console** self-service, `read`-gated, in the use
  group: generates the Claude Code `SKILL.md` client-side with the
  Station origin and open forest baked in (recall before answering, save
  what is worth keeping, cite node ids); copy or download, no new server
  endpoint, no third write path. Walkthrough names pairing (J.2.6) as the
  credential step. The file's body stays English it addresses a model.
- **`view` in the manual** the MCP tools table in Integrations now
  carries C.6d's `view`.
- **The handbook** `docs/guide/{en,pt,es}/`: README, install,
  first-access, using, feeding, connecting-ai, managing; screenshots
  captured from a live scratch Station into `docs/guide/assets/` (shared,
  English UI). Root README links it.

## Acceptance criteria

- [ ] F.52: a `read` principal gets the Skills console and a skill
      carrying this Station's origin + forest id; no admin gate, no new
      endpoint.
- [ ] F.53: a fresh browser sees the presentation exactly once, dismissal
      writes only browser storage; the menu renders MCP / API /
      Integrations in en/pt/es.
- [ ] `python scripts/i18n.py check` clean; i18n suite green (three
      complete languages, new namespaces `skills`, `welcome`).
- [ ] Handbook complete in the three languages, links and assets resolve.
- [ ] The user's own pass in a real browser.

## Out of scope

- Serving the handbook from the Station (the repo and GitHub render it).
- Per-language screenshots (assets are shared and show the English UI).
- A skills marketplace or more than the one memory skill.
