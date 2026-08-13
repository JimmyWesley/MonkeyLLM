# T11 Answer store: serve the answer already bought

status: in-progress (2026-08-11: exact tier shipped end-to-end `answer_store.py`,
closed-list key with the K.3 entry-search mode included, HEAD invalidation,
heat-on-hit via `Trails.add_heat`, audit marking + digest, `Server-Timing`
`cache` clock, `cache: false` refresh on REST and MCP, admin surface
`/v1/admin/cache`, Studio Ask toggle + cached badge + Models card, locales
en/es/pt; F.37 suite green except the near-tier clause. Step 8 the near
tier remains.)
spec: v0.35 (J.10.7 two-hash revalidation + the C.6c.2 index-refinement fix;
was v0.33 J.10.7 + the J.10.6 `cache` clock + the J.4 audit rule + F.37)

2026-08-11, v0.35: HEAD left the sweep's key the reading fingerprint
(material as a set keyed by id, volatile fields excluded) now decides
whether the model runs; the sweep's retrieval runs on every ask; the
Part D whisper closes every hosted answer, hit and miss alike; walk
entries stay HEAD-pinned. C.6c.2 fixed along the way: index nodes are no
longer match-refined (the subtree grep destabilised the reading and
mislabelled snippets). F.37 suite rewritten accordingly (18 tests).

## Goal

Front the Station's `answer` composite with the per-forest answer store of
spec v0.33 J.10.7: a bounded cache in `_derived/cache/`, keyed by the closed
list (normalised question, effective terms, `k`, hops budget, resolved
binding, caller scope, forest HEAD), invalidated by the forest's own HEAD,
and honest on every surface `cached: true` in the body, `cache` in
`Server-Timing`, a marked audit row, and heat deposited on the stored trail.

## Context

- The provider round trip is the only expensive line in the product;
  retrieval is sub-millisecond. Repeated questions at deployment scale were
  paying full model price for answers already bought. The store makes the
  second ask free without ever serving a stale or out-of-scope answer.
- Everything lands in `apps/station/` (+ Studio). The engine gains no cache
  logic; `src/monkeyllm/` must not import from `apps/` (licensing boundary),
  and every piece the host needs already exists:
  - `GitOps` exposes HEAD (`src/monkeyllm/gitops.py`, `rev-parse HEAD`);
  - `Trails.add_heat(node_ids, ...)` is the storage-level heat deposit
    (`src/monkeyllm/trails.py`) a hit deposits through it, never through
    a primitive (J.6.1's warming rule in mirror);
  - `harvest` results carry the `trail`; the J.10.5 walk knows the nodes it
    opened either is the trail an entry stores;
  - `inference.py` already resolves bindings and prices runs (`_price`);
  - the audit log and `Server-Timing` assembly live in `app.py`/`registry.py`.
- v0.31 J.5.9 (runs live in the browser) stands unrevised: a run is one
  operator's note; a store entry is the deployment's instrument, named by
  its key and shared only within one scope. The v0.33 changelog states the
  distinction do not blur it in code or UI copy.

## Steps

1. **Store module** (`apps/station/monkeyllm_station/answer_store.py`):
   SQLite at `<forest>/_derived/cache/answers.db`, WAL +
   `synchronous=NORMAL` like the rest of `_derived/`. Schema: key digest
   (PK), question as asked, normalised question, effective terms, `k`,
   hops, binding fingerprint, scope fingerprint, HEAD, response JSON,
   trail JSON, created ts, last-served ts, served count, priced flag +
   usd of the original run, optional question embedding. Operations:
   `get`, `put`, `evict_to_bound` (oldest-served-first), `clear`, `stats`.
   Opened and touched **only on the forest worker thread** the
   `app.state.pool` rule applies unchanged.
2. **Key builder**: the closed list of J.10.7, nothing more. Question
   normalisation = NFC, trim, collapse inner whitespace, casefold. Digest
   = SHA-256; a short prefix is the log/audit name.
3. **Registry settings** (per forest): `enabled` (default **on**),
   `max_entries`, `ttl_hours` (hygiene only), `similarity` (nullable =
   near tier off). Admin surface: `GET/PUT /v1/admin/cache?forest=` and a
   clear action, behind `admin`.
4. **Wire into `answer`** (REST and MCP alike): lookup before compose.
   Hit: serve stored response + `cached: true` + original-run timestamp;
   `Server-Timing` carries `cache`, never `model`; audit row marked
   served-from-store with the key digest, cost recorded as avoided; heat
   deposited on the stored trail via `Trails.add_heat`; host log line with
   the digest. Miss: run, then store only a whole run never empty
   evidence, never an error/refusal, never a truncated response, never a
   turn that wrote.
5. **Bypass/refresh**: `cache: false` on the call skips the read, runs the
   model, and replaces the entry. Studio Ask gets the toggle and a
   "served from store" badge; J.5.9 runs record the flag they were asked
   with, so with/without pairs read side by side.
6. **J.10.6 amendment in code**: add the `cache` metric; the sum rule is
   over the clocks present. Adjust the F.32 test accordingly.
7. **Economy panel**: hits, misses, held-vs-bound, and USD not spent —
   summed only over priced original runs (unpriced saving is unpriced,
   never $0.00).
8. **Near tier** (last, optional to split into its own commit): only when
   Canopy AND an embedder are bound; embed entry questions; serve above
   the operator's threshold with every non-question key component matching
   exactly; refuse when the caller supplied terms; response names the
   stored question it answered. Off by default.
9. **F.37 suite**: every clause one provider call for a repeat, miss
   after a `plant`, miss on any key component change, empty-evidence never
   stored, refresh semantics, bound + eviction order, cross-scope
   isolation (two principals, distinct allow lists), heat risen with no
   tracer event, near-tier off/on behaviour.

## Acceptance criteria

- [ ] F.37 green, clause by clause.
- [ ] F.32 still green with `cache` present on hits and `model` absent.
- [ ] Leak check: an entry stored under one scope is never served to
      another principal's scope, on both surfaces.
- [ ] The engine tree is untouched: no cache code, no new imports.
- [ ] Full suite green (`.venv\Scripts\python.exe -m pytest -q`).

## Out of scope

- Any engine change: no primitive caching, no cache logic or vocabulary in
  `src/monkeyllm/`.
- Cross-forest or cross-deployment sharing; external cache backends
  (Redis and friends) the store is a file in `_derived/`, disposable.
- Caching `curate`, `harvest`, or any primitive.
- Query rewriting or paraphrase clustering beyond the single-threshold
  near tier with its disclosure.
