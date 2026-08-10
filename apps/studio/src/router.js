// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Where the console is (spec J.5.8).
 *
 * The address IS the state. Every screen used to live at `/`, so a reload
 * started the console over — first forest of the list, default console,
 * nothing selected — a selection could not be sent to anybody, and Back left
 * the product. What is on screen is read from here; nothing keeps a second
 * copy of it.
 *
 *   /f/{forest}/{console}        the forest, and the console open on it
 *   ?node=…                      the selection, across consoles
 *   ?mode= ?dataset= ?table= …   what the open console needs to be itself
 *
 * Ids are query values, never path segments: a node id contains `/` (A.2),
 * so `/f/x/explore/a/b/_index` would be a path the router has to guess at.
 *
 * Dependency-free, like the i18n next to it. A router library buys nested
 * routes, loaders and data revalidation; this console has one route shape
 * and reads its data through `api.js`, so a 40 kB runtime would be paying
 * for a `useSyncExternalStore` over `history`.
 */
import { useCallback, useSyncExternalStore } from 'react'

/** Where a bare `/` goes. A convenience for the door and nothing more: an
 *  address always wins over it (J.5.8), and a forest that has left the
 *  principal's grants is not a place to restore. */
const PLACE = 'monkeyllm.studio.place'

const listeners = new Set()
const notify = () => { for (const fn of listeners) fn() }

// `popstate` covers Back and Forward. Our own pushes do not fire it, so
// `navigate` notifies — otherwise the console would move without rendering.
if (typeof window !== 'undefined') window.addEventListener('popstate', notify)

function subscribe(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

const url = () => location.pathname + location.search

/** The current address, as a string. Strings compare by value, which is what
 *  `useSyncExternalStore` needs to decide whether anything changed. */
export function useUrl() {
  return useSyncExternalStore(subscribe, url, () => '/')
}

/** `{forest, view, params}` — `params` is a `URLSearchParams`.
 *
 *  An address that is not `/f/…` yields nulls rather than throwing: the
 *  console resolves the bare `/` itself, because only it knows which forests
 *  this principal has. */
export function parse(href = url()) {
  const [path, query] = href.split('?')
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent)
  const params = new URLSearchParams(query || '')
  return parts[0] === 'f' && parts[1]
    ? { forest: parts[1], view: parts[2] || null, params }
    : { forest: null, view: null, params }
}

/** The address of a console, with its selection. Empty values are dropped —
 *  `?node=` in a shared link is noise that reads like a selection. */
export function hrefFor(forest, view, params = {}) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  const tail = q.toString()
  return `/f/${encodeURIComponent(forest)}/${view}${tail ? `?${tail}` : ''}`
}

/** Moving pushes; adjusting replaces (J.5.8). Back is for undoing
 *  navigation, and a Back that walks a per-keystroke trail is a Back nobody
 *  presses twice. */
export function navigate(href, { replace = false } = {}) {
  if (href === url()) return
  history[replace ? 'replaceState' : 'pushState'](null, '', href)
  notify()
}

/** Props for an anchor that navigates in place.
 *
 *  A real `href`, so the browser's own affordances work: open in a new tab,
 *  copy link, middle click, the status bar showing where this goes. Only the
 *  plain click is intercepted — a modified click is the operator asking the
 *  browser for something, and the browser can now answer it, because the
 *  Station serves these addresses (J.5.8).
 */
export function linkTo(href) {
  return {
    href,
    onClick: (e) => {
      if (e.defaultPrevented || e.button !== 0) return
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      e.preventDefault()
      navigate(href)
    },
  }
}

/** A piece of a console's state, kept in the query string.
 *
 *  `allow` is what this console understands. A value outside it falls back
 *  to the default instead of rendering nothing: links outlive the version
 *  that wrote them, and a shared address gets edited by hand (J.5.8).
 *
 *  Replaces by default — choosing a tab is adjusting, not moving.
 */
export function useRouteState(key, fallback, { allow, push = false } = {}) {
  const here = useUrl()
  const { forest, view, params } = parse(here)
  const raw = params.get(key)
  const value = raw !== null && (!allow || allow.includes(raw)) ? raw : fallback

  /** `set(value, {push})` — the override is for corrections. A selection the
   *  forest turned out not to contain is replaced, never pushed: it is not a
   *  place the operator went (J.5.8). */
  const set = useCallback((next, opts = {}) => {
    const { forest: f, view: v, params: p } = parse()
    if (!f || !v) return
    const merged = Object.fromEntries(p)
    // Deleting rather than writing an empty value: the address should carry
    // what is selected, and nothing where nothing is.
    if (next === undefined || next === null || next === '' || next === fallback) {
      delete merged[key]
    } else {
      merged[key] = String(next)
    }
    navigate(hrefFor(f, v, merged), { replace: !(opts.push ?? push) })
  }, [key, fallback, push])

  return [forest && view ? value : fallback, set]
}

export const rememberPlace = (forest, view) => {
  try { localStorage.setItem(PLACE, JSON.stringify({ forest, view })) } catch { /* private mode */ }
}

export const lastPlace = () => {
  try { return JSON.parse(localStorage.getItem(PLACE)) || {} } catch { return {} }
}
