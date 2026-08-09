/* The files mode of Explore (spec J.5.4).
 *
 * The same forest as the graph, seen the way it lives on disk: a tree of
 * markdown with payloads beside their owners. Each file opens as what it
 * *is* — prose rendered as prose, a database as a table you can query, an
 * HTML body as a page — and the stored form is always one click away.
 *
 * Three rules from J.5.4 are load-bearing here:
 *
 * - **Nothing is read outside the primitives.** The tree comes from the map
 *   projection, a body from `pick`, a table from `query`. There is no file
 *   endpoint, because a console that could read bytes directly would be the
 *   privileged side-channel J.5 forbids.
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
import {
  Badge, Card, Empty, ErrorNote, Skeleton, Spinner,
} from '../design/ui.jsx'
import {
  ChevronRight, Code2, Database, Eye, File, Flame, Link, Pencil, Search,
} from '../design/icons.jsx'
import { Metric, useAsync } from './shared.jsx'

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

/** A node id and its payload, as paths. `people/jimmy-wesley` is the file
 *  `people/jimmy-wesley.md`; a dataset's `.db` sits beside it. */
export function filesOf(nodes) {
  const out = []
  for (const n of nodes) {
    out.push({ path: `${n.id}.md`, id: n.id, kind: 'md', type: n.type })
    if (n.payload && !/^[a-z0-9+.-]+:\/\//i.test(n.payload)) {
      const dir = n.id.includes('/') ? n.id.slice(0, n.id.lastIndexOf('/') + 1) : ''
      out.push({
        path: dir + n.payload, id: n.id, type: n.type,
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
      <Card title={t('files.tree')} icon={File} bodyClass="p-2">
        <label className="relative mb-2 block">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2
                                       -translate-y-1/2 text-text-3" />
          <input className="field !py-1.5 pl-8 text-[12.5px]" value={filter}
                 placeholder={t('files.filter')}
                 onChange={(e) => setFilter(e.target.value)} />
        </label>
        <div className="max-h-[26rem] overflow-y-auto pr-1">
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
      <span className="truncate font-mono text-[11.5px]">{label}</span>
    </button>
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
    return (
      <Card title={file.path} subtitle={t('files.payload_sub')} icon={File}>
        <Empty icon={File} title={t('files.payload')}>{t('files.payload_hint')}</Empty>
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
          <p className="mb-1.5 text-[11.5px] text-text-3">{t('files.passport_hint')}</p>
          <pre className="source-view">{passportYaml(d)}</pre>
        </div>
        <div>
          <div className="label">{t('files.body_stored')}</div>
          {body.error ? <ErrorNote error={body.error} />
            : outlineOnly ? <OutlineOnly outline={body.data.outline} />
            : <pre className="source-view">{text}</pre>}
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
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div onClick={follow}
         className={asPage ? 'rounded-lg border border-line bg-surface-2 p-4' : ''}>
      {asPage && <div className="label">{t('files.as_page')}</div>}
      <Markdown>{asPage ? text : linkify(text)}</Markdown>
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
            <span className="ml-auto text-[11px] text-text-3">{t('files.db_guard')}</span>
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
                                       text-[10.5px] font-semibold uppercase
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
      <p className="mt-2 text-[11.5px] text-text-3">
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
    <Card bodyClass="p-0">
      <div className="flex border-b border-line">
        {[['passport', t('files.tab_passport')],
          ['index', t('files.tab_index')],
          ['trails', t('files.tab_trails')]].map(([key, label]) => (
          <button key={key} type="button" onClick={() => setTab(key)}
                  aria-pressed={tab === key}
                  className={`flex-1 border-b-2 px-2 py-2 text-[11.5px] transition
                    ${tab === key ? 'border-accent text-accent'
                                  : 'border-transparent text-text-3 hover:text-text-2'}`}>
            {label}
          </button>
        ))}
      </div>

      <div className="max-h-[30rem] overflow-y-auto p-3.5">
        {digest.busy ? <Skeleton rows={5} />
          : digest.error ? <ErrorNote error={digest.error} onRetry={digest.reload} />
          : !d ? null
          : tab === 'passport' ? <Passport d={d} meta={meta} onOpen={onOpen} />
          : tab === 'index' ? <IndexEntry forest={forest} d={d} />
          : <Trails meta={meta} d={d} />}
      </div>
    </Card>
  )
}

function Passport({ d, meta, onOpen }) {
  const { t } = useI18n()
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone="accent">{d.type}</Badge>
        {meta?.stale && <Badge tone="warn">{t('files.stale')}</Badge>}
      </div>
      <div className="nodeid break-all">{d.id}</div>
      <p className="text-[13px] leading-relaxed text-text">{d.summary}</p>
      {!!d.tags?.length && (
        <div className="flex flex-wrap gap-1">
          {d.tags.map((tag) => <span key={tag} className="badge">{tag}</span>)}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <Metric label={t('explore.degree')} value={d.stats?.degree ?? 0} />
        <Metric label={t('explore.tokens')} value={d.stats?.body_tokens ?? 0} />
      </div>
      {!!d.edges_out?.length && (
        <div>
          <div className="label flex items-center gap-1.5"><Link size={12} />
            {t('explore.edges')}</div>
          <ul className="divide-y divide-line">
            {d.edges_out.map((e, i) => (
              <li key={i} className="py-1.5">
                <span className="text-[10.5px] uppercase tracking-[0.05em] text-text-3">
                  {e.rel}
                </span>
                <button type="button" onClick={() => onOpen?.(e.target)}
                        className="block break-all text-left font-mono text-[11.5px]
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
        {entry ? `- [[${entry.id}]] — ${entry.summary}` : t('files.index_missing')}
      </pre>
      <p className="text-[11.5px] text-text-3">{t('files.index_derived')}</p>
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
