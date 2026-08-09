// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The graph mode of Explore (spec J.5.4).
 *
 * A forest is a graph with heat on it, and every list-shaped console so far
 * has had to describe that by reading out names. This draws it.
 *
 * Three decisions worth keeping:
 *
 * 1. **Canvas, and the simulation is written here.** A force layout is ~60
 *    lines of physics; a graph library is a megabyte and an opinion about
 *    how nodes should look. At the fixture's 82 nodes and a wide forest's
 *    few thousand, the naive O(n²) repulsion runs comfortably inside a
 *    frame, and the cost of the dependency would be paid on every load.
 * 2. **Every channel carries a fact the forest holds** (J.5.4): colour is
 *    the node's type, taken from the dialect the projection sent rather
 *    than a list compiled in here; radius is degree recomputed by the
 *    Station over what this principal may see; the glow is pheromone; a
 *    dashed edge is a proposal (`confidence < 1`) and never an assertion.
 * 3. **The layout means nothing.** It is presentation, so it animates —
 *    and a reduced-motion preference settles it immediately instead.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../i18n.jsx'
import { useTheme } from '../theme.jsx'
import { Empty, Skeleton, ErrorNote } from '../design/ui.jsx'
import { Graph as GraphIcon, Refresh } from '../design/icons.jsx'

const KNOWN_TYPES = ['branch', 'note', 'document', 'dataset', 'entity',
                     'concept', 'event', 'media']

/** Colours live in the stylesheet with every other colour, so the map
 *  repaints with the theme. Read once per theme change, not per frame. */
function readPalette(types) {
  const css = getComputedStyle(document.documentElement)
  const channel = (name, fallback) => {
    const raw = css.getPropertyValue(`--${name}`).trim()
    return raw ? `rgb(${raw.split(/\s+/).join(' ')})` : fallback
  }
  const fallback = channel('type-other', 'rgb(120 132 124)')
  const byType = {}
  for (const type of types) {
    byType[type] = KNOWN_TYPES.includes(type)
      ? channel(`type-${type}`, fallback) : fallback
  }
  return {
    byType,
    other: fallback,
    edge: channel('graph-edge', 'rgb(150 162 152)'),
    shortcut: channel('graph-shortcut', 'rgb(200 132 40)'),
    accent: channel('accent', 'rgb(47 125 88)'),
    text: channel('text', 'rgb(24 32 27)'),
  }
}

/* -- the simulation ------------------------------------------------------ */

const CHARGE = 1500          // repulsion, falling off with distance²
const NEAR = 26000           // ...applied only within ~160px, so it stays cheap
const REST = 95              // spring rest length
const PULL_STRUCT = 0.06     // containment holds a branch together...
const PULL_LINK = 0.03       // ...more firmly than a curated trail does
const GRAVITY = 0.011
const MAX_STEP = 14
const DAMPING = 0.6
const COOL = 0.988
const DRIFT = 0.012          // the settled forest breathes rather than freezes

function seed(nodes, w, h, random) {
  const regions = [...new Set(nodes.map((n) => n.id.split('/')[0]))]
  nodes.forEach((n, i) => {
    const angle = (regions.indexOf(n.id.split('/')[0]) / regions.length) * Math.PI * 2
                  + (i % 7) * 0.13
    const r = Math.min(w, h) * (0.08 + 0.34 * random())
    n.x = w / 2 + Math.cos(angle) * r
    n.y = h / 2 + Math.sin(angle) * r
    n.vx = 0
    n.vy = 0
  })
}

function step(nodes, springs, w, h, alpha, pinned) {
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i]
      const b = nodes[j]
      let dx = a.x - b.x
      let dy = a.y - b.y
      const d2 = dx * dx + dy * dy || 1
      if (d2 >= NEAR) continue
      const f = (CHARGE / d2) * alpha
      dx *= f; dy *= f
      a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy
    }
  }
  for (const s of springs) {
    const a = nodes[s.a]
    const b = nodes[s.b]
    const dx = b.x - a.x
    const dy = b.y - a.y
    const d = Math.hypot(dx, dy) || 1
    const f = (d - REST) * s.w * alpha
    a.vx += (dx / d) * f; a.vy += (dy / d) * f
    b.vx -= (dx / d) * f; b.vy -= (dy / d) * f
  }
  for (const n of nodes) {
    n.vx += (w / 2 - n.x) * GRAVITY * alpha
    n.vy += (h / 2 - n.y) * GRAVITY * alpha
    if (n === pinned) { n.vx = 0; n.vy = 0; continue }
    n.x += Math.max(-MAX_STEP, Math.min(MAX_STEP, n.vx))
    n.y += Math.max(-MAX_STEP, Math.min(MAX_STEP, n.vy))
    n.vx *= DAMPING; n.vy *= DAMPING
  }
}

