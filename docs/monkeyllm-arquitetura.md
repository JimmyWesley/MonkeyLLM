# MonkeyLLM — Agent-Navigable Knowledge Forest Architecture

**Domain:** monkeyllm.com
**Concept:** A memory system for LLMs where knowledge lives in markdown files organised as a hierarchical forest of indexes. The agent (monkey) does not scan the forest: it reads indexes (branches), jumps between nodes (hops), and collects only the target information (bananas).
**Central thesis:** Hierarchical navigation through pre-computed indexes outperforms flat vector search (RAG) in context efficiency, operation count, and accuracy on multi-hop questions.

---

## 1. Project Vocabulary

| MonkeyLLM term | Technical meaning |
|---|---|
| **Forest** | The full corpus (Docker volume or S3/R2 bucket) |
| **Branch** | Index file (`_index.md`) for a folder |
| **Master branch** | Root index of the forest (`/_index.md`) — top-of-tree view |
| **Banana** | Atomic unit of knowledge (a final `.md` file) |
| **Hop** | One navigation operation (open an index or follow a link) |
| **Trail** | Sequence of hops from the root to the banana |
| **Scent** | Metadata/summary that lets the agent decide the next hop without opening the content |
| **Passport** | Sibling `.md` file that represents a non-markdown file (PDF, XLSX, SQLite, JSON) in the forest and tells the agent how to query it |
| **Pheromone (whisper)** | Heat weight on edges/nodes, reinforced by successful traversals, that re-ranks results; evaporates over time |
| **Shout (shortcut)** | Permanent lateral wikilink created by the agent when it discovers a valuable banana via a long trail |
| **Troop** | N monkeys hunting in parallel, coordinated by session pheromone (intra-session stigmergy) |
| **Catalog** | SQLite in `_derived/` with frontmatter of all nodes, serving metadata queries (`scan`) without opening files |

Paper metrics: **hops-to-banana** (how many jumps to the answer), **tokens-to-banana** (total context cost of the trail), **banana precision** (did the collected banana answer the question?).

---

## 2. Design Principles

1. **Files are the database.** The canonical truth is plain markdown files. Any binary index (vectors, serialised graph) is a derived, disposable, rebuildable layer.
2. **Every folder is self-describing.** Every folder contains a `_index.md` summarising what is in it and where the paths lead. An agent dropped into any folder knows where it is.
3. **Navigation over search.** Vector search only serves to find the entry point (teleport). From there, the agent navigates the structure, like a human navigates a wiki.
4. **Token-frugal by design.** Each index file is optimised for maximum routing information per token. The agent decides the next hop reading ~200–500 tokens, never loading raw content.
5. **Human-compatible.** Everything opens in Obsidian, VS Code, or GitHub. Humans and agents edit the same substrate.
6. **Git-native.** Compounding knowledge is auditable: every agent write is a commit. Entity merges, corrections, and decay have history.

---

## 3. Forest Structure (Physical Layout)

```
forest/
├── _index.md                  # Master branch: global map, regions, landmarks
├── _meta/
│   ├── schema.md              # Valid node and edge types (the forest "dialect")
│   ├── aliases.md             # Entity resolution table (Apple = Apple Inc)
│   └── stats.md               # Counts, dates, index health
├── _derived/                  # Derived layer (NEVER a source of truth)
│   ├── embeddings.lance/      # Digest vectors (optional, rebuildable)
│   ├── graph.cache.json       # Materialised link graph
│   └── lexical.idx/           # BM25/FTS index (optional)
├── people/
│   ├── _index.md              # Branch: lists digest for each person + cross-links
│   ├── jimmy-wesley.md
│   └── ...
├── projects/
│   ├── _index.md
│   ├── mixerllm/
│   │   ├── _index.md          # Sub-branch: architecture, decisions, experiments
│   │   ├── architecture.md
│   │   └── decisions/
│   │       ├── _index.md
│   │       └── 2026-03-mixer-lang-v2.md
│   └── monkeyllm/
└── concepts/
    ├── _index.md
    └── ...
```

