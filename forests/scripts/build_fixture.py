# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Build the Phase 0 test forest (forests/forest-fixture/).

Deterministic: ~90+ nodes, 12 branches, 1 SQLite dataset, cross-links
designed to support the 10 multi-hop demo questions. Run:

    python forests/scripts/build_fixture.py [--out forests/forest-fixture]
"""

from __future__ import annotations

import argparse
import random
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from monkeyllm.indexer import count_coverage, entry_line  # noqa: E402
from monkeyllm.parser import serialize_node  # noqa: E402

TODAY = "2026-06-10"
CREATED = "2026-06-01"

SCHEMA_MD = """---
id: _meta/schema
type: note
title: Forest dialect
summary: Node and edge types valid in this forest. New types are declared here before first use; the Vine rejects anything not declared.
created: 2026-06-01
updated: 2026-06-10
---

# Forest dialect

## Node types (type)

| `type` | Description | Harvest verb |
|---|---|---|
| `branch` | Index file (_index.md) of a folder | look |
| `note` | Free-text knowledge | pick |
| `document` | Converted document (PDF/DOCX origin) | pick |
| `dataset` | Tabular data (sibling SQLite) | query |
| `entity` | Person, organization, product, place | pick |
| `concept` | Definition / technical term | pick |
| `event` | Dated fact (meeting, decision, release) | pick |
| `media` | Image/audio/video with description | pick |

## Edge types (rel)

