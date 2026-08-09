"""Per-forest administration (spec J.3.2, criterion F.22).

Two different questions, easily conflated, and conflating them was the bug:

1. *May this caller enter the route?*  — `admin` anywhere.
2. *What may they see inside it?*      — only forests they administer.

Every `/v1/admin/*` route answered (1) correctly from the start. Several
answered (2) with "everything", so an administrator of one forest could
read every principal's branch prefixes and the complete audit log of
forests they cannot even open.

`test_every_admin_route_refuses_a_non_admin` enumerates the app's own route
table rather than a hand-written list, because the failure mode worth
guarding against is a *new* route that forgets the check — and a list
written by hand forgets it in exactly the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

MINE = "forest-mine"
THEIRS = "forest-theirs"


@pytest.fixture(scope="session")
def two_forests(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("admin-scope")
    build_forest(root / MINE)
    build_forest(root / THEIRS)
    return root


@pytest.fixture()
def station(two_forests, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    app = build_app(root=two_forests, registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, app


def _key(registry, principal, forest, caps):
    key = registry.issue_key(principal)
    registry.grant(principal, forest, set(caps))
    return {"Authorization": f"Bearer {key}"}


def _populate(registry):
    """Two worlds that must not see each other."""
    registry.grant("ours", MINE, {"read"}, allow=["public/"])
    registry.grant("theirs", THEIRS, {"read"}, allow=["confidential/"])
    registry.issue_key("theirs", label="their-ci")


# -- (1) may they enter at all ---------------------------------------------


def _admin_routes(app):
    """(path, method) pairs taken from the app's own table, so a route added
    tomorrow is swept tomorrow without anyone remembering to add it here."""
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/v1/admin/"):
            out += [(path, m) for m in sorted(r.methods - {"HEAD", "OPTIONS"})]
    return sorted(out)


def test_the_route_table_is_what_we_think_it_is(station):
    """A canary: if a route is added, this fails and the author has to decide
    consciously whether the sweep below covers it."""
    _, _, app = station
    assert _admin_routes(app) == [
        ("/v1/admin/audit", "GET"),
        ("/v1/admin/canopy", "GET"), ("/v1/admin/canopy", "POST"),
        ("/v1/admin/forests", "POST"),
        ("/v1/admin/grant", "POST"),
        ("/v1/admin/health", "GET"),
        ("/v1/admin/keys", "GET"), ("/v1/admin/keys", "POST"),
        ("/v1/admin/models", "GET"), ("/v1/admin/models", "POST"),
        ("/v1/admin/password", "POST"),
        ("/v1/admin/people", "GET"), ("/v1/admin/people", "POST"),
        ("/v1/admin/principals", "GET"),
        ("/v1/admin/providers", "GET"), ("/v1/admin/providers", "POST"),
        ("/v1/admin/providers/test", "POST"),
        ("/v1/admin/snapshots", "GET"), ("/v1/admin/snapshots", "POST"),
    ]


def test_every_admin_route_refuses_a_non_admin(station):
    client, registry, app = station
    head = _key(registry, "reader", MINE, {"read", "query", "write", "tend", "ingest"})

    got = {}
    for path, method in _admin_routes(app):
        got[f"{method} {path}"] = client.request(
            method, path, json={"forest": MINE, "principal": "reader"},
            headers=head).status_code

    assert got, "the sweep found no routes, which would make it vacuous"
    assert all(code == 403 for code in got.values()), got


def test_every_admin_route_refuses_an_anonymous_caller(station):
    client, _, app = station
    for path, method in _admin_routes(app):
        r = client.request(method, path, json={})
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


def test_an_unknown_v1_path_answers_as_the_api(station):
    """Not a leak, but a real annoyance: unmatched /v1 paths used to fall
    through to the static file server and answer with the console's HTML."""
    client, _, _ = station
    r = client.get("/v1/admin/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "E_NOT_FOUND"
    # And a POST-only route reached with GET says so instead of serving HTML.
    html = client.get("/v1/admin/forests")
    assert "text/html" not in html.headers.get("content-type", "")


# -- (2) what may they see inside ------------------------------------------


def test_an_admin_of_one_forest_sees_no_principal_of_the_other(station):
    client, registry, _ = station
    _populate(registry)
    head = _key(registry, "boss", MINE, {"read", "admin"})

    body = client.get("/v1/admin/principals", headers=head)
    assert body.status_code == 200
    people = body.json()["principals"]
    names = {p["id"] for p in people}

    assert "ours" in names
    assert "theirs" not in names, "a principal of another forest was disclosed"
    # And no row mentions the other forest, in any field.
    assert THEIRS not in body.text
    # Including the branch prefixes, which describe somebody's world.
    assert "confidential/" not in body.text
    assert any("public/" in str(g["allow"])
               for p in people for g in p["grants_detail"] if p["id"] == "ours")


def test_an_admin_of_one_forest_sees_no_audit_entry_of_the_other(station):
    client, registry, _ = station
    _populate(registry)
    # Generate real traffic in both forests.
    for forest, principal in ((MINE, "ours"), (THEIRS, "theirs")):
        key = registry.issue_key(principal, label=f"{principal}-work")
        client.post(f"/v1/forests/{forest}/look", json={"id": "_index"},
                    headers={"Authorization": f"Bearer {key}"})

    head = _key(registry, "boss", MINE, {"read", "admin"})
    body = client.get("/v1/admin/audit?limit=200", headers=head)
    assert body.status_code == 200
    entries = body.json()["entries"]

    assert entries, "the filter must not empty the log for a legitimate admin"
    assert {e["forest"] for e in entries} == {MINE}
    assert THEIRS not in body.text


def test_an_admin_of_both_sees_both(station):
    """The filter must narrow, not break: over-restricting is a bug too."""
    client, registry, _ = station
    _populate(registry)
    key = registry.issue_key("owner")
    for forest in (MINE, THEIRS):
        registry.grant("owner", forest, {"read", "admin"})
        client.post(f"/v1/forests/{forest}/look", json={"id": "_index"},
                    headers={"Authorization": f"Bearer {key}"})
    head = {"Authorization": f"Bearer {key}"}

    names = {p["id"] for p in client.get("/v1/admin/principals",
                                         headers=head).json()["principals"]}
    assert {"ours", "theirs"} <= names

    forests = {e["forest"] for e in
               client.get("/v1/admin/audit?limit=200", headers=head).json()["entries"]}
    assert forests == {MINE, THEIRS}


def test_the_audit_limit_still_holds_after_filtering(station):
    client, registry, _ = station
    key = registry.issue_key("busy")
    registry.grant("busy", MINE, {"read"})
    for _ in range(12):
        client.post(f"/v1/forests/{MINE}/look", json={"id": "_index"},
                    headers={"Authorization": f"Bearer {key}"})

    head = _key(registry, "boss", MINE, {"read", "admin"})
    entries = client.get("/v1/admin/audit?limit=5", headers=head).json()["entries"]
    assert len(entries) == 5


def test_grant_and_models_stay_per_forest(station):
    """These two already took a forest argument; the check is that they
    still refuse the forest the caller does not administer."""
    client, registry, _ = station
    head = _key(registry, "boss", MINE, {"read", "admin"})

    assert client.post("/v1/admin/grant",
                       json={"principal": "x", "forest": THEIRS, "caps": ["read"]},
                       headers=head).status_code == 403
    assert client.get(f"/v1/admin/models?forest={THEIRS}",
                      headers=head).status_code == 403
    assert client.get(f"/v1/admin/models?forest={MINE}",
                      headers=head).status_code == 200
