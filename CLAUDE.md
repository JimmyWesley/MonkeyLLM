# MonkeyLLM — agent guide

Knowledge forest navigable by an SLM: markdown + indexes, traversed through
**Vine**'s MCP primitives. `docs/monkeyllm-spec-v0.47.md` is normative
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
  `harvest`'s item cap is `MONKEYLLM_HARVEST_MAX_K` (default 5, garbage
  refused as `E_SCHEMA`, spec C.6c v0.34); its 4000-token budget is the
  outer wall regardless of cap, and the `answer` cache keys the sweep by
  the *effective* (capped) `k` (J.10.7).
- **`locate` is BM25-only by default** (Phase 0, zero embeddings). It becomes
  hybrid (RRF vector+BM25) only when a Canopy index AND an embedder are both
  present — any other combination keeps the BM25-only contract intact.
- **locate/sniff contract split** (spec C.6b): `locate` searches curated
  metadata only; `sniff` searches bodies only (literal grep, no regex).
  Never mix the two.
- **A read embeds the query and nothing else (spec K.2 + K.6 + J.13.4,
  v0.42)**: lazy re-embedding used to run inside `locate`, so the question
  arriving after an ingest paid to embed every document of it — unbounded
  work in the primitive with the tightest budget (F.6); one measured
  `locate` cost 2.67 s. The vector scan was never the problem (0.044 ms
  per dim-1024 dot product). Now: reads embed only the query, through the
  **K.6 memo** (`embed(model, text)` is pure → `_derived`, keyed by model
  + normalized text, LRU-bounded); node vectors are refreshed **only** by
  `build_canopy` or `POST /v1/admin/canopy {refresh: true}` (J.13.4, in
  Studio's Optimize tab). The debt is visible: `canopy_status` carries
  `stale`. A node not yet embedded is still found by BM25 — the catalog
  upsert is synchronous — so the cost is dense-half recall, never
  findability. A refresh against an absent/mismatched index REFUSES
  (K.4: a partial re-embed spans two spaces and fails silently).
- **The repair is on the console (spec J.13.3, v0.41)**: `POST
  /v1/admin/reindex` rebuilds one forest's catalog — `admin` on that
  forest AND an unrestricted scope (the count IS the forest's size and
  every row rewritten includes nodes a branch-scoped principal may not
  read). It runs on the lane and the caller waits, like a canopy build;
  it is NOT a J.9 job (it plants nothing, commits nothing, has no report
  to stream). Writes `_derived/` only, so a **read-only Station serves
  it too** — an index it could never repair would degrade forever. In
  Studio it lives in the ingest console's **Optimize** tab (renamed from
  "Refresh"): `sync` keeps the content current, `reindex` keeps what
  finds it current. Every tab value MUST be in `useRouteState`'s `allow`
  list — `sync` never was, so clicking it wrote an address the validator
  rejected and the console snapped back to Upload (J.5.8).
- **The scan is memoized, never replaced (spec C.6b.1, v0.40)**: two
  thirds of a global `sniff` was the OS opening files, on every ask, and
  since J.10.7 v0.35 the sweep's retrieval runs even when the answer is
  served from the store. `_sniff_body` is a pure function of (body,
  folded term), so `_derived` keeps one row per (term, node) — **including
  non-matches**, or the ~95% that never match are rescanned forever —
  valid while `nodes.body_hash` still matches. Hash, never `mtime`: a
  `reindex` or an edit reverted to its original text must invalidate
  nothing. Rows are per LINE (`[line_no, section, pos, line_text]`)
  because the scan emits one match per line centred on the *leftmost*
  term that hit it — storing rendered snippets would make a two-term
  question disagree with itself. Ranking (`heat`, `score`, order) is
  NEVER memoized; it is recomputed per call. `content: cached|reference`
  bodies carry an empty hash and keep the direct scan: the `.md` the
  hash digests is not the text they scan. Dropping the memo may change
  latency and nothing else.
- `query` is read-only SQL over `type:dataset` nodes: reject every write
  (`;DROP`, `ATTACH`, multi-statement, `PRAGMA`) — there is an injection suite.
