# MonkeyLLM Station

The host layer (spec Part J): serves a **forest registry** to many
principals with identity, capabilities and audit — the untouched engine
wrapped by a front door, so a forest can be a governed corporate asset
instead of a personal directory.

Status: **Phase A** (task T07) — read-only REST. See "What is not here yet".

## Why it adds no dependencies

`starlette` and `uvicorn` already ship with `mcp`, the engine's own
dependency. The Station is built directly on them, so J.6's promise (one
image, no external database) survives: the host registry is a single SQLite
file.

## Run it

```bash
pip install -e . && pip install -e apps/station
station serve --root forests --registry ./station.db --port 8800
```

First run mints a bootstrap `admin` key with full capabilities on every
forest in the root and prints it once — only its digest is stored.

Grant someone narrower access:

```bash
station key --registry ./station.db --principal alice --forest forest-fixture --caps read,query
```

Container (spec J.6):

```bash
docker compose -f apps/station/docker-compose.yml up --build
```

## The API

Every call carries `Authorization: Bearer <key>` (or `X-API-Key`).

| Endpoint | Meaning |
|---|---|
| `GET /v1/health` | liveness; no key required |
| `GET /v1/forests` | the forests **this principal** may see |
| `POST /v1/forests/{forest}/{primitive}` | body is the primitive's arguments as JSON |

Primitives served in Phase A: `locate`, `look`, `move`, `pick`, `scan`,
`sniff`, `harvest`, `query`.

```bash
curl -sX POST localhost:8800/v1/forests/forest-fixture/locate \
     -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
     -d '{"query": "stigmergy", "k": 3}'
```

Responses are the primitives' own payloads, and failures are the spec's
error envelope (`{"error": {code, message, hint}}`) mapped onto HTTP status
codes.

## How it is built

- **`policy.py`** — `Policy` + `ScopedVine`, the single enforcement seam.
  Every surface reaches a forest through it, so an unscoped `Vine` is
  unreachable by construction (J.1). Capabilities (`read`, `query`,
  `write`, `tend`, `ingest`, `admin`) are enforced here.
- **`registry.py`** — principals, API keys (stored as digests only) and
  grants, in host-side SQLite. Never inside a forest (J.0).
- **`app.py`** — Starlette routes. Forest resolution reuses the engine's
  `ForestPool` (spec C.0) unchanged, including its path-escape guard.

Two decisions worth knowing:

- **An ungranted forest answers exactly like a nonexistent one.** Otherwise
  the API enumerates the registry — the same existence-oracle reasoning J.3
  applies to nodes, applied to forests.
- **All forest access is confined to one dedicated thread.** SQLite
  connections belong to the thread that opened them and the engine rightly
  does not weaken that; confining access also keeps blocking reads off the
  event loop. Serialising across forests is a Phase A simplification — a
  worker per forest is the scale-out step and changes nothing above that
  line.

## What is not here yet

| Missing | Lands in |
|---|---|
| Prefix scoping (`allow`/`deny` subtrees) + the F.18 leak suite | **T08**. Until then a prefix-restricted policy is *refused at construction* rather than silently under-enforced. |
| Writes (`plant`/`graft`/`tend`), ingest, principal-stamped commits (J.4) | T07 Phase B |
| MCP surface behind the same keys | T07 Phase B |
| Studio web console (J.5) | T09 |
| OIDC/SSO, quotas, rate limits | T07 Phase C |
