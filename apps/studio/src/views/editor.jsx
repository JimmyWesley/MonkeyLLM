// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

/* Governed editing (spec J.5.4, v0.43).
 *
 * The whole point of this screen is what it does NOT do: it never writes a
 * file. It is an editor whose Save is a `graft` — the same call an agent
 * makes over MCP, validated by the same parser, committed by the same git,
 * stamped with the acting principal by the same host. Humans and agents
 * write through one door.
 *
 * Three consequences shape the design.
 *
 * **The note is the unit of edit (v0.43).** A whole body under the pick
 * budget is edited in one surface and saved as ONE `graft` carrying
 * `replace_body` — one commit for one thought. Two fallbacks keep that
 * honest: a body over the pick budget was read truncated, and writing back
 * less than was read is how notes lose their tails, so it is edited at the
 * section grain; and an index's body is the indexer's render, so it too
 * stays at the section grain.
 *
 * **What the rich editor cannot hold, it must not eat.** A body carrying
 * markdown beyond the rich schema (tables, raw HTML) round-trips lossily —
 * so those bodies open in the Markdown surface, where the bytes on screen
 * are the bytes stored, and the rich mode is locked rather than lossy.
 *
 * **The patch is shown before it is sent.** The operator is authoring a
 * commit, and a commit is not a keystroke: the operations appear beside
 * the editor, in the shape the API will receive them.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import { marked } from 'marked'
import TurndownService from 'turndown'

import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, CodeArea, ErrorNote, Field, Note, Skeleton,
} from '../design/ui.jsx'
import { Highlighted } from '../design/highlight.jsx'
import { Check, ChevronLeft, Code2, Mic, Pencil, Save, Undo } from '../design/icons.jsx'
import { has, useAsync } from './shared.jsx'
import { parseTags } from '../tags.js'

/* Markdown is what the forest stores; the rich editor speaks HTML. The
 * pair is kept in one place so a round trip cannot drift between two
 * settings. */
const turndown = new TurndownService({
  headingStyle: 'atx', bulletListMarker: '-', codeBlockStyle: 'fenced',
})
// A wikilink is forest content, not markup: turndown must not "escape" the
// brackets it does not understand.
turndown.addRule('keepWikilinks', {
  filter: (node) => node.nodeName === 'P' && /\[\[[^\]]+\]\]/.test(node.textContent),
  replacement: (content) => content.replace(/\\\[\\\[/g, '[[').replace(/\\\]\\\]/g, ']]'),
})

const toHtml = (md) => marked.parse(String(md || ''), { gfm: true, breaks: false })
const toMarkdown = (html) => turndown.turndown(String(html || '')).trim()

/** Markdown the rich schema cannot represent: pipe tables and raw HTML
 *  blocks. Round-tripping them through the rich editor would silently drop
 *  them, so such bodies edit as source (J.5.4 v0.43). */
const richLossy = (md) => /^\s*\|.*\|/m.test(md || '') || /^\s*<\w+/m.test(md || '')

/** The engine's own budget for a summary (models.validate_summary): 60
 *  tokens, counted the way the parser counts them — whitespace-separated. */
export const SUMMARY_TOKENS = 60
export const countTokens = (s) => String(s || '').split(/\s+/).filter(Boolean).length

/* -- the scent, extracted (spec J.5.18 rule 1) ----------------------------
 *
 * Title, summary and tags are the fields a reader is best placed to fix,
 * precisely because they are reading — so the Read console offers them too
 * (J.5.18 rule 1). What it does NOT get is a second implementation: the
 * form's shape, the diff that becomes the patch and the fields themselves
 * live here, once, and both consoles mount them. One door for humans and
 * agents was already the rule (J.5.4); this keeps one door for the two
 * screens too.
 *
 * Mounting the whole `NodeEditor` from Read was the other option and it is
 * the wrong one: that editor's subject is the BODY — two grains, a rich
 * surface, a markdown surface, a section picker — and Read is a page
 * somebody is reading. Offering the body editor there would replace the
 * document with Explore's screen, which is the thing rule 1 complains
 * about, pointed the other way.
 */

