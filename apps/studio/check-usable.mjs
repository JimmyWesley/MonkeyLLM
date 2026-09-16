// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* F.218 (spec v0.83): the consoles carry no list of their own.
 *
 * An operator installed a PDF converter and the ingest console greyed out
 * every .pdf; a transcriber registered a role and the Models console had no
 * card for it. Both consoles kept a list in their source — formats in one,
 * roles in the other — and neither list could learn what the mechanism
 * under it had changed. The criterion is therefore about where the lists
 * COME FROM, which a reader of the source can see (F.137's boundary):
 *
 *   - Ingest reads `formats` off the ingest status and keeps no ACCEPT/BINARY
 *     constant; a file is refused by what the host answered.
 *   - Models renders its cards from the `.roles` the bindings answer carries
 *     and iterates no local role list.
 *   - Extensions sends `enable_on` with the install, reads `activated` and
 *     `loaded`, and reviews in place — no install-side Modal.
 *
 * `tests/test_v083_usable_console.py` runs it, and runs it again against
 * the v0.82 sources as the negative control. Pass a directory holding the
 * three views as the first argument to point it elsewhere. */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const views = process.argv[2] || join(here, 'src/views')
const read = (name) => readFileSync(join(views, name), 'utf8')
const ingest = read('Ingest.jsx')
const models = read('Models.jsx')
const extensions = read('Extensions.jsx')

let failed = 0
const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}

// -- Ingest: formats from the host, never a constant -------------------------
ok('ingest keeps no ACCEPT list', !/const ACCEPT\s*=/.test(ingest))
ok('ingest keeps no BINARY list', !/const BINARY\s*=/.test(ingest))
ok('ingest reads formats off the status', /status\.formats/.test(ingest))
ok('the picker accepts what the host answered',
   /accept=\{accepted\s*\?/.test(ingest))
ok('a file is refused by the host\'s answer, before upload',
   /accepted && !accepted\.has\(/.test(ingest))
ok('the refusal names what the forest takes', /ingest\.accepts/.test(ingest))

// -- Models: cards from the host's roles -------------------------------------
ok('models iterates no local role list', !/ROLES\.map\(/.test(models))
ok('models renders from the answer\'s roles',
   /bindings\.data\?\.roles/.test(models) && /roles\.map\(/.test(models))
ok('models binds the whole answer, not only .bindings',
   /api\.bindings\(forest\)\s*,/.test(models))
ok('the form is shaped by kind', /CHAT_SHAPED/.test(models)
   && /chatShaped && \(/.test(models))
ok('an extension role shows its description',
   /role\.description \|\| t\('models\.role_ext_sub'/.test(models))

// -- Extensions: one legible act ---------------------------------------------
ok('enabling rides the install', /enable_on: forest/.test(extensions))
ok('the outcome reads activated', /outcome\.activated/.test(extensions))
ok('the listing reads loaded', /ext\.loaded === false/.test(extensions))
ok('the review is in place, not a dialog',
   /function Review\(/.test(extensions) && !/onInstall=\{async \(src, up\)/.test(extensions))
ok('the review says what the forest will accept', /plan\.formats/.test(extensions))
ok('a restart is stated only when needed', /ext\.restart\.pending/.test(extensions))

if (failed) {
  console.log(`\n${failed} criterion/criteria failed`)
  process.exit(1)
}
console.log('\nall criteria hold')
