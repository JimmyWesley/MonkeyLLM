// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { WATCH, noteJob, useAttend, useBoard } from '../board.js'
import {
  Badge, Card, Combobox, Empty, ErrorNote, Field, Note, Rows, Select, Skeleton,
  Spinner, Toggle,
} from '../design/ui.jsx'
import { Folded, More } from '../design/Disclosure.jsx'
import {
  Ask, Check, Eye, Ingest, Models as Chip, Plus, Trash,
} from '../design/icons.jsx'
import { Metric, NeedsCapability, has, useAsync } from './shared.jsx'

/** Saving a binding, with the three states a save actually has.
 *
 *  "Nothing to save" is a state, not a disabled edge case: an enabled
 *  Update on an untouched form invites a write that changes nothing, and
 *  then says nothing back — which is exactly how an operator ends up
 *  clicking it twice wondering whether it took. Pressed, the button reports
 *  that it is working and then that it worked, and goes quiet on its own.
 */
function useSave(run) {
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!done) return undefined
    const id = setTimeout(() => setDone(false), 2500)
    return () => clearTimeout(id)
  }, [done])

  return [async (e) => {
    e?.preventDefault?.()
    setBusy(true); setDone(false)
    // A failure is reported by the caller, which owns the error surface; it
    // must not also confirm success, and it must not escape as an unhandled
    // rejection either.
    try { await run(); setDone(true) } catch { /* reported */ } finally { setBusy(false) }
  }, busy, done]
}

function SaveButton({ busy, done, dirty, disabled, label }) {
  const { t } = useI18n()
  return (
    <button className="btn btn-primary" disabled={busy || disabled || !dirty}
            title={dirty ? undefined : t('common.no_changes')}>
      {busy ? (
        <>
          {/* Not the shared `Spinner`: that one is muted grey for a page
              body, which on a filled button reads as a rendering fault. */}
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2
                           border-accent-fg/30 border-t-accent-fg" />
          {t('common.saving')}
        </>
      ) : done ? <><Check size={14} /> {t('common.saved')}</>
        : label}
    </button>
  )
}

/** Spec J.10. A forest is not one workload: ingest wants care because its
 *  output is the scent every later hop navigates by; answering wants speed.
 *  One global endpoint cannot express that, and it cannot express "this
 *  corpus stays local while that one uses a hosted model" either. */
/* L.6 rule 1 (v0.83): the LIST of roles is the host's — `GET /v1/admin/models`
 * carries every bindable role with its `kind` and its origin, and this
 * console renders from that answer. What stays here is presentation for the
 * product's own roles: an icon and a reply-length default. A role an
 * extension registers gets a generic glyph and its manifest's description.
 * The v0.82 console kept the list itself, so a role the Extensions console
 * listed had no card here and the route refused it besides. */
const PRESENTATION = {
  // 300 was sized for the summary (60 tokens) and not for the reply that
  // carries it: JSON envelope, tags, and — on a hybrid thinker — a whole
  // reasoning pass before the first character of content. Too small a
  // budget truncates the reply mid-JSON, which reads downstream as "the
  // model said nothing useful" rather than "it was cut off".
  ingest: { icon: Ingest, defaultTokens: 600 },
  // `answer` is the one role whose reply carries the citation apparatus and
  // not just prose: on a walk the final action is a JSON object holding the
  // answer text AND `answer_nodes`, and a client that also asks for a
  // verbatim proof pushes it further. Measured on the 18-question suite with
  // a local 12B, at 600 two answers were cut mid-object and scored as wrong
  // — the model had already run the right query and reached the right node.
  // At 1500 both pass and the wall time falls with them (139s -> 15s),
  // because the rejected retries stop happening. The hint below already
  // warned about this; the default did not obey it.
  answer: { icon: Ask, defaultTokens: 1500 },
  // The G.5.1 describer. It runs where ingest runs — once per image, at
  // adopt/sync — and what it writes is the only text `sniff` will ever see
  // of a slide or a screenshot, so fidelity is the thing to pay for. Unbound,
  // images still plant as media with the stub body; nothing here is required
  // for ingest to keep working (J.10).
  vision: { icon: Eye, defaultTokens: 600 },
}
const GENERIC = { icon: Chip, defaultTokens: 600 }
// The shapes a binding form takes, by the role's `kind` (L.6): a chat turn
// has a reply length and a reasoning switch; a transcription is a multipart
// upload and has neither.
const CHAT_SHAPED = new Set(['chat', 'vision'])

