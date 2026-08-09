// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The Data console — a database client over the forest's datasets.
 *
 * Everything here is the two primitives the spec already defines. Reading is
 * `query` (C.5, read-only, single statement); writing is `tend` (C.10, one
 * INSERT/UPDATE/DELETE at a time, WHERE mandatory, its own git commit). The
 * console never gets a private channel: the SQL it builds is the SQL it
 * shows, and an operator without the `tend` capability simply browses.
 *
 * Structure is deliberately read-only. `tend` forbids DDL forever (spec
 * v0.21 C.10) and schema evolution is not the query surface's job — a table
 * is born through `plant`'s declarative schema (C.7.1) and changed by
 * rebuilding it, so offering an "add column" button here would only be a
 * button that always fails.
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Code, CopyButton, Empty, ErrorNote, Modal, Note, Skeleton,
  Spinner, Table, Tabs, Td,
} from '../design/ui.jsx'
import {
  ChevronLeft, ChevronRight, Columns, Data as DataIcon, Download,
  Grid as GridIcon, Play, Plus, Refresh, Save,
} from '../design/icons.jsx'
import { Grid, TypedInput, fieldKind, isComplete } from '../design/grid.jsx'
import { NeedsCapability, has, rootsOf, useAsync } from './shared.jsx'

const PAGE_SIZES = [25, 50, 100, 500]

/* -- SQL the console writes for you ------------------------------------- */

const qid = (name) => `"${String(name).replace(/"/g, '""')}"`
const lit = (v) => `'${String(v).replace(/'/g, "''")}'`

/** A cell as SQL. The column's kind decides bare or quoted, and an empty box
 *  means NULL rather than the empty string — the distinction every database
 *  client is expected to keep. The input already refuses anything the column
 *  cannot hold, so by the time a value gets here it only has to be quoted. */
function cellLiteral(text, kind) {
  const v = String(text ?? '')
  if (v === '') return 'NULL'
  if ((kind === 'integer' || kind === 'number') && Number.isFinite(Number(v))) {
    return String(Number(v))
  }
  return lit(v)
}

const CONSTRAINT_START = /^(PRIMARY|UNIQUE|CHECK|FOREIGN|CONSTRAINT)\b/i
const TYPE_STOP =
  /^(NOT|NULL|PRIMARY|UNIQUE|DEFAULT|CHECK|REFERENCES|COLLATE|GENERATED|AS|AUTOINCREMENT)\b/i

/** Column types out of the stored `CREATE TABLE`.
 *
 *  `PRAGMA table_info` would be the direct route, but `query` forbids PRAGMA
 *  (spec C.5), so the declaration itself is the source. Names are never taken
 *  from here — those come from `look`'s query manual, which is the contract.
 *  A parse that fails therefore costs the types, never the browsing. */
