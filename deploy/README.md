# Deploying MonkeyLLM

One container runs everything (spec J.6): the **Station** serves the REST
API (`/v1`), the MCP surface (`/mcp`) and the **Studio** web console (`/`) —
the Studio is a static React bundle compiled into the image at build time,
so there is no separate frontend service to run.

Everything worth keeping lives in named volumes, so a crash, a rebuild or
an update never loses data:

| Volume | Mounted at | Holds |
|---|---|---|
| `forests` | `/forests` | every forest: markdown, its embedded git history, dataset `.db` payloads, `_derived/` caches |
| `registry` | `/registry` | the host registry (`station.db`): principals, API-key digests, grants, audit |
| `models` | `/models` | GGUF weights for the optional local inference services (multi-GB, out of the image) |

## Quick start on any Docker host

From the repository root:

```bash
cp .env.example .env      # uncomment and fill in what you use
```

```bash
docker compose up --build -d
```

Then open `http://localhost:8800`. A Station with nobody in it shows the
**setup screen** (spec J.2.4): pick a username and password and you are the
**owner** administrator of every forest, present and future, including
before the first one exists. The screen also offers to start you with a
demo forest, an empty one, or nothing at all.

Setup exists only while the registry holds no credential, and it closes
permanently the moment it is used. From then on the console shows the
ordinary sign-in.

**You do not need `MONKEYLLM_STATION_ADMIN`.** Those two variables are a
break-glass account held in the environment; setting them *replaces* the
setup screen rather than complementing it, because two doors competing for
the first identity is a race nobody wants on a public URL. Leave them unset
unless you specifically want a credential that lives in the environment and
is rotated by restarting.

### The first forest on a clean deployment

Setup will offer to create it. If you skipped that, the owner creates one
from *Studio → the empty state*, or over the API `POST /v1/admin/forests`
accepts the owner on an empty registry precisely so no deployment needs a
shell to become usable.

The container CLI remains available for scripted provisioning:

```bash
docker compose exec station vine init --forest /forests/handbook --title "Handbook"
```

Then give yourself access, either way:

```bash
docker compose exec station station key --principal admin --forest handbook --caps read,query,write,tend,ingest,admin
```

prints a fresh full-capability API key; or, if the break-glass account is
set, `docker compose restart station` the environment account is
re-granted on every boot, so the new forest is covered and the Studio login
works. From here on, forests are created from *Studio → Overview* or
`POST /v1/admin/forests` no shell needed again.

## Dokploy

There is **one compose file** and it is the same one you run on a laptop
([`docker-compose.yml`](../docker-compose.yml)). Everything that differs
between the two lives in variables, so a deployment cannot drift away from
the file that gets tested.

1. **Create the service** in your Dokploy project: *Create Service →
   Compose*, pick this repository and branch, and leave **Compose Path** at
   `./docker-compose.yml`.
2. **Environment** in the *Environment* tab, set what you use (the full
   catalogue with commentary is [.env.example](../.env.example)):

   ```dotenv
   # The two that make it a deployment: join the network Traefik lives on.
   STATION_NETWORK=dokploy-network
   STATION_NETWORK_EXTERNAL=true

   MONKEYLLM_STATION_ALLOWED_HOSTS=monkeyllm.dev.example.com
   MONKEYLLM_LLM_ENDPOINT=https://openrouter.ai/api/v1
   MONKEYLLM_LLM_API_KEY=sk-or-...
   MONKEYLLM_LLM_MODEL=google/gemma-3-12b-it
   ```

   Without those first two the containers come up on a private network of
   their own and Traefik has nothing to route to the deploy succeeds and
   the domain answers 502, which is the one failure here that does not
   explain itself.

3. **Domain** in the *Domains* tab add your domain pointing at service
   `station`, container port `8800`, HTTPS on. Traefik reaches the container
   over `dokploy-network`. The host port stays bound to loopback, so the
   Station is never answering in the clear on the public IP.
4. **Deploy**, then open your domain. The setup screen is waiting: create
   the owner, choose whether to start with a demo forest, and you are in.
   No container terminal, no key from the logs, no `vine init`.

   Note the ordering setup is open until somebody uses it, so point the
   domain at the service and complete it yourself before announcing the URL.
   The deploy log says as much on first boot: it prints the console URL and
   nothing else, because starting a Station mints no credential (J.2.5).
   If you would rather have a key than a browser scripted access, an MCP
   client, no domain yet set `MONKEYLLM_STATION_BOOTSTRAP_KEY=1` for the
   first boot and the log carries the key instead. It is shown once, it
   carries full authority, and it closes the setup screen: the two are one
   window, and whichever you use spends it.

