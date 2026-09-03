// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The skill, in blocks (J.5.12, v0.60).
 *
 * The file the Skills console hands out grew every version that touched
 * it — 3,921 tokens by v0.59, +14% in that release alone — and it was
 * indivisible: an agent that fires it pays for all of it, including the
 * ~1,400 tokens of `plant` anatomy that a J.2.6 paired key carrying
 * `{read, ingest}` is not allowed to execute. A runtime holds only the
 * `description` in context and loads the body on trigger, so the number
 * to shrink is what a firing costs.
 *
 * So: a folder. `SKILL.md` holds what every agent needs and is a complete
 * skill on its own; `references/*.md` hold what only some do and cost
 * nothing until read. Four rules keep the split safe — the core is never
 * a teaser, every reference is named in the core with the condition that
 * sends an agent to it, no instruction exists in two blocks, and several
 * INSTALLED skills is not the split (each would cost its description in
 * every session, and the runtime rather than the core would decide which
 * loads).
 *
 * Every example carries the forest argument, which is the shape the tools
 * actually take: the previous file had twenty-three call examples and not
 * one of them passed it.
 *
 * English on purpose: these files address a model, not the reader (J.5.3's
 * content-not-chrome, applied outward).
 */

/** Capability a block needs, and the line the core prints to send an agent
 *  to it. Order is the order they are offered and assembled. */
export const BLOCKS = [
  { id: 'saving', cap: 'ingest', title: 'Saving to the forest',
    file: 'references/saving.md',
    when: 'the user says something worth keeping' },
  { id: 'writing', cap: 'write', title: 'Writing nodes directly',
    file: 'references/writing.md',
    when: 'you are about to create, edit, move or remove a node' },
  { id: 'time', cap: 'read', title: 'Asking about a period',
    file: 'references/time.md',
    when: 'the question is about a period ("last week", "since June")' },
  { id: 'datasets', cap: 'query', title: 'Datasets',
    file: 'references/datasets.md',
    when: 'you need rows, counts or aggregates from a `type: dataset` node' },
  { id: 'sharing', cap: 'read', title: 'Handing a document to a person',
    file: 'references/sharing.md',
    when: 'a document has to leave the forest and reach a person' },
]

/** The agent archetypes the split exists for. A preset is a shortcut through
 *  the block list, never a different list: what it selects is exactly what a
 *  person could tick by hand, so nothing is reachable only through one. */
export const PRESETS = [
  { id: 'reader', blocks: ['time'] },
  { id: 'memory', blocks: ['saving', 'time'] },
  { id: 'curator', blocks: ['saving', 'writing', 'time', 'sharing'] },
  { id: 'analyst', blocks: ['datasets', 'time'] },
  { id: 'all', blocks: BLOCKS.map((b) => b.id) },
]

const same = (a, b) => a.length === b.length && a.every((x) => b.includes(x))

/** Which preset a selection IS, if any — the console highlights it rather
 *  than keeping a second copy of the choice. */
export const presetFor = (blocks) =>
  PRESETS.find((p) => same(p.blocks, blocks))?.id || null

/** The blocks a grant carries by itself — the console's default selection
 *  (J.5.12 v0.60). `tend` implies the dataset block for the same reason
 *  `query` does: it is the other half of one surface. */
export const defaultBlocks = (caps) => BLOCKS.filter(
  (b) => caps.includes(b.cap) || (b.id === 'datasets' && caps.includes('tend')),
).map((b) => b.id)

const list = (xs) => xs.map((x) => `\`${x}\``).join(', ')

/** FNV-1a, for the one case a name has to be shortened: two selections that
 *  share a first forest must still produce two names. */
const shortHash = (s) => {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(36).slice(0, 6)
}

/** The skill's `name:` and its folder on disk (J.5.12, v0.61).
 *
 *  It was a constant, so a person generating one skill per forest — which
 *  is what this console invites — installed two files claiming the same
 *  name. Derived from the selected forests instead: sorted, so the same SET
 *  reproduces the same name; hashed when it would not fit, so two
 *  selections sharing a first forest still differ. */
