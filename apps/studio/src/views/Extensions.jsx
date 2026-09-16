// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The Extensions console (spec Part L, L.11).
 *
 * Two authorities meet on this screen and the console must not blur them.
 * Installing puts third-party code in this host's process, where it reaches
 * every forest served — so it needs authority over the whole deployment.
 * Enabling decides what acts on ONE forest's material, and needs only that
 * forest's `admin`. The route decides both; this console reads `may_install`
 * off the response rather than inferring it, because a second opinion about
 * authority is a second authority.
 *
 * Three things are shown that a console is tempted to hide:
 *
 * 1. **The tier, always, with its reason.** `unverified` is a legitimate
 *    state — the operator chose it — and a badge that only appears when
 *    something is wrong teaches nobody to look for it.
 * 2. **The ref beside the id** for a tracked install. "The same extension"
 *    on two deployments is not the same code, and the id alone says it is.
 * 3. **What a removal un-declares**, before the removal, not after.
 *
 * A panel an extension declares is rendered from its manifest by the
 * components here (L.11): no extension-supplied script ever runs in this
 * origin, and the CSP (J.5.13) is not relaxed to admit one.
 */

import { useState } from 'react'

import { api, toBase64 } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { useRouteState } from '../router.js'
import {
  Badge, Card, Empty, ErrorNote, Field, Modal, Note, Segmented, Skeleton,
  Table, Td, Toggle,
} from '../design/ui.jsx'
import {
  Alert, Check, Download, File, Link, Refresh, Save, Upload,
} from '../design/icons.jsx'
import { zip } from '../zip.js'
import { NeedsCapability, has, useAsync } from './shared.jsx'

/** The tier, as a badge that is always present.
 *
 *  `verified` reads as calm, `signed` as ordinary, `unverified` as something
 *  the operator accepted on purpose — never as an error, because it is not
 *  one, and never absent, because absence is what makes a badge unread. */
function Tier({ tier }) {
  const tone = tier === 'verified' ? 'good'
    : tier === 'signed' ? 'accent' : 'warn'
  return <Badge tone={tone}>{tier}</Badge>
}