function columnsFromDdl(ddl) {
  const open = ddl ? ddl.indexOf('(') : -1
  if (open < 0) return {}
  const inner = ddl.slice(open + 1, ddl.lastIndexOf(')'))

  const parts = []
  let depth = 0
  let buf = ''
  for (const ch of inner) {
    if (ch === '(') depth += 1
    if (ch === ')') depth -= 1
    if (ch === ',' && depth === 0) { parts.push(buf); buf = '' } else buf += ch
  }
  parts.push(buf)

  const out = {}
  for (const raw of parts) {
    const part = raw.trim()
    if (!part || CONSTRAINT_START.test(part)) continue
    const m = part.match(/^("([^"]*)"|`([^`]*)`|\[([^\]]*)\]|[A-Za-z_][\w$]*)\s*([\s\S]*)$/)
    if (!m) continue
    const rest = m[5] || ''
    const type = []
    for (const word of rest.split(/\s+/).filter(Boolean)) {
      if (TYPE_STOP.test(word)) break
      type.push(word)
    }
    out[m[2] ?? m[3] ?? m[4] ?? m[1]] = {
      type: type.join(' '),
      pk: /\bPRIMARY\s+KEY\b/i.test(rest),
      notnull: /\bNOT\s+NULL\b/i.test(rest),
      dflt: (rest.match(/\bDEFAULT\s+('(?:[^']|'')*'|\S+)/i) || [])[1] || null,
    }
  }
  // A table-level `PRIMARY KEY (a, b)` still marks the columns it names.
  const composite = ddl.match(/\bPRIMARY\s+KEY\s*\(([^)]*)\)/i)
  for (const n of composite ? composite[1].split(',') : []) {
    const key = n.trim().replace(/^["`[]|["`\]]$/g, '')
    if (out[key]) out[key].pk = true
  }
  return out
}

const describe = (names = [], ddl) => {
  const meta = columnsFromDdl(ddl)
  return names.map((name) => ({
    name, type: '', pk: false, notnull: false, dflt: null, ...(meta[name] || {}),
  }))
}

function toCsv(columns, rows) {
  const esc = (v) => (v === null || v === undefined ? ''
    : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v))
  return [columns.map(esc).join(','), ...rows.map((r) => r.map(esc).join(','))].join('\n')
}

/** Typing in a column filter must not be one round trip per keystroke. */
function useDebounced(value, ms = 300) {
  const [out, setOut] = useState(value)
  useEffect(() => {
    const handle = setTimeout(() => setOut(value), ms)
    return () => clearTimeout(handle)
  }, [value, ms])
  return out
}

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

/* -- the draft: edited on screen, not yet in the database ---------------- */

const EMPTY_DRAFT = { edits: {}, deletes: [], inserts: [], seq: 0 }

const isDirty = (d) =>
  d.deletes.length > 0 || d.inserts.length > 0 || Object.keys(d.edits).length > 0

/** How many things the operator changed — the number on the save button.
 *  A new row counts once however many of its boxes were filled; an existing
 *  row counts one per cell, because that is what was touched. */
function countChanges(draft) {
  const cells = Object.entries(draft.edits)
    .filter(([key]) => !key.startsWith('n'))
    .reduce((n, [, cols]) => n + Object.keys(cols).length, 0)
  return cells + draft.deletes.length + draft.inserts.length
}

/** The draft as the fewest statements `tend` will accept.
 *
 *  `tend` takes one instruction per call and commits it on its own (spec
 *  C.10), so a screenful of edits cannot become a single transaction. What it
 *  CAN become is a handful of well-formed statements instead of one per cell:
 *  cells changed in the same row share one SET, rows given the same SET share
 *  one WHERE ... IN, new rows share one INSERT, and removals are one DELETE.
 *  Twenty edits across four rows leave here as four statements, not twenty.
 *
 *  Deletes go last on purpose: a row dropped before its neighbours are
 *  updated is a row whose UPDATE would then quietly match nothing. */
function compile(table, columns, draft) {
  const kindOf = (name) => columns.find((c) => c.name === name)?.kind
  const out = []

  const signatures = new Map()
  for (const row of draft.inserts) {
    const values = { ...row.values, ...(draft.edits[row.key] || {}) }
    const filled = columns.map((c) => c.name).filter((n) => String(values[n] ?? '') !== '')
    if (!filled.length) continue
    const key = filled.join('\0')
    if (!signatures.has(key)) signatures.set(key, { cols: filled, tuples: [] })
    signatures.get(key).tuples.push(
      `(${filled.map((n) => cellLiteral(values[n], kindOf(n))).join(', ')})`)
  }
  for (const { cols, tuples } of signatures.values()) {
    out.push(`INSERT INTO ${qid(table)} (${cols.map(qid).join(', ')})\n`
             + `VALUES ${tuples.join(',\n       ')}`)
  }

  const bySet = new Map()
  for (const [key, cells] of Object.entries(draft.edits)) {
    const rid = Number(key)
    // A staged row is already inside its INSERT, and a row on its way out
    // does not need to be corrected first.
    if (!Number.isInteger(rid) || draft.deletes.includes(rid)) continue
    const set = columns
      .filter((c) => cells[c.name] !== undefined)
      .map((c) => `${qid(c.name)} = ${cellLiteral(cells[c.name], c.kind)}`)
      .join(', ')
    if (!set) continue
    if (!bySet.has(set)) bySet.set(set, [])
    bySet.get(set).push(rid)
  }
  for (const [set, rids] of bySet) {
    out.push(`UPDATE ${qid(table)} SET ${set} WHERE `
             + (rids.length === 1 ? `rowid = ${rids[0]}` : `rowid IN (${rids.join(', ')})`))
  }

  if (draft.deletes.length) {
    out.push(`DELETE FROM ${qid(table)} WHERE `
             + (draft.deletes.length === 1
               ? `rowid = ${draft.deletes[0]}`
               : `rowid IN (${draft.deletes.join(', ')})`))
  }
  return out
}

/* -- the console --------------------------------------------------------- */

export default function Data({ forest, grant }) {
  const { t } = useI18n()
  const [id, setId] = useState('')
  const [table, setTable] = useState('')
  const [tab, setTab] = useState('rows')
  const [page, setPage] = useState(0)
  const [size, setSize] = useState(100)
  const [sort, setSort] = useState(null)          // {col, dir}
  const [filters, setFilters] = useState({})
  const [sql, setSql] = useState('')
  const [free, setFree] = useState({})            // the SQL tab's own result
  const [draft, setDraft] = useState(EMPTY_DRAFT) // edited but not yet written
  const [pending, setPending] = useState(null)    // the compiled statements
  const [written, setWritten] = useState(null)
  const [inserting, setInserting] = useState(false)

  const mayWrite = has(grant, 'tend')

  const found = useAsync(async () => {
    const all = []
    for (const root of rootsOf(grant)) {
      const s = await api.call(forest, 'scan', {
        parent_id: root, recursive: true, limit: 200, filter: { type: 'dataset' },
      })
      all.push(...(s.nodes || []))
    }
    return all
  }, [forest, grant], { skip: !has(grant, 'read') })

  /* The dataset's shape: tables and columns from the contract (`look`), types
   * from the stored DDL, row counts in a single SELECT of scalar subqueries —
   * one statement, because `query` allows exactly one. */
  const meta = useAsync(async () => {
    const digest = await api.call(forest, 'look', { id })
    const manual = digest.query_manual || {}
    const names = Object.keys(manual.tables || {})

    const ddl = {}
    try {
      const r = await api.call(forest, 'query', {
        id,
        sql: "SELECT name, sql FROM sqlite_master WHERE type='table' "
           + "AND name NOT LIKE 'sqlite_%'",
      })
      for (const [name, text] of r.rows || []) ddl[name] = text
    } catch { /* names and columns already came from the manual */ }

    const counts = {}
    if (names.length) {
      try {
        const r = await api.call(forest, 'query', {
          id,
          sql: `SELECT ${names.map((n, i) => `(SELECT COUNT(*) FROM ${qid(n)}) AS c${i}`)
                          .join(', ')}`,
        })
        names.forEach((n, i) => { counts[n] = r.rows?.[0]?.[i] })
      } catch { /* counts are decoration, not navigation */ }
    }

    return {
      summary: digest.summary,
      examples: manual.example_queries || [],
      tables: names.map((n) => ({
        name: n, columns: describe(manual.tables[n], ddl[n]), ddl: ddl[n] || null,
        rows: counts[n],
      })),
    }
  }, [forest, id], { skip: !id })

  // Keep the selection real across reloads without resetting it on every one:
  // a `tend` refreshes the counts and must not throw the operator back to the
  // first table.
  useEffect(() => {
    const names = (meta.data?.tables || []).map((x) => x.name)
    if (!names.length) { setTable(''); return }
    if (!names.includes(table)) {
      setTable(names[0]); setPage(0); setSort(null); setFilters({})
      setDraft(EMPTY_DRAFT)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta.data])

  const current = (meta.data?.tables || []).find((x) => x.name === table) || null

  // The boxes update on every keystroke; the query follows the settled value.
  const filterKey = useDebounced(JSON.stringify(filters))
  const sortKey = sort ? `${sort.col}:${sort.dir}` : ''

  const where = useMemo(() => {
    const parts = Object.entries(JSON.parse(filterKey))
      .filter(([, v]) => String(v).trim() !== '')
      .map(([col, v]) => `${qid(col)} LIKE ${lit(`%${v}%`)}`)
    return parts.length ? ` WHERE ${parts.join(' AND ')}` : ''
  }, [filterKey])

  const order = sort ? ` ORDER BY ${qid(sort.col)} ${sort.dir === 'desc' ? 'DESC' : 'ASC'}` : ''

  /* `rowid` is what makes a row addressable, and addressable is what makes it
   * editable: `tend` demands a WHERE, and a WHERE over visible columns could
   * match rows the operator never saw. A view or a WITHOUT ROWID table has no
   * rowid, so the grid degrades to read-only rather than disappearing. */
  const rows = useAsync(async () => {
    const from = `${qid(table)}${where}`
    const tail = `${order} LIMIT ${size} OFFSET ${page * size}`
    const total = await api.call(forest, 'query', { id, sql: `SELECT COUNT(*) AS n FROM ${from}` })
    try {
      const r = await api.call(forest, 'query',
                               { id, sql: `SELECT rowid AS _rid, * FROM ${from}${tail}` })
      return {
        columns: r.columns.slice(1),
        rows: (r.rows || []).map((row) => ({ rid: row[0], cells: row.slice(1) })),
        keyed: true, total: total.rows?.[0]?.[0] ?? 0, elapsed_ms: r.elapsed_ms,
      }
    } catch {
      const r = await api.call(forest, 'query', { id, sql: `SELECT * FROM ${from}${tail}` })
      return {
        columns: r.columns,
        rows: (r.rows || []).map((row) => ({ rid: null, cells: row })),
        keyed: false, total: total.rows?.[0]?.[0] ?? 0, elapsed_ms: r.elapsed_ms,
      }
    }
  }, [forest, id, table, filterKey, sortKey, size, page], { skip: !id || !table })

  // The editor opens on the statement the current table would run, so the SQL
  // tab starts from something that already works instead of an empty box.
  const preset = current
    ? `SELECT ${current.columns.map((c) => qid(c.name)).join(', ')}\n`
      + `  FROM ${qid(current.name)}${where}${order}\n LIMIT ${size}`
    : ''
  useEffect(() => {
    setSql(preset)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table, id])

  if (!has(grant, 'query')) {
    return <NeedsCapability message={t('access.needs_admin')} hint={t('cap.query')} />
  }

  // One place decides what each column accepts, so the cell editor and the
  // new-row form can never disagree about it. The rows on screen are the
  // sample: a DATE stored as TEXT is only recognisable from its values.
  const gridColumns = useMemo(() => {
    const declared = current?.columns.length
      ? current.columns
      : (rows.data?.columns || []).map((name) => ({ name, type: '' }))
    return declared.map((c, j) => ({
      ...c,
      kind: fieldKind(c, (rows.data?.rows || []).slice(0, 30).map((r) => r.cells[j])),
    }))
  }, [current, rows.data])

  const editable = mayWrite && rows.data?.keyed && current

  // Staged rows ride along at the end of whatever page is open, marked `+`:
  // they exist on screen and nowhere else until the batch is applied.
  const deletedSet = useMemo(() => new Set(draft.deletes), [draft.deletes])
  const displayRows = useMemo(() => [
    ...(rows.data?.rows || []),
    ...draft.inserts.map((r) => ({
      rid: r.key,
      staged: true,
      cells: gridColumns.map((c) => (r.values[c.name] ?? '')),
    })),
  ], [rows.data, draft.inserts, gridColumns])
  const changes = countChanges(draft)

  /* Editing stages; it never writes. A cell put back to what the database
   * already holds stops being a change at all, so the counter can be trusted:
   * "3 changes" always means three things really differ. */
  function stageEdit(rid, col, text, stored) {
    setWritten(null)
    setDraft((d) => {
      const key = String(rid)
      const row = { ...(d.edits[key] || {}) }
      const original = stored === null || stored === undefined ? '' : String(stored)
      if (text === original && !key.startsWith('n')) delete row[col]
      else row[col] = text
      const edits = { ...d.edits }
      if (Object.keys(row).length) edits[key] = row
      else delete edits[key]
      return { ...d, edits }
    })
  }

  function stageDelete(rid) {
    setWritten(null)
    setDraft((d) => {
      if (String(rid).startsWith('n')) {          // a staged row just goes away
        const edits = { ...d.edits }
        delete edits[rid]
        return { ...d, edits, inserts: d.inserts.filter((r) => r.key !== rid) }
      }
      return d.deletes.includes(rid)
        ? { ...d, deletes: d.deletes.filter((x) => x !== rid) }
        : { ...d, deletes: [...d.deletes, rid] }
    })
  }

  function stageInsert(values) {
    setWritten(null)
    setInserting(false)
    setDraft((d) => ({
      ...d, seq: d.seq + 1, inserts: [...d.inserts, { key: `n${d.seq}`, values }],
    }))
  }

  /* One statement per `tend` call, one commit per statement (spec C.10): a
   * batch is applied in order, not in a transaction. Stopping at the first
   * failure and saying how far it got is the only honest report. */
  async function applyPending() {
    setPending((p) => ({ ...p, busy: true, error: null }))
    const statements = pending.statements
    let done = 0
    let affected = 0
    for (const statement of statements) {
      try {
        const r = await api.call(forest, 'tend', { id, sql: statement })
        done += 1
        affected += r.rows_affected ?? 0
      } catch (error) {
        setPending({ ...pending, busy: false, error, done, total: statements.length })
        // Nothing written yet means the draft is still exactly what is on
        // screen. Once something IS written, the screen and the draft no
        // longer describe the same database, and keeping it would invite a
        // second INSERT of a row that already landed.
        if (done > 0) setDraft(EMPTY_DRAFT)
        rows.reload()
        meta.reload()
        return
      }
    }
    setPending(null)
    setDraft(EMPTY_DRAFT)
    setWritten({ rows_affected: affected, commits: done })
    rows.reload()
    meta.reload()
  }

  async function runFree(e) {
    e.preventDefault()
    setFree({ busy: true })
    try { setFree({ data: await api.call(forest, 'query', { id, sql }) }) }
    catch (error) { setFree({ error }) }
  }

  const pages = Math.max(1, Math.ceil((rows.data?.total || 0) / size))

  return (
    <div className="grid gap-4 lg:grid-cols-[290px_1fr]">
      <Card title={t('data.pick')} icon={DataIcon} bodyClass="p-2"
            actions={<button className="btn btn-sm btn-ghost" onClick={found.reload}
                             title={t('common.refresh')}><Refresh size={14} /></button>}>
        {found.busy ? <div className="p-3"><Skeleton rows={3} /></div>
          : found.error ? <div className="p-3"><ErrorNote error={found.error} /></div>
          : (found.data || []).length === 0 ? <Empty icon={DataIcon}>{t('data.none')}</Empty> : (
          <ul className="space-y-0.5">
            {found.data.map((n) => (
              <li key={n.id}>
                <button onClick={() => {
                          setId(n.id); setPage(0); setSort(null); setFilters({})
                          setPending(null); setWritten(null); setFree({})
                          setDraft(EMPTY_DRAFT)
                        }}
                        className={`w-full rounded-lg px-2.5 py-2 text-left transition
                          hover:bg-surface-2 ${n.id === id ? 'bg-accent-soft' : ''}`}>
                  <span className="nodeid block truncate">{n.id}</span>
                  <span className="mt-0.5 block line-clamp-2 text-[12px] text-text-3">
                    {n.summary}
                  </span>
                </button>

                {n.id === id && (
                  <ul className="mb-1 ml-2 mt-1 space-y-0.5 border-l border-line pl-2">
                    {meta.busy && <li className="px-2 py-1"><Skeleton rows={1} /></li>}
                    {(meta.data?.tables || []).map((tb) => (
                      <li key={tb.name}>
                        <button onClick={() => {
                                  setTable(tb.name); setPage(0); setSort(null)
                                  setFilters({}); setTab('rows'); setDraft(EMPTY_DRAFT)
                                }}
                                className={`flex w-full items-center justify-between gap-2
                                  rounded-md px-2 py-1.5 text-left transition hover:bg-surface-2
                                  ${tb.name === table ? 'bg-surface-2' : ''}`}>
                          <span className="flex min-w-0 items-center gap-1.5">
                            <GridIcon size={13} className={tb.name === table
                              ? 'text-accent' : 'text-text-3'} />
                            <span className="truncate font-mono text-[12px] text-text-2">
                              {tb.name}
                            </span>
                          </span>
                          <span className="shrink-0 font-mono text-[10.5px] text-text-3">
                            {tb.rows ?? ''}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="min-w-0 space-y-4">
        {!id ? (
          <Card><Empty icon={DataIcon} title={t('data.empty')}>{t('data.empty_hint')}</Empty></Card>
        ) : (
          <Card bodyClass="p-0"
                title={table || id} subtitle={id} icon={DataIcon}
                actions={<>
                  {rows.data && (
                    <Badge tone="accent">{t('data.rows', { n: rows.data.total })}</Badge>
                  )}
                  <button className="btn btn-sm btn-ghost" title={t('common.refresh')}
                          onClick={() => { rows.reload(); meta.reload() }}>
                    <Refresh size={14} />
                  </button>
                </>}>
            <div className="px-5 pt-1">
              <Tabs value={tab} onChange={setTab} options={[
                { value: 'rows', label: t('data.tab_rows') },
                { value: 'structure', label: t('data.tab_structure') },
                { value: 'sql', label: t('data.tab_sql') },
              ]} />
            </div>

            <div className="space-y-3 p-5">
              {meta.error && <ErrorNote error={meta.error} onRetry={meta.reload} />}

              {tab === 'rows' && (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="flex items-center gap-1">
                      <button className="btn btn-sm btn-ghost" disabled={page === 0}
                              onClick={() => setPage((p) => Math.max(0, p - 1))}
                              aria-label="previous page"><ChevronLeft size={14} /></button>
                      <span className="px-1 text-[12px] tabular-nums text-text-3">
                        {t('data.page', { p: page + 1, n: pages })}
                      </span>
                      <button className="btn btn-sm btn-ghost" disabled={page + 1 >= pages}
                              onClick={() => setPage((p) => p + 1)}
                              aria-label="next page"><ChevronRight size={14} /></button>
                    </div>
                    <select className="field !w-auto !py-1.5 text-[12.5px]" value={size}
                            aria-label={t('data.page_size')}
                            onChange={(e) => { setSize(Number(e.target.value)); setPage(0) }}>
                      {PAGE_SIZES.map((n) => (
                        <option key={n} value={n}>{t('data.per_page', { n })}</option>
                      ))}
                    </select>
                    {Object.values(filters).some((v) => String(v).trim() !== '') && (
                      <button className="btn btn-sm" onClick={() => { setFilters({}); setPage(0) }}>
                        {t('data.clear_filters')}
                      </button>
                    )}
                    <span className="flex-1" />
                    {rows.data?.elapsed_ms !== undefined && (
                      <Badge>{t('common.elapsed', { ms: rows.data.elapsed_ms })}</Badge>
                    )}
                    {rows.data?.rows?.length > 0 && (
                      <button className="btn btn-sm"
                              onClick={() => download(
                                `${table}.csv`,
                                toCsv(gridColumns.map((c) => c.name),
                                      rows.data.rows.map((r) => r.cells)))}>
                        <Download size={14} /> CSV
                      </button>
                    )}
                    {editable && (
                      <button className="btn btn-sm" onClick={() => setInserting(true)}>
                        <Plus size={14} /> {t('data.insert')}
                      </button>
                    )}
                    {changes > 0 && (
                      <>
                        <button className="btn btn-sm" onClick={() => setDraft(EMPTY_DRAFT)}>
                          {t('data.discard')}
                        </button>
                        <button className="btn btn-sm btn-primary"
                                onClick={() => {
                                  setWritten(null)
                                  setPending({
                                    statements: compile(table, gridColumns, draft),
                                  })
                                }}>
                          <Save size={14} /> {t('data.save', { n: changes })}
                        </button>
                      </>
                    )}
                  </div>

                  {written && (
                    <Note>{t('data.written', { rows: written.rows_affected,
                                               n: written.commits })}</Note>
                  )}

                  {rows.busy && <Spinner label={t('common.loading')} />}
                  {rows.error && <ErrorNote error={rows.error} onRetry={rows.reload} />}
                  {rows.data && (
                    <>
                      <Grid columns={gridColumns} rows={displayRows} offset={page * size}
                            sort={sort} filters={filters} emptyLabel={t('data.no_rows')}
                            edits={draft.edits} deleted={deletedSet}
                            onSort={(col) => {
                              setPage(0)
                              setSort((s) => (s?.col !== col ? { col, dir: 'asc' }
                                : s.dir === 'asc' ? { col, dir: 'desc' } : null))
                            }}
                            onFilter={(col, value) => {
                              setPage(0)
                              setFilters((f) => ({ ...f, [col]: value }))
                            }}
                            onEdit={editable ? stageEdit : undefined}
                            onDelete={editable ? stageDelete : undefined} />
                      <p className="text-[11.5px] text-text-3">
                        {mayWrite
                          ? (rows.data.keyed ? t('data.edit_hint') : t('data.no_rowid'))
                          : t('data.read_only')}
                      </p>
                    </>
                  )}
                </>
              )}

              {tab === 'structure' && (
                <Structure table={current} t={t} />
              )}

              {tab === 'sql' && (
                <form onSubmit={runFree} className="space-y-3">
                  <label className="block">
                    <span className="label">{t('data.sql')}</span>
                    <textarea className="field min-h-[130px] resize-y font-mono text-[12.5px]
                                         leading-relaxed"
                              rows={5} value={sql} spellCheck={false}
                              onChange={(e) => setSql(e.target.value)} />
                  </label>
                  {(meta.data?.examples || []).length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      <span className="text-[11.5px] text-text-3">{t('data.examples')}</span>
                      {meta.data.examples.map((q) => (
                        <button key={q} type="button" onClick={() => setSql(q)}
                                className="badge max-w-full hover:border-accent/40
                                           hover:bg-accent-soft hover:text-accent">
                          <span className="truncate font-mono">{q}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="flex justify-end gap-2">
                    <button type="button" className="btn btn-sm" disabled={!preset}
                            onClick={() => setSql(preset)}>{t('data.reset_sql')}</button>
                    <button className="btn btn-primary" disabled={!sql.trim() || free.busy}>
                      <Play size={14} /> {t('data.run')}
                    </button>
                  </div>

                  {free.busy && <Spinner label={t('common.working')} />}
                  {free.error && <ErrorNote error={free.error} />}
                  {free.data && (
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone="accent">{t('data.rows', { n: free.data.row_count })}</Badge>
                        <Badge>{t('common.elapsed', { ms: free.data.elapsed_ms })}</Badge>
                        {free.data.limited && <Badge tone="warn">{t('data.limited')}</Badge>}
                        <span className="flex-1" />
                        {free.data.row_count > 0 && (
                          <button type="button" className="btn btn-sm"
                                  onClick={() => download('query.csv',
                                                          toCsv(free.data.columns, free.data.rows))}>
                            <Download size={14} /> CSV
                          </button>
                        )}
                      </div>
                      <Grid columns={(free.data.columns || []).map((name) => ({ name, type: '' }))}
                            rows={(free.data.rows || []).map((r) => ({ rid: null, cells: r }))}
                            emptyLabel={t('data.no_rows')} />
                    </div>
                  )}
                </form>
              )}
            </div>
          </Card>
        )}

        <Note>{t('data.sub')}</Note>
      </div>

      {pending && (
        <PendingWrite pending={pending} t={t}
                      onCancel={() => setPending(null)} onApply={applyPending} />
      )}

      <InsertRow open={inserting} columns={gridColumns} t={t}
                 onClose={() => setInserting(false)} onSubmit={stageInsert} />
    </div>
  )
}

/** Nothing is written until the operator has read the statement. `tend`
 *  commits one instruction at a time (C.10), so one instruction is exactly
 *  what this shows.
 *
 *  Anchored to the bottom of the window rather than dropped in above the
 *  grid: a bar that appears in the flow pushes the rows down, and the click
 *  already travelling towards a cell lands on "apply" instead. A write must
 *  never be something the layout can talk you into. */
function PendingWrite({ pending, onApply, onCancel, t }) {
  const { statements, error, done, busy } = pending
  return (
    <div className="fixed inset-x-0 bottom-0 z-40 p-3 sm:p-4" role="alertdialog">
      <div className="card animate-rise mx-auto max-w-3xl border-warn/40 p-3 shadow-pop">
        <p className="text-[12.5px] font-medium text-text">
          {t('data.pending', { n: statements.length })}
        </p>
        <div className="mt-1.5 max-h-[30vh] space-y-1 overflow-auto">
          {statements.map((sql, i) => (
            <pre key={i}
                 className={`overflow-x-auto rounded border px-2.5 py-2 font-mono text-[12px]
                             leading-relaxed
                             ${done > i
                               ? 'border-line bg-surface-2 text-text-3 line-through'
                               : 'border-line bg-surface-2 text-text-2'}`}>{sql}</pre>
          ))}
        </div>
        {error && (
          <div className="mt-2 space-y-2">
            <ErrorNote error={error} />
            {done > 0 && (
              <Note tone="warn">
                {t('data.partial', { done, total: pending.total })}
              </Note>
            )}
          </div>
        )}
        <div className="mt-3 flex items-center justify-end gap-2">
          <span className="mr-auto text-[11.5px] text-text-3">
            {t('data.commits', { n: statements.length })}
          </span>
          <button type="button" className="btn btn-sm" onClick={onCancel}>
            {error ? t('common.close') : t('common.cancel')}
          </button>
          {!error && (
            <button type="button" className="btn btn-sm btn-primary" disabled={busy}
                    onClick={onApply}>
              {busy ? t('common.working') : t('data.apply')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function Structure({ table, t }) {
  if (!table) return <Empty icon={Columns}>{t('data.no_table')}</Empty>
  return (
    <div className="space-y-4">
      <Table head={['#', t('data.column'), t('common.type'), t('data.nullable'),
                    t('data.default')]}>
        {table.columns.map((c, i) => (
          <tr key={c.name}>
            <Td className="w-8 font-mono text-[11.5px] text-text-3">{i + 1}</Td>
            <Td className="font-mono text-[12.5px] text-text">
              {c.name}
              {c.pk && <Badge tone="accent" className="ml-2">PK</Badge>}
            </Td>
            <Td className="font-mono text-[12px] uppercase text-text-2">{c.type || '—'}</Td>
            <Td className="text-[12px] text-text-2">
              {c.notnull ? t('data.not_null') : t('data.null_ok')}
            </Td>
            <Td className="font-mono text-[12px] text-text-3">{c.dflt || '—'}</Td>
          </tr>
        ))}
      </Table>

      {table.ddl && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="label !mb-0">{t('data.ddl')}</span>
            <CopyButton value={table.ddl} label={t('common.copy')} />
          </div>
          <Code max="14rem">{table.ddl}</Code>
        </div>
      )}

      <Note>{t('data.structure_note')}</Note>
    </div>
  )
}

/** The new-row form takes the column's word for what it holds: a number
 *  column refuses letters as they are typed, a date column opens the
 *  browser's picker and yields the format SQLite sorts on. Reaching `tend`
 *  with a value the column cannot store should not be possible from here. */
function InsertRow({ open, columns = [], onClose, onSubmit, t }) {
  const [values, setValues] = useState({})
  useEffect(() => { if (open) setValues({}) }, [open])
  if (!open || !columns.length) return null

  // A blank NOT NULL column is only a problem once a row is actually being
  // composed — flagging every one of them the moment the form opens would be
  // shouting at someone who has not typed anything yet.
  const started = Object.values(values).some((v) => String(v) !== '')
  const problem = (c) => {
    const v = values[c.name] ?? ''
    if (v === '') return started && c.notnull ? t('data.needs_value') : null
    return isComplete(c.kind, v) ? null : t(`data.needs_${c.kind}`)
  }
  const errors = columns.map(problem)
  const ready = started && errors.every((e) => !e)

  return (
    <Modal open wide onClose={onClose} title={t('data.insert')}
           subtitle={t('data.insert_hint')}
           footer={<>
             <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
             <button className="btn btn-primary" disabled={!ready}
                     onClick={() => onSubmit(values)}>{t('data.insert_review')}</button>
           </>}>
      <div className="grid gap-3 sm:grid-cols-2">
        {columns.map((c, i) => (
          <label key={c.name} className="block">
            <span className="label">
              {c.name}
              <span className="ml-1.5 font-mono normal-case tracking-normal text-text-3">
                {c.type || c.kind.toUpperCase()}{c.notnull ? ' · NOT NULL' : ''}
              </span>
            </span>
            <TypedInput kind={c.kind} value={values[c.name] ?? ''}
                        placeholder={c.notnull ? '' : 'NULL'}
                        onChange={(next) => setValues((v) => ({ ...v, [c.name]: next }))}
                        className={`field font-mono text-[12.5px]
                                    ${errors[i] ? '!border-danger' : ''}`} />
            {errors[i] && (
              <span className="mt-1 block text-[11.5px] text-danger">{errors[i]}</span>
            )}
          </label>
        ))}
      </div>
    </Modal>
  )
}
