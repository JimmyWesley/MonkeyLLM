// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useEffect, useRef, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import TurndownService from 'turndown'

import { api , toBase64 } from '../api.js'
import { useRouteState } from '../router.js'
import { useI18n } from '../i18n.jsx'
import {
  WATCH, enqueue, noteJob, release, remove as unqueue, takeFired, useAttend,
  useBoard,
} from '../board.js'
import {
  Badge, Card, ErrorNote, Field, Note, Segmented, Select, Spinner, Tabs,
} from '../design/ui.jsx'
import { Disclosure } from '../design/Disclosure.jsx'
import {
  Clock, Database, File, Ingest as Upload, Pencil, Play, Plus, Refresh, X,
} from '../design/icons.jsx'
import {
  NeedsCapability, NewBranch, branchOf, has, nodeLink, useAsync, useForestTree,
} from './shared.jsx'
import Storage from './storage.jsx'

/* What the Gardener's built-in converters read (G.2). Text goes up as text;
 * .docx/.xls/.xlsx and SQLite databases go up as base64, because their
 * converters read bytes. Anything else is refused HERE, by name, instead of
 * being dropped on the floor: an upload that silently ignores half the
 * selection is indistinguishable from one that failed. */
/* Which entries travel as text (`{name, text}`) rather than as bytes. The
 * shape is J.8's. What the forest ACCEPTS is not decided here at all: it
 * arrives with the ingest status as `formats` (J.8.5, v0.83), computed by
 * the same discovery the next batch will run, so a converter an extension
 * adds is accepted here the moment the forest enables it. The v0.82 console
 * kept a list of its own and greyed out every .pdf while the converter for
 * it was installed, enabled and loaded — nothing had failed. */
const TEXTUAL = /\.(md|markdown|txt|csv|json|tsv|ya?ml)$/i
const MAX_BYTES = 25 * 1024 * 1024
const extensionOf = (path) => {
  const m = /\.[^./\\]+$/.exec(path)
  return m ? m[0].toLowerCase() : ''
}

/* The G.10.1 stages, in the Gardener's order. Named here rather than read
 * off the job, because a bar's fraction needs to know how many phases
 * there are before it has seen them all. */
const STAGES = ['convert', 'curate', 'plant']

/* The Curator's own wording for the one rejection with a specific cure:
 * a thinking model that spent its whole budget before writing anything. */
const EMPTY_REPLY = 'the model returned an empty message'

/* Chunked so a 20 MB document does not blow the argument limit of
 * String.fromCharCode with one spread of the whole array. */
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

/** The source a bucket adopt is started from (J.8.6 rule 2).
 *
 *  The store's own bucket and prefix, plus whatever the operator narrowed it
 *  to. Composed here and shown on the card BEFORE anything starts, because
 *  the moment the source is chosen is the only moment the operator has a
 *  choice about what will be read — and because the two halves of a prefix
 *  (the administrator's, in the store, and this one) are exactly the kind of
 *  thing somebody doubles by hand.
 */
export function bucketUri(store, prefix = '') {
  const parts = [store.prefix || '', prefix || '']
    .map((p) => String(p).replace(/^\/+|\/+$/g, ''))
    .filter(Boolean)
  return `s3://${store.bucket}${parts.length ? `/${parts.join('/')}` : ''}`
}

/* The composer writes prose; the forest stores markdown. One converter,
 * configured once, so the round trip cannot drift. */
const turndown = new TurndownService({
  headingStyle: 'atx', bulletListMarker: '-', codeBlockStyle: 'fenced',
})

/* The content policy a bucket adopts under (G.7 rule 7, v0.84). `cached` is
 * the default for a remote source — the body lives in `_derived/` and out of
 * git — and the card says what that costs a snapshot, because a backup that
 * silently depends on somebody's bucket still existing is the class of
 * surprise Part I's v0.74 round was about. */
const CONTENT = ['cached', 'inline']

/* The canopy build and refresh are J.9 jobs from v0.84 (J.13.4), so they
 * ride the same board, the same pill and the same `?job=` as a batch. The
 * mode is how a RE-DISCOVERED job (a reload, another tab) is recognised;
 * a job this console started arrives in the response and needs no name. */
const CANOPY = 'canopy'

/* The four ways material comes in, and the only values the tab strip holds.
 * `?mode=` still carries six, because two of them named a tab when they were
 * written and an address outlives the layout that produced it (J.5.8):
 * `optimize` and `storage` now name a SECTION of this console instead. */
const SOURCES = ['upload', 'compose', 'adopt', 'bucket']

/* How many accepted formats the dropzone names before it folds the rest.
 * The LIST is the host's (J.8.5) and this console still carries none of its
 * own — what is decided here is only how much of that answer fits on a line
 * a person reads while holding a file. */
const FORMATS_SHOWN = 5

/** Is the source a past adopt recorded a folder this forest really mirrors?
 *
 *  Before v0.61 an upload recorded the staging area as the forest's
 *  `source_root` (J.8.3), so forests ingested by an older Station carry
 *  `…/_derived/uploads` as their mirrored source to this day. That is not a
 *  mirror and never was — an upload is a courier — so a console that offers
 *  to re-read it is offering to re-read a directory the Station empties as
 *  it works, and the amber "outside MONKEYLLM_INGEST_ROOTS" underneath it is
 *  an alarm about a folder nobody chose. A stale record is a quiet fact; the
 *  warning belongs to a REAL source the host can no longer read. */
const mirrorsSource = (recorded) => (
  Boolean(recorded) && !/(^|[/\\])_derived([/\\]|$)/.test(String(recorded)))

