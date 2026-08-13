// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The popup: LOGIN (pair or paste a token) and MAIN (pick a forest, clip).
// Every action sends ONE runtime message to the service worker and gets an
// ack back before any network happens — the worker owns the work, storage
// carries the progress, and closing this window never cancels a clip
// (J.15: the click answers immediately; the work happens behind it).
// The popup renders state from 'mkc:last' + the queue via
// chrome.storage.onChanged; it never waits on a pipeline.

import * as api from './api.js';
import * as i18n from './i18n.js';

const FOREST_KEY = 'mkc:forest';
const DESTS_KEY = 'mkc:dests';
const LAST_KEY = 'mkc:last';
const QUEUE_KEY = 'mkc:queue';

const $ = (id) => document.getElementById(id);

// -- i18n: the person's own language, stored with the extension -------------

let lang = 'en';
const t = (key, subs) => i18n.t(lang, key, subs);

async function applyLanguage() {
  lang = await i18n.activeLang();
  for (const el of document.querySelectorAll('[data-i18n]')) {
    el.textContent = t(el.dataset.i18n);
  }
  for (const el of document.querySelectorAll('[data-i18n-ph]')) {
    el.placeholder = t(el.dataset.i18nPh);
  }
  for (const el of document.querySelectorAll('[data-i18n-title]')) {
    el.title = t(el.dataset.i18nTitle);
  }
}

async function buildLangSelect() {
  const select = $('lang');
  select.replaceChildren();
  for (const code of i18n.LANGS) {
    const opt = document.createElement('option');
    opt.value = code;
    opt.textContent = code === 'auto' ? t('langAuto') : i18n.LANG_NAMES[code];
    select.appendChild(opt);
  }
  select.value = await i18n.storedPref();
}

$('lang').addEventListener('change', async () => {
  await i18n.setPref($('lang').value);
  await applyLanguage();
  await buildLangSelect(); // the 'Auto' label itself just changed language
  await renderStatus();    // and so did the status strip's words
});

// -- view switching ----------------------------------------------------------

function show(view) {
  $('view-login').hidden = view !== 'login';
  $('view-main').hidden = view !== 'main';
}

function loginError(message) {
  const el = $('login-error');
  el.textContent = message || '';
  el.hidden = !message;
}

function mainWarning(message) {
  const el = $('main-warning');
  el.textContent = message || '';
  el.hidden = !message;
}

/** One friendly sentence per failure class — the raw envelope is for
 *  debuggers, not for someone typing a password. */
function friendly(e, tokenFlow) {
  if (!e) return t('errNetwork');
  if (e.code === 'E_RATE_LIMITED' || e.status === 429) return t('errRateLimited');
  if (e.status === 401 || e.code === 'E_FORBIDDEN') {
    return tokenFlow ? t('errTokenBad') : t('errUnauthorized');
  }
  if (e.code === 'E_NETWORK') return t('errNetwork');
  return e.hint ? `${e.message} — ${e.hint}` : (e.message || String(e));
}

// -- LOGIN -------------------------------------------------------------------

$('tab-password').addEventListener('click', () => setTab('password'));
$('tab-token').addEventListener('click', () => setTab('token'));

function setTab(which) {
  const pw = which === 'password';
  $('tab-password').classList.toggle('active', pw);
  $('tab-token').classList.toggle('active', !pw);
  $('tab-password').setAttribute('aria-selected', String(pw));
  $('tab-token').setAttribute('aria-selected', String(!pw));
  $('pane-password').hidden = !pw;
  $('pane-token').hidden = pw;
  loginError(null);
}

/** Normalize the origin and get the browser's permission for it — the ONLY
 *  host permission this extension ever asks for (J.15: the server origin at
 *  pairing time, never <all_urls> at install). */
async function preparedOrigin() {
  const origin = api.normalizeOrigin($('origin').value);
  if (!origin) {
    loginError(t('errBadOrigin'));
    return null;
  }
  const granted = await chrome.permissions.request({
    origins: [api.originPattern(origin)],
  });
  if (!granted) {
    loginError(t('errPermission'));
    return null;
  }
  return origin;
}

