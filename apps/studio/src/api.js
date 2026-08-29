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

  /** The progress of one `answer`, while it is still being answered (J.10.12).
   *
   *  `fetch` and not `EventSource`, for one reason that decides it: an
   *  EventSource cannot carry a header, and this Station is reached with a
   *  Bearer token. The alternative is the key in the query string, and a
   *  credential in a URL is a credential in every log and every referrer —
   *  the same rule J.16 keeps when it audits a webhook's host and never its
   *  path. So the frames are parsed here, which is a dozen lines.
   *
   *  Resolves when the run closes. Never rejects: a channel is an
   *  enhancement over a call that is happening anyway, so a Station that
   *  does not serve one, a proxy that buffers it away, or a network that
   *  drops it must cost the caller nothing but the picture.
   */
  events: async (forest, run, onEvent, signal) => {
    try {
      const res = await fetch(
        `/v1/forests/${encodeURIComponent(forest)}/answer/`
        + `${encodeURIComponent(run)}/events`,
        { headers: { ...(getKey() ? { Authorization: `Bearer ${getKey()}` } : {}) },
          signal })
      if (!res.ok || !res.body) return
      const reader = res.body.getReader()
      const decode = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decode.decode(value, { stream: true })
        // SSE frames are separated by a blank line. A partial frame stays in
        // the buffer: a chunk boundary is not a message boundary.
        let cut = buffer.indexOf('\n\n')
        while (cut !== -1) {
          const frame = buffer.slice(0, cut)
          buffer = buffer.slice(cut + 2)
          let kind = 'message'
          let data = ''
          for (const line of frame.split('\n')) {
            if (line.startsWith('event: ')) kind = line.slice(7)
            else if (line.startsWith('data: ')) data += line.slice(6)
          }
          if (kind !== 'ping') {
            try {
              onEvent(kind, data ? JSON.parse(data) : {})
            } catch { /* one bad frame is not the end of the channel */ }
          }
          if (kind === 'done') return
          cut = buffer.indexOf('\n\n')
        }
      }
    } catch { /* aborted, unreachable, or unsupported: the call is unaffected */ }
  },

  // Map projections (J.11): a region in one call rather than one call per
  // node. Read-only, scoped exactly like the primitives, and derived — a
  // stale answer is fixed by reindexing, never by reconciling here.
  map: (forest, kind, params = {}) => {
    const q = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== ''))
    const tail = q.toString() ? `?${q}` : ''
    return request(`/v1/forests/${encodeURIComponent(forest)}/${kind}${tail}`)
  },

  // Payload bytes (J.14): the raw file behind a media node's textual proxy.
  // Steps around `request` because the body is the bytes, not JSON — and it
  // exists at all because an <img src> cannot carry the Bearer header, so
  // the caller fetches the blob and mints an object URL it must revoke.
  // Segments are encoded one by one: a node id carries slashes the route's
  // path matcher needs to see as slashes.
  payload: async (forest, node) => {
    const path = `/v1/forests/${encodeURIComponent(forest)}/payload/`
      + String(node).split('/').map(encodeURIComponent).join('/')
    const res = await fetch(path, {
      headers: getKey() ? { Authorization: `Bearer ${getKey()}` } : {},
    })
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      const err = payload?.error || {}
      throw new ApiError(err.message || res.statusText || `HTTP ${res.status}`,
                         { code: err.code, hint: err.hint, status: res.status })
    }
    // Two steps on purpose: the type is a header, the bytes are the body.
    // A caller sniffing whether a media payload is an image must be able
    // to decline BEFORE paying for it — a 40 MB audio payload is a header
    // read, not a download (J.14).
    return {
      type: res.headers.get('Content-Type') || '',
      blob: () => res.blob(),
      cancel: () => { res.body?.cancel()?.catch(() => {}) },
    }
  },

  // The document as text/markdown (J.14.1): no token budget — a download
  // for people, never model material. Segments encoded one by one, exactly
  // as `payload` does and for the same reason.
  exportNode: async (forest, node) => {
    const path = `/v1/forests/${encodeURIComponent(forest)}/export/`
      + String(node).split('/').map(encodeURIComponent).join('/')
    const res = await fetch(path, {
      headers: getKey() ? { Authorization: `Bearer ${getKey()}` } : {},
    })
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      const err = payload?.error || {}
      throw new ApiError(err.message || res.statusText || `HTTP ${res.status}`,
                         { code: err.code, hint: err.hint, status: res.status })
    }
    return res.text()
  },

  // Shares (J.17): a share is a key with one room. The token rides once,
  // inside the URL the create answers with; the listing never carries it.
  createShare: (forest, node, days) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/share`,
            { method: 'POST', body: days ? { node, days } : { node } }),
  shares: (forest) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/shares`),
  revokeShare: (forest, id) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/shares/${encodeURIComponent(id)}`,
            { method: 'DELETE' }),
  // The anonymous half: no Authorization on purpose — the token IS the
  // authority, re-checked server-side at every serve.
  sharedDocument: async (token) => {
    const res = await fetch(`/v1/share/${encodeURIComponent(token)}`)
    const payload = await res.json().catch(() => ({}))
    if (!res.ok) {
      const err = payload?.error || {}
      throw new ApiError(err.message || res.statusText || `HTTP ${res.status}`,
                         { code: err.code, hint: err.hint, status: res.status })
    }
    return payload
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

  // Webhooks (J.16): the outbound half. Scoped exactly like everything else
  // — the GET carries the catalogue a console must never hard-code, and the
  // secret appears in exactly one response, the one that created it.
  webhooks: (forest) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/webhooks`),
  saveWebhook: (forest, body) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/webhooks`,
            { method: 'POST', body }),
  webhook: (forest, id) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/webhooks/${encodeURIComponent(id)}`),
  webhookAction: (forest, id, body) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/webhooks/${encodeURIComponent(id)}`,
            { method: 'POST', body }),
  deleteWebhook: (forest, id) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/webhooks/${encodeURIComponent(id)}`,
            { method: 'DELETE' }),

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
  // J.13.4: embed what changed. Not a build — a model change needs the
  // whole index rebuilt, because a partial re-embed spans two spaces (K.4).
  refreshCanopy: (forest) =>
    request('/v1/admin/canopy', { method: 'POST', body: { forest, refresh: true } }),

  // maintenance (J.13): the Ranger's report, and Part I over REST.
  // NOT `health` — that name belongs to the Station's own liveness probe
  // above, and a second definition silently replaced it: the Gate asks
  // `api.health()` whether a password door exists, got a 403 from this
  // endpoint instead, and stopped offering the password form entirely.
  forestHealth: (forest) =>
    request(`/v1/admin/health?forest=${encodeURIComponent(forest)}`),
  // J.13.5: the C.9 lock, inspected and (when orphan) released. The
  // console gains no path the API refuses — a held lock stays held.
  locks: (forest) =>
    request(`/v1/admin/locks?forest=${encodeURIComponent(forest)}`),
  unlock: (forest) =>
    request('/v1/admin/unlock', { method: 'POST', body: { forest } }),
  snapshots: (forest) =>
    request(`/v1/admin/snapshots?forest=${encodeURIComponent(forest)}`),
  takeSnapshot: (forest, withPayloads = false) =>
    request('/v1/admin/snapshots',
            { method: 'POST', body: { forest, with_payloads: withPayloads } }),

  // Snapshot travel (J.13.1/J.13.2, owner-only). Both step around
  // `request`: the download's body is the bundle rather than JSON, and the
  // import's is multipart — the browser sets the boundary itself, so no
  // Content-Type is spelled out.
  downloadSnapshot: async (forest, name) => {
    const res = await fetch(
      `/v1/admin/snapshots/${encodeURIComponent(forest)}/${encodeURIComponent(name)}`,
      { headers: getKey() ? { Authorization: `Bearer ${getKey()}` } : {} })
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      const err = payload?.error || {}
      throw new ApiError(err.message || res.statusText || `HTTP ${res.status}`,
                         { code: err.code, hint: err.hint, status: res.status })
    }
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.click()
    URL.revokeObjectURL(url)
  },
  importSnapshot: async ({ id, bundle, payloads }) => {
    const form = new FormData()
    form.set('id', id)
    form.set('bundle', bundle)
    if (payloads) form.set('payloads', payloads)
    const res = await fetch('/v1/admin/snapshots/import', {
      method: 'POST',
      headers: getKey() ? { Authorization: `Bearer ${getKey()}` } : {},
      body: form,
    })
    const payload = await res.json().catch(() => ({}))
    if (!res.ok) {
      const err = payload?.error || {}
      throw new ApiError(err.message || res.statusText || `HTTP ${res.status}`,
                         { code: err.code, hint: err.hint, status: res.status })
    }
    return payload
  },

  // What a refresh would re-read (J.8): the recorded source root, whether
  // this Station may still read it, and whether it reads host paths at all.
  ingestStatus: (forest) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/ingest`),

  bindings: (forest) =>
    request(`/v1/admin/models?forest=${encodeURIComponent(forest)}`),
  bindModel: (body) => request('/v1/admin/models', { method: 'POST', body }),

  // The answer store (J.10.7): its per-forest switches and its economy.
  // One POST both updates settings and, with `clear: true`, empties it.
  answerCache: (forest) =>
    request(`/v1/admin/cache?forest=${encodeURIComponent(forest)}`),
  setAnswerCache: (body) => request('/v1/admin/cache', { method: 'POST', body }),

  // The repair the derived layer is designed around (J.13.3). Synchronous
  // on purpose: the caller waits, because a rebuild the console could not
  // confirm is a rebuild nobody can rely on.
  // J.13.6 (v0.61): re-derive what ingest would derive today, from the
  // passports. Not a job — it runs on the lane and the caller waits, like
  // the rebuild beside it.
  // `body` is the OBJECT: `request` stringifies it (line 63). Passing a
  // string here encoded it twice, so the Station's `request.json()` handed
  // the route a `str` and `body.get(...)` raised — a 500 on every press of
  // the Re-derive button. `reindex` below is what the shape should be.
  recurate: (forest, derive = ['aliases']) =>
    request('/v1/admin/recurate', { method: 'POST', body: { forest, derive } }),
  // J.13.7 (v0.61): what is in the upload staging area that is not a
  // document, and the sweep for it. One resource, two verbs — the same
  // question asked twice.
  staging: (forest) =>
    request(`/v1/admin/staging?forest=${encodeURIComponent(forest)}`),
  clearStaging: (forest) => request('/v1/admin/staging', { method: 'POST',
                                                          body: { forest } }),
  reindex: (forest) => request('/v1/admin/reindex', { method: 'POST',
                                                      body: { forest } }),
}
