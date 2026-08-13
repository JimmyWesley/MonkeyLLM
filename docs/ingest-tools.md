# Ingest tools the Gardener's converter and hook surface

How the Gardener (`vine adopt` / `vine sync`, spec Part G) turns files into
forest nodes, and how to plug in your own converters or curation hooks
without touching MonkeyLLM's source.

## Pipeline

```
0 archive  ->  1 convert  ->  2 curate  ->  3 plant
```

Only stage 2 ever calls an LLM, and stage 1 runs fully without one `vine
adopt` on a plain markdown/csv/json dump needs no `MONKEYLLM_LLM_ENDPOINT`
at all. `--curate` opts into stage 2 (`src/monkeyllm/curator.py`): A.4
summaries, tags, and edge proposals (G.4.2.1).

## Built-in converters (stage 1)

| Extension | Converter | Needs |
| --- | --- | --- |
| `.md` | `MarkdownConverter` | |
| `.txt` | `MarkdownConverter` | |
| `.csv` | `CsvConverter` -> dataset (C.7.1 schema + rows) | |
| `.json` (tabular array) | `JsonConverter` -> dataset | |
| `.db` / `.sqlite` / `.sqlite3` | `SqliteConverter` -> dataset **adopted whole** (G.2.2) | |
| `.xlsx` | `XlsxConverter` -> dataset, one table per sheet (G.2.4) | `pip install monkeyllm[ingest]` (openpyxl) |
| `.xls` | `XlsConverter` -> dataset, one table per sheet (G.2.4) | `pip install monkeyllm[ingest]` (xlrd) |
| `.docx` | `DocxConverter` (spec v0.12 G.2.1) | `pip install monkeyllm[ingest]` (python-docx) |

`.xls`/`.xlsx`/`.docx` silently report `unsupported` when the extra isn't
installed sync never crashes on a missing optional dependency. SQLite
needs no extra: it is the standard library and already the payload format.
Anything without a matching converter is reported `unsupported` in the
adopt/sync report; nothing is dropped silently.

A SQLite source is **not** rebuilt row by row. The converter reads the
structure of every table and its first 3 rows; the Gardener copies the file
into place as the node's payload and plants a passport with no `schema`
(G.2.2). Rebuilding would be unbounded in the source's size and lossy in
its types and the result would be byte-for-byte what the source already
was. A file whose header is not `SQLite format 3` is an error naming the
file, never a crash.

Every dataset passport from `.csv`, from a workbook, from a `.db`, and
from a C.7.1 birth carrying rows gets the **sample map** (G.2.3) in its
body: `## Query manual` (tables and columns) followed by `## Sample rows`
(each table's first 3 rows as a pipe table, ≤12 columns wide, saying how
many it left out). That map is the only thing `sniff` can see inside a
payload, so it is what makes a dataset findable by what it *contains*
rather than only by what it is called. A `sync` rewrites those two sections
and leaves the rest of the body alone.

The map is also **the only thing the ingest model reads** about a dataset
(G.4.6): a 5 MB CSV and a 5 GB database both cost about 150 tokens, so
curation never scales with the source. Without a bound model the G.4.1
factual template stays, as always.

Sizes the Gardener does **not** refuse (G.2.5): C.7.1's ≤10 tables and ≤50
columns bound what a *model* may declare, not what an operator already
owns, so a 141-column ERP export adopts whole. What is bounded is the map,
because that is where the tokens are.

The `DocxConverter` does a single-pass `w:t` traversal in document order:
heading-styled paragraphs become `##`+ headings, pipe tables keep their
rows (nested tables flatten into cell text), fragmented runs are merged per
paragraph, and text-box content is captured. Headers/footers are excluded
by design letterhead is scent noise, not content.

## Discovery order (G.2)

```
forest-config command hooks  >  monkeyllm.converters entry points  >  built-ins
```

Each source is tried per file extension, in that order, and the first
converter that claims the extension wins. This lets you override a
built-in (e.g. run your own `.docx` pipeline) without forking the package.

### 1. Command hooks (no dependency, any license)

Add a `converters:` map to `_meta/gardener.yaml` in the forest a shell
template with `{input}`/`{output}` placeholders:

```yaml
converters:
  ".pdf": '"/path/to/pdf-tool" "{input}" "{output}"'
```

The command must write markdown to `{output}` (or print it to stdout) and
exit 0; a `# Title` heading on the first line becomes the node title. This
is the escape hatch for copyleft or heavyweight tools (e.g. a PyMuPDF/AGPL
PDF extractor) that can never be an installed dependency of MonkeyLLM
itself the license rule (MIT-clean built-ins/extras only) stays intact
because the tool lives outside the process, invoked by `subprocess.run`.
A non-zero exit or empty output raises `E_SCHEMA` and aborts adopting that
one file (the Gardener never plants a broken node); the rest of the batch
is unaffected.

### 2. `monkeyllm.converters` entry points (installable plugin package)

Register a class or callable implementing the `Converter` protocol
(`convert(self, path: Path) -> Conversion`) under the `monkeyllm.converters`
entry-point group in your plugin package's `pyproject.toml`:

```toml
[project.entry-points."monkeyllm.converters"]
pdf = "my_monkeyllm_plugin:PdfConverter"
```

`Conversion` is a small dataclass: `kind` (`"markdown"` or `"dataset"`),
`title`, and either `markdown` or `schema`+`rows` (C.7.1 declarative
schema, for converters that discover tabular data). A broken plugin
(import error, exception) is skipped, never blocks discovery of the rest.

### 3. Built-ins

Fixed fallback list (`builtin_converters()`); always available, never
override the two sources above.

## `on_curate` hooks (G.4.3)

Deterministic enrichment that runs after the LLM curator (or instead of it,
when `--curate` is off) and before `plant`. A hook is a callable taking the
frontmatter draft dict and returning it (mutated or replaced):

```python
def add_compliance_tag(draft: dict) -> dict:
    draft.setdefault("tags", []).append("compliance")
    return draft
```

Register it under the `monkeyllm.hooks` entry-point group with name
`on_curate`:

```toml
[project.entry-points."monkeyllm.hooks"]
on_curate = "my_monkeyllm_plugin:add_compliance_tag"
```

Hooks run in discovery order; a hook that raises has its error recorded in
the adopt/sync report (`report["errors"]`) but never aborts the batch —
already-planted nodes stay planted, later files keep processing.

## `_meta/gardener.yaml` reference

```yaml
converters:
  ".pdf": '"tool" "{input}" "{output}"'   # G.2 command hooks
curation:
  default_tags: ["internal"]              # merged into every curated draft
  directives: |                           # injected into the curator's system prompt
    Prefer a formal tone. Flag anything mentioning PII.
```

`curation.directives` is free text passed straight to the LLM system
prompt (`src/monkeyllm/curator.py`) use it for house style, domain
vocabulary, or things the model should watch for, not for contract
changes (those still require a spec version bump, per the project's
"the spec is the truth" rule).

## What the Gardener will never do

- **Never delete nodes.** A source file removed on disk makes `sync`
  report the passport `stale`; the Ranger (Part H) is the only process
  that later acts on stale/uncertain state, and even it never deletes.
- **Never write DDL.** Dataset-producing converters hand back a
  declarative `schema` (C.7.1); Vine generates the `CREATE TABLE`s.
- **Never mint new node ids from thin air for edges.** Edge proposals
  (G.4.2.1) only ever target existing nodes drawn from a closed
  catalog-search candidate list a hallucinated target is structurally
  impossible to plant.
