// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The Data console — a database client over the forest's datasets.
 *
 * Everything here is the primitives the spec already defines. Reading is
 * `query` (C.5, read-only, single statement); writing is `tend` (C.10, one
 * INSERT/UPDATE/DELETE at a time, WHERE mandatory, its own git commit);
 * making one is `plant` with a declarative schema (C.7.1); bringing one in
 * is the J.8 ingest surface. The console never gets a private channel: the
 * SQL it builds is the SQL it shows, and an operator without the `tend`
 * capability simply browses.
 *
 * Structure is deliberately read-only. `tend` forbids DDL forever (spec
 * v0.21 C.10) and schema evolution is not the query surface's job — a table
 * is born through `plant`'s declarative schema (C.7.1) and changed by
 * rebuilding it, so offering an "add column" button here would only be a
 * button that always fails.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { noteJob } from '../board.js'
import { useRouteState } from '../router.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Code, CodeArea, CopyButton, Empty, ErrorNote, Field, Modal,
  Note, Select, Skeleton, Spinner, Table, Tabs, Td, TextArea,
} from '../design/ui.jsx'
import { Highlighted } from '../design/highlight.jsx'
import {
  ChevronLeft, ChevronRight, Code2, Columns, Data as DataIcon, Download,
  Grid as GridIcon, Ingest as ImportIcon, Pencil, Play, Plus, Refresh, Save,
  Trash, X,
} from '../design/icons.jsx'
import { Grid, TypedInput, fieldKind, isComplete } from '../design/grid.jsx'
import {
  NeedsCapability, branchOf, has, rootsOf, slugOf, useAsync, useForestTree,
} from './shared.jsx'

const PAGE_SIZES = [25, 50, 100, 500]

/* G.2 says which converters exist; this is the subset that becomes a
 * dataset. Everything here goes up as bytes — `.csv` and `.json` are text,
 * but the wire contract takes either and one rule is easier to trust than
 * two. */
const IMPORT_ACCEPT = '.db,.sqlite,.sqlite3,.csv,.json,.xls,.xlsx'
const IMPORTABLE = /\.(db|sqlite|sqlite3|csv|json|xlsx?)$/i
const IMPORT_MAX_BYTES = 100 * 1024 * 1024

/* C.7.1 rule 1: the four types a declared column may have, and the limits
 * the engine will enforce anyway. Shown here so the form refuses before the
 * round trip does — never instead of it. */
/* C.2.1: the heading is a contract token — `look` reads this exact section
 * back out, so the console may not localise it or spell it differently. */
const NOTES_SECTION = 'Notes'