$('btn-pair').addEventListener('click', async () => {
  loginError(null);
  const origin = await preparedOrigin();
  if (!origin) return;
  const username = $('username').value.trim();
  const password = $('password').value;
  if (!username || !password) {
    loginError(t('errUnauthorized'));
    return;
  }
  $('btn-pair').disabled = true;
  try {
    // J.2.6: the password is a gesture here — it buys the narrowed key and
    // is never stored anywhere.
    const paired = await api.pair(origin, {
      username,
      password,
      label: 'Browser clipper',
    });
    await api.setAccount({
      origin,
      key: paired.api_key,
      principal: paired.principal,
    });
    $('password').value = '';
    await enterMain();
  } catch (e) {
    loginError(friendly(e, false));
  } finally {
    $('btn-pair').disabled = false;
  }
});

$('btn-token').addEventListener('click', async () => {
  loginError(null);
  const origin = await preparedOrigin();
  if (!origin) return;
  const key = $('token').value.trim();
  if (!key) {
    loginError(t('errTokenBad'));
    return;
  }
  $('btn-token').disabled = true;
  try {
    // Probe /v1/me BEFORE saving: a mistyped key stored is a broken main
    // view later, with no hint of why.
    const who = await api.probe(origin, key);
    await api.setAccount({ origin, key, principal: who.principal });
    $('token').value = '';
    await enterMain();
  } catch (e) {
    loginError(friendly(e, true));
  } finally {
    $('btn-token').disabled = false;
  }
});

// -- MAIN --------------------------------------------------------------------

let forestList = [];

async function enterMain() {
  let listed;
  try {
    listed = await api.forests();
  } catch (e) {
    if (e.status === 401 || e.code === 'E_FORBIDDEN') {
      // The key expired or was revoked in People; the pairing must be
      // redone, and pretending otherwise renders dead buttons.
      await api.clearAccount();
      show('login');
      loginError(t('errTokenBad'));
      return;
    }
    show('main');
    mainWarning(friendly(e, false));
    return;
  }

  forestList = listed.forests || [];
  const acct = await api.account();
  $('principal').textContent = acct ? acct.principal : '';

  const select = $('forest');
  select.replaceChildren();
  // Mirrors the server's Policy.grants(): 'admin' implies every capability,
  // so an admin-only grant clips even though 'ingest' is not spelled out.
  // (A pair key never carries admin — this matters for pasted full tokens.)
  const canIngest = (f) =>
    (f.caps || []).includes('ingest') || (f.caps || []).includes('admin');
  const clippable = forestList.filter(canIngest);
  for (const f of forestList) {
    const opt = document.createElement('option');
    opt.value = f.id;
    const ok = canIngest(f);
    opt.textContent = ok ? f.id : `${f.id} — ${t('forestNoIngest')}`;
    opt.disabled = !ok;
    select.appendChild(opt);
  }

  // A pair key holds read+ingest at most, but the mask only narrows: with
  // no ingest grant anywhere the person can look and not clip, and the
  // honest thing is to say that in words rather than gray out eight buttons.
  mainWarning(clippable.length ? null : t('errNoIngest'));
  for (const b of $('actions').querySelectorAll('button')) {
    b.disabled = !clippable.length;
  }

  const stored = await chrome.storage.local.get(FOREST_KEY);
  const remembered = stored[FOREST_KEY];
  if (remembered && clippable.some((f) => f.id === remembered)) {
    select.value = remembered;
  } else if (clippable.length) {
    select.value = clippable[0].id;
    await chrome.storage.local.set({ [FOREST_KEY]: select.value });
  }

  await onForestChange();
  await renderStatus();
  show('main');
}

$('forest').addEventListener('change', async () => {
  await chrome.storage.local.set({ [FOREST_KEY]: $('forest').value });
  await onForestChange();
});

