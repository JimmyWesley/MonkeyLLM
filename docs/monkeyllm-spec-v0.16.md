# MonkeyLLM — Technical Specification v0.16 (Phase 0/1/2 + host layer)

**Audience:** development team.
**Scope:** normative specification of the forest dialect (`schema.md`), the I/O contracts of the Vine protocol's primitives (MCP), the host layer that serves them to many principals (Part J), and the Phase 0 acceptance criteria.
**Companion document:** `monkeyllm-arquitetura.md` (architectural view).
**Convention:** the words MUST, MUST NOT, MAY follow the spirit of RFC 2119.

> Language note: as of the T02 translation pass (2026-07-02) the entire
> document is English. As of v0.5 every **contract token** (type/rel/enum
> values, parsed section headings) is English regardless of prose language.

**Changelog v0.15 → v0.16 — the console becomes usable by someone who has
not read this document:**

v0.14 and v0.15 gave the Station a front door and a choice of reader. Both
were specified from the storage model outward, and the console inherited
that: it asked an operator for capability sets and comma-separated branch
prefixes, offered no way to start a forest or put anything into one, and
spoke one language in one theme. A governed knowledge base that only its
own author can operate is not a product. v0.16 specifies the console as a
first-class contract rather than a rendering of the registry.

- **J.5 rewritten** — a normative information architecture (nine consoles
  in three groups), the rule that **the console MUST address the operator
  in the operator's vocabulary**, not the policy model's, and two
  requirements the previous version left to taste: localisation
  (English, Portuguese, Spanish) and both light and dark presentation.
  The no-side-channel rule is unchanged and now explicitly covers strings:
  a translation MUST NOT alter what a surface returns.
- **J.7 Forest lifecycle** — `POST /v1/admin/forests`, so a deployment can
  reach its second forest without shell access to the volume. Creation is
  A.5 `init_forest` and nothing else; the id is validated against path
  escape before it is a path, and the creator is granted the forest so a
  newly created forest is never orphaned.
- **J.8 Ingest surface** — the Gardener (Part G) reached over REST, with
  `adopt`, `sync` and a **staged upload** for operators who have a browser
  and no shell. Requires the `ingest` capability; the destination branch is
  scope-checked, so ingest cannot be used to write where reads are denied.
- **The naming reuse, stated plainly:** J.7 named "out of scope for Part
  J" in v0.14 and became J.11 in v0.15. In v0.16 the free slot is reused
  for the forest lifecycle. Cite J.11 for the exclusions.
- New acceptance criterion **F.20** (console: every string localised in all
  three languages, both themes, and the scoped principal's console shows a
  scoped world; forest creation refuses path escape; ingest refuses to
  write outside scope).

**Changelog v0.14 → v0.15 — J.10, per-forest inference (the forest picks its
own model):**

Part J gave forests a front door; v0.15 lets each one choose who reads it.
A forest is not one workload: ingest wants a careful summariser whose output
every later hop navigates by, while answering wants a fast reader that
follows instructions. One global `MONKEYLLM_LLM_*` cannot express that, and
it cannot express "this corpus stays on a local endpoint while that one uses
a hosted model" either.

- **J.10 Providers and role bindings** — operators register any
  OpenAI-compatible `/v1` (OpenRouter, LiteLLM, vLLM, local llama.cpp) in
  the host registry, then bind a model per `(forest, role)` with
  `role ∈ {ingest, answer}`. Credentials are write-only across every
  surface: the API accepts a key and reports only whether one is set.
- **J.10.3 Model-backed composites** — `answer` (retrieval + the forest's
  answering model, returning a grounded reply with its evidence) and
  `curate` (re-summarise a node through the ingest model, under the A.4
  scent rules). Both are host composites, not primitives: the engine gains
  nothing.
- **The invariant that makes this safe:** the retrieval half runs through
  `ScopedVine` *before* the model is called, so a bound model only ever
  sees material the principal could already read. Binding a model MUST NOT
  become a way around J.3.
- New acceptance criterion **F.19** (secrets never returned; bindings
  refuse unknown providers/roles; the answering model receives only
  in-scope material).

**Changelog v0.13 → v0.14 — Part J, the Station (the forest gets a front
door):**

Everything up to v0.13 assumes one operator who owns the filesystem.
Corporate self-hosting needs the shape the database products converged on:
an untouched engine wrapped by a host that adds identity, policy, audit and
a friendly surface. Part J specifies that host — and specifies it as a
**privileged client**, not an extension: the engine gains nothing, loses
nothing, and its test suite MUST pass unedited.

- **J.1 The Station** — one self-hostable service mounting a forest
  registry (the `--root` resolution that already exists) and exposing
  three surfaces — REST, MCP, Studio — over exactly one enforcement core.
  No surface may reach an unscoped `Vine`.
- **J.2 Identity** — principals (users and service tokens), per-forest
  roles, API keys now and OIDC later. Identity and policy live in the
  **host registry**, never inside a forest: forests are content.
- **J.3 Policy (`ScopedVine`)** — deny-by-default grants over **branch
  prefixes** plus a capability set, with one enforcement rule per
  primitive. Two invariants make it trustworthy rather than merely
  configured: scope filtering MUST precede budgeting (no truncation
  oracle) and out-of-scope MUST be indistinguishable from absent (no
  existence oracle) — including through `move`'s edges, which would
  otherwise leak a forbidden node's existence.
- **J.4 Audit** — writes stay git commits, now stamped with the acting
  principal; reads extend the Part D telemetry with principal identity.
- **J.5 Studio** — the web console, itself a plain REST client with no
  privileged side-channel.
- New acceptance criterion **F.18** (the leak suite: one test per
  primitive per surface, plus the two oracle invariants).

**Changelog v0.12 → v0.13 — branch rollup + Landmarks (the map grows a
sense of place):**

The branch hierarchy already occupies the position that graph-RAG systems
pay dearly to discover (hierarchical communities); what it lacked was
synthesized content at each level. Two additions, zero new primitives:

- **G.4.4 Branch rollup** — after adopt/sync curation, the Gardener MAY
  synthesize branch (`_index.md`) frontmatter summaries bottom-up (deepest
  branch first) from the children's entry lines. Scope is strictly
  branches with `source: ingest` (hand-authored branch summaries are never
  rewritten; an explicit `--all` override exists). A.4 summary rules apply
  (validate-and-retry); LLM failure falls back to a deterministic composed
  summary and never blocks (same posture as G.4.2). Writes go through the
  C.8 `graft` path, so verbatim propagation into parent index entries and
  `.md`-only commits are inherited, not reimplemented. Rollup cost is
  O(branches), not O(nodes) — the lazy end of the graph-RAG spectrum.
- **A.5 entry-sync rule tightened** — when a summary change propagates
  into a `## Sub-branches` entry, the entry's trailing coverage suffix
  (`. N bananas, M sub-branches.`) MUST be preserved (previously it was
  silently dropped by the sync rewrite).
- **A.5 `## Landmarks` implemented as a Ranger duty (H.7)** — the master
  `_index.md`'s Landmarks section (already normative since v0.5) is now
  populated mechanically: top 10-20 highest-degree non-branch nodes from
  the catalog's edges table, entry lines with summaries, idempotent
  refresh through the audited `.md`-only path (`ranger(landmarks): …`).
  Zero LLM involvement.
- New acceptance criterion **F.17** (rollup scope/fallback/propagation +
  Landmarks idempotence).

**Changelog v0.11 → v0.12 — Gardener v2: native DOCX + edge proposals (the
forest starts weaving itself):**

Two Gardener extensions, both strictly inside the edges-only surface (G.2):

- **G.2.1 DOCX built-in converter** — `.docx` joins the built-ins when
  `python-docx` (MIT; lxml, BSD) is importable, mirroring the `openpyxl`
  pattern. Single-pass `w:t` traversal in document order: body paragraphs
  (style-mapped headings), tables (→ pipe tables), and text inside embedded
  text boxes (`wps:txbx` / legacy `v:textbox`); fragmented runs merge
  naturally by joining a paragraph's `w:t` descendants. Headers/footers are
  EXCLUDED (page-number/letterhead boilerplate is scent noise). Technique
  derived from the owner's pdf-replace project (MIT-clean reading side).
  No `python-docx` → `.docx` files report `unsupported`, never a crash.
- **G.4.2.1 Edge proposals** — LLM curation MAY now propose `related-to`
  links from the adopted node to EXISTING nodes, each carrying link-level
  `confidence: 0.3` (the C.8 ladder's bottom rung). Candidates come from
  the catalog (BM25 over curated metadata); the model can only pick from
  the offered list — a hallucinated target is structurally impossible.
  This closes the loop with Part H: the Gardener proposes, usage heats,
  the Ranger promotes (0.8) or prunes. Entity EXTRACTION (creating new
  `entity` nodes) stays deferred: it needs a placement policy and a
  `same-as` dedup story first.
- New acceptance criterion **F.16** (DOCX fidelity + proposal guard rails).

**Changelog v0.10 → v0.11 — the map is not the territory (tiered storage,
big sources, S3-ready):**

A 2 TB source must not require 4 TB locally. The forest splits into three
tiers — SCENT (passports: summaries/outlines/links, ~0.1% of source size,
always local, in git), FLESH (converted full text, ~1-5%, local, git or
derived cache), BONE (raw binaries, 95%+, stay at the source / object
storage, fetched rarely). New normative items:

- **G.7 Content & archive policies** — per-adoption `content:
  inline | cached | reference` and `archive: never (default) | always`.
  Non-inline bodies are resolved lazily by `pick`/`sniff`; the map
  (locate/look/scan, heat, curation) never needed the body and is
  unaffected. `archive: never` kills the redundant `_assets/` copy when
  the source is durable.
- **G.8 Targeted sync & triggers** — `sync(path=...)` reprocesses a single
  source file; an mtime+size fast-path avoids re-hashing unchanged trees.
  Event sources (filesystem watchers, S3/Drive push notifications) are
  EDGES that call targeted sync; **events trigger, the hash-diff
  reconciler stays authoritative** (lost events are healed by the next
  full sync).
- **G.9 Payload fetchers** — `payload`/`source_path` MAY carry a scheme
  (`file://` implicit; `s3://` via optional MIT extra). Remote payloads
  download on first use into `_derived/payloads/` (hash-validated cache).
  Dataset `.db` files are **local-first by design** (SQLite cannot be
  queried remotely; hot knowledge bases need sub-ms reads) — object
  storage holds them only as backup/cold tiers.
- **H.6 Cache eviction** — the Ranger evicts cold entries from
  `_derived/payloads/` (LRU by last access; config `payload_cache_gb`).
- **Part I — Snapshots**: `vine snapshot create|restore` packages the
  forest as a `git bundle` (full commit history travels along) +
  compression, optionally uploaded to object storage; payload sidecar
  optional. The Ranger MAY schedule snapshots (backup policy).
- Informative (G.4 note): **progressive curation** — adopt the skeleton
  deterministically first (the engine answers immediately with weak
  scent), then LLM-curate as a background queue prioritized by heat: the
  pheromone tells the Gardener where to polish first. Querying an
  UNMAPPED source per-question is the anti-pattern this project exists to
  kill (O(corpus) per question vs O(corpus) once + O(hops) per question).
- New acceptance criterion **F.15** (policies + targeted sync; fetcher/
  snapshot coverage lands with their implementations).

**Changelog v0.9 → v0.10 — Part H: the Ranger (long-term maintenance — the
forest forgets, confirms and warns):**

The pheromone layer only compounds if it can also FORGET: without
evaporation every trail saturates at 1.0 and heat stops carrying signal;
without pruning, agent proposals (confidence 0.3/0.5) accumulate as noise.
New normative items:

- **Part H (Ranger)** — the maintenance daemon: heat evaporation with a
  configurable half-life over `_derived/trails.db` (H.1); promotion and
  pruning of uncertain links — links born with link-level
  `confidence < 1.0` are the ONLY Ranger-managed edges (H.2); a read-only
  health report: `needs_split`, fat nodes, lint issues, stale passports,
  low-confidence inventory (H.3); on-demand run + service loop (H.4).
- Ranger is **trusted infrastructure** (like the Gardener): evaporation
  touches only the derived layer (no commits — `_derived/` is disposable);
  promotion/pruning write through the audited `.md`-only path with commit
  messages `ranger(promote): …` / `ranger(prune): …`.
- The Ranger NEVER deletes nodes, never touches structural edges or any
  link without a link-level confidence field, and never performs `same-as`
  physical compaction (still human-approved, still out of scope).
- New acceptance criterion **F.14** (synthetic-clock evaporation,
  promotion/pruning safety, health report).

**Changelog v0.8 → v0.9 — Part G: the Gardener (brownfield ingest, the
forest learns to grow itself):**

The dominant real-world scenario is **adoption**: the engine is pointed at a
directory tree already full of documents ("mata alta") and must curate all
of it — then notice when source files change. New normative items:

- **Part G (Gardener)** — the ingest pipeline: passport policy (G.1),
  public converter contract with three discovery sources — forest-config
  command hooks, `monkeyllm.converters` entry points, built-ins (G.2);
  `adopt` (mirror an existing tree: folders → branches, files → passports,
  deterministic placement) and `sync` (hash-diff incremental update) (G.3);
  curation stage with forest-level curation config and `on_curate` hooks —
  the only LLM-dependent stage, always skippable (G.4); media via the same
  converter contract: transcript/description is the body, the raw asset is
  the payload (G.5).
- **C.7.1 extension: initial `rows` at birth** — `plant` of a dataset MAY
  carry `rows` per table, inserted **parameterized** (never SQL text) before
  `payload_hash` is computed. Bulk loads bypass neither the schema
  validation nor A.3.1 — and avoid `tend`'s keyword scanner false-positives
  on arbitrary data.
- **Extension surface is edges-only (normative)**: plugins exist for what
  goes IN (converters, curation hooks). The primitives' semantics, budgets
  and security guards are NOT extensible. UIs/automations (dashboards,
  upload bots) are *clients* of the MCP server or the library — they need
  no plugin API.
- New acceptance criterion **F.13** (adopt/sync end-to-end).

**Changelog v0.7 → v0.8 — dataset birth: declarative schema in `plant`
(Phase 2, the living bank grows its own organs):**

`tend` (C.10) writes rows into datasets that already exist; until now no
primitive could *create* a dataset — the `.db` was born only in offline
generators. v0.8 closes the loop so an agent can collect data (web, PDFs,
conversations), give it a structured home, and fill it — all through the
primitives. Normative items:

- **C.7.1 Dataset planting** — `plant` of a `type: dataset` node accepts an
  optional **declarative `schema`** object (tables → columns → types). The
  Vine generates the DDL itself (names regex-validated, types from an
  allowlist), creates the SQLite payload, computes `payload_hash`, and
  auto-generates the `## Query manual` body section from the schema. **No
  raw DDL ever comes from the model** — creation-time structure is data,
  not SQL.
- **`tend` is unchanged**: DDL stays forbidden there forever. The separation
  is temporal — creation (rare, structured, validated whole) vs operation
  (frequent, single-statement DML). `ALTER TABLE` after birth is out of
  scope (plant a new dataset and migrate, or wait for the Gardener).
- A.3.1 holds with zero new machinery: the payload is created on the
  filesystem, only the `.md` (with `payload` + `payload_hash`) is committed.
- New acceptance criterion **F.12** (schema validation, payload creation,
  auto manual, atomic rollback — covered by tests).

**Changelog v0.6 → v0.7 — `tend`: dataset writes (Phase 2 entry, the living
bank):**

`query` stays read-only by design; agent writes to dataset payloads get
their own primitive with a hard guard rail. New normative items:

- **C.10 `tend(id, sql)`** — the 10th primitive: single-statement
  INSERT/UPDATE/DELETE on a `type:dataset` node's SQLite payload, with an
  audit commit of the node's `.md` (`payload_hash` refresh) — the binary
  still never enters git (A.3.1 unchanged). Full contract in C.10.
- **Lint: payload drift warning** — `vine validate` MUST warn when a node's
  `payload_hash` no longer matches the payload file's sha256 (completes the
  A.3 drift-detection promise; `tend` keeps the hash fresh, out-of-band
  edits become visible).
