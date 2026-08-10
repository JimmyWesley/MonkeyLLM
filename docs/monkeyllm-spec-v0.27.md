# MonkeyLLM — Technical Specification v0.27 (Phase 0/1/2 + host layer)

**Audience:** development team.
**Scope:** normative specification of the forest dialect (`schema.md`), the I/O contracts of the Vine protocol's primitives (MCP), the host layer that serves them to many principals (Part J), and the Phase 0 acceptance criteria.
**Companion document:** `monkeyllm-arquitetura.md` (architectural view).
**Convention:** the words MUST, MUST NOT, MAY follow the spirit of RFC 2119.

> Language note: as of the T02 translation pass (2026-07-02) the entire
> document is English. As of v0.5 every **contract token** (type/rel/enum
> values, parsed section headings) is English regardless of prose language.

**Changelog v0.26 → v0.27 — the console can shape the forest it serves.**

A forest created through the console has exactly one branch: its master
index. Nothing in the console could add a second. The only branch-maker in
the whole product was `adopt`, which does not invent structure — it mirrors
a source directory tree — so a forest that did not arrive as a folder tree
could only ever be a flat pile at the root, and the operator's one shaping
tool was to go and reorganise a folder on some other machine first, then
ingest it. The Ingest console asked "where do these go?" and offered only
the branches that a past adopt happened to create.

Nothing in the engine was missing. `plant` already accepts `type: branch`,
already refuses an id that does not live under its parent, already refuses
a duplicate, already grafts the entry into the parent index and commits
both files atomically, and `ScopedVine` already refuses a write outside the
grant. The gap was entirely a console that never called it — which is the
best kind of gap, because closing it adds no second way to write.

- **J.5.7 Shaping the forest.** The console creates a branch through
  `plant` and through nothing else. The operator names it; the console
  derives the id and never lets anyone type one, because ids are immutable
  (C.7) and a typo would be permanent.
- **The destination picker creates.** "Where do these go?" is exactly the
  moment the missing branch is discovered, so the branch can be made from
  there — the same call, not a second one, and not a trip to another
  console and back.
- **The boundary is stated, not implied.** There is no move, no rename and
  no delete: ids are immutable, a node's id encodes its branch, and no
  primitive relocates one. The console can create structure and curate it.
  It is not a file manager, and this is written down so nothing is designed
  against one that does not exist.
- New acceptance criterion **F.30**.

**Changelog v0.25 → v0.26 — ingest grows a perimeter: every source is
named, vetted, and contained.**

A forest created through the console and then refreshed from it ingested
the Station's own installation tree. The chain had three links, each
defensible alone: `sync` defaults to the source root a prior `adopt`
recorded (G.3); a forest that has never adopted has no such root; and an
absent root was read as the empty path, which every filesystem API resolves
to *the working directory of the process*. So the one mode J.8 exempts from
the `admin` requirement — exempt precisely because its directory was vetted
at adopt time — became the one mode that walked a directory nobody had ever
vetted, on behalf of a principal who was never asked for `admin`.

Three more escapes of the same shape were open beside it. The walk had no
notion of a forest, so a source placed above the registry would have
adopted every neighbouring forest's passports as documents, across the
tenant boundary. A targeted `sync` joined its caller's path onto the source
root and checked containment with `relative_to`, which is lexical: `../../x`
survived the join and came back out as a "relative" path, so the file was
read and planted. And `content: reference` resolved `source_root/source_path`
without checking the result stayed underneath it, which turned `pick` — a
*read* primitive — into a reader for any file the host process could open.

None of the four was a missing check inside a feature. They were the same
absent idea, four times: **an ingest source is a boundary, and a boundary
has to be stated somewhere.** This version states it.

- **G.3 amended: an ingest source is always a named, contained directory.**
  The empty source is a caller error, never a fallback to the working
  directory. A source MUST NOT be, contain, or sit inside the forest, and
  any directory that is itself a forest is pruned from every walk.
- **G.8 amended: a targeted `sync` path is contained after resolution**,
  not by string inspection — `..` collapses and symlinks are followed
  before the comparison, because the lexical check is the bug.
- **G.7 amended: a `reference` body MUST resolve underneath the source
  root.** `source_path` is ordinary frontmatter that anything able to
  `plant` can set, so this is containment, not trust.
- **J.8.2 Ingest roots, deny-by-default.** The host names the directories
  it will read on a caller's behalf, and an unconfigured Station names
  none: it accepts `upload` and `compose`, which carry their own bytes, and
  refuses every host path. A control that must be switched *on* protects
  only the deployments that already knew; a control that must be switched
  *off* protects the rest. This is the one rule here that is a default
  rather than a check, and it is the one that matters most, because the
  operator who most needs it is the one who never reads this document.
- **The registry root is never an ingest source**, listed or not: one
  forest reading the volume that holds every forest is the tenant boundary
  failing in the only direction that counts.
- **J.6 amended**: a Station's working directory MUST NOT be its own
  install tree — defence in depth, so that the next path bug lands
  somewhere empty.
- **J.8 amended**: a console MUST NOT offer a refresh without naming the
  directory it will re-read. A blind button is how this shipped.
- New acceptance criterion **F.29**.

**Changelog v0.24 → v0.25 — the first boot: a deployment that has nobody
yet must still be able to acquire somebody.**

Every version so far assumed the registry already had an administrator. It
does not on the day it is installed. A Station started on an empty volume
grants the environment super-admin `admin` on every forest *in the registry*
— of which there are none — so it authenticates and governs nothing, and
J.7 then refuses it the first forest because creating one requires `admin`
on a forest that already exists. The two rules are individually sound and
jointly a deadlock: the product cannot be reached through its own front
door on the one occasion every deployment goes through.

The fix is not a wider grant. It is recognising that **the authority to
start a forest cannot itself be derived from a forest**, and giving that
authority somewhere to live.

- **J.2.4 First-run setup.** While the registry holds no credential, the
  Station offers exactly one unauthenticated route that creates the
  **owner** — and it closes permanently, in the same transaction that
  creates them. This is the one place a second authentication path could
  hide, so its closing condition is normative and its race is specified,
  not left to implementation.
- **The owner is a property of the principal, not a sum of grants.** An
  owner holds `admin` on every forest **present and future**, including on
  none. Re-granting at boot was the alternative and it is wrong for the
  same reason the deadlock exists: it derives authority from the very
  thing the owner is needed to create.
- **J.7 amended.** Creating a forest requires `admin` on an existing forest
  **or** the owner bit. An unprivileged principal still never can.
- **J.2.1 amended.** The environment super-admin is demoted to what it was
  always described as: break-glass. It is no longer the documented way in,
  and while it is configured the setup route does not exist — one door at a
  time, so the two can never race for the same first identity.
- **J.5.6 The setup screen**, pre-identity like the Gate, and the optional
  seeded forest that makes an empty console teach something. The seed is
  never shipped as content: it is generated, outside the engine, by code
  that only calls public primitives.
- New acceptance criterion **F.28**.

**Changelog v0.23 → v0.24 — composing with review: the author sees the
passport before the forest keeps it.**

`compose` (v0.22) let a person post prose and have the Curator make a node
of it. It planted first and reported afterwards, so the summary that becomes
the scent every later hop navigates by, and the link proposals that become
the Ranger's working set, were facts before anyone had read them. Undoing
them meant editing a node that already existed.

- **J.8.1 Two-phase compose.** `stage: true` runs the whole pipeline —
  converter, curation, G.4.2.1 candidate proposals — and stops at the
  plant, returning the draft. A second call carrying `draft` accepts it.
  Nothing is planted, grafted or committed by the staging call.
- **Accepting re-runs the same pipeline, with the approval pinned.** The
  approved passport enters as an `on_curate` hook, so the plant, the commit
  and the content policy are the ones every adopted file gets. The model is
  not asked twice: it would answer differently, and what shipped would not
  be what was approved.
- **The reviewer's edits are re-validated, not trusted.** A returned draft
  is a client payload: summaries are re-clipped to the A.4 budget, tags
  re-cleaned and capped, and every link re-checked against the closed-
  candidate rules of G.4.2.1 — `related-to` only, existing and in-scope
  targets, never a branch, never self or parent, capped at 3, and pinned at
  confidence 0.3 whoever kept it.
- **Staging is not planting, and dry-run is a property of the Gardener.**
  `Gardener(dry_run=True)` cannot write: no plant, no graft, no body cache,
  no archived bytes, no config. The flag lives on the object rather than on
  a call so no path can forget it.
- New acceptance criterion **F.27**.

**Changelog v0.22 → v0.23 — the maintenance surface: the Ranger reports to
somebody.**

Part H gave the forest a Ranger and Part I gave it snapshots, and both have
been reachable only from a shell. The operator who most needs to know a
branch has grown too wide, or that a hundred link proposals are waiting, is
the one running a hosted Station — and they have a browser.

- **J.13 Maintenance surface.** `GET /v1/admin/health` returns the Ranger's
  H.3 report unchanged; snapshots can be created and listed over REST.
  Neither is a primitive and neither invents a number: the report is what
  `Ranger.health()` already computes.
- **Health is an owner's view, and says so.** The report counts and names
  things across the WHOLE forest — lint errors, fat nodes, stale passports —
  so it requires `admin` *and* an unrestricted scope. A scoped principal is
  refused with the reason rather than handed a filtered half-report whose
  numbers would quietly describe a forest they cannot see.
- **Restore stays on the command line, deliberately.** Part I restores a
  bundle into an *empty* destination; there is no in-place restore to offer,
  and a console button that always answers "target is not empty" would be a
  worse answer than no button. Disaster recovery is not a web workflow.
- New acceptance criterion **F.26**.

**Changelog v0.21 → v0.22 — Forest Views: the map becomes visible.**

Everything the Station serves has been legible to an agent and illegible to
a person. `look` returns a digest, `scan` returns a page, and neither ever
shows the shape of the thing being navigated. A forest is a graph with
heat on it; a console that can only render lists is describing a map by
reading out street names.

- **J.11 Map projections.** Two read-only endpoints — `GET /graph` and
  `GET /trails` — that project the Catalog (C.6.1) and the pheromone layer
  (Part D/H.1) as whole-of-region payloads. They add no primitive and no
  engine capability: everything they return is already reachable one node
  at a time through `look`/`move`/`scan`, and they are subject to the same
  J.3 filtering, including the recomputation of every derived count.
- **J.5.4 Forest Views.** The Explore console gains modes over one
  selection — graph, tree, files — and the file view renders each file as
  what it is: markdown rendered by default with the stored source one click
  away, a dataset payload as a browsable table, an HTML body as a page.
  Presentation only: no request, response or permission changes.
- **J.8's fourth mode, `compose`.** A person writes prose in the console
  and it enters the forest through the ingest pipeline that already exists
  — same converters, same curation, same commits — rather than through a
  second, unaudited door.
- **Editing is a write, not a save.** A console MAY offer rich editing of a
  node, and MUST express the result as `graft`/`tend` operations. Writing
  a node file directly is forbidden to every surface, the console included.
- New acceptance criterion **F.25** (a map projection discloses nothing a
  node-by-node walk would not).

**Changelog v0.20 → v0.21 — the Gauntlet: the vector layer moves from the
entry to the hand:**

Measurement (2026-08-08, bge-m3 on a local Ollama) established where the
dense layer helps and where it hurts, and the two answers are opposite:

| Corpus | BM25 R@1 | Hybrid R@1 |
|---|---|---|
| bench-forest, 18 v2 queries | 0.778 | **0.889** |
| forest-fixture, 10 demo queries | **1.000** | **0.400** |

RRF rewards *agreement*, not correctness. Fusing a fuzzy ranker into one
that is already right can only pull the answer away from rank 1 — on the
fixture it dropped `block-loop` from 1st to 4th while the vector list
surfaced the topically-adjacent `speculative-decoding`. So the published
hybrid row does not survive scent-weighted BM25, and v0.19's own
`{{TODO: hybrid re-run}}` is answered in the negative.

The same rule points at where the layer *does* pay. Entry search already
has a strong query-dependent ranker. **Navigation has none**: `look` orders
edges by heat (past usefulness), `scan` by degree (connectivity), `move`
not at all — every one of them blind to what is being hunted right now.
Adding a query-dependent signal there is not fusion; it is the first such
signal, with nothing to dilute.

- **Part K — the Gauntlet.** The forager carries the query vector and the
  *frontier* is ordered by proximity to it: which neighbours `look` shows
  within its edge cap, which children `scan` returns under its budget,
  which way `move` points. Cost is one query embedding per hunt, reused
  across every hop; per hop it is a dot product over vectors already in the
  Canopy — no HTTP, **no tokens**.
- **Strictly optional, and identical when absent.** No embedder, or no
  index, or a stale index ⇒ every primitive behaves exactly as in v0.20.
  Not degraded: identical. The Gauntlet MUST NOT become a dependency of
  navigation.
- **K.4 The mismatch guard**, a defect this work uncovered: the Canopy
  records the model that built it and *nothing compared it*. An index built
  with `bge-m3` queried by a `gemma4:12b` embedder reported `hybrid = True`
  and silently compared vectors from two different spaces. Now a mismatch
  disables the dense layer and says so.
- New acceptance criterion **F.24** (absent/stale embedder is byte-identical
  to v0.20; conditioning is visible in the response; mismatch disables and
  reports).

**Also in v0.21 — J.10.1, the provider the deployment already declared:**

A Station started with `MONKEYLLM_LLM_ENDPOINT` and its key has already
been told everything the console's provider form would ask for. Asking
again makes an operator copy a secret out of the place that governs it —
the environment, which the deployment rotates and never backs up — into a
place that does not.

- **J.10.1 Environment-declared providers.** They appear configured at
  boot, marked `origin: "env"`. The key is resolved from the environment at
  call time and **MUST NOT be written to the registry**. The console MUST
  refuse to edit or remove one — accepting would be undone by the next
  restart. A row whose declaration is withdrawn becomes an ordinary console
  row rather than being deleted with its bindings.

**Changelog v0.19 → v0.20 — one person, several forests, one decision:**

v0.19 made the *person* the unit of administration but left the grant step
naming a single forest, so a registry hosting six forests turned "give this
service read access to everything" into six visits to the same form — six
requests, six chances to stop halfway, and a token whose real reach was
never visible in one place. The person was one thought; their access was
still shaped like one row of the grants table.

- **J.2.3 `grant` and `revoke_access` take one forest or several.** `grant`
  MAY carry `forests: [<id>, …]` instead of `forest: <id>`, and
  `revoke_access` MAY carry a list. The scalar forms remain valid and mean a
  one-element list, so every existing client keeps working.
- **A list is not a relaxation.** Each named forest is authorised on its
  own (`admin` on *that* forest), applied on its own, and refused on its
  own — a refusal names the forest and MUST NOT discard the forests the
  caller was entitled to grant. This is J.2.3's partial-application rule
  applied within a step rather than only between steps.
- **Scope prefixes are forest-local.** `allow`/`deny` apply to every forest
  named in the same grant, because a grant is one policy. Branch names are
  not portable between forests, so the console offers the branch picker only
  when exactly one forest is selected and grants the whole forest otherwise
  (J.5.5) — the API does not second-guess a caller that knows better.
- **What did NOT change:** the escalation rule (J.2.2). A key still
  authenticates a principal, so minting one still requires `admin` on
  **every** forest that principal holds — which is precisely why the grant
  step has to be able to say "these forests" in one request that the
  administrator of all of them can make.
- Criterion **F.23** extended: a multi-forest grant lands on every forest
  the caller administers, refuses the ones it does not by name, and the
  resulting token reads in each granted forest.

**Changelog v0.18 → v0.19 — governance is organised around people:**

The host grew three governance objects — grants, passwords, API keys — and
the console grew one screen per object. That is the storage model wearing a
navigation bar. Nobody administers a *grant*; they onboard a **person**, and
onboarding is one thought: this is who they are, this is what they may see,
here is how they sign in, here is a token for their script. Splitting that
across three destinations made the operator hold the model in their head
instead of the interface holding it for them.

- **J.2.3 `POST /v1/admin/people`** — one call applies any combination of
  grant, revoke-access, password and token changes to one person, so the
  console can offer onboarding as a single form. It is a **composite, not a
  new authority**: each part re-checks the rule that already governed it,
  and the parts apply in an order that makes a first-time grant usable
  (grant first, so a brand-new principal becomes administrable and can then
  receive a password and a key in the same request).
- **`GET /v1/admin/people`** — the person-shaped read the console needs:
  identity, grants, password presence, tokens and last-seen in one object,
  filtered by J.3.2. Assembling this client-side from three endpoints made
  the console's shape depend on the registry's.
- **J.5.5 The People console** replaces the separate Access and Tokens
  screens: a list of people, a detail view per person carrying everything
  about them, and a credential-shaped tab for the operator who wants to
  audit tokens rather than people.
- **What did NOT change:** every enforcement rule. `admin` on the forest to
  grant, `administers_fully` to touch a credential, the environment account
  refusing a stored password, per-forest filtering on read. A convenience
  endpoint that relaxed any of them would be a new way in wearing the
  clothes of a better form.
- New acceptance criterion **F.23** (the composite performs each part under
  its own rule and refuses the parts it may not do without abandoning the
  parts it may; onboarding in one call yields a working sign-in and a
  working token).

**Changelog v0.17 → v0.18 — administration stops being global:**

Asking "should the console hide what a person cannot do?" turned into an
audit of every host route, and the audit found the real defect. Every
`/v1/admin/*` route correctly refuses a non-administrator — but it treated
`admin` **on any forest** as a licence to read **every** forest's
governance data. An administrator of one forest could list every principal
in the registry with their exact branch prefixes, and read the complete
audit log of forests they cannot open. J.2.2 already closed this shape for
API keys; the same reasoning was never carried to the rest.

- **J.3.2 Administration is per forest.** Holding `admin` somewhere admits
  a caller to a host route; it never entitles them to rows about forests
  they do not administer. Every host route MUST filter its result to those
  forests, and a route that cannot be filtered MUST require admin
  everywhere instead.
- **J.5.1 revised** — a console the principal cannot use is now **omitted
  from navigation** rather than shown with an explanation. Corporate
  operators read a menu as a list of what they may do, and an entry that
  only ever refuses teaches nothing that a support conversation would not
  teach better.
- **Hiding is presentation and MUST NOT be the control.** The view keeps
  its own capability guard, and the API remains the authority: navigation
  is a convenience over a decision the server already made and would make
  again for a request the console never sent.
- New acceptance criterion **F.22** (every host route refused without the
  capability; per-forest filtering proven with a two-forest registry and a
  partial administrator; navigation contains exactly the permitted
  consoles).

**Changelog v0.16 → v0.17 — credentials get a front door and a lifecycle:**

v0.16 made the console usable; it left the credential that opens it with no
story at all. A key was minted by a CLI or hidden inside the grant form,
never listed, never expiring, never revocable, with no record of last use —
and the only way into the console was to paste one. That is the opposite of
governance: the object that grants access was the one object the governance
console could not govern.

- **J.2.1 Two doors, one identity.** `POST /v1/auth/login` exchanges a
  username and password for a **session token**, which is an ordinary API
  key with a short lifetime. Machines keep pasting keys. Both arrive at the
  same `authenticate()` and the same J.3 policy, so there is exactly one
  authorization path no matter which door was used.
- **The environment super-admin** — `MONKEYLLM_STATION_ADMIN` and
  `MONKEYLLM_STATION_PASSWORD` — is verified against the environment and
  never stored: it is break-glass, and hashing a value that already sits in
  the environment protects nothing while giving a rotation two places to go
  wrong.
- **J.2.2 Token lifecycle** — label, expiry, revocation, last use, and a
  non-secret prefix so a token can be recognised in a list without being
  disclosed. Expired and revoked keys MUST fail authentication, which is
  where a lifecycle either exists or does not.
- **The escalation rule that makes delegated token issuance safe:** minting
  or revoking a key for a principal requires `admin` on **every** forest
  that principal holds a grant on — not merely on one of them.
- **J.5.4 Tokens console**, and the explicit ruling that there is **no
  second, super-admin panel**: one console over one API, with capabilities
  deciding what appears. A second panel needs a second authentication path,
  and a second authentication path is where the backdoor goes.
- New acceptance criterion **F.21** (login, session expiry, revocation,
  last-use, prefix-only listing, and the cross-forest escalation refusal).

**Changelog v0.15 → v0.16 — the console becomes usable by someone who has
not read this document:**

v0.14 and v0.15 gave the Station a front door and a choice of reader. Both
were specified from the storage model outward, and the console inherited
that: it asked an operator for capability sets and comma-separated branch
prefixes, offered no way to start a forest or put anything into one, and
spoke one language in one theme. A governed knowledge base that only its
own author can operate is not a product. v0.16 specifies the console as a
first-class contract rather than a rendering of the registry.

