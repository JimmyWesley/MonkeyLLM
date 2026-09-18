// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The files mode of Explore (spec J.5.4).
 *
 * The same forest as the graph, seen the way it lives on disk: a tree of
 * markdown with payloads beside their owners. Each file opens as what it
 * *is* — prose rendered as prose, a database as a table you can query, an
 * HTML body as a page — and the stored form is always one click away.
 *
 * Three rules from J.5.4 are load-bearing here:
 *
 * - **Nothing is read outside the primitives and the J.14 byte route.** The
 *   tree comes from the map projection, a body from `pick`, a table from
 *   `query`, an image from `GET .../payload/{node}` — a governed surface any
 *   client with the same key could fetch, never the privileged side-channel
 *   J.5 forbids.
 * - **A reconstructed passport is never shown as the file's bytes.** The
 *   source view names its two halves: the passport as the Catalog holds it,
 *   and the body as stored.
 * - **A body over the `pick` budget shows the outline the primitive
 *   returned**, rather than pretending to have the whole text.
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { Markdown } from '../design/markdown.jsx'
import { Highlighted } from '../design/highlight.jsx'
import {
  Badge, Card, Empty, ErrorNote, Skeleton, Spinner,
} from '../design/ui.jsx'
import {
  Alert, Check, ChevronRight, Code2, Copy, Database, Download, Eye, File, Flame,
  Link, Pencil, Search,
} from '../design/icons.jsx'
import { Metric, useAsync } from './shared.jsx'
import { SUMMARY_TOKENS, countTokens } from './editor.jsx'

const HTML_BODY = /^\s*<(!doctype|html|div|section|article|table|h[1-6]|p|ul|ol)\b/i
const WIKILINK = /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g

/** A `[[wikilink]]` is a trail a person can follow, and printing the
 *  brackets makes them read the address instead. It becomes an ordinary
 *  link to a fragment the view intercepts — so nothing leaves the console
 *  and the sanitiser has nothing new to allow. */
const NODE_HREF = '#node:'
const linkify = (md) => String(md || '').replace(
  WIKILINK,
  (_, target, label) => `[${label || target}](${NODE_HREF}${encodeURIComponent(target.trim())})`)

/** The archive a converter keeps beside a branch (G.5.1), hidden from the
 *  tree.
 *
 *  `_assets/` holds the ORIGINAL a document was made from, under a name the
 *  Gardener composed out of a hash — `bfad6417-chatgpt--chatg.pdf`. Nobody
 *  typed it and nobody can read it, and the tree is the one surface in the
 *  console that claims to be what a person would see on disk. It is filtered
 *  out of the LISTING and nothing else: the catalog is untouched, and the
 *  node's own panel offers those bytes as `Original · download` (J.14),
 *  which is the address a reader can actually use.
 *
 *  `_assets` is per-BRANCH, so it is a directory name at any depth — never
 *  a prefix of the path. */
const ASSETS_DIR = /(?:^|\/)_assets\//
export const inAssets = (path) => ASSETS_DIR.test(String(path || ''))

/** A node id and its payload, as paths. `people/jimmy-wesley` is the file
 *  `people/jimmy-wesley.md`; a dataset's `.db` sits beside it. */
export function filesOf(nodes) {
  const out = []
  for (const n of nodes) {
    out.push({ path: `${n.id}.md`, id: n.id, kind: 'md', type: n.type })
    if (n.payload && !/^[a-z0-9+.-]+:\/\//i.test(n.payload)) {
      const dir = n.id.includes('/') ? n.id.slice(0, n.id.lastIndexOf('/') + 1) : ''
      const path = dir + n.payload
      if (inAssets(path)) continue
      out.push({
        path, id: n.id, type: n.type,
        payload_type: n.payload_type,
        kind: n.payload.toLowerCase().endsWith('.db') ? 'db' : 'payload',
      })
    }
  }
  return out.sort((a, b) => a.path.localeCompare(b.path))
}

/** Nest the flat list into folders, so the tree looks like the disk. */
function foldersOf(files) {
  const root = { dirs: new Map(), files: [] }
  for (const f of files) {
    const parts = f.path.split('/')
    let node = root
    for (const part of parts.slice(0, -1)) {
      if (!node.dirs.has(part)) node.dirs.set(part, { dirs: new Map(), files: [] })
      node = node.dirs.get(part)
    }
    node.files.push({ ...f, name: parts[parts.length - 1] })
  }
  return root
}

