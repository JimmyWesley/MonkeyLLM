// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Empty, ErrorNote, Note, Segmented, Spinner, Toggle,
} from '../design/ui.jsx'
import { Markdown } from '../design/markdown.jsx'
import {
  Ask as AskIcon, Collapse, Download, Expand, Printer, Sparkle,
} from '../design/icons.jsx'
import { Metric, NeedsCapability, fmtMs, has, nodeLink, useAsync } from './shared.jsx'

/** The console that needs no explanation, which is why it is the landing one.
 *
 * Retrieval is scoped and deterministic and happens first; only then does the
 * forest's bound model read what was found (J.10.3). The evidence list is not
 * decoration — it is the set of nodes that were actually read. */
export default function Ask({ forest, grant, goto }) {
  const { t } = useI18n()
  const [question, setQuestion] = useState('')
  const [k, setK] = useState(3)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [hybrid, setHybrid] = useState(false)
  // J.10.5. Off by default because it is not free: one model call per hop
  // against one for the sweep.
  const [hops, setHops] = useState(false)
  const [wide, setWide] = useState(false)

  const admin = has(grant, 'admin')
  // Only an admin can read index health, and only an admin has any business
  // switching the entry ranker. Non-admins never see the control, which is
  // right: it is a measurement instrument, not a preference.
  const canopy = useAsync(() => api.canopy(forest), [forest], { skip: !admin })
  const dense = canopy.data?.state === 'active' && canopy.data?.enabled !== false

  if (!has(grant, 'read')) {
    return <NeedsCapability message={t('access.needs_admin')} hint={t('cap.read')} />
  }

  async function ask(text) {
    const q = (text ?? question).trim()
    if (!q) return
    setQuestion(q)
    setBusy(true); setError(null); setResult(null)
    const t0 = performance.now()
    try {
      const { data, timing } = await api.timedCall(forest, 'answer', {
        question: q, k,
        ...(hybrid ? { hybrid: true } : {}),
        ...(hops ? { hops: true } : {}),
      })
      setResult({ ...data, timing, ms: Math.round(performance.now() - t0) })
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  const noModel = error?.code === 'E_SCHEMA' && /no model is bound/i.test(error.message)

  return (
    <div className="space-y-4">
      <Card title={t('ask.title')} subtitle={t('ask.sub')} icon={AskIcon}>
        <form onSubmit={(e) => { e.preventDefault(); ask() }} className="space-y-3">
          <textarea
            className="field min-h-[92px] resize-y text-[14px] leading-relaxed"
            rows={3} autoFocus value={question}
            placeholder={t('ask.placeholder')}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); ask() }
            }}
          />
          {/* Settings left, action right — the same order every form on this
              console uses, so the button is always in the corner the eye
              already went to. */}
          <div className="flex flex-wrap items-center justify-end gap-3">
            <div className="mr-auto flex items-center gap-2">
              <span className="text-[11.5px] text-text-3">{t('ask.depth')}</span>
              <Segmented value={k} onChange={setK} options={[
                { value: 2, label: '2' }, { value: 3, label: '3' }, { value: 6, label: '6' },
              ]} />
            </div>
            {/* A keyboard shortcut is not advice on a phone. */}
            <span className="hidden text-[11.5px] text-text-3 sm:inline">
              {t('ask.hint_send')}
            </span>
            <button className="btn btn-primary" disabled={busy || !question.trim()}>
              <Sparkle size={15} />
              {busy ? t('ask.thinking') : t('ask.send')}
            </button>
          </div>

          <div className="space-y-3 border-t border-line pt-3">
            <Toggle checked={hops} onChange={setHops}
                    label={t('ask.hops')} hint={t('ask.hops_hint')} />
            {dense && (
              <Toggle checked={hybrid} onChange={setHybrid}
                      label={t('ask.hybrid')} hint={t('ask.hybrid_hint')} />
            )}
          </div>
        </form>

        {!result && !busy && (
          <div className="mt-5 border-t border-line pt-4">
            <div className="label">{t('ask.examples')}</div>
            <div className="flex flex-wrap gap-2">
              {['ask.ex1', 'ask.ex2', 'ask.ex3'].map((key) => (
                <button key={key} type="button" onClick={() => ask(t(key))}
                        className="badge hover:border-accent/40 hover:bg-accent-soft
                                   hover:text-accent">
                  {t(key)}
                </button>
              ))}
            </div>
          </div>
        )}
      </Card>

      {busy && <Working hops={hops} />}

      {error && (
        <Card>
          <ErrorNote error={error} />
          {noModel && (
            <div className="mt-3">
              <Note tone="warn">
                {t('ask.no_model')}{' '}
                {has(grant, 'admin') && (
                  <button className="font-medium text-accent underline-offset-2 hover:underline"
                          onClick={() => goto('models')}>{t('overview.bind_model')}</button>
                )}
              </Note>
            </div>
          )}
        </Card>
      )}

      {result && (
        <div className={`grid gap-4 ${wide ? '' : 'lg:grid-cols-[1fr_320px]'}`}>
          <Card className="print-target" title={t('ask.answer')} icon={Sparkle}
                actions={<>
                  <Badge tone="accent">{result.model}</Badge>
                  <Badge>{t('common.elapsed', { ms: result.ms })}</Badge>
                  {/* Reading is the point; the instruments can wait. Widening
                      moves the panel below instead of hiding it. */}
                  <button className="btn btn-sm btn-ghost !px-1.5 hidden lg:inline-flex"
                          onClick={() => setWide((w) => !w)}
                          title={t(wide ? 'ask.collapse' : 'ask.expand')}
                          aria-label={t(wide ? 'ask.collapse' : 'ask.expand')}>
                    {wide ? <Collapse size={15} /> : <Expand size={15} />}
                  </button>
                </>}>
            {/* An answer is markdown — tables, lists, and sometimes a mermaid
                diagram. Rendering it as preformatted text showed the source
                of a document instead of the document. */}
            <Markdown>{result.answer}</Markdown>

            <div className="mt-6 border-t border-line pt-4">
              <div className="label">{t('common.evidence')}</div>
              {result.evidence?.length ? (
                <>
                  <p className="mb-2.5 text-[12px] text-text-3">{t('ask.evidence_hint')}</p>
                  {/* An id is not a label: `projects/leads-2d` could be
                      anything. The scent travels with every result already,
                      so saying what is behind each link costs nothing. */}
                  <ul className="space-y-1.5">
                    {result.evidence.map((id) => {
                      const src = (result.sources || []).find((s) => s.id === id)
                      return (
                        <li key={id}>
                          <a className="block w-full rounded-lg border border-line bg-surface
                                        px-2.5 py-2 text-left transition
                                        hover:border-accent/40"
                             {...nodeLink(forest, id)}>
                            <span className="flex flex-wrap items-baseline gap-x-2">
                              <span className="font-mono text-[12px] text-accent">{id}</span>
                              {src?.type && (
                                <span className="text-[10.5px] uppercase tracking-[0.07em]
                                                 text-text-3">{src.type}</span>
                              )}
                            </span>
                            {(src?.title || src?.summary) && (
                              <span className="mt-0.5 block text-[12px] leading-relaxed text-text-2">
                                {src.title && <b className="font-medium text-text">{src.title}. </b>}
                                {src.summary}
                              </span>
                            )}
                          </a>
                        </li>
                      )
                    })}
                  </ul>
                </>
              ) : <Empty>{t('ask.nothing')}</Empty>}
            </div>

            {/* Taking the answer with you. `.md` is the answer as written;
                the PDF goes through the browser's own print pipeline, which
                already knows how to lay out text and rasterise the SVG of a
                diagram — a bundled PDF writer would do both worse. */}
            <div className="no-print mt-5 flex flex-wrap justify-end gap-2
                            border-t border-line pt-3">
              <button className="btn btn-sm"
                      onClick={() => downloadMarkdown(result, question, forest)}>
                <Download size={14} /> {t('ask.download_md')}
              </button>
              <button className="btn btn-sm" onClick={() => window.print()}>
                <Printer size={14} /> {t('ask.download_pdf')}
              </button>
            </div>

            {result.hops?.length > 0 && <Path hops={result.hops} />}
            {/* One panel either way: the sweep hands the material back in a
                bundle, the forager assembles it hop by hop (J.10.5). */}
            {(result.harvest?.results?.length || result.read?.length) > 0 && (
              <Material results={result.harvest?.results || result.read}
                        sources={result.sources || []} />
            )}
          </Card>

          <Explain trace={result.trace} wall={result.ms} hybrid={hybrid}
                   cost={result.cost} timing={result.timing} />
        </div>
      )}

      <Note>{t('ask.limits')}</Note>
      {/* No Gauntlet switch here on purpose: `answer` composes `harvest`,
          which is entry search — locate + sniff, no `look`, no `move`, no
          `scan`. Part K conditions the *frontier*, and this console never
          hops. The switch above is the other one: whether the vector layer
          joins entry search, which is the thing that does affect an answer
          — and the thing measurement says makes it worse. */}
      <Note>{t('gauntlet.not_here')}</Note>
    </div>
  )
}