/** The form as the digest hands it over. Tags become the comma-separated
 *  field a person edits; nothing else is touched. */
export const scentForm = (d) => ({
  title: d?.title || '',
  summary: d?.summary || '',
  tags: (d?.tags || []).join(', '),
})

/** The `set_frontmatter` this form implies — derived, never accumulated:
 *  exactly the difference between what was read and what is on screen, so
 *  opening a node and saving it untouched is a no-op.
 *
 *  The tags go through `parseTags`, which trims the separator's whitespace
 *  and changes nothing else (J.5.18 rule 5): what the engine refuses, the
 *  engine says, naming the tag. A console that quietly lowercased a tag
 *  into something acceptable would be rewriting what somebody typed. */
export function scentFrontmatter(form, d) {
  const out = {}
  if (!form || !d) return out
  const tags = parseTags(form.tags)
  if (form.title !== d.title) out.title = form.title
  if (form.summary !== d.summary) out.summary = form.summary
  if (JSON.stringify(tags) !== JSON.stringify(d.tags || [])) out.tags = tags
  return out
}

/** The three fields, laid out the same way wherever they are mounted. */
export function ScentFields({ form, setForm }) {
  const { t } = useI18n()
  const tokens = countTokens(form?.summary)
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('editor.title')} value={form?.title || ''}
               onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <Field label={t('editor.tags')} value={form?.tags || ''}
               hint={t('editor.tags_hint')}
               onChange={(e) => setForm({ ...form, tags: e.target.value })} />
      </div>
      <div className="mt-3">
        <Field as="textarea" rows={2} label={t('editor.summary')}
               value={form?.summary || ''}
               error={tokens > SUMMARY_TOKENS ? t('editor.summary_long') : undefined}
               hint={t('editor.summary_count', { n: tokens, max: SUMMARY_TOKENS })}
               onChange={(e) => setForm({ ...form, summary: e.target.value })} />
      </div>
    </>
  )
}

/** The scent editor the Read console mounts (J.5.18 rule 1).
 *
 *  The same `graft` an agent makes over MCP, on the same three fields, and
 *  nothing else — no body, no sections. `digest` is the `look` the page
 *  already ran, so this panel costs no second read; `onSaved` hands the
 *  fresh result back so the page can re-read what the engine actually
 *  stored rather than trusting the local copy.
 */
export function ScentEditor({ forest, grant, id, digest, onSaved }) {
  const { t } = useI18n()
  const [form, setForm] = useState(() => scentForm(digest))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)

  // A different node is a different scent: the form follows the subject.
  useEffect(() => {
    setForm(scentForm(digest))
    setError(null)
    setDone(null)
  }, [id, digest])

  // J.5.4 / J.5.17 rule 1: absent rather than disabled where the grant does
  // not carry the capability.
  if (!has(grant, 'write')) return null

  const frontmatter = scentFrontmatter(form, digest)
  const dirty = Object.keys(frontmatter).length > 0
  const tooLong = countTokens(form?.summary) > SUMMARY_TOKENS

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const result = await api.call(forest, 'graft',
                                    { id, patch: { set_frontmatter: frontmatter } })
      setDone(result)
      onSaved?.(result)
    } catch (e) { setError(e); setDone(null) } finally { setSaving(false) }
  }

  return (
    <Card title={t('editor.scent')} subtitle={t('editor.scent_hint')} icon={Pencil}
          bodyClass="p-3">
      <ScentFields form={form} setForm={setForm} />
      <div className="mt-3 flex items-center gap-2">
        <button className="btn btn-primary btn-sm" onClick={save}
                disabled={!dirty || saving || tooLong}>
          {saving ? t('common.saving') : t('editor.commit')}
        </button>
        <button className="btn btn-sm" disabled={!dirty || saving}
                onClick={() => { setForm(scentForm(digest)); setDone(null) }}>
          <Undo size={13} /> {t('editor.discard')}
        </button>
      </div>
      {/* The engine's refusal, rendered as the engine wrote it — it is the
          one thing that names the tag it would not take (J.5.18 rule 5). */}
      <ErrorNote error={error} />
      {done && (
        <Note tone="ok">
          <span className="inline-flex items-center gap-1.5">
            <Check size={14} />
            {t('editor.committed', { commit: (done.commit || '').slice(0, 7) })}
          </span>
        </Note>
      )}
    </Card>
  )
}

