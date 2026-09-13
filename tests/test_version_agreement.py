# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""One version, written twice, checked once.

The number lives in `pyproject.toml` (what pip installs and what PyPI
publishes) and in `monkeyllm.__version__` (what a source checkout reports
and what `package_version()` falls back to). The release workflow's guard
compares the TAG to `pyproject.toml` alone, so the second copy could drift
without anything noticing — and the symptom would be a Station telling an
extension author, through `station_compat` and the L.16 authoring
reference, that it is a version it is not.

Two descriptions of one number agree only where somebody compared them.
This is the comparison.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import monkeyllm

ROOT = Path(__file__).resolve().parents[1]


def _declared() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def test_the_package_reports_what_pyproject_publishes():
    assert monkeyllm.__version__ == _declared()


def test_the_version_is_three_numbers():
    """CONTRIBUTING, "Versions": major.minor.patch, and the minor is the
    spec version this release implements."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", _declared()), _declared()


def test_the_minor_names_a_spec_that_exists():
    """`0.81.x` implements docs/monkeyllm-spec-v0.81.md. A release whose
    minor names no spec is a release nobody can check against a contract."""
    major, minor, _patch = _declared().split(".")
    spec = ROOT / "docs" / f"monkeyllm-spec-v{major}.{minor}.md"
    assert spec.is_file(), f"{spec.name} does not exist"