export const skillName = (forests) => {
  const ids = (forests || []).map(
    (f) => String(f.id || f).toLowerCase().replace(/[^a-z0-9]+/g, '-')
      .replace(/(^-|-$)/g, '')).filter(Boolean).sort()
  if (!ids.length) return 'monkeyllm-memory'
  const full = `monkeyllm-${ids.join('-')}`
  if (full.length <= 64) return full
  return `monkeyllm-${ids[0].slice(0, 40)}-${shortHash(ids.join(','))}`
}

/** Re-wrap a paragraph whose length depends on how many forests were picked.
 *  The fixed prose below is wrapped by hand; only the interpolated sentences
 *  need this, and a ragged file is a file somebody edits by hand. */
const fill = (text, indent = '', width = 78) => {
  const out = []
  let line = indent
  for (const word of text.trim().split(/\s+/)) {
    if (line.length > indent.length && line.length + 1 + word.length > width) {
      out.push(line)
      line = indent
    }
    line += (line.length > indent.length ? ' ' : '') + word
  }
  out.push(line)
  return out.join('\n')
}

/* ---------------------------------------------------------------- core */

/** The reference table: every block that shipped, named with its trigger.
 *  A file the core does not name does not exist (J.5.12 rule 2). */
const referenceTable = (blocks, caps, inline) => {
  if (!blocks.length) return ''
  const rows = blocks.map((b) => {
    // A block generated for a capability the key does not hold says so in
    // its own first line; the table repeats it so the choice is visible
    // before the file is opened (J.5.12, v0.60).
    const short = b.id === 'datasets'
      ? (caps.includes('query') ? '' : ' (needs `query`)')
      : (caps.includes(b.cap) ? '' : ` (needs \`${b.cap}\`)`)
    const where = inline ? `**${b.title}**, below` : `\`${b.file}\``
    return `| ${b.when}${short} | ${where} |`
  }).join('\n')
  const intro = inline
    ? `The sections below cover what this one does not. Read a section when its
       row applies, and not before.`
    : `Read one of these when its row applies, and not before — everything above
       works without them.`
  return `
## More, when you need it

${fill(intro)}

| when | read |
|---|---|
${rows}
`
}

/** The routing table: which forest for which question (J.5.12 v0.60).
 *  Only for a multi-forest skill — inside ONE forest \`coverage()\` is a
 *  single live call and a written-down copy of the shape can only drift. */
const routingTable = (forests) => {
  const rows = forests.map((f) => {
    const roots = (f.roots || []).slice(0, 4)
      .map((r) => `${r.title} (${r.nodes})`).join(', ')
    return `| \`${f.id}\` | ${roots || '—'} | ${f.caps.join(', ')} |`
  }).join('\n')
  return `
## Which forest

| forest | its largest roots (nodes) | your key there |
|---|---|---|
${rows}

That is a map for choosing, not an inventory: it was read when this file was
generated. \`coverage(forest)\` is the current shape of any one of them, and
\`forests()\` is what your key may actually do today.
`
}

const core = ({ origin, forests, station, blocks, caps, inline, reinstall }) => {
  const multi = forests.length > 1
  const ids = forests.map((f) => f.id)
  const one = ids[0]
  const subject = multi ? 'These forests are' : 'This forest is'
  const named = multi
    ? `the knowledge forests ${list(ids)}`
    : `the knowledge forest \`${one}\``

  const them = multi ? 'them' : 'it'
  const their = multi ? 'their' : 'its'

  return `---
name: ${skillName(forests)}
description: >-
${fill(`Use the MonkeyLLM ${multi ? `forests ${ids.map((i) => `"${i}"`).join(', ')}`
    : `forest "${one}"`} at ${origin} as persistent memory. Recall from ${them}
  before answering anything in ${their} domain, save durable new knowledge into
  ${them}, and cite the node ids you read.`, '  ')}
station: "${station}"
forests: [${ids.join(', ')}]
---

# ${subject} your memory

${fill(`The MCP server \`monkeyllm\` serves ${named} at ${origin}. Treat ${them}
as persistent memory for ${their} domain: ${multi ? 'they outlive' : 'it outlives'}
this conversation, other people and agents feed ${them} too, and everything you
read carries a node id you can cite.`)}

