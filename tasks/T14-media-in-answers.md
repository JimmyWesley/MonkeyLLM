status: done (2026-08-13: spec v0.48 amended in place C.6d `view`, J.10.8
reply size, J.10.9 media references, J.10.7 fingerprint fix; engine + Station
+ Studio shipped, F.50/F.51 suites green. Remaining: the user's real-browser
pass and the commit, both theirs.)

# T14 Media in answers: the model shows, the client sees, the reply fits

## Goal

Close the loop the Clipper opened (T13). A screenshot ingested through the
Gardener was findable (describer prose) and visible on a node page (J.14),
but three surfaces still could not use it:

1. **The answer** the model read the description and had no way to hand
   the reader the image itself (or its PDF export).
2. **A multimodal MCP client** a model working over MCP/API could locate
   the media node and never see the pixels (a tutorial screenshot before
   acting on it, a UI print sent as feedback).
3. **The reply size** the only length control was the binding's
   `max_tokens`: per forest, operator-set, enforced as a silent mid-sentence
   cut. The person asking needs it per question.

## What shipped (spec v0.48, amended in place while uncommitted)

- **C.6d `view(id)`** MCP-only tool: the image payload of an in-scope
  media node as an MCP image content block beside a JSON header (`id`,
  `media_type`, `size`, `payload_hash`, never the path). J.14's resolution
  rules verbatim; images only; ≤ 6 MiB (the describer's own cap); traced
  and audited like a read. Engine `Vine.view` + `ScopedVine.view` +
  `vine serve` tool + Station MCP tool. REST refuses the name.
- **J.10.8 `reply_tokens`** per-call override of the binding's
  `max_tokens`, clamped [64, 4000], stated in the prompt (sweep and walk),
  in the J.10.7 key only when set (absent/0 key as before the upgrade).
  Studio: a slider beside "How much to read", persisted per person in
  `monkeyllm.ask.prefs` (localStorage, J.5.3's class never the address).
  MCP `answer` accepts it.
- **J.10.9 `media:` references** `MEDIA_CAVEAT` (sweep) and a
  `FORAGE_SYSTEM` rule (walk) teach `![caption](media:<node id>)`, material
  ids only. Studio's shared `Markdown` gains `media={{forest}}`: the scheme
  resolves after mount through `api.payload` (J.14, viewer's credential);
  failure renders the caption. Evidence items of type `media` render
  `PayloadImage`. PDF export (window.print) includes the images; the `.md`
  export rewrites `media:` to the absolute payload route.
- **J.10.7 fingerprint fix** `notes` now enters the reading fingerprint
  (it is handed to the model since v0.47); an operator editing a dataset's
  notes invalidates the stored answer built without them.

## Acceptance criteria

- [x] F.50: `view` serves bytes equal to disk with the passport's hash;
  dataset → `E_SCHEMA` naming the type; oversize → `E_SCHEMA` naming the
  size; remote → `E_SCHEMA` naming the scheme; out-of-scope, absent and
  payload-less answer one envelope (tests/test_view.py,
  tests/test_station_view.py).
- [x] F.51: `reply_tokens` caps the provider call and is stated; absent is
  byte-identical to before; two sizes are two store entries
  (tests/test_station_reply_budget.py).
- [x] Notes enter the fingerprint; media caveat rides only when media is in
  the bundle; walk prompt carries the rule (same file).
- [x] Full suite green; Studio builds.

## Out of scope

- A vision-capable walk (`view` inside the J.10.5 loop) C.6d.7 names it
  as a possible future, not this task.
- Audio over `view` waits for the transcriber role (G.5.1).
- The Ask console's read-amount options (2/3/6) unchanged; the sweep cap
  remains `MONKEYLLM_HARVEST_MAX_K` (default 5).
