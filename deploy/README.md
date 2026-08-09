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

```bash
docker compose logs station | grep "API key"
```

The last command shows the bootstrap `admin` key the first boot mints —
store it, it is printed exactly once and only its digest is kept. Open
`http://localhost:8800` for the Studio. Setting `MONKEYLLM_STATION_ADMIN`
and `MONKEYLLM_STATION_PASSWORD` in `.env` additionally enables the
console's login form (break-glass account, never stored).

### The first forest on a clean deployment

Spec J.7 lets a deployment reach its *second* forest without shell access:
creating one through the API requires `admin` on an existing forest, so on
an empty volume the first forest is born with the engine's own CLI inside
the container:

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
   MONKEYLLM_STATION_ADMIN=jimmy
   MONKEYLLM_STATION_PASSWORD=something long and unguessable
   MONKEYLLM_STATION_ALLOWED_HOSTS=monkeyllm.dev.example.com
   MONKEYLLM_LLM_ENDPOINT=https://openrouter.ai/api/v1
   MONKEYLLM_LLM_API_KEY=sk-or-...
   MONKEYLLM_LLM_MODEL=google/gemma-3-12b-it
   ```

3. **Domain** — in the *Domains* tab add your domain pointing at service
   `station`, container port `8800`, HTTPS on. Traefik reaches the
   container over `dokploy-network`; no host port is published.
4. **Deploy** — the first deployment's logs print the bootstrap `admin`
   API key once. Store it.
5. **First forest** — same as locally, but through Dokploy's container
   terminal (*... → Terminal* on the `station` service): run the
   `vine init` / `station key` commands from
   [the first-forest section](#the-first-forest-on-a-clean-deployment).

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