A **node** is one markdown document with a curated passport (title, summary,
tags) and a body. A **branch** is a node that holds others; its id ends in
\`/_index\`; \`kind\` on the wire is \`branch\` or \`note\`. Everything else
is a leaf note.

## Every call names the forest

The forest is the first argument of every tool on this server:

    locate(forest: "${one}", query: "pheromone")

${fill(`Below, \`forest\` stands for ${multi
    ? 'whichever of the forests above the question belongs to'
    : `\`"${one}"\``}. There is no default — a call without it is refused before
it reaches any forest.`)}

## Call forests() first

\`forests()\` is the one call that takes no forest, and it is where a session
starts. It returns what your key may actually use: the forests, the
capabilities you hold in each, the \`roots\` to start from, \`locked\` when a
forest cannot serve right now — and \`station\`, this server's version.

**This skill was generated against Station ${station}.** When \`forests()\`
reports a newer one, say so and hand your operator this link — it rebuilds
exactly this skill, same forests and same blocks, against the Station as it is
now:

    ${reinstall || `${origin}/f/${one}/skills`}

Do it before relying on the file: a stale skill is a stale map of the surface,
and tools it does not name still exist. You cannot install it yourself, and
that is deliberate — a skill outlives the connection that delivered it, so a
person decides what your standing instructions say.

A forest named in this file that \`forests()\` does not list is not a defect
to report or route around. Your key's reach narrowed, and everything outside
a key answers \`E_NOT_FOUND\` exactly as a missing node does.
${multi ? routingTable(forests) : ''}
## Recall before you answer

${fill(`For any question ${multi ? 'these forests' : 'the forest'} could answer
(${their} projects, people, decisions, documents, data), recall first and reason
after:`)}

- \`answer(forest, question)\` — the one-shot: retrieval plus a grounded reply
  with sources. Prefer it when the forest's answer is the answer.
  \`min_evidence: n\` refuses to answer over too little (it replies
  \`answer: null\` and hands you the retrieval instead); \`min_score\` makes
  that floor count *relevance* and not just items, since the sweep returns
  \`k\` results whatever their scores. **The two compose, and more sharply
  than they read:** scores are compressed, so a threshold that means anything
  usually admits only the one item that ranked top of both retrievers —
  \`(min_evidence: 1, min_score: 0.02)\` is the useful pair, and 2 is a
  deliberate demand for corroboration you will pay for in refusals. A refusal
  says which half fired: \`evidence_count\` beside \`below_min_score\`, the
  items the threshold dropped. Read a few \`harvest\` scores before choosing
  a number — it means something in this deployment and nothing outside it.
- \`harvest(forest, query)\` — retrieval without a model call: top items and
  matched passages, each carrying the \`trail\` it came from. Prefer it when
  you will reason over the material yourself.
- \`locate(forest, query)\` → \`look(forest, id)\` → \`pick(forest, id)\` —
  navigate: rank entry points, read a node's passport, open its body.
  \`pick\` reads one section (\`section: "Header"\`), several at once
  (\`section: ["A", "B"]\`), and a body over its 4000-token budget arrives in
  PAGES: pass the response's \`next\` back as \`after\` until none comes, and
  the concatenated pages are the body, byte for byte. \`look\` also says who
  and when: \`source\`, \`created\`, \`updated\`, \`aliases\`, \`origin\`.
- \`sniff(forest, terms)\` — literal text search inside bodies (substring,
  not regex).
- \`scan(forest, parent_id)\`, \`move(forest, id)\` — list a branch's nodes by
  metadata; follow a node's typed edges. \`scan(forest, "_index",
  recursive: true)\` maps a whole forest cheaply; to walk one completely,
  start with \`after: ""\` and keep passing \`next\` back — id order,
  complete, no duplicates. \`filter\` matches any passport field
  (\`{"source": "agent"}\` lists what agents wrote).
- \`coverage(forest)\` — what a forest actually holds: the roots you can start
  from, how many nodes sit under each, where that material came from and when
  it arrived. Metadata only; it opens nothing. Worth one call before your
  first question in a forest you have not read before.
- \`view(forest, id)\` — the image behind a \`type: media\` node, if you can
  see images.

**\`locate\` and \`sniff\` search different things, and that is the one thing
worth remembering about this surface.** \`locate\` reads curated metadata —
titles, summaries, tags — and never bodies. So an exact term nobody lifted
into a summary (an error code, an invoice number, a library name) returns
\`{"results": []}\` from \`locate\` and is found instantly by \`sniff\`. When a
\`locate\` comes back empty it tells you how many nodes it searched and points
you at \`sniff\`: an empty result is never evidence that the forest does not
know. Do not answer from your own knowledge until \`sniff\` has come back
empty too.

**Before you trust a silence, ask what the forest holds.** An empty
\`locate\`, an empty \`sniff\` and a refusal all mean the same narrow thing:
*not in the material I searched*. \`coverage(forest)\` is the only call that
tells you what that material is. If somebody asks about a subject and no root
there covers it, say that — the forest has never heard of it — rather than
answering from whatever came closest. A partial corpus answers with a
citation, a source and a trace, which is exactly the shape of a trustworthy
answer, so the wrong one is indistinguishable from the right one unless you
check. Each root also carries the \`origin\` prefix that \`scan\`'s
\`origin_prefix\` filter takes, for listing everything that came from one
source.

Three things that save round trips, all worth using by default:

- \`look\` takes up to 10 ids at once and \`pick\` up to 5 — one call, one
  budget, every id you sent accounted for in \`nodes\`, \`missing\` or
  \`dropped\`.
- \`locate(forest, query, include: ["outline"])\` returns each result's
  section headers, which is exactly what \`pick(forest, id, section)\` takes —
  so you can go from search to passage without the \`look\` in between. Every
  result also carries \`body_tokens\`, so you know the size of what you are
  about to open.
- \`fields\` is the cost lever on \`look\` and the page lever on \`scan\`:
  \`fields: ["summary"]\` costs a fraction of the digest, and a \`scan\` page
  holds more items the fewer fields each carries. A clipped digest NAMES what
  it dropped in \`truncated_fields\` — without that flag, \`edges_out: []\`
  really is an isolated node.

Cite node ids for anything you assert from the forest — and cite them the way
a person can read: the title first, the id in brackets, as in
\`Pheromone (projects/monkeyllm/pheromone)\`. Every result you get already
carries both, so this costs nothing; an id alone means nothing to whoever
reads your answer. If the forest and the user disagree, say so: the forest
owns its documents, the user owns the present.
${referenceTable(blocks, caps, inline)}
## Respect the contract

- Your key decides what you see and what you may write; what it cannot reach
  does not exist. Never work around a refusal — say what was refused and
  which capability it needs.
- Every read is budgeted. \`truncated: true\` means ask narrower, not retry
  harder.
- Every refusal is \`{error: {code, message, hint}}\` and the hint is
  actionable: \`E_SCHEMA\` means fix the argument it names, \`E_NOT_FOUND\`
  means the node is absent or outside your key, \`E_INTERNAL\` means the
  server failed and repeating the call will not help.
`
}

