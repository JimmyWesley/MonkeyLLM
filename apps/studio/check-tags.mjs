// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* J.5.18 acceptance (F.168), on the half a machine can see.
 *
 * The same construction `check-hands.mjs` and `check-skill.mjs` use: Studio
 * has no test runner, so the console's checkable claims are checked next to
 * the code that makes them, and `tests/test_v075_tags.py` runs this file. A
 * non-zero exit is a failed criterion, named on stdout.
 *
 * What is checked here:
 *
 *  - the tag algebra, imported and EXERCISED as functions — union, subtract,
 *    the fold that decides uniqueness, and the summary that decides whether
 *    a run may call itself complete. These are F.168's arithmetic clauses
 *    and they are real assertions, not string searches;
 *  - the structural facts a reader of the source can actually see: that the
 *    bulk write reads each node before it writes, that the merged list is
 *    what gets sent, that the loop survives a refusal, that the vocabulary
 *    comes from the documented route, that the scent editor is the SAME
 *    component Explore's editor is built from, and that nothing on the
 *    typed-tag path normalises what somebody typed;
 *  - the sentences, read out of the shipped catalogues in all three
 *    languages, where the sentence IS the rule (a partial run must not read
 *    as a finished one).
 *
 * What is NOT checked here, and is normative text with no test on F.137's
 * stated boundary: that the progress bar actually moves, that a click on a
 * tag really re-renders the listing, and that a refusal is visible on the
 * screen. Those want a DOM and a live Station; asserting them from the
 * source would only assert that a string is present. The engine's half of
 * F.168 — the counts, the scope, the cap, the refusal — is tested against
 * the route and the primitive in `tests/test_v075_tags.py`.
 */
import { readFileSync } from 'node:fs'
import {
  parseTags, runSummary, sameTags, subtractTags, tagKey, unionTags,
} from './src/tags.js'

let failed = 0
const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')
const LANGS = ['en', 'pt', 'es']
const cat = Object.fromEntries(
  LANGS.map((l) => [l, JSON.parse(read(`./src/locales/tags/${l}.json`))]))
const tagsView = read('./src/views/tags.jsx')
const readConsole = read('./src/views/Read.jsx')
const editor = read('./src/views/editor.jsx')
const apiClient = read('./src/api.js')

/* -- rule 3: adding is not replacing ------------------------------------- */

ok('J.5.18 r3 a bulk apply UNIONS into what the node already carries',
   JSON.stringify(unionTags(['ledger', 'q1-2026'], ['invoice']))
     === JSON.stringify(['ledger', 'q1-2026', 'invoice']))
ok('J.5.18 r3 an apply never drops a tag the node already had',
   unionTags(['a', 'b', 'c'], ['d']).length === 4
   && ['a', 'b', 'c'].every((x) => unionTags(['a', 'b', 'c'], ['d']).includes(x)))
ok('J.5.18 r3 applying twice is applying once (idempotent)',
   JSON.stringify(unionTags(unionTags(['a'], ['b']), ['b']))
     === JSON.stringify(['a', 'b']))
ok('J.5.18 r3 a case variant is the same tag, and the STORED spelling wins',
   JSON.stringify(unionTags(['Produção'], ['produção'])) === JSON.stringify(['Produção']))
ok('J.5.18 r3 a bulk remove subtracts only what was named',
   JSON.stringify(subtractTags(['a', 'b', 'c'], ['b'])) === JSON.stringify(['a', 'c']))
ok('J.5.18 r3 a remove of something absent removes nothing',
   JSON.stringify(subtractTags(['a', 'b'], ['zzz'])) === JSON.stringify(['a', 'b']))
ok('J.5.18 r3 a remove matches under the same fold an apply does',
   JSON.stringify(subtractTags(['Produção', 'a'], ['PRODUÇÃO'])) === JSON.stringify(['a']))
// The failure this rule exists to prevent, stated as arithmetic: neither
// operation can ever produce the typed set on its own.
ok('J.5.18 r3 neither operation can produce the typed set alone',
   JSON.stringify(unionTags(['keep'], ['new'])) !== JSON.stringify(['new'])
   && JSON.stringify(subtractTags(['keep'], ['new'])) !== JSON.stringify(['new']))
ok('an unchanged list is recognised, so no node is given an empty commit',
   sameTags(['a', 'b'], ['a', 'b']) && !sameTags(['a', 'b'], ['b', 'a'])
   && !sameTags(['a'], ['a', 'b']))

/* -- rule 5: nothing typed is quietly normalised -------------------------- */

ok('J.5.18 r5 the separator\'s whitespace is trimmed and nothing else is',
   JSON.stringify(parseTags('  invoice ,  Q1-2026  '))
     === JSON.stringify(['invoice', 'Q1-2026']))
