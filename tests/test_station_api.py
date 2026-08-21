# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Station Phase A (spec J.1/J.2/J.3): auth, capabilities, and the two
oracle-shaped invariants the host can already honour at forest granularity.

The Station is a separate deployable (`apps/station/`), but its tests live in
the one suite that must stay green — and the package is imported the way the
repo's scripts do it, by path, since it is not installed in dev.

The full leak suite (F.18: one test per primitive per surface, node-level
scoping) lands with T08, when prefix policies become enforceable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

from monkeyllm.errors import E_LOCKED

FOREST = "forest-fixture"


@pytest.fixture(scope="session")
def station_root(tmp_path_factory) -> Path:
    """A forest registry: one root directory holding one forest."""
    root = tmp_path_factory.mktemp("registry-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(station_root, tmp_path):
    """(TestClient, Registry) with no principals yet — each test grants what
    it needs, so default-deny is exercised rather than assumed."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=station_root, registry_path=tmp_path / "station.db", mcp=False)
    # TestClient's context manager runs the lifespan, so shutdown closes the
    # pool inside its own forest thread — the same path production takes.
    with TestClient(app) as client:
        yield client, app.state.registry


def _close_pool(client):
    """Close every open vine, each in the thread that opened it.

    A SQLite connection belongs to its thread and the Station confines every
    forest touch to its own lane (J.9); `state.forest_lane(forest)` is that
    thread, and it is how anything outside a request gets in there.
    """
    state = client.app.state
    for entry in state.pool.list()["forests"]:
        if entry["active"]:
            fid = entry["id"]
            state.forest_lane(fid).submit(
                lambda fid=fid: state.pool.close_one(fid)).result()


def _key(registry, caps=("read",), forest=FOREST, principal="alice"):
    key = registry.issue_key(principal)
    registry.grant(principal, forest, set(caps))
    return {"Authorization": f"Bearer {key}"}


def test_health_is_open(station):
    client, _ = station
    r = client.get("/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_studio_is_served(station):
    client, _ = station
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "MonkeyLLM Studio" in r.text


def test_studio_holds_no_credentials(station):
    """Studio is a plain REST client (J.5): whatever it can do, an API client
    with the same principal can do — so it must ship no key of its own."""
    import re

    client, _ = station
    # the placeholder text "mk_..." is fine; an actual minted key is not
    assert not re.search(r"mk_[A-Za-z0-9_-]{20,}", client.get("/").text)


def test_no_key_is_401(station):
    client, _ = station
    assert client.get("/v1/forests").status_code == 401
    assert client.post(f"/v1/forests/{FOREST}/locate", json={"query": "x"}).status_code == 401


def test_bad_key_is_401(station):
    client, _ = station
    r = client.get("/v1/forests", headers={"Authorization": "Bearer mk_not-a-real-key"})
    assert r.status_code == 401


def test_forests_lists_only_granted(station):
    client, registry = station
    r = client.get("/v1/forests", headers=_key(registry))
    assert r.status_code == 200
    assert [f["id"] for f in r.json()["forests"]] == [FOREST]


def test_forests_empty_without_grant(station):
    """Authenticated but ungranted: deny-by-default (J.3)."""
    client, registry = station
    key = registry.issue_key("bob")
    r = client.get("/v1/forests", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200 and r.json()["forests"] == []


def test_locate_returns_results(station):
    client, registry = station
    r = client.post(f"/v1/forests/{FOREST}/locate",
                    json={"query": "stigmergy", "k": 3}, headers=_key(registry))
    assert r.status_code == 200
    assert r.json()["results"] and all("id" in hit for hit in r.json()["results"])


def test_look_and_harvest_round_trip(station):
    client, registry = station
    headers = _key(registry)
    r = client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"}, headers=headers)
    assert r.status_code == 200 and r.json()["id"] == "_index"
    r = client.post(f"/v1/forests/{FOREST}/harvest",
                    json={"query": "stigmergy", "k": 2}, headers=headers)
    assert r.status_code == 200 and "results" in r.json()


def test_missing_node_is_404_envelope(station):
    client, registry = station
    r = client.post(f"/v1/forests/{FOREST}/look",
                    json={"id": "nope/does-not-exist"}, headers=_key(registry))
    assert r.status_code == 404 and r.json()["error"]["code"] == "E_NOT_FOUND"


def test_ungranted_forest_is_indistinguishable_from_absent(station):
    """J.3's existence-oracle rule applied at forest granularity: 'you may
    not' and 'there is no such thing' MUST look identical, or the API
    enumerates the registry."""
    client, registry = station
    headers = _key(registry)  # granted on FOREST only
    ungranted = client.post("/v1/forests/forest-fixture-2/locate",
                            json={"query": "x"}, headers=headers)
    absent = client.post("/v1/forests/no-such-forest-at-all/locate",
                         json={"query": "x"}, headers=headers)
    assert ungranted.status_code == absent.status_code == 404
    assert ungranted.json() == absent.json() or (
        ungranted.json()["error"]["code"] == absent.json()["error"]["code"]
        and ungranted.json()["error"]["hint"] == absent.json()["error"]["hint"]
    )


def test_query_requires_query_cap(station):
    client, registry = station
    r = client.post(f"/v1/forests/{FOREST}/query",
                    json={"id": "sales/report-q1-2026", "sql": "SELECT 1"},
                    headers=_key(registry, caps=("read",)))
    assert r.status_code == 403 and r.json()["error"]["code"] == "E_FORBIDDEN"


def test_query_works_with_cap(station):
    client, registry = station
    r = client.post(f"/v1/forests/{FOREST}/query",
                    json={"id": "sales/report-q1-2026",
                          "sql": "SELECT region, SUM(value) AS total FROM sales GROUP BY region"},
                    headers=_key(registry, caps=("read", "query")))
    assert r.status_code == 200 and r.json()["rows"]


def test_writes_require_the_write_cap(station):
    client, registry = station
    r = client.post(f"/v1/forests/{FOREST}/plant",
                    json={"node": {"id": "notes/x", "parent": "notes/_index",
                                   "type": "note", "title": "X", "summary": "y"}},
                    headers=_key(registry, caps=("read",)))
    assert r.status_code == 403 and r.json()["error"]["code"] == "E_FORBIDDEN"


def test_write_is_attributed_to_the_principal(station, station_root):
    """J.4: the commit the engine made must name who asked for it."""
    import subprocess

    client, registry = station
    headers = _key(registry, caps=("read", "write"), principal="writer")
    r = client.post(
        f"/v1/forests/{FOREST}/plant",
        json={"node": {"id": "notes/station-made-this", "parent": "notes/_index",
                       "type": "note", "title": "Station made this",
                       "summary": "A node planted through the Station, for attribution."}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    sha = r.json()["commit"]
    root = station_root / FOREST
    message = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%B", sha],
                             capture_output=True, text=True)
    assert message.returncode == 0, "the returned sha must exist after amending"
    assert "station-principal: writer" in message.stdout


def test_reads_and_writes_are_audited(station):
    client, registry = station
    headers = _key(registry, caps=("read",), principal="watched")
    client.post(f"/v1/forests/{FOREST}/locate", json={"query": "stigmergy"}, headers=headers)
    entries = registry.audit(limit=10, principal="watched")
    assert entries and entries[0]["primitive"] == "locate"
    assert entries[0]["forest"] == FOREST


def test_audit_stores_no_content(station):
    """The log records access, not what was read (J.4)."""
    client, registry = station
    headers = _key(registry, caps=("read",), principal="watched")
    secret = "x" * 500
    client.post(f"/v1/forests/{FOREST}/locate", json={"query": secret}, headers=headers)
    entry = registry.audit(limit=1, principal="watched")[0]
    assert secret not in entry["args"] and "chars>" in entry["args"]


def test_bad_body_is_400(station):
    client, registry = station
    headers = _key(registry)
    r = client.post(f"/v1/forests/{FOREST}/locate", content=b"{not json",
                    headers={**headers, "content-type": "application/json"})
    assert r.status_code == 400
    r = client.post(f"/v1/forests/{FOREST}/locate", json={"bogus_param": 1}, headers=headers)
    assert r.status_code == 400 and r.json()["error"]["code"] == "E_SCHEMA"


def test_keys_are_stored_hashed_only(station):
    _, registry = station
    key = registry.issue_key("carol")
    stored = [r[0] for r in registry.conn.execute("SELECT key_hash FROM api_keys")]
    assert key not in stored
    assert registry.authenticate(key) == "carol"
    assert registry.authenticate("mk_wrong") is None


def test_scoped_principal_sees_only_its_subtree_over_rest(station):
    """The leak suite proves this at the library surface; this is the same
    guarantee arriving through HTTP."""
    client, registry = station
    key = registry.issue_key("scoped")
    registry.grant("scoped", FOREST, {"read"}, allow=["projects/"])
    headers = {"Authorization": f"Bearer {key}"}

    hits = client.post(f"/v1/forests/{FOREST}/locate",
                       json={"query": "model", "k": 5}, headers=headers).json()["results"]
    assert hits and all(h["id"].startswith("projects/") for h in hits)

    hidden = client.post(f"/v1/forests/{FOREST}/look",
                         json={"id": "people/jimmy-wesley"}, headers=headers)
    absent = client.post(f"/v1/forests/{FOREST}/look",
                         json={"id": "projects/nope-not-real"}, headers=headers)
    assert hidden.status_code == absent.status_code == 404
    assert hidden.json()["error"]["hint"] == absent.json()["error"]["hint"]


def test_me_reports_roots_for_a_scoped_principal(station):
    client, registry = station
    key = registry.issue_key("scoped")
    registry.grant("scoped", FOREST, {"read"}, allow=["projects/"])
    body = client.get("/v1/me", headers={"Authorization": f"Bearer {key}"}).json()
    assert body["principal"] == "scoped"
    assert body["grants"][0]["roots"] == ["projects/_index"]


def test_unknown_capability_is_rejected(station):
    _, registry = station
    with pytest.raises(ValueError):
        registry.grant("dave", FOREST, {"read", "superuser"})


def test_an_orphan_lock_heals_and_a_live_one_is_named(station, station_root):
    """C.9 (v0.55): the lock is possession, not existence.

    A file left by a dead writer — which is how server processes end — used
    to be a total outage repaired only by shell access. It now heals at the
    next open. A LIVE writer still refuses, with `E_LOCKED` naming its card
    rather than `_unknown_forest`: a grant already tells the caller the
    forest exists (J.3), and "you typed the wrong name" sent operators
    hunting for a mistake that was not there.
    """
    from monkeyllm.forest import WriterLock

    client, registry = station
    headers = _key(registry, caps=("read", "write"))

    # Boot warming (J.6.1) leaves this forest open and holding its own lock,
    # so the pool is emptied first and the leftover written after: a forest
    # nobody has open, with a lock somebody left behind.
    _close_pool(client)
    lock = station_root / FOREST / ".vine.lock"
    lock.write_text("999999", encoding="utf-8")
    try:
        r = client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                        headers=headers)
        assert r.status_code == 200, r.text  # the orphan healed, silently
    finally:
        _close_pool(client)

    holder = WriterLock(station_root / FOREST)
    holder.acquire()
    try:
        # J.6.2 (v0.57): a held writer lock stops writes, not reads — the
        # readers take no lock, so the read keeps serving...
        r = client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                        headers=headers)
        assert r.status_code == 200, r.text
        # ...while the write answers E_LOCKED naming the holder's card.
        r = client.post(
            f"/v1/forests/{FOREST}/plant",
            json={"node": {"id": "locked-probe", "type": "note",
                           "title": "Locked probe",
                           "summary": "A write under a live foreign "
                                      "writer lock must refuse.",
                           "parent": "_index"}},
            headers=headers)
        assert r.status_code == 409, r.text
        err = r.json()["error"]
        assert err["code"] == E_LOCKED
        assert str(os.getpid()) in err["message"]  # the card, quoted
    finally:
        holder.release()
        _close_pool(client)


def test_an_ungranted_forest_stays_an_unknown_forest(station):
    """The oracle guard the test above must not have weakened."""
    client, registry = station
    headers = _key(registry, caps=("read",))
    r = client.post("/v1/forests/no-such-forest/look", json={"id": "_index"},
                    headers=headers)
    assert r.status_code == 404
    assert "unknown forest" in r.json()["error"]["message"]
