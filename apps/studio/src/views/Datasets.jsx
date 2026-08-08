import { useState } from 'react'
import { api } from '../api.js'
import { Panel, Field, TextArea, ErrorNote, Spinner, Empty, Chip, Table } from '../components/ui.jsx'

export default function Datasets({ forest, grant }) {
  const [id, setId] = useState('')
  const [sql, setSql] = useState('')
  const [found, setFound] = useState(null)
  const [state, setState] = useState({})

  async function discover() {
    setFound('loading')
    try {
      const roots = grant?.roots?.length ? grant.roots : ['_index']
      const all = []
      for (const r of roots) {
        const s = await api.call(forest, 'scan',
          { parent_id: r, recursive: true, limit: 200, filter: { type: 'dataset' } })
        all.push(...(s.nodes || []))
      }
      setFound(all)
    } catch (e) { setFound({ error: e }) }
  }

  async function run(e) {
    e.preventDefault()
    setState({ busy: true })
    try { setState({ busy: false, data: await api.call(forest, 'query', { id, sql }) }) }
    catch (error) { setState({ busy: false, error }) }
  }

  return (
    <div className="space-y-4">
      <Panel
        title="Datasets"
        subtitle="Read-only SQL. The engine rejects every write here — tend is the only write path, and it takes one statement at a time."
        actions={<button className="btn" onClick={discover}>Find datasets</button>}
      >
        <form onSubmit={run} className="space-y-3">
          <Field label="Dataset node" value={id} onChange={(e) => setId(e.target.value)}
                 placeholder="sales/report-q1-2026" />
          <TextArea label="SQL" rows={4} value={sql} onChange={(e) => setSql(e.target.value)}
                    placeholder="SELECT region, SUM(value) AS total FROM sales GROUP BY region ORDER BY total DESC" />
          <button className="btn btn-primary" disabled={!id || !sql || state.busy}>Run query</button>
        </form>
      </Panel>

      {found && (
        <Panel title="Datasets in scope">
          {found === 'loading' ? <Spinner label="scanning" />
            : found.error ? <ErrorNote error={found.error} />
            : found.length === 0 ? <Empty>No dataset inside this principal's scope.</Empty> : (
            <ul className="divide-y divide-canvas-line/70">
              {found.map((n) => (
                <li key={n.id} className="flex items-baseline justify-between gap-3 py-2.5">
                  <div>
                    <button className="nodeid hover:underline" onClick={() => setId(n.id)}>{n.id}</button>
                    <p className="mt-0.5 text-[13px] text-bark-400">{n.summary}</p>
                  </div>
                  <button className="btn !py-1" onClick={() => setId(n.id)}>Use</button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      {state.busy && <Panel><Spinner label="querying" /></Panel>}
      {state.error && <Panel><ErrorNote error={state.error} /></Panel>}
      {state.data && (
        <Panel
          title="Rows"
          actions={<>
            <Chip>{state.data.row_count} row{state.data.row_count === 1 ? '' : 's'}</Chip>
            <Chip>{state.data.elapsed_ms} ms</Chip>
            {state.data.limited && <Chip>limited</Chip>}
          </>}
        >
          <Table head={state.data.columns || []}>
            {(state.data.rows || []).map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} className="px-2 py-1.5 font-mono text-[12px] text-bark-300">
                    {String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </Table>
        </Panel>
      )}
    </div>
  )
}
