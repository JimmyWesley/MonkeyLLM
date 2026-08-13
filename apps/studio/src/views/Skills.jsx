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
import { useI18n } from '../i18n.jsx'
import { Card, CopyButton, Note } from '../design/ui.jsx'
import { Highlighted } from '../design/highlight.jsx'
import { Download, Key, Plug, Sparkle } from '../design/icons.jsx'
import { NeedsCapability, has } from './shared.jsx'

/** One file, addressed to the model that will load it. English on purpose;
 *  origin and forest are the only moving parts. */
const skillFile = (origin, forest) => `---
name: monkeyllm-memory
description: >-
  Use the MonkeyLLM forest "${forest}" at ${origin} as persistent memory.
  Recall from it before answering anything in its domain, save durable new
  knowledge into it, and cite the node ids you read.
---

# This forest is your memory

The MCP server \`monkeyllm\` serves the knowledge forest \`${forest}\` at
${origin}. Treat it as persistent memory for its domain: it outlives this
conversation, other people and agents feed it too, and everything you read
carries a node id you can cite.

## Recall before you answer

For any question the forest could answer (its projects, people, decisions,
documents, data), recall first and reason after:

- \`answer\` — the one-shot: retrieval plus a grounded reply with sources.
  Prefer it when the forest's answer is the answer.
- \`harvest\` — retrieval without a model call: top items and matched
  passages. Prefer it when you will reason over the material yourself.
- \`locate\` → \`look\` → \`pick\` — navigate: find nodes by their curated
  scent, read a node's passport, open one section of its body.
- \`sniff\` — literal text search inside bodies (grep, not regex).
- \`query\` — read-only SQL over \`type: dataset\` nodes, if your key
  carries the \`query\` capability. \`look\` at the dataset first: its
  \`notes\` say what the columns mean.

Cite node ids for anything you assert from the forest. If the forest and
the user disagree, say so: the forest owns its documents, the user owns
the present.

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

Write in English, keep the summary honest (it is how the note will be
found), and never invent structure the forest does not have.

## Respect the contract

- Your key decides what you see and what you may write; what it cannot
  reach does not exist. Never work around a refusal — say what was
  refused and which capability it needs.
- Every read is budgeted. \`truncated: true\` means ask narrower, not
  retry harder.
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

  if (!has(grant, 'read')) {
    return <NeedsCapability message={t('skills.locked')} hint={t('cap.read')} />
  }

  const origin = window.location.origin
  const skill = skillFile(origin, forest)

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
