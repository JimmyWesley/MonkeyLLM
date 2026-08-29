# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Ask console's path panel (spec J.5.15, F.137).

The panel is drawn on a canvas in a browser, so nothing here can look at
it — and it is not the drawing that F.137 is about. The criterion is what
gets MARKED, and the rules that decide are in `apps/studio/src/trailmap.js`
precisely so a machine can put the questions to them:
`apps/studio/check-trail.mjs` does, and this module runs it.

A walk is marked from two objects rather than one — J.10.12's `hop` events
while the call is open, the response's own `read` and `hops` at the close
(J.5.15 rule 2) — so the checker also puts the question those two raise
together: the live picture MUST be contained in the final one. A dot that
lights while a hunt runs and goes dark when its answer lands is two pictures
of one hunt, which is the thing the live channel exists to end.

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
TRAIL = STUDIO / "src" / "views" / "trail.jsx"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_panel_marks_only_what_the_material_says():
    r = subprocess.run(["node", str(CHECKER)], capture_output=True, text=True,
                       cwd=STUDIO)
    assert r.returncode == 0, r.stdout + r.stderr
    # Every criterion reported, not just the ones that happened to run: the
    # checker is one module, so a throw partway down exits non-zero while the
    # criteria after it are never asked at all.
    assert r.stdout.count("PASS") >= 35, r.stdout


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


def _block(source: str, opens_at: int) -> tuple[int, int]:
    """The span of the braced block whose first `{` is at or after `opens_at`."""
    start = source.index("{", opens_at)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return start, i
    raise AssertionError("unbalanced braces around the preview guard")


def test_no_retrieval_preview_on_a_walk():
    """J.5.15 rule 2 (v0.67), F.142: the preview is a sweep's, and only a sweep's.

    A walk runs no `harvest` at all — its entry is a bare `locate` and every
    retrieval after it is a call the model authored (J.10.5) — so a harvest
    fired beside a walk is not the same sweep, it is a sweep that never
    happened, and painting its results as the answer's retrieval is exactly
    what rule 3 forbids.

    What a canvas paints is not machine-readable (F.137 states that
    boundary), so what is asked here is REACHABILITY, in the idiom
    F.111-F.116 use for generated text: every path that starts the parallel
    retrieval — the immediate one and the fallback that stands in for an
    absent J.10.12 channel — must lie inside the block the walk switch turns
    off.
    """
    source = ASK.read_text(encoding="utf-8")
    starts = [m.start() for m in re.finditer(r"'harvest'", source)]
    assert starts, "the path panel's retrieval preview is gone from Ask.jsx"

    guards = [m.start() for m in re.finditer(r"if \(!hops\) \{", source)]
    assert len(guards) == 1, (
        "the sweep-only guard must be exactly one block, or 'every path that "
        "starts a preview' is not a question this check can ask")
    opened, closed = _block(source, guards[0])
    for at in starts:
        assert opened < at < closed, (
            "a retrieval preview is reachable while the walk switch is on: "
            "the panel would paint a sweep that never happened (J.5.15 rule 2)")

    # The other half of the same rule: the drawing is the only reason a
    # preview ever ran, so with the panel switched off nothing fires in
    # either mode — and the call then carries no `run` either.
    drawing = [m.start() for m in re.finditer(r"if \(runId\) \{", source)]
    assert len(drawing) == 1, "the panel's own gate is not one block"
    opened, closed = _block(source, drawing[0])
    for at in starts:
        assert opened < at < closed, (
            "a retrieval preview is reachable with the path panel switched "
            "off, and the drawing was the only reason it ran (J.5.15 rule 1)")


def test_the_fallback_dies_when_the_answer_lands():
    """J.5.15 rule 1: the panel costs the forest nothing.

    The fallback exists to stand in for a progress channel that never spoke.
    Once the POST has settled there is no gap left for it to fill, and a
    stored answer (J.10.7) returns in milliseconds — so a timer nobody
    cancels makes the store's own economy pay for a retrieval on every hit,
    and draws nothing with it.
    """
    source = ASK.read_text(encoding="utf-8")
    settle = re.search(r"finally \{(.{0,600}?)setBusy\(false\)", source, re.S)
    assert settle, "the ask's settle is gone from Ask.jsx"
    assert "clearTimeout(" in settle.group(1), (
        "the answer settles without cancelling the preview fallback: a "
        "stored answer would pay for a retrieval it never draws")


def _draw_block(source: str, anchor: str, span: int = 520) -> str:
    """The source right after `anchor` — the loop that draws one line.

    Named apart from `_block` above, which answers a different question
    about a different file: two helpers sharing a name is how a passing
    test starts failing for a reason that has nothing to do with it.
    """
    i = source.index(anchor)
    return source[i:i + span]


