// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The inbound trigger (spec J.20) — what tells this forest that its bucket
 * changed.
 *
 * Beside Webhooks in the Build group, and the reverse of it. A webhook
 * leaves the Station's authority behind, so J.16 rations what it may SAY; a
 * notification arrives with no authority at all, so J.20 rations what it may
 * CAUSE. That asymmetry is the whole console:
 *
 *   - **The authority is the signature and nothing else.** No principal, no
 *     key, no session. So the secret is shown exactly once, at creation, and
 *     can never be read back — J.16's custody rule for J.16's reason, and
 *     J.17's for a share token.
 *   - **What it may cause is one sentence**: refresh these keys of this
 *     forest's own recorded source. It cannot adopt, cannot change `dest`,
 *     cannot name a different source and cannot reach another forest. A
 *     permanent standing authority has to be small enough to read in one
 *     go, and this console prints that sentence where the secret is handed
 *     over.
 *   - **Signing is one rule in this product**, verified inbound and produced
 *     outbound: HMAC-SHA256 over `<timestamp>.<body>`, with the timestamp
 *     inside the signed string so a captured body cannot replay forever. The
 *     snippet below is therefore the same shape as the Webhooks console's
 *     verifier, read from the other end.
 *
 * The console shows the address to POST to, because the integrator writing
 * the Lambda or the n8n node is usually not the person who created the
 * subscription, and an address nobody can copy is an integration nobody
 * builds.
 */
import { useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Code, CopyButton, Empty, ErrorNote, Field, Modal, Note,
  Segmented, Skeleton, Table, Td,
} from '../design/ui.jsx'
import { Folded, More } from '../design/Disclosure.jsx'
import { Alert, Key, Plus, Refresh, Trash, X } from '../design/icons.jsx'
import { NeedsCapability, has, useAsync } from './shared.jsx'

/** The skew J.20 rule 1 admits, in seconds, until the host has answered.
 *
 *  The Station states its own (`limits.skew_seconds`, beside `max_keys` and
 *  the address), and what it says is what is rendered — J.8.5's rule, which
 *  this console follows rather than printing a number of its own that goes
 *  stale the day a deployment changes it. This is the value the product
 *  ships, so the sentence is right before the first answer lands and is the
 *  host's from then on. */
const SKEW = 300

const SIGN = {
  node: ({ url, id }) => `import crypto from 'node:crypto'

const SECRET = process.env.MONKEYLLM_NOTIFY_SECRET

// The body is the bytes you send — sign it, then send
// exactly those bytes. Re-stringified JSON is not them.
const body = JSON.stringify({ keys: ['handbook/2024/onboarding.md'] })
const at = Math.floor(Date.now() / 1000).toString()
const mac = crypto.createHmac('sha256', SECRET)
  .update(at + '.' + body).digest('hex')

await fetch('${url}', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-MonkeyLLM-Subscription': '${id}',
    'X-MonkeyLLM-Timestamp': at,
    'X-MonkeyLLM-Signature': 'sha256=' + mac,
  },
  body,
})`,
  python: ({ url, id }) => `import hashlib, hmac, json, os, time, urllib.request

SECRET = os.environ["MONKEYLLM_NOTIFY_SECRET"].encode()

body = json.dumps({"keys": ["handbook/2024/onboarding.md"]}).encode()
at = str(int(time.time()))
mac = hmac.new(SECRET, at.encode() + b"." + body,
               hashlib.sha256).hexdigest()

req = urllib.request.Request(
    "${url}", data=body, method="POST",
    headers={
        "Content-Type": "application/json",
        "X-MonkeyLLM-Subscription": "${id}",
        "X-MonkeyLLM-Timestamp": at,
        "X-MonkeyLLM-Signature": f"sha256={mac}",
    })
urllib.request.urlopen(req)`,
}

