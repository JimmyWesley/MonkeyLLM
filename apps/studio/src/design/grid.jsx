// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The data grid — the one shape in the vocabulary that behaves like a
 * database client rather than a report: frozen header, frozen row numbers,
 * per-column filters, type-aware alignment and in-place editing.
 *
 * It renders and it reports; it never talks to the engine. An edit leaves
 * here as `(rid, column, text)` and the view turns it into the single
 * statement `tend` accepts (spec C.10). That split is deliberate: the grid
 * cannot write, so the SQL is always assembled — and shown — somewhere the
 * operator can read it before anything is committed.
 */
import { useEffect, useRef, useState } from 'react'
import { ChevronDown, Trash, Undo } from './icons.jsx'

/** SQLite type affinity, the same rule the engine's own storage uses: a
 *  declared type containing INT/REAL/FLOA/DOUB/NUM/DEC is a number, and
 *  numbers belong on the right. */
export const NUMERIC_TYPE = /INT|REAL|FLOA|DOUB|NUM|DEC/i

const INTEGER_TYPE = /INT/i
const DATE_TYPE = /^DATE$/i
const DATETIME_TYPE = /DATETIME|TIMESTAMP/i
const TIME_TYPE = /^TIME$/i

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/
const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$/
const ISO_TIME = /^\d{2}:\d{2}(:\d{2})?$/

/** What a column accepts.
 *
 *  The declared type decides first. When it says nothing useful — SQLite has
 *  no date type, so dates live in TEXT columns — the values already on screen
 *  decide instead. Shape, never column names: keying off the word "date"
 *  would work in one language and quietly fail in every other, and the engine
 *  is deliberately blind to what a forest is about. */
export function fieldKind(column, samples = []) {
  const type = column?.type || ''
  if (DATETIME_TYPE.test(type)) return 'datetime'
  if (DATE_TYPE.test(type)) return 'date'
  if (TIME_TYPE.test(type)) return 'time'
  if (INTEGER_TYPE.test(type)) return 'integer'
  if (NUMERIC_TYPE.test(type)) return 'number'

  const seen = samples.filter((v) => v !== null && v !== undefined && v !== '')
  if (seen.length >= 3) {
    if (seen.every((v) => ISO_DATE.test(String(v)))) return 'date'
    if (seen.every((v) => ISO_DATETIME.test(String(v)))) return 'datetime'
    if (seen.every((v) => ISO_TIME.test(String(v)))) return 'time'
  }
  return 'text'
}

// Permissive while typing (a lone `-` is a number on its way), strict when
// the value is about to become SQL.
const TYPING = { integer: /^-?\d*$/, number: /^-?\d*\.?\d*([eE][-+]?\d*)?$/ }

/** Does this text still belong in this kind of column? Empty always does:
 *  empty means NULL, and NULL is a value. */
export function acceptsWhileTyping(kind, text) {
  return !TYPING[kind] || TYPING[kind].test(text)
}

export function isComplete(kind, text) {
  if (text === '') return true
  if (kind === 'integer' || kind === 'number') return Number.isFinite(Number(text))
  if (kind === 'date') return ISO_DATE.test(text)
  if (kind === 'time') return ISO_TIME.test(text)
  if (kind === 'datetime') return ISO_DATETIME.test(text)
  return true
}

const INPUT_PROPS = {
  date: { type: 'date' },
  datetime: { type: 'datetime-local', step: 1 },
  time: { type: 'time', step: 1 },
  integer: { type: 'text', inputMode: 'numeric' },
  number: { type: 'text', inputMode: 'decimal' },
}

/** A box that can only hold what its column stores. Numbers refuse letters as
 *  they are typed; dates and times get the browser's own picker, so the value
 *  is already in the format SQLite compares and sorts on. */
