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

/* Text formats only on this path: the upload body is JSON, so a .docx or an
 * .xlsx would have to be base64 to survive it. Those keep the folder-mirror
 * route, where the Gardener reads the bytes directly. */
const ACCEPT = '.md,.markdown,.txt,.csv,.json,.tsv,.yaml,.yml'
const TEXTUAL = /\.(md|markdown|txt|csv|json|tsv|ya?ml)$/i

export default function Ingest({ forest, grant, goto }) {
  const { t } = useI18n()
  const [mode, setMode] = useState('upload')
  const [files, setFiles] = useState([])
  const [dest, setDest] = useState('')
  const [path, setPath] = useState('')
  const [state, setState] = useState({})
  const [dragging, setDragging] = useState(false)
  const picker = useRef(null)

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

  async function take(list) {
    const picked = []
    for (const f of Array.from(list)) {
      if (!TEXTUAL.test(f.name)) continue
      picked.push({ name: f.webkitRelativePath || f.name, text: await f.text() })
    }
    setFiles((prev) => [...prev, ...picked])
  }

  async function submit(e) {
    e.preventDefault()
    setState({ busy: true })
    try {
      const body = mode === 'upload' ? { mode, files, dest: dest || undefined }
        : mode === 'adopt' ? { mode, path, dest: dest || undefined }
        : { mode: 'sync' }
      const report = await api.ingest(forest, body)
      setState({ busy: false, report })
      if (mode === 'upload') setFiles([])
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
                  onDrop={(e) => { e.preventDefault(); setDragging(false); take(e.dataTransfer.files) }}
                  onClick={() => picker.current?.click()}
                  className={`grid cursor-pointer place-items-center rounded-xl border-2
                    border-dashed px-4 py-10 text-center transition
                    ${dragging ? 'border-accent bg-accent-soft' : 'border-line hover:border-line-strong'}`}
                >
                  <span className="mb-2 grid h-11 w-11 place-items-center rounded-xl
                                   bg-surface-2 text-text-3"><Upload size={20} /></span>
                  <p className="text-[13.5px] font-medium text-text">{t('ingest.drop')}</p>
                  <p className="mt-1 text-[12px] text-text-3">{t('ingest.drop_hint')}</p>
                  <input ref={picker} type="file" multiple accept={ACCEPT} className="hidden"
                         onChange={(e) => take(e.target.files)} />
                </div>

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
                            {(f.text.length / 1024).toFixed(1)} kB
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

  return (
    <Card title={t('ingest.report')}
          actions={<Badge tone={report.curated ? 'accent' : 'default'}>
            {report.mode}
          </Badge>}>
      <Note tone={report.curated ? 'info' : 'warn'}>
        {report.curated ? t('ingest.curated') : t('ingest.uncurated')}
      </Note>

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