/** Sections of a markdown body, `## Header` down. The section grain offers
 *  these because `replace_section` addresses exactly them. */
function sectionsOf(body) {
  const out = []
  const lines = String(body || '').split('\n')
  let current = null
  for (const line of lines) {
    const m = /^(#{2,3})\s+(.+?)\s*$/.exec(line)
    if (m) {
      if (current) out.push(current)
      current = { header: m[2], lines: [] }
      continue
    }
    if (current) current.lines.push(line)
  }
  if (current) out.push(current)
  return out.map((s) => ({ header: s.header, body: s.lines.join('\n').trim() }))
}

export default function NodeEditor({ forest, grant, id, onClose, onSaved }) {
  const { t } = useI18n()
  const [section, setSection] = useState(null)
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const [mode, setMode] = useState(null)   // 'rich' | 'source', whole-note only
  const [src, setSrc] = useState('')
  const srcRef = useRef(null)

  const digest = useAsync(() => api.call(forest, 'look', { id }), [forest, id])
  const body = useAsync(() => api.call(forest, 'pick', { id }), [forest, id])

  // The two grains (J.5.4 v0.43): whole note when the read was whole and
  // the body is the author's; section surgery for truncated reads and for
  // indexes, whose body is the indexer's render.
  const isIndex = id === '_index' || id.endsWith('/_index')
  const whole = Boolean(body.data && !body.data.truncated && !isIndex)
  const orig = body.data?.body || ''

  const sections = useMemo(() => sectionsOf(orig), [orig])
  const original = sections.find((s) => s.header === section) || null
  const lossy = useMemo(() => richLossy(orig), [orig])

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [2, 3] } }),
      Placeholder.configure({ placeholder: t('editor.placeholder') }),
    ],
    content: '',
    editorProps: { attributes: { class: 'editor-surface' } },
  }, [])

  // The passport form loads once the digest lands.
  useEffect(() => {
    if (!digest.data || form) return
    setForm(scentForm(digest.data))
  }, [digest.data, form])

  // Whole-note mode: the body lands in the surface that can hold it.
  useEffect(() => {
    if (!body.data || !whole) return
    const start = lossy ? 'source' : 'rich'
    setMode(start)
    setSrc(orig)
    if (editor && start === 'rich') editor.commands.setContent(toHtml(orig))
  }, [body.data, whole, lossy, editor])   // eslint-disable-line react-hooks/exhaustive-deps

  // Section grain: pick the first section once the body lands.
  useEffect(() => {
    if (whole || !sections.length || section !== null) return
    setSection(sections[0].header)
  }, [whole, sections, section])

  useEffect(() => {
    if (whole || !editor || !original) return
    editor.commands.setContent(toHtml(original.body))
  }, [whole, editor, original?.header])   // eslint-disable-line react-hooks/exhaustive-deps

  if (!has(grant, 'write')) {
    return (
      <Card>
        <Note tone="warn">{t('editor.needs_write')}</Note>
        <button className="btn btn-sm mt-3" onClick={onClose}>
          <ChevronLeft size={14} /> {t('editor.back')}
        </button>
      </Card>
    )
  }
  if (digest.busy || body.busy) return <Card><Skeleton rows={8} /></Card>
  if (digest.error) return <Card><ErrorNote error={digest.error} onRetry={digest.reload} /></Card>
  if (body.error) return <Card><ErrorNote error={body.error} onRetry={body.reload} /></Card>

  const d = digest.data

  /* The patch is derived, never accumulated: what is sent is exactly the
     difference between what was read and what is on screen. In rich mode
     the comparison runs against the round-tripped original, so opening a
     note and saving it untouched stays a no-op. */
  const patch = {}
  const frontmatter = scentFrontmatter(form, d)
  if (Object.keys(frontmatter).length) patch.set_frontmatter = frontmatter

  if (whole && mode === 'rich' && editor) {
    const edited = toMarkdown(editor.getHTML())
    const baseline = toMarkdown(toHtml(orig))
    if (edited !== baseline) patch.replace_body = edited
  } else if (whole && mode === 'source') {
    if (src !== orig) patch.replace_body = src
  } else if (!whole && original && editor) {
    const edited = toMarkdown(editor.getHTML())
    if (edited && edited !== original.body) {
      patch.replace_section = { header: original.header, body: edited }
    }
  }

  const summaryTokens = countTokens(form?.summary)
  const summaryTooLong = summaryTokens > SUMMARY_TOKENS
  const dirty = Object.keys(patch).length > 0

  // Shown before it is sent — with a long body folded for the eye. The
  // fold is display only: what the editor holds is what the API receives.
  const shownPatch = patch.replace_body !== undefined && patch.replace_body.length > 400
    ? { ...patch,
        replace_body: `${patch.replace_body.slice(0, 400)}\n… (+${patch.replace_body.length - 400})` }
    : patch

  function switchMode(next) {
    if (next === mode || !editor) return
    if (next === 'source') {
      // An untouched rich surface hands back the stored bytes, not its own
      // normalisation of them.
      const edited = toMarkdown(editor.getHTML())
      const baseline = toMarkdown(toHtml(orig))
      setSrc(edited === baseline ? orig : edited)
    } else {
      editor.commands.setContent(toHtml(src))
    }
    setMode(next)
  }

  function dictate(text) {
    const el = srcRef.current
    if (!el) { setSrc((prev) => `${prev}${prev.endsWith(' ') || !prev ? '' : ' '}${text} `); return }
    const at = el.selectionStart ?? src.length
    const next = `${src.slice(0, at)}${text} ${src.slice(el.selectionEnd ?? at)}`
    setSrc(next)
  }

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const result = await api.call(forest, 'graft', { id, patch })
      setDone(result)
      onSaved?.(result)
      // Re-read rather than trusting the local copy: the engine may have
      // normalised what it stored, and the next patch must diff against
      // what is actually there.
      digest.reload()
      body.reload()
      setForm(null)
      setSection(null)
    } catch (e) { setError(e) } finally { setSaving(false) }
  }

  function discard() {
    setForm(scentForm(d))
    if (whole) {
      setSrc(orig)
      if (editor && mode === 'rich') editor.commands.setContent(toHtml(orig))
    } else if (editor && original) {
      editor.commands.setContent(toHtml(original.body))
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
      <div className="min-w-0 space-y-4">
        <Card title={d.title} subtitle={d.id} icon={Pencil}
              actions={
                <button className="btn btn-sm" onClick={onClose}>
                  <ChevronLeft size={14} /> {t('editor.back')}
                </button>
              }>
          <ScentFields form={form} setForm={setForm} />
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] uppercase tracking-[0.06em] text-text-3">
              {t('editor.locked')}
            </span>
            <Badge>id: {d.id}</Badge>
            <Badge>type: {d.type}</Badge>
          </div>
        </Card>

        {whole ? (
          <Card title={t('common.body')} subtitle={t('editor.whole_hint')}
                icon={Code2}
                actions={
                  <div className="segment">
                    <button type="button" aria-pressed={mode === 'rich'}
                            disabled={lossy}
                            title={lossy ? t('editor.rich_locked') : undefined}
                            onClick={() => switchMode('rich')}>
                      {t('editor.mode_rich')}
                    </button>
                    <button type="button" aria-pressed={mode === 'source'}
                            onClick={() => switchMode('source')}>
                      {t('editor.mode_source')}
                    </button>
                  </div>
                }>
            {lossy && <Note>{t('editor.rich_locked')}</Note>}
            {mode === 'rich' ? (
              <>
                <Toolbar editor={editor} />
                <div className="mt-2 rounded-lg border border-line bg-surface-2 p-3">
                  <EditorContent editor={editor} />
                </div>
              </>
            ) : (
              <>
                <div className="flex justify-end">
                  <Dictation onText={dictate} />
                </div>
                {/* J.5.10: coloured, because this is the surface the rich
                    editor hands back whenever a body holds a table — which
                    every dataset's does. It was the plainest text in the
                    console at exactly the moment structure mattered most. */}
                <CodeArea ref={srcRef} lang="markdown" value={src}
                          className="mt-1" minHeight="22rem"
                          aria-label={t('editor.body')}
                          onChange={(e) => setSrc(e.target.value)} />
              </>
            )}
          </Card>
        ) : (
          <Card title={t('editor.section')} subtitle={t('editor.section_hint')}
                icon={Code2}
                actions={
                  <select className="field !w-auto !py-1.5 text-[12.5px]"
                          value={section || ''}
                          onChange={(e) => setSection(e.target.value)}>
                    {sections.map((s) => (
                      <option key={s.header} value={s.header}>{s.header}</option>
                    ))}
                  </select>
                }>
            {body.data?.truncated && <Note>{t('editor.body_truncated')}</Note>}
            {!sections.length ? (
              <Note>{t('editor.no_sections')}</Note>
            ) : (
              <>
                <Toolbar editor={editor} />
                <div className="mt-2 rounded-lg border border-line bg-surface-2 p-3">
                  <EditorContent editor={editor} />
                </div>
              </>
            )}
          </Card>
        )}
      </div>

      <div className="space-y-4">
        <Card title={t('editor.pending')} subtitle={t('editor.pending_hint')}
              icon={Save}>
          {dirty ? (
            <pre className="source-view">
              <Highlighted text={JSON.stringify(shownPatch, null, 2)} lang="json" />
            </pre>
          ) : (
            <p className="text-[12.5px] text-text-3">{t('common.no_changes')}</p>
          )}

          <div className="mt-3 flex gap-2">
            <button className="btn btn-primary btn-sm" onClick={save}
                    disabled={!dirty || saving || summaryTooLong}>
              {saving ? t('common.saving') : t('editor.commit')}
            </button>
            <button className="btn btn-sm" disabled={!dirty || saving}
                    onClick={discard}>
              <Undo size={13} /> {t('editor.discard')}
            </button>
          </div>

          <ErrorNote error={error} />
          {done && (
            <Note tone="ok">
              <span className="inline-flex items-center gap-1.5">
                <Check size={14} /> {t('editor.committed', { commit: (done.commit || '').slice(0, 7) })}
              </span>
            </Note>
          )}
        </Card>

        <Card title={t('editor.rules')}>
          <ul className="space-y-1.5 text-[12.5px] leading-relaxed text-text-3">
            <li>{t('editor.rule_immutable')}</li>
            <li>{t('editor.rule_summary')}</li>
            <li>{t('editor.rule_commit')}</li>
          </ul>
        </Card>
      </div>
    </div>
  )
}

