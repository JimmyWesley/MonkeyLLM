# Connecting your AI

English · [Português](../pt/connecting-ai.md) · [Español](../es/connecting-ai.md)

[← Handbook](./README.md)

This is the page the rest of the handbook has been building toward. Everything
so far [installing the Station](./install.md), [signing in](./first-access.md),
[asking questions](./using.md), [feeding documents](./feeding.md) happened
through the Studio. But the Studio is a window. The product is the forest behind
it, and the forest is built to be read and grown by *your own AI*.

## Why

When you connect an agent to a forest, it gains something a chat transcript
never gives it: a **persistent, governed, citable memory**.

- **Persistent** the forest outlives every conversation. What one session
  plants, the next session recalls. Other people and other agents feed it too,
  and it keeps growing for as long as you keep it.
- **Governed** the agent holds a key, the key carries your grants, and every
  read and write passes the same enforcement seam the console does. What the
  key cannot reach does not exist for the agent.
- **Citable** everything the agent reads carries a node id. Answers grounded
  in the forest can say exactly which nodes they stand on.

And there is nothing second-class about the connection. The Station has no
privileged side-channel: whatever the Studio shows you, an API or MCP client
holding the same key could fetch too. The console's Ask page calls the same
`answer` your agent will call. Connecting an AI is not an integration bolted
on the side it is the front door.

> **Note** the snippets below use `https://station.example.com` as a
> placeholder. You rarely have to substitute anything by hand: the Skills and
> Integrations consoles render these exact snippets with your Station's real
> address and forest already filled in.

## The three surfaces

One container, three surfaces, the same governed forests. All three
authenticate with the same API keys, checked at a single gate, and every
forest access routes through the same scoped enforcement.

| Surface | Who it serves | Where |
|---|---|---|
| **Studio** | Humans this web console | `https://station.example.com/` |
| **REST** | Apps, scripts and integrations | `https://station.example.com/v1/…` |
| **MCP** | Any agent harness (streamable HTTP) | `https://station.example.com/mcp/` |

The MCP surface is contract-identical to a local `vine serve`: an agent that
works against a forest on your own disk works against a Station-served forest
with no change beyond the endpoint and a credential. Scoping only ever narrows
*content* it never changes the shape of a response.

## Pair a key

Your agent needs a credential that is *yours* not one an administrator has
to mint. Pairing is that door: `POST /v1/auth/pair` is unauthenticated like
login, takes your username and password, and answers with an API key.

```bash
curl -sX POST https://station.example.com/v1/auth/pair \
  -H 'content-type: application/json' \
  -d '{"username": "you", "password": "…", "label": "claude-code"}'
```

The reply carries `api_key` (it looks like `mk_…`), your `principal`, the
key's `caps` and its `expires_at`. What makes a paired key safe to hand to a
machine is that it **can only narrow, never add**:

- **The mask.** A paired key carries a capability mask `{read, ingest}` by
  default, and that set is also the ceiling: asking for `write`, `tend`,
  `query` or `admin` is refused as `E_SCHEMA`. Those stay what an
  administrator mints deliberately.
- **Grants ∩ mask, at the moment of use.** The key's effective authority is
  your own grants filtered through the mask, computed live a grant revoked
  after pairing is gone from the key immediately. A paired key held by an
  owner is still refused every admin route.
- **It always expires.** 90 days by default, 365 at most; there is no
  "unlimited". The key is shown once only its digest is stored.
- **Self-service by construction.** Pairing reaches nothing your password
  could not already reach, so no admin gate stands in front of it. Both
  `login` and `pair` are rate-limited, and the refusal never reveals whether
  a username exists.

The key lives where every key lives: the Access console lists it, and an
administrator can revoke it there at any time (see
[Managing the Station](./managing.md)).

## Claude Code in two commands

If your agent is Claude Code, the whole connection is the pairing call above
plus one registration:

```bash
claude mcp add --transport http monkeyllm https://station.example.com/mcp/ \
  --header "Authorization: Bearer mk_…"
```