- **J.5 rewritten** — a normative information architecture (nine consoles
  in three groups), the rule that **the console MUST address the operator
  in the operator's vocabulary**, not the policy model's, and two
  requirements the previous version left to taste: localisation
  (English, Portuguese, Spanish) and both light and dark presentation.
  The no-side-channel rule is unchanged and now explicitly covers strings:
  a translation MUST NOT alter what a surface returns.
- **J.7 Forest lifecycle** — `POST /v1/admin/forests`, so a deployment can
  reach its second forest without shell access to the volume. Creation is
  A.5 `init_forest` and nothing else; the id is validated against path
  escape before it is a path, and the creator is granted the forest so a
  newly created forest is never orphaned.
- **J.8 Ingest surface** — the Gardener (Part G) reached over REST, with
  `adopt`, `sync` and a **staged upload** for operators who have a browser
  and no shell. Requires the `ingest` capability; the destination branch is
  scope-checked, so ingest cannot be used to write where reads are denied.
- **The naming reuse, stated plainly:** J.7 named "out of scope for Part
  J" in v0.14 and became J.11 in v0.15. In v0.16 the free slot is reused
  for the forest lifecycle. Cite J.11 for the exclusions.
- New acceptance criterion **F.20** (console: every string localised in all
  three languages, both themes, and the scoped principal's console shows a
  scoped world; forest creation refuses path escape; ingest refuses to
  write outside scope).

**Changelog v0.14 → v0.15 — J.10, per-forest inference (the forest picks its
own model):**

Part J gave forests a front door; v0.15 lets each one choose who reads it.
A forest is not one workload: ingest wants a careful summariser whose output
every later hop navigates by, while answering wants a fast reader that
follows instructions. One global `MONKEYLLM_LLM_*` cannot express that, and
it cannot express "this corpus stays on a local endpoint while that one uses
a hosted model" either.

- **J.10 Providers and role bindings** — operators register any
  OpenAI-compatible `/v1` (OpenRouter, LiteLLM, vLLM, local llama.cpp) in
  the host registry, then bind a model per `(forest, role)` with
  `role ∈ {ingest, answer}`. Credentials are write-only across every
  surface: the API accepts a key and reports only whether one is set.
- **J.10.3 Model-backed composites** — `answer` (retrieval + the forest's
  answering model, returning a grounded reply with its evidence) and
  `curate` (re-summarise a node through the ingest model, under the A.4
  scent rules). Both are host composites, not primitives: the engine gains
  nothing.
- **The invariant that makes this safe:** the retrieval half runs through
  `ScopedVine` *before* the model is called, so a bound model only ever
  sees material the principal could already read. Binding a model MUST NOT
  become a way around J.3.
- New acceptance criterion **F.19** (secrets never returned; bindings
  refuse unknown providers/roles; the answering model receives only
  in-scope material).

**Changelog v0.13 → v0.14 — Part J, the Station (the forest gets a front
door):**

Everything up to v0.13 assumes one operator who owns the filesystem.
Corporate self-hosting needs the shape the database products converged on:
an untouched engine wrapped by a host that adds identity, policy, audit and
a friendly surface. Part J specifies that host — and specifies it as a
**privileged client**, not an extension: the engine gains nothing, loses
nothing, and its test suite MUST pass unedited.

- **J.1 The Station** — one self-hostable service mounting a forest
  registry (the `--root` resolution that already exists) and exposing
  three surfaces — REST, MCP, Studio — over exactly one enforcement core.
  No surface may reach an unscoped `Vine`.
- **J.2 Identity** — principals (users and service tokens), per-forest
  roles, API keys now and OIDC later. Identity and policy live in the
  **host registry**, never inside a forest: forests are content.
- **J.3 Policy (`ScopedVine`)** — deny-by-default grants over **branch
  prefixes** plus a capability set, with one enforcement rule per
  primitive. Two invariants make it trustworthy rather than merely
  configured: scope filtering MUST precede budgeting (no truncation
  oracle) and out-of-scope MUST be indistinguishable from absent (no
  existence oracle) — including through `move`'s edges, which would
  otherwise leak a forbidden node's existence.
- **J.4 Audit** — writes stay git commits, now stamped with the acting
  principal; reads extend the Part D telemetry with principal identity.
- **J.5 Studio** — the web console, itself a plain REST client with no
  privileged side-channel.
- New acceptance criterion **F.18** (the leak suite: one test per
  primitive per surface, plus the two oracle invariants).

**Changelog v0.12 → v0.13 — branch rollup + Landmarks (the map grows a
sense of place):**

The branch hierarchy already occupies the position that graph-RAG systems
pay dearly to discover (hierarchical communities); what it lacked was
synthesized content at each level. Two additions, zero new primitives:

- **G.4.4 Branch rollup** — after adopt/sync curation, the Gardener MAY
  synthesize branch (`_index.md`) frontmatter summaries bottom-up (deepest
  branch first) from the children's entry lines. Scope is strictly
  branches with `source: ingest` (hand-authored branch summaries are never
  rewritten; an explicit `--all` override exists). A.4 summary rules apply
  (validate-and-retry); LLM failure falls back to a deterministic composed
  summary and never blocks (same posture as G.4.2). Writes go through the
  C.8 `graft` path, so verbatim propagation into parent index entries and
  `.md`-only commits are inherited, not reimplemented. Rollup cost is
  O(branches), not O(nodes) — the lazy end of the graph-RAG spectrum.
- **A.5 entry-sync rule tightened** — when a summary change propagates
  into a `## Sub-branches` entry, the entry's trailing coverage suffix
  (`. N bananas, M sub-branches.`) MUST be preserved (previously it was
  silently dropped by the sync rewrite).
- **A.5 `## Landmarks` implemented as a Ranger duty (H.7)** — the master
  `_index.md`'s Landmarks section (already normative since v0.5) is now
  populated mechanically: top 10-20 highest-degree non-branch nodes from
  the catalog's edges table, entry lines with summaries, idempotent
  refresh through the audited `.md`-only path (`ranger(landmarks): …`).
  Zero LLM involvement.
- New acceptance criterion **F.17** (rollup scope/fallback/propagation +
  Landmarks idempotence).

**Changelog v0.11 → v0.12 — Gardener v2: native DOCX + edge proposals (the
forest starts weaving itself):**

Two Gardener extensions, both strictly inside the edges-only surface (G.2):

- **G.2.1 DOCX built-in converter** — `.docx` joins the built-ins when
  `python-docx` (MIT; lxml, BSD) is importable, mirroring the `openpyxl`
  pattern. Single-pass `w:t` traversal in document order: body paragraphs
  (style-mapped headings), tables (→ pipe tables), and text inside embedded
  text boxes (`wps:txbx` / legacy `v:textbox`); fragmented runs merge
  naturally by joining a paragraph's `w:t` descendants. Headers/footers are
  EXCLUDED (page-number/letterhead boilerplate is scent noise). Technique
  derived from the owner's pdf-replace project (MIT-clean reading side).
  No `python-docx` → `.docx` files report `unsupported`, never a crash.
- **G.4.2.1 Edge proposals** — LLM curation MAY now propose `related-to`
  links from the adopted node to EXISTING nodes, each carrying link-level
  `confidence: 0.3` (the C.8 ladder's bottom rung). Candidates come from
  the catalog (BM25 over curated metadata); the model can only pick from
  the offered list — a hallucinated target is structurally impossible.
  This closes the loop with Part H: the Gardener proposes, usage heats,
  the Ranger promotes (0.8) or prunes. Entity EXTRACTION (creating new
  `entity` nodes) stays deferred: it needs a placement policy and a
  `same-as` dedup story first.
- New acceptance criterion **F.16** (DOCX fidelity + proposal guard rails).

**Changelog v0.10 → v0.11 — the map is not the territory (tiered storage,
big sources, S3-ready):**

A 2 TB source must not require 4 TB locally. The forest splits into three
tiers — SCENT (passports: summaries/outlines/links, ~0.1% of source size,
always local, in git), FLESH (converted full text, ~1-5%, local, git or
derived cache), BONE (raw binaries, 95%+, stay at the source / object
storage, fetched rarely). New normative items:

- **G.7 Content & archive policies** — per-adoption `content:
  inline | cached | reference` and `archive: never (default) | always`.
  Non-inline bodies are resolved lazily by `pick`/`sniff`; the map
  (locate/look/scan, heat, curation) never needed the body and is
  unaffected. `archive: never` kills the redundant `_assets/` copy when
  the source is durable.
- **G.8 Targeted sync & triggers** — `sync(path=...)` reprocesses a single
  source file; an mtime+size fast-path avoids re-hashing unchanged trees.
  Event sources (filesystem watchers, S3/Drive push notifications) are
  EDGES that call targeted sync; **events trigger, the hash-diff
  reconciler stays authoritative** (lost events are healed by the next
  full sync).
- **G.9 Payload fetchers** — `payload`/`source_path` MAY carry a scheme
  (`file://` implicit; `s3://` via optional MIT extra). Remote payloads
  download on first use into `_derived/payloads/` (hash-validated cache).
  Dataset `.db` files are **local-first by design** (SQLite cannot be
  queried remotely; hot knowledge bases need sub-ms reads) — object
  storage holds them only as backup/cold tiers.
- **H.6 Cache eviction** — the Ranger evicts cold entries from
  `_derived/payloads/` (LRU by last access; config `payload_cache_gb`).
- **Part I — Snapshots**: `vine snapshot create|restore` packages the
  forest as a `git bundle` (full commit history travels along) +
  compression, optionally uploaded to object storage; payload sidecar
  optional. The Ranger MAY schedule snapshots (backup policy).
- Informative (G.4 note): **progressive curation** — adopt the skeleton
  deterministically first (the engine answers immediately with weak
  scent), then LLM-curate as a background queue prioritized by heat: the
  pheromone tells the Gardener where to polish first. Querying an
  UNMAPPED source per-question is the anti-pattern this project exists to
  kill (O(corpus) per question vs O(corpus) once + O(hops) per question).
- New acceptance criterion **F.15** (policies + targeted sync; fetcher/
  snapshot coverage lands with their implementations).

**Changelog v0.9 → v0.10 — Part H: the Ranger (long-term maintenance — the
forest forgets, confirms and warns):**

The pheromone layer only compounds if it can also FORGET: without
evaporation every trail saturates at 1.0 and heat stops carrying signal;
without pruning, agent proposals (confidence 0.3/0.5) accumulate as noise.
New normative items:

- **Part H (Ranger)** — the maintenance daemon: heat evaporation with a
  configurable half-life over `_derived/trails.db` (H.1); promotion and
  pruning of uncertain links — links born with link-level
  `confidence < 1.0` are the ONLY Ranger-managed edges (H.2); a read-only
  health report: `needs_split`, fat nodes, lint issues, stale passports,
  low-confidence inventory (H.3); on-demand run + service loop (H.4).
- Ranger is **trusted infrastructure** (like the Gardener): evaporation
  touches only the derived layer (no commits — `_derived/` is disposable);
  promotion/pruning write through the audited `.md`-only path with commit
  messages `ranger(promote): …` / `ranger(prune): …`.
- The Ranger NEVER deletes nodes, never touches structural edges or any
  link without a link-level confidence field, and never performs `same-as`
  physical compaction (still human-approved, still out of scope).
- New acceptance criterion **F.14** (synthetic-clock evaporation,
  promotion/pruning safety, health report).

**Changelog v0.8 → v0.9 — Part G: the Gardener (brownfield ingest, the
forest learns to grow itself):**

The dominant real-world scenario is **adoption**: the engine is pointed at a
directory tree already full of documents ("mata alta") and must curate all
of it — then notice when source files change. New normative items:

- **Part G (Gardener)** — the ingest pipeline: passport policy (G.1),
  public converter contract with three discovery sources — forest-config
  command hooks, `monkeyllm.converters` entry points, built-ins (G.2);
  `adopt` (mirror an existing tree: folders → branches, files → passports,
  deterministic placement) and `sync` (hash-diff incremental update) (G.3);
  curation stage with forest-level curation config and `on_curate` hooks —
  the only LLM-dependent stage, always skippable (G.4); media via the same
  converter contract: transcript/description is the body, the raw asset is
  the payload (G.5).
- **C.7.1 extension: initial `rows` at birth** — `plant` of a dataset MAY
  carry `rows` per table, inserted **parameterized** (never SQL text) before
  `payload_hash` is computed. Bulk loads bypass neither the schema
  validation nor A.3.1 — and avoid `tend`'s keyword scanner false-positives
  on arbitrary data.
- **Extension surface is edges-only (normative)**: plugins exist for what
  goes IN (converters, curation hooks). The primitives' semantics, budgets
  and security guards are NOT extensible. UIs/automations (dashboards,
  upload bots) are *clients* of the MCP server or the library — they need
  no plugin API.
- New acceptance criterion **F.13** (adopt/sync end-to-end).

**Changelog v0.7 → v0.8 — dataset birth: declarative schema in `plant`
(Phase 2, the living bank grows its own organs):**

`tend` (C.10) writes rows into datasets that already exist; until now no
primitive could *create* a dataset — the `.db` was born only in offline
generators. v0.8 closes the loop so an agent can collect data (web, PDFs,
conversations), give it a structured home, and fill it — all through the
primitives. Normative items:

- **C.7.1 Dataset planting** — `plant` of a `type: dataset` node accepts an
  optional **declarative `schema`** object (tables → columns → types). The
  Vine generates the DDL itself (names regex-validated, types from an
  allowlist), creates the SQLite payload, computes `payload_hash`, and
  auto-generates the `## Query manual` body section from the schema. **No
  raw DDL ever comes from the model** — creation-time structure is data,
  not SQL.
- **`tend` is unchanged**: DDL stays forbidden there forever. The separation
  is temporal — creation (rare, structured, validated whole) vs operation
  (frequent, single-statement DML). `ALTER TABLE` after birth is out of
  scope (plant a new dataset and migrate, or wait for the Gardener).
- A.3.1 holds with zero new machinery: the payload is created on the
  filesystem, only the `.md` (with `payload` + `payload_hash`) is committed.
- New acceptance criterion **F.12** (schema validation, payload creation,
  auto manual, atomic rollback — covered by tests).

**Changelog v0.6 → v0.7 — `tend`: dataset writes (Phase 2 entry, the living
bank):**

`query` stays read-only by design; agent writes to dataset payloads get
their own primitive with a hard guard rail. New normative items:

- **C.10 `tend(id, sql)`** — the 10th primitive: single-statement
  INSERT/UPDATE/DELETE on a `type:dataset` node's SQLite payload, with an
  audit commit of the node's `.md` (`payload_hash` refresh) — the binary
  still never enters git (A.3.1 unchanged). Full contract in C.10.
- **Lint: payload drift warning** — `vine validate` MUST warn when a node's
  `payload_hash` no longer matches the payload file's sha256 (completes the
  A.3 drift-detection promise; `tend` keeps the hash fresh, out-of-band
  edits become visible).
- New acceptance criterion **F.11** (tend guard rails + audit, covered by
  tests).

**Changelog v0.5 → v0.6 — shout trigger measures the real trail (Part D):**

The shout never fired in practice: 39 successful hunts across the fixture and
the bench forest produced zero shortcut suggestions. Root cause: the trigger
reused `hops-to-banana`, which counts only `look`+`move` calls before the
FIRST `pick`/`query` — but agents traverse deep chains with **pick chains**
(`locate → pick → pick → pick`), so the counter stays at 0–2 even on long
winning trails. Normative changes:

- New session metric **`trail_len`**: the number of traced read-primitive
  calls (`locate`, `sniff`, `look`, `move`, `scan`, `pick`, `query`) made
  strictly BEFORE the first harvest (`pick`/`query`) of a node listed in
  `outcome.answer_nodes`. `null` when no answer node was harvested.
- `close_session` MUST suggest shortcuts (`suggest_shortcuts`) when
  `trail_len >= 4` (threshold unchanged). The shout edge itself is still the
  orchestrator's decision (C.8 reinforce-before-create applies).
- **`hops-to-banana` is unchanged** (look+move before the first harvest) —
  it stays a Monkey Bench metric for longitudinal comparability; it is no
  longer the shout trigger.

**Changelog v0.4 → v0.5 — canonical English vocabulary (normative):**

The tool's vocabulary is English. Every contract token that was Portuguese
is renamed; the Portuguese tokens are **removed** (clean break, pre-release —
no alias layer). A forest MAY still declare extra types/rels of its own in
`_meta/schema.md` (the dialect stays data-driven), but everything the Vine
hardcodes, emits or parses now uses the English tokens below.

| Kind | v0.4 (removed) | v0.5 (canonical) |
|---|---|---|
| node type | `galho` | `branch` |
| node type | `nota` | `note` |
| node type | `documento` | `document` |
| node type | `entidade` | `entity` |
| node type | `conceito` | `concept` |
| node type | `evento` | `event` |
| node type | `midia` | `media` |
| node type | `dataset` | `dataset` (unchanged) |
| rel | `parte-de` / `contem` | `part-of` / `contains` |
| rel | `relacionado-com` | `related-to` |
| rel | `mencionado-em` / `menciona` | `mentioned-in` / `mentions` |
| rel | `autor` / `autor-de` | `author` / `author-of` |
| rel | `comparado-com` | `compared-with` |
| rel | `derivado-de` / `origem-de` | `derived-from` / `origin-of` |
| rel | `same-as` | `same-as` (unchanged) |
| rel | `atalho-descoberto` | `discovered-shortcut` |
| rel | `sucede` / `precede` | `succeeds` / `precedes` |
| `entity_kind` | `pessoa`, `organizacao`, `produto`, `lugar`, `outro` | `person`, `organization`, `product`, `place`, `other` |
| `source` | `agente` | `agent` (`manual`, `ingest` unchanged) |
| A.5 heading | `## Sub-galhos` | `## Sub-branches` |
| A.5 heading | `## Bananas diretas` | `## Direct bananas` |
| A.5 heading | `## Trilhas cruzadas` | `## Cross trails` |
| A.5 heading | `## Landmarks` | `## Landmarks` (unchanged) |
| `coverage` format | `"N bananas, M sub-galhos"` | `"N bananas, M sub-branches"` |
| dataset body section | `## Manual de consulta` | `## Query manual` (source of C.2 `query_manual`) |
| A.4 anti-patterns | "este documento descreve", "arquivo contendo" | "this document describes", "file containing" |
| C.8 shout metadata | `discovered_by: agente` | `discovered_by: agent` |

Test data remains Portuguese where it is content (fixture corpus prose,
titles, summaries, ids, tags, demo/bench questions and prompts); only the
structural tokens above change there.

**Changelog v0.3 → v0.4:**

- **C.0 Forest registry (multi-forest serving)**: one MCP server MAY host many
  forests under a root directory (`vine serve --root DIR`). Every tool gains
  an optional trailing `forest: string` parameter selecting the target forest;
  a new `forests()` tool lists what the registry serves. Forests open lazily
  on first touch (auto-index included). Single-forest mode (`--forest`) keeps
  the previous behavior — `forest` is optional there — so v0.3 clients are
  not broken.
- New acceptance criterion F.10 (registry: selection, lazy open, path safety,
  single-forest backward compatibility).

**Changelog v0.2 → v0.3:**

- New composite MCP tool **C.6c `harvest`**: zero-LLM, one-shot retrieval for
  clients that bring their own model. Fuses `locate` + `sniff` (RRF), returns
  ranked bananas with full body or matched sections plus exact snippets.
  It is an orchestration over existing primitives — the nine primitive
  contracts are untouched.
- Three integration modes documented (C.6c intro): direct navigation
  (client LLM drives the primitives), harvest (one call, evidence back),
  concierge (local SLM hunts and answers). Configuration picks the default;
  the MCP client's LLM may choose per call.
- New acceptance criterion F.9 (harvest quality + budget).

**Changelog v0.1 → v0.2:**

- New read primitive **C.6b `sniff`** (the sniffer): literal search over node **bodies**, returning node + section + snippet. Complements `locate` (which stays restricted to curated metadata — C.1 contract intact) covering the case "exact term buried in the body, invisible to summary/tags".
- **A.3.1 Binary payload policy**: binaries never enter the forest's Git — Vine versions `.md` only (enforced at the commit layer); payloads are referenced by `payload` + `payload_hash` and excluded by the forest's `.gitignore`.
- Acceptance criterion F.1 updated to include C.6b; new criteria F.7 (sniff quality) and F.8 (payloads outside Git).
- Nothing else changes: every other contract is identical to v0.1 (which stays archived for history).

---

## Part A — The Forest Dialect (`_meta/schema.md`)

`schema.md` is a living file inside the forest that declares the valid types. The Vine MUST validate every write (`plant`/`graft`) against it. The agent MAY read it via `look("_meta/schema")` to learn the dialect in 1 hop.

