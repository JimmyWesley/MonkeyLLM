// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useRef, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import TurndownService from 'turndown'

import { api } from '../api.js'
import { useRouteState } from '../router.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Empty, ErrorNote, Field, Note, Select, Spinner, Tabs,
} from '../design/ui.jsx'
import { File, Ingest as Upload, Pencil, Plus, Refresh, X } from '../design/icons.jsx'
import {
  NeedsCapability, NewBranch, branchOf, has, nodeLink, useAsync, useForestTree,
} from './shared.jsx'

/* What the Gardener's built-in converters read (G.2). Text goes up as text;
 * .docx/.xlsx go up as base64, because their converters read bytes. Anything
 * else is refused HERE, by name, instead of being dropped on the floor: an
 * upload that silently ignores half the selection is indistinguishable from
 * one that failed. */
const TEXTUAL = /\.(md|markdown|txt|csv|json|tsv|ya?ml)$/i
const BINARY = /\.(docx|xlsx)$/i
const ACCEPT = '.md,.markdown,.txt,.csv,.json,.tsv,.yaml,.yml,.docx,.xlsx'
const MAX_BYTES = 25 * 1024 * 1024

/* The Curator's own wording for the one rejection with a specific cure:
 * a thinking model that spent its whole budget before writing anything. */
const EMPTY_REPLY = 'the model returned an empty message'

/* Chunked so a 20 MB document does not blow the argument limit of
 * String.fromCharCode with one spread of the whole array. */
function toBase64(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i += 8192) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192))
  }
  return btoa(binary)
}

/* Drag-and-drop hands over directory entries, not files. Walking them is what
 * makes dropping a folder behave like choosing one. */
async function filesFromEntry(entry, prefix = '') {
  if (entry.isFile) {
    const file = await new Promise((res, rej) => entry.file(res, rej))
    return [{ file, path: prefix + file.name }]
  }
  if (!entry.isDirectory) return []
  const reader = entry.createReader()
  const out = []
  for (;;) {
    // readEntries returns at most 100 per call — it must be drained.
    const batch = await new Promise((res, rej) => reader.readEntries(res, rej))
    if (!batch.length) break
    for (const child of batch) {
      out.push(...await filesFromEntry(child, `${prefix}${entry.name}/`))
    }
  }
  return out
}

/* The composer writes prose; the forest stores markdown. One converter,
 * configured once, so the round trip cannot drift. */
const turndown = new TurndownService({
  headingStyle: 'atx', bulletListMarker: '-', codeBlockStyle: 'fenced',
})

