# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The one-time repair of the shipped reply budget (spec J.10.8).

Every role shipped bound at `max_tokens` 600. For `answer` that is below the
reply it has to carry: the final action of a walk is a JSON object holding the
answer text AND `answer_nodes`, so the budget pays for the citation apparatus
and not only for prose. Measured on the 18-question suite, two answers were
lost to it — both AFTER the model had run the correct query and reached the
correct node, and both scored as WRONG ANSWERS rather than as truncation,
which is what kept the cause invisible.

Raising the default repairs nobody: a binding is a stored row, so every
deployment already on 600 stays on 600 until somebody edits it by hand. Hence
a data repair — and hence `PRAGMA user_version`, because the interesting
property is not that it runs but that it runs ONCE. An operator who chooses
600 deliberately after the upgrade must keep it, and a deliberate 600 is
byte-identical to the shipped one; only the stamp can tell them apart.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "station"))

from monkeyllm_station.registry import DATA_REPAIRS, Registry  # noqa: E402


def _aged(path: Path, bindings: dict[str, int]) -> None:
    """A registry as an older Station left it: rows bound, stamp at zero."""
    reg = Registry(path)
    try:
        reg.put_provider("p", "http://stub/v1", None)
        for role, tokens in bindings.items():
            reg.bind_model("f", role, "p", "m", max_tokens=tokens)
    finally:
        reg.close()
    raw = sqlite3.connect(path)
    raw.execute("PRAGMA user_version = 0")
    raw.commit()
    raw.close()


def _tokens(reg: Registry, role: str) -> int:
    return next(b["max_tokens"] for b in reg.bindings("f") if b["role"] == role)


def test_answer_binding_on_the_shipped_default_is_repaired(tmp_path):
    path = tmp_path / "aged.db"
    _aged(path, {"answer": 600, "ingest": 600, "vision": 600})

    reg = Registry(path)
    try:
        assert _tokens(reg, "answer") == 1500
        # The other two roles write a short scent and a description; neither
        # carries the citation apparatus, so neither is this bug.
        assert _tokens(reg, "ingest") == 600
        assert _tokens(reg, "vision") == 600
    finally:
        reg.close()


def test_a_budget_the_operator_chose_is_never_moved(tmp_path):
    path = tmp_path / "chosen.db"
    _aged(path, {"answer": 900})

    reg = Registry(path)
    try:
        assert _tokens(reg, "answer") == 900
    finally:
        reg.close()


def test_the_repair_runs_once_and_does_not_fight_the_operator(tmp_path):
    """The property the version stamp exists for."""
    path = tmp_path / "once.db"
    _aged(path, {"answer": 600})

    reg = Registry(path)
    try:
        assert _tokens(reg, "answer") == 1500
        # The operator now chooses 600 on purpose, which is indistinguishable
        # from the value the repair just moved.
        reg.bind_model("f", "answer", "p", "m", max_tokens=600)
    finally:
        reg.close()

    reg = Registry(path)
    try:
        assert _tokens(reg, "answer") == 600  # not 1500 again
    finally:
        reg.close()


def test_a_fresh_registry_is_stamped_current_and_carries_no_repair(tmp_path):
    path = tmp_path / "fresh.db"
    reg = Registry(path)
    reg.close()
    raw = sqlite3.connect(path)
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == len(DATA_REPAIRS)
    finally:
        raw.close()


@pytest.mark.parametrize("role", ["answer", "ingest", "vision"])
def test_a_new_binding_defaults_to_the_raised_budget(tmp_path, role):
    """The signature default, which is what an API caller that names no
    budget gets. The console sends its own per-role value."""
    reg = Registry(tmp_path / "new.db")
    try:
        reg.put_provider("p", "http://stub/v1", None)
        reg.bind_model("f", role, "p", "m")
        assert _tokens(reg, role) == 1500
    finally:
        reg.close()
