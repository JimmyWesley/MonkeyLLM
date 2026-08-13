# MonkeyLLM Station

The host layer (spec Part J): serves a **forest registry** to many
principals with identity, subtree-scoped policy, audit, a web console, and
a per-forest choice of which model does the reading the untouched engine
wrapped by a front door, so a forest can be a governed corporate asset
instead of a personal directory.

## Why it adds almost no dependencies

`starlette` and `uvicorn` already ship with `mcp`, the engine's own
dependency, so the Python side adds none. The Studio is a static React
bundle built at image time. J.6 holds: one image, two volumes, no external
database the host registry is a single SQLite file.

## Run it

```bash
pip install -e . && pip install -e apps/station
(cd apps/studio && npm ci && npm run build)
station serve --root forests --registry ./station.db --port 8800 --writable
```

First run mints a bootstrap `admin` key with full capabilities on every
forest in the root and prints it once only its digest is stored. You do
not need it to reach the console: open the Studio and the **setup screen**
(J.2.4) creates the owner.

### The owner (J.2.4)

A Station with no credential offers exactly one unauthenticated route,
`POST /v1/auth/setup`, and it closes permanently the first time it is used.
What it creates is the **owner**: a principal carrying a bit rather than a
pile of grants, which makes it `admin` on every forest present and future —
including on none at all. That last part is the point. Authority to create
the first forest cannot be derived from a forest, or a fresh install has
nobody able to make one.

There is exactly one owner, enforced by a unique index rather than by the
code path that happens to create it, and the bit cannot be handed out
through `/v1/admin/people`. Everything else stays per forest: the owner uses
the same consoles as everybody, with the same capability rules.

### Signing in (J.2.1)

Two doors, one identity. A super-administrator in the environment is
**break-glass** setting it replaces the setup screen rather than
complementing it, so the two never race for the first identity:

```bash
export MONKEYLLM_STATION_ADMIN=jimmy
export MONKEYLLM_STATION_PASSWORD='something long and unguessable'
```

That account is compared against the environment and **never stored** it
is break-glass, and hashing a value that already sits in the environment
protects nothing while giving a rotation two places to go wrong. Rotate it
by changing the variable and restarting. If the variables are absent there
is no password door at all, which is the only safe default.

Everyone else gets a password under **Studio → Tokens**, stored as a salted
scrypt hash. A login returns a **session token**: an ordinary API key with a
12-hour life, so from that point on there is exactly one authorization path
no matter which door was used.

`--writable` is off by default: reads always work, and writes, ingest and
forest creation are refused up front with `E_READONLY` rather than failing
file by file once the work is under way.

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

Navigation lists exactly the consoles the caller's capabilities permit on
the selected forest, and re-evaluates when the forest changes. That is
presentation, not enforcement: each console guards itself, and the API
refuses regardless including for a request the console never sent.

The Studio (J.5) is nine consoles in three groups **Use** (Overview, Ask,
Explore, Playground, Data), **Build** (Ingest, Models) and **Govern**
(People, Audit) in English, Portuguese and Spanish, light and dark. It
addresses the operator in the operator's vocabulary: access is granted by
ticking the **forests** it covers, picking a **role**, and for a single
forest **branches from the actual tree**, with the resulting capability set
shown as a consequence and the whole grant restated in a sentence before it
is saved. A policy an operator cannot read back is one they cannot audit.

### REST

```bash
curl -sX POST localhost:8800/v1/forests/forest-fixture/answer \
     -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
     -d '{"question": "who wrote the MixerLLM architecture?"}'
```

`POST /v1/forests/{forest}/{name}` where `name` is a primitive
(`locate`, `look`, `move`, `pick`, `scan`, `sniff`, `harvest`, `query`,
`plant`, `graft`, `tend`), a composite (`answer`, `curate`) or `ingest`
(J.8). Also `GET /v1/health`, `/v1/me`, `/v1/forests`,
`POST /v1/admin/forests` (J.7) and the other `/v1/admin/*` routes the Studio
uses. Failures are the spec's error envelope mapped onto HTTP codes.

### The answer store (J.10.7)

