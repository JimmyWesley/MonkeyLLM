"""Station Phase A (spec J.1/J.2/J.3): auth, capabilities, and the two
oracle-shaped invariants the host can already honour at forest granularity.

The Station is a separate deployable (`apps/station/`), but its tests live in
the one suite that must stay green — and the package is imported the way the
repo's scripts do it, by path, since it is not installed in dev.

The full leak suite (F.18: one test per primitive per surface, node-level
scoping) lands with T08, when prefix policies become enforceable.
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

    app = build_app(root=station_root, registry_path=tmp_path / "station.db")
    # TestClient's context manager runs the lifespan, so shutdown closes the
    # pool inside its own forest thread — the same path production takes.
    with TestClient(app) as client:
        yield client, app.state.registry


def _key(registry, caps=("read",), forest=FOREST, principal="alice"):
    key = registry.issue_key(principal)
    registry.grant(principal, forest, set(caps))
    return {"Authorization": f"Bearer {key}"}


def test_health_is_open(station):
    client, _ = station
    r = client.get("/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


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


def test_write_primitives_are_not_exposed_in_phase_a(station):
    """Writes wait for J.4 principal-stamped commits — an unattributed write
    endpoint is worse than none."""
    client, registry = station
    headers = _key(registry, caps=("read", "write", "tend", "admin"))
    for name in ("plant", "graft", "tend"):
        assert client.post(f"/v1/forests/{FOREST}/{name}", json={},
                           headers=headers).status_code == 404, name


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


def test_prefix_policy_is_refused_until_t08(station):
    """Safe failure mode: the Station refuses a policy it cannot enforce
    rather than accepting it and serving everything."""
    from monkeyllm_station.policy import Policy

    with pytest.raises(NotImplementedError):
        Policy(forest=FOREST, caps=frozenset({"read"}), allow=("projects/",))
    with pytest.raises(NotImplementedError):
        Policy(forest=FOREST, caps=frozenset({"read"}), deny=("projects/secret/",))


def test_unknown_capability_is_rejected(station):
    _, registry = station
    with pytest.raises(ValueError):
        registry.grant("dave", FOREST, {"read", "superuser"})
