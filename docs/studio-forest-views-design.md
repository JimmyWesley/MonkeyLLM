# Studio Forest Views — design note (pre-spec)

Status: **approved direction, pre-spec** — contract items below require a spec
version bump (Part J additions) before code, per the project rule.
Date: 2026-08-09. Source: ideation session with an interactive prototype built
from the real `forests/forest-fixture` (82 nodes, 97 edges, live force
simulation, working file browser / db browser / query shortcuts). The
prototype is a session artifact, intentionally not committed (page chrome is
pt-BR); everything normative about it is captured here.

## Vision

One console, two views over the same truth. The **graph of the forest**
(Obsidian-style, but alive: pheromone heat, discovered shortcuts, Gardener
proposals) and the **files as they live on disk** (markdown + git), each node
opening in the most elegant form available. This is the first screen a person
sees; it is where the product explains itself.

## What already exists vs. what is new

Existing and untouched: the Station (REST + MCP), the Studio shell and its
consoles — **Data keeps its current dataset screen**, Ask, Ingest (upload),
Models, People, Audit, Overview. The changes are surgical:

1. The **Explore console gains three modes**: Graph (new), Tree (today's
   Explore), Files (new). A pill switcher in the console toolbar.
2. A **side inspector** (passport / index entry / trails / git) — evolution of
   Explore's current detail pane.
3. A **governed editing screen** (new).
4. An **Ingest "Write" tab** (new) — free-text posting with automatic curation.

## Screen 1 — Graph mode ("Canopy")

- **Data**: new `GET /v1/forests/{forest}/graph` — a read-only projection of
  the Catalog (`nodes` + `edges`) joined with persistent heat from
  `trails.db`. Must go through `ScopedVine`/`Policy`: out-of-scope nodes are
  absent, any edge with a filtered endpoint is dropped, derived counts are
  recomputed (out of scope is indistinguishable from absent). The Catalog is
  never the source of truth; the UI offers `reindex` on staleness.
- **Visual channels** (legend read from the forest's `_meta/schema.md`
  dialect, never hardcoded):
  - node color = `type`; node size = degree; node glow = heat [0,1];
  - containment/`part-of` edges faint; typed links normal;
  - link-level `confidence < 1.0` dashed (0.3 proposal / 0.5 shortcut /
    0.8 promoted); `discovered-shortcut` visually distinct (amber);
  - `stale` and lint problems as warning badges.
- **Behavior**: live force simulation (d3-force — build-time Studio
  dependency; the Station image gains no runtime dependency, spec J.6). Nodes
  self-organize on entry; dragging a node pulls its neighborhood; wheel zoom,
  pan, hover highlights the neighborhood; a "reorganize" control reheats the
  simulation. `prefers-reduced-motion` gets a settled static layout.
- **Click = `look`**: the inspector shows the node digest (same data an agent
  receives, same scope policy), with "Open in Files".
- **Scale**: full graph up to ~2k nodes; beyond that, a local view (radius N
  from a node, or per branch) with click-to-expand — same level-by-level
  pattern as `useForestTree`.

## Screen 2 — Files mode ("Grove")

- Left: the real tree (branches, `_index.md` per folder, payloads shown
  beside their owner node). Built with the `useForestTree` BFS pattern.
- Center, dispatch by file type — the file always opens in its most readable
  form, and the tree stays available to switch files at any moment:
  - **`.md` — Reading view is the default** (rendered markdown, TipTap
    surface, passport card on top, wikilinks resolvable). A
    **Reading | Source** toggle switches to raw text in Monaco (read-only).
  - **`.db` — inline dataset browser**: table list on a side rail (auto-open
    the first/only table), the `SELECT` visible and editable on top
    (default top-100), and **query shortcuts** parsed from the node's own
    `## Query manual` examples. All reads go through the `query` primitive
    (single SELECT, LIMIT injected, timeout) — the browser is a shortcut;
    heavy work remains in the Data console, which is unchanged.
  - **`.html` — rendered as a page** (sandboxed `iframe srcdoc`), with a
    Page | Source toggle.
  - Bodies over the `pick` budget (4000 tokens) show the outline and load
    per section, as an agent would.