const COLUMN_TYPES = ['TEXT', 'INTEGER', 'REAL', 'BLOB']
const MAX_TABLES = 10
const MAX_COLUMNS = 50
const SQL_NAME = /^[a-z_][a-z0-9_]*$/

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
  // What is being looked at goes in the address (J.5.8) — the dataset, the
  // table, the tab. How far into it does not: paging, sorting and filtering
  // are how a table is read, not which table it is.
  const [id, setId] = useRouteState('dataset', '', { push: true })
  const [table, setTable] = useRouteState('table', '', { push: true })
  // Every tab value MUST be in the allow list, or clicking it writes an
  // address the validator rejects and the console snaps back (J.5.8).
  const [tab, setTab] = useRouteState('tab', 'rows',
                                      { allow: ['rows', 'structure', 'sql', 'notes'] })
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
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)

  const mayWrite = has(grant, 'tend')
  const mayPlant = has(grant, 'write')   // J.3: `plant` is the write row
  const mayIngest = has(grant, 'ingest')

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
  //
  // A table named by the address and no longer in the dataset is corrected
  // here rather than left describing a page that is not there — by
  // replacement, because nobody navigated to it (J.5.8).
  useEffect(() => {
    // Before the dataset has answered there is nothing to correct against,
    // and correcting anyway would drop the table the address arrived with.
    if (!meta.data) return
    const names = (meta.data.tables || []).map((x) => x.name)
    if (!names.length) { setTable('', { push: false }); return }
    if (!names.includes(table)) {
      setTable(names[0], { push: false })
      setPage(0); setSort(null); setFilters({})
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

  /* Opening and leaving a dataset (J.5.10). Both are navigations, so both
   * push: the address is where the console is (J.5.8), and Back is how an
   * operator returns to the list they came from. */
  function connect(next) {
    setId(next); setPage(0); setSort(null); setFilters({})
    setPending(null); setWritten(null); setFree({}); setDraft(EMPTY_DRAFT)
  }

  /* Leaving MUST NOT drop a pending write. An unapplied draft is work the
   * operator can still see; discarding it silently because they clicked
   * "disconnect" would be the console spending it for them. */
  function disconnect() {
    if (changes > 0) return
    setId(''); setTable(''); setPage(0); setSort(null); setFilters({})
    setPending(null); setWritten(null); setFree({}); setDraft(EMPTY_DRAFT)
  }

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

  const connected = (found.data || []).find((n) => n.id === id) || null

  return (
    <div className="grid gap-4 lg:grid-cols-[290px_1fr]">
      {/* J.5.10: while a dataset is selected the picker IS that dataset. The
          list is a browse surface and the selection is a working surface,
          and keeping eleven other databases one mis-click from the query
          being edited is inviting the mis-click. */}
      <Card title={id ? t('data.connected') : t('data.pick')} icon={DataIcon}
            bodyClass="p-2"
            actions={id ? (
              <button className="btn btn-sm" onClick={disconnect} disabled={changes > 0}
                      title={changes > 0 ? t('data.disconnect_blocked') : undefined}>
                <ChevronLeft size={14} /> {t('data.disconnect')}
              </button>
            ) : (
              <button className="btn btn-sm btn-ghost" onClick={found.reload}
                      title={t('common.refresh')}><Refresh size={14} /></button>
            )}>
        {/* The connected panel comes first on purpose: it is built from
            `look`, not from the list, so an address that arrives with a
            dataset already in it must not wait on a scan — or worse, show
            the list's error where the dataset was asked for. */}
        {id ? (
          <div className="space-y-2 p-1.5">
            <div>
              <span className="nodeid block break-all">{id}</span>
              <span className="mt-1 block text-[12px] leading-relaxed text-text-3">
                {connected?.summary || meta.data?.summary}
              </span>
            </div>
            {changes > 0 && <Note tone="warn">{t('data.disconnect_blocked')}</Note>}
            <ul className="space-y-0.5 border-t border-line pt-2">
              {meta.busy && <li className="px-2 py-1"><Skeleton rows={2} /></li>}
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
          </div>
        ) : found.busy ? <div className="p-3"><Skeleton rows={3} /></div>
          : found.error ? <div className="p-3"><ErrorNote error={found.error} /></div>
          : (found.data || []).length === 0 ? (
          <Empty icon={DataIcon}>{t('data.none')}</Empty>
        ) : (
          <ul className="space-y-0.5">
            {found.data.map((n) => (
              <li key={n.id}>
                <button onClick={() => connect(n.id)}
                        className="w-full rounded-lg px-2.5 py-2 text-left transition
                                   hover:bg-surface-2">
                  <span className="nodeid block truncate">{n.id}</span>
                  <span className="mt-0.5 block line-clamp-2 text-[12px] text-text-3">
                    {n.summary}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {(mayPlant || mayIngest) && (
          <div className="mt-2 flex flex-wrap gap-2 border-t border-line px-1.5 pt-2">
            {mayPlant && (
              <button className="btn btn-sm" onClick={() => setCreating(true)}>
                <Plus size={14} /> {t('data.new')}
              </button>
            )}
            {mayIngest && (
              <button className="btn btn-sm" onClick={() => setImporting(true)}>
                <ImportIcon size={14} /> {t('data.import')}
              </button>
            )}
          </div>
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
                { value: 'rows', label: t('data.tab_rows'), icon: GridIcon },
                { value: 'structure', label: t('data.tab_structure'), icon: Columns },
                { value: 'sql', label: t('data.tab_sql'), icon: Code2 },
                { value: 'notes', label: t('data.tab_notes'), icon: Pencil },
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

              {tab === 'notes' && (
                <Notes forest={forest} id={id} mayWrite={has(grant, 'write')}
                       t={t} onSaved={meta.reload} />
              )}

              {tab === 'sql' && (
                <form onSubmit={runFree} className="space-y-3">
                  <label className="block">
                    <span className="label">{t('data.sql')}</span>
                    <CodeArea lang="sql" value={sql} minHeight="8.5rem"
                              aria-label={t('data.sql')}
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

      {creating && (
        <NewDataset forest={forest} grant={grant} t={t}
                    onClose={() => setCreating(false)}
                    onCreated={(newId) => { found.reload(); connect(newId) }} />
      )}
      {importing && (
        <ImportDataset forest={forest} grant={grant} t={t}
                       onClose={() => setImporting(false)}
                       onQueued={() => found.reload()} />
      )}
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
                               : 'border-line bg-surface-2 text-text-2'}`}>
              {done > i ? sql : <Highlighted text={sql} lang="sql" />}
            </pre>
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
          <Code max="14rem" lang="sql">{table.ddl}</Code>
        </div>
      )}

      <Note>{t('data.structure_note')}</Note>
    </div>
  )
}

/** What a person teaches the agent about this data (spec C.2.1).
 *
 *  Everything else this console shows about a dataset was inferred: the
 *  structure came from the file, the sample from its first rows, the
 *  summary from those. What none of it can supply is meaning — that this
 *  column is USD and that one BRL, that `status` is a one-letter code,
 *  which join answers the question people actually ask. An agent without
 *  that writes SQL that runs and answers wrongly, which is the worst
 *  failure available to it.
 *
 *  The section is read with `pick`, never from `look`: the digest clips
 *  notes to their budget, and editing a clipped copy would save the clip.
 *  It is written with ONE `graft` — `append_section` the first time,
 *  `replace_section` after — so the teaching is part of the node, commit
 *  and attribution included, and the Gardener will not touch it (G.2.3
 *  rule 4 rewrites the two generated sections and only those). */
function Notes({ forest, id, mayWrite, onSaved, t }) {
  const [text, setText] = useState(null)
  const [exists, setExists] = useState(false)
  const [state, setState] = useState({})

  const loaded = useAsync(async () => {
    try {
      const r = await api.call(forest, 'pick', { id, section: NOTES_SECTION })
      // `pick` returns the section with its heading; the heading is the
      // contract, not the content, so it never reaches the editor.
      return { body: (r.body || '').split('\n').slice(1).join('\n').trim(),
               exists: true }
    } catch (error) {
      if (error?.code === 'E_NOT_FOUND') return { body: '', exists: false }
      throw error
    }
  }, [forest, id])

  useEffect(() => {
    if (!loaded.data) return
    setText(loaded.data.body)
    setExists(loaded.data.exists)
    setState({})
  }, [loaded.data])

  const value = text ?? ''
  const dirty = loaded.data && value !== loaded.data.body

  async function save() {
    setState({ busy: true })
    const body = value.trim()
    try {
      await api.call(forest, 'graft', {
        id,
        patch: exists
          ? { replace_section: { header: NOTES_SECTION, body } }
          : { append_section: { header: NOTES_SECTION, body } },
      })
      setState({ saved: true })
      setExists(true)
      loaded.reload()
      onSaved?.()
    } catch (error) { setState({ busy: false, error }) }
  }

  if (loaded.busy) return <Spinner label={t('common.loading')} />
  if (loaded.error) return <ErrorNote error={loaded.error} onRetry={loaded.reload} />

  return (
    <div className="space-y-3">
      <Note>{t('data.notes_hint')}</Note>
      <label className="block">
        <span className="label">{t('data.tab_notes')}</span>
        <CodeArea lang="markdown" value={value} minHeight="14rem"
                  aria-label={t('data.tab_notes')} readOnly={!mayWrite}
                  placeholder={t('data.notes_placeholder')}
                  onChange={(e) => { setText(e.target.value); setState({}) }} />
      </label>

      {state.error && <ErrorNote error={state.error} />}
      {state.saved && !dirty && <Note>{t('data.notes_saved')}</Note>}

      <div className="flex items-center justify-end gap-2">
        <span className="mr-auto text-[11.5px] text-text-3">
          {t('data.notes_commit')}
        </span>
        {dirty && (
          <button className="btn btn-sm" onClick={() => setText(loaded.data.body)}>
            {t('data.discard')}
          </button>
        )}
        <button className="btn btn-primary btn-sm" onClick={save}
                disabled={!mayWrite || !dirty || state.busy}>
          <Save size={14} />
          {state.busy ? t('common.working') : t('data.notes_save')}
        </button>
      </div>
      {!mayWrite && <Note tone="warn">{t('data.notes_read_only')}</Note>}
    </div>
  )
}

/* -- making one, and bringing one in (spec J.5.10) ----------------------- */

const EMPTY_TABLE = () => ({ name: '', columns: [{ name: '', type: 'TEXT', pk: false }] })

/** A dataset is born through ONE `plant` with a declarative schema (C.7.1).
 *
 *  The console never writes DDL and never offers a box to type it into:
 *  table names, column names, the four types and the primary key are
 *  fields, and the `CREATE TABLE` is the Vine's. Everything that makes a
 *  node a node — the id under its parent, the entry in the parent index,
 *  the commit, the audit row — comes for free from the primitive, exactly
 *  as it does for an agent.
 *
 *  Ids are composed, never typed: the leaf is slugged from the name and
 *  shown before the call, because no primitive relocates a node and a
 *  mistake here is permanent. */
function NewDataset({ forest, grant, onClose, onCreated, t }) {
  const [parent, setParent] = useState(rootsOf(grant)[0] || '_index')
  const [name, setName] = useState('')
  const [summary, setSummary] = useState('')
  const [tables, setTables] = useState([EMPTY_TABLE()])
  const [state, setState] = useState({})

  const tree = useForestTree(forest, grant, api.call)
  const parents = tree.data?.branches || rootsOf(grant).map((r) => ({ id: r }))

  const slug = slugOf(name)
  const under = branchOf(parent || '_index')
  const id = slug ? (under ? `${under}/${slug}` : slug) : null
  // The engine owns the A.4 verdict; this is the budget shown while typing.
  const tokens = Math.ceil(summary.trim().split(/\s+/).filter(Boolean).length * 1.3)

  const patch = (i, next) =>
    setTables((ts) => ts.map((tb, j) => (j === i ? { ...tb, ...next } : tb)))
  const patchColumn = (i, j, next) => patch(i, {
    columns: tables[i].columns.map((c, k) => (k === j ? { ...c, ...next } : c)),
  })

  /* What the engine will refuse, said before the round trip — never
   * instead of it. C.7.1 validates every one of these again, and the two
   * can only ever disagree in the direction of an extra refusal here. */
  const problems = []
  const names = tables.map((tb) => tb.name.trim())
  tables.forEach((tb, i) => {
    if (!SQL_NAME.test(names[i])) problems.push(t('data.bad_table', { n: i + 1 }))
    else if (names.indexOf(names[i]) !== i) problems.push(t('data.dup_table', { name: names[i] }))
    const cols = tb.columns.map((c) => c.name.trim())
    if (!cols.length) problems.push(t('data.no_columns', { name: names[i] || i + 1 }))
    cols.forEach((c, j) => {
      if (!SQL_NAME.test(c)) problems.push(t('data.bad_column', { n: j + 1, table: names[i] }))
      else if (cols.indexOf(c) !== j) problems.push(t('data.dup_column', { name: c }))
    })
  })
  const ready = id && summary.trim() && !problems.length && !state.busy

  async function submit(e) {
    e.preventDefault()
    if (!ready) return
    setState({ busy: true })
    const schema = {}
    for (const tb of tables) {
      const columns = {}
      for (const c of tb.columns) columns[c.name.trim()] = c.type
      const pk = tb.columns.filter((c) => c.pk).map((c) => c.name.trim())
      schema[tb.name.trim()] = pk.length ? { columns, primary_key: pk } : { columns }
    }
    try {
      // C.7 takes ONE object: the request body is the call's keyword
      // arguments, so a flat passport would reach `plant(id=…)` and fail.
      await api.call(forest, 'plant', {
        node: {
          id,
          type: 'dataset',
          parent: parent || '_index',
          title: name.trim(),
          summary: summary.trim(),
          source: 'manual',
          schema,
        },
      })
      onCreated?.(id)
      onClose?.()
    } catch (error) { setState({ busy: false, error }) }
  }

  return (
    <Modal open wide onClose={onClose} title={t('data.new')} subtitle={t('data.new_sub')}
           footer={<>
             <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
             <button className="btn btn-primary" disabled={!ready} onClick={submit}>
               <Plus size={14} />
               {state.busy ? t('data.creating') : t('data.create')}
             </button>
           </>}>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label={t('data.parent')} value={parent} hint={t('data.parent_hint')}
                  onChange={(e) => setParent(e.target.value)}>
            {parents.map((p) => (
              <option key={p.id} value={p.id}>{branchOf(p.id) || t('branch.root')}</option>
            ))}
          </Select>
          <Field label={t('data.name')} value={name} required autoFocus
                 placeholder={t('data.name_placeholder')}
                 onChange={(e) => setName(e.target.value)}
                 hint={id ? t('data.will_be', { id }) : t('data.name_hint')} />
        </div>

        <Field as={TextArea} label={t('data.summary')} value={summary} required rows={2}
               placeholder={t('data.summary_placeholder')}
               onChange={(e) => setSummary(e.target.value)}
               hint={t('branch.summary_hint', { n: tokens })}
               error={tokens > 60 ? t('branch.summary_long') : undefined} />

        <div className="space-y-3">
          <span className="label !mb-0">{t('data.tables')}</span>
          {tables.map((tb, i) => (
            <div key={i} className="rounded-lg border border-line bg-surface-2 p-3">
              <div className="flex items-center gap-2">
                <input className="field font-mono text-[12.5px]" value={tb.name}
                       placeholder={t('data.table_name')} aria-label={t('data.table_name')}
                       onChange={(e) => patch(i, { name: e.target.value })} />
                {tables.length > 1 && (
                  <button type="button" className="btn btn-sm btn-ghost"
                          aria-label={t('data.remove_table')}
                          onClick={() => setTables((ts) => ts.filter((_, j) => j !== i))}>
                    <Trash size={14} />
                  </button>
                )}
              </div>

              <div className="mt-2 space-y-1.5">
                {tb.columns.map((c, j) => (
                  <div key={j} className="flex items-center gap-2">
                    <input className="field font-mono text-[12.5px]" value={c.name}
                           placeholder={t('data.column_name')}
                           aria-label={t('data.column_name')}
                           onChange={(e) => patchColumn(i, j, { name: e.target.value })} />
                    <select className="field !w-auto font-mono text-[12.5px]" value={c.type}
                            aria-label={t('common.type')}
                            onChange={(e) => patchColumn(i, j, { type: e.target.value })}>
                      {COLUMN_TYPES.map((ty) => <option key={ty} value={ty}>{ty}</option>)}
                    </select>
                    <label className="flex shrink-0 items-center gap-1.5 text-[12px] text-text-3">
                      <input type="checkbox" checked={c.pk}
                             onChange={(e) => patchColumn(i, j, { pk: e.target.checked })} />
                      PK
                    </label>
                    {tb.columns.length > 1 && (
                      <button type="button" className="btn btn-sm btn-ghost"
                              aria-label={t('data.remove_column')}
                              onClick={() => patch(i, {
                                columns: tb.columns.filter((_, k) => k !== j),
                              })}>
                        <X size={13} />
                      </button>
                    )}
                  </div>
                ))}
                <button type="button" className="btn btn-sm"
                        disabled={tb.columns.length >= MAX_COLUMNS}
                        onClick={() => patch(i, {
                          columns: [...tb.columns, { name: '', type: 'TEXT', pk: false }],
                        })}>
                  <Plus size={13} /> {t('data.add_column')}
                </button>
              </div>
            </div>
          ))}
          <button type="button" className="btn btn-sm" disabled={tables.length >= MAX_TABLES}
                  onClick={() => setTables((ts) => [...ts, EMPTY_TABLE()])}>
            <Plus size={13} /> {t('data.add_table')}
          </button>
        </div>

        {problems.length > 0 && (
          <Note tone="warn">{problems[0]}</Note>
        )}
        <Note>{t('data.new_note')}</Note>
        {state.error && <ErrorNote error={state.error} />}
      </form>
    </Modal>
  )
}

/** Importing goes through J.8's ingest surface and nowhere else.
 *
 *  The console does not parse the file, does not infer a schema and does
 *  not plant: an importer that understood `.xlsx` would be a converter
 *  living where nobody can extend it, and it would disagree with the
 *  Gardener the first time either of them changed. What it sends is bytes
 *  and a destination; what comes back is a job (J.9), announced by the
 *  pill every console carries. */
function ImportDataset({ forest, grant, onClose, onQueued, t }) {
  // J.8 names a destination by BRANCH, not by its index node — the same
  // value the ingest console sends, because two consoles disagreeing about
  // the shape of `dest` is one of them silently planting at the root.
  const [dest, setDest] = useState(branchOf(rootsOf(grant)[0] || '_index'))
  const [files, setFiles] = useState([])
  const [refused, setRefused] = useState([])
  const [state, setState] = useState({})
  const picker = useRef(null)

  const tree = useForestTree(forest, grant, api.call)
  const parents = tree.data?.branches || rootsOf(grant).map((r) => ({ id: r }))

  async function take(list) {
    const picked = []
    const bad = []
    setState({ reading: true })
    for (const file of Array.from(list || [])) {
      if (!IMPORTABLE.test(file.name)) {
        bad.push({ name: file.name, why: t('data.import_type') })
        continue
      }
      if (file.size > IMPORT_MAX_BYTES) {
        bad.push({ name: file.name, why: t('data.import_size') })
        continue
      }
      picked.push({ name: file.name, b64: await toBase64(await file.arrayBuffer()),
                    bytes: file.size })
    }
    setState({})
    setFiles((prev) => {
      const byName = new Map(prev.map((f) => [f.name, f]))
      for (const f of picked) byName.set(f.name, f)
      return [...byName.values()]
    })
    setRefused(bad)
  }

  async function submit(e) {
    e.preventDefault()
    if (!files.length) return
    setState({ busy: true })
    try {
      // `bytes` is display-only; the wire contract is J.8's {name, text|b64}.
      const r = await api.ingest(forest, {
        mode: 'upload',
        files: files.map(({ bytes, ...rest }) => rest),
        dest: dest || undefined,
      })
      // J.9.3: the pill reads the job board, so the batch this console
      // started has to be put on it — otherwise the announcement waits for
      // the next poll and the operator watches nothing happen.
      noteJob(forest, r.job)
      setState({ job: r.job || r })
      onQueued?.()
    } catch (error) { setState({ busy: false, error }) }
  }

  const total = files.reduce((n, f) => n + f.bytes, 0)

  return (
    <Modal open onClose={onClose} title={t('data.import')} subtitle={t('data.import_sub')}
           footer={<>
             <button className="btn" onClick={onClose}>
               {state.job ? t('common.close') : t('common.cancel')}
             </button>
             {!state.job && (
               <button className="btn btn-primary" onClick={submit}
                       disabled={!files.length || state.busy || state.reading}>
                 <ImportIcon size={14} />
                 {state.busy ? t('common.working') : t('data.import_start')}
               </button>
             )}
           </>}>
      <form onSubmit={submit} className="space-y-4">
        <Select label={t('data.dest')} value={dest} hint={t('data.dest_hint')}
                onChange={(e) => setDest(e.target.value)}>
          {/* J.8: a principal whose scope is not the whole forest MUST name
              a destination, so the root is not theirs to choose. */}
          {rootsOf(grant).includes('_index')
            && <option value="">{t('ingest.dest_root')}</option>}
          {parents.map((p) => {
            const name = branchOf(p.id)
            return name ? <option key={p.id} value={name}>{name}</option> : null
          })}
        </Select>

        <div>
          <input ref={picker} type="file" multiple accept={IMPORT_ACCEPT} className="hidden"
                 onChange={(e) => { take(e.target.files); e.target.value = '' }} />
          <button type="button" className="btn w-full" onClick={() => picker.current?.click()}>
            <Plus size={14} /> {t('data.import_pick')}
          </button>
          <p className="mt-1.5 text-[11.5px] text-text-3">{t('data.import_formats')}</p>
        </div>

        {state.reading && <Spinner label={t('common.working')} />}

        {files.length > 0 && (
          <ul className="space-y-1">
            {files.map((f) => (
              <li key={f.name}
                  className="flex items-center gap-2 rounded-md border border-line
                             bg-surface-2 px-2.5 py-1.5">
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-2">
                  {f.name}
                </span>
                <span className="shrink-0 text-[11px] tabular-nums text-text-3">
                  {Math.max(1, Math.round(f.bytes / 1024))} KB
                </span>
                <button type="button" className="btn btn-sm btn-ghost"
                        aria-label={t('common.cancel')}
                        onClick={() => setFiles((fs) => fs.filter((x) => x.name !== f.name))}>
                  <X size={13} />
                </button>
              </li>
            ))}
            <li className="pt-1 text-[11.5px] text-text-3">
              {t('data.import_total', { n: files.length,
                                        kb: Math.max(1, Math.round(total / 1024)) })}
            </li>
          </ul>
        )}

        {refused.length > 0 && (
          <Note tone="warn">
            {refused.map((r) => `${r.name} — ${r.why}`).join('; ')}
          </Note>
        )}

        {state.job
          ? <Note>{t('data.import_queued')}</Note>
          : <Note>{t('data.import_note')}</Note>}
        {state.error && <ErrorNote error={state.error} />}
      </form>
    </Modal>
  )
}

/* Chunked so a large upload does not blow the argument limit of
 * String.fromCharCode with one spread of the whole array. */
async function toBase64(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i += 8192) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192))
  }
  return btoa(binary)
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
