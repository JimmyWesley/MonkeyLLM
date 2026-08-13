# MonkeyLLM Clipper

A Manifest V3 browser extension that clips the page you are reading into a
MonkeyLLM forest (spec v0.48, J.15). It is an ordinary client: it speaks the
Station's REST surface and nothing else — no privileged path, nothing in the
engine knows it exists.

What it clips:

- **Page** — the readable article (Readability), converted to Markdown
  (Turndown + GFM tables/strikethrough), sent as one `compose`.
- **Selection** — exactly what you highlighted, HTML-serialized and
  converted, so a copied table is still a table.
- **Screenshot** — the visible tab, downscaled to a describer-sized JPEG and
  sent through `upload` as a media file (a J.9 job).
- **Region** — drag a rectangle over the page (crosshair overlay, live
  dimensions), then adjust it: move the box, resize it by its eight
  handles, **annotate it** from the icon rail riding the selection's
  edge (arrow, box, freehand pen, **text label**, undo — the LightShot
  vocabulary; annotations are vectors the worker composites onto the
  crop itself, razor-sharp at any pixel ratio), and write — or
  **dictate** with the mic button — a note for the Gardener in the
  floating panel. While dictating, the note box yields to a pulsing
  listening bar (click it to stop); the box returns with the transcript
  inside. Enter (or the Capture button) confirms, Esc backs out one
  layer at a time (open label → armed tool → the picker). The note
  becomes its own markdown node naming the screenshot it rode with —
  the same two-nodes shape as "Page + screenshot". The crop is done
  client-side, device-pixel-ratio aware — no pixels leave the tab
  except the chosen rectangle, and what you see inside the border
  (undimmed) is exactly what is captured. The popup closing when you
  click the page is by design: the background worker owns the flow.
  Dictation runs in the extension's own offscreen context — the first
  use opens a small page asking for the microphone ONCE, for the
  extension, never for the site you are clipping.
- **Any image** — right-click an image → "Send image to MonkeyLLM". The
  bytes are read from the page itself; when cross-origin rules bar that,
  the fallback captures the screen region the image occupies — the screen
  never lies. The extension never fetches page-image URLs from its own
  worker (it holds no host permission for them, and asks for none).
- **Page + screenshot** — two nodes, each naming the other in its prose.
- **YouTube watch pages** — title, channel, description, and the transcript
  when a caption track is reachable (best-effort; a missing transcript never
  fails the clip).
- **Notes** — a quick plain-Markdown note in the popup for one-liners, or
  the full **editor tab** (the Write button): a comfortable page with rich
  text (TipTap), a minimal toolbar, per-forest drafts that survive the tab
  closing, and **dictation** through the browser's own speech recognition
  (the button appears only where the browser offers it; the language
  follows your UI language setting). The editor sends through the same
  `compose` pipeline as everything else.
- **Files** — upload a binary as-is.

**Nothing blocks on the server.** Every button sends one message to the
background worker and returns; progress renders from extension storage, so
closing the popup never cancels a clip. Before a `compose`, the worker
checks the forest's job board — a compose against a lane that is mid-batch
would wait, not fail — and queues client-side behind a running batch, the
same client-side queue that catches `E_LOCKED` (the host itself never
queues). The badge and a notification are the completion signal.

Every clip carries its address: composes end with a `Source:` line and
uploads carry `source_url` (the page URL, tracking parameters stripped) —
a clip nobody can trace back to its page is a citation with no cite.

## Keyboard shortcuts

Three commands ship with suggested keys — `Alt+Shift+M` opens the popup,
`Alt+Shift+P` clips the page, `Alt+Shift+R` captures a region. Chrome
applies a suggestion **only if nothing else already uses it** (a clash
resolves to "unassigned", never to a stolen key), and every binding is
yours to change at `chrome://extensions/shortcuts`. Pressing a shortcut
is a user gesture like clicking the icon: it grants the same `activeTab`
consent and clips into the forest and branch last chosen in the popup.

