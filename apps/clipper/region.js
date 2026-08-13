// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The region picker (spec J.15): a floating crop overlay, injected on the
// person's click and gone the moment the choice is made. DRAW a rectangle,
// ADJUST it (move, resize by its eight handles), ANNOTATE it from the
// icon rail beside the selection — arrow, box, pen, text label, undo, the
// LightShot vocabulary — and write or DICTATE a note for the Gardener.
//
// It reports a rectangle (viewport CSS px + devicePixelRatio), the
// annotation VECTORS and the note — never pixels. The service worker
// captures the tab, crops, and composites the annotations onto the crop
// itself: nothing here has to survive into the screenshot, so the whole
// overlay tears down before the capture (the compositing race fix stands).
//
// Dictation runs in the extension's own offscreen document, relayed here
// as final text — the page under this overlay never holds the microphone.
// While it listens, the note box yields to a pulsing listening bar; the
// box returns, transcript inside, the moment the person stops.
//
// Classic script, isolated world, no imports. UI strings arrive through
// `window.__mkcRegionText`, planted by the worker just before this file.

(() => {
  if (window.__mkcRegionActive) return; // one picker at a time
  window.__mkcRegionActive = true;

  const TEXT = Object.assign({
    placeholder: 'Note for the Gardener (optional)',
    capture: 'Capture',
    cancel: 'Cancel',
    adjust: 'Drag the box or its handles to adjust — Esc cancels',
    arrow: 'Arrow',
    rect: 'Box',
    pen: 'Pen',
    text: 'Text',
    undo: 'Undo',
    color: 'Color',
    mic: 'Dictate the note',
    micStop: 'Stop dictating',
    micDenied: 'Allow the microphone once in the tab that just opened, then try again.',
    listening: 'Listening — click to stop',
    preparing: 'Starting the microphone…',
    processing: 'Processing…',
  }, window.__mkcRegionText || {});
  delete window.__mkcRegionText;

  const send = (msg) => {
    try {
      chrome.runtime.sendMessage(msg);
    } catch {
      // The extension was reloaded under us; nothing to report to.
    }
  };

  const MIN = 8;             // px — anything smaller is a click, not a region
  const HANDLE = 10;         // px — the grab squares on the box
  const RED = '#e5484d';     // annotation red, mirrored by the worker
  const GREEN = '#58b788';
  const INK = '#c9d6cd';

  // The annotation colour: LightShot's grammar again — one well on the
  // rail, press it and DRAG along a gradient strip, release and go. Each
  // vector keeps the colour it was drawn with (a blue arrow and a yellow
  // one live in the same shot), and the worker composites per vector.
  // The last pick rides in from storage, planted like the strings.
  const PALETTE = ['#ffffff', '#ffd60a', '#ff9f0a', '#e5484d', '#bf5af2',
                   '#0a84ff', '#64d2ff', '#30d158', '#111111'];
  let annotColor = (typeof window.__mkcRegionColor === 'string'
    && window.__mkcRegionColor) || RED;
  delete window.__mkcRegionColor;

  // -- icons: one visual language, stroke-only, currentColor ---------------

  const ICONS = {
    arrow: '<path d="M6 18 16 8M9 7h8v8"/>',
    rect: '<rect x="4" y="6" width="16" height="12" rx="1.5"/>',
    pen: '<path d="M4 20l1.5-5L16 4.5l3.5 3.5L9 18.5 4 20z"/><path d="M13.5 7l3.5 3.5"/>',
    text: '<path d="M5 7V5h14v2M12 5v14M9 19h6"/>',
    undo: '<path d="M4 9h10a5.5 5.5 0 1 1 0 11h-3"/><path d="M8 5 4 9l4 4"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/>'
      + '<path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/>',
  };

  const iconSvg = (name, size = 16) =>
    `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"`
    + ' stroke="currentColor" stroke-width="1.8" stroke-linecap="round"'
    + ` stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;

  // Everything lives under one root node so cleanup is a single remove.
  // The root itself is transparent: the dim comes from the box's huge
  // box-shadow, which leaves the SELECTED area clear instead of tinting
  // it — what you see inside the border is exactly what will be captured.
  const root = document.createElement('div');
  root.setAttribute('style', [
    'position:fixed', 'inset:0', 'z-index:2147483647',
    'cursor:crosshair', 'background:transparent',
  ].join(';'));

  // Keyframes cannot live in inline styles; one scoped tag, gone with root.
  const styleTag = document.createElement('style');
  styleTag.textContent =
    '@keyframes mkcPulse{0%,100%{opacity:1;transform:scale(1)}'
    + '50%{opacity:0.45;transform:scale(0.8)}}';
  root.appendChild(styleTag);

  const box = document.createElement('div');
  box.setAttribute('style', [
    'position:fixed', 'display:none', `border:1.5px solid ${GREEN}`,
    'box-shadow:0 0 0 200000px rgba(0,0,0,0.35)', 'box-sizing:border-box',
    'background:transparent', 'pointer-events:none',
  ].join(';'));

  const label = document.createElement('div');
  label.setAttribute('style', [
    'position:fixed', 'display:none', 'padding:2px 7px',
    'background:#10241a', 'color:#e6ece7', 'border-radius:4px',
    'font:12px/1.6 system-ui,sans-serif', 'pointer-events:none',
    'white-space:nowrap',
  ].join(';'));

  // The live annotation layer: full-viewport SVG, never interactive — the
  // vectors drawn here are PREVIEW only; the worker re-draws them onto the
  // cropped bitmap, which is what actually ships.
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('style', [
    'position:fixed', 'inset:0', 'width:100%', 'height:100%',
    'pointer-events:none', 'z-index:2147483647',
  ].join(';'));

  // -- the tool rail: icons only, riding the selection's edge --------------

  const rail = document.createElement('div');
  rail.setAttribute('style', [
    'position:fixed', 'display:none', 'flex-direction:column', 'gap:4px',
    'padding:5px', 'background:#10241a', 'border-radius:8px',
    'box-shadow:0 6px 24px rgba(0,0,0,0.4)', 'pointer-events:auto',
    'z-index:2147483647',
  ].join(';'));

  const toolBtnStyle = (on) => [
    'width:30px', 'height:30px', 'display:grid', 'place-items:center',
    'border-radius:6px', 'cursor:pointer', 'padding:0',
    on ? `background:${GREEN};color:#08130d;border:1px solid ${GREEN}`
       : `background:transparent;color:${INK};border:1px solid transparent`,
  ].join(';');

  let activeTool = null; // null | 'arrow' | 'rect' | 'pen' | 'text'
  const toolButtons = {};
  const mkTool = (kind) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.title = TEXT[kind];
    b.innerHTML = iconSvg(kind);
    b.setAttribute('style', toolBtnStyle(false));
    b.addEventListener('click', () => setTool(activeTool === kind ? null : kind));
    toolButtons[kind] = b;
    return b;
  };

  // -- the colour well and its strip ----------------------------------------

  const colorWell = document.createElement('button');
  colorWell.type = 'button';
  colorWell.title = TEXT.color;
  colorWell.setAttribute('style', toolBtnStyle(false));
  const wellDot = document.createElement('span');
  wellDot.setAttribute('style', [
    'width:16px', 'height:16px', 'border-radius:50%',
    `background:${annotColor}`, 'border:2px solid #2c4a3a',
    'box-sizing:border-box', 'pointer-events:none',
  ].join(';'));
  colorWell.appendChild(wellDot);
  rail.appendChild(colorWell);

  const STRIP_W = 16;
  const STRIP_H = 148;
  const strip = document.createElement('div');
  strip.setAttribute('style', [
    'position:fixed', 'display:none', `width:${STRIP_W}px`,
    `height:${STRIP_H}px`, 'border-radius:8px', 'pointer-events:auto',
    'z-index:2147483647', 'cursor:crosshair', 'box-sizing:border-box',
    'border:1px solid rgba(0,0,0,0.45)',
    `background:linear-gradient(${PALETTE.join(',')})`,
    'box-shadow:0 6px 24px rgba(0,0,0,0.4)',
  ].join(';'));

  // The strip is sampled, never guessed: the same gradient painted onto a
  // 1px-wide canvas gives the exact colour under the finger at any point,
  // including the white and black caps a hue formula cannot reach.
  let stripCtx = null;
  function sampleStrip(clientY) {
    if (!stripCtx) {
      const c = document.createElement('canvas');
      c.width = 1;
      c.height = STRIP_H;
      stripCtx = c.getContext('2d', { willReadFrequently: true });
      const g = stripCtx.createLinearGradient(0, 0, 0, STRIP_H);
      PALETTE.forEach((col, i) => g.addColorStop(i / (PALETTE.length - 1), col));
      stripCtx.fillStyle = g;
      stripCtx.fillRect(0, 0, 1, STRIP_H);
    }
    const top = strip.getBoundingClientRect().top;
    const y = clamp(Math.round(clientY - top), 0, STRIP_H - 1);
    const [r, g, b] = stripCtx.getImageData(0, y, 1, 1).data;
    return `rgb(${r},${g},${b})`;
  }

  let colorPick = null; // {from: 'well'|'strip', moved: bool} while pressed
  const stripOpen = () => strip.style.display === 'block';

  function applyColor(c) {
    annotColor = c;
    wellDot.style.background = c;
  }

  function openStrip() {
    const wr = colorWell.getBoundingClientRect();
    const rr = rail.getBoundingClientRect();
    // Beside the rail, away from the selection; flipped when the rail
    // already hugs that edge — same never-off-screen rule as the rail.
    let left = rr.right + 8;
    if (left + STRIP_W > window.innerWidth - 6) left = rr.left - STRIP_W - 8;
    if (left < 6) left = clamp(rr.left, 6, window.innerWidth - STRIP_W - 6);
    strip.style.left = left + 'px';
    strip.style.top = clamp(wr.top - 4, 8,
                            window.innerHeight - STRIP_H - 8) + 'px';
    strip.style.display = 'block';
  }
  function closeStrip() {
    strip.style.display = 'none';
  }

  colorWell.addEventListener('mousedown', (ev) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    ev.stopPropagation();
    if (stripOpen()) { closeStrip(); return; }
    openStrip();
    // The press that opened it may keep going: drag onto the strip, pick,
    // release — one gesture, no second click owed.
    colorPick = { from: 'well', moved: false };
  });
  strip.addEventListener('mousedown', (ev) => {
    if (ev.button !== 0) return;
    ev.preventDefault();
    ev.stopPropagation();
    applyColor(sampleStrip(ev.clientY));
    colorPick = { from: 'strip', moved: false };
  });

  rail.appendChild(mkTool('arrow'));
  rail.appendChild(mkTool('rect'));
  rail.appendChild(mkTool('pen'));
  rail.appendChild(mkTool('text'));

  const btnUndo = document.createElement('button');
  btnUndo.type = 'button';
  btnUndo.title = TEXT.undo;
  btnUndo.innerHTML = iconSvg('undo');
  btnUndo.setAttribute('style', toolBtnStyle(false) + ';opacity:0.5');
  btnUndo.disabled = true;
  rail.appendChild(btnUndo);

  function setTool(kind) {
    if (textInput) commitTextInput();
    closeStrip();
    activeTool = kind;
    for (const [k, b] of Object.entries(toolButtons)) {
      b.setAttribute('style', toolBtnStyle(k === kind));
    }
    // While a tool is armed the region is considered settled: the box and
    // its handles yield the pointer so strokes land on the page area, and
    // the cursor says what the hand does.
    box.style.pointerEvents = kind ? 'none' : 'auto';
    root.style.cursor = kind === 'text' ? 'text' : kind ? 'crosshair' : 'default';
    for (const h of handles) h.style.display = kind ? 'none' : 'block';
  }

  // -- the panel: hint, note (with mic), the two ways out -------------------

  const panel = document.createElement('div');
  panel.setAttribute('style', [
    'position:fixed', 'display:none', 'width:320px', 'padding:10px',
    'background:#10241a', 'border-radius:8px', 'pointer-events:auto',
    'font:12.5px/1.5 system-ui,sans-serif', 'color:#e6ece7',
    'box-shadow:0 6px 24px rgba(0,0,0,0.4)',
  ].join(';'));

  const hint = document.createElement('div');
  hint.textContent = TEXT.adjust;
  hint.setAttribute('style',
    'color:#9fb3a7;font-size:11.5px;margin:0 0 8px;');

  const noteRow = document.createElement('div');
  noteRow.setAttribute('style', 'display:flex;gap:6px;margin:0 0 8px;');

  const note = document.createElement('textarea');
  note.rows = 2;
  note.placeholder = TEXT.placeholder;
  note.setAttribute('style', [
    'flex:1', 'box-sizing:border-box', 'resize:vertical',
    'background:#0b1a13', 'color:#e6ece7', 'border:1px solid #2c4a3a',
    'border-radius:6px', 'padding:6px 8px', 'font:inherit',
    'min-height:38px',
  ].join(';'));

  // The listening bar stands in for the note while the mic is live: a
  // pulsing dot, the promise that a click stops it, and the last phrase
  // heard — the box returns with the whole transcript on stop.
  const listenBar = document.createElement('button');
  listenBar.type = 'button';
  listenBar.setAttribute('style', [
    'flex:1', 'display:none', 'align-items:center', 'gap:8px',
    'background:#0b1a13', `border:1px solid ${RED}`, 'border-radius:6px',
    'padding:6px 10px', 'font:inherit', 'color:#e6ece7', 'cursor:pointer',
    'min-height:38px', 'text-align:left',
  ].join(';'));
  const listenDot = document.createElement('span');
  listenDot.setAttribute('style', [
    'width:9px', 'height:9px', 'border-radius:50%', `background:${RED}`,
    'flex:none', 'animation:mkcPulse 1.1s ease-in-out infinite',
  ].join(';'));
  const listenText = document.createElement('span');
  listenText.textContent = TEXT.listening;
  listenText.setAttribute('style',
    'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
    + 'font-size:12px;color:#9fb3a7;');
  listenBar.appendChild(listenDot);
  listenBar.appendChild(listenText);

  // Four honest states, because the recognizer's lifecycle is not a
  // boolean: 'preparing' until its own audiostart fires (words spoken
  // before that are never heard, so the bar must not claim to record),
  // and 'processing' after stop until stt-end — the late finals arriving
  // there are exactly the words that used to get eaten.
  let micState = 'idle'; // idle | preparing | listening | processing
  const micOn = () => micState !== 'idle';
  const btnMic = document.createElement('button');
  btnMic.type = 'button';
  btnMic.title = TEXT.mic;
  btnMic.innerHTML = iconSvg('mic');
  btnMic.setAttribute('style', toolBtnStyle(false) + ';align-self:flex-start;'
    + 'border-color:#2c4a3a');

  function setMicState(state) {
    micState = state;
    const busy = state !== 'idle';
    btnMic.setAttribute('style', toolBtnStyle(busy) + ';align-self:flex-start;'
      + (busy ? '' : 'border-color:#2c4a3a'));
    btnMic.title = busy ? TEXT.micStop : TEXT.mic;
    note.style.display = busy ? 'none' : 'block';
    listenBar.style.display = busy ? 'flex' : 'none';
    if (state === 'preparing') listenText.textContent = TEXT.preparing;
    if (state === 'listening') listenText.textContent = TEXT.listening;
    if (state === 'processing') listenText.textContent = TEXT.processing;
    if (!busy) {
      note.focus();
      note.scrollTop = note.scrollHeight;
    }
  }

  function toggleMic() {
    if (micState === 'idle') {
      send({ type: 'mkc:stt-start' });
      setMicState('preparing');
    } else if (micState === 'processing') {
      // Already winding down; a second click is impatience, not a command.
    } else {
      send({ type: 'mkc:stt-stop' });
      setMicState('processing');
    }
  }
  btnMic.addEventListener('click', toggleMic);
  listenBar.addEventListener('click', toggleMic);

  noteRow.appendChild(note);
  noteRow.appendChild(listenBar);
  noteRow.appendChild(btnMic);

  const btnRow = document.createElement('div');
  btnRow.setAttribute('style', 'display:flex;gap:8px;justify-content:flex-end;');
  const mkBtn = (text, primary) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = text;
    b.setAttribute('style', [
      'padding:5px 14px', 'border-radius:6px', 'font:inherit',
      'cursor:pointer',
      primary
        ? `background:${GREEN};color:#08130d;border:1px solid ${GREEN};font-weight:600`
        : `background:transparent;color:${INK};border:1px solid #2c4a3a`,
    ].join(';'));
    return b;
  };
  const btnCancel = mkBtn(TEXT.cancel, false);
  const btnCapture = mkBtn(TEXT.capture, true);
  btnRow.appendChild(btnCancel);
  btnRow.appendChild(btnCapture);

  panel.appendChild(hint);
  panel.appendChild(noteRow);
  panel.appendChild(btnRow);

  // Eight grab squares. Their `dir` names which edges they drive.
  const handles = [];
  for (const dir of ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']) {
    const h = document.createElement('div');
    h.dataset.dir = dir;
    const cursor = { n: 'ns', s: 'ns', e: 'ew', w: 'ew',
                     ne: 'nesw', sw: 'nesw', nw: 'nwse', se: 'nwse' }[dir];
    h.setAttribute('style', [
      'position:fixed', 'display:none', `width:${HANDLE}px`,
      `height:${HANDLE}px`, `background:${GREEN}`,
      'border:1.5px solid #0b1a13', 'border-radius:2px',
      'box-sizing:border-box', 'pointer-events:auto',
      `cursor:${cursor}-resize`, 'z-index:2147483647',
    ].join(';'));
    handles.push(h);
    root.appendChild(h);
  }

  root.appendChild(box);
  root.appendChild(svg);
  root.appendChild(label);
  root.appendChild(rail);
  root.appendChild(strip);
  root.appendChild(panel);
  (document.body || document.documentElement).appendChild(root);

  // The worker that waits for this answer is idle-killed after ~30s of
  // silence; a slow, careful adjustment must not outlive it. A heartbeat
  // while the overlay is up keeps it awake — cheap, and it stops with us.
  const heartbeat = setInterval(() => send({ type: 'mkc:region-ping' }), 10000);

  let mode = 'draw';        // 'draw' → 'adjust'
  let rect = null;          // {x, y, w, h} in viewport CSS px
  let startX = 0;
  let startY = 0;
  let dragging = false;     // draw-phase drag
  let moving = null;        // {dx, dy} while the box is dragged
  let resizing = null;      // handle dir while a handle is dragged
  let drawing = null;       // in-flight stroke annotation
  let textInput = null;     // in-flight text label <input>
  let finished = false;
  const annotations = [];   // committed vectors, viewport CSS px

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(v, hi));
  const clampX = (v) => clamp(v, rect.x, rect.x + rect.w);
  const clampY = (v) => clamp(v, rect.y, rect.y + rect.h);

  function normalized(r) {
    return {
      x: Math.min(r.x, r.x + r.w),
      y: Math.min(r.y, r.y + r.h),
      w: Math.abs(r.w),
      h: Math.abs(r.h),
    };
  }

  // -- annotation rendering (preview only) ---------------------------------

  function shapeEl(a) {
    // Each vector keeps the colour it was drawn with; the worker mirrors
    // this exactly when it composites onto the crop.
    const col = a.color || RED;
    let el;
    if (a.kind === 'rect') {
      el = document.createElementNS(SVG_NS, 'rect');
      const n = normalized({ x: a.x, y: a.y, w: a.w, h: a.h });
      el.setAttribute('x', n.x); el.setAttribute('y', n.y);
      el.setAttribute('width', Math.max(1, n.w));
      el.setAttribute('height', Math.max(1, n.h));
      el.setAttribute('rx', 2);
    } else if (a.kind === 'arrow') {
      el = document.createElementNS(SVG_NS, 'g');
      const line = document.createElementNS(SVG_NS, 'line');
      line.setAttribute('x1', a.x1); line.setAttribute('y1', a.y1);
      const angle = Math.atan2(a.y2 - a.y1, a.x2 - a.x1);
      const head = 13;
      line.setAttribute('x2', a.x2 - Math.cos(angle) * head * 0.6);
      line.setAttribute('y2', a.y2 - Math.sin(angle) * head * 0.6);
      const tip = document.createElementNS(SVG_NS, 'polygon');
      tip.setAttribute('points', [
        [a.x2, a.y2],
        [a.x2 - head * Math.cos(angle - 0.42), a.y2 - head * Math.sin(angle - 0.42)],
        [a.x2 - head * Math.cos(angle + 0.42), a.y2 - head * Math.sin(angle + 0.42)],
      ].map((p) => p.join(',')).join(' '));
      tip.setAttribute('fill', col);
      tip.setAttribute('stroke', 'none');
      el.appendChild(line);
      el.appendChild(tip);
    } else if (a.kind === 'text') {
      el = document.createElementNS(SVG_NS, 'text');
      el.setAttribute('x', a.x);
      el.setAttribute('y', a.y);
      el.setAttribute('dominant-baseline', 'text-before-edge');
      el.setAttribute('fill', col);
      el.setAttribute('stroke', 'none');
      el.setAttribute('style',
        'font:600 16px system-ui,sans-serif;user-select:none;');
      el.textContent = a.text;
      return el;
    } else { // pen
      el = document.createElementNS(SVG_NS, 'polyline');
      el.setAttribute('points', a.points.map((p) => p.join(',')).join(' '));
    }
    el.setAttribute('stroke', col);
    el.setAttribute('stroke-width', 3);
    el.setAttribute('fill', a.kind === 'arrow' ? 'none' : 'none');
    el.setAttribute('stroke-linecap', 'round');
    el.setAttribute('stroke-linejoin', 'round');
    return el;
  }

  function renderAnnotations() {
    svg.replaceChildren();
    for (const a of annotations) svg.appendChild(shapeEl(a));
    if (drawing) svg.appendChild(shapeEl(drawing));
    btnUndo.disabled = !annotations.length;
    btnUndo.style.opacity = annotations.length ? '1' : '0.5';
  }

  btnUndo.addEventListener('click', () => {
    annotations.pop();
    renderAnnotations();
  });

  // -- the text label tool ---------------------------------------------------

  function openTextInput(x, y) {
    commitTextInput();
    const input = document.createElement('input');
    input.type = 'text';
    input.setAttribute('style', [
      'position:fixed', `left:${x}px`, `top:${y - 2}px`,
      'background:transparent', `color:${annotColor}`,
      `border:1px dashed ${annotColor}`, 'border-radius:3px',
      'font:600 16px system-ui,sans-serif', 'padding:1px 3px',
      'outline:none', 'min-width:40px', 'width:6ch',
      'pointer-events:auto', 'z-index:2147483647',
    ].join(';'));
    // The label ships in the colour it was opened with, even if the well
    // changes before it is committed — what you see is what lands.
    input.dataset.color = annotColor;
    input.addEventListener('input', () => {
      input.style.width = Math.max(6, input.value.length + 2) + 'ch';
    });
    input.addEventListener('keydown', (ev) => {
      ev.stopPropagation(); // the page AND our own Esc/Enter handlers
      if (ev.key === 'Enter') commitTextInput();
      if (ev.key === 'Escape') discardTextInput();
    });
    input.addEventListener('blur', () => commitTextInput());
    input.addEventListener('mousedown', (ev) => ev.stopPropagation());
    input.dataset.x = x;
    input.dataset.y = y;
    root.appendChild(input);
    textInput = input;
    setTimeout(() => input.focus(), 0);
  }

  // Removing a focused <input> fires its own blur, and blur commits — so
  // both exits release `textInput` BEFORE touching the DOM. Otherwise the
  // blur re-enters, removes the node the outer call is still removing, and
  // the outer remove() throws NotFoundError; Escape was worse still, since
  // the re-entrant commit wrote the very label the discard was refusing.
  function commitTextInput() {
    const input = textInput;
    if (!input) return;
    textInput = null;
    const value = input.value.trim();
    const { x, y } = { x: Number(input.dataset.x), y: Number(input.dataset.y) };
    const color = input.dataset.color;
    input.remove();
    if (value) {
      annotations.push({ kind: 'text', x, y, text: value,
                         color: color || annotColor });
      renderAnnotations();
    }
  }

  function discardTextInput() {
    const input = textInput;
    if (!input) return;
    textInput = null;
    input.remove();
  }

  // -- layout ----------------------------------------------------------------

  function paint() {
    const r = rect;
    box.style.display = 'block';
    box.style.left = r.x + 'px';
    box.style.top = r.y + 'px';
    box.style.width = r.w + 'px';
    box.style.height = r.h + 'px';
    label.style.display = 'block';
    label.textContent = `${Math.round(r.w)} × ${Math.round(r.h)} px`;
    const lx = clamp(r.x, 4, window.innerWidth - 130);
    const ly = r.y > 28 ? r.y - 26 : r.y + r.h + 6;
    label.style.left = lx + 'px';
    label.style.top = ly + 'px';
    if (mode === 'adjust') {
      if (!activeTool) placeHandles(r);
      placeRail(r);
      placePanel(r);
    }
  }

  function placeHandles(r) {
    const half = HANDLE / 2;
    const pos = {
      nw: [r.x, r.y], n: [r.x + r.w / 2, r.y], ne: [r.x + r.w, r.y],
      e: [r.x + r.w, r.y + r.h / 2], se: [r.x + r.w, r.y + r.h],
      s: [r.x + r.w / 2, r.y + r.h], sw: [r.x, r.y + r.h],
      w: [r.x, r.y + r.h / 2],
    };
    for (const h of handles) {
      const [cx, cy] = pos[h.dataset.dir];
      h.style.display = 'block';
      h.style.left = (cx - half) + 'px';
      h.style.top = (cy - half) + 'px';
    }
  }

  /** The rail rides the selection's right edge, LightShot's grammar; when
   *  the selection hugs the viewport's right, it flips to the left, and
   *  it never leaves the screen. */
  function placeRail(r) {
    rail.style.display = 'flex';
    const rw = rail.offsetWidth || 42;
    const rh = rail.offsetHeight || 190;
    let left = r.x + r.w + 10;
    if (left + rw > window.innerWidth - 6) left = r.x - rw - 10;
    if (left < 6) left = clamp(r.x + r.w - rw - 6, 6, window.innerWidth - rw - 6);
    rail.style.left = left + 'px';
    rail.style.top = clamp(r.y, 8, window.innerHeight - rh - 8) + 'px';
  }

  function placePanel(r) {
    panel.style.display = 'block';
    const pw = 320;
    const ph = panel.offsetHeight || 130;
    const left = clamp(r.x, 8, window.innerWidth - pw - 8);
    // Below the box when there is room, above it otherwise, pinned inside
    // the viewport either way — a panel half off-screen is a panel whose
    // Capture button cannot be pressed.
    let top = r.y + r.h + 12;
    if (top + ph > window.innerHeight - 8) top = r.y - ph - 12;
    if (top < 8) top = clamp(r.y + 12, 8, window.innerHeight - ph - 8);
    panel.style.left = left + 'px';
    panel.style.top = top + 'px';
  }

  function enterAdjust() {
    mode = 'adjust';
    root.style.cursor = 'default';
    // The box now takes the pointer, so it can be dragged whole.
    box.style.pointerEvents = 'auto';
    box.style.cursor = 'move';
    paint();
    note.focus();
  }

  // -- lifecycle ---------------------------------------------------------------

  /** Tear the overlay down without reporting anything — the shared tail
   *  of every exit, and what the worker asks for when its wait expires. */
  function teardown() {
    if (micOn()) send({ type: 'mkc:stt-stop' });
    clearInterval(heartbeat);
    window.removeEventListener('keydown', onKey, true);
    window.removeEventListener('mousemove', onWinMove, true);
    window.removeEventListener('mouseup', onWinUp, true);
    try { chrome.runtime.onMessage.removeListener(onDown); } catch { /* gone */ }
    root.remove();
    window.__mkcRegionActive = false;
  }

  /** The overlay removes itself ALWAYS — cancel, confirm, or a listener
   *  throwing mid-gesture. Everything ends by calling finish().
   *
   *  Order is load-bearing: the worker calls captureVisibleTab the moment
   *  the rectangle lands, and captureVisibleTab copies the CURRENT
   *  composited frame — which still shows the dim, the border and the
   *  preview vectors until the renderer commits a frame without them. So
   *  the overlay comes DOWN first (annotations included: the worker
   *  redraws them onto the crop itself), two animation frames put us
   *  after that commit, a small breath covers slow compositors, and only
   *  then does the rectangle leave. */
  function finish(result) {
    if (finished) return;
    finished = true;
    teardown();
    if (!result) {
      send({ type: 'mkc:region-picked', cancelled: true });
      return;
    }
    requestAnimationFrame(() => requestAnimationFrame(() => {
      setTimeout(() => send({ type: 'mkc:region-picked', ...result }), 80);
    }));
  }

  function confirm() {
    commitTextInput(); // a label mid-type is a label meant to ship
    const r = rect && normalized(rect);
    if (r && r.w >= MIN && r.h >= MIN) {
      finish({
        x: r.x, y: r.y, w: r.w, h: r.h,
        devicePixelRatio: window.devicePixelRatio || 1,
        comment: note.value.trim(),
        annotations,
        // The last pick becomes the next session's first colour.
        color: annotColor,
      });
    } else {
      finish(null);
    }
  }

  /** Worker → overlay: teardown on expiry, and the dictation stream. */
  function onDown(msg) {
    if (!msg) return;
    if (msg.type === 'mkc:region-teardown' && !finished) {
      finished = true;
      teardown();
      return;
    }
    if (msg.type === 'mkc:stt-live') {
      // The engine's own audiostart: NOW the microphone hears. Restarts
      // after a breath of silence re-fire it; only the first one moves
      // the state.
      if (micState === 'preparing') setMicState('listening');
      return;
    }
    if (msg.type === 'mkc:stt-result' && msg.final && msg.text) {
      // Final text only, appended where the person left off — dictation
      // writes words, never markup, and never fights the caret. The bar
      // echoes the last phrase so the person knows they were heard.
      note.value = (note.value ? note.value.replace(/\s*$/, ' ') : '')
        + msg.text;
      if (micState === 'listening') listenText.textContent = msg.text;
      return;
    }
    if (msg.type === 'mkc:stt-error') {
      setMicState('idle');
      hint.textContent = msg.error === 'not-allowed'
        ? TEXT.micDenied : TEXT.adjust;
      return;
    }
    if (msg.type === 'mkc:stt-end') {
      setMicState('idle');
    }
  }
  try { chrome.runtime.onMessage.addListener(onDown); } catch { /* no bus */ }

  // -- draw phase -------------------------------------------------------------

  root.addEventListener('mousedown', (ev) => {
    if (ev.button !== 0) return;
    // A press anywhere else puts the palette away; the well and the strip
    // stop their own events before reaching here.
    if (stripOpen()) closeStrip();
    if (mode === 'draw') {
      ev.preventDefault();
      dragging = true;
      startX = ev.clientX;
      startY = ev.clientY;
      rect = { x: startX, y: startY, w: 0, h: 0 };
      paint();
      return;
    }
    if (mode === 'adjust' && activeTool) {
      ev.preventDefault();
      const x = clampX(ev.clientX);
      const y = clampY(ev.clientY);
      if (activeTool === 'text') {
        openTextInput(x, y);
        return;
      }
      drawing = activeTool === 'rect'
        ? { kind: 'rect', x, y, w: 0, h: 0, color: annotColor }
        : activeTool === 'arrow'
          ? { kind: 'arrow', x1: x, y1: y, x2: x, y2: y, color: annotColor }
          : { kind: 'pen', points: [[x, y]], color: annotColor };
      renderAnnotations();
    }
  });

  // -- adjust phase: move the whole box ----------------------------------

  box.addEventListener('mousedown', (ev) => {
    if (ev.button !== 0 || mode !== 'adjust' || activeTool) return;
    ev.preventDefault();
    ev.stopPropagation();
    moving = { dx: ev.clientX - rect.x, dy: ev.clientY - rect.y };
  });

  // -- adjust phase: resize by a handle -----------------------------------

  for (const h of handles) {
    h.addEventListener('mousedown', (ev) => {
      if (ev.button !== 0 || mode !== 'adjust') return;
      ev.preventDefault();
      ev.stopPropagation();
      resizing = h.dataset.dir;
    });
  }

  function onWinMove(ev) {
    if (colorPick) {
      // The pick is live: the well previews every colour the drag crosses,
      // and releasing keeps the one under the finger.
      ev.preventDefault();
      colorPick.moved = true;
      applyColor(sampleStrip(ev.clientY));
      return;
    }
    if (mode === 'draw') {
      if (!dragging) return;
      ev.preventDefault();
      rect = normalized({
        x: startX, y: startY,
        w: ev.clientX - startX, h: ev.clientY - startY,
      });
      paint();
      return;
    }
    if (drawing) {
      ev.preventDefault();
      const x = clampX(ev.clientX);
      const y = clampY(ev.clientY);
      if (drawing.kind === 'rect') {
        drawing.w = x - drawing.x;
        drawing.h = y - drawing.y;
      } else if (drawing.kind === 'arrow') {
        drawing.x2 = x;
        drawing.y2 = y;
      } else {
        const last = drawing.points[drawing.points.length - 1];
        // Thin the stream: a point per ~3px keeps the vector light without
        // visibly changing the stroke.
        if (Math.hypot(x - last[0], y - last[1]) > 3) drawing.points.push([x, y]);
      }
      renderAnnotations();
    } else if (moving) {
      ev.preventDefault();
      rect.x = clamp(ev.clientX - moving.dx, 0, window.innerWidth - rect.w);
      rect.y = clamp(ev.clientY - moving.dy, 0, window.innerHeight - rect.h);
      paint();
    } else if (resizing) {
      ev.preventDefault();
      const x = clamp(ev.clientX, 0, window.innerWidth);
      const y = clamp(ev.clientY, 0, window.innerHeight);
      let { x: rx, y: ry, w, h } = rect;
      const right = rx + w;
      const bottom = ry + h;
      if (resizing.includes('w')) { w = right - x; rx = x; }
      if (resizing.includes('e')) { w = x - rx; }
      if (resizing.includes('n')) { h = bottom - y; ry = y; }
      if (resizing.includes('s')) { h = y - ry; }
      rect = normalized({ x: rx, y: ry, w, h });
      paint();
    }
  }

  function onWinUp(ev) {
    if (colorPick) {
      // A press-drag-release picked and is done; a bare click on the well
      // leaves the strip up for an unhurried second click.
      if (colorPick.from === 'strip' || colorPick.moved) closeStrip();
      colorPick = null;
      return;
    }
    if (mode === 'draw' && dragging) {
      ev.preventDefault();
      dragging = false;
      const r = normalized(rect);
      if (r.w >= MIN && r.h >= MIN) {
        rect = r;
        enterAdjust();  // mouseup ends the DRAW, never the choice
      } else {
        finish(null);   // a click with no drag is a cancel, not a 0×0 crop
      }
      return;
    }
    if (drawing) {
      const keep = drawing.kind === 'pen' ? drawing.points.length > 1
        : drawing.kind === 'arrow'
          ? Math.hypot(drawing.x2 - drawing.x1, drawing.y2 - drawing.y1) >= 6
          : Math.abs(drawing.w) >= 4 && Math.abs(drawing.h) >= 4;
      if (keep) {
        // normalized() rebuilds the rect from coordinates alone — the
        // colour must ride along or the release repaints it in default red.
        annotations.push(drawing.kind === 'rect'
          ? { kind: 'rect', ...normalized(drawing), color: drawing.color }
          : drawing);
      }
      drawing = null;
      renderAnnotations();
      return;
    }
    moving = null;
    resizing = null;
  }
  window.addEventListener('mousemove', onWinMove, true);
  window.addEventListener('mouseup', onWinUp, true);

  // Clicks inside the panel and the rail are their own; without this a
  // mousedown on the textarea would fall through and read as a new draw.
  panel.addEventListener('mousedown', (ev) => ev.stopPropagation());
  rail.addEventListener('mousedown', (ev) => ev.stopPropagation());
  btnCancel.addEventListener('click', () => finish(null));
  btnCapture.addEventListener('click', confirm);

  function onKey(ev) {
    if (ev.key === 'Escape') {
      ev.preventDefault();
      ev.stopPropagation();
      // The nearest undoable thing goes first: an open label, then the
      // palette, then an armed tool, then the picker itself.
      if (textInput) { discardTextInput(); return; }
      if (stripOpen()) { closeStrip(); return; }
      if (activeTool) { setTool(null); paint(); return; }
      finish(null);
    } else if (ev.key === 'Enter') {
      // Inside the note, Enter is a newline and Ctrl/Cmd+Enter captures;
      // anywhere else, Enter captures directly.
      if (ev.target === note && !(ev.ctrlKey || ev.metaKey)) return;
      ev.preventDefault();
      ev.stopPropagation();
      if (mode === 'adjust') confirm();
    }
  }
  // Capture phase: the page must not see — or swallow — the picker's keys.
  window.addEventListener('keydown', onKey, true);
})();
