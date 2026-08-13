# T13 The Clipper: a browser extension that feeds the Gardener

status: in-progress (2026-08-13: spec v0.48 + full implementation on
`develop`, uncommitted. Station: pair route + caps mask threaded through
REST and MCP (admin/owner bits included), shared login/pair rate limiter
(bounded window map), payload bytes route, vision describer wiring.
Engine: media stub converter, media typing, staged-media archive on adopt
AND re-archive on sync, `extra_converters` seam, converter-failure
fallback chain in both ingest and refresh paths. Studio: vision role card
+ Integrations clipper section, locales en/pt/es. `apps/clipper/`: MV3
extension complete (pairing, pickers, 6 actions, context menus,
serialized E_LOCKED queue, YouTube transcript, screenshot-at-click).
Adversarial review: 25 agents, 10 findings → 6 roots, all fixed with
regression tests. Distribution shipped after review: the Station serves
the one shared build at `GET /clipper.zip` (J.15 amendment; ETag'd,
rebuilt when a file changes, `MONKEYLLM_STATION_CLIPPER_DIR` override)
and the Studio rail offers "Get the Clipper" to every signed-in person
— never admin-gated. ROUND 2 (2026-08-13, from a real-browser test):
spec v0.48 amended in place J.8 `source_url` on upload entries
(provenance map in the Gardener, surviving refreshes), G.5.1 describer
timeout ≤60s (a convert stage holds the forest lane; 180s froze every
console on the forest), J.14 console SHOULD render media images, J.15
non-blocking click path / region capture / image context menu / editor
tab / UI language. Implemented: Station provenance + control-char
refusal + payload 304s; Studio PayloadImage (header-sniff before body);
clipper rebuilt fire-and-forget (worker owns the work, storage carries
progress), region.js drag overlay (teardown-before-capture, expiry
handshake), image menu with raster transcode + screen fallback, honest
job reports (a done job that planted nothing fails loudly), editor.html
with TipTap + dictation + per-forest drafts (no resurrect-after-send),
own i18n (auto/en/pt/es) with selector. Second adversarial review: 25
agents, 9 confirmed → all fixed with regression tests. Suite green:
845 passed. REMAINING: re-test in the browser (reload the unpacked
extension) and the user's commit.)
spec: v0.48 (J.2.6 + G.5.1 + J.14 + J.15, F.47–F.49)

## Goal

A Manifest V3 browser extension (`apps/clipper/`, AGPL) that clips what a
person is reading into a forest through the Station's existing surfaces:
the readable article or the selection as markdown through `compose`, a
screenshot as a `media` node through `upload`, a typed note through
`compose` with a forest picker, a destination branch picker, and a
pairing flow (server origin + username/password, once) that stores only a
narrowed key (J.2.6), never the password.

## Context

The ingest console (J.8) already covers the operator at their desk; the
Clipper covers the same person mid-browse "this page belongs in my
forest" as one click instead of a copy-paste round trip. Three host
contracts were missing and are now spec v0.48:

- **J.2.6 pairing** `POST /v1/auth/pair` turns a password into a key
  carrying a capability mask (`{read, ingest}` by default); effective
  authority is grants ∩ mask wherever the requesting principal's
  authority is read (REST and MCP, admin/owner bits included). Login and
  pair gain a rate limiter.
- **G.5.1 stub + describer** image/audio sources plant as `media`
  (never `unsupported`): a built-in stub converter in the engine, plus a
  host-injected describer when the forest binds the new `vision` role
  (J.10). Media staged under `_derived/` (uploads) is archived into
  `_assets/` regardless of archive policy. New `extra_converters` seam
  in the Gardener (public API v1, additive).
- **J.14 payload bytes** `GET /v1/forests/{forest}/payload/{node}`
  serves the payload file of an in-scope node (read cap, byte-identical
  `E_NOT_FOUND` out-of-scope, containment, local payloads only), so a
  clipped screenshot is visible in a console at all.

## Steps

1. ~~Spec v0.48~~ (done).
2. Station: pair route + rate limiter + caps mask threading (REST + MCP),
   payload route, vision describer injection in `run_ingest`.
3. Engine: media typing, image/audio stub converter, `extra_converters`,
   `_derived/` staging archive rule.
4. Station: `vision.py` describer (chat content-parts over the existing
   OpenAI-compatible binding), `vision` in `Registry.ROLES`.
5. Studio: `vision` role card in Models; Clipper section in Integrations
   (pairing instructions, install steps); locales en/pt/es.
6. Extension: MV3, popup (login/pair, forest+dest pickers, clip page /
   clip selection / screenshot / write / upload file), context menu,
   Readability+Turndown vendored, YouTube transcript special-case,
   client-side `E_LOCKED` queue, `_locales` en/pt/es, icons from the
   project logo.
7. Tests: F.47 (pair narrows, rate limit), F.48 (stub/describer/staging
   archive), F.49 (payload bytes) suite stays green.

## Acceptance criteria

- [x] F.47: masked key refused `plant` and every `/v1/admin` route (owner
      included, MCP included); still reads and ingests; pair rate-limited;
      expiry mandatory; `/v1/me` reports masked caps.
      (`tests/test_station_pair.py`, 14 tests)
- [x] F.48: `.png` never `unsupported`; stub without binding, description
      with one; describer failure falls back to stub on adopt AND sync;
      upload-staged media archived under `_assets/` even with
      `archive: never`, and RE-archived when a staged file is re-synced;
      operator command hook outranks the describer.
      (`tests/test_media_stub.py` + `tests/test_station_vision.py`)
- [x] F.49: payload bytes equal disk, `ETag` = `payload_hash`,
      out-of-scope/absent/no-payload byte-identical `E_NOT_FOUND`,
      escape refused, remote URI `E_SCHEMA`.
      (`tests/test_station_payload.py`, 8 tests)
- [ ] Clipper clips in a real browser: page → markdown node, selection →
      markdown node, screenshot → media node, note → markdown node;
      forest and dest pickers driven by `/v1/forests` roots; stores
      origin + paired key only. (Built and statically validated; needs a
      load-unpacked smoke test by a person.)
- [x] Full pytest suite green (831 passed, 2026-08-13).

## Out of scope

- Store distribution (Chrome Web Store / AMO listing) and signing.
- Full-page scroll-stitched screenshots (visible viewport only in v1).
- Audio transcription (a `transcribe` role is G.5's named future, not
  this task).
- Automatic branch routing ("the Gardener picks the branch") the
  Clipper suggests via `locate`, the person confirms; auto-routing would
  be a G.4 spec change.
- Serving payload bytes over MCP to multimodal clients (G.5's parked
  extension stays parked).
