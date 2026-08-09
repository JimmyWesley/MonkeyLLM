#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Build `forests/wide-forest` — a corpus with a realistic branching factor.

Every forest in this repository is hand-built and *narrow*: the fixture has
a mean degree of 2.3 and a maximum of 11, and no node anywhere exceeds
`look`'s 12-edge cap. On such a corpus the forager almost never chooses
among more than three neighbours, so any measurement of frontier ranking
measures a floor, not a mechanism (the same shape as the paper's §6.4
finding about pheromone).

Real corpora are not like that. The Gardener mirrors folders, so a `docs/`
directory with 200 files becomes one branch with 200 children — and `scan`
then returns roughly seventeen of them, cut by the 800-token budget and
ordered by *degree*, which is ~1 for everything freshly ingested. The
forager sees 17 of 200 chosen by nothing.

This generator reproduces that shape so Part K can be measured honestly:

- wide branches (default 60 children each), like an adopted folder
- siblings that are **topically close**, so the discriminating information
  is in the summary rather than in the title — a corpus where every
  sibling is obviously distinct would make any ranker look good
- questions whose answer is one specific sibling, with lexical overlap
  spread across several of them, so `locate` lands on the right *branch*
  and the remaining work is genuinely frontier choice

Usage:
    python forests/scripts/build_wide_forest.py [--out DIR] [--per-branch N]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from monkeyllm.parser import serialize_node  # noqa: E402

TODAY = date.today().isoformat()
CREATED = "2026-01-15"

SCHEMA_MD = """# Forest dialect

> Node and edge types valid in this forest.

## Node types

- `branch` — a region index
- `note` — a short written note
- `document` — an adopted document

## Edge types

- `part-of` — structural containment
- `related-to` — a curated cross reference
"""

# Four regions, each the kind of folder an operator actually adopts. The
# `topic` words appear in EVERY sibling of the region on purpose: that is
# what makes the region easy to find and its interior hard to choose from.
REGIONS = [
    {
        "id": "runbooks",
        "title": "Runbooks",
        "topic": "runbook incident on-call procedure escalation",
        "kinds": ["database failover", "cache eviction storm", "certificate expiry",
                  "queue backlog", "disk pressure", "region evacuation",
                  "token leak", "clock drift", "DNS propagation", "rate-limit breach"],
        "systems": ["billing", "checkout", "search", "identity", "media", "notifications"],
    },
    {
        "id": "policies",
        "title": "Policies",
        "topic": "policy rule compliance approval requirement",
        "kinds": ["expense approval", "data retention", "vendor onboarding",
                  "access review", "travel booking", "incident disclosure",
                  "device encryption", "contractor access", "records disposal",
                  "third-party audit"],
        "systems": ["engineering", "finance", "legal", "support", "sales", "people"],
    },
    {
        "id": "decisions",
        "title": "Decision records",
        "topic": "decision record rationale trade-off chosen alternative",
        "kinds": ["storage engine", "message bus", "auth protocol", "deploy strategy",
                  "schema migration", "caching layer", "observability stack",
                  "feature flagging", "build system", "test strategy"],
        "systems": ["platform", "mobile", "web", "data", "infra", "ml"],
    },
    {
        "id": "reports",
        "title": "Quarterly reports",
        "topic": "report quarter summary metric variance outcome",
        "kinds": ["headcount", "churn", "latency", "revenue", "uptime", "spend",
                  "adoption", "backlog", "satisfaction", "conversion"],
        "systems": ["q1-2025", "q2-2025", "q3-2025", "q4-2025", "q1-2026", "q2-2026"],
    },
]

# Each answer is a fact that exists in exactly one sibling. The question
# deliberately avoids the sibling's naming fields where it can, so the work
# is not a title match.
FACTS = [
    ("the on-call engineer pages the {system} owner after {n} minutes without acknowledgement",
     "After how many minutes does an unacknowledged {kind} page escalate to the {system} owner?"),
    ("the documented recovery target for this path is {n} minutes",
     "What is the recovery target for the {kind} path in {system}?"),
    ("approval above {n} thousand requires a second signature from {system}",
     "Above what amount does {kind} need a second signature in {system}?"),
    ("records under this rule are kept for {n} months and then destroyed",
     "How long are {kind} records kept in {system} before destruction?"),
    ("the chosen option was rejected once before, in the {n}th review",
     "In which review was the {kind} choice for {system} previously rejected?"),
    ("the measured variance against plan was {n} percent",
     "What was the variance against plan for {kind} in {system}?"),
]


