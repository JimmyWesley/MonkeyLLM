import { useEffect, useState } from 'react'
import { api, getKey, setKey, clearKey, ApiError } from './api.js'
import { Panel, Field, ErrorNote, Spinner, Empty, Chip } from './components/ui.jsx'
import Ask from './views/Ask.jsx'
import Browse from './views/Browse.jsx'
import Search from './views/Search.jsx'
import Datasets from './views/Datasets.jsx'
import Models from './views/Models.jsx'
import Governance from './views/Governance.jsx'
import Audit from './views/Audit.jsx'

const VIEWS = [
  { key: 'ask', label: 'Ask' },
  { key: 'browse', label: 'Browse' },
  { key: 'search', label: 'Search' },
  { key: 'data', label: 'Datasets' },
  { key: 'models', label: 'Models' },
  { key: 'govern', label: 'Governance' },
  { key: 'audit', label: 'Audit' },
]

export default function App() {
  const [session, setSession] = useState(null)   // {me, forests}
  const [booting, setBooting] = useState(true)
  const [forest, setForest] = useState(null)
  const [view, setView] = useState('ask')
  const [node, setNode] = useState(null)

  async function boot() {
    const [me, list] = await Promise.all([api.me(), api.forests()])
    setSession({ me, forests: list.forests })
    setForest((f) => f || list.forests[0]?.id || null)
  }

  useEffect(() => {
    if (!getKey()) { setBooting(false); return }
    boot().catch(() => clearKey()).finally(() => setBooting(false))
  }, [])

  if (booting) {
    return <div className="grid min-h-screen place-items-center"><Spinner label="connecting" /></div>
  }
  if (!session) return <Gate onIn={async () => { await boot() }} />

  const { me, forests } = session
  const grant = me.grants?.find((g) => g.forest === forest)
  const openNode = (id) => { setNode(id); setView('browse') }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-canvas-line/80
                         bg-canvas/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-5 py-3">
          <div className="flex items-baseline gap-2">
            <span className="text-[15px] font-semibold tracking-tight text-moss-50">MonkeyLLM</span>
            <span className="text-[15px] text-bark-500">Studio</span>
          </div>

          {forests.length > 0 && (
            <select value={forest || ''} onChange={(e) => { setForest(e.target.value); setNode(null) }}
                    className="field !w-auto !py-1.5 text-[13px]">
              {forests.map((f) => <option key={f.id} value={f.id}>{f.id}</option>)}
            </select>
          )}

          <div className="flex-1" />
          <Chip tone="moss">{me.principal}</Chip>
          {me.admin && <Chip>admin</Chip>}
          <button className="btn !py-1.5" onClick={() => { clearKey(); location.reload() }}>
            Sign out
          </button>
        </div>
      </header>

      <div className="mx-auto flex max-w-7xl gap-6 px-5 py-6">
        <nav className="hidden w-40 shrink-0 sm:block">
          <ul className="sticky top-20 space-y-0.5">
            {VIEWS.map((v) => (
              <li key={v.key}>
                <button onClick={() => setView(v.key)}
                        className={`w-full rounded-lg px-3 py-2 text-left text-[13px] transition
                          ${view === v.key
                            ? 'bg-moss-900/70 text-moss-200 shadow-ring'
                            : 'text-bark-400 hover:bg-canvas-soft hover:text-moss-100'}`}>
                  {v.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <main className="min-w-0 flex-1">
          {!forest ? (
            <Panel><Empty>No forest has been granted to this principal yet.</Empty></Panel>
          ) : view === 'ask' ? <Ask forest={forest} onOpenNode={openNode} />
            : view === 'browse' ? <Browse forest={forest} grant={grant} node={node} setNode={setNode} />
            : view === 'search' ? <Search forest={forest} onOpenNode={openNode} />
            : view === 'data' ? <Datasets forest={forest} grant={grant} />
            : view === 'models' ? <Models forest={forest} />
            : view === 'govern' ? <Governance forest={forest} me={me} grant={grant} />
            : <Audit me={me} />}
        </main>
      </div>
    </div>
  )
}

function Gate({ onIn }) {
  const [value, setValue] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    setKey(value.trim())
    try { await onIn() }
    catch (err) {
      clearKey()
      setError(err instanceof ApiError ? err : new ApiError('That key was not accepted.'))
    } finally { setBusy(false) }
  }

  return (
    <div className="grid min-h-screen place-items-center px-5">
      <div className="w-full max-w-md">
        <div className="mb-5 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-moss-50">MonkeyLLM Studio</h1>
          <p className="mt-1 text-[13px] text-bark-500">
            Console for a governed forest.
          </p>
        </div>
        <Panel>
          <form onSubmit={submit} className="space-y-4">
            <Field label="API key" type="password" autoFocus value={value}
                   placeholder="mk_…" onChange={(e) => setValue(e.target.value)}
                   hint="The Station stores only its digest." />
            <ErrorNote error={error} />
            <button className="btn btn-primary w-full justify-center" disabled={busy || !value.trim()}>
              {busy ? 'Connecting…' : 'Connect'}
            </button>
          </form>
        </Panel>
      </div>
    </div>
  )
}
