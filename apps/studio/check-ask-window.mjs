// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* J.5.19 acceptance (F.173, the console's half): the question's period,
 * checked.
 *
 * Studio has no test runner and this file is not one — it reads the Ask
 * console's source and asks it F.173's questions: that `since`/`until` are
 * offered, sent as C.13.1's own parameters on `answer`, prefilled from the
 * address, and written to no browser preference. A Python test runs it; a
 * non-zero exit is a failed criterion, named on stdout.
 *
 * The boundary is F.137's. What a reader of the source can see is the
 * decision layer: where the two values come from, which call carries them
 * and under what condition, what the label beside the answer is computed
 * from, and where they are NOT written. What it cannot see is a rendered
 * date picker or a badge on a screen — those want a browser, and asserting
 * them from the source would only assert that a string is present. Every
 * check that asserts a PRESENCE was verified to fail with the v0.78 view
 * put back; the ones that assert an absence (nothing written to storage or
 * the address, nothing validated by the console) hold on that source too
 * and are kept because they are what the next edit could break. Pass
 * another Ask source as the first argument to repeat the control. */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const askPath = process.argv[2] || join(here, 'src/views/Ask.jsx')
const src = readFileSync(askPath, 'utf8')
const locale = (lang) => JSON.parse(
  readFileSync(join(here, `src/locales/ask/${lang}.json`), 'utf8'))

let failed = 0
const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}

/* One function's body, found by its declaration and closed by brace depth,
   so a check reads THAT function and not a coincidence elsewhere. */
const bodyOf = (signature) => {
  const start = src.indexOf(signature)
  if (start < 0) return ''
  let depth = 0
  // The signature ends with the body's own brace: a destructured parameter
  // list carries braces of its own, and opening on the first one found
  // would return the parameter list and call it the function.
  let i = src.indexOf('{', start + signature.length - 1)
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++
    else if (src[i] === '}' && --depth === 0) break
  }
  return src.slice(start, i + 1)
}
/* A slice between two markers, for the things that are not functions. */
const between = (from, to) => {
  const a = src.indexOf(from)
  if (a < 0) return ''
  const b = src.indexOf(to, a)
  return b < 0 ? '' : src.slice(a, b)
}
const count = (re) => (src.match(re) || []).length

/* -- (a) read from the address at mount, exactly as `q` is --------------- */

const fromAddress = (name) => new RegExp(
  `const \\[${name}, set\\w+\\] = useState\\(\\s*\\(\\) => new URLSearchParams\\(window\\.location\\.search\\)\\.get\\('${name}'\\) \\|\\| ''\\)`)
ok('F.173 `since` is read from the address once, at mount, like `q`',
   fromAddress('since').test(src))
ok('F.173 `until` is read from the address once, at mount, like `q`',
   fromAddress('until').test(src))
ok('F.173 the console never writes the address (J.5.8: it restores a page, never a call)',
   !/useRouteState|router\.js|history\.(push|replace)|searchParams\.set|location\.search\s*=/.test(src))

/* -- (b) sent as C.13.1's parameters on `answer`, only when set ---------- */

const askBody = bodyOf('async function ask(text) {')
/* The object the `answer` POST is built from, and nothing before it: the
   fallback harvest in the same function carries the same spread, and a
   check that found the first occurrence would pass on the wrong call. */
const paramsBlock = between('const params = {', 'const t0 = performance.now()')
const sinceSpread = /\.\.\.\(since \? \{ since \} : \{\}\)/
const untilSpread = /\.\.\.\(until \? \{ until \} : \{\}\)/
ok('F.173 the `answer` request carries `since` only when set',
   askBody.includes('const params = {') && sinceSpread.test(paramsBlock))
ok('F.173 the `answer` request carries `until` only when set',
   askBody.includes('const params = {') && untilSpread.test(paramsBlock))
ok('F.173 `date_field` is never sent — `created` is the console\'s question',
   !/date_field\s*:/.test(askBody) && !/date_field/.test(paramsBlock.replace(/\/\/.*$/gm, '')))
const fallback = between("api.call(forest, 'harvest'", '.then(')
ok('F.173 the J.5.15 fallback harvest is bounded like the answer it stands in for',
   fallback.length > 0 && sinceSpread.test(fallback) && untilSpread.test(fallback))
