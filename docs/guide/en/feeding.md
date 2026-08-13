# Feeding the forest

English · [Português](../pt/feeding.md) · [Español](../es/feeding.md)

[← Handbook](./README.md)

A forest grows by being fed. Everything on this page — a dropped folder, a
pasted article, a spreadsheet, a screenshot, a clipped web page — walks the
same pipeline: converted to markdown or a dataset, given a summary (the
*scent* every later hop navigates by), and committed to the forest's own
git. The console is the window you feed it through; the nodes it plants are
the product, and they stay useful long after the tab is closed.

## The Ingest console

The Ingest console ("Add documents") is where files become forest:
converted, summarised, linked and committed — the same pipeline the command
line uses. It offers up to four tabs:

![The Ingest console with files staged for upload](../assets/ingest.png)

| Tab | What it does | How it answers |
|---|---|---|
| **Send files** | uploads files from your computer; the Station stages and adopts them | a job you can watch |
| **Write** | one authored document, curated and shown to you *before* planting | in place, with review |
| **Mirror a folder** | mirrors a directory the **Station host** can read | a job you can watch |
| **Optimize** | re-reads the mirrored folder (sync), rebuilds the index, refreshes the vector layer | the re-read is a job like any batch; the index and vector actions run while you wait |

Every mode asks **where to put them**: an existing branch, and everything
lands under it. Adding documents needs the `ingest` capability.

### Sending files

