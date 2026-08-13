// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The writing tab (spec J.15): room, rich text and dictation, sending
// through the SAME compose pipeline as every other clip. A popup dies on
// blur — and the microphone permission prompt is a blur — so writing
// happens here, in a page that survives its own tools.
//
// TipTap (vendor/tiptap.js, IIFE → window.TipTap) is the editing surface;
// what leaves this page is markdown, produced by Turndown from the
// editor's HTML, handed to the service worker as ONE 'compose' message.
// The worker acks immediately and owns the send — its E_LOCKED queue, its
// badge, its notification — so closing this tab after Send loses nothing.

import * as api from './api.js';
import * as i18n from './i18n.js';

const FOREST_KEY = 'mkc:forest';
const DESTS_KEY = 'mkc:dests';
const DRAFTS_KEY = 'mkc:drafts';

const $ = (id) => document.getElementById(id);
const { Editor, StarterKit, Placeholder } = window.TipTap;

// -- i18n --------------------------------------------------------------------

let lang = 'en';
let langPref = 'auto';
const t = (key, subs) => i18n.t(lang, key, subs);

async function applyLanguage() {
  langPref = await i18n.storedPref();
  lang = i18n.resolveLang(langPref);
  document.title = t('editorPageTitle');
  for (const el of document.querySelectorAll('[data-i18n]')) {
    el.textContent = t(el.dataset.i18n);
  }
  for (const el of document.querySelectorAll('[data-i18n-ph]')) {
    el.placeholder = t(el.dataset.i18nPh);
  }
  for (const el of document.querySelectorAll('[data-i18n-title]')) {
    el.title = t(el.dataset.i18nTitle);
  }
  for (const el of document.querySelectorAll('[data-i18n-aria]')) {
    el.setAttribute('aria-label', t(el.dataset.i18nAria));
    el.title = t(el.dataset.i18nAria);
  }
  if (recognition) recognition.lang = i18n.speechLang(langPref);
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
  select.value = langPref;
}

$('lang').addEventListener('change', async () => {
  await i18n.setPref($('lang').value);
  await applyLanguage();
  await buildLangSelect();
  if (editor) {
    // The Placeholder extension reads its option lazily (it is a function
    // below); an empty transaction makes it repaint in the new language.
    editor.view.dispatch(editor.state.tr);
  }
});

function pageWarning(message) {
  const el = $('page-warning');
  el.textContent = message || '';
  el.hidden = !message;
}

// -- the editor ---------------------------------------------------------------

let editor = null;

function buildEditor(content) {
  return new Editor({
    element: $('editor'),
    extensions: [
      StarterKit,
      Placeholder.configure({
        // A function, so a live language switch changes the hint without
        // rebuilding the editor.
        placeholder: () => t('editorPlaceholder'),
      }),
    ],
    content: content || '',
    onUpdate: () => scheduleDraftSave(),
    onTransaction: () => paintToolbar(),
  });
}

// -- toolbar -------------------------------------------------------------------

const TOOLS = [
  ['tb-h2', (c) => c.toggleHeading({ level: 2 }), (e) => e.isActive('heading', { level: 2 })],
  ['tb-bold', (c) => c.toggleBold(), (e) => e.isActive('bold')],
  ['tb-italic', (c) => c.toggleItalic(), (e) => e.isActive('italic')],
  ['tb-bullet', (c) => c.toggleBulletList(), (e) => e.isActive('bulletList')],
  ['tb-ordered', (c) => c.toggleOrderedList(), (e) => e.isActive('orderedList')],
  ['tb-code', (c) => c.toggleCodeBlock(), (e) => e.isActive('codeBlock')],
  ['tb-quote', (c) => c.toggleBlockquote(), (e) => e.isActive('blockquote')],
];

for (const [id, run] of TOOLS) {
  $(id).addEventListener('click', () => {
    if (!editor) return;
    run(editor.chain().focus()).run();
  });
}

function paintToolbar() {
  if (!editor) return;
  for (const [id, , active] of TOOLS) {
    $(id).classList.toggle('active', Boolean(active(editor)));
  }
}

// -- drafts: autosaved per forest, so a closed tab loses nothing --------------

let currentForest = '';
let draftTimer = null;

