status: done (2026-09-17: spec v0.84 CUT and IMPLEMENTED — J.19 stores +
G.7 r5 lossiness + G.9 write-by-binding/read-by-bucket + J.14 served
remotes (proxy under MONKEYLLM_STATION_PAYLOAD_PROXY_MAX_MB, 302 or
`Accept: application/json` above it) + A.3 `video`/`file` + Part I
`payloads_remote`/`--with-remote`/`buckets_unserved` + L.5 worker config.
F.219-F.228 green in tests/test_v084_{storage,station_storage,
worker_config}.py + apps/studio/check-storage.mjs; the live-MinIO module
tests/test_v084_live_s3.py runs in 7.6 s and skips where the store is not
named in the environment. Two defects only the live store could show:
botocore presigns SigV2 unless `signature_version` is set by hand (AWS has
refused SigV2 since 2014), and the Station forwarded no `stores=` to
`create_snapshot`/`restore_snapshot`, so `--with-remote` and
`buckets_unserved` would have been wrong on every deployment. OPEN, by
name: nothing lifts an existing `_assets/` tree into a newly bound store
and nothing moves objects when a binding changes; `prune` never deletes a
remote object, so nothing reclaims them; nothing probes a store's
reachability between ingests; a `.csv` original is not archived beside the
`.db` it births; `look` on a remote dataset still fetches the whole `.db`,
because C.2.2 has no "remote and not yet cached" rule. Uncommitted —
Jimmy commits by hand.)

# T19 Object storage: where the bytes that are not markdown live

## Goal

Give a forest somewhere to put the tier that is not text — a PDF's original,
a screenshot, an hour of video — that is not the disk of whatever container
the Station happens to run in. An operator configures an S3-compatible store
the way they already configure a model provider, a forest binds it **by
name**, and the Gardener's archive stage writes there instead of into
`_assets/`. A deployment that configures nothing keeps behaving exactly as it
does today, to the byte.

And fix the thing that made this urgent: under `archive: never` (the default)
plus the v0.61 consume, **an uploaded PDF's original exists nowhere** — the
conversion is lossy, the staged bytes are deleted the moment the node lands,
and no console offers a way to change either.

## Context

Three facts from the code, none of them a guess:

1. **The archive condition is media-shaped.** `gardener.py` archives a source
   only when `staged_media or archive == "always"` (the adopt path at ~1479,
   the sync path at ~2324). `staged_media` is `PAYLOAD_TYPE_BY_EXT[ext] in
   ("image", "audio")` and the source under the forest's own `_derived/`.
   G.5.1 wrote that exception for media and gave a reason that was never
   about media: *the staged copy is the only one that will exist*. A `.pdf`
   arriving through the same door gets none of it.
2. **`_assets/` is the only destination there is.** `Gardener._archive`
   (~1307) writes `<branch>/_assets/<sha8>-<slug><ext>` and returns
   `(payload, payload_type, payload_hash)`. The digest it needs is already
   computed; a content-addressed object key is the same digest under a
   different prefix.
3. **A remote payload is refused by both byte surfaces.** `Vine.view`
   (~2085) and the J.14 route in `app.py` (~4850) both answer "remote payload
   scheme 's3' is not served". So today an object store is a place a document
   goes to stop being viewable, which is why nothing has ever bound one.

Two more, about the shape of the answer:

- **A store is a provider in every way that matters** (J.10/J.3.2): one row,
  no forest column, any forest may bind it, its credential pays for all of
  them. So it inherits the reach rule, the write-only credential, the
  "a credential belongs to the address it was stored against" custody rule,
  and the environment-declared row (`origin: env`, key never persisted).
  `registry.py`'s `providers` table and `adopt_env_providers` are the
  template, line for line.
- **The engine may not read the registry.** `src/monkeyllm/` must never
  import from `apps/` (LICENSING), so credentials arrive as a resolver handed
  at construction, keyword-only — the same G.2.5 construction that keeps
  `adopted=` and `visible=` unreachable from the wire.