### A.1 Node types (`type`)

| `type` | Description | Payload | Harvest verb |
|---|---|---|---|
| `branch` | Index file (`_index.md`) of a folder | — | `look` |
| `note` | Free-text knowledge (default banana) | — | `pick` |
| `document` | Converted document (PDF/DOCX origin) | original in `_assets/` | `pick` |
| `dataset` | Tabular data | sibling SQLite (`.db`) | `query` |
| `entity` | Person, organization, product, place (subtype in `entity_kind`) | — | `pick` |
| `concept` | Definition / technical term | — | `pick` |
| `event` | Dated fact (meeting, decision, release) | — | `pick` |
| `media` | Image/audio/video with description or transcript | original in `_assets/` | `pick` |

Rules:
- New types MUST be added to `schema.md` before first use; the Vine rejects an unknown `type` (`E_SCHEMA` error).
- `entity` MUST have `entity_kind` ∈ {`person`, `organization`, `product`, `place`, `other`}.

### A.2 Edge types (`rel`)

Edges are directed, typed, and declared in the source node's frontmatter (`links:`). The derived layer materializes the inverses automatically.

| `rel` | Inverse (derived) | Semantics |
|---|---|---|
| `part-of` | `contains` | Logical hierarchy (not the physical folder hierarchy) |
| `related-to` | `related-to` | Generic association (symmetric) |
| `mentioned-in` | `mentions` | Entity cited in a document |
| `author` | `author-of` | Authorship |
| `compared-with` | `compared-with` | Technical contrast (symmetric) |
| `derived-from` | `origin-of` | Provenance (note derived from document, dataset from export, etc.) |
| `same-as` | `same-as` | **Soft merge** of duplicate entities (symmetric) |
| `discovered-shortcut` | — | The monkey's shout (created by `graft`, see Part C.8) |
| `succeeds` | `precedes` | Temporal order between events/versions |

Rules:
- A `rel` outside this table → `E_SCHEMA` error (the table grows by editing `schema.md`, never ad-hoc).
- `same-as` MUST NOT delete nodes; physical merging is the Ranger's compaction alone (out of Phase 0 scope).
- Maximum of 50 `links` per node; above that the node is a candidate to become a branch (signal for the Ranger).

### A.3 Normative frontmatter

Fields required on **every** node:

```yaml
id: string            # stable slug, unique in the forest, = relative path without .md
type: string          # one of the A.1 types
title: string         # human title (mutable; id never changes)
summary: string       # 1-3 sentences, <= 60 tokens. THE SCENT. See A.4.
created: date         # ISO 8601
updated: date         # ISO 8601, refreshed on every graft
```

Optional fields:

```yaml
tags: [string]            # free vocabulary, lowercase, no accents
links: [{rel, target}]    # typed edges (A.2)
confidence: float         # 0.0-1.0; default 1.0; <1.0 = unconfirmed knowledge
source: enum              # manual | ingest | agent
payload: string           # sibling file name (datasets/media)
payload_type: enum        # sqlite | pdf | docx | image | audio
payload_hash: string      # sha256 of the payload (drift detection)
entity_kind: enum         # only for type: entity
aliases: [string]         # alternate names (used by lexical locate)
```

Rules:
- `id` is immutable. Renaming = creating a new node + `same-as` + tombstone (out of Phase 0 scope; renaming is forbidden in Phase 0).
- The parser MUST reject invalid frontmatter with `E_FRONTMATTER` and the field's path.

#### A.3.1 Binary payload policy (v0.2)

Binaries **never enter the forest's Git**. Normative:

1. The Vine MUST NOT version anything beyond `.md`: `plant`/`graft` stage only markdown files (hard guard at the commit layer, not convention).
2. The forest's `.gitignore` MUST exclude binary payloads (`*.db`, `*.sqlite`, `_assets/`), plus `_derived/` and `.vine.lock`.
3. The payload lives on the filesystem next to the node (or in external storage, in future phases) and the **node** versions only the reference: `payload` (name) + `payload_hash` (sha256). Binary drift is detected by hash, not diff.
4. Rationale: Git delta-compresses text, not binaries — frequently updated payloads would blow up the repository. The versioned knowledge is the distilled layer (markdown); heavy data is referenced, not embedded.

### A.4 The `summary` specification (the most critical component)

The `summary` MUST let an SLM decide "does this node matter to me?" without opening the body. Normative format:

1. **Sentence 1:** what it is (category + subject).
2. **Sentence 2:** the key content (concrete numbers, names, time scope).
3. **Sentence 3 (optional):** what is NOT here / where the complement lives.

- Limit: 60 tokens (validated by the Vine at `plant`).
- FORBIDDEN: "This document describes...", "File containing..." (anti-patterns that spend tokens without scent).
- Good: `"Sales by region and SKU, Jan-Mar 2026, 14,302 rows with margin and channel. Does not include returns (see sales/returns-q1)."`

### A.5 The `_index.md` specification (branch)

Required structure, in this order:

```markdown
---
id: <folder>/_index
type: branch
coverage: "N bananas, M sub-branches"
updated: <date>
---

# <Region title>

> <1-2 sentences: what lives here + where to go if not here>

## Sub-branches
- [[<id>]] — <sub-branch summary>. <coverage>.

## Direct bananas
- [[<id>]] — <summary copied from the banana's frontmatter>

## Cross trails
- <reason> → [[<id>]]
```

Rules:
- Entries replicate the child nodes' `summary` VERBATIM (the Gardener/Vine keeps sync; humans do not hand-edit these lines).
- Sync rewrites of a `## Sub-branches` entry MUST preserve the trailing coverage suffix (`. N bananas, M sub-branches.`) — v0.13.
- A branch's frontmatter `summary` MAY be synthesized bottom-up by the Gardener from the children's entries (G.4.4) when the branch was born from ingest; hand-authored branch summaries are never rewritten.
- A branch with > 150 entries or > 3,000 tokens → `needs_split` flag for the Ranger.
- The master branch (`/_index.md`) MUST additionally contain a `## Landmarks` section (10-20 highest-degree nodes, with summary). The Ranger keeps it fresh mechanically (H.7, v0.13): top non-branch nodes by degree over the typed-edge table, idempotent, audited `.md`-only commit.

---

## Part B — Identity, Trail and Addressing

- **Canonical ID:** path relative to the root, without extension. E.g.: `projects/mixerllm/architecture`.
- **Trail:** list of IDs from the root to the node. E.g.: `["_index", "projects/_index", "projects/mixerllm/_index", "projects/mixerllm/architecture"]`.
- Wikilinks in the body use `[[id]]` or `[[id|text]]`. The parser resolves `[[...]]` only against canonical IDs (no fuzzy match — ambiguity is a Ranger lint error, not runtime guessing).

---

## Part C — Primitive Contracts (Vine server, MCP)

Transport: MCP (stdio for dev; HTTP/SSE on Docker). All responses in JSON. Errors follow `{error: {code, message, hint}}` with codes `E_NOT_FOUND`, `E_SCHEMA`, `E_FRONTMATTER`, `E_READONLY`, `E_QUERY_FORBIDDEN`, `E_TIMEOUT`, `E_LOCKED`.

### C.0 Forest registry — multi-forest serving (v0.4)

The product is filesystem-native: a folder is a forest, its `_index.md` is
the door. One server therefore serves N forests; the request picks one.

Server modes:

- **Single-forest** (`vine serve --forest DIR`): the v0.3 behavior. The
  `forest` parameter is optional everywhere; when present it MUST match the
  served forest's name (else `E_NOT_FOUND`).
- **Registry** (`vine serve --root DIR`): every subdirectory of `DIR`
  containing an `_index.md` is a servable forest, identified by its path
  relative to the root (nested ids like `clients/acme` are allowed). The
  `forests()` tool lists direct children; `forest` is REQUIRED on every other
  tool (`E_SCHEMA` with the available ids as hint when missing).

Rules (normative):

