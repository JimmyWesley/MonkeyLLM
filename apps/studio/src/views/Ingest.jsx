// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useEffect, useRef, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import TurndownService from 'turndown'

import { api } from '../api.js'
import { useRouteState } from '../router.js'
import { useI18n } from '../i18n.jsx'
import {
  WATCH, enqueue, noteJob, release, remove as unqueue, takeFired, useAttend,
  useBoard,
} from '../board.js'
import {
  Badge, Card, Empty, ErrorNote, Field, Note, Select, Spinner, Tabs,
} from '../design/ui.jsx'
import {
  Clock, File, Files, Ingest as Upload, Pencil, Play, Plus, Refresh, X,
} from '../design/icons.jsx'
import {
  NeedsCapability, NewBranch, branchOf, has, nodeLink, useAsync, useForestTree,
} from './shared.jsx'

/* What the Gardener's built-in converters read (G.2). Text goes up as text;
 * .docx/.xls/.xlsx and SQLite databases go up as base64, because their
 * converters read bytes. Anything else is refused HERE, by name, instead of
 * being dropped on the floor: an upload that silently ignores half the
 * selection is indistinguishable from one that failed. */
const TEXTUAL = /\.(md|markdown|txt|csv|json|tsv|ya?ml)$/i
const BINARY = /\.(docx|xlsx?|db|sqlite|sqlite3)$/i
const ACCEPT = '.md,.markdown,.txt,.csv,.json,.tsv,.yaml,.yml,.docx,.xls,'
             + '.xlsx,.db,.sqlite,.sqlite3'
const MAX_BYTES = 25 * 1024 * 1024

/* The G.10.1 stages, in the Gardener's order. Named here rather than read
 * off the job, because a bar's fraction needs to know how many phases
 * there are before it has seen them all. */