def build(per_branch: int) -> tuple[list[dict], list[dict]]:
    nodes: list[dict] = []
    questions: list[dict] = []

    for region in REGIONS:
        made = 0
        for kind in region["kinds"]:
            for system in region["systems"]:
                if made >= per_branch:
                    break
                slug = f"{kind.replace(' ', '-')}-{system.replace(' ', '-')}"
                node_id = f"{region['id']}/{slug}"
                title = f"{kind.title()} — {system}"
                fact_tpl, question_tpl = FACTS[made % len(FACTS)]
                n = 5 + (made * 7) % 90
                fact = fact_tpl.format(system=system, n=n)
                nodes.append({
                    "id": node_id,
                    "type": "document",
                    "title": title,
                    # Every summary carries the region topic, so BM25 can find
                    # the region and cannot separate the siblings by it.
                    "summary": (f"{region['topic'].split()[0].title()} for {kind} in "
                                f"{system}: scope, owners and thresholds. {fact.capitalize()}."),
                    "tags": [region["id"], system],
                    "body": (f"# {title}\n\n"
                             f"Scope: {kind} affecting {system}.\n\n"
                             f"## Detail\n\n{fact.capitalize()}.\n\n"
                             f"## Owners\n\nThe {system} group owns this document.\n"),
                })
                if made % 10 == 3:      # one question per ten siblings
                    questions.append({
                        "id": f"{region['id']}-{made:03d}",
                        "question": question_tpl.format(kind=kind, system=system, n=n),
                        "expected_nodes": [node_id],
                        "answer_contains": [str(n)],
                    })
                made += 1
            if made >= per_branch:
                break
    return nodes, questions


def write(out: Path, nodes: list[dict]) -> None:
    (out / "_meta").mkdir(parents=True, exist_ok=True)
    # The dialect is itself a node, so it carries a passport like everything
    # else — `validate` rejects a bare markdown file here, and rightly.
    (out / "_meta" / "schema.md").write_text(
        serialize_node(
            {"id": "_meta/schema", "type": "note", "title": "Forest dialect",
             "summary": ("Node and edge types valid in this forest. New types are "
                         "declared here before first use; the Vine rejects anything "
                         "not declared."),
             "created": CREATED, "updated": TODAY},
            SCHEMA_MD),
        encoding="utf-8", newline="\n")

    for n in nodes:
        fm = {"id": n["id"], "type": n["type"], "title": n["title"],
              "summary": n["summary"], "tags": n["tags"],
              "created": CREATED, "updated": TODAY, "source": "ingest"}
        path = out / f"{n['id']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_node(fm, n["body"]), encoding="utf-8", newline="\n")

    for region in REGIONS:
        kids = [n for n in nodes if n["id"].startswith(f"{region['id']}/")]
        entries = "\n".join(f"- [[{k['id']}]] — {k['summary'][:70]}…" for k in kids)
        fm = {"id": f"{region['id']}/_index", "type": "branch", "title": region["title"],
              "summary": (f"{region['title']}: {len(kids)} documents covering "
                          f"{region['topic'].split()[0]} material across teams."),
              "coverage": f"{len(kids)} bananas, 0 sub-branches",
              "created": CREATED, "updated": TODAY, "source": "ingest"}
        body = (f"# {region['title']}\n\n> {fm['summary']}\n\n"
                f"## Sub-branches\n\n## Direct bananas\n\n{entries}\n\n## Cross trails\n")
        (out / region["id"] / "_index.md").write_text(
            serialize_node(fm, body), encoding="utf-8", newline="\n")

    subs = "\n".join(
        f"- [[{r['id']}/_index]] — {r['title']} "
        f"({len([n for n in nodes if n['id'].startswith(r['id'] + '/')])} bananas)"
        for r in REGIONS)
    fm = {"id": "_index", "type": "branch", "title": "Wide Forest",
          "summary": ("Master branch of a deliberately wide corpus: few regions, "
                      "many near-identical siblings inside each."),
          "coverage": f"0 bananas, {len(REGIONS)} sub-branches",
          "created": CREATED, "updated": TODAY, "source": "ingest"}
    (out / "_index.md").write_text(
        serialize_node(fm, f"# Wide Forest\n\n> {fm['summary']}\n\n"
                           f"## Sub-branches\n\n{subs}\n\n## Direct bananas\n\n"
                           "## Cross trails\n"),
        encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(REPO / "forests" / "wide-forest"))
    ap.add_argument("--per-branch", type=int, default=60)
    args = ap.parse_args()

    out = Path(args.out)
    nodes, questions = build(args.per_branch)
    write(out, nodes)

    qpath = REPO / "bench" / "questions-wide.json"
    qpath.write_text(json.dumps(questions, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")

    print(f"wide forest at {out}: {len(nodes)} documents in {len(REGIONS)} branches "
          f"({args.per_branch} each)")
    print(f"{len(questions)} questions at {qpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
