from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO / "forests" / "scripts" / "build_fixture.py"


def build_forest(dest: Path) -> Path:
    subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--out", str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


@pytest.fixture(scope="session")
def forest_ro(tmp_path_factory) -> Path:
    """Session-wide forest for read-only tests."""
    return build_forest(tmp_path_factory.mktemp("forest") / "forest")


@pytest.fixture(scope="session")
def vine_ro(forest_ro):
    from monkeyllm import Vine

    v = Vine(forest_ro, writable=False)
    yield v
    v.close()


@pytest.fixture()
def forest_rw(tmp_path) -> Path:
    """Fresh forest per test for write tests."""
    return build_forest(tmp_path / "forest")


@pytest.fixture()
def vine_rw(forest_rw):
    from monkeyllm import Vine

    v = Vine(forest_rw, writable=True)
    yield v
    v.close()
