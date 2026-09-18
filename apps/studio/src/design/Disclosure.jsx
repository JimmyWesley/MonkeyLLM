// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Disclosure — the one-line rule for explanatory prose (spec J.5).
 *
 * Every console used to carry its own manual inside its cards: two to four
 * paragraphs before the first field, and on a phone six screens of text
 * before a button. The product was documenting itself on every screen,
 * and the reading it asked for was the reading the handbook already
 * offers. A screen now states ONE line and offers the rest: `summary` is
 * always visible, `children` is shown when the reader asks.
 *
 * The reader's choice is never persisted and never in the address — it is
 * a taste, not a selection (J.5.8). `open` only seeds the first render, for
 * the rare card whose prose IS the content (a walkthrough step).
 */
import { useId, useState } from 'react'
import { ChevronRight, Info } from './icons.jsx'
import { useI18n } from '../i18n.jsx'

/** A paragraph as its first sentence and everything after it.
 *
 *  The fold needs a summary, and the summary a console already has is the
 *  first sentence the writer wrote — asking every call site for a second,
 *  shorter string would mean three more translations per paragraph and a
 *  new way for the two to disagree. So the split is computed, and it is
 *  deliberately conservative:
 *
 *   - it cuts only at a `.`/`!`/`?` FOLLOWED BY WHITESPACE, which leaves
 *     `v0.84`, `1.0`, `sha256=<hex>` and `<timestamp>.<corpo>` whole;
 *   - the next sentence must START like one — not a lowercase letter or a
 *     digit — so `etc. e depois` and `Sr. Silva` are not sentence ends;
 *   - and a lead under `MIN_LEAD` characters is not a summary, so the cut
 *     moves to the next boundary instead: "Curto." explains nothing.
 *
 *  A paragraph it cannot split is returned whole and is simply not
 *  foldable — never truncated, because the rule is fold, never delete. The
 *  floor is 24 because it was measured against every string this console
 *  actually folds: at 40 it left 23 real paragraphs unfolded across the
 *  three languages, and at 24 it leaves 11, every one of which is a single
 *  sentence with nothing to fold. The shortest leads it then produces are
 *  "O console nunca escreve DDL." and "O que o agente não consegue ver.",
 *  which are the summaries somebody would have written by hand.
 */
const MIN_LEAD = 24

export function splitLead(text) {
  const whole = String(text ?? '').trim()
  const re = /[.!?](?=\s)/g
  let m
  while ((m = re.exec(whole)) !== null) {
    const at = m.index + 1
    if (at < MIN_LEAD) continue
    const rest = whole.slice(at).trim()
    if (/^[\p{Ll}\p{Nd}]/u.test(rest)) continue
    return [whole.slice(0, at), rest]
  }
  return [whole, '']
}

/** One paragraph, folded at its own first sentence.
 *
 *  The card-shaped fold: the summary sits in the same box `Note` uses, and
 *  `children` may add whatever else belonged to that card's preamble —
 *  further paragraphs, a list — behind the same control. */
export function Folded({ text, children, tone = 'info', open = false }) {
  const [lead, rest] = splitLead(text)
  const more = rest || children
  return (
    <Disclosure summary={lead} tone={tone} open={open}>
      {more ? <>{rest ? <p>{rest}</p> : null}{children}</> : undefined}
    </Disclosure>
  )
}

/** The same fold with no box around it: a caption that states one line and
 *  offers the rest. For prose that hangs under something else — a switch,
 *  a snippet, a field — where a second bordered box would be the density
 *  this whole rule exists to remove. */
export function More({ text, className = 'text-[12px] leading-relaxed text-text-3' }) {
  const [lead, rest] = splitLead(text)
  const [shown, setShown] = useState(false)
  const id = useId()
  const { t } = useI18n()
  if (!rest) return <span className={`block ${className}`}>{lead}</span>
  return (
    <span className={`block ${className}`}>
      {lead}{' '}
      {/* A real button and never a `<label>`'s child: this caption lives
          under switches, and a control nested in a label would toggle the
          switch it explains (ui.jsx `Toggle`, the `compact` note). */}
      <button type="button" aria-expanded={shown} aria-controls={id}
              onClick={() => setShown((v) => !v)}
              className="whitespace-nowrap font-medium text-text-2 underline
                         underline-offset-2 transition hover:text-accent">
        {shown ? t('common.less') : t('common.more')}
      </button>
      {shown && <span id={id} className="mt-1 block">{rest}</span>}
    </span>
  )
}

// The same two tones `Note` uses (design/ui.jsx NOTE_TONES), so a summary
// line and a full note sit beside each other without a third colour.
const TONES = {
  info: ['border-line bg-surface-2/40', 'text-text-3'],
  warn: ['border-warn/25 bg-warn-soft', 'text-warn'],
}

export function Disclosure({ summary, children, open = false, tone = 'info' }) {
  const [shown, setShown] = useState(Boolean(open))
  const id = useId()
  const { t } = useI18n()
  const [box, icon] = TONES[tone] || TONES.info
  const expandable = children !== undefined && children !== null && children !== false
  return (
    <div className={`rounded-lg border px-3 py-2.5 text-[12.5px] ${box}`}>
      <div className="flex items-start gap-2.5">
        <Info size={15} className={`mt-px shrink-0 ${icon}`} />
        <div className="min-w-0 flex-1 leading-relaxed text-text-2">{summary}</div>
        {expandable && (
          <button type="button" aria-expanded={shown} aria-controls={id}
                  onClick={() => setShown((v) => !v)}
                  className="flex shrink-0 items-center gap-0.5 text-[12px]
                             text-text-3 transition hover:text-text">
            {shown ? t('common.less') : t('common.more')}
            <ChevronRight size={13}
                          className={`transition-transform ${shown ? 'rotate-90' : ''}`} />
          </button>
        )}
      </div>
      {expandable && shown && (
        <div id={id} className="mt-2 space-y-2 border-t border-line/60 pt-2
                                leading-relaxed text-text-3">
          {children}
        </div>
      )}
    </div>
  )
}
