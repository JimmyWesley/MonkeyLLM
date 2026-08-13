// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The Clipper's service worker (spec J.15): the one clip pipeline behind
// the popup's buttons, the editor tab and the context menus, plus the
// client-side E_LOCKED queue. The host never queues (J.9) — a busy forest
// answers 409 and the retrying is OURS, in chrome.storage.session, so it
// dies with the browser exactly like Studio's next-batch FIFO (J.9.2) and
// survives the worker being idle-killed in between.
//
// The click answers immediately; the work happens behind it (J.15). Every
// UI surface sends ONE runtime message and gets an ack back before any
// network happens; progress is rendered from storage ('mkc:last' and the
// queue) via chrome.storage.onChanged, and the badge + a notification are
// the completion signal. Closing the popup never cancels anything.

import * as api from './api.js';
import * as i18n from './i18n.js';

const QUEUE_KEY = 'mkc:queue';
const LAST_KEY = 'mkc:last';
const FOREST_KEY = 'mkc:forest';
const DESTS_KEY = 'mkc:dests';

const RETRY_MS = 5000;    // ~5s between attempts...
const MAX_ATTEMPTS = 60;  // ...for about five minutes — the length of a long
                          // batch (J.9), which is exactly what we wait behind
const JOB_POLL_MS = 2000;
const JOB_POLL_MAX = 150; // five minutes of curation is a long batch already
const SHOT_MAX_WIDTH = 1568; // a full-res PNG is pointlessly heavy for a describer
const REGION_WAIT_MS = 180000; // a careful drag deserves patience

/** Translate in the stored UI language — read from storage on every use,
 *  because a notification formatted before the person changed languages
 *  should not speak the old one (J.15: the setting is the person's own,
 *  not the browser's). */
async function tt(key, subs) {
  const lang = await i18n.activeLang();
  return i18n.t(lang, key, subs);
}

// ---------------------------------------------------------------------------
// Context menus — registered at install, retitled when the UI language
// changes. Clicks run the same pipeline as the popup, with the forest and
// branch the person last chose there.
// ---------------------------------------------------------------------------

const MENUS = [
  { id: 'mkc-clip-selection', key: 'menuClipSelection', contexts: ['selection'] },
  { id: 'mkc-clip-page', key: 'menuClipPage', contexts: ['page'], command: 'clip-page' },
  { id: 'mkc-clip-region', key: 'menuCaptureRegion', contexts: ['page'], command: 'capture-region' },
  { id: 'mkc-clip-image', key: 'menuClipImage', contexts: ['image'] },
];

/** Menu titles carry the CURRENT shortcut in parentheses — read from
 *  commands.getAll, never hardcoded: the person may have remapped it in
 *  chrome://extensions/shortcuts, and a suggestion Chrome never applied
 *  (key already taken) shows nothing rather than a lie. */
async function menuTitles() {
  const lang = await i18n.activeLang();
  let bound = {};
  try {
    for (const c of await chrome.commands.getAll()) {
      if (c.name && c.shortcut) bound[c.name] = c.shortcut;
    }
  } catch { bound = {}; }
  return MENUS.map((m) => ({
    ...m,
    title: i18n.t(lang, m.key)
      + (m.command && bound[m.command] ? ` (${bound[m.command]})` : ''),
  }));
}

chrome.runtime.onInstalled.addListener(() => {
  (async () => {
    const titled = await menuTitles();
    // removeAll first: an extension update replays onInstalled, and a
    // create with an id that already exists fails instead of replacing.
    chrome.contextMenus.removeAll(() => {
      for (const m of titled) {
        chrome.contextMenus.create({
          id: m.id,
          title: m.title,
          contexts: m.contexts,
        });
      }
    });
  })();
});

async function retitleMenus() {
  for (const m of await menuTitles()) {
    chrome.contextMenus.update(m.id, { title: m.title }, () => {
      // A menu that does not exist yet (fresh worker before onInstalled
      // replays) is not an error worth surfacing.
      void chrome.runtime.lastError;
    });
  }
}

// Shortcuts have no change event, so remaps are picked up here: the worker
// wakes on every use of the extension, and a retitle is two cheap calls.
retitleMenus();

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab || tab.id === undefined) return;
  clipFromMenu(info, tab).catch(async (e) => {
    notify('notifFailTitle', errorText(e));
    await setLast({ state: 'failed', msg: errorText(e) });
  });
});

/** The forest and branch the person last chose in the popup — the target
 *  every entry point that is not the popup (menus, keyboard) clips into.
 *  Null after saying why, so callers just return. */
async function storedTarget() {
  const acct = await api.account();
  if (!acct) {
    notify('notifFailTitle', await tt('notifPairFirst'));
    return null;
  }
  const stored = await chrome.storage.local.get([FOREST_KEY, DESTS_KEY]);
  const forest = stored[FOREST_KEY];
  if (!forest) {
    notify('notifFailTitle', await tt('notifPickForest'));
    return null;
  }
  return { forest, dest: (stored[DESTS_KEY] || {})[forest] || '' };
}

async function clipFromMenu(info, tab) {
  const target = await storedTarget();
  if (!target) return;

  if (info.menuItemId === 'mkc-clip-image') {
    await clipImage(tab, info, target.forest, target.dest);
    return;
  }
  const kind = info.menuItemId === 'mkc-clip-selection' ? 'selection'
    : info.menuItemId === 'mkc-clip-region' ? 'region'
    : 'page';
  await clipTab(tab, kind, target.forest, target.dest);
}

