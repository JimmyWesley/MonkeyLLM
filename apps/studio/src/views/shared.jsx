// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Small pieces every console needs, in one place so nine views cannot drift
 * into nine subtly different ideas of "loading" or "you may not do this". */
import { useCallback, useEffect, useState } from 'react'
import { hrefFor, linkTo } from '../router.js'
import { branchIdFor, branchOf } from '../nodes.js'
import { useI18n } from '../i18n.jsx'
import { Card, Empty, ErrorNote, Field, Modal, Select, TextArea } from '../design/ui.jsx'
import { Access, Plus } from '../design/icons.jsx'

export const ALL_CAPS = ['read', 'query', 'write', 'tend', 'ingest', 'admin']

/** Props for an anchor that opens a node in Explore (J.5.8).
 *
 *  A node is an address, so every reference to one — a citation, an ingest
 *  result, a root — is a link that can be opened in a new tab and pasted
 *  into a message. Spread onto an `<a>`; the plain click stays in-page. */
export const nodeLink = (forest, id, view = 'explore') =>
  linkTo(hrefFor(forest, view, { node: id }))

export const capsOf = (grant) => grant?.caps || []
export const has = (grant, cap) =>
  capsOf(grant).includes(cap) || capsOf(grant).includes('admin')

/** Where a scoped principal starts. `_index` means the whole forest. */
export const rootsOf = (grant) =>
  grant?.roots?.length ? grant.roots : ['_index']

/* The address algebra lives in `nodes.js` — plain JS, so the console's own
 * checker can import it (J.5.17). Re-exported here because every view
 * already reaches for these through this module, and two import paths to
 * one function is how a second copy of it eventually appears. */
export { branchIdFor, branchOf, slugOf } from '../nodes.js'

