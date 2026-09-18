// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Where the originals are kept (spec J.19, console rules in J.19.9).
 *
 * A tab of the Ingest console and not a console of its own, because J.19.9
 * says the Build group's question — *how do I put my documents in* — is
 * answered incompletely until it says where the originals go. Two panels,
 * and they answer to two different authorities on purpose (J.19.5):
 *
 *   - **the deployment's stores**, which any administrator may READ and only
 *     somebody who administers every forest may change (J.19.2), because a
 *     store's credential pays for every forest that binds it;
 *   - **this forest's binding**, which is the forest admin's own decision and
 *     is a NAME — never an endpoint, never a credential.
 *
 * The panel that cannot be used says so rather than offering a control that
 * will refuse (J.19.9), and the reader is told which of the two they hold.
 *
 * Nothing here ever renders a secret. The API answers `has_key` and nothing
 * else (J.19.1), the form's credential fields start empty on every open, and
 * an update that leaves them empty keeps the stored pair — the only way an
 * editor that cannot READ a value can leave it alone (J.16's rule).
 */
import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Empty, ErrorNote, Field, Note, Select, Skeleton, Spinner,
  Table, Td, Toggle,
} from '../design/ui.jsx'
import { Check, Database, Plus, Trash, X } from '../design/icons.jsx'

/** What "keep them here" is worth as a value: nothing, which is what the
 *  binding is when it is absent (G.6). A sentinel would have to be
 *  translated into `null` at the one place it is sent, and that place is
 *  below — so the empty string IS the local option. */
const LOCAL = ''

const EMPTY_FORM = {
  name: '', endpoint: '', bucket: '', prefix: '', region: '',
  access_key: '', secret_key: '', path_style: false,
}

/** The deployment's stores and this forest's binding.
 *
 *  `stores` is the Ingest console's own `useAsync` handle, passed down
 *  rather than re-fetched: the Connect-a-bucket card reads the same list,
 *  and two readings of one listing disagree the moment one of them is
 *  stale.
 */
export default function Storage({ forest, stores, status, me, onBound }) {
  const { t } = useI18n()
  const [error, setError] = useState(null)

  // J.19.2's reach, as the route reports it (`may_manage`). The console does
  // not compute it: "administers every forest" is a fact about forests this
  // key may not even see, so a guess here would either hide a control the
  // operator has or offer one that refuses. The owner bit is the floor while
  // an older Station answers without the field — it is a subset of the
  // reach, so it never shows a control that will be refused.
  const mayEdit = stores.data?.may_manage ?? (me?.owner === true)
  const list = stores.data?.stores || null

  return (
    <div className="space-y-4">
      {error && <Card><ErrorNote error={error} /></Card>}

      <Binding forest={forest} stores={list} status={status}
               onBound={onBound} onError={setError} />

      <Card title={t('storage.stores')} subtitle={t('storage.stores_sub')}
            icon={Database}
            actions={<Badge tone={mayEdit ? 'accent' : 'default'}>
              {t(mayEdit ? 'storage.reach_edit' : 'storage.reach_read')}
            </Badge>}>
        {/* Said, never implied: a reader who may only look is told so here,
            where the controls they do not have would have been. */}
        {!mayEdit && <Note>{t('storage.reach_read_hint')}</Note>}

        <div className={mayEdit ? '' : 'mt-3'}>
          {stores.busy && !list ? <Skeleton rows={2} />
            : stores.error ? <ErrorNote error={stores.error} onRetry={stores.reload} />
            : !list?.length ? <Empty icon={Database}>{t('storage.none')}</Empty>
            : <StoreTable stores={list} mayEdit={mayEdit}
                          onChanged={stores.reload} onError={setError} />}
        </div>

        {list?.some((s) => s.source === 'environment') && (
          <p className="mt-2 text-[11.5px] text-text-3">{t('storage.env_note')}</p>
        )}

        {mayEdit && (
          <StoreForm stores={list || []}
                     onSaved={stores.reload} onError={setError} />
        )}
      </Card>
    </div>
  )
}