// ---------------------------------------------------------------------------
// Keyboard shortcuts (J.15): the platform's commands, never our key hooks.
// Chrome applies a suggested key ONLY when nothing else holds it, and the
// person remaps everything at chrome://extensions/shortcuts — so a clash
// with the browser or the system resolves to "unassigned", never to a
// stolen key. Pressing one is a user gesture: activeTab is granted exactly
// as it is for a click.
// ---------------------------------------------------------------------------

chrome.commands.onCommand.addListener((command, tab) => {
  (async () => {
    const active = tab && tab.id !== undefined
      ? tab
      : (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
    if (!active || active.id === undefined) return;
    const target = await storedTarget();
    if (!target) return;
    const kind = command === 'capture-region' ? 'region' : 'page';
    await clipTab(active, kind, target.forest, target.dest);
  })().catch(async (e) => {
    notify('notifFailTitle', errorText(e));
    await setLast({ state: 'failed', msg: errorText(e) });
  });
});

// ---------------------------------------------------------------------------
// Runtime messages. Two families:
//   - the region picker reporting back (a content script talking up), and
//   - UI surfaces asking for work ('clip' | 'compose' | 'upload').
// Work messages are ACKED IMMEDIATELY and run detached: the popup that sent
// one may be gone before the first byte reaches the server, and that is the
// design — the person keeps browsing, storage carries the progress, and the
// badge + notification carry the outcome (J.15).
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const type = msg && msg.type;

  if (type === 'mkc:region-ping') {
    // The picker's heartbeat: handling any message resets the worker's
    // idle clock, which is the entire point.
    sendResponse({ ok: true });
    return false;
  }
  if (type === 'mkc:region-picked') {
    const tabId = sender && sender.tab && sender.tab.id;
    const settle = tabId !== undefined && pendingRegions.get(tabId);
    if (settle) {
      settle(msg.cancelled ? null : msg);
    } else if (!msg.cancelled) {
      // A rectangle arrived with nobody waiting: the wait expired, or the
      // worker was restarted mid-drag. The overlay removed itself exactly
      // as on success, so without saying so the person believes the
      // region was clipped when nothing was.
      (async () => {
        await setLast({ state: 'failed', msg: await tt('errRegionExpired') });
        notify('notifFailTitle', await tt('errRegionExpired'));
      })();
    }
    sendResponse({ ok: true });
    return false;
  }

  // Dictation for the region note (J.15): the overlay asks, an OFFSCREEN
  // document of the extension listens — SpeechRecognition needs a page and
  // the page under the overlay must never be the one holding the mic. The
  // types encode direction: -start/-stop come up from the tab, -go/-halt
  // go down to offscreen, -result/-error/-end come back from it.
  if (type === 'mkc:stt-start') {
    sttTabId = sender && sender.tab && sender.tab.id;
    startDictation().catch(() => relaySpeech({
      type: 'mkc:stt-error', error: 'unavailable' }));
    sendResponse({ ok: true });
    return false;
  }
  if (type === 'mkc:stt-stop') {
    chrome.runtime.sendMessage({ type: 'mkc:stt-halt' }).catch(() => {});
    sendResponse({ ok: true });
    return false;
  }
  if (type === 'mkc:stt-result' || type === 'mkc:stt-error'
      || type === 'mkc:stt-end' || type === 'mkc:stt-live') {
    relaySpeech(msg);
    sendResponse({ ok: true });
    return false;
  }

  if (type === 'clip' || type === 'compose' || type === 'upload') {
    runDetached(msg);
    sendResponse({ ok: true, accepted: true });
    return false;
  }

  sendResponse({ ok: false, error: { code: 'E_SCHEMA', message: `unknown message: ${type}` } });
  return false;
});

/** Start the work and answer nobody: failures land in 'mkc:last' and a
 *  notification, which are the only channels a closed popup still has. */
function runDetached(msg) {
  handleWork(msg).catch(async (e) => {
    await setLast({ state: 'failed', msg: errorText(e) });
    notify('notifFailTitle', errorText(e));
  });
}

async function handleWork(msg) {
  switch (msg.type) {
    case 'clip': {
      const tab = await chrome.tabs.get(msg.tabId);
      return clipTab(tab, msg.kind, msg.forest, msg.dest || '');
    }
    case 'compose':
      return submitAndTell(msg.forest,
        composeBody(msg.dest || '', msg.title, msg.text), msg.title);
    case 'upload':
      return submitAndTell(msg.forest,
        uploadBody(msg.dest || '', msg.files, msg.sourceUrl),
        msg.label || (msg.files[0] && msg.files[0].name) || 'upload');
    default:
      throw new Error(`unknown message: ${msg.type}`);
  }
}

async function submitAndTell(forest, body, label) {
  await setLast({ state: 'working' });
  const out = await submitIngest(forest, body, label);
  await notifyOutcome(out, label);
  return out;
}

// ---------------------------------------------------------------------------
// The clip pipeline
// ---------------------------------------------------------------------------

