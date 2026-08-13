status: done (2026-08-09 spec v0.22 first, then code; full suite green and verified against a live Station. The last partial criterion, review before planting, was closed by T10.1 on the same day)

# T10 Studio Forest Views: graph mode, files mode, governed editing, Write tab

## Goal

Turn the Explore console into the product's face: an Obsidian-style **live
graph** of the forest (heat, shortcuts, proposals), a **files mode** where
every file opens in its most readable form (markdown Reading/Source, inline
`.db` browser with query shortcuts, rendered HTML), **governed editing**
(TipTap serializing to `graft`, never raw file writes), and an Ingest
**Write** tab where a person posts free text and the Curator plants it.

## Context

Full design: `docs/studio-forest-views-design.md` (normative for this task).
Validated with an interactive prototype over the real fixture (82 nodes).
Builds on T07 (Station), T08 (ScopedVine) and T09 (Studio); closes T09
item 11 (trails dashboard) along the way. The Data console is untouched.

## Steps

1. ~~**Spec bump first**~~ done as **v0.22**: J.11 map projections, J.5.4
   Forest Views, J.8 `compose`, criterion F.25, and the T09 WYSIWYG exception
   recorded. CLAUDE.md now points at v0.22, resolving the v0.20/v0.21 drift.
2. ~~**F1 Canopy**~~ done: `GET /graph` through `ScopedVine` (edges need
   both endpoints, degree recomputed); Explore mode switcher; a hand-written
   force simulation on canvas (drag, zoom, hover, reorganize, reduced-motion
   settles immediately); legend built from the dialect the payload carries;
   click selects, and "Open in Files" carries the selection across.
3. ~~**F2 Living trails**~~ done: `GET /trails`; pheromone glow, dashed
   `confidence < 1`, amber `discovered-shortcut`, each channel toggleable.
4. ~~**F3 Grove**~~ done: tree from the projection; `.md` Reading (default)
   with a Source view that labels passport and stored body separately;
   wikilinks followed inside the console; `.db` browser opening on its first
   table with Query-manual shortcuts, reading only through `query`; HTML
   bodies rendered as a sanitised page; outline for oversized bodies;
   inspector tabs Passport / Index / Trails.
5. ~~**F4 Governed writing**~~ done: TipTap editor serialising to `graft`
   (locked immutables, live 60-token summary counter, patch shown before it
   is sent, one section per commit); Ingest **Write** tab composing into
   J.8's `compose`, which walks the existing Gardener pipeline.
6. ~~i18n en/pt/es for every new string; `tests/test_station_map.py` for the
   new routes.~~

## Acceptance criteria

- [x] Spec section merged before any endpoint code; normative version resolved.
- [x] `/graph` and `/trails` pass the scope-leak suite (no out-of-scope node,
      edge, or derived count observable).
- [x] Graph mode renders the fixture with live simulation; type colors come
      from the forest dialect, not constants.
- [x] Files mode: `.md` defaults to Reading with Source toggle; clicking the
      fixture `.db` opens the browser with the first table loaded and working
      Query-manual shortcuts; `.html` renders as a page; tree stays usable
      throughout.
- [x] No Studio code path writes a file directly: every mutation is a
      `graft`/`tend`/`plant` commit stamped with the principal.
- [x] Write tab: link proposals only ever target catalog-offered candidates
      (cap 3, conf 0.3) inherited from the pipeline, so it holds. Review
      before planting now holds too, closed by **T10.1** (spec v0.24 J.8.1):
      composing stages and returns the draft, and a second call accepts it.
- [x] Data console behavior unchanged; i18n test green; `api.js` remains the
      only `fetch` caller.

## Out of scope

Raw in-browser file editing; wikilink-derived graph edges (own contract
change); realtime collaboration; mobile; any UI plugin API.

## Outcome

Shipped in one pass, contract first. `tests/test_station_map.py` (18 tests)
covers F.25: the whole-payload leak sweep, degree recomputed from the
projection's own edges, edges needing both endpoints, `parent` never naming
a hidden branch, persistent-heat-only trails, region narrowing, truncation,
capability and key refusals, and the GET route not shadowing the POST
primitives. Full suite green.

Verified against a live Station on the fixture: the graph self-organises and
selects in both themes; a node opens rendered with wikilinks followed inside
the console; the `.db` opens on its first table with Query-manual shortcuts
running through `query`; an edit committed `graft(...)` with a
`station-principal` trailer; a composed post committed `plant(...)`.

Two defects were found in that pass and fixed: the dataset browser deadlocked
on an effect that invalidated its own dependency, and the shared table's
min-width pushed right-aligned numbers out of their scroller while the
left-aligned headers stayed visible.

Deviations from the design note, all recorded there: the force layout is
hand-written rather than d3-force; editing is section-scoped because that is
what `graft` replaces atomically; the inspector has three tabs, not four (a
Git tab would have needed a history endpoint nobody had asked for); HTML
renders at body level, since there is no file-serving endpoint by design.

**Follow-up review before planting: closed by T10.1** (2026-08-09, spec
v0.24 J.8.1). Composing now stages, and the accepting call pins the approved
passport as an `on_curate` hook so the plant and the commit stay the ones
every adopted file gets. See `tasks/T10.1-compose-review.md`.

**Not a follow-up after all:** this task's branch hit `mcp` 2.0 having removed `mcp.server.fastmcp`, and flagged the unbounded `mcp>=1.2` pin as a
defect. `develop` had already fixed it forward the MCP surface is migrated
to 2.x and the pin is `mcp>=2,<3`. Resolved on merge, nothing to do.