ok('J.5.18 r5 case is preserved exactly as typed',
   JSON.stringify(parseTags('ISO-27001, BE-291')) === JSON.stringify(['ISO-27001', 'BE-291']))
ok('J.5.18 r5 diacritics are preserved (G.4.2 r2: they are never stripped)',
   JSON.stringify(parseTags('produção, segurança')) === JSON.stringify(['produção', 'segurança']))
// The load-bearing one: a tag the ENGINE will refuse survives to the wire
// verbatim, so the refusal names what was typed rather than a rewrite of it.
ok('J.5.18 r5 a tag the engine refuses is passed on verbatim, not repaired',
   JSON.stringify(parseTags('rate limit')) === JSON.stringify(['rate limit'])
   && JSON.stringify(parseTags('-leading')) === JSON.stringify(['-leading']))
ok('J.5.18 r5 the fold is a COMPARISON form and is never written',
   tagKey('Produção') === 'produção' && parseTags('Produção')[0] === 'Produção')
ok('J.5.18 r5 one tag typed twice is one tag, in the first spelling',
   JSON.stringify(parseTags('Invoice, invoice')) === JSON.stringify(['Invoice']))
// A console-side normalisation would live on the write path, so that is
// where it is looked for: `tagKey` is the only place a fold may appear.
const folds = tagsView.match(/\.toLowerCase\(\)|\.normalize\(/g) || []
ok('J.5.18 r5 the console never folds a tag on the way to the engine',
   folds.length === 0, folds.join(', '))
const algebra = read('./src/tags.js')
const foldLines = algebra.split('\n')
  .map((line, i) => [i + 1, line])
  .filter(([, line]) => /\.toLowerCase\(\)|\.normalize\(/.test(line))
ok('J.5.18 r5 the fold lives in tagKey alone',
   foldLines.length === 1 && /export const tagKey/.test(foldLines[0][1]),
   foldLines.map(([n]) => `line ${n}`).join(', '))
ok('J.5.18 r5 the engine\'s own refusal is what is rendered',
   /f\.message/.test(tagsView))

/* -- rule 2: the bulk write is stated ------------------------------------ */

ok('J.5.18 r2 progress is against the TOTAL, not a spinner',
   tagsView.includes("t('tags.bulk_progress', { done:")
   && /percent/.test(tagsView) && /summary\.total/.test(tagsView))
// The summary is the claim, so the claim is checked as arithmetic.
ok('J.5.18 r2 a run that reached every node with one refusal is NOT complete',
   runSummary({ total: 3, done: 3, failures: [{ id: 'x' }] }).complete === false
   && runSummary({ total: 3, done: 3, failures: [{ id: 'x' }] }).partial === true)
ok('J.5.18 r2 a run cut short is NOT complete',
   runSummary({ total: 3, done: 2, failures: [] }).complete === false)
ok('J.5.18 r2 only a whole clean run is complete',
   runSummary({ total: 3, done: 3, failures: [] }).complete === true)
ok('J.5.18 r2 an empty run claims nothing',
   runSummary({ total: 0, done: 0, failures: [] }).complete === false)
ok('J.5.18 r2 progress is a percentage of the total and never of the done',
   runSummary({ total: 4, done: 1, failures: [] }).percent === 25
   && runSummary({ total: 0, done: 0, failures: [] }).percent === 0)
// A refusal is caught per node and pushed; the loop has no break and no
// rethrow, so one refusal cannot abandon the rest.
const loop = tagsView.slice(tagsView.indexOf('for (const id of ids)'),
                            tagsView.indexOf('onDone?.()'))
ok('J.5.18 r2 one node\'s refusal does not abandon the rest',
   /failures\.push\(/.test(loop) && !/\bbreak\b/.test(loop) && !/\bthrow\b/.test(loop))
ok('J.5.18 r2 every failure is named, never counted only',
   /run\.failures\.map/.test(tagsView) && /\{f\.id\}/.test(tagsView))
ok('J.5.18 r2 the operator is told they are authoring N commits',
   ['en', 'pt', 'es'].every((l) => /commit/i.test(cat[l]['tags.bulk_sub'])))
for (const lang of LANGS) {
  const partial = cat[lang]['tags.bulk_partial']
  ok(`J.5.18 r2 [${lang}] a partial run does not read as a finished one`,
     partial.includes('{done}') && partial.includes('{total}')
     && partial.includes('{failed}'), partial)
  ok(`J.5.18 r2 [${lang}] the union/subtract rule is stated where tags are typed`,
     /(union|uni[óa]o|resta|subtract|substitui|reemplaza|replace|carries|carrega|lleva)/i
       .test(cat[lang]['tags.bulk_hint']))
}

/* -- rule 3, on the wire: the write is the MERGE -------------------------- */

ok('J.5.18 r3 each node is read before it is written',
   /api\.call\(forest, 'look',\s*\{ id, fields: \['tags'\] \}\)/.test(
     tagsView.replace(/\n\s*/g, ' ')))
ok('J.5.18 r3 the merged list is what gets grafted',
   /const next = mode === 'apply'\s*\? unionTags\(current, wanted\)\s*: subtractTags\(current, wanted\)/
     .test(tagsView.replace(/\n\s*/g, ' ')))
// The typed set must never be the value of `tags` in a patch.
const writes = tagsView.match(/set_frontmatter: \{ tags: (\w+) \}/g) || []
ok('J.5.18 r3 the only tags a graft carries are the merged ones',
   writes.length === 1 && writes[0].includes('tags: next'), writes.join(' | '))
// There is no batch graft, so N calls it is — and that is one graft in one
// place, not a Promise.all that would hide which node the run reached.
ok('J.5.18 r2 the N writes are sequential, so the position is knowable',
   !/Promise\.all[^\n]*graft/.test(tagsView))

/* -- rule 4: the vocabulary is the route's, and the filter is exact ------- */

ok('J.5.18 r4 the vocabulary comes from the documented route',
   /tags: \(forest, \{ limit \} = \{\}\) =>/.test(apiClient)
   && apiClient.includes('/tags'))
ok('J.5.18 r4 the panel reads the route and computes no total of its own',
   /api\.tags\(forest\)/.test(tagsView)
   // A local reduce over the entries on screen is exactly the number J.4.3
   // forbids: it moves when the page size does.
   && !/reduce\(/.test(tagsView))
ok('J.5.18 r4 a clipped vocabulary says so, with both numbers',
   /vocab\.data\?\.truncated/.test(tagsView)
   && tagsView.includes("t('tags.vocabulary_truncated',"))
for (const lang of LANGS) {
  ok(`J.5.18 r4 [${lang}] the clipped notice names shown AND total`,
     cat[lang]['tags.vocabulary_truncated'].includes('{shown}')
     && cat[lang]['tags.vocabulary_truncated'].includes('{total}'))
  ok(`J.5.18 r4 [${lang}] the count is said to be over the scope, not the page`,
     /(scope|escopo|alcance)/i.test(cat[lang]['tags.vocabulary_hint']))
}
ok('J.5.18 r4 clicking a tag filters on the COLUMN, never on a ranked search',
   /filter: \{ tags_any: \[tag\] \}/.test(tagsView)
   && /api\.call\(forest, 'scan'/.test(tagsView))
ok('J.5.18 r4 the filtered listing starts at the principal\'s own roots',
   /browseTag\(forest, roots, next\)/.test(readConsole)
   && /rootsOf\(grant\)/.test(readConsole))
ok('J.5.18 r4 a cut listing is not presented as the whole match',
   readConsole.includes("t('tags.filter_more'"))

/* -- rule 1: the scent is editable where it is read ----------------------- */

ok('J.5.18 r1 the Read console offers the scent editor',
   readConsole.includes('<ScentEditor')
   && readConsole.includes("import { ScentEditor } from './editor.jsx'"))
// Reuse, not a second implementation: the fields, the diff and the summary
// budget are defined once and both consoles mount them.
ok('J.5.18 r1 the fields are the editor\'s own, mounted twice',
   (editor.match(/<ScentFields /g) || []).length === 2
   && /export function ScentFields/.test(editor))
ok('J.5.18 r1 the patch is derived by one function, not two',
   (editor.match(/scentFrontmatter\(/g) || []).length >= 3
   && /export function scentFrontmatter/.test(editor))
ok('J.5.18 r1 it writes through the same graft an agent makes',
   /api\.call\(forest, 'graft',\s*\{ id, patch: \{ set_frontmatter: frontmatter \} \}\)/
     .test(editor.replace(/\n\s*/g, ' ')))
ok('J.5.18 r1 it is absent without write, never disabled',
   /if \(!has\(grant, 'write'\)\) return null/.test(editor)
   && /has\(grant, 'write'\) && \(/.test(readConsole))
ok('J.5.18 r1 the three fields are exactly title, summary and tags',
   /out\.title = form\.title/.test(editor) && /out\.summary = form\.summary/.test(editor)
   && /out\.tags = tags/.test(editor))
ok('J.5.18 r1 the tags field goes through parseTags and nothing else',
   /const tags = parseTags\(form\.tags\)/.test(editor)
   && !/form\.tags\.split/.test(editor))
ok('J.5.18 r1 the bulk surface is absent without write',
   /writes && picked\.length > 0 && \(/.test(readConsole)
   && /const writes = has\(grant, 'write'\)/.test(readConsole))

console.log(failed ? `\n${failed} criterion(s) failed` : '\nall criteria met')
process.exit(failed ? 1 : 0)
