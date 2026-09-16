<!-- SPDX-License-Identifier: Apache-2.0 -->
# Extending MonkeyLLM

Two different things are called "extending", and keeping them apart is the
whole of this page.

**Configuring** is pointing the product at your model, your embedder, your
storage. It needs no code and is listed at the bottom.

**Extending** is giving a deployment a capability it does not have — a
transcriber, a converter for a format nobody here has heard of, an OCR
pass, a tool your agents can call. That is an **extension** (spec Part L),
and it is what most of this page is about.

`docs/monkeyllm-spec-v0.83.md` is the normative contract; nothing here
overrides it.

---

## Why an extension is not a fork, and not a patch

Every capability above arrives with a dependency, and the dependency is the
problem. FFmpeg is GPL or LGPL depending on how it was built; a document
converter drags a machine-learning stack; a transcriber drags another.
`LICENSING.md` splits this tree Apache-2.0 (engine) / AGPL-3.0-only (host),
and that split holds only while the dependency list stays clean — pinning
any of them would make this project their distributor.

So **this project distributes nothing**. You install what you choose, under
its own licence, which is shown to you before the install completes. The
curated index carries signed *pointers*, never artifacts.

And an extension **contributes at a named seam** — it never patches. That
is not politeness, it is what leaves this project free to refactor: you are
coupled to a seam's published contract, never to the code behind it. An
extension that monkeypatched would break on the next release, and every
release after that would be negotiated with people who did.

## The package

```
manifest.json     identity, compat, permissions, contributions, config
main.py           register(api) — the one activation entry point
worker.py         handlers you marked `heavy` (run in their own process)
ui/panel.json     declarative console contributions
requirements.txt  resolved into the extension's own environment
LICENSE           your licence, shown before the install completes
```

`register(api)` is called once, and every claim is made inside it. The `api`
object is **enumerated**: it exposes what Part L lists and nothing more, so
a new engine capability needs its own line in the spec before an extension
can reach it.

## The seams

There are ten, and the exact shape of each handler is **generated from the
code** rather than written here — a transcribed signature is one that lies
the first time a seam changes. Read yours from your own Station:

- **In the console:** Extensions → *Write an extension* → *Show me how*.
  The same screen hands you a folder (`SKILL.md` + generated references) to
  give your coding agent.
- **Over HTTP:** `GET /v1/extensions/authoring` (JSON), or
  `?as=markdown&doc=seams` for the reference as text.

Briefly, what they are for: `converters` (a file type the deployment could
not read), `curation` (adjust a draft passport), `events` (react to
something that happened), `jobs` (maintenance an operator pulls), `tools`
(a tool for the agents), `routes` (an endpoint under `/v1/ext/<id>/`),
`ranking` and `prompt` (change what an answer is made of — these two are
named in the trace, because an operator comparing a bad answer against a
good one has no other way to learn a third party was between them),
`roles` (a model role you register) and `panel` (your console surface).

## Four rules that will refuse you

1. **A handler must fit its seam.** A parameter the seam does not pass is
   fine if it carries a default and a **failure** if it does not — checked
   at install, by reading your source without importing it. `**kwargs`
   excuses nothing: given `def on_event(event, forrest, **rest)`, `**rest`
   absorbs the `forest` the host passes and `forrest` is still unfilled.
2. **Namespace what you create.** A tool or route named outside your
   extension's namespace refuses the install rather than being renamed
   under you.
3. **You never hold a model key.** Declare a role your extension needs or
   registers; the operator binds it to a provider they already pay for, and
   the host hands you a bound caller. Your spend is metered, capped and
   audited under the person who caused it.
4. **Failing is allowed; failing the act is not.** Anything you raise is
   contained — the ingest falls back to the built-in converter, the batch
   completes, and the report names you.

## Heavy work

Mark a handler `heavy` and it runs in your extension's **own process and
own environment**. That is what keeps the dependency that motivated your
extension out of the process serving the forest, and it is why an
API-backed extension often needs no dependency at all: an HTTP call is
something the host already knows how to make.

