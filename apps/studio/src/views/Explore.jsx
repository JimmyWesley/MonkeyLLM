// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useRouteState } from '../router.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Code, Empty, ErrorNote, Skeleton, Spinner,
} from '../design/ui.jsx'
import {
  ChevronRight, Explore as Tree, File, Files, Graph, Link, Pencil, Plus, Search,
} from '../design/icons.jsx'
import {
  Metric, NeedsCapability, NewBranch, branchOf, has, rootsOf, useAsync,
  useCrumbs, useForestTree,
} from './shared.jsx'
import ForestGraph from './graph.jsx'
import ForestFiles, { PayloadImage } from './files.jsx'
import NodeEditor from './editor.jsx'

/** One console, three ways of looking at the same forest (spec J.5.4).
 *
 *  The selection survives a mode change, deliberately: switching from the
 *  graph to the files is not a new question, it is the same node seen
 *  differently — so the file for the selected node is what opens.
 *
 *  Graph and files share one map projection (J.11). It is a single call for
 *  the whole region, so asking for it twice would be two copies of the same
 *  answer, and letting the tree mode pay for it would slow down the console
 *  a principal with a narrow scope actually uses.
 */
export default function Explore({ forest, grant, node, setNode, goto }) {
  const { t } = useI18n()
  // In the address, with the selection (J.5.8): "look at this node on the
  // graph" is a link, and a reload lands on the same view of the same node
  // rather than back at the default.
  const [mode, setMode] = useRouteState('mode', 'graph',
                                        { allow: ['graph', 'files', 'tree'] })
  const [editing, setEditing] = useState(null)

  const roots = rootsOf(grant)
  const current = node || roots[0]

  const map = useAsync(() => api.map(forest, 'graph'), [forest],
                       { skip: mode === 'tree' })

  useEffect(() => { setEditing(null) }, [forest])

  if (!has(grant, 'read')) {
    return <NeedsCapability message={t('access.needs_admin')} hint={t('cap.read')} />
  }

  if (editing) {
    return (
      <NodeEditor forest={forest} grant={grant} id={editing}
                  onClose={() => setEditing(null)}
                  onSaved={() => map.reload()} />
    )
  }

  // The map leads: the graph is what a person opens a forest to see, the
  // files are where they go to read, and the tree is the narrow-scope
  // fallback — still the only mode that never pays for the projection.
  const MODES = [
    ['graph', Graph, t('explore.mode_graph')],
    ['files', Files, t('explore.mode_files')],
    ['tree', Tree, t('explore.mode_tree')],
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="segment">
          {MODES.map(([value, Icon, label]) => (
            <button key={value} type="button" aria-pressed={mode === value}
                    onClick={() => setMode(value)}>
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>
        {node && (
          <span className="nodeid truncate text-[12px]">{node}</span>
        )}
        {has(grant, 'write') && node && mode !== 'tree' && (
          <button className="btn btn-sm ml-auto" onClick={() => setEditing(node)}>
            <Pencil size={13} /> {t('files.edit')}
          </button>
        )}
      </div>

      {mode === 'graph' && (
        <ForestGraph forest={forest} data={map.data} busy={map.busy}
                     error={map.error}
                     onReload={map.reload} selected={node} onSelect={setNode}
                     onOpen={(id) => { setNode(id); setMode('files') }} />
      )}

      {mode === 'files' && (
        <ForestFiles forest={forest} grant={grant} data={map.data}
                     busy={map.busy} selected={node} onSelect={setNode}
                     onEdit={has(grant, 'write') ? setEditing : null} />
      )}

      {mode === 'tree' && (
        <BrowseAndSearch forest={forest} grant={grant} current={current}
                         setNode={setNode} goto={goto} />
      )}
    </div>
  )
}

/** Browsing and searching were two consoles over one question — "where does
 *  this live" — so they are one console now: the tree on the left, what you
 *  found on the right, and a search box that fills the tree's place when it
 *  has something to say. */
function BrowseAndSearch({ forest, grant, current, setNode, goto }) {
  const { t } = useI18n()
  const [term, setTerm] = useState('')
  const [hits, setHits] = useState(null)
  const [searching, setSearching] = useState(false)
  // J.5.7: the tree is where the shape of the forest is visible, so it is
  // where an operator notices the branch that should exist and does not.
  const [makingBranch, setMakingBranch] = useState(false)
  const [branchParent, setBranchParent] = useState('_index')

  const tree = useForestTree(forest, grant, api.call)
  const digest = useAsync(() => api.call(forest, 'look', { id: current }),
                          [forest, current])

  async function search(e) {
    e?.preventDefault()
    if (!term.trim()) { setHits(null); return }
    setSearching(true)
    try {
      // Both halves of the C.6b split, because a person searching does not
      // know whether their words live in a summary or only in a body.
      const [loc, sn] = await Promise.all([
        api.call(forest, 'locate', { query: term, k: 8 }),
        api.call(forest, 'sniff', { terms: term.split(/[\s,]+/).filter(Boolean), k: 6 }),
      ])
      const seen = new Map()
      for (const r of loc.results || []) seen.set(r.id, { ...r, where: 'scent' })
      for (const r of sn.results || []) if (!seen.has(r.id)) seen.set(r.id, { ...r, where: 'body' })
      setHits([...seen.values()])
    } catch (err) { setHits({ error: err }) } finally { setSearching(false) }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={search} className="flex gap-2">
        <label className="relative min-w-0 flex-1">
          <Search size={16} className="pointer-events-none absolute left-3 top-1/2
                                       -translate-y-1/2 text-text-3" />
          <input className="field pl-9" value={term} placeholder={t('explore.find_ph')}
                 onChange={(e) => { setTerm(e.target.value); if (!e.target.value) setHits(null) }} />
        </label>
        <button className="btn btn-primary" disabled={searching || !term.trim()}>
          {searching ? t('common.loading') : t('common.search')}
        </button>
      </form>

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <div className="min-w-0">
          {hits ? (
            <Card title={t('common.results')} icon={Search} bodyClass="p-2">
              {hits.error ? <div className="p-3"><ErrorNote error={hits.error} /></div>
                : hits.length === 0 ? <Empty>{t('explore.no_hits')}</Empty> : (
                <ul className="space-y-0.5">
                  {hits.map((h) => (
                    <li key={h.id}>
                      <button onClick={() => setNode(h.id)}
                              className={`w-full rounded-lg px-2.5 py-2 text-left transition
                                hover:bg-surface-2 ${h.id === current ? 'bg-accent-soft' : ''}`}>
                        <span className="flex items-center gap-1.5">
                          <span className="nodeid truncate">{h.id}</span>
                          {h.where === 'body' && <Badge>{t('common.body')}</Badge>}
                        </span>
                        <span className="mt-0.5 block line-clamp-2 text-[12px] text-text-3">
                          {h.summary || h.snippet}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ) : (
            <Card title={t('explore.tree')} icon={Tree} bodyClass="p-2"
                  actions={has(grant, 'write') ? (
                    <button type="button" className="btn btn-sm"
                            onClick={() => {
                              // Whatever branch is open is the parent worth
                              // offering first; the dialog can still change it.
                              setBranchParent(
                                current?.endsWith('_index') ? current : '_index')
                              setMakingBranch(true)
                            }}>
                      <Plus size={13} /> {t('branch.new')}
                    </button>
                  ) : null}>
              {tree.busy ? <div className="p-3"><Skeleton rows={5} /></div>
                : tree.error ? <div className="p-3"><ErrorNote error={tree.error} /></div> : (
                <ul className="space-y-0.5">
                  {(tree.data?.branches || []).map((b) => {
                    const depth = branchOf(b.id).split('/').filter(Boolean).length
                    return (
                      <li key={b.id}>
                        <button onClick={() => setNode(b.id)}
                                style={{ paddingLeft: `${8 + depth * 12}px` }}
                                className={`flex w-full items-center gap-1.5 rounded-lg py-1.5 pr-2
                                  text-left text-[12.5px] transition hover:bg-surface-2
                                  ${b.id === current ? 'bg-accent-soft text-accent' : 'text-text-2'}`}>
                          <ChevronRight size={13} className="opacity-50" />
                          <span className="truncate">{branchOf(b.id).split('/').pop() || '/'}</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </Card>
          )}
        </div>

        <NodeDetail forest={forest} grant={grant} id={current} digest={digest}
                    setNode={setNode} goto={goto} />
      </div>

      <NewBranch
        forest={forest} call={api.call} t={t}
        open={makingBranch} onClose={() => setMakingBranch(false)}
        parents={[{ id: '_index' }, ...(tree.data?.branches || [])]}
        parent={branchParent} onParent={setBranchParent}
        // Opening what was just made: the operator asked for this branch to
        // exist, so the tree moves to it rather than leaving them to find it.
        onCreated={(id) => { tree.reload(); setNode(id) }} />
    </div>
  )
}

function NodeDetail({ forest, grant, id, digest, setNode, goto }) {
  const { t } = useI18n()
  const [body, setBody] = useState(null)
  const crumbs = useCrumbs(id, grant)
  const roots = rootsOf(grant)

  useEffect(() => { setBody(null) }, [id])

  async function read() {
    setBody('loading')
    try { setBody(await api.call(forest, 'pick', { id })) }
    catch (e) { setBody({ error: e }) }
  }

  if (digest.busy) return <Card><Skeleton rows={5} /></Card>
  if (digest.error) return <Card><ErrorNote error={digest.error} onRetry={digest.reload} /></Card>
  const d = digest.data
  if (!d) return null

  return (
    <div className="min-w-0 space-y-4">
      <nav className="flex flex-wrap items-center gap-1 text-[12px] text-text-3">
        {[...roots, ...crumbs.filter((c) => !roots.includes(c))].map((c, i) => (
          <span key={c} className="flex items-center gap-1">
            {i > 0 && <span className="text-line-strong">/</span>}
            <button onClick={() => setNode(c)}
                    className="rounded px-1 py-0.5 font-mono hover:text-accent">{c}</button>
          </span>
        ))}
      </nav>

      <Card title={d.title} subtitle={d.id} icon={File}
            actions={<>
              <Badge tone="accent">{d.type}</Badge>
              <button className="btn btn-sm" onClick={read}>{t('explore.read')}</button>
              {/* J.5.14 rule 5: reachable from where the document is found. */}
              {goto && (
                <button className="btn btn-sm" onClick={() => goto('read', d.id)}>
                  {t('explore.open_read')}
                </button>
              )}
            </>}>
        <p className="text-[14px] leading-relaxed text-text">{d.summary}</p>

        {/* The image the prose was written about, beside it (J.14). `look`
            carries no payload fields, so the component itself lets the
            served Content-Type decide — and declines an audio payload. */}
        {d.type === 'media' && (
          <div className="mt-4">
            <PayloadImage forest={forest} id={d.id} title={d.title} type={d.type} />
          </div>
        )}

        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric label={t('explore.degree')} value={d.stats?.degree ?? 0} />
          <Metric label={t('explore.heat')} value={d.stats?.heat ?? 0} />
          <Metric label={t('explore.tokens')} value={d.stats?.body_tokens ?? 0} />
          <Metric label={t('explore.updated')} value={d.updated || '—'} />
        </div>

        {d.coverage && (
          <p className="mt-3 text-[12px] text-text-3">
            <span className="font-medium">{t('explore.coverage')}:</span> {d.coverage}
          </p>
        )}

        {body && (
          <div className="mt-5">
            <div className="label">{t('common.body')}</div>
            {body === 'loading' ? <Spinner label={t('common.loading')} />
              : body.error ? <ErrorNote error={body.error} />
              : <Code max="28rem" lang="markdown">{body.body}</Code>}
          </div>
        )}
      </Card>

      {!!d.children?.length && (
        <Card title={t('explore.children')} icon={Tree}>
          <ul className="divide-y divide-line">
            {d.children.map((c) => (
              <li key={c.id} className="py-2.5 first:pt-0 last:pb-0">
                <button onClick={() => setNode(c.id)} className="nodeid hover:underline">
                  {c.id}
                </button>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-text-3">{c.summary}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {!!d.edges_out?.length && (
        <Card title={t('explore.edges')} subtitle={t('explore.edges_hint')} icon={Link}>
          <ul className="divide-y divide-line">
            {d.edges_out.map((e, i) => (
              <li key={i} className="py-2.5 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>{e.rel}</Badge>
                  <button onClick={() => setNode(e.target)} className="nodeid hover:underline">
                    {e.target}
                  </button>
                </div>
                <p className="mt-0.5 text-[12.5px] leading-relaxed text-text-3">
                  {e.target_summary}
                </p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {!d.children?.length && !d.edges_out?.length && (
        <Card><Empty icon={File}>{t('explore.leaf')}</Empty></Card>
      )}
    </div>
  )
}