Rules:
- Recommended maximum depth: **4 levels** (keeps any trail within ≤5 hops).
- A folder "explodes" (gains subfolders) when its `_index.md` exceeds ~150 entries or ~3k tokens — analogous to a B-tree page split, but guided by semantics.
- File names are stable slugs (`jimmy-wesley.md`), never renamed; titles change in the frontmatter.

---

## 4. File Anatomy

### 4.1 Banana (knowledge file)

```markdown
---
id: projects/mixerllm/architecture  # stable identity (slug)
type: document                       # type from schema.md
title: MixerLLM Architecture
summary: >                           # THE SCENT — 1-3 sentences, decides hops
  Inference architecture with a hot and cold model collaborating
  via compressed symbolic language (mixer-lang), with block-loop
  and inverse delegation.
tags: [inference, slm, architecture]
links:
  - rel: part-of
    target: projects/mixerllm
  - rel: related-to
    target: concepts/speculative-decoding
  - rel: author
    target: people/jimmy-wesley
created: 2026-06-10
updated: 2026-06-10
confidence: 1.0                    # for compounding: uncertain knowledge < 1.0
source: manual                     # manual | ingest | agent
---

# MixerLLM Architecture

(full content here — the agent ONLY reads this after deciding
this is the right banana)

## Relations
- Part of [[projects/mixerllm/_index]]
- Contrasts with [[concepts/speculative-decoding]]
```

The YAML frontmatter is the machine interface; the body is the human/LLM interface. `summary` is the most important field in the entire system: it is what the index replicates and what navigation relies on.

### 4.2 Branch (`_index.md`)

```markdown
---
id: projects/_index
type: branch
coverage: 12 bananas, 3 sub-branches
updated: 2026-06-10
---

# Projects

> Active and archived technical projects. For people involved,
> see [[people/_index]]. For theoretical foundations, [[concepts/_index]].

## Sub-branches
- [[mixerllm/_index]] — Hot/cold inference architecture with
  mixer-lang. 8 bananas. Active.
- [[monkeyllm/_index]] — Navigable knowledge bank (this
  system). 4 bananas. Active.

## Direct bananas
- [[pipeline-audio]] — Transcription/diarisation pipeline on the 3090;
  pyannote → NeMo Sortformer migration. Completed.

## Cross trails (lateral links)
- Local inference and quantisation → [[concepts/quantisation]]
- Reference hardware → [[infra/workstation-3090]]
```

Three fixed sections: **sub-branches** (descent), **direct bananas** (leaves), **cross trails** (lateral shortcuts — this is what turns the tree into a graph and dramatically reduces hops).

### 4.3 Master branch (`/_index.md`)

Same as a regular branch, but includes:
- **Landmarks:** the 10–20 nodes with the highest degree/importance, with digests — direct entry points without descending the hierarchy.
- **Region map:** one sentence per top-level folder.
- **Conventions:** link to `_meta/schema.md` so the agent learns the dialect in 1 hop.

---

### 4.4 Passport (heterogeneous files)

The forest accepts any format, but **no file enters without a passport**: a sibling `.md` that is the official node for that file in the graph. The agent always touches the passport first; the native file is the payload.

Conversion rules on ingest (Gardener):

| Source format | Treatment | Agent consumes via |
|---|---|---|
| PDF, DOCX | Converted to `.md` (body becomes the banana); original preserved in `_assets/` | `pick()` |
| XLSX, CSV, tabular JSON | Converted to **SQLite** (`.db`, single file, queryable); passport contains the query manual | `query()` |
| Small hierarchical JSON | Embedded in the passport body as a code block | `pick()` |
| Images, audio | Passport with description/transcription generated on ingest | `pick()` |

Example passport for a spreadsheet:

