// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* A class name nobody else uses and no stylesheet defines is a no-op.
 *
 * This checker exists because of a real failure. The Extensions console was
 * written with `className="stack"`, `"row gap"`, `"muted"`, `"small"`,
 * `"kv"` and `"mono"` — none of which exist: not in `index.css`, not as
 * Tailwind utilities, not anywhere else in the app. Every one of them
 * silently did nothing, so the console shipped with no gap between its
 * cards, its button and its hint on one crushed line, and its labels
 * unstyled. The build was green: JSX cannot know that a class is fictional,
 * and Tailwind quietly generates nothing for a token it does not recognise.
 *
 * The rule is deliberately narrow, so it accuses only the shape that bug
 * had: a token is suspect when it is **defined in no stylesheet** AND
 * **appears in exactly one file**. A real Tailwind utility (`flex`,
 * `space-y-4`, `text-[11.5px]`) is used all over the app and clears the
 * second test; a genuinely one-off utility clears the first by being
 * recognisable Tailwind. What is left is invented vocabulary.
 *
 * `tests/test_v081_classes.py` runs it; a non-zero exit is a failed check,
 * named on stdout. Pass another src directory as the first argument to run
 * the negative control.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, extname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = process.argv[2] || join(here, 'src')
const css = readFileSync(join(here, 'src/index.css'), 'utf8')

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return walk(path)
    return ['.jsx', '.js'].includes(extname(name)) ? [path] : []
  })
}

/* Tailwind's own shapes. Anything matching these is the framework's
   vocabulary and is not ours to verify — a typo there generates nothing and
   is caught by looking, which is the trade Tailwind asks for. What this
   checker is for is the token that LOOKS like a house class. */
const TAILWIND = [
  /^-?[a-z]+(-[a-z0-9.]+)*$/,          // flex, space-y-4, text-text-3
  /\[.+\]$/,                            // text-[11.5px], grid-cols-[8rem_1fr]
  /^(sm|md|lg|xl|2xl|hover|focus|active|disabled|group-hover|dark|first|last|odd|even|peer|motion-safe|motion-reduce|print|rtl|ltr|aria-\w+|data-\[.+\]):/,
]
/* Tokens that are plain words — no dash, no bracket — are exactly the shape
   `stack`, `muted`, `small`, `kv`, `row`, `gap` and `mono` had. Tailwind has
   plain-word utilities too (`flex`, `grid`, `block`, `truncate`), and those
   are used in dozens of files, so the one-file test separates them. */
const PLAIN = /^[a-z][a-z0-9]*$/

const files = walk(src)
const seen = new Map()   // token -> Set(file)
for (const file of files) {
  const text = readFileSync(file, 'utf8')
  for (const m of text.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
    // Strip `${...}` BEFORE splitting: a first cut split on whitespace
    // first, so the innards of a template expression (`${forest}`,
    // `${a ? 'x' : 'y'}`) arrived as tokens and the checker accused ten
    // identifiers that were never class names.
    const literal = (m[1] || m[2] || '').replace(/\$\{[^{}]*\}/g, ' ')
    if (literal.includes('${')) continue        // nested braces: not ours to parse
    for (const token of literal.split(/\s+/)) {
      const clean = token.trim()
      if (!clean) continue
      if (!seen.has(clean)) seen.set(clean, new Set())
      seen.get(clean).add(file.replace(src + '/', ''))
    }
  }
}

function defined(token) {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
  return new RegExp("\\." + escaped + "(?![\\w-])").test(css)
}

let failed = 0
const suspects = []
for (const [token, where] of [...seen].sort()) {
  if (where.size > 1) continue                 // shared vocabulary
  if (defined(token)) continue                 // a real house class
  if (!PLAIN.test(token)) continue             // dashed/bracketed = Tailwind
  if (TAILWIND.some((re) => re.test(token)) && where.size > 1) continue
  suspects.push([token, [...where][0]])
}

/* Plain one-word tokens that ARE Tailwind and legitimately appear once. The
   list is short on purpose: adding to it should feel like a decision. */
const KNOWN = new Set([
  'flex', 'grid', 'block', 'inline', 'hidden', 'truncate', 'relative',
  'absolute', 'fixed', 'sticky', 'static', 'italic', 'underline', 'uppercase',
  'lowercase', 'capitalize', 'container', 'group', 'peer', 'contents',
  'transform', 'transition', 'resize', 'appearance', 'isolate', 'invisible',
])

for (const [token, file] of suspects) {
  if (KNOWN.has(token)) continue
  failed++
  console.log(`FAIL  "${token}" in ${file} — defined in no stylesheet and used in no other file`)
}

console.log(failed
  ? `\n${failed} invented class name(s)`
  : `\nall ${seen.size} class tokens are defined or shared`)
process.exit(failed ? 1 : 0)
