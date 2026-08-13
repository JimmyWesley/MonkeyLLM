# Install & deploy

English · [Português](../pt/install.md) · [Español](../es/install.md)

[← Handbook](./README.md)

The **Station** is the self-hostable host: one container serves the REST
API (`/v1`), the MCP surface (`/mcp`) and the **Studio** web console (`/`).
The Studio is a static bundle built into the image — there is no separate
frontend service to run. Remember what you are deploying: the console is a
window; the forests behind it are the product, and everything worth keeping
lives in volumes, so the container itself is disposable.

## Docker (recommended)

From the repository root:

```bash
cp .env.example .env      # optional but recommended — fill in what you use
docker compose up --build -d
docker compose logs station   # the first boot says how to get in
```

### The volumes

A crash, a rebuild or an update never loses data, because everything that
matters lives in named volumes:

| Volume | Mounted at | Holds |
|---|---|---|
| `forests` | `/forests` | every forest: markdown, its embedded git history, dataset `.db` payloads, `_derived/` caches |
| `registry` | `/registry` | the host registry (`station.db`): principals, API-key digests, grants, audit — one SQLite file |
| `models` | `/models` | GGUF weights for the optional local inference sidecars — multi-GB, kept out of the image |

> **Note** — a fourth volume, `documents`, is mounted at `/data` as the
> container's working directory and as a place to put files the Station may
> mirror. Swap it for a bind mount of your own folder
> (`./documents:/data`) and set `MONKEYLLM_INGEST_ROOTS=/data` to let the
> console read it — the allow-list is empty by default, and empty means
> none. See [Feeding the forest](./feeding.md).

### `.env` essentials

The compose file reads `.env` natively; anything left commented out falls
back to the code's own defaults. The annotated catalogue is
[`.env.example`](../../../.env.example) — the short version:

```dotenv
# Chat provider (any OpenAI-compatible /v1 endpoint):
MONKEYLLM_LLM_ENDPOINT=https://openrouter.ai/api/v1
MONKEYLLM_LLM_API_KEY=sk-or-your-key-here
MONKEYLLM_LLM_MODEL=google/gemma-3-12b-it

# Where the Station answers. Loopback by default — on a server, a reverse
# proxy reaches the container over the docker network, never the host port.
#STATION_PORT=8800
#STATION_BIND=127.0.0.1

# Hosts the MCP surface answers to; add your domain when serving through one.
#MONKEYLLM_STATION_ALLOWED_HOSTS=localhost,localhost:8800,127.0.0.1,127.0.0.1:8800
```

A provider configured this way arrives pre-configured and read-only in
*Studio → Models*, marked "from the environment" — the key is never copied
into the registry, and you rotate it by editing the variable and
restarting.

### First boot: the setup screen

Starting a Station mints nothing (spec J.2.5): the registry is exactly as
authoritative after boot as before it, and the first-boot log names the
console URL — `http://localhost:8800`. Open it, and a Station with nobody
in it shows the **setup screen** (spec J.2.4): pick a username and
password and you are the **owner** — administrator of every forest,
present and future, including before the first one exists. The screen also
offers to start you with a seeded demo forest, an empty one, or nothing at
all.

![The first-run setup screen, where the first person to arrive creates the owner](../assets/setup.png)

Setup exists only while the registry holds no credential, and it closes
permanently the moment it is used. From then on the console shows the
ordinary sign-in.

> **Note** — a Station published on a public URL with an unclaimed owner
> seat is a race against strangers. Point your domain at it and complete
> setup yourself before announcing the address; the first-boot log says as
> much.

### Browserless deploys: the bootstrap key

A headless server, CI, or an MCP-only client still needs a first door.
Start the Station once with `--bootstrap-key` (or set
`MONKEYLLM_STATION_BOOTSTRAP_KEY=1` — platform UIs with no argv field can
ask through the environment) and the boot mints **one** full-authority API
key, with the owner bit, and prints it in the log exactly once — only its
digest is stored, so save it before the logs rotate.

The flag and the setup screen are two doors onto the same one-shot window:
whichever you use spends it, and minting the key closes setup. A restart
with the flag on a Station that already has a way in mints nothing.

> **Note** — you do not need `MONKEYLLM_STATION_ADMIN` /
> `MONKEYLLM_STATION_PASSWORD`. Those two are a break-glass account held
> in the environment, compared at login and never stored; setting them
> *replaces* the setup screen rather than complementing it. When they are
> set, the first-boot log names the username to sign in as — it never
> prints the password.

## Local models

No external provider is needed: two llama.cpp sidecars ship behind compose
profiles, so chat and embeddings can run beside the Station.

```bash
docker compose --profile local-llm --profile local-embed up -d
```