def test_the_helicopter_stops_at_the_branch():
    """F.151. Two lines, and the split is WHERE the flight ends.

    This panel spent two revisions saying the wrong thing, and both were the
    same wrong thing: that the agent arrived, in one move, on the exact file
    it needed. First as one amber chain from the root, then as one chain
    that marched. The product does not claim that — the helicopter puts you
    near, and the last step in is yours.

    So the blue line is the flight and it STOPS at the branch: a segment
    whose destination is a marked node is not its to draw. The amber is the
    monkey's own movement and means that in both modes — on a sweep, the one
    step into the opened file; on a walk, the real hop sequence.
    """
    source = TRAIL.read_text(encoding="utf-8")
    assert "pal.drop" in source and "pal.trail" in source, \
        "the two lines no longer come from two tokens"
    assert re.search(r"out\.drop = channel\('graph-drop'", source), \
        "the flight has no colour of its own"

    # The split rule itself: destination marked => the monkey's leg.
    assert re.search(r"legOf = \(seg\) => \(marked\.has\(seg\.b\)", source), \
        "nothing decides where the flight ends"
    # A window after the anchor, not a brace match: the block is long and
    # counting braces from a regex is how a test starts failing for reasons
    # that have nothing to do with what it checks.
    fly = _draw_block(source, "ctx.strokeStyle = pal.drop")
    assert "legOf(seg) !== 'fly'" in fly, \
        "the flight draws legs that belong to the walk"

    # Both march: the eye must read two movements, not a movement and a wire.
    assert len(re.findall(r"ctx\.lineDashOffset = -march", source)) >= 2, \
        "one of the two lines is static"
    assert re.search(r"trailRef\.current\.segments\.length\s*&&", source), \
        "the march is not gated on there being anything to draw"


def test_the_drops_leave_together():
    """F.152. Several hits are several drops leaving the base at once.

    The reveal used to stagger each leg by its depth, so a two-hit answer
    drew one chain and then the other and read as an order the retrieval
    never had — `locate` returns a ranked set, not a sequence of journeys.
    One progress value, shared by every leg.
    """
    source = TRAIL.read_text(encoding="utf-8")
    assert re.search(r"const flown = clamp01\(", source), "the flight has no clock"
    # The tell-tale of the old behaviour: progress computed FROM the leg.
    fly = _draw_block(source, "ctx.strokeStyle = pal.drop")
    assert "seg.depth" not in fly, \
        "the flight is still staggered by depth; drops must leave together"


def test_a_sweep_draws_no_route():
    """F.152. `hopSegments` is empty without hops, and an absent line is the true
    statement that no walking occurred. Asserted on the rule rather than on
    the canvas: a sweep passes no `hops`, so there is nothing to collapse."""
    source = (STUDIO / "src" / "trailmap.js").read_text(encoding="utf-8")
    fn = re.search(r"export function hopSegments\(hops, byId\) \{(.*?)\n\}",
                   source, re.S)
    assert fn, "hopSegments is gone"
    body = fn.group(1)
    # Only a hop that NAMES one node is a position. A hop that returned a
    # set is the agent looking around from where it already stands, and a
    # line to the first of ten results is a step nobody took.
    assert "STANDS_ON.has(hop.tool)" in body, body
    assert re.search(r"STANDS_ON = new Set\(\['move', 'pick', 'look'\]\)", source)
    # Standing still twice is one place.
    assert re.search(r"stops\[stops\.length - 1\]\.id === id", body), body


def test_every_node_the_trail_touches_is_named():
    """A waypoint with no name is a shape, not a route.

    The captions used to come from `marked` alone — the nodes the answer
    stopped at — so the branches it climbed THROUGH to reach them were
    anonymous. Half of "where did this answer go" is the way there.
    """
    source = TRAIL.read_text(encoding="utf-8")
    passed = re.search(r"const passed = new Map\(\)(.{0,600}?)\n\s*if \(marked\.size",
                       source, re.S)
    assert passed, "the through-nodes are no longer collected"
    body = passed.group(1)
    # Built from the segments, which is what "passed through" means, and
    # never double-counting a node the answer actually stopped at.
    assert "for (const seg of segments)" in body, body
    assert "marked.has(id)" in body, body
    # Both sets reach the caption pass, and a hit stays visibly a hit.
    rows = re.search(r"const rows = \[(.{0,400}?)\]\n", source, re.S)
    assert rows and "marked" in rows.group(1) and "passed" in rows.group(1), \
        "the caption pass no longer reads both sets"
    assert re.search(r"hit \? at : at \* 0\.\d+", source), \
        "a way-through caption must not read as loudly as a result"


def test_the_camera_frames_what_has_been_revealed():
    """F.153: the view travels, because the reveal is the subject.

    Leaning on every marked node from the first frame puts the whole answer
    in shot before any of it has arrived, and a viewer shown the destination
    first has been told there is nothing to discover. The frame is computed
    from what the reveal has reached.

    Read off the source for F.137's reason. What is asserted is the input to
    the camera, not the picture: a build that collects marks without
    consulting the reveal position fails, whatever it then does with them.
    """
    source = TRAIL.read_text(encoding="utf-8")
    fit = _draw_block(source, "const touched = []", 420)
    assert "anim.current.pos" in _draw_block(source, "const at = anim.current.pos", 60), \
        "the camera has no clock"
    assert re.search(r"if \(Math\.min\(\.\.\.stages\) > at\) continue", fit), \
        "the camera leans on marks the reveal has not reached yet"
    assert re.search(r"if \(seg\.stage > at\) continue", fit), \
        "the camera leans on segments the reveal has not reached yet"
    # And it keeps re-framing while the reveal runs, or the travel is one jump.
    assert re.search(r"anim\.current\.pos \+ dt / STAGE_MS\)\n\s*//.*\n(\s*//.*\n)*\s*fit\(",
                     source), "the frame is computed once and never updated"
