// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// Tiny typed client over the Station's REST surface (spec J.15).
//
// Every request runs in an extension context — the popup or the service
// worker — never in an injected page script. Extension pages are exempt
// from the page's CORS once the origin permission is granted at pairing
// time; a script injected into the page is exactly the context that is
// NOT exempt, so nothing here is ever imported by clip.js.
//
// The Station answers refusals as {error: {code, message, hint?}} with an
// HTTP status derived from the code (E_LOCKED is 409, E_FORBIDDEN 403,
// and so on). One parser turns that envelope into an ApiError so callers
// branch on `code`, never on prose.

const ACCOUNT_KEY = 'mkc:account';

export class ApiError extends Error {
  constructor(code, message, hint, status) {
    super(message || code);
    this.name = 'ApiError';
    this.code = code;
    this.hint = hint || null;
    this.status = status || 0;
  }
}

/** Reduce whatever the person typed to a clean origin, or null.
 *  "station.example.com/f/x" and "https://station.example.com" both
 *  become "https://station.example.com" — the path is Studio's, not ours. */
export function normalizeOrigin(text) {
  let raw = String(text || '').trim();
  if (!raw) return null;
  if (!/^https?:\/\//i.test(raw)) raw = 'https://' + raw;
  try {
    const u = new URL(raw);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
    return u.origin;
  } catch {
    return null;
  }
}

/** The match pattern to request for an origin. Chrome match patterns do
 *  not carry ports, so the pattern is per-host: asking for
 *  "http://localhost/*" is what covers "http://localhost:8420". */
export function originPattern(origin) {
  const u = new URL(origin);
  return `${u.protocol}//${u.hostname}/*`;
}

async function request(origin, key, method, path, body) {
  let res;
  try {
    res = await fetch(origin + path, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(key ? { Authorization: `Bearer ${key}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    // fetch rejects only when the network itself failed (DNS, refused,
    // no permission for the origin). There is no envelope to parse.
    throw new ApiError('E_NETWORK', String(e && e.message || e), null, 0);
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    // A non-JSON body behind a proxy error page; fall through to status.
  }
  if (data && data.error && typeof data.error === 'object') {
    const err = data.error;
    throw new ApiError(err.code || 'E_SCHEMA', err.message || res.statusText,
                       err.hint, res.status);
  }
  if (!res.ok) {
    // 429 from the pair/login limiter carries one deliberate message
    // whether the user exists or not (J.2.6); keep the status visible so
    // the popup can say "wait a minute" instead of parroting it.
    throw new ApiError(res.status === 429 ? 'E_RATE_LIMITED' : 'E_SCHEMA',
                       res.statusText || `HTTP ${res.status}`, null, res.status);
  }
  return data;
}

// -- the paired account ----------------------------------------------------

export async function account() {
  const got = await chrome.storage.local.get(ACCOUNT_KEY);
  return got[ACCOUNT_KEY] || null;
}

export async function setAccount(acct) {
  // {origin, key, principal} and NOTHING else — the password is a gesture
  // at pairing, never data at rest (J.15).
  await chrome.storage.local.set({ [ACCOUNT_KEY]: acct });
}

export async function clearAccount() {
  await chrome.storage.local.remove(ACCOUNT_KEY);
}

async function authed() {
  const acct = await account();
  if (!acct || !acct.origin || !acct.key) {
    throw new ApiError('E_NOT_PAIRED', 'no paired server', null, 0);
  }
  return acct;
}

// -- the calls ---------------------------------------------------------------

/** POST /v1/auth/pair (J.2.6): unauthenticated, password in, narrowed key
 *  out — {api_key, principal, caps, expires_at}. The mask defaults to
 *  read+ingest, which is exactly a clipper's job description, so we do
 *  not send `caps` at all. */
export function pair(origin, { username, password, label } = {}) {
  return request(origin, null, 'POST', '/v1/auth/pair', {
    username,
    password,
    ...(label ? { label } : {}),
  });
}

/** GET /v1/me with explicit credentials — the probe the paste-a-token
 *  path runs BEFORE anything is saved. */
export function probe(origin, key) {
  return request(origin, key, 'GET', '/v1/me');
}

/** GET /v1/me for the stored account. A masked key answers masked caps
 *  (J.2.6), so what we render is what the key can actually do. */
export async function me() {
  const a = await authed();
  return request(a.origin, a.key, 'GET', '/v1/me');
}

/** GET /v1/forests → {forests: [{id, active, caps, roots}], mode}. */
export async function forests() {
  const a = await authed();
  return request(a.origin, a.key, 'GET', '/v1/forests');
}

/** POST /v1/forests/{forest}/ingest — compose answers in place with the
 *  Gardener's report; upload answers 202 {job} (J.9). */
export async function ingest(forest, body) {
  const a = await authed();
  return request(a.origin, a.key, 'POST',
                 `/v1/forests/${encodeURIComponent(forest)}/ingest`, body);
}

/** GET /v1/forests/{forest}/jobs → {jobs: [...]}. */
export async function jobs(forest) {
  const a = await authed();
  return request(a.origin, a.key, 'GET',
                 `/v1/forests/${encodeURIComponent(forest)}/jobs`);
}

/** GET /v1/forests/{forest}/jobs/{id} → {job: snapshot}. */
export async function job(forest, id) {
  const a = await authed();
  return request(a.origin, a.key, 'GET',
                 `/v1/forests/${encodeURIComponent(forest)}/jobs/${encodeURIComponent(id)}`);
}

/** POST /v1/forests/{forest}/{primitive} — the ten primitives plus the
 *  composites; the Clipper only ever asks for `locate` and `scan`. */
export async function primitive(forest, name, args) {
  const a = await authed();
  return request(a.origin, a.key, 'POST',
                 `/v1/forests/${encodeURIComponent(forest)}/${encodeURIComponent(name)}`,
                 args || {});
}