/** Is this job's report the ingest report the card below knows how to read?
 *
 *  Two runs on the board are not ingests — the scent pass (J.13.6.1) and the
 *  canopy build — and their reports carry none of its fields. Rendered as
 *  one, a canopy build's report announces that no ingest model is bound,
 *  which is a statement about a model that run never wanted. Each has its
 *  own card in Optimize, which is where its own numbers belong. */
const ingestShaped = (job) => !['recurate', CANOPY].includes(job?.mode)

export default function Ingest({ forest, grant, me, goto }) {
  const { t } = useI18n()
  // Where the console is; what is staged in it is not. Files, a draft and a
  // destination are work in progress, and a reload has already lost them —
  // an address that claimed otherwise would be worse than one that does not
  // mention them.
  // 'optimize' was missing from this list while a tab set it, so clicking
  // the tab wrote `?mode=sync` and the validator handed back the fallback:
  // the console snapped to Upload and the page appeared to close itself.
  // A tab that exists MUST be nameable in the address (J.5.8).
  // 'bucket' and 'storage' joined with J.8.6 and J.19.9 (v0.84). Six tabs
  // that were not peers is what this console was; four are, and the other
  // two are sections — but every value STAYS spelled the way it always was,
  // because addresses naming them exist in the wild and J.5.8's rule is
  // about the address, never about the layout that happened to produce it.
  const [place, setPlace] = useRouteState('mode', 'upload',
                                          { allow: ['upload', 'adopt', 'bucket',
                                                    'compose', 'optimize',
                                                    'storage'] })
  // Which door the form is showing. `optimize` and `storage` scroll to their
  // section and leave the form exactly where it was.
  const mode = SOURCES.includes(place) ? place : 'upload'
  // The running batch, by address (J.9.1): `?job=` is replaced in, so a
  // reload restores the progress view by reading the job — a record, never
  // a call — and Back does not walk the batch's lifetime.
  const [jobId, setJobId] = useRouteState('job', '')
  const [title, setTitle] = useState('')
  const [files, setFiles] = useState([])
  const [dest, setDest] = useState('')
  // J.8 (v0.61): an uploaded document's `origin` is the `source_url` its
  // entry declares, and nothing else — the staging path it arrived by is a
  // fact about plumbing. There was nowhere to state it, so every document
  // saved through this console arrived with no origin, and the gap was
  // reported from outside as the field not working.
  const [sourceUrl, setSourceUrl] = useState('')
  const [path, setPath] = useState('')
  /* Connecting a bucket (J.8.6): the store is CHOSEN from the host's own
     list and never typed — a text field here would resolve against whatever
     ambient credential chain the process happens to have (G.3.1 rule 1),
     which is the one place in this console where being wrong is expensive.
     The rest are the two decisions G.3.1 and G.4.7 make, and no others. */
  const [bucket, setBucket] = useState({ store: '', prefix: '', curate: true,
                                         content: 'cached' })
  const [state, setState] = useState({})
  const [skipped, setSkipped] = useState([])
  const [reading, setReading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [makingBranch, setMakingBranch] = useState(false)
  const picker = useRef(null)
  const folderPicker = useRef(null)
  const staging = useRef(0)
  // Where `?mode=optimize` and `?mode=storage` land now that neither is a
  // tab. The address still names the place; the place is a section of this
  // page instead of a screen of its own.
  const optimizeAt = useRef(null)
  const storageAt = useRef(null)

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

  /* The deployment's object stores (J.19), read ONCE for the two tabs that
     need them: the Storage tab sets this forest's binding out of these
     names, and Connect a bucket sources from them. Listing is open to any
     administrator (J.19.2) — whether this reader may CHANGE one is the
     route's answer, not this console's arithmetic. */
  const stores = useAsync(() => api.stores(), [forest],
                          { skip: !has(grant, 'admin') })
  const storeList = stores.data?.stores || []

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
  // J.8.5: the formats THIS forest converts, from the host. `null` while
  // unknown — and while unknown nothing is refused by type: a list the host
  // has not answered is not a list this console may invent.
  const accepted = Array.isArray(status.formats)
    ? new Set(status.formats.map((f) => f.extension)) : null
  const acceptedList = accepted ? [...accepted].sort().join(', ') : ''
  /* Twenty-three extensions is a paragraph, and it sat inside the drop
     target. The few named on the line are still the HOST's answer, ordered
     by what the host itself says about each: a format some operator added
     here — a command hook, an installed extension — reads before the ones
     every deployment has, so the converter somebody just installed is the
     first thing its own console names. The rest is one click away and
     nothing is invented on this side. */
  const byOrigin = Array.isArray(status.formats)
    ? [...status.formats].sort((a, b) => (
      (a.via === 'builtin' ? 1 : 0) - (b.via === 'builtin' ? 1 : 0)
        || String(a.extension).localeCompare(String(b.extension))))
    : []
  const shownFormats = byOrigin.slice(0, FORMATS_SHOWN)
    .map((f) => f.extension).join(', ')
  const moreFormats = Math.max(0, byOrigin.length - FORMATS_SHOWN)
  const acceptedShort = moreFormats
    ? t('ingest.accepts_more', { list: shownFormats, n: moreFormats })
    : shownFormats
  /* J.8 + J.8.3: what a refresh would re-read, and whether it is a source
     anybody chose. A stale staging path is neither a folder nor an alarm. */
  const mirrors = mirrorsSource(status.source)

  /* An address naming a section brings the section into view. Restoring a
     place is all it does — no call, no write (J.5.8's rule about what a deep
     link may cause).
     It waits for the two answers these sections are drawn from, because a
     section that grows above the one being scrolled to lands the reader
     somewhere else — and once per arrival, so a reload of the status does
     not drag the page back under somebody who has scrolled away. */
  const scrolledFor = useRef(null)
  useEffect(() => {
    const target = place === 'optimize' ? optimizeAt
      : place === 'storage' ? storageAt : null
    if (!target) { scrolledFor.current = null; return undefined }
    if (ingestState.busy || stores.busy || scrolledFor.current === place) {
      return undefined
    }
    scrolledFor.current = place
    const id = requestAnimationFrame(() => {
      target.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
    return () => cancelAnimationFrame(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [place, ingestState.busy, stores.busy])

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
        // Refused HERE, before upload, by what the forest said it takes —
        // so "no converter for this format" is a fact about this forest.
        if (accepted && !accepted.has(extensionOf(path))) {
          refused.push({ name: path, why: 'type' })
          continue
        }
        if (file.size > MAX_BYTES) {
          refused.push({ name: path, why: 'size' })
          continue
        }
        picked.push(TEXTUAL.test(path)
          ? { name: path, text: await file.text(), bytes: file.size }
          : { name: path, b64: toBase64(await file.arrayBuffer()), bytes: file.size })
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

  /** One place where a batch becomes a job (J.9, J.9.1, J.9.2).
   *
   *  Every door's submit goes through it, and so does the refresh — which
   *  left the add card this round and is no less a batch for sitting in
   *  Optimize. Waiting in the tab's queue, following the job in the address
   *  and reloading the binding are one behaviour, not one per door.
   */
  async function startBatch(body, meta) {
    // J.9.2: while the board is busy this is a promise, not a POST. It joins
    // the tab's queue and fires, in order, when the board frees.
    if (boardBusy) {
      enqueue(forest, body, meta)
      return { queued: true }
    }
    const started = await api.ingest(forest, body)
    // The report is the fresher fact about what is bound: a model bound from
    // another tab (or from Models, moments ago) would otherwise leave this
    // card contradicting the report right below it.
    bindings.reload()
    if (started.job) {
      // J.9: the batch was accepted, not finished. The job goes onto the
      // board view first-hand and into the address; the watcher takes over —
      // the form is free again, and so is the operator.
      noteJob(forest, started.job)
      setJobId(started.job.id)
      return { job: started.job }
    }
    return { report: started }
  }

  async function submit(e) {
    e.preventDefault()
    // `bytes` is display-only; the wire contract is {name, text|b64}.
    const url = sourceUrl.trim()
    const payload = files.map(({ bytes, ...rest }) => (
      url ? { ...rest, source_url: url } : rest))
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
    /* A bucket is an `adopt` whose source is an `s3://` URI (J.8.6 rule 5):
       the same mode, the same job, the same queue, the same report. What it
       adds is the two decisions the card asked for — curate now or later,
       and the content policy the bodies land under. */
    const chosen = storeList.find((s) => s.name === bucket.store)
    const source = chosen ? bucketUri(chosen, bucket.prefix) : ''
    const body = mode === 'upload'
      ? { mode, files: payload, dest: dest || undefined }
      : mode === 'adopt' ? { mode, path, dest: dest || undefined }
      : mode === 'bucket'
        ? { mode: 'adopt', source, dest: dest || undefined,
            curate: bucket.curate, content: bucket.content }
      : { ...composition, stage: true }

    if (mode === 'compose') {
      // Composing is a conversation, not a batch: it never queues and never
      // becomes a job, so it does not go through `startBatch`.
      setState({ busy: true })
      try {
        const report = await api.ingest(forest, body)
        bindings.reload()
        // `stamp` remounts the review card. Keying it on the draft id would
        // not: staging the same title twice returns the same id, so an
        // edited text would come back under the previous review's summary,
        // tags and unticked boxes — the reviewer would approve a passport
        // they never saw.
        staging.current += 1
        setState({ busy: false,
                   review: { ...composition, ...report, stamp: staging.current } })
      } catch (error) { setState({ busy: false, error }) }
      return  // nothing has been planted yet; the composer keeps its text
    }

    const clear = () => {
      if (mode === 'upload') { setFiles([]); setSkipped([]); setSourceUrl('') }
    }
    setState({ busy: true })
    try {
      const out = await startBatch(body, {
        mode,
        count: mode === 'upload' ? files.length : undefined,
        dest: dest || undefined,
        path: mode === 'adopt' ? path : mode === 'bucket' ? source : undefined,
      })
      clear()
      setState(out.report ? { busy: false, report: out.report } : {})
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
    // A store, and that is the whole requirement: the prefix may be empty
    // (the store's own is the source then) and the destination defaults to
    // the root, exactly as every other door's does.
    : mode === 'bucket' ? Boolean(bucket.store)
    : Boolean(title.trim() && composed)

  /* J.8.6 rule 1: with no store there is no bucket to read from, so the card
     says which console configures one and the controls that would refuse —
     the destination, the button — are not drawn at all. It reads the list
     and not the asking, so a store that arrives makes them APPEAR: a control
     that shows up while the answer loads and then vanishes is the flicker
     the whole round is against. */
  const bucketBlocked = mode === 'bucket' && storeList.length === 0

  /* The tab strip holds the four ways material comes in, and nothing else.
     Six tabs were never peers: two of them were errands you run on a forest
     that is already full, and sitting beside the doors they made the strip
     read as a list of six equal choices. The short label is what fits one
     row on a phone; the full sentence is the tab's own title and, for the
     tab that is open, the card's subtitle — so the sentence is never lost
     and never occupies a second line of everybody's screen. */
  const door = (value, short, full) => ({
    value, label: <span title={full}>{t(short)}</span>,
  })
  const doors = [
    door('upload', 'ingest.tab_upload', t('ingest.mode_upload')),
    door('compose', 'ingest.tab_compose', t('ingest.mode_compose')),
    // Mirroring needs the capability AND a Station configured to read host
    // folders at all (J.8.2). Offering a tab whose every submit is refused
    // teaches the operator nothing about why.
    ...(has(grant, 'admin') && status.host_paths !== false
      ? [door('adopt', 'ingest.tab_adopt', t('ingest.mode_adopt'))] : []),
    // J.8.6 + J.19.9: this reads the deployment's store list, which is an
    // administrator's listing (J.19.2) — a tab whose every request is
    // refused teaches nothing about why.
    ...(has(grant, 'admin')
      ? [door('bucket', 'ingest.tab_bucket', t('ingest.mode_bucket'))] : []),
  ]

  return (
    /* One column, bounded. The right-hand column held one sentence about the
       summary model and took 380px of every screen to say it; that sentence
       is a line under the button now, and the card it left behind has the
       width — capped, because a form whose fields run the whole of a 1440px
       screen is a form nobody can read across. */
    <div className="mx-auto w-full max-w-3xl space-y-8">
      <div className="min-w-0 space-y-4">
        <Card title={t('ingest.title')} subtitle={t(`ingest.mode_${mode}`)}
              icon={Upload}>
          <Tabs value={mode} onChange={(m) => { setPlace(m); setState({}) }}
                options={doors} />

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
                  <p className="mt-1 text-[12px] text-text-3">
                    {accepted ? t('ingest.drop_hint', { list: acceptedShort })
                              : t('ingest.drop_hint_unknown')}
                  </p>
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
                  <input ref={picker} type="file" multiple className="hidden"
                         accept={accepted ? [...accepted].join(',') : undefined}
                         onChange={(e) => take(e.target.files)} />
                  <input ref={folderPicker} type="file" multiple webkitdirectory=""
                         directory="" className="hidden"
                         onChange={(e) => take(e.target.files)} />
                </div>

                {/* The whole list, one click away. It is still the host's
                    answer (J.8.5) — what is decided here is where it is
                    read, not what is in it. */}
                {moreFormats > 0 && (
                  <Disclosure summary={t('ingest.formats_count',
                                         { n: byOrigin.length })}>
                    <span className="font-mono text-[11.5px]">{acceptedList}</span>
                  </Disclosure>
                )}

                {reading && <Spinner label={t('ingest.reading')} />}

                {skipped.length > 0 && (
                  <Note tone="warn">
                    <div>{t('ingest.skipped', { n: skipped.length })}</div>
                    {accepted && skipped.some((s) => s.why === 'type') && (
                      <div className="mt-1 text-[11.5px]">
                        {t('ingest.accepts', { list: acceptedList })}
                      </div>
                    )}
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
                    <div className="mt-3">
                      <Field label={t('ingest.source_url')} value={sourceUrl}
                             placeholder="https://example.com/page"
                             hint={t('ingest.source_url_hint')}
                             onChange={(e) => setSourceUrl(e.target.value)} />
                    </div>
                  </div>
                )}
              </>
            )}

            {mode === 'compose' && (
              <>
                <Disclosure summary={t('ingest.compose_lede')}>
                  {t('ingest.compose_hint')}
                </Disclosure>
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

            {mode === 'bucket' && (
              <ConnectBucket value={bucket} onChange={setBucket}
                             stores={storeList} busy={stores.busy}
                             error={stores.error} onStorage={() => setPlace('storage')} />
            )}

            {/* With no store there is nothing to put anywhere, so the
                destination and the button are not drawn (J.8.6 rule 1): a
                form whose every control refuses is not an explanation. */}
            {!bucketBlocked && (
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

            {!bucketBlocked && (
              <div>
                <div className="flex justify-end">
                  {/* One batch per forest at a time (J.9) — but a busy board
                      no longer disables the button: the batch waits in the
                      tab's queue instead (J.9.2), and the label says it will
                      wait rather than start. Compose stays out: it is a
                      synchronous review, not a batch, so it simply waits for
                      the board.
                      A button that cannot run is not a dimmed primary: the
                      accent is the product saying "this is the act", and an
                      act nobody can perform yet has no business claiming it.
                      It earns the accent the moment it can run. */}
                  <button className={ready && !state.busy && !composeWaits
                                       ? 'btn btn-primary' : 'btn'}
                          disabled={!ready || state.busy || composeWaits}>
                    {mode === 'compose' ? <Pencil size={14} />
                      : queueing ? <Clock size={14} /> : <Upload size={14} />}
                    {state.busy || composeWaits ? t('ingest.running')
                      : queueing ? t('ingest.queue')
                      : mode === 'compose' ? t('ingest.review') : t('ingest.start')}
                  </button>
                </div>
                {/* What will write the summaries, in one line where the act
                    is (J.5). It used to be a card in a column of its own —
                    380px of screen for one sentence, and the sentence was
                    about something the operator changes somewhere else. */}
                <SummaryModel bound={bound} goto={goto} />
              </div>
            )}
          </form>
        </Card>

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
        {job && job.state !== 'running' && job.report && ingestShaped(job) && (
          <Report report={job.report} forest={forest} />
        )}
        {state.report && <Report report={state.report} forest={forest} />}
        {(board.items.length > 0 || board.held) && (
          <QueueCard forest={forest} queue={board} />
        )}
        {/* Nothing to report is not a report. The card that filled a screen
            with a large glyph and "nothing ingested yet" was the console's
            answer to its own quietest state, and it said less than the empty
            space it replaced. */}
      </div>

      {/* The errands you run on a forest that is already full. A section,
          because they were never peers of the four doors — and `?mode=
          optimize` still names this place (J.5.8), it just scrolls here
          instead of replacing the page.
          The refresh is an `ingest` act and the repairs are `admin` ones,
          which is what the tab was and what the section stays: a bare `sync`
          names no host path, so J.8 never asked for `admin` and this console
          must not either. The section is drawn when it holds something. */}
      {(has(grant, 'admin') || mirrors) && (
        <section ref={optimizeAt} className="space-y-3 scroll-mt-4">
          <h2 className="label">{t('ingest.mode_optimize')}</h2>
          {has(grant, 'admin') && (
            <>
              {/* J.13.3: the other half of keeping a forest current. The
                  refresh below keeps the content current; this keeps what
                  finds the content current. */}
              <Rebuild forest={forest} />
              <Rederive forest={forest} />
              {/* J.13.6.1: the model-backed one, below the two free repairs
                  it must not be confused with. The running job is handed to
                  it so the button cannot be pressed twice and the report
                  lands where the operator started it — the progress bar and
                  the full report are the page's, on the J.9 board. */}
              <Rescent forest={forest} bound={bound}
                       job={job && job.mode === 'recurate' ? job : null}
                       onJob={(started) => {
                         noteJob(forest, started)
                         setJobId(started.id)
                       }} />
              <DenseLayer forest={forest}
                          job={job && job.mode === CANOPY ? job : null}
                          onJob={(started) => {
                            noteJob(forest, started)
                            setJobId(started.id)
                          }} />
            </>
          )}
          {/* J.8: a refresh reads a source the request never names, so the
              control never appears without it beside it. A forest that
              mirrors nothing has no control here at all and ONE quiet line
              saying so — a stale `_derived/` path recorded by a pre-v0.61
              Station used to open this section with an amber alarm about a
              staging directory nobody chose (J.8.3). */}
          {!ingestState.busy && (mirrors ? (
            <SourceRefresh source={status.source} blocked={!status.can_sync}
                           queueing={boardBusy}
                           onRun={() => startBatch({ mode: 'sync' },
                                                   { mode: 'optimize' })} />
          ) : (
            <p className="px-1 text-[12px] leading-relaxed text-text-3">
              {t('ingest.sync_none')}
            </p>
          ))}
          {has(grant, 'admin') && <Staging forest={forest} />}
        </section>
      )}

      {/* J.19.9: where the originals go, in the console whose question is
          how documents get in. Outside the ingest form on purpose — its
          panels are forms of their own, and a form inside a form is not a
          form. */}
      {has(grant, 'admin') && (
        <section ref={storageAt} className="space-y-3 scroll-mt-4">
          <h2 className="label">{t('ingest.mode_storage')}</h2>
          <Storage forest={forest} stores={stores} status={status} me={me}
                   onBound={ingestState.reload} />
        </section>
      )}

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

/** What will write the summaries, said where the summaries are asked for.
 *
 *  This was a card in a 380px column of its own, and the column existed for
 *  this one sentence. A line under the button is the whole of what it had to
 *  say, and it leaves the form the width.
 *
 *  It still ASKS rather than asserting: the card used to state "no ingest
 *  model is bound" unconditionally, which read as fact and was wrong the
 *  moment one was. A principal without `admin` cannot see bindings at all,
 *  so for them this says nothing — the ingest report afterwards carries
 *  `curated` and is authoritative for everyone.
 */
function SummaryModel({ bound, goto }) {
  const { t } = useI18n()
  // `undefined` is still asking and `false` is may-not-see. Neither is a
  // fact, and a line that appears and then corrects itself is worse than a
  // line that waits.
  if (bound === undefined || bound === false) return null
  return (
    <p className="mt-2 flex flex-wrap items-center justify-end gap-x-1.5
                  text-[11.5px] text-text-3">
      <span>{bound ? t('ingest.curated_by', { model: bound.model })
                   : t('ingest.no_model')}</span>
      <span aria-hidden="true">·</span>
      <button type="button" className="text-accent transition hover:underline"
              onClick={() => goto('models')}>
        {t('nav.models')}
      </button>
    </p>
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
                  // A bucket waits under the source it will read, like the
                  // folder beside it: `s3://bucket/prefix` is the one thing
                  // that tells two queued batches apart.
                  : item.mode === 'adopt' || item.mode === 'bucket'
                    ? <code className="font-mono text-[12px]">{item.path}</code>
                    // The refresh, which is queued under the place it is
                    // started from and named by what it does.
                    : t('ingest.sync_title')}
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

/** Connecting a bucket (spec J.8.6).
 *
 *  The fourth door, and the one for the operator whose corpus is already
 *  somewhere — which is most operators, and the audience J.8 was written
 *  for: a browser and no shell. Its fields are exactly the decisions G.3.1
 *  and G.4.7 make and no others.
 *
 *  The store is CHOSEN, never typed. A text field for an endpoint or a
 *  bucket would resolve against whatever ambient credential chain the
 *  process happens to have, and this console carries no list of stores of
 *  its own for the same reason it carries no list of formats (J.8.5's rule,
 *  applied to the thing where being wrong is expensive). With nothing
 *  configured the card says which console configures one, rather than
 *  offering a field whose every value is refused.
 *
 *  Both choices state their cost where they are made: curating now is one
 *  model call per document before the corpus is searchable, and `cached`
 *  bodies mean a snapshot carries the map and not the text.
 */
function ConnectBucket({ value, onChange, stores, busy, error, onStorage }) {
  const { t } = useI18n()
  const chosen = stores.find((s) => s.name === value.store) || null
  const set = (patch) => onChange({ ...value, ...patch })

  if (error) return <ErrorNote error={error} />
  if (busy && !stores.length) return <Spinner label={t('common.loading')} />
  if (!stores.length) {
    return (
      <div className="space-y-3">
        <Note tone="warn">{t('ingest.bucket_no_store')}</Note>
        <button type="button" className="btn btn-sm" onClick={onStorage}>
          <Database size={13} /> {t('ingest.bucket_configure')}
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Select label={t('ingest.bucket_store')} value={value.store} required
                hint={t('ingest.bucket_store_hint')}
                onChange={(e) => set({ store: e.target.value })}>
          <option value="" disabled>—</option>
          {stores.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
        </Select>
        <Field label={t('ingest.bucket_prefix')} value={value.prefix}
               placeholder="handbook/2024/" hint={t('ingest.bucket_prefix_hint')}
               onChange={(e) => set({ prefix: e.target.value })} />
      </div>

      {/* What will be read, resolved, before anything starts (J.8.6 rule 2).
          The object count is the batch's own `total` — it is counted by the
          listing the job runs, and this console does not run one of its
          own. */}
      {chosen && (
        <Note>
          {t('ingest.bucket_reads')}{' '}
          <code className="font-mono">{bucketUri(chosen, value.prefix)}</code>
          <div className="mt-1 text-[11.5px]">{t('ingest.bucket_count')}</div>
        </Note>
      )}

      <div>
        <div className="label">{t('ingest.bucket_curate')}</div>
        <Segmented value={value.curate ? 'now' : 'later'}
                   onChange={(v) => set({ curate: v === 'now' })}
                   options={[{ value: 'now', label: t('ingest.bucket_curate_now') },
                             { value: 'later', label: t('ingest.bucket_curate_later') }]} />
        <p className="mt-1.5 text-[11.5px] text-text-3">
          {t(value.curate ? 'ingest.bucket_curate_now_hint'
                          : 'ingest.bucket_curate_later_hint')}
        </p>
      </div>

      <Select label={t('ingest.bucket_content')} value={value.content}
              hint={t(`ingest.bucket_content_${value.content}_hint`)}
              onChange={(e) => set({ content: e.target.value })}>
        {CONTENT.map((c) => (
          <option key={c} value={c}>{t(`ingest.bucket_content_${c}`)}</option>
        ))}
      </Select>
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

      {/* Formats, not files (J.8 v0.84, J.8.6 rule 6). `unsupported` is a
          list of relative paths and three thousand of them is not a report
          anybody reads; `{extension: count}` is the sentence an operator
          can act on, and it sits ABOVE the paths, which stay exactly as
          they were. Rendered from the report's own map — a console that
          counted the paths itself would disagree with it the moment the
          list is bounded. */}
      {report.unsupported_formats
        && Object.keys(report.unsupported_formats).length > 0 && (
        <div className="mt-4">
          <div className="label">{t('ingest.unsupported_formats')}</div>
          <ul className="flex flex-wrap gap-1.5">
            {Object.entries(report.unsupported_formats)
              .sort((a, b) => b[1] - a[1])
              .map(([ext, n]) => (
                <li key={ext}>
                  <span className="badge font-mono">{ext} · {n}</span>
                </li>
              ))}
          </ul>
        </div>
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
    /* A lighter header than the add card's: no icon, no subtitle. The one
       line every repair owes its reader is the Disclosure's summary, and the
       paragraphs that used to sit above the first field are behind it. */
    <Card title={t('ingest.rebuild_title')}>
      <Disclosure summary={t('ingest.rebuild_sub')}>
        {t('ingest.rebuild_hint')}
      </Disclosure>
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
        <button type="button" className={state.busy ? 'btn' : 'btn btn-primary'}
                disabled={state.busy} onClick={run}>
          <Refresh size={14} />
          {state.busy ? t('ingest.rebuild_running') : t('ingest.rebuild_start')}
        </button>
      </div>
    </Card>
  )
}

/** The refresh (J.8), which left the add card this round.
 *
 *  It was the fifth tab and it never belonged beside the four doors: every
 *  other tab takes material from somewhere and puts it in, and this one
 *  re-reads what a past adopt already recorded. It is still the same batch —
 *  same queue, same job, same address (J.8.6 rule 5's point, made about the
 *  oldest mode) — so it is started through the console's one `startBatch`.
 *
 *  What it must show is the source, because a refresh names a directory the
 *  request never does: a button whose reach is invisible is not consent.
 *  The card is drawn only when there IS one, so the amber below is about a
 *  real folder this Station may no longer read, and never about a staging
 *  path an older Station wrote down (J.8.3).
 */
function SourceRefresh({ source, blocked, queueing, onRun }) {
  const { t } = useI18n()
  const [state, setState] = useState({})

  const run = async () => {
    setState({ busy: true })
    try { await onRun(); setState({}) } catch (error) { setState({ error }) }
  }

  return (
    <Card title={t('ingest.sync_title')}>
      <Disclosure summary={<>
        {t('ingest.sync_source')}{' '}
        <code className="break-all font-mono">{source}</code>
      </>}>
        {t('ingest.sync_hint')}
      </Disclosure>
      {blocked && (
        <div className="mt-3"><Note tone="warn">{t('ingest.sync_blocked')}</Note></div>
      )}
      {state.error && <div className="mt-3"><ErrorNote error={state.error} /></div>}
      <div className="mt-4 flex justify-end">
        <button type="button"
                className={blocked || state.busy ? 'btn' : 'btn btn-primary'}
                disabled={blocked || state.busy} onClick={run}>
          {queueing ? <Clock size={14} /> : <Refresh size={14} />}
          {state.busy ? t('ingest.running')
            : queueing ? t('ingest.queue') : t('ingest.start')}
        </button>
      </div>
    </Card>
  )
}

/** What ingest would derive today, applied to what it derived before
 *  (J.13.6).
 *
 *  The third repair in this tab, and the one whose absence was measured
 *  from outside: alias derivation improved in v0.59, every input to it
 *  already sits in the passports, and the only way to apply it was `sync`
 *  — which needs the recorded host root and admin over it. A forest of
 *  1,877 nodes therefore had the feature in the code and not in the
 *  corpus. Union semantics, so running it twice changes nothing and a
 *  hand-written alias is never displaced. */
function Rederive({ forest }) {
  const { t } = useI18n()
  const [state, setState] = useState({})

  const run = async () => {
    setState({ busy: true })
    try {
      setState({ done: await api.recurate(forest) })
    } catch (error) {
      setState({ error })
    }
  }

  return (
    <Card title={t('ingest.rederive_title')}>
      <Disclosure summary={t('ingest.rederive_sub')}>
        {t('ingest.rederive_hint')}
      </Disclosure>
      {state.error && <div className="mt-3"><ErrorNote error={state.error} /></div>}
      {state.done && (
        <div className="mt-3">
          <Note>
            {t('ingest.rederive_done', { n: state.done.changed,
                                         scanned: state.done.scanned })}
          </Note>
        </div>
      )}
      <div className="mt-4 flex justify-end">
        <button type="button" className={state.busy ? 'btn' : 'btn btn-primary'}
                disabled={state.busy} onClick={run}>
          <Refresh size={14} />
          {state.busy ? t('ingest.rederive_running') : t('ingest.rederive_start')}
        </button>
      </div>
    </Card>
  )
}

/** The scent every node carries, written again by the model (J.13.6.1).
 *
 *  The fourth repair in this tab and the odd one out, which is why the card
 *  has to say so in its first two lines. Its neighbours are free and
 *  mechanical: `reindex` rebuilds what finds the content, `Re-derive` reads
 *  passports and does arithmetic on them. This one spends ONE MODEL CALL
 *  PER NODE, and what it rewrites is what a node SAYS about itself — the
 *  summary an agent navigates by. Both facts are the operator's to weigh
 *  before pressing anything, so the count in scope is shown as the stated
 *  cost (J.13.6.1 rule 5) and the button never runs without it.
 *
 *  The job itself is the console's ordinary machinery: it goes on the J.9
 *  board like an ingest batch, so the progress bar and the report below
 *  belong to the page and not to this card. */
function Rescent({ forest, bound, job, onJob }) {
  const { t } = useI18n()
  const [state, setState] = useState({})
  /* J.13.6.1 rules 8 and 9 (v0.84). `created` is the host's own default and
     is left unsent while it is chosen, so a console that has never touched
     these controls asks for exactly what v0.83 asked for. `limit` empty is
     the whole scope. */
  const [order, setOrder] = useState('created')
  const [limit, setLimit] = useState('')
  const running = job && job.state === 'running'
  const report = job && job.state !== 'running' ? job.report : null

  const run = async () => {
    setState({ busy: true })
    try {
      const started = await api.recurate(forest, ['scent'], {
        order: order === 'created' ? undefined : order,
        limit: limit === '' ? undefined : Number(limit),
      })
      setState({ nodes: started.nodes, remaining: started.remaining })
      if (started.job) onJob(started.job)
    } catch (error) {
      setState({ error })
    }
  }

  return (
    <Card title={t('ingest.rescent_title')}>
      {/* What separates it from its neighbours, first and in its own tone —
          a repair that costs money must not read like the free ones stacked
          above it. The line is visible and the two paragraphs behind it are
          not: the sentence that decides whether to press this is the one
          about the bill, and it is the summary. */}
      <Disclosure tone="warn" summary={t('ingest.rescent_lede')}>
        <p>{t('ingest.rescent_sub')}</p>
        <p>{t('ingest.rescent_cost')}</p>
        <p>{t('ingest.rescent_hint')}</p>
      </Disclosure>
      {/* A real condition, and the one that decides whether anything can be
          asked at all — so it stays a Note. */}
      {bound === null && (
        <div className="mt-3"><Note tone="warn">{t('ingest.rescent_unbound')}</Note></div>
      )}

      {/* Which nodes, and how many of them. Oldest first is what the pass
          exists for — the thinnest scent, carried longest — and hottest
          first improves what agents are actually reading before what nobody
          has opened. A bound run pays for the cap and not for the scope,
          and running it again re-visits the same nodes: the pass keeps no
          memory of what it curated, and that is said here rather than
          discovered on the second bill. */}
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Select label={t('ingest.rescent_order')} value={order}
                hint={t(`ingest.rescent_order_${order}_hint`)}
                onChange={(e) => setOrder(e.target.value)}>
          <option value="created">{t('ingest.rescent_order_created')}</option>
          <option value="heat">{t('ingest.rescent_order_heat')}</option>
        </Select>
        <Field label={t('ingest.rescent_limit')} type="number" min="1"
               value={limit} placeholder={t('ingest.rescent_limit_all')}
               hint={t('ingest.rescent_limit_hint')}
               onChange={(e) => setLimit(e.target.value)} />
      </div>

      {state.error && <div className="mt-3"><ErrorNote error={state.error} /></div>}
      {state.nodes !== undefined && (
        <div className="mt-3">
          {/* The bill, as the host stated it: with a cap the number is the
              cap and never the scope (rule 9), so this prints what came
              back and computes nothing of its own. */}
          <Note tone="info">
            {t('ingest.rescent_scope', { n: state.nodes })}
            {state.remaining ? ` ${t('ingest.rescent_remaining',
                                      { n: state.remaining })}` : ''}
          </Note>
        </div>
      )}
      {report && (
        <div className="mt-3">
          <Note>
            {t('ingest.rescent_done', {
              n: report.changed || 0,
              unchanged: (report.unchanged || []).length,
            })}
            {report.fallbacks > 0
              && ` ${t('ingest.rescent_fallbacks', { n: report.fallbacks })}`}
            {/* Rule 9: `remaining` beside the bill is what makes a second
                run a decision rather than a guess. */}
            {report.remaining
              ? ` ${t('ingest.rescent_remaining', { n: report.remaining })}` : ''}
          </Note>
        </div>
      )}
      <div className="mt-4 flex justify-end">
        <button type="button"
                className={state.busy || running || bound === null
                             ? 'btn' : 'btn btn-primary'}
                disabled={state.busy || running || bound === null}
                onClick={run}>
          <Pencil size={14} />
          {running || state.busy
            ? t('ingest.rescent_running') : t('ingest.rescent_start')}
        </button>
      </div>
    </Card>
  )
}

/** What is in the staging area that is not a document (J.13.7).
 *
 *  Since v0.61 an uploaded file is removed as it becomes a node, so what
 *  shows here is a conversion that failed, a batch that was cancelled, or
 *  — on a forest ingested by an older Station — a document whose node was
 *  later pruned. All three are legitimate; what was not is that none of
 *  them could be seen, and invisible bytes in a staging area are how a
 *  pruned node once came back. The card hides itself when there is
 *  nothing: an empty area is the normal state and does not need a panel.
 */
function Staging({ forest }) {
  const { t } = useI18n()
  const [state, setState] = useState({})
  const found = useAsync(() => api.staging(forest), [forest])
  const now = state.done || found.data

  if (found.busy || !now || !now.unrecorded) return null

  const clear = async () => {
    setState({ busy: true })
    try {
      setState({ done: await api.clearStaging(forest) })
    } catch (error) {
      setState({ error, done: now })
    }
  }

  return (
    <Card title={t('ingest.staging_title')}>
      {/* A real condition — bytes that are there — so it stays a Note. */}
      <Note tone="warn">
        {t('ingest.staging_found', { n: now.unrecorded,
                                     kb: Math.max(1, Math.round(now.bytes / 1024)) })}
      </Note>
      <ul className="mt-3 max-h-32 space-y-0.5 overflow-y-auto">
        {(now.names || []).map((name) => (
          <li key={name} className="font-mono text-[11.5px] text-text-3">{name}</li>
        ))}
      </ul>
      <div className="mt-3">
        <Disclosure summary={t('ingest.staging_sub')}>
          {t('ingest.staging_hint')}
        </Disclosure>
      </div>
      {state.error && <div className="mt-3"><ErrorNote error={state.error} /></div>}
      <div className="mt-4 flex justify-end">
        <button type="button" className={state.busy ? 'btn' : 'btn btn-primary'}
                disabled={state.busy} onClick={clear}>
          <X size={14} />
          {state.busy ? t('ingest.staging_running') : t('ingest.staging_start')}
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
function DenseLayer({ forest, job, onJob }) {
  const { t } = useI18n()
  const [state, setState] = useState({})
  // The status is re-read when the run settles: what `stale` says is exactly
  // what the run changed.
  const status = useAsync(() => api.canopy(forest), [forest, job?.state])
  const now = state.done || status.data
  const running = job && job.state === 'running'

  // Nothing to say to a forest that never built an index: Models is where
  // that conversation belongs, and repeating it here would send the
  // operator to a second console to do the first thing.
  if (status.busy || !now || !now.vectors) return null

  const refresh = async () => {
    setState({ busy: true })
    try {
      const started = await api.refreshCanopy(forest)
      // J.13.4 (v0.84): a refresh is a J.9 job now — same board, same
      // progress, same cancel, same one-batch-per-forest lock. An older
      // Station answers the status synchronously, and that answer is still
      // read rather than being called a failure.
      if (started?.job) { setState({}); onJob(started.job) }
      else setState({ done: started })
    } catch (error) {
      setState({ error })
    }
  }

  return (
    <Card title={t('ingest.dense_title')}>
      {/* The state in one line — which is the whole answer when the layer is
          current — and what being behind actually costs behind it. */}
      <Disclosure summary={now.stale
                             ? t('ingest.dense_behind_sum', { n: now.stale })
                             : t('ingest.dense_current', { n: now.vectors })}>
        <p>{t('ingest.dense_sub')}</p>
        {now.stale ? <p>{t('ingest.dense_behind', { n: now.stale })}</p> : null}
      </Disclosure>
      {/* A cancelled run changed nothing and is not resumable (J.13.4): the
          index is the one the forest already had, and the next press starts
          over and pays again. Said here, because what was spent is spent. */}
      {job && job.state === 'cancelled' && (
        <div className="mt-3"><Note tone="warn">{t('ingest.dense_cancelled')}</Note></div>
      )}
      {state.error && <div className="mt-3"><ErrorNote error={state.error} /></div>}
      <div className="mt-4 flex justify-end">
        <button type="button"
                className={state.busy || running || !now.stale
                             ? 'btn' : 'btn btn-primary'}
                disabled={state.busy || running || !now.stale} onClick={refresh}>
          <Refresh size={14} />
          {state.busy || running ? t('ingest.dense_running')
                                 : t('ingest.dense_start')}
        </button>
      </div>
    </Card>
  )
}
