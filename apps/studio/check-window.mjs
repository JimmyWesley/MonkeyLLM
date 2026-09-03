// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* J.5.4 acceptance (F.170): the timeline is a window, checked.
 *
 * Studio has no test runner and this file is not one — it reads the graph
 * view's source and asks it F.170's questions. `tests/test_v076_window.py`
 * runs it; a non-zero exit is a failed criterion, named on stdout.
 *
 * The boundary is F.137's. What a reader of the source can see is the
 * decision layer: which set the simulation steps and which set the paint
 * reads, what the readout is computed from, where the window is written
 * and where it is not. What it cannot see is a rendered slider, a thumb
 * under a pointer or a canvas — those want a browser, and asserting them
 * from the source would only assert that a string is present. Every check
 * below was verified to fail with the v0.75 view put back; pass another
 * graph source as the first argument to repeat that control. */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const graphPath = process.argv[2] || join(here, 'src/views/graph.jsx')
const src = readFileSync(graphPath, 'utf8')
const css = readFileSync(join(here, 'src/index.css'), 'utf8')
const locale = (lang) => JSON.parse(
  readFileSync(join(here, `src/locales/graph/${lang}.json`), 'utf8'))

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
  let i = src.indexOf('{', start)
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++
    else if (src[i] === '}' && --depth === 0) break
  }
  return src.slice(start, i + 1)
}
const count = (re) => (src.match(re) || []).length

/* -- two controls on one scale, each named ------------------------------- */

const startInput = /<input type="range"[^>]*aria-label=\{t\('graph\.window_start'\)\}/
const endInput = /<input type="range"[^>]*aria-label=\{t\('graph\.window_end'\)\}/
ok('F.170 the timeline carries a start control that is a real range',
   startInput.test(src))
ok('F.170 the timeline carries an end control that is a real range',
   endInput.test(src))
ok('F.170 the two controls are named once each, not shared',
   count(/graph\.window_start/g) === 1 && count(/graph\.window_end/g) === 1)
const named = ['en', 'pt', 'es'].every((lang) => {
  const d = locale(lang)
  return d['graph.window_start'] && d['graph.window_end']
    && d['graph.window_start'] !== d['graph.window_end']
})
ok('F.170 both names exist in the three languages and differ from each other',
   named)
ok('F.170 the pair is grouped under the timeline name for assistive technology',
   /role="group"\s+aria-label=\{t\('graph\.timeline'\)\}/.test(src))

/* -- the start defaults to the origin ------------------------------------ */

ok('F.170 the window opens at the origin (state)',
   /useState\(\{ from: 0, t: Infinity, playing: false \}\)/.test(src))
ok('F.170 a new projection resets the window to the whole forest (build)',
   /setTimeline\(\{ from: 0, t: nodes\.length, playing: false \}\)/.test(src))

/* -- a node outside the window leaves the picture and never the physics -- */

const filters = bodyOf('const applyFilters = useCallback((s) => {')
ok('F.170 `shown` is the window applied to the simulated set, in applyFilters',
   /n\.shown = n\.on && n\.bornRank >= s\.from/.test(filters))
const stepBody = bodyOf('export function step(sim, w, h, p) {')
ok('F.170 the simulation steps `on` and never reads `shown`',
   /if \(n\.on\) live\.push\(n\)/.test(stepBody) && !/shown/.test(stepBody))
ok('F.170 springs stay in the physics on `on`, not on `shown`',
   /spring\.on = s\.nodes\[spring\.a\]\.on && s\.nodes\[spring\.b\]\.on/.test(filters))
const drawBody = bodyOf('const draw = useCallback(() => {')
ok('F.170 the paint skips a node outside the window',
   /if \(!n\.shown \|\| !inView\(n\)\) continue/.test(drawBody))
ok('F.170 the paint skips a trail with an end outside the window',
   /!a\.shown \|\| !b\.shown/.test(drawBody))
ok('F.170 the paint never reads `on` (the simulated set) directly',
   !/\.on\b/.test(drawBody))
