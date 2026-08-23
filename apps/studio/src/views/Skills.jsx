// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Skills (J.5.12): hand a person the instruction file that turns their own
 * AI into a reader and feeder of this forest.
 *
 * Self-service by contract: `read`-gated, never admin — pairing (J.2.6)
 * made the credential self-service and the Clipper (J.15) made
 * distribution self-service, so learning to connect must be too. The skill
 * is generated HERE, client-side, with this Station's origin and the chosen
 * forests baked in (Integrations' rule: documentation that cannot drift
 * from the deployment it documents). The Station gains no endpoint for it,
 * and the skill teaches only the published MCP surface under the person's
 * own paired key — no third write path.
 *
 * v0.60: the skill is a folder, not a file. The text lives in `skill.js`,
 * in blocks; this console chooses which of them ship. Two things are
 * chosen here and both are the same idea — a skill should be the size of
 * the agent it is for:
 *
 *   - the BLOCKS, defaulting to the capabilities of the key on the chosen
 *     forests, because ~1,400 tokens of `plant` anatomy is dead weight in
 *     an agent whose paired key carries `{read, ingest}`;
 *   - the FORESTS, defaulting to the open one, because an agent configured
 *     for two forests should be handed one skill. More than one bakes a
 *     routing table read from `coverage` (C.17) — inside a single forest
 *     that call is live and a written-down copy could only drift.
 *
 * A baked forest id is intent, never authority: the file teaches
 * `forests()` as the first call, and says that a forest missing from its
 * reply is a narrowed key rather than a defect.
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { hrefFor, useRouteState } from '../router.js'
import { useI18n } from '../i18n.jsx'
import { Card, CheckList, CopyButton, Note, Segmented } from '../design/ui.jsx'
import { Highlighted } from '../design/highlight.jsx'
import { Download, Files, Key, Plug, Sparkle } from '../design/icons.jsx'
import { NeedsCapability, has } from './shared.jsx'
import { BLOCKS, PRESETS, buildSkill, defaultBlocks, inlineSkill, installScript,
         presetFor, skillName, tokens } from '../skill.js'
import { zip } from '../zip.js'

/** The folder's name on disk, and therefore inside the archive: extracting
 *  gives a directory a person can drop straight into ~/.claude/skills/.
 *  Derived from the selected forests (J.5.12 v0.61) — a constant here made
 *  one-skill-per-forest, which this console invites, collide on `name:`. */

const P = ({ children }) => (
  <p className="max-w-[72ch] text-[13px] leading-relaxed text-text-2">{children}</p>
)

function CodeBlock({ title, code, lang = 'bash', actions }) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface-2">
      <div className="flex items-center justify-between gap-3 border-b border-line
                      py-1 pl-3 pr-1.5">
        <span className="truncate font-mono text-[11px] text-text-3">{title}</span>
        <span className="flex shrink-0 items-center gap-1.5">
          {actions}
          <CopyButton value={code} />
        </span>
      </div>
      <pre className="max-h-[26rem] overflow-auto p-3 font-mono text-[12px] leading-relaxed
                      text-text-2">
        <Highlighted text={code} lang={lang} />
      </pre>
    </div>
  )
}

/** The browser saves what the console generated — no server round trip,
 *  exactly like the copy button beside it (J.5.12). */
function save(name, blob) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

const saveFile = (name, text) =>
  save(name, new Blob([text], { type: 'text/markdown' }))

/** The whole folder, as a folder. The install paste is the shortest route on
 *  a machine with a shell; this is the route for every other machine, and it
 *  arrives already arranged — `<name>/SKILL.md` beside
 *  `<name>/references/*.md`, nothing for the reader to place. */
const saveFolder = (files, folder) =>
  save(`${folder}.zip`, zip(files.map((f) => ({ ...f, path: `${folder}/${f.path}` }))))

