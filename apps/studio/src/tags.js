// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The tag algebra (spec J.5.18 rules 3 and 5).
 *
 * Plain JS with no React in it, for the reason `nodes.js` is: the console's
 * own checker (`check-tags.mjs`) imports these and exercises them as
 * functions, so the two rules a machine can actually verify — a bulk apply
 * UNIONS and a bulk remove SUBTRACTS, and nothing typed is quietly rewritten
 * — are checked as arithmetic rather than as a string in a source file.
 *
 * Two rules shape every function here.
 *
 * **Adding is not replacing (rule 3).** `unionTags` returns what the node
 * already carried plus what is new; `subtractTags` returns what is left
 * after removing exactly what was named. Neither ever produces the typed
 * set on its own, which is the write that would erase curation across a
 * selection in one careless action.
 *
 * **Nothing is normalised (rule 5).** `tagKey` exists to decide whether two
 * spellings are the same tag — it is a comparison form and it is NEVER what
 * gets written. `parseTags` trims the whitespace around a comma-separated
 * field, because that whitespace is the separator's and not the operator's,
 * and it does nothing else: no lowercasing, no accent stripping, no
 * substitution of a character the engine would refuse. The engine's refusal
 * is the truth, and a console that quietly rewrote a tag into something
 * acceptable would be making the same mistake as one that silently dropped
 * what the model wrote (G.4.2 rule 1).
 */

/** The comparison form of a tag: NFC + case folding, the same decision
 *  `models.tag_key` makes on the engine side (G.4.2 rule 2). Never written
 *  anywhere — a tag keeps the spelling it was given. */
export const tagKey = (tag) => String(tag ?? '').normalize('NFC').toLowerCase()

/** A comma-separated field as the list of tags it names.
 *
 *  Trimming is the separator's own whitespace, not a normalisation: `a, b`
 *  and `a,b` name the same two tags, and a leading space is nobody's
 *  intention. Everything else survives verbatim, including a tag the engine
 *  will refuse — which is the point (rule 5). Duplicates typed twice
 *  collapse under the fold; the FIRST spelling wins, because that is the
 *  one the person typed first. */
export function parseTags(input) {
  const out = []
  const seen = new Set()
  for (const raw of String(input ?? '').split(',')) {
    const tag = raw.trim()
    if (!tag) continue
    const key = tagKey(tag)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(tag)
  }
  return out
}

/** J.5.18 rule 3: adding is not replacing.
 *
 *  Every tag the node already carries survives, in its own spelling and in
 *  its own order; a wanted tag joins the tail only when nothing already
 *  there matches it under the fold. So `produção` is not added beside
 *  `Produção`, and re-running the same apply is a no-op — which is what
 *  makes a partial run safe to repeat. */
export function unionTags(existing, adding) {
  const out = [...(existing || [])]
  const seen = new Set(out.map(tagKey))
  for (const tag of adding || []) {
    const key = tagKey(tag)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(tag)
  }
  return out
}

/** J.5.18 rule 3: a bulk remove subtracts exactly what was named, and
 *  leaves everything else where it was. */
export function subtractTags(existing, removing) {
  const gone = new Set((removing || []).map(tagKey))
  return (existing || []).filter((tag) => !gone.has(tagKey(tag)))
}

/** Whether two tag lists are the same write. Order and spelling both count:
 *  the engine stores the list it is given, so a reorder IS a change — but a
 *  node whose tags come back identical must not be grafted at all, or a
 *  bulk apply would author N commits that change nothing. */
export const sameTags = (a, b) =>
  (a || []).length === (b || []).length
  && (a || []).every((tag, i) => tag === (b || [])[i])

/** What a bulk run may honestly say about itself (J.5.18 rule 2).
 *
 *  `complete` is the whole claim: a run is complete only when every node in
 *  the selection was reached AND none of them refused. A run that touched
 *  every node but had one refusal is a partial run, and saying otherwise is
 *  exactly the completion this rule forbids. */
export function runSummary(run) {
  const total = run?.total ?? 0
  const done = run?.done ?? 0
  const failures = run?.failures || []
  return {
    total,
    done,
    changed: run?.changed ?? 0,
    unchanged: run?.unchanged ?? 0,
    failed: failures.length,
    // Progress against the total, always — the operator is authoring N
    // commits and is told which one of the N is running.
    percent: total ? Math.round((done / total) * 100) : 0,
    complete: total > 0 && done === total && failures.length === 0,
    partial: total > 0 && (done < total || failures.length > 0),
  }
}
