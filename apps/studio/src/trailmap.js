// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* What the path panel draws, decided (spec J.5.15, F.137).
 *
 * Separated from `views/trail.jsx` for the reason `skill.js` is separated
 * from `Skills.jsx`: the rules that decide which node belongs to which
 * stage are the criterion, and a criterion inside a React component is a
 * criterion no machine can ask about. Everything here is pure — same
 * material in, same marks out — so `check-trail.mjs` can put F.137's
 * questions to it directly.
 *
 * The canvas is not here. Colours, motion and camera are taste; these are
 * the claims.
 */

/* The stages, in the order the engine runs them (C.6c). `key` is both the
 * i18n suffix and the colour token, so adding one is one line here and one
 * line in three catalogues — never a switch statement somewhere else.
 * `cited` is last and is a walk's alone (J.5.15 rule 4). */
export const STAGES = [
  { key: 'locate', token: 'accent' },
  { key: 'sniff', token: 'graph-trail' },
  { key: 'read', token: 'type-document' },
  { key: 'cited', token: 'text' },
]

export const LOCATE = 0
export const SNIFF = 1
export const READ = 2
export const CITED = 3

/** The readable tail of an id. A branch is named by its branch —
 *  `projects/mixerllm/_index` is "mixerllm/", never the word `_index`,
 *  which is the one part of the address that says nothing. */
export function shortName(id) {
  const parts = id.split('/')
  const last = parts[parts.length - 1]
  if (last === '_index') return `${parts[parts.length - 2] || ''}/`
  return last || id
}

/** Which stages touched each node, from what the host returned.
 *
 *  `evidence` is the harvest bundle (a sweep) or the walk's assembled
 *  `read` — both carry `found_by` and `content`, which is the whole reason
 *  J.10.4 assembles them into one shape.
 *
 *  `cited` is the reply's own list and MUST be passed only for a walk
 *  (J.5.15 rule 4): there `answer_nodes` is a choice the model made,
 *  filtered by the host to what it actually opened. On a sweep `evidence`
 *  is every id in the bundle, because the reply is prose and names nothing
 *  — marking that as "cited" would draw a selection that never happened.
 *
 *  Nothing here infers. A node is in a stage because the material says so
 *  (J.5.15 rule 3), and a stage nothing reached stays empty.
 */
export function markNodes(evidence, cited) {
  const marks = new Map()
  const touch = (id, stage) => {
    if (typeof id !== 'string' || !id) return
    if (!marks.has(id)) marks.set(id, new Set())
    marks.get(id).add(stage)
  }
  for (const item of evidence || []) {
    const by = item?.found_by || []
    // `locate` and `sniff` are the retrievers. `pick`/`query` appear only
    // on a walk, and there they mean what `content` means on a sweep: text
    // that was actually handed over.
    if (by.includes('locate')) touch(item.id, LOCATE)
    if (by.includes('sniff')) touch(item.id, SNIFF)
    if (item?.content?.length || by.includes('pick') || by.includes('query')) {
      touch(item.id, READ)
    }
  }
  for (const id of cited || []) touch(id, CITED)
  return marks
}

/** The stages this run can have. A sweep passes no `cited` and therefore
 *  has three; a walk passes one — even an empty one, which is a walk that
 *  cited nothing and is a different statement from a mode that cannot. */
export const stagesFor = (cited) => (cited ? STAGES : STAGES.slice(0, CITED))

/** How far the reveal may run: one past the last stage holding anything.
 *  Empty LEADING stages are still crossed — a walk records no entry
 *  `locate`, because J.10.4 keeps only what carries text, and stalling
 *  there would hold the whole trail back over a stage that is merely
 *  unrecorded rather than empty. */
export function reachedStages(marks) {
  let last = -1
  for (const stages of marks.values()) {
    for (const s of stages) if (s > last) last = s
  }
  return last + 1
}

/** How many nodes each stage holds, by stage index. */
export function stageCounts(marks) {
  return STAGES.map((_, i) => {
    let n = 0
    for (const stages of marks.values()) if (stages.has(i)) n += 1
    return n
  })
}

