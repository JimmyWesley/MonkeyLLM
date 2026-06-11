"""Deterministic 100-document mixed dump for the T04 curation measurement.

Generates `dump-ingest/` (git-ignored): a realistic brownfield directory —
markdown articles, plain-text notes, CSV/JSON tables — for a fictional
company ("Toucan Robotics", English content). The Gardener adopts this tree
and the curation acceptance criterion (>= 95% LLM summaries passing A.4) is
measured by scripts/measure_curation.py.

    python scripts/build_dump.py [--out dump-ingest]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from pathlib import Path

PROJECTS = ["falcon-arm", "heron-vision", "ibis-gripper", "kite-navigation",
            "lark-telemetry", "owl-inspection", "swift-conveyor", "tern-docking"]
PEOPLE = ["Alice Norden", "Bruno Vask", "Carla Ostrov", "Daniel Reim",
          "Edith Solano", "Frederico Lanz"]
CITIES = ["Rotterdam", "Porto", "Gdansk", "Valencia", "Lyon", "Tampere"]
COMPONENTS = ["torque sensor", "depth camera", "servo driver", "battery pack",
              "edge controller", "lidar module"]
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]


def md_article(rng: random.Random, i: int) -> tuple[str, str]:
    project = rng.choice(PROJECTS)
    person = rng.choice(PEOPLE)
    city = rng.choice(CITIES)
    component = rng.choice(COMPONENTS)
    pct = rng.randint(3, 38)
    units = rng.randint(40, 900)
    quarter = rng.choice(QUARTERS)
    title = f"{project.replace('-', ' ').title()} — {quarter} 2026 update"
    body = f"""# {title}

The {project} line closed {quarter} 2026 with {units} units shipped from the
{city} plant, a {pct}% increase over the previous quarter. {person} leads the
workstream and reported that the {component} supplier renegotiation cut unit
cost by {rng.randint(2, 14)}%.

## Risks

The main open risk is the {rng.choice(COMPONENTS)} lead time, currently at
{rng.randint(4, 16)} weeks. Mitigation: a second source is being qualified in
{rng.choice(CITIES)}.

## Next steps

- Field test batch {rng.randint(10, 99)} with {rng.randint(3, 12)} pilot customers.
- Review the {quarter} retro with {rng.choice(PEOPLE)} before the next steering.
"""
    return f"projects/{project}/{quarter.lower()}-2026-update-{i:02d}.md", body


def txt_note(rng: random.Random, i: int) -> tuple[str, str]:
    person = rng.choice(PEOPLE)
    topic = rng.choice(["budget", "hiring", "tooling", "compliance", "training"])
    body = (f"Note {i:02d} — {topic} call with {person} on 2026-{rng.randint(1, 6):02d}-"
            f"{rng.randint(1, 28):02d}.\n\nAgreed: {person} owns the {topic} plan "
            f"for {rng.choice(PROJECTS)}; review in {rng.randint(2, 8)} weeks. "
            f"Open question: {rng.choice(COMPONENTS)} certification scope.\n")
    return f"notes/{topic}/note-{i:02d}.txt", body


def csv_table(rng: random.Random, i: int) -> tuple[str, str]:
    rows = [["order_id", "customer", "city", "units", "amount_eur"]]
    for n in range(rng.randint(12, 40)):
        rows.append([f"ORD-{i:02d}{n:03d}", f"Customer {rng.randint(1, 30)}",
                     rng.choice(CITIES), rng.randint(1, 25),
                     round(rng.uniform(800, 42000), 2)])
    out = "\n".join(",".join(str(c) for c in row) for row in rows) + "\n"
    return f"sales/orders-batch-{i:02d}.csv", out


def json_table(rng: random.Random, i: int) -> tuple[str, str]:
    data = [{"ticket": f"TK-{i:02d}{n:02d}", "project": rng.choice(PROJECTS),
             "severity": rng.choice(["low", "medium", "high"]),
             "hours_to_close": rng.randint(1, 96)}
            for n in range(rng.randint(8, 25))]
    return f"support/tickets-{i:02d}.json", json.dumps(data, indent=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dump-ingest")
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    rng = random.Random(2026)

    files: list[tuple[str, str]] = []
    files += [md_article(rng, i) for i in range(60)]
    files += [txt_note(rng, i) for i in range(25)]
    files += [csv_table(rng, i) for i in range(10)]
    files += [json_table(rng, i) for i in range(5)]

    for rel, body in files:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8", newline="\n")
    print(f"{len(files)} files -> {out}")


if __name__ == "__main__":
    main()
