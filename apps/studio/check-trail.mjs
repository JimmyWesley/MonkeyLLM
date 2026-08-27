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
 * What this cannot see is the canvas — colours, motion, camera — and it is
 * not supposed to: those are taste, and F.137 is about claims. */
import {
  CITED, LOCATE, READ, SNIFF, markNodes, reachedStages, shortName,
  stageCounts, stagesFor, trailSegments,
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
