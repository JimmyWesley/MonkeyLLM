// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The Webhooks console (spec J.16.5) — what this forest tells your other
 * tools, and when.
 *
 * Every other console in the Build group is about what comes in (Ingest) or
 * who reads it (Models). This one is the third direction: out. It is also
 * the only console whose subject leaves the Station's authority behind, so
 * two things are said here rather than assumed —
 *
 *   1. **What travels is shown before it is subscribed to.** Picking an
 *      event renders the exact body that event will POST, including whether
 *      the metadata opt-in is on. An integration is built against a shape,
 *      and an operator who cannot see the shape builds against a guess.
 *   2. **The opt-in explains itself where it is set.** `include_metadata`
 *      sends curated text to an address no grant governs; a checkbox
 *      labelled "include metadata" would be a decision made in the dark.
 *
 * The catalogue is served (J.16.3), never hard-coded here: the console
 * renders what the Station says exists, and translates only the line that
 * explains each event.
 */
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { useRouteState } from '../router.js'
import {
  Badge, Card, CheckList, Code, CopyButton, Empty, ErrorNote, Field, Modal,
  Note, Segmented, Select, Skeleton, Table, Tabs, Td, TextArea, Toggle,
} from '../design/ui.jsx'
import {
  Alert, Check, ChevronLeft, Clock, Code2, Key, Play, Plus, Refresh, Trash,
  Webhook as WebhookIcon, X,
} from '../design/icons.jsx'
import { NeedsCapability, has, useAsync } from './shared.jsx'

/** The address of the "not saved yet" webhook. A sentinel rather than a
 *  separate boolean, so the form is a place the operator can be at, can
 *  link to, and can leave with Back (J.5.8). */
const DRAFT = 'new'

const TABS = ['settings', 'deliveries']

/** What each event's `data` looks like, so the preview is the real shape
 *  rather than a description of it. Identity only — the same rule the
 *  Station enforces, restated here because this is where somebody decides
 *  whether the payload is enough for what they want to build. */
const SAMPLE = {
  'node.planted': { node: 'projects/acme/contract-2026', type: 'document', parent: 'projects/acme/_index', source: 'upload', commit: 'a0d2393c' },
  'node.grafted': { node: 'projects/acme/contract-2026', operations: ['append_section'], commit: 'a0d2393c' },
  'branch.created': { node: 'projects/acme/_index', type: 'branch', parent: 'projects/_index', source: 'manual', commit: 'a0d2393c' },
  'dataset.created': { node: 'finance/ledger-2026', type: 'dataset', parent: 'finance/_index', source: 'upload', commit: 'a0d2393c' },
  'dataset.changed': { node: 'finance/ledger-2026', rows_affected: 3, commit: 'a0d2393c' },
  'ingest.started': { job: 'ing-8f21ab04', mode: 'upload', total: 42 },
  'ingest.finished': { job: 'ing-8f21ab04', mode: 'upload', total: 42, commit: 'a0d2393c', curated: true, planted: 39, updated: 2, unchanged: 1, unsupported: 0, errors: 0, stale: 0 },
  'ingest.failed': { job: 'ing-8f21ab04', mode: 'sync', done: 12, total: 42, code: 'E_LOCKED' },
  'ingest.cancelled': { job: 'ing-8f21ab04', mode: 'adopt', done: 12, total: 42, planted: 12 },
  'ingest.document.failed': { job: 'ing-8f21ab04', document: 'q3/report.docx', index: 12, total: 42 },
  'answer.served': { mode: 'sweep', cached: false, evidence: 5, cost: { usd: 0.0021, prompt_tokens: 1840, completion_tokens: 260 } },
  'answer.failed': { code: 'E_TIMEOUT' },
  'access.denied': { primitive: 'plant', code: 'E_FORBIDDEN' },
  'grant.changed': { principal: 'maria', caps: ['read', 'query'], branches: 2 },
  'model.bound': { role: 'answer', provider: 'openrouter', model: 'anthropic/claude-sonnet-5', removed: false },
  'snapshot.created': { name: 'demo-20260820-1402.forest', bytes: 1843200, payloads: 4, payloads_omitted: 0 },
  'canopy.built': { embedded: 82, nodes: 82, stale: 0, model: 'text-embedding-3-large', refresh: false },
  'reindex.finished': { nodes: 82, ms: 143.2 },
  // Two passes fire this one and they do not carry the same fields: the
  // J.13.6.1 scent re-curation runs as a J.9 job (so `job`) and calls a
  // model per node (so `fallbacks`, the nodes where the Curator did not
  // answer), while the G.2.6 alias re-derivation runs on the lane and does
  // neither — its `data` is `{scanned, changed, derive}` alone. The sample
  // shows the fuller one; a receiver must read the fields it needs rather
  // than assume every field is there.
  'recurate.finished': { scanned: 1877, changed: 41, fallbacks: 3, derive: ['scent'], job: 'ing-8f21ab04' },
  'auth.login.succeeded': { username: 'maria', host: '203.0.113.9' },
  'auth.login.failed': { username: 'maria', host: '203.0.113.9' },
  'pair.issued': { principal: 'maria', caps: ['ingest', 'read'], prefix: 'mk_7Fq2x', expires_in_days: 90 },
  'key.issued': { principal: 'ci-bot', label: 'nightly', prefix: 'mk_7Fq2x', expires_in_days: 365 },
  'key.revoked': { principal: 'ci-bot', key: 'mk_7Fq2x' },
  'provider.changed': { name: 'openrouter', endpoint: 'https://openrouter.ai/api/v1', removed: false, key_supplied: true },
  'forest.created': { forest: 'acme', title: 'Acme', seed: null, commit: 'a0d2393c' },
}

