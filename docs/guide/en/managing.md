# Managing & governing

English · [Português](../pt/managing.md) · [Español](../es/managing.md)

[← Handbook](./README.md)

The forest is the product; this page is about keeping it governed and
healthy. Five consoles carry that work — **Access**, **Models**, **Health**,
**Audit** and the **Optimize** tab of Ingest — and all of them appear only
to a key that holds the `admin` capability on the forest. Everything they
do travels through the same `/v1` routes any API client could call: there
is no privileged side-channel, and there is deliberately no separate
super-administrator panel. One console, one API, with capabilities deciding
what appears.

## People & access

Governance in the Studio is shaped like a **person**, not like a table of
grants. Adding somebody is one form — who they are, what they may see, how
they sign in, and a token if their scripts need one — because that is one
decision, and afterwards every change to that person starts from their row
in the list: their level, their scope, whether they can sign in, how many
live tokens they hold, and when they were last seen.

![The Access console: everyone who can reach your forests, one row per person](../assets/people.png)

Access is granted as a **level first, capabilities second**. A level is a
named starting point, and the console documents every level on the screen
itself, so choosing one never requires leaving it:

| Level | Can | Cannot |
|---|---|---|
| **Reader** | read the material | everything else |
| **Analyst** | read, run read-only SQL | write anything |
| **Editor** | read, query, create and edit nodes, change dataset rows | add new documents, grant access |
| **Curator** | everything an editor can, plus loading new documents in | grant access to others |
| **Owner** | full control, including giving access to other people | — |

A level is only a starting point: a "Fine-tune the capabilities" section
lets any grant deviate from it (the capabilities are `read`, `query`,
`write`, `tend`, `ingest`, `admin`), and the chosen level is restated in
plain words directly under the choice — "Reads, and runs read-only SQL
over datasets." — so what you are about to save is said before you save it.

Two more rules keep the form honest:

- **Forests are chosen as a set.** The form offers every forest you
  administer as a multi-selection — one person, one decision, not one
  visit to this form per forest. If a step is refused (say, a forest you
  do not administer), the rest is still applied and the refusal is listed
  by name; nothing is silently dropped.
- **Branch scope appears only when it means something.** With exactly one
  forest ticked, you can narrow the grant to branches picked from that
  forest's own tree ("Only the branches I choose"). With several forests
  ticked the grant covers each forest whole, and the form says so —
  branch names are not shared between forests, so applying one forest's
  names to another would be a lie.

> **Note** — Choose a scope of zero branches and the console warns you:
> that person would see nothing at all. An empty scope is a valid grant;
> it is just rarely the one you meant.

### Keys and tokens

The second tab of the same console lists **every credential that can reach
this Station** — two views over one truth. Each token carries a label
("CI pipeline, Zapier, staging bot"), a recognisable prefix, an expiry
(7, 30, 90 or 365 days, or never), and when it was last used; each can be
revoked on the spot. The secret itself is shown exactly once, at creation
— only its digest is stored, so copy it then or mint another.

Paired keys — the self-service keys the Clipper and the Skills console
derive from a person's own password (`POST /v1/auth/pair`) — live here
too. They are ordinary tokens with a twist: they carry a capability mask
of at most `{read, ingest}`, their authority is the person's own grants
**intersected with that mask at the moment of use** (a grant revoked later
is gone from the key immediately), and they always expire — 90 days by
default, 365 at most. Pairing can only narrow, never add, which is why it
needs no administrator.

Session tokens — the by-product of a password sign-in — never appear in
this list. They are not a credential an operator manages.

One escalation rule shapes what you can see: a key authenticates a
*principal*, and a principal may hold grants on several forests, so
minting or revoking their credentials requires `admin` on **every** forest
they hold. A person who also holds a forest you do not administer appears
in your list, but their credentials are out of reach — the console says so
on their row.

### The setup window, and why starting mints nothing

A fresh Station belongs to nobody, and it stays that way until a person
claims it: **starting a Station mints nothing**. The registry holds exactly
the same authority after boot as before it — no key, no password, no
principal that can act. That is what lets the first-run setup window
survive to be used.

While the registry holds no credential of any kind, `POST /v1/auth/setup`
is open: the first person to open the console becomes the **owner**, the
single principal that holds `admin` on every forest, present and future.
The first boot announces this on standard output — the console URL, and a
warning that an unclaimed owner seat on a public interface is a race
against strangers. Once setup has run, the route closes permanently and
answers exactly like a path that never existed.

Two deployments opt out of the setup screen, each explicitly:

