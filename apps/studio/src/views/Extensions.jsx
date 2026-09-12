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

import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { useRouteState } from '../router.js'
import {
  Badge, Card, Empty, ErrorNote, Field, Modal, Note, Skeleton, Table, Td,
} from '../design/ui.jsx'
import { Alert, Refresh, Save } from '../design/icons.jsx'
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

export default function Extensions({ forest, grant }) {
  const { t } = useI18n()
  const [selected, setSelected] = useRouteState('ext', null)
  const [source, setSource] = useState('')
  const [confirming, setConfirming] = useState(null)
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

  const refresh = () => { installed.reload(); enablement.reload() }

  const act = async (body) => {
    setBusy(true)
    setError(null)
    try {
      const result = await api.extensionAction(body)
      refresh()
      return result
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
    } catch (err) {
      // L.8: the host names what stops being declared; show that rather
      // than a generic failure, and let the operator decide again.
      const losing = err?.body?.error?.losing
      if (losing) setConfirming({ id, losing })
    }
  }

  return (
    <div className="stack">
      {error ? <ErrorNote error={error} onRetry={refresh} /> : null}

      {absent.length ? (
        // L.12 / F.187: silence here is an .mp3 quietly converted by the
        // built-in stub with nobody told.
        <Note tone="warn">
          {t('ext.absent', { list: absent.join(', ') })}
        </Note>
      ) : null}

      {mayInstall ? (
        <Card title={t('ext.install')} subtitle={t('ext.install.blurb')}>
          <div className="row gap">
            <Field
              label={t('ext.source')}
              hint={t('ext.source.hint')}
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder="github.com/org/monkeyllm-whisper@v1.2.0"
            />
            <button
              className="btn"
              disabled={busy || !source.trim()}
              onClick={async () => {
                // L.9 rule 4: the operator is shown the licence, the source
                // and the tier BEFORE anything is accepted.
                const plan = await act({ action: 'plan', source })
                setConfirming({ plan, source })
              }}
            >
              <Refresh /> {t('ext.review')}
            </button>
          </div>
        </Card>
      ) : (
        <Note tone="info">{t('ext.install.denied')}</Note>
      )}

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
                  <strong>{ext.id}</strong> <span className="muted">{ext.version}</span>
                  {/* L.2 rule 2: the ref travels with the id, everywhere. */}
                  {ext.tracking ? (
                    <div className="muted small">
                      {t('ext.tracking', { ref: ext.tracking })}
                    </div>
                  ) : null}
                  {ext.description ? (
                    <div className="muted small">{ext.description}</div>
                  ) : null}
                  {ext.broken ? (
                    <div className="small"><Alert /> {ext.broken}</div>
                  ) : null}
                </Td>
                <Td>
                  <Tier tier={ext.tier} />
                  {ext.reason ? (
                    <div className="muted small">{ext.reason}</div>
                  ) : null}
                </Td>
                <Td>
                  {(ext.contributes || []).map((seam) => (
                    <Badge key={seam}>{seam}</Badge>
                  ))}
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
        {/* L.8: a restart is stated, never implied — "disabled" without one
            means the module is still resident. */}
        <Note tone="info">{t('ext.restart')}</Note>
      </Card>

      {selected ? (
        <ConfigPanel ext={selected} forest={forest} mayEdit={mayInstall}
                     onClose={() => setSelected(null)} />
      ) : null}

      <ReviewModal
        state={confirming}
        onClose={() => setConfirming(null)}
        onInstall={async (src) => {
          await act({ action: 'install', source: src, acknowledge: true })
          setConfirming(null)
          setSource('')
        }}
        onRemove={(id) => remove(id, true)}
      />
    </div>
  )
}

/** What the operator is being asked to accept, before anything happens.
 *
 *  Licence, source, tier and permissions together — L.9 rule 4 is one act of
 *  consent, and splitting it across screens is how consent becomes a click.
 *  The permissions line says plainly that it INFORMS rather than contains,
 *  because in-process it does (L.9 rule 2) and an install screen that
 *  implied otherwise would be the most expensive sentence in the product. */
function ReviewModal({ state, onClose, onInstall, onRemove }) {
  const { t } = useI18n()
  if (!state) return null

  if (state.losing) {
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

  const plan = state.plan || {}
  return (
    <Modal open title={t('ext.review.title')} onClose={onClose}
           subtitle={plan.id ? `${plan.id} ${plan.version || ''}` : state.source}
           footer={
             <button className="btn btn-primary"
                     disabled={!plan.kit?.ok}
                     onClick={() => onInstall(state.source)}>
               <Save /> {t('ext.review.accept')}
             </button>
           }>
      <dl className="kv">
        <dt>{t('ext.licence')}</dt><dd>{plan.license || '—'}</dd>
        <dt>{t('ext.source')}</dt><dd className="mono">{plan.source}</dd>
        <dt>{t('ext.tier')}</dt>
        <dd><Tier tier={plan.tier || 'unverified'} />
          {plan.reason ? <div className="muted small">{plan.reason}</div> : null}
        </dd>
        {plan.revision ? (
          <>
            <dt>{t('ext.revision')}</dt>
            <dd className="mono">{plan.revision.slice(0, 12)}</dd>
          </>
        ) : null}
        {plan.tracking ? (
          <>
            <dt>{t('ext.tracking.label')}</dt>
            <dd className="mono">{plan.tracking}</dd>
          </>
        ) : null}
        <dt>{t('ext.permissions')}</dt>
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
        <div className="stack">
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
            <div className="muted">
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