export default function Extensions({ forest, grant, goto }) {
  const { t } = useI18n()
  const [selected, setSelected] = useRouteState('ext', null)
  const [confirming, setConfirming] = useState(null)   // a removal, pending
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const installed = useAsync(() => api.extensions(), [forest])
  const enablement = useAsync(() => api.extensionEnablement(forest), [forest])

  if (!has(grant, 'admin')) {
    return <NeedsCapability message={t('ext.needs')} hint={t('ext.needs.hint')} />
  }

  const list = installed.data?.extensions || []
  const mayInstall = installed.data?.may_install === true
  const enabled = new Set(enablement.data?.enabled || [])
  const absent = enablement.data?.expected_but_absent || []
  // L.8 (v0.83): "installed" and "installed and serving" are two states.
  const pending = list.filter((ext) => ext.loaded === false).map((ext) => ext.id)

  const refresh = () => { installed.reload(); enablement.reload() }

  const act = async (body) => {
    setBusy(true)
    setError(null)
    try {
      return await api.extensionAction(body)
    } catch (err) {
      setError(err)
      throw err
    } finally {
      setBusy(false)
    }
  }

  const toggle = async (ext, next) => {
    setBusy(true)
    setError(null)
    try {
      await api.setExtensionEnablement({ forest, ext, enabled: next })
      enablement.reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (id, acknowledge) => {
    try {
      await act({ action: 'remove', id, acknowledge })
      setConfirming(null)
      refresh()
    } catch (err) {
      // L.8: the host names what stops being declared; show that rather
      // than a generic failure, and let the operator decide again.
      const losing = err?.body?.error?.losing
      if (losing) setConfirming({ id, losing })
    }
  }

  return (
    <div className="space-y-4">
      {error ? <ErrorNote error={error} onRetry={refresh} /> : null}

      {absent.length ? (
        // L.12 / F.187: silence here is an .mp3 quietly converted by the
        // built-in stub with nobody told.
        <Note tone="warn">
          {t('ext.absent', { list: absent.join(', ') })}
        </Note>
      ) : null}

      {mayInstall ? (
        <Installer forest={forest} busy={busy} act={act} goto={goto}
                   onInstalled={refresh} />
      ) : (
        <Note tone="info">{t('ext.install.denied')}</Note>
      )}

      {/* L.16: writing is not installing, so this is offered to everyone
          who can open this console — and the route behind it is not under
          the admin gate either. The teaching prose lives in the repository
          where it is read without running anything; what is served here is
          DERIVED, so a seam added to the catalogue documents itself. */}
      <AuthoringCard />

      <Card
        title={t('ext.installed')}
        actions={<button className="btn btn-sm" onClick={refresh}>
          <Refresh /> {t('common.refresh')}
        </button>}
      >
        {installed.busy ? <Skeleton rows={3} /> : list.length === 0 ? (
          <Empty title={t('ext.none')}>{t('ext.none.hint')}</Empty>
        ) : (
          <Table head={[t('ext.name'), t('ext.tier'), t('ext.contributes'),
                        t('ext.enabled_here'), '']}>
            {list.map((ext) => (
              <tr key={ext.id}>
                <Td>
                  <strong>{ext.id}</strong> <span className="text-text-3">{ext.version}</span>{' '}
                  {/* L.8 (v0.83): serving now, or after a restart — said. */}
                  {ext.loaded === false
                    ? <Badge tone="warn">{t('ext.not_loaded')}</Badge>
                    : <Badge tone="good">{t('ext.loaded')}</Badge>}
                  {/* L.2 rule 2: the ref travels with the id, everywhere. */}
                  {ext.tracking ? (
                    <div className="text-[11.5px] text-text-3">
                      {t('ext.tracking', { ref: ext.tracking })}
                    </div>
                  ) : null}
                  {ext.description ? (
                    <div className="text-[11.5px] text-text-3">{ext.description}</div>
                  ) : null}
                  {ext.broken ? (
                    <div className="text-[12px]"><Alert /> {ext.broken}</div>
                  ) : null}
                </Td>
                <Td>
                  <Tier tier={ext.tier} />
                  {ext.reason ? (
                    <div className="text-[11.5px] text-text-3">{ext.reason}</div>
                  ) : null}
                </Td>
                <Td>
                  {(ext.contributes || []).map((seam) => (
                    <Badge key={seam}>{seam}</Badge>
                  ))}
                  {(ext.formats || []).length ? (
                    <div className="mt-1 font-mono text-[11px] text-text-3">
                      {ext.formats.join(' ')}
                    </div>
                  ) : null}
                  {(ext.registers_roles || []).map((role) => (
                    <Badge key={role.role} tone="accent">
                      {t('ext.role', { role: role.role, kind: role.kind })}
                    </Badge>
                  ))}
                </Td>
                <Td>
                  <input
                    type="checkbox"
                    checked={enabled.has(ext.id)}
                    disabled={busy}
                    onChange={(e) => toggle(ext.id, e.target.checked)}
                    aria-label={t('ext.enable_on', { forest })}
                  />
                </Td>
                <Td>
                  <button className="btn btn-sm"
                          onClick={() => setSelected(ext.id)}>
                    {t('ext.configure')}
                  </button>
                  {mayInstall ? (
                    <button className="btn btn-sm"
                            disabled={busy}
                            onClick={() => remove(ext.id, false)}>
                      {t('ext.remove')}
                    </button>
                  ) : null}
                </Td>
              </tr>
            ))}
          </Table>
        )}
        {/* L.8: a restart is stated when it is NEEDED, naming who needs it;
            "disabled" without one means the module is still resident. */}
        {pending.length ? (
          <Note tone="warn">{t('ext.restart.pending', { list: pending.join(', ') })}</Note>
        ) : (
          <Note tone="info">{t('ext.restart')}</Note>
        )}
      </Card>

      {selected ? (
        <ConfigPanel ext={selected} forest={forest} mayEdit={mayInstall}
                     onClose={() => setSelected(null)} />
      ) : null}

      <RemoveModal state={confirming} onClose={() => setConfirming(null)}
                   onRemove={(id) => remove(id, true)} />
    </div>
  )
}

/** L.16's card, unchanged in substance: opened on demand. */
function AuthoringCard() {
  const { t } = useI18n()
  const [authoring, setAuthoring] = useState(false)
  return (
    <Card title={t('ext.author')} subtitle={t('ext.author.blurb')}
          bodyClass={authoring ? 'p-5' : 'p-0'}
          actions={
            <button className="btn btn-sm"
                    onClick={() => setAuthoring((v) => !v)}>
              {authoring ? t('common.hide') : t('ext.author.open')}
            </button>
          }>
      {authoring ? <AuthoringPanel /> : null}
    </Card>
  )
}

/** The install, as one legible act (L.11, v0.83).
 *
 *  The v0.82 card had the file chooser at the bottom, a "Review" button at
 *  the top right that merely changed shade when a file was chosen, and a
 *  dialog over the card to install from — three places for one act, and an
 *  operator who had chosen a zip did not read the distant button as the
 *  next step. So:
 *
 *  1. ONE primary control at a time, beside the thing it acts on: choose
 *     (primary) → review (primary, under the choice) → install (primary,
 *     under the review).
 *  2. Choosing changes nothing on the host; the review (L.9 rule 4) is the
 *     first call and its result is shown IN PLACE, never in a dialog.
 *  3. Enabling on this forest rides the install through a visible control
 *     that defaults on — installing from a forest is a statement of intent
 *     about that forest — and the route refuses the enablement, never the
 *     install, where it may not.
 *  4. The outcome says what is active now, what needs a restart, what the
 *     forest now accepts, and what is still missing before it can be used.
 */
function Installer({ forest, busy, act, goto, onInstalled }) {
  const { t } = useI18n()
  const [mode, setMode] = useState('upload')          // 'upload' | 'address'
  const [source, setSource] = useState('')
  const [upload, setUpload] = useState(null)          // {name, b64, bytes}
  const [plan, setPlan] = useState(null)              // the review, in place
  const [enableHere, setEnableHere] = useState(true)
  const [outcome, setOutcome] = useState(null)        // the install's answer

  const chosen = mode === 'upload' ? !!upload : !!source.trim()
  const request = () => (mode === 'upload'
    ? { upload: { name: upload.name, b64: upload.b64 } }
    : { source: source.trim() })

  const reset = () => {
    setSource(''); setUpload(null); setPlan(null); setOutcome(null)
  }

  const pick = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setPlan(null)
    setUpload({ name: file.name, b64: toBase64(await file.arrayBuffer()),
                bytes: file.size })
  }

  const review = async () => {
    setPlan(null)
    try { setPlan(await act({ action: 'plan', ...request() })) }
    catch { /* shown by act() */ }
  }

  const install = async () => {
    try {
      const result = await act({
        action: 'install', acknowledge: true, ...request(),
        ...(enableHere ? { enable_on: forest } : {}),
      })
      setOutcome(result)
      setPlan(null)
      onInstalled()
    } catch { /* shown by act() */ }
  }

  return (
    <Card title={t('ext.install')} subtitle={t('ext.install.blurb')} icon={Upload}>
      {outcome ? (
        <Outcome outcome={outcome} forest={forest} goto={goto} onAnother={reset} />
      ) : (
        <div className="space-y-4">
          <Segmented value={mode}
                     onChange={(next) => { setMode(next); setPlan(null) }}
                     options={[
                       { value: 'upload', label: t('ext.mode.upload'), icon: Upload },
                       { value: 'address', label: t('ext.mode.address'), icon: Link },
                     ]} />

          {mode === 'upload' ? (
            <div className="rounded-xl border-2 border-dashed border-line px-4 py-6 text-center">
              {upload ? (
                <>
                  <p className="flex items-center justify-center gap-1.5 text-[13.5px] font-medium text-text">
                    <File size={14} /> {upload.name}
                  </p>
                  <p className="mt-1 text-[12px] text-text-3">
                    {t('ext.upload.chosen', { kb: Math.round(upload.bytes / 1024) })}
                  </p>
                  <label className="btn btn-sm mt-3">
                    {t('ext.upload.change')}
                    <input type="file" accept=".zip" hidden onChange={pick} />
                  </label>
                </>
              ) : (
                <>
                  <p className="text-[13.5px] font-medium text-text">{t('ext.upload.title')}</p>
                  <p className="mt-1 text-[12px] text-text-3">{t('ext.upload.hint')}</p>
                  {/* The one primary control while nothing is chosen. */}
                  <label className="btn btn-primary mt-3">
                    <Upload size={15} /> {t('ext.upload')}
                    <input type="file" accept=".zip" hidden onChange={pick} />
                  </label>
                </>
              )}
            </div>
          ) : (
            <Field
              label={t('ext.source')}
              hint={t('ext.source.hint')}
              value={source}
              onChange={(e) => { setSource(e.target.value); setPlan(null) }}
              placeholder="github.com/org/monkeyllm-whisper@v1.2.0"
            />
          )}

          {plan ? (
            <Review plan={plan} forest={forest} busy={busy}
                    enableHere={enableHere} setEnableHere={setEnableHere}
                    onInstall={install} onBack={() => setPlan(null)} />
          ) : (
            // Rule 1: under the choice, primary the moment there is one.
            <div className="flex flex-wrap items-center gap-3">
              <button className={`btn ${chosen ? 'btn-primary' : ''}`}
                      disabled={busy || !chosen} onClick={review}>
                <Refresh /> {t('ext.review.cta')}
              </button>
              <span className="text-[11.5px] text-text-3">
                {chosen ? t('ext.review.next') : t('ext.review.first')}
              </span>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

/** What the operator is being asked to accept, in place (L.9 rule 4, L.11
 *  rule 2). Licence, source, tier and permissions together — one act of
 *  consent — plus what the extension will make the forest take and offer,
 *  so the decision is about what it DOES and not only where it came from. */
function Review({ plan, forest, busy, enableHere, setEnableHere, onInstall, onBack }) {
  const { t } = useI18n()
  const ok = plan.kit?.ok === true
  const roles = (plan.registers_roles || [])
    .map((r) => `${r.role} (${r.kind})`).join(', ')
  return (
    <div className="space-y-3 rounded-xl border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13.5px]">
          <strong>{plan.id || plan.source}</strong>{' '}
          <span className="text-text-3">{plan.version || ''}</span>
        </div>
        <Badge tone={ok ? 'good' : 'warn'}>
          {ok ? t('ext.review.ok') : t('ext.review.failed')}
        </Badge>
      </div>
      <dl className="grid grid-cols-[8rem_1fr] gap-x-4 gap-y-2 text-[12.5px]">
        <dt className="font-medium text-text-2">{t('ext.licence')}</dt><dd>{plan.license || '—'}</dd>
        <dt className="font-medium text-text-2">{t('ext.source')}</dt>
        <dd className="font-mono text-[11.5px] text-text-3">{plan.source}</dd>
        <dt className="font-medium text-text-2">{t('ext.tier')}</dt>
        <dd>
          <Tier tier={plan.tier || 'unverified'} />
          {plan.reason ? <div className="text-[11.5px] text-text-3">{plan.reason}</div> : null}
        </dd>
        {plan.revision ? (
          <>
            <dt className="font-medium text-text-2">{t('ext.revision')}</dt>
            <dd className="font-mono text-[11.5px] text-text-3">{plan.revision.slice(0, 12)}</dd>
          </>
        ) : null}
        {plan.tracking ? (
          <>
            <dt className="font-medium text-text-2">{t('ext.tracking.label')}</dt>
            <dd className="font-mono text-[11.5px] text-text-3">{plan.tracking}</dd>
          </>
        ) : null}
        <dt className="font-medium text-text-2">{t('ext.review.formats')}</dt>
        <dd className="font-mono text-[11.5px]">
          {(plan.formats || []).length ? plan.formats.join(' ') : t('ext.review.none')}
        </dd>
        <dt className="font-medium text-text-2">{t('ext.review.roles')}</dt>
        <dd>{roles || t('ext.review.none')}</dd>
        <dt className="font-medium text-text-2">{t('ext.permissions')}</dt>
        <dd>
          <div>{t('ext.perm.network', {
            list: (plan.permissions?.network || []).join(', ') || t('ext.none.short'),
          })}</div>
          <div>{t('ext.perm.filesystem', {
            value: plan.permissions?.filesystem || 'none',
          })}</div>
          {/* L.9 rule 2, said out loud. */}
          <Note tone="warn">{t('ext.perm.informs')}</Note>
        </dd>
      </dl>
      {plan.kit?.ok === false ? (
        <Note tone="error">
          {t('ext.kit.failed', { list: (plan.kit.failed || []).join(', ') })}
        </Note>
      ) : null}
      {ok ? (
        <Toggle checked={enableHere} onChange={setEnableHere}
                label={t('ext.enable_here', { forest })}
                hint={t('ext.enable_here.hint')} />
      ) : null}
      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
        {/* The one primary control, under what it acts on. */}
        <button className="btn btn-primary" disabled={busy || !ok} onClick={onInstall}>
          <Save /> {t('ext.install.cta')}
        </button>
        <button className="btn" disabled={busy} onClick={onBack}>
          {t('ext.review.back')}
        </button>
      </div>
    </div>
  )
}

/** L.11 rule 4: what is active now, what needs a restart, what the forest
 *  now accepts, and what is still missing before the extension can be used. */
function Outcome({ outcome, forest, goto, onAnother }) {
  const { t } = useI18n()
  const roles = (outcome.registers_roles || [])
    .map((r) => `${r.role} (${r.kind})`).join(', ')
  return (
    <div className="space-y-3">
      <Note tone={outcome.activated ? 'good' : 'warn'}>
        <strong>{t('ext.done.title', { id: outcome.id, version: outcome.version || '' })}</strong>{' '}
        {outcome.activated
          ? t('ext.done.active')
          : t('ext.done.restart', { note: outcome.activation_note || '' })}
      </Note>
      <ul className="space-y-1.5 text-[12.5px]">
        {outcome.enabled_on?.length ? (
          <li className="flex items-center gap-1.5"><Check size={14} /> {t('ext.done.enabled', { forest })}</li>
        ) : null}
        {outcome.enable_error ? (
          <li className="flex items-center gap-1.5"><Alert size={14} /> {t('ext.done.enable_error', { error: outcome.enable_error })}</li>
        ) : null}
        {(outcome.formats || []).length ? (
          <li>{t('ext.done.formats', { list: outcome.formats.join(', ') })}</li>
        ) : null}
        {roles ? (
          <li className="flex flex-wrap items-center gap-2">
            <span>{t('ext.done.roles', { list: roles })}</span>
            {goto ? (
              <button className="btn btn-sm" onClick={() => goto('models')}>
                {t('ext.done.goto_models')}
              </button>
            ) : null}
          </li>
        ) : null}
      </ul>
      <button className="btn" onClick={onAnother}>{t('ext.done.another')}</button>
    </div>
  )
}

/** L.8: what a removal un-declares is named BEFORE the act, and decided
 *  again by the operator. */
function RemoveModal({ state, onClose, onRemove }) {
  const { t } = useI18n()
  if (!state?.losing) return null
  return (
    <Modal open title={t('ext.remove.title')} onClose={onClose}
           footer={
             <button className="btn btn-danger"
                     onClick={() => onRemove(state.id)}>
               {t('ext.remove.confirm')}
             </button>
           }>
      <Note tone="warn">
        {t('ext.remove.losing', { list: state.losing.join(', ') })}
      </Note>
    </Modal>
  )
}

/** The declarative panel (L.11): the manifest describes, this renders.
 *
 *  A field declared `secret` shows its PRESENCE and never its value, and an
 *  empty box means "leave it alone" rather than "clear it" — the only way an
 *  editor that cannot read a value can avoid destroying it. */
function ConfigPanel({ ext, forest, mayEdit, onClose }) {
  const { t } = useI18n()
  const config = useAsync(() => api.extensionConfig(ext), [ext])
  const quota = useAsync(() => api.extensionQuota(ext, forest), [ext, forest])
  const [draft, setDraft] = useState({})
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  const declares = config.data?.declares || {}
  const values = config.data?.values || {}

  const save = async () => {
    setError(null)
    try {
      await api.saveExtensionConfig({ ext, values: draft })
      setDraft({})
      setSaved(true)
      config.reload()
    } catch (err) { setError(err) }
  }

  return (
    <Modal open wide title={t('ext.config.title', { ext })} onClose={onClose}
           footer={mayEdit ? (
             <button className="btn btn-primary"
                     disabled={Object.keys(draft).length === 0}
                     onClick={save}>
               <Save /> {t('common.save')}
             </button>
           ) : null}>
      {error ? <ErrorNote error={error} /> : null}
      {saved ? <Note tone="good">{t('ext.config.saved')}</Note> : null}
      {config.busy ? <Skeleton rows={3} /> : (
        <div className="space-y-3">
          {Object.keys(declares).length === 0
            ? <Empty title={t('ext.config.none')} />
            : Object.entries(declares).map(([key, field]) => (
              <Field
                key={key}
                label={key}
                hint={field.secret
                  ? (values[key]?.has_value
                    ? t('ext.config.secret.set')
                    : t('ext.config.secret.unset'))
                  : field.description}
                type={field.secret ? 'password' : 'text'}
                disabled={!mayEdit}
                value={draft[key] ?? (field.secret ? ''
                  : (values[key]?.value ?? field.default ?? ''))}
                placeholder={field.secret ? '••••••••' : ''}
                onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
              />
            ))}
          <Card title={t('ext.quota.title')} subtitle={t('ext.quota.blurb')}>
            <div className="text-text-3">
              {t('ext.quota.state', {
                spent: (quota.data?.spent ?? 0).toFixed(4),
                ceiling: quota.data?.ceiling ?? '—',
                period: quota.data?.period ?? 'month',
              })}
            </div>
          </Card>
        </div>
      )}
    </Modal>
  )
}


/** L.16 — the derived half of what an author is handed.
 *
 *  It lists the seams from the STATION's own contracts rather than from a
 *  copy kept here, because a copy is what goes stale the first time a seam
 *  is added — silently, to exactly the person who has no other source. The
 *  concepts (why a contribution and not a patch, the worked example) live
 *  in the repository and are linked, not restated.
 */
function AuthoringPanel() {
  const { t } = useI18n()
  const doc = useAsync(() => api.extensionAuthoring(), [])
  const [saving, setSaving] = useState(false)

  const download = async () => {
    setSaving(true)
    try {
      const [seams, manifest] = await Promise.all([
        api.extensionAuthoringDoc('seams'),
        api.extensionAuthoringDoc('manifest'),
      ])
      const version = doc.data?.station || ''
      const folder = 'monkeyllm-extension-authoring'
      const core = [
        '---',
        'name: monkeyllm-extension',
        `description: Write a MonkeyLLM extension for a Station running ${version}.`,
        '---',
        '',
        `# Writing a MonkeyLLM extension (Station ${version})`,
        '',
        'An extension adds a capability this deployment does not have — a',
        'converter for a file type, a tool for the agents, a panel in the',
        'console — **without a single package entering the engine\'s own',
        'environment**.',
        '',
        'It **contributes at a named seam** and never patches. That is what',
        'leaves the product free to refactor: you are coupled to a seam\'s',
        'published contract, never to the code behind it.',
        '',
        '## The package',
        '',
        '```',
        'manifest.json   identity, compat, permissions, contributions, config',
        'main.py         register(api) — the one activation entry point',
        'worker.py       handlers you marked `heavy` (their own process)',
        'ui/panel.json   declarative console contributions',
        'requirements.txt  resolved into the extension\'s own environment',
        'LICENSE         your licence, shown before the install completes',
        '```',
        '',
        '- `references/seams.md` — every seam and the exact shape of its',
        '  handler. Generated from this Station.',
        '- `references/manifest.md` — the manifest JSON Schema. Generated.',
        '',
        '## Rules that will refuse you',
        '',
        '- A handler naming a parameter its seam does not pass **fails the',
        '  conformance kit at install** — unless that parameter has a',
        '  default. `**kwargs` excuses nothing.',
        '- A tool or route name outside your namespace refuses the install.',
        '- You never hold a model key: declare a role, and the host hands',
        '  you a bound caller.',
        '- Installing or removing takes effect after the host restarts.',
        '  Settings take effect immediately.',
        '',
        '## Install what you wrote',
        '',
        'Zip the folder and upload it in the Extensions console, or from a',
        'shell on the host: `vine ext install ./your-extension --yes`.',
        '',
        'The concepts, and a worked example that ships in the repository,',
        'are in `docs/extending.md`.',
        '',
      ].join('\n')
      save(`${folder}.zip`, zip([
        { path: `${folder}/SKILL.md`, text: core },
        { path: `${folder}/references/seams.md`, text: seams },
        { path: `${folder}/references/manifest.md`, text: manifest },
      ]))
    } finally { setSaving(false) }
  }

  if (doc.busy) return <Skeleton rows={3} />
  if (doc.error) return <ErrorNote error={doc.error} onRetry={doc.reload} />

  return (
    <div className="space-y-3">
      <Note tone="info">
        {t('ext.author.derived', { version: doc.data?.station || '?' })}
      </Note>
      <Table head={[t('ext.author.seam'), t('ext.author.shape'),
                    t('ext.author.does')]}>
        {(doc.data?.seams || []).map((s) => (
          <tr key={s.seam}>
            <Td><code>{s.seam}</code></Td>
            <Td>
              {s.declarative
                ? <span className="text-[11.5px] text-text-3">{t('ext.author.manifest_only')}</span>
                : <code className="text-[12px]">{s.signature}</code>}
            </Td>
            <Td className="text-[12px]">{s.summary}</Td>
          </tr>
        ))}
      </Table>
      <div className="flex flex-wrap items-end gap-2">
        <button className="btn btn-primary" disabled={saving}
                onClick={download}>
          <Download size={15} /> {t('ext.author.download')}
        </button>
        <span className="text-[11.5px] text-text-3">{t('ext.author.download.hint')}</span>
      </div>
    </div>
  )
}

/** The Skills console's own saver: a Blob, an anchor, a revoked URL. */
function save(name, blob) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