/** kind: 'page' | 'selection' | 'shot' | 'both' | 'region'. */
async function clipTab(tab, kind, forest, dest) {
  await setLast({ state: 'working' });
  try {
    const pageUrl = stripTracking(tab.url || '');

    if (kind === 'shot') {
      const name = shotName(tab.title || 'page', pageUrl);
      const b64 = await captureShot(tab);
      const out = await submitUpload(forest, dest, [{ name, b64 }], name, pageUrl);
      await notifyOutcome(out, name);
      return out;
    }

    if (kind === 'region') {
      // The popup closed when the person clicked the page — by design; this
      // worker owns the flow from here (J.15: the crop happens client-side,
      // and no pixels leave the tab except the chosen rectangle).
      const rect = await pickRegion(tab);
      if (!rect) {
        await setLast({ state: 'failed', msg: await tt('errRegionCancelled') });
        return { cancelled: true };
      }
      const name = shotName(tab.title || 'page', pageUrl);
      const b64 = await cropShot(tab, rect, rect.devicePixelRatio || 1,
                                 rect.annotations || []);
      // A note written in the picker travels as a PAIRED compose — the
      // media node's body is the server's to write (J.15), so the person's
      // words become their own node, naming the screenshot it rode with,
      // exactly the two-nodes shape of 'both'.
      const comment = String(rect.comment || '').trim();
      if (comment) {
        const title = comment.split('\n')[0].slice(0, 80)
          || `Note on ${tab.title || 'a page'}`;
        const text = comment
          + `\n\nWritten over the region screenshot \`${name}\`; `
          + 'its media node shows the selected area.'
          + sourceLine(pageUrl);
        await submitCompose(forest, dest, title, text);
      }
      const out = await submitUpload(forest, dest, [{ name, b64 }], name, pageUrl);
      await notifyOutcome(out, name);
      return out;
    }

    // Pixels first, prose second: the screenshot must show the page the
    // person clicked on, and captureVisibleTab shoots whatever is active
    // in the window at CALL time — after a slow curated compose that can
    // be another tab entirely, and if the person navigated the clipped
    // tab, activeTab is gone and the pair would fail half-planted.
    const shotB64 = kind === 'both' ? await captureShot(tab) : null;

    const clip = await extract(tab, kind === 'selection' ? 'selection' : 'page');
    const url = stripTracking(clip.url || tab.url || '');
    const title = clip.title || tab.title || url;
    let markdown = clip.markdown || '';
    let name = null;

    if (kind === 'both') {
      // Two nodes, each naming the other in prose (J.15): the markdown
      // names the image file it was clipped with, and the file NAME —
      // the one piece of prose an upload lets a client author — carries
      // the page's title and host so the media node's body quotes them.
      name = shotName(title, url);
      markdown += `\n\nA screenshot taken with this clip was uploaded as ` +
        `\`${name}\`; its media node shows this same page.`;
    }

    markdown += sourceLine(url);
    const composed = await submitCompose(forest, dest, title, markdown);

    if (kind === 'both' && composed) {
      // Queued or not, the screenshot rides with the prose: submitUpload
      // itself queues on E_LOCKED, so the pair still lands as a pair once
      // the batch ahead of it finishes. The image carries the same
      // source_url — provenance travels on every path (J.15).
      const up = await submitUpload(forest, dest, [{ name, b64: shotB64 }], name, url);
      if (!composed.queued) await notifyOutcome(up, name);
      return { ...composed, upload: up };
    }
    await notifyOutcome(composed, title);
    return composed;
  } catch (e) {
    await setLast({ state: 'failed', msg: errorText(e) });
    throw e;
  }
}

/** Inject vendors + clip.js and run the extraction. The injection itself is
 *  the activeTab consent being spent; a page the browser refuses to touch
 *  (chrome://, the web store) surfaces as one friendly error. */
async function extract(tab, mode) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: [
        'vendor/Readability.js',
        'vendor/turndown.js',
        'vendor/turndown-plugin-gfm.js',
        'clip.js',
      ],
    });
  } catch (e) {
    throw new Error(await tt('errUnclippable'));
  }

  // YouTube's player state lives in a page global the isolated world cannot
  // see, so a tiny MAIN-world grabber reads it and hands it across. The
  // transcript itself is fetched by clip.js from the page context — the
  // only context where that caption URL is same-origin.
  let yt = null;
  if (/^https?:\/\/(www\.|m\.)?youtube\.com\/watch/.test(tab.url || '')) {
    try {
      const [r] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        world: 'MAIN',
        func: grabYouTube,
      });
      yt = (r && r.result) || null;
    } catch {
      // Best-effort by contract: no player response, ordinary page clip.
    }
  }

  const [res] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: (opts) => window.__monkeyClip.run(opts),
    args: [{ mode, yt }],
  });
  const out = res && res.result;
  if (!out) throw new Error(await tt('errUnclippable'));
  if (out.error === 'no-selection') throw new Error(await tt('errNoSelection'));
  return out;
}

/** Runs in the page's MAIN world. Keep it dependency-free and defensive:
 *  it executes inside an arbitrary page and must only ever return data. */
