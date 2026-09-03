# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The operator's hands, on the console side (spec J.5.17, F.167).

`prune` and `transplant` are the engine's, and the engine's own suite is
where "it removes the node, keeps the history and moves the payload" is
proven. What this file covers is the other half of F.167: the console that
now reaches them — that the prune confirmation states the two facts C.14
makes true, that an `E_ANCHORED` refusal is drawn as the list it carries
with its count treated as the complete fact, that a branch is offered no
transplant control at all, and that neither act leaves a dead id in the
address.

Studio has no test runner, so this follows `tests/test_skill_console.py`:
the criteria live in `apps/studio/check-hands.mjs`, next to the code they
describe, and are run from here so one cannot quietly stop being true.

The boundary is F.137's and is deliberately not papered over. What a checker
reading the source can see is structure — a gate, a missing control, a
handler called after its await, a sentence in three catalogues. What it
cannot see is a rendered dialog, a click that navigates, or a query string
after a commit; those want a DOM and a live Station, and asserting them from
the source would only assert that a string is present.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUDIO = REPO / "apps" / "studio"
CHECKER = STUDIO / "check-hands.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_operator_hands_meet_their_criteria():
    r = subprocess.run(["node", str(CHECKER)], capture_output=True, text=True,
                       cwd=STUDIO)
    assert r.returncode == 0, r.stdout + r.stderr
    # Every criterion reported, not just the ones that happened to run: a
    # checker that exits 0 because it stopped early is a passing test about
    # nothing.
    assert r.stdout.count("PASS") >= 35, r.stdout


def test_the_hands_are_reachable_from_both_consoles():
    """J.5.17 rule 1, asserted on the wiring rather than on the component.

    The dialogs are only worth anything where a node is the subject, and the
    two consoles that have one are Explore and Read. This is the cheap half
    of that check and it needs no toolchain, so it runs even where node does
    not exist.
    """
    for view in ("Explore.jsx", "Read.jsx"):
        text = (STUDIO / "src" / "views" / view).read_text(encoding="utf-8")
        assert "NodeHands" in text, f"{view} does not offer the operator's hands"


def test_no_console_carries_a_bulk_removal():
    """J.5.17 rule 5. `prune` is one node per call by contract — one commit,
    one anchor check, one audit row — so a loop over a selection would let a
    single `E_ANCHORED` strand a half-finished sweep with nothing recording
    where it stopped. The dispatch appears exactly once in the whole app."""
    src = STUDIO / "src"
    calls = [
        f"{path.relative_to(src)}:{n}"
        for path in src.rglob("*.jsx")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "api.call(" in line and "'prune'" in line
    ]
    assert len(calls) == 1, f"prune is dispatched from more than one place: {calls}"
