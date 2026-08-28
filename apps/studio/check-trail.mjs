// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* J.5.15 acceptance (F.137): what the path panel marks, checked.
 *
 * Studio has no test runner and this file is not one — it is the console's
 * decision layer, asked the criterion's own questions. `trailmap.js` holds
 * the rules precisely so they can be asked here rather than inferred from
 * a screenshot. `tests/test_trail_panel.py` runs it; a non-zero exit is a
 * failed criterion, named on stdout.
 *
 * A walk is asked one more thing than a sweep is, and it is asked of two
 * objects rather than one: the panel fills from J.10.12's `hop` events while
 * the call is open and from the response's own records at the close (J.5.15
 * rule 2), so the material has to be assembled twice. The picture drawn live
 * MUST therefore be contained in the picture left standing — no dot lights
 * during a hunt and goes dark when its answer arrives — and that is a
 * question about `evidenceFromHops` and `mergeEvidence` together, which is
 * why they are asked it here rather than inferred from a screenshot either.
 *
 * What this cannot see is the canvas — colours, motion, camera — and it is
 * not supposed to: those are taste, and F.137 is about claims. */
import {
  CITED, LOCATE, READ, SNIFF, STAGES, evidenceFromHops, markNodes,
  mergeEvidence, reachedStages, shortName, stageCounts, stagesFor,
  trailSegments,
} from './src/trailmap.js'

let failed = 0
const ok = (n, c, extra = '') => {
  if (!c) failed++
  console.log(`${c ? 'PASS' : 'FAIL'}  ${n}${extra ? '  ' + extra : ''}`)
}

/* A projection shaped like J.11's: id -> {parent}. */
const projection = (pairs) => new Map(pairs.map(([id, parent]) => [id, { id, parent }]))

const FOREST = projection([
  ['_index', null],
  ['projects/_index', '_index'],
  ['projects/mixerllm/_index', 'projects/_index'],
  ['projects/mixerllm/experiment-log', 'projects/mixerllm/_index'],
  ['projects/mixerllm/benchmarks', 'projects/mixerllm/_index'],
  ['people/_index', '_index'],
])

/* -- rule 3: a stage is what the material says, never an inference ------- */

const sweep = [
  { id: 'projects/mixerllm/experiment-log', found_by: ['locate', 'sniff'],
    content: [{ section: null, body: 'x' }] },
  { id: 'projects/mixerllm/benchmarks', found_by: ['sniff'], content: [] },
  { id: 'people/_index', found_by: ['locate'], content: [] },
]
const m1 = markNodes(sweep, undefined)

ok('F.137 `locate` in found_by marks the entry stage',
   m1.get('projects/mixerllm/experiment-log').has(LOCATE)
   && m1.get('people/_index').has(LOCATE))
ok('F.137 no `locate` in found_by does not mark the entry stage',
   !m1.get('projects/mixerllm/benchmarks').has(LOCATE),
   [...m1.get('projects/mixerllm/benchmarks')].join(','))
ok('F.137 `sniff` marks the literal stage and only where present',
   m1.get('projects/mixerllm/benchmarks').has(SNIFF)
   && !m1.get('people/_index').has(SNIFF))
ok('F.137 content handed over marks the read stage, an empty list does not',
   m1.get('projects/mixerllm/experiment-log').has(READ)
   && !m1.get('people/_index').has(READ))

const counts1 = stageCounts(m1)
ok('F.137 counts are what the material carries',
   counts1[LOCATE] === 2 && counts1[SNIFF] === 2 && counts1[READ] === 1
   && counts1[CITED] === 0, counts1.join('/'))

/* -- rule 4: `cited` is a walk's stage and not a sweep's ------------------ */

ok('F.137 a sweep produces no cited stage at all',
   stagesFor(undefined).length === 3
   && !stagesFor(undefined).some((s) => s.key === 'cited'))
ok('F.137 a sweep marks nothing as cited even when ids are known',
   stageCounts(markNodes(sweep, undefined))[CITED] === 0)

