// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Empty, ErrorNote, Note, Skeleton, Table, Td,
} from '../design/ui.jsx'
import { Audit as Log, Refresh, Search } from '../design/icons.jsx'
import { NeedsCapability, has, useAsync } from './shared.jsx'

export default function Audit({ grant }) {
  const { t } = useI18n()
  const [filter, setFilter] = useState('')
  const admin = has(grant, 'admin')
  const log = useAsync(() => api.audit(200).then((r) => r.entries), [], { skip: !admin })

  if (!admin) {
    return <NeedsCapability message={t('audit.needs_admin')} hint={t('cap.admin')} />
  }

  const rows = (log.data || []).filter(
    (e) => !filter || e.principal.toLowerCase().includes(filter.toLowerCase()))

  return (
    <div className="space-y-4">
      <Card title={t('audit.title')} subtitle={t('audit.sub')} icon={Log}
            actions={<button className="btn btn-sm" onClick={log.reload}>
              <Refresh size={14} /> {t('common.refresh')}
            </button>}>
        <label className="relative mb-4 block max-w-xs">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2
                                       -translate-y-1/2 text-text-3" />
          <input className="field pl-9 !py-1.5 text-[13px]" value={filter}
                 placeholder={t('audit.filter')}
                 onChange={(e) => setFilter(e.target.value)} />
        </label>

        {log.busy ? <Skeleton rows={5} />
          : log.error ? <ErrorNote error={log.error} onRetry={log.reload} />
          : rows.length === 0 ? <Empty icon={Log}>{t('audit.none')}</Empty> : (
          <Table head={[t('audit.when'), t('audit.who'), t('audit.what'), t('audit.where'),
                        t('audit.result'), t('audit.size'), t('audit.commit')]}>
            {rows.map((e, i) => (
              <tr key={i}>
                <Td className="whitespace-nowrap font-mono text-[11.5px] text-text-3">
                  {String(e.at || '').replace('T', ' ').slice(0, 19)}
                </Td>
                <Td className="font-medium text-text">{e.principal}</Td>
                <Td><Badge tone="accent">{e.primitive}</Badge></Td>
                <Td className="font-mono text-[11.5px] text-text-3">{e.forest}</Td>
                <Td>
                  {e.result === 'ok' ? <Badge>ok</Badge>
                                     : <Badge tone="danger">{e.result}</Badge>}
                </Td>
                <Td className="tabular-nums text-text-3">{e.size}</Td>
                <Td className="font-mono text-[11.5px] text-text-3">
                  {e.commit_sha ? e.commit_sha.slice(0, 7) : '—'}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <Note>{t('audit.no_bodies')}</Note>
    </div>
  )
}
