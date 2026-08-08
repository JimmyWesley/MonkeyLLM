import { useState } from 'react'
import { api } from '../api.js'
import { Panel, TextArea, ErrorNote, Spinner, Empty, Chip } from '../components/ui.jsx'

// The flagship surface: one question in, a grounded answer out. Retrieval is
// scoped and deterministic; only then does the forest's bound `answer` model
// read what the principal was already allowed to see (spec J.10).
export default function Ask({ forest, onOpenNode }) {
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  async function ask(e) {
    e?.preventDefault()
    if (!question.trim()) return
    setBusy(true); setError(null); setResult(null)
    const t0 = performance.now()
    try {
      const r = await api.call(forest, 'answer', { question, k: 3 })
      setResult({ ...r, ms: Math.round(performance.now() - t0) })
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <Panel
        title="Ask the forest"
        subtitle="Scoped retrieval, then the model bound to this forest reads it. The answer cites the nodes it used."
      >
        <form onSubmit={ask} className="space-y-3">
          <TextArea
            rows={3}
            value={question}
            placeholder="Which region had the highest total sales in Q1, and where is that recorded?"
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) ask(e) }}
          />
          <div className="flex items-center gap-3">
            <button className="btn btn-primary" disabled={busy || !question.trim()}>
              {busy ? 'Thinking…' : 'Ask'}
            </button>
            <span className="text-[12px] text-bark-500">⌘↵ to send</span>
          </div>
        </form>
      </Panel>

      {busy && <Panel><Spinner label="retrieving and reading" /></Panel>}
      {error && (
        <Panel>
          <ErrorNote error={error} />
          {error.code === 'E_SCHEMA' && (
            <p className="mt-3 text-[13px] text-bark-500">
              If no model is bound yet, set one under <b className="text-moss-200">Models</b>.
            </p>
          )}
        </Panel>
      )}

      {result && (
        <Panel
          title="Answer"
          actions={<>
            <Chip tone="moss">{result.model}</Chip>
            <Chip>{result.ms} ms</Chip>
          </>}
        >
          <p className="whitespace-pre-wrap text-[14px] leading-relaxed text-moss-50">
            {result.answer}
          </p>
          <div className="mt-5">
            <div className="label">Evidence</div>
            {result.evidence?.length ? (
              <div className="flex flex-wrap gap-2">
                {result.evidence.map((id) => (
                  <button key={id} onClick={() => onOpenNode(id)}
                          className="chip hover:border-moss-600 hover:text-moss-200">
                    <span className="font-mono">{id}</span>
                  </button>
                ))}
              </div>
            ) : <Empty>The retrieval returned nothing in scope.</Empty>}
          </div>
        </Panel>
      )}
    </div>
  )
}