- Right: inspector tabs — Passport (catalog view), Index (the verbatim entry
  in the parent `_index`, marked as derived/never hand-edited), Trails
  (persistent heat + recent sessions), Git (the node's commit history from
  the embedded repo).
- Status bar: frontmatter validation, last commit, `.vine.lock` presence.

## Screen 3 — Governed editing (TipTap → `graft`)

The reconciliation of "edit in the browser" with "the forest only changes
through governed writes": the editor **never writes the file**. It serializes
the difference into `graft` operations — `set_frontmatter`,
`replace_section`, `add_links`, `remove_links` — and the commit is stamped
with the logged-in principal, audited like any agent write.

- Frontmatter is a form, not text: `id`/`type`/`created` locked; `summary`
  with a live ≤ 60-token counter (same validator as the parser); tags as
  chips; wikilink autocomplete over the catalog (existing targets only).
- A pending-changes panel shows the graft patch and the resulting commit
  message before applying. What TipTap produces is exactly what an agent
  would send over MCP — humans and agents write through the same door.
- Editing a dataset cell (in the Grove db browser or the Data console) builds
  a single `tend` DML with a full WHERE, shown as SQL before applying.
- **T09 scope revision recorded here**: T09 declared "WYSIWYG node editing"
  out of scope ("forests are generated/ingested, not hand-authored in a
  browser"). Governed-write editing keeps the spirit — no raw file writes,
  ever — and is adopted as a deliberate exception. T09's out-of-scope line
  stands for *raw* editing only.

## Screen 4 — Data console

Unchanged. The Grove `.db` browser links to it for heavy work.

## Screen 5 — Ingest "Write" tab (post to the forest)

Second tab of the Ingest console, after Upload: a blank TipTap compose in
markdown. On **Publish**, the Curator (local SLM) reads the text and
proposes the full passport — id, type, destination branch (selectable),
summary ≤ 60 tokens, tags — plus **edge proposals at link-level
`confidence 0.3` picked from a closed catalog-offered candidate list**
(cap 3; hallucinated targets structurally impossible, G.4.2.1). The person
reviews (accept/reject per link, adjust fields), then the node lands as a
`plant` committed as the principal, with the parent index entry created.
The Ranger manages the 0.3 population afterwards (H.2). Nothing is planted
without review.

## Contract additions (spec bump required BEFORE code)

1. `GET /v1/forests/{forest}/graph` — scoped catalog projection (Part J).
2. `GET /v1/forests/{forest}/trails` — per-node persistent heat (Part J);
   also unblocks T09 item 11 (trails dashboard).
3. Ingest "Write": likely covered by the existing ingest endpoint with a
   text payload + curation; confirm or extend in the spec.
4. Explore modes, Reading/Source toggles, db browser and HTML rendering are
   **presentation** (J.5) — no contract change.
5. Editing uses existing primitives (`graft`/`tend`) — no contract change.
6. Resolve the normative-spec question first: CLAUDE.md declares v0.20
   normative but `docs/monkeyllm-spec-v0.21.md` exists.

## Non-goals

No plugin API for the UI (clients only, edges-only extension surface). No
privileged side-channel (whatever Studio shows, an API client with the same
principal can fetch). No wikilink-derived graph edges in the first phases
(the Catalog indexes frontmatter links only; body wikilinks as a second edge
source is its own contract change). No realtime collaboration.

## Phasing

- **F1 — Canopy (read-only)**: spec bump, `/graph`, force-simulation canvas,
  inspector via `look`.
- **F2 — Living trails**: `/trails`, pheromone glow, shortcut/proposal
  styling, promote/prune visibility (closes T09 item 11).
- **F3 — Grove**: tree + Reading/Source, inline db browser with query
  shortcuts, HTML rendering, inspector tabs, outline for oversized bodies.
- **F4 — Governed writing**: TipTap→graft editor, tend cell edits, Ingest
  "Write" tab with curation review, session replays over the graph.

Every phase is independently demoable. i18n is contractual: every new string
in en/pt/es (the i18n test fails otherwise); semantic Tailwind tokens only;
`api.js` remains the only module that calls `fetch`.
