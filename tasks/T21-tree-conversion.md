status: done (2026-09-17: spec v0.84 CUT and IMPLEMENTED — `Conversion.kind:
"tree"`, G.2.8 (the branch carries the front matter, the parts become
`<id>/<NNN>-<slug>`, `succeeds` from part N to N-1 through the audited link
write, a refresh reconciles by part and deletes nothing), A.3 `source_part`
as a string of DIGITS (`yaml.safe_load("012")` is 10), J.8.4's passport
applied to the branch alone. F.239-F.246 green in
tests/test_v084_tree.py. The gotcha worth keeping: `_passports()` keyed on
`source_path` alone collapses a tree, because every part of one document
shares it. OPEN, by name: the section-grain editor has no Markdown
surface; the rich editor holds neither a Link nor an Image node
(StarterKit ships neither), so a body carrying one still edits as source;
and the PDF extension appends a page's tables at `#### Tables` rather than
interleaving them at their bbox position. Uncommitted — Jimmy commits by
hand.)

# T21 Tree conversion: a document that becomes a branch

## Goal

Let a converter answer with a **tree** — the document's own front matter
plus its parts, in order — so that a long document enters the forest as a
branch with one node per part instead of one node with everything in it.
Each part gets its own scent, its own place under a branch, its own links
and its own heat, and a reader reaches the chapter instead of the book.

## Context

The PDF extension (`ideias/extensions/pdf`) extracts every page of a
document into one node with a `## Page N` section per page. Measured on a
six-page report: 7,567 characters, about 1,900 tokens — exactly right, and
`pick` returns that body in one call under its 4,000-token ceiling
(`PICK_MAX_BODY_TOKENS`).

A 500-page book converted the same way is 150,000-300,000 tokens in one
node. Nothing that reads it breaks: `export` has no budget (J.14.1), `pick`
pages (C.4.1), `sniff` finds a term and names the page. What breaks is
everything that decides whether the book is ever **reached**:

- the scent is one 60-token `summary` (A.4) standing for 500 pages, and it
  cannot be bought out of the problem — `locate` answers inside 800 tokens
  (`BUDGET_LOCATE` in `vine.py`), which is about ten results at 60 tokens
  and about five at 120, so a longer summary halves the number of entry
  points an agent chooses between;
- `locate` ranks the book as **one result**: a shelf of six books is a
  ranking over six items, and "which part of which book" is never asked;
- `sniff` returns **one node** with forty matches in it and the budget
  decides which of the forty the reader sees.

Jimmy's sentence for the fix: *explode big contexts into many
micro-contexts and create links between them*. Granularity solves what the
budget cannot.

**Where the cut is decided.** The engine never decides where a document
divides: that requires knowing the format and usually the subject, and
`src/monkeyllm/` must stay forest-agnostic — no content vocabulary, not
even in a hint. The contract says what a tree **is** and what the Gardener
**does** with one; the cut is the converter's, which is also where the
knowledge and the accountability are.

**Spec.** Drafted for v0.84: `Conversion` gains `kind: "tree"` (amends
G.2); a new **G.2.8** carries the whole rule set (shape and refusals,
typing, ids, the branch body, what every node records, links, curation,
batch planting, the archive, `sync`, reading it whole, and that nothing
changes on the wire); `source_part` joins A.3; G.1, G.3, G.4.2.1, G.4.4 and
J.8.4 take one amendment each. Acceptance **F.239-F.246**. No new J
section, no new primitive, no new parameter on any primitive.

## Steps

1. **Cut spec v0.84** with the G.2.8 round merged in. **Check the file does
   not exist before writing it** (the v0.74 lesson: a `write_text` onto a
   live spec destroyed a parallel session's work, and only APFS birthtime
   caught it). Verify the cut by `diff` against v0.83, not by re-running
   anchor asserts — a diff is what catches an edit that never landed.