/* ---------------------------------------------------------- references */

/** A block generated for a capability the key does not hold says so in its
 *  own first line (J.5.12, v0.60): conditional teaching is legitimate,
 *  unconditional teaching of an impossible write is the contradiction. */
const needs = (cap, caps) => caps.includes(cap) ? ''
  : `
> Requires the \`${cap}\` capability. \`forests()\` says whether your key
> carries it here; if it does not, say so instead of trying.
`

const saving = ({ caps }) => `# Saving to the forest
${needs('ingest', caps)}
When the user states something durable — a decision, a fact, a preference, a
correction — offer to keep it. \`ingest\` is the write a paired key carries by
default, and it is the whole path:

    ingest(forest, mode: "upload",
           files: [{name: "sso-decision.md", text: "..."}],
           dest: "decisions")

- **One document per fact worth finding on its own.** The Gardener converts,
  curates and commits it: title, summary, tags and aliases are written for
  you from the text you send, so the text has to state its own subject in its
  first lines.
- **\`dest\` is a branch that exists.** Either spelling of it —
  \`"decisions"\` or \`"decisions/_index"\`. \`locate(forest, ...)\` or
  \`coverage(forest)\` first; if nothing fits, ask the user rather than
  inventing a place.
- **If the material came from an address, say so.** An entry may carry
  \`source_url\`, and for an uploaded document that IS its \`origin\` —
  the field every later reader uses to go back to the source. Nothing else
  fills it: an upload that declares no \`source_url\` has no origin at all,
  because the staging path it arrived by is a fact about plumbing.

      files: [{name: "pricing-page.md", text: "...",
               source_url: "https://example.com/pricing"}]
- **A file that is not text goes as bytes.** The entry carries \`b64\`
  (the raw file, base64) instead of \`text\` — this is the one path bytes
  take into a forest:

      files: [{name: "print-template.jpg", b64: "<base64 of the file>"}]

  An image (png, jpg, gif, webp) or audio file (mp3, wav, m4a, ogg, flac)
  becomes a \`type: media\` node: the Gardener keeps the bytes in the forest
  and writes the description, and \`view(forest, id)\` later shows the image
  itself. Spreadsheets, csv, json and sqlite become datasets; docx becomes a
  document where that converter is installed; anything else comes back in
  the job report as \`unsupported\` and is not planted. \`plant\` carries no
  bytes — a media node planted without a payload is refused — and
  \`origin\` is a pointer for people that the forest never follows.
- **The name is part of the document.** A file called \`note.md\` gives the
  curator nothing to work with; \`2026-08-sso-decision.md\` gives it a date and
  a subject.
- A batch runs as a job and this call waits for it by default. Pass
  \`wait: false\` when you would rather not hold the turn, and read the job
  later.

Say what you saved and where, with the id the reply gives you. A save the
user cannot find again is not a save.
`