const STAGES = ['convert', 'curate', 'plant']

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
  // 'optimize' was missing from this list while a tab set it, so clicking
  // the tab wrote `?mode=sync` and the validator handed back the fallback:
  // the console snapped to Upload and the page appeared to close itself.
  // A tab that exists MUST be nameable in the address (J.5.8).
  const [mode, setMode] = useRouteState('mode', 'upload',
                                        { allow: ['upload', 'adopt', 'compose',
                                                  'optimize'] })
  // The running batch, by address (J.9.1): `?job=` is replaced in, so a
  // reload restores the progress view by reading the job — a record, never
  // a call — and Back does not walk the batch's lifetime.
  const [jobId, setJobId] = useRouteState('job', '')
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

  /* The tab's one view of the job board (J.9.3): the batches waiting their
     turn, and the jobs as last read. Tab memory, so both survive a look at
     another console — which is the whole reason they are not state of this
     component. This console is somebody watching, so it registers the fine
     cadence; the board polls once for every reader. */
  const board = useBoard(forest)
  useAttend(forest, WATCH, has(grant, 'ingest'))

  /* J.9.1 (v0.36): the query belongs to its console, so coming back from
     the map loses `?job=` while the batch runs on. Whenever the address
     names no job and the board says one is running — entering, returning,
     or a batch begun by another client — it goes into the address,
     replacing: a correction, not a place the operator went. */
  useEffect(() => {
    if (!jobId && board.running) setJobId(board.running.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board.version, jobId])

  /* When the tab's queue fires a batch, the console that is looking follows
     it — the new job goes into the address exactly as a submit's would,
     even over a settled job's report. A console that is not mounted leaves
     it for the rediscovery above. */
  useEffect(() => {
    const fired = takeFired(forest)
    if (fired) setJobId(fired)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forest, board.version])

  /* The job the address names, read off the board (J.9): host memory, so
     watching is free and survives a reload. An id the board no longer
     carries is a Station that restarted — said as such, never dressed up
     as a failure — but only once the board has actually been read. */
  const job = jobId ? board.jobs.find((j) => j.id === jobId) || null : null
  const jobLost = Boolean(jobId) && board.fetched && !job

  /* A settle is what changes what `sync` would re-read, so the status card
     below re-asks after one. Watched as a transition, not a state: the
     report of a batch that finished last week must not retrigger it. */
  const [settled, setSettled] = useState(0)
  const lastSeen = useRef({ id: null, state: null })
  useEffect(() => {
    const prev = lastSeen.current
    if (job && prev.id === job.id && prev.state === 'running'
        && job.state !== 'running') {
      setSettled((n) => n + 1)
    }
    lastSeen.current = { id: job?.id || null, state: job?.state || null }
  }, [job])

  /* J.8: a refresh reads a directory the request never names — it comes
     from what a past adopt recorded. So the console asks what that is and
     shows it, because a button whose reach is invisible is not consent.
     Re-asked after every run: an adopt is exactly what changes the answer. */
  const ingestState = useAsync(() => api.ingestStatus(forest),
                               [forest, state.report, settled])
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
    // J.9.2: while the board is busy this submit is a promise, not a POST.
    // It joins the tab's queue and fires, in order, when the board frees;
    // the button said so.
    if (queueing) {
      enqueue(forest, body, {
        mode,
        count: mode === 'upload' ? files.length : undefined,
        dest: dest || undefined,
        path: mode === 'adopt' ? path : undefined,
      })
      if (mode === 'upload') { setFiles([]); setSkipped([]) }
      setState({})
      return
    }
    setState({ busy: true })
    try {
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
      if (report.job) {
        // J.9: the batch was accepted, not finished. The job goes onto the
        // board view first-hand and into the address; the watcher takes
        // over — the form is free again, and so is the operator.
        noteJob(forest, report.job)
        setState({})
        setJobId(report.job.id)
        if (mode === 'upload') { setFiles([]); setSkipped([]) }
        return
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

  // The board is busy while a batch runs or others wait their turn: a
  // submit then queues instead of posting (J.9.2). Compose never queues —
  // it is a synchronous review, not a batch — so it just waits.
  const boardBusy = Boolean(board.running) || board.items.length > 0
    || Boolean(board.held)
  const queueing = boardBusy && mode !== 'compose'
  const composeWaits = mode === 'compose' && Boolean(board.running)

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
            { value: 'upload', label: t('ingest.mode_upload'), icon: Upload },
            { value: 'compose', label: t('ingest.mode_compose'), icon: Pencil },
            // Mirroring needs the capability AND a Station configured to read
            // host folders at all (J.8.2). Offering a tab whose every submit
            // is refused teaches the operator nothing about why.
            ...(has(grant, 'admin') && status.host_paths !== false
              ? [{ value: 'adopt', label: t('ingest.mode_adopt'), icon: Files }] : []),
            { value: 'optimize', label: t('ingest.mode_optimize'), icon: Refresh },
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

            {mode === 'optimize' ? (
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
              {/* One batch per forest at a time (J.9) — but a busy board no
                  longer disables the button: the batch waits in the tab's
                  queue instead (J.9.2), and the label says it will wait
                  rather than start. Compose stays out: it is a synchronous
                  review, not a batch, so it simply waits for the board. */}
              <button className="btn btn-primary"
                      disabled={!ready || state.busy || composeWaits}>
                {mode === 'optimize' ? <Refresh size={14} />
                  : mode === 'compose' ? <Pencil size={14} />
                  : queueing ? <Clock size={14} /> : <Upload size={14} />}
                {state.busy || composeWaits ? t('ingest.running')
                  : queueing ? t('ingest.queue')
                  : mode === 'compose' ? t('ingest.review') : t('ingest.start')}
              </button>
            </div>
          </form>
        </Card>

        {/* J.13.3: the other half of keeping a forest current. Sync refreshes
            the content; this refreshes what the content is found by, and
            until v0.41 the console printed "reindex to rebuild it" without
            offering any way to. Its own card because it is not an ingest —
            it plants nothing, joins no queue and takes no destination. */}
        {mode === 'optimize' && has(grant, 'admin') && (
          <>
            <Rebuild forest={forest} />
            <DenseLayer forest={forest} />
          </>
        )}
        {state.busy && <Card><Spinner label={t('ingest.running')} /></Card>}
        {state.error && <Card><ErrorNote error={state.error} /></Card>}
        {state.review && !state.busy && (
          <ReviewDraft key={state.review.stamp} review={state.review}
                       onPublish={publish}
                       onDiscard={() => setState({})} />
        )}
        {jobLost && (
          <Card title={t('ingest.job_title')}>
            {/* A dead job id is said, not dressed up (J.9.1): absence of the
                record is not failure of the work. */}
            <Note tone="warn">{t('ingest.job_lost')}</Note>
            <button className="btn btn-sm mt-3" onClick={() => setJobId('')}>
              {t('common.close')}
            </button>
          </Card>
        )}
        {job && job.state === 'running' && (
          <JobProgress job={job}
                       onCancel={() => api.cancelJob(forest, job.id).catch(() => {})} />
        )}
        {job && job.state === 'cancelled' && (
          <Card title={t('ingest.job_title')}>
            <Note tone="warn">{t('ingest.job_cancelled')}</Note>
          </Card>
        )}
        {job && job.state === 'error' && (
          <Card title={t('ingest.job_title')}>
            <Note tone="danger">{t('ingest.job_failed')}</Note>
            {job.error && <div className="mt-2"><ErrorNote error={job.error} /></div>}
          </Card>
        )}
        {job && job.state !== 'running' && job.report && (
          <Report report={job.report} forest={forest} />
        )}
        {state.report && <Report report={state.report} forest={forest} />}
        {(board.items.length > 0 || board.held) && (
          <QueueCard forest={forest} queue={board} />
        )}
        {!state.busy && !state.error && !state.report && !state.review
          && !jobId && !board.items.length && !board.held && (
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

/** The running batch, from its job record (J.9.1): done over total, the
 *  document in hand, the errors so far — and the one control a batch has,
 *  which stops at the next step boundary. Never modal: freeing the operator
 *  to look elsewhere is the reason jobs exist. */
function JobProgress({ job, onCancel }) {
  const { t } = useI18n()
  const [asked, setAsked] = useState(false)
  const total = Math.max(job.total || 0, 1)
  /* G.10.1: a document is one step, so a one-file batch would sit at 0%
     for as long as the file takes — which reads as a hang, not as work.
     The stage the Gardener reports moves the bar WITHIN the current
     document: `done` documents, plus how far into the one in hand. The
     fraction stays honest because the stage list is closed and ordered,
     and it never reaches the next whole number — only a finished step
     does that. */
  const within = job.stage ? (STAGES.indexOf(job.stage) + 1) / (STAGES.length + 1) : 0
  const pct = Math.min(100, Math.round((((job.done || 0) + within) / total) * 100))
  return (
    <Card title={t('ingest.job_title')} subtitle={t('ingest.job_sub')}
          icon={Upload}
          actions={<Badge tone="accent">{job.mode}</Badge>}>
      <div className="flex items-center justify-between text-[12.5px]">
        <span className="font-medium text-text">
          {t('ingest.job_progress', { done: job.done || 0, total: job.total || 0 })}
        </span>
        <span className="text-text-3">{pct}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2">
        <div className="h-full rounded-full bg-accent transition-[width] duration-500"
             style={{ width: `${pct}%` }} />
      </div>
      {job.current && (
        <p className="mt-2 truncate font-mono text-[11.5px] text-text-3">
          {t('ingest.job_current', { file: job.current })}
          {job.stage && (
            <span className="ml-1.5 text-text-2">
              · {t(`ingest.stage_${job.stage}`)}
            </span>
          )}
        </p>
      )}
      <div className="mt-3 flex items-center justify-between">
        {job.errors > 0
          ? <Badge tone="danger">{t('ingest.job_errors', { n: job.errors })}</Badge>
          : <span />}
        <button type="button" className="btn btn-sm" disabled={asked}
                onClick={() => { setAsked(true); onCancel() }}>
          <X size={13} />
          {asked ? t('ingest.job_cancelling') : t('ingest.job_cancel')}
        </button>
      </div>
    </Card>
  )
}

/** The batches waiting their turn (J.9.2): tab memory, shown where it
 *  waits. Each entry fires as an ordinary batch POST when the board frees,
 *  oldest first; a cancel of the running batch — or a refusal — holds the
 *  line until the operator's hand, because stop means everything. */
function QueueCard({ forest, queue }) {
  const { t } = useI18n()
  return (
    <Card title={t('ingest.queue_title')} subtitle={t('ingest.queue_sub')}
          icon={Clock}
          actions={<Badge tone="accent">{queue.items.length}</Badge>}>
      {queue.held && (
        <Note tone="warn">
          <div>
            {t(queue.held.why === 'cancelled' ? 'ingest.queue_held_cancelled'
                                              : 'ingest.queue_held_refused')}
          </div>
          {queue.held.error && (
            <div className="mt-2"><ErrorNote error={queue.held.error} /></div>
          )}
          {queue.items.length > 0 && (
            <button type="button" className="btn btn-sm mt-2"
                    onClick={() => release(forest)}>
              <Play size={13} /> {t('ingest.queue_release')}
            </button>
          )}
        </Note>
      )}
      {queue.items.length > 0 && (
        <ul className={`space-y-1.5 ${queue.held ? 'mt-3' : ''}`}>
          {queue.items.map((item, i) => (
            <li key={item.id}
                className="flex items-center gap-2 rounded-lg border border-line
                           bg-surface-2 px-2.5 py-1.5">
              <Badge tone={i === 0 ? 'accent' : undefined}>{item.mode}</Badge>
              <span className="min-w-0 flex-1 truncate text-[12.5px] text-text-2">
                {item.mode === 'upload'
                  ? t('ingest.queue_files', { n: item.count || 0 })
                  : item.mode === 'adopt'
                    ? <code className="font-mono text-[12px]">{item.path}</code>
                    : t('ingest.mode_optimize')}
                {item.mode !== 'optimize' && (
                  <span className="text-text-3">
                    {' → '}{item.dest || t('ingest.dest_root')}
                  </span>
                )}
              </span>
              <button type="button" className="btn btn-sm btn-ghost !p-1"
                      title={t('ingest.queue_remove')}
                      onClick={() => unqueue(forest, item.id)}>
                <X size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
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
      {/* Five states, not two. The Curator falls back silently by contract
          (G.4 rule 6), so every failure produces the same nodes a working
          ingest would — which is why the report has to name WHICH failure.
          "Never answered" and "answered and was rejected" look identical on
          disk and have opposite fixes.
          The fifth is not a failure at all (J.8, v0.45): a batch of only
          `unchanged` files asks the model nothing, and reporting that as a
          rejection sends the operator to tune a model that was never asked
          anything. A real rejection always leaves a fallback or a retry
          behind — that is the discriminator, not the zero. */}
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
      ) : !(stats.fallbacks || stats.retries) ? (
        <Note tone="info">
          {t('ingest.model_unneeded', { n: stats.skipped || 0 })}
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

/** The catalog rebuild (J.13.3) — the repair every "the files win" rule in
 *  the spec ends with, finally reachable without a shell.
 *
 *  Deliberately not part of the ingest form: it plants nothing, it takes no
 *  destination, and it never joins the J.9.2 queue, because the host runs it
 *  on the lane rather than as a batch. It is the same errand as Sync told
 *  about a different layer — content vs. what finds the content — which is
 *  why the two share this tab and nothing else. */
function Rebuild({ forest }) {
  const { t } = useI18n()
  const [state, setState] = useState({})

  const run = async () => {
    setState({ busy: true })
    try {
      setState({ done: await api.reindex(forest) })
    } catch (error) {
      setState({ error })
    }
  }

  return (
    <Card title={t('ingest.rebuild_title')} subtitle={t('ingest.rebuild_sub')}
          icon={Refresh}>
      <Note>{t('ingest.rebuild_hint')}</Note>
      {state.error && <div className="mt-3"><ErrorNote error={state.error} /></div>}
      {state.done && (
        <div className="mt-3">
          <Note>
            {t('ingest.rebuild_done', { n: state.done.nodes,
                                        ms: Math.round(state.done.ms) })}
          </Note>
        </div>
      )}
      <div className="mt-4 flex justify-end">
        <button type="button" className="btn btn-primary" disabled={state.busy}
                onClick={run}>
          <Refresh size={14} />
          {state.busy ? t('ingest.rebuild_running') : t('ingest.rebuild_start')}
        </button>
      </div>
    </Card>
  )
}

/** The dense layer's freshness (J.13.4, K.4).
 *
 *  Until v0.42 this happened by itself, inside whichever `locate` arrived
 *  after somebody's ingest — so a question paid to embed two hundred
 *  documents it never asked about, in the primitive with the tightest
 *  budget in the spec. It is a choice now, and the number that says what
 *  the choice costs is printed above the button. */
function DenseLayer({ forest }) {
  const { t } = useI18n()
  const [state, setState] = useState({})
  const status = useAsync(() => api.canopy(forest), [forest])
  const now = state.done || status.data

  // Nothing to say to a forest that never built an index: Models is where
  // that conversation belongs, and repeating it here would send the
  // operator to a second console to do the first thing.
  if (status.busy || !now || !now.vectors) return null

  const refresh = async () => {
    setState({ busy: true })
    try {
      setState({ done: await api.refreshCanopy(forest) })
    } catch (error) {
      setState({ error })
    }
  }

  return (
    <Card title={t('ingest.dense_title')} subtitle={t('ingest.dense_sub')}
          icon={Refresh}>
      <Note>
        {now.stale
          ? t('ingest.dense_behind', { n: now.stale })
          : t('ingest.dense_current', { n: now.vectors })}
      </Note>
      {state.error && <div className="mt-3"><ErrorNote error={state.error} /></div>}
      <div className="mt-4 flex justify-end">
        <button type="button" className="btn"
                disabled={state.busy || !now.stale} onClick={refresh}>
          <Refresh size={14} />
          {state.busy ? t('ingest.dense_running') : t('ingest.dense_start')}
        </button>
      </div>
    </Card>
  )
}
