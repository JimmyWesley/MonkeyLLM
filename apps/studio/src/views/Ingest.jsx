import { useRef, useState } from 'react'
import { api } from '../api.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, Empty, ErrorNote, Field, Note, Select, Spinner, Tabs,
} from '../design/ui.jsx'
import { File, Ingest as Upload, Refresh, X } from '../design/icons.jsx'
import {
  NeedsCapability, branchOf, has, useAsync, useForestTree,
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

export default function Ingest({ forest, grant, goto }) {
  const { t } = useI18n()
  const [mode, setMode] = useState('upload')
  const [files, setFiles] = useState([])
  const [dest, setDest] = useState('')
  const [path, setPath] = useState('')
  const [state, setState] = useState({})
  const [skipped, setSkipped] = useState([])
  const [reading, setReading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const picker = useRef(null)
  const folderPicker = useRef(null)

  const tree = useForestTree(forest, grant, api.call)
  // undefined = still asking, null = nothing bound, object = the binding.
  // Only an admin may read bindings; for anyone else it stays `false`, and
  // the card says nothing rather than guessing.
  const bindings = useAsync(() => api.bindings(forest).then((b) => b.bindings),
                            [forest], { skip: !has(grant, 'admin') })
  const bound = !has(grant, 'admin') ? false
    : bindings.busy ? undefined
    : (bindings.data || []).find((b) => b.role === 'ingest') || null

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
      const body = mode === 'upload'
        ? { mode, files: payload, dest: dest || undefined }
        : mode === 'adopt' ? { mode, path, dest: dest || undefined }
        : { mode: 'sync' }
      const report = await api.ingest(forest, body)
      setState({ busy: false, report })
      // The report is the fresher fact about what is bound: a model bound
      // from another tab (or from Models, moments ago) would otherwise leave
      // this card contradicting the report right below it.
      bindings.reload()
      if (mode === 'upload') { setFiles([]); setSkipped([]) }
    } catch (error) { setState({ busy: false, error }) }
  }

  const ready = mode === 'upload' ? files.length > 0
    : mode === 'adopt' ? Boolean(path) : true

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <div className="min-w-0 space-y-4">
        <Card title={t('ingest.title')} subtitle={t('ingest.sub')} icon={Upload}>
          <Tabs value={mode} onChange={(m) => { setMode(m); setState({}) }} options={[
            { value: 'upload', label: t('ingest.mode_upload') },
            ...(has(grant, 'admin') ? [{ value: 'adopt', label: t('ingest.mode_adopt') }] : []),
            { value: 'sync', label: t('ingest.mode_sync') },
          ]} />

          <form onSubmit={submit} className="mt-4 space-y-4">
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

            {mode === 'adopt' && (
              <Field label={t('ingest.path')} value={path} required
                     placeholder="/data/handbook" hint={t('ingest.path_hint')}
                     onChange={(e) => setPath(e.target.value)} />
            )}

            {mode === 'sync' ? (
              <Note>{t('ingest.sync_hint')}</Note>
            ) : (
              <Select label={t('ingest.dest')} value={dest} hint={t('ingest.dest_hint')}
                      onChange={(e) => setDest(e.target.value)}>
                <option value="">{t('ingest.dest_root')}</option>
                {(tree.data?.branches || []).map((b) => {
                  const name = branchOf(b.id)
                  return name ? <option key={b.id} value={name}>{name}</option> : null
                })}
              </Select>
            )}

            <div className="flex justify-end">
              <button className="btn btn-primary" disabled={!ready || state.busy}>
                {mode === 'sync' ? <Refresh size={14} /> : <Upload size={14} />}
                {state.busy ? t('ingest.running') : t('ingest.start')}
              </button>
            </div>
          </form>
        </Card>

        {state.busy && <Card><Spinner label={t('ingest.running')} /></Card>}
        {state.error && <Card><ErrorNote error={state.error} /></Card>}
        {state.report && <Report report={state.report} goto={goto} />}
        {!state.busy && !state.error && !state.report && (
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
    </div>
  )
}

function Report({ report, goto }) {
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
                      <button className="badge font-mono hover:border-accent/40 hover:text-accent"
                              onClick={() => goto('explore', String(item))}>
                        {String(item)}
                      </button>
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
