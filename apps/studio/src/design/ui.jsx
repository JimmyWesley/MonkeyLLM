// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The component vocabulary every console is built from.
 *
 * Deliberately small: nine consoles sharing eleven components is what makes
 * the interface feel like one product. A view that needs a shape not in here
 * should add it here rather than hand-roll a one-off — a second kind of card
 * is how a design system stops being one.
 */
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Alert, Check, ChevronDown, Copy, Info, Refresh, Search, X } from './icons.jsx'

export function Card({ title, subtitle, actions, icon: Icon, children,
                       className = '', bodyClass = 'p-5' }) {
  return (
    /* `min-w-0`: as a grid or flex item a card defaults to min-content width,
       so one wide child — a `<pre>` of JSON, a table — grew the track past
       the viewport and the whole page scrolled sideways, dragging the header
       and the tab bar off with it. The child's own `overflow-auto` cannot
       help while its parent is free to expand. */
    <section className={`card animate-rise min-w-0 ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b
                           border-line px-5 py-3.5">
          <div className="flex min-w-0 items-start gap-2.5">
            {Icon && (
              <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center
                               rounded-lg bg-accent-soft text-accent">
                <Icon size={16} />
              </span>
            )}
            <div className="min-w-0">
              {title && <h2 className="truncate text-[14.5px] font-semibold text-text">{title}</h2>}
              {subtitle && <p className="mt-0.5 text-[12.5px] leading-relaxed text-text-3">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  )
}

/** The dashboard tile: label, one number, a line of context, tinted glyph. */
export function Stat({ label, value, hint, icon: Icon, tone = 'accent' }) {
  const tint = tone === 'muted'
    ? 'bg-surface-2 text-text-3' : 'bg-accent-soft text-accent'
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-3">
        <span className="text-[12.5px] font-medium text-text-2">{label}</span>
        {Icon && (
          <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${tint}`}>
            <Icon size={16} />
          </span>
        )}
      </div>
      <div className="mt-2 text-[26px] font-semibold leading-none tracking-tight text-text">
        {value}
      </div>
      {hint && <p className="mt-1.5 text-[12px] text-text-3">{hint}</p>}
    </div>
  )
}

export function Field({ label, hint, error, className = '', as, children, ...props }) {
  const Tag = as || 'input'
  return (
    <label className={`block ${className}`}>
      {label && <span className="label">{label}</span>}
      <Tag className="field" {...props}>{children}</Tag>
      {hint && !error && <span className="mt-1 block text-[11.5px] text-text-3">{hint}</span>}
      {error && <span className="mt-1 block text-[11.5px] text-danger">{error}</span>}
    </label>
  )
}

export const TextArea = (props) => (
  <Field as="textarea" {...props} />
)

export function Select({ label, hint, children, className = '', ...props }) {
  return (
    <label className={`block ${className}`}>
      {label && <span className="label">{label}</span>}
      <div className="relative">
        <select className="field appearance-none" {...props}>{children}</select>
        <ChevronDown size={15} className="pointer-events-none absolute right-2.5
                                          top-1/2 -translate-y-1/2 text-text-3" />
      </div>
      {hint && <span className="mt-1 block text-[11.5px] text-text-3">{hint}</span>}
    </label>
  )
}

/** A text field that also offers what the server already knows.
 *
 *  Deliberately not a <select>: the value must stay free text, because a
 *  catalogue that under-reports (most gateways do) must not make a valid
 *  model unbindable. The list narrows the search; it never fences it.
 */