- **A row cap is not a token cap (spec C.5.1, v0.47)**: `query` was the only
  read primitive with no budget, so `SELECT *` on a 141-column export
  measured **86,929 tokens for 15 rows** (429,397 for 200) — into a walk
  that re-sends its history every turn. `BUDGET_QUERY` = 2000, below
  `pick`'s 4000 because a body is read once and a result is carried
  forward. Whole rows drop from the tail; **`columns` never does** — it is
  the map back, so a result whose every row was refused still says *these
  are the columns your statement produces*. `limited` (the injected `LIMIT
  200` was reached) and `truncated` (the budget dropped rows) are
  independent, and the hint MUST lead with **the missing rows exist**: a
  live model read "truncated to 5 of 15" as "only 5 matched" and offered
  them as the answer. Sized by summing each row's own cost, never by
  `shrink_list_to_budget` — 200 re-serialisations of a wide result is
  seconds.
- **Invalid is not forbidden (spec C.5.2, v0.47)**: every SQLite failure
  wore `E_QUERY_FORBIDDEN`, the code for attempting a write, so a mistyped
  table on a readable dataset was indistinguishable from a policy denial —
  in the console and in the audit. `E_QUERY_INVALID` (HTTP **400**) is what
  SQLite decides; `E_QUERY_FORBIDDEN` (**403**) stays what the guard
  decides. Both `query` and `tend`: one kept honest would make the code
  mean different things per primitive.
- `tend` (spec C.10) is the ONLY dataset write path: single INSERT/UPDATE/
  DELETE, WHERE mandatory on UPDATE/DELETE, no DDL; refreshes `payload_hash`
  and commits only the `.md` (it has its own injection suite too).
