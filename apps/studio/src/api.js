// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The only way this app reaches a forest. Studio holds no privileged
// side-channel (spec J.5): every call carries the operator's own key, so
// whatever Studio can show, an API client with that key could fetch too.

import { dropEverything } from './history.js'

const KEY_STORAGE = 'monkeyllm.station.key'

export const getKey = () => localStorage.getItem(KEY_STORAGE) || ''
export const setKey = (k) => localStorage.setItem(KEY_STORAGE, k)
export const clearKey = () => localStorage.removeItem(KEY_STORAGE)

/** Leaving takes the kept runs with it (J.5.9).
 *
 *  Deliberately not inside `clearKey`: that also runs when a boot fails,
 *  and a Station briefly unreachable would then discard an operator's whole
 *  history as if they had signed out. Signing out is the deliberate act, so
 *  it is the one that drops the bodies. Resolves before the caller reloads
 *  — a delete cut off mid-transaction is a delete that did not happen. */
export const signOut = () => {
  clearKey()
  return dropEverything().catch(() => {})
}

export class ApiError extends Error {
  constructor(message, { code, hint, status } = {}) {
    super(message)
    this.code = code
    this.hint = hint
    this.status = status
  }
}

/** The host's own clocks, off `Server-Timing` (J.10.6).
 *
 *  Returns null when the header is absent — an older Station, or a proxy
 *  that dropped it. A console that then reports its own stopwatch as the
 *  cost of the call would be making the exact claim J.10.6 forbids, so the
 *  callers treat null as "the engine figure is unknown", never as zero. */
function serverTiming(res) {
  const raw = res.headers.get('Server-Timing')
  if (!raw) return null
  const out = {}
  for (const part of raw.split(',')) {
    const [name, ...params] = part.trim().split(';')
    const dur = params.map((p) => p.trim())
      .find((p) => p.startsWith('dur='))?.slice(4)
    if (dur !== undefined && Number.isFinite(Number(dur))) out[name.trim()] = Number(dur)
  }
  return Object.keys(out).length ? out : null
}

async function request(path, { method = 'GET', body, timing = false } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(getKey() ? { Authorization: `Bearer ${getKey()}` } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  const payload = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = payload?.error || {}
    // HTTP/2 carries no reason phrase, so `statusText` is empty behind any
    // modern proxy: a failure with no envelope rendered as a blank message
    // and read as "no reason given" rather than as a server error.
    throw new ApiError(err.message || res.statusText || `HTTP ${res.status}`, {
      code: err.code, hint: err.hint, status: res.status,
    })
  }
  // Deliberately a separate return shape rather than a field grafted onto
  // the payload: the Playground prints the response verbatim, and a console
  // that invented a key would be showing the caller something no API client
  // receives.
  return timing ? { data: payload, timing: serverTiming(res) } : payload
}

export const api = {
  health: () => request('/v1/health'),
  me: () => request('/v1/me'),
  forests: () => request('/v1/forests'),

  // forest primitives + the model-backed composites (J.10)
  call: (forest, primitive, payload = {}) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/${primitive}`,
            { method: 'POST', body: payload }),

  // The same call, with the host's clocks alongside it (J.10.6): resolves to
  // `{data, timing}`. For the two consoles that report latency — everywhere
  // else the numbers are instruments nobody asked for.
  timedCall: (forest, primitive, payload = {}) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/${primitive}`,
            { method: 'POST', body: payload, timing: true }),

  // Map projections (J.11): a region in one call rather than one call per
  // node. Read-only, scoped exactly like the primitives, and derived — a
  // stale answer is fixed by reindexing, never by reconciling here.
  map: (forest, kind, params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== ''))
    const tail = q.toString() ? `?${q}` : ''
    return request(`/v1/forests/${encodeURIComponent(forest)}/${kind}${tail}`)
  },

  // credentials (J.2.1 / J.2.2)
  login: (username, password) =>
    request('/v1/auth/login', { method: 'POST', body: { username, password } }),
  // First-run setup (J.2.4). Exists only while the Station has no credential;
  // once it has run it answers like any unrouted path, which is how the
  // console learns it lost the race.
  setup: (body) => request('/v1/auth/setup', { method: 'POST', body }),
  keys: () => request('/v1/admin/keys'),

  // Person-shaped governance (J.2.3): one read, one write, per person.
  people: () => request('/v1/admin/people'),
  savePerson: (body) => request('/v1/admin/people', { method: 'POST', body }),
  issueKey: (body) => request('/v1/admin/keys', { method: 'POST', body }),
  revokeKey: (id) => request('/v1/admin/keys', { method: 'POST', body: { revoke: id } }),
  setPassword: (principal, password) =>
    request('/v1/admin/password', { method: 'POST', body: { principal, password } }),

  // forest lifecycle (J.7) and the Gardener over REST (J.8)
  createForest: (body) => request('/v1/admin/forests', { method: 'POST', body }),
  ingest: (forest, body) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/ingest`,
            { method: 'POST', body }),

  // Ingest jobs (J.9): a batch answers 202 with a job. Reading one is a
  // host-record read — it never touches the forest, which is what makes
  // polling free while the batch runs.
  job: (forest, id) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/jobs/${encodeURIComponent(id)}`),
  jobs: (forest) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/jobs`),
  cancelJob: (forest, id) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/jobs/${encodeURIComponent(id)}/cancel`,
            { method: 'POST' }),

  // governance
  principals: () => request('/v1/admin/principals'),
  grant: (body) => request('/v1/admin/grant', { method: 'POST', body }),
  audit: (limit = 200) => request(`/v1/admin/audit?limit=${limit}`),

  // inference providers and per-forest bindings
  providers: () => request('/v1/admin/providers'),
  putProvider: (body) => request('/v1/admin/providers', { method: 'POST', body }),
  testProvider: (body) => request('/v1/admin/providers/test', { method: 'POST', body }),
  // The Gauntlet's index (Part K)
  canopy: (forest) => request(`/v1/admin/canopy?forest=${encodeURIComponent(forest)}`),
  buildCanopy: (forest) =>
    request('/v1/admin/canopy', { method: 'POST', body: { forest } }),
  setCanopy: (forest, enabled) =>
    request('/v1/admin/canopy', { method: 'POST', body: { forest, enabled } }),

  // maintenance (J.13): the Ranger's report, and Part I over REST.
  // NOT `health` — that name belongs to the Station's own liveness probe
  // above, and a second definition silently replaced it: the Gate asks
  // `api.health()` whether a password door exists, got a 403 from this
  // endpoint instead, and stopped offering the password form entirely.
  forestHealth: (forest) =>
    request(`/v1/admin/health?forest=${encodeURIComponent(forest)}`),
  snapshots: (forest) =>
    request(`/v1/admin/snapshots?forest=${encodeURIComponent(forest)}`),
  takeSnapshot: (forest, withPayloads = false) =>
    request('/v1/admin/snapshots',
            { method: 'POST', body: { forest, with_payloads: withPayloads } }),

  // What a refresh would re-read (J.8): the recorded source root, whether
  // this Station may still read it, and whether it reads host paths at all.
  ingestStatus: (forest) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/ingest`),

  bindings: (forest) =>
    request(`/v1/admin/models?forest=${encodeURIComponent(forest)}`),
  bindModel: (body) => request('/v1/admin/models', { method: 'POST', body }),
}