- New acceptance criterion **F.11** (tend guard rails + audit, covered by
  tests).

**Changelog v0.5 → v0.6 — shout trigger measures the real trail (Part D):**

The shout never fired in practice: 39 successful hunts across the fixture and
the bench forest produced zero shortcut suggestions. Root cause: the trigger
reused `hops-to-banana`, which counts only `look`+`move` calls before the
FIRST `pick`/`query` — but agents traverse deep chains with **pick chains**
(`locate → pick → pick → pick`), so the counter stays at 0–2 even on long
winning trails. Normative changes:

- New session metric **`trail_len`**: the number of traced read-primitive
  calls (`locate`, `sniff`, `look`, `move`, `scan`, `pick`, `query`) made
  strictly BEFORE the first harvest (`pick`/`query`) of a node listed in
  `outcome.answer_nodes`. `null` when no answer node was harvested.
- `close_session` MUST suggest shortcuts (`suggest_shortcuts`) when
  `trail_len >= 4` (threshold unchanged). The shout edge itself is still the
  orchestrator's decision (C.8 reinforce-before-create applies).
- **`hops-to-banana` is unchanged** (look+move before the first harvest) —
  it stays a Monkey Bench metric for longitudinal comparability; it is no
  longer the shout trigger.

**Changelog v0.4 → v0.5 — canonical English vocabulary (normative):**

The tool's vocabulary is English. Every contract token that was Portuguese
is renamed; the Portuguese tokens are **removed** (clean break, pre-release —
no alias layer). A forest MAY still declare extra types/rels of its own in
`_meta/schema.md` (the dialect stays data-driven), but everything the Vine
hardcodes, emits or parses now uses the English tokens below.

| Kind | v0.4 (removed) | v0.5 (canonical) |
|---|---|---|
| node type | `galho` | `branch` |
| node type | `nota` | `note` |
| node type | `documento` | `document` |
| node type | `entidade` | `entity` |
| node type | `conceito` | `concept` |
| node type | `evento` | `event` |
| node type | `midia` | `media` |
| node type | `dataset` | `dataset` (unchanged) |
| rel | `parte-de` / `contem` | `part-of` / `contains` |
| rel | `relacionado-com` | `related-to` |
| rel | `mencionado-em` / `menciona` | `mentioned-in` / `mentions` |
| rel | `autor` / `autor-de` | `author` / `author-of` |
| rel | `comparado-com` | `compared-with` |
| rel | `derivado-de` / `origem-de` | `derived-from` / `origin-of` |
| rel | `same-as` | `same-as` (unchanged) |
| rel | `atalho-descoberto` | `discovered-shortcut` |
| rel | `sucede` / `precede` | `succeeds` / `precedes` |
| `entity_kind` | `pessoa`, `organizacao`, `produto`, `lugar`, `outro` | `person`, `organization`, `product`, `place`, `other` |
| `source` | `agente` | `agent` (`manual`, `ingest` unchanged) |
| A.5 heading | `## Sub-galhos` | `## Sub-branches` |
| A.5 heading | `## Bananas diretas` | `## Direct bananas` |
| A.5 heading | `## Trilhas cruzadas` | `## Cross trails` |
| A.5 heading | `## Landmarks` | `## Landmarks` (unchanged) |
| `coverage` format | `"N bananas, M sub-galhos"` | `"N bananas, M sub-branches"` |
| dataset body section | `## Manual de consulta` | `## Query manual` (source of C.2 `query_manual`) |
| A.4 anti-patterns | "este documento descreve", "arquivo contendo" | "this document describes", "file containing" |
| C.8 shout metadata | `discovered_by: agente` | `discovered_by: agent` |

Test data remains Portuguese where it is content (fixture corpus prose,
titles, summaries, ids, tags, demo/bench questions and prompts); only the
structural tokens above change there.

**Changelog v0.3 → v0.4:**

- **C.0 Forest registry (multi-forest serving)**: one MCP server MAY host many
  forests under a root directory (`vine serve --root DIR`). Every tool gains
  an optional trailing `forest: string` parameter selecting the target forest;
  a new `forests()` tool lists what the registry serves. Forests open lazily
  on first touch (auto-index included). Single-forest mode (`--forest`) keeps
  the previous behavior — `forest` is optional there — so v0.3 clients are
  not broken.
- New acceptance criterion F.10 (registry: selection, lazy open, path safety,
  single-forest backward compatibility).

**Changelog v0.2 → v0.3:**

- New composite MCP tool **C.6c `harvest`**: zero-LLM, one-shot retrieval for
  clients that bring their own model. Fuses `locate` + `sniff` (RRF), returns
  ranked bananas with full body or matched sections plus exact snippets.
  It is an orchestration over existing primitives — the nine primitive
  contracts are untouched.
- Three integration modes documented (C.6c intro): direct navigation
  (client LLM drives the primitives), harvest (one call, evidence back),
  concierge (local SLM hunts and answers). Configuration picks the default;
  the MCP client's LLM may choose per call.
- New acceptance criterion F.9 (harvest quality + budget).

**Changelog v0.1 → v0.2:**

- New read primitive **C.6b `sniff`** (the sniffer): literal search over node **bodies**, returning node + section + snippet. Complements `locate` (which stays restricted to curated metadata — C.1 contract intact) covering the case "exact term buried in the body, invisible to summary/tags".
- **A.3.1 Binary payload policy**: binaries never enter the forest's Git — Vine versions `.md` only (enforced at the commit layer); payloads are referenced by `payload` + `payload_hash` and excluded by the forest's `.gitignore`.
- Acceptance criterion F.1 updated to include C.6b; new criteria F.7 (sniff quality) and F.8 (payloads outside Git).
- Nothing else changes: every other contract is identical to v0.1 (which stays archived for history).

---

## Part A — The Forest Dialect (`_meta/schema.md`)

`schema.md` is a living file inside the forest that declares the valid types. The Vine MUST validate every write (`plant`/`graft`) against it. The agent MAY read it via `look("_meta/schema")` to learn the dialect in 1 hop.

### A.1 Node types (`type`)

| `type` | Description | Payload | Harvest verb |
|---|---|---|---|
| `branch` | Index file (`_index.md`) of a folder | — | `look` |
| `note` | Free-text knowledge (default banana) | — | `pick` |
| `document` | Converted document (PDF/DOCX origin) | original in `_assets/` | `pick` |
| `dataset` | Tabular data | sibling SQLite (`.db`) | `query` |
| `entity` | Person, organization, product, place (subtype in `entity_kind`) | — | `pick` |
| `concept` | Definition / technical term | — | `pick` |
| `event` | Dated fact (meeting, decision, release) | — | `pick` |
| `media` | Image/audio/video with description or transcript | original in `_assets/` | `pick` |

Rules:
- New types MUST be added to `schema.md` before first use; the Vine rejects an unknown `type` (`E_SCHEMA` error).
- `entity` MUST have `entity_kind` ∈ {`person`, `organization`, `product`, `place`, `other`}.

### A.2 Edge types (`rel`)

Edges are directed, typed, and declared in the source node's frontmatter (`links:`). The derived layer materializes the inverses automatically.

| `rel` | Inverse (derived) | Semantics |
|---|---|---|
| `part-of` | `contains` | Logical hierarchy (not the physical folder hierarchy) |
| `related-to` | `related-to` | Generic association (symmetric) |
| `mentioned-in` | `mentions` | Entity cited in a document |
| `author` | `author-of` | Authorship |
| `compared-with` | `compared-with` | Technical contrast (symmetric) |
| `derived-from` | `origin-of` | Provenance (note derived from document, dataset from export, etc.) |
| `same-as` | `same-as` | **Soft merge** of duplicate entities (symmetric) |
| `discovered-shortcut` | — | The monkey's shout (created by `graft`, see Part C.8) |
| `succeeds` | `precedes` | Temporal order between events/versions |

Rules:
- A `rel` outside this table → `E_SCHEMA` error (the table grows by editing `schema.md`, never ad-hoc).
- `same-as` MUST NOT delete nodes; physical merging is the Ranger's compaction alone (out of Phase 0 scope).
- Maximum of 50 `links` per node; above that the node is a candidate to become a branch (signal for the Ranger).

### A.3 Normative frontmatter

Fields required on **every** node:

```yaml
id: string            # stable slug, unique in the forest, = relative path without .md
type: string          # one of the A.1 types
title: string         # human title (mutable; id never changes)
summary: string       # 1-3 sentences, <= 60 tokens. THE SCENT. See A.4.
created: date         # ISO 8601
updated: date         # ISO 8601, refreshed on every graft
```

