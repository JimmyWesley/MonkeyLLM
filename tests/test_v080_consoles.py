# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""A console entry is complete, or the app does not load (Part L, v0.80).

This exists because of a failure that shipped: `extensions` was added to
the shell's `CONSOLES` and to `App`'s `VIEWS`, and not to `CONSOLE_ICON`.
The nav then rendered `<Icon/>` where `Icon` was `undefined` — React error
#130 — and because the nav renders on **every** page, a missing icon took
down every console, including ones nobody had touched. The Studio build
was green throughout: JSX cannot know that a lookup in a plain object can
miss, and the failure surfaced only as a blank screen in a browser.

The criterion is therefore not "extensions has an icon". It is that every
console the shell offers has all four things it needs — a view, an icon,
and a label and a blurb in each language — so a console added tomorrow is
checked tomorrow. That is `test_station_admin_scope`'s route canary, moved
to the front end, and it is the check the class of bug demanded rather than
the patch the instance did.

The checker was verified to FAIL with the icon map's `extensions` entry
removed; it takes another Shell source as its argument, which is how that
control is repeated.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio"
CHECKER = STUDIO / "check-consoles.mjs"


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node is not available")
def test_every_console_has_a_view_an_icon_and_its_labels():
    result = subprocess.run(["node", str(CHECKER)], capture_output=True,
                            text=True, cwd=str(STUDIO))
    assert result.returncode == 0, result.stdout + result.stderr