From then on the forest's tools are in every session. Two things worth
knowing on the first call:

- Have the agent call `forests()` first. A scoped key has no master index;
  that call returns the forests the key may use and the roots to start from.
- The MCP surface only answers hosts listed in
  `MONKEYLLM_STATION_ALLOWED_HOSTS`. If you serve through a domain, name it
  there (or `*` to skip the check) every request still needs a key.

## The Skills console

A connected agent knows the tools exist; it does not yet have the *habit* of
using them. The Skills console closes that gap. A skill is a small instruction
file an agent runtime loads, and this one teaches your agent to treat the
forests you choose as its memory: recall from them before answering, save what
is worth keeping, cite the node ids it read.

![The Skills console, generating the memory skill for this Station and forest](../assets/skills.png)

The console walks you through the same steps as this page — pair a key, point
Claude Code at the Station, size the skill, hand it the files — and every
snippet on it already carries the Station's address and the forests you picked.
The skill is generated in your browser, for that exact deployment; the Station
gains no endpoint for it. It is available to anyone whose key can `read` the
forest — never admin-gated, because pairing made the credential self-service
and learning to connect must be too.

### The skill is a folder, and you choose how much of it ships

An agent loads a skill whole, so the console splits it: a core every agent
needs, and reference files it reads only when it needs them.

```
~/.claude/skills/monkeyllm-memory/
├── SKILL.md              recall, citation, refusals — the core
└── references/
    ├── saving.md         ingest one document (a paired key's default write)
    ├── writing.md        plant, graft, prune, transplant, the anatomy of a node
    ├── time.md           calendar and date windows
    ├── datasets.md       notes, read-only SQL, single-statement DML
    └── sharing.md        export and share links
```

The blocks start selected to match what your key can do in the forests you
picked. A key paired with the default `read` + `ingest` gets `saving.md` and
not `writing.md`, and is spared some 1,400 tokens of writing instructions it
could not have executed anyway. Widen the selection if you are preparing the
skill for somebody whose key is wider — the block then names the capability it
requires in its own first line. The console prints what the core costs as you
choose, because that is the number every session pays when the skill fires.

**Download the folder (.zip)** hands you the whole thing already arranged —
`monkeyllm-memory/SKILL.md` beside `monkeyllm-memory/references/*.md`. Unzip
it into `~/.claude/skills/` and the install is done; the paste above is the
faster route only if you are already at a terminal.

If your runtime takes no folder, **One file** inlines the same blocks into a
single `SKILL.md`. The instructions are the same ones; what changes is that
all of them load every time.

### Which forests it is for

Pick one forest or several. One skill for two forests beats installing two
that each know half of what the agent needs — and when you pick more than one,
the file carries a routing table (which forest holds what, read from
`coverage` as the file is generated) so the agent does not have to search all
of them to find out.

What the file bakes in is *intent*, not permission. It teaches `forests()` as
the very first call, because that is the only place your capabilities, your
roots and this Station's version are true at the moment the agent uses them. A
forest whose grant later lapses simply stops being listed, and the skill says
plainly that this is a narrowed key — not something to report or work around.

### Keeping it current

The Station stamps its version into the file, and the skill teaches the agent
to compare it against what `forests()` reports. When the Station is newer, the
agent says so and hands you the link that rebuilds *this* skill — same forests,
same blocks, same assembly. That link is simply this console's address, which
is why the choices you make here appear in the URL: bookmark it, and the whole
update is one visit and one paste.

The agent never installs the skill itself, and that is deliberate. What it gets
over MCP — the tools, the instructions — reaches it only while it is connected
to this Station. A file in its skills folder keeps instructing it in every
session afterwards, including sessions this Station is not part of. What
outlives the connection is yours to decide.

### What the core teaches

- **Every call names the forest** — the forest is the first argument of every
  tool on this server, and the file writes it that way in every example.