A worked example ships in this repository: [`extensions/whisper`](../extensions/whisper)
turns an audio file into a transcript the forest can search, in about 130
lines, with **no `requirements.txt` at all**.

## Installing what you wrote

Five doors, one resolver, and whatever you use it resolves to an immutable
artifact before it is validated:

| Source | How |
|---|---|
| the curated index | `vine ext install whisper` |
| git | `vine ext install github.com/you/ext@v1.0.0` |
| a release archive | `vine ext install https://…/ext-1.0.0.zip` |
| a path on the host | `vine ext install ./ext` |
| **an upload** | the Extensions console — the only door that works from your own machine against a remote Station. Choose the zip, review in place, install; the same act can enable it on the forest you are looking at |

Trust is stated, never implied: `verified` (from the index), `signed` (a
signed git tag checked against the keys your forge publishes for you), or
`unverified` — which an upload always is, because there is nothing behind
it that could have been checked.

A first install is **active at once**: the host loads an id it has never
loaded and says so (`activated: true`). Reinstalling, updating or removing
an extension that is loaded takes effect after the host restarts, because
Python cannot unload a module; the console names what is waiting. Settings
take effect immediately.

What your extension changes shows up where it is used: a converter's file
extensions appear in the ingest console's picker of every forest that
enables it (the host answers `formats`), and a role you register appears
as a card in Models with the `description` you gave it in the manifest —
`{"role": "transcribe", "kind": "transcribe", "description": "…"}` —
shaped by its `kind`, so a transcription binding asks for no reply length.

## Pin to the minor you tested against

The minor is the spec version a release implements and the patch is every
release that cuts no spec — and **while the major is `0`, a patch may
change behaviour**. So pin:

```json
"station_compat": ">=0.83,<0.84"
```

A wider range like `>=0.83,<1.0` is legal and means what it says: *I accept
whatever the next minor does to me*. That is a reasonable bet for a small
surface and an unreasonable one for anything reading a seam closely. Your
own Station prints the range to copy — Extensions → *Write an extension*.
See CONTRIBUTING, "Versions, and what a tag means".

**What validation cannot promise**, said plainly because it matters:
resolving `requirements.txt` executes third-party build code, and a git
source runs the author's build backend. The conformance kit therefore does
not run before third-party code runs — it runs before anything is
**registered**. That is why the signature tier carries more weight than the
kit does.

---

## Configuration, which needs no code

- **Chat model** — any OpenAI-compatible `/v1/chat/completions`
  (llama.cpp, OpenRouter, vLLM, LM Studio). Bound per forest and per role
  in the Models console; see `docs/local-inference.md`.
- **Embedder** — any OpenAI-compatible `/v1/embeddings`, for the optional
  Canopy vector layer. Absent an index and an embedder, `locate` stays
  BM25-only, which is the Phase 0 contract and never a degradation.
- **Ingest converters and curation hooks** without an extension —
  `_meta/gardener.yaml` command hooks and the `monkeyllm.converters` /
  `monkeyllm.hooks` entry points, covered in `docs/ingest-tools.md`. An
  operator's own command hook outranks an extension, deliberately: it is
  the most local statement of intent there is.
- **Remote payload fetchers** — `file://` and `s3://` are built in.
  Adding a scheme means editing `fetch.py`; it is short and
  security-sensitive, so it stays in-tree rather than open to any installed
  package.
- **New UIs and bots** — these are MCP clients, not extensions. The ten
  primitives over MCP are the integration surface.

## Boundaries that do not move without a spec bump

- Primitive semantics, token budgets and truncation contracts.
- The `locate`/`sniff` split — metadata versus bodies, never merged.
- `tend` staying DML-only; `plant`'s declarative schema as the only path to
  a new table.
- **J.3's oracle**: nothing an extension does may disclose that a node
  exists outside its caller's scope.
- Binaries never entering forest git — payloads are referenced, not
  committed.
- A new node `type` or `rel` is declared in the forest's own dialect
  (`_meta/schema.md`), through the seam that exists, never around it.

If a change touches any of the above, the process is: write the spec delta
first (a new `docs/monkeyllm-spec-v0.NN.md`), then implement. The spec is
the truth.
