// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Tags, browsed and applied in bulk (spec J.5.18 rules 2, 3 and 4).
 *
 * Tags are one of the four columns `locate` ranks by (C.6.1), which makes
 * them the cheapest correction anybody can make to a forest's findability —
 * and until v0.75 the console offered them as a comma-separated text field
 * on one screen, one node at a time.
 *
 * Three rules from J.5.18 shape what is here.
 *
 * **The vocabulary is a map, and it is counted in SQL (rule 4).** The panel
 * reads `GET /v1/forests/{f}/tags`, whose counts are computed over the
 * caller's whole scope inside a GROUP BY — never over the page on screen,
 * for J.4.3's reason. So `invoice: 41` beside `invoices: 3` is a fact about
 * the forest that does not move when somebody changes a limit, and that is
 * the whole reason the drift is visible at all. The cap is stated: when the
 * route says `truncated`, the panel says how many tags it is NOT showing.
 *
 * **Clicking a tag filters the forest by it (rule 4).** Through `scan` with
 * `filter: {tags_any: [tag]}`, recursive, from the principal's own roots —
 * an exact filter on the column, not a `locate` query that happens to rank
 * the tag highly. `scan` already reports `total` and `truncated`, so the
 * listing can say how much of the match it is showing.
 *
 * **The bulk write is stated, and adding is not replacing (rules 2 and 3).**
 * There is no batch `graft`, so this is N calls and the operator is told so:
 * progress against the total, each refusal named and the run continuing past
 * it, and — the clause a summary is most tempted to round off — a partial
 * run never reports completion. Each node's CURRENT tags are read first and
 * the merged list is what gets written; the typed set is never sent as a
 * node's tags, because one careless action must not erase curation across a
 * selection.
 */
import { useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Empty, ErrorNote, Note, Skeleton,
} from '../design/ui.jsx'
import { Check, Plus, Tag, Trash, X } from '../design/icons.jsx'
import { useAsync } from './shared.jsx'
import {
  parseTags, runSummary, sameTags, subtractTags, unionTags,
} from '../tags.js'

/** The listing `scan` returns for one tag, over every root the principal
 *  starts from (J.5.18 rule 4).
 *
 *  One call per root because `scan` takes one parent; the results are merged
 *  by id and the totals summed, so a principal granted two subtrees sees one
 *  list. `truncated` is the OR: if any root's page was cut, the listing is
 *  not the whole match and must not read as if it were. */
export async function browseTag(forest, roots, tag) {
  const pages = await Promise.all((roots || ['_index']).map((root) =>
    api.call(forest, 'scan', {
      parent_id: root,
      recursive: true,
      filter: { tags_any: [tag] },
      fields: ['id', 'kind', 'title', 'summary', 'tags'],
      limit: 50,
    })))
  const seen = new Map()
  let total = 0
  let truncated = false
  for (const page of pages) {
    for (const n of page.nodes || []) if (!seen.has(n.id)) seen.set(n.id, n)
    total += page.total || 0
    truncated = truncated || !!page.truncated
  }
  return { hits: [...seen.values()], total, truncated }
}

/** The forest's tag vocabulary, with counts (J.5.18 rule 4). */
export function TagVocabulary({ forest, active, onPick, onClear }) {
  const { t } = useI18n()
  const vocab = useAsync(() => api.tags(forest), [forest])

  const entries = vocab.data?.tags || []
  return (
    <Card title={t('tags.vocabulary')} subtitle={t('tags.vocabulary_hint')}
          icon={Tag} bodyClass="p-3"
          actions={active ? (
            <button className="btn btn-sm" onClick={onClear}>
              <X size={12} /> {t('tags.clear_filter')}
            </button>
          ) : null}>
      {vocab.busy ? <Skeleton rows={4} />
        : vocab.error ? <ErrorNote error={vocab.error} onRetry={vocab.reload} />
        : !entries.length ? <Empty icon={Tag}>{t('tags.vocabulary_empty')}</Empty> : (
        <>
          <ul className="flex flex-wrap gap-1.5">
            {entries.map((e) => (
              <li key={e.tag}>
                <button type="button"
                        aria-pressed={active === e.tag}
                        onClick={() => onPick(e.tag)}
                        className={`inline-flex items-center gap-1.5 rounded-full border
                          px-2.5 py-1 text-[12px] transition
                          ${active === e.tag
                            ? 'border-accent bg-accent-soft text-accent'
                            : 'border-line text-text-2 hover:bg-surface-2'}`}>
                  <span className="truncate">{e.tag}</span>
                  <span className="text-text-3">{e.nodes}</span>
                </button>
              </li>
            ))}
          </ul>
          {/* C.6.2's pattern, on the console side: the cap is stated, so a
              vocabulary that was clipped never reads as a vocabulary that
              is complete. */}
          {vocab.data?.truncated && (
            <p className="mt-3 border-t border-line pt-2 text-[12px] text-text-3">
              {t('tags.vocabulary_truncated',
                 { shown: vocab.data.returned, total: vocab.data.total })}
            </p>
          )}
        </>
      )}
    </Card>
  )
}