- **Recall before you answer** — `answer` when the forest's answer *is* the
  answer; `harvest` when the agent will reason over the material itself;
  `locate` → `look` → `pick` to navigate; `sniff` for literal text inside
  bodies; `coverage` for what the forest actually holds. And: cite node ids
  for anything asserted from the forest.
- **An empty result is not an empty forest** — `locate` reads curated
  metadata and never bodies, so a term nobody lifted into a summary is found
  by `sniff` and by nothing else; and before trusting any silence, ask
  `coverage` what the material even is.
- **Respect the contract** — the key decides what the agent sees and what it
  may write; never work around a refusal — say what was refused and which
  capability it needs. Every read is budgeted, and `truncated: true` means
  ask narrower, not retry harder.

> **Note** — the skill's body is English regardless of the console language,
> on purpose: it addresses the model, not you. The walkthrough around it is
> translated like any other part of the console.

## The MCP tools

The tools are the engine's primitives plus the composites, each behind the
capability it needs. `forests` answers to any valid key; everything else is
gated as shown.

| Tool | Needs | What it does |
|---|---|---|
| `forests` | any key | Lists the forests this key may use, with capabilities and starting roots. |
| `locate` | `read` | Ranked entry points over curated metadata where to drop into the forest. |
| `look` | `read` | Cheap digest of one node: summary, edges, children, stats. |
| `move` | `read` | Neighbours of a node along typed edges. |
| `pick` | `read` | Reads the body, or one section of it. |
| `scan` | `read` | Filters a branch's nodes by metadata. |
| `sniff` | `read` | Literal search inside bodies the facts summaries do not carry. |
| `calendar` | `read` | Where the forest's material sits in time: how many nodes each period holds, most recent first. |
| `coverage` | `read` | What the forest holds: its roots, how big each is, where that material came from and when. |
| `history` | `read` | What happened to a node and who did it every commit, newest first. |
| `harvest` | `read` | One-shot retrieval: ranked evidence with exact snippets, no hops. |
| `answer` | `read` | A grounded answer written by the model bound to the forest, with its evidence. |
| `view` | `read` | The image payload of a media node, as image content a multimodal client reads into its own context. |
| `query` | `query` | Read-only SQL against a dataset node. |
| `plant` | `write` | Creates a node. |
| `graft` | `write` | Edits a node. |
| `prune` | `write` | Removes one node; `force` also strips the links pointing at it. |
| `transplant` | `write` | Moves one node to a new address and leaves the old id as a waymark. |
| `tend` | `tend` | Single-statement dataset write. |
| `ingest` | `ingest` | Puts documents into the forest through the Gardener. |

Every searching call takes an optional `since`/`until` window over node
dates, and `calendar` says which periods hold anything — so "what did we
decide last week" becomes two dates read off a map instead of a sweep of the
whole forest. `look` and `pick` also accept a list of ids: one call, one
budget, every id accounted for.

A reasonable mental model: `answer` and `harvest` are the one-shots, the
`locate`/`look`/`move`/`pick`/`scan`/`sniff` family is navigation, `query` and
`tend` are the dataset pair, and `plant`/`graft`/`ingest` are how the forest
grows.

## The REST surface in five minutes

Scripts and applications speak the same forests over plain HTTP/JSON. Send
the key as a bearer token on every request. If you have a username and
password instead, a login returns a **session token** an ordinary key with
a 12-hour life so past the door there is exactly one authorization path:

```bash
curl -sX POST https://station.example.com/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username": "admin", "password": "…"}'
```

One route shape covers every primitive: POST the arguments as JSON to the
primitive's name, per forest —
`POST /v1/forests/{forest}/{name}`. Three examples, for a forest named
`handbook`:

```bash
# ask for a grounded answer
curl -sX POST https://station.example.com/v1/forests/handbook/answer \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"question": "what is our expense policy?"}'
```

```bash
# retrieve evidence without a model
curl -sX POST https://station.example.com/v1/forests/handbook/harvest \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"query": "expense policy", "terms": ["receipt"], "k": 3}'
```

