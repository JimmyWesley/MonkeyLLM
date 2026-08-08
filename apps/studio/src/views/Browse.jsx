import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Panel, ErrorNote, Spinner, Empty, Chip, Stat } from '../components/ui.jsx'

// Ancestors come from the id, filtered by the grant: a scoped principal has
// no path up to the master index, so offering one would only 404.
function crumbsFor(id, allow) {
  const whole = allow.length === 1 && allow[0] === ''
  const parts = id.split('/')
  const out = []
  for (let i = 1; i < parts.length; i++) out.push(parts.slice(0, i).join('/') + '/_index')
  return out.filter((c) => c !== id && (whole || allow.some((a) => c.startsWith(a))))
}

export default function Browse({ forest, grant, node, setNode }) {
  const [digest, setDigest] = useState(null)
  const [body, setBody] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(true)

  const roots = grant?.roots?.length ? grant.roots : ['_index']
  const current = node || roots[0]

  useEffect(() => {
    let live = true
    setBusy(true); setError(null); setBody(null)
    api.call(forest, 'look', { id: current })
      .then((d) => { if (live) setDigest(d) })
      .catch((e) => { if (live) { setError(e); setDigest(null) } })
      .finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [forest, current])

  async function readBody() {
    setBody('loading')
    try { setBody(await api.call(forest, 'pick', { id: current })) }
    catch (e) { setBody({ error: e }) }
  }

  const crumbs = crumbsFor(current, grant?.allow || [''])

  return (
    <div className="space-y-4">
      <nav className="flex flex-wrap items-center gap-1.5 text-[12px] text-bark-500">
        {roots.map((r) => (
          <button key={r} onClick={() => setNode(r)}
                  className="rounded px-1.5 py-0.5 font-mono hover:text-moss-300">{r}</button>
        ))}
        {crumbs.filter((c) => !roots.includes(c)).map((c) => (
          <span key={c} className="flex items-center gap-1.5">
            <span className="text-canvas-line">/</span>
            <button onClick={() => setNode(c)}
                    className="rounded px-1.5 py-0.5 font-mono hover:text-moss-300">{c}</button>
          </span>
        ))}
      </nav>

      {busy && <Panel><Spinner label="opening" /></Panel>}
      {error && <Panel><ErrorNote error={error} /></Panel>}

      {digest && !busy && (
        <>
          <Panel
            title={digest.title}
            subtitle={digest.id}
            actions={<>
              <Chip tone="moss">{digest.type}</Chip>
              <button className="btn" onClick={readBody}>Read body</button>
            </>}
          >
            <p className="text-[14px] leading-relaxed text-moss-50">{digest.summary}</p>
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Stat label="degree" value={digest.stats?.degree ?? 0} />
              <Stat label="heat" value={digest.stats?.heat ?? 0} />
              <Stat label="body tokens" value={digest.stats?.body_tokens ?? 0} />
              <Stat label="updated" value={digest.updated || '—'} />
            </div>
            {digest.coverage && (
              <p className="mt-3 text-[12px] text-bark-500">{digest.coverage}</p>
            )}
            {body && (
              <div className="mt-5">
                <div className="label">Body</div>
                {body === 'loading' ? <Spinner label="reading" />
                  : body.error ? <ErrorNote error={body.error} />
                  : <pre className="max-h-[420px] overflow-auto rounded-lg border
                                    border-canvas-line bg-canvas-soft p-3 text-[12.5px]
                                    leading-relaxed text-bark-300 whitespace-pre-wrap">
                      {body.body}
                    </pre>}
              </div>
            )}
          </Panel>

          {!!digest.children?.length && (
            <Panel title="Children">
              <ul className="divide-y divide-canvas-line/70">
                {digest.children.map((c) => (
                  <li key={c.id} className="py-2.5">
                    <button onClick={() => setNode(c.id)} className="nodeid hover:underline">
                      {c.id}
                    </button>
                    <p className="mt-0.5 text-[13px] text-bark-400">{c.summary}</p>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {!!digest.edges_out?.length && (
            <Panel title="Edges" subtitle="Only edges whose other end is in scope are shown.">
              <ul className="divide-y divide-canvas-line/70">
                {digest.edges_out.map((e, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-2 py-2.5">
                    <Chip>{e.rel}</Chip>
                    <button onClick={() => setNode(e.target)} className="nodeid hover:underline">
                      {e.target}
                    </button>
                    <p className="w-full text-[13px] text-bark-400">{e.target_summary}</p>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {!digest.children?.length && !digest.edges_out?.length && (
            <Panel><Empty>A leaf: no children, no outgoing edges in scope.</Empty></Panel>
          )}
        </>
      )}
    </div>
  )
}