function Toolbar({ editor }) {
  const { t } = useI18n()
  if (!editor) return null
  const item = (label, active, run, title) => (
    <button key={label} type="button" title={title}
            aria-pressed={active} onClick={run}
            className={`rounded-md px-2 py-1 text-[12px] transition
              ${active ? 'bg-accent-soft text-accent' : 'text-text-3 hover:bg-surface-2'}`}>
      {label}
    </button>
  )
  return (
    <div className="flex flex-wrap items-center gap-0.5 rounded-lg border border-line
                    bg-surface-2 p-1">
      {item('B', editor.isActive('bold'),
            () => editor.chain().focus().toggleBold().run(), t('editor.bold'))}
      {item('I', editor.isActive('italic'),
            () => editor.chain().focus().toggleItalic().run(), t('editor.italic'))}
      {item('H2', editor.isActive('heading', { level: 2 }),
            () => editor.chain().focus().toggleHeading({ level: 2 }).run(), 'H2')}
      {item('H3', editor.isActive('heading', { level: 3 }),
            () => editor.chain().focus().toggleHeading({ level: 3 }).run(), 'H3')}
      {item('•', editor.isActive('bulletList'),
            () => editor.chain().focus().toggleBulletList().run(), t('editor.list'))}
      {item('1.', editor.isActive('orderedList'),
            () => editor.chain().focus().toggleOrderedList().run(), t('editor.ordered'))}
      {item('❝', editor.isActive('blockquote'),
            () => editor.chain().focus().toggleBlockquote().run(), t('editor.quote'))}
      {item('</>', editor.isActive('codeBlock'),
            () => editor.chain().focus().toggleCodeBlock().run(), t('editor.code'))}
      <span className="mx-0.5 h-4 w-px bg-line" aria-hidden="true" />
      <Dictation onText={(text) => editor.chain().focus().insertContent(`${text} `).run()} />
    </div>
  )
}