function grabYouTube() {
  try {
    const pr = window.ytInitialPlayerResponse;
    if (!pr || !pr.videoDetails) return null;
    const list = pr.captions
      && pr.captions.playerCaptionsTracklistRenderer
      && pr.captions.playerCaptionsTracklistRenderer.captionTracks;
    return {
      title: pr.videoDetails.title || document.title,
      channel: pr.videoDetails.author || '',
      description: pr.videoDetails.shortDescription || '',
      captionUrl: (list && list.length) ? list[0].baseUrl : null,
    };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Region capture — inject the overlay, wait for the rectangle, crop the
// visible tab. The overlay reports viewport CSS pixels + dpr; the crop
// multiplies and clamps, so a zoomed page or a 2× display crops what was
// actually drawn (J.15).
// ---------------------------------------------------------------------------

const pendingRegions = new Map(); // tabId → settle(rect|null)

// -- dictation plumbing (J.15): tab ⇄ worker ⇄ offscreen ---------------------

let sttTabId = null; // the tab whose overlay is listening

async function startDictation() {
  try {
    await chrome.offscreen.createDocument({
      url: 'offscreen.html',
      reasons: ['USER_MEDIA'],
      justification: 'Speech recognition for the region note: the '
        + 'microphone belongs to the extension, never to the page '
        + 'under the overlay.',
    });
  } catch {
    // Already open from a previous round — fine, it is idempotent below.
  }
  const lang = await i18n.activeLang();
  const srLang = { pt: 'pt-BR', es: 'es-ES', en: 'en-US' }[lang]
    || navigator.language || 'en-US';
  await chrome.runtime.sendMessage({ type: 'mkc:stt-go', lang: srLang });
}

function relaySpeech(msg) {
  if (sttTabId !== null && sttTabId !== undefined) {
    chrome.tabs.sendMessage(sttTabId, msg).catch(() => {});
  } else {
    // The listener is an extension page (the popup's ask box), not a tab:
    // a runtime broadcast reaches it, and every other extension context
    // ignores types it does not know.
    chrome.runtime.sendMessage(msg).catch(() => {});
  }
  if (msg.type === 'mkc:stt-error' && msg.error === 'not-allowed') {
    // The extension's origin has no microphone grant yet. A prompt cannot
    // render inside an offscreen document, so a small visible page asks
    // ONCE; every later session is silent.
    chrome.tabs.create({ url: 'permission.html' });
  }
  // The offscreen document stays WARM between sessions on purpose: its
  // creation is a visible chunk of the words-eaten-at-the-start delay,
  // and an idle document holds no microphone — the indicator follows the
  // recognizer, not the page.
}

async function pickRegion(tab) {
  const picked = new Promise((resolve) => {
    const timer = setTimeout(() => {
      pendingRegions.delete(tab.id);
      // Tell the overlay to go: without this it sits on the page pinging a
      // worker that stopped listening, and a drag completed after the
      // deadline would vanish into the no-settle branch looking exactly
      // like a success to the person who drew it.
      chrome.tabs.sendMessage(tab.id, { type: 'mkc:region-teardown' })
        .catch(() => { /* tab gone or overlay already down */ });
      resolve(null);
    }, REGION_WAIT_MS);
    pendingRegions.set(tab.id, (rect) => {
      clearTimeout(timer);
      pendingRegions.delete(tab.id);
      resolve(rect);
    });
  });
  try {
    // The overlay's words, in the person's own language: a content script
    // cannot reach the extension's i18n module, so the strings are planted
    // one message ahead of the file that reads them.
    const text = {
      placeholder: await tt('regionComment'),
      capture: await tt('regionCapture'),
      cancel: await tt('regionCancel'),
      adjust: await tt('regionAdjust'),
      arrow: await tt('regionArrow'),
      rect: await tt('regionRect'),
      pen: await tt('regionPen'),
      text: await tt('regionText'),
      undo: await tt('regionUndo'),
      mic: await tt('regionMic'),
      micStop: await tt('regionMicStop'),
      micDenied: await tt('regionMicDenied'),
      listening: await tt('regionListening'),
      preparing: await tt('sttPreparing'),
      processing: await tt('sttProcessing'),
    };
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      args: [text],
      func: (t) => { window.__mkcRegionText = t; },
    });
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['region.js'],
    });
  } catch {
    pendingRegions.delete(tab.id);
    throw new Error(await tt('errUnclippable'));
  }
  return picked;
}

/** Crop `rect` (viewport CSS px) out of the visible tab. Same JPEG shape
 *  as a full shot, and the same width cap — the describer reads it, not a
 *  print shop. */
async function cropShot(tab, rect, dpr, annotations = []) {
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: 'png',
  });
  const blob = await (await fetch(dataUrl)).blob();
  const bmp = await createImageBitmap(blob);
  // Multiply by dpr, then clamp to the bitmap: on a zoomed page or a
  // multi-monitor window the math can land a pixel outside, and drawImage
  // with an out-of-range source rectangle silently distorts.
  let sx = Math.round(rect.x * dpr);
  let sy = Math.round(rect.y * dpr);
  let sw = Math.round(rect.w * dpr);
  let sh = Math.round(rect.h * dpr);
  sx = Math.max(0, Math.min(sx, bmp.width - 1));
  sy = Math.max(0, Math.min(sy, bmp.height - 1));
  sw = Math.max(1, Math.min(sw, bmp.width - sx));
  sh = Math.max(1, Math.min(sh, bmp.height - sy));
  const scale = Math.min(1, SHOT_MAX_WIDTH / sw);
  const w = Math.max(1, Math.round(sw * scale));
  const h = Math.max(1, Math.round(sh * scale));
  const canvas = new OffscreenCanvas(w, h);
  const ctx = canvas.getContext('2d');
  ctx.drawImage(bmp, sx, sy, sw, sh, 0, 0, w, h);
  bmp.close();
  // The picker's annotations (J.15) are vectors in viewport CSS px; they
  // are composited HERE, onto the cropped bitmap, never into the page's
  // DOM — the overlay tears down whole before the capture (the race we
  // fixed once), and the arrows render at full sharpness regardless.
  if (annotations.length) drawAnnotations(ctx, annotations, sx, sy, dpr, scale);
  const jpeg = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.85 });
  return b64Of(new Uint8Array(await jpeg.arrayBuffer()));
}