| `rel` | Inverse | Semantics |
|---|---|---|
| `part-of` | `contains` | Logical hierarchy |
| `related-to` | `related-to` | Generic association (symmetric) |
| `mentioned-in` | `mentions` | Entity cited in a document |
| `author` | `author-of` | Authorship |
| `compared-with` | `compared-with` | Technical contrast (symmetric) |
| `derived-from` | `origin-of` | Provenance |
| `same-as` | `same-as` | Soft merge of duplicate entities |
| `discovered-shortcut` | — | The monkey's shout (created by graft) |
| `succeeds` | `precedes` | Temporal order |
"""

# ---------------------------------------------------------------------------
# Node inventory. Each banana: (id, type, title, summary, tags, links, body)
# links: list of (rel, target). Bodies use ## sections so outline/pick work.
# ---------------------------------------------------------------------------

N = []  # populated below


def node(id, type, title, summary, tags=(), links=(), body="", **extra):
    N.append(
        {
            "id": id,
            "type": type,
            "title": title,
            "summary": summary,
            "tags": list(tags),
            "links": [{"rel": r, "target": t} for r, t in links],
            "body": body,
            "extra": extra,
        }
    )


# -- people ----------------------------------------------------------------

PEOPLE = [
    ("jimmy-wesley", "Jimmy Wesley",
     "CTO of Tropicália Tech and author of the MixerLLM architecture. Lives in Recife (PE). Leads local inference and the MonkeyLLM paper.",
     ["cto", "inference"], [("author", "projects/mixerllm/architecture"), ("related-to", "organizations/tropicalia-tech")],
     "## Profile\n\nCTO and co-founder of Tropicália Tech. Lives in **Recife, Pernambuco**. Expert in local SLM inference and quantization.\n\n## Responsibilities\n\n- Architecture of the [[projects/mixerllm/architecture|MixerLLM]]\n- Technical direction of [[projects/monkeyllm/vision|MonkeyLLM]]\n- Relationship with [[organizations/ufpe]] for the 2026 workshop"),
    ("elena-souza", "Elena Souza",
     "CEO and co-founder of Tropicália Tech. Responsible for strategic sales; closed the DataCoop contract in February 2026. Based in São Paulo.",
     ["ceo", "sales"], [("related-to", "organizations/tropicalia-tech"), ("mentioned-in", "events/2026-02-datacoop-contract")],
     "## Profile\n\nCEO and co-founder of Tropicália Tech, based in São Paulo. Led the negotiation of the [[organizations/datacoop]] contract.\n\n## Background\n\nFormer commercial director at an industrial IoT scale-up. MBA from FGV."),
    ("ana-castro", "Ana Castro",
     "Data engineer; owner of the sales pipeline and the Q1 2026 dataset. Maintains the ERP export and the sales report query manual.",
     ["data", "sales"], [("author", "sales/report-q1-2026"), ("related-to", "organizations/tropicalia-tech")],
     "## Profile\n\nData engineer responsible for the monthly ERP export to the forest and for the quality of [[sales/report-q1-2026]].\n\n## Notes\n\nDefined the macro-region convention used in the `region` column."),
    ("bruno-lima", "Bruno Lima",
     "Researcher in stigmergy and ant colony optimization. Wrote the digital pheromone notes and reviews the related work chapter of the paper.",
     ["research", "stigmergy"], [("author", "projects/monkeyllm/pheromone"), ("related-to", "concepts/stigmergy")],
     "## Profile\n\nPartner researcher from [[organizations/lab-amazonia]]. Works with ACO (ant colony optimization) since 2019.\n\n## Contributions\n\nDesigned the whisper/shout mechanism of [[projects/monkeyllm/pheromone]]."),
    ("carla-mendes", "Carla Mendes",
     "Product manager of MonkeyLLM. Defines the phase 0-4 roadmap and the paper's bilingual glossary. Interface with beta clients.",
     ["pm", "product"], [("related-to", "projects/monkeyllm/vision")],
     "## Profile\n\nPM of MonkeyLLM. Maintains the roadmap and prioritizes the Monkey Bench as the decision arbiter.\n\n## Notes\n\nAdvocated for Obsidian compatibility as a marketing feature."),
    ("diego-rocha", "Diego Rocha",
     "Infrastructure engineer: workstation 3090, edge cluster and the Docker deploy of the Vine. Manages the R2 mirror and the forest volume.",
     ["infra", "docker"], [("author", "infra/docker-deploy"), ("related-to", "infra/workstation-3090")],
     "## Profile\n\nSRE at Tropicália Tech. Maintains the [[infra/workstation-3090]] and the compose for [[infra/docker-deploy]].\n\n## On-call\n\nResponsible for R2 sync and forest backups."),
    ("fabio-nunes", "Fábio Nunes",
     "Inference engineer; implemented the MixerLLM block-loop and the latency benchmarks on the 3090. Maintains the llama.cpp server.",
     ["inference", "benchmarks"], [("author", "projects/mixerllm/block-loop"), ("related-to", "projects/mixerllm/benchmarks")],
     "## Profile\n\nInference engineer focused on quantized SLMs (Q4/Q5) and continuous batching.\n\n## Contributions\n\nAuthor of [[projects/mixerllm/block-loop]] and the numbers in [[projects/mixerllm/benchmarks]]."),
    ("helena-prado", "Helena Prado",
     "Product designer; responsible for the visual identity of monkeyllm.com and the L0-L4 layered architecture diagrams.",
     ["design"], [("related-to", "projects/monkeyllm/vision")],
     "## Profile\n\nDesigner. Created the forest visual system (branches, bananas, trails) used on the site and in the paper."),
    ("marcos-tavares", "Marcos Tavares",
     "Data scientist at DataCoop, technical contact for the February contract. Validates the MonkeyLLM pilot over the cooperative's data.",
     ["client", "data"], [("related-to", "organizations/datacoop")],
     "## Profile\n\nTechnical contact for the pilot at [[organizations/datacoop]]. Reports Vine bugs via shared channel."),
    ("rita-azevedo", "Rita Azevedo",
     "Professor at UFPE, advisor for the May 2026 workshop and co-author of the paper. Expert in information retrieval and BM25.",
     ["academia", "ir"], [("related-to", "organizations/ufpe"), ("related-to", "concepts/bm25")],
     "## Profile\n\nAssociate professor at [[organizations/ufpe]]. Co-author of the MonkeyLLM paper; reviews the baselines section."),
]
for slug, title, summary, tags, links, body in PEOPLE:
    node(f"people/{slug}", "entity", title, summary, tags, links, body, entity_kind="person")

# -- organizations -------------------------------------------------------------

ORGS = [
    ("tropicalia-tech", "Tropicália Tech",
     "Company behind MixerLLM and MonkeyLLM. Headquarters in São Paulo, R&D in Recife. CEO: Elena Souza; CTO: Jimmy Wesley. 18 people.",
     [("related-to", "people/elena-souza"), ("related-to", "people/jimmy-wesley")],
     "## About\n\nFounded in 2024. Products: [[products/mixerllm-engine]], [[products/monkeyllm-server]] and the edge hardware line ([[products/sensor-x]], [[products/gateway-m]], [[products/edge-kit]]).\n\n## Key people\n\n- CEO: [[people/elena-souza]]\n- CTO: [[people/jimmy-wesley]]"),
    ("datacoop", "DataCoop",
     "Agricultural data cooperative, MonkeyLLM pilot client. Contract signed in February 2026 including 200 Sensor X units and the memory pilot.",
     [("related-to", "people/marcos-tavares"), ("mentioned-in", "events/2026-02-datacoop-contract")],
     "## About\n\nCooperative with 40 associated farms in Central-West Brazil. Buys edge sensors and contracted the MonkeyLLM pilot as agronomist memory.\n\n## Technical contact\n\n[[people/marcos-tavares]]"),
    ("lab-amazonia", "Lab Amazônia",
     "Independent research laboratory in bio-inspired systems; origin of Bruno Lima and partner in the stigmergy mechanism.",
     [("related-to", "people/bruno-lima")],
     "## About\n\nResearch lab in bio-inspired computing (ants, bees, stigmergy). Informal research partnership since 2025."),
    ("ufpe", "UFPE",
     "Federal University of Pernambuco; academic partner for the paper. Hosted the May 2026 workshop on index-based navigation.",
     [("related-to", "people/rita-azevedo"), ("mentioned-in", "events/2026-05-ufpe-workshop")],
     "## About\n\nAcademic partner via [[people/rita-azevedo]] (CIn/UFPE). Co-authorship on the paper and student researchers on the Monkey Bench."),
]
for slug, title, summary, links, body in ORGS:
    node(f"organizations/{slug}", "entity", title, summary, ["organization"], links, body, entity_kind="organization")

# -- products ------------------------------------------------------------------

PRODUCTS = [
    ("sensor-x", "Sensor X",
     "Edge sensor for agricultural telemetry, SKU A-101. Revenue leader in Q1 2026; sold in batches to cooperatives.",
     [("related-to", "sales/report-q1-2026")],
     "## Spec\n\n- **SKU:** A-101\n- Soil and climate telemetry, LoRa, 2-year battery.\n\n## Commercial\n\nSold in lots of 50; main item in the [[events/2026-02-datacoop-contract]] contract."),
    ("gateway-m", "Gateway M",
     "Field gateway that aggregates sensors via LoRa and runs lightweight inference, SKU B-202. Higher margin than Sensor X.",
     [("related-to", "sales/report-q1-2026")],
     "## Spec\n\n- **SKU:** B-202\n- Aggregates up to 200 sensors; runs quantized SLM for local alerts."),
    ("edge-kit", "Edge Kit",
     "Quick-deployment bundle (1 Gateway M + 10 Sensor X + support), SKU C-303. Preferred channel: partners.",
     [("related-to", "sales/report-q1-2026")],
     "## Spec\n\n- **SKU:** C-303\n- Entry bundle for mid-size farms."),
    ("mixerllm-engine", "MixerLLM Engine",
     "Hot/cold inference runtime with mixer-lang; licensed as SDK. In beta with two clients.",
     [("derived-from", "projects/mixerllm/architecture")],
     "## Spec\n\nSDK of the runtime described in [[projects/mixerllm/architecture]]. Closed beta."),
    ("monkeyllm-server", "MonkeyLLM Server",
     "MCP server (Vine) + forest as a memory product for agents. Distribution via Docker Compose and pip.",
     [("derived-from", "projects/monkeyllm/vision")],
     "## Spec\n\nMonkeyLLM entry product: any MCP client can plug the forest as memory."),
]
for slug, title, summary, links, body in PRODUCTS:
    node(f"products/{slug}", "entity", title, summary, ["product"], links, body, entity_kind="product")

# -- concepts -------------------------------------------------------------------

CONCEPTS = [
    ("rag", "RAG",
     "Retrieval-Augmented Generation: top-k chunk retrieval by vector similarity injected into context. Main baseline for the Monkey Bench.",
     [("compared-with", "projects/monkeyllm/vision")],
     "## Definition\n\nRetrieves chunks by similarity and injects them into the prompt. Structurally fails on multi-hop questions and large tabular data.\n\n## In the project\n\nMandatory baseline of [[projects/monkeyllm/monkey-bench]]."),
    ("graphrag", "GraphRAG",
     "Microsoft RAG variant that builds an entity and community graph for hierarchical summarization. Direct related work for the paper.",
     [("compared-with", "projects/monkeyllm/vision")],
     "## Definition\n\nBuilds a knowledge graph + community summaries. Indexes once; does not learn from use — the central difference from MonkeyLLM."),
    ("raptor", "RAPTOR",
     "Recursive tree of summaries via clustering for multi-level abstract retrieval. Related work in the paper.",
     [], "## Definition\n\nRecursive summaries in a tree. Similar to MonkeyLLM branches, but static and without agent navigation."),
    ("speculative-decoding", "Speculative decoding",
     "Acceleration technique where a draft model proposes tokens that the target model verifies. Technical contrast for the MixerLLM block-loop.",
     [("compared-with", "projects/mixerllm/architecture")],
     "## Definition\n\nDraft model proposes, target verifies in parallel. The MixerLLM block-loop inverts the relationship: the hot model delegates semantic blocks to the cold one."),
    ("quantization", "Quantization",
     "Weight precision reduction (Q4/Q5, GGUF) to run SLMs on consumer GPUs like the RTX 3090. Prerequisite for the local navigator agent.",
     [], "## Definition\n\nQ4_K_M is the sweet spot for Qwen 7-14B on the 3090: ~6-9 GB VRAM, minimal navigation quality loss."),
    ("stigmergy", "Stigmergy",
     "Indirect coordination via environmental marks (Grassé, 1959): ants and pheromones. Theoretical foundation of the whisper and shout mechanisms in MonkeyLLM.",
     [("related-to", "projects/monkeyllm/pheromone")],
     "## Definition\n\nAgents coordinate by modifying the environment, not exchanging messages. In MonkeyLLM: heat in trails ([[projects/monkeyllm/pheromone]]) and permanent shortcuts."),
    ("aco", "Ant Colony Optimization",
     "Meta-heuristic by Dorigo inspired by ants: pheromone trails with reinforcement and evaporation. Foundation of the heat mechanism.",
     [("related-to", "concepts/stigmergy")],
     "## Definition\n\nChoice probability proportional to pheromone; evaporation prevents premature convergence — exactly the role of the 30-day heat half-life."),
    ("bm25", "BM25",
     "Classic IR lexical ranking function; serves the Phase 0 locate via SQLite FTS5. Complements vectors in RRF fusion.",
     [], "## Definition\n\nSaturated TF-IDF with size normalization. Unbeatable for exact terms, IDs and SKUs — hence it persists even with vectors."),
    ("rrf", "Reciprocal Rank Fusion",
     "Rank fusion by sum of 1/(k+position). Combines BM25 and vector search in locate without calibrating scores.",
     [("related-to", "concepts/bm25")],
     "## Definition\n\nscore(d) = Σ 1/(k + rank_i(d)), k≈60. Robust to different scales from the source rankers."),
    ("embeddings", "Embeddings",
     "Dense text vectors; enter only in Phase 1 (bge-m3, Matryoshka 1024→256, binary quantization + rescore). Cover summaries, never bodies.",
     [], "## Definition\n\nIn MonkeyLLM vectors exist in a single place: locate. Deleting _derived destroys them with no loss of truth."),
    ("mcp", "Model Context Protocol",
     "Open protocol that exposes tools to LLMs; the Vine speaks MCP (stdio and HTTP). It is the MonkeyLLM entry product.",
     [], "## Definition\n\nTool-use standard between clients (Claude, IDEs) and servers. The 8 Vine primitives are MCP tools."),
    ("slm", "SLM",
     "Small Language Model (1-14B): cheap enough to navigate indexes locally. The MonkeyLLM monkey is a Qwen 7-14B Q4.",
     [], "## Definition\n\nThe thesis: an SLM well-guided by indexes navigates better than a large LLM drowning in RAG chunks."),
    ("wikilink", "Wikilink",
     "Double-bracket link syntax for note connections; resolved only against canonical IDs, no fuzzy match. Ambiguity is a lint error, not a guess.",
     [], "## Definition\n\nDouble-bracket format with canonical id, optionally with display text after the pipe. Obsidian compatibility is a forest marketing feature."),
    ("frontmatter", "Frontmatter",
     "YAML block at the top of each node: the machine interface of the banana. Required fields: id, type, title, summary, created, updated.",
     [], "## Definition\n\nThe summary in the frontmatter is the most critical component of the system: it is the scent that decides hops."),
    ("hierarchical-navigation", "Hierarchical navigation",
     "Central MonkeyLLM thesis: descending through self-describing indexes beats flat vector search in multi-hop questions, cost, and accuracy.",
     [("related-to", "projects/monkeyllm/vision")],
     "## Definition\n\nThe agent reads ~200-500 tokens of index per hop instead of loading fat chunks; depth ≤4 keeps trails at ≤5 hops."),
    ("continuous-batching", "Continuous batching",
     "Technique to serve N sequences on the same GPU by interleaving tokens; makes the Troop (N=3-5 monkeys) cost nearly the same wall-clock as 1.",
     [], "## Definition\n\nvLLM and llama.cpp parallel slots implement it; prerequisite for Phase 1.5."),
    ("hotpotqa", "HotpotQA",
     "Classic multi-hop question benchmark; inspires the format of the Monkey Bench v1 questions.",
     [("related-to", "projects/monkeyllm/monkey-bench")],
     "## Definition\n\nQuestions requiring composing evidence from 2+ documents — the use case where flat RAG suffers most."),
    ("memgpt", "MemGPT/Letta",
     "Paged memory system for LLMs with OS-like functions; related work on agent memory for the paper.",
     [], "## Definition\n\nPages context between main and external memory. Contrast: MonkeyLLM externalizes memory as a navigable, Git-auditable forest."),
    ("sqlite-fts5", "SQLite FTS5",
     "SQLite full-text search extension; serves the lexical side of locate and lives in the derived catalog.",
     [("related-to", "concepts/bm25")],
     "## Definition\n\nEmbedded inverted index with native bm25(), unicode61 tokenizer and diacritic removal — sufficient for the entire Phase 0."),
    ("token-budget", "Token budget",
     "Cross-cutting Vine principle: every response fits a declared budget (look 500, move 600, locate/scan 800) and truncates explicitly.",
     [], "## Definition\n\nSilent truncation is forbidden: truncated: true always. The agent never receives a cut response without knowing it."),
]
for slug, title, summary, links, body in CONCEPTS:
    node(f"concepts/{slug}", "concept", title, summary, ["concept"], links, body)

# -- projects/mixerllm --------------------------------------------------------------

node("projects/mixerllm/architecture", "document",
     "MixerLLM Architecture",
     "Inference architecture with hot and cold models collaborating via compressed symbolic language (mixer-lang), with block-loop and inverse delegation. Author: Jimmy Wesley.",
     ["inference", "slm", "architecture"],
     [("part-of", "projects/mixerllm/_index"), ("compared-with", "concepts/speculative-decoding"), ("author", "people/jimmy-wesley")],
     "## Overview\n\nTwo models collaborate: a **hot** one (fast, quantized, always resident) and a **cold** one (larger, loaded on demand). Communication uses [[projects/mixerllm/mixer-lang]], a compressed symbolic language.\n\n## Mixer-lang\n\nDelegation protocol: the hot model emits `@delega{...}` blocks that the cold model expands. Average compression of 5:1 over equivalent prose.\n\n## Block-loop\n\nSee [[projects/mixerllm/block-loop]]: the execution loop processes semantic blocks, not tokens — the delegation is the inverse of speculative decoding.\n\n## Benchmarks\n\nFull numbers in [[projects/mixerllm/benchmarks]]: 2.4x throughput vs single-model baseline on the 3090.")

node("projects/mixerllm/mixer-lang", "document",
     "Mixer-lang",
     "Compressed symbolic delegation language between hot and cold model. @delega blocks with 5:1 compression; grammar stable since the v2 decision in March 2026.",
     ["mixer-lang", "protocol"],
     [("part-of", "projects/mixerllm/_index"), ("derived-from", "projects/mixerllm/architecture")],
     "## Grammar\n\n`@delega{intent, context, budget}` blocks and `@expand{...}` responses. Closed vocabulary of 64 symbols.\n\n## History\n\nThe v2 grammar was approved at the March decision ([[events/2026-03-mixerllm-v2-release]]).")

node("projects/mixerllm/block-loop", "document",
     "Block-loop",
     "Semantic-block execution loop with inverse delegation: the hot model decides, the cold one expands. Implemented by Fábio Nunes; direct contrast with speculative decoding.",
     ["inference", "block-loop"],
     [("part-of", "projects/mixerllm/_index"), ("author", "people/fabio-nunes"), ("compared-with", "concepts/speculative-decoding")],
     "## Mechanism\n\nIn speculative decoding the small model proposes and the large one verifies token by token. In the block-loop the relationship inverts: the hot (small) model owns the decision and delegates **semantic blocks** wholesale to the cold one.\n\n## Implementation\n\nPriority block queue; the cold model is woken in batch every 3 pending blocks.")

node("projects/mixerllm/benchmarks", "document",
     "MixerLLM Benchmarks",
     "Results on the RTX 3090: 2.4x throughput vs single-model, p95 latency 380ms per block, 9.2 GB VRAM with Qwen 14B/7B Q4 pair. Measured by Fábio Nunes in May 2026.",
     ["benchmarks", "3090"],
     [("part-of", "projects/mixerllm/_index"), ("author", "people/fabio-nunes"), ("related-to", "infra/workstation-3090")],
     "## Setup\n\nHardware: [[infra/workstation-3090]]. Model pair: Qwen2.5 14B (cold) + 7B (hot), both Q4_K_M.\n\n## Results\n\n| Metric | Value |\n|---|---|\n| Throughput vs single-model | 2.4x |\n| p95 latency per block | 380 ms |\n| Total VRAM | 9.2 GB |\n\n## Observations\n\nGain drops to 1.6x on short prompts (<200 tokens), where delegation does not pay off.")

_exp_sections = "\n".join(
    f"## Experiment {i:02d}\n\nRun with seed {1000+i}: temperature variation {0.1*(i%7):.1f}, "
    f"block budget {4+i%5}, observed compression {4.0+(i%10)/10:.1f}:1. "
    f"Result: {'approved' if i % 3 else 'discarded'} — average latency {300+7*i} ms, "
    f"relative throughput {1.5+(i%9)*0.1:.1f}x. Notes: fine-tuning of the symbol vocabulary, "
    f"re-evaluate the priority queue when cold model saturates, repeat with larger batch next window. "
    f"Additional observations from run {i}: the VRAM profile stayed stable at {8.0+(i%5)*0.3:.1f} GB, "
    f"no fragmentation after {100+i} consecutive delegations; the block cache reached hit-rate of "
    f"{60+(i%30)}% and the cold model expansion time varied between {40+i} and {90+2*i} ms per block."
    for i in range(1, 49)
)
node("projects/mixerllm/experiment-log", "note",
     "MixerLLM Experiment Log",
     "Raw diary of 40 experiment runs for mixer-lang (seeds, temperatures, compression, latency). Consult by section; the full body exceeds 4,000 tokens.",
     ["experiments", "log"],
     [("part-of", "projects/mixerllm/_index")],
     "## How to read\n\nOne section per run; use pick(section=) — the full body blows the read budget.\n\n" + _exp_sections)

# -- projects/monkeyllm ---------------------------------------------------------------

node("projects/monkeyllm/vision", "document",
     "MonkeyLLM Vision",
     "Agent-navigable knowledge base: markdown forest with self-describing indexes, 8 MCP primitives and stigmergy. Thesis: hierarchical navigation beats flat RAG in multi-hop.",
     ["vision", "architecture"],
     [("part-of", "projects/monkeyllm/_index"), ("compared-with", "concepts/rag"), ("compared-with", "concepts/graphrag")],
     "## Thesis\n\nNavigation through pre-computed indexes ([[concepts/hierarchical-navigation]]) beats flat vector search in context efficiency and multi-hop accuracy.\n\n## Layers\n\nL0 forest → L1 indexes → L2 derived → L3 protocol (Vine) → L4 agent. L0/L1 are the product; L2 is disposable cache.\n\n## Differentiator\n\nNeither RAG nor GraphRAG improve with use; MonkeyLLM converges via pheromone and shortcuts.")

node("projects/monkeyllm/primitives", "document",
     "The 8 Vine Primitives",
     "MCP tool contracts: locate, look (500 tokens), move (600), pick, query (SQL read-only), scan (catalog), plant and graft (atomic write with Git). Budgets always explicit.",
     ["mcp", "protocol"],
     [("part-of", "projects/monkeyllm/_index"), ("related-to", "concepts/mcp"), ("related-to", "concepts/token-budget")],
     "## Reading\n\n`locate` is the helicopter (BM25 in Phase 0); `look` is the central operation (≤500 tokens); `move` navigates edges; `pick` harvests body or section; `query` queries SQLite datasets; `scan` filters metadata via catalog.\n\n## Writing\n\n`plant` creates (validates schema, updates parent index, commits); `graft` edits with reinforce-before-create policy for shortcuts.")

node("projects/monkeyllm/pheromone", "document",
     "Pheromone: whisper and shout",
     "MonkeyLLM stigmergy mechanism: volatile heat on winning trails (whisper, evaporates in 30 days) and permanent shortcuts via graft (shout, trails ≥4 hops). Author: Bruno Lima.",
     ["stigmergy", "pheromone"],
     [("part-of", "projects/monkeyllm/_index"), ("author", "people/bruno-lima"), ("related-to", "concepts/stigmergy"), ("related-to", "concepts/aco")],
     "## Whisper\n\nEach successful hunt increments `heat` in the trail (in _derived/trails.db). locate/look reorder by score × (1 + α·heat). Exponential evaporation with a 30-day half-life.\n\n## Shout\n\nLong trail (≥4 hops) creates a permanent `discovered-shortcut` with confidence 0.5 — Git commit, auditable.\n\n## Policy\n\nReinforce before create: existing shortcut is fortified, never duplicated.")

node("projects/monkeyllm/monkey-bench", "document",
     "Monkey Bench",
     "MonkeyLLM evaluation harness: HotpotQA-style multi-hop questions, hops-to-banana, tokens-to-banana, and banana precision metrics. Baselines: classic top-k RAG and iterative RAG.",
     ["benchmark", "evaluation"],
     [("part-of", "projects/monkeyllm/_index"), ("related-to", "concepts/hotpotqa"), ("compared-with", "concepts/rag")],
     "## Metrics\n\n- **hops-to-banana**: look+move calls until first pick/query of the answer.\n- **tokens-to-banana**: Σ output tokens in the session.\n- **banana precision**: correct answer nodes / harvested.\n\n## Baselines\n\n(a) Classic top-k RAG with the same corpus in chunks and same embedder; (b) iterative RAG without indexes or graph.\n\n## Phase 1 criterion\n\nPrecision ≥ baseline and ≤60% of iterative RAG tokens.")

node("projects/audio-pipeline", "note",
     "Audio Pipeline",
     "Transcription and diarization pipeline on the 3090; migration from pyannote to NeMo Sortformer completed in 2025. Project closed, maintained as reference.",
     ["audio", "completed"],
     [("related-to", "infra/workstation-3090")],
     "## Summary\n\nWhisper transcription + Sortformer diarization, 6x real-time on the 3090. Closed; lessons applied to the MixerLLM inference server.")

# -- sales -----------------------------------------------------------------------------

node("sales/report-q1-2026", "dataset",
     "Sales Report Q1 2026",
     "Sales by region and SKU, Jan-Mar 2026, 600 rows with channel, quantity, value and margin in USD. Does not include returns (see sales/returns-q1). Source: ERP, export by Ana Castro.",
     ["sales", "q1", "dataset"],
     [("part-of", "sales/_index"), ("author", "people/ana-castro"), ("related-to", "products/_index")],
     "## Query manual\n\n**Tables:** `sales(date, sku, product, region, channel, qty, value, margin)`\n\n**Key columns:** `sku` cross-references [[products/_index]] (A-101 Sensor X, B-202 Gateway M, C-303 Edge Kit); `region` uses 5 macro-regions; `value` and `margin` in USD.\n\n**Example queries:**\n- Total by region: `SELECT region, SUM(value) AS total FROM sales GROUP BY region ORDER BY total DESC`\n- Revenue by SKU: `SELECT sku, product, SUM(value) AS revenue FROM sales GROUP BY sku ORDER BY revenue DESC`\n- Margin by channel: `SELECT channel, ROUND(SUM(margin),2) AS m FROM sales GROUP BY channel`",
     payload="report-q1-2026.db", payload_type="sqlite")

node("sales/returns-q1", "note",
     "Q1 2026 Returns",
     "Summary of the quarter's returns: 14 Sensor X units (batch 22-B, seal failure) and 2 Gateway M. Value returned: $41,300. Not in the main dataset.",
     ["sales", "returns"],
     [("part-of", "sales/_index"), ("related-to", "sales/report-q1-2026")],
     "## Detail\n\nBatch 22-B of the [[products/sensor-x]] had a seal failure; replacement covered under warranty. Quality process opened with the casing supplier.")

node("sales/discount-policy", "note",
     "Discount Policy 2026",
     "Current commercial rules: up to 8% direct, up to 15% via partner with CEO approval, bundles (Edge Kit) already priced with 10% built in.",
     ["sales", "policy"],
     [("part-of", "sales/_index")],
     "## Rules\n\n- Direct channel: up to 8% without approval.\n- Partner: up to 15%, requires approval of [[people/elena-souza]].\n- [[products/edge-kit]] does not stack discount.")

node("sales/targets-2026", "note",
     "Commercial Targets 2026",
     "Annual target of $9.5M with 55% in the second half; Q1 closed at ~$1.9M (20% of target). Northeast expansion planned for Q3.",
     ["sales", "targets"],
     [("part-of", "sales/_index"), ("related-to", "sales/report-q1-2026")],
     "## Summary\n\nQ1 realized ≈ $1.9M. The Northeast expansion plan depends on hiring two reps in Recife.")

# -- events ---------------------------------------------------------------------------

EVENTS = [
    ("2026-01-monkeyllm-kickoff", "MonkeyLLM Kickoff", "January 12, 2026 meeting that approved the phase 0-4 roadmap and named Carla Mendes as PM. Decision: validate navigation before ingest.",
     [("mentioned-in", "projects/monkeyllm/vision"), ("related-to", "people/carla-mendes")],
     "## Minutes\n\n01/12/2026. Present: Elena, Jimmy, Carla, Bruno. Approved: Phase 0 validates an SLM navigating only through indexes; MCP server before ingest pipeline."),
    ("2026-02-datacoop-contract", "DataCoop Contract", "Contract signed on February 18, 2026 with DataCoop: 200 Sensor X units, 4 Gateway M and the MonkeyLLM pilot. Value: $480,000. Negotiated by Elena Souza.",
     [("related-to", "organizations/datacoop"), ("related-to", "products/sensor-x"), ("related-to", "people/elena-souza")],
     "## Terms\n\n02/18/2026. 200× [[products/sensor-x]] + 4× [[products/gateway-m]] + agent memory pilot. Billing in 3 installments; technical contact [[people/marcos-tavares]]."),
    ("2026-03-mixerllm-v2-release", "MixerLLM v2 Release (mixer-lang v2)", "Release on March 30, 2026: mixer-lang v2 grammar approved — closed vocabulary of 64 symbols, backward-compatible, compression from 4:1 to 5:1.",
     [("related-to", "projects/mixerllm/mixer-lang"), ("succeeds", "events/2026-01-monkeyllm-kickoff")],
     "## Decision\n\n03/30/2026. v2 closes the vocabulary at 64 symbols and improves average compression to 5:1. Approved by Jimmy after experiments 21-28 of [[projects/mixerllm/experiment-log]]."),
    ("2026-04-paper-submission", "Paper Submission (internal deadline)", "Internal deadline of April 30, 2026 for the MonkeyLLM paper draft; related work section with Bruno and baselines with Rita Azevedo.",
     [("related-to", "people/rita-azevedo"), ("succeeds", "events/2026-03-mixerllm-v2-release")],
     "## Status\n\nDraft circulated on 04/28. Pending: convergence curve (needs Phase 2) and Troop numbers."),
    ("2026-05-ufpe-workshop", "UFPE Workshop", "Workshop on May 15, 2026 at CIn/UFPE on index-based navigation; 40 participants, organized with Rita Azevedo. Generated 2 student researchers for the Monkey Bench.",
     [("related-to", "organizations/ufpe"), ("related-to", "people/rita-azevedo"), ("succeeds", "events/2026-04-paper-submission")],
     "## Summary\n\n05/15/2026, CIn/UFPE. Live demo of the Vine navigating the test forest; feedback incorporated in spec v0.1."),
    ("2026-06-spec-v01", "Spec v0.1 Approved", "Approval on June 8, 2026 of the technical specification v0.1 of Phase 0 by the architecture team: contracts of the 8 primitives, dialect, and acceptance criteria.",
     [("succeeds", "events/2026-05-ufpe-workshop"), ("related-to", "projects/monkeyllm/primitives")],
     "## Record\n\n06/08/2026. Spec v0.1 becomes the contract truth; changes require a new spec version before code."),
]
for slug, title, summary, links, body in EVENTS:
    node(f"events/{slug}", "event", title, summary, ["event"], links, body)

# -- infra ----------------------------------------------------------------------------

INFRA = [
    ("workstation-3090", "Workstation 3090",
     "R&D reference machine: RTX 3090 with 24 GB VRAM, 128 GB RAM, NVMe 4 TB. Runs the inference server and MixerLLM benchmarks.",
     [("related-to", "projects/mixerllm/benchmarks")],
     "## Spec\n\n- GPU: **RTX 3090, 24 GB VRAM**\n- RAM 128 GB, NVMe 4 TB, Ryzen 9.\n\n## Use\n\nServes Qwen 7-14B Q4 via llama.cpp; forest local on NVMe (look <1ms)."),
    ("edge-cluster", "Edge Cluster",
     "Three Gateway M units used to test embedded inference and the MonkeyLLM offline mode in the field.",
     [("related-to", "products/gateway-m")],
     "## Setup\n\n3× [[products/gateway-m]] on the bench with real sensors; simulates a DataCoop farm."),
    ("docker-deploy", "Vine Docker Deploy",
     "Production compose: vine (MCP server) with forest volume, gardener with GPU passthrough and ranger on cron; async mirror via rclone to R2.",
     [("related-to", "infra/sync-r2"), ("author", "people/diego-rocha")],
     "## Compose\n\nServices: `vine` (HTTP/SSE), `gardener` (ingest, GPU), `ranger` (cron). The _derived folder never syncs — each node rebuilds its own canopy."),
    ("sync-r2", "R2 Sync",
     "Async forest mirror on Cloudflare R2 (zero egress) via rclone every 15 min; never enters the read path.",
     [("part-of", "infra/_index")],
     "## Policy\n\nLocal-first: reads/writes always on local volume. R2 is backup and multi-device; byte-range remote adds 30-80ms per hop, acceptable only in remote-only deploy."),
]
for slug, title, summary, links, body in INFRA:
    node(f"infra/{slug}", "note", title, summary, ["infra"], links, body)

# -- notes ----------------------------------------------------------------------------

NOTES = [
    ("paper-ideas", "Paper Ideas",
     "Idea backlog: convergence curve as the signature graph, bilingual glossary of playful terms, positioning against RAG/GraphRAG/RAPTOR/MemGPT.",
     [("related-to", "projects/monkeyllm/monkey-bench")],
     "## List\n\n1. hops-to-banana curve per week of use.\n2. Comparison table vs [[concepts/rag]], [[concepts/graphrag]], [[concepts/raptor]], [[concepts/memgpt]].\n3. Troop trade-off (speed × cost)."),
    ("bilingual-glossary", "Bilingual Glossary",
     "Mapping of playful terms to technical English: shout = shortcut grafting (the shout), whisper = session-scoped pheromone (the whisper), troop = troop (parallel foragers).",
     [], "## Table\n\n| PT | EN |\n|---|---|\n| grito | shortcut grafting (the \"shout\") |\n| sussurro | session-scoped pheromone (the \"whisper\") |\n| tropa | troop (parallel foragers) |\n| cheiro | scent (summary) |"),
    ("project-risks", "Project Risks",
     "Top risks: summary quality (the entire system), desynchronized indexes, pheromone pollution, forests >100k bananas, payload-passport drift.",
     [("related-to", "projects/monkeyllm/vision")],
     "## Mitigations\n\nSummaries: generous compute at ingest + bench measurement. Indexes: write only via plant/graft. Pollution: low confidence + Ranger pruning."),
    ("recommended-readings", "Recommended Readings",
     "Team's living bibliography: Grassé (stigmergy), Dorigo (ACO), GraphRAG, RAPTOR, MemGPT, and spreading activation papers.",
     [("related-to", "concepts/stigmergy")],
     "## List\n\n- Grassé 1959 — stigmergy in termites.\n- Dorigo 1996 — Ant System.\n- Edge et al. 2024 — GraphRAG.\n- Sarthi et al. 2024 — RAPTOR."),
    ("internal-faq", "Internal FAQ",
     "Frequently asked questions from the team: why markdown and not a database, why BM25 before vectors, why Git on every write, when Phase 3 (Rust) triggers.",
     [], "## Why files?\n\nFiles are the database: auditable, Obsidian-compatible, derived layer disposable.\n\n## When Rust?\n\nOnly with a measured bottleneck (>100k nodes or p95 exceeded) — never because 'Rust is faster'."),
    ("team-onboarding", "Team Onboarding",
     "Entry trail for new members: read the vision, the dialect in _meta/schema, the primitives, and run the 10-question demo locally.",
     [("related-to", "projects/monkeyllm/primitives")],
     "## Steps\n\n1. [[projects/monkeyllm/vision]] → 2. [[_meta/schema]] → 3. [[projects/monkeyllm/primitives]] → 4. local demo."),
]
for slug, title, summary, links, body in NOTES:
    node(f"notes/{slug}", "note", title, summary, ["note"], links, body)

# ---------------------------------------------------------------------------
# Branch definitions: id -> (title, summary/blurb, cross-trails)
# ---------------------------------------------------------------------------

BRANCHES = {
    "people/_index": (
        "People",
        "People in the Tropicália Tech ecosystem: internal team, academic partners and client contacts, with roles and responsibilities.",
        ["Organizations they belong to → [[organizations/_index]]", "Authorship of technical documents → [[projects/_index]]"],
    ),
    "organizations/_index": (
        "Organizations",
        "Companies, clients, labs and universities in the ecosystem: Tropicália Tech, DataCoop, Lab Amazônia and UFPE.",
        ["People in each organization → [[people/_index]]", "Contracts and milestones → [[events/_index]]"],
    ),
    "products/_index": (
        "Products",
        "Product line: edge hardware (Sensor X A-101, Gateway M B-202, Edge Kit C-303) and software (MixerLLM Engine, MonkeyLLM Server).",
        ["Sales numbers by SKU → [[sales/report-q1-2026]]", "Origin architectures → [[projects/_index]]"],
    ),
    "projects/_index": (
        "Projects",
        "Active and archived technical projects: MixerLLM (hot/cold inference), MonkeyLLM (navigable memory) and the completed audio pipeline.",
        ["Theoretical foundations → [[concepts/_index]]", "Reference hardware → [[infra/workstation-3090]]"],
    ),
    "projects/mixerllm/_index": (
        "MixerLLM",
        "Hot/cold inference architecture with mixer-lang: architecture, grammar, block-loop, 3090 benchmarks and the raw experiment log.",
        ["Technical contrast → [[concepts/speculative-decoding]]", "v2 release → [[events/2026-03-mixerllm-v2-release]]"],
    ),
    "projects/monkeyllm/_index": (
        "MonkeyLLM",
        "Navigable knowledge base (this system): vision and thesis, the 8 Vine primitives, the pheromone mechanism and the Monkey Bench.",
        ["Theoretical basis → [[concepts/stigmergy]]", "Approved spec → [[events/2026-06-spec-v01]]"],
    ),
    "concepts/_index": (
        "Concepts",
        "Technical reference definitions: RAG and variants, stigmergy and ACO, BM25/RRF/FTS5, quantization, MCP, SLMs and protocol principles.",
        ["Practical application of concepts → [[projects/_index]]"],
    ),
    "sales/_index": (
        "Sales",
        "Data and commercial rules: SQL-queryable Q1 2026 dataset, quarter returns, discount policy and annual targets.",
        ["Product sheets by SKU → [[products/_index]]", "DataCoop contract → [[events/2026-02-datacoop-contract]]"],
    ),
    "events/_index": (
        "Events",
        "2026 timeline: kickoff, DataCoop contract, mixer-lang v2 release, paper submission, UFPE workshop and spec v0.1 approval.",
        ["People and organizations cited → [[people/_index]]"],
    ),
    "infra/_index": (
        "Infrastructure",
        "Hardware and operations: R&D workstation 3090, edge cluster, Vine Docker deploy and the async R2 mirror.",
        ["Benchmarks running here → [[projects/mixerllm/benchmarks]]"],
    ),
    "notes/_index": (
        "Notes",
        "Cross-cutting team notes: paper ideas, bilingual glossary, risks, recommended readings, FAQ and onboarding.",
        ["Referenced projects → [[projects/_index]]"],
    ),
}

LANDMARKS = [
    "projects/monkeyllm/vision",
    "projects/mixerllm/architecture",
    "sales/report-q1-2026",
    "people/jimmy-wesley",
    "organizations/tropicalia-tech",
    "projects/monkeyllm/pheromone",
    "concepts/rag",
    "events/2026-02-datacoop-contract",
    "infra/workstation-3090",
    "projects/monkeyllm/monkey-bench",
]


def build_sales_db(path: Path) -> None:
    rng = random.Random(42)
    skus = [("A-101", "Sensor X", 1250.0), ("B-202", "Gateway M", 6800.0), ("C-303", "Edge Kit", 14900.0)]
    regions = ["Southeast", "South", "Northeast", "North", "Central-West"]
    weights = [0.38, 0.22, 0.18, 0.07, 0.15]  # Southeast wins deterministically
    channels = ["direct", "partner", "online"]
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sales (date TEXT, sku TEXT, product TEXT, region TEXT, channel TEXT, qty INTEGER, value REAL, margin REAL)"
    )
    start = date(2026, 1, 2)
    rows = []
    for _ in range(600):
        d = start + timedelta(days=rng.randint(0, 88))
        sku, product, price = rng.choice(skus)
        region = rng.choices(regions, weights=weights)[0]
        channel = rng.choice(channels)
        qty = rng.randint(1, 12)
        value = round(qty * price * rng.uniform(0.92, 1.0), 2)
        margin = round(value * rng.uniform(0.18, 0.34), 2)
        rows.append((d.isoformat(), sku, product, region, channel, qty, value, margin))
    conn.executemany("INSERT INTO sales VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "forests" / "forest-fixture"))
    args = ap.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        def _clear_readonly(func, path, exc):
            import os, stat
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(out, onexc=_clear_readonly)
    out.mkdir(parents=True)

    (out / "_meta").mkdir()
    (out / "_meta" / "schema.md").write_text(SCHEMA_MD, encoding="utf-8", newline="\n")

    by_id = {n["id"]: n for n in N}

    # bananas
    for n in N:
        fm = {
            "id": n["id"], "type": n["type"], "title": n["title"], "summary": n["summary"],
            "created": CREATED, "updated": TODAY,
        }
        if n["tags"]:
            fm["tags"] = n["tags"]
        if n["links"]:
            fm["links"] = n["links"]
        fm["source"] = "manual"
        fm.update(n["extra"])
        body = f"# {n['title']}\n\n{n['body'].strip()}\n"
        path = out / f"{n['id']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")

    build_sales_db(out / "sales" / "report-q1-2026.db")

    # branch indexes
    def children_of(branch_id: str) -> tuple[list[str], list[str]]:
        folder = branch_id[: -len("/_index")]
        subs, bananas = [], []
        for nid in sorted(by_id):
            parent = nid.rsplit("/", 1)[0] if "/" in nid else ""
            if parent == folder:
                bananas.append(nid)
        for b in BRANCHES:
            if b == branch_id:
                continue
            bf = b[: -len("/_index")]
            if "/" in bf and bf.rsplit("/", 1)[0] == folder:
                subs.append(b)
        return subs, bananas

    for branch_id, (title, blurb, cross) in BRANCHES.items():
        subs, bananas = children_of(branch_id)
        lines = [f"# {title}", "", f"> {blurb}", ""]
        if subs:
            lines.append("## Sub-branches")
            for s in subs:
                lines.append(entry_line(s, BRANCHES[s][1]))
            lines.append("")
        lines.append("## Direct bananas")
        for b in bananas:
            lines.append(entry_line(b, by_id[b]["summary"]))
        lines.append("")
        if cross:
            lines.append("## Cross trails")
            for c in cross:
                lines.append(f"- {c}")
            lines.append("")
        body = "\n".join(lines)
        fm = {
            "id": branch_id, "type": "branch", "title": title, "summary": blurb,
            "coverage": count_coverage(body), "created": CREATED, "updated": TODAY,
        }
        path = out / f"{branch_id}.md"
        path.write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")

    # master index
    top_branches = [b for b in BRANCHES if "/" not in b[: -len("/_index")]]
    lines = [
        "# Tropicália Forest",
        "",
        "> Knowledge base of Tropicália Tech: people, projects (MixerLLM, MonkeyLLM), "
        "concepts, sales, events and infrastructure. Dialect at [[_meta/schema]].",
        "",
        "## Sub-branches",
    ]
    for b in sorted(top_branches):
        lines.append(entry_line(b, BRANCHES[b][1]))
    lines += ["", "## Direct bananas", "", "## Landmarks"]
    for lm in LANDMARKS:
        lines.append(entry_line(lm, by_id[lm]["summary"]))
    lines += ["", "## Cross trails", "- Forest dialect (node and edge types) → [[_meta/schema]]", ""]
    body = "\n".join(lines)
    fm = {
        "id": "_index", "type": "branch", "title": "Tropicália Forest",
        "summary": "Master branch of the Tropicália Tech knowledge base: regions of people, organizations, products, projects, concepts, sales, events, infra and notes.",
        "coverage": count_coverage(body), "created": CREATED, "updated": TODAY,
    }
    (out / "_index.md").write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")

    # git init + initial commit
    def git(*a):
        subprocess.run(["git", "-C", str(out), "-c", "user.name=fixture", "-c", "user.email=fixture@monkeyllm.local", *a],
                       check=True, capture_output=True, text=True)
    git("init", "--quiet")
    # spec A.3.1: binaries never enter the forest git (referenced by payload_hash)
    (out / ".gitignore").write_text(
        "_derived/\n.vine.lock\n*.db\n*.sqlite\n_assets/\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "--quiet", "-m", "fixture: initial forest (~100 nodes, 12 branches, 1 dataset)")

    total = len(N) + len(BRANCHES) + 2  # + master index + schema
    print(f"forest written to {out}: {total} nodes ({len(BRANCHES) + 1} branches, {len(N)} bananas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
