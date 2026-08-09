# T04 — Phase 2: Living Bank (Gardener, Ranger, dataset writes)

status: in-progress (workstream 3 `tend` DONE 2026-06-11 via spec v0.7;
workstream 5 dataset birth DONE 2026-06-11 via spec v0.8;
workstream 1 Gardener v1 deterministic core DONE 2026-06-11 via spec v0.9;
workstream 2 Ranger v1 DONE 2026-06-11 via spec v0.10;
LLM curation (G.4.2) DONE + measured 2026-06-11;
workstream 6 tiered storage DONE 2026-06-11 via spec v0.11 (G.7/G.8 +
G.9 fetchers/prefetch + H.6 eviction + Part I snapshots);
DOCX built-in + edge proposals DONE 2026-06-11 via spec v0.12;
convergence curve measured (criterion NOT met — see workstream 4) —
media extras and guidance docs remain)
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
   **LLM curation (G.4.2) — DONE + MEASURED (2026-06-11):**
   `src/monkeyllm/curator.py` — the Curator is itself an `on_curate` hook:
   A.4 summary via LLM with validate-and-retry (max 3 attempts, error fed
   back), tags (cleaned slugs, merged after config default_tags), operator
   `curation.directives` injected into the system prompt, language follows
   the content. Any failure falls back to the derived summary — never
   blocks. CLI: `vine adopt|sync --curate` (MONKEYLLM_LLM_ENDPOINT).
   **Measured (gemma-4 12B local, 100-doc EN dump via
   forests/scripts/build_dump.py + scripts/measure_curation.py): 100 planted,
   85 LLM summaries (15 datasets keep factual templates), acceptance
   100% (2 retries, 0 fallbacks), 0 lint errors, 1.71 s/doc (171 s
   total).** Criterion >= 95%: PASSED.
   Bonus regression fix found by the measurement: `GitRepo.is_repo` used
   `--is-inside-work-tree`, so a forest created INSIDE any outer repo
   skipped `git init` and forest commits would land in the outer repo —
   now requires the forest root to be its own toplevel (test added).
   **Gardener v2 — DOCX built-in + edge proposals DONE (spec v0.12,
   2026-06-11):**
   - **G.2.1 DocxConverter**: `.docx` built-in when `python-docx` is
     importable (`ingest` extra; MIT + lxml BSD — license rule intact).
     Single-pass `w:t` traversal in document order, derived from the
     pdf-replace reading technique: heading-styled paragraphs (`Title`/
     `Heading N` → `##`+), pipe tables (direct rows; nested tables flatten
     into cell text), fragmented runs merged by joining each paragraph's
     `w:t` descendants, embedded text-box content (`wps:txbx`/`v:textbox`)
     captured, headers/footers excluded (letterhead = scent noise). No
     python-docx → `unsupported`; command hooks still outrank it. 11 tests
     in tests/test_docx_converter.py.
   - **G.4.2.1 edge proposals**: the Curator proposes `related-to` links at
     link-level `confidence: 0.3` toward EXISTING nodes only — candidates
     come from a catalog BM25 search (`make_candidates`; branches, self and
     parent excluded), the model picks from the closed list (hallucinated
     ids structurally dropped), cap 3, dedup vs existing links, optional
     `note` (≤120 chars). Plant now serializes link extras
     (`models.frontmatter_dict` kept only rel/target before — fixed), so
     proposals land in frontmatter as exactly the population H.2 manages:
     Gardener proposes → usage heats → Ranger promotes/prunes. Failures
     never block (counted in stats). 9 tests + end-to-end Ranger handoff
     test in tests/test_curator.py.
   **Remaining (Gardener v3):** entity EXTRACTION (minting new `entity`
   nodes — needs placement policy + `same-as` dedup story, deferred by
   spec v0.12); media extras (faster-whisper transcripts, vision
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
4. **Convergence curve — MEASURED 2026-06-11, criterion NOT met; two
   findings for the paper.** Driver: `scripts/convergence.py` (rebuild →
   5 learning passes of bench v3, heat/shortcuts accumulating, artifacts
   in `bench/_artifacts/convergence/`). Gemma-4 local, hybrid locate:

   | pass | correct | hops | trail_len | tokens | shortcuts |
   | --- | --- | --- | --- | --- | --- |
   | 1 | 11/11 | 1.45 | 2.70 | 1364 | +6 grafted |
   | 2 | 10/11 | 1.27 | 2.55 | 1447 | +2 fortified |
   | 3 | 10/11 | 1.38 | 2.43 | 1478 | +2 fortified |
   | 4 | 10/11 | 1.33 | 2.62 | 1355 | +2 fortified |
   | 5 | 10/11 | 1.33 | 2.62 | 1354 | +2 fortified |

   Drops vs pass 1: hops -12.4%, trail_len -10%, tokens -0.8% — **>= 25%
   NOT met.**
   **Finding 1 (floor effect):** gemma-4 + sniff + hybrid locate already
   navigate v3 cold at ~1.4 hops — near the floor of 1; there is no 25%
   of headroom to reclaim. The convergence hypothesis presumes a
   suboptimal cold baseline (weaker model, deeper forest, or 4+-hop
   cold paths). The MECHANISM works (6 shouts grafted on pass 1,
   reinforce-before-create fortifying on every later pass, zero
   duplicates); the metric has no room on this setup.
   **Finding 2 (pheromone cross-talk / interference):** v3-01 was correct
   on pass 1 and WRONG on passes 2-5: the winning trail of v3-11
   (piloto-resgate) deposited heat that boosted the wrong "novidade de
   abril" release event in locate's ranking (score x (1+0.3*heat)) for
   the semantically similar v3-01 (right answer: plataforma-tambor). The
   pheromone helps REPEATED hunts but can mislead similar-but-different
   questions — first documented interference case. Mitigation ideas
   (future work, spec change required): lower alpha, query-conditioned
   heat, shortcut context metadata. Note Ranger promote/prune does not
   address this: the misleading signal is node heat, not links.
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
6. **Tiered storage (spec v0.11 G.7/G.8) — DONE (2026-06-11):** the map is
   not the territory. `content: inline|cached|reference` (cached bodies in
   `_derived/bodies/` out of git; reference reads the source live; lazy
   resolution in pick/sniff; explicit degraded mode E_NOT_FOUND while
   locate/look keep working; curation always sees full text);
   `archive: never` default (no more `_assets/` copies of durable
   sources); targeted sync (`sync --path`, the event-trigger building
   block: watchers/S3 events/Drive webhooks call it — events trigger,
   the reconciler decides) + mtime/size fast-path (no re-hashing
   unchanged trees). 12 tests in tests/test_content_policy.py.
   **G.9/H.6/Part I — DONE (same day):** `fetch.py` fetcher registry
   (`file://` built-in = test double; `s3://` via optional boto3 with
   `MONKEYLLM_S3_ENDPOINT` for MinIO/R2) + hash-validated
   `_derived/payloads/` cache (tampered downloads refused); `tend`
   rejects remote payloads (local-first, G.9.4); `Vine.prefetch(scope)` +
   `vine prefetch` — the parachute warms the camp (owner's idea: land,
   pull the region's payloads, then sniff/query at local speed); Ranger
   `payload_cache_gb` LRU eviction in run(); `vine snapshot
   create|restore` via git bundle (full audit history travels; optional
   payload sidecar zip; `--to` uploads via the fetcher). 9 tests in
   tests/test_fetch_snapshot.py. Map stays local to the Vine — remote
   clients come through MCP (spec note in G.9).

## Acceptance criteria

- [x] 100 mixed documents ingested end-to-end, >= 95% summaries pass A.4,
      zero broken links post-ingest — measured 2026-06-11 (gemma-4 local):
      100/100 planted, LLM acceptance 100% (85 summaries, 2 retries,
      0 fallbacks), lint errors 0, 1.71 s/doc
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