/* Dictation is an input method, nothing more: the words land in whichever
 * surface is open exactly as typing would land them, and the write still
 * leaves as the one `graft` the operator reviews (J.5.4). Recognition runs
 * in the browser's own engine — no audio touches the Station — and the
 * button only exists where the browser offers the API, which is what makes
 * a phone the place a note gets spoken instead of typed. */
function Dictation({ onText }) {
  const { t, lang } = useI18n()
  const [listening, setListening] = useState(false)
  const rec = useRef(null)
  const wanted = useRef(false)
  // The engine outlives many renders; results must land in the CURRENT
  // surface state, not the one captured when the mic was pressed.
  const onTextRef = useRef(onText)
  useEffect(() => { onTextRef.current = onText })

  const Engine = typeof window !== 'undefined'
    && (window.SpeechRecognition || window.webkitSpeechRecognition)

  useEffect(() => () => {
    wanted.current = false
    rec.current?.stop()
  }, [])

  if (!Engine) return null

  const SPOKEN = { en: 'en-US', pt: 'pt-BR', es: 'es-ES' }

  function stop() {
    wanted.current = false
    setListening(false)
    rec.current?.stop()
  }
  function start() {
    const engine = new Engine()
    engine.lang = SPOKEN[lang] || 'en-US'
    engine.continuous = true
    engine.interimResults = false
    engine.onresult = (ev) => {
      let text = ''
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        if (ev.results[i].isFinal) text += ev.results[i][0].transcript
      }
      text = text.trim()
      if (text) onTextRef.current(text)
    }
    // Browsers end recognition on their own after a silence; while the
    // operator still wants to talk, a quiet pause is not a stop.
    engine.onend = () => {
      if (wanted.current) { try { engine.start() } catch { stop() } }
    }
    engine.onerror = (ev) => {
      if (ev.error !== 'no-speech') stop()
    }
    rec.current = engine
    wanted.current = true
    setListening(true)
    try { engine.start() } catch { stop() }
  }

  return (
    <button type="button" aria-pressed={listening}
            title={listening ? t('editor.dictate_stop') : t('editor.dictate')}
            onClick={() => (listening ? stop() : start())}
            className={`rounded-md px-2 py-1 transition ${listening
              ? 'animate-pulse bg-accent-soft text-accent'
              : 'text-text-3 hover:bg-surface-2'}`}>
      <Mic size={14} />
    </button>
  )
}
