// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Programmer mode — a console-wide, opt-in toggle that recolours JSON and
 * SQL previews (design/highlight.jsx) with the same hues the node-type
 * legend uses. Off by default: the calm palette is what a non-programmer
 * sees, and colourised code is one switch away rather than imposed on
 * every `Code` block in the console.
 */
import { createContext, useCallback, useContext, useState } from 'react'

const STORAGE = 'monkeyllm.studio.devmode'

const DevModeContext = createContext(null)

export function DevModeProvider({ children }) {
  const [on, setOn] = useState(() => localStorage.getItem(STORAGE) === '1')

  const toggle = useCallback((next) => {
    localStorage.setItem(STORAGE, next ? '1' : '0')
    setOn(next)
  }, [])

  return (
    <DevModeContext.Provider value={{ on, toggle }}>
      {children}
    </DevModeContext.Provider>
  )
}

export const useDevMode = () => useContext(DevModeContext)