/** This forest's `assets:` line (J.19.5).
 *
 *  A name and a sentence. The sentence is the whole of what an operator
 *  needs and nowhere else says: it decides where the NEXT archived original
 *  goes, and it moves nothing already written (J.19.10) — a setting that
 *  silently implied a migration would be the worst kind of promise, because
 *  the bytes it did not move are the ones somebody stops backing up.
 */
function Binding({ forest, stores, status, onBound, onError }) {
  const { t } = useI18n()
  const bound = status?.assets || LOCAL
  const [choice, setChoice] = useState(bound)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => { setChoice(bound) }, [bound])
  useEffect(() => {
    if (!saved) return undefined
    const id = setTimeout(() => setSaved(false), 2500)
    return () => clearTimeout(id)
  }, [saved])

  // The names to choose from. The deployment's listing when this reader has
  // it, and otherwise the ones the ingest status names — the same answer,
  // from the surface this forest's own admin always reaches, so a stores
  // listing that failed does not take the binding control with it.
  const names = stores ? stores.map((s) => s.name) : (status?.stores || null)

  // L.12's rule, on this forest's own page: `_meta` declares an expectation
  // and never grants it, so a binding naming a store the deployment does not
  // have is not an error — it is an unmet expectation, and it is named in
  // the one place where it can be acted on (J.19.9). The HOST decides it
  // (`assets_missing`), because it is the surface that knows both halves;
  // the comparison below is what an older Station is read with, and a claim
  // made from no answer at all would fire on every load.
  const unmet = status?.assets_missing
    ?? (Boolean(bound) && Array.isArray(names) && !names.includes(bound))

  async function save(e) {
    e.preventDefault()
    setBusy(true)
    try {
      await api.setIngestConfig(forest, { assets: choice || null })
      setSaved(true)
      onBound?.()
    } catch (err) { onError(err) } finally { setBusy(false) }
  }

  return (
    <Card title={t('storage.binding')} subtitle={t('storage.binding_sub')}
          icon={Database}>
      <form onSubmit={save} className="space-y-3">
        <Select label={t('storage.binding_label')} value={choice}
                hint={t('storage.binding_hint')}
                onChange={(e) => setChoice(e.target.value)}>
          <option value={LOCAL}>{t('storage.binding_local')}</option>
          {(names || []).map((name) => (
            <option key={name} value={name}>{name}</option>
          ))}
          {/* A binding the deployment cannot serve is still what this forest
              says: dropping it from the picker would make the Save silently
              change it to something else. */}
          {unmet && <option value={bound}>{bound}</option>}
        </Select>
        <Note>{t('storage.binding_next')}</Note>
        {unmet && <Note tone="warn">{t('storage.unmet', { name: bound })}</Note>}
        <div className="flex justify-end">
          <button className="btn btn-primary" disabled={busy || choice === bound}
                  title={choice === bound ? t('common.no_changes') : undefined}>
            {busy ? <Spinner label={t('common.saving')} />
              : saved ? <><Check size={14} /> {t('common.saved')}</>
              : t('common.save')}
          </button>
        </div>
      </form>
    </Card>
  )
}