async function onForestChange() {
  const forest = $('forest').value;
  if (!forest) return;

  // Destination: the remembered choice, offered over a datalist of the
  // grant's roots plus the forest root's child branches. Free text stays
  // allowed — the datalist suggests, it never constrains.
  const dests = (await chrome.storage.local.get(DESTS_KEY))[DESTS_KEY] || {};
  $('dest').value = dests[forest] || '';

  const info = forestList.find((f) => f.id === forest);
  const options = new Set();
  for (const root of (info && info.roots) || []) {
    const branch = root.replace(/\/?_index$/, '');
    if (branch) options.add(branch);
  }
  try {
    const scanned = await api.primitive(forest, 'scan', {
      parent_id: '_index',
      filter: { kind: 'branch' },
      fields: ['id'],
      limit: 50,
    });
    for (const node of scanned.nodes || []) {
      const branch = String(node.id || '').replace(/\/?_index$/, '');
      if (branch) options.add(branch);
    }
  } catch {
    // A scoped grant cannot scan the master index (J.3) — the roots above
    // are exactly what such a principal is allowed to see.
  }
  const datalist = $('dest-options');
  datalist.replaceChildren();
  for (const value of [...options].sort()) {
    const opt = document.createElement('option');
    opt.value = value;
    datalist.appendChild(opt);
  }

  const acct = await api.account();
  // Studio opens on ASK: the person leaving the popup for the console is
  // most often carrying a question, not a batch.
  $('open-studio').href = acct
    ? `${acct.origin}/f/${encodeURIComponent(forest)}/ask` : '#';
}

$('dest').addEventListener('change', async () => {
  const forest = $('forest').value;
  if (!forest) return;
  const dests = (await chrome.storage.local.get(DESTS_KEY))[DESTS_KEY] || {};
  dests[forest] = $('dest').value.trim();
  await chrome.storage.local.set({ [DESTS_KEY]: dests });
});

$('open-studio').addEventListener('click', async (ev) => {
  ev.preventDefault();
  const acct = await api.account();
  const forest = $('forest').value;
  if (acct && forest) {
    chrome.tabs.create({
      url: `${acct.origin}/f/${encodeURIComponent(forest)}/ask`,
    });
  }
});

// Ask this forest, from right here: opens Studio's Ask console with the
// question PREFILLED in the address (?q=). Prefilled, never fired — the
// address restores a page, it must not spend a model call (J.5.8); the
// person reviews and presses ask in the console.
async function openAsk() {
  const acct = await api.account();
  const forest = $('forest').value;
  if (!acct || !forest) return;
  const q = $('ask-q').value.trim();
  const suffix = q ? `?q=${encodeURIComponent(q)}` : '';
  chrome.tabs.create({
    url: `${acct.origin}/f/${encodeURIComponent(forest)}/ask${suffix}`,
  });
  $('ask-q').value = '';
  autoGrow($('ask-q'));
}
$('btn-ask').addEventListener('click', openAsk);
$('ask-q').addEventListener('keydown', (ev) => {
  // Enter asks, Shift+Enter breaks the line — the grammar of every chat
  // box, and this box is shaped like one on purpose.
  if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); openAsk(); }
});

/** Height follows the words: the box grows with the text up to a ceiling
 *  and only then scrolls — a popup is short, but a question mid-thought
 *  deserves to be seen whole. */
function autoGrow(el, max = 160) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, max) + 'px';
  el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden';
}
$('ask-q').addEventListener('input', () => autoGrow($('ask-q')));
$('note-text').addEventListener('input', () => autoGrow($('note-text'), 220));

// -- dictating the question ---------------------------------------------------
// The same offscreen pipeline the region picker uses; the worker relays
// everything back here. Four honest states, because the recognizer's
// lifecycle is not a boolean:
//
//   idle → preparing (start sent; the engine takes real time to come
//   alive, and words spoken now are never heard — so the UI must not say
//   "recording" yet) → listening (the engine's own audiostart fired; the
//   seconds start counting) → processing (stop sent; buffered audio is
//   still becoming text, and the late finals are exactly the words that
//   used to get eaten) → idle (stt-end: the box returns, transcript in).

let askMicState = 'idle'; // idle | preparing | listening | processing
let askTickTimer = null;
let askT0 = 0;

function askLive(text) {
  $('ask-live-text').textContent = text;
}