```markdown
---
id: sales/report-q1-2026
type: dataset
title: Sales Report Q1 2026
summary: >
  Sales by region and product, Jan–Mar 2026. 14,302 rows.
  Includes SKU, margin, and channel. Source: ERP, manual export.
payload: report-q1-2026.db        # sibling SQLite
payload_type: sqlite
links:
  - rel: part-of
    target: sales/_index
  - rel: related-to
    target: products/_index
---

# Sales Report Q1 2026

## Query manual
**Tables:** `sales(date, sku, product, region, channel, qty, value, margin)`

**Key columns:** `sku` joins with [[products/_index]]; `region` uses
standard names; `value` in USD.

**Example queries:**
- Total by region: `SELECT region, SUM(value) FROM sales GROUP BY region;`
- Top 10 SKUs by margin: `SELECT sku, SUM(margin) m FROM sales GROUP BY sku ORDER BY m DESC LIMIT 10;`

**Sample (3 rows):**
| date | sku | product | region | value |
|---|---|---|---|---|
| 2026-01-05 | A-101 | Sensor X | Southeast | 1,250.00 |
| ... | | | | |
```

Principle: **tables do not become text — tables become queryable databases.** The agent never loads 14,000 rows into context; it reads the manual (1 hop, ~400 tokens) and queries the spreadsheet with SQL (1 query, ~50 tokens of response). This is what makes the system viable for large tabular data, where RAG-by-chunking fails structurally.



```
┌─────────────────────────────────────────────────┐
│  L4 · NAVIGATOR AGENT (the Monkey)              │
│  SLM (Qwen 7–14B Q4/Q5) with 3 primitives       │
├─────────────────────────────────────────────────┤
│  L3 · NAVIGATION PROTOCOL (MCP server)          │
│  locate() · look() · move() · pick() · query()  │
│  plant() · graft()                              │
├─────────────────────────────────────────────────┤
│  L2 · DERIVED LAYER (acceleration, disposable)  │
│  embeddings (locate) · BM25 (exact locate)      │
│  materialised graph (cheap move)                │
├─────────────────────────────────────────────────┤
│  L1 · SEMANTIC INDEXES (_index.md)              │
│  maintained by the Gardener (ingest pipeline)   │
├─────────────────────────────────────────────────┤
│  L0 · FOREST (markdown + frontmatter + links)   │
│  local Docker volume ←async sync→ S3/R2         │
└─────────────────────────────────────────────────┘
```

The golden rule: **L0 and L1 are the product. L2 is cache. L3 is the interface. L4 is the user.** If you delete all of L2, the system keeps working (slower on `locate`, identical elsewhere). This is what differentiates MonkeyLLM from a vector database: RAG without a vector index dies; MonkeyLLM without a vector index becomes a wiki — that still navigates.

---

## 6. Protocol Primitives (L3)

Exposed as MCP tools. Conceptual signatures:

### `locate(query, k=5) → [entry_points]`
The **helicopter**: the monkey never starts from the trunk — it is dropped in the region closest to the target. Fuses vector search (digests) + BM25 (exact terms, IDs, SKUs) via RRF, at **two levels**: bananas (leaves) and branches (landing zones — for broad questions, landing in the right region and navigating locally outperforms landing on a wrong leaf). Returns id, trail, summary, and score for each candidate. **The only place in the system where vectors exist.**

### `look(id) → digest`
The most-used operation. Returns in compact format:
frontmatter + index sections (if branch) or frontmatter + header outline (if banana) + 1-hop neighbourhood with labels. Target cost: **≤500 tokens**. Never returns the full body.

### `move(id, rel?) → [neighbours]`
Structural navigation: children, parent, or edges of a given type (`rel: related-to`). Served from the materialised graph (L2) or, without cache, from link parsing (L0).

### `pick(id, section?) → content`
Harvests the banana: returns the body (or just one section). The agent only calls `pick` once the `summary` has already indicated this is the target. A low `pick/look` ratio is a sign of efficient navigation.

### `query(id, sql) → rows`
Read-only query against a SQLite payload (tabular datasets). The agent learns the schema from the passport (`look`) and asks the data instead of loading it. Guard-rails: `SELECT` only, forced `LIMIT` (e.g. 200 rows), 2s timeout. Response in compact table form.