export function Combobox({ label, value, onChange, options = [], hint, placeholder,
                           busy, empty, required }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(null)   // null = showing the value
  const box = useRef(null)

  useEffect(() => {
    const away = (e) => { if (!box.current?.contains(e.target)) { setOpen(false); setQuery(null) } }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])

  const text = query ?? value ?? ''
  const needle = (query ?? '').toLowerCase()
  const shown = (needle
    ? options.filter((o) => o.value.toLowerCase().includes(needle)
                         || (o.meta || '').toLowerCase().includes(needle))
    : options).slice(0, 60)

  return (
    <label className="relative block" ref={box}>
      {label && <span className="label">{label}</span>}
      <div className="relative">
        <input
          className="field pr-8" value={text} placeholder={placeholder} required={required}
          onFocus={() => setOpen(true)}
          onChange={(e) => { setQuery(e.target.value); onChange(e.target.value); setOpen(true) }}
          onKeyDown={(e) => { if (e.key === 'Escape') { setOpen(false); setQuery(null) } }}
        />
        <ChevronDown size={15} className="pointer-events-none absolute right-2.5 top-1/2
                                          -translate-y-1/2 text-text-3" />
      </div>

      {open && (
        <div className="absolute left-0 right-0 top-full z-40 mt-1 max-h-64 overflow-y-auto
                        rounded-lg border border-line bg-surface py-1 shadow-pop">
          {busy ? <div className="px-3 py-2"><Spinner label="…" /></div>
            : shown.length === 0 ? (
              <p className="px-3 py-2 text-[12px] text-text-3">{empty}</p>
            ) : shown.map((o) => (
              <button key={o.value} type="button"
                      className={`flex w-full items-baseline justify-between gap-3 px-3 py-1.5
                                  text-left transition hover:bg-surface-2
                                  ${o.value === value ? 'text-accent' : 'text-text-2'}`}
                      onClick={() => { onChange(o.value); setQuery(null); setOpen(false) }}>
                <span className="truncate font-mono text-[12px]">{o.value}</span>
                {o.meta && (
                  <span className="shrink-0 text-[11px] tabular-nums text-text-3">{o.meta}</span>
                )}
              </button>
            ))}
        </div>
      )}
      {hint && <span className="mt-1 block text-[11.5px] text-text-3">{hint}</span>}
    </label>
  )
}

/** The box a checkbox lives in, so "selected" looks the same everywhere. */
function Box({ checked, mixed }) {
  return (
    <span aria-hidden="true"
          className={`mt-px grid h-[15px] w-[15px] shrink-0 place-items-center rounded
            border transition ${checked || mixed
              ? 'border-accent bg-accent text-accent-fg'
              : 'border-line-strong bg-surface'}`}>
      {mixed ? <span className="block h-[2px] w-[7px] rounded-full bg-accent-fg" />
        : checked ? <Check size={11} strokeWidth={3} /> : null}
    </span>
  )
}

/** Multi-selection over a bounded list: check what you want, or take all.
 *
 *  A <select multiple> is the shape the platform offers and the wrong one:
 *  it hides the selection behind scroll and loses it to a stray click. This
 *  keeps every choice visible as a checkbox, keeps the region a fixed height
 *  so twelve options look like the same control as three, and offers a
 *  filter once the list is long enough that scanning it stops being free.
 */
export function CheckList({
  label, hint, options = [], value = [], onChange,
  allLabel, filterPlaceholder, empty, filterFrom = 8, max = '13rem',
}) {
  const [query, setQuery] = useState('')
  const needle = query.trim().toLowerCase()
  const shown = needle
    ? options.filter((o) => `${o.value} ${o.label || ''}`.toLowerCase().includes(needle))
    : options

  const all = options.map((o) => o.value)
  const every = all.length > 0 && all.every((v) => value.includes(v))
  const some = !every && all.some((v) => value.includes(v))
  const toggle = (v) => onChange(value.includes(v)
    ? value.filter((x) => x !== v) : [...value, v])

  return (
    <div>
      {label && <span className="label">{label}</span>}
      <div className="overflow-hidden rounded-lg border border-line bg-surface-2">
        <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
          <button type="button" role="checkbox" aria-checked={every ? 'true' : some ? 'mixed' : 'false'}
                  disabled={all.length === 0} onClick={() => onChange(every ? [] : all)}
                  className="flex items-center gap-2 text-[12.5px] font-medium text-text
                             transition hover:text-accent disabled:opacity-40">
            <Box checked={every} mixed={some} />
            {allLabel}
          </button>
          <span className="shrink-0 text-[11.5px] tabular-nums text-text-3">
            {value.length}/{all.length}
          </span>
        </div>

        {options.length >= filterFrom && (
          <div className="relative border-b border-line">
            <Search size={14} className="pointer-events-none absolute left-3 top-1/2
                                         -translate-y-1/2 text-text-3" />
            <input value={query} onChange={(e) => setQuery(e.target.value)}
                   placeholder={filterPlaceholder}
                   className="w-full bg-transparent py-2 pl-8 pr-3 text-[13px] text-text
                              placeholder:text-text-3 outline-none" />
          </div>
        )}

        <div className="overflow-y-auto" style={{ maxHeight: max }}>
          {shown.length === 0 ? (
            <p className="px-3 py-3 text-[12px] text-text-3">{empty}</p>
          ) : shown.map((o) => {
            const on = value.includes(o.value)
            return (
              <button key={o.value} type="button" role="checkbox" aria-checked={on}
                      onClick={() => toggle(o.value)}
                      className={`flex w-full items-start gap-2 px-3 py-[7px] text-left
                                  transition hover:bg-surface-3
                                  ${on ? 'text-text' : 'text-text-2'}`}>
                <Box checked={on} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-[12.5px]">
                    {o.label || o.value}
                  </span>
                  {o.meta && <span className="block text-[11px] text-text-3">{o.meta}</span>}
                </span>
              </button>
            )
          })}
        </div>
      </div>
      {hint && <span className="mt-1 block text-[11.5px] text-text-3">{hint}</span>}
    </div>
  )
}

