// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The reading console in anonymous dress (spec J.17 rule 7).
 *
 * One document, no session: the token in the address is the whole
 * authority, re-checked server-side at every serve. No Studio chrome that
 * presumes an account, no link into the forest — the document ends at its
 * own edges. `media:` references render as their captions (J.10.9's
 * fallback): the token's scope is one node, not the images beside it.
 */
import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { Card, CopyButton, ErrorNote, Spinner } from '../design/ui.jsx'
import { Markdown } from '../design/markdown.jsx'
import { Book, Download } from '../design/icons.jsx'

export default function SharedRead({ token }) {
  const { t } = useI18n()
  const [doc, setDoc] = useState(null)
  const [error, setError] = useState(null)
  const bodyHost = useRef(null)

  useEffect(() => {
    let live = true
    api.sharedDocument(token)
      .then((d) => { if (live) setDoc(d) })
      .catch((e) => { if (live) setError(e) })
    return () => { live = false }
  }, [token])

  const jump = (header) => {
    const host = bodyHost.current
    if (!host) return
    const target = [...host.querySelectorAll('h1,h2,h3,h4,h5,h6')]
      .find((h) => h.textContent.trim() === String(header).trim())
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const download = () => {
    const url = URL.createObjectURL(
      new Blob([doc?.markdown || ''], { type: 'text/markdown;charset=utf-8' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${String(doc?.title || 'document').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'document'}.md`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  }

  return (
    <div className="mx-auto min-h-screen w-full max-w-5xl px-4 py-8">
      {error ? (
        <Card title={t('read.shared_gone')} icon={Book}>
          <ErrorNote error={error} />
        </Card>
      ) : !doc ? (
        <div className="grid min-h-[40vh] place-items-center">
          <Spinner label={t('common.loading')} size={18} />
        </div>
      ) : (
        <div className="flex flex-col gap-4 lg:flex-row">
          <div className="min-w-0 flex-1">
            <Card
              title={doc.title}
              icon={Book}
              subtitle={t('read.shared_expires', { date: String(doc.expires).slice(0, 10) })}
              actions={(
                <div className="flex items-center gap-1.5">
                  <CopyButton value={doc.markdown} label={t('read.copy_raw')} />
                  <button className="btn btn-sm" onClick={download}>
                    <Download size={13} /> {t('read.download')}
                  </button>
                </div>
              )}
            >
              <div ref={bodyHost} className="max-w-[76ch]">
                <Markdown>{doc.markdown}</Markdown>
              </div>
            </Card>
          </div>
          {(doc.outline || []).length > 0 && (
            <div className="w-full shrink-0 lg:w-64">
              <Card title={t('read.outline')} bodyClass="p-2">
                <ul className="space-y-0.5">
                  {doc.outline.map((h) => (
                    <li key={h}>
                      <button
                        className="w-full truncate rounded-md px-2 py-1 text-left
                                   text-[12.5px] text-text-2 hover:bg-surface-2
                                   hover:text-text"
                        onClick={() => jump(h)}>
                        {h}
                      </button>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
