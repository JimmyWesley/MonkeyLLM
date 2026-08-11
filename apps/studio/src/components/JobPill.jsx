// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The batch, visible from every console (spec J.9.3).
 *
 * A small pill announces the running batch and the waiting queue from
 * whatever console is open, and expands on demand into what the job record
 * says — done over total, the document in hand, errors so far, the cancel,
 * and the way to the ingest console. It reads the tab's board watcher and
 * nothing else: no browser-storage copy, no address writes — rendering
 * never navigates (J.5.8), only the link does.
 *
 * The cadence follows the attention: collapsed it asks for the glance
 * pace, expanded for the watch pace. On the ingest console it renders
 * nothing and asks for nothing — the full progress card is already on
 * screen, and that console registers its own attention.
 */

import { useState } from 'react'
import { api } from '../api.js'
import { hrefFor, linkTo } from '../router.js'
import { useI18n } from '../i18n.jsx'
import {
  GLANCE, WATCH, release, useAttend, useBoard,
} from '../board.js'
import { Badge, ErrorNote, Note } from '../design/ui.jsx'
import {
  ChevronDown, Clock, Ingest as Upload, Play, X,
} from '../design/icons.jsx'
import { has } from '../views/shared.jsx'

export default function JobPill({ forest, view, grant }) {
  const { t } = useI18n()
  const board = useBoard(forest)
  const [open, setOpen] = useState(false)
  // Which job the stop was asked of: keyed by id, so the button comes back
  // for the next batch instead of staying spent forever.
  const [asked, setAsked] = useState('')

  // Watching needs the same capability that could have asked for the work
  // (J.9); the ingest console carries its own card and its own attention.
  const active = Boolean(forest) && has(grant, 'ingest') && view !== 'ingest'
  useAttend(forest, open ? WATCH : GLANCE, active)

  const job = board.running
  const waiting = board.items.length
  if (!active || (!job && !waiting && !board.held)) return null

  const total = job ? Math.max(job.total || 0, 1) : 0
  const pct = job ? Math.min(100, Math.round(((job.done || 0) / total) * 100)) : 0

  if (!open) {
    return (
      <div className="fixed bottom-20 right-4 z-30 lg:bottom-6 lg:right-6">
        <button type="button" aria-expanded={false}
                title={t(job ? 'ingest.job_title' : 'ingest.queue_title')}
                onClick={() => setOpen(true)}
                className="flex items-center gap-2 rounded-full border border-line
                           bg-bg-elev py-2 pl-3 pr-3.5 text-[12.5px] font-medium
                           text-text shadow-pop transition hover:border-line-strong">
          {board.held
            ? <Clock size={15} className="text-warn" />
            : <Upload size={15} className={job ? 'text-accent' : 'text-text-3'} />}
          {job
            ? <span>{job.total > 0 ? `${pct}%` : t('ingest.job_title')}</span>
            : <span>{t('ingest.pill_queue', { n: waiting })}</span>}
          {job && waiting > 0 && (
            <span className="text-text-3">+{waiting}</span>
          )}
        </button>
      </div>
    )
  }

  return (
    <div className="fixed bottom-20 right-4 z-30 w-[min(330px,calc(100vw-2rem))]
                    rounded-xl border border-line bg-bg-elev p-3.5 shadow-pop
                    lg:bottom-6 lg:right-6">
      <div className="flex items-center gap-2">
        <Upload size={15} className="text-accent" />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text">
          {t(job ? 'ingest.job_title' : 'ingest.queue_title')}
        </span>
        {job && <Badge tone="accent">{job.mode}</Badge>}
        <button type="button" className="btn btn-sm btn-ghost !p-1"
                aria-expanded onClick={() => setOpen(false)}
                title={t('common.close')}>
          <ChevronDown size={14} />
        </button>
      </div>

      {job && (
        <div className="mt-2.5">
          <div className="flex items-center justify-between text-[12px]">
            <span className="text-text-2">
              {t('ingest.job_progress', { done: job.done || 0, total: job.total || 0 })}
            </span>
            <span className="text-text-3">{job.total > 0 ? `${pct}%` : '…'}</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-accent transition-[width] duration-500"
                 style={{ width: `${pct}%` }} />
          </div>
          {job.current && (
            <p className="mt-1.5 truncate font-mono text-[11px] text-text-3">
              {t('ingest.job_current', { file: job.current })}
            </p>
          )}
          <div className="mt-2 flex items-center justify-between">
            {job.errors > 0
              ? <Badge tone="danger">{t('ingest.job_errors', { n: job.errors })}</Badge>
              : <span />}
            <button type="button" className="btn btn-sm" disabled={asked === job.id}
                    onClick={() => {
                      setAsked(job.id)
                      api.cancelJob(forest, job.id).catch(() => {})
                    }}>
              <X size={12} />
              {asked === job.id ? t('ingest.job_cancelling') : t('ingest.job_cancel')}
            </button>
          </div>
        </div>
      )}

      {board.held && (
        <div className="mt-2.5">
          <Note tone="warn">
            <div>
              {t(board.held.why === 'cancelled' ? 'ingest.queue_held_cancelled'
                                                : 'ingest.queue_held_refused')}
            </div>
            {board.held.error && (
              <div className="mt-2"><ErrorNote error={board.held.error} /></div>
            )}
            {waiting > 0 && (
              <button type="button" className="btn btn-sm mt-2"
                      onClick={() => release(forest)}>
                <Play size={12} /> {t('ingest.queue_release')}
              </button>
            )}
          </Note>
        </div>
      )}

      <div className="mt-2.5 flex items-center justify-between border-t
                      border-line pt-2.5">
        <span className="text-[12px] text-text-3">
          {waiting > 0 ? t('ingest.pill_queue', { n: waiting }) : ''}
        </span>
        {/* A real anchor (J.5.8): the way to the full card, the queue and
            the report. Rendering never navigates; this click does. */}
        <a className="text-[12px] font-medium text-accent hover:underline"
           {...linkTo(hrefFor(forest, 'ingest'))}>
          {t('ingest.pill_console')}
        </a>
      </div>
    </div>
  )
}
