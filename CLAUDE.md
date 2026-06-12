# MonkeyLLM — agent guide

Knowledge forest navigable by an SLM: markdown + indexes, traversed through
**Vine**'s MCP primitives. `docs/monkeyllm-spec-v0.12.md` is normative
(earlier versions are archived) — **the spec is the truth**; any contract
change requires a new spec version before code.

## Language policy

**English is the project's native language** — code, comments, docstrings,
tests, docs, CLI output, task files. When touching a file, translate any
Portuguese remnants you find in it (boy-scout rule; full sweep is tasks/T02).
**Every contract token is English** (spec v0.5): node types
(`branch`/`note`/`document`/`entity`/`concept`/`event`/`media`), rels
(`part-of`, `related-to`, `discovered-shortcut`, …), `entity_kind`/`source`
enums, and the parsed index headings (`## Sub-branches`, `## Direct bananas`,
`## Cross trails`, `## Query manual`). The Portuguese tokens were removed —
never reintroduce them.
There are no Portuguese exceptions — all content (node IDs, titles, summaries,
bodies, tags, question sets, system prompts, generator literals) is English.
Forests are never edited in place — change the generator and rebuild.

## Layout

- `src/monkeyllm/` — the `monkeyllm` package, `vine` CLI. `vine.py`
  (10 primitives), `harvest.py` (C.6c composite MCP tool: one-shot zero-LLM
  retrieval), `gardener.py` (Part G ingest: adopt/sync + pluggable
  converters), `ranger.py` (Part H maintenance: evaporation, link
  promotion/pruning, health), `catalog.py` (SQLite + FTS5 = locate's BM25
  side + scan),
  `canopy.py` (optional vector layer, Phase 1), `parser.py`/`models.py`
  (frontmatter), `forest.py`/`gitops.py` (files + commits),
  `telemetry.py`/`trails.py` (traces + pheromone).
- `forests/` — ALL generated forests live here, fully gitignored except
  `forests/scripts/` (the generators: `build_fixture.py`,
  `build_bench_forest.py`, `build_dump.py`). `forests/forest-fixture/` =
  test forest (82 nodes, 12 branches, 1 SQLite dataset, own embedded git);
  `forests/bench-forest/` = Monkey Bench corpus; `forests/dump-ingest/` +
  `forests/_measure-forest/` = curation measurement. Rebuild, never edit.
- `examples/` — how-to-use material. `examples/demo/` = agent↔Vine loop
  for the multi-hop questions (criterion F.5); `harvest.py` is the CLI
  wrapper over `monkeyllm.harvest`.
- `bench/` — Monkey Bench: chunker, RAG baselines (topk/iter), runner.
- `scripts/` — infra + measurement: `setup_models.py`, `serve_llm.py`,
  `bench_locate.py`, `measure_curation.py`, `convergence.py`,
  `junit_to_html.py`.
- `tasks/` — backlog, one file per task (see `tasks/README.md`).
- `_derived/` is disposable and rebuildable (`vine reindex`); never a source
  of truth.

## Commands

```powershell
.venv\Scripts\python.exe -m pytest -q          # suite (must stay green)
python -m monkeyllm.cli init --forest D:\path --title "..."   # new empty forest
python -m monkeyllm.cli validate --forest forests\forest-fixture
python -m monkeyllm.cli reindex  --forest forests\forest-fixture
python -m monkeyllm.cli canopy build --forest forests\forest-fixture  # vector layer
python -m monkeyllm.cli adopt D:\dump --forest D:\forest     # Gardener: mirror a tree
python -m monkeyllm.cli sync --forest D:\forest              # Gardener: hash-diff refresh
python -m monkeyllm.cli ranger --forest D:\forest            # Ranger: evaporate+tend+health
python forests/scripts/build_fixture.py                         # rebuild the fixture
python scripts/bench_locate.py                                  # quality+latency
```

Local models (llama.cpp on the 3090): see `docs/local-inference.md`.

## Conventions and pitfalls

- **Token budgets** with always-explicit truncation (`truncated: true`):
  look 500, move 600, locate/scan/sniff 800. Never cut silently.
