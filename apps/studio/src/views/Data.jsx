import { useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Code, Empty, ErrorNote, Note, Skeleton, Spinner, Table, Td,
} from '../design/ui.jsx'
import { Data as DataIcon, Play } from '../design/icons.jsx'
import { NeedsCapability, has, rootsOf, useAsync } from './shared.jsx'

export default function Data({ forest, grant }) {
  const { t } = useI18n()
  const [id, setId] = useState('')
  const [sql, setSql] = useState('')
  const [state, setState] = useState({})

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

  const manual = useAsync(() => api.call(forest, 'look', { id }), [forest, id],
                          { skip: !id })

  if (!has(grant, 'query')) {
    return <NeedsCapability message={t('access.needs_admin')} hint={t('cap.query')} />
  }

  async function run(e) {
    e.preventDefault()
    setState({ busy: true })
    try { setState({ busy: false, data: await api.call(forest, 'query', { id, sql }) }) }
    catch (error) { setState({ busy: false, error }) }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
      <div className="space-y-4">
        <Card title={t('data.pick')} icon={DataIcon} bodyClass="p-2">
          {found.busy ? <div className="p-3"><Skeleton rows={3} /></div>
            : found.error ? <div className="p-3"><ErrorNote error={found.error} /></div>
            : (found.data || []).length === 0 ? <Empty icon={DataIcon}>{t('data.none')}</Empty> : (
            <ul className="space-y-0.5">
              {found.data.map((n) => (
                <li key={n.id}>
                  <button onClick={() => setId(n.id)}
                          className={`w-full rounded-lg px-2.5 py-2 text-left transition
                            hover:bg-surface-2 ${n.id === id ? 'bg-accent-soft' : ''}`}>
                    <span className="nodeid block truncate">{n.id}</span>
                    <span className="mt-0.5 block line-clamp-2 text-[12px] text-text-3">
                      {n.summary}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {id && manual.data?.body_preview && (
          <Card title={t('data.manual')} subtitle={t('data.manual_hint')}>
            <Code max="18rem">{manual.data.body_preview}</Code>
          </Card>
        )}
      </div>

      <div className="min-w-0 space-y-4">
        <Card title={t('data.title')} subtitle={t('data.sub')} icon={DataIcon}>
          <form onSubmit={run} className="space-y-3">
            <label className="block">
              <span className="label">{t('common.node')}</span>
              <input className="field font-mono text-[12.5px]" value={id}
                     placeholder="sales/report-q1-2026"
                     onChange={(e) => setId(e.target.value)} />
            </label>
            <label className="block">
              <span className="label">{t('data.sql')}</span>
              <textarea className="field min-h-[110px] resize-y font-mono text-[12.5px]
                                   leading-relaxed"
                        rows={4} value={sql}
                        placeholder="SELECT region, SUM(value) AS total FROM sales GROUP BY region ORDER BY total DESC"
                        onChange={(e) => setSql(e.target.value)} />
            </label>
            <div className="flex justify-end">
              <button className="btn btn-primary" disabled={!id || !sql || state.busy}>
                <Play size={14} /> {t('data.run')}
              </button>
            </div>
          </form>
        </Card>

        {state.busy && <Card><Spinner label={t('common.working')} /></Card>}
        {state.error && <Card><ErrorNote error={state.error} /></Card>}

        {state.data && (
          <Card title={t('common.results')}
                actions={<>
                  <Badge tone="accent">{t('data.rows', { n: state.data.row_count })}</Badge>
                  <Badge>{t('common.elapsed', { ms: state.data.elapsed_ms })}</Badge>
                  {state.data.limited && <Badge tone="warn">{t('data.limited')}</Badge>}
                </>}>
            <Table head={state.data.columns || []}>
              {(state.data.rows || []).map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <Td key={j} className="font-mono text-[12px] text-text-2">
                      {cell === null ? '—' : String(cell)}
                    </Td>
                  ))}
                </tr>
              ))}
            </Table>
          </Card>
        )}

        {!state.data && !state.busy && !state.error && (
          <Card><Empty icon={DataIcon}>{t('data.empty')}</Empty></Card>
        )}

        <Note>{t('data.sub')}</Note>
      </div>
    </div>
  )
}
