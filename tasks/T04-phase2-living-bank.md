# T04 — Phase 2: Living Bank (Gardener, Ranger, dataset writes)

status: in-progress (workstream 3 `tend` DONE 2026-06-11 via spec v0.7;
workstream 5 dataset birth DONE 2026-06-11 via spec v0.8;
workstream 1 Gardener v1 deterministic core DONE 2026-06-11 via spec v0.9;
workstream 2 Ranger v1 DONE 2026-06-11 via spec v0.10 —
LLM curation stage (G.4.2), DOCX converter and convergence curve remain)
depends-on: T01 (measurement discipline), T03 (troop data feeds adaptive ideas)

## Goal

The compounding phase: automatic ingest, agent writes, long-term pheromone
maintenance — the forest stops being a smart reader and becomes memory that
learns. Includes the owner's "living brain" vision: agents that not only
query datasets but **write** to them, safely.

## Already in place (seeds)

- `vine validate` (lint) — Ranger's linter seed.
- Reinforce-before-create in `graft` (shortcut fortification).
- Demo `--learn` consumes `suggest_shortcuts` (the shout) end to end.
- Binary payload policy (spec A.3.1): payloads referenced by `payload_hash`,
  never committed — datasets can grow without bloating the forest repo.
- `trails.db` schema carries timestamps (evaporation-ready).

## Workstreams

1. **Gardener v1 (ingest) — deterministic core DONE (spec v0.9 Part G,
   2026-06-11):** `src/monkeyllm/gardener.py` + `vine adopt`/`vine sync`.
   Adopt mirrors an existing tree (folders -> branches, files -> passports
   with `source_path`+`source_hash`; the forest IS the sync state); sync
   hash-diffs new/changed/deleted (changed = audited `.md`-only commit,
   curated frontmatter preserved; deleted = `stale` report, never auto-
   pruned). Converter contract is the public plugin API v1: config command
   hooks > `monkeyllm.converters` entry points > built-ins (md/txt, csv,
   tabular json, xlsx-if-openpyxl -> dataset born with rows via C.7.1 r7).
   `on_curate` hooks; crashes contained. License rule: built-ins/extras
   MIT-clean only; copyleft tools (e.g. PyMuPDF AGPL in the user's
   pdf-replace) plug via command hook, never as dependency. 11 tests in
   tests/test_gardener.py.
   **Remaining (Gardener v2):** LLM curation stage (G.4.2: A.4 summaries
   with retry guided by config `curation.directives`, tags, entity/edge
   proposals at confidence 0.3) measured against the >= 95% A.4 criterion;
   in-house DOCX->MD built-in converter derived from the pdf-replace
   technique (python-docx MIT: w:t traversal incl. text boxes + fragmented
   run merge); media extras (faster-whisper transcripts, vision
   descriptions); `docs/ingest-tools.md` + `docs/extending.md` guidance.
2. **Ranger v1 (maintenance) — DONE (spec v0.10 Part H, 2026-06-11):**
   `src/monkeyllm/ranger.py` + `vine ranger [--every N]`. Evaporation
   (configurable half-life, dust removal, stale-session cleanup, derived
   layer only — no commits, idempotent under synthetic clock); promotion/
   pruning of links with link-level confidence < 1.0 ONLY (promote to 0.8
   when both endpoints hot, prune when <= 0.5 and both stone cold; audited
   `ranger(promote|prune)` commits; structural/1.0 links untouchable);
   health report (needs_split per A.5, fat nodes per A.2, lint counts,
   stale passports vs gardener source_root, uncertain-link buckets, heat
   stats). 12 tests in tests/test_ranger.py.
   **Deferred to Ranger v2:** assisted branch split (blocked by immutable
   ids — needs the rename/tombstone policy first), `same-as` candidate
   blocking by embedding similarity, filesystem watcher.
3. **Dataset writes ("tend") — DONE (spec v0.7, 2026-06-11):** the 10th
   primitive, C.10. Single-statement INSERT/UPDATE/DELETE; WHERE mandatory on
   UPDATE/DELETE (mass-wipe guard); no DDL/ATTACH/PRAGMA (own injection
   suite); audit = `payload_hash` refresh + `.md`-only git commit (A.3.1
   intact); failed SQL rolls back; `vine validate` warns on payload drift.
   Exposed as MCP tool. 8 tests in tests/test_tend.py.
4. **Convergence curve:** fixed recurring question set; hops-to-banana must
   drop >= 25% after simulated use (the paper's signature chart). Needs a
   bigger/deeper forest than forest-fixture — shouts never fire at 1-2 hops
   (measured 2026-06-11: 0 shortcut grafts across 28 hunts on the fixture).
5. **Dataset birth ("plant with schema") — DONE (spec v0.8, 2026-06-11):**
   C.7.1 — `plant` of a `type: dataset` node accepts a declarative `schema`
   (tables -> columns -> allowlisted types, optional primary_key); the model
   never writes DDL — Vine generates the CREATE TABLEs, births the `.db`,
   computes `payload_hash`, auto-generates `## Query manual` (C.2 works from
   birth), and the commit carries only the `.md` (A.3.1). Rollback removes
   the newborn payload. Closes the loop with `tend`: an agent can now
   collect external data, give it a structured home, and fill it — entirely
   through the primitives (the owner's collector-agent scenario; also the
   "table buried in a giant document -> queryable twin" move). `ALTER` stays
   out of agent reach. 16 tests in tests/test_plant_dataset.py.

## Acceptance criteria

- [ ] 100 mixed documents ingested end-to-end, >= 95% summaries pass A.4,
      zero broken links post-ingest
- [ ] Convergence: hops-to-banana mean drops >= 25% on recurring questions
- [x] Ranger runs as a service (`vine ranger --every N`); evaporation/
      pruning verified with synthetic clock (spec v0.10 F.14, 12 tests)
- [x] spec published covering `tend` (dataset writes) before its code —
      shipped as spec v0.7 + implementation + injection/audit/drift tests
- [x] spec published covering dataset birth (declarative schema in `plant`)
      before its code — shipped as spec v0.8 (C.7.1, F.12) + implementation
      + schema-injection/atomicity/manual tests
- [x] spec published covering the Gardener (Part G) before its code —
      shipped as spec v0.9 (G.1-G.6, C.7.1 rows, F.13) + deterministic
      adopt/sync + converter/hook plugin surface + tests
- [x] spec published covering the Ranger (Part H) before its code —
      shipped as spec v0.10 (H.1-H.5, F.14) + evaporation/tending/health
      + synthetic-clock tests

## Out of scope

Physical `same-as` compaction without human approval; multi-writer.
