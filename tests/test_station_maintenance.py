# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The maintenance surface (spec J.13, criterion F.26).

The Ranger's report and Part I's snapshots reach the operator who has a
browser instead of a shell. Neither invents anything: `health` relays what
`Ranger.health()` computes, and a snapshot is the bundle `vine snapshot`
already makes. So the tests are about the two things a host CAN get wrong —
who may see a whole-forest report, and where the bundles land.
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


@pytest.fixture()
def station(tmp_path):
    """A registry of its own per test: snapshots write to disk, and a shared
    root would let one test see another's bundles."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "forests"
    root.mkdir()
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, root


def _key(registry, caps=("admin", "read"), principal="root", **grant):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), **grant)
    return {"Authorization": f"Bearer {key}"}


# -- health -----------------------------------------------------------------


def test_health_matches_the_rangers_own_report(station):
    """F.26: relayed, not recomputed. A host that reshapes the report becomes
    a second definition of the forest's health."""
    from monkeyllm import Vine
    from monkeyllm.ranger import Ranger

    client, registry, root = station
    served = client.get(f"/v1/admin/health?forest={FOREST}",
                        headers=_key(registry)).json()

    with Vine(root / FOREST, writable=False) as v:
        direct = Ranger(v).health()

    assert set(served) == set(direct)
    for field in ("needs_split", "fat_nodes", "stale_passports", "lint",
                  "uncertain_links"):
        assert served[field] == direct[field], field


def test_health_refuses_a_scoped_admin_with_the_reason(station):
    """A filtered report would carry numbers describing nodes the caller
    cannot see — the disclosure J.3 exists to prevent."""
    client, registry, _ = station
    headers = _key(registry, principal="scoped", allow=["projects/"])
    r = client.get(f"/v1/admin/health?forest={FOREST}", headers=headers)
    assert r.status_code == 403
    assert "whole forest" in r.json()["error"]["message"]


def test_health_needs_admin(station):
    client, registry, _ = station
    headers = _key(registry, caps=("read",), principal="reader")
    assert client.get(f"/v1/admin/health?forest={FOREST}",
                      headers=headers).status_code == 403


def test_health_needs_a_key(station):
    client, _, _ = station
    assert client.get(f"/v1/admin/health?forest={FOREST}").status_code == 401


def test_health_writes_nothing(station):
    """J.13: reporting only. Evaporation and promote/prune are the Ranger's
    own run, not a side effect of opening a console."""
    import subprocess

    client, registry, root = station
    head = lambda: subprocess.run(  # noqa: E731
        ["git", "-C", str(root / FOREST), "rev-parse", "HEAD"],
        capture_output=True, text=True).stdout.strip()

    before = head()
    client.get(f"/v1/admin/health?forest={FOREST}", headers=_key(registry))
    assert head() == before


# -- snapshots --------------------------------------------------------------


def test_snapshot_lands_outside_every_forest(station, tmp_path):
    """F.26: a bundle inside the tree would be a binary where A.3.1 keeps
    them out, and the next snapshot would package the last one."""
    client, registry, root = station
    r = client.post("/v1/admin/snapshots", json={"forest": FOREST},
                    headers=_key(registry))
    assert r.status_code == 200, r.text
    assert r.json()["bytes"] > 0

    assert not list((root / FOREST).rglob("*.bundle"))
    assert not list(root.glob("*.bundle"))
    assert list((tmp_path / "snapshots" / FOREST).glob("*.bundle"))


def test_a_second_snapshot_does_not_package_the_first(station, tmp_path):
    client, registry, _ = station
    headers = _key(registry)
    first = client.post("/v1/admin/snapshots", json={"forest": FOREST},
                        headers=headers).json()
    second = client.post("/v1/admin/snapshots", json={"forest": FOREST},
                         headers=headers).json()
    assert first["name"] != second["name"]
    # Same history, so the same size give or take packing — certainly not the
    # first bundle carried inside the second.
    assert second["bytes"] < first["bytes"] * 2


def test_snapshots_are_listed_after_being_taken(station):
    client, registry, _ = station
    headers = _key(registry)
    assert client.get(f"/v1/admin/snapshots?forest={FOREST}",
                      headers=headers).json()["snapshots"] == []
    taken = client.post("/v1/admin/snapshots", json={"forest": FOREST},
                        headers=headers).json()
    listed = client.get(f"/v1/admin/snapshots?forest={FOREST}",
                        headers=headers).json()["snapshots"]
    assert [s["name"] for s in listed] == [taken["name"]]
    assert listed[0]["created"].endswith("+00:00")


def test_snapshots_need_admin(station):
    client, registry, _ = station
    headers = _key(registry, caps=("read",), principal="reader")
    assert client.post("/v1/admin/snapshots", json={"forest": FOREST},
                       headers=headers).status_code == 403
    assert client.get(f"/v1/admin/snapshots?forest={FOREST}",
                      headers=headers).status_code == 403


def test_restore_is_not_exposed(station):
    """J.13 states it stays on the command line; the absence is the contract,
    so it is asserted rather than assumed."""
    client, registry, _ = station
    r = client.post("/v1/admin/snapshots/restore", json={"forest": FOREST},
                    headers=_key(registry))
    assert r.status_code == 404
