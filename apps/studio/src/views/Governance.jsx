import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Panel, Field, ErrorNote, Spinner, Empty, Chip, Table } from '../components/ui.jsx'

const ALL_CAPS = ['read', 'query', 'write', 'tend', 'ingest', 'admin']

export default function Governance({ forest, me, grant }) {
  const [people, setPeople] = useState(null)
  const [error, setError] = useState(null)
  const [issued, setIssued] = useState(null)
  const [form, setForm] = useState({ principal: '', allow: '', deny: '', caps: ['read'], issue_key: true })

  async function refresh() {
    if (!me.admin) return
    try { setPeople((await api.principals()).principals) } catch (e) { setError(e) }
  }
  useEffect(() => { refresh() }, [me.admin])

  async function save(e) {
    e.preventDefault()
    setError(null); setIssued(null)
    const split = (s) => s.split(',').map((x) => x.trim()).filter(Boolean)
    try {
      const r = await api.grant({
        principal: form.principal, forest,
        caps: form.caps, allow: split(form.allow), deny: split(form.deny),
        issue_key: form.issue_key,
      })
      if (r.api_key) setIssued({ principal: r.principal, key: r.api_key })
      refresh()
    } catch (err) { setError(err) }
  }

  const toggleCap = (c) => setForm((f) => ({
    ...f, caps: f.caps.includes(c) ? f.caps.filter((x) => x !== c) : [...f.caps, c],
  }))

  return (
    <div className="space-y-4">
      <Panel title="This key" subtitle="A principal's world is exactly what it was granted.">
        <div className="flex flex-wrap items-center gap-2">
          <Chip tone="moss">{me.principal}</Chip>
          {(grant?.caps || []).map((c) => <Chip key={c}>{c}</Chip>)}
        </div>
        <dl className="mt-4 grid gap-2 text-[13px] sm:grid-cols-2">
          <div><dt className="label">allow</dt>
            <dd className="font-mono text-[12px] text-bark-400">
              {JSON.stringify(grant?.allow ?? [''])}</dd></div>
          <div><dt className="label">deny</dt>
            <dd className="font-mono text-[12px] text-bark-400">
              {JSON.stringify(grant?.deny ?? [])}</dd></div>
        </dl>
      </Panel>

      {!me.admin ? (
        <Panel><Empty>Administering principals needs the <b>admin</b> capability on this forest.</Empty></Panel>
      ) : (
        <>
          {error && <Panel><ErrorNote error={error} /></Panel>}
          <Panel title="Grant access" subtitle={`On ${forest}. Leave "allow" blank to grant the whole forest.`}>
            <form onSubmit={save} className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Principal" required value={form.principal} placeholder="alice"
                       onChange={(e) => setForm({ ...form, principal: e.target.value })} />
                <Field label="Allow prefixes" value={form.allow} placeholder="projects/, sales/reports/"
                       onChange={(e) => setForm({ ...form, allow: e.target.value })} />
                <Field label="Deny prefixes" value={form.deny} placeholder="projects/secret/"
                       onChange={(e) => setForm({ ...form, deny: e.target.value })} />
              </div>
              <div>
                <span className="label">Capabilities</span>
                <div className="flex flex-wrap gap-2">
                  {ALL_CAPS.map((c) => (
                    <button key={c} type="button" onClick={() => toggleCap(c)}
                            className={form.caps.includes(c) ? 'chip chip-moss' : 'chip hover:border-moss-600'}>
                      {c}
                    </button>
                  ))}
                </div>
              </div>
              <label className="flex items-center gap-2 text-[13px] text-bark-400">
                <input type="checkbox" checked={form.issue_key}
                       onChange={(e) => setForm({ ...form, issue_key: e.target.checked })} />
                Issue an API key for this principal
              </label>
              <button className="btn btn-primary" disabled={!form.principal}>Save grant</button>
            </form>

            {issued && (
              <div className="mt-4 rounded-lg border border-moss-600/50 bg-moss-900/40 p-3">
                <p className="text-[13px] text-moss-200">
                  Key for <b>{issued.principal}</b> — copy it now, only its digest is kept.
                </p>
                <pre className="mt-2 overflow-x-auto rounded bg-canvas p-2 font-mono
                                text-[12px] text-moss-50">{issued.key}</pre>
              </div>
            )}
          </Panel>

          <Panel title="Principals">
            {people === null ? <Spinner label="loading" />
              : people.length === 0 ? <Empty>No principal yet.</Empty> : (
              <Table head={['principal', 'keys', 'grants']}>
                {people.map((p) => (
                  <tr key={p.id}>
                    <td className="px-2 py-2 text-moss-50">{p.id}</td>
                    <td className="px-2 py-2 text-bark-400">{p.keys}</td>
                    <td className="px-2 py-2">
                      <div className="space-y-1">
                        {p.grants_detail.map((g) => (
                          <div key={g.forest} className="flex flex-wrap items-center gap-1.5">
                            <span className="font-mono text-[12px] text-bark-300">{g.forest}</span>
                            {g.caps.map((c) => <Chip key={c}>{c}</Chip>)}
                            <span className="font-mono text-[11.5px] text-bark-500">
                              allow {JSON.stringify(g.allow)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </Panel>
        </>
      )}
    </div>
  )
}
