import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Panel, Field, Select, ErrorNote, Spinner, Empty, Chip, Table } from '../components/ui.jsx'

// Spec J.10. A forest is not one workload: ingest wants a careful summariser
// that obeys the scent contract, answering wants a fast reader. Binding a
// model per (forest, role) is how an operator pays for care where care
// matters — and keeps a sensitive corpus on a local endpoint.
const ROLES = [
  { key: 'ingest', title: 'Ingest', blurb: 'Writes summaries and proposes edges at ingest time. Favour care over speed — this text is what every later hop navigates by.' },
  { key: 'answer', title: 'Answer', blurb: 'Reads harvested material and writes the final answer. Favour speed and instruction-following.' },
]

const PRESETS = [
  { name: 'openrouter', endpoint: 'https://openrouter.ai/api/v1' },
  { name: 'litellm', endpoint: 'http://localhost:4000/v1' },
  { name: 'local-llamacpp', endpoint: 'http://localhost:8090/v1' },
]

export default function Models({ forest }) {
  const [providers, setProviders] = useState([])
  const [bindings, setBindings] = useState([])
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(true)
  const [probe, setProbe] = useState(null)
  const [draft, setDraft] = useState({ name: '', endpoint: '', api_key: '' })

  async function refresh() {
    setBusy(true); setError(null)
    try {
      const [p, b] = await Promise.all([api.providers(), api.bindings(forest)])
      setProviders(p.providers); setBindings(b.bindings)
    } catch (e) { setError(e) } finally { setBusy(false) }
  }
  useEffect(() => { refresh() }, [forest])

  async function saveProvider(e) {
    e.preventDefault()
    try { await api.putProvider(draft); setDraft({ name: '', endpoint: '', api_key: '' }); refresh() }
    catch (err) { setError(err) }
  }
  async function testProvider(name, endpoint, api_key) {
    setProbe({ name, state: 'testing' })
    try {
      const r = await api.testProvider({ name, endpoint, api_key })
      setProbe({ name, state: r.ok ? 'ok' : 'fail', ...r })
    } catch (err) { setProbe({ name, state: 'fail', error: err.message }) }
  }
  async function removeProvider(name) {
    try { await api.putProvider({ name, remove: true }); refresh() } catch (e) { setError(e) }
  }

  const bindingFor = (role) => bindings.find((b) => b.role === role)

  return (
    <div className="space-y-4">
      {error && <Panel><ErrorNote error={error} /></Panel>}

      <Panel
        title="Inference providers"
        subtitle="Any OpenAI-compatible /v1 — OpenRouter, LiteLLM, vLLM, a local llama.cpp. Keys are stored server-side and never sent back to this page."
      >
        <form onSubmit={saveProvider} className="grid gap-3 sm:grid-cols-[1fr_1.4fr_1fr_auto] sm:items-end">
          <Field label="Name" value={draft.name} required placeholder="openrouter"
                 onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <Field label="Endpoint" value={draft.endpoint} required placeholder="https://openrouter.ai/api/v1"
                 onChange={(e) => setDraft({ ...draft, endpoint: e.target.value })} />
          <Field label="API key" type="password" value={draft.api_key} placeholder="sk-or-…"
                 hint="Blank keeps the stored key."
                 onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} />
          <button className="btn btn-primary h-[38px]">Save</button>
        </form>

        <div className="mt-3 flex flex-wrap gap-2">
          {PRESETS.map((p) => (
            <button key={p.name} type="button" className="chip hover:border-moss-600 hover:text-moss-200"
                    onClick={() => setDraft({ ...draft, name: draft.name || p.name, endpoint: p.endpoint })}>
              {p.name}
            </button>
          ))}
        </div>

        <div className="mt-5">
          {busy ? <Spinner label="loading providers" />
            : providers.length === 0 ? <Empty>No provider configured yet.</Empty> : (
            <Table head={['provider', 'endpoint', 'key', '']}>
              {providers.map((p) => (
                <tr key={p.name}>
                  <td className="px-2 py-2 text-moss-50">{p.name}</td>
                  <td className="px-2 py-2 font-mono text-[12px] text-bark-400">{p.endpoint}</td>
                  <td className="px-2 py-2">
                    {p.has_key ? <Chip tone="moss">stored</Chip> : <Chip>none</Chip>}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex justify-end gap-2">
                      <button className="btn !py-1" onClick={() => testProvider(p.name)}>Test</button>
                      <button className="btn !py-1" onClick={() => removeProvider(p.name)}>Remove</button>
                    </div>
                  </td>
                </tr>
              ))}
            </Table>
          )}
          {probe && (
            <div className="mt-3 text-[13px]">
              {probe.state === 'testing' ? <Spinner label={`testing ${probe.name}`} />
                : probe.state === 'ok'
                  ? <p className="text-moss-300">{probe.name}: reachable — {probe.count} model(s) advertised.</p>
                  : <p className="text-ember-400">{probe.name}: {probe.error || 'unreachable'}</p>}
              {probe.state === 'ok' && !!probe.models?.length && (
                <p className="mt-1 font-mono text-[11.5px] text-bark-500">
                  {probe.models.slice(0, 8).join(' · ')}{probe.models.length > 8 ? ' …' : ''}
                </p>
              )}
            </div>
          )}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        {ROLES.map((role) => (
          <RoleBinding key={role.key} role={role} forest={forest} providers={providers}
                       binding={bindingFor(role.key)} onSaved={refresh} onError={setError} />
        ))}
      </div>
    </div>
  )
}

