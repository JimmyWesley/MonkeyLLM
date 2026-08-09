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
**owner** — administrator of every forest, present and future, including
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
from *Studio → the empty state*, or over the API — `POST /v1/admin/forests`
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
set, `docker compose restart station` — the environment account is
re-granted on every boot, so the new forest is covered and the Studio login
works. From here on, forests are created from *Studio → Overview* or
`POST /v1/admin/forests` — no shell needed again.

## Dokploy

1. **Create the service** — in your Dokploy project: *Create Service →
   Compose*, pick this repository and branch, and set **Compose Path** to
   `./deploy/docker-compose.dokploy.yml`.
2. **Environment** — in the *Environment* tab, set what you use (the full
   catalogue with commentary is [.env.example](../.env.example)):

   ```dotenv
   MONKEYLLM_STATION_ALLOWED_HOSTS=monkeyllm.dev.example.com
   MONKEYLLM_LLM_ENDPOINT=https://openrouter.ai/api/v1
   MONKEYLLM_LLM_API_KEY=sk-or-...
   MONKEYLLM_LLM_MODEL=google/gemma-3-12b-it
   ```

3. **Domain** — in the *Domains* tab add your domain pointing at service
   `station`, container port `8800`, HTTPS on. Traefik reaches the
   container over `dokploy-network`; no host port is published.
4. **Deploy**, then open your domain. The setup screen is waiting: create
   the owner, choose whether to start with a demo forest, and you are in.
   No container terminal, no key from the logs, no `vine init`.

   Note the ordering — setup is open until somebody uses it, so point the
   domain at the service and complete it yourself before announcing the URL.
   The deployment logs still print a bootstrap API key on first boot; it is
   for scripted access, and it is not needed to reach the console.

Provider keys set this way arrive pre-configured in *Studio → Models*,
marked "from the environment", and are **never copied into the registry** —
rotate by editing the variable and redeploying.

### MCP clients through the domain

Point any MCP harness at `https://<your-domain>/mcp/` (streamable HTTP)
with an `Authorization: Bearer <key>` header. The MCP surface only answers
hosts listed in `MONKEYLLM_STATION_ALLOWED_HOSTS` — set it to your domain
as above (the compose file defaults it to `*`, which skips the host check;
every request still needs an API key). REST and the Studio are unaffected.

## Updates, restarts, persistence

- **Update**: redeploy (Dokploy) or `docker compose up --build -d` — the
  image is rebuilt, the volumes are untouched, work continues where it was.
- **Crash**: `restart: unless-stopped` brings the container back; state is
  in the volumes, not the container.
- **Backup**: per forest, `vine snapshot create` produces a git bundle with
  full history (spec Part I); back up the `registry` volume (one SQLite
  file) together with the snapshots — grants and key digests belong with
  the forests they govern.

## Optional local inference

No external LLM provider needed — two llama.cpp sidecars are included
behind compose profiles:

```bash
docker compose --profile local-llm --profile local-embed up -d
```

First start downloads the weights from Hugging Face into the `models`
volume (defaults: Qwen2.5-7B-Instruct Q4_K_M for chat, bge-m3 Q8_0 for
embeddings — override with `LLAMA_CHAT_HF` / `LLAMA_EMBED_HF`); later
starts reuse them. Then point the Station at the sidecars in `.env` /
Dokploy environment:

```dotenv
MONKEYLLM_LLM_ENDPOINT=http://llm:8090/v1
MONKEYLLM_EMBED_ENDPOINT=http://embed:8091/v1
```

On Dokploy, if the UI cannot pass `--profile`, delete the `profiles:` lines
in the compose file to always run the sidecars. They run on CPU by default;
leave the embedder off to keep `locate` on its BM25-only Phase 0 contract.

## Read-only Station

Remove `--writable` from the `command:` line and redeploy: reads keep
working, while writes, ingest and forest creation are refused up front with
`E_READONLY` (spec J).