const ANNOTATION_COLOR = '#e5484d'; // the red every screenshot tool taught

function drawAnnotations(ctx, annotations, sx, sy, dpr, scale) {
  const fx = (v) => (v * dpr - sx) * scale;
  const fy = (v) => (v * dpr - sy) * scale;
  const lw = Math.max(2.5, 3 * dpr * scale);
  ctx.strokeStyle = ANNOTATION_COLOR;
  ctx.fillStyle = ANNOTATION_COLOR;
  ctx.lineWidth = lw;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  for (const a of annotations) {
    if (a.kind === 'rect') {
      ctx.strokeRect(fx(a.x), fy(a.y),
                     Math.max(1, a.w * dpr * scale),
                     Math.max(1, a.h * dpr * scale));
    } else if (a.kind === 'arrow') {
      const x1 = fx(a.x1); const y1 = fy(a.y1);
      const x2 = fx(a.x2); const y2 = fy(a.y2);
      const angle = Math.atan2(y2 - y1, x2 - x1);
      const head = Math.max(12 * dpr * scale, lw * 3.5);
      // The shaft stops short of the tip so the head's point stays sharp.
      const bx = x2 - Math.cos(angle) * head * 0.6;
      const by = y2 - Math.sin(angle) * head * 0.6;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(bx, by);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 - head * Math.cos(angle - 0.42),
                 y2 - head * Math.sin(angle - 0.42));
      ctx.lineTo(x2 - head * Math.cos(angle + 0.42),
                 y2 - head * Math.sin(angle + 0.42));
      ctx.closePath();
      ctx.fill();
    } else if (a.kind === 'pen' && Array.isArray(a.points) && a.points.length > 1) {
      ctx.beginPath();
      ctx.moveTo(fx(a.points[0][0]), fy(a.points[0][1]));
      for (const [px, py] of a.points.slice(1)) ctx.lineTo(fx(px), fy(py));
      ctx.stroke();
    } else if (a.kind === 'text' && a.text) {
      // Mirrors the preview: 600 16px system-ui at the label's top-left.
      // The same CSS pixel size scaled the same way keeps what was typed
      // where it was typed.
      ctx.font = `600 ${16 * dpr * scale}px system-ui, sans-serif`;
      ctx.textBaseline = 'top';
      ctx.fillText(String(a.text), fx(a.x), fy(a.y));
    }
  }
}

// ---------------------------------------------------------------------------
// Image context menu — the bytes come from the page, never from this
// worker (it holds no host permission for arbitrary image origins and must
// not ask for any). Chain: (1) fetch in the page's MAIN world, which is
// same-origin or CORS-open exactly when the page itself could read the
// image; (2) failing that, crop the rectangle the <img> occupies out of
// captureVisibleTab — the screen never lies (J.15).
// ---------------------------------------------------------------------------

async function clipImage(tab, info, forest, dest) {
  await setLast({ state: 'working' });
  try {
    const pageUrl = stripTracking(info.pageUrl || tab.url || '');
    let b64 = null;
    let mime = null;

    try {
      const [r] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        world: 'MAIN',
        func: fetchImageInPage,
        args: [info.srcUrl || ''],
      });
      if (r && r.result && r.result.b64) {
        b64 = r.result.b64;
        mime = r.result.mime || null;
      }
    } catch {
      // Injection refused or the page fetch threw; the screen fallback is
      // next, and it is the honest one anyway.
    }

    if (b64) {
      // The Gardener claims png/jpg/jpeg/gif/webp (G.5.1) and nothing
      // else: an .svg or .avif would stage, report `unsupported`, and
      // plant nothing — a clip that silently vanishes. Transcode what the
      // worker can decode (AVIF); what it cannot (SVG has no decoder
      // here) falls through to the screen crop, which never lies.
      try {
        ({ b64, mime } = await toServerImage(b64, mime));
      } catch {
        b64 = null;
      }
    }

    if (!b64) {
      const [r] = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: imageRectInPage,
        args: [info.srcUrl || ''],
      });
      const rect = r && r.result;
      if (!rect) throw new Error(await tt('errNoImage'));
      b64 = await cropShot(tab, rect, rect.devicePixelRatio || 1);
      mime = 'image/jpeg';
    }

    const name = imageName(info.srcUrl || '', tab.title || 'image', mime);
    const out = await submitUpload(forest, dest, [{ name, b64 }], name, pageUrl);
    await notifyOutcome(out, name);
    return out;
  } catch (e) {
    await setLast({ state: 'failed', msg: errorText(e) });
    throw e;
  }
}

/** Runs in the page's MAIN world: fetch the image with the page's own
 *  authority and hand back bytes. Cross-origin without CORS rejects — the
 *  caller falls back to the screen. Dependency-free, returns data only. */
async function fetchImageInPage(srcUrl) {
  try {
    if (!srcUrl) return null;
    const res = await fetch(srcUrl);
    if (!res.ok) return null;
    const blob = await res.blob();
    if (blob.size > 20 * 1024 * 1024) return null; // not an upload surface for originals
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let s = '';
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
    }
    return { b64: btoa(s), mime: blob.type || null };
  } catch {
    return null;
  }
}

/** Runs in the page (isolated world): find the <img> under that URL, bring
 *  it on screen if needed, and report the viewport rectangle it occupies —
 *  clamped, because captureVisibleTab sees the viewport and nothing else. */