**One store record, not two.** T20 ("a forest from a bucket") needs a
credential for a **source** bucket; this task defines one for a
**destination** bucket. They are the same `stores` row and the same resolver
seam, or the deployment configures MinIO twice and two tables describe one
bucket — the failure v0.83 spent a whole round on. Whichever lands second
adopts the other's field names.

**A finding worth knowing before step 2:** `_meta/gardener.yaml` is **not
tracked** in any forest this project has produced. `forest.init` commits
`.gitignore`, `_index.md` and `_meta/schema.md` and nothing else, and
`Gardener._save_config` writes the file without committing it (verified:
`git -C forests/forest-fixture ls-files _meta` lists `_meta/schema.md`
alone). So "the binding travels in a snapshot" is false until the write goes
through `GitRepo.commit_meta` — the narrow `_meta/*.yaml|md` door L.12 opened
for `extensions.yaml`, which already exists and already refuses everything
else.

## Decisions taken

| # | Decision | Cost accepted |
|---|---|---|
| 1 | **A store mirrors a provider** — registry row, write-only credential, listing open to any admin, mutation/test needs authority over every forest | A single-forest deployment feels no difference; a second forest narrows that authority the moment it exists |
| 2 | **`MONKEYLLM_S3_BUCKET`/`_PREFIX` declare the `env` store**, credentials by boto3's default chain | An EC2/ECS deployment may hold no key at all; the row is read-only and the variables are the only way to change it |
| 3 | **The forest binds a NAME** in `_meta/gardener.yaml`, committed through the `_meta` door | `_meta` declares expectation and never grants it: an unmet binding is a warning and a local fallback, never an error |
| 4 | **Write resolution: binding → `env` → local `_assets/`** | A deployment that configured nothing is byte-identical, and that is a test, not a claim |
| 5 | **Read resolution by BUCKET, never by binding** | A forest that changed stores still reads what it wrote; a bucket no store serves is `E_NOT_FOUND` naming the bucket |
| 6 | **Content-addressed key** `s3://<bucket>/<prefix>/<forest id>/<sha256>.<ext>` | Dedup and immutability are free, and nothing in the key is caller-authored, so there is no traversal to refuse |
| 7 | **An upload that fails falls back to local and is NAMED** | The courier deletes the staged original; losing bytes to a network error is the one outcome this round exists to prevent |
| 8 | **Only a LOSSLESS conversion may skip the archive** (G.7 rule 5) | Text passthrough and `.db` adoption stay unarchived; every other conversion keeps its original |
| 9 | **A remote payload is proxied under 32 MB and 302'd above it** | Video never crosses the Station; a presigned URL leaves its authority behind, so its TTL is short and it is never recorded |
| 10 | **`video` and `file` join `payload_type`** | A recording stops being a `document`; an archived original with an unnamed extension stops being bytes no passport points at |
| 11 | **The heavy-worker request carries the resolved config** | The knobs the pdf extension reads from the host environment become install settings; a worker that does not ask is unchanged |
| 12 | **Nothing migrates** | Binding a store lifts no existing `_assets/`, and changing one moves nothing. Named, not implied |

## Steps

Spec first, then engine (Apache), then Station (AGPL), then Studio — the
order the licensing boundary already imposes, since the engine may not import
the host.

