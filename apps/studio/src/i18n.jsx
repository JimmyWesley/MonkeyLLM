// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Localisation (spec J.5.3): English, Portuguese, Spanish — complete.
 *
 * The catalogues live in `locales/<namespace>/{en,pt,es}.json` — one folder
 * per namespace, one file per language inside it, so a translator working on
 * one console area opens one folder instead of hunting a flat 700-key file,
 * and a missing key is locatable by the namespace it should have been in.
 * Vite inlines JSON imports at build time, so this still ships as one bundle
 * with no runtime fetch.
 *
 * Dependency-free on purpose. An i18n library buys plurals, dates and lazy
 * catalogues; this console needs none of those and the deployment is one
 * image with no CDN, so a 60-line context beats a 40 kB runtime.
 *
 * Flat dotted keys, three files per namespace: a missing translation is
 * visible in review and provable in test (`tests/test_studio_i18n.py` fails
 * on the first key absent from any language), which is what makes "complete"
 * a rule rather than an intention.
 *
 * What is NOT translated: node ids, titles, summaries, bodies, SQL and model
 * output. Those are forest content, and a console that rewrote them would be
 * lying about what is stored.
 */
import { createContext, useContext, useEffect, useMemo, useState } from 'react'

const STORAGE = 'monkeyllm.studio.lang'

export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'pt', label: 'Português' },
  { code: 'es', label: 'Español' },
]

// One glob over every namespace folder, merged back into a flat per-language
// dictionary so the rest of this module — and every `t()` call site — never
// has to know namespaces exist. `eager: true` keeps this a build-time inline
// (no runtime fetch); a namespace missing a language file just contributes
// nothing here, which is why completeness is proven in the test suite and
// not asserted at import time — a throw here would take the whole console
// down for a typo in a language nobody is using yet.
const files = import.meta.glob('./locales/*/*.json', { eager: true })

const DICTIONARIES = { en: {}, pt: {}, es: {} }
for (const [path, mod] of Object.entries(files)) {
  const lang = path.slice(path.lastIndexOf('/') + 1, -'.json'.length)
  if (DICTIONARIES[lang]) Object.assign(DICTIONARIES[lang], mod.default)
}

export { DICTIONARIES }

function detect() {
  const saved = localStorage.getItem(STORAGE)
  if (saved && DICTIONARIES[saved]) return saved
  for (const tag of navigator.languages || [navigator.language || 'en']) {
    const code = String(tag).slice(0, 2).toLowerCase()
    if (DICTIONARIES[code]) return code
  }
  return 'en'
}

const I18nContext = createContext(null)

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(detect)

  useEffect(() => { document.documentElement.lang = lang }, [lang])

  const value = useMemo(() => {
    const dict = DICTIONARIES[lang] || DICTIONARIES.en
    /** Interpolates {name} placeholders. An unknown key returns itself, so a
     *  gap is loud in the interface instead of rendering as blank. */
    const t = (key, vars) => {
      let out = dict[key] ?? DICTIONARIES.en[key] ?? key
      if (vars) {
        for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(v)
      }
      return out
    }
    return {
      lang, t,
      setLang: (next) => { localStorage.setItem(STORAGE, next); setLangState(next) },
    }
  }, [lang])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export const useI18n = () => useContext(I18nContext)