function StoreTable({ stores, mayEdit, onChanged, onError }) {
  const { t } = useI18n()
  const [probe, setProbe] = useState(null)
  const [asked, setAsked] = useState(null)

  async function test(name) {
    setProbe({ name, busy: true })
    try {
      const r = await api.testStore(name)
      setProbe({ name, ...r })
    } catch (err) {
      setProbe({ name, ok: false, error: err.message })
    }
  }

  async function remove(name) {
    setAsked(null)
    try { await api.deleteStore(name); onChanged() } catch (err) { onError(err) }
  }

  return (
    <>
      <Table head={[t('storage.name'), t('storage.where'), t('storage.key'),
                    t('storage.source'), '']}>
        {stores.map((s) => {
          const env = s.source === 'environment'
          return (
            <tr key={s.name}>
              <Td className="font-medium text-text">{s.name}</Td>
              <Td className="whitespace-nowrap font-mono text-[12px] text-text-3">
                s3://{s.bucket}{s.prefix ? `/${s.prefix}` : ''}
                {s.endpoint && (
                  <span className="block text-text-3/80">{s.endpoint}</span>
                )}
              </Td>
              <Td>
                {/* `has_key` is a bool and the only thing the API says about
                    the credential (J.19.1). Nothing here has a value to
                    render, which is the point. */}
                {s.has_key ? <Badge tone="accent">{t('storage.key_stored')}</Badge>
                           : <Badge>{t('storage.key_none')}</Badge>}
              </Td>
              <Td>
                {env ? <Badge>{t('storage.origin_env')}</Badge>
                     : <Badge tone="accent">{t('storage.origin_console')}</Badge>}
              </Td>
              <Td>
                <div className="flex justify-end gap-1.5">
                  {mayEdit && (
                    <button className="btn btn-sm" type="button"
                            disabled={probe?.name === s.name && probe.busy}
                            onClick={() => test(s.name)}>
                      {t('storage.test')}
                    </button>
                  )}
                  {mayEdit && !env && (
                    asked === s.name ? (
                      <>
                        <button className="btn btn-sm btn-danger" type="button"
                                onClick={() => remove(s.name)}>
                          {t('storage.remove_confirm')}
                        </button>
                        <button className="btn btn-sm btn-ghost !p-1" type="button"
                                title={t('common.close')}
                                onClick={() => setAsked(null)}>
                          <X size={13} />
                        </button>
                      </>
                    ) : (
                      <button className="btn btn-sm btn-danger" type="button"
                              title={t('storage.remove')}
                              onClick={() => setAsked(s.name)}>
                        <Trash size={13} />
                      </button>
                    )
                  )}
                  {mayEdit && env && (
                    <span className="text-[11.5px] text-text-3">
                      {t('storage.env_locked')}
                    </span>
                  )}
                </div>
              </Td>
            </tr>
          )
        })}
      </Table>

      {asked && (
        <div className="mt-2"><Note tone="warn">{t('storage.remove_hint')}</Note></div>
      )}
      {probe && <Probe probe={probe} />}
    </>
  )
}

/** What the test did, step by step (J.19.3).
 *
 *  The probe is a WRITE — reachable, written, deleted — and "OK" about a
 *  three-step check is three facts a reader cannot separate when one of them
 *  later fails. A grant that can create an object and not remove it passes
 *  every listing a check could make and is exactly the fact that matters
 *  when a forest wants its bytes back, so each step is printed with its own
 *  verdict, in the order the host ran them.
 */
function Probe({ probe }) {
  const { t } = useI18n()
  if (probe.busy) {
    return <div className="mt-3"><Spinner label={t('storage.testing')} /></div>
  }
  const steps = probe.steps || []
  return (
    <div className="mt-3 space-y-1.5 text-[12.5px]">
      <p className={probe.ok ? 'text-accent' : 'text-danger'}>
        {probe.name}: {t(probe.ok ? 'storage.test_ok' : 'storage.test_fail')}
        {probe.error ? ` — ${probe.error}` : ''}
      </p>
      {steps.map((c, i) => (
        <p key={i} className="flex items-center gap-1.5 font-mono text-[11.5px]">
          <span className={c.ok ? 'text-accent' : 'text-danger'}>
            {c.ok ? <Check size={12} /> : <X size={12} />}
          </span>
          <span className="text-text-2">{t(`storage.step_${c.step}`)}</span>
          {c.error && <span className="text-text-3">{c.error}</span>}
        </p>
      ))}
      {/* The probe never leaves the prefix, and where it went is the fact an
          operator needs when the delete is the step that failed: the object
          is still in their bucket, under a key only this answer names. */}
      {probe.probe && !probe.ok && steps.some((c) => c.step === 'delete') && (
        <p className="font-mono text-[11.5px] text-text-3">
          {t('storage.probe_left', { key: probe.probe })}
        </p>
      )}
    </div>
  )
}

/** Adding one, and changing one (J.19.1).
 *
 *  Editing loads everything the API answers and NOTHING it does not: the
 *  credential fields open empty on a store that has one, and the hint says
 *  that leaving them empty keeps it. The pair moves together, so a form with
 *  one half filled is refused here by name instead of as an `E_SCHEMA` about
 *  a field the operator thought was optional.
 */