## UI language

The popup and the editor speak your choice of **English, Português or
Español** — the selector sits in the popup's footer and on the editor page,
and the default follows the browser. The setting is stored with the
extension (`i18n.js` holds the three dictionaries); notifications read it
before formatting. Only the manifest's name/description stay on the
platform's `_locales` mechanism, as the platform requires.

Dictionary parity is checked with one line (run from `apps/clipper/`):

```sh
node --input-type=module -e "import('./i18n.js').then(m => { const ks = Object.keys(m.MESSAGES.en).sort().join(','); for (const l of ['pt','es']) if (Object.keys(m.MESSAGES[l]).sort().join(',') !== ks) { console.error('key mismatch:', l); process.exit(1); } console.log('en/pt/es keys match'); })"
```

## Licensing

This directory (`apps/clipper/`) is **AGPL-3.0-only**, like the rest of the
host (see `LICENSING.md` at the repository root). The engine
(`src/monkeyllm/`) stays Apache-2.0; the host may import the engine, never
the other way around. Vendored libraries keep their own licenses (below).

## Install (Chrome / Edge / Brave)

1. Grab the build: every Station serves it at `{origin}/clipper.zip`,
   and Studio offers the same download on the sidebar rail ("Get the
   Clipper") — unzip it anywhere. Working from the repository,
   `apps/clipper` itself is the build.
2. Open `chrome://extensions`.
3. Turn on **Developer mode** (top right).
4. Click **Load unpacked** and pick the unzipped folder (or this
   directory).
5. Pin the monkey to the toolbar if you like.

## Pairing

The Clipper stores a server origin and a paired key — never your password.

1. Click the Clipper icon. You land on the pairing screen.
2. Enter your Station's origin, e.g. `https://station.example.com`.
3. Either sign in with **username & password** — the Clipper calls
   `POST /v1/auth/pair` (spec J.2.6), which mints a clip-only key
   (`read` + `ingest`, expiring, revocable in Studio → People) — or paste a
   key you already hold under **Paste a token**.
4. The browser will ask to grant the extension access to that one origin.
   That is the only host permission the Clipper ever requests: it is asked
   for at pairing time, for the server you named, never `<all_urls>` at
   install.
5. Pick a forest and (optionally) a destination branch. Clip away.

**Log out** discards the key from the browser. Revoking it for real happens
on the server, in Studio → People, where every key lives.

## Packaging

```sh
cd apps/clipper && zip -r ../clipper.zip . -x 'node_modules/*'
```

Load the zip through a store dashboard, or keep loading the directory
unpacked — the server ships no per-user binary; pairing replaces any
baked-in URL.

## Vendored libraries

| File | Project | License |
|---|---|---|
| `vendor/Readability.js` | Mozilla Readability | Apache-2.0 (`vendor/Readability.LICENSE`) |
| `vendor/turndown.js` | Turndown | MIT (`vendor/turndown.LICENSE`) |
| `vendor/turndown-plugin-gfm.js` | Turndown GFM plugin | MIT (`vendor/turndown-plugin-gfm.LICENSE`) |
| `vendor/tiptap.js` | TipTap (+ StarterKit, Placeholder) | MIT (`vendor/tiptap.LICENSE`) |

Readability/Turndown are loaded only by injection into the page you are
clipping, on your click; TipTap (and Turndown again) load in the
extension's own editor tab. The extension has no content scripts declared
and runs on no page by itself — the region picker (`region.js`) is likewise
injected only on your click and removes itself when the choice is made.

## Firefox

Firefox supports MV3 and this extension is close to portable: the manifest
needs `browser_specific_settings.gecko`, and Firefox handles
`background.service_worker` differently (it prefers `background.scripts`).
`SpeechRecognition` is absent there, so the dictation button simply does
not render. Both manifest items are minor tweaks; shipping them is out of
scope here.