async function readDrafts() {
  return (await chrome.storage.local.get(DRAFTS_KEY))[DRAFTS_KEY] || {};
}

function scheduleDraftSave() {
  clearTimeout(draftTimer);
  draftTimer = setTimeout(saveDraft, 600);
}

async function saveDraft() {
  if (!currentForest || !editor) return;
  const drafts = await readDrafts();
  const title = $('title').value;
  const html = editor.getHTML();
  if (!title.trim() && editor.isEmpty) {
    delete drafts[currentForest]; // an emptied draft is a discarded one
  } else {
    drafts[currentForest] = { title, html, at: Date.now() };
  }
  await chrome.storage.local.set({ [DRAFTS_KEY]: drafts });
  const note = $('draft-note');
  note.hidden = false;
  setTimeout(() => { note.hidden = true; }, 2000);
}

async function loadDraft(forest) {
  const drafts = await readDrafts();
  const draft = drafts[forest] || null;
  $('title').value = (draft && draft.title) || '';
  if (editor) editor.commands.setContent((draft && draft.html) || '');
}

async function clearDraft(forest) {
  const drafts = await readDrafts();
  delete drafts[forest];
  await chrome.storage.local.set({ [DRAFTS_KEY]: drafts });
}

$('title').addEventListener('input', scheduleDraftSave);

// A tab closed mid-thought: one last synchronous-ish save attempt. The
// debounce above means at most ~600ms of typing could be at risk.
window.addEventListener('beforeunload', () => { saveDraft(); });

// -- pickers: the same data the popup uses ------------------------------------

let forestList = [];

async function loadForests() {
  let listed;
  try {
    listed = await api.forests();
  } catch (e) {
    pageWarning(e && e.code === 'E_NOT_PAIRED'
      ? t('notifPairFirst')
      : (e && e.hint ? `${e.message} — ${e.hint}` : (e && e.message) || t('errNetwork')));
    $('btn-send').disabled = true;
    return;
  }
  forestList = listed.forests || [];
  const canIngest = (f) =>
    (f.caps || []).includes('ingest') || (f.caps || []).includes('admin');
  const clippable = forestList.filter(canIngest);

  const select = $('forest');
  select.replaceChildren();
  for (const f of forestList) {
    const opt = document.createElement('option');
    opt.value = f.id;
    opt.textContent = canIngest(f) ? f.id : `${f.id} — ${t('forestNoIngest')}`;
    opt.disabled = !canIngest(f);
    select.appendChild(opt);
  }
  pageWarning(clippable.length ? null : t('errNoIngest'));
  $('btn-send').disabled = !clippable.length;

  const stored = await chrome.storage.local.get(FOREST_KEY);
  const remembered = stored[FOREST_KEY];
  if (remembered && clippable.some((f) => f.id === remembered)) {
    select.value = remembered;
  } else if (clippable.length) {
    select.value = clippable[0].id;
  }
  await onForestChange(false);
}

$('forest').addEventListener('change', async () => {
  await chrome.storage.local.set({ [FOREST_KEY]: $('forest').value });
  await onForestChange(true);
});

async function onForestChange(switching) {
  const forest = $('forest').value;
  if (!forest) return;
  if (switching && currentForest && currentForest !== forest) {
    // The unsent words follow their forest, not the dropdown.
    await saveDraft();
  }
  currentForest = forest;
  await loadDraft(forest);

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
    // A scoped grant cannot scan the master index (J.3); the roots above
    // are exactly what such a principal may see.
  }
  const datalist = $('dest-options');
  datalist.replaceChildren();
  for (const value of [...options].sort()) {
    const opt = document.createElement('option');
    opt.value = value;
    datalist.appendChild(opt);
  }

  const acct = await api.account();
  $('open-studio').href = acct
    ? `${acct.origin}/f/${encodeURIComponent(forest)}/ingest` : '#';
}

$('dest').addEventListener('change', async () => {
  const forest = $('forest').value;
  if (!forest) return;
  const dests = (await chrome.storage.local.get(DESTS_KEY))[DESTS_KEY] || {};
  dests[forest] = $('dest').value.trim();
  await chrome.storage.local.set({ [DESTS_KEY]: dests });
});

// -- dictation: the browser's own speech facilities (J.15) --------------------

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let micOn = false;

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Final speech lands at the caret as PLAIN text — dictation writes words,
 *  never markup. */
