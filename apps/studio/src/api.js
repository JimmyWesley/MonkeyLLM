// The only way this app reaches a forest. Studio holds no privileged
// side-channel (spec J.5): every call carries the operator's own key, so
// whatever Studio can show, an API client with that key could fetch too.

const KEY_STORAGE = 'monkeyllm.station.key'

export const getKey = () => localStorage.getItem(KEY_STORAGE) || ''
export const setKey = (k) => localStorage.setItem(KEY_STORAGE, k)
export const clearKey = () => localStorage.removeItem(KEY_STORAGE)

export class ApiError extends Error {
  constructor(message, { code, hint, status } = {}) {
    super(message)
    this.code = code
    this.hint = hint
    this.status = status
  }
}

async function request(path, { method = 'GET', body } = {}) {
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
    throw new ApiError(err.message || res.statusText, {
      code: err.code, hint: err.hint, status: res.status,
    })
  }
  return payload
}

export const api = {
  health: () => request('/v1/health'),
  me: () => request('/v1/me'),
  forests: () => request('/v1/forests'),

  // forest primitives + the model-backed composites (J.10)
  call: (forest, primitive, payload = {}) =>
    request(`/v1/forests/${encodeURIComponent(forest)}/${primitive}`,
            { method: 'POST', body: payload }),

  // governance
  principals: () => request('/v1/admin/principals'),
  grant: (body) => request('/v1/admin/grant', { method: 'POST', body }),
  audit: (limit = 200) => request(`/v1/admin/audit?limit=${limit}`),

  // inference providers and per-forest bindings
  providers: () => request('/v1/admin/providers'),
  putProvider: (body) => request('/v1/admin/providers', { method: 'POST', body }),
  testProvider: (body) => request('/v1/admin/providers/test', { method: 'POST', body }),
  bindings: (forest) =>
    request(`/v1/admin/models?forest=${encodeURIComponent(forest)}`),
  bindModel: (body) => request('/v1/admin/models', { method: 'POST', body }),
}
