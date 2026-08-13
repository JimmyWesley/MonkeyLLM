// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The extraction half of a clip (spec J.15). Injected on user action only,
// as a classic script in the ISOLATED world, after vendor/Readability.js,
// vendor/turndown.js and vendor/turndown-plugin-gfm.js — the click is the
// consent, and nothing here runs on any page by itself.
//
// This file reads the page and returns markdown; it NEVER talks to the
// Station. Page scripts are subject to the page's CORS and must stay so —
// the one fetch below goes to the page's OWN origin (a YouTube caption
// track), which is exactly what a page context is allowed to do.

(() => {
  if (window.__monkeyClip) return; // re-injection is idempotent

  function turndown() {
    const td = new TurndownService({
      headingStyle: 'atx',
      codeBlockStyle: 'fenced',
      bulletListMarker: '-',
    });
    // GFM pieces we want: tables and strikethrough. Not the whole bundle —
    // task-list items and highlighted code fences add noise a curated
    // passport never earns back.
    td.use([turndownPluginGfm.tables, turndownPluginGfm.strikethrough]);
    return td;
  }

  /** The selection's HTML, serialized through a detached div. Ranges keep
   *  live formatting the plain selection string throws away — a copied
   *  table should still be a table when Turndown is done with it. */
  function selectionMarkdown() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
    const holder = document.createElement('div');
    for (let i = 0; i < sel.rangeCount; i++) {
      holder.appendChild(sel.getRangeAt(i).cloneContents());
    }
    const md = turndown().turndown(holder.innerHTML).trim();
    return md || null;
  }

  /** The readable article, or an honest fallback. Readability mutates the
   *  document it parses, so it always gets a clone — the person is still
   *  reading the original. */
  function pageMarkdown() {
    let article = null;
    try {
      article = new Readability(document.cloneNode(true)).parse();
    } catch {
      // A hostile or bizarre DOM must not kill the clip; the fallback below
      // is what "no readable article" already means.
    }
    if (article && article.content) {
      return {
        title: (article.title || document.title || '').trim(),
        markdown: turndown().turndown(article.content).trim(),
      };
    }
    // No article: title + body text is the floor. innerText respects the
    // page's rendering (hidden nodes stay hidden), which is what the person
    // actually saw.
    return {
      title: (document.title || location.hostname).trim(),
      markdown: (document.body ? document.body.innerText : '').trim(),
    };
  }

  /** json3 caption events → readable transcript lines. One line per cue
   *  with a [m:ss] mark, so a long talk stays scannable and quotable. */
  function transcriptFromJson3(data) {
    const lines = [];
    for (const ev of data.events || []) {
      if (!ev.segs) continue;
      const text = ev.segs.map((s) => s.utf8 || '').join('')
        .replace(/\n/g, ' ').trim();
      if (!text) continue;
      const t = Math.floor((ev.tStartMs || 0) / 1000);
      const m = Math.floor(t / 60);
      const s = String(t % 60).padStart(2, '0');
      lines.push(`[${m}:${s}] ${text}`);
    }
    return lines.join('\n');
  }

  /** A watch page as prose: title, channel, description, and the transcript
   *  when one is reachable. `yt` arrives from a MAIN-world grab of
   *  ytInitialPlayerResponse (the isolated world cannot see page globals);
   *  the caption fetch happens HERE because it is same-origin from the
   *  page's context and from nowhere else the extension runs. */
  async function youtubeMarkdown(yt) {
    const parts = [];
    if (yt.channel) parts.push(`**Channel:** ${yt.channel}`);
    parts.push(`**URL:** ${location.href.split('&')[0]}`);
    if (yt.description) {
      parts.push(`## Description\n\n${yt.description.trim()}`);
    }
    if (yt.captionUrl) {
      // Best-effort by contract: a transcript that cannot be fetched must
      // never fail the clip — the video's passport is still worth planting.
      try {
        const res = await fetch(yt.captionUrl + '&fmt=json3');
        if (res.ok) {
          const transcript = transcriptFromJson3(await res.json());
          if (transcript) parts.push(`## Transcript\n\n${transcript}`);
        }
      } catch {
        // Unreachable track, consent wall, format drift: the clip goes on.
      }
    }
    return {
      title: (yt.title || document.title || '').trim(),
      markdown: parts.join('\n\n').trim(),
    };
  }

  window.__monkeyClip = {
    /** opts: {mode: 'page'|'selection', yt: object|null}.
     *  Returns {title, markdown, url} or {error: 'no-selection'}.
     *  executeScript awaits a returned promise, so this may be async. */
    async run(opts) {
      opts = opts || {};
      if (opts.mode === 'selection') {
        const md = selectionMarkdown();
        if (md === null) return { error: 'no-selection' };
        return {
          title: (document.title || location.hostname).trim(),
          markdown: md,
          url: location.href,
        };
      }
      if (opts.yt) {
        const out = await youtubeMarkdown(opts.yt);
        return { ...out, url: location.href };
      }
      const out = pageMarkdown();
      return { ...out, url: location.href };
    },
  };
})();
