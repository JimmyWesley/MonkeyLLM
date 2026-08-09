/* Localisation (spec J.5.3): English, Portuguese, Spanish — complete.
 *
 * The catalogues live in `locales/{en,pt,es}.json` — one file per language,
 * so a translation pass reads one file top to bottom instead of scrolling
 * three dictionaries stacked in one module. Vite inlines JSON imports at
 * build time, so this still ships as one bundle with no runtime fetch.
 *
 * Dependency-free on purpose. An i18n library buys plurals, dates and lazy
 * catalogues; this console needs none of those and the deployment is one
 * image with no CDN, so a 60-line context beats a 40 kB runtime.
 *
 * Flat dotted keys, three files side by side: a missing translation is
 * visible in review and provable in test (`tests/test_studio_i18n.py` fails
 * on the first key absent from any language), which is what makes "complete"
 * a rule rather than an intention.
 *
 * What is NOT translated: node ids, titles, summaries, bodies, SQL and model
 * output. Those are forest content, and a console that rewrote them would be
 * lying about what is stored.
 */
import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import en from './locales/en.json'
import pt from './locales/pt.json'
import es from './locales/es.json'

const STORAGE = 'monkeyllm.studio.lang'

export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'pt', label: 'Português' },
  { code: 'es', label: 'Español' },
]

export const DICTIONARIES = { en, pt, es }

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
    const dict = DICTIONARIES[lang] || en
    /** Interpolates {name} placeholders. An unknown key returns itself, so a
     *  gap is loud in the interface instead of rendering as blank. */
    const t = (key, vars) => {
      let out = dict[key] ?? en[key] ?? key
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