const writing = ({ caps }) => `# Writing nodes directly
${needs('write', caps)}
\`ingest\` hands a document to the Gardener and lets it decide the passport.
\`plant\` writes the passport yourself — use it when the shape matters: an id
you chose, links to existing nodes, a summary you wrote.

## The anatomy of a node

- **Required:** \`id\` (a path under its parent — the id IS the address and it
  is FOREVER), \`type\`, \`title\`, \`summary\`, \`parent\`.
- **The id determines the parent.** \`notes/my-report\` must have
  \`parent: "notes/_index"\`, and every intermediate level must already exist
  as a branch — the refusal names the parent it expected.
- **Types and rels are per forest.** They are declared in \`_meta/schema\`,
  and an undeclared one is refused. In an unfamiliar forest,
  \`pick(forest, "_meta/schema")\` once before your first write — one cheap
  call, and it is the dialect you must write in.
- **The summary has a ceiling: 60 tokens** (1–3 sentences). It is how every
  search finds the node — \`locate\` sees nothing else — so state WHAT it is,
  the key facts, and what is NOT here.
- **\`aliases\` is the findability lever.** \`locate\` never reads bodies, so
  give the node the names people will actually type: the ticket code, the
  short name, the number ("BE-291", "R4"). One line of aliases does more for
  recall than any body edit.
- **\`links\` place it in the graph:** \`[{rel, target}]\`, rels from
  \`_meta/schema\`.
- **\`origin\` says where it came from:** one URI, when the document exists
  outside the forest too.
- **Rehearse the expensive ones:** \`plant(forest, node, dry_run: true)\` runs
  every validation — parent chain, types, the summary ceiling — writes
  nothing, and names every problem it found, not just the first.

## The rest of the write surface

- \`plant(forest, [n1, n2, …])\` — up to 20 nodes in ONE call: all validated
  before any is written, and they land in one commit or none of them do. A
  set of documents that link to each other never exists half-built.
- \`plant(forest, node, if_absent: true)\` — if a plant failed and you cannot
  tell whether it landed, repeat it this way: an id already taken answers
  \`created: false\` and writes nothing.
- \`graft(forest, id, patch)\` — extend a node you can name. A graft that
  changes a body without its summary answers \`summary_stale: true\` — rewrite
  the summary in the same turn (\`set_frontmatter: {summary}\`), or the note
  keeps being found by what it used to say.
- \`prune(forest, id)\` — remove a node you created wrongly: a test artifact,
  a duplicate. If other nodes point at it the refusal lists them;
  \`force: true\` removes it and strips those backlinks in one commit. History
  keeps everything. Clean up after yourself: a probe node left behind is
  somebody else's search result.
- \`transplant(forest, id, new_id)\` — the node is in the wrong branch, or its
  id says the wrong thing. Do NOT rebuild it: transplant moves the document,
  every link pointing at it and its payload in one commit, and leaves the old
  id as a **waymark** — \`locate\` still finds it by the old name, and a read
  of the old id is told where it went. Branches do not move: transplant their
  leaves.
- \`history(forest, id)\` — what happened to a node and who did it, newest
  first, with the full timestamp and the acting principal. Read it before you
  edit somebody else's document.

**Replacing a document rather than continuing it?** Say which you mean:
\`succeeds\` orders two moments (round 4 came after round 3 — both remain true
of their moment), \`supersedes\` retires one (this policy replaces that one).
A node something supersedes is left OUT of retrieval by default and named in
\`superseded_excluded\`, so an outdated document stops answering for the
current one — while \`history\` and the graph still show it.

Write in English, keep the summary honest, and never invent structure the
forest does not have.
`