export default function Skills({ forest, grant, me }) {
  const { t } = useI18n()
  // J.5.12 (v0.56): the skill states its age. The version comes off the
  // Station's own health probe — the same string forests() serves — so the
  // stamped file cannot drift from the deployment it documents.
  const [station, setStation] = useState('')
  const [roots, setRoots] = useState({})
  const asked = useRef(new Set())

  useEffect(() => {
    api.health().then((h) => setStation(h.version || '')).catch(() => {})
  }, [])

  const grants = me?.grants || []
  const known = grants.map((g) => g.forest)
  const capsOf = (id) => grants.find((g) => g.forest === id)?.caps || []

  // J.5.8: the selection lives in the address, not in a second copy of it.
  // Here that is load-bearing beyond the rule — the address IS how this
  // skill is regenerated later, so the file can name the link that rebuilds
  // exactly itself against a newer Station (J.5.12, v0.60).
  const [rawForests, setForests] = useRouteState('forests', forest)
  const picked = rawForests === 'none' ? []
    : rawForests.split(',').filter((id) => known.includes(id))
  const caps = [...new Set(picked.flatMap(capsOf))]

  // Absent means "whatever this key can do" — so the default follows the
  // forests as they change, and only a deliberate choice is written down.
  // `none` is how zero blocks says itself; an empty value is an absent one.
  const fallback = defaultBlocks(caps).join(',')
  const [rawBlocks, setBlocks] = useRouteState('blocks', fallback)
  const blocks = rawBlocks === 'none' ? []
    : rawBlocks.split(',').filter((id) => BLOCKS.some((b) => b.id === id))

  const [assembly, setAssembly] = useRouteState('assembly', 'folder',
                                                { allow: ['folder', 'single'] })
  const setPicked = (ids) => setForests(ids.length ? ids.join(',') : 'none')
  const setChosen = (ids) => setBlocks(ids.length ? ids.join(',') : 'none')
  const multi = picked.length > 1
  const preset = presetFor(blocks)

  // C.17 read once per forest, and only for the table that needs it: a
  // single-forest skill teaches `coverage()` instead of baking its answer.
  useEffect(() => {
    if (!multi) return
    for (const id of picked) {
      if (asked.current.has(id)) continue
      asked.current.add(id)
      api.call(id, 'coverage', {})
        .then((r) => setRoots((s) => ({ ...s, [id]: r.roots || [] })))
        .catch(() => setRoots((s) => ({ ...s, [id]: [] })))
    }
  }, [multi, picked.join(',')])

  if (!has(grant, 'read')) {
    return <NeedsCapability message={t('skills.locked')} hint={t('cap.read')} />
  }

  const origin = window.location.origin
  const ctx = {
    origin, station: station || 'unknown', caps,
    forests: picked.map((id) => ({ id, caps: capsOf(id), roots: roots[id] || [] })),
    // The address that rebuilds this exact skill. It spends nothing and
    // commits nothing to visit (J.5.8), so the file can hand it to an agent
    // that has just discovered its own staleness.
    reinstall: origin + hrefFor(forest, 'skills', {
      forests: picked.join(','),
      blocks: blocks.length ? blocks.join(',') : 'none',
      assembly: assembly === 'folder' ? '' : assembly,
    }),
  }
  const files = picked.length
    ? (assembly === 'folder' ? buildSkill(ctx, blocks) : inlineSkill(ctx, blocks))
    : []
  const core = files[0]
  // The one name: the frontmatter's, the folder's, the archive's.
  const folder = skillName(ctx.forests)
  const extra = files.slice(1)
  const extraTokens = extra.reduce((n, f) => n + tokens(f.text), 0)

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

      <Card title={t('skills.shape.title')} subtitle={t('skills.shape.sub')}
            icon={Files} bodyClass="space-y-4 p-5">
        <P>{t('skills.shape.p1')}</P>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[12px] text-text-3">{t('skills.shape.preset')}</span>
          {PRESETS.map((p) => (
            <button key={p.id} type="button"
                    className={`btn btn-sm ${preset === p.id ? 'btn-primary' : ''}`}
                    onClick={() => setChosen(p.blocks)}>
              {t(`skills.preset.${p.id}`)}
            </button>
          ))}
          {!preset && (
            <span className="text-[12px] text-text-3">{t('skills.preset.custom')}</span>
          )}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <CheckList label={t('skills.shape.forests')} value={picked}
                     onChange={setPicked} allLabel={t('skills.shape.all_forests')}
                     empty={t('skills.shape.no_forests')}
                     hint={multi ? t('skills.shape.multi_hint')
                                 : t('skills.shape.one_hint')}
                     options={grants.map((g) => ({
                       value: g.forest,
                       meta: g.caps.join(', '),
                     }))} />
          <CheckList label={t('skills.shape.blocks')} value={blocks}
                     onChange={setChosen} allLabel={t('skills.shape.all_blocks')}
                     empty={t('skills.shape.no_blocks')}
                     hint={t('skills.shape.blocks_hint')}
                     options={BLOCKS.map((b) => ({
                       value: b.id, label: b.title,
                       meta: caps.includes(b.cap) ? b.file
                                                  : `${b.file} · ${t('skills.shape.needs')} ${b.cap}`,
                     }))} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Segmented value={assembly} onChange={setAssembly} options={[
            { value: 'folder', label: t('skills.shape.folder') },
            { value: 'single', label: t('skills.shape.single') },
          ]} />
          {core && (
            <p className="text-[12px] text-text-3">
              <span className="tabular-nums text-text-2">
                {tokens(core.text).toLocaleString()}
              </span>{' '}
              {assembly === 'folder' ? t('skills.shape.core_cost')
                                     : t('skills.shape.single_cost')}
              {assembly === 'folder' && extra.length > 0 && (
                <> · <span className="tabular-nums text-text-2">
                  {extraTokens.toLocaleString()}
                </span> {t('skills.shape.refs_cost', { n: extra.length })}</>
              )}
            </p>
          )}
        </div>
        <Note>{assembly === 'folder' ? t('skills.shape.folder_note')
                                     : t('skills.shape.single_note')}</Note>
      </Card>

      <Card title={t('skills.install.title')} subtitle={t('skills.install.sub')}
            icon={Download} bodyClass="space-y-4 p-5">
        <P>{t('skills.install.p1')}</P>
        {!core ? (
          <Note tone="warn">{t('skills.shape.no_forests')}</Note>
        ) : (
          <>
            <CodeBlock title={t('skills.install.script')}
                       code={installScript(files, `~/.claude/skills/${folder}`)} />
            {files.length > 1 && (
              <div className="flex flex-wrap items-center gap-2">
                <button className="btn btn-primary"
                        onClick={() => saveFolder(files, folder)}>
                  <Download size={15} /> {t('skills.install.zip')}
                </button>
                <span className="text-[12px] text-text-3">{t('skills.install.zip_hint')}</span>
              </div>
            )}
            <P>{t('skills.install.or_files')}</P>
            {files.map((f) => (
              <CodeBlock key={f.path} lang="markdown"
                         title={`~/.claude/skills/${folder}/${f.path}`}
                         code={f.text}
                         actions={
                           <button className="btn btn-sm"
                                   title={t('skills.install.download')}
                                   onClick={() => saveFile(f.path.split('/').pop(), f.text)}>
                             <Download size={14} />
                           </button>
                         } />
            ))}
            <Note>{t('skills.install.english')}</Note>
          </>
        )}
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