/** The two fields the opt-in adds, and only on events that name a node —
 *  which is exactly what the Station does (J.16.1 rule 3). */
const METADATA_SAMPLE = {
  title: 'Contract renewal — Acme 2026',
  summary: 'Annual renewal with a 99.9% SLA and an inflation-linked adjustment.',
}
const CARRIES_METADATA = new Set(['node.planted', 'branch.created', 'dataset.created'])

const VERIFY = {
  node: (secret) => `import crypto from 'node:crypto'

const SECRET = '${secret}'

// Hash the RAW body, before any JSON parsing:
// parsed-and-restringified is not the same bytes.
export function verify(raw, headers) {
  const at = headers['x-monkeyllm-timestamp']
  const mac = crypto.createHmac('sha256', SECRET)
    .update(at + '.' + raw).digest('hex')
  const sent = headers['x-monkeyllm-signature']
  if (sent !== 'sha256=' + mac) return false
  // The timestamp is signed, so a captured
  // body cannot be replayed as a new event.
  return Math.abs(Date.now() / 1e3 - +at) < 300
}`,
  python: (secret) => `import hashlib, hmac, time

SECRET = "${secret}".encode()

def verify(raw: bytes, headers) -> bool:
    at = headers["X-MonkeyLLM-Timestamp"]
    mac = hmac.new(
        SECRET, at.encode() + b"." + raw,
        hashlib.sha256).hexdigest()
    sent = headers.get("X-MonkeyLLM-Signature", "")
    if not hmac.compare_digest(f"sha256={mac}", sent):
        return False
    # Signed timestamp: no replay of an old body.
    return abs(time.time() - int(at)) < 300`,
}

const hostOf = (url) => { try { return new URL(url).host } catch { return url } }

/** The dot beside a webhook, and the one word under it. Four states, because
 *  "off" and "suspended" are not the same fact: one is a decision, the other
 *  is the Station reporting that it stopped (J.16.4). */
function statusOf(hook) {
  if (hook.suspended) return { tone: 'danger', key: `suspended_${hook.suspended}` }
  if (!hook.enabled) return { tone: 'muted', key: 'state_off' }
  if (hook.last_status && hook.last_status >= 300) return { tone: 'warn', key: 'state_failing' }
  if (hook.last_status) return { tone: 'ok', key: 'state_live' }
  return { tone: 'muted', key: 'state_new' }
}

const DOT = {
  ok: 'bg-ok', warn: 'bg-warn', danger: 'bg-danger', muted: 'bg-line-strong',
}

