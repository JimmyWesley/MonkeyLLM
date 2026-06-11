# T04 — Phase 2: Living Bank (Gardener, Ranger, dataset writes)

status: todo
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

1. **Gardener v1 (ingest):** PDF/DOCX -> markdown (docling/marker); tabular
   (XLSX/CSV/JSON) -> SQLite payload + passport node with query manual;
   SLM-generated summaries validated against spec A.4; entity/edge extraction
   with per-origin confidence; `payload_hash` + passport regeneration on drift.
2. **Ranger v1 (maintenance):** heat evaporation (configurable half-life);
   shortcut/proposal promotion and pruning; `needs_split` detection and
   assisted branch split; continuous lint; `same-as` candidate blocking by
   embedding similarity (physical merge stays human-approved).
3. **Dataset writes ("tend") — REQUIRES SPEC v0.3 FIRST:** today `query` is
   read-only by design (injection suite enforces it). Agent writes to dataset
   payloads need a new primitive contract: allowed statements, audit trail
   (the node's .md records what/when/who; the binary stays out of git),
   journaling/rollback, and how indexes refresh. Write the spec before any code.
4. **Convergence curve:** fixed recurring question set; hops-to-banana must
   drop >= 25% after simulated use (the paper's signature chart). Needs a
   bigger/deeper forest than forest-fixture — shouts never fire at 1-2 hops
   (measured 2026-06-11: 0 shortcut grafts across 28 hunts on the fixture).

## Acceptance criteria

- [ ] 100 mixed documents ingested end-to-end, >= 95% summaries pass A.4,
      zero broken links post-ingest
- [ ] Convergence: hops-to-banana mean drops >= 25% on recurring questions
- [ ] Ranger runs as a service; evaporation/pruning verified with synthetic clock
- [ ] spec v0.3 published covering `tend` (dataset writes) before its code

## Out of scope

Physical `same-as` compaction without human approval; multi-writer.
