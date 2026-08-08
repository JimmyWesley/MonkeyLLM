export function Panel({ title, subtitle, actions, children, className = '' }) {
  return (
    <section className={`panel p-5 animate-rise ${className}`}>
      {(title || actions) && (
        <header className="mb-4 flex items-start justify-between gap-4">
          <div>
            {title && <h2 className="text-[15px] font-semibold text-moss-50">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[13px] text-bark-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  )
}

export function Field({ label, hint, className = '', ...props }) {
  return (
    <label className={`block ${className}`}>
      {label && <span className="label">{label}</span>}
      <input className="field" {...props} />
      {hint && <span className="mt-1 block text-[11px] text-bark-500">{hint}</span>}
    </label>
  )
}

export function Select({ label, children, className = '', ...props }) {
  return (
    <label className={`block ${className}`}>
      {label && <span className="label">{label}</span>}
      <select className="field appearance-none" {...props}>{children}</select>
    </label>
  )
}

export function TextArea({ label, className = '', ...props }) {
  return (
    <label className={`block ${className}`}>
      {label && <span className="label">{label}</span>}
      <textarea className="field font-mono text-[12.5px] leading-relaxed" {...props} />
    </label>
  )
}

export const Chip = ({ children, tone }) => (
  <span className={tone === 'moss' ? 'chip chip-moss' : 'chip'}>{children}</span>
)

export const Empty = ({ children }) => (
  <p className="py-8 text-center text-[13px] text-bark-500">{children}</p>
)

export function ErrorNote({ error }) {
  if (!error) return null
  return (
    <div className="rounded-lg border border-ember-500/40 bg-ember-500/5 px-3 py-2">
      <p className="text-[13px] text-ember-400">{error.message}</p>
      {error.hint && <p className="mt-0.5 text-[12px] text-bark-500">{error.hint}</p>}
    </div>
  )
}

export const Spinner = ({ label = 'working' }) => (
  <span className="inline-flex items-center gap-2 text-[13px] text-bark-500">
    <span className="h-3 w-3 animate-spin rounded-full border-2 border-canvas-line border-t-moss-400" />
    {label}…
  </span>
)

export function Stat({ label, value }) {
  return (
    <div className="rounded-lg border border-canvas-line bg-canvas-soft px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-bark-500">{label}</div>
      <div className="mt-0.5 text-[15px] text-moss-50">{value}</div>
    </div>
  )
}

export function Table({ head, children }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-canvas-line text-left">
            {head.map((h) => (
              <th key={h} className="px-2 py-2 text-[11px] font-medium uppercase
                                     tracking-wide text-bark-500">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-canvas-line/70">{children}</tbody>
      </table>
    </div>
  )
}
