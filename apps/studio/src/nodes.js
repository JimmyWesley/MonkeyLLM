// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* What the console knows about a node without asking anybody (spec A.2,
 * C.14, C.15).
 *
 * Two pure halves, deliberately kept out of the components that render
 * them:
 *
 * - **The address algebra.** An id is a path, so composing one — a branch
 *   under a parent (J.5.7), a leaf moved to another branch (J.5.17 rule 4)
 *   — is arithmetic on strings, and the engine still owns every verdict:
 *   what is computed here is the id the operator is about to ask for, never
 *   whether they may have it.
 * - **What a refusal carries.** `E_ANCHORED` puts `anchors` and
 *   `anchor_count` on the envelope (C.14 rule 3) and those two numbers are
 *   not the same number: the list is capped at 20 and loses anything out of
 *   the caller's scope, while the count is exact. Reading the length of the
 *   list as the size of the problem is precisely the misreading J.5.17
 *   rule 3 forbids, so the comparison is made once, here, rather than in
 *   each place the list is drawn.
 *
 * Plain JS and not JSX on purpose: this is the half of J.5.17 a machine can
 * check, and `apps/studio/check-hands.mjs` imports it from node with no
 * build step — the same construction `skill.js` and `check-skill.mjs` use.
 */

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

/** A branch id (`projects/_index`) as the branch itself (`projects`). */
export const branchOf = (id) =>
  id === '_index' ? '' : String(id || '').replace(/\/?_index$/, '')

/** The id a branch would get under `parent` (`_index` = forest root). */
export function branchIdFor(parent, name) {
  const slug = slugOf(name)
  if (!slug) return null
  const under = branchOf(parent || '_index')
  return under ? `${under}/${slug}/_index` : `${slug}/_index`
}

/** The id a leaf would get under `parent`. The same composition a plant
 *  uses (J.5.7) without the `/_index` tail — which is the whole difference
 *  between a branch and a document, and the reason `transplant` refuses a
 *  branch (C.15 rule 1). */
export function leafIdFor(parent, name) {
  const slug = slugOf(name)
  if (!slug) return null
  const under = branchOf(parent || '_index')
  return under ? `${under}/${slug}` : slug
}

/** The branch a node lives in, as a branch id — `_index` at the root. */
export function parentOf(id) {
  const under = branchOf(id)
  const cut = under.lastIndexOf('/')
  return cut === -1 ? '_index' : `${under.slice(0, cut)}/_index`
}

/** The last segment of a leaf id — what an operator would call the file. */
export const nameOf = (id) => String(id || '').split('/').pop() || ''

/** An id that names a branch. The digest's `type` is the authority when the
 *  console has one; this is what it falls back to, and it is exact: A.5
 *  gives every branch an `_index`. */
export const looksLikeBranch = (id) => id === '_index' || /\/_index$/.test(String(id || ''))

/** The forest root. It has no parent to account for it, so C.14 refuses to
 *  prune it and C.15 refuses to move it. */
export const isRootId = (id) => id === '_index'

/** The dialect's own files. Served, but never content (C.6) — and never
 *  editable through the primitives an operator has (C.14, C.15). */
export const isSystemId = (id) => id === '_meta' || String(id || '').startsWith('_meta/')

/** What `E_ANCHORED` actually said (C.14 rule 3).
 *
 *  `named` is what the console may draw as nodes; `total` is the fact. They
 *  differ for two reasons that both matter and neither of which the list
 *  itself shows: the engine caps the list at 20, and it drops anchors
 *  outside the caller's scope (reporting those only as `out_of_scope`,
 *  because J.3 forbids naming them). `complete` is the one question the
 *  screen has to answer honestly — whether what it is showing IS the set.
 *
 *  A branch refused for its children is the same code with no anchors at
 *  all (C.14 rule 4), which lands here as `total: 0`: nothing to draw, and
 *  nothing `force` could do about it.
 */
export function anchorsOf(error) {
  const data = error?.data || {}
  const named = Array.isArray(data.anchors) ? data.anchors : []
  const count = Number(data.anchor_count)
  const total = Number.isFinite(count) ? count : named.length
  const scoped = Number(data.out_of_scope)
  const outOfScope = Number.isFinite(scoped) ? scoped : 0
  return {
    named,
    total,
    // Never negative: an older Station that sent a count and no list, or a
    // list longer than the count, must not render as "-3 more".
    unnamed: Math.max(0, total - named.length),
    outOfScope,
    complete: named.length >= total,
  }
}
