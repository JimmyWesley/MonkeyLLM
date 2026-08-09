# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""First-run setup and the owner bit (spec J.2.4, criterion F.28).

The bug these cover is not subtle once seen: a Station on an empty volume
granted its super-admin `admin` on every forest *in the registry*, of which
there were none, and J.7 then refused it the first forest because creating
one required `admin` on a forest that already existed. Two sound rules, one
deadlock, on the single occasion every deployment goes through.

So the interesting assertions here are about *absence* — no forest, no
credential, no second owner — and about a route that has to disappear
without leaving a trace that it ever existed.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from starlette.testclient import TestClient

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

from monkeyllm_station.app import build_app  # noqa: E402

OWNER = {"username": "jimmy", "password": "a-properly-long-password"}


@pytest.fixture()
def station(tmp_path, monkeypatch):
    """An empty registry with no environment super-admin: the first boot."""
    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    root = tmp_path / "forests"
    root.mkdir()
    return TestClient(build_app(root=root, registry_path=tmp_path / "station.db",
                                writable=True, mcp=False))


def auth(response) -> dict:
    return {"Authorization": f"Bearer {response.json()['key']}"}


def test_health_asks_for_setup_before_anybody_exists(station):
    body = station.get("/v1/health").json()
    assert body["setup_required"] is True
    # There is no password door yet either; the console must not offer a
    # sign-in form on a Station nobody can sign in to.
    assert body["password_login"] is False


def test_the_owner_governs_a_registry_with_no_forest_at_all(station):
    created = station.post("/v1/auth/setup", json=OWNER)
    assert created.status_code == 200
    assert created.json()["owner"] is True

    me = station.get("/v1/me", headers=auth(created)).json()
    # The deadlock in one assertion: admin while holding zero grants.
    assert me["grants"] == []
    assert me["admin"] is True and me["owner"] is True


def test_the_owner_creates_the_first_forest_and_can_read_it(station):
    headers = auth(station.post("/v1/auth/setup", json=OWNER))
    assert station.post("/v1/admin/forests", headers=headers,
                        json={"id": "main", "title": "Main"}).status_code == 200

    # "Present and future": a forest that did not exist when the owner was
    # created is theirs too, without any grant being written for it.
    assert station.post("/v1/forests/main/look", headers=headers,
                        json={"id": "_index"}).status_code == 200
    listed = station.get("/v1/forests", headers=headers).json()["forests"]
    assert [f["id"] for f in listed] == ["main"]
    assert "admin" in listed[0]["caps"]


def test_a_principal_without_grants_is_still_refused_the_first_forest(station):
    """The owner bit is the exception, not a hole: everyone else is unchanged."""
    owner = auth(station.post("/v1/auth/setup", json=OWNER))
    station.post("/v1/admin/forests", headers=owner,
                 json={"id": "main", "title": "Main"})
    station.post("/v1/admin/people", headers=owner,
                 json={"principal": "nobody", "password": "another-long-one"})

    theirs = auth(station.post("/v1/auth/login", json={
        "username": "nobody", "password": "another-long-one"}))
    refused = station.post("/v1/admin/forests", headers=theirs,
                           json={"id": "theirs", "title": "Theirs"})
    assert refused.status_code == 403


def test_a_closed_setup_is_indistinguishable_from_an_unrouted_path(station):
    station.post("/v1/auth/setup", json=OWNER)

    closed = station.post("/v1/auth/setup", json=OWNER)
    unrouted = station.post("/v1/auth/setup", json=OWNER)  # same path, now gone
    never_existed = station.post("/v1/auth/setup-x", json={})

    assert closed.status_code == never_existed.status_code == 404
    assert closed.json() == unrouted.json()
    # Byte-identical but for the path itself: "already configured" would
    # publish the deployment's state to anyone who asked.
    assert closed.json()["error"]["hint"] == never_existed.json()["error"]["hint"]
    assert closed.json()["error"]["message"] == "no such endpoint: /auth/setup"
    assert station.get("/v1/health").json()["setup_required"] is False


def test_concurrent_first_calls_produce_exactly_one_owner(station):
    """The whole security surface of an unauthenticated route.

    A check-then-write with a gap between them is a back door whose key is a
    race condition, so this runs the race rather than reading the code.
    """
    wins: list[bool] = []
    barrier = threading.Barrier(8)

    def attempt(i: int) -> None:
        barrier.wait()
        response = station.post("/v1/auth/setup", json={
            "username": f"owner{i}", "password": "a-properly-long-password"})
        wins.append(response.status_code == 200)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(wins) == 1, f"{sum(wins)} owners created"