export default function Webhooks({ forest, grant }) {
  const { t } = useI18n()
  const [selected, select] = useRouteState('hook', '')
  const [tab, setTab] = useRouteState('tab', 'settings', { allow: TABS })
  const [secret, setSecret] = useState(null)

  const board = useAsync(() => api.webhooks(forest), [forest],
                         { skip: !has(grant, 'admin') })

  if (!has(grant, 'admin')) {
    return <NeedsCapability message={t('webhooks.needs_admin')} hint={t('cap.admin')} />
  }
  if (board.busy) return <Card><Skeleton rows={6} /></Card>
  if (board.error) {
    return <Card title={t('webhooks.title')} icon={WebhookIcon}>
      <ErrorNote error={board.error} onRetry={board.reload} />
    </Card>
  }

  const { webhooks = [], events = [], groups = [], scopes = [], limits = {},
          queue = {} } = board.data || {}
  const hook = selected === DRAFT ? null
    : webhooks.find((w) => w.id === selected) || null
  const editing = selected === DRAFT || hook

  return (
    <div className="space-y-4">
      {editing ? (
        <Detail forest={forest} hook={hook} events={events} groups={groups}
                scopes={scopes} limits={limits} tab={tab} setTab={setTab}
                onBack={() => select('')} onSecret={setSecret}
                onSaved={(id) => { board.reload(); select(id) }}
                onDeleted={() => { board.reload(); select('') }} />
      ) : (
        <List forest={forest} webhooks={webhooks} queue={queue} limits={limits}
              onOpen={(id) => { setTab('settings'); select(id, { push: true }) }}
              onChanged={board.reload} />
      )}
      <SecretModal secret={secret} onClose={() => setSecret(null)} />
    </div>
  )
}

/* ── the list ─────────────────────────────────────────────────────────── */

