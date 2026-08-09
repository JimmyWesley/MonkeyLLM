/* Governed editing (spec J.5.4).
 *
 * The whole point of this screen is what it does NOT do: it never writes a
 * file. It is a rich editor whose Save is a `graft` — the same call an
 * agent makes over MCP, validated by the same parser, committed by the same
 * git, stamped with the acting principal by the same host. Humans and
 * agents write through one door.
 *
 * Two consequences shape the design.
 *
 * **One section per edit.** `graft` replaces one section atomically (C.8).
 * Editing the whole body would mean several grafts, several commits, and a
 * half-applied edit whenever the third one failed. So the editor works at
 * the contract's own grain: pick a section, edit it, one commit. The
 * frontmatter form rides along in the same patch, because `set_frontmatter`
 * is part of the same operation.
 *
 * **The patch is shown before it is sent.** The operator is authoring a
 * commit, and a commit is not a keystroke: the exact operations appear
 * beside the editor, in the shape the API will receive them.
 */
import { useEffect, useMemo, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import { marked } from 'marked'
import TurndownService from 'turndown'

import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, ErrorNote, Field, Note, Skeleton,
} from '../design/ui.jsx'
import { Check, ChevronLeft, Code2, Pencil, Save, Undo } from '../design/icons.jsx'
import { has, useAsync } from './shared.jsx'

/* Markdown is what the forest stores; the editor speaks HTML. The pair is
 * kept in one place so a round trip cannot drift between two settings. */
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

/** The engine's own budget for a summary (models.validate_summary): 60
 *  tokens, counted the way the parser counts them — whitespace-separated. */
const SUMMARY_TOKENS = 60
const countTokens = (s) => String(s || '').split(/\s+/).filter(Boolean).length

/** Sections of a markdown body, `## Header` down. The editor offers these
 *  because `replace_section` addresses exactly them. */
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

  const digest = useAsync(() => api.call(forest, 'look', { id }), [forest, id])
  const body = useAsync(() => api.call(forest, 'pick', { id }), [forest, id])

  const sections = useMemo(() => sectionsOf(body.data?.body), [body.data])
  const original = sections.find((s) => s.header === section) || null

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [2, 3] } }),
      Placeholder.configure({ placeholder: t('editor.placeholder') }),
    ],
    content: '',
    editorProps: { attributes: { class: 'editor-surface' } },
  }, [])

  // The passport form and the first section load once the two reads land.
  useEffect(() => {
    if (!digest.data || form) return
    setForm({
      title: digest.data.title || '',
      summary: digest.data.summary || '',
      tags: (digest.data.tags || []).join(', '),
    })
  }, [digest.data, form])

  useEffect(() => {
    if (!sections.length || section !== null) return
    setSection(sections[0].header)
  }, [sections, section])

  useEffect(() => {
    if (!editor || !original) return
    editor.commands.setContent(toHtml(original.body))
  }, [editor, original?.header])   // eslint-disable-line react-hooks/exhaustive-deps

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
  const edited = editor ? toMarkdown(editor.getHTML()) : ''
  const tags = form?.tags.split(',').map((s) => s.trim()).filter(Boolean) || []

  /* The patch is derived, never accumulated: what is sent is exactly the
     difference between what was read and what is on screen. */
  const patch = {}
  const frontmatter = {}
  if (form && form.title !== d.title) frontmatter.title = form.title
  if (form && form.summary !== d.summary) frontmatter.summary = form.summary
  if (form && JSON.stringify(tags) !== JSON.stringify(d.tags || [])) {
    frontmatter.tags = tags
  }
  if (Object.keys(frontmatter).length) patch.set_frontmatter = frontmatter
  if (original && edited && edited !== original.body) {
    patch.replace_section = { header: original.header, body: edited }
  }

  const summaryTokens = countTokens(form?.summary)
  const summaryTooLong = summaryTokens > SUMMARY_TOKENS
  const dirty = Object.keys(patch).length > 0

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
    } catch (e) { setError(e) } finally { setSaving(false) }
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
                   error={summaryTooLong ? t('editor.summary_long') : undefined}
                   hint={t('editor.summary_count', { n: summaryTokens,
                                                     max: SUMMARY_TOKENS })}
                   onChange={(e) => setForm({ ...form, summary: e.target.value })} />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] uppercase tracking-[0.06em] text-text-3">
              {t('editor.locked')}
            </span>
            <Badge>id: {d.id}</Badge>
            <Badge>type: {d.type}</Badge>
          </div>
        </Card>

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
      </div>

      <div className="space-y-4">
        <Card title={t('editor.pending')} subtitle={t('editor.pending_hint')}
              icon={Save}>
          {dirty ? (
            <pre className="source-view">{JSON.stringify(patch, null, 2)}</pre>
          ) : (
            <p className="text-[12.5px] text-text-3">{t('common.no_changes')}</p>
          )}

          <div className="mt-3 flex gap-2">
            <button className="btn btn-primary btn-sm" onClick={save}
                    disabled={!dirty || saving || summaryTooLong}>
              {saving ? t('common.saving') : t('editor.commit')}
            </button>
            <button className="btn btn-sm" disabled={!dirty || saving}
                    onClick={() => {
                      setForm({
                        title: d.title || '', summary: d.summary || '',
                        tags: (d.tags || []).join(', '),
                      })
                      if (editor && original) editor.commands.setContent(toHtml(original.body))
                    }}>
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
    </div>
  )
}
