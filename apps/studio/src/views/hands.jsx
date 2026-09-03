// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The operator's hands: prune and transplant (spec J.5.17).
 *
 * Both primitives have been contracted, dispatched, audited and taught to
 * agents for versions — and unreachable from Studio, so the person who
 * planted a node in the wrong place held strictly fewer powers over their
 * own forest than the agent they connected to it. These are the two
 * controls that close that gap, and nothing here is a second engine: every
 * verdict is the primitive's.
 *
 * Four things this file exists to get right:
 *
 * - **The prune confirmation is written in the engine's own terms** (rule
 *   2). It names the node by title AND id, and states the two facts C.14
 *   makes true that nobody assumes about a delete button: the passport
 *   leaves through git, so the history keeps it, and a local payload is
 *   MOVED to `_derived/graveyard/` rather than unlinked. Overstating the
 *   damage teaches an operator to fear a reversible act; understating it is
 *   worse.
 * - **`E_ANCHORED` is the most useful thing this screen ever says** (rule
 *   3), so it is drawn as the list it carries — every anchor a node the
 *   console will navigate to — and never as a red sentence. `force` is a
 *   SECOND decision behind its own confirmation, because stripping other
 *   nodes' links is not the act that was just asked for.
 * - **What is shown is never presented as the whole** when the engine said
 *   otherwise: the list is capped and drops what lies outside the caller's
 *   scope, `anchor_count` is exact, and `anchorsOf` compares them once
 *   (`nodes.js`) so no rendering has to remember to.
 * - **There is no bulk anything** (rule 5). `prune` is one node per call by
 *   contract — one commit, one anchor check, one audit row — and a loop in
 *   a browser would let a single refusal strand a half-finished sweep with
 *   nothing recording where it stopped.
 *
 * The caller decides where the selection goes afterwards (rule 6): a pruned
 * id no longer resolves and a moved one is somewhere else, so neither may
 * be left sitting in the address bar.
 */
import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { Badge, ErrorNote, Field, Modal, Note, Select } from '../design/ui.jsx'
import { Move, Trash } from '../design/icons.jsx'
import {
  anchorsOf, isRootId, isSystemId, leafIdFor, looksLikeBranch, nameOf, parentOf,
} from '../nodes.js'
import { branchOf, has, useForestTree } from './shared.jsx'

/**
 * The pair of controls, for whichever console has a node as its subject.
 *
 * `onNavigate(id)` moves the console to another node (the anchors are
 * links, not names); `onPruned()` and `onMoved(newId)` are where the
 * address is repaired — this component does not own the selection, and a
 * component that navigated on its own would be a second copy of J.5.8.
 */
export default function NodeHands({ forest, grant, id, type, title,
                                    onNavigate, onPruned, onMoved }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(null)   // 'prune' | 'move' | null

  // Rule 1: absent, never disabled. A control that is only there to refuse
  // teaches the operator that the console is where permissions are argued
  // with, and J.5.4 already settled that for the editor.
  if (!id || !has(grant, 'write')) return null
  // Neither primitive can act on these, so neither offers a button: the
  // root has no parent to account for it and `_meta/` is the dialect, not
  // content (C.14 rule 4, C.15 rule 1).
  if (isRootId(id) || isSystemId(id)) return null

  // The digest's `type` when the console has one, the id's own shape when
  // it does not — every branch carries an `_index` (A.5), so the fallback
  // is exact rather than a guess.
  const branch = type === 'branch' || looksLikeBranch(id)

  return (
    <>
      <button type="button" className="btn btn-sm" onClick={() => setOpen('prune')}>
        <Trash size={13} /> {t('hands.prune')}
      </button>
      {/* Rule 4: leaf only. A branch gets no transplant control at all —
          not a disabled one, and not one that refuses on submit. */}
      {!branch && (
        <button type="button" className="btn btn-sm" onClick={() => setOpen('move')}>
          <Move size={13} /> {t('hands.move')}
        </button>
      )}

      <PruneDialog forest={forest} id={id} title={title}
                   open={open === 'prune'} onClose={() => setOpen(null)}
                   onNavigate={onNavigate} onPruned={onPruned} />
      {!branch && (
        <MoveDialog forest={forest} grant={grant} id={id}
                    open={open === 'move'} onClose={() => setOpen(null)}
                    onMoved={onMoved} />
      )}
    </>
  )
}

