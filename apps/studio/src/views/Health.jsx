// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The Health console (spec J.13) — what the Ranger sees.
 *
 * Part H has been able to describe a forest's shape since v0.10, and the
 * only way to read it was a shell. This is that report, relayed: every
 * number here is one `Ranger.health()` computed, and the console adds no
 * arithmetic of its own — a second opinion about a forest's health is worse
 * than none.
 *
 * Reading changes nothing. Evaporation and promote/prune are the Ranger's
 * own scheduled run, deliberately not a side effect of opening a page.
 */
import { useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Empty, ErrorNote, Note, Skeleton, Toggle,
} from '../design/ui.jsx'
import {
  Alert, Check, Download, Flame, Health as HealthIcon, Link, Refresh,
} from '../design/icons.jsx'
import { NeedsCapability, has, useAsync } from './shared.jsx'

export default function Health({ forest, grant, goto, me }) {
  const { t } = useI18n()

  if (!has(grant, 'admin')) {
    return <NeedsCapability message={t('health.needs_admin')} hint={t('cap.admin')} />
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <Report forest={forest} goto={goto} />
      <Snapshots forest={forest} me={me} />
    </div>
  )
}

function Report({ forest, goto }) {
  const { t } = useI18n()
  const report = useAsync(() => api.forestHealth(forest), [forest])

  if (report.busy) return <Card><Skeleton rows={7} /></Card>
  if (report.error) {
    // Two refusals worth explaining rather than showing raw: a scoped
    // admin is asking for a shape this report does not have, and a locked
    // forest is a state this console can actually repair (J.13.5).
    const scoped = report.error.status === 403
      && /whole forest/i.test(report.error.message || '')
    const locked = report.error.code === 'E_LOCKED'
    return (
      <Card title={t('health.title')} icon={HealthIcon}>
        {locked
          ? <LockPanel forest={forest} onCleared={report.reload} />
          : scoped
            ? <Empty icon={Alert} title={t('health.scoped')}>{t('health.scoped_hint')}</Empty>
            : <ErrorNote error={report.error} onRetry={report.reload} />}
      </Card>
    )
  }

  const d = report.data
  const lint = d.lint || {}
  const proposals = Object.entries(d.uncertain_links || {})
    .sort((a, b) => Number(a[0]) - Number(b[0]))
  const clear = !lint.errors && !lint.warnings && !d.needs_split?.length
    && !d.fat_nodes?.length && !d.stale_passports?.length
    && !d.needs_description?.length

  return (
    <div className="min-w-0 space-y-4">
      <Card title={t('health.title')} subtitle={t('health.sub')} icon={HealthIcon}
            actions={<button className="btn btn-sm" onClick={report.reload}>
              <Refresh size={14} /> {t('common.refresh')}
            </button>}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Count label={t('health.lint_errors')} value={lint.errors || 0} tone="danger" />
          <Count label={t('health.lint_warnings')} value={lint.warnings || 0} tone="warn" />
          <Count label={t('health.needs_split')} value={d.needs_split?.length || 0} tone="warn" />
          <Count label={t('health.fat_nodes')} value={d.fat_nodes?.length || 0} tone="warn" />
        </div>
        {clear && <Note tone="ok" className="mt-4">
          <span className="inline-flex items-center gap-1.5">
            <Check size={14} /> {t('health.all_clear')}
          </span>
        </Note>}
      </Card>

      <NodeList title={t('health.needs_split')} hint={t('health.needs_split_hint')}
                ids={d.needs_split} goto={goto} />
      <NodeList title={t('health.fat_nodes')} hint={t('health.fat_nodes_hint')}
                ids={d.fat_nodes} goto={goto} />
      <NodeList title={t('health.stale_passports')}
                hint={t('health.stale_passports_hint')}
                ids={d.stale_passports} goto={goto} />
      <NodeList title={t('health.needs_description')}
                hint={t('health.needs_description_hint')}
                ids={d.needs_description} goto={goto} />

      {proposals.length > 0 && (
        <Card title={t('health.uncertain')} subtitle={t('health.uncertain_hint')}
              icon={Link}>
          <div className="flex flex-wrap gap-2">
            {/* `0.5` and `1` side by side read as one number, so the count
                is labelled rather than merely spaced. */}
            {proposals.map(([confidence, n]) => (
              <span key={confidence} className="badge">
                <span className="font-mono">{t('health.confidence', { c: confidence })}</span>
                <span className="text-line-strong">·</span>
                <span>{t('health.links_n', { n })}</span>
              </span>
            ))}
          </div>
        </Card>
      )}

      <Card title={t('health.heat')} icon={Flame}>
        <p className="text-[13.5px] text-text">
          {t('health.heat_rows', { n: d.heat?.rows ?? 0 })}
        </p>
        <p className="mt-0.5 text-[12.5px] text-text-3">
          {t('health.heat_stats', { max: d.heat?.max ?? 0, mean: d.heat?.mean ?? 0 })}
        </p>
      </Card>
    </div>
  )
}

