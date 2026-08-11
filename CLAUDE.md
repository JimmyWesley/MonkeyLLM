# MonkeyLLM — agent guide

Knowledge forest navigable by an SLM: markdown + indexes, traversed through
**Vine**'s MCP primitives. `docs/monkeyllm-spec-v0.33.md` is normative
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

## Licensing

Two licenses (see `LICENSING.md`): **Apache-2.0** for the engine and
everything around it, **AGPL-3.0-only** for the host (`apps/station/`,
`apps/studio/`). Every new source file carries an SPDX header naming the
license of the tree it lives in. Apache-2.0 is one-way compatible with
AGPL, so the direction is load-bearing: the host may import the engine, and
`src/monkeyllm/` **must never import from `apps/`** — that is now a legal
boundary, not only the Part J "privileged client" design rule.

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
- **Starting a Station mints nothing (spec J.2.5, v0.28)**: the registry is
  as authoritative after boot as before it, so J.2.4's setup window survives
  to be used. The first-run banner names the open door (setup URL / env
  username — never the env password) and says nothing on later restarts.
  `--bootstrap-key` (or `MONKEYLLM_STATION_BOOTSTRAP_KEY=1`) is the opt-in
  for a browserless deployment: mints **into that same window only**, with
  the owner bit, and thereby closes it. Never grant a first credential per
  forest — an empty volume has none, which is the v0.25 deadlock.
- **Latency is reported by the host, never by the client (spec J.10.6,
  v0.29)**: every primitive response carries `Server-Timing: vine, host[,
  model][, cache]` — a **header**, because the body is the agent's context
  window and it is token-budgeted, so console instruments must never be
  added to it. `vine` is read off the Part D tracer (never a second
  stopwatch), the clocks present account for the whole host span, and a
  console MUST lead with the
  engine figure: over a network a 0.2 ms `locate` looks like 29 ms, and a
  panel that prints the 29 is describing the internet.
- **Nobody's first call pays for the process (spec J.6.1 + C.6.1, v0.29)**:
  `_derived/` databases open in **WAL + `synchronous=NORMAL`** (every read
  primitive deposits pheromone, so every read is also a commit; the files
  are the truth and `reindex` is the repair, so the durability given up was
  never owed). `Vine.warm()` faults those pages in through **storage only,
  never a primitive** — warming through `locate` would forge the heat the
  Ranger reads as evidence. A Station opens and warms every forest at boot
  (`--no-warm` / `MONKEYLLM_STATION_WARM=0` for registries too big to hold
  open), best effort: one locked forest never stops the others.
- **`app.state.pool` is only touchable through `app.state.forest_lane(id)`**
  (spec J.9, v0.32): one worker thread — lane — per forest; a SQLite
  connection belongs to its opening thread, and since boot warming the pool
  is rarely empty. Never touch a vine from another forest's lane, and never
  from the event loop.
- **Batch ingest is a job (spec J.9 + G.10, v0.32)**: `adopt`/`sync`/
  `upload` validate synchronously and answer **202 + job** (`wait: true`
  blocks; the MCP `ingest` tool waits by default); `compose` stays in
  place. One batch per forest at a time — the E_LOCKED refusal names the
  running job. The Gardener steps one document per `next()`
  (`adopt_iter`/`sync_iter`), records `source_root` BEFORE the first step
  (that is what makes cancel/crash recoverable by `sync`), and same-forest
  reads interleave between steps. Job records live in host memory only:
  `GET .../jobs[/{id}]` must never touch a forest (no lane, no trace, no
  pheromone), a restart forgets records but never work, and Studio carries
  the running job in the address as `?job=`.
- **The answer already bought is served, said, and still heats the forest
  (spec J.10.7, v0.33 — T11)**: the host caches `answer` and
  nothing else, per forest, in `_derived/cache/`. The key is a closed list —
  normalised question, effective terms, `k`, hops, resolved binding, caller
  scope, forest HEAD — so HEAD is the invalidation and TTL is hygiene only;
  an entry never crosses scopes. Empty-evidence, errored, truncated or
  writing runs never enter. A hit says `cached: true`, carries
  `Server-Timing: cache` with no `model`, audits with the entry digest
  (cost recorded as avoided, never re-spent), and deposits heat on the
  stored trail via `Trails.add_heat` — storage, never a primitive (J.6.1's
  warming rule in mirror). The near-question tier exists only when Canopy
  AND an embedder are present, is off by default, and names the stored
  question it answered. `cache: false` skips the read and replaces the
  entry.
- **The address is where the console is (spec J.5.8, v0.30)**:
  `/f/{forest}/{console}` with the selection in the query (`node`, `mode`,
  `dataset`, `table`, `tab`). Studio keeps **no second copy** of it — `App`
  reads `router.js`, never `useState` — because the address bar is the copy
  the operator can see. Moving pushes, adjusting replaces, rendering never
  writes. A forest the key has no grant on is **said, not swapped**: the
  console that silently opens a different forest is how somebody comes to
  believe they are reading one they are not. The address restores a page,
  never a call — no reload may spend a model call or a commit. On the host,
  a GET that matches no route and no file is answered with the shell **only
  when it accepts HTML**: a missing asset must stay a 404, or the browser
  gets an HTML body under a JavaScript MIME type.
- **The console shapes the forest through `plant` (spec J.5.7, v0.27)**:
  branch creation in Studio composes ONE `plant` call — the id lives under
  the chosen parent, the parent-index entry and the commit are the engine's.
  Ids are never typed (they are immutable) and there is no move/rename/
  delete: no primitive relocates a node, so misplacement is permanent.
- **Ingest sources are contained (spec G.3/G.8/J.8.2, v0.26)**: an absent
  source is `E_SCHEMA`, never the working directory; a source may not be,
  contain or sit inside the forest (only `_derived/` is exempt, for upload
  staging); a directory carrying `_index.md` is pruned from every walk; a
  targeted `sync` path is contained **after** resolution. On the host,
  `MONKEYLLM_INGEST_ROOTS` is an allow-list that is **empty by default and
  empty means none** — `admin` says who may ask, the roots say what exists
  to be asked for, and the registry root is never one of them.
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