### `plant(node) / graft(id, patch)` — writes
Create a new banana / edit an existing one. Every write: (a) validates against `schema.md`; (b) updates the folder's `_index.md`; (c) records a Git commit; (d) marks derived embeddings as stale. Entity merge is **soft**: a `same_as` edge + entry in `aliases.md`; periodic compaction physically merges them.

---

## 7. Software Components (what to build)

| # | Component | Role | Suggested stack (v1) |
|---|---|---|---|
| 1 | **Forest Spec** | Formal specification of layout, frontmatter, link schema | Document (this + schema.md) |
| 2 | **Gardener** | Ingest pipeline: parse (PDF/DOCX/MD → MD), semantic chunking, entity/relation extraction via SLM, summary generation, index updates | Python + quantised Qwen on the 3090; PDF via docling/marker |
| 3 | **Ranger** | Maintenance: detects stale indexes, broken links, folders that need splitting, entity merge candidates | Python, periodic jobs |
| 4 | **Canopy** | Derived layer: embeddings (bge-m3, Matryoshka 1024→256, binary quantisation + rescore), BM25 (Tantivy or SQLite FTS5), graph cache | Python; embedded LanceDB (Apache 2.0, free) or even plain numpy in v0 |
| 5 | **Vine** | MCP server exposing the 6 primitives | Python MCP SDK (`MCPServer`) |
| 6 | **Monkey Bench** | Evaluation harness: corpus + multi-hop questions + metrics (hops-to-banana, tokens-to-banana, precision) vs RAG baseline | Python |

Build order: **1 → 5 (with L2 empty, pure file navigation) → 6 → 2 → 4 → 3.** Note: the MCP server comes before the ingest pipeline — validate navigation on a hand-built forest (e.g. your own notes vault) before automating ingestion.

## 8. Deploy

```
┌────────────── Docker Compose ──────────────┐
│  vine (MCP server) ── volume: /forest      │
│  gardener (ingest worker, GPU passthrough) │
│  ranger (cron)                             │
└──────────────┬─────────────────────────────┘
               │ rclone/litestream async sync
               ▼
        S3 / Cloudflare R2 (cold, backup, multi-device)
```

- Local-first: reads/writes always on the local volume; R2 is an async mirror (R2 has zero egress, good for multi-machine).
- The `_derived/` folder does **not** sync — each node rebuilds its own canopy.
- Git bare repo on the volume = compounding knowledge audit log.

## 9. Validation Roadmap (and the Paper)

**Phase 0 (1 week):** Forest Spec + hand-built test forest (~100 bananas, 10 branches). Vine with `look/move/pick` only (zero embeddings). Question to answer: *can an SLM navigate using only indexes?*

**Phase 1 (3–4 weeks):** `locate` with embeddings + BM25. Monkey Bench with 50–100 multi-hop questions. Baseline: classic top-k RAG on the same corpus. Paper hypothesis: **MonkeyLLM answers multi-hop questions with higher accuracy and lower token cost than flat RAG.**

**Phase 2 (4–6 weeks):** Gardener — automatic ingest of PDF/DOCX/MD. Measure the quality of SLM-generated summaries (they are the heart of the system). Compounding: `plant/graft` + Git.

**Phase 3:** If (and only if) the protocol proves value and the Python stack bottlenecks, rewrite Canopy/Vine in Rust — now with measured requirements, not imagined ones.

**Paper skeleton:** (1) problem: agents waste context with flat RAG; (2) proposal: hierarchical navigation through self-describing indexes; (3) 6-primitive protocol; (4) Monkey Bench vs RAG/GraphRAG; (5) hops/tokens/precision metrics; (6) compounding via versioned filesystem. Positioning against: classic RAG, GraphRAG (Microsoft), RAPTOR, MemGPT/Letta.

## 10. Pheromone Trails — the Living Bank (Stigmergy)