Provider keys set this way arrive pre-configured in *Studio → Models*,
marked "from the environment", and are **never copied into the registry** —
rotate by editing the variable and redeploying.

### MCP clients through the domain

Point any MCP harness at `https://<your-domain>/mcp/` (streamable HTTP)
with an `Authorization: Bearer <key>` header. The MCP surface only answers
hosts listed in `MONKEYLLM_STATION_ALLOWED_HOSTS`, and the compose file
defaults it to **localhost only** so **a deployment behind a domain
refuses every MCP request until you name the domain there**. Nothing else
goes red when that happens: REST serves, Studio opens, `/v1/health` says
`ok`, and the client reports `Failed to connect`.

Set it to your domain (add `:443` too if your proxy passes the port
through), and never to `*` — that turns off the `Origin` check as well:

```dotenv
MONKEYLLM_STATION_ALLOWED_HOSTS=monkeyllm.dev.example.com,localhost,127.0.0.1
```

**Smoke-test the surface, not just the container.** A green deploy proves
REST answers; only this proves MCP does:

```bash
BASE=https://monkeyllm.dev.example.com
KEY=mk_...

# 1) the host verdict, from the domain itself — `host_allowed: false` is
#    the whole diagnosis, and it needs no key
curl -s $BASE/v1/health | jq .mcp

# 2) the handshake — expect 200; a 421 answers with the reason
curl -s -X POST $BASE/mcp/ \
  -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}'
```

The Station also warns at boot (`docker compose logs station`) when its
allow-list names local addresses only. REST and the Studio are unaffected
by any of this — which is exactly why the failure is easy to miss.

### A CDN in front can refuse clients you did not think about

If the Station sits behind a WAF (Cloudflare and friends), its bot rules
apply before anything here does. Measured on one deployment: identical
requests answered 200 for `python-httpx`, `python-requests`, `node-fetch`
and an empty user agent, and **403 for `Python-urllib/3.12`** — the
standard library's default. MCP clients were unaffected (the Python SDK
uses httpx), but any integration or CI script written with `urllib` sees a
403 that carries the CDN's HTML, not the Station's envelope, and therefore
reads like a bad key. Allow-list what you script with, or send a user agent
of your own.

## Updates, restarts, persistence

- **Update**: redeploy (Dokploy) or `docker compose up --build -d` the
  image is rebuilt, the volumes are untouched, work continues where it was.
- **Crash**: `restart: unless-stopped` brings the container back; state is
  in the volumes, not the container.
- **Backup**: per forest, `vine snapshot create` produces a git bundle with
  full history (spec Part I); back up the `registry` volume (one SQLite
  file) together with the snapshots grants and key digests belong with
  the forests they govern.

## Optional local inference

No external LLM provider needed two llama.cpp sidecars are included
behind compose profiles:

```bash
docker compose --profile local-llm --profile local-embed up -d
```

First start downloads the weights from Hugging Face into the `models`
volume (defaults: Qwen2.5-7B-Instruct Q4_K_M for chat, bge-m3 Q8_0 for
embeddings override with `LLAMA_CHAT_HF` / `LLAMA_EMBED_HF`); later
starts reuse them. Then point the Station at the sidecars in `.env` /
Dokploy environment:

```dotenv
MONKEYLLM_LLM_ENDPOINT=http://llm:8090/v1
MONKEYLLM_EMBED_ENDPOINT=http://embed:8091/v1
```

On Dokploy there is no `--profile` flag to pass: the UI runs a plain
`docker compose up`, which starts every service **except** the profiled
ones so a deploy that shows only `station` is the profiles working as
designed, not a failed sidecar. Turn them on by adding this to the
Environment tab, which Compose reads on its own:

```dotenv
COMPOSE_PROFILES=local-embed        # or: local-llm,local-embed
```

Deleting the `profiles:` lines from the compose file has the same effect
and is the fallback if the variable does not take. Either way the sidecar
is only half the job the Station reads `MONKEYLLM_EMBED_ENDPOINT` at
startup, so it needs the variable above **and** a restart before `locate`
goes hybrid. The first start is slow and quiet while it pulls the GGUF
into the `models` volume; `docker compose logs embed` shows the progress.

They run on CPU by default; leave the embedder off to keep `locate` on its
BM25-only Phase 0 contract.

## Read-only Station

Remove `--writable` from the `command:` line and redeploy: reads keep
working, while writes, ingest and forest creation are refused up front with
`E_READONLY` (spec J).
