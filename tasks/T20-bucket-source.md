status: done (2026-09-17: spec v0.84 CUT and IMPLEMENTED — G.3.1 bucket
source (the bucket is the BONE: `payload` and `origin` are the object's own
URI, containment is "a configured store serves it"), G.3.2 auto-bucketing,
G.4.7 `curate: false` + J.13.6.1 `order`/`limit`, G.10.2 batched planting,
A.5 `INDEX_ENTRIES_MAX`, J.8.6 the bucket card, J.20 the inbound trigger,
J.13.4 canopy-as-job. F.229-F.238 green in tests/test_v084_{bucket,
station_bucket}.py + apps/studio/check-bucket.mjs. Measured here, on a
stubbed store with 2,000 objects and `curate=False`: adopt in **22.7 s**,
**101 plant commits** (G.10.2's batches of 20, not 2,000 ceremonies),
largest `_index.md` **55,276 bytes** under the A.5 wall, 0 errors, curation
reported `disabled` rather than failed. The live bucket end of it —
`adopt s3://` over a real MinIO prefix, then one changed object refreshed
by the ETag fast-path — is in tests/test_v084_live_s3.py. OPEN, by name:
the bucket card does not count the objects before Start, so the estimate an
operator reads is the one they typed. Uncommitted — Jimmy commits by
hand.)

# T20 A forest from a bucket

## Goal

Somebody with ten thousand documents already in object storage must be able
to point a forest at them and walk away — one call, one job, a map they can
search the same afternoon, and zero bytes of anybody's original copied
anywhere.

Today they cannot. `Gardener._resolve_source` resolves a source with
`Path(raw).resolve()` and refuses anything that is not `is_dir()`, so the
only route into a forest is a local directory. The workaround is to mount
the bucket (s3fs, rclone) and adopt the mount, and it is wrong in the one
place this product is least allowed to be wrong: G.2.7 makes the Gardener
fill `origin` with the source file's own URI, so ten thousand passports
record `file:///mnt/dump/…` — the address of a mount table on one machine,
not of the object every one of those nodes came from. The map outlives the
deployment; provenance that resolves only inside one container does not.

## Why now: the four walls at 10,000

The mount is the visible problem. Behind it are four that nobody has
measured, because nobody has run this corpus size through the pipeline.

| # | Wall | Where it is | What it costs at 10,000 |
|---|---|---|---|
| 1 | One commit per document | `gardener.py` ~1521 `self.vine.plant(draft, adopted=True)`, once per `_ingest_file` | 10,000 git ceremonies; C.7.4 measured the same cost at 100 in v0.58 and gave `plant` a list form the Gardener never used |
| 2 | Curation is all-or-nothing and inside the batch | `run_ingest` builds the Curator and appends it as an `on_curate` hook; the CLI's `--curate` is the only opt-out anywhere | the first search waits behind 10,000 model calls nobody has decided to pay for |
| 3 | Nothing caps an index body | `indexer.py` `add_entry` appends and never counts; `count_coverage` counts the rendered lines | a flat prefix mirrors into ONE `_index.md` of ~800k tokens: 10,000 entries, each an id plus a child summary at A.4's 60-token ceiling |
| 4 | The canopy build holds the request | `admin_canopy` runs `vine.build_canopy()` on the forest thread and the caller waits | 10,000 embeddings inside one HTTP request — J.9's founding argument, arriving at a different console |

Wall 3 has a second half: even with an index cap, a flat prefix of 10,000
keys mirrors into one branch with 10,000 children. A.5 flags `needs_split`
at 150 entries, which is advice to a Ranger that has never split anything.

## Decisions taken (2026-09-17)

| # | Decision | Cost accepted |
|---|---|---|
| 1 | **A bucket is a SOURCE, served only through a configured object store (J.19)** — having a store is the containment rule for a remote source, the counterpart of `MONKEYLLM_INGEST_ROOTS` for directories | The ingest roots list and the store list are two mechanisms answering one question; neither can express the other's subject, and both have to be checked |
| 2 | **The bucket is the BONE.** `payload` and `origin` are the object's URI; `archive: never` (already the default) means nothing is copied | `tend` refuses a remote payload (G.9 rule 4), so a dataset adopted from a bucket is queryable and not writable |
| 3 | **ETag + size is the freshness fast-path; `source_hash` stays sha256 on the bytes** | A multipart ETag changes on a byte-identical re-upload, so that object is downloaded for nothing once — never reported as changed |
| 4 | **Plant in batches of 20 (C.7.4), step stays one document** | A crash or cancel loses up to 19 documents' conversions — model calls included — which `sync` redoes by `source_hash` |
| 5 | **`curate: false` is a per-batch decision on the wire**, with the reason in the report; the deferred pass is J.13.6.1 with `order` and `limit` | Nothing marks a node as awaiting curation; an operator running a bounded pass twice pays twice, and the report's `remaining` is the only cursor |
| 6 | **`order: "heat"` reads the persistent pheromone**, so a big forest curates what agents actually read first | The pass is now steered by traffic, which means a forest nobody has read yet curates in `created` order and that is the default |
| 7 | **`cached` is the default content policy for a remote source; `reference` degrades into it** | A `.forest` of such a forest carries the map and not the bodies — small, and not self-contained |
| 8 | **The index cap is on the rendering, never on the truth** — `coverage`, `stats.degree`, `scan` keep counting every child | `count_coverage(body)` has to stop being the source of the `coverage:` frontmatter, or the wall lies about itself |
| 9 | **Auto-bucketing picks the first of three rules that fits and RECORDS it** | The recorded rule wins forever, including when the set grows past the point where another rule would now be chosen — because no primitive relocates a node |
| 10 | **The inbound trigger answers to a subscription's secret and to nothing else**; audited as `notify:<id>`, never as a person | A permanent standing authority held by whoever has the secret — which is why the set of things it can cause is one sentence long |
| 11 | **The host queues a machine's keys and still never queues a person's batch** | Visible, bounded, coalesced, dead on restart; the healer is the periodic full `sync` G.8 already requires |
| 12 | **Curation MAY move off the lane (J.10.11's shape), but the batch still lands in source order** | A host that cannot guarantee ordering must not do it, so the optimisation is a MAY and the serial path stays the reference implementation |

## Context

- Spec draft for v0.84 exists as an edit script against
  `docs/monkeyllm-spec-v0.83.md`; it touches A.5, C.2, G.3 (+ new G.3.1,
  G.3.2), G.4 (+ new G.4.7), G.6, G.7, G.8, G.10 (+ new G.10.2), J.8 (+ new
  J.8.6), J.9, J.13.4, J.13.6.1, and adds **J.20**. Acceptance **F.229 -
  F.238**.
- **J.19 (object stores) is not this task's.** It is a parallel v0.84 draft:
  a registry of named stores mirroring providers — endpoint, bucket, prefix,
  credentials — plus an implicit `env` store from `MONKEYLLM_S3_BUCKET`.
  This task consumes it and defines none of it. What it needs from J.19 is a
  bucket-to-store lookup that is total, or a documented tie-break.
- `src/monkeyllm/fetch.py` already has the S3 half of what is needed:
  `_s3_client()` (boto3 optional extra, `MONKEYLLM_S3_ENDPOINT` for
  MinIO/R2), `_fetch_s3`, `upload`, and the hash-validated `PayloadCache`
  the G.9 remote-payload path uses. Listing is what is missing.
- `Vine.plant` already takes a list (C.7.4, `MAX_BATCH_PLANT = 20`) and
  `_plant_batch` refuses datasets in a batch. It does **not** forward
  `adopted=` — which is correct and worth not "fixing": that flag only
  relaxes C.7.1's table/column counts, which only a `schema` can trip, and a
  batch never carries one.
- `Trails.heat_all()` already reads the whole persistent scope in one
  statement (added for the J.11 projections) — that is `order: "heat"`'s
  input, and nothing new is needed in `trails.py`.
- `Gardener.scent_scope()` currently orders by `id`, which is alphabetical,
  which is nothing. `order` replaces it; `created` becomes the default.

## Steps

1. **Cut `docs/monkeyllm-spec-v0.84.md`** from the three v0.84 drafts.
   **Check the file does not exist first** — v0.74's round destroyed a
   parallel session's uncommitted spec with `DST.write_text()` and was
   caught only because APFS keeps birthtime. Verify the cut by `diff`
   against v0.83, not by re-running anchor asserts: the peer's `diff` is
   what catches a missing edit, and re-asserting only proves the anchors
   somebody thought to name.
2. **`src/monkeyllm/sources.py` (new).** The one abstraction this whole
   round rests on: a source is *list → fetch one → its identity*, and
   nothing else in the Gardener should know which kind it has.
   - `LocalSource(root)` wrapping today's `_walk`/`stat`/`read_bytes`
     exactly, so the directory path is refactored and not rewritten.
   - `ObjectSource(store, bucket, prefix)` — paginated `list_objects_v2`
     eagerly at construction (G.10 needs `total` before the first step),
     `Delimiter` unused (the mirror wants the whole key tree), directory
     markers and G.6 `ignore` globs applied to the relative key, a
     sub-prefix carrying `_index.md` pruned whole (G.3 rule 3), `fetch(key)
     → Path` into `_derived/staging/`.
   - `resolve_source(raw, forest, stores)` replacing `Gardener._resolve_source`:
     same `E_SCHEMA` for an absent source, same containment for a directory,
     `E_FORBIDDEN` for a bucket no store serves or a prefix a store does not
     contain, **before any network call**.
3. **`src/monkeyllm/gardener.py` — the source seam.** `adopt_iter` /
   `sync_iter` / `_ingest_file` / `_sync_one` / `_settle_unchanged` /
   `_passports` take their entries from the source object rather than from
   `Path`: `source_path` = relative key, `source_size` + **`source_etag`**
   (new passport field; `source_mtime` stays for local), `origin` =
   `_origin_for` returning the object URI, `_install_payload` referencing
   the URI instead of copying for a remote source, `_apply_content_policy`
   defaulting to `cached` and degrading `reference` (the staged-upload
   branch already there is the model). Remove the staged copy as each
   document lands — and, unlike J.8.3's courier, remove it on failure too.
4. **`src/monkeyllm/gardener.py` — batched planting (G.10.2).** An open
   batch of up to `MAX_BATCH_PLANT` drafts; flushed when full, at the end
   of the run, and by any document that cannot join it (datasets). Branches
   join their children's batch. The step's `action` is decided at the step
   from the draft's own C.7.3 rehearsal, so a draft that would fail is an
   `error` at its own step and not at the flush; the step record gains
   `committed`.
5. **`src/monkeyllm/indexer.py` + `src/monkeyllm/vine.py` — the wall.**
   `INDEX_ENTRIES_MAX` (500) in `indexer.py`; `add_entry` keeps the section
   at the cap and maintains one overflow line naming `scan(parent_id,
   after="")`; `count_coverage` stops being the source of the `coverage:`
   frontmatter — `render_index` takes the true child counts from the
   catalog. Audit every caller of `count_coverage`/`parse_coverage` before
   changing it: C.1 and C.2 both read that string.
6. **`src/monkeyllm/gardener.py` — auto-bucketing (G.3.2).**
   `MONKEYLLM_ADOPT_BUCKET_ABOVE` (200, `0` disables); the three rules in
   order (name's leading segment → `created` year-month → first character of
   the slug); the chosen rule written into `gardener.yaml` under
   `bucketing: {<source-relative dir>: {rule, above}}` and read back by
   `sync` before any placement decision.
7. **`src/monkeyllm/gardener.py` — deferred curation (G.4.7).**
   `Gardener(..., curate=...)` is not the seam — the Curator is a hook the
   host builds — so what changes here is the report: a curation block
   carrying the reason (`disabled` / `unbound` / the existing failure
   states) and whether a model is bound, and `rollup(curator=None)` running
   on a `curate: false` batch so branch summaries are
   `derive_branch_summary`'s rather than the template sentence.
8. **`src/monkeyllm/gardener.py` — the ordered scent pass (J.13.6.1 r8-9).**
   `recurate_scent_iter(order="created", limit=None)`; `scent_scope` orders
   by `created` (oldest first) or by `Trails.heat_all()` (hottest first,
   no-heat last, ties on `created`), deterministic both ways; `remaining` on
   the report.
9. **`src/monkeyllm/cli.py` + `src/monkeyllm/signatures.py`.** `vine adopt
   s3://…`, `vine sync --path <key>`, `--no-curate` on both (mutually
   exclusive with the existing `--curate`); the `ingest` signature entry
   gains `source` and `curate`, and the MCP tool description in
   `mcp_surface.py` names the bucket door and what it needs (J.1.2 rule 7:
   a description names the neighbour that does what it refuses).
10. **Measurement, before the Station work and again after.**
    `scripts/bench_ingest.py`: generate a synthetic source of 10,000 small
    markdown documents (a flat variant and a nested one), then measure —
    (a) v0.83 adopt, per-document commits, curation off: wall time, commits,
    peak `_index.md` size in tokens; (b) the same with batching; (c) the
    same with `curate: false` against a bound model, versus `curate: true`
    on a 200-document slice extrapolated (10,000 model calls is not a
    measurement anybody should pay for); (d) `sync` over the unchanged
    source, counting `GetObject` calls against a local MinIO or a stubbed
    client. Record the numbers in this file. Decisions 4 and 12's value is a
    claim until then, and the round's own spec says so.
11. **Station: ingest (`apps/station/monkeyllm_station/app.py`).**
    `run_ingest` accepts `source` beside `path` (both `admin`, two different
    reasons — see J.8's amendment), routes an `s3://` through J.19's store
    lookup, and threads `curate`. `_finish_ingest` reports
    `unsupported_formats` and the curation reason.
    `apps/station/monkeyllm_station/jobs.py`: `committed` on the record.
12. **Station: the canopy job.** `admin_canopy` POST answers 202 with a J.9
    job claiming the forest's one batch lock (shared with ingest and
    recurate — same reason `recurate_scent` shares it), progress per node,
    cancel, and an index installed atomically at the close so a cancel
    changes nothing. GET stays synchronous and lock-free.
13. **Station: the inbound trigger (J.20).** A `notify_subscriptions` table
    in `registry.py` (id, forest, hashed secret, created, last used); the
    route `POST /v1/forests/{f}/ingest/notify`; HMAC verification sharing
    **one** helper with J.16's outbound signer (two implementations of one
    signing rule drift, and only one of them is the one an integrator
    implemented); the byte-identical refusal for every failure; the held,
    coalesced, bounded key set on the job board; the `notify:<id>` audit
    row carrying the count and no key.
14. **Studio: `apps/studio/src/views/Ingest.jsx`** — the **Connect a
    bucket** card (store from the host's listing, prefix, dest, curate
    now/later with the call count beside it, content policy with the
    snapshot consequence beside it), the `unsupported_formats` summary above
    the path list, strings in `apps/studio/src/locales/ingest/{en,pt,es}.json`
    (J.5.3), and the new tab value added to `useRouteState`'s `allow` list in
    `apps/studio/src/router.js` — the v0.41 bug where a tab value outside
    `allow` wrote an address the validator rejected and snapped the console
    back to Upload.
    `apps/studio/check-bucket.mjs` asserts statically that the card carries
    no store list, no endpoint field and no format list of its own (F.218's
    rule, F.137's boundary), run from `tests/test_v084_bucket_console.py`.
15. **Studio: the Optimize tab** gains nothing new — the canopy card is
    already there and becomes a job card, and the scent card gains `order`
    and `limit` with the bill beside them.
16. **`docs/local-inference.md` / `docs/guide`**: one page on connecting a
    bucket, in the guide's three locales, sharing `docs/guide/assets/`.

## Acceptance criteria

- [ ] F.229 A bucket becomes a forest: passports carry the key as
      `source_path` and the object URI as `origin`, bodies are `cached` and
      out of git, an adopted image and `.db` reference the object, staging
      is empty at the close, `gardener.yaml` records the URI, `reference`
      degrades and says so, `query` works through the G.9 cache and `tend`
      refuses. **Negative control:** the same tree from a local directory is
      byte-identical but for `origin`'s scheme and the absent
      `source_etag`; every v0.83 directory-adopt test passes unmodified.
- [ ] F.230 A bucket no store serves is refused `E_FORBIDDEN` with zero
      calls made to the store, naming the stores and no credential; an
      escaping prefix and an escaping key are refused; a sub-prefix with an
      `_index.md` is pruned whole; a store error is an `error`, never
      `stale`.
- [ ] F.231 A `sync` over an unchanged prefix issues zero `GetObject`
      calls; a byte-identical re-upload under a new multipart ETag is
      fetched once, hashes equal, reports `unchanged` and commits nothing;
      changed bytes are re-converted and committed; a targeted key sync
      reconciles that key alone and refuses `..` and absolute keys.
- [ ] F.232 200 documents adopt in ~`n/20` commits with `.md` files
      byte-identical to the per-document run; `committed` is monotonic and
      never exceeds `done`; a cancel leaves no partial batch and `sync`
      finishes without planting anything twice; a dataset flushes the batch
      and plants alone. **Negative control:** ≤20 documents is one commit.
- [ ] F.233 `curate: false` on a forest **with** a binding calls the model
      zero times, writes derived summaries, reports `disabled` while still
      reporting the binding, and still writes deterministic branch
      summaries; the nodes are revisitable by `derive: ["scent"]`.
      **Negative control:** `curate: true` is byte-identical to v0.83;
      with no binding the reason is `unbound`.
- [ ] F.234 `limit: n` bills `n` and reports `remaining`; `order: "heat"`
      is hottest-first, no-heat-last, deterministic across runs and
      unaffected by session heat; `order: "created"` is oldest-first.
      **Negative control:** neither parameter reproduces v0.75's pass field
      for field.
- [ ] F.235 A branch over `INDEX_ENTRIES_MAX` renders the cap plus one
      overflow line naming `scan`, while `coverage:`, `look`, `coverage()`
      and `scan(after="")` all still account for every child. **Negative
      control:** a branch under the cap renders byte-identical to v0.83.
- [ ] F.236 A wide prefix buckets by the first fitting rule, records it, and
      places a later file by the **recorded** rule; a set no rule can split
      adopts anyway under the last one. **Negative control:** a directory
      under the ceiling adopts flat, and `MONKEYLLM_ADOPT_BUCKET_ABOVE=0`
      adopts every source flat.
- [ ] F.237 A signed notification schedules exactly its keys; absent, wrong,
      stale, unknown and removed all answer one **byte-identical** refusal;
      an escaping key refuses the whole request naming the count and the
      first key; a notification during a batch is held, coalesced and
      bounded while an operator's POST is still `E_LOCKED`; the audit row is
      `notify:<id>` with a count and no key and no person.
- [ ] F.238 Build and refresh answer 202 with a job, share the forest's
      batch lock in both directions, and a cancelled build leaves
      `canopy_status` byte-identical to before it started. **Negative
      control:** `GET /v1/admin/canopy` unchanged and lock-free; F.42
      passes unmodified.
- [ ] Measurement recorded in this file: wall time, commit count and peak
      index size for 10,000 documents, before and after, with and without
      curation.

## Out of scope

- **Defining J.19.** Object stores — the registry, the credentials custody,
  the `env` store, the console — are a parallel v0.84 draft. This task
  consumes the lookup and adds nothing to it.
- **Any store but S3-compatible.** Azure Blob, GCS and Drive are the same
  shape and a different SDK; Part L is where they belong (a `converters` or
  a new seam), and adding a second scheme here before the first one has run
  at 10,000 objects would be guessing twice.
- **Continuous watching.** G.3 still says v1 sync is on-demand and
  deterministic. J.20 is a trigger, not a watcher: nothing polls, nothing
  subscribes to the store on our side.
- **Writing to a bucket.** `tend` refuses remote payloads (G.9 rule 4) and
  that stays. A forest never writes to the store it reads.
- **Pruning what the bucket deleted.** A deleted object is reported `stale`
  and the Gardener still never deletes a node (G.3). Turning `stale` into a
  prune is the Ranger's question and needs its own round.
- **A resumable canopy build.** J.13.4's new rule throws away a cancelled
  build's work on purpose; making it resumable needs partial vectors that
  are storable and not servable, which is a K.4 conversation.
- **A cursor for the bounded scent pass.** J.13.6.1 rule 9 states plainly
  that two `limit`ed runs pay twice. `since`/`until` on the pass is the
  obvious fix and is not in this round.
- **Splitting an oversized branch.** A.5's `needs_split` stays advice; the
  cap is a wall. A Ranger that splits a branch would relocate nodes, which
  no primitive does (J.5.7, C.15 moves one leaf at a time).

## Open questions

1. How a URI picks a store when two stores serve one bucket — needs J.19's
   answer, or `store://<name>/<prefix>` instead of `s3://`.
2. Whether the engine (no Station) needs a stores file under
   `~/.monkeyllm/`, the way Part L put the global extension install there,
   or whether the implicit `env` store is the whole CLI story.
3. Whether Part I's `README.txt` should name the `source_root` a `cached`
   forest's bodies depend on. It belongs in Part I, which may be another
   draft's this round.
4. `_derived/staging/` versus the existing `_derived/uploads/`
   (`UPLOAD_DIR`): kept separate here because J.13.7's "unrecorded" question
   has a different answer for the two — an upload's leftovers are the only
   copy and are evidence, a bucket download's are a cache of something the
   store still holds.
