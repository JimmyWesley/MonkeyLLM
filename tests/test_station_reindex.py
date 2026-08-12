# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The catalog rebuild over HTTP (spec J.13.3, criterion F.41).

Every "if it diverges from the files, the files win and the catalog
rebuilds" rule in the spec ends at one command, and until v0.41 a hosted
operator — who has a browser, not a shell — could not run it.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"


@pytest.fixture(scope="session")
def reindex_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("reindex-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(reindex_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    app = build_app(root=reindex_root, registry_path=tmp_path / "station.db",
                    mcp=False, writable=True)
    with TestClient(app) as client:
        yield client, app.state.registry, app


def _admin(registry, principal="boss", allow=None):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, {"read", "admin"}, allow=allow)
    return {"Authorization": f"Bearer {key}"}


def _head(root: Path) -> str:
    return subprocess.run(["git", "-C", str(root / FOREST), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def _derived(root: Path, name: str, sql: str):
    """Read a derived database with our OWN connection.

    The Station's belongs to that forest's lane (J.9) and SQLite refuses it
    from any other thread — which is the rule working, not an obstacle.
    """
    conn = sqlite3.connect(root / FOREST / "_derived" / name)
    try:
        return conn.execute(sql).fetchone()
    finally:
        conn.close()


NEW_NODE = """---
id: notes/arrived-behind-the-station
type: note
title: Arrived behind the Station
summary: A node that reached the files without passing through the host.
created: '2026-08-12'
updated: '2026-08-12'
---

# Arrived behind the Station

A snapshot restore, a git pull, an editor: the files changed and nobody
told the index. Ptarmigan is the word that proves it was found.
"""


def test_rebuild_finds_what_arrived_behind_the_station(station, reindex_root):
    """The divergence this endpoint exists for: a git pull, a restore, an
    edit — the files moved and the derived layer did not."""
    client, registry, _ = station
    head = _admin(registry)
    body = {"terms": ["ptarmigan"]}
    assert client.post(f"/v1/forests/{FOREST}/sniff", json=body,
                       headers=head).json()["results"] == []

    (reindex_root / FOREST / "notes" / "arrived-behind-the-station.md").write_text(
        NEW_NODE, encoding="utf-8")

    r = client.post("/v1/admin/reindex", json={"forest": FOREST}, headers=head)
    assert r.status_code == 200, r.text
    assert r.json()["nodes"] > 0

    found = client.post(f"/v1/forests/{FOREST}/sniff", json=body,
                        headers=head).json()["results"]
    assert [x["id"] for x in found] == ["notes/arrived-behind-the-station"]


def test_count_equals_the_shell(station, reindex_root):
    client, registry, _ = station
    head = _admin(registry)
    served = client.post("/v1/admin/reindex", json={"forest": FOREST},
                         headers=head).json()["nodes"]
    out = subprocess.run(
        [sys.executable, "-m", "monkeyllm.cli", "reindex",
         "--forest", str(reindex_root / FOREST)],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
    assert str(served) in out.stdout, out.stdout + out.stderr


def test_a_branch_scoped_admin_is_refused(station):
    """The count is the size of the whole forest, and every row rewritten
    includes nodes this principal may not read (J.13.3)."""
    client, registry, _ = station
    head = _admin(registry, "narrow", allow=["notes/"])
    r = client.post("/v1/admin/reindex", json={"forest": FOREST}, headers=head)
    assert r.status_code == 403
    assert "whole forest" in r.json()["error"]["message"]


def test_it_writes_no_history_and_no_pheromone(station, reindex_root):
    client, registry, _ = station
    head = _admin(registry)
    heat = "SELECT count(*), coalesce(sum(heat), 0) FROM heat"
    before_heat = _derived(reindex_root, "trails.db", heat)
    before_head = _head(reindex_root)

    assert client.post("/v1/admin/reindex", json={"forest": FOREST},
                       headers=head).status_code == 200

    assert _derived(reindex_root, "trails.db", heat) == before_heat
    assert _head(reindex_root) == before_head


def test_it_is_idempotent(station):
    client, registry, _ = station
    head = _admin(registry)
    first = client.post("/v1/admin/reindex", json={"forest": FOREST},
                        headers=head).json()
    second = client.post("/v1/admin/reindex", json={"forest": FOREST},
                         headers=head).json()
    assert first["nodes"] == second["nodes"]


def test_the_memo_survives_a_rebuild(station, reindex_root):
    """C.6b.1: rebuilding rewrites every row, and an unchanged body keeps its
    hash — so a repair must not also be a punishment."""
    client, registry, _ = station
    head = _admin(registry)
    client.post(f"/v1/forests/{FOREST}/sniff",
                json={"terms": ["architecture"]}, headers=head)
    rows = "SELECT count(*) FROM sniff_memo"
    before = _derived(reindex_root, "catalog.db", rows)[0]
    assert before, "the sniff learned nothing, so this test proves nothing"

    assert client.post("/v1/admin/reindex", json={"forest": FOREST},
                       headers=head).status_code == 200

    assert _derived(reindex_root, "catalog.db", rows)[0] == before


def test_an_unknown_forest_is_not_invented(station):
    client, registry, _ = station
    key = registry.issue_key("boss")
    registry.grant("boss", "nope", {"read", "admin"})
    r = client.post("/v1/admin/reindex", json={"forest": "nope"},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 404