Optional fields:

```yaml
tags: [string]            # free vocabulary, lowercase, no accents
links: [{rel, target}]    # typed edges (A.2)
confidence: float         # 0.0-1.0; default 1.0; <1.0 = unconfirmed knowledge
source: enum              # manual | ingest | agent
payload: string           # sibling file name (datasets/media)
payload_type: enum        # sqlite | pdf | docx | image | audio
payload_hash: string      # sha256 of the payload (drift detection)
entity_kind: enum         # only for type: entity
aliases: [string]         # alternate names (used by lexical locate)
```

Rules:
- `id` is immutable. Renaming = creating a new node + `same-as` + tombstone (out of Phase 0 scope; renaming is forbidden in Phase 0).
- The parser MUST reject invalid frontmatter with `E_FRONTMATTER` and the field's path.

#### A.3.1 Binary payload policy (v0.2)

Binaries **never enter the forest's Git**. Normative:

1. The Vine MUST NOT version anything beyond `.md`: `plant`/`graft` stage only markdown files (hard guard at the commit layer, not convention).
2. The forest's `.gitignore` MUST exclude binary payloads (`*.db`, `*.sqlite`, `_assets/`), plus `_derived/` and `.vine.lock`.
3. The payload lives on the filesystem next to the node (or in external storage, in future phases) and the **node** versions only the reference: `payload` (name) + `payload_hash` (sha256). Binary drift is detected by hash, not diff.
4. Rationale: Git delta-compresses text, not binaries — frequently updated payloads would blow up the repository. The versioned knowledge is the distilled layer (markdown); heavy data is referenced, not embedded.

### A.4 The `summary` specification (the most critical component)

The `summary` MUST let an SLM decide "does this node matter to me?" without opening the body. Normative format:

1. **Sentence 1:** what it is (category + subject).
2. **Sentence 2:** the key content (concrete numbers, names, time scope).
3. **Sentence 3 (optional):** what is NOT here / where the complement lives.

- Limit: 60 tokens (validated by the Vine at `plant`).
- FORBIDDEN: "This document describes...", "File containing..." (anti-patterns that spend tokens without scent).
- Good: `"Sales by region and SKU, Jan-Mar 2026, 14,302 rows with margin and channel. Does not include returns (see sales/returns-q1)."`

### A.5 The `_index.md` specification (branch)

Required structure, in this order:

```markdown
---
id: <folder>/_index
type: branch
coverage: "N bananas, M sub-branches"
updated: <date>
---

# <Region title>

> <1-2 sentences: what lives here + where to go if not here>

## Sub-branches
- [[<id>]] — <sub-branch summary>. <coverage>.

## Direct bananas
- [[<id>]] — <summary copied from the banana's frontmatter>

## Cross trails
- <reason> → [[<id>]]
```

Rules:
- Entries replicate the child nodes' `summary` VERBATIM (the Gardener/Vine keeps sync; humans do not hand-edit these lines).
- Sync rewrites of a `## Sub-branches` entry MUST preserve the trailing coverage suffix (`. N bananas, M sub-branches.`) — v0.13.
- A branch's frontmatter `summary` MAY be synthesized bottom-up by the Gardener from the children's entries (G.4.4) when the branch was born from ingest; hand-authored branch summaries are never rewritten.
- A branch with > 150 entries or > 3,000 tokens → `needs_split` flag for the Ranger.
- The master branch (`/_index.md`) MUST additionally contain a `## Landmarks` section (10-20 highest-degree nodes, with summary). The Ranger keeps it fresh mechanically (H.7, v0.13): top non-branch nodes by degree over the typed-edge table, idempotent, audited `.md`-only commit.

---

## Part B — Identity, Trail and Addressing

- **Canonical ID:** path relative to the root, without extension. E.g.: `projects/mixerllm/architecture`.
- **Trail:** list of IDs from the root to the node. E.g.: `["_index", "projects/_index", "projects/mixerllm/_index", "projects/mixerllm/architecture"]`.
- Wikilinks in the body use `[[id]]` or `[[id|text]]`. The parser resolves `[[...]]` only against canonical IDs (no fuzzy match — ambiguity is a Ranger lint error, not runtime guessing).

---

## Part C — Primitive Contracts (Vine server, MCP)

Transport: MCP (stdio for dev; HTTP/SSE on Docker). All responses in JSON. Errors follow `{error: {code, message, hint}}` with codes `E_NOT_FOUND`, `E_SCHEMA`, `E_FRONTMATTER`, `E_READONLY`, `E_QUERY_FORBIDDEN`, `E_TIMEOUT`, `E_LOCKED`.

### C.0 Forest registry — multi-forest serving (v0.4)

The product is filesystem-native: a folder is a forest, its `_index.md` is
the door. One server therefore serves N forests; the request picks one.

Server modes:

- **Single-forest** (`vine serve --forest DIR`): the v0.3 behavior. The
  `forest` parameter is optional everywhere; when present it MUST match the
  served forest's name (else `E_NOT_FOUND`).
- **Registry** (`vine serve --root DIR`): every subdirectory of `DIR`
  containing an `_index.md` is a servable forest, identified by its path
  relative to the root (nested ids like `clients/acme` are allowed). The
  `forests()` tool lists direct children; `forest` is REQUIRED on every other
  tool (`E_SCHEMA` with the available ids as hint when missing).

Rules (normative):

