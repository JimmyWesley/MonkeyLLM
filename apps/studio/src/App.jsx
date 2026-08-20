// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useCallback, useEffect, useState } from 'react'
import { api, getKey, setKey, clearKey, ApiError } from './api.js'
import { useI18n } from './i18n.jsx'
import { useTheme } from './theme.jsx'
import {
  hrefFor, lastPlace, linkTo, navigate, parse, rememberPlace, useUrl,
} from './router.js'
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
import Webhooks from './views/Webhooks.jsx'
import Skills from './views/Skills.jsx'
import Read from './views/Read.jsx'
import SharedRead from './views/SharedRead.jsx'

const VIEWS = {
  overview: Overview, ask: Ask, explore: Explore, read: Read,
  playground: Playground,
  data: Data, ingest: Ingest, models: Models, people: People, audit: Audit,
  health: Health, webhooks: Webhooks,
  integrations: Integrations,
  skills: Skills,
}

export default function App() {
  const { t } = useI18n()
  const [session, setSession] = useState(null)   // {me, forests}
  const [booting, setBooting] = useState(true)
  // Where the console is (J.5.8). Read from the address on every render, so
  // there is no second copy of it to disagree with the address bar.
  const here = useUrl()
  // A share link (J.17) renders BEFORE any identity gate: the token in the
  // address is the whole authority, and asking the anonymous reader to sign
  // in would refuse exactly the person the link exists for.
  const shared = here.split('?')[0].match(/^\/s\/([A-Za-z0-9_-]+)$/)
  const { forest, view, params } = parse(here)
  const node = params.get('node') || null

  const boot = useCallback(async () => {
    const [me, list] = await Promise.all([api.me(), api.forests()])
    setSession({ me, forests: list.forests })
    return list
  }, [])

  useEffect(() => {
    if (!getKey()) { setBooting(false); return }
    boot().catch(() => clearKey()).finally(() => setBooting(false))
  }, [boot])

  const ids = session?.forests.map((f) => f.id) || []
  const known = ids.includes(forest)
  const grant = session?.me.grants?.find((g) => g.forest === forest) || null

  // Capabilities are per forest, so switching forests can take the current
  // console away — and an address can name one this grant never had. Either
  // way the console MOVES rather than quietly rendering something else: the
  // address is what the operator can see, so it must not describe a page
  // that is not on screen (J.5.8).
  const visible = consolesFor(grant)
  const landing = (visible.find((c) => c.key === 'ask') || visible[0])?.key || 'overview'
  const servable = known && visible.some((c) => c.key === view)

  useEffect(() => {
    if (shared) return       // a share URL is a place, not a missing forest
    if (!session || !ids.length) return
    if (!forest) {
      // A bare `/`. The remembered place is a starting point and nothing
      // more: it never overrides an address, and a forest that has left the
      // principal's grants is not a place to go back to.
      const place = lastPlace()
      const start = ids.includes(place.forest) ? place.forest : ids[0]
      navigate(hrefFor(start, place.view || 'ask'), { replace: true })
      return
    }
    if (!known) return                       // said, not swapped (J.5.8)
    if (!servable) {
      navigate(hrefFor(forest, landing, Object.fromEntries(params)), { replace: true })
      return
    }
    rememberPlace(forest, view)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, here])

  if (shared) return <SharedRead token={shared[1]} />

  if (booting) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner label={t('common.loading')} size={18} />
      </div>
    )
  }
  if (!session) return <Doorway onIn={boot} />

  const setNode = (id) => navigate(
    hrefFor(forest, view, { ...Object.fromEntries(params), node: id || '' }))
  const goto = (next, id) => navigate(
    hrefFor(forest, next, { node: id || node || '' }))

  const View = VIEWS[view] || Overview

  return (
    <Shell session={session} forest={forest} view={view || landing} node={node} grant={grant}
           onForestCreated={(id) => boot().then(() => navigate(hrefFor(id, landing)))}>
      {!ids.length ? (
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
      ) : forest && !known ? (
        <NoSuchForest id={forest} forests={session.forests} landing={landing} />
      ) : !servable ? (
        // Resolving in the effect above: one frame, not a screen.
        <Spinner label={t('common.loading')} size={18} />
      ) : (
        <View key={`${forest}:${view}`} forest={forest} grant={grant} me={session.me}
              node={node} setNode={setNode} goto={goto} />
      )}
    </Shell>
  )
}

