status: in-progress (2026-09-13: v0.80 SHIPPED to PyPI; v0.81 adds the
author's door — uploaded archives, declared seam contracts checked by the
kit, and the L.16 authoring surface. Remaining: F.194's gpg measurement,
the curated index, and the console's browser pass.)

# T18 Extensions: third-party modules, installed by the operator

## Goal

Let somebody who is not this project add a capability — a Whisper
transcriber, a Docling converter, an FFmpeg thumbnailer, an OCR pass, a
connector to a system nobody here has heard of — from a zip, without a single
one of those dependencies entering this repository.

It has to work on both hosts this product has: a Station driven from the
Studio, and a bare `pip install monkeyllm` driven from the `vine` CLI.

The shape is a browser extension written in Python: one package that carries
its backend module **and** its console surface, declares what it contributes,
and is installed, enabled, disabled and removed by the operator.

## Why now: the licensing thesis

`LICENSING.md` splits the tree Apache-2.0 (engine) / AGPL-3.0-only (host) and
the split only holds while the dependency list stays clean. FFmpeg is
GPL-or-LGPL depending on the build, Docling drags a machine-learning stack,
Whisper drags another; pinning any of them in `pyproject.toml` makes this
project a distributor of them.

An extension moves the decision to the operator. **This project never
distributes an extension's bytes** — not even from the curated registry,
which hosts a signed *index* pointing at somebody else's release. What the
operator installs on their own machine is their act, under the extension's
own licence, declared in its manifest and shown before the install completes.

## Decisions taken (2026-09-07)

| # | Decision | Cost accepted |
|---|---|---|
| 1 | **In-process Python module** for registration (hooks, precedence, config, UI contributions) | Extension code runs with the Station's authority; the trust controls below are what stands between that and the operator |
| 2 | **Own venv per extension; declared heavy functions run in a worker** | Two ways to write code in one package; the author must mark what is heavy |
| 3 | **Contribution with precedence, never monkeypatch** | An extension cannot reach a seam this project did not name; new seams need a spec bump |
| 4 | **Every layer open**: ingest, events/jobs, host surface (MCP tools, REST routes, Studio panel), retrieval/answer | The retrieval seam can degrade the product invisibly — it MUST be named in the Part D trace |
| 5 | **Declarative UI**: the manifest describes, Studio renders with its own components | The vocabulary grows release by release; an author cannot draw anything Studio has no component for |
| 6 | **Installed globally by the owner, enabled per forest by that forest's admin** | Two authorities, two screens |
| 7 | **Enabled on a forest ⇒ published on that forest** — no second opt-in control | A key reaching several forests sees the union of their extension tools |
| 8 | **Config and secrets in the registry, J.10.2 custody** | The extension declares a config schema; it cannot store an arbitrary blob |
| 9 | **Restart required to install AND to remove** | Service interruption per change; in exchange, process state always equals the register |
| 10 | **Uninstall touches nothing in the forest; config is quarantined** | An undeclared `type` starts being refused by A.2 — the console must say so *before* confirming; quarantined secrets need an expiry and a screen |
| 11 | **Models by role, never by key**: consumes existing roles, may register a new one | A registered role needs a `kind` to say which API shape it speaks |
| 12 | **Quota per extension per forest, refusal on exhaustion** | A badly calibrated ceiling breaks legitimate ingest mid-batch |
| 13 | **Audit keeps the human principal and adds `via: ext:<id>`** | One nullable column in J.4.2; a pre-L row reads it as absent |
| 18 | **A moving ref is allowed and marked `tracking`** | Two deployments running "the same extension" can be running different code; the console must show the ref, not only the id |
| 19 | **Signature = a signed git tag verified against the keys the forge publishes for the author's account** | Identity is delegated to the forge: a compromised account is a compromised extension, and verification needs network to the forge at install time |
| 16 | **Four install sources, one resolver** — curated id, git URL, release archive, local zip — all resolved to an immutable artifact before validation | A git install needs egress from the host; the local-zip route stays for air-gapped deployments |
| 17 | **A contribution the host cannot serve is inert and named, never an error** | The config schema, not the panel, is the source of truth for settings — the kit fails an extension that cannot be configured without a console |
| 15 | **The mechanism is the engine's, the governance is the Station's** — a `pip install monkeyllm[extensions]` user installs extensions from the CLI | Venv management and subprocess supervision enter the Apache package; kept behind an optional extra so a library embedder does not pay for it |
| 14 | **All four trust controls in v1**: conformance kit, declared permissions, signature + curated registry, operator sovereignty | Signature and index infrastructure before the first third-party extension exists |

## Where the mechanism lives

Part J calls the Station a *privileged client* of the engine — "the engine
gains nothing, loses nothing" — and extensions are not the exception. The
**mechanism** is the engine's; the **governance** is the Station's, exactly
the cut that already separates `Vine` from `ScopedVine`.

| Engine (Apache, extra `monkeyllm[extensions]`) | Station (AGPL) |
|---|---|
| manifest schema, signature verification | owner/admin authority |
| conformance kit (runs against `forests/forest-fixture`) | secret custody (J.10.2) |
| venv resolution, loader, `register(api)` | per-forest quota |
| seam precedence, worker protocol | `via:` in the J.4.2 audit row |
| `vine ext install/list/enable/disable/remove` | Studio console, curated index |

The two levels map onto both hosts:

- **Global install** → `~/.monkeyllm/extensions/<id>/` for the CLI, the data
  directory for the Station. **Never `_derived/`**, which is disposable and
  which `vine reindex` is entitled to delete.
- **Per-forest enablement** → a line in `_meta/extensions.yaml`, which is
  git-tracked (`forest.py`). The forest therefore carries **which extensions
  it expects**, the snapshot takes them along, and `vine validate` can say
  *"this forest expects `whisper` and it is not installed"* instead of quietly
  converting an `.mp3` with the built-in stub.

What a pip-only operator does **not** get, and why it is correct that they do
not:

1. **Secret custody.** There is no registry. Keys come from the environment,
   which is what the engine already does for endpoint, model and API key.
   `_meta/` is versioned, so non-secret config may live there and a **secret
   never may** — the loader refuses a config file carrying a declared secret
   field.
2. **Quota.** They are spending their own key directly; there is nobody to
   protect from whom.
3. **`via:` in an audit row.** The engine has the Part D trace, not an access
   log. The extension is named in the trace instead — which F.184 already
   requires.
4. **The owner/admin split.** They are the operator; sovereignty is
   trivially satisfied.

Two properties fall out for free: **the mandatory restart costs the CLI
nothing** (every invocation is already a fresh process), and a proprietary
extension in a pip-only deployment sits in a **pure Apache-2.0 context** — the
cleanest licensing case this design produces.

The `monkeyllm.converters` / `monkeyllm.hooks` entry points stay for
compatibility, but the zip is the better route even for a CLI operator: pip
puts every extension in one interpreter, which is the dependency conflict this
whole design exists to avoid.

## Install sources

Community extensions live where their authors live, so a zip upload cannot be
the only door. Four sources, one resolver:

| Source | Form |
|---|---|
| curated index | `vine ext install whisper` |
| git | `vine ext install github.com/org/monkeyllm-whisper@v1.2.0` |
| release archive | `vine ext install https://.../whisper-1.2.0.zip` |
| local file | `vine ext install ./whisper-1.2.0.zip` |

**Whatever the source, it resolves to an immutable artifact before anything is
validated.** A git ref resolves to a commit SHA and the **SHA** is what the
install record holds: a tag can be force-pushed and a branch moves nightly, so
"the thing that was signed" has to be the thing that runs. `@v1.2.0` means
*the SHA that tag pointed at when this operator installed*.

The git source is also what makes `vine ext update <id>` meaningful: re-resolve
the ref, re-run the kit, and leave the current install untouched if it fails.

**A moving ref is allowed and marked.** `@main` installs, records the SHA it
resolved to, and carries `tracking: main` in the install record — an author
developing an extension should not have to cut a release per test. Every
surface that names the extension names the ref beside it, because "the same
extension" on two deployments is then not the same code. Being *behind* costs
a fetch, so it is reported by `vine ext outdated` on demand and never by
`list`, which must stay an offline call.

### Trust tiers

An arbitrary git URL is in direct tension with "signature + curated registry".
The resolution is to make the posture explicit rather than to pick one:

| Tier | Meaning |
|---|---|
| `verified` | id from the curated index; the index carries the expected signing identity and the artifact matches it |
| `signed` | git source at a **signed tag**, verified against the public keys the forge publishes for the author's account (GitHub first; GitLab the same shape) |
| `unverified` | everything else — unsigned tags, tracked branches, plain archives, local zips |

Two consequences fall out rather than being decided:

- **A tracked branch is `unverified` by construction.** A branch carries no
  tag, so there is nothing to verify; the tier says it without a rule of its
  own.
- **`signed` needs the network at install time**, because the keys live at the
  forge. An air-gapped deployment installing from a local zip reaches
  `unverified` or `verified` (index-carried identity), never `signed`.

Identity is delegated to the forge, and that is the cost of not running a key
infrastructure: **a compromised GitHub account is a compromised extension**.
The cheap hardening that keeps the choice intact is to record *which* identity
verified an install — account login plus key fingerprint — and surface a
change on update rather than accepting it silently. Repo transfers and key
rotations become visible without anybody maintaining a keyring.

The tier is recorded and shown everywhere the extension appears — `vine ext
list`, the console, the health report. An extension never changes tier
quietly: a source that was signed and comes back unsigned refuses the update.

**What the conformance kit cannot promise.** Resolving `requirements.txt`
executes third-party build code by construction — true of pip everywhere — and
a git source additionally runs the author's build backend. The kit therefore
does **not** run before third-party code runs; it runs before anything is
*registered*. The docs must say this in those words, because it is the reason
the signature tier carries more weight than the kit does.

## Contributions the host cannot serve

A CLI operator has no console, so `ui/panel.json` has nowhere to draw. The rule
is J.1.2 rule 4 applied to extensions: **a contribution the host cannot serve
is inert and named, never an error.**

- The loader **parses and validates** the panel even where nothing renders it,
  so a broken panel is caught on the author's laptop instead of in a Station.
- It does not render it: it exposes the parsed contribution, and the Station
  draws.
- `vine ext list` reports `panel: declared (no host surface)`.

The half that matters more is configuration. An extension whose settings exist
only as a Studio form is unusable from the CLI, so:

**The config schema is the source of truth; the panel is decoration over it.**
Studio renders a form from the manifest's `config` block; the CLI reads the
same block for `vine ext config <id> --set language=pt` and for validation. A
registered model role binds through the Models console on a Station and
through `MONKEYLLM_ROLE_<NAME>_*` on the CLI — one role, two binding surfaces.

The conformance kit enforces it: **an extension with a required setting that
has no entry in the config schema fails.** That single rule is what keeps the
CLI a first-class host instead of a degraded one.

A panel-only extension — a dashboard widget contributing no backend seam — is
legitimate, and simply does nothing on a CLI. The list says so rather than
implying it is running.

## Anatomy

```
whisper-ext-1.2.0.zip
├── manifest.json         # identity, compat, permissions, contributions, config schema
├── main.py               # register(api) — the one entry point
├── worker.py             # functions declared heavy; runs in the extension's own venv
├── ui/panel.json         # declarative console contributions
├── requirements.txt      # resolved into the extension's own venv at install
├── LICENSE               # the extension's own licence, shown before install completes
└── SIGNATURE             # detached signature over the zip
```

```json
{
  "id": "whisper",
  "version": "1.2.0",
  "station_compat": ">=0.80,<0.90",
  "license": "MIT",
  "permissions": {
    "network": ["api.openai.com"],
    "filesystem": "none",
    "capabilities": ["ingest"]
  },
  "models": { "requires": [], "registers": [{ "role": "transcribe", "kind": "transcribe" }] },
  "contributes": {
    "converters": [{ "extensions": [".mp3", ".m4a", ".wav"], "handler": "worker:transcribe", "heavy": true }],
    "tools":      [{ "name": "transcribe", "handler": "main:tool_transcribe" }],
    "panel":      "ui/panel.json"
  },
  "config": { "language": { "type": "string", "default": "auto" } }
}
```

`register(api)` receives the one object an extension is allowed to hold. It is
**enumerated**, like `ScopedVine` — a new engine capability needs its line
there or the extension cannot reach it, and that is deliberate.

## The contribution model

An extension does not patch anything. It **claims** a named seam, and
precedence decides. `discover_converters` already works exactly this way
(config command hooks > injected extras > entry points > built-ins), so the
model is not new — it is the existing one, published with a version.

This is what preserves the ability to refactor the engine: an extension is
coupled to a seam's contract, never to the shape of the code behind it.

## Models: roles, never keys

The extension declares roles it **requires** and roles it **registers**. A
registered role appears in the existing Models console and the operator binds
it to a provider they already pay for; the extension calls
`api.models.complete(role=..., ...)` and never sees an endpoint, a key, or
even `has_key`.

Three rules ride with it:

1. **Install refuses a required role with no binding**, at install time and by
   name — not at the first transcription.
2. **Every extension model call is metered** and lands in the J.4.2 row with
   `cost` and `model_ms`. Unmetered extension spend is a bill with nobody's
   name on it, which is exactly the failure v0.73 was written against.
3. **A role carries a `kind`** (`chat` / `embed` / `vision` / `transcribe` /
   `rerank`). Transcription is not `/chat/completions`; without `kind` the
   whole class of non-chat extensions has nowhere to bind.

## Authority, audit, budget

- Owner installs (it is their process). The forest's admin enables (it is
  their material). An admin can never install: in-process code reaches every
  forest, so a local decision would have a global effect.
