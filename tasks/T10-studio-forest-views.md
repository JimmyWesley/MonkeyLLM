status: todo

# T10 — Studio Forest Views: graph mode, files mode, governed editing, Write tab

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

1. **Spec bump first** (project rule): add to Part J —
   `GET /v1/forests/{f}/graph` (scoped catalog projection joined with heat)
   and `GET /v1/forests/{f}/trails`; confirm the Ingest text/curation path;
   record the T09 WYSIWYG-exception (governed-write editing only). Resolve
   which spec version is normative (CLAUDE.md says v0.20; v0.21 exists).
2. **F1 — Canopy**: Starlette routes through `ScopedVine` (drop filtered
   endpoints' edges, recompute counts); Explore mode switcher
   (Graph/Tree/Files); d3-force canvas (live simulation, drag/zoom/hover,
   reorganize control, reduced-motion fallback); legend from `_meta/schema.md`;
   click = `look` inspector with "Open in Files".
3. **F2 — Living trails**: heat glow, `confidence < 1` dashing,
   `discovered-shortcut` styling, promote/prune visibility.
4. **F3 — Grove**: tree (`useForestTree` pattern); `.md` Reading (default) /
   Source toggle; `.db` inline browser (table rail, auto-open first table,
   top-100 SELECT, shortcuts parsed from `## Query manual`, reads via
   `query` only); `.html` sandboxed rendering; inspector tabs
   (Passport/Index/Trails/Git); outline for bodies over the `pick` budget.
5. **F4 — Governed writing**: TipTap→`graft` editor (locked immutables,
   60-token summary counter, catalog-only wikilink autocomplete, patch
   preview); dataset cell edit → single `tend` DML with WHERE preview;
   Ingest Write tab (compose → Curator proposes passport + conf-0.3 links
   from closed candidate list → human review → `plant` as principal).
6. i18n en/pt/es for every string; tests for the new routes (scope-leak
   suite extended to `/graph` and `/trails`).

## Acceptance criteria

- [ ] Spec section merged before any endpoint code; normative version resolved.
- [ ] `/graph` and `/trails` pass the scope-leak suite (no out-of-scope node,
      edge, or derived count observable).
- [ ] Graph mode renders the fixture with live simulation; type colors come
      from the forest dialect, not constants.
- [ ] Files mode: `.md` defaults to Reading with Source toggle; clicking the
      fixture `.db` opens the browser with the first table loaded and working
      Query-manual shortcuts; `.html` renders as a page; tree stays usable
      throughout.
- [ ] No Studio code path writes a file directly: every mutation is a
      `graft`/`tend`/`plant` commit stamped with the principal.
- [ ] Write tab: posted text is never planted without review; link proposals
      only ever target catalog-offered candidates (cap 3, conf 0.3).
- [ ] Data console behavior unchanged; i18n test green; `api.js` remains the
      only `fetch` caller.

## Out of scope

Raw in-browser file editing; wikilink-derived graph edges (own contract
change); realtime collaboration; mobile; any UI plugin API.