const PRESETS = [
  { name: 'openai', endpoint: 'https://api.openai.com/v1' },
  { name: 'openrouter', endpoint: 'https://openrouter.ai/api/v1' },
  { name: 'ollama', endpoint: 'http://localhost:11434/v1' },
  { name: 'litellm', endpoint: 'http://localhost:4000/v1' },
  { name: 'local-llamacpp', endpoint: 'http://localhost:8090/v1' },
  { name: 'vllm', endpoint: 'http://localhost:8000/v1' },
]

/** Providers quote USD per token, which is unreadable at 0.0000006. Per
 *  million is how everyone actually compares them. A model with no stated
 *  price shows nothing — silence must not render as free. */
function priceTag(model) {
  const { prompt, completion } = model
  if (prompt == null && completion == null) return null
  const per = (v) => (v == null ? '?' : `$${(v * 1e6).toFixed(2)}`)
  return `${per(prompt)} / ${per(completion)} · 1M`
}

export default function Models({ forest, grant }) {
  const { t } = useI18n()
  const [error, setError] = useState(null)
  const [probe, setProbe] = useState(null)
  const [draft, setDraft] = useState({ name: '', endpoint: '', api_key: '' })
  /* J.5: the list before the form. Adding a provider is done once and then
     almost never — it was the first thing on the console and the table it
     feeds was below it, so the screen opened on a blank form and an
     operator scrolled past their own deployment to find it. */
  const [adding, setAdding] = useState(false)
  // Per-provider catalogue, fetched from the provider's own /models. Cached
  // here so the two role cards share one round trip.
  const [catalogue, setCatalogue] = useState({})

  const admin = has(grant, 'admin')
  const providers = useAsync(() => api.providers().then((p) => p.providers),
                             [forest], { skip: !admin })
  // The whole answer, not only `.bindings`: `.roles` is what the cards are
  // rendered from (L.6 rule 1).
  const bindings = useAsync(() => api.bindings(forest), [forest], { skip: !admin })

  if (!admin) {
    return <NeedsCapability message={t('models.needs_admin')} hint={t('cap.admin')} />
  }

  const bound = bindings.data?.bindings || []
  const roles = (bindings.data?.roles || []).filter((r) => r.role !== 'embed')

  const refresh = () => { providers.reload(); bindings.reload() }

  async function saveProvider(e) {
    e.preventDefault()
    setError(null)
    try {
      await api.putProvider(draft)
      setDraft({ name: '', endpoint: '', api_key: '' })
      setAdding(false)
      refresh()
    } catch (err) { setError(err) }
  }

  /** One call answers both questions: is it reachable, and what does it
   *  serve. `announce` is off when a role card asks, so browsing models
   *  does not repaint the connection banner. */
  const load = useCallback(async (name, { announce = false } = {}) => {
    if (!name) return
    if (announce) setProbe({ name, state: 'testing' })
    setCatalogue((c) => ({ ...c, [name]: { ...(c[name] || {}), busy: true } }))
    try {
      const r = await api.testProvider({ name })
      setCatalogue((c) => ({ ...c, [name]: { busy: false, models: r.models || [],
                                             ok: r.ok, error: r.error } }))
      if (announce) setProbe({ name, state: r.ok ? 'ok' : 'fail', ...r })
    } catch (err) {
      setCatalogue((c) => ({ ...c, [name]: { busy: false, models: [], error: err.message } }))
      if (announce) setProbe({ name, state: 'fail', error: err.message })
    }
  }, [])

  return (
    <div className="space-y-4">
      {error && <Card><ErrorNote error={error} /></Card>}

      <Card title={t('models.providers')} subtitle={t('models.providers_sub')} icon={Chip}
            actions={
              <button type="button" className={`btn btn-sm ${adding ? '' : 'btn-primary'}`}
                      onClick={() => setAdding((v) => !v)}>
                {adding ? t('common.cancel') : <><Plus size={14} /> {t('models.add')}</>}
              </button>}>
        {/* A failed fetch must not render as an empty list. `data` is null
            on error too, so testing only its length told an operator whose
            Station was unreachable that their providers were *gone* — a
            false statement about their data, produced by a network blip. */}
        {providers.busy ? <Skeleton rows={2} />
          : providers.error ? <ErrorNote error={providers.error} onRetry={providers.reload} />
          : (providers.data || []).length === 0 ? (
            <Empty icon={Chip}
                   action={<button type="button" className="btn btn-primary btn-sm"
                                   onClick={() => setAdding(true)}>
                     <Plus size={14} /> {t('models.add')}
                   </button>}>
              {t('models.none')}
            </Empty>
          ) : (
            <Rows head={[t('models.name'), t('models.endpoint'), t('models.key')]}
                  rows={providers.data.map((p) => ({
                    key: p.name,
                    cells: [
                      <span className="flex flex-wrap items-center gap-1.5 font-medium text-text">
                        {p.name}
                        {/* Declared by the deployment (J.10.1): shown as a fact
                            about where it came from, because that is also why
                            its key and endpoint are not editable here. */}
                        {p.origin === 'env' && <Badge>{t('models.origin_env')}</Badge>}
                      </span>,
                      <span className="break-all font-mono text-[12px] text-text-3">
                        {p.endpoint}
                      </span>,
                      p.has_key ? <Badge tone="accent">{t('models.key_stored')}</Badge>
                                : <Badge>{t('models.key_none')}</Badge>,
                    ],
                    actions: <>
                      <button className="btn btn-sm"
                              onClick={() => load(p.name, { announce: true })}>
                        {t('models.test')}
                      </button>
                      <button className="btn btn-sm btn-danger"
                              disabled={p.origin === 'env'}
                              title={p.origin === 'env' ? t('models.env_locked') : undefined}
                              onClick={() => api.putProvider({ name: p.name, remove: true })
                                .then(refresh).catch(setError)}>
                        <Trash size={13} />
                      </button>
                    </>,
                  }))} />
          )}

        {/* Only where an `env` badge is actually on screen — the note is
            about that badge, and a rule with nothing to explain is noise. */}
        {(providers.data || []).some((p) => p.origin === 'env') && (
          <div className="mt-2"><More text={t('models.env_note')} /></div>
        )}

        {probe && (
          <div className="mt-3 text-[12.5px]">
            {probe.state === 'testing' ? <Spinner label={t('models.testing')} />
              : probe.state === 'ok'
                ? <p className="text-accent">
                    {probe.name}: {t('models.reachable', { n: probe.count })}
                  </p>
                : <p className="text-danger">
                    {probe.name}: {t('models.unreachable')} — {probe.error}
                  </p>}
            {probe.state === 'ok' && !!probe.models?.length && (
              <p className="mt-1 font-mono text-[12px] text-text-3">
                {probe.models.slice(0, 6).map((m) => m.id).join(' · ')}
                {probe.models.length > 6 ? ' …' : ''}
              </p>
            )}
          </div>
        )}

        {adding && (
          <form onSubmit={saveProvider} className="mt-5 space-y-3 border-t border-line pt-4">
            <div className="grid gap-3 sm:grid-cols-[1fr_1.5fr_1fr_auto] sm:items-end">
              <Field label={t('models.name')} value={draft.name} required autoFocus
                     placeholder="openai"
                     onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              <Field label={t('models.endpoint')} value={draft.endpoint} required
                     placeholder="https://api.openai.com/v1"
                     onChange={(e) => setDraft({ ...draft, endpoint: e.target.value })} />
              <Field label={t('models.key')} type="password" value={draft.api_key}
                     placeholder="sk-or-…"
                     onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} />
              {/* Stacked, it would otherwise stretch the full width and read as
                  the most important thing on the card, which it is not. */}
              <button className="btn btn-primary h-[38px] justify-self-end sm:justify-self-auto">
                {t('common.save')}
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button key={p.name} type="button"
                        className="badge hover:border-accent/40 hover:text-accent"
                        onClick={() => setDraft({ ...draft, name: draft.name || p.name,
                                                  endpoint: p.endpoint })}>
                  {p.name}
                </button>
              ))}
            </div>
            <More text={t('models.key_hint')} />
          </form>
        )}
      </Card>

      {bindings.busy && !bindings.data ? <Skeleton rows={4} /> : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {roles.map((r) => (
          <RoleBinding key={r.role}
                       role={{ key: r.role, kind: r.kind, builtin: r.builtin !== false,
                               ext: r.ext, description: r.description,
                               ...(PRESENTATION[r.role] || GENERIC) }}
                       forest={forest}
                       providers={providers.data || []}
                       binding={bound.find((b) => b.role === r.role)}
                       catalogue={catalogue} loadCatalogue={load}
                       onSaved={refresh} onError={setError} />
        ))}
      </div>

      <Gauntlet forest={forest} providers={providers.data || []}
                binding={bound.find((b) => b.role === 'embed')}
                catalogue={catalogue} loadCatalogue={load}
                onSaved={refresh} onError={setError} />

      <AnswerStore forest={forest} onError={setError} />

      {/* J.3.2: who this provider list answers to. One line, and the rule
          behind it a tap away. */}
      <Folded text={t('models.scope_note')} />
    </div>
  )
}