`answer` is fronted by a per-forest cache of answers already bought,
governed by two hashes with two jobs (v0.35). The first normalised
question, effective terms, effective `k`, entry-search mode, resolved
binding, caller scope finds the entry. The second is the **reading
fingerprint**: the sweep's retrieval runs on every ask (it is the cheap
half), and the stored reply is served only when the material the model
would read is the material it already answered. Invalidation is therefore
exact, not indiscriminate: an edit to a node the question reads is a
miss; a write anywhere else invalidates nothing; there is no staleness
window to tune. (A `hops` walk cannot be re-run without paying the model,
so walk entries are pinned to the forest's HEAD instead any commit
invalidates them.) A hit says so on every surface: the body carries
`cached: true` and the time of the original run (`cached_at`) over fresh
retrieval fields, the `Server-Timing` header carries `cache` and no
`model`, and the audit row is marked as served from the store with the
entry's key digest. Hit or miss, the answer's evidence receives the
Part D whisper, so the pheromone map keeps reading the deployment's
questions as the heat they are.

Pass `"cache": false` to skip the read and buy a fresh run; the fresh
result **replaces** the stored entry, which is how with-and-without is
compared:

```bash
curl -sX POST localhost:8800/v1/forests/forest-fixture/answer \
     -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
     -d '{"question": "who wrote the MixerLLM architecture?", "cache": false}'
```

The MCP `answer` tool takes the same parameter. Settings and economy live
at `GET|POST /v1/admin/cache?forest=` (requires `admin` on that forest):
`enabled` (default on), `max_entries` (the stated bound, evicting
oldest-served-first), `ttl_hours` (hygiene only the key already
invalidates), and `clear: true` to empty the store. The stats report hits,
misses, entries held against the bound, and the money not spent counted
only over runs the provider priced, because an unpriced saving is unpriced,
never $0.00.

### Maintenance (J.13)

`GET /v1/admin/health?forest=` relays the Ranger's H.3 report unchanged —
lint counts, branches grown too wide, overloaded nodes, passports whose
source vanished, link proposals by confidence, pheromone stats. It requires
`admin` **and** an unrestricted scope: the report counts things across the
whole forest, so a filtered version would carry numbers describing nodes the
caller cannot see. Reading it writes nothing.

`GET|POST /v1/admin/snapshots` takes and lists Part I bundles, which land
beside the registry rather than inside any forest. **Restore is not
exposed**: a bundle unpacks into an empty directory, so there is nothing to
restore over a live forest, and taking a filesystem destination from an HTTP
caller would spend the Station's authority rather than the caller's. It stays
`vine snapshot restore`.

### Map projections (J.11)

```bash
curl -s localhost:8800/v1/forests/forest-fixture/graph \
     -H "Authorization: Bearer $KEY"
```

`GET /v1/forests/{forest}/graph` returns `{nodes, edges, types, rels,
truncated}` the Catalog joined with persistent heat and
`GET .../trails` returns `{heat, stats, truncated}`. Both take `scope`
(a branch) and `limit`, both need `read`, and both are scoped exactly like
the primitives: **an edge appears only when both of its endpoints do**, and
`degree` is recomputed from the edges that survived rather than reported
from the Catalog, because a count taken over the whole forest is itself a
disclosure. They add no authority everything in them is reachable node by
node through `look`/`move`/`scan`; what they add is a shape you can ask for
in one call. Like the Catalog itself they are **derived**: a consumer that
finds one stale reindexes rather than reconciling.

### Putting documents in (J.8)

```bash
curl -sX POST localhost:8800/v1/forests/handbook/ingest \
     -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
     -d '{"mode":"upload","dest":"policies",
          "files":[{"name":"expenses.md","text":"# Expenses\n…"}]}'
```

