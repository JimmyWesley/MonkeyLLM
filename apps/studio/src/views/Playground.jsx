// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useState } from 'react'
import { api } from '../api.js'
import { useRouteState } from '../router.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Code, CopyButton, Empty, ErrorNote, Field, Note, Spinner, Tabs,
  Toggle,
} from '../design/ui.jsx'
import {
  Ask, Compass, Download, Eye, Files, Play, Playground as Beaker, Search,
} from '../design/icons.jsx'
import {
  Metric, NeedsCapability, fmtMs, has, rootsOf, useForestTree,
} from './shared.jsx'

/* The budgets are the engine's, restated here only so the number an operator
 * sees while tuning is the number the primitive actually enforces (C.6). */
/** Where entry search runs, and therefore where the RRF switch means
 *  something. `look`/`move` never call `locate`; offering it there would be
 *  a control with no wire behind it. */
const ENTRY_OPS = ['locate', 'harvest', 'answer']
/** The calls that look for something, and are therefore the ones where "in
 *  how large a corpus" is part of the answer. `look`/`move` are handed the
 *  node; saying what else exists would describe work they did not do. */
const SEARCH_OPS = ['locate', 'sniff', 'harvest', 'answer']

const OPS = [
  { key: 'locate', budget: 800, fields: ['query', 'k'], icon: Search },
  { key: 'sniff', budget: 800, fields: ['terms', 'k'], icon: Files },
  { key: 'harvest', budget: 4000, fields: ['query', 'terms', 'k'], icon: Download },
  { key: 'look', budget: 500, fields: ['id'], icon: Eye },
  { key: 'move', budget: 600, fields: ['id'], icon: Compass },
  { key: 'answer', budget: null, fields: ['query', 'k'], icon: Ask },
]

/** Everything that was not the call (J.10.6).
 *
 *  One quiet line, deliberately. What a visitor is here to judge is the
 *  engine: how long it takes this thing to find something. The rest of the
 *  span is their own network and whatever host they pointed at — a fact
 *  about somebody's infrastructure, not about the product, and giving it
 *  the same weight as the engine would be reporting the wrong subject.
 *
 *  It is not dropped either. The panel says 0.6 ms while the click felt
 *  instant-but-not-that-instant, and a number with no account of the gap
 *  reads as a claim rather than a measurement. Naming the gap is what makes
 *  the small number believable.
 */
function Aside({ timing, wall, bytes, rate }) {
  const { t, lang } = useI18n()
  // Never negative: the header is measured inside the span the client is
  // timing — but a stopwatch read across a suspended tab is not.
  const net = Math.max(0, wall - timing.vine - timing.host - (timing.model || 0))
  return (
    <p className="mb-3 text-[11px] leading-relaxed text-text-3">
      {/* Spelled out, never as `/s`. Rendered as "7.407/s" the number was
          read as seven-point-four seconds — by the person who wrote the
          engine, which settles whether a visitor would manage it. And
          "the engine does", not "the server serves": this rate comes off
          the engine clock alone, and a request also crosses a network. */}
      {rate != null && `${t('playground.rate', { n: rate.toLocaleString(lang) })} `}
      {t('playground.aside', {
        host: fmtMs(timing.host), net: fmtMs(net),
        bytes: bytes?.toLocaleString(lang),
      })}
    </p>
  )
}