const time = () => `# Asking about a period

When the question is about a period — "last week", "since the contract",
"what changed in June" — do not sweep the forest hoping something recent
floats up.

1. \`calendar(forest)\` — how many nodes each period holds, most recent
   first, empty periods omitted. Add \`granularity: "week"\` for weeks.
2. Read the bucket you want and pass its exact \`since\` and \`until\`
   straight into \`locate\`, \`sniff\`, \`scan\` or \`harvest\`.

A window is decided from curated metadata before any body is opened, so on a
large forest it is the cheapest filter available. Bounds are \`YYYY\`,
\`YYYY-MM\` or \`YYYY-MM-DD\`; a bound the server cannot read is refused
rather than ignored, because a filter silently dropped is a lie about what
was searched.

\`date_field\` chooses which date: \`created\` (default) or \`updated\`.
Undated nodes are in no window at all, and the reply counts them
(\`undated_excluded\`) instead of hiding them.

If the window turns out to hold nothing, the reply says so explicitly
(\`matched_window: 0\`) and names the nearest populated periods — read that
before concluding anything: "nothing that week" is not "nothing anywhere".

**Never invent a window the user did not ask for.** A search bounded to a
period they did not name is a search that quietly lost the rest of the
forest.
`

const datasets = ({ caps }) => `# Datasets
${needs('query', caps)}
A \`type: dataset\` node is a real SQLite database behind a markdown passport.
You read it with SQL, and you read the passport first.

1. \`look(forest, id)\` — the digest carries \`notes\`: what the operator
   wrote about what the columns MEAN (which one is USD, what a status code
   stands for, which join answers the real question). The sample map in the
   body (\`## Query manual\`, \`## Sample rows\`) names every column and shows
   three rows per table. Read both before writing SQL; guessing a schema you
   could have read is how a confident wrong number gets produced.
2. \`query(forest, id, sql)\` — read-only SQL. One statement, no writes, no
   \`PRAGMA\`, no \`ATTACH\`. A \`LIMIT 200\` is injected if you leave one out.
3. The result is token-budgeted like everything else. Whole rows drop from
   the tail and \`truncated: true\` says so — **the missing rows exist**;
   \`limited\` separately means the row cap was reached. \`columns\` is never
   dropped, so you always know the shape of what you asked for. Aggregate in
   SQL rather than pulling rows and counting them yourself.
4. Two different refusals: \`E_QUERY_INVALID\` is SQLite saying your statement
   is wrong (fix it), \`E_QUERY_FORBIDDEN\` is the grant saying you may not
   read that (do not rephrase it — say what was refused).
5. \`payload_missing: true\` in the digest means the database file behind
   this passport is gone. The passport still reads; no query will run. Say
   that to the user — it is a fact about the forest, not about your SQL.

\`tend(forest, id, sql)\` is the only write path into a dataset, and it needs
the \`tend\` capability of its own: ONE \`INSERT\`, \`UPDATE\` or
\`DELETE\`, \`WHERE\` mandatory on update and delete, never DDL. New tables
and columns are not an agent's to create.
`

