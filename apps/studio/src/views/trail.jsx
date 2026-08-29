// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The path one answer took, drawn on the forest (spec J.5.4 + J.10.4).
 *
 * Explore's graph answers "what is in here". This answers a different
 * question — "what did THIS question do to it" — and that is why it is a
 * second view rather than a mode of the first: no filters, no settings,
 * nothing to tune. One question, one path, and the map is the caption.
 *
 * The one thing it does take is a hand on the view (J.5.15 rule 10, v0.67):
 * a thousand dots drawn to fit is a field of dots, and "where did that come
 * from" is read by looking closer at one part of it. Navigating spends
 * nothing — no call, no write, no heat, and not one millisecond of rule 7's
 * figure, which is the retrieval's own cost and never this panel's.
 *
 * Decisions worth keeping:
 *
 * 1. **The layout is Explore's, imported, never re-derived.** `seed` and
 *    `step` come from `graph.jsx`. The same forest must open the same way
 *    in both consoles, or a person describing a cluster in one is not
 *    describing it in the other.
 * 2. **Nothing here is narrated.** Every stage is read off material the
 *    host actually returned: `found_by` says which retriever reached a node
 *    (C.6c), `content` says what was handed to the model. A stage with
 *    nothing in it stays dim — it is not a promise that something is coming.
 * 2b. **`cited` is a walk's stage and not a sweep's.** On a walk the reply
 *    names its own `answer_nodes` and the host keeps only those it actually
 *    opened (J.10.5) — a real choice, worth its own ring. On a sweep
 *    `evidence` is every id in the bundle, because the reply is prose and
 *    names nothing; drawing that as "cited" would show a selection that
 *    never happened. So the caller passes `cited` only when there was one,
 *    and the stage simply does not exist otherwise.
 * 3. **Slow is stated, never implied.** Retrieval is milliseconds and this
 *    animation is seconds, so the panel prints the real figure off the
 *    trace beside it. An animation that quietly ran at the speed of the
 *    thing it depicts would be a lie in the one console whose whole promise
 *    is that the answer is checkable.
 * 4. **The trail is amber and a shortcut is not.** `--graph-trail` is its
 *    own token: a `discovered-shortcut` is a fact the forest holds, a trail
 *    is what one question did to it, and two facts must not share a colour.
 * 5. **The trunk lights once.** Ancestors are shared, so segments are
 *    deduplicated and each lights at the EARLIEST stage that needed it —
 *    drawing a shared trunk once per hit would make the root the brightest
 *    thing on a map about somewhere else.
 * 6. **Structure comes from `parent`,** which the Station already filtered
 *    to what this principal may see (J.11): a chain that leaves the scope
 *    simply stops, and never draws a line to something the caller cannot
 *    read.
 * 7. **The reveal waits where the call waits.** It advances toward the
 *    number of stages that have data, so the sweep's three land together in
 *    milliseconds and `cited` lands when the model is finally done — the
 *    pause in the middle is the model writing, not a scripted beat.
 * 8. **The background is dots, and the trail is the only line** (J.5.15
 *    rule 9, v0.67). The edge set is still read and still pulls: paint and
 *    physics are separate concerns, and Explore has always shipped exactly
 *    this split — its hidden proposals pull as springs while no line is
 *    drawn for them — so the clusters, the hubs and the branch discs are
 *    where they were. What used to be painted here was every edge J.11
 *    returns, the `confidence < 1` class included and at twice the opacity
 *    of structure, so the answer's trail lay under a mat of proposals
 *    nobody had asked to see.
 * 9. **The dots carry the one fact this panel is about: where.** They are
 *    coloured by home branch — a fact the forest holds — with Explore's own
 *    palette and the operator's own stored grouping depth, because two
 *    consoles that group one forest two ways teach a person that the
 *    branches moved. They stay dim: the trail and its stages are the
 *    subject, and the map is the room it happened in. And whichever fact a
 *    colour encodes, the legend names it (J.5.4).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { useTheme } from '../theme.jsx'
import { Card, ErrorNote, Skeleton } from '../design/ui.jsx'
import { Graph as GraphIcon, Play } from '../design/icons.jsx'
import { hrefFor, navigate } from '../router.js'
import {
  STAGES, boxOf, hopSegments, markNodes, reachedStages, shortName, stageCounts,
  stagesFor, trailSegments,
} from '../trailmap.js'
import { groupOf, groupPalette, seed, step } from './graph.jsx'
import { useAsync } from './shared.jsx'

const STAGE_MS = 620      // one stage's share of the reveal
const FORCE = { repel: 1, distance: 1.15, attract: 1, center: 1 }
const PAD = 34            // camera margin, in css pixels
const LABEL_LIMIT = 22    // past this a caption per hit whites out the map
// The walking dashes: short mark, longer gap, so the eye reads footsteps
// rather than a dotted rule. `MARCH_PX_PER_S` is deliberately slow — this
// panel sits beside a real millisecond figure (J.5.15) and an animation
// that hurries makes the retrieval look like the thing taking the time.
const TRAIL_DASH = [3, 6]
const MARCH_PX_PER_S = 26
const TAU = Math.PI * 2
const ZOOM_STEP = 1.15    // one mouse notch
const ZOOM_MIN = 0.5      // times the fitted scale — never an absolute one:
const ZOOM_MAX = 8        // "fitted" is a different number per forest
const GROUP_DEPTH = 3     // Explore's own default, when a forest has no view

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v)

