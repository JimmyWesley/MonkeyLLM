// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* One console may fail; the console may not disappear.
 *
 * React 18 unmounts the whole tree on an uncaught render throw, so a single
 * bad element anywhere below `App` leaves a blank page with no navigation,
 * no forest picker and no way back — the operator's only repair is guessing
 * that a reload might help. That is what a `<Field>` wrapping a `<Select>`
 * did to the reading console: React refused an `<input>` with children
 * (#137) and took the entire Studio down with it, every time a document was
 * opened.
 *
 * The boundary is not the fix for that bug — the bug is fixed where it was
 * written. It is the answer to the *class*: the shell survives, the address
 * still says where the operator is, and the failure is reported as one
 * console's failure instead of as the product ending.
 *
 * Deliberately below the Shell and never above it: a boundary that also
 * caught the navigation would leave nothing to navigate WITH.
 */
import { Component } from 'react'
import { useI18n } from '../i18n.jsx'
import { Card } from '../design/ui.jsx'
import { Alert } from '../design/icons.jsx'

export class Boundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // The console has no error sink of its own, and inventing one would be a
    // second, unaudited channel out of the operator's browser (J.5.13's
    // premise). The devtools console is where a front-end failure belongs.
    console.error('Studio console failed to render', error, info)   // eslint-disable-line no-console
  }

  componentDidUpdate(prev) {
    // `resetKey` is the place: moving console, forest or node must clear a
    // failure that belonged to where the operator no longer is. Without
    // this, one broken document would poison every later navigation.
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  render() {
    if (!this.state.error) return this.props.children
    return <Crashed error={this.state.error}
                    onRetry={() => this.setState({ error: null })} />
  }
}

/** The report. A function component because the strings are translated and
 *  a class cannot hold a hook. */
function Crashed({ error, onRetry }) {
  const { t } = useI18n()
  return (
    <Card>
      <div className="py-6 text-center">
        <span className="mx-auto mb-3 grid h-11 w-11 place-items-center rounded-xl
                         bg-surface-2 text-danger"><Alert size={20} /></span>
        <p className="text-[13.5px] font-medium text-text">{t('app.crashed')}</p>
        <p className="mx-auto mt-1 max-w-[46ch] text-[12.5px] text-text-3">
          {t('app.crashed_hint')}
        </p>
        {error?.message && (
          <code className="mx-auto mt-3 block max-w-[60ch] truncate rounded-lg bg-surface-2
                           px-3 py-1.5 text-left text-[11.5px] text-text-3">
            {String(error.message)}
          </code>
        )}
        <button className="btn btn-primary btn-sm mt-4" onClick={onRetry}>
          {t('app.crashed_retry')}
        </button>
      </div>
    </Card>
  )
}