async function imageRectInPage(srcUrl) {
  const imgs = Array.from(document.images || []);
  const img = imgs.find((i) => i.currentSrc === srcUrl || i.src === srcUrl)
    || imgs.find((i) => i.currentSrc && srcUrl
                        && i.currentSrc.split('#')[0] === srcUrl.split('#')[0]);
  if (!img) return null;
  let r = img.getBoundingClientRect();
  const off = r.bottom < 0 || r.top > window.innerHeight
    || r.right < 0 || r.left > window.innerWidth;
  if (off) {
    img.scrollIntoView({ block: 'center', inline: 'center' });
    // One breath for the scroll and repaint to land before the screenshot.
    await new Promise((resolve) => setTimeout(resolve, 350));
    r = img.getBoundingClientRect();
  }
  const x = Math.max(0, r.left);
  const y = Math.max(0, r.top);
  const w = Math.min(r.right, window.innerWidth) - x;
  const h = Math.min(r.bottom, window.innerHeight) - y;
  if (w < 2 || h < 2) return null;
  return { x, y, w, h, devicePixelRatio: window.devicePixelRatio || 1 };
}

/** A name for the uploaded image: the URL's basename when it has one, the
 *  page-title slug when it does not, extension corrected to the mime the
 *  bytes actually carry. */
function imageName(srcUrl, pageTitle, mime) {
  let base = '';
  try {
    const path = new URL(srcUrl).pathname;
    base = decodeURIComponent(path.split('/').pop() || '');
  } catch { /* data: or garbage; the slug below covers it */ }
  base = slug(base.replace(/\.[a-z0-9]+$/i, ''), 60) || slug(pageTitle, 40) || 'image';
  // Raster extensions only — toServerImage already transcoded anything
  // else, so a name the server's converters do not claim never leaves.
  const ext = { 'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif',
                'image/webp': '.webp' }[mime] || '.jpg';
  return base + ext;
}

// ---------------------------------------------------------------------------
// Screenshot capture — visible tab, downscaled to a describer-sized JPEG.
// ---------------------------------------------------------------------------

async function captureShot(tab) {
  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: 'png',
  });
  const blob = await (await fetch(dataUrl)).blob();
  const bmp = await createImageBitmap(blob);
  const scale = Math.min(1, SHOT_MAX_WIDTH / bmp.width);
  const w = Math.max(1, Math.round(bmp.width * scale));
  const h = Math.max(1, Math.round(bmp.height * scale));
  const canvas = new OffscreenCanvas(w, h);
  canvas.getContext('2d').drawImage(bmp, 0, 0, w, h);
  bmp.close();
  const jpeg = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.85 });
  return b64Of(new Uint8Array(await jpeg.arrayBuffer()));
}

function b64Of(bytes) {
  // btoa over chunks: String.fromCharCode.apply on the whole buffer blows
  // the argument limit on big screenshots.
  let s = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(s);
}

// What the Gardener's converters claim (G.5.1). Anything else uploaded
// as-is stages, reports `unsupported`, and plants nothing.
const SERVER_IMAGE_MIMES = new Set([
  'image/png', 'image/jpeg', 'image/gif', 'image/webp',
]);

/** Bytes the server would refuse become a JPEG it will not; bytes it
 *  accepts pass through untouched. Throws when the worker cannot decode
 *  the format (SVG) — the caller's screen-crop fallback takes over. */
async function toServerImage(b64, mime) {
  if (SERVER_IMAGE_MIMES.has(mime)) return { b64, mime };
  const blob = await (await fetch(
    `data:${mime || 'application/octet-stream'};base64,${b64}`)).blob();
  const bmp = await createImageBitmap(blob);
  const canvas = new OffscreenCanvas(bmp.width, bmp.height);
  canvas.getContext('2d').drawImage(bmp, 0, 0);
  bmp.close();
  const jpeg = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.9 });
  return { b64: b64Of(new Uint8Array(await jpeg.arrayBuffer())),
           mime: 'image/jpeg' };
}

// ---------------------------------------------------------------------------
// Submitting — compose for ALL prose, upload ONLY for binaries (J.15).
// Every upload entry carries source_url when a page produced it: a clip
// nobody can trace back to its page is a citation with no cite.
// ---------------------------------------------------------------------------

function composeBody(dest, title, text) {
  return {
    mode: 'compose',
    title,
    text,
    ...(dest ? { dest } : {}),
  };
}

/** The Station validates source_url as http/https and ≤2048 chars; send
 *  only what it will take, and never let a weird URL sink the upload. */
function uploadBody(dest, files, sourceUrl) {
  const src = /^https?:\/\//i.test(sourceUrl || '') && sourceUrl.length <= 2048
    ? sourceUrl : null;
  return {
    mode: 'upload',
    files: files.map((f) => (src ? { ...f, source_url: src } : { ...f })),
    ...(dest ? { dest } : {}),
  };
}

function submitCompose(forest, dest, title, text) {
  return submitIngest(forest, composeBody(dest, title, text), title);
}

function submitUpload(forest, dest, files, label, sourceUrl) {
  return submitIngest(forest, uploadBody(dest, files, sourceUrl),
    label || (files[0] && files[0].name) || 'upload');
}

/** Is a batch mid-run on this forest? A compose does not 409 — it WAITS on
 *  the forest lane behind every remaining step of the batch (J.9), which
 *  from a popup reads as a freeze. So composes look at the job board first
 *  and queue behind a running batch instead of standing in line silently.
 *  The board read touches no lane (J.9), so asking is free. */