- The J.4.2 row keeps `principal` (the human who caused it) and gains
  **`via`** (`ext:whisper`). Nullable — a pre-L row reads it as absent, never
  as "no extension", per the v0.73 rule about columns that lie by omission.
- Quota is per extension per forest, set by the operator, and exhaustion is a
  refusal in the envelope shape (`E_EXT_QUOTA`), never a silent stop.

## Lifecycle

Install → restart → enable per forest → run → disable → uninstall → restart.

The restart is not a limitation to hide: Python does not unload a module, so
"disabled" without a restart would mean the code is still resident. The
console states the truth rather than implying an unload that did not happen.

Uninstall leaves the forest untouched (it is git; nothing is lost), and the
console **names what will start being refused** — every `type` and `rel` the
extension declared in `_meta/schema.md` that no other extension declares —
before the operator confirms. Config and secrets go to quarantine with an
expiry, so a failed upgrade is recoverable and an abandoned secret is not
immortal.

## Trust: four controls, four different jobs

1. **Conformance kit** — manifest against the schema, protocol version,
   declared handlers importable, a document round-trip against
   `forests/forest-fixture`. This is a *compatibility* control. The docs must
   say plainly that it is not a security control: it proves the extension
   works, never that it is honest.
2. **Declared permissions** — network hosts, filesystem, capabilities,
   granted item by item at install. In-process these *inform*; they *contain*
   only what runs in the worker. The install screen must not imply otherwise.
