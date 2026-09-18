// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* J.19's console, checked (spec v0.84, F.219-F.228's console half).
 *
 * Studio has no test runner and this file is not one — it reads the source
 * of the Storage tab and the reading panel and asks them J.19.9's and
 * J.14's questions. `tests/test_v084_studio.py` runs it; a non-zero exit is
 * a failed criterion, named on stdout.
 *
 * The boundary is F.137's. What a reader of the source can see is the
 * decision layer: where the reach comes from, which fields are rendered,
 * what a blank credential sends, and whether a byte route is reached by a
 * fetch or by a navigation. What it cannot see is a rendered table, a
 * pointer on a button or a 302 — those want a browser and a Station, and
 * asserting them from the source would only assert that a string is
 * present.
 *
 * Pass a directory holding the views as the first argument to point it
 * elsewhere (the v0.83 sources are the negative control).
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const views = process.argv[2] || join(here, 'src/views')
const read = (name) => readFileSync(join(views, name), 'utf8')
const storage = read('storage.jsx')
const ingest = read('Ingest.jsx')
const files = read('files.jsx')
const api = readFileSync(join(here, 'src/api.js'), 'utf8')
const LANGS = ['en', 'pt', 'es']
const locale = (ns, lang) => JSON.parse(
  readFileSync(join(here, `src/locales/${ns}/${lang}.json`), 'utf8'))

let failed = 0
const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}

/* One function's body, found by its declaration and closed by brace depth,
   so a check reads THAT function and not a coincidence elsewhere. */
const bodyOf = (src, signature) => {
  const start = src.indexOf(signature)
  if (start < 0) return ''
  let depth = 0
  let i = src.indexOf('{', start + signature.length - 1)
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++
    else if (src[i] === '}' && --depth === 0) break
  }
  return src.slice(start, i + 1)
}

const TABLE = 'function StoreTable({ stores, mayEdit, onChanged, onError }) {'
const FORM = 'function StoreForm({ stores, onSaved, onError }) {'
const BINDING = 'function Binding({ forest, stores, status, onBound, onError }) {'
const table = bodyOf(storage, TABLE)
const form = bodyOf(storage, FORM)
const binding = bodyOf(storage, BINDING)

/* -- the reach: read from the route, never computed --------------------- */

/* The store surface is a SECTION of the ingest console rather than a tab of
   it (the v0.85 layout round): J.19.9 puts it in Build → Ingest and says
   nothing about which shape it takes there, and `?mode=storage` still names
   it because an address outlives the layout that produced it (J.5.8). What
   this asserts is unchanged in substance — only an administrator is offered
   it, and it is reachable by name. */
