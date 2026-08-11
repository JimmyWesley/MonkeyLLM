// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Rendering model output as what it is: markdown.
 *
 * An answer arrives as markdown — headings, lists, tables, fenced code — and
 * showing it as preformatted text made the console display the source of a
 * document instead of the document. Diagrams are the sharper case: asked for
 * one, a model writes a mermaid fence, and a fence is not a diagram.
 *
 * Two rules hold this together:
 *
 * 1. **The text is untrusted.** It is generated, and generation can be
 *    steered by whatever was in the forest. It is parsed, then sanitised,
 *    and only then inserted — never the other way round.
 * 2. **Mermaid is loaded only if a diagram appears.** It is by far the
 *    largest thing this console could ship, and most answers have no
 *    diagram in them; a dynamic import keeps it out of the first paint.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

import { useTheme } from '../theme.jsx'
import { highlightHtml } from './highlight.jsx'

/** Links in generated text point outward. `noopener` is not optional on a
 *  target that the page did not author. */
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.getAttribute('href')?.startsWith('http')) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

export function Markdown({ children, className = '' }) {
  const { resolved } = useTheme()
  const host = useRef(null)
  const sources = useRef([])
  const [failed, setFailed] = useState(false)

  const html = useMemo(() => {
    sources.current = []
    const renderer = new marked.Renderer()
    // Fences are held back, not rendered: the diagram is drawn after mount,
    // from an array the sanitiser never touches. Nothing from the model is
    // interpolated into the markup here.
    renderer.code = ({ text, lang }) => {
      if ((lang || '').trim().toLowerCase() === 'mermaid') {
        const i = sources.current.push(text) - 1
        return `<div class="md-diagram" data-diagram="${i}"></div>`
      }
      // Coloured here rather than after mount: the tokenizer escapes what it
      // emits and the whole string still goes through the sanitiser below,
      // so the fence gains spans without gaining a second trust boundary.
      return `<pre><code>${highlightHtml(text, lang)}</code></pre>`
    }
    const parsed = marked.parse(String(children ?? ''), {
      renderer, gfm: true, breaks: true,
    })
    return DOMPurify.sanitize(parsed, { ADD_ATTR: ['target'] })
  }, [children])

  useEffect(() => {
    const slots = host.current?.querySelectorAll('.md-diagram') || []
    if (!slots.length) return
    let alive = true
    setFailed(false)
    import('mermaid').then(async ({ default: mermaid }) => {
      const draw = async (theme, target) => {
        mermaid.initialize({
          startOnLoad: false, securityLevel: 'strict', theme,
          fontFamily: 'ui-sans-serif, system-ui, sans-serif',
        })
        for (const slot of slots) {
          const src = sources.current[Number(slot.dataset.diagram)]
          if (!alive || src == null) continue
          try {
            // `render` returns a string; the id must be unique per call or
            // mermaid reuses a stale definition from a previous answer.
            const { svg } = await mermaid.render(
              `d-${Math.random().toString(36).slice(2)}`, src)
            if (alive) target(slot, svg)
          } catch {
            // A model can emit invalid mermaid. Showing the source beats
            // showing mermaid's own error card in the middle of an answer.
            if (alive) {
              slot.innerHTML = `<pre><code>${escapeHtml(src)}</code></pre>`
              setFailed(true)
            }
          }
        }
      }

      await draw(resolved === 'dark' ? 'dark' : 'default',
                 (slot, svg) => { slot.innerHTML = svg })

      // Paper is white. A dark-theme diagram carries its colours as `fill`
      // attributes inside the SVG, which no print stylesheet can override —
      // it prints as black boxes with black text. So a light twin is drawn
      // alongside it and swapped in by the print stylesheet. Only when the
      // screen is dark: in light mode the visible one already prints.
      if (resolved !== 'dark') {
        // Switching dark → light re-draws the visible diagram in light, and
        // a twin left over from the dark pass would keep claiming the print
        // slot. Harmless output, stale DOM: clear it.
        for (const slot of slots) {
          slot.classList.remove('md-diagram-screen')
          const twin = slot.nextElementSibling
          if (twin?.classList.contains('md-diagram-print')) twin.remove()
        }
        return
      }
      await draw('default', (slot, svg) => {
        let twin = slot.nextElementSibling
        if (!twin?.classList.contains('md-diagram-print')) {
          twin = document.createElement('div')
          twin.className = 'md-diagram md-diagram-print'
          slot.after(twin)
        }
        twin.innerHTML = svg
        // Marks the original as "has a stand-in for paper". The print rule
        // keys off this and not off `.md-diagram`, so a diagram with no twin
        // — every light-mode one — still prints.
        slot.classList.add('md-diagram-screen')
      })
    }).catch(() => setFailed(true))
    return () => { alive = false }
  }, [html, resolved])

  return (
    <div ref={host} className={`md ${className}`}
         data-diagram-failed={failed || undefined}
         dangerouslySetInnerHTML={{ __html: html }} />
  )
}
