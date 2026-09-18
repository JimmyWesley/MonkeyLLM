// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The bucket round's consoles, checked (spec v0.84: J.8.6, J.13.4,
 * J.13.6.1, J.20).
 *
 * Studio has no test runner and this file is not one — it reads the source
 * of the ingest console, the Models console and the notifications console
 * and asks them the round's own questions. `tests/test_v084_studio.py` runs
 * it; a non-zero exit is a failed criterion, named on stdout.
 *
 * The boundary is F.137's: what a reader of the source can see is where a
 * list comes from, what a submit puts on the wire, which answer a number is
 * printed from, and whether a control waits or follows a job. A rendered
 * card, a progress bar under a pointer and a 202 want a browser and a
 * Station, and are not asserted here.
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
const ingest = read('Ingest.jsx')
const models = read('Models.jsx')
const notify = read('Notify.jsx')
const api = readFileSync(join(here, 'src/api.js'), 'utf8')
const LANGS = ['en', 'pt', 'es']
const locale = (ns, lang) => JSON.parse(
  readFileSync(join(here, `src/locales/${ns}/${lang}.json`), 'utf8'))

let failed = 0
const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}

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

const CARD = 'function ConnectBucket({ value, onChange, stores, busy, error, '
  + 'onStorage }) {'
const card = bodyOf(ingest, CARD)
const submit = bodyOf(ingest, 'async function submit(e) {')
/* Following the job used to live inside `submit`; it is `startBatch` now,
   because the refresh left the add card for its own place in Optimize (the
   v0.85 layout round) and a second copy of "queue, POST, note the job, put
   it in the address" is how two doors come to behave differently. The
   criterion is the same one — the batch is the ordinary J.9 job, on the
   ordinary path — read across both halves. */
const startBatch = bodyOf(ingest, 'async function startBatch(body, meta) {')
const rescent = bodyOf(ingest, 'function Rescent({ forest, bound, job, onJob }) {')
const dense = bodyOf(ingest, 'function DenseLayer({ forest, job, onJob }) {')

/* -- J.8.6: connecting a bucket ----------------------------------------- */