def test_setup_refuses_a_password_that_governs_everything_and_is_tiny(station):
    refused = station.post("/v1/auth/setup",
                           json={"username": "jimmy", "password": "short"})
    assert refused.status_code == 400
    # Refusing must not consume the one-shot route.
    assert station.get("/v1/health").json()["setup_required"] is True
    assert station.post("/v1/auth/setup", json=OWNER).status_code == 200


def test_clearing_the_password_does_not_reopen_setup(station):
    """Otherwise removing a password would hand the Station to whoever asked
    next — the reason `setup_available` checks the owner separately."""
    headers = auth(station.post("/v1/auth/setup", json=OWNER))
    station.post("/v1/admin/password", headers=headers,
                 json={"principal": "jimmy", "password": None})
    assert station.get("/v1/health").json()["setup_required"] is False


def test_the_environment_super_admin_replaces_setup_rather_than_racing_it(
        tmp_path, monkeypatch):
    """One door at a time (J.2.4): a deployment that declared its first
    identity in the environment is not also up for grabs over HTTP."""
    monkeypatch.setenv("MONKEYLLM_STATION_ADMIN", "admin")
    monkeypatch.setenv("MONKEYLLM_STATION_PASSWORD", "break-glass-password")
    root = tmp_path / "forests"
    root.mkdir()
    client = TestClient(build_app(root=root, registry_path=tmp_path / "s.db",
                                  writable=True, mcp=False))

    assert client.get("/v1/health").json()["setup_required"] is False
    assert client.post("/v1/auth/setup", json=OWNER).status_code == 404

    # And it governs the empty registry, which is what it could not do before.
    session = client.post("/v1/auth/login", json={
        "username": "admin", "password": "break-glass-password"}).json()
    assert session["admin"] is True and session["owner"] is True
    assert client.post("/v1/admin/forests",
                       headers={"Authorization": f"Bearer {session['key']}"},
                       json={"id": "first", "title": "First"}).status_code == 200


def test_the_seeded_demo_is_a_forest_the_console_can_answer_from(station):
    """J.2.4's demo exists so `Ask` and `Explore` are not blank on day one."""
    headers = auth(station.post("/v1/auth/setup", json=OWNER))
    assert station.post("/v1/admin/forests", headers=headers,
                        json={"id": "demo", "title": "Demo forest",
                              "seed": "demo"}).status_code == 200

    located = station.post("/v1/forests/demo/locate", headers=headers,
                           json={"query": "how is scope enforced", "k": 3}).json()
    assert located["results"], "the demo must answer the question it teaches"

    # The demo's own lesson: a body-only fact that `locate` cannot see.
    assert station.post("/v1/forests/demo/locate", headers=headers,
                        json={"query": "pangolin"}).json()["results"] == []
    assert station.post("/v1/forests/demo/sniff", headers=headers,
                        json={"terms": ["pangolin"]}).json()["results"]


def test_a_registry_written_before_v0_25_upgrades_in_place(tmp_path):
    """The owner bit arrives as a migration, and its unique index cannot run
    until the column exists — so ordering it wrong takes down every Station
    that upgrades rather than starts fresh. This is that upgrade.
    """
    import sqlite3

    from monkeyllm_station.registry import Registry

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE principals (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'service',
            created TEXT NOT NULL, pw_salt TEXT, pw_hash TEXT);
        INSERT INTO principals (id, kind, created) VALUES ('alice', 'user', '2026-01-01');
    """)
    old.commit()
    old.close()

    registry = Registry(path)
    try:
        # Nothing lost, and the new column defaulted rather than nulled.
        assert registry.is_owner("alice") is False
        assert registry.owner_id() is None
        # And the guarantee is live on the upgraded database, not just on
        # freshly created ones.
        assert registry.create_owner("alice2", "a-properly-long-password") is True
        assert registry.create_owner("alice3", "a-properly-long-password") is False
        assert registry.owner_id() == "alice2"
    finally:
        registry.close()


def test_an_unknown_seed_is_refused_rather_than_silently_ignored(station):
    headers = auth(station.post("/v1/auth/setup", json=OWNER))
    refused = station.post("/v1/admin/forests", headers=headers,
                           json={"id": "x", "title": "X", "seed": "bogus"})
    assert refused.status_code == 400
    assert "bogus" in refused.json()["error"]["message"]
