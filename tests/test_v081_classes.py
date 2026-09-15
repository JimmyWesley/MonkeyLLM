# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""An invented class name is a no-op, and nothing noticed (v0.81).

The Extensions console shipped with `className="stack"`, `"row gap"`,
`"muted"`, `"small"`, `"kv"` and `"mono"`. None of them exist — not in
`index.css`, not as Tailwind utilities, not anywhere else in the app — so
every one silently did nothing: the cards had no gap between them, a button
and its hint shared one crushed line, and the labels were unstyled. The
Studio build was green throughout, because JSX cannot know a class is
fictional and Tailwind generates nothing for a token it does not recognise.
It surfaced when somebody looked at the screen.

`apps/studio/check-classes.mjs` is the criterion, next to the code it
describes: a token defined in no stylesheet AND used in no other file is
invented vocabulary. The checker was verified to FAIL with those class
names put back, and takes another src directory as its argument, which is
how that control is repeated.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio"
CHECKER = STUDIO / "check-classes.mjs"


@pytest.mark.skipif(shutil.which("node") is None,
                    reason="node is not available")
def test_no_view_uses_a_class_that_does_not_exist():
    result = subprocess.run(["node", str(CHECKER)], capture_output=True,
                            text=True, cwd=str(STUDIO))
    assert result.returncode == 0, result.stdout + result.stderr
