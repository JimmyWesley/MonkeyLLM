// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api.js'
import {
  MAX_RUNS, clearRuns, exportRuns, listRuns, loadRun, saveRun,
} from '../history.js'
import { useI18n } from '../i18n.jsx'
import {
  Badge, Card, CopyButton, Empty, ErrorNote, Modal, Note, Segmented, Spinner,
  Toggle,
} from '../design/ui.jsx'
import { Markdown } from '../design/markdown.jsx'
import {
  Ask as AskIcon, Clock, Collapse, Download, Expand, Eye, Graph as GraphIcon,
  Printer, Sparkle, Trash,
} from '../design/icons.jsx'
import { PayloadImage } from './files.jsx'
import { evidenceFromHops, mergeEvidence } from '../trailmap.js'
import AnswerTrail from './trail.jsx'
import {
  Metric, NeedsCapability, Row, TraceSteps, fmtMs, has, nodeLink, useAsync,
} from './shared.jsx'

/* J.10.8: the reply size is the person's own preference — like language and
 * theme (J.5.3), it lives in the browser and never in the address. 0 is
 * "auto": the forest binding's own max_tokens rules, and nothing is sent. */
const ASK_PREFS_KEY = 'monkeyllm.ask.prefs'
const REPLY_STEPS = [0, 200, 400, 600, 900, 1200, 1800, 2600, 4000]

function loadPrefs() {
  try {
    return { reply: 0, graph: true,
             ...JSON.parse(localStorage.getItem(ASK_PREFS_KEY) || '{}') }
  } catch {
    return { reply: 0, graph: true }
  }
}

function savePrefs(patch) {
  try {
    localStorage.setItem(ASK_PREFS_KEY, JSON.stringify({ ...loadPrefs(), ...patch }))
  } catch { /* private mode: the preference just does not persist */ }
}

/* J.10.12: how long the console waits for the answer's own progress channel
 * before falling back to J.5.15's second retrieval. Long enough that a
 * served channel always wins (the bundle is published in milliseconds),
 * short enough that an older Station's map is not visibly late. */
const CHANNEL_GRACE_MS = 900

/* A rendezvous, not a name (J.10.12 rule 5): opaque, this browser's own, and
 * never reused. `randomUUID` needs a secure context, which a Station on plain
 * http over a LAN is not — so there is a fallback, and it only has to be
 * unique among one person's own in-flight questions. */
const newRunId = () => (
  globalThis.crypto?.randomUUID
    ? crypto.randomUUID()
    : `r-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`)

const replyStepIndex = (value) => REPLY_STEPS.reduce(
  (best, v, i) => (Math.abs(v - value) < Math.abs(REPLY_STEPS[best] - value) ? i : best), 0)

/** The console that needs no explanation, which is why it is the landing one.
 *
 * Retrieval is scoped and deterministic and happens first; only then does the
 * forest's bound model read what was found (J.10.3). The evidence list is not
 * decoration — it is the set of nodes that were actually read. */