ok('J.8.6 the card exists and is a mode of the ingest form', card.length > 0
   && /mode === 'bucket' && \(/.test(ingest))
ok('J.8.6 the submit posts an s3:// source, curated or not, with a policy',
   /mode: 'adopt', source, dest: dest \|\| undefined,/.test(submit)
   && /curate: bucket\.curate, content: bucket\.content/.test(submit))
ok('J.8.6 the source is the store\'s own bucket and prefix, resolved here',
   /export function bucketUri\(store, prefix = ''\)/.test(ingest)
   && /`s3:\/\/\$\{store\.bucket\}/.test(ingest))
ok('J.8.6 rule 1 the store list is the host\'s answer',
   /api\.stores\(\)/.test(ingest) && /stores\.data\?\.stores \|\| \[\]/.test(ingest))
ok('J.8.6 rule 1 the console carries no store, endpoint or bucket of its own',
   !/const STORES\s*=/.test(ingest)
   && !/https?:\/\/[a-z0-9.-]*s3[a-z0-9.-]*\./i.test(ingest),
   'nothing a credential could be typed into')
ok('J.8.6 rule 1 with nothing configured the card says which console configures one',
   /if \(!stores\.length\) \{/.test(card)
   && /ingest\.bucket_no_store/.test(card) && /ingest\.bucket_configure/.test(card))
ok('J.8.6 rule 2 what will be read is shown before anything starts',
   /ingest\.bucket_reads/.test(card) && /bucketUri\(chosen, value\.prefix\)/.test(card))
ok('J.8.6 rule 3 curate now or later, each with its cost beside it',
   /ingest\.bucket_curate_now_hint/.test(card)
   && /ingest\.bucket_curate_later_hint/.test(card))
ok('J.8.6 rule 4 the content policy defaults to cached and states its cost',
   /content: 'cached'/.test(ingest)
   && /const CONTENT = \['cached', 'inline'\]/.test(ingest)
   && /t\(`ingest\.bucket_content_\$\{value\.content\}_hint`\)/.test(card))
ok('J.8.6 rule 5 it is the ordinary J.9 job, on the ordinary path',
   /const out = await startBatch\(body, \{/.test(submit)
   && startBatch.length > 0
   && /const started = await api\.ingest\(forest, body\)/.test(startBatch)
   && /noteJob\(forest, started\.job\)/.test(startBatch)
   && /setJobId\(started\.job\.id\)/.test(startBatch))
ok('J.9.2 every door queues through that same one place',
   /if \(boardBusy\) \{\s*\n\s*enqueue\(forest, body, meta\)/.test(startBatch)
   && !/enqueue\(forest,/.test(submit),
   'a second queueing path is how two doors come to behave differently')
ok('J.8.6 rule 6 the report names formats before it lists files',
   /report\.unsupported_formats/.test(ingest)
   && /ingest\.unsupported_formats/.test(ingest),
   'the map is the report\'s own, never counted from the bounded list')
ok('J.5.8 the tab is nameable in the address',
   /allow: \[[^\]]*'bucket'/.test(ingest) && /allow: \[[^\]]*'storage'/.test(ingest))
ok('J.9.2 a queued bucket waits under the source it will read',
   /item\.mode === 'adopt' \|\| item\.mode === 'bucket'/.test(ingest))

/* -- J.13.6.1 rules 8 and 9: the scent pass chooses and is bounded ------- */

ok('J.13.6.1 r8 the pass takes an order',
   /ingest\.rescent_order_created/.test(rescent)
   && /ingest\.rescent_order_heat/.test(rescent))
ok('J.13.6.1 r9 and a cap on how many nodes it visits',
   /ingest\.rescent_limit/.test(rescent))
ok('J.13.6.1 both ride the call, and the default is left unsent',
   /order: order === 'created' \? undefined : order/.test(rescent)
   && /limit: limit === '' \? undefined : Number\(limit\)/.test(rescent))
ok('J.13.6.1 the api sends only what was chosen',
   /\.\.\.\(order \? \{ order \} : \{\}\)/.test(api)
   && /\.\.\.\(limit \? \{ limit: Number\(limit\) \} : \{\}\)/.test(api))
ok('J.13.6.1 r5 the bill printed is the host\'s number, never a computed one',
   /setState\(\{ nodes: started\.nodes, remaining: started\.remaining \}\)/
     .test(rescent)
   && /t\('ingest\.rescent_scope', \{ n: state\.nodes \}\)/.test(rescent))
ok('J.13.6.1 r9 what is left is said, so a second run is a decision',
   /ingest\.rescent_remaining/.test(rescent))

/* -- J.13.4: the dense layer is a job now -------------------------------- */

ok('J.13.4 the refresh follows the job instead of waiting',
   /if \(started\?\.job\) \{ setState\(\{\}\); onJob\(started\.job\) \}/.test(dense))
ok('J.13.4 the build hands its job to the board',
   /const started = await api\.buildCanopy\(forest\)/.test(models)
   && /if \(started\?\.job\) noteJob\(forest, started\.job\)/.test(models))
ok('J.13.4 the build card reads the board rather than polling its own',
   /const board = useBoard\(forest\)/.test(models)
   && /board\.jobs\.find\(\(j\) => j\.mode === 'canopy'\)/.test(models))
ok('J.13.4 the run shows done over total, not a spinner alone',
   /gauntlet\.job_progress/.test(models))
ok('J.13.4 a cancelled build says it is not resumable, in both places',
   /gauntlet\.build_cancelled/.test(models) && /ingest\.dense_cancelled/.test(dense))
ok('J.9 a report that is not an ingest report is not rendered as one',
   /const ingestShaped = \(job\) => !\['recurate', CANOPY\]\.includes\(job\?\.mode\)/
     .test(ingest)
   && /job\.report && ingestShaped\(job\)/.test(ingest))

/* -- J.20: the inbound trigger ------------------------------------------ */

ok('J.20 r4 the console is admin on this forest',
   /has\(grant, 'admin'\)/.test(notify) && /notify\.needs_admin/.test(notify))
ok('J.20 r4 the secret is rendered from the creation answer alone',
   /setSecret\(\{ secret: made\.secret, id: made\.subscription\?\.id \}\)/
     .test(notify)
   && !/s\.secret/.test(notify),
   'the listing has no secret to render')
ok('J.20 r4 and it is said that it is shown once',
   /notify\.secret_once/.test(notify) && /notify\.create_hint/.test(notify))
ok('J.20 the address to POST to is the host\'s path on this origin',
   /const url = `\$\{location\.origin\}\$\{path\}`/.test(notify)
   && /const path = subs\.data\?\.url/.test(notify)
   && /ingest\/notify/.test(notify))
ok('J.8.5 the key ceiling and the skew are the host\'s numbers',
   /limits\.max_keys/.test(notify)
   && /limits\.skew_seconds \?\? SKEW/.test(notify))
ok('J.20 r1 the snippet signs <timestamp>.<body> under the subscription',
   /at \+ '\.' \+ body/.test(notify)
   && /at\.encode\(\) \+ b"\." \+ body/.test(notify)
   && /X-MonkeyLLM-Subscription/.test(notify))
ok('J.20 r3 one refusal for every cause, said where it is debugged',
   /notify\.sign_refusal/.test(notify))
ok('J.20 what a notification may cause is stated', /notify\.causes/.test(notify))
ok('J.20 the console carries no key ceiling of its own',
   !/MAX_KEYS/.test(notify)
   && LANGS.every((lang) => !/\d/.test(locale('notify', lang)['notify.url_hint'])),
   'the bound is the deployment\'s, and a console that printed it would go stale')
ok('J.20 removing one is a second decision, and its effect is said',
   /asked === s\.id \?/.test(notify) && /notify\.remove_hint/.test(notify))
ok('J.5.1 it sits in the Build group beside Webhooks, on `admin`',
   /\{ key: 'notify', group: 'build', cap: 'admin' \}/
     .test(readFileSync(join(here, 'src/components/Shell.jsx'), 'utf8')))

/* -- the strings -------------------------------------------------------- */

ok('J.5.3 the bucket card is named in the three languages',
   LANGS.every((lang) => {
     const d = locale('ingest', lang)
     return ['ingest.mode_bucket', 'ingest.bucket_store', 'ingest.bucket_reads',
             'ingest.bucket_curate_now_hint', 'ingest.bucket_content_cached_hint',
             'ingest.rescent_order_heat_hint', 'ingest.rescent_limit_hint',
             'ingest.dense_cancelled'].every((k) => d[k])
       && d['ingest.rescent_remaining'].includes('{n}')
   }))
ok('J.5.3 the notifications console is named in the three languages',
   LANGS.every((lang) => {
     const d = locale('notify', lang)
     const nav = locale('nav', lang)
     return ['notify.title', 'notify.causes', 'notify.sign_headers',
             'notify.sign_refusal', 'notify.secret_once', 'notify.url_hint']
       .every((k) => d[k])
       && d['notify.sign_skew'].includes('{n}')
       && nav['nav.notify'] && nav['nav.notify.blurb']
   }))

if (failed) {
  console.log(`\n${failed} criterion/criteria failed`)
  process.exit(1)
}
console.log('\nall bucket criteria hold')