export function Toggle({ checked, onChange, label, hint }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5">
      <button
        type="button" role="switch" aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`mt-0.5 h-[18px] w-8 shrink-0 rounded-full border transition
          ${checked ? 'border-accent bg-accent' : 'border-line-strong bg-surface-2'}`}
      >
        <span className={`block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform
          ${checked ? 'translate-x-[15px]' : 'translate-x-[1px]'}`} />
      </button>
      <span className="min-w-0">
        <span className="block text-[13px] text-text">{label}</span>
        {hint && <span className="block text-[11.5px] text-text-3">{hint}</span>}
      </span>
    </label>
  )
}

export function Segmented({ value, onChange, options, className = '' }) {
  return (
    <div className={`segment ${className}`} role="group">
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value}
                onClick={() => onChange(o.value)} title={o.title || o.label}>
          {o.icon && <o.icon size={14} />}
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Tabs({ value, onChange, options }) {
  return (
    <div className="flex flex-wrap gap-1 border-b border-line">
      {options.map((o) => (
        <button key={o.value} type="button" onClick={() => onChange(o.value)}
                className={`-mb-px border-b-2 px-3 py-2 text-[13px] font-medium transition
                  ${value === o.value
                    ? 'border-accent text-text'
                    : 'border-transparent text-text-3 hover:text-text-2'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export const Badge = ({ children, tone = 'default', className = '', ...rest }) => (
  <span className={`badge ${tone === 'accent' ? 'badge-accent'
    : tone === 'danger' ? 'badge-danger'
    : tone === 'warn' ? 'badge-warn' : ''} ${className}`} {...rest}>{children}</span>
)

export const Empty = ({ title, children, icon: Icon, action }) => (
  <div className="grid place-items-center px-4 py-10 text-center">
    {Icon && (
      <span className="mb-3 grid h-11 w-11 place-items-center rounded-xl
                       bg-surface-2 text-text-3"><Icon size={20} /></span>
    )}
    {title && <p className="text-[13.5px] font-medium text-text">{title}</p>}
    {children && <p className="mt-1 max-w-sm text-[12.5px] leading-relaxed text-text-3">{children}</p>}
    {action && <div className="mt-4">{action}</div>}
  </div>
)

/** Errors keep the engine's own `hint`: it is written for the caller, and
 *  paraphrasing it would drop the one line that says what to do next. */
export function ErrorNote({ error, onRetry }) {
  if (!error) return null
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-danger/25
                    bg-danger-soft px-3 py-2.5">
      <Alert size={16} className="mt-0.5 text-danger" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-danger">{error.message}</p>
        {error.hint && <p className="mt-0.5 text-[12px] text-text-2">{error.hint}</p>}
      </div>
      {onRetry && (
        <button className="btn btn-sm btn-ghost" onClick={onRetry}>
          <Refresh size={14} />
        </button>
      )}
    </div>
  )
}

const NOTE_TONES = {
  warn: ['border-warn/25 bg-warn-soft text-text-2', 'text-warn'],
  danger: ['border-danger/25 bg-danger-soft text-text-2', 'text-danger'],
  info: ['border-line bg-surface-2 text-text-2', 'text-text-3'],
}

export const Note = ({ children, tone = 'info' }) => {
  const [box, icon] = NOTE_TONES[tone] || NOTE_TONES.info
  return (
    <div className={`flex items-start gap-2.5 rounded-lg border px-3 py-2.5
                     text-[12.5px] ${box}`}>
      <Info size={15} className={`mt-px ${icon}`} />
      <div className="min-w-0 flex-1 leading-relaxed">{children}</div>
    </div>
  )
}

export const Spinner = ({ label, size = 14 }) => (
  <span className="inline-flex items-center gap-2 text-[12.5px] text-text-3">
    <span className="animate-spin rounded-full border-2 border-line border-t-accent"
          style={{ width: size, height: size }} />
    {label}
  </span>
)

export const Skeleton = ({ rows = 3 }) => (
  <div className="space-y-2">
    {Array.from({ length: rows }, (_, i) => (
      <div key={i} className="h-4 animate-pulse rounded bg-surface-2"
           style={{ width: `${100 - i * 12}%` }} />
    ))}
  </div>
)

export function Table({ head, children, dense = false }) {
  return (
    <div className="-mx-1 overflow-x-auto">
      {/* `min-w-full` let the table squeeze to the container instead of using
          the scroller it is already wrapped in — on a phone that shredded a
          URL into one character per line. A floor makes the wrapper do its
          job: columns keep their shape and the table scrolls sideways. */}
      <table className="w-full min-w-[34rem] text-[13px]">
        <thead>
          <tr className="border-b border-line text-left">
            {head.map((h, i) => (
              <th key={i} className="px-2 pb-2 text-[11px] font-semibold uppercase
                                     tracking-[0.06em] text-text-3">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className={`divide-y divide-line ${dense ? '' : ''}`}>{children}</tbody>
      </table>
    </div>
  )
}

export const Td = ({ children, className = '', ...p }) => (
  <td className={`px-2 py-2.5 align-top ${className}`} {...p}>{children}</td>
)

export function CopyButton({ value, label }) {
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!done) return
    const t = setTimeout(() => setDone(false), 1600)
    return () => clearTimeout(t)
  }, [done])
  return (
    <button type="button" className="btn btn-sm"
            onClick={() => { navigator.clipboard?.writeText(value); setDone(true) }}>
      {done ? <Check size={14} /> : <Copy size={14} />}
      {label}
    </button>
  )
}

export function Modal({ open, onClose, title, subtitle, children, footer, wide }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    ref.current?.querySelector('input, textarea, select, button')?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  // Rendered into `document.body`, not where it was written. `position:
  // fixed` resolves against the nearest ancestor carrying a transform, and
  // the sidebar is one — it slides in and out on `translate-y`. A dialog
  // opened from the forest picker therefore centred itself inside a 248px
  // rail, title wrapping mid-word, instead of over the page. A portal makes
  // the dialog independent of wherever it happens to be mounted, which is
  // the only fix that also covers the transform somebody adds next year.
  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center overflow-y-auto
                    bg-black/40 p-4 backdrop-blur-[2px]"
         onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true"
           className={`card animate-rise w-full shadow-pop ${wide ? 'max-w-2xl' : 'max-w-md'}`}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-3.5">
          <div>
            <h2 className="text-[15px] font-semibold text-text">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[12.5px] text-text-3">{subtitle}</p>}
          </div>
          <button className="btn btn-sm btn-ghost" onClick={onClose} aria-label="close">
            <X size={15} />
          </button>
        </header>
        <div className="p-5">{children}</div>
        {footer && (
          <footer className="flex justify-end gap-2 border-t border-line px-5 py-3.5">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body)
}

/** Monospace payload viewer — request bodies, SQL, node bodies. */
export const Code = ({ children, className = '', max = '20rem' }) => (
  <pre className={`overflow-auto rounded-lg border border-line bg-surface-2 p-3
                   prose-body ${className}`} style={{ maxHeight: max }}>{children}</pre>
)
