// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The one visible ask (spec J.15): a microphone prompt cannot render
// inside an offscreen document, so this page asks for the EXTENSION
// origin's grant exactly once. Granted, it closes itself; every later
// dictation session starts silently.

import * as i18n from './i18n.js';

const $ = (id) => document.getElementById(id);

(async () => {
  const lang = await i18n.activeLang();
  const t = (key) => i18n.t(lang, key);
  for (const el of document.querySelectorAll('[data-i18n]')) {
    el.textContent = t(el.dataset.i18n);
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    for (const track of stream.getTracks()) track.stop();
    $('perm-status').textContent = t('permOk');
    setTimeout(() => window.close(), 1200);
  } catch {
    $('perm-status').textContent = t('permDenied');
  }
})();
