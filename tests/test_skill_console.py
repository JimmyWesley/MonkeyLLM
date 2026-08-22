# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Skills console's generated artifact (spec J.5.12, F.111 - F.115).

The skill is built in the browser and the Station gains no endpoint for it,
so nothing on this side of the wire can be asserted against a response. What
CAN be asserted is the generator: `apps/studio/check-skill.mjs` builds every
assembly the console offers and checks the criteria against the text itself.
Run from here so a criterion cannot quietly stop being true.

What it cannot see is the address: F.116's other half — the console reading
and writing its selection through `useRouteState` — needs a DOM, so what is
checked here is the file's side of it (the core names the link that rebuilds
it, and says installing is the operator's act).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CHECKER = REPO / "apps" / "studio" / "check-skill.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_generated_skill_meets_its_criteria():
    r = subprocess.run(["node", str(CHECKER)], capture_output=True, text=True,
                       cwd=REPO / "apps" / "studio")
    assert r.returncode == 0, r.stdout + r.stderr
    # Every criterion reported, not just the ones that happened to run.
    assert r.stdout.count("PASS") >= 17, r.stdout
