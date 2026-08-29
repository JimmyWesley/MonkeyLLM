# `questions-locate-v1` — the evaluation set that can move

Companion to `questions-locate-v1.json`. Written for T17
(`ideias/locate-sniff/04-tasks/T17-locate-evaluation-set.md`).

## Why it exists

Run against unmodified `develop` on 2026-08-28, the three sets that existed
scored:

| set | questions | nodes | recall@1 | MRR |
|---|---:|---:|---:|---:|
| fixture / `examples/demo/questions.json` | 10 | 82 | **1.000** | **1.000** |
| wide-forest / `questions-wide.json` | 24 | 246 | **1.000** | **1.000** |
| bench-forest / `questions-v2.json` | 18 | 154 | 0.778 | 0.866 |

Two at the ceiling; the third resolves one question. No change to `locate`
could be shown to help or hurt. This set exists to make that possible.

## The corpus

`forests/idie-findleads-docs` — 1,877 nodes, ~7.8 MB, mostly Portuguese
engineering tasks (`tasks/back-end`, `tasks/workers`, `tasks/findleads/*`,
`tasks/incidentes-sistemicos`, …) plus an ingest of the MonkeyLLM repo
itself.

**It is not in this repository.** `forests/` is gitignored and that corpus
is an ingest of material we do not ship. `bench_locate.py` skips with exit 0
when the forest is absent, so CI does not break; whoever holds the corpus
can run the set. Choosing a real, uneven corpus over a generated one was
deliberate: a synthetic forest built to contain the four classes below
measures what its generator put there.

**It has been written to since the baseline.** `recurate` ran on
2026-08-28, taking `aliases` from 0% to 93.7% of nodes. The pre-`recurate`
state is reproducible from the same catalog by blanking the `aliases`
column of `nodes_fts` — which is how the experiment at the end of this
document was run.

## Baseline (unmodified `develop`, 2026-08-28)

```
recall@1  0.711   recall@3  0.756   recall@5  0.778   MRR  0.734
p50 1.9 ms   p95 2.6 ms

class                n  recall@1  recall@3  recall@5    MRR
grammar             15     0.533     0.533     0.533  0.533
index_vs_content    15     0.933     1.000     1.000  0.967
inflection          15     0.667     0.733     0.800  0.702
silence             15     0/15 answered with nothing
```

0.711 is inside T17's target band [0.6, 0.9]: room to improve, room to
regress, and the classes disagree with each other, which is what makes the
aggregate worth reading.

### Current (spec v0.70 + `recurate`, 5 classes, 75 questions)

```
recall@1  0.833   recall@3  0.850   recall@5  0.867   MRR  0.843
p50 0.7 ms   p95 1.4 ms

class                n  recall@1  recall@3  recall@5    MRR
code_lookup         15     1.000     1.000     1.000  1.000
grammar             15     0.600     0.600     0.667  0.617
index_vs_content    15     1.000     1.000     1.000  1.000
inflection          15     0.733     0.800     0.800  0.756
silence             15     1/15 answered with nothing
```

## The five classes

**`inflection` (15)** — the question uses a form the target document does
not. `locate` tokenizes with `unicode61`, which does no stemming, so
"idempotente" and "Idempotência" are different terms. This is what the
prefix leg (T18) targets; without this class it is invisible.

**`index_vs_content` (15)** — the target is a content node inside a branch
whose `_index` matches as well or better. Already at 0.933, so on this
corpus the `_index` demotion proposed as L4 has less to win than the
bench-forest q03 suggested.

**`grammar` (15)** — the question is written as a person speaks. It was the
worst class at 0.533, with 7 of 15 falling out of the top-5 entirely,
because `locate` sent the raw question to FTS5 and ORed every token. Spec
v0.70 (C.1.2) derives terms first and it is 0.600 now — still the worst,
so still where the headroom is.

**`code_lookup` (15)** — the query IS an identifier (`DT-038`, `INC-004`),
which is how an agent that read a citation returns to the document and how a
person looks up a ticket somebody mentioned. Added after the first version
of this set could not see the `recurate` backfill at all. It is split
deliberately:

- **control (cod01-cod08)** — the code appears in the document's own
  hand-written title, so it was findable before any alias existed (title
  carries BM25 weight 4.0).
- **treatment (cod09-cod15)** — the title carries only the number
  (`038 — Chat Sidebar…`); the code exists solely as a derived alias, and
  the derived initials match what the team actually writes.

**`silence` (15)** — `expected_nodes: []`. The forest genuinely does not
hold office leases, ISO 14001, vehicle fleets or TikTok campaigns
(verified with `sniff` over bodies, not with `locate`; the three near
misses were substring artefacts — "SAP" inside "What**sap**p", "TikTok"
inside "**tiktok**en"). Scored apart from recall: a silence and a hit are
not the same event and averaging them hides both.

