<div align="center">
  <img src="docs/logo.png" alt="MonkeyLLM Logo" width="120"/>
</div>

# MonkeyLLM

A knowledge forest navigable by a small language model: markdown nodes with
curated, scent-carrying passports plus lightweight indexes, traversed
through **Vine**'s MCP primitives — the agent *navigates* to what it needs
instead of being handed a retrieval dump. The **Station** (spec Part J)
wraps the untouched engine with identity, scoped policy, audit and the
**Studio** web console, so a forest can be a governed shared asset instead
of a personal directory.

The spec is the truth: the latest `docs/monkeyllm-spec-v*.md` is normative;
code follows it, never the other way around.

## Layout

| Path | What lives there |
|---|---|
| `src/monkeyllm/` | the engine: `vine` CLI, 10 primitives, harvest, Gardener (ingest), Ranger (maintenance), catalog, Canopy |
| `apps/station/` | the deployable host: REST `/v1`, MCP `/mcp`, serves the Studio |
| `apps/studio/` | the web console (React/Vite, built into the Station image) |
| `forests/` | generated forests (gitignored except `forests/scripts/`) — rebuild, never edit |
| `bench/` | Monkey Bench: chunker, RAG baselines, runner |
| `scripts/` | infra + measurement (local models, bench, curation metrics) |
| `docs/` | the spec and design notes |
| `tasks/` | backlog, one file per task |

## Quick start (development)

```bash
pip install -e ".[dev]" && pip install -e apps/station
python -m pytest -q
python forests/scripts/build_fixture.py
python -m monkeyllm.cli validate --forest forests/forest-fixture
```

## Run the whole environment (Docker)

One container serves frontend and backend; data persists in named volumes:

```bash
cp .env.example .env   # fill in what you use
docker compose up --build -d
```

See [deploy/README.md](deploy/README.md) for the full walkthrough,
including Dokploy and optional local llama.cpp inference.

## License

Two licenses, split along the line the architecture already draws:

- **Engine** (`src/monkeyllm/`, the spec, the benchmark, the tooling) —
  [Apache-2.0](LICENSE). The MCP contract is meant to spread.
- **Host** (`apps/station/`, `apps/studio/`) —
  [AGPL-3.0-only](apps/station/LICENSE). Self-hosting is free and
  unrestricted; offering it as a managed service means opening your stack.

See [LICENSING.md](LICENSING.md) for the full map, the commercial option and
the DCO requirement for contributions.
