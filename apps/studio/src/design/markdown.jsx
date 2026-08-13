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

import { api } from '../api.js'
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

/** `media={{ forest }}` opts a surface into J.10.9: a markdown image whose
 *  address is `media:<node id>` is resolved after mount through the J.14
 *  payload route, with the viewer's own credential — so scope is enforced
 *  where it always is, and an id the model invented (or one this viewer may
 *  not read) renders as its caption and nothing else. */
export function Markdown({ children, className = '', media = null }) {
  const { resolved } = useTheme()
  const host = useRef(null)
  const sources = useRef([])
  const mediaRefs = useRef([])
  const [failed, setFailed] = useState(false)

  const html = useMemo(() => {
    sources.current = []
    mediaRefs.current = []
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
    if (media?.forest) {
      // Same discipline as the diagrams: the id and the caption are parked
      // in a ref the sanitiser never sees, and only an index enters markup.
      const baseImage = renderer.image.bind(renderer)
      renderer.image = (token) => {
        const href = String(token.href || '')
        if (href.startsWith('media:')) {
          const i = mediaRefs.current.push({
            id: href.slice('media:'.length),
            alt: String(token.text || ''),
          }) - 1
          return `<span class="md-media" data-media="${i}"></span>`
        }
        return baseImage(token)
      }
    }
    const parsed = marked.parse(String(children ?? ''), {
      renderer, gfm: true, breaks: true,
    })
    return DOMPurify.sanitize(parsed, { ADD_ATTR: ['target'] })
  }, [children, media?.forest])

  useEffect(() => {
    const slots = host.current?.querySelectorAll('.md-media') || []
    if (!media?.forest || !slots.length) return
    let alive = true
    const urls = []
    ;(async () => {
      for (const slot of slots) {
        const ref = mediaRefs.current[Number(slot.dataset.media)]
        if (!alive || !ref) continue
        try {
          const p = await api.payload(media.forest, ref.id)
          if (!p.type.startsWith('image/')) {
            p.cancel()
            throw new Error('not an image')
          }
          const blob = await p.blob()
          if (!alive) return
          const url = URL.createObjectURL(blob)
          urls.push(url)
          const link = document.createElement('a')
          link.href = url
          link.target = '_blank'
          link.rel = 'noreferrer'
          const img = document.createElement('img')
          img.src = url
          img.alt = ref.alt
          img.className = 'md-media-img max-h-[420px] max-w-full rounded-lg '
            + 'border border-line bg-surface-2 object-contain'
          link.replaceChildren(img)
          slot.replaceChildren(link)
        } catch {
          // The caption, never an error card: a failed reference must not
          // outrank the answer it decorates (J.10.9).
          if (alive && ref.alt) {
            const cap = document.createElement('em')
            cap.className = 'text-text-3'
            cap.textContent = ref.alt
            slot.replaceChildren(cap)
          }
        }
      }
    })()
    return () => {
      alive = false
      urls.forEach((u) => URL.revokeObjectURL(u))
    }
  }, [html, media?.forest])

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
