// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The tab's one view of the job board, and the batches waiting their turn
 * (spec J.9.2 + J.9.3).
 *
 * The job board is the host's memory of running work (J.9), and this module
 * keeps NO copy of it in browser storage: a stored id would go stale in
 * both directions — surviving the Station restart that forgot the record,
 * and blind to a batch another principal started. Entering a forest asks
 * the board once; everything after is the watch.
 *
 * One watcher per forest, its cadence following the attention (J.9.3):
 * whoever is looking registers what freshness they need — the collapsed
 * pill a minute, the expanded pill or the open ingest console seconds —
 * and the watcher polls at the finest of them. A waiting queue keeps its
 * own settle-detection pace even with nobody looking, because its promise
 * (J.9.2: fire when the board frees) does not depend on an audience.
 *
 * The queue itself is tab memory, the opposite of the invisible queue J.9
 * refuses in every property the refusal names: visible where it waits,
 * sent nowhere until its turn, abandoned when the tab closes. A cancel
 * holds it — stop means everything — and any refusal other than E_LOCKED
 * holds it too; E_LOCKED just means another client won the race, and the
 * queue takes its turn at that job's settle instead.
 */

import { useEffect, useSyncExternalStore } from 'react'
import { api } from './api.js'

/** Attention cadences (J.9.3): the order of a minute for a glance, the
 *  order of seconds for a watch; a waiting queue sits between the two. */
export const GLANCE = 60_000
export const WATCH = 2_000
const SETTLE = 5_000

const EMPTY = { jobs: [], running: null, fetched: false,
                items: [], held: null, version: 0 }

/* forest -> { jobs, fetched, printed: last published wire form,
 *             items: [{id, body, mode, count, dest, path}],
 *             held: null | {why: 'cancelled'|'refused', error?},
 *             after: id of the job whose settle the queue waits on,
 *             fired: id of the job the last fired batch opened (taken once),
 *             attentions: Map(token -> ms), timer, ticking,
 *             version, snapshot } */
const boards = new Map()
const listeners = new Set()
let seq = 0

function board(forest) {
  let out = boards.get(forest)
  if (!out) {
    out = { jobs: [], fetched: false, printed: '', items: [], held: null,
            after: null, fired: null, attentions: new Map(), timer: null,
            ticking: false, version: 0, snapshot: EMPTY }
    boards.set(forest, out)
  }
  return out
}

/* Snapshots are rebuilt on change and cached between: `useSyncExternalStore`
 * compares by identity, and a getter building a fresh object each call
 * would render forever. */
function publish(entry) {
  entry.version += 1
  entry.snapshot = {
    jobs: entry.jobs,
    running: entry.jobs.find((j) => j.state === 'running') || null,
    fetched: entry.fetched,
    items: entry.items,
    held: entry.held,
    version: entry.version,
  }
  for (const fn of listeners) fn()
}