function setAskMicState(state) {
  askMicState = state;
  const busy = state !== 'idle';
  $('ask-q').hidden = busy;
  $('ask-live').hidden = !busy;
  // While the mic runs, the bar is the whole interface: Perguntar only
  // means something once there is a finished question to carry to the
  // console, and a button that cannot act yet is noise beside a timer.
  $('btn-ask').hidden = busy;
  $('ask-mic').classList.toggle('recording', busy);
  $('ask-mic').title = t(busy ? 'dictateStop' : 'dictate');
  if (state !== 'listening') {
    clearInterval(askTickTimer);
    askTickTimer = null;
  }
  if (state === 'preparing') askLive(t('sttPreparing'));
  if (state === 'processing') askLive(t('sttProcessing'));
  if (state === 'idle') {
    const q = $('ask-q');
    autoGrow(q);
    q.focus();
    q.scrollTop = q.scrollHeight;
  }
}

function askStartTicking() {
  askT0 = Date.now();
  const tick = () => {
    const s = Math.floor((Date.now() - askT0) / 1000);
    const mm = Math.floor(s / 60);
    const ss = String(s % 60).padStart(2, '0');
    askLive(t('askListening', [`${mm}:${ss}`]));
  };
  tick();
  clearInterval(askTickTimer);
  askTickTimer = setInterval(tick, 500);
}

function askMicToggle() {
  if (askMicState === 'idle') {
    chrome.runtime.sendMessage({ type: 'mkc:stt-start' }).catch(() => {});
    setAskMicState('preparing');
  } else if (askMicState === 'processing') {
    // Already winding down; a second click is impatience, not a command.
  } else {
    chrome.runtime.sendMessage({ type: 'mkc:stt-stop' }).catch(() => {});
    setAskMicState('processing');
  }
}
$('ask-mic').addEventListener('click', askMicToggle);
$('ask-live').addEventListener('click', askMicToggle);

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg || askMicState === 'idle') return;
  if (msg.type === 'mkc:stt-live') {
    // Restarts after a breath of silence re-fire audiostart; the timer
    // keeps its zero.
    if (askMicState === 'preparing') {
      setAskMicState('listening');
      askStartTicking();
    }
  } else if (msg.type === 'mkc:stt-result' && msg.final && msg.text) {
    const q = $('ask-q');
    q.value = (q.value ? q.value.replace(/\s*$/, ' ') : '') + msg.text;
    if (!q.hidden) autoGrow(q);
  } else if (msg.type === 'mkc:stt-error') {
    setAskMicState('idle');
    if (msg.error === 'not-allowed') mainWarning(t('regionMicDenied'));
  } else if (msg.type === 'mkc:stt-end') {
    setAskMicState('idle');
  }
});

// A popup dies on any blur; a microphone must not outlive the button that
// turned it on. Best-effort — pagehide usually delivers the message.
window.addEventListener('pagehide', () => {
  if (askMicState !== 'idle') {
    chrome.runtime.sendMessage({ type: 'mkc:stt-stop' }).catch(() => {});
  }
});

$('btn-logout').addEventListener('click', async () => {
  // Local discard only: the key row lives on, revocable in Studio → People
  // (J.2.2) — the tooltip says so.
  await api.clearAccount();
  show('login');
});

// -- actions -----------------------------------------------------------------

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

/** Fire one message and move on. The reply is an ACK, not an outcome —
 *  the worker runs the pipeline detached, and the status strip follows it
 *  through storage.session whether this window lives or dies. */
async function dispatch(msg) {
  const forest = $('forest').value;
  if (!forest) {
    mainWarning(t('errNoForest'));
    return;
  }
  mainWarning(null);
  const full = { ...msg, forest, dest: $('dest').value.trim() };
  try {
    await chrome.runtime.sendMessage(full);
  } catch (e) {
    // The channel closing because THIS popup went down first is fine — the
    // worker keeps going and the strip catches up on next open. But while
    // the popup is still visible, a throw here means the message NEVER
    // left (an oversized upload, a worker that failed to wake): swallowing
    // it strands the strip on "Clipping…" forever over work nobody has.
    if (document.visibilityState === 'visible') {
      mainWarning(friendly(e, false));
      setStatusLine('err', t('statusFailed', [(e && e.message) || '']));
    }
  }
}

