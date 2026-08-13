<div align="center">
  <img src="docs/logo.png" alt="MonkeyLLM Logo" width="120"/>
</div>

# MonkeyLLM

**This repository is not an application. It is a knowledge engine — a new
way to query data.**

Knowledge lives in a **forest**: a git-versioned tree of markdown nodes,
each carrying a curated, scent-bearing passport. An AI does not get handed
a retrieval dump — it **navigates**: drops in through search, follows
typed edges, reads exactly the node it needs, and plants what it learns.
Successful hunts deposit pheromone and mint shortcut links, so the corpus
itself learns from use.

The number that made us write it down: on a benchmark where **every
question needs ≥3 chained hops**, the *same* 12B local model scores
**0 / 11 as a classic top-k RAG reader** and **11 / 11 (100%) as a forest
navigator** — at **0.58×** the token cost per correct answer of an
iterative-RAG baseline, on a single consumer GPU. If your first reaction
is *"I need to test whether this actually serves my case"* — good. Every
number is reproducible from committed scripts, and the whole design is
written down in [the paper](paper/monkeyllm-paper.md).

Everything else in this repository exists *around* that engine. The
**Studio** console you will see in screenshots is not the product — it is
the **management layer**: the window where people watch, govern and teach
what the engine serves.

The spec is the truth: the latest `docs/monkeyllm-spec-v*.md` is
normative; code follows it, never the other way around.

## The engine, inside your own code

The engine is a plain Python package (**Apache-2.0**) with no host, no
server and no UI attached. Point it at a folder and you have a forest;
operate it from your own Python:

```bash
pip install -e .                                # the monkeyllm package + vine CLI
vine init --forest ./brain --title "My brain"   # an empty forest, git and all
```

```python
from monkeyllm import Vine
from monkeyllm.harvest import harvest

vine = Vine("./brain")
vine.plant({"id": "inbox/_index", "type": "branch", "parent": "_index",
            "title": "Inbox", "summary": "Loose notes before they find a branch."})
vine.plant({"id": "inbox/first-note", "type": "note", "parent": "inbox/_index",
            "title": "First note", "summary": "Where this brain begins.",
            "body": "Planted from my own code."})

vine.locate("where does this brain begin?")   # ranked entry points, BM25, zero embeddings
harvest(vine, "first note")                   # one-shot retrieval: evidence + snippets, zero LLM
```

Every primitive an agent uses rides that same object — `locate`, `look`,
`move`, `pick`, `scan`, `sniff`, `query`, `plant`, `graft`, `tend` — each
token-budgeted, each truncation explicit. The Gardener (`vine adopt` /
`vine sync`) mirrors an existing document tree into a forest, and the
Ranger (`vine ranger`) keeps it healthy over time.

And the same forest speaks **MCP** to any agent, straight from the CLI:

```bash
vine serve --forest ./brain                    # stdio MCP server
vine serve --forest ./brain --transport http   # or over HTTP
```

Claude Code, or any MCP-capable runtime, then holds the forest's tools —
no host, no accounts, your machine, your ecosystem.

## Quick start (development)

```bash
pip install -e ".[dev]" && pip install -e apps/station
python -m pytest -q
python forests/scripts/build_fixture.py
python -m monkeyllm.cli validate --forest forests/forest-fixture
```

## The management layer (Station + Studio)

When a forest must be a **shared, governed asset** instead of a personal
directory, the **Station** (spec Part J) wraps the untouched engine with
identity, per-forest policy, audit and model bindings — REST under `/v1`,
MCP under `/mcp` — and serves the **Studio**, the web console:

<div align="center">
  <img src="docs/guide/assets/overview.png" alt="The Studio console — the management layer over the engine" width="720"/>
</div>

Ask questions that arrive with their sources, walk the tree as a living
graph, query datasets in SQL, feed the forest from uploads and the browser
Clipper, grant scoped access, and hand your own AI the skill that makes
the forest its persistent memory. The console is where the engine's
possibilities become visible — but whatever it shows, an API client
holding the same key could fetch: there is no privileged path.

## Documentation

**[The MonkeyLLM Handbook](docs/guide/README.md)** — install it, sign in
for the first time, use and feed the forest, connect your own AI over MCP
(including the Claude Code skill the Studio generates), and govern the
deployment. English, Português and Español, with screenshots.

## The paper

**[MonkeyLLM: Stigmergic Navigation of Knowledge Forests](paper/monkeyllm-paper.md)**
— replacing retrieval-augmented generation with agentic foraging by small
language models. The forest, the scent contract, the ten budgeted
primitives, the pheromone economy, and the **Forest Principle** — *spend
intelligence on the environment so you can spend less on the model* —
with every benchmark number reproducible from this repository.

## Layout

| Path | What lives there |
|---|---|
| `src/monkeyllm/` | **the engine**: `vine` CLI, 10 primitives, harvest, Gardener (ingest), Ranger (maintenance), catalog, Canopy |
| `apps/station/` | the deployable host: REST `/v1`, MCP `/mcp`, serves the Studio |
| `apps/studio/` | the web console (React/Vite, built into the Station image) |
| `apps/clipper/` | the browser extension: clip the page you are reading into a forest |
| `paper/` | the paper: design, vocabulary, benchmarks, authorship |
| `forests/` | generated forests (gitignored except `forests/scripts/`) — rebuild, never edit |
| `bench/` | Monkey Bench: chunker, RAG baselines, runner |
| `scripts/` | infra + measurement (local models, bench, curation metrics) |
| `docs/` | the spec, the handbook (`docs/guide/`) and design notes |
| `tasks/` | backlog, one file per task |

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
- **Host** (`apps/station/`, `apps/studio/`, `apps/clipper/`) —
  [AGPL-3.0-only](apps/station/LICENSE). Self-hosting is free and
  unrestricted; offering it as a managed service means opening your stack.

See [LICENSING.md](LICENSING.md) for the full map, the commercial option and
the DCO requirement for contributions.
