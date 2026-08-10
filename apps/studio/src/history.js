// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The runs Ask has made, kept where they were made (spec J.5.9).
//
// IndexedDB and not `localStorage`, for three reasons that are all the same
// reason — a run is not a preference. It carries the material the model was
// given, which is node bodies: hundreds of kilobytes for one question with
// `k=6`. `localStorage` holds about five megabytes per origin, is
// synchronous, and stores strings, so keeping runs there would serialise
// half a megabyte on the main thread after every answer and then start
// failing at around the tenth question. IndexedDB stores the object, gets an
// origin quota measured in hundreds of megabytes, and indexes it — so "this
// principal's runs on this forest" is a lookup rather than a parse of
// everything ever kept.
//
// Two stores, one database. The list is drawn from `runs`, which holds only
// what a row shows; the answer and its material live in `payloads` and are
// read on restore alone. One store would mean deserialising every body in
// the history to draw a list of questions.
//
// Nothing here reaches the network, and that is the point: J.5.9 keeps a run
// on the machine that asked. The host has no place to put model output that
// would not be pretending it is forest content, and the call itself is
// already recorded — the audit row of J.4, the pheromone of Part D.

const DB = 'monkeyllm.studio'
const VERSION = 1
const RUNS = 'runs'
const PAYLOADS = 'payloads'

// The bound of J.5.9, per principal per forest. Stated here, shown in the
// panel, and applied oldest-first: a store that quietly dropped the far end
// would let a partial history read as a complete one.
export const MAX_RUNS = 50
export const MAX_BYTES = 20 * 1024 * 1024

let handle = null
let opening = null
// Private browsing, a refused quota, storage switched off by policy. The
// answer on screen does not depend on any of it, so a failure here is
// reported as "no history", never raised into the ask (J.5.9).
let broken = false

function open() {
  if (handle) return Promise.resolve(handle)
  if (broken) return Promise.resolve(null)
  if (opening) return opening
  if (typeof indexedDB === 'undefined') { broken = true; return Promise.resolve(null) }

  opening = new Promise((resolve) => {
    let req
    try { req = indexedDB.open(DB, VERSION) } catch { broken = true; return resolve(null) }
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(RUNS)) {
        const runs = db.createObjectStore(RUNS, { keyPath: 'id' })
        // Compound and ordered: the query the panel makes is always "this
        // principal, this forest, newest first", which a cursor walks
        // backwards over this index without touching another scope's rows.
        runs.createIndex('scope', ['principal', 'forest', 'ts'])
      }
      if (!db.objectStoreNames.contains(PAYLOADS)) {
        db.createObjectStore(PAYLOADS, { keyPath: 'id' })
      }
    }
    req.onsuccess = () => {
      handle = req.result
      // A second tab upgrading the schema would block on this connection
      // forever; letting go is better than holding a version hostage.
      handle.onversionchange = () => { handle.close(); handle = null }
      resolve(handle)
    }
    req.onerror = () => { broken = true; resolve(null) }
    req.onblocked = () => { broken = true; resolve(null) }
  }).finally(() => { opening = null })

  return opening
}

/** One transaction, resolved when it commits rather than when the last
 *  request succeeds — a write that resolved early would report a run as kept
 *  and then lose it to a quota error at commit time. */
function tx(stores, mode, body) {
  return open().then((db) => {
    if (!db) return null
    return new Promise((resolve) => {
      let t
      try { t = db.transaction(stores, mode) } catch { return resolve(null) }
      let out = null
      t.oncomplete = () => resolve(out)
      t.onerror = () => resolve(null)
      t.onabort = () => resolve(null)
      try { body(t, (value) => { out = value }) } catch { t.abort() }
    })
  }).catch(() => null)
}

const req = (request, then) => { request.onsuccess = () => then(request.result) }

/** Ids are generated, never derived from the question: the same question
 *  asked twice is two runs, and that pair is the comparison J.5.9 exists
 *  for. `randomUUID` is a secure-context API and a Station on a LAN over
 *  plain HTTP is not one, so it cannot be the only source. */
function newId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    try { return crypto.randomUUID() } catch { /* insecure context */ }
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

const scopeRange = (principal, forest) => IDBKeyRange.bound(
  [principal, forest, -Infinity], [principal, forest, Infinity])

/** What a row shows, and nothing that would need the payload read to draw
 *  it. `bytes` is measured once here so the panel can total a history
 *  without deserialising one. */
