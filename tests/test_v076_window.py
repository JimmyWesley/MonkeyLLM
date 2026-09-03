# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The timeline is a window (spec J.5.4 v0.76, F.170).

The graph mode's docked timeline gained a start beside its end. The
criterion has two halves and only one of them is a slider: a node outside
the window must leave the PICTURE and never the physics, because the
survivors of a narrow window are leaves whose branch was planted long
before it — take the branch out of the springs and they fall into the
centre, and the map then says what arrived while lying about where it
landed.

Studio has no test runner, so this follows `tests/test_v075_console.py`:
the criteria live in `apps/studio/check-window.mjs`, next to the code they
describe, and are run from here so one cannot quietly stop being true. The
checker accepts another graph source as its argument, which is how the
negative control (the v0.75 view put back) was run.

The boundary is F.137's: the checker reads the source and sees the decision
layer — which set is stepped, which set is painted, what the readout is
computed from, where the window is written. A rendered slider, a thumb
under a pointer and the canvas itself want a browser, and are not asserted
from the source.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUDIO = REPO / "apps" / "studio"
CHECKER = STUDIO / "check-window.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_window_meets_its_criteria():
    r = subprocess.run(["node", str(CHECKER)], capture_output=True, text=True,
                       cwd=STUDIO)
    assert r.returncode == 0, r.stdout + r.stderr
    # Every criterion reported, not just the ones that happened to run: a
    # checker that exits 0 because it stopped early is a passing test about
    # nothing.
    assert r.stdout.count("PASS") >= 30, r.stdout


def test_the_two_ends_are_named_in_every_language():
    """The cheap half, needing no toolchain: the start and the end are two
    controls with two names, in all three languages the Studio ships, and
    the graph view uses both — a slider with one name is one slider."""
    for lang in ("en", "pt", "es"):
        d = json.loads((STUDIO / "src" / "locales" / "graph" / f"{lang}.json")
                       .read_text(encoding="utf-8"))
        assert d["graph.window_start"] and d["graph.window_end"], lang
        assert d["graph.window_start"] != d["graph.window_end"], lang
    text = (STUDIO / "src" / "views" / "graph.jsx").read_text(encoding="utf-8")
    assert "t('graph.window_start')" in text
    assert "t('graph.window_end')" in text


def test_the_window_is_a_paint_split_never_a_physics_one():
    """J.5.4 v0.76's load-bearing sentence, asserted without node: the
    simulation's own step function reads `on` and does not know `shown`
    exists."""
    text = (STUDIO / "src" / "views" / "graph.jsx").read_text(encoding="utf-8")
    start = text.index("export function step(sim, w, h, p) {")
    end = text.index("\n}\n", start)
    step = text[start:end]
    assert "if (n.on) live.push(n)" in step
    assert "shown" not in step
    assert "n.shown = n.on && n.bornRank >= s.from" in text