- **A `.db` is adopted, a `.csv` is converted (spec G.2.2, v0.44)**: a
  SQLite source becomes a `payload` conversion — the converter reads
  structure + 3 rows per table and the Gardener **copies the file** into
  place as the payload, planting with no `schema` (C.7.1's "payload
  already exists" path). Never re-INSERT a `.db` row by row: unbounded in
  the source's size, lossy in its types, and the round trip's destination
  is what the source already was. Every dataset passport carries the
  **sample map** (G.2.3): `## Query manual` + `## Sample rows` — every
  table, first 3 rows, cells clipped at 120 chars, ≤20 tables sampled and
  the omission stated. That map is the ONLY thing `sniff` can see inside a
  payload. `sync` rewrites those two sections and no others. Workbooks are
  one table per sheet (G.2.4) — and **never trust `<dimension>`**: openpyxl
  in read-only mode believes it, and non-Excel exports declare `A1:A1`, so
  a real 130-row sheet arrives as one row and reads as "no data"
  (`ws.reset_dimensions()`).
- **A count limit guards invention, not data (spec G.2.5, v0.45)**: C.7.1's
  ≤10 tables / ≤50 columns stop a model inventing DDL; they were also
  refusing real 141-column ERP exports. `Vine.plant(node, adopted=True)`
  drops **only those two counts** — names, types and `primary_key` are
  validated as always. Keyword-only and unreachable from the wire
  (`ScopedVine.plant(self, node)` forwards `node` alone), because a flag an
  agent can set is not a guard. A wide table's real cost is tokens, so the
  bound lives in the G.2.3 map instead: ≤12 sampled columns, omission
  stated, while the manual still names every column.
- **`## Notes` is the human half of the map (spec C.2.1, v0.46)**: the map
  says what is in a dataset, a person says what it *means* (which column is
  USD, what a status code stands for, which join answers the real
  question). `look` returns it as `notes` for `type: dataset` — bounded to
  `BUDGET_NOTES` (200) inside look's 500 and flagged `truncated` when
  clipped — because the agent's path is `look` → `query` and a note only
  `pick` can reach is a note nobody reads. Written through ONE `graft`
  (`append_section` first time, `replace_section` after); the Gardener
  never touches it (G.2.3 rule 4) and curation MUST NOT either. A console
  edits it from `pick`, NEVER from the digest — saving a clipped copy
  deletes the tail. Datasets only: elsewhere the body is already reachable.
  **The notes travel with the dataset on EVERY path** (v0.47): any material
  a host assembles for a model carries the `notes` of every dataset in it,
  not just `look`. `harvest` does it because the sweep never looks; the
  walk's entry (J.10.5) does it because the entry is `locate` — curated
  metadata, no body — and on a dataset the natural next move is `query`,
  so a model that never looks never reads a word the operator wrote. The
  mode with more freedom was the mode with less information, and it read
  as the agent ignoring them. Unconditional: whether the section shares
  vocabulary with today's question is not a reason to withhold it. The walk calls primitives; the sweep is
  `locate` + `sniff` + matched sections and looks at nothing — so notes
  that only ride in the digest are invisible from the console's ordinary
  ask, which is exactly where they get written. `look`'s dataset extras are
  now computed per requested field, so `fields=["notes"]` (and the sweep's
  existing `fields=["summary"]`) no longer open the payload for nothing.
- **Curation reads the map, never the file (spec G.4.6, v0.45)**: a dataset
  is curated from `## Query manual` + `## Sample rows`, so a 5 MB CSV and a
  5 GB `.db` cost the model the same ~150 tokens. `_clip` cuts by LINE —
  flattening newlines turned every pipe table into one line of pipes.
- **A stage is reported, never yielded (spec G.10.1, v0.45)**: a G.10 step
  is still a whole document (yielding mid-document would suspend an open
  model call), but the Gardener names its phase — `convert`/`curate`/
  `plant` — through `on_stage`, and the J.9 job carries it as `stage`. That
  is the only reason a one-file batch's progress bar can move; a raising
  observer is swallowed. A `sync` never reports `curate`: a refresh keeps
  the scent somebody already approved.
- **"Nothing to do" is not a rejection (spec J.8, v0.45)**: curation stats
  carry `skipped`, and the console's discriminator is **no fallback and no
  retry** — a real rejection always leaves one behind. Reporting an
  all-`unchanged` batch as a model failure sends the operator to tune a
  model that was never asked anything.
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
  the running job in the address as `?job=`. Entering the ingest console
  without `?job=` rediscovers a running job from the job list and puts it
  back in the address (J.9.1, v0.36); next batches may wait in a FIFO in
  tab memory (J.9.2) — visible, never in the address, dead with the tab,
  fired one per settle, held on cancel or non-`E_LOCKED` refusal. The
  host itself still never queues. A pill on every console announces the
  running batch and the queue (J.9.3, v0.37): it reads the job board only
  — never a browser-storage copy — through ONE watcher per forest whose
  cadence follows the attention (~1 min collapsed, ~2 s expanded or with
  the ingest console open), and it yields on the ingest console itself.
- **Two hashes: the question finds the entry, the reading decides the
  model (spec J.10.7, v0.35 — T11)**: the host caches `answer` and nothing
  else, per forest, in `_derived/cache/`. The sweep's retrieval runs on
  EVERY ask (it is the cheap half); its key — normalised question,
  effective terms, effective `k`, hybrid, binding, scope, **no HEAD** —
  finds the entry, and the **reading fingerprint** (material as a set
  keyed by id: type/title/summary/matches/content + truncated; never
  score, heat or order) decides: equal → serve the stored reply with fresh
  retrieval fields; different → the model runs and the entry is replaced.
  The walk keeps HEAD in its key and is served whole (it cannot be
  re-walked without paying per hop). The **whisper closes every hosted
  answer** — heat on the evidence via `Trails.add_heat`, hit and miss
  alike. Empty-evidence, errored, truncated or writing runs never enter;
  an entry never crosses scopes; a hit says `cached: true`, carries
  `Server-Timing: cache` with no `model`, audits with the entry digest,
  and never re-bills the recorded cost. `cache: false` skips the serve
  and replaces. C.6c.2: index nodes are never match-refined — sniff
  resolves an index id to its subtree, which mislabelled children's
  snippets and destabilised the reading.
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
- **The Data console makes, imports and leaves (spec J.5.10, v0.44)**: a
  dataset is born through ONE `plant` with a declarative schema (no DDL in
  the console, ever); a file is imported through the J.8 `upload` ingest
  (never parsed in the browser, never planted beside the Gardener) and the
  answer is a J.9 job; a selected dataset collapses the picker to itself
  and offers an explicit way back that clears `?dataset`/`?table` — and
  refuses while a `tend` draft is staged. SQL is coloured where it is
  typed: a highlighted mirror under a transparent `<textarea>`, mirror
  `aria-hidden` so the characters are not read twice.
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