1. **Lazy open + auto-index**: a forest is opened on first touch; an empty
   catalog triggers a full reindex (Vine's standard first-touch behavior).
   Opened forests stay open for the server's lifetime; each has its own
   catalog, trails, tracer session and (when writable) writer lock.
2. **Path safety**: the resolved forest path MUST stay inside the root —
   `..`, absolute paths or symlink escapes are `E_NOT_FOUND`. A directory
   without `_index.md` is not a forest (`E_NOT_FOUND`).
3. **Isolation**: pheromone, traces and indexes never leak across forests
   (they live in each forest's own `_derived/`).
4. `forests()` → `{"forests": [{"id", "active"}], "mode": "registry"|"single"}`
   where `active` means already opened in this server.

```json
{"tool": "locate", "args": {"query": "...", "forest": "clients/acme"}}
```

Cross-cutting principle: **every response MUST fit the declared token budget**. The Vine truncates with an explicit `"truncated": true` marker — never silently.

### C.1 `locate(query: string, k: int = 5, scope: "all"|"branches"|"bananas" = "all", type_filter?: string) → LocateResult`

The **helicopter**: a location engine that drops the monkey in the region closest to the target — it never starts from the trunk. RRF fusion of vector search (over summaries) + BM25 (over title, aliases, tags, summary). In Phase 0, MAY be BM25-only (SQLite FTS5); the interface does not change once vectors land.

The index covers **two levels**: bananas (leaves) and branches (regions — every branch has its own summary, hence indexable). A branch result = **landing zone**: the monkey lands in the right region and navigates 1-2 hops with local context, instead of dropping onto a possibly wrong leaf. `scope: "branches"` is useful for broad questions ("what do we know about sales?"); `scope: "bananas"` for pointed ones.

```json
{
  "results": [
    {
      "id": "sales/_index",
      "kind": "branch",
      "type": "branch",
      "title": "Sales",
      "summary": "...",
      "trail": ["_index"],
      "coverage": "23 bananas, 4 sub-branches",
      "score": 0.91,
      "heat": 0.40
    },
    {
      "id": "projects/mixerllm/architecture",
      "kind": "banana",
      "type": "document",
      "title": "MixerLLM Architecture",
      "summary": "...",
      "trail": ["_index", "projects/_index", "projects/mixerllm/_index"],
      "score": 0.82,
      "heat": 0.31
    }
  ],
  "truncated": false
}
```

Budget: <= 800 tokens. Ordering: `score_final = rrf_score x (1 + alpha*heat)`, alpha default 0.3 (configurable; alpha=0 turns pheromone off).

### C.2 `look(id: string, fields?: [string]) → Digest`

The central operation. Hard budget: **<= 500 tokens**.

`fields` (optional): list of desired fields (e.g. `["summary", "edges_out"]`). When present, the response contains ONLY those fields (+ `id`, always). Typical use: a monkey in scan mode asking only for `summary` of several nodes — cost drops from ~400 to ~70 tokens per look.

Response for a **banana** (`note`/`document`/`concept`/`entity`/`event`):

```json
{
  "id": "projects/mixerllm/architecture",
  "type": "document",
  "title": "MixerLLM Architecture",
  "summary": "...",
  "tags": ["inference", "slm"],
  "confidence": 1.0,
  "updated": "2026-06-10",
  "outline": ["Overview", "Mixer-lang", "Block-loop", "Benchmarks"],
  "edges_out": [
    {"rel": "part-of", "target": "projects/mixerllm/_index", "target_summary": "..."},
    {"rel": "compared-with", "target": "concepts/speculative-decoding", "target_summary": "..."}
  ],
  "edges_in": [
    {"rel": "mentions", "source": "people/jimmy-wesley"}
  ],
  "stats": {"body_tokens": 2840, "degree": 7, "heat": 0.45}
}
```

Response for a **branch**: replaces `outline` with `children` (sub-branches and direct bananas, each with `id` + `summary`) and `cross_trails`.

Response for a **dataset**: includes `query_manual` (tables, key columns, 2-3 example_queries) and `sample_rows` (<= 3 rows).

Rules:
- `edges_out`/`edges_in` capped at 12 each, ordered by heat desc; surplus indicated in `stats.degree`.
- `target_summary` MUST come truncated to 25 tokens (it's a neighbor's scent, not a full digest).
- `body_tokens` lets the agent estimate a `pick`'s cost before making it.

### C.3 `move(id: string, rel?: string, direction: "out"|"in"|"both" = "out") → [Neighbor]`

```json
{
  "neighbors": [
    {"id": "...", "rel": "compared-with", "direction": "out", "type": "concept", "summary": "...", "heat": 0.1}
  ],
  "truncated": false
}
```

Without `rel`: all neighbors. Budget: <= 600 tokens. `move(id, "children")` is sugar for a branch's physical children.

### C.4 `pick(id: string, section?: string) → Content`

```json
{
  "id": "...",
  "title": "...",
  "section": "Mixer-lang",
  "body": "<markdown of the section or the whole body>",
  "body_tokens": 612,
  "truncated": false
}
```

- `section` matches against the `outline`'s headers (case-insensitive, exact match first, then prefix).
- Body > 4,000 tokens without `section` → returns only the expanded outline + `truncated: true` + hint `"use section="`. (Forces the agent to harvest the section, not the whole tree.)

### C.5 `query(id: string, sql: string) → Rows`

- Preconditions: node `type: dataset`, `payload_type: sqlite`.
- Validation: a single statement only; MUST start with `SELECT` or `WITH`; forbidden: `ATTACH`, write `PRAGMA`, `INSERT/UPDATE/DELETE/DROP/ALTER` → `E_QUERY_FORBIDDEN`. Connection opened read-only (`mode=ro`).
- Forced `LIMIT`: if absent, injects `LIMIT 200`. 2s timeout → `E_TIMEOUT`.

```json
{
  "columns": ["region", "total"],
  "rows": [["Southeast", 1250000.0], ["South", 740000.0]],
  "row_count": 5,
  "limited": false,
  "elapsed_ms": 3
}
```

Columnar format (`columns` + `rows` as arrays) — not objects repeating the keys; saves ~40% of the tokens.

### C.6 `scan(parent_id: string, filter?: Filter, fields?: [string], recursive: bool = false, limit: int = 50) → [PartialNode]`

**Metadata** query over a branch's children, without opening any file. Served by the **Catalog** (see C.6.1).

`Filter` supports equality and comparison over frontmatter fields:

```json
{
  "parent_id": "projects/_index",
  "filter": {"type": "dataset", "updated_after": "2026-03-01", "tags_any": ["sales"]},
  "fields": ["id", "summary", "payload_type"],
  "recursive": true
}
```

Response: list of partial nodes (only the requested `fields`), ordered by `heat` desc. Budget: <= 800 tokens, with explicit `truncated`.

Canonical use case: "I only want the sales datasets updated this quarter" → 1 call, ~3ms, ~200 tokens — instead of descending the hierarchy opening indexes.

#### C.6.1 The Catalog (`_derived/catalog.db`)

SQLite in the derived layer with one row per forest node: every frontmatter field + trail + degree + heat. Rebuildable from scratch by a full scan (`vine reindex`); updated incrementally on every `plant`/`graft`. It's what serves `scan()` and `locate`'s lexical side (FTS5 over title/aliases/tags/summary in the same base). **Not the source of truth** — if it diverges from the files, the files win and the catalog rebuilds.

### C.6b `sniff(terms: string | [string], scope?: string, k: int = 5, type_filter?: string) → SniffResult`

The **sniffer**: **literal** search over nodes' markdown bodies, returning node + section + occurrence snippet. It complements `locate`: the helicopter flies over curated metadata (summary/tags/title); the sniffer goes down to ground level and follows the trail of an exact term — error code, proper name, invoice number, identifier — that nobody bothered (or was obligated) to lift into the summary. The contract split is normative: **`locate` MUST NOT index bodies; `sniff` MUST NOT query curated metadata** (except to display the result).

Parameters:

- `terms`: 1 to 8 **literal** terms (a single string is promoted to a 1-item list). Substring matching, case- and diacritic-insensitive (NFD, combining marks stripped). A term with a space = exact phrase. A normalized term with < 2 characters → `E_SCHEMA`. **Regex is NOT accepted** (Phase 0): SLMs write fragile regex, and arbitrary regex opens unpredictable cost; literal terms give 95% of the value with a simple contract.
- `scope` (optional): id of **any node**. A branch (`sales/_index` or `sales`) restricts the search to the matching physical subtree; a banana restricts it to that single node's body (grep-within-node — the natural chaining after a `locate`/`look` that already found the target). Without `scope`, the whole forest. Nonexistent node → `E_NOT_FOUND`.
- `k`: max nodes in the result (default 5, cap 20).
- `type_filter`: as in `locate`.

Search semantics:

- Scans **only the body** of `.md` files (frontmatter excluded; `_derived`, `_assets` and binary payloads ignored).
- A node matches when **at least one** term occurs in the body; nodes matching **more distinct terms** rank first (AND-preferred, OR-tolerant).
- `match` = the occurrence's line, attributed to the section (H2/H3 header) containing it. Max of **3 matches per node** in the response (`match_count` reports the total; surplus flagged by `truncated_matches: true`).
- `snippet` = a window of the line centered on the first occurrence, truncated to ~25 tokens.

Ordering (same pheromone formula as C.1): `score = strength x (1 + alpha*heat)`, where `strength = matched_terms/requested_terms`, tie-broken by `match_count`.

```json
{
  "results": [
    {
      "id": "sales/exchange-policy",
      "type": "note",
      "title": "Exchange policy",
      "trail": ["_index", "sales/_index"],
      "score": 0.95,
      "heat": 0.31,
      "match_count": 4,
      "truncated_matches": true,
      "matches": [
        {"section": "Deadlines", "line": 23, "snippet": "…return with invoice NF-4412 within 30 days…"}
      ]
    }
  ],
  "scanned_nodes": 82,
  "truncated": false
}
```

Budget: <= 800 tokens, explicit truncation (`truncated: true`) dropping nodes off the end of the list.

Canonical use (the monkey's decision, taught in the orchestrator's system prompt):

1. Question contains an exact/rare term → `sniff` directly: lands in the right section and harvests with `pick(id, section)` — cuts hops-to-banana.
2. Conceptual question → `locate` (unchanged).
3. Chained: `locate` finds the region, `sniff(terms, scope=branch)` hunts the snippet within it.

Phase 0 implementation: direct file scan on every call (grep-like, no new index) — always fresh by construction, no extra derived state. MAY gain an index (body FTS5 in a separate table) in a future phase **with no interface change**, as long as the contract split with `locate` holds.

### C.6c `harvest(query: string, terms?: [string], k: int = 3) → HarvestResult`

**Composite tool, not a primitive**: a deterministic, zero-LLM orchestration
over C.1 `locate`, C.6b `sniff` and C.4 `pick`. It exists for the
bring-your-own-model integration: the caller's LLM (MCP client) gets ranked
evidence in one call and decides the next steps itself.

The three integration modes (informative):

1. **Direct navigation** — the client's LLM drives the primitives itself.
   Best when reasoning must happen *during* navigation. Token cost is bounded
   by the per-primitive budgets; the real cost is round-trips.
2. **Harvest (this tool)** — one call, evidence back, zero tokens spent on
   the server side. Best default for capable client models.
3. **Concierge** — a local SLM hunts and returns a synthesized answer
   (orchestrator-side, e.g. `examples/demo/run_demo.py`); for thin clients.

Parameters:

- `query`: free text; feeds `locate` as-is.
- `terms` (optional): exact literal terms for `sniff`. When absent, terms are
  derived from the query (words >= 4 chars, stopwords removed, max 8).
- `k`: max bananas returned (default 3, cap 5).

Semantics (normative):

1. Candidates = RRF fusion of `locate(query, k*2)` and `sniff(terms, k*2)`
   rankings (same RRF as C.1's hybrid mode).
2. Match refinement by **term scarcity**: per-term `sniff` scoped to each
   selected node, rarest term first — a rare exact term ("1045") MUST NOT be
   drowned by common co-occurring terms under the per-node match cap.
3. Content policy per node: full body when <= 1200 tokens; otherwise the
   matched sections (max 2) via `pick(section)`; otherwise outline + hint.
4. Response items carry: `id`, `title`, `type`, `trail`, `summary`, `score`,
   `found_by` (locate/sniff), `matches` (section, line, snippet) and
   `content`. The caller can always continue with the primitives using `id`.

Budget: <= 4000 tokens total, explicit `truncated: true` dropping whole tail
results first (never silently slicing a body).

```json
{
  "query": "...", "terms": ["..."],
  "results": [
    {
      "id": "projetos/mixerllm/log-experimentos",
      "title": "...", "type": "note",
      "trail": ["_index", "projetos/_index", "projetos/mixerllm/_index"],
      "summary": "...", "score": 0.0328, "found_by": ["locate", "sniff"],
      "matches": [{"section": "Experimento 45", "line": 141, "snippet": "…"}],
      "content": [{"section": "Experimento 45", "body": "…", "body_tokens": 146}]
    }
  ],
  "truncated": false
}
```

### C.7 `plant(node: NodeSpec) → PlantResult`

`NodeSpec` = full frontmatter + `body` + `parent` (destination branch id).

Atomic operation (in this order; failure at any step = full rollback):
1. Validates frontmatter against the schema (A.3) and `summary` (A.4);
2. Checks `id` uniqueness;
3. Writes the file;
4. Inserts the entry into the parent `_index.md`'s `## Direct bananas` (or `## Sub-branches`);
5. `git commit` with the standardized message `plant(<id>): <title> [source=<source>]`;
6. Marks the node stale in the derived layer (lazy re-embedding).

Returns: `{id, commit, trail}`.

#### C.7.1 Dataset planting — declarative schema (v0.8)

A `NodeSpec` with `type: dataset` MAY carry a `schema` object describing the
payload to be **born** with the node:

```json
{
  "type": "dataset",
  "id": "clients/prospecting-2026",
  "parent": "clients/_index",
  "title": "Client prospecting 2026",
  "summary": "...",
  "schema": {
    "clients": {
      "columns": {"name": "TEXT", "site": "TEXT", "segment": "TEXT",
                  "collected_at": "TEXT"},
      "primary_key": ["name"]
    }
  }
}
```

Rules (normative):

1. **The model never writes DDL.** The schema is data; the Vine generates
   the `CREATE TABLE` statements itself. Validation, all `E_SCHEMA` on
   failure:
   - table and column names MUST match `^[a-z_][a-z0-9_]*$` (≤ 64 chars);
   - column types MUST be one of `TEXT`, `INTEGER`, `REAL`, `BLOB`;
   - `primary_key` (optional, per table) MUST reference declared columns;
   - limits: ≤ 10 tables per dataset, ≤ 50 columns per table, ≥ 1 of each.
2. `schema` on a non-dataset `type` → `E_SCHEMA`. A dataset planted
   WITHOUT `schema` keeps the v0.7 behavior (reference to a payload that
   already exists on the filesystem).
3. **Payload birth**: `payload` defaults to `<leaf-of-id>.db`,
   `payload_type` to `sqlite` (explicit values are honored; `payload` MUST
   be a bare filename ending in `.db`). The target file MUST NOT already
   exist (`E_SCHEMA` — never silently overwrite a payload). The Vine
   creates the SQLite file, applies the generated DDL, and computes
   `payload_hash` (sha256) into the frontmatter.
4. **Auto manual**: when the body lacks a `## Query manual` section, the
   Vine appends one generated from the schema — each table with its column
   list, plus example queries (`` `SELECT * FROM <t> LIMIT 5` ``,
   `` `SELECT COUNT(*) FROM <t>` ``) — so C.2 `look`'s `query_manual`
   contract works from birth. A caller-provided manual is kept verbatim.
5. **Atomicity**: the C.7 rollback covers the payload — any failure after
   the `.db` is created MUST remove it along with the `.md`. A.3.1 intact:
   the commit carries only markdown; one dataset node = one `.db` = one
   database (several tables = several keys in `schema`; there is no
   separate "create database" concept).
6. After birth, rows enter exclusively via `tend` (C.10) — multi-row
   `INSERT INTO t VALUES (...), (...)` is a single statement and therefore
   already legal there. Schema evolution (`ALTER`) is NOT available to
   agents in v0.8.
7. **Initial rows (v0.9)**: the `NodeSpec` MAY carry `rows`, a mapping
   `table → list of rows` loaded at birth, after the DDL and BEFORE
   `payload_hash` is computed. Normative: rows are inserted **parameterized**
   (`executemany` with placeholders — row values are data, never SQL text,
   so no keyword scanning applies and injection is impossible by
   construction); every `rows` table MUST exist in `schema` and every row
   MUST have exactly the table's column count (`E_SCHEMA` otherwise); the
   atomic rollback of C.7 covers loaded rows (the payload is removed whole).
   This is the bulk-load path for the Gardener (G.3) and collector agents;
   incremental writes after birth remain `tend`-only.

Canonical uses (informative): an agent collecting external data plants the
dataset then fills it with `tend`, for later harvest by `query`/humans; an
agent finding a large markdown table in a `document` plants a dataset twin,
loads the rows, and `graft`s a `related-to` link from the document — prose
stays as source, the data becomes filterable SQL.

### C.8 `graft(id: string, patch: GraftPatch) → GraftResult`

`GraftPatch` supports three operations (combinable):
- `set_frontmatter: {field: value}` — mutable fields only (`title`, `summary`, `tags`, `confidence`); `id`, `type`, `created` are immutable (`E_READONLY`);
- `add_links: [{rel, target}]` / `remove_links: [...]`;
- `append_section: {header, body}` or `replace_section: {header, body}`.

Special rules:
- A `summary` change propagates to every `_index.md` that replicates it (same transaction).
- **Reinforce-before-create policy (shortcuts):** at the end of a successful hunt, the decision cascade is: (1) if a shortcut already covers the entry→banana connection on the trail, do NOT create one — just increment the existing one's `heat` and `confidence` (fortification, no commit); (2) if none exists and the trail was >= 4 hops, `graft` a new `discovered-shortcut` with `confidence: 0.5` and `discovered_by: agent`; (3) new lateral connections the agent notices (`related-to` between the banana and semantic neighbors) enter as a **proposal** with `confidence: 0.3`, subject to confirmation or pruning by the Ranger. The Vine MUST implement step 1's check inside `graft` itself (shortcut idempotence): grafting a duplicate link automatically becomes fortification, never an error or a duplicate.
- Commit: `graft(<id>): <patch summary>`.

### C.10 `tend(id: string, sql: string) → TendResult` (v0.7 — Phase 2)

The dataset-write primitive: the forest stops being a smart reader and
becomes memory that learns. `query` (C.5) remains read-only forever; `tend`
is the only sanctioned write path into a dataset payload.

Preconditions:

- Writable Vine (read-only server → `E_READONLY`).
- Node is `type: dataset` with `payload_type: sqlite` and an existing
  payload file — anything else → `E_QUERY_FORBIDDEN` / `E_NOT_FOUND`.

Statement rules (normative, mirror of C.5's paranoia):

- Exactly ONE statement, and it MUST start with `INSERT`, `UPDATE` or
  `DELETE`. Reads belong to `query`; schema changes (CREATE/ALTER/DROP)
  belong to the Gardener — all rejected with `E_QUERY_FORBIDDEN`.
- Forbidden anywhere in the statement: `ATTACH`, `DETACH`, `PRAGMA`,
  `DROP`, `ALTER`, `CREATE`, `VACUUM`, `REINDEX`, `BEGIN`, `COMMIT`,
  `TRANSACTION` → `E_QUERY_FORBIDDEN`.
- `UPDATE`/`DELETE` MUST carry a `WHERE` clause (mass-wipe guard): target
  rows explicitly; full rewrites are the Gardener's job.
- Timeout 2s → `E_TIMEOUT`. SQL errors roll the transaction back and
  surface as `E_QUERY_FORBIDDEN` (the payload is untouched).

Audit trail (A.3.1 compliant):

1. The write commits in the payload SQLite.
2. The Vine refreshes the node's frontmatter: `payload_hash` = sha256 of
   the payload file, `updated` = today.
3. `git commit` of ONLY the `.md`, message `tend(<id>): <VERB> <n> row(s)`.
   The what/when history lives in the markdown commit stream; the binary
   never enters git.
4. If step 2-3 fails after step 1 committed, the `.md` is restored and the
   error surfaces — the resulting hash drift is exactly what
   `vine validate` now warns about (self-healing: the next successful
   `tend` refreshes the hash).

Response:

```json
{"id": "vendas/pedidos-2026", "rows_affected": 1,
 "payload_hash": "<sha256>", "commit": "<hash>", "elapsed_ms": 4.2}
```

### C.9 Concurrency and consistency (Phase 0)

- **One writer, N readers:** `plant`/`graft` go through a single queue (global mutex in the Vine). Reads never block.
- Readers MAY see state up to 1 write behind (eventual consistency of seconds) — acceptable by design.
- The `.vine.lock` file at the root prevents two writer Vines on the same forest (`E_LOCKED`).

---

## Part D — Telemetry (feeds the pheromone and the Monkey Bench)

Every navigation session generates a trace in `_derived/traces/<session>.jsonl`, one event per primitive call: `{ts, session, primitive, id, tokens_in, tokens_out, elapsed_ms}`.

At the end, the orchestrator MUST close the session with `outcome: {success: bool, answer_nodes: [ids]}`. This closing is what:
1. Increments `heat` along the whole winning trail (whisper);
2. Evaluates the shout (v0.6): when the session metric `trail_len` — read
   calls made before the first harvest of an answer node — is `>= 4`, the
   answer nodes come back in `suggest_shortcuts`, and the orchestrator MAY
   `graft` a `discovered-shortcut` from the hunt's entry node (C.8 applies);
3. Feeds the Monkey Bench metrics: **hops-to-banana** = number of `look`+`move` calls before the answer's first `pick`/`query`; **tokens-to-banana** = sum of session tokens_out; **banana precision** = correct answer_nodes / harvested answer_nodes; **trail_len** (v0.6) = read calls before the first harvest of an answer_node.

---

## Part E — The Troop (Parallel Swarm Navigation)

N monkeys (navigator SLM instances) hunt the same banana in parallel, coordinated by **intra-session stigmergy**: they never exchange messages — they smell each other's trails. The Vine is already N-readers by design (C.9); the Troop is an **orchestrator**-side component (the MCP client side), not the bank.

### E.1 Hunt protocol

1. **Frontier partition:** `locate(query, k=N)` → each monkey gets a distinct entry point (top-N results). Without partitioning, everyone explores the same trail and the parallelism is wasted.
2. **Session pheromone:** each monkey, upon judging a node promising (the SLM's own call: "relevant to the question? yes/no"), deposits `session_heat` in the hunt's scope (`_derived/trails.db`, session namespace). `locate`/`look`/`scan` inside the session apply `score x (1 + beta*session_heat)` — monkeys gravitate toward regions where others found signal.
3. **Shared visited set:** `look`/`scan` digests already made in the session land in a shared cache; a monkey that would touch an already-visited node gets the cached digest instead (zero cost), and the orchestrator redirects it to unexplored frontier.
4. **Stop:** the hunt ends when (a) a monkey harvests a banana with high confidence (self-assessment above threshold), (b) the troop's hop budget runs out, or (c) the frontier empties. A **judge** (may be the main model itself) aggregates the harvests and synthesizes the answer.
5. **Post-session:** only the winning trail(s) convert `session_heat` into persistent `heat` (Part D). Losing trails evaporate with the session — the swarm does not pollute long-term pheromone.

### E.2 Implementation notes

- **Concurrency:** asyncio in the orchestrator; the monkeys spend ~95% of their time waiting on inference. On the 3090, serving the N monkeys through the same inference server with *continuous batching* (vLLM/llama.cpp parallel slots) makes N=3-5 cost nearly the same wall-clock as N=1.
- **Sizing:** N=3 is the default; above N~5 returns diminish (frontiers overlap in small forests). N is a Monkey Bench parameter, not a constant.
- **New metric:** *troop speedup* = wall-clock hops (parallel rounds) vs the solo monkey's total hops, and total token cost (the troop spends more tokens in aggregate — the speed x cost trade-off MUST be measured, not assumed).
- **Phase:** Troop is Phase 1.5 — requires the full Vine + telemetry (Part D) working. Nothing in Phase 0 changes, except ensuring `trails.db` supports session namespacing (already anticipated in the trace schema).

## Part F — Phase 0 Acceptance Criteria

Deliverable: Vine (MCP, Python) + a manual test forest (~100 nodes, 10 branches, >=1 SQLite dataset) + test suite.

1. All C.1-C.6b primitives functional with the exact contracts above (locate may be BM25-only), including `fields` in `look` and the Catalog serving `scan`.
2. `plant`/`graft` atomic with a Git commit and index update, verified by test.
3. Token budgets respected (tests with giant synthetic nodes verifying explicit truncation).
4. `query` rejects all write SQL (injection suite: `;DROP`, `ATTACH`, multi-statement, PRAGMA).
5. Demo: a local SLM (Qwen 7-14B Q4), given only the MCP tools and the master branch, answers 10 multi-hop questions about the test forest, with recorded traces and computed metrics.
6. Latency: p95 of `look`/`move`/`pick` < 10ms, `query` < 50ms, `locate` < 100ms, `sniff` < 100ms (local forest, NVMe).
7. `sniff`: finds a fact present ONLY in the body (invisible to `locate`), attributes the correct section, respects `scope`, normalizes case/diacritics, and rejects empty terms (`E_SCHEMA`) — all covered by test.
8. Payloads outside Git (A.3.1): the Vine's commit ignores non-`.md` files even if requested, and the test forest's `git ls-files` contains no binary — both verified by test.
9. `harvest` (C.6c): buried fact returns the right matched section under term-scarcity refinement; small bodies come whole; `k` and the 4000-token budget are honored with explicit truncation — all covered by tests.
10. Forest registry (C.0): per-request forest selection works across two forests with isolated results; lazy first-touch open auto-indexes; path escape and non-forest directories are rejected; single-forest mode serves v0.3 clients unchanged — all covered by tests.
11. `tend` (C.10): accepts only single-statement INSERT/UPDATE/DELETE (its own
    injection suite: DDL, ATTACH/PRAGMA, multi-statement, WHERE-less
    UPDATE/DELETE all rejected); refreshes `payload_hash` and commits only the
    `.md`; read-only Vine rejected; failed SQL leaves the payload untouched;
    `vine validate` warns on payload hash drift — all covered by tests.
12. Dataset planting (C.7.1): declarative schema births a queryable payload
    (`look` shows the auto query manual, `query`/`tend` work immediately);
    name/type/limit validation rejects bad schemas (`E_SCHEMA`), including
    injection attempts via table/column names; existing payload is never
    overwritten; rollback removes the newborn `.db`; the commit carries only
    the `.md` — all covered by tests.
13. Gardener (Part G): `adopt` of a mixed source tree (markdown, text,
    tabular) produces a forest that lints with zero errors — folders
    mirrored as branches, passports carrying `source_path` + `source_hash`,
    non-text originals archived under `_assets/`, datasets born with rows
    loaded, no binary in the forest git; `sync` classifies new / changed /
    deleted sources by hash-diff with no false positives, updates changed
    passports through the audited write path, and never deletes; converter
    discovery honors the config-hook > entry-point > built-in order; an
    external command hook converts a file end-to-end; an `on_curate` hook
    can enrich a draft and a crashing hook does not abort the ingest — all
    covered by tests.
14. Ranger (Part H): under a synthetic clock, one half-life halves heat and
    dust rows vanish; stale session scopes are cleared; promotion raises a
    well-used proposal's link confidence with an audited commit; pruning
    removes only cold, low-confidence links — links with confidence 1.0 or
    without a link-level confidence are NEVER touched; the health report
    flags an oversized branch (`needs_split`), an over-linked node and a
    stale passport; repeated runs are idempotent — all covered by tests.
15. Tiered storage (G.7/G.8): a `cached` adoption keeps node `.md`s body-
    free with the flesh in `_derived/bodies/` and OUT of git, while `pick`
    and `sniff` resolve it transparently; a `reference` adoption reads the
    source live; an unresolvable body fails with `E_NOT_FOUND` + hint
    while `locate`/`look` keep working (degraded map); `archive: never`
    creates no `_assets/` copies; `sync(path=...)` reconciles exactly one
    file; the mtime+size fast-path skips hashing unchanged files — all
    covered by tests. (Fetcher cache, H.6 eviction and Part I snapshots
    are covered by tests as their implementations land.)
16. Gardener v2 (G.2.1 + G.4.2.1): the DOCX built-in extracts headings,
    plain paragraphs, pipe tables, fragmented runs (joined whole) and
    text-box text from a real `.docx`, excludes headers/footers, and a
    missing `python-docx` yields `unsupported` (never a crash) with a
    command hook still able to claim `.docx`; edge proposals accept only
    catalog-offered targets at link-level `confidence: 0.3` with `rel:
    related-to` (hallucinated ids, self-links, duplicates and over-cap
    picks are dropped; branches are never candidates), the planted node
    carries the proposed links, and the Ranger's H.2 machinery manages
    them (promotable, prunable) — all covered by tests.
17. Rollup + Landmarks (G.4.4 + H.7): rollup replaces only `source: ingest`
    branch summaries (hand-authored branches untouched unless `--all`),
    runs deepest-first so parents see fresh child summaries, falls back
    deterministically to an A.4-valid summary when the LLM fails, and
    propagates the new summary into the parent's `## Sub-branches` entry
    WITH the coverage suffix preserved; the Ranger populates the master
    `## Landmarks` with top-degree non-branch nodes, a second run with an
    unchanged graph produces no new commit, and degree-0 nodes never
    appear — all covered by tests.
18. Station + ScopedVine (Part J): a fresh deployment plus one API key
    serves REST, MCP and Studio against a registry of two forests; the
    **leak suite** proves a principal granted only `projects/` cannot
    obtain the id, title, summary, body, edge or snippet of any node
    outside `projects/` through ANY primitive on ANY surface — one test
    per primitive per surface, `harvest` and `move` included; an
    out-of-scope `look`/`pick` is byte-identical to the genuinely-absent
    `E_NOT_FOUND`; a scoped `locate`/`scan`/`sniff` returns the same
    response shape and budget fields as the unscoped call (filtering
    precedes truncation); writes through the Station carry the acting
    principal in the commit message and the audit log reconstructs a
    session's full trail; capability gates reject `query`/`tend`/`plant`/
    `graft` without the matching cap; and the engine suite passes with
    zero edits under `src/monkeyllm/` — all covered by tests.
19. Per-forest inference (J.10): a provider's key is never returned by any
    surface (create, list, or re-edit) and an empty key on update keeps the
    stored one; a binding is refused for an unknown provider or an unknown
    role; removing a provider removes the bindings that pointed at it; the
    two roles can hold different models on the same forest; `answer` and
    `curate` refuse politely when no model is bound, and enforce the `read`
    and `write` capabilities respectively; and — the load-bearing one — for
    a principal scoped to a subtree, the material handed to the answering
    model contains no node outside that subtree — all covered by tests.
20. Console, lifecycle and ingest (J.5/J.7/J.8): every user-facing string
    resolves in all three languages, with a test that fails on the first
    key missing from any of them; the console renders in both themes and
    holds no credential in its bundle; forest creation refuses ids
    containing separators or relative segments **before** joining them to
    the root, refuses an id that already exists, and grants the creator
    the forest it just made; ingest refuses without the `ingest`
    capability and refuses a `dest` outside scope, an uploaded filename
    that escapes its staging directory is rejected, and a forest with no
    `ingest` binding still ingests with G.4-derived summaries; and a
    `projects/`-scoped principal's console offers only `projects/` in its
    tree, its scope picker and its dataset list — all covered by tests.

Out of scope for Phase 0 (do not implement): embeddings/vectors, `same-as` compaction, S3/R2 sync, multi-writer, Troop (Part E — Phase 1.5; only ensure session namespacing in trails.db). Automatic ingest left this list in v0.9 (Part G); evaporation and promotion/pruning left it in v0.10 (Part H).

---

## Part G — The Gardener (ingest pipeline, spec v0.9)

The Gardener turns raw directories into forest. It is **trusted
infrastructure** (it runs with the operator's authority, not an agent's),
but it writes through the same audited mechanics as everything else: nodes
are born via C.7 `plant`, datasets via C.7.1, and only `.md` ever reaches
git (A.3.1). Four stages — only one of them needs an LLM:

```text
0 archive  →  1 convert  →  2 curate  →  3 plant
(raw copy)    (pluggable)    (LLM-optional)  (existing primitives)
```

### G.1 Passport policy (normative)

No file enters the forest without a passport: a sibling `.md` node that is
the file's official presence in the graph. The agent always touches the
passport first; the native file is payload.

- Every passport records **`source_path`** (the source file's path, as given
  to adopt/sync) and **`source_hash`** (sha256 of the source bytes) in its
  frontmatter. These two fields make the forest itself the sync state —
  there is no separate bookkeeping database to drift.
- Conversion targets per format: markdown/plain text → `note` (body is the
  content, no payload); convertible documents (PDF/DOCX/…) → `document`
  (body is the converted markdown, original archived); tabular (CSV/XLSX/
  tabular JSON) → `dataset` (C.7.1 birth with schema + rows; original
  archived); audio/image/video → `media` (body is the transcript/
  description, original archived).
- Archived originals live in the node's branch under `_assets/` (gitignored
  per A.3.1), referenced by `payload` + `payload_hash`. Markdown/plain-text
  sources are NOT archived (the body is lossless).
- Node ids are deterministic slugs of the source-relative path (lowercase,
  ASCII-folded, `[a-z0-9._-]`); a slug collision appends a short hash. The
  id mirrors the source layout — placement in `adopt` mode is structural,
  not an LLM decision (ids are immutable; deciding placement at birth is
  mandatory, see A.3).

### G.2 Converter contract (public plugin API v1)

A converter claims file extensions and produces either markdown or a
dataset description:

```python
class Converter(Protocol):
    extensions: set[str]            # e.g. {".docx"}
    def convert(self, path: Path) -> Conversion: ...

Conversion = markdown(title, body)            # → note/document/media
           | dataset(title, schema, rows)     # → C.7.1 birth
```

Discovery order (first converter claiming the extension wins):

1. **Command hooks** from the forest's Gardener config (G.6) — an external
   command template (`"{input}"`/`"{output}"` placeholders) that must write
   markdown; lets operators plug ANY tool (including copyleft-licensed
   ones) without it ever becoming a dependency of this project.
2. **Entry points**: packages installed in the environment declaring the
   `monkeyllm.converters` group (`pip install monkeyllm-whisper` just
   works). This is the third-party extension surface.
3. **Built-ins**: `.md`/`.txt` passthrough; `.csv`/tabular `.json` (and
   `.xlsx` when `openpyxl` is present) → dataset with inferred column
   types; `.docx` → markdown when `python-docx` is present (G.2.1).
   Built-ins MUST keep the core dependency-light and MIT-clean.

A file with no claiming converter is reported as `unsupported` — never a
crash, never a silent skip.

#### G.2.1 DOCX built-in converter (v0.12)

Available when `python-docx` is importable (optional `ingest` extra —
python-docx is MIT, its lxml dependency BSD; same gating pattern as the
`.xlsx` built-in). Normative behavior:

1. **Document order, single pass.** The converter walks the body's block
   elements in order: `w:p` (paragraph) and `w:tbl` (table).
2. **Paragraph text = the join of ALL descendant `w:t` elements.** This
   captures runs fragmented mid-word by Word (joining merges them for
   free) AND text living inside embedded text boxes (`wps:txbx`, legacy
   `v:textbox`) — content invisible to naive `paragraph.text` readers.
3. **Headings**: paragraphs styled `Heading N` (or `Title`) map to
   markdown `#`-headings (`Title`/`Heading 1` → `##` and deeper — `#` is
   reserved for the node title line). Everything else is a plain
   paragraph.
4. **Tables** become GitHub pipe tables: first row = header, cells take
   the same all-`w:t` join. Nested tables flatten into their cell text.
5. **Headers/footers are EXCLUDED**: page numbers and letterhead repeat
   on every page and would pollute the scent (A.4 summaries derive from
   the opening text).
6. **Exclusions are not errors**: images/drawings contribute no text
   (media adoption is G.5's path); an empty document converts to an
   empty-bodied markdown with the filename title.

Without `python-docx`, `.docx` files are reported `unsupported` (G.2) —
operators can still route them through a command hook (e.g. a Pandoc or
MarkItDown wrapper), which keeps priority over this built-in.

**Extension surface is edges-only (normative):** converters and curation
hooks extend what goes INTO the forest. Nothing extends the primitives'
semantics, token budgets, or security guards (`query`/`tend` validation,
A.3.1, C.9 locking). UIs, upload receivers and automations are clients of
the MCP server or of the Python library — they require no plugin API.

### G.3 `adopt` and `sync` (the brownfield engine)

- **`adopt(source_dir, dest?)`** mirrors an existing tree: each source
  directory becomes a `branch` (planted before its children), each file is
  converted and planted as its passport under the mirrored branch.
  Deterministic: stable ordering, slug ids, no LLM in the loop. `dest`
  roots the mirror under an existing branch (default: forest root).
- **`sync(source_dir?)`** re-walks the source (default: the adopted root
  recorded in config) and hash-diffs against the passports' `source_hash`:
  - **new** file → adopt it;
  - **changed** hash → re-convert; the passport's body, `source_hash`,
    `payload_hash` (datasets are rebuilt) and `updated` are refreshed
    through the Gardener's audited write path — a git commit
    `gardener(sync): <id>` of only the `.md`. Curated frontmatter
    (summary, tags, links, confidence) is PRESERVED;
  - **deleted** source → the passport is reported `stale`. The Gardener
    NEVER deletes nodes; pruning is the Ranger's call (tombstone policy,
    out of scope here).
- Continuous watching (filesystem events) is a Ranger-era concern; v1 sync
  is on-demand and deterministic.

### G.4 Curation (the only LLM stage — always skippable)

Stage 2 enriches the draft node before planting:

1. **Without an LLM** (default in v1): summary derived from the converted
   content's first sentences (≤ 60 tokens, A.4-validated, with a safe
   fallback), `source: ingest`, `confidence: 0.7` (unreviewed), default
   tags from config. The pipeline never blocks on a missing GPU.
2. **With an LLM** (Gardener v2): A.4 summary with validate-and-retry,
   tags, edge proposals at link-level `confidence: 0.3` (G.4.2.1), guided
   by the **curation directives** in the forest config — free-text criteria
   the operator wants the Gardener to "keep an eye on" (e.g. "prioritize
   contract numbers and client names in summaries"). Entity EXTRACTION
   (minting new `entity` nodes) is deferred past v0.12: it needs a
   placement policy and a `same-as` dedup story first.
3. **`on_curate` hooks**: plugins (entry-point group `monkeyllm.hooks`,
   name `on_curate`) and/or locally registered callables receive the draft
   (dict) and may mutate it. Hooks run in discovery order; a raising hook
   is logged into the report and SKIPPED — a broken plugin never aborts an
   ingest.

#### G.4.2.1 Edge proposals (v0.12)

LLM curation MAY propose links from the node being adopted to nodes that
ALREADY exist in the forest. The contract is built so a wrong proposal is
cheap and a fabricated one is impossible:

1. **Candidates come from the catalog, never from the model's memory.**
   The Curator runs a BM25 search (C.6.1) with the draft's title + curated
   summary and offers the model a closed list of up to 8 candidates
   (`id`, `title`, `summary`). Excluded from candidacy: the draft itself,
   `branch` nodes (a link to a folder carries no scent), and the draft's
   own parent.
2. **The model picks from the list — or picks nothing.** Anything outside
   the offered ids is dropped (the hallucination guard is structural, not
   a prompt instruction). Picking nothing is a valid, common answer:
   relatedness must be visible in the two summaries.
3. **Every proposal is `rel: related-to`** (symmetric, generic — A.2) with
   **link-level `confidence: 0.3`** and MAY carry a short free-text `note`
   (kept out of the summary budget; helps the Ranger's audit trail). Other
   rels (`mentioned-in`, `same-as`, …) are NOT proposable in v0.12 — they
   assert ontology, not navigational adjacency.
4. **Caps and dedup**: at most 3 proposals per node; self-links and
   duplicates of existing links (same `rel` + `target`) are dropped.
5. **Node-level vs link-level confidence**: the adopted node keeps its
   G.4 `confidence: 0.7` (unreviewed content); 0.3 lives ON THE LINK —
   that is exactly the population Part H manages. The lifecycle is the
   point: **the Gardener proposes (0.3), usage heats both endpoints, the
   Ranger promotes (0.8) or prunes (cold)**. A proposal nobody ever walks
   costs one frontmatter line and dies by H.2.
6. **Failure never blocks**: bad JSON, transport errors or zero valid
   picks simply yield zero proposals (counted in the Curator's stats);
   the node still plants.

#### G.4.4 Branch rollup (v0.13)

Curation gives every banana a scent; rollup gives every REGION one. After
the per-node curation stage of an `adopt`/`sync` (or on demand), the
Gardener MAY rewrite branch frontmatter summaries bottom-up:

1. **Scope**: only branches with `source: ingest` — the Gardener rewrites
   what the Gardener planted, nothing else. An explicit operator override
   (`--all`) MAY widen the scope to every non-`_meta` branch.
2. **Order**: deepest branch first (by id depth), so a parent's rollup
   always sees its sub-branches' fresh summaries.
3. **Input**: the branch's own `## Sub-branches` and `## Direct bananas`
   entry lines (which replicate child summaries verbatim, A.5), clipped to
   the curation content budget. The model never reads child bodies —
   rollup is O(branches) LLM calls with bounded prompts.
4. **Output contract**: an A.4-valid summary (1-3 sentences, ≤ 60 tokens)
   answering the A.5 blockquote question — what lives here + where to go
   if it is not here. Validate-and-retry as in G.4.2.
5. **Fallback**: any failure (bad JSON, invalid summary after retries,
   transport error) falls back to a deterministic summary composed from
   child titles and counts — the pipeline never blocks and never leaves a
   branch worse than the template it had. Counted in the Curator's stats.
6. **Write path**: C.8 `graft` on the frontmatter `summary` — atomic,
   `.md`-only commit, catalog upsert, and VERBATIM propagation of the new
   summary into the parent's `## Sub-branches` entry (coverage suffix
   preserved, A.5). No new write machinery.
7. **What rollup is NOT**: it never creates nodes or links, never touches
   bodies (`## Cross trails` stays hand-authored), and never runs without
   an operator asking for curation (it is part of the always-skippable
   LLM stage).

### G.5 Media (multimodal by proxy)

Audio/image/video go through the SAME converter contract: the converter
(e.g. a Whisper transcriber, a vision-model describer — extras or hooks,
never core dependencies) returns markdown that becomes the `media`
passport's body. The forest's job is **finding** media fast: `locate`/
`sniff` search the textual proxy; a multimodal client that wants full
fidelity follows `payload` to the raw file. Text to find, binary to
consume. (Serving payload bytes over MCP to multimodal clients is a
possible future extension — not normative here.)

### G.6 Gardener config (`_meta/gardener.yaml`)

Operator-level configuration, read by the Gardener (not a node — `_meta/`
non-markdown files are not indexed):

```yaml
source_root: D:/dump/docs        # written by adopt; sync's default source
ignore: ["~$*", "*.tmp"]         # extra ignore globs (defaults: VCS dirs, temp files)
converters:                      # command hooks (discovery priority 1)
  ".pdf": 'pdf2md "{input}" -o "{output}"'
curation:
  default_tags: [adopted]
  directives: >                  # free text fed to the curation LLM (G.4.2)
    Prioritize contract numbers and client names in summaries.
content: inline                  # inline | cached | reference (G.7)
archive: never                   # never (default) | always (G.7)
```

### G.7 Content & archive policies (v0.11)

The forest's three tiers: SCENT (passport frontmatter — always local, in
git), FLESH (full converted text), BONE (raw binaries — stay at the
source). The `content` policy decides where the FLESH lives:

- **`inline`** (default): the converted body lives in the node `.md`
  (v0.9 behavior — git-versioned content; right for normal corpora).
- **`cached`**: the node `.md` holds only the title stub and the
  frontmatter marker `content: cached`; the converted body is written to
  `_derived/bodies/<id>.md` — OUT of git. Right for huge corpora.
  Regenerable: re-running `sync` while sources are reachable rebuilds the
  cache (the body is a function of source + converter).
- **`reference`**: no local body at all; the body IS the source file,
  read live at harvest time. ONLY valid for passthrough text sources
  (`.md`/`.txt`); marker `content: reference`.

Normative semantics:

1. **Lazy resolution**: `pick` (and `sniff`, when it reaches such a node)
   resolves the body from the cache file (`cached`) or from
   `source_root/source_path` (`reference`). The resolution is transparent
   — same response shape, same budgets.
2. **Degraded mode is explicit**: when the body cannot be resolved
   (source share down, cache purged), the read fails with `E_NOT_FOUND`
   and a hint naming the missing backing file. The MAP keeps working —
   `locate`/`look`/`scan`/heat never depended on the body.
3. `look`'s `outline` MAY be empty for non-inline nodes (the digest comes
   from the catalog; spending I/O to outline a remote body would break
   the <= 500-token cheapness contract).
4. Summary derivation and LLM curation (G.4) always see the FULL
   converted text at ingest time — the scent quality does not depend on
   the content policy.
5. **`archive`**: `never` (default) — durable sources are not copied into
   `_assets/`; `source_path` + `source_hash` are the reference. `always`
   — inbox mode: the source will vanish after ingest, archive the
   original (v0.9 behavior). Datasets keep their local `.db` payload
   under every policy (G.9).

### G.8 Targeted sync & triggers (v0.11)

- **`sync(path=...)`** reconciles a single source-relative path (new,
  changed or deleted) without walking the whole tree — the building block
  for event-driven updates.
- **Fast-path (normative)**: passports record `source_size` and
  `source_mtime`; a sync visit MUST skip hashing when both match the
  stored values (rsync's trick — re-hashing 2 TB per cycle is the real
  bottleneck). Hash remains the authority whenever the fast-path misses.
- **Events trigger, the reconciler decides**: filesystem watchers, S3
  event notifications, Drive `changes.watch` and upload webhooks are
  CLIENTS/plugins that call targeted sync. Events MUST NOT be trusted as
  state (they get lost); a periodic full `sync` (`--every N`) heals
  anything an event missed. Same controller pattern as C.6.1: derived
  state reconciles from the files, never the other way around.

### G.9 Payload fetchers (v0.11)

`payload` and `source_path` MAY carry a URI scheme. Plain paths mean
`file://` (today's behavior, zero change). Remote schemes (`s3://` first,
as an optional MIT-licensed extra) resolve through a fetcher registry:

1. Remote payloads/bodies download on first use into
   `_derived/payloads/`, validated against `payload_hash`/`source_hash`
   before use (a corrupted or tampered download never reaches the agent).
2. **Datasets are local-first by design**: SQLite needs a local file, and
   a hot knowledge base needs sub-millisecond reads — object storage
   holds `.db` files only as backup or cold-archive tiers. A cold
   dataset's first `query` pays one download; the cache absorbs the rest.
3. Remote sync uses the store's own change signals (ETag listings)
   instead of downloading to hash.
4. **`tend` rejects remote payloads** (`E_QUERY_FORBIDDEN` with hint):
   writes belong to the local-first tier — editing a cached copy of a
   remote database would fork it silently. Reads (`query`, `look`'s
   dataset digest) work through the cache transparently.
5. **Region prefetch (the parachute warms the camp)**: `prefetch(scope)`
   downloads every remote payload under a branch in one sweep — the
   orchestrator calls it right after `locate` drops the monkey, so the
   subsequent `sniff`/`query` hops run at local speed. Combined with H.6
   eviction, the payload cache converges to the shape of the pheromone:
   hot regions stay warm, cold regions evaporate from disk.

The MAP itself (passports + the forest git) stays local to wherever the
Vine runs — it is the truth, it is ~0.1% of the source, and remote
clients reach it through the MCP server, not by replicating it. Moving a
map between machines is what snapshots are for (Part I). `catalog.db` and
`trails.db` remain disposable caches OF the local map (C.6.1) — they are
never the only local copy of anything.

---

## Part H — The Ranger (maintenance, spec v0.10)

The Ranger keeps the forest healthy over time. The compounding loop only
works if the pheromone can also **forget**: without evaporation every trail
saturates at `heat = 1.0` and the whisper stops discriminating; without
pruning, agent proposals pile up as permanent noise. The Ranger is trusted
infrastructure (operator authority): evaporation lives entirely in the
derived layer; every node edit goes through the audited `.md`-only commit
path.

### H.1 Heat evaporation (derived layer only — no commits)

- Persistent heat decays exponentially:
  `heat' = heat × 0.5^(Δt / half_life)`, where `Δt` is the time since the
  row's `updated` timestamp. Default `half_life_days: 30` (config H.5).
- Rows whose decayed heat falls below **0.01** are deleted (dust removal —
  the table stays proportional to what is actually warm).
- Session scopes (`scope != ''`) older than `session_ttl_hours` (default
  24) are cleared — crash leftovers from Troop hunts must not survive.
- Evaporation re-stamps `updated` at decay time (the decay is applied, not
  re-derived); running the Ranger twice in a row is a no-op within clock
  precision (idempotence under the synthetic-clock test).
- `_derived/` remains disposable: deleting `trails.db` loses memory but
  breaks nothing (A.3 spirit) — therefore evaporation never commits.

### H.2 Promotion and pruning of uncertain links

**Scope rule (normative): the Ranger manages ONLY links that carry a
link-level `confidence < 1.0`** — i.e. edges born as proposals
(`related-to` at 0.3, C.8) or discovered shortcuts (0.5, C.8). Structural
edges (`part-of`, etc.), links without a confidence field and links at
`confidence: 1.0` are NEVER touched.

- **Promotion**: a managed link whose BOTH endpoints hold persistent heat
  `>= promote_floor` (default 0.2) after evaporation is *confirmed by use*:
  link confidence is raised to `promoted_confidence` (default 0.8). Audited
  commit `ranger(promote): <id> <rel>-><target> 0.8` of only the `.md`.
- **Pruning**: a managed link with `confidence <= prune_below` (default
  0.5) whose BOTH endpoints have fully evaporated (heat 0 — no
  reinforcement within memory) is removed. Audited commit
  `ranger(prune): <id> <rel>-><target>`.
- A link that is neither hot enough to promote nor cold enough to prune is
  left alone — patience is a feature.
- The Ranger NEVER deletes nodes. Stale passports (G.3) stay reported until
  a human (or a future tombstone policy) decides.

### H.3 Health report (read-only)

One pass over the catalog + files, returned as a dict and printed by the
CLI:

- **`needs_split`**: branches with > 150 entries or > 3.000 body tokens
  (A.5 rule).
- **`fat_nodes`**: nodes with degree > 50 (A.2 rule — branch candidates).
- **`lint`**: error/warning counts from `vine validate`'s engine (includes
  payload drift, C.10).
- **`stale_passports`**: passports whose `source_path` no longer exists
  under the Gardener's `source_root` (when configured).
- **`uncertain_links`**: inventory of managed links by confidence bucket
  (what the next promotion/pruning cycle will look at).
- **`heat`**: row count + max/mean of the persistent scope (pheromone
  health at a glance).

### H.4 Execution model

- `vine ranger [--forest DIR]` — one full cycle: evaporate → tend links →
  health report.
- `vine ranger --every N` — service mode: repeat every N seconds until
  interrupted (Docker-friendly; the deploy doc's `ranger (cron)` box).
- The Ranger takes an injectable clock (`now`) — the synthetic-clock tests
  of F.14 depend on it.

### H.5 Ranger config (`_meta/ranger.yaml`)

```yaml
half_life_days: 30
session_ttl_hours: 24
promote_floor: 0.2
promoted_confidence: 0.8
prune_below: 0.5
payload_cache_gb: 5        # H.6 (v0.11)
```

### H.6 Payload-cache eviction (v0.11)

The Ranger evicts `_derived/payloads/` entries least-recently-used first
when the cache exceeds `payload_cache_gb`. Eviction is always safe: every
cached entry is re-fetchable from its source URI and hash-validated on
return (G.9.1). Evaporation for bytes — same philosophy as H.1.

### H.7 Landmarks refresh (v0.13)

The Ranger keeps the master `_index.md`'s `## Landmarks` section (A.5)
populated — the forest's hubs, discovered mechanically:

1. **Selection**: top 10-20 nodes by degree over the catalog's typed-edge
   table (frontmatter `links`, both directions). Excluded: `branch` nodes
   (a landmark must carry scent), `_meta/*`, and degree-0 nodes. The
   folder hierarchy (`parent`) does NOT count toward degree — landmarks
   measure how woven a node is, not how filed.
2. **Rendering**: A.5 entry lines (`- [[id]] — <summary>`) inside the
   `## Landmarks` section of the master branch only. The section is
   created if the heading is missing.
3. **Idempotence**: the section is rebuilt in full and compared; an
   unchanged graph produces no write and no commit.
4. **Write path**: the audited `.md`-only pattern (H.2) with commit
   message `ranger(landmarks): refresh`, followed by a catalog upsert of
   the master index. No LLM, no node creation, no link changes.

---

## Part I — Snapshots (v0.11)

A forest snapshot is ONE file: the forest's git repository packaged as a
`git bundle` (the full commit history — every plant/tend/gardener/ranger
audit trail — travels along), compressed.

- `vine snapshot create [--out FILE]` → `<forest>-<date>.bundle.zst` (or
  `.bundle` when zstd is unavailable). Payload `.db` files are NOT inside
  (they are not in git, A.3.1); `--with-payloads` adds a sidecar archive.
- `vine snapshot restore FILE --forest DIR` → a full forest clone with
  history; `vine reindex` rebuilds the derived layer.
- Upload to object storage rides the G.9 fetcher (`--to s3://...`).
- The Ranger MAY schedule snapshots in service mode (backup policy:
  interval + retention), config in `_meta/ranger.yaml`.

Use cases (informative): backup/DR, distribution (a team pulls the whole
MAP in one small download — the scent tier is ~0.1% of the source),
frozen releases of a knowledge base ("the forest as of Q2 close").

---

## Part J — The Station (host layer: self-host, governance, scoped access)

### J.0 Position

Parts A-I describe a forest and the Vine that reads it, for one operator
who owns the filesystem. Part J describes the **Station**: the service that
serves forests to *many* principals — with identity, policy, audit and a
web console — so that a forest becomes a governed corporate asset instead
of a personal directory.

The Station is a **privileged client**, never an extension (G.0):

- The engine (`src/monkeyllm/`) MUST NOT gain policy, identity or tenancy
  awareness. Primitive semantics, budgets and guards are identical whether
  a call arrives through the Station or through `vine serve`.
- Forests remain content. Principals, tokens and policies MUST live in the
  **host registry** (host-side storage), never inside a forest — a forest
  handed to another operator carries no credentials.
- Every write remains a git commit inside the forest (A.3), and binaries
  remain outside that git (A.3.1).

### J.1 The Station

The Station mounts a **forest registry** — a root directory whose valid
forests are resolved exactly as C.0 registry mode already resolves them —
and exposes three surfaces:

| Surface | Consumer | Transport |
|---|---|---|
| REST | applications, scripts, integrations | HTTP/JSON under `/v1/` |
| MCP | agents, IDEs, bots | the Part C tool contracts, unchanged |
| Studio | humans | web console served by the Station (J.5) |

All three surfaces MUST route every forest access through the single
`ScopedVine` of J.3. An unscoped `Vine` handle MUST NOT be reachable from
any surface, including internal helpers and background jobs.

The MCP surface MUST remain contract-identical to `vine serve`: an agent
that works against a local Vine works against a Station-served forest with
no change beyond endpoint and credentials. Scoping is expressed only as
narrower *content*, never as a different shape (J.3).

### J.2 Identity

- **Principals** are users (humans) or service tokens (machines). Both are
  registry objects; both carry a stable id used in audit records.
- **Authentication:** API keys (stored hashed) MUST be supported; OIDC/JWT
  for corporate SSO MAY be added, mapping claims onto a principal.
- **Roles** are per-forest: `owner`, `gardener` (ingest and writes),
  `ranger` (maintenance), `reader`. A principal MAY hold different roles on
  different forests. Roles are shorthand for capability sets (J.3); an
  explicit policy grant always refines them.

### J.3 Policy and enforcement — `ScopedVine`

**Unit of scope: the branch prefix.** The hierarchy that Part A already
maintains is the policy surface — a grant names a subtree, not a node list.

A policy binds one principal to one forest:

```yaml
principal: <id>
forest:    <forest-id>
allow:     [projects/, sales/reports/]    # subtree grants
deny:      [projects/secret/]             # carve-outs; deny wins
caps:      [read, write, query, tend, ingest, admin]
datasets:                                 # optional narrowing
  sales/report-q1-2026: {tables: [sales]}
```

Resolution rules: absent policy means **no access** (deny-by-default); a
node is in scope when some `allow` prefix matches its id and no `deny`
prefix does; `deny` MUST win over `allow` at any depth.

`ScopedVine` wraps the ten primitives plus `harvest` with exactly one rule
each:

| Primitive | Enforcement |
|---|---|
| `locate`, `scan` | candidate set restricted to in-scope nodes **before** ranking, budgeting and truncation |
| `sniff` | body search space restricted to in-scope nodes |
| `look`, `pick` | node MUST be in scope, else `E_NOT_FOUND` |
| `move` | edges whose other endpoint is out of scope MUST be omitted from the response |
| `harvest` | inherits the above (it is a C.6c composite, not a bypass) |
| `query` | requires `query` cap and an in-scope `type:dataset` node; the optional table allow-list is checked against the parsed statement; C.9 read-only guards unchanged |
| `tend` | requires `tend` cap and an in-scope dataset; C.10 guards unchanged |
| `plant`, `graft` | require `write` cap; the target id MUST be in scope |
| Gardener `adopt`/`sync` | require `ingest` cap; MUST NOT write outside scope |

**Two invariants, both security-critical:**

1. **No truncation oracle.** Scope filtering MUST be applied before token
   budgets and `truncated` are computed. A scoped response MUST have the
   same shape and budget semantics as an unscoped one; a caller MUST NOT
   be able to infer hidden content from result counts or truncation flags.
2. **No existence oracle.** An out-of-scope node MUST produce a response
   byte-identical to that of a node that does not exist (`E_NOT_FOUND`,
   same hint). This extends to `move`: an omitted edge MUST be
   indistinguishable from an absent edge, because an error or a placeholder
   would itself disclose the forbidden node.

Structural consequence: `ScopedVine` composes the public `Vine`; it MUST
NOT patch, subclass around, or reach into engine internals. Any behavior it
cannot express through public primitives is a spec gap to be resolved here,
not a monkey-patch.

### J.4 Audit

- **Writes** are already commits; the Station MUST stamp the acting
  principal in the message, following the existing convention
  (`station(<principal>): <action>`, cf. `ranger(promote|prune)`). Git
  history remains the source of truth for what changed.
- **Reads** extend Part D telemetry with the principal: every scoped call
  records `(principal, forest, primitive, argument digest, result size,
  timestamp)`. Bodies and snippets MUST NOT be copied into the audit log —
  it records access, not content.
- The pair MUST be sufficient to reconstruct any answer's full trail after
  the fact: which principal, which primitives, which nodes, in which order.

### J.5 Studio

A web console served by the Station. Studio MUST consume only the
documented REST surface. It MUST NOT hold a privileged side-channel:
whatever Studio can do, an API client with the same principal can do — and
whatever a principal cannot do, Studio cannot show. Localisation and
theming are presentation: they MUST NOT change any request, response or
permission.

#### J.5.1 Information architecture

The console is organised into three groups, answering three different
questions an operator arrives with:

| Group | Console | Answers |
|---|---|---|
| **Use** | Overview | what is in this forest and what may I do here |
| | Ask | what does the forest know about *X* |
| | Explore | where does a fact live, and what is next to it |
| | Playground | what exactly does an agent see, and what would this call cost |
| | Data | what do the datasets contain |
| **Build** | Ingest | how do I put my documents in |
| | Models | who reads this forest, and who summarises it |
| **Govern** | Access | who may see what |
| | Audit | who saw what |

Navigation MUST carry an icon per console alongside its label: the console
is used by people who did not choose these names, and a name alone is a
weak target.

`Ask` is the default landing console for a principal holding `read`,
because it is the only one whose purpose needs no explanation. A console
the principal's capabilities do not permit MUST be presented as an
explanation of what is missing, never as an empty or failing form.

#### J.5.2 The vocabulary rule

The console MUST address the operator in the operator's vocabulary. The
policy model of J.3 is storage, not interface:

- **Roles before capabilities.** Access is granted by choosing a named
  role; the resulting capability set MUST be shown as a *consequence* of
  that choice, never demanded as the input. Refining the set directly MAY
  be offered as an explicit deviation from a role.
- **Scope is picked, not typed.** Branch prefixes MUST be selectable from
  the forest's actual branch tree. Free text MAY remain available; it MUST
  NOT be the only way in, because a typed prefix that matches nothing is
  indistinguishable, in a text field, from one that matches everything.
- **The grant MUST be restated in a sentence** before it is saved: which
  principal, which branches out of how many, what they will be able to do,
  and what they will not. A policy an operator cannot read back is a
  policy they cannot audit.

#### J.5.3 Localisation and theme

- The console MUST ship **English, Portuguese and Spanish**, complete: a
  missing translation is a defect, not a fallback. It MUST detect the
  browser's preference on first load and persist an explicit choice.
- The console MUST offer both a **light and a dark** presentation, follow
  the operating system preference until told otherwise, and persist an
  explicit choice.
- Content is not chrome. Node ids, titles, summaries, bodies, SQL and
  model output are forest data and MUST be rendered as stored — the
  console translates its own words only.

### J.6 Deployment

A Station deployment MUST be reducible to one container image plus two
volumes — the forest registry and the host registry — with no external
database required. Snapshots (Part I) remain the backup unit; the host
registry is backed up alongside them.

### J.7 Forest lifecycle

A deployment that can only serve forests placed on its volume by hand is
not self-service. `POST /v1/admin/forests {id, title, summary?}` creates
one, and creation is exactly A.5 `init_forest` — the same skeleton,
dialect and embedded git a local `vine init` produces. The Station adds no
second way to make a forest.

- The `id` is a directory name inside the registry root and MUST be
  validated **as a name, before it is a path**: a bounded character set,
  no separators, no relative segments. Rejecting after joining is too
  late.
- Creating requires the `admin` capability on some existing forest — the
  authority to govern a forest is the authority to start another. A
  bootstrapped deployment therefore reaches its second forest through the
  API, and an unprivileged principal never can.
- The creator MUST be granted the new forest with full capabilities.
  Creating a forest nobody can open would be a silent failure with a
  success status.
- An existing id MUST be refused rather than adopted: quietly returning
  someone else's forest because the name matched is an access-control bug
  wearing a convenience feature.

Deletion is deliberately absent. A forest is content with history; the
operator removes it from the volume, and Part I snapshots are how it comes
back.

### J.8 Ingest surface

Part G already turns directories into forest. J.8 exposes it, because the
operator who most needs ingest is the one who has a browser and no shell.
`POST /v1/forests/{forest}/ingest` takes one of three modes:

| Mode | Body | Does |
|---|---|---|
| `adopt` | `{path, dest?}` | mirrors a directory the **Station host** can read |
| `sync` | `{path?, dest?}` | G.8 hash-diff refresh of a previous adopt |
| `upload` | `{files: [{name, text}], dest?}` | stages the payload under the forest root, then adopts it |

Common rules:

- Requires the `ingest` capability (J.3's Gardener row), and `dest` MUST be
  in scope. Ingest is a write; a principal who may not read a subtree MUST
  NOT be able to write into it, or scope becomes a one-way mirror.
- A principal whose scope is not the whole forest MUST supply `dest`.
  Defaulting to the root would let a narrowly scoped principal write where
  it cannot read.
- **Naming a host path is a privileged act** and MUST additionally require
  `admin` on the forest. `path` is read with the Station's authority, not
  the caller's, so `ingest` alone would turn a content capability into
  arbitrary read access to the host filesystem. The exception is a
  *targeted* `sync` of a path relative to the source root a prior adopt
  already recorded: that directory was vetted when it was adopted.
- `upload` MUST validate each entry's `name` as a relative path with no
  escape, and stage under a directory inside the forest that is not itself
  forest content. Uploaded bytes are a source, not a node: they become
  nodes only through the same converters, curation and commits as `adopt`.
- The response is the Part G `IngestReport` — created, updated, unchanged,
  unsupported, errors — unabridged. A partially successful ingest that
  reports success is worse than one that fails.
- Curation uses the forest's `ingest` binding (J.10) when one exists and
  the deterministic G.4 derivation when it does not. Ingest MUST NOT
  require a model: a forest with no binding still ingests, with derived
  summaries.

*Attribution boundary (informative):* J.4 stamps the acting principal by
amending the commit a write produced. An ingest produces many — one per
node — and amending would rewrite only the last while claiming the batch.
The Station therefore records the resulting commit **range** in the audit
log and returns it, rather than rewriting history it did not author.

### J.10 Per-forest inference

**Providers.** An operator registers named endpoints in the host registry:
a name, an OpenAI-compatible `/v1` base URL, and an optional key. Any
compatible gateway qualifies — OpenRouter, LiteLLM, vLLM, a local
llama.cpp. Credentials are **write-only across every surface**: the API
accepts a key and reports only whether one is set (`has_key`), and an
update with an empty key MUST preserve the stored one so an endpoint can
be corrected without re-pasting a secret.

**Role bindings.** A binding maps `(forest, role) → (provider, model,
max_tokens, reasoning)` with `role ∈ {ingest, answer}`:

| Role | Used by | What to optimise for |
|---|---|---|
| `ingest` | curation at adopt/sync, `curate` | care: its output is the scent every later hop navigates by |
| `answer` | `answer` | speed and instruction-following over already-retrieved material |

A binding MUST be refused if the provider or the role is unknown, and
removing a provider MUST remove the bindings that pointed at it — a
dangling binding would fail at the worst possible moment.

### J.10.3 Model-backed composites

Two host composites, neither a primitive (the engine gains nothing):

- **`answer(question, k)`** — runs the scoped `harvest`, hands the result
  to the forest's `answer` model, and returns `{answer, model, evidence,
  harvest}`. Requires the `read` capability.
- **`curate(id)`** — re-summarises one node through the `ingest` model
  under the A.4 scent rules (validate-and-retry), returning the proposed
  summary rather than writing it. Requires the `write` capability, because
  it spends the operator's tokens.

**The invariant that makes binding a model safe:** retrieval runs through
`ScopedVine` *before* any model is called, so the model receives only
material the principal could already have read primitive by primitive.
Binding a model MUST NOT widen what a principal can see; if a composite
ever needs data outside the caller's scope, that is a specification
question, not an implementation shortcut.

*Known boundary (informative):* `answer` reads text. Facts that live only
inside a `type:dataset` payload are reached with `query`, so a question
whose answer is an aggregate over rows will be honestly refused rather
than guessed. A tool-calling answer loop is the natural follow-up.

### J.11 Out of scope for Part J

Engine changes of any kind (contracts, budgets, ranking); per-node ACLs
finer than the branch prefix; row-level filtering inside datasets beyond
the table allow-list; multi-writer forests (the single-writer lock stands);
billing and metering beyond per-token quotas.

*Documented boundary (informative):* scoping is per node, and node bodies
are author-written prose. A body that names an out-of-scope node discloses
that id to anyone who may read the body — the remedy is to keep such
references in the same scope, not to redact prose, which would corrupt the
content the forest exists to serve.
