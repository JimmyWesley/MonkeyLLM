// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Skills (J.5.12): hand a person the instruction file that turns their own
 * AI into a reader and feeder of this forest.
 *
 * Self-service by contract: `read`-gated, never admin — pairing (J.2.6)
 * made the credential self-service and the Clipper (J.15) made
 * distribution self-service, so learning to connect must be too. The skill
 * is generated HERE, client-side, with this Station's origin and the open
 * forest baked in (Integrations' rule: documentation that cannot drift
 * from the deployment it documents). The Station gains no endpoint for it,
 * and the skill teaches only the published MCP surface under the person's
 * own paired key — no third write path.
 *
 * The file's body is English regardless of the console language: it
 * addresses a model, not the reader (J.5.3's content-not-chrome, applied
 * outward). The walkthrough around it is translated like any other chrome.
 */
import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { Card, CopyButton, Note } from '../design/ui.jsx'
import { Highlighted } from '../design/highlight.jsx'
import { Download, Key, Plug, Sparkle } from '../design/icons.jsx'
import { NeedsCapability, has } from './shared.jsx'

/** One file, addressed to the model that will load it. English on purpose;
 *  origin, forest and the Station version are the only moving parts. */
const skillFile = (origin, forest, station) => `---
name: monkeyllm-memory
description: >-
  Use the MonkeyLLM forest "${forest}" at ${origin} as persistent memory.
  Recall from it before answering anything in its domain, save durable new
  knowledge into it, and cite the node ids you read.
station: "${station}"
---

# This forest is your memory

The MCP server \`monkeyllm\` serves the knowledge forest \`${forest}\` at
${origin}. Treat it as persistent memory for its domain: it outlives this
conversation, other people and agents feed it too, and everything you read
carries a node id you can cite.

**This skill was generated against Station ${station}, and the server tells
you when it has aged:** the \`forests()\` reply — your first call — carries
\`station\`, the server's current version. When it is newer than the
\`station\` in this file's frontmatter, tell your operator to re-download
this skill from the Studio's Skills console before relying on it: a stale
skill is a stale map of the surface, and tools it does not name still
exist.

A **node** is one markdown document with a curated passport (title, summary,
tags) and a body. A **branch** is a node that holds others; its id ends in
\`/_index\`; \`kind\` on the wire is \`branch\` or \`note\`. Everything else
is a leaf note.

## Recall before you answer

For any question the forest could answer (its projects, people, decisions,
documents, data), recall first and reason after:

- \`answer(question)\` — the one-shot: retrieval plus a grounded reply with
  sources. Prefer it when the forest's answer is the answer. Pass
  \`min_evidence: 2\` when you would rather see the evidence than a confident
  paragraph over one weak snippet — below the floor it replies
  \`answer: null\` and hands you the retrieval instead.
- \`harvest(query)\` — retrieval without a model call: top items and matched
  passages. Prefer it when you will reason over the material yourself.
- \`locate(query)\` → \`look(id)\` → \`pick(id)\` — navigate: rank entry points,
  read a node's passport, open its body. \`pick\` reads one section
  (\`section: "Header"\`), several at once (\`section: ["A", "B"]\`), and a
  body over its 4000-token budget arrives in PAGES: pass the response's
  \`next\` back as \`after\` until none comes, and the concatenated pages are
  the body, byte for byte. \`look\` also says who and when: \`source\`,
  \`created\`, \`updated\`, the node's \`aliases\` when it has any, and its
  \`origin\` (where the document came from) when one was recorded.
- \`sniff(terms)\` — literal text search inside bodies (substring, not regex).
- \`scan(parent_id)\`, \`move(id)\` — list a branch's nodes by metadata; follow
  a node's typed edges. \`scan("_index", recursive: true)\` is the cheapest
  map of the whole forest when you need to see its shape first. Every scan
  says \`total\` and \`returned\`; to walk everything, start it with
  \`after: ""\` and keep passing the response's \`next\` back as \`after\` —
  id order, complete, no duplicates. \`filter\` matches any passport field:
  \`filter: {"source": "agent"}\` lists what agents wrote,
  \`filter: {"kind": "note"}\` leaves the branches out.
- \`calendar()\` — where the material sits in time: how many nodes each
  period holds, most recent first.
- \`view(id)\` — the image behind a \`type: media\` node, if you can see images.
- \`query(id, sql)\` — read-only SQL over \`type: dataset\` nodes, if your key
  carries the \`query\` capability. \`look\` at the dataset first: its
  \`notes\` say what the columns mean.

**\`locate\` and \`sniff\` search different things, and that is the one thing
worth remembering about this surface.** \`locate\` reads curated metadata —
titles, summaries, tags — and never bodies. So an exact term nobody lifted
into a summary (an error code, an invoice number, a library name) returns
\`{"results": []}\` from \`locate\` and is found instantly by \`sniff\`. When a
\`locate\` comes back empty it tells you how many nodes it searched and points
you at \`sniff\`: an empty result is never evidence that the forest does not
know. Do not answer from your own knowledge until \`sniff\` has come back
empty too.

**When the question is about a period** — "last week", "since the contract",
"what changed in June" — do not sweep the forest hoping something recent
floats up. Call \`calendar()\` (add \`granularity: "week"\` for weeks), read
the period you want, and pass that bucket's \`since\` and \`until\` straight
into \`locate\`, \`sniff\`, \`scan\` or \`harvest\`. A window is decided from
curated metadata before any body is opened, so on a large forest it is the
cheapest filter available — and if the window turns out to hold nothing, the
answer says so explicitly (\`matched_window: 0\`) instead of looking like an
empty forest. Bounds are \`YYYY\`, \`YYYY-MM\` or \`YYYY-MM-DD\`, inclusive.
Never invent a window the user did not ask for: a search bounded to a period
they did not name is a search that quietly lost the rest of the forest.

Two things that save round trips, both worth using by default:

- \`look\` takes up to 10 ids at once and \`pick\` up to 5 — one call, one
  budget, every id you sent accounted for in \`nodes\`, \`missing\` or
  \`dropped\`.
- \`locate(query, include: ["outline"])\` returns each result's section
  headers, which is exactly what \`pick(id, section)\` takes — so you can go
  from search to passage without the \`look\` in between. Every result also
  carries \`body_tokens\`, so you know the size of what you are about to open.
- \`fields\` is the cost lever on \`look\` AND the page lever on \`scan\`:
  \`look(id, fields: ["summary"])\` costs a fraction of the full digest, and
  a \`scan\` page holds more items the fewer fields each carries —
  \`fields: ["id"]\` enumerates a large forest in a fraction of the calls.
  When a \`look\` digest is over budget it clips fields in a declared order
  and NAMES them in \`truncated_fields\`; an \`edges_out: []\` without that
  flag really is an isolated node, and \`stats.degree\` is the arithmetic
  truth either way.

Cite node ids for anything you assert from the forest — and cite them the
way a person can read: the title first, the id in brackets, as in
\`Pheromone (projects/monkeyllm/pheromone)\`. Every result you get already
carries both, so this costs nothing; an id alone means nothing to whoever
reads your answer. If the forest and the user disagree, say so: the forest
owns its documents, the user owns the present.

## Save what is worth keeping

When the user states something durable — a decision, a fact, a preference,
a correction — offer to keep it. \`forests\` lists what your key carries;
use the write it actually allows:

- \`ingest\` (a paired key carries this by default): send one markdown
  document — a clear file name, the fact in the body, the destination
  branch as \`dest\` — and the Gardener gives it its passport.
- \`plant\` / \`graft\` (only if your key carries \`write\`): plant a new
  note under the branch where it belongs (\`locate\` the branch first; if
  nothing fits, ask the user), or graft to extend a node you can name.
  If a \`plant\` fails and you cannot tell whether it landed, repeat it with
  \`if_absent: true\`: an id already taken answers \`created: false\` and
  writes nothing. A \`graft\` that changes a body without its summary
  answers \`summary_stale: true\` — rewrite the summary in the same turn
  (\`set_frontmatter: {summary}\`), or the note keeps being found by what
  it used to say.
- \`prune(id)\` (also \`write\`): remove a node you created wrongly — a test
  artifact, a duplicate, a note planted in the wrong place. If other nodes
  point at it the refusal lists them; \`force: true\` removes it and strips
  those backlinks in one commit. History keeps everything, so this undoes
  a mistake without hiding that it happened. Clean up after yourself: a
  probe node left behind is somebody else's search result.
- \`transplant(id, new_id)\` (also \`write\`): the node is in the wrong
  branch, or its id says the wrong thing. Do NOT rebuild it — transplant
  moves the document, every link pointing at it, and its payload in one
  commit, and leaves the old id as a **waymark**: \`locate\` still finds
  the node by the old name, and anyone reading the old id is told where
  it went. Branches do not move: transplant their leaves.
- \`history(id)\`: what happened to a node and who did it — every commit,
  newest first, with the full timestamp and the acting principal. Read it
  before you edit somebody else's document, and when you need to say
  "this changed on the 14th" instead of guessing from \`updated\`.

**Planting several related nodes? Send them as a list.** \`plant\` takes
up to 20 nodes in one call: all of them are validated before any is
written, and they land in one commit or none of them do. A set of
documents that link to each other never exists half-built, and one call
costs the forest one commit instead of twenty.

**Replacing a document rather than continuing it?** Say which you mean:
\`succeeds\` orders two moments (round 4 came after round 3 — both remain
true of their moment), \`supersedes\` retires one (this policy replaces
that one). A node something supersedes is left OUT of retrieval by
default and named in \`superseded_excluded\`, so an outdated document
stops answering for the current one — while \`history\` and the graph
still show it.

### The anatomy of a node (read this before your first \`plant\`)

The \`node\` you hand to \`plant\` is the most important input this surface
takes, so here is its whole shape:

- **Required:** \`id\` (a path under its parent — the id IS the address and
  it is FOREVER: there is no rename, so choose it as carefully as a URL),
  \`type\`, \`title\`, \`summary\`, \`parent\`.
- **The id determines the parent.** \`notes/my-report\` must have
  \`parent: "notes/_index"\`, and every intermediate level must already
  exist as a branch — the refusal names the parent it expected.
- **Types and rels are per forest.** They are declared in
  \`_meta/schema\`, and an undeclared one is refused. In an unfamiliar
  forest, \`pick("_meta/schema")\` once before your first write — it is one
  cheap call and it is the dialect you must write in.
- **The summary has a ceiling: 60 tokens** (1–3 sentences). It is how
  every search finds the node — \`locate\` sees nothing else — so state
  WHAT it is, the key facts, and what is NOT here.
- **\`aliases\` is the findability lever.** \`locate\` never reads bodies,
  so give the node the names people will actually type: the ticket code,
  the short name, the number ("BE-291", "R4"). One line of aliases does
  more for recall than any body edit.
- **\`links\` place it in the graph:** \`[{rel, target}]\`, rels from
  \`_meta/schema\`. When a document follows an earlier one, say so with
  \`succeeds\` — retrieval reads that order, and an \`answer\` will treat
  the older node as history instead of mixing two moments into one
  present. When it REPLACES the earlier one, say \`supersedes\` instead:
  the predecessor stops being offered as evidence.
- **\`origin\` says where it came from:** one URI (a path, a URL, a commit
  ref) when the document exists outside the forest too — it is how the
  copy can ever be reconciled with its source.
- **Rehearse the expensive ones:** \`plant(node, dry_run: true)\` runs
  every validation — parent chain, types, the summary ceiling — and
  writes nothing. One cheap call instead of shipping a 30 KB body to
  learn your summary is 61 tokens.

Write in English, keep the summary honest (it is how the note will be
found, and \`locate\` sees nothing else), and never invent structure the
forest does not have.

### Handing a document to a person

Two REST surfaces exist for the moment your work must leave the forest —
both under the same origin and key discipline as everything else:

- \`GET ${origin}/v1/forests/${forest}/export/<node id>\` downloads the
  document as markdown, byte-identical to what was planted;
  \`?recursive=true\` on a branch downloads the subtree as a zip.
- \`POST ${origin}/v1/forests/${forest}/share\` with \`{"node": "<id>"}\`
  mints an expiring share link (\`/s/<token>\`) a person can open with no
  account — the URL comes back once, in that reply. Offer this when the
  user asks to "send" a document to somebody.

## Respect the contract

- Your key decides what you see and what you may write; what it cannot
  reach does not exist. Never work around a refusal — say what was
  refused and which capability it needs.
- Every read is budgeted. \`truncated: true\` means ask narrower, not
  retry harder.
- Every refusal is \`{error: {code, message, hint}}\` and the hint is
  actionable: \`E_SCHEMA\` means fix the argument it names, \`E_NOT_FOUND\`
  means the node is absent or outside your key, \`E_INTERNAL\` means the
  server failed and repeating the call will not help.
- Datasets change through \`tend\` only if your key carries it: one
  statement at a time, never DDL.
`

