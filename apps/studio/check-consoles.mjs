// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* A console entry is complete, or the app does not load (Part L, v0.80).
 *
 * This checker exists because of a real failure and describes exactly it:
 * `extensions` was added to `CONSOLES` and to `VIEWS`, and NOT to
 * `CONSOLE_ICON`. The nav then rendered `<Icon/>` where `Icon` was
 * `undefined`, which is React error #130 — and because the nav renders on
 * every page, a missing icon took down **every console**, including ones
 * nobody had touched. The build was green: JSX does not know that a lookup
 * in a plain object can miss.
 *
 * So the criterion is not "extensions has an icon". It is: every console
 * the shell offers has all four things it needs — a view to render, an
 * icon to draw, and a label and a blurb in all three languages. A console
 * added tomorrow is checked tomorrow, which is the route canary's rule
 * (`test_station_admin_scope`) applied to the front end.
 *
 * `tests/test_v080_consoles.py` runs it; a non-zero exit is a failed
 * criterion, named on stdout. Pass another Shell source as the first
 * argument to run the negative control. */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const shellPath = process.argv[2] || join(here, 'src/components/Shell.jsx')
const shell = readFileSync(shellPath, 'utf8')
const icons = readFileSync(join(here, 'src/design/icons.jsx'), 'utf8')
const app = readFileSync(join(here, 'src/App.jsx'), 'utf8')
const nav = (lang) => JSON.parse(
  readFileSync(join(here, `src/locales/nav/${lang}.json`), 'utf8'))

let failed = 0
const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}

/* The object literal that follows a `const NAME = {` or `export const
   NAME = {`, closed by brace depth so a nested object cannot end it. */
function literal(src, name) {
  const start = src.search(new RegExp(`(export\\s+)?const\\s+${name}\\s*=\\s*[{[]`))
  if (start < 0) return ''
  const open = src.slice(start).search(/[{[]/) + start
  const close = { '{': '}', '[': ']' }[src[open]]
  let depth = 0
  for (let i = open; i < src.length; i++) {
    if (src[i] === src[open]) depth++
    else if (src[i] === close) { depth--; if (!depth) return src.slice(open, i + 1) }
  }
  return ''
}

const consolesBlock = literal(shell, 'CONSOLES')
const keys = [...consolesBlock.matchAll(/key:\s*'([a-z]+)'/g)].map((m) => m[1])
ok('the shell offers consoles at all', keys.length >= 10, `${keys.length} found`)

const iconMap = literal(icons, 'CONSOLE_ICON')
const iconKeys = new Set(
  [...iconMap.matchAll(/([a-z]+)\s*:/g)].map((m) => m[1]))
const viewMap = literal(app, 'VIEWS')
const viewKeys = new Set(
  [...viewMap.matchAll(/([a-z]+)\s*:/g)].map((m) => m[1]))

const langs = ['en', 'pt', 'es']
const labels = Object.fromEntries(langs.map((l) => [l, nav(l)]))

for (const key of keys) {
  // An icon, or the nav renders `undefined` and the whole app is a blank
  // screen with React #130 in the console.
  ok(`${key}: has an icon`, iconKeys.has(key))
  // A view, or the address resolves to nothing.
  ok(`${key}: has a view`, viewKeys.has(key))
  for (const lang of langs) {
    ok(`${key}: ${lang} label`, typeof labels[lang][`nav.${key}`] === 'string')
    ok(`${key}: ${lang} blurb`,
       typeof labels[lang][`nav.${key}.blurb`] === 'string')
  }
}

/* The other direction: an icon or a view for a console nobody offers is
   dead weight, and usually the leftover of a rename. */
for (const key of iconKeys) {
  ok(`icon ${key} belongs to a console`, keys.includes(key))
}

console.log(failed ? `\n${failed} check(s) failed` : '\nall checks passed')
process.exit(failed ? 1 : 0)