async function forestBusy(forest) {
  try {
    const listed = await api.jobs(forest);
    return (listed.jobs || []).some((j) => j.state === 'running');
  } catch {
    // No board to read (older Station, network blip): try the write itself
    // rather than inventing a refusal the server never gave.
    return false;
  }
}

/** One door for every ingest. Success is reported per shape — compose
 *  answers in place, upload answers a job we poll — and E_LOCKED lands in
 *  the queue instead of on the floor. */
async function submitIngest(forest, body, label) {
  if (body.mode === 'compose' && await forestBusy(forest)) {
    await enqueue({ forest, body, label });
    await setLast({ state: 'queued' });
    return { queued: true };
  }
  let result;
  try {
    result = await api.ingest(forest, body);
  } catch (e) {
    if (e && e.code === 'E_LOCKED') {
      await enqueue({ forest, body, label });
      await setLast({ state: 'queued' });
      return { queued: true };
    }
    throw e;
  }
  return settleIngest(forest, result, label);
}

/** A fresh (non-queued) success: read the shape and update the strip. */
async function settleIngest(forest, result, label) {
  if (result && result.job) {
    // A batch was accepted (202): the report arrives on the job (J.9).
    await setLast({ state: 'job', id: result.job.id });
    const done = await pollJob(forest, result.job.id);
    if (done.state === 'done') {
      // J.8: a partially successful ingest that reports success is worse
      // than one that fails — a 'done' job whose report planted nothing
      // (all unsupported, all errors) is a failure to the person who
      // clipped, whatever the job's state says.
      const failure = reportFailure(done.report);
      if (failure) {
        await setLast({ state: 'failed', msg: failure });
        throw new Error(failure);
      }
      await setLast({ state: 'planted', id: plantedOf(done.report) || label });
    } else {
      const msg = (done.error && done.error.message) || done.state;
      await setLast({ state: 'failed', msg });
      throw new Error(msg);
    }
    return { job: done };
  }
  // compose answered in place with the Gardener's report.
  const failure = reportFailure(result);
  if (failure) {
    await setLast({ state: 'failed', msg: failure });
    throw new Error(failure);
  }
  const id = plantedOf(result) || label;
  await setLast({ state: 'planted', id });
  return { planted: id, report: result };
}

function plantedOf(report) {
  if (!report) return null;
  for (const listName of ['planted', 'updated', 'unchanged']) {
    const list = report[listName];
    if (Array.isArray(list) && list.length) return list[0];
  }
  return null;
}

/** The reason a report that landed nothing is a failure, or null when
 *  something was planted, updated or deliberately kept as unchanged. The
 *  server's own error strings are shown verbatim — they name the file and
 *  the converter, which is exactly what the person needs. */
function reportFailure(report) {
  if (!report) return null;
  const landed = ['planted', 'updated', 'unchanged']
    .some((k) => Array.isArray(report[k]) && report[k].length);
  if (landed) return null;
  if (Array.isArray(report.errors) && report.errors.length) {
    return String(report.errors[0]);
  }
  if (Array.isArray(report.unsupported) && report.unsupported.length) {
    return `unsupported: ${report.unsupported[0]}`;
  }
  return 'nothing was planted';
}

async function pollJob(forest, id) {
  for (let i = 0; i < JOB_POLL_MAX; i++) {
    await sleep(JOB_POLL_MS);
    const got = await api.job(forest, id);
    const snap = got && got.job;
    if (!snap) break;
    if (snap.state !== 'running') return snap;
  }
  return { state: 'error', error: { message: 'job did not settle in time' } };
}

async function notifyOutcome(out, label) {
  if (!out || out.queued || out.cancelled) return; // the queue notifies when it drains
  if (out.job) {
    notify('notifOkTitle', await tt('notifUploadDone', [label]));
  } else {
    notify('notifOkTitle', String(out.planted || label));
  }
}

// ---------------------------------------------------------------------------
// The E_LOCKED queue — storage.session, badge while pending, notification
// on the final outcome. Read on every worker wake so an idle-kill between
// retries forgets the timer, never the work.
// ---------------------------------------------------------------------------

let pumpArmed = false;
let pumpRunning = false;
let pumpQueued = false;

// Every queue mutation goes through ONE promise chain. The queue lives in
// storage.session, and both enqueue() and the pump read-modify-write it
// across awaits — interleaved, one write silently clobbers the other, which
// is a dropped clip (the one thing a queue may never do) or a re-fired one.
let queueChain = Promise.resolve();
function withQueue(fn) {
  const run = queueChain.then(fn, fn);
  queueChain = run.then(() => {}, () => {});
  return run;
}

async function readQueue() {
  const got = await chrome.storage.session.get(QUEUE_KEY);
  return got[QUEUE_KEY] || [];
}

async function writeQueue(queue) {
  await chrome.storage.session.set({ [QUEUE_KEY]: queue });
  await badge(queue.length);
}

function enqueue(entry) {
  return withQueue(async () => {
    const queue = await readQueue();
    queue.push({
      id: 'q-' + Math.random().toString(36).slice(2, 10),
      attempts: 0,
      at: Date.now(),
      ...entry,
    });
    await writeQueue(queue);
  }).then(() => armPump());
}

function armPump(delay = RETRY_MS) {
  // One timer, re-armed after each pass. setTimeout in a worker is only as
  // durable as the worker — which is why the queue itself lives in
  // storage.session and is re-read at the top of this file on every wake.
  if (pumpArmed) return;
  pumpArmed = true;
  setTimeout(() => {
    pumpArmed = false;
    runPump();
  }, delay);
}