3. **Signature + curated registry** — a signed `index.json` this project
   hosts, pointing at third-party releases. Signature verified at install; an
   unsigned zip installs with an explicit unverified warning.
4. **Operator sovereignty** — the owner sees the licence, the permissions and
   the origin, and decides. Nothing installs behind their back.

## Boundaries that stay closed

Unchanged from `docs/extending.md` and Part G:

- Primitive semantics, token budgets and truncation contracts.
- The `locate`/`sniff` split; `tend` staying DML-only; `plant`'s declarative
  schema as the only path to a table.
- The J.3 oracle: an extension tool may never disclose the existence of a node
  outside the caller's scope. Extension tools run under the caller's
  `ScopedVine`, never under a raw `Vine`.
- Binaries never entering forest git (A.3.1).

## What shipped (2026-09-08)

- **Spec v0.80, Part L** (`docs/monkeyllm-spec-v0.80.md`) — L.0-L.15 and
  F.174-F.194, amending J.4.2 (`via`), J.10 (roles carry a `kind`), J.5 and
  A.3.1's commit guard (a second, narrow door for `_meta/*.yaml`).
- **Engine runtime** — `src/monkeyllm/extensions/`: `manifest.py`,
  `sources.py` (four sources, one resolver, three tiers), `store.py`
  (host-level dir + quarantine), `api.py` (the enumerated `register(api)`),
  `worker.py`, `conformance.py`, `loader.py`, `forestcfg.py`,
  `installer.py`, `converters.py`.