function subscribe(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** The board as the console renders it:
 *  `{jobs, running, fetched, items, held, version}`. */
export function useBoard(forest) {
  return useSyncExternalStore(
    subscribe,
    () => (forest ? board(forest).snapshot : EMPTY),
    () => EMPTY,
  )
}

/** Register what freshness this reader needs; returns the release. The
 *  watcher runs at the finest cadence any reader asked (J.9.3). */
export function attend(forest, ms) {
  const entry = board(forest)
  const token = (seq += 1)
  entry.attentions.set(token, ms)
  // A new reader wants an answer, not a countdown: fetch now when nothing
  // has been fetched yet, otherwise just fall in at the new pace.
  schedule(forest, entry.fetched ? undefined : 0)
  return () => {
    entry.attentions.delete(token)
    schedule(forest)
  }
}

/** `attend`, as a hook. `active: false` unplugs without unmounting. */
export function useAttend(forest, ms, active = true) {
  useEffect(() => {
    if (!forest || !active) return undefined
    return attend(forest, ms)
  }, [forest, ms, active])
}

/** Stage a batch behind the running job (J.9.2). `meta` is what the card
 *  can say about it: {mode, count, dest, path}. */
export function enqueue(forest, body, meta) {
  const entry = board(forest)
  entry.items = [...entry.items, { id: `q-${(seq += 1)}`, body, ...meta }]
  const running = entry.jobs.find((j) => j.state === 'running')
  if (running) entry.after = running.id
  publish(entry)
  schedule(forest)
}

/** Take an entry out of the waiting. Destroys nothing but the wait; an
 *  empty queue has nothing left to hold, so the hold goes with it. */
export function remove(forest, id) {
  const entry = board(forest)
  entry.items = entry.items.filter((item) => item.id !== id)
  if (!entry.items.length) entry.held = null
  publish(entry)
  schedule(forest)
}

/** The operator's hand after a hold (J.9.2): start the next batch. */
export function release(forest) {
  const entry = board(forest)
  entry.held = null
  publish(entry)
  schedule(forest, 0)
}

/** The job the last fired batch opened, once: the open ingest console
 *  adopts it into the address; a closed one leaves it for rediscovery
 *  (J.9.1). Not part of the snapshot — taking it must not re-render what
 *  it informed. */
export function takeFired(forest) {
  const entry = board(forest)
  const fired = entry.fired
  entry.fired = null
  return fired
}

/** A job this tab just learned first-hand (a submit's 202): onto the board
 *  view now, so the console never waits a poll to see its own act. Not a
 *  read of the board, so `fetched` — which authorises the "job lost"
 *  verdict — stays whatever it was. */
export function noteJob(forest, job) {
  if (!job) return
  const entry = board(forest)
  entry.jobs = [job, ...entry.jobs.filter((j) => j.id !== job.id)]
  publish(entry)
  schedule(forest)
}

function cadence(entry) {
  let ms = Infinity
  for (const wanted of entry.attentions.values()) ms = Math.min(ms, wanted)
  // The queue's promise does not depend on an audience: with batches
  // waiting (and no hold), settle detection keeps its own pace.
  if (entry.items.length && !entry.held) ms = Math.min(ms, SETTLE)
  return ms
}

function schedule(forest, delay) {
  const entry = board(forest)
  clearTimeout(entry.timer)
  entry.timer = null
  const ms = delay !== undefined ? delay : cadence(entry)
  if (!Number.isFinite(ms)) return // nobody looking, nothing waiting
  entry.timer = setTimeout(() => tick(forest), ms)
}

async function tick(forest) {
  const entry = board(forest)
  if (entry.ticking) return
  entry.ticking = true
  let again = true
  try {
    let out
    try {
      out = await api.jobs(forest)
    } catch (error) {
      again = false
      // A key that cannot read jobs will not read them next time either —
      // the watcher goes quiet rather than drumming 403s; a fresh reader
      // (attend) starts it over. A blip deserves another look, unhurried.
      if (error.status !== 401 && error.status !== 403) {
        schedule(forest, Math.max(cadence(entry), SETTLE))
      }
      return
    }
    entry.jobs = out.jobs || []
    entry.fetched = true

    const running = entry.jobs.find((j) => j.state === 'running')
    if (running) {
      entry.after = running.id
    } else if (entry.items.length && !entry.held) {
      // The board is free. If the job the queue waited on settled
      // `cancelled`, the queue holds (J.9.2): stop meant everything.
      const settled = entry.after
        && entry.jobs.find((j) => j.id === entry.after)
      if (settled && settled.state === 'cancelled') {
        entry.after = null
        entry.held = { why: 'cancelled' }
      } else {
        entry.after = null
        await fire(forest, entry)
      }
    }

    // Publish only what changed: at a glance cadence nothing usually did,
    // and re-rendering every reader to say so would be noise.
    const printed = JSON.stringify([entry.jobs, entry.items, entry.held])
    if (printed !== entry.printed) {
      entry.printed = printed
      publish(entry)
    }
  } finally {
    entry.ticking = false
    if (again) schedule(forest)
  }
}

async function fire(forest, entry) {
  const [next] = entry.items
  let out
  try {
    out = await api.ingest(forest, next.body)
  } catch (error) {
    if (error.code === 'E_LOCKED') return // lost the race; wait that job out
    entry.held = { why: 'refused', error }
    return
  }
  entry.items = entry.items.slice(1)
  entry.fired = out.job?.id || null
  if (out.job) {
    entry.jobs = [out.job, ...entry.jobs.filter((j) => j.id !== out.job.id)]
    entry.after = out.job.id
  }
}
