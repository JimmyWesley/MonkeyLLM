// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import { I18nProvider } from './i18n.jsx'
import { ThemeProvider } from './theme.jsx'
import { DevModeProvider } from './devmode.jsx'
import './index.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ThemeProvider>
      <DevModeProvider>
        <I18nProvider>
          <App />
        </I18nProvider>
      </DevModeProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