export default function Ask({ forest, grant, me, goto }) {
  const { t, lang } = useI18n()
  // ?q= PREFILLS the question — it never asks it. The address restores a
  // page, not a call (J.5.8): a shared link or the Clipper's ask box
  // lands here with the words ready, and the person presses ask. Read
  // once at mount; typing never writes it back.
  const [question, setQuestion] = useState(
    () => new URLSearchParams(window.location.search).get('q') || '')
  const [k, setK] = useState(3)
  // J.10.8: how long an answer this person likes. Restored from the saved
  // preference at mount; dragging the slider is what writes it back.
  const [reply, setReply] = useState(() => loadPrefs().reply || 0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [hybrid, setHybrid] = useState(false)
  // J.10.5. Off by default because it is not free: one model call per hop
  // against one for the sweep.
  const [hops, setHops] = useState(false)
  // J.10.7. On by default because it is free: a repeat of a question on an
  // unchanged forest is served from the store. Off sends `cache: false`,
  // which buys a fresh run and replaces the stored one — the with-and-
  // without comparison the runs history exists to read side by side.
  const [cache, setCache] = useState(true)
  const [wide, setWide] = useState(false)
  // J.5.4: the map of what the answer did. A preference like the reply
  // size — it lives in the browser and never in the address (J.5.8) —
  // and it is its OWN switch, deliberately not folded into `hops`: the
  // walk is what costs seconds, the drawing costs nothing, and one
  // control over both would teach an operator that the picture is slow.
  // On by default (J.5.15 rule 10): a demonstration should show the
  // product's own subject without a preparation step.
  const [showGraph, setShowGraph] = useState(() => loadPrefs().graph !== false)
  // What the answer's own progress channel has delivered so far (J.10.12):
  // the sweep's bundle at ~19 ms, and a walk's hops as each completes. The
  // `preview` is the J.5.15 fallback for a Station that serves no channel.
  const [preview, setPreview] = useState(null)
  const [live, setLive] = useState(null)
  // The runs kept in this browser (J.5.9), and which of them — if any — is
  // what the answer panel is currently showing.
  const [history, setHistory] = useState(false)
  const [restored, setRestored] = useState(null)
  // The progress subscription of the ask currently in flight (J.10.12).
  // One at a time and never longer than its own call: a channel left open
  // keeps delivering ITS run's hops into whatever `live` now belongs to, and
  // one question's path drawn as another's is the invention J.5.15 rule 3
  // forbids — the panel would be honest about material from the wrong hunt.
  const channel = useRef(null)
  const principal = me?.principal || ''

  const admin = has(grant, 'admin')
  // Only an admin can read index health, and only an admin has any business
  // switching the entry ranker. Non-admins never see the control, which is
  // right: it is a measurement instrument, not a preference.
  const canopy = useAsync(() => api.canopy(forest), [forest], { skip: !admin })
  const dense = canopy.data?.state === 'active' && canopy.data?.enabled !== false

  /** Close a progress subscription (J.10.12), and forget it if it is still
   *  the one this console is watching. The guard is for the ask that already
   *  replaced this one: it owns the ref now, and an older settle arriving
   *  late must not tear down the channel of the question now on screen. */
  function closeChannel(open) {
    open?.abort()
    if (channel.current === open) channel.current = null
  }

  // A subscription must not outlive the console that opened it.
  useEffect(() => () => channel.current?.abort(), [])

  /* What the path panel draws, in the order the sources can be trusted
     (J.5.15 rule 2): the finished answer outranks everything; while a walk
     runs, its hops as they arrive; and a sweep's bundle, which reaches the
     console before either — and on a walk is never fired at all, so `preview`
     stays null and the panel holds nothing until the walk says otherwise.

     A walk's close is the UNION of its two records, because neither contains
     the other: `read` carries the text that was handed over and names no
     `locate`, `scan` or `move`, while the hop records name exactly those and
     are the only place they are written down. Taking `read` alone would drop
     every dot the live walk lit and collapse the entry stage to zero at the
     moment the answer landed — two pictures of one hunt, which is the thing
     the live channel exists to end.

     Memoised because the identity is what the panel re-marks on: recomputing
     it per keystroke would re-derive the marks and the trail of an answer
     that has not changed since it landed. */
  const drawn = useMemo(() => {
    if (!result) return live?.length ? evidenceFromHops(live) : preview?.results
    if (result.harvest?.results) return result.harvest.results
    return mergeEvidence(result.read, evidenceFromHops(result.hops))
  }, [result, live, preview])

  if (!has(grant, 'read')) {
    return <NeedsCapability message={t('access.needs_admin')} hint={t('cap.read')} />
  }

  async function ask(text) {
    const q = (text ?? question).trim()
    if (!q) return
    setQuestion(q)
    setBusy(true); setError(null); setResult(null); setRestored(null)
    setPreview(null); setLive(null)
    // J.10.12: watch this call's own progress. The bundle arrives from the
    // answer itself at ~19 ms and each hop as it completes, so on a Station
    // that serves the channel the console runs NO second retrieval — the
    // map is drawn from the very object the reply will be written from.
    const runId = showGraph ? newRunId() : null
    // Held so the answer's own settle can cancel it: past that moment there
    // is nothing left for a second retrieval to be early FOR, and a stored
    // answer (J.10.7) would otherwise pay for a read nobody ever draws.
    let fallback = null
    // The previous ask's channel, if one is somehow still open, belongs to a
    // question this panel is no longer showing. Closed before this one opens,
    // so its remaining hops cannot land in the new run's `live`.
    closeChannel(channel.current)
    const watching = runId ? new AbortController() : null
    channel.current = watching
    if (runId) {
      let arrived = false
      api.events(forest, runId, (kind, data) => {
        if (kind === 'retrieval') { arrived = true; setPreview(data) }
        if (kind === 'hop') {
          arrived = true
          setLive((held) => [...(held || []), data])
        }
      }, watching.signal)
      // J.5.15 rule 2 (v0.67): the preview is a SWEEP's, and only a sweep's.
      // A walk runs no `harvest` at all — its entry is a bare `locate` and
      // every retrieval after it is a call the model authored (J.10.5) — so
      // a harvest fired beside a walk is not the same sweep, it is a sweep
      // that never happened, and painting its results as the answer's
      // retrieval is exactly what rule 3 forbids. A walk's panel starts
      // empty (a fact, not a placeholder) and fills from the hops
      // themselves: J.10.12's events while the call is open, and the
      // response's own `read`/`evidence` at the close.
      if (!hops) {
        // The J.5.15 fallback, held back for the channel rather than raced
        // with it: an older Station, or a proxy that ate the stream, still
        // draws — and a current one pays for no extra read at all.
        fallback = setTimeout(() => {
          if (arrived) return
          api.call(forest, 'harvest',
                   { query: q, k, ...(hybrid ? { hybrid: true } : {}) })
            .then((data) => { if (!arrived) setPreview(data) })
            .catch(() => {})
        }, CHANNEL_GRACE_MS)
      }
    }
    // Kept beside the answer because they are half of what a comparison
    // needs: the same question at `k=2` and at `k=6` are two runs, and a
    // record that dropped them would show two answers and no reason.
    const params = {
      k, ...(runId ? { run: runId } : {}),
      ...(reply ? { reply_tokens: reply } : {}),
      ...(hybrid ? { hybrid: true } : {}), ...(hops ? { hops: true } : {}),
      ...(cache ? {} : { cache: false }),
    }
    const t0 = performance.now()
    try {
      const { data, timing } = await api.timedCall(forest, 'answer', { question: q, ...params })
      const run = { ...data, timing, ms: Math.round(performance.now() - t0) }
      setResult(run)
      // Fire and forget, and deliberately outside the try's failure path: a
      // browser that cannot keep a run (private window, refused quota) has
      // not failed the ask, and J.5.9 says it must not be told it has.
      saveRun({ principal, forest, question: q, params, result: run }).catch(() => {})
    } catch (err) { setError(err) } finally {
      // Whatever the answer did, it has landed: the fallback's whole job was
      // to stand in for a channel that never spoke, and a call that is over
      // has no gap left to fill. A stored answer returns in milliseconds,
      // so without this the store's own economy paid for a retrieval on
      // every hit (J.5.15 rule 1: the panel costs the forest nothing).
      if (fallback) clearTimeout(fallback)
      closeChannel(watching)
      setBusy(false)
    }
  }

  /** Reading a run back reads a record: no call leaves the browser (J.5.9).
   *
   *  The parameters go back exactly as they were sent, so "ask again" asks
   *  the same question rather than a similar one — a comparison between a
   *  saved `k=6` run and a fresh `k=3` one is not a comparison. */
  async function restore(id) {
    const run = await loadRun(id)
    if (!run) return
    // A record is now what the panel shows, so a live hunt's hops belong to
    // no question on this screen.
    closeChannel(channel.current)
    setHistory(false); setError(null); setBusy(false)
    setQuestion(run.question)
    setK(run.params?.k ?? 3)
    // The run's own size, without touching the saved preference: restoring
    // a record must not rewrite how this person likes fresh answers.
    setReply(run.params?.reply_tokens ?? 0)
    setHybrid(!!run.params?.hybrid)
    setHops(!!run.params?.hops)
    setCache(run.params?.cache !== false)
    setPreview(null); setLive(null)
    setResult(run.result)
    setRestored({ ts: run.ts, model: run.result?.model })
  }

  const noModel = error?.code === 'E_SCHEMA' && /no model is bound/i.test(error.message)

  // The request as a command (the Playground's pattern): the parameters as
  // the form would send them now, and never the key — `$MONKEYLLM_KEY` is a
  // placeholder because a credential pasted into a chat or a script is a
  // credential published (J.10's write-only rule, one surface out).
  const curl = `curl -X POST ${window.location.origin}/v1/forests/${forest}/answer \\
  -H "Authorization: Bearer $MONKEYLLM_KEY" \\
  -H "Content-Type: application/json" \\
  -d '${JSON.stringify({
    question, k,
    ...(reply ? { reply_tokens: reply } : {}),
    ...(hybrid ? { hybrid: true } : {}), ...(hops ? { hops: true } : {}),
    ...(cache ? {} : { cache: false }),
  })}'`

  return (
    <div className="space-y-4">
      {/* A clock and not a menu: the history of J.5.9 is opened, never
          linked to, so it is a control on the console rather than a place
          the address bar can name. */}
      <Card title={t('ask.title')} subtitle={t('ask.sub')} icon={AskIcon}
            actions={<>
              <button type="button" className="btn btn-sm btn-ghost !px-2"
                      title={t('ask.history_title')} aria-label={t('ask.history_title')}
                      onClick={() => setHistory(true)}>
                <Clock size={15} />
              </button>
            </>}>
        <form onSubmit={(e) => { e.preventDefault(); ask() }} className="space-y-3">
          <textarea
            className="field min-h-[92px] resize-y text-[14px] leading-relaxed"
            rows={3} autoFocus value={question}
            placeholder={t('ask.placeholder')}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              // The shortcut is the button, so it is the button's state too:
              // the send control is disabled while an answer is in flight,
              // and a keyboard path that was not would let one question's
              // POST land as another's answer.
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                if (!busy) ask()
              }
            }}
          />
          {/* Settings left, action right — the same order every form on this
              console uses, so the button is always in the corner the eye
              already went to. */}
          <div className="flex flex-wrap items-center justify-end gap-3">
            <div className="mr-auto flex flex-wrap items-center gap-x-4 gap-y-2">
              <div className="flex items-center gap-2">
                <span className="text-[11.5px] text-text-3">{t('ask.depth')}</span>
                <Segmented value={k} onChange={setK} options={[
                  { value: 2, label: '2' }, { value: 3, label: '3' }, { value: 6, label: '6' },
                ]} />
              </div>
              {/* J.10.8: dragged per person, remembered per person. "Auto"
                  sends nothing — the forest binding's own size rules. */}
              <label className="flex items-center gap-2" title={t('ask.reply_hint')}>
                <span className="text-[11.5px] text-text-3">{t('ask.reply_len')}</span>
                <input type="range" className="graph-range w-24"
                       min={0} max={REPLY_STEPS.length - 1} step={1}
                       value={replyStepIndex(reply)}
                       aria-label={t('ask.reply_len')}
                       onChange={(e) => {
                         const v = REPLY_STEPS[Number(e.target.value)] || 0
                         setReply(v)
                         savePrefs({ reply: v })
                       }} />
                <span className="whitespace-nowrap font-mono text-[11px] tabular-nums
                                 text-text-3">
                  {reply
                    ? t('ask.reply_words', { n: Math.round(reply * 0.75) })
                    : t('ask.reply_auto')}
                </span>
              </label>
              {/* J.5.15 rule 10, kept by moving rather than by staying: the
                  drawing is still NOT a parameter of the question — it is
                  not in the flags list below, which is "what the question is
                  asked with" — and it is still never the walk's switch
                  (rule 1) and still a browser preference (rule 8). What
                  changed is that an icon alone in the header was a control
                  nobody found. This row sits above the answer and is not
                  pushed off screen by it, which was the reason the header
                  was chosen in the first place. */}
              <Toggle compact icon={GraphIcon} checked={showGraph}
                      label={t('ask.graph')} hint={t('ask.graph_hint')}
                      onChange={(v) => { setShowGraph(v); savePrefs({ graph: v }) }} />
            </div>
            {/* A keyboard shortcut is not advice on a phone. */}
            <span className="hidden text-[11.5px] text-text-3 sm:inline">
              {t('ask.hint_send')}
            </span>
            <button className="btn btn-primary" disabled={busy || !question.trim()}>
              <Sparkle size={15} />
              {busy ? t('ask.thinking') : t('ask.send')}
            </button>
          </div>

          {/* What the question is asked WITH. The drawing is not one of
              these — it is a way of reading the answer, so it lives on the
              header (J.5.15 rule 10) and never in this list. */}
          <div className="space-y-3 border-t border-line pt-3">
            <Toggle checked={hops} onChange={setHops}
                    label={t('ask.hops')} hint={t('ask.hops_hint')} />
            {dense && (
              <Toggle checked={hybrid} onChange={setHybrid}
                      label={t('ask.hybrid')} hint={t('ask.hybrid_hint')} />
            )}
            <Toggle checked={cache} onChange={setCache}
                    label={t('ask.cache')} hint={t('ask.cache_hint')} />
          </div>
        </form>

        {!result && !busy && (
          <div className="mt-5 border-t border-line pt-4">
            <div className="label">{t('ask.examples')}</div>
            <div className="flex flex-wrap gap-2">
              {['ask.ex1', 'ask.ex2', 'ask.ex3'].map((key) => (
                <button key={key} type="button" onClick={() => ask(t(key))}
                        className="badge hover:border-accent/40 hover:bg-accent-soft
                                   hover:text-accent">
                  {t(key)}
                </button>
              ))}
            </div>
          </div>
        )}
      </Card>

      {busy && <Working hops={hops} />}

      {error && (
        <Card>
          <ErrorNote error={error} />
          {noModel && (
            <div className="mt-3">
              <Note tone="warn">
                {t('ask.no_model')}{' '}
                {has(grant, 'admin') && (
                  <button className="font-medium text-accent underline-offset-2 hover:underline"
                          onClick={() => goto('models')}>{t('overview.bind_model')}</button>
                )}
              </Note>
            </div>
          )}
        </Card>
      )}

      {/* A saved answer that looked live would be the whole feature working
          backwards: the model may have been rebound since, and telling the
          two apart is the reason the run was kept (J.5.9). */}
      {restored && result && (
        <Card>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <Badge tone="warn"><Clock size={12} /> {t('ask.restored')}</Badge>
            <span className="text-[12px] text-text-2">
              {when(restored.ts, lang)}
              {restored.model && <> · <span className="font-mono">{restored.model}</span></>}
            </span>
            <span className="w-full text-[12px] leading-relaxed text-text-3 sm:w-auto">
              {t('ask.restored_hint')}
            </span>
            <button type="button" className="btn btn-sm btn-primary sm:ml-auto"
                    disabled={busy} onClick={() => ask()}>
              <Sparkle size={14} /> {t('ask.run_again')}
            </button>
          </div>
        </Card>
      )}

      {result && (
        <div className={`grid gap-4 ${wide ? '' : 'lg:grid-cols-[1fr_320px]'}`}>
          <Card className="print-target" title={t('ask.answer')} icon={Sparkle}
                actions={<>
                  <Badge tone="accent">{result.model}</Badge>
                  {/* A hit is a record served, and it says so (J.10.7): the
                      badge names the store, and its tooltip the time the
                      answer was actually bought. */}
                  {result.cached && (
                    <span title={result.cached_at ? when(result.cached_at, lang) : undefined}>
                      <Badge tone="warn">{t('ask.cached')}</Badge>
                    </span>
                  )}
                  <Badge>{t('common.elapsed', { ms: result.ms })}</Badge>
                  {/* Reading is the point; the instruments can wait. Widening
                      moves the panel below instead of hiding it. */}
                  <button className="btn btn-sm btn-ghost !px-1.5 hidden lg:inline-flex"
                          onClick={() => setWide((w) => !w)}
                          title={t(wide ? 'ask.collapse' : 'ask.expand')}
                          aria-label={t(wide ? 'ask.collapse' : 'ask.expand')}>
                    {wide ? <Collapse size={15} /> : <Expand size={15} />}
                  </button>
                </>}>
            {/* An answer is markdown — tables, lists, and sometimes a mermaid
                diagram. Rendering it as preformatted text showed the source
                of a document instead of the document. `media` opts in the
                J.10.9 references: `![…](media:<id>)` becomes the image
                itself, fetched through J.14 with this viewer's credential. */}
            <Markdown media={{ forest }}>{result.answer}</Markdown>

            <div className="mt-6 border-t border-line pt-4">
              <div className="label">{t('common.evidence')}</div>
              {result.evidence?.length ? (
                <>
                  <p className="mb-2.5 text-[12px] text-text-3">{t('ask.evidence_hint')}</p>
                  {/* An id is not a label: `projects/leads-2d` could be
                      anything. The scent travels with every result already,
                      so saying what is behind each link costs nothing. */}
                  <ul className="space-y-1.5">
                    {result.evidence.map((id) => {
                      const src = (result.sources || []).find((s) => s.id === id)
                      return (
                        <li key={id}>
                          <a className="block w-full rounded-lg border border-line bg-surface
                                        px-2.5 py-2 text-left transition
                                        hover:border-accent/40"
                             {...nodeLink(forest, id)}>
                            <span className="flex flex-wrap items-baseline gap-x-2">
                              <span className="font-mono text-[12px] text-accent">{id}</span>
                              {src?.type && (
                                <span className="text-[10.5px] uppercase tracking-[0.07em]
                                                 text-text-3">{src.type}</span>
                              )}
                            </span>
                            {(src?.title || src?.summary) && (
                              <span className="mt-0.5 block text-[12px] leading-relaxed text-text-2">
                                {src.title && <b className="font-medium text-text">{src.title}. </b>}
                                {src.summary}
                              </span>
                            )}
                          </a>
                          {/* J.10.9: evidence of type media shows its image
                              beside its scent — the description exists
                              because of the image (J.14). Outside the <a>:
                              PayloadImage is a link of its own. */}
                          {src?.type === 'media' && (
                            <div className="mt-1.5 px-2.5">
                              <PayloadImage forest={forest} id={id}
                                            type="media" title={src?.title} />
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                </>
              ) : <Empty>{t('ask.nothing')}</Empty>}
            </div>

            {/* Taking the answer with you. `.md` is the answer as written;
                the PDF goes through the browser's own print pipeline, which
                already knows how to lay out text and rasterise the SVG of a
                diagram — a bundled PDF writer would do both worse. */}
            <div className="no-print mt-5 flex flex-wrap justify-end gap-2
                            border-t border-line pt-3">
              <CopyButton value={curl} label={t('ask.copy_curl')} />
              <button className="btn btn-sm"
                      onClick={() => downloadMarkdown(result, question, forest)}>
                <Download size={14} /> {t('ask.download_md')}
              </button>
              <button className="btn btn-sm" onClick={() => window.print()}>
                <Printer size={14} /> {t('ask.download_pdf')}
              </button>
            </div>

            {result.hops?.length > 0 && <Path hops={result.hops} />}
            {/* One panel either way: the sweep hands the material back in a
                bundle, the forager assembles it hop by hop (J.10.5). */}
            {(result.harvest?.results?.length || result.read?.length) > 0 && (
              <Material results={result.harvest?.results || result.read}
                        sources={result.sources || []} />
            )}
          </Card>

          <Explain trace={result.trace} wall={result.ms} hybrid={hybrid}
                   cost={result.cost} timing={result.timing} />
        </div>
      )}

      {/* J.10.4 drawn: the same material the answer lists, on the forest it
          came out of — and UNDER the answer (J.5.15 rule 10), because the
          answer is what was asked for and this is where it came from. The
          final result outranks the preview the moment it lands: on a sweep
          they are the same sweep, but only one of them is what was actually
          answered from. */}
      {showGraph && (
        /* What it draws is decided above (`drawn`), where the three sources
           and their order can be read in one place. */
        <AnswerTrail forest={forest}
                     evidence={drawn}
                     cited={Array.isArray(result?.hops) ? result.evidence : undefined}
                     hops={result?.hops}
                     trace={result?.trace}
                     live={!result && !!live?.length}
                     busy={busy} />
      )}

      <History open={history} onClose={() => setHistory(false)}
               principal={principal} forest={forest} onPick={restore} />

      <Note>{t('ask.limits')}</Note>
      {/* No Gauntlet switch here on purpose: `answer` composes `harvest`,
          which is entry search — locate + sniff, no `look`, no `move`, no
          `scan`. Part K conditions the *frontier*, and this console never
          hops. The switch above is the other one: whether the vector layer
          joins entry search, which is the thing that does affect an answer
          — and the thing measurement says makes it worse. */}
      <Note>{t('gauntlet.not_here')}</Note>
    </div>
  )
}

/** The answer as a file. Markdown because that is what it already is —
 *  converting it to anything else here would be a lossy round trip.
 *
 *  `media:` references are rewritten to the absolute J.14 route (J.10.9):
 *  the exported file names a fetchable address — credential still required —
 *  rather than a scheme only this console understands. */
function downloadMarkdown(result, question, forest) {
  const answer = String(result.answer || '').replace(
    /\]\(media:([^()\s]+)\)/g,
    (_, id) => `](${window.location.origin}/v1/forests/${encodeURIComponent(forest)}`
      + `/payload/${id.split('/').map(encodeURIComponent).join('/')})`)
  const lines = [
    `# ${question}`, '',
    answer, '',
    '---', '',
    `- Forest: \`${forest}\``,
    `- Model: \`${result.model}\``,
    ...(result.hops?.length
      ? [`- Hops: ${result.hops.map((h) => `${h.tool}${h.id ? `(${h.id})` : ''}`).join(' → ')}`]
      : []),
    ...(result.evidence?.length ? [`- Evidence: ${result.evidence.join(', ')}`] : []),
    ...(result.cost?.priced ? [`- Cost: $${result.cost.usd}`] : []),
    `- ${new Date().toISOString()}`,
  ]
  const url = URL.createObjectURL(
    new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `${(question || 'answer').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60) || 'answer'}.md`
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

/** When a run was made, in the reader's own locale.
 *
 *  Absolute, never "3 hours ago": these are compared with each other and
 *  with things that happened at a particular time — an ingest, a model
 *  rebound — and a relative clock turns every one of those comparisons into
 *  arithmetic the reader has to do. */
function when(ts, lang) {
  const d = new Date(ts)
  return `${d.toLocaleDateString(lang)} · ${d.toLocaleTimeString(lang, {
    hour: '2-digit', minute: '2-digit',
  })}`
}

const DAY = 86400000

function dayLabel(ts, lang, t) {
  const now = new Date()
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  if (ts >= midnight) return t('ask.history_today')
  if (ts >= midnight - DAY) return t('ask.history_yesterday')
  return new Date(ts).toLocaleDateString(lang, {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

const fmtBytes = (n) => (n >= 1024 * 1024
  ? `${(n / 1024 / 1024).toFixed(1)} MB`
  : `${Math.max(1, Math.round(n / 1024))} KB`)

/** The runs already made on this forest (J.5.9).
 *
 *  Grouped by day, and deliberately not by "session": a browser cannot
 *  observe a session — a reload, a second tab and a laptop reopened the next
 *  morning are indistinguishable to it — so grouping by one would be
 *  grouping by something the console invented. The day is real.
 *
 *  Nothing in this panel calls the Station. The list, the restore and the
 *  export all read the browser's own store, which is the whole point: these
 *  answers exist here and nowhere else.
 */
function History({ open, onClose, principal, forest, onPick }) {
  const { t, lang } = useI18n()
  const [state, setState] = useState(null)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    if (!open) return undefined
    setConfirming(false)
    setState(null)
    let live = true
    listRuns(principal, forest).then((s) => { if (live) setState(s) })
    return () => { live = false }
  }, [open, principal, forest])

  const runs = state?.runs || []
  const groups = []
  for (const run of runs) {
    const label = dayLabel(run.ts, lang, t)
    const last = groups[groups.length - 1]
    if (last && last.label === label) last.runs.push(run)
    else groups.push({ label, runs: [run] })
  }

  async function discard() {
    await clearRuns(principal, forest)
    setState({ ok: true, runs: [], bytes: 0 })
    setConfirming(false)
  }

  /** The one thing that ever moves a run off this machine, and it moves
   *  because somebody asked (J.5.9). Whole records — the answers with their
   *  material — because a history exported without them is a list of
   *  questions. */
  async function download() {
    const data = await exportRuns(principal, forest)
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `${forest}-runs.json`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  }

  return (
    <Modal open={open} onClose={onClose} wide
           title={t('ask.history_title')} subtitle={t('ask.history_local')}
           footer={runs.length > 0 && (
             <>
               {/* The bound, said out loud. A store that dropped its far end
                   in silence would let a partial history read as a complete
                   one (J.5.9). */}
               <span className="mr-auto text-left text-[11.5px] leading-relaxed text-text-3">
                 {t('ask.history_holding', {
                   n: runs.length, size: fmtBytes(state?.bytes || 0),
                 })}
                 <br />
                 {t('ask.history_bound', { n: MAX_RUNS })}
               </span>
               <button type="button" className="btn btn-sm" onClick={download}>
                 <Download size={14} /> {t('ask.history_export')}
               </button>
               <button type="button" className={`btn btn-sm ${confirming ? 'btn-danger' : ''}`}
                       onClick={() => (confirming ? discard() : setConfirming(true))}>
                 <Trash size={14} />
                 {confirming ? t('ask.history_clear_confirm') : t('ask.history_clear')}
               </button>
             </>
           )}>
      {state === null ? <Spinner label={t('common.loading')} />
        : !state.ok ? <Note tone="warn">{t('ask.history_unavailable')}</Note>
        : !runs.length ? (
          <Empty icon={Clock} title={t('ask.history_none')}>{t('ask.history_empty')}</Empty>
        ) : (
          <div className="max-h-[60vh] space-y-4 overflow-y-auto">
            {groups.map((group) => (
              <div key={group.label}>
                <div className="label">{group.label}</div>
                <ul className="space-y-1.5">
                  {group.runs.map((run) => (
                    <li key={run.id}>
                      <button type="button" onClick={() => onPick(run.id)}
                              className="w-full rounded-lg border border-line bg-surface
                                         px-3 py-2 text-left transition
                                         hover:border-accent/40">
                        <span className="block truncate text-[13px] font-medium text-text">
                          {run.question}
                        </span>
                        <span className="mt-1 flex flex-wrap items-baseline gap-x-2
                                         gap-y-1 text-[11px] text-text-3">
                          <span className="tabular-nums">
                            {new Date(run.ts).toLocaleTimeString(lang, {
                              hour: '2-digit', minute: '2-digit',
                            })}
                          </span>
                          {/* What was sent, not what it produced: two runs of
                              one question differ by these. */}
                          <span className="font-mono">
                            {t('ask.history_depth', { k: run.params?.k ?? '—' })}
                          </span>
                          {run.params?.hops && <Badge>{t('ask.history_hops')}</Badge>}
                          {run.params?.hybrid && <Badge>{t('ask.history_hybrid')}</Badge>}
                          {run.model && <span className="font-mono">{run.model}</span>}
                          {/* No stopwatch on the row: the client's round trip
                              is not the cost of the call (J.10.6), and the
                              three clocks that are live in the panel the run
                              restores into. */}
                          <span className="ml-auto tabular-nums">
                            {t('common.evidence')}: {run.evidence}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
    </Modal>
  )
}

/** While the answer is being made.
 *
 *  Deliberately NOT a fake narration of hops. The request is one POST and
 *  the host answers once, so a console that claimed "now it is reading X"
 *  would be inventing it — and an invented progress bar is worse than an
 *  honest clock, because it is indistinguishable from a real one. What is
 *  true and useful: which mode is running, what that mode does, and how
 *  long it has been running. Streaming the real hops needs the host to push
 *  events (SSE), which is a different contract.
 */
function Working({ hops }) {
  const { t } = useI18n()
  const [ms, setMs] = useState(0)
  useEffect(() => {
    const t0 = performance.now()
    const id = setInterval(() => setMs(performance.now() - t0), 100)
    return () => clearInterval(id)
  }, [])

  const stages = hops
    ? ['ask.stage_entry', 'ask.stage_walk', 'ask.stage_write']
    : ['ask.stage_entry', 'ask.stage_read', 'ask.stage_write']

  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <Spinner label={t(hops ? 'ask.working_hops' : 'ask.working_sweep')} />
        <span className="font-mono text-[12px] tabular-nums text-text-3">
          {(ms / 1000).toFixed(1)}s
        </span>
      </div>
      <ul className="mt-3 space-y-1 text-[12px] text-text-3">
        {stages.map((s) => <li key={s}>· {t(s)}</li>)}
      </ul>
    </Card>
  )
}

/** The material the model was actually given.
 *
 *  The recurring question this answers is "did it read the summary or the
 *  text?" — and the honest reply is: the summary decides *which* node, the
 *  body is what gets read. `matches` are literal snippets with their section
 *  and line; `content` is the body when it fits the per-node budget, or the
 *  matched sections when it does not, or the outline when even those are too
 *  big. Showing it turns a claim into something checkable.
 */
function Material({ results, sources = [] }) {
  const { t } = useI18n()
  const scent = (id) => results.find((r) => r.id === id)?.summary
    || sources.find((s) => s.id === id)?.summary
  return (
    /* Out of the PDF: this is verbatim source, pages of it, and an export is
       the answer with its provenance — the evidence list and the walk say
       where it came from without reprinting the forest. */
    <div className="no-print mt-6 border-t border-line pt-4">
      <div className="label">{t('ask.material')}</div>
      <p className="mb-3 text-[12px] text-text-3">{t('ask.material_hint')}</p>
      <div className="space-y-2">
        {results.map((r) => {
          /* A row that opens on nothing must not offer to open. The sweep
             can hand back a node it found by curated metadata alone whose
             body it could not read (G.7): no snippet, no section, nothing
             behind the eye — and an affordance over an empty box is a
             promise this panel exists not to make. */
          const readable = (r.matches?.length || 0) + (r.content?.length || 0) > 0
          const head = (
            <>
              <span className="font-mono text-[12px] text-text">{r.id}</span>
              <span className="text-[11.5px] text-text-3">
                {t('ask.material_counts', {
                  m: r.matches?.length || 0,
                  s: r.content?.length || 0,
                })}
              </span>
              <span className="ml-auto flex items-center gap-2">
                {r.found_by?.length > 0 && (
                  <span className="font-mono text-[10.5px] uppercase tracking-[0.08em]
                                   text-text-3">{r.found_by.join(' + ')}</span>
                )}
                {/* The affordance, not a second control: the summary already
                    IS the button, so this is a span the row's own click
                    drives — a nested <button> would be two targets for one
                    act. Open or shut is read off `details[open]` in CSS, so
                    nothing here keeps state the DOM already holds. */}
                {readable && (
                  <span className="btn gap-1.5 rounded-md bg-surface-2 px-2 py-1
                                   text-[11.5px] text-text-2 hover:bg-surface-3
                                   group-open:border-accent/30
                                   group-open:bg-accent-soft group-open:text-accent">
                    <Eye size={13} />
                    <span className="group-open:hidden">{t('ask.material_show')}</span>
                    <span className="hidden group-open:inline">{t('ask.material_hide')}</span>
                  </span>
                )}
              </span>
              {scent(r.id) && (
                <span className="w-full text-[11.5px] leading-relaxed text-text-3">
                  {scent(r.id)}
                </span>
              )}
            </>
          )

          if (!readable) {
            return (
              <div key={r.id} className="flex flex-wrap items-baseline gap-2 rounded-lg
                                         border border-line bg-surface px-3 py-2">
                {head}
              </div>
            )
          }

          return (
            <details key={r.id} className="group rounded-lg border border-line bg-surface">
              <summary className="flex cursor-pointer flex-wrap items-baseline gap-2 px-3 py-2">
                {head}
              </summary>

              <div className="space-y-3 border-t border-line px-3 py-2.5">
                {r.matches?.length > 0 && (
                  <ul className="space-y-1.5">
                    {r.matches.map((m, i) => (
                      <li key={i} className="text-[12px]">
                        <span className="font-mono text-[10.5px] text-text-3">
                          {m.section || '—'}:{m.line}
                        </span>
                        <p className="mt-0.5 border-l-2 border-accent/40 pl-2
                                      font-mono text-[11.5px] leading-relaxed text-text-2">
                          {m.snippet}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}

                {r.content?.map((c, i) => (
                  /* Rows are a table. Rendering them as pretty-printed JSON
                     asked the reader to parse a serialisation of something
                     the console already knows how to draw. */
                  c.columns ? <Rows key={i} {...c} /> : (
                    <div key={i}>
                      <div className="mb-1 text-[11px] text-text-3">
                        {c.section
                          ? t('ask.material_section', { s: c.section })
                          : c.outline ? t('ask.material_outline')
                          : t('ask.material_full')}
                        {c.body_tokens != null && ` · ${c.body_tokens} tokens`}
                      </div>
                      {c.body && (
                        <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words
                                        rounded-md bg-surface-2 p-2.5 font-mono text-[11.5px]
                                        leading-relaxed text-text-2">{c.body}</pre>
                      )}
                      {c.outline && (
                        <p className="font-mono text-[11.5px] text-text-3">
                          {(Array.isArray(c.outline) ? c.outline : [c.outline]).join(' · ')}
                        </p>
                      )}
                    </div>
                  )
                ))}
              </div>
            </details>
          )
        })}
      </div>
    </div>
  )
}

/** The rows a `query` hop returned — the same grid the Data console draws,
 *  with the SQL that produced it above. */
function Rows({ sql, columns, rows, row_count, limited }) {
  const { t } = useI18n()
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline gap-2">
        <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-accent">{sql}</code>
        <span className="text-[11px] text-text-3">
          {t('data.rows', { n: row_count ?? rows.length })}
          {limited ? ` · ${t('data.limited')}` : ''}
        </span>
      </div>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-line bg-surface-2 text-left">
              {columns.map((c) => (
                <th key={c} className="whitespace-nowrap px-2.5 py-1.5 text-[10.5px]
                                       font-semibold uppercase tracking-[0.06em]
                                       text-text-3">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.slice(0, 20).map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j} className="whitespace-nowrap px-2.5 py-1.5 font-mono
                                         tabular-nums text-text-2">
                    {cell === null ? '—' : String(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 20 && (
        <p className="mt-1 text-[11px] text-text-3">{t('ask.rows_more', { n: rows.length - 20 })}</p>
      )}
    </div>
  )
}

/** Where the forager went, hop by hop (J.10.5).
 *
 *  A row of tool names is not a walk: "sniff, sniff, locate" and "sniff → 0,
 *  sniff → 0, locate → 5" are the same list and opposite stories. Each hop
 *  therefore shows what the model chose (its own arguments) and what came
 *  back (one number), numbered so the order is unambiguous.
 */
function Path({ hops }) {
  const { t } = useI18n()
  const outcome = (out = {}) => {
    if (out.error) return t('ask.hop_error', { code: out.error })
    for (const [key, label] of [['results', 'ask.hop_results'], ['rows', 'ask.hop_rows'],
                                ['tokens', 'ask.hop_tokens'], ['nodes', 'ask.hop_nodes'],
                                ['neighbors', 'ask.hop_neighbors'],
                                ['children', 'ask.hop_children'],
                                ['edges', 'ask.hop_edges']]) {
      if (out[key] != null) return t(label, { n: out[key] })
    }
    return ''
  }
  const args = (a = {}) => Object.entries(a)
    .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join(', ') : v}`).join(' · ')

  return (
    <div className="mt-6 border-t border-line pt-4">
      <div className="label">{t('ask.path')} · {t('ask.path_count', { n: hops.length })}</div>
      <p className="mb-2 text-[11px] text-text-3">{t('ask.path_clocks')}</p>
      <ol className="space-y-1">
        {hops.map((h, i) => (
          <li key={i} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5
                                 rounded-md px-1.5 py-1 odd:bg-surface-2/40">
            <span className="w-4 shrink-0 text-right font-mono text-[10.5px] text-text-3">
              {h.n ?? i + 1}
            </span>
            <span className={`font-mono text-[12px] font-medium
                              ${h.ok ? 'text-text' : 'text-danger'}`}>{h.tool}</span>
            {h.id && <span className="font-mono text-[11px] text-text-2">{h.id}</span>}
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-text-3">
              {args(h.args)}
            </span>
            <span className={`shrink-0 text-[11px] tabular-nums
                              ${h.ok ? 'text-text-3' : 'text-danger'}`}>
              {outcome(h.out)}
            </span>
            {/* Two clocks, because they are two costs: the forest call, and
                the model turn that decided to make it. Reporting one number
                would hide which half a slow hunt is actually spending. */}
            <span className="shrink-0 font-mono text-[11px] tabular-nums text-text-2">
              {h.ms != null && `${h.ms < 10 ? h.ms.toFixed(2) : Math.round(h.ms)} ms`}
              {h.model_ms != null && (
                <span className="text-text-3"> + {Math.round(h.model_ms)} ms</span>
              )}
            </span>
            {/* J.10.5 (v0.47): the code alone rendered a mistyped table and a
                mistyped column as the same word twice, so a reader could not
                see that the engine had already answered both. The model was
                always given the whole envelope; this is the panel catching up. */}
            {h.out?.message && (
              <p className="basis-full pl-6 font-mono text-[11px] leading-snug text-danger/80">
                {h.out.message}
              </p>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

/** What the call actually did, step by step (J.10.4).
 *
 *  `answer` is one request and several forest calls plus a provider round
 *  trip. One elapsed number cannot say which of those to fix, and the
 *  usual suspicion — "the forest is slow" — is almost always wrong: the
 *  retrieval half runs in single-digit milliseconds and the model does not.
 */
function Explain({ trace, wall, hybrid, cost, timing }) {
  const { t } = useI18n()
  if (!trace?.steps?.length) return null

  // The gap between the client's stopwatch and the host's own span: TLS, the
  // network, HTTP framing, JSON, this render. Named rather than hidden, so
  // the columns add up. J.10.6's header makes the host's share a measured
  // number instead of a lump in the remainder — without it, the sum of the
  // steps is the best the console can subtract.
  const served = timing
    ? timing.vine + (timing.model || 0) + timing.host
    : trace.total_ms
  const overhead = wall != null ? Math.max(0, wall - served) : null

  return (
    <Card title={t('explain.title')} subtitle={t('explain.sub')}>
      {/* The forest figure is net of the embedder's round trip (J.10.4
          v0.68): `retrieval_ms` is the engine's whole span and the K.2
          embed rides inside it, so printing it whole reads a provider's
          8 s as the forest's — the exact misreading this panel exists to
          prevent, raised by the panel itself. */}
      {/* Two columns, never four. The panel lives in a narrow rail, and a
          fourth column there does not make the tiles smaller — it clips the
          LABELS, which is the half that says what the number is. Two and
          two wraps to a second row and every caption stays whole. Three
          tiles take the same grid and leave one cell empty, which reads as
          a grid with three things in it rather than as a broken row. */}
      <div className="grid grid-cols-2 gap-2">
        <Metric label={t('explain.retrieval')} tone="accent"
                value={`${Math.round((trace.retrieval_ms - (trace.embed_ms || 0)
                                      - (trace.dense_ms || 0)) * 10) / 10} ms`} />
        {trace.dense_ms > 0 && (
          <Metric label={t('explain.dense')} value={`${trace.dense_ms} ms`} />
        )}
        {trace.embed_ms > 0 && (
          <Metric label={t('explain.embed')} value={`${trace.embed_ms} ms`} />
        )}
        <Metric label={t('explain.model')}
                value={trace.steps.find((s) => s.step === 'model')
                  ? `${trace.steps.find((s) => s.step === 'model').ms} ms` : '—'} />
      </div>

      <div className="mt-4">
        <TraceSteps steps={trace.steps} />
      </div>

      <dl className="mt-4 space-y-1.5 border-t border-line pt-3 text-[11.5px]">
        <Row label={t('explain.steps')} value={trace.steps.length} />
        <Row label={t('explain.server')} value={`${trace.total_ms} ms`} />
        {timing && <Row label={t('explain.host')} value={fmtMs(timing.host)} />}
        {overhead != null && <Row label={t('explain.transport')} value={fmtMs(overhead)} />}
        <Row label={t('explain.entry')}
             value={t(hybrid ? 'explain.entry_hybrid' : 'explain.entry_bm25')} />
      </dl>

      {cost && (
        <dl className="mt-3 space-y-1.5 border-t border-line pt-3 text-[11.5px]">
          <Row label={t('explain.tokens_in')} value={cost.prompt_tokens.toLocaleString()} />
          <Row label={t('explain.tokens_out')} value={cost.completion_tokens.toLocaleString()} />
          <Row label={t('explain.calls')} value={cost.calls} />
          {/* An unknown price is not a free one: a local Ollama publishes no
              rate, and rendering that as $0.00 would be a claim. */}
          {cost.priced ? (
            <div className="flex items-baseline justify-between gap-3 pt-1">
              <dt className="font-medium text-text-2">{t('explain.cost')}</dt>
              <dd className="font-mono font-semibold text-accent">
                {cost.usd < 0.01 ? `$${cost.usd.toFixed(6)}` : `$${cost.usd.toFixed(4)}`}
              </dd>
            </div>
          ) : (
            <p className="pt-1 text-[11px] text-text-3">{t('explain.cost_unknown')}</p>
          )}
        </dl>
      )}
    </Card>
  )
}

