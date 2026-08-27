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
import { fmtMs, nodeLink } from './shared.jsx'
import {
  Badge, Card, CopyButton, Empty, ErrorNote, Select, Spinner,
} from '../design/ui.jsx'
import { Markdown } from '../design/markdown.jsx'
import {
  Book, Compass, Download, Search, Share, Trash, X,
} from '../design/icons.jsx'

export default function Read({ forest, grant, node, setNode, goto }) {
  if (!node) {
    return <Finder forest={forest} />
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
function Finder({ forest }) {
  const { t } = useI18n()
  const [q, setQ] = useState('')
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const search = async (e) => {
    e?.preventDefault()
    const query = q.trim()
    if (!query) return
    setBusy(true); setError(null)
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

  const box = (
    <SearchBox q={q} setQ={setQ} onSubmit={search} busy={busy}
               placeholder={t('read.finder_placeholder')}
               label={t('common.search')} />
  )

  // Nothing asked yet: the whole page is the question.
  if (!res && !error) {
    return (
      <div className="grid min-h-[56vh] place-items-center px-4">
        <div className="w-full max-w-2xl text-center">
          <span className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl
                           bg-surface-2 text-text-3"><Book size={22} /></span>
          <h1 className="text-[19px] font-medium text-text">{t('read.title')}</h1>
          <p className="mx-auto mt-1 max-w-[46ch] text-[12.5px] text-text-3">
            {t('read.finder_hint')}
          </p>
          <div className="mt-6">{box}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-3xl">
      <div className="max-w-2xl">{box}</div>
      {error && <div className="mt-4"><ErrorNote error={error} /></div>}
      {busy && <div className="mt-6"><Spinner label={t('common.loading')} /></div>}
      {res && !busy && (res.hits.length ? (
        <>
          <Stats res={res} />
          <ol className="mt-4 space-y-6">
            {res.hits.map((h) => <Hit key={h.id} forest={forest} hit={h} />)}
          </ol>
          {res.truncated && (
            <p className="mt-8 border-t border-line pt-4 text-[12.5px] text-text-3">
              {t('read.finder_more')}
            </p>
          )}
        </>
      ) : (
        <div className="mt-8">
          <Empty title={t('read.finder_empty')} icon={Search}>
            <span className="mt-1 block text-[12px] text-text-3">
              {res.searched != null && `${t('read.finder_searched', { n: res.searched })} · `}
              {t('read.finder_scent_only')}
            </span>
          </Empty>
        </div>
      ))}
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
    <p className="mt-5 text-[12px] text-text-3"
       title={t('read.finder_roundtrip', { ms: fmtMs(res.wall) })}>
      {n === 1 ? t('read.finder_found_one') : t('read.finder_found', { n })}
      {res.engine != null && ` · ${t('read.finder_time', { ms: fmtMs(res.engine) })}`}
    </p>
  )
}

/** One result. The address above, the title as the link, the summary below —
 *  the shape a person already knows how to read. */
function Hit({ forest, hit }) {
  const { t } = useI18n()
  const crumbs = hit.id.replace(/\/_index$/, '').split('/')
  return (
    <li>
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
    </li>
  )
}

function Document({ forest, grant, node, setNode, goto }) {
  const { t } = useI18n()
  const [digest, setDigest] = useState(null)
  const [raw, setRaw] = useState(null)
  const [error, setError] = useState(null)
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
  }, [forest, node])

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
      <div className="min-w-0 flex-1">
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