export default function ForestFiles({ forest, grant, data, selected, onSelect,
                                      onEdit, busy }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(null)      // the chosen path
  const [filter, setFilter] = useState('')

  const files = useMemo(() => filesOf(data?.nodes || []), [data])

  // Selecting in the graph and switching mode should land on that node's
  // file, not on whatever was open last.
  useEffect(() => {
    if (!files.length) return
    setOpen((current) => {
      if (selected) {
        const own = files.find((f) => f.id === selected && f.kind === 'md')
        if (own && (!current || files.find((f) => f.path === current)?.id !== selected)) {
          return own.path
        }
      }
      return current && files.some((f) => f.path === current)
        ? current : files[0]?.path || null
    })
  }, [files, selected])

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    return q ? files.filter((f) => f.path.toLowerCase().includes(q)) : files
  }, [files, filter])

  const current = files.find((f) => f.path === open) || null

  if (busy) return <div className="card p-4"><Skeleton rows={6} /></div>
  if (!files.length) {
    return (
      <div className="card p-4">
        <Empty icon={File} title={t('files.empty')}>{t('files.empty_hint')}</Empty>
      </div>
    )
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[248px_minmax(0,1fr)_280px]">
      {/* The rails pin to the viewport at xl, the way the nav rail does
          (Shell): the tree takes every pixel of screen it can get and
          scrolls inside itself, instead of stopping at a fixed cap with
          dead page below — and it stays in hand while a long body scrolls.
          `self-start` gives sticky its room; below xl the columns stack
          and the caps return. */}
      <Card title={t('files.tree')} icon={File}
            className="xl:sticky xl:top-6 xl:flex xl:max-h-[calc(100vh-3rem)]
                       xl:flex-col xl:self-start"
            bodyClass="p-2 xl:flex xl:min-h-0 xl:flex-1 xl:flex-col">
        <label className="relative mb-2 block">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2
                                       -translate-y-1/2 text-text-3" />
          <input className="field !py-1.5 pl-8 text-[12.5px]" value={filter}
                 placeholder={t('files.filter')}
                 onChange={(e) => setFilter(e.target.value)} />
        </label>
        <div className="max-h-[26rem] overflow-y-auto pr-1 xl:max-h-none
                        xl:min-h-0 xl:flex-1">
          {filter.trim() ? (
            <ul className="space-y-0.5">
              {shown.map((f) => (
                <li key={f.path}>
                  <FileRow file={f} depth={0} open={open}
                           onOpen={(p) => { setOpen(p); onSelect?.(f.id) }}
                           label={f.path} />
                </li>
              ))}
              {!shown.length && (
                <p className="px-2 py-3 text-[12px] text-text-3">{t('files.no_match')}</p>
              )}
            </ul>
          ) : (
            <Folder node={foldersOf(files)} depth={0} open={open}
                    onOpen={(p, id) => { setOpen(p); onSelect?.(id) }} />
          )}
        </div>
      </Card>

      <div className="min-w-0">
        {current
          ? <Viewer key={current.path} forest={forest} grant={grant}
                    file={current} onEdit={onEdit}
                    onNavigate={(id) => {
                      const own = files.find((f) => f.id === id && f.kind === 'md')
                      if (own) { setOpen(own.path); onSelect?.(id) }
                    }} />
          : <Card><Empty icon={File}>{t('files.pick')}</Empty></Card>}
      </div>

      <Inspector forest={forest} node={current?.id}
                 meta={data?.nodes?.find((n) => n.id === current?.id)}
                 onOpen={(id) => {
                   const own = files.find((f) => f.id === id && f.kind === 'md')
                   if (own) { setOpen(own.path); onSelect?.(id) }
                 }} />
    </div>
  )
}