/** How deep a branch group runs, as the operator's own Explore is showing
 *  this forest (J.5.4 v0.38 keeps that per forest, in the browser, never in
 *  the address and never a call). Read, never written: the panel takes the
 *  grouping and gives none back.
 *
 *  `colorBy` — Explore's switch between branch and type — is deliberately
 *  not taken. J.5.15 rule 9 fixes what THIS panel's colour encodes, the home
 *  branch, because the question it answers is *where*; the legend names that
 *  fact whichever way Explore happens to be set. The depth is the part that
 *  must agree, or the same forest is grouped two ways by two consoles.
 *
 *  The fallback is Explore's `DEFAULTS.groupDepth`, restated rather than
 *  imported: this panel honours two fields of a presentation preset that is
 *  Explore's own, and importing the whole preset would tie a console's taste
 *  to another console's. */
function readGroupDepth(forest) {
  try {
    const raw = JSON.parse(localStorage.getItem(`monkeyllm.graph.${forest}`) || '{}')
    const depth = Math.floor(Number(raw.groupDepth))
    return depth >= 1 && depth <= 8 ? depth : GROUP_DEPTH
  } catch { return GROUP_DEPTH }
}

/** Colours live in the stylesheet with every other colour, so the map
 *  repaints with the theme. Read once per theme change, never per frame.
 *  Each stage names its own token in `trailmap.js`, so a stage added there
 *  arrives here with a colour and no edit. */
function readPalette() {
  const css = getComputedStyle(document.documentElement)
  const channel = (name, fallback) => {
    const raw = css.getPropertyValue(`--${name}`).trim()
    return raw ? `rgb(${raw.split(/\s+/).join(' ')})` : fallback
  }
  const out = { stage: {} }
  for (const s of STAGES) out.stage[s.key] = channel(s.token, 'rgb(120 132 124)')
  // `dot` is the root group's colour and the colour of every dot until the
  // branch palette is computed — the absence of a branch, not one more
  // branch (the rule Explore's own `pal.other` follows). No edge token is
  // read any more: nothing here draws one.
  out.dot = channel('text-3', 'rgb(120 132 124)')
  out.trail = channel('graph-trail', 'rgb(202 146 18)')
  out.drop = channel('graph-drop', 'rgb(38 150 190)')
  out.label = channel('text-2', 'rgb(90 100 92)')
  return out
}

