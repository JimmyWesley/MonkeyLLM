import { useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Code, CopyButton, Empty, ErrorNote, Field, Note, Spinner, Tabs,
  Toggle,
} from '../design/ui.jsx'
import { Play, Playground as Beaker } from '../design/icons.jsx'
import { Metric, NeedsCapability, has, rootsOf } from './shared.jsx'

/* The budgets are the engine's, restated here only so the number an operator
 * sees while tuning is the number the primitive actually enforces (C.6). */
/** Where entry search runs, and therefore where the RRF switch means
 *  something. `look`/`move` never call `locate`; offering it there would be
 *  a control with no wire behind it. */
const ENTRY_OPS = ['locate', 'harvest', 'answer']

const OPS = [
  { key: 'locate', budget: 800, fields: ['query', 'k'] },
  { key: 'sniff', budget: 800, fields: ['terms', 'k'] },
  { key: 'harvest', budget: 4000, fields: ['query', 'terms', 'k'] },
  { key: 'look', budget: 500, fields: ['id'] },
  { key: 'move', budget: 600, fields: ['id'] },
  { key: 'answer', budget: null, fields: ['query', 'k'] },
]

export default function Playground({ forest, grant }) {
  const { t } = useI18n()
  const [op, setOp] = useState('locate')
  const [form, setForm] = useState({ query: '', terms: '', k: 5, id: '' })
  // K.3: the claim is a navigation gain, so it has to be measurable
  // against itself — same corpus, same session, one click apart.
  const [gauntlet, setGauntlet] = useState(true)
  // K.1: off by default, because measurement says fusing the dense layer
  // into an already-correct BM25 moves the right node off rank 1.
  const [hybrid, setHybrid] = useState(false)
  const [state, setState] = useState({})

  if (!has(grant, 'read')) {
    return <NeedsCapability message={t('access.needs_admin')} hint={t('cap.read')} />
  }

  const spec = OPS.find((o) => o.key === op)
  const root = rootsOf(grant)[0]

  const payload = () => {
    const out = {}
    if (spec.fields.includes('query')) out[op === 'answer' ? 'question' : 'query'] = form.query
    if (spec.fields.includes('terms')) {
      const terms = form.terms.split(/[\s,]+/).filter(Boolean)
      if (terms.length || op === 'sniff') out.terms = terms
    }
    if (spec.fields.includes('k')) out.k = Number(form.k) || 5
    if (spec.fields.includes('id')) out.id = form.id || root
    if (['look', 'move'].includes(op) && !gauntlet) out.gauntlet = false
    // The other dense switch, and a different one: this fuses the vector
    // layer into ENTRY search (K.1). Sent only where entry search happens.
    if (ENTRY_OPS.includes(op) && hybrid) out.hybrid = true
    return out
  }

  async function run(e) {
    e.preventDefault()
    const body = payload()
    setState({ busy: true, body })
    const t0 = performance.now()
    try {
      const data = await api.call(forest, op, body)
      setState({ busy: false, body, data, ms: Math.round(performance.now() - t0) })
    } catch (error) {
      setState({ busy: false, body, error, ms: Math.round(performance.now() - t0) })
    }
  }

  const rows = state.data
    ? (state.data.results || state.data.neighbors || state.data.nodes
       || state.data.evidence || []).length
    : null
  const bytes = state.data ? JSON.stringify(state.data).length : null
  const origin = window.location.origin

  const curl = `curl -X POST ${origin}/v1/forests/${forest}/${op} \\
  -H "Authorization: Bearer $MONKEYLLM_KEY" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify(payload())}'`

  return (
    <div className="space-y-4">
      <Card title={t('playground.title')} subtitle={t('playground.sub')} icon={Beaker}>
        <Tabs value={op} onChange={(next) => { setOp(next); setState({}) }}
              options={OPS.map((o) => ({ value: o.key, label: o.key }))} />

        <p className="mt-3 text-[12.5px] text-text-3">{t(`playground.${op}`)}</p>

        <form onSubmit={run} className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            {spec.fields.includes('query') && (
              <Field label={t('playground.query')} value={form.query} required
                     placeholder={t('ask.ex1')} className="sm:col-span-2"
                     onChange={(e) => setForm({ ...form, query: e.target.value })} />
            )}
            {spec.fields.includes('terms') && (
              <Field label={t('playground.terms')} value={form.terms}
                     hint={t('playground.terms_hint')} placeholder="retro, thursday"
                     className="sm:col-span-2"
                     onChange={(e) => setForm({ ...form, terms: e.target.value })} />
            )}
            {spec.fields.includes('id') && (
              <Field label={t('playground.node')} value={form.id} placeholder={root}
                     onChange={(e) => setForm({ ...form, id: e.target.value })} />
            )}
            {spec.fields.includes('k') && (
              <Field label={t('playground.k')} type="number" min="1" max="20" value={form.k}
                     onChange={(e) => setForm({ ...form, k: e.target.value })} />
            )}
          </div>
          <div className="flex flex-wrap items-center justify-end gap-4">
            {['look', 'move'].includes(op) && (
              <div className="mr-auto">
                <Toggle checked={gauntlet} onChange={setGauntlet}
                        label={t('gauntlet.toggle')} hint={t('gauntlet.toggle_hint')} />
              </div>
            )}
            {ENTRY_OPS.includes(op) && (
              <div className="mr-auto">
                <Toggle checked={hybrid} onChange={setHybrid}
                        label={t('ask.hybrid')} hint={t('ask.hybrid_hint')} />
              </div>
            )}
            <button className="btn btn-primary" disabled={state.busy}>
              <Play size={14} />
              {state.busy ? t('common.working') : t('playground.send')}
            </button>
          </div>
        </form>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <Card title={t('common.response')}
              actions={state.ms != null && <Badge>{t('common.elapsed', { ms: state.ms })}</Badge>}>
          {state.busy ? <Spinner label={t('common.working')} />
            : state.error ? <ErrorNote error={state.error} />
            : state.data ? (
            <>
              <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Metric label={t('playground.latency')} value={`${state.ms} ms`} tone="accent" />
                <Metric label={t('playground.returned')} value={rows ?? '—'} />
                <Metric label={t('playground.budget')} value={spec.budget ?? '—'} />
                <Metric label="bytes" value={bytes} />
              </div>
              {state.data.truncated && <Note tone="warn">{t('common.truncated')}</Note>}
              <div className="mt-3">
                <Code max="26rem">{JSON.stringify(state.data, null, 2)}</Code>
              </div>
            </>
          ) : <Empty icon={Beaker}>{t('playground.empty')}</Empty>}
        </Card>

        <div className="min-w-0 space-y-4">
          <Card title={t('common.request')}>
            <Code max="12rem">{JSON.stringify(payload(), null, 2)}</Code>
          </Card>

          <Card title={t('playground.curl')} subtitle={t('playground.curl_hint')}
                actions={<CopyButton value={curl} />}>
            <Code max="14rem">{curl}</Code>
            <div className="mt-3">
              <Note>{t('playground.mcp_hint', { url: `${origin}/mcp/` })}</Note>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
