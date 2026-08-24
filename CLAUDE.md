# MonkeyLLM agent guide

Knowledge forest navigable by an SLM: markdown + indexes, traversed through
**Vine**'s MCP primitives. `docs/monkeyllm-spec-v0.64.md` is normative
(earlier versions are archived) **the spec is the truth**; any contract
change requires a new spec version before code.

## Language policy

**English is the project's native language** code, comments, docstrings,
tests, docs, CLI output, task files. When touching a file, translate any
Portuguese remnants you find in it (boy-scout rule; full sweep is tasks/T02).
**Every contract token is English** (spec v0.5): node types
(`branch`/`note`/`document`/`entity`/`concept`/`event`/`media`), rels
(`part-of`, `related-to`, `discovered-shortcut`, …), `entity_kind`/`source`
enums, and the parsed index headings (`## Sub-branches`, `## Direct bananas`,
`## Cross trails`, `## Query manual`). The Portuguese tokens were removed —
never reintroduce them.
There are no Portuguese exceptions all content (node IDs, titles, summaries,
bodies, tags, question sets, system prompts, generator literals) is English.
Forests are never edited in place change the generator and rebuild.

## Licensing

Two licenses (see `LICENSING.md`): **Apache-2.0** for the engine and
everything around it, **AGPL-3.0-only** for the host (`apps/station/`,
`apps/studio/`, `apps/clipper/`). Every new source file carries an SPDX header naming the
license of the tree it lives in. Apache-2.0 is one-way compatible with
AGPL, so the direction is load-bearing: the host may import the engine, and
`src/monkeyllm/` **must never import from `apps/`** that is now a legal
boundary, not only the Part J "privileged client" design rule.

## Layout

- `src/monkeyllm/` the `monkeyllm` package, `vine` CLI. `vine.py`
  (10 primitives), `harvest.py` (C.6c composite MCP tool: one-shot zero-LLM
  retrieval), `gardener.py` (Part G ingest: adopt/sync + pluggable
  converters), `ranger.py` (Part H maintenance: evaporation, link
  promotion/pruning, health), `catalog.py` (SQLite + FTS5 = locate's BM25
  side + scan),
  `canopy.py` (optional vector layer, Phase 1), `parser.py`/`models.py`
  (frontmatter), `forest.py`/`gitops.py` (files + commits),
  `telemetry.py`/`trails.py` (traces + pheromone).
- `forests/` ALL generated forests live here, fully gitignored except
  `forests/scripts/` (the generators: `build_fixture.py`,
  `build_bench_forest.py`, `build_dump.py`). `forests/forest-fixture/` =
  test forest (82 nodes, 12 branches, 1 SQLite dataset, own embedded git);
  `forests/bench-forest/` = Monkey Bench corpus; `forests/dump-ingest/` +
  `forests/_measure-forest/` = curation measurement. Rebuild, never edit.
- `examples/` how-to-use material. `examples/demo/` = agent↔Vine loop
  for the multi-hop questions (criterion F.5); `harvest.py` is the CLI
  wrapper over `monkeyllm.harvest`.
- `bench/` Monkey Bench: chunker, RAG baselines (topk/iter), runner.
- `scripts/` infra + measurement: `setup_models.py`, `serve_llm.py`,
  `bench_locate.py`, `measure_curation.py`, `convergence.py`,
  `junit_to_html.py`.
- `tasks/` backlog, one file per task (see `tasks/README.md`).
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

- **A transport method is not a capability, and 404 is not a refusal (spec
  J.1.2 rule 4 + J.1.4, v0.64)**: J.1.2 rule 4 withholds what nothing is
  registered behind, and the implementation withheld one name more than the
  rule ever named — `subscriptions/listen`, which at the **2026-07-28** era
  is not a feature a client lists but the **only server-to-client channel**,
  the replacement for the standing GET stream. The Station answers
  `server/discover` at that era with a 200, so it says the era is spoken;
  the client then opens its listen stream and the SDK answers an
  unregistered method with **HTTP 404**, which on this transport means *your
  session is gone* (2.5.3). A released client (Antigravity, on the Go SDK)
  read exactly that, tore down a healthy connection, and reported **0
  tools** — the error naming a session id never issued rather than the
  method never served, so the symptom arrives with the wrong name attached
  and the call that fails is the NEXT one. Now: the withheld list is
  `UNSERVED_METHODS` and reaches `prompts/*` and `resources/*` and stops (a
  test asserts that SHAPE, because the next name added will be added for
  rule 4's reason and may not be rule 4's kind of thing); and `SoftRefusal`
  re-states any 404 whose body is a JSON-RPC error as a **200** with the
  envelope untouched — the mount is stateless, so no 404 it produces can be
  about a session, while a 404 that is not a JSON-RPC body (a wrong path
  under the mount) is left alone, because that one really is an address.
  The admitted cost: at 2026-07-28 the SDK derives `tools.listChanged` from
  the served handler, so we announce `true` and publish no such event — an
  empty promise by rule 4's letter, but the round trip rule 4 was written
  against does not exist here (one quiet stream, versus a fatal 404). The
  earlier eras are unchanged to the bit. The end-to-end stream is NOT in the
  suite: its response never ends, and the in-process client cannot hold one
  open without holding its own shutdown (F.135 records the gap).
