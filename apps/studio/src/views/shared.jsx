// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Small pieces every console needs, in one place so nine views cannot drift
 * into nine subtly different ideas of "loading" or "you may not do this". */
import { useCallback, useEffect, useState } from 'react'
import { hrefFor, linkTo } from '../router.js'
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

/** A branch id (`projects/_index`) as the branch itself (`projects`). */
export const branchOf = (id) =>
  id === '_index' ? '' : id.replace(/\/?_index$/, '')

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

/** A name as the path segment it becomes. Mirrors the Gardener's `slugify`
 *  closely enough that a folder and a hand-made branch of the same name
 *  land on the same id — an operator who mirrors `Contracts` later should
 *  not get `contracts` beside `Contracts`. */
export function slugOf(name) {
  return (name || '')
    .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')  // strip diacritics
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)
}

/** The id a branch would get under `parent` (`_index` = forest root). */
export function branchIdFor(parent, name) {
  const slug = slugOf(name)
  if (!slug) return null
  const under = branchOf(parent || '_index')
  return under ? `${under}/${slug}/_index` : `${slug}/_index`
}

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
