import { useState } from 'react'
import { api } from '../api.js'
import { Panel, Field, Select, ErrorNote, Spinner, Empty, Chip } from '../components/ui.jsx'

const MODES = {
  locate: { label: 'locate — curated metadata', hint: 'BM25 over title, aliases, tags and summary.' },
  sniff: { label: 'sniff — literal, inside bodies', hint: 'Exact terms the summaries never carry.' },
  harvest: { label: 'harvest — one-shot evidence', hint: 'Zero-LLM retrieval: ranked nodes with snippets.' },
}

export default function Search({ forest, onOpenNode }) {
  const [q, setQ] = useState('')
  const [mode, setMode] = useState('locate')
  const [state, setState] = useState({ busy: false })

  async function run(e) {
    e?.preventDefault()
    if (!q.trim()) return
    setState({ busy: true })
    const t0 = performance.now()
    try {
      const payload = mode === 'sniff' ? { terms: q.trim().split(/\s+/), k: 8 }
        : mode === 'harvest' ? { query: q, k: 3 } : { query: q, k: 8 }
      const r = await api.call(forest, mode, payload)
      setState({ busy: false, data: r, ms: Math.round(performance.now() - t0) })
    } catch (error) { setState({ busy: false, error }) }
  }

  const hits = state.data?.results || []

  return (
    <div className="space-y-4">
      <Panel title="Search" subtitle="The same budgets the agent sees — this is where scent gets tuned.">
        <form onSubmit={run} className="grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
          <Field label="Query" value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="question, or exact terms" />
          <Select label="Mode" value={mode} onChange={(e) => setMode(e.target.value)}>
            {Object.entries(MODES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </Select>
          <button className="btn btn-primary h-[38px]" disabled={state.busy}>Run</button>
        </form>
        <p className="mt-2 text-[12px] text-bark-500">{MODES[mode].hint}</p>
      </Panel>

      {state.busy && <Panel><Spinner label="searching" /></Panel>}
      {state.error && <Panel><ErrorNote error={state.error} /></Panel>}

      {state.data && !state.busy && (
        <Panel
          title="Results"
          actions={<>
            <Chip>{hits.length} hit{hits.length === 1 ? '' : 's'}</Chip>
            <Chip>{state.ms} ms</Chip>
            {state.data.truncated && <Chip>truncated</Chip>}
            {state.data.scanned_nodes != null && <Chip>{state.data.scanned_nodes} scanned</Chip>}
          </>}
        >
          {hits.length === 0 ? <Empty>Nothing in scope matched.</Empty> : (
            <ul className="divide-y divide-canvas-line/70">
              {hits.map((h) => (
                <li key={h.id} className="py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <button onClick={() => onOpenNode(h.id)} className="nodeid hover:underline">
                      {h.id}
                    </button>
                    {h.score != null && <Chip>score {h.score}</Chip>}
                    {!!h.heat && <Chip tone="moss">heat {h.heat}</Chip>}
                  </div>
                  {h.title && <p className="mt-1 text-[14px] text-moss-50">{h.title}</p>}
                  {h.summary && <p className="mt-0.5 text-[13px] text-bark-400">{h.summary}</p>}
                  {!!h.matches?.length && (
                    <div className="mt-2 space-y-1">
                      {h.matches.map((m, i) => (
                        <pre key={i} className="overflow-x-auto rounded border border-canvas-line
                                                bg-canvas-soft px-2.5 py-1.5 text-[12px] text-bark-300">
                          {m.text || m.line || JSON.stringify(m)}
                        </pre>
                      ))}
                    </div>
                  )}
                  {h.content && (
                    <pre className="mt-2 max-h-64 overflow-auto rounded border border-canvas-line
                                    bg-canvas-soft px-2.5 py-1.5 text-[12px] whitespace-pre-wrap
                                    text-bark-300">
                      {typeof h.content === 'string' ? h.content : JSON.stringify(h.content, null, 2)}
                    </pre>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}
    </div>
  )
}