- **`vine ext`** — install, update, list, outdated, show, config, enable,
  disable, remove, quarantine; `vine validate` names an expected-but-absent
  extension.
- **Station** — `extensions.py` (config custody, enablement index, quota),
  `via` on the audit row, four routes under `/v1/admin/extensions*`, and the
  ingest Gardener now receives the forest's registry.
- **Studio** — the Extensions console (L.11, declarative), `api.js`, the
  `govern` group, en/pt/es.
- **Tests** — `tests/test_v080_extensions.py` (59) and
  `tests/test_v080_station_extensions.py` (27).

## v0.81 — the door an author could not find (2026-09-13)

Three gaps, and the first was not a missing button. The console's install
box asks for "a path", and a path is on the **host** — through a browser
that is the container's filesystem, so an operator holding an extension
they had just written had **no route at all** to a remote Station short of
publishing it to git first. The local-file door served only somebody with a
shell there, who would have used the CLI.

- **An uploaded archive is a source (L.2).** `{name, b64}` — the shape
  ingest has carried since J.8, so a browser that can send a document can
  send an extension with no new mechanism. `unverified` by construction (no
  forge, no index identity, so nothing could have been checked), refused
  over the ceiling **before** it is written, and capped at 25 MB because
  this door is for an extension's own code.
