# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Boot opens the forests (spec J.6.1, C.6.1, criterion F.33).

The console's whole subject is how little retrieval costs, and the person
most likely to be handed a cold first call is the one evaluating the
product. Opening happens either way; this decides who waits for it.

Two things must survive the optimisation, and they are the two this product
asks to be trusted on: the pheromone and the audit log. A boot that warmed
itself through `locate` would leave forty reads nobody made in both.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"


@pytest.fixture(scope="session")
def warm_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("warm-root")
    build_forest(root / FOREST)
    return root


def _app(root: Path, registry: Path, **kw):
    from monkeyllm_station.app import build_app

    return build_app(root=root, registry_path=registry, mcp=False, **kw)


def _serve(app):
    from starlette.testclient import TestClient

    return TestClient(app)


# -- what warming does ------------------------------------------------------


def test_boot_opens_every_forest(warm_root, tmp_path):
    """So the first request is not the one measuring cold SQLite."""
    app = _app(warm_root, tmp_path / "on.db")
    assert app.state.pool.list()["forests"][0]["active"] is False

    with _serve(app):
        assert app.state.warmed["warmed"] == [FOREST]
        assert app.state.warmed["skipped"] == {}
        # Active before anybody has asked for anything.
        assert app.state.pool.list()["forests"][0]["active"] is True


def test_warming_off_goes_back_to_first_touch(warm_root, tmp_path):
    """The switch exists because holding every forest open is memory, and a
    registry of five hundred is a different deployment from one of ten.

    J.6.2 (v0.57): a READ no longer opens the writer — it is served by a
    reader vine, and `active` describes the writer, which opens on the
    first write or admin touch.
    """
    app = _app(warm_root, tmp_path / "off.db", warm=False)
    with _serve(app) as client:
        assert not hasattr(app.state, "warmed")
        assert app.state.pool.list()["forests"][0]["active"] is False

        registry = app.state.registry
        key = registry.issue_key("p")
        registry.grant("p", FOREST, {"read", "write"})
        r = client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                        headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200
        assert app.state.pool.list()["forests"][0]["active"] is False

        r = client.post(
            f"/v1/forests/{FOREST}/plant",
            json={"node": {"id": "warm-probe", "type": "note",
                           "title": "Warm probe",
                           "summary": "First-touch probe: the write opens "
                                      "the writer vine.",
                           "parent": "_index"}},
            headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200, r.text
        assert app.state.pool.list()["forests"][0]["active"] is True


def test_the_environment_can_turn_it_off(warm_root, tmp_path, monkeypatch):
    from monkeyllm_station.app import WARM_ENV, warm_from_env

    monkeypatch.setenv(WARM_ENV, "0")
    assert warm_from_env() is False
    with _serve(_app(warm_root, tmp_path / "env.db")) as client:
        assert client.app.state.pool.list()["forests"][0]["active"] is False

    # An explicit argument outranks it: a deployment that passes one has
    # already decided.
    monkeypatch.setenv(WARM_ENV, "0")
    with _serve(_app(warm_root, tmp_path / "env2.db", warm=True)) as client:
        assert client.app.state.pool.list()["forests"][0]["active"] is True


# -- what warming must not do -----------------------------------------------


def test_warming_deposits_no_pheromone_and_writes_no_audit(warm_root, tmp_path):
    """`warm()` is storage, not a call. Through `locate` it would forge the
    evidence the Ranger reads as where callers actually went (Part D/H)."""
    from monkeyllm.vine import Vine

    with Vine(warm_root / FOREST, writable=False) as vine:
        before = dict(vine.trails.heat_all())
        traced = len(vine.tracer.events)

    app = _app(warm_root, tmp_path / "clean.db")
    with _serve(app):
        # Through the forest's lane: those connections belong to it, and the
        # pool is not empty any more precisely because warming ran.
        after = app.state.forest_lane(FOREST).submit(
            lambda: (app.state.pool.get(FOREST).trails.heat_all(),
                     len(app.state.pool.get(FOREST).tracer.events))).result()
        assert after == (before, traced)
        assert app.state.registry.audit(limit=50) == []


def test_a_forest_that_will_not_open_does_not_stop_the_station(
        warm_root, tmp_path):
    """Refusing to serve the others because one was busy is not a
    performance feature. C.9 (v0.55): "busy" now means a LIVE writer — an
    orphan file heals during warm-up and skips nothing."""
    from monkeyllm.forest import WriterLock

    second = warm_root.parent / "locked-root"
    if not second.exists():
        second.mkdir()
        build_forest(second / FOREST)
        build_forest(second / "other-forest")
    holder = WriterLock(second / FOREST)
    holder.acquire()
    try:
        app = _app(second, tmp_path / "locked.db")
        # Shutdown closes the pool in its own forest thread, so leaving the
        # context is the whole cleanup.
        with _serve(app) as client:
            assert app.state.warmed["warmed"] == ["other-forest"]
            assert FOREST in app.state.warmed["skipped"]
            assert client.get("/v1/health").status_code == 200
    finally:
        holder.release()


def test_an_orphan_lock_does_not_skip_warming(warm_root, tmp_path):
    """The other half of C.9 v0.55: the file alone decides nothing."""
    second = warm_root.parent / "orphan-root"
    if not second.exists():
        second.mkdir()
        build_forest(second / FOREST)
    (second / FOREST / ".vine.lock").write_text("999999", encoding="utf-8")
    app = _app(second, tmp_path / "orphan.db")
    with _serve(app):
        assert FOREST in app.state.warmed["warmed"]
        assert not app.state.warmed["skipped"]


# -- derived storage (C.6.1) ------------------------------------------------


def test_derived_databases_are_tuned_for_reads(warm_root):
    """Every read primitive commits, so the journal mode is on the hot path.
    The durability given up is durability `_derived/` never had."""
    from monkeyllm.vine import Vine

    with Vine(warm_root / FOREST, writable=False) as vine:
        for conn in (vine.catalog.conn, vine.trails.conn):
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1


def test_warming_is_read_only_on_a_read_only_forest(warm_root):
    """It has to be: a Station serves reads by default, and a warm-up that
    needed to write could not run there at all."""
    from monkeyllm.vine import Vine

    with Vine(warm_root / FOREST, writable=False) as vine:
        vine.warm()
        vine.warm()          # idempotent, and still nothing written
        assert vine.catalog.count() > 0