- **The budget nobody chose is still a budget (spec J.10/J.10.8, v0.63)**:
  every binding shipped at `max_tokens` **600**, and J.10.8 stated the cap in
  the prompt only **when a caller set `reply_tokens`**. Both were sized for a
  reply that is prose, and the `answer` turn is not: it is a JSON object
  carrying the text AND `answer_nodes`, so the budget pays for the citation
  apparatus before it pays for a sentence (a client that also wants a verbatim
  `proof` pays for that too). Measured on the 18-question suite a 12B scored
  **16/18** at 600 and **neither miss was navigation** one had already run
  `SUM(...) GROUP BY region` on the right dataset and was cut mid-object, the
  other reached the right node in ONE hop and lost the right sentence to a
  truncated `proof`. At 1500 both pass and the wall time falls with them
  (139 s → 15 s, 149 s → 11 s), because the rejected retries stop. What hid
  it for so long is the symptom's shape: **a cut answer scores as a wrong
  answer**, never as a cut, so the console blames the model and the operator
  tunes a model that was right. Now: the `answer` role binds at **1500**
  (`ingest`/`vision` keep 600 a scent and a description carry no citations;
  the curator's 300 is a different client); the runtime fallback and
  `Registry.bind_model` follow; and the prompt states the cap **whatever chose
  it**, because the silent case was exactly the one where nobody had chosen.
  Raising a default reaches nobody who already has a row, so existing
  bindings move by a **one-time data repair** (`DATA_REPAIRS` in
  `registry.py`, stamped in `PRAGMA user_version`) the point is not that it
  runs but that it runs ONCE: a deliberate 600 afterwards is byte-identical to
  the shipped one, and only the stamp tells them apart. `max_tokens` is in the
  J.10.7 store key, so the repair **invalidates that forest's answer cache**
  once, by design.
- **The cold scan was never the corpus (spec C.6b.1, v0.62)**: a `sniff`
  for a term no memo entry covers must read every body in scope, and that
  cost was deferred as "the corpus" until it was measured. On 1,902 nodes /
  11.9 MB it was **629 ms of CPU of which reading the files was 31**. The
  fold (C.6b's matching rule: lowercase + strip diacritics, length
  preserved) was a Python loop over every character of every body — 387 ms,
  62% — and G.7's `content:` marker was a MULTILINE regex over whole files
  looking for a line only the frontmatter can hold — 71 ms more. Now
  `_fold` is one `str.translate` against `_FOLD_TABLE` (ASCII takes
  `str.lower()`, which for ASCII *is* the fold) and `_split_raw` finds the
  frontmatter/body boundary once so the marker is searched in the head:
  **133 ms**, sweep 933 → 448. `_FOLD_LIMIT` is `0x30000` and **not the
  BMP** — cased scripts live in the SMP (Deseret, Adlam, Osage, Vithkuqi,
  Warang Citi, Medefaidrin) and CJK Compatibility Ideographs decompose to
  U+2FA1D; a BMP table stops folding six living scripts in silence, so
  F.129 pins the limit against the Unicode version in use. The table is
  built on first use, never at import: a `plant` folds nothing. The
  trigram-FTS body index (P-03) is NOT here and its case is weaker — it was
  proposed to remove a corpus read that is 5% of the call. Still open, and
  bounded by the v0.59 rules: a warm `sniff` stays proportional to its
  matches, which for a term matching most of a forest means deserializing
  one memo record per matching node to rank it.
- **An upload is a courier, not a mirror (spec J.8.3, v0.61)**: the bug
  reported was a `prune` that undid itself on somebody else's next upload;
  the cause was that the whole upload path treated `_derived/uploads` as a
  source tree the forest MIRRORS. `adopt_iter` records its source as
  `source_root`, so **one upload repointed a forest that really did mirror
  a folder** (and J.8 makes a console show that root beside the refresh
  control); the refresh then walked the whole DIRECTORY, so a file whose
  node had been pruned was read as new and replanted. Now ONE path for
  every upload — `sync_iter(paths=[...], consume=True)`: plants what has no
  passport, refreshes what has one, records NOTHING, and **removes each
  file as it becomes a node** (`report.consumed`; `_LANDED` = planted/
  updated/unchanged). A file that FAILED stays — nothing landed and it is
  the evidence. `consume` is keyword-only and host-supplied (G.2.5's
  construction): the engine never decides a source may be deleted, and a
  host directory is never touched (G.3). `_apply_content_policy(staged=)`
  degrades `reference` → `cached` for a staged source, because a body
  addressed to a courier vanishes. `prune` (C.14 r2) still takes a staged
  file to `_derived/graveyard/<id>/source/` via `Vine._staged_source` —
  that path is the repair for forests ingested by an OLDER Station, which
  is all of them.
- **What never landed is countable and clearable (spec J.13.7, v0.61)**:
  `GET|POST /v1/admin/staging`. Unrecorded = a staged file no passport
  records as its `source_path` (`Gardener.unrecorded_sources`) — never a
  heuristic on age or name, which would eventually delete a document
  somebody was about to ingest. POST **moves** them to
  `_derived/graveyard/_staging/`; refuses `E_LOCKED` while a batch runs;
  `admin` + unrestricted scope, GET served read-only, POST not. Fourth card
  in Studio's Optimize, hidden at zero. Invisible accumulation is what made
  the resurrection possible, so the answer is not a shell.
- **A missing payload is a fact about the payload (spec C.2.2, v0.61)**:
  `look` on a `type: dataset` node whose LOCAL payload is gone returns the
  passport with `payload_missing: true` and without `query_manual`/
  `sample_rows` — it used to raise `E_NOT_FOUND` for the whole digest, so a
  node `scan` listed was unreadable through the primitive that reads
  passports. The flag survives the `fields=` filter (it is the answer to
  "why is the field I asked for absent"); `notes` is unaffected (body, not
  file); `query`/`tend` still refuse; remote payloads (G.9) are not this
  case. `coverage` counts the same condition per root and in the totals
  (C.17 rule 11) — a stat, never an open, so rule 1 stands.
- **`dest` names a branch in either spelling (spec G.3, v0.61)**:
  `normalize_dest` strips a trailing `/_index` and reads bare `_index` as
  the root, applied in `adopt_iter`/`sync_iter` AND at the Station boundary
  **before** the scope test, so the test and the write agree. Before this,
  the canonical form every other surface uses built `x/_index/_index` and
  was refused with an `expected_parent` naming the exact string the caller
  sent.
- **`mode` is the caller's own word (spec J.9, v0.61)**: it used to be
  rewritten to `"sync"` mid-call by the upload flip, so a caller that said
  `upload` read `sync` beside an `updated` list of nodes it never named.
  The flip is gone, so there is one mode and it is the request's. A
  `strategy` field naming the mechanism was drafted and dropped — it
  labelled a mechanism that should not have existed.
- **Every read by id answers the waymark (spec C.15 rule 4, v0.61)**:
  `Vine._waymark` / `_read_or_waymark` is the one place — `look`, `pick`,
  `move`, `history`, `view` and `query` alike. v0.58 implemented five of
  six; `pick` read the file directly, and `pick` is the call an agent
  holding a written-down id actually makes.
- **A derived alias is a name, not a leading digit (spec G.2.6 rule 5,
  v0.61)**: `_LEADING_NUMBER_RE` requires the digits to END (separator or
  stem end), so `9router-free-ai-router` derives nothing from its `9` while
  `291-provider-budget` still derives `291`/`back-end/291`/`BE-291`. A
  single digit in the index searched by curated metadata alone is noise
  with the power to rank.
- **An unknown token names the set that would be accepted (spec A.2,
  v0.61)**: `dialect.declared_hint` on every undeclared `type`/`rel`
  refusal, in `plant` and `graft`. The forest's `_meta/schema.md` is the
  runtime authority, so a rel the engine ships may legitimately be absent
  (a pre-v0.58 forest has no `supersedes`) — that is A.2 working; a refusal
  with no `hint` is not.
- **What ingest derives can be re-derived (spec J.13.6, v0.61)**:
  `Gardener.recurate(derive=["aliases"])` behind `POST /v1/admin/recurate`
  — from the forest's OWN passports, so no source tree, no converter, no
  model, no network. Union semantics (G.2.6 rule 3): adds only, never
  displaces a hand-written alias, twice is once. One `.md` commit per
  changed node (`recurate(aliases): <id>`), principal stamped; `admin` +
  unrestricted scope, writer lane, caller waits (reindex's shape) — and
  unlike reindex it COMMITS, so a read-only Station refuses it. `origin` is
  deliberately NOT derivable here: inventing provenance from a recorded
  relative path is the one thing this product may not do. In Studio it is
  the third card in the ingest console's **Optimize** tab.
- **The floor says which half refused (spec J.10.10 rule 8, v0.61)**: the
  `insufficient_evidence` payload carries `below_min_score` — content-
  carrying items that did not clear the threshold. RRF output is
  compressed, so a meaningful `min_score` usually admits only the item that
  ranked top of both retrievers, and `(2, 0.02)` then refuses questions the
  forest answers well. The useful pair is `(1, min_score)`; the skill says
  so. An uploaded document's `origin` is its entry's `source_url` and
  nothing else (G.2.7 rule 1) — the skill's saving block and the console's
  upload form both name it now, which is the whole of what "A-02" was.
- **A skill is the size of the agent (spec J.5.12, v0.60)**: the Skills
  console hands out a FOLDER — `SKILL.md` (the core: recall, `locate` vs
  `sniff`, coverage-before-a-silence, citation, refusals) plus
  `references/{saving,writing,time,datasets,sharing}.md`, each named in the
  core with the trigger that sends an agent to read it. Blocks default to the
  key's own caps, so a `{read, ingest}` paired key stops paying ~1,400 tokens
  of `plant` anatomy it may not execute; a block chosen beyond the key names
  the capability in its own first line; the folder also downloads as one
  arranged `.zip` (`apps/studio/src/zip.js`, stored entries, no dependency)
  for the machine with no shell to paste into. Several INSTALLED skills is NOT the
  split — each costs its `description` every session and the runtime, not the
  core, decides which loads. Every example carries the `forest` argument (the
  v0.59 file had 23 call examples and passed it in none). Forests are
  selected and baked as INTENT: `forests()` is the authority, >1 forest bakes
  a routing table from C.17 `coverage`, one forest teaches the live call
  instead (a copy of a shape can only drift). Blocks/forests/assembly ride
  the ADDRESS (J.5.8), because the address is what rebuilds this exact skill
  later — the core names that link as the repair for its own staleness. The
  agent never installs it: a skill outlives the connection that delivered
  it, so no endpoint and no `skill()` tool (a tool description is charged to
  every client every session, forever). Text in `apps/studio/src/skill.js`;
  `apps/studio/check-skill.mjs` IS F.111-F.116 + F.127 and runs from
  `tests/test_skill_console.py`. **The name is derived** (`skillName`,
  v0.61): it was a constant, so one skill per forest — what the console
  invites — collided on `name:`. Sorted ids, hashed when they would not
  fit; the same name is the frontmatter's, the folder's and the archive's.
  A generated file may never teach a call this deployment refuses (F.127):
  v0.60 shipped `dest: "decisions/_index"` into the one write example while
  the server rejected exactly that form.
- **A node moves once, and the old address says where (spec C.15,
  v0.58)**: `transplant(id, new_id)` — leaf only (branches never; move
  their leaves), passport + backlinks + both indexes + payload in ONE
  commit (git's rename detection is what keeps `history --follow`
  whole). The waymark is `moved_from` on the passport — the catalog's
  `moves` table is DERIVED from it at upsert, so a reindex rebuilds the
  redirect and nothing lives only in `_derived`; the old id also joins
  `aliases`. A read of the old id raises `E_MOVED` (404) carrying
  `moved_to` — and `ScopedVine._translate_moved` collapses it to the
  byte-identical `E_NOT_FOUND` when the destination is out of scope (a
  waymark must not be a periscope). `moved_from` in a `plant` is
  `E_SCHEMA`: only transplant writes it. Heat re-keys via
  `Trails.rekey`, best effort.
- **The document's past is readable (spec C.16, v0.58)**: `history(id,
  limit≤50)` over `GitRepo.file_history` (`--follow`, `%aI` so the
  timestamp finally has time of day, unit/record separators so a commit
  MESSAGE with newlines cannot fake a boundary), `action` parsed off the
  subject prefix, `by` from the `station-principal:` trailer. A listing,
  never time travel — reading a body AT a commit stays Part I's.
- **A batch is one plant (spec C.7.4, v0.58)**: `plant([...])` ≤20 —
  every node rehearsed through `_plant(dry_run=True, pending=…)` BEFORE
  any write (so a branch and its children share a batch, in order), then
  one commit for the lot or nothing at all. `existing` is `if_absent`'s
  per-node answer; in-batch duplicates and `schema` nodes refuse (a
  payload birth mid-batch has no rollback story). `ScopedVine.plant`
  gates EVERY node before the engine sees the list.
- **A replacement suppresses, `succeeds` does not (spec C.6c.4, v0.58)**:
  new rel `supersedes`/`superseded-by` — the sweep drops a candidate a
  LIVE node supersedes, refills the seat, and NAMES what it hid
  (`superseded_excluded`); `include_superseded: true` restores the
  history view and keys differently. Navigation (`locate`/`sniff`/
  `scan`/`move`) never suppresses. Under a policy the superseder must be
  visible to suppress (`visible=` rides from `ScopedVine.harvest`).
  Existing forests opt in by declaring the rel in their `_meta/schema`
  (A.2's rule) — the fixture generator declares it.
- **Identical questions in flight share one generation (spec J.10.7,
  v0.58)**: the `inflight` table in `app.py` keyed by (forest, store
  key) — a follower awaits the leader's `asyncio.Event` on the loop (no
  lane held), then `recheck_store` re-consults under its OWN reading
  fingerprint; a differing reading still buys its own call. The leader
  releases in a `finally` AFTER the settle, so an errored leader frees
  its followers instead of stranding them. `cache: false` never
  coalesces.
- **Ingest fills `origin` (spec G.2.7, v0.58)**: source file's `file://`
  URI on adopt and refresh, the upload's declared `source_url` when
  there is one, nothing for a staging path under `_derived/` — and only
  when ABSENT (a hand-written origin outranks a derived one, G.2.6's
  union rule for one scalar). The sync fast-path backfills it, so a
  forest ingested before the rule gains origins without re-conversion.
- **Reads scale on a reader pool (spec J.6.2, v0.57)**: each open forest
  has K read-only Vines (`MONKEYLLM_STATION_READERS`, default 4; `0`
  restores the single lane), each confined to its own thread; reads, the
  sweep's retrieval and the J.11 map projections ride them, while writes,
  ingest steps and admin repairs keep the writer lane. Readers take no
  lock — so a held writer lock (or a running batch, or another agent's
  plant) **stops writes, not reads**, and with warming off a read no
  longer opens the writer (`active` in the forest list describes the
  WRITER). `tune_derived` gained `busy_timeout=5000` because N readers
  are N occasional pheromone writers. After `reindex`/canopy build the
  handlers call `readers.reset(forest)` — a held-open view of a rebuilt
  index is not trusted.
- **The provider is not a lane (spec J.10.11, v0.57)**: the sweep
  `answer` runs prepare (reader lane) → model (no lane, `asyncio.to_thread`)
  → settle (SAME reader lane). The trace slice is CAPTURED at the end of
  prepare (`_deferred.events`) because the lane serves other calls while
  the model writes — `explain(..., events=)` must never read the live
  tracer for a deferred call. Concurrent model calls are admitted under
  `MONKEYLLM_STATION_MODEL_CONCURRENCY` (default 8, `0` unbounded) —
  parallel because the hold is gone, bounded because the provider is
  metered — and `/v1/health` publishes `concurrency: {readers, model}`
  (the team discovered every ceiling by experiment; P-03). The walk
  (`hops`) and `recurate` stay lane-bound by design. Both surfaces route
  through `execute_call`.
- **`look` never drops a field in silence (spec C.2, v0.57)**: the budget
  clips `outline` → `children` → `edges_in`/`edges_out` → `sample_rows`
  last (a dataset's digest exists to feed `query`), and every clipped
  field is named in `truncated_fields`. The flags are pre-sized inside
  the budget (C.6.2's pattern) — adding them after the shrink pushed the
  digest back over 500.
- **The sweep knows what time it is (spec C.6c.3, v0.57)**: harvest items
  carry `created`/`updated` (off the catalog row, never a file open);
  equal RRF scores order newer-first (tie-break, NEVER a boost); a
  `succeeds` edge inside the selected set annotates both ends
  (`supersedes`/`superseded_by`) — annotated, never suppressed. Dates and
  annotations enter the J.10.7 reading fingerprint. `ScopedVine.catalog`
  is a read-through property that exists for exactly this (not
  dispatchable from the wire).
- **`plant(dry_run=true)` rehearses (spec C.7.3, v0.57)**: same code path
  up to the first write — never a parallel validator — then
  `{valid: true, dry_run: true}` with `created` absent. Composes with
  `if_absent`; gated by `write` like the real call.
- **`origin` is one URI, never prose (spec A.3, v0.57)**: ≤2048 chars, no
  whitespace/control (J.8's `source_url` rule); mutable via graft
  (`None` clears it); in `look` when present, filterable in `scan`; the
  engine NEVER dereferences it. Catalog column added in place, filled by
  the next write or reindex.
- **The principal is stamped, never amended (spec J.4, v0.57)**:
  `Vine.commit_trailers` (backed by `GitRepo.trailers`) rides the
  original commit; dispatch sets/clears it around scoped writes and
  `stamp_principal`'s amend survives only as the no-seam fallback.
  Gardener/Ranger commits stay unstamped as before.
- **`export?recursive=true` zips a branch's in-scope subtree (spec
  J.14.1, v0.57)**: each member byte-identical to its single export,
  named `<id>.md`; out-of-scope members silently absent (scan's rule);
  a leaf with the flag and ANY unknown query parameter are `E_SCHEMA`.
  The Ranger's `run()` now ends with `git gc --auto` (H.8), reported as
  `gc:` in the report.
- **Token budgets** with always-explicit truncation (`truncated: true`):
  look 500, move 600, locate/scan/sniff 800. Never cut silently.
  `harvest`'s item cap is `MONKEYLLM_HARVEST_MAX_K` (default 5, garbage
  refused as `E_SCHEMA`, spec C.6c v0.34); its 4000-token budget is the
  outer wall regardless of cap, and the `answer` cache keys the sweep by
  the *effective* (capped) `k` (J.10.7).
- **`locate` is BM25-only by default** (Phase 0, zero embeddings). It becomes
  hybrid (RRF vector+BM25) only when a Canopy index AND an embedder are both
  present any other combination keeps the BM25-only contract intact.
- **locate/sniff contract split** (spec C.6b): `locate` searches curated
  metadata only; `sniff` searches bodies only (literal grep, no regex).
  Never mix the two.
- **A read embeds the query and nothing else (spec K.2 + K.6 + J.13.4,
  v0.42)**: lazy re-embedding used to run inside `locate`, so the question
  arriving after an ingest paid to embed every document of it unbounded
  work in the primitive with the tightest budget (F.6); one measured
  `locate` cost 2.67 s. The vector scan was never the problem (0.044 ms
  per dim-1024 dot product). Now: reads embed only the query, through the
  **K.6 memo** (`embed(model, text)` is pure → `_derived`, keyed by model
  + normalized text, LRU-bounded); node vectors are refreshed **only** by
  `build_canopy` or `POST /v1/admin/canopy {refresh: true}` (J.13.4, in
  Studio's Optimize tab). The debt is visible: `canopy_status` carries
  `stale`. A node not yet embedded is still found by BM25 the catalog
  upsert is synchronous so the cost is dense-half recall, never
  findability. A refresh against an absent/mismatched index REFUSES
  (K.4: a partial re-embed spans two spaces and fails silently).
- **The repair is on the console (spec J.13.3, v0.41)**: `POST
  /v1/admin/reindex` rebuilds one forest's catalog `admin` on that
  forest AND an unrestricted scope (the count IS the forest's size and
  every row rewritten includes nodes a branch-scoped principal may not
  read). It runs on the lane and the caller waits, like a canopy build;
  it is NOT a J.9 job (it plants nothing, commits nothing, has no report
  to stream). Writes `_derived/` only, so a **read-only Station serves
  it too** an index it could never repair would degrade forever. In
  Studio it lives in the ingest console's **Optimize** tab (renamed from
  "Refresh"): `sync` keeps the content current, `reindex` keeps what
  finds it current. Every tab value MUST be in `useRouteState`'s `allow`
  list `sync` never was, so clicking it wrote an address the validator
  rejected and the console snapped back to Upload (J.5.8).
- **The scan is memoized, never replaced (spec C.6b.1, v0.40)**: two
  thirds of a global `sniff` was the OS opening files, on every ask, and
  since J.10.7 v0.35 the sweep's retrieval runs even when the answer is
  served from the store. `_sniff_body` is a pure function of (body,
  folded term), so `_derived` keeps one row per (term, node) **including
  non-matches**, or the ~95% that never match are rescanned forever —
  valid while `nodes.body_hash` still matches. Hash, never `mtime`: a
  `reindex` or an edit reverted to its original text must invalidate
  nothing. Rows are per LINE (`[line_no, section, pos, line_text]`)
  because the scan emits one match per line centred on the *leftmost*
  term that hit it storing rendered snippets would make a two-term
  question disagree with itself. Ranking (`heat`, `score`, order) is
  NEVER memoized; it is recomputed per call. `content: cached|reference`
  bodies carry an empty hash and keep the direct scan: the `.md` the
  hash digests is not the text they scan. Dropping the memo may change
  latency and nothing else.
- `query` is read-only SQL over `type:dataset` nodes: reject every write
  (`;DROP`, `ATTACH`, multi-statement, `PRAGMA`) there is an injection suite.
- **A row cap is not a token cap (spec C.5.1, v0.47)**: `query` was the only
  read primitive with no budget, so `SELECT *` on a 141-column export
  measured **86,929 tokens for 15 rows** (429,397 for 200) into a walk
  that re-sends its history every turn. `BUDGET_QUERY` = 2000, below
  `pick`'s 4000 because a body is read once and a result is carried
  forward. Whole rows drop from the tail; **`columns` never does** it is
  the map back, so a result whose every row was refused still says *these
  are the columns your statement produces*. `limited` (the injected `LIMIT
  200` was reached) and `truncated` (the budget dropped rows) are
  independent, and the hint MUST lead with **the missing rows exist**: a
  live model read "truncated to 5 of 15" as "only 5 matched" and offered
  them as the answer. Sized by summing each row's own cost, never by
  `shrink_list_to_budget` 200 re-serialisations of a wide result is
  seconds.
- **Invalid is not forbidden (spec C.5.2, v0.47)**: every SQLite failure
  wore `E_QUERY_FORBIDDEN`, the code for attempting a write, so a mistyped
  table on a readable dataset was indistinguishable from a policy denial —
  in the console and in the audit. `E_QUERY_INVALID` (HTTP **400**) is what
  SQLite decides; `E_QUERY_FORBIDDEN` (**403**) stays what the guard
  decides. Both `query` and `tend`: one kept honest would make the code
  mean different things per primitive.
- **SQLite decides what a statement touches (spec C.5.3, v0.50)**: a
  grant's table allow-list is enforced by the **authorizer**, asked once
  per table and column the statement actually touches — so subquery, CTE,
  view and table-valued function are the same question. Reading table
  names out of SQL text is a second parser and two parsers agree only
  where somebody compared them; a text pre-read MAY stay for a friendlier
  message, NEVER as the control. It applies to `query` **and `tend`, with
  `SQLITE_READ` denied too**: writing is a way of reading, so a scope on
  the destination alone is not a scope. The refusal is
  `E_QUERY_FORBIDDEN`/403 (the grant decided it; SQLite only noticed) and
  never names the table it stopped at. Under a scope the schema is not
  readable either — the C.5 name hint is filtered by the allow-list, and
  `pragma_*` functions are refused beside the `PRAGMA` keyword they share
  no spelling with. The list travels keyword-only from `ScopedVine`,
  unreachable from the wire (same construction as G.2.5).
- `tend` (spec C.10) is the ONLY dataset write path: single INSERT/UPDATE/
  DELETE, WHERE mandatory on UPDATE/DELETE, no DDL; refreshes `payload_hash`
  and commits only the `.md` (it has its own injection suite too).
- **A `.db` is adopted, a `.csv` is converted (spec G.2.2, v0.44)**: a
  SQLite source becomes a `payload` conversion the converter reads
  structure + 3 rows per table and the Gardener **copies the file** into
  place as the payload, planting with no `schema` (C.7.1's "payload
  already exists" path). Never re-INSERT a `.db` row by row: unbounded in
  the source's size, lossy in its types, and the round trip's destination
  is what the source already was. Every dataset passport carries the
  **sample map** (G.2.3): `## Query manual` + `## Sample rows` every
  table, first 3 rows, cells clipped at 120 chars, ≤20 tables sampled and
  the omission stated. That map is the ONLY thing `sniff` can see inside a
  payload. `sync` rewrites those two sections and no others. Workbooks are
  one table per sheet (G.2.4) and **never trust `<dimension>`**: openpyxl
  in read-only mode believes it, and non-Excel exports declare `A1:A1`, so
  a real 130-row sheet arrives as one row and reads as "no data"
  (`ws.reset_dimensions()`).
- **A count limit guards invention, not data (spec G.2.5, v0.45)**: C.7.1's
  ≤10 tables / ≤50 columns stop a model inventing DDL; they were also
  refusing real 141-column ERP exports. `Vine.plant(node, adopted=True)`
  drops **only those two counts** names, types and `primary_key` are
  validated as always. Keyword-only and unreachable from the wire
  (`ScopedVine.plant(self, node)` forwards `node` alone), because a flag an
  agent can set is not a guard. A wide table's real cost is tokens, so the
  bound lives in the G.2.3 map instead: ≤12 sampled columns, omission
  stated, while the manual still names every column.
- **`## Notes` is the human half of the map (spec C.2.1, v0.46)**: the map
  says what is in a dataset, a person says what it *means* (which column is
  USD, what a status code stands for, which join answers the real
  question). `look` returns it as `notes` for `type: dataset` bounded to
  `BUDGET_NOTES` (200) inside look's 500 and flagged `truncated` when
  clipped because the agent's path is `look` → `query` and a note only
  `pick` can reach is a note nobody reads. Written through ONE `graft`
  (`append_section` first time, `replace_section` after); the Gardener
  never touches it (G.2.3 rule 4) and curation MUST NOT either. A console
  edits it from `pick`, NEVER from the digest saving a clipped copy
  deletes the tail. Datasets only: elsewhere the body is already reachable.
  **The notes travel with the dataset on EVERY path** (v0.47): any material
  a host assembles for a model carries the `notes` of every dataset in it,
  not just `look`. `harvest` does it because the sweep never looks; the
  walk's entry (J.10.5) does it because the entry is `locate` curated
  metadata, no body and on a dataset the natural next move is `query`,
  so a model that never looks never reads a word the operator wrote. The
  mode with more freedom was the mode with less information, and it read
  as the agent ignoring them. Unconditional: whether the section shares
  vocabulary with today's question is not a reason to withhold it. The walk calls primitives; the sweep is
  `locate` + `sniff` + matched sections and looks at nothing so notes
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
  model call), but the Gardener names its phase `convert`/`curate`/
  `plant` through `on_stage`, and the J.9 job carries it as `stage`. That
  is the only reason a one-file batch's progress bar can move; a raising
  observer is swallowed. A `sync` never reports `curate`: a refresh keeps
  the scent somebody already approved.
- **"Nothing to do" is not a rejection (spec J.8, v0.45)**: curation stats
  carry `skipped`, and the console's discriminator is **no fallback and no
  retry** a real rejection always leaves one behind. Reporting an
  all-`unchanged` batch as a model failure sends the operator to tune a
  model that was never asked anything.
- **Datasets are born via `plant` with a declarative `schema`** (spec C.7.1):
  the model never writes DDL Vine validates names/types, creates the `.db`,
  auto-generates `## Query manual`, and commits only the `.md`. No `ALTER`
  for agents; `tend` stays DML-only forever. Initial `rows` at birth are
  loaded parameterized (v0.9 rule 7) never as SQL text.
- **A pair key narrows, never adds (spec J.2.6, v0.48)**: `POST
  /v1/auth/pair` turns a password into a key carrying a capability mask
  (`{read, ingest}` default, that set is also the ceiling anything else
  is `E_SCHEMA`); effective authority is grants **∩ mask at the moment of
  use**, wherever the requesting principal's authority is read policy
  build, grants listing, admin/owner bits, REST **and** MCP. Self-service
  by construction (it reaches nothing the password could not); MUST
  expire (90 d default, 365 ceiling); `login`+`pair` are rate-limited
  with one 429 message that never reveals whether the user exists.
- **An image is never `unsupported` (spec G.5.1, v0.48)**: image/audio
  plant as `media` via the engine's built-in stub converter (typing rule:
  text → `note`, image/audio payload type → `media`, else `document`); a
  bound `vision` role (J.10) injects a describer through the Gardener's
  `extra_converters` seam (after operator command hooks, before entry
  points/built-ins); a describer that raises falls back to the stub.
  Media staged under `_derived/` (uploads) is archived into `_assets/`
  regardless of `archive:` staging is disposable, so there the payload
  is the only copy.
- **Payload bytes are a human surface (spec J.14, v0.48)**: `GET
  /v1/forests/{f}/payload/{node}` read cap, byte-identical
  `E_NOT_FOUND` for out-of-scope/absent/no-payload, resolved path
  contained in the forest root, remote URIs refused `E_SCHEMA`. Bytes
  never enter material the host assembles for a model; the G.5.1
  describer reads the image at ingest, and C.6d `view` is the one
  path a multimodal *client* fetches it deliberately.
- **A model sees the image it chose (spec C.6d, v0.48)**: `view(id)` is
  an **MCP-only** tool (REST refuses the name J.14's GET is REST's
  byte route, and a JSON twin would disclose server paths): image
  payloads only, ≤6 MiB (the describer's own cap one project-wide
  answer to "too big for a model"), local-only, contained, and
  byte-identical `E_NOT_FOUND` for absent/out-of-scope/payload-less.
  Engine method `Vine.view` returns path+identity, never bytes; the MCP
  layer reads the file into an image content block beside a JSON header
  that MUST NOT carry the path. Traced and audited like a read.
- **The reply has a stated size (spec J.10.8, v0.48)**: `answer` takes
  `reply_tokens` per call clamped [64, 4000], it replaces the
  binding's `max_tokens` on the model call AND is stated in the prompt
  (a hard cut alone truncates mid-sentence, invisibly). It enters the
  J.10.7 key **only when set**; absent and `0` both mean "the binding
  rules" and key exactly as before the upgrade. The console slider is
  a per-person localStorage preference (`monkeyllm.ask.prefs`), never
  in the address. The reasoning bump applies after the override.
- **The answer shows what it read (spec J.10.9, v0.48)**: prompts teach
  `![caption](media:<node id>)` whenever the material carries a `media`
  node ids from the material only. The host never fetches or
  rewrites; Studio's `Markdown media={{forest}}` resolves the scheme
  through J.14 with the *viewer's* credential, so an invented or
  out-of-scope id renders as its caption, never an error. Evidence of
  type `media` renders its image (PayloadImage, outside the row's own
  `<a>`); the `.md` export rewrites `media:` to the absolute payload
  route. And the reading fingerprint now hashes `notes` too a
  teaching edited is a reading changed.
- **A read says what it did not do (spec C.1.1 + C.6c, v0.52)**: `locate`
  searches curated metadata only, so a term living in a body returns `[]`
  byte-identical to a forest that never heard of it and a live agent read
  that as "the forest does not know" and answered from its own parameters,
  which is the one failure the product exists to prevent. An EMPTY `locate`
  (and an empty sweep) now carries `searched` + a `hint` naming `sniff`;
  computed only on the empty path, because a caller holding results was
  already told what it needed. Every result carries `body_tokens` and
  `include: ["outline"]` adds the section list both read off the catalog
  row the search already loaded, so neither opens a file. Under a policy
  `searched` counts only nodes in scope: a global count would make an empty
  entry search a size oracle for the region nobody granted.
- **Where the material sits in time (spec C.13, v0.52)**: `locate`, `sniff`,
  `scan` and `harvest` take optional `since`/`until`/`date_field`
  (`created` default, `updated` the other; **never** an "indexed" date
  `_derived/` is disposable and a `reindex` would silently move every such
  timestamp). Bounds accept `YYYY` / `YYYY-MM` / `YYYY-MM-DD` and expand to
  their own period; a bound it cannot read is `E_SCHEMA`, NEVER ignored a
  filter silently dropped is a lie about what was searched. The predicate is
  a **bare comparison on the indexed column** (`created >= ?`, upper bound
  exclusive at +1 day) `substr()` there computes the same answer and
  throws the index away and it is applied where CANDIDATES are chosen, so
  `k` is still met inside a window. Undated nodes are in no window and the
  count says so (`undated_excluded`). `calendar` (C.13.3) is the map that
  makes a window a choice instead of a guess: periods most recent first,
  empty ones omitted, **grouped in SQLite** (one row per period, never one
  per node), each bucket carrying the exact `since`/`until` the reads take.
  Under a policy the counts are filtered by the policy's own prefixes as
  SQL (`Policy.sql_scope`), because a global count here is a finer size
  oracle than `locate` could ever be. An empty windowed read says whether
  the WINDOW was the reason (`matched_window`) and names the nearest
  populated periods otherwise "nothing in that week" reads as "nothing
  anywhere", which is the failure the window was supposed to avoid.
- **A document is read back whole, in pages (spec C.4.1, v0.56)**: `pick`
  on an over-budget body answers the FIRST page (paragraph blocks,
  byte-exact substrings) + `next`/`returned`/`total` — never the old empty
  body. Pages concatenated in cursor order reproduce the body
  byte-identically (F.80); a single block wider than the whole budget
  arrives alone, cut, flagged `cut: true`, cursor still advancing.
  `section` accepts a list (≤10, one 4000 budget, `sections`/`missing`/
  `dropped`); `after`+`section` and `after`+id-list are E_SCHEMA. A bare
  string `section` and a within-budget body keep the old shapes TO THE
  BYTE.
- **An unknown graft patch key is refused, never absorbed (spec C.8,
  v0.56)**: `GraftPatch` is `extra="forbid"` and `Vine.graft` names the
  key + lists the operations. Before this, an unknown key beside a legal
  op answered 200 and silently did less than asked.
- **The metaphor stays in the prose (spec C.1/C.6, v0.56)**: every wire
  `kind` emits `note`/`branch` (`_wire_kind`); locate scope is `notes`
  (`bananas` accepted as deprecated alias for one minor version); a `kind`
  filter matches the emitted spelling. The catalog still stores 'banana'
  internally — translate at EMISSION, never leak it into a field value.
  Index-body headings (`## Direct bananas`) are forest format and stay.
- **`prune` is the write you can take back (spec C.14, v0.56)**: passport
  removed through git (history keeps it), parent index + coverage
  refreshed, catalog row deleted, local payload MOVED to
  `_derived/graveyard/<id>/`. `edges_in` refuse with `E_ANCHORED` (409)
  carrying `anchors`/`anchor_count` on the envelope (`VineError(data=)`);
  `force=true` strips backlinks in the same commit but REFUSES when an
  anchor is out of the caller's scope (count only, never names). A branch
  with children never prunes, `force` included; root and `_meta/` never.
  A pruned id is free to replant. Rides the `write` capability (J.2.6's
  mask ceiling is closed); `visible=` is keyword-only host-passed like
  scan's; emits `node.pruned` (J.16).
- **The document is a human surface (spec J.14.1/J.5.14/J.17, v0.56)**:
  `GET /v1/forests/{f}/export/{node}` is text/markdown, NO token budget
  (download, not context), inline content byte-identical to the planted
  file, J.14's discipline (read cap, byte-identical E_NOT_FOUND). The
  Studio `read` console renders via export — never `pick`. A share
  (`POST .../share {node, days}` → `/s/<token>`) is a key with one room:
  token stored HASHED, shown once, expiring (default 7 d, ceiling 90),
  authority re-read at EVERY serve against the issuer's current reach
  (a lapsed grant suspends it), every dead state one byte-identical 404.
- **The skill states its age (spec J.1.2 r6/J.5.12, v0.56)**: `forests()`
  (MCP and REST) carries `station: "<version>"`; the generated skill
  stamps the version and teaches the re-download check. The team once
  filed a feature request for a tool that existed — their skill predated
  it.
- **`sync` unions derived aliases, never removes (spec G.2.6, v0.56)**:
  the fast-path skips the CONVERSION, not the alias check, so an
  `aliases:` map added to a live forest reaches already-ingested files on
  the next sync. Hand-added aliases survive; cap overflow is counted in
  the report (`aliases_clipped`), never silent.
- **A batch is one call, so it has one budget (spec C.11, v0.52)**: `look`
  takes ≤10 ids, `pick` ≤5, sized by ONE budget (2000 / 4000) never the
  per-item budget times the count. Whole items drop from the tail and are
  NAMED in `dropped`; every id sent comes back in exactly one of `nodes` /
  `missing` / `dropped`; `missing` covers absent and out-of-scope alike
  (J.3 survives the new shape). A string in returns the old single shape to
  the byte; a one-element list still returns a list.
- **Every exit is an envelope (spec C.12, v0.52)**: one signature table in
  `src/monkeyllm/signatures.py` both surfaces read (a test compares it to
  the MCP tool schemas two descriptions of one contract agree only where
  somebody compared them). Argument shape is `E_SCHEMA` naming the
  parameter, what arrived and what was expected never a `TypeError`'s
  text; `null` is a MISSING argument, never the string `"None"` looked up;
  the last resort is `E_INTERNAL`/500 in the envelope shape, naming the
  primitive and the exception type and nothing else. And a missing
  parameter is not a denial: a route that wanted `?forest=` says so
  (`E_SCHEMA`), instead of telling an admin they lack `admin`.
- **A pointer never outranks what it points at (spec C.6b, v0.52)**:
  `sniff` scores `strength x density x (1 + alpha*heat)` with
  `density = 1 + 0.15*log2(match_count)` `match_count` as a tie-break
  alone left `heat` deciding every literal search. An `_index` node ranks
  below every content node in the same result set (it carries the summary
  of every child, so it matches almost anything and gathers heat by being
  the way through), demoted in the ORDER and never in the `score`. And
  derived terms keep any code-shaped token whatever its length (a digit,
  all caps, `-`/`_`/`.`/`/`) and order those first: the 4-char floor was
  dropping `RAG`, `MCP`, `421`, `p95` the tokens a technical corpus is
  searched BY while keeping the question's verb.
- **A write you can repeat (spec C.7.2, v0.52)**: `plant(node,
  if_absent=true)` answers `created: false` for an id already taken,
  writing nothing, committing nothing and comparing nothing (changing what
  is there is `graft`). Keyword-only in the engine, so `plant(node, True)`
  is still a `TypeError` that is the property G.2.5 relies on to keep
  `adopted` unreachable. Every `plant` result now carries `created`.
- **The dark surface says so (spec J.1.1, v0.52)**: the MCP mount's `421`
  wears the envelope (`E_HOST_NOT_ALLOWED`, naming the refused Host and
  `MONKEYLLM_STATION_ALLOWED_HOSTS`) the SDK still DECIDES, the host only
  rewrites the sentence; a Station serving MCP with no explicit allow-list
  warns at boot; `/v1/health` carries `mcp.host_allowed` for **this
  request's own Host**. The allow-list is never listed. A deployment behind
  a domain is dark until the domain is named, and every other signal stays
  green while it is.
- **The answer it should not give (spec J.10.10, v0.52)**: `answer(...,
  min_evidence=n)` counts the sweep's items that carry content BEFORE the
  store is consulted and before the provider is called; below the floor it
  returns `{answer: null, reason: "insufficient_evidence", harvest}`. Off
  by default (`0`), never in the J.10.7 key (it cannot change what the
  model would write, only whether it is asked) and a refusal is never
  billed and never stored.
- **A page capture is the page, not the window (spec J.15, v0.51)**:
  the Clipper's page screenshot scrolls the document to its end and
  composes the viewports into one image. It is read ONCE, at ingest, by
  the G.5.1 describer, and that prose is all `locate`/`sniff` ever see of
  it — so a viewport-bounded capture let a scroll bar decide how much of
  the page is findable. Four rules, each a way the obvious loop is wrong:
  **re-measure every step** (scrolling is what makes a lazy page grow, so
  its height before the first move is not its height); **hide fixed/sticky
  after the first slice** (they ride the scroll and get stamped down the
  whole image); **bound it** by slice count, end the walk when scrolling
  stops advancing, and take the composed height from what was CAPTURED
  (a page that outgrew the cap must not end in a blank band); **restore
  the scroll position**. `captureVisibleTab` is quota-limited to ~2/s, so
  the slices are spaced. The region picker stays a crop of the visible
  view — it is a rectangle somebody drew on what they were looking at.
- **A webhook body is an audit row with a destination (spec J.16,
  v0.53)**: Part J was pull-only, so nothing could tell an operator's other
  tools that anything happened. The outbound half is shaped by one fact — a
  delivery **leaves the Station's authority behind**: whoever holds the URL
  reads it, under no scope, and a grant revoked later reaches none of it. So
  the payload carries identity (ids, types, counts, states, job ids,
  commits, error codes) and **never** a body, a snippet, a question, a
  reply, SQL, a dataset row or `## Notes`. The one opt-in
  (`include_metadata`) adds `title` + `summary` only, defaults off, and
  **adds only what the act already knew** — `plant` was handed a title,
  `graft` was not, and no event may cause a read. A **scope is a ceiling**:
  forest webhooks (that forest's `admin`) can never subscribe to a
  deployment event, and deployment webhooks need J.10.2's reach (owner, or
  admin of every forest). Authority is re-read at **delivery**, so a lapsed
  grant **suspends** rather than keeps firing — deleting would be the same
  fact delivered as silence. Emission is O(1) when nobody subscribes (the
  subscription index is in memory; a registry read per primitive would tax
  the hot path to answer "no") and never runs on a forest lane: the
  primitive returns before a socket opens. One body across every attempt so
  a receiver dedupes by `id`; HMAC-SHA256 over `<timestamp>.<body>` (the
  timestamp is INSIDE, or a captured body replays forever); destination
  validated exactly as a provider's (J.10.2, resolved not read); headers
  write-only (`null` = keep, which is the only way an editor that cannot
  READ a value can leave it alone); audited by id and destination **host**,
  never the path — a Slack or n8n URL is a secret in its tail. Console in
  **Build**, so the group reads as what comes in / who reads it / what goes
  out; it previews the exact JSON before the event is subscribed to.
- **The Clipper is a client (spec J.15, v0.48)** `apps/clipper/`, MV3:
  stores origin + paired key only (never the password); prose through
  `compose`, binaries through `upload`; `E_LOCKED` queues client-side;
  injects on user action only (`activeTab`). Distributed by the Station
  at `GET /clipper.zip` ONE shared build, unauthenticated like the
  shell, offered on the Studio rail to every signed-in person (never
  admin-gated: pairing is self-service, so distribution is too);
  `MONKEYLLM_STATION_CLIPPER_DIR` overrides the staged build.
- **The door names its surfaces, and the first minute is chrome (spec
  J.5.1 + J.5.11 + J.5.12, v0.49)**: the integration manual's menu entry
  reads **MCP / API / Integrations** (`MCP`/`API` travel untranslated);
  the first-access presentation shows at most once per browser (flag in
  browser storage only spends no model call, writes nothing
  server-side, never precedes identity); the **Skills** console is
  self-service (`read`-gated, NEVER admin-gated) and generates the
  Claude Code skill client-side with the Station origin + open forest id
  baked in the Station gains no endpoint, the skill teaches only the
  published MCP surface under a paired key, and its body stays English
  (it addresses a model; the walkthrough around it is translated).
  Companion handbook: `docs/guide/{en,pt,es}` screenshots shared in
  `docs/guide/assets/`.
- **A provider serves every forest, so it answers to every forest (spec
  J.3.2 + J.10.2, v0.50)**: the providers table has no forest column —
  the endpoint decides where every forest's material goes and the key pays
  for every forest's calls. **Listing** stays open to any admin (a
  per-forest binding points at those names; `has_key` is a bool, never the
  key); **editing or testing** requires administering *every* forest.
  Stated as reach, not as the owner bit, so J.2.1 break-glass keeps
  provider repair and a single-forest deployment is unaffected — and a
  second forest narrows that authority the moment it exists, with nobody
  revoking anything. Custody: a stored key does NOT follow a changed
  endpoint (blank-key re-save still works while the address is unchanged)
  and is never sent to a caller-supplied destination. A connection test
  resolves the host and judges **every** address it maps to — text
  inspection decides on what a URL says, not where it goes — refusing
  non-public ones unless `MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE=1`,
  which local llama.cpp/Ollama deployments need (`docs/local-inference.md`).
- **Governance leaves a trail (spec J.4.1, v0.50)**: Part D audited reads
  and writes; the mutations deciding *who may do either* are audited too —
  grant/revoke, key issue/revoke, password, provider, model binding,
  forest creation, login (**both outcomes** — the J.2.6 limiter counts in
  memory and forgets on restart), pair, setup. Never the secret: a key by
  its non-secret prefix, a password only by the fact one was set. A
  governance row carries the no-forest placeholder `"-"` and **only the
  owner reads those** (J.3.2's rule, applied to governance); a row that IS
  about one forest carries its id so that forest's admin reads it back. An
  audit write must never fail the act it describes.
- **The page declares what it may load (spec J.5.13, v0.50)**: the console
  renders model output and ingested bodies as markdown, both untrusted by
  the product's premise — and whatever such text talks the page into
  fetching is fetched by the *reader's* browser, which the Station never
  sees, so no host-side check can be the control. Every response carries
  CSP (`img-src` same-origin + `data:` + `blob:`, `connect-src 'self'`,
  `frame-ancestors 'none'`, `object-src`/`base-uri 'none'`), `nosniff`,
  `no-referrer`, `X-Frame-Options: DENY`. Nothing legitimate is lost:
  J.14 images arrive by credentialed fetch and render as `blob:`. Inline
  script is allowed **by hash computed from the built shell** — a digest
  written by hand goes stale on the next edit and fails silently (the page
  loads, the theme script just stops). `style-src` keeps `'unsafe-inline'`
  (style attributes + mermaid); script never does, and never
  `'unsafe-eval'`. The renderer dropping unresolved image sources is the
  second layer, not the control.
- **A sidecar carries payloads, decided when unpacking (spec J.13.2,
  v0.50)**: `restore` validates every member **before** extracting and
  refuses the archive rather than skipping a member; members are named
  positively (the payload files) instead of filtered against known-bad
  shapes, because the destination is a working git repo whose contents git
  itself later reads, and discarding relative segments is not sufficient
  there. Explicit uncompressed ceiling, and
  `MONKEYLLM_STATION_IMPORT_MAX_MB` now **defaults to 1024** (`0` still
  means unlimited, decided rather than inherited).
- **Starting a Station mints nothing (spec J.2.5, v0.28)**: the registry is
  as authoritative after boot as before it, so J.2.4's setup window survives
  to be used. The first-run banner names the open door (setup URL / env
  username never the env password) and says nothing on later restarts.
  `--bootstrap-key` (or `MONKEYLLM_STATION_BOOTSTRAP_KEY=1`) is the opt-in
  for a browserless deployment: mints **into that same window only**, with
  the owner bit, and thereby closes it. Never grant a first credential per
  forest an empty volume has none, which is the v0.25 deadlock.
- **Latency is reported by the host, never by the client (spec J.10.6,
  v0.29)**: every primitive response carries `Server-Timing: vine, host[,
  model][, cache]` a **header**, because the body is the agent's context
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
  never a primitive** warming through `locate` would forge the heat the
  Ranger reads as evidence. A Station opens and warms every forest at boot
  (`--no-warm` / `MONKEYLLM_STATION_WARM=0` for registries too big to hold
  open), best effort: one locked forest never stops the others.
- **`app.state.pool` is only touchable through `app.state.forest_lane(id)`**
  (spec J.9, v0.32): one worker thread lane per forest; a SQLite
  connection belongs to its opening thread, and since boot warming the pool
  is rarely empty. Never touch a vine from another forest's lane, and never
  from the event loop.
- **Batch ingest is a job (spec J.9 + G.10, v0.32)**: `adopt`/`sync`/
  `upload` validate synchronously and answer **202 + job** (`wait: true`
  blocks; the MCP `ingest` tool waits by default); `compose` stays in
  place. One batch per forest at a time the E_LOCKED refusal names the
  running job. The Gardener steps one document per `next()`
  (`adopt_iter`/`sync_iter`), records `source_root` BEFORE the first step
  (that is what makes cancel/crash recoverable by `sync`), and same-forest
  reads interleave between steps. Job records live in host memory only:
  `GET .../jobs[/{id}]` must never touch a forest (no lane, no trace, no
  pheromone), a restart forgets records but never work, and Studio carries
  the running job in the address as `?job=`. Entering the ingest console
  without `?job=` rediscovers a running job from the job list and puts it
  back in the address (J.9.1, v0.36); next batches may wait in a FIFO in
  tab memory (J.9.2) visible, never in the address, dead with the tab,
  fired one per settle, held on cancel or non-`E_LOCKED` refusal. The
  host itself still never queues. A pill on every console announces the
  running batch and the queue (J.9.3, v0.37): it reads the job board only
  never a browser-storage copy through ONE watcher per forest whose
  cadence follows the attention (~1 min collapsed, ~2 s expanded or with
  the ingest console open), and it yields on the ingest console itself.
- **Two hashes: the question finds the entry, the reading decides the
  model (spec J.10.7, v0.35 T11)**: the host caches `answer` and nothing
  else, per forest, in `_derived/cache/`. The sweep's retrieval runs on
  EVERY ask (it is the cheap half); its key normalised question,
  effective terms, effective `k`, hybrid, binding, scope, **no HEAD** —
  finds the entry, and the **reading fingerprint** (material as a set
  keyed by id: type/title/summary/matches/content + truncated; never
  score, heat or order) decides: equal → serve the stored reply with fresh
  retrieval fields; different → the model runs and the entry is replaced.
  The walk keeps HEAD in its key and is served whole (it cannot be
  re-walked without paying per hop). The **whisper closes every hosted
  answer** heat on the evidence via `Trails.add_heat`, hit and miss
  alike. Empty-evidence, errored, truncated or writing runs never enter;
  an entry never crosses scopes; a hit says `cached: true`, carries
  `Server-Timing: cache` with no `model`, audits with the entry digest,
  and never re-bills the recorded cost. `cache: false` skips the serve
  and replaces. C.6c.2: index nodes are never match-refined sniff
  resolves an index id to its subtree, which mislabelled children's
  snippets and destabilised the reading.
- **The address is where the console is (spec J.5.8, v0.30)**:
  `/f/{forest}/{console}` with the selection in the query (`node`, `mode`,
  `dataset`, `table`, `tab`). Studio keeps **no second copy** of it `App`
  reads `router.js`, never `useState` because the address bar is the copy
  the operator can see. Moving pushes, adjusting replaces, rendering never
  writes. A forest the key has no grant on is **said, not swapped**: the
  console that silently opens a different forest is how somebody comes to
  believe they are reading one they are not. The address restores a page,
  never a call no reload may spend a model call or a commit. On the host,
  a GET that matches no route and no file is answered with the shell **only
  when it accepts HTML**: a missing asset must stay a 404, or the browser
  gets an HTML body under a JavaScript MIME type.
- **The Data console makes, imports and leaves (spec J.5.10, v0.44)**: a
  dataset is born through ONE `plant` with a declarative schema (no DDL in
  the console, ever); a file is imported through the J.8 `upload` ingest
  (never parsed in the browser, never planted beside the Gardener) and the
  answer is a J.9 job; a selected dataset collapses the picker to itself
  and offers an explicit way back that clears `?dataset`/`?table` and
  refuses while a `tend` draft is staged. SQL is coloured where it is
  typed: a highlighted mirror under a transparent `<textarea>`, mirror
  `aria-hidden` so the characters are not read twice.
- **The console shapes the forest through `plant` (spec J.5.7, v0.27)**:
  branch creation in Studio composes ONE `plant` call the id lives under
  the chosen parent, the parent-index entry and the commit are the engine's.
  Ids are never typed (they are immutable) and there is no move/rename/
  delete: no primitive relocates a node, so misplacement is permanent.
- **Ingest sources are contained (spec G.3/G.8/J.8.2, v0.26)**: an absent
  source is `E_SCHEMA`, never the working directory; a source may not be,
  contain or sit inside the forest (only `_derived/` is exempt, for upload
  staging); a directory carrying `_index.md` is pruned from every walk; a
  targeted `sync` path is contained **after** resolution. On the host,
  `MONKEYLLM_INGEST_ROOTS` is an allow-list that is **empty by default and
  empty means none** `admin` says who may ask, the roots say what exists
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
  BONE (raw binaries) stays at the source `archive: never` is the
  default. Curation always sees the FULL text (G.7.4). Events trigger,
  the hash-diff reconciler decides (`sync --path` + mtime/size fast-path).
- **Remote payloads (G.9)**: `payload` may be a URI (`file://`, `s3://` via
  optional boto3; `MONKEYLLM_S3_ENDPOINT` for MinIO/R2). Reads fetch into
  the hash-validated `_derived/payloads/` cache (Ranger evicts LRU, H.6);
  `tend` REJECTS remote payloads (datasets are local-first). `vine
  prefetch <branch>` warms a region after the locate drop. `vine snapshot
  create|restore` = git bundle with full history (Part I); the map itself
  always stays local to the Vine remote clients come through MCP.
- `plant`/`graft` are atomic and `git commit` **inside the forest**
  (spec C.7/C.8). That is product behavior and it is correct.
- **Binaries never enter the forest git** (spec A.3.1): gitops only versions
  `.md`; payloads (`*.db`, `_assets/`) stay on the filesystem, referenced by
  `payload` + `payload_hash`.
- **NEVER commit to the project's outer repo** the user commits by hand.
  (Forests under `forests/` have their own embedded git; that is different.)
- The frontmatter parser rejects early: better to refuse garbage than accept it.
