# Extending MonkeyLLM

A map of every place MonkeyLLM is designed to be extended, and — just as
important — the boundaries that stay closed. `docs/monkeyllm-spec-v0.20.md`
is the normative contract; nothing below overrides it. Ingest-specific
plugins (converters, `on_curate` hooks) are covered in
`docs/ingest-tools.md` — this doc is the wider picture.

## What's a UI/bot, not a plugin

Per spec Part G: "UIs and bots are MCP/library clients, not plugins."
Nothing here is about forking `vine.py` — the ten primitives' semantics,
token budgets, and guards (locate BM25-only by default, `tend` DML-only,
no silent truncation, etc.) are the fixed contract every client talks to.
Extension points are additive, at the edges: what feeds data in, what
model answers, where payloads live.

## 1. Chat LLM (curation + any agent driving the loop)

Any OpenAI-compatible `/v1/chat/completions` endpoint — llama.cpp,
OpenRouter, vLLM, LM Studio. Configured entirely by environment variables
(`MONKEYLLM_LLM_ENDPOINT`/`_MODEL`/`_API_KEY`/`_MAX_TOKENS`/`_REASONING`),
consumed identically by `src/monkeyllm/curator.py` (Gardener curation) and
`examples/demo/run_demo.py` (the navigator agent). See `.env.example` and
`docs/model-notes.md` for known-good models and gotchas (reasoning-model
token budgets, OpenRouter model-id quirks).

There is no plugin surface here beyond "point it at a different endpoint"
— by design, so curation/navigation behavior stays reproducible across
models rather than depending on custom prompting code per provider.

## 2. Embedder (Canopy vector layer, Phase 1, optional)

Any OpenAI-compatible `/v1/embeddings` endpoint, via
`MONKEYLLM_EMBED_ENDPOINT`/`_MODEL`/`_API_KEY` (`src/monkeyllm/canopy.py`,
`LlamaCppEmbedder`). Absent both a Canopy index and an embedder, `locate`
stays BM25-only (the Phase 0 contract) — this is a hybrid-search
upgrade, never a requirement. OpenRouter does not serve embeddings; use a
local llama.cpp embedding server or another OpenAI-compatible provider for
this piece specifically.

## 3. Ingest converters and curation hooks (Gardener, Part G)

Covered in full in `docs/ingest-tools.md`: `_meta/gardener.yaml` command
hooks, `monkeyllm.converters` / `monkeyllm.hooks` entry points, the
`Converter` protocol, the `on_curate` contract.

## 4. Remote payload fetchers (spec G.9)

`src/monkeyllm/fetch.py` resolves a `payload:` URI's scheme through the
`FETCHERS` registry — built in: `file://` (also the test double) and
`s3://` (optional `boto3` extra; `MONKEYLLM_S3_ENDPOINT` for MinIO/R2).
Reads land in the hash-validated `_derived/payloads/` cache (tampered
downloads are refused, never silently served); the Ranger evicts it
LRU-style (`payload_cache_gb`, spec H.6). `tend` rejects remote payloads
outright — datasets stay local-first (G.9.4).

Adding a new scheme means adding an entry to `FETCHERS` in `fetch.py`
itself (there is no entry-point group for this yet — it's a short,
security-sensitive function, kept in-tree rather than opened to arbitrary
installed packages). If you need one, open a task rather than monkey-
patching the dict at runtime.

## 5. MCP server / clients

`src/monkeyllm/server.py` exposes the ten primitives (plus `harvest`, the
C.6c composite retrieval tool) over MCP. Any MCP-speaking agent or IDE
integration is a valid client — this is the intended integration surface
for new UIs/bots, not a code extension point. `ForestPool` (multi-forest
serving) picks the forest from `--forest`, `MONKEYLLM_FOREST`, or a
`--root` directory of forests.

## Boundaries that do not move without a spec bump

- Primitive semantics, token budgets (`look` 500, `move` 600,
  `locate`/`scan`/`sniff` 800), and truncation contracts.
- `locate`/`sniff` split (metadata vs. body search) — never merged.
- `tend` staying DML-only, `plant`'s declarative dataset schema staying
  the only path to a new table (no `ALTER` for agents, ever).
- Edge proposals targeting only existing, catalog-offered nodes (G.4.2.1)
  — never a route to mint hallucinated targets.
- Binaries never entering forest git (spec A.3.1) — payloads referenced by
  `payload_hash`, not committed.

If a change touches any of the above, the process is: write the spec
delta first (new `docs/monkeyllm-spec-v0.NN.md`), then implement — per
`CLAUDE.md`, "the spec is the truth."