/* Which stage a hop's returned SET belongs to (J.10.5 `ids`, v0.67).
 *
 * `locate` and `sniff` are the two the sweep has as well, and they mean the
 * same thing here. `scan` and `move` are navigation — a branch listed, an
 * edge followed — and what they hand back is reached exactly the way a
 * `locate` hit is: named and ranked or listed, and not yet read. They mark
 * the entry stage for that reason and never the read one, because neither
 * call returns a body.
 *
 * A Map, not an object: `hop.tool` arrives off the wire, and an object would
 * answer `constructor` with something truthy. */
const SET_STAGE = new Map([
  ['locate', 'locate'], ['sniff', 'sniff'], ['scan', 'locate'], ['move', 'locate'],
])

/** A walk's hops, in the shape the sweep's bundle already has.
 *
 *  J.10.12 delivers `hops[n]` as each step completes, and J.10.4 assembles
 *  the same steps into `read` at the end. This is that assembly, done early
 *  and by the same rule, so the map a person watches being drawn and the map
 *  left standing afterwards are the same map — only what carries text counts
 *  (`sniff` snippets, `pick` bodies, `query` rows); a `look` is a digest, and
 *  calling a summary an excerpt would blur the distinction the panel exists
 *  to make.
 */
export function evidenceFromHops(hops) {
  const byId = new Map()
  const slot = (id, by) => {
    if (typeof id !== 'string' || !id) return null
    if (!byId.has(id)) byId.set(id, { id, found_by: [], content: [] })
    const entry = byId.get(id)
    if (!entry.found_by.includes(by)) entry.found_by.push(by)
    return entry
  }
  for (const hop of hops || []) {
    if (!hop?.ok) continue
    const tool = hop.tool
    const stage = SET_STAGE.get(tool)
    if (stage) {
      // A hop that returned a set names it: `ids`, in result order, capped at
      // 10 (J.10.5, v0.67). A COUNT lights nothing — `out` says how many came
      // back and never which — so a record written before that version, which
      // has no `ids` at all, marks no node here. Absent reads as empty, never
      // as "the call returned nothing" and never as something inferred from
      // the count, the arguments, or the id the call was addressed by.
      for (const id of hop.ids || []) slot(id, stage)
    } else if (tool === 'pick' || tool === 'query') {
      // These return no set; they carry the one id they were addressed by,
      // and what they bring back is text.
      const entry = slot(hop.id, tool)
      if (entry) entry.content.push({ section: hop.args?.section || null })
    }
  }
  return [...byId.values()]
}

/** Several records of one hunt, folded into the one list `markNodes` reads.
 *
 *  A walk's close holds two, and neither contains the other. `read` (J.10.4)
 *  keeps every node whose call handed TEXT over — every id a `sniff` matched,
 *  uncapped, with the body or the rows it produced — and records nothing at
 *  all for `locate`, `scan` or `move`, because none of them returns a body.
 *  The hop records (J.10.5, v0.67) are the only place those three are written
 *  down, as `ids`, capped at 10.
 *
 *  Taking one and dropping the other is how a map drawn live goes dark at the
 *  end: every dot a `locate` hop lit while the walk ran would be dropped by
 *  the response that hop helped produce, and the entry stage would fall to
 *  zero at the exact moment the answer arrived. Both halves are the response's
 *  own material — a `hop` IS `hops[n]` (J.10.12 rule 2) — so nothing here is
 *  inferred (J.5.15 rule 3); the map left standing is the union, and never
 *  less than the map that was watched being drawn.
 *
 *  Earlier lists win the text: two records of one `pick` are one body read
 *  once, and concatenating them would draw the node as read twice.
 */
export function mergeEvidence(...lists) {
  const byId = new Map()
  for (const list of lists) {
    for (const item of list || []) {
      const id = item?.id
      if (typeof id !== 'string' || !id) continue
      let held = byId.get(id)
      if (!held) {
        held = { id, found_by: [], matches: [], content: [] }
        byId.set(id, held)
      }
      for (const by of item.found_by || []) {
        if (!held.found_by.includes(by)) held.found_by.push(by)
      }
      if (!held.matches.length && item.matches?.length) held.matches = [...item.matches]
      if (!held.content.length && item.content?.length) held.content = [...item.content]
    }
  }
  return [...byId.values()]
}

