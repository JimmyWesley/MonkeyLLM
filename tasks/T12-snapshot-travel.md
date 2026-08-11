# T12 — Snapshot travel: download and import over the Station

status: done (2026-08-11: both routes shipped in `app.py` — download streams
with owner gate, name-before-path validation and containment after
resolution; import stages under `snapshots/_incoming`, restores via Part I,
grants the creator, opens the lane best-effort, spends no model call.
Studio: per-row download + payload-sidecar download in the Health snapshots
panel, `ImportForestModal` off the forest switcher, both rendered owner-only;
locales en/pt/es; `python-multipart` declared. F.39 suite in
`test_station_maintenance.py` (5 tests) green, admin-route canary extended,
full suite green.)
spec: v0.39 (J.13.1 download + J.13.2 import, Part I pointer, F.39)

## Goal

Let a snapshot leave and enter a Station over HTTP, owner-only: stream the
bundles J.13 already takes (`GET /v1/admin/snapshots/{forest}/{file}`), and
create a new forest from an uploaded bundle
(`POST /v1/admin/snapshots/import`) — J.7 name rules, refuse-if-existing,
`reindex` included, no model call. Spec v0.39 is written; this task is the
implementation.

## Context

The Station takes and lists snapshots (J.13) but the bundle stays on the
volume, reachable only by a shell the hosted operator does not have; the
only way back into a registry is `vine snapshot restore` at a terminal.
Part I's use cases (backup, distribution, frozen releases) end at the
volume boundary. The immediate motivator: pulling a production forest down
to a dev machine to reproduce host-side latency locally (the hybrid-locate
investigation of 2026-08-11 — Ollama cold reload ≈ 3.2 s, stale canopy
refresh ≈ 12 ms/node inside `locate`).

Both routes are owner-only by design: a bundle carries the whole forest
with full history (every branch scope collapses inside it), and an import
bypasses every J.8 converter/curation/review pass — a bundle is already
forest and enters as-is.

## Steps

1. **Download route** in `apps/station/monkeyllm_station/app.py`:
   `GET /v1/admin/snapshots/{forest}/{file}` — owner gate
   (`registry.is_owner`), `{file}` validated as a single name (no
   separators, no relative segments), resolved target contained inside
   `snapshot_dir(forest)` after resolution, unlisted name → `E_NOT_FOUND`.
   Stream with `Content-Disposition` + `application/octet-stream`. No
   lane, no trace, no pheromone, no commit; audit row (J.4) with file
   name and byte count.
2. **Import route**: `POST /v1/admin/snapshots/import` — owner gate; body
   carries `id` + bundle bytes (+ optional payload sidecar). Validate `id`
   as a name before it is a path (J.7); refuse an existing id; stage the
   uploaded bytes outside every forest; `restore_snapshot` into the
   registry root; place payloads; run `reindex`; register + grant the
   creator full capabilities; open and warm the lane (J.6.1). No model
   call — no curation, no canopy build. Optional size cap from deployment
   config.
3. **Studio**: a download control beside each row of the snapshots panel
   and an import control on the forest list — both rendered only for the
   owner (the host refuses everyone else regardless; the console just
   doesn't offer a dead door).
4. **F.39 suite**: round-trip (create → download → import under fresh id →
   `git log` equality); downloaded bytes hash-equal the file on the
   volume; traversal/unlisted `{file}` refused without filesystem effect;
   non-owner `admin` refused on both routes with the owner reason;
   existing id refused; imported forest answers `locate` with no shell
   step and stays BM25-only until a canopy is built; neither route
   produces a commit, a trace or pheromone in any forest.

## Acceptance criteria

- [x] F.39 green.
- [x] Existing F.26 stays green (list/create untouched).
- [x] Suite green (`.venv\Scripts\python.exe -m pytest -q`).

## Out of scope

- Restore into an existing forest over HTTP (stays `vine snapshot
  restore`, J.13).
- Scoped/partial bundles ("there is no such thing as a scoped bundle").
- Scheduled snapshot shipping to object storage (Part I `--to s3://`
  already covers it engine-side).
- Any change to Part I's on-disk formats.