const walk = [
  { id: 'projects/mixerllm/experiment-log', found_by: ['sniff', 'pick'],
    content: [{ section: null, body: 'x' }] },
  { id: 'projects/mixerllm/benchmarks', found_by: ['sniff'], content: [] },
]
const m2 = markNodes(walk, ['projects/mixerllm/experiment-log'])
ok('F.137 a walk with answer_nodes produces a cited stage',
   stagesFor(['x']).length === 4
   && m2.get('projects/mixerllm/experiment-log').has(CITED))
ok('F.137 a walk cites only what it names',
   !m2.get('projects/mixerllm/benchmarks').has(CITED))
ok('F.137 a walk that cited nothing still HAS the stage',
   stagesFor([]).length === 4, 'empty is a statement, absent is a mode')
ok('F.137 a walk `pick` marks the read stage',
   m2.get('projects/mixerllm/experiment-log').has(READ))
ok('F.137 an unrecorded entry locate leaves the stage empty, not filled',
   stageCounts(m2)[LOCATE] === 0)

/* -- the reveal crosses an empty leading stage, never stalls on it ------- */

ok('F.137 the reveal reaches past an empty entry stage on a walk',
   reachedStages(m2) === CITED + 1, String(reachedStages(m2)))
ok('F.137 nothing marked reaches no stage', reachedStages(new Map()) === 0)

/* -- rule 2: the map watched being drawn is the map left standing --------- */

/* A walk as the host records it (J.10.5, v0.67): `ids` on the calls whose
   result is a set, the addressed `id` on the ones that hand text back, and
   two refusals — a hunt that never mistypes a term is not a hunt, and a
   refused call is exactly where an assembly is tempted to draw the node it
   was ABOUT. J.10.12 rule 2 makes every event a prefix of this list, so the
   live panel is this same list truncated wherever the answer has got to. */
const HOPS = [
  { n: 1, tool: 'locate', args: { query: 'latency' }, out: 3, ok: true,
    ids: ['projects/mixerllm/experiment-log', 'projects/mixerllm/benchmarks',
          'people/_index'] },
  { n: 2, tool: 'look', id: 'projects/mixerllm/benchmarks', out: 120, ok: true },
  { n: 3, tool: 'sniff', args: { terms: ['p95'] }, out: 'E_SCHEMA', ok: false },
  { n: 4, tool: 'pick', id: 'people/_index', out: 'E_NOT_FOUND', ok: false },
  { n: 5, tool: 'scan', id: 'projects/_index', out: 2, ok: true,
    ids: ['projects/mixerllm/_index'] },
  { n: 6, tool: 'pick', id: 'projects/mixerllm/experiment-log',
    args: { section: 'Results' }, out: 812, ok: true },
]

/* What J.10.4 assembles for that same walk: only the calls that handed TEXT
   over, so the `locate` and the `scan` are not in it at all. That is the
   whole reason the close is a union — the response's own `read` is not a
   superset of the hops, and taking it alone would put the entry stage back
   to zero at the moment the answer landed. */
const WALK_READ = [
  { id: 'projects/mixerllm/experiment-log', found_by: ['pick'], matches: [],
    content: [{ section: 'Results', body: 'p95 fell to 19 ms', body_tokens: 6 }] },
]

const finalMarks = markNodes(mergeEvidence(WALK_READ, evidenceFromHops(HOPS)),
                             ['projects/mixerllm/experiment-log'])
const finalCounts = stageCounts(finalMarks)

/* Every moment of the walk, not merely its last one: a dot may go out at any
   hop, and a check that only compared the finished list against itself would
   see none of them. */
let dark = null
let dropped = null
for (let n = 1; n <= HOPS.length; n += 1) {
  const liveMarks = markNodes(evidenceFromHops(HOPS.slice(0, n)), undefined)
  for (const [id, stages] of liveMarks) {
    for (const s of stages) {
      if (!finalMarks.get(id)?.has(s)) {
        dark = dark || `${shortName(id)}@${STAGES[s].key} lit at hop ${n}`
      }
    }
  }
  stageCounts(liveMarks).forEach((c, s) => {
    if (c > finalCounts[s]) {
      dropped = dropped || `${STAGES[s].key} ${c} at hop ${n} -> ${finalCounts[s]}`
    }
  })
}
ok('F.137 no node lit during a walk goes dark at its close', dark === null,
   dark || 'live marks are a subset of the close, at every hop')