const nodeAtBody = bodyOf('const nodeAt = (p) => {')
ok('F.170 the hand cannot reach a node outside the window',
   /if \(!n\.shown\) continue/.test(nodeAtBody) && !/\.on\b/.test(nodeAtBody))
const fitBody = bodyOf('const fit = useCallback((lerp = 1) => {')
ok('F.170 the camera frames what is shown, not what is simulated',
   /if \(!n\.shown\) continue/.test(fitBody) && !/\.on\b/.test(fitBody))
ok('F.170 moving the start repaints without reheating the layout',
   /const windowMoved = from !== s\.from/.test(src)
   && /\} else if \(windowMoved\) \{\s*applyFilters\(s\)\s*\}/.test(src))

/* -- the readout, "now", and play ---------------------------------------- */

ok('F.170 the readout counts the nodes inside the window over the total',
   /\{shown - from\}\/\{total\}/.test(src))
ok('F.170 the readout names both days when the window has a start',
   /windowed \? `\$\{fromStamp\} → \$\{stamp\}` : stamp/.test(src))
const toNowBody = bodyOf('const toNow = useCallback(() => {')
ok('F.170 "now" restores the whole forest — start at the origin, end at now',
   /setTimeline\(\{ from: 0, t: sim\.current\.nodes\.length, playing: false \}\)/
     .test(toNowBody))
ok('F.170 "now" is asleep only when the window IS the whole forest',
   /const whole = atNow && from === 0/.test(src) && /disabled=\{whole\}/.test(src))
const playBody = bodyOf('const play = useCallback(() => {')
ok('F.170 play grows the window from its own start and holds the start',
   /setTimeline\(\{ from, t: from, playing: true \}\)/.test(playBody))
ok('F.170 play reseeds only from the origin — a window is not restaged',
   /if \(from === 0\) \{[^]*?seed\(s,/.test(playBody))
ok('F.170 the loop carries the start through every tick of the replay',
   count(/setTimeline\(\(cur\) => \(\{ \.\.\.cur, t: /g) >= 2)

/* -- never persisted, never the address ---------------------------------- */

ok('F.170 the only browser-storage write is the view settings, not the window',
   count(/localStorage\.setItem\(/g) === 1
   && /localStorage\.setItem\(settingsKey\(forest\),\s*JSON\.stringify\(\{ \.\.\.settings, query: '' \}\)\)/.test(src)
   && !/localStorage\.setItem\([^)]*timeline/.test(src))
ok('F.170 the view settings carry no window',
   !/from:|window/.test(bodyOf('const DEFAULTS = {')))
ok('F.170 the graph view never touches the address',
   !/useRouteState|router\.js|history\.(push|replace)/.test(src))

/* -- the two thumbs stay reachable --------------------------------------- */

ok('F.170 the start cannot pass the end (start ≤ end - 1)',
   /Math\.min\(Number\(ev\.target\.value\), Math\.max\(0, shown - 1\)\)/.test(src))
ok('F.170 the end cannot pass the start (end ≥ start + 1 once a start is set)',
   /Math\.max\(Number\(ev\.target\.value\), from > 0 \? from \+ 1 : 0\)/.test(src))
ok('F.170 the thumb nearest the pointer is raised, and not while one is held',
   /if \(grabbing\.current\) return/.test(src)
   && /const nearest = x < \(pctFrom \+ pct\) \/ 2 \? 'from' : 'to'/.test(src))
ok('F.170 an input is inert except for its thumb; the front one is whole',
   /\.graph-window-thumb \{[^}]*pointer-events: none;/.test(css)
   && /\.graph-window-thumb\.is-front \{ pointer-events: auto; \}/.test(css)
   && /::-webkit-slider-thumb \{[^}]*pointer-events: auto;/.test(css)
   && /::-moz-range-thumb \{[^}]*pointer-events: auto;/.test(css))

if (failed) {
  console.log(`\n${failed} criterion(s) failed`)
  process.exit(1)
}
console.log('\nall F.170 criteria hold')