export function useAsync(fn, deps = [], { skip = false } = {}) {
  const [state, setState] = useState({ busy: !skip, data: null, error: null })
  const run = useCallback(() => {
    if (skip) { setState({ busy: false, data: null, error: null }); return }
    let live = true
    setState((s) => ({ ...s, busy: true, error: null }))
    Promise.resolve()
      .then(fn)
      .then((data) => live && setState({ busy: false, data, error: null }))
      .catch((error) => live && setState({ busy: false, data: null, error }))
    return () => { live = false }
    // `skip` belongs in the dependency list: a caller that starts skipping —
    // or stops — is asking for a different answer, and leaving it out would
    // freeze the first one in the closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, skip])
  useEffect(() => run(), [run])
  return { ...state, reload: run }
}

/** J.5.1: a console the principal cannot use explains what is missing.
 *  An empty form that 403s on submit teaches nothing. */
export function NeedsCapability({ message, hint }) {
  return (
    <Card>
      <Empty icon={Access} title={message}>{hint}</Empty>
    </Card>
  )
}

export function NodeChip({ id, onOpen, children }) {
  return (
    <button type="button" onClick={() => onOpen?.(id)}
            className="badge max-w-full hover:border-accent/40 hover:bg-accent-soft
                       hover:text-accent">
      <span className="truncate font-mono">{children || id}</span>
    </button>
  )
}

/** Breadcrumbs stop at the principal's own roots: there is no path up to a
 *  master index they were never granted, and offering one would only 404. */
export function useCrumbs(id, grant) {
  const allow = grant?.allow?.length ? grant.allow : ['']
  const whole = allow.length === 1 && allow[0] === ''
  const parts = String(id || '').split('/')
  const out = []
  for (let i = 1; i < parts.length; i++) out.push(`${parts.slice(0, i).join('/')}/_index`)
  return out.filter((c) => c !== id && (whole || allow.some((a) => c.startsWith(a))))
}

/** A duration, at the precision that duration actually has.
 *
 *  Sub-millisecond is the whole claim of this project, so it is not rounded
 *  away: `locate` at 0.226 ms and `locate` at "0 ms" are the same call
 *  described as a measurement and as a rounding artefact. Above 10 ms the
 *  decimals are noise and go. */
export const fmtMs = (n) =>
  !Number.isFinite(n) ? '—'
    : n < 1 ? `${Number(n.toFixed(3))} ms`
    : n < 10 ? `${Number(n.toFixed(2))} ms`
    : `${Math.round(n)} ms`

/** The engine's own clock, step by step (J.10.4).
 *
 *  Lives here rather than in the Ask console because two panels report the
 *  same trace and a second rendering of it would drift: `answer` explains a
 *  reply, the Playground explains a call, and both are reading the identical
 *  `trace.steps` the host attached. The milliseconds are printed as the
 *  engine rounded them — three decimals, never re-rounded — because the
 *  whole point of the list is that a call the panel above sums as one
 *  number was several, and most of them were under a millisecond.
 */
export function TraceSteps({ steps }) {
  const { t } = useI18n()
  if (!steps?.length) return null
  // Every primitive row prints the engine's own work: the K.2 embed share
  // is subtracted where it rode and listed ONCE at the tail beside `model`
  // (J.10.4 v0.68) — provider spend sits with provider spend, so `locate`
  // stays the smallest number the trace can back. The host still serves
  // the whole span plus the named share; the netting is this panel's.
  const round3 = (n) => Math.round(n * 1000) / 1000
  const embedTotal = steps.reduce((n, s) => n + (s.embed_ms || 0), 0)
  // The Canopy scan (v0.71), on the same rule and for the same reason. It
  // is the half nobody had named: on a warm query embed the round trip is a
  // memo hit worth 0.1 ms and the scan is 68 ms of local CPU over every
  // node vector, so `locate` read as 70 ms of forest work that the forest
  // never did. Two rows, not one, because a provider and a process are
  // tuned differently.
  const denseTotal = steps.reduce((n, s) => n + (s.dense_ms || 0), 0)
  const rows = steps.map((s) => {
    const share = Math.min((s.embed_ms || 0) + (s.dense_ms || 0), s.ms)
    return { ...s, ms: round3(s.ms - share) }
  })
  const tailAt = () => (rows.length && rows[rows.length - 1].step === 'model'
    ? rows.length - 1 : rows.length)
  if (denseTotal > 0) rows.splice(tailAt(), 0, { step: 'dense', ms: round3(denseTotal) })
  if (embedTotal > 0) rows.splice(tailAt(), 0, { step: 'embed', ms: round3(embedTotal) })
  // Proportional to the slowest step, not to the total: the model dwarfs
  // everything, and a bar chart scaled to it would render every retrieval
  // step as the same invisible sliver.
  const worst = Math.max(...rows.map((s) => s.ms), 1)
  return (
    <ol className="space-y-2.5">
      {rows.map((s, i) => (
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
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-surface-2">
            {/* `embed` wears the model's tone: it IS a provider round
                trip, and painting it as the forest is the misreading the
                v0.68 split exists to prevent. */}
            <div className={`h-full rounded-full ${s.step === 'model' || s.step === 'embed' ? 'bg-text-3' : 'bg-accent'}`}
                 style={{ width: `${Math.max(2, (s.ms / worst) * 100)}%` }} />
          </div>
          {s.detail && <p className="mt-1 truncate text-[11px] text-text-3">{s.detail}</p>}
        </li>
      ))}
    </ol>
  )
}

/** A label and its number, on one line. Shared because the Ask console and
 *  the Playground both close a panel with the same little table, and two
 *  spellings of it would drift in the padding. */
export const Row = ({ label, value }) => (
  <div className="flex items-baseline justify-between gap-3">
    <dt className="text-text-3">{label}</dt>
    <dd className="font-mono text-text-2">{value}</dd>
  </div>
)

export function Metric({ label, value, tone }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-3 py-2">
      <div className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-text-3">
        {label}
      </div>
      <div className={`mt-0.5 text-[15px] font-medium tabular-nums
                       ${tone === 'accent' ? 'text-accent' : 'text-text'}`}>
        {value}
      </div>
    </div>
  )
}

const MAX_DEPTH = 12

/** One breadth-first walk of everything the principal can reach, shared by
 *  the tree, the scope picker, the ingest destinations and the counters.
 *
 *  Deliberately NOT a recursive `scan`: that primitive answers under an
 *  800-token budget, so on the test forest it returns 17 of 82 nodes and
 *  flags `truncated`. The budget is right for an agent, which wants a
 *  cheap look; a console that reported "17" as the size of an 82-node
 *  forest would simply be wrong. Walking level by level keeps every call
 *  inside the budget and makes the total exact.
 */
export function useForestTree(forest, grant, call, { skip = false } = {}) {
  return useAsync(async () => {
    const roots = rootsOf(grant)
    const branches = new Map(roots.map((r) => [r, { id: r, root: true }]))
    let frontier = roots
    let leaves = 0
    let datasets = 0
    let partial = false

    for (let depth = 0; depth < MAX_DEPTH && frontier.length; depth++) {
      const pages = await Promise.all(frontier.map(
        (id) => call(forest, 'scan', { parent_id: id, limit: 200 }).catch(() => null)))
      const next = []
      for (const page of pages) {
        if (!page) { partial = true; continue }
        // A single branch wide enough to blow the budget still truncates;
        // the flag travels with the numbers so the count is never silently
        // presented as complete.
        partial = partial || Boolean(page.truncated)
        for (const n of page.nodes || []) {
          if (n.type === 'branch') {
            if (!branches.has(n.id)) { branches.set(n.id, n); next.push(n.id) }
          } else {
            leaves += 1
            if (n.type === 'dataset') datasets += 1
          }
        }
      }
      frontier = next
    }

    return {
      branches: [...branches.values()].sort((a, b) => a.id.localeCompare(b.id)),
      nodes: leaves,
      datasets,
      partial,
    }
  }, [forest, grant], { skip: skip || !forest })
}

/* ── Shaping the forest (J.5.7) ──────────────────────────────────────────
 *
 * A.5 gives a new forest one branch. `adopt` makes more, but only by
 * mirroring a folder tree, so a forest whose documents arrive by upload had
 * nowhere to put them but the root — permanently. This is the missing
 * branch-maker, and it is deliberately thin: it composes one `plant` call.
 * Everything that makes a branch a branch — the id living under its parent,
 * the entry grafted into the parent's `## Sub-branches`, the commit, the
 * audit row — is the engine's, exactly as it is for an agent. */

/** The A.5 skeleton, so a new branch reads like every other one from the
 *  first moment instead of growing headings when something lands in it. */
const INDEX_BODY = (title, summary) =>
  `# ${title}\n\n> ${summary}\n\n## Sub-branches\n\n## Direct bananas\n\n` +
  '## Cross trails\n'

/**
 * The create-a-branch dialog, shared by Explore and the Ingest destination
 * picker so the two cannot drift into two different ideas of a branch.
 *
 * `onCreated(id)` receives the new branch id — the picker uses it to select
 * what it just made, so the ingest that prompted the branch continues
 * without a second trip through another console.
 */
export function NewBranch({ forest, parents, parent, onParent, open, onClose,
                            onCreated, call, t }) {
  const [name, setName] = useState('')
  const [summary, setSummary] = useState('')
  const [state, setState] = useState({})

  const id = branchIdFor(parent, name)
  // The engine owns the A.4 verdict (J.5.7); this is the budget shown while
  // typing, never a second rule. Over-budget still submits and is still
  // refused by the engine, so the two can never disagree about the answer.
  const tokens = Math.ceil((summary.trim().split(/\s+/).filter(Boolean).length) * 1.3)

  async function submit(e) {
    e.preventDefault()
    if (!id) return
    setState({ busy: true })
    try {
      const title = name.trim()
      // The primitive's argument is `node` — the request body is the call's
      // keyword arguments, so a flat passport reaches `plant(id=..., ...)`
      // and fails as an unexpected keyword. C.7 takes one object.
      await call(forest, 'plant', {
        node: {
          id,
          type: 'branch',
          parent: parent || '_index',
          title,
          summary: summary.trim(),
          source: 'manual',
          body: INDEX_BODY(title, summary.trim()),
        },
      })
      setName(''); setSummary(''); setState({})
      onCreated?.(id)
      onClose?.()
    } catch (error) { setState({ busy: false, error }) }
  }

  return (
    <Modal open={open} onClose={onClose} title={t('branch.new')}
           subtitle={t('branch.new_sub')}>
      <form onSubmit={submit} className="space-y-4">
        <Select label={t('branch.parent')} value={parent || '_index'}
                hint={t('branch.parent_hint')}
                onChange={(e) => onParent?.(e.target.value)}>
          {(parents || []).map((p) => (
            <option key={p.id} value={p.id}>{branchOf(p.id) || t('branch.root')}</option>
          ))}
        </Select>

        <Field label={t('branch.name')} value={name} required autoFocus
               placeholder={t('branch.name_placeholder')}
               onChange={(e) => setName(e.target.value)}
               hint={id ? t('branch.will_be', { id })
                        : t('branch.name_hint')} />

        <Field as={TextArea} label={t('branch.summary')} value={summary} required
               rows={3} placeholder={t('branch.summary_placeholder')}
               onChange={(e) => setSummary(e.target.value)}
               hint={t('branch.summary_hint', { n: tokens })}
               error={tokens > 60 ? t('branch.summary_long') : undefined} />

        {state.error && <ErrorNote error={state.error} />}

        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="btn btn-primary" disabled={!id || !summary.trim() || state.busy}>
            <Plus size={14} />
            {state.busy ? t('branch.creating') : t('branch.create')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