- **Headless boxes** pass `--bootstrap-key` (or
  `MONKEYLLM_STATION_BOOTSTRAP_KEY=1`) and the first API key — carrying
  the owner bit — is printed once at boot, into that same one-shot window
  and never again.
- **Break-glass deployments** set `MONKEYLLM_STATION_ADMIN` and
  `MONKEYLLM_STATION_PASSWORD`: an environment-held account, never stored,
  rotated by restarting. Configuring it closes setup, because the
  deployment has already declared its first identity.

## Models

A forest answers questions, summarises what comes in and describes images
only if you bind it a model. The Models console is where that happens —
per forest, in two halves: providers and roles.

![The Models console: providers on one side, the three roles a forest binds on the other](../assets/models.png)

**Providers** are named endpoints — any OpenAI-compatible `/v1` base URL
works: OpenRouter, LiteLLM, vLLM, a local llama.cpp. Keys are write-only
across every surface: the console reports only whether one is stored, and
leaving the field blank on an update keeps the stored one, so an endpoint
can be corrected without re-pasting a secret. Providers declared by the
deployment's own environment (`MONKEYLLM_LLM_ENDPOINT`,
`MONKEYLLM_EMBED_ENDPOINT`) arrive pre-configured and read-only — change
the variables and restart the Station to change them.

When you choose a model, the console offers the provider's own catalogue
(fetched from its `/models` route) so you pick a real identifier instead
of typing one — but you may still type a model the provider does not
advertise, because gateways under-report.

**Roles** are what a forest actually binds — `(forest, role) → (provider,
model, reply length, reasoning)`:

| Role | The console calls it | What to optimise for |
|---|---|---|
| `answer` | Answering questions | Speed — it reads retrieved material and writes the reply, on every question. |
| `ingest` | Summarising what comes in | Care — it writes the summary every later search navigates by, once per document. |
| `vision` | Describing images | Fidelity — it reads slides, diagrams and screenshots at ingest, and its description is all an image ever says. |

Each binding carries a **reply length** (the whole reply the model may
write — too low truncates mid-sentence, and a reasoning model needs room
to think first) and a **reasoning** switch, off by default and worth
turning on only for hybrid thinking models.

Two facts worth holding on to:

- **Binding a model never widens access.** Retrieval runs inside the
  asker's scope before any model is called, so the model only ever reads
  what that person could already have read primitive by primitive.
- **A forest with no `answer` binding still does everything but Ask.**
  Explore, Data, ingest, search — all of it works; the Overview says it
  plainly: "No model is bound to this forest yet, so Ask cannot answer.
  Everything else works."

## Health

The forest's caretaker is the **Ranger**, and the Health console is its
report — "what the Ranger would report on its next run. Reading it changes
nothing."