const P = ({ children }) => (
  <p className="max-w-[72ch] text-[13px] leading-relaxed text-text-2">{children}</p>
)

function CodeBlock({ title, code, lang = 'bash' }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface-2">
      <div className="flex items-center justify-between gap-3 border-b border-line
                      py-1 pl-3 pr-1.5">
        <span className="truncate font-mono text-[11px] text-text-3">{title}</span>
        <CopyButton value={code} />
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-[12px] leading-relaxed
                      text-text-2">
        <Highlighted text={code} lang={lang} />
      </pre>
    </div>
  )
}

/** The browser saves what the console generated — no server round trip,
 *  exactly like the copy button beside it (J.5.12). */
function saveFile(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export default function Skills({ forest, grant }) {
  const { t } = useI18n()
  // J.5.12 (v0.56): the skill states its age. The version comes off the
  // Station's own health probe — the same string forests() serves — so the
  // stamped file cannot drift from the deployment it documents.
  const [station, setStation] = useState('')
  useEffect(() => {
    api.health().then((h) => setStation(h.version || '')).catch(() => {})
  }, [])

  if (!has(grant, 'read')) {
    return <NeedsCapability message={t('skills.locked')} hint={t('cap.read')} />
  }

  const origin = window.location.origin
  const skill = skillFile(origin, forest, station || 'unknown')

  return (
    <div className="max-w-[860px] space-y-5">
      <Card title={t('skills.what.title')} subtitle={t('skills.what.sub')}
            icon={Sparkle} bodyClass="space-y-4 p-5">
        <P>{t('skills.what.p1')}</P>
        <P>{t('skills.what.p2')}</P>
      </Card>

      <Card title={t('skills.pair.title')} subtitle={t('skills.pair.sub')}
            icon={Key} bodyClass="space-y-4 p-5">
        <P>{t('skills.pair.p1')}</P>
        <CodeBlock title={t('skills.pair.snippet')}
                   code={`curl -sX POST ${origin}/v1/auth/pair \\
  -H 'content-type: application/json' \\
  -d '{"username": "you", "password": "…", "label": "claude-code"}'`} />
        <Note>{t('skills.pair.once')}</Note>
      </Card>

      <Card title={t('skills.connect.title')} subtitle={t('skills.connect.sub')}
            icon={Plug} bodyClass="space-y-4 p-5">
        <P>{t('skills.connect.p1')}</P>
        <CodeBlock title="bash"
                   code={`claude mcp add --transport http monkeyllm ${origin}/mcp/ \\
  --header "Authorization: Bearer mk_…"`} />
      </Card>

      <Card title={t('skills.install.title')} subtitle={t('skills.install.sub')}
            icon={Download} bodyClass="space-y-4 p-5">
        <P>{t('skills.install.p1')}</P>
        <CodeBlock title="~/.claude/skills/monkeyllm-memory/SKILL.md"
                   code={skill} lang="markdown" />
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn btn-primary"
                  onClick={() => saveFile('SKILL.md', skill)}>
            <Download size={15} /> {t('skills.install.download')}
          </button>
          <span className="text-[12px] text-text-3">{t('skills.install.or_copy')}</span>
        </div>
        <Note>{t('skills.install.english')}</Note>
      </Card>

      <Card title={t('skills.other.title')} subtitle={t('skills.other.sub')}
            icon={Plug} bodyClass="space-y-4 p-5">
        <P>{t('skills.other.p1')}</P>
        <CodeBlock title="json" lang="json"
                   code={`{
  "mcpServers": {
    "monkeyllm": {
      "type": "http",
      "url": "${origin}/mcp/",
      "headers": { "Authorization": "Bearer mk_…" }
    }
  }
}`} />
        <P>{t('skills.other.manual')}</P>
      </Card>
    </div>
  )
}