## What the silence class found immediately

**`locate` returned results for all 15.** It never answers nothing to a
natural-language question, because it ORs every term and any grammar word
matches something.

And the score does not carry the difference either. `Vine.locate` normalises
`strength` against the best hit **in its own result set**
(`r["rank"] / best`), so the top result is **1.000 for every question in
this set** — the ones the forest answers well and the ones about vehicle
fleets alike. An agent reading the response has no signal separating "this
is exactly it" from "these are the five least irrelevant things I found".

The absolute BM25 underneath *does* carry it, and is discarded:

| class | median raw bm25 | best | worst |
|---|---:|---:|---:|
| index_vs_content | -39.11 | -63.08 | -16.03 |
| inflection | -27.28 | -39.97 | -12.50 |
| grammar | -24.59 | -48.58 | -16.31 |
| **silence** | **-11.54** | **-18.55** | **-5.54** |

(lower is better in SQLite's bm25). All 45 answerable questions score below
the silence median. The distributions overlap at the edge but are plainly
different — the information exists and the contract throws it away.

This is C.1.1 from the other side. C.1.1 (v0.52) made the *empty* result say
what it searched, because an agent read `[]` as "the forest does not know".
This set shows the empty path is almost never taken for a real question, and
that the non-empty one always looks maximally confident. **Not proposed
here** — it is a contract change with no spec, and it wants its own round.

## Rules the set was written under

1. **`expected_nodes` never came from running a search.** Documents were
   chosen by structural position (branch listings, not queries), read, and
   the question written from what the document says. A set labelled from
   search output scores 1.000 by construction — the most likely explanation
   for the two saturated sets above.
2. **No question was tuned after seeing its score.** The baseline is the
   first run.
3. Silence topics were verified by `sniff` over bodies — the strongest
   available evidence of absence — and each near miss inspected by hand.

## Running it

```bash
.venv/bin/python scripts/bench_locate.py --forest forests/idie-findleads-docs --questions bench/questions-locate-v1.json
```

## Known limits

- **One corpus, one dialect.** Portuguese engineering tasks. A second set
  over a different corpus would measure something this one cannot.
- **No human relevance judgements.** `expected_nodes` is one author's
  reading of which document answers the question. For most questions the
  target names a specific fact (an endpoint, an error class, a count) that
  lives in one document; where it does not, the judgement is arguable.
- **BM25 only.** The dense layer was off (`hybrid_locate` defaults false).
  Set `MONKEYLLM_EMBED_ENDPOINT` and build the canopy for the hybrid row.


## The natural experiment this class was built for

Running `recurate` on the corpus (aliases 0% -> 93.7%) moved the aggregate
by **nothing**: 0.778 before, 0.778 after, every class identical. The four
original classes are all natural language and not one contains a code, so
the backfill was invisible to the instrument that had just been built to
measure `locate`.

`code_lookup` is that missing axis. Measured on the same catalog with the
`aliases` column blanked (the pre-`recurate` state) against the live one:

| group | without aliases | with aliases |
|---|---:|---:|
| control — code in the title | **1.000** | 1.000 |
| **treatment — code only as a derived alias** | **0.000** | **1.000** |

The control is what makes the treatment readable: it is unchanged, so the
jump is the aliases and not the measurement.

## What building the class exposed

Two defects in `derive_aliases`, neither of which the bare-number analysis
found, because both are in the *letter* form:

**Derived codes collide across depth.** `_folder_initials` reads only the
last path segment, so `tasks/back-end` and `tasks/findleads/back-end` both
derive `BE`. Of 1,148 distinct letter codes in the corpus, **376 (33%)
point at more than one node**, covering 795 nodes. `BE-005` reaches four
documents across two products. Worse, `QA-2026` reaches **26** — a date in
a title (`qa-2026-05-30`) read as a code by the self-code pattern.

**Derived initials disagree with the team's convention.** Comparing the
`LETTERS-`prefix the team actually writes in titles against what the engine
derives, over the ten folders where the convention is visible: **six agree,
four do not** — `incidentes-sistemicos` is INC to the team and IS to the
engine, `machine-access-api` is MA and MAA, `harness-ux` is HX and HU,
`providers` is PV and nothing. Where they disagree the alias is dead weight:
nobody types `IS-001`.

Both have the same repair and G.2.6 already names it — the operator's
`aliases:` map in `gardener.yaml`, which is **empty** on this forest. Fill
it and re-run `recurate`; union semantics add the correct forms without
displacing anything. This is why the questions above use only codes that
are unique AND follow the team's real convention: a set built on ambiguous
codes would measure the ambiguity instead of the retrieval.