/* J.13.5: the refusal explained where it appears. The card is C.9's
 * holder card; the release is the API's own `unlock`, which refuses a
 * live writer — this console gains no path the API refuses. */
function LockPanel({ forest, onCleared }) {
  const { t } = useI18n()
  const lock = useAsync(() => api.locks(forest), [forest])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function release() {
    setBusy(true)
    setError(null)
    try {
      await api.unlock(forest)
      onCleared?.()
    } catch (e) { setError(e) } finally { setBusy(false) }
  }

  if (lock.busy) return <Skeleton rows={3} />
  if (lock.error) return <ErrorNote error={lock.error} onRetry={lock.reload} />
  const d = lock.data || {}
  const holder = d.holder || {}
  const releasable = d.state === 'orphan'
    || (d.state === 'held' && d.verified === false && !d.self)
  return (
    <div className="space-y-3">
      <Empty icon={Alert} title={t('health.locked')}>
        {releasable ? t('health.locked_orphan')
          : d.self ? t('health.locked_self') : t('health.locked_held')}
      </Empty>
      {holder.pid && (
        <p className="text-center font-mono text-[12px] text-text-3">
          {t('health.lock_holder', {
            pid: holder.pid, host: holder.host || '?', since: holder.since || '?',
          })}
        </p>
      )}
      {releasable && (
        <div className="text-center">
          <button className="btn btn-primary btn-sm" onClick={release} disabled={busy}>
            {busy ? t('health.releasing') : t('health.release')}
          </button>
        </div>
      )}
      <ErrorNote error={error} />
    </div>
  )
}

function Count({ label, value, tone }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-3 py-2">
      <div className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-text-3">
        {label}
      </div>
      <div className={`mt-0.5 text-[19px] font-medium tabular-nums
        ${value === 0 ? 'text-text-3'
          : tone === 'danger' ? 'text-danger' : tone === 'warn' ? 'text-warn' : 'text-text'}`}>
        {value}
      </div>
    </div>
  )
}

/** An empty list is not a card. Only what needs attention is shown, so the
 *  page is as short as the forest is healthy. */
function NodeList({ title, hint, ids, goto }) {
  if (!ids?.length) return null
  return (
    <Card title={title} subtitle={hint} icon={Alert}
          actions={<Badge tone="warn">{ids.length}</Badge>}>
      <ul className="flex flex-wrap gap-1.5">
        {ids.slice(0, 60).map((id) => (
          <li key={id}>
            <button className="badge font-mono hover:border-accent/40 hover:text-accent"
                    onClick={() => goto?.('explore', id)}>
              {id}
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Snapshots({ forest, me }) {
  const { t } = useI18n()
  const [payloads, setPayloads] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const list = useAsync(() => api.snapshots(forest), [forest])

  async function take() {
    setBusy(true)
    setError(null)
    try {
      await api.takeSnapshot(forest, payloads)
      list.reload()
    } catch (e) { setError(e) } finally { setBusy(false) }
  }

  // J.13.1 is owner-only; the host refuses everyone else regardless, the
  // console just doesn't offer a dead door.
  async function download(name) {
    setError(null)
    try { await api.downloadSnapshot(forest, name) } catch (e) { setError(e) }
  }

  return (
    <Card title={t('health.snapshots')} subtitle={t('health.snapshots_sub')}
          icon={Download}>
      <Toggle checked={payloads} onChange={setPayloads}
              label={t('health.with_payloads')} />
      <button className="btn btn-primary btn-sm mt-3" onClick={take} disabled={busy}>
        {busy ? t('health.taking') : t('health.take')}
      </button>
      <ErrorNote error={error} />

      <div className="mt-4">
        {list.busy ? <Skeleton rows={3} />
          : list.error ? <ErrorNote error={list.error} onRetry={list.reload} />
          : !list.data?.snapshots?.length
            ? <p className="text-[12.5px] text-text-3">{t('health.no_snapshots')}</p>
            : (
              <ul className="divide-y divide-line">
                {list.data.snapshots.map((s) => (
                  <li key={s.name} className="py-2 first:pt-0">
                    <div className="flex items-center gap-1.5">
                      <div className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-text-2">
                        {s.name}
                      </div>
                      {me?.owner && (
                        <button className="btn btn-sm btn-ghost !px-1.5"
                                title={t('health.download')}
                                onClick={() => download(s.name)}>
                          <Download size={13} />
                        </button>
                      )}
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-text-3">
                      <span>{(s.bytes / 1024).toFixed(1)} kB</span>
                      <span>{s.created?.slice(0, 16).replace('T', ' ')}</span>
                      {s.payloads && (me?.owner
                        ? <button className="badge hover:border-accent/40 hover:text-accent"
                                  title={t('health.download_payloads')}
                                  onClick={() => download(`${s.name}.payloads.zip`)}>
                            payloads
                          </button>
                        : <Badge>payloads</Badge>)}
                    </div>
                  </li>
                ))}
              </ul>
            )}
      </div>

      <Note className="mt-4">{t('health.restore_note')}</Note>
    </Card>
  )
}