```bash
# upload documents: text as "text", any other file as "b64"
# (an image or audio file lands as a media node; view serves its bytes)
# (add "passport": {title, summary, tags, ...} when you already know the scent)
curl -sX POST https://station.example.com/v1/forests/handbook/ingest \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"mode": "upload", "dest": "policies",
       "files": [{"name": "expenses.md", "text": "# Expenses…"},
                 {"name": "receipt.jpg", "b64": "<base64 of the file>"}]}'
```

Failures are one envelope, mapped onto HTTP codes, and the `hint` is written
for the caller show it:

```json
{
  "error": {
    "code": "E_FORBIDDEN",
    "message": "missing or invalid API key",
    "hint": "Send Authorization: Bearer <key>."
  }
}
```

> **Note** out of scope is indistinguishable from absent. A node the key
> may not see reports `E_NOT_FOUND`, byte for byte the same as a node that
> does not exist. This is deliberate: an error that said "forbidden" would
> itself disclose the node.

## Any other runtime

Nothing above is particular to Claude Code beyond the install path. Any
MCP-capable runtime connects with the same endpoint and the same paired key —
register it wherever your runtime configures MCP servers:

```json
{
  "mcpServers": {
    "monkeyllm": {
      "type": "http",
      "url": "https://station.example.com/mcp/",
      "headers": { "Authorization": "Bearer mk_…" }
    }
  }
}
```

Hand it the same `SKILL.md` instructions, adapted to however your runtime
loads system prompts or skills. The file addresses the model, so it travels.

## What your agent can never do

Connecting an AI does not open a hole in the governance the agent is a
principal like any other, and the contract holds on every surface.

**Scopes hold.** A grant binds a principal to one forest with capabilities
and branch-prefix scope: allow and deny lists of subtree prefixes, deny wins
at any depth, and no grant means no access. The capabilities are exactly six:

| Capability | Allows |
|---|---|
| `read` | read the material |
| `query` | run read-only SQL |
| `write` | create and edit nodes |
| `tend` | change dataset rows |
| `ingest` | add new documents |
| `admin` | grant access to others |

Scope filtering is applied *before* ranking and budgeting, so an agent cannot
infer hidden content from result counts or truncation flags and an
out-of-scope node answers exactly like a missing one.

**Budgets hold.** Every read primitive answers within a declared token
budget, and a cut result always says `truncated: true` never a silent cut:

| Call | Budget (tokens) |
|---|---|
| `look` | 500 |
| `move` | 600 |
| `locate`, `scan`, `sniff`, `calendar`, `coverage`, `history` | 800 each |
| `query` | 2000 |
| `pick`, `harvest` | 4000 |

A body over `pick`'s budget comes back as its outline plus a hint to ask for
one section. The budgets are why a forest stays navigable by a small model —
and why the skill teaches "ask narrower, not retry harder".

**Writes stay disciplined.** `plant` and `graft` are atomic git commits
inside the forest; datasets change only through `tend`, one DML statement at
a time, WHERE mandatory on UPDATE and DELETE, no DDL ever. There is no
route by which an agent deletes a node.

**The audit sees everything.** Every scoped read lands in the host registry:
principal, forest, primitive, an argument digest, result size and timestamp —
never bodies. Every write is a git commit stamped with the acting principal.
Which agent read which nodes, in which order, is reconstructible after the
fact see [Managing the Station](./managing.md).

## Where the full manual lives

This page is the operator's path. The exhaustive reference every route,
every tool, every deployment knob and environment variable lives inside the
Studio itself, in the **MCP / API / Integrations** console. It is admin-gated,
because it speaks the administrator's vocabulary: credentials, hosts, the
container.

![The Integrations console: the deployment manual, inside the deployment it describes](../assets/integrations.png)

It is a console rather than a static site on purpose: every example there
carries that Station's own origin, so each snippet is copy-ready for the host
the administrator is actually looking at documentation that cannot drift
from the deployment it documents. When something on this page and something
in that console disagree, trust the console: it is describing itself.
