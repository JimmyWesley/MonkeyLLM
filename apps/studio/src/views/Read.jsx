// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The reading console (spec J.5.14).
 *
 * Every other console is an instrument; this page SHOWS a document to a
 * person. The body arrives whole through the J.14.1 export — never through
 * `pick`, whose ceiling protects a model's context window, not a reader
 * scrolling — and renders through the same markdown pipeline as model
 * output (untrusted by the product's own premise, J.5.13). The outline is
 * the sidebar; the raw markdown is one click away; and the share link
 * (J.17) is minted here, because "hand this to somebody" is a reading-page
 * act.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { fmtMs, has, nodeLink, rootsOf } from './shared.jsx'
import NodeHands from './hands.jsx'
import { ScentEditor } from './editor.jsx'
import { BulkTags, TagVocabulary, browseTag } from './tags.jsx'
import {
  Badge, Card, CopyButton, Empty, ErrorNote, Select, Spinner,
} from '../design/ui.jsx'
import { Markdown } from '../design/markdown.jsx'
import {
  Book, Compass, Download, Pencil, Search, Share, Tag, Trash, X,
} from '../design/icons.jsx'

export default function Read({ forest, grant, node, setNode, goto }) {
  if (!node) {
    return <Finder key={forest} forest={forest} grant={grant} />
  }
  return <Document key={`${forest}:${node}`} forest={forest} grant={grant}
                   node={node} setNode={setNode} goto={goto} />
}

/** The one call this page makes returns at most a budget's worth of entries
 *  (C.6): asking for more than fits changes nothing, so the page size and
 *  the ask are the same number. */
const PAGE = 10

/** No selection: find the document to read.
 *
 *  Shaped like a search engine and not like a form, because that is what a
 *  person opening this console is doing. Three things follow from that:
 *
 *  1. **The result is a link.** A real `href` through the router's own
 *     helper, so middle click, "copy link" and the status bar all work — a
 *     list of buttons looks the same and answers none of those.
 *  2. **The clock is the engine's** (J.10.6). `Server-Timing: vine` is the
 *     forest's own figure; the round trip is the internet's and rides in the
 *     tooltip, never in the headline. When the header is absent — an older
 *     Station, a proxy that dropped it — the line simply carries no time,
 *     because printing the stopwatch there would be the exact claim J.10.6
 *     forbids.
 *  3. **The page is one page.** `locate` answers within a token budget
 *     (C.6, 800) and has no cursor, so ~10 entries is the whole of what one
 *     call can return: there is no page two to offer. When the budget cut
 *     the list, the line SAYS there are more rather than implying the
 *     forest holds ten.
 *
 *  A thin `locate` on purpose — it searches curated metadata and never the
 *  bodies (C.6b), so the empty state names the search it did not do and
 *  points at Explore, which runs both halves. The full instrument lives
 *  there; this is only the way to a page.
 */
function Finder({ forest, grant }) {
  const { t } = useI18n()
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  // J.5.18 rule 4: the tag the listing is filtered by, when the listing came
  // from the vocabulary rather than from the search box. Two ways in, one
  // list out — and only one of them can be active, because a result set that
  // is both a search and a filter would be neither.
  const [tag, setTag] = useState(null)
  // rules 2/3: the selection, in the order the list shows it. Ids, never
  // objects — a node re-read after a write must not have two copies here.
  const [picked, setPicked] = useState([])
  // What a bulk write invalidates: the counts in the vocabulary, and the
  // tags on the rows. Bumped once, at the end of a run.
  const [version, setVersion] = useState(0)

  const writes = has(grant, 'write')
  const roots = rootsOf(grant)

  // `override` is how a re-read after a bulk write repeats the SAME search:
  // `q` is state and a handler closing over it would repeat whatever was in
  // the box at the time the closure was made, which is not the question the
  // listing on screen answers.
  const search = async (e, override, { keep = false } = {}) => {
    e?.preventDefault()
    const query = String(override ?? q).trim()
    if (!query) return
    setBusy(true); setError(null); setTag(null)
    // A NEW question drops the selection; a re-read of the SAME one keeps
    // it, because the run's report is attached to it — and rule 2's whole
    // point is that a partial run is read, not swept off screen by the
    // refresh that follows it.
    if (!keep) setPicked([])
    const t0 = performance.now()
    try {
      const { data, timing } = await api.timedCall(
        forest, 'locate', { query, k: PAGE })
      setRes({
        query,
        hits: data.results || [],
        truncated: !!data.truncated,
        // C.1.1: what an empty read owes its caller — how large the space
        // was. Present only on the empty path, which is the only place the
        // console has a use for it.
        searched: data.searched ?? null,
        engine: timing?.vine ?? null,
        wall: performance.now() - t0,
      })
    } catch (err) { setError(err); setRes(null) } finally { setBusy(false) }
  }

  /* J.5.18 rule 4: clicking a tag filters the forest by it.
   *
   * Through `scan` with `filter: {tags_any: [tag]}` and not through a
   * `locate` of the word: `locate` would RANK the tag among titles,
   * summaries and aliases, and a document that merely mentions it would
   * arrive beside the ones that carry it. The vocabulary's count is an
   * exact count of the column, so the listing under it has to be the same
   * question — or the panel would say 41 and the page would show 47.
   */
  const browse = async (next, { keep = false } = {}) => {
    setBusy(true); setError(null); setQ(''); setTag(next)
    if (!keep) setPicked([])
    const t0 = performance.now()
    try {
      const page = await browseTag(forest, roots, next)
      setRes({
        tag: next,
        hits: page.hits,
        total: page.total,
        truncated: page.truncated,
        searched: null,
        // No engine figure here: this is several `scan` calls, and printing
        // one call's `Server-Timing` as the cost of the listing would be the
        // claim J.10.6 forbids. Absent is the honest answer.
        engine: null,
        wall: performance.now() - t0,
      })
    } catch (err) { setError(err); setRes(null) } finally { setBusy(false) }
  }

  /** After N commits, what is on screen is behind: the row's tags and the
   *  vocabulary's counts both moved. Re-read rather than patch a local copy
   *  — the engine's answer is the one that is true.
   *
   *  The selection survives it. The run's account — how many landed, which
   *  node refused and why — lives beside the selection, so clearing it here
   *  would delete the report at the exact moment it says something (J.5.18
   *  rule 2). The operator drops it themselves, with Deselect. */
  const refresh = () => {
    setVersion((v) => v + 1)
    if (tag) browse(tag, { keep: true })
    else if (res?.query) search(null, res.query, { keep: true })
  }

  const toggle = (id) => setPicked((prev) => (
    prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const box = (
    <SearchBox q={q} setQ={setQ} onSubmit={search} busy={busy}
               placeholder={t('read.finder_placeholder')}
               label={t('common.search')} />
  )

  const vocabulary = (
    <TagVocabulary key={`${forest}:${version}`} forest={forest} active={tag}
                   onPick={browse} onClear={() => { setTag(null); setRes(null) }} />
  )

  // Nothing asked yet: the whole page is the question — and, under it, the
  // vocabulary, which is the other way in (J.5.18 rule 4): somebody who
  // does not know what to search for can read what the forest is tagged by.
  if (!res && !error) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-[6vh]">
        <div className="text-center">
          <span className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl
                           bg-surface-2 text-text-3"><Book size={22} /></span>
          <h1 className="text-[19px] font-medium text-text">{t('read.title')}</h1>
          <p className="mx-auto mt-1 max-w-[46ch] text-[12.5px] text-text-3">
            {t('read.finder_hint')}
          </p>
          <div className="mt-6">{box}</div>
        </div>
        <div className="mt-8">{vocabulary}</div>
      </div>
    )
  }

  const shown = res?.hits || []
  const allPicked = shown.length > 0 && shown.every((h) => picked.includes(h.id))

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        <div className="max-w-2xl">{box}</div>
        {error && <div className="mt-4"><ErrorNote error={error} /></div>}
        {busy && <div className="mt-6"><Spinner label={t('common.loading')} /></div>}
        {res && !busy && (shown.length ? (
          <>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
              <Stats res={res} />
              {writes && (
                <button type="button" className="btn btn-sm"
                        onClick={() => setPicked(allPicked ? []
                          : shown.map((h) => h.id))}>
                  {allPicked ? t('tags.select_none') : t('tags.select_all')}
                </button>
              )}
            </div>
            {res.tag && (
              <p className="mt-1 flex items-center gap-1.5 text-[12px] text-text-3">
                <Tag size={12} /> {t('tags.filtered_by', { tag: res.tag })}
              </p>
            )}
            <ol className="mt-4 space-y-6">
              {shown.map((h) => (
                <Hit key={h.id} forest={forest} hit={h}
                     selectable={writes} picked={picked.includes(h.id)}
                     onPick={() => toggle(h.id)} />
              ))}
            </ol>
            {res.truncated && (
              <p className="mt-8 border-t border-line pt-4 text-[12.5px] text-text-3">
                {res.tag
                  ? t('tags.filter_more', { shown: shown.length, total: res.total })
                  : t('read.finder_more')}
              </p>
            )}
          </>
        ) : (
          <div className="mt-8">
            <Empty title={res.tag ? t('tags.filter_empty') : t('read.finder_empty')}
                   icon={res.tag ? Tag : Search}>
              <span className="mt-1 block text-[12px] text-text-3">
                {res.searched != null && `${t('read.finder_searched', { n: res.searched })} · `}
                {res.tag ? t('tags.filter_empty_hint') : t('read.finder_scent_only')}
              </span>
            </Empty>
          </div>
        ))}
      </div>

      <div className="space-y-4">
        {/* rules 2 and 3: the bulk write appears only when there is a
            selection to write to, and only for a grant that carries
            `write` — absent, never disabled (J.5.4). */}
        {writes && picked.length > 0 && (
          <BulkTags forest={forest} ids={picked} onDone={refresh}
                    onClear={() => setPicked([])} />
        )}
        {vocabulary}
      </div>
    </div>
  )
}

