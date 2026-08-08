# MonkeyLLM Station

The host layer (spec Part J): serves a **forest registry** to many
principals with identity, subtree-scoped policy, audit, a web console, and
a per-forest choice of which model does the reading — the untouched engine
wrapped by a front door, so a forest can be a governed corporate asset
instead of a personal directory.

## Why it adds almost no dependencies

`starlette` and `uvicorn` already ship with `mcp`, the engine's own
dependency, so the Python side adds none. The Studio is a static React
bundle built at image time. J.6 holds: one image, two volumes, no external
database — the host registry is a single SQLite file.

## Run it

```bash
pip install -e . && pip install -e apps/station
(cd apps/studio && npm ci && npm run build)
station serve --root forests --registry ./station.db --port 8800
```

First run mints a bootstrap `admin` key with full capabilities on every
forest in the root and prints it once — only its digest is stored.

```bash
docker compose -f apps/station/docker-compose.yml up --build
```

## The three surfaces

| Surface | For | Where |
|---|---|---|
| REST | apps, scripts, integrations | `/v1/...` |
| MCP | any agent harness | `/mcp/` (streamable HTTP, same keys) |
| Studio | humans | `/` |

All three route through one `ScopedVine`. There is no unscoped path.

### REST

```bash
curl -sX POST localhost:8800/v1/forests/forest-fixture/answer \
     -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
     -d '{"question": "who wrote the MixerLLM architecture?"}'
```

`POST /v1/forests/{forest}/{name}` where `name` is a primitive
(`locate`, `look`, `move`, `pick`, `scan`, `sniff`, `harvest`, `query`,
`plant`, `graft`, `tend`) or a composite (`answer`, `curate`). Also
`GET /v1/health`, `/v1/me`, `/v1/forests`, and the `/v1/admin/*` routes the
Studio uses. Failures are the spec's error envelope mapped onto HTTP codes.

### MCP — pointing an existing harness at a governed forest

Add the Station as a streamable-HTTP MCP server with an `Authorization:
Bearer <key>` header. The tools are the Part C primitives plus `answer`,
so an agent that works against `vine serve` works here, gaining only a key
and a scope. Call `forests()` first: a scoped key has no master `_index`,
and that call returns the roots to start from.

## Governance (J.2/J.3)

A grant binds a principal to a forest with **capabilities**
(`read`, `query`, `write`, `tend`, `ingest`, `admin`) and **branch-prefix
scope** (`allow` / `deny`, deny wins, absent grant means no access).

```bash
station key --principal alice --forest forest-fixture --caps read,query
# then narrow the scope from Studio → Governance, or POST /v1/admin/grant
```

Two properties worth knowing, because they are what make the scoping
trustworthy rather than decorative:

- **Out of scope is indistinguishable from absent.** A node you may not
  see reports the engine's own `E_NOT_FOUND`, byte for byte — including
  through `move`, whose edges would otherwise disclose a hidden neighbour.
  The same reasoning applies to forests: an ungranted forest answers
  exactly like a nonexistent one, or the API becomes a registry
  enumerator.
- **Every derived count is recomputed.** `coverage`, `stats.degree`,
  `scanned_nodes` and the ancestor `trail` are counted over the whole
  forest by the engine, so the host recomputes them over what survived
  filtering. A count is a disclosure.

## Models per forest (J.10)

A forest is not one workload. Register any OpenAI-compatible `/v1`
(OpenRouter, LiteLLM, vLLM, local llama.cpp) under **Studio → Models**,
then bind a model per role:

| Role | Used by | Optimise for |
|---|---|---|
| `ingest` | curation, `curate` | care — its output is the scent every later hop navigates by |
| `answer` | `answer` | speed and instruction-following over retrieved material |

Provider keys are **write-only**: the API accepts one and afterwards
reports only that a key is set. Saving with an empty key keeps the stored
one, so an endpoint typo can be fixed without re-pasting a secret.

Binding a model cannot widen access: retrieval runs through `ScopedVine`
*before* the model is called, so it only ever sees what the caller could
already read. A `projects/`-scoped principal asking where the MixerLLM
author lives gets "the material does not contain that" — the fact lives in
`people/`.

## Audit (J.4)

Reads land in the host registry (principal, forest, primitive, argument
**digest**, size, timestamp — never bodies). Writes are git commits inside
the forest, amended to carry `station-principal: <id>`; the amended sha is
what the API returns, so the caller never holds one that no longer exists.

## How it is built

- **`policy.py`** — `Policy` + `ScopedVine`, the single enforcement seam.
  The scoped read methods keep the engine's signatures, so the `harvest`
  composite inherits scoping instead of reimplementing it.
- **`registry.py`** — principals, API keys (digests only), grants,
  providers, model bindings, audit. Never inside a forest (J.0).
- **`app.py`** — Starlette routes; forest resolution reuses the engine's
  `ForestPool` (C.0) unchanged, path-escape guard included.
- **`mcp_surface.py`** — the MCP mount. Stateless mode is a correctness
  choice: with sessions, a tool call can run in a task created during an
  earlier request, and the principal `ContextVar` would be the wrong one.
- **`inference.py`** — the per-binding chat client and the composites.

All forest access is confined to one dedicated thread: SQLite connections
belong to the thread that opened them and the engine rightly does not
weaken that. A worker per forest is the scale-out step.

## What is not here yet

| Missing | Where it goes |
|---|---|
| Ingest endpoints (`adopt`/`sync`) and the curation review queue | T07 / T09 |
| Trails dashboard, Ranger health, snapshots in Studio | T09 |
| OIDC/SSO, per-token quotas, rate limits | T07 Phase C |
| `answer` over datasets (a tool-calling loop; today it honestly refuses aggregate questions) | J.10 follow-up |
| Per-node ACLs finer than the branch prefix | out of scope (J.11) |
