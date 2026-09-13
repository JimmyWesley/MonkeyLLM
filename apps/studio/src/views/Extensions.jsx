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
  Badge, Card, Empty, ErrorNote, Field, Modal, Note, Skeleton, Table, Td,
} from '../design/ui.jsx'
import { Alert, Download, Refresh, Save, Upload } from '../design/icons.jsx'
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

export default function Extensions({ forest, grant }) {
  const { t } = useI18n()
  const [selected, setSelected] = useRouteState('ext', null)
  const [source, setSource] = useState('')
  const [upload, setUpload] = useState(null)   // {name, b64, bytes}
  const [authoring, setAuthoring] = useState(false)
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
              disabled={!!upload}
              onChange={(e) => setSource(e.target.value)}
              placeholder="github.com/org/monkeyllm-whisper@v1.2.0"
            />
            <button
              className="btn"
              disabled={busy || (!source.trim() && !upload)}
              onClick={async () => {
                // L.9 rule 4: the operator is shown the licence, the source
                // and the tier BEFORE anything is accepted.
                const body = upload
                  ? { action: 'plan', upload: { name: upload.name, b64: upload.b64 } }
                  : { action: 'plan', source }
                const plan = await act(body)
                setConfirming({ plan, source, upload })
              }}
            >
              <Refresh /> {t('ext.review')}
            </button>
          </div>

          {/* L.2 (v0.81): the door the others do not open. "A path" is a
              path on the HOST — through a browser that is the container's
              filesystem, so without this an operator holding an extension
              they just wrote has no route short of publishing it to git. */}
          <div className="row gap" style={{ alignItems: 'center' }}>
            <label className="btn">
              <Upload size={15} /> {t('ext.upload')}
              <input
                type="file"
                accept=".zip"
                hidden
                onChange={async (e) => {
                  const file = e.target.files?.[0]
                  e.target.value = ''
                  if (!file) return
                  setError(null)
                  try {
                    setUpload({
                      name: file.name,
                      b64: toBase64(await file.arrayBuffer()),
                      bytes: file.size,
                    })
                    setSource('')
                  } catch (err) { setError(err) }
                }}
              />
            </label>
            {upload ? (
              <span className="muted small">
                {upload.name} ({Math.round(upload.bytes / 1024)} KB) ·{' '}
                <button className="btn btn-sm"
                        onClick={() => setUpload(null)}>
                  {t('common.clear')}
                </button>
              </span>
            ) : (
              <span className="muted small">{t('ext.upload.hint')}</span>
            )}
          </div>
        </Card>
      ) : (
        <Note tone="info">{t('ext.install.denied')}</Note>
      )}

      {/* L.16: writing is not installing, so this is offered to everyone
          who can open this console — and the route behind it is not under
          the admin gate either. The teaching prose lives in the repository
          where it is read without running anything; what is served here is
          DERIVED, so a seam added to the catalogue documents itself. */}
      <Card title={t('ext.author')} subtitle={t('ext.author.blurb')}
            actions={
              <button className="btn btn-sm"
                      onClick={() => setAuthoring((v) => !v)}>
                {authoring ? t('common.hide') : t('ext.author.open')}
              </button>
            }>
        {authoring ? <AuthoringPanel /> : null}
      </Card>

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
        onInstall={async (src, up) => {
          await act(up
            ? { action: 'install', acknowledge: true,
                upload: { name: up.name, b64: up.b64 } }
            : { action: 'install', source: src, acknowledge: true })
          setConfirming(null)
          setSource('')
          setUpload(null)
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
                     onClick={() => onInstall(state.source, state.upload)}>
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
    <div className="stack">
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
                ? <span className="muted small">{t('ext.author.manifest_only')}</span>
                : <code className="small">{s.signature}</code>}
            </Td>
            <Td className="small">{s.summary}</Td>
          </tr>
        ))}
      </Table>
      <div className="row gap">
        <button className="btn btn-primary" disabled={saving}
                onClick={download}>
          <Download size={15} /> {t('ext.author.download')}
        </button>
        <span className="muted small">{t('ext.author.download.hint')}</span>
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
