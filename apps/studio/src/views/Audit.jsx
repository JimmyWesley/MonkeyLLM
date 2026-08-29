// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The Audit console (spec J.5.16).
 *
 * An operator opens this screen holding two questions — is anything wrong,
 * and what is this costing me — and for a long time it answered neither: one
 * page of one table, `ok` in every row, no cost anywhere and no way to ask
 * for less than everything. The row carries the answers now (J.4.2) and the
 * route carries the filters and the totals (J.4.3), so the work here is to
 * read them and to not have a second opinion about any of it.
 *
 * The numbers above the table are the host's `totals`, over the whole
 * filtered set. They are NEVER summed from `entries`: a count of the rows on
 * screen is a fact about the page size, and it would fall the moment somebody
 * changed the limit. Same reasoning as J.10.6's — the console reports the
 * host's instrument, it does not build one.
 *
 * The two money figures stay apart because they are different facts. What a
 * provider was paid is spend; what the answer store made unnecessary is a
 * saving, and a single "cost" covering both is a bill nobody can reconcile.
 */

import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { useRouteState } from '../router.js'
import {
  Badge, Card, Empty, ErrorNote, Note, Segmented, Select, Skeleton, Stat, Table, Td,
} from '../design/ui.jsx'
import { Alert, Audit as Log, Models, Refresh, Save } from '../design/icons.jsx'
import { NeedsCapability, has, useAsync } from './shared.jsx'

/** Money as the provider priced it. Never rounded to `$0.00`: a sweep costs
 *  fractions of a cent and two decimals would report every one of them as
 *  free, which is the claim J.5.16 rule 4 exists to prevent. */
function money(usd) {
  const n = Number(usd) || 0
  if (n === 0) return '$0'
  if (n >= 1) return `$${n.toFixed(2)}`
  if (n >= 0.01) return `$${n.toFixed(3)}`
  return `$${n.toFixed(5)}`
}

/** Milliseconds, at the precision they are worth reading at. */
function millis(ms) {
  const n = Number(ms)
  if (!Number.isFinite(n)) return null
  if (n >= 1000) return `${(n / 1000).toFixed(1)} s`
  return `${n < 10 ? n.toFixed(2) : Math.round(n)} ms`
}

/** The argument digest, as stored (J.4). It is the only field in the row
 *  that says WHICH node was read, and it arrives as the JSON text the
 *  registry wrote — parsed here rather than server-side so the response
 *  stays byte-identical to the one older clients already read. */
function digestOf(args) {
  try {
    const parsed = JSON.parse(args || '{}')
    return parsed && typeof parsed === 'object' ? Object.entries(parsed) : []
  } catch {
    return []
  }
}

function Digest({ args }) {
  const pairs = digestOf(args)
  if (!pairs.length) return <span className="text-text-3">—</span>
  return (
    <div className="flex max-w-[26rem] flex-wrap gap-1">
      {pairs.map(([k, v]) => (
        <span key={k} className="badge max-w-full font-mono text-[11px]">
          <span className="text-text-3">{k}</span>
          <span className="truncate">{String(v)}</span>
        </span>
      ))}
    </div>
  )
}