1. **Lazy open + auto-index**: a forest is opened on first touch; an empty
   catalog triggers a full reindex (Vine's standard first-touch behavior).
   Opened forests stay open for the server's lifetime; each has its own
   catalog, trails, tracer session and (when writable) writer lock.
2. **Path safety**: the resolved forest path MUST stay inside the root —
   `..`, absolute paths or symlink escapes are `E_NOT_FOUND`. A directory
   without `_index.md` is not a forest (`E_NOT_FOUND`).
3. **Isolation**: pheromone, traces and indexes never leak across forests
   (they live in each forest's own `_derived/`).
4. `forests()` → `{"forests": [{"id", "active"}], "mode": "registry"|"single"}`
   where `active` means already opened in this server.

```json
{"tool": "locate", "args": {"query": "...", "forest": "clients/acme"}}
```

Cross-cutting principle: **every response MUST fit the declared token budget**. The Vine truncates with an explicit `"truncated": true` marker — never silently.

### C.1 `locate(query: string, k: int = 5, scope: "all"|"branches"|"bananas" = "all", type_filter?: string) → LocateResult`

The **helicopter**: a location engine that drops the monkey in the region closest to the target — it never starts from the trunk. RRF fusion of vector search (over summaries) + BM25 (over title, aliases, tags, summary). In Phase 0, MAY be BM25-only (SQLite FTS5); the interface does not change once vectors land.

The index covers **two levels**: bananas (leaves) and branches (regions — every branch has its own summary, hence indexable). A branch result = **landing zone**: the monkey lands in the right region and navigates 1-2 hops with local context, instead of dropping onto a possibly wrong leaf. `scope: "branches"` is useful for broad questions ("what do we know about sales?"); `scope: "bananas"` for pointed ones.

```json
{
  "results": [
    {
      "id": "sales/_index",
      "kind": "branch",
      "type": "branch",
      "title": "Sales",
      "summary": "...",
      "trail": ["_index"],
      "coverage": "23 bananas, 4 sub-branches",
      "score": 0.91,
      "heat": 0.40
    },
    {
      "id": "projects/mixerllm/architecture",
      "kind": "banana",
      "type": "document",
      "title": "MixerLLM Architecture",
      "summary": "...",
      "trail": ["_index", "projects/_index", "projects/mixerllm/_index"],
      "score": 0.82,
      "heat": 0.31
    }
  ],
  "truncated": false
}
```

Budget: <= 800 tokens. Ordering: `score_final = rrf_score x (1 + alpha*heat)`, alpha default 0.3 (configurable; alpha=0 turns pheromone off).

### C.2 `look(id: string, fields?: [string]) → Digest`

The central operation. Hard budget: **<= 500 tokens**.

`fields` (optional): list of desired fields (e.g. `["summary", "edges_out"]`). When present, the response contains ONLY those fields (+ `id`, always). Typical use: a monkey in scan mode asking only for `summary` of several nodes — cost drops from ~400 to ~70 tokens per look.

Response for a **banana** (`note`/`document`/`concept`/`entity`/`event`):

```json
{
  "id": "projects/mixerllm/architecture",
  "type": "document",
  "title": "MixerLLM Architecture",
  "summary": "...",
  "tags": ["inference", "slm"],
  "confidence": 1.0,
  "updated": "2026-06-10",
  "outline": ["Overview", "Mixer-lang", "Block-loop", "Benchmarks"],
  "edges_out": [
    {"rel": "part-of", "target": "projects/mixerllm/_index", "target_summary": "..."},
    {"rel": "compared-with", "target": "concepts/speculative-decoding", "target_summary": "..."}
  ],
  "edges_in": [
    {"rel": "mentions", "source": "people/jimmy-wesley"}
  ],
  "stats": {"body_tokens": 2840, "degree": 7, "heat": 0.45}
}
```

Response for a **branch**: replaces `outline` with `children` (sub-branches and direct bananas, each with `id` + `summary`) and `cross_trails`.

Response for a **dataset**: includes `query_manual` (tables, key columns, 2-3 example_queries) and `sample_rows` (<= 3 rows).

Rules:
- `edges_out`/`edges_in` capped at 12 each, ordered by heat desc; surplus indicated in `stats.degree`.
- `target_summary` MUST come truncated to 25 tokens (it's a neighbor's scent, not a full digest).
- `body_tokens` lets the agent estimate a `pick`'s cost before making it.

### C.3 `move(id: string, rel?: string, direction: "out"|"in"|"both" = "out") → [Neighbor]`

```json
{
  "neighbors": [
    {"id": "...", "rel": "compared-with", "direction": "out", "type": "concept", "summary": "...", "heat": 0.1}
  ],
  "truncated": false
}
```

Without `rel`: all neighbors. Budget: <= 600 tokens. `move(id, "children")` is sugar for a branch's physical children.

### C.4 `pick(id: string, section?: string) → Content`

```json
{
  "id": "...",
  "title": "...",
  "section": "Mixer-lang",
  "body": "<markdown of the section or the whole body>",
  "body_tokens": 612,
  "truncated": false
}
```

- `section` matches against the `outline`'s headers (case-insensitive, exact match first, then prefix).
- Body > 4,000 tokens without `section` → returns only the expanded outline + `truncated: true` + hint `"use section="`. (Forces the agent to harvest the section, not the whole tree.)

### C.5 `query(id: string, sql: string) → Rows`

- Preconditions: node `type: dataset`, `payload_type: sqlite`.
- Validation: a single statement only; MUST start with `SELECT` or `WITH`; forbidden: `ATTACH`, write `PRAGMA`, `INSERT/UPDATE/DELETE/DROP/ALTER` → `E_QUERY_FORBIDDEN`. Connection opened read-only (`mode=ro`).
- Forced `LIMIT`: if absent, injects `LIMIT 200`. 2s timeout → `E_TIMEOUT`.

```json
{
  "columns": ["region", "total"],
  "rows": [["Southeast", 1250000.0], ["South", 740000.0]],
  "row_count": 5,
  "limited": false,
  "elapsed_ms": 3
}
```

Columnar format (`columns` + `rows` as arrays) — not objects repeating the keys; saves ~40% of the tokens.

### C.6 `scan(parent_id: string, filter?: Filter, fields?: [string], recursive: bool = false, limit: int = 50) → [PartialNode]`

**Metadata** query over a branch's children, without opening any file. Served by the **Catalog** (see C.6.1).

`Filter` supports equality and comparison over frontmatter fields:

```json
{
  "parent_id": "projects/_index",
  "filter": {"type": "dataset", "updated_after": "2026-03-01", "tags_any": ["sales"]},
  "fields": ["id", "summary", "payload_type"],
  "recursive": true
}
```

Response: list of partial nodes (only the requested `fields`), ordered by `heat` desc. Budget: <= 800 tokens, with explicit `truncated`.

Canonical use case: "I only want the sales datasets updated this quarter" → 1 call, ~3ms, ~200 tokens — instead of descending the hierarchy opening indexes.

#### C.6.1 The Catalog (`_derived/catalog.db`)

SQLite in the derived layer with one row per forest node: every frontmatter field + trail + degree + heat. Rebuildable from scratch by a full scan (`vine reindex`); updated incrementally on every `plant`/`graft`. It's what serves `scan()` and `locate`'s lexical side (FTS5 over title/aliases/tags/summary in the same base). **Not the source of truth** — if it diverges from the files, the files win and the catalog rebuilds.

### C.6b `sniff(terms: string | [string], scope?: string, k: int = 5, type_filter?: string) → SniffResult`

The **sniffer**: **literal** search over nodes' markdown bodies, returning node + section + occurrence snippet. It complements `locate`: the helicopter flies over curated metadata (summary/tags/title); the sniffer goes down to ground level and follows the trail of an exact term — error code, proper name, invoice number, identifier — that nobody bothered (or was obligated) to lift into the summary. The contract split is normative: **`locate` MUST NOT index bodies; `sniff` MUST NOT query curated metadata** (except to display the result).

Parameters:

- `terms`: 1 to 8 **literal** terms (a single string is promoted to a 1-item list). Substring matching, case- and diacritic-insensitive (NFD, combining marks stripped). A term with a space = exact phrase. A normalized term with < 2 characters → `E_SCHEMA`. **Regex is NOT accepted** (Phase 0): SLMs write fragile regex, and arbitrary regex opens unpredictable cost; literal terms give 95% of the value with a simple contract.
- `scope` (optional): id of **any node**. A branch (`sales/_index` or `sales`) restricts the search to the matching physical subtree; a banana restricts it to that single node's body (grep-within-node — the natural chaining after a `locate`/`look` that already found the target). Without `scope`, the whole forest. Nonexistent node → `E_NOT_FOUND`.
- `k`: max nodes in the result (default 5, cap 20).
- `type_filter`: as in `locate`.

Search semantics:

- Scans **only the body** of `.md` files (frontmatter excluded; `_derived`, `_assets` and binary payloads ignored).
- A node matches when **at least one** term occurs in the body; nodes matching **more distinct terms** rank first (AND-preferred, OR-tolerant).
- `match` = the occurrence's line, attributed to the section (H2/H3 header) containing it. Max of **3 matches per node** in the response (`match_count` reports the total; surplus flagged by `truncated_matches: true`).
- `snippet` = a window of the line centered on the first occurrence, truncated to ~25 tokens.

Ordering (same pheromone formula as C.1): `score = strength x (1 + alpha*heat)`, where `strength = matched_terms/requested_terms`, tie-broken by `match_count`.

```json
{
  "results": [
    {
      "id": "sales/exchange-policy",
      "type": "note",
      "title": "Exchange policy",
      "trail": ["_index", "sales/_index"],
      "score": 0.95,
      "heat": 0.31,
      "match_count": 4,
      "truncated_matches": true,
      "matches": [
        {"section": "Deadlines", "line": 23, "snippet": "…return with invoice NF-4412 within 30 days…"}
      ]
    }
  ],
  "scanned_nodes": 82,
  "truncated": false
}
```

Budget: <= 800 tokens, explicit truncation (`truncated: true`) dropping nodes off the end of the list.

Canonical use (the monkey's decision, taught in the orchestrator's system prompt):

1. Question contains an exact/rare term → `sniff` directly: lands in the right section and harvests with `pick(id, section)` — cuts hops-to-banana.
2. Conceptual question → `locate` (unchanged).
3. Chained: `locate` finds the region, `sniff(terms, scope=branch)` hunts the snippet within it.

Phase 0 implementation: direct file scan on every call (grep-like, no new index) — always fresh by construction, no extra derived state. MAY gain an index (body FTS5 in a separate table) in a future phase **with no interface change**, as long as the contract split with `locate` holds.

### C.6c `harvest(query: string, terms?: [string], k: int = 3) → HarvestResult`

**Composite tool, not a primitive**: a deterministic, zero-LLM orchestration
over C.1 `locate`, C.6b `sniff` and C.4 `pick`. It exists for the
bring-your-own-model integration: the caller's LLM (MCP client) gets ranked
evidence in one call and decides the next steps itself.

The three integration modes (informative):

1. **Direct navigation** — the client's LLM drives the primitives itself.
   Best when reasoning must happen *during* navigation. Token cost is bounded
   by the per-primitive budgets; the real cost is round-trips.
2. **Harvest (this tool)** — one call, evidence back, zero tokens spent on
   the server side. Best default for capable client models.
3. **Concierge** — a local SLM hunts and returns a synthesized answer
   (orchestrator-side, e.g. `examples/demo/run_demo.py`); for thin clients.

Parameters:

- `query`: free text; feeds `locate` as-is.
- `terms` (optional): exact literal terms for `sniff`. When absent, terms are
  derived from the query (words >= 4 chars, stopwords removed, max 8).
- `k`: max bananas returned (default 3, cap 5).

Semantics (normative):

1. Candidates = RRF fusion of `locate(query, k*2)` and `sniff(terms, k*2)`
   rankings (same RRF as C.1's hybrid mode).
2. Match refinement by **term scarcity**: per-term `sniff` scoped to each
   selected node, rarest term first — a rare exact term ("1045") MUST NOT be
   drowned by common co-occurring terms under the per-node match cap.
3. Content policy per node: full body when <= 1200 tokens; otherwise the
   matched sections (max 2) via `pick(section)`; otherwise outline + hint.
4. Response items carry: `id`, `title`, `type`, `trail`, `summary`, `score`,
   `found_by` (locate/sniff), `matches` (section, line, snippet) and
   `content`. The caller can always continue with the primitives using `id`.

Budget: <= 4000 tokens total, explicit `truncated: true` dropping whole tail
results first (never silently slicing a body).

```json
{
  "query": "...", "terms": ["..."],
  "results": [
    {
      "id": "projetos/mixerllm/log-experimentos",
      "title": "...", "type": "note",
      "trail": ["_index", "projetos/_index", "projetos/mixerllm/_index"],
      "summary": "...", "score": 0.0328, "found_by": ["locate", "sniff"],
      "matches": [{"section": "Experimento 45", "line": 141, "snippet": "…"}],
      "content": [{"section": "Experimento 45", "body": "…", "body_tokens": 146}]
    }
  ],
  "truncated": false
}
```

### C.7 `plant(node: NodeSpec) → PlantResult`

`NodeSpec` = full frontmatter + `body` + `parent` (destination branch id).

Atomic operation (in this order; failure at any step = full rollback):
1. Validates frontmatter against the schema (A.3) and `summary` (A.4);
2. Checks `id` uniqueness;
3. Writes the file;
4. Inserts the entry into the parent `_index.md`'s `## Direct bananas` (or `## Sub-branches`);
5. `git commit` with the standardized message `plant(<id>): <title> [source=<source>]`;
6. Marks the node stale in the derived layer (lazy re-embedding).

Returns: `{id, commit, trail}`.

#### C.7.1 Dataset planting — declarative schema (v0.8)

A `NodeSpec` with `type: dataset` MAY carry a `schema` object describing the
payload to be **born** with the node:

```json
{
  "type": "dataset",
  "id": "clients/prospecting-2026",
  "parent": "clients/_index",
  "title": "Client prospecting 2026",
  "summary": "...",
  "schema": {
    "clients": {
      "columns": {"name": "TEXT", "site": "TEXT", "segment": "TEXT",
                  "collected_at": "TEXT"},
      "primary_key": ["name"]
    }
  }
}
```

Rules (normative):

1. **The model never writes DDL.** The schema is data; the Vine generates
   the `CREATE TABLE` statements itself. Validation, all `E_SCHEMA` on
   failure:
   - table and column names MUST match `^[a-z_][a-z0-9_]*$` (≤ 64 chars);
   - column types MUST be one of `TEXT`, `INTEGER`, `REAL`, `BLOB`;
   - `primary_key` (optional, per table) MUST reference declared columns;
   - limits: ≤ 10 tables per dataset, ≤ 50 columns per table, ≥ 1 of each.
2. `schema` on a non-dataset `type` → `E_SCHEMA`. A dataset planted
   WITHOUT `schema` keeps the v0.7 behavior (reference to a payload that
   already exists on the filesystem).
3. **Payload birth**: `payload` defaults to `<leaf-of-id>.db`,
   `payload_type` to `sqlite` (explicit values are honored; `payload` MUST
   be a bare filename ending in `.db`). The target file MUST NOT already
   exist (`E_SCHEMA` — never silently overwrite a payload). The Vine
   creates the SQLite file, applies the generated DDL, and computes
   `payload_hash` (sha256) into the frontmatter.
4. **Auto manual**: when the body lacks a `## Query manual` section, the
   Vine appends one generated from the schema — each table with its column
   list, plus example queries (`` `SELECT * FROM <t> LIMIT 5` ``,
   `` `SELECT COUNT(*) FROM <t>` ``) — so C.2 `look`'s `query_manual`
   contract works from birth. A caller-provided manual is kept verbatim.
5. **Atomicity**: the C.7 rollback covers the payload — any failure after
   the `.db` is created MUST remove it along with the `.md`. A.3.1 intact:
   the commit carries only markdown; one dataset node = one `.db` = one
   database (several tables = several keys in `schema`; there is no
   separate "create database" concept).
6. After birth, rows enter exclusively via `tend` (C.10) — multi-row
   `INSERT INTO t VALUES (...), (...)` is a single statement and therefore
   already legal there. Schema evolution (`ALTER`) is NOT available to
   agents in v0.8.
7. **Initial rows (v0.9)**: the `NodeSpec` MAY carry `rows`, a mapping
   `table → list of rows` loaded at birth, after the DDL and BEFORE
   `payload_hash` is computed. Normative: rows are inserted **parameterized**
   (`executemany` with placeholders — row values are data, never SQL text,
   so no keyword scanning applies and injection is impossible by
   construction); every `rows` table MUST exist in `schema` and every row
   MUST have exactly the table's column count (`E_SCHEMA` otherwise); the
   atomic rollback of C.7 covers loaded rows (the payload is removed whole).
   This is the bulk-load path for the Gardener (G.3) and collector agents;
   incremental writes after birth remain `tend`-only.

Canonical uses (informative): an agent collecting external data plants the
dataset then fills it with `tend`, for later harvest by `query`/humans; an
agent finding a large markdown table in a `document` plants a dataset twin,
loads the rows, and `graft`s a `related-to` link from the document — prose
stays as source, the data becomes filterable SQL.

### C.8 `graft(id: string, patch: GraftPatch) → GraftResult`

`GraftPatch` supports three operations (combinable):
- `set_frontmatter: {field: value}` — mutable fields only (`title`, `summary`, `tags`, `confidence`); `id`, `type`, `created` are immutable (`E_READONLY`);
- `add_links: [{rel, target}]` / `remove_links: [...]`;
- `append_section: {header, body}` or `replace_section: {header, body}`.

Special rules:
- A `summary` change propagates to every `_index.md` that replicates it (same transaction).
- **Reinforce-before-create policy (shortcuts):** at the end of a successful hunt, the decision cascade is: (1) if a shortcut already covers the entry→banana connection on the trail, do NOT create one — just increment the existing one's `heat` and `confidence` (fortification, no commit); (2) if none exists and the trail was >= 4 hops, `graft` a new `discovered-shortcut` with `confidence: 0.5` and `discovered_by: agent`; (3) new lateral connections the agent notices (`related-to` between the banana and semantic neighbors) enter as a **proposal** with `confidence: 0.3`, subject to confirmation or pruning by the Ranger. The Vine MUST implement step 1's check inside `graft` itself (shortcut idempotence): grafting a duplicate link automatically becomes fortification, never an error or a duplicate.
- Commit: `graft(<id>): <patch summary>`.

### C.10 `tend(id: string, sql: string) → TendResult` (v0.7 — Phase 2)

The dataset-write primitive: the forest stops being a smart reader and
becomes memory that learns. `query` (C.5) remains read-only forever; `tend`
is the only sanctioned write path into a dataset payload.

Preconditions:

- Writable Vine (read-only server → `E_READONLY`).
- Node is `type: dataset` with `payload_type: sqlite` and an existing
  payload file — anything else → `E_QUERY_FORBIDDEN` / `E_NOT_FOUND`.

Statement rules (normative, mirror of C.5's paranoia):

- Exactly ONE statement, and it MUST start with `INSERT`, `UPDATE` or
  `DELETE`. Reads belong to `query`; schema changes (CREATE/ALTER/DROP)
  belong to the Gardener — all rejected with `E_QUERY_FORBIDDEN`.
- Forbidden anywhere in the statement: `ATTACH`, `DETACH`, `PRAGMA`,
  `DROP`, `ALTER`, `CREATE`, `VACUUM`, `REINDEX`, `BEGIN`, `COMMIT`,
  `TRANSACTION` → `E_QUERY_FORBIDDEN`.
- `UPDATE`/`DELETE` MUST carry a `WHERE` clause (mass-wipe guard): target
  rows explicitly; full rewrites are the Gardener's job.
- Timeout 2s → `E_TIMEOUT`. SQL errors roll the transaction back and
  surface as `E_QUERY_FORBIDDEN` (the payload is untouched).

Audit trail (A.3.1 compliant):

1. The write commits in the payload SQLite.
2. The Vine refreshes the node's frontmatter: `payload_hash` = sha256 of
   the payload file, `updated` = today.
3. `git commit` of ONLY the `.md`, message `tend(<id>): <VERB> <n> row(s)`.
   The what/when history lives in the markdown commit stream; the binary
   never enters git.
4. If step 2-3 fails after step 1 committed, the `.md` is restored and the
   error surfaces — the resulting hash drift is exactly what
   `vine validate` now warns about (self-healing: the next successful
   `tend` refreshes the hash).

Response:

```json
{"id": "vendas/pedidos-2026", "rows_affected": 1,
 "payload_hash": "<sha256>", "commit": "<hash>", "elapsed_ms": 4.2}
```

### C.9 Concurrency and consistency (Phase 0)

- **One writer, N readers:** `plant`/`graft` go through a single queue (global mutex in the Vine). Reads never block.
- Readers MAY see state up to 1 write behind (eventual consistency of seconds) — acceptable by design.
- The `.vine.lock` file at the root prevents two writer Vines on the same forest (`E_LOCKED`).

---

## Part D — Telemetry (feeds the pheromone and the Monkey Bench)

Every navigation session generates a trace in `_derived/traces/<session>.jsonl`, one event per primitive call: `{ts, session, primitive, id, tokens_in, tokens_out, elapsed_ms}`.

At the end, the orchestrator MUST close the session with `outcome: {success: bool, answer_nodes: [ids]}`. This closing is what:
1. Increments `heat` along the whole winning trail (whisper);
2. Evaluates the shout (v0.6): when the session metric `trail_len` — read
   calls made before the first harvest of an answer node — is `>= 4`, the
   answer nodes come back in `suggest_shortcuts`, and the orchestrator MAY
   `graft` a `discovered-shortcut` from the hunt's entry node (C.8 applies);
3. Feeds the Monkey Bench metrics: **hops-to-banana** = number of `look`+`move` calls before the answer's first `pick`/`query`; **tokens-to-banana** = sum of session tokens_out; **banana precision** = correct answer_nodes / harvested answer_nodes; **trail_len** (v0.6) = read calls before the first harvest of an answer_node.

---

## Part E — The Troop (Parallel Swarm Navigation)

N monkeys (navigator SLM instances) hunt the same banana in parallel, coordinated by **intra-session stigmergy**: they never exchange messages — they smell each other's trails. The Vine is already N-readers by design (C.9); the Troop is an **orchestrator**-side component (the MCP client side), not the bank.

### E.1 Hunt protocol

1. **Frontier partition:** `locate(query, k=N)` → each monkey gets a distinct entry point (top-N results). Without partitioning, everyone explores the same trail and the parallelism is wasted.
2. **Session pheromone:** each monkey, upon judging a node promising (the SLM's own call: "relevant to the question? yes/no"), deposits `session_heat` in the hunt's scope (`_derived/trails.db`, session namespace). `locate`/`look`/`scan` inside the session apply `score x (1 + beta*session_heat)` — monkeys gravitate toward regions where others found signal.
3. **Shared visited set:** `look`/`scan` digests already made in the session land in a shared cache; a monkey that would touch an already-visited node gets the cached digest instead (zero cost), and the orchestrator redirects it to unexplored frontier.
4. **Stop:** the hunt ends when (a) a monkey harvests a banana with high confidence (self-assessment above threshold), (b) the troop's hop budget runs out, or (c) the frontier empties. A **judge** (may be the main model itself) aggregates the harvests and synthesizes the answer.
5. **Post-session:** only the winning trail(s) convert `session_heat` into persistent `heat` (Part D). Losing trails evaporate with the session — the swarm does not pollute long-term pheromone.

### E.2 Implementation notes

- **Concurrency:** asyncio in the orchestrator; the monkeys spend ~95% of their time waiting on inference. On the 3090, serving the N monkeys through the same inference server with *continuous batching* (vLLM/llama.cpp parallel slots) makes N=3-5 cost nearly the same wall-clock as N=1.
- **Sizing:** N=3 is the default; above N~5 returns diminish (frontiers overlap in small forests). N is a Monkey Bench parameter, not a constant.
- **New metric:** *troop speedup* = wall-clock hops (parallel rounds) vs the solo monkey's total hops, and total token cost (the troop spends more tokens in aggregate — the speed x cost trade-off MUST be measured, not assumed).
- **Phase:** Troop is Phase 1.5 — requires the full Vine + telemetry (Part D) working. Nothing in Phase 0 changes, except ensuring `trails.db` supports session namespacing (already anticipated in the trace schema).

## Part F — Phase 0 Acceptance Criteria

Deliverable: Vine (MCP, Python) + a manual test forest (~100 nodes, 10 branches, >=1 SQLite dataset) + test suite.

1. All C.1-C.6b primitives functional with the exact contracts above (locate may be BM25-only), including `fields` in `look` and the Catalog serving `scan`.
2. `plant`/`graft` atomic with a Git commit and index update, verified by test.
3. Token budgets respected (tests with giant synthetic nodes verifying explicit truncation).
4. `query` rejects all write SQL (injection suite: `;DROP`, `ATTACH`, multi-statement, PRAGMA).
5. Demo: a local SLM (Qwen 7-14B Q4), given only the MCP tools and the master branch, answers 10 multi-hop questions about the test forest, with recorded traces and computed metrics.
6. Latency: p95 of `look`/`move`/`pick` < 10ms, `query` < 50ms, `locate` < 100ms, `sniff` < 100ms (local forest, NVMe).
7. `sniff`: finds a fact present ONLY in the body (invisible to `locate`), attributes the correct section, respects `scope`, normalizes case/diacritics, and rejects empty terms (`E_SCHEMA`) — all covered by test.
8. Payloads outside Git (A.3.1): the Vine's commit ignores non-`.md` files even if requested, and the test forest's `git ls-files` contains no binary — both verified by test.
9. `harvest` (C.6c): buried fact returns the right matched section under term-scarcity refinement; small bodies come whole; `k` and the 4000-token budget are honored with explicit truncation — all covered by tests.
10. Forest registry (C.0): per-request forest selection works across two forests with isolated results; lazy first-touch open auto-indexes; path escape and non-forest directories are rejected; single-forest mode serves v0.3 clients unchanged — all covered by tests.
11. `tend` (C.10): accepts only single-statement INSERT/UPDATE/DELETE (its own
    injection suite: DDL, ATTACH/PRAGMA, multi-statement, WHERE-less
    UPDATE/DELETE all rejected); refreshes `payload_hash` and commits only the
    `.md`; read-only Vine rejected; failed SQL leaves the payload untouched;
    `vine validate` warns on payload hash drift — all covered by tests.
12. Dataset planting (C.7.1): declarative schema births a queryable payload
    (`look` shows the auto query manual, `query`/`tend` work immediately);
    name/type/limit validation rejects bad schemas (`E_SCHEMA`), including
    injection attempts via table/column names; existing payload is never
    overwritten; rollback removes the newborn `.db`; the commit carries only
    the `.md` — all covered by tests.
13. Gardener (Part G): `adopt` of a mixed source tree (markdown, text,
    tabular) produces a forest that lints with zero errors — folders
    mirrored as branches, passports carrying `source_path` + `source_hash`,
    non-text originals archived under `_assets/`, datasets born with rows
    loaded, no binary in the forest git; `sync` classifies new / changed /
    deleted sources by hash-diff with no false positives, updates changed
    passports through the audited write path, and never deletes; converter
    discovery honors the config-hook > entry-point > built-in order; an
    external command hook converts a file end-to-end; an `on_curate` hook
    can enrich a draft and a crashing hook does not abort the ingest — all
    covered by tests.
14. Ranger (Part H): under a synthetic clock, one half-life halves heat and
    dust rows vanish; stale session scopes are cleared; promotion raises a
    well-used proposal's link confidence with an audited commit; pruning
    removes only cold, low-confidence links — links with confidence 1.0 or
    without a link-level confidence are NEVER touched; the health report
    flags an oversized branch (`needs_split`), an over-linked node and a
    stale passport; repeated runs are idempotent — all covered by tests.
15. Tiered storage (G.7/G.8): a `cached` adoption keeps node `.md`s body-
    free with the flesh in `_derived/bodies/` and OUT of git, while `pick`
    and `sniff` resolve it transparently; a `reference` adoption reads the
    source live; an unresolvable body fails with `E_NOT_FOUND` + hint
    while `locate`/`look` keep working (degraded map); `archive: never`
    creates no `_assets/` copies; `sync(path=...)` reconciles exactly one
    file; the mtime+size fast-path skips hashing unchanged files — all
    covered by tests. (Fetcher cache, H.6 eviction and Part I snapshots
    are covered by tests as their implementations land.)
16. Gardener v2 (G.2.1 + G.4.2.1): the DOCX built-in extracts headings,
    plain paragraphs, pipe tables, fragmented runs (joined whole) and
    text-box text from a real `.docx`, excludes headers/footers, and a
    missing `python-docx` yields `unsupported` (never a crash) with a
    command hook still able to claim `.docx`; edge proposals accept only
    catalog-offered targets at link-level `confidence: 0.3` with `rel:
    related-to` (hallucinated ids, self-links, duplicates and over-cap
    picks are dropped; branches are never candidates), the planted node
    carries the proposed links, and the Ranger's H.2 machinery manages
    them (promotable, prunable) — all covered by tests.
17. Rollup + Landmarks (G.4.4 + H.7): rollup replaces only `source: ingest`
    branch summaries (hand-authored branches untouched unless `--all`),
    runs deepest-first so parents see fresh child summaries, falls back
    deterministically to an A.4-valid summary when the LLM fails, and
    propagates the new summary into the parent's `## Sub-branches` entry
    WITH the coverage suffix preserved; the Ranger populates the master
    `## Landmarks` with top-degree non-branch nodes, a second run with an
    unchanged graph produces no new commit, and degree-0 nodes never
    appear — all covered by tests.
18. Station + ScopedVine (Part J): a fresh deployment plus one API key
    serves REST, MCP and Studio against a registry of two forests; the
    **leak suite** proves a principal granted only `projects/` cannot
    obtain the id, title, summary, body, edge or snippet of any node
    outside `projects/` through ANY primitive on ANY surface — one test
    per primitive per surface, `harvest` and `move` included; an
    out-of-scope `look`/`pick` is byte-identical to the genuinely-absent
    `E_NOT_FOUND`; a scoped `locate`/`scan`/`sniff` returns the same
    response shape and budget fields as the unscoped call (filtering
    precedes truncation); writes through the Station carry the acting
    principal in the commit message and the audit log reconstructs a
    session's full trail; capability gates reject `query`/`tend`/`plant`/
    `graft` without the matching cap; and the engine suite passes with
    zero edits under `src/monkeyllm/` — all covered by tests.
19. Per-forest inference (J.10): a provider's key is never returned by any
    surface (create, list, or re-edit) and an empty key on update keeps the
    stored one; a binding is refused for an unknown provider or an unknown
    role; removing a provider removes the bindings that pointed at it; the
    two roles can hold different models on the same forest; `answer` and
    `curate` refuse politely when no model is bound, and enforce the `read`
    and `write` capabilities respectively; and — the load-bearing one — for
    a principal scoped to a subtree, the material handed to the answering
    model contains no node outside that subtree — all covered by tests.
20. Console, lifecycle and ingest (J.5/J.7/J.8): every user-facing string
    resolves in all three languages, with a test that fails on the first
    key missing from any of them; the console renders in both themes and
    holds no credential in its bundle; forest creation refuses ids
    containing separators or relative segments **before** joining them to
    the root, refuses an id that already exists, and grants the creator
    the forest it just made; ingest refuses without the `ingest`
    capability and refuses a `dest` outside scope, an uploaded filename
    that escapes its staging directory is rejected, and a forest with no
    `ingest` binding still ingests with G.4-derived summaries; and a
    `projects/`-scoped principal's console offers only `projects/` in its
    tree, its scope picker and its dataset list — all covered by tests.
21. Credentials (J.2.1/J.2.2/J.5.4): a username and password exchange for a
    session token that authorises exactly what the same principal's API key
    would and no more; a Station with no `MONKEYLLM_STATION_PASSWORD` set
    has **no** password door rather than a default one; a password is
    stored only as a salted memory-hard hash and a principal without one
    cannot log in; an **expired** key, a **revoked** key and an unknown key
    are all rejected identically; `last_used_at` advances on a successful
    call; listing returns prefixes and never a secret, and a secret is
    returned exactly once at creation; session tokens do not appear in the
    token console; and — the load-bearing one — an administrator of one
    forest is refused when minting or revoking a key for a principal that
    also holds a grant on a forest they do not administer, so a token
    cannot be used to reach across the registry — all covered by tests.
22. Per-forest administration and navigation (J.3.2/J.5.1): every
    `/v1/admin/*` route refuses a principal without `admin`, proven by a
    sweep that enumerates the routes rather than a hand-written list that
    a new route can quietly escape; and on a two-forest registry, an
    administrator of one forest sees **no** principal, branch prefix or
    audit entry belonging to the other — while an administrator of both
    sees everything. Navigation lists exactly the permitted consoles for
    the selected forest, and each console still guards itself when reached
    with the capability missing — all covered by tests.
23. Person-shaped governance (J.2.3/J.5.5): one `POST /v1/admin/people`
    creates a principal, grants it, sets its password and mints its key,
    and the resulting password logs in while the resulting key reads —
    proving onboarding needs one request; each step re-checks its own rule,
    so an administrator of one forest is refused the credential steps for a
    principal that also holds another forest **while the grant it was
    entitled to make still applies**, and the response names what was
    refused; clearing a password removes the sign-in; revoking all of a
    person's keys stops all of them at once; and `GET /v1/admin/people`
    returns only administered forests' grants and tokens — all covered by
    tests. A grant naming **several** forests lands on each of them, so the
    key minted in the same request reads in every one; naming a forest the
    caller does not administer refuses that forest **by id** while the rest
    still apply; and a multi-forest `revoke_access` removes exactly the
    grants named — also covered by tests.

24. The Gauntlet (Part K): with no embedder, an empty index, or an index
    whose recorded model differs from the embedder's, `look`, `move` and
    `scan` return **byte-identical** responses to the same calls made with
    the feature absent entirely — proven by comparing the two, not by
    inspecting a flag; a mismatched index also turns hybrid `locate` off
    and is reported by validation rather than silently ranking across two
    vector spaces; when active, the frontier order changes, the response
    says it was conditioned and toward what, and the per-call opt-out
    restores the unconditioned order within the same session; and the goal
    is embedded once per hunt rather than once per hop — all covered by
    tests.

25. Map projections (J.11): for a scoped principal, `GET /graph` returns no
    id the same principal cannot `look` at, every edge it returns has both
    endpoints in scope, and every `degree` it reports equals the degree
    computed from the returned edges alone — proven by recomputing, not by
    trusting the field; `GET /trails` exposes persistent heat only, never a
    session scope; both flag `truncated` when a bound cut the answer; and
    the Explore console's graph, tree and file modes read only these
    endpoints and the Part C primitives — all covered by tests.

Out of scope for Phase 0 (do not implement): embeddings/vectors, `same-as` compaction, S3/R2 sync, multi-writer, Troop (Part E — Phase 1.5; only ensure session namespacing in trails.db). Automatic ingest left this list in v0.9 (Part G); evaporation and promotion/pruning left it in v0.10 (Part H).

---

## Part G — The Gardener (ingest pipeline, spec v0.9)

The Gardener turns raw directories into forest. It is **trusted
infrastructure** (it runs with the operator's authority, not an agent's),
but it writes through the same audited mechanics as everything else: nodes
are born via C.7 `plant`, datasets via C.7.1, and only `.md` ever reaches
git (A.3.1). Four stages — only one of them needs an LLM:

```text
0 archive  →  1 convert  →  2 curate  →  3 plant
(raw copy)    (pluggable)    (LLM-optional)  (existing primitives)
```

### G.1 Passport policy (normative)

No file enters the forest without a passport: a sibling `.md` node that is
the file's official presence in the graph. The agent always touches the
passport first; the native file is payload.

- Every passport records **`source_path`** (the source file's path, as given
  to adopt/sync) and **`source_hash`** (sha256 of the source bytes) in its
  frontmatter. These two fields make the forest itself the sync state —
  there is no separate bookkeeping database to drift.
- Conversion targets per format: markdown/plain text → `note` (body is the
  content, no payload); convertible documents (PDF/DOCX/…) → `document`
  (body is the converted markdown, original archived); tabular (CSV/XLSX/
  tabular JSON) → `dataset` (C.7.1 birth with schema + rows; original
  archived); audio/image/video → `media` (body is the transcript/
  description, original archived).
- Archived originals live in the node's branch under `_assets/` (gitignored
  per A.3.1), referenced by `payload` + `payload_hash`. Markdown/plain-text
  sources are NOT archived (the body is lossless).
- Node ids are deterministic slugs of the source-relative path (lowercase,
  ASCII-folded, `[a-z0-9._-]`); a slug collision appends a short hash. The
  id mirrors the source layout — placement in `adopt` mode is structural,
  not an LLM decision (ids are immutable; deciding placement at birth is
  mandatory, see A.3).

### G.2 Converter contract (public plugin API v1)

A converter claims file extensions and produces either markdown or a
dataset description:

```python
class Converter(Protocol):
    extensions: set[str]            # e.g. {".docx"}
    def convert(self, path: Path) -> Conversion: ...

Conversion = markdown(title, body)            # → note/document/media
           | dataset(title, schema, rows)     # → C.7.1 birth
```

Discovery order (first converter claiming the extension wins):

1. **Command hooks** from the forest's Gardener config (G.6) — an external
   command template (`"{input}"`/`"{output}"` placeholders) that must write
   markdown; lets operators plug ANY tool (including copyleft-licensed
   ones) without it ever becoming a dependency of this project.
2. **Entry points**: packages installed in the environment declaring the
   `monkeyllm.converters` group (`pip install monkeyllm-whisper` just
   works). This is the third-party extension surface.
3. **Built-ins**: `.md`/`.txt` passthrough; `.csv`/tabular `.json` (and
   `.xlsx` when `openpyxl` is present) → dataset with inferred column
   types; `.docx` → markdown when `python-docx` is present (G.2.1).
   Built-ins MUST keep the core dependency-light and MIT-clean.

A file with no claiming converter is reported as `unsupported` — never a
crash, never a silent skip.

#### G.2.1 DOCX built-in converter (v0.12)

Available when `python-docx` is importable (optional `ingest` extra —
python-docx is MIT, its lxml dependency BSD; same gating pattern as the
`.xlsx` built-in). Normative behavior:

1. **Document order, single pass.** The converter walks the body's block
   elements in order: `w:p` (paragraph) and `w:tbl` (table).
2. **Paragraph text = the join of ALL descendant `w:t` elements.** This
   captures runs fragmented mid-word by Word (joining merges them for
   free) AND text living inside embedded text boxes (`wps:txbx`, legacy
   `v:textbox`) — content invisible to naive `paragraph.text` readers.
3. **Headings**: paragraphs styled `Heading N` (or `Title`) map to
   markdown `#`-headings (`Title`/`Heading 1` → `##` and deeper — `#` is
   reserved for the node title line). Everything else is a plain
   paragraph.
4. **Tables** become GitHub pipe tables: first row = header, cells take
   the same all-`w:t` join. Nested tables flatten into their cell text.
5. **Headers/footers are EXCLUDED**: page numbers and letterhead repeat
   on every page and would pollute the scent (A.4 summaries derive from
   the opening text).
6. **Exclusions are not errors**: images/drawings contribute no text
   (media adoption is G.5's path); an empty document converts to an
   empty-bodied markdown with the filename title.

Without `python-docx`, `.docx` files are reported `unsupported` (G.2) —
operators can still route them through a command hook (e.g. a Pandoc or
MarkItDown wrapper), which keeps priority over this built-in.

**Extension surface is edges-only (normative):** converters and curation
hooks extend what goes INTO the forest. Nothing extends the primitives'
semantics, token budgets, or security guards (`query`/`tend` validation,
A.3.1, C.9 locking). UIs, upload receivers and automations are clients of
the MCP server or of the Python library — they require no plugin API.

### G.3 `adopt` and `sync` (the brownfield engine)

- **`adopt(source_dir, dest?)`** mirrors an existing tree: each source
  directory becomes a `branch` (planted before its children), each file is
  converted and planted as its passport under the mirrored branch.
  Deterministic: stable ordering, slug ids, no LLM in the loop. `dest`
  roots the mirror under an existing branch (default: forest root).
- **`sync(source_dir?)`** re-walks the source (default: the adopted root
  recorded in config) and hash-diffs against the passports' `source_hash`:
  - **new** file → adopt it;
  - **changed** hash → re-convert; the passport's body, `source_hash`,
    `payload_hash` (datasets are rebuilt) and `updated` are refreshed
    through the Gardener's audited write path — a git commit
    `gardener(sync): <id>` of only the `.md`. Curated frontmatter
    (summary, tags, links, confidence) is PRESERVED;
  - **deleted** source → the passport is reported `stale`. The Gardener
    NEVER deletes nodes; pruning is the Ranger's call (tombstone policy,
    out of scope here).
- Continuous watching (filesystem events) is a Ranger-era concern; v1 sync
  is on-demand and deterministic.

**Source containment (normative, v0.26).** Both entry points resolve their
source through one gate, because two gates drift:

1. **A source is always named.** `adopt` requires one; `sync` takes the one
   `adopt` recorded. When neither exists the call is `E_SCHEMA` — an
   absent source MUST NOT fall back to the process's working directory,
   to a default, or to anything else. "The usual place" for a forest that
   has no usual place is not a location, and every filesystem API in wide
   use resolves the empty path to the working directory silently.
2. **A source MUST NOT overlap the forest.** It may not *be* the forest
   root, contain it, or sit inside it. The single exception is the
   forest's own `_derived/` subtree, which is explicitly not forest
   content and is where a host stages uploaded bytes (J.8).
3. **A forest is never a source.** A directory carrying the A.5 master
   index (`_index.md`) that is met *inside* a walk is pruned whole,
   children included. Its passports are somebody's curated nodes, not
   documents awaiting conversion, and a source that happens to sit above a
   registry would otherwise deliver every forest under it into this one,
   in a single call and across the tenant boundary.

The Gardener is trusted infrastructure running with the operator's
authority (see the head of this Part), so these rules bound *what a walk
may reach*, not who may ask for it. Who may ask, and which directories a
**host** will open on a caller's behalf, is J.8.2 — a shell user is
already standing on the filesystem and is not subject to it.

### G.4 Curation (the only LLM stage — always skippable)

Stage 2 enriches the draft node before planting:

1. **Without an LLM** (default in v1): summary derived from the converted
   content's first sentences (≤ 60 tokens, A.4-validated, with a safe
   fallback), `source: ingest`, `confidence: 0.7` (unreviewed), default
   tags from config. The pipeline never blocks on a missing GPU.
2. **With an LLM** (Gardener v2): A.4 summary with validate-and-retry,
   tags, edge proposals at link-level `confidence: 0.3` (G.4.2.1), guided
   by the **curation directives** in the forest config — free-text criteria
   the operator wants the Gardener to "keep an eye on" (e.g. "prioritize
   contract numbers and client names in summaries"). Entity EXTRACTION
   (minting new `entity` nodes) is deferred past v0.12: it needs a
   placement policy and a `same-as` dedup story first.
3. **`on_curate` hooks**: plugins (entry-point group `monkeyllm.hooks`,
   name `on_curate`) and/or locally registered callables receive the draft
   (dict) and may mutate it. Hooks run in discovery order; a raising hook
   is logged into the report and SKIPPED — a broken plugin never aborts an
   ingest.

#### G.4.2.1 Edge proposals (v0.12)

LLM curation MAY propose links from the node being adopted to nodes that
ALREADY exist in the forest. The contract is built so a wrong proposal is
cheap and a fabricated one is impossible:

1. **Candidates come from the catalog, never from the model's memory.**
   The Curator runs a BM25 search (C.6.1) with the draft's title + curated
   summary and offers the model a closed list of up to 8 candidates
   (`id`, `title`, `summary`). Excluded from candidacy: the draft itself,
   `branch` nodes (a link to a folder carries no scent), and the draft's
   own parent.
2. **The model picks from the list — or picks nothing.** Anything outside
   the offered ids is dropped (the hallucination guard is structural, not
   a prompt instruction). Picking nothing is a valid, common answer:
   relatedness must be visible in the two summaries.
3. **Every proposal is `rel: related-to`** (symmetric, generic — A.2) with
   **link-level `confidence: 0.3`** and MAY carry a short free-text `note`
   (kept out of the summary budget; helps the Ranger's audit trail). Other
   rels (`mentioned-in`, `same-as`, …) are NOT proposable in v0.12 — they
   assert ontology, not navigational adjacency.
4. **Caps and dedup**: at most 3 proposals per node; self-links and
   duplicates of existing links (same `rel` + `target`) are dropped.
5. **Node-level vs link-level confidence**: the adopted node keeps its
   G.4 `confidence: 0.7` (unreviewed content); 0.3 lives ON THE LINK —
   that is exactly the population Part H manages. The lifecycle is the
   point: **the Gardener proposes (0.3), usage heats both endpoints, the
   Ranger promotes (0.8) or prunes (cold)**. A proposal nobody ever walks
   costs one frontmatter line and dies by H.2.
6. **Failure never blocks**: bad JSON, transport errors or zero valid
   picks simply yield zero proposals (counted in the Curator's stats);
   the node still plants.

#### G.4.4 Branch rollup (v0.13)

Curation gives every banana a scent; rollup gives every REGION one. After
the per-node curation stage of an `adopt`/`sync` (or on demand), the
Gardener MAY rewrite branch frontmatter summaries bottom-up:

1. **Scope**: only branches with `source: ingest` — the Gardener rewrites
   what the Gardener planted, nothing else. An explicit operator override
   (`--all`) MAY widen the scope to every non-`_meta` branch.
2. **Order**: deepest branch first (by id depth), so a parent's rollup
   always sees its sub-branches' fresh summaries.
3. **Input**: the branch's own `## Sub-branches` and `## Direct bananas`
   entry lines (which replicate child summaries verbatim, A.5), clipped to
   the curation content budget. The model never reads child bodies —
   rollup is O(branches) LLM calls with bounded prompts.
4. **Output contract**: an A.4-valid summary (1-3 sentences, ≤ 60 tokens)
   answering the A.5 blockquote question — what lives here + where to go
   if it is not here. Validate-and-retry as in G.4.2.
5. **Fallback**: any failure (bad JSON, invalid summary after retries,
   transport error) falls back to a deterministic summary composed from
   child titles and counts — the pipeline never blocks and never leaves a
   branch worse than the template it had. Counted in the Curator's stats.
6. **Write path**: C.8 `graft` on the frontmatter `summary` — atomic,
   `.md`-only commit, catalog upsert, and VERBATIM propagation of the new
   summary into the parent's `## Sub-branches` entry (coverage suffix
   preserved, A.5). No new write machinery.
7. **What rollup is NOT**: it never creates nodes or links, never touches
   bodies (`## Cross trails` stays hand-authored), and never runs without
   an operator asking for curation (it is part of the always-skippable
   LLM stage).

### G.5 Media (multimodal by proxy)

Audio/image/video go through the SAME converter contract: the converter
(e.g. a Whisper transcriber, a vision-model describer — extras or hooks,
never core dependencies) returns markdown that becomes the `media`
passport's body. The forest's job is **finding** media fast: `locate`/
`sniff` search the textual proxy; a multimodal client that wants full
fidelity follows `payload` to the raw file. Text to find, binary to
consume. (Serving payload bytes over MCP to multimodal clients is a
possible future extension — not normative here.)

### G.6 Gardener config (`_meta/gardener.yaml`)

Operator-level configuration, read by the Gardener (not a node — `_meta/`
non-markdown files are not indexed):

```yaml
source_root: D:/dump/docs        # written by adopt ONLY; sync's default source
                                 # absent = sync has nothing to refresh (G.3)
ignore: ["~$*", "*.tmp"]         # extra ignore globs (defaults: VCS dirs, temp files)
converters:                      # command hooks (discovery priority 1)
  ".pdf": 'pdf2md "{input}" -o "{output}"'
curation:
  default_tags: [adopted]
  directives: >                  # free text fed to the curation LLM (G.4.2)
    Prioritize contract numbers and client names in summaries.
content: inline                  # inline | cached | reference (G.7)
archive: never                   # never (default) | always (G.7)
```

### G.7 Content & archive policies (v0.11)

The forest's three tiers: SCENT (passport frontmatter — always local, in
git), FLESH (full converted text), BONE (raw binaries — stay at the
source). The `content` policy decides where the FLESH lives:

- **`inline`** (default): the converted body lives in the node `.md`
  (v0.9 behavior — git-versioned content; right for normal corpora).
- **`cached`**: the node `.md` holds only the title stub and the
  frontmatter marker `content: cached`; the converted body is written to
  `_derived/bodies/<id>.md` — OUT of git. Right for huge corpora.
  Regenerable: re-running `sync` while sources are reachable rebuilds the
  cache (the body is a function of source + converter).
- **`reference`**: no local body at all; the body IS the source file,
  read live at harvest time. ONLY valid for passthrough text sources
  (`.md`/`.txt`); marker `content: reference`.

Normative semantics:

1. **Lazy resolution**: `pick` (and `sniff`, when it reaches such a node)
   resolves the body from the cache file (`cached`) or from
   `source_root/source_path` (`reference`). The resolution is transparent
   — same response shape, same budgets.
2. **Degraded mode is explicit**: when the body cannot be resolved
   (source share down, cache purged), the read fails with `E_NOT_FOUND`
   and a hint naming the missing backing file. The MAP keeps working —
   `locate`/`look`/`scan`/heat never depended on the body.
3. `look`'s `outline` MAY be empty for non-inline nodes (the digest comes
   from the catalog; spending I/O to outline a remote body would break
   the <= 500-token cheapness contract).
4. Summary derivation and LLM curation (G.4) always see the FULL
   converted text at ingest time — the scent quality does not depend on
   the content policy.
5. **`archive`**: `never` (default) — durable sources are not copied into
   `_assets/`; `source_path` + `source_hash` are the reference. `always`
   — inbox mode: the source will vanish after ingest, archive the
   original (v0.9 behavior). Datasets keep their local `.db` payload
   under every policy (G.9).
6. **Containment (normative, v0.26)**: the resolved backing file MUST lie
   underneath `source_root`; otherwise the read fails as rule 2's
   `E_NOT_FOUND` and the hint MUST NOT quote what was found there.
   `source_path` is ordinary frontmatter — the Gardener writes it, and
   `plant` accepts it like any other extra field — so a node can name a
   path its author chose. Without this rule `pick`, a read primitive
   available to any principal holding `read`, resolves arbitrary host
   files with the Vine's authority and reports them as the node's own
   body. The check happens after resolution, so `..` and symlinks are
   already collapsed.

### G.8 Targeted sync & triggers (v0.11)

- **`sync(path=...)`** reconciles a single source-relative path (new,
  changed or deleted) without walking the whole tree — the building block
  for event-driven updates.
- **Containment (normative, v0.26)**: `path` is relative to the source
  root and MUST resolve underneath it; an absolute path or one that
  escapes is `E_SCHEMA`. The comparison MUST be made on the **resolved**
  path. A lexical check passes `../../etc/passwd` — joined onto the root
  it still *starts* with the root, so a purely textual "is it relative to"
  answers yes, the file is read, and its slugified `..` segments become a
  branch. Events arrive from watchers, webhooks and queues (below), which
  is to say from outside; this path is caller input like any other.
- **Fast-path (normative)**: passports record `source_size` and
  `source_mtime`; a sync visit MUST skip hashing when both match the
  stored values (rsync's trick — re-hashing 2 TB per cycle is the real
  bottleneck). Hash remains the authority whenever the fast-path misses.
- **Events trigger, the reconciler decides**: filesystem watchers, S3
  event notifications, Drive `changes.watch` and upload webhooks are
  CLIENTS/plugins that call targeted sync. Events MUST NOT be trusted as
  state (they get lost); a periodic full `sync` (`--every N`) heals
  anything an event missed. Same controller pattern as C.6.1: derived
  state reconciles from the files, never the other way around.

### G.9 Payload fetchers (v0.11)

`payload` and `source_path` MAY carry a URI scheme. Plain paths mean
`file://` (today's behavior, zero change). Remote schemes (`s3://` first,
as an optional MIT-licensed extra) resolve through a fetcher registry:

1. Remote payloads/bodies download on first use into
   `_derived/payloads/`, validated against `payload_hash`/`source_hash`
   before use (a corrupted or tampered download never reaches the agent).
2. **Datasets are local-first by design**: SQLite needs a local file, and
   a hot knowledge base needs sub-millisecond reads — object storage
   holds `.db` files only as backup or cold-archive tiers. A cold
   dataset's first `query` pays one download; the cache absorbs the rest.
3. Remote sync uses the store's own change signals (ETag listings)
   instead of downloading to hash.
4. **`tend` rejects remote payloads** (`E_QUERY_FORBIDDEN` with hint):
   writes belong to the local-first tier — editing a cached copy of a
   remote database would fork it silently. Reads (`query`, `look`'s
   dataset digest) work through the cache transparently.
5. **Region prefetch (the parachute warms the camp)**: `prefetch(scope)`
   downloads every remote payload under a branch in one sweep — the
   orchestrator calls it right after `locate` drops the monkey, so the
   subsequent `sniff`/`query` hops run at local speed. Combined with H.6
   eviction, the payload cache converges to the shape of the pheromone:
   hot regions stay warm, cold regions evaporate from disk.

The MAP itself (passports + the forest git) stays local to wherever the
Vine runs — it is the truth, it is ~0.1% of the source, and remote
clients reach it through the MCP server, not by replicating it. Moving a
map between machines is what snapshots are for (Part I). `catalog.db` and
`trails.db` remain disposable caches OF the local map (C.6.1) — they are
never the only local copy of anything.

---

## Part H — The Ranger (maintenance, spec v0.10)

The Ranger keeps the forest healthy over time. The compounding loop only
works if the pheromone can also **forget**: without evaporation every trail
saturates at `heat = 1.0` and the whisper stops discriminating; without
pruning, agent proposals pile up as permanent noise. The Ranger is trusted
infrastructure (operator authority): evaporation lives entirely in the
derived layer; every node edit goes through the audited `.md`-only commit
path.

### H.1 Heat evaporation (derived layer only — no commits)

- Persistent heat decays exponentially:
  `heat' = heat × 0.5^(Δt / half_life)`, where `Δt` is the time since the
  row's `updated` timestamp. Default `half_life_days: 30` (config H.5).
- Rows whose decayed heat falls below **0.01** are deleted (dust removal —
  the table stays proportional to what is actually warm).
- Session scopes (`scope != ''`) older than `session_ttl_hours` (default
  24) are cleared — crash leftovers from Troop hunts must not survive.
- Evaporation re-stamps `updated` at decay time (the decay is applied, not
  re-derived); running the Ranger twice in a row is a no-op within clock
  precision (idempotence under the synthetic-clock test).
- `_derived/` remains disposable: deleting `trails.db` loses memory but
  breaks nothing (A.3 spirit) — therefore evaporation never commits.

### H.2 Promotion and pruning of uncertain links

**Scope rule (normative): the Ranger manages ONLY links that carry a
link-level `confidence < 1.0`** — i.e. edges born as proposals
(`related-to` at 0.3, C.8) or discovered shortcuts (0.5, C.8). Structural
edges (`part-of`, etc.), links without a confidence field and links at
`confidence: 1.0` are NEVER touched.

- **Promotion**: a managed link whose BOTH endpoints hold persistent heat
  `>= promote_floor` (default 0.2) after evaporation is *confirmed by use*:
  link confidence is raised to `promoted_confidence` (default 0.8). Audited
  commit `ranger(promote): <id> <rel>-><target> 0.8` of only the `.md`.
- **Pruning**: a managed link with `confidence <= prune_below` (default
  0.5) whose BOTH endpoints have fully evaporated (heat 0 — no
  reinforcement within memory) is removed. Audited commit
  `ranger(prune): <id> <rel>-><target>`.
- A link that is neither hot enough to promote nor cold enough to prune is
  left alone — patience is a feature.
- The Ranger NEVER deletes nodes. Stale passports (G.3) stay reported until
  a human (or a future tombstone policy) decides.

### H.3 Health report (read-only)

One pass over the catalog + files, returned as a dict and printed by the
CLI:

- **`needs_split`**: branches with > 150 entries or > 3.000 body tokens
  (A.5 rule).
- **`fat_nodes`**: nodes with degree > 50 (A.2 rule — branch candidates).
- **`lint`**: error/warning counts from `vine validate`'s engine (includes
  payload drift, C.10).
- **`stale_passports`**: passports whose `source_path` no longer exists
  under the Gardener's `source_root` (when configured).
- **`uncertain_links`**: inventory of managed links by confidence bucket
  (what the next promotion/pruning cycle will look at).
- **`heat`**: row count + max/mean of the persistent scope (pheromone
  health at a glance).

### H.4 Execution model

- `vine ranger [--forest DIR]` — one full cycle: evaporate → tend links →
  health report.
- `vine ranger --every N` — service mode: repeat every N seconds until
  interrupted (Docker-friendly; the deploy doc's `ranger (cron)` box).
- The Ranger takes an injectable clock (`now`) — the synthetic-clock tests
  of F.14 depend on it.

### H.5 Ranger config (`_meta/ranger.yaml`)

```yaml
half_life_days: 30
session_ttl_hours: 24
promote_floor: 0.2
promoted_confidence: 0.8
prune_below: 0.5
payload_cache_gb: 5        # H.6 (v0.11)
```

### H.6 Payload-cache eviction (v0.11)

The Ranger evicts `_derived/payloads/` entries least-recently-used first
when the cache exceeds `payload_cache_gb`. Eviction is always safe: every
cached entry is re-fetchable from its source URI and hash-validated on
return (G.9.1). Evaporation for bytes — same philosophy as H.1.

### H.7 Landmarks refresh (v0.13)

The Ranger keeps the master `_index.md`'s `## Landmarks` section (A.5)
populated — the forest's hubs, discovered mechanically:

1. **Selection**: top 10-20 nodes by degree over the catalog's typed-edge
   table (frontmatter `links`, both directions). Excluded: `branch` nodes
   (a landmark must carry scent), `_meta/*`, and degree-0 nodes. The
   folder hierarchy (`parent`) does NOT count toward degree — landmarks
   measure how woven a node is, not how filed.
2. **Rendering**: A.5 entry lines (`- [[id]] — <summary>`) inside the
   `## Landmarks` section of the master branch only. The section is
   created if the heading is missing.
3. **Idempotence**: the section is rebuilt in full and compared; an
   unchanged graph produces no write and no commit.
4. **Write path**: the audited `.md`-only pattern (H.2) with commit
   message `ranger(landmarks): refresh`, followed by a catalog upsert of
   the master index. No LLM, no node creation, no link changes.

---

## Part I — Snapshots (v0.11)

A forest snapshot is ONE file: the forest's git repository packaged as a
`git bundle` (the full commit history — every plant/tend/gardener/ranger
audit trail — travels along), compressed.

- `vine snapshot create [--out FILE]` → `<forest>-<date>.bundle.zst` (or
  `.bundle` when zstd is unavailable). Payload `.db` files are NOT inside
  (they are not in git, A.3.1); `--with-payloads` adds a sidecar archive.
- `vine snapshot restore FILE --forest DIR` → a full forest clone with
  history; `vine reindex` rebuilds the derived layer.
- Upload to object storage rides the G.9 fetcher (`--to s3://...`).
- The Ranger MAY schedule snapshots in service mode (backup policy:
  interval + retention), config in `_meta/ranger.yaml`.

Use cases (informative): backup/DR, distribution (a team pulls the whole
MAP in one small download — the scent tier is ~0.1% of the source),
frozen releases of a knowledge base ("the forest as of Q2 close").

---

## Part J — The Station (host layer: self-host, governance, scoped access)

### J.0 Position

Parts A-I describe a forest and the Vine that reads it, for one operator
who owns the filesystem. Part J describes the **Station**: the service that
serves forests to *many* principals — with identity, policy, audit and a
web console — so that a forest becomes a governed corporate asset instead
of a personal directory.

The Station is a **privileged client**, never an extension (G.0):

- The engine (`src/monkeyllm/`) MUST NOT gain policy, identity or tenancy
  awareness. Primitive semantics, budgets and guards are identical whether
  a call arrives through the Station or through `vine serve`.
- Forests remain content. Principals, tokens and policies MUST live in the
  **host registry** (host-side storage), never inside a forest — a forest
  handed to another operator carries no credentials.
- Every write remains a git commit inside the forest (A.3), and binaries
  remain outside that git (A.3.1).

### J.1 The Station

The Station mounts a **forest registry** — a root directory whose valid
forests are resolved exactly as C.0 registry mode already resolves them —
and exposes three surfaces:

| Surface | Consumer | Transport |
|---|---|---|
| REST | applications, scripts, integrations | HTTP/JSON under `/v1/` |
| MCP | agents, IDEs, bots | the Part C tool contracts, unchanged |
| Studio | humans | web console served by the Station (J.5) |

All three surfaces MUST route every forest access through the single
`ScopedVine` of J.3. An unscoped `Vine` handle MUST NOT be reachable from
any surface, including internal helpers and background jobs.

The MCP surface MUST remain contract-identical to `vine serve`: an agent
that works against a local Vine works against a Station-served forest with
no change beyond endpoint and credentials. Scoping is expressed only as
narrower *content*, never as a different shape (J.3).

### J.2 Identity

- **Principals** are users (humans) or service tokens (machines). Both are
  registry objects; both carry a stable id used in audit records.
- **Authentication:** API keys (stored hashed) MUST be supported; OIDC/JWT
  for corporate SSO MAY be added, mapping claims onto a principal.
- **Roles** are per-forest: `owner`, `gardener` (ingest and writes),
  `ranger` (maintenance), `reader`. A principal MAY hold different roles on
  different forests. Roles are shorthand for capability sets (J.3); an
  explicit policy grant always refines them.

#### J.2.1 Two doors, one identity

A human should not have to paste a 43-character secret to open a web
console, and a machine should not have to hold a password. So there are two
doors:

- **Password** — `POST /v1/auth/login {username, password}` returns a
  **session token**: an ordinary API key with a short lifetime and a
  `session` kind. Sessions MUST NOT appear in the token console; they are
  the by-product of a login, not a credential an operator manages.
- **API key** — pasted directly, as before.

Both MUST converge on the same `authenticate()` and the same J.3 policy
resolution. There is exactly **one** authorization path; the door only
decides how the principal was established, never what it may do.

**The environment super-admin.** `MONKEYLLM_STATION_ADMIN` and
`MONKEYLLM_STATION_PASSWORD` define a break-glass account, verified against
the environment with a constant-time comparison and **never stored**.
Hashing a value that already sits in the environment protects nothing, and
storing it would give a rotation two places to go wrong. It carries the
owner bit (J.2.4), so it governs a registry that holds no forest yet — the
grant-per-forest reading of this rule is what made an empty deployment
unreachable before v0.25. If the variables are absent, the door simply does
not exist — a deployment that never sets them has no default password,
which is the only safe default.

It is **break-glass and MUST NOT be the documented way in**. A deployment
that sets it has chosen an environment-held credential over an owner the
registry knows; both are legitimate, but they MUST NOT be offered at the
same time, and J.2.4 states which one wins.

Other principals MAY hold a password, set by an administrator and stored
**hashed with a memory-hard KDF and a per-principal salt** (unlike API
keys, a password is guessable, so the plain-digest reasoning does not carry
over). A principal without a password cannot use the password door at all;
absence MUST NOT degrade into a blank or default credential.

#### J.2.2 Token lifecycle

A credential that cannot be listed, expired or revoked is not governed. Every
API key MUST carry:

| Field | Why it is not optional |
|---|---|
| `label` | a token nobody can identify is a token nobody dares revoke |
| `expires_at` | the default answer to a leak nobody noticed |
| `revoked_at` | the answer to a leak somebody did notice |
| `last_used_at` | what makes an unused token safe to remove |
| `prefix` | lets a token be recognised in a list without being disclosed |

Authentication MUST reject expired and revoked keys, and MUST record last
use. Listing MUST return the prefix and this metadata and never the secret,
which is shown exactly once, at creation.

**The escalation rule.** A key authenticates a *principal*, and a principal
may hold grants on several forests. Minting or revoking a key for a
principal therefore requires `admin` on **every forest that principal is
granted**, not merely on one of them — otherwise the administrator of one
forest could mint a credential that opens another. For the same reason, the
token console MUST list only principals the caller fully administers.

#### J.2.3 The person as the unit of administration

Grants, passwords and keys are three tables and one thought. Onboarding
somebody is not three tasks performed in three places; it is one decision
with three consequences. `POST /v1/admin/people` therefore applies, for a
single principal and in this order:

1. **grant** — create or replace their access on one or more forests
2. **revoke access** — remove their access to one or more forests
3. **password** — set, replace or clear it (absent field means "leave it")
4. **issue key** — mint one, returned exactly once
5. **revoke keys** — one, or all of theirs

The order is normative because it is what makes first-time onboarding work
in a single request: the grant lands before the credential steps, so a
principal that did not exist a moment ago is administrable by the time its
password and key are created.

**A composite is not an authority.** Each step MUST re-check the rule that
governs it on its own — `admin` on the forest for (1) and (2),
`administers_fully` for (3), (4) and (5), and the environment account's
refusal to hold a stored password. A step the caller may not perform MUST
be refused **without abandoning the steps they may**: the response reports
what was applied and what was refused, because silently dropping half of a
submitted form is worse than either doing it or failing it.

**Several forests, one decision.** Access is rarely forest-shaped: an
analyst joins a team that reads four of the six forests, a CI service reads
all of them. Steps (1) and (2) therefore accept a **set** of forests —
`grant` MAY carry `forests: [<id>, …]` in place of `forest: <id>`, and
`revoke_access` MAY carry a list in place of a string. The scalar forms
remain valid and mean a one-element list.

A set MUST NOT weaken the per-forest rule. Each named forest is authorised,
applied and refused **individually**: an administrator of two forests out of
three who names all three grants two and is told, by forest id, why the
third was refused. Partial application within the step follows the same
reasoning as partial application between steps — the operator gets what they
were entitled to, and an explicit account of what they were not. The step
counts as applied when at least one forest landed.

`allow`/`deny` prefixes in a grant apply to **every** forest it names,
because a grant is one policy expressed once. Branch names are forest-local,
so naming several forests and a subtree at the same time is only meaningful
when the caller knows those subtrees exist in each; the API MUST NOT
second-guess that, while the console MUST NOT offer it blindly (J.5.5).

**The escalation rule is unaffected.** A key authenticates a principal, so
minting one still requires `admin` on every forest that principal holds
(J.2.2). Widening a principal to a forest the caller does not administer is
refused at step (1) and can never become a back door into step (4): step (4)
re-reads the principal's grants as they stand after step (1).

`GET /v1/admin/people` returns, per principal the caller administers:
identity, grants (filtered by J.3.2), whether a password exists, their
tokens, and when they were last seen. The console MUST NOT have to
reassemble a person from three endpoints; that shape is the registry's, not
the operator's.

#### J.2.4 First-run setup, and the owner

A Station is installed before it has an administrator. Until v0.25 that
first moment had no answer: authority was a sum of per-forest grants, an
empty registry summed to nothing, and J.7 would not hand over the first
forest because there was no existing one to be admin of. A product MUST be
reachable through its own front door on first boot.

**The owner bit.** A principal MAY carry `owner`, a property of the
principal itself. An owner holds `admin` on every forest in the registry —
**present and future, including none**. It is not a grant, is not stored
per forest, and is not re-derived at startup:

- authority that must be able to create the first forest cannot be derived
  from a forest, or the deadlock simply moves;
- re-granting at boot drifts — every forest created later needs the same
  loop to run again, and the one time it does not is a support ticket;
- a grant can be revoked forest by forest, which would silently produce a
  half-owner. The bit is atomic: an owner is one or is not.

There is **exactly one owner**, and the bit is not grantable through
`/v1/admin/people` or any other route. Governance is still per forest
(J.3.2); the owner is the root of it, not a second tier of console.

**The setup route.** `POST /v1/auth/setup {username, password, email?}`
creates the owner and returns a session token, exactly as a login would.

- It MUST be **unauthenticated**, because there is nobody to authenticate.
- It MUST exist **only while the registry holds no credential of any kind**
  — no password, no non-session API key. That is the one condition under
  which an open route creates no privilege escalation: there is no
  privilege yet to escalate from.
- It MUST NOT exist while an environment super-admin is configured. That
  deployment has already declared its first identity, and two open doors
  competing for it is the race this section exists to forbid.
- Once it has run it MUST close **permanently**. A closed route MUST answer
  exactly as an unrouted path does — not "already configured", which
  publishes the deployment's state to anyone who asks.
- The check and the creation MUST be **one atomic transaction**. Two
  simultaneous requests MUST produce one owner and one refusal, never two
  owners. This is the whole security surface of the feature: a
  check-then-write with a gap between them is a back door with a race
  condition as its key.
- `email` is **optional**, stored locally as the owner's contact, and MUST
  NOT be transmitted anywhere. A setup step that depends on a network call
  cannot complete on an air-gapped host, and asking for an address in
  exchange for nothing is a poor first sentence for a product to say.
- The password is stored under the J.2.1 rules — memory-hard KDF, salted.
  The owner is an ordinary principal that happens to carry a bit.

**The first forest.** Setup MAY create one, and the choice MUST be the
operator's: an empty forest, or a **seeded demo** whose only purpose is that
`Ask` and `Explore` have something to answer on the first visit. Neither is
required — an owner with no forest is now a valid, workable state, which is
precisely what v0.24 could not represent.

The seed MUST be **generated, never shipped as content**: a generator that
calls only public primitives, living outside `src/monkeyllm/` because the
engine carries no vocabulary of its own (a forest is content, and content
is not the engine's business). A demo forest MUST NOT be committed to the
repository — the generator is the artifact, the forest is its output.

**F.28 (acceptance).** On a registry with no credential and no environment
super-admin, `GET /v1/health` reports setup is required and the setup route
creates an owner whose session **immediately** reports `admin`, holds
`admin` on a forest created *after* the owner existed, and is refused by
nothing that `admin` permits; the same route, called a second time, answers
byte-identically to an unrouted path, and two concurrent first calls produce
exactly **one** owner and one refusal — proven by running them against one
registry, not by inspecting the code. With an environment super-admin
configured, the route MUST NOT exist at all. An owner MUST be able to create
the first forest on an empty registry, and a non-owner without grants MUST
still be refused it. Clearing every credential MUST NOT reopen setup while
the owner principal exists — all covered by tests.

### J.3 Policy and enforcement — `ScopedVine`

**Unit of scope: the branch prefix.** The hierarchy that Part A already
maintains is the policy surface — a grant names a subtree, not a node list.

A policy binds one principal to one forest:

```yaml
principal: <id>
forest:    <forest-id>
allow:     [projects/, sales/reports/]    # subtree grants
deny:      [projects/secret/]             # carve-outs; deny wins
caps:      [read, write, query, tend, ingest, admin]
datasets:                                 # optional narrowing
  sales/report-q1-2026: {tables: [sales]}
```

Resolution rules: absent policy means **no access** (deny-by-default); a
node is in scope when some `allow` prefix matches its id and no `deny`
prefix does; `deny` MUST win over `allow` at any depth.

`ScopedVine` wraps the ten primitives plus `harvest` with exactly one rule
each:

| Primitive | Enforcement |
|---|---|
| `locate`, `scan` | candidate set restricted to in-scope nodes **before** ranking, budgeting and truncation |
| `sniff` | body search space restricted to in-scope nodes |
| `look`, `pick` | node MUST be in scope, else `E_NOT_FOUND` |
| `move` | edges whose other endpoint is out of scope MUST be omitted from the response |
| `harvest` | inherits the above (it is a C.6c composite, not a bypass) |
| `query` | requires `query` cap and an in-scope `type:dataset` node; the optional table allow-list is checked against the parsed statement; C.9 read-only guards unchanged |
| `tend` | requires `tend` cap and an in-scope dataset; C.10 guards unchanged |
| `plant`, `graft` | require `write` cap; the target id MUST be in scope |
| Gardener `adopt`/`sync` | require `ingest` cap; MUST NOT write outside scope |

**Two invariants, both security-critical:**

1. **No truncation oracle.** Scope filtering MUST be applied before token
   budgets and `truncated` are computed. A scoped response MUST have the
   same shape and budget semantics as an unscoped one; a caller MUST NOT
   be able to infer hidden content from result counts or truncation flags.
2. **No existence oracle.** An out-of-scope node MUST produce a response
   byte-identical to that of a node that does not exist (`E_NOT_FOUND`,
   same hint). This extends to `move`: an omitted edge MUST be
   indistinguishable from an absent edge, because an error or a placeholder
   would itself disclose the forbidden node.

Structural consequence: `ScopedVine` composes the public `Vine`; it MUST
NOT patch, subclass around, or reach into engine internals. Any behavior it
cannot express through public primitives is a spec gap to be resolved here,
not a monkey-patch.

#### J.3.2 Administration is per forest

J.3 scopes *content*. The same reasoning governs *governance data*, and it
is easy to miss because the capability check passes: holding `admin` on one
forest admits a caller to a host route, and that is all it does. It is
never a licence to read rows about forests they do not administer.

Therefore every host route that returns registry data MUST filter its
result to the forests the caller administers:

| Route | Filter |
|---|---|
| `/v1/admin/principals` | principals holding a grant on an administered forest, with `grants_detail` reduced to those forests |
| `/v1/admin/audit` | entries whose forest is administered |
| `/v1/admin/keys` | principals the caller administers **fully** (J.2.2 — a key spans forests, so partial administration is not enough) |
| `/v1/admin/grant`, `/v1/admin/models` | already per forest; unchanged |

A branch prefix is a description of somebody's world, and an audit entry
is a record of what they read. Neither becomes public because the reader
happens to administer a different forest.

*Boundary (informative):* providers (J.10) are a **host** resource, shared
by every forest, so any administrator sees and edits them. This is by
design and it has a cost worth stating: removing a provider removes the
bindings of forests the remover may not administer. A per-owner provider
model would be a new concept, and it belongs in a later version rather
than as an implementation detail here.

### J.4 Audit

- **Writes** are already commits; the Station MUST stamp the acting
  principal in the message, following the existing convention
  (`station(<principal>): <action>`, cf. `ranger(promote|prune)`). Git
  history remains the source of truth for what changed.
- **Reads** extend Part D telemetry with the principal: every scoped call
  records `(principal, forest, primitive, argument digest, result size,
  timestamp)`. Bodies and snippets MUST NOT be copied into the audit log —
  it records access, not content.
- The pair MUST be sufficient to reconstruct any answer's full trail after
  the fact: which principal, which primitives, which nodes, in which order.

### J.5 Studio

A web console served by the Station. Studio MUST consume only the
documented REST surface. It MUST NOT hold a privileged side-channel:
whatever Studio can do, an API client with the same principal can do — and
whatever a principal cannot do, Studio cannot show. Localisation and
theming are presentation: they MUST NOT change any request, response or
permission.

#### J.5.1 Information architecture

The console is organised into three groups, answering three different
questions an operator arrives with:

| Group | Console | Answers |
|---|---|---|
| **Use** | Overview | what is in this forest and what may I do here |
| | Ask | what does the forest know about *X* |
| | Explore | where does a fact live, and what is next to it |
| | Playground | what exactly does an agent see, and what would this call cost |
| | Data | what do the datasets contain |
| **Build** | Ingest | how do I put my documents in |
| | Models | who reads this forest, and who summarises it |
| **Govern** | People | who exists, what they may see, how they sign in |
| | Audit | who saw what |

Navigation MUST carry an icon per console alongside its label: the console
is used by people who did not choose these names, and a name alone is a
weak target.

Navigation MUST list exactly the consoles the principal's capabilities
permit on the selected forest, and MUST re-evaluate when that forest
changes — capabilities are per forest, so the menu is too. `Ask` is the
default landing console for a principal holding `read`; a principal
without it lands on the first console they do have.

**Hiding is presentation and MUST NOT be the control.** Each console keeps
its own capability guard, because a hidden entry is still reachable by
anyone who can set application state, and the API remains the authority: it
already refuses, and it would refuse a request the console never sent.
Where a console is *partly* available — `Access`, which shows a principal
its own grant whether or not it may administer others — it stays listed and
explains the missing half rather than disappearing.

#### J.5.2 The vocabulary rule

The console MUST address the operator in the operator's vocabulary. The
policy model of J.3 is storage, not interface:

- **Roles before capabilities.** Access is granted by choosing a named
  role; the resulting capability set MUST be shown as a *consequence* of
  that choice, never demanded as the input. Refining the set directly MAY
  be offered as an explicit deviation from a role.
- **Scope is picked, not typed.** Branch prefixes MUST be selectable from
  the forest's actual branch tree. Free text MAY remain available; it MUST
  NOT be the only way in, because a typed prefix that matches nothing is
  indistinguishable, in a text field, from one that matches everything.
- **The grant MUST be restated in a sentence** before it is saved: which
  principal, which branches out of how many, what they will be able to do,
  and what they will not. A policy an operator cannot read back is a
  policy they cannot audit.

#### J.5.3 Localisation and theme

- The console MUST ship **English, Portuguese and Spanish**, complete: a
  missing translation is a defect, not a fallback. It MUST detect the
  browser's preference on first load and persist an explicit choice.
- The console MUST offer both a **light and a dark** presentation, follow
  the operating system preference until told otherwise, and persist an
  explicit choice.
- Content is not chrome. Node ids, titles, summaries, bodies, SQL and
  model output are forest data and MUST be rendered as stored — the
  console translates its own words only.

#### J.5.4 Credentials, and the panel that does not exist

Issuing, listing and revoking API keys follows J.2.2: label, principal,
expiry, last use, prefix. The secret appears once, at creation, and the
console MUST say so at the moment it is shown rather than afterwards.

The access **levels** MUST be documented in the console itself — the named
roles, what each one can do, and what it cannot. An operator choosing a
level should not have to leave the screen to learn what the choice means.

#### J.5.5 The People console

Governance is presented **per person**, not per table:

- **Onboarding is one form.** Who they are, what they may see, how they
  sign in, and a token if they need one — submitted together, because that
  is one decision. Splitting it across screens makes the operator hold the
  model that the interface should be holding for them.
- **Forests are chosen as a set, not one at a time.** The form MUST offer
  every forest the operator administers as a multi-selection with an
  all-or-nothing control, in a bounded, scrollable region so that a registry
  with fifty forests looks like the same form as one with three. A
  single-choice control here would be the interface asserting that access is
  forest-shaped, and it is not: repeating the whole form once per forest is
  how a five-forest grant becomes four forests and a forgotten one.
- **Branch scope appears only when it means something.** Branch names are
  forest-local (J.2.3), so the subtree picker is offered when exactly one
  forest is selected; with several selected the grant covers each forest
  whole, and the form MUST say so rather than silently applying one forest's
  branch names to another's.
- **The list is the maintenance surface.** Every person the caller
  administers appears with their level, scope, whether they can sign in,
  how many live tokens they hold, and when they were last seen. Changing
  any of it starts from that row, not from a separate screen.
- **Credentials stay visible as credentials too.** A second view lists
  tokens across people, for the operator auditing what exists rather than
  who exists. Two views over one truth; not two places to maintain it.
- Secrets — a generated password, a new key — appear once, at the moment
  they are created, in the same place the operator was already looking.

**There is no separate super-administrator panel, and there MUST NOT be
one.** One console over one API, with capabilities deciding what appears: a
principal without `admin` does not see Tokens, and a principal with `admin`
on one forest does not see the credentials of another. A second panel would
require a second authentication path, and a second authentication path is
where the backdoor goes — this is the same reasoning as J.5's
no-side-channel rule, applied to the console's own front door.

#### J.5.4 Forest Views

A forest is a graph of nodes and typed trails with heat on it, and a tree
of files on disk. Both are the same truth; a console MUST be able to show
either without the operator changing consoles. The Explore console
therefore carries **modes over one selection** — the selected node survives
a mode change, because the operator did not stop looking at it.

| Mode | Shows | Reads |
|---|---|---|
| graph | nodes and trails, laid out spatially | J.11's `/graph` |
| tree | the branch hierarchy as a list | `scan` |
| files | the forest as files, one open at a time | `look`, `pick`, `query` |

**Encoding rules for the graph mode.** Every visual channel MUST carry a
fact the forest actually holds, and MUST NOT invent one:

- Node type comes from the forest's own dialect (`_meta/schema.md`, A.1).
  A console MUST NOT hardcode the type list: a forest that added a type
  gets a legend entry, not an unlabelled colour.
- Heat is the pheromone value of Part D, and a console that shows heat MUST
  show the value it received rather than a rank — heat is comparable across
  nodes and a rank is not.
- Link-level `confidence` below 1.0 MUST be visually distinct from curated
  links: it is a proposal under the Ranger's management (H.2), not an
  assertion. `discovered-shortcut` (C.8) MUST be distinguishable in turn.
- Layout is presentation and carries no meaning. A console MAY animate it;
  it MUST honour a reduced-motion preference by settling immediately.

**Rendering rules for the files mode.** A file MUST be rendered as what it
is, and its stored form MUST remain reachable:

- A node body is markdown: rendered by default, with the stored source
  available in one action. A body whose content is HTML is rendered as a
  page, sanitised; it MUST NOT be able to script the console, and it MUST
  NOT be able to reach the console's credentials.
- A `type: dataset` node's payload is a database: its tables MUST be
  listable and browsable through `query` and nothing else — the same single
  SELECT, the same injected LIMIT, the same timeout (C.5). A console
  browsing a payload is a `query` client, not a second access path.
- Frontmatter shown beside a body is the passport as the Catalog holds it.
  A console MUST NOT present a reconstructed passport as the file's bytes.
- A body over the `pick` budget MUST show the outline the primitive
  returned rather than pretending to have the whole text.

**Editing.** A console MAY offer editing, and every edit MUST leave as a
Part C write — `graft` for a node, `tend` for a dataset row. No surface,
the console included, may write a node file or a payload directly: the
commit, the validation, the index propagation and the audit record are the
write, and a "save" that skips them is a forest that no longer describes
itself. A console offering editing MUST show the operations before they are
applied: the operator is authoring a commit, and a commit is not a
keystroke.

#### J.5.6 The setup screen

The console has exactly two pre-identity screens. The Gate (sign in) is one;
the setup screen is the other, and which one appears is not the console's
choice — `GET /v1/health` already says whether a password door exists, and
it MUST also say whether setup is required. The console asks and renders the
answer. A console that decided this locally would eventually show a sign-in
form on a Station nobody can sign in to, which is the bug this whole section
exists to remove.

- It MUST collect a username and a password, MAY collect an email, and MUST
  label the email as optional in the interface rather than only in the API.
- It MUST offer the first-forest choice of J.2.4 — empty or seeded demo —
  and MUST let it be skipped. An owner with no forest is a valid state and
  the console MUST render it without looking broken: the existing "no
  forest" empty state already carries the create action for an
  administrator, and the owner is one.
- It carries the language and theme controls, for the Gate's reason (J.5.3):
  the first screen a person sees cannot require a session to be legible.
- It MUST NOT be reachable once setup has closed. The route is gone by then,
  so the console MUST treat a failed setup call as "someone else got here
  first" and fall back to the Gate rather than retrying.

Everything else in J.5 is unchanged: there is still no second panel, the
owner uses the same nine consoles as anyone else, and what appears is still
decided by capabilities (J.5.4).

#### J.5.7 Shaping the forest (v0.27)

A.5 gives a new forest one branch, its master index. Part G grows more, but
only by mirroring a source tree — `adopt` derives structure, it does not
invent it. So a forest whose documents arrive through `upload` or `compose`
has nowhere to put them except the root, permanently, and the operator's
only recourse is to leave the product, arrange a folder tree on some other
machine, and mirror that instead. The console MUST be able to add a branch.

- **Through `plant`, and through nothing else.** A branch made here MUST be
  the same node an agent's `plant` would make: same validation, same commit,
  same audit row, same entry grafted into the parent index by the engine.
  The console composes a call; it does not write files, does not maintain
  the parent's `## Sub-branches` list, and adds no second idea of what a
  branch is. This is the J.7 rule (`the Station adds no second way to make a
  forest`) one level down.
- **The operator names it; the console derives the id.** The name is
  slugified into a path segment and the id is composed as
  `<parent>/<slug>/_index`. Ids MUST NOT be typed by hand in this flow:
  they are immutable (C.7), so a typo is not a mistake to correct but a
  node to abandon, and the engine's own check — that an id lives under the
  parent it names — is unhelpful to someone who did not know they were
  writing a path.
- **The parent is chosen, never typed**, and only from branches the
  principal can already reach. A parent it cannot read is not a parent it
  may write under, and offering one produces a refusal the operator cannot
  act on.
- **The summary is required, and the engine judges it.** It is the A.4
  scent every later hop navigates by, so it is not optional and not
  derived from the name. The console MAY show the 60-token budget while
  typing; it MUST NOT implement its own rule, because two validators
  disagree eventually and the engine's is the one that decides.
- **A new branch carries the A.5 index skeleton** — `## Sub-branches`,
  `## Direct bananas`, `## Cross trails` — so it reads like every other
  branch from the first moment rather than growing headings the first time
  something is planted into it.
- **Scope is the engine's, restated in the interface.** `ScopedVine`
  already refuses a write outside the grant, so a scoped principal cannot
  create at the root; the console MUST NOT offer a parent it knows will be
  refused. Hiding is presentation and never the control (J.5.1) — the API
  still refuses what the console never sent.
- **Where it lives.** Two places, one component: the Explore console, where
  an operator is looking at the shape of the forest, and inline in the
  Ingest destination picker, because "where do these go?" is exactly the
  moment a missing branch is noticed. The picker's create action MUST make
  the branch and then select it, so the ingest that prompted it continues
  without a second trip.

**What this is not.** There is no move, no rename and no delete. A node's
id encodes its branch and ids are immutable, so relocating one would mean
a new id and every `related-to` link pointing at the old one going stale;
no primitive does it, and none is specified here. The console can create
structure and curate what is in it (`graft`, and the Curator through
J.10). An operator who puts a branch in the wrong place lives with it or
rebuilds the region deliberately — which is the honest cost of ids that
are also addresses, and is stated here so that nothing downstream is
designed against a file manager this product does not have.

**F.30 (acceptance).** A principal holding `write` creates a branch through
the console's call and gets a node whose `type` is `branch`, whose id is
`<parent>/<slug>/_index`, whose parent index gained exactly one
`## Sub-branches` entry, and whose creation appears in the audit log with
a commit sha — none of it written by the console. The same call with a
name that slugs to nothing is refused, a duplicate id is refused, and a
summary that breaks A.4 is refused by the engine rather than accepted and
truncated. A principal scoped to a subtree is refused a branch at the root
with `E_FORBIDDEN` and succeeds inside its own grant. All covered by tests.

### J.6 Deployment

A Station deployment MUST be reducible to one container image plus two
volumes — the forest registry and the host registry — with no external
database required. Snapshots (Part I) remain the backup unit; the host
registry is backed up alongside them.

**The working directory is not a location (normative, v0.26).** A Station
process MUST NOT run with its own installation tree as its working
directory. The rules of G.3 and J.8.2 are what *prevent* an unnamed source
from being walked; this one decides what an unnamed source would have
reached had they failed, and the answer should be an empty directory
rather than the product's source code. Ingestable material belongs on its
own volume, mounted for that purpose and named in `MONKEYLLM_INGEST_ROOTS`
— never on the image.

### J.7 Forest lifecycle

A deployment that can only serve forests placed on its volume by hand is
not self-service. `POST /v1/admin/forests {id, title, summary?}` creates
one, and creation is exactly A.5 `init_forest` — the same skeleton,
dialect and embedded git a local `vine init` produces. The Station adds no
second way to make a forest.

- The `id` is a directory name inside the registry root and MUST be
  validated **as a name, before it is a path**: a bounded character set,
  no separators, no relative segments. Rejecting after joining is too
  late.
- Creating requires the `admin` capability on some existing forest **or the
  owner bit (J.2.4)** — the authority to govern a forest is the authority
  to start another, and the owner is the authority that precedes every
  forest. A bootstrapped deployment therefore reaches its second forest
  through the API, an empty one reaches its **first**, and an unprivileged
  principal never reaches either. Requiring an existing forest of everyone
  was the v0.24 reading, and on an empty registry it locked the owner out
  of the only action that could unlock it.
- The creator MUST be granted the new forest with full capabilities.
  Creating a forest nobody can open would be a silent failure with a
  success status.
- An existing id MUST be refused rather than adopted: quietly returning
  someone else's forest because the name matched is an access-control bug
  wearing a convenience feature.

Deletion is deliberately absent. A forest is content with history; the
operator removes it from the volume, and Part I snapshots are how it comes
back.

### J.8 Ingest surface

Part G already turns directories into forest. J.8 exposes it, because the
operator who most needs ingest is the one who has a browser and no shell.
`POST /v1/forests/{forest}/ingest` takes one of four modes:

| Mode | Body | Does |
|---|---|---|
| `adopt` | `{path, dest?}` | mirrors a directory the **Station host** can read |
| `sync` | `{path?, dest?}` | G.8 hash-diff refresh of a previous adopt |
| `upload` | `{files: [{name, text}], dest?}` | stages the payload under the forest root, then adopts it |
| `compose` | `{title, text, dest?}` | stages one authored markdown document, then adopts it |

Common rules:

- Requires the `ingest` capability (J.3's Gardener row), and `dest` MUST be
  in scope. Ingest is a write; a principal who may not read a subtree MUST
  NOT be able to write into it, or scope becomes a one-way mirror.
- A principal whose scope is not the whole forest MUST supply `dest`.
  Defaulting to the root would let a narrowly scoped principal write where
  it cannot read.
- **Naming a host path is a privileged act** and MUST additionally require
  `admin` on the forest, **and** the path MUST pass J.8.2. `path` is read
  with the Station's authority, not the caller's, so `ingest` alone would
  turn a content capability into arbitrary read access to the host
  filesystem. The exception is a *targeted* `sync` of a path relative to
  the source root a prior adopt already recorded: that directory was
  vetted when it was adopted, and G.8's containment keeps the targeted
  path inside it.
- **A refresh MUST name what it will re-read.** `sync` without a source is
  the one call whose reach is invisible at the point of asking: it comes
  from configuration, not from the request. A console MUST therefore show
  the recorded source root beside the control, and MUST NOT offer the
  control at all for a forest that has none. A button whose scope the
  operator cannot see is not consent, and this is the shape the v0.25
  console shipped in.
- `upload` MUST validate each entry's `name` as a relative path with no
  escape, and stage under a directory inside the forest that is not itself
  forest content. Uploaded bytes are a source, not a node: they become
  nodes only through the same converters, curation and commits as `adopt`.
- The response is the Part G `IngestReport` — created, updated, unchanged,
  unsupported, errors — unabridged. A partially successful ingest that
  reports success is worse than one that fails.
- Curation uses the forest's `ingest` binding (J.10) when one exists and
  the deterministic G.4 derivation when it does not. Ingest MUST NOT
  require a model: a forest with no binding still ingests, with derived
  summaries.

- `compose` is `upload` with one authored document and a title instead of a
  filename. It exists because the alternative — a console that plants a node
  directly — would be a second write path with its own idea of what a
  passport is. Authored prose MUST go through the same converters, the same
  curation (G.4) and the same commits as an adopted file, and the
  edge proposals it receives MUST be the closed-candidate ones of G.4.2.1.
  A console MUST NOT let `compose` name a host path.

#### J.8.1 Composing with review

Curation is the one ingest step whose output a person may want to see before
it is true. A summary is the scent every later hop navigates by (A.4) and a
proposal is what the Ranger will spend the next month promoting or pruning
(H.2); both are cheap to correct in a draft and expensive to correct in a
node that already exists, has a commit, and may already have been read.

`compose` therefore takes two calls:

| Call | Body | Does |
|---|---|---|
| stage | `{mode: "compose", title, text, dest?, stage: true}` | converts, curates, proposes — and stops at the plant |
| accept | `{mode: "compose", title, text, dest?, draft: {…}}` | runs the same pipeline with the approved passport pinned |

Normative rules:

- **The staging call MUST NOT write forest content.** No node is planted, no
  frontmatter grafted, no commit produced, no branch created, no body
  cached, no source archived, and the Gardener's own configuration is
  unchanged. Writing the authored text into the staging area is not an
  exception to this: a staged byte is a source, and sources become nodes
  only by being adopted.
- **A dry run MUST be a property of the Gardener, not of a call.** A
  Gardener constructed to preview MUST be unable to write by any path it
  offers. A flag passed per call is forgotten by the next call that is
  added; an object that cannot write is not.
- **The staging call MUST report what the accepting call would produce** —
  the node id, its parent, type, summary, tags and proposed links, each link
  named by the title of what it points at. A review that shows an id without
  saying what it is is not a review.
- **Accepting MUST walk the same pipeline as an adopted file.** The approved
  passport enters as an `on_curate` hook (G.4.3), leaving the converter, the
  content policy (G.7), the plant and the commit exactly as they are for
  every other source. A second write path that plants from a draft directly
  would be a second definition of what a passport is, and nothing would keep
  the two honest.
- **Accepting MUST NOT re-curate through the model.** It would answer
  differently, and what shipped would then not be what was approved. The
  planted summary MUST be the approved one. (Branch rollup, G.4.4, is a
  different write about a different node and is unaffected.)
- **A returned draft is a client payload and MUST be re-validated**, exactly
  as if the reviewer had authored every field: the summary re-clipped to the
  A.4 budget, tags re-cleaned and capped at the G.4 maximum, and each link
  re-checked against G.4.2.1 — `rel: related-to` only, target existing and
  in scope, never a branch, never the node itself or its parent, capped at
  the proposal maximum. Trusting the round-trip would make the hallucination
  guard a client-side one, which is to say none.
- **A kept proposal stays at confidence 0.3.** A reviewer glancing at a link
  is not evidence that it is used, and 0.3 is precisely the population the
  Ranger manages (H.2). Promotion is earned by traffic; a human-authored
  certain link is `graft`'s job, not ingest's.
- **Review is compose-only.** `adopt`, `sync` and `upload` are batches whose
  drafts have no single decision to make; `stage` on those modes MUST be
  refused rather than silently ignored.
- **Neither call may be skipped by the other's arguments.** A body carrying
  both `stage` and `draft` MUST be refused: it states two intentions and the
  host must not pick one.
- The two calls are otherwise indistinguishable to the policy layer: both
  require `ingest`, both scope-check `dest`, and neither may name a host
  path.

**F.27 (acceptance).** A staging call over a forest leaves `git rev-parse
HEAD` unchanged, adds no node to the catalog and writes no body cache, while
returning a draft whose id equals the one the accepting call plants; an
accepted draft whose links were edited to name a branch, an out-of-scope
node, a non-existent node, itself, its parent, a rel other than `related-to`
or a fourth proposal MUST plant with those links dropped, and every surviving
link at confidence 0.3; and the planted node's summary MUST be the approved
text, not a re-curated one.

*Attribution boundary (informative):* J.4 stamps the acting principal by
amending the commit a write produced. An ingest produces many — one per
node — and amending would rewrite only the last while claiming the batch.
The Station therefore records the resulting commit **range** in the audit
log and returns it, rather than rewriting history it did not author.

#### J.8.2 Ingest roots (v0.26)

G.3 bounds what a walk may *reach* once a directory is named. J.8.2 bounds
which directories a **host** will open at all, because the two questions
have different answers: a person at a shell already holds the filesystem,
and a request arriving over HTTP does not.

A Station MUST hold a list of **ingest roots** — absolute directories it is
willing to read on a caller's behalf — configured out of band
(`MONKEYLLM_INGEST_ROOTS`, OS path-separated). Every host path a request
names, in any mode, MUST resolve to a location at or underneath one of
them, compared **after** resolution so `..` and symlinks are collapsed
first.

- **The default is empty, and empty means none.** An unconfigured Station
  MUST refuse every host path and still serve `upload` and `compose`,
  which carry their own bytes and stage inside the forest. This is the
  normative default and not merely a recommended one: a deployment whose
  operator has never read this document is the deployment that most needs
  the boundary, and a control that must be switched on is a control that
  is off wherever nobody knew to look. The refusal MUST name the setting,
  because an operator who *did* mean to mirror a host folder learns the
  one thing they need from the error itself.
- **`admin` is not a bypass.** The capability answers *who may ask*; the
  roots answer *what exists to be asked for*. Collapsing the two puts the
  host's whole filesystem one grant away, and in a self-hosted deployment
  the operator holds that grant by construction — which is exactly the
  reader who is not protected by a rule addressed to attackers.
- **The registry root is never an ingest root**, listed or not, nor is any
  ancestor of it. G.3 already prunes a forest met inside a walk; this rule
  refuses the walk. One forest reading the volume that holds every forest
  is the tenant boundary failing in the only direction that counts, and a
  configuration mistake MUST NOT be able to express it.
- Roots that do not exist at boot are a **startup** error, not a per-call
  surprise: an operator who mistyped a mount learns it from the log at
  boot rather than from an ingest that quietly refuses months later.
- The list bounds host paths only. Staged uploads live under the forest's
  own `_derived/` (J.8) and are generated, not named by the caller, so
  they are outside this rule — as is a targeted `sync` path, which is
  relative to an already-vetted source root and contained by G.8.

**F.29 (acceptance).** With `MONKEYLLM_INGEST_ROOTS` unset, an `adopt`
naming any host path is refused for an `admin` principal and for the
owner, with an error naming the setting, while `upload` and `compose`
succeed unchanged. With a root configured, a path inside it succeeds; a
path outside it, a path that resolves outside it through `..` or a
symlink, and the registry root itself are each refused. A forest that has
never adopted refuses a bare `sync` without reading any directory, and the
`_meta/gardener.yaml` of that forest still records no `source_root`
afterwards. A `sync` whose targeted path escapes the recorded source root
is refused. A `pick` of a `reference` node whose `source_path` points
outside the source root fails `E_NOT_FOUND` without disclosing the file's
contents. An `adopt` of a directory containing another forest plants no
node from it. All covered by tests.

### J.10 Per-forest inference

**Providers.** An operator registers named endpoints in the host registry:
a name, an OpenAI-compatible `/v1` base URL, and an optional key. Any
compatible gateway qualifies — OpenRouter, LiteLLM, vLLM, a local
llama.cpp. Credentials are **write-only across every surface**: the API
accepts a key and reports only whether one is set (`has_key`), and an
update with an empty key MUST preserve the stored one so an endpoint can
be corrected without re-pasting a secret.

**J.10.1 Environment-declared providers.** A deployment that already sets
`MONKEYLLM_LLM_ENDPOINT` / `MONKEYLLM_EMBED_ENDPOINT` (with their optional
`…_PROVIDER` name and `…_API_KEY`) has stated a provider. The Station MUST
publish it at boot so no operator is asked to re-enter it, marked
`origin: "env"` to distinguish it from a row somebody typed.

Its key **MUST NOT be persisted in the registry**: it is held for the life
of the process and resolved when a call is made. The registry file is a
backup target and the environment is not; a deployment that chose the
environment for its secret MUST NOT have it copied elsewhere as a side
effect of starting the host. Write-only still holds — `has_key` is the only
thing any surface reports.

Such a row is **read-only to the console**: an edit or a removal MUST be
refused, because the environment would reinstate it at the next restart and
the operator would meanwhile be looking at a configuration the deployment
does not have. Withdrawing the variables is the way to remove it; at the
next boot the row becomes an ordinary console provider — keyless, visibly
so — rather than being deleted, which would silently take its bindings with
it.

**Model discovery.** A provider already publishes what it serves, at
`/models`. The console MUST offer that catalogue when choosing a model —
with the per-token prices when the provider states them — rather than
asking an operator to type an identifier. Typing invites the failure this
rule exists to prevent: a model name from one provider bound to another,
which is well-formed, accepted, and wrong until the first call fails.

Discovery is a convenience, never a constraint: a model the endpoint does
not advertise MUST remain bindable, because gateways under-report and a
console that refuses an unlisted name would be less capable than the API
beneath it.

**Role bindings.** A binding maps `(forest, role) → (provider, model,
max_tokens, reasoning)` with `role ∈ {ingest, answer}`:

| Role | Used by | What to optimise for |
|---|---|---|
| `ingest` | curation at adopt/sync, `curate` | care: its output is the scent every later hop navigates by |
| `answer` | `answer` | speed and instruction-following over already-retrieved material |

A binding MUST be refused if the provider or the role is unknown, and
removing a provider MUST remove the bindings that pointed at it — a
dangling binding would fail at the worst possible moment.

### J.10.3 Model-backed composites

Two host composites, neither a primitive (the engine gains nothing):

- **`answer(question, k)`** — runs the scoped `harvest`, hands the result
  to the forest's `answer` model, and returns `{answer, model, model_ms,
  evidence, harvest, trace}` (J.10.4). Requires the `read` capability.
- **`curate(id)`** — re-summarises one node through the `ingest` model
  under the A.4 scent rules (validate-and-retry), returning the proposed
  summary rather than writing it. Requires the `write` capability, because
  it spends the operator's tokens.

**The invariant that makes binding a model safe:** retrieval runs through
`ScopedVine` *before* any model is called, so the model receives only
material the principal could already have read primitive by primitive.
Binding a model MUST NOT widen what a principal can see; if a composite
ever needs data outside the caller's scope, that is a specification
question, not an implementation shortcut.

*Known boundary (informative):* `answer` reads text. Facts that live only
inside a `type:dataset` payload are reached with `query`, so a question
whose answer is an aggregate over rows will be honestly refused rather
than guessed — unless the model is given the primitives and allowed to run
`query` itself, which is J.10.5.

### J.10.5 The answer that navigates

`answer`'s default is a sweep: `harvest`, one model call, done. Cheap,
predictable — and blind to anything not reachable from the entry list. It
is retrieval-augmented generation with a forest underneath, and it uses
none of what the forest is for.

`answer` therefore accepts **`hops`**: with it, the model holds the read
primitives and decides where to go until it can answer. This is the loop
criterion F.5 already measures offline; J.10.5 is that loop as a hosted
composite.

- **Opt-in, always.** One model call per hop against one for the sweep, so
  the default MUST remain the sweep. `hops: true` means the host's own
  budget; a number sets it. The budget MUST be bounded.
- **Read-only, by whitelist, not by capability.** The loop offers `locate`,
  `sniff`, `look`, `move`, `pick`, `scan`, `query` and nothing else. The
  policy would already refuse a write to a principal without the capability
  — but a principal who *has* `write` asked a question, and a loop that
  could `plant` would turn a question into an edit.
- **Every call goes through `ScopedVine`**, exactly as a client's would.
  The loop is a client with no privileges of its own; J.10.3's invariant is
  unchanged, not re-argued.
- **A spent budget still answers.** Running out MUST force one closing turn
  over what was already read, rather than discarding the hunt — the tokens
  are spent either way.
- **Evidence is what was opened.** Cited ids that the loop never read MUST
  NOT be returned as evidence: that is a claim about the forest rather than
  a reading of it.

The response carries `hops` alongside the `trace` of J.10.4, so the path and
its cost are both visible. A hop MUST report more than its tool name: the
arguments the model chose, one number for what came back (results, rows,
tokens, or the refusal code), and **two clocks** — the forest call and the
model turn that decided to make it. "sniff, sniff, locate" and "sniff → 0,
sniff → 0, locate → 5" are the same list of verbs and opposite stories, and
one combined duration would hide which half a slow hunt is spending.

The arguments appear here and **not** in the `trace`, deliberately: the
trace is the technical record and reports shape only (J.10.4), while a hop's
arguments are the model's own choices, derived from the caller's own
question, over results the scope already filtered.

Steps in the `trace` that a hop caused SHOULD carry that hop's number, so a
console can show a timing and the decision behind it in one place. The entry
`locate` is not a hop — the forager did not choose it.

**And it carries what it read.** The sweep can show the material because
`harvest` returns it in one bundle; a forager has a walk instead, so the
same evidence MUST be assembled from the hops and returned in the same
shape (`read`): `pick` bodies and sections, `sniff` snippets with their
section and line, `query` rows. A `look` is a digest and is not material —
naming a summary an excerpt would blur the one distinction this reporting
exists to make. A console MUST render both the same way, because "what was
this answer built from" is the same question in both modes.

### J.10.4 Explaining a composite

A composite is opaque from the outside: `answer` is one request, several
forest calls and a provider round trip, and a single elapsed number cannot
say which of them to fix. The usual suspicion — "the forest is slow" — is
almost always wrong, and there is no way to find that out from a total.

Calls that are several calls (`answer`, `harvest`) MUST therefore return a
`trace`: the ordered steps the call performed, each with its primitive, its
elapsed milliseconds, the tokens it emitted and — only for primitives that
take one — the node id; plus `retrieval_ms`, `total_ms`, and the provider
round trip as a `model` step. Consoles that answer questions MUST show it.

The engine already times every primitive it runs (Part D), so this is a
slice of that trace and not a second instrumentation: the events the call
appended, and nothing else.

**A trace reports shape, never content.** No arguments, no queries, no
snippets — a step names what ran and what it cost. Node ids appear only for
primitives the caller's own policy already admitted, since scoping happens
before the call the trace is describing; a trace therefore cannot disclose
what a scoped response withheld.

**What it cost, when the provider says so.** A composite that calls a model
MUST report the tokens the provider itself metered (`usage`) and, when that
provider publishes rates, the money: `cost: {prompt_tokens,
completion_tokens, calls, priced, usd}`. Two rules make it trustworthy.
Counting tokens locally is an estimate of somebody else's meter and MUST
NOT be substituted for it. And a provider that publishes no rate — a local
Ollama, a llama.cpp — MUST be reported as **unpriced**, never as free:
`priced: false` with no `usd`, because rendering silence as $0.00 is a
claim about money made from the absence of one.

### J.11 Map projections

`look`, `move` and `scan` answer *about this node*. A console showing the
shape of a region would have to ask them once per node, and a region is not
a node. Two read-only endpoints answer *about this region* instead:

| Endpoint | Returns |
|---|---|
| `GET /v1/forests/{forest}/graph` | `{nodes: [...], edges: [...], truncated}` |
| `GET /v1/forests/{forest}/trails` | `{heat: [{id, heat}], stats, truncated}` |

Both require the `read` capability and are subject to J.3 in full. Neither
is a primitive: they add no capability an authorised caller does not
already have, and everything they return is reachable node by node through
Part C. They are a *shape* the same authority can be asked for in one call.

Normative rules:

- **A node out of scope is absent**, exactly as in J.3 — never a stub,
  never a count. An edge is included only when **both** endpoints survive
  filtering; an edge with one visible end would disclose the other.
- **Every derived number is recomputed from what survived.** `degree` MUST
  count the edges present in the response, not the edges in the Catalog.
  A count taken over the whole forest is itself a disclosure (J.3).
- **Heat is the persistent scope only.** Session-scoped heat belongs to a
  hunt in flight and MUST NOT be observable through a map.
- **The Catalog is not the source of truth** (C.6.1). A projection MUST be
  documented as derived and rebuildable; a consumer that finds it stale
  reindexes rather than reconciling.
- **Bounded, and honest about it.** Both accept `scope` (a branch prefix,
  itself scope-checked) and `limit`. When a bound is reached the response
  MUST carry `truncated: true` — the same always-explicit rule as every
  primitive budget (C.1). A projection MUST NOT silently sample.
- The payloads carry no bodies. A map is scent, not flesh: `pick` remains
  the only way to a body, with its own budget.

**F.25 (acceptance).** For a scoped principal, every id appearing anywhere
in a map projection MUST be reachable by that principal through `look`, and
every `degree` MUST equal the degree computed from the projection's own
edges. A projection that fails either is an oracle.

### J.13 Maintenance surface

Part H's Ranger and Part I's snapshots are operator tools, and a hosted
Station's operator has a browser rather than a shell.

| Endpoint | Returns |
|---|---|
| `GET /v1/admin/health?forest=` | the H.3 report, unchanged |
| `GET /v1/admin/snapshots?forest=` | the bundles taken so far |
| `POST /v1/admin/snapshots` | `{forest, with_payloads?}` — takes one |

Normative rules:

- **Health requires `admin` on the forest AND an unrestricted scope.** The
  report is inherently whole-forest: it counts lint errors, names fat nodes
  and lists stale passports across everything. Filtering it to a prefix
  would leave numbers that silently describe nodes the caller may not see,
  which is the disclosure J.3 exists to prevent. A scoped principal MUST be
  refused with that reason stated, never served a filtered report.
- **The report is relayed, not recomputed.** Whatever `Ranger.health()`
  returns is what the endpoint returns. A host that reformats or summarises
  it becomes a second definition of the forest's health.
- **Health MUST NOT write.** It reports; evaporation, promotion and pruning
  remain the Ranger's own run (H.1/H.2), which is a scheduled job and not a
  side effect of somebody opening a console.
- **Snapshots are host state, not forest content.** Bundles MUST be written
  outside every forest — a `.bundle` inside a forest would be a binary in
  the tree A.3.1 keeps binaries out of, and the next snapshot would package
  the last one.
- **Restore is NOT exposed.** Part I restores into an empty destination, so
  there is nothing to offer a console operating on a live forest, and taking
  a filesystem destination from an HTTP caller spends the Station's
  authority rather than the caller's (the same reasoning J.8 applies to
  `path`). Restoring stays `vine snapshot restore`.

**F.26 (acceptance).** `GET /v1/admin/health` matches `Ranger.health()` field
for field on the same forest; a principal holding `admin` on a *branch
prefix* is refused with the scope reason rather than served; a snapshot
lands outside every forest directory and a second one does not package the
first; and no maintenance endpoint produces a commit.

### J.12 Out of scope for Part J

Engine changes of any kind (contracts, budgets, ranking); per-node ACLs
finer than the branch prefix; row-level filtering inside datasets beyond
the table allow-list; multi-writer forests (the single-writer lock stands);
billing and metering beyond per-token quotas.

*Documented boundary (informative):* scoping is per node, and node bodies
are author-written prose. A body that names an out-of-scope node discloses
that id to anyone who may read the body — the remedy is to keep such
references in the same scope, not to redact prose, which would corrupt the
content the forest exists to serve.

---

## Part K — The Gauntlet (query-conditioned frontier, v0.21)

### K.0 Why it is not the entry search

Part C's `locate` answers *where do I start*. Parts C.3–C.5 answer *where
do I go next*, and they answer it without knowing what the forager is
looking for: `look` sorts edges by heat, `scan` sorts children by degree,
`move` does not sort. Heat is the memory of past hunts and degree is the
shape of the graph; neither is about **this** question.

The Gauntlet is the instrument that closes that gap — a query-conditioned
ordering of the *frontier*, i.e. the set of nodes reachable in one step
from where the forager stands. In information-foraging terms it makes
proximal cue assessment conditional on the goal, which is what a real
forager's nose does and what static curated scent cannot do.

It is deliberately **not** a second entry search. Measurement (§5.1)
showed that fusing a dense ranker into an already-correct lexical one
degrades it. The frontier has no such ranker to degrade.

### K.1 Contract

When the Gauntlet is **active** for a call, the candidate list of `look`
(`edges_out`/`edges_in`), `move` (`neighbors`) and `scan` (`nodes`) is
ordered by a blend of query proximity and the existing signal, **before**
the edge cap and the token budget are applied. Ordering changes; shapes,
budgets, truncation semantics and every other field do not.

**Availability is not consent.** The vector layer has two possible
consumers and the measurement above says opposite things about them, so
*having* an index MUST NOT decide *using* it for either:

| Consumer | Default | Why |
|---|---|---|
| entry search (`locate` under RRF) | **off** | fusing into an already-correct BM25 degrades it |
| the Gauntlet (frontier order) | **on** when ready | there is no query-dependent ranker there to degrade |

An implementation MUST therefore keep the layer's *readiness* separate from
each consumer's decision. Binding an embedding model to a forest turns on
the Gauntlet and MUST NOT turn on hybrid entry search: an operator who
picks up the instrument has not asked for the degradation, and a feature
that silently enables a measured regression is a trap, not a default.

The Gauntlet is active only when all of the following hold:

1. an embedder is configured, and
2. a Canopy index exists, is non-empty, and its recorded model matches the
   embedder's (K.4), and
3. a **goal vector** is available for the session (K.2), and
4. the call did not opt out (K.3).

If any fails, the primitive MUST behave exactly as it does without the
Gauntlet — the same order, the same fields, the same bytes. Absence is not
a degraded mode; it is the Phase 0 contract, unchanged.

### K.2 The goal, and why it costs nothing

The goal vector is the embedding of the most recent `locate`/`harvest`
query in the session: the forager picks the instrument up when the hunt
starts and carries it for every hop after. `locate` MUST embed the query
whenever the layer is ready — **for the goal**, whether or not it also
fuses the result into its own ranking. That is one embedding per hunt, not
per hop, and it is the entire running cost.

The separation matters for exactly the reason K.1 gives: the query is
embedded so the forager can *navigate* with it, not so entry search can
re-rank with it. Each subsequent hop is a dot
product over vectors already stored in the Canopy — no network call, no
model call, and no tokens in either direction.

A caller MAY override the goal per call with an explicit `toward` string;
the implicit goal is what makes the feature free, and the explicit one is
what makes it testable.

The goal is session state and MUST be observable, never silent: a response
whose order was conditioned MUST say so — the primitive reports that its
frontier was ranked and toward what. A reordering the reader cannot see is
a reordering the reader cannot audit, which is the same objection this
specification raises to every other invisible transformation.

### K.3 Opt-out, and the experiment it enables

Every affected primitive accepts an optional boolean that disables the
Gauntlet for that call. This is not a convenience: a feature that claims a
navigation gain MUST be measurable **against itself on the same corpus in
the same session**, and that requires turning it off without restarting
anything or rebuilding an index.

Consoles that expose navigation (the Playground) and the answering
composite (`answer`) MUST surface that switch, so an operator can compare
the two orders on their own corpus rather than trusting a table measured on
somebody else's.

**The entry-search switch is a different switch.** `answer` composes
`harvest`, which is `locate` + `sniff` and never hops, so a *Gauntlet*
control on an answering console would change nothing — and a control that
changes nothing is worse than no control. What does change an answer is
K.1's other consumer: whether the vector layer is fused into entry search.
Calls that perform entry search (`locate`, `harvest`, `answer`) MUST
therefore accept an optional `hybrid` boolean, **defaulting to false on
every call**, for the same reason the opt-out exists: the published
degradation (R@1 1.00 → 0.40) has to be reproducible on the operator's own
corpus. It MUST NOT be sticky — a request that omits it is a BM25 request,
whatever the previous request asked for.

*Deployment note (informative):* whether the Gauntlet is available at all
is a property of the forest's configuration, not of the caller's identity.
A deployment MAY additionally pin it on or off for a given credential, but
the default is per-forest availability plus per-call choice.

### K.4 Index integrity (the mismatch guard)

The Canopy records the model that built it. Comparing a query embedded by
one model against vectors produced by another compares two unrelated
spaces: the result is not worse ranking, it is meaningless ranking, and it
fails silently because a dot product always returns a number.

Therefore: when the embedder's model differs from the index's recorded
model, the dense layer MUST be treated as **absent** — hybrid `locate` off,
Gauntlet off, Phase 0 behaviour — and the mismatch MUST be reported by the
forest's validation and by any surface that shows index status. Rebuilding
is the only resolution; a partial re-embed would leave the index in two
spaces at once.

### K.5 Out of scope

Re-ranking node *bodies* (that is `sniff`'s job and it is literal by
contract); replacing heat with proximity (they answer different questions
and H's pheromone economics depend on heat remaining a memory); and any
behaviour that makes navigation *require* an embedder.