const sharing = ({ origin }) => `# Handing a document to a person

Two REST routes exist for the moment your work has to leave the forest. Both
take the same key you already hold, as a bearer token.

- \`GET ${origin}/v1/forests/<forest>/export/<node id>\` — the document as
  markdown, byte-identical to what was planted. \`?recursive=true\` on a
  branch downloads the whole subtree as a zip.
- \`POST ${origin}/v1/forests/<forest>/share\` with \`{"node": "<id>"}\` —
  mints an expiring link (\`/s/<token>\`) that a person can open with no
  account. The URL comes back once, in that reply; it expires on its own
  (7 days by default), and it stops working if your own access to the node
  lapses.

Offer the share link when the user asks to "send" a document to somebody, and
the export when they want the file itself. Do not paste a whole document into
the conversation when a link would do.
`

const BODIES = { saving, writing, time, datasets, sharing }

/* ------------------------------------------------------------ assembly */

/** The folder: `SKILL.md`, plus one file per selected block. */
export function buildSkill(ctx, selected) {
  const blocks = BLOCKS.filter((b) => selected.includes(b.id))
  return [{ path: 'SKILL.md', text: core({ ...ctx, blocks }) },
          ...blocks.map((b) => ({ path: b.file, text: BODIES[b.id](ctx) }))]
}

/** The same selection as ONE file, for a runtime that takes no folder.
 *  The parts are the same parts (J.5.12 v0.60): what changes is that the
 *  reference table points at sections below instead of files beside, and
 *  each block's heading drops one level. Never a different edition. */
export function inlineSkill(ctx, selected) {
  const blocks = BLOCKS.filter((b) => selected.includes(b.id))
  const parts = blocks.map((b) => BODIES[b.id](ctx).replace(/^# /, '## '))
  return [{ path: 'SKILL.md',
            text: [core({ ...ctx, blocks, inline: true }), ...parts].join('\n') }]
}

/** One paste that writes the whole folder. The console has no server to
 *  zip it and gains no endpoint for one (J.5.12); the heredocs are quoted,
 *  so nothing in a skill's text is expanded by the shell on the way in. */
export function installScript(files, dir = '~/.claude/skills/monkeyllm-memory') {
  // The caller passes the derived folder (J.5.12 v0.61); the default is
  // what a skill with no forest selected would be called.
  const nested = files.some((f) => f.path.includes('/'))
  return [`mkdir -p ${dir}${nested ? '/references' : ''}`,
          ...files.map((f) => `cat > ${dir}/${f.path} <<'MONKEYLLM_SKILL'\n`
                            + `${f.text}MONKEYLLM_SKILL`)].join('\n\n')
}

/** What a firing costs, near enough to choose by — the whole point of the
 *  split is that this number is visible while the blocks are picked. */
export const tokens = (text) => Math.round(text.length / 3.7)
