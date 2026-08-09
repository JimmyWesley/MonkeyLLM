// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useCallback, useEffect, useState } from 'react'
import { api, getKey, setKey, clearKey, ApiError } from './api.js'
import { useI18n } from './i18n.jsx'
import { useTheme } from './theme.jsx'
import { Card, ErrorNote, Field, Note, Spinner, Tabs } from './design/ui.jsx'
import { Forest, Globe, Moon, Sun } from './design/icons.jsx'
import { Shell, consolesFor } from './components/Shell.jsx'
import Overview from './views/Overview.jsx'
import Ask from './views/Ask.jsx'
import Explore from './views/Explore.jsx'
import Playground from './views/Playground.jsx'
import Data from './views/Data.jsx'
import Ingest from './views/Ingest.jsx'
import Models from './views/Models.jsx'
import People from './views/People.jsx'
import Audit from './views/Audit.jsx'
import Health from './views/Health.jsx'
import Integrations from './views/Integrations.jsx'

const VIEWS = {
  overview: Overview, ask: Ask, explore: Explore, playground: Playground,
  data: Data, ingest: Ingest, models: Models, people: People, audit: Audit,
  health: Health,
  integrations: Integrations,
}

export default function App() {
  const { t } = useI18n()
  const [session, setSession] = useState(null)   // {me, forests}
  const [booting, setBooting] = useState(true)
  const [forest, setForest] = useState(null)
  const [view, setView] = useState('ask')
  const [node, setNode] = useState(null)

  const boot = useCallback(async (prefer) => {
    const [me, list] = await Promise.all([api.me(), api.forests()])
    setSession({ me, forests: list.forests })
    setForest((f) => prefer || f || list.forests[0]?.id || null)
    return list
  }, [])

  useEffect(() => {
    if (!getKey()) { setBooting(false); return }
    boot().catch(() => clearKey()).finally(() => setBooting(false))
  }, [boot])

  if (booting) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner label={t('common.loading')} size={18} />
      </div>
    )
  }
  if (!session) return <Gate onIn={boot} />

  const grant = session.me.grants?.find((g) => g.forest === forest) || null

  // Capabilities are per forest, so switching forests can take the current
  // console away. Falling back keeps the app on something real instead of
  // rendering a console this grant cannot use.
  const visible = consolesFor(grant)
  const current = visible.some((c) => c.key === view) ? view
    : (visible.find((c) => c.key === 'ask') || visible[0])?.key || 'overview'
  const View = VIEWS[current] || Overview
  const goto = (next, id) => { if (id) setNode(id); setView(next) }

  return (
    <Shell session={session} forest={forest} setForest={(f) => { setForest(f); setNode(null) }}
           view={current} setView={setView} grant={grant}
           onForestCreated={(id) => boot(id)}>
      {!forest ? (
        <Card>
          <div className="py-6 text-center">
            <span className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl
                             bg-surface-2 text-text-3"><Forest size={20} /></span>
            <p className="text-[13.5px] font-medium text-text">{t('forest.none')}</p>
            {session.me.admin && (
              <p className="mt-1 text-[12.5px] text-text-3">{t('forest.none_admin')}</p>
            )}
          </div>
        </Card>
      ) : (
        <View key={`${forest}:${current}`} forest={forest} grant={grant} me={session.me}
              node={node} setNode={setNode} goto={goto} />
      )}
    </Shell>
  )
}

/** The one screen shown before identity exists, so it carries the language
 *  and theme controls itself — asking someone to sign in before they can
 *  read the form would be a poor first impression. */
function Gate({ onIn }) {
  const { t, lang, setLang } = useI18n()
  const { resolved, setMode } = useTheme()
  const [door, setDoor] = useState('password')
  const [value, setValue] = useState('')
  const [creds, setCreds] = useState({ username: '', password: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  // Whether the password door exists at all is a deployment fact, so the
  // console asks rather than assuming: a Station with no password configured
  // must not show a form that can only ever fail.
  const [hasPasswordDoor, setHasPasswordDoor] = useState(null)
  useEffect(() => {
    api.health()
      .then((h) => { setHasPasswordDoor(h.password_login); if (!h.password_login) setDoor('key') })
      .catch(() => setHasPasswordDoor(false))
  }, [])

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      if (door === 'password') {
        // The session token is an ordinary key from here on, so everything
        // downstream is the single path it already was (J.2.1).
        const session = await api.login(creds.username.trim(), creds.password)
        setKey(session.key)
      } else {
        setKey(value.trim())
      }
      await onIn()
    } catch (err) {
      clearKey()
      setError(err instanceof ApiError ? err : new ApiError(t('gate.rejected')))
    } finally { setBusy(false) }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-[400px]">
        <div className="mb-6 text-center">
          <span className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl
                           bg-accent text-accent-fg"><Forest size={24} /></span>
          <h1 className="text-[21px] font-semibold tracking-tight text-text">
            {t('app.name')} {t('app.studio')}
          </h1>
          <p className="mt-1 text-[13px] text-text-3">{t('app.tagline')}</p>
        </div>

        <Card title={t('gate.title')} bodyClass="p-5 pt-0">
          {hasPasswordDoor && (
            <Tabs value={door} onChange={(d) => { setDoor(d); setError(null) }} options={[
              { value: 'password', label: t('gate.with_password') },
              { value: 'key', label: t('gate.with_key') },
            ]} />
          )}
          <form onSubmit={submit} className="space-y-4 pt-5">
            {door === 'password' ? (
              <>
                <Field label={t('gate.username')} autoFocus value={creds.username}
                       autoComplete="username" placeholder="admin"
                       onChange={(e) => setCreds({ ...creds, username: e.target.value })} />
                <Field label={t('gate.password')} type="password" value={creds.password}
                       autoComplete="current-password" hint={t('gate.password_hint')}
                       onChange={(e) => setCreds({ ...creds, password: e.target.value })} />
              </>
            ) : (
              <Field label={t('gate.key')} type="password" autoFocus value={value}
                     placeholder="mk_…" hint={t('gate.key_hint')}
                     onChange={(e) => setValue(e.target.value)} />
            )}
            <ErrorNote error={error} />
            <button className="btn btn-primary w-full"
                    disabled={busy || (door === 'password'
                      ? !creds.username.trim() || !creds.password
                      : !value.trim())}>
              {busy ? t('gate.connecting') : t('gate.connect')}
            </button>
            <Note>
              <b className="text-text">{t('gate.where')}</b> {t('gate.where_hint')}
            </Note>
          </form>
        </Card>

        <div className="mt-4 flex items-center justify-center gap-2">
          <div className="segment">
            {[['light', Sun], ['dark', Moon]].map(([m, Icon]) => (
              <button key={m} type="button" aria-pressed={resolved === m}
                      onClick={() => setMode(m)} title={t(`theme.${m}`)}>
                <Icon size={14} />
              </button>
            ))}
          </div>
          <label className="relative">
            <Globe size={14} className="pointer-events-none absolute left-2.5 top-1/2
                                        -translate-y-1/2 text-text-3" />
            <select value={lang} onChange={(e) => setLang(e.target.value)}
                    aria-label={t('lang.label')}
                    className="field !w-auto appearance-none !py-1.5 pl-8 pr-7 text-[12.5px]">
              <option value="en">English</option>
              <option value="pt">Português</option>
              <option value="es">Español</option>
            </select>
          </label>
        </div>
      </div>
    </div>
  )
}