function RoleBinding({ role, forest, providers, binding, onSaved, onError }) {
  const [form, setForm] = useState({ provider: '', model: '', max_tokens: 600, reasoning: 'off' })
  useEffect(() => {
    setForm({
      provider: binding?.provider || providers[0]?.name || '',
      model: binding?.model || '',
      max_tokens: binding?.max_tokens || (role.key === 'ingest' ? 300 : 600),
      reasoning: binding?.reasoning || 'off',
    })
  }, [binding, providers.length, role.key])

  async function save(e) {
    e.preventDefault()
    try { await api.bindModel({ forest, role: role.key, ...form }); onSaved() }
    catch (err) { onError(err) }
  }
  async function unbind() {
    try { await api.bindModel({ forest, role: role.key, remove: true }); onSaved() }
    catch (err) { onError(err) }
  }

  return (
    <Panel
      title={role.title}
      subtitle={role.blurb}
      actions={binding ? <Chip tone="moss">bound</Chip> : <Chip>unbound</Chip>}
    >
      <form onSubmit={save} className="space-y-3">
        <Select label="Provider" value={form.provider} required
                onChange={(e) => setForm({ ...form, provider: e.target.value })}>
          <option value="" disabled>choose a provider</option>
          {providers.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
        </Select>
        <Field label="Model" value={form.model} required
               placeholder={role.key === 'ingest' ? 'google/gemma-4-26b-a4b-it' : 'qwen/qwen3.5-flash-02-23'}
               onChange={(e) => setForm({ ...form, model: e.target.value })} />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Max tokens" type="number" min="64" value={form.max_tokens}
                 onChange={(e) => setForm({ ...form, max_tokens: Number(e.target.value) })} />
          <Select label="Reasoning" value={form.reasoning}
                  onChange={(e) => setForm({ ...form, reasoning: e.target.value })}>
            <option value="off">off — recommended</option>
            <option value="on">on — hybrid thinkers</option>
          </Select>
        </div>
        <div className="flex gap-2">
          <button className="btn btn-primary" disabled={!form.provider || !form.model}>
            {binding ? 'Update' : 'Bind model'}
          </button>
          {binding && <button type="button" className="btn" onClick={unbind}>Unbind</button>}
        </div>
      </form>
    </Panel>
  )
}
