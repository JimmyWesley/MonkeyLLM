# MonkeyLLM: Stigmergic Navigation of Knowledge Forests — Replacing Retrieval-Augmented Generation with Agentic Foraging by Small Language Models

**Author:** Jimmy Wesley Maciel Soares
**Affiliation:** Independent Researcher
**Location:** São Paulo, Brazil
**Contact:** {{CONTACT_EMAIL — e.g. contact@monkeyllm.com or services@idie.ai}}
**ORCID iD:** [0009-0007-1022-9510](https://orcid.org/0009-0007-1022-9510)
**Canonical URL:** {{CANONICAL_URL — e.g. https://monkeyllm.com}}
**Reference implementation:** {{REPO_URL — e.g. https://github.com/JimmyWesley/monkeyllm}}
**Document version:** 1.0.0
**Publication date (ISO 8601 with timezone):** {{PUBLICATION_DATE — e.g. 2026-07-15T09:00:00-03:00}} (São Paulo, Brazil)
**DOI:** *(pending — to be assigned upon Zenodo / arXiv deposit)*
**Document SHA-256:** [to be computed on final version — see Appendix D]

**Copyright © 2026 Jimmy Wesley Maciel Soares. All rights reserved.**
**License:** Text under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — Reference implementation under {{CODE_LICENSE — T05 suggests Apache-2.0}}

---

## Authorship Declaration

I, **Jimmy Wesley Maciel Soares**, declare that the conceptual framework presented in this paper — including but not limited to: (a) the **knowledge forest** as a hierarchical, git-versioned, agent-navigable substrate for grounding language models, with its full ecological vocabulary (forest, branch, banana, monkey, vine, scent, pheromone, shout, whisper, troop, gardener, ranger, canopy); (b) the **scent contract**: hard-budgeted, machine-validated curated summaries (≤60 tokens) as the load-bearing signal enabling zero-read navigation decisions by small language models; (c) the **ten token-budgeted navigation primitives** with explicit-truncation contracts and the normative locate/sniff metadata–body separation; (d) the **stigmergic learning layer** for retrieval — pheromone heat with exponential half-life evaporation, agent-minted `discovered-shortcut` links, and the confidence lifecycle (0.3 → 0.5 → 0.8 → prune) managed by an autonomous Ranger; (e) the **SCENT/FLESH/BONE tiered-storage model** ("the map is not the territory") making terabyte-scale corpora navigable from a laptop; (f) the **troop-with-judge accuracy amplifier** and its patience stop policy; and (g) the **Forest Principle** — *spend intelligence on the environment so you can spend less on the model* — as a generalized design rule for grounded AI systems — was originated, designed and authored by me, and is first publicly disclosed in this document on the date stamped above.

This paper is published as **prior art** for the purposes of establishing authorship, and constitutes an open invitation for collaboration, replication, and derivative work under the terms of the CC BY 4.0 license, with the sole requirement that this authorship be attributed in any subsequent use, publication, or commercial application.

---

## Abstract

Retrieval-Augmented Generation (RAG) grounds language models by embedding text chunks and stuffing the top-*k* nearest neighbors into the prompt. This design is stateless, structure-blind, and brittle exactly where grounding matters most: on questions whose answer must be *assembled* from facts scattered across documents. On our benchmark of strictly multi-hop questions (every question requiring ≥3 chained hops), classic top-*k* RAG scores **0 out of 11**. Zero.

We present **MonkeyLLM**, an architecture that replaces one-shot retrieval with **navigation**. Knowledge lives in a **forest** — a hierarchical, git-versioned graph of Markdown nodes carrying curated, hard-budgeted metadata ("scent") — and a **small language model** traverses it as a foraging agent through ten typed, token-budgeted tool primitives exposed over the Model Context Protocol. Successful hunts deposit **pheromone** on the trail and mint permanent **shortcut links**, so the corpus itself learns from use: a direct transposition of stigmergy and ant-colony optimization to knowledge retrieval, and a computational realization of information-foraging theory.

The same 12B local model that scores 0/11 as a RAG reader scores **11/11 (100%)** as a forest navigator, at **0.58×** the token cost per correct answer of an iterative-RAG baseline, on a single consumer GPU. Hybrid lexical–vector entry search (BM25 + embeddings under Reciprocal Rank Fusion) achieves recall@5 = 1.0 at p95 = 61.5 ms. A 12B curator ingests 100 heterogeneous real-world documents with 100% summary-contract compliance and zero broken links, at 1.7 s/document. We further report three findings of independent scientific interest: parallel foragers with a judge act as an **accuracy amplifier** rather than a speed amplifier; the first documented case of **pheromone cross-talk** in an LLM retrieval system; and a **floor effect** proving that curation quality and trail learning are economic substitutes. Every number in this paper is reproducible from committed scripts in the reference implementation.

**Keywords:** retrieval-augmented generation · agentic retrieval · stigmergy · ant colony optimization · small language models · information foraging · knowledge graphs · Model Context Protocol · Forest Principle

---

## 1. Introduction

### 1.1 A thought experiment

Take the smartest person you know. Hand them eleven questions about your company's internal documentation — real questions, the kind people actually ask: *"which platform hosts the sensor that triggered the April incident, and who signed off on its maintenance window?"* Now impose the RAG condition: for each question, they may read **six paragraphs, chosen by a similarity function that saw only the question**, and nothing else. No follow-up. No "let me check where that report points."

They will fail. Not because they aren't smart — because the six paragraphs contain the *first link* of a chain whose remaining links live elsewhere, and the protocol forbids following them. When we ran exactly this protocol against our multi-hop benchmark, the model didn't hallucinate its way to wrong answers; it did something more damning. It answered, correctly and uselessly, **"the context does not support this"** — eleven times out of eleven.

Now remove the constraint. Same model, same corpus, same questions — but let it *walk*: read a map, smell its options, hop to the next node, follow a cross-reference, open a body only when certain. Score: **11/11**.

Nothing about the model changed. What changed was the *shape of the world we put it in*. That is the entire thesis of this paper.

### 1.2 The pain: RAG retrieves, it does not *look for*

The dominant recipe for grounding LLMs in private corpora — chunk, embed, retrieve top-*k*, generate [1, 3] — treats knowledge as an unordered bag of fragments and retrieval as a single act of guessing. Five failure modes follow directly from that shape:

1. **Multi-hop collapse.** Chained questions defeat single-shot retrieval structurally, not probabilistically: the retriever surfaces the first link, and the honest generator reports insufficiency. In our benchmark (§5.2), this is not a degradation — it is a **cliff**, from 12/18 on mixed questions to 0/11 the moment every question requires chaining.
2. **Structure blindness.** Chunking destroys the corpus's native organization — folders, sections, cross-references — and documented failure modes compound from there: missing content, wrong-granularity chunks, contexts assembled from unrelated fragments [8].
3. **Position sensitivity.** Even when the right passages are retrieved, models systematically under-use information buried in the middle of long stuffed contexts [7].
4. **Statelessness.** Every query starts from zero. A RAG pipeline that answered a question yesterday has learned *nothing* that helps it today. There is no substrate on which experience can accumulate — no trail, no worn path, no institutional memory.
5. **Inverted economics.** The corpus must be embedded up front and re-embedded as it changes, while the reader model's intelligence is spent *filtering noise* instead of *following structure*. The expensive resource does the janitorial work.

### 1.3 The proposal: navigate, don't retrieve

No animal that lives off dispersed resources runs similarity search over its habitat. A monkey foraging for fruit uses three things the jungle provides: **structure** (branches organize space), **scent** (cheap signals readable at a distance, before committing to a climb), and **trails** (paths worn by every forager before it). Information-foraging theory [39, 40] established decades ago that humans hunt information the same way — following "information scent" through link structures, patch by patch. MonkeyLLM operationalizes the analogy end-to-end, and takes it literally enough to compute with:

| Ecology | MonkeyLLM | Technical realization |
|---|---|---|
| Forest | Knowledge corpus | Hierarchical Markdown graph, git-versioned |
| Branch | Organizing index | `_index.md` per region, curated child listings |
| Banana | Atomic knowledge unit | Leaf `.md` node or queryable SQLite dataset |
| Monkey | Navigator agent | A *small* LM (7–12B) in a tool loop |
| Vine | The way through the canopy | MCP server exposing 10 typed primitives |
| Scent | Decide-without-opening signal | ≤60-token curated summaries, tags, outlines |
| Pheromone | Trails of successful foragers | Heat weights, exponential evaporation |
| Shout | A discovery made permanent | Agent-minted `discovered-shortcut` links |
| Whisper | Intra-session coordination | Session-scoped heat shared by a troop |
| Troop | Parallel foragers | N agents + judge |
| Gardener / Ranger | Ecosystem maintenance | Ingest pipeline / decay, promotion, pruning |

The central design bet: **a small model reading ~200–500 tokens of curated metadata per hop out-answers a large stuffed context**, because each hop is a *decision informed by structure* rather than a gamble on embedding geometry. This aligns with the position that small language models are the natural engine of agentic AI [29] — the intelligence required per step is modest *if the environment is legible*. We name the general form of this bet the **Forest Principle** (§7).

### 1.4 Contributions

1. **The forest architecture (§3)** — a complete, normatively specified system: ten token-budgeted primitives with explicit-truncation contracts, the scent contract, a three-tier storage model separating map from territory, a safety-constrained dataset read/write layer, and full ingest (Gardener) and maintenance (Ranger) pipelines. Everything runs locally; nothing requires a frontier model.
2. **A stigmergic learning layer for retrieval (§3.4)** — pheromone heat with exponential evaporation, agent-minted shortcuts, and a confidence lifecycle managed autonomously — adapted directly from ant-colony optimization [24, 28]. The corpus becomes a medium through which agents teach each other, across sessions, without communicating.
3. **Empirical results (§5)** — 100% vs. 0% (top-*k*) and 64% (iterative) on strictly multi-hop QA; 0.58× tokens per correct answer; perfect entry recall at 61.5 ms p95; 100% ingest contract compliance on real heterogeneous documents — all with 12B-class local models on one consumer GPU.
4. **Three research findings (§6)** — the troop accuracy amplifier, pheromone cross-talk (first documented interference case of its kind), and the convergence floor effect — each with a traced mechanism, not just a number.
5. **The Forest Principle (§7)** — *spend intelligence on the environment so you can spend less on the model* — as a generalized design rule, with its relationship to RAG, GraphRAG, and agentic memory made explicit.

---

## 2. Related Work

**RAG and its refinements.** RAG [1], REALM [2], and DPR [3] established retrieve-then-read; RETRO [4] moved retrieval into pretraining. Self-RAG [5] and FLARE [6] make retrieval *adaptive* — when and whether to retrieve — but the retrieval act itself remains flat similarity search over chunks. MonkeyLLM changes the act: retrieval becomes sequential decision-making over explicit structure.

**Documented RAG failure modes.** Liu et al. [7] show the lost-in-the-middle effect; Barnett et al. [8] catalog seven engineering failure points, several rooted in chunking; surveys [9, 10] connect retrieval noise to hallucination. These are precisely the pressures the scent-first, read-lazily design answers.

**Structured and hierarchical retrieval.** GraphRAG [11] builds entity graphs and community summaries; RAPTOR [12] builds recursive summary trees; HippoRAG [13] applies hippocampal indexing over knowledge graphs; Pan et al. [14] survey LLM–KG unification. All of these *pre-compute* structure that a retriever then queries in one or few shots. MonkeyLLM shares the structural premise but differs on two axes with no precedent we are aware of: the structure is **walked by the model itself**, hop by hop, and the structure is **alive** — mutable by the agent (planted nodes, grafted links) and adaptive to usage (pheromone). GraphRAG's graph never learns which of its edges are worth anything. MonkeyLLM's forest does.

**Agentic retrieval and tool use.** WebGPT [15] and WebArena [22] navigate the open web; ReAct [16], Toolformer [18], and Reflexion [17] establish the reason–act loop; LATS [21] adds tree search; MemGPT [19] pages memory hierarchically; agentic-RAG surveys [23] map the emerging space. MonkeyLLM's distinguishing choices: (a) a *closed, contract-typed* action space with hard token budgets per observation — engineered so a 7–12B model suffices where web agents need frontier models; (b) MCP [20] as the transport, making the forest a server any agent can mount; (c) the environment itself, not the agent, is the locus of learning.

**Stigmergy and swarm intelligence.** Grassé [25] coined stigmergy for coordination through environment modification; Dorigo et al. [28, 24] formalized pheromone optimization with the evaporation update τ ← (1−ρ)τ + Δτ; Bonabeau, Dorigo & Theraulaz [26, 27] generalized the paradigm. MonkeyLLM is, to our knowledge, **the first system to use literal pheromone dynamics — deposit, evaporate, promote, prune — as the learning layer of an LLM retrieval system**, and §6.2 reports the first documented pheromone-interference failure in this setting.

**Small language models.** SLM surveys [30] and the phi line [31] show curated data lets small models punch above their weight; Qwen [32], Gemma [33], and Llama [34] provide capable open checkpoints; Belcak et al. [29] argue on economic grounds that SLMs are the future of agentic AI. MonkeyLLM is an existence proof in the retrieval domain: every headline result in this paper was produced by a 12B model on a single RTX 3090.

**Ranking machinery and theory.** BM25 [35] over SQLite FTS5 [37] gives a zero-dependency lexical layer; Reciprocal Rank Fusion [36] fuses it with optional vectors; information-foraging theory [39, 40] supplies the cognitive account of why scent-following works at all.

### 2.1 Summary of novelty

| Component | Novel? | Most-similar prior work |
|---|---|---|
| Hierarchical summaries over a corpus | No | RAPTOR, GraphRAG |
| Agentic tool loop for retrieval | No | ReAct, WebGPT, agentic RAG |
| Hard token budgets with explicit-truncation contracts per primitive | **Yes** | (no precedent found) |
| The scent contract: machine-validated ≤60-token summaries as the navigation signal | **Yes** | Information scent [39] (theory, not a contract) |
| Normative metadata/body search split (locate vs. sniff) | **Yes** | (no precedent found) |
| Pheromone heat + evaporation as retrieval re-ranking | **Yes** | ACO [24, 28] (non-LLM domain) |
| Agent-minted permanent shortcut links with confidence lifecycle | **Yes** | (no precedent found) |
| Autonomous promote/prune daemon over uncertain links (Ranger) | **Yes** | (no precedent found) |
| Corpus as git repository, every agent write a commit | **Yes** | (no precedent found in retrieval systems) |
| SCENT/FLESH/BONE tiered storage for navigable TB-scale corpora | **Yes** | MemGPT [19] (context paging, not corpus tiering) |
| Troop + judge over shared session pheromone | **Yes** | Multi-agent debate (no stigmergic medium) |

---

## 3. The MonkeyLLM Architecture

### 3.1 The forest: a corpus you can stand inside

A forest is a directory tree of Markdown files with YAML frontmatter, owning an **embedded git repository**: every write — human, gardener, or monkey — is a commit. The corpus is versioned, auditable, and diffable by construction. Two node kinds exist: **branches** (`_index.md` files that summarize and enumerate their region) and **bananas** (leaves: notes, documents, entities, concepts, events, media, or datasets).

Every node carries a *passport*: title, type, tags, links with per-link confidence, and — the load-bearing element — a **curated summary of at most 60 tokens**, structured by contract: (1) what this is; (2) its differential content — numbers, names, temporal scope; (3) optionally, what is *not* here and where it lives. The contract is machine-validated at write time. Anti-patterns ("This document describes…") are rejected: a summary that wastes tokens without scent poisons every hop decision downstream. This discipline is what makes navigation cheap; it is to MonkeyLLM what chunk quality is to RAG, except it is *enforced*.

Derived artifacts — an SQLite FTS5 catalog, the pheromone database, an optional vector index — live in a disposable `_derived/` layer, rebuildable from the Markdown at any moment. Binaries never enter git; datasets are SQLite payloads referenced by content hash. Delete `_derived/`, run one command, and the forest is whole again: **the Markdown and its git history are the single source of truth.**

### 3.2 The Vine: ten primitives, every observation budgeted

The agent touches the forest exclusively through an MCP server exposing ten typed tools. Every read primitive carries a **hard output budget with explicit truncation** (`truncated: true` — never a silent cut, so the agent can always distinguish "not there" from "cut off"):

| Primitive | Budget (tokens) | Semantics |
|---|---|---|
| `locate(query, k)` | ≤ 800 | Ranked entry points over curated metadata; BM25, optionally hybrid (§3.3) |
| `look(id)` | ≤ 500 | Node digest: summary, tags, outline, top-12 edges with 25-token neighbor scents |
| `move(id, rel?)` | ≤ 600 | Typed edge traversal to neighbors |
| `pick(id, section?)` | ≤ 4000 | Read a body; bodies > 4000 tokens force section selection |
| `sniff(terms)` | ≤ 800 | Literal, diacritics-normalized grep over *bodies only* |
| `scan(parent, filter)` | ≤ 800 | Metadata filtering of a region, zero file opens |
| `harvest(query)` | ≤ 4000 | Zero-LLM composite: locate + sniff fused by RRF + selective pick |
| `query(id, sql)` | 200 rows / 2 s | Read-only SQL over dataset nodes, injection-hardened |
| `plant` / `graft` / `tend` | atomic | Writes: birth a node / mutate passports & links / single-statement DML — each one git commit |

Two contracts deserve emphasis. The **locate/sniff split** is normative: `locate` searches only curated metadata (the scent layer); `sniff` searches only raw bodies. The separation makes the value of curation *measurable* and keeps entry search fast. The **write-safety model** is defense-in-depth: `query` rejects every write; `tend` accepts exactly one INSERT/UPDATE/DELETE with a mandatory WHERE on mutation and no DDL, ever; datasets are born from a *declarative schema* validated by the Vine — the model never writes DDL. Both guards carry dedicated injection test suites.

A typical hop costs 200–500 tokens of observation. A five-hop answer costs ~1.5–2.5k tokens of *exactly relevant* context — versus a top-*k* stuffing of comparable size whose relevance is a bet placed before reading anything.

### 3.3 Entry search: BM25 + vectors under RRF, re-ranked by heat

Phase 0 requires zero embeddings: `locate` is BM25 [35] over FTS5 [37] — a corpus becomes navigable with no GPU, no embedding pass, no vector database. When a vector index (the *Canopy*) and an embedder are present, `locate` becomes hybrid via Reciprocal Rank Fusion [36]:

$$
s_{\mathrm{RRF}}(d) \;=\; \sum_{r \,\in\, \{\mathrm{BM25},\ \mathrm{vec}\}} \frac{1}{k + \mathrm{rank}_r(d) + 1}, \qquad k = 60
$$

The fused strength is then modulated by pheromone:

$$
\mathrm{score}(d) \;=\; \mathrm{strength}(d)\,\bigl(1 + \alpha\, h(d)\bigr), \qquad \alpha = 0.3
$$

where $h(d) \in [0,1]$ is the node's heat. Cold nodes rank purely on relevance; well-trodden nodes gain up to a 30% boost. The forest's history participates in every search.

### 3.4 Stigmergy: the corpus that learns

Here is the part with no analogue in RAG. Following ant-system dynamics [28, 24], every successful hunt deposits heat on the nodes of its trail. Within a session, a troop shares *session-scoped* heat (**whispers** — one monkey's progress warms the trail for its troop-mates in real time):

$$
h_{\mathrm{total}} = h_{\mathrm{persistent}} + \beta\, h_{\mathrm{session}}, \qquad \beta = 0.5
$$

Persistent heat **evaporates** with an exponential half-life, applied idempotently by the Ranger daemon:

$$
h(t + \Delta t) \;=\; h(t)\cdot 2^{-\Delta t / T_{1/2}}, \qquad T_{1/2} = 30\ \text{days};\quad h < 0.01 \Rightarrow \text{removed}
$$

— the classical τ ← (1−ρ)τ decay [28] in half-life form. Knowledge that stops being used literally cools down and fades from the ranking, exactly as an unused trail regrows.

Beyond scalar heat, agents make discoveries **structural**. When a hunt reaches its answer through a chain of ≥4 hops, the agent grafts a permanent `discovered-shortcut` link — a **shout** — at link confidence 0.5, under an idempotent *reinforce-before-create* rule (rediscovery strengthens; it never duplicates). Links thus carry a confidence lifecycle, managed exclusively by the Ranger and only below 1.0:

| Confidence | Origin | Ranger action |
|---|---|---|
| 1.0 | Structural / human | Untouchable |
| 0.8 | Promoted | Stable |
| 0.5 | Shout (agent-discovered shortcut) | Promote or prune |
| 0.3 | Curator edge proposal at ingest | Promote or prune |

Promotion fires when both endpoints are hot ($h \ge 0.2$ → confidence 0.8, audited commit); pruning removes stone-cold uncertain links. The Ranger never deletes nodes. The net effect satisfies Grassé's strict definition of stigmergy [25]: **agents coordinate across sessions through modifications of the shared environment, never through direct communication.** The thousandth question asked of a forest is answered by a measurably different — better — forest than the first.

### 3.5 The living corpus: Gardener, Curator, and tiered storage

Forests are not hand-built shrines. The **Gardener** mirrors external sources into the forest (`adopt`/`sync`, hash-diff reconciliation) through pluggable converters, and an optional LLM **Curator** writes contract-compliant summaries (validate-and-retry against the 60-token rule) and proposes `related-to` edges at confidence 0.3 — chosen only from a **closed, catalog-supplied candidate list, making hallucinated link targets structurally impossible**, not merely unlikely. The Gardener never deletes nodes; vanished sources are flagged stale for the Ranger.

Storage is tiered — *the map is not the territory*:

- **SCENT** — passports and indexes: always local, always in git, ~0.1% of source size;
- **FLESH** — converted full text: inline in git, cached out of git, or referenced live at the source, per adoption policy;
- **BONE** — raw binaries: stay at the source; `s3://` URIs supported with a hash-validated LRU cache.

The consequence is worth stating plainly: **a 2 TB corpus is fully navigable from a laptop that holds only its scent.** The monkey smells everything; it fetches flesh only for the nodes it actually decides to read.

### 3.6 The troop: parallel foragers and a judge

For hard questions, N monkeys (N = 3–5) hunt in parallel from distinct entry points (a partition of `locate`'s top-k frontier), share session pheromone, and a judge synthesizes their candidates. A **patience stop policy** — keep hunting while harvests still surface new nodes; stop after $P$ dry rounds — replaces oracle knowledge of a question's fork-width; solo agents use a width-aware step budget $B(q) = 14 + 3(w-1)$.

---

## 4. Experimental Setup

**Corpora.** `bench-forest`: 153 nodes, 6 branches, generated deterministically by committed scripts. A separate 100-document heterogeneous dump (PDF, XLSX, Markdown) exercises ingest. Everything rebuilds from the repository.

**Question sets.** v2: 18 mixed-difficulty questions. v3: 11 questions, every one requiring ≥3 hops with verified chained evidence. v4: 8 fork-tier questions (fork-width 2–4, requiring aggregation across parallel sub-chains).

**Arms.**
- **monkey** — one SLM navigating through Vine primitives (step budget 14; width-aware on v4);
- **topk** — classic RAG: same corpus, chunked, top-k = 6 by similarity, one completion;
- **iter** — iterative RAG: retrieve → read → reformulate → retrieve, until answered or budget exhausted;
- **troop** — N = 3 monkeys + judge (quorum / coverage / patience variants).

**Models.** Navigation, generation, and curation: **Gemma-4 12B served locally** (llama.cpp, one RTX 3090); the 2026-07-02 fork-tier runs used `qwen3.5-flash` via OpenRouter to remove GPU contention. Embeddings (hybrid locate only): bge-m3. *No frontier-scale model appears anywhere in this paper.*

**Metrics.** *hops-to-banana* and *trail length* (read-primitive calls before first harvest of an answer node); *tokens-to-banana* (total observation tokens per question); *banana precision* $|H \cap E|/|H|$ for harvested set $H$ against expected nodes $E$; correctness; wall-clock (median, p95). {{OPTIONAL: statistical treatment — seeds/repeats per cell, CIs — add if the bench is rerun with repeats}}.

---

## 5. Results

### 5.1 Entry search: the monkey starts on the right branch

Hybrid locate (BM25 + bge-m3 under RRF), 153-node forest, 18 queries × 40 repeats:

| Configuration | R@1 | R@3 | R@5 | MRR | p50 | p95 |
|---|---|---|---|---|---|---|
| BM25-only | 0.556 | 0.583 | 0.611 | 0.630 | — | 5.9 ms |
| **Hybrid (RRF)** | **1.00** | **1.00** | **1.00** | **0.88** | 48 ms | **61.5 ms** |

Perfect recall@5 at p95 = 61.5 ms means every hunt opens on or adjacent to the answer region. (The rare p99 spike of 2.1 s is first-call embedder warm-up.)

### 5.2 Multi-hop question answering: the cliff

| | **Mixed set (v2, 18 q)** | | | **Strictly multi-hop (v3, 11 q, ≥3 hops)** | | |
|---|---|---|---|---|---|---|
| Arm | Correct | Precision | Tok (med) | Correct | Precision | Tok (med) |
| **monkey** | **18/18** | **1.00** | 867 | **11/11** | **1.00** | 1433 |
| topk (k=6) | 12/18 | 0.68 | 849 | **0/11** | 0.64 | 803 |
| iter | 16/18 | 0.82 | 708 | 7/11 | 0.86 | 1384 |

Read the topk row left to right. On mixed questions it looks respectable — 12/18, the number a demo shows you. The moment every question requires chaining, it falls off a cliff to **zero**. This is not a strawman configuration; chunk + embed + top-k + generate is the default architecture of most deployed RAG systems in 2026. The failure is structural and therefore *invisible to sampling*: any evaluation containing single-hop questions averages the cliff away.

Iterative RAG partially recovers (7/11) but pays in latency variance (p95 = 17.5 s/q vs. the monkey's 8.4 s) and still misses a third of the questions. And the token economics invert on inspection: the monkey's raw median (1433) is comparable to iter's (1384), but tokens *per correct answer* are 1433 × 11⁄11 = **1,433** vs. 1384 × 11⁄7 ≈ **2,175** — a **0.58× ratio**. *Failing cheaply is not economy.*

A complete hop-by-hop hunt, with primitives, observations, and token accounting, is worked in **Appendix A**.

### 5.3 Ingest: a 12B curator is enough

On the 100-document heterogeneous dump (Gemma-4 12B as Curator): 100 nodes planted under a mirrored 8-branch hierarchy; **100% of LLM summaries passed the 60-token scent contract** (2 self-corrected retries, 0 fallbacks); **0 broken links, 0 lint errors** post-ingest; **1.71 s/document** end-to-end. Edge proposals produced zero hallucinated targets — by construction, since candidates come from a closed catalog list. Building a forest does not require a frontier model either.

---

## 6. Findings

We report three findings that emerged from measurement, each with a traced mechanism. Two of them are "failures" by their original success criteria — and both taught us more than the successes did.

### 6.1 The troop is an accuracy amplifier, not a speed amplifier

The hypothesis said parallel monkeys would be *faster*. They weren't — they were *righter*. On single-chain questions (v3), troop (N=3) reached **11/11 vs. 10/11 solo**, at 2.3× tokens and 3.3× wall-clock: three monkeys entering by different frontier nodes explore *distinct wrong chains*, and the judge arbitrates. On fork-tier questions (v4), the deployable **patience** policy scored **8/8 vs. 7/8 solo** (solo's failure: step-budget exhaustion mid-chain on a width-3 question), and generalized to **5/5 on a freshly ingested 100-document real-data forest**, covering both failure modes (date-scoped lookup, enumeration) that motivated it.

The speedup hypothesis failed cleanly — best case cut wall-clock 10% while losing coverage — and the post-mortem yielded a sharp precondition. On a 153-node forest, sub-chains are 2–3 hops each; a solo agent serializes them faster than the troop pays coordination overhead. Modeling sub-chain costs $c_i$:

$$
\mathbb{E}[\text{speedup}] \approx \frac{\sum_i c_i}{\max_i c_i + c_{\mathrm{judge}}}
$$

which degenerates below 1 exactly when $\max_i c_i$ approaches $\sum_i c_i$ — the shallow-forest regime. **Parallel foraging buys latency only when sub-chains are deep (≥4 hops) or reads are slow (remote payloads); it buys reliability everywhere.** {{TODO: validate on a deeper corpus once built}}.

### 6.2 Pheromone cross-talk: when a good trail lies

This is, to our knowledge, the first documented case of pheromone interference in an LLM retrieval system, and we present it as a phenomenon, not a patched bug.

Across five convergence passes with accumulating trails, question v3-01 was answered **correctly on pass 1 and wrongly on every pass thereafter**. The forest *learned itself into a mistake*. Full trace: the winning trail of an unrelated question (v3-11) deposited heat on a node semantically adjacent to v3-01's decoy; the re-ranking term $(1+\alpha h)$ with $\alpha = 0.3$ then lifted the decoy above the true answer in `locate`. Heat is query-*unconditioned* — relevance to one hunt leaks into all hunts.

The failure has a classical flavor: ACO fights premature trail concentration with evaporation and pheromone bounds [24]; our 30-day half-life is far too slow to help within a session cluster. Candidate mitigations, each a deliberate spec change rather than a hot-fix: lower $\alpha$; query-conditioned heat $h(d \mid \mathrm{topic})$; per-*link* rather than per-node heat; context metadata on shortcuts. For any system that lets usage feed back into ranking — including every "learning" retrieval product now shipping — this failure class is waiting. We name it so it can be looked for.

### 6.3 The floor effect: curation and learning are substitutes

The learning layer was hypothesized to cut hops ≥25% over repeated exposure. Measured over 5 passes: hops 1.45 → 1.33 (**−12.4%**), trail length −3.0%, tokens −0.7%. Criterion: not met. Mechanism: demonstrably working — 6 shouts grafted on pass 1, reinforce-before-create fortifying them after (zero duplicates), heat re-ranking stable.

The resolution of this paradox is the finding: **hybrid locate plus disciplined curation already navigates the benchmark cold at ~1.4 hops — there is no 25% to reclaim near the 1-hop floor.** Trail learning needs headroom: weaker entry search, deeper hierarchies, or 4+-hop cold paths. Stated as economics: *curation quality and trail learning are substitutes.* Money spent on scent reduces the marginal value of pheromone, and vice versa — which tells an operator precisely where to spend next on any given corpus. {{TODO: deeper-corpus convergence run}}.

---

## 7. The Forest Principle

We generalize the architecture into a design rule:

> **Spend intelligence on the environment so you can spend less on the model.** Structure the corpus so that each retrieval step is a cheap local decision over curated signals; let successful use modify the structure; and the model required at query time shrinks by orders of magnitude.

The three clauses are independent. The first (curated structure + scent) is what converts one hard global guess — "which k fragments are jointly sufficient?" — into a sequence of easy local questions: "which of these twelve summarized edges smells most like the goal?" The second (stigmergic feedback) is what makes the system's *thousandth* query cheaper and better-grounded than its first — a property absent from every stateless pipeline. The third is the economic punchline, and the empirical content of this paper: under the first two clauses, **a 12B local model outperforms the architecture that a frontier model needs in order to fail politely.**

The principle locates the industry's spending pattern precisely backwards. The prevailing answer to grounding failures is a bigger context window, a bigger reader, a better re-ranker — intelligence at query time, paid on every query, learning nothing. The Forest Principle moves that spend to ingest time (curation, once per document) and to structure (accumulating across all queries), where it compounds. RAG treats the corpus as dead data to be excavated by an ever-smarter reader; MonkeyLLM treats the reader as replaceable labor working an ever-smarter corpus.

The principle is modality-independent: any system with (a) a decomposable knowledge substrate, (b) cheap curated signals over its parts, and (c) repeated queries whose successes can be recorded structurally, is a candidate — code navigation, personal knowledge management, robot task memory, scientific literature graphs. We instantiate it for text corpora; the invariant is the rule, not the Markdown.

---

## 8. Discussion

**The auditability dividend.** Because every write is a git commit and every read is a typed, budgeted call with a recorded trace, a MonkeyLLM answer is **replayable**: the exact trail, every observation, and the harvested evidence are inspectable after the fact. Ask a RAG pipeline *why* it retrieved what it retrieved and you get cosine similarities; ask a forest and you get a trail you can walk yourself. For regulated and high-stakes domains this is not a nicety — it is the difference between an answer and an account.

**Costs and honest trade-offs.** Navigation pays per hop: on shallow questions, top-k is faster and adequate (v2: 12/18 at lower latency) — which is why `harvest` exists as a zero-LLM single-shot path for the easy case. The forest requires curation — human or a 12B curator (§5.3) — and the scent contract is load-bearing: bad summaries would poison every hop, which is exactly why the contract is machine-enforced rather than aspirational. Pheromone introduces a genuinely new failure class (§6.2). Our corpora are small (10²–10³ nodes); behavior at 10⁵–10⁶ nodes, where hierarchy depth interacts with entry-search quality, is untested. {{TODO: scale study}}.

**Limitations.** (i) A single benchmark family, generated by the authors — external multi-hop suites are needed; (ii) correctness scored by substring matching; (iii) no statistical repeats on the headline table yet; (iv) entity extraction and `same-as` deduplication are specified but deferred; (v) the cross-talk mitigation is proposed, not implemented.

**Reproducing this paper.** Clone the repository, build the fixture forest, point the demo at any OpenAI-compatible endpoint — a local llama.cpp server is enough — and run the bench (Appendix B gives the exact commands). Every table above regenerates from committed scripts. If the 0/11 cliff sounds implausible, we encourage you to reproduce *that number first*: it takes one command and it is the whole argument.

---

## 9. Conclusion

We put the same small model into two worlds. In the world RAG builds — flat, destructured, stateless — it scored zero on questions that required following a thread. In a forest — hierarchical, scented, versioned, and learning from every successful hunt — it scored perfectly, cheaper per correct answer, on hardware that fits under a desk.

MonkeyLLM's claim is therefore not that navigation beats retrieval by some margin on some benchmark. It is that **grounding is a property of the environment, not of the model** — and that the intelligence of the environment can substitute for the scale of the model. The stigmergic layer makes that environment a living one, shared across sessions and agents; its two failure modes surfaced here — cross-talk and the floor effect — chart the immediate research agenda: query-conditioned pheromone, deeper corpora, external benchmarks.

If the path to cheap, private, grounded AI runs anywhere, it does not run through bigger context windows. It runs through better forests.

---

## Reproducibility

All code, the normative specification (`docs/monkeyllm-spec-v0.12.md`), corpus generators, question sets, and measurement scripts ship in the reference implementation. Key entry points: `bench/run_bench.py` (all arms), `scripts/bench_locate.py` (§5.1), `scripts/measure_curation.py` (§5.3), `scripts/convergence.py` (§6.2–6.3). Forests rebuild deterministically; the full test suite (272 tests, including SQL-injection suites for `query` and `tend`) passes green. See Appendix B for a five-minute quickstart.

## Acknowledgements

Conceptual development by **Jimmy Wesley Maciel Soares**, São Paulo, Brazil, 2026. All experiments in this paper ran on a single consumer GPU (NVIDIA RTX 3090) — a fact the author considers part of the argument. The author thanks the open-source community for llama.cpp, SQLite, and the open-weight model families that made this design space tractable. {{ADDITIONAL_ACKNOWLEDGMENTS — collaborators, reviewers, if any}}

**Conflicts of interest:** None declared.
**Funding:** This research was conducted independently without external funding.
**Data availability:** All corpora, question sets, and measurement scripts are available at the canonical repository URL listed in the document header.

---

## References

[1] Lewis, P., Perez, E., Piktus, A., et al. (2020). Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. *NeurIPS 2020*. [arXiv:2005.11401](https://arxiv.org/abs/2005.11401)

[2] Guu, K., Lee, K., Tung, Z., Pasupat, P., Chang, M.-W. (2020). REALM: Retrieval-Augmented Language Model Pre-Training. *ICML 2020*. [arXiv:2002.08909](https://arxiv.org/abs/2002.08909)

[3] Karpukhin, V., Oğuz, B., Min, S., et al. (2020). Dense Passage Retrieval for Open-Domain Question Answering. *EMNLP 2020*. [arXiv:2004.04906](https://arxiv.org/abs/2004.04906)

[4] Borgeaud, S., Mensch, A., Hoffmann, J., et al. (2022). Improving Language Models by Retrieving from Trillions of Tokens. *ICML 2022*. [arXiv:2112.04426](https://arxiv.org/abs/2112.04426)

[5] Asai, A., Wu, Z., Wang, Y., Sil, A., Hajishirzi, H. (2024). Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection. *ICLR 2024*. [arXiv:2310.11511](https://arxiv.org/abs/2310.11511)

[6] Jiang, Z., Xu, F. F., Gao, L., et al. (2023). Active Retrieval Augmented Generation. *EMNLP 2023*. [arXiv:2305.06983](https://arxiv.org/abs/2305.06983)

[7] Liu, N. F., Lin, K., Hewitt, J., et al. (2024). Lost in the Middle: How Language Models Use Long Contexts. *TACL* 12:157–173. [arXiv:2307.03172](https://arxiv.org/abs/2307.03172). doi:10.1162/tacl_a_00638

[8] Barnett, S., Kurniawan, S., Thudumu, S., Brannelly, Z., Abdelrazek, M. (2024). Seven Failure Points When Engineering a Retrieval Augmented Generation System. *CAIN 2024*. [arXiv:2401.05856](https://arxiv.org/abs/2401.05856). doi:10.1145/3644815.3644945

[9] Gao, Y., Xiong, Y., Gao, X., et al. (2023). Retrieval-Augmented Generation for Large Language Models: A Survey. [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)

[10] Huang, L., Yu, W., Ma, W., et al. (2025). A Survey on Hallucination in Large Language Models. *ACM TOIS* 43(2). [arXiv:2311.05232](https://arxiv.org/abs/2311.05232). doi:10.1145/3703155

[11] Edge, D., Trinh, H., Cheng, N., et al. (2024). From Local to Global: A Graph RAG Approach to Query-Focused Summarization. [arXiv:2404.16130](https://arxiv.org/abs/2404.16130)

[12] Sarthi, P., Abdullah, S., Tuli, A., et al. (2024). RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval. *ICLR 2024*. [arXiv:2401.18059](https://arxiv.org/abs/2401.18059)

[13] Gutiérrez, B. J., Shu, Y., Gu, Y., Yasunaga, M., Su, Y. (2024). HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models. *NeurIPS 2024*. [arXiv:2405.14831](https://arxiv.org/abs/2405.14831)

[14] Pan, S., Luo, L., Wang, Y., et al. (2024). Unifying Large Language Models and Knowledge Graphs: A Roadmap. *IEEE TKDE* 36(7):3580–3599. [arXiv:2306.08302](https://arxiv.org/abs/2306.08302). doi:10.1109/TKDE.2024.3352100

[15] Nakano, R., Hilton, J., Balaji, S., et al. (2021). WebGPT: Browser-Assisted Question-Answering with Human Feedback. [arXiv:2112.09332](https://arxiv.org/abs/2112.09332)

[16] Yao, S., Zhao, J., Yu, D., et al. (2023). ReAct: Synergizing Reasoning and Acting in Language Models. *ICLR 2023*. [arXiv:2210.03629](https://arxiv.org/abs/2210.03629)

[17] Shinn, N., Cassano, F., Gopinath, A., Narasimhan, K., Yao, S. (2023). Reflexion: Language Agents with Verbal Reinforcement Learning. *NeurIPS 2023*. [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)

[18] Schick, T., Dwivedi-Yu, J., Dessì, R., et al. (2023). Toolformer: Language Models Can Teach Themselves to Use Tools. *NeurIPS 2023*. [arXiv:2302.04761](https://arxiv.org/abs/2302.04761)

[19] Packer, C., Wooders, S., Lin, K., et al. (2023). MemGPT: Towards LLMs as Operating Systems. [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)

[20] Anthropic (2024). Introducing the Model Context Protocol. [anthropic.com/news/model-context-protocol](https://www.anthropic.com/news/model-context-protocol); specification: [modelcontextprotocol.io](https://modelcontextprotocol.io)

[21] Zhou, A., Yan, K., Shlapentokh-Rothman, M., Wang, H., Wang, Y.-X. (2024). Language Agent Tree Search Unifies Reasoning, Acting, and Planning in Language Models. *ICML 2024*. [arXiv:2310.04406](https://arxiv.org/abs/2310.04406)

[22] Zhou, S., Xu, F. F., Zhu, H., et al. (2024). WebArena: A Realistic Web Environment for Building Autonomous Agents. *ICLR 2024*. [arXiv:2307.13854](https://arxiv.org/abs/2307.13854)

[23] Singh, A., Ehtesham, A., Kumar, S., Khoei, T. T. (2025). Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG. [arXiv:2501.09136](https://arxiv.org/abs/2501.09136)

[24] Dorigo, M., Stützle, T. (2004). *Ant Colony Optimization*. MIT Press. doi:10.7551/mitpress/1290.001.0001

[25] Grassé, P.-P. (1959). La reconstruction du nid et les coordinations interindividuelles chez *Bellicositermes natalensis* et *Cubitermes* sp. La théorie de la stigmergie. *Insectes Sociaux* 6(1):41–80. doi:10.1007/BF02223791

[26] Bonabeau, E., Dorigo, M., Theraulaz, G. (1999). *Swarm Intelligence: From Natural to Artificial Systems*. Oxford University Press.

[27] Theraulaz, G., Bonabeau, E. (1999). A Brief History of Stigmergy. *Artificial Life* 5(2):97–116. doi:10.1162/106454699568700

[28] Dorigo, M., Maniezzo, V., Colorni, A. (1996). Ant System: Optimization by a Colony of Cooperating Agents. *IEEE Trans. SMC–B* 26(1):29–41. doi:10.1109/3477.484436

[29] Belcak, P., Heinrich, G., Diao, S., et al. (2025). Small Language Models are the Future of Agentic AI. NVIDIA Research. [arXiv:2506.02153](https://arxiv.org/abs/2506.02153)

[30] Lu, Z., Li, X., Cai, D., et al. (2024). Small Language Models: Survey, Measurements, and Insights. [arXiv:2409.15790](https://arxiv.org/abs/2409.15790)

[31] Gunasekar, S., Zhang, Y., Aneja, J., et al. (2023). Textbooks Are All You Need. [arXiv:2306.11644](https://arxiv.org/abs/2306.11644)

[32] Qwen Team (2025). Qwen2.5 Technical Report. [arXiv:2412.15115](https://arxiv.org/abs/2412.15115)

[33] Gemma Team, Google DeepMind (2024). Gemma 2: Improving Open Language Models at a Practical Size. [arXiv:2408.00118](https://arxiv.org/abs/2408.00118)

[34] Grattafiori, A., et al. (2024). The Llama 3 Herd of Models. [arXiv:2407.21783](https://arxiv.org/abs/2407.21783)

[35] Robertson, S., Zaragoza, H. (2009). The Probabilistic Relevance Framework: BM25 and Beyond. *Foundations and Trends in IR* 3(4):333–389. doi:10.1561/1500000019

[36] Cormack, G. V., Clarke, C. L. A., Buettcher, S. (2009). Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods. *SIGIR 2009*, 758–759. doi:10.1145/1571941.1572114

[37] SQLite Consortium. SQLite FTS5 Extension. [sqlite.org/fts5.html](https://www.sqlite.org/fts5.html)

[38] Zhong, W., Guo, L., Gao, Q., Ye, H., Wang, Y. (2024). MemoryBank: Enhancing Large Language Models with Long-Term Memory. *AAAI 2024*. [arXiv:2305.10250](https://arxiv.org/abs/2305.10250). doi:10.1609/aaai.v38i17.29946

[39] Pirolli, P., Card, S. K. (1999). Information Foraging. *Psychological Review* 106(4):643–675. doi:10.1037/0033-295X.106.4.643

[40] Pirolli, P. (2007). *Information Foraging Theory: Adaptive Interaction with Information*. Oxford University Press. doi:10.1093/acprof:oso/9780195173321.001.0001

---

## Appendix A — A Worked Hunt

**Question (multi-hop, 3 chained facts):** *"Which platform hosts the sensor that triggered the April incident, and what dataset records its readings?"*

**What top-k RAG does:** embeds the question; retrieves six chunks about "April incident" (the incident report ranks highest); the report names the sensor but not its platform; the model answers *"the context does not specify which platform hosts the sensor."* Correct, useless, 0 points, ~800 tokens.

**What the monkey does:**

```
hop 1  locate("April incident sensor platform")           ~310 tok
       → #1 events/april-incident (score .94, heat .12)
hop 2  look(events/april-incident)                        ~420 tok
       → summary names sensor-t4; edges: [caused-by → sensors/sensor-t4]
       → does NOT open the body: the scent already says where to go
hop 3  look(sensors/sensor-t4)                            ~390 tok
       → summary: "...mounted on plataforma-tambor since 2025-11..."
       → edges: [part-of → platforms/tambor], [recorded-in → data/readings-t4]
hop 4  pick(sensors/sensor-t4, section="Telemetry")       ~280 tok
       → confirms dataset id + column names for the readings
hop 5  query(data/readings-t4, "SELECT MAX(ts) ...")      ~90 tok
       → live confirmation the dataset is the recording target
```

**Answer:** *"Platform **tambor**; readings recorded in dataset **readings-t4**"* — with the full trail as its receipt. Total: **~1,490 observation tokens across 5 hops**, every one of them relevant. Because the winning trail was ≥4 hops, the agent grafts a shout — `events/april-incident —discovered-shortcut→ platforms/tambor` (confidence 0.5) — and the *next* monkey asking anything similar gets there in 2 hops. The corpus just got better because someone used it.

The failure trace is as instructive as the success: this hunt is structurally impossible for top-k RAG at any k, because no similarity function maps "April incident" onto a dataset passport that never mentions April — only the *walk* connects them.

---

## Appendix B — Five-Minute Quickstart

```bash
git clone {{REPO_URL}} && cd monkeyllm
python -m venv .venv && . .venv/bin/activate && pip install -e .
python -m pytest -q                          # 272 tests, green
python forests/scripts/build_fixture.py      # build the demo forest (82 nodes)
python -m monkeyllm.cli validate --forest forests/forest-fixture

# point the demo at ANY OpenAI-compatible endpoint — local llama.cpp is enough:
python scripts/serve_llm.py --model <your-local-12B>     # or set MONKEYLLM_LLM_ENDPOINT
python examples/demo/run_demo.py             # watch a monkey hunt, hop by hop

# reproduce the headline table (§5.2), including topk's 0/11:
python bench/run_bench.py --arms monkey,topk,iter --questions bench/questions-v3.json
```

The forest is just Markdown in a git repo — open it in any editor, `git log` it, and watch `graft(...)` commits appear as agents learn.

---

## Appendix C — Glossary

| Term | Meaning |
|---|---|
| Forest | The corpus: hierarchical Markdown graph with embedded git |
| Branch / Banana | Index node (`_index.md`) / atomic knowledge leaf |
| Monkey / Troop | One navigating SLM agent / N parallel agents + judge |
| Vine | MCP server exposing the 10 primitives |
| Hop | One read-primitive call |
| Scent | ≤60-token machine-validated summary + metadata enabling zero-read decisions |
| Pheromone / Heat | Usage weights on nodes, evaporating with a 30-day half-life |
| Whisper / Shout | Session-scoped shared heat / permanent agent-minted shortcut link |
| Gardener / Curator | Ingest pipeline / LLM summarizer & edge proposer at ingest |
| Ranger | Maintenance daemon: evaporation, link promotion/pruning, health |
| Canopy | Optional vector index enabling hybrid locate |
| SCENT / FLESH / BONE | Storage tiers: metadata / converted text / raw binaries |
| Forest Principle | Spend intelligence on the environment so you can spend less on the model |

---

## Appendix D — Forensic and Cryptographic Evidence of Authorship

This appendix collects the technical artifacts anchoring the authorship claim in independently verifiable evidence. Items marked **REQUIRED** are minimal to establish strong prior art.

### D.1 Timestamping

**REQUIRED.** Publication is timestamped at {{PUBLICATION_DATE}} (America/São_Paulo). The document is mirrored to at least three independent immutable hosts before any commercial discussion:

1. **arXiv pre-print** — category `cs.CL`, cross-list `cs.IR` and `cs.MA` (the stigmergic layer is multi-agent). Generates permanent DOI and date stamp.
2. **Zenodo deposit** — free, CERN-hosted, generates DOI.
3. **Git commit** at {{REPO_URL}} — initial commit SHA as Git-native timestamp.
4. **Wayback Machine snapshot** of {{CANONICAL_URL}} taken immediately after publication.

### D.2 Document hash

**REQUIRED.** Computed once the manuscript is frozen and published *alongside* the document (a separate `HASHES.txt`, the repository README, the OpenTimestamps `.ots` file, and the announcement post) — never embedded inside it, to avoid the circular-dependency problem:

```
SHA-256 of monkeyllm-paper-v1.0.0.md: [computed AFTER finalization]
```

### D.3 Blockchain timestamping (recommended)

```bash
pip install opentimestamps-client
ots stamp monkeyllm-paper-v1.0.0.md   # keep the resulting .ots with the document
```

### D.4 Cryptographic signature (recommended)

The author signs the canonical document with GPG; public key fingerprint:

```
2D791FD6704739CF25FD0954E67A8C2561C414E6
```

Verification:

```bash
gpg --fetch-keys {{PUBLIC_KEY_URL — e.g. https://monkeyllm.com/jimmy.asc}}
gpg --verify monkeyllm-paper-v1.0.0.md.asc monkeyllm-paper-v1.0.0.md
```

### D.5 Social and identity linkage

| Channel | Handle / URL | Purpose |
|---|---|---|
| ORCID iD | [0009-0007-1022-9510](https://orcid.org/0009-0007-1022-9510) | Academic identity |
| GitHub | {{GITHUB_PROFILE — e.g. https://github.com/JimmyWesley}} | Source-code authorship |
| Domain registrant | {{CANONICAL_URL}} — registered to Jimmy Wesley Maciel Soares | WHOIS record |
| LinkedIn | https://www.linkedin.com/in/jimmy-wesley/ | Professional identity |
| X / Twitter | https://x.com/JimmyWesleyBr | Public announcement & archival |

A public announcement is made on at least one timestamped platform immediately after publication, linking the canonical URL, and captured via Wayback Machine the same day.

---

## How to cite this paper

**Plain text:**

```
Soares, J. W. M. (2026). MonkeyLLM: Stigmergic Navigation of Knowledge
Forests — Replacing Retrieval-Augmented Generation with Agentic Foraging
by Small Language Models. Paper v1.0.0, {{PUBLICATION_DATE_SHORT}}.
ORCID: 0009-0007-1022-9510. {{CANONICAL_URL}}
```

**BibTeX:**

```bibtex
@misc{soares2026monkeyllm,
  author       = {Soares, Jimmy Wesley Maciel},
  title        = {{MonkeyLLM}: Stigmergic Navigation of Knowledge Forests ---
                   Replacing Retrieval-Augmented Generation with Agentic
                   Foraging by Small Language Models},
  year         = {2026},
  version      = {1.0.0},
  howpublished = {Preprint},
  url          = {{{CANONICAL_URL}}},
  orcid        = {0009-0007-1022-9510},
  note         = {Reference implementation: {{REPO_URL}}}
}
```

**APA 7:**

```
Soares, J. W. M. (2026). MonkeyLLM: Stigmergic navigation of knowledge
forests — replacing retrieval-augmented generation with agentic foraging
by small language models (Version 1.0.0). {{CANONICAL_URL}}
```

**IEEE:**

```
J. W. M. Soares, "MonkeyLLM: Stigmergic Navigation of Knowledge Forests —
Replacing Retrieval-Augmented Generation with Agentic Foraging by Small
Language Models," Preprint v1.0.0, 2026. [Online]. Available: {{CANONICAL_URL}}
```

---

## Remaining fields to fill

| Placeholder | Where | Note |
|---|---|---|
| `{{CONTACT_EMAIL}}` | Header | contact@monkeyllm.com or services@idie.ai |
| `{{CANONICAL_URL}}` / `{{REPO_URL}}` / `{{GITHUB_PROFILE}}` | Header, App. B/D, citations | Final public URLs |
| `{{PUBLICATION_DATE}}` / `{{PUBLICATION_DATE_SHORT}}` | Header, App. D, citations | ISO 8601 with timezone |
| `{{CODE_LICENSE}}` | Header | T05 suggests Apache-2.0 |
| `{{PUBLIC_KEY_URL}}` | App. D.4 | Where the GPG public key will live |
| `{{ADDITIONAL_ACKNOWLEDGMENTS}}` | Acknowledgements | Optional |
| `{{TODO: ...}}` (×3) | §6.1, §6.3, §8 | Future experiments — run or delete |
| `{{OPTIONAL: statistical treatment}}` | §4 | Add if bench rerun with repeats |