ok('F.137 no stage counted during a walk falls at its close', dropped === null,
   dropped || `close ${finalCounts.join('/')}`)

/* Guards the guard: an assembly that returned nothing at all would satisfy
   every subset above forever, and so would a close that lit the whole
   forest. Both ends are stated as numbers. */
const atEntry = evidenceFromHops(HOPS.slice(0, 1))
const entryCounts = stageCounts(markNodes(atEntry, undefined))
ok('F.137 a walk lights its entry hop from `ids`, not from the count',
   entryCounts[LOCATE] === 3 && entryCounts[READ] === 0, entryCounts.join('/'))
ok('F.137 the close holds every entry the walk lit, and the text it read',
   finalCounts[LOCATE] === 4 && finalCounts[SNIFF] === 0
   && finalCounts[READ] === 1 && finalCounts[CITED] === 1, finalCounts.join('/'))
ok('F.137 a refused hop marks nothing, and unmarks nothing either',
   finalMarks.get('people/_index')?.has(LOCATE)
   && !finalMarks.get('people/_index')?.has(READ),
   [...(finalMarks.get('people/_index') || [])].join(','))
ok('F.137 a `look` hands over a digest, which is not the read stage',
   finalMarks.get('projects/mixerllm/benchmarks')?.has(LOCATE)
   && !finalMarks.get('projects/mixerllm/benchmarks')?.has(READ),
   [...(finalMarks.get('projects/mixerllm/benchmarks') || [])].join(','))

/* -- a record written before `ids` names nothing, and nothing is guessed -- */

/* A stored walk (J.10.7) outlives the version that wrote it, so this shape
   will be read for as long as those entries live. F.140: the absent field
   reads as an empty list — never as "the call returned nothing", and never
   filled in from `out`, from the arguments, or from the id the call was
   addressed by. */
const OLD = [
  { n: 1, tool: 'locate', args: { query: 'latency' }, out: 5, ok: true },
  { n: 2, tool: 'scan', id: 'projects/_index', out: 4, ok: true },
  { n: 3, tool: 'move', id: 'projects/mixerllm/_index',
    args: { rel: 'related-to' }, out: 2, ok: true },
  { n: 4, tool: 'pick', id: 'projects/mixerllm/experiment-log', out: 800, ok: true },
]
const old = evidenceFromHops(OLD)
ok('F.137 a navigation hop with no `ids` marks nothing',
   old.length === 1 && old[0].id === 'projects/mixerllm/experiment-log',
   old.map((e) => e.id).join(' '))
ok('F.137 a count is not a set: `out: 5` lights no node',
   stageCounts(markNodes(old, undefined))[LOCATE] === 0)
ok('F.137 the id a `scan` or `move` went TO is not something it brought back',
   !old.some((e) => e.id === 'projects/_index'
                    || e.id === 'projects/mixerllm/_index'))

/* -- the close is a union, and the earlier record keeps the text ---------- */

const fromRead = [
  { id: 'projects/mixerllm/experiment-log', found_by: ['sniff', 'pick'],
    matches: [{ line: 12, text: 'p95 fell to 19 ms' }],
    content: [{ section: null, body: 'the body as it was handed over' }] },
  { id: 'projects/mixerllm/benchmarks', found_by: ['sniff'],
    matches: [{ line: 3, text: 'p95' }], content: [] },
]
const fromHops = [
  { id: 'projects/mixerllm/experiment-log', found_by: ['locate', 'pick'],
    matches: [{ line: 99, text: 'a second record of one reading' }],
    content: [{ section: 'Results' }] },
  { id: 'people/_index', found_by: ['locate'], content: [] },
]
const merged = mergeEvidence(fromRead, fromHops)
const both = merged.find((e) => e.id === 'projects/mixerllm/experiment-log')
ok('F.137 the close is the union of both records, neither containing the other',
   merged.length === 3, merged.map((e) => shortName(e.id)).join(' '))