function insertSpoken(text) {
  if (!editor || !text) return;
  editor.chain().focus().insertContent(escapeHtml(text)).run();
}

if (SR) {
  const micBtn = $('tb-mic');
  micBtn.hidden = false;

  recognition = new SR();
  recognition.continuous = true;
  recognition.interimResults = true;

  recognition.onresult = (ev) => {
    let interim = '';
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const result = ev.results[i];
      if (result.isFinal) {
        insertSpoken(result[0].transcript.trim() + ' ');
      } else {
        interim += result[0].transcript;
      }
    }
    const ghost = $('ghost');
    ghost.textContent = interim;
    ghost.hidden = !interim;
  };

  recognition.onend = () => {
    // Chrome ends recognition on silence; while the toggle is on, that is
    // a pause for breath, not a request to stop.
    if (micOn) {
      try { recognition.start(); } catch { /* already restarting */ }
    } else {
      $('ghost').hidden = true;
    }
  };

  recognition.onerror = (ev) => {
    if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed') {
      micOn = false;
      micBtn.classList.remove('recording');
      micBtn.setAttribute('aria-label', t('dictate'));
      $('ghost').hidden = true;
    }
  };

  micBtn.addEventListener('click', () => {
    micOn = !micOn;
    micBtn.classList.toggle('recording', micOn);
    micBtn.setAttribute('aria-label', t(micOn ? 'dictateStop' : 'dictate'));
    micBtn.title = t(micOn ? 'dictateStop' : 'dictate');
    if (micOn) {
      recognition.lang = i18n.speechLang(langPref);
      try { recognition.start(); } catch { /* already running */ }
    } else {
      recognition.stop();
      $('ghost').hidden = true;
    }
  });
}
// No SpeechRecognition (Firefox, some builds): the button stays hidden —
// feature-detected, never greyed out with no explanation.

// -- send ----------------------------------------------------------------------

function markdownOf(html) {
  const td = new TurndownService({
    headingStyle: 'atx',
    codeBlockStyle: 'fenced',
    bulletListMarker: '-',
  });
  td.use([turndownPluginGfm.tables, turndownPluginGfm.strikethrough]);
  return td.turndown(html).trim();
}

$('btn-send').addEventListener('click', async () => {
  const forest = $('forest').value;
  if (!forest) {
    pageWarning(t('errNoForest'));
    return;
  }
  const title = $('title').value.trim();
  const text = editor ? markdownOf(editor.getHTML()) : '';
  if (!title || !text) {
    pageWarning(t('errNeedTitleText'));
    return;
  }
  pageWarning(null);

  if (micOn) $('tb-mic').click(); // a send ends the dictation session

  // ONE message to the worker — the same door every clip goes through.
  // The reply is an ack; the compose (and any E_LOCKED queueing) is the
  // worker's from here, notification included.
  try {
    await chrome.runtime.sendMessage({
      type: 'compose',
      forest,
      dest: $('dest').value.trim(),
      title,
      text,
    });
  } catch {
    // The worker was mid-restart; the message API will have woken it, but
    // without an ack we cannot claim the note left. Keep the draft.
    pageWarning(t('errNetwork'));
    return;
  }

  // The sent note must not resurrect as a draft: the 600ms debounce may
  // still be pending, and beforeunload fires saveDraft on the way out —
  // both would re-save what was just cleared. Cancel the timer and empty
  // the fields, so any late save finds nothing and (per saveDraft's own
  // rule) discards rather than writes. Send it again from the sent view
  // and you would plant a duplicate node.
  clearTimeout(draftTimer);
  draftTimer = null;
  $('title').value = '';
  if (editor) editor.commands.clearContent();
  await clearDraft(forest);
  $('view-write').hidden = true;
  $('view-sent').hidden = false;
});

$('btn-again').addEventListener('click', () => {
  $('title').value = '';
  if (editor) editor.commands.clearContent();
  $('view-sent').hidden = true;
  $('view-write').hidden = false;
  editor.commands.focus();
});

// -- boot -----------------------------------------------------------------------

(async () => {
  await applyLanguage();
  await buildLangSelect();
  editor = buildEditor('');
  await loadForests();
  paintToolbar();
})();