/** An address naming a forest this principal has no grant on (J.5.8).
 *
 *  Said, never swapped. Sending them to a forest they *can* see would answer
 *  a link to a specific place with a different place and no explanation —
 *  which is how somebody comes to believe they are reading a forest they are
 *  not. The forests they do have are the way on, as links.
 */
function NoSuchForest({ id, forests, landing }) {
  const { t } = useI18n()
  return (
    <Card>
      <div className="py-6 text-center">
        <span className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl
                         bg-surface-2 text-text-3"><Forest size={20} /></span>
        <p className="text-[13.5px] font-medium text-text">{t('forest.unknown')}</p>
        <p className="mx-auto mt-1 max-w-[46ch] text-[12.5px] text-text-3">
          {t('forest.unknown_hint', { id })}
        </p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {forests.map((f) => (
            <a key={f.id} className="btn btn-sm" {...linkTo(hrefFor(f.id, landing))}>
              <Forest size={13} /> {f.id}
            </a>
          ))}
        </div>
      </div>
    </Card>
  )
}

/** Which pre-identity screen to show is a deployment fact, not a guess: a
 *  Station with nobody in it needs setup, and one with a closed setup needs
 *  the Gate (J.5.6). Asking once here also spares the Gate its own request. */
function Doorway({ onIn }) {
  const { t } = useI18n()
  const [health, setHealth] = useState(null)

  useEffect(() => {
    // A Station that cannot answer is not a Station that needs setting up —
    // falling back to the Gate keeps a network blip from offering to create
    // an owner on a deployment that already has one.
    api.health().then(setHealth).catch(() => setHealth({}))
  }, [])

  if (!health) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner label={t('common.loading')} size={18} />
      </div>
    )
  }
  return health.setup_required
    ? <Setup onIn={onIn} onTaken={() => setHealth({ ...health, setup_required: false })} />
    : <Gate onIn={onIn} health={health} />
}

/** A forest id is a directory name (J.7), so what the operator types becomes
 *  one here rather than being rejected by the API for a space. */
function slugify(text) {
  const slug = text.normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '').slice(0, 63)
  return slug || 'main'
}

const MIN_PASSWORD = 12

/** First-run setup (J.2.4): the screen that exists once. It creates the
 *  owner and, if asked, the first forest — then hands over to the console
 *  exactly as a login would. */
