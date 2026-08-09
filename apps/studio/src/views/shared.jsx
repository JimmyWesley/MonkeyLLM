/* Small pieces every console needs, in one place so nine views cannot drift
 * into nine subtly different ideas of "loading" or "you may not do this". */
import { useCallback, useEffect, useState } from 'react'
import { Card, Empty } from '../design/ui.jsx'
import { Access } from '../design/icons.jsx'

export const ALL_CAPS = ['read', 'query', 'write', 'tend', 'ingest', 'admin']

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
