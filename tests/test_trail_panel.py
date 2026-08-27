# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Ask console's path panel (spec J.5.15, F.137).

The panel is drawn on a canvas in a browser, so nothing here can look at
it — and it is not the drawing that F.137 is about. The criterion is what
gets MARKED, and the rules that decide are in `apps/studio/src/trailmap.js`
precisely so a machine can put the questions to them:
`apps/studio/check-trail.mjs` does, and this module runs it.

Two of F.137's claims are not the console's to keep, and they are checked
here directly:

* **The preview forges no heat.** The panel draws early by running the
  sweep's retrieval itself, ahead of the answer. That is only allowed
  because a read deposits no pheromone — heat is the whisper's, at the
  close of an answer (J.10.7). If a bare `harvest` ever started depositing,
  the panel would be quietly rewriting the ranking it exists to depict, and
  every console showing it would be lying twice.
* **The preview asks the answer's own question.** Same question, same `k`,
  same entry ranker, or the map describes a retrieval that never ran.
  That one lives in JSX, so it is read off the source: the point is not the
  spelling but that the three arguments are still there.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUDIO = REPO / "apps" / "studio"
CHECKER = STUDIO / "check-trail.mjs"
ASK = STUDIO / "src" / "views" / "Ask.jsx"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_panel_marks_only_what_the_material_says():
    r = subprocess.run(["node", str(CHECKER)], capture_output=True, text=True,
                       cwd=STUDIO)
    assert r.returncode == 0, r.stdout + r.stderr
    # Every criterion reported, not just the ones that happened to run.
    assert r.stdout.count("PASS") >= 20, r.stdout


def test_a_harvest_deposits_no_pheromone(vine_rw):
    """J.5.15 rule 2, and the reason the preview is allowed to exist.

    Heat is deposited by the whisper at the close of a hosted answer, never
    by a primitive. The panel runs a second retrieval per question, so if
    that ever changed, every question would double-count its own evidence
    and the ranking the map depicts would be one the map itself caused.
    """
    from monkeyllm.harvest import harvest

    result = harvest(vine_rw, "latency experiment", k=3)
    ids = [r["id"] for r in result.get("results", [])]
    assert ids, "the fixture must answer this, or the test proves nothing"

    before = vine_rw.trails.heat_map(ids)
    for _ in range(3):
        harvest(vine_rw, "latency experiment", k=3)
    after = vine_rw.trails.heat_map(ids)

    assert after == before, (
        f"a harvest moved the heat of {[i for i in ids if after.get(i) != before.get(i)]}"
        " — the path panel's preview would be forging the ranking it draws")

    # Guards the guard: every reading above is 0.0, so an instrument that
    # simply could not see heat would pass this test forever. The whisper's
    # own channel must move it.
    vine_rw.trails.add_heat(ids)
    assert vine_rw.trails.heat_map(ids) != before, (
        "heat_map reported no change after an explicit deposit, so the "
        "assertion above proved nothing")


def test_the_preview_asks_the_answers_own_question():
    """J.5.15 rule 2: the preview is the same sweep, not a similar one."""
    source = ASK.read_text(encoding="utf-8")
    call = re.search(r"api\.call\(\s*forest,\s*'harvest',(.{0,200}?)\)\s*\n",
                     source, re.S)
    assert call, "the path panel's retrieval preview is gone from Ask.jsx"
    args = call.group(1)
    # The question, the depth and the entry ranker — the three the answer is
    # about to be asked with. A preview missing any of them draws a
    # retrieval that never ran.
    assert "query: q" in args, args
    assert re.search(r"\bk\b", args), args
    assert "hybrid" in args, args


def test_the_panel_is_its_own_switch():
    """J.5.15 rule 1: never folded into the walk's.

    A walk is one model call per hop and the drawing is none. One control
    over both would teach an operator that the picture is what made the
    answer slow — which is exactly the reading the panel must not invite in
    front of somebody evaluating the product.
    """
    source = ASK.read_text(encoding="utf-8")
    assert "t('ask.graph')" in source, "the path panel has no switch of its own"
    assert "t('ask.hops')" in source, "the walk's switch is gone"
    assert "savePrefs({ graph:" in source, (
        "the switch must persist as a browser preference (J.5.8): the "
        "address carries the selection, not the taste")
    # The two switches are separate pieces of state, so neither can move the
    # other. `hops` reaching the panel's state at all is the defect.
    assert not re.search(r"setShowGraph\((?!v\b|\(|false|true)", source), source
