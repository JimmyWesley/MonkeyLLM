// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* The frame every console sits in (spec J.5.1).
 *
 * Three groups answering three questions — use it, build it, govern it —
 * because the flat list of seven names it replaces required already knowing
 * what each one did. Every entry carries an icon: the console is operated by
 * people who did not choose these words.
 */
import { useEffect, useRef, useState } from 'react'
import { api, signOut } from '../api.js'
import { hrefFor, linkTo } from '../router.js'
import { useI18n, LANGUAGES } from '../i18n.jsx'
import { useTheme } from '../theme.jsx'
import { useDevMode } from '../devmode.jsx'
import { Badge, ErrorNote, Field, Modal, Toggle } from '../design/ui.jsx'
import {
  CONSOLE_ICON, ChevronDown, Code2, Forest, Globe, LogOut, Moon, More, PanelLeft,
  Plus, Star, Sun, X,
} from '../design/icons.jsx'

/** `cap` is what the console's own endpoints require. Absent means every
 *  principal has something to see there: Overview describes the key itself,
 *  including the scope and capabilities this grant carries. */
export const CONSOLES = [
  { key: 'overview', group: 'use' },
  { key: 'ask', group: 'use', cap: 'read' },
  { key: 'explore', group: 'use', cap: 'read' },
  { key: 'playground', group: 'use', cap: 'read' },
  { key: 'data', group: 'use', cap: 'query' },
  { key: 'ingest', group: 'build', cap: 'ingest' },
  { key: 'models', group: 'build', cap: 'admin' },
  { key: 'people', group: 'govern', cap: 'admin' },
  { key: 'audit', group: 'govern', cap: 'admin' },
  { key: 'health', group: 'govern', cap: 'admin' },
  { key: 'integrations', group: 'govern', cap: 'admin' },
]

const GROUPS = ['use', 'build', 'govern']

/** The consoles a grant permits (J.5.1). Capabilities are per forest, so
 *  this is recomputed whenever the forest changes.
 *
 *  This is navigation, NOT enforcement: the API already refuses, each view
 *  guards itself, and a hidden entry is still reachable by anyone who can
 *  set application state. Hiding is here because a menu reads as a list of
 *  what you may do, and an entry that only ever refuses teaches nothing.
 */
export function consolesFor(grant) {
  const caps = grant?.caps || []
  const allows = (cap) => !cap || caps.includes(cap) || caps.includes('admin')
  return CONSOLES.filter((c) => allows(c.cap))
}

const RAIL = 'monkeyllm.studio.rail'
const PINS = 'monkeyllm.studio.pins'
const DESKTOP = '(min-width: 1024px)'

/** Slots on the phone's bar, beside the permanent "More". Four fit a 375px
 *  screen with a readable label under each icon; five do not, and an icon
 *  whose label is clipped is an icon nobody learns. */
const TABS = 4

/** Which consoles ride the bottom bar (mobile).
 *
 *  Chosen by the operator with a star, because there is no right default for
 *  everybody: a curator lives in Ingest, an auditor never opens it. Until
 *  somebody chooses, the first four this grant permits — in menu order, so
 *  the bar and the menu tell the same story.
 *
 *  Always filtered through what the grant permits: a pin kept from a forest
 *  where you had `admin` must not hold a slot in one where you do not.
 */
function usePins(visible) {
  const [chosen, setChosen] = useState(() => {
    try { return JSON.parse(localStorage.getItem(PINS)) } catch { return null }
  })
  const keys = visible.map((c) => c.key)
  const wanted = new Set(Array.isArray(chosen) ? chosen : keys.slice(0, TABS))
  const pins = keys.filter((k) => wanted.has(k)).slice(0, TABS)

  const toggle = (key) => {
    const next = pins.includes(key) ? pins.filter((k) => k !== key)
      : pins.length >= TABS ? pins : [...pins, key]
    localStorage.setItem(PINS, JSON.stringify(next))
    setChosen(next)
  }
  return [pins, toggle]
}

/** The collapsed rail is a desktop affordance, and CSS alone could not say
 *  so: `collapsed` also decides what is *rendered*, not just how wide it is.
 *  Without this, collapsing on a laptop left the phone's drawer — 248px of
 *  it — showing the one-column rail, brand row and all. */