Drop files or a folder on the **Send files** tab. Markdown, text, CSV,
JSON, Word and Excel are all understood; tabular files become queryable
datasets ([see below](#datasets)). Files over 25 MB — or with no converter
for their format — are left out, and the console says so rather than
skipping them silently. Nothing is parsed in the browser: the bytes travel
to the Station and the Gardener does the reading.

### Writing in place, with review

The **Write** tab is for the article you just pasted, the note you just
finished, the thing you just learned. It walks the same pipeline as an
uploaded file — but it stops before planting and shows you the draft first
(spec J.8.1):

- the node's id and the branch it will live under,
- the **summary** — the scent every later hop navigates by,
- the tags,
- the **proposed connections**, each named by the title of what it points
  at.

Nothing has been written at that point: no node, no commit, no branch. You
can edit the summary, drop a proposed link, or discard the whole draft.
When you publish, the approved summary is planted exactly as you approved
it — never re-curated behind your back.

> **Note** — kept links stay at confidence 0.3, which is precisely the
> population the Ranger promotes or prunes based on real traffic. A link
> you are *certain* about is made by editing the node, not by ingest.

### Mirroring a server folder

**Mirror a folder** adopts a directory that lives on the Station's own
disk — useful when the corpus is already on the server, or too large to
push through a browser. Because the path is read with the Station's
filesystem access (not yours), this is a privileged act: it requires the
`admin` capability on the forest, *and* the path must sit inside one of the
Station's configured **ingest roots**:

```bash
# OS path-separated list of directories the Station may read on request.
MONKEYLLM_INGEST_ROOTS=/srv/dumps:/srv/exports
```

The default is **empty, and empty means none** (spec J.8.2): an
unconfigured Station refuses every host path — for the admin and for the
owner alike — while **Send files** and **Write** keep working, because they
carry their own bytes. `admin` is not a bypass: the capability answers
*who may ask*, the roots answer *what exists to be asked for*. When no
roots are configured, the Mirror tab does not appear at all, and the
refusal names the setting so an operator who *did* mean to mirror a folder
learns exactly what to configure.

Once a folder has been mirrored, the **Optimize** tab re-runs the mirror:
its **Ingest** button re-reads the folder you last mirrored — shown beside
the button, so you always see what will be re-read — and updates only what
changed, by hash diff. A sync keeps the summaries somebody already
approved: curation never runs on one.

### Batches are jobs

The batch modes — send, mirror, refresh — answer immediately with a **job**
(spec J.9), and the work runs on the Station:

- **One batch per forest at a time.** A second batch while one runs is
  refused, naming the running job — so the console can show it to you
  instead of starting invisible work.
- **The page follows the job, it does not hold it.** The running job's id
  rides in the address (`?job=`), so a reload restores the progress view by
  reading a record — never by re-running anything. Navigating away loses
  nothing; the job does not need its audience.
- **The pill follows you.** From every console of the forest, a small
  indicator announces the running batch — done over total, the document in
  hand, errors so far — and expands into the cancel and the way back to the
  ingest console.
- **The next batch waits in the tab.** While a job runs, the button offers
  **Join the queue**: batches start by themselves, in order, when the one
  running finishes. The queue is visible where it waits, lives in your tab,
  and dies with it — the host itself never queues invisible work. If you
  *stop* a batch, the queue holds and waits for you.
- **Cancelling is clean.** A cancel takes effect at the next document
  boundary — a document is whole or absent, never half. What was planted
  stands (those are commits), and mirroring the folder again from
  **Optimize** completes the rest without duplicating anything.

> **Note** — a Station restart forgets job *records*, never the *work*: the
> work is commits, and the forest's own account is the audit trail and
> `git log`. An address naming a forgotten job says so plainly.

When the batch finishes you get the unabridged report: created, updated,
unchanged, skipped, unsupported, errors. A partially successful ingest that
reports success would be worse than one that fails.

## Curation — the only LLM stage, always skippable

Between conversion and planting sits **curation** (spec G.4), the one stage
where a model may be involved — and the one stage that never blocks on a
missing model:

- **Without a model bound**, the summary is derived from the document's
  opening text, tagged `source: ingest` at confidence 0.7. Everything still
  ingests; the console tells you a bound model would make the summaries
  better.
- **With the forest's `ingest` binding** (set in Models — see
  [Managing](./managing.md)), the Curator writes a proper summary and tags,
  proposes up to three `related-to` links, and rolls up branch summaries so
  every region carries a scent too.

The proposed links are picked from a **closed candidate list** the catalog
offers — the model can pick from the list or pick nothing, so a
hallucinated link target is structurally impossible. Picking nothing is a
valid, common answer.

**"Nothing to do" is not a rejection.** A batch of unchanged files, or of
datasets (which are summarised from their structure), needs no model — and
the report says so: *"Nothing in this batch needed the model… The binding
is fine."* A genuine model rejection always leaves a fallback or a retry
behind in the report; that is the discriminator. The two have opposite
fixes — one is a different model or prompt, the other is nothing at all —
and the console will never send you to tune a model that was never asked
anything.

## Datasets

Tabular files become **datasets**: real SQLite payloads an agent can
`query` with read-only SQL. Two different things happen depending on what
you feed it (spec G.2.2):

- **A `.db` is adopted whole.** A SQLite file is the one format the forest
  already speaks — a dataset's payload *is* a SQLite database — so the
  bytes are copied into place, never re-inserted row by row. Types, views,
  indexes and BLOBs all survive, and a 5 GB database costs the same to
  adopt as a 5 MB one.
- **A `.csv`, `.json`, `.xls` or `.xlsx` is converted** into a newborn
  dataset with inferred column types. A workbook converts **every** sheet,
  one table per sheet — taking sheet one and dropping the rest is how a
  spreadsheet arrives missing the data somebody adopted it for.

Either way, the dataset's passport carries the **sample map** (spec G.2.3):
a `## Query manual` naming every table and every column with its type, and
`## Sample rows` showing the first three rows of every table — cells
clipped, wide tables sampled at twelve columns, at most twenty tables
sampled, and every omission stated. The map matters because a `.db` is
opaque to every text primitive the forest has: those three rows per table
are what `sniff` can see inside a payload — the vocabulary, the id format,
the date format. It is not a substitute for `query`; it is the scent that
tells an agent *which* dataset to query.

> **Note** — the usual schema caps (10 tables, 50 columns) guard a *model*
> inventing a schema; they do not apply to data you already own. A real
> 141-column ERP export adopts fine — the bound cost lives in the map, not
> in a refusal.

Datasets can also be **born in the Data console** (spec J.5.10): **New
dataset** asks for a name, a branch, and the tables and columns you
declare — fields, not SQL. The console never writes DDL; the Vine generates
the `CREATE TABLE`, creates the `.db`, and commits only the `.md` — one
`plant` call. The id is composed from the name, shown before the call, and
immutable after it. The Data console's **Import** does the same as the
ingest console's Send files — same converters, same curation, same job,
same pill — never a private parser in the browser.

## Media

An image is never "unsupported" (spec G.5.1). Images (`.png`, `.jpg`,
`.jpeg`, `.gif`, `.webp`) and audio (`.mp3`, `.wav`, `.m4a`, `.ogg`,
`.flac`) plant as **`media`** nodes: the original bytes become the payload,
and the body is the textual proxy the forest searches — text to find,
binary to consume.

What that body says depends on the forest's models:

- With no vision model bound, a built-in stub writes what is known: the
  format, the size, and that no description is available yet. The node
  exists, is findable by its filename and place, and can be described
  later.
- With a model bound to the **vision** role ("Describing images" in
  Models), the describer writes what the image shows **and any legible text
  in it** — which is what makes a slide, a whiteboard or a flowchart
  findable by `sniff`, since `sniff` reads the textual proxy and nothing
  else. It runs once per image at ingest, and its description is all an
  image ever says — worth binding a faithful model.

A describer that fails — endpoint down, image refused, too slow — falls
back to the stub with the reason in the report. A broken model never aborts
an ingest.

## The Clipper

The **Clipper** (spec J.15) is a browser extension that clips the page you
are reading into a forest — a client like any other, using the same write
paths the console uses:

- **The readable article, or just your selection,** arrives as markdown
  through the same compose pipeline, review included.
- **A screenshot** — the visible view, or a dragged region you can adjust
  and annotate — arrives as a `media` node through upload, described by the
  bound vision model like any other image.
- **A note rides along**: the region picker takes a note, typed or
  dictated, which travels as a paired compose naming the screenshot — so
  the picture and your words about it land as two nodes that reference each
  other.
- **Every clip carries its address.** Composes end with a `Source:` line;
  uploads carry the page's URL — and it survives every refresh, so a
  screenshot's node always says what page it is a screenshot *of*.

On first use it asks for the Station's origin and your username and
password, once. The password is exchanged on the spot and never stored:
what the Clipper keeps is a **paired key** narrowed to `read` + `ingest`,
expiring in 90 days, revocable at any time under People. Pairing can only
narrow your own authority, never add to it.

If the forest is busy — a batch mid-run answers `E_LOCKED` — the Clipper
queues the clip client-side and retries, settling with a notification while
you keep browsing. The queue dies with the browser; the host never queues.

Download it from the rail — **Get the Clipper extension** — or from
`GET /clipper.zip` on your Station's origin. The Integrations console walks
through the install (load unpacked, pin to the toolbar). Distribution is
self-service, like pairing: every signed-in person gets the download, not
only administrators. It reads a page only when you click it there.

## Teaching — the `## Notes` section

The sample map says what is *in* a dataset. It cannot say what it *means* —
that one column is USD while another is BRL, that `status` uses one-letter
codes, which join answers the question people actually ask. That knowledge
lives in somebody's head, and an agent writing SQL without it writes SQL
that runs and answers wrongly — the worst failure this system can produce,
because it looks like success.

So a dataset carries a **`## Notes`** section (spec C.2.1), and it is
yours:

- **Write it in the Data console**, on the **Notes** tab beside Rows,
  Structure and SQL (needs the `write` capability). Saving is one graft,
  one commit — versioned and attributed like everything else.
- **Nothing else touches it.** The Gardener rewrites the two generated
  sections and only those, so your notes survive every sync, every
  re-adoption, every payload replacement. Curation never writes it either:
  a model's guess about what a column means is exactly what this section
  exists to correct.
- **It travels with the dataset on every path.** Any material the host
  assembles for a model carries the notes of every dataset in it — `look`
  returns them, the one-shot harvest carries them, the navigating answer's
  entry carries them. Unconditionally: whether your note shares vocabulary
  with today's question is not a reason to withhold your instructions about
  how to read the data.

The console's own placeholder shows the register to write in:

```
valor_total_invoice is USD; valor_cambio is BRL.
status: A = open, C = cancelled, F = closed.
Direct imports are the rows where arrendatario is empty.
```

A few sentences here are the highest-leverage words in the forest: written
once, read on every ask that touches the dataset.

---

The forest is fed. Now connect the AIs that will read it — and grow it —
from the outside: [Connecting your AIs →](./connecting-ai.md)