ok('J.19.2 the store surface is offered to an administrator of this forest',
   /has\(grant, 'admin'\) && \(\s*\n\s*<section ref=\{storageAt\}/.test(ingest)
   && /<Storage forest=\{forest\}/.test(ingest))
ok('J.19.9 and it is still nameable in the address',
   /allow: \[[^\]]*'storage'/.test(ingest)
   && /place === 'storage' \? storageAt/.test(ingest))
ok('J.19.2 whether the reader may EDIT is the route\'s answer',
   /stores\.data\?\.may_manage/.test(storage))
ok('J.19.2 the console does not compute "administers every forest" itself',
   !/grants\.(every|filter)/.test(storage) && !/forests\.length/.test(storage))
ok('J.19.9 a reader who may only look is told so, where the controls are not',
   /storage\.reach_read_hint/.test(storage)
   && /\{!mayEdit && <Note>/.test(storage))
ok('J.19.2 every editing control is behind that same answer',
   table.includes('{mayEdit && (')
   && /\{mayEdit && \(\s*\n\s*<StoreForm/.test(storage))

/* -- the credential: write-only, on every surface ----------------------- */

ok('J.19.1 the listing renders `has_key` and nothing else about the key',
   /s\.has_key \?/.test(storage)
   && !/\.secret_key\b(?!:)/.test(table))
ok('J.19.1 no credential is ever read back off a response',
   !/(store|s|data)\.(secret_key|access_key)/.test(storage),
   'the form reads its own state, never the API\'s answer')
ok('J.19.1 editing a store opens with the credential fields empty',
   /setForm\(\{\s*\n?\s*\.\.\.EMPTY_FORM,/.test(form)
   && /access_key: '', secret_key: ''/.test(storage))
ok('J.19.1 a blank credential sends `null`, which means keep',
   /access_key: form\.access_key \|\| null/.test(form)
   && /secret_key: form\.secret_key \|\| null/.test(form))
ok('J.19.1 the pair moves together, refused here by name',
   /const half = Boolean\(form\.access_key\) !== Boolean\(form\.secret_key\)/
     .test(form)
   && /storage\.key_pair/.test(form))
ok('J.19.1 a name is fixed once the store exists',
   /disabled=\{Boolean\(editing\)\}/.test(form))

/* -- the environment-declared store ------------------------------------- */

ok('J.19.4 an env store carries no remove control',
   /\{mayEdit && !env && \(/.test(storage))
ok('J.19.4 an env store is not offered for editing either',
   /filter\(\(s\) => s\.source !== 'environment'\)/.test(form))
ok('J.19.4 and the reason is said, not implied',
   /storage\.env_locked/.test(storage) && /storage\.env_note/.test(storage))

/* -- the test is a write, and says what it did -------------------------- */

ok('J.19.3 the test reports its steps, not one word',
   /const steps = probe\.steps \|\| \[\]/.test(storage)
   && /steps\.map\(/.test(storage))
ok('J.19.3 a step carries its own verdict, and its own name',
   /c\.ok \? <Check size=\{12\} \/> : <X size=\{12\} \/>/.test(storage)
   && /t\(`storage\.step_\$\{c\.step\}`\)/.test(storage))
ok('J.19.3 a probe that could not be removed says where it is',
   /storage\.probe_left/.test(storage),
   'an object this credential can create and cannot delete is a fact about the grant')

/* -- the binding: a name, and what it changes --------------------------- */

ok('J.19.5 the binding sends a NAME and nothing else',
   /api\.setIngestConfig\(forest, \{ assets: choice \|\| null \}\)/.test(binding))
ok('J.19.5 no endpoint, bucket or credential is on the binding form',
   !/endpoint/.test(binding) && !/bucket/.test(binding))
ok('J.19.10 it says it decides the NEXT original and moves nothing',
   /storage\.binding_next/.test(binding))
ok('J.19.9 an unmet expectation is named where the binding is set',
   /const unmet = status\?\.assets_missing/.test(binding)
   && /storage\.unmet/.test(binding),
   'the host decides it; the comparison is what an older answer is read with')
ok('J.19.9 the unmet name stays selectable, so a save cannot silently change it',
   /\{unmet && <option value=\{bound\}>/.test(binding))
ok('J.19.2 removing a store is a second decision',
   /asked === s\.name \?/.test(storage) && /storage\.remove_confirm/.test(storage))
ok('J.19.2 and what a removal does NOT do is said',
   /storage\.remove_hint/.test(storage))

/* -- J.14 (v0.84): a remote original is a link, never a fetch ----------- */

const original = bodyOf(files, 'function Original({ forest, d, meta }) {')
ok('J.14 a remote payload is offered',
   /const remote = !local &&/.test(original)
   && /\{remote && \(/.test(original))
ok('J.14 rule 5 it ASKS for the URL and navigates to what comes back',
   /onClick=\{open\}/.test(original)
   && /await api\.payloadUrl\(forest, d\.id\)/.test(original)
   && /window\.open\(url, '_blank', 'noopener'\)/.test(original))
ok('J.14 rule 5 no bare href to the payload route — it carries no credential',
   !/href=\{api\.payload/.test(original) && !/payloadHref/.test(api),
   'a top-level navigation sends no Authorization header, so it answers 401')
ok('J.14 nothing fetches a payload that may redirect',
   /\{local && \(\s*\n\s*<button type="button" className="btn btn-sm" onClick=\{save\}/
     .test(original),
   'the blob path is reachable only for bytes the digest sized')
ok('J.14 rule 5 the ask is explicit, under the viewer\'s own credential',
   /payloadUrl: async \(forest, node\) =>/.test(api)
   && /Accept: 'application\/json'/.test(api)
   && /Authorization: `Bearer \$\{getKey\(\)\}`/.test(api))
ok('J.14 the link is named in the three languages',
   LANGS.every((lang) => locale('files', lang)['files.original_open']
     && locale('files', lang)['files.original_remote']))

/* -- the strings ------------------------------------------------------- */

const KEYS = ['storage.stores', 'storage.binding', 'storage.binding_local',
              'storage.binding_next', 'storage.unmet', 'storage.key_keep',
              'storage.key_pair', 'storage.reach_read_hint', 'storage.test',
              'storage.remove_hint', 'storage.path_style_hint']
ok('J.5.3 every string exists in the three languages, placeholders intact',
   LANGS.every((lang) => {
     const d = locale('storage', lang)
     return KEYS.every((k) => d[k]) && d['storage.unmet'].includes('{name}')
       && d['storage.editing'].includes('{name}')
   }))

if (failed) {
  console.log(`\n${failed} criterion/criteria failed`)
  process.exit(1)
}
console.log('\nall storage criteria hold')