/** The answer store (J.10.7) — the cache in front of `answer`.
 *
 *  Beside the bindings rather than among them, because it is not one: it
 *  spends nothing and serves what a binding already bought. Its switches
 *  live with its economy, because the numbers are the reason the switches
 *  exist — hits, and the money not spent, are what an operator weighs when
 *  sizing the bound. The saving shows a dash when the provider states no
 *  price: silence is never rendered as $0.00 (J.10.4).
 */
function AnswerStore({ forest, onError }) {
  const { t } = useI18n()
  const status = useAsync(() => api.answerCache(forest), [forest])
  const [form, setForm] = useState(null)
  const [clearing, setClearing] = useState(false)

  useEffect(() => {
    const s = status.data?.settings
    if (s) setForm({ enabled: !!s.enabled, max_entries: s.max_entries,
                     ttl_hours: s.ttl_hours ?? '' })
  }, [status.data])

  const [save, saving, saved] = useSave(async () => {
    try {
      await api.setAnswerCache({
        forest,
        enabled: form.enabled,
        max_entries: Number(form.max_entries) || 1,
        ttl_hours: form.ttl_hours === '' ? null : Number(form.ttl_hours),
      })
      status.reload()
    } catch (err) { onError(err); throw err }
  })

  async function clear() {
    setClearing(true)
    try { await api.setAnswerCache({ forest, clear: true }); status.reload() }
    catch (err) { onError(err) } finally { setClearing(false) }
  }

  const s = status.data?.settings
  const stats = status.data?.stats
  const dirty = !!s && !!form && (form.enabled !== !!s.enabled
    || Number(form.max_entries) !== s.max_entries
    || (form.ttl_hours === '' ? null : Number(form.ttl_hours)) !== (s.ttl_hours ?? null))

  return (
    <Card title={t('models.cache_title')} subtitle={t('models.cache_sub')} icon={Ask}
          actions={s && (
            <Badge tone={s.enabled ? 'accent' : 'default'}>
              {t(s.enabled ? 'models.cache_on_badge' : 'models.cache_off_badge')}
            </Badge>
          )}>
      {status.error ? <ErrorNote error={status.error} onRetry={status.reload} />
        : !form ? <Skeleton rows={2} /> : (
        <>
          <form onSubmit={save} className="space-y-3">
            <Toggle checked={form.enabled}
                    onChange={(v) => setForm({ ...form, enabled: v })}
                    label={t('models.cache_enabled')}
                    hint={t('models.cache_enabled_hint')} />
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t('models.cache_bound')} type="number" min="1"
                     value={form.max_entries}
                     onChange={(e) => setForm({ ...form, max_entries: e.target.value })} />
              <Field label={t('models.cache_ttl')} type="number" min="1"
                     placeholder="—" value={form.ttl_hours}
                     onChange={(e) => setForm({ ...form, ttl_hours: e.target.value })} />
            </div>
            <More text={t('models.cache_ttl_hint')} />
            <div className="flex items-center justify-end gap-2">
              <button type="button" className="btn btn-sm btn-danger"
                      disabled={clearing || !stats?.held} onClick={clear}>
                <Trash size={13} /> {t('models.cache_clear')}
              </button>
              <SaveButton busy={saving} done={saved} dirty={dirty}
                          label={t('common.save')} />
            </div>
          </form>
          {stats && (
            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Metric label={t('models.cache_held')}
                      value={`${stats.held} / ${s?.max_entries ?? '—'}`} />
              <Metric label={t('models.cache_hits')} value={stats.hits}
                      tone="accent" />
              <Metric label={t('models.cache_misses')} value={stats.misses} />
              <Metric label={t('models.cache_saved')}
                      value={stats.avoided_usd != null
                        ? `$${stats.avoided_usd.toFixed(4)}` : '—'} />
            </div>
          )}
        </>
      )}
    </Card>
  )
}