MonkeyLLM is not static: it **learns from its own use**. The mechanism is stigmergy — indirect communication via the environment, like ant pheromone trails. Every successful navigation makes the next ones cheaper. Two complementary mechanisms:

### 10.1 Whisper (pheromone — derived layer, volatile)
- Each edge traversal in a trail that ended successfully (the banana answered the question) increments a `heat` weight on the edge and the destination node.
- `heat` lives in `_derived/trails.db` (high write frequency; does not pollute Git).
- Effect: `locate()` and `look()` re-rank results by `score × f(heat)` — hot bananas and branches rise in rankings.
- **Evaporation:** the Ranger applies exponential decay (e.g. half-life of 30 days). Without evaporation, the system becomes addicted to old paths and new bananas never compete.

### 10.2 Shout (shortcut — canonical layer, permanent)
- **Policy: reinforce before creating.** When the banana is found, the cascade is: (1) shortcut already exists in the trail? → fortify (heat + confidence rise, nothing new is created); (2) does not exist and the trail was long (≥4 hops)? → `graft` creates the lateral wikilink (`rel: discovered-shortcut`, `confidence: 0.5`); (3) did the monkey notice new meaningful lateral connections? → proposes `related-to` with `confidence: 0.3`, which the Ranger confirms or prunes.
- Case (1) is the common path: the system converges on a stable mesh of fortified shortcuts instead of accumulating redundant links.
- Shortcuts become Git commits → auditable, reversible, visible to humans in Obsidian.
- The Ranger prunes shortcuts and proposals that were never reused.

### 10.3 Why this matters for the paper
Neither RAG, GraphRAG, nor RAPTOR improve with use — they index once and stay static. MonkeyLLM converges: **hops-to-banana decreases over time for recurring question distributions.** That convergence curve (average hops per week of use) is a novel result graph and is the materialisation of "compounding knowledge".

## 11. Latency Budget

Latency per hop is dominated by agent inference, not storage — and the design exploits this:

| Operation | Typical cost (local, NVMe) |
|---|---|
| `look` / `move` / `pick` (file read) | < 1 ms |
| `query` (indexed SQLite) | 1–5 ms |
| `locate` (BQ + rescore + BM25 + RRF) | 5–15 ms |
| **Hop decision by SLM (Qwen 7–14B Q4, 3090)** | **100–500 ms** |

Design conclusions from this table:
1. Optimising storage below ~10ms is irrelevant; optimising **number of hops** and **tokens per hop** is everything. Pheromone, shortcuts, ≤500-token digests, and landmarks exist for this reason.
2. S3/R2 sync never enters the read path (it is an async mirror). In remote-only deploy, byte-range requests on R2 add 30–80ms per hop — acceptable, but local-first remains the target.
3. End-to-end target: a multi-hop question answered in **< 5 s** with a local SLM (≈ 4–6 hops × SLM decision), versus tens of seconds from an iterative RAG agent that loads fat chunks each round.

## 12. Known Risks

1. **Summary quality is the entire system.** A bad summary = wrong scent = lost monkey. Mitigation: spend generous compute on ingest (it is offline) and measure summaries in Monkey Bench.
2. **Stale indexes** (write without updating `_index.md`). Mitigation: every write goes through `plant/graft` (atomic update) + Ranger audits.
3. **Write concurrency.** Filesystems have no transactions. v1 mitigation: single write queue in Vine (one writer, N readers).
4. **Giant forests (>100k bananas).** Markdown indexes may not scale. Honest answer: this is exactly the limit Monkey Bench will reveal and that would justify Phase 3 (custom engine). Don't solve it before measuring.
5. **Pheromone/shortcut pollution.** An agent that "shouts" too much fills branches with lateral links and degrades indexes. Mitigation: shortcuts are born with low `confidence`, require reuse for promotion, and the Ranger prunes; evaporation ensures old heat does not dominate.
6. **Payload and passport drift.** The spreadsheet changes and the query manual goes stale. Mitigation: Gardener regenerates the passport when it detects a payload hash change.
