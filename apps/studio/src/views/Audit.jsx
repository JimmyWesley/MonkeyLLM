import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Panel, ErrorNote, Spinner, Empty, Chip, Table } from '../components/ui.jsx'

export default function Audit({ me }) {
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!me.admin) return
    api.audit(200).then((r) => setEntries(r.entries)).catch(setError)
  }, [me.admin])

  if (!me.admin) {
    return <Panel><Empty>Reading the audit log needs the <b>admin</b> capability.</Empty></Panel>
  }

  return (
    <Panel
      title="Audit"
      subtitle="Reads come from the host log; writes are git commits inside the forest, stamped with the principal that asked."
    >
      {error && <ErrorNote error={error} />}
      {entries === null ? <Spinner label="loading" />
        : entries.length === 0 ? <Empty>Nothing recorded yet.</Empty> : (
        <Table head={['when', 'principal', 'forest', 'call', 'arguments', 'result', 'commit']}>
          {entries.map((e, i) => (
            <tr key={i}>
              <td className="px-2 py-1.5 whitespace-nowrap text-[12px] text-bark-500">{e.ts}</td>
              <td className="px-2 py-1.5 text-moss-50">{e.principal}</td>
              <td className="px-2 py-1.5 text-bark-400">{e.forest}</td>
              <td className="px-2 py-1.5"><span className="font-mono text-[12px] text-moss-400">{e.primitive}</span></td>
              <td className="px-2 py-1.5 max-w-[22rem] truncate font-mono text-[11.5px] text-bark-500"
                  title={e.args}>{e.args}</td>
              <td className="px-2 py-1.5">
                {e.result === 'ok' ? <Chip tone="moss">ok</Chip> : <Chip>error</Chip>}
              </td>
              <td className="px-2 py-1.5 font-mono text-[11.5px] text-bark-500">
                {(e.commit_sha || '').slice(0, 8)}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Panel>
  )
}