export default function Audit({ grant }) {
  const { t } = useI18n()
  const admin = has(grant, 'admin')

  // J.5.16 rule 5: every filter is in the address, so a filtered view is a
  // link somebody can send to whoever has to look at it.
  const [who, setWho] = useRouteState('who', '')
  const [call, setCall] = useRouteState('call', '')
  const [where, setWhere] = useRouteState('where', '')
  const [outcome, setOutcome] = useRouteState('outcome', '', { allow: ['errors', 'cache'] })
  const [since, setSince] = useRouteState('since', '')
  const [until, setUntil] = useRouteState('until', '')

  const log = useAsync(() => api.audit({
    principal: who,
    primitive: call,
    forest: where,
    // Two different questions over one control: "only the refusals" is a
    // predicate over several result values, "only the ones the store served"
    // is one value. The route spells them separately and so does this.
    errors: outcome === 'errors' ? 1 : '',
    result: outcome === 'cache' ? 'cache' : '',
    since,
    until,
  }), [who, call, where, outcome, since, until], { skip: !admin })

  if (!admin) {
    return <NeedsCapability message={t('audit.needs_admin')} hint={t('cap.admin')} />
  }

  const rows = log.data?.entries || []
  const totals = log.data?.totals || {}
  const facets = log.data?.filters || {}
  const forests = facets.forests || []
  const filtered = who || call || where || outcome || since || until

  const clear = () => {
    setWho(''); setCall(''); setWhere(''); setOutcome(''); setSince(''); setUntil('')
  }

  // Named `covered`, not `window`: a `const window` inside a component
  // shadows the global one for the whole scope, which is a trap the next
  // edit walks into rather than a bug today.
  const covered = totals.first && totals.last
    ? `${totals.first.slice(0, 10)} → ${totals.last.slice(0, 10)}`
    : t('audit.window_none')

  return (
    <div className="space-y-4">
      {/* The set, before any row of it (J.5.16 rule 1). */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat icon={Log} label={t('audit.stat.calls')}
              value={log.busy ? '—' : (totals.calls ?? 0).toLocaleString()}
              hint={log.busy ? '' : t('audit.stat.calls_hint', {
                people: totals.people ?? 0, window: covered,
              })} />
        <Stat icon={Alert} tone={totals.errors ? 'danger' : 'muted'}
              label={t('audit.stat.errors')}
              value={log.busy ? '—' : (totals.errors ?? 0).toLocaleString()}
              hint={t('audit.stat.errors_hint')} />
        <Stat icon={Models} label={t('audit.stat.spent')}
              value={log.busy ? '—'
                : (totals.usd ? money(totals.usd)
                  : totals.unpriced ? '—' : money(0))}
              hint={log.busy ? ''
                : totals.unpriced
                  ? t('audit.stat.unpriced', { n: totals.unpriced })
                  : t('audit.stat.spent_hint', {
                    tokens: (totals.tokens ?? 0).toLocaleString(),
                  })} />
        {/* Never added into the figure beside it: this is the money that was
            NOT paid, and the two sum to nothing meaningful (J.4.2). */}
        <Stat icon={Save} tone={totals.usd_saved ? 'accent' : 'muted'}
              label={t('audit.stat.saved')}
              value={log.busy ? '—' : money(totals.usd_saved)}
              hint={log.busy ? ''
                : t('audit.stat.saved_hint', { n: totals.cached ?? 0 })} />
      </div>

      <Card title={t('audit.title')} subtitle={t('audit.sub')} icon={Log}
            actions={<button className="btn btn-sm" onClick={log.reload}>
              <Refresh size={14} /> {t('common.refresh')}
            </button>}>
        {/* J.5.16 rule 8: the choices are the values the response says occur.
            A list carried in the console goes stale the release after it is
            written, and it goes stale silently — the filter simply stops
            offering the call that was added. */}
        <div className="mb-4 flex flex-wrap items-end gap-2">
          <Select className="w-44" value={who} onChange={(e) => setWho(e.target.value)}>
            <option value="">{t('audit.any_person')}</option>
            {(facets.principals || []).map((p) => <option key={p} value={p}>{p}</option>)}
          </Select>
          <Select className="w-44" value={call} onChange={(e) => setCall(e.target.value)}>
            <option value="">{t('audit.any_call')}</option>
            {(facets.primitives || []).map((p) => <option key={p} value={p}>{p}</option>)}
          </Select>
          {forests.length > 1 && (
            <Select className="w-48" value={where} onChange={(e) => setWhere(e.target.value)}>
              <option value="">{t('audit.any_forest')}</option>
              {forests.map((f) => <option key={f} value={f}>{f}</option>)}
            </Select>
          )}
          <Segmented className="whitespace-nowrap" value={outcome}
                     onChange={setOutcome}
                     options={[
                       { value: '', label: t('audit.all') },
                       { value: 'errors', label: t('audit.only_errors') },
                       { value: 'cache', label: t('audit.only_cache') },
                     ]} />
          <label className="flex items-center gap-1.5 text-[12px] text-text-3">
            {t('audit.from')}
            <input type="date" className="field !w-auto !py-1.5 text-[12.5px]"
                   value={since} onChange={(e) => setSince(e.target.value)} />
          </label>
          <label className="flex items-center gap-1.5 text-[12px] text-text-3">
            {t('audit.to')}
            <input type="date" className="field !w-auto !py-1.5 text-[12.5px]"
                   value={until} onChange={(e) => setUntil(e.target.value)} />
          </label>
          {filtered && (
            <button className="btn btn-sm" onClick={clear}>{t('audit.clear')}</button>
          )}
        </div>

        {log.busy ? <Skeleton rows={6} />
          : log.error ? <ErrorNote error={log.error} onRetry={log.reload} />
          : rows.length === 0 ? (
            /* An empty page under a filter is not an empty log, and saying
               "nothing recorded yet" there sends somebody to look for the
               traffic they can already see under the filter next to it. */
            <Empty icon={Log}
                   title={filtered ? t('audit.none_here') : t('audit.none')}
                   action={filtered
                     ? <button className="btn btn-sm" onClick={clear}>
                         {t('audit.clear')}
                       </button>
                     : null} />
          ) : (
          <Table head={[t('audit.when'), t('audit.who'), t('audit.what'),
                        t('audit.args'),
                        ...(forests.length > 1 ? [t('audit.where')] : []),
                        t('audit.result'), t('audit.took'), t('audit.cost'),
                        t('audit.size'), t('audit.commit')]}>
            {rows.map((e, i) => (
              <tr key={i}>
                {/* `ts` is the column's name and always was. The console
                    read `e.at`, so the one column every row of this log has
                    always had rendered empty. */}
                <Td className="whitespace-nowrap font-mono text-[11.5px] text-text-3">
                  {String(e.ts || '').replace('T', ' ').slice(0, 19)}
                </Td>
                <Td className="font-medium text-text">{e.principal}</Td>
                <Td><Badge tone="accent">{e.primitive}</Badge></Td>
                <Td><Digest args={e.args} /></Td>
                {forests.length > 1 && (
                  <Td className="font-mono text-[11.5px] text-text-3">{e.forest}</Td>
                )}
                <Td>
                  {/* An unknown code renders as itself: a Station newer than
                      this console must not lose the reason it refused. */}
                  {e.error_code ? <Badge tone="danger">{e.error_code}</Badge>
                    : e.result === 'ok' ? <Badge>ok</Badge>
                    : e.result === 'cache' ? <Badge tone="warn">{t('audit.from_store')}</Badge>
                    : <Badge tone="danger">{e.result}</Badge>}
                </Td>
                <Td className="whitespace-nowrap tabular-nums text-text-2">
                  {/* The forest's own clock first (J.10.6), the provider's
                      beneath it: they are different bills and the fix for
                      each is a different purchase. */}
                  {millis(e.ms) || <span className="text-text-3">—</span>}
                  {e.model_ms !== undefined && (
                    <span className="mt-0.5 block text-[11px] text-text-3">
                      {t('audit.model_took', { ms: millis(e.model_ms) })}
                    </span>
                  )}
                </Td>
                <Td className="whitespace-nowrap tabular-nums">
                  {e.priced ? (
                    <span className={e.result === 'cache' ? 'text-text-3' : 'text-text-2'}>
                      {e.result === 'cache' ? t('audit.saved_cell', { usd: money(e.usd) })
                        : money(e.usd)}
                    </span>
                  ) : e.tokens !== undefined ? (
                    <span className="text-text-3">
                      {t('audit.tokens_only', { tokens: e.tokens.toLocaleString() })}
                    </span>
                  ) : <span className="text-text-3">—</span>}
                </Td>
                <Td className="tabular-nums text-text-3">{e.size}</Td>
                <Td className="font-mono text-[11.5px] text-text-3">
                  {e.commit_sha ? e.commit_sha.slice(0, 7) : '—'}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Note>{t('audit.no_bodies')}</Note>
    </div>
  )
}