2. **Engine — the conversion.** `Conversion` (`gardener.py` ~86-110) gains
   `children: list[dict] | None = None`. Nothing else on the transport:
   `src/monkeyllm/extensions/converters.py` builds a `Conversion` from a
   worker's JSON with its accepted set derived from the dataclass's own
   fields, so a heavy handler (L.5) can answer `kind: "tree"` the day the
   field exists.

3. **Engine — validation, in one place.** A `_validate_tree` called from
   `_ingest_file` before any branch is ensured: `children` a list of
   objects, at least two, each with a non-empty `title` and non-empty
   `markdown`, at most `TREE_CHILDREN_MAX` (200; hard ceiling 999 — see the
   padding rule). Every refusal lands in `report.errors` naming the
   converter and the file, plants **nothing**, and lets the rest of the
   batch through, exactly like every other conversion failure (G.2).

4. **Engine — `source_part`.** Declare it on `NodeSpec` (`models.py`)
   rather than leaving it to `extra="allow"`, for the reason `lang` is
   declared: a field that passes through unread is a field that stores
   garbage. It is a **string of digits** — `yaml.safe_load("a: 012")` is
   **10** (YAML 1.1 octal), verified, so an integer is `E_SCHEMA` naming the
   field and never coerced. Refuse it from a caller in
   `frontmatter_dict()` the way `moved_from` is refused (C.15): only the
   Gardener writes it.

5. **Engine — the plant.** Split `_ingest_file`'s tail so the draft build
   (aliases, origin, provenance line, curation, content policy) is one
   function the branch and each child share, then plant through
   `vine.plant([...])` in chunks of `MAX_BATCH_PLANT` (20), root first, in
   order. **`_plant_batch` must forward `adopted`**: `plant()` takes it
   keyword-only and drops it on the list path today, and `_plant` refuses a
   `media` node with no payload unless `adopted` (C.7.5 rule 4) — so a
   media tree would be refused in a batch and planted fine one by one.
   Branch id `<id>/_index`, children `<id>/<NNN>-<slug>` with **fixed
   three-digit padding** (a width sized to the child count breaks id order
   the first time a sync grows the tree past 9 or past 99, and ids are
   immutable so they cannot be widened afterwards).

6. **Engine — the branch body.** The tree's `markdown` above the A.5
   sections, which must still parse: `indexer.SUBBRANCH_SECTION`,
   `indexer.BANANAS_SECTION` and `Cross trails`. `parser.extract_section`
   matches case-insensitively, at any heading level, exact match first and
   then **by prefix**, and takes the FIRST match — so a document heading
   named like one of them captures the index's own entries. Demote such a
   heading to emphasis, keep its words, count it in
   `report.headings_demoted`. Branch summary: `derive_summary(markdown,
   title)` at ingest, replaced by the G.4.4 rollup when curation runs
   (the branch is `source: ingest`, so rollup already covers it).

7. **Engine — the sequence.** `succeeds` from part N to part N−1, written
   on the child's own draft `links` at plant time (link targets are not
   required to exist, so no second pass). Check the dialect **once per
   tree** (`vine.forest.dialect.rels`) before building the batch — an
   undeclared rel inside a batch refuses the whole batch (C.7.4 rule 1) —
   and report `report.sequence_skipped` when the forest declares no
   `succeeds`. A fresh forest declares it (`forest.py::_SCHEMA_BODY`), so
   the negative control is a forest whose `_meta/schema.md` was written
   before v0.58.