- **Seam contracts are declared and checked (L.3, L.9 r1).** What each seam
  passes lived in the spec's prose and nowhere in the code, so the kit could
  say "it works" about a handler with the wrong parameters — found on the
  first ingest, at whatever hour that ran. `contracts.py` declares all ten;
  the kit checks the signature at install by reading the **source**, never
  importing it, because a heavy handler's module imports the dependency L.5
  exists to keep out of this process.
- **The authoring surface (L.16).** Prose is written and lives in
  `docs/extending.md`; schemas are **derived** from the manifest model and
  the seam contracts. `GET /v1/extensions/authoring` serves them, open to
  anyone signed in — writing is not installing, and gating the docs on the
  authority to install withholds them from the only person who needs them.
  The console renders the seam table and hands out a folder for a coding
  agent.

Two things this round got wrong first and is worth keeping:

1. **`**kwargs` was treated as excusing a misspelled parameter.** It does
   not: given `def on_event(event, forrest, **rest)`, `**rest` absorbs the
   `forest` the host passes and `forrest` is still unfilled. The rule hinges
   on **defaults**, not on kwargs, and the spec paragraph was corrected to
   match the code rather than the other way round.
2. **The new check immediately failed a v0.80 test fixture of our own** — an
   `events` handler declared as `echo(value)`, a signature no real `events`
   call could fill. It passed for a release because nothing checked.

## What is not done

- **F.194 is implemented and not measured.** Signed-tag verification against
  a forge's published keys needs a signed tag and gpg on the runner.
- **The curated index** (`extensions/index.json`) does not exist, so the
  `verified` tier has nothing to resolve against yet.
- **`docs/extending.md`** still describes the pre-Part-L world.
- **The Studio console** builds and has not been opened in a browser.
- **No real extension exists yet.** Whisper / Docling / FFmpeg are still
  hypothetical, and building one is what will find what no test found.

## Two bugs this round produced, both silent

Worth keeping because neither raised anything and both were found by a test
written for something else.

1. **An extension's module was executed twice** — once for `register` and
   again per declared handler — so `register()` wrote to one module object
   and the handlers read from another. Any module-level state an author
   keeps splits in half with no error. The loader now imports once per
   installed tree (the tree, not the id: a process may hold two installs of
   one id).
2. **The extension list was gated on "has a grant" where it meant "is an
   admin"**, so an ordinary reader could list what was installed. Caught by
   `test_station_admin_scope`'s route canary, which exists precisely so a
   route added today is swept today.

And one design failure caught by reading: the `tools/list` filter's fallback
returned the UNFILTERED list when it did not recognise the SDK's shape. A
visibility filter must fail **closed** — fewer tools than the rule allows is
a degradation, more is a disclosure.

## Steps

1. Cut **spec v0.80** with **Part L (Extensions)**: L.1 manifest and package,
   L.2 the seam catalogue with precedence, L.3 the `register(api)` surface,
   L.4 worker protocol, L.5 model roles and `kind`, L.6 authority/audit/quota,
   L.7 lifecycle and uninstall, L.8 the four trust controls, L.9 the
   declarative UI vocabulary. Amend J.4.2 (`via`), J.10.2 (registered roles),
   J.5 (the Extensions console). **Check the file does not exist first.**
2. `monkeyllm-ext` — the SDK and manifest schema, **Apache-2.0**, importable
   without touching `apps/`. Without this, every extension is a derivative of
   an AGPL host and the ecosystem cannot happen.