/* -- the view ------------------------------------------------------------ */

export default function ForestGraph({ data, selected, onSelect, onOpen,
                                      busy, error, onReload }) {
  const { t } = useI18n()
  const { resolved } = useTheme()
  const canvas = useRef(null)
  const box = useRef(null)
  const sim = useRef({ nodes: [], springs: [], index: {}, alpha: 0 })
  const view = useRef({ x: 0, y: 0, k: 1 })
  const pinned = useRef(null)
  const [hover, setHover] = useState(null)
  const [hidden, setHidden] = useState(() => new Set())
  const [showHeat, setShowHeat] = useState(true)
  const [showProposals, setShowProposals] = useState(true)
  const [showStructure, setShowStructure] = useState(true)

  const calm = typeof matchMedia === 'function'
    && matchMedia('(prefers-reduced-motion: reduce)').matches

  const types = useMemo(() => {
    const present = new Set((data?.nodes || []).map((n) => n.type))
    return (data?.types || []).filter((ty) => present.has(ty))
  }, [data])

  const palette = useMemo(
    () => readPalette(types.length ? types : KNOWN_TYPES),
    [types, resolved])

  const counts = useMemo(() => {
    const out = {}
    for (const n of data?.nodes || []) out[n.type] = (out[n.type] || 0) + 1
    return out
  }, [data])

  /* Structure comes from `parent`, which the Station already filtered: a
     branch whose parent is out of scope arrives with none, so containment
     never draws an edge to something the caller cannot see. */
  const links = useMemo(() => {
    if (!data) return []
    const known = new Set(data.nodes.map((n) => n.id))
    const structure = data.nodes
      .filter((n) => n.parent && known.has(n.parent))
      .map((n) => ({ src: n.parent, dst: n.id, rel: '', structure: true,
                     confidence: 1 }))
    return [...data.edges, ...structure]
  }, [data])

  const neighbours = useMemo(() => {
    const map = new Map()
    const add = (a, b) => {
      if (!map.has(a)) map.set(a, new Set())
      map.get(a).add(b)
    }
    for (const e of links) { add(e.src, e.dst); add(e.dst, e.src) }
    return map
  }, [links])

  /* Build (or rebuild) the simulation whenever the payload changes. */
  const reheat = useCallback((full) => {
    const el = canvas.current
    if (!el || !data) return
    const w = el.clientWidth || 720
    const h = el.clientHeight || 520
    if (full) {
      const nodes = data.nodes.map((n) => ({ ...n }))
      const index = Object.fromEntries(nodes.map((n, i) => [n.id, i]))
      const springs = links
        .filter((e) => index[e.src] != null && index[e.dst] != null)
        .map((e) => ({ a: index[e.src], b: index[e.dst],
                       w: e.structure ? PULL_STRUCT : PULL_LINK }))
      // Deterministic placement: the same forest opens the same way twice,
      // which matters when somebody is describing what they are looking at.
      let s = 1
      const random = () => {
        s = (s * 1103515245 + 12345) % 2147483648
        return s / 2147483648
      }
      seed(nodes, w, h, random)
      sim.current = { nodes, springs, index, alpha: 1 }
      if (calm) {
        for (let i = 0; i < 300; i++) {
          step(nodes, springs, w, h, 1 - i / 300, null)
        }
        sim.current.alpha = 0
      }
    } else {
      sim.current.alpha = Math.max(sim.current.alpha, 1)
      if (!calm) return
      const { nodes, springs } = sim.current
      seed(nodes, w, h, (() => { let s = 1; return () => (s = (s * 48271) % 2147483647) / 2147483647 })())
      for (let i = 0; i < 300; i++) step(nodes, springs, w, h, 1 - i / 300, null)
      sim.current.alpha = 0
    }
  }, [data, links, calm])

  useEffect(() => { reheat(true) }, [reheat])

  const visible = useCallback((n) => !hidden.has(n.type), [hidden])

  const drawnEdge = useCallback((e) => {
    if (e.structure && !showStructure) return false
    if (!e.structure && e.confidence < 1 && e.rel !== 'discovered-shortcut'
        && !showProposals) return false
    const { index, nodes } = sim.current
    const a = nodes[index[e.src]]
    const b = nodes[index[e.dst]]
    return Boolean(a && b && visible(a) && visible(b))
  }, [showStructure, showProposals, visible])

  /* -- painting ---------------------------------------------------------- */

  const draw = useCallback(() => {
    const el = canvas.current
    if (!el || !data) return
    const dpr = window.devicePixelRatio || 1
    const w = el.clientWidth
    const h = el.clientHeight
    if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
      el.width = Math.round(w * dpr)
      el.height = Math.round(h * dpr)
    }
    const ctx = el.getContext('2d')
    const { nodes, index } = sim.current
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    ctx.translate(view.current.x, view.current.y)
    ctx.scale(view.current.k, view.current.k)

    const focus = hover || selected
    const near = focus
      ? new Set([focus, ...(neighbours.get(focus) || [])]) : null
    const k = view.current.k

    for (const e of links) {
      if (!drawnEdge(e)) continue
      const a = nodes[index[e.src]]
      const b = nodes[index[e.dst]]
      const dim = near && !(near.has(e.src) && near.has(e.dst))
      const shortcut = e.rel === 'discovered-shortcut'
      ctx.setLineDash(shortcut ? [5, 4] : e.confidence < 1 ? [3, 4] : [])
      ctx.globalAlpha = dim ? 0.08 : shortcut ? 0.9 : e.structure ? 0.3 : 0.62
      ctx.strokeStyle = shortcut ? palette.shortcut : palette.edge
      ctx.lineWidth = (shortcut ? 1.6 : e.structure ? 0.8 : 1.1) / k
      ctx.beginPath()
      ctx.moveTo(a.x, a.y)
      ctx.lineTo(b.x, b.y)
      ctx.stroke()
    }
    ctx.setLineDash([])
    ctx.globalAlpha = 1

    for (const n of nodes) {
      if (!visible(n)) continue
      const dim = near && !near.has(n.id)
      const r = 3 + Math.min(9, n.degree * 0.65)
      if (showHeat && n.heat > 0.05 && !dim) {
        const glow = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, r * 3.6)
        glow.addColorStop(0, palette.shortcut.replace(')', ` / ${0.34 * n.heat})`)
          .replace('rgb(', 'rgba('))
        glow.addColorStop(1, palette.shortcut.replace(')', ' / 0)')
          .replace('rgb(', 'rgba('))
        ctx.fillStyle = glow
        ctx.beginPath()
        ctx.arc(n.x, n.y, r * 3.6, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalAlpha = dim ? 0.18 : 1
      ctx.fillStyle = palette.byType[n.type] || palette.other
      ctx.beginPath()
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
      ctx.fill()
      if (n.id === selected) {
        ctx.strokeStyle = palette.accent
        ctx.lineWidth = 1.8 / k
        ctx.beginPath()
        ctx.arc(n.x, n.y, r + 3.5, 0, Math.PI * 2)
        ctx.stroke()
      }
      if (!dim && (n.degree >= 7 || n.id === focus || k > 1.6)) {
        ctx.globalAlpha = dim ? 0.2 : 0.85
        ctx.fillStyle = palette.text
        ctx.font = `${10.5 / k}px ui-monospace, Menlo, monospace`
        ctx.fillText(n.id.split('/').pop().replace('_index', '/'),
                     n.x + r + 4, n.y + 3)
      }
      ctx.globalAlpha = 1
    }
  }, [data, links, hover, selected, neighbours, palette, showHeat, visible,
      drawnEdge])

  /* One loop for the life of the view: it steps the physics while there is
     energy left, then keeps a slow drift so the forest looks alive rather
     than frozen. Under reduced motion it paints once per change instead. */
  useEffect(() => {
    if (calm) { draw(); return undefined }
    let running = true
    let frame = 0
    const tick = () => {
      if (!running) return
      const el = canvas.current
      const s = sim.current
      if (el && s.nodes.length) {
        const w = el.clientWidth
        const h = el.clientHeight
        if (s.alpha > 0.012) {
          step(s.nodes, s.springs, w, h, s.alpha, pinned.current)
          s.alpha *= COOL
        } else {
          if (frame % 4 === 0) {
            const n = s.nodes[Math.floor(Math.random() * s.nodes.length)]
            if (n && n !== pinned.current) {
              n.vx += (Math.random() - 0.5) * 0.9
              n.vy += (Math.random() - 0.5) * 0.9
            }
          }
          step(s.nodes, s.springs, w, h, DRIFT, pinned.current)
        }
      }
      frame += 1
      draw()
      requestAnimationFrame(tick)
    }
    tick()
    return () => { running = false }
  }, [draw, calm])

  useEffect(() => {
    const el = box.current
    if (!el || typeof ResizeObserver !== 'function') return undefined
    const ro = new ResizeObserver(() => { sim.current.alpha = Math.max(sim.current.alpha, 0.3); draw() })
    ro.observe(el)
    return () => ro.disconnect()
  }, [draw])

  /* -- pointer ----------------------------------------------------------- */

  const at = (ev) => {
    const r = canvas.current.getBoundingClientRect()
    return {
      x: (ev.clientX - r.left - view.current.x) / view.current.k,
      y: (ev.clientY - r.top - view.current.y) / view.current.k,
    }
  }
  const nodeAt = (p) => {
    let best = null
    let bd = 15 / view.current.k
    for (const n of sim.current.nodes) {
      if (!visible(n)) continue
      const d = Math.hypot(n.x - p.x, n.y - p.y)
      if (d < bd) { bd = d; best = n }
    }
    return best
  }

  const drag = useRef(null)
  const pan = useRef(null)
  const origin = useRef(null)

  function down(ev) {
    const n = nodeAt(at(ev))
    if (n) { drag.current = n; pinned.current = n } else {
      pan.current = { x: ev.clientX, y: ev.clientY }
    }
    origin.current = { x: ev.clientX, y: ev.clientY }
    ev.currentTarget.setPointerCapture(ev.pointerId)
    ev.currentTarget.dataset.dragging = 'true'
  }
  function move(ev) {
    if (drag.current) {
      const p = at(ev)
      drag.current.x = p.x
      drag.current.y = p.y
      sim.current.alpha = Math.max(sim.current.alpha, 0.3)
      if (calm) draw()
      return
    }
    if (pan.current) {
      view.current.x += ev.clientX - pan.current.x
      view.current.y += ev.clientY - pan.current.y
      pan.current = { x: ev.clientX, y: ev.clientY }
      if (calm) draw()
      return
    }
    const n = nodeAt(at(ev))
    if ((n?.id || null) !== hover) setHover(n?.id || null)
  }
  function up(ev) {
    // A drag that ends where it started is a click. Four pixels of slack,
    // because a trackpad rarely lets go without moving a little.
    const from = origin.current
    const moved = from && Math.hypot(ev.clientX - from.x, ev.clientY - from.y) > 4
    if (!moved) {
      const n = drag.current || nodeAt(at(ev))
      if (n) onSelect?.(n.id)
    }
    drag.current = null
    pinned.current = null
    pan.current = null
    origin.current = null
    ev.currentTarget.dataset.dragging = 'false'
  }
  function wheel(ev) {
    ev.preventDefault()
    const r = canvas.current.getBoundingClientRect()
    const mx = ev.clientX - r.left
    const my = ev.clientY - r.top
    const f = ev.deltaY < 0 ? 1.15 : 1 / 1.15
    const k = Math.max(0.3, Math.min(4, view.current.k * f))
    view.current.x = mx - (mx - view.current.x) * (k / view.current.k)
    view.current.y = my - (my - view.current.y) * (k / view.current.k)
    view.current.k = k
    if (calm) draw()
  }

  /* Wheel must be non-passive to preventDefault, which React's onWheel is
     not — so it is bound by hand. */
  useEffect(() => {
    const el = canvas.current
    if (!el) return undefined
    const handler = (ev) => wheel(ev)
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  })

  if (busy) return <div className="card p-4"><Skeleton rows={6} /></div>
  if (error) {
    return <div className="card p-4"><ErrorNote error={error} onRetry={onReload} /></div>
  }
  if (!data?.nodes?.length) {
    return (
      <div className="card p-4">
        <Empty icon={GraphIcon} title={t('graph.empty')}>{t('graph.empty_hint')}</Empty>
      </div>
    )
  }

  const hovered = hover && data.nodes.find((n) => n.id === hover)
  const toggle = (type) => setHidden((prev) => {
    const next = new Set(prev)
    if (next.has(type)) next.delete(type)
    else next.add(type)
    return next
  })

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-3 py-2">
        {types.map((type) => (
          <button key={type} type="button" onClick={() => toggle(type)}
                  aria-pressed={!hidden.has(type)}
                  className={`badge transition ${hidden.has(type) ? 'opacity-40' : ''}`}>
            <span className="tree-dot"
                  style={{ background: palette.byType[type] || palette.other }} />
            {type}
            <span className="text-text-3">{counts[type]}</span>
          </button>
        ))}
        <span className="flex-1" />
        <Switch on={showHeat} set={setShowHeat} label={t('graph.heat')} />
        <Switch on={showProposals} set={setShowProposals} label={t('graph.proposals')} />
        <Switch on={showStructure} set={setShowStructure} label={t('graph.structure')} />
        <button type="button" className="btn btn-sm btn-ghost"
                onClick={() => reheat(false)} title={t('graph.reorganize')}>
          <Refresh size={14} /> {t('graph.reorganize')}
        </button>
      </div>

      <div ref={box} className="relative">
        <canvas ref={canvas} className="graph-canvas h-[clamp(360px,58vh,640px)]"
                onPointerDown={down} onPointerMove={move} onPointerUp={up}
                onPointerLeave={() => setHover(null)} />
        {hovered && (
          <div className="pointer-events-none absolute left-3 top-3 max-w-[19rem]
                          rounded-lg border border-line bg-bg-elev/95 px-3 py-2
                          shadow-pop backdrop-blur">
            <div className="nodeid truncate">{hovered.id}</div>
            <div className="mt-0.5 text-[13px] font-medium text-text">{hovered.title}</div>
            <p className="mt-1 line-clamp-3 text-[12px] leading-relaxed text-text-3">
              {hovered.summary}
            </p>
            <div className="mt-1.5 text-[11px] text-text-3">
              {t('graph.tip_stats', { degree: hovered.degree,
                                      heat: hovered.heat.toFixed(2) })}
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t
                      border-line px-3 py-2 text-[11.5px] text-text-3">
        <Legend dash="" color={palette.edge} label={t('graph.legend_trail')} />
        <Legend dash="3 4" color={palette.edge} label={t('graph.legend_proposal')} />
        <Legend dash="5 4" color={palette.shortcut} label={t('graph.legend_shortcut')} />
        <span className="inline-flex items-center gap-1.5">
          <span className="tree-dot" style={{ background: palette.shortcut }} />
          {t('graph.legend_heat')}
        </span>
        <span className="ml-auto">{t('graph.hint')}</span>
        {data.truncated && (
          <span className="badge badge-warn">{t('graph.truncated')}</span>
        )}
      </div>

      {selected && (
        <div className="border-t border-line px-3 py-2 text-[12px] text-text-3">
          <button type="button" className="btn btn-sm"
                  onClick={() => onOpen?.(selected)}>
            {t('graph.open_in_files')}
          </button>
        </div>
      )}
    </div>
  )
}

function Switch({ on, set, label }) {
  return (
    <button type="button" onClick={() => set(!on)} aria-pressed={on}
            className={`badge transition ${on ? 'badge-accent' : 'opacity-55'}`}>
      {label}
    </button>
  )
}

function Legend({ dash, color, label }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <svg width="24" height="6" aria-hidden="true">
        <line x1="0" y1="3" x2="24" y2="3" stroke={color} strokeWidth="1.4"
              strokeDasharray={dash || undefined} />
      </svg>
      {label}
    </span>
  )
}