export default function AnswerTrail({ forest, evidence, cited, trace, busy,
                                      hops, live = false }) {
  const { t } = useI18n()
  const { resolved } = useTheme()
  const box = useRef(null)
  const canvas = useRef(null)
  const sim = useRef({ nodes: [], springs: [], links: [], index: {},
                       alpha: 0, alphaTarget: 0, active: false, rand: Math.random })
  // `fitK` is the scale the camera would choose on its own — the zoom clamp
  // is relative to it, because "fitted" is a different number per forest.
  // `manual` is a hand on the view: from the first wheel or drag the camera
  // stops framing itself, until a double click or a new forest (rule 10).
  const cam = useRef({ x: 0, y: 0, k: 1, fitK: 1, manual: false })
  const anim = useRef({ pos: 0 })
  const needsDraw = useRef(true)
  // The colouring, held where `build()` can reach it (see the effect below).
  const colourRuns = useRef(null)
  const [hover, setHover] = useState(null)
  const [replays, setReplays] = useState(0)

  const calm = typeof matchMedia === 'function'
    && matchMedia('(prefers-reduced-motion: reduce)').matches

  // One cheap read on the reader pool (J.6.2), and it is the same
  // projection Explore takes — a forest open in both consoles pays for the
  // map twice and for nothing else.
  const map = useAsync(() => api.map(forest, 'graph'), [forest])

  const marks = useMemo(() => markNodes(evidence, cited), [evidence, cited])
  const byId = useMemo(() => {
    const out = new Map()
    for (const n of map.data?.nodes || []) out.set(n.id, n)
    return out
  }, [map.data])
  const trail = useMemo(() => trailSegments(marks, byId), [marks, byId])
  // The walk's own line (J.5.15): where the agent STOOD, in the order it
  // stood there. Empty on a sweep, which is the honest answer — a sweep
  // does not move, and the amber line above is its address, not its route.
  const route = useMemo(() => hopSegments(hops, byId), [hops, byId])

  // Which stages this run can have, what they hold, and how far the reveal
  // may run — all three decided in `trailmap.js`, where F.137 can ask.
  const applicable = stagesFor(cited)
  const counts = useMemo(() => stageCounts(marks), [marks])
  const available = useMemo(() => reachedStages(marks), [marks])

  const palette = useMemo(() => readPalette(), [resolved])

  /* The branch hues, Explore's formula over Explore's own sorted key list
     (J.5.15 rule 9): the same forest must arrive in the same colours in both
     consoles, so the palette is imported and the grouping is the operator's.
     Computed once per forest, theme or depth — never per frame. */
  const groupDepth = useMemo(() => readGroupDepth(forest), [forest])
  const groupColors = useMemo(() => {
    const keys = new Set()
    for (const n of map.data?.nodes || []) keys.add(groupOf(n.id, groupDepth))
    return groupPalette([...keys].sort(), resolved === 'dark')
  }, [map.data, groupDepth, resolved])

  /* Three real branch hues for the legend. The row names what the colour
     encodes (J.5.4), and it names it in the colours actually on the map. */
  const swatch = useMemo(() => {
    const out = []
    for (const key of Object.keys(groupColors)) {
      if (groupColors[key] && out.length < 3) out.push(groupColors[key])
    }
    return out
  }, [groupColors])

  const paletteRef = useRef(palette)
  const trailRef = useRef(trail)
  const routeRef = useRef(route)
  const marksRef = useRef(marks)
  useEffect(() => { paletteRef.current = palette; needsDraw.current = true }, [palette])
  useEffect(() => { trailRef.current = trail; needsDraw.current = true }, [trail])
  useEffect(() => { routeRef.current = route; needsDraw.current = true }, [route])
  useEffect(() => { marksRef.current = marks; needsDraw.current = true }, [marks])

  /* -- camera ------------------------------------------------------------- */

  /* The camera starts on the whole forest and leans toward what the answer
     touched as the trail spreads — halfway, never all the way: a map about
     three nodes that shows only those three is no longer a map of a forest,
     which is the thing being demonstrated. */
  const fit = useCallback((ease = 1) => {
    const el = canvas.current
    const s = sim.current
    // A hand on the view owns it: the camera stops reframing under somebody
    // who is looking at one corner of the map (rule 10). `manual` is cleared
    // by the reset gesture and by a new forest, and by nothing else.
    if (!el || !s.nodes.length || cam.current.manual) return
    const whole = boxOf(s.nodes)
    if (!whole) return
    // Only what has been REVEALED so far (v0.71). Framing the final set
    // from the first frame makes the camera answer a question the viewer
    // has not been asked yet: everything is already in shot, so nothing
    // that follows is a discovery. Leaning on the growing set instead makes
    // the view travel — it tightens as the answer narrows, which is the
    // thing being watched.
    const at = anim.current.pos
    const touched = []
    for (const [id, stages] of marksRef.current) {
      if (Math.min(...stages) > at) continue
      const n = s.nodes[s.index[id]]
      if (n) touched.push(n)
    }
    for (const seg of trailRef.current.segments) {
      if (seg.stage > at) continue
      for (const id of [seg.a, seg.b]) {
        const n = s.nodes[s.index[id]]
        if (n) touched.push(n)
      }
    }
    const near = touched.length >= 2 ? boxOf(touched) : null
    const LEAN = 0.5
    const mix = (a, b) => (near ? a + (b - a) * LEAN : a)
    const x0 = mix(whole.x0, near?.x0); const x1 = mix(whole.x1, near?.x1)
    const y0 = mix(whole.y0, near?.y0); const y1 = mix(whole.y1, near?.y1)

    const w = el.clientWidth || 1
    const h = el.clientHeight || 1
    const k = Math.min((w - PAD * 2) / Math.max(1, x1 - x0),
                       (h - PAD * 2) / Math.max(1, y1 - y0), 2.4)
    const v = cam.current
    // The TARGET scale, not the eased one: the zoom clamp is a multiple of
    // what the camera would choose, and a limit that moved while the camera
    // was still settling would be a different limit every frame.
    v.fitK = k
    v.k += (k - v.k) * ease
    v.x += ((w / 2 - ((x0 + x1) / 2) * k) - v.x) * ease
    v.y += ((h / 2 - ((y0 + y1) / 2) * k) - v.y) * ease
  }, [])

  /* -- the simulation ----------------------------------------------------- */

  const build = useCallback(() => {
    const el = canvas.current
    const data = map.data
    if (!el || !data) return
    const w = el.clientWidth || 720
    const h = el.clientHeight || 380
    const nodes = data.nodes.map((n) => ({
      id: n.id, parent: n.parent, degree: n.degree || 0, type: n.type,
      title: n.title, seedGroup: groupOf(n.id, 2),
      r0: 1.6 + Math.min(5, Math.sqrt(n.degree || 0) * 1.1),
      on: true, fx: null, fy: null, x: 0, y: 0, vx: 0, vy: 0,
    }))
    const index = Object.fromEntries(nodes.map((n, i) => [n.id, i]))
    const known = new Set(nodes.map((n) => n.id))
    const links = [
      ...data.nodes.filter((n) => n.parent && known.has(n.parent))
        .map((n) => ({ src: n.parent, dst: n.id, structure: true, confidence: 1 })),
      ...data.edges,
    ].filter((e) => index[e.src] != null && index[e.dst] != null)

    // Spring strength is Explore's, for the same reason the layout is: a
    // hub with three hundred leaves must keep its place in both maps.
    const degree = {}
    for (const e of links) {
      degree[e.src] = (degree[e.src] || 0) + 1
      degree[e.dst] = (degree[e.dst] || 0) + 1
    }
    const springs = links.map((e) => {
      const da = degree[e.src]
      const db = degree[e.dst]
      const kind = e.structure ? 1 : (e.confidence < 1 ? 0.35 : 0.7)
      const cross = nodes[index[e.src]].seedGroup !== nodes[index[e.dst]].seedGroup
      return { a: index[e.src], b: index[e.dst], bias: da / (da + db),
               strength: (kind / Math.min(da, db)) * (cross ? 0.12 : 1), on: true }
    })

    const s = { nodes, springs, links, index, alpha: 1, alphaTarget: 0,
                active: true, rand: Math.random }
    seed(s, w, h)
    sim.current = s
    // The colours belong to the simulation and this is a new one, so they are
    // put back here rather than left to an effect that watches a different set
    // of things. `calm` rebuilds and no colour input changes with it, so a
    // viewer who turns Reduce Motion on mid-session would otherwise be left
    // with a grey map under a legend still naming the branches.
    colourRuns.current?.(s)
    if (calm) {
      // Settled before the first paint: nobody asked to watch the layout
      // assemble here. The reveal is the animation; the map is the stage.
      for (let i = 0; i < 420 && s.active; i += 1) step(s, w, h, FORCE)
      s.active = false
    }
    // A new map is a new view: whatever the hand did to the last forest's
    // camera it did not do to this one.
    cam.current.manual = false
    fit(1)
    needsDraw.current = true
  }, [map.data, calm, fit])

  useEffect(() => { build() }, [build])

  /* The dots, grouped by colour once rather than styled one at a time: on a
     1200-node forest the fill state changes are what cost, not the arcs. A
     run is an array of indices into `s.nodes`, rebuilt when the layout, the
     theme or the grouping changes and never inside a frame. Runs live on the
     simulation because the draw reads it through a ref, like everything else
     it paints.

     Held in a ref as well as run here, because those are two different
     moments: this effect fires when a COLOUR input moves, and `build()`
     replaces the simulation wholesale when one of ITS inputs moves. Neither
     set contains the other, and a rebuilt simulation carries no colours until
     they are put back — which `build()` does with this same function, so the
     two cannot drift into a map that is grey under a legend about branches. */
  useEffect(() => {
    colourRuns.current = (s) => {
      if (!s.nodes.length) return
      const grey = palette.dot
      const runs = new Map()
      for (let i = 0; i < s.nodes.length; i += 1) {
        // The root group has no branch to name, so it stays grey — the rule
        // Explore follows for the same nodes.
        const color = groupColors[groupOf(s.nodes[i].id, groupDepth)] || grey
        const held = runs.get(color)
        if (held) held.push(i)
        else runs.set(color, [i])
      }
      s.runs = [...runs].map(([color, list]) => ({ color, list }))
      needsDraw.current = true
    }
    colourRuns.current(sim.current)
  }, [map.data, groupColors, groupDepth, palette])

  /* A new ask restarts the reveal — `busy` rising is the moment one left
     the browser — and so does the replay button and a change of forest.
     A LIVE walk is the exception: its hops arrive one at a time (J.10.12)
     and each one is a step forward, so the reveal advances with the hunt
     rather than replaying itself on every arrival. */
  useEffect(() => {
    if (!busy || live) return
    anim.current.pos = 0
    needsDraw.current = true
  }, [busy, live])
  useEffect(() => {
    anim.current.pos = 0
    needsDraw.current = true
  }, [replays, forest])

  /* -- painting ----------------------------------------------------------- */

  const draw = useCallback(() => {
    const el = canvas.current
    const s = sim.current
    if (!el || !s.nodes.length) return
    const dpr = window.devicePixelRatio || 1
    const w = el.clientWidth
    const h = el.clientHeight
    if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
      el.width = Math.round(w * dpr)
      el.height = Math.round(h * dpr)
    }
    const ctx = el.getContext('2d')
    const pal = paletteRef.current
    const v = cam.current
    const pos = anim.current.pos
    const march = anim.current.march || 0
    const { segments, deepest } = trailRef.current
    const marked = marksRef.current
    const X = (n) => n.x * v.k + v.x
    const Y = (n) => n.y * v.k + v.y
    const reveal = (stage) => clamp01(pos - stage)

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    ctx.lineCap = 'round'

    /* 1. The forest as context: dots, and not one edge (J.5.15 rule 9). The
          edge set is still read and still pulls — it is in `s.springs`, and
          the layout below is the layout it produces — but nothing is drawn
          for it: the panel's question is *where*, and the answer used to
          arrive under a mat of proposals nobody had asked to see.

          The colour is the home branch, dim, so the trail and its stages
          stay the foreground. One path per branch instead of one fill per
          dot; a dot outside the canvas is skipped, which is what makes a
          zoomed-in view cheaper than a fitted one rather than the same.
          Radius is screen space on purpose: zooming spreads a cluster
          apart instead of inflating it, which is the reason to zoom. */
    ctx.globalAlpha = 0.3
    const runs = s.runs
    if (runs) {
      for (const run of runs) {
        ctx.fillStyle = run.color
        ctx.beginPath()
        for (const i of run.list) {
          const n = s.nodes[i]
          if (marked.has(n.id)) continue
          const x = X(n)
          if (x < -6 || x > w + 6) continue
          const y = Y(n)
          if (y < -6 || y > h + 6) continue
          const r = n.r0 * 0.62
          ctx.moveTo(x + r, y)
          ctx.arc(x, y, r, 0, TAU)
        }
        ctx.fill()
      }
    } else {
      // One frame can land before the colouring effect does. Grey is the
      // honest answer there — it is what a node with no branch gets anyway.
      ctx.fillStyle = pal.dot
      ctx.beginPath()
      for (const n of s.nodes) {
        if (marked.has(n.id)) continue
        const x = X(n)
        const y = Y(n)
        const r = n.r0 * 0.62
        ctx.moveTo(x + r, y)
        ctx.arc(x, y, r, 0, TAU)
      }
      ctx.fill()
    }

    /* 2. The trail, crawling outward from the root. Each segment takes its
          own slice of its stage's reveal, ordered by depth, so the line
          travels through the forest instead of appearing on it. */
    /* 2a. The HELICOPTER (blue): base to the nearest BRANCH, and it stops
           there. The segment that would enter the document is not drawn
           here — that last step is the monkey's, below. Drawing the whole
           chain in one colour was the bug: it read as "flown straight onto
           the exact file", which is the claim the product does not make and
           the panel was making for it.

           Every leg advances TOGETHER, not staggered by depth: several hits
           are several drops leaving the base at once, and revealing them
           one after another invented an order the retrieval never had. */
    // The flight draws every ancestry segment the WALK does not — which is
    // the rule, and the earlier version was a special case of it that broke
    // the general one. On a sweep the walk is the last ancestry step, so
    // the flight yields it. On a walk the walk is the hop sequence, which
    // covers no ancestry at all: yielding those segments anyway left them
    // drawn by nobody, and the address vanished. The picture became hop
    // lines flying between distant branches with no forest under them.
    const hopping = routeRef.current.segments.length > 0
    const legOf = (seg) => (!hopping && marked.has(seg.b) ? 'walk' : 'fly')
    const flown = clamp01(pos / Math.max(1, STAGES.length - 1))
    ctx.lineWidth = 1.9
    ctx.setLineDash(TRAIL_DASH)
    ctx.strokeStyle = pal.drop
    ctx.lineDashOffset = -march
    for (const seg of segments) {
      if (legOf(seg) !== 'fly') continue
      if (reveal(seg.stage) <= 0) continue
      const a = s.nodes[s.index[seg.a]]
      const b = s.nodes[s.index[seg.b]]
      if (!a || !b) continue
      const ax = X(a); const ay = Y(a)
      ctx.globalAlpha = 0.30 + 0.5 * flown
      ctx.beginPath()
      ctx.moveTo(ax, ay)
      ctx.lineTo(ax + (X(b) - ax) * flown, ay + (Y(b) - ay) * flown)
      ctx.stroke()
    }

    /* 2b. The MONKEY (amber): its own movement, and the colour means that
           in BOTH modes — which is what lets one legend line describe it.

           On a sweep the movement is one step: the branch the drop reached,
           into the document that was opened. That is the last segment of
           each chain, the one 2a refused to draw.

           On a walk it is the real hop sequence instead — the agent moved
           for real, several times, and painting only its final step would
           throw away the one thing a walk has that a sweep does not. The
           amber never means "an address" in either case.

           It starts AFTER the flight so the eye reads the order — flown in,
           then stepped through — without the stages being staggered. */
    const legs = routeRef.current.segments
    const walked = clamp01((pos - 0.55) / Math.max(1, STAGES.length - 1))
    ctx.strokeStyle = pal.trail
    ctx.lineWidth = 2.2
    ctx.lineDashOffset = -march
    if (legs.length) {
      for (const leg of legs) {
        const a = s.nodes[s.index[leg.a]]
        const b = s.nodes[s.index[leg.b]]
        if (!a || !b || walked <= 0) continue
        const ax = X(a); const ay = Y(a)
        ctx.globalAlpha = 0.45 + 0.5 * walked
        ctx.beginPath()
        ctx.moveTo(ax, ay)
        ctx.lineTo(ax + (X(b) - ax) * walked, ay + (Y(b) - ay) * walked)
        ctx.stroke()
      }
    } else {
      for (const seg of segments) {
        if (legOf(seg) !== 'walk') continue
        if (reveal(seg.stage) <= 0 || walked <= 0) continue
        const a = s.nodes[s.index[seg.a]]
        const b = s.nodes[s.index[seg.b]]
        if (!a || !b) continue
        const ax = X(a); const ay = Y(a)
        ctx.globalAlpha = 0.45 + 0.5 * walked
        ctx.beginPath()
        ctx.moveTo(ax, ay)
        ctx.lineTo(ax + (X(b) - ax) * walked, ay + (Y(b) - ay) * walked)
        ctx.stroke()
      }
    }
    ctx.setLineDash([])
    ctx.lineDashOffset = 0

    /* 3. The hits, ringed from the inside out in stage order — so a node
          the model actually read is visibly more than one `locate` ranked,
          and a node that is all four is unmistakable. */
    for (const [id, stages] of marked) {
      const n = s.nodes[s.index[id]]
      if (!n) continue
      const ordered = [...stages].sort((p, q) => p - q)
      const at = reveal(ordered[0])
      if (at <= 0) continue
      const x = X(n); const y = Y(n)
      const base = (n.r0 + 1.6) * (0.6 + 0.4 * at)
      ctx.globalAlpha = 0.85 * at
      ctx.fillStyle = pal.stage[STAGES[ordered[0]].key]
      ctx.beginPath()
      ctx.arc(x, y, base, 0, Math.PI * 2)
      ctx.fill()
      let ring = base
      ctx.lineWidth = 1.5
      for (const stage of ordered) {
        const on = reveal(stage)
        if (on <= 0) continue
        ring += 3
        ctx.globalAlpha = 0.75 * on
        ctx.strokeStyle = pal.stage[STAGES[stage].key]
        ctx.beginPath()
        ctx.arc(x, y, ring * (0.7 + 0.3 * on), 0, Math.PI * 2)
        ctx.stroke()
      }
    }

    /* 4. Names — for every node the trail TOUCHES, not only the ones it
          stopped at. A route whose waypoints are anonymous is a shape, and
          the question this panel answers is *where the answer went*: the
          branch it climbed through is half of that answer. Nodes the walk
          only passed through are written dimmer and smaller, so the reading
          order stays hit-first; they are captions on the way, not results.

          `marked` still decides whether captions are drawn at all, because
          it is the count that says how busy the answer was — a sweep with
          forty hits is unreadable with or without the ancestors. */
    const passed = new Map()   // id -> stage it lights at (through-nodes only)
    for (const seg of segments) {
      for (const id of [seg.a, seg.b]) {
        if (marked.has(id)) continue
        const held = passed.get(id)
        if (held === undefined || seg.stage < held) passed.set(id, seg.stage)
      }
    }
    if (marked.size <= LABEL_LIMIT) {
      ctx.font = '500 10.5px ui-monospace, SFMono-Regular, Menlo, monospace'
      ctx.textAlign = 'center'
      ctx.fillStyle = pal.label
      // Siblings land on top of each other — they are siblings — so a
      // caption that simply sat above its node would bury the one beside
      // it. Each is lifted until it clears what is already written; two
      // unreadable names are worse than one name higher than it should be.
      const placed = []
      for (const [id, stages] of marked) {
        const n = s.nodes[s.index[id]]
        // The obstacle is the node WITH its rings: a caption clearing the
        // dot but not the rings around it is still a caption on a node.
        if (n) placed.push({ x: X(n), y: Y(n), half: n.r0 + 8 + 3 * stages.size })
      }
      for (const id of passed.keys()) {
        const n = s.nodes[s.index[id]]
        if (n) placed.push({ x: X(n), y: Y(n), half: n.r0 + 8 })
      }
      // Hits first: they claim their space before the way-through captions
      // compete for it, so a crowded map loses an ancestor's name and never
      // a result's.
      const rows = [
        ...[...marked].map(([id, stages]) => ({ id, at: Math.min(...stages), hit: true })),
        ...[...passed].map(([id, stage]) => ({ id, at: stage, hit: false })),
      ]
      for (const { id, at: stageOf, hit } of rows) {
        const n = s.nodes[s.index[id]]
        if (!n) continue
        const at = reveal(stageOf)
        if (at <= 0.25) continue
        ctx.font = hit
          ? '500 10.5px ui-monospace, SFMono-Regular, Menlo, monospace'
          : '500 9.5px ui-monospace, SFMono-Regular, Menlo, monospace'
        const label = shortName(id).slice(0, 26)
        const half = ctx.measureText(label).width / 2 + 5
        const x = X(n)
        const free = (cy) => cy >= 12 && cy <= h - 6 && !placed.some(
          (q) => Math.abs(q.y - cy) < 13 && Math.abs(q.x - x) < q.half + half)
        // Above first, then below — a caption pushed past the top edge is a
        // caption nobody reads, which is worse than one on the wrong side
        // of its own node.
        let y = null
        for (let lift = 0; lift < 10 && y === null; lift += 1) {
          const up = Y(n) - (n.r0 + 12) - lift * 13
          const down = Y(n) + n.r0 + 20 + lift * 13
          if (free(up)) y = up
          else if (free(down)) y = down
        }
        if (y === null) continue
        placed.push({ x, y, half })
        ctx.globalAlpha = hit ? at : at * 0.55
        ctx.fillText(label, x, y)
      }
      ctx.textAlign = 'start'
    }
    ctx.globalAlpha = 1
  }, [])

  const drawRef = useRef(draw)
  useEffect(() => { drawRef.current = draw }, [draw])

  /* -- the loop ----------------------------------------------------------- */

  useEffect(() => {
    if (calm) {
      // No loop under reduced motion: the reveal is already at its end and
      // the panel paints when something changed.
      anim.current.pos = available
      drawRef.current()
      return undefined
    }
    let running = true
    let previous = 0
    const tick = (now) => {
      if (!running) return
      const el = canvas.current
      const s = sim.current
      const dt = previous ? Math.min(64, now - previous) : 16
      previous = now
      if (el && s.nodes.length) {
        if (s.active) {
          step(s, el.clientWidth, el.clientHeight, FORCE)
          fit(0.09)
          needsDraw.current = true
        }
        if (anim.current.pos < available) {
          anim.current.pos = Math.min(available, anim.current.pos + dt / STAGE_MS)
          // Re-frame as it goes, gently: the set the camera leans on grows
          // stage by stage, so a fixed frame would be a still picture of a
          // reveal. Eased hard (0.05) because a camera that snaps to each
          // new node is a camera nobody can read.
          fit(0.05)
          needsDraw.current = true
        }
        // The dashes keep walking after the reveal has finished, so the
        // panel stays a route being travelled instead of freezing into a
        // diagram. Only while there IS a trail: an empty panel that repaints
        // forever is a battery bug, not an animation.
        if (trailRef.current.segments.length && anim.current.pos > 0) {
          anim.current.march = (anim.current.march || 0)
            + (dt / 1000) * MARCH_PX_PER_S
          needsDraw.current = true
        }
      }
      if (needsDraw.current) {
        needsDraw.current = false
        drawRef.current()
      }
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
    return () => { running = false }
  }, [calm, fit, available])

  useEffect(() => {
    const el = box.current
    if (!el || typeof ResizeObserver !== 'function') return undefined
    const ro = new ResizeObserver(() => {
      const s = sim.current
      s.active = true
      s.alpha = Math.max(s.alpha, 0.25)
      needsDraw.current = true
      if (calm) { fit(1); drawRef.current() }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [calm, fit])

  /* -- the hand on the view (J.5.15 rule 10) ------------------------------- */

  /* Zoom about a point, so the pixel under the cursor stays under it. A
     world point sits at `p·k + v`; asking that it still sit there at `k' =
     k·f` gives `v' = p_screen − (p_screen − v)·(k'/k)`, which is the whole
     of it — the same line Explore's wheel uses, on a scale clamped to a
     multiple of the fitted one rather than to an absolute number that would
     mean something different per forest.

     It spends nothing: no call, no write, no heat, and no touch to the
     millisecond figure below the canvas (rule 10, rule 7). */
  const zoomAt = useCallback((px, py, factor) => {
    const v = cam.current
    const base = v.fitK || v.k || 1
    const k = Math.max(base * ZOOM_MIN, Math.min(base * ZOOM_MAX, v.k * factor))
    v.manual = true
    if (k !== v.k) {
      v.x = px - (px - v.x) * (k / v.k)
      v.y = py - (py - v.y) * (k / v.k)
      v.k = k
    }
    needsDraw.current = true
    if (calm) drawRef.current()
  }, [calm])

  /* Back to the framed view. The fit is recomputed rather than remembered,
     because the forest may have settled — or the answer moved — since. */
  const resetView = useCallback(() => {
    cam.current.manual = false
    fit(1)
    needsDraw.current = true
    if (calm) drawRef.current()
  }, [calm, fit])

  /* Wheel must be non-passive to preventDefault, which React's onWheel is
     not — so it is bound by hand, and re-bound when the canvas appears (it
     is behind the map's skeleton until the projection lands). */
  useEffect(() => {
    const el = canvas.current
    if (!el) return undefined
    const onWheel = (event) => {
      event.preventDefault()
      const rect = el.getBoundingClientRect()
      // A trackpad pinch arrives as a wheel with `ctrlKey` and a continuous
      // delta; a mouse notch is one fixed step. Read the same way, a pinch
      // is either inert or violent.
      const factor = event.ctrlKey
        ? Math.exp(-event.deltaY / 120)
        : (event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP)
      zoomAt(event.clientX - rect.left, event.clientY - rect.top, factor)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt, map.busy, map.error])

  /* -- pointing ----------------------------------------------------------- */

  const pointers = useRef(new Map())
  const pinch = useRef(null)
  const pan = useRef(null)
  // Where the gesture began, so a drag that ends on a node is not a click.
  const gesture = useRef({ x: 0, y: 0, moved: false })

  const onPointerDown = (event) => {
    const el = canvas.current
    if (!el) return
    try { el.setPointerCapture(event.pointerId) } catch { /* gone already */ }
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
    if (pointers.current.size === 2) {
      // A second finger turns any gesture into a pinch — never a pan, and
      // never a click however still it ends.
      const [a, b] = [...pointers.current.values()]
      pinch.current = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1,
                        mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 }
      pan.current = null
      gesture.current.moved = true
      return
    }
    pan.current = { x: event.clientX, y: event.clientY }
    gesture.current = { x: event.clientX, y: event.clientY, moved: false }
  }

  const onPointerMove = (event) => {
    const el = canvas.current
    const s = sim.current
    if (!el || !s.nodes.length) return
    if (pointers.current.has(event.pointerId)) {
      pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
    }
    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1
      const mx = (a.x + b.x) / 2
      const my = (a.y + b.y) / 2
      const rect = el.getBoundingClientRect()
      // Two fingers that also travelled asked to pan while they zoomed, and
      // the pan is applied first so the zoom is about where they now are.
      const factor = d / pinch.current.d
      const v = cam.current
      v.x += mx - pinch.current.mx
      v.y += my - pinch.current.my
      pinch.current = { d, mx, my }
      zoomAt(mx - rect.left, my - rect.top, factor)
      return
    }
    if (pan.current) {
      const dx = event.clientX - pan.current.x
      const dy = event.clientY - pan.current.y
      if (dx || dy) {
        const v = cam.current
        v.x += dx
        v.y += dy
        v.manual = true
        pan.current = { x: event.clientX, y: event.clientY }
        if (!gesture.current.moved
            && (Math.abs(event.clientX - gesture.current.x) > 4
                || Math.abs(event.clientY - gesture.current.y) > 4)) {
          gesture.current.moved = true
          // The card names the node under the pointer, and once the map is
          // moving under it that is no longer the node it names.
          if (hover) setHover(null)
        }
        needsDraw.current = true
        if (calm) drawRef.current()
      }
      return
    }
    const rect = el.getBoundingClientRect()
    const px = event.clientX - rect.left
    const py = event.clientY - rect.top
    const v = cam.current
    let best = null
    let bestD = 18 * 18
    for (const id of marksRef.current.keys()) {
      const n = s.nodes[s.index[id]]
      if (!n) continue
      const dx = n.x * v.k + v.x - px
      const dy = n.y * v.k + v.y - py
      const d = dx * dx + dy * dy
      if (d < bestD) { bestD = d; best = { id, x: px, y: py } }
    }
    setHover(best)
  }

  const onPointerUp = (event) => {
    pointers.current.delete(event.pointerId)
    if (pointers.current.size < 2) pinch.current = null
    pan.current = null
  }

  /* -- the panel ---------------------------------------------------------- */

  if (map.error) {
    return (
      <Card title={t('ask.trail')} icon={GraphIcon}>
        <ErrorNote error={map.error} onRetry={map.reload} />
      </Card>
    )
  }

  const hovered = hover && byId.get(hover.id)

  return (
    <Card title={t('ask.trail')} subtitle={t('ask.trail_sub')} icon={GraphIcon}
          actions={available > 0 && !calm && (
            <button type="button" className="btn btn-sm"
                    onClick={() => setReplays((n) => n + 1)}>
              <Play size={13} /> {t('ask.trail_replay')}
            </button>
          )}>
      {map.busy ? <Skeleton rows={4} /> : (
        <>
          {/* Taller than a banner on purpose: a forest lays out roughly
              square, and a wide short box spends its width on sky. */}
          {/* The canvas carries the click, not the card. A card is written
              where the pointer is and the pointer must keep moving to reach
              it — by which time it is no longer over the node that produced
              it, so a card that had to be clicked could never be. The node
              under the pointer is the target instead, and the card is what
              says which node that is. */}
          <div ref={box} className="relative h-[360px] w-full overflow-hidden rounded-lg
                                    border border-line bg-bg sm:h-[500px]">
            {/* `touch-none` because the panel takes the gesture: without it
                a two-finger pinch zooms the page and a drag scrolls it, and
                the map underneath never hears either. A drag that travelled
                is a pan and not a click, or reaching a corner of the forest
                would keep opening whatever was under the finger. */}
            <canvas ref={canvas}
                    className={`h-full w-full touch-none
                                ${hover ? 'cursor-pointer' : 'cursor-grab'}`}
                    onPointerDown={onPointerDown} onPointerMove={onPointerMove}
                    onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
                    onPointerLeave={() => setHover(null)}
                    onDoubleClick={resetView}
                    onClick={() => !gesture.current.moved && hover && navigate(
                      hrefFor(forest, 'explore', { node: hover.id }))} />
            {hovered && (
              /* Above the pointer, unless there is no room above — the box
                 clips, so a card that always sat on top would be cut in
                 half for every hit near the canopy. */
              <div className={`pointer-events-none absolute z-10 max-w-[70%]
                               -translate-x-1/2 rounded-lg border border-line
                               bg-surface px-2.5 py-1.5 shadow-pop
                               ${hover.y < 76 ? 'translate-y-4'
                                 : '-translate-y-[calc(100%+14px)]'}`}
                   style={{ left: hover.x, top: hover.y }}>
                <span className="block font-mono text-[11px] text-accent">{hovered.id}</span>
                {hovered.title && (
                  <span className="mt-0.5 block text-[11.5px] text-text-2">{hovered.title}</span>
                )}
              </div>
            )}
            {available === 0 && (
              <div className="pointer-events-none absolute inset-x-0 bottom-3 text-center
                              text-[11.5px] text-text-3">
                {t(busy ? 'ask.trail_waiting' : 'ask.trail_empty')}
              </div>
            )}
          </div>

          {/* The stages with the counts they actually carry. A stage holding
              nothing stays dim whether or not the reveal has passed it. */}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            {applicable.map((stage, i) => (
              <span key={stage.key}
                    className={`flex items-baseline gap-1.5 text-[11.5px] transition
                                ${counts[i] > 0 ? 'text-text-2' : 'text-text-3 opacity-45'}`}>
                <span className="h-2 w-2 shrink-0 translate-y-[1px] rounded-full"
                      style={{ background: palette.stage[stage.key] }} />
                {t(`ask.trail_stage_${stage.key}`)}
                <span className="font-mono tabular-nums">{counts[i]}</span>
              </span>
            ))}
            {/* The two lines, named. Without this the reader has to guess
                which colour is a claim about the forest's shape and which
                is a claim about what happened, and the amber one is the
                easier of the two to misread. */}
            <span className="flex items-baseline gap-1.5 text-[11.5px] text-text-2">
              <span className="h-0 w-4 shrink-0 translate-y-[-2px] border-t-2 border-dashed"
                    style={{ borderColor: palette.drop }} />
              {t('ask.trail_line_drop')}
            </span>
            <span className="flex items-baseline gap-1.5 text-[11.5px] text-text-2">
              <span className="h-0 w-4 shrink-0 translate-y-[-2px] border-t-2 border-dashed"
                    style={{ borderColor: palette.trail }} />
              {t(route.segments.length ? 'ask.trail_line_walk' : 'ask.trail_line_step')}
              {route.segments.length > 0 && (
                <span className="font-mono tabular-nums">{route.stops.length}</span>
              )}
            </span>
            {trace?.retrieval_ms != null && (
              <span className="ml-auto font-mono text-[11px] tabular-nums text-text-3">
                {t('ask.trail_real', { ms: trace.retrieval_ms })}
              </span>
            )}
          </div>

          {/* Whichever fact a colour encodes, the legend names it (J.5.4):
              the rings above are the stages, and the dots behind them are
              the branches the forest already had. The gesture rides the same
              line because nothing on a canvas says it can be moved. */}
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1
                          text-[11px] text-text-3">
            <span className="flex items-center gap-1.5">
              {swatch.length > 0 && (
                <span className="flex gap-[3px]" aria-hidden="true">
                  {swatch.map((color, i) => (
                    // Keyed by position: two branches CAN land on one hue
                    // once the golden angle wraps, and a duplicate key is a
                    // warning about a swatch that is merely decorative.
                    // eslint-disable-next-line react/no-array-index-key
                    <span key={i} className="h-2 w-2 rounded-full"
                          style={{ background: color, opacity: 0.75 }} />
                  ))}
                </span>
              )}
              {t('ask.trail_colour')}
            </span>
            <span className="opacity-70">{t('ask.trail_view_hint')}</span>
          </div>
        </>
      )}
    </Card>
  )
}