8. **Engine — `sync`.** `_passports()` keys on `source_path` and a tree
   makes every node share one, so it collapses to the last node read
   today: make it return the document's node plus its parts. Then in
   `_sync_one`: refresh a part that exists (id kept, curated scent kept —
   a refresh never curates), plant a part that is new, report `stale` a
   part the source lost (never delete — Part G's standing rule), and
   recompute the sequence over the parts that remain. The rewrite goes
   through `links.rewrite_link` (`links.py`), extended to **add** a link
   the passport does not carry and to take `by="gardener"` in the
   `_SUBJECT` table (`gardener(sequence): <id> succeeds-><target>`, which
   `history` parses as the action `gardener`). One audited write path, not
   a second one. The G.2.6/G.2.7 backfills in `_settle_unchanged` run on
   the document's node only.

9. **Engine — aliases and the archive.** `derive_aliases` runs for the
   document's node alone; a child derives only from its own title (a code
   in the file name names the book, and copying it onto 200 chapters
   poisons the one field `locate` searches by). `_archive` is called once,
   with the tree branch as the node, so the original lands in that branch's
   `_assets/` and is named by `payload`/`payload_type`/`payload_hash` on
   the branch.

10. **Curator.** `_propose` (`curator.py`) excludes the other parts of the
    same document from candidacy — the draft's own subtree, decided by its
    `parent` when the draft carries `source_part`. They are already joined
    by `part-of` and the sequence, and three proposals spent inside a book
    are three not spent on the forest.

11. **Station.** `PassportGate` (`apps/station/monkeyllm_station/compose.py`)
    keys on `draft["source_path"]`, which every node of a tree shares: pin
    the passport on the node with **no** `source_part` (the document's own)
    and let the curator speak for the parts. Without this an upload of a
    200-chapter book lands as 200 copies of one summary.

12. **Fixture.** `forests/scripts/build_fixture.py` needs **nothing**: its
    `SCHEMA_MD` already declares `succeeds` (line 68) and `supersedes`
    beside it. Do **not** add a tree-shaped document to the shared fixture —
    `tests/test_bench_baselines.py:36` and `tests/test_infra.py:49` assert
    82 nodes, and the bench corpus would need re-baselining. The suites for
    this round build their own forest (`init_forest`) with a stub
    tree-returning converter, which is also the only way to test the
    refusals.

13. **The pdf extension's cut rule** (`ideias/extensions/pdf`, gitignored,
    shipped as its own zip — separate work, after the engine lands).
    `worker.py::convert` returns `{kind: "tree", …}` when the document is
    worth cutting: bookmarks → parts (`_outline` already walks the bookmark
    tree but keeps titles only and drops the destinations — a cut needs
    `reader.get_destination_page_number`); else heading detection; else
    windows of N pages titled by their range; and **never below about
    3,000 tokens**, where `pick` reads the document whole anyway. Knobs are
    environment variables (`MONKEYLLM_EXT_PDF_SPLIT`, `_SPLIT_MIN_TOKENS`,
    `_WINDOW_PAGES`), like every other setting in that worker: a heavy
    handler receives the path and nothing else, so a manifest `config`
    block it could not read would be a lie.

14. **Studio.** Explore renders branches already (graph, tree and files
    modes read J.11 plus the primitives), and so do Links, tags and Ask.
    Two named needs:
    - the ingest report's `Report` rows (`views/Ingest.jsx`, the `groups`
      list) gain `sequence_skipped` as a warn row and `headings_demoted`
      beside the `tags_dropped`/`aliases_clipped` counters, with the en/pt/es
      keys;
    - the read console downloads one node (`api.exportNode`); a branch that
      is a document wants the subtree zip (`?recursive=true`, J.14.1) —
      one control, and the only place a person gets the book back whole.

15. **`docs/extending.md`**: the authoring guidance for the cut (when to
    return a tree, where to cut, what belongs in the branch's body, never a
    one-child tree, give every part a real title, do not sort the list).
    Prose is written and schemas are derived (L.16 rule 1), so this is
    written by hand beside the generated seam reference.

## Acceptance criteria

- [ ] F.239 A `markdown` conversion is untouched: same node id, same
      passport bytes, same report shape and same catalog row before and
      after the round, compared as bytes; a forest with no tree-returning
      converter is byte-identical on adopt, sync, locate, scan and coverage.
