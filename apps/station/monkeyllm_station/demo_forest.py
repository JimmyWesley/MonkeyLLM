# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""The seeded demo forest offered at first-run setup (spec J.2.4).

An empty console teaches nothing: `Ask` has nothing to answer, `Explore` has
nothing to draw, and the first impression of a knowledge product is a blank
page. This plants a forest small enough to read in a minute and shaped to
show what the primitives actually do — a branch tree to `move` through,
bodies that only `sniff` can reach, and a cross trail that is not part of
the hierarchy.

**Why it lives here and not in the engine.** A forest is content, and the
engine carries no vocabulary of its own — `src/monkeyllm/` must work on
anybody's forest, so it cannot ship one. Onboarding is the host's concern,
which puts the generator in the Station.

**Why a generator and not files.** Forests are never edited in place and
never committed: the artifact is the code that builds one. This calls only
public primitives, so what it produces is exactly what a client could have
planted, and it stays correct when the dialect changes.

Runnable both ways — the setup screen calls `build_demo`, and an operator
with a shell can do the same thing by hand:

    python -m monkeyllm_station.demo_forest --forest /forests/demo
"""

from __future__ import annotations

import argparse
from pathlib import Path

TITLE = "Demo forest"
SUMMARY = ("A small forest that explains MonkeyLLM by being one — "
           "branches to walk, bodies to search, one cross trail.")

# Branches first: a node's parent must exist when it is planted. A branch
# id is the folder plus `/_index` (Part B addressing), and that id — not
# the bare folder name — is what its children name as their parent.
BRANCHES = [
    ("navigation/_index", "Navigating a forest",
     "How an agent moves through the map: the primitives, in the order a "
     "hunt actually uses them."),
    ("curation/_index", "Curating a forest",
     "How material enters and stays healthy: ingest, the passport, and the "
     "maintenance that follows."),
    ("governance/_index", "Governing a forest",
     "Who may see what, and how a deployment is administered."),
]

NOTES = [
    ("navigation/scent-before-flesh", "navigation/_index", "concept",
     "Scent before flesh",
     "Every node carries a short passport; bodies are only read on demand.",
     ["scent", "budget"],
     [],
     "A passport is the title, the summary and the tags — about 0.1% of the "
     "source material. An agent reads passports to decide where to go and "
     "pays for a body only once it has decided. That is what lets a small "
     "model work a large corpus: the map is cheap and the territory is not.\n\n"
     "The budget is always explicit. When a response is cut, it says so with "
     "`truncated: true` rather than silently returning less."),

    ("navigation/locate-and-sniff", "navigation/_index", "concept",
     "locate and sniff do different jobs",
     "locate searches curated metadata; sniff searches bodies. Never the same "
     "thing.",
     ["retrieval", "bm25"],
     [],
     "`locate` ranks passports with BM25 — it answers \"where might this "
     "live?\". `sniff` is a literal search inside bodies, no regex, and it "
     "answers \"which node actually says this word?\".\n\n"
     "A fact buried in a body is invisible to `locate` by design. Try it: "
     "`locate(\"pangolin\")` returns nothing at all, because no passport in "
     "this forest mentions the animal — while `sniff([\"pangolin\"])` walks "
     "straight to the body that does."),

    ("navigation/one-shot-harvest", "navigation/_index", "concept",
     "harvest, for models that cannot walk",
     "One deterministic sweep that returns the relevant material without any "
     "model in the loop.",
     ["harvest", "retrieval"],
     [("related-to", "navigation/locate-and-sniff")],
     "Not every client can navigate. `harvest` runs locate and sniff in one "
     "pass and returns what it found, with zero LLM calls on the way — the "
     "one-shot door for bring-your-own-model clients.\n\n"
     "A stronger model ignores it and walks the primitives instead, which "
     "finds things a single sweep cannot."),

    ("curation/the-passport", "curation/_index", "concept",
     "What ingest actually produces",
     "Documents become passports: a summary, tags and links, with the "
     "original left where it was.",
     ["ingest", "gardener"],
     [("related-to", "navigation/scent-before-flesh")],
     "Ingest does not copy your files into the forest. It reads them, writes "
     "a passport for each, and records where the original lives. The map "
     "stays small and versioned; the bytes stay put.\n\n"
     "Curation always sees the full text, even when the body will not be "
     "stored — a summary written from a truncated document is a summary of "
     "the wrong thing."),

    ("curation/never-edited-in-place", "curation/_index", "concept",
     "Forests are rebuilt, not edited",
     "The generator is the artifact; the forest is its output.",
     ["generator", "discipline"],
     [],
     "This forest was planted by a script. Nothing here was typed into a "
     "file by hand, and re-running the script produces it again.\n\n"
     "The habit matters at scale: a corpus you can regenerate is a corpus you "
     "can fix, and one that was hand-edited is a corpus you can only patch. "
     "Also, unrelated: a pangolin is the only mammal covered in scales."),

    ("curation/evaporation", "curation/_index", "concept",
     "Trails evaporate",
     "Paths that stop being used fade, so the map reflects what is actually "
     "read.",
     ["ranger", "pheromone"],
     [],
     "Every hop leaves a little heat on the trail it took. Heat decays, so a "
     "shortcut that was useful last quarter and useless since stops competing "
     "with the ones being used today.\n\n"
     "The Ranger promotes trails that stay hot and prunes the ones that go "
     "cold. It never deletes a node — only the paths between them."),

    ("governance/scope-is-not-a-filter", "governance/_index", "concept",
     "Scope is enforced before ranking",
     "An out-of-scope node is indistinguishable from one that does not exist.",
     ["policy", "security"],
     [("related-to", "curation/the-passport")],
     "A principal scoped to one branch does not get a filtered view of the "
     "whole forest — the candidate set is narrowed before anything is ranked, "
     "budgeted or truncated.\n\n"
     "That ordering is the whole point. If filtering happened after "
     "truncation, the number of results would leak the existence of material "
     "the caller may not read."),

    ("governance/the-owner", "governance/_index", "concept",
     "The owner precedes every forest",
     "First-run setup creates one owner, and then closes for good.",
     ["setup", "identity"],
     [],
     "Authority over a forest cannot come from a forest, or a fresh install "
     "would have nobody able to create the first one.\n\n"
     "So the owner is a property of the principal: administrator of every "
     "forest present and future, including none at all. The route that "
     "creates it exists only while the registry holds no credential, and it "
     "shuts permanently the moment it is used."),
]


def build_demo(root: str | Path, *, title: str = TITLE) -> dict:
    """Create the forest at `root` and plant the demo into it.

    Returns the `init_forest` info dict. Raises whatever the engine raises —
    a half-planted demo is worth failing loudly over, since the caller can
    simply delete the directory and try again.
    """
    from monkeyllm.forest import init_forest
    from monkeyllm.vine import Vine

    root = Path(root)
    info = init_forest(root, title=title, summary=SUMMARY)
    vine = Vine(root, writable=True)
    try:
        for node_id, node_title, blurb in BRANCHES:
            vine.plant({"id": node_id, "type": "branch", "parent": "_index",
                        "title": node_title, "summary": blurb,
                        "source": "manual"})
        for (node_id, parent, node_type, node_title, blurb, tags, links,
             body) in NOTES:
            vine.plant({
                "id": node_id, "type": node_type, "parent": parent,
                "title": node_title, "summary": blurb, "tags": list(tags),
                "links": [{"rel": rel, "target": target}
                          for rel, target in links],
                "body": body, "source": "manual",
            })
    finally:
        vine.close()
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m monkeyllm_station.demo_forest", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forest", required=True,
                    help="directory to create (must not exist yet)")
    ap.add_argument("--title", default=TITLE)
    args = ap.parse_args(argv)

    target = Path(args.forest)
    if target.exists():
        print(f"demo: refusing to plant into an existing path: {target}")
        return 2
    info = build_demo(target, title=args.title)
    print(f"demo forest at {info['root']} — "
          f"{len(BRANCHES)} branches, {len(NOTES)} notes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