Four modes: `upload` sends the documents themselves, `compose` sends one
authored document as `{title, text}` (the console's Write tab), `adopt`
mirrors a directory the Station host can read, and `sync` re-reads what was
adopted. Authored prose is a source like any other: it walks the same
converters, curation and commits, so there is no second write path with its
own idea of what a passport is. All of them need the `ingest` capability
and a `dest` inside the caller's scope —
a principal who may not read a subtree must not be able to write into it.

Naming a **host path** additionally needs `admin`: that path is read with
the Station's filesystem access, not the caller's, so `ingest` alone would
quietly become arbitrary read access to the container. `upload` needs no
such privilege because the caller supplies the bytes.

`compose` takes two calls (J.8.1). Send `stage: true` and the whole pipeline
runs converter, curation, closed-candidate proposals and stops at the
plant, returning the draft it *would* have planted, each proposed link named
by the title of what it points at. Send that draft back as `draft` and it is
accepted: the approved passport enters as an `on_curate` hook, so the plant
and the commit are the ones every adopted file gets, and the model is not
asked to curate the document twice. A returned draft is a client payload, so
every field is re-validated summary re-clipped to the A.4 budget, tags
re-cleaned, and each link re-checked against G.4.2.1 (`related-to` only,
existing and in-scope targets, never a branch, capped at three, and pinned at
confidence 0.3 whoever kept it).

Uploads stage under the forest's `_derived/uploads/` outside git, one
stable directory per forest, so re-sending a filename is an *update* (the
G.8 hash diff) rather than a second node beside the first.

### MCP pointing an existing harness at a governed forest

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
# then narrow the scope from Studio → Access, or POST /v1/admin/grant
```

## People (J.2.3 / J.5.5)

Grants, passwords and API keys are three tables and one thought. **Studio →
People** is organised around the thought: one form onboards somebody —
who they are, what they may see, how they sign in, a token if they need one
— and afterwards their row owns every change to them.

```bash
curl -sX POST localhost:8800/v1/admin/people \
     -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
     -d '{"principal":"carlos",
          "grant":{"forest":"handbook","caps":["read","query"],"allow":["projects/"]},
          "password":"a long enough passphrase",
          "issue_key":{"label":"carlos laptop","expires_in_days":30}}'
```

The response reports `applied` and `refused` per step. It is a composite,
**not a new authority**: every step re-checks the rule that already governed
it, and a step the caller may not perform is refused without abandoning the
steps they may silently dropping half a submitted form is worse than
doing it or failing it. The order is normative: the grant lands first, so a
principal that did not exist a moment ago is administrable by the time its
password and key are created.

Access is rarely forest-shaped, so `grant` takes `forests` and
`revoke_access` takes a list one request for a group of forests or for all
of them, and one token that reads in each:

```bash
curl -sX POST localhost:8800/v1/admin/people \
     -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
     -d '{"principal":"reporting-service",
          "grant":{"forests":["handbook","sales","support"],"caps":["read"]},
          "issue_key":{"label":"nightly report"}}'