async function clip(kind) {
  const tab = await activeTab();
  if (!tab) return;
  // Choosing another action folds the quick note away (its draft is
  // already saved — typing is saving); the question box takes the slot
  // back, which is where the outcome will be watched from. A picked file
  // waiting for its note is dropped too — the person chose otherwise.
  closeFileNote();
  pendingUpload = null;
  await closeQuickNote();
  setStatusLine('', t('statusWorking'));
  await dispatch({ type: 'clip', kind, tabId: tab.id });
}

$('act-page').addEventListener('click', () => clip('page'));
$('act-selection').addEventListener('click', () => clip('selection'));
$('act-shot').addEventListener('click', () => clip('shot'));
$('act-both').addEventListener('click', () => clip('both'));

// Region capture: the worker injects the overlay; the popup closes when
// the person clicks the page, which is fine BY DESIGN — the worker owns
// the flow end to end (J.15).
$('act-region').addEventListener('click', () => clip('region'));

// Write: a full tab with room, rich text and dictation (J.15 — a popup
// dies on blur, and the microphone prompt would kill the very note it
// asked to hear).
$('act-write').addEventListener('click', () => {
  chrome.tabs.create({ url: chrome.runtime.getURL('editor.html') });
  window.close();
});

// Quick note: inline title + textarea for one-liners, sent as one compose.
// It BORROWS the question box's slot — the two never stack (the popup is
// small and both are "type here" invitations) — and what was typed is kept
// in session storage, so leaving and coming back finds the thought where
// it was left. Sending, or the browser closing, is what discards it.
const QUICKNOTE_KEY = 'mkc:quicknote';

async function openQuickNote() {
  closeFileNote(); // the two borrow the same slot and never stack
  pendingUpload = null;
  $('ask-block').hidden = true;
  $('note-view').hidden = false;
  const stored = (await chrome.storage.session.get(QUICKNOTE_KEY))[QUICKNOTE_KEY];
  if (stored) {
    $('note-title').value = stored.title || '';
    $('note-text').value = stored.text || '';
    autoGrow($('note-text'), 220);
  }
  $('note-title').focus();
}

async function closeQuickNote({ keepDraft = true } = {}) {
  if ($('note-view').hidden) return;
  if (keepDraft) {
    await chrome.storage.session.set({ [QUICKNOTE_KEY]: {
      title: $('note-title').value, text: $('note-text').value } });
  } else {
    await chrome.storage.session.remove(QUICKNOTE_KEY);
    $('note-title').value = '';
    $('note-text').value = '';
  }
  $('note-view').hidden = true;
  $('ask-block').hidden = false;
}

$('act-note').addEventListener('click', openQuickNote);
$('note-cancel').addEventListener('click', () => closeQuickNote());

// Typing is saving: a popup can die on any blur, and a draft that only
// existed on cancel would not survive the click that killed it.
for (const id of ['note-title', 'note-text']) {
  $(id).addEventListener('input', () => {
    chrome.storage.session.set({ [QUICKNOTE_KEY]: {
      title: $('note-title').value, text: $('note-text').value } });
  });
}

$('note-send').addEventListener('click', async () => {
  const title = $('note-title').value.trim();
  const text = $('note-text').value;
  if (!title || !text.trim()) return;
  setStatusLine('', t('statusWorking'));
  await dispatch({ type: 'compose', title, text });
  await closeQuickNote({ keepDraft: false }); // sent is the one true discard
});

// Upload a file: binary in, base64 out, mode "upload" (J.15 — binaries
// never travel as prose). The file keeps its own name. Between the pick
// and the send there is one breath: an OPTIONAL guidance box — empty, the
// file speaks for itself (a bound vision model reads an image on its own);
// written, the words go as a paired note naming the file, the region
// note's exact shape. The bytes live only in this popup: no session copy
// (they can be 24 MB), so a popup that dies forgets the pick, never the
// forest.
let pendingUpload = null;

$('act-upload').addEventListener('click', () => {
  closeQuickNote();
  $('file-input').click();
});

