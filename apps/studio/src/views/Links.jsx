// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The review of uncertain links (spec J.18, H.2.1).
 *
 * A `related-to` proposal is born at link-level `confidence: 0.3` because a
 * model asserted it and something ELSE has to confirm it (G.4.2.1). Until
 * v0.75 the only "something else" was heat, so a correct proposal between
 * two nodes nobody has walked stayed at 0.3 forever — and in a forest that
 * has just been ingested every node is cold by definition, which is exactly
 * when the proposals are worth reading. This screen is the person's vote.
 *
 * What this file exists to get right:
 *
 * - **Both endpoints' summaries, side by side.** A decision about adjacency
 *   is made on the scent, which is what the proposal itself was made on. No
 *   bodies are fetched and none are shown.
 * - **Both heats, printed.** They are the answer to "why has this not been
 *   promoted already" (H.2 promotes when BOTH endpoints are warm). Without
 *   them the reviewer is asked to second-guess a rule they cannot see.
 * - **A group is the unit.** Proposals are born up to three at a time on one
 *   document, so a source node's proposals settle in ONE action — one POST
 *   carrying several votes, not a loop of requests a refusal can strand
 *   half-finished.
 * - **No "accept all" over the page.** A control that settles what is off
 *   screen turns a review into a rubber stamp, and the confidence it writes
 *   would then record nothing. Every group action names its own node.
 * - **Progress is never rounded up.** The host reports the outcome of every
 *   vote sent — `accepted`, `rejected`, `unchanged`, `missing`, `refused` —
 *   and this console renders all five. A partial run says so.
 * - **An empty queue is a fact** (J.5.4), not a console that failed to load.
 *
 * The page cursor rides the address (J.5.8), so a review interrupted by a
 * reload resumes on the page it was on rather than at the beginning.
 */
import { useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { useRouteState } from '../router.js'
import {
  Badge, Card, Empty, ErrorNote, Note, Skeleton,
} from '../design/ui.jsx'
import {
  Alert, Check, ChevronLeft, ChevronRight, Flame, Link, X,
} from '../design/icons.jsx'
import { NeedsCapability, has, useAsync } from './shared.jsx'

/** The five outcomes the host can report, split by what they mean for the
 *  reviewer: three settled the link, two did not. */
const SETTLED = ['accepted', 'rejected', 'unchanged']
const UNSETTLED = ['missing', 'refused']

export default function Links({ forest, grant, goto }) {
  const { t } = useI18n()
  // Cursor pages, in the address: `after` is the last source id of the
  // previous page, and the trail of ids we walked through to get here is
  // what makes "back" possible without a second copy of the state.
  const [after, setAfter] = useRouteState('after', '')
  const [trail, setTrail] = useState([])
  const [outcomes, setOutcomes] = useState(null)   // last batch's report
  const [busy, setBusy] = useState(null)           // the group id in flight
  const [error, setError] = useState(null)

  const page = useAsync(
    () => api.uncertainLinks(forest, { after }),
    [forest, after],
    { skip: !has(grant, 'write') })

  if (!has(grant, 'write')) {
    return <NeedsCapability message={t('links.needs_write')} hint={t('cap.write')} />
  }

  /** One POST for however many votes the action covers (J.18): fifty
   *  independent decisions, each its own commit, none of them lost because
   *  another one was refused. */
  async function cast(groupId, votes) {
    setBusy(groupId)
    setError(null)
    setOutcomes(null)
    try {
      const r = await api.voteLinks(forest, votes)
      setOutcomes({ sent: votes.length, votes: r.votes || [], counts: r.counts || {} })
      page.reload()
    } catch (e) { setError(e) } finally { setBusy(null) }
  }

  const forward = (next) => { setTrail((p) => [...p, after]); setAfter(next) }
  const back = () => {
    const prev = trail[trail.length - 1] ?? ''
    setTrail((p) => p.slice(0, -1))
    setAfter(prev)
  }

  const d = page.data
  const groups = d?.groups || []

  return (
    <div className="min-w-0 space-y-4">
      <Card title={t('links.title')} subtitle={t('links.sub')} icon={Link}
            actions={d ? <Badge>{t('links.pending', { n: d.total ?? 0 })}</Badge> : null}>
        <p className="text-[12.5px] text-text-3">{t('links.why')}</p>
      </Card>

      <Report report={outcomes} onDismiss={() => setOutcomes(null)} />
      <ErrorNote error={error} />

      {page.busy ? <Card><Skeleton rows={6} /></Card>
        : page.error ? <Card><ErrorNote error={page.error} onRetry={page.reload} /></Card>
        : !groups.length ? (
          <Card>
            <Empty icon={Check} title={after ? t('links.page_empty') : t('links.none')}>
              {after ? t('links.page_empty_hint') : t('links.none_hint')}
            </Empty>
            {after ? (
              <div className="text-center">
                <button className="btn btn-sm" onClick={back}>
                  <ChevronLeft size={13} /> {t('links.back')}
                </button>
              </div>
            ) : null}
          </Card>
        ) : groups.map((g) => (
          <Group key={g.source.id} group={g} goto={goto}
                 busy={busy === g.source.id} onVote={cast} />
        ))}

      {(trail.length > 0 || d?.next) && (
        <div className="flex items-center justify-between">
          <button className="btn btn-sm" disabled={!trail.length} onClick={back}>
            <ChevronLeft size={13} /> {t('links.back')}
          </button>
          <span className="text-[12px] text-text-3">
            {t('links.showing', { n: groups.length, total: d?.total ?? 0 })}
          </span>
          <button className="btn btn-sm" disabled={!d?.next}
                  onClick={() => forward(d.next)}>
            {t('links.next')} <ChevronRight size={13} />
          </button>
        </div>
      )}
    </div>
  )
}

/** One source node and its proposals. The group is the action's boundary:
 *  its two buttons name THIS node and reach nothing off screen. */
function Group({ group, goto, busy, onVote }) {
  const { t } = useI18n()
  const src = group.source
  const all = (vote) => group.links.map((l) => ({
    id: src.id, rel: l.rel, target: l.target.id, vote,
  }))

  return (
    <Card icon={Link}
          title={src.title || src.id}
          subtitle={src.summary}
          actions={<Badge tone="warn">{t('links.n_here', { n: group.links.length })}</Badge>}>
      <div className="flex flex-wrap items-center gap-2">
        <button className="badge font-mono hover:border-accent/40 hover:text-accent"
                onClick={() => goto?.('read', src.id)}>{src.id}</button>
        <Heat value={src.heat} />
      </div>

      <ul className="mt-3 divide-y divide-line">
        {group.links.map((l) => (
          <li key={`${l.rel}:${l.target.id}`} className="py-3 first:pt-0 last:pb-0">
            <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-start">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge>{l.rel}</Badge>
                  <Badge tone="warn">{t('links.confidence', { c: l.confidence })}</Badge>
                  <button className="badge font-mono hover:border-accent/40 hover:text-accent"
                          onClick={() => goto?.('read', l.target.id)}>
                    {l.target.id}
                  </button>
                  <Heat value={l.target.heat} />
                </div>
                <p className="mt-1 text-[13.5px] font-medium text-text">
                  {l.target.title || l.target.id}
                </p>
                <p className="mt-0.5 text-[12.5px] text-text-2">{l.target.summary}</p>
                {l.note && (
                  <p className="mt-1 text-[12px] italic text-text-3">
                    {t('links.note', { note: l.note })}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 gap-1.5">
                <button className="btn btn-sm btn-primary" disabled={busy}
                        onClick={() => onVote(src.id, [{
                          id: src.id, rel: l.rel, target: l.target.id, vote: 'accept',
                        }])}>
                  <Check size={13} /> {t('links.accept')}
                </button>
                <button className="btn btn-sm" disabled={busy}
                        onClick={() => onVote(src.id, [{
                          id: src.id, rel: l.rel, target: l.target.id, vote: 'reject',
                        }])}>
                  <X size={13} /> {t('links.reject')}
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>

      {group.links.length > 1 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="text-[12px] text-text-3">{t('links.settle_all')}</span>
          <button className="btn btn-sm btn-primary" disabled={busy}
                  onClick={() => onVote(src.id, all('accept'))}>
            <Check size={13} /> {t('links.accept_group', { n: group.links.length })}
          </button>
          <button className="btn btn-sm" disabled={busy}
                  onClick={() => onVote(src.id, all('reject'))}>
            <X size={13} /> {t('links.reject_group', { n: group.links.length })}
          </button>
        </div>
      )}
    </Card>
  )
}

/** H.2's own evidence, printed. `0` is the interesting value here — it is
 *  why the Ranger could never promote this link — so it is shown, never
 *  hidden as an empty state. */
function Heat({ value }) {
  const { t } = useI18n()
  return (
    <span className="badge" title={t('links.heat_hint')}>
      <Flame size={11} />
      <span className="font-mono tabular-nums">{Number(value ?? 0).toFixed(2)}</span>
    </span>
  )
}

/** What the last batch actually did. Never a claim of completion: the host
 *  reports five outcomes and two of them mean the link was NOT settled, so
 *  those are named individually with the ids they belong to. */
function Report({ report, onDismiss }) {
  const { t } = useI18n()
  if (!report) return null
  const settled = SETTLED.reduce((n, k) => n + (report.counts[k] || 0), 0)
  const left = report.votes.filter((v) => UNSETTLED.includes(v.outcome))
  return (
    <Card icon={left.length ? Alert : Check}
          title={t('links.report', { settled, sent: report.sent })}
          actions={<button className="btn btn-sm btn-ghost !px-1.5" onClick={onDismiss}>
            <X size={13} />
          </button>}>
      <div className="flex flex-wrap gap-2">
        {SETTLED.filter((k) => report.counts[k]).map((k) => (
          <Badge key={k} tone="accent">{t(`links.outcome_${k}`, { n: report.counts[k] })}</Badge>
        ))}
        {UNSETTLED.filter((k) => report.counts[k]).map((k) => (
          <Badge key={k} tone="warn">{t(`links.outcome_${k}`, { n: report.counts[k] })}</Badge>
        ))}
      </div>
      {left.length > 0 && (
        <div className="mt-3">
          <Note tone="warn">{t('links.not_settled')}</Note>
          <ul className="mt-2 space-y-1">
            {left.map((v, i) => (
              <li key={i} className="font-mono text-[11.5px] text-text-3">
                {v.rel} → {v.target} · {t(`links.outcome_one_${v.outcome}`)}
                {v.message ? ` · ${v.message}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  )
}
