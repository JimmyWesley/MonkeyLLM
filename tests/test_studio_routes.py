# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The console keeps its place in the address, and only there (spec J.5.8).

Where Studio is — the forest, the console, the selection — used to live in
React state and nowhere else, so every screen was served at `/` and a reload
started over in somebody else's forest. The fix is not "add a URL": it is
that the address *is* the state. A second copy of it would disagree with the
address bar eventually, and the address bar is the copy the operator can
see, share and edit.

Read from the source for the same reason `test_studio_calls` does: the
console is JavaScript, there is no JS harness in this suite, and CI has no
node. What is checked here is therefore architecture, not behaviour — the
behaviour lives in `test_station_studio_routes` (the host half) and in F.34.
"""

from __future__ import annotations

import re
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio" / "src"
ROUTER = STUDIO / "router.js"


def _sources():
    for path in sorted(STUDIO.rglob("*.jsx")) + sorted(STUDIO.rglob("*.js")):
        yield path, path.read_text(encoding="utf-8")


def test_the_router_exists_and_owns_the_grammar():
    text = ROUTER.read_text(encoding="utf-8")
    assert "export function hrefFor" in text
    assert "export function parse" in text
    assert "/f/" in text, "the address grammar of J.5.8 is not in the router"


def test_only_the_router_touches_history():
    """One router. A console that pushed its own entry would be navigating
    without the address bar's reader — and the browser's Back button is the
    one control this product does not implement."""
    offenders = [
        str(path.relative_to(STUDIO)) for path, text in _sources()
        if path != ROUTER
        and re.search(r"history\.(push|replace)State|location\.(assign|replace)\b", text)
    ]
    assert not offenders, (
        f"{offenders} navigate outside router.js; use `navigate`/`linkTo`")


def test_console_addresses_are_never_built_by_hand():
    """`hrefFor` is the only producer of an address, so the grammar changes in
    one place. A hand-built `/f/${forest}/…` is a second grammar that drifts
    from the first the day a parameter is added."""
    offenders = [
        str(path.relative_to(STUDIO)) for path, text in _sources()
        if path != ROUTER and re.search(r"[\"'`]/f/", text)
    ]
    assert not offenders, f"{offenders} build a console address by hand; use `hrefFor`"


def test_the_app_keeps_no_second_copy_of_where_it_is():
    """The regression this whole section exists for: `useState('ask')` for the
    open console, and a forest chosen again on every reload."""
    text = (STUDIO / "App.jsx").read_text(encoding="utf-8")
    held = set(re.findall(r"const \[(\w+),\s*set\w+\]\s*=\s*useState", text))
    assert not held & {"forest", "view", "node"}, (
        f"App.jsx holds {sorted(held & {'forest', 'view', 'node'})} in state; "
        "the address is where the console is (J.5.8)")
    assert "useUrl()" in text and "parse(" in text


def test_navigation_is_anchors():
    """Open in a new tab, copy link, middle click, the status bar. A `<button>`
    that calls a state setter has none of them, and the Station now serves the
    addresses those affordances produce."""
    shell = (STUDIO / "components" / "Shell.jsx").read_text(encoding="utf-8")
    assert "linkTo(" in shell, "the navigation no longer carries its addresses"
    assert not re.search(r"onClick=\{\(\)\s*=>\s*setView\(", shell)