ok('F.173 the request is the one place the window is sent from (one `answer` call)',
   count(/api\.timedCall\(forest, 'answer'/g) === 1)

/* -- (c) never a browser preference ---------------------------------------- */

ok('F.173 no `savePrefs(` call carries `since` or `until`',
   !/savePrefs\(\{[^}]*\b(since|until)\b/.test(src))
ok('F.173 `loadPrefs()` is never read for `since` or `until`',
   !/loadPrefs\(\)\.(since|until)/.test(src)
   && !/\b(since|until)\b/.test(bodyOf('function loadPrefs() {')))
ok('F.173 no browser-storage write names the window at all',
   !/localStorage\.setItem\([^)]*\b(since|until)\b/.test(src)
   && !/sessionStorage/.test(src))
ok('F.173 restoring a saved run puts the run\'s own window back (J.5.9), not a preference',
   /setSince\(run\.params\?\.since \|\| ''\)/.test(bodyOf('async function restore(id) {'))
   && /setUntil\(run\.params\?\.until \|\| ''\)/.test(bodyOf('async function restore(id) {')))

/* -- (d) two date controls, each named -------------------------------------- */

const sinceInput = /<input type="date"[^>]*value=\{since\}[^>]*aria-label=\{t\('ask\.window_since'\)\}/
const untilInput = /<input type="date"[^>]*value=\{until\}[^>]*aria-label=\{t\('ask\.window_until'\)\}/
ok('F.173 the console offers `since` as a real date input, named',
   sinceInput.test(src))
ok('F.173 the console offers `until` as a real date input, named',
   untilInput.test(src))
ok('F.173 the two controls are named once each, not shared',
   count(/ask\.window_since/g) === 1 && count(/ask\.window_until/g) === 1)
ok('F.173 the pair is grouped under the period\'s name for assistive technology',
   /role="group"\s+aria-label=\{t\('ask\.window'\)\}/.test(src))
ok('F.173 the inputs validate nothing of their own (a bad bound is C.13.1 rule 4\'s refusal)',
   !/<input type="date"[^>]*\b(min|max|pattern|required)=/.test(src)
   && !/E_SCHEMA[^\n]*(since|until)|(since|until)[^\n]*E_SCHEMA/.test(src.replace(/\/\/.*$/gm, '').replace(/\/\*[^]*?\*\//g, '')))

/* -- (e) the cURL carries the window ---------------------------------------- */

const curl = between('const curl = `curl', '`\n')
ok('F.173 the cURL the console offers carries `since` and `until` when set',
   /\.\.\.\(since \? \{ since \} : \{\}\)/.test(curl)
   && /\.\.\.\(until \? \{ until \} : \{\}\)/.test(curl))

/* -- (f) the label is the echo, never the inputs ---------------------------- */

const usedCall = between("t('ask.window_used'", '})')
ok('F.173 the "window used" label exists and is gated on the response\'s `window`',
   /result\.window && \(/.test(src) && usedCall.length > 0)
ok('F.173 the label reads `result.window.since` / `result.window.until` (C.13.1 rule 6)',
   /since: result\.window\.since/.test(usedCall) && /until: result\.window\.until/.test(usedCall))
ok('F.173 the label never reads the inputs\' own strings',
   !/since: since|until: until|\bsince,|\buntil,/.test(usedCall))
ok('F.173 the exported .md is labelled by the same echo',
   /result\.window\s*\?\s*\[`- Window: \$\{result\.window\.since/.test(
     bodyOf('function downloadMarkdown(result, question, forest) {')))

/* -- (g) a bounded run is badged in the history ----------------------------- */

const historyBody = bodyOf('function History({ open, onClose, principal, forest, onPick }) {')
ok('F.173 the run history badges a bounded run off what was SENT',
   /\(run\.params\?\.since \|\| run\.params\?\.until\) && \(/.test(historyBody)
   && /t\('ask\.history_window'\)/.test(historyBody))

/* -- the hop panel reads v0.79's record (J.10.5) ---------------------------- */

const pathBody = bodyOf('function Path({ hops }) {')
ok('F.173 a hop\'s object argument (`filter`) renders as compact JSON, arrays still join',
   /typeof v === 'object' \? JSON\.stringify\(v\)/.test(pathBody)
   && /Array\.isArray\(v\) \? v\.join\(', '\)/.test(pathBody))
ok('F.173 a `calendar` hop\'s `buckets` outcome is labelled',
   /\['buckets', 'ask\.hop_buckets'\]/.test(pathBody)
   && ['en', 'pt', 'es'].every((lang) => /\{n\}/.test(locale(lang)['ask.hop_buckets'] || '')))

/* -- (h) the words exist in the three languages ----------------------------- */

const KEYS = ['ask.window', 'ask.window_hint', 'ask.window_since', 'ask.window_until',
              'ask.window_used', 'ask.window_clear', 'ask.history_window']
for (const lang of ['en', 'pt', 'es']) {
  const d = locale(lang)
  ok(`F.173 every window key exists and is non-empty in ${lang}`,
     KEYS.every((k) => typeof d[k] === 'string' && d[k].trim().length > 0),
     KEYS.filter((k) => !d[k]).join(' '))
  ok(`F.173 ${lang}'s "window used" carries both placeholders`,
     /\{since\}/.test(d['ask.window_used'] || '') && /\{until\}/.test(d['ask.window_used'] || ''))
  ok(`F.173 ${lang} names the two ends differently`,
     d['ask.window_since'] !== d['ask.window_until'])
}

if (failed) {
  console.log(`\n${failed} criterion(s) failed`)
  process.exit(1)
}
console.log('\nall F.173 (console) criteria hold')