/** The Gauntlet (Part K) — deliberately not a third role card.
 *
 *  `ingest` and `answer` are required for their feature to work at all; this
 *  one is an optimisation of navigation that already works without it, it
 *  carries a build step, and changing its model invalidates the index. A box
 *  that looked like the other two would say none of that.
 */
function Gauntlet({ forest, providers, binding, catalogue, loadCatalogue,
                    onSaved, onError }) {
  const { t } = useI18n()
  const [form, setForm] = useState({ provider: '', model: '' })
  const [building, setBuilding] = useState(false)
  /* J.13.4 (v0.84): a build is a J.9 job. It embeds every node, so on a
     ten-thousand-node forest the synchronous shape was a request no gateway
     on the path is patient enough to hold — and the operator's answer was a
     timeout over work that was still running. The board is the one the
     ingest console and the pill already read; this card only has to find
     its own run on it and follow it. */
  const board = useBoard(forest)
  const job = board.jobs.find((j) => j.mode === 'canopy') || null
  const running = job?.state === 'running'
  useAttend(forest, WATCH, running)
  const status = useAsync(() => api.canopy(forest), [forest, job?.state])
  const enabled = status.data?.enabled !== false

  async function toggle(next) {
    try { await api.setCanopy(forest, next); status.reload() }
    catch (err) { onError(err) }
  }

  useEffect(() => {
    setForm({ provider: binding?.provider || providers[0]?.name || '',
              model: binding?.model || '' })
  }, [binding, providers.length])

  const cat = catalogue[form.provider] || {}
  useEffect(() => {
    if (form.provider && !catalogue[form.provider]) loadCatalogue(form.provider)
  }, [form.provider, catalogue, loadCatalogue])

  const state = status.data?.state
  const tone = state === 'active' ? 'accent'
    : state === 'model-mismatch' ? 'danger' : 'default'

  const [save, saving, saved] = useSave(async () => {
    try {
      await api.bindModel({ forest, role: 'embed', ...form, max_tokens: 0 })
      onSaved(); status.reload()
    } catch (err) { onError(err); throw err }
  })

  const dirty = form.provider !== (binding?.provider || '')
    || form.model !== (binding?.model || '')

  async function build() {
    setBuilding(true)
    try {
      const started = await api.buildCanopy(forest)
      // The job goes on the board first-hand, so the pill announces it on
      // every console and the watcher takes over — the operator is free to
      // leave this page, which is the whole reason jobs exist. An older
      // Station answers the status synchronously and is not called a
      // failure for it.
      if (started?.job) noteJob(forest, started.job)
      status.reload()
    } catch (err) { onError(err) } finally { setBuilding(false) }
  }

  return (
    <Card title={t('gauntlet.title')} subtitle={t('gauntlet.sub')} icon={Chip}
          actions={<Badge tone={enabled ? tone : 'default'}>
            {enabled ? t(`gauntlet.state_${state || 'unknown'}`) : t('gauntlet.state_off')}
          </Badge>}>
      <Folded text={t('gauntlet.optional')} />

      {/* `items-end` misaligned these: only the model field carries a hint,
          so bottom-aligning pushed the provider select a line lower than its
          own label. Each control owns its row height instead, and the button
          drops to its own line rather than fighting two labelled fields. */}
      <form onSubmit={save} className="mt-4 space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label={t('models.providers')} value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value })}>
            <option value="" disabled>—</option>
            {providers.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </Select>
          <Combobox label={t('models.model')} value={form.model}
                    placeholder="bge-m3" busy={cat.busy}
                    empty={t('models.model_none')} hint={t('gauntlet.model_hint')}
                    options={(cat.models || []).map((m) => ({ value: m.id, meta: priceTag(m) }))}
                    onChange={(model) => setForm({ ...form, model })} />
        </div>
        <div className="flex justify-end">
          <SaveButton busy={saving} done={saved} dirty={dirty}
                      disabled={!form.provider || !form.model}
                      label={binding ? t('models.update') : t('models.bind')} />
        </div>
      </form>

      <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <Metric label={t('gauntlet.vectors')} value={status.data?.vectors ?? '—'} />
        <Metric label={t('gauntlet.index_model')} value={status.data?.index_model || '—'} />
        <Metric label={t('gauntlet.query_model')} value={status.data?.query_model || '—'} />
      </div>

      {state === 'model-mismatch' && (
        <div className="mt-3"><Note tone="warn">{t('gauntlet.mismatch')}</Note></div>
      )}

      {/* The run, while it is running: done over total off the job record,
          never a spinner that says only that something is happening. The
          cancel is the job's own (the pill and the Ingest console carry it),
          so this card follows and does not duplicate it. */}
      {running && (
        <div className="mt-4">
          <div className="flex items-center justify-between text-[12.5px]">
            <span className="font-medium text-text">
              {t('gauntlet.job_progress', { done: job.done || 0,
                                            total: job.total || 0 })}
            </span>
            <span className="text-text-3">
              {Math.min(100, Math.round(((job.done || 0)
                                         / Math.max(job.total || 0, 1)) * 100))}%
            </span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-accent transition-[width] duration-500"
                 style={{ width: `${Math.min(100, Math.round(((job.done || 0)
                   / Math.max(job.total || 0, 1)) * 100))}%` }} />
          </div>
        </div>
      )}
      {/* J.13.4: a cancelled build is not resumable in v0.84 — the forest
          keeps the index it had, and the next build starts over and pays
          again. An index in two states is worse than no index, and a
          half-built one would be indistinguishable from a complete index
          over a smaller forest. */}
      {job?.state === 'cancelled' && (
        <div className="mt-3"><Note tone="warn">{t('gauntlet.build_cancelled')}</Note></div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3
                      border-t border-line pt-4">
        <Toggle checked={enabled} onChange={toggle}
                label={t('gauntlet.enabled')} hint={t('gauntlet.enabled_hint')} />
        <button type="button" className="btn ml-auto" onClick={build}
                disabled={building || running || !binding}>
          {building || running ? <Spinner label={t('gauntlet.building')} />
                    : status.data?.vectors ? t('gauntlet.rebuild') : t('gauntlet.build')}
        </button>
      </div>
      <div className="mt-2"><More text={t('gauntlet.build_hint')} /></div>
    </Card>
  )
}

function RoleBinding({ role, forest, providers, binding, catalogue, loadCatalogue,
                       onSaved, onError }) {
  const { t } = useI18n()
  const [form, setForm] = useState({ provider: '', model: '', max_tokens: 600,
                                     reasoning: 'off' })

  useEffect(() => {
    setForm({
      provider: binding?.provider || providers[0]?.name || '',
      model: binding?.model || '',
      max_tokens: binding?.max_tokens || role.defaultTokens,
      reasoning: binding?.reasoning || 'off',
    })
  }, [binding, providers.length, role.key, role.defaultTokens])

  // Ask the selected provider what it serves, once. Both role cards read the
  // same cache, so choosing the same provider twice costs one round trip.
  const cat = catalogue[form.provider] || {}
  useEffect(() => {
    if (form.provider && !catalogue[form.provider]) loadCatalogue(form.provider)
  }, [form.provider, catalogue, loadCatalogue])

  // A model belonging to a different provider is the failure this picker
  // exists to prevent, and it stays possible by hand — so it is flagged
  // rather than blocked: catalogues under-report, and a warning that can be
  // ignored is right where a refusal would be wrong.
  const stray = form.model && cat.models?.length
    && !cat.models.some((m) => m.id === form.model)

  const [save, saving, saved] = useSave(async () => {
    try { await api.bindModel({ forest, role: role.key, ...form }); onSaved() }
    catch (err) { onError(err); throw err }
  })

  // The form's shape follows the role's `kind` (L.6 rule 1): a transcription
  // binding is a multipart upload with no reply and no reasoning, and a
  // field that means nothing is a field somebody will tune.
  const chatShaped = CHAT_SHAPED.has(role.kind || 'chat')

  // Compared against what is bound, field by field, so "Update" lights up
  // for a reply-length tweak and not for re-selecting the same model.
  const dirty = form.provider !== (binding?.provider || '')
    || form.model !== (binding?.model || '')
    || (chatShaped && form.reasoning !== (binding?.reasoning || 'off'))
    || (chatShaped
        && Number(form.max_tokens) !== Number(binding?.max_tokens ?? role.defaultTokens))

  const title = role.builtin ? t(`models.role_${role.key}`) : role.key
  const subtitle = role.builtin ? t(`models.role_${role.key}_sub`)
    : (role.description || t('models.role_ext_sub', { ext: role.ext }))

  return (
    <Card title={title} subtitle={subtitle}
          icon={role.icon}
          actions={<>
            {!role.builtin && <Badge>{t('models.role_from', { ext: role.ext })}</Badge>}
            {binding ? <Badge tone="accent">{t('models.bound')}</Badge>
                     : <Badge>{t('models.unbound')}</Badge>}
          </>}>
      <form onSubmit={save} className="space-y-3">
        <Select label={t('models.providers')} value={form.provider} required
                onChange={(e) => setForm({ ...form, provider: e.target.value })}>
          <option value="" disabled>—</option>
          {providers.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
        </Select>
        <Combobox
          label={t('models.model')} value={form.model} required
          placeholder={t('models.model_ph')}
          busy={cat.busy}
          empty={cat.models ? t('models.model_none') : t('models.model_test_first')}
          hint={cat.models ? t('models.model_hint', { n: cat.models.length })
                           : t('models.model_test_first')}
          options={(cat.models || []).map((m) => ({ value: m.id, meta: priceTag(m) }))}
          onChange={(model) => setForm({ ...form, model })}
        />
        {stray && <Note tone="warn">{t('models.model_stray', { provider: form.provider })}</Note>}
        {!role.builtin && (
          <p className="text-[12px] text-text-3">{t(`models.kind_${role.kind || 'chat'}`)}</p>
        )}
        {/* Two columns only once there is room for them: at 375px the
            reply-length label wrapped to two lines while its neighbour did
            not, and the reasoning select clipped its own option mid-word. */}
        {chatShaped && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('models.max_tokens')} type="number" min="64"
                   hint={t('models.max_tokens_hint')} value={form.max_tokens}
                   onChange={(e) => setForm({ ...form, max_tokens: Number(e.target.value) })} />
            <Select label={t('models.reasoning')} value={form.reasoning}
                    onChange={(e) => setForm({ ...form, reasoning: e.target.value })}>
              <option value="off">{t('models.reasoning_off')}</option>
              <option value="on">{t('models.reasoning_on')}</option>
            </Select>
          </div>
        )}
        {/* Actions right, where a form's actions live: the eye leaves the
            last field on the right and lands on them. */}
        <div className="flex flex-wrap justify-end gap-2 border-t border-line pt-3">
          {binding && (
            <button type="button" className="btn"
                    onClick={() => api.bindModel({ forest, role: role.key, remove: true })
                      .then(onSaved).catch(onError)}>
              {t('models.unbind')}
            </button>
          )}
          <SaveButton busy={saving} done={saved} dirty={dirty}
                      disabled={!form.provider || !form.model}
                      label={binding ? t('models.update') : t('models.bind')} />
        </div>
      </form>
    </Card>
  )
}