async function runPump() {
  // One pump at a time. A pump can block for minutes inside a job poll,
  // and a second timer firing meanwhile must not start a sibling: two
  // pumps would take the same entry twice and overwrite each other's
  // remainder. A request that arrives mid-run marks pumpQueued and the
  // running pump goes one more round instead.
  if (pumpRunning) {
    pumpQueued = true;
    return;
  }
  pumpRunning = true;
  try {
    do {
      pumpQueued = false;
      await pump();
    } while (pumpQueued);
  } catch {
    armPump();
  } finally {
    pumpRunning = false;
  }
}

async function pump() {
  for (;;) {
    // Pop ONE entry before processing it — no snapshot of the whole queue
    // is ever held across an await and written back, so an enqueue landing
    // mid-flight is picked up on the next turn of this loop instead of
    // being overwritten.
    const entry = await withQueue(async () => {
      const queue = await readQueue();
      if (!queue.length) return null;
      await writeQueue(queue.slice(1));
      return queue[0];
    });
    if (entry === null) {
      await badge(0);
      return;
    }
    try {
      // A retried compose gets the SAME board check the fresh one got:
      // firing it into a lane that is mid-batch would not 409, it would
      // park the pump behind the whole batch — the freeze, relocated.
      if (entry.body.mode === 'compose' && await forestBusy(entry.forest)) {
        const still = new Error('an ingest job is still running on this forest');
        still.code = 'E_LOCKED';
        throw still;
      }
      const result = await api.ingest(entry.forest, entry.body);
      const settled = await settleIngest(entry.forest, result, entry.label);
      await notifyOutcome(settled, entry.label);
    } catch (e) {
      if (e && e.code === 'E_LOCKED') {
        entry.attempts += 1;
        if (entry.attempts >= MAX_ATTEMPTS) {
          // Five minutes of 409s is not a hiccup any more; give up LOUDLY —
          // dropping silently is the one thing a queue may never do.
          notify('notifFailTitle', await tt('statusFailed', [errorText(e)]));
          await setLast({ state: 'failed', msg: errorText(e) });
        } else {
          // Back into the LIVE queue, not a snapshot, and wait a beat:
          // the forest is busy, so hammering the next entry now would
          // only collect the same 409.
          await withQueue(async () => {
            const queue = await readQueue();
            queue.push(entry);
            await writeQueue(queue);
          });
          armPump();
          return;
        }
      } else {
        // A real refusal (scope, schema, read-only) will not get better by
        // waiting; report it and drop the entry.
        notify('notifFailTitle', errorText(e));
        await setLast({ state: 'failed', msg: errorText(e) });
      }
    }
  }
}

// Wake-up: whatever was pending when the worker last died is still in
// storage.session; put the badge back and resume retrying.
readQueue().then((queue) => {
  badge(queue.length);
  if (queue.length) armPump();
});

// The context menus speak the stored language; a change made in the popup
// or the editor reaches this worker as a storage event (and wakes it).
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes[i18n.LANG_KEY]) retitleMenus();
});

// ---------------------------------------------------------------------------
// Small shared bits
// ---------------------------------------------------------------------------

/** Tracking params never enter the forest: a clipped URL is a citation,
 *  and utm_* / fbclid / gclid are somebody else's bookkeeping. */
function stripTracking(raw) {
  try {
    const u = new URL(raw);
    const drop = [];
    for (const k of u.searchParams.keys()) {
      if (/^utm_/i.test(k) || k === 'fbclid' || k === 'gclid') drop.push(k);
    }
    for (const k of drop) u.searchParams.delete(k);
    return u.toString();
  } catch {
    return raw;
  }
}

/** Every clip's markdown ends with where it came from and when (J.15).
 *  Forest content is English by project policy, so this line is not
 *  localized — it is content, not UI. */
function sourceLine(url) {
  const day = new Date().toISOString().slice(0, 10);
  return `\n\n---\n\nSource: ${url} (clipped ${day})`;
}

/** Slugs are for file NAMES sent to upload, never for compose titles —
 *  the server slugs compose titles itself and must see the original. */
function slug(text, max = 40) {
  return String(text || '').toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, max);
}

function shotName(title, url) {
  let host = '';
  try { host = new URL(url).hostname; } catch { /* keep '' */ }
  const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 12);
  return `${slug(title) || 'page'}--${slug(host, 30)}-${stamp}.jpg`;
}

async function setLast(last) {
  await chrome.storage.session.set({ [LAST_KEY]: { ...last, at: Date.now() } });
}

async function badge(count) {
  await chrome.action.setBadgeBackgroundColor({ color: '#2e7d4f' });
  await chrome.action.setBadgeText({ text: count ? String(count) : '' });
}

/** Fire a notification in the stored UI language. Fire-and-forget by
 *  design — callers are mid-pipeline and a notification must never gate
 *  the work — but the language read is awaited inside, so the text is
 *  the person's language at SEND time. */
function notify(titleKey, message) {
  (async () => {
    const title = await tt(titleKey);
    chrome.notifications.create({
      type: 'basic',
      iconUrl: 'icons/icon128.png',
      title,
      message: String(message || ''),
    });
  })();
}

function errorText(e) {
  if (!e) return 'unknown error';
  const msg = e.message || String(e);
  return e.hint ? `${msg} — ${e.hint}` : msg;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
