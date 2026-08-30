// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* J.5.17 acceptance (F.167), on the half a machine can see.
 *
 * Studio has no test runner and this file is not one — it is the same
 * construction `check-skill.mjs` uses: the console's checkable claims,
 * checked where they are made. `tests/test_v075_console.py` runs it; a
 * non-zero exit is a failed criterion, named on stdout.
 *
 * What is checked here: the address algebra and the anchor arithmetic
 * (imported and exercised as functions), the confirmation text (read out of
 * the shipped catalogues, in all three languages), and the source facts
 * that are structural rather than behavioural — the gate on `write`, the
 * branch's missing transplant control, the absence of any bulk removal.
 *
 * What is NOT checked here, and is normative text with no test on F.137's
 * stated boundary: that the rendered dialog looks right, that a click
 * actually navigates, and that the address really loses `?node=` after a
 * commit. Those need a DOM and a live Station; asserting them from the
 * source would be asserting that a string is present, which is not the same
 * claim. The engine's half of F.167 — that the prune removes, keeps history
 * and moves the payload — is tested against the primitive itself, not here.
 */
import { readFileSync } from 'node:fs'
import {
  anchorsOf, branchIdFor, isRootId, isSystemId, leafIdFor, looksLikeBranch,
  nameOf, parentOf, slugOf,
} from './src/nodes.js'

let failed = 0
const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')
const LANGS = ['en', 'pt', 'es']
const cat = Object.fromEntries(
  LANGS.map((l) => [l, JSON.parse(read(`./src/locales/hands/${l}.json`))]))
const hands = read('./src/views/hands.jsx')
const explore = read('./src/views/Explore.jsx')
const readConsole = read('./src/views/Read.jsx')

/* -- rule 2: the confirmation names the node and states the two facts ----- */

const en = cat.en
ok('J.5.17 r2 the confirmation names title AND id',
   en['hands.prune_subject'].includes('{title}') && en['hands.prune_subject'].includes('{id}'),
   en['hands.prune_subject'])
// The two facts C.14 makes true and a user will not assume. Checked in
// every language: a translation that dropped "graveyard" would be a
// different promise made to a different operator.
for (const lang of LANGS) {
  const git = cat[lang]['hands.prune_git'].toLowerCase()
  const grave = cat[lang]['hands.prune_graveyard']
  ok(`J.5.17 r2 [${lang}] the passport is removed through git and kept in history`,
     git.includes('git') && /hist[oó]r/.test(git))
  ok(`J.5.17 r2 [${lang}] a local payload MOVES to _derived/graveyard/`,
     grave.includes('_derived/graveyard/')
     && /(moved|movido|mueve|move)/i.test(grave))
}
// Neither overstating nor understating: the words a delete dialog reaches
// for, and that C.14 does not make true, must not appear.
const overstated = LANGS.flatMap((l) => Object.entries(cat[l])
  .filter(([k, v]) => k.startsWith('hands.prune')
    && /\b(permanent|permanente|irreversible|irrevers[íi]vel|forever|para sempre|para siempre)\b/i.test(v))
  .map(([k]) => `${l}:${k}`))
ok('J.5.17 r2 the prune text claims no permanence C.14 does not make',
   overstated.length === 0, overstated.join(', '))
ok('J.5.17 r2 both facts are rendered in the first step of the dialog',
   hands.includes("t('hands.prune_git')") && hands.includes("t('hands.prune_graveyard')")
   && hands.includes("t('hands.prune_subject'"))

/* -- rule 3: E_ANCHORED is a list, and the count is the complete fact ----- */

// The engine's own shapes (C.14 rule 3), read the way the console reads them.
const capped = anchorsOf({
  code: 'E_ANCHORED',
  data: { anchors: Array.from({ length: 20 }, (_, i) => ({ source: `a/${i}`, rel: 'related-to' })),
          anchor_count: 31 },
})
ok('C.14 r3 a capped list is not presented as complete',
   capped.named.length === 20 && capped.total === 31 && capped.unnamed === 11
   && capped.complete === false)
const scoped = anchorsOf({
  code: 'E_ANCHORED',
  data: { anchors: [{ source: 'a/1', rel: 'part-of' }], anchor_count: 4, out_of_scope: 3 },
})
ok('C.14 r3 an out-of-scope anchor is a count, never a name',
   scoped.named.length === 1 && scoped.total === 4 && scoped.outOfScope === 3
   && scoped.complete === false)