/** The answer as a file. Markdown because that is what it already is —
 *  converting it to anything else here would be a lossy round trip. */
function downloadMarkdown(result, question, forest) {
  const lines = [
    `# ${question}`, '',
    result.answer, '',
    '---', '',
    `- Forest: \`${forest}\``,
    `- Model: \`${result.model}\``,
    ...(result.hops?.length
      ? [`- Hops: ${result.hops.map((h) => `${h.tool}${h.id ? `(${h.id})` : ''}`).join(' → ')}`]
      : []),
    ...(result.evidence?.length ? [`- Evidence: ${result.evidence.join(', ')}`] : []),
    ...(result.cost?.priced ? [`- Cost: $${result.cost.usd}`] : []),
    `- ${new Date().toISOString()}`,
  ]
  const url = URL.createObjectURL(
    new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${(question || 'answer').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'answer'}.md`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

/** While the answer is being made.
 *
 *  Deliberately NOT a fake narration of hops. The request is one POST and
 *  the host answers once, so a console that claimed "now it is reading X"
 *  would be inventing it — and an invented progress bar is worse than an
 *  honest clock, because it is indistinguishable from a real one. What is
 *  true and useful: which mode is running, what that mode does, and how
 *  long it has been running. Streaming the real hops needs the host to push
 *  events (SSE), which is a different contract.
 */
function Working({ hops }) {
  const { t } = useI18n()
  const [ms, setMs] = useState(0)
  useEffect(() => {
    const t0 = performance.now()
    const id = setInterval(() => setMs(performance.now() - t0), 100)
    return () => clearInterval(id)
  }, [])

  const stages = hops
    ? ['ask.stage_entry', 'ask.stage_walk', 'ask.stage_write']
    : ['ask.stage_entry', 'ask.stage_read', 'ask.stage_write']

  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <Spinner label={t(hops ? 'ask.working_hops' : 'ask.working_sweep')} />
        <span className="font-mono text-[12px] tabular-nums text-text-3">
          {(ms / 1000).toFixed(1)}s
        </span>
      </div>
      <ul className="mt-3 space-y-1 text-[12px] text-text-3">
        {stages.map((s) => <li key={s}>· {t(s)}</li>)}
      </ul>
    </Card>
  )
}

/** The material the model was actually given.
 *
 *  The recurring question this answers is "did it read the summary or the
 *  text?" — and the honest reply is: the summary decides *which* node, the
 *  body is what gets read. `matches` are literal snippets with their section
 *  and line; `content` is the body when it fits the per-node budget, or the
 *  matched sections when it does not, or the outline when even those are too
 *  big. Showing it turns a claim into something checkable.
 */
function Material({ results, sources = [] }) {
  const { t } = useI18n()
  const scent = (id) => results.find((r) => r.id === id)?.summary
    || sources.find((s) => s.id === id)?.summary
  return (
    /* Out of the PDF: this is verbatim source, pages of it, and an export is
       the answer with its provenance — the evidence list and the walk say
       where it came from without reprinting the forest. */
    <div className="no-print mt-6 border-t border-line pt-4">
      <div className="label">{t('ask.material')}</div>
      <p className="mb-3 text-[12px] text-text-3">{t('ask.material_hint')}</p>
      <div className="space-y-2">
        {results.map((r) => (
          <details key={r.id} className="rounded-lg border border-line bg-surface">
            <summary className="flex cursor-pointer flex-wrap items-baseline gap-2 px-3 py-2">
              <span className="font-mono text-[12px] text-text">{r.id}</span>
              <span className="text-[11.5px] text-text-3">
                {t('ask.material_counts', {
                  m: r.matches?.length || 0,
                  s: r.content?.length || 0,
                })}
              </span>
              {r.found_by?.length > 0 && (
                <span className="ml-auto font-mono text-[10.5px] uppercase tracking-[0.08em]
                                 text-text-3">{r.found_by.join(' + ')}</span>
              )}
              {scent(r.id) && (
                <span className="w-full text-[11.5px] leading-relaxed text-text-3">
                  {scent(r.id)}
                </span>
              )}
            </summary>

            <div className="space-y-3 border-t border-line px-3 py-2.5">
              {r.matches?.length > 0 && (
                <ul className="space-y-1.5">
                  {r.matches.map((m, i) => (
                    <li key={i} className="text-[12px]">
                      <span className="font-mono text-[10.5px] text-text-3">
                        {m.section || '—'}:{m.line}
                      </span>
                      <p className="mt-0.5 border-l-2 border-accent/40 pl-2
                                    font-mono text-[11.5px] leading-relaxed text-text-2">
                        {m.snippet}
                      </p>
                    </li>
                  ))}
                </ul>
              )}

              {r.content?.map((c, i) => (
                /* Rows are a table. Rendering them as pretty-printed JSON
                   asked the reader to parse a serialisation of something
                   the console already knows how to draw. */
                c.columns ? <Rows key={i} {...c} /> : (
                  <div key={i}>
                    <div className="mb-1 text-[11px] text-text-3">
                      {c.section
                        ? t('ask.material_section', { s: c.section })
                        : c.outline ? t('ask.material_outline')
                        : t('ask.material_full')}
                      {c.body_tokens != null && ` · ${c.body_tokens} tokens`}
                    </div>
                    {c.body && (
                      <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words
                                      rounded-md bg-surface-2 p-2.5 font-mono text-[11.5px]
                                      leading-relaxed text-text-2">{c.body}</pre>
                    )}
                    {c.outline && (
                      <p className="font-mono text-[11.5px] text-text-3">
                        {(Array.isArray(c.outline) ? c.outline : [c.outline]).join(' · ')}
                      </p>
                    )}
                  </div>
                )
              ))}
            </div>
          </details>
        ))}
      </div>
    </div>
  )
}

/** The rows a `query` hop returned — the same grid the Data console draws,
 *  with the SQL that produced it above. */
function Rows({ sql, columns, rows, row_count, limited }) {
  const { t } = useI18n()
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline gap-2">
        <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-accent">{sql}</code>
        <span className="text-[11px] text-text-3">
          {t('data.rows', { n: row_count ?? rows.length })}
          {limited ? ` · ${t('data.limited')}` : ''}
        </span>
      </div>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-line bg-surface-2 text-left">
              {columns.map((c) => (
                <th key={c} className="whitespace-nowrap px-2.5 py-1.5 text-[10.5px]
                                       font-semibold uppercase tracking-[0.06em]
                                       text-text-3">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.slice(0, 20).map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} className="whitespace-nowrap px-2.5 py-1.5 font-mono
                                         tabular-nums text-text-2">
                    {cell === null ? '—' : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 20 && (
        <p className="mt-1 text-[11px] text-text-3">{t('ask.rows_more', { n: rows.length - 20 })}</p>
      )}
    </div>
  )
}

/** Where the forager went, hop by hop (J.10.5).
 *
 *  A row of tool names is not a walk: "sniff, sniff, locate" and "sniff → 0,
 *  sniff → 0, locate → 5" are the same list and opposite stories. Each hop
 *  therefore shows what the model chose (its own arguments) and what came
 *  back (one number), numbered so the order is unambiguous.
 */
function Path({ hops }) {
  const { t } = useI18n()
  const outcome = (out = {}) => {
    if (out.error) return t('ask.hop_error', { code: out.error })
    for (const [key, label] of [['results', 'ask.hop_results'], ['rows', 'ask.hop_rows'],
                                ['tokens', 'ask.hop_tokens'], ['nodes', 'ask.hop_nodes'],
                                ['neighbors', 'ask.hop_neighbors'],
                                ['children', 'ask.hop_children'],
                                ['edges', 'ask.hop_edges']]) {
      if (out[key] != null) return t(label, { n: out[key] })
    }
    return ''
  }
  const args = (a = {}) => Object.entries(a)
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(', ') : v}`).join(' · ')

  return (
    <div className="mt-6 border-t border-line pt-4">
      <div className="label">{t('ask.path')} · {t('ask.path_count', { n: hops.length })}</div>
      <p className="mb-2 text-[11px] text-text-3">{t('ask.path_clocks')}</p>
      <ol className="space-y-1">
        {hops.map((h, i) => (
          <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5
                                 rounded-md px-1.5 py-1 odd:bg-surface-2/40">
            <span className="w-4 shrink-0 text-right font-mono text-[10.5px] text-text-3">
              {h.n ?? i + 1}
            </span>
            <span className={`font-mono text-[12px] font-medium
                              ${h.ok ? 'text-text' : 'text-danger'}`}>{h.tool}</span>
            {h.id && <span className="font-mono text-[11px] text-text-2">{h.id}</span>}
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-text-3">
              {args(h.args)}
            </span>
            <span className={`shrink-0 text-[11px] tabular-nums
                              ${h.ok ? 'text-text-3' : 'text-danger'}`}>
              {outcome(h.out)}
            </span>
            {/* Two clocks, because they are two costs: the forest call, and
                the model turn that decided to make it. Reporting one number
                would hide which half a slow hunt is actually spending. */}
            <span className="shrink-0 font-mono text-[11px] tabular-nums text-text-2">
              {h.ms != null && `${h.ms < 10 ? h.ms.toFixed(2) : Math.round(h.ms)} ms`}
              {h.model_ms != null && (
                <span className="text-text-3"> + {Math.round(h.model_ms)} ms</span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

/** What the call actually did, step by step (J.10.4).
 *
 *  `answer` is one request and several forest calls plus a provider round
 *  trip. One elapsed number cannot say which of those to fix, and the
 *  usual suspicion — "the forest is slow" — is almost always wrong: the
 *  retrieval half runs in single-digit milliseconds and the model does not.
 */
function Explain({ trace, wall, hybrid, cost, timing }) {
  const { t } = useI18n()
  if (!trace?.steps?.length) return null

  const worst = Math.max(...trace.steps.map((s) => s.ms), 1)
  // The gap between the client's stopwatch and the host's own span: TLS, the
  // network, HTTP framing, JSON, this render. Named rather than hidden, so
  // the columns add up. J.10.6's header makes the host's share a measured
  // number instead of a lump in the remainder — without it, the sum of the
  // steps is the best the console can subtract.
  const served = timing
    ? timing.vine + (timing.model || 0) + timing.host
    : trace.total_ms
  const overhead = wall != null ? Math.max(0, wall - served) : null

  return (
    <Card title={t('explain.title')} subtitle={t('explain.sub')}>
      <div className="grid grid-cols-2 gap-2">
        <Metric label={t('explain.retrieval')} value={`${trace.retrieval_ms} ms`} tone="accent" />
        <Metric label={t('explain.model')}
                value={trace.steps.find((s) => s.step === 'model')
                  ? `${trace.steps.find((s) => s.step === 'model').ms} ms` : '—'} />
      </div>

      <ol className="mt-4 space-y-2.5">
        {trace.steps.map((s, i) => (
          <li key={i}>
            <div className="flex items-baseline gap-2">
              {/* Which decision caused this step. Without it the panel is a
                  list of primitives and the walk is somewhere else. */}
              {s.hop != null && (
                <span className="shrink-0 rounded bg-accent-soft px-1 font-mono
                                 text-[10px] font-semibold text-accent">
                  {t('explain.hop_n', { n: s.hop })}
                </span>
              )}
              <span className="font-mono text-[12px] font-medium text-text">{s.step}</span>
              {s.id && <span className="min-w-0 flex-1 truncate font-mono text-[11px]
                                        text-text-3">{s.id}</span>}
              <span className="ml-auto shrink-0 font-mono text-[11.5px] text-text-2">
                {s.ms} ms
              </span>
            </div>
            {/* Proportional to the slowest step, not to the total: the model
                dwarfs everything, and a bar chart scaled to it would render
                every retrieval step as the same invisible sliver. */}
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-surface-2">
              <div className={`h-full rounded-full ${s.step === 'model' ? 'bg-text-3' : 'bg-accent'}`}
                   style={{ width: `${Math.max(2, (s.ms / worst) * 100)}%` }} />
            </div>
            {s.detail && <p className="mt-1 truncate text-[11px] text-text-3">{s.detail}</p>}
          </li>
        ))}
      </ol>

      <dl className="mt-4 space-y-1.5 border-t border-line pt-3 text-[11.5px]">
        <Row label={t('explain.steps')} value={trace.steps.length} />
        <Row label={t('explain.server')} value={`${trace.total_ms} ms`} />
        {timing && <Row label={t('explain.host')} value={fmtMs(timing.host)} />}
        {overhead != null && <Row label={t('explain.transport')} value={fmtMs(overhead)} />}
        <Row label={t('explain.entry')}
             value={t(hybrid ? 'explain.entry_hybrid' : 'explain.entry_bm25')} />
      </dl>

      {cost && (
        <dl className="mt-3 space-y-1.5 border-t border-line pt-3 text-[11.5px]">
          <Row label={t('explain.tokens_in')} value={cost.prompt_tokens.toLocaleString()} />
          <Row label={t('explain.tokens_out')} value={cost.completion_tokens.toLocaleString()} />
          <Row label={t('explain.calls')} value={cost.calls} />
          {/* An unknown price is not a free one: a local Ollama publishes no
              rate, and rendering that as $0.00 would be a claim. */}
          {cost.priced ? (
            <div className="flex items-baseline justify-between gap-3 pt-1">
              <dt className="font-medium text-text-2">{t('explain.cost')}</dt>
              <dd className="font-mono font-semibold text-accent">
                {cost.usd < 0.01 ? `$${cost.usd.toFixed(6)}` : `$${cost.usd.toFixed(4)}`}
              </dd>
            </div>
          ) : (
            <p className="pt-1 text-[11px] text-text-3">{t('explain.cost_unknown')}</p>
          )}
        </dl>
      )}
    </Card>
  )
}

const Row = ({ label, value }) => (
  <div className="flex items-baseline justify-between gap-3">
    <dt className="text-text-3">{label}</dt>
    <dd className="font-mono text-text-2">{value}</dd>
  </div>
)