$('file-input').addEventListener('change', async () => {
  const file = $('file-input').files[0];
  $('file-input').value = '';
  if (!file) return;
  // Chrome caps a runtime message around 64 MB and base64 inflates by
  // 4/3 — past this the sendMessage throws and the file goes nowhere.
  // Refuse it up front with the reason instead.
  if (file.size > 24 * 1024 * 1024) {
    mainWarning(t('errFileTooBig'));
    return;
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  let s = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  pendingUpload = { name: file.name, b64: btoa(s) };
  openFileNote(file.name);
});

function openFileNote(name) {
  closeQuickNote();
  $('ask-block').hidden = true;
  $('file-view').hidden = false;
  $('file-name').textContent = name;
  $('file-note').value = '';
  autoGrow($('file-note'), 180);
  $('file-note').focus();
}

function closeFileNote() {
  if ($('file-view').hidden) return;
  $('file-view').hidden = true;
  $('ask-block').hidden = false;
}

$('file-send').addEventListener('click', async () => {
  if (!pendingUpload) { closeFileNote(); return; }
  const upload = pendingUpload;
  pendingUpload = null;
  const note = $('file-note').value.trim();
  setStatusLine('', t('statusWorking'));
  closeFileNote();
  await dispatch({
    type: 'upload',
    files: [upload],
    label: upload.name,
    ...(note ? { note } : {}),
  });
});

$('file-cancel').addEventListener('click', () => {
  pendingUpload = null;
  closeFileNote();
});

$('file-note').addEventListener('input', () => autoGrow($('file-note'), 180));

// -- status strip ------------------------------------------------------------

function setStatusLine(cls, text) {
  const el = $('status');
  el.className = 'status' + (cls ? ` ${cls}` : '');
  el.textContent = text;
}

// One small voice for "it worked": the strip records, the toast ANNOUNCES.
// Only real transitions speak — the stale state a fresh popup finds in
// storage is history, not news.
let toastTimer = null;
let lastSeen = null;

function toast(cls, text) {
  const el = $('toast');
  el.className = cls;
  el.textContent = text;
  // Force a restyle so back-to-back toasts re-animate.
  void el.offsetWidth;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2600);
}

async function renderStatus() {
  const got = await chrome.storage.session.get([LAST_KEY, QUEUE_KEY]);
  const last = got[LAST_KEY];
  const queue = got[QUEUE_KEY] || [];

  if (!last) {
    setStatusLine('', t('statusIdle'));
  } else if (last.state === 'working') {
    setStatusLine('', t('statusWorking'));
  } else if (last.state === 'planted') {
    setStatusLine('ok', t('statusPlanted', [String(last.id || '')]));
  } else if (last.state === 'job') {
    setStatusLine('', t('statusJob', [String(last.id || '')]));
  } else if (last.state === 'queued') {
    setStatusLine('', t('statusQueued'));
  } else if (last.state === 'failed') {
    setStatusLine('bad', t('statusFailed', [String(last.msg || '')]));
  }

  const seen = JSON.stringify(last || null);
  if (lastSeen !== null && seen !== lastSeen && last) {
    if (last.state === 'planted') {
      toast('ok', '✓ ' + t('statusPlanted', [String(last.id || '')]));
    } else if (last.state === 'failed') {
      toast('bad', '✗ ' + t('statusFailed', [String(last.msg || '')]));
    } else if (last.state === 'queued') {
      toast('', t('statusQueued'));
    }
  }
  lastSeen = seen;

  const note = $('queue-note');
  note.hidden = !queue.length;
  if (queue.length) note.textContent = t('queuePending', [String(queue.length)]);
}

chrome.storage.onChanged.addListener((_changes, area) => {
  if (area === 'session') renderStatus();
});

// -- boot --------------------------------------------------------------------

(async () => {
  // The version beside the name: the manifest is the one source of truth
  // for what is actually running in this browser.
  $('version').textContent = 'v' + chrome.runtime.getManifest().version;
  await applyLanguage();
  await buildLangSelect();
  const acct = await api.account();
  if (acct) {
    await enterMain();
  } else {
    show('login');
  }
})();