/** One node, named, with what its removal actually does (C.14). */
function PruneDialog({ forest, id, title, open, onClose, onNavigate, onPruned }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  // What the last refusal said about the anchors, kept in its own state
  // rather than re-derived from `error`: the second decision is ABOUT that
  // refusal, so clearing the error to make the call must not empty the
  // sentence explaining what the call is going to do.
  const [anchors, setAnchors] = useState(null)
  // The second decision (rule 3), reached only from a refusal that named
  // anchors — never offered beside the first one, where it would read as a
  // stronger version of the same button.
  const [forcing, setForcing] = useState(false)

  useEffect(() => {
    if (open) { setError(null); setAnchors(null); setForcing(false); setBusy(false) }
  }, [open])

  async function run(force) {
    setBusy(true)
    setError(null)
    try {
      // One node, one call. `force` rides only when it was decided.
      const result = await api.call(forest, 'prune', force ? { id, force: true } : { id })
      setBusy(false)
      onClose?.()
      // After the commit and never before it: the write is the truth, so
      // nothing on screen changes until the engine says it happened.
      onPruned?.(id, result)
    } catch (e) {
      setBusy(false)
      setForcing(false)
      setError(e)
      setAnchors(e?.code === 'E_ANCHORED' ? anchorsOf(e) : null)
    }
  }

  const go = (target) => { onClose?.(); onNavigate?.(target) }

  return (
    <Modal open={open} onClose={onClose}
           title={forcing ? t('hands.force_title') : t('hands.prune_title')}
           subtitle={anchors && !forcing ? t('hands.anchored') : undefined}>
      <div className="space-y-3.5">
        <p className="text-[13px] leading-relaxed text-text">
          {t('hands.prune_subject', { title: title || id, id })}
        </p>

        {forcing ? (
          <>
            <p className="text-[12.5px] leading-relaxed text-text-2">
              {t('hands.force_what')}
            </p>
            {/* C.14 rule 6, in the engine's own arithmetic: force edits
                every pointing node, so a pointing node the caller cannot
                see refuses the whole call. Said, not enforced here — the
                button stays, because a console that withheld a call the
                API would accept is a second guard. */}
            {anchors?.outOfScope > 0 && (
              <Note tone="warn">{t('hands.force_scope', { n: anchors.outOfScope })}</Note>
            )}
          </>
        ) : (
          <ul className="space-y-2 text-[12.5px] leading-relaxed text-text-2">
            <li className="rounded-lg bg-surface-2 px-3 py-2">{t('hands.prune_git')}</li>
            <li className="rounded-lg bg-surface-2 px-3 py-2">{t('hands.prune_graveyard')}</li>
          </ul>
        )}

        {anchors && !forcing && (
          <div className="space-y-2">
            {/* The engine's own sentence and hint, in the tone of a fact
                rather than a fault: this refusal is information the
                operator asked for. */}
            {error && (
              <Note tone="warn">
                {error.message}
                {error.hint && <span className="mt-1 block text-text-3">{error.hint}</span>}
              </Note>
            )}
            {anchors.total > 0 && (
              <p className="text-[12.5px] text-text-2">
                {t('hands.anchored_count', { n: anchors.total })}
              </p>
            )}
            {!!anchors.named.length && (
              <ul className="divide-y divide-line rounded-lg border border-line">
                {anchors.named.map((a, i) => (
                  <li key={`${a.source}-${i}`}
                      className="flex items-center gap-2 px-2.5 py-1.5">
                    <Badge>{a.rel}</Badge>
                    <button type="button" onClick={() => go(a.source)}
                            className="nodeid min-w-0 flex-1 truncate text-left
                                       hover:text-accent hover:underline">
                      {a.source}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {/* Rule 3: the count is the complete fact, the list is not. */}
            {!anchors.complete && (
              <p className="text-[12px] text-text-3">
                {t('hands.anchored_partial', { shown: anchors.named.length })}
                {anchors.outOfScope > 0
                  && ` ${t('hands.anchored_scope', { n: anchors.outOfScope })}`}
              </p>
            )}
          </div>
        )}

        {error && !anchors && <ErrorNote error={error} />}

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className="btn"
                  onClick={() => (forcing ? setForcing(false) : onClose?.())}>
            {forcing ? t('hands.back') : t('common.cancel')}
          </button>
          {anchors && !forcing ? (
            anchors.total > 0 && (
              <button type="button" className="btn btn-danger"
                      onClick={() => setForcing(true)}>
                <Trash size={14} /> {t('hands.force')}
              </button>
            )
          ) : (
            <button type="button" className="btn btn-danger" disabled={busy}
                    onClick={() => run(forcing)}>
              <Trash size={14} />
              {busy ? t('hands.pruning') : t('hands.prune_confirm')}
            </button>
          )}
        </div>
      </div>
    </Modal>
  )
}

/** A rename with a waymark (C.15): the parent is chosen, the leaf name is
 *  typed, and the id is composed the way J.5.7 composes a plant. */
function MoveDialog({ forest, grant, id, open, onClose, onMoved }) {
  const { t } = useI18n()
  const [parent, setParent] = useState(() => parentOf(id))
  const [name, setName] = useState(() => nameOf(id))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  // Skipped until the dialog opens: the walk is one `scan` per branch, and
  // a picker nobody opened should cost nothing.
  const tree = useForestTree(forest, grant, api.call, { skip: !open })

  useEffect(() => {
    if (!open) return
    setParent(parentOf(id)); setName(nameOf(id)); setError(null); setBusy(false)
  }, [open, id])

  // The branches this principal can actually reach — `useForestTree` starts
  // from their own roots, so a scoped operator is never offered a
  // destination the write would refuse. While it loads, the node's own
  // branch is the only honest option.
  const parents = tree.data?.branches?.length
    ? tree.data.branches : [{ id: parentOf(id) }]
  const newId = leafIdFor(parent, name)
  const same = !newId || newId === id

  async function submit(e) {
    e.preventDefault()
    if (same) return
    setBusy(true)
    setError(null)
    try {
      await api.call(forest, 'transplant', { id, new_id: newId })
      setBusy(false)
      onClose?.()
      // Rule 6: arriving at the new address is the good outcome — the node
      // is there, and the old id is a waymark rather than a place to sit.
      onMoved?.(newId)
    } catch (err) { setBusy(false); setError(err) }
  }

  return (
    <Modal open={open} onClose={onClose} title={t('hands.move_title')}
           subtitle={t('hands.move_sub')}>
      <form onSubmit={submit} className="space-y-4">
        <Select label={t('hands.move_parent')} value={parent}
                hint={t('hands.move_parent_hint')}
                onChange={(e) => setParent(e.target.value)}>
          {parents.map((p) => (
            <option key={p.id} value={p.id}>{branchOf(p.id) || t('branch.root')}</option>
          ))}
        </Select>

        <Field label={t('hands.move_name')} value={name} required autoFocus
               onChange={(e) => setName(e.target.value)}
               hint={newId && !same ? t('hands.move_will_be', { id: newId })
                 : same && newId ? t('hands.move_same')
                 : t('hands.move_name_hint')} />

        <Note>{t('hands.move_waymark', { id })}</Note>

        {error && <ErrorNote error={error} />}

        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="btn btn-primary" disabled={same || busy}>
            <Move size={14} />
            {busy ? t('hands.moving') : t('hands.move_confirm')}
          </button>
        </div>
      </form>
    </Modal>
  )
}
