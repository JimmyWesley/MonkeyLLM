// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The path one answer took, drawn on the forest (spec J.5.4 + J.10.4).
 *
 * Explore's graph answers "what is in here". This answers a different
 * question — "what did THIS question do to it" — and that is why it is a
 * second view rather than a mode of the first: no filters, no settings, no
 * pan, nothing to tune. One question, one path, and the map is the caption.
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
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { useTheme } from '../theme.jsx'
import { Card, ErrorNote, Skeleton } from '../design/ui.jsx'
import { Graph as GraphIcon, Play } from '../design/icons.jsx'
import { hrefFor, navigate } from '../router.js'
import {
  STAGES, boxOf, markNodes, reachedStages, shortName, stageCounts,
  stagesFor, trailSegments,
} from '../trailmap.js'
import { groupOf, seed, step } from './graph.jsx'
import { useAsync } from './shared.jsx'

const STAGE_MS = 620      // one stage's share of the reveal
const FORCE = { repel: 1, distance: 1.15, attract: 1, center: 1 }
const PAD = 34            // camera margin, in css pixels
const LABEL_LIMIT = 22    // past this a caption per hit whites out the map

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v)

export default function AnswerTrail({ forest, evidence, cited, trace, busy }) {
  const { t } = useI18n()
  const { resolved } = useTheme()
  const box = useRef(null)
  const canvas = useRef(null)
  const sim = useRef({ nodes: [], springs: [], links: [], index: {},
                       alpha: 0, alphaTarget: 0, active: false, rand: Math.random })
  const cam = useRef({ x: 0, y: 0, k: 1 })
  const anim = useRef({ pos: 0 })
  const needsDraw = useRef(true)
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

  // Which stages this run can have, what they hold, and how far the reveal
  // may run — all three decided in `trailmap.js`, where F.137 can ask.
  const applicable = stagesFor(cited)
  const counts = useMemo(() => stageCounts(marks), [marks])
  const available = useMemo(() => reachedStages(marks), [marks])

  const palette = useMemo(() => readPalette(), [resolved])

  const paletteRef = useRef(palette)
  const trailRef = useRef(trail)
  const marksRef = useRef(marks)
  useEffect(() => { paletteRef.current = palette; needsDraw.current = true }, [palette])
  useEffect(() => { trailRef.current = trail; needsDraw.current = true }, [trail])
  useEffect(() => { marksRef.current = marks; needsDraw.current = true }, [marks])

  /* -- camera ------------------------------------------------------------- */

  /* The camera starts on the whole forest and leans toward what the answer
     touched as the trail spreads — halfway, never all the way: a map about
     three nodes that shows only those three is no longer a map of a forest,
     which is the thing being demonstrated. */
  const fit = useCallback((ease = 1) => {
    const el = canvas.current
    const s = sim.current
    if (!el || !s.nodes.length) return
    const whole = boxOf(s.nodes)
    if (!whole) return
    const touched = []
    for (const id of marksRef.current.keys()) {
      const n = s.nodes[s.index[id]]
      if (n) touched.push(n)
    }
    for (const seg of trailRef.current.segments) {
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
    if (calm) {
      // Settled before the first paint: nobody asked to watch the layout
      // assemble here. The reveal is the animation; the map is the stage.
      for (let i = 0; i < 420 && s.active; i += 1) step(s, w, h, FORCE)
      s.active = false
    }
    fit(1)
    needsDraw.current = true
  }, [map.data, calm, fit])

  useEffect(() => { build() }, [build])

  /* A new ask restarts the reveal — `busy` rising is the moment one left
     the browser — and so does the replay button and a change of forest. */
  useEffect(() => {
    if (!busy) return
    anim.current.pos = 0
    needsDraw.current = true
  }, [busy])
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
    const { segments, deepest } = trailRef.current
    const marked = marksRef.current
    const X = (n) => n.x * v.k + v.x
    const Y = (n) => n.y * v.k + v.y
    const reveal = (stage) => clamp01(pos - stage)

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    ctx.lineCap = 'round'

    /* 1. The forest as context. Two passes rather than a style per edge:
          the state changes are what cost, not the lines. A proposal is
          `confidence < 1` and is dashed here for the reason it is dashed in
          Explore — it is a proposal, never an assertion. */
    ctx.lineWidth = 1
    for (const pass of [false, true]) {
      ctx.globalAlpha = pass ? 0.22 : 0.11
      ctx.strokeStyle = pass ? pal.proposal : pal.edge
      ctx.setLineDash(pass ? [3, 4] : [])
      ctx.beginPath()
      for (const e of s.links) {
        if ((!e.structure && e.confidence < 1) !== pass) continue
        const a = s.nodes[s.index[e.src]]
        const b = s.nodes[s.index[e.dst]]
        ctx.moveTo(X(a), Y(a))
        ctx.lineTo(X(b), Y(b))
      }
      ctx.stroke()
    }
    ctx.setLineDash([])

    ctx.globalAlpha = 0.3
    ctx.fillStyle = pal.dot
    for (const n of s.nodes) {
      if (marked.has(n.id)) continue
      ctx.beginPath()
      ctx.arc(X(n), Y(n), n.r0 * 0.62, 0, Math.PI * 2)
      ctx.fill()
    }

    /* 2. The trail, crawling outward from the root. Each segment takes its
          own slice of its stage's reveal, ordered by depth, so the line
          travels through the forest instead of appearing on it. */
    ctx.lineWidth = 1.9
    ctx.strokeStyle = pal.trail
    for (const seg of segments) {
      const stageAt = reveal(seg.stage)
      if (stageAt <= 0) continue
      const local = clamp01(stageAt * (deepest + 1) - seg.depth)
      if (local <= 0) continue
      const a = s.nodes[s.index[seg.a]]
      const b = s.nodes[s.index[seg.b]]
      if (!a || !b) continue
      const ax = X(a); const ay = Y(a)
      ctx.globalAlpha = 0.34 + 0.5 * local
      ctx.beginPath()
      ctx.moveTo(ax, ay)
      ctx.lineTo(ax + (X(b) - ax) * local, ay + (Y(b) - ay) * local)
      ctx.stroke()
    }

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

    /* 4. Names, but only while the result is small enough to read them. */
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
      const rows = [...marked].map(([id, stages]) => ({ id, stages }))
        .sort((a, b) => {
          const na = s.nodes[s.index[a.id]]
          const nb = s.nodes[s.index[b.id]]
          return (na ? na.y : 0) - (nb ? nb.y : 0)
        })
      for (const { id, stages } of rows) {
        const n = s.nodes[s.index[id]]
        if (!n) continue
        const at = reveal(Math.min(...stages))
        if (at <= 0.25) continue
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
        ctx.globalAlpha = at
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

  /* -- pointing ----------------------------------------------------------- */

  const onMove = (event) => {
    const el = canvas.current
    const s = sim.current
    if (!el || !s.nodes.length) return
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
            <canvas ref={canvas}
                    className={`h-full w-full ${hover ? 'cursor-pointer' : ''}`}
                    onMouseMove={onMove} onMouseLeave={() => setHover(null)}
                    onClick={() => hover && navigate(
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
            {trace?.retrieval_ms != null && (
              <span className="ml-auto font-mono text-[11px] tabular-nums text-text-3">
                {t('ask.trail_real', { ms: trace.retrieval_ms })}
              </span>
            )}
          </div>
        </>
      )}
    </Card>
  )
}