function StoreForm({ stores, onSaved, onError }) {
  const { t } = useI18n()
  const [form, setForm] = useState(EMPTY_FORM)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(false)

  const set = (k) => (e) => setForm({
    ...form, [k]: e.target?.type === 'checkbox' ? e.target.checked : e.target.value })

  const half = Boolean(form.access_key) !== Boolean(form.secret_key)
  const ready = form.name.trim() && form.bucket.trim() && !half

  function edit(store) {
    setEditing(store.name)
    setForm({
      ...EMPTY_FORM,
      name: store.name, endpoint: store.endpoint || '', bucket: store.bucket || '',
      prefix: store.prefix || '', region: store.region || '',
      path_style: Boolean(store.path_style),
    })
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    const body = {
      name: form.name.trim(), endpoint: form.endpoint.trim(),
      bucket: form.bucket.trim(), prefix: form.prefix.trim(),
      region: form.region.trim(), path_style: form.path_style,
      // `null` is "keep what is stored" (J.19.1). Sending the empty string
      // would be an operator asking for a store with no credential, which is
      // a different request and one nobody made by leaving a field alone.
      access_key: form.access_key || null,
      secret_key: form.secret_key || null,
    }
    try {
      if (editing) await api.updateStore(editing, body)
      else await api.createStore(body)
      setForm(EMPTY_FORM)
      setEditing(null)
      onSaved()
    } catch (err) { onError(err) } finally { setBusy(false) }
  }

  return (
    <form onSubmit={submit} className="mt-5 space-y-3 border-t border-line pt-4">
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] font-medium text-text">
          {editing ? t('storage.editing', { name: editing }) : t('storage.add')}
        </span>
        <div className="flex gap-1.5">
          {(stores || []).filter((s) => s.source !== 'environment').map((s) => (
            <button key={s.name} type="button"
                    className="badge hover:border-accent/40 hover:text-accent"
                    onClick={() => edit(s)}>
              {s.name}
            </button>
          ))}
          {editing && (
            <button type="button" className="btn btn-sm btn-ghost !p-1"
                    title={t('common.close')}
                    onClick={() => { setEditing(null); setForm(EMPTY_FORM) }}>
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {/* A name is an identifier before it is anything else (J.19.1): it is
            typed into a forest's `_meta/` and read back by a resolver, so it
            is fixed once the store exists. */}
        <Field label={t('storage.name')} value={form.name} required
               disabled={Boolean(editing)} placeholder="backups"
               hint={t('storage.name_hint')} onChange={set('name')} />
        <Field label={t('storage.bucket')} value={form.bucket} required
               placeholder="forest-originals" onChange={set('bucket')} />
        <Field label={t('storage.endpoint')} value={form.endpoint}
               placeholder="https://s3.eu-central-1.amazonaws.com"
               hint={t('storage.endpoint_hint')} onChange={set('endpoint')} />
        <Field label={t('storage.prefix')} value={form.prefix}
               placeholder="originals/" hint={t('storage.prefix_hint')}
               onChange={set('prefix')} />
        <Field label={t('storage.region')} value={form.region}
               placeholder="eu-central-1" onChange={set('region')} />
        <Field label={t('storage.access_key')} value={form.access_key}
               autoComplete="off" placeholder={editing ? '••••••' : 'AKIA…'}
               hint={editing ? t('storage.key_keep') : undefined}
               onChange={set('access_key')} />
        <Field label={t('storage.secret_key')} type="password"
               value={form.secret_key} autoComplete="new-password"
               placeholder={editing ? '••••••' : undefined}
               hint={editing ? t('storage.key_keep') : t('storage.key_hint')}
               onChange={set('secret_key')} />
      </div>

      <Toggle checked={form.path_style}
              onChange={(v) => setForm({ ...form, path_style: v })}
              label={t('storage.path_style')} hint={t('storage.path_style_hint')} />

      {half && <Note tone="warn">{t('storage.key_pair')}</Note>}

      <div className="flex justify-end">
        <button className="btn btn-primary" disabled={busy || !ready}>
          {editing ? <Check size={14} /> : <Plus size={14} />}
          {busy ? t('common.saving')
            : editing ? t('common.save') : t('storage.add_action')}
        </button>
      </div>
    </form>
  )
}