function SearchBox({ q, setQ, onSubmit, busy, placeholder, label }) {
  return (
    <form onSubmit={onSubmit} className="flex items-center gap-2">
      <label className="relative min-w-0 flex-1">
        <Search size={16} className="pointer-events-none absolute left-4 top-1/2
                                     -translate-y-1/2 text-text-3" />
        <input
          className="w-full rounded-full border border-line bg-surface-2 py-2.5 pl-11 pr-4
                     text-sm text-text shadow-card outline-none transition
                     placeholder:text-text-3 focus:border-accent focus:bg-surface
                     focus:ring-2 focus:ring-accent/20"
          value={q} placeholder={placeholder} autoFocus
          onChange={(e) => setQ(e.target.value)} />
      </label>
      <button className="btn btn-primary rounded-full px-4" type="submit"
              disabled={busy || !q.trim()}>
        <Search size={14} /> {label}
      </button>
    </form>
  )
}

/** How many, and whose clock said how fast. */
function Stats({ res }) {
  const { t } = useI18n()
  const n = res.hits.length
  return (
    <p className="text-[12px] text-text-3"
       title={t('read.finder_roundtrip', { ms: fmtMs(res.wall) })}>
      {n === 1 ? t('read.finder_found_one') : t('read.finder_found', { n })}
      {res.engine != null && ` · ${t('read.finder_time', { ms: fmtMs(res.engine) })}`}
    </p>
  )
}

