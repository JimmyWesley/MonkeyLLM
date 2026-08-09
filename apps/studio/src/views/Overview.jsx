import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import { Card, Note, Skeleton, Stat } from '../design/ui.jsx'
import {
  Ask, Data, Explore, Forest, Ingest, Models, Overview as Grid,
} from '../design/icons.jsx'
import { ALL_CAPS, capsOf, has, rootsOf, useAsync, useForestTree } from './shared.jsx'

/** The landing answer to "what is this and what may I do here".
 *
 * Every number is counted over what this key can actually reach, not over
 * the forest — a scoped principal seeing the true total would learn the size
 * of the part they were denied. */
export default function Overview({ forest, grant, me, goto }) {
  const { t } = useI18n()

  const stats = useForestTree(forest, grant, api.call)

  const bindings = useAsync(
    () => api.bindings(forest).then((b) => b.bindings),
    [forest], { skip: !has(grant, 'admin') })

  const held = capsOf(grant)
  const missing = ALL_CAPS.filter((c) => !held.includes(c) && !held.includes('admin'))
  const whole = rootsOf(grant).length === 1 && rootsOf(grant)[0] === '_index'
  const answerBound = bindings.data?.some((b) => b.role === 'answer')

  // "82" when the walk was complete, "82+" when one branch overflowed the
  // scan budget. A count that might be short says so.
  const count = (n) => (stats.data?.partial ? `${n}+` : n)

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {stats.busy ? (
          Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="card p-4"><Skeleton rows={2} /></div>
          ))
        ) : (
          <>
            <Stat label={t('overview.nodes')} value={count(stats.data?.nodes ?? 0)}
                  icon={Grid} hint={t('overview.sub')} />
            <Stat label={t('overview.branches')}
                  value={count(stats.data?.branches?.length ?? 0)} icon={Forest} />
            <Stat label={t('overview.datasets')} value={stats.data?.datasets ?? 0}
                  icon={Data} tone={stats.data?.datasets ? 'accent' : 'muted'} />
            <Stat label={t('overview.scope')}
                  value={whole ? t('overview.scope_all')
                               : t('overview.scope_n', { n: rootsOf(grant).length })}
                  icon={Explore} tone="muted"
                  hint={whole ? undefined : rootsOf(grant).join(' · ')} />
          </>
        )}
      </div>

      {has(grant, 'admin') && !bindings.busy && !answerBound && (
        <Note tone="warn">
          {t('overview.no_model')}{' '}
          <button className="font-medium text-accent underline-offset-2 hover:underline"
                  onClick={() => goto('models')}>{t('overview.bind_model')}</button>
        </Note>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t('overview.start')} icon={Ask} className="lg:col-span-2">
          <div className="grid gap-2.5 sm:grid-cols-3">
            <Action icon={Ask} label={t('overview.start_ask')}
                    onClick={() => goto('ask')} disabled={!has(grant, 'read')} />
            <Action icon={Explore} label={t('overview.start_explore')}
                    onClick={() => goto('explore')} disabled={!has(grant, 'read')} />
            <Action icon={Ingest} label={t('overview.start_ingest')}
                    onClick={() => goto('ingest')} disabled={!has(grant, 'ingest')} />
          </div>

          <div className="mt-5">
            <div className="label">{t('overview.roots')}</div>
            <div className="flex flex-wrap gap-1.5">
              {rootsOf(grant).map((r) => (
                <button key={r} className="badge hover:border-accent/40 hover:text-accent"
                        onClick={() => goto('explore', r)}>
                  <span className="font-mono">{r}</span>
                </button>
              ))}
            </div>
          </div>
        </Card>

        <Card title={t('overview.can')} icon={Models}>
          <ul className="space-y-1.5 text-[13px]">
            {(held.includes('admin') ? ALL_CAPS : held).map((c) => (
              <li key={c} className="flex items-start gap-2 text-text-2">
                <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                {t(`cap.${c}`)}
              </li>
            ))}
          </ul>
          {missing.length > 0 && (
            <>
              <div className="label mt-5">{t('overview.cannot')}</div>
              <ul className="space-y-1.5 text-[13px]">
                {missing.map((c) => (
                  <li key={c} className="flex items-start gap-2 text-text-3">
                    <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-line-strong" />
                    {t(`cap.${c}`)}
                  </li>
                ))}
              </ul>
            </>
          )}
          <p className="mt-4 text-[11.5px] leading-relaxed text-text-3">
            {me.principal} · {forest}
          </p>
        </Card>
      </div>
    </div>
  )
}

function Action({ icon: Icon, label, onClick, disabled }) {
  return (
    <button onClick={onClick} disabled={disabled}
            className="flex flex-col items-start gap-2 rounded-lg border border-line
                       bg-surface-2 p-3 text-left transition
                       hover:border-accent/40 hover:bg-accent-soft
                       disabled:pointer-events-none disabled:opacity-40">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-surface text-accent">
        <Icon size={16} />
      </span>
      <span className="text-[12.5px] font-medium leading-snug text-text">{label}</span>
    </button>
  )
}