export default function Notify({ forest, grant }) {
  const { t } = useI18n()
  const [error, setError] = useState(null)
  const [secret, setSecret] = useState(null)
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [asked, setAsked] = useState(null)
  const [lang, setLang] = useState('python')

  const admin = has(grant, 'admin')
  const subs = useAsync(() => api.ingestSubscriptions(forest), [forest],
                        { skip: !admin })

  if (!admin) {
    return <NeedsCapability message={t('notify.needs_admin')} hint={t('cap.admin')} />
  }

  // The address the integrator POSTs to: the host's own path, made absolute
  // with the browser's origin — which is the Station this console is talking
  // to, and the only hostname that is right behind any proxy. Composed here
  // only until the listing answers, so the page is never blank.
  const limits = subs.data?.limits || {}
  const path = subs.data?.url
    || `/v1/forests/${encodeURIComponent(forest)}/ingest/notify`
  const url = `${location.origin}${path}`
  const skewMinutes = Math.max(1, Math.round((limits.skew_seconds ?? SKEW) / 60))
  const list = subs.data?.subscriptions || []
  const sample = list[0]?.id || 'sub-…'

  async function create(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const made = await api.createIngestSubscription(
        forest, label.trim() ? { label: label.trim() } : {})
      setLabel('')
      // The one response that carries it (J.20 rule 4). Nothing stores it,
      // nothing logs it, and the listing below will never show it again.
      // The id travels beside it, in the row the same answer carries, so the
      // modal can show the pair that has to be sent together.
      if (made.secret) {
        setSecret({ secret: made.secret, id: made.subscription?.id })
      }
      subs.reload()
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  async function remove(id) {
    setAsked(null)
    try { await api.deleteIngestSubscription(forest, id); subs.reload() }
    catch (err) { setError(err) }
  }

  return (
    <div className="space-y-4">
      {error && <Card><ErrorNote error={error} /></Card>}

      <Card title={t('notify.title')} subtitle={t('notify.sub')} icon={Refresh}>
        {/* The standing authority, in one line with the rest behind it:
            what it may CAUSE is the reason this console is careful, and it
            is still a sentence somebody has to be able to read whole. */}
        <Folded text={t('notify.causes')} />
        <div className="mt-3">
          <div className="label">{t('notify.url')}</div>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-lg border border-line
                             bg-surface-2 px-2.5 py-1.5 font-mono text-[12px]
                             text-text-2">{url}</code>
            <CopyButton value={url} label={t('common.copy')} />
          </div>
          <div className="mt-1.5"><More text={t('notify.url_hint')} /></div>
          {/* The ceiling is the deployment's and is read from its answer: a
              console that printed a number of its own would be wrong on the
              first deployment that raised it (J.8.5's rule). */}
          {limits.max_keys ? (
            <p className="mt-1 text-[12px] text-text-3">
              {t('notify.url_max', { n: limits.max_keys })}
            </p>
          ) : null}
        </div>
      </Card>

      <Card title={t('notify.list')} subtitle={t('notify.list_sub')} icon={Key}
            actions={<Badge>{list.length}</Badge>}>
        {subs.busy && !subs.data ? <Skeleton rows={2} />
          : subs.error ? <ErrorNote error={subs.error} onRetry={subs.reload} />
          : !list.length ? <Empty icon={Key}>{t('notify.none')}</Empty> : (
          <Table head={[t('notify.id'), t('notify.label'), t('notify.created'), '']}>
            {list.map((s) => (
              <tr key={s.id}>
                <Td className="font-mono text-[12px] text-text">{s.id}</Td>
                <Td className="text-text-2">{s.label || '—'}</Td>
                <Td className="whitespace-nowrap text-text-3">{s.created || '—'}</Td>
                <Td>
                  <div className="flex justify-end gap-1.5">
                    {asked === s.id ? (
                      <>
                        <button type="button" className="btn btn-sm btn-danger"
                                onClick={() => remove(s.id)}>
                          {t('notify.remove_confirm')}
                        </button>
                        <button type="button" className="btn btn-sm btn-ghost !p-1"
                                title={t('common.close')}
                                onClick={() => setAsked(null)}>
                          <X size={13} />
                        </button>
                      </>
                    ) : (
                      <button type="button" className="btn btn-sm btn-danger"
                              title={t('notify.remove')}
                              onClick={() => setAsked(s.id)}>
                        <Trash size={13} />
                      </button>
                    )}
                  </div>
                </Td>
              </tr>
            ))}
          </Table>
        )}
        {asked && <div className="mt-2"><Note tone="warn">{t('notify.remove_hint')}</Note></div>}

        {/* The hint lives OUTSIDE the grid: with it inside the field's cell,
            `items-end` aligned the button to the hint's baseline, a row
            below the input it belongs to. */}
        <form onSubmit={create}
              className="mt-5 grid gap-3 border-t border-line pt-4 sm:grid-cols-[minmax(0,1fr)_auto]
                         sm:items-end">
          <Field label={t('notify.label')} value={label} className="min-w-0"
                 placeholder={t('notify.label_ph')}
                 onChange={(e) => setLabel(e.target.value)} />
          <button className="btn btn-primary h-[38px] whitespace-nowrap" disabled={busy}>
            <Plus size={14} /> {busy ? t('common.saving') : t('notify.create')}
          </button>
        </form>
        <p className="mt-1.5 text-[12px] text-text-3">
          {t('notify.label_hint')} {t('notify.create_hint')}
        </p>
      </Card>

      <Card title={t('notify.sign')} subtitle={t('notify.sign_sub')} icon={Key}>
        <Segmented value={lang} onChange={setLang}
                   options={[{ value: 'python', label: 'Python' },
                             { value: 'node', label: 'Node' }]} />
        <div className="mt-3">
          <Code lang={lang === 'node' ? 'javascript' : 'python'}>
            {SIGN[lang]({ url, id: sample })}
          </Code>
        </div>
        {/* Three rules under one snippet used to be three boxes of prose
            between the code and the next card. Each states its own line and
            keeps the rest — the refusal one stays a warn, because an
            integrator debugging a 4xx has to find it. */}
        <div className="mt-3 space-y-1.5">
          <Folded text={t('notify.sign_headers')} />
          <Folded text={t('notify.sign_skew', { n: skewMinutes })} />
          <Folded text={t('notify.sign_refusal')} tone="warn" />
        </div>
      </Card>

      <Modal open={Boolean(secret)} onClose={() => setSecret(null)}
             title={t('notify.secret_title')} subtitle={t('notify.secret_sub')}
             footer={<button className="btn btn-primary"
                             onClick={() => setSecret(null)}>
               {t('notify.secret_kept')}
             </button>}>
        <Note tone="warn">
          <span className="flex items-center gap-1.5">
            <Alert size={13} /> {t('notify.secret_once')}
          </span>
        </Note>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <code className="min-w-0 flex-1 break-all rounded-lg border border-line
                           bg-surface-2 px-2.5 py-2 font-mono text-[12px] text-text">
            {secret?.secret}
          </code>
          <CopyButton value={secret?.secret || ''} label={t('common.copy')} />
        </div>
        {secret?.id && (
          <p className="mt-3 text-[12.5px] text-text-2">
            {t('notify.secret_id')}{' '}
            <code className="font-mono">{secret.id}</code>
          </p>
        )}
        <p className="mt-3 text-[12.5px] text-text-3">{t('notify.secret_use')}</p>
      </Modal>
    </div>
  )
}
