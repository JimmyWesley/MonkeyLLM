# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""F.218 (spec v0.83) — the consoles carry no list of their own.

The criteria live in `apps/studio/check-usable.mjs`, next to the code they
read; this file runs them, and runs them once more against the v0.82
sources as the negative control, because a static check that cannot fail
proves only that a string is present.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUDIO = REPO / "apps" / "studio"
CHECKER = STUDIO / "check-usable.mjs"
VIEWS = ("Ingest.jsx", "Models.jsx", "Extensions.jsx")

needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not available")


@needs_node
def test_the_consoles_read_their_lists_off_the_host():
    result = subprocess.run(["node", str(CHECKER)], capture_output=True,
                            text=True, cwd=str(STUDIO))
    assert result.returncode == 0, result.stdout + result.stderr


@needs_node
def test_the_previous_consoles_fail_the_criteria(tmp_path):
    """The negative control: the sources this round replaced."""
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    old = tmp_path / "views"
    old.mkdir()
    for name in VIEWS:
        show = subprocess.run(
            ["git", "show", f"v0.82.0:apps/studio/src/views/{name}"],
            capture_output=True, text=True, cwd=str(REPO))
        if show.returncode != 0:
            pytest.skip("the v0.82.0 tag is not reachable from this checkout")
        (old / name).write_text(show.stdout, encoding="utf-8")
    result = subprocess.run(["node", str(CHECKER), str(old)],
                            capture_output=True, text=True, cwd=str(STUDIO))
    assert result.returncode != 0, result.stdout
    assert "FAIL" in result.stdout