function Folder({ node, depth, open, onOpen, name }) {
  const [collapsed, setCollapsed] = useState(depth > 1)
  const dirs = [...node.dirs.entries()].sort((a, b) => a[0].localeCompare(b[0]))

  return (
    <div>
      {name && (
        <button type="button" className="tree-row font-medium"
                style={{ paddingLeft: `${6 + depth * 11}px` }}
                aria-expanded={!collapsed}
                onClick={() => setCollapsed((v) => !v)}>
          <ChevronRight size={12}
                        className={`opacity-60 transition ${collapsed ? '' : 'rotate-90'}`} />
          <span className="truncate">{name}</span>
        </button>
      )}
      {!collapsed && (
        <>
          {dirs.map(([dirName, child]) => (
            <Folder key={dirName} node={child} name={dirName} depth={depth + 1}
                    open={open} onOpen={onOpen} />
          ))}
          <ul>
            {node.files.map((f) => (
              <li key={f.path}>
                <FileRow file={f} depth={depth + 1} open={open}
                         onOpen={(p) => onOpen(p, f.id)} label={f.name} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function FileRow({ file, depth, open, onOpen, label }) {
  const Icon = file.kind === 'db' ? Database : File
  return (
    <button type="button" className="tree-row"
            style={{ paddingLeft: `${8 + depth * 11}px` }}
            aria-current={open === file.path}
            onClick={() => onOpen(file.path)}>
      <Icon size={12} className="shrink-0 opacity-70" />
      <span className="truncate font-mono text-[12px]">{label}</span>
    </button>
  )
}

/* -- payload bytes (J.14) ------------------------------------------------- */

/** The image behind a media node, beside its prose (spec J.14).
 *
 *  The description exists because of the image, so a reader shown one
 *  without the other is left trusting text about pixels nobody can see.
 *  The bytes come through the J.14 route — a fetch, because an <img src>
 *  cannot carry the Bearer header — and live as an object URL, revoked
 *  when the node changes or the view unmounts. A payload that is gone or
 *  out of scope is a quiet one-line note, never an error wall: the map
 *  keeps working when the flesh is out of reach (G.7).
 */
export function PayloadImage({ forest, id, title, type, payloadType }) {
  const { t } = useI18n()
  // Media only, and only an image when the map named the payload's type.
  // `look` carries no payload fields, so callers coming from a digest pass
  // no payloadType and the served Content-Type decides instead — an audio
  // payload simply declines to render.
  const wanted = type === 'media' && (!payloadType || payloadType === 'image')
  const [shown, setShown] = useState(null)   // {url} | {missing: true} | null

  useEffect(() => {
    if (!wanted) return undefined
    let url = null
    let alive = true
    setShown(null)
    api.payload(forest, id)
      .then(async (p) => {
        // When the map declared `payload_type: image`, the map is trusted;
        // otherwise only bytes the host itself calls an image are shown —
        // and the decision is made on the HEADER, before the body is paid
        // for: an audio payload declines at one header read, not after a
        // full download it was going to discard.
        if (!alive || (!payloadType && !p.type.startsWith('image/'))) {
          p.cancel()
          return
        }
        const blob = await p.blob()
        if (!alive) return
        url = URL.createObjectURL(blob)
        setShown({ url })
      })
      .catch(() => { if (alive) setShown({ missing: true }) })
    return () => { alive = false; if (url) URL.revokeObjectURL(url) }
  }, [forest, id, wanted, payloadType])

  if (!wanted || !shown) return null
  if (shown.missing) {
    return <p className="text-[12px] text-text-3">{t('files.payload_missing')}</p>
  }
  return (
    <a href={shown.url} target="_blank" rel="noreferrer"
       title={t('files.payload_open')} className="inline-block">
      <img src={shown.url} alt={title || t('files.payload_alt')}
           className="max-h-[420px] max-w-full rounded-lg border border-line
                      bg-surface-2 object-contain" />
    </a>
  )
}

/* -- the viewer ---------------------------------------------------------- */

function Viewer({ forest, grant, file, onEdit, onNavigate }) {
  const { t } = useI18n()
  const [mode, setMode] = useState('read')

  useEffect(() => { setMode('read') }, [file.path])

  const digest = useAsync(() => api.call(forest, 'look', { id: file.id }),
                          [forest, file.id])

  if (file.kind === 'db') {
    return <DatasetViewer forest={forest} grant={grant} file={file} digest={digest} />
  }
  if (file.kind === 'payload') {
    // The file IS the image here, so it opens as one (J.14); every other
    // payload kind still has no viewer and says so.
    return (
      <Card title={file.path} subtitle={t('files.payload_sub')} icon={File}>
        {file.type === 'media' && file.payload_type === 'image' ? (
          <PayloadImage forest={forest} id={file.id} title={digest.data?.title}
                        type="media" payloadType="image" />
        ) : (
          <Empty icon={File} title={t('files.payload')}>{t('files.payload_hint')}</Empty>
        )}
      </Card>
    )
  }

  return (
    <Card
      title={file.path}
      subtitle={digest.data?.title}
      icon={File}
      actions={
        <>
          <div className="segment">
            {[['read', Eye, t('files.mode_read')], ['source', Code2, t('files.mode_source')]]
              .map(([value, Icon, label]) => (
                <button key={value} type="button" aria-pressed={mode === value}
                        onClick={() => setMode(value)}>
                  <Icon size={13} /> {label}
                </button>
              ))}
          </div>
          <CopyExport forest={forest} id={file.id} />
          {onEdit && (
            <button type="button" className="btn btn-sm"
                    onClick={() => onEdit(file.id)}>
              <Pencil size={13} /> {t('files.edit')}
            </button>
          )}
        </>
      }>
      <NodeBody forest={forest} id={file.id} mode={mode} digest={digest}
                onNavigate={onNavigate} />
    </Card>
  )
}

/** The document as the forest stores it, on the clipboard (J.14.1).
 *
 *  The bytes come from the EXPORT route — the planted file verbatim,
 *  frontmatter included, no token budget — and never from a surface that
 *  re-serialises them. That distinction is the whole reason this button
 *  exists: an operator copied a body out of the rich editor, which renders
 *  markdown as HTML and writes it back, and what landed on the clipboard was
 *  one flattened paragraph with `\_` inside every identifier. The reading
 *  view shows a RENDERING too, so "select all, copy" here would hand over
 *  the browser's idea of the text. This hands over the file.
 *
 *  Safari will not accept a `writeText` that arrives after an await, so the
 *  fetch is handed to the clipboard as a PROMISE where that API exists — the
 *  gesture is still the click. Everywhere else the plain path is used, and
 *  the fetch's own error survives either way, because a refusal from the
 *  Station is the useful half of a failure.
 */
function CopyExport({ forest, id }) {
  const { t } = useI18n()
  const [state, setState] = useState(null)   // 'busy' | 'done' | Error

  useEffect(() => {
    if (state !== 'done') return undefined
    const timer = setTimeout(() => setState(null), 1600)
    return () => clearTimeout(timer)
  }, [state])

  async function copy() {
    setState('busy')
    let failure = null
    const text = () => api.exportNode(forest, id)
      .catch((e) => { failure = e; throw e })
    try {
      const clipboard = navigator.clipboard
      if (typeof ClipboardItem !== 'undefined' && clipboard?.write) {
        await clipboard.write([new ClipboardItem({
          'text/plain': text().then((md) => new Blob([md], { type: 'text/plain' })),
        })])
      } else {
        await clipboard.writeText(await text())
      }
      setState('done')
    } catch (e) { setState(failure || e) }
  }

  const failed = state && state !== 'busy' && state !== 'done'
  return (
    /* The refusal is the Station's own sentence, kept where the act was —
       an error wall over the document for a clipboard that did not take is
       louder than what happened (J.5.17 rule 3 the other way round). */
    <button type="button" className="btn btn-sm" onClick={copy}
            disabled={state === 'busy'}
            title={failed ? state.message : t('files.copy_markdown_hint')}>
      {failed ? <Alert size={13} />
        : state === 'done' ? <Check size={13} /> : <Copy size={13} />}
      {t('files.copy_markdown')}
    </button>
  )
}

/** Passport from `look`, body from `pick`. Two calls, because that is what
 *  the contract offers — and the second only when the first succeeded. */
function NodeBody({ forest, id, mode, digest, onNavigate }) {
  const { t } = useI18n()
  const body = useAsync(() => api.call(forest, 'pick', { id }), [forest, id])

  if (digest.busy || body.busy) return <Skeleton rows={6} />
  if (digest.error) return <ErrorNote error={digest.error} onRetry={digest.reload} />

  const d = digest.data || {}
  const text = body.data?.body ?? ''
  // C.4: an oversized body is refused and the outline comes back instead.
  const outlineOnly = Boolean(body.data?.outline && !body.data?.body)

  if (mode === 'source') {
    return (
      <div className="space-y-4">
        <div>
          <div className="label">{t('files.passport')}</div>
          <p className="mb-1.5 text-[12px] text-text-3">{t('files.passport_hint')}</p>
          <pre className="source-view">
            <Highlighted text={passportYaml(d)} lang="yaml" />
          </pre>
        </div>
        <div>
          <div className="label">{t('files.body_stored')}</div>
          {body.error ? <ErrorNote error={body.error} />
            : outlineOnly ? <OutlineOnly outline={body.data.outline} />
            : <pre className="source-view"><Highlighted text={text} lang="markdown" /></pre>}
        </div>
      </div>
    )
  }

  if (body.error) return <ErrorNote error={body.error} onRetry={body.reload} />
  if (outlineOnly) return <OutlineOnly outline={body.data.outline} />
  // J.5.4: an HTML body is a page, sanitised. `Markdown` parses then
  // sanitises before inserting, so a document cannot script the console.
  const asPage = HTML_BODY.test(text)

  /* Wikilinks became fragment links; catching them here keeps navigation
     inside the console instead of leaving a dead `#` in the address bar. */
  function follow(ev) {
    const anchor = ev.target.closest?.('a[href^="#node:"]')
    if (!anchor) return
    ev.preventDefault()
    onNavigate?.(decodeURIComponent(anchor.getAttribute('href').slice(NODE_HREF.length)))
  }

  return (
    <div className="space-y-4">
      {/* Above the body, because the body exists because of it (J.14). */}
      {d.type === 'media' && (
        <PayloadImage forest={forest} id={id} title={d.title} type={d.type} />
      )}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
      <div onClick={follow}
           className={asPage ? 'rounded-lg border border-line bg-surface-2 p-4' : ''}>
        {asPage && <div className="label">{t('files.as_page')}</div>}
        <Markdown>{asPage ? text : linkify(text)}</Markdown>
      </div>
    </div>
  )
}

function OutlineOnly({ outline }) {
  const { t } = useI18n()
  return (
    <div>
      <p className="mb-2 text-[12.5px] text-text-3">{t('files.outline_only')}</p>
      <ul className="space-y-1">
        {outline.map((section, i) => (
          <li key={`${section}-${i}`}
              className="rounded-md bg-surface-2 px-2.5 py-1.5 text-[12.5px] text-text-2">
            {section}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** The passport as the Catalog holds it — labelled as such, never as the
 *  file's bytes (J.5.4). */
function passportYaml(d) {
  const lines = [
    `id: ${d.id ?? ''}`,
    `type: ${d.type ?? ''}`,
    `title: ${d.title ?? ''}`,
    `summary: ${d.summary ?? ''}`,
  ]
  if (d.updated) lines.push(`updated: ${d.updated}`)
  if (d.confidence != null && d.confidence !== 1) lines.push(`confidence: ${d.confidence}`)
  if (d.tags?.length) lines.push(`tags: [${d.tags.join(', ')}]`)
  if (d.edges_out?.length) {
    lines.push('links:')
    for (const e of d.edges_out) {
      lines.push(`  - rel: ${e.rel}`)
      lines.push(`    target: ${e.target}`)
    }
  }
  return lines.join('\n')
}

/* -- datasets ------------------------------------------------------------ */

const DEFAULT_ROWS = 100

/** A payload browsed through `query` and nothing else (J.5.4): the same
 *  single SELECT, the same injected LIMIT, the same timeout an agent gets. */
function DatasetViewer({ forest, grant, file, digest }) {
  const { t } = useI18n()
  const [table, setTable] = useState(null)
  // Two pieces of state, deliberately: `sql` is what the operator is
  // typing and `submitted` is what was actually asked for. Running on
  // every keystroke would fire a query per character.
  const [sql, setSql] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  const manual = digest.data?.query_manual
  const tables = useMemo(() => Object.keys(manual?.tables || {}), [manual])

  const ask = (next) => { setSql(next); setSubmitted(next); setAttempt((n) => n + 1) }

  // One table or many, the first one opens loaded: a browser that starts
  // empty asks the operator to guess a name it already knows.
  useEffect(() => {
    if (!tables.length || table) return
    setTable(tables[0])
    ask(`SELECT * FROM ${tables[0]} LIMIT ${DEFAULT_ROWS}`)
  }, [tables, table])   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!submitted.trim()) return undefined
    let alive = true
    setBusy(true)
    api.call(forest, 'query', { id: file.id, sql: submitted })
      .then((r) => { if (alive) setResult(r) })
      .catch((error) => { if (alive) setResult({ error }) })
      .finally(() => { if (alive) setBusy(false) })
    return () => { alive = false }
  }, [forest, file.id, submitted, attempt])

  const canQuery = (grant?.caps || []).some((c) => c === 'query' || c === 'admin')

  if (digest.busy) return <Card><Skeleton rows={6} /></Card>
  if (digest.error) return <Card><ErrorNote error={digest.error} onRetry={digest.reload} /></Card>
  if (!canQuery) {
    return (
      <Card title={file.path} icon={Database}>
        <Empty icon={Database} title={t('files.db_needs_query')}>{t('cap.query')}</Empty>
      </Card>
    )
  }

  return (
    <Card title={file.path} subtitle={t('files.db_sub', { id: file.id })}
          icon={Database}>
      {/* One column, not two: results are the wide thing here, and a side
          rail would spend the width they need. The table list is a row of
          chips, which is enough for the handful of tables a payload has. */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-text-3">
            {t('files.db_tables')}
          </span>
          {tables.map((name) => (
            <button key={name} type="button" aria-pressed={table === name}
                    className={`badge transition ${table === name ? 'badge-accent' : ''}`}
                    onClick={() => {
                      setTable(name)
                      ask(`SELECT * FROM ${name} LIMIT ${DEFAULT_ROWS}`)
                    }}>
              <Database size={11} className="opacity-70" />
              {name}
              <span className="text-text-3">
                {(manual?.tables?.[name] || []).length}
              </span>
            </button>
          ))}
        </div>

        <div className="min-w-0">
          <label className="block">
            <span className="label">{t('files.db_sql')}</span>
            <textarea className="field font-mono text-[12px]" rows={2} value={sql}
                      spellCheck={false}
                      onChange={(e) => setSql(e.target.value)} />
          </label>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <button type="button" className="btn btn-sm btn-primary"
                    disabled={busy || !sql.trim()}
                    onClick={() => ask(sql)}>
              {busy ? t('common.working') : t('common.run')}
            </button>
            {(manual?.example_queries || []).map((q, i) => (
              <button key={i} type="button" className="badge hover:border-accent/40"
                      title={q} onClick={() => ask(q)}>
                {t('files.db_shortcut', { n: i + 1 })}
              </button>
            ))}
            <span className="ml-auto text-[12px] text-text-3">{t('files.db_guard')}</span>
          </div>

          <div className="mt-3">
            {busy && !result ? <Spinner label={t('common.loading')} />
              : result?.error ? <ErrorNote error={result.error} />
              : result ? <Rows result={result} />
              : null}
          </div>
        </div>
      </div>
    </Card>
  )
}

/** A local table rather than the shared one: that component carries a
 *  min-width for narrow phones, and here it pushed a right-aligned number
 *  out of the scroller while its left-aligned header stayed in view — a
 *  column that looked empty and was not. Cells size to their content, so
 *  what scrolls is the table and never a value. */
function Rows({ result }) {
  const { t } = useI18n()
  const columns = result.columns || []
  const rows = result.rows || []
  if (!rows.length) return <p className="text-[12.5px] text-text-3">{t('files.db_no_rows')}</p>
  return (
    <div>
      <div className="max-h-[24rem] overflow-auto rounded-lg border border-line">
        <table className="w-full text-[12.5px]">
          <thead className="sticky top-0 bg-surface-2">
            <tr className="text-left">
              {columns.map((c, i) => (
                <th key={i} className="whitespace-nowrap border-b border-line px-2.5 py-2
                                       text-[11px] font-semibold uppercase
                                       tracking-[0.06em] text-text-3">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((row, i) => (
              <tr key={i} className="hover:bg-surface-2">
                {row.map((cell, j) => (
                  <td key={j} className={`whitespace-nowrap px-2.5 py-1.5 text-text-2
                    ${typeof cell === 'number' ? 'tabular-nums' : ''}`}>
                    {cell === null ? <span className="text-text-3">—</span> : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[12px] text-text-3">
        {t('files.db_rows', { n: rows.length })}
        {result.limited ? ` · ${t('common.truncated')}` : ''}
      </p>
    </div>
  )
}

/* -- the inspector ------------------------------------------------------- */

function Inspector({ forest, node, meta, onOpen }) {
  const { t } = useI18n()
  const [tab, setTab] = useState('passport')

  const digest = useAsync(() => api.call(forest, 'look', { id: node }),
                          [forest, node], { skip: !node })

  if (!node) return null
  const d = digest.data

  return (
    /* The same viewport pin as the tree: two rails, one rule. */
    <Card className="xl:sticky xl:top-6 xl:flex xl:max-h-[calc(100vh-3rem)]
                     xl:flex-col xl:self-start"
          bodyClass="p-0 xl:flex xl:min-h-0 xl:flex-1 xl:flex-col">
      <div className="flex shrink-0 border-b border-line">
        {[['passport', t('files.tab_passport')],
          ['index', t('files.tab_index')],
          ['trails', t('files.tab_trails')]].map(([key, label]) => (
          <button key={key} type="button" onClick={() => setTab(key)}
                  aria-pressed={tab === key}
                  className={`flex-1 border-b-2 px-2 py-2 text-[12px] transition
                    ${tab === key ? 'border-accent text-accent'
                                  : 'border-transparent text-text-3 hover:text-text-2'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="max-h-[30rem] overflow-y-auto p-3.5 xl:max-h-none
                      xl:min-h-0 xl:flex-1">
        {digest.busy ? <Skeleton rows={5} />
          : digest.error ? <ErrorNote error={digest.error} onRetry={digest.reload} />
          : !d ? null
          : tab === 'passport'
            ? <Passport forest={forest} d={d} meta={meta} onOpen={onOpen} />
          : tab === 'index' ? <IndexEntry forest={forest} d={d} />
          : <Trails meta={meta} d={d} />}
      </div>
    </Card>
  )
}

/** Kilobytes for a person. The same shape the Ask console's own formatter
 *  uses; both are three lines over `Number`, and neither is a contract. */
const fmtBytes = (n) => (n >= 1024 * 1024
  ? `${(n / 1024 / 1024).toFixed(1)} MB`
  : `${Math.max(1, Math.round(n / 1024))} KB`)

/** The passport, with its three layers named.
 *
 *  The product's own author read the `summary` of an ingested PDF as "the
 *  model summarised my document" and went looking for the rest of it. He was
 *  reading the right field and the wrong thing: a summary is the SCENT — 60
 *  tokens of curated metadata, the only text `locate` searches (C.6b) — and
 *  the document itself was sitting under it, whole, as the body. Nothing was
 *  missing; the panel had simply never said which of the two it was showing.
 *
 *  So each layer is labelled with what it is FOR: the scent with the budget
 *  it is written against and the call that reads it, the body with its own
 *  size, and the original with its type and bytes. All three come from the
 *  `look` the panel already ran — `outline`, `stats.body_tokens` and the
 *  C.2.2 payload fields are in the digest it asks for, and `look` stats a
 *  payload without ever opening it (C.2.2 rule 6).
 */
function Passport({ forest, d, meta, onOpen }) {
  const { t } = useI18n()
  const scent = countTokens(d.summary)
  // The outline is the first thing `look`'s budget clips (C.2), and it says
  // so. A count taken from a clipped list is a floor, and it is printed as
  // one rather than as a number that happens to be wrong.
  const clipped = (d.truncated_fields || []).includes('outline')
  const sections = `${(d.outline || []).length}${clipped ? '+' : ''}`
  return (
    <div className="space-y-3">
      <Badge tone="accent">{d.type}</Badge>
      <div className="nodeid break-all">{d.id}</div>
      <div>
        <div className="label">
          {t('files.scent', { n: scent, max: SUMMARY_TOKENS })}
        </div>
        <p className="text-[13px] leading-relaxed text-text">{d.summary}</p>
        <p className="mt-1 text-[12px] leading-relaxed text-text-3">
          {t('files.scent_hint')}
        </p>
      </div>
      {!!d.tags?.length && (
        <div className="flex flex-wrap gap-1">
          {d.tags.map((tag) => <span key={tag} className="badge">{tag}</span>)}
        </div>
      )}
      <div>
        <div className="label">{t('files.body_label')}</div>
        <p className="text-[12.5px] text-text-2">
          {d.outline
            ? t('files.body_line', { sections, tokens: d.stats?.body_tokens ?? 0 })
            : t('files.body_line_tokens', { tokens: d.stats?.body_tokens ?? 0 })}
        </p>
      </div>
      <Original forest={forest} d={d} meta={meta} />
      {/* The body's size used to sit beside this one as a second metric; it
          is in the Body line above now, and a figure printed twice is a
          figure that will disagree with itself. */}
      <Metric label={t('explore.degree')} value={d.stats?.degree ?? 0} />
      {!!d.edges_out?.length && (
        <div>
          <div className="label flex items-center gap-1.5"><Link size={12} />
            {t('explore.edges')}</div>
          <ul className="divide-y divide-line">
            {d.edges_out.map((e, i) => (
              <li key={i} className="py-1.5">
                <span className="text-[11px] uppercase tracking-[0.05em] text-text-3">
                  {e.rel}
                </span>
                <button type="button" onClick={() => onOpen?.(e.target)}
                        className="block break-all text-left font-mono text-[12px]
                                   text-text-2 hover:text-accent">
                  {e.target}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/** The file this document was made from (J.14 + C.2.2 rule 6).
 *
 *  A converted document keeps its original under the branch's `_assets/`,
 *  and the tree no longer shows that directory — so this line is the one
 *  route to it, and it is the honest one: it names the type and the size the
 *  passport already knows, and hands the bytes over through the governed
 *  J.14 route with the viewer's own credential, exactly as `PayloadImage`
 *  fetches a picture. Any payload type is served there, not only images.
 *
 *  Three states, and the third is the point of the other two: bytes that are
 *  in the forest, bytes the passport names and the disk does not have
 *  (`payload_missing`, G.7's "the map keeps working when the flesh is out of
 *  reach"), and a node that never had an original at all — a note, which
 *  gets no line rather than a line saying "none".
 *
 *  A remote payload (G.9) names its type and carries no `payload_bytes` —
 *  `look` stats a local file and never opens a remote one, so a size is the
 *  one thing it cannot have. J.14 serves those bytes from v0.84, one of two
 *  ways: proxied under the ceiling, and **302 to a presigned URL** above it.
 *  Which one it will be is not knowable from here, so the remote line is a
 *  LINK and never a fetch: J.5.13 pins this page to `connect-src 'self'`, a
 *  credentialed fetch that redirects to a store's origin is refused by the
 *  page's own policy, and the repair must not be widening the policy to
 *  whatever origin a store happens to have — that would make the CSP a
 *  function of the registry. A link is a top-level navigation, which no
 *  `connect-src` governs.
 */
function Original({ forest, d, meta }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (d.payload_missing) {
    return <p className="text-[12px] text-text-3">{t('files.original_missing')}</p>
  }
  if (d.payload_type === undefined && d.payload_bytes === undefined) return null

  // The archived name is a hash the Gardener composed; what a person wants
  // in their Downloads folder is the node's own name with the original's
  // extension on it — the same shape the Read console's `.md` download uses.
  const stored = String(meta?.payload || '')
  const ext = stored.includes('.') ? stored.slice(stored.lastIndexOf('.') + 1)
    : (d.payload_type || 'bin')
  const name = `${d.id.split('/').pop() || 'payload'}.${ext.toLowerCase()}`
  const local = typeof d.payload_bytes === 'number'
  // The passport's own URI is the confirmation when the map is loaded; the
  // absent size is the digest's own answer and stands on its own when it is
  // not (C.2.2 rule 6).
  const remote = !local && (!stored || /^[a-z0-9+.-]+:\/\//i.test(stored))

  /** J.14 rule 5, the whole of the console's half: one credentialed ask,
   *  one navigation. The window is opened AFTER the await, which a strict
   *  popup blocker may refuse; opening it first and setting its location
   *  would need a handle, and a handle is exactly what `noopener` withholds
   *  — so the trade is made in favour of the store never being handed a
   *  reference to this page. */
  async function open() {
    setBusy(true)
    setError(null)
    try {
      const { url } = await api.payloadUrl(forest, d.id)
      window.open(url, '_blank', 'noopener')
    } catch (e) { setError(e) } finally { setBusy(false) }
  }

  async function save() {
    setBusy(true)
    setError(null)
    let url = null
    try {
      const p = await api.payload(forest, d.id)
      url = URL.createObjectURL(await p.blob())
      const a = document.createElement('a')
      a.href = url
      a.download = name
      a.click()
    } catch (e) { setError(e) } finally {
      setBusy(false)
      if (url) setTimeout(() => URL.revokeObjectURL(url), 2000)
    }
  }

  return (
    <div>
      <div className="label">{t('files.original')}</div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12.5px] text-text-2">
          {(d.payload_type || ext).toUpperCase()}
          {local ? ` · ${fmtBytes(d.payload_bytes)}` : ''}
        </span>
        {local && (
          <button type="button" className="btn btn-sm" onClick={save} disabled={busy}>
            <Download size={13} />
            {busy ? t('common.working') : t('files.original_download')}
          </button>
        )}
        {/* J.14 rule 5: ASK for the URL, then navigate to it. A `fetch` of
            the bytes cannot follow the 302 (J.5.13 pins this page to
            `connect-src 'self'`), and a bare `href` to the payload route
            carries no credential and answers 401 — the two failures this
            rule exists between. `noopener` because the tab lands on a
            store's own origin, and a window handed a reference back to this
            one is a window that can navigate it. */}
        {remote && (
          <button type="button" className="btn btn-sm" onClick={open}
                  disabled={busy}>
            <Download size={13} />
            {busy ? t('common.working') : t('files.original_open')}
          </button>
        )}
      </div>
      {remote && (
        <p className="mt-1 text-[12px] text-text-3">{t('files.original_remote')}</p>
      )}
      <ErrorNote error={error} />
    </div>
  )
}

/** The entry this node has in its parent index — the same summary, kept in
 *  sync by the engine on every write. Derived, never hand-edited. */
function IndexEntry({ forest, d }) {
  const { t } = useI18n()
  const parent = d.trail?.length ? d.trail[d.trail.length - 1] : null
  const family = useAsync(() => api.call(forest, 'look', { id: parent }),
                          [forest, parent], { skip: !parent })

  if (!parent) return <p className="text-[12.5px] text-text-3">{t('files.index_root')}</p>
  if (family.busy) return <Skeleton rows={3} />
  if (family.error) return <ErrorNote error={family.error} />

  const entry = (family.data?.children || []).find((c) => c.id === d.id)
  return (
    <div className="space-y-2.5">
      <p className="text-[12px] text-text-3">{t('files.index_hint', { parent })}</p>
      <pre className="source-view">
        <Highlighted lang="markdown"
                     text={entry ? `- [[${entry.id}]] — ${entry.summary}`
                                 : t('files.index_missing')} />
      </pre>
      <p className="text-[12px] text-text-3">{t('files.index_derived')}</p>
    </div>
  )
}

function Trails({ meta, d }) {
  const { t } = useI18n()
  const heat = meta?.heat ?? d.stats?.heat ?? 0
  return (
    <div className="space-y-3">
      <div>
        <div className="label flex items-center gap-1.5"><Flame size={12} />
          {t('files.heat_persistent')}</div>
        <div className="text-[18px] font-medium tabular-nums text-text">
          {Number(heat).toFixed(2)}
        </div>
        <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-3">
          <div className="h-full rounded-full bg-accent"
               style={{ width: `${Math.min(100, Number(heat) * 100)}%` }} />
        </div>
      </div>
      <p className="text-[12px] leading-relaxed text-text-3">{t('files.heat_hint')}</p>
      <Metric label={t('explore.updated')} value={d.updated || '—'} />
    </div>
  )
}
