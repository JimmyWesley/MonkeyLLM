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
import {
  Badge, Card, CopyButton, Empty, ErrorNote, Field, Select, Spinner,
} from '../design/ui.jsx'
import { Markdown } from '../design/markdown.jsx'
import {
  Book, Compass, Download, Search, Share, Trash, X,
} from '../design/icons.jsx'

export default function Read({ forest, grant, node, setNode, goto }) {
  const { t } = useI18n()
  if (!node) {
    return <Finder forest={forest} onOpen={setNode} />
  }
  return <Document key={`${forest}:${node}`} forest={forest} grant={grant}
                   node={node} setNode={setNode} goto={goto} />
}

/** No selection: find the document to read. A thin `locate` — the full
 *  instrument lives in Explore; this is only the way to a page. */
function Finder({ forest, onOpen }) {
  const { t } = useI18n()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const search = async (e) => {
    e?.preventDefault()
    if (!q.trim()) return
    setBusy(true); setError(null)
    try {
      const r = await api.call(forest, 'locate', { query: q, k: 8 })
      setHits(r.results || [])
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  return (
    <Card title={t('read.title')} icon={Book}>
      <p className="mb-3 text-[12.5px] text-text-3">{t('read.finder_hint')}</p>
      <form onSubmit={search} className="flex gap-2">
        <input className="input flex-1" value={q} placeholder={t('read.finder_placeholder')}
               onChange={(e) => setQ(e.target.value)} />
        <button className="btn btn-primary" type="submit" disabled={busy || !q.trim()}>
          <Search size={14} /> {t('common.search')}
        </button>
      </form>
      {error && <div className="mt-3"><ErrorNote error={error} /></div>}
      {busy && <div className="mt-4"><Spinner label={t('common.loading')} /></div>}
      {hits && !busy && (hits.length ? (
        <ul className="mt-4 space-y-1">
          {hits.map((h) => (
            <li key={h.id}>
              <button className="w-full rounded-lg px-3 py-2 text-left hover:bg-surface-2"
                      onClick={() => onOpen(h.id)}>
                <span className="block text-[13px] font-medium text-text">{h.title}</span>
                <span className="block truncate text-[12px] text-text-3">{h.summary}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-4"><Empty title={t('read.finder_empty')} icon={Search} /></div>
      ))}
    </Card>
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
        <Field label={t('read.share_days')} className="flex-1">
          <Select value={days} onChange={(e) => setDays(e.target.value)}>
            <option value="7">{t('read.days_7')}</option>
            <option value="30">{t('read.days_30')}</option>
            <option value="90">{t('read.days_90')}</option>
          </Select>
        </Field>
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