```

The scalar `forest` still works and means a one-element list. A set is a
convenience, never a relaxation: each forest is authorised, applied and
refused **on its own**, so an administrator of two of the three grants those
two and gets the third back in `refused` with its `forest` named.
`allow`/`deny` apply to every forest in the grant branch names are
forest-local, which is why Studio offers the branch picker only when a single
forest is ticked and grants each forest whole otherwise.

`GET /v1/admin/people` returns the person-shaped read the console uses:
identity, grants, whether a password exists, tokens, and last-seen already
filtered by J.3.2.

A token carries the permissions of the principal it belongs to and has none
of its own so "what can this token do" is answered by that person's
access, never by the token. Two consequences worth knowing:

- Minting or revoking a key for a principal requires `admin` on **every**
  forest that principal is granted, not merely on one. Otherwise the
  administrator of one forest could mint a credential that opens another.
  The console shows such a person without their credentials, for the same
  reason.
- Expired and revoked keys fail inside `authenticate()`, the single gate
  every surface passes through. A lifecycle enforced anywhere else is a
  lifecycle with a bypass.

There is **no separate super-administrator panel**, deliberately: one
console over one API, with capabilities deciding what appears. A second
panel would need a second way in.

**Administration is per forest (J.3.2).** Holding `admin` somewhere lets a
caller into a host route; it never entitles them to rows about forests they
do not administer. `/v1/admin/people`, `/v1/admin/principals` and `/v1/admin/audit` filter to
the administered set, so an administrator of one forest sees neither the
branch prefixes nor the read history of another. `/v1/admin/keys` is
stricter still a key spans forests, so issuing one needs `admin` on
*every* forest its principal holds.

*Known boundary:* providers (J.10) are a host resource shared by all
forests, so any administrator can edit them and removing one removes the
bindings of forests they may not administer.

Two properties worth knowing, because they are what make the scoping
trustworthy rather than decorative:

- **Out of scope is indistinguishable from absent.** A node you may not
  see reports the engine's own `E_NOT_FOUND`, byte for byte including
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
| `ingest` | curation, `curate` | care its output is the scent every later hop navigates by |
| `answer` | `answer` | speed and instruction-following over retrieved material |

Provider keys are **write-only**: the API accepts one and afterwards
reports only that a key is set. Saving with an empty key keeps the stored
one, so an endpoint typo can be fixed without re-pasting a secret.

**A provider you already configured arrives configured (J.10.1).** If the
deployment sets the variables this project already documents, the Station
publishes them at boot and the console shows them as *from the environment*:

```bash
export MONKEYLLM_LLM_ENDPOINT=https://openrouter.ai/api/v1
export MONKEYLLM_LLM_API_KEY=sk-or-…
export MONKEYLLM_LLM_PROVIDER=openrouter      # optional; host name if unset
export MONKEYLLM_EMBED_ENDPOINT=http://ollama.local/v1   # same, for the Gauntlet
```

Nobody is asked to paste that key into a form and it is **not copied into
the registry**: it lives in the process for as long as the process does and
is read when a call is made. The registry file is something you back up;
the environment is not. Rotation stays where it already was: change the
variable, restart.

Consequently these rows are read-only in the console an edit would be
undone by the next restart. Unset the variables to remove one; at the next
boot it becomes an ordinary console provider, keyless and visibly so,
rather than vanishing and taking its bindings with it.

**Choosing the model** uses the provider's own `/models`: pick from a
searchable list showing per-token prices where the provider states them
(OpenRouter does; Ollama and llama.cpp do not, and silence is reported as
silence rather than as free). Typing a name is still allowed catalogues
under-report but a model the provider does not advertise is flagged,
because a model id from *another* provider is the usual cause and it fails
only at the first call.

Binding a model cannot widen access: retrieval runs through `ScopedVine`
*before* the model is called, so it only ever sees what the caller could
already read. A `projects/`-scoped principal asking where the MixerLLM
author lives gets "the material does not contain that" the fact lives in
`people/`.

## Audit (J.4)

Reads land in the host registry (principal, forest, primitive, argument
**digest**, size, timestamp never bodies). Writes are git commits inside
the forest, amended to carry `station-principal: <id>`; the amended sha is
what the API returns, so the caller never holds one that no longer exists.

## How it is built

- **`policy.py`** `Policy` + `ScopedVine`, the single enforcement seam.
  The scoped read methods keep the engine's signatures, so the `harvest`
  composite inherits scoping instead of reimplementing it.
- **`registry.py`** principals, API keys (digests only), grants,
  providers, model bindings, audit. Never inside a forest (J.0).
- **`app.py`** Starlette routes; forest resolution reuses the engine's
  `ForestPool` (C.0) unchanged, path-escape guard included.
- **`mcp_surface.py`** the MCP mount. Stateless mode is a correctness
  choice: with sessions, a tool call can run in a task created during an
  earlier request, and the principal `ContextVar` would be the wrong one.
- **`inference.py`** the per-binding chat client and the composites.

All forest access is confined to one dedicated thread: SQLite connections
belong to the thread that opened them and the engine rightly does not
weaken that. A worker per forest is the scale-out step.

## What is not here yet

| Missing | Where it goes |
|---|---|
| Curation review queue for the 0.3-confidence proposals a *batch* ingest made (a composed post reviews before it lands, J.8.1) | T04 |
| Binary uploads (`.docx`, `.xlsx`) today they take the folder-mirror route | T09 |
| OIDC/SSO, per-token quotas, rate limits | T07 Phase C |
| `answer` over datasets (a tool-calling loop; today it honestly refuses aggregate questions) | J.10 follow-up |
| Per-node ACLs finer than the branch prefix | out of scope (J.12) |