function Setup({ onIn, onTaken }) {
  const { t } = useI18n()
  const [form, setForm] = useState({ username: '', password: '', email: '' })
  const [start, setStart] = useState('demo')
  const [forestName, setForestName] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const short = form.password.length > 0 && form.password.length < MIN_PASSWORD
  const ready = form.username.trim() && form.password.length >= MIN_PASSWORD

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const session = await api.setup({
        username: form.username.trim(),
        password: form.password,
        email: form.email.trim() || undefined,
      })
      setKey(session.key)
    } catch (err) {
      setBusy(false)
      // The route is gone, so somebody reached it first. Retrying can only
      // fail again; the Gate is where they belong now (J.5.6).
      if (err instanceof ApiError && err.status === 404) return onTaken()
      return setError(err instanceof ApiError ? err : new ApiError(t('setup.failed')))
    }

    if (start !== 'skip') {
      const title = start === 'demo'
        ? t('setup.demo_title')
        : (forestName.trim() || t('setup.empty_title'))
      try {
        await api.createForest({
          id: slugify(start === 'demo' ? 'demo' : title), title,
          seed: start === 'demo' ? 'demo' : undefined,
        })
      } catch {
        // The owner exists and is signed in; refusing to continue over a
        // forest would strand them outside their own Station. The console's
        // empty state carries the create action, and the owner is an
        // administrator there (J.5.6).
      }
    }
    await onIn()
  }

  return (
    <Doorframe>
      <Card title={t('setup.title')} subtitle={t('setup.lede')} bodyClass="p-5 pt-0">
        <form onSubmit={submit} className="space-y-4 pt-5">
          <Field label={t('setup.username')} autoFocus value={form.username}
                 autoComplete="username" hint={t('setup.username_hint')}
                 onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <Field label={t('setup.password')} type="password" value={form.password}
                 autoComplete="new-password" hint={t('setup.password_hint')}
                 error={short ? t('setup.password_short') : undefined}
                 onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <Field label={t('setup.email')} type="email" value={form.email}
                 autoComplete="email" placeholder={t('setup.optional')}
                 hint={t('setup.email_hint')}
                 onChange={(e) => setForm({ ...form, email: e.target.value })} />

          <fieldset className="space-y-2">
            <legend className="mb-1 text-[12.5px] font-medium text-text">
              {t('setup.first_forest')}
            </legend>
            {[['demo', t('setup.start_demo'), t('setup.start_demo_hint')],
              ['empty', t('setup.start_empty'), t('setup.start_empty_hint')],
              ['skip', t('setup.start_skip'), t('setup.start_skip_hint')]].map(
              ([value, label, hint]) => (
                <label key={value} className="flex cursor-pointer gap-2.5 rounded-lg
                                              border border-line p-2.5 text-[12.5px]">
                  <input type="radio" name="start" value={value} className="mt-0.5"
                         checked={start === value}
                         onChange={() => setStart(value)} />
                  <span>
                    <span className="block font-medium text-text">{label}</span>
                    <span className="block text-text-3">{hint}</span>
                  </span>
                </label>
              ))}
          </fieldset>

          {start === 'empty' && (
            <Field label={t('setup.forest_name')} value={forestName}
                   placeholder={t('setup.empty_title')}
                   hint={t('setup.forest_name_hint',
                           { id: slugify(forestName || t('setup.empty_title')) })}
                   onChange={(e) => setForestName(e.target.value)} />
          )}

          <ErrorNote error={error} />
          <button className="btn btn-primary w-full" disabled={busy || !ready}>
            {busy ? t('setup.creating') : t('setup.create')}
          </button>
          <Note>
            <b className="text-text">{t('setup.once')}</b> {t('setup.once_hint')}
          </Note>
        </form>
      </Card>
    </Doorframe>
  )
}

/** The one screen shown before identity exists, so it carries the language
 *  and theme controls itself — asking someone to sign in before they can
 *  read the form would be a poor first impression. */
function Gate({ onIn, health }) {
  const { t } = useI18n()
  const [door, setDoor] = useState(health?.password_login === false ? 'key' : 'password')
  const [value, setValue] = useState('')
  const [creds, setCreds] = useState({ username: '', password: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  // Whether the password door exists at all is a deployment fact, so the
  // console is told rather than assuming: a Station with no password
  // configured must not show a form that can only ever fail.
  const hasPasswordDoor = health?.password_login ?? false

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
    <Doorframe>
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
    </Doorframe>
  )
}

/** Chrome shared by both pre-identity screens (J.5.6). The language and
 *  theme controls live here rather than in the Shell, because the first
 *  screen a person sees cannot require a session to be legible (J.5.3). */
function Doorframe({ children }) {
  const { t, lang, setLang } = useI18n()
  const { resolved, setMode } = useTheme()
  return (
    <div className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-[400px]">
        <div className="mb-6 text-center">
          <img src="/logo.png" alt="MonkeyLLM" className="mx-auto mb-3 h-16 w-16" />
          <h1 className="text-[21px] font-semibold tracking-tight text-text">
            {t('app.name')} {t('app.studio')}
          </h1>
          <p className="mt-1 text-[13px] text-text-3">{t('app.tagline')}</p>
        </div>

        {children}

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
