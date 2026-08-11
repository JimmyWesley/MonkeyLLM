// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The graph mode of Explore (spec J.5.4, v0.38).
 *
 * A forest is a graph with heat on it, and every list-shaped console so far
 * has had to describe that by reading out names. This draws it.
 *
 * Decisions worth keeping:
 *
 * 1. **Canvas, and the simulation is written here.** A graph library is a
 *    megabyte and an opinion about how nodes should look. The physics below
 *    is the standard velocity-Verlet layout (the d3-force family): long-range
 *    many-body repulsion through a Barnes-Hut quadtree — O(n log n), so a
 *    few thousand nodes stay inside a frame — springs whose strength is
 *    normalised by the smaller endpoint's degree so a hub is not torn apart
 *    by its own leaves, and a weak centring pull. Long-range repulsion is
 *    the whole trick: clusters that share no trail still make room for each
 *    other, which is what makes the map legible at a thousand nodes.
 * 2. **The layout settles (J.5.4 v0.38).** Energy decays to zero and the
 *    loop stops stepping; motion is spent only on new data, the operator's
 *    hand, or an explicit reorganize. A forest cannot be pointed at while
 *    it trembles.
 * 3. **Every channel carries a fact the forest holds** (J.5.4): colour is
 *    the node's type or its home branch — the operator's choice between two
 *    facts, never an invented category; radius is degree recomputed by the
 *    Station over what this principal may see; the glow is pheromone; a
 *    dashed edge is a proposal (`confidence < 1`) and never an assertion.
 * 4. **View tuning is the operator's and stays out of the address** (J.5.8):
 *    filters, groups, display and force settings persist in browser storage
 *    per forest. The address carries the selection, not the taste.
 * 5. **Replay is presentation over the projection already in hand** (J.5.4
 *    v0.38): `created` order, no second call, no write. Under reduced
 *    motion it is a scrubber, not an animation.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useI18n } from '../i18n.jsx'
import { useTheme } from '../theme.jsx'
import { Empty, ErrorNote, Skeleton, Toggle } from '../design/ui.jsx'
import {
  ChevronDown, Graph as GraphIcon, Pause, Play, Refresh, Search, Sliders, X,
} from '../design/icons.jsx'

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

/** A branch is a fact the id holds (J.5.4 v0.38): the group of
 *  `tasks/back-end/041-oauth` at depth 2 is `tasks/back-end`. A node that
 *  lives at the root has no branch to name, so it groups under `/`. */
function groupOf(id, depth) {
  const parts = id.split('/')
  if (parts.length <= 1) return '/'
  return parts.slice(0, Math.min(depth, parts.length - 1)).join('/')
}

/** Group hues walk the golden angle, so any number of branches lands evenly
 *  spread and the same forest colours the same way twice. The root group
 *  stays grey: it is the absence of a branch, not one more branch. */
function groupPalette(keys, dark) {
  const out = {}
  keys.forEach((key, i) => {
    out[key] = key === '/'
      ? null
      : `hsl(${Math.round((i * 137.508 + 208) % 360)} 60% ${dark ? 63 : 44}%)`
  })
  return out
}

/* -- the simulation ------------------------------------------------------ */

const REST = 44            // spring rest length at distance ×1
const REPEL = 150          // many-body strength at repel ×1
const CENTER = 0.055       // centring pull at center ×1
const VEL_DECAY = 0.62     // velocity kept per tick
const ALPHA_DECAY = 0.026  // energy lost per tick — ~4 s to rest
const ALPHA_MIN = 0.004    // below this the loop stops stepping
const THETA2 = 0.81        // Barnes-Hut opening criterion, θ = 0.9

function jiggle(rand) { return (rand() - 0.5) * 1e-4 }

/** One quadtree per tick. Objects, not typed arrays: at a few thousand
 *  nodes allocation is far from the bottleneck, and this stays readable. */
function buildQuad(nodes) {
  let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity
  for (const n of nodes) {
    if (n.x < x0) x0 = n.x
    if (n.y < y0) y0 = n.y
    if (n.x > x1) x1 = n.x
    if (n.y > y1) y1 = n.y
  }
  const size = Math.max(x1 - x0, y1 - y0) || 1
  const root = { x: x0, y: y0, s: size, kids: null, one: null, m: 0, sx: 0, sy: 0 }
  const place = (q, n) => {
    const h = q.s / 2
    const i = (n.x >= q.x + h ? 1 : 0) | (n.y >= q.y + h ? 2 : 0)
    const k = q.kids[i] || (q.kids[i] = {
      x: q.x + ((i & 1) ? h : 0), y: q.y + ((i & 2) ? h : 0), s: h,
      kids: null, one: null, m: 0, sx: 0, sy: 0,
    })
    insert(k, n, 0)
  }
  const insert = (q, n, depth) => {
    q.m += 1; q.sx += n.x; q.sy += n.y
    if (q.one === null && q.kids === null) { q.one = n; return }
    if (depth > 22) return // coincident pile: aggregate mass is enough
    if (q.kids === null) {
      q.kids = [null, null, null, null]
      const prior = q.one
      q.one = null
      place(q, prior)
    }
    place(q, n)
  }
  for (const n of nodes) insert(root, n, 0)
  return root
}

function applyRepulsion(root, n, k, rand) {
  const stack = [root]
  while (stack.length) {
    const q = stack.pop()
    if (!q || !q.m) continue
    let dx = n.x - q.sx / q.m
    let dy = n.y - q.sy / q.m
    let d2 = dx * dx + dy * dy
    // Far enough away, a whole quadrant acts as one body; up close, open it.
    if (q.kids !== null && q.s * q.s >= THETA2 * d2) {
      stack.push(q.kids[0], q.kids[1], q.kids[2], q.kids[3])
      continue
    }
    if (q.one === n && q.m === 1) continue
    if (d2 === 0) { dx = jiggle(rand); dy = jiggle(rand); d2 = dx * dx + dy * dy }
    if (d2 < 1) d2 = Math.sqrt(d2) // very close: soften instead of exploding
    const f = (k * q.m) / d2
    n.vx += dx * f
    n.vy += dy * f
  }
}