- [ ] F.240 A tree of twelve children plants one branch and twelve nodes:
      ids and padding, types from the source, parent, `source_part`, the
      shared `source_path`/`source_hash`, `origin` on every node, the three
      A.5 sections still parsed with the front matter above them, and
      `scan(after: "")` in document order. A front-matter heading colliding
      with an A.5 section name is demoted, counted, and the index still
      parses.
- [ ] F.241 `move(rel: "precedes", direction: "in")` walks the document
      forward and `move(rel: "succeeds")` walks it back; every sequence link
      is confidence 1.0 and none appears in Part H's managed population or
      J.18's listing.
- [ ] F.242 On a forest declaring no `succeeds`, the same tree plants the
      branch and all its children, carries no `succeeds` anywhere, does not
      fail, and names the branch in `sequence_skipped`.
- [ ] F.243 One child, no children, an empty child title, an empty child
      body and `TREE_CHILDREN_MAX + 1` children are each a per-file error
      that plants nothing — no branch, no orphan — while the rest of the
      batch lands.
- [ ] F.244 A tree of twenty-five children lands in more than one commit,
      in order, complete; a run abandoned between two commits leaves the
      prefix, and the next `sync` plants exactly what is missing, duplicates
      no id and completes the sequence.
- [ ] F.245 `sync`: an edited part refreshes in place with its id, summary
      and tags intact; an added part plants and joins the sequence; a
      removed part is reported `stale` and still readable; a reordered
      sequence is rewritten by the audited link path under a
      `gardener(sequence)` subject that `history` reads back.
- [ ] F.246 `export?recursive=true` on the branch returns a zip of
      byte-identical single exports; `sniff` scoped to the branch names the
      part that matched and does not rank the branch above its own children;
      an upload passport applies to the branch alone and the parts are
      curated; the derived aliases sit on the branch and on no child.

## Out of scope

- **Retrofitting a document already ingested as one node.** Nothing here
  converts a leaf into a branch. See the open questions.
- **Splitting from the wire.** No primitive learns a parameter, `plant` is
  unchanged, `ScopedVine.plant` is unchanged, and an agent cannot ask for a
  document to be cut.
- **The engine deciding a cut.** Not a built-in heuristic, not a fallback
  chunker, not a config knob in `gardener.yaml` that guesses. The converter
  decides or nobody does.
- **The Ranger splitting branches.** A tree branch over 150 entries raises
  `needs_split` like any other branch; acting on that flag is still nobody's
  automatic job.
- **OCR, layout analysis, or anything that improves what the converter
  reads.** This round is about what happens to what it returns.

## Open questions

- **Retrofitting.** A `sync` could notice that the converter now answers
  `tree` for a node planted as a leaf. Three shapes, all ugly in different
  ways: refuse and report (the node stays a leaf forever); plant the tree
  beside it and `supersedes` the leaf (the sweep already suppresses the
  superseded — my preference); or re-mint the leaf as a branch, which is a
  `transplant` of a kind C.15 refuses for branches. `recurate` (J.13.6) is
  the shape a decided answer would take.
- **Where `TREE_CHILDREN_MAX` is configured**, and whether a document above
  it should be refused whole (today's draft) or planted up to the cap with
  the remainder reported — a partial document is exactly what the refusal
  rule exists to prevent, so this needs deciding before the first 1,200-part
  book meets it.
- **A tree branch under `content: cached`** (G.7): a leaf's body moves to
  `_derived/bodies/`, a branch's body is the indexer's render. The right
  rule is probably "the branch is always inline, the children obey the
  policy", but that is a G.7 amendment nobody has needed yet.
- **A `media` source answering with a tree** (a long transcript cut into
  sections): the typing rule admits it and the bytes are named once on the
  branch, but every child is then a `media` node whose `look` reports
  `payload_missing` — true, and it will read like a fault.