function card(record, result, bytes) {
  return {
    id: record.id,
    principal: record.principal,
    forest: record.forest,
    ts: record.ts,
    question: record.question,
    params: record.params,
    // Which model answered, because a run kept across a rebinding is
    // exactly the comparison worth making. No latency: the client's own
    // round trip is not the cost of the call (J.10.6), and the host's three
    // clocks travel inside the payload for the panel that knows how to read
    // them.
    model: result?.model || null,
    evidence: result?.evidence?.length || 0,
    bytes,
  }
}

/** Keep a run. Resolves to its card, or null when storage is unavailable —
 *  the caller has already shown the answer either way. */
export async function saveRun({ principal, forest, question, params, result }) {
  if (!principal || !forest) return null
  let bytes = 0
  // An estimate, and deliberately the cheap one: the structured clone that
  // actually gets stored has no length to ask for, and the panel needs a
  // number to hold itself to the bound.
  try { bytes = JSON.stringify(result).length } catch { bytes = 0 }
  const record = { id: newId(), principal, forest, ts: Date.now(), question, params }
  const saved = await tx([RUNS, PAYLOADS], 'readwrite', (t, set) => {
    const row = card(record, result, bytes)
    t.objectStore(RUNS).put(row)
    t.objectStore(PAYLOADS).put({ id: record.id, result })
    set(row)
  })
  if (saved) await evict(principal, forest)
  return saved
}

/** Oldest first, by count and by size. Both bounds are per scope: one
 *  forest's long evaluation session is not a reason to drop another's. */
async function evict(principal, forest) {
  const { runs } = await listRuns(principal, forest)
  let bytes = 0
  const doomed = []
  runs.forEach((row, i) => {
    bytes += row.bytes || 0
    if (i >= MAX_RUNS || bytes > MAX_BYTES) doomed.push(row.id)
  })
  if (!doomed.length) return
  await tx([RUNS, PAYLOADS], 'readwrite', (t) => {
    for (const id of doomed) {
      t.objectStore(RUNS).delete(id)
      t.objectStore(PAYLOADS).delete(id)
    }
  })
}

/** This principal's runs on this forest, newest first.
 *
 *  `ok` is not `runs.length`: an empty history and a browser that cannot
 *  keep one are different states, and the panel says which. */
export async function listRuns(principal, forest) {
  if (!principal || !forest) return { ok: true, runs: [], bytes: 0 }
  const rows = await tx([RUNS], 'readonly', (t, set) => {
    const out = []
    const cursor = t.objectStore(RUNS).index('scope')
      .openCursor(scopeRange(principal, forest), 'prev')
    // One handler, fired again on every `continue()`. The array is filled
    // during the transaction and read when it commits.
    cursor.onsuccess = () => {
      const c = cursor.result
      if (!c) return
      out.push(c.value)
      c.continue()
    }
    set(out)
  })
  if (!rows) return { ok: false, runs: [], bytes: 0 }
  return { ok: true, runs: rows, bytes: rows.reduce((n, r) => n + (r.bytes || 0), 0) }
}

/** The response as it was received. Restoring reads exactly one payload;
 *  the list never does. */
export async function loadRun(id) {
  const found = await tx([RUNS, PAYLOADS], 'readonly', (t, set) => {
    const row = t.objectStore(RUNS).get(id)
    req(row, (record) => {
      if (!record) return set(null)
      const payload = t.objectStore(PAYLOADS).get(id)
      req(payload, (blob) => set(blob ? { ...record, result: blob.result } : null))
    })
  })
  return found || null
}

export async function clearRuns(principal, forest) {
  const { runs } = await listRuns(principal, forest)
  await tx([RUNS, PAYLOADS], 'readwrite', (t) => {
    for (const row of runs) {
      t.objectStore(RUNS).delete(row.id)
      t.objectStore(PAYLOADS).delete(row.id)
    }
  })
}

/** Everything, every principal, every forest.
 *
 *  Called when the credential goes (J.5.9): a run carries node bodies read
 *  under a grant, and a browser is shared furniture. Keying by principal
 *  already hides one operator's runs from the next; discarding them is the
 *  part that means the bodies are gone rather than merely unlisted. */
export async function dropEverything() {
  await tx([RUNS, PAYLOADS], 'readwrite', (t) => {
    t.objectStore(RUNS).clear()
    t.objectStore(PAYLOADS).clear()
  })
}

/** The kept runs as one file, whole — the answers and their material, not
 *  the cards. The only thing that ever moves a run off this machine, and it
 *  moves because somebody asked for it (J.5.9). */
export async function exportRuns(principal, forest) {
  const { runs } = await listRuns(principal, forest)
  const full = []
  for (const row of runs) {
    const record = await loadRun(row.id)
    if (record) full.push(record)
  }
  return { forest, principal, exported: new Date().toISOString(), runs: full }
}