export default function Ingest({ forest, grant, goto }) {
  const { t } = useI18n()
  // The tab is in the address; what is staged in it is not. Files, a draft
  // and a destination are work in progress, and a reload has already lost
  // them — an address that claimed otherwise would be worse than one that
  // does not mention them.
  const [mode, setMode] = useRouteState('mode', 'upload',
                                        { allow: ['upload', 'adopt', 'compose'] })
  const [title, setTitle] = useState('')
  const [files, setFiles] = useState([])
  const [dest, setDest] = useState('')
  const [path, setPath] = useState('')
  const [state, setState] = useState({})
  const [skipped, setSkipped] = useState([])
  const [reading, setReading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [makingBranch, setMakingBranch] = useState(false)
  const picker = useRef(null)
  const folderPicker = useRef(null)
  const staging = useRef(0)

  /* The composer (J.8's `compose`). Mounted once, not per tab switch: a
     draft that vanished because somebody looked at the Upload tab would be
     a draft nobody trusts. */
  const composer = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [2, 3] } }),
      Placeholder.configure({ placeholder: t('ingest.compose_placeholder') }),
    ],
    content: '',
    editorProps: { attributes: { class: 'editor-surface' } },
  }, [])

  const tree = useForestTree(forest, grant, api.call)
  // undefined = still asking, null = nothing bound, object = the binding.
  // Only an admin may read bindings; for anyone else it stays `false`, and
  // the card says nothing rather than guessing.
  const bindings = useAsync(() => api.bindings(forest).then((b) => b.bindings),
                            [forest], { skip: !has(grant, 'admin') })
  const bound = !has(grant, 'admin') ? false
    : bindings.busy ? undefined
    : (bindings.data || []).find((b) => b.role === 'ingest') || null

  /* J.8: a refresh reads a directory the request never names — it comes
     from what a past adopt recorded. So the console asks what that is and
     shows it, because a button whose reach is invisible is not consent.
     Re-asked after every run: an adopt is exactly what changes the answer. */
  const ingestState = useAsync(() => api.ingestStatus(forest),
                               [forest, state.report])
  const status = ingestState.data || {}

  if (!has(grant, 'ingest')) {
    return <NeedsCapability message={t('ingest.needs_cap')} hint={t('cap.ingest')} />
  }

  /* `list` is either a FileList (picker) or [{file, path}] (dropped tree). */
  async function take(list) {
    const entries = Array.from(list).map((item) => (
      item.file ? item : { file: item, path: item.webkitRelativePath || item.name }))
    const picked = []
    const refused = []
    setReading(true)
    try {
      for (const { file, path } of entries) {
        const binary = BINARY.test(path)
        if (!binary && !TEXTUAL.test(path)) {
          refused.push({ name: path, why: 'type' })
          continue
        }
        if (file.size > MAX_BYTES) {
          refused.push({ name: path, why: 'size' })
          continue
        }
        picked.push(binary
          ? { name: path, b64: toBase64(await file.arrayBuffer()), bytes: file.size }
          : { name: path, text: await file.text(), bytes: file.size })
      }
    } finally { setReading(false) }
    // Same name twice in one batch would stage the first and lose it.
    setFiles((prev) => {
      const byName = new Map(prev.map((f) => [f.name, f]))
      for (const f of picked) byName.set(f.name, f)
      return [...byName.values()]
    })
    setSkipped((prev) => [...prev, ...refused])
  }

  async function drop(e) {
    e.preventDefault()
    setDragging(false)
    const items = Array.from(e.dataTransfer.items || [])
      .map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null))
      .filter(Boolean)
    if (!items.length) return take(e.dataTransfer.files)
    const found = []
    for (const entry of items) found.push(...await filesFromEntry(entry))
    return take(found)
  }

  async function submit(e) {
    e.preventDefault()
    setState({ busy: true })
    try {
      // `bytes` is display-only; the wire contract is {name, text|b64}.
      const payload = files.map(({ bytes, ...rest }) => rest)
      // Composing does NOT publish (J.8.1): it stages, and what comes back
      // is a proposal. The text travels with the review so the accepting
      // call sends the same bytes the Curator read — re-serialising the
      // editor at publish time would let a stray keystroke change the
      // document out from under the passport that was approved.
      const composition = {
        mode: 'compose', title: title.trim(),
        text: turndown.turndown(composer?.getHTML() || ''),
        dest: dest || undefined,
      }
      const body = mode === 'upload'
        ? { mode, files: payload, dest: dest || undefined }
        : mode === 'adopt' ? { mode, path, dest: dest || undefined }
        : mode === 'compose' ? { ...composition, stage: true }
        : { mode: 'sync' }
      const report = await api.ingest(forest, body)
      // The report is the fresher fact about what is bound: a model bound
      // from another tab (or from Models, moments ago) would otherwise leave
      // this card contradicting the report right below it.
      bindings.reload()
      if (mode === 'compose') {
        // `stamp` remounts the review card. Keying it on the draft id would
        // not: staging the same title twice returns the same id, so an
        // edited text would come back under the previous review's summary,
        // tags and unticked boxes — the reviewer would approve a passport
        // they never saw.
        staging.current += 1
        setState({ busy: false,
                   review: { ...composition, ...report, stamp: staging.current } })
        return  // nothing has been planted yet; the composer keeps its text
      }
      setState({ busy: false, report })
      if (mode === 'upload') { setFiles([]); setSkipped([]) }
    } catch (error) { setState({ busy: false, error }) }
  }

  /** Phase two: the reviewer accepted, with whatever edits they made. */
  async function publish(draft) {
    const { title: t0, text, dest: d0 } = state.review
    setState({ ...state, busy: true })
    try {
      const report = await api.ingest(forest, {
        mode: 'compose', title: t0, text, dest: d0, draft,
      })
      setState({ busy: false, report })
      setTitle('')
      composer?.commands.clearContent()
      bindings.reload()
    } catch (error) { setState({ ...state, busy: false, error }) }
  }

  const composed = (composer?.getText() || '').trim()
  const ready = mode === 'upload' ? files.length > 0
    : mode === 'adopt' ? Boolean(path)
    : mode === 'compose' ? Boolean(title.trim() && composed)
    // J.8: a forest with no recorded source has nothing to refresh, and one
    // whose source left this Station's ingest roots cannot be refreshed from
    // here. Both are refused by the API; the button says so before the click
    // rather than after it. `busy` keeps it disabled until the answer lands,
    // so the enabled state is never a guess.
    : Boolean(status.can_sync)

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <div className="min-w-0 space-y-4">
        <Card title={t('ingest.title')} subtitle={t('ingest.sub')} icon={Upload}>
          <Tabs value={mode} onChange={(m) => { setMode(m); setState({}) }} options={[
            { value: 'upload', label: t('ingest.mode_upload') },
            { value: 'compose', label: t('ingest.mode_compose') },
            // Mirroring needs the capability AND a Station configured to read
            // host folders at all (J.8.2). Offering a tab whose every submit
            // is refused teaches the operator nothing about why.
            ...(has(grant, 'admin') && status.host_paths !== false
              ? [{ value: 'adopt', label: t('ingest.mode_adopt') }] : []),
            { value: 'sync', label: t('ingest.mode_sync') },
          ]} />

          <form onSubmit={submit} className="mt-4 space-y-4">
            {/* The mirror tab is gone for an admin only because this Station
                was never told which folders it may read (J.8.2). Silence
                would read as "the feature is missing". */}
            {mode === 'upload' && has(grant, 'admin') && status.host_paths === false && (
              <Note>{t('ingest.no_host_paths')}</Note>
            )}
            {mode === 'upload' && (
              <>
                <div
                  onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={drop}
                  className={`grid place-items-center rounded-xl border-2
                    border-dashed px-4 py-10 text-center transition
                    ${dragging ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong'}`}
                >
                  <span className="mb-2 grid h-11 w-11 place-items-center rounded-xl
                                   bg-surface-2 text-text-3"><Upload size={20} /></span>
                  <p className="text-[13.5px] font-medium text-text">{t('ingest.drop')}</p>
                  <p className="mt-1 text-[12px] text-text-3">{t('ingest.drop_hint')}</p>
                  {/* Two explicit buttons: "choose a folder" meant the folder on
                      your own machine, and there was no way to say that. */}
                  <div className="mt-3 flex gap-2">
                    <button type="button" className="btn btn-sm"
                            onClick={() => picker.current?.click()}>
                      {t('ingest.pick_files')}
                    </button>
                    <button type="button" className="btn btn-sm"
                            onClick={() => folderPicker.current?.click()}>
                      {t('ingest.pick_folder')}
                    </button>
                  </div>
                  <input ref={picker} type="file" multiple accept={ACCEPT} className="hidden"
                         onChange={(e) => take(e.target.files)} />
                  <input ref={folderPicker} type="file" multiple webkitdirectory=""
                         directory="" className="hidden"
                         onChange={(e) => take(e.target.files)} />
                </div>

                {reading && <Spinner label={t('ingest.reading')} />}

                {skipped.length > 0 && (
                  <Note tone="warn">
                    <div>{t('ingest.skipped', { n: skipped.length })}</div>
                    <ul className="mt-1.5 max-h-28 space-y-0.5 overflow-y-auto">
                      {skipped.slice(0, 20).map((s, i) => (
                        <li key={`${s.name}-${i}`} className="font-mono text-[11.5px]">
                          {s.name} — {t(s.why === 'size' ? 'ingest.skip_size'
                                                         : 'ingest.skip_type')}
                        </li>
                      ))}
                    </ul>
                    <button type="button" className="btn btn-sm btn-ghost mt-2"
                            onClick={() => setSkipped([])}>
                      {t('common.close')}
                    </button>
                  </Note>
                )}

                {files.length > 0 && (
                  <div>
                    <div className="label">{t('ingest.chosen', { n: files.length })}</div>
                    <ul className="max-h-44 space-y-1 overflow-y-auto">
                      {files.map((f, i) => (
                        <li key={`${f.name}-${i}`}
                            className="flex items-center gap-2 rounded-lg border border-line
                                       bg-surface-2 px-2.5 py-1.5">
                          <File size={14} className="text-text-3" />
                          <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-2">
                            {f.name}
                          </span>
                          <span className="text-[11px] text-text-3">
                            {((f.bytes ?? f.text?.length ?? 0) / 1024).toFixed(1)} kB
                          </span>
                          <button type="button" className="btn btn-sm btn-ghost !p-1"
                                  onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                            <X size={13} />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            )}

            {mode === 'compose' && (
              <>
                <Note>{t('ingest.compose_hint')}</Note>
                <Field label={t('ingest.compose_title')} value={title} required
                       placeholder={t('ingest.compose_title_ph')}
                       hint={t('ingest.compose_title_hint')}
                       onChange={(e) => setTitle(e.target.value)} />
                <div>
                  <div className="label">{t('ingest.compose_body')}</div>
                  <Composer editor={composer} />
                </div>
              </>
            )}

            {mode === 'adopt' && (
              <Field label={t('ingest.path')} value={path} required
                     placeholder="/data/handbook" hint={t('ingest.path_hint')}
                     onChange={(e) => setPath(e.target.value)} />
            )}

            {mode === 'sync' ? (
              <div className="space-y-2">
                <Note>{t('ingest.sync_hint')}</Note>
                {/* The whole point of J.8's amendment: name the directory. */}
                {status.source && (
                  <Note>
                    {t('ingest.sync_source')}{' '}
                    <code className="font-mono">{status.source}</code>
                  </Note>
                )}
                {!ingestState.busy && !status.source && (
                  <Note tone="warn">{t('ingest.sync_none')}</Note>
                )}
                {!ingestState.busy && status.source && !status.can_sync && (
                  <Note tone="warn">{t('ingest.sync_blocked')}</Note>
                )}
              </div>
            ) : (
              <div className="space-y-1.5">
                <Select label={t('ingest.dest')} value={dest} hint={t('ingest.dest_hint')}
                        onChange={(e) => setDest(e.target.value)}>
                  <option value="">{t('ingest.dest_root')}</option>
                  {(tree.data?.branches || []).map((b) => {
                    const name = branchOf(b.id)
                    return name ? <option key={b.id} value={name}>{name}</option> : null
                  })}
                </Select>
                {/* J.5.7: "where do these go?" is exactly when the missing
                    branch is noticed, so it can be made from here — and the
                    picker selects what it just made, so this ingest carries
                    on instead of sending the operator to another console. */}
                {has(grant, 'write') && (
                  <button type="button" className="btn btn-sm"
                          onClick={() => setMakingBranch(true)}>
                    <Plus size={13} /> {t('branch.new')}
                  </button>
                )}
              </div>
            )}

            <div className="flex justify-end">
              <button className="btn btn-primary" disabled={!ready || state.busy}>
                {mode === 'sync' ? <Refresh size={14} />
                  : mode === 'compose' ? <Pencil size={14} /> : <Upload size={14} />}
                {state.busy ? t('ingest.running')
                  : mode === 'compose' ? t('ingest.review') : t('ingest.start')}
              </button>
            </div>
          </form>
        </Card>

        {state.busy && <Card><Spinner label={t('ingest.running')} /></Card>}
        {state.error && <Card><ErrorNote error={state.error} /></Card>}
        {state.review && !state.busy && (
          <ReviewDraft key={state.review.stamp} review={state.review}
                       onPublish={publish}
                       onDiscard={() => setState({})} />
        )}
        {state.report && <Report report={state.report} forest={forest} />}
        {!state.busy && !state.error && !state.report && !state.review && (
          <Card><Empty icon={Upload}>{t('ingest.empty')}</Empty></Card>
        )}
      </div>

      <div className="space-y-4">
        <Card title={t('models.role_ingest')} subtitle={t('models.role_ingest_sub')}>
          {/* Asks what is actually bound instead of asserting. The card used
              to state "no ingest model is bound" unconditionally, which read
              as fact and was wrong the moment one was. A principal without
              'admin' cannot see bindings at all, so for them this says
              nothing — the ingest report afterwards carries `curated` and is
              authoritative for everyone. */}
          {bound === undefined ? <Spinner label={t('common.loading')} />
            : bound ? (
              <Note>
                {t('ingest.curated_by', { model: bound.model })}
              </Note>
            ) : bound === null ? (
              <>
                <Note tone="warn">{t('ingest.uncurated')}</Note>
                <button className="btn btn-sm mt-3" onClick={() => goto('models')}>
                  {t('overview.bind_model')}
                </button>
              </>
            ) : null}
        </Card>
      </div>

      <NewBranch
        forest={forest} call={api.call} t={t}
        open={makingBranch} onClose={() => setMakingBranch(false)}
        parents={[{ id: '_index' }, ...(tree.data?.branches || [])]}
        parent={dest ? `${dest}/_index` : '_index'}
        onParent={(id) => setDest(branchOf(id))}
        // Selecting what was just made is the whole point of creating it
        // from here (J.5.7): the ingest that prompted the branch continues.
        onCreated={(id) => { setDest(branchOf(id)); tree.reload() }} />
    </div>
  )
}

/** The compose surface. Deliberately the same editor the node editor uses:
 *  writing a new node and editing an old one are one skill, not two. */
function Composer({ editor }) {
  const { t } = useI18n()
  if (!editor) return <Spinner label={t('common.loading')} />
  const item = (label, active, run, title) => (
    <button key={label} type="button" title={title} aria-pressed={active}
            onClick={run}
            className={`rounded-md px-2 py-1 text-[12px] transition
              ${active ? 'bg-accent-soft text-accent' : 'text-text-3 hover:bg-surface-2'}`}>
      {label}
    </button>
  )
  return (
    <div>
      <div className="flex flex-wrap items-center gap-0.5 rounded-t-lg border
                      border-line bg-surface-2 p-1">
        {item('B', editor.isActive('bold'),
              () => editor.chain().focus().toggleBold().run(), t('editor.bold'))}
        {item('I', editor.isActive('italic'),
              () => editor.chain().focus().toggleItalic().run(), t('editor.italic'))}
        {item('H2', editor.isActive('heading', { level: 2 }),
              () => editor.chain().focus().toggleHeading({ level: 2 }).run(), 'H2')}
        {item('•', editor.isActive('bulletList'),
              () => editor.chain().focus().toggleBulletList().run(), t('editor.list'))}
        {item('1.', editor.isActive('orderedList'),
              () => editor.chain().focus().toggleOrderedList().run(), t('editor.ordered'))}
        {item('❝', editor.isActive('blockquote'),
              () => editor.chain().focus().toggleBlockquote().run(), t('editor.quote'))}
        {item('</>', editor.isActive('codeBlock'),
              () => editor.chain().focus().toggleCodeBlock().run(), t('editor.code'))}
      </div>
      <div className="rounded-b-lg border border-t-0 border-line bg-surface-2 p-3">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}

/** The engine's own budget for a summary (models.validate_summary): 60
 *  tokens, counted the way the parser counts them — whitespace-separated. */
const SUMMARY_TOKENS = 60
const countTokens = (s) => String(s || '').split(/\s+/).filter(Boolean).length

/** Phase one's answer, made decidable (J.8.1).
 *
 *  What is under review is the *passport*, not the prose: the summary is the
 *  scent every later hop navigates by, and each proposal is something the
 *  Ranger will spend the next month promoting or pruning. Both are cheap to
 *  fix here and expensive to fix in a node that already exists.
 *
 *  Dropping a proposal is a checkbox rather than a delete button because
 *  nothing is destroyed by unchecking it — the draft is not stored anywhere,
 *  and Discard throws the whole thing away.
 */
function ReviewDraft({ review, onPublish, onDiscard }) {
  const { t } = useI18n()
  const draft = review.drafts?.[0]
  const [summary, setSummary] = useState(draft?.summary || '')
  const [tags, setTags] = useState((draft?.tags || []).join(', '))
  const [dropped, setDropped] = useState(() => new Set())

  if (!draft) {
    // The Gardener converted nothing — an empty document, or a converter
    // that refused it. Its own errors are the answer, not a blank card.
    return (
      <Card title={t('ingest.review_title')}>
        <ErrorNote error={{ message: review.errors?.[0] || t('ingest.review_none') }} />
        <button className="btn btn-sm mt-3" onClick={onDiscard}>{t('common.close')}</button>
      </Card>
    )
  }

  const links = draft.links || []
  const tokens = countTokens(summary)
  const tooLong = tokens > SUMMARY_TOKENS

  function accept() {
    onPublish({
      ...draft,
      summary,
      tags: tags.split(',').map((s) => s.trim()).filter(Boolean),
      links: links.filter((l) => !dropped.has(l.target)),
    })
  }

  return (
    <Card title={t('ingest.review_title')} subtitle={t('ingest.review_sub')}
          icon={Pencil}
          actions={<Badge tone="warn">{t('ingest.review_pending')}</Badge>}>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge>id: {draft.id}</Badge>
        <Badge>type: {draft.type}</Badge>
        <Badge>{t('ingest.review_parent', { id: draft.parent })}</Badge>
      </div>

      <div className="mt-3">
        <Field as="textarea" rows={3} label={t('ingest.review_summary')}
               value={summary} hint={t('editor.summary_count', { n: tokens,
                                                                 max: SUMMARY_TOKENS })}
               error={tooLong ? t('editor.summary_long') : undefined}
               onChange={(e) => setSummary(e.target.value)} />
      </div>
      <div className="mt-3">
        <Field label={t('editor.tags')} value={tags} hint={t('editor.tags_hint')}
               onChange={(e) => setTags(e.target.value)} />
      </div>

      <div className="mt-4">
        <div className="label">{t('ingest.review_links')}</div>
        {links.length === 0 ? (
          <p className="text-[12.5px] text-text-3">{t('ingest.review_no_links')}</p>
        ) : (
          <ul className="space-y-1.5">
            {links.map((l) => (
              <li key={l.target}
                  className="flex items-start gap-2 rounded-lg border border-line
                             bg-surface-2 px-2.5 py-2">
                <input type="checkbox" className="mt-1" checked={!dropped.has(l.target)}
                       onChange={(e) => {
                         const next = new Set(dropped)
                         if (e.target.checked) next.delete(l.target)
                         else next.add(l.target)
                         setDropped(next)
                       }} />
                <div className="min-w-0 flex-1">
                  {/* The title, not just the id: agreeing to a link whose
                      target you cannot name is not a review. */}
                  <div className="truncate text-[13px] text-text">
                    {l.target_title || l.target}
                  </div>
                  <div className="truncate font-mono text-[11.5px] text-text-3">
                    {l.target}
                  </div>
                  {l.note && (
                    <div className="mt-0.5 text-[12px] text-text-2">{l.note}</div>
                  )}
                </div>
                <Badge>{l.confidence}</Badge>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Note className="mt-4">{t('ingest.review_note')}</Note>

      <div className="mt-4 flex justify-end gap-2">
        <button className="btn" onClick={onDiscard}>{t('ingest.review_discard')}</button>
        <button className="btn btn-primary" onClick={accept} disabled={tooLong}>
          <Pencil size={14} /> {t('ingest.publish')}
        </button>
      </div>
    </Card>
  )
}

function Report({ report, forest }) {
  const { t } = useI18n()
  const groups = [
    ['ingest.planted', report.planted, 'accent'],
    ['ingest.updated', report.updated],
    ['ingest.branches', report.branches],
    ['ingest.unchanged', report.unchanged],
    ['ingest.unsupported', report.unsupported, 'warn'],
    ['ingest.stale', report.stale, 'warn'],
    ['ingest.errors', report.errors, 'danger'],
  ].filter(([, list]) => Array.isArray(list) && list.length > 0)

  const stats = report.curation || {}
  return (
    <Card title={t('ingest.report')}
          actions={<Badge tone={report.curated ? 'accent' : 'default'}>
            {report.mode}
          </Badge>}>
      {/* Four states, not two. The Curator falls back silently by contract
          (G.4 rule 6), so every failure produces the same nodes a working
          ingest would — which is why the report has to name WHICH failure.
          "Never answered" and "answered and was rejected" look identical on
          disk and have opposite fixes. */}
      {report.curated ? (
        <Note tone="info">
          {t('ingest.curated', {
            n: stats.llm_summaries || 0, regions: stats.branch_rollups || 0,
          })}
          {stats.fallbacks > 0 && ` ${t('ingest.curated_partial', { n: stats.fallbacks })}`}
          {stats.repaired > 0 && ` ${t('ingest.curated_trimmed', { n: stats.repaired })}`}
        </Note>
      ) : !report.bound ? (
        <Note tone="warn">{t('ingest.uncurated')}</Note>
      ) : stats.transport_errors > 0 ? (
        <Note tone="danger">
          {t('ingest.model_silent')}
          {stats.error && (
            <div className="mt-1.5 font-mono text-[11.5px]">{stats.error}</div>
          )}
        </Note>
      ) : (
        <Note tone="danger">
          {t('ingest.model_rejected', { n: stats.retries || 0 })}
          {stats.rejected_because && (
            <div className="mt-1.5 font-mono text-[11.5px]">
              {stats.rejected_because}
            </div>
          )}
          {stats.rejected_because === EMPTY_REPLY && (
            <div className="mt-1.5">{t('ingest.model_empty_hint')}</div>
          )}
          {stats.last_reply && (
            <details className="mt-2">
              <summary className="cursor-pointer">{t('ingest.model_reply')}</summary>
              <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap
                              rounded-lg bg-surface px-2 py-1.5 font-mono text-[11.5px]">
                {stats.last_reply}
              </pre>
            </details>
          )}
        </Note>
      )}

      {groups.length === 0 ? (
        <p className="mt-4 text-[13px] text-text-3">{t('ingest.unchanged')}</p>
      ) : (
        <div className="mt-4 space-y-4">
          {groups.map(([key, list, tone]) => (
            <div key={key}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="text-[12.5px] font-medium text-text">{t(key)}</span>
                <Badge tone={tone}>{list.length}</Badge>
              </div>
              <ul className="flex flex-wrap gap-1.5">
                {list.slice(0, 40).map((item, i) => (
                  <li key={i}>
                    {key === 'ingest.errors' || key === 'ingest.unsupported' ? (
                      <span className="badge font-mono">{String(item)}</span>
                    ) : (
                      <a className="badge font-mono hover:border-accent/40 hover:text-accent"
                         {...nodeLink(forest, String(item))}>
                        {String(item)}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {report.commit && (
        <p className="mt-5 border-t border-line pt-3 font-mono text-[11.5px] text-text-3">
          {report.commit_before?.slice(0, 7)} → {report.commit.slice(0, 7)}
        </p>
      )}
    </Card>
  )
}