3. Engine: the source resolver (curated id / git / archive / local file →
   immutable artifact + tier) and `vine ext` — install, update, list, config,
   enable/disable per forest, remove — plus `vine validate` reporting an
   expected-but-absent extension.
4. Station: installer (venv resolution, signature, conformance kit),
   registry tables (installs, per-forest enablement, config, quota), the
   worker supervisor, `register(api)`.
5. Seam publication, one at a time, each with its precedence test.
6. Studio: the Extensions console (install, permissions review, per-forest
   enablement, config from the declared schema, quota, quarantine).
7. Move Whisper / Docling / FFmpeg out of this repo and ship them as the first
   signed extensions — the proof that the boundary works.
8. `docs/extending.md` rewritten around Part L; an authoring guide with a
   worked extension.

## Acceptance criteria

- [ ] F.174 A manifest that fails the schema, the compat range, or the
      conformance kit installs **nothing** — no venv, no registry row.
- [ ] F.175 An extension's heavy dependency is absent from the Station's own
      interpreter (asserted by importing it and expecting failure in-process).
- [ ] F.176 A required role with no binding refuses the install by name.
- [ ] F.177 An extension model call appears in the J.4.2 row with the human
      `principal`, `via: ext:<id>`, `cost` and `model_ms`.
- [ ] F.178 Quota exhaustion refuses in the envelope shape and the refusal is
      audited; the next period admits again.
- [ ] F.179 An extension tool called with an out-of-scope id returns the
      byte-identical `E_NOT_FOUND` a primitive returns (J.3 survives).
- [ ] F.180 Enabling on forest A publishes the tool to a key holding A and
      **not** to a key holding only B.
- [ ] F.181 Uninstall names every `type`/`rel` that will start being refused,
      before confirmation; the forest's files are byte-identical after.
- [ ] F.182 Quarantined config is recovered by reinstalling the same id, and
      expires on schedule.
- [ ] F.183 An extension raising inside a seam is contained: ingest falls back
      to the built-in converter, the batch completes, the report names it.
- [ ] F.184 A retrieval/answer contribution is named in the Part D trace.
- [ ] F.185 An unsigned source installs only after an explicit unverified
      acknowledgement; the tier is recorded, shown, and a signed extension
      returning unsigned refuses the update.
- [ ] F.186 An extension installs and runs on a `pip install
      monkeyllm[extensions]` operator with no Station present: `vine ext
      install`, enablement written to `_meta/extensions.yaml`, the converter
      claiming its extension on the next `vine adopt`.
- [ ] F.187 `vine validate` names an extension the forest expects and that is
      not installed; the base install (no extra) loads and the loader is a
      no-op rather than an import error.
- [ ] F.188 A config file under `_meta/` carrying a field the manifest
      declared as a secret is refused — `_meta/` is versioned.
- [ ] F.189 A git install records the resolved commit SHA, not the ref; the
      same `@tag` installed after the tag moved is a different SHA and the
      console says so.
- [ ] F.190 An extension declaring a panel installs and runs from the CLI: the
      panel is validated, reported as unserved, and nothing errors.
- [ ] F.191 Every required setting is reachable through `vine ext config`; the
      kit fails an extension whose required setting has no schema entry.
- [ ] F.192 A failed `vine ext update` leaves the previous install running and
      unmodified.
- [ ] F.193 An install from `@main` records the SHA, is marked `tracking` and
      lands in the `unverified` tier; `vine ext list` names the ref and makes
      no network call.
- [ ] F.194 A signed tag verifies against the forge's published keys and
      reaches `signed`; the verifying identity is recorded, and an install
      whose identity changed refuses the update until acknowledged.

## Out of scope

- A hosted marketplace with accounts and payments. The registry is a signed
  index file.
- Extensions in languages other than Python. The worker protocol should not
  *forbid* it, but v1 ships one SDK.
- Hot install/upgrade without restart. Decided against; revisit only if
  everything moves to workers.
- Any relaxation of the primitives' contract.

## Open questions

- The declarative UI vocabulary: which components in v1 (form, table, action
  button, status card) and how it grows without a spec bump per widget.
- Whether a worker may be a container where Docker is available, as a second
  runtime under the same manifest.
- Quota unit: calls, tokens, or currency — and where the period resets.