function useDesktop() {
  const [is, setIs] = useState(() => window.matchMedia(DESKTOP).matches)
  useEffect(() => {
    const mq = window.matchMedia(DESKTOP)
    const on = (e) => setIs(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return is
}

/** Every destination is a real anchor (J.5.8): open in a new tab, copy link
 *  and middle click work, and the status bar says where an entry goes. The
 *  selection travels between consoles — moving from Explore to Data is the
 *  same forest and, as far as anything is concerned, the same node. */
function consoleLink(forest, key, node) {
  return forest ? linkTo(hrefFor(forest, key, node ? { node } : {})) : {}
}

export function Shell({ session, forest, view, node, onForestCreated,
                        grant, children }) {
  const { t } = useI18n()
  const visible = consolesFor(grant)
  const [open, setOpen] = useState(false)   // mobile sheet
  const [stored, setCollapsed] = useState(
    () => localStorage.getItem(RAIL) === '1')
  const desktop = useDesktop()          // unconditional: it is a hook
  const collapsed = stored && desktop
  const [pins, togglePin] = usePins(visible)

  useEffect(() => { setOpen(false) }, [view, forest])

  const collapse = (next) => {
    localStorage.setItem(RAIL, next ? '1' : '0')
    setCollapsed(next)
  }

  return (
    /* Flex, not grid. As a grid item the sidebar stretched to the height of
       the content column, so a long page pushed its footer far below the
       fold — the taller the right side, the taller the menu. `h-screen` +
       `sticky` pins it to the viewport instead, and the two columns scroll
       independently: the rail inside itself, the page as a page. */
    <div className="min-h-screen lg:flex lg:items-start">
      <div className={`fixed inset-0 z-40 bg-black/50 lg:hidden ${open ? '' : 'hidden'}`}
           onClick={() => setOpen(false)} />
      {/* One element, two shapes. On a phone the menu is a sheet that rises
          from the bar you opened it with — a drawer sliding in from the left
          would point at nothing. From `lg` up it is the sidebar it always
          was, and every mobile-only rule is overridden rather than removed,
          so the two layouts cannot drift apart. */}
      <aside className={`fixed inset-x-0 bottom-0 z-40 flex max-h-[86vh] w-full shrink-0
                         flex-col rounded-t-2xl border-t border-line bg-bg-elev
                         shadow-pop transition-transform
                         lg:sticky lg:inset-x-auto lg:left-0 lg:top-0 lg:h-screen
                         lg:max-h-none lg:translate-y-0 lg:rounded-none
                         lg:border-r lg:border-t-0 lg:shadow-none
                         lg:transition-[width] lg:duration-150
                         ${collapsed ? 'lg:w-[68px]' : 'lg:w-[248px]'}
                         ${open ? 'translate-y-0' : 'translate-y-full'}`}>
        <div className="mx-auto mt-2.5 h-1 w-10 shrink-0 rounded-full bg-line-strong lg:hidden" />

        <ForestSwitcher session={session} forest={forest} view={view}
                        onCreated={onForestCreated} collapsed={collapsed}
                        onCollapse={() => collapse(!collapsed)}
                        onClose={() => setOpen(false)} />

        <nav className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-2">
          <p className="px-2 pt-2.5 text-[11px] text-text-3 lg:hidden">
            {t('nav.pin_hint')}
          </p>
          {GROUPS.filter((g) => visible.some((c) => c.group === g)).map((group) => (
            <div key={group}>
              {collapsed
                ? <div className="mx-2 my-2 h-px bg-line lg:block" />
                : <div className="nav-group">{t(`group.${group}`)}</div>}
              <ul className="space-y-0.5">
                {visible.filter((c) => c.group === group).map((c) => {
                  const Icon = CONSOLE_ICON[c.key]
                  const pinned = pins.includes(c.key)
                  const full = !pinned && pins.length >= TABS
                  return (
                    <li key={c.key} className="flex items-center gap-1">
                      <a
                        className={`nav-item flex-1 ${collapsed ? 'lg:justify-center lg:px-0' : ''}`}
                        title={collapsed ? t(`nav.${c.key}`) : t(`nav.${c.key}.blurb`)}
                        aria-current={view === c.key ? 'page' : undefined}
                        {...consoleLink(forest, c.key, node)}>
                        <Icon size={17} />
                        <span className={collapsed ? 'lg:hidden' : ''}>
                          {t(`nav.${c.key}`)}
                        </span>
                      </a>
                      <button type="button" onClick={() => togglePin(c.key)}
                              disabled={full} aria-pressed={pinned}
                              title={full ? t('nav.pin_full', { n: TABS })
                                          : t(pinned ? 'nav.unpin' : 'nav.pin')}
                              className={`shrink-0 rounded-md p-2 transition lg:hidden
                                          ${pinned ? 'text-accent' : 'text-text-3'}
                                          ${full ? 'opacity-30' : 'hover:bg-surface-2'}`}>
                        <Star size={15} filled={pinned} />
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
        </nav>

        <Footer session={session} collapsed={collapsed}
                onExpand={() => collapse(false)} />
      </aside>

      {/* min-w-0 so a wide table inside a console scrolls itself instead of
          widening this column and, with it, the whole layout. */}
      <div className="min-w-0 flex-1">
        {/* On a phone this bar carries the three things you cannot re-derive
            from what is on screen: which product this is, which forest you
            are in, and which console is open. No hamburger — navigation is
            the bar at the bottom, within thumb reach, and a second door to
            the same menu up here would only be a second thing to explain. */}
        <header className="sticky top-0 z-30 flex items-center gap-2 border-b
                           border-line bg-bg/85 px-3 py-2.5 backdrop-blur lg:hidden">
          <button className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                  onClick={() => setOpen(true)} aria-label={t('nav.menu')}>
            <img src="/logo.png" className="h-10 w-10 shrink-0" alt="MonkeyLLM" />
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-[13.5px] font-semibold tracking-tight text-text">
                {t('app.name')} <span className="font-normal text-text-3">{t('app.studio')}</span>
              </span>
              <span className="block truncate text-[10.5px]">
                <span className="text-text-3">{forest || t('forest.none')}</span>
                <span className="px-1 text-line-strong">·</span>
                <span className="font-semibold uppercase tracking-[0.08em] text-accent">
                  {t(`nav.${view}`)}
                </span>
              </span>
            </span>
          </button>
        </header>
        {/* pb-24: the bottom bar is fixed, so without it the last card on a
            page sits under the tabs and nothing says it is there. */}
        <main className="mx-auto w-full max-w-content px-4 pb-24 pt-6 sm:px-6
                         lg:px-8 lg:pb-6">
          <div className="mb-5 hidden lg:block">
            <h1 className="text-[19px] font-semibold tracking-tight text-text">
              {t(`nav.${view}`)}
            </h1>
            <p className="mt-0.5 text-[13px] text-text-3">{t(`nav.${view}.blurb`)}</p>
          </div>
          {children}
        </main>

        <TabBar pins={pins} view={view} forest={forest} node={node}
                onMore={() => setOpen(true)} moreOpen={open} />
      </div>
    </div>
  )
}

/** The phone's primary navigation (J.5.1).
 *
 *  Icons with labels, not icons alone: these consoles are not universal
 *  metaphors, and a bar of unlabelled glyphs is a quiz. "More" is always the
 *  last slot and never moves — whatever the operator pinned, the way back to
 *  everything else is in the same place.
 */
function TabBar({ pins, view, forest, node, onMore, moreOpen }) {
  const { t } = useI18n()
  const tab = (active) => `flex flex-1 flex-col items-center gap-1 px-1 py-2
                           text-[10px] font-medium transition
                           ${active ? 'text-accent' : 'text-text-3'}`
  return (
    <nav className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line
                    bg-bg-elev/95 pb-[env(safe-area-inset-bottom)] backdrop-blur
                    lg:hidden">
      {pins.map((key) => {
        const Icon = CONSOLE_ICON[key]
        return (
          <a key={key} className={tab(view === key && !moreOpen)}
             aria-current={view === key ? 'page' : undefined}
             {...consoleLink(forest, key, node)}>
            <Icon size={19} />
            <span className="w-full truncate">{t(`nav.${key}`)}</span>
          </a>
        )
      })}
      <button className={tab(moreOpen)} onClick={onMore} aria-expanded={moreOpen}>
        <More size={19} />
        <span className="w-full truncate">{t('nav.more')}</span>
      </button>
    </nav>
  )
}

function ForestSwitcher({ session, forest, view, onCreated, collapsed,
                         onCollapse, onClose }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const box = useRef(null)

  useEffect(() => {
    const away = (e) => { if (!box.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [])

  // The id in the address, whether or not it names a forest this key can
  // reach: an address into a forest without a grant is answered by saying so
  // (J.5.8), and the switcher naming a different one would contradict it.
  const current = session.forests.find((f) => f.id === forest)
  const label = current?.id || forest

  return (
    <div className="border-b border-line p-2.5" ref={box}>
      {/* On the rail the mark IS the switcher — one green tree, not a logo
          stacked above a second tree that does the same thing. The collapse
          control moves to the footer, where there is room for it. */}
      {!collapsed && (
        <div className="mb-2 flex items-center gap-2 px-1.5 pt-1">
          <img src="/logo.png" className="h-9 w-9 shrink-0" alt="MonkeyLLM" />
          <span className="flex-1 truncate text-[13.5px] font-semibold tracking-tight text-text">
            {t('app.name')} <span className="font-normal text-text-3">{t('app.studio')}</span>
          </span>
          <button className="btn btn-sm btn-ghost !px-1.5 hidden lg:inline-flex"
                  onClick={onCollapse} title={t('nav.collapse')}
                  aria-label={t('nav.collapse')}>
            <PanelLeft size={16} />
          </button>
          {/* The overlay closes it too, but a drawer whose only exit is a tap
              on the dimmed area is an exit you have to already know about. */}
          <button className="btn btn-sm btn-ghost !px-1.5 lg:hidden"
                  onClick={onClose} aria-label={t('common.close')}>
            <X size={16} />
          </button>
        </div>
      )}

      <div className="relative">
        {collapsed ? (
          <button className="mx-auto grid h-10 w-10 place-items-center transition hover:opacity-80"
                  title={label || t('forest.switch')}
                  onClick={() => setOpen((v) => !v)}>
            <img src="/logo.png" className="h-10 w-10" alt="MonkeyLLM" />
          </button>
        ) : (
        <button className="flex w-full items-center gap-2 rounded-lg border border-line
                           bg-surface px-2.5 py-2 text-left transition hover:border-line-strong"
                onClick={() => setOpen((v) => !v)}>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-medium text-text">
              {label || t('forest.none')}
            </span>
            <span className="block truncate text-[11px] text-text-3">
              {current
                ? (current.roots?.length === 1 && current.roots[0] === '_index'
                    ? t('overview.scope_all')
                    : t('overview.scope_n', { n: current.roots?.length || 0 }))
                : t('forest.switch')}
            </span>
          </span>
          <ChevronDown size={15} className="text-text-3" />
        </button>
        )}

        {open && (
          /* On the rail the panel would be 68px wide and unusable, so it
             escapes sideways instead of stretching the sidebar. */
          <div className={`absolute top-full z-50 mt-1 min-w-[200px] overflow-hidden
                           rounded-lg border border-line bg-surface shadow-pop
                           ${collapsed ? 'lg:left-0 lg:right-auto' : 'left-0 right-0'}`}>
            <ul className="max-h-64 overflow-y-auto py-1">
              {/* The console travels; the selection does not. A node id
                  addresses one forest (A.2), so carrying it across would open
                  the new forest on a node it does not contain. */}
              {session.forests.map((f) => {
                const to = linkTo(hrefFor(f.id, view || 'overview'))
                return (
                  <li key={f.id}>
                    <a className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-left
                                   text-[13px] transition hover:bg-surface-2
                                   ${f.id === forest ? 'text-accent' : 'text-text-2'}`}
                       {...to} onClick={(e) => { setOpen(false); to.onClick(e) }}>
                      <Forest size={14} />
                      <span className="truncate">{f.id}</span>
                    </a>
                  </li>
                )
              })}
            </ul>
            {session.me.admin && (
              <button className="flex w-full items-center gap-2 border-t border-line
                                 px-2.5 py-2 text-[13px] font-medium text-accent
                                 transition hover:bg-surface-2"
                      onClick={() => { setOpen(false); setCreating(true) }}>
                <Plus size={14} /> {t('forest.new')}
              </button>
            )}
          </div>
        )}
      </div>

      <NewForestModal open={creating} onClose={() => setCreating(false)}
                      onCreated={onCreated} />
    </div>
  )
}

export function NewForestModal({ open, onClose, onCreated }) {
  const { t } = useI18n()
  const [form, setForm] = useState({ id: '', title: '', summary: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (open) { setForm({ id: '', title: '', summary: '' }); setError(null) } }, [open])

  // The id becomes a folder name and cannot be renamed, so it is derived from
  // the title as a suggestion the operator can still override.
  const onTitle = (title) => setForm((f) => ({
    ...f, title,
    id: f.touchedId ? f.id : title.toLowerCase().replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '').slice(0, 63),
  }))

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      await api.createForest(form)
      onCreated(form.id)
      onClose()
    } catch (err) { setError(err) } finally { setBusy(false) }
  }

  return (
    <Modal open={open} onClose={onClose} title={t('forest.new_title')}
           subtitle={t('forest.new_sub')}
           footer={<>
             <button className="btn" onClick={onClose}>{t('common.cancel')}</button>
             <button className="btn btn-primary" form="new-forest"
                     disabled={busy || !form.id || !form.title}>
               {busy ? t('common.working') : t('common.create')}
             </button>
           </>}>
      <form id="new-forest" onSubmit={submit} className="space-y-3.5">
        <Field label={t('forest.title')} value={form.title} required autoFocus
               placeholder="Engineering handbook" hint={t('forest.title_hint')}
               onChange={(e) => onTitle(e.target.value)} />
        <Field label={t('forest.id')} value={form.id} required
               placeholder="engineering-handbook" hint={t('forest.id_hint')}
               onChange={(e) => setForm({ ...form, id: e.target.value, touchedId: true })} />
        <Field label={`${t('forest.summary')} (${t('common.optional')})`}
               value={form.summary}
               onChange={(e) => setForm({ ...form, summary: e.target.value })} />
        <ErrorNote error={error} />
      </form>
    </Modal>
  )
}

function Footer({ session, collapsed, onExpand }) {
  const { t, lang, setLang } = useI18n()
  const { resolved, setMode } = useTheme()
  const { on: devMode, toggle: setDevMode } = useDevMode()

  if (collapsed) {
    // Same controls, one column wide. Nothing is dropped on the rail — a
    // control you have to expand the menu to reach is a control you stop
    // using.
    const next = LANGUAGES[(LANGUAGES.findIndex((l) => l.code === lang) + 1)
                           % LANGUAGES.length]
    return (
      <div className="hidden flex-col items-center gap-1.5 border-t border-line
                      p-2.5 lg:flex">
        <button className="btn btn-sm btn-ghost !px-2" onClick={onExpand}
                title={t('nav.expand')} aria-label={t('nav.expand')}>
          <PanelLeft size={15} className="rotate-180" />
        </button>
        <button className="btn btn-sm btn-ghost !px-2"
                title={t(`theme.${resolved === 'dark' ? 'light' : 'dark'}`)}
                onClick={() => setMode(resolved === 'dark' ? 'light' : 'dark')}>
          {resolved === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>
        <button className={`btn btn-sm btn-ghost !px-2 ${devMode ? 'text-accent' : ''}`}
                aria-pressed={devMode} title={t('devmode.label')}
                onClick={() => setDevMode(!devMode)}>
          <Code2 size={15} />
        </button>
        <button className="btn btn-sm btn-ghost !px-2" title={`${t('lang.label')}: ${next.label}`}
                onClick={() => setLang(next.code)}>
          <Globe size={15} />
        </button>
        <span className="grid h-7 w-7 place-items-center rounded-full bg-accent-soft
                         text-[11px] font-semibold uppercase text-accent"
              title={session.me.principal}>
          {session.me.principal.slice(0, 2)}
        </span>
        <button className="btn btn-sm btn-ghost !px-2" title={t('session.signout')}
                onClick={() => signOut().finally(() => location.reload())}>
          <LogOut size={15} />
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-2.5 border-t border-line p-2.5">
      {/* Two choices, not three. The system preference is the starting point,
          so a "system" button would only ever mean "go back to the default" —
          a third control for a state the console already begins in. Pressing
          either one pins it from then on. */}
      <div className="segment w-full">
        {[['light', Sun], ['dark', Moon]].map(([m, Icon]) => (
          <button key={m} type="button" aria-pressed={resolved === m}
                  onClick={() => setMode(m)} title={t(`theme.${m}`)}>
            <Icon size={14} />
            {t(`theme.${m}`)}
          </button>
        ))}
      </div>

      <Toggle checked={devMode} onChange={setDevMode}
              label={t('devmode.label')} hint={t('devmode.hint')} />

      <label className="relative block">
        <Globe size={14} className="pointer-events-none absolute left-2.5 top-1/2
                                    -translate-y-1/2 text-text-3" />
        <select value={lang} onChange={(e) => setLang(e.target.value)}
                aria-label={t('lang.label')}
                className="field appearance-none !py-1.5 pl-8 text-[12.5px]">
          {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
        </select>
        <ChevronDown size={14} className="pointer-events-none absolute right-2.5
                                          top-1/2 -translate-y-1/2 text-text-3" />
      </label>

      <div className="flex items-center gap-2 rounded-lg px-1 py-1">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full
                         bg-accent-soft text-[11px] font-semibold uppercase text-accent">
          {session.me.principal.slice(0, 2)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] font-medium text-text">
            {session.me.principal}
          </span>
          <span className="block text-[11px] text-text-3">
            {session.me.admin ? t('session.admin') : t('session.member')}
          </span>
        </span>
        <button className="btn btn-sm btn-ghost" title={t('session.signout')}
                onClick={() => signOut().finally(() => location.reload())}>
          <LogOut size={15} />
        </button>
      </div>
    </div>
  )
}