ok('F.137 a node in both keeps every retriever that reached it',
   both?.found_by.join(',') === 'sniff,pick,locate', both?.found_by.join(','))
ok('F.137 one body read once is drawn once, by the record that carried it',
   both?.content.length === 1 && both?.matches.length === 1
   && both?.matches[0]?.line === 12,
   `${both?.content.length} content / matches from line ${both?.matches[0]?.line}`)
ok('F.137 an empty list is not text, so a later record may still fill it',
   mergeEvidence([{ id: 'a', found_by: ['locate'], content: [] }],
                 [{ id: 'a', found_by: ['pick'], content: [{ section: null }] }])[0]
     .content.length === 1)
ok('F.137 a response carrying no `read` at all still draws its hops',
   mergeEvidence(undefined, atEntry).length === 3)
ok('F.137 junk survives neither the assembly nor the union',
   evidenceFromHops([null, { tool: 'pick', ok: true },
                     { tool: 'locate', ok: true, ids: [42, ''] }]).length === 0
   && mergeEvidence([{ found_by: ['locate'] }, null], [{ id: 42 }]).length === 0)

/* -- rule 5: a segment needs BOTH ends in the projection ------------------ */

const t1 = trailSegments(m1, FOREST)
const inside = t1.segments.every((s) => FOREST.has(s.a) && FOREST.has(s.b))
ok('F.137 every segment has both ends in the projection', inside,
   `${t1.segments.length} segments`)

/* The same marks against a projection that stops at the branch: a scoped
   principal receives no root, so the chain must stop there and the missing
   ancestor must not be drawn to. */
const SCOPED = projection([
  ['projects/mixerllm/_index', null],
  ['projects/mixerllm/experiment-log', 'projects/mixerllm/_index'],
  ['projects/mixerllm/benchmarks', 'projects/mixerllm/_index'],
])
const t2 = trailSegments(markNodes(sweep, undefined), SCOPED)
ok('F.137 a chain that leaves the scope stops there',
   t2.segments.every((s) => SCOPED.has(s.a) && SCOPED.has(s.b))
   && !t2.segments.some((s) => s.a === '_index' || s.b === '_index'),
   t2.segments.map((s) => `${shortName(s.a)}>${shortName(s.b)}`).join(' '))
ok('F.137 a marked node absent from the projection draws no segment',
   trailSegments(markNodes([{ id: 'ghost/node', found_by: ['locate'] }], undefined),
                 FOREST).segments.length === 0)

/* -- a shared trunk is one segment, at the earliest stage ---------------- */

const shared = t1.segments.filter((s) => s.a === '_index' && s.b === 'projects/_index')
ok('F.137 a shared ancestor is one segment', shared.length === 1,
   `${shared.length} copies`)
ok('F.137 a shared segment lights at the earliest stage that needed it',
   shared[0]?.stage === LOCATE, String(shared[0]?.stage))

/* -- naming: `_index` is the one part of an address that says nothing ---- */

ok('F.137 a branch is named by its branch',
   shortName('projects/mixerllm/_index') === 'mixerllm/'
   && shortName('projects/mixerllm/experiment-log') === 'experiment-log'
   && shortName('_index') === '/')

/* -- nothing is invented from a malformed payload ------------------------ */

ok('F.137 junk in the material marks nothing',
   markNodes([{ found_by: ['locate'] }, { id: 42, found_by: ['locate'] },
              { id: '', found_by: ['locate'] }, null], undefined).size === 0)
ok('F.137 a cycle in `parent` terminates',
   trailSegments(markNodes([{ id: 'a', found_by: ['locate'] }], undefined),
                 projection([['a', 'b'], ['b', 'a']])).segments.length <= 2)

console.log(failed ? `\n${failed} criterion(s) failed` : '\nall criteria hold')
process.exit(failed ? 1 : 0)