/** Apply or remove tags across a selection (J.5.18 rules 2, 3 and 5).
 *
 *  `ids` is the selection, in the order the list shows it. The run is
 *  sequential on purpose: each node is read, merged and written, and the
 *  operator watches the count move — N commits are being authored, and
 *  firing them all at once would hide both the cost and the position the
 *  run reached if something refuses.
 */
export function BulkTags({ forest, ids, onDone, onClear }) {
  const { t } = useI18n()
  const [input, setInput] = useState('')
  const [run, setRun] = useState(null)

  const wanted = parseTags(input)
  const busy = !!run?.busy
  const summary = run ? runSummary(run) : null

  async function apply(mode) {
    if (!wanted.length || !ids.length) return
    const failures = []
    let changed = 0
    let unchanged = 0
    let done = 0
    setRun({ mode, total: ids.length, done, changed, unchanged,
             failures, busy: true })
    for (const id of ids) {
      try {
        // J.5.18 rule 3: read what is there FIRST. The write is the MERGE
        // of the node's own tags with what was typed — never the typed set
        // on its own, which would erase every tag the node already carried.
        const current = (await api.call(forest, 'look',
                                        { id, fields: ['tags'] })).tags || []
        const next = mode === 'apply'
          ? unionTags(current, wanted)
          : subtractTags(current, wanted)
        if (sameTags(current, next)) {
          // Nothing to write: a node that already carries the tag must not
          // be given a commit that changes none of its bytes.
          unchanged += 1
        } else {
          await api.call(forest, 'graft',
                         { id, patch: { set_frontmatter: { tags: next } } })
          changed += 1
        }
      } catch (e) {
        // Rule 2: report it and keep going. A run that abandoned the rest
        // on the first refusal would leave the operator with a selection
        // half-written and no record of where it stopped.
        failures.push({ id, message: e.message, code: e.code })
      }
      done += 1
      setRun({ mode, total: ids.length, done, changed, unchanged,
               failures: [...failures], busy: done < ids.length })
    }
    onDone?.()
  }

  return (
    <Card title={t('tags.bulk_title')}
          subtitle={t('tags.bulk_sub', { n: ids.length })}
          icon={Tag}
          actions={(
            <button className="btn btn-sm" onClick={onClear} disabled={busy}>
              <X size={12} /> {t('tags.deselect')}
            </button>
          )}>
      <label className="block">
        <span className="label">{t('tags.bulk_field')}</span>
        <input className="field" value={input} disabled={busy}
               placeholder={t('tags.bulk_placeholder')}
               onChange={(e) => setInput(e.target.value)} />
      </label>
      <p className="mt-1.5 text-[12px] text-text-3">{t('tags.bulk_hint')}</p>

      {!!wanted.length && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {/* What was typed, exactly as typed (rule 5): nothing here is
              normalised, so the operator sees the spelling the engine will
              be asked to accept. */}
          {wanted.map((tag) => <Badge key={tag}>{tag}</Badge>)}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn btn-primary btn-sm" disabled={busy || !wanted.length}
                onClick={() => apply('apply')}>
          <Plus size={13} /> {t('tags.bulk_apply')}
        </button>
        <button className="btn btn-sm" disabled={busy || !wanted.length}
                onClick={() => apply('remove')}>
          <Trash size={12} /> {t('tags.bulk_remove')}
        </button>
      </div>

      {summary && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-[12.5px]">
            <span className="font-medium text-text">
              {t('tags.bulk_progress', { done: summary.done, total: summary.total })}
            </span>
            <span className="text-text-3">{summary.percent}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-accent transition-[width] duration-300"
                 style={{ width: `${summary.percent}%` }} />
          </div>
          <p className="mt-2 text-[12px] text-text-3">
            {t('tags.bulk_counts', { changed: summary.changed,
                                     unchanged: summary.unchanged })}
          </p>
          {/* Rule 2: completion is claimed only for a run that reached
              every node AND had no refusal. Anything else says so. */}
          {!busy && (
            <div className="mt-2">
              {summary.complete ? (
                <Note tone="ok">
                  <span className="inline-flex items-center gap-1.5">
                    <Check size={14} /> {t('tags.bulk_complete', { n: summary.total })}
                  </span>
                </Note>
              ) : (
                <Note tone="warn">
                  {t('tags.bulk_partial', { done: summary.done - summary.failed,
                                            total: summary.total,
                                            failed: summary.failed })}
                </Note>
              )}
            </div>
          )}
          {!!summary.failed && (
            <ul className="mt-2 space-y-1">
              {run.failures.map((f) => (
                <li key={f.id} className="text-[12px] leading-relaxed">
                  <span className="nodeid">{f.id}</span>
                  {/* The engine's own sentence, which is the one that names
                      the tag it refused (rule 5). */}
                  <span className="ml-1.5 text-text-3">{f.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  )
}