export function TypedInput({ kind = 'text', value, onChange, className = '', ...rest }) {
  const native = INPUT_PROPS[kind] || { type: 'text' }
  // `datetime-local` only accepts the T form; SQLite's own literals use a
  // space. Translating at the edge keeps both sides in their own convention.
  const shown = kind === 'datetime' ? String(value).replace(' ', 'T') : value
  return (
    <input {...native} {...rest} value={shown}
           onChange={(e) => {
             const next = kind === 'datetime' ? e.target.value.replace('T', ' ') : e.target.value
             if (acceptsWhileTyping(kind, next)) onChange(next)
           }}
           className={className} />
  )
}

const NULL_CELL = (
  <span className="italic text-text-3/70">NULL</span>
)

export function Grid({
  columns = [],
  rows = [],
  offset = 0,
  sort = null,
  onSort,
  filters = null,
  onFilter,
  onEdit,
  onDelete,
  edits = null,        // {rowKey: {column: text}} — staged, not written
  deleted = null,      // Set of row keys staged for removal
  maxHeight = '58vh',
  emptyLabel,
}) {
  const [editing, setEditing] = useState(null)   // {rid, col}

  // A refetch replaces the rows under an open editor; committing then would
  // write the old draft into whatever row now sits there.
  useEffect(() => { setEditing(null) }, [rows])

  if (!columns.length) return null

  // The filter row pins under the header, so the header's height is fixed
  // rather than content-derived: `top-[34px]` has to match something exact.
  const head = 'sticky top-0 z-20 h-[34px] bg-surface border-b border-line'
  const numbered = 'sticky left-0 bg-surface border-r border-line'
  const under = 'sticky top-[34px] border-b border-line bg-surface'

  return (
    <div className="overflow-auto rounded-lg border border-line"
         style={{ maxHeight }}>
      <table className="w-full border-separate border-spacing-0 text-[12.5px]">
        <thead>
          <tr>
            <th className={`${head} ${numbered} z-30 w-10 px-2 py-2 text-right
                            text-[10.5px] font-medium text-text-3`}>#</th>
            {columns.map((c) => {
              const active = sort?.col === c.name
              return (
                <th key={c.name}
                    className={`${head} whitespace-nowrap px-2.5 py-1.5 text-left
                                ${onSort ? 'cursor-pointer hover:bg-surface-2' : ''}`}
                    onClick={() => onSort?.(c.name)}>
                  <span className="flex items-center gap-1.5">
                    <span className={`font-semibold ${active ? 'text-accent' : 'text-text'}`}>
                      {c.name}
                    </span>
                    {c.pk && (
                      <span className="rounded bg-accent-soft px-1 text-[9.5px]
                                       font-semibold uppercase text-accent">pk</span>
                    )}
                    {c.type && (
                      <span className="font-mono text-[10px] uppercase text-text-3">
                        {c.type}
                      </span>
                    )}
                    {active && (
                      <ChevronDown size={12}
                                   className={`text-accent ${sort.dir === 'desc' ? '' : 'rotate-180'}`} />
                    )}
                  </span>
                </th>
              )
            })}
            {onDelete && <th className={`${head} w-8`} />}
          </tr>
          {filters && (
            <tr>
              <th className={`${under} ${numbered} z-30`} />
              {columns.map((c) => (
                <th key={c.name} className={`${under} z-20 px-1 py-1`}>
                  <input value={filters[c.name] || ''} placeholder="—"
                         aria-label={c.name}
                         onChange={(e) => onFilter?.(c.name, e.target.value)}
                         className="w-full min-w-[6rem] rounded border border-transparent
                                    bg-surface-2 px-1.5 py-1 font-mono text-[11.5px]
                                    text-text-2 outline-none placeholder:text-text-3/50
                                    focus:border-accent/40" />
                </th>
              ))}
              {onDelete && <th className={`${under} z-20`} />}
            </tr>
          )}
        </thead>

        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={columns.length + (onDelete ? 2 : 1)}
                  className="px-3 py-8 text-center text-[12.5px] text-text-3">
                {emptyLabel}
              </td>
            </tr>
          )}
          {rows.map((row, i) => {
            const key = String(row.rid)
            const staged = edits?.[key] || null
            const dropping = deleted?.has(row.rid)
            return (
            <tr key={row.rid ?? i}
                className={`group hover:bg-surface-2/60
                            ${dropping ? 'opacity-45 line-through' : ''}`}>
              <td className={`${numbered} px-2 py-1.5 text-right font-mono text-[11px]
                              group-hover:bg-surface-2
                              ${row.staged ? 'text-accent' : 'text-text-3'}`}>
                {row.staged ? '+' : offset + i + 1}
              </td>
              {columns.map((c, j) => {
                const stored = row.cells[j]
                const dirty = staged && staged[c.name] !== undefined
                const value = dirty ? staged[c.name] : stored
                const open = editing && editing.rid === row.rid && editing.col === c.name
                const editable = Boolean(onEdit) && row.rid !== null && row.rid !== undefined
                return (
                  <td key={c.name}
                      onDoubleClick={() => editable && setEditing({ rid: row.rid, col: c.name })}
                      className={`max-w-[22rem] border-b border-line px-2.5 py-1.5
                                  ${NUMERIC_TYPE.test(c.type || '') ? 'text-right tabular-nums' : ''}
                                  ${open ? 'p-0' : 'truncate'}
                                  ${dirty ? 'bg-accent-soft text-accent' : 'text-text-2'}
                                  ${editable ? 'cursor-cell' : ''} font-mono`}
                      title={open ? undefined
                        : dirty ? `${stored === null ? 'NULL' : stored} → ${value === '' ? 'NULL' : value}`
                        : (stored === null ? 'NULL' : String(stored))}>
                    {open
                      ? <CellEditor value={value} kind={c.kind}
                                    onCancel={() => setEditing(null)}
                                    onCommit={(next) => {
                                      setEditing(null)
                                      if (next !== (value === null ? '' : String(value))) {
                                        onEdit(row.rid, c.name, next, stored)
                                      }
                                    }} />
                      : value === null || ((dirty || row.staged) && value === '')
                        ? NULL_CELL : String(value)}
                  </td>
                )
              })}
              {onDelete && (
                <td className="border-b border-line px-1 py-1 text-right no-underline">
                  <button type="button"
                          aria-label={dropping ? 'keep row' : 'delete row'}
                          disabled={row.rid === null || row.rid === undefined}
                          onClick={() => onDelete(row.rid)}
                          className={`rounded p-1 transition focus:opacity-100
                                      group-hover:opacity-100 disabled:hidden
                                      ${dropping
                                        ? 'text-danger opacity-100'
                                        : 'text-text-3 opacity-0 hover:bg-danger-soft hover:text-danger'}`}>
                    {dropping ? <Undo size={13} /> : <Trash size={13} />}
                  </button>
                </td>
              )}
            </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Escape must not commit, and blur must — which is why the cancel path sets
 *  a flag the blur handler reads instead of racing it. A half-typed value
 *  (`-`, `2026-04`) is not an edit: it cancels rather than reaching `tend` to
 *  be rejected there. */
function CellEditor({ value, kind = 'text', onCommit, onCancel }) {
  const [draft, setDraft] = useState(value === null ? '' : String(value))
  const cancelled = useRef(false)
  const ok = isComplete(kind, draft)
  const finish = () => (ok ? onCommit(draft) : onCancel())
  return (
    <TypedInput autoFocus kind={kind} value={draft} onChange={setDraft}
                onFocus={(e) => {
                  // Date and time inputs have no text selection to make.
                  try { e.target.select() } catch { /* not selectable */ }
                }}
                onBlur={() => !cancelled.current && finish()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); finish() }
                  if (e.key === 'Escape') { cancelled.current = true; onCancel() }
                }}
                className={`w-full rounded border bg-surface px-2 py-1 font-mono
                            text-[12.5px] text-text outline-none
                            ${ok ? 'border-accent/60' : 'border-danger'}`} />
  )
}