/** One tick. `p` is the operator's force tuning (×1 = the defaults). */
function step(sim, w, h, p) {
  const { nodes, springs, rand } = sim
  sim.alpha += (sim.alphaTarget - sim.alpha) * ALPHA_DECAY
  const alpha = sim.alpha
  const live = []
  for (const n of nodes) if (n.on) live.push(n)

  if (live.length > 1) {
    const root = buildQuad(live)
    const k = REPEL * p.repel * alpha
    for (const n of live) applyRepulsion(root, n, k, rand)
  }

  const rest = REST * p.distance
  for (const s of springs) {
    if (!s.on) continue
    const a = nodes[s.a]
    const b = nodes[s.b]
    let dx = (b.x + b.vx) - (a.x + a.vx)
    let dy = (b.y + b.vy) - (a.y + a.vy)
    let d = Math.hypot(dx, dy)
    if (d === 0) { dx = jiggle(rand); dy = jiggle(rand); d = Math.hypot(dx, dy) }
    const f = ((d - rest) / d) * alpha * s.strength * p.attract
    dx *= f; dy *= f
    b.vx -= dx * s.bias; b.vy -= dy * s.bias
    a.vx += dx * (1 - s.bias); a.vy += dy * (1 - s.bias)
  }

  const kc = CENTER * p.center * alpha
  for (const n of live) {
    n.vx += (w / 2 - n.x) * kc
    n.vy += (h / 2 - n.y) * kc
    if (n.fx != null) { n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0; continue }
    n.vx *= VEL_DECAY; n.vy *= VEL_DECAY
    n.x += n.vx; n.y += n.vy
  }

  if (sim.alpha < ALPHA_MIN && sim.alphaTarget === 0) sim.active = false
}

/** Deterministic placement: the same forest opens the same way twice, which
 *  matters when somebody is describing what they are looking at.
 *
 *  A node is born beside its own nucleus, never at the middle of the world:
 *  each branch gets a centre on a ring, roots hatch at their branch's
 *  centre, and every child hatches beside its parent — breadth-first down
 *  the structure, so a branch opens as a disc around its own hub and the
 *  physics only has to bloom it, not carry it across the map. Orphans with
 *  no home at all seed on the outer ring, which is where the repulsion
 *  would take them anyway. */
function seed(sim, w, h) {
  let s = 7
  const rand = () => {
    s = (s * 1103515245 + 12345) % 2147483648
    return s / 2147483648
  }
  sim.rand = rand
  const { nodes, index } = sim
  const groups = [...new Set(nodes.map((n) => n.seedGroup))].sort()
  const R = Math.min(w, h) * 0.34
  const centre = {}
  groups.forEach((g, i) => {
    const angle = (i / Math.max(1, groups.length)) * Math.PI * 2
    centre[g] = { x: w / 2 + Math.cos(angle) * R,
                  y: h / 2 + Math.sin(angle) * R }
  })

  const hatch = (n, x, y, spread) => {
    const a = rand() * Math.PI * 2
    const r = spread * (0.35 + rand() * 0.65)
    n.x = x + Math.cos(a) * r
    n.y = y + Math.sin(a) * r
    n.vx = 0; n.vy = 0; n.fx = null; n.fy = null
    n.placed = true
  }

  const kids = new Map()
  const queue = []
  for (const n of nodes) {
    n.placed = false
    const pi = n.parent != null ? index[n.parent] : undefined
    if (pi === undefined) {
      // No parent in the payload: this IS a nucleus (or a true orphan).
      const c = centre[n.seedGroup]
      if (n.degree === 0) {
        const a = rand() * Math.PI * 2
        const r = Math.min(w, h) * 0.52 * (0.9 + rand() * 0.25)
        hatch(n, w / 2 + Math.cos(a) * r, h / 2 + Math.sin(a) * r, 10)
      } else {
        hatch(n, c.x, c.y, 24)
      }
      queue.push(n)
    } else {
      if (!kids.has(pi)) kids.set(pi, [])
      kids.get(pi).push(n)
    }
  }
  while (queue.length) {
    const n = queue.shift()
    for (const child of kids.get(index[n.id]) || []) {
      if (child.placed) continue
      hatch(child, n.x, n.y, 26)
      queue.push(child)
    }
  }
  // A parent pointer the walk never reached (it cannot happen in a tree,
  // but a map must not hang on a malformed payload): the branch centre.
  for (const n of nodes) {
    if (!n.placed) hatch(n, centre[n.seedGroup].x, centre[n.seedGroup].y, 24)
  }
}

/* -- view settings (J.5.4 v0.38: presentation, per forest, never in the
      address, never a call) ---------------------------------------------- */

/* The factory preset is the operator-tuned one that read best on a real
 * ~1900-node forest: long links and strong repulsion open the clusters,
 * heavier nodes and thinner trails keep the nuclei legible, proposals stay
 * quiet until asked for. Presentation only — no contract fixes these. */
const DEFAULTS = {
  query: '',
  orphans: true, heatOn: true, proposals: false, shortcuts: true,
  structure: true,
  hiddenTypes: [], hiddenGroups: [],
  colorBy: 'branch', groupDepth: 3,
  arrows: true, labels: 0.5, nodeScale: 1.5, linkWidth: 0.7,
  center: 1.2, repel: 1.5, attract: 0.85, distance: 2.3,
}

const settingsKey = (forest) => `monkeyllm.graph.${forest}`

function loadSettings(forest) {
  try {
    const raw = JSON.parse(localStorage.getItem(settingsKey(forest)) || '{}')
    return { ...DEFAULTS, ...raw }
  } catch { return { ...DEFAULTS } }
}

/* -- the view ------------------------------------------------------------ */

