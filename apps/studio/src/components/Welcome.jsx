// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* First access (J.5.11): the one-time presentation.
 *
 * The first signed-in minute decides what a person believes this
 * deployment is; left alone they conclude the console is the product. It
 * is a window — the forest behind it is fed and read by AIs over MCP, and
 * this is the only moment the product gets to say so.
 *
 * Chrome, wholly: shown at most once per browser (the flag is browser
 * storage, same standing as the reply-size preference), dismissing it
 * spends nothing — no model call, no commit, no address change — and it
 * never precedes identity, because the Shell it renders in already
 * requires a session. J.2.4's setup and J.5.6's gate are untouched.
 */
import { useState } from 'react'
import { useI18n } from '../i18n.jsx'
import { hrefFor, navigate } from '../router.js'
import { Modal } from '../design/ui.jsx'
import { Ask, Ingest, Plug, Sparkle } from '../design/icons.jsx'
import { has } from '../views/shared.jsx'

const WELCOMED = 'monkeyllm.studio.welcomed'

const PILLARS = [
  [Plug, 'connect'],
  [Ingest, 'feed'],
  [Ask, 'ask'],
]

export default function Welcome({ forest, grant }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(WELCOMED) !== '1' } catch { return false }
  })

  const dismiss = () => {
    try { localStorage.setItem(WELCOMED, '1') } catch { /* private mode */ }
    setOpen(false)
  }

  // Navigation-only: the modal may LINK to consoles that do real work,
  // never do any itself (J.5.11).
  const toSkills = () => {
    dismiss()
    if (forest) navigate(hrefFor(forest, 'skills'))
  }

  const canRead = has(grant, 'read')

  return (
    <Modal open={open} onClose={dismiss} wide
           title={t('welcome.title')} subtitle={t('welcome.sub')}
           footer={<>
             {canRead && forest && (
               <button className="btn" onClick={toSkills}>
                 <Sparkle size={14} /> {t('welcome.skills_cta')}
               </button>
             )}
             <button className="btn btn-primary" onClick={dismiss}>
               {t('welcome.start')}
             </button>
           </>}>
      <p className="max-w-[62ch] text-[13px] leading-relaxed text-text-2">
        {t('welcome.p1')}
      </p>
      <div className="mt-4 grid gap-2.5 sm:grid-cols-3">
        {PILLARS.map(([Icon, k]) => (
          <div key={k} className="rounded-lg border border-line bg-surface-2 p-3">
            <span className="mb-2 grid h-8 w-8 place-items-center rounded-lg
                             bg-surface text-accent">
              <Icon size={16} />
            </span>
            <p className="text-[12.5px] font-medium text-text">{t(`welcome.${k}.title`)}</p>
            <p className="mt-1 text-[12px] leading-relaxed text-text-3">{t(`welcome.${k}.p`)}</p>
          </div>
        ))}
      </div>
    </Modal>
  )
}
