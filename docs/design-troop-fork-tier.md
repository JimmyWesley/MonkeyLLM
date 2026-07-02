# Design — T03 fork-tier: giving the troop something to fork

Status: IMPLEMENTED + MEASURED 2026-07-02 — see "Fork-tier results" in
tasks/T03-troop-orchestrator.md for the outcome (criterion not met; stop-
policy trade-off mapped; a fourth policy, `coverage`, was added during
measurement). Kept as the design record. Follow-up to T03's honest verdict:
on single-chain questions the troop is an accuracy amplifier (judge
arbitration), not a speed amplifier — parallelism only pays when the
frontier genuinely forks. This design creates that fork and re-measures.

No spec bump needed: the bench and the troop are orchestrator-side clients
(spec Part E architecture note in T03); no primitive contract changes.

## Pre-step 0 — regenerate the stale question file

`bench/questions-v3.json` on disk is Portuguese output from before the
English normalization; `build_bench_forest.py` already emits English.
Regenerate the bench forest + question files before anything else, or v3/v4
comparisons will be measured against mismatched-language artifacts.

## Part A — questions-v4: the fork tier (`build_questions_v4`)

New generator function in `forests/scripts/build_bench_forest.py`, same
shape as v3 plus one field: `fork_width` — the number of *independent*
sub-chains a correct answer requires. v3 questions are all `fork_width: 1`
(one pinned chain); v4 targets `fork_width >= 2`. Five question shapes, all
answerable from ground truth the generator already holds:

1. **Shared-feature fork (width 2)** — v3 deliberately *excludes* releases
   whose feature appears in >1 project (`feat_counts[feature] == 1`); v4
   uses exactly those rejects: "Two projects shipped <shared feature
   paraphrase> in April — which ones, and who leads each?" Expected nodes =
   both release→vision→lead chains. Natural 2-way fork with zero new
   universe content.
2. **Union over incidents (width = #recalls)** — "Which cities do the
   technical owners of the 2026 recalled products live in?" One
   independent recall→product→owner chain per incident.
3. **Filter over a client set (width ~ set size, capped)** — "Which of the
   field clients bought <product family> in the first semester?" Requires
   visiting several `organizations/field-clients/*` contract chains;
   answer is the qualifying subset.
4. **Negation over projects (width = #projects)** — "Which project shipped
   no April release?" Must enumerate the project set; no single chain can
   prove a negative.
5. **Attribute scan over people (width ~ #leads)** — "Among the project
   leads, who came from <institute>?" The institute lives only in person
   nodes; entry is ambiguous by construction.

Scoring works unchanged: `answer_contains` lists ALL required atoms (both
leads, every city, the qualifying clients), and the existing
`correct_text = all(contains)` check handles unions. `expected_nodes` is
the union of all sub-chain nodes; `banana_precision` keeps its meaning.

Target: 8–10 v4 questions, `fork_width` 2–4, `min_hops >= 3` per sub-chain.

## Part B — stop discipline (`troop/orchestrator.py`)

T03 documented a near-miss: the FIRST confident answer sets the stop flag,
and in v3-11 the first answer was wrong. On fork questions this gets worse —
a monkey finishing one sub-chain must not kill the monkeys walking the
others. Make the policy explicit and measurable:

```
stop_policy: "first" | "quorum" | "none"   (troop param, bench flag)
```

- `first` — current behavior, kept for comparison.
- `quorum` — stop only when >= ceil(n/2) monkeys have answered. Default for
  the fork tier.
- `none` — every monkey runs to its own answer/budget; judge sees all.

Judge synthesis is already union-friendly (it reads all harvests); no judge
change needed beyond receiving more complete reports.

## Part C — work-stealing on the frontier

Today each monkey gets exactly one `locate(k=n)` entry and exits when done.
For `fork_width > n` (and for early finishers on width-2 questions with
n=3), add: a monkey that answers its sub-chain pulls the next *unvisited*
frontier item (from the same scout `locate`, extended to `k=max(n,
fork_width_estimate)` — in practice `k=2n`) and keeps hunting until the
stop policy fires. The shared visited-cache already prevents duplicate
work; this just reuses it as the work queue's dedup.

## Part D — bench integration and re-measurement

- `run_bench.py`: accept `--questions bench/questions-v4.json` (already
  generic), add `--stop-policy`, and report the per-question-class
  breakdown T03's 4th criterion asks for: single-chain (v3) vs fork (v4).
- Arms in one run: monkey (N=1) vs troop (N=3, quorum) on the same v4 set.
- **Acceptance re-measure (T03 criterion 1):** N=3 cuts median wall-clock
  >= 35% vs N=1 on `fork_width >= 2` questions, total tokens <= 2.5x.

### Why the speedup should exist now (hypothesis, to be measured)

A solo monkey on a width-3 question walks 3 sub-chains *sequentially*
(~3x steps); the troop walks them concurrently. Upper bound ~3x minus judge
overhead and shared-decode contention. Note the serving change since the
2026-06-11 measurement: via OpenRouter the N streams don't share a single
3090's decode throughput — the GPU-contention confound in the original
FAILED measurement disappears. Worth re-running the v3 (single-chain) arm
too, to see how much of the 3.3x wall-clock penalty was contention vs
genuine extra navigation.

## Execution order

1. Regenerate bench forest + v3 questions (fixes stale PT file).
2. `build_questions_v4` in the generator (+ `fork_width` field).
3. `stop_policy` + work-stealing in `troop/orchestrator.py` (+ tests
   mirroring tests/test_troop.py's zero-duplicate-look check under
   stealing).
4. Bench flags + per-class report.
5. Measure; update T03 Results with the honest verdict either way.

## Out of scope (unchanged from T03)

Adaptive troop sizing; `troop_hunt` as an official MCP tool (that promotion
requires a spec version first).