const whole = anchorsOf({
  code: 'E_ANCHORED',
  data: { anchors: [{ source: 'a/1', rel: 'part-of' }], anchor_count: 1 },
})
ok('C.14 r3 a complete list says so', whole.complete === true && whole.unnamed === 0)
// C.14 rule 4: a branch refused for its children carries no anchors at all.
const children = anchorsOf({ code: 'E_ANCHORED', data: {} })
ok('C.14 r4 a branch refusal names nothing to force',
   children.total === 0 && children.named.length === 0 && children.complete === true)
// A pre-C.14 or malformed envelope must not render as "-3 more".
ok('C.14 r3 a list longer than the count never renders a negative remainder',
   anchorsOf({ data: { anchors: [{ source: 'x' }, { source: 'y' }], anchor_count: 1 } })
     .unnamed === 0)
ok('J.5.17 r3 the anchors are drawn as navigable nodes, not as a string',
   /anchors\.named\.map/.test(hands) && /onNavigate\?\.\(/.test(hands))
ok('J.5.17 r3 the count is shown, and the shortfall is stated',
   hands.includes("t('hands.anchored_count'") && hands.includes("t('hands.anchored_partial'")
   && hands.includes("t('hands.anchored_scope'"))
ok('J.5.17 r3 force is a second, separately confirmed decision',
   // Two states, one button each: the first step cannot submit `force`, and
   // the second restates what it does before it can.
   /setForcing\(true\)/.test(hands) && /run\(forcing\)/.test(hands)
   && hands.includes("t('hands.force_what')"))
for (const lang of LANGS) {
  ok(`J.5.17 r3 [${lang}] the force step restates what force does`,
     /(same commit|backlink|link|v[íi]nculo|enlace|commit)/i.test(cat[lang]['hands.force_what']))
}
ok('J.5.17 r3 force is never offered when the refusal named no anchors',
   /anchors\.total > 0 &&\s*\(?\s*<button/.test(hands.replace(/\n\s*/g, ' ')))

/* -- rule 4: a transplant is composed, and a branch has no control -------- */

ok('J.5.7 the destination is composed, never typed whole',
   leafIdFor('projects/_index', 'Q1 Report') === 'projects/q1-report'
   && leafIdFor('_index', 'Q1 Report') === 'q1-report'
   && leafIdFor('a/b/_index', 'x') === 'a/b/x')
ok('J.5.7 a leaf id is not a branch id',
   branchIdFor('_index', 'x') === 'x/_index' && leafIdFor('_index', 'x') === 'x')
ok('the address algebra round-trips a leaf',
   parentOf('projects/reports/q1') === 'projects/reports/_index'
   && parentOf('q1') === '_index'
   && nameOf('projects/reports/q1') === 'q1'
   // `parentOf` answers the BRANCH a node lives in; composing back into it
   // must be the id it started from.
   && leafIdFor(parentOf('projects/q1'), nameOf('projects/q1')) === 'projects/q1')
ok('a name with nothing sluggable composes no id',
   leafIdFor('_index', '   ') === null && slugOf('///') === '')
ok('C.15 r1 a branch is recognised by its own address',
   looksLikeBranch('_index') && looksLikeBranch('a/b/_index') && !looksLikeBranch('a/b'))
ok('C.14/C.15 the root and the dialect are never subjects',
   isRootId('_index') && isSystemId('_meta/schema') && isSystemId('_meta')
   && !isSystemId('meta/x'))
ok('J.5.17 r4 a branch is offered no transplant control at all',
   // Rendered under `!branch`, both the button and its dialog — not
   // disabled, and not a control that refuses on submit.
   /\{!branch && \(/.test(hands) && /const branch = type === 'branch' \|\| looksLikeBranch\(id\)/.test(hands))
ok('J.5.17 r4 the confirmation says the old address keeps answering',
   hands.includes("t('hands.move_waymark'"))
for (const lang of LANGS) {
  ok(`J.5.17 r4 [${lang}] the waymark sentence names the old id`,
     cat[lang]['hands.move_waymark'].includes('{id}'))
}
ok('J.5.17 r4 the parent is chosen from what the principal can reach',
   /useForestTree\(forest, grant, api\.call, \{ skip: !open \}\)/.test(hands)
   && /<Select label=\{t\('hands\.move_parent'\)\}/.test(hands))

/* -- rule 1: gated on write, absent rather than disabled ------------------ */

ok('J.5.17 r1 the hands are absent without the write capability',
   /if \(!id \|\| !has\(grant, 'write'\)\) return null/.test(hands))
ok('J.5.17 r1 no control is merely disabled by the grant',
   !/disabled=\{[^}]*has\(grant/.test(hands))
ok('J.5.17 r1 both consoles that have a node as their subject offer them',
   explore.includes('<NodeHands') && readConsole.includes('<NodeHands')
   && explore.includes("from './hands.jsx'") && readConsole.includes("from './hands.jsx'"))

/* -- rule 5: no bulk removal anywhere in the console ---------------------- */

const sources = ['./src/views/hands.jsx', './src/views/Explore.jsx', './src/views/Read.jsx',
                 './src/views/files.jsx', './src/views/graph.jsx', './src/views/Data.jsx',
                 './src/views/Ingest.jsx', './src/views/editor.jsx']
const bulk = sources.filter((p) => {
  const text = read(p)
  // A prune inside a loop, or a prune over anything plural: `prune` is one
  // node per call by contract, so the console may never hold a list of them.
  return /(map|forEach|for |while |Promise\.all)[^\n]*prune/i.test(text)
    || /prune[^\n]*(\.map\(|forEach|Promise\.all)/i.test(text)
})
ok('J.5.17 r5 no console loops a prune over a selection', bulk.length === 0, bulk.join(', '))
// The dispatch itself, not the word: `prune` names a dialog and a piece of
// state too, and counting those would make this criterion a spelling test.
const calls = sources.flatMap((p) => (read(p).match(/api\.call\([^,]+, '(prune|transplant)'/g) || []))
ok('J.5.17 r5 prune and transplant are dispatched from exactly one place each',
   calls.filter((c) => c.endsWith("'prune'")).length === 1
   && calls.filter((c) => c.endsWith("'transplant'")).length === 1, calls.join(' | '))

/* -- rule 6: the selection is moved off the id that is gone --------------- */

ok('J.5.17 r6 a prune clears the selection in every console that offers it',
   /onPruned=\{\(\) => \{ setNode\(null\); map\.reload\(\) \}\}/.test(explore)
   && /onPruned=\{\(\) => \{ setNode\(null\); onChanged\?\.\(\) \}\}/.test(explore)
   && /onPruned=\{\(\) => setNode\(null\)\}/.test(readConsole))
ok('J.5.17 r6 a transplant moves the selection to the new id',
   /onMoved=\{\(next\) => \{ setNode\(next\); map\.reload\(\) \}\}/.test(explore)
   && /onMoved=\{\(next\) => setNode\(next\)\}/.test(readConsole))
// Both handlers are called after their own await and nowhere else: the
// commit is the truth, so there is no optimistic copy of the forest to
// correct when the engine refuses.
const after = (call, handler) => {
  const at = hands.indexOf(`api.call(forest, '${call}'`)
  const uses = [...hands.matchAll(new RegExp(`${handler}\\?\\.\\(`, 'g'))].map((m) => m.index)
  return at > 0 && uses.length === 1 && uses[0] > at
}
ok('J.5.17 r6 nothing changes before the commit says it did',
   after('prune', 'onPruned') && after('transplant', 'onMoved'))
ok('a call in flight disables its own button',
   /disabled=\{busy\}/.test(hands) && /disabled=\{same \|\| busy\}/.test(hands))

/* -- the catalogues are complete and shaped like the rest ---------------- */

const keys = Object.keys(en)
const gaps = LANGS.flatMap((l) => keys.filter((k) => !cat[l][k]).map((k) => `${l}:${k}`))
ok('J.5.3 the three catalogues are complete', gaps.length === 0, gaps.join(', '))
const used = [...hands.matchAll(/t\('(hands\.[a-z0-9_.]+)'/g)].map((m) => m[1])
const undefinedKeys = [...new Set(used)].filter((k) => !(k in en))
ok('every hands.* key the dialog reads is defined', undefinedKeys.length === 0,
   undefinedKeys.join(', '))
const unused = keys.filter((k) => !used.includes(k))
ok('every hands.* key defined is read', unused.length === 0, unused.join(', '))

console.log(failed ? `\n${failed} criterion(s) failed` : '\nall criteria met')
process.exit(failed ? 1 : 0)
