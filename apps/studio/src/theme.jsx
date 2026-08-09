/* Light and dark (spec J.5.3), with "system" as the honest default.
 *
 * The choice is written to <html data-theme>, not held in React state that
 * components read: CSS then owns the repaint, an OS-level change while
 * "system" is selected takes effect without a re-render, and the value is
 * applied by a blocking snippet in index.html before first paint so nobody
 * sees a white flash on the way to a dark console.
 */
import { createContext, useCallback, useContext, useEffect, useState } from 'react'

const STORAGE = 'monkeyllm.studio.theme'
const MODES = ['light', 'dark', 'system']

const query = () => window.matchMedia('(prefers-color-scheme: dark)')

export function resolve(mode) {
  return mode === 'system' ? (query().matches ? 'dark' : 'light') : mode
}

export function apply(mode) {
  document.documentElement.dataset.theme = resolve(mode)
}

const ThemeContext = createContext(null)

export function ThemeProvider({ children }) {
  const [mode, setMode] = useState(() => {
    const saved = localStorage.getItem(STORAGE)
    return MODES.includes(saved) ? saved : 'system'
  })

  useEffect(() => {
    apply(mode)
    if (mode !== 'system') return
    const mq = query()
    const onChange = () => apply('system')
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [mode])

  const choose = useCallback((next) => {
    localStorage.setItem(STORAGE, next)
    setMode(next)
  }, [])

  return (
    <ThemeContext.Provider value={{ mode, setMode: choose, resolved: resolve(mode) }}>
      {children}
    </ThemeContext.Provider>
  )
}

export const useTheme = () => useContext(ThemeContext)
