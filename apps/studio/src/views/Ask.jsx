import { useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Empty, ErrorNote, Note, Segmented, Spinner,
} from '../design/ui.jsx'
import { Ask as AskIcon, Sparkle } from '../design/icons.jsx'
import { NeedsCapability, NodeChip, has } from './shared.jsx'

/** The console that needs no explanation, which is why it is the landing one.
 *
 * Retrieval is scoped and deterministic and happens first; only then does the
 * forest's bound model read what was found (J.10.3). The evidence list is not
 * decoration — it is the set of nodes that were actually read. */
export default function Ask({ forest, grant, goto }) {
  const { t } = useI18n()
  const [question, setQuestion] = useState('')
  const [k, setK] = useState(3)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  if (!has(grant, 'read')) {
    return <NeedsCapability message={t('access.needs_admin')} hint={t('cap.read')} />
  }

  async function ask(text) {
    const q = (text ?? question).trim()
    if (!q) return
    setQuestion(q)
    setBusy(true); setError(null); setResult(null)
    const t0 = performance.now()
    try {
      const r = await api.call(forest, 'answer', { question: q, k })
      setResult({ ...r, ms: Math.round(performance.now() - t0) })
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  const noModel = error?.code === 'E_SCHEMA' && /no model is bound/i.test(error.message)

  return (
    <div className="space-y-4">
      <Card title={t('ask.title')} subtitle={t('ask.sub')} icon={AskIcon}>
        <form onSubmit={(e) => { e.preventDefault(); ask() }} className="space-y-3">
          <textarea
            className="field min-h-[92px] resize-y text-[14px] leading-relaxed"
            rows={3} autoFocus value={question}
            placeholder={t('ask.placeholder')}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); ask() }
            }}
          />
          {/* Settings left, action right — the same order every form on this
              console uses, so the button is always in the corner the eye
              already went to. */}
          <div className="flex flex-wrap items-center justify-end gap-3">
            <div className="mr-auto flex items-center gap-2">
              <span className="text-[11.5px] text-text-3">{t('ask.depth')}</span>
              <Segmented value={k} onChange={setK} options={[
                { value: 2, label: '2' }, { value: 3, label: '3' }, { value: 6, label: '6' },
              ]} />
            </div>
            {/* A keyboard shortcut is not advice on a phone. */}
            <span className="hidden text-[11.5px] text-text-3 sm:inline">
              {t('ask.hint_send')}
            </span>
            <button className="btn btn-primary" disabled={busy || !question.trim()}>
              <Sparkle size={15} />
              {busy ? t('ask.thinking') : t('ask.send')}
            </button>
          </div>
        </form>

        {!result && !busy && (
          <div className="mt-5 border-t border-line pt-4">
            <div className="label">{t('ask.examples')}</div>
            <div className="flex flex-wrap gap-2">
              {['ask.ex1', 'ask.ex2', 'ask.ex3'].map((key) => (
                <button key={key} type="button" onClick={() => ask(t(key))}
                        className="badge hover:border-accent/40 hover:bg-accent-soft
                                   hover:text-accent">
                  {t(key)}
                </button>
              ))}
            </div>
          </div>
        )}
      </Card>

      {busy && <Card><Spinner label={t('ask.thinking')} /></Card>}

      {error && (
        <Card>
          <ErrorNote error={error} />
          {noModel && (
            <div className="mt-3">
              <Note tone="warn">
                {t('ask.no_model')}{' '}
                {has(grant, 'admin') && (
                  <button className="font-medium text-accent underline-offset-2 hover:underline"
                          onClick={() => goto('models')}>{t('overview.bind_model')}</button>
                )}
              </Note>
            </div>
          )}
        </Card>
      )}

      {result && (
        <Card title={t('ask.answer')} icon={Sparkle}
              actions={<>
                <Badge tone="accent">{result.model}</Badge>
                <Badge>{t('common.elapsed', { ms: result.ms })}</Badge>
              </>}>
          <p className="whitespace-pre-wrap text-[14.5px] leading-relaxed text-text">
            {result.answer}
          </p>

          <div className="mt-6 border-t border-line pt-4">
            <div className="label">{t('common.evidence')}</div>
            {result.evidence?.length ? (
              <>
                <p className="mb-2.5 text-[12px] text-text-3">{t('ask.evidence_hint')}</p>
                <div className="flex flex-wrap gap-1.5">
                  {result.evidence.map((id) => (
                    <NodeChip key={id} id={id} onOpen={(n) => goto('explore', n)} />
                  ))}
                </div>
              </>
            ) : <Empty>{t('ask.nothing')}</Empty>}
          </div>
        </Card>
      )}

      <Note>{t('ask.limits')}</Note>
      {/* No Gauntlet switch here on purpose: `answer` composes `harvest`,
          which is entry search. Part K conditions the *frontier* — look,
          move, scan — and this console never hops. A switch that changed
          nothing would be worse than its absence. */}
      <Note>{t('gauntlet.not_here')}</Note>
    </div>
  )
}