export default function Playground({ forest, grant }) {
  const { t, lang } = useI18n()
  // Which primitive is being demonstrated is the page; what it answered is
  // not. The address restores the form, never the call (J.5.8) — `answer`
  // spends a model call and no reload asked for one.
  const [op, setOp] = useRouteState('op', 'locate',
                                    { allow: OPS.map((o) => o.key) })
  const [form, setForm] = useState({ query: '', terms: '', k: 5, id: '' })
  // K.3: the claim is a navigation gain, so it has to be measurable
  // against itself — same corpus, same session, one click apart.
  const [gauntlet, setGauntlet] = useState(true)
  // K.1: off by default, because measurement says fusing the dense layer
  // into an already-correct BM25 moves the right node off rank 1.
  const [hybrid, setHybrid] = useState(false)
  const [state, setState] = useState({})
  // How large the haystack was — above the early return, because a hook
  // behind a condition is a hook that changes count between renders.
  // Counted over what this key can actually reach, so a scoped grant is
  // never told the size of the whole forest.
  const tree = useForestTree(forest, grant, api.call, { skip: !has(grant, 'read') })

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
      // J.10.6: the host's own clocks come back beside the body, so the
      // number this panel leads with is the call and not the internet.
      const { data, timing } = await api.timedCall(forest, op, body)
      setState({ busy: false, body, data, timing, ms: performance.now() - t0 })
    } catch (error) {
      setState({ busy: false, body, error, ms: performance.now() - t0 })
    }
  }

  const rows = state.data
    ? (state.data.results || state.data.neighbors || state.data.nodes
       || state.data.evidence || []).length
    : null
  const bytes = state.data ? JSON.stringify(state.data).length : null
  // What the engine figure means in the unit a reader actually feels. Not a
  // projection: the Station serialises every forest call onto one worker
  // thread (J.0), so the inverse of the engine's own time IS the rate this
  // deployment sustains on this corpus, back to back. Never shown where a
  // provider ran — the rate of an `answer` is the model's, not the forest's,
  // and putting a retrieval number on it would be the same misattribution
  // this panel exists to stop.
  const rate = state.timing && !state.timing.model && state.timing.vine > 0
    ? Math.round(1000 / state.timing.vine)
    : null
  // The size of the haystack is what makes the milliseconds mean something:
  // "0.135 ms" is a fact, "0.135 ms across 82 nodes" is the claim. And
  // unlike a rate derived from one sample, it does not move between clicks.
  // Branches count — `locate` searches their metadata like any other node's,
  // and on the test forest the top hit for most queries IS one.
  const haystack = SEARCH_OPS.includes(op) && tree.data
    ? `${tree.data.nodes + tree.data.branches.length}${tree.data.partial ? '+' : ''}`
    : null
  const origin = window.location.origin

  const curl = `curl -X POST ${origin}/v1/forests/${forest}/${op} \\
  -H "Authorization: Bearer $MONKEYLLM_KEY" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify(payload())}'`

  return (
    <div className="space-y-4">
      <Card title={t('playground.title')} subtitle={t('playground.sub')} icon={Beaker}>
        <Tabs value={op} onChange={(next) => { setOp(next); setState({}) }}
              options={OPS.map((o) => ({ value: o.key, label: o.key, icon: o.icon }))} />

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
              /* No round-trip badge once the host reports its own clock: it
                 was the largest number on the panel and the one that says
                 least about the product. It moves to the aside, named. */
              actions={state.ms != null && !state.timing
                && <Badge>{t('common.elapsed', { ms: Math.round(state.ms) })}</Badge>}>
          {state.busy ? <Spinner label={t('common.working')} />
            : state.error ? <ErrorNote error={state.error} />
            : state.data ? (
            <>
              {/* The headline is the engine, never the round trip (J.10.6).
                  A Station reached over the internet answers a 0.2 ms
                  `locate` in ~30 ms of wall clock, and a panel that printed
                  the 30 was describing somebody's network while claiming to
                  describe the call. Without the header there is no engine
                  figure to lead with, so the old number stays — under its
                  own, honest name. */}
              <div className={`mb-3 grid grid-cols-2 gap-2 ${
                haystack ? 'sm:grid-cols-4' : 'sm:grid-cols-3'}`}>
                <Metric tone="accent"
                        label={t(state.timing ? 'playground.engine' : 'playground.latency')}
                        value={fmtMs(state.timing ? state.timing.vine : state.ms)} />
                {/* Not a rate: a rate off one sample swung twentyfold
                    between clicks, and it was read as seconds. This is the
                    haystack, it is the same number every time, and it is
                    what the reader is actually judging. `look`/`move` are
                    handed their node, so there is no haystack to report and
                    the tile is not there rather than empty. */}
                {haystack && <Metric label={t('playground.corpus')}
                                     value={t('playground.nodes', { n: haystack })} />}
                <Metric label={t('playground.returned')} value={rows ?? '—'} />
                <Metric label={t('playground.budget')} value={spec.budget ?? '—'} />
              </div>
              {state.timing && <Aside timing={state.timing} wall={state.ms}
                                      bytes={bytes} rate={rate} />}
              {state.data.truncated && <Note tone="warn">{t('common.truncated')}</Note>}
              <div className="mt-3">
                <Code max="26rem" lang="json">{JSON.stringify(state.data, null, 2)}</Code>
              </div>
            </>
          ) : <Empty icon={Beaker}>{t('playground.empty')}</Empty>}
        </Card>

        <div className="min-w-0 space-y-4">
          <Card title={t('common.request')}>
            <Code max="12rem" lang="json">{JSON.stringify(payload(), null, 2)}</Code>
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