export default function ForestGraph({ forest, data, selected, onSelect,
                                      onOpen, busy, error, onReload }) {
  const { t } = useI18n()
  const { resolved } = useTheme()
  const canvas = useRef(null)
  const box = useRef(null)
  const sim = useRef({ nodes: [], springs: [], index: {}, order: [],
                       alpha: 0, alphaTarget: 0, active: false, fitted: false,
                       rand: Math.random })
  const view = useRef({ x: 0, y: 0, k: 1 })
  const needsDraw = useRef(true)

  const [settings, setSettings] = useState(() => loadSettings(forest))
  const [panel, setPanel] = useState(false)
  const [hover, setHover] = useState(null)
  const [replay, setReplay] = useState({ on: false, playing: false, t: 0 })

  const calm = typeof matchMedia === 'function'
    && matchMedia('(prefers-reduced-motion: reduce)').matches

  // Refs mirror everything draw() and the loop read, so the one animation
  // loop mounted for the life of the view never sees a stale closure.
  const paramsRef = useRef(settings)
  const focusRef = useRef({ hover: null, selected: null })
  const replayRef = useRef(replay)
  const paletteRef = useRef(null)
  const drawRef = useRef(() => {})

  useEffect(() => { setSettings(loadSettings(forest)) }, [forest])
  useEffect(() => {
    paramsRef.current = settings
    // The search term is deliberately not persisted: a filter remembered
    // from yesterday would open tomorrow's forest mysteriously empty.
    try {
      localStorage.setItem(settingsKey(forest),
                           JSON.stringify({ ...settings, query: '' }))
    } catch { /* a full or absent storage costs the tuning, never the map */ }
  }, [settings, forest])
  useEffect(() => { replayRef.current = replay }, [replay])
  useEffect(() => {
    focusRef.current = { hover, selected }
    needsDraw.current = true
  }, [hover, selected])

  const set = useCallback((patch) => {
    setSettings((prev) => ({ ...prev, ...patch }))
  }, [])

  const types = useMemo(() => {
    const present = new Set((data?.nodes || []).map((n) => n.type))
    return (data?.types || []).filter((ty) => present.has(ty))
  }, [data])

  const palette = useMemo(
    () => readPalette(types.length ? types : KNOWN_TYPES),
    [types, resolved])

  const typeCounts = useMemo(() => {
    const out = {}
    for (const n of data?.nodes || []) out[n.type] = (out[n.type] || 0) + 1
    return out
  }, [data])

  /* Branch groups at the chosen depth, with their deterministic colours. */
  const groups = useMemo(() => {
    const counts = new Map()
    for (const n of data?.nodes || []) {
      const g = groupOf(n.id, settings.groupDepth)
      counts.set(g, (counts.get(g) || 0) + 1)
    }
    const keys = [...counts.keys()].sort()
    return { keys, counts, colors: groupPalette(keys, resolved === 'dark') }
  }, [data, settings.groupDepth, resolved])

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
  const neighboursRef = useRef(neighbours)
  useEffect(() => { neighboursRef.current = neighbours }, [neighbours])
  const groupsRef = useRef(groups)
  useEffect(() => { groupsRef.current = groups }, [groups])
  useEffect(() => { paletteRef.current = palette }, [palette])

  /* -- building the simulation ------------------------------------------- */

  const applyFilters = useCallback((s) => {
    const p = paramsRef.current
    const hiddenT = new Set(p.hiddenTypes)
    const hiddenG = new Set(p.hiddenGroups)
    const words = p.query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    // The quick search keeps what matches AND what stands one trail away:
    // a hit with its neighbourhood is an answer, a hit alone is a dot.
    let keep = null
    if (words.length) {
      keep = new Set()
      for (const n of s.nodes) {
        n.matched = words.every((word) => n.hay.includes(word))
        if (n.matched) keep.add(n.id)
      }
      for (const id of [...keep]) {
        for (const nb of neighboursRef.current.get(id) || []) keep.add(nb)
      }
    } else {
      for (const n of s.nodes) n.matched = false
    }
    for (const n of s.nodes) {
      n.on = !hiddenT.has(n.type)
        && !hiddenG.has(groupOf(n.id, p.groupDepth))
        && (p.orphans || n.degree > 0)
        && (keep === null || keep.has(n.id))
        && n.bornRank < s.alive
    }
    for (const spring of s.springs) {
      spring.on = s.nodes[spring.a].on && s.nodes[spring.b].on
    }
  }, [])

  /* Reads through refs so its identity is stable: a theme change or a new
     group depth recolours the standing layout instead of rebuilding and
     reseeding the whole simulation. */
  const applyColors = useCallback((s) => {
    const p = paramsRef.current
    const g = groupsRef.current
    const pal = paletteRef.current
    for (const n of s.nodes) {
      n.color = p.colorBy === 'branch'
        ? (g.colors[groupOf(n.id, p.groupDepth)] || pal.other)
        : (pal.byType[n.type] || pal.other)
    }
  }, [])

  useEffect(() => {
    if (!sim.current.nodes.length) return
    applyColors(sim.current)
    needsDraw.current = true
  }, [groups, palette, applyColors])

  const settle = useCallback((ticks) => {
    const el = canvas.current
    const s = sim.current
    if (!el || !s.nodes.length) return
    for (let i = 0; i < ticks && s.active; i++) {
      step(s, el.clientWidth || 720, el.clientHeight || 520, paramsRef.current)
    }
    needsDraw.current = true
  }, [])

  const fit = useCallback((lerp = 1) => {
    const el = canvas.current
    const s = sim.current
    if (!el) return
    let x0 = Infinity; let y0 = Infinity; let x1 = -Infinity; let y1 = -Infinity
    for (const n of s.nodes) {
      if (!n.on) continue
      if (n.x < x0) x0 = n.x
      if (n.y < y0) y0 = n.y
      if (n.x > x1) x1 = n.x
      if (n.y > y1) y1 = n.y
    }
    if (x0 === Infinity) return
    const w = el.clientWidth
    const h = el.clientHeight
    const k = Math.max(0.12, Math.min(
      1.6, (w - 90) / Math.max(1, x1 - x0), (h - 90) / Math.max(1, y1 - y0)))
    const tx = w / 2 - k * (x0 + x1) / 2
    const ty = h / 2 - k * (y0 + y1) / 2
    const v = view.current
    v.k += (k - v.k) * lerp
    v.x += (tx - v.x) * lerp
    v.y += (ty - v.y) * lerp
    needsDraw.current = true
  }, [])

  /* Build (or rebuild) whenever the payload changes. */
  const build = useCallback(() => {
    const el = canvas.current
    if (!el || !data) return
    const w = el.clientWidth || 720
    const h = el.clientHeight || 520
    const nodes = data.nodes.map((n) => ({
      ...n,
      label: (n.title || n.id.split('/').pop().replace('_index', '/')).slice(0, 34),
      hay: `${n.id} ${n.title || ''} ${(n.tags || []).join(' ')} ${n.type}`
        .toLowerCase(),
      seedGroup: groupOf(n.id, 2),
      r0: 2.4 + Math.min(8, Math.sqrt(n.degree || 0) * 1.7),
      on: true, bornRank: 0, bornAt: 0, fx: null, fy: null,
      x: 0, y: 0, vx: 0, vy: 0,
    }))
    const index = Object.fromEntries(nodes.map((n, i) => [n.id, i]))

    // Spring strength is d3's: 1 / min(degree) over the springs actually
    // simulated, biased so the lighter end does most of the moving. A hub
    // with three hundred leaves keeps its place; the leaves fan around it.
    const raw = links.filter((e) => index[e.src] != null && index[e.dst] != null)
    const simDegree = {}
    for (const e of raw) {
      simDegree[e.src] = (simDegree[e.src] || 0) + 1
      simDegree[e.dst] = (simDegree[e.dst] || 0) + 1
    }
    const springs = raw.map((e) => {
      const da = simDegree[e.src]
      const db = simDegree[e.dst]
      const kind = e.structure ? 1 : (e.confidence < 1 ? 0.35 : 0.7)
      return {
        a: index[e.src], b: index[e.dst],
        bias: da / (da + db),
        strength: (kind / Math.min(da, db)),
        on: true,
      }
    })

    // Replay order: the forest as it grew (J.5.4 v0.38). A passport without
    // `created` (an old projection) falls back to `updated`, and a node
    // with neither is treated as older than every record.
    const order = nodes.map((_, i) => i).sort((a, b) => {
      const ka = nodes[a].created || nodes[a].updated || '0000'
      const kb = nodes[b].created || nodes[b].updated || '0000'
      return ka < kb ? -1 : ka > kb ? 1 : (nodes[a].id < nodes[b].id ? -1 : 1)
    })
    order.forEach((nodeIdx, rank) => { nodes[nodeIdx].bornRank = rank })

    const s = {
      nodes, springs, index, order,
      alive: nodes.length, lastAlive: nodes.length,
      alpha: 1, alphaTarget: 0, active: true, fitted: false,
      rand: Math.random,
    }
    seed(s, w, h)
    sim.current = s
    applyFilters(s)
    applyColors(s)
    setReplay({ on: false, playing: false, t: 0 })
    if (calm) { settle(400); s.fitted = true; fit(); drawRef.current() }
    needsDraw.current = true
  }, [data, links, calm, applyFilters, applyColors, settle, fit])

  useEffect(() => { build() }, [build])

  /* Filter or colour tuning re-layouts what remains — motion spent on the
     operator's hand, which is the settle rule's own exception. */
  useEffect(() => {
    const s = sim.current
    if (!s.nodes.length) return
    applyFilters(s)
    applyColors(s)
    s.alpha = Math.max(s.alpha, 0.5)
    s.active = true
    if (calm) settle(300)
    needsDraw.current = true
  }, [settings.query, settings.orphans, settings.hiddenTypes,
      settings.hiddenGroups, settings.groupDepth, settings.colorBy,
      applyFilters, applyColors, calm, settle])

  /* Force tuning reheats gently; display tuning only repaints. */
  useEffect(() => {
    const s = sim.current
    if (!s.nodes.length) return
    s.alpha = Math.max(s.alpha, 0.35)
    s.active = true
    if (calm) settle(250)
    needsDraw.current = true
  }, [settings.center, settings.repel, settings.attract, settings.distance,
      calm, settle])
  useEffect(() => { needsDraw.current = true },
            [settings.arrows, settings.labels, settings.nodeScale,
             settings.linkWidth, settings.heatOn, settings.proposals,
             settings.shortcuts, settings.structure])

  /* -- replay ------------------------------------------------------------ */

  const enterReplay = useCallback(() => {
    const el = canvas.current
    const s = sim.current
    if (!el || !s.nodes.length) return
    seed(s, el.clientWidth || 720, el.clientHeight || 520)
    s.alive = 0
    s.lastAlive = 0
    s.alpha = 1
    s.active = true
    s.fitted = true // replay keeps its own camera
    applyFilters(s)
    setReplay({ on: true, playing: !calm, t: 0 })
    needsDraw.current = true
  }, [applyFilters, calm])

  const exitReplay = useCallback(() => {
    const s = sim.current
    s.alive = s.nodes.length
    s.lastAlive = s.nodes.length
    s.alphaTarget = 0
    s.alpha = Math.max(s.alpha, 0.3)
    s.active = true
    applyFilters(s)
    setReplay({ on: false, playing: false, t: 0 })
    if (calm) settle(300)
    needsDraw.current = true
  }, [applyFilters, calm, settle])

  useEffect(() => {
    const s = sim.current
    if (!s.nodes.length || !replay.on) return
    const count = Math.max(0, Math.min(s.nodes.length, Math.floor(replay.t)))
    if (count === s.alive) return
    s.alive = count
    // A node is born where its parent stands: the forest grows outward the
    // way it actually grew, instead of teleporting into a finished layout.
    if (count > s.lastAlive) {
      for (let rank = s.lastAlive; rank < count; rank++) {
        const n = s.nodes[s.order[rank]]
        const parent = n.parent != null ? s.nodes[s.index[n.parent]] : null
        if (parent && parent.bornRank < rank) {
          n.x = parent.x + (s.rand() - 0.5) * 26
          n.y = parent.y + (s.rand() - 0.5) * 26
          n.vx = 0; n.vy = 0
        }
        n.bornAt = performance.now()
      }
    }
    s.lastAlive = count
    applyFilters(s)
    s.alphaTarget = replay.playing ? 0.13 : 0
    s.alpha = Math.max(s.alpha, 0.25)
    s.active = true
    if (calm) settle(60)
    needsDraw.current = true
  }, [replay, applyFilters, calm, settle])

  useEffect(() => {
    const s = sim.current
    if (!replay.on) return
    s.alphaTarget = replay.playing ? 0.13 : 0
    if (replay.playing) s.active = true
  }, [replay.on, replay.playing])

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
    const p = paramsRef.current
    const pal = paletteRef.current
    const v = view.current
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, w, h)
    ctx.translate(v.x, v.y)
    ctx.scale(v.k, v.k)
    const k = v.k

    // Only the hand dims the map: hovering spotlights a neighbourhood, but
    // a selection restored from the address (J.5.8) keeps its ring and
    // nothing else — a reload must open in full colour, not half-faded at
    // a node somebody chose yesterday.
    const { hover: hov, selected: sel } = focusRef.current
    const focus = hov
    const near = focus
      ? new Set([focus, ...(neighboursRef.current.get(focus) || [])]) : null

    // Rough world-space viewport, for culling while zoomed in.
    const m = 60 / k
    const vx0 = -v.x / k - m
    const vy0 = -v.y / k - m
    const vx1 = (w - v.x) / k + m
    const vy1 = (h - v.y) / k + m
    const inView = (n) => n.x > vx0 && n.x < vx1 && n.y > vy0 && n.y < vy1

    // Edges batch into one path per style: at a few thousand trails, one
    // stroke per style is the difference between a frame and four.
    const buckets = {
      structure: { lit: [], dim: [], alpha: 0.3, width: 0.7, dash: [] },
      trail: { lit: [], dim: [], alpha: 0.6, width: 1.05, dash: [] },
      proposal: { lit: [], dim: [], alpha: 0.5, width: 0.9, dash: [3, 4] },
      shortcut: { lit: [], dim: [], alpha: 0.9, width: 1.5, dash: [5, 4] },
    }
    const arrows = []
    for (const e of links) {
      const a = nodes[index[e.src]]
      const b = nodes[index[e.dst]]
      if (!a || !b || !a.on || !b.on) continue
      if (!inView(a) && !inView(b)) continue
      const shortcut = e.rel === 'discovered-shortcut'
      const proposal = !e.structure && !shortcut && e.confidence < 1
      if (e.structure && !p.structure) continue
      if (proposal && !p.proposals) continue
      if (shortcut && !p.shortcuts) continue
      const kind = e.structure ? 'structure'
        : shortcut ? 'shortcut' : proposal ? 'proposal' : 'trail'
      const lit = !near || (near.has(e.src) && near.has(e.dst))
      buckets[kind][lit ? 'lit' : 'dim'].push(a.x, a.y, b.x, b.y)
      if (p.arrows && !e.structure && lit && k >= 1.1) arrows.push(a, b)
    }
    for (const [kind, bucket] of Object.entries(buckets)) {
      const color = kind === 'shortcut' ? pal.shortcut : pal.edge
      ctx.setLineDash(bucket.dash)
      ctx.lineWidth = (bucket.width * p.linkWidth) / k
      ctx.strokeStyle = color
      for (const [side, alpha] of [['lit', bucket.alpha], ['dim', 0.05]]) {
        const pts = bucket[side]
        if (!pts.length) continue
        ctx.globalAlpha = alpha
        ctx.beginPath()
        for (let i = 0; i < pts.length; i += 4) {
          ctx.moveTo(pts[i], pts[i + 1])
          ctx.lineTo(pts[i + 2], pts[i + 3])
        }
        ctx.stroke()
      }
    }
    ctx.setLineDash([])
    if (arrows.length) {
      ctx.globalAlpha = 0.7
      ctx.fillStyle = pal.edge
      const size = 4.2 / k
      for (let i = 0; i < arrows.length; i += 2) {
        const a = arrows[i]
        const b = arrows[i + 1]
        const d = Math.hypot(b.x - a.x, b.y - a.y) || 1
        const ux = (b.x - a.x) / d
        const uy = (b.y - a.y) / d
        const tipX = b.x - ux * (b.r0 * p.nodeScale + 2 / k)
        const tipY = b.y - uy * (b.r0 * p.nodeScale + 2 / k)
        ctx.beginPath()
        ctx.moveTo(tipX, tipY)
        ctx.lineTo(tipX - ux * size - uy * size * 0.55,
                   tipY - uy * size + ux * size * 0.55)
        ctx.lineTo(tipX - ux * size + uy * size * 0.55,
                   tipY - uy * size - ux * size * 0.55)
        ctx.closePath()
        ctx.fill()
      }
    }
    ctx.globalAlpha = 1

    const now = performance.now()
    const replaying = replayRef.current.on
    const labelBase = 11 / k
    ctx.font = `${labelBase}px ui-sans-serif, system-ui, sans-serif`
    ctx.textAlign = 'center'
    for (const n of nodes) {
      if (!n.on || !inView(n)) continue
      const dim = near && !near.has(n.id)
      // A newborn eases in over a third of a second — visible growth, not a
      // teleport. Outside replay `bornAt` is 0 and pop is 1.
      const pop = replaying && n.bornAt
        ? Math.min(1, (now - n.bornAt) / 350) : 1
      const r = n.r0 * p.nodeScale * (0.4 + 0.6 * pop)
      if (p.heatOn && n.heat > 0.05 && !dim) {
        const glow = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, r * 3.6)
        glow.addColorStop(0, pal.shortcut.replace(')', ` / ${0.34 * n.heat})`)
          .replace('rgb(', 'rgba('))
        glow.addColorStop(1, pal.shortcut.replace(')', ' / 0)')
          .replace('rgb(', 'rgba('))
        ctx.fillStyle = glow
        ctx.beginPath()
        ctx.arc(n.x, n.y, r * 3.6, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.globalAlpha = dim ? 0.14 : pop
      ctx.fillStyle = n.color
      ctx.beginPath()
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2)
      ctx.fill()
      if (n.id === sel) {
        ctx.strokeStyle = pal.accent
        ctx.lineWidth = 1.8 / k
        ctx.beginPath()
        ctx.arc(n.x, n.y, r + 3.5, 0, Math.PI * 2)
        ctx.stroke()
      }
      if (!dim) {
        // Labels arrive with zoom (the display slider says how eagerly) and
        // hubs earn theirs a little sooner; focus is always named.
        const kNeeded = 0.35 + p.labels * 2.4 - Math.min(0.5, n.degree * 0.03)
        const a = (n.id === sel || n.matched || (focus && near.has(n.id)))
          ? 1 : Math.max(0, Math.min(1, (k - kNeeded) * 3))
        if (a > 0.02) {
          ctx.globalAlpha = a * 0.9
          ctx.fillStyle = pal.text
          ctx.fillText(n.label, n.x, n.y + r + labelBase + 1 / k)
        }
      }
      ctx.globalAlpha = 1
    }
    ctx.textAlign = 'start'
  }, [data, links])

  useEffect(() => {
    drawRef.current = draw
    needsDraw.current = true
  }, [draw])

  /* One loop for the life of the view. It steps while there is energy and
     stops when the forest settles (J.5.4 v0.38) — no drift, no trembling:
     a map at rest holds still, and an idle frame costs nothing. */
  useEffect(() => {
    if (calm) return undefined
    let running = true
    let last = performance.now()
    const tick = (now) => {
      if (!running) return
      const el = canvas.current
      const s = sim.current
      const dt = Math.min(64, now - last)
      last = now
      if (el && s.nodes.length) {
        const r = replayRef.current
        if (r.on && r.playing) {
          const total = Math.max(6000, Math.min(30000, s.nodes.length * 14))
          const nextT = r.t + (dt / total) * s.nodes.length
          if (nextT >= s.nodes.length) {
            setReplay({ on: true, playing: false, t: s.nodes.length })
          } else {
            setReplay({ on: true, playing: true, t: nextT })
          }
          fit(0.05) // the camera pulls back as the forest grows
        }
        if (s.active) {
          step(s, el.clientWidth, el.clientHeight, paramsRef.current)
          if (!s.fitted && s.alpha < 0.35) { s.fitted = true; fit() }
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
  }, [calm, fit])

  /* Under reduced motion there is no loop: paint when something changed. */
  useEffect(() => { if (calm) drawRef.current() })

  useEffect(() => {
    const el = box.current
    if (!el || typeof ResizeObserver !== 'function') return undefined
    const ro = new ResizeObserver(() => {
      needsDraw.current = true
      if (calm) drawRef.current()
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [calm])

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
      if (!n.on) continue
      const d = Math.hypot(n.x - p.x, n.y - p.y)
      if (d < bd) { bd = d; best = n }
    }
    return best
  }

  const drag = useRef(null)
  const origin = useRef(null)   // where the gesture began, for click detection
  const panLast = useRef(null)  // last position while panning
  const pointers = useRef(new Map())
  const pinch = useRef(null)
  const pinched = useRef(false) // a pinch is never a click, even at 4px

  function down(ev) {
    pointers.current.set(ev.pointerId, { x: ev.clientX, y: ev.clientY })
    ev.currentTarget.setPointerCapture(ev.pointerId)
    if (pointers.current.size === 2) {
      // A second finger turns any gesture into a pinch: drop the node.
      if (drag.current) { drag.current.fx = null; drag.current.fy = null }
      drag.current = null
      panLast.current = null
      pinched.current = true
      const [a, b] = [...pointers.current.values()]
      pinch.current = { d: Math.hypot(a.x - b.x, a.y - b.y),
                       mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 }
      return
    }
    pinched.current = false
    const n = nodeAt(at(ev))
    if (n) {
      drag.current = n
      n.fx = n.x; n.fy = n.y
      // The d3 drag pattern: hold some energy while the hand is down, so
      // the neighbourhood follows fluidly instead of snapping after.
      const s = sim.current
      s.alphaTarget = Math.max(s.alphaTarget, 0.3)
      s.alpha = Math.max(s.alpha, 0.3)
      s.active = true
    } else {
      panLast.current = { x: ev.clientX, y: ev.clientY }
    }
    origin.current = { x: ev.clientX, y: ev.clientY }
    ev.currentTarget.dataset.dragging = 'true'
  }
  function move(ev) {
    if (pointers.current.has(ev.pointerId)) {
      pointers.current.set(ev.pointerId, { x: ev.clientX, y: ev.clientY })
    }
    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      const d = Math.hypot(a.x - b.x, a.y - b.y) || 1
      const mx = (a.x + b.x) / 2
      const my = (a.y + b.y) / 2
      const r = canvas.current.getBoundingClientRect()
      const v = view.current
      const k = Math.max(0.12, Math.min(4, v.k * (d / pinch.current.d)))
      const px = mx - r.left
      const py = my - r.top
      v.x = px - (px - v.x) * (k / v.k) + (mx - pinch.current.mx)
      v.y = py - (py - v.y) * (k / v.k) + (my - pinch.current.my)
      v.k = k
      pinch.current = { d, mx, my }
      needsDraw.current = true
      if (calm) drawRef.current()
      return
    }
    if (drag.current) {
      const p = at(ev)
      drag.current.fx = p.x
      drag.current.fy = p.y
      sim.current.active = true
      needsDraw.current = true
      if (calm) { drag.current.x = p.x; drag.current.y = p.y; drawRef.current() }
      return
    }
    if (panLast.current) {
      view.current.x += ev.clientX - panLast.current.x
      view.current.y += ev.clientY - panLast.current.y
      panLast.current = { x: ev.clientX, y: ev.clientY }
      needsDraw.current = true
      if (calm) drawRef.current()
      return
    }
    const n = nodeAt(at(ev))
    if ((n?.id || null) !== hover) setHover(n?.id || null)
  }
  function up(ev) {
    pointers.current.delete(ev.pointerId)
    if (pointers.current.size < 2) pinch.current = null
    // A drag that ends where it started is a click. Four pixels of slack,
    // because a trackpad rarely lets go without moving a little.
    const from = origin.current
    if (from && !pinched.current
        && Math.hypot(ev.clientX - from.x, ev.clientY - from.y) <= 4) {
      const n = drag.current || nodeAt(at(ev))
      // Clicking the forest floor clears the selection: the way back to
      // full colour must be as easy as the way in.
      onSelect?.(n ? n.id : null)
    }
    if (drag.current) { drag.current.fx = null; drag.current.fy = null }
    drag.current = null
    panLast.current = null
    if (pointers.current.size === 0) {
      origin.current = null
      pinched.current = false
    }
    sim.current.alphaTarget = replayRef.current.playing ? 0.13 : 0
    ev.currentTarget.dataset.dragging = 'false'
  }
  function wheel(ev) {
    ev.preventDefault()
    const r = canvas.current.getBoundingClientRect()
    const mx = ev.clientX - r.left
    const my = ev.clientY - r.top
    const f = ev.deltaY < 0 ? 1.15 : 1 / 1.15
    const v = view.current
    const k = Math.max(0.12, Math.min(4, v.k * f))
    v.x = mx - (mx - v.x) * (k / v.k)
    v.y = my - (my - v.y) * (k / v.k)
    v.k = k
    needsDraw.current = true
    if (calm) drawRef.current()
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
  const s = sim.current
  const bornCount = Math.min(s.nodes.length, Math.floor(replay.t))
  const newest = replay.on && bornCount > 0
    ? s.nodes[s.order[bornCount - 1]] : null
  const toggleIn = (key, value) => set({
    [key]: settings[key].includes(value)
      ? settings[key].filter((x) => x !== value)
      : [...settings[key], value],
  })

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-3 py-2">
        <button type="button" aria-pressed={replay.on}
                className={`badge transition ${replay.on ? 'badge-accent' : ''}`}
                onClick={() => (replay.on ? exitReplay() : enterReplay())}>
          <Play size={12} /> {t('graph.live')}
        </button>
        <label className="relative min-w-0 max-w-xs flex-1">
          <Search size={14} className="pointer-events-none absolute left-2.5
                                       top-1/2 -translate-y-1/2 text-text-3" />
          <input className="field h-8 pl-8 text-[12.5px]" value={settings.query}
                 placeholder={t('graph.search_ph')}
                 onChange={(ev) => set({ query: ev.target.value })} />
        </label>
        <span className="flex-1" />
        <button type="button" className="btn btn-sm btn-ghost"
                onClick={() => {
                  const el = canvas.current
                  const st = sim.current
                  if (!el || !st.nodes.length) return
                  seed(st, el.clientWidth, el.clientHeight)
                  st.alpha = 1
                  st.alphaTarget = 0
                  st.active = true
                  st.fitted = false
                  if (calm) { settle(400); st.fitted = true; fit() }
                  needsDraw.current = true
                }}
                title={t('graph.reorganize')}>
          <Refresh size={14} /> {t('graph.reorganize')}
        </button>
        <button type="button" aria-pressed={panel}
                className={`btn btn-sm ${panel ? '' : 'btn-ghost'}`}
                onClick={() => setPanel(!panel)}>
          <Sliders size={14} /> {t('graph.view')}
        </button>
      </div>

      <div ref={box} className="relative">
        <canvas ref={canvas} className="graph-canvas h-[clamp(360px,58vh,640px)]"
                onPointerDown={down} onPointerMove={move} onPointerUp={up}
                onPointerCancel={up}
                onPointerLeave={() => setHover(null)} />

        {hovered && !panel && (
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

        {panel && (
          <ViewPanel t={t} settings={settings} set={set} types={types}
                     typeCounts={typeCounts} groups={groups} palette={palette}
                     toggleIn={toggleIn} onClose={() => setPanel(false)}
                     onReset={() => set({ ...DEFAULTS })} />
        )}

        {replay.on && (
          <div className="absolute inset-x-3 bottom-3 flex items-center gap-2
                          rounded-lg border border-line bg-bg-elev/95 px-3 py-2
                          shadow-pop backdrop-blur">
            {!calm && (
              <button type="button" className="btn btn-sm"
                      onClick={() => setReplay((r) => ({
                        ...r,
                        playing: !r.playing,
                        t: !r.playing && r.t >= s.nodes.length ? 0 : r.t,
                      }))}
                      aria-label={replay.playing ? t('graph.pause') : t('graph.play')}>
                {replay.playing ? <Pause size={13} /> : <Play size={13} />}
              </button>
            )}
            <input type="range" className="graph-range flex-1" min={0}
                   max={s.nodes.length} step={1} value={bornCount}
                   onChange={(ev) => setReplay((r) => ({
                     ...r, playing: false, t: Number(ev.target.value),
                   }))} />
            <span className="min-w-[9.5rem] text-right font-mono text-[11px] text-text-3">
              {(newest?.created || newest?.updated || '—')} · {bornCount}/{s.nodes.length}
            </span>
            <button type="button" className="btn btn-sm btn-ghost"
                    onClick={exitReplay} aria-label={t('graph.close')}>
              <X size={13} />
            </button>
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

/* -- the view panel (J.5.4 v0.38) ---------------------------------------- */

function ViewPanel({ t, settings, set, types, typeCounts, groups, palette,
                     toggleIn, onClose, onReset }) {
  return (
    <div className="absolute bottom-3 right-3 top-3 flex w-[17.5rem] flex-col
                    rounded-lg border border-line bg-bg-elev/95 shadow-pop
                    backdrop-blur">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <Sliders size={14} className="text-text-3" />
        <span className="text-[13px] font-medium text-text">{t('graph.view')}</span>
        <span className="flex-1" />
        <button type="button" className="btn btn-sm btn-ghost" onClick={onReset}
                title={t('graph.reset_view')}>
          <Refresh size={12} />
        </button>
        <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}
                aria-label={t('graph.close')}>
          <X size={13} />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
        <Section title={t('graph.filters')} defaultOpen>
          <div className="flex flex-wrap gap-1.5">
            {types.map((type) => (
              <button key={type} type="button"
                      onClick={() => toggleIn('hiddenTypes', type)}
                      aria-pressed={!settings.hiddenTypes.includes(type)}
                      className={`badge transition ${settings.hiddenTypes.includes(type) ? 'opacity-40' : ''}`}>
                <span className="tree-dot"
                      style={{ background: palette.byType[type] || palette.other }} />
                {type}
                <span className="text-text-3">{typeCounts[type]}</span>
              </button>
            ))}
          </div>
          <div className="mt-2 space-y-1.5">
            <Toggle checked={settings.orphans} label={t('graph.orphans')}
                    onChange={(on) => set({ orphans: on })} />
            <Toggle checked={settings.heatOn} label={t('graph.heat')}
                    onChange={(on) => set({ heatOn: on })} />
            <Toggle checked={settings.proposals} label={t('graph.proposals')}
                    onChange={(on) => set({ proposals: on })} />
            <Toggle checked={settings.shortcuts} label={t('graph.shortcuts')}
                    onChange={(on) => set({ shortcuts: on })} />
            <Toggle checked={settings.structure} label={t('graph.structure')}
                    onChange={(on) => set({ structure: on })} />
          </div>
        </Section>

        <Section title={t('graph.groups')} defaultOpen>
          <div className="segment mb-2 w-full">
            <button type="button" aria-pressed={settings.colorBy === 'branch'}
                    className="flex-1"
                    onClick={() => set({ colorBy: 'branch' })}>
              {t('graph.color_by_branch')}
            </button>
            <button type="button" aria-pressed={settings.colorBy === 'type'}
                    className="flex-1"
                    onClick={() => set({ colorBy: 'type' })}>
              {t('graph.color_by_type')}
            </button>
          </div>
          {settings.colorBy === 'branch' && (
            <>
              <Range label={t('graph.group_depth')} min={1} max={3} step={1}
                     value={settings.groupDepth} display={String(settings.groupDepth)}
                     onChange={(depth) => set({ groupDepth: depth, hiddenGroups: [] })} />
              <div className="mt-1.5 flex max-h-44 flex-wrap gap-1.5 overflow-y-auto">
                {groups.keys.map((key) => (
                  <button key={key} type="button"
                          onClick={() => toggleIn('hiddenGroups', key)}
                          aria-pressed={!settings.hiddenGroups.includes(key)}
                          className={`badge max-w-full transition ${settings.hiddenGroups.includes(key) ? 'opacity-40' : ''}`}>
                    <span className="tree-dot"
                          style={{ background: groups.colors[key] || palette.other }} />
                    <span className="truncate font-mono text-[10.5px]">{key}</span>
                    <span className="text-text-3">{groups.counts.get(key)}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </Section>

        <Section title={t('graph.display')}>
          <Toggle checked={settings.arrows} label={t('graph.arrows')}
                  onChange={(on) => set({ arrows: on })} />
          <Range label={t('graph.text_threshold')} min={0} max={1} step={0.05}
                 value={settings.labels}
                 onChange={(labels) => set({ labels })} />
          <Range label={t('graph.node_size')} min={0.4} max={2.2} step={0.1}
                 value={settings.nodeScale}
                 onChange={(nodeScale) => set({ nodeScale })} />
          <Range label={t('graph.link_width')} min={0.3} max={3} step={0.1}
                 value={settings.linkWidth}
                 onChange={(linkWidth) => set({ linkWidth })} />
        </Section>

        <Section title={t('graph.forces')}>
          <Range label={t('graph.force_center')} min={0} max={2} step={0.05}
                 value={settings.center} onChange={(center) => set({ center })} />
          <Range label={t('graph.force_repel')} min={0} max={2.5} step={0.05}
                 value={settings.repel} onChange={(repel) => set({ repel })} />
          <Range label={t('graph.force_link')} min={0} max={2} step={0.05}
                 value={settings.attract} onChange={(attract) => set({ attract })} />
          <Range label={t('graph.force_distance')} min={0.4} max={2.5} step={0.05}
                 value={settings.distance} onChange={(distance) => set({ distance })} />
        </Section>
      </div>
    </div>
  )
}

function Section({ title, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-lg">
      <button type="button" onClick={() => setOpen(!open)}
              className="flex w-full items-center gap-1.5 rounded-lg px-1.5 py-1.5
                         text-[12.5px] font-medium text-text-2 transition
                         hover:bg-surface-2">
        <ChevronDown size={13}
                     className={`transition-transform ${open ? '' : '-rotate-90'}`} />
        {title}
      </button>
      {open && <div className="px-1.5 pb-2 pt-1">{children}</div>}
    </div>
  )
}

function Range({ label, value, onChange, min, max, step, display }) {
  return (
    <label className="mt-2 block first:mt-0">
      <span className="flex items-center justify-between text-[11.5px] text-text-3">
        {label}
        <span className="font-mono">{display ?? value.toFixed(2).replace(/\.?0+$/, '')}</span>
      </span>
      <input type="range" className="graph-range mt-1 w-full" min={min} max={max}
             step={step} value={value}
             onChange={(ev) => onChange(Number(ev.target.value))} />
    </label>
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