1. **Cut spec v0.84** from `docs/monkeyllm-spec-v0.83.md`. **Check the file
   does not exist first** (the v0.74 lesson: a `write_text` over a live cut
   destroyed a parallel session's work). Apply the draft in
   `spec84-storage.md`: new `### J.19 Object stores (v0.84)` between J.18 and
   J.12, amendments to A.3, G.1, G.5.1, G.6, G.7 rule 5, G.9, H.3, Part I,
   C.6d, J.3.2, J.4.1, J.13.2, J.14, L.5, and F.219-F.228 placed beside the
   rules they test. Verify by `diff` against v0.83, not by re-running anchor
   greps — the peer review that caught a missing edit in v0.74 was a diff.
2. **`src/monkeyllm/dialect.py`** — `PAYLOAD_TYPES` gains `video` and `file`.
   One line, and it is what `models.validate_frontmatter` (~329) enforces.
3. **`src/monkeyllm/gardener.py`** —
   - `PAYLOAD_TYPE_BY_EXT` gains `.mp4 .m4v .mkv .mov .webm .avi .mpg .mpeg`
     as `video`; `VIDEO_EXTENSIONS` beside `IMAGE_EXTENSIONS`/`AUDIO_EXTENSIONS`.
   - the typing rule: `is_media_source` reads `("image", "audio", "video")`.
   - the archive condition, both copies (~1479 adopt, ~2324 sync): replace
     `staged_media` with **lossiness** — a `markdown`-kind conversion of a
     non-text source that is staged (`self._is_staged(f)`) archives whatever
     `archive:` says; `archive: always` keeps its meaning; `payload` and
     `dataset` conversions are unchanged. Keep ONE predicate and call it from
     both paths, or the two will diverge the way they nearly did in v0.78.
   - `_archive` gains the store: resolve the destination (binding → `env` →
     local), upload content-addressed with a `HEAD` first, 60 s timeout,
     fall back to local on any failure with the reason in `report.errors`
     and a per-file count in the report.
   - an archived original whose extension names no payload type is referenced
     as `file` (this removes the "archived but not referenced" branch).
   - `Gardener(vine, ..., stores=None)` keyword-only; `supported_formats` and
     the rest untouched.
4. **`src/monkeyllm/fetch.py`** — a `Store` record and a resolver protocol
   (`by_name`, `by_bucket`); `_s3_client(store=None)` builds from the record
   or falls back to `MONKEYLLM_S3_ENDPOINT` + the default chain (today's
   behaviour); `head(uri)` → size/etag; `presign(uri, ttl)`; `upload` takes a
   store. `PayloadCache(derived, stores=None)` resolves by bucket and raises
   the `E_NOT_FOUND` naming the bucket when nothing serves it. Nothing here
   logs a credential.
5. **`src/monkeyllm/vine.py`** — `Vine(..., stores=None)` (and
   `server.ForestPool(..., stores=)`, which constructs every `Vine`);
   `view` resolves a remote image through the cache after a `HEAD` against
   the 6 MiB ceiling, still refuses a non-image by type and now names the
   J.14 route; `look` carries `payload_remote: true` for a remote payload and
   makes **no** network call.
6. **`src/monkeyllm/catalog.py`** — `count_missing_payloads` counts a remote
   payload whose bucket no store serves, and reports the buckets; C.17 rule
   11 and Part I's restore keep sharing the one implementation.
7. **`src/monkeyllm/snapshot.py`** — `create_snapshot(..., with_remote=False)`
   reports `payloads_remote` always and packs objects under
   `payloads/_remote/<bucket>/<key>` when asked;
   `_check_container_member` admits that shape with every existing clause
   intact (no `..`, no backslash, no dot-leading component, ≥2 components
   after `_remote/`); `restore_snapshot` parses a `_remote/` member back into
   its URI and writes to the slot **the cache computes**, reporting
   `remote_restored`, and counts unserved buckets into `payloads_missing`
   with `buckets_unserved` beside it.
8. **`src/monkeyllm/cli.py`** — `--with-remote` on `snapshot create`;
   `validate` prints the unmet `assets:` expectation the way it already
   prints an expected-but-absent extension (~209). No `vine stores`: the
   engine's store is the environment's, and governance is the Station's
   (L.12's split).
9. **`src/monkeyllm/lint.py` / `ranger.py`** — `stores_missing` in the H.3
   health report: the unmet binding plus the buckets this forest's payloads
   name that no resolver serves. A stat, no object opened.
10. **`src/monkeyllm/extensions/worker.py` + `loader.py` + `contracts.py`** —
    the worker request carries `config`; the child passes it only to a
    handler that declares the parameter; the seam contracts declare it so the
    L.9 check knows the signature is legal. A v0.83 worker is byte-identical.
11. **`apps/station/monkeyllm_station/registry.py`** — the `stores` table
    (name PK, endpoint, bucket, prefix, region, access_key, secret_key,
    path_style, origin, created), `adopt_env_stores`, `put_store`,
    `delete_store`, `stores()` (never a secret, `has_key` only),
    `store_secret()`. A new table needs a `MIGRATIONS`/`ensure_schema` entry
    and **no `DATA_REPAIRS` statement** — there is no shipped value to
    repair, and appending one that does nothing burns a `user_version` stamp.
12. **`apps/station/monkeyllm_station/app.py`** —
    - `GET|POST /v1/admin/stores` and `POST /v1/admin/stores/test`, gated by
      `is_admin` for the listing and `governs_deployment` for everything
      else; `_reject_internal_endpoint` reused as-is (same variable);
      `record_governance("admin.store"/"admin.store.test", …)`;
      `hooks.emit(webhooks.DEPLOYMENT, "store.changed", …)`.
    - build the resolver from the registry and hand it to the pool, so every
      `Vine` and every `Gardener` gets it; the resolver is the only thing
      that crosses into the engine.
    - the J.14 payload route: resolve the node **on the lane**, then leave it
      for the `HEAD`/fetch/presign; proxy at or under
      `MONKEYLLM_STATION_PAYLOAD_PROXY_MAX_MB` (32), 302 above it with
      `MONKEYLLM_STATION_PAYLOAD_PRESIGN_TTL` (300); audit the node, the byte
      count and that it redirected — never the signed URL.
    - snapshot create/import: `with_remote`, and the new counts on both
      responses.
    - `test_station_admin_scope`'s route canary will sweep the new routes the
      day they are added; that is the point of it (v0.80's lesson).
13. **Studio** — `api.js` (`stores`, `putStore`, `deleteStore`, `testStore`,
    the per-forest binding), a **Storage** tab in `views/Ingest.jsx` beside
    Upload/Sync/Optimize, locales in `src/locales/…/{en,pt,es}.json`. Two
    traps with receipts: the tab value MUST be in `useRouteState`'s `allow`
    list or the address snaps back to Upload (the v0.41 `sync` bug), and no
    code path may `fetch` a payload URL that can redirect — J.5.13 pins
    `connect-src 'self'`, so a large payload is offered as a link, never as
    an inline fetch.
14. **`apps/studio/check-storage.mjs`**, run from `tests/test_v084_*.py`:
    asserts the console holds no list of endpoints or buckets of its own, and
    that the redirect-capable route is never fetched (F.226's static half,
    F.137's boundary).
15. **Docs** — the MinIO paragraph (drafted in `spec84-storage.md` §4) into
    `docs/` beside the local-inference note; `.env.example` gains
    `MONKEYLLM_S3_BUCKET` / `MONKEYLLM_S3_PREFIX`; `apps/station/README.md`
    gains the two new variables.
16. **Tests** — `tests/test_v084_stores.py` (engine: resolution, archive,
    fetch, snapshot), `tests/test_v084_station_stores.py` (routes, reach,
    custody, payload serving), against a stubbed S3 that records every call
    it was given, so "the stored credential was not sent" is asserted at the
    destination and not at the caller.

## Acceptance criteria

- [ ] F.219 The store row and its secret: listing carries `has_key` and
      neither the secret nor the access key id; `null` keeps; a half pair is
      `E_SCHEMA`; a changed endpoint or bucket requires the credential again;
      listing is any admin's while create/change/remove/test need every
      forest (break-glass included); removing a store leaves every forest's
      `_meta/gardener.yaml` byte-identical; every act is audited without the
      secret.
- [ ] F.220 The test writes: `HEAD` + probe written + probe deleted, all
      three named; a read-only credential FAILS naming the write; private
      addresses refused unless `MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE=1`;
      a caller-supplied destination receives no stored credential (asserted
      at the stub).
- [ ] F.221 The `env` store: published read-only from the variables, its
      credential absent from the registry file, edit and removal refused;
      with the variables unset, every path behaves byte-identically to v0.83.
- [ ] F.222 The write: content-addressed key, `HEAD`-dedup, the three
      passport fields; **with nothing configured the forest tree is
      byte-identical to the v0.83 result**; an unmet binding falls back
      locally and is named in the report, in `validate` and in H.3; a timed
      out upload does the same and no passport ever names an object the store
      does not hold.
- [ ] F.223 The read follows the bucket: a re-bound forest still reads its
      old bucket; an unserved bucket is `E_NOT_FOUND` naming the bucket and
      nothing else; an out-of-scope node still answers the byte-identical
      F.49 envelope; a hash mismatch re-fetches.
- [ ] F.224 A lossy original survives its own upload: an uploaded `.pdf`
      under `archive: never` is archived and servable after the staged copy
      is consumed; a `.md` is not archived; a `.db` is stored exactly once; a
      durable disk source is still referenced and not copied.
- [ ] F.225 `video` and `file`: a `.mp4` plants `media` with
      `payload_type: video`; an unnamed extension is referenced as `file`; a
      pre-v0.84 node is not retyped by `sync`.
- [ ] F.226 Proxy and redirect: under the ceiling the bytes, the `ETag` and
      the 304; above it a 302 whose presigned URL works and expires; the
      audit row carries no signature; a scheme that cannot sign is proxied or
      refused naming the ceiling; the three `E_NOT_FOUND`s stay identical;
      the console never fetches a redirect-capable URL.
- [ ] F.227 `view` reaches a remote image (bytes and `payload_hash` match),
      refuses one over 6 MiB **without fetching it**, and refuses a video by
      type while naming the J.14 route.
- [ ] F.228 The worker knows its settings: a handler declaring `config`
      receives defaults overlaid with stored values and sees an edit on the
      next call with no restart; a handler that does not declare it is
      byte-identical to v0.83; a declared secret reaches the worker and
      appears in no report, log, audit row or error.

## Out of scope

- **Migration and reclamation.** Nothing lifts an existing `_assets/` into a
  store, nothing moves objects when a binding changes, and `prune` never
  deletes a remote object. Both wants are real; both rewrite or delete bytes
  in bulk and deserve their own round with their own failure analysis.
- **Per-tenant isolation.** A prefix is not a boundary. Two forests bound to
  one store share a bucket and a credential; a deployment that needs
  isolation configures a store per bucket.
- **Backends beyond S3-compatible.** Azure Blob and GCS are a fetcher each,
  not a contract change; this round ships the one boto3 already speaks.
- **`source_path` with a scheme.** G.9 allows it and `content: reference`
  would resolve it; this round touches payloads only.
- **Streaming, ranges, CDNs.** The redirect exists precisely so this project
  never becomes any of them.
- **Any relaxation of the primitives' contract**, the token budgets, or the
  rule that binaries never enter forest git (A.3.1).

## Open questions

- Whether a `.csv`/`.xlsx` original should be archived beside the `.db` it
  became. Today it is not, and the cost is the formulas and layout the
  conversion drops; keeping it needs a second payload reference on one node.
- Whether the Ranger should periodically prove a bound store is reachable,
  or whether the first failed archive is soon enough.
- Whether a large payload should be downloadable at all from a console that
  cannot fetch it — a link is specified; a signed link shown as text may be
  worse, since a reader can paste it anywhere.
