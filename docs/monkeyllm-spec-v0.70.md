# MonkeyLLM Technical Specification v0.70 (Phase 0/1/2 + host layer)

**Audience:** development team.
**Scope:** normative specification of the forest dialect (`schema.md`), the I/O contracts of the Vine protocol's primitives (MCP), the host layer that serves them to many principals (Part J), and the Phase 0 acceptance criteria.
**Companion document:** `monkeyllm-arquitetura.md` (architectural view).
**Convention:** the words MUST, MUST NOT, MAY follow the spirit of RFC 2119.

> Language note: as of the T02 translation pass (2026-07-02) the entire
> document is English. As of v0.5 every **contract token** (type/rel/enum
> values, parsed section headings) is English regardless of prose language.

**Changelog v0.69 → v0.70 the question is not the query.**

`locate` takes a question and hands it to FTS5 whole: split on whitespace,
each token quoted, joined by `OR`. Every article, preposition and auxiliary
verb in the sentence is therefore a search term with a vote. `harvest` has
never done this — C.6c derives terms first, through a stopword set that
speaks three languages — but the entry search that `harvest` itself calls
was never given the same treatment, and nobody had measured what it costs
because until now nothing could.

What could not be measured is the point. Of the labelled question sets this
project carries, two scored **recall@1 = 1.000 before any change** and the
third resolves one question in eighteen. A change to the entry ranker could
be neither approved nor refused. Measured against a new 60-question set over
a 1,877-node corpus — four classes, `expected_nodes` written from reading
documents rather than from running searches — the baseline is **0.711**, and
deriving terms first moves it to **0.778**, MRR 0.734 to 0.791: **five
questions up, none down**. Per class, the natural-language class carries the
loss it was expected to carry: 0.533 today, the worst of the four, with
seven of fifteen questions falling out of the top five entirely.

On the old instrument the identical change was three up and three down. It
is the same change. Only the instrument moved, and this changelog exists as
much for that as for the rule below: **a ranking change measured on a
saturated set has not been measured.**

Two rules follow, and the second is not optional decoration. Derivation can
return **nothing** — "api", "sql", "o que é isso" all derive to the empty
list, because the floor that keeps grammar out also keeps three-letter
lowercase tokens out. A `locate` that passed that straight through would
answer nothing at all to a caller who typed one word, which is the failure
C.1.1 exists to prevent, manufactured on purpose.

- **The entry search searches derived terms, not the sentence (amends
  C.1).**
- **An empty derivation falls back to the sentence (amends C.1).**
- Acceptance: **F.147 - F.148**.

**Changelog v0.68 → v0.69 a path is not a syscall.**

`Forest.path_for` turns an id into a file and, in the same breath, decides
that the file is inside the forest. It decides it with `Path.resolve()` — a
`realpath` walk, one syscall per component, symlinks followed — and a body
scan calls it **once per node in scope**. Measured on a served 1,877-node
forest: **72 ms of a ~230 ms cold `sniff`**, against **2.6 ms** for the same
containment decided on the string. Thirty-one percent of the call, spent
asking the filesystem a question the engine had already answered.

The decomposition around it is worth stating, because it is the second time
this call has been measured and each time the answer moved. v0.62 found
629 ms and left it at 133 by fixing the fold loop and the frontmatter regex.
What is left today, per cold call, is `path_for` at 31%, the fold at 32%,
reading every file at 16%, `_split_raw` at 2% — and `str.find`, the work the
primitive exists to do, at **1%**. The v0.62 changelog closed the trigram
question with "reading the corpus is 5% of the call"; after v0.62's own
fixes that number is 16%, and the sentence should not be quoted again
without its date.

The repair is not to stop checking. It is to notice that `path_for` answers
two different questions wearing one name. When a caller hands the Station an
id, containment is a **security** question about untrusted input and must
resolve symlinks. When the engine reads an id out of its own catalog —
which is what a scan does, for every node — containment is a question about
a node the engine itself planted and whose path it itself wrote. Paying
1,877 `realpath` walks to re-decide that is not caution; it is a boundary
check that drifted into a loop.

So the rule below is about **where** the check belongs, never whether it
happens, and it comes with the obligation that makes it safe: the boundary
set is written down and tested per surface, because the way this goes wrong
is silent. Nothing fails. An id simply passes.

- **Containment is enforced at every boundary that accepts an id from
  outside the engine (amends A.3.1/C.6b.1).**
- **An id read from the catalog is not such a boundary (amends C.6b.1).**
- **A write always resolves (amends C.7/C.8/C.14/C.15).**
- Acceptance: **F.145 – F.146**.

> Numbering note: this version takes **C.6b.2**. The prefix leg for a thin
> `locate` — drafted alongside this work — is deliberately NOT here and will
> take C.6b.3 when it lands. It widens what an entry search can find, and
> the labelled question sets available today contain no question whose
> correct answer is silence, so its central refusal criterion cannot yet be
> written. A widening shipped with its recall criterion provable and its
> restraint criterion absent is exactly the asymmetry that makes widening
> feel free.

**Changelog v0.67 → v0.68 the gauntlet rides inside the forest's clock.**

An operator asked a hosted question with hybrid entry on and read, on the
very panel J.10.4 exists for: forest 8437 ms, of which `locate` was 8391 —
beside sniffs and picks that each ran in fractions of a millisecond. The
panel's own premise is that the usual suspicion "the forest is slow" is
almost always wrong, and here the panel itself was the one raising it: the
forest's whole work in that trace was some forty milliseconds. The other
8.3 seconds were the K.2 query embed — one HTTP round trip to the embedding
provider, run inside `locate`'s span because K.2 puts it there, and timed
as `locate` because Part D times a primitive from outside, as it should.

Nothing sums the answer model into the retrieval figure — J.10.4 has
reported those apart since it existed. But the *other* model on the read
path, the embedder, had no clock of its own, so its round trip is billed to
whichever primitive it ran inside: `locate` when the entry embeds the
query (hybrid on), a walk's first `look`/`move` when the goal embeds lazily
(K.2). Two facts made the misattribution durable. The figure indicts the
wrong half — the operator reads "the forest took eight seconds" and tunes
an engine that spent forty milliseconds, while the provider, or its cold
model load, goes unexamined. And the memo (K.6) makes the number
unreproducible: the second ask of the same question embeds from
`_derived`, so the figure vanishes on exactly the retry that was meant to
confirm it.

The repair is a named share, never a second stopwatch. The Part D event
gains `embed_ms`: the milliseconds the call spent obtaining a query vector
through K.2/K.6 — memo hits included, because a hit's near-zero is the memo
working and is worth seeing — present only when an embed ran, so every
other event is byte-identical. `elapsed_ms` stays the whole wall span,
embed included: it is true, and a total that quietly excluded a slow
provider would be the flattering version of the same lie. J.10.4 forwards
the field on the step that paid it and sums it once as `trace.embed_ms`,
present only when nonzero; `retrieval_ms` and `total_ms` keep their
meaning to the byte, so no shipped number is redefined. And the console
rule: a panel that leads with the engine figure MUST NOT present the
embedder's round trip as the forest's — where `embed_ms` is nonzero, every
step and the forest figure are shown net of their share, and the summed
share is listed once at the tail beside the `model` step, in the model's
own tone: provider spend sits with provider spend, and every primitive row
is the engine's own smallest true number. The
`Server-Timing` header (J.10.6) is unchanged: its clocks partition the
host's span and `vine` still accounts the engine's wall time; the split
rides the trace, which is the channel the console already reads.

Acceptance: **F.143 – F.144**. The panel's rendering is normative text with
no test behind it, on the boundary F.142 already states.

**Changelog v0.66 → v0.67 a sample is not the corpus.**

A served forest of about twelve hundred nodes was asked what it was about.
In walk mode it read the readme and stopped; in sweep mode it generalised
five ranked excerpts into a claim about the whole forest. Neither answer is
a hallucination and neither is a defect in the loop: both are this
specification working exactly as written, which is why the repair is here
and not in a patch note.

There are four causes and each of them is a sentence nobody wrote.

**The walk's tool menu is closed** — "and nothing else" — and `coverage` is
not on it. C.17 exists for precisely the question that was asked; its own
motivating story is a faithful answer wrong about its subject, given because
nothing had told the agent what the corpus holds. The one read built for
that question class was barred from the one mode that could have chosen to
call it. It is on the list now, and it widens nothing: `coverage` is
metadata only and scope-filtered like every other read, so a walk that calls
it learns what the same principal could already have asked for directly.

**The sweep's prompt has no denominator.** It orders the model to answer
strictly from the material it was handed, and nothing anywhere says what
that material *is*. `searched` rides the empty path only — C.1.1's rule, and
it is the right rule — so a non-empty bundle carries no corpus size at all,
and five items out of twelve hundred arrive looking exactly like twelve
hundred out of twelve hundred. Generalising them is not the model
disobeying the prompt; it is the model obeying it. J.10.8 settled the shape
of this repair for a different number in v0.63 — the cap is stated whatever
chose it — and this is the same repair applied to the sample.

**The walk's entry is a synthetic retrieval nobody admits to.** The first
message is a `locate` of the raw question, labelled with the question, and
the prompt never says that no model chose those terms. Re-authoring the
retrieval — translating a Portuguese question into an English corpus's
vocabulary, reaching for the rarer term — is a move the walk has had since
hop 1 and was never told it was allowed to make. The machinery was there;
the sentence was not. Prompt wording stays implementation freedom, as it has
always been. What is stated here is what the prompt must not leave out.

**And nothing could hand authored terms to a hosted sweep.** J.10.7's key
text has read "whether the caller supplied them or the sweep derived them"
since v0.33, describing a path no surface offered: `harvest` takes `terms`
and `answer` did not, so both key builders re-derive from the question and
the first half of that clause has never once been true. `answer` takes
`terms` now, **sweep only** — a walk authors its own retrieval, and a
parameter silently dropped is a lie about what ran — and the key text
becomes a description instead of an aspiration. This is emphatically not a
planning turn: no model runs before the retrieval, C.6c stays zero-LLM,
J.10.11's phases stay in order, J.10.10's floor stays before the model, and
a call that sends no `terms` keys and answers exactly as it did. The
authoring happens in a client that already holds a model.

The remaining change answers none of those four. It is v0.65's path panel,
and its two defects are one defect twice: **it drew what did not happen.**
On a walk it ran a sweep the walk never runs and painted those dots as the
answer's retrieval, so the first picture an operator saw was of a retrieval
that never occurred, and the live hops then displaced it — which reads,
exactly and wrongly, as the model ignoring what it was shown. Rule 2's
justification ("they are the same sweep") is a sweep-mode sentence; in walk
mode there is no same anything, and rule 3 already forbids inventing a
stage. So the preview is mode-aware: no harvest is fired for a walk, the
panel starts empty, and it fills from J.10.12's `hop` events and, at the
close, the response's own `read`. For those events to light anything they
have to carry ids, and a hop record for `locate`/`sniff`/`scan`/`move` did
not — it carried a count, and a count lights no node. The record gains
`ids`, and F.138's event-equals-record comparison extends to cover them.

The panel's other defect was its background. It painted the whole edge set
of the J.11 projection, including the `confidence < 1` class Explore hides
by default, and painted that class at **twice** the opacity of structure; on
a curated forest carrying up to three proposals a node, that is the hairball
the operator reported. Dots only now, coloured by home branch the way that
operator's own Explore is set to colour them, with the full edge set still
feeding the layout springs — paint and physics split, which is what Explore
itself has shipped all along. The trail stays the only line drawn. And the
panel moves below the answer, accepts zoom and pan, and keeps its own
compact switch as a browser preference: the address carries the selection,
not the taste.

One thing in this version is not a contract and is named only so it is not
mistaken for one. The derived-term stopword set gains the Portuguese and
Spanish demonstratives beside the English ones it already carried: `esta`
was absent while `this` and `that` were present, so the question above
reached `sniff` as a substring search for `esta`, which matches inside
`restart` and `timestamp`. C.6b does not enumerate that set and this version
does not begin to — a list fixed in the specification is a specification
amended in every language somebody asks a question in.

Acceptance: **F.139 – F.142**.

**Changelog v0.65 → v0.66 the answer arrives once; the work does not.**

v0.65 drew the path an answer took and said, in its own changelog, what it
could not do: the walk's hops arriving one at a time, live, needs the host
to push. This is that push, and it is smaller than it looked.

The reason it looked large was a wrong diagnosis. A walk holds its reader
lane for its whole duration (J.10.11 says so), and the assumption was that
emitting a hop mid-call therefore needed the J.10.11 treatment — the model
lifted off the lane first. It does not. A lane is a thread in an executor
and the loop is reachable from any thread, so a hop can be handed across
without the walk changing where it runs at all. The lane question is real
and is about throughput; it is not this section's question, and conflating
them would have bought a large refactor to ship a small feature.

What is added is **one route and one optional field**. A caller may put an
opaque `run` on a `POST .../answer`; a caller that does not is byte-for-byte
where it was. `GET .../answer/{run}/events` is a `text/event-stream` that
carries the same call's progress: `retrieval` when the sweep's bundle exists
(19 ms in, against a reply 10 s out), `hop` as each of a walk's steps
completes, `done` at the close. Nothing about the answer's own response
moves, and the MCP surface gains nothing at all.

The rule that makes it safe is the one that also makes it simple, and it is
NOT J.16's. A webhook leaves the Station's authority behind — whoever holds
the URL reads it — so J.16 rations its payload down to identity. This
stream is the opposite shape: it is **pulled**, by the same principal, under
the same credential and the same scope, for a call that principal is already
making. So the rule is not "carry less than the response"; it is **carry
nothing the completed response would not have carried to this same
principal**. An event is a PREFIX of the answer, never a second disclosure
surface — `retrieval` is that response's own `harvest`, `hop` is its own
`hops[n]` — which is checkable by comparing the two, and F.138 does.

Three properties keep a spectator from costing the answer anything. Emission
never blocks: the lane hands the event to the loop and returns, and a
consumer too slow to keep up loses events rather than slowing the hunt.
Nothing outlives its call: the buffer is host memory like a J.9 job record,
a restart forgets it, and a channel closes rather than hangs — after a
bounded grace, because a watcher opens its channel before firing the call
(the only order that misses nothing) and a race is not an absence. And the stream is never the answer: the reply text
arrives on the POST alone, so a client that ignores the channel loses
nothing and a client that reads only the channel has no answer.

**Changelog v0.64 → v0.65 the retrieval is done long before the reply is.**

A hosted `answer` is two costs that differ by three orders of magnitude.
The sweep's retrieval is milliseconds — 19 on the 82-node fixture, 448 on a
1,902-node forest cold — and the provider round trip is seconds. J.10.11
already separates them so the model does not hold a reader lane, and J.10.6
already publishes them apart so a console can say which half was slow. What
neither of them changed is that the Station answers **once**: the bundle
exists as a value in the host at 19 ms and leaves the building at 10 s.

So the Ask console spent that gap on a spinner. It has always been able to
say WHAT was read — J.10.4 assembles the sweep's bundle and the walk's hops
into one shape for exactly that — but only as a list, only afterwards, and
never as a place. A forest is a graph (J.5.4 draws it), and a question that
reached three nodes in one branch out of nine reached them somewhere.

J.5.15 is that panel, and it is bounded by what can be known without a new
contract. The console runs the sweep's retrieval ITSELF, in parallel with
the answer, through the ordinary `harvest` primitive: same question, same
`k`, same entry ranker, deterministic and read-only, so what it draws is
what the answer will see rather than a guess at it — and it deposits no
pheromone, because heat is the whisper's at the close of an answer (J.10.7)
and never a read's. The map is the J.11 `graph` projection, already scoped,
already filtered, and already what Explore reads.

Two rules in J.5.15 exist because the honest version and the flattering
version differ. On a **sweep** `evidence` is every id in the bundle — the
reply is prose and names nothing — so there is no "the model chose these"
stage to draw, and drawing one would show a selection that never happened;
`cited` is a walk's stage, where `answer_nodes` is a real choice filtered to
what was actually opened (J.10.5). And on a walk the entry `locate` marks
nothing, because J.10.4 keeps only what carries text: the stage reads zero,
which is true, rather than being filled from `sources` to look complete.

The panel also states its own speed. The reveal takes seconds and the thing
it depicts took milliseconds, so the real figure rides beside it off the
Part D trace. A console whose subject is that retrieval is cheap must not
leave an audience believing the animation is the measurement.

What is NOT here: the walk's hops arriving one at a time, live. That needs
the host to push, which is a contract, and this version does not add one.

**Changelog v0.63 → v0.64 a transport method is not a capability.**

J.1.2 rule 4 says an announced capability with nothing behind it is an
instruction to every connecting client to spend a round trip learning
"empty", and the implementation applied it by deleting handlers from the
SDK's registry. It deleted one more than the rule names. Beside `prompts/*`
and `resources/*` it deleted **`subscriptions/listen`**, which at the
2026-07-28 era is not a feature of the resources family at all: it is the
only server-to-client channel there is, the replacement for the standing GET
stream of every earlier era.

What that costs is not a wasted round trip. The Station answers
`server/discover` at 2026-07-28 with a 200, which tells the client this era
is spoken; the client then opens its `subscriptions/listen` stream, and the
SDK answers an unregistered method with **HTTP 404**. In streamable HTTP a
404 has a meaning of its own (2.5.3: the server MAY terminate a session, and
must then answer 404 to requests carrying its id), so a conforming client
reads it as *your session is gone* and tears the connection down. The next
call dies with it. Measured against a released client (Antigravity, on the
Go SDK), the whole surface reported **0 tools**, and the error it printed
named a session id that was never issued rather than the method that was
never served.

Two facts follow, and they are separable. The first is that the deletion
went past the rule and is withdrawn. The second is that serving the method
changes one announced bit: at 2026-07-28 the SDK derives every list-changed
flag from whether the listen handler is served, so `tools.listChanged`
becomes `true` while this Station still publishes no such event. Under rule
4's own reasoning that is an empty promise — but the cost rule 4 was written
against does not exist here. A client that subscribes at this era opens one
stream that stays quiet; it spends no round trip listing anything, and the
alternative is not silence but a fatal 404. The earlier eras are unchanged to
the bit: `tools.listChanged` stays `false` at 2025-06-18 and 2025-11-25,
because there the flag is derived from notification options and not from the
handler.

- **A transport method is never withheld as an empty capability (amends
  J.1.2 rule 4).**
- **A refusal MUST NOT be spelled 404 on this transport (new J.1.4).**
- Acceptance: **F.135 - F.136**.

**Changelog v0.62 → v0.63 the budget nobody chose is still a budget.**

Every model binding shipped at `max_tokens` 600, and J.10.8 stated the cap in
the prompt only when a caller set `reply_tokens`. Both halves were sized for a
reply that is prose. The `answer` turn is not prose: it is a JSON object
carrying the answer text AND `answer_nodes`, so the budget pays for the
citation apparatus before it pays for a sentence, and a client that also asks
for a verbatim proof pays for that too.

Measured on the 18-question suite, a local 12B scored **16/18** at 600, and
neither miss was a navigation failure. One had already run `SELECT region,
SUM(amount) ... GROUP BY region` against the right dataset and was cut
mid-object. The other reached the right node in a single hop and held the
right sentence, then lost it when the truncated `proof` failed its audit. At
1500 both pass, and the wall time falls with them (139 s to 15 s, 149 s to
11 s) because the rejected retries stop happening. What kept this invisible is
the shape of the symptom: **a cut answer scores as a wrong answer**, never as
a cut. The console blames the model, the operator tunes the model, and the
model was right.

Raising the default repairs nobody on its own. A binding is a stored row, so
every deployment already on 600 stays there until somebody edits it by hand.
Hence a one-time data repair, and hence a stamp on it: the property that
matters is not that the repair runs but that it runs **once**. An operator who
chooses 600 after the upgrade must keep it, and a deliberate 600 is
byte-identical to the shipped one, so nothing but a version stamp can tell the
two apart.

The third rule is the one that would have made the first two unnecessary. A
cap the model is never told about can only be discovered by being hit, and
J.10.8 told it only when a caller had set `reply_tokens`, which is to say it
fell silent in exactly the case where nobody had chosen and the shipped number
was deciding alone.

- **The `answer` role is bound at 1500 (amends J.10).**
- **A shipped default is repaired once, and stamped (amends J.10).**
- **The cap is said whatever chose it (amends J.10.8).**
- Acceptance: **F.132 - F.134**.

**Changelog v0.61 → v0.62 the cold scan was never the corpus.**

C.6b.1's memo made a repeated `sniff` proportional to its matches and left
the first one alone. A term the forest has never been asked for is scanned
against every body in scope and no memo can help, because the fact it would
remember is the one being computed. That cost was reported against v0.59,
assumed to be the corpus, and deferred **on a condition** that it be
measured before a fix was designed, because the fix on the table was a
trigram index over bodies in `_derived/` a second search engine, to be
kept honest against C.6b's literal semantics forever.

The measurement is in, and it does not say what the deferral assumed. On a
1,902-node forest holding 11.9 MB of markdown, a cold `sniff` for a term
that matches nothing cost **629 ms of CPU**, of which reading all 1,902
files was **31**. The other 598 were two things this document had never
looked at:

- The **fold** lowercase and strip diacritics, which is C.6b's matching
  rule and therefore normative was a Python loop over every character of
  every body, with a dict lookup and a list append per character: **387 ms**,
  62% of the call.
- The **`content:` marker**, which decides whether a body is inline or lives
  elsewhere (G.7), was matched with a MULTILINE regex over the whole file
  to find a line that can only ever appear in the frontmatter: **71 ms**,
  another 11%.

Nearly three quarters of a "full corpus scan" was spent not reading the
corpus. Both are now what they should have been the fold is one
`str.translate` against a table built on first use, and the marker is
looked for in the frontmatter and the same call costs **133 ms**. The
sweep behind `answer` went from 933 ms to 448. Nothing about any answer
changed: these are cost rules under C.6b.1's first rule, and the fold's
identity to its own definition is verified over every code point Python can
represent, not over a sample.

The trigram index is **not** in this version, and its case is weaker than
it looked. It was proposed to remove a corpus read that turns out to be 5%
of the call it was blamed for. What remains true, and is stated here rather
than implied, is the shape: a cold `sniff` is still proportional to the
corpus and a warm one to its matches (the v0.59 rules below). A future
version that wants to change the first of those now has an honest baseline
to beat.

- **The fold is a table, not a loop (amends C.6b.1).**
- **A frontmatter marker is read in the frontmatter (amends C.6b.1/G.7).**
- **What a cold scan costs, measured (amends C.6b.1).**
- Acceptance: **F.129 – F.131**.

**Changelog v0.60 → v0.61 the write means what it said.**

Two rounds of outside verification (2026-08-21 and 2026-08-22) tested this
Station against its own promises. The read side came back untouched: the
grounded answer stayed faithful, the `min_score` floor kept refusing the
question whose evidence does not clear it, and the trace measured the
product's own regressions. Every finding that landed, landed on the other
half — **whether a write means what it said afterwards.**

`prune` removed a node, reported `pruned: true`, and the next upload to
the same branch **replanted it**, with a fresh timestamp and an edge into
the new material. The remover was told the removal happened; the forest
disagreed a day later, in silence. In a memory that is worse than a write
that fails: a failed write is retried, a resurrected one reintroduces
material somebody decided to withdraw. Beside it, a dataset whose payload
had gone missing took the whole `look` with it, so a node visible to
`scan` was unreadable through the primitive that reads passports and the
passport had nothing to do with the missing file.

The rest of this version is the backlog those rounds left open — six items
reported against v0.59 and still open in v0.60, which is the first time in
the series the report-today-shipped-tomorrow cycle broke. Three of them
turned out not to be what they looked like, and that is stated here rather
than buried: `origin` on an upload was working as specified and undocumented
(J.8 rule: an upload's origin is the `source_url` it declares, and nothing
taught anyone to declare it); `supersedes` was in the engine's default
dialect since v0.58 and absent from the deployed forests' own
`_meta/schema.md`, which is A.2 working as designed with a refusal that
failed to say so; and of the five reads said to ignore the waymark, four
already honoured it and `pick` did not.

- **An upload is a courier, not a mirror (new J.8.3, amends J.9).** The
  bug reported was a `prune` that undid itself on somebody else's next
  upload. Underneath it sat an assumption nobody had written down: that the
  upload staging area is a source tree this forest *mirrors*. From that one
  assumption came all of it — `adopt` recorded the staging path as the
  forest's `source_root`, so **one upload repointed a forest that really
  did mirror a folder** and the operator's Sync then described the courier;
  the refresh walked the whole directory, so a file whose node had been
  pruned was read as a new document and planted again; the report said
  `sync` to a caller that had said `upload`; and nothing could ever be
  removed from the area, so it accumulated where nobody could see it.
  Uploaded bytes are now what they always were: how a document reaches a
  Station, scoped to the entries of that request, recording nothing,
  removed as they become nodes (`consumed`), kept when they fail, never
  backing a `reference` body, and — for what legitimately remains —
  countable and clearable through **J.13.7** instead of a shell.
- **A missing payload is a fact about the payload (new C.2.2).** `look`
  built a dataset's `query_manual` and `sample_rows` by opening the `.db`,
  and an absent file raised `E_NOT_FOUND` for the entire digest. The
  passport title, summary, tags, edges, notes never depended on that
  file. The digest now degrades: the passport is returned, the two
  payload-derived fields are omitted, and `payload_missing: true` says
  which. `coverage` counts the same condition per root, so an operator
  reads the damage in one call instead of discovering it one
  `E_NOT_FOUND` at a time.
- **A branch is addressed by its id (amends G.3/J.8).** `dest` was the
  one place in the whole surface where a branch may **not** be named the
  way every other place names it: `scan("tasks/_index")`, `parent:
  "notes/_index"`, `coverage`'s roots all take the canonical form, and
  `dest: "notes/_index"` produced `notes/_index/_index` and a refusal
  whose "expected parent" was the exact string the caller had sent. The
  advice was to do what had just been done. `dest` now accepts both
  forms, and the skill teaches the canonical one.
- **Every read by id answers the waymark (amends C.15 rule 4).** Stated
  in v0.58, implemented in `look`, `move`, `history`, `view` and `query`,
  and missing from `pick` the read an agent holding a written-down id
  actually makes. Half a redirect is not a redirect.
- **A derived alias is a name, not a leading digit (amends G.2.6).** The
  number a file's stem starts with is derived as an alias, and the test
  for "starts with digits" did not require the digits to END. A document
  named `9router-free-ai-router.md` derived the alias `9`, which enters
  the one index searched by metadata alone and ranks. The number must be
  a whole leading segment, followed by a separator or by nothing.
- **An unknown token names the set that would be accepted (amends
  A.2/C.7/C.8).** A forest's dialect is its own file and a rel the engine
  ships may be absent from it that is A.2 working. What is not working
  is `E_SCHEMA: unknown rel 'supersedes'` with no `hint`, in the exact
  case where naming the forest's declared rels answers the question
  completely. C.12's envelope says every refusal carries an actionable
  hint; this one did not.
- **What ingest derives can be re-derived (new J.13.6, amends G.2.6
  rule 4).** Aliases derive from the source path and the title, both
  recorded in the passport so the repair for a forest ingested before
  a derivation rule existed needs no source tree, no converter and no
  model. It was nevertheless reachable only through `sync`, which needs
  the recorded host root and `admin` over it. A maintenance pass now
  re-derives from the forest's own passports and reports what changed;
  a forest of 1,877 nodes stops being a forest where the delivered
  feature is absent in practice.
- **The floor says which half refused (amends J.10.10).** `min_evidence`
  counts items that clear `min_score`, so with a threshold that means
  anything the pair `(2, 0.02)` refuses questions the forest answers
  well and the refusal reported `evidence_count: 1` without saying that
  two further items were dropped by the threshold. `below_min_score`
  names them, and the skill states the pairing that works.
- **The skill names its forest, its origin and its useful floor (amends
  J.5.12).** One skill per forest collided on `name:`; the saving block
  taught the `dest` form the server refuses and never mentioned
  `source_url`, the only way an uploaded document gets an `origin`.
- Acceptance: **F.117 – F.128**.

**Changelog v0.59 → v0.60 the skill fits the agent.**

Every version that touched the Skills console made the file it hands out
better and bigger. v0.49 gave a person a skill instead of asking them to
write one; v0.56 taught it to state its age; v0.57 taught the anatomy of
a node because a first-session agent would otherwise plant nodes nobody
could find; v0.58 added the document's past; v0.59 added `coverage` and
`min_score` — 471 tokens in one release, to a file that had reached
3,921.

None of those were wrong, and the sum is: an agent that fires this skill
pays for all of it, once per session, forever. A key paired with J.2.6's
default `{read, ingest}` carries about 1,400 tokens of `plant` anatomy it
is not allowed to execute, and an agent asked only to read pays for the
whole write surface. The product spent five versions teaching the model
to ask narrower and never applied the lesson to its own instructions.

The second half is smaller and worse. Every primitive here takes
`forest` as its first argument. The generated skill contained twenty-three
call examples and **not one of them passed it**: the forest's id lived in
the title, in the `description` and in no call the model was ever shown.
The console that exists so documentation cannot drift from its
deployment was teaching a call shape the deployment does not have.

- **A skill is a folder (amends J.5.12).** `SKILL.md` carries what every
  agent needs; `references/{saving,writing,time,datasets,sharing}.md`
  carry what only some do, each named in the core with the condition that
  sends an agent to read it. A reference that is not read costs nothing,
  which is the whole point: the runtime holds only the `description` in
  context and loads the body on trigger, so the number to shrink is what
  a firing costs. The core alone is a complete skill and never a teaser;
  no instruction exists in two blocks; and several *installed* skills is
  explicitly not the split — each would cost its `description` in every
  session, and the runtime rather than the core would decide which one
  loads, which a model about to make its first write cannot know in
  advance.
- **The key chooses the blocks (amends J.5.12).** The default selection
  is the capabilities of the key on the selected forests — the console
  already renders under that grant. A block may be included deliberately
  for a capability the key lacks (a skill prepared for a colleague), and
  then it names the capability it requires in its first line, which is
  v0.49's conditional-teaching correction kept honest rather than
  discarded. The same selection can be assembled as one inlined file for
  runtimes that take no folder, and the two assemblies teach the same
  surface.
- **An example is a call (amends J.5.12).** Every example in every
  generated file carries the forest argument in the shape the tool takes.
- **The skill is for the forests it names (amends J.5.12).** The console
  offers the forests the key reaches, the open one pre-selected, so an
  agent configured for two forests is handed one skill. A baked id is
  intent, never authority: `forests()` is taught as the first call
  because capabilities, roots, `locked` and `station` are only true at
  the moment of use, and a forest whose grant has lapsed answers
  `E_NOT_FOUND` like anything else outside a key — the ordinary shape of
  a narrowed key, not a defect to work around. More than one forest
  carries a routing table (id, largest roots, capabilities held at
  generation) built from C.17 `coverage`, because a model given several
  forests and no map either sweeps them all or picks one in silence. One
  forest carries no table: there `coverage()` is a single live call, and
  a written-down copy of a forest's shape can only drift from it.
- **The address is the way back (amends J.5.12/J.5.8).** Blocks, forests and
  assembly ride the query, so the generated file can name the one link that
  rebuilds itself against a newer Station — the repair for the staleness the
  v0.56 stamp only detects. Installing stays the operator's act: a skill
  outlives the connection that delivered it, which is exactly what a tool
  description does not, so the Station gains neither an endpoint nor a
  `skill()` tool for it.
- Acceptance: **F.111 – F.116**.

**Changelog v0.58 → v0.59 the forest says what it holds.**

Every read in this product says what it did not do. `locate` returning
nothing reports `searched` and names `sniff`; `look` names the field it
clipped; `scan` returns `total` beside `returned`; the sweep counts what
it suppressed. The discipline is mature and it is the reason the tool can
be trusted by something that is not reading carefully.

It had never reached the outermost layer. A consumer agent asked this
forest for a mandatory rule, got a faithful answer citing a real
document, and the answer was wrong about the thing it was asked — not
because retrieval failed, but because the branch holding the rule had
never been ingested, and **nothing on the surface could say so**. The
partial answer arrives in the exact shape of the trustworthy one: with a
citation, with a source, with a trace. That is the most expensive silence
a memory can keep, and it is the last one left.

v0.59 closes it, and pays a debt the load measurements made undeniable
along the way.

- **A forest can say what it holds (new C.17 `coverage`).** One cheap
  call, answered from the catalog alone with no file opened and every
  count grouped in SQLite: the roots the caller may start from, how many
  nodes sit under each, where that material came from (`origin` as the
  exact prefix `scan` takes) and how much of it carries no origin at all,
  the dates it spans, and the totals by type and by source. Scoped like
  every read — under a policy the roots are the principal's own roots and
  every count is filtered by the policy's own prefixes as SQL (C.13.3's
  rule, for the same reason: a global count here is a finer size oracle
  than `locate` could ever be). It states what is present and never
  guesses what is absent; seeing that a root is not there is the caller's
  conclusion to draw, and the point is that they can now draw it in one
  call instead of needing the source tree on disk.
- **The document's own name resolves (amends G.2.6).** Alias derivation
  required the operator to declare a folder→prefix map, and without one
  ingest wrote no aliases at all — so in a forest where every document
  has a canonical code, 1,877 of 1,877 nodes lacked the name they are
  called by, and the most common access in the forest fell through to the
  path that measured **~100× slower**. Ingest now derives from what the
  source already states about itself: a code in the shape `LETTERS-DIGITS`
  present in the title or the H1, the leading number of the file's stem,
  the path form, and — when the containing folder's name is itself
  compound — its initials as a prefix. None of that is content vocabulary
  entering the engine: the engine invents no words, it reads back the ones
  the document and the path already carry. The `aliases:` map keeps the
  job only an operator can do — declaring a convention the material does
  not state — and a hand-written alias still outranks every derived one.
- **What came from a tree is listable (amends C.6).** `scan` gains the
  filter key `origin_prefix`, matching a prefix of the node's `origin`
  URI; the exact-match `origin` key stays, because "which node is this
  file?" and "what came from that directory?" are different questions.
  `coverage` publishes the prefix that `scan` takes, so there is no
  arithmetic between finding a source and listing it — the same
  contract C.13.3 gives windows.
- **A floor that counts evidence, not items (amends J.10.10).** The
  `min_evidence` floor counted retrieved items, and the sweep returns `k`
  items whatever their score, so the floor was reached almost always and
  the protection it advertises almost never fired: it guarded against an
  empty forest, not against weak evidence. `answer` gains `min_score`,
  applied before the count, and the refusal names both numbers. The
  specification states plainly what the score is — an RRF rank artifact,
  comparable within a deployment and not across corpora — so the lever is
  tuned rather than believed.
- **A citation carries its scope (amends J.10.4/J.10.5).** `sources[]`
  carried `id`, `title`, `summary`, `type` while the `harvest` beside it
  carried each item's `trail` — so the field designed to be read was the
  one that lost the material's place in the forest. In a multi-product
  forest, which is the normal case and not the exception, the trail is
  what makes "according to `findleads/back-end`…" visible at a glance.
  The data was already computed; it now crosses the last layer.
- **A rehearsal names every problem (amends C.7.3).** `dry_run` exists to
  turn trial-and-error into one call, and it validated in a chain — first
  problem, stop — so it stayed trial-and-error, merely cheap. A failing
  rehearsal now reports every problem it could determine, and a failing
  batch rehearsal reports them for **every** node rather than up to the
  first. The envelope's own code, message and hint are unchanged to the
  byte; the full list rides in its `data`.
- **The share link is one address with two representations (amends
  J.17).** `/s/<token>` was a console route, served only to a request that
  accepts HTML, so the first thing anybody does to debug a share — curl it
  — answered 404 while the browser worked. It now content-negotiates:
  a browser gets the reader page, everything else gets exactly what
  `GET /v1/share/{token}` serves, from the same handler, with the same
  authority re-read and the same byte-identical 404 for every dead state.
- **A remembered non-match is a count, not a row (amends C.6b.1).** The
  memoized scan removed the file I/O and left everything else: on a
  1,911-node forest a warm `sniff` carried a row out of SQLite for **every
  node in the forest**, deserialized and recombined each one, and only then
  discovered that ~95% of them matched nothing — after loading every
  catalog row too, and asking SQLite for heat **one node at a time**, and
  rendering snippet windows for thousands of lines of which at most fifteen
  are ever returned. Measured: 94 ms of a 103 ms sweep, and throughput that
  **falls** as concurrency rises, because the work is CPU-bound and the
  reader pool of J.6.2 cannot multiply what the GIL serializes. Four cost
  rules now bind the memo — the matching lines and the *uncovered* nodes
  are what a read asks for (everything else in scope is one count), the
  catalog rows loaded are the candidates', heat for them is one statement,
  and a snippet is rendered only for a result that is answered. A warm
  `sniff` for a term living in a handful of bodies went from 10.9 ms to
  **1.5 ms** on that forest; a term living in most of the corpus stays
  proportional to its matches, which is the honest floor and is stated as
  one. The answer is byte-identical to the direct scan throughout;
  C.6b.1's first rule was never in question and is not relaxed.
- Acceptance: **F.103 – F.110**.

**Changelog v0.57 → v0.58 the document has a past.**

v0.56 made the forest replace the file; v0.57 made it serve a hundred
readers. What remains is the knot every earlier changelog deferred by
name: a document that cannot move, does not remember, and arrives one at
a time. The pieces were always one design — moving a node needs a
waymark, a waymark needs history to stay honest, history needs an
author, and the author has been riding every write since J.4 stamped the
`station-principal:` trailer. This version unties the knot, and closes
the one regression v0.57 would otherwise have shipped: with the model
calls parallel, identical concurrent misses each paid for a generation
the first of them was already buying.

- **A node can move, and the old address says where (new C.15
  `transplant`).** The consumer team's words: "se eu errar a branch de
  um documento, refazer é a única saída" — misplacement was permanent.
  `transplant(id, new_id)` moves ONE leaf node: passport rewritten under
  the new id in the same commit that removes the old file (git's rename
  detection keeps `--follow` history whole), every backlink rewritten to
  the new address (prune-force's discipline: refused when an anchor lies
  outside the caller's scope), both parent indexes and coverages
  refreshed, a local payload moved beside it. The old id becomes a
  **waymark**: recorded as `moved_from` on the new passport (files are
  the truth — a reindex rebuilds the redirect map from them) and joined
  to `aliases`, so `locate` still finds the old name; a read of the
  exact old id answers **`E_MOVED`** naming `moved_to` — unless the new
  address lies outside the reader's scope, in which case the answer is
  the byte-identical `E_NOT_FOUND` of a node that never existed (a
  waymark must not be a periscope). Branches do not transplant (move
  the leaves, one audited decision at a time — C.14's rule); root and
  `_meta/` never; `graft`'s `set_parent` stays refused (an address is
  not a field).
- **A document remembers who did what, and when (new C.16 `history`).**
  Every write was already a commit and the acting principal already rode
  it (J.4, v0.57); nothing could read them back — the team accumulated
  ten commits in one session and called git better at this than the
  product. `history(id)` lists the node's commits, newest first, through
  renames (`--follow`): full **timestamp** (day-precision frontmatter
  finally has an intraday answer — D-01b closes here), the `action` (the
  commit subject's own prefix: plant, graft, tend, transplant, gardener,
  ranger…), and `by` — the attribution trailer's value when the commit
  carries one. Read-capability, scoped like every read, budgeted like
  every read.
- **A batch is one plant (new C.7.4).** The team planted eight documents
  in eight calls; two died mid-batch and left a graph half-built that
  only `if_absent` retries could heal. `plant` now accepts a **list** (≤
  20): every node validated BEFORE anything is written — in order, so a
  branch and its children may share one batch — and the whole batch
  lands in **one commit** or none of it lands (`E_SCHEMA` names the
  failing node). One commit is also one writer-lane occupation, which is
  the write ceiling the load report measured, attacked from the other
  flank. `if_absent` and `dry_run` compose with the list.
- **A replacement suppresses what it replaced (amends A.2, new
  C.6c.4).** The dialect gains `supersedes`/`superseded-by` — distinct
  from `succeeds`, which orders moments without judging them. The sweep
  now EXCLUDES a result that a live node supersedes, refills the seat,
  and **counts what it hid** (`superseded_excluded` names id and
  successor — nothing is silent); `include_superseded: true` restores
  the history view. Navigation (`locate`, `sniff`, `move`, `scan`) shows
  the forest as it is: suppression is a retrieval-for-answering rule,
  never a map rule. Existing forests opt in by declaring the rel in
  their own `_meta/schema` (A.2's rule since Phase 0).
- **The Gardener records where it came from (new G.2.7).** v0.57 gave
  the passport `origin` and only agents wrote it. Ingest now fills it:
  the source file's URI on adopt and refresh, the upload's `source_url`
  when one was declared (J.8) — and **only when absent**, because an
  operator's hand-written origin outranks a derived one (G.2.6's union
  rule, applied to one scalar). Staged uploads without a URL get none: a
  path inside `_derived/` is a fact about plumbing.
- **Identical questions in flight share one generation (amends
  J.10.7).** v0.57 made misses parallel, which un-made an accident of
  the old serialisation: queued identical misses used to hit the store
  the leader had just filled. Now deliberately: concurrent sweep misses
  with the same store key **coalesce** — followers await the leader,
  then re-consult the store under their own reading fingerprint. A
  follower whose reading matches is served the stored reply
  (`cached: true`, the plain truth); one whose reading differs runs its
  own model call, exactly as J.10.7 always ruled. `cache: false` opts
  out of coalescing along with everything else.
- `transplant` joins the J.16 events (`node.transplanted`, identity
  only), the signature table, both MCP surfaces (20 tools; the J.1.2
  parity test counts them) and the skill.
- Deferred, named: branch transplant (move the leaves first),
  reading a document *at* a historical commit (history lists; Part I
  restores), `P-04` queue position (awaiting the load re-test's
  numbers), and `sniff`'s scaling (same).
- Acceptance: **F.95 – F.102**.

**Changelog v0.56 → v0.57 the forest serves a hundred readers.**

Two sources, one version. The first is an incident: the first production
deployment under real agent load locked up — not when a model answered,
but when an agent **planted**. The host serialises every touch of a forest
on one thread (J.9), so a write's git ceremony (measured at 69× a
`locate`, before container filesystems multiply it) and the Gardener's
curation model call each held that thread while every read of the forest
queued behind them. C.9 has promised "one writer, N readers: reads never
block" since Phase 0 — the engine honours it (WAL), the host did not. The
second source is the consumer team's seventh report, the first written
after they stopped testing the product and started **using** it as memory
— eight real documents, planted, linked and consulted — which surfaced
the failures only real use can: a digest that drops its edges in silence,
an answer that mixes rounds of the truth, and a write surface whose shape
is documented nowhere an agent looks.

- **Reads scale (new J.6.2; C.9 finally held by the host).** Each open
  forest gains a **reader pool**: K read-only engine instances, each
  confined to its own thread, serving every read primitive and the
  sweep's retrieval. Writes, ingest steps and admin repairs keep the
  single writer lane. Readers take no lock (C.9's lock is possession of
  the *write*), deposit pheromone exactly as any read does, and see every
  write that committed before their transaction began (WAL snapshot). A
  read never again waits for a plant, a batch, or a model call.
  `MONKEYLLM_STATION_READERS` sizes the pool (default 4; `0` restores the
  single lane). Concurrent pheromone writers make SQLite contention real,
  so the derived-layer tuning gains `busy_timeout` — a writer waits its
  turn instead of failing with "database is locked".
- **The provider is not a lane (new J.10.11).** The sweep `answer` held
  its forest thread through the model round trip — seconds during which
  a 0.2 ms read could not run. The consumer team's load report measured
  it precisely: cold-cache throughput pinned at 0.3 req/s at every
  concurrency, latency linear in the queue, and a cache hit the server
  served in 104 ms arriving in 6.6 s because it waited behind
  generations. It now runs in three phases: *prepare* on
  a reader lane (retrieval, floor, store consult — and the trace slice is
  captured there, so a concurrent call on the same lane cannot leak into
  this call's `trace`), the *model call* on no lane at all, *settle* back
  on the same reader lane (store deposit, whisper). Concurrent model
  calls are admitted under `MONKEYLLM_STATION_MODEL_CONCURRENCY`
  (default 8) — parallel because the lane hold is gone, bounded because
  the provider is metered — and `/v1/health` publishes
  `concurrency: {readers, model}`, so an agent can read the deployment's
  shape instead of discovering it by experiment. The walk (`hops`) and
  `recurate` stay lane-bound and say so: a walk interleaves reads with
  model turns by design, and it is opt-in per call.
- **The batch owns the writer lane, and only that (J.9 note).** The
  Gardener's curation call runs inside an ingest step, on the writer
  lane. With J.6.2 that is now the correct cost: during a batch, *writes*
  queue behind the current document — reads and answers flow on the
  reader pool. Splitting the curation call out of the step is deliberately
  NOT done: G.10.1 stands (a step is a whole document), and the reader
  pool removes the only starvation that was observed.
- **The principal is stamped, never amended (amends J.4).** The host
  attributed writes by amending the engine's commit — every write paid
  for two commits and a log read. The engine now accepts **commit
  trailers** for the host to set (`Vine.commit_trailers`, a J.0-style
  public seam like `embedder`): the trailer rides the original commit.
  The amend path remains only as fallback for engines older than the
  host.
- **The repo is tended too (new H.8).** Forest git repos accumulate loose
  objects at one-commit-per-write; on overlay filesystems every git
  operation slows with them. The Ranger's `run()` now finishes with
  `git gc --auto` — git's own thresholds decide, the Ranger only asks;
  reported in the run's report, never a commit.
- **`look` never drops a field in silence (amends C.2).** Found by the
  team in real use, and the response contradicted itself: `edges_out: []`
  beside `stats.degree: 2`. The budget shrink took the edges — the small,
  structural field — while a 28-item `outline` (the big, re-derivable
  one) stayed. In a product whose philosophy is "a read says what it did
  not do", this was the one silent omission left in the hot path. Now:
  the budget clips in declared order — `outline` first (big, and
  re-derivable through `pick`), then `children`, then
  `edges_in`/`edges_out`, a dataset's `sample_rows` last — and **every
  field the budget touched is named in `truncated_fields`**.
- **The answer knows what time it is (amends C.6c, J.10.7).** Asked
  "what is still open?", the hosted answer merged a two-rounds-old report
  with the current one and reported as open what the newer document says
  was fixed — while the `succeeds` edges stating the order sat unused in
  the graph. A memory that treats every version of the truth as the same
  present gets *less* reliable as it grows. Three changes, none of them a
  new model call: every sweep item now carries `created`/`updated`
  (read off the catalog row already in hand); equal-relevance fusion
  breaks ties toward the more recently updated node; and when one
  selected item `succeeds` another, both are annotated
  (`supersedes`/`superseded_by`) so the model — instructed by the host's
  prompt — reads the older one as history, not as the present. The
  annotations and dates join the J.10.7 reading fingerprint: material
  re-dated is material re-read.
- **A write rehearsed (new C.7.3).** Two of the team's eight plants died
  on a 61-token summary — after 33 KB of body crossed the network.
  `plant(node, dry_run=true)` runs every validation the real plant runs
  — id/parent chain, declared types and rels, summary ceiling, alias
  bounds, dataset schema — writes nothing, commits nothing, and answers
  `{valid: true, id}` or the exact error the real call would raise.
- **A document says where it came from (amends A.3, C.2, C.6).** The
  team stored documents that exist as files in a repository and had no
  field to say so. Optional frontmatter `origin`: one free-form URI
  (path, URL, commit — ≤ 2048 chars, no whitespace/control characters),
  mutable, returned by `look` whenever present, filterable in `scan`.
  The engine never dereferences it; it is provenance for reconciliation,
  not a fetch instruction.
- **A section answers by name (amends C.4.1).** `pick(section=[...])`
  items each carry `header` — the header line that actually matched —
  because prefix matching means the section served is not always the
  string asked, and a list result identified only by order is a result
  the caller re-derives.
- **The subtree export exists, and the flag is never swallowed (amends
  J.14.1).** `export?recursive=true` was accepted with `200` and
  ignored — the exact defect C.8 just fixed for `graft`, on the route
  beside it. `recursive=true` on a branch now returns a **zip** of the
  subtree (every in-scope node, each member the byte-identical single
  export, named by node id); an unknown query parameter on this route is
  `E_SCHEMA`, never silence.
- **The skill teaches writing (amends J.5.12).** The team planted
  well-formed nodes only because they had read the source in earlier
  rounds; the skill documents reading thoroughly and writing almost not
  at all — and the `plant` tool's `node` parameter had an empty
  description. The generated skill gains the **anatomy of a node**: the
  node shape, `aliases` presented as the findability lever it is, the
  60-token summary ceiling, the id-determines-parent rule, reading
  `_meta/schema` before the first write in an unknown forest, `fields`
  as the paging lever in `look`/`scan` — and one footnote naming the
  REST surfaces an agent will want the moment it writes: `export` and
  share links (the team probed for A-01 by guessing URLs and filed as
  missing a feature v0.56 had shipped; a surface the skill does not name
  does not exist).
- Deferred, named: rename/move and per-node history (the v0.58 knot,
  unchanged), batch `plant` with atomicity (F-01), a `supersedes` rel
  that suppresses its predecessor from retrieval by default (N-02's
  fullest form — the annotation ships now, the suppression needs the
  history design), and Gardener auto-fill of `origin` at adopt.
- Acceptance: **F.87 – F.94**.

**Changelog v0.55 → v0.56 the forest replaces the file.**

The consumer team's sixth report opens with an inventory: six rounds of
testing produced six reports, and every one lives as a `.md` on a disk the
forest will never see. The storing half already held — a 19,420-character
report plants, round-trips byte-identical, outlines into 28 sections, and
every read finds it — so what keeps knowledge on the disk is the
**surroundings** of the document: hand it to a person, reread it whole,
take it back, and know who said it. As long as any of those four is
missing, the rational agent writes to the disk — where `rm`, `cat` and a
shareable path exist — and only promotes to the forest what is already
finished, which is exactly the habit the product exists to end. This
version is the surroundings. Underneath the findings sat one more: half of
what the team asked for already existed, and the skill they navigated by
was too old to say so — a stale skill is a stale map of the product, and
nothing told them.

- **A document is read back whole, in pages (amends C.4).** `pick` on an
  over-budget body answered an empty body and a hint. The protection was
  right; the dead end was not: the team's reports are all above the
  ceiling, and rereading your own document in 28 `section=` calls is why
  the local copy survives. `pick` now pages — paragraph blocks, each page
  a byte-exact substring, an `after` cursor in `scan`'s idiom (`next`,
  `returned`, `total`) — and pages concatenated in order reproduce the
  body **to the byte**. A single block wider than the whole budget arrives
  alone and cut, flagged, with the cursor still advancing: progress is
  guaranteed, and so is the flag. `section` also accepts a list now:
  `pick` already batched ids, and refusing two sections of one document in
  one call while serving five documents was asymmetry, not protection.
- **An unknown patch key is refused, never absorbed (amends C.8).**
  `graft` with `{"regenerate_summary": true, "append_section": …}`
  answered `200` and silently dropped the key it did not know — the caller
  walks away believing the summary was regenerated. A patch key is a
  claim about what the write does; an unknown one is now `E_SCHEMA`,
  naming the key and listing the operations that exist (the same
  discipline v0.54 gave unknown REST parameters).
- **The passport says who and when (amends C.2).** `source`, `created`
  and `aliases` were in every passport and in the indexed catalog — the
  team probed for them and concluded the product could not answer "what
  did I write here?". `look` now returns them, and `scan` takes
  `source=` as a filter, which makes that question one enumeration.
- **The metaphor stays in the prose (amends C.1/C.6).** The team's first
  call of the session failed because documentation taught vocabulary the
  wire does not speak — and then the wire spoke `"kind": "banana"` back.
  Charm aimed at a human reader, in a field only machines read, is
  friction both ways. Every wire emission of `kind` now says
  `note`/`branch`; `locate`'s scope word is `notes` (`bananas` accepted,
  deprecated, for one minor version). Prose, docs and index headings keep
  the metaphor — it was always for people.
- **A write you can take back (new C.14 `prune`).** The team left three
  probe nodes as permanent garbage in a production forest, tagged
  `delete-me` because that was the most deletion the product offered.
  Their sentence stands: *an agent that cannot undo should not write
  alone* — and its consequence is agents writing to disk, where `rm`
  exists. `prune(id, force=false)` removes one node: passport removed
  through git (history keeps it — recovery is an operator act, Part I),
  parent index entry and coverage refreshed, catalog row gone, local
  payload moved to `_derived/graveyard/`. A node with `edges_in` is
  refused with **the list of what points at it** (`E_ANCHORED`) unless
  `force: true`, which also strips those backlinks in the same commit. A
  branch with children is never prunable — prune the children first; no
  recursive deletion exists. A pruned id is free again: ids are immutable
  while they exist.
- **The document is a human surface (new J.14.1, J.5.14, J.17).** The #1
  reason the team still writes `.md`: the only way to hand a forest
  document to a person was to rebuild it outside the forest. Three
  pieces, one per audience. `GET /v1/forests/{f}/export/{node}` returns
  the document as `text/markdown` — no token budget, it is a download,
  J.14's discipline verbatim (read cap, contained, byte-identical
  `E_NOT_FOUND`). The Studio **reading console** (`/f/{forest}/read`)
  renders a node for reading — full body via export, outline as a
  navigable sidebar, media through the viewer's own credential (J.10.9),
  copy and download of the raw markdown. And a **share link** (J.17)
  hands one document to somebody with no account: a share is a key with
  one room — one node, read-only, expiring, revocable, re-checked at
  every serve against its issuer's own current reach (J.16's lesson: a
  lapsed grant suspends what it issued).
- **The skill states its age (amends J.1.2, J.5.11).** The team operated
  a round without `scan` and filed a feature request for a thing that
  existed: their downloaded skill predated it, and nothing anywhere said
  so. The `forests()` reply — the first call every skill teaches — now
  carries `station: "<version>"`; the generated skill stamps the version
  it was built against and teaches the comparison: server newer than
  skill → tell the operator to re-download it from the Skills console.
  The server cannot push a skill; it can make staleness visible in the
  first reply of every session.
- **The alias map refresh follows the config (amends G.2.6).** `sync`'s
  fast-path skips unchanged sources, so adding an `aliases:` map to
  `gardener.yaml` changed nothing already ingested — a config edit was
  invisible exactly where it was aimed. The fast-path now still skips the
  conversion but recomputes derived aliases and refreshes the passport
  when they differ.
- `prune` joins the J.16 webhook events (identity only, like every
  event) and the MCP surface (17 tools; the J.1.2 parity test enforces
  the instructions naming it).
- Deferred, named: rename/move (`set_parent`) — an id is a path, so a
  move rewrites every edge, trail and cache key that names it; and
  per-node history with the writing principal as commit author — both
  need the author design first (next version's work, with C-01's
  graveyard as prior art).
- Acceptance: **F.79 – F.86**.

**Changelog v0.54 → v0.55 a lock is possession, not a file.**

The 0.54.0 upgrade killed the container the way every upgrade kills a
container, and the Station that came up could open nothing: two forests,
every primitive, both surfaces, `E_LOCKED` — while `/v1/health` said `ok`,
`writable: true`, and `forests()` listed both forests with full
capabilities. The consumer team's fifth report is one incident wearing two
findings, and both are contract defects, not operations mistakes.

- **The lock is held, never merely present (amends C.9).** `.vine.lock`
  used to be `O_EXCL`: the FILE was the lock, so a process that died
  without deleting it — which is how processes die — left the forest
  refusing every open forever, repaired only by shell access. Possession
  is now the kernel's advisory lock on the open file, which the OS
  releases when the holder exits, however it exits. The file's content
  becomes the holder's card — pid, host, since — for the refusal to
  quote; an orphan file (present, unheld) is reclaimed silently at the
  next open. `E_LOCKED` now means what it says: a live writer exists,
  named in the message. A filesystem that cannot hold the kernel lock
  keeps the v0.54 existence semantics, stated rather than guessed.
- **The lock is inspectable and an orphan is releasable over HTTP (new
  J.13.5).** `GET /v1/admin/locks?forest=` answers free / orphan / held
  (with the card); `POST /v1/admin/unlock {forest}` removes an orphan
  file and REFUSES a held one — an endpoint must not be able to break a
  live writer's lock, because two writers is the corruption C.9 exists
  to prevent. Audited under J.4.1. The old hint — "remove the file
  manually" — addressed a shell the caller of an API does not have; the
  Studio Health console now shows the lock card and offers the release,
  admin-gated, which is the button the incident asked for.
- **The door tells the truth about the rooms (new J.1.3, the team's
  S-20).** `/v1/health` carries `forests: {served, locked}` — counts,
  never ids: health is unauthenticated and forest ids are J.3's to
  disclose — and its `status` degrades to `"degraded"` when any forest
  is held by a foreign writer. `forests()` and `GET /v1/forests` mark
  each entry the key may see with `locked: true` when it cannot
  currently serve, so the first call the instructions prescribe stops
  sending agents into rooms that do not open. This is J.1.1's lesson
  applied one level down: v0.52 taught health to report the MCP door,
  and the next outage was behind the next door.
- **The instructions name every tool (amends J.1.2, the team's S-06).**
  The `instructions` served at `initialize` described 8 of 16 tools, and
  an agent that trusts them uses half the product — the team operated a
  whole round without `scan` while asking for exactly what `scan` does.
  Every tool the surface registers MUST be named in the instructions,
  and the two lists are compared mechanically in the suite (C.12's rule:
  two descriptions of one contract agree only where somebody compared
  them).
- Acceptance: **F.75 – F.78**.

**Changelog v0.53 → v0.54 the wire is for machines.**

A team that consumes this product entirely through MCP and REST — the
consumer is an LLM harness, never a person — measured four rounds against a
served Station and reported where the contract still assumes a human is
reading. Almost every finding is the same finding: a response that a person
would understand and a machine cannot act on. Indentation a model pays for
and never reads; an error flag that disagrees with the envelope; an invalid
enum answered with an empty list; a truncation nobody was told about; a
forest that cannot be enumerated by the surface that lists it. This version
closes those, and the rule they share is C.12's, extended to its last
consequences: **everything a response knows about itself, it says on the
wire.**

- **The block is for the model, so it is compact (new J.1.2).** Every MCP
  tool result's text block is serialized with no indentation and no
  formatting whitespace — measured waste was 15–30% of every read's budget.
  Same keys, same values, same order; a console that wants pretty JSON
  renders it client-side. The same rule sets `isError` whenever the result
  carries the C.12 envelope: the protocol's flag and the envelope are two
  spellings of one fact and MUST agree. The body of the refusal is
  unchanged — `{code, message, hint}` remains the contract.
- **An enum refuses what it does not accept (C.12 rule 7).**
  `move(direction=…)` takes `out | in | both` and answers `E_SCHEMA` — 
  naming the parameter, the value and the accepted set — for anything else;
  it MUST NOT answer an empty neighbour list, which is indistinguishable
  from an isolated node. `locate(scope=…)` and `scan(fields=…)` follow the
  same rule with their own sets. A parameter that silently falls back to a
  default turns a typo into a wrong answer with a clean conscience.
- **Size travels with every discovery (amends C.6, C.6b, C.6c).**
  `body_tokens` — already on `locate` results since v0.52 — now rides
  `sniff` results, `harvest` items and `scan`'s default fields, read off
  the catalog row the search already loaded. The cost of opening a node is
  known wherever a node is offered.
- **The forest is enumerable (amends C.6).** `scan` takes `after` — an id
  cursor: results in id order, strictly after the cursor, `toward`/
  `gauntlet` refused beside it because an enumeration has one order. Every
  `scan` response carries `total` (what the requested scope holds) and
  `returned`; a cursored page that left something behind carries `next`.
  `truncated: true` stops being a dead end — it now names the way to the
  rest. The 800-token budget and the ≤ 50 item cap are stated in the
  contract instead of discovered by binary search.
- **The demotion is visible (amends C.6b).** An index hit carries
  `demoted: true` beside its unadjusted `score`, so a client that fuses or
  re-sorts by score can preserve the order the contract promised. The score
  itself still never lies (v0.52 rule).
- **The system node says so (amends C.6).** A `scan` item under `_meta/`
  carries `system: true` — the one honest answer to "why does `scan` count
  one more child than `look`".
- **A write that outdates the scent says so (amends C.8).** `graft` that
  changed the body without touching `summary` returns
  `summary_stale: true`: the navigation layer is built on summaries, and
  v0.52 taught callers to trust `locate` — so the layer the caller trusts
  must not age silently. The repair was always one call —
  `set_frontmatter: {summary}` — and is now stated in the contract.
  `aliases` joins the mutable frontmatter set (≤ 16 entries, each a
  non-empty string ≤ 80 chars), so a curated name can be taught after the
  fact.
- **The team's own name for a document resolves (new G.2.6).** Every project
  has a vocabulary (`BE-291`) that is in no title and no body — it is in
  the tree structure plus a convention. The Gardener derives `aliases` from
  the operator's folder → prefix map in `gardener.yaml`; `locate` has
  indexed aliases at weight 3 since the column existed. Without the map,
  nothing is derived: the engine stays forest-agnostic, the convention is
  the operator's to declare.
- **An undescribed media node is counted (amends H.3).** The G.5.1 stub is
  the floor, not the goal: `health` lists `needs_description`, so "media
  nobody can find by content" is a number on a report instead of a
  discovery in production.
- **The provider's cut is reported (amends J.10.8).** The premise that "a
  provider's cut carries no flag" was wrong for the OpenAI-compatible
  surface this host speaks: `finish_reason` is right there, and is now
  read. A reply the provider cut carries `truncated: true` and its
  `finish_reason`; a truncated reply never enters the J.10.7 store (the
  guard existed and nothing ever armed it); the response echoes the
  effective `reply_tokens`, so a clamped request learns it was clamped.
- **A citation carries the title (amends J.10.9).** The prompt teaches
  `Title [id]`, because `[chatgpt--chatgpt-com-202608200332]` means nothing
  to the person reading the answer — the id stays, machine-resolvable, and
  the title makes it prose.
- **Coverage is data (amends C.1/C.2).** `locate` and `look` report a
  branch's coverage as `{notes, branches}` — counts, not the sentence
  "4 bananas, 0 sub-branches", which forced every consumer to parse prose
  and guess what a banana is. The metaphor keeps the index bodies and the
  docs; machine fields carry numbers.
- **The server states its version (amends J.1).** `serverInfo.version` is
  the installed package's version — an integrator debugging against a
  deployment must be able to ask which build answered, and a whole report
  cycle was once spent against a build nobody could identify. `/v1/health`
  carries the same `version`. MCP capabilities with nothing behind them
  (`resources`, `prompts`) are not announced: an advertised capability is
  a promise, and every client pays a round trip to discover an empty one.
- Acceptance: **F.68 – F.74**.

**Changelog v0.52 → v0.53 the forest can say something first.**

One section is new. Part J has been a pull surface since it existed: a
principal arrives, is scoped, and reads. Nothing in it can tell anybody
that something happened, so a forest cannot take part in the automation
built around it — the operator who wants a message when a contract lands,
a rebuild when the corpus changes, or a page when the answer model starts
refusing, has to ask again, and asking again is what this project's
economics are against.

**J.16 Webhooks** is the outbound half, and it is shaped by one fact:
a delivery leaves the Station's authority behind. Inside, a read is
scoped, budgeted and audited; once bytes are POSTed to a URL, whoever
holds that URL reads them, under no scope, and a grant revoked afterwards
reaches none of it. So the body of a webhook is an audit row with a
destination — what happened, to what, by whom, when — and never content.

- **The payload carries identity, never content (new J.16.1).** Ids,
  types, counts, states, job ids, commit shas, error codes, costs. Never
  a body, a snippet, a question, a reply, SQL, a dataset row or a
  dataset's `## Notes`. One per-webhook opt-in adds `title` and
  `summary` — the two fields `locate` already returns — and it never
  widens further and never causes a read: it states what the act already
  knew, so `plant` can carry a title and `graft` cannot.
- **A scope is a ceiling, not a filter (new J.16.2).** A webhook belongs
  to a forest, administered by that forest's admin, or to the deployment,
  managed by whoever governs the deployment under J.10.2's reach rule.
  A forest webhook cannot subscribe to a deployment event however its
  list is written. Authority is re-read at **delivery**, so a webhook
  whose owner's authority lapsed is suspended and says so, rather than
  continuing to fire on a grant that is gone.
- **A closed, served catalogue (new J.16.3).** Twenty-five events across
  content, ingest, answer, access, config and maintenance, named as
  contract tokens in English and returned by the API so no console
  hard-codes them. Only events the Station can actually emit are named;
  reads are deliberately absent, because a webhook per read would put an
  outbound request on the path of the tightest budget in the system.
- **The event never fails the act (new J.16.4).** Emission is
  non-blocking, never on a forest lane, and O(1) when nothing subscribes.
  One body across every attempt so a receiver deduplicates by `id`;
  bounded backed-off retries that stop; a bounded queue that counts what
  it drops; suspension after stated consecutive failure; a recorded,
  redeliverable attempt log. Signed HMAC-SHA256 over
  `<timestamp>.<body>`, destination validated exactly as a provider's
  (J.10.2), headers write-only, and the whole lifecycle audited under
  J.4.1 by id and destination host.
- **Webhooks is a console in Build (amends J.5.1).** The group becomes
  the three directions a forest moves in: what comes in, who reads it,
  what goes out.
- Acceptance: **F.65, F.66, F.67**.

**Changelog v0.51 → v0.52 a read says what it did not do.**

An agent read a served forest end to end and wrote down every place it had
to guess. Almost nothing it found was a wrong answer; nearly all of it was
an answer that did not say enough about itself.

`locate` returning `[]` is byte-identical whether the forest has nothing on
the subject or has eight paragraphs about it under a summary that never
mentions the word so the model that follows the documented order concludes
the forest does not know, and answers from its own memory. That is the one
failure this project exists to prevent, and it was reached by doing exactly
what the documentation says. A malformed argument came back as `500
Internal Server Error` with no code and no hint, which is indistinguishable
from a forest that broke, and the three reactions those two situations
demand are opposite ones. An auto-generated index outranked the note it
points at, because `heat` was the only term separating them. A technical
question lost `MCP`, `RAG` and `421` on the way in, because they are short.
And a `421` from the MCP mount named neither the host it refused, nor the
hosts it accepts, nor the variable that decides so a deployment whose
every health signal was green had its main surface dark, and the operator's
only clue was `Failed to connect`.

Everything below is that class of defect: **the system knew, and did not
say.** No primitive changes what it searches, no budget is loosened, and no
guard is weakened.

- **An empty read carries what it looked at (amended C.1).** `locate`
  returns `body_tokens` on every result the number `look` already
  reports, delivered at the one moment it changes a decision and takes
  `include: ["outline"]` for the section list, both read from the catalog
  row the search already loaded. When the result list is empty, and only
  then, it carries `searched` and a `hint` naming the search it did not
  perform. `harvest` says the same when both of its legs come back empty.
- **A batch is one call, so it has one budget (new C.11).** `look` and
  `pick` accept a list of ids. The saving is round trips, never tokens: the
  batch is sized by one budget, whole items drop from the tail, and every
  id the caller sent comes back accounted for in `nodes`, `missing` or
  `dropped`.
- **A pointer never outranks what it points at (amended C.6b).**
  `match_count` enters the score instead of only breaking its ties, and an
  index node ranks below every content node in the same result set. An
  index carries the summary of every child, so it matches nearly any term
  and accumulates heat by being the way through; its matches are evidence
  about a child.
- **Short is not the same as noise (amended C.6c).** Derived terms keep any
  token that looks like code (a digit, all caps, `-`/`_`/`.`/`/`) whatever
  its length, and order those first so the cap drops grammar before signal.
  The four-character floor stays for ordinary words.
- **Every exit is an envelope (new C.12).** One signature table, declared in
  the engine, checkable against the MCP tool schemas mechanically; argument
  shape is `E_SCHEMA` naming the parameter, what arrived and what was
  expected; `null` is a missing parameter, never the string `"None"`; the
  last resort is `E_INTERNAL` in the envelope shape rather than a bare 500;
  and a missing parameter is refused as one, never as a denial.
- **A write you can repeat (new C.7.2).** `plant(node, if_absent: true)`
  answers `created: false` for an id already taken, writing nothing and
  comparing nothing. The default is unchanged: a duplicate id is still a
  refusal, because silently overwriting a node is the one failure a
  knowledge base does not recover from.
- **The dark surface says so (new J.1.1).** The MCP mount's `421` wears the
  envelope and names the refused host and the variable that admits it; a
  Station serving MCP with no explicit allow-list warns at boot; and
  `/v1/health` reports `mcp.host_allowed` for **this request's own host**,
  so the curl that reaches the domain answers the question about the
  domain. The check itself is untouched, and the list is never disclosed.
- **Where the material sits in time (new C.13).** `locate`, `sniff`, `scan`
  and `harvest` take optional `since`/`until`/`date_field`, and `calendar`
  reports which periods hold anything, so a window is a choice rather than
  a guess. The window is decided from the catalog row before any body is
  opened, which makes it the cheapest filter in the system; it is never a
  default; a malformed bound is refused rather than ignored; and an empty
  windowed read says whether the WINDOW was the reason, which is a
  different mistake from a question that matched nothing.
- **The answer it should not give (new J.10.10).** `answer(question,
  min_evidence: n)` counts the sweep's material before the model call and,
  below the floor, returns `answer: null` with the retrieval attached. Off
  by default. A refusal decided before the provider is called is never
  billed and never stored.
- Acceptance: **F.56 - F.64**.

**Changelog v0.50 → v0.51 a page is what a page is, not what fits on the screen.**

One section moves. The Clipper's page capture (J.15) is the whole
scrollable document rather than the viewport that happened to be showing.

The reason is what a screenshot is *for* here. It is not a picture kept for
its own sake: it is read once, at ingest, by the G.5.1 describer, and what
that describer writes is the only thing `locate` and `sniff` will ever see
of it. A capture bounded by the window therefore does not merely lose the
bottom of the page it decides how much of that page is findable at all,
by where somebody's scroll bar happened to rest.

- **Capture offers the whole page and a dragged region (amended J.15).**
  The page capture scrolls the document to its end, shooting each viewport,
  and composes them into one image. Three constraints are normative because
  each of them is a way the naive loop misleads: the page is re-measured at
  every step (scrolling is what makes a lazily-loaded page grow, so its
  height before the first move is not its height); viewport-fixed elements
  are hidden after the first slice (they travel with the scroll and would
  otherwise be stamped down the length of the image, over the content they
  cover); and the person's scroll position is restored when it ends.
  The capture is **bounded** by an explicit slice count, and a page that
  does not advance ends the walk rather than repeating itself. The region
  picker is unchanged, and remains a crop of the visible view — it is a
  rectangle a person drew on what they were looking at.
- No other section changes. `upload` still receives one entry, the media
  node's body is still the server's to write, and the two-nodes shape of a
  page-plus-screenshot clip is what it was.
- Acceptance: **F.55**.

**Changelog v0.49 → v0.50 the boundaries the system describes are the ones it enforces.**

A consolidation release. No primitive gains a parameter an agent can
reach, no budget moves, no console gains a page. What changes is that
several boundaries this document already draws are now drawn by the
component that can actually hold them, and that a few of them are stated
here for the first time instead of being left to implementation.

Three ideas run through all of it. **Decisions belong to whoever resolves
the thing being decided** if a rule is about what a SQL statement
touches, SQLite decides it, because a second reader of the same text
agrees only where somebody thought to compare them. **Authority has to
match reach** configuration shared by every forest is answerable to
whoever answers for every forest, and a credential belongs to the address
it was stored against. **What cannot be checked at the door has to be
declared up front** the console's page is where untrusted text is
rendered, and the browser is the only party present when it loads.

- **The table allow-list is decided by the database (amended C.5, new
  C.5.3; amended C.10).** J.3 already required it to be checked "against
  the parsed statement"; C.5.3 now says how, and extends it to the write
  path, reads included a scope that governs one direction and not the
  other is not a scope. Schema-describing table-valued functions join the
  refusal list beside the keyword they do not share a spelling with, and a
  not-found hint under a scope names only permitted tables.
- **An authorizer refusal is the guard's, not SQLite's (amended C.5.2).**
  It keeps `E_QUERY_FORBIDDEN` / **403**, and it does not name what it
  stopped at.
- **Deployment-wide configuration answers to deployment-wide authority
  (amended J.3.2).** Reading the provider list stays open to any
  administrator; editing or testing one requires authority over every
  forest. Expressed as reach, not as the owner bit, so break-glass (J.2.1)
  and single-forest deployments are untouched. A stored provider
  credential does not follow a changed endpoint and is never sent to a
  caller-supplied destination, and a connection test validates where it is
  about to connect.
- **Governance leaves a trail (new J.4.1).** The mutations that decide who
  may read and write grants, keys, passwords, providers, bindings,
  forests, sign-in are recorded on the terms Part D already uses: the
  act, never the secret. Rows belonging to no forest are the owner's to
  read.
- **The console declares what its page may load (new J.5.13).** A
  content-security policy and the baseline response headers, served with
  every response. The exfiltration path this closes never reaches the
  Station, so no server-side check could be the control.
- **Efficiency, unchanged semantics:** a table scope is now enforced
  during statement preparation rather than by scanning text before it, and
  the snapshot restore path validates sidecar members before extracting
  rather than after writing them.
- **New deployment variables:** `MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE`
  (J.10.2) and a default for `MONKEYLLM_STATION_IMPORT_MAX_MB` (J.13.2).
- Acceptance: **F.54**.

**Changelog v0.48 → v0.49 the door names what it opens, and the first minute says what this is.**

Nothing below moves a primitive, a budget or a guard. This version is
about what a person *believes* after their first ten minutes: that the
Studio is the product, when it is a window into it. The product is a
knowledge forest that external agents feed and read through MCP; the
console exists so people can watch, govern and teach that brain. Three
presentation contracts make the point unmissable, and a companion
handbook writes it down.

- **The integration manual's door names its surfaces (amended J.5.1).**
  The console entry once labelled "Integrations" MUST be labelled
  **MCP / API / Integrations**. A menu is read by somebody deciding what
  the product *is*, and a vague noun at the bottom of the govern group
  reads as an appendix when the thing behind it is the entire point.
  The J.5.1 table now also names every console the Studio actually
  ships, which it had quietly outgrown.
- **The first minute is a contract (new J.5.11).** The console gains a
  one-time, client-side presentation shown after the first sign-in: what
  a forest is, that agents connect and feed it through MCP, where to
  start. Presentation only it MUST NOT spend a model call, MUST NOT
  write anything server-side, MUST NOT enter the address (J.5.8), and
  MUST NOT exist before identity does: J.2.4's setup window and J.5.6's
  gate are untouched.
- **A skill is handed, not hunted (new J.5.12).** A Skills console —
  self-service, `read`-gated, never admin-gated generates the
  instruction file an agent runtime (Claude Code and its kin) installs
  to use this Station as persistent memory: recall before answering,
  save what is learned, cite node ids. Generated client-side with this
  Station's own origin and the open forest baked in (Integrations' own
  copy-ready rule), delivered by copy or file download: the Station
  gains no endpoint, the skill teaches no write path the MCP surface
  does not already publish (J.15's rule for every client).
- **Companion, non-normative:** `docs/guide/` the operator handbook
  (install, first access, using, feeding, connecting an AI, managing),
  with screenshots, in the three console languages of J.5.3.
- Acceptance: **F.52, F.53**.

**Changelog v0.47 → v0.48 the browser is a source, and a key that narrows needs nobody's permission.**

A browser extension the Clipper (J.15) turns the page a person is
reading into an ingest source: the selection or the readable article as
markdown through `compose`, a screenshot as a `media` node through
`upload`. Everything it needs from the host is the three contracts this
version adds plus one static artifact, the shared build the Station
serves at `GET /clipper.zip` (J.15) so the console can offer the
extension to everyone who may pair. No primitive's semantics, budget or
guard moves.

- **Pairing (new J.2.6).** The Clipper must hold a credential, and both
  existing ones are wrong for it: a session is the principal's *whole*
  authority with a short life (it dies mid-week in a toolbar), and an
  admin-minted key makes an administrator the gatekeeper of every
  browser. `POST /v1/auth/pair` turns a password into a key that carries
  a **capability mask** effective authority is grants ∩ mask, `{read,
  ingest}` by default enforced wherever the requesting principal's
  authority is read, REST and MCP alike, the admin and owner bits
  included. It needs no admin gate because it can only narrow: the key
  reaches nothing the password could not already reach. A pair key MUST
  expire, and `login`/`pair` MUST be rate-limited they are reachable
  from every browser now, not only from the console.
- **An image is never `unsupported` (new G.5.1).** The Gardener gains a
  built-in stub converter: image and audio sources plant as `media`
  nodes the original as payload, a stub body naming what is known —
  instead of falling out of the report. A forest with a bound `vision`
  model (new J.10 role) turns that body into a real description through
  a host-injected converter, and a describer that fails falls back to
  the stub: a broken model never aborts ingest. The stub is what makes
  a screenshot land; the describer is what makes it findable.
- **An upload's staging is not a durable source (amended G.7, in
  G.5.1).** `archive: never` rightly keeps durable originals at the
  source but an uploaded source lives under `_derived/`, which is
  disposable by contract, so a node referencing it would outlive its
  own bytes. Media adopted from inside the forest's `_derived/` MUST be
  archived into `_assets/` regardless of the archive policy: the
  payload is the only copy there is.
- **Payload bytes get a read surface (new J.14).** `GET
  /v1/forests/{forest}/payload/{node}` serves the payload file of an
  in-scope node read capability, byte-identical `E_NOT_FOUND` for
  out-of-scope and absent alike, resolved path contained in the forest
  root, local payloads only. Until now a screenshot the Clipper
  ingested was a node whose image no console could show.
- **A multimodal client may view what it found (new C.6d; amended
  G.5, J.14).** G.5 named serving payload bytes over MCP as a possible
  future; it is now the `view` tool: the image payload of an in-scope
  `media` node, returned as MCP image content beside a small JSON
  header same resolution rules as J.14 (byte-identical `E_NOT_FOUND`,
  local-only, contained), images only, bounded at the describer's own
  6 MiB. The line J.14 drew is *sharpened*, not crossed: material the
  host assembles for a model still never carries bytes `view` is the
  caller's model fetching the image deliberately, into its own context,
  under its own budget, exactly as G.5 always intended a "multimodal
  client that wants full fidelity" to do.
- **The answer can show what it read (new J.10.9).** A media node's
  body is a describer's prose about pixels the reader cannot see. The
  answering model may now embed the image itself: a markdown image whose
  address is `media:<node id>`, allowed only for ids present in its
  material. The host neither fetches nor rewrites anything the console
  resolves the reference through J.14, where scope is enforced, so an
  invented id renders as its caption and nothing else. Evidence of type
  `media` is rendered with its image beside the prose, and exports carry
  what the reader saw.
- **The reply has a stated size (new J.10.8; amended J.10.7).**
  The only reply-length control was the binding's `max_tokens` per
  forest, operator-set, and silent: a model that overran it was cut
  mid-sentence. `answer` now accepts `reply_tokens` per call, clamped
  to [64, 4000]; the effective value caps the model call AND is stated
  in the prompt, so the model shapes the reply instead of being
  truncated by it. It joins the J.10.7 key a short answer and a long
  answer to one question are two entries and the console offers it as
  a slider kept as the person's own preference, client-side, never in
  the address.
- **The fingerprint reads everything the model reads (amended
  J.10.7).** v0.47 made a dataset's `notes` ride in every bundle;
  the reading fingerprint was still hashing the six original fields, so
  an operator editing the teaching did not invalidate the stored answer
  built without it a stale hit, exactly what the fingerprint exists to
  make impossible. The rule was always "the sweep fingerprints what it
  would hand the model"; the `notes` now enter the hash like any other
  handed field.
- Acceptance: **F.47, F.48, F.49, F.50, F.51**.

**Changelog v0.46 → v0.47 a wrong name is not a locked door, and a result is material like any other.**

A walk was run against a 141-column export and cost 168k input tokens,
37 seconds and 33× the sweep, to produce an answer whose *set* of rows was
right and whose *order* was invented. Every step of that is a defect this
version names, and none of them is the model being bad at SQL.

- **`query` gets a token budget (amended C.5).** It was the only read
  primitive without one: a row cap of 200 and no ceiling, so `SELECT *`
  on that table measured **86,929 tokens for 15 rows** and 429,397 for
  all 129. Every other read is bounded look 500, move 600,
  locate/scan/sniff 800, pick 4000, harvest 4000 because a primitive
  that can return unbounded text cannot be composed into anything. Rows
  drop from the tail with `truncated: true`; `columns` **survives whole**,
  because the names of the columns are exactly what a caller needs to ask
  again, narrower. The bound is not only a cost control: an agent learns
  to project from being told, in one hop, that it did not.
- **A name that is not there is not a forbidden operation (amended C.5,
  C.10; new `E_QUERY_INVALID`).** `no such table` came back as
  `E_QUERY_FORBIDDEN` the code for attempting a write so a typo was
  indistinguishable from a policy refusal, in the console and in the
  audit. Refusal is what the guard decides; invalidity is what SQLite
  decides. HTTP 400, not 403: the caller asked wrong, they were not
  denied.
- **A dataset's notes travel with the dataset, on every path (amended
  C.2.1, J.10.5).** v0.46 put them in `look` and in `harvest`. The walk
  enters through `locate`, and a model that goes straight to `query`
  never sees them which is what happened. The rule is now the general
  one: any material a host assembles for a model carries the notes of
  every dataset in it. Otherwise teaching the agent depends on the agent
  choosing to be taught.
- **A hop's refusal reports what it was (amended J.10.5).** The loop
  already feeds the whole error envelope back to the model; it kept only
  the code for the console. The reader saw `E_QUERY_FORBIDDEN` twice and
  could not tell that the engine had already answered both.
- **The manual states the width (amended G.2.3).** A wide table's manual
  says how many columns it has and that `SELECT *` will not fit. This is
  arithmetic, not curation: the Gardener still MUST NOT decide which
  columns matter that is meaning, and meaning is `## Notes`.
- Acceptance: **F.46**.

**Changelog v0.45 → v0.46 the map says what is there, a person says what it means.**

Everything about a dataset that this system knows, it inferred. The map
(G.2.3) reads structure and three rows; curation (G.4.6) reads the map.
Nothing anywhere carries the one thing that decides whether generated SQL
is *right*: that this column is USD and that one is BRL, that `status` is
a one-letter code, that direct imports are the null-`arrendatario` rows.
An agent without that writes a query that runs and answers wrongly, which
is the worst failure available to it indistinguishable from success.

- **`## Notes`, and `look` returns it (new C.2.1).** A dataset passport
  may carry a section the operator writes and nothing else touches. It
  comes back in the digest, bounded to 200 tokens and truncated out loud,
  because the path an agent takes to a dataset is `look` then `query` —
  a note reachable only through `pick` is a note nobody reads.
- **The console has a place to write it (amended J.5.10).** A **Notes**
  tab beside Rows, Structure and SQL, composing ONE `graft`. No second
  write path, no side store: the teaching is part of the node, versioned
  and attributed like its summary.
- **Source is coloured wherever it is typed, not only SQL (amended
  J.5.10).** The markdown body editor is the surface an operator falls
  back to whenever a body holds a table which every dataset's does so
  it was the plainest text in the console at exactly the moment structure
  mattered most.
- Acceptance: **F.45**.

**Changelog v0.44 → v0.45 the map is the scent, and the wait has a name.**

v0.44 put a bounded map of every dataset into its body and then did not
read it. The Curator skips `type: dataset` by an older rule datasets had
nothing but a column list to summarise, so a factual template was the
honest answer and the consequence is a 10,000-row dataset whose scent is
still *"Adopted from source; pending curation"*, which is the text an agent
weighs when deciding whether this dataset can answer the question. The map
fixed the input; this reads it.

Two reporting failures travel with it. A batch that legitimately needed no
model all datasets, or all `unchanged` produced zero LLM summaries with
a model bound, and the console has no state for that, so it accused the
model of answering and being rejected **zero times**. And a batch of one
document is one G.10 step, so the progress bar stands at 0 until it is 1:
the operator watching a large file is watching something indistinguishable
from a hang.

- **The dataset's scent comes from its map (new G.4.6).** The Curator
  curates a dataset from the G.2.3 map structure and three rows per
  table and never from the payload or the source. Bounded by
  construction: a 5 MB CSV and a 5 GB database cost the model the same few
  hundred tokens. The G.4.1 template stays the fallback, so ingest still
  never blocks on a model.
- **A stage is reported, never yielded (new G.10.1).** G.10's step
  boundary is untouched a document is still one step, and nothing
  suspends mid-document, which is exactly what v0.32 refused. What is new
  is that the Gardener *names the phase it is in* through an observer, and
  J.9's job record carries it beside `current`. Naming a phase suspends
  nothing; that was never the objection.
- **A count limit is a guard against invention, not a verdict on data
  (new G.2.5).** C.7.1's ≤10 tables and ≤50 columns exist so a model
  cannot declare nonsense DDL. They were also refusing a 141-column ERP
  export the operator already owns the tool telling somebody their
  spreadsheet is wrong. Adoption by the Gardener is exempt from the two
  counts and from nothing else. The bound that actually matters moved to
  where the cost is: the G.2.3 map now caps sampled **columns** too.
- **A workbook's declared extent is not evidence (amended G.2.4).**
  openpyxl in read-only mode trusts the file's `<dimension>` record, and
  files written by anything other than Excel routinely declare `A1:A1`.
  A real 130-row sheet arrived as one row and was reported as a workbook
  with no data. The extent is now inferred from the rows that are there.
- **The report distinguishes "rejected" from "nothing to do" (amended
  J.8).** Curation stats gain `skipped`. Bound, zero calls, zero retries
  and something skipped is a batch that needed no model and the fix for
  that is nothing, while the fix for a rejection is a different model,
  prompt or budget. A console that shows one as the other sends the
  operator to tune a model that was never asked anything.
- Acceptance: **F.44**.

**Changelog v0.43 → v0.44 a database is a source, and a table is a map.**

A `.db` is the one file format this project already speaks natively and
the only one the Gardener could not ingest. Worse, the tabular converters
it *did* have produced datasets an agent cannot navigate: the passport's
body carried a column list and nothing else, so `sniff` which searches
bodies and only bodies (C.6b) could tell you a table has a `status`
column and never that the values in it are `open` and `closed`. The map
described the container and left out the contents.

- **A SQLite file is adopted, not rebuilt (new G.2.2).** `.db`/`.sqlite`/
  `.sqlite3` convert to a **payload** conversion: the file IS the dataset's
  payload, copied into place beside its passport. Reading every row into
  memory to re-`INSERT` it through C.7.1 would be unbounded in the source's
  size and lossy in its types, and the destination of that round trip is
  byte-for-byte what the source already was.
- **Every dataset passport carries a sample map (new G.2.3).** The body
  gets `## Query manual` as today followed by `## Sample rows`: per
  table, the columns with their types and the **first 3 rows**, rendered as
  a pipe table. Bounded by construction (3 rows, cells clipped, a stated
  table cap), deterministic, no model involved. This is the surface `sniff`
  reads, and it is what makes a dataset findable by what is *in* it.
- **A workbook is multi-table (new G.2.4).** `.xlsx` (openpyxl) and the new
  `.xls` (xlrd, BSD) convert **every** sheet to a table, not the first one
  silently. Over the C.7.1 table limit the file is refused by name.
- **The map follows the data (amended G.3).** A `sync` that rebuilds a
  dataset payload rewrites the two map sections and leaves every other
  section of the body alone a stale sample is a lie with a commit behind
  it.
- **C.7.1 rule 4 amended**: the auto manual includes the sample map when
  the node is born with `rows`.
- **J.5.10 (new)**: the Data console gains the three things a database
  client is expected to have datasets **born** through one `plant`,
  files **imported** through the J.8 upload surface (never a second write
  path), and a connection that can be **left**. Its SQL editor is coloured
  like every other source surface in the console.
- Acceptance: **F.43**.

**Changelog v0.42 → v0.43 the whole note in one commit.**

The Explore console's editor works at the section's grain because that
was the only grain C.8 offered: `replace_section`, one commit each. For
a person, the note is the unit of thought an edit that touches three
sections is one edit, and asking for three commits invites the
half-applied note the section grain was meant to prevent. C.8 gains one
operation and two refusals:

- **`replace_body: string`** replaces the entire body, atomically, in
  the same one-commit transaction as the rest of the patch. Combinable
  with `set_frontmatter` and the link operations; the empty string is a
  valid body (clearing a note is an edit, not an error).
- **Not combinable with the section operations.** A patch carrying
  `replace_body` alongside `replace_section` or `append_section` states
  two truths about one body refused as `E_SCHEMA`, never resolved by
  precedence.
- **Index bodies are the engine's.** A branch index's body is rendered
  by the indexer and parsed by contract headings; `replace_body` on an
  index node is refused (`E_SCHEMA`). Section surgery on indexes stays
  exactly as it was.
- **The write validates before it commits**: the serialized node must
  re-parse, so a body that would poison the next read is refused while
  the file on disk is still the old one.
- **J.5.4 (editing)**: a console MAY offer whole-note editing through
  `replace_body`, and MUST NOT compose one from a truncated `pick` —
  a body over the pick budget is edited at the section grain, because
  writing back less than was read is how notes lose their tails.

**Changelog v0.41 → v0.42 nobody's question pays for somebody's ingest.**

`locate` carries a 100 ms p95 budget (F.6) and, with the dense layer on,
two unbounded network operations. One is by contract the query must be
embedded (K.2). The other is not: **lazy re-embedding ran inside the read
path**, so every node an ingest marked stale was embedded by whichever
question happened to arrive next. Ingest two hundred documents and the
next person to ask anything pays for two hundred embeddings, inside a
primitive whose entire budget is a tenth of a second. Measured on a live
forest: one `locate`, 2.67 seconds. The vector scan was never the cost —
a dot product over dim-1024 vectors is 0.044 ms each, so the whole
wide-forest index searches in 11 ms.

- **The read path never embeds a node (amended K.2, C.6).** `locate` and
  the Gauntlet's goal embed **the query** and nothing else. Refreshing
  the dense layer is maintenance, and this specification already has a
  shape for maintenance the operator triggers and the console shows
  (J.13.3). A node planted a second ago is found by BM25 immediately —
  the catalog upsert is synchronous so the layer's debt costs recall
  in the dense half, never findability.
- **The debt is visible (amended K.4).** `canopy_status` gains `stale`:
  how many nodes are waiting to be embedded. It is the number that
  predicts what a refresh will cost, and an operator who cannot see it
  cannot choose when to pay it.
- **Refresh is an explicit act (new J.13.4).** `POST /v1/admin/canopy`
  accepts `{refresh: true}`: embed the stale ones, leave the rest. It is
  the cheap sibling of a full build, and it is offered beside the
  catalog rebuild in the console's Optimize tab content, index, dense
  layer, one errand told three times.
- **Embedding one text is memoized (new K.6).** `embed(model, text)` is
  a pure function, so the query half is cacheable exactly as the literal
  scan is (C.6b.1): `_derived/`, keyed by model and normalized text,
  disposable, bounded. A forest that is asked the same question twice
  stops paying the round trip twice.
- Acceptance: **F.42**.

**Changelog v0.40 → v0.41 the repair is on the console.**

`reindex` is the repair the whole derived layer is designed around: the
files are the truth, `_derived/` is disposable, and every divergence
anywhere in this document ends with "the files win and the catalog
rebuilds". The console says so out loud Files prints *"no entry yet,
reindex to rebuild it"* and then offers no way to do it. A hosted
operator has a browser, not a shell (the premise J.13 already states and
J.13.2 acted on), so the one instruction the console gives most often
was the one thing it could not carry out. v0.40 sharpened the point: a
forest imported over J.13.2, or one written by an earlier version,
carries no `body_hash` and pays the direct scan on every ask until
somebody opens a terminal.

- **Rebuild (new J.13.3).** `POST /v1/admin/reindex` rebuilds one
  forest's catalog from its files and answers with the node count. It
  writes only `_derived/`: no commit, no model call, no pheromone so
  it is offered even by a read-only Station, which would otherwise have
  a permanently degraded index and no way back.
- **It is offered where the operator already goes to keep a forest
  current.** The ingest console's refresh tab becomes **Optimize**: keep
  the content fresh (`sync`, Part G) and keep the indexes fast
  (`reindex`, C.6.1) are the same errand told twice, and splitting them
  across two consoles teaches nobody which one they needed.
- Acceptance: **F.41**.

**Changelog v0.39 → v0.40 the scan remembers what it read.**

`sniff` was specified as a direct file scan on every call, and the
implementation was faithful: one `open`+`read`+`close` per node, per
call, forever. Measured on a 246-node forest, two thirds of a global
sniff is the operating system opening files while `locate`, which
lives in SQLite, answers the same query in half a millisecond. The cost
is linear in the size of the forest and it is paid by every ask,
including the ones the answer store (J.10.7) serves without a model,
because the reading fingerprint needs a fresh reading before it can
decide. A forest that grows by ingest therefore gets slower at
answering, forever, which is the opposite of what a curated map is for.

The scan is a **pure function** of a body and a folded term, so it is
memoizable without touching semantics:

- **The memo (new C.6b.1).** A Vine MAY cache the per-line result of the
  literal scan in the derived layer, keyed by (folded term, node), valid
  while the node's stored **body hash** matches. Output MUST be identical
  to the direct scan, byte for byte this is memoization of the scan,
  never its replacement by a tokenized index, so the C.6b split with
  `locate` and the literal-substring contract are untouched. Rows record
  **non-matches too**: without them the 95% of nodes that never match are
  rescanned on every call and the memo buys nothing.
- **Line granularity is normative, not an implementation taste.** The
  scan emits one match per *line*, centred on the leftmost term that hit
  it, so the union of two per-term memos is not the two-term result. A
  memo MUST store enough per line to reproduce the combined snippet.
- **Hash, not timestamp.** Validity is decided by content, so a
  `reindex`, a `git pull` that changed nothing, or an edit reverted to
  its original text do not invalidate what did not change. `mtime` is
  coarse, platform-dependent and can move backwards.
- **The catalog carries the hash (C.6.1).** One more column, written on
  every upsert, rebuilt by `reindex` the disposable layer's usual
  posture: if it diverges from the files, the files win.
- **Only bodies the hash covers** (`content: inline`). A `reference`
  body changes at its source and a `cached` body lives in
  `_derived/bodies`, both with no write to the `.md` the hash digests —
  they keep the direct scan.
- Acceptance: **F.40**.

**Changelog v0.38 → v0.39 the snapshot travels.**

J.13 could take a snapshot and name it, and there it ended: the bundle
was born on the Station's volume and stayed there, reachable only by
the shell the hosted operator does not have. A forest came *back* the
same way `vine snapshot restore` at a terminal. Part I's own use
cases backup, distribution, the team that pulls the whole map in one
small download were promised to exactly the people the host layer
exists to serve, and the host layer did not serve them. Two additions
to J.13, both owner-only:

- **Download (J.13.1).** `GET /v1/admin/snapshots/{forest}/{file}`
  streams a bundle or payload sidecar the J.13 listing already names.
  A snapshot is the whole forest with its whole history every branch
  scope a grant table enforces collapses the moment the bytes leave —
  so the only principal a download cannot over-serve is the one whose
  authority already spans everything: the owner bit. Contained after
  resolution, audited, and it touches no forest no lane, no trace,
  no pheromone, no commit.
- **Import (J.13.2).** `POST /v1/admin/snapshots/import` accepts the
  bundle (and optional sidecar) in the request body and restores it
  into a forest id that does not exist yet J.7's name validation,
  J.7's refuse-if-existing, J.7's grant-to-creator. The J.13 objection
  to exposing restore was never restore itself: it was the live-forest
  destination and the host path taken from a caller, and import has
  neither. The imported forest arrives servable (`reindex` included)
  and arrives cold: no model call, no curation, no canopy a bundle
  is already forest and enters as-is, which is exactly why the door is
  owner-only.
- Part I gains the pointer: a hosted Station moves snapshots over HTTP
  under J.13's rules. Restore into an *existing* forest stays a shell
  act, as before. Acceptance: **F.39**.

**Changelog v0.37 → v0.38 the map settles, groups, and replays.**

The graph mode of J.5.4 drew a thousand-node forest as one trembling
blob: every cluster collapsed onto every other, and a deliberate drift
kept the picture moving forever, so the one console built to show the
shape of the forest was the one console where the shape could not be
seen. The encoding rules gain teeth, and J.11 carries one more passport
fact:

- **The layout must come to rest (J.5.4).** A map at rest holds still;
  motion is spent only on change new data, the operator's hand, or an
  explicit reorganize. A forest cannot be pointed at while it trembles,
  and "pointing at it" is what a map is for. Distinct regions must read
  as distinct: a layout that piles unrelated branches into one heap is
  not a presentation choice, it is a map that answers the operator
  wrongly.
- **Colour is a choice between facts (J.5.4).** Colour MAY encode the
  node's type (the dialect) or its home branch (the id) both are facts
  the forest holds. A console MUST NOT colour by a category the forest
  does not hold, and whichever fact colour encodes, the legend names it.
- **View tuning belongs to the operator (J.5.4).** Filters, grouping,
  label visibility, node scale, link width, force strengths all
  presentation, all local. Tuning MAY persist in browser storage per
  forest; it MUST NOT enter the address (J.5.8: the address carries the
  selection, not the taste) and it MUST NOT spend a call or a write.
- **Growth replay (J.5.4).** A console MAY replay the region in
  `created` order: nodes appear as they were planted, trails appear when
  both ends exist. Replay is presentation over the projection already in
  hand no second call, no write, and under reduced motion it is a
  scrubber, not an animation.
- **`created` joins the projection (J.11).** The passport has always
  held it and the projection already carries `updated`; a replay of the
  forest's growth is a shape question, and shape questions are what J.11
  exists to answer in one call.

**Changelog v0.36 → v0.37 the batch is visible from every console.**

v0.36 stopped the ingest console from forgetting a running batch; every
other console still could not say one existed. The operator J.9 freed to
look elsewhere had to come back to know their 1800 documents were still
landing presence was the price of awareness. New section **J.9.3**:

- **A small indicator on every console of the forest** announces the
  running batch and the waiting queue, expanding on demand into the job
  record's progress done over total, the document in hand, errors so
  far with the cancel and the way to the ingest console.
- **It reads the job board and nothing else.** No browser-storage copy
  of a record the host already keeps: a stored id goes stale in both
  directions it survives the restart that forgot the record, and it
  misses the batch another principal started. Entering a forest asks the
  board once; everything after is the watch.
- **One watcher per forest, its cadence following the attention**: the
  order of a minute collapsed, the order of seconds expanded or with the
  ingest console open, settle-detection pace while a queue waits.
  Watching is free in every ledger (J.9), but free is not a licence to
  be noisy.

**Changelog v0.35 → v0.36 the console keeps sight of the batch.**

J.9.1 put the running job in the address so a reload could not lose it —
and then the operator moved to another console, whose address the query
does not follow, and came back to an empty form while 1800 documents
ingested on. The record was on the board the whole time; only the console
stopped looking. And under that running batch, the submit button told the
operator with the next folder already in hand to come back later a wait
the console could have held for them. Two amendments, both console-side;
the host's contract (one batch per forest, refusal over queueing, J.9)
does not move:

- **Returning rediscovers the running job (J.9.1).** Entering the ingest
  console with no `?job=` reads the job list a record, never a call —
  and puts a running job's id back in the address, replacing. What the
  operator started is on screen whenever they stand where it runs.
- **The next batch waits in the console, never in the host (new J.9.2).**
  The console may stage batches while one runs and submit each as an
  ordinary batch POST when the board frees, first in first out. The queue
  is tab memory: visible where it waits, never in the address, dead with
  the tab which is exactly why it does not reopen the door J.9 closed,
  whose danger was *invisible* work that *outlives* its asker. A cancel
  holds the queue (stop means everything); a refusal other than
  `E_LOCKED` holds it too, shown; `E_LOCKED` means another client won
  the race, and the queue simply waits for the job the refusal names.

**Changelog v0.34 → v0.35 the second hash: the reading decides the
model.**

v0.33 keyed every answer-store entry by the forest's HEAD, and HEAD is a
hammer. Every write moves it a `tend` in a sales table emptied the
stored answer about architecture, one Ranger promotion emptied the whole
store so on a forest that is actually alive, the store spent its life
empty. The invalidation was never wrong. It was indiscriminate, and
indiscriminate is expensive at exactly the scale the store exists for.

The fix restates what the store is for. What must never go stale is not
"the forest as of a commit" it is **the model's reading**: the material
the sweep put in front of the provider. The retrieval that assembles that
material is the cheap half by five orders of magnitude, so the sweep now
runs it on **every** ask, hit or miss, and the store fronts the model and
never the search. Two digests, two jobs: the first the question under
its configuration finds the entry; the second the **reading
fingerprint** decides whether the model owes a fresh pass.

- **The sweep's key loses HEAD; the entry gains the reading fingerprint.**
  A digest over the material as a set keyed by id types, titles,
  summaries, matches, bodies, the truncation flag and nothing volatile:
  not score, not heat, not the serving order, which pheromone reshuffles
  on every use. A result that enters or leaves the set is a change of
  reading; a reshuffle is not.
- **A hit runs the forest and skips only the bill.** The sweep's
  primitives really run, so a hit's trace is its own retrieval's and
  the whisper of Part D now closes every hosted answer: heat on the
  evidence, hit and miss alike (v0.33 whispered only on hits, telling
  the Ranger that bought answers did not matter). The response says
  which half is which retrieval fields fresh, model fields the record,
  `cached: true` with the time the reply was bought.
- **A reading that changed is a miss, exactly.** A `graft` on a node the
  question reads invalidates it; a `plant` in a branch it never touches
  invalidates nothing; a `tend` that changes rows but not prose changes no
  reading. Heat that pushes a result out of the set or a new one in —
  changes the reading and is honestly a miss; the worst case is a bought
  run, never a stale answer.
- **The walk stays v0.33.** A forager's path cannot be re-walked without
  paying the model per hop, so walk entries keep HEAD in their key, are
  served as received, and deposit heat through the trails store.
- **C.6c.2 stops refining index nodes.** Building the fingerprint exposed
  a harvest bug: `sniff` resolves an index id to its subtree, so refining
  an index result grepped the forest under it children's snippets
  attributed to the index, chosen by heat rank, different on every read
  (and `pick` then failed to open those foreign sections for content).
  An index result now keeps the global sniff's within-body matches.
- Criterion **F.37** rewritten for the reading check.

**Changelog v0.33 → v0.34 the cap the operator sets.**

C.6c capped `k` at five because the bundle is spent twice: once by the
engine, in milliseconds, and once by whoever reads it prompt tokens,
prefill, a context window that may not hold twenty thousand tokens of
evidence. That second bill is the deployment's, not the dialect's: a
Station bound to a wide-window model wastes nothing at eight bananas,
and a thin client on a four-thousand-token window chokes on six. One
compiled number cannot be right in both rooms, and until now it was
compiled in.

- **C.6c: the harvest cap moves to the environment.**
  `MONKEYLLM_HARVEST_MAX_K` (an integer >= 1) sets it; unset means **5**,
  exactly as before, so no deployment changes behaviour by upgrading. A
  value that does not parse, or parses below 1, is refused (`E_SCHEMA`,
  naming the variable) never silently corrected, per the project's
  reject-early rule. The response budget is untouched and remains the
  outer wall: a raised cap buys more items only until the budget
  truncates, explicitly, as ever.
- **J.10.7: the key holds the effective `k`.** The cap shapes the
  sweep's answer, so the capped value is what names it. A cap raised
  between restarts therefore misses cleanly instead of serving
  five-banana answers under a ten-banana promise and two callers
  asking past the cap stop minting distinct keys for one identical
  answer. The walk's `k` (J.10.5) was never capped and keys as given.
- New acceptance criterion **F.38**; F.37's miss list now says the
  effective `k`.

**Changelog v0.32 → v0.33 the answer already bought.**

The cost of this product has two halves that differ by five orders of
magnitude. Retrieval is a fraction of a millisecond J.10.6 exists because
that fact is invisible from outside and the provider round trip behind an
`answer` is seconds, and the only line on the bill. A deployment in front of
real traffic does not receive an even spread of novel questions; it receives
the same handful all day. Every repetition re-ran the model over the same
harvest of the same forest under the same binding and the same scope, and
paid full price for an answer the deployment had already bought. Nothing in
the call was new. Only the bill was.

v0.31 ruled that the host keeps no model output (J.5.9), and that ruling
stands unrevised. A *run* is one operator's private working note about an
evaluation kept where it was made, dead with the credential, shareable
with nobody by construction. What v0.33 adds is a different object: an entry
in a per-forest store, named by everything that shaped the call, served only
to callers whose call is the same call, and invalidated by the forest itself
moving. The host still keeps no history of what models said; it keeps the
answer this deployment already paid for, under a key that states exactly
what was paid for.

- **J.10.7 The answer already given.** `answer` and `answer` alone is
  fronted by a bounded per-forest store in `_derived/`. The key is a closed
  list: the normalised question, the effective terms, `k`, the hops budget,
  the resolved binding, the caller's scope, and the forest's HEAD. Anything
  that could change the answer is part of the name of the answer.
- **The forest's own clock is the invalidation.** Every write is already a
  commit and HEAD is in the key, so every entry made before a write misses
  after it there is no invalidation code to be wrong. A TTL is hygiene,
  never correctness.
- **Nothing empty and nothing broken is kept.** A retrieval that found
  nothing, an errored or truncated response, a turn that wrote none of
  them enter the store.
- **A hit says so, and still heats the forest.** The response is labelled a
  record, not a bill; heat lands on the entry's stored trail through the
  trails store, never through a primitive. J.6.1's warming rule in mirror:
  warming through `locate` would forge evidence of use, and serving from a
  store without depositing would hide it.
- **J.10.6 gains `cache`**, present when the store was consulted; on a hit
  `model` is absent, because no provider ran. **J.4 records a hit as a
  hit**, with the entry's digest, so a served answer still reconstructs.
- **The near question is an opt-in with a disclosure.** Serving on
  similarity instead of equality exists only where a Canopy index and an
  embedder already do, is off by default, and names the stored question it
  answered.
- New acceptance criterion **F.37**.

**Changelog v0.31 → v0.32 a batch is not a request.**

Adopting a folder is minutes of work: a converter pass, a model round trip
and a commit *per document*. The Station ran all of it inside the HTTP
request that asked for it, on the one worker thread every forest shares —
an acknowledged simplification, and this is the release that pays it off.
The consequences arrived together, as they always do: the gateway timed the
request out at its own limit and answered 524 while the work kept running,
unwatchable; every console froze, because a `look` on an untouched forest
was queued behind somebody else's ingest; and the operator, shown a dead
spinner over a working batch, learned nothing a progress bar would not have
told them. Three failures, three rules:

- **Work that outlives a request must not answer as one.** The batch modes
  of J.8 `adopt`, `sync`, `upload` now validate synchronously and answer
  **202 with a job**: identity, progress, and, when it finishes, the same
  unabridged `IngestReport` as before. `compose` is one document and a
  review conversation, and stays in place. New section **J.9**.
- **One forest's work must not delay another's.** Isolation between forests
  is now normative, not an implementation aspiration: a call on one forest
  MUST NOT wait on another forest's work (J.9). The SQLite thread-affinity
  discipline was always per forest; the single lane never was.
- **A batch must not starve the forest it is filling.** `adopt` and `sync`
  become drainable step iterators in Part G one document per step, the
  report as the final value so a host can let reads through between
  steps and count progress without a second pipeline. New section
  **G.10**; the recorded source root moves to *before* the first step,
  which is what makes an interrupted batch completable by `sync` instead
  of restartable from zero.

Progress is watched, not streamed: a job is a host record, reading one
touches no forest, and the console follows it by the address (`?job=`,
J.5.8 discipline restoring a page never spends a call). A second batch on
a busy forest is refused with the running job named, a restart forgets
records but never work, and the MCP `ingest` tool waits by default because
an agent's poll loop is context spent on plumbing.

- New acceptance criterion **F.36**.

**Changelog v0.30 → v0.31 judging a forest is a comparison, and the
console kept nothing to compare.**

Ask is where this product is judged. Somebody types a question, reads the
answer, and then does what everybody does next: asks it again after an
ingest, with the walk turned on, against a model that has since been
rebound. Each of those destroyed the one before it. The console held exactly
one result, in application state, and a reload held none.

What was lost is not the prose. `answer` comes back with the evidence, the
material the model was actually given, the walk it took, the host's three
clocks and the token cost (J.10.4, J.10.5, J.10.6) the whole apparatus
that turns an answer into something checkable rather than something to
believe. The only way to keep any of it was the markdown download, which
keeps the prose and drops all of it.

So the console keeps the runs it made, and keeps them **in the browser**. A
run is not a fact about the forest: the forest's own record of that call is
already written the audit row of J.4 and the pheromone of Part D, both at
the moment it ran. What a model said is not curated, not indexed, not
versioned and not reproducible, so a host that stored it would be keeping
model output where forest content lives; and a synced history would copy a
grant's worth of node bodies onto a second machine to make a convenience
work.

- **J.5.9 The runs already made.** Question, parameters as sent and response
  as received, kept by the browser, keyed by principal and forest, discarded
  with the credential.
- **A restored run is a record, not a call.** J.5.8's rule one level in: it
  says when it was made and which model made it, and asking again is a
  deliberate act that leaves a new run beside the old one.
- **A run has no address.** J.5.8 made the console's places linkable; a run
  exists only in the browser that made it, so a URL naming one would work
  for its author and be broken for everyone else.
- **The bound is stated, never silent** the truncation rule of C.6 applied
  to a store instead of a response.
- New acceptance criterion **F.35**.

**Changelog v0.29 → v0.30 the console gets an address.**

Every screen of Studio lived at `/`. Which forest was open, which console
was showing and which node was selected were React state and nothing else,
so the address bar said the same eight characters from sign-in to sign-out.
Three consequences, each of them a thing an operator does daily:

- **a reload lost the place.** F5 is not an exotic gesture it is what a
  person does when a panel looks stale and it returned them to the first
  forest of their list and the default console. For someone working in the
  third forest that is a silent relocation into somebody else's data, and
  the console said nothing about having moved them;
- **nothing could be sent to anybody.** "Look at this node" was a sentence
  containing directions rather than a link, in a product whose entire
  subject is addressable knowledge;
- **Back left the product.** The console had never written a history entry,
  so the browser's back button went to whatever preceded the Station.

The forest is the scope of every request on the page, and the operator
picked it deliberately. It is the one piece of state a console must never
choose again on the operator's behalf.

- **J.5.8 The address bar.** `/f/{forest}/{console}`, with what the console
  has selected in the query. The URL is the console's state, not a
  decoration of it: moving writes a history entry, adjusting replaces one,
  and rendering never writes at all.
- **A forest that cannot be shown is named, not swapped.** Following a link
  into a forest this principal has no grant on MUST say so. Redirecting to a
  forest they *can* see is how a person comes to believe they are looking at
  a forest they are not.
- **Restoring a place restores a page, never a call.** The address carries
  what is being looked at. It MUST NOT carry a model call, a write, or
  anything else that spends money or changes the forest on arrival.
- **The host answers the console's addresses.** A deep link is a GET of a
  path the API does not own, so the Station serves the shell for it for
  *document* requests only, so a missing asset stays a 404 instead of
  becoming an HTML page with a JavaScript MIME type.
- New acceptance criterion **F.34**.

**Changelog v0.28 → v0.29 a client stopwatch is not a measurement of the
engine.**

The whole claim of this project is a number: navigation is cheap. A
`locate` costs a fraction of a millisecond, and that is the difference
between an agent that may look around and one that must be given everything
up front. The console that exists to show a caller exactly what an agent
sees the Playground was reporting that call at **29 ms**.

Nothing was slow. The console had no other number to show. It timed the
`fetch` with `performance.now()`, so what it displayed was TLS, the
internet, HTTP, JSON and a React render, with the primitive somewhere inside
it measured in process, that same `locate` is 0.226 ms of engine and
0.58 ms of host. The console printed the transport and labelled it the
call, in accent colour, as the headline of the panel.

The engine has timed every primitive since Part D. J.10.4 already carries
those numbers out to a caller but only for `answer` and `harvest`, on the
reasoning that "a single primitive already reports its own latency to
whoever invoked it". That is true of a library caller and false of an HTTP
one: over the wire, `elapsed_ms` never leaves the process. Every REST client
of this host has been in the same position as the Playground, with no way to
tell a slow forest from a slow network.

The fix is not to put a `trace` on every primitive. A response body is the
agent's context window and it is budgeted in tokens (C.6); charging every
`locate` for a diagnostic no agent reads would be paying for the console's
instruments out of the model's pocket.

- **J.10.6 The host's own clocks.** Every primitive response carries
  `Server-Timing` `vine`, `host`, and `model` when a provider ran. It is a
  header, so the body is byte-identical and the token budget is untouched;
  it is the standard header, so a browser's network panel already draws it.
- **The engine number is the headline, and transport is an aside.** A
  console that shows latency MUST lead with the engine's own figure and MUST
  NOT present a client-side round trip as the cost of a call. What is being
  judged is retrieval; the rest of the span is the reader's own network and
  host. It is still stated once, quietly, named as infrastructure because
  a small number with no account of the gap is read as a claim.
- **Never a second instrumentation.** `vine` is the sum of the tracer events
  the call appended, the same slice J.10.4 already reports. `host` is what
  is left of the host's own span after the engine and the provider: policy,
  audit, serialisation. Three clocks that add up to the span, or the header
  is wrong.
- New acceptance criterion **F.32**.

**And then the number was measured, which is the point of reporting it.**
With the engine's own clock finally visible, the first call of a fresh
process turned out to cost around ten milliseconds of host against a third
of one from the second call on none of it the corpus, all of it SQLite
waking up. Reporting a number honestly is what makes it worth improving.

- **C.6.1 amended: derived storage is tuned for reads.** Every read
  primitive deposits pheromone, so every read is also a commit; `_derived/`
  databases open in WAL with `synchronous=NORMAL`. The durability given up
  is durability the derived layer never had the files are the truth and
  `reindex` is the repair and it buys roughly a fifth off the median
  `locate` and a third off p95.
- **C.6.1 amended: `warm()`.** Storage only, never through a primitive: a
  server that warmed itself through `locate` would be forging the pheromone
  the Ranger reads as evidence of where callers went.
- **J.6.1 Boot opens the forests.** Default on, off for registries too large
  to hold open, best effort so one locked forest cannot stop a Station.
  Opening costs what it always cost; this only decides who waits for it, and
  the answer should not be "whoever arrives first".
- New acceptance criterion **F.33**.

**Changelog v0.27 → v0.28 the first minute of a deployment, said out
loud.**

v0.25 gave a Station with nobody in it a way to acquire somebody. What it
did not do was tell anybody. The first minute of every deployment happens in
a terminal `docker compose up`, a stream of log lines and the product
said nothing there about how to get in, while a convenience left over from
before the owner existed quietly made sure that nothing worked.

`station serve` minted an `admin` API key on any registry that held no key,
and printed it. Three consequences, each of which alone is a locked door:

- the key was granted `admin` **per forest**, and a fresh volume has no
  forests, so it authenticated as a principal with no authority at all —
  `admin: false`, and the first forest refused with `E_FORBIDDEN`. That is
  the v0.25 deadlock exactly, re-entered through a door v0.25 did not look
  at;
- an API key **is a credential**, so minting one closed the J.2.4 setup
  route before the first HTTP request arrived. The setup screen, the
  documented first door, could never appear in the shipped image;
- it was printed to a block-buffered standard output, so on the occasions it
  would have mattered it did not reach `docker logs` at all.

The correction is not a bigger banner. It is that **starting a server is not
an act of administration**: a Station MUST NOT acquire a credential by being
switched on, and what it says on first run must describe the door that is
actually open.

- **J.2.5 The first-run announcement.** On a Station nobody can yet sign in
  to, the console output MUST say how to get in: the URL, and which of the
  three states the deployment is in. It is keyed on the registry, not on a
  flag file, so it appears exactly while it is true and stays quiet on every
  later restart.
- **Starting mints nothing.** The registry a Station starts on is exactly as
  authoritative after boot as before it. J.2.4's window closes when a person
  closes it, never as a side effect of a restart.
- **The bootstrap key is break-glass, and it is asked for.** An operator with
  no browser MUST still be able in, so `--bootstrap-key` mints the first key
  explicitly, once, and **carrying the owner bit**, because a first
  credential that cannot create the first forest is the deadlock with extra
  steps. It consumes the same one-shot window as the setup screen, and the
  announcement says so: two doors to the same first identity, never open at
  the same time.
- **The environment password is never printed.** Echoing a value the
  operator already holds adds no way in and adds one copy in every log
  aggregator downstream.
- **J.6 amended: the announcement is unbuffered.** A first-run instruction
  that arrives when a 8 KiB buffer happens to fill was not delivered. This is
  a deployment detail and it is normative, because the feature is worth
  nothing without it.
- New acceptance criterion **F.31**.

**Changelog v0.26 → v0.27 the console can shape the forest it serves.**

A forest created through the console has exactly one branch: its master
index. Nothing in the console could add a second. The only branch-maker in
the whole product was `adopt`, which does not invent structure it mirrors
a source directory tree so a forest that did not arrive as a folder tree
could only ever be a flat pile at the root, and the operator's one shaping
tool was to go and reorganise a folder on some other machine first, then
ingest it. The Ingest console asked "where do these go?" and offered only
the branches that a past adopt happened to create.

Nothing in the engine was missing. `plant` already accepts `type: branch`,
already refuses an id that does not live under its parent, already refuses
a duplicate, already grafts the entry into the parent index and commits
both files atomically, and `ScopedVine` already refuses a write outside the
grant. The gap was entirely a console that never called it which is the
best kind of gap, because closing it adds no second way to write.

- **J.5.7 Shaping the forest.** The console creates a branch through
  `plant` and through nothing else. The operator names it; the console
  derives the id and never lets anyone type one, because ids are immutable
  (C.7) and a typo would be permanent.
- **The destination picker creates.** "Where do these go?" is exactly the
  moment the missing branch is discovered, so the branch can be made from
  there the same call, not a second one, and not a trip to another
  console and back.
- **The boundary is stated, not implied.** There is no move, no rename and
  no delete: ids are immutable, a node's id encodes its branch, and no
  primitive relocates one. The console can create structure and curate it.
  It is not a file manager, and this is written down so nothing is designed
  against one that does not exist.
- New acceptance criterion **F.30**.

**Changelog v0.25 → v0.26 ingest grows a perimeter: every source is
named, vetted, and contained.**

A forest created through the console and then refreshed from it ingested
the Station's own installation tree. The chain had three links, each
defensible alone: `sync` defaults to the source root a prior `adopt`
recorded (G.3); a forest that has never adopted has no such root; and an
absent root was read as the empty path, which every filesystem API resolves
to *the working directory of the process*. So the one mode J.8 exempts from
the `admin` requirement exempt precisely because its directory was vetted
at adopt time became the one mode that walked a directory nobody had ever
vetted, on behalf of a principal who was never asked for `admin`.

Three more escapes of the same shape were open beside it. The walk had no
notion of a forest, so a source placed above the registry would have
adopted every neighbouring forest's passports as documents, across the
tenant boundary. A targeted `sync` joined its caller's path onto the source
root and checked containment with `relative_to`, which is lexical: `../../x`
survived the join and came back out as a "relative" path, so the file was
read and planted. And `content: reference` resolved `source_root/source_path`
without checking the result stayed underneath it, which turned `pick` a
*read* primitive into a reader for any file the host process could open.

None of the four was a missing check inside a feature. They were the same
absent idea, four times: **an ingest source is a boundary, and a boundary
has to be stated somewhere.** This version states it.

- **G.3 amended: an ingest source is always a named, contained directory.**
  The empty source is a caller error, never a fallback to the working
  directory. A source MUST NOT be, contain, or sit inside the forest, and
  any directory that is itself a forest is pruned from every walk.
- **G.8 amended: a targeted `sync` path is contained after resolution**,
  not by string inspection `..` collapses and symlinks are followed
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
  install tree defence in depth, so that the next path bug lands
  somewhere empty.
- **J.8 amended**: a console MUST NOT offer a refresh without naming the
  directory it will re-read. A blind button is how this shipped.
- New acceptance criterion **F.29**.

**Changelog v0.24 → v0.25 the first boot: a deployment that has nobody
yet must still be able to acquire somebody.**

Every version so far assumed the registry already had an administrator. It
does not on the day it is installed. A Station started on an empty volume
grants the environment super-admin `admin` on every forest *in the registry*
— of which there are none so it authenticates and governs nothing, and
J.7 then refuses it the first forest because creating one requires `admin`
on a forest that already exists. The two rules are individually sound and
jointly a deadlock: the product cannot be reached through its own front
door on the one occasion every deployment goes through.

The fix is not a wider grant. It is recognising that **the authority to
start a forest cannot itself be derived from a forest**, and giving that
authority somewhere to live.

- **J.2.4 First-run setup.** While the registry holds no credential, the
  Station offers exactly one unauthenticated route that creates the
  **owner** and it closes permanently, in the same transaction that
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
  and while it is configured the setup route does not exist one door at a
  time, so the two can never race for the same first identity.
- **J.5.6 The setup screen**, pre-identity like the Gate, and the optional
  seeded forest that makes an empty console teach something. The seed is
  never shipped as content: it is generated, outside the engine, by code
  that only calls public primitives.
- New acceptance criterion **F.28**.

**Changelog v0.23 → v0.24 composing with review: the author sees the
passport before the forest keeps it.**

`compose` (v0.22) let a person post prose and have the Curator make a node
of it. It planted first and reported afterwards, so the summary that becomes
the scent every later hop navigates by, and the link proposals that become
the Ranger's working set, were facts before anyone had read them. Undoing
them meant editing a node that already existed.

- **J.8.1 Two-phase compose.** `stage: true` runs the whole pipeline —
  converter, curation, G.4.2.1 candidate proposals and stops at the
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
  candidate rules of G.4.2.1 `related-to` only, existing and in-scope
  targets, never a branch, never self or parent, capped at 3, and pinned at
  confidence 0.3 whoever kept it.
- **Staging is not planting, and dry-run is a property of the Gardener.**
  `Gardener(dry_run=True)` cannot write: no plant, no graft, no body cache,
  no archived bytes, no config. The flag lives on the object rather than on
  a call so no path can forget it.
- New acceptance criterion **F.27**.

**Changelog v0.22 → v0.23 the maintenance surface: the Ranger reports to
somebody.**

Part H gave the forest a Ranger and Part I gave it snapshots, and both have
been reachable only from a shell. The operator who most needs to know a
branch has grown too wide, or that a hundred link proposals are waiting, is
the one running a hosted Station and they have a browser.

- **J.13 Maintenance surface.** `GET /v1/admin/health` returns the Ranger's
  H.3 report unchanged; snapshots can be created and listed over REST.
  Neither is a primitive and neither invents a number: the report is what
  `Ranger.health()` already computes.
- **Health is an owner's view, and says so.** The report counts and names
  things across the WHOLE forest lint errors, fat nodes, stale passports —
  so it requires `admin` *and* an unrestricted scope. A scoped principal is
  refused with the reason rather than handed a filtered half-report whose
  numbers would quietly describe a forest they cannot see.
- **Restore stays on the command line, deliberately.** Part I restores a
  bundle into an *empty* destination; there is no in-place restore to offer,
  and a console button that always answers "target is not empty" would be a
  worse answer than no button. Disaster recovery is not a web workflow.
- New acceptance criterion **F.26**.

**Changelog v0.21 → v0.22 Forest Views: the map becomes visible.**

Everything the Station serves has been legible to an agent and illegible to
a person. `look` returns a digest, `scan` returns a page, and neither ever
shows the shape of the thing being navigated. A forest is a graph with
heat on it; a console that can only render lists is describing a map by
reading out street names.

- **J.11 Map projections.** Two read-only endpoints `GET /graph` and
  `GET /trails` that project the Catalog (C.6.1) and the pheromone layer
  (Part D/H.1) as whole-of-region payloads. They add no primitive and no
  engine capability: everything they return is already reachable one node
  at a time through `look`/`move`/`scan`, and they are subject to the same
  J.3 filtering, including the recomputation of every derived count.
- **J.5.4 Forest Views.** The Explore console gains modes over one
  selection graph, tree, files and the file view renders each file as
  what it is: markdown rendered by default with the stored source one click
  away, a dataset payload as a browsable table, an HTML body as a page.
  Presentation only: no request, response or permission changes.
- **J.8's fourth mode, `compose`.** A person writes prose in the console
  and it enters the forest through the ingest pipeline that already exists
  same converters, same curation, same commits rather than through a
  second, unaudited door.
- **Editing is a write, not a save.** A console MAY offer rich editing of a
  node, and MUST express the result as `graft`/`tend` operations. Writing
  a node file directly is forbidden to every surface, the console included.
- New acceptance criterion **F.25** (a map projection discloses nothing a
  node-by-node walk would not).

**Changelog v0.20 → v0.21 the Gauntlet: the vector layer moves from the
entry to the hand:**

Measurement (2026-08-08, bge-m3 on a local Ollama) established where the
dense layer helps and where it hurts, and the two answers are opposite:

| Corpus | BM25 R@1 | Hybrid R@1 |
|---|---|---|
| bench-forest, 18 v2 queries | 0.778 | **0.889** |
| forest-fixture, 10 demo queries | **1.000** | **0.400** |

RRF rewards *agreement*, not correctness. Fusing a fuzzy ranker into one
that is already right can only pull the answer away from rank 1 on the
fixture it dropped `block-loop` from 1st to 4th while the vector list
surfaced the topically-adjacent `speculative-decoding`. So the published
hybrid row does not survive scent-weighted BM25, and v0.19's own
`{{TODO: hybrid re-run}}` is answered in the negative.

The same rule points at where the layer *does* pay. Entry search already
has a strong query-dependent ranker. **Navigation has none**: `look` orders
edges by heat (past usefulness), `scan` by degree (connectivity), `move`
not at all every one of them blind to what is being hunted right now.
Adding a query-dependent signal there is not fusion; it is the first such
signal, with nothing to dilute.

- **Part K the Gauntlet.** The forager carries the query vector and the
  *frontier* is ordered by proximity to it: which neighbours `look` shows
  within its edge cap, which children `scan` returns under its budget,
  which way `move` points. Cost is one query embedding per hunt, reused
  across every hop; per hop it is a dot product over vectors already in the
  Canopy no HTTP, **no tokens**.
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

**Also in v0.21 J.10.1, the provider the deployment already declared:**

A Station started with `MONKEYLLM_LLM_ENDPOINT` and its key has already
been told everything the console's provider form would ask for. Asking
again makes an operator copy a secret out of the place that governs it —
the environment, which the deployment rotates and never backs up into a
place that does not.

- **J.10.1 Environment-declared providers.** They appear configured at
  boot, marked `origin: "env"`. The key is resolved from the environment at
  call time and **MUST NOT be written to the registry**. The console MUST
  refuse to edit or remove one accepting would be undone by the next
  restart. A row whose declaration is withdrawn becomes an ordinary console
  row rather than being deleted with its bindings.

**Changelog v0.19 → v0.20 one person, several forests, one decision:**

v0.19 made the *person* the unit of administration but left the grant step
naming a single forest, so a registry hosting six forests turned "give this
service read access to everything" into six visits to the same form six
requests, six chances to stop halfway, and a token whose real reach was
never visible in one place. The person was one thought; their access was
still shaped like one row of the grants table.

- **J.2.3 `grant` and `revoke_access` take one forest or several.** `grant`
  MAY carry `forests: [<id>, …]` instead of `forest: <id>`, and
  `revoke_access` MAY carry a list. The scalar forms remain valid and mean a
  one-element list, so every existing client keeps working.
- **A list is not a relaxation.** Each named forest is authorised on its
  own (`admin` on *that* forest), applied on its own, and refused on its
  own a refusal names the forest and MUST NOT discard the forests the
  caller was entitled to grant. This is J.2.3's partial-application rule
  applied within a step rather than only between steps.
- **Scope prefixes are forest-local.** `allow`/`deny` apply to every forest
  named in the same grant, because a grant is one policy. Branch names are
  not portable between forests, so the console offers the branch picker only
  when exactly one forest is selected and grants the whole forest otherwise
  (J.5.5) the API does not second-guess a caller that knows better.
- **What did NOT change:** the escalation rule (J.2.2). A key still
  authenticates a principal, so minting one still requires `admin` on
  **every** forest that principal holds which is precisely why the grant
  step has to be able to say "these forests" in one request that the
  administrator of all of them can make.
- Criterion **F.23** extended: a multi-forest grant lands on every forest
  the caller administers, refuses the ones it does not by name, and the
  resulting token reads in each granted forest.

**Changelog v0.18 → v0.19 governance is organised around people:**

The host grew three governance objects grants, passwords, API keys and
the console grew one screen per object. That is the storage model wearing a
navigation bar. Nobody administers a *grant*; they onboard a **person**, and
onboarding is one thought: this is who they are, this is what they may see,
here is how they sign in, here is a token for their script. Splitting that
across three destinations made the operator hold the model in their head
instead of the interface holding it for them.

- **J.2.3 `POST /v1/admin/people`** one call applies any combination of
  grant, revoke-access, password and token changes to one person, so the
  console can offer onboarding as a single form. It is a **composite, not a
  new authority**: each part re-checks the rule that already governed it,
  and the parts apply in an order that makes a first-time grant usable
  (grant first, so a brand-new principal becomes administrable and can then
  receive a password and a key in the same request).
- **`GET /v1/admin/people`** the person-shaped read the console needs:
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

**Changelog v0.17 → v0.18 administration stops being global:**

Asking "should the console hide what a person cannot do?" turned into an
audit of every host route, and the audit found the real defect. Every
`/v1/admin/*` route correctly refuses a non-administrator but it treated
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
- **J.5.1 revised** a console the principal cannot use is now **omitted
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

**Changelog v0.16 → v0.17 credentials get a front door and a lifecycle:**

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
- **The environment super-admin** `MONKEYLLM_STATION_ADMIN` and
  `MONKEYLLM_STATION_PASSWORD` is verified against the environment and
  never stored: it is break-glass, and hashing a value that already sits in
  the environment protects nothing while giving a rotation two places to go
  wrong.
- **J.2.2 Token lifecycle** label, expiry, revocation, last use, and a
  non-secret prefix so a token can be recognised in a list without being
  disclosed. Expired and revoked keys MUST fail authentication, which is
  where a lifecycle either exists or does not.
- **The escalation rule that makes delegated token issuance safe:** minting
  or revoking a key for a principal requires `admin` on **every** forest
  that principal holds a grant on not merely on one of them.
- **J.5.4 Tokens console**, and the explicit ruling that there is **no
  second, super-admin panel**: one console over one API, with capabilities
  deciding what appears. A second panel needs a second authentication path,
  and a second authentication path is where the backdoor goes.
- New acceptance criterion **F.21** (login, session expiry, revocation,
  last-use, prefix-only listing, and the cross-forest escalation refusal).

**Changelog v0.15 → v0.16 the console becomes usable by someone who has
not read this document:**

v0.14 and v0.15 gave the Station a front door and a choice of reader. Both
were specified from the storage model outward, and the console inherited
that: it asked an operator for capability sets and comma-separated branch
prefixes, offered no way to start a forest or put anything into one, and
spoke one language in one theme. A governed knowledge base that only its
own author can operate is not a product. v0.16 specifies the console as a
first-class contract rather than a rendering of the registry.

- **J.5 rewritten** a normative information architecture (nine consoles
  in three groups), the rule that **the console MUST address the operator
  in the operator's vocabulary**, not the policy model's, and two
  requirements the previous version left to taste: localisation
  (English, Portuguese, Spanish) and both light and dark presentation.
  The no-side-channel rule is unchanged and now explicitly covers strings:
  a translation MUST NOT alter what a surface returns.
- **J.7 Forest lifecycle** `POST /v1/admin/forests`, so a deployment can
  reach its second forest without shell access to the volume. Creation is
  A.5 `init_forest` and nothing else; the id is validated against path
  escape before it is a path, and the creator is granted the forest so a
  newly created forest is never orphaned.
- **J.8 Ingest surface** the Gardener (Part G) reached over REST, with
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

**Changelog v0.14 → v0.15 J.10, per-forest inference (the forest picks its
own model):**

Part J gave forests a front door; v0.15 lets each one choose who reads it.
A forest is not one workload: ingest wants a careful summariser whose output
every later hop navigates by, while answering wants a fast reader that
follows instructions. One global `MONKEYLLM_LLM_*` cannot express that, and
it cannot express "this corpus stays on a local endpoint while that one uses
a hosted model" either.

- **J.10 Providers and role bindings** operators register any
  OpenAI-compatible `/v1` (OpenRouter, LiteLLM, vLLM, local llama.cpp) in
  the host registry, then bind a model per `(forest, role)` with
  `role ∈ {ingest, answer, vision}`. Credentials are write-only across
  every surface: the API accepts a key and reports only whether one is
  set.
- **J.10.3 Model-backed composites** `answer` (retrieval + the forest's
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

**Changelog v0.13 → v0.14 Part J, the Station (the forest gets a front
door):**

Everything up to v0.13 assumes one operator who owns the filesystem.
Corporate self-hosting needs the shape the database products converged on:
an untouched engine wrapped by a host that adds identity, policy, audit and
a friendly surface. Part J specifies that host and specifies it as a
**privileged client**, not an extension: the engine gains nothing, loses
nothing, and its test suite MUST pass unedited.

- **J.1 The Station** one self-hostable service mounting a forest
  registry (the `--root` resolution that already exists) and exposing
  three surfaces REST, MCP, Studio over exactly one enforcement core.
  No surface may reach an unscoped `Vine`.
- **J.2 Identity** principals (users and service tokens), per-forest
  roles, API keys now and OIDC later. Identity and policy live in the
  **host registry**, never inside a forest: forests are content.
- **J.3 Policy (`ScopedVine`)** deny-by-default grants over **branch
  prefixes** plus a capability set, with one enforcement rule per
  primitive. Two invariants make it trustworthy rather than merely
  configured: scope filtering MUST precede budgeting (no truncation
  oracle) and out-of-scope MUST be indistinguishable from absent (no
  existence oracle) including through `move`'s edges, which would
  otherwise leak a forbidden node's existence.
- **J.4 Audit** writes stay git commits, now stamped with the acting
  principal; reads extend the Part D telemetry with principal identity.
- **J.5 Studio** the web console, itself a plain REST client with no
  privileged side-channel.
- New acceptance criterion **F.18** (the leak suite: one test per
  primitive per surface, plus the two oracle invariants).

**Changelog v0.12 → v0.13 branch rollup + Landmarks (the map grows a
sense of place):**

The branch hierarchy already occupies the position that graph-RAG systems
pay dearly to discover (hierarchical communities); what it lacked was
synthesized content at each level. Two additions, zero new primitives:

- **G.4.4 Branch rollup** after adopt/sync curation, the Gardener MAY
  synthesize branch (`_index.md`) frontmatter summaries bottom-up (deepest
  branch first) from the children's entry lines. Scope is strictly
  branches with `source: ingest` (hand-authored branch summaries are never
  rewritten; an explicit `--all` override exists). A.4 summary rules apply
  (validate-and-retry); LLM failure falls back to a deterministic composed
  summary and never blocks (same posture as G.4.2). Writes go through the
  C.8 `graft` path, so verbatim propagation into parent index entries and
  `.md`-only commits are inherited, not reimplemented. Rollup cost is
  O(branches), not O(nodes) the lazy end of the graph-RAG spectrum.
- **A.5 entry-sync rule tightened** when a summary change propagates
  into a `## Sub-branches` entry, the entry's trailing coverage suffix
  (`. N bananas, M sub-branches.`) MUST be preserved (previously it was
  silently dropped by the sync rewrite).
- **A.5 `## Landmarks` implemented as a Ranger duty (H.7)** the master
  `_index.md`'s Landmarks section (already normative since v0.5) is now
  populated mechanically: top 10-20 highest-degree non-branch nodes from
  the catalog's edges table, entry lines with summaries, idempotent
  refresh through the audited `.md`-only path (`ranger(landmarks): …`).
  Zero LLM involvement.
- New acceptance criterion **F.17** (rollup scope/fallback/propagation +
  Landmarks idempotence).

**Changelog v0.11 → v0.12 Gardener v2: native DOCX + edge proposals (the
forest starts weaving itself):**

Two Gardener extensions, both strictly inside the edges-only surface (G.2):

- **G.2.1 DOCX built-in converter** `.docx` joins the built-ins when
  `python-docx` (MIT; lxml, BSD) is importable, mirroring the `openpyxl`
  pattern. Single-pass `w:t` traversal in document order: body paragraphs
  (style-mapped headings), tables (→ pipe tables), and text inside embedded
  text boxes (`wps:txbx` / legacy `v:textbox`); fragmented runs merge
  naturally by joining a paragraph's `w:t` descendants. Headers/footers are
  EXCLUDED (page-number/letterhead boilerplate is scent noise). Technique
  derived from the owner's pdf-replace project (MIT-clean reading side).
  No `python-docx` → `.docx` files report `unsupported`, never a crash.
- **G.4.2.1 Edge proposals** LLM curation MAY now propose `related-to`
  links from the adopted node to EXISTING nodes, each carrying link-level
  `confidence: 0.3` (the C.8 ladder's bottom rung). Candidates come from
  the catalog (BM25 over curated metadata); the model can only pick from
  the offered list a hallucinated target is structurally impossible.
  This closes the loop with Part H: the Gardener proposes, usage heats,
  the Ranger promotes (0.8) or prunes. Entity EXTRACTION (creating new
  `entity` nodes) stays deferred: it needs a placement policy and a
  `same-as` dedup story first.
- New acceptance criterion **F.16** (DOCX fidelity + proposal guard rails).

**Changelog v0.10 → v0.11 the map is not the territory (tiered storage,
big sources, S3-ready):**

A 2 TB source must not require 4 TB locally. The forest splits into three
tiers SCENT (passports: summaries/outlines/links, ~0.1% of source size,
always local, in git), FLESH (converted full text, ~1-5%, local, git or
derived cache), BONE (raw binaries, 95%+, stay at the source / object
storage, fetched rarely). New normative items:

- **G.7 Content & archive policies** per-adoption `content:
  inline | cached | reference` and `archive: never (default) | always`.
  Non-inline bodies are resolved lazily by `pick`/`sniff`; the map
  (locate/look/scan, heat, curation) never needed the body and is
  unaffected. `archive: never` kills the redundant `_assets/` copy when
  the source is durable.
- **G.8 Targeted sync & triggers** `sync(path=...)` reprocesses a single
  source file; an mtime+size fast-path avoids re-hashing unchanged trees.
  Event sources (filesystem watchers, S3/Drive push notifications) are
  EDGES that call targeted sync; **events trigger, the hash-diff
  reconciler stays authoritative** (lost events are healed by the next
  full sync).
- **G.9 Payload fetchers** `payload`/`source_path` MAY carry a scheme
  (`file://` implicit; `s3://` via optional MIT extra). Remote payloads
  download on first use into `_derived/payloads/` (hash-validated cache).
  Dataset `.db` files are **local-first by design** (SQLite cannot be
  queried remotely; hot knowledge bases need sub-ms reads) object
  storage holds them only as backup/cold tiers.
- **H.6 Cache eviction** the Ranger evicts cold entries from
  `_derived/payloads/` (LRU by last access; config `payload_cache_gb`).
- **Part I Snapshots**: `vine snapshot create|restore` packages the
  forest as a `git bundle` (full commit history travels along) +
  compression, optionally uploaded to object storage; payload sidecar
  optional. The Ranger MAY schedule snapshots (backup policy).
- Informative (G.4 note): **progressive curation** adopt the skeleton
  deterministically first (the engine answers immediately with weak
  scent), then LLM-curate as a background queue prioritized by heat: the
  pheromone tells the Gardener where to polish first. Querying an
  UNMAPPED source per-question is the anti-pattern this project exists to
  kill (O(corpus) per question vs O(corpus) once + O(hops) per question).
- New acceptance criterion **F.15** (policies + targeted sync; fetcher/
  snapshot coverage lands with their implementations).

**Changelog v0.9 → v0.10 Part H: the Ranger (long-term maintenance the
forest forgets, confirms and warns):**

The pheromone layer only compounds if it can also FORGET: without
evaporation every trail saturates at 1.0 and heat stops carrying signal;
without pruning, agent proposals (confidence 0.3/0.5) accumulate as noise.
New normative items:

- **Part H (Ranger)** the maintenance daemon: heat evaporation with a
  configurable half-life over `_derived/trails.db` (H.1); promotion and
  pruning of uncertain links links born with link-level
  `confidence < 1.0` are the ONLY Ranger-managed edges (H.2); a read-only
  health report: `needs_split`, fat nodes, lint issues, stale passports,
  low-confidence inventory (H.3); on-demand run + service loop (H.4).
- Ranger is **trusted infrastructure** (like the Gardener): evaporation
  touches only the derived layer (no commits `_derived/` is disposable);
  promotion/pruning write through the audited `.md`-only path with commit
  messages `ranger(promote): …` / `ranger(prune): …`.
- The Ranger NEVER deletes nodes, never touches structural edges or any
  link without a link-level confidence field, and never performs `same-as`
  physical compaction (still human-approved, still out of scope).
- New acceptance criterion **F.14** (synthetic-clock evaporation,
  promotion/pruning safety, health report).

**Changelog v0.8 → v0.9 Part G: the Gardener (brownfield ingest, the
forest learns to grow itself):**

The dominant real-world scenario is **adoption**: the engine is pointed at a
directory tree already full of documents ("mata alta") and must curate all
of it then notice when source files change. New normative items:

- **Part G (Gardener)** the ingest pipeline: passport policy (G.1),
  public converter contract with three discovery sources forest-config
  command hooks, `monkeyllm.converters` entry points, built-ins (G.2);
  `adopt` (mirror an existing tree: folders → branches, files → passports,
  deterministic placement) and `sync` (hash-diff incremental update) (G.3);
  curation stage with forest-level curation config and `on_curate` hooks —
  the only LLM-dependent stage, always skippable (G.4); media via the same
  converter contract: transcript/description is the body, the raw asset is
  the payload (G.5).
- **C.7.1 extension: initial `rows` at birth** `plant` of a dataset MAY
  carry `rows` per table, inserted **parameterized** (never SQL text) before
  `payload_hash` is computed. Bulk loads bypass neither the schema
  validation nor A.3.1 and avoid `tend`'s keyword scanner false-positives
  on arbitrary data.
- **Extension surface is edges-only (normative)**: plugins exist for what
  goes IN (converters, curation hooks). The primitives' semantics, budgets
  and security guards are NOT extensible. UIs/automations (dashboards,
  upload bots) are *clients* of the MCP server or the library they need
  no plugin API.
- New acceptance criterion **F.13** (adopt/sync end-to-end).

**Changelog v0.7 → v0.8 dataset birth: declarative schema in `plant`
(Phase 2, the living bank grows its own organs):**

`tend` (C.10) writes rows into datasets that already exist; until now no
primitive could *create* a dataset the `.db` was born only in offline
generators. v0.8 closes the loop so an agent can collect data (web, PDFs,
conversations), give it a structured home, and fill it all through the
primitives. Normative items:

- **C.7.1 Dataset planting** `plant` of a `type: dataset` node accepts an
  optional **declarative `schema`** object (tables → columns → types). The
  Vine generates the DDL itself (names regex-validated, types from an
  allowlist), creates the SQLite payload, computes `payload_hash`, and
  auto-generates the `## Query manual` body section from the schema. **No
  raw DDL ever comes from the model** creation-time structure is data,
  not SQL.
- **`tend` is unchanged**: DDL stays forbidden there forever. The separation
  is temporal creation (rare, structured, validated whole) vs operation
  (frequent, single-statement DML). `ALTER TABLE` after birth is out of
  scope (plant a new dataset and migrate, or wait for the Gardener).
- A.3.1 holds with zero new machinery: the payload is created on the
  filesystem, only the `.md` (with `payload` + `payload_hash`) is committed.
- New acceptance criterion **F.12** (schema validation, payload creation,
  auto manual, atomic rollback covered by tests).

**Changelog v0.6 → v0.7 `tend`: dataset writes (Phase 2 entry, the living
bank):**

`query` stays read-only by design; agent writes to dataset payloads get
their own primitive with a hard guard rail. New normative items:

- **C.10 `tend(id, sql)`** the 10th primitive: single-statement
  INSERT/UPDATE/DELETE on a `type:dataset` node's SQLite payload, with an
  audit commit of the node's `.md` (`payload_hash` refresh) the binary
  still never enters git (A.3.1 unchanged). Full contract in C.10.
- **Lint: payload drift warning** `vine validate` MUST warn when a node's
  `payload_hash` no longer matches the payload file's sha256 (completes the
  A.3 drift-detection promise; `tend` keeps the hash fresh, out-of-band
  edits become visible).
- New acceptance criterion **F.11** (tend guard rails + audit, covered by
  tests).

**Changelog v0.5 → v0.6 shout trigger measures the real trail (Part D):**

The shout never fired in practice: 39 successful hunts across the fixture and
the bench forest produced zero shortcut suggestions. Root cause: the trigger
reused `hops-to-banana`, which counts only `look`+`move` calls before the
FIRST `pick`/`query` but agents traverse deep chains with **pick chains**
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

**Changelog v0.4 → v0.5 canonical English vocabulary (normative):**

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
  the previous behavior `forest` is optional there so v0.3 clients are
  not broken.
- New acceptance criterion F.10 (registry: selection, lazy open, path safety,
  single-forest backward compatibility).

**Changelog v0.2 → v0.3:**

- New composite MCP tool **C.6c `harvest`**: zero-LLM, one-shot retrieval for
  clients that bring their own model. Fuses `locate` + `sniff` (RRF), returns
  ranked bananas with full body or matched sections plus exact snippets.
  It is an orchestration over existing primitives the nine primitive
  contracts are untouched.
- Three integration modes documented (C.6c intro): direct navigation
  (client LLM drives the primitives), harvest (one call, evidence back),
  concierge (local SLM hunts and answers). Configuration picks the default;
  the MCP client's LLM may choose per call.
- New acceptance criterion F.9 (harvest quality + budget).

**Changelog v0.1 → v0.2:**

- New read primitive **C.6b `sniff`** (the sniffer): literal search over node **bodies**, returning node + section + snippet. Complements `locate` (which stays restricted to curated metadata C.1 contract intact) covering the case "exact term buried in the body, invisible to summary/tags".
- **A.3.1 Binary payload policy**: binaries never enter the forest's Git Vine versions `.md` only (enforced at the commit layer); payloads are referenced by `payload` + `payload_hash` and excluded by the forest's `.gitignore`.
- Acceptance criterion F.1 updated to include C.6b; new criteria F.7 (sniff quality) and F.8 (payloads outside Git).
- Nothing else changes: every other contract is identical to v0.1 (which stays archived for history).

---

## Part A The Forest Dialect (`_meta/schema.md`)

`schema.md` is a living file inside the forest that declares the valid types. The Vine MUST validate every write (`plant`/`graft`) against it. The agent MAY read it via `look("_meta/schema")` to learn the dialect in 1 hop.

### A.1 Node types (`type`)

| `type` | Description | Payload | Harvest verb |
|---|---|---|---|
| `branch` | Index file (`_index.md`) of a folder | | `look` |
| `note` | Free-text knowledge (default banana) | | `pick` |
| `document` | Converted document (PDF/DOCX origin) | original in `_assets/` | `pick` |
| `dataset` | Tabular data | sibling SQLite (`.db`) | `query` |
| `entity` | Person, organization, product, place (subtype in `entity_kind`) | | `pick` |
| `concept` | Definition / technical term | | `pick` |
| `event` | Dated fact (meeting, decision, release) | | `pick` |
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
| `discovered-shortcut` | | The monkey's shout (created by `graft`, see Part C.8) |
| `succeeds` | `precedes` | Temporal order between events/versions |
| `supersedes` | `superseded-by` | Replacement (v0.58): the successor makes the predecessor history — the sweep suppresses the target by default (C.6c.4). `succeeds` orders moments without judging them; `supersedes` judges. |

Rules:
- A `rel` outside this table → `E_SCHEMA` error (the table grows by editing `schema.md`, never ad-hoc).
- **The refusal names the set that WOULD be accepted (v0.61).** The table
  above is the engine's default; the forest's own `_meta/schema.md` is the
  authority at runtime, so a rel the engine ships may legitimately be
  absent from a given forest a forest created before `supersedes` existed
  declares nine rels and refuses the tenth, which is this rule working as
  designed. What was not working is the refusal: `unknown rel
  'supersedes'`, with no `hint`, in the one case where listing the
  forest's declared rels answers the question completely and costs a
  sorted join. C.12's envelope requires an actionable hint on every
  refusal; `E_SCHEMA` for an undeclared `type` or `rel` MUST therefore name
  the forest's declared set (clipped, with the count, if it is long) and
  say where it is declared. Applies to `plant`, `graft` and every other
  path that validates against the dialect a caller must never have to
  guess a vocabulary the forest can simply state.
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
origin: string            # where this document came from (v0.57): one URI
                          # (path, URL, commit ref) — free-form, <= 2048
                          # chars, no whitespace or control characters
```

Rules:
- `id` is immutable. Renaming = creating a new node + `same-as` + tombstone (out of Phase 0 scope; renaming is forbidden in Phase 0).
- The parser MUST reject invalid frontmatter with `E_FRONTMATTER` and the field's path.
- `origin` (v0.57) is provenance toward the world outside the forest —
  the complement of `derived-from`, which is node↔node. It is mutable
  (`set_frontmatter`), returned by `look` whenever present, filterable in
  `scan`. The engine MUST NOT dereference it: it is an address a person
  or a reconciliation job follows, never a fetch instruction. One token:
  whitespace or control characters are `E_SCHEMA` (the same rule as J.8's
  `source_url`, for the same reason — an `origin` with a newline is prose
  wearing a field).

#### A.3.1 Binary payload policy (v0.2)

Binaries **never enter the forest's Git**. Normative:

1. The Vine MUST NOT version anything beyond `.md`: `plant`/`graft` stage only markdown files (hard guard at the commit layer, not convention).
2. The forest's `.gitignore` MUST exclude binary payloads (`*.db`, `*.sqlite`, `_assets/`), plus `_derived/` and `.vine.lock`.
3. The payload lives on the filesystem next to the node (or in external storage, in future phases) and the **node** versions only the reference: `payload` (name) + `payload_hash` (sha256). Binary drift is detected by hash, not diff.
4. Rationale: Git delta-compresses text, not binaries frequently updated payloads would blow up the repository. The versioned knowledge is the distilled layer (markdown); heavy data is referenced, not embedded.

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
- [[<id>]] <sub-branch summary>. <coverage>.

## Direct bananas
- [[<id>]] <summary copied from the banana's frontmatter>

## Cross trails
- <reason> → [[<id>]]
```

Rules:
- Entries replicate the child nodes' `summary` VERBATIM (the Gardener/Vine keeps sync; humans do not hand-edit these lines).
- Sync rewrites of a `## Sub-branches` entry MUST preserve the trailing coverage suffix (`. N bananas, M sub-branches.`) v0.13.
- A branch's frontmatter `summary` MAY be synthesized bottom-up by the Gardener from the children's entries (G.4.4) when the branch was born from ingest; hand-authored branch summaries are never rewritten.
- A branch with > 150 entries or > 3,000 tokens → `needs_split` flag for the Ranger.
- The master branch (`/_index.md`) MUST additionally contain a `## Landmarks` section (10-20 highest-degree nodes, with summary). The Ranger keeps it fresh mechanically (H.7, v0.13): top non-branch nodes by degree over the typed-edge table, idempotent, audited `.md`-only commit.

---

## Part B Identity, Trail and Addressing

- **Canonical ID:** path relative to the root, without extension. E.g.: `projects/mixerllm/architecture`.
- **Trail:** list of IDs from the root to the node. E.g.: `["_index", "projects/_index", "projects/mixerllm/_index", "projects/mixerllm/architecture"]`.
- Wikilinks in the body use `[[id]]` or `[[id|text]]`. The parser resolves `[[...]]` only against canonical IDs (no fuzzy match ambiguity is a Ranger lint error, not runtime guessing).

---

## Part C Primitive Contracts (Vine server, MCP)

Transport: MCP (stdio for dev; HTTP/SSE on Docker). All responses in JSON. Errors follow `{error: {code, message, hint}}` with codes `E_NOT_FOUND`, `E_SCHEMA`, `E_FRONTMATTER`, `E_READONLY`, `E_QUERY_FORBIDDEN`, `E_QUERY_INVALID` (v0.47, C.5.2), `E_TIMEOUT`, `E_LOCKED`, `E_ANCHORED` (v0.56, C.14), `E_MOVED` (v0.58, C.15 — HTTP 404, `data.moved_to` when the new address is in the reader's scope).

### C.0 Forest registry multi-forest serving (v0.4)

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

Cross-cutting principle: **every response MUST fit the declared token budget**. The Vine truncates with an explicit `"truncated": true` marker never silently.

### C.1 `locate(query: string, k: int = 5, scope: "all"|"branches"|"notes" = "all", type_filter?: string, include?: [string]) → LocateResult`

The **helicopter**: a location engine that drops the monkey in the region closest to the target it never starts from the trunk. RRF fusion of vector search (over summaries) + BM25 (over title, aliases, tags, summary). In Phase 0, MAY be BM25-only (SQLite FTS5); the interface does not change once vectors land.

The index covers **two levels**: bananas (leaves) and branches (regions every branch has its own summary, hence indexable). A branch result = **landing zone**: the monkey lands in the right region and navigates 1-2 hops with local context, instead of dropping onto a possibly wrong leaf. `scope: "branches"` is useful for broad questions ("what do we know about sales?"); `scope: "notes"` for pointed ones.

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
      "coverage": {"notes": 23, "branches": 4},
      "score": 0.91,
      "heat": 0.40
    },
    {
      "id": "projects/mixerllm/architecture",
      "kind": "note",
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

**`scope` is an enum (v0.54, C.12 rule 7):** a value outside
`all | branches | notes` is `E_SCHEMA` naming the parameter, the value
and the accepted set — never treated as `"all"`. A parameter that silently
falls back to a default turns a typo into a result the caller believes was
filtered.

**The metaphor stays in the prose (v0.56).** The wire's leaf token is
`notes` for the scope and `"note"` for every emitted `kind` field — the
consumer team's first call of a session failed on vocabulary the docs
taught and the wire refused, and then the wire answered `"kind": "banana"`
back. Charm aimed at a person, in a field only machines read, is friction
in both directions. `scope: "bananas"` remains accepted as a **deprecated
alias** for one minor version (same filter, no warning field — the hint
lives in the docs); the catalog MAY keep any internal spelling it likes,
because storage is not the wire. Prose, guides and the index-body headings
(`## Direct bananas`, A.5) keep the metaphor — they address people, and
A.5 headings are forest format, not API payload.

**`coverage` is counts (v0.54):** a branch result carries
`coverage: {"notes": n, "branches": m}` — machine fields carry numbers.
The prose rendering ("23 bananas, 4 sub-branches") remains what the index
*bodies* say (A.5); it does not cross into API payloads.

#### C.1.1 What the entry list says about itself (v0.52)

`locate` searches curated metadata and nothing else the split with
`sniff` is normative (C.6b) and stays exactly as it is. But that split is a
decision the caller cannot see, and its consequence is measurable: a term
present eight times in a body and absent from the summary returns
`{"results": [], "truncated": false}`, which is byte-identical to the answer
for a subject the forest has never heard of. An agent following the
documented order (`locate` → `look` → `pick`) reads that as "the forest does
not know" and answers from its own parameters, with the forest one call
away. The primitive was right and the caller was wrong for a reason the
primitive could have removed.

Three additions. All three are facts the catalog row already holds, so none
of them opens a file or costs a search:

1. **`body_tokens` on every result.** The same number `look` reports under
   `stats`, delivered at the moment the agent is choosing what to open
   which is the only moment it changes a decision. Chosen blind, the agent
   discovers the size of what it opened after paying for it, and under a
   tight budget takes the conservative wrong option: the small irrelevant
   node instead of the large correct one.
2. **`include: ["outline"]`.** Optional; adds each result's section headers
   from the same row. `look` remains the digest and nothing moves out of it;
   what disappears is the hop whose only purpose was learning which section
   to `pick`. The 800-token budget is unchanged and truncation stays
   explicit, so asking for outlines costs results at the tail never
   silence, and never a bigger response than the budget allows.
3. **`searched` and a `hint`, when and only when the list is empty.** An
   empty result carries `searched` (how many nodes' scent the search ran
   over) and a `hint` naming the search this primitive does **not** perform.
   Computed only on the empty path, because a caller holding results has
   already been told what it needed: the count answers "is there anything
   here at all", and a non-empty list answers it better.

`searched` is bounded by what the principal may see. Under a restricted
policy (J.3) it counts the nodes in scope the number they could reach by
walking never the forest's size, which would make an entry search a
size oracle for the region they were not granted.

A `hint` MUST NOT name a node, a term or anything from the forest's
content: it says which primitive searches bodies, and stops there.

**F.56 (acceptance).** Every `locate` result carries `body_tokens` equal to
what `look` reports for the same node under `stats`. `include: ["outline"]`
adds the section list without the response exceeding 800 tokens, and drops
results at the tail with `truncated: true` when it would. A query matching
nothing returns `searched` and a `hint` naming `sniff`; a query matching
something returns neither. Under a scoped policy, `searched` never exceeds
the number of nodes in scope. A term present in a body and absent from every
summary still returns no results the split with `sniff` is unchanged, and
the hint is what tells the caller so. Covered by tests.

#### C.1.2 The query is derived before it is searched (v0.70)

`locate` MUST derive search terms from `query` before building the FTS
match, by the same rule `harvest` uses (C.6c): drop the stopword set, keep
code-shaped tokens whatever their length and order them first, apply the
term cap. The raw sentence MUST NOT be the search.

**Rule 1 — the derivation is `harvest`'s, not a second one.** Two
derivations from one intent agree only where somebody compared them, and the
sweep already calls `locate`; a `locate` that read the question differently
from the `sniff` beside it would make one call contradict its own other
half.

**Rule 2 — an empty derivation falls back to the whole query.** A question
made entirely of grammar, and equally a single short lowercase token
("api", "sql", "ui"), derives to nothing. `locate` MUST then search the raw
tokens exactly as it did before this version. A search that answers nothing
because the *filter* consumed the question is indistinguishable, to the
caller, from a forest that does not hold the subject — C.1.1's failure,
manufactured. This rule is what keeps the change from creating the very
silence C.1.1 was written against.

**Rule 3 — nothing else moves.** Scope, window, type filter, budget,
`searched`, the `sniff` hint, the ranking, the hybrid fusion and every
response field are untouched. This section changes which terms are searched
and nothing about what happens to what is found.

**A stated cost.** The floor that removes grammar also removes lowercase
tokens shorter than four characters that are not code-shaped, so a query
like "erro sql no worker" searches `erro` and `worker` and drops the term
that discriminates. Measured on the corpus above the trade is positive
overall and this case is real: it is named here rather than left to be
rediscovered. Lowering the floor to three changed nothing on the labelled
set (the set contains no such question, which is the honest reason to leave
the floor alone rather than tune it against no evidence). A future set with
a short-technical-token class is what would settle it.

**F.147 (acceptance).** On a labelled set with headroom, `locate` scores no
worse than the raw-sentence behaviour it replaces, per class as well as in
aggregate. The comparison MUST be run on a set whose baseline is under 1.000
— a saturated set cannot refuse this change and MUST NOT be cited as having
approved it.

**F.148 (acceptance).** `locate("api")`, `locate("sql")` and a query made
only of stopwords return exactly what they returned before v0.70, byte for
byte. A query whose derivation is non-empty searches the derived terms.
Covered by tests.

### C.2 `look(id: string, fields?: [string]) → Digest`

The central operation. Hard budget: **<= 500 tokens**.

`fields` (optional): list of desired fields (e.g. `["summary", "edges_out"]`). When present, the response contains ONLY those fields (+ `id`, always). Typical use: a monkey in scan mode asking only for `summary` of several nodes cost drops from ~400 to ~70 tokens per look.

Response for a **banana** (`note`/`document`/`concept`/`entity`/`event`):

```json
{
  "id": "projects/mixerllm/architecture",
  "type": "document",
  "title": "MixerLLM Architecture",
  "summary": "...",
  "tags": ["inference", "slm"],
  "confidence": 1.0,
  "created": "2026-05-02",
  "updated": "2026-06-10",
  "source": "ingest",
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

Response for a **branch**: replaces `outline` with `children` (sub-branches and direct bananas, each with `id` + `summary`), `cross_trails`, and `coverage` as `{"notes": n, "branches": m}` counts (v0.54 — same rule as C.1).

Response for a **dataset**: includes `query_manual` (tables, key columns, 2-3 example_queries), `sample_rows` (<= 3 rows) and `notes` (C.2.1).

Rules:
- `edges_out`/`edges_in` capped at 12 each, ordered by heat desc; surplus indicated in `stats.degree`.
- `target_summary` MUST come truncated to 25 tokens (it's a neighbor's scent, not a full digest).
- `body_tokens` lets the agent estimate a `pick`'s cost before making it.
- **The passport says who and when (v0.56):** `created` and `source`
  are returned always, `aliases` whenever the node carries any, and
  `origin` whenever the node carries one (v0.57). All three
  were in every passport and in the indexed catalog since their birth;
  `look` just never said them, so the consumer team probed for provenance
  and concluded the product had none — and could not audit why an alias
  search hit. A forest shared between people and agents owes its reader
  "who asserted this, and when" for the same reason answers cite node
  ids. (Time of day and the writing principal are deliberately NOT here
  yet: frontmatter dates are day-precision, and the engine does not know
  the principal — that design lands with per-node history, next
  version.)
- **The budget clips in declared order, and it says so (v0.57).** Found
  in real use: a node with a 28-item outline answered `edges_out: []`,
  `edges_in: []` beside `stats.degree: 2` — the budget shrink emptied the
  edge lists (small, structural, irreplaceable in this response) while
  the outline (large, re-derivable via `pick`'s first page) stayed. The
  caller concluded the node was isolated and never called `move`: the
  graph, lost in silence, in the primitive the skill calls "where I read
  the passport". Every other cut in the product announces itself
  (`truncated`, `dropped`, `searched`); this one now does too. When the
  digest exceeds `BUDGET_LOOK`, fields are clipped in this order —
  `outline` first (big, and re-derivable through `pick`'s first page;
  whole items from the tail), then `children`, then
  `edges_in`/`edges_out`, and a dataset's `sample_rows` only as the last
  resort (its digest exists to feed `query`) — and **every field the
  budget touched is named in `truncated_fields`** beside the existing
  `truncated: true`. A caller who sees `edges_out: []` WITHOUT
  `"edges_out" in truncated_fields` may finally trust the emptiness;
  `stats.degree` remains the arithmetic truth either way. `fields=`
  remains the escape: a digest asked to carry less rarely clips at all.

#### C.2.1 `## Notes` what a person teaches the agent (v0.46)

A dataset is the one node type whose contents no text primitive can see:
`locate` reads curated metadata, `sniff` reads bodies, and the facts live
in a `.db`. G.2.3's map fixed *structure* the tables, the columns, three
rows. What it cannot supply is **meaning**: that `total_invoice` is in USD
while `exchange_value` is in BRL, that `status` uses one-letter codes,
that direct imports are the rows where `lessee` is null, or which join is
the one that answers the question people actually ask. Nor can it supply
*shape*: that `total_invoice` is TEXT holding `USD 54.607,56`, so
`SUM(total_invoice)` is `0.0` and looks like an answer.

That knowledge exists only in somebody's head, and an agent writing SQL
without it writes SQL that runs and answers wrongly the worst failure
this system can produce, because it is indistinguishable from success.

A dataset passport MAY therefore carry a **`## Notes`** section.

Normative:

1. **It is the operator's, and nothing else writes it.** The Gardener
   rewrites the two generated sections and only those (G.2.3 rule 4), so
   `## Notes` survives every `sync`, every re-adoption and every payload
   replacement. Curation MUST NOT write it either: a model's guess about
   what a column means is exactly what this section exists to correct.
2. **`look` MUST return it**, as `notes`, for `type: dataset`. This is the
   whole point and not a convenience: the path an agent takes to a dataset
   is `look` then `query` a note it can only reach through `pick` is a
   note it will not read, and a teaching surface nobody reads is worse
   than none, because somebody maintains it.
3. **Bounded, and truncated out loud.** `notes` carries its own budget
   (200 tokens) inside `look`'s 500, clipped with the C.6 rule a
   `truncated` marker, never a silent cut. It is clipped **before** the
   digest's overall budget check, and it outranks `sample_rows` when the
   digest still has to shed: three generated rows are cheaper to lose
   than a sentence a person wrote on purpose.
4. **Written through `graft` like every other body edit** (C.8:
   `replace_section`, or `append_section` the first time). There is no
   second write path, no side file and no store it is part of the node,
   so it is versioned, attributed and committed exactly as its summary is.
5. **Datasets only, for now.** On every other node type the body itself is
   reachable through `pick` and searchable through `sniff`, so a section
   promoted into `look` would spend the tightest budget in the system on
   something already available. A `## Notes` heading on a note is an
   ordinary section and stays one.
6. **The notes travel with the dataset, on every path (v0.47).** Stated
   first for `harvest` (v0.46) and now as the general rule it always was:
   **any material a host assembles for a model MUST carry the `notes` of
   every dataset present in that material.** Not only `look`, which is one
   primitive the model may or may not call.

   The failure this fixes was observed. The sweep is `locate` + `sniff` +
   matched sections and never looks at anything, so v0.46 attached the
   notes to its dataset items. The walk (J.10.5) enters through `locate`,
   whose result is curated metadata and carries no body and a model that
   goes from that entry straight to `query`, which is the natural move on a
   dataset, never calls `look` and never sees a word the operator wrote. In
   a measured run the mode with *more* freedom was the mode with *less*
   information, which is the opposite of the intent, and the operator's
   reasonable reading was that the agent had ignored them.

   The attachment is **unconditional**: whether the section happens to
   share vocabulary with today's question is not a reason to withhold a
   person's instructions about how to read the data. A teaching that
   depends on the agent choosing to be taught is not a teaching surface,
   and a third answer path added later inherits this rule rather than
   rediscovering it.

*Informative:* this is the human half of the same idea the map is the
machine half of. The map says what is there; the notes say what it means.

#### C.2.2 A missing payload is a fact about the payload (v0.61)

`look` builds a dataset's `query_manual` and `sample_rows` by opening the
`.db`, and an absent file raised `E_NOT_FOUND` for the **whole digest**.
Everything else in that digest title, summary, tags, `created`,
`origin`, the edges, `## Notes` comes from the passport and the catalog
and never depended on the payload. So a node that `scan` lists and
`locate` ranks was unreadable through the one primitive whose job is to
read passports, and the reader was told the *node* was not found. That is
the most confusing pair of answers the surface can give about one id, and
it was observed in the field on both datasets of a live forest.

1. **The digest degrades; it does not vanish.** When a `type: dataset`
   node's local payload is absent, `look` returns the passport as always,
   OMITS `query_manual` and `sample_rows`, and carries
   **`payload_missing: true`**. `notes` is unaffected: it is read from the
   body, and what a person wrote about the data outlives the file.
2. **It is stated, never inferred.** A caller MUST be able to tell "this
   dataset has no sample rows to show" from "this dataset's file is gone".
   The flag is the difference, and its absence means the payload was
   there.
3. **Every other primitive keeps refusing.** `query` and `tend` name the
   missing payload with `E_NOT_FOUND` exactly as before: they cannot do
   their work without the file, and inventing an empty result set would be
   the silent-wrong-answer failure this document exists to prevent.
   Degrading is for the digest, whose content is the passport.
4. **A remote payload is not this case.** G.9's fetch-on-first-use has its
   own failures and its own errors; `payload_missing` is about a LOCAL
   file the passport names and the filesystem does not have.
5. **The condition is countable in one call** `coverage` reports it per
   root (C.17 rule 11), so an operator learns the size of the damage
   without walking the forest one `E_NOT_FOUND` at a time.

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

**`direction` is an enum (v0.54, C.12 rule 7):** a value outside
`out | in | both` is `E_SCHEMA` naming the parameter, the value and the
accepted set. It MUST NOT answer an empty neighbour list: on a node with
`degree > 0`, `{"neighbors": []}` for a mistyped direction is
byte-identical to an isolated node, and the observed mistake —
`direction="all"`, borrowed from `locate`'s `scope` vocabulary — is one
every integrator makes once. The refusal's hint names `both` as this
primitive's word for every direction. The MCP tool schema declares the
same enum, so the mistake dies at validation on that surface too.

### C.4 `pick(id: string, section?: string | [string], after?: string) → Content`

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
- A single `section` string returns the shape above, **to the byte** what it returned before v0.56.

#### C.4.1 A document is read back whole, in pages (v0.56)

`pick` on a body over 4,000 tokens used to return an empty body, the
outline and a hint. The ceiling was right — it exists so one call cannot
flood a walk — but the dead end was not: the consumer team measured their
own reports at 4,855 tokens and found that rereading a document they had
just planted cost 28 `section=` calls. While that is true, the local
`.md` copy is cheaper than the forest, and it survives. The body of one
large node is the same problem as one large forest, and it gets the same
answer the C.6.2 enumeration cursor got: pages, an `after` cursor, and
totals.

Normative:

1. **The page unit is the paragraph block.** The body is split at blank-
   line boundaries into contiguous segments; every page is a
   concatenation of whole segments and is a **byte-exact substring** of
   the body. Pages fetched in order and concatenated reproduce the body
   byte-identically — that is F.80, and it is the property that lets an
   agent trust the reassembly.
2. **The cursor is `scan`'s idiom.** An over-budget read (no `section`)
   returns the FIRST page within the 4,000-token budget plus
   `truncated: true`, `next` (opaque cursor naming the last block
   delivered), `returned` and `total` (block counts) and a hint teaching
   `after=`. Passing `after` resumes; an unknown or malformed cursor is
   `E_SCHEMA` naming it. A body within budget and no `after` returns the
   pre-v0.56 shape unchanged.
3. **Progress is guaranteed, and so is the flag.** A single block wider
   than the whole budget arrives alone, hard-cut, with `cut: true` beside
   `truncated` — and `next` still advances past it. Without the advance
   the cursor parks forever on the block; without the flag the cut is
   silent, which C.6's rule forbids.
4. **`section` accepts a list** (≤ 10 names, one call, one 4,000-token
   budget — C.11's rule, never per-item times count). The result carries
   `sections: [{section, header, body, body_tokens}]` in request order —
   `section` echoes the name as asked, `header` (v0.57) the header line
   that actually matched, because matching is by prefix (C.4) and a
   result identified only by order is a result the caller re-derives —
   plus
   `missing` (names no header matched — with the outline in the hint) and
   `dropped` (names whose content did not fit; whole sections drop from
   the tail and are named). Every requested name lands in exactly one of
   the three. A one-element list returns a list; a bare string returns
   the old single shape, to the byte.
5. **`after` and `section` never combine** — two addressing schemes in
   one call is `E_SCHEMA`. `after` pages the whole body; `section`
   addresses pieces of it by name.

### C.5 `query(id: string, sql: string) → Rows`

- Preconditions: node `type: dataset`, `payload_type: sqlite`.
- Validation: a single statement only; MUST start with `SELECT` or `WITH`; forbidden: `ATTACH`, `PRAGMA` in both its spellings the keyword and the `pragma_*` table-valued functions (v0.50) and `INSERT/UPDATE/DELETE/DROP/ALTER` → `E_QUERY_FORBIDDEN`. Connection opened read-only (`mode=ro`).
- Forced `LIMIT`: if absent, injects `LIMIT 200`. 2s timeout → `E_TIMEOUT`.
- **A name that is not there MUST say what is (v0.46).** `no such table`
  and `no such column` are how generated SQL usually fails an agent that
  has not `look`ed yet guesses the table from the node's id, which is a
  reasonable guess and normally wrong. The error's `hint` therefore
  carries the dataset's actual table names (or, for a column, the columns
  of its tables). Without it the caller spends a whole extra hop, and a
  model call, discovering something the failing call already had open. The
  lookup is best effort: it runs while an error is being raised and MUST
  NOT be able to replace it.

```json
{
  "columns": ["region", "total"],
  "rows": [["Southeast", 1250000.0], ["South", 740000.0]],
  "row_count": 5,
  "limited": false,
  "elapsed_ms": 3
}
```

Columnar format (`columns` + `rows` as arrays) not objects repeating the keys; saves ~40% of the tokens.

##### C.5.1 The result is budgeted, and `columns` is not (normative, v0.47)

`query` was the only read primitive with no token bound. It had a row cap
— the injected `LIMIT 200` and a row cap is not a token cap: width is
unbounded. Measured on a 141-column ERP export, `SELECT *` returned
**86,929 tokens for 15 rows** and **429,397 for all 129**. Fed to a model
that re-sends its history each turn, one such call was the whole cost of a
walk.

1. **`BUDGET_QUERY` = 2000 tokens**, applied to the response the same way
   every other budget is applied (A.4): whole items are dropped from the
   tail and `truncated: true` is set. Never a sliced row, never a silent
   cut. It sits below `pick`'s 4000 deliberately a body is read once,
   while a result enters a loop that carries it forward.
2. **`columns` is never dropped.** It is the smallest useful thing in the
   response and the only part that tells the caller how to ask again. A
   result whose every row was dropped therefore still answers: *these are
   the columns your statement produces, and none of the rows fit*. That is
   a map back, and it costs a few hundred tokens against the tens of
   thousands refused.
3. **`row_count` is what came back**, and `truncated` is what says more
   existed. The two flags are not interchangeable and both may be true:
   `limited` means the injected `LIMIT 200` was reached and the *query*
   matched more; `truncated` means the token budget dropped rows the query
   *returned*. A caller that cannot tell them apart cannot tell "narrow
   your filter" from "narrow your projection".
4. **The hint names the way out.** When rows were dropped, the hint MUST
   state the column count and say to name the columns needed. When *every*
   row was dropped it is the entire useful payload, so it MUST also give
   the per-row cost. Aggregates are unaffected by construction `SELECT
   SUM(x)` is one short row which is the point: the bound bites exactly
   the statements that should have been narrower, and the caller finds
   that out in one hop instead of in a context window.
5. **Nothing here is a refusal.** The statement ran; the payload did not
   fit. `truncated` is the same contract as everywhere else in this spec,
   and a caller MUST NOT read it as absence the C.6/C.6b rule that
   `truncated: true` never means "does not exist" applies unchanged.

##### C.5.2 Invalid is not forbidden (normative, v0.47)

Every SQLite failure surfaced as `E_QUERY_FORBIDDEN`, the code the guard
raises for attempting a write. So `no such table: report_2026` a
caller's typo, on a dataset they are allowed to read was reported with
the vocabulary of a policy denial, in the response, in the console and in
the audit trail. An operator reading a walk saw two locked doors where the
engine had in fact answered both questions.

`E_QUERY_INVALID` is therefore its own code, for statements that pass the
guard and fail in SQLite: unknown table or column, syntax error, wrong
argument count. `E_QUERY_FORBIDDEN` keeps exactly what the guard decides —
not a dataset, not a single statement, wrong leading keyword, forbidden
keyword, `UPDATE`/`DELETE` without `WHERE` (C.10), a remote payload under
`tend` (G.9). The split applies to `query` and `tend` alike; one of the two
kept honest would be worse than neither, because then the code would mean
different things per primitive.

Over HTTP (J.4) `E_QUERY_INVALID` is **400** and `E_QUERY_FORBIDDEN` stays
**403**. The distinction is the ordinary one and it is worth having: 403
says the principal may not, 400 says the request was wrong. A client
retrying on 403 is confused; a client retrying on 400 with a corrected
statement is doing the right thing, and until now it could not tell which
it was holding.

The C.5 name hint is unchanged and is now carried by `E_QUERY_INVALID`,
where it always belonged.

**The one case where the two halves meet (v0.50).** A table allow-list is
enforced by SQLite (C.5.3), so its refusal is *noticed* by SQLite and
*decided* by the grant. It keeps `E_QUERY_FORBIDDEN` and **403**: the
principal may not, which is precisely what 403 says, and a client that
corrects the statement will be refused again. The message MUST state that
the statement reaches outside the allow-list and MUST NOT name the table
it stopped at otherwise the refusal answers "does this table exist?"
for everything the scope withholds, one guess at a time.

##### C.5.3 The table allow-list is decided by the database (normative, v0.50)

J.3 lets a grant narrow a dataset to some of its tables, and requires that
narrowing to be checked "against the parsed statement". This section says
what does the parsing: **SQLite itself**, through its authorizer, consulted
while the statement is prepared.

The rule and its reason are the same sentence. Deciding what a statement
touches by reading its text means keeping a second parser, and two parsers
agree only where somebody thought to compare them; for SQL that comparison
has no natural end, and being wrong about it is silent. The authorizer is
asked once per table and column the statement **actually** touches, so a
subquery, a CTE, a view and a table-valued function are the same question,
answered by the component that resolves them.

Normative consequences:

1. When a grant carries a table allow-list for a dataset, `query` MUST
   enforce it through the authorizer. An implementation MAY also pre-read
   the statement to produce a friendlier message naming the offending
   table it MUST NOT rely on that reading as the control.
2. `SQLITE_READ` on a table outside the list is a refusal, as are the
   write actions. Both matter, and on the write path (C.10) the read
   action is the one that matters most: a statement may write only where
   it is permitted and still take its value from a table it may not read.
   A scope that governs the destination and ignores the source is not a
   scope.
3. Under an allow-list, the schema is not readable either. SQLite's own
   internal tables and the `pragma_*` functions describe every table there
   is, which is the map to exactly what the grant withholds.
4. The C.5 name hint MUST be filtered by the allow-list, and MUST be
   omitted entirely when nothing permitted remains. A misspelling is not a
   reason to answer with an inventory of what is being withheld.
5. The allow-list travels as a **host-supplied** argument. The engine
   exposes it keyword-only and the scoped surface supplies it from the
   grant; it MUST NOT be reachable from the wire, because a narrowing a
   caller can set is a narrowing a caller can omit. (Same construction as
   G.2.5's adoption flag.)

Nothing here changes what a permitted statement returns, or its budget
(C.5.1), or its timeout. An ungoverned principal one whose grant carries
no table list is unaffected: no authorizer is installed for them.

### C.6 `scan(parent_id: string, filter?: Filter, fields?: [string], recursive: bool = false, limit: int = 50, after?: string) → [PartialNode]`

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

Response: list of partial nodes (only the requested `fields`), ordered by `heat` desc. Budget: <= 800 tokens, with explicit `truncated`. Default `fields`: `id`, `type`, `summary`, `body_tokens` (v0.54 — the cost of opening a node is known wherever a node is offered, C.1.1's rule).

Canonical use case: "I only want the sales datasets updated this quarter" → 1 call, ~3ms, ~200 tokens instead of descending the hierarchy opening indexes.

**`fields` is a stated set (v0.54, C.12 rule 7).** The accepted names are
the catalog's caller-facing columns — `id`, `kind`, `type`, `title`,
`summary`, `tags`, `aliases`, `created`, `updated`, `confidence`, `source`,
`entity_kind`, `payload_type`, `parent`, `trail`, `coverage`,
`body_tokens`, `outline`, `heat` — and an unknown name is `E_SCHEMA` naming
it and the set. Before this, an unknown field was silently omitted from
every item, which reads exactly like "that field is empty on every node".
`payload`, `payload_hash` and the catalog's internal columns are not in the
set: a payload location is J.14's business, not a listing's.

**Provenance is a filter (v0.56).** `filter` matches any caller-facing
catalog column by equality (plus the comparative keys above), and that
includes `source` — so "what did the agents write here?" is
`scan(_index, filter={"source": "agent"}, recursive=true)`, one
enumeration. This worked mechanically before v0.56; it is now stated,
taught by the skill, and covered by F.82, because a capability nobody can
discover is a capability the product does not have (the C.1.1 lesson,
applied to itself).

**Where a node came from is a filter too (v0.59).** `origin` (A.3) is a
URI, and two different questions are asked of it: *which node is this
exact file?* and *what came out of that directory?* The first is the
equality match every catalog column already has. The second is
`origin_prefix`, matching when the node's `origin` starts with the given
string — the reconciliation filter the consumer team asked for, and the
one that makes a partial ingest visible
(`scan(_index, filter={"origin_prefix": "file:///srv/dump/tasks/"},
recursive=true)`). Both keys stay: collapsing them into one prefix match
would delete the ability to ask about a single file, which is the finer
of the two questions. A node with no `origin` matches neither. The prefix
a caller passes is the one `coverage` publishes per root (C.17 rule 4) —
there is no arithmetic between finding a source and listing it.

**`kind` speaks the wire's spelling (v0.56, C.1's rule).** Every emitted
`kind` is `note` or `branch`, and a `kind` filter takes those same
values — the filter MUST match what the field emits, whatever the catalog
stores internally. A filter that only matches the storage spelling would
make `filter={"kind": "note"}` silently empty, which is C.12's forbidden
lie.

**A system node says so (v0.54).** An item whose id lives under `_meta/`
carries `system: true`. `_meta/schema.md` is a child of no branch, so it
appears in a recursive `scan` and in no `look` — two tools answering "what
is here" with different counts and no explanation. The marker is the
explanation; nothing is hidden, because a dialect an agent may read is not
a secret, only not content.

#### C.6.2 The forest is enumerable (v0.54)

`truncated: true` used to be a dead end: `limit` could only shrink the
page, the budget cut the rest, and nothing said what was dropped, how much
existed, or how to get it. On a real corpus (1,877 nodes) that made `scan`
constitutionally unable to answer "did the ingest complete?", "what is in
this forest?" — the questions an inventory exists for. `pick` batches
already solved this shape the right way (C.11 names what it drops); `scan`
now says what it left out and how to continue:

1. **`total` and `returned`, on every response.** `total` is what the
   requested scope holds — parent + `recursive` + `filter` + window,
   counted before any cut; `returned` is what this response carries after
   all of them. The two numbers are the size of what was NOT received,
   which is the fact a caller cannot otherwise learn.
2. **`after` — an id cursor.** When present, results come in id order,
   strictly after the cursor (`after: ""` starts at the beginning), and a
   page that left something behind carries `next`: the last id returned,
   which is exactly what the next call's `after` takes. Enumeration is
   complete and duplicate-free over a stable forest; nodes planted behind
   the cursor while a walk is in flight are the next walk's to find.
3. **One order per mode.** `after` selects id order; without it the heat
   order of every previous version is byte-identical. `after` beside
   `toward`/`gauntlet` is `E_SCHEMA`: an enumeration has one order, and a
   ranked page cannot be resumed.
4. **The budget is part of the contract, stated where the caller reads:**
   <= 800 tokens, <= 50 items per page, whichever cuts first — and neither
   cut is silent anymore, because `total`/`returned`/`next` survive both.
5. **Under a policy, the counts are the principal's own (J.3).** The
   scope's predicate is applied where candidates are chosen — same
   construction as C.13.3 and `searched` — so `total` counts nodes in
   scope, never the forest (a finer size oracle than `locate` could ever
   be), and the cursor walks the principal's nodes without skipping what
   a post-hoc trim would have dropped.

#### C.6.1 The Catalog (`_derived/catalog.db`)

SQLite in the derived layer with one row per forest node: every frontmatter field + trail + degree + heat. Rebuildable from scratch by a full scan (`vine reindex`); updated incrementally on every `plant`/`graft`. It's what serves `scan()` and `locate`'s lexical side (FTS5 over title/aliases/tags/summary in the same base). **Not the source of truth** if it diverges from the files, the files win and the catalog rebuilds.

**The body hash (normative, v0.40).** Each row also carries
`body_hash`: the digest of the node's body **as `sniff` would scan it**
(the raw markdown body, frontmatter excluded), written on every upsert
and rebuilt by `reindex`. It exists so a memoized scan (C.6b.1) can
decide validity by content rather than by clock, and it is the same
disposable-layer bargain as the rest of this file: a divergence is
repaired by `reindex`, never by trusting the catalog over the files. A
row whose `body_hash` is absent (a catalog written before this version)
MUST behave as a cache miss, never as a match an empty hash that
compared equal would serve stale snippets forever.

**Derived storage is tuned for reads, not for durability (normative,
v0.29).** Every read primitive deposits pheromone (Part D, E.2), so every
read is also a commit in SQLite's default rollback mode, a journal
created, fsynced and deleted per call. Databases under `_derived/`
(`catalog.db`, `trails.db`) MUST therefore open in WAL with
`synchronous=NORMAL`.

The durability this trades away is durability the derived layer does not
have to begin with: the `.md` files are the source of truth, `_derived/` is
disposable by definition, and the repair for any inconsistency is already
`reindex`. A crash costs the tail the last few heat deposits, which
evaporate on a schedule anyway (H.1) and never the corpus. WAL remains
crash-safe; what is lost is recency, and recency is exactly what heat is
allowed to lose.

Best effort, and that is normative too: a filesystem that cannot support
WAL (a network mount with no shared memory) MUST keep the mode it had and
keep working. A forest that refused to open because it could not be made
faster would have traded the whole feature for part of one.

**Warming (normative, v0.29).** A Vine MUST expose `warm()`: fault in the
pages a search will want, through the storage layer only. It MUST NOT go
through a primitive that would append a trace event and deposit heat, and
a server that warmed itself through `locate` would be forging the pheromone
the Ranger later reads as evidence of where callers went. It MUST NOT read
bodies; that is the whole corpus off disk, which is a different trade and
not this one. Opening a forest warms it.

### C.6b `sniff(terms: string | [string], scope?: string, k: int = 5, type_filter?: string) → SniffResult`

The **sniffer**: **literal** search over nodes' markdown bodies, returning node + section + occurrence snippet. It complements `locate`: the helicopter flies over curated metadata (summary/tags/title); the sniffer goes down to ground level and follows the trail of an exact term error code, proper name, invoice number, identifier that nobody bothered (or was obligated) to lift into the summary. The contract split is normative: **`locate` MUST NOT index bodies; `sniff` MUST NOT query curated metadata** (except to display the result).

Parameters:

- `terms`: 1 to 8 **literal** terms (a single string is promoted to a 1-item list). Substring matching, case- and diacritic-insensitive (NFD, combining marks stripped). A term with a space = exact phrase. A normalized term with < 2 characters → `E_SCHEMA`. **Regex is NOT accepted** (Phase 0): SLMs write fragile regex, and arbitrary regex opens unpredictable cost; literal terms give 95% of the value with a simple contract.
- `scope` (optional): id of **any node**. A branch (`sales/_index` or `sales`) restricts the search to the matching physical subtree; a banana restricts it to that single node's body (grep-within-node the natural chaining after a `locate`/`look` that already found the target). Without `scope`, the whole forest. Nonexistent node → `E_NOT_FOUND`.
- `k`: max nodes in the result (default 5, cap 20).
- `type_filter`: as in `locate`.

Search semantics:

- Scans **only the body** of `.md` files (frontmatter excluded; `_derived`, `_assets` and binary payloads ignored).
- A node matches when **at least one** term occurs in the body; nodes matching **more distinct terms** rank first (AND-preferred, OR-tolerant).
- `match` = the occurrence's line, attributed to the section (H2/H3 header) containing it. Max of **3 matches per node** in the response (`match_count` reports the total; surplus flagged by `truncated_matches: true`).
- `snippet` = a window of the line centered on the first occurrence, truncated to ~25 tokens.

Ordering (v0.52): `score = strength x density x (1 + alpha*heat)`, where
`strength = matched_terms/requested_terms` (unchanged) and
`density = 1 + beta*log2(match_count)`, beta default 0.15 so ten
occurrences of a term outweigh a maximal pheromone bonus, and a single
occurrence changes nothing. `match_count` MUST NOT be left as the tie-break
alone: across literal hits `strength` is frequently constant, which leaves
`heat` as the only term that separates them and makes the ranking of a body
search the ranking of the traversal that came before it. Measured on a
served forest, `sniff(["421", "Host"])` put a branch index holding **one**
occurrence above the note holding **ten**.

**A pointer never outranks what it points at (v0.52).** An index node
(`_index`, `<branch>/_index`) carries the summary of every child, so it
matches nearly any term somebody asks about, and it accumulates heat by
being the way through to everything under it. A term found inside it is
evidence about a child. An index node therefore ranks **below every
non-index node in the same result set**, whatever its score. It is not
removed a match in an index is still a way in and its `score` is
reported unchanged, because a score adjusted to force an order is a number
that lies, while an order stated in the contract is one the caller can
read. This is the same judgement C.6c.2 already made when it refused to
refine an index node's matches.

**The demotion is visible (v0.54).** A demoted hit carries
`demoted: true` beside its unadjusted `score`. An order stated only in the
contract is invisible on the wire: the natural move for any client that
fuses result sets is to re-sort by `score`, and doing so silently undid
the rule above — the response gave it no way to know a rule existed. The
marker says "this item's position is deliberate"; the score keeps telling
the truth.

**`body_tokens` on every result (v0.54).** Same field, same source and
same reason as C.1.1 rule 1: the row is already in hand, and the caller
is choosing what to open.

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
      "body_tokens": 612,
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

1. Question contains an exact/rare term → `sniff` directly: lands in the right section and harvests with `pick(id, section)` cuts hops-to-banana.
2. Conceptual question → `locate` (unchanged).
3. Chained: `locate` finds the region, `sniff(terms, scope=branch)` hunts the snippet within it.

Phase 0 implementation: direct file scan on every call (grep-like, no new index) always fresh by construction, no extra derived state. MAY gain an index (body FTS5 in a separate table) in a future phase **with no interface change**, as long as the contract split with `locate` holds.

#### C.6b.1 The memoized scan (`_derived`, v0.40)

`_sniff_body(body, term)` is a **pure function**: the same body and the
same folded term yield the same lines, always. A Vine therefore MAY
memoize it in the derived layer. The permission is narrow and the
following are normative.

- **Identical output.** A memoized `sniff` MUST return exactly what the
  direct scan returns same nodes, same sections, same line numbers,
  same snippets, same `match_count` and `truncated_matches`, same
  ordering. This is memoization of the scan, **not** its replacement by
  an index: no tokenization, no stemming, no analyzer. C.6b's literal
  substring semantics and the `locate`/`sniff` split are untouched, and
  any divergence is a defect, not a tuning choice.
- **Validity is the body hash** (C.6.1). An entry is usable while the
  node's current `body_hash` equals the hash recorded with the entry.
  Absent hash on either side = miss. Timestamps MUST NOT be used for
  this: `mtime` granularity is coarse and platform-dependent and clocks
  move backwards.
- **Non-matches are recorded.** An entry MUST distinguish "this node was
  scanned for this term and matched nothing" from "this node was never
  scanned for this term". Without the negative, every non-matching node —
  nearly the whole forest is rescanned on every call.
- **Line granularity.** The scan emits one match per *line*, whose
  snippet is centred on the leftmost position among the terms that hit
  that line. A per-term memo MUST therefore record, per matching line,
  enough to rebuild that combined result (the line's number, its section,
  the term's position in it, and the line's text) storing the rendered
  snippet alone is wrong, because a second term in the same line moves
  the window. Entries MUST record the **complete** line list: the
  3-matches-per-node cap of C.6b is applied when answering, and
  `match_count`/`truncated_matches` are computed before it.
- **Scope-independent.** An entry is a fact about one node and one term,
  so it is reusable by any later call whatever its `scope`, `k` or
  `type_filter`, and a scoped scan populates entries a global scan can
  later use.
- **Ranking is never memoized.** `heat`, `score` and ordering are
  query-time state (Part D) and MUST be recomputed on every call. An
  entry that froze the ranking would make the pheromone unobservable
  through the primitive that reads it most.
- **A remembered non-match is a count, not a row (v0.59).** The memo
  records non-matches precisely so the ~95% of a forest that holds none of
  the terms costs nothing but a lookup — and the first implementation then
  carried every one of those rows out of the database and deserialized it,
  to discover the list was empty. The negative MUST still be recorded (the
  rule above is unchanged; without it every non-matching node is rescanned
  forever), but a read MUST NOT be proportional to it. What a call needs
  from the memo is the matching lines and the set of nodes the memo does
  **not** cover — the second being the cheap half to ask for, and empty on
  a warm forest. Everything else in scope is covered and matched nothing,
  which is one count. Concretely: the rows fetched, the records
  deserialized and the catalog rows loaded are all proportional to the
  MATCHES, while `scanned_nodes` keeps counting every node the scan
  covered, because the honesty of that number is the reason it exists.
  A node covered for a term and absent from its matches IS the empty
  record, inferred rather than transferred; recombining empty line lists
  produces the empty match list, which is the result the scan skips.
- **Heat for the candidates is one statement (v0.59).** Ranking is never
  memoized — the rule above stands and is not weakened — but recomputing
  it MUST NOT mean one SQLite round trip per node. A `sniff` whose terms
  are common words matched most of a 1,911-node forest and asked for heat
  **1,945 times**, which is the same mistake C.13.3 named for counting:
  the work belongs in one query, not in a Python loop around one.
- **A snippet is rendered for a result that is answered (v0.59).** The
  windowing rule of C.6b (centred on the leftmost hit in the line) is
  unchanged, and `match_count`/`truncated_matches` are still computed
  over the **complete** line list before any cap. What changes is when the
  window is computed: a call that returns at most `k` nodes of at most 3
  matches each MUST NOT render thousands of snippet windows it will
  discard. Rendering happens after the ranking and the cut.
- **What stays proportional to the matches, and what cannot (v0.59).** With
  the three rules above, a warm `sniff` for a term that lives in a handful
  of bodies touches a handful of bodies' worth of work, whatever the size
  of the forest — measured on a 1,911-node corpus, 10.9 ms to **1.5 ms**.
  A term that genuinely appears in most of the corpus is a different
  question: every matching node must be counted and ranked, so that call is
  proportional to the matches and there is no honest way around it. This
  document states the distinction rather than promising a single number,
  because a reader who benchmarks the second case and finds it unchanged
  should know that is the contract and not a regression.
- **The fold is a table, not a loop (v0.62).** C.6b matches on a folded
  form lowercased, diacritics stripped to the base character of the NFD
  decomposition, length preserved so a position maps back to the original
  line. That is a per-character mapping, and a per-character mapping
  implemented as a Python loop over the text costs more than reading the
  text from disk: measured, **387 ms to fold 11.9 MB against 31 ms to read
  it**. The mapping MUST be applied in one pass by the runtime
  (`str.translate` against a precomputed table; ASCII text folds by
  `str.lower()`, which for ASCII *is* the definition). Two constraints
  make this a memoization and not a change of meaning. The table MUST
  cover every code point the fold can change **this is not the BMP**:
  cased scripts live in the SMP (Deseret, Adlam, Osage, Vithkuqi, Warang
  Citi, Medefaidrin) and CJK Compatibility Ideographs decompose as high as
  U+2FA1D, so a BMP-sized table silently stops folding six living scripts.
  And the limit MUST be pinned by a check against the Unicode version in
  use, so a later version that raises it fails loudly rather than narrowing
  the match in silence. The table MAY be built on first use it is state
  no write primitive needs.
- **A frontmatter marker is read in the frontmatter (v0.62).** G.7's
  `content: cached|reference` says where a node's FLESH lives. It is
  frontmatter by definition, and looking for it in the whole file was a
  scan of the corpus to answer a question about its first few lines: **71
  ms** of the 629 above, and 4 ms when asked of the frontmatter alone. The
  scan MUST find the boundary between frontmatter and body once and ask
  each half only what that half can answer. The old reading also treated a
  body that merely *quotes* the marker as a node whose body lives
  elsewhere; that was harmless (an inline node resolves to its own body)
  and it is gone.
- **What a cold scan costs, and what it does not (v0.62).** A `sniff` for a
  term no entry covers MUST scan every body in scope there is no honest
  alternative inside a literal contract, and the memo cannot pre-compute an
  answer to a question nobody has asked. What this document now records is
  what that costs when the implementation is not wasteful, so a later
  proposal is measured against it rather than against an artifact.
  On 1,902 nodes / 11.9 MB, CPU time, medians of five interleaved runs:

  | cold `sniff` | before v0.62 | v0.62 |
  |---|---|---|
  | term matches nothing, ASCII bodies | 629 ms | **133 ms** |
  | term matches nothing, accented bodies | 612 ms | **258 ms** |
  | term matches, ASCII bodies | 726 ms | **244 ms** |
  | term matches, accented bodies | 731 ms | **379 ms** |
  | sweep (`harvest`), cold | 933 ms | **448 ms** |

  Accented bodies cost more and MUST be expected to: they cannot take the
  ASCII path, so every character passes through the table. A warm `sniff`
  is unchanged by all of this it never folds and the v0.59 rules above
  continue to govern it.
- **These are cost rules, and the first rule governs them (v0.59).** Every
  one of the three above is required to leave the answer byte-identical to
  the direct scan — same nodes, same lines, same snippets, same counts,
  same order. A cost rule that changed a result would not be a cost rule;
  it would be a different search wearing the same name. Measured motive:
  before them, a warm `sniff` on that forest cost 94 ms of a 103 ms sweep
  and throughput **fell** as concurrency rose, because the work was
  CPU-bound Python and the reader pool of J.6.2 cannot multiply what the
  interpreter serializes. The pool fixed blocking; only this fixes cost.
- **Only bodies the hash actually covers.** `body_hash` digests the
  node's own `.md` body, so the memo is confined to `content: inline`
  nodes. A `reference` body resolves to a file outside the forest that
  changes with no write the catalog observes; a `cached` body lives in
  `_derived/bodies` and can change or go missing, which the direct
  scan reports by skipping the node while the `.md` body, a stub,
  stays byte-identical. Both MUST record an absent `body_hash` and keep
  the direct scan. A later version MAY extend the memo to them by
  hashing the *resolved* body instead; until then the narrower rule is
  the honest one.
- **Disposable, and bounded.** The memo lives under `_derived/`, is
  rebuilt by use (never by `reindex`, which only has to invalidate it),
  and MUST be droppable at any moment with no effect other than latency.
  A deployment MAY evict it least-recently-used by term is the
  precedent (H.6) and eviction MUST NOT change any answer.

**F.58 (acceptance).** A `sniff` where an index node and a content node
match the same terms ranks the content node first, whatever their `heat`,
and reports both scores unadjusted. Between two content nodes with equal
term coverage, the one with more occurrences ranks higher; with equal
occurrences, heat still decides. Covered by tests.

#### C.6b.2 Containment is decided where the id arrives (v0.69)

`Forest.path_for` maps an id to a path and rejects ids that escape the
forest. That rejection is normative and unchanged. What this section fixes
is **where the expensive form of it runs**.

**Rule 1 — every boundary that accepts an id from outside the engine MUST
resolve.** The wire (REST and MCP), `ScopedVine`, and any host-supplied path
(`MONKEYLLM_INGEST_ROOTS`, upload staging, snapshot import) MUST decide
containment with symlinks resolved. At those points the id is untrusted
input and a symlink planted inside the forest is a real escape.

**Rule 2 — an id the engine read from its own catalog is not such a
boundary.** The catalog holds ids for nodes the engine planted and whose
paths the engine wrote. A read driven by the catalog — the `sniff` scan is
the one that matters, at one call per node in scope — MAY decide containment
textually: normalize the joined path (which resolves `..` and therefore
still refuses traversal) and require the forest root as a prefix.

**Rule 3 — a write always resolves.** `plant`, `graft`, `prune`,
`transplant` and `tend` take their ids from a caller, so they are rule 1's
case wherever they appear, including when a batch (C.7.4) rehearses them.

**Rule 4 — the boundary set is written down, and tested per surface.** The
failure mode of rule 2 is silent: a boundary left out does not raise, does
not log and does not slow down; an id simply passes. An implementation
therefore MUST carry a test that exercises traversal (`../`), encoded
traversal, and a **real symlink** planted inside a test forest against
**each** surface named in rule 1, and every one MUST refuse with the
byte-identical `E_NOT_FOUND` J.3 requires. A surface not in that test is not
covered by this section.

**Rule 5 — the relaxation is unreachable from the wire.** The textual form
MUST NOT be selectable by an argument any caller can send. It is the
engine's own internal path, chosen where the id's provenance is known — the
same construction G.2.5 uses for `adopted=` and C.5.3 for the table
allow-list: keyword-only, host-supplied, absent from the dispatch table.

This is a cost rule in C.6b.1's sense — no wire shape moves and no answer
changes — with one exception that is why it appears here rather than in a
changelog line alone: it redistributes a **security** check, and a security
check moved without being written down is a security check deleted.

**F.145 (acceptance).** Traversal, encoded traversal and a real symlink
planted inside a test forest are each refused with byte-identical
`E_NOT_FOUND`, on every surface of rule 1: engine, `ScopedVine`, REST and
MCP. Covered by tests.

**F.146 (acceptance).** A cold `sniff` over a forest of ~1,900 nodes spends
no `realpath` per node: the scan's containment is textual, and the primitive
returns the same nodes, sections, snippets and order it returned before this
version. The memo (C.6b.1) is untouched — a warm `sniff` is byte-identical.
Covered by tests.

### C.6c `harvest(query: string, terms?: [string], k: int = 3) → HarvestResult`

**Composite tool, not a primitive**: a deterministic, zero-LLM orchestration
over C.1 `locate`, C.6b `sniff` and C.4 `pick`. It exists for the
bring-your-own-model integration: the caller's LLM (MCP client) gets ranked
evidence in one call and decides the next steps itself.

The three integration modes (informative):

1. **Direct navigation** the client's LLM drives the primitives itself.
   Best when reasoning must happen *during* navigation. Token cost is bounded
   by the per-primitive budgets; the real cost is round-trips.
2. **Harvest (this tool)** one call, evidence back, zero tokens spent on
   the server side. Best default for capable client models.
3. **Concierge** a local SLM hunts and returns a synthesized answer
   (orchestrator-side, e.g. `examples/demo/run_demo.py`); for thin clients.

Parameters:

- `query`: free text; feeds `locate` as-is.
- `terms` (optional): exact literal terms for `sniff`. When absent, terms are
  derived from the query: words >= 4 characters, stopwords removed, max 8 —
  **plus, since v0.52, any token that looks like code whatever its length**.
  A token qualifies as code-shaped when it contains a digit, is written in
  capitals, or carries `-`, `_`, `.` or `/`. The four-character floor was
  discarding exactly the tokens a technical corpus is searched by (`RAG`,
  `MCP`, `JWT`, `SSO`, `421`, `p95`), so "how do I fix the 421 from MCP"
  reached `sniff` as `["corrigir"]` — a literal search for the question's
  verb, against a forest where the answer was sitting under both discarded
  tokens. The floor stays for ordinary words: a short common word is
  grammar, and every junk term lowers the `strength` of a real hit (C.6b),
  so widening the filter costs precision on every other query. Code-shaped
  tokens are ordered **first**, so the 8-term cap drops grammar before it
  drops signal.
- `k`: max bananas returned (default 3). The cap is the deployment's,
  not the caller's: `MONKEYLLM_HARVEST_MAX_K`, an integer >= 1 read from
  the environment, default **5** when unset. A value that does not parse
  as an integer, or parses below 1, is refused with `E_SCHEMA` naming
  the variable never silently corrected. The cap bounds the item
  count only; the response budget (below) is unchanged and remains the
  outer wall, with truncation explicit as ever.

Semantics (normative):

1. Candidates = RRF fusion of `locate(query, k*2)` and `sniff(terms, k*2)`
   rankings (same RRF as C.1's hybrid mode).
2. Match refinement by **term scarcity**: per-term `sniff` scoped to each
   selected node, rarest term first a rare exact term ("1045") MUST NOT be
   drowned by common co-occurring terms under the per-node match cap.
   **Never for an index node (v0.35)**: `sniff` resolves an index id to its
   subtree, so "refining" one grepped the forest under it children's
   snippets attributed to the index, chosen by heat rank and therefore
   different on every read. An index result keeps the global sniff's
   matches, which are found inside its own body; refinement MUST NOT cross
   the node it refines.
3. Content policy per node: full body when <= 1200 tokens; otherwise the
   matched sections (max 2) via `pick(section)`; otherwise outline + hint.
4. Response items carry: `id`, `title`, `type`, `trail`, `summary`, `score`,
   `found_by` (locate/sniff), `matches` (section, line, snippet),
   `body_tokens` (v0.54 — the whole body's size, C.1.1's rule, so a caller
   deciding to `pick` past the excerpt knows the price) and `content`. The
   caller can always continue with the primitives using `id`.
5. **An empty sweep says what it swept (v0.52).** When both legs come back
   with nothing, the response carries `searched` and a `hint` on the same
   terms as C.1.1 — the sweep is the one call a caller makes *instead of*
   navigating, so an empty one with no coverage is the same silence C.1.1
   describes, arriving where there is no next primitive to try. The hint
   points at the two moves that remain: narrowing the question, and passing
   `terms` explicitly. The derived list is already in the response, and
   when the sweep found nothing it is the first thing worth doubting.

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
      "body_tokens": 1832,
      "matches": [{"section": "Experimento 45", "line": 141, "snippet": "…"}],
      "content": [{"section": "Experimento 45", "body": "…", "body_tokens": 146}]
    }
  ],
  "truncated": false
}
```

**F.59 (acceptance).** `harvest("how do I fix the 421 from MCP")` derives
terms including `421` and `MCP`. `RAG`, `JWT`, `p95` and `x-api-key` survive
derivation; `fix`, `the` and `como` do not. When the cap is reached,
code-shaped tokens are the ones kept. A sweep that finds nothing carries
`searched` and a `hint`; a sweep that finds something carries neither.
Covered by tests.

#### C.6c.3 The sweep knows what time it is (v0.57)

A knowledge base accumulates versions of the truth — that is what it is
*for* — and the consumer team proved the failure mode the day they used
it: asked "what is still open?", the hosted answer read a two-rounds-old
report and the current one as the same present, reporting as open what
the newer document says was fixed. The `succeeds` edges stating the order
sat in the graph, declared with the very rel `_meta/schema` defines for
temporal order, and nothing read them. A memory that weighs August and
October as equal witnesses gets less reliable the more it remembers.

Three rules, none of which spends a model call:

1. **Every item states its time.** Sweep items carry `created` and
   `updated`, read off the catalog row the selection already loaded —
   never a file open. What the model does with them is the host's
   business (J.10 teaches it); the contract's business is that the
   material is dated.
2. **Equal relevance prefers the newer.** The RRF fusion breaks score
   ties toward the more recently `updated` node (then `created`, then id
   for determinism). A tie-break, never a boost: recency MUST NOT outrank
   relevance — a five-year-old architecture note that matches the
   question still beats yesterday's standup that does not.
3. **A succession inside the result set is annotated.** When one selected
   item `succeeds` another (directly, in the catalog's edges), the newer
   carries `supersedes: [ids]` and the older `superseded_by: [ids]`.
   Annotated, never suppressed: the older node stays in the material —
   history is evidence too — but the model is no longer the only one who
   could have discovered the order, because it never did. (A `supersedes`
   rel that suppresses its predecessor from retrieval by default is the
   fullest form of this fix and is deferred to the history design —
   suppression without a way to see what was suppressed is how a forest
   starts lying in the other direction.)

The dates and the annotations enter the J.10.7 reading fingerprint:
material re-dated or re-ordered is material re-read, and a stored answer
built before the succession was declared MUST NOT be served after it.

#### C.6c.4 A replacement suppresses what it replaced (v0.58)

C.6c.3 annotated and deliberately did not suppress: suppression without
a way to see what was suppressed is how a forest starts lying in the
other direction. With `history` (C.16) and the graph both able to show
the past, the fullest form the consumer team asked for lands, scoped to
the one place it belongs:

1. **The rel is `supersedes` (A.2), and it is a judgement.** `succeeds`
   says "B came after A" — both remain the truth of their moments; a
   round-4 report does not falsify round 3. `supersedes` says "B is what
   A used to be" — the policy that replaced a policy, the spec that
   absorbed a draft. Writers choose which claim they are making.
2. **The sweep excludes the superseded and refills the seat.** After
   selection, a candidate that a LIVE node `supersedes` leaves the
   result set and the next-ranked candidate takes its place — `k` is
   still met. The successor competes on its own relevance and is never
   smuggled in: a replacement that does not match the question is not
   evidence for it.
3. **Nothing is hidden silently.** The response carries
   `superseded_excluded: [{id, by}]` — the reader is told what was set
   aside and by what, in the same breath. An empty sweep whose only
   matches were superseded still says so, which is the difference
   between "nothing matches" and "what matched has been replaced".
4. **`include_superseded: true` restores the history view** — the
   excluded items return, carrying their C.6c.3 annotations. Off by
   default; the flag enters the J.10.7 key (it changes the reading).
5. **Navigation never suppresses.** `locate`, `sniff`, `move`, `scan`
   and the map projections show the forest as it is — suppression is a
   rule about material assembled for ANSWERING, not about the map. An
   agent walking the graph sees the superseded node, its edges, and its
   history.
6. Scope is honest: the suppression edge is read from the catalog under
   the caller's own view — a successor the caller cannot see cannot
   suppress what they can (the same periscope rule as C.15's waymark).

### C.6d `view(id: string) → media content` (v0.48)

**MCP tool, not a REST primitive**: the image payload behind a `media`
node, handed to the *caller's* model as MCP image content. G.5 stated
the split text to find, binary to consume and named this tool as a
possible future; this section makes it normative. `harvest` finds the
screenshot by its describer prose; `view` is how a multimodal client
then reads the pixels themselves: a tutorial screenshot before acting
on it, a UI mock a person clipped as feedback, a whiteboard photo whose
arrows the describer could only gesture at.

Semantics (normative):

1. Resolution follows J.14 exactly: the node, its `payload` field
   resolved relative to the node's directory, contained in the forest
   root after resolution. Absent node, node without a `payload`, and a
   `payload` whose file is missing all answer the **same** `E_NOT_FOUND`
   envelope as a missing node and on a host, an out-of-scope node is
   byte-identical to all of them (J.3's no-existence-oracle invariant).
2. A remote payload URI (G.9) is refused `E_SCHEMA` naming the scheme,
   as on J.14: fetching inside a read hides a network dependency;
   `vine prefetch` is how a remote region is warmed.
3. **Images only.** A payload whose type is not `image/*` is refused
   `E_SCHEMA` naming the type: a dataset is read with `query`, audio
   waits for a transcriber role (G.5.1), and raw bytes of arbitrary
   kind remain the human surface's affair (J.14).
4. **Bounded at 6 MiB** the same number as the G.5.1 describer's own
   refusal, because it is the same question ("too big to hand a
   model?") and one project answers it once. Over the bound is
   `E_SCHEMA` naming the size; the J.14 route serves bytes of any size
   to people.
5. The result is two content blocks: a JSON header `id`,
   `media_type`, `size`, `payload_hash` and the image content itself.
   The token budgets of Part C do not apply to the image block: the
   bytes land in the caller's context by the caller's explicit choice,
   and the byte bound above is their ceiling.
6. Traced like any read (Part D) and it deposits pheromone: a model
   that chose to open an image is the strongest evidence of usefulness
   this node will ever receive.
7. On a host: requires the `read` capability, audited like a read with
   the byte size (never the bytes), and **not** offered to the J.10.5
   walk its whitelist is unchanged, because the forest's own `answer`
   binding is not presumed multimodal. A vision-capable walk is a
   possible future, not this section.
8. On the REST surface this tool does not exist: `GET .../payload/{node}`
   (J.14) is REST's byte route, and a JSON twin of it would only
   disclose server paths.

**F.50 (acceptance).** `view` on a media node returns image content
whose bytes equal the payload file and a header whose `payload_hash`
matches the passport. On a dataset it answers `E_SCHEMA` naming the
type; over 6 MiB, `E_SCHEMA` naming the size; on a remote URI,
`E_SCHEMA` naming the scheme. A scoped principal viewing an
out-of-scope media node receives the same envelope as for a missing
one, and a node without a payload the same. All covered by tests.

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

#### C.7.1 Dataset planting declarative schema (v0.8)

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
   exist (`E_SCHEMA` never silently overwrite a payload). The Vine
   creates the SQLite file, applies the generated DDL, and computes
   `payload_hash` (sha256) into the frontmatter.
4. **Auto manual**: when the body lacks a `## Query manual` section, the
   Vine appends one generated from the schema each table with its column
   list, plus example queries (`` `SELECT * FROM <t> LIMIT 5` ``,
   `` `SELECT COUNT(*) FROM <t>` ``) so C.2 `look`'s `query_manual`
   contract works from birth. **When the node is born with `rows` (rule 7)
   the auto manual is followed by the `## Sample rows` map of G.2.3**,
   taken from those rows: the body is the only place a value inside the
   payload is ever visible to `sniff`, and a dataset born full and mapped
   empty is findable by nothing it contains. A caller-provided manual is
   kept verbatim, and suppresses both sections an author who wrote the
   manual owns the body.
5. **Atomicity**: the C.7 rollback covers the payload any failure after
   the `.db` is created MUST remove it along with the `.md`. A.3.1 intact:
   the commit carries only markdown; one dataset node = one `.db` = one
   database (several tables = several keys in `schema`; there is no
   separate "create database" concept).
6. After birth, rows enter exclusively via `tend` (C.10) multi-row
   `INSERT INTO t VALUES (...), (...)` is a single statement and therefore
   already legal there. Schema evolution (`ALTER`) is NOT available to
   agents in v0.8.
7. **Initial rows (v0.9)**: the `NodeSpec` MAY carry `rows`, a mapping
   `table → list of rows` loaded at birth, after the DDL and BEFORE
   `payload_hash` is computed. Normative: rows are inserted **parameterized**
   (`executemany` with placeholders row values are data, never SQL text,
   so no keyword scanning applies and injection is impossible by
   construction); every `rows` table MUST exist in `schema` and every row
   MUST have exactly the table's column count (`E_SCHEMA` otherwise); the
   atomic rollback of C.7 covers loaded rows (the payload is removed whole).
   This is the bulk-load path for the Gardener (G.3) and collector agents;
   incremental writes after birth remain `tend`-only.

Canonical uses (informative): an agent collecting external data plants the
dataset then fills it with `tend`, for later harvest by `query`/humans; an
agent finding a large markdown table in a `document` plants a dataset twin,
loads the rows, and `graft`s a `related-to` link from the document prose
stays as source, the data becomes filterable SQL.

#### C.7.2 A write you can repeat (v0.52)

`plant` refuses a duplicate `id` with `E_SCHEMA`, and that MUST remain the
default: a node silently overwritten because somebody reused an id is the
one failure a knowledge base does not recover from, and it is invisible
afterwards. The cost of that correctness is that **a write cannot be
retried**. An agent whose `plant` timed out does not know whether the node
exists; retrying may fail for a reason that reads like its own mistake, and
not retrying may drop the fact it was asked to keep. Unsupervised writing
needs one of the two to be safe.

`plant(node, if_absent: true)` makes the call idempotent **by id**:

1. Id free: the node is planted exactly as it is planted today validation,
   index entry, commit, all of C.7 unchanged and the result carries
   `created: true`.
2. Id taken: **nothing is written, nothing is committed**, and the result is
   `{id, created: false, trail}` describing the node that is already there.
3. The submitted content is NOT compared to the existing node, NOT merged
   and NOT applied. `if_absent` says "make sure this exists"; changing what
   exists is `graft`'s job, and a flag that quietly edited would be the
   silent overwrite this contract refuses.
4. Scope is unchanged. The destination parent is resolved and gated exactly
   as ever, so the flag cannot be used to probe ids under a branch the
   principal may not write to; an out-of-scope destination is refused before
   the id is ever looked at.
5. `created` is present on **every** `plant` result, with or without the
   flag it is `true` on the path that plants, so a client never has to
   infer the outcome from the absence of a field.

**F.61 (acceptance).** `plant(node)` on a free id returns `created: true`
and a commit; repeated, it returns `E_SCHEMA` and writes nothing. The same
call with `if_absent: true` returns `created: false`, no commit, the
existing node's trail, and leaves the existing node byte-identical even when
the submitted body differs. Two `if_absent` plants of the same id leave one
node and one commit in the forest's history. Covered by tests.

#### C.7.3 A write rehearsed (v0.57)

The 60-token summary ceiling is a good rule with an expensive messenger:
the refusal arrives *after* the whole node crossed the network — the
consumer team lost two of eight plants to summaries of 61 and 62 tokens,
each costing a 33 KB round trip to learn one number. The error message
was excellent and late.

`plant(node, dry_run=true)` runs the rehearsal:

1. **Every validation the real plant runs, in the real order** — id and
   parent-chain rules, declared types and rels against `_meta/schema`,
   the summary ceiling, alias bounds, link targets' existence wherever
   the real plant checks it, dataset `schema` validation (C.7.1). Not a
   parallel checker: the same code path up to the first write, because
   two validators agree only where somebody compared them (the C.5.3
   lesson).
2. **Nothing is written, nothing is committed, nothing is indexed.** No
   file, no catalog row, no pheromone, no `_derived` touch. A dry run
   repeated forever leaves the forest byte-identical.
3. The success answer is `{id, valid: true, dry_run: true}` — and
   `created` is absent, because nothing was. A failure is the exact
   envelope the real call would have raised.
4. `dry_run` composes with `if_absent` (the rehearsal then also reports
   `created: false` for a taken id instead of `E_SCHEMA`, mirroring
   C.7.2's answer shape).
5. Scope and capability are checked as on the real path: the rehearsal
   requires `write` and gates the destination — a dry run that a
   read-only principal could call would be an oracle for what a write
   *would* say.
6. **A failing rehearsal names every problem it can determine (v0.59).**
   The point of this primitive is to replace trial-and-error with one
   call, and validating in a chain — first problem, stop — left it
   trial-and-error that merely costs less: the consumer team's node had a
   61-token summary *and* a non-existent parent, and learned about them in
   two round trips. A dry run MUST run every check whose preconditions
   hold and report the lot. Three constraints keep it honest:
   - **The envelope is unchanged to the byte.** `code`, `message` and
     `hint` remain those of the *first* problem in the real path's own
     order, so a client that reads the code, and every test written
     against v0.57, sees exactly what it saw before. The complete list
     rides in the envelope's `data` as `errors: [{id, code, message,
     hint}]` (C.12's `data` carrier, the shape C.14 already uses for
     `anchors`), the first entry being the one the envelope repeats.
   - **A check whose precondition failed is skipped, never guessed.** If
     the parent does not exist, the rehearsal does not invent what its
     kind would have been; the reported list is what could be
     *determined*, and a second rehearsal after the fixes is a legitimate
     step, not a failure of this rule.
   - **A batch rehearses every node (C.7.4).** `dry_run` over a list runs
     all of them and collects across all of them, each error carrying its
     node's `id` and its `index` in the list — twenty nodes with twenty
     problems is one correction, which is the whole reason the list form
     exists. The real `plant` is unaffected: it refuses at the first
     problem, because writes wait behind it and there is nothing to gain
     from computing more.

#### C.7.4 A batch is one plant (v0.58)

The consumer team planted eight documents in eight calls; two failed on
their summaries and left a half-built graph — nodes present, links
aimed at absences — that only a second corrective pass healed. Their
sentence: the same batch principle `look`, `pick` and `scan` already
have on the read side, owed to the write side. And the load report adds
the other half of the motive: one plant is one writer-lane occupation
and one git commit, so one hundred nodes were one hundred commits.

`plant` accepts a **list** in `node` (≤ 20 — `MAX_BATCH_PLANT`):

1. **Everything is validated before anything is written.** Every node
   runs C.7.3's rehearsal, in list order, against the forest PLUS the
   batch's own earlier nodes — so a branch and its children may share
   one batch. The first failure refuses the whole call with the exact
   envelope the failing node would have raised alone, prefixed with its
   id; nothing is written, nothing is committed. All-or-nothing, stated:
   a partial batch is the half-built graph this rule exists to end.
2. **The batch lands in ONE commit** (`plant(batch): N nodes`), every
   file and every parent-index refresh inside it. One commit is one
   lane occupation and one git ceremony — the write ceiling, divided by
   the batch size.
3. **The answer accounts for every id sent** (C.11's idiom):
   `{created: [ids], existing: [ids], commit, count}` — `existing` is
   `if_absent`'s per-node answer (an id already taken skips, writes
   nothing, fails nothing); without `if_absent` a taken id fails the
   batch as it fails a single plant.
4. **`dry_run` composes:** the whole batch rehearses, nothing lands,
   and the answer is `{valid: true, count, dry_run: true}` — or the
   first failure, exactly as rule 1.
5. A duplicate id INSIDE the batch is `E_SCHEMA` naming it — two nodes
   cannot claim one address even transiently.
6. A single dict in `node` keeps the v0.57 shapes to the byte; a
   one-element list answers the batch shape. Datasets (`schema`) are
   refused in batches for now — a payload birth mid-batch has no
   rollback story yet, and refusing is honest where restoring is not.

### C.8 `graft(id: string, patch: GraftPatch) → GraftResult`

`GraftPatch` supports four operations (combinable):
- `set_frontmatter: {field: value}` mutable fields only (`title`, `summary`, `tags`, `confidence`, and `aliases` as of v0.54 — a list of at most 16 non-empty strings of at most 80 chars each, anything else `E_SCHEMA`); `id`, `type`, `created` are immutable (`E_READONLY`);
- `add_links: [{rel, target}]` / `remove_links: [...]`;
- `append_section: {header, body}` or `replace_section: {header, body}`;
- `replace_body: string` (v0.43) the entire body at once, the note as
  the unit of edit. The empty string is a valid body. NOT combinable
  with the section operations (`E_SCHEMA`: one patch, one truth about
  the body), and refused on index nodes (`E_SCHEMA`: an index's body is
  the indexer's render, and a hand-written one would stop parsing as a
  map). The serialized node MUST re-parse before the commit happens.

Special rules:
- A `summary` change propagates to every `_index.md` that replicates it (same transaction).
- **A write that outdates the scent says so (v0.54).** A `graft` whose
  patch changed the body (`replace_body`, `replace_section`,
  `append_section`) without carrying a `summary` in the same patch returns
  `summary_stale: true`. `locate` indexes title, aliases, tags and summary
  and nothing else (C.6b split), so every body edit that leaves the summary
  behind ages the exact layer navigation trusts — and v0.52's empty-read
  hint *taught* callers to trust it. The flag is the caller's chance to
  repair in the same turn, and the repair is one call:
  `graft(id, {set_frontmatter: {summary: …}})` — which was always legal and
  is now stated. The flag is absent (never `false`) on every other patch;
  it is a signal, not a judgement of whether the summary still fits, which
  only a reader of both can make.
- **An unknown patch key is refused, never absorbed (v0.56).** A key of
  `patch` that names no operation above is `E_SCHEMA`, naming the key and
  listing the operations that exist. Before this, an unknown key was
  silently discarded: alone it read as an empty patch, but **beside a
  legal operation the call answered `200` and did less than it was asked**
  — `graft(id, {"regenerate_summary": true, "append_section": …})`
  appended the section, dropped the flag, and the caller walked away
  believing the summary was regenerated. A patch key is a claim about
  what the write does; the write must refuse claims it does not
  understand, which is the same discipline v0.54's rule 8 (C.12) applied
  to unknown REST parameters. The refusal happens before anything is
  written — a patch half-understood MUST NOT be half-applied.
- **Reinforce-before-create policy (shortcuts):** at the end of a successful hunt, the decision cascade is: (1) if a shortcut already covers the entry→banana connection on the trail, do NOT create one just increment the existing one's `heat` and `confidence` (fortification, no commit); (2) if none exists and the trail was >= 4 hops, `graft` a new `discovered-shortcut` with `confidence: 0.5` and `discovered_by: agent`; (3) new lateral connections the agent notices (`related-to` between the banana and semantic neighbors) enter as a **proposal** with `confidence: 0.3`, subject to confirmation or pruning by the Ranger. The Vine MUST implement step 1's check inside `graft` itself (shortcut idempotence): grafting a duplicate link automatically becomes fortification, never an error or a duplicate.
- Commit: `graft(<id>): <patch summary>`.

### C.10 `tend(id: string, sql: string) → TendResult` (v0.7 Phase 2)

The dataset-write primitive: the forest stops being a smart reader and
becomes memory that learns. `query` (C.5) remains read-only forever; `tend`
is the only sanctioned write path into a dataset payload.

Preconditions:

- Writable Vine (read-only server → `E_READONLY`).
- Node is `type: dataset` with `payload_type: sqlite` and an existing
  payload file anything else → `E_QUERY_FORBIDDEN` / `E_NOT_FOUND`.

Statement rules (normative, mirror of C.5's paranoia):

- Exactly ONE statement, and it MUST start with `INSERT`, `UPDATE` or
  `DELETE`. Reads belong to `query`; schema changes (CREATE/ALTER/DROP)
  belong to the Gardener all rejected with `E_QUERY_FORBIDDEN`.
- Forbidden anywhere in the statement: `ATTACH`, `DETACH`, `PRAGMA` in
  both spellings, the keyword and the `pragma_*` functions (v0.50)
  `DROP`, `ALTER`, `CREATE`, `VACUUM`, `REINDEX`, `BEGIN`, `COMMIT`,
  `TRANSACTION` → `E_QUERY_FORBIDDEN`.
- `UPDATE`/`DELETE` MUST carry a `WHERE` clause (mass-wipe guard): target
  rows explicitly; full rewrites are the Gardener's job.
- **The table allow-list applies here too, reads included (v0.50).** When
  the grant narrows the dataset (J.3), `tend` enforces it through the same
  authorizer as `query` (C.5.3), refusing the write actions *and*
  `SQLITE_READ` outside the list. Without the read action the scope would
  hold only for the destination, and writing is a way of reading.
- Timeout 2s → `E_TIMEOUT`. SQL errors roll the transaction back and
  surface as `E_QUERY_INVALID` (v0.47, C.5.2 the guard above decides
  what is *forbidden*; SQLite decides what is *invalid*, and a `tend`
  naming a column that does not exist is the second, on a dataset the
  principal is allowed to write). The payload is untouched either way.

Audit trail (A.3.1 compliant):

1. The write commits in the payload SQLite.
2. The Vine refreshes the node's frontmatter: `payload_hash` = sha256 of
   the payload file, `updated` = today.
3. `git commit` of ONLY the `.md`, message `tend(<id>): <VERB> <n> row(s)`.
   The what/when history lives in the markdown commit stream; the binary
   never enters git.
4. If step 2-3 fails after step 1 committed, the `.md` is restored and the
   error surfaces the resulting hash drift is exactly what
   `vine validate` now warns about (self-healing: the next successful
   `tend` refreshes the hash).

Response:

```json
{"id": "vendas/pedidos-2026", "rows_affected": 1,
 "payload_hash": "<sha256>", "commit": "<hash>", "elapsed_ms": 4.2}
```

### C.9 Concurrency and consistency (Phase 0)

- **One writer, N readers:** `plant`/`graft` go through a single queue (global mutex in the Vine). Reads never block.
- Readers MAY see state up to 1 write behind (eventual consistency of seconds) acceptable by design.
- The `.vine.lock` file at the root prevents two writer Vines on the same forest (`E_LOCKED`).

**The lock is possession, not existence (v0.55).** Until v0.54 the lock
was the file: created `O_EXCL`, holding nothing but a pid nobody ever read
back. A process that exits without deleting it — a kill, an OOM, a
container upgrade, which is how server processes actually end — left the
forest refusing every writable open forever, and since a host serves reads
through its one writable Vine, an orphan file was a total outage repaired
only by shell access. Measured in the field: one upgrade, two forests,
every primitive dead, health green.

Four rules replace that:

1. **Possession is the kernel's.** Acquiring the lock is taking the OS's
   advisory lock (`flock`-class) on the open lock file, which the kernel
   releases when the holding process exits, however it exits. The file's
   existence decides nothing.
2. **The file is the holder's card.** On acquire it is rewritten with
   `{pid, host, since}` — diagnostics for humans and for the refusal,
   never the control. A card left by a dead process is an orphan: the
   next open takes the kernel lock over it, rewrites the card, and
   serves. Silently, because recovering from a crash is not an event the
   caller needs to act on.
3. **`E_LOCKED` names the holder.** A refusal quotes the card — pid,
   host, since — so "who has it" stops being a filesystem investigation.
   The hint says the lock releases itself when its holder exits, instead
   of prescribing a manual `rm` to callers who have an API and no shell.
4. **A filesystem that cannot hold the lock says so by behaving as
   before.** Where the kernel lock is unsupported (some network mounts),
   acquisition falls back to v0.54's existence semantics — refusing on a
   present file — because guessing liveness without the kernel is how
   two writers happen. The J.13.5 release endpoint is the operator's
   path there.

Reclaim races are closed by identity, not by luck: after taking the
kernel lock the holder verifies the path still names the inode it locked
(a release unlinks while holding, so a waiter that acquired on the
now-unlinked inode retries against the fresh file). Bounded retries; a
forest that stays contended answers `E_LOCKED` honestly.

**N readers are real now (v0.57).** The lock is possession of the
*write*: a read-only Vine (`writable=False`) takes no lock and MAY be
opened in any number beside the writer, in the same process or another.
What makes that safe is WAL — a reader sees every write whose transaction
committed before its own began, which is exactly the "up to 1 write
behind" this section has promised since Phase 0. What makes it *practical*
is one more pragma: every read deposits pheromone, so N readers are N
occasional writers to the trails store, and SQLite's default answer to a
busy writer is an immediate "database is locked". The derived-layer
tuning (`tune_derived`) therefore sets `busy_timeout` alongside WAL: a
contended deposit waits its milliseconds instead of erroring. The host
layer's use of this property is J.6.2.

---

### C.11 A batch is one call (v0.52)

`look` and `pick` accept a **list** of ids where they accept one. The
minimum path to read a passage is three calls (`locate` → `look` → `pick`),
so reading five nodes cost eleven round trips, eleven tool results in the
caller's context window, and — measured against a served Station — about
six seconds of network for a forest of four nodes. Context is the resource
this product promises to save, and the shape of the surface was spending it
on plumbing. An agent that tried the obvious grouping, `pick(id=["a","b"])`,
got `500 Internal Server Error` (C.12).

The saving is round trips. It is **not** tokens, and the contract says so:

1. **One call, one budget.** A batch is sized by a single budget, not by the
   per-item budget times the number of items: `look` ≤ 2000 tokens for the
   whole response (BUDGET_LOOK stays 500 for a single digest and for each
   digest inside a batch), `pick` ≤ 4000 — the same wall a single body
   already meets. An agent that asks for five large bodies gets what fits
   and is told the rest was dropped; nothing about a batch may deliver more
   material into one turn than the primitive would deliver alone.
2. **Whole items drop, from the tail, in the caller's order.** Results are
   returned in the order the ids were given ranking a list somebody
   already chose would make which item is dropped unpredictable. Dropped
   items are **named** in `dropped: [id, …]` with `truncated: true`; a body
   is never sliced to make room.
3. **Every id comes back accounted for.** Each id in the request appears
   exactly once in the response: in `nodes`, in `missing`, or in `dropped`.
   A batch of ten with one bad id MUST NOT fail as a whole — the other nine
   were valid questions and re-asking them is exactly the round trip this
   removes.
4. **`missing` keeps J.3's rule.** An id that does not exist and an id the
   principal may not see are both `missing`, byte-identical, exactly as
   `E_NOT_FOUND` is for a single read. A batch MUST NOT become the surface
   that distinguishes them.
5. **The shape follows the request, not the result.** A list in returns
   `{nodes, missing, dropped, truncated}`; a string in returns the single
   digest or content object of C.2/C.4, unchanged to the byte. A one-element
   list is still a list: a client that built its request as a list must not
   have to branch on how many ids it happened to hold.
6. **Bounded.** `look` accepts at most 10 ids, `pick` at most 5; more is
   `E_SCHEMA` naming the cap. An empty list is `E_SCHEMA` too — it is not
   a request for nothing, it is a caller with a bug.
7. Duplicates are collapsed, keeping first position. The same node read
   twice in one call is a mistake with no meaning to preserve.

Each item is built by the primitive itself: same fields, same per-node
budget, same `fields`/`section` argument applied to every id in the batch.
A batch is a transport shape, never a second semantics.

**F.57 (acceptance).** `look` and `pick` with a list of ids answer
`{nodes, missing, dropped, truncated}` in the caller's order; with a string
they answer exactly the single-node shape they answered before. A batch
containing one absent id and one out-of-scope id reports both in `missing`,
byte-identically, and still returns the valid ones. A batch whose bodies
exceed the budget drops whole items from the tail, names them in `dropped`,
and never returns a sliced body. Ids over the cap, and an empty list, are
`E_SCHEMA`. For every accepted batch, the union of `nodes`, `missing` and
`dropped` is exactly the set of ids requested. Covered by tests.

### C.12 Every exit is an envelope (v0.52)

Part C says a failure is `{error: {code, message, hint}}`, and the project's
error text is one of the things a reader of this surface praises — because
the consumer is a model, and an error that teaches is the difference between
recovering in the next turn and giving up. The hole was never in the codes
it defines; it was in the paths that reach none of them. Seven malformed
calls against a served Station produced five different behaviours:

| call | was |
|---|---|
| `pick(id=["a","b"])`, `look(id=["a"])`, `locate(query=["a"])` | `500`, body `Internal Server Error`, no envelope |
| `locate(query="x", k="three")` | `400 E_SCHEMA: "'>' not supported between instances of 'int' and 'str'"` |
| `look(id=null)` | `404 E_NOT_FOUND: node not found: None` |
| `sniff(terms=[123])` | `200 {"results": []}` |

The last two are worse than the crashes, because they answer. A `null` id
was coerced into the string `"None"` and looked up; an integer term was
accepted and matched nothing, which is indistinguishable from "nothing in
this forest matches". A `500` with no code cannot even be classified: it
tells a model nothing about which of three opposite reactions is right
alert the operator, stop, or just fix the argument.

Normative:

1. **One signature table.** Every primitive's parameters name, accepted
   types, default, whether required are declared **once, in the engine**,
   and every surface that receives arguments from the wire enforces that
   declaration either directly, before the primitive is reached, or
   through a transport that already refuses on a schema of its own (MCP
   validates a tool call against the tool's input schema). Where the second
   is relied on, the two MUST be checked against each other mechanically:
   two descriptions of one contract agree only where somebody compared them
   (C.5.3's rule, applied to arguments rather than tables). A parameter an
   MCP tool accepts and the table does not know is a defect in whichever is
   wrong, and the comparison is what says so.
2. **Argument shape is `E_SCHEMA`/400**, and the message names the
   parameter, what arrived, and what was expected. A Python exception's text
   is not a message: `'>' not supported between instances of 'int' and
   'str'` is a stack trace wearing an envelope, and it names neither the
   parameter nor the type.
3. **`null` is not a value.** A parameter given `null` is a parameter not
   given: refused as missing when it is required, defaulted when it is
   optional. Never coerced to a string and looked up.
4. **A list where a scalar belongs is refused as a list** unless the
   primitive takes one (C.11) never iterated, never joined, never
   silently taking the first element.
5. **The last resort is still an envelope.** Any exception no rule above
   caught is answered `E_INTERNAL`/500 in the envelope shape, naming the
   primitive and the exception's type and nothing more: no traceback, no
   file path, no SQL. An unhandled path is a defect in the host; served as
   a bare 500 it becomes the caller's defect too, because the caller cannot
   tell it apart from its own bad argument. This applies to **every** route
   the host serves, not only the primitives.
6. **A missing parameter is not a denial.** A route that requires
   `?forest=` and did not get one answers `E_SCHEMA`/400 naming it. Measured:
   `GET /v1/admin/health` with no `forest` told a key holding `admin` on
   every forest it lacked `admin` on that forest sending an operator to
   audit grants over a mistake that was in the URL. What was asked for is
   resolved before who may have it, for every parameter whose absence is
   not itself a secret; an id that may not exist keeps its existing
   treatment (J.3), because "which forest" is a question about the request
   and "may I" is a question about the principal.

**The table covers the composites too (v0.67).** `harvest` and the host's
`answer` are declared in the same one table as the primitives, for rule 1's
reason and not by analogy: they receive arguments from the wire, so a
parameter one surface accepts and the table does not know is the same defect
there as anywhere. `answer`'s optional `terms` (J.10.3) is therefore a row
in that table — not a key the route happens to read — which is what makes it
enforceable identically on REST and MCP and comparable by the test rule 1
requires.

**F.60 (acceptance).** Each of the seven malformed calls tabled above is
answered with the envelope: `E_SCHEMA`/400 naming the parameter and the
types for the wrong-shape ones, `E_SCHEMA` for a `null` required parameter
and for `sniff(terms=[123])`. No route answers a bare `500`: an exception
raised inside a primitive arrives as `E_INTERNAL`/500 in the envelope shape,
naming the primitive and the exception type and carrying no traceback.
`GET /v1/admin/health` with no `forest` answers `E_SCHEMA`/400 to a key that
holds `admin`, and `E_FORBIDDEN`/403 to one that does not hold it on the
forest it named. A test compares the MCP tool schemas against the engine's
signature table and fails on any divergence. Covered by tests.

### C.13 Where the material sits in time (v0.52)

"Last week I wrote something about this" is how a person addresses their own
knowledge, and the forest already knows: every passport carries `created`
and `updated` (A.3), the Gardener stamps `created` when a document enters,
git versions both, and `reindex` rebuilds them identically. What was missing
was any way to **use** them. An agent asked about last week had to sweep the
whole forest and hope the ranking floated something recent — on a forest of
four nodes that is invisible, and on a forest of forty thousand it is the
difference between a search and a scan.

A window is also the cheapest filter this system has: it is decided from the
catalog row, before a single body is opened. A `sniff` bounded to seven days
opens the files of those seven days and no others.

Two additions, and the second is what makes the first safe.

#### C.13.1 Windowed reads

`locate`, `sniff`, `scan`, `harvest` and `answer` (J.10) take three
optional parameters:

- `since`, `until` — inclusive bounds, accepted as `YYYY`, `YYYY-MM` or
  `YYYY-MM-DD`. A partial bound expands to its own period: `since:
  "2026-08"` is 2026-08-01, `until: "2026-08"` is 2026-08-31, `until:
  "2026"` is 2026-12-31. Either may be given alone.
- `date_field` — `"created"` (default) or `"updated"`.

Normative:

1. **Optional, and absent means unchanged.** A call without them behaves
   byte-for-byte as it did before this version: same candidates, same
   ranking, same budget, same fields. Nothing about a window is ever a
   default, because a default window is a forest that quietly shrank.
2. **A window narrows the candidates, never the ranking.** It is a
   metadata filter (C.6b's split is untouched: `locate` still reads
   curated metadata, `sniff` still reads bodies); `score` and `heat` mean
   exactly what they meant.
3. **Applied where candidates are chosen, not after the cut.** Filtering a
   ranked top-`k` after the fact returns fewer than `k` results while the
   forest holds more that match — the caller then reads scarcity that the
   implementation invented. The predicate belongs in the query that selects
   candidates.
4. **An unparseable bound is `E_SCHEMA`**, naming the accepted forms. It
   MUST NOT be ignored: a filter silently dropped is a lie about what was
   searched, and it is told to a caller who will believe the result covers
   only their window. Same for an unknown `date_field`, and for `since`
   later than `until`.
5. **Undated nodes never match a window**, and the response says how many
   were excluded that way (`undated_excluded`, present only when there are
   any — a forest with complete passports should not spend a line of its
   budget on a zero). A node whose passport carries no usable date is not
   "recent" and is not "old"; dropping it silently is how a windowed search
   loses material nobody suspects. Under a policy the number counts only
   nodes in scope, like every other count a scoped caller reads (J.3).
6. **The response echoes the window it applied**, normalized —
   `window: {since, until, date_field}`. The caller sent `2026-08`; what it
   gets back is the two dates the search actually used, which are also the
   two it can reuse.
7. **A bounded hunt is bounded at every hop.** When `answer` walks (J.10.5)
   rather than sweeping, the window is forced onto every searching call the
   model makes, not only onto the entry search, and the prompt states the
   bound. A model that forgot its window on the second hop would produce an
   answer labelled with a period it left — which is worse than no window,
   because the label is what a reader trusts.
8. **A window names the answer it produced.** Unlike `min_evidence`
   (J.10.10), a window on `answer` MUST enter the J.10.7 cache key: it
   changes which nodes the retrieval could reach at all, so the same
   question bounded to June and to July are two questions, and one entry
   serving both would answer one with the other. It enters only when set,
   so a call without it keys exactly as it did before this version.
9. **The derived layer is not a clock.** `date_field` names a passport
   field and nothing else. "When it was indexed" MUST NOT become a third
   option: `_derived/` is disposable and rebuilt on demand (`reindex`), so
   a window over an indexing timestamp would mean one thing today and a
   different thing after a rebuild, with no way for a caller to know which.
   The date a document entered the forest is already `created`, written by
   whoever planted or ingested it, versioned in git with the node.

#### C.13.2 The empty window explains itself

The risk of any filter is that it turns "nothing here" into "nothing
anywhere", and a window is the easiest filter in this system to get wrong:
a caller guessing at last week's dates, a forest whose material sits in a
different month, a `created` that never got written. C.1.1's rule therefore
applies with one addition — **when a windowed read comes back empty it says
whether the window was the reason.**

An empty windowed read carries, beside C.1.1's `searched` and `hint`:

- `matched_window` — how many nodes fall inside the window at all,
  independent of the question. `0` means the window is the reason and the
  question was never tested; a number above zero means the window held
  material and the question did not match any of it. Those are different
  mistakes with different repairs, and a caller cannot guess which it made.
- a `hint` naming the forest's actual date range and the nearest periods
  that DO hold material, so the next call is a correction rather than
  another guess.

Both are computed only on the empty path, for C.1.1's reason: a caller
holding results has already been told what it needed.

#### C.13.3 `calendar(scope?, date_field="created", granularity="month", since?, until?, limit=24) → Calendar`

The map that makes a window a choice instead of a guess. It answers, from
the catalog alone and without opening a single body: **what periods hold
anything, and how much.**

```json
{
  "date_field": "created",
  "granularity": "month",
  "range": {"first": "2026-01-03", "last": "2026-08-19", "nodes": 82},
  "buckets": [
    {"period": "2026-08", "since": "2026-08-01", "until": "2026-08-31", "nodes": 12},
    {"period": "2026-06", "since": "2026-06-01", "until": "2026-06-30", "nodes": 31}
  ],
  "undated": 3,
  "truncated": false
}
```

- `granularity`: `day` | `week` | `month` | `year`. A week is ISO-8601
  (Monday-first, labelled `2026-W34`).
- **Most recent first.** The question that brings a caller here is almost
  always about the recent end, and `limit` cuts the far end.
- **Empty periods are omitted.** A three-year gap costs nothing to report
  and the buckets that exist are exactly the answer to "which weeks have
  anything".
- **A bucket's `since`/`until` are the strings the reads take.** The map
  hands back the query: there is no arithmetic for the caller to get wrong
  between finding a period and searching it.
- `range` is the real first and last date in scope, so a caller that wants
  a window nobody listed can still see the edges of what exists.
- `undated` is reported for C.13.1 rule 5's reason.
- Budget ≤ 800 tokens; over it, buckets drop from the far end with
  `truncated: true`. `limit` is capped at 120.
- `scope` restricts to a branch's subtree, exactly as `sniff`'s does.
- Under a policy (J.3) every count covers **only nodes in scope**. A global
  count here would be a size oracle, and a finer one than `locate` could
  ever be: it would describe the shape of a region the principal was never
  granted, period by period.

Two implementation rules, normative because both are ways the obvious code
gives up the performance this section exists for:

- **The window is a bare comparison on the column.** `created >= ?` uses
  the catalog's index; `substr(created, 1, 10) >= ?` computes the same
  answer and cannot, which on a forest large enough to want windows is the
  whole difference. The upper bound is therefore held exclusive, one day
  past the caller's inclusive `until`, so a column carrying a time still
  falls inside its own last day. The catalog indexes both date columns.
- **The aggregation belongs to SQLite.** `calendar` MUST group in the
  database and return one row per period, not one row per node folded in
  the host: the counting is the part that scales with the forest, and it is
  the part a database does in C. A scoped `calendar` (J.3) pushes the
  policy's own prefixes into the same `WHERE`, so scoping stays a predicate
  rather than a walk. Where the same fold exists in the host as well, the
  two MUST be compared mechanically over a real corpus — C.5.3's rule
  again: two spellings of one decision agree only where somebody checked.

**F.64 (acceptance).** A `locate`, `sniff`, `scan`, `harvest` or `answer`
carrying `since`/`until` returns only nodes whose `date_field` falls inside the
inclusive window, with `k` still met when the window holds enough matches,
and echoes the normalized window. `since: "2026-08"` and `since:
"2026-08-01"` produce identical results. A malformed bound, an unknown
`date_field`, and `since` after `until` are each `E_SCHEMA`. A node with no
date is absent from every windowed result and counted in
`undated_excluded`. An empty windowed read carries `matched_window` and a
hint naming the nearest populated periods; the same read without a window
carries neither. `calendar` returns buckets most recent first, omits empty
periods, and each bucket's `since`/`until`, fed back into `locate`, return
that bucket's nodes. Two `answer` calls differing only in their window are
two store entries. Under a scoped policy no count — and no number quoted in
a hint — exceeds the nodes in scope. Covered by tests.

### C.14 `prune(id: string, force: bool = false) → PruneResult` (v0.56)

The write you can take back. Until v0.56 every `plant` was irreversible —
no primitive removed a node — and the consumer team measured the
consequence in their own behavior: three probe nodes left as permanent
garbage in a production forest, tagged `delete-me` because a tag was the
most deletion the product offered, and the stated conclusion that *an
agent that cannot undo should not write alone*. The rational strategy
under that constraint is to write on the local disk, where `rm` exists,
and promote only finished work — which is exactly the habit this product
exists to end. A removal primitive is therefore not a convenience; it is
what makes unsupervised writing rational.

```json
{"id": "probes/size-probe-report", "pruned": true,
 "backlinks_removed": 0, "payload_moved": null, "commit": "<hash>"}
```

Normative:

1. **What it removes.** The node's `.md` leaves the working tree through
   git (the deletion is staged and committed as `prune(<id>)` — history
   keeps every byte, which is what makes this *soft*: recovery is an
   operator act, `git revert` or a Part I snapshot, never a primitive).
   The parent index loses the child's entry and its coverage counts are
   refreshed, in the same commit (the reverse of C.7's planting, using
   the same indexer). The catalog row is deleted synchronously, so no
   read offers the node again. Derived remnants — heat, sniff memos,
   embeddings — become unreachable the moment the row is gone and are
   the derived layer's to evaporate; a `reindex` owes them nothing.
2. **A local payload moves to the graveyard, never dies with the call.**
   A payload file inside the forest (a dataset's `.db`, an `_assets/`
   media file) is MOVED to `_derived/graveyard/<node-id>/` — binaries
   are not in git (A.3.1), so unlink would be the one truly
   irreversible byte of a primitive that promises to be reversible.
   The graveyard is `_derived/`: disposable, never a source of truth,
   and the operator's to empty. A remote payload (G.9) is left where it
   lives — the forest never owned it.

   **And so does a source staged inside the forest (v0.61).** When the
   node's `source_path` resolves under the forest's OWN `_derived/` —
   the upload staging area, disposable by the same construction — that
   file moves to `_derived/graveyard/<node-id>/source/` and the result
   says `staged_moved`. Leaving it behind is what let a later pass over
   the staging area read the pruned document as *new* and plant it
   again. A source tree on the host is never touched, by this or any
   other primitive: deleting somebody's file is not a thing a removal
   inside a forest may do (G.3), and the distinction is the containment
   test, not a flag.
3. **What points at the node refuses the removal (`E_ANCHORED`, HTTP
   409).** A node with `edges_in` is refused, and the refusal carries
   `anchors: [{source, rel}, …]` (capped at 20, `anchor_count` exact) —
   the caller asked to remove something other nodes cite, and the list
   is what it needs to decide. `force: true` overrides: the same commit
   that removes the node also edits every pointing node's frontmatter,
   dropping exactly the links whose target died — a forest MUST NOT be
   left pointing at a hole it created on purpose. `backlinks_removed`
   counts them.
4. **A branch with children is never prunable — `force` included.** The
   refusal is `E_ANCHORED` naming the child count. Prune the children
   first: recursive deletion is a loop the CALLER writes, one audited,
   one-node decision at a time, not a flag that can erase a subtree in
   one call. The forest root's `_index` is never prunable (it has no
   parent to account for it).
5. **A pruned id is free.** `plant` of the same id afterwards is legal
   and creates a NEW node — ids are immutable *while they exist*
   (C.7.2's duplicate refusal protects living nodes, not ghosts). The
   forest's git history distinguishes the generations.
6. **Scope and capability (J.3).** `ScopedVine.prune` gates the id
   exactly as every read does — out of scope answers `E_NOT_FOUND`
   byte-identical to absent — and rides the same write capability as
   `plant`/`graft`: J.2.6's mask ceiling is a closed set, and a fourth
   token would invalidate every issued key. Under `force`, a pointing
   node OUTSIDE the caller's scope is not silently edited: the whole
   call refuses (`E_ANCHORED`, the out-of-scope anchors reported only
   as a count — J.3 forbids naming them), because a write the caller
   cannot see is a write it cannot have authorized.
7. **Audited and emitted.** The audit row and the J.16 `prune` webhook
   event carry the id, the type, `backlinks_removed` and the commit —
   identity, never content, like every event.
8. **Answer-cache honesty is free.** A cached `answer` whose material
   cited the pruned node re-runs its sweep on every ask (J.10.7); the
   reading fingerprint no longer matches, so the stored reply is
   replaced, never served stale. Stated, not new machinery.

### C.15 `transplant(id: string, new_id: string) → TransplantResult` (v0.58)

An id is a path, so misplacement was permanent: the consumer team put a
document under the wrong branch and the only remedy was rebuilding it by
hand — plant a copy, restring every link, prune the original, lose the
history. Every deferral of this feature named the same fear: a move
rewrites every edge, trail and cache key that names the node. The answer
is not to make the id mutable — it is to make the move ONE audited act
that leaves a waymark.

1. **One leaf node, whole, in one commit.** The passport is rewritten
   under `new_id` (frontmatter `id` updated, everything else preserved —
   `created` included) and the old file removed in the same commit; the
   change is small enough that git's rename detection keeps
   `history --follow` unbroken. A local payload moves beside the new
   passport. Branches refuse (`E_SCHEMA`): move the leaves, one audited
   decision at a time — C.14's own rule against subtree operations in
   one call. Root and `_meta/*` never move; `new_id` obeys every rule a
   plant obeys (parent chain exists, id free, `expected_parent`).
2. **Every backlink is rewritten, or the call refuses.** The nodes that
   point at `id` (catalog `edges_in`) are edited to point at `new_id`,
   inside the same commit — and exactly as C.14 rule 6: an anchor
   outside the caller's scope refuses the whole call with a count,
   because a write the caller cannot see is a write it cannot have
   authorized. There is no `force` here: a move that stripped links
   instead of following them would be a prune wearing a move's name.
3. **The old address is a waymark.** `new_id`'s passport records
   `moved_from: [old ids]` (appended across chained moves) and the old
   id joins `aliases` (union, 16-cap, overflow counted) — so `locate`
   finds the old name forever. The redirect map is DERIVED from
   `moved_from` at indexing: the files are the truth, and a reindex
   rebuilds it (nothing lives only in `_derived`).
4. **A read of the old id answers `E_MOVED`, naming `moved_to`** — a
   read says what it did not do, and "it is not here" is half the
   truth when the other half is known. **Every read by id (v0.61):**
   `look`, `pick`, `move`, `history`, `view` and `query` alike. Stated
   generally in v0.58 and implemented in five of the six `pick` read
   the file directly and answered a bare `E_NOT_FOUND`, which is the
   call an agent holding a written-down id actually makes, so the
   waymark was missing from exactly the path it was built for. A
   redirect honoured by half a surface teaches callers not to trust it.
   HTTP 404 (it is not at this
   address); the envelope's `data` carries `moved_to`. Under a policy,
   the new address is disclosed ONLY when it lies in the reader's own
   scope; otherwise the answer is the byte-identical `E_NOT_FOUND` of a
   node that never existed — a waymark must not be a periscope into a
   region nobody granted.
5. **Heat follows the node, best effort.** The trails store re-keys the
   old id's heat to the new one; it is `_derived`, evaporation heals
   whatever a crash loses, and the pheromone was earned by the content,
   which did not change.
6. **Scope and capability:** `write`, gated on BOTH addresses — reading
   rule on the source (out of scope answers `E_NOT_FOUND` as absent),
   writing rule on the destination (`E_FORBIDDEN` naming the grant,
   C.7's own asymmetry). Audited with both ids; J.16 emits
   `node.transplanted` (identity only).
7. **The stores stay honest for free:** the sweep's reading fingerprint
   keys material by id, so a moved node misses cleanly and the fresh
   run reads the new address; the walk's HEAD key invalidates on the
   commit. Stated, not new machinery.
8. `graft`'s `set_parent` remains a refused unknown key: an address is
   not a field, and an edit that relocates is this primitive, audited
   as itself.

### C.16 `history(id: string, limit: int = 20) → History` (v0.58)

Every write has been a commit since C.7, and since v0.57 the acting
principal rides the commit itself — yet nothing on the surface could
read any of it back. The consumer team accumulated ten commits in one
session and put it plainly: git answers "what changed and who changed
it" better than the forest does. This primitive is that answer, on the
forest's own surface.

1. **The node's commits, newest first, through renames.** Backed by the
   repo's own log with rename-following, so a transplanted document's
   past does not begin at its move. `limit` ≤ 50, default 20; the
   response says `total` is unknowable cheaply and instead carries
   `truncated` + the oldest sha served — resuming deeper is Part I's
   territory (the bundle has everything).
2. **Each entry carries:** `commit` (sha), `at` (ISO 8601 **with time
   of day** — the intraday answer day-precision frontmatter could
   never give; D-01b closes here), `action` (the commit subject's own
   prefix: `plant`, `graft`, `tend`, `prune`, `transplant`,
   `gardener(...)`, `ranger(...)`, `init`, or the subject verbatim when
   it matches no convention), `message` (the subject line), and `by` —
   the attribution trailer's value when the commit carries one
   (`station-principal:`, the trailer J.4 defines; absent on engine-only
   writes, honestly).
3. **Read semantics throughout:** `read` capability, scope-gated like
   `look` (out of scope answers `E_NOT_FOUND` byte-identical to
   absent), token-budgeted (`BUDGET_HISTORY` = 800, whole entries drop
   from the tail with `truncated: true`), traced and heat-depositing
   like any read. A pruned id has no history to ask for (`E_NOT_FOUND`
   — recovery is Part I's, an operator act); a moved id answers
   `E_MOVED` like every read of a waymark (C.15 rule 4).
4. **Listing, never time travel.** `history` says what happened; it
   does not serve old bodies. Reading a document *at* a commit is
   deferred with the restore design (Part I) — a listing that also
   time-travelled would be two primitives wearing one name.

### C.17 `coverage(scope?: string, date_field?: string) → Coverage` (v0.59)

Every read in Part C says what it did not do. `locate` names the count it
searched; `look` names the field it clipped; `scan` returns `total` beside
`returned`; the sweep counts what it suppressed. None of that reaches the
question that comes *before* any of them: **what is in this forest at
all?**

A consumer agent asked a faithful question, received a faithful answer
built from a real document, and the answer was wrong about the subject —
because the branch holding the material had never been ingested. Nothing
on the surface could have told it so. A partial corpus produces an answer
in the exact shape of a complete one: cited, sourced, traced. `coverage`
is the read that makes the shape of the corpus askable.

1. **Metadata only, grouped in SQLite.** No file is opened, no body is
   read, and no count is computed one node at a time — every aggregate is
   one statement over the catalog, so a forest of forty thousand nodes
   answers in the same shape as one of forty (C.13.3's rule, for the same
   reason).
2. **A root is where the caller starts.** Unrestricted, the roots are the
   branch children of the forest's root `_index`. Under a policy they are
   the principal's own granted subtrees — the same list `forests()`
   publishes, so the two surfaces cannot disagree about where a session
   begins.
3. **Each root carries:** `id`, `title`, `nodes` (everything under its
   prefix, the root index included), `branches`, `first`/`last` (the
   oldest and newest date under it, in the requested `date_field` —
   `created` by default, `updated` the other, and **never** an "indexed"
   date, C.13's rule), `origin` when the material under it declares one,
   and `without_origin` — how many of its nodes carry none.
4. **`origin` is reported as the prefix `scan` takes.** The value is the
   longest common prefix of the origins under that root, ending at a
   URI path boundary, and it is exactly the string
   `scan(filter: {origin_prefix: …})` accepts (C.6). A caller must never
   have to construct it: the map names the strings the reads take, which
   is the contract C.13.3 gives windows.
5. **A partial origin is stated, never rounded.** `without_origin` exists
   because a root where nine nodes in ten know their source and one does
   not is not a root with an origin. A forest ingested before G.2.7 has
   no origins at all, and `coverage` must say that rather than omit the
   field and read as "no source".
6. **Totals beside the roots:** `total` (nodes in scope), `types`
   (`{type: count}`), `sources` (`{source: count}` over the `source`
   enum), `undated` (nodes with no date in the requested field, C.13.2's
   count), `system` (the dialect's own `_meta/` files, which are the child
   of no branch and therefore under no root), and `date_field`. A node
   with no value in a grouped column falls in no bucket — a column with no
   value is not a category — so a grouping need not sum to `total`, while
   the roots plus the listing's own index plus `system` always do.
7. **Under a policy every number is the policy's own.** Roots are
   `Policy.roots`; every aggregate is filtered by the policy's own
   prefixes as SQL (`Policy.sql_scope`), keyword-only and host-supplied,
   unreachable from the wire (G.2.5's construction). A global count here
   would describe the size and shape of a region nobody granted — a finer
   oracle than `locate`'s `searched`, which is already scoped for this
   reason.
8. **It says what is there; it never guesses what is not.** No `missing`
   list, no comparison against a source tree, no inference about what an
   operator meant to ingest. The forest can only testify about itself.
   What changes is that a caller reads the whole shape in one cheap call
   and draws the conclusion — "there is no `docs` root here, so ask
   somewhere else" — which previously required having the source tree
   mounted on disk.
9. **Read semantics throughout:** `read` capability, traced like every
   read, budgeted (`BUDGET_COVERAGE` = 800). Roots drop from the tail
   with `truncated: true`; **the totals never drop** — they are the
   answer's spine, and a coverage report whose total was clipped would be
   the failure it exists to prevent. It deposits no pheromone: it chose
   no node.
10. **`scope`** narrows the whole answer to one subtree — the roots
    become that branch's own children, and every total counts inside it.
    The same string `scan` and `sniff` take.
11. **A payload the forest names and does not have is counted (v0.61).**
    Each root carries `payload_missing` how many of its nodes declare a
    LOCAL payload that is not on disk and the totals carry the same
    number for the scope. It is the one integrity fact this primitive can
    establish without opening a file: the passport says the path, and the
    filesystem answers. A forest that announces `dataset: 2` while
    neither serves a query is announcing capacity it does not have, which
    is precisely the class of silence C.17 was created to end; the
    difference is that here the forest CAN testify, so it must. Remote
    payloads (G.9) are not counted: their absence is a fetch away and is
    not a fact the catalog holds. The count is filtered by the policy
    like every other number here (rule 7).

The field named `coverage` on a branch node (A.4) answers the same
question one level down — what this branch holds. The primitive is that
field for the forest.

## Part D Telemetry (feeds the pheromone and the Monkey Bench)

Every navigation session generates a trace in `_derived/traces/<session>.jsonl`, one event per primitive call: `{ts, session, primitive, id, tokens_in, tokens_out, elapsed_ms}`.

When the call obtained a query vector through K.2/K.6, the event also
carries `embed_ms` — the milliseconds of that embed, memo hits included
(a hit's near-zero is the memo working, and only this figure can say so).
`elapsed_ms` remains the whole span, embed included; an event for a call
that ran no embed carries no such key and is byte-identical to v0.67. A
pre-v0.68 event's absent `embed_ms` reads as "no embed ran", never as an
unknown share (v0.68).

At the end, the orchestrator MUST close the session with `outcome: {success: bool, answer_nodes: [ids]}`. This closing is what:
1. Increments `heat` along the whole winning trail (whisper);
2. Evaluates the shout (v0.6): when the session metric `trail_len` read
   calls made before the first harvest of an answer node is `>= 4`, the
   answer nodes come back in `suggest_shortcuts`, and the orchestrator MAY
   `graft` a `discovered-shortcut` from the hunt's entry node (C.8 applies);
3. Feeds the Monkey Bench metrics: **hops-to-banana** = number of `look`+`move` calls before the answer's first `pick`/`query`; **tokens-to-banana** = sum of session tokens_out; **banana precision** = correct answer_nodes / harvested answer_nodes; **trail_len** (v0.6) = read calls before the first harvest of an answer_node.

---

## Part E The Troop (Parallel Swarm Navigation)

N monkeys (navigator SLM instances) hunt the same banana in parallel, coordinated by **intra-session stigmergy**: they never exchange messages they smell each other's trails. The Vine is already N-readers by design (C.9); the Troop is an **orchestrator**-side component (the MCP client side), not the bank.

### E.1 Hunt protocol

1. **Frontier partition:** `locate(query, k=N)` → each monkey gets a distinct entry point (top-N results). Without partitioning, everyone explores the same trail and the parallelism is wasted.
2. **Session pheromone:** each monkey, upon judging a node promising (the SLM's own call: "relevant to the question? yes/no"), deposits `session_heat` in the hunt's scope (`_derived/trails.db`, session namespace). `locate`/`look`/`scan` inside the session apply `score x (1 + beta*session_heat)` monkeys gravitate toward regions where others found signal.
3. **Shared visited set:** `look`/`scan` digests already made in the session land in a shared cache; a monkey that would touch an already-visited node gets the cached digest instead (zero cost), and the orchestrator redirects it to unexplored frontier.
4. **Stop:** the hunt ends when (a) a monkey harvests a banana with high confidence (self-assessment above threshold), (b) the troop's hop budget runs out, or (c) the frontier empties. A **judge** (may be the main model itself) aggregates the harvests and synthesizes the answer.
5. **Post-session:** only the winning trail(s) convert `session_heat` into persistent `heat` (Part D). Losing trails evaporate with the session the swarm does not pollute long-term pheromone.

### E.2 Implementation notes

- **Concurrency:** asyncio in the orchestrator; the monkeys spend ~95% of their time waiting on inference. On the 3090, serving the N monkeys through the same inference server with *continuous batching* (vLLM/llama.cpp parallel slots) makes N=3-5 cost nearly the same wall-clock as N=1.
- **Sizing:** N=3 is the default; above N~5 returns diminish (frontiers overlap in small forests). N is a Monkey Bench parameter, not a constant.
- **New metric:** *troop speedup* = wall-clock hops (parallel rounds) vs the solo monkey's total hops, and total token cost (the troop spends more tokens in aggregate the speed x cost trade-off MUST be measured, not assumed).
- **Phase:** Troop is Phase 1.5 requires the full Vine + telemetry (Part D) working. Nothing in Phase 0 changes, except ensuring `trails.db` supports session namespacing (already anticipated in the trace schema).

## Part F Phase 0 Acceptance Criteria

Deliverable: Vine (MCP, Python) + a manual test forest (~100 nodes, 10 branches, >=1 SQLite dataset) + test suite.

1. All C.1-C.6b primitives functional with the exact contracts above (locate may be BM25-only), including `fields` in `look` and the Catalog serving `scan`.
2. `plant`/`graft` atomic with a Git commit and index update, verified by test.
3. Token budgets respected (tests with giant synthetic nodes verifying explicit truncation).
4. `query` rejects all write SQL (injection suite: `;DROP`, `ATTACH`, multi-statement, PRAGMA).
5. Demo: a local SLM (Qwen 7-14B Q4), given only the MCP tools and the master branch, answers 10 multi-hop questions about the test forest, with recorded traces and computed metrics.
6. Latency: p95 of `look`/`move`/`pick` < 10ms, `query` < 50ms, `locate` < 100ms, `sniff` < 100ms (local forest, NVMe).
7. `sniff`: finds a fact present ONLY in the body (invisible to `locate`), attributes the correct section, respects `scope`, normalizes case/diacritics, and rejects empty terms (`E_SCHEMA`) all covered by test.
8. Payloads outside Git (A.3.1): the Vine's commit ignores non-`.md` files even if requested, and the test forest's `git ls-files` contains no binary both verified by test.
9. `harvest` (C.6c): buried fact returns the right matched section under term-scarcity refinement; small bodies come whole; `k` and the 4000-token budget are honored with explicit truncation all covered by tests.
10. Forest registry (C.0): per-request forest selection works across two forests with isolated results; lazy first-touch open auto-indexes; path escape and non-forest directories are rejected; single-forest mode serves v0.3 clients unchanged all covered by tests.
11. `tend` (C.10): accepts only single-statement INSERT/UPDATE/DELETE (its own
    injection suite: DDL, ATTACH/PRAGMA, multi-statement, WHERE-less
    UPDATE/DELETE all rejected); refreshes `payload_hash` and commits only the
    `.md`; read-only Vine rejected; failed SQL leaves the payload untouched;
    `vine validate` warns on payload hash drift all covered by tests.
12. Dataset planting (C.7.1): declarative schema births a queryable payload
    (`look` shows the auto query manual, `query`/`tend` work immediately);
    name/type/limit validation rejects bad schemas (`E_SCHEMA`), including
    injection attempts via table/column names; existing payload is never
    overwritten; rollback removes the newborn `.db`; the commit carries only
    the `.md` all covered by tests.
13. Gardener (Part G): `adopt` of a mixed source tree (markdown, text,
    tabular) produces a forest that lints with zero errors folders
    mirrored as branches, passports carrying `source_path` + `source_hash`,
    non-text originals archived under `_assets/`, datasets born with rows
    loaded, no binary in the forest git; `sync` classifies new / changed /
    deleted sources by hash-diff with no false positives, updates changed
    passports through the audited write path, and never deletes; converter
    discovery honors the config-hook > entry-point > built-in order; an
    external command hook converts a file end-to-end; an `on_curate` hook
    can enrich a draft and a crashing hook does not abort the ingest all
    covered by tests.
14. Ranger (Part H): under a synthetic clock, one half-life halves heat and
    dust rows vanish; stale session scopes are cleared; promotion raises a
    well-used proposal's link confidence with an audited commit; pruning
    removes only cold, low-confidence links links with confidence 1.0 or
    without a link-level confidence are NEVER touched; the health report
    flags an oversized branch (`needs_split`), an over-linked node and a
    stale passport; repeated runs are idempotent all covered by tests.
15. Tiered storage (G.7/G.8): a `cached` adoption keeps node `.md`s body-
    free with the flesh in `_derived/bodies/` and OUT of git, while `pick`
    and `sniff` resolve it transparently; a `reference` adoption reads the
    source live; an unresolvable body fails with `E_NOT_FOUND` + hint
    while `locate`/`look` keep working (degraded map); `archive: never`
    creates no `_assets/` copies; `sync(path=...)` reconciles exactly one
    file; the mtime+size fast-path skips hashing unchanged files all
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
    them (promotable, prunable) all covered by tests.
17. Rollup + Landmarks (G.4.4 + H.7): rollup replaces only `source: ingest`
    branch summaries (hand-authored branches untouched unless `--all`),
    runs deepest-first so parents see fresh child summaries, falls back
    deterministically to an A.4-valid summary when the LLM fails, and
    propagates the new summary into the parent's `## Sub-branches` entry
    WITH the coverage suffix preserved; the Ranger populates the master
    `## Landmarks` with top-degree non-branch nodes, a second run with an
    unchanged graph produces no new commit, and degree-0 nodes never
    appear all covered by tests.
18. Station + ScopedVine (Part J): a fresh deployment plus one API key
    serves REST, MCP and Studio against a registry of two forests; the
    **leak suite** proves a principal granted only `projects/` cannot
    obtain the id, title, summary, body, edge or snippet of any node
    outside `projects/` through ANY primitive on ANY surface one test
    per primitive per surface, `harvest` and `move` included; an
    out-of-scope `look`/`pick` is byte-identical to the genuinely-absent
    `E_NOT_FOUND`; a scoped `locate`/`scan`/`sniff` returns the same
    response shape and budget fields as the unscoped call (filtering
    precedes truncation); writes through the Station carry the acting
    principal in the commit message and the audit log reconstructs a
    session's full trail; capability gates reject `query`/`tend`/`plant`/
    `graft` without the matching cap; and the engine suite passes with
    zero edits under `src/monkeyllm/` all covered by tests.
19. Per-forest inference (J.10): a provider's key is never returned by any
    surface (create, list, or re-edit) and an empty key on update keeps the
    stored one; a binding is refused for an unknown provider or an unknown
    role; removing a provider removes the bindings that pointed at it; the
    two roles can hold different models on the same forest; `answer` and
    `curate` refuse politely when no model is bound, and enforce the `read`
    and `write` capabilities respectively; and the load-bearing one for
    a principal scoped to a subtree, the material handed to the answering
    model contains no node outside that subtree all covered by tests.
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
    tree, its scope picker and its dataset list all covered by tests.
21. Credentials (J.2.1/J.2.2/J.5.4): a username and password exchange for a
    session token that authorises exactly what the same principal's API key
    would and no more; a Station with no `MONKEYLLM_STATION_PASSWORD` set
    has **no** password door rather than a default one; a password is
    stored only as a salted memory-hard hash and a principal without one
    cannot log in; an **expired** key, a **revoked** key and an unknown key
    are all rejected identically; `last_used_at` advances on a successful
    call; listing returns prefixes and never a secret, and a secret is
    returned exactly once at creation; session tokens do not appear in the
    token console; and the load-bearing one an administrator of one
    forest is refused when minting or revoking a key for a principal that
    also holds a grant on a forest they do not administer, so a token
    cannot be used to reach across the registry all covered by tests.
22. Per-forest administration and navigation (J.3.2/J.5.1): every
    `/v1/admin/*` route refuses a principal without `admin`, proven by a
    sweep that enumerates the routes rather than a hand-written list that
    a new route can quietly escape; and on a two-forest registry, an
    administrator of one forest sees **no** principal, branch prefix or
    audit entry belonging to the other while an administrator of both
    sees everything. Navigation lists exactly the permitted consoles for
    the selected forest, and each console still guards itself when reached
    with the capability missing all covered by tests.
23. Person-shaped governance (J.2.3/J.5.5): one `POST /v1/admin/people`
    creates a principal, grants it, sets its password and mints its key,
    and the resulting password logs in while the resulting key reads —
    proving onboarding needs one request; each step re-checks its own rule,
    so an administrator of one forest is refused the credential steps for a
    principal that also holds another forest **while the grant it was
    entitled to make still applies**, and the response names what was
    refused; clearing a password removes the sign-in; revoking all of a
    person's keys stops all of them at once; and `GET /v1/admin/people`
    returns only administered forests' grants and tokens all covered by
    tests. A grant naming **several** forests lands on each of them, so the
    key minted in the same request reads in every one; naming a forest the
    caller does not administer refuses that forest **by id** while the rest
    still apply; and a multi-forest `revoke_access` removes exactly the
    grants named also covered by tests.

24. The Gauntlet (Part K): with no embedder, an empty index, or an index
    whose recorded model differs from the embedder's, `look`, `move` and
    `scan` return **byte-identical** responses to the same calls made with
    the feature absent entirely proven by comparing the two, not by
    inspecting a flag; a mismatched index also turns hybrid `locate` off
    and is reported by validation rather than silently ranking across two
    vector spaces; when active, the frontier order changes, the response
    says it was conditioned and toward what, and the per-call opt-out
    restores the unconditioned order within the same session; and the goal
    is embedded once per hunt rather than once per hop all covered by
    tests.

25. Map projections (J.11): for a scoped principal, `GET /graph` returns no
    id the same principal cannot `look` at, every edge it returns has both
    endpoints in scope, and every `degree` it reports equals the degree
    computed from the returned edges alone proven by recomputing, not by
    trusting the field; `GET /trails` exposes persistent heat only, never a
    session scope; both flag `truncated` when a bound cut the answer; and
    the Explore console's graph, tree and file modes read only these
    endpoints and the Part C primitives all covered by tests.

Out of scope for Phase 0 (do not implement): embeddings/vectors, `same-as` compaction, S3/R2 sync, multi-writer, Troop (Part E Phase 1.5; only ensure session namespacing in trails.db). Automatic ingest left this list in v0.9 (Part G); evaporation and promotion/pruning left it in v0.10 (Part H).

---

## Part G The Gardener (ingest pipeline, spec v0.9)

The Gardener turns raw directories into forest. It is **trusted
infrastructure** (it runs with the operator's authority, not an agent's),
but it writes through the same audited mechanics as everything else: nodes
are born via C.7 `plant`, datasets via C.7.1, and only `.md` ever reaches
git (A.3.1). Four stages only one of them needs an LLM:

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
  (body is the converted markdown, original archived); tabular (CSV/XLS/
  XLSX/tabular JSON) → `dataset` (C.7.1 birth with schema + rows; original
  archived); **native SQLite (`.db`/`.sqlite`/`.sqlite3`) → `dataset` by
  adoption of the file itself as the payload** (G.2.2); audio/image/video →
  `media` (body is the transcript/description, original archived).
- Archived originals live in the node's branch under `_assets/` (gitignored
  per A.3.1), referenced by `payload` + `payload_hash`. Markdown/plain-text
  sources are NOT archived (the body is lossless).
- Node ids are deterministic slugs of the source-relative path (lowercase,
  ASCII-folded, `[a-z0-9._-]`); a slug collision appends a short hash. The
  id mirrors the source layout placement in `adopt` mode is structural,
  not an LLM decision (ids are immutable; deciding placement at birth is
  mandatory, see A.3).

### G.2 Converter contract (public plugin API v1)

A converter claims file extensions and produces either markdown or a
dataset description:

```python
class Converter(Protocol):
    extensions: set[str]            # e.g. {".docx"}
    def convert(self, path: Path) -> Conversion: ...

Conversion = markdown(title, body)                 # → note/document/media
           | dataset(title, schema, rows)          # → C.7.1 birth
           | payload(title, tables, samples)       # → G.2.2 adoption
```

The third kind (v0.44) says *"the source file is already the payload"*: the
converter reports the structure it read and the Gardener installs the bytes.
It exists for formats the forest speaks natively, and G.2.2 is the only
built-in that uses it.

Discovery order (first converter claiming the extension wins):

1. **Command hooks** from the forest's Gardener config (G.6) an external
   command template (`"{input}"`/`"{output}"` placeholders) that must write
   markdown; lets operators plug ANY tool (including copyleft-licensed
   ones) without it ever becoming a dependency of this project.
2. **Entry points**: packages installed in the environment declaring the
   `monkeyllm.converters` group (`pip install monkeyllm-whisper` just
   works). This is the third-party extension surface.
3. **Built-ins**: `.md`/`.txt` passthrough; `.csv`/tabular `.json` (and
   `.xlsx` when `openpyxl` is present, `.xls` when `xlrd` is) → dataset
   with inferred column types, one table per sheet (G.2.4);
   `.db`/`.sqlite`/`.sqlite3` → dataset by adoption (G.2.2, no optional
   dependency `sqlite3` is the standard library and already this
   project's payload format); `.docx` → markdown when `python-docx` is
   present (G.2.1). Built-ins MUST keep the core dependency-light and
   MIT-clean.

A file with no claiming converter is reported as `unsupported` never a
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
   `v:textbox`) content invisible to naive `paragraph.text` readers.
3. **Headings**: paragraphs styled `Heading N` (or `Title`) map to
   markdown `#`-headings (`Title`/`Heading 1` → `##` and deeper `#` is
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

#### G.2.2 SQLite adoption the file is the payload (v0.44)

`.db`, `.sqlite` and `.sqlite3` are the one source format a forest already
speaks: a dataset's payload IS a SQLite database (C.7.1 rule 5). The
built-in therefore does not convert it **adopts**.

Normative behavior:

1. **A payload conversion, not a dataset conversion.** The converter opens
   the source **read-only** (`mode=ro`), reads the structure of every table
   in `sqlite_master` (`PRAGMA table_info` for names and declared types)
   and the **first 3 rows of each** (G.2.3), and reports them. It never
   reads the whole file into memory: the largest thing it holds is
   `3 × columns` values per table.
2. **The bytes are copied, never re-inserted.** The Gardener installs the
   source file beside the passport as `<leaf>.db` the same location and
   the same `payload`/`payload_type`/`payload_hash` frontmatter a C.7.1
   birth produces and plants the node with no `schema`, which is the
   pre-existing "payload already on the filesystem" path (C.7.1 rule 2).
   Rebuilding the database row by row would be unbounded in the source's
   size, and lossy where the source's types, `WITHOUT ROWID` tables,
   views, indexes or BLOBs do not survive a `TEXT|INTEGER|REAL|BLOB`
   round trip. The destination of that round trip is byte-for-byte what
   the source already was.
3. **The C.7.1 schema limits do not apply.** They bound what a *model* may
   declare (≤ 10 tables, ≤ 50 columns, four types); an operator adopting a
   database they already own is not declaring anything. The map (G.2.3)
   is bounded instead, which is where the cost actually lives.
4. **A file that is not SQLite is an error, never a crash.** The 16-byte
   header (`SQLite format 3\0`) is checked before anything is opened;
   a mismatch is `E_SCHEMA` naming the file, reported per-file like every
   other conversion failure (G.2). An encrypted or corrupt database fails
   the same way, on the first read.
5. **Adoption is a copy the rollback owns.** If the plant fails after the
   file is installed, the copy MUST be removed C.7's atomicity extends
   to it exactly as it does to a newborn payload. On `sync`, a changed
   source replaces the payload whole and refreshes `payload_hash`,
   `source_hash` and the map, through the audited `.md`-only commit (G.3).
6. **`archive: always` does not double the file.** A payload conversion's
   original is its payload; copying it a second time into `_assets/` would
   store the same bytes twice under two hashes. The archive step is
   skipped for this kind, as it already is for C.7.1 births.

*Why not reference the source in place (informative):* because `sync` would
then be the only thing standing between a moved directory and a dataset
that answers `E_NOT_FOUND` to every question. Payloads are local to the
Vine by design (G.9.4); a remote or foreign-tree payload is the exception
that `content: reference` and the fetchers cover, not the default a folder
drop should get.

#### G.2.5 A count limit guards invention, not data (v0.45)

C.7.1 rule 1 caps a declared schema at 10 tables and 50 columns. That
guard is aimed at a **model**: an agent inventing a schema can invent a
thousand columns, and nothing downstream would question it. G.2.2 rule 3
already said the counts do not apply to an adopted SQLite file. The same
reasoning applies to every conversion, and it took a real 141-column ERP
export being refused to notice.

Normative:

1. **The Gardener's plants are `adopted`.** A schema the Gardener read off
   a source is exempt from the two COUNTS tables and columns and from
   nothing else. Names still match `^[a-z_][a-z0-9_]*$`, types are still
   one of the four, `primary_key` still references declared columns, and
   every one of those refusals still fires.
2. **Exemption MUST NOT be reachable from the wire.** It is a keyword-only
   argument of the library call, and the host's policy wrapper forwards
   only the node so a request body carrying it is an error, not a
   relaxed guard. A flag an agent can set is not a guard.
3. **The bound moves to where the cost is.** What a wide table actually
   costs is tokens in the body and in `look`, and G.2.3's caps are what
   bound those sampled columns, sampled rows, clipped cells. Refusing
   the *data* to protect a *rendering* was solving the wrong problem.
4. **Nothing about `tend` or `query` changes.** DML-only, read-only,
   single-statement, every injection guard exactly as it was. This is
   about how many columns a table born from a file may have, and nothing
   else.

#### G.2.3 The sample map (v0.44)

Every dataset passport's body from C.7.1 births, from the tabular
converters, and from G.2.2 adoptions alike carries two generated
sections:

```markdown
## Query manual

Tables:
- `findings_raw(page TEXT, type TEXT, detail TEXT)`

Example queries:
- `SELECT * FROM findings_raw LIMIT 5`
- `SELECT COUNT(*) FROM findings_raw`

## Sample rows

### findings_raw 490 rows

| page | type | detail |
| --- | --- | --- |
| /login | error | submit returns 404 |
| /login | warning | password field has no autocomplete |
| /admin/users | error | table renders before the fetch resolves |
```

Normative rules:

1. **Structure and contents, for every table.** The manual names each
   table and its columns with declared types; the sample names each table
   and shows its **first 3 rows** (`SELECT * FROM <t> LIMIT 3`, no
   `ORDER BY` the file's own order is the cheapest and the most
   honest). "Every table" is the point of the whole section: a database
   whose second table is the one being asked about is not mapped by its
   first. **Tables, in name order**: views are excluded because C.2's
   `query_manual` excludes them, and a body claiming a view the digest
   never mentions is two answers to one question; name order keeps the
   map stable, so a `sync` rewrites it when the data moved and not when
   SQLite happened to reorder its catalog.
2. **This is what `sniff` reads.** `locate` searches curated metadata and
   `sniff` searches bodies (C.6b), so a value that appears nowhere but
   inside the payload is invisible to both a `.db` is opaque to every
   text primitive the forest has. Three rows per table put the *shape of
   the values* into the body: the vocabulary, the id format, the date
   format, the units. It is not a substitute for `query`; it is the scent
   that tells an agent which dataset to `query`.
3. **Bounded by construction, and never silently.** ≤ 3 rows per table;
   **≤ 12 columns per sampled row**; each cell clipped to 120 characters
   with `…`; BLOBs rendered as `<blob N bytes>`, never as their bytes;
   NULL as an empty cell; pipes and newlines escaped so the table stays a
   table. At most **20 tables** get a sample section. Whenever a cap cuts
   tables or columns the section MUST state how many were left out. A
   map that quietly stops is worse than a short one.
   The column cap is where the real cost lives (v0.45): a 141-column
   export sampled whole would put three rows of 141 clipped cells into the
   body and into every `look` of it. The **manual still names every
   column** that is the structure, and an agent needs it to write SQL —
   while the sample shows the leading ones.
4. **Generated, never curated.** Both sections are rewritten whole by the
   Gardener whenever the payload is rebuilt or replaced (G.3), and only
   those two sections are: a curator's own headings in the same body
   survive untouched. A caller-provided `## Query manual` at plant time is
   still kept verbatim (C.7.1 rule 4) an author who wrote the manual
   owns it.
5. **The summary names the tables, not just the first one.** G.4.1's
   derived summary for a dataset MUST count the tables and name as many as
   the A.4 budget holds. "Table X with 6 rows" for a twelve-table database
   is a scent for the wrong thing.
6. **A wide table says it is wide (v0.47).** When a table has more columns
   than the sample shows, the manual MUST state the count and that
   `SELECT *` will not fit C.5.1's budget. The agent otherwise learns this
   by spending a hop on a truncated result which now works, but a map
   that could have said so beforehand and did not is a map withholding
   something it knows.

   This is the boundary of what the Gardener is allowed to contribute, and
   it is a sharp one. **Column count is arithmetic; column relevance is
   meaning.** The Gardener MUST NOT name "the important columns", order
   them by likely usefulness, or otherwise decide what the data is *for* —
   it does not know, it would be confident anyway, and rule 4 already
   forbids it inventing rather than reading. Which columns answer the
   question is `## Notes` (C.2.1), written by somebody who knows. The
   manual still names **every** column: that is structure, and an agent
   cannot project without it.

#### G.2.4 Workbooks are multi-table (v0.44)

`.xlsx` (openpyxl, MIT) and `.xls` (xlrd, BSD-3 optional `ingest` extra,
same gating pattern) convert **every** sheet: one table per sheet, named
by the slugified sheet name, deduplicated. The first non-empty row of each
sheet is its header; empty sheets are skipped. Taking sheet one and
dropping the rest is how a spreadsheet arrives in a forest missing the
data somebody adopted it for.

**A workbook's declared extent MUST NOT be trusted (v0.45).** The `.xlsx`
format carries a `<dimension>` record naming the used range, and a
read-only reader believes it but files written by anything other than
Excel (exports, report generators, spreadsheet libraries) routinely
declare `A1:A1` or omit it entirely. A real 130-row sheet then arrives as
one row and the file is reported as a workbook with no data: a correct
message about a wrong reading, which is the worst kind. The extent MUST be
inferred from the rows actually present.

A workbook with no sheet holding more than a header row is `E_SCHEMA`
naming the file reported per-file like every other conversion failure,
never a crash. There is **no cap on sheets or columns** here; see G.2.5.

#### G.2.6 The team's own name for a document (aliases, v0.54)

Every project that files documents under a convention has a vocabulary the
files themselves never spell. A task living at
`tasks/back-end/291-provider-budget.md` is called **`BE-291`** in every
conversation, commit and cross-reference — and that token is in no title,
no summary and no body, so `locate` returns nothing and `sniff` returns
the *neighbours*: the documents that cite `BE-291`, wearing scores and
snippets and the full costume of a correct answer. For an LLM consumer
that is the worst failure shape this product can produce — plausibly wrong
beats visibly empty (C.1.1 exists because of the second; this rule exists
because of the first).

The passport has carried `aliases` since A.3, and `locate` has indexed it
at weight 3 — between title and tags — since the catalog existed. What was
missing is a writer. The Gardener now derives aliases at draft time:

1. **What the source states about itself is derived; what only an
   operator knows is declared (v0.59).** The first version of this rule
   required the `aliases:` map for anything at all, and the field showed
   the cost: in a forest where every document has a canonical code,
   **1,877 of 1,877** ingested nodes carried no aliases, and the most
   frequent access in that forest fell through to the path measured ~100×
   slower — while the skill was busy calling `aliases` "the findability
   lever" and telling agents to fill it by hand. The corrected boundary
   is not "no map, no aliases"; it is **who knows the name**. A code the
   document prints in its own title is procedence, and reading it back is
   not the engine acquiring content vocabulary — the engine invents no
   words, and it must never derive from a table of conventions it carries
   itself (that would be the G.4.5 violation this rule guards). A
   convention the material does not state — *`back-end` means `BE`
   because a team decided so* — still lives in `gardener.yaml`'s
   `aliases:` map, which is the forest's own config.
2. **The derivation is mechanical, deterministic, and has four sources.**
   For a source file whose stem starts with digits `N`, in folder `F`:
   - **the bare number** `N` — how a document is referred to inside its
     own folder, and the cheapest of all;
   - **the path form** `F/N`;
   - **the declared prefix** `P-N`, when `gardener.yaml` maps `F` to `P`.
     The operator's declaration wins and **suppresses the next rule**: a
     convention stated is not a convention to be guessed alongside;
   - **the folder's initials** `I-N`, when no map covers `F` and `F` is a
     compound name (two or more parts separated by `-` or `_`), `I` being
     the uppercased first letter of each part: `back-end/291` → `BE-291`.
     A single-word folder derives no prefix — one letter is not a name,
     and inventing `T-291` from `tasks` would put noise in the field the
     forest is most often searched by.

   Independently of the file's number, the draft also gains **every code
   in the shape `LETTERS-DIGITS`** (2–6 capitals, a hyphen, 1–6 digits)
   appearing in the document's **title or its H1** — `ADR-0002` names
   itself, and a document stating its own name is the least ambiguous
   source there is. Bodies below the H1 are not scanned: a code inside
   prose is usually a reference to a *different* document, which is
   exactly the neighbour-instead-of-target failure this rule exists to
   end.

   Derived aliases are deduplicated preserving first occurrence, ordered
   deterministically (declared before derived, prefixed before bare), and
   an unnumbered file in an unmapped folder with no code in its title
   still derives nothing — honestly, rather than by inventing a name for
   a document that has none.
3. **`sync` adds, never removes (v0.56).** v0.54 said a changed
   convention is applied by re-adopting — and the field showed what that
   costs: an operator added the `aliases:` map to a live forest, ran
   `sync`, and nothing happened, because the fast-path (G.8) skips
   unchanged sources and the config is not part of what it compares. A
   config edit was invisible exactly where it was aimed. `sync` now
   recomputes the DERIVED aliases for every visited passport — fast-path
   included; the derivation is two string operations, the conversion is
   what the fast-path saves — and **unions** the missing ones into the
   frontmatter. Union, never replacement: adding a name is not rewriting
   somebody's edit, removing one is, so hand-added aliases survive every
   refresh and removal stays a human act (`graft`, rule 4). Existing
   aliases are never displaced by the 16-alias cap (C.8); derived forms
   that no longer fit are dropped and counted in the sync report
   (`aliases_clipped`), never silently.
4. **The backfill is `graft`.** `aliases` is mutable frontmatter (C.8,
   v0.54), so an already-ingested forest is repaired by writes, not by
   re-ingesting. Curation MUST NOT touch aliases: a model inventing a
   team's naming convention is the hallucination G.4.2.1 exists to
   prevent, in a smaller costume. **And the backfill MUST be reachable
   without the source tree (v0.61):** every input to this derivation the
   source path and the title is recorded in the passport, so the repair
   needs no directory, no converter and no model. It was nevertheless
   reachable only through `sync`, which resolves a host root and requires
   `admin` over it and a forest of 1,877 nodes therefore had the feature
   in the code and not in the corpus, which is the only place it counts.
   J.13.6 is that pass.
5. **A derived number is a whole leading segment (v0.61).** Rule 2 derives
   from "a stem that starts with digits", and the test did not require the
   digits to end: `9router-free-ai-router.md` derived the aliases `9` and
   `x/9`. A single digit is not a name it is a token that enters the one
   index searched by curated metadata alone, matches broadly and ranks,
   which is noise with authority in exactly the field this rule exists to
   make trustworthy. The leading digits MUST be followed by a separator
   (`-`, `_`, `.`, or whitespace) or by the end of the stem. `291-provider-
   budget` still derives `291`, `BE-291` and `back-end/291`; `9router`
   derives nothing from its number, and its title's own code (rule 2's
   last paragraph) is unaffected.

#### G.2.7 The Gardener records where it came from (`origin`, v0.58)

v0.57 gave the passport `origin` and only agents wrote it — yet the one
writer who always KNOWS the origin is the ingest pipeline, which was
recording `source_path` (its own bookkeeping, relative to a root only
the Gardener remembers) and telling the reader nothing. Three rules:

1. **Adopt and refresh fill `origin` with the source file's URI**
   (`file://…`, absolute, percent-encoded — the A.3 validation passes by
   construction). An upload staged under `_derived/` gets the entry's
   declared `source_url` instead (J.8's provenance, already validated)
   — and nothing at all when none was declared: a path inside the
   staging area is a fact about plumbing, not about the document.
2. **Only when absent.** An operator's or agent's hand-written `origin`
   outranks a derived one and survives every `sync` — G.2.6's union
   rule, applied to one scalar. The fast-path applies the same
   `setdefault` it applies to aliases, so a forest ingested before this
   rule gains origins on its next sync without re-conversion.
3. **Curation MUST NOT touch it** (G.2.3 rule 4's spirit): an origin is
   a fact, and a model's guess about facts is the failure this pipeline
   exists to filter out.

**Extension surface is edges-only (normative):** converters and curation
hooks extend what goes INTO the forest. Nothing extends the primitives'
semantics, token budgets, or security guards (`query`/`tend` validation,
A.3.1, C.9 locking). UIs, upload receivers and automations are clients of
the MCP server or of the Python library they require no plugin API.

### G.3 `adopt` and `sync` (the brownfield engine)

- **`adopt(source_dir, dest?)`** mirrors an existing tree: each source
  directory becomes a `branch` (planted before its children), each file is
  converted and planted as its passport under the mirrored branch.
  Deterministic: stable ordering, slug ids, no LLM in the loop. `dest`
  roots the mirror under an existing branch (default: forest root).
- **`dest` names a branch, in either of the two spellings a branch has
  (v0.61).** A branch's id ends in `/_index` and that is how it is named
  everywhere else on the surface `scan("tasks/_index")`, `parent:
  "notes/_index"`, `coverage`'s roots so `dest` MUST accept
  `tasks/_index` and `tasks` as the same destination, and `_index` alone
  as the forest root. Before this it accepted only the bare form and the
  canonical one produced `tasks/_index/_index`, refused with an
  `expected_parent` that named the exact string the caller had sent: the
  advice was to do what had just been done, which is a refusal nobody can
  act on. Normalisation happens once, at the boundary, before scope is
  checked against it (J.8) so the scope test and the write agree about
  which branch is meant.
- **`sync(source_dir?)`** re-walks the source (default: the adopted root
  recorded in config) and hash-diffs against the passports' `source_hash`:
  - **new** file → adopt it;
  - **changed** hash → re-convert; the passport's body, `source_hash`,
    `payload_hash` (datasets are rebuilt; an adopted SQLite payload is
    replaced whole, G.2.2 rule 5) and `updated` are refreshed
    through the Gardener's audited write path a git commit
    `gardener(sync): <id>` of only the `.md`. Curated frontmatter
    (summary, tags, links, confidence) is PRESERVED, and for a dataset
    **the two map sections are rewritten and nothing else in the body is**
    (G.2.3 rule 4): a payload that changed under a sample that did not is
    a stale claim with a commit behind it, and a curator's own sections
    are not the Gardener's to overwrite;
  - **deleted** source → the passport is reported `stale`. The Gardener
    NEVER deletes nodes; pruning is the Ranger's call (tombstone policy,
    out of scope here).
- Continuous watching (filesystem events) is a Ranger-era concern; v1 sync
  is on-demand and deterministic.

**Source containment (normative, v0.26).** Both entry points resolve their
source through one gate, because two gates drift:

1. **A source is always named.** `adopt` requires one; `sync` takes the one
   `adopt` recorded. When neither exists the call is `E_SCHEMA` an
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
**host** will open on a caller's behalf, is J.8.2 a shell user is
already standing on the filesystem and is not subject to it.

### G.4 Curation (the only LLM stage always skippable)

Stage 2 enriches the draft node before planting:

1. **Without an LLM** (default in v1): summary derived from the converted
   content's first sentences (≤ 60 tokens, A.4-validated, with a safe
   fallback), `source: ingest`, `confidence: 0.7` (unreviewed), default
   tags from config. The pipeline never blocks on a missing GPU.
2. **With an LLM** (Gardener v2): A.4 summary with validate-and-retry,
   tags, edge proposals at link-level `confidence: 0.3` (G.4.2.1), guided
   by the **curation directives** in the forest config free-text criteria
   the operator wants the Gardener to "keep an eye on" (e.g. "prioritize
   contract numbers and client names in summaries"). Entity EXTRACTION
   (minting new `entity` nodes) is deferred past v0.12: it needs a
   placement policy and a `same-as` dedup story first.
3. **`on_curate` hooks**: plugins (entry-point group `monkeyllm.hooks`,
   name `on_curate`) and/or locally registered callables receive the draft
   (dict) and may mutate it. Hooks run in discovery order; a raising hook
   is logged into the report and SKIPPED a broken plugin never aborts an
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
2. **The model picks from the list or picks nothing.** Anything outside
   the offered ids is dropped (the hallucination guard is structural, not
   a prompt instruction). Picking nothing is a valid, common answer:
   relatedness must be visible in the two summaries.
3. **Every proposal is `rel: related-to`** (symmetric, generic A.2) with
   **link-level `confidence: 0.3`** and MAY carry a short free-text `note`
   (kept out of the summary budget; helps the Ranger's audit trail). Other
   rels (`mentioned-in`, `same-as`, …) are NOT proposable in v0.12 they
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

#### G.4.6 The dataset's scent comes from its map (v0.45)

Curation skipped `type: dataset` because a dataset had nothing to read: no
body, and a column list that the G.4.1 template already stated better than
a model would. G.2.3 changed the input every dataset passport now carries
its structure and the first three rows of every table so the reason is
gone and the cost of reading it is known in advance.

Normative:

1. **The Curator curates a dataset from its map, and from nothing else.**
   Not the payload, not the source file, not a sample it takes itself. The
   map is already in the draft when curation runs (stage 2 follows stage 1),
   it is bounded by G.2.3 three rows per table, cells clipped, a stated
   table cap and that bound is what makes this safe: **a 5 MB CSV and a
   5 GB database cost the model the same few hundred tokens.** An ingest
   whose model cost scaled with the source would be an ingest nobody can
   run on real data.
2. **The fallback is unchanged.** A refused, malformed or absent answer
   leaves the G.4.1 factual template in place and counts as a fallback,
   exactly as it does for a document. Ingest never blocks on a model
   (G.4), and that is not weakened here.
3. **Curation writes `summary` and `tags`, never the body.** The two
   generated sections are the Gardener's (G.2.3 rule 4) and a model
   rewriting them would put unverified rows where a reader expects the
   ones that are in the payload. Edge proposals (G.4.2.1) apply to a
   dataset exactly as they do to any other node.
4. **Why it is worth a model call at all.** A.4 makes the summary the
   scent every hop navigates by, and `locate` searches curated metadata
   only (C.6b). "Adopted from source; pending curation" is therefore what
   an agent reads when deciding whether this dataset can answer the
   question for the one node type whose contents it cannot otherwise
   see.

#### G.4.4 Branch rollup (v0.13)

Curation gives every banana a scent; rollup gives every REGION one. After
the per-node curation stage of an `adopt`/`sync` (or on demand), the
Gardener MAY rewrite branch frontmatter summaries bottom-up:

1. **Scope**: only branches with `source: ingest` the Gardener rewrites
   what the Gardener planted, nothing else. An explicit operator override
   (`--all`) MAY widen the scope to every non-`_meta` branch.
2. **Order**: deepest branch first (by id depth), so a parent's rollup
   always sees its sub-branches' fresh summaries.
3. **Input**: the branch's own `## Sub-branches` and `## Direct bananas`
   entry lines (which replicate child summaries verbatim, A.5), clipped to
   the curation content budget. The model never reads child bodies —
   rollup is O(branches) LLM calls with bounded prompts.
4. **Output contract**: an A.4-valid summary (1-3 sentences, ≤ 60 tokens)
   answering the A.5 blockquote question what lives here + where to go
   if it is not here. Validate-and-retry as in G.4.2.
5. **Fallback**: any failure (bad JSON, invalid summary after retries,
   transport error) falls back to a deterministic summary composed from
   child titles and counts the pipeline never blocks and never leaves a
   branch worse than the template it had. Counted in the Curator's stats.
6. **Write path**: C.8 `graft` on the frontmatter `summary` atomic,
   `.md`-only commit, catalog upsert, and VERBATIM propagation of the new
   summary into the parent's `## Sub-branches` entry (coverage suffix
   preserved, A.5). No new write machinery.
7. **What rollup is NOT**: it never creates nodes or links, never touches
   bodies (`## Cross trails` stays hand-authored), and never runs without
   an operator asking for curation (it is part of the always-skippable
   LLM stage).

### G.5 Media (multimodal by proxy)

Audio/image/video go through the SAME converter contract: the converter
(e.g. a Whisper transcriber, a vision-model describer extras or hooks,
never core dependencies) returns markdown that becomes the `media`
passport's body. The forest's job is **finding** media fast: `locate`/
`sniff` search the textual proxy; a multimodal client that wants full
fidelity follows `payload` to the raw file. Text to find, binary to
consume. Serving payload bytes over MCP to multimodal clients is the
`view` tool (C.6d, v0.48): found by its prose, read in its pixels.

### G.5.1 The stub and the describer (v0.48)

Before this version an image was `unsupported`: no converter claimed
it, so a screenshot the single most common thing a person clips —
fell out of the report. Two pieces fix that, split exactly along the
engine/host line.

**The stub (engine, built-in).** A built-in converter claims image
extensions (`.png .jpg .jpeg .gif .webp`) and audio extensions
(`.mp3 .wav .m4a .ogg .flac`) and returns markdown: an H1 from the
filename and a body that states plainly what is known the format,
the size, and that no description is available yet. The Gardener
plants it as **`media`**, not `document`: the typing rule becomes
*text source → `note`; payload type `image`/`audio` → `media`;
otherwise → `document`*. An image is never `unsupported` again, with
or without a model.

**The describer (host, injected).** A forest may bind a model to the
new **`vision`** role (J.10). When one is bound, the host injects a
describer converter for the image extensions that sends the image to
the bound model and returns its description as the body: what the
image shows, and **any legible text in it** that is what makes a
slide, a whiteboard or a flowchart findable by `sniff`, which reads
the textual proxy and nothing else (G.5). A describer that fails —
endpoint down, image refused, over budget MUST fall back to the
stub: G.4.3's rule reaches conversion too, a broken model never
aborts ingest. Audio keeps the stub until a transcriber role exists;
G.5 already names that future.

**The seam (public API v1, additive).** Injected converters enter
through a new `extra_converters` argument to the Gardener, ranked
**after the operator's command hooks and before entry points and
built-ins**: an operator who configured their own `.png` command hook
keeps it; everyone else gets the describer over the stub. Nothing
else about G.2 discovery moves, and the engine itself still never
holds a model: the describer lives in the host.

**The describer holds a lane (v0.48).** Its call runs inside the
convert stage of a step, and a step holds the forest's one lane (J.9):
every read on that forest every console open on it waits behind
it. The describer's request MUST therefore carry a timeout of at most
**60 seconds**, and a timeout falls back to the stub like any other
failure, with the reason in the report's `errors`. The 180-second
patience that suits a chat surface is a frozen panel here; a
deployment that wants slower vision buys it consciously, never by
default.

**The staging amendment (G.7).** `archive: never` keeps durable
originals at the source, and stays the default. But an *uploaded*
source is staged under the forest's `_derived/` disposable and
rebuildable by contract so a media node referencing it would
outlive its own bytes. Media whose source root lies inside the
forest's `_derived/` MUST be archived into `_assets/` and referenced
as payload regardless of the archive policy: there, the payload is
the only copy that exists. A durable disk source under
`archive: never` is still referenced, not copied, exactly as G.7
says.

**F.48 (acceptance).** A `.png` adopted with no vision binding plants
a `media` node with a stub body never `unsupported` and, when
staged through `upload`, carries the original under `_assets/` as its
payload even under `archive: never`. The same `.png` with a bound
`vision` role plants the model's description as the body, and a
describer that raises falls back to the stub with the failure in the
report's `errors`. An operator command hook on `.png` wins over the
injected describer. All covered by tests.

### G.6 Gardener config (`_meta/gardener.yaml`)

Operator-level configuration, read by the Gardener (not a node `_meta/`
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

The forest's three tiers: SCENT (passport frontmatter always local, in
git), FLESH (full converted text), BONE (raw binaries stay at the
source). The `content` policy decides where the FLESH lives:

- **`inline`** (default): the converted body lives in the node `.md`
  (v0.9 behavior git-versioned content; right for normal corpora).
- **`cached`**: the node `.md` holds only the title stub and the
  frontmatter marker `content: cached`; the converted body is written to
  `_derived/bodies/<id>.md` OUT of git. Right for huge corpora.
  Regenerable: re-running `sync` while sources are reachable rebuilds the
  cache (the body is a function of source + converter).
- **`reference`**: no local body at all; the body IS the source file,
  read live at harvest time. ONLY valid for passthrough text sources
  (`.md`/`.txt`); marker `content: reference`.

Normative semantics:

1. **Lazy resolution**: `pick` (and `sniff`, when it reaches such a node)
   resolves the body from the cache file (`cached`) or from
   `source_root/source_path` (`reference`). The resolution is transparent
   same response shape, same budgets.
2. **Degraded mode is explicit**: when the body cannot be resolved
   (source share down, cache purged), the read fails with `E_NOT_FOUND`
   and a hint naming the missing backing file. The MAP keeps working —
   `locate`/`look`/`scan`/heat never depended on the body.
3. `look`'s `outline` MAY be empty for non-inline nodes (the digest comes
   from the catalog; spending I/O to outline a remote body would break
   the <= 500-token cheapness contract).
4. Summary derivation and LLM curation (G.4) always see the FULL
   converted text at ingest time the scent quality does not depend on
   the content policy.
5. **`archive`**: `never` (default) durable sources are not copied into
   `_assets/`; `source_path` + `source_hash` are the reference. `always`
   inbox mode: the source will vanish after ingest, archive the
   original (v0.9 behavior). Datasets keep their local `.db` payload
   under every policy (G.9).
6. **Containment (normative, v0.26)**: the resolved backing file MUST lie
   underneath `source_root`; otherwise the read fails as rule 2's
   `E_NOT_FOUND` and the hint MUST NOT quote what was found there.
   `source_path` is ordinary frontmatter the Gardener writes it, and
   `plant` accepts it like any other extra field so a node can name a
   path its author chose. Without this rule `pick`, a read primitive
   available to any principal holding `read`, resolves arbitrary host
   files with the Vine's authority and reports them as the node's own
   body. The check happens after resolution, so `..` and symlinks are
   already collapsed.

### G.8 Targeted sync & triggers (v0.11)

- **`sync(path=...)`** reconciles a single source-relative path (new,
  changed or deleted) without walking the whole tree the building block
  for event-driven updates.
- **Containment (normative, v0.26)**: `path` is relative to the source
  root and MUST resolve underneath it; an absolute path or one that
  escapes is `E_SCHEMA`. The comparison MUST be made on the **resolved**
  path. A lexical check passes `../../etc/passwd` joined onto the root
  it still *starts* with the root, so a purely textual "is it relative to"
  answers yes, the file is read, and its slugified `..` segments become a
  branch. Events arrive from watchers, webhooks and queues (below), which
  is to say from outside; this path is caller input like any other.
- **Fast-path (normative)**: passports record `source_size` and
  `source_mtime`; a sync visit MUST skip hashing when both match the
  stored values (rsync's trick re-hashing 2 TB per cycle is the real
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
   a hot knowledge base needs sub-millisecond reads object storage
   holds `.db` files only as backup or cold-archive tiers. A cold
   dataset's first `query` pays one download; the cache absorbs the rest.
3. Remote sync uses the store's own change signals (ETag listings)
   instead of downloading to hash.
4. **`tend` rejects remote payloads** (`E_QUERY_FORBIDDEN` with hint):
   writes belong to the local-first tier editing a cached copy of a
   remote database would fork it silently. Reads (`query`, `look`'s
   dataset digest) work through the cache transparently.
5. **Region prefetch (the parachute warms the camp)**: `prefetch(scope)`
   downloads every remote payload under a branch in one sweep the
   orchestrator calls it right after `locate` drops the monkey, so the
   subsequent `sniff`/`query` hops run at local speed. Combined with H.6
   eviction, the payload cache converges to the shape of the pheromone:
   hot regions stay warm, cold regions evaporate from disk.

The MAP itself (passports + the forest git) stays local to wherever the
Vine runs it is the truth, it is ~0.1% of the source, and remote
clients reach it through the MCP server, not by replicating it. Moving a
map between machines is what snapshots are for (Part I). `catalog.db` and
`trails.db` remain disposable caches OF the local map (C.6.1) they are
never the only local copy of anything.

### G.10 Ingest yields (v0.32)

`adopt` and `sync` were always a loop over documents with a config save at
the end; G.10 makes the loop's step boundary part of the contract, because
a host that wants to interleave other work with a batch or count its
progress needs the seam the loop already had.

`adopt_iter(source, dest?)` and `sync_iter(source?, dest?, path?)` return
**step iterators**: each step converts, curates and plants **exactly one
source file**, then yields a progress record

```json
{"file": "guides/setup.md", "index": 3, "total": 41, "action": "planted"}
```

where `index` counts steps taken (so it is also "done"), and `action` is
one of `planted`, `updated`, `unchanged`, `unsupported`, `error`, `stale`,
`skipped`. Construction is eager where iteration is lazy: resolving the
source with the G.3/G.8 errors that entails and walking it happen at
the call, so a bad source fails **before any step runs** and the iterator
knows its `total` up front; a host can therefore refuse, or promise
progress out of `total`, before accepting the batch (J.9). Walking is
filesystem work; no document is touched until the first step. Once
exhausted, the iterator's `result` is the unabridged `IngestReport` of
G.3. Normative rules:

- **`adopt` and `sync` MUST remain "drain the iterator and return its
  report".** One pipeline, two paces. A second code path that batches
  differently from how it steps would drift, and the drift would be
  invisible until a sync disagreed with the adopt that preceded it.
- **A step is a whole document** converter, curation (G.4, model round
  trip included), content policy (G.7) and plant. Yielding mid-document
  would suspend an open model call or a half-planted node on the goodwill
  of a consumer that may never resume; yielding between documents suspends
  nothing, because C.7 already made each plant atomic and committed.
- **The source root is recorded before the first step, not after the
  last.** An abandoned run a crash, a cancel (J.9) leaves the files
  already stepped planted and committed, and the recorded root is what
  lets `sync` finish the remainder through the G.8 hash diff instead of
  the operator starting over. Recording it last, as v0.31 did, made every
  interrupted adopt a forest with no memory of where it came from.
- **Abandonment is safe at every yield.** No step depends on a later one:
  branch indexes are grafted as each document needs them (G.3), so an
  iterator dropped at step *k* leaves exactly the first *k* documents in
  the forest, correct and committed, and nothing else.
- `dry_run` composes unchanged: a preview Gardener steps and yields the
  same way and writes nothing (J.8.1's object-level guarantee), with
  drafts accumulating on the report exactly as before.
- The CLI and every existing caller keep calling `adopt`/`sync`; the
  iterators add a pace, not a mode. Converters, hooks, budgets and guards
  are exactly as extensible and no more as G.2 already says.

#### G.10.1 The stage inside the step (v0.45)

A step is a whole document, and the rule above says why: yielding
mid-document would suspend an open model call or a half-planted node on a
consumer that may never resume. That objection is about **suspension**, not
about visibility and a batch of one large document is one step, so a
consumer counting steps shows nothing at all until it shows everything.
An operator cannot tell that from a hang.

The Gardener therefore **names the phase it is in** without pausing in it.

`Gardener(vine, …, on_stage=…)` takes an optional observer called as
`on_stage(file, stage)` as the current document passes through the closed,
ordered list

```text
convert  →  curate  →  plant
```

Normative rules:

- **A stage is reported, never yielded.** The observer is called from the
  thread already doing the work, between operations that are already
  sequential there. Nothing is suspended, nothing is resumable, and the
  G.10 step boundary is exactly where it was. A consumer that ignores the
  observer sees the v0.32 contract unchanged.
- **The observer MUST NOT be able to affect the ingest.** A raising
  observer is swallowed and the batch continues, like a broken `on_curate`
  hook (G.4.3). Progress reporting that can abort the work it reports on
  is worse than no progress reporting.
- **Stages are closed and ordered, so a fraction is honest.** A consumer
  MAY render position within a document as `stage index / stage count`,
  which is what lets a one-document batch move at all.
- **A skipped stage is passed, not pending.** Not every document reaches
  every stage an unsupported file stops at `convert`, an `unchanged`
  file never leaves it so a consumer MUST NOT wait for a stage that will
  not come. The step's own `action` (G.10) remains the truth about what
  happened; a stage says only where the work is.
- **Stages are not a report.** They are transient, they are never counted
  into the `IngestReport`, and they are never written into a forest the
  same boundary J.9 draws around job records.

**J.9 amendment.** A job record carries `stage` beside `current`: the phase
of the file named by `current`, `null` between documents and on a finished
job. It is host memory like every other field of the record, so reading it
still touches no forest, and a restart still forgets records without
forgetting work.

---

## Part H The Ranger (maintenance, spec v0.10)

The Ranger keeps the forest healthy over time. The compounding loop only
works if the pheromone can also **forget**: without evaporation every trail
saturates at `heat = 1.0` and the whisper stops discriminating; without
pruning, agent proposals pile up as permanent noise. The Ranger is trusted
infrastructure (operator authority): evaporation lives entirely in the
derived layer; every node edit goes through the audited `.md`-only commit
path.

### H.1 Heat evaporation (derived layer only no commits)

- Persistent heat decays exponentially:
  `heat' = heat × 0.5^(Δt / half_life)`, where `Δt` is the time since the
  row's `updated` timestamp. Default `half_life_days: 30` (config H.5).
- Rows whose decayed heat falls below **0.01** are deleted (dust removal —
  the table stays proportional to what is actually warm).
- Session scopes (`scope != ''`) older than `session_ttl_hours` (default
  24) are cleared crash leftovers from Troop hunts must not survive.
- Evaporation re-stamps `updated` at decay time (the decay is applied, not
  re-derived); running the Ranger twice in a row is a no-op within clock
  precision (idempotence under the synthetic-clock test).
- `_derived/` remains disposable: deleting `trails.db` loses memory but
  breaks nothing (A.3 spirit) therefore evaporation never commits.

### H.2 Promotion and pruning of uncertain links

**Scope rule (normative): the Ranger manages ONLY links that carry a
link-level `confidence < 1.0`** i.e. edges born as proposals
(`related-to` at 0.3, C.8) or discovered shortcuts (0.5, C.8). Structural
edges (`part-of`, etc.), links without a confidence field and links at
`confidence: 1.0` are NEVER touched.

- **Promotion**: a managed link whose BOTH endpoints hold persistent heat
  `>= promote_floor` (default 0.2) after evaporation is *confirmed by use*:
  link confidence is raised to `promoted_confidence` (default 0.8). Audited
  commit `ranger(promote): <id> <rel>-><target> 0.8` of only the `.md`.
- **Pruning**: a managed link with `confidence <= prune_below` (default
  0.5) whose BOTH endpoints have fully evaporated (heat 0 no
  reinforcement within memory) is removed. Audited commit
  `ranger(prune): <id> <rel>-><target>`.
- A link that is neither hot enough to promote nor cold enough to prune is
  left alone patience is a feature.
- The Ranger NEVER deletes nodes. Stale passports (G.3) stay reported until
  a human (or a future tombstone policy) decides.

### H.3 Health report (read-only)

One pass over the catalog + files, returned as a dict and printed by the
CLI:

- **`needs_split`**: branches with > 150 entries or > 3.000 body tokens
  (A.5 rule).
- **`fat_nodes`**: nodes with degree > 50 (A.2 rule branch candidates).
- **`lint`**: error/warning counts from `vine validate`'s engine (includes
  payload drift, C.10).
- **`stale_passports`**: passports whose `source_path` no longer exists
  under the Gardener's `source_root` (when configured).
- **`uncertain_links`**: inventory of managed links by confidence bucket
  (what the next promotion/pruning cycle will look at).
- **`needs_description`** (v0.54): `type: media` nodes still carrying the
  G.5.1 stub sentence — media that was ingested with no vision binding, or
  whose describer failed. Such a node is findable by filename and nothing
  else, and its summary matches every other undescribed media node's; the
  operator's repair is binding a `vision` model and re-describing, and a
  repair nobody is told about is not one. The check matches the stub
  SENTENCE, exported as one constant the converter and this check share —
  two spellings of a sentinel agree only where somebody compared them.
- **`heat`**: row count + max/mean of the persistent scope (pheromone
  health at a glance).

### H.4 Execution model

- `vine ranger [--forest DIR]` one full cycle: evaporate → tend links →
  health report.
- `vine ranger --every N` service mode: repeat every N seconds until
  interrupted (Docker-friendly; the deploy doc's `ranger (cron)` box).
- The Ranger takes an injectable clock (`now`) the synthetic-clock tests
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
return (G.9.1). Evaporation for bytes same philosophy as H.1.

### H.7 Landmarks refresh (v0.13)

The Ranger keeps the master `_index.md`'s `## Landmarks` section (A.5)
populated the forest's hubs, discovered mechanically:

1. **Selection**: top 10-20 nodes by degree over the catalog's typed-edge
   table (frontmatter `links`, both directions). Excluded: `branch` nodes
   (a landmark must carry scent), `_meta/*`, and degree-0 nodes. The
   folder hierarchy (`parent`) does NOT count toward degree landmarks
   measure how woven a node is, not how filed.
2. **Rendering**: A.5 entry lines (`- [[id]] <summary>`) inside the
   `## Landmarks` section of the master branch only. The section is
   created if the heading is missing.
3. **Idempotence**: the section is rebuilt in full and compared; an
   unchanged graph produces no write and no commit.
4. **Write path**: the audited `.md`-only pattern (H.2) with commit
   message `ranger(landmarks): refresh`, followed by a catalog upsert of
   the master index. No LLM, no node creation, no link changes.

### H.8 The repo is tended too (v0.57)

A forest's git repository accumulates one commit per write forever, and
git left alone accumulates loose objects with them. On a laptop's SSD
that is invisible; on the overlay filesystems containers actually run on,
every git operation slows as the object directory grows — and since every
`plant` IS a commit (C.7), the write path inherits the drag. Measured in
the first production deployment: the repo's own hygiene was a material
share of why a plant held its forest's thread long enough for operators
to describe the product as frozen.

The Ranger's `run()` therefore ends by asking git to tend the repo:
`git gc --auto --quiet`. Normative:

1. **Git decides, the Ranger only asks.** `--auto` applies git's own
   thresholds; most runs do nothing, and the Ranger MUST NOT force a
   repack on every pass.
2. **Never a commit, never a node.** Repo maintenance touches `.git/`
   only — it changes no history, no working tree, no catalog row. It is
   the same class of act as evaporation: housekeeping in a layer the
   contract does not version.
3. **Reported, best-effort.** The run's report carries `gc:
   ran|skipped|unavailable`; a git that fails the call fails nothing
   else (the same rule as the audit's — maintenance must never fail the
   work it maintains).

---

## Part I Snapshots (v0.11)

A forest snapshot is ONE file: the forest's git repository packaged as a
`git bundle` (the full commit history every plant/tend/gardener/ranger
audit trail travels along), compressed.

- `vine snapshot create [--out FILE]` → `<forest>-<date>.bundle.zst` (or
  `.bundle` when zstd is unavailable). Payload `.db` files are NOT inside
  (they are not in git, A.3.1); `--with-payloads` adds a sidecar archive.
- `vine snapshot restore FILE --forest DIR` → a full forest clone with
  history; `vine reindex` rebuilds the derived layer.
- Upload to object storage rides the G.9 fetcher (`--to s3://...`).
- The Ranger MAY schedule snapshots in service mode (backup policy:
  interval + retention), config in `_meta/ranger.yaml`.
- A hosted Station moves snapshots over HTTP download of the bundles
  it took, import of a bundle into a forest that does not exist yet —
  under J.13's rules (owner-only, v0.39). Restore into an *existing*
  forest stays `vine snapshot restore` at a shell.

Use cases (informative): backup/DR, distribution (a team pulls the whole
MAP in one small download the scent tier is ~0.1% of the source),
frozen releases of a knowledge base ("the forest as of Q2 close").

---

## Part J The Station (host layer: self-host, governance, scoped access)

### J.0 Position

Parts A-I describe a forest and the Vine that reads it, for one operator
who owns the filesystem. Part J describes the **Station**: the service that
serves forests to *many* principals with identity, policy, audit and a
web console so that a forest becomes a governed corporate asset instead
of a personal directory.

The Station is a **privileged client**, never an extension (G.0):

- The engine (`src/monkeyllm/`) MUST NOT gain policy, identity or tenancy
  awareness. Primitive semantics, budgets and guards are identical whether
  a call arrives through the Station or through `vine serve`.
- Forests remain content. Principals, tokens and policies MUST live in the
  **host registry** (host-side storage), never inside a forest a forest
  handed to another operator carries no credentials.
- Every write remains a git commit inside the forest (A.3), and binaries
  remain outside that git (A.3.1).

### J.1 The Station

The Station mounts a **forest registry** a root directory whose valid
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

#### J.1.1 The surface that answers only to itself (v0.52)

The MCP mount refuses any request whose `Host` header is not in
`MONKEYLLM_STATION_ALLOWED_HOSTS` DNS-rebinding protection, and it stays
exactly as strict as it is. The default list names a local install, and the
shipped `docker-compose.yml` inherits that default, so **a Station published
under a domain refuses every MCP request until an operator names the
domain**. Nothing else about the deployment says so. `GET /v1/health`
answers `ok`, `GET /v1/forests` lists them, Studio opens, REST serves every
primitive and the only dark surface is the one the product exists for. The
client reports `Failed to connect`; the wire carries `421` and nineteen
bytes of `Invalid Host header`, which name neither the refused host, nor the
accepted ones, nor the variable that decides. The diagnosis was reached, in
the field, only because the person holding the failing client also had the
source tree open.

Three requirements, none of which relaxes the check:

1. **The refusal wears the envelope.** A `421` leaving the MCP mount is
   answered `{error: {code: "E_HOST_NOT_ALLOWED", message, hint}}`, naming
   the `Host` that was refused and the environment variable that would admit
   it. The **decision** stays with the transport guard that makes it today
   one decider, as everywhere else in this document only the sentence is
   the host's. The host that appears in the message is the one the caller
   sent: it is not a disclosure, it is a quotation.
2. **The boot says it.** A Station that serves MCP with no explicit
   allow-list MUST log a warning at startup, naming the variable and saying
   that MCP will answer to local addresses only. A deployment whose main
   surface cannot answer MUST NOT boot silently. A list containing `*` MUST
   warn too, naming what it turns off: `*` disables `Origin` checking along
   with the host check, so it is never the shortcut for "my domain".
3. **`/v1/health` reflects it, per request.** The health document carries
   `mcp: {enabled, host_allowed}`, where `host_allowed` is the verdict for
   **this request's own `Host`**. The operator curls the domain they
   published and gets the answer about that domain, in the place they were
   already looking. It discloses nothing the allow-list is never listed,
   and the host being judged is the one the caller supplied.

The allow-list itself MUST NOT be served to a caller, and no route may be
added that reveals it. Naming the variable is documentation; printing its
value is configuration disclosure.

**F.62 (acceptance).** A request to the MCP mount carrying a `Host` that
is not allowed is answered `421` with `{error: {code:
"E_HOST_NOT_ALLOWED", …}}` naming that host and the variable; the same
request with an allowed host completes the handshake. `GET /v1/health`
carries `mcp.host_allowed` matching that verdict for the host the caller
sent. A Station that starts serving MCP with no explicit allow-list logs a
warning naming the variable. No response anywhere lists the allow-list.
Covered by tests.

#### J.1.2 The block is for the model (v0.54)

The text block of an MCP tool result goes into an LLM's context, where it
is billed by the token and read by a parser. Everything in this section
follows from taking that consumer seriously.

1. **Compact serialization.** The result dict is serialized with no
   indentation and no separator whitespace. Measured against a served
   Station, pretty-printing cost 29.9% of a `locate`, 24.1% of a
   `harvest` — ~500 tokens per sweep, a whole `pick` of real content per
   five-hop hunt, spent on air. Keys, values and their order are
   unchanged: this is presentation, and the contract has no presentation
   layer on the wire. A console that wants indentation renders it
   client-side, where it is free.
2. **`isError` agrees with the envelope.** A tool result whose body
   carries the C.12 envelope (`error` at the top level) sets the
   protocol's `isError` flag. The SDK already flags schema-validation
   failures, so the two failure families used to wear opposite flags —
   and a harness that branches on the protocol field treated `E_NOT_FOUND`
   as success, forwarding the envelope as if it were data. Whether a
   domain refusal "is" a protocol error is a debate the consumer settles:
   a machine reads one field, so the two signals MUST agree. The envelope
   itself is unchanged — `{code, message, hint}` is the body either way.
3. **The server states its version.** `serverInfo.version` carries the
   installed package's version. An integrator debugging against a
   deployment must be able to ask which build answered; a full report
   cycle was once spent against a build nobody could identify, and the
   client had no way to detect it.
4. **No empty promises.** Capabilities with nothing registered behind them
   (`resources`, `prompts`) are not announced. An announced capability is
   an instruction to every connecting client to spend a round trip listing
   it; two round trips per connect, forever, to learn "empty" is a cost
   with no buyer.

   **A transport method is not a capability (amended v0.64).** This rule
   reaches the two families it names and no further. In particular
   `subscriptions/listen` (2026-07-28, SEP-2575) MUST stay served: it is
   not a feature a client lists, it is the era's only server-to-client
   channel — what the standing GET stream was before it — and withholding
   it does not save a round trip, it ends the connection (J.1.4). The
   consequence is that at that era the SDK derives `tools.listChanged`
   from the served handler and announces `true` while this Station
   publishes no such event. That is admitted deliberately: the promise
   costs a subscriber one stream that stays quiet, which is the cheaper of
   the two things a client can be told. Earlier eras are unchanged —
   `tools.listChanged` is `false` at 2025-06-18 and 2025-11-25, where the
   flag is derived from notification options rather than from the handler.
5. **The instructions name every tool (v0.55).** The `instructions`
   served at `initialize` are the one description of this surface every
   client receives unasked, and an agent that trusts them uses exactly
   what they name — a consumer team operated a full round without `scan`
   while writing a feature request for what `scan` already did. Every
   registered tool appears in the instructions by name, and the suite
   compares the two lists mechanically: two descriptions of one contract
   agree only where somebody compared them.
6. **The first reply states the version (v0.56).** The `forests()`
   result — the call the instructions prescribe first — and REST's
   `GET /v1/forests` carry `station: "<version>"`, the same string as
   rule 3's `serverInfo.version`. Rule 3 put the version where a
   protocol client can read it; this rule puts it where the MODEL reads,
   because the model is what navigates by a downloaded skill, and a
   skill is a snapshot of this surface that nothing ages visibly: the
   team's round-without-`scan` was a stale skill, not a missing tool.
   The generated skill stamps the version it was built against (J.5.12)
   and teaches the comparison; the server cannot push a skill, but it
   can make staleness visible in the first reply of every session.

#### J.1.3 The door tells the truth about the rooms (v0.55)

v0.52 taught `/v1/health` to report the MCP door (J.1.1), and the next
outage was behind the next door: a Station whose every forest refused to
open still answered `status: "ok"`, `writable: true`, and listed both
forests with full capabilities — while `forests()` is the first call the
instructions prescribe. An agent was instructed to begin from an answer
that was false, and its next call could not tell a bad key from a bad
name from a dead server.

1. **`/v1/health` carries `forests: {served, locked}`** — counts, never
   ids: health is unauthenticated, and forest ids are J.3's to disclose.
   `served` is what would open; `locked` is what a live foreign writer
   currently holds (C.9). The probe reads the lock file and asks the
   kernel — it MUST NOT open the forest, warm it, or touch a lane.
2. **`status` says `"degraded"` when `locked > 0`.** A Station serving
   none of what it exists to serve is not `ok`, and an operator's first
   curl is the place to say so.
3. **`forests()` and `GET /v1/forests` mark what cannot serve.** An
   entry the key may see carries `locked: true` while a foreign writer
   holds it — the caller was going to learn this anyway, one failed call
   later and without the reason. An orphan lock marks nothing: it heals
   at the next open (C.9), so reporting it would name a problem the
   product no longer has.

#### J.1.4 A refusal is not a disconnection (v0.64)

Streamable HTTP gives one status code a meaning the JSON-RPC layer above it
cannot override: **404 means the session named by this request no longer
exists** (2.5.3). A client that receives it has been told, correctly, that
continuing on this connection is pointless, and the conforming answer is to
stop — so 404 is the one status a live server MUST NOT spend on anything
smaller than that.

An unregistered method is something smaller. The SDK answers it with
`-32601 Method not found` under HTTP 404, which is defensible as HTTP and
wrong as this transport: the two facts differ in scope, and the client can
only act on the one the status carries. Measured, that is the whole distance
between "this server does not offer that method" and **0 tools** — the
client tore down a session that was healthy, and the call that failed was
the next one, not the one refused.

1. **The MCP mount MUST NOT answer a served request with 404 for any reason
   other than a session that is gone.** A method this Station does not serve
   is a JSON-RPC error carried by a 2xx, on the terms C.12 already sets for
   every other refusal on this surface.
2. **A method the era requires is served, not refused** (J.1.2 rule 4 as
   amended). Where the two rules could disagree, this one does not arise:
   the method is served, so no refusal is spelled at all.
3. **The rule is about the wire, not about authority.** J.3's byte-identical
   `E_NOT_FOUND` for an out-of-scope node is unaffected — it is a JSON-RPC
   result about a node, and it is exactly the disclosure boundary that
   requires it to be indistinguishable from an absent one. Nothing here
   licenses naming what a scope hides.

The general form is the one this document keeps arriving at from different
directions: a signal has one meaning per layer, and a layer that borrows
another's vocabulary to say something cheaper will be believed about the
expensive thing.

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

- **Password** `POST /v1/auth/login {username, password}` returns a
  **session token**: an ordinary API key with a short lifetime and a
  `session` kind. Sessions MUST NOT appear in the token console; they are
  the by-product of a login, not a credential an operator manages.
- **API key** pasted directly, as before.

Both MUST converge on the same `authenticate()` and the same J.3 policy
resolution. There is exactly **one** authorization path; the door only
decides how the principal was established, never what it may do.

**The environment super-admin.** `MONKEYLLM_STATION_ADMIN` and
`MONKEYLLM_STATION_PASSWORD` define a break-glass account, verified against
the environment with a constant-time comparison and **never stored**.
Hashing a value that already sits in the environment protects nothing, and
storing it would give a rotation two places to go wrong. It carries the
owner bit (J.2.4), so it governs a registry that holds no forest yet the
grant-per-forest reading of this rule is what made an empty deployment
unreachable before v0.25. If the variables are absent, the door simply does
not exist a deployment that never sets them has no default password,
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
granted**, not merely on one of them otherwise the administrator of one
forest could mint a credential that opens another. For the same reason, the
token console MUST list only principals the caller fully administers.

#### J.2.3 The person as the unit of administration

Grants, passwords and keys are three tables and one thought. Onboarding
somebody is not three tasks performed in three places; it is one decision
with three consequences. `POST /v1/admin/people` therefore applies, for a
single principal and in this order:

1. **grant** create or replace their access on one or more forests
2. **revoke access** remove their access to one or more forests
3. **password** set, replace or clear it (absent field means "leave it")
4. **issue key** mint one, returned exactly once
5. **revoke keys** one, or all of theirs

The order is normative because it is what makes first-time onboarding work
in a single request: the grant lands before the credential steps, so a
principal that did not exist a moment ago is administrable by the time its
password and key are created.

**A composite is not an authority.** Each step MUST re-check the rule that
governs it on its own `admin` on the forest for (1) and (2),
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
reasoning as partial application between steps the operator gets what they
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
- re-granting at boot drifts every forest created later needs the same
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
  no password, no non-session API key. That is the one condition under
  which an open route creates no privilege escalation: there is no
  privilege yet to escalate from.
- It MUST NOT exist while an environment super-admin is configured. That
  deployment has already declared its first identity, and two open doors
  competing for it is the race this section exists to forbid.
- Once it has run it MUST close **permanently**. A closed route MUST answer
  exactly as an unrouted path does not "already configured", which
  publishes the deployment's state to anyone who asks.
- It MUST NOT be closed by the Station's own **startup** (v0.28). The window
  belongs to the person who opens the console; a process that consumes it by
  booting removes the feature from every deployment that runs the image as
  shipped. Only an operator's explicit request may take it instead (J.2.5).
- The check and the creation MUST be **one atomic transaction**. Two
  simultaneous requests MUST produce one owner and one refusal, never two
  owners. This is the whole security surface of the feature: a
  check-then-write with a gap between them is a back door with a race
  condition as its key.
- `email` is **optional**, stored locally as the owner's contact, and MUST
  NOT be transmitted anywhere. A setup step that depends on a network call
  cannot complete on an air-gapped host, and asking for an address in
  exchange for nothing is a poor first sentence for a product to say.
- The password is stored under the J.2.1 rules memory-hard KDF, salted.
  The owner is an ordinary principal that happens to carry a bit.

**The first forest.** Setup MAY create one, and the choice MUST be the
operator's: an empty forest, or a **seeded demo** whose only purpose is that
`Ask` and `Explore` have something to answer on the first visit. Neither is
required an owner with no forest is now a valid, workable state, which is
precisely what v0.24 could not represent.

The seed MUST be **generated, never shipped as content**: a generator that
calls only public primitives, living outside `src/monkeyllm/` because the
engine carries no vocabulary of its own (a forest is content, and content
is not the engine's business). A demo forest MUST NOT be committed to the
repository the generator is the artifact, the forest is its output.

**F.28 (acceptance).** On a registry with no credential and no environment
super-admin, `GET /v1/health` reports setup is required and the setup route
creates an owner whose session **immediately** reports `admin`, holds
`admin` on a forest created *after* the owner existed, and is refused by
nothing that `admin` permits; the same route, called a second time, answers
byte-identically to an unrouted path, and two concurrent first calls produce
exactly **one** owner and one refusal proven by running them against one
registry, not by inspecting the code. With an environment super-admin
configured, the route MUST NOT exist at all. An owner MUST be able to create
the first forest on an empty registry, and a non-owner without grants MUST
still be refused it. Clearing every credential MUST NOT reopen setup while
the owner principal exists all covered by tests.

#### J.2.5 The first run, announced (v0.28)

J.2.4 made a Station with nobody in it reachable. This section makes it
**findable**, because the two are not the same thing and only the first was
ever built.

Nobody meets this product in a browser. They meet it in a terminal, watching
`docker compose up` scroll, and at the end of that scroll they either know
what to do next or they do not. A console that would have told them is
behind the door they are trying to open. So the first minute is a log line,
and the log line is part of the product.

**Starting mints nothing (normative).** A Station MUST NOT create a
credential as a side effect of starting. The registry it starts on MUST hold
exactly the same authority after boot as before it no key, no password, no
principal that can act. This is what makes J.2.4's window survive to be used:
a process that mints itself a credential on an empty registry closes setup
before the first request and turns the documented first door into code that
only tests can reach.

The environment super-admin (J.2.1) is not an exception to this. It creates
an *identity* and no credential: the password is compared against the
environment and never stored, so nothing in the registry becomes usable by
possessing the registry. That it also closes setup is J.2.4's rule about
declared identities, not a side effect of booting.

**The announcement.** When nobody can yet sign in, the Station MUST write to
its standard output how to get in, and MUST name the console's URL. There
are exactly three states and the announcement MUST distinguish them, because
the operator's next action differs in each:

| Registry state | What the announcement says |
|---|---|
| No credential, no environment super-admin | setup is open: the first person to open the console becomes the owner |
| Environment super-admin configured | sign in as that **username**, with the password held in the environment |
| Any credential exists | nothing this is not a first run |

- The environment password MUST NOT be printed. The operator set it; the log
  aggregator did not need a copy.
- The open-setup announcement MUST also read as a warning. A Station
  published on a public interface with an unclaimed owner seat is a race
  against strangers, and the operator learns that here or after losing it.
- The third row is silence, not a status line. A restart that reports the
  deployment's authentication state to whatever collects its logs is a
  disclosure with no reader who needed it.
- The condition is **the registry**, never a marker file. A first run is a
  fact about state, and a Station whose registry volume was replaced is
  having its first run again no matter what the filesystem remembers.

**The bootstrap key (opt-in).** A deployment with no reachable browser —
headless server, CI, an MCP-only client MUST still have a first door. The
Station therefore accepts an explicit request, at start, to mint the first
API key: a `--bootstrap-key` flag, or the equivalent environment variable so
that a platform UI with no argv field can ask for it too.

- It MUST be explicit. An opt-in that defaults to on is not an opt-in, and
  the default here is the setup screen.
- It MUST mint **only into J.2.4's window** no owner, no credential and
  return nothing at all otherwise. A running deployment MUST NOT be able to
  grow a new full-authority key by being restarted with a flag; that is what
  `station key` and the People console are for, both of which require
  somebody who is already in.
- The principal it mints MUST take the **owner bit**. A first credential
  that cannot create the first forest is the v0.25 deadlock wearing a new
  hat, and this is the one requirement here that is about authority rather
  than about words on a screen.
- Minting it **closes setup**, by J.2.4's own rule, and the announcement
  MUST say so. The flag and the setup screen are two doors onto one
  one-shot window; whichever is used spends it.
- The key is shown **once**, at creation, and only its digest is kept
  (J.2.2). The announcement MUST say that too, because a secret that scrolls
  past unlabelled is a secret the operator will look for again tomorrow.

**F.31 (acceptance).** On an empty registry with no environment super-admin,
starting the Station MUST leave `GET /v1/health` reporting
`setup_required: true` proving the boot minted nothing and the
announcement on standard output MUST carry the console URL. Started once
with the bootstrap flag, the same registry MUST then report
`setup_required: false`, the printed key MUST authenticate a principal
reporting `owner: true`, and that principal MUST be able to create the first
forest on the empty registry; started with the flag a **second** time, or
against a registry that already holds a credential, it MUST mint nothing.
With an environment super-admin configured, the announcement MUST name the
username, MUST NOT contain the password, and no key is minted. On a
registry that already holds a credential the announcement MUST be empty. All
covered by tests.

#### J.2.6 Pairing a key that narrows (v0.48)

A device that acts for a person all day a browser extension, a phone
shortcut must hold a credential, and both existing shapes are wrong
for it. A session (J.2.1) is the principal's whole authority with a
short life: stored in a toolbar it is both too much and too brief, and
an extension that silently re-logs in must store the password, which is
strictly worse. An admin-minted key (J.2.2) has the right lifetime but
the wrong gatekeeper: a person should not need an administrator to
connect their own browser to their own grants.

`POST /v1/auth/pair` is the third door. Unauthenticated like `login`,
it takes `{username, password, label?, caps?, expires_in_days?}` and
answers `{api_key, principal, caps, expires_at}` an ordinary J.2.2
key whose row additionally carries a **capability mask**.

- **The mask only narrows.** The key's effective authority is the
  principal's grants **∩ mask, computed at the moment of use** —
  wherever the requesting principal's authority is read: the policy
  built for a forest call, the grants a console is shown, and the
  admin and owner bits, over REST and MCP alike. A mask never adds a
  capability, never widens a scope, and a masked key held by an owner
  is refused every `/v1/admin` route exactly as if the owner bit were
  absent. Grants revoked after pairing are gone from the intersection
  immediately: the mask is a filter over live authority, not a copy of
  it.
- **`caps` ⊆ `{read, ingest}`, default both.** A pair key exists to
  clip and to look; asking for `write`, `tend`, `query` or `admin` is
  `E_SCHEMA`. Those remain what People and `station key` mint,
  deliberately.
- **No admin gate, by construction.** Pairing is self-service because
  it reaches nothing the password could not already reach refusing
  it would not protect anything, only route the same authority through
  a wider credential. A principal with no `ingest` grant anywhere still
  pairs; the key simply cannot ingest, which is the grants speaking,
  not the door.
- **It MUST expire.** Default 90 days, ceiling 365; absent or zero
  means the default, never "unlimited". The lifecycle is otherwise
  J.2.2's: digest-only storage, shown once, revoked from People,
  `last_used_at` maintained.
- **`login` and `pair` MUST be rate-limited.** Both verify passwords
  and both are now reachable from every browser that holds the origin,
  not only from the console. A fixed window per (username, client) is
  enough; the refusal is HTTP 429 with the same one message whether
  the user exists or not the limiter must not become the directory
  the login refusal already refuses to be (J.2.1).
- `/v1/me` and `/v1/forests` answered to a masked key report the
  **masked** caps: what a console renders from them is what the key
  can actually do, or every disabled button becomes a support ticket.

**F.47 (acceptance).** Pairing with a valid password returns a key
whose `/v1/me` shows only the masked caps. That key MUST be refused a
`plant` its principal would be granted unmasked, MUST still read and
`ingest`, and minted for the owner MUST be refused every
`/v1/admin` route and MUST NOT satisfy the admin bit over MCP. A wrong
password, an unknown user and a user with no password answer
identically. Failures past the window answer 429 without revealing
whether the user exists. Every pair key carries an expiry; `caps`
outside `{read, ingest}` is `E_SCHEMA`. All covered by tests.

### J.3 Policy and enforcement `ScopedVine`

**Unit of scope: the branch prefix.** The hierarchy that Part A already
maintains is the policy surface a grant names a subtree, not a node list.

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
| `query` | requires `query` cap and an in-scope `type:dataset` node; the optional table allow-list is checked against the parsed statement (C.5.3); C.9 read-only guards unchanged |
| `tend` | requires `tend` cap and an in-scope dataset; the optional table allow-list is checked against the parsed statement, **reads included** (C.5.3, v0.50); C.10 guards unchanged |
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
| `/v1/admin/keys` | principals the caller administers **fully** (J.2.2 a key spans forests, so partial administration is not enough) |
| `/v1/admin/grant`, `/v1/admin/models` | already per forest; unchanged |

A branch prefix is a description of somebody's world, and an audit entry
is a record of what they read. Neither becomes public because the reader
happens to administer a different forest.

*Boundary (normative as of v0.50):* providers (J.10) are a **host**
resource one row, no forest column, shared by every forest. Their reach
is therefore the whole deployment: the endpoint decides where every
forest's material is sent, the key pays for every forest's calls, and
removing one removes the bindings of forests the remover may not
administer. Authority over them MUST match that reach.

| Operation | Authority |
|---|---|
| list providers (`GET`) | any administrator. A per-forest model binding points at these names, and the response carries `has_key` rather than any secret |
| create, change, remove, or test a provider | administers **every** forest in the deployment |

"Every forest" rather than "the owner bit" is deliberate, and it is the
same reasoning J.2.4 gives for the bit itself: authority is stated as what
it reaches, so the rule keeps working where the bit is unavailable. The
J.2.1 break-glass account falls back to per-forest grants when the owner
seat is taken and keeps provider repair, which is the situation
break-glass exists for; a single-forest deployment is unaffected, there
being no second forest to cross into; and a deployment's second forest
narrows the authority the moment it exists, with nobody revoking anything.

Two custody rules follow, and they hold for every principal including the
owner:

1. **A stored credential belongs to the address it was stored against.**
   Changing a provider's endpoint MUST require supplying its key again.
   Leaving other fields alone with a blank key still keeps the stored one
   — that is the case the blank-key affordance exists for.
2. **A stored credential is never sent to a caller-supplied
   destination.** Where a connection test accepts both a saved provider
   and an endpoint typed into a form, a supplied endpoint that differs
   from the stored one is a different destination: it carries its own key
   or none.

A per-tenant provider model remains a later concept, not an implementation
detail here.

### J.4 Audit

- **Writes** are already commits; the Station MUST stamp the acting
  principal in the message, following the existing convention
  (`station(<principal>): <action>`, cf. `ranger(promote|prune)`). Git
  history remains the source of truth for what changed.
- **Stamped at the commit, never amended after (v0.57).** The stamp used
  to be an amend: the engine committed, the host read the message back
  and rewrote the commit with the `station-principal:` trailer — two
  commits and a log read for every write, on the one thread every write
  already queues for. The engine now exposes `commit_trailers` — a
  public, host-writable seam in the J.0 pattern (`embedder`,
  `hybrid_locate`): lines the next commit appends after a blank line, in
  git's own trailer convention. The host sets it around each scoped
  write; the engine stays principal-blind (it appends what it is handed
  and never reads it). The sha the caller receives is the only sha that
  ever existed. The amend remains as fallback where the seam is absent
  (an older engine), because attribution lost is worse than attribution
  paid for twice.
- **Reads** extend Part D telemetry with the principal: every scoped call
  records `(principal, forest, primitive, argument digest, result size,
  timestamp)`. Bodies and snippets MUST NOT be copied into the audit log —
  it records access, not content.
- **An answer served from the store is audited as one** (J.10.7): the row
  carries the entry's key digest, is marked as served from the store, and
  the cost it records is the cost avoided, never a second spend.
  Reconstruction survives the shortcut the row names the entry, and the
  entry keeps the original run and its trail.
- The pair MUST be sufficient to reconstruct any answer's full trail after
  the fact: which principal, which primitives, which nodes, in which order.

#### J.4.1 Governance is audited too (normative, v0.50)

The bullets above record what was read and what was written. This records
the changes that decide **who may do either** — the questions any later
review starts from: when was this key made, and by whom; when did this
grant widen; when did this provider change address.

The Station MUST record, on the same table and the same terms:

| Event | Carries |
|---|---|
| grant / revoke | target, forest, capabilities |
| key issued / revoked | target, label, the key's non-secret prefix, expiry |
| password set or cleared | target, and that it happened |
| provider created, changed, removed, tested | name, endpoint, whether a key was supplied |
| model binding | forest, role, provider, model |
| forest created | id, seed |
| sign-in, pairing, owner setup | username, client host, outcome |

Three rules:

1. **Never the secret.** The digesting of Part D applies unchanged, and
   nothing secret is passed to it in the first place: a key is named by
   its non-secret prefix, a password only by the fact that one was set.
2. **A governance row belongs to no forest** and MUST carry a single
   agreed placeholder, so that "show me the administration trail" is a
   filter rather than a guess. A row that *is* about one forest — a grant,
   a model binding, a forest's creation — carries that forest's id, so its
   administrator can read it back.
3. **Placeholder rows are the owner's to read.** They describe the
   deployment as a whole, and J.3.2's rule applies to them for the same
   reason it applies to content: administering one forest is not a licence
   to read the shape of the others.

Failed sign-ins MUST be recorded as well as successful ones. The J.2.6
limiter counts in memory and forgets on restart, so without a row there is
no answer to whether anyone was trying. Recording the attempted username
is intended: it is what was tried.

An audit write MUST NOT be able to fail the action it describes.

### J.5 Studio

A web console served by the Station. Studio MUST consume only the
documented REST surface. It MUST NOT hold a privileged side-channel:
whatever Studio can do, an API client with the same principal can do and
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
| | Skills | how does my own AI learn to use this forest as memory (J.5.12) |
| **Build** | Ingest | how do I put my documents in |
| | Models | who reads this forest, and who summarises it |
| | Webhooks | what this forest tells my other tools, and when (J.16) |
| **Govern** | Access | who exists, what they may see, how they sign in |
| | Audit | who saw what |
| | Health | what the Ranger sees, and how to snapshot |
| | MCP / API / Integrations | how agents, apps and deployments plug into this Station |

Navigation MUST carry an icon per console alongside its label: the console
is used by people who did not choose these names, and a name alone is a
weak target.

One label is normative (v0.49): the integration manual's entry MUST read
**MCP / API / Integrations** the three surfaces it documents, in that
order. The menu is where a newcomer decides what this deployment *is*,
and the previous label, a lone abstract noun in the govern group, read as
an appendix. The consoles are a window; the surfaces named on this door
are the product: external intelligences plugging into a brain a person
grows for themselves. Localisation MAY translate the trailing noun
("Integrações", "Integraciones"); `MCP` and `API` are names and travel
as-is, like the node types of A.1.

Navigation MUST list exactly the consoles the principal's capabilities
permit on the selected forest, and MUST re-evaluate when that forest
changes capabilities are per forest, so the menu is too. `Ask` is the
default landing console for a principal holding `read`; a principal
without it lands on the first console they do have.

**Hiding is presentation and MUST NOT be the control.** Each console keeps
its own capability guard, because a hidden entry is still reachable by
anyone who can set application state, and the API remains the authority: it
already refuses, and it would refuse a request the console never sent.
Where a console has something for *every* principal Overview, which
describes the key itself, its scope and its capabilities it is always
listed; an entry that could only ever refuse is hidden instead (the govern
consoles for a non-admin), because a menu reads as a list of what you may
do, and an entry that only ever refuses teaches nothing (v0.49 this
corrects the earlier example: Access is admin-gated and hidden like its
group; the principal's own half of that story lives in Overview).

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
  model output are forest data and MUST be rendered as stored the
  console translates its own words only.

#### J.5.4 Credentials, and the panel that does not exist

Issuing, listing and revoking API keys follows J.2.2: label, principal,
expiry, last use, prefix. The secret appears once, at creation, and the
console MUST say so at the moment it is shown rather than afterwards.

The access **levels** MUST be documented in the console itself the named
roles, what each one can do, and what it cannot. An operator choosing a
level should not have to leave the screen to learn what the choice means.

#### J.5.5 The People console

Governance is presented **per person**, not per table:

- **Onboarding is one form.** Who they are, what they may see, how they
  sign in, and a token if they need one submitted together, because that
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
- Secrets a generated password, a new key appear once, at the moment
  they are created, in the same place the operator was already looking.

**There is no separate super-administrator panel, and there MUST NOT be
one.** One console over one API, with capabilities deciding what appears: a
principal without `admin` does not see Tokens, and a principal with `admin`
on one forest does not see the credentials of another. A second panel would
require a second authentication path, and a second authentication path is
where the backdoor goes this is the same reasoning as J.5's
no-side-channel rule, applied to the console's own front door.

#### J.5.4 Forest Views

A forest is a graph of nodes and typed trails with heat on it, and a tree
of files on disk. Both are the same truth; a console MUST be able to show
either without the operator changing consoles. The Explore console
therefore carries **modes over one selection** the selected node survives
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
  show the value it received rather than a rank heat is comparable across
  nodes and a rank is not.
- Link-level `confidence` below 1.0 MUST be visually distinct from curated
  links: it is a proposal under the Ranger's management (H.2), not an
  assertion. `discovered-shortcut` (C.8) MUST be distinguishable in turn.
- Colour MAY encode the node's type or its home branch the dialect and
  the id, both facts the forest holds. A console MUST NOT colour by a
  category the forest does not hold, and whichever fact colour encodes,
  the legend names it (v0.38).
- Layout is presentation and carries no meaning. A console MAY animate it;
  it MUST honour a reduced-motion preference by settling immediately —
  and it MUST settle regardless (v0.38): a map at rest holds still,
  spending motion only on new data, the operator's hand, or an explicit
  reorganize. A forest cannot be pointed at while it trembles. Distinct
  regions MUST read as distinct: a layout that piles unrelated branches
  into one heap answers the operator wrongly.
- View tuning filters, grouping, label visibility, node scale, link
  width, force strengths is presentation and belongs to the operator
  (v0.38). It MAY persist in browser storage, per forest; it MUST NOT
  enter the address (J.5.8: the address carries the selection, not the
  taste) and it MUST NOT spend a call or a write.
- **Growth replay** (v0.38). A console MAY replay the region in `created`
  order (ties by id): nodes appear as they were planted, trails appear
  when both ends exist. Replay is presentation over the projection
  already in hand it MUST NOT spend another call and it MUST NOT
  write. Under reduced motion the replay is a scrubber, not an
  animation.

**Rendering rules for the files mode.** A file MUST be rendered as what it
is, and its stored form MUST remain reachable:

- A node body is markdown: rendered by default, with the stored source
  available in one action. A body whose content is HTML is rendered as a
  page, sanitised; it MUST NOT be able to script the console, and it MUST
  NOT be able to reach the console's credentials.
- A `type: dataset` node's payload is a database: its tables MUST be
  listable and browsable through `query` and nothing else the same single
  SELECT, the same injected LIMIT, the same timeout (C.5). A console
  browsing a payload is a `query` client, not a second access path.
- Frontmatter shown beside a body is the passport as the Catalog holds it.
  A console MUST NOT present a reconstructed passport as the file's bytes.
- A body over the `pick` budget MUST show the outline the primitive
  returned rather than pretending to have the whole text.

**Editing.** A console MAY offer editing, and every edit MUST leave as a
Part C write `graft` for a node, `tend` for a dataset row. No surface,
the console included, may write a node file or a payload directly: the
commit, the validation, the index propagation and the audit record are the
write, and a "save" that skips them is a forest that no longer describes
itself. A console offering editing MUST show the operations before they are
applied: the operator is authoring a commit, and a commit is not a
keystroke.

Whole-note editing (v0.43): a console MAY edit the entire body in one
place and save it as one `graft` carrying `replace_body` the note as
the unit of edit, one commit for one thought. Two rules keep it honest:
the console MUST NOT compose a `replace_body` from a truncated `pick`
(a body over the pick budget is edited at the section grain, because
writing back less than was read is how notes lose their tails), and a
rich editor that cannot represent everything markdown can say MUST
offer the stored source as an editing surface, so what the operator
cannot see is still not silently dropped.

#### J.5.6 The setup screen

The console has exactly two pre-identity screens. The Gate (sign in) is one;
the setup screen is the other, and which one appears is not the console's
choice `GET /v1/health` already says whether a password door exists, and
it MUST also say whether setup is required. The console asks and renders the
answer. A console that decided this locally would eventually show a sign-in
form on a Station nobody can sign in to, which is the bug this whole section
exists to remove.

- It MUST collect a username and a password, MAY collect an email, and MUST
  label the email as optional in the interface rather than only in the API.
- It MUST offer the first-forest choice of J.2.4 empty or seeded demo —
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
only by mirroring a source tree `adopt` derives structure, it does not
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
  node to abandon, and the engine's own check that an id lives under the
  parent it names is unhelpful to someone who did not know they were
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
- **A new branch carries the A.5 index skeleton** `## Sub-branches`,
  `## Direct bananas`, `## Cross trails` so it reads like every other
  branch from the first moment rather than growing headings the first time
  something is planted into it.
- **Scope is the engine's, restated in the interface.** `ScopedVine`
  already refuses a write outside the grant, so a scoped principal cannot
  create at the root; the console MUST NOT offer a parent it knows will be
  refused. Hiding is presentation and never the control (J.5.1) the API
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
rebuilds the region deliberately which is the honest cost of ids that
are also addresses, and is stated here so that nothing downstream is
designed against a file manager this product does not have.

**F.30 (acceptance).** A principal holding `write` creates a branch through
the console's call and gets a node whose `type` is `branch`, whose id is
`<parent>/<slug>/_index`, whose parent index gained exactly one
`## Sub-branches` entry, and whose creation appears in the audit log with
a commit sha none of it written by the console. The same call with a
name that slugs to nothing is refused, a duplicate id is refused, and a
summary that breaks A.4 is refused by the engine rather than accepted and
truncated. A principal scoped to a subtree is refused a branch at the root
with `E_FORBIDDEN` and succeeds inside its own grant. All covered by tests.

#### J.5.8 The address bar (v0.30)

A console is a place, and a place has an address. Studio's did not: every
screen was served at `/`, and which forest, which console and which node
were open lived in application state alone. So a reload started the console
over first forest of the list, default console, nothing selected a
selection could not be sent to a colleague, and the browser's Back button
left the product because no history entry had ever been written.

**The URL is the console's state, not a decoration of it.** What is on
screen MUST be derivable from the address, and the address MUST be the
thing the console reads when it renders. A console that keeps a second copy
of where it is will disagree with the address bar eventually, and the
address bar is the copy the operator can see, share and edit.

| Part | Carries | Why there |
|---|---|---|
| `/f/{forest}/{console}` | the forest, and the console open on it | the forest scopes every request the page makes, and the console is what the page *is* |
| `?node=` | the selected node, across consoles | a node id contains `/` (A.2) and is not a path segment |
| `?…` | what the open console needs to be the same page | `mode`, `dataset`, `table`, `tab` the console's own selection, not its scroll position |

- **The forest comes first, and it is never re-chosen for the operator.** It
  is the scope of every call on the page, so a console that picks it again
  on a reload has changed *which data is on screen* without being asked. A
  URL naming a forest MUST win over any remembered preference.
- **Moving is a history entry; adjusting is not.** Choosing a forest, a
  console or a node MUST push; toggling a mode, a tab or correcting a
  selection that turned out not to exist MUST replace. Back is for undoing
  navigation, and a Back that walks a per-keystroke trail is a Back nobody
  presses twice.
- **The address is written by navigation, never by rendering.** Loading data
  MUST NOT rewrite it. The one exception is a selection the forest does not
  contain a table dropped since the link was written which MAY be
  corrected to what is actually shown, by replacement, because the
  alternative is an address that describes a page that is not there.
- **A parameter the console does not understand MUST be ignored.** Links
  outlive the version that wrote them, and a shared address is edited by
  hand. An unknown console falls back exactly as J.5.1 already says
  capabilities fall back; an unknown parameter value falls back to its
  default. Neither is an error screen.
- **The last place is remembered only to resolve a bare `/`.** Which forest
  somebody was last in is a convenience for the door, not an authority: it
  MUST NOT override an address, MUST NOT survive the grant that justified it
  (a forest no longer in `GET /v1/forests` is not a place to restore), and
  MUST NOT be the console's idea of where it is.
- **A forest the principal cannot see is said, not swapped.** An address
  naming a forest absent from this principal's list MUST be reported as
  what it is, with the forests they do have offered as the way on. Silently
  redirecting to a forest they can see is worse than an error: the operator
  followed a link to a specific place, and landing somewhere else without
  being told is how a person comes to believe they are in a forest they are
  not.
- **Restoring a place MUST NOT restore an action.** The address carries what
  is being looked at, never a call to make. A deep link MUST NOT cause a
  model call, a write, an ingest or a snapshot on arrival: J.10 composites
  cost money and Part C writes cost commits, and a reload is not consent to
  either. What an operator typed MAY be restored; what it produced is
  re-asked for by hand.
- **What has an address MUST be a link.** Every navigation entry, every
  forest in the switcher and every reference to a node MUST be a real
  anchor carrying that address, so the browser's own affordances open in
  a new tab, copy link, middle click, the status bar work. Intercepting
  the plain click is how it stays a single-page application; intercepting a
  modified click is how it stops being a web page. A control that can be
  unavailable is not an address and stays a button: `disabled` is a
  statement about a capability, and an anchor cannot make it.
- **Hiding is still not the control (J.5.1).** An address is application
  state a person can type, so a console reachable by URL but not by menu
  MUST refuse exactly as the menu implies which it already does, because
  the API is the authority and the guard is in the console, not in the way
  it was reached.

**The host answers the console's addresses.** A deep link is a `GET` of a
path that belongs to Studio and not to the API, and the Station is what
receives it.

- A `GET` matching no API route, no mount and no file in the build MUST be
  answered with the console's shell, so that reloading `/f/x/explore`
  reaches the same application that pushed it.
- It MUST be answered that way **only for document requests** a request
  that accepts HTML. A missing script or stylesheet MUST stay a `404`: an
  asset answered with the shell is an HTML body served under a JavaScript
  MIME type, which fails later, elsewhere, and unrecognisably.
- `/v1` MUST keep answering as the API (the J.1 rule that an unrouted `/v1`
  path is a JSON error, never the console), and the MCP mount is untouched.
- The shell MUST NOT be cached by the browser. It names the hashed assets of
  one build; a stale copy asks for files the deployment no longer has.

**F.34 (acceptance).** Opening a console, selecting a node and reloading
MUST return the same forest, the same console and the same selection. The
address MUST survive being copied into another browser with the same
principal, and Back MUST retrace the consoles visited rather than leaving
the console. A `GET /f/{forest}/explore` on the Station MUST return the
shell with `200`; `GET /assets/missing.js` MUST return `404`; `GET
/v1/nope` MUST return the JSON error envelope of J.1. An address naming a
forest outside the principal's grants MUST show that forest's name and an
explanation, and MUST NOT change which forest the console is reading.
Covered by tests.

#### J.5.9 The runs already made (v0.31)

Ask holds one result and then loses it: the next question replaces it and a
reload leaves none. So the console cannot do the thing it exists for. The
same question after an ingest, with the walk on (J.10.5), or against a model
rebound since are different answers to one question, and judging a forest is
reading them next to each other.

The console MUST keep the runs it made, and MUST keep them in the browser.

**A run is one submission.** The record is what was sent the question and
the parameters exactly as they went and what came back, whole: answer,
evidence, the material the model was given, the walk, the trace, the clocks
and the cost. Half a record is not a run: an answer without the material it
was drawn from is the markdown download, which the console already has and
which is not evidence of anything. The same question asked twice MUST leave
two runs, because those two are the comparison.

**It stays on the machine that asked, and nothing carries it anywhere.** A
run is the operator's working note about an evaluation, not a fact about the
forest, and the forest has already recorded the call it describes an audit
row (J.4) and pheromone (Part D), both written when the call ran. The
console MUST NOT send a run anywhere, and MUST NOT make a request in order
to show one: a history that needed the host would be a slower copy of
something the host does not have.

**Keyed by principal and by forest, and dead with the credential.** A run
carries node bodies read under a grant, and a grant is per forest (J.3). The
history offered MUST be the current principal's, on the current forest, and
signing out MUST discard what was kept. A browser is shared furniture, and a
console showing the previous operator's answers would be showing what the
API refuses J.5's no-side-channel rule, arriving through the back.

**Restoring a run restores a record, never a call.** This is J.5.8's rule
one level in. Selecting a run MUST put back the question and the parameters
as they were sent, and MUST show the response as received, labelled with
when it was made and which model made it: an answer whose model has since
been rebound reads as current otherwise, and telling the two apart is the
entire purpose. Asking again MUST be a deliberate act, and MUST leave a new
run rather than overwrite the one being read.

**A run has no address.** J.5.8 made the console's places linkable and a run
is not one: it exists only in the browser that made it, so an address naming
it resolves for its author and is broken for everybody else. The address bar
carries the console; the history is opened there, not linked to.

**The bound is stated out loud.** Retention is finite bodies are large and
browser storage is not the operator's disk. The console MUST keep a stated
number of runs per forest, MUST discard the oldest first, MUST show what it
is holding, and MUST offer to discard it. Silent eviction is C.6's
truncation rule in a different costume: what was dropped is said, or a
partial history is read as a complete one.

**Storage is a convenience and MUST NOT become a failure.** Private
browsing, a refused quota, storage switched off the answer on screen is
unaffected. The console MUST report the history as unavailable and MUST NOT
turn a storage error into a failed `ask`. It MAY offer the kept runs as a
file, asked for by hand, which is the only thing that should ever move them.

**F.35 (acceptance).** Two questions asked on one forest leave two runs.
Restoring the first puts back its question and its parameters, shows its
answer with the time it was made and the model that made it, and issues no
request to the Station. Asking again leaves the restored run intact and adds
a third. Signing out leaves no run readable, and a second principal signing
in on the same browser finds an empty history. The store never exceeds its
stated bound and says what it holds. With storage unavailable the console
still answers and says the history is not. Covered by tests.

#### J.5.10 The Data console (v0.44)

The Data console is a database client over the forest's datasets, and it
shipped without the three things every database client has: a way to make
one, a way to bring one in, and a way to leave the one you are in. What it
gains here are those three, and colour on the surface where SQL is typed.

**A dataset is born through one `plant`.** Exactly the J.5.7 rule for
branches, for the same reason: the id lives under a chosen parent, the
parent-index entry and the commit are the engine's, and the console composes
a single C.7.1 call carrying a declarative `schema`. Normative:

- The console MUST NOT write DDL, and MUST NOT offer a free-text SQL box for
  creation. Table and column names, the four types and the primary key are
  fields; the `CREATE TABLE` is the Vine's (C.7.1 rule 1). A console that
  typed DDL would be a second definition of what a dataset is.
- Ids are **never typed** and never moved. The leaf is slugified from the
  name, shown before the call, and immutable after it no primitive
  relocates a node.
- Creation requires the `plant` capability and a `dest` in scope. A console
  MUST NOT offer the control to a principal who cannot use it.
- Schema evolution stays absent. `tend` is DML-only forever (C.10) and there
  is no `ALTER` for agents or consoles; a table is changed by rebuilding it.

**A dataset is imported through J.8, never beside it.** The console MAY
accept `.db`, `.sqlite`, `.sqlite3`, `.csv`, `.json`, `.xls` and `.xlsx`
files and MUST send them as an `upload` ingest (J.8) the same converters
(G.2), the same curation (G.4), the same commits, the same J.9 job and the
same pill (J.9.3) as a folder dropped on the ingest console. Normative:

- Import requires the `ingest` capability, scope-checks `dest`, and MUST NOT
  let the caller name a host path (J.8: that is `admin` and J.8.2's roots).
- Binary sources travel as `b64`; the wire contract is J.8's `{name,
  text|b64}` and nothing else.
- The console MUST NOT plant an imported file itself, parse it in the
  browser, or pre-compute its schema. An importer that understood the file
  would be a converter living where nobody can extend it, and it would
  disagree with the Gardener the first time either changed.
- The answer is a job, not a dataset. The console says so, and the list
  refreshes when the job settles.

**A connection can be left.** While a dataset is selected the picker MUST
show that dataset its id, its scent, its tables and their row counts —
and MUST offer an explicit control that returns to the list. Rationale: the
list is a browse surface and the selection is a working surface, and a
console that keeps eleven other databases one mis-click away from the query
you are editing is inviting the mis-click. Leaving is a **navigation**, so
it clears the selection in the address (`?dataset`, `?table` J.5.8) and
pushes; it MUST NOT drop a pending write. Unapplied edits are a draft the
operator can still see, so the control MUST refuse (or confirm) while one
is staged rather than discarding it silently.

**A person teaches the dataset (v0.46).** A **Notes** tab beside Rows,
Structure and SQL edits the C.2.1 section, and composes ONE `graft` —
`replace_section`, or `append_section` the first time. Normative:

- It requires `write`, and a console MUST NOT offer it without.
- The tab value goes in the address like every other (J.5.8), which means
  it MUST be in the route validator's allow list. A tab that is not is a
  tab that bounces back to the first one when clicked.
- The console MUST NOT write the notes anywhere but the node's body. A
  side store would be teaching the agent cannot read, which is the one
  thing this must not be.
- What is being taught is prose about data, so the editor is the markdown
  one, coloured like every other source surface.

**Source is coloured where it is typed.** The console already colours every
literal surface it *prints* (statements pending a `tend`, stored DDL,
fenced blocks in an answer). The surfaces it did not colour were the
editable ones the SQL box and the markdown body editor which are the
surfaces a person actually reads while composing. The markdown one matters
most where the rich editor refuses: a body holding a table, which every
dataset's does. A plain `<textarea>` cannot hold spans, so the editor is a
highlighted mirror under a transparent input: same font, same metrics, same
wrapping, scrolled together, with the caret and the selection visible. The
input remains a real `<textarea>` native editing, native undo,
keyboard-accessible and the mirror is `aria-hidden`: it is a second
rendering of the same characters, and a screen reader must not read them
twice.

**F.46 (acceptance).** A `query` whose result exceeds `BUDGET_QUERY`
returns fewer rows than it matched, with `truncated: true`, the full
`columns` list and a hint naming the column count; a `SELECT *` on a table
wide enough that not one row fits returns zero rows, `truncated: true`,
`columns` intact and a hint carrying the per-row cost and the same
statement rewritten to name three columns returns its rows untruncated. An
aggregate is never truncated. `limited` and `truncated` are independently
observable. A statement naming a table that does not exist answers
`E_QUERY_INVALID` (HTTP 400) carrying the C.5 name hint, while attempting
a write answers `E_QUERY_FORBIDDEN` (HTTP 403); the same split holds for
`tend`. A walk whose entry `locate` returns a dataset puts that dataset's
`notes` in the model's first message without any `look` being called, and
a failed hop reports the error's message beside its code. A table with
more columns than the sample shows states the count and the `SELECT *`
warning in its `## Query manual`, and names every column anyway. Covered
by tests.

**F.45 (acceptance).** A dataset's `## Notes` section comes back from
`look` as `notes`, survives a `sync` that replaces the payload and rewrites
the map, and is never written by curation. Notes longer than the budget
come back clipped with `truncated`, and a digest over its overall budget
drops `sample_rows` before it drops them. The console's Notes tab issues
exactly one `graft` `append_section` when the section is absent,
`replace_section` when it is present writes nothing else, and its tab
value round-trips through the address. Covered by tests.

**F.44 (acceptance).** A 5 MB CSV adopted against a bound ingest model
sends the model the G.2.3 map and not the file: the request the Curator
issues is bounded by the map's own limits, the planted summary is the
model's, and a model that refuses leaves the G.4.1 template with the
fallback counted. A batch whose every document is a dataset or is
`unchanged` reports `curated: false` with `skipped > 0`, and the console
says nothing needed the model instead of reporting a rejection. A batch of
one document reports a job whose `stage` advances `convert → curate →
plant` while `done` stays 0, an observer that raises on every call changes
neither the report nor the commits, and a finished job carries `stage:
null`. A `.xlsx` whose `<dimension>` record declares `A1:A1` over a sheet
of many rows adopts every one of them. A workbook of 141 columns plants,
`query` reaches the last column, the sample shows 12 and says how many it
left out, and the manual names all 141 while the same 141-column schema
sent to `plant` **over the wire** is still refused by C.7.1. Covered by
tests.

**F.43 (acceptance).** A `.db` adopted by the Gardener plants ONE dataset
whose payload is byte-identical to the source, whose `payload_hash` matches
it, and whose body maps **every** table with its columns and first 3 rows;
`query` answers on the second table without any further ingest, and `sniff`
for a value that appears only in a sampled row finds the node. A source
whose bytes are not a SQLite database is reported as an error naming the
file, and the forest is unchanged. A `.xlsx` with three sheets plants three
tables; one with more sheets than C.7.1 allows is refused by name. A
`sync` after the source database changes replaces the payload, refreshes
`payload_hash` and the two map sections, leaves a curator's own section in
the same body untouched, and commits only the `.md`. Creating a dataset
from the console issues exactly one `plant` and no DDL; importing one
issues exactly one `ingest` and no `plant`. Covered by tests.

#### J.5.11 First access (v0.49)

The first signed-in minute decides what a person believes this
deployment is. Left alone, they conclude the obvious wrong thing: that
the console is the product. It is a window. The product is the forest
behind it a knowledge base external agents feed and read through MCP,
growing for as long as somebody keeps it and nothing on a stats page
says so.

So the console MUST offer a one-time presentation after the first
sign-in: what a forest is, that AIs connect to it and feed it through
MCP, and where to start ask, feed, connect. It is chrome, wholly:

- **Dismissed once, gone for good per browser.** The flag is written
  when the person dismisses it, and lives in browser storage, the same
  standing as the reply-size preference (J.10.8): a personal setting,
  never in the address (J.5.8 the address restores a page, never a
  call). Until it is acknowledged it MAY appear again an unacknowledged
  presentation is an unread one, not a delivered one.
- **It spends nothing.** Rendering or dismissing it MUST NOT issue a
  model call, a commit, or any write beyond that browser-storage flag.
  It may only ever *link* to consoles that do real work.
- **It never precedes identity.** J.2.4's setup window and J.5.6's gate
  are exactly what they were; the presentation appears only inside a
  session, and MUST NOT block the console dismissable, skippable,
  translated like everything else (J.5.3).
- **Overview MAY restate it permanently, small**: a standing pointer to
  the Skills console (J.5.12) and the integration manual, because the
  person who dismissed the presentation on day one is the person who
  needs the door on day thirty.

**F.53 (acceptance).** A fresh browser profile signing into a served
Studio is shown the presentation; dismissing it produces no request
beyond what the landing console already makes, and after dismissal it
never appears again in that browser; and the integration manual's menu
entry renders **MCP / API / Integrations** in each of the three languages
of J.5.3.

#### J.5.12 The Skills console (v0.49, blocks v0.60)

A *skill* is a small instruction file an agent runtime Claude Code
and its kin loads to learn a workflow. The workflow this Station
wants every visiting agent to learn is: **use this forest as your
persistent memory** recall before answering, save what you learn,
cite the node ids you read. The Skills console hands that file over
instead of asking the person to write it.

- **Self-service, never admin-gated.** Available to any principal whose
  grant holds `read` on the open forest. Pairing (J.2.6) made the
  credential self-service; the Clipper (J.15) made distribution
  self-service; a skill gated behind an administrator would undo both.
- **Generated where it is read.** The skill text carries this Station's
  own origin and the open forest's id Integrations' rule verbatim:
  documentation that cannot drift from the deployment it documents.
  Produced client-side, delivered by copy or file download; the Station
  gains **no endpoint** for it.
- **It teaches only the published surface, shaped to the key.** Every
  operation the skill instructs goes through the MCP tools as documented,
  under the person's own paired key: recall through
  `locate`/`harvest`/`answer`, and **saving through `ingest`** one
  markdown document through the Gardener because that is the one write
  the J.2.6 default mask actually carries. `plant`/`graft`, `query` and
  `tend` MUST be taught only as conditional on a key that carries
  `write`/`query`/`tend`: a skill that teaches a write its own credential
  step cannot perform, to an agent it also teaches "never work around a
  refusal", is a contradiction obeyed straight into silence (v0.49 this
  corrects the earlier wording). No third write path (J.15), no
  privileged side-channel (J.0, J.5).
- **The walkthrough names pairing as the credential step.** A person
  installs this against their own password-derived key with the default
  `{read, ingest}`-style narrowing of J.2.6 never by asking an
  administrator to mint one.
- **The file addresses a model, not the reader.** Its body is English
  regardless of the console language like SQL, ids and model output,
  it is content the console must not rewrite (J.5.3); the surrounding
  walkthrough is translated like any other chrome.
- **The skill states its age (v0.56).** The generated file carries the
  Station version it was built against, and its body teaches the check:
  `forests()` returns `station` (J.1.2 rule 6); when the server is newer
  than the skill, the agent MUST tell its operator to re-download the
  skill from this console rather than navigate by a stale map. The team's
  round-without-`scan` was exactly this failure: the tool existed, their
  downloaded skill predated it, and nothing anywhere said so. A skill is
  a cached copy of the surface; v0.56 gives the cache a validator.
- **The skill teaches writing (v0.57).** The consumer team's seventh
  report measured the asymmetry: they planted well-formed nodes only
  because they had read the engine's source in earlier rounds — an agent
  on its first session would plant nodes with no aliases, no edges and
  possibly an undeclared rel, and the forest would get worse with nobody
  told. The skill (and the MCP tool descriptions — the `plant` tool's
  `node` parameter carried an EMPTY description) MUST teach the **anatomy
  of a node**, conditional on a writing key as ever:
  1. the `node` shape — required and optional fields, each with its role;
  2. `aliases` presented as what it is: the findability lever, because
     `locate` reads curated metadata and never bodies — "give the node
     the names people will actually type";
  3. the summary ceiling, **with the number** (60 tokens): the error
     message names it, but it arrives after the body crossed the network;
  4. the id-determines-parent rule: every intermediate level must exist
     as a branch, and the id is forever;
  5. read `_meta/schema` (one `pick`) before the first write in an
     unknown forest — types and rels are per forest and undeclared ones
     are refused;
  6. `fields` in `look` and `scan` as the cost lever, stating that fewer
     fields means bigger `scan` pages;
  7. `dry_run` (C.7.3) as the rehearsal before an expensive plant.
  And one footnote naming the two REST surfaces an agent wants the moment
  it writes for people: `export` (J.14.1) and share links (J.17). The
  team probed for shares by guessing URL patterns and filed as missing a
  feature that had shipped — a surface the skill does not name does not
  exist.
- **The skill teaches the document's past (v0.58):** `transplant` as the
  repair for a misplaced node (and that the old id keeps finding it),
  `history` as "what happened here and who did it", the batch `plant`
  as the way several related nodes land whole or not at all, and
  `supersedes` vs `succeeds` — the judgement and the timeline, chosen
  deliberately.

- **A skill is a folder, and the core is what every agent pays (v0.60).**
  The file has grown every version that touched it born at ~2,300
  tokens in v0.49, the age stamp in v0.56, the anatomy of a node in
  v0.57, `transplant`/`history`/batch in v0.58, `coverage` and
  `min_score` in v0.59 and it arrived at **3,921 tokens, +14% in that
  last release alone**. Growth is not the defect; the defect is that it
  is indivisible. A runtime keeps only the `description` in context and
  loads the body when the skill fires, so the number that matters is what
  a *firing* costs and every agent pays all of it, including the ~1,400
  tokens of `plant` anatomy that a J.2.6 paired key, carrying
  `{read, ingest}` by default, is not able to execute. The console MUST
  therefore deliver a skill **folder**: a `SKILL.md` holding what every
  agent needs, and `references/*.md` holding what only some do, read by
  the agent in one call when the core sends it there.

  | file | required capability | what it holds |
  |---|---|---|
  | `SKILL.md` | `read` | what a node is, `forests()` first, the age check, the read loop, `locate` ≠ `sniff`, `coverage` before a silence, citation, refusals and budgets |
  | `references/saving.md` | `ingest` | the one write a paired key carries by default: one document through the Gardener |
  | `references/writing.md` | `write` | `plant`/`graft`/`prune`/`transplant`/`history`, the batch, `supersedes` vs `succeeds`, and the anatomy of a node |
  | `references/time.md` | `read` | `calendar` and the `since`/`until` window |
  | `references/datasets.md` | `query` (and `tend` to write) | `look` for the `## Notes` first, then read-only SQL, then single-statement DML |
  | `references/sharing.md` | `read` | `export` and share links the two REST surfaces an agent wants the moment it writes for people |

  Four rules make the split safe:

  1. **The core alone is a complete skill**, never a teaser: an agent that
     reads nothing else still recalls correctly, still knows that an empty
     `locate` is not an empty forest, and still cites what it read.
  2. **Every reference is named in the core, with the condition that sends
     the agent to it.** A file the core does not name does not exist
     which is the v0.57 footnote's lesson about `export` and shares,
     applied to the skill's own parts.
  3. **No instruction exists in two blocks.** A sentence kept in two
     spellings is two contracts, and they diverge on the first edit.
  4. **Several installed skills is NOT the split.** Each one costs its
     `description` in every session whether or not it fires, and the
     *runtime* decides which loads a model that does not yet know it is
     about to write will not load a writing skill. One skill that names
     its own references routes deterministically and costs nothing for
     what it does not read.

- **The key chooses the blocks, and a person may overrule it (v0.60).**
  The console already knows the grant it renders under, so the default
  selection is exactly the capabilities of the key on the selected
  forests. A block whose capability the key lacks MAY still be generated
  deliberately somebody preparing a skill for a colleague whose key is
  wider and when it is, its first line MUST name the capability it
  requires. That keeps the v0.49 correction honest: teaching a write
  *conditionally* is legitimate, teaching one unconditionally to an agent
  whose credential cannot perform it is the contradiction obeyed straight
  into silence. The archetypes the split exists for — reads, reads and
  remembers, curates, analyses datasets, everything — MAY be offered as
  named shortcuts through the same list, never as a different list: what a
  shortcut selects must be exactly what a person could tick by hand, or
  something becomes reachable only through a preset.

- **Single-file assembly stays (v0.60).** Not every runtime takes a
  folder, and a person pasting one file into one path is the shortest
  install there is. The console MUST offer the same selection inlined
  into one `SKILL.md`, and the two assemblies MUST teach the same
  surface: the inlined file is the concatenation of the parts, never a
  different edition of them.

- **An example is a call (v0.60).** Every primitive on this surface takes
  `forest` as its first argument, and the generated skill's twenty-three
  call examples passed it *not once* `answer(question)`,
  `coverage()`, `scan(root, filter: …)`. The forest lived in the title,
  in the `description` and in no call the model was ever shown. Every
  example in every generated file MUST carry the forest argument in the
  shape the tool takes; the file states once, concretely, what that
  argument is, and never writes a call without it afterwards.

- **The skill is for the forests it names, and `forests()` is the
  authority (v0.60).** The console offers the forests the key reaches,
  as a selection, with the open one already chosen so that a person
  configuring an agent for two forests hands it one skill instead of
  choosing which half of its memory to install. The rule that keeps the
  selection from becoming a lie is that **a baked id is intent, never
  authority**:
  1. `forests()` MUST be taught as the first call. It is the only place
     capabilities, roots, `locked` and `station` are true *at the moment
     of use*; everything baked was true when the file was generated.
  2. A named forest whose grant has since lapsed answers `E_NOT_FOUND`
     like anything else outside a key, and the skill MUST say so: that is
     the ordinary shape of a narrowed key, not a defect to report or work
     around (J.3's byte-identical refusal, read from the agent's side).
  3. **More than one forest MUST carry a routing table** one row per
     forest: its id, its largest roots, and the capabilities the key held
     there when the file was made built from `coverage` (C.17) at
     generation time. Without it a model either sweeps every forest at N
     times the cost or picks one in silence, and picking in silence is
     the failure C.17 exists to prevent, one layer out.
  4. **One forest MUST NOT carry a baked table.** Inside a single forest
     `coverage()` is one live call, and a copy of a forest's shape can
     only drift from it the same reason this console generates its own
     text from the deployment it documents rather than shipping a
     written-down copy.

**F.52 (acceptance).** A principal holding `read` opens the Skills
console and receives a skill whose text contains the Station's own
origin and the open forest's id, and whose install steps require only a
paired key. An admin gate on the console, or a new server endpoint
minted for the artifact, is a failure.

- **The selection is in the address, and the skill names the way back
  (v0.60).** The blocks, the forests and the assembly are this console's
  selection, so they ride the query like every other console's (J.5.8) —
  and here that rule earns more than consistency: the address IS the
  regeneration. The generated core names it, so an agent that has just
  discovered its own staleness hands its operator the one link that
  rebuilds *this* skill — same forests, same blocks, same assembly —
  against the Station as it now is, instead of "re-download it from the
  console" and a selection nobody wrote down. Visiting it spends no model
  call and commits nothing, which is what makes it safe to put in a file
  an agent reads.

  **And the agent MUST NOT install it.** Not because it could not — it
  holds file tools, and the text would be one tool call away if the
  surface ever served one — but because a skill outlives the connection
  that delivered it. The MCP instructions and every tool description
  reach a model only while it is connected; a file under
  `~/.claude/skills/` keeps instructing it in every later session,
  including sessions this Station is not in. What persists past the
  connection is a person's decision. So the Station still gains no
  endpoint for the artifact (v0.49's rule, unchanged) and the surface
  gains no `skill()` tool — which would additionally charge every
  connected client its description in every session, forever, to save a
  paste that happens once a release. The staleness check is a validator
  and the link is the repair; neither is an install.

- **The skill is generated FOR a deployment, so it may not teach a call
  that deployment refuses (v0.61).** This console exists precisely so
  documentation cannot drift from the Station it describes, and the v0.60
  file drifted anyway in three places, each found by an agent following
  it: the saving example passed `dest: "decisions/_index"`, the canonical
  branch form, which the server refused (G.3 fixes the server; the example
  is fixed too, because two halves of one product disagreeing about a
  spelling is the defect, not either half); the same block never mentioned
  `source_url`, so every document an agent saved arrived without an
  `origin` and the gap was then reported as a missing feature; and the
  answer block taught `min_evidence: 2` without J.10.10 rule 8's pairing,
  which turns a floor into a universal refuser as soon as `min_score` is
  set. A generated file MUST be checkable against the surface it names,
  and the check runs in the suite (`check-skill.mjs`).
- **The skill is named for what it addresses (v0.61).** `name:` was a
  constant, so a person generating one skill per forest as the console
  invites installed two files claiming the same name. The name derives
  from the selected forests, deterministically, so two selections that
  differ produce names that differ and the same selection reproduces its
  own byte for byte (J.5.8).
- Acceptance: **F.52**, **F.111 – F.116**, **F.127**.

#### J.5.13 The page declares what it may load (normative, v0.50)

Studio renders two kinds of untrusted text as markdown: what a model
wrote, and the body of an ingested document. Both are untrusted by the
product's own premise ingest is how outside material gets in, and J.15's
Clipper exists to capture third-party pages.

That matters here because of *where* the rendering happens. Whatever such
text can talk the page into fetching, the page fetches from the reader's
own authenticated browser, and the Station is not on that path at all: the
request never arrives, so no host-side check can be the control. The
control is telling the browser the rules before it reads anything.

The Station MUST therefore serve, with every response:

| Header | Requirement |
|---|---|
| `Content-Security-Policy` | `default-src 'self'`; `img-src` limited to same-origin, `data:` and `blob:`; `connect-src 'self'`; `frame-ancestors 'none'`; `object-src 'none'`; `base-uri 'none'` |
| `X-Content-Type-Options` | `nosniff` — a JSON envelope is filled with forest content, and one sniffed as HTML is a scripting surface |
| `Referrer-Policy` | `no-referrer` — a console address names the forest and the node being read, which belongs to the reader |
| `X-Frame-Options` | `DENY`, for browsers that do not implement `frame-ancestors` |

`img-src` is the load-bearing line, and it costs nothing legitimate: a
forest image is fetched through J.14 with the viewer's own credential and
rendered from a blob, because an `<img src>` cannot carry the bearer
credential in the first place (J.10.9). An off-origin image address in
rendered output is therefore never something the console asked for.

Two implementation constraints are normative because getting them wrong is
silent:

1. **Inline script is allowed by hash, and the hash is computed from the
   built shell**, not written down beside it. The console applies the
   saved theme inline before first paint (J.5.3); a digest maintained by
   hand goes stale on the next edit of that script, and the failure is a
   page that still loads with the script simply not running.
2. **Styles keep `'unsafe-inline'`** — style attributes and the diagram
   renderer both require it — **and script MUST NOT.** No `'unsafe-eval'`
   either; the console's bundle needs neither.

The console's renderer SHOULD additionally drop image sources it did not
itself resolve. That is a second layer, not the control: it protects a
deployment serving the bundle from something that does not send these
headers.

**F.54 (acceptance).** (a) A statement reaching a table outside a grant's
allow-list is refused with `E_QUERY_FORBIDDEN`/403 through `query` and
through `tend` alike, in whatever syntax it is written, and the refusal
does not name the table; a permitted statement is unaffected. (b) A
principal administering one forest of several can list providers and
cannot edit or test one; a principal administering every forest can.
(c) Changing a provider's endpoint without supplying its key is refused,
and the stored provider is unchanged. (d) Issuing a key, granting,
setting a password, changing a provider and signing in each leave an audit
row, and no row contains a secret. (e) The console's shell is served with
the headers above, and the policy admits the shell's own inline script.

#### J.5.14 The reading console (v0.56)

Every console until now was an instrument: Explore operates on a node,
Ask interrogates the forest, Data edits datasets. None of them *shows a
document to a person* — Explore renders the body as raw markdown in a
code block, through `pick`, which means a document over the C.4 ceiling
renders as nothing at all, in the product's own console. The consumer
team's number-one reason for keeping local `.md` files was literal: the
operator asked for "an analysis in `.md` to send to the dev team",
because a forest document had no form a person could be handed.

`/f/{forest}/read` (selection in `?node=`, J.5.8 as ever) is the page a
document is READ on:

1. **The body arrives whole, through J.14.1's export** — never through
   `pick`. The C.4 ceiling protects a model's context window; a person
   scrolling is not that, and rendering a truncation the surface imposed
   on itself would misreport the document to its own author.
2. **Rendered, not quoted.** The body renders through the same markdown
   pipeline as model output (J.5.13 CSP applies; it is ingested,
   untrusted text) with `media:` resolution through the viewer's own
   credential (J.10.9) — an out-of-scope image renders as its caption
   here exactly as it does in an answer.
3. **The outline is the sidebar.** C.4's section list, as anchors. A
   28-section report is navigable, which is what the outline was always
   for.
4. **The raw markdown is one click away** — copy, and download via
   J.14.1 (the export route is the download; the console adds no second
   path).
5. **Reachable from where the document is found:** Explore's node panel
   links to the reading page, and the reading page links back. A share
   link (J.17) is minted HERE, because "hand this to somebody" is a
   reading-page act, not an operating-console act.

#### J.5.15 The path an answer took (v0.65; drawing only what happened, v0.67)

J.10.4 gave the Ask console the material an answer was built from, and the
console lists it. A list is the right form for checking a citation and the
wrong form for one question a demonstration always gets asked: *where in
the forest did that come from?* The forest is a graph, J.5.4 draws it, and
until now nothing connected the two — the console that knew which nodes
were read could not show where they were, and the console that showed where
everything was did not know which had been read.

The Ask console MAY draw a second panel: the same material, on the map it
came out of. It is presentation over data already returned, and every rule
below exists to keep it that.

1. **It costs the answer nothing, and it is its own switch.** The map is
   one J.11 `graph` read and the retrieval preview — where rule 2 allows
   one at all — is one `harvest`, both on the reader pool (J.6.2), both
   concurrent with the answer, neither on its critical path. It costs the
   forest nothing either: a panned or zoomed view spends no call (rule 10).
   The switch MUST be separate from the J.10.5 walk switch. They are not
   the same cost — a walk is one model call per hop and the drawing is
   none — and a single control over both would teach an operator that the
   picture is what made the answer slow.
2. **The preview is the same sweep, not a similar one — and only where
   there is a sweep (amended v0.67).** The console MAY run the retrieval
   itself, before the answer returns, and when it does it MUST send the
   question, `k` and entry ranker the answer is being asked with. It MUST
   NOT deposit heat: pheromone is the whisper's, at the close of an answer
   (J.10.7). When the answer lands, its own bundle replaces the preview —
   they are the same sweep, but only one of them is what was answered from.

   **The preview is therefore mode-aware.** That whole justification is a
   sweep-mode sentence. A walk runs no `harvest` at all: its entry is a bare
   `locate` and every retrieval after it is a call the model authored
   (J.10.5), so a `harvest` fired beside a walk is not the same sweep, it is
   a sweep that never happened — and painting its results as the answer's
   retrieval is exactly what rule 3 forbids. When the walk switch is on, the
   console MUST NOT fire a preview; and because the same rule governs it,
   the fallback a console runs when no progress channel answers MUST NOT
   fire one either. **A walk's panel starts empty**, which rule 3 already
   says is a fact and not a placeholder, and fills as the walk moves: from
   J.10.12's `hop` events while the call is open — which is what the hop
   record's `ids` (J.10.5, v0.67) exist to make drawable — and, at the
   close, from the response's own `read` and `evidence`. Nothing is drawn
   ahead of the walk, because ahead of the walk there is nothing to know.
3. **Every stage is read off returned material.** `found_by` says which
   retriever reached a node (C.6c); `content` says what was handed to the
   model. A stage MUST NOT be inferred, filled in, or narrated. A stage
   with nothing in it is shown as empty, which is a fact, not a placeholder
   for something still coming.
4. **`cited` is a walk's stage and not a sweep's.** On a walk the reply
   names `answer_nodes` and the host keeps only those it opened (J.10.5) —
   a choice, and drawable as one. On a sweep `evidence` is every id in the
   bundle, because the reply is prose and cites nothing; presenting that as
   "cited" would draw a selection that did not occur, so on a sweep the
   stage MUST NOT exist.
5. **The trail is the forest's own structure.** The line from the root to
   a hit follows `parent`, which J.11 has already filtered to what this
   principal may see: a chain that leaves the scope stops, and never draws
   a segment to a node the caller cannot read. Shared ancestors are drawn
   once, at the earliest stage that needed them.
6. **A trail is not a shortcut.** It carries its own colour token. A
   `discovered-shortcut` is a fact the forest holds and a trail is what one
   question did to it, and two different facts MUST NOT arrive in one
   colour. Proposals (`confidence < 1`) stay dashed, as in J.5.4 — and
   under rule 9 this panel draws none of them, which satisfies the
   distinction by not raising it.
7. **The panel states its own speed.** The reveal is seconds and the
   retrieval it depicts is milliseconds, so the real figure MUST be shown
   beside it, read off the Part D trace (J.10.4) and never a second
   stopwatch. This console's subject is how little retrieval costs; an
   animation that let an audience read its own duration as the measurement
   would misreport the product in the one place it is being judged.
8. **Presentation stays out of the address** (J.5.8). The switch is a
   browser preference like the reply size (J.10.8); the address carries the
   selection, not the taste.
9. **The background is dots, and the trail is the only line (v0.67).** The
   map's purpose here is *where*, not *how everything connects*: the panel
   draws the projection's nodes and MUST NOT draw its edges. What it used to
   draw was every edge J.11 returned, the `confidence < 1` class included —
   the class Explore hides by default — and at twice the opacity of
   structure, so on a curated forest the answer's trail was laid over a mat
   of proposals nobody had asked to see. The edge set is still read and MUST
   still feed the layout: paint and physics are separate concerns, and
   Explore has always shipped exactly this split (its hidden proposals pull
   as springs while no line is drawn for them), so the clusters, the hubs
   and the branch discs are unchanged.

   **The dots carry the one fact the panel is about: where.** They are
   coloured by **home branch**, which is a fact the forest holds (J.5.4's
   rule for colour), and by the same grouping the operator's own Explore is
   showing them — the per-forest stored view settings, and Explore's own
   defaults when there are none. Two consoles over one forest that group it
   two different ways teach an operator that the branches moved. They stay
   dim, because the trail and its stages are the subject and the map is the
   room it happened in. And **whichever fact colour encodes, the legend
   names it** (J.5.4, v0.38): a branch-coloured background owes a legend
   line that a grey one did not.
10. **The panel is placed under the answer, and it can be moved (v0.67).**
    The answer is what was asked for; the panel is where it came from, so it
    sits **below** the reply rather than beside or above it. Its switch is
    a compact control of its own — default **on**, so a demonstration shows
    the product's subject without a preparation step — and it remains rule
    8's kind of choice: a per-person browser preference, never in the
    address, and never the same control as the walk switch (rule 1). The
    panel MUST accept zoom and pan — wheel or pinch, drag, and a gesture
    that restores the fitted view — because a forest of a thousand nodes
    drawn to fit is a field of dots, and the question this panel answers is
    read by looking closer at one part of it. Navigating the view is
    presentation and spends nothing: no call, no write, no heat, and no
    change to rule 7's figure, which is the retrieval's own millisecond
    count and not the panel's.

Live hops — a walk's steps arriving one at a time rather than together at
the end — were not this section in v0.65, because they needed the host to
push. **J.10.12 is that push (v0.66)**, and rule 2 above is how this panel
consumes it: on a walk the events are not a garnish on a drawing that was
already made, they are the only honest source it has.

### J.6 Deployment

A Station deployment MUST be reducible to one container image plus two
volumes the forest registry and the host registry with no external
database required. Snapshots (Part I) remain the backup unit; the host
registry is backed up alongside them.

**The first minute is a log line (normative, v0.28).** A Station's startup
output MUST reach the container log as it is written unbuffered, or
flushed at emission. Everything J.2.5 specifies is delivered through this
channel and through no other, so a default block buffer does not degrade the
feature, it deletes it: the operator reads the log at the one moment it is
empty, concludes the product has nothing to say, and goes looking for a
password that was never printed.

#### J.6.1 Boot opens the forests

A forest is opened on its first touch, which means the first caller pays
for it: measured on a fresh Station, that request costs roughly ten
milliseconds of host against a third of one from the second call on, and
none of the difference is the corpus. It is SQLite waking up. On a console
whose whole subject is how little retrieval costs, the person most likely
to be shown that number is the one evaluating the product.

A Station MUST therefore open and warm (C.6.1) every servable forest at
boot, and it MUST be possible to turn that off. The cost is what makes the
switch necessary: opening holds a few megabytes of resident memory per
forest, which is fine for a registry of ten and is not for a registry of
five hundred. Default on, because the deployment that never thinks about it
is the one that should be fast.

**Best effort, never fatal.** A forest that will not open a writer lock
left behind, a catalog that needs rebuilding MUST be skipped and the
Station MUST start. Refusing to serve thirty-nine forests because the
fortieth was busy is not a performance feature.

**Warming is not a request.** It runs through `warm()` and therefore leaves
no trace event, no heat and no audit record. A boot that logged forty reads
nobody made would corrupt the two things this product asks to be trusted
on: the pheromone and the audit trail.

**F.33 (acceptance).** On a Station started with warming on, every servable
forest MUST be open before the first request arrives, and the pheromone and
the audit log MUST be exactly as they were before boot. A forest holding a
foreign writer lock MUST leave the Station running and serving the others.
With warming off, opening MUST go back to happening on first touch. Covered
by tests.

**The working directory is not a location (normative, v0.26).** A Station
process MUST NOT run with its own installation tree as its working
directory. The rules of G.3 and J.8.2 are what *prevent* an unnamed source
from being walked; this one decides what an unnamed source would have
reached had they failed, and the answer should be an empty directory
rather than the product's source code. Ingestable material belongs on its
own volume, mounted for that purpose and named in `MONKEYLLM_INGEST_ROOTS`
— never on the image.

#### J.6.2 Reads scale (v0.57)

The first production deployment under real agent load locked up, and the
operators' report used the right word: *frozen*. Not when a model
answered — when an agent **planted**. One thread per forest (J.9) meant
every read queued behind every write, and a write is a git ceremony
measured at 69× a `locate` on a fast local disk, before the container's
overlay filesystem multiplies it. C.9 has said "one writer, N readers:
reads never block" since Phase 0. The engine honours it — WAL readers
never wait on the writer — and the host was the one violating it, by
making N readers share the writer's thread.

Each open forest now has a **reader pool** beside its writer lane:

1. **K read-only engine instances** (`writable=False` — no lock, C.9),
   each confined to its own thread exactly as the writer is to its lane.
   SQLite connections still never cross threads; there are simply more
   threads, each with its own connections, tracer and embedder seam.
2. **Reads run on the pool.** Every read primitive, the composites'
   retrieval, and the map projections (J.11) dispatch to a reader lane
   (round-robin). Writes (`plant`, `graft`, `tend`, `prune`), ingest
   steps, and admin repairs (reindex, canopy build, restore) keep the
   writer lane, unchanged.
3. **Freshness is WAL's promise, stated honestly:** a read sees every
   write whose commit finished before the read's transaction began —
   C.9's "up to 1 write behind", now observable. A caller that needs
   read-your-write reads its write's own *response*, which is where the
   engine already answers what changed.
4. **Pheromone is deposited exactly as before.** A reader Vine's reads
   are reads; heat, traces and audit rows are identical in kind to the
   single-lane ones. (This is why C.9 gains `busy_timeout`: N readers
   are N occasional writers to the trails store.)
5. **Sized by `MONKEYLLM_STATION_READERS`** — default 4, `0` restores
   the single-lane behaviour byte-identically (the pool is an
   arrangement of threads, never a contract change). Readers open
   lazily, on their own lane, on first use: boot warming (J.6.1) warms
   the writer; multiplying boot cost by K would move the cold-start
   problem, not solve it.
6. **The lanes are still the only door.** `app.state.pool` remains
   reachable only through the lane accessors; a reader vine belongs to
   its lane exactly as the writer belongs to J.9's.
7. **A held writer lock stops writes, not reads.** v0.55's total outage
   — a live foreign holder refusing every primitive — narrows to its
   true size: readers take no lock, so reads and answers keep serving
   while writes answer `E_LOCKED` naming the holder (C.9's own model —
   the flock is writer-vs-writer, and WAL never made a reader wait).
   Likewise, with warming off a READ no longer opens the writer: the
   pool opens on the first write or admin touch, and `GET /v1/forests`'
   `active` describes the writer, which is the thing its `locked` probe
   was always about. With the pool disabled (`0`), the single lane's
   old refusals return, byte-identical.

What this buys, stated as the incident that demanded it: during a batch
ingest whose curation model call holds the writer lane for seconds per
document, and during any agent's plant, **every read of that forest
proceeds** — a hundred agents consulting a forest wait on nothing but
their own reads.

### J.7 Forest lifecycle

A deployment that can only serve forests placed on its volume by hand is
not self-service. `POST /v1/admin/forests {id, title, summary?}` creates
one, and creation is exactly A.5 `init_forest` the same skeleton,
dialect and embedded git a local `vine init` produces. The Station adds no
second way to make a forest.

- The `id` is a directory name inside the registry root and MUST be
  validated **as a name, before it is a path**: a bounded character set,
  no separators, no relative segments. Rejecting after joining is too
  late.
- Creating requires the `admin` capability on some existing forest **or the
  owner bit (J.2.4)** the authority to govern a forest is the authority
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

The three batch modes `adopt`, `sync`, `upload` validate synchronously
and answer **202 with a job** (J.9); `compose` is one document and a review
conversation (J.8.1) and answers in place.

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
#### J.8.3 An upload is a courier, not a mirror (v0.61)

An upload was two code paths — `adopt` the first time, a refresh of the
staging **directory** every time after — and both halves were wrong in the
same way: they treated the staging area as a *source tree this forest
mirrors*. The consequences were found in the field, and they compound.

`adopt` records its source as the forest's `source_root`. So **one upload
repointed a forest that really did mirror `/data/handbook` at the upload
staging area**: the recorded root is what a refresh re-reads and what a
console MUST show beside the refresh control (J.8's own rule above), so
the operator's Sync now described the courier and the folder they had
adopted was forgotten.

And because the refresh walked the whole directory, every file any previous
batch had ever uploaded was re-examined on every upload. A file whose node
had since been **pruned** no longer had a passport to diff against: it was
not a refresh candidate, it was a new document, and it was **planted
again** — a fresh timestamp, a fresh curation, an edge into the material of
the batch that resurrected it. The remover had been told `pruned: true`, in
a previous session, and the forest contradicted it a day later without an
act by anyone. In a memory that is worse than a write that fails: a failed
write is retried, a resurrected one reintroduces material somebody decided
to withdraw — a wrong fact, a private one — and the removal is what looked
successful.

Underneath both is the same unstated assumption, and stating it is the fix:
**staged bytes are a courier.** They are how a document reaches a Station
that its author cannot otherwise write to; they are not a folder anybody
mirrors, and they are not where anything lives.

1. **One path, first upload or hundredth.** The pass is scoped to the
   entries of THAT request: an entry with no passport is planted, an entry
   whose name matches a passport's recorded source path refreshes that node
   (never a second one), and nothing else in the directory is touched,
   reported or looked at. A call may only testify about what it walked, so
   `stale` covers the named set alone.
2. **An upload records no source root and no destination.** `source_root`
   is what a refresh re-reads; a courier is not that. A forest whose only
   ingest was uploads therefore has none, and a console correctly does not
   offer the refresh control at all.
3. **Bytes that became a node are removed as they land**, and the report
   names them (`consumed`). The node is the record; a copy left in the
   courier is what a later pass reads as a document nobody sent. Bytes that
   did NOT become a node — a conversion error, an unsupported format — are
   kept: nothing landed, and the file is the only evidence of what was
   sent. The engine never decides this on its own: consumability is
   declared by the caller that staged the bytes, keyword-only and
   unreachable from the wire (G.2.5's construction), because the general
   rule stands — **this pipeline deletes no source it did not stage** (G.3),
   and a mirrored host directory is never touched by any of it.
4. **A staged source never backs a `reference` body** (G.7). A `reference`
   body is re-read from its source at every `pick`, and this source is one
   the forest itself may discard; the policy degrades to `cached`, exactly
   as it already does for a converted body that has nowhere else to live.
5. **What remains is countable and clearable** (J.13.7). Failures,
   cancelled batches and — on a forest ingested by an older Station —
   documents whose nodes were later pruned. Invisible accumulation is what
   made the resurrection possible, so the answer is not a shell.
6. A pruned node's staged file goes with it (C.14 rule 2). Under rules 1–3
   there is usually nothing left to take; the rule exists for every forest
   ingested before this version, which is all of them.
- An upload entry MAY carry `source_url` (v0.48): where these bytes came
  from, when the origin is an address rather than a directory a clipped
  page, a saved image. **It is also the whole of an uploaded document's
  `origin` (v0.61, stating G.2.7 rule 1 from this side).** An adopted file
  has a path and the Gardener writes it; an uploaded one has a staging
  path, which is a fact about plumbing and is deliberately not recorded,
  so an upload that declares nothing gets no `origin` and `coverage`
  counts it in `without_origin` correctly. This was read from outside as
  the feature missing, twice, because nothing on any surface said the
  field existed: a console offering upload MUST offer somewhere to state
  it, and a generated skill teaching upload MUST name it. `http`/`https` only, at most 2048 characters;
  anything else is `E_SCHEMA`. The host hands it to the Gardener as a
  **provenance map** (source path → URL; public plugin API v1, additive
  like `extra_converters`), and the Gardener appends a final
  `Source: <url>` line to the converted body the same line a composed
  clip already carries **on adopt and on every refresh alike**, so a
  re-uploaded screenshot keeps its address (a refresh rebuilds the body
  from the converter, and provenance recorded only at curation would
  vanish with the first `sync`; curation keeps its G.3 rule of never
  running on refreshes). Provenance is prose, not a new frontmatter
  field: the origin survives where a person can follow it and `sniff`
  can find it. It applies to every conversion of that entry, including
  the G.5.1 stub and describer bodies, which is what lets a screenshot's
  node say what page it is a screenshot **of**.
- The result is the Part G `IngestReport` created, updated, unchanged,
  unsupported, errors unabridged. A partially successful ingest that
  reports success is worse than one that fails. For the batch modes the
  report arrives on the finished job (J.9); for `compose` it is the
  response body, as before.
- Curation uses the forest's `ingest` binding (J.10) when one exists and
  the deterministic G.4 derivation when it does not. Ingest MUST NOT
  require a model: a forest with no binding still ingests, with derived
  summaries.
- **The report distinguishes a rejection from nothing to do (v0.45).**
  Curation statistics carry `skipped`: drafts the Curator returned
  untouched because there was nothing for a model to read an
  `unchanged` file it never saw, a draft with no body. A report where a
  model is **bound** and carries no evidence that it was ever asked
  anything no summary written, no rollup, no retry, no fallback, no
  transport error describes a batch that needed no model, and a console
  MUST say so rather than reporting a rejection. (A genuine rejection
  always leaves a fallback or a retry behind; that is what separates the
  two, and `skipped` says which drafts the Curator deliberately passed
  over.)
  The two have opposite fixes: one is a different model, prompt or token
  budget, and the other is nothing at all. Sending an operator to tune a
  model that was never asked anything is worse than saying nothing,
  because it looks like an answer.

- `compose` is `upload` with one authored document and a title instead of a
  filename. It exists because the alternative a console that plants a node
  directly would be a second write path with its own idea of what a
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
| stage | `{mode: "compose", title, text, dest?, stage: true}` | converts, curates, proposes and stops at the plant |
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
  re-checked against G.4.2.1 `rel: related-to` only, target existing and
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
amending the commit a write produced. An ingest produces many one per
node and amending would rewrite only the last while claiming the batch.
The Station therefore records the resulting commit **range** in the audit
log and returns it, rather than rewriting history it did not author.

#### J.8.2 Ingest roots (v0.26)

G.3 bounds what a walk may *reach* once a directory is named. J.8.2 bounds
which directories a **host** will open at all, because the two questions
have different answers: a person at a shell already holds the filesystem,
and a request arriving over HTTP does not.

A Station MUST hold a list of **ingest roots** absolute directories it is
willing to read on a caller's behalf configured out of band
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
  the operator holds that grant by construction which is exactly the
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
  they are outside this rule as is a targeted `sync` path, which is
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

### J.9 Ingest jobs (v0.32)

A batch ingest is minutes of work a converter pass, a model round trip
and a commit per document (Part G) and v0.31 ran all of it inside the
HTTP request that asked for it. Every gateway on the path has a patience
shorter than a folder, so the operator's answer was a timeout over a batch
that was still running: unwatchable, uncancellable, and indistinguishable
from a crash. J.9 gives the work an identity instead of a connection.

#### The job

`POST /v1/forests/{forest}/ingest` in a batch mode `adopt`, `sync`,
`upload` answers **202 Accepted**:

```json
{"job": {"id": "ing-8f3ka2", "forest": "handbook", "mode": "adopt",
         "state": "running", "done": 0, "total": 41, "current": null,
         "started": "2026-08-11T14:02:11Z"}}
```

- **`mode` is the caller's own word, on the job and on the report
  (v0.61).** It used to be rewritten mid-call: an upload whose staging
  root was already recorded became `mode: "sync"`, the mode that mirrors
  a host directory, on both. A caller that sent `upload` and read `sync`
  beside an `updated` list naming nodes it never mentioned had been told,
  by the only surface it has, that something it did not ask for had
  happened — in a product where every read declares what it did, the
  write report was the one place the answer contradicted the call. The
  first fix drafted for this added a second field to name the mechanism,
  which is a label for a mechanism that should not have existed: J.8's
  upload path is now one path, so there is one mode and it is the
  request's.
- **Refusal is still synchronous.** Capability, scope, `dest`, the ingest
  roots of J.8.2 and the staging of uploaded bytes are all checked before
  the 202, with exactly the v0.31 errors. A 202 for a request that was
  always going to fail validation teaches the caller to distrust 202; only
  work that has been *accepted* becomes a job.
- The job then advances one G.10 step at a time. `state` is one of
  `running`, `done`, `error`, `cancelled`; `done`/`total` count source
  files; `current` names the file being worked. A finished job carries the
  unabridged `IngestReport` as `report`, the commit range as
  `commit_before`/`commit` (the J.8 attribution rule unchanged), and
  `finished`. A failed one carries the spec error envelope as `error`,
  beside the report of what it did complete.
- **One batch per forest at a time.** A batch POST while one runs is
  refused `E_LOCKED` **naming the running job**, so the console can offer
  to show it instead. Queueing invisible work is how a forest gets a
  surprise second ingest an hour after somebody gave up and closed the
  tab.
- `wait: true` on the POST answers only when the job is finished, with the
  job in its final state for callers whose own patience is not a
  gateway's. The **MCP `ingest` tool waits by default**: an agent's poll
  loop would be context spent on plumbing, and its call is already the
  unit it wants an answer to.
- The audit row (J.4) is written when the job finishes, carrying the
  commit range and the job id the ingest is the fact being recorded,
  and it has not happened until it has.

#### Reading a job

`GET /v1/forests/{forest}/jobs` lists recent jobs, newest first, bounded,
`truncated: true` when the bound cut (the C.6 rule); `GET
/v1/forests/{forest}/jobs/{id}` returns one. Both require the `ingest`
capability the authority to watch the work is the authority that could
have asked for it.

- **Reading a job MUST NOT touch the forest.** A job is a record in the
  host's memory; a poll that queued behind the work it reports would be
  the v0.31 deadlock again, one level up. No forest thread, no trace
  event, no pheromone, no audit row: watching is free, in every ledger.
- **Job records are process state, bounded and honest about it.** They are
  never written into a forest progress is not curated content, the same
  boundary that keeps model runs in the browser (J.5.9). A restart
  therefore forgets the *records*; it cannot forget the *work*, because
  the work is commits. A job id the host no longer knows answers
  `E_NOT_FOUND` absence of the record is not failure of the work, and
  the forest's own account is the audit log and `git log`.
- **Recovery is `sync`, not archaeology.** G.10 records the source root
  before the first step, every step is committed, and the G.8 hash diff
  is idempotent so a batch interrupted by a crash, a cancel or a
  restart is *finished* by running `sync`, which re-reads nothing that
  already landed and plants nothing twice.

#### Cancelling

`POST /v1/forests/{forest}/jobs/{id}/cancel` asks the job to stop. It
takes effect at the next step boundary a document is whole or absent,
never half and the job reports `cancelled`, its report covering the
steps it took. The steps stand: they are commits, and un-planting nodes
is no primitive's job (C.7). A cancelled batch is completed later by
`sync`, or left as it is.

#### Isolation and fairness

Two rules the jobs machinery exists to serve, stated as contract because
they are observable and a future implementation must preserve them:

- **Isolation: a call on one forest MUST NOT wait on another forest's
  work.** The engine's thread-affinity discipline (C.6.1, J.6.1) was
  always per forest; serialising *across* forests was a host
  simplification, acknowledged as such, and v0.32 retires it. One lane
  per forest, opened lazily with the forest and closed with it a
  registry too large to hold every forest open (J.6.1) is equally too
  large to hold every lane, and the same switch governs both.
- **Fairness: between two steps of a running batch, calls to the same
  forest MUST get their turn.** The batch yields at every document
  (G.10), so a `locate` on a forest mid-ingest is answered within one
  document's work, not one folder's. The model round trip inside a step
  bounds the wait; the folder never does.
- **The batch owns the writer lane, and only that (v0.57).** With J.6.2,
  "calls to the same forest" splits: *reads* never enter the writer lane
  at all — during a step, curation model call included, every read of
  the forest proceeds on the reader pool. What queues between steps is
  the other *writes*, and that cost is correct: one batch per forest at
  a time was already the rule, and a plant that interleaves mid-batch
  waits one document, exactly as fairness always promised. Splitting the
  curation call out of the step is deliberately not done — G.10.1 stands
  (a step is a whole document), and the starvation the incident measured
  was the readers', which the pool ends.

#### J.9.1 The console follows the job

- **The address carries the job**: the ingest console puts the running
  job's id in the query (`?job=…`), replacing rather than pushing
  (J.5.8). A reload restores the progress view by reading the job a
  record, never a call: no model spend, no commit, no re-POST of the
  batch. Leaving the console open is watching; leaving it entirely is
  safe, because the job does not need its audience.
- **Progress is shown from the job record** `done`/`total`, the current
  file, errors so far and the console MUST NOT block navigation while a
  batch runs. Freeing the operator to look elsewhere is the reason jobs
  exist; a modal progress screen would rebuild the v0.31 experience out
  of politeness.
- **A dead job id is said, not dressed up**: an address naming a job the
  host has forgotten (restart, eviction) says so and points at the audit
  log, rather than inventing a state or silently clearing the query. The
  J.5.8 rule about forests that cannot be shown, one size smaller.
- **Returning rediscovers the running job (v0.36).** The query belongs to
  the console it is on (J.5.8), so moving to another console does not
  drag `?job=` along and coming back must not greet the operator with
  an empty form while their batch runs on. Entering the ingest console
  with no `?job=` MUST read the job list a record, never a call, free
  in every ledger and, finding one `running`, put its id in the
  address, replacing rather than pushing: a correction, not a place the
  operator went. A finished job is not adopted; its record is on the
  board and its story in the audit log.

#### J.9.2 The next batch waits in the console, never in the host (v0.36)

The host refuses to queue (J.9) because work waiting in a server after
its audience left becomes a surprise ingest an hour later. That reasoning
names the danger precisely: *invisible* work that *outlives* its asker.
Work that is on screen and dies with the tab is neither and the
operator standing in front of a running batch with the next folder in
hand was being told "come back later" by a disabled button. The console
may hold that wait for them:

- **The console MAY stage next batches while a job runs**, first in
  first out, and submit each as an ordinary batch POST when the running
  job settles. The host sees nothing new: every submission is a plain
  request racing every other client, refused `E_LOCKED` like any other
  if it loses. On that refusal the queue is not dropped the batch
  waits for the job the refusal names, and takes its turn at *that*
  job's settle.
- **The queue is tab memory.** It is shown where it waits; it is never
  in the address (work in progress is not a place the J.5.8 rule that
  already governs staged files); it is sent nowhere until its turn; and
  closing the tab abandons it, exactly as closing the tab abandons
  staged files. Nothing invisible remains anywhere, which is why this
  does not reopen the door J.9 closed.
- **Consent is per batch.** Each entry joins the queue by the same
  explicit act that would have submitted it, under a button that says it
  will wait rather than start. An entry can be taken out of the queue
  while it waits; removal destroys nothing but the waiting.
- **A cancel holds the queue.** The operator who stopped the running
  batch said stop, and auto-starting the next thing behind that word
  would be the console contradicting them. `done` and `error` release
  the next batch batches are independent, and one batch's bad day is
  not a verdict on the next but after a `cancelled` settle the queue
  waits for the operator, who starts it explicitly or takes it apart. A
  submission the host refuses (other than `E_LOCKED`) holds the queue
  the same way, with the refusal shown.

#### J.9.3 The batch is visible from every console (v0.37)

J.9.1 freed the operator from the batch; it did not tell them how it was
doing unless they came back. From every console of the forest, a running
batch and a waiting queue (J.9.2) is announced by a small indicator
that expands on demand into what the job record says: done over total,
the document in hand, errors so far, the queue behind it, the cancel,
and the way to the ingest console. Three rules:

- **The indicator reads the board, never a client copy.** The job board
  is the one memory of running work (J.9), and the console keeps no
  duplicate of it in browser storage: a stored id would go stale in both
  directions surviving the restart that forgot the record, and blind
  to the batch another principal started, which deserves the indicator
  just the same. Entering a forest asks the board once; everything after
  is the watch. Signing in again, on any machine, is therefore enough to
  find the batch: the memory was never in the browser.
- **The cadence follows the attention.** One watcher per forest serves
  every reader at the finest cadence any of them asks: collapsed, the
  indicator reads the board on the order of a minute; expanded or with
  the ingest console open on the order of seconds; a waiting queue
  sits between the two, at the pace settle detection needs. Watching is
  free in every ledger (J.9), but free is not a licence to be noisy.
- **The indicator yields.** On the ingest console the full progress card
  is already on screen, and a floating copy of it would be noise. And it
  is scoped like everything on screen (J.5.8): it shows the forest the
  address names, never activity from another one.

**F.36 (acceptance).** An `adopt` of a multi-file directory answers 202
with a job before the batch finishes; polling reaches `done` with
`done == total` and a report whose contents match what the same directory
yields under v0.31 semantics. While a batch with a deliberately slow
converter runs on forest A, a read primitive on forest B completes without
waiting for the batch, and a read on forest A completes within one step's
time, not the batch's. Polling a job adds no trace event and no pheromone
to the forest. A second batch POST on forest A while the job runs is
refused naming the running job's id. A cancel after *k* steps leaves
exactly *k* documents planted and committed with `state: "cancelled"`, and
a subsequent `sync` completes the remainder without duplicating any of the
*k* which requires, and thereby tests, that the source root was recorded
before the first step. `wait: true` returns the finished job in one
response. On a fresh Station instance the old job id answers `E_NOT_FOUND`
while the planted nodes and the audit row survive. All covered by tests.

### J.10 Per-forest inference

**Providers.** An operator registers named endpoints in the host registry:
a name, an OpenAI-compatible `/v1` base URL, and an optional key. Any
compatible gateway qualifies OpenRouter, LiteLLM, vLLM, a local
llama.cpp. Credentials are **write-only across every surface**: the API
accepts a key and reports only whether one is set (`has_key`), and an
update with an empty key MUST preserve the stored one **while the endpoint
is unchanged** so a provider can be re-saved without re-pasting a
secret. Changing the endpoint is a different destination and requires the
key again (J.3.2, v0.50). Who may perform any of this is J.3.2's table.

**J.10.1 Environment-declared providers.** A deployment that already sets
`MONKEYLLM_LLM_ENDPOINT` / `MONKEYLLM_EMBED_ENDPOINT` (with their optional
`…_PROVIDER` name and `…_API_KEY`) has stated a provider. The Station MUST
publish it at boot so no operator is asked to re-enter it, marked
`origin: "env"` to distinguish it from a row somebody typed.

Its key **MUST NOT be persisted in the registry**: it is held for the life
of the process and resolved when a call is made. The registry file is a
backup target and the environment is not; a deployment that chose the
environment for its secret MUST NOT have it copied elsewhere as a side
effect of starting the host. Write-only still holds `has_key` is the only
thing any surface reports.

Such a row is **read-only to the console**: an edit or a removal MUST be
refused, because the environment would reinstate it at the next restart and
the operator would meanwhile be looking at a configuration the deployment
does not have. Withdrawing the variables is the way to remove it; at the
next boot the row becomes an ordinary console provider keyless, visibly
so rather than being deleted, which would silently take its bindings with
it.

**J.10.2 A named destination is validated before it is contacted
(normative, v0.50).** The connection test lets a caller name an address the
Station then opens a connection to, from wherever the Station sits. The
address MUST therefore be checked before the call:

- `http` or `https` only;
- the host name MUST be resolved and **every** address it maps to judged.
  Inspecting the URL text would decide on what the address says rather than
  on where it goes;
- loopback, link-local, private, reserved, multicast and unspecified
  addresses are refused with `E_SCHEMA`, **unless**
  `MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE` is set truthy.

That variable is not a corner case: a local llama.cpp or Ollama lives on
loopback, which is the ordinary development posture of this project (see
`docs/local-inference.md`). It is off by default all the same, because the
deployment that most needs the boundary is the one whose operator never
read this paragraph, and turning it on is one line for the deployment that
knows it needs it.

**Model discovery.** A provider already publishes what it serves, at
`/models`. The console MUST offer that catalogue when choosing a model —
with the per-token prices when the provider states them rather than
asking an operator to type an identifier. Typing invites the failure this
rule exists to prevent: a model name from one provider bound to another,
which is well-formed, accepted, and wrong until the first call fails.

Discovery is a convenience, never a constraint: a model the endpoint does
not advertise MUST remain bindable, because gateways under-report and a
console that refuses an unlisted name would be less capable than the API
beneath it.

**Role bindings.** A binding maps `(forest, role) → (provider, model,
max_tokens, reasoning)` with `role ∈ {ingest, answer, vision}`:

| Role | Used by | What to optimise for |
|---|---|---|
| `ingest` | curation at adopt/sync, `curate` | care: its output is the scent every later hop navigates by |
| `answer` | `answer` | speed and instruction-following over already-retrieved material |
| `vision` | the G.5.1 describer at adopt/sync | fidelity: it reads slides, diagrams and screenshots so `sniff` can |

A binding MUST be refused if the provider or the role is unknown, and
removing a provider MUST remove the bindings that pointed at it a
dangling binding would fail at the worst possible moment.

**The default budget (v0.63).** A binding created without a stated
`max_tokens` carries **1500**, and so does a call that finds neither a
`reply_tokens` nor a binding budget. The number is sized for the `answer`
role, the one whose reply carries the citation apparatus and not only prose.
`ingest` writes a scent and `vision` writes a description, and both keep the
smaller budget they were sized for; the curator's own default is a different
client with a different job and is unaffected.

**Repairing a shipped default (v0.63).** A default is the value for rows
nobody has written, so raising one reaches no deployment that already has
bindings. A host MAY therefore carry **data repairs**: ordered statements
applied to a registry once and recorded against it, so that a value an
operator chooses afterwards is never overwritten by the repair that moved it.
The repair raising `answer` off the shipped 600 MUST NOT move a binding at any
other value, MUST NOT touch another role, and MUST NOT run twice. A registry
created fresh is stamped current and applies none of them.

### J.10.3 Model-backed composites

Two host composites, neither a primitive (the engine gains nothing):

- **`answer(question, k, terms?)`** runs the scoped `harvest`, hands the
  result to the forest's `answer` model, and returns `{answer, model,
  model_ms, evidence, harvest, trace}` (J.10.4). Requires the `read`
  capability.
- **`curate(id)`** re-summarises one node through the `ingest` model
  under the A.4 scent rules (validate-and-retry), returning the proposed
  summary rather than writing it. Requires the `write` capability, because
  it spends the operator's tokens.

**The invariant that makes binding a model safe:** retrieval runs through
`ScopedVine` *before* any model is called, so the model receives only
material the principal could already have read primitive by primitive.
Binding a model MUST NOT widen what a principal can see; if a composite
ever needs data outside the caller's scope, that is a specification
question, not an implementation shortcut.

**The material is a sample, and the prompt MUST say so (v0.67).** The sweep
hands the model a ranked top-`k` from a corpus of any size and instructs it
to answer strictly from that material. The instruction is right and the
omission beside it is not: nothing in the prompt says the material is a
selection. `searched` rides the **empty** path only, by C.1.1's rule, and
that rule stands — a caller holding results was already told what it needed —
so a non-empty bundle carries no denominator anywhere, and five items out of
twelve hundred are presented in the exact shape twelve hundred out of twelve
hundred would take.

The consequence is not an occasional error, it is a licence. Asked what a
forest is about, a model handed five excerpts and told they are "the forest
material" answers about those five and is **obeying the prompt** — the
answer is faithful, cited, traced and wrong about its subject, which is the
failure C.17 was written for. So the sweep's prompt MUST state that the
material is a ranked top-`k` retrieval drawn from a larger corpus and MUST
NOT present it as the corpus itself; a question the material cannot support
is refused or answered as a partial reading, never generalised. Wording is
implementation freedom; stating the fact is not. This is J.10.8's rule about
the reply cap applied to the sample size, and for the same reason: a
constraint the model is not told about can only be discovered by being hit,
and here being hit is silent.

**`terms` (v0.67), on the sweep only.** `answer` accepts an optional list of
literal `terms`, forwarded to the C.6c `harvest` as its `sniff` terms
exactly as `harvest`'s own parameter takes them — the same shapes accepted,
the same validation, and garbage refused as `E_SCHEMA` in the same words.
Absent, the sweep derives them from the question as it always has.

- **It is the caller's retrieval, authored where a model already sits.**
  C.6c is normatively zero-LLM and stays so; J.10.11's phases stay in order
  and J.10.10's floor stays before the model. Nothing here puts a planning
  turn in front of the retrieval. What it does is open the seam this
  document has described since v0.33 and never offered: J.10.7's key names
  the effective terms "whether the caller supplied them or the sweep derived
  them", and until now no hosted surface could supply them, so the first
  half of that clause was a description of nothing. A client holding a model
  — an MCP agent, a console affordance — can translate a question into the
  corpus's own vocabulary and hand over the result.
- **With `hops`, it is `E_SCHEMA`.** A walk authors its own retrieval from
  hop 1 (J.10.5) and takes no term list; accepting one and dropping it would
  be a lie about what ran, which is C.13 rule 4's judgement about a silently
  ignored window applied to a silently ignored parameter.
- **It enters the J.10.7 key as the effective terms**, which is where that
  key already put them. A call that sends none keys exactly as it did before
  this version and its response is byte-identical, so no store is
  invalidated by the upgrade.

*Known boundary (informative):* `answer` reads text. Facts that live only
inside a `type:dataset` payload are reached with `query`, so a question
whose answer is an aggregate over rows will be honestly refused rather
than guessed unless the model is given the primitives and allowed to run
`query` itself, which is J.10.5.

### J.10.5 The answer that navigates

`answer`'s default is a sweep: `harvest`, one model call, done. Cheap,
predictable and blind to anything not reachable from the entry list. It
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
  `sniff`, `look`, `move`, `pick`, `scan`, `query`, `coverage` (v0.67) and
  nothing else. The policy would already refuse a write to a principal
  without the capability but a principal who *has* `write` asked a
  question, and a loop that could `plant` would turn a question into an
  edit.

  **`coverage` is on the list because of what it answers (v0.67).** A
  question about the forest itself — what is here, what is this collection
  about, is there anything on X at all — is not a point lookup and is not
  answered by ranking documents against it. C.17 is the map's own read: the
  roots, their sizes, their sources, what is missing, so a silence can be
  told from an absence. It was the one primitive built for that question
  class and the closed list was barring it from the one mode that could
  decide to call it, which left a walk with no move but to read one document
  and describe the corpus from it. Nothing widens: `coverage` reads curated
  metadata and counts, it opens no body (C.17 rule 1), and every number in
  it is the calling policy's own (C.17 rule 7) — the walk is a client with
  no privileges of its own here as everywhere. The menu the loop offers the
  model MUST name it, because a tool a model is never told about is a tool
  the whitelist did not admit.
- **Every call goes through `ScopedVine`**, exactly as a client's would.
  The loop is a client with no privileges of its own; J.10.3's invariant is
  unchanged, not re-argued.
- **A spent budget still answers.** Running out MUST force one closing turn
  over what was already read, rather than discarding the hunt the tokens
  are spent either way.
- **Evidence is what was opened.** Cited ids that the loop never read MUST
  NOT be returned as evidence: that is a claim about the forest rather than
  a reading of it.
- **The entry carries what a dataset teaches (v0.47).** The loop's first
  message is the entry `locate`, which is curated metadata: no body, no
  manual, no notes. C.2.1 rule 6 governs it like any other material a host
  assembles every `type: dataset` in that entry list MUST arrive with its
  `notes`. Without this the walk is the one path where an operator's
  instructions depend on the model deciding to `look` first, and on a
  dataset the natural next move is `query`.
- **A refusal reports what it was, not only that it was (v0.47).** The
  loop already returns the whole error envelope to the *model* that is
  how it corrects itself, and it MUST keep doing so. What it reported to
  the *console* was the code alone, so two different mistakes (a guessed
  table name, then a guessed column name) rendered as the same word twice,
  and the reader could not tell that the engine had answered both with the
  C.5 hint. A hop's outcome MUST therefore carry the error's message,
  clipped like its other string fields. Nothing new is disclosed: the
  message is the engine's own reply to a statement the caller wrote,
  against a node already inside the scope.

The response carries `hops` alongside the `trace` of J.10.4, so the path and
its cost are both visible. A hop MUST report more than its tool name: the
arguments the model chose, one number for what came back (results, rows,
tokens, or the refusal code), and **two clocks** the forest call and the
model turn that decided to make it. "sniff, sniff, locate" and "sniff → 0,
sniff → 0, locate → 5" are the same list of verbs and opposite stories, and
one combined duration would hide which half a slow hunt is spending.

The arguments appear here and **not** in the `trace`, deliberately: the
trace is the technical record and reports shape only (J.10.4), while a hop's
arguments are the model's own choices, derived from the caller's own
question, over results the scope already filtered.

**A hop that returned a set names the set (v0.67).** One number is enough to
tell "sniff → 0" from "sniff → 5" and it is not enough to say *which five*.
For the tools whose result is a listed or ranked set — `locate`, `sniff`,
`scan`, `move` — the hop record MUST therefore also carry `ids`: the ids of
the items that call returned, **in result order**, capped at 10. *Also* is
load-bearing: `scan` and `move` are addressed by an id and already record
it, and they keep it, because the two fields answer two questions — where
the call went, and what it brought back. Tools that return no set (`look`,
`pick`, `query`) keep the `id` they already carry and gain nothing; a hop
that named none of either carries neither field.

The reason is J.10.12. That section's rule 2 makes an event a prefix of the
response — `hop` **is** `hops[n]`, which is what F.138 compares — so a
spectator watching a walk arrive can light only what the record names, and a
count lights no node. Without this a live walk shows its `pick`s and its
`query`s and draws nothing at all for the two tools it does most, which is
indistinguishable on a console from a walk that found nothing. The cap of 10
is the same judgement every other clipped field in this section makes: the
record is a report on a hunt, not a second copy of its results, and the
budget belongs to the reply. Nothing is disclosed that was not: these are
ids the same call already returned to the same principal, through a scope
that filtered them before the model saw them.

**A record written before this version has no `ids`, and a consumer MUST
treat the absent field as empty** — never as "the call returned nothing",
and never inferred from `out`, the arguments, or anything else. A stored
walk (J.10.7) outlives the version that wrote it, so the absent field will
be read for as long as those entries live.

Steps in the `trace` that a hop caused SHOULD carry that hop's number, so a
console can show a timing and the decision behind it in one place. The entry
`locate` is not a hop the forager did not choose it.

**Two things the loop's prompt MUST say (v0.67).** How a prompt is worded is
implementation freedom and stays so — the prompt is not on J.10.7's closed
key list and a walk's entries die with HEAD — but *what it may leave out* is
not, for the reason J.10.8 gave when it required the reply cap to be stated
whatever chose it: a constraint a model can only discover by hitting it is a
constraint the model was never given.

1. **The entry was not the model's retrieval.** The prompt MUST tell the
   model that its first message is a synthetic `locate` of the question
   **verbatim**, chosen by no one. The loop labels that result with the
   question, which reads as a retrieval somebody meant; in fact nobody
   translated the question into the corpus's language, nobody chose a rarer
   term, and for a question asked in a language the corpus is not written in
   the entry can be pure noise. Re-authoring retrieval — a second `locate`
   with the model's own terms, a `sniff` for the word the corpus would
   actually use — is the walk's own move, available from hop 1, and it must
   read as a first move rather than as a repetition of work already done.
2. **A question about the corpus is answered from structure.** The prompt
   MUST name that question class — what is this forest about, what does it
   hold, is there anything here on X — and MUST route it toward structure
   rather than toward a document: `coverage`, the root `_index`, and more
   than one branch. **A single document is one node's claim and is never the
   corpus**, however confidently it describes it; a readme is a document
   about a forest exactly as an entry in the forest is. This is C.17's own
   motivating story arriving one surface later, and the whitelist above is
   what makes the instruction executable.

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
say which of them to fix. The usual suspicion "the forest is slow" is
almost always wrong, and there is no way to find that out from a total.

Calls that are several calls (`answer`, `harvest`) MUST therefore return a
`trace`: the ordered steps the call performed, each with its primitive, its
elapsed milliseconds, the tokens it emitted and only for primitives that
take one the node id; plus `retrieval_ms`, `total_ms`, and the provider
round trip as a `model` step. Consoles that answer questions MUST show it.

The engine already times every primitive it runs (Part D), so this is a
slice of that trace and not a second instrumentation: the events the call
appended, and nothing else.

**The embedder is a provider, not a primitive (v0.68).** A step whose
Part D event carries `embed_ms` reports it, and the trace carries
`embed_ms` — the sum across its steps — present only when nonzero.
`retrieval_ms` is unchanged: it accounts the engine span as ever, embed
included, so no shipped number is redefined. A console that leads with the
engine figure (J.10.6) MUST NOT present the embedder's round trip as the
forest's: where `embed_ms` is nonzero, every step and the forest figure
are shown net of their share, and the summed share is listed once at the
tail beside the `model` step, in the model's own tone — provider spend
sits with provider spend, and every primitive row is the engine's own
smallest true number. The netting is the console's; the host serves the
whole span and the named share, never a subtracted figure.

**A trace reports shape, never content.** No arguments, no queries, no
snippets a step names what ran and what it cost. Node ids appear only for
primitives the caller's own policy already admitted, since scoping happens
before the call the trace is describing; a trace therefore cannot disclose
what a scoped response withheld.

**What it cost, when the provider says so.** A composite that calls a model
MUST report the tokens the provider itself metered (`usage`) and, when that
provider publishes rates, the money: `cost: {prompt_tokens,
completion_tokens, calls, priced, usd}`. Two rules make it trustworthy.
Counting tokens locally is an estimate of somebody else's meter and MUST
NOT be substituted for it. And a provider that publishes no rate a local
Ollama, a llama.cpp MUST be reported as **unpriced**, never as free:
`priced: false` with no `usd`, because rendering silence as $0.00 is a
claim about money made from the absence of one.

### J.10.6 The host's own clocks

J.10.4 explains a composite because a composite is several calls. A single
primitive is one call, and the reasoning was that it therefore needs no
explaining: whoever invoked it can time it. That holds for a library caller
and fails for an HTTP one. Over the wire the caller's stopwatch measures
TLS, the network, HTTP framing, JSON and its own render, and the engine's
`elapsed_ms` never leaves the process so a REST client cannot tell 0.2 ms
of `locate` behind 28 ms of internet from 28 ms of `locate`. Those are
opposite facts about the product and they look identical from outside.

**Every primitive response MUST carry `Server-Timing`.** Three metrics, in
milliseconds:

- `vine` the engine, the sum of the tracer events this call appended.
  Present on every response, `0` when the call reached no primitive.
- `host` the host's own share: policy, the audit record, serialisation,
  the forest-thread hop. What is left of the host's span after the other
  two.
- `model` the provider round trip, present only when one happened
  (J.10.3, J.10.5).
- `cache` the answer store's own work: the lookup and the
  reading-fingerprint check, plus, on a walk hit, the heat deposit
  (J.10.7). Present only when the store was consulted. On a hit `model`
  is absent, because no provider ran a header claiming one did would be
  the forged number this section exists to prevent.

The clocks present MUST account for the host's whole span, so a caller that
subtracts them from its own stopwatch is left with transport and nothing
else.

**A header, not a field.** A response body is the agent's context window
and it is budgeted in tokens (C.6). Diagnostics for a human console MUST
NOT be added to it: no agent reads them and every agent would pay for them,
and a number appended after the budget was enforced would break the budget
it was appended to. `Server-Timing` is carried by the transport, costs the
body nothing, and is already rendered by every browser's network panel.
The MCP surface (J.4) has no headers and reports nothing extra; that is
correct, because its caller is the agent, not the console.

**A timing MUST NOT disclose what a scoped response withheld.** Like a
trace (J.10.4), it reports shape only three durations, no ids, no
arguments, no counts. It rides on every response the primitive route
produces past authentication, refusals included: a route that timed only
its successes would answer "which forests exist?" by staying silent. An
unauthenticated request never reaches a forest and carries nothing.

**Consoles report the engine, and transport is not the subject.** A surface
that shows the latency of a call MUST show the engine's own figure as the
primary number, and MUST NOT present a client-side round trip as the cost
of the call. What a reader is there to judge is retrieval: how long this
engine takes to find something in a corpus. The rest of the span is their
network and whatever host they pointed at a measurement of somebody's
infrastructure, and giving it equal weight reports the wrong subject.

Transport MUST NOT be hidden either, and the reason is not symmetry. A
console that shows 0.2 ms for a click that plainly took longer is making a
claim the reader cannot reconcile, and an unreconcilable number is read as
marketing. So it is stated once, plainly, and named as infrastructure
rather than as the call.

**The engine figure MAY be given a unit a reader feels.** Every forest call
is serialised onto one worker thread (J.0), so the inverse of the engine's
own time is not a projection: it is the rate that deployment sustains on
that corpus, back to back. A surface that reports it MUST derive it from
the engine clock alone and MUST NOT report it for a call in which a
provider ran the rate of an `answer` is the model's, not the forest's.

**F.32 (acceptance).** Every served primitive MUST answer with a
`Server-Timing` header carrying `vine` and `host`; `answer` MUST also carry
`model` when a provider ran a hit of J.10.7's store carries `cache`
instead and the clocks present MUST sum to no more than the host's measured span
for the request. A response body MUST be byte-identical to the same call
made before this section existed the header is the only difference and
the token budget of every primitive MUST be unchanged. The Playground MUST
lead with the engine figure, MUST NOT lead with a round trip, and MUST
still account for the remainder of the span somewhere on the panel.
Covered by tests.

### J.10.7 The answer already given (v0.33; the reading check, v0.35)

`answer` is the one call in this host that costs real money and real
seconds; everything beneath it is a fraction of a millisecond, which is the
fact J.10.6 exists to make visible. A deployment in front of traffic is
asked the same questions over and over, and until now every repetition
bought a fresh provider round trip over the same material. The retrieval
was already too cheap to be worth saving; the model call is the entire
bill, and the store exists to stop paying it twice.

**The store fronts the model, and nothing else.** Primitives are never
cached: they are the cheap half, and their contracts budgets, truncation,
scoping are per call by design. `harvest` is zero-LLM and needs no
saving the sweep runs its retrieval on **every** ask, hit or miss,
because the retrieval's result is what decides a hit (below). `curate` is
never served from a store, because its purpose is a fresh reading.
Wherever `answer` is served, the store sits between the retrieval and the
provider. Per forest it can be switched off; it is **on by default with a
stated bound**, because the check below makes a stale hit structurally
impossible and the labelling below makes every hit visible.

**The key is a closed list, and everything that shapes the call is on
it.** An entry is named by the digest of, exactly:

1. the question, normalised for nothing but writing: Unicode-normalised,
   trimmed, inner whitespace collapsed, case-folded;
2. the **effective terms** the ones the call actually used, whether the
   caller supplied them or the sweep derived them. Since v0.67 both halves
   of that sentence describe a path a caller can take: `answer` accepts
   `terms` on the sweep (J.10.3), so a supplied list keys as itself and an
   absent one keys as the derived list, which is exactly the digest a call
   before this version produced. Nothing else changes here — a caller who
   sends no `terms` is a stranger to nothing and every existing entry
   survives;
3. the **effective `k`** capped by C.6c for the sweep, because the cap
   shapes the answer and so must name it; as given for the walk, which
   C.6c does not cap the hops budget when the walk was on (J.10.5),
   and the entry-search mode (K.3) a hybrid entry retrieves
   differently, so it answers differently;
4. the **binding as resolved** provider, model, `max_tokens`,
   `reasoning`. A rebound model is a different answerer, so it is a
   different key. And the caller's **`reply_tokens`, when one was set**
   (J.10.8, v0.48), as clamped: a short answer and a long answer to one
   question are two different answers, and a call that set none keys
   exactly as before, so an upgrade invalidates nothing;
5. the caller's **scope** allow, deny and table grants as enforced
   (J.3). Two principals under one scope are asking one forest; under
   different scopes they are asking different forests that happen to share
   a directory. An entry MUST be shared across principals whose scope is
   identical and MUST NOT be served across scopes: J.10.3's invariant
   survives the store by construction, not by a check;
6. the forest's **HEAD** **for the walk only** (J.10.5, v0.35). A walk
   cannot be re-walked without paying the model per hop, so its entries
   stay pinned to the exact forest that produced them. The sweep's key
   carries no HEAD: its freshness is decided by the reading, below.

Two calls that differ anywhere on the list are strangers to the store.
Nothing off the list may enter the key, because every extra component is a
hit rate halved for no correctness bought.

**The reading is the freshness check (v0.35).** Two digests with two
jobs. The key above finds the entry; a second digest the **reading
fingerprint**, stored with it decides whether the model owes a fresh
pass. The sweep fingerprints what it would hand the model: the set of
results keyed by id, each contributing its type, title, summary, matches,
body content and `notes` when it carries them (v0.48 the teaching is
handed to the model, so a teaching edited is a reading changed), its
`created`/`updated` dates and its `supersedes`/`superseded_by`
annotations (v0.57, C.6c.3 — the material's stated time is handed to the
model, so material re-dated or re-ordered is material re-read), plus the
bundle's truncation flag and nothing
volatile: not score, not heat, not the serving order. Pheromone drifts on
every use and reorders near-ties (Part D); the order is the ranking's
affair, not the body's, and a store invalidated by its own hits would
never hold an entry. A result that enters or leaves the set is a change
of reading; a set that merely reshuffled is not. Equal fingerprints mean the model
would be handed the same reading it already answered, so the stored reply
is served; different means the forest changed under this question there
may be new information, so the model runs on the new reading and the
entry is replaced. The check is exact where HEAD was indiscriminate: a
`graft` on a node the question reads is a miss; a `plant` in a branch the
question never touches invalidates nothing; a `tend` that changes rows
but not prose changes no reading. Heat that pushes a result out of the
set or a new one in changes the reading and is honestly a miss; the
worst case is a bought run, never a stale answer. For the walk, HEAD in the key remains
the clock: every commit invalidates it, exactly as v0.33 stated.
Evaporation (H.1) commits nothing and, by itself, still invalidates
nothing. A TTL exists as hygiene space, never correctness.

**Nothing empty and nothing broken enters the store.** A miss stores its
run only when the run was worth its key:

- a run whose retrieval found **nothing** an empty entry list, a walk
  that opened no node, evidence of zero MUST NOT be stored. An empty
  answer is the least useful response this product can give, and the store
  MUST NOT make it the fastest;
- an errored call, a refusal, or a response marked truncated MUST NOT be
  stored;
- a turn that performed any write MUST NOT be stored. The loop already
  cannot write (J.10.5); this rule survives any future surface that can.

**A hit is a record served over a live reading, and it says which is
which.** The retrieval fields of a sweep hit `harvest`, `evidence`,
`sources`, the trace are this call's own, fresh from the sweep that
just ran. The model fields `answer`, `model`, `usage`, `cost` are the
record, returned as bought, with `cached: true` and the time of the
original run (J.5.9's distinction one level down). The original cost MUST
NOT be counted a second time as spend, and no `model` clock or trace step
may claim a provider ran. A walk hit is still served whole, as received
(v0.33). Either way a console MUST label the answer as served from the
store, and the host's log states the hit with the entry's digest.

**The whisper is the composite's close (v0.35).** Part D ends a
successful hunt with heat on the winning trail, and a hosted `answer` is
a hunt whether the reply was bought or served v0.33 whispered only on
hits, which told the Ranger that a question answered from the store
mattered and the same question freshly bought did not. The host MUST
deposit the whisper on the answer's evidence hit and miss alike,
through the trails store, the same channel the engine's own session close
uses, never a primitive so the nodes behind a deployment's most-asked
questions read to the Ranger as exactly as hot as they are (H.2). A sweep
hit additionally holds the tracer events of its own retrieval, because
that retrieval really ran; a walk hit appends none, because nothing ran —
its stored trail is what the whisper lands on.

**It lives in the disposable layer.** The store is per forest, in
`_derived/` beside the catalog and the trails, WAL like the rest (J.6.1),
out of git like every non-`.md` (A.3.1). It is never a source of truth: a
snapshot does not package it (Part I), `reindex` owes it nothing, and
deleting it costs money the answers are bought again but never truth.

**The bound is stated out loud.** The store is finite, per forest, and
says so: a stated cap, oldest-served-first eviction, and a surface that
shows what is held against the bound. Silent unbounded growth is C.6's sin
in yet another costume.

**Asking past the store is one flag, and it refreshes.** A call carrying
`cache: false` MUST skip the serve the sweep's retrieval runs
regardless run the model on the fresh reading, and **replace** the
entry its key names. That is the with-and-without comparison made honest —
J.5.9 exists to read such pairs side by side and it is the operator's
way to force a fresh draw of one answer without emptying anything.

**The console states the store's economy.** Per forest: hits, misses, what
is held against the bound, and the money not spent computed only over
runs whose provider priced them. J.10.4's rule holds in mirror: an
unpriced run's saving is unpriced, never $0.00. The settings on or off,
the bound, the hygiene TTL, the similarity threshold where it applies —
are the operator's, per forest, behind `admin`; emptying the store is
offered there, and costs truth nothing.

**The near question, only where the forest has ears for it.** Exact keys
answer exact repetition, and real traffic rephrases. Where and only
where a Canopy index and an embedder are both present (the same
conjunction that makes `locate` hybrid), the store MAY also hold an
embedding of each entry's question and serve an entry whose stored
question clears an operator-set similarity threshold with **every other
component of the key still matching exactly** (scope, binding, `k`, hops)
**and the reading fingerprint still deciding**: a neighbour whose stored
reading no longer matches this sweep's is not served, however close the
question. The question and the terms derived from it are what similarity
stands in for; terms the caller supplied are a precision instrument, and a
call that carries them MUST NOT be answered by a neighbour. The tier is
**off by default** the exact tier has no false positives and the near
tier trades some for hit rate, which is the operator's trade to make and
a neighbour served MUST name the stored question it answered, because the
reader can judge the stand-in only when shown it.

**F.37 (acceptance).** The same question asked twice on an unchanged
forest makes one provider call: the second response carries `cached:
true`, the original run's answer, fresh retrieval fields, a
`Server-Timing` with `cache` and no `model`, an audit row marked as
served from the store and the second sweep's primitives really ran:
tracer events appended, and the whisper deposited on the evidence, as it
also is on a miss. A `plant`
of material foreign to the question between the two asks is **still one
provider call**; a `graft` that edits a node in the question's reading
makes it two. A change to any of: terms, the effective `k`, hops,
binding, or scope is a miss. A run with empty evidence, asked twice, is
two provider calls and no entry. `cache: false` answers fresh and
replaces the entry. The store never exceeds its stated bound and evicts
oldest-served-first. An entry stored under one scope is never served to
another. A walk answer is keyed with HEAD, and any commit invalidates it.
With the near tier off, a rephrased question is a miss; with it on, a
neighbour served names the stored question it answered. Covered by
tests.

**F.38 (acceptance).** With `MONKEYLLM_HARVEST_MAX_K` unset, a `harvest`
asking `k: 50` returns at most 5 results the default is the old cap,
byte for byte. Set to a smaller integer, the smaller integer wins; the
response budget still holds and truncation is still explicit. Set to `0`
or to text, `harvest` answers `E_SCHEMA` naming the variable. On the
host, two sweeps asking `k: 10` and `k: 50` under a cap of 5 form one
store key and the second is served from the store; the same two calls
with the walk on (J.10.5) form two keys, because the walk's `k` is not
capped. Covered by tests.

**Identical questions in flight share one generation (v0.58).** The old
single lane had an accidental virtue: identical misses queued, and every
one behind the first hit the entry the first had just stored. J.10.11's
parallel phase 2 un-made it — ten identical cold asks became ten paid
generations racing to replace one entry. Deliberately now: concurrent
sweep misses with the SAME store key **coalesce**. The first becomes the
leader and runs phases 2–3 as ever; followers await it on the loop (no
lane held), then **re-consult the store under their own reading
fingerprint** — a follower whose reading matches the leader's is served
the stored reply (`cached: true`, which is the plain truth of what
happened), and one whose reading differs runs its own model call,
exactly as the reading check always ruled. The in-flight table lives in
host memory, keyed by (forest, store key), and empties itself: a leader
that errors or declines to store releases its followers to their own
calls — coalescing is an optimisation over the store, never a second
source of truth. `cache: false` opts out of coalescing along with
everything else, and a disabled store coalesces nothing.

### J.10.8 The reply has a stated size (v0.48)

The one control over how much an answer says was the binding's
`max_tokens` (J.10): per forest, set by the operator, and enforced only
as a hard cut a model that overran it stopped mid-sentence. The person
asking has the opposite need per question: a one-line confirmation now,
a thorough reading across documents later. That is a per-call choice,
not a per-forest configuration.

`answer` therefore accepts **`reply_tokens`**, walk and sweep alike:

- **Clamped to [64, 4000]**, the upper bound being the project's
  familiar "one reading" budget (`pick`, `harvest`). Absent means the
  binding's `max_tokens` rules exactly as before the parameter is an
  override, never a new default.
- **The cap is also said (amended v0.63).** The effective value replaces
  `max_tokens` on the model call AND is stated in the prompt, so the model
  shapes the reply to fit rather than being truncated by it, and this holds
  whatever chose that value: the caller's `reply_tokens`, the binding, or the
  default when neither did. It used to be said only **when set**, which left
  the prompt silent in exactly the case where nobody had chosen a number and
  the shipped default was deciding alone, and a deployment that never touches
  the parameter is the one that most needs the warning. What is stated is the
  cap, never a parameter the caller did not send: a call carrying no
  `reply_tokens` still reports none. On a walk it bounds every turn and the
  note aims at the final answer, which is the turn it exists for. This
  section used to call a tool call "far under the floor", which is true of a
  navigating turn and false of the one that answers: that turn is an object
  carrying the text AND `answer_nodes`, and it is the turn a low cap cuts.
- **The cut is reported (v0.54).** This section used to claim a
  provider's cut carries no flag; for the OpenAI-compatible surface this
  host speaks, that was wrong — `finish_reason` is in every response,
  and it is now read. A reply the provider stopped for length carries
  `truncated: true` and its `finish_reason`; a reply that finished
  carries neither. A truncated reply MUST NOT enter the J.10.7 store:
  `storable` always refused truncated results, but nothing ever set the
  flag, so cut-off answers were bought once and served forever. This was
  the one place in the product where a caller paid and could not tell
  whether it received everything.
- **The clamp is reported (v0.54).** The response echoes the effective
  `reply_tokens` whenever one was set. `reply_tokens: 40` is served by
  the floor, 64 — a fact the caller could previously learn only by
  noticing that `completion` exceeded the request, which reads as an
  overrun rather than a clamp.
- **It joins the key when set** (J.10.7): the effective, clamped value —
  two calls that differ only in reply size are asking for two different
  answers. A call that set none contributes nothing to the key, so
  existing stores survive the upgrade untouched.
- The binding's `reasoning` bump is applied after the override, for the
  same reason it exists at all: thinking tokens must not eat the reply.

**The console offers it as a control, and keeps it as a preference.**
A slider beside the ask box, defaulting to the binding's own size
("auto"), persisted client-side per person J.5.3's class of choice
(like language and theme), never in the address: the address restores
a page (J.5.8), and how long someone likes their answers is theirs, not
the page's.

**F.51 (acceptance).** An `answer` carrying `reply_tokens` makes the
provider call with that value as `max_tokens` (clamped to [64, 4000])
and the prompt states it; absent, the binding's value rules byte-for-
byte as before. Two sweeps differing only in `reply_tokens` are two
store entries; a call without it forms the same key as before the
upgrade. The MCP `answer` tool accepts it. Covered by tests.

### J.10.9 The answer that shows what it read (v0.48)

A media node's body is a describer's prose about pixels (G.5.1). The
J.14 route lets a console show the image beside the node but the
*answer* is where a person actually meets the forest, and an answer
built on a screenshot was text about an image nobody was shown: the
model had read the description, used it, and had no way to hand the
reader the thing itself.

The model may now **embed a media node's image in its reply**, by
reference:

- The syntax is a markdown image whose address is the `media:` scheme
  followed by the node id `![<caption>](media:<node id>)` stated to
  the model in the answer prompts whenever its material contains a
  `media` node, with the rule that only ids present in the material may
  be named. It is a *reference*: the host neither fetches, inlines nor
  rewrites anything, and the reply stays plain markdown storable in
  the answer store (J.10.7) unchanged, because a node id is stable
  where a URL is not.
- **The console resolves it through J.14**, the route where scope is
  already enforced: a `media:` reference is fetched with the viewer's
  own credential, so an id the model invented or one the *viewer*
  may not read resolves `E_NOT_FOUND` and MUST render as its caption
  and nothing else, never as an error that outranks the answer. Bytes
  still never ride in the response body; G.5's line is untouched.
- **Evidence shows its image.** An evidence item of type `media` MUST
  be rendered with its image beside its scent (J.14's console rule,
  made specific): whether or not the model chose to embed it, "what was
  this answer built from" includes the pixels.
- **Exports carry what the reader saw.** A PDF export includes the
  rendered images; a markdown export rewrites `media:` references to
  the absolute J.14 route, so the file names a fetchable address
  rather than a scheme only this console understands.

*(Informative.)* The embed rule rides in the prompt per call, so it
reaches every binding without retraining; a model that never embeds
loses nothing evidence rendering does not depend on it.

**A citation carries the title (v0.54).** The prompt teaches the closing
citations as `Title [id]`, not the bare id: `sources` always carried the
title, but the *reply text* is what a person reads, forwards and pastes,
and `[chatgpt--chatgpt-com-202608200332]` tells that person nothing. The
id stays in the bracket — it is what a console or a harness resolves —
and the title is what makes the line prose. A renderer keeps needing no
lookup, because the model writes both from material it already holds.

**A citation carries its scope (v0.59).** `sources[]` is the block a
console renders and an agent summarises — and it carried `id`, `title`,
`summary` and `type` while the `harvest` sitting beside it carried each
item's `trail`. The field designed to be read was the one that lost the
material's place in the forest. A multi-product forest is the normal
case, not the exception: a consumer forest held the product, a second
product, a billing platform and this repository side by side, and an
answer about the wrong one of them cited a real document, correctly, and
was wrong about the subject anyway. With the trail in the citation that
answer reads as *"according to `findleads/back-end`…"* and the mismatch
is visible before a word of the reply is trusted. `sources[]` therefore
carries `trail` — the same list `harvest` computed, never a second
lookup, and absent rather than invented when a hop produced a node with
no trail in hand. This binds both shapes: the sweep's sources (J.10.4)
and the walk's, which assembles the same block hop by hop (J.10.5).

#### J.10.10 The answer it should not give (v0.52)

`answer` always answers. When the sweep comes back with two weak snippets,
the model still writes a paragraph, and the response still dresses it in
`sources`, `evidence` and `usage` — so a synthesis built on almost nothing
is, to the reader, indistinguishable from one built on the document that
settles the question. That is hallucination arriving with a citation, and
the sparser the forest the likelier it is: the failure grows in exactly the
deployments least able to notice it.

`answer(question, min_evidence: n)` gives the caller the floor:

1. Default `0` — **off**. The behaviour of every existing caller is
   unchanged. It is **not** part of the J.10.7 key, and that is deliberate:
   it cannot change what the model would write, only whether it is asked,
   so an entry produced with a floor is the same answer as one produced
   without it. A refusal never enters the store, so no entry can exist
   under the parameter to begin with.
2. The host counts the sweep's items **that carry content** before calling
   the model. Below `n`, no model call is made.
3. The refusal is `{answer: null, reason: "insufficient_evidence",
   evidence_count, min_evidence, harvest}` — with the retrieval attached,
   because the caller asked a question and the honest reply is "here is
   everything the forest has on it, and it is less than you asked for".
   Handing back nothing would send the caller to its own parameters, which
   is the failure this whole release is about.
4. It costs nothing. The refusal is decided before the provider is called,
   so it is never billed, carries no `model` clock (J.10.6), and never
   enters the answer store — J.10.7's existing rule for empty-evidence runs,
   applied to a run that was declined for the same reason.
5. `min_evidence` is clamped to [0, the effective `k`]: a floor above the
   number of items the sweep may return is a refusal by arithmetic, and a
   caller asking for that has made a mistake, not a policy.

A floor is a blunt instrument one strong node can settle a question that
five weak ones cannot and this document does not claim otherwise. It is
the caller's knob, off unless asked for, and it is the only one that can be
enforced without asking a model to grade its own evidence.

**Counting items is not counting evidence (v0.59).** The floor as
specified above counts the sweep's items that carry content — and the
sweep returns `k` items whatever their scores, so on any forest that is
not nearly empty the count reaches the floor and the guard never fires. A
consumer agent asked a question with no answer in the corpus, with
`min_evidence: 2` set, and got three items scoring 0.0164, 0.0164 and
0.0161: the floor passed, the model ran, and it was the *model's* honesty
— not the guard's — that produced the refusal. A protection that fires
only on an empty forest is not the protection it advertises.

6. **`min_score: float`** (v0.59), default `0` — off. An item counts as
   evidence only when it carries content **and** its harvest `score` is
   at or above the threshold. It is applied before the count, so
   `min_evidence` and `min_score` compose as one floor: *n items that
   clear s*. It shares every property of `min_evidence` — outside the
   J.10.7 key, never billed, never stored, refusal shape unchanged except
   that it names both numbers (`min_score` beside `min_evidence` and
   `evidence_count`), because a refusal that hides which knob fired is a
   knob nobody can tune.
7. **What the number means MUST be stated, not implied** (v0.59). The
   `score` is RRF fusion output (C.6c): a rank artifact, near
   `1/(60+rank)` per list a node appears in — which is why 0.0164 reads
   as *"top of one retriever"* and 0.0325 as *"top of both"*. It is
   therefore comparable **within a deployment** and meaningless across
   corpora, embedders or `k` values. This document declines to ship a
   default threshold for the same reason it declines to grade evidence
   with a model: the honest artefact is a lever the operator calibrates
   against their own forest, plus the sentence explaining what they are
   calibrating.
8. **The refusal says which half refused (v0.61).** The two knobs compose,
   and the composition is sharper than it reads: RRF output is compressed
   near `1/(60+rank)`, so a threshold that means anything usually admits
   the ONE item that is top of both retrievers and excludes the filler
   and then `min_evidence: 2`, the value a caller picks to mean "I want
   two sources", refuses questions the forest answers correctly. Measured
   twice on the same live forest: `(2, 0.02)` refused a question that
   `(1, 0.02)` answered faithfully with citations. The floor is behaving
   as specified; what was missing is that the refusal reported
   `evidence_count: 1` and said nothing about the two items the threshold
   had just dropped, so the tuning problem was invisible in the only
   artefact that could show it. The refusal MUST therefore carry
   **`below_min_score`**: how many items carried content and did not clear
   the threshold. `evidence_count + below_min_score` is what the count
   would have been with no threshold, which is the number the caller needs
   to choose between lowering `min_score` and lowering `min_evidence`. Any
   surface that teaches these knobs MUST state the pairing: with a
   `min_score` that means anything, `min_evidence: 1` is the useful floor,
   and 2 is a deliberate demand for corroboration paid for in refusals.

**F.63 (acceptance).** An `answer` carrying `min_evidence` above the
number of items the sweep produced returns `answer: null`,
`reason: "insufficient_evidence"` and the harvest, makes no provider call
(no `model` clock, no cost, no store entry). Above the floor the reply is
unchanged, and the cache key is the same one the call formed before the
upgrade. Covered by tests.

### J.10.11 The provider is not a lane (v0.57)

The sweep `answer` ran whole on its forest's thread — retrieval, then
the provider round trip, then the store deposit — so for the seconds a
model took to write, the thread on which every 0.2 ms read of that
forest runs held an open socket and did nothing. Under a hundred
consulting agents that is not a latency detail; it is the lockup J.6.2
describes, reproduced by every question. The retrieval halves need the
engine; the model call needs nothing but the bundle already in hand —
`inference.answer` handed a bundle touches no vine at all, which is the
property this section makes load-bearing.

The sweep `answer` runs in **three phases**:

1. **Prepare, on a reader lane (J.6.2):** capability and binding checks,
   the sweep's retrieval, the J.10.10 floor, the J.10.7 store consult.
   A hit, a refusal, or a validation error completes here — those paths
   never leave the lane and are byte-identical to before. On the miss
   path, the phase ends by **capturing this call's trace slice** (the
   tracer events its own retrieval produced, and their engine-time sum)
   — captured at the boundary, because the lane serves other calls while
   the model writes, and a trace read later would carry a stranger's
   hops (the J.10.6/J.10.4 figures must describe this call and nothing
   else).
2. **The model call, on no lane at all.** The bundle, the binding and
   the question leave the lane; the provider round trip runs on an
   anonymous executor thread. Nothing in this phase may touch a vine, a
   catalog, a trail or the store — the phase's inputs are values, and
   its output is a reply.
3. **Settle, on the same reader lane:** the store deposit (J.10.7), the
   whisper (heat on the evidence), the audit row, the J.16 emission.
   Pinned to the lane of phase 1: the vine whose trails the whisper
   feeds belongs to that thread.

The clocks (J.10.6) are unchanged in meaning: `vine` is phase 1's
captured engine time, `model` is phase 2's round trip, `host` is the
remainder of the whole span — the three still account for it.

**Phase 2 has a stated ceiling.** The consumer team's load report
measured the old shape exactly: cold `answer` throughput pinned at 0.3
req/s whatever the concurrency, latency rising linearly with it — one
model call at a time, Little's law closing the case — and a 104 ms cache
hit arriving in 6.6 s because it waited behind generations. Removing the
lane hold removes the serialisation; what replaces it must not be "as
many sockets as there are askers", because the provider is metered and
the operator pays it. Concurrent phase-2 calls are admitted under
`MONKEYLLM_STATION_MODEL_CONCURRENCY` (default 8, `0` = unbounded); a
call over the ceiling waits in the host, visibly (the wait is inside the
`host` clock, never the `model` one). Hits never touch the ceiling —
they end in phase 1.

**The deployment states its shape.** `/v1/health` carries
`concurrency: {readers, model}` — the reader pool's size and the model
ceiling. The team discovered every limit by experiment and asked for
this directly: an agent that can read the ceiling chooses `harvest` over
`answer` by itself. Counts of capacity, never per-forest data: health
stays the unauthenticated surface it is.

**Stated exceptions, not omissions:** the **walk** (`hops`) interleaves
primitive reads with model turns by design and stays on its reader lane
for its whole duration — it occupies one lane of K, never the writer,
and it is opt-in per call. **`recurate`** (one read, one model call, one
graft) is a write and stays whole on the writer lane; it is an
operator's curation act, not a hot path. A future version may split it
with this section's pattern if it ever measures as one.

### J.10.12 The progress of an answer (v0.66)

A hosted `answer` is two costs three orders of magnitude apart (J.5.15) and
the Station answers once, so everything the call learns early it discloses
late. The sweep's bundle exists at millisecond 19 and leaves at second 10;
a walk's third hop is decided at second 22 and is first visible at second
54, next to the second and the fourth.

A Station MAY therefore serve a progress channel for one `answer` call.

1. **It is opt-in, per call, and additive.** `answer` accepts an optional
   `run`: an opaque, caller-chosen string. A call without one behaves
   exactly as before, and the RESPONSE to a call with one is byte-identical
   to the response without. The channel is `GET
   /v1/forests/{forest}/answer/{run}/events`, `text/event-stream`,
   authenticated and scoped like every other route in this part.
2. **An event carries nothing the completed response would not have carried
   to this same principal.** This is a pull under the caller's own
   credential, not J.16's push to whoever holds a URL, so the payload is not
   rationed down to identity — it is bounded by the answer itself.
   `retrieval` carries that response's own `harvest`; `hop` carries its own
   `hops[n]`. An event with a field the response lacks is a defect, and the
   two being comparable is what makes the rule checkable.
3. **The stream is not the answer.** The reply text is served on the POST
   and only there. A client that never opens the channel loses nothing; a
   client that reads only the channel has no answer. This is what keeps the
   channel optional rather than a second contract for the same act.
4. **Emission MUST NOT block the call.** The forest lane hands an event to
   the event loop and returns; it never awaits a consumer. A buffer that is
   full drops events and says how many, because a hunt slowed by somebody
   watching it is a hunt whose measurements are now about the watching.
5. **A run is a rendezvous, not a name.** It is scoped to (principal,
   forest), it may be claimed once, it expires on the order of minutes, and
   it names nothing in the forest. A second concurrent claim of a live run
   is refused. It MUST NOT appear in an audit path or a log line as
   anything but an opaque id.
6. **Nothing outlives its call.** The buffer is host memory, like a J.9 job
   record: a restart forgets records and never work. A channel opened after
   its call ended MUST close with what it has, and one for a run that never
   appears MUST close too. A watcher MAY open the channel BEFORE firing the
   call — that is the only order in which no event can be missed, and it is
   the order a console must take, because awaiting the POST means awaiting
   the whole answer — so an unclaimed run is not yet an absent one and a
   bounded grace applies before it is treated as one. Bounded is the
   requirement: a stream that hangs on a typo is indistinguishable from one
   whose call is merely slow.
7. **The MCP surface gains nothing.** No tool, no subscription, no
   listen-side change. J.1.2's reasoning about announced capabilities is
   unaffected because nothing here is announced to an agent: this is the
   console's channel, in the sense J.10.6 established when it put a timing
   in a header rather than in the body an agent pays for.

**F.138 (acceptance).** A `POST .../answer` carrying `run` returns a
response byte-identical to the same call without it. The `retrieval` event's
payload equals that response's `harvest`, and each `hop` event's payload
equals the corresponding entry of its `hops`, field for field — compared,
not asserted separately. A channel opened for a finished run closes with
what it has; a channel opened for a run that never existed closes rather
than hanging. A consumer that reads nothing does not delay the answer, and
the events it missed are counted. Covered by tests.

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

- **A node out of scope is absent**, exactly as in J.3 never a stub,
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
  MUST carry `truncated: true` the same always-explicit rule as every
  primitive budget (C.1). A projection MUST NOT silently sample.
- The payloads carry no bodies. A map is scent, not flesh: `pick` remains
  the only way to a body, with its own budget.
- **`created` and `updated` ride along** (v0.38). Both are passport facts
  the Catalog already holds, at the passport's own day precision. A
  replay of the forest's growth (J.5.4) is a shape question, and shape
  questions are what a projection exists to answer in one call.

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
| `POST /v1/admin/snapshots` | `{forest, with_payloads?}` takes one |
| `GET /v1/admin/snapshots/{forest}/{file}` | that bundle or sidecar, streamed (owner, J.13.1) |
| `POST /v1/admin/snapshots/import` | `{id}` + bundle [+ sidecar] → a new forest (owner, J.13.2) |
| `POST /v1/admin/reindex` | `{forest}` rebuilds the catalog, returns the node count (J.13.3) |
| `GET /v1/admin/locks?forest=` | the C.9 lock's state: free, orphan, or held — with the holder's card (J.13.5) |
| `POST /v1/admin/unlock` | `{forest}` removes an orphan lock file; refuses a held one (J.13.5) |

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
  outside every forest a `.bundle` inside a forest would be a binary in
  the tree A.3.1 keeps binaries out of, and the next snapshot would package
  the last one.
- **Restore into a live forest is NOT exposed.** Part I restores into an
  empty destination, so there is nothing to offer a console operating on
  an existing forest, and taking a filesystem destination from an HTTP
  caller spends the Station's authority rather than the caller's (the
  same reasoning J.8 applies to `path`). Restoring in place stays `vine
  snapshot restore`. Import (J.13.2) is neither of those things: it
  restores into a forest that does not exist yet, at a destination the
  host derives from a validated *name*.

#### J.13.3 Rebuild (v0.41)

`POST /v1/admin/reindex` with `{forest}` runs `Catalog.reindex()` and
answers `{forest, nodes, ms}`.

- **`admin` on the forest AND an unrestricted scope**, for health's
  reason (J.13) with one addition: the count it returns is the size of
  the whole forest, and it rewrites the row of every node including
  the ones a branch-scoped principal may not read. A scoped principal
  MUST be refused with that reason stated.
- **It runs on the forest's lane and the caller waits.** Rebuilding is
  offline work, exactly like a canopy build (which re-embeds every
  summary and is already synchronous); it is bounded and it is the
  thread-affinity rule (C.6.1) that decides where it runs, not the
  patience of the caller. It is NOT an ingest job (J.9): it plants
  nothing, converts nothing, commits nothing, and has no report to
  stream.
- **It writes `_derived/` and nothing else.** No commit, no model call,
  no pheromone, no trace event the audit row (J.4) is the only record
  it leaves. A Station serving read-only forests MUST still offer it:
  the derived layer is not the content, and a read-only Station that
  could never repair its own index would degrade permanently with no way
  back that does not involve a shell.
- **It may run while a batch does.** J.9's fairness rule says a call to
  a forest gets its turn between the steps of a running ingest, and this
  is such a call; the count it answers with describes the moment it ran,
  which is all any count ever does.
- **Idempotent, and never a repair of the files.** Reindexing twice
  changes nothing the second time, and a node the files no longer have
  leaves the catalog rather than being restored to it: the files win,
  which is what this endpoint exists to enforce.
- **The memo survives what did not change** (C.6b.1): rebuilding rewrites
  every row, and a body whose bytes are identical keeps its hash and
  therefore its memo entries. A `reindex` that dropped the memo would
  make the repair a punishment.

**F.41 (acceptance).** `POST /v1/admin/reindex` on a forest whose
catalog was deleted restores `locate`, `scan` and `sniff` to their
pre-deletion answers with no other action; the response's `nodes` equals
the count `vine reindex` reports at a shell on the same forest; a
branch-scoped `admin` is refused with the scope reason; a read-only
Station serves it; it produces no commit, no trace event and no
pheromone in the target forest, and exactly one audit row; a second call
changes nothing; and memo entries for unchanged bodies survive it.

#### J.13.4 Refresh the dense layer (v0.42)

`POST /v1/admin/canopy` accepts `{refresh: true}`: embed the nodes marked
stale and leave the rest alone. Same authority, lane and audit as a build
(K.4's surface), and the same answer the status, now carrying `stale`.

- **A refresh is not a build.** It embeds what changed; a build embeds
  everything and is what a model change requires (K.4 forbids a partial
  re-embed across two spaces). A refresh against a mismatched or absent
  index MUST refuse rather than half-fill it.
- **It is where the operator already goes.** Beside J.13.3's rebuild in
  the console's Optimize tab: the content (`sync`), what finds it
  (`reindex`), and the dense half (`refresh`) are one errand told three
  times, and an operator hunting for them in three consoles learns none
  of them.
- **Nothing else may embed a node.** With K.2 amended, this endpoint and
  a full build are the only places node vectors are produced. A read
  that quietly did it would put an ingest's bill inside a question again.

**F.42 (acceptance).** With the dense layer active and nodes newly
planted, `locate` MUST NOT issue an embedding request for any node: the
embedder sees exactly one call, for the query, and the same `locate`
repeated on an unchanged forest sees zero (the memo). `canopy_status`
reports `stale` equal to the number of nodes written since the last build
or refresh; `{refresh: true}` embeds exactly those and drives `stale` to
zero without re-embedding the rest; a refresh against a model-mismatched
index is refused rather than mixing two spaces; a node planted and not
yet refreshed is still returned by `locate` (BM25) and still absent from
the vector hits; and dropping the memo changes latency and nothing else.

**F.26 (acceptance).** `GET /v1/admin/health` matches `Ranger.health()` field
for field on the same forest; a principal holding `admin` on a *branch
prefix* is refused with the scope reason rather than served; a snapshot
lands outside every forest directory and a second one does not package the
first; and no maintenance endpoint produces a commit.

#### J.13.6 Re-derive what ingest derives (v0.61)

`reindex` (J.13.3) repairs what finds a node; `sync` (J.8) repairs what a
node says by re-reading its source. Between them sits a repair neither
performs: a derivation rule that improved after the material was ingested.
Aliases (G.2.6) are the case that forced it every input to that
derivation the source path, the title lives in the passport, so the
repair needs no source tree, no converter, no model and no network. Yet
the only path to it was `sync`, which resolves the recorded host root and
requires `admin` over a directory the Station may no longer be able to
read. A forest of 1,877 nodes was therefore a forest where the feature
shipped in v0.59 was, in practice, absent and "the code has it" is not a
claim a user can verify from outside.

`POST /v1/admin/recurate {forest, derive: ["aliases"]}` — under
`/v1/admin/` beside `reindex` and the canopy build, because it is the
same kind of act on the same authority, and because a literal under
`/v1/forests/{forest}/` would have to be read past the primitive
catch-all.

1. **From the forest's own passports, and nothing else.** It reads what
   the nodes already record and writes only fields the pipeline derives.
   It MUST NOT open a source file, call a converter, call a model or reach
   the network: this is arithmetic on material already committed, and
   anything else is `sync` wearing a different name.
2. **It unions, exactly as `sync` does** (G.2.6 rule 3): missing derived
   forms are added, hand-written ones are never displaced, the 16-alias
   cap never evicts an existing entry, and overflow is counted
   (`aliases_clipped`) rather than dropped in silence. A node with nothing
   to add is not rewritten and not committed.
3. **One commit per changed node, `.md` only**, subject
   `recurate(aliases): <id>`, principal stamped like every Station write
   (J.4). The report carries `scanned`, `changed`, the ids, and
   `aliases_clipped` a pass that changed nothing says so, which is the
   answer an operator running it twice should get.
4. **`admin` on the forest, on the writer lane, and the caller waits**
   the shape of `reindex` (J.13.3), for the same reasons: it rewrites
   rows the caller may not be scoped to read, and the count IS the
   forest's size. Unlike `reindex` it commits, so a read-only Station
   refuses it.
5. **`derive` is a closed list.** `aliases` is the only member in v0.61.
   `origin` is deliberately NOT one: it is derived from the source file's
   address, which this pass does not have and MUST not guess (G.2.7 rule
   2's "only when absent" protects a written origin; inventing one from a
   recorded relative path would fabricate provenance, and provenance is
   the field this product is least allowed to fabricate).
6. **In Studio it lives beside `reindex`, in Optimize** (J.5.10): `sync`
   keeps the content current, `reindex` keeps what finds it current, and
   this keeps what ingest would derive today current. Three repairs, one
   tab, each naming what it does not do.

#### J.13.7 The staging area, seen and cleared (v0.61)

J.8.3 makes uploaded bytes a courier that empties itself as documents
land. Three things still stay: a conversion that failed, a batch that was
cancelled, and — on any forest ingested before that rule — a document
whose node was later pruned. All three are legitimate; what was not is
that none of them could be **seen**. Invisible accumulation is precisely
what made a pruned node come back, and an operator with a browser had no
answer at all.

`GET /v1/admin/staging?forest=` and `POST /v1/admin/staging {forest}`.

1. **One resource, because it is one question asked twice.** The GET says
   what is there — how many files no live passport records, their total
   size, and their names (bounded, `truncated` when the bound cut). The
   POST removes exactly those.
2. **"Unrecorded" is a fact, not a guess:** a staged file whose relative
   path is no node's `source_path`. Nothing is inferred from age, name or
   modification time — a heuristic here would eventually delete a document
   somebody was about to ingest.
3. **Removal is a MOVE into `_derived/graveyard/_staging/`**, C.14's rule
   applied to the same class of bytes: the graveyard is disposable, never
   a source of truth, and the operator's to empty.
4. **It refuses while a batch runs on that forest** (`E_LOCKED`, naming
   the job): a running batch is reading these files, and one cancelled
   halfway leaves the rest of its bytes here.
5. **`admin` and an unrestricted scope**, `reindex`'s rule (J.13.3): the
   area holds bytes headed for any branch, so a branch-limited grant is not
   the authority for it. The GET is served by a read-only Station; the
   POST is not, because it writes.
6. Audited as `staging.clear` with the count. The names are not audited:
   an uploaded filename is the operator's, and the count is what the act
   was.

#### J.13.1 Snapshot download (v0.39)

`GET /v1/admin/snapshots/{forest}/{file}` streams one file the J.13
listing names a bundle or its payload sidecar with a filename header
and an octet-stream type.

- **Owner-only.** A bundle is the whole forest with its whole history:
  every branch scope, every redaction the grant table enforces, collapses
  the moment the bytes leave. `admin` on a forest is authority over the
  forest's *service*, not over every byte it has ever held under every
  other principal's scope so the only principal a download cannot
  over-serve is the one whose authority already spans everything, and
  that is the owner bit (J.2.4). A non-owner MUST be refused with that
  reason, never served a filtered archive; there is no such thing as a
  scoped bundle.
- **Contained after resolution.** `{file}` is a name, not a path: one
  segment, no separators, no relative parts, and the resolved target MUST
  still sit inside that forest's snapshot directory (the J.8.2 posture:
  validate as a name before it is a path, contain after resolution). A
  name the listing would not return is `E_NOT_FOUND`, never a probe into
  the volume.
- **Host state only.** Serving a download touches no lane, writes no
  trace, deposits no pheromone and produces no commit the same
  discipline as the J.9 job board. It is audited (J.4) with the file name
  and byte count; the audit row is the only record it leaves.

#### J.13.2 Snapshot import (v0.39)

`POST /v1/admin/snapshots/import` carries a new forest id and the
snapshot itself the bundle, plus the optional payload sidecar in the
request body, and answers with the forest the registry now serves.

- **Owner-only.** Import is J.7 creation *plus* arbitrary content that
  bypasses every converter, curation pass and review the J.8 surface
  imposes on bytes entering a forest a bundle is already forest and
  enters as-is. The only principal that may plant an unreviewed forest on
  the volume is the one that governs the volume.
- **J.7 rules apply whole.** The id is validated as a name before it is a
  path; an existing id MUST be refused rather than adopted; the creator
  holds the result with full capabilities. Import is the second way a
  forest appears on a Station, and it appears exactly where J.7 forests
  do.
- **The body is the source.** The bundle arrives as request bytes and is
  staged outside every forest (snapshots are host state, J.13); no host
  path is taken from the caller and J.8.2's roots are not consulted —
  they govern what the Station may *read*, and import reads nothing from
  the volume. The accepted size is capped by
  `MONKEYLLM_STATION_IMPORT_MAX_MB`, which as of v0.50 **has a default**
  (1024): an unbounded upload fills the volume every other forest lives
  on, and a limit nobody set is a limit nobody has. `0` still means no
  limit, for a deployment that decided so rather than inherited it.
- **A sidecar carries payloads, and the consumer decides that (v0.50).**
  Part I's producer writes only payload files, but an imported bundle came
  from somewhere else — that is what importing is — so `restore` MUST
  validate every member *before* extracting, and MUST refuse the archive
  rather than skip a member: an archive carrying something else was built
  by somebody who expected it to land, and the operator is entitled to
  know before the forest exists. Members are named positively (the payload
  files a sidecar exists to carry) rather than filtered against known-bad
  shapes; the extraction's destination is a working git repository, whose
  contents git itself later reads and acts on, and discarding relative
  segments is not a sufficient rule there. An explicit uncompressed
  ceiling applies, since compression ratios are not bounded by the upload
  cap above.
- **Arrives servable, arrives cold.** Import ends with Part I restore,
  payloads placed beside the tree, and a `reindex` a hosted forest has
  no shell to run one, and a forest the console lists but cannot serve is
  a silent failure wearing a success status. It MUST NOT spend a model
  call: no curation, no canopy build the vector layer waits for an
  operator who asks for it, and `locate` stays BM25-only until then
  (C.6). Accepted formats are exactly what Part I `create` produces. The
  new forest opens and warms like any other (J.6.1).

**F.39 (acceptance).** A snapshot created over J.13, downloaded over
J.13.1 and imported over J.13.2 under a fresh id yields a forest whose
`git log` equals the source forest's; the downloaded bytes hash-equal the
file on the volume; a `{file}` carrying a separator, a relative segment
or a name absent from the listing is refused without filesystem effect; a
non-owner `admin` is refused on both routes with the owner reason; an
existing id is refused rather than adopted; the imported forest answers
`locate` with no further shell step and stays BM25-only until a canopy is
built; and neither route produces a commit, a trace or pheromone in any
forest.

#### J.13.5 The lock, inspected and released (v0.55)

C.9's lock heals itself when its holder dies — that is the fix. What
remains for the host is the pair of questions an operator still asks:
*who has this forest*, and *how do I clear a file the kernel cannot vouch
for* (the fallback filesystems of C.9 rule 4, and the caution of wanting
to see before trusting the self-heal).

- **`GET /v1/admin/locks?forest=`** answers one of three states:
  `{state: "free"}` (no file), `{state: "orphan", holder}` (a file
  nobody holds — the next open reclaims it), `{state: "held", holder}`
  (a live writer; `holder` is the C.9 card: pid, host, since). The probe
  asks the kernel and reads the file; it MUST NOT open the forest or
  touch a lane — a diagnostic that needs the patient healthy is not a
  diagnostic.
- **`POST /v1/admin/unlock {forest}`** removes an **orphan** lock file
  and answers what it found. A **held** lock is refused with `E_LOCKED`
  quoting the card: an endpoint able to break a live writer's lock is an
  endpoint able to produce two writers, which is the corruption C.9
  exists to prevent — no flag overrides this. Both routes ride
  `admin_gate` (C.12 rule 6) and the mutation is audited under J.4.1
  with the forest id and the card it removed.
- **The console offers it where the refusal appears (amends J.5.9).**
  The Health console, on an `E_LOCKED` answer, shows the lock card and —
  for the states the endpoint would accept — the release action. The
  button is the API's `unlock`, nothing more: a console MUST NOT gain a
  path the API refuses.

**F.40 (acceptance).** For every query in the Phase 0 suite, a `sniff`
answered from a cold memo and the same `sniff` answered from a warm one
are byte-identical once ranking fields are held constant, and both equal
the direct scan with the memo disabled; editing one node's body changes
that node's result on the next call while every other node is served
from the memo; a `reindex` after an edit that restored the original text
invalidates nothing; a scoped `sniff` populates entries a later global
`sniff` uses; a node with `content: reference` is rescanned every call;
deleting `_derived/` changes latency and nothing else; and `heat` and
`score` still move between two otherwise identical calls.

### J.14 Payload bytes (v0.48)

A `media` node's image and a dataset's `.db` live beside the map as
payload files (A.3.1, G.7). Every read primitive serves the textual
proxy on purpose text to find, binary to consume (G.5) but until
now nothing served the binary to the person: a screenshot the Clipper
ingested was a node whose image no console could show.

`GET /v1/forests/{forest}/payload/{node}`:

- Requires the `read` capability on the forest. The node resolves
  through the same scope rules as every read: out of scope and absent
  answer a **byte-identical `E_NOT_FOUND`** (J.3's no-existence-oracle
  invariant). A node without a `payload` field is `E_NOT_FOUND` too —
  absence is explicit, the map keeps working.
- A remote payload URI (G.9 `s3://`, `file://`) is refused with
  `E_SCHEMA` naming the scheme: v1 serves local bytes only. Fetching
  on a GET would hide a network dependency inside a read; a remote
  region is warmed by `vine prefetch`, not by a browser.
- The resolved file MUST lie inside the forest root. The `payload`
  field is Gardener- or operator-written, not caller input but a
  containment failure is refused, never followed; this surface hands
  out file contents and gets the J.8.2 discipline.
- The response is the raw bytes: `Content-Type` guessed from the file
  name (`application/octet-stream` when unknown), `ETag` from
  `payload_hash` when the node carries one, `Cache-Control: private`.
- It is a **human surface**. Payload bytes MUST NOT enter material the
  host assembles for a model not through this route, not through any
  other: the describer (G.5.1) reads the image at ingest, and a
  multimodal *client* that wants the pixels fetches them deliberately
  through `view` (C.6d), into its own context, under its own budget.
  What G.5's line forbids is bytes arriving unasked in a token-budgeted
  bundle; what it always intended is a client choosing to consume the
  binary it found.
- Audited like a read; served by a read-only Station (it writes
  nothing).
- A console SHOULD render an in-scope media node's image payload
  through this route beside the node's prose (v0.48). The description
  exists because of the image; a reader shown one without the other is
  left trusting text about pixels nobody can see.

**F.49 (acceptance).** The served bytes equal the file on disk and the
`ETag` equals the node's `payload_hash`. A scoped principal asking for
an out-of-scope media node receives the same envelope as for a missing
one; a node without payload the same. A dataset's `.db` is served
under the same rules. A `payload` field resolving outside the forest
root is refused, and a remote URI answers `E_SCHEMA`. All covered by
tests.

#### J.14.1 The document is a byte surface too (v0.56)

J.14 served the binary beside the map; nothing served the map's own
text. `pick` returns JSON with the body escaped inside — and above the
C.4 ceiling, not even that — so the only way to hand a forest document
to an e-mail, a ticket, a PR or a pipeline was to reassemble it outside
the forest. That reassembly is the local `.md` habit, mechanized.

`GET /v1/forests/{forest}/export/{node}`:

- Answers `text/markdown; charset=utf-8` with
  `Content-Disposition: attachment` naming `<leaf>.md`. **No token
  budget**: this is a download for people and pipelines, J.14's
  precedent — budgets protect a model's context window, and none is on
  this path.
- For `content: inline` the response is the passport file **verbatim,
  byte-identical** — frontmatter and body exactly as planted, which is
  what makes `curl … > report.md` reproduce the planted document
  (F.84). For `content: cached|reference` the response is the
  frontmatter plus the resolved body (G.7); an unreachable body is
  `E_NOT_FOUND` with the map intact, G.7's own rule.
- Scope, refusals, audit: J.14 verbatim — `read` capability,
  out-of-scope and absent byte-identical `E_NOT_FOUND`, path containment,
  audited as a read, served by a read-only Station.
- Any node type exports: a dataset or media node exports its passport
  (the map); the payload stays J.14's route. One route per surface,
  no overlap.

**The subtree exports too, and the flag is never swallowed (v0.57).**
The consumer team sent `?recursive=true`, received `200` and the branch
node alone — the parameter was accepted and ignored, the exact defect
C.8 had just fixed for `graft`, alive on the route beside it. Two rules:

1. `recursive=true` on a **branch** returns a **zip**
   (`application/zip`, `Content-Disposition` naming `<leaf>.zip`): one
   member per node of the subtree, the branch's own passport included,
   each member the **byte-identical single export** of that node, named
   `<id>.md` (the id is a path, so the zip unpacks as the subtree it
   is). Members are the caller's scope's view: out-of-scope nodes are
   absent exactly as they are absent from `scan` — and absent silently,
   because a manifest of what a scope may not see would be the size
   oracle J.3 exists to prevent. Payloads are NOT inside (A.3.1's rule:
   the map travels, the binaries are referenced); J.14 remains the byte
   route. On a non-branch node, `recursive=true` is `E_SCHEMA` — a leaf
   has no subtree, and pretending otherwise is the silence this rule
   removes.
2. **An unknown query parameter on this route is `E_SCHEMA`**, naming
   the parameter and listing the accepted set — C.12's discipline
   applied to the query string. A download URL is pasted, edited and
   shared by hand more than any JSON body; the silent-parameter failure
   mode is *worse* here, not better.

### J.15 The Clipper (v0.48)

A browser extension that clips the page a person is reading into a
forest. It is a **client** Studio's rule (J.0) verbatim: MCP/REST
surfaces only, no privileged path, nothing in the engine knows it
exists. What is normative here is the little that keeps it honest:

- **It stores the server origin and a paired key (J.2.6), never the
  password.** The password is a gesture at pairing, not data at rest.
  Logout discards the key; revocation stays in People (J.2.2), where
  every key already lives.
- **Prose goes through `compose`; binaries go through `upload`.** One
  clip = one `compose` (a single document, answered in place, J.8.1
  review available); a screenshot = one `upload` entry (`{name, b64}`,
  a J.9 job). The Clipper MUST NOT invent a third write path J.5.7's
  rule for the console is the rule for every client.
- **A page clip with a screenshot is two nodes**, tied to each other
  as far as the write paths allow: the markdown names the image file
  it was clipped with, and the image's *file name* carries the page's
  title and host the stub body (G.5.1) quotes that name, so the
  provenance survives into prose. The media node's body is written
  server-side by the stub or the describer; a client cannot author it,
  and MUST NOT gain a way to (that would be the third write path this
  section forbids). The pairing is prose, not a new edge type; the
  Curator's closed-candidate proposals (G.4.2.1) remain the only
  machine-written links.
- **The click answers immediately; the work happens behind it.** The
  Clipper MUST NOT hold its UI against the server: uploads, composes
  against a busy lane and slow batches queue in the extension
  (storage-backed) and settle with a notification, while the person
  keeps browsing. A popup frozen against a forest lane that is mid-
  ingest (J.9, G.10.1) is the failure mode, not a UX choice.
- **On `E_LOCKED` the Clipper queues client-side and retries.** The
  host still never queues (J.9); the queue dies with the browser, like
  Studio's (J.9.2).
- **Capture offers the whole page and a dragged region (v0.51).** A page
  capture MUST be the scrollable document, not the viewport: the extension
  scrolls to the end, shoots each viewport, and composes the slices into
  one image. What a screenshot is for here is the reason — it is read once,
  at ingest, by the G.5.1 describer, and that prose is all `locate` and
  `sniff` will ever see of it, so a capture bounded by the window decides
  how much of the page is findable by where a scroll bar happened to rest.

  Four rules, each of them a way the obvious loop goes wrong:

  1. **Re-measure at every step.** Scrolling is what makes a lazily-loaded
     page grow, so the height read before the first move is not the page's
     height, and trusting it stops the walk in the middle of a feed.
  2. **Hide viewport-fixed elements after the first slice.** They travel
     with the scroll, so leaving them stamps the same header down the
     length of the composed image, over the content it covers.
  3. **Bound it, and notice a page that does not move.** An explicit slice
     limit, and a walk that ends when scrolling stops advancing rather
     than shooting one viewport repeatedly; the composed height MUST come
     from what was captured, so a page that outgrew the limit ends where
     the capture ended rather than in a blank band.
  4. **Give the page back.** The scroll position, and anything hidden for
     the walk, are restored when it finishes — a clip that quietly leaves
     somebody at the bottom of an article has taken something from them.

  A page the extension may not script still yields the capture the browser
  will give: one viewport is a smaller answer, never an error.

  The **region** picker is unchanged and stays a crop of the visible view —
  it is a rectangle somebody drew on what they were looking at. It is an
  overlay injected on the click the same activeTab
  consent as every injection and the crop happens client-side,
  device-pixel-ratio aware: no pixels leave the tab except the chosen
  rectangle. The drag ends the DRAW, never the choice: the rectangle
  stays up, movable and resizable by its handles, until the person
  confirms a selection two pixels short is adjusted, not redrawn.
  The picker MAY annotate (arrow, box, pen, text label): annotations are
  **vectors, composited by the worker onto the cropped bitmap** —
  never DOM the capture must race, and they render at full sharpness
  at any pixel ratio. The picker MAY take a note, typed or dictated;
  the note travels as a **paired `compose`** naming the screenshot
  file (the two-nodes rule above) the media node's body stays the
  server's to write. Dictation runs in the **extension's own
  offscreen context**: the microphone grant belongs to the extension,
  made once on a visible page, and the page under the overlay never
  holds the microphone its origin collects no grant and its
  Permissions-Policy cannot forbid what never runs in it.
- **Keyboard shortcuts are the platform's commands, never key hooks.**
  Suggested keys apply only when nothing else holds them a clash
  with the browser or the system resolves to *unassigned*, never to a
  stolen key and the person remaps them in the browser's own
  shortcut settings. Pressing one is a user gesture like the click,
  and grants exactly what the click grants.
- **An image under the pointer is clippable from its context menu.**
  The bytes are read from the page; when cross-origin rules bar
  reading them, the fallback is the screen region the image occupies.
  Either way they travel as an ordinary `upload`, with `source_url`
  naming the page (J.8).
- **Every clip carries its address.** Composes end with the `Source:`
  line; uploads carry `source_url` a clip nobody can trace back to
  its page is a citation with no cite.
- **Writing happens in a full tab, not the popup.** The editor page
  offers room, rich editing and dictation through the browser's own
  speech facilities, and sends through the same `compose`. A popup
  dies on blur; a microphone permission prompt would kill the very
  note it asked to hear.
- **The extension's UI language is the person's own setting**, stored
  with the extension, defaulting to the browser's. Manifest-level
  strings follow the browser locale the platform's rule, not ours —
  and the panel's language preference lives in another origin's
  storage, unreachable by design.
- **It injects on user action only.** The extension requests host
  permission for the paired origin, reads the page under `activeTab` —
  the click is the consent and MUST NOT run on every page. It sends
  exactly what the person chose: the selection, the readable article,
  the page as an image, or the region they drew. That the page capture
  scrolls to compose itself (above) is the same single consent doing the
  same single job it is one capture of one page, not a second visit.
- **Clipped pages are third-party text entering curation.** The
  boundary is held by two things that already exist: the pair mask
  (a clipper key holds `read`+`ingest` and nothing else) and
  G.4.2.1's closed candidate list, which makes an invented link
  target structurally impossible no matter what the page says.
- **Distribution is the Station's, and it is not admin-gated.** One
  shared build, served at `GET /clipper.zip` a static artifact
  beside the console shell, unauthenticated like it: the extension is
  public software carrying no secrets and no origin, because pairing
  supplies both. The server ships no per-user binary, ever. The
  console MUST offer the download to every signed-in person, not only
  to administrators pairing is self-service (J.2.6), so distribution
  MUST be too, or the administrator becomes the gatekeeper the pair
  route exists to remove. A deployment that stages no build answers
  404 with the reason, like a missing Studio build does.

**F.55 (acceptance).** A page taller than the window, clipped as an image,
arrives as one media node whose picture reaches the end of the document —
not the end of the window. On a page that loads as it scrolls, the capture
reaches past what the document measured before the first move. A fixed
header appears once, not once per screen. The person's scroll position is
where they left it. A page that cannot be scrolled, and a page the
extension may not script, each yield one viewport rather than an error.

### J.16 Webhooks (v0.53)

Everything Part J does so far is **pull**. A principal arrives, is
identified, is scoped, and reads. That is the right shape for a knowledge
base and the wrong shape for everything around one: the operator who wants
a message when a contract lands, a rebuild when the corpus changes, or a
page when the answer model starts refusing has no way to be told. Their
only option is to ask again, and asking again is the one thing this
project's economics are built against.

A webhook is the outbound half. The Station POSTs a small, signed
notification to an address the operator registered, when a named event
happens. It is a **host** surface, exactly like providers and bindings
(J.10): no primitive gains a parameter, no MCP tool is added, and nothing
here is written into a forest.

Two of those are deliberate rather than incidental. **No MCP tool**,
because a webhook is a standing instruction to send data outward and an
agent that could install one could exfiltrate a forest one event at a
time — the same reasoning that keeps `ScopedVine.plant` from forwarding
G.2.5's `adopted` flag. **Nothing in the forest**, because a forest handed
to another operator MUST carry no credentials (J.0), and a webhook URL is
a credential in every way that matters.

#### J.16.1 The payload is an audit row with a destination (normative)

This is the load-bearing rule and every other rule in J.16 follows from
it: **a delivery leaves the Station's authority behind.** Inside, a read is
scoped by J.3, bounded by a token budget and recorded by J.4. The moment
bytes are POSTed to a URL, whoever holds that URL reads them, for as long
as they keep them, under no scope at all; and a grant revoked afterwards
reaches none of it.

So a webhook body carries what an audit row carries — *what happened, to
what, by whom, when* — and MUST NOT carry content:

- node bodies, `pick` sections, `sniff` snippets: never;
- a question, a model's reply, the text of its evidence: never;
- SQL, column values, dataset rows, a dataset's `## Notes`: never;
- payload bytes, or any URL from which bytes can be fetched without a
  credential: never.

What it does carry is **identity and shape**: node ids, node types,
parents, counts, states, job ids, commit shas, capability names,
durations, costs, error codes. A receiver that wants more comes back
through the API holding its own credential, and is scoped like anybody
else. That is the entire design: the notification says *there is something
to read*, and the reading stays inside the authority that governs it.

**One opt-in, per webhook.** A webhook MAY carry `include_metadata`. Set,
the events that name a node also carry that node's `title` and `summary` —
curated metadata, the same two fields `locate` already returns to anyone
holding `read`. Three rules keep the opt-in from becoming a hole:

1. It defaults to **off**, and the console states what turning it on
   means at the moment it is turned on.
2. It never widens past `title` and `summary`. The list above stays
   forbidden in every mode; there is no setting that sends a body.
3. **It adds only what the act already knew.** `plant` was handed a title,
   so `node.planted` can state one; `graft` was not, so `node.grafted`
   does not, and does not go looking. A webhook MUST NOT cause a read: an
   event that opened a node in order to describe itself would put an
   unbounded, unaudited retrieval on the path of every write.

#### J.16.2 Two scopes, and why a scope is a ceiling

A webhook belongs to exactly one scope:

- a **forest** — managed by a principal holding `admin` on it, hearing
  that forest's events;
- the **deployment** — managed by a principal who *governs the
  deployment*, which is J.10.2's reach rule unchanged (the owner, or an
  administrator of every forest that exists), hearing every forest's
  events **and** the ones that belong to no forest.

The deployment scope exists because several of the most useful signals are
not about a forest at all: a refused sign-in, a key issued, a provider
whose address moved. J.4.1 rule 3 already makes those the owner's to read,
and a webhook is a way of reading, so the same reach decides it.

The scope is a **ceiling, not a filter**. A forest webhook cannot
subscribe to a deployment event however its subscription list is written,
and the Station refuses the subscription rather than silently dropping the
event: a scope that a list could widen would make the list the control,
and the list is edited by whoever holds the console.

`forest.created` is deployment-scoped for a duller reason than authority.
A forest that has just been created has no webhooks on it, so the event,
delivered to its own scope, would be delivered to nobody.

**Authority is re-read at delivery, never only at creation.** v0.50 settled
that a second forest narrows deployment authority *the moment it exists,
with nobody revoking anything*; a standing instruction to send data
outward would otherwise escape that rule, having been created while the
authority held and continuing to fire after it lapsed. So every delivery
re-reads the authority of the principal the webhook is **owned by** —
`admin` on its forest, or deployment governance — and a webhook whose
owner no longer holds it is **suspended**, not deleted, and says so
wherever it is listed. Suspension is undone by the grant returning, or by
another principal with the authority adopting the webhook. Deleting it
instead would be the same fact delivered as silence, and silence reads as
an integration that works.

#### J.16.3 The catalogue

Event names are **contract tokens** and are English, the A.1 rule applied
to a second vocabulary. They are `group.thing.happened`, they are stable
across versions, and the catalogue is **closed** and **served**: `GET
.../webhooks` returns it beside the list, so a console never hard-codes it
and an integration can enumerate what it may subscribe to.

Only events the Station can actually emit are named. A catalogue entry
that never fires is worse than an absent one, because it is a subscription
that reads as coverage.

| Scope | Group | Event | Fires when |
|---|---|---|---|
| forest | content | `node.planted` | `plant` created a node (C.7) |
| | | `node.grafted` | `graft` extended one (C.8) |
| | | `node.pruned` | `prune` removed one (C.14, v0.56) |
| | | `node.transplanted` | `transplant` moved one (C.15, v0.58 — both ids, backlinks rewritten count) |
| | | `branch.created` | the planted node was a branch (J.5.7) |
| | | `dataset.created` | `plant` created a dataset (C.7.1) |
| | | `dataset.changed` | `tend` wrote a row (C.10) |
| | ingest | `ingest.started` | a batch was accepted (J.9) |
| | | `ingest.finished` | it finished |
| | | `ingest.failed` | it ended in an error |
| | | `ingest.cancelled` | it was cancelled |
| | | `ingest.document.failed` | one document inside it failed (G.10) |
| | answer | `answer.served` | `answer` replied, from the model or the store |
| | | `answer.failed` | the composite errored |
| | access | `access.denied` | a scoped call was refused (403) |
| | | `grant.changed` | a grant on this forest was written or revoked |
| | | `model.bound` | a role was bound or unbound here (J.10) |
| | maintenance | `snapshot.created` | Part I, over J.13 |
| | | `canopy.built` | Part K's index was built or refreshed |
| | | `reindex.finished` | J.13.3 repaired the catalog |
| | | `recurate.finished` | J.13.6 re-derived from the passports |
| deployment | access | `auth.login.succeeded` | a sign-in was accepted |
| | | `auth.login.failed` | one was refused (J.4.1) |
| | | `pair.issued` | a password became a key (J.2.6) |
| | | `key.issued` | a key was minted |
| | | `key.revoked` | one was revoked |
| | config | `provider.changed` | a provider was created, edited or removed |
| | | `forest.created` | a forest was created (J.7) |

`webhook.test` exists and is **not subscribable**: it is what the console's
test button sends, so that "does this address work" is answered without
waiting for a real event and without a real event's data.

**Reads are deliberately absent.** Every read already deposits pheromone
and writes an audit row. A webhook per read would put an outbound HTTP
request on the path of the primitive with the tightest budget in the
system (F.6), in order to say something the audit says better and the
trails say cheaper.

#### J.16.4 Delivery

**An event MUST NOT be able to fail or slow the act that produced it.**
J.4's last sentence, applied to a thing that talks to the internet.
Emission is non-blocking and never runs on a forest lane (J.9): the
primitive has returned before any socket is opened. Emission MUST also be
O(1) when nothing subscribes — the Station holds the subscription index in
memory and refreshes it when a webhook is written, because a registry read
per primitive call would tax the hot path in order to answer "no".

- **One body, many attempts.** The body is byte-identical on every retry,
  so the signature is stable and a receiver deduplicating by `id` sees one
  event. What changed between attempts travels in the headers.
- **Retries are bounded, backed off, and stop.** Delivery is best-effort
  notification and never a queue with a guarantee: what happened is
  recorded in the audit table and in git, and a webhook is a hint that
  they moved. A restart forgets pending retries — stated here, rather than
  discovered later.
- **The queue is bounded and says so.** Overflow drops and counts, and the
  count is reported. A silent drop reads as an integration that works.
- **Consecutive failure suspends the webhook**, with the reason recorded.
  An endpoint that has been answering 500 for a week is not a
  subscription; it is a retry loop nobody is watching.
- **Every attempt is recorded**: delivery id, event, when, attempt number,
  HTTP status, duration, and a clipped copy of the response. The response
  body is the *receiver's* text rather than forest content, so keeping it
  is what makes a broken integration debuggable. Records are bounded per
  webhook, and the bound is stated.
- **Redelivery** re-sends a recorded delivery, body unchanged, as a new
  attempt. It is how an integration is repaired without waiting for the
  event to happen a second time.

**Signing.** Every request carries `X-MonkeyLLM-Signature: sha256=<hex>` —
the HMAC-SHA256 of `<timestamp>.<body>` under a per-webhook secret —
beside `X-MonkeyLLM-Timestamp`, `X-MonkeyLLM-Event`,
`X-MonkeyLLM-Delivery`, `X-MonkeyLLM-Attempt` and `X-MonkeyLLM-Forest`.
The timestamp is *inside* the signed string, so a captured body cannot be
replayed as a fresh event. The secret is shown **once**, at creation, and
the console says so at the moment it shows it (J.5.4's rule, for J.5.4's
reason). It can be rotated; it can never be read back.

**The destination is validated like a provider's.** A webhook URL is a
caller-supplied address that the Station will connect to repeatedly and
unattended — J.10.2's problem exactly, so it gets J.10.2's answer:
`http(s)` only, the host name resolved and **every** address it maps to
judged, non-public ones refused unless the deployment says otherwise
(`MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE=1`, which a self-hosted n8n on
the same machine needs). Text inspection would decide on what a URL says
rather than on where it goes.

**Headers.** A webhook MAY carry a small map of request headers, because
many destinations authenticate. Bounded, never overriding the
`X-MonkeyLLM-*` set or the framing headers, and **write-only**: the API
returns header *names* and never their values, the same custody rule a
provider's key gets, and for the same reason — a value that can be read
back is a value that leaks through whoever can read the configuration.

**A webhook is audited as the governance change it is.** J.4.1's table
gains a row: created, edited, removed, tested, rotated, suspended, each
carrying the webhook's id and its destination **host** — never the path,
never the secret, never a header value.

#### J.16.5 The console (amends J.5.1)

Webhooks are a console of their own, in the **Build** group, requiring
`admin`. That group then reads as the three directions a forest moves in:
Ingest is what comes in, Models is who reads it, Webhooks is what goes
out.

- **The catalogue is presented as the operator's five questions**, not as
  a list of twenty-five tokens: what changed, what was ingested, what was
  asked, who was let in or refused, what maintenance ran. Each group
  selects and clears as a group; each event states in one line when it
  fires. The token itself is shown as stored — it is a contract name, and
  J.5.3's content rule applies to it.
- **The body is previewed before it is subscribed to.** Selecting an event
  shows the exact JSON that event will POST, including whether
  `include_metadata` is on. An integration is built against a shape, and
  an operator who cannot see the shape builds against a guess.
- **The test is one button and its answer is the whole answer**: the
  status, the duration, and the response the endpoint gave back. A test
  that only reported success or failure would leave the two most common
  causes — a wrong path answering 404, a proxy answering HTML —
  indistinguishable.
- **The secret is shown once, and said so at that moment** (J.5.4).
- **The deliveries are a table with the event, the time, the status, the
  attempt and the error**, newest first, with redelivery on each row.
- **The deployment scope appears only for a principal who governs the
  deployment** (J.16.2). Hiding is presentation and not the control — the
  API refuses either way — but an entry that could only ever refuse
  teaches nothing (J.5.1).
- The address carries the selection: `?hook=` for the webhook being
  edited, `?tab=` for settings or deliveries, both in `useRouteState`'s
  `allow` list (J.5.8).

**F.65 (acceptance).** A webhook subscribed to `node.planted` on a forest
receives exactly one POST per `plant`, whose body carries the node's id,
type and parent and carries **no** `title`, `summary` or body text. The
same webhook with `include_metadata` set carries `title` and `summary` and
still no body text. `graft` on the same webhook carries neither, with the
opt-in set or clear. The `plant` response time is unchanged when the
destination is a black hole that never answers.

**F.66 (acceptance).** A forest-scoped webhook asking to subscribe to
`auth.login.failed` is refused with `E_SCHEMA` naming the event. A
deployment-scoped webhook created by the owner receives it. When a second
forest is created and the webhook's owner administers only the first, the
next delivery does not go out and the webhook is listed as suspended,
naming the reason; granting `admin` on the second forest resumes it
without the webhook being edited.

**F.67 (acceptance).** A destination answering 500 is retried the stated
number of times, backing off, with one delivery record per attempt sharing
one delivery `id` and one signature; after the stated number of
consecutive failures the webhook is suspended. `sha256=HMAC(secret,
timestamp + "." + body)` verifies against the headers on every attempt.
A URL resolving to a loopback or private address is refused at creation
unless `MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE=1`, and a header value
saved on a webhook is never returned by any endpoint.

### J.17 A share is a key with one room (v0.56)

The reading console (J.5.14) shows a document to a person with an
account. The person the document is FOR usually has none — the operator's
stated flow is "send it to the dev team" — and as long as reaching them
requires reconstructing the document outside the forest, every report
has a local copy by definition. A **share link** hands one document to
somebody with no account, under authority that stays the issuer's.

`POST /v1/forests/{forest}/share {node, days?}` → `{id, url, expires}`.
`GET /s/{share-token}` serves the reading page; the page fetches
`GET /v1/share/{share-token}` → `{title, markdown, outline, expires}`.
`GET /v1/forests/{forest}/shares` lists; `DELETE
/v1/forests/{forest}/shares/{id}` revokes.

Normative:

1. **One room.** A share names exactly one node. It grants `read` of
   that node's export — never its neighbours, never `locate`, never the
   forest's existence beyond this document. The served markdown resolves
   like J.14.1's export; `media:` references render as their captions
   (J.10.9's fallback), because the token's scope is one node, not the
   images beside it. A caller who wants the images shared shares their
   nodes.
2. **Issued inside the issuer's own reach.** Creating a share requires
   `read` with the node in scope — a share is a delegation, and nobody
   delegates what they do not hold. The token is generated with ≥128
   bits of entropy and stored **hashed**, exactly as keys are (J.2.2);
   the URL is the secret, shown once at creation.
3. **Authority is re-read at every serve (J.16's lesson).** Each `GET`
   re-checks: share not revoked, not expired, AND the issuer still
   holds `read` with the node in scope. A lapsed grant suspends every
   share it issued, the moment it lapses — a share MUST NOT outlive the
   authority it delegated. Revoked, expired, suspended, absent and
   never-existed answer one **byte-identical `E_NOT_FOUND`**: a share
   URL in the wild must not become an oracle for why it stopped
   working.
4. **Expiring, bounded.** `days` defaults to 7, ceiling 90 (`E_SCHEMA`
   beyond — the J.2.6 shape). No non-expiring share exists: a URL is a
   credential that cannot be rotated, only revoked, and one forgotten
   forever is the incident report of 2027.
5. **Listed and revocable where it was minted.** The reading console
   shows the node's active shares to their issuer (and all of a
   forest's to its admin, who may revoke any — a share is a grant, and
   J.2's rule is that grants are visible to who governs the forest).
   The listing carries `id`, node, issuer, `expires` — **never the
   token**, which no endpoint returns after creation.
6. **Audited as governance and as reads.** `share.created` /
   `share.revoked` are J.4.1 governance rows (by share `id`); every
   serve is audited by share `id` — the reader is anonymous, the
   authority is not. Serves are rate-limited beside `login`/`pair`
   (J.2.6): the token space makes guessing hopeless, the limiter makes
   it loud.
7. **The page is the reading console in anonymous dress.** Same
   renderer, same CSP (J.5.13), outline sidebar, copy/download of the
   raw markdown. No Studio chrome that presumes a session; no link into
   the forest — the document ends at its own edges.
8. **One address, two representations (v0.59).** `/s/{token}` began as a
   console route, so the SPA fallback served it only to a request that
   accepts HTML (J.5.8's rule, which is correct and stays): the first
   thing anybody does to debug a share — `curl` it — answered **404**
   while the same URL opened fine in a browser, and a link that works
   for people and 404s for machines reads as a broken feature. The route
   now content-negotiates on `Accept`: a document request gets the
   reading page, and every other request gets exactly what
   `GET /v1/share/{token}` returns, from that same handler — same
   authority re-read (rule 3), same rate limit, same byte-identical
   `E_NOT_FOUND` for every dead state, same audit row. No second URL is
   minted and the mint response is unchanged: the resource is *the
   shared document*, and two spellings of one resource is the thing that
   confused this in the first place.

**F.68 (acceptance).** Every MCP tool result's text block contains no
newline and no indentation whitespace between tokens, and parses to the
same keys and values the REST surface returns for the same call. A tool
result carrying the `error` envelope (`look` on an unknown forest, `look`
on a missing node, `tend` on a non-dataset) sets `isError: true`; a
successful call does not; the envelope body is `{code, message, hint}`
either way. `serverInfo.version` equals the installed package version, and
`resources`/`prompts` capabilities are absent from `initialize` while
nothing is registered behind them. Covered by tests.

**F.69 (acceptance).** `move(direction="all")` on a node with
`degree > 0` is `E_SCHEMA` naming `direction`, the value and the accepted
set — never an empty neighbour list. `locate(scope="typo")` and
`scan(fields=["nope"])` are refused the same way. Every accepted value
behaves exactly as before. Covered by tests.

**F.70 (acceptance).** On a forest larger than one `scan` page, chaining
`scan(parent, recursive=true, after=<last next>)` from `after: ""`
enumerates every node exactly once — no loss, no duplicates — and every
response carries `total` (constant across the chain) and `returned`. A
page that left nodes behind carries `next`; the final page does not.
`after` beside `toward` is `E_SCHEMA`. Without `after`, ordering and
shape are byte-identical to v0.53, plus `total`/`returned`. Every `scan`
item's default fields include `body_tokens`; a `sniff` result and a
`harvest` item carry `body_tokens` equal to `look`'s `stats.body_tokens`
for the same node. A demoted `sniff` hit carries `demoted: true` with its
score unadjusted; `_meta/schema` in a recursive scan carries
`system: true`. Covered by tests.

**F.71 (acceptance).** A `graft` that changes the body without a
`summary` in the same patch returns `summary_stale: true`; carrying a
`summary` (or touching no body) returns no such key. A frontmatter-only
graft setting `aliases` succeeds, the FTS row is refreshed, and
`locate` finds the node by the new alias; 17 aliases, or an alias that is
not a non-empty string, is `E_SCHEMA`. Covered by tests.

**F.72 (acceptance).** With `aliases: {targets: BE}` in `gardener.yaml`,
adopting `targets/291-budget.md` yields a node whose passport carries
`aliases: ["BE-291", "targets/291"]` and `locate("BE-291")` returns it
first; the same tree adopted without the map yields no aliases. A `sync`
refresh preserves them. Curation never writes aliases. Covered by tests.

**F.73 (acceptance).** An `answer` whose provider reply carries
`finish_reason: "length"` returns `truncated: true` and the
`finish_reason`, and is not stored: the same question asked again runs
the model again. A finished reply carries neither flag and stores as
before. A call with `reply_tokens: 40` is served with the clamped 64 and
the response says `reply_tokens: 64`. Covered by tests.

**F.74 (acceptance).** `health()` lists under `needs_description` exactly
the `type: media` nodes whose body still carries the G.5.1 stub sentence,
and the sentence is a single shared constant between the converter and the
check. Covered by tests.

**F.75 (acceptance).** A `.vine.lock` file whose writer is gone (the file
present, the kernel lock unheld) does not stop the next writable open:
the Vine opens, serves, and rewrites the card — no manual step, no
restart. A second writable Vine on a forest whose first is still open is
refused `E_LOCKED` naming pid, host and since; closing the first admits
the second. On a Station, an orphan lock left before boot changes neither
warm-up nor any request's outcome. Covered by tests.

**F.76 (acceptance).** `GET /v1/admin/locks` reports `free` with no file,
`orphan` for a card nobody holds, and `held` with the card while a writer
lives. `POST /v1/admin/unlock` removes the orphan (audited, with the
card), answers idempotently for `free`, and refuses `held` with
`E_LOCKED` quoting the card. Both refuse a missing `forest` with
`E_SCHEMA` (C.12 rule 6) and a non-admin with `E_FORBIDDEN`. Covered by
tests.

**F.77 (acceptance).** While a foreign writer holds a forest,
`/v1/health` answers `status: "degraded"` with `forests.locked` counted
and no forest id anywhere in the body, and `forests()` / `GET
/v1/forests` mark that entry `locked: true` for a key that may see it.
With the writer gone and only its file left, health answers `ok`, nothing
is marked, and every read serves. Covered by tests.

**F.78 (acceptance).** Every tool name returned by `tools/list` appears
in the `instructions` the same server hands to `initialize` — compared
mechanically, so the next tool added without its sentence fails the
suite. Covered by tests.

**F.79 (acceptance).** `pick` of a body over 4,000 tokens returns a
non-empty first page within the budget, `truncated: true`, `next`,
`returned` and `total`, and a hint naming `after`. An unknown cursor is
`E_SCHEMA` naming it; `after` beside `section` is `E_SCHEMA`; a body
within budget returns the pre-v0.56 shape with no cursor fields. A
single block wider than the budget arrives alone, flagged `cut: true`,
with `next` advancing past it. Covered by tests.

**F.80 (acceptance).** The pages of a multi-page body, fetched in cursor
order and concatenated, equal the body **byte-identically** — measured
on a body with tables, fenced code, nested lists and accented text. A
19,420-character body completes in at most 5 calls. `pick(id,
section=[a, b, c])` returns every requested name in exactly one of
`sections` / `missing` / `dropped`, in request order, under one
4,000-token budget; a bare-string `section` returns the v0.55 shape to
the byte. Covered by tests.

**F.81 (acceptance).** `graft` whose patch carries an unknown key beside
a legal operation refuses with `E_SCHEMA` naming the key and listing the
accepted operations, and writes nothing — the legal operation is NOT
applied. The same unknown key alone refuses identically. Covered by
tests.

**F.82 (acceptance).** `look` returns `created` and `source` for every
node and `aliases` for a node that carries any; a scoped look shows the
same values. `scan(filter={"source": "agent"})` returns exactly the
nodes whose passport says so. Covered by tests.

**F.83 (acceptance).** No wire response of any primitive contains the
string `banana` in a field value: `kind` emits `note`/`branch` in
`locate`, `scan` and everywhere else it appears. `locate(scope="notes")`
filters leaves; `scope="bananas"` behaves identically (deprecated
alias); `scan(filter={"kind": "note"})` matches what `kind` emits.
Covered by tests.

**F.84 (acceptance).** `GET .../export/{node}` of an inline-content node
answers `text/markdown` bytes equal to the planted file, for a node of
any size; out-of-scope, absent and payload-less answer the byte-identical
`E_NOT_FOUND` of J.14; a read-only Station serves it. Covered by tests.

**F.85 (acceptance).** `prune` of an unreferenced leaf removes the
passport, the parent-index entry and the catalog row in one commit, and
a subsequent `plant` of the same id succeeds. `prune` of a node with
`edges_in` refuses with `E_ANCHORED` naming the anchors; with
`force: true` it removes the node and strips every backlink in the same
commit. A branch with children refuses, `force` included. A dataset's
`.db` lands under `_derived/graveyard/<id>/`. A scoped principal pruning
an out-of-scope id receives `E_NOT_FOUND` byte-identical to absent, and
`force` refuses when an anchor lies outside the caller's scope,
reporting only a count. Covered by tests.

**F.86 (acceptance).** `forests()` and `GET /v1/forests` carry
`station` equal to the installed version, and the generated skill stamps
the same version and teaches the re-download check. A share link serves
the node's rendered markdown with no session; after revocation, expiry,
or the issuer's grant lapsing, the same URL answers the byte-identical
`E_NOT_FOUND` of a token that never existed; no endpoint returns the
token after creation. Covered by tests.

**F.87 (acceptance).** `look` on a node whose full digest exceeds
`BUDGET_LOOK` never returns an emptied `edges_out`/`edges_in` without
naming the field in `truncated_fields`; the clip order is `outline`,
`children`, the edges, then `sample_rows`; and a digest whose
edge lists survive intact does not name them. `stats.degree` equals the
true degree in every case. Covered by tests.

**F.88 (acceptance).** Sweep items carry `created` and `updated`; two
items with equal fusion scores order the more recently updated first;
and when one selected item `succeeds` another, the pair carries
`supersedes`/`superseded_by`. Declaring the succession changes the
J.10.7 reading fingerprint (a stored answer is not served across it).
Covered by tests.

**F.89 (acceptance).** `plant(node, dry_run=true)` on a valid node
answers `{valid: true}` and leaves the forest byte-identical — no file,
no commit, no catalog row, no heat; on an invalid node it raises the
exact envelope the real call would; and it requires `write` exactly as
the real call does. Covered by tests.

**F.90 (acceptance).** A node planted with `origin` returns it in
`look`; `scan(filter={"origin": …})` finds it; an `origin` with
whitespace or over 2048 chars is `E_SCHEMA`; and the engine performs no
I/O against the URI. Covered by tests.

**F.91 (acceptance).** `pick(section=[...])` items carry `header` equal
to the header line that matched, including when prefix matching resolved
a different string than was asked. Covered by tests.

**F.92 (acceptance).** With a reader pool of K ≥ 1, a read on a forest
whose writer lane is held (a write in progress, or an ingest step
running a curation call) completes without waiting for the writer;
`MONKEYLLM_STATION_READERS=0` restores single-lane behaviour; reads on
reader vines deposit pheromone and audit rows exactly as writer-lane
reads did. A sweep `answer`'s provider call runs on no forest lane: a
read on the same forest completes while the model is writing, the served
response is byte-identical in shape, and its `trace` and `vine` clock
carry only that call's own retrieval. Two cold asks run their model
calls concurrently (up to `MONKEYLLM_STATION_MODEL_CONCURRENCY`), and
`/v1/health` carries `concurrency: {readers, model}`. Covered by tests.

**F.93 (acceptance).** `GET .../export/{branch}?recursive=true` returns
a zip whose members are exactly the in-scope subtree, each byte-identical
to that node's single export; a scoped principal's zip omits what its
scan omits; `recursive=true` on a leaf and any unknown query parameter
answer `E_SCHEMA`. Covered by tests.

**F.94 (acceptance).** A scoped write's commit carries the
`station-principal:` trailer in its original commit (no amend: the sha
returned is the first sha created), and the Ranger's `run()` report
carries `gc`. Covered by tests.

**F.95 (acceptance).** `transplant` of a leaf moves the passport, keeps
`created`, rewrites every backlink, refreshes both parent indexes, and
lands in ONE commit; a local payload moves beside the new passport. The
new node carries `moved_from` and the old id in `aliases`; `locate` by
the old name finds the new node; a read of the old id answers `E_MOVED`
with `moved_to`. A branch, the root and `_meta/*` refuse. After
`reindex`, the waymark still answers (`moved_from` rebuilt it). Covered
by tests.

**F.96 (acceptance).** Under a policy, `transplant` refuses when any
backlink's holder is out of scope (count, never names), refuses a
destination outside the grant as `E_FORBIDDEN`, and a scoped read of a
waymark whose `moved_to` is out of scope answers the byte-identical
`E_NOT_FOUND` of a node that never existed. Covered by tests.

**F.97 (acceptance).** `history(id)` lists the node's commits newest
first with `at` carrying time of day, `action` parsed from the subject,
and `by` equal to the `station-principal:` trailer on host-stamped
writes; a transplanted node's history crosses the move unbroken;
`limit` and the 800-token budget truncate explicitly; out-of-scope and
absent answer identically. Covered by tests.

**F.98 (acceptance).** `plant` with a list validates every node before
writing any: a batch whose third node is invalid writes nothing and
names it; a valid batch of N lands N nodes in exactly ONE new commit; a
branch and its children succeed in one batch in order; `if_absent`
reports taken ids in `existing` without failing the batch; `dry_run`
rehearses the whole list and writes nothing; an in-batch duplicate id
and any `schema` node refuse. A single dict keeps the v0.57 shape to
the byte. Covered by tests.

**F.99 (acceptance).** With `B supersedes A` declared, a sweep matching
both returns B and not A, carries `superseded_excluded` naming A and B,
and still returns `k` items when candidates remain;
`include_superseded: true` restores A with its annotations and forms a
different store key. `locate` and `scan` still return A. A scoped caller
who cannot see B receives A unsuppressed. Covered by tests.

**F.100 (acceptance).** An adopted file's node carries `origin` as its
source `file://` URI; an upload with `source_url` carries that URL; an
upload without one carries no origin; a hand-set origin survives `sync`;
and a forest ingested before the rule gains origins on its next sync
without re-conversion. Covered by tests.

**F.101 (acceptance).** Two concurrent cold `answer`s with the same
question produce ONE provider call: the follower is served the leader's
stored reply with `cached: true` and its own retrieval fields. With
different questions they generate independently (F.92's concurrency
stands). A leader that errors releases followers to their own calls,
and `cache: false` never coalesces. Covered by tests.

**F.102 (acceptance).** The MCP surfaces serve `transplant` and
`history` (19 tools, named in the instructions — the J.1.2 parity test
counts them); `transplant` rides `write` and `history` rides `read`
under J.2.6's existing mask ceiling. Covered by tests.

**F.103 (acceptance).** `coverage()` on the fixture returns every branch
child of the root `_index` as a root, each with `nodes` equal to the
count of catalog rows under its prefix, plus `total`, `types`, `sources`
and `undated`; the sum of the roots' `nodes` accounts for every node in
the forest exactly once. It opens no file and issues no per-node query.
Under a branch-scoped policy the roots are that policy's own roots, every
count covers only nodes in scope, and the totals of an unrestricted call
are not derivable from it. `scope` narrows roots and totals alike.
Covered by tests.

**F.104 (acceptance).** For a root whose nodes were ingested, `coverage`
reports `origin` as a prefix that every one of those origins starts with,
and `scan(root, filter={"origin_prefix": <that value>}, recursive=true)`
returns exactly the nodes counted — the map's string is the read's string
with no arithmetic between them. A root with a mix reports
`without_origin` with the count that carries none; a forest with no
origins at all reports `without_origin` equal to its size and no
`origin`. `filter={"origin": <full URI>}` still matches that one node.
Covered by tests.

**F.105 (acceptance).** A source file `291-provider-budget.md` under
`back-end/` is ingested with **no** `aliases:` map and its node carries
`291`, `back-end/291` and `BE-291`; with the map declaring `back-end: BE`
the result is the same set and no doubled prefix. A file under a
single-word folder derives the number and the path form and **no**
letter prefix. A document whose title states `ADR-0002` carries it
whatever its folder, and a code appearing only in the body below the H1
is not derived. `locate` for any derived alias returns the node.
Covered by tests.

**F.106 (acceptance).** `plant(dry_run=true)` on a node with a 61-token
summary **and** a non-existent parent answers one envelope whose `code`,
`message` and `hint` are byte-identical to v0.58's, and whose `data.errors`
names both problems, the first entry repeating the envelope. A batch dry
run of 20 nodes with problems in nodes 3 and 17 reports both, each with
its `id` and `index`. A real `plant` still refuses at the first problem
and writes nothing. A valid dry run's success shape is unchanged.
Covered by tests.

**F.107 (acceptance).** `answer(question, min_evidence=2, min_score=0.02)`
against a sweep returning three items scoring below the threshold answers
`answer: null`, `reason: "insufficient_evidence"` naming `min_score` and
`min_evidence`, makes no provider call, is not billed and creates no
store entry. The same call with `min_score` absent behaves exactly as
v0.58. `min_score` does not enter the J.10.7 key: two otherwise identical
questions differing only in it hit the same entry. Covered by tests.

**F.108 (acceptance).** Every item of `answer`'s `sources[]` carries the
`trail` the sweep computed for that node, equal element-for-element to
the matching item's `trail` in the response's own `harvest`. The walk's
`sources[]` carries it for every node whose material arrived with one.
No additional read is issued to produce it. Covered by tests.

**F.109 (acceptance).** A warm `sniff` whose terms match no body loads no
catalog row and deserializes no record for the non-matching nodes, and
still reports `scanned_nodes` equal to the nodes covered; a warm `sniff`
whose terms match most of the forest issues a **bounded** number of heat
queries independent of the number of matching nodes; and in both cases
the response is byte-identical to the same call against a cleared memo —
same results, order, snippets, `match_count`, `truncated_matches`,
`scanned_nodes`. Covered by tests.

**F.110 (acceptance).** `GET /s/{token}` with `Accept: text/html` serves
the reading shell; the same URL with any other `Accept` returns exactly
the body of `GET /v1/share/{token}`. A revoked, expired, suspended or
never-existing token answers the byte-identical `E_NOT_FOUND` on both
paths and under both `Accept` values. The MCP surfaces serve `coverage`
(20 tools, named in the instructions — the J.1.2 parity test counts
them), riding `read` under J.2.6's existing mask ceiling. Covered by
tests.

**F.111 (acceptance).** A key carrying `{read, ingest}` generates a skill
whose `SKILL.md` instructs no `plant`, `graft`, `prune`, `transplant` or
`tend`, ships `references/saving.md` and no `references/writing.md`, and
is smaller than the single file it replaces. Every reference the
selection produced is named in the core together with the condition that
sends an agent to read it, and the core is a usable skill on its own.
Covered by tests.

**F.112 (acceptance).** Every call example in every generated file names
the forest as its first argument. No generated file contains a call
written without it. Covered by tests.

**F.113 (acceptance).** Two selected forests produce a routing table with
one row per forest carrying its id, its largest roots and the
capabilities the key holds there, built from `coverage`. One selected
forest produces no table, and the core teaches `coverage()` in its place.
Both files teach `forests()` as the first call. Covered by tests.

**F.114 (acceptance).** The default block selection equals the
capabilities of the key on the selected forests; a block included for a
capability the key does not carry names that capability in its first
line. Covered by tests.

**F.115 (acceptance).** The single-file assembly of a selection carries
the same instructions as the concatenation of the folder assembly of the
same selection. A principal holding `read` alone still reaches the
console, and the Station gains no endpoint for any of it (F.52 stands).
Covered by tests.

**F.116 (acceptance).** The Skills console reads its forests, blocks and
assembly from the address and writes every change back to it; reloading
that address reproduces the same files byte for byte, spends no model call
and commits nothing. The generated core names that address as the way to
rebuild itself, and states that installing is the operator's act. No MCP
tool and no HTTP route serves the skill.

**F.117 (acceptance).** A file uploaded to a forest, planted, and then
`prune`d, is NOT planted again by a later upload of a different file to
the same destination: that second call reports only its own entry, and
the pruned id stays absent. The prune moved that node's staged file into
`_derived/graveyard/<id>/source/` and said so (`staged_moved`), while a
node ingested from a host directory leaves its source untouched. The staged file of the earlier batch is
neither planted, refreshed nor reported `stale` by it. Re-uploading a name
whose passport still records it remains an update of that node, never a
second node. Covered by tests.

**F.118 (acceptance).** `look` on a `type: dataset` node whose local
payload file has been removed returns the passport title, summary,
tags, edges, `notes` with `payload_missing: true` and without
`query_manual` or `sample_rows`, instead of `E_NOT_FOUND`. `query` and
`tend` on the same node still refuse with `E_NOT_FOUND` naming the
payload. With the payload present, the response carries no
`payload_missing` and is byte-identical to the response before the
upgrade. Covered by tests.

**F.119 (acceptance).** `coverage` reports `payload_missing` per root and
in the totals, counting nodes whose LOCAL payload is absent and no remote
payload; under a policy the count is the policy's own. Covered by tests.

**F.120 (acceptance).** `ingest(dest: "x/_index")` and
`ingest(dest: "x")` land the same documents under the same branch, and
`dest: "_index"` means the forest root. The scope check (J.8) is applied
to the normalised destination, so a principal scoped to `x/` is refused
neither form and a principal scoped elsewhere is refused both. No
destination produces an id containing `/_index/`. Covered by tests.

**F.121 (acceptance).** Every upload answers `mode: "upload"` on the job
and on the report, first or hundredth, and no second field names a
mechanism. An upload leaves the forest's recorded `source_root` exactly as
it found it — a forest that mirrors `/data/handbook` still mirrors it
afterwards — and records none when it had none. A staged entry that became
a node is gone from the staging area when the batch settles and is named in
`consumed`; one that failed conversion is still there and is not. A source
outside the forest is never removed by an upload or by a `prune`. Covered
by tests.

**F.122 (acceptance).** After `transplant`, `pick` on the old id answers
`E_MOVED` carrying `moved_to`, exactly as `look`, `move`, `history`,
`view` and `query` do — and under a policy whose scope excludes the
destination, all six collapse to the byte-identical `E_NOT_FOUND` of an
absent node (C.15 rule 4). Covered by tests.

**F.123 (acceptance).** A source file `9router-free-ai-router.md` derives
no alias from its leading digit; `291-provider-budget.md` under
`back-end/` still derives `291`, `back-end/291` and `BE-291`. Covered by
tests.

**F.124 (acceptance).** `plant` and `graft` refusing an undeclared `type`
or `rel` return `E_SCHEMA` whose `hint` names the forest's declared set
and where it is declared. A forest whose `_meta/schema.md` omits a rel the
engine ships still refuses it — the authority is the file — and now says
what it would have accepted. Covered by tests.

**F.125 (acceptance).** `POST /v1/forests/{f}/recurate {derive:
["aliases"]}` on a forest whose nodes were ingested before a derivation
rule adds the missing derived aliases, never displaces a hand-written one,
opens no source file and calls no model, commits `.md` only with the
principal stamped, and reports `scanned`/`changed`/`aliases_clipped`. Run
twice, the second pass reports `changed: 0` and commits nothing. It
requires `admin` and is refused on a read-only Station. Covered by tests.

**F.126 (acceptance).** An `answer` refused by the floor carries
`below_min_score`: the number of content-carrying items that did not clear
`min_score`. With no threshold set the field is `0` and the refusal is
byte-identical to the one before the upgrade. Covered by tests.

**F.127 (acceptance).** Every `dest` in every generated skill file is a
form the server accepts; the saving block names `source_url` as what gives
an uploaded document its `origin`; the answer block states J.10.10 rule
8's pairing. Two different forest selections generate different `name:`
values, and the same selection reproduces its own. Covered by tests.

**F.128 (acceptance).** `GET /v1/admin/staging` reports the staged files no
live passport records — count, bytes and bounded names — and `POST` moves
exactly those into `_derived/graveyard/_staging/`, leaving a forest whose
uploads all landed reporting zero. A forest seeded with files an older
Station staged, whose nodes were pruned, reports them and can be swept. The
clear refuses with `E_LOCKED` while a batch runs on that forest, and both
verbs refuse a branch-limited admin. Covered by tests.

**F.129 (acceptance).** The fold is byte-identical to its own definition
lowercase and strip diacritics to the base character of the NFD
decomposition for **every** code point Python can represent, not for a
sample, and it preserves length everywhere (C.6b reports a position into
the original line). Cased astral scripts and CJK Compatibility Ideographs
fold like any other letter, and nothing at or above the table's limit folds
to anything but itself checked in bulk against the Unicode version in
use, so a later version cannot narrow the match in silence. A `sniff` finds
the same node in either case spelling of its term. Covered by tests.

**F.130 (acceptance).** The G.7 `content:` marker is read in the
frontmatter. A node whose frontmatter does not declare it and whose **body**
contains the line `content: cached` is scanned as the inline node it is,
and the second call the one served by the memo agrees with the first.
Covered by tests.

**F.131 (acceptance).** A cold `sniff` folds each body at most once, plus
once per term, and the fold table is built on first use: importing the
package builds nothing, and folding ASCII text builds nothing, because
ASCII needs no table. Covered by tests.

**F.132 (acceptance).** A binding created without a stated budget carries
1500, whatever its role; one created with a budget carries what was named.
The `answer` role's shipped default is 1500, and `ingest` and `vision` keep
theirs: a scent and a description do not carry the citation apparatus that
sized the number. Covered by tests.

**F.133 (acceptance).** A registry left by an older host with an `answer`
binding at exactly the shipped 600 reads 1500 after the next open; one at any
other value, and any other role at 600, is untouched. The repair runs once,
so an operator who binds 600 after it has run still reads 600 after every
later open. A registry created fresh is stamped current and applies no
repair. Covered by tests.

**F.134 (acceptance).** The prompt states the effective cap in tokens and in
words, in the sweep and on a walk alike, whether the number came from
`reply_tokens`, from the binding, or from the default. A call that sent no
`reply_tokens` still reports none: what the amendment adds to the prompt it
does not add to the response. Covered by tests.

**F.135 (acceptance).** The list of methods withheld under J.1.2 rule 4
names the two families that rule names and nothing else, and
`tools.listChanged` is `false` at 2025-06-18 and 2025-11-25 and `true` at
2026-07-28. The second assertion carries the first: at that era the SDK
derives the flag from whether the listen handler is served, so the flag
being `true` IS the handler being registered. Covered by tests.

The end-to-end shape — a client of that era completing its connection and
reading the same tool count an earlier-era client reads — is verified
against a released client rather than in the suite, because the response to
`subscriptions/listen` is an endless stream and the suite's in-process
client cannot hold one open without holding its own shutdown. That is a
limit of the harness and it is recorded here so the gap is a known one:
what the suite guards is that nobody deletes the handler again.

**F.136 (acceptance).** No request the MCP mount serves is answered 404
except one naming a session that no longer exists. A method the Station does
not serve is a JSON-RPC error under a 2xx status, and a test asks for one to
prove it. Covered by tests.

**F.137 (acceptance).** The Ask console's path panel (J.5.15) marks a node
in a stage only from material the host returned: a sweep whose `found_by`
carries `locate` marks the entry stage and one that does not, does not; a
sweep produces no `cited` stage at all while a walk with `answer_nodes`
produces one; and a trail segment is drawn only where BOTH ends are in the
J.11 projection this principal received. The retrieval preview, where rule 2
allows one, sends the same question, `k` and entry ranker as the answer
beside it, and the heat of every node is unchanged by it. Covered by tests.

**F.139 (acceptance).** The walk's whitelist (J.10.5) admits `coverage`: a
turn whose parsed call is `coverage` executes through `ScopedVine` like any
other hop, its result reaches the next turn in the same shape, and it is
recorded as a hop. The tool menu the loop states to the model names it —
a tool the model is never offered is a tool the whitelist did not admit. A
write primitive is still refused, whatever capabilities the caller holds.
Covered by tests.

**F.140 (acceptance).** A hop whose tool is `locate`, `sniff`, `scan` or
`move` carries `ids`: the ids that call returned, in result order, at most
ten, and a `scan` or `move` hop still carries the `id` it was addressed by.
A hop whose tool is `look`, `pick` or `query` carries the `id` it was given
and no `ids`. Each `hop` event of J.10.12 equals the corresponding
entry of the response's `hops` field for field, `ids` included — compared,
not asserted separately, which is F.138's comparison extended rather than a
second one. A record carrying no `ids` reads as an empty list and never as a
call that returned nothing. Covered by tests.

**F.141 (acceptance).** `answer(question, terms=[…])` reaches the sweep's
`sniff` leg with exactly those terms — the bundle reports the terms sent,
not the derived ones — and the J.10.7 entry it forms is keyed by them: two
sweeps differing only in `terms` are two entries. `terms` sent beside `hops`
is `E_SCHEMA` naming the parameter; a malformed list is refused in the same
words `harvest` refuses it, on the same rules (C.6c). A call carrying no
`terms` returns a byte-identical response and forms the same key as before
this version, so no stored entry is invalidated by the upgrade. Both
surfaces accept the parameter and the signature table declares it (C.12).
Covered by tests.

**F.142 (acceptance).** The Ask console fires no retrieval preview on a
walk. Checked in the console's own source, in the idiom F.111–F.116 use for
generated text: every path that starts the parallel `harvest` — the
immediate one and the fallback that stands in for an absent J.10.12 channel
— is reachable only when the walk switch is off, so a call carrying `hops`
starts none and its panel holds nothing until a `hop` event or the response
arrives. J.5.15 rule 9's drawing is deliberately not covered here: what a
canvas paints is not machine-readable, which is the boundary F.137 already
states, so dots-only, the branch colouring and its legend line are normative
text with no test behind them. Covered by tests.

**F.143 (acceptance).** A hybrid `locate`'s Part D event carries `embed_ms`
and its `elapsed_ms` covers it; the lazily embedded goal lands the field on
the hop that paid it, never on the `locate` that deferred it; and a call
that ran no embed emits an event with no such key — byte-identical to
v0.67. A memo hit still carries the field, near zero: the memo working is a
fact worth the bytes. Covered by tests.

**F.144 (acceptance).** `explain` forwards `embed_ms` on the step whose
event carries it and sums it as `trace.embed_ms` only when nonzero;
`retrieval_ms` and `total_ms` are unchanged to the byte, and a trace with
no embed anywhere carries no `embed_ms` at all. The step-shape guard
admits the new key beside the old five and nothing else. The panel's
net-of-embed rendering is normative text with no test, on F.142's stated
boundary. Covered by tests.

### J.12 Out of scope for Part J

Engine changes of any kind (contracts, budgets, ranking); per-node ACLs
finer than the branch prefix; row-level filtering inside datasets beyond
the table allow-list; multi-writer forests (the single-writer lock stands);
billing and metering beyond per-token quotas.

*Documented boundary (informative):* scoping is per node, and node bodies
are author-written prose. A body that names an out-of-scope node discloses
that id to anyone who may read the body the remedy is to keep such
references in the same scope, not to redact prose, which would corrupt the
content the forest exists to serve.

---

## Part K The Gauntlet (query-conditioned frontier, v0.21)

### K.0 Why it is not the entry search

Part C's `locate` answers *where do I start*. Parts C.3–C.5 answer *where
do I go next*, and they answer it without knowing what the forager is
looking for: `look` sorts edges by heat, `scan` sorts children by degree,
`move` does not sort. Heat is the memory of past hunts and degree is the
shape of the graph; neither is about **this** question.

The Gauntlet is the instrument that closes that gap a query-conditioned
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
Gauntlet the same order, the same fields, the same bytes. Absence is not
a degraded mode; it is the Phase 0 contract, unchanged.

### K.2 The goal, and why it costs nothing

The goal vector is the embedding of the most recent `locate`/`harvest`
query in the session: the forager picks the instrument up when the hunt
starts and carries it for every hop after. `locate` MUST embed the query
whenever the layer is ready **for the goal**, whether or not it also
fuses the result into its own ranking. That is one embedding per hunt, not
per hop, and it is the entire running cost.

That cost runs inside whichever traced primitive needed the vector —
`locate` at the entry, a hop's `look`/`move` when the goal embeds lazily —
and is therefore named there: the primitive's Part D event carries it as
`embed_ms` (v0.68), so the one network round trip on the read path can
never be read as the forest's own work.

The separation matters for exactly the reason K.1 gives: the query is
embedded so the forager can *navigate* with it, not so entry search can
re-rank with it. Each subsequent hop is a dot
product over vectors already stored in the Canopy no network call, no
model call, and no tokens in either direction.

A caller MAY override the goal per call with an explicit `toward` string;
the implicit goal is what makes the feature free, and the explicit one is
what makes it testable.

**The read path embeds the query and nothing else (normative, v0.42).**
`locate`, `harvest` and the Gauntlet's goal MUST NOT embed *nodes*.
Refreshing stale vectors inside a read was one caller paying an ingest's
bill: the work is proportional to what somebody else wrote, it is
unbounded, and it lands on whoever asks next inside the primitive with
the tightest budget in the document (F.6). Re-embedding is maintenance
(J.13.4), triggered and observable, exactly as the catalog rebuild is
(J.13.3).

The cost of that separation is stated plainly rather than hidden: until a
refresh runs, a newly written node is **absent from the dense half** of
hybrid ranking. It is not absent from the forest the catalog upsert is
synchronous, so BM25 finds it on the next call, and every structural
primitive already does. The debt is reported (K.4) so it can be chosen,
which is the whole difference between a trade-off and a surprise.

The goal is session state and MUST be observable, never silent: a response
whose order was conditioned MUST say so the primitive reports that its
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
control on an answering console would change nothing and a control that
changes nothing is worse than no control. What does change an answer is
K.1's other consumer: whether the vector layer is fused into entry search.
Calls that perform entry search (`locate`, `harvest`, `answer`) MUST
therefore accept an optional `hybrid` boolean, **defaulting to false on
every call**, for the same reason the opt-out exists: the published
degradation (R@1 1.00 → 0.40) has to be reproducible on the operator's own
corpus. It MUST NOT be sticky a request that omits it is a BM25 request,
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
model, the dense layer MUST be treated as **absent** hybrid `locate` off,
Gauntlet off, Phase 0 behaviour and the mismatch MUST be reported by the
forest's validation and by any surface that shows index status. Rebuilding
is the only resolution; a partial re-embed would leave the index in two
spaces at once.

**Status reports the debt (normative, v0.42).** The status surface of this
section MUST also carry `stale`: the number of nodes written since the
last build or refresh, and therefore absent from the dense half. It is
the number that predicts what a refresh costs and the only way an
operator can decide when to pay it; a layer that is quietly behind is
indistinguishable from one that is current.

### K.6 The embedding memo (v0.42)

`embed(model, text)` is a pure function of its inputs, so a Vine MAY
memoize it in the derived layer under exactly the C.6b.1 discipline:

- **Keyed by the model and the normalized text**, because a vector from
  one model in another model's space is the meaningless comparison K.4
  exists to prevent.
- **Only texts a caller supplies** queries, `toward` goals. A node's
  vector already has a home, the Canopy index itself, and storing it
  twice would make two answers to "what is this node's vector".
- **Disposable and bounded.** It lives in `_derived/`, may be dropped at
  any moment with no effect but latency, and MAY be evicted
  least-recently-used (H.6 is the precedent).
- **Never a substitute for the index.** A memo hit skips a round trip;
  it never makes an absent or mismatched index look present (K.4 stands
  ahead of it).

### K.5 Out of scope

Re-ranking node *bodies* (that is `sniff`'s job and it is literal by
contract); replacing heat with proximity (they answer different questions
and H's pheromone economics depend on heat remaining a memory); and any
behaviour that makes navigation *require* an embedder.