![The Health console: the Ranger's report, and the forest packaged as a snapshot](../assets/health.png)

What the Ranger tends, on its own runs:

- **Heat evaporation.** Every read deposits pheromone; without forgetting,
  every trail would saturate and the heat would stop discriminating. Heat
  decays exponentially (half-life 30 days by default), and rows that cool
  below 0.01 are removed as dust. Evaporation lives entirely in the
  derived layer — it never commits.
- **Promotion and pruning — of uncertain links only.** The Ranger manages
  exactly the links born below full confidence: agent proposals and
  discovered shortcuts. A proposal whose both endpoints stay warm is
  confirmed by use and promoted; one whose both endpoints have gone stone
  cold is pruned. Structural edges and links at confidence 1.0 are never
  touched, every change is an audited `.md`-only commit
  (`ranger(promote)`, `ranger(prune)`), and a link that is neither hot
  enough nor cold enough is left alone — patience is a feature. The
  Ranger never deletes nodes.

The **report** needs `admin` on the forest and an unrestricted scope — it
counts problems across the whole forest, so a branch-scoped grant is
refused rather than served numbers that silently describe nodes it cannot
see. It covers: branches to split (too wide for any reader), overloaded
nodes (more trails than anyone can follow from one place), lint errors and
warnings, sources that vanished (the node stays; the file it came from is
gone), link proposals awaiting the Ranger, and the pheromone at a glance —
how many warm nodes, peak and average heat.

Reading the report changes nothing. The tending itself is a scheduled run
at a shell, one cycle or as a service:

```bash
vine ranger --forest /forests/<id>              # one cycle: evaporate → tend links → report
vine ranger --forest /forests/<id> --every 3600 # service mode, repeat every N seconds
```

On a Docker deployment, the same command runs inside the container:
`docker compose exec station vine ranger --forest /forests/<id>`.

### Snapshots

A snapshot is the forest packaged as **one file** — its git repository as
a bundle, full history included, every plant and every audit commit
travelling along. From the Health console you can take one ("Include
dataset payloads" adds a sidecar archive for the `.db` files git never
holds), and the **owner** can download the bundle and the sidecar.

Importing goes through the forest switcher: **Import snapshot** creates a
new forest from a bundle, history included, owner-only — the bundle enters
as-is, with no curation pass, which is exactly why only the principal that
governs the volume may plant one. The imported forest arrives servable
(the Station reindexes it on arrival) and cold: no model call is spent,
and search stays keyword-only until someone builds the vector layer.

> **Note** — Restoring *over* a live forest is deliberately not offered in
> the console; that stays on the command line (`vine snapshot restore`).
> A snapshot travels: download it here, import it as a new forest there.

## Audit

The Audit console answers "who saw what". Its two halves are stored where
each belongs:

- **Reads** land in the audit log: who, which forest, which call, an
  argument digest, the result size, and when. Bodies and snippets are
  never copied in — the log records access, not content — and the console
  says so on the screen.
- **Writes** are already commits in the forest's own git history, stamped
  with the acting principal (`station(<principal>): <action>`), so the
  history of what changed is the forest's own.

Together the two reconstruct any answer's full trail after the fact:
which principal, which primitives, which nodes, in which order. An answer
served from the store (see below) is audited as one — the row carries the
entry's key digest, is marked as served from the store, and the cost it
records is the cost *avoided*, never a second spend.

The log is filterable by person, and reading it needs the `admin`
capability.

## Optimize

The Ingest console's **Optimize** tab gathers one errand told three times:
keep the content current, keep what finds it current, and keep the dense
half paid up. Three buttons, and knowing which to press is most of the
skill:

| Button | What it does | When to press it |
|---|---|---|
| **Sync** | Re-reads the folder this forest last mirrored and updates only what changed. | The source documents moved on and the forest should follow. |
| **Rebuild** | Rebuilds the search index from the files — the files are the truth, the index is derived. | Anything looks out of date: a search that misses a node you can read, a forest that arrived from a snapshot or an older version. |
| **Refresh** | Embeds only the nodes written since the vector layer was last built. | The console says "*n* nodes have been written since the last build, so hybrid search ranks without them." |

Rebuild (`POST /v1/admin/reindex`) needs `admin` and an unrestricted scope
— the count it returns is the size of the whole forest. It writes only the
derived layer: no commit, no history change, which is also why a
read-only Station still offers it — an index it could never repair would
degrade forever.

Refresh exists because **a read embeds only the query**: asking questions
never pays to embed documents, so the embedding debt of an ingest
accumulates visibly as a "stale" count instead of hiding inside somebody's
search latency. Until you press it, new nodes are still found — by
keyword; only the vector half of hybrid ranking is behind. A refresh
against a missing or model-mismatched index refuses rather than half-fill
two incompatible spaces; that case wants a full canopy build.

## Costs and budgets

Every read primitive answers within a declared **token budget**, and
truncation is always explicit — a `truncated: true` marker, never a silent
cut. An agent's context window is the scarcest resource in the system, and
the budgets are how the forest respects it:

| Primitive | Budget (tokens) |
|---|---|
| `look` | 500 |
| `move` | 600 |
| `locate`, `scan`, `sniff` | 800 |
| `query` | 2,000 — whole rows drop from the tail; the column list never does |
| `pick` | a body over 4,000 returns its outline instead, steering the agent to one section |
| `harvest` | 4,000 for the whole composite |

The one call that costs real money is `answer` — the model call behind
Ask. The Station therefore keeps an **answer store**, per forest: a
repeated question is served from the store, not re-billed. Retrieval still
runs on every ask (it is the cheap half), and what it retrieved decides
freshness — an entry is served only while the material behind it is
byte-for-byte what it was, so a stale hit is structurally impossible and
any write to the forest invalidates every entry made before it. Entries
never cross access scopes, a served answer says so ("From the store" in
Ask, `cached: true` on the API), and the audit row records the cost
avoided rather than spending it twice.

The store's controls sit in the Models console: on or off per forest (on
by default), how many entries are kept, an optional expiry in hours
(hygiene, not correctness), a button to empty it, and the running score —
hits, misses, and tokens **not spent**.

---

Two places to go from here: [Install & deploy](./install.md) for updating
the Station itself — everything worth keeping lives in the named volumes,
so an update is a rebuild, not a migration — and
[Connecting your AI](./connecting-ai.md), because a well-governed forest
is still only as alive as the agents reading and feeding it.