/** One result. The address above, the title as the link, the summary below —
 *  the shape a person already knows how to read.
 *
 *  The checkbox is the bulk selection (J.5.18 rule 2) and it sits OUTSIDE
 *  the link: a row that is both a navigation and a selection makes one of
 *  the two an accident, so the box is its own target and the title is still
 *  a real `href`. It is absent without `write`, never disabled.
 */
function Hit({ forest, hit, selectable, picked, onPick }) {
  const { t } = useI18n()
  const crumbs = hit.id.replace(/\/_index$/, '').split('/')
  return (
    <li className="flex gap-3">
      {selectable && (
        <input type="checkbox" checked={!!picked} onChange={onPick}
               aria-label={t('tags.select_node', { id: hit.id })}
               className="mt-1.5 h-3.5 w-3.5 shrink-0 accent-current text-accent" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[11.5px] text-text-3">
          <span className="min-w-0 truncate">{crumbs.join(' › ')}</span>
          {hit.kind === 'branch' && <Badge>{t('read.finder_branch')}</Badge>}
        </div>
        <a {...nodeLink(forest, hit.id, 'read')}
           className="mt-0.5 block text-[16px] leading-snug text-accent hover:underline">
          {hit.title}
        </a>
        {hit.summary && (
          <p className="mt-1 max-w-[80ch] text-[13px] leading-relaxed text-text-2">
            {hit.summary}
          </p>
        )}
        {!!hit.tags?.length && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {hit.tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}
          </div>
        )}
      </div>
    </li>
  )
}

function Document({ forest, grant, node, setNode, goto }) {
  const { t } = useI18n()
  const [digest, setDigest] = useState(null)
  const [raw, setRaw] = useState(null)
  const [error, setError] = useState(null)
  // J.5.18 rule 1: the scent is editable where it is read. Closed by
  // default — this is a reading page, and the editor is what a reader
  // reaches for when they notice something wrong, not what they came for.
  const [editing, setEditing] = useState(false)
  const [version, setVersion] = useState(0)
  const bodyHost = useRef(null)

  useEffect(() => {
    let live = true
    setDigest(null); setRaw(null); setError(null)
    Promise.all([
      api.call(forest, 'look', { id: node }),
      api.exportNode(forest, node),
    ]).then(([d, text]) => {
      if (!live) return
      if (d?.error) { setError(d.error); return }
      setDigest(d); setRaw(text)
    }).catch((e) => { if (live) setError(e) })
    return () => { live = false }
    // `version` is the re-read after a scent commit: the passport changed,
    // so the digest AND the export text are both behind. Re-read rather
    // than patch the local copy — the engine may have stored something
    // other than what was sent, and the next patch has to diff against
    // what is actually there.
  }, [forest, node, version])

  // The export is frontmatter + body (J.14.1); the page renders the body
  // and keeps the full text for copy/download — fidelity where it counts.
  const body = useMemo(
    () => (raw == null ? null : raw.replace(/^---\n[\s\S]*?\n---\n/, '')),
    [raw])

  const jump = (header) => {
    const host = bodyHost.current
    if (!host) return
    const target = [...host.querySelectorAll('h1,h2,h3,h4,h5,h6')]
      .find((h) => h.textContent.trim() === String(header).trim())
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const download = () => {
    const url = URL.createObjectURL(
      new Blob([raw || ''], { type: 'text/markdown;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${node.split('/').pop() || 'node'}.md`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  }

  if (error) return <ErrorNote error={error} />
  if (!digest || raw == null) return <Spinner label={t('common.loading')} />

  const outline = digest.outline || []
  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <div className="min-w-0 flex-1 space-y-4">
        {editing && (
          <ScentEditor forest={forest} grant={grant} id={node} digest={digest}
                       onSaved={() => setVersion((v) => v + 1)} />
        )}
        <Card
          title={digest.title}
          icon={Book}
          subtitle={digest.summary}
          actions={(
            <div className="flex items-center gap-1.5">
              <CopyButton value={raw} label={t('read.copy_raw')} />
              <button className="btn btn-sm" onClick={download}>
                <Download size={13} /> {t('read.download')}
              </button>
              <button className="btn btn-sm" onClick={() => goto('explore', node)}>
                <Compass size={13} /> {t('read.in_explore')}
              </button>
              {/* J.5.18 rule 1: title, summary and tags, through the same
                  `graft` Explore's editor uses — a doorway, not a second
                  door. Gated on `write` and absent without it (J.5.4). */}
              {has(grant, 'write') && (
                <button className="btn btn-sm" aria-pressed={editing}
                        onClick={() => setEditing((v) => !v)}>
                  <Pencil size={13} /> {t('editor.scent')}
                </button>
              )}
              {/* J.5.17 rule 1: this console has a node as its subject, so
                  it offers the same two hands Explore does — and after
                  either act the selection leaves the address (rule 6),
                  which here means the finder rather than a document that
                  is gone. A move keeps a document open: it is the same
                  document, at the address it now has. */}
              <NodeHands forest={forest} grant={grant} id={node}
                         type={digest.type} title={digest.title}
                         onNavigate={(target) => setNode(target)}
                         onPruned={() => setNode(null)}
                         onMoved={(next) => setNode(next)} />
              <button className="btn btn-sm" onClick={() => setNode(null)}
                      title={t('read.close')}>
                <X size={13} />
              </button>
            </div>
          )}
        >
          <div ref={bodyHost} className="max-w-[76ch]">
            <Markdown media={{ forest }}>{body}</Markdown>
          </div>
        </Card>
      </div>
      <div className="w-full shrink-0 space-y-4 lg:w-72">
        {outline.length > 0 && (
          <Card title={t('read.outline')} bodyClass="p-2">
            <ul className="space-y-0.5">
              {outline.map((h) => (
                <li key={h}>
                  <button
                    className="w-full truncate rounded-md px-2 py-1 text-left text-[12.5px]
                               text-text-2 hover:bg-surface-2 hover:text-text"
                    onClick={() => jump(h)}>
                    {h}
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        )}
        <SharePanel forest={forest} node={node} grant={grant} />
        <Card bodyClass="p-3">
          <dl className="space-y-1 text-[12px] text-text-3">
            <div className="flex justify-between gap-2">
              <dt>{t('read.node_id')}</dt>
              <dd className="truncate font-mono text-text-2">{node}</dd>
            </div>
            {digest.created && (
              <div className="flex justify-between gap-2">
                <dt>{t('read.created')}</dt><dd>{digest.created}</dd>
              </div>
            )}
            {digest.updated && (
              <div className="flex justify-between gap-2">
                <dt>{t('read.updated')}</dt><dd>{digest.updated}</dd>
              </div>
            )}
            {digest.source && (
              <div className="flex justify-between gap-2">
                <dt>{t('read.source')}</dt><dd>{digest.source}</dd>
              </div>
            )}
          </dl>
        </Card>
      </div>
    </div>
  )
}

/** The share panel (J.17): mint, list, revoke — for this node. The token
 *  appears exactly once, in the URL the create answers with; the listing
 *  never carries it, so a link not copied now is a link that needs a new
 *  share. */
function SharePanel({ forest, node }) {
  const { t } = useI18n()
  const [shares, setShares] = useState([])
  const [days, setDays] = useState('7')
  const [minted, setMinted] = useState(null)   // {id, url, expires}
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const refresh = () => api.shares(forest)
    .then((r) => setShares((r.shares || []).filter((s) => s.node === node)))
    .catch(() => setShares([]))
  useEffect(() => { refresh() }, [forest, node]) // eslint-disable-line react-hooks/exhaustive-deps

  const mint = async () => {
    setBusy(true); setError(null)
    try {
      const r = await api.createShare(forest, node, Number(days))
      setMinted({ ...r, url: `${window.location.origin}${r.url}` })
      refresh()
    } catch (e) { setError(e) } finally { setBusy(false) }
  }

  const revoke = async (id) => {
    try {
      await api.revokeShare(forest, id)
      if (minted?.id === id) setMinted(null)
      refresh()
    } catch (e) { setError(e) }
  }

  return (
    <Card title={t('read.share_title')} icon={Share} bodyClass="p-3">
      <p className="mb-2 text-[12px] text-text-3">{t('read.share_hint')}</p>
      <div className="flex items-end gap-2">
        {/* The select carries its own label: wrapping it in a `Field` made
            React render an <input> with children, which is a hard throw
            (#137) — and with no boundary above it, that throw took the whole
            console down every time a document opened. */}
        <Select label={t('read.share_days')} className="flex-1"
                value={days} onChange={(e) => setDays(e.target.value)}>
          <option value="7">{t('read.days_7')}</option>
          <option value="30">{t('read.days_30')}</option>
          <option value="90">{t('read.days_90')}</option>
        </Select>
        <button className="btn btn-primary btn-sm" onClick={mint} disabled={busy}>
          <Share size={13} /> {t('read.share_create')}
        </button>
      </div>
      {error && <div className="mt-2"><ErrorNote error={error} /></div>}
      {minted && (
        <div className="mt-3 rounded-lg bg-surface-2 p-2">
          <p className="mb-1 text-[11.5px] text-text-3">{t('read.share_once')}</p>
          <div className="flex items-center gap-1.5">
            <code className="min-w-0 flex-1 truncate text-[11.5px]">{minted.url}</code>
            <CopyButton value={minted.url} />
          </div>
        </div>
      )}
      {shares.length > 0 && (
        <ul className="mt-3 space-y-1">
          {shares.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-2 text-[12px]">
              <span className="truncate text-text-2">
                <Badge>{s.id}</Badge>{' '}
                {t('read.share_expires', { date: String(s.expires).slice(0, 10) })}
              </span>
              <button className="btn btn-ghost btn-sm" onClick={() => revoke(s.id)}
                      title={t('read.share_revoke')}>
                <Trash size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