/** Where the agent actually STOOD, hop after hop (J.5.15).
 *
 *  This is the other line, and it is a different claim from `trailSegments`.
 *  That one climbs `parent` from every hit to the root: it is an ADDRESS —
 *  "the node the entry search found lives in this branch" — and it exists
 *  even on a sweep, which never moves at all. This one is a ROUTE, and only
 *  a walk has one.
 *
 *  A position is a hop that names ONE node: `move`, `pick`, `look`. A hop
 *  that returned a set (`locate`, `sniff`, `scan`) is the agent looking
 *  around from where it already is, not going somewhere — drawing a line to
 *  the first of ten results would invent a step it never took, which is the
 *  exact misreading the two-line split exists to remove.
 *
 *  Consecutive hops on the same node collapse: reading a node and then
 *  picking it is one place, twice.
 */
const STANDS_ON = new Set(['move', 'pick', 'look'])

export function hopSegments(hops, byId) {
  const stops = []
  for (const hop of hops || []) {
    if (!hop?.ok || !STANDS_ON.has(hop.tool)) continue
    const id = typeof hop.id === 'string' && hop.id ? hop.id : null
    if (!id || !byId.has(id)) continue
    if (stops.length && stops[stops.length - 1].id === id) continue
    stops.push({ id, n: hop.n })
  }
  const segments = []
  for (let i = 1; i < stops.length; i += 1) {
    // `depth` is the step number, so the reveal walks them in the order
    // they happened rather than by how deep in the tree they sit.
    segments.push({ a: stops[i - 1].id, b: stops[i].id, depth: i - 1,
                    stage: 0 })
  }
  return { segments, stops, deepest: Math.max(0, stops.length - 2) }
}

/** Root-to-node chains, deduplicated into segments.
 *
 *  Structure comes from `parent`, which J.11 has already filtered to what
 *  this principal may see, so a chain that leaves the scope simply stops
 *  and no segment is ever drawn to a node the caller cannot read (J.5.15
 *  rule 5). `byId` is that projection: absence from it is absence.
 *
 *  Ancestors are shared, so a segment is kept once and lights at the
 *  EARLIEST stage any of its users needed — drawing a shared trunk once
 *  per hit would make the root the brightest thing on a map about
 *  somewhere else.
 */
export function trailSegments(marks, byId) {
  const segments = new Map()
  for (const [id, stages] of marks) {
    if (!byId.has(id)) continue
    const first = Math.min(...stages)
    // Up through `parent` to the highest ancestor still in scope. The seen
    // guard is for a malformed payload, not for a tree: a map must not
    // hang on one.
    const chain = []
    const seen = new Set()
    let cursor = id
    while (cursor && byId.has(cursor) && !seen.has(cursor)) {
      seen.add(cursor)
      chain.unshift(cursor)
      cursor = byId.get(cursor).parent
    }
    for (let i = 1; i < chain.length; i += 1) {
      // The separator is a byte a node id cannot contain, so no two
      // different pairs can collide on one key. Written as an escape:
      // a literal NUL in the source makes git read this whole module
      // as binary, which costs it its diffs and its blame.
      const key = `${chain[i - 1]}\u0000${chain[i]}`
      const held = segments.get(key)
      if (held === undefined) {
        segments.set(key, { a: chain[i - 1], b: chain[i], stage: first, depth: i - 1 })
      } else {
        held.stage = Math.min(held.stage, first)
        held.depth = Math.min(held.depth, i - 1)
      }
    }
  }
  let deepest = 0
  for (const s of segments.values()) if (s.depth > deepest) deepest = s.depth
  return { segments: [...segments.values()], deepest }
}

/** The box that holds `points`, ignoring the outermost few per axis.
 *  `seed` puts degree-zero orphans on an outer ring, so a plain min/max is
 *  decided by the loneliest node in the forest — which spends a third of
 *  the canvas on empty sky. */
export function boxOf(points) {
  if (!points.length) return null
  const xs = points.map((n) => n.x).sort((a, b) => a - b)
  const ys = points.map((n) => n.y).sort((a, b) => a - b)
  const cut = Math.floor(xs.length * 0.03)
  const at = (arr, i) => arr[Math.min(arr.length - 1, Math.max(0, i))]
  return { x0: at(xs, cut), x1: at(xs, xs.length - 1 - cut),
           y0: at(ys, cut), y1: at(ys, ys.length - 1 - cut) }
}