The first start downloads the weights from Hugging Face into the `models`
volume (defaults: Qwen2.5-7B-Instruct Q4_K_M for chat, bge-m3 Q8_0 for
embeddings — override with `LLAMA_CHAT_HF` / `LLAMA_EMBED_HF`); later
starts reuse them. Then point the Station at the sidecars by their compose
service names, in `.env`:

```dotenv
MONKEYLLM_LLM_ENDPOINT=http://llm:8090/v1
MONKEYLLM_EMBED_ENDPOINT=http://embed:8091/v1
```

The Station reads these at startup, so the sidecar is only half the job —
set the variable **and** restart the Station. On a compose platform with
no `--profile` flag (Dokploy, Coolify), set `COMPOSE_PROFILES=local-llm,local-embed`
in the environment instead; Compose reads it on its own.

> **Note** — the sidecars run on CPU by default, which is fine for the 7B
> Q4 navigator. Leave the embedder off to keep entry search (`locate`) on
> its BM25-only contract — the vector layer is optional by design.

## From source

Install the engine and the Station, build the console once, and serve.

```bash
pip install -e .                # the engine (add ".[dev]" for the test suite)
pip install -e apps/station     # the host: REST, MCP, serves the Studio
```

```bash
cd apps/studio
npm ci && npm run build         # the console, built once into apps/studio/dist
```

The Station serves the bundle from `apps/studio/dist`; if you skip the
build, it answers with that exact hint instead of a console.

```bash
station serve --root /forests --registry /registry/station.db --port 8800 --writable
```

- `--root` — the forest registry directory (default `/forests`, or
  `MONKEYLLM_STATION_ROOT`).
- `--registry` — the host registry SQLite file (default
  `/registry/station.db`, or `MONKEYLLM_STATION_REGISTRY`).
- `--port` — default `8800`; `--host` defaults to `127.0.0.1`.
- `--writable` — accepts writes, ingest and forest creation. Without it
  the Station is read-only: reads keep working, writes are refused up
  front with `E_READONLY`.
- `--bootstrap-key` and `--no-warm` work here exactly as in Docker.

> **Note** — outside Docker, nothing loads `.env` for you (there is no
> python-dotenv). Load it into the shell yourself:
> `set -a; source .env; set +a`.

## Environment reference

These are the variables the Integrations console documents (*Studio →
Integrations → Environment reference*); the full annotated catalogue lives
in `.env.example`.

| Variable | Meaning |
|---|---|
| `MONKEYLLM_STATION_ADMIN`, `MONKEYLLM_STATION_PASSWORD` | Break-glass console login. Both must be set; never stored; rotate by restart. |
| `MONKEYLLM_STATION_ALLOWED_HOSTS` | Hosts the MCP surface answers. Add your domain, or `*` to skip the check. |
| `STATION_PORT` | Published port of the compose service — `8800` by default. |
| `MONKEYLLM_LLM_ENDPOINT`, `MONKEYLLM_LLM_API_KEY`, `MONKEYLLM_LLM_PROVIDER` | Chat provider, pre-configured and read-only under Models; the key is never copied into the registry. |
| `MONKEYLLM_LLM_MODEL`, `MONKEYLLM_LLM_MAX_TOKENS`, `MONKEYLLM_LLM_REASONING` | Default model id, response budget and reasoning mode for that provider. |
| `MONKEYLLM_EMBED_ENDPOINT`, `MONKEYLLM_EMBED_MODEL`, `MONKEYLLM_EMBED_API_KEY` | Embedding endpoint and model for the optional vector layer. Unset keeps entry search on its BM25-only contract. |
| `MONKEYLLM_S3_ENDPOINT` | S3-compatible endpoint for remote payloads — MinIO, R2. |

## Updating & read-only

**Updates** are a rebuild: `docker compose up --build -d` (or redeploy, on
a managed host). The image is replaced, the volumes are untouched, and
work continues where it was.

**Snapshot before you upgrade.** Each forest packages as a git bundle with
its full history (spec Part I):

```bash
docker compose exec station vine snapshot create --forest /forests/<name>
```

Back up the `registry` volume (one SQLite file) together with the
snapshots — grants and key digests belong with the forests they govern.
`vine snapshot restore <bundle>` brings a forest back.

**Read-only Station.** Remove `--writable` from the `command:` line and
redeploy: reads keep working, while writes, ingest and forest creation are
refused up front with `E_READONLY`. One deliberate exception: a read-only
Station still serves `POST /v1/admin/reindex` (spec J.13.3), because a
catalog rebuild writes only the disposable `_derived/` layer — an index the
Station could never repair would degrade forever.

## Where to go next

The Station is up and the setup screen is waiting. [First
access](./first-access.md) walks through claiming the owner seat, the
welcome tour, and your first forest — and from there,
[Connecting AI](./connecting-ai.md) is where the brain starts to grow.