- **`locate` is BM25-only by default** (Phase 0, zero embeddings). It becomes
  hybrid (RRF vector+BM25) only when a Canopy index AND an embedder are both
  present — any other combination keeps the BM25-only contract intact.
- **locate/sniff contract split** (spec C.6b): `locate` searches curated
  metadata only; `sniff` searches bodies only (literal grep, no regex).
  Never mix the two.
- `query` is read-only SQL over `type:dataset` nodes: reject every write
  (`;DROP`, `ATTACH`, multi-statement, `PRAGMA`) — there is an injection suite.
- `tend` (spec C.10) is the ONLY dataset write path: single INSERT/UPDATE/
  DELETE, WHERE mandatory on UPDATE/DELETE, no DDL; refreshes `payload_hash`
  and commits only the `.md` (it has its own injection suite too).
- **Datasets are born via `plant` with a declarative `schema`** (spec C.7.1):
  the model never writes DDL — Vine validates names/types, creates the `.db`,
  auto-generates `## Query manual`, and commits only the `.md`. No `ALTER`
  for agents; `tend` stays DML-only forever. Initial `rows` at birth are
  loaded parameterized (v0.9 rule 7) — never as SQL text.
- **Gardener (spec Part G) extends edges only**: converters (config command
  hooks > `monkeyllm.converters` entry points > built-ins) and `on_curate`
  hooks. Primitives' semantics/budgets/guards are NOT extensible; UIs and
  bots are MCP/library clients, not plugins. The Gardener never deletes
  nodes (deleted sources are reported `stale` for the Ranger).
- **Edge proposals (G.4.2.1) target EXISTING nodes only**: the Curator may
  add `related-to` links at link-level `confidence: 0.3`, picked from a
  closed catalog-offered candidate list (hallucinated targets are
  structurally impossible; branches never candidates; cap 3). That 0.3
  population is exactly what the Ranger manages (H.2). The `.docx` built-in
  (G.2.1) needs the `ingest` extra (python-docx, MIT) and excludes
  headers/footers by design.
- **Ranger (spec Part H) manages ONLY links with link-level
  `confidence < 1.0`** (proposals/shortcuts): promote when both endpoints
  are hot, prune when both are stone cold; structural edges and
  confidence-1.0 links are untouchable. Evaporation lives in `_derived/`
  (no commits); promote/prune commit `.md`-only as `ranger(promote|prune)`.
  The Ranger never deletes nodes.
- **Tiered storage (spec G.7-G.9)**: SCENT (passports) always local/git;
  FLESH per `content: inline|cached|reference` policy (`cached` bodies live
  in `_derived/bodies/`, OUT of git; `pick`/`sniff` resolve lazily; an
  unreachable body is explicit `E_NOT_FOUND` while the map keeps working);
  BONE (raw binaries) stays at the source — `archive: never` is the
  default. Curation always sees the FULL text (G.7.4). Events trigger,
  the hash-diff reconciler decides (`sync --path` + mtime/size fast-path).
- **Remote payloads (G.9)**: `payload` may be a URI (`file://`, `s3://` via
  optional boto3; `MONKEYLLM_S3_ENDPOINT` for MinIO/R2). Reads fetch into
  the hash-validated `_derived/payloads/` cache (Ranger evicts LRU, H.6);
  `tend` REJECTS remote payloads (datasets are local-first). `vine
  prefetch <branch>` warms a region after the locate drop. `vine snapshot
  create|restore` = git bundle with full history (Part I); the map itself
  always stays local to the Vine — remote clients come through MCP.
- `plant`/`graft` are atomic and `git commit` **inside the forest**
  (spec C.7/C.8). That is product behavior and it is correct.
- **Binaries never enter the forest git** (spec A.3.1): gitops only versions
  `.md`; payloads (`*.db`, `_assets/`) stay on the filesystem, referenced by
  `payload` + `payload_hash`.
- **NEVER commit to the project's outer repo** — the user commits by hand.
  (Forests under `forests/` have their own embedded git; that is different.)
- The frontmatter parser rejects early: better to refuse garbage than accept it.