function List({ forest, webhooks, queue, limits, onOpen, onChanged }) {
  const { t } = useI18n()
  const [error, setError] = useState(null)

  async function setEnabled(hook, enabled) {
    setError(null)
    try {
      // `headers` is deliberately absent: the API returns names, never
      // values, so a round trip through this console would send the map
      // back as a list of names and delete every value in it. Absent means
      // "keep what is stored" (J.16.4).
      await api.saveWebhook(forest, {
        id: hook.id, url: hook.url, events: hook.events, label: hook.label,
        branches: hook.branches, include_metadata: hook.include_metadata,
        enabled,
      })
      onChanged()
    } catch (e) { setError(e) }
  }

  return (
    <Card title={t('webhooks.title')} subtitle={t('webhooks.sub')}
          icon={WebhookIcon}
          actions={
            <button className="btn btn-primary btn-sm" onClick={() => onOpen(DRAFT)}>
              <Plus size={14} /> {t('webhooks.new')}
            </button>}>
      <ErrorNote error={error} />

      {webhooks.length === 0 ? (
        <Recipes t={t} onNew={() => onOpen(DRAFT)} />
      ) : (
        <div className="space-y-2">
          {webhooks.map((hook) => {
            const state = statusOf(hook)
            return (
              <div key={hook.id}
                   className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg
                              border border-line bg-surface-2 px-3 py-2.5">
                <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[state.tone]}`}
                      aria-hidden="true" />
                <button type="button" onClick={() => onOpen(hook.id)}
                        className="min-w-0 flex-1 text-left">
                  <span className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate text-[13.5px] font-medium text-text">
                      {hook.label || hostOf(hook.url)}
                    </span>
                    <span className={`shrink-0 text-[11.5px] ${
                      state.tone === 'danger' ? 'text-danger'
                        : state.tone === 'warn' ? 'text-warn' : 'text-text-3'}`}>
                      {t(`webhooks.${state.key}`)}
                    </span>
                  </span>
                  <span className="block truncate font-mono text-[11.5px] text-text-3">
                    {hook.url}
                  </span>
                </button>
                <div className="flex shrink-0 items-center gap-2">
                  {hook.scope === '-' && (
                    <Badge tone="accent">{t('webhooks.scope_deployment')}</Badge>
                  )}
                  <Badge>{t('webhooks.n_events', { n: hook.events.length })}</Badge>
                  <Toggle checked={hook.enabled} label=""
                          onChange={(v) => setEnabled(hook, v)} />
                </div>
              </div>
            )
          })}
        </div>
      )}

      {(queue.pending > 0 || queue.dropped > 0) && (
        <div className="mt-4">
          <Note tone={queue.dropped > 0 ? 'warn' : 'info'}>
            {t('webhooks.queue', { pending: queue.pending || 0,
                                   dropped: queue.dropped || 0 })}
          </Note>
        </div>
      )}
      {webhooks.length > 0 && (
        <p className="mt-3 text-[11.5px] text-text-3">
          {t('webhooks.delivery_rules', {
            attempts: limits.attempts, suspend: limits.suspend_after,
            timeout: limits.timeout_seconds })}
        </p>
      )}
    </Card>
  )
}

/** The empty state carries the reason to be here at all. Three shapes an
 *  operator recognises, so "what would I even use this for" is answered
 *  before the form is opened. */
function Recipes({ t, onNew }) {
  const recipes = ['chat', 'automation', 'service']
  return (
    <Empty icon={WebhookIcon} title={t('webhooks.empty')}
           action={<button className="btn btn-primary" onClick={onNew}>
             <Plus size={14} /> {t('webhooks.new')}
           </button>}>
      <span className="block">{t('webhooks.empty_hint')}</span>
      <span className="mt-4 grid gap-2 text-left sm:grid-cols-3">
        {recipes.map((key) => (
          <span key={key} className="rounded-lg border border-line bg-surface-2 p-3">
            <span className="block text-[12.5px] font-medium text-text">
              {t(`webhooks.recipe.${key}`)}
            </span>
            <span className="mt-0.5 block text-[11.5px] leading-relaxed text-text-3">
              {t(`webhooks.recipe.${key}_hint`)}
            </span>
          </span>
        ))}
      </span>
    </Empty>
  )
}

/* ── one webhook ──────────────────────────────────────────────────────── */

function Detail({ forest, hook, events, groups, scopes, limits, tab, setTab,
                  onBack, onSecret, onSaved, onDeleted }) {
  const { t } = useI18n()
  const fresh = !hook

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button className="btn btn-sm btn-ghost" onClick={onBack}>
          <ChevronLeft size={14} /> {t('webhooks.all')}
        </button>
        {!fresh && (
          <span className="font-mono text-[11.5px] text-text-3">{hook.id}</span>
        )}
      </div>

      {fresh ? (
        <Settings forest={forest} hook={null} events={events} groups={groups}
                  scopes={scopes} limits={limits} onSecret={onSecret}
                  onSaved={onSaved} onDeleted={onDeleted} />
      ) : (
        <>
          <Tabs value={tab} onChange={setTab} options={[
            { value: 'settings', label: t('webhooks.tab_settings'), icon: Code2 },
            { value: 'deliveries', label: t('webhooks.tab_deliveries'), icon: Clock },
          ]} />
          {tab === 'deliveries'
            ? <Deliveries forest={forest} hook={hook} limits={limits} />
            : <Settings forest={forest} hook={hook} events={events}
                        groups={groups} scopes={scopes} limits={limits}
                        onSecret={onSecret} onSaved={onSaved}
                        onDeleted={onDeleted} />}
        </>
      )}
    </div>
  )
}

const blank = (scopes) => ({
  label: '', url: '', events: [], branches: [], include_metadata: false,
  enabled: true, scope: scopes.includes('forest') ? 'forest' : 'deployment',
})

function Settings({ forest, hook, events, groups, scopes, limits, onSecret,
                    onSaved, onDeleted }) {
  const { t } = useI18n()
  const [form, setForm] = useState(() => hook
    ? { ...hook, scope: hook.scope === '-' ? 'deployment' : 'forest' }
    : blank(scopes))
  // `null` in a header value means "keep the stored one" — the only way an
  // editor that can never READ a value can leave it alone (J.16.4).
  const [headers, setHeaders] = useState(() =>
    (hook?.headers || []).map((name) => ({ name, value: null })))
  const [headersTouched, setHeadersTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)
  const [probe, setProbe] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (!saved) return undefined
    const id = setTimeout(() => setSaved(false), 2500)
    return () => clearTimeout(id)
  }, [saved])

  const set = (patch) => { setForm((f) => ({ ...f, ...patch })); setSaved(false) }

  // The catalogue, as the picker's groups. A group with nothing in it for
  // this scope is not rendered — an empty box teaches nothing.
  const byGroup = useMemo(() => {
    const scope = form.scope === 'deployment' ? 'deployment' : 'forest'
    const allowed = events.filter(
      (e) => scope === 'deployment' || e.scope === 'forest')
    return groups
      .map((group) => [group, allowed.filter((e) => e.group === group)])
      .filter(([, list]) => list.length > 0)
  }, [events, groups, form.scope])

  // Switching scope narrows what may be subscribed to, so the selection is
  // narrowed with it rather than being refused on save (J.16.2).
  const selectable = new Set(byGroup.flatMap(([, list]) => list.map((e) => e.event)))
  const chosen = form.events.filter((e) => selectable.has(e))

  const ready = form.url.trim() && chosen.length > 0

  async function save(e) {
    e?.preventDefault?.()
    setBusy(true); setError(null)
    try {
      const body = {
        ...(hook ? { id: hook.id } : { scope: form.scope }),
        url: form.url.trim(), events: chosen, label: form.label.trim(),
        branches: form.branches, include_metadata: form.include_metadata,
        enabled: form.enabled,
      }
      // Only when the operator actually opened the editor: absent means
      // "keep", and sending an untouched map back would be a write.
      if (headersTouched) {
        body.headers = Object.fromEntries(
          headers.filter((h) => h.name.trim())
            .map((h) => [h.name.trim(), h.value]))
      }
      const reply = await api.saveWebhook(forest, body)
      if (reply.secret) onSecret(reply.secret)
      setSaved(true)
      setHeadersTouched(false)
      onSaved(reply.webhook.id)
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  async function act(action, extra) {
    setBusy(true); setError(null); setProbe(null)
    try {
      const reply = await api.webhookAction(forest, hook.id, { action, ...extra })
      if (reply.secret) onSecret(reply.secret)
      if (reply.delivery) setProbe(reply.delivery)
      onSaved(hook.id)
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  async function remove() {
    setBusy(true); setError(null)
    try { await api.deleteWebhook(forest, hook.id); onDeleted() }
    catch (err) { setError(err); setBusy(false) }
  }

  return (
    <form onSubmit={save} className="grid gap-4 xl:grid-cols-[1fr_420px]">
      <div className="min-w-0 space-y-4">
        <Card title={hook ? t('webhooks.edit') : t('webhooks.new')}
              subtitle={t('webhooks.where_sub')} icon={WebhookIcon}>
          <div className="space-y-4">
            {hook?.suspended && (
              <Note tone="danger">
                <b className="text-text">{t(`webhooks.${statusOf(hook).key}`)}</b>{' '}
                {t(`webhooks.suspended_${hook.suspended}_hint`)}
              </Note>
            )}

            <Field label={t('webhooks.url')} value={form.url} required
                   placeholder="https://hooks.example.com/monkeyllm"
                   hint={t('webhooks.url_hint')}
                   onChange={(e) => set({ url: e.target.value })} />

            <Field label={t('webhooks.label')} value={form.label}
                   placeholder={t('webhooks.label_placeholder')}
                   hint={t('webhooks.label_hint')}
                   onChange={(e) => set({ label: e.target.value })} />

            {!hook && scopes.length > 1 && (
              <Select label={t('webhooks.scope')} value={form.scope}
                      hint={t(`webhooks.scope_${form.scope}_hint`)}
                      onChange={(e) => set({ scope: e.target.value })}>
                <option value="forest">
                  {t('webhooks.scope_forest_option', { forest })}
                </option>
                <option value="deployment">{t('webhooks.scope_deployment_option')}</option>
              </Select>
            )}

            <Toggle checked={form.enabled} label={t('webhooks.enabled')}
                    hint={t('webhooks.enabled_hint')}
                    onChange={(v) => set({ enabled: v })} />
          </div>
        </Card>

        <Card title={t('webhooks.events')} subtitle={t('webhooks.events_sub')}
              icon={Play}>
          <div className="grid gap-4 sm:grid-cols-2">
            {byGroup.map(([group, list]) => (
              <CheckList key={group}
                         label={t(`webhooks.group.${group}`)}
                         hint={t(`webhooks.group.${group}_hint`)}
                         allLabel={t('webhooks.all_of_group')}
                         filterPlaceholder={t('webhooks.filter')}
                         empty={t('webhooks.no_events')}
                         max="11rem"
                         options={list.map((e) => ({
                           value: e.event, label: e.event,
                           meta: t(`webhooks.event.${e.event}`),
                         }))}
                         value={chosen.filter((e) =>
                           list.some((o) => o.event === e))}
                         onChange={(next) => set({
                           events: [
                             ...chosen.filter((e) => !list.some((o) => o.event === e)),
                             ...next,
                           ],
                         })} />
            ))}
          </div>
          {chosen.length === 0 && (
            <p className="mt-3 text-[12px] text-text-3">{t('webhooks.pick_one')}</p>
          )}
        </Card>

        <Card title={t('webhooks.narrowing')} subtitle={t('webhooks.narrowing_sub')}>
          <div className="space-y-4">
            <Field as={TextArea} rows={2} label={t('webhooks.branches')}
                   value={form.branches.join('\n')}
                   placeholder={'projects/\nfinance/'}
                   hint={t('webhooks.branches_hint')}
                   onChange={(e) => set({
                     branches: e.target.value.split('\n')
                       .map((s) => s.trim()).filter(Boolean),
                   })} />

            <div className="rounded-lg border border-line bg-surface-2 p-3">
              <Toggle checked={form.include_metadata}
                      label={t('webhooks.metadata')}
                      hint={t('webhooks.metadata_hint')}
                      onChange={(v) => set({ include_metadata: v })} />
              <p className="mt-2 pl-[42px] text-[11.5px] leading-relaxed text-text-3">
                {t('webhooks.metadata_note')}
              </p>
            </div>

            <HeadersEditor headers={headers} limits={limits}
                           onChange={(next) => {
                             setHeaders(next); setHeadersTouched(true); setSaved(false)
                           }} />
          </div>
        </Card>

        <div className="flex flex-wrap items-center gap-2">
          <button className="btn btn-primary" disabled={busy || !ready}>
            {saved ? <><Check size={14} /> {t('common.saved')}</>
              : busy ? t('common.saving')
              : hook ? t('common.save') : t('webhooks.create')}
          </button>
          {hook && (
            <>
              <button type="button" className="btn" disabled={busy}
                      onClick={() => act('test')}>
                <Play size={14} /> {t('webhooks.test')}
              </button>
              <button type="button" className="btn" disabled={busy}
                      onClick={() => act('rotate')}>
                <Key size={14} /> {t('webhooks.rotate')}
              </button>
              <button type="button" className="btn btn-ghost ml-auto text-danger"
                      disabled={busy} onClick={() => setConfirmDelete(true)}>
                <Trash size={14} /> {t('webhooks.delete')}
              </button>
            </>
          )}
        </div>

        <ErrorNote error={error} />
        {probe && <Probe record={probe} onClose={() => setProbe(null)} />}
      </div>

      <div className="min-w-0 space-y-4">
        <Preview events={chosen} forest={forest} scope={form.scope}
                 includeMetadata={form.include_metadata} />
        {hook && <Verify />}
      </div>

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)}
             title={t('webhooks.delete_title')}
             subtitle={t('webhooks.delete_sub')}
             footer={
               <>
                 <button type="button" className="btn"
                         onClick={() => setConfirmDelete(false)}>
                   {t('common.cancel')}
                 </button>
                 <button type="button" className="btn btn-danger" disabled={busy}
                         onClick={remove}>
                   <Trash size={14} /> {t('webhooks.delete')}
                 </button>
               </>}>
        <p className="text-[13px] text-text-2">
          {t('webhooks.delete_body', { url: hook?.url || '' })}
        </p>
      </Modal>
    </form>
  )
}

/** Header values are write-only, so this editor never claims to show one:
 *  a stored header reads as "kept" until somebody types over it, and typing
 *  over it is the only way to change it (J.16.4). */
function HeadersEditor({ headers, limits, onChange }) {
  const { t } = useI18n()
  const max = limits.max_headers || 5
  const edit = (i, patch) =>
    onChange(headers.map((h, j) => (i === j ? { ...h, ...patch } : h)))

  return (
    <div>
      <span className="label">{t('webhooks.headers')}</span>
      <div className="space-y-2">
        {headers.map((h, i) => (
          <div key={i} className="flex items-center gap-2">
            <input className="field flex-1" value={h.name} placeholder="Authorization"
                   onChange={(e) => edit(i, { name: e.target.value })} />
            <input className="field flex-1" type="password"
                   value={h.value === null ? '' : h.value}
                   placeholder={h.value === null ? t('webhooks.header_kept')
                     : t('webhooks.header_value')}
                   onChange={(e) => edit(i, { value: e.target.value })} />
            <button type="button" className="btn btn-sm btn-ghost"
                    aria-label={t('webhooks.remove_header')}
                    onClick={() => onChange(headers.filter((_, j) => j !== i))}>
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
      {headers.length < max && (
        <button type="button" className="btn btn-sm mt-2"
                onClick={() => onChange([...headers, { name: '', value: '' }])}>
          <Plus size={13} /> {t('webhooks.add_header')}
        </button>
      )}
      <span className="mt-1 block text-[11.5px] text-text-3">
        {t('webhooks.headers_hint', { n: max })}
      </span>
    </div>
  )
}

/** The body, before it is subscribed to (J.16.5). */
function Preview({ events, forest, scope, includeMetadata }) {
  const { t } = useI18n()
  const [shown, setShown] = useState(null)
  const event = events.includes(shown) ? shown : events[0]

  if (!events.length) {
    return (
      <Card title={t('webhooks.preview')} icon={Code2}>
        <p className="text-[12.5px] text-text-3">{t('webhooks.preview_empty')}</p>
      </Card>
    )
  }

  const data = { ...(SAMPLE[event] || {}) }
  if (includeMetadata && CARRIES_METADATA.has(event)) Object.assign(data, METADATA_SAMPLE)
  const body = {
    id: 'whd-9f31c2a4e70b',
    event,
    forest: scope === 'deployment' ? '-' : forest,
    at: '2026-08-20T14:02:11Z',
    principal: 'maria',
    data,
  }

  return (
    <Card title={t('webhooks.preview')} subtitle={t('webhooks.preview_sub')}
          icon={Code2}>
      {events.length > 1 && (
        <div className="mb-3">
          <Select value={event} onChange={(e) => setShown(e.target.value)}
                  aria-label={t('webhooks.preview')}>
            {events.map((e) => <option key={e} value={e}>{e}</option>)}
          </Select>
        </div>
      )}
      <Code lang="json" max="18rem">{JSON.stringify(body, null, 2)}</Code>
      <p className="mt-2 text-[11.5px] leading-relaxed text-text-3">
        {t('webhooks.preview_note')}
      </p>
      <div className="mt-3 rounded-lg border border-line bg-surface-2 p-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.06em] text-text-3">
          {t('webhooks.headers_sent')}
        </p>
        <Code max="9rem" className="mt-2">{[
          'X-MonkeyLLM-Event: ' + event,
          'X-MonkeyLLM-Delivery: whd-9f31c2a4e70b',
          'X-MonkeyLLM-Attempt: 1',
          'X-MonkeyLLM-Forest: ' + (scope === 'deployment' ? '-' : forest),
          'X-MonkeyLLM-Timestamp: 1786370531',
          'X-MonkeyLLM-Signature: sha256=8f21…',
        ].join('\n')}</Code>
      </div>
    </Card>
  )
}

function Verify() {
  const { t } = useI18n()
  const [lang, setLang] = useState('node')
  return (
    <Card title={t('webhooks.verify')} subtitle={t('webhooks.verify_sub')}
          icon={Key}>
      <Segmented value={lang} onChange={setLang} options={[
        { value: 'node', label: 'Node' }, { value: 'python', label: 'Python' },
      ]} />
      <div className="mt-3">
        <Code lang={lang === 'node' ? null : 'python'} max="20rem">
          {VERIFY[lang]('whsec_…')}
        </Code>
      </div>
    </Card>
  )
}

/** A test's answer is the whole answer: the status, the time, and what the
 *  endpoint said back. Reporting only success or failure would leave a 404
 *  on a wrong path and a proxy answering HTML indistinguishable (J.16.5). */
function Probe({ record, onClose }) {
  const { t } = useI18n()
  const tone = record.ok ? 'info' : 'danger'
  return (
    <div className={`rounded-lg border px-3 py-2.5 text-[12.5px] ${
      record.ok ? 'border-ok/25 bg-ok-soft' : 'border-danger/25 bg-danger-soft'}`}>
      <div className="flex items-start gap-2.5">
        {record.ok ? <Check size={15} className="mt-px text-ok" />
          : <Alert size={15} className="mt-px text-danger" />}
        <div className="min-w-0 flex-1">
          <p className={record.ok ? 'text-text' : 'text-danger'}>
            {record.ok ? t('webhooks.test_ok', { status: record.status,
                                                 ms: Math.round(record.ms) })
              : record.status
                ? t('webhooks.test_status', { status: record.status,
                                              ms: Math.round(record.ms) })
                : t('webhooks.test_unreachable')}
          </p>
          {(record.error || record.response) && (
            <Code max="8rem" className="mt-2">{record.error || record.response}</Code>
          )}
        </div>
        <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}
                aria-label={t('common.close')}>
          <X size={14} />
        </button>
      </div>
      <p className={`mt-1.5 pl-[25px] text-[11.5px] ${tone === 'danger'
        ? 'text-text-2' : 'text-text-3'}`}>
        {t('webhooks.test_note')}
      </p>
    </div>
  )
}

/* ── what actually went out ───────────────────────────────────────────── */

function Deliveries({ forest, hook, limits }) {
  const { t } = useI18n()
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const log = useAsync(() => api.webhook(forest, hook.id), [forest, hook.id])

  async function redeliver(delivery) {
    setBusy(delivery); setError(null)
    try {
      await api.webhookAction(forest, hook.id, { action: 'redeliver', delivery })
      log.reload()
    } catch (e) { setError(e) } finally { setBusy(null) }
  }

  if (log.busy) return <Card><Skeleton rows={5} /></Card>
  if (log.error) {
    return <Card><ErrorNote error={log.error} onRetry={log.reload} /></Card>
  }

  const rows = log.data?.deliveries || []
  return (
    <Card title={t('webhooks.tab_deliveries')} subtitle={t('webhooks.log_sub')}
          icon={Clock}
          actions={<button className="btn btn-sm" onClick={log.reload}>
            <Refresh size={14} /> {t('common.refresh')}
          </button>}>
      <ErrorNote error={error} />
      {rows.length === 0 ? (
        <Empty icon={Clock} title={t('webhooks.log_empty')}>
          {t('webhooks.log_empty_hint')}
        </Empty>
      ) : (
        <Table head={[t('webhooks.col_event'), t('webhooks.col_when'),
                      t('webhooks.col_status'), t('webhooks.col_attempt'), '']}>
          {rows.map((row, i) => (
            <tr key={`${row.delivery}-${row.attempt}-${i}`}>
              <Td>
                <span className="block font-mono text-[12px]">{row.event}</span>
                <span className="block font-mono text-[11px] text-text-3">
                  {row.delivery}
                </span>
              </Td>
              <Td className="whitespace-nowrap text-text-3">{row.ts}</Td>
              <Td>
                <span className={`badge ${row.status && row.status < 300
                  ? 'badge-accent' : 'badge-danger'}`}>
                  {row.status || t('webhooks.no_answer')}
                </span>
                <span className="mt-0.5 block text-[11px] tabular-nums text-text-3">
                  {Math.round(row.ms || 0)} ms
                </span>
                {(row.error || row.response) && (
                  <span className="mt-0.5 block max-w-[24ch] truncate font-mono
                                   text-[11px] text-text-3"
                        title={row.error || row.response}>
                    {row.error || row.response}
                  </span>
                )}
              </Td>
              <Td className="tabular-nums text-text-3">{row.attempt}</Td>
              <Td>
                <button className="btn btn-sm" disabled={busy === row.delivery}
                        onClick={() => redeliver(row.delivery)}>
                  <Refresh size={13} /> {t('webhooks.redeliver')}
                </button>
              </Td>
            </tr>
          ))}
        </Table>
      )}
      <p className="mt-3 text-[11.5px] text-text-3">
        {t('webhooks.log_bound', { n: limits.keep_deliveries })}
      </p>
    </Card>
  )
}

/** Once, and said so at the moment it is shown (J.5.4 / J.16.4). */
function SecretModal({ secret, onClose }) {
  const { t } = useI18n()
  return (
    <Modal open={Boolean(secret)} onClose={onClose}
           title={t('webhooks.secret_title')}
           subtitle={t('webhooks.secret_sub')}
           footer={<button className="btn btn-primary" onClick={onClose}>
             {t('webhooks.secret_kept')}
           </button>}>
      <div className="space-y-3">
        <Note tone="warn">{t('webhooks.secret_once')}</Note>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-lg border border-line
                           bg-surface-2 px-3 py-2 font-mono text-[12.5px]">
            {secret}
          </code>
          <CopyButton value={secret || ''} label={t('common.copy')} />
        </div>
        <p className="text-[12px] leading-relaxed text-text-3">
          {t('webhooks.secret_use')}
        </p>
      </div>
    </Modal>
  )
}
