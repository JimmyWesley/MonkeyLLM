// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The dictation host (spec J.15): SpeechRecognition needs a document, the
// service worker has none, and the page under the region overlay must
// never be the one holding the microphone — its origin would collect the
// grant, and many sites forbid it outright via Permissions-Policy. This
// offscreen page runs on the EXTENSION's origin: one grant, made once on
// the visible permission page, covers every later session.
//
// Message contract (direction is encoded in the names):
//   worker → here:  mkc:stt-go {lang} | mkc:stt-halt
//   here → worker:  mkc:stt-result {text, final} | mkc:stt-error {error}
//                   | mkc:stt-end

let recognition = null;
let active = false;

const send = (msg) => chrome.runtime.sendMessage(msg).catch(() => {});

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg) return;
  if (msg.type === 'mkc:stt-go') start(msg.lang || 'en-US');
  if (msg.type === 'mkc:stt-halt') stop();
});

function start(lang) {
  const SR = self.SpeechRecognition || self.webkitSpeechRecognition;
  if (!SR) {
    send({ type: 'mkc:stt-error', error: 'unsupported' });
    return;
  }
  if (active) return; // one session; a second -go is a no-op
  active = true;
  recognition = new SR();
  recognition.lang = lang;
  recognition.continuous = true;
  recognition.interimResults = false; // the overlay appends FINAL text only

  // The recognizer takes real time to come alive — the document may need
  // creating, and the engine does its own handshake. Words spoken before
  // this fires are simply never heard, so the UI must not say "recording"
  // until it does: 'live' is when the microphone is actually capturing.
  recognition.onaudiostart = () => send({ type: 'mkc:stt-live' });

  recognition.onresult = (ev) => {
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      const r = ev.results[i];
      if (r.isFinal) {
        const text = r[0].transcript.trim();
        if (text) send({ type: 'mkc:stt-result', text, final: true });
      }
    }
  };

  recognition.onerror = (ev) => {
    // 'no-speech' is a pause for breath, not a failure; onend restarts.
    if (ev.error === 'no-speech' || ev.error === 'aborted') return;
    active = false;
    send({ type: 'mkc:stt-error', error: ev.error || 'unknown' });
  };

  recognition.onend = () => {
    // Chrome ends recognition on silence; while the session is on, that
    // is not a request to stop.
    if (active) {
      try { recognition.start(); } catch { /* already restarting */ }
    } else {
      send({ type: 'mkc:stt-end' });
    }
  };

  try {
    recognition.start();
  } catch (e) {
    active = false;
    send({ type: 'mkc:stt-error', error: String(e && e.message) || 'start' });
  }
}

function stop() {
  if (!active) {
    send({ type: 'mkc:stt-end' });
    return;
  }
  active = false;
  try { recognition.stop(); } catch { /* already stopped */ }
}
