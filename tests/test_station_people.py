"""Person-shaped governance (spec J.2.3, criterion F.23).

Onboarding somebody is one decision with three consequences — access, a way
to sign in, a token for their scripts — so it is one request. The risk in a
convenience endpoint is that it becomes a shortcut *around* the rules it
composes, so most of what follows checks that it did not: each step is
still governed by the rule that governed it before, and a step the caller
may not perform is refused without discarding the steps they may.
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
    root = tmp_path_factory.mktemp("people")
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
        yield client, app.state.registry


def _boss(registry, forests=(MINE,), principal="boss"):
    key = registry.issue_key(principal)
    for f in forests:
        registry.grant(principal, f, {"read", "admin"})
    return {"Authorization": f"Bearer {key}"}


ONBOARD = {
    "principal": "nina",
    "grant": {"forest": MINE, "caps": ["read", "query"], "allow": ["projects/"]},
    "password": "a long enough passphrase",
    "issue_key": {"label": "nina's laptop", "expires_in_days": 30},
}


def test_onboarding_is_one_request(station):
    """The whole point: one call yields a working sign-in and a working
    token for a principal that did not exist a moment ago."""
    client, registry = station
    head = _boss(registry)

    r = client.post("/v1/admin/people", json=ONBOARD, headers=head)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == ["grant", "password", "issue_key"]
    assert body["refused"] == []

    # The password signs in.
    login = client.post("/v1/auth/login",
                        json={"username": "nina", "password": ONBOARD["password"]})
    assert login.status_code == 200
    assert login.json()["principal"] == "nina"

    # The key reads, inside the scope it was granted.
    work = {"Authorization": f"Bearer {body['api_key']}"}
    assert client.post(f"/v1/forests/{MINE}/look", json={"id": "projects/_index"},
                       headers=work).status_code == 200
    assert client.post(f"/v1/forests/{MINE}/look", json={"id": "_index"},
                       headers=work).status_code == 404   # outside 'projects/'


def test_the_grant_lands_before_the_credentials(station):
    """Normative ordering (J.2.3). With the credential steps first, a
    brand-new principal would have no grants, `administers_fully` would be
    vacuously true, and onboarding would depend on that accident."""
    client, registry = station
    head = _boss(registry)
    r = client.post("/v1/admin/people", json=ONBOARD, headers=head)
    assert r.json()["applied"].index("grant") == 0


def test_the_person_view_is_assembled_server_side(station):
    client, registry = station
    head = _boss(registry)
    client.post("/v1/admin/people", json=ONBOARD, headers=head)

    body = client.get("/v1/admin/people", headers=head).json()
    nina = next(p for p in body["people"] if p["id"] == "nina")
    assert nina["has_password"] is True
    assert nina["grants"][0]["allow"] == ["projects/"]
    assert nina["live_tokens"] == 1
    assert nina["tokens"][0]["label"] == "nina's laptop"
    assert nina["manageable"] is True
    assert body["forests"] == [MINE]


def test_last_seen_appears_after_the_token_is_used(station):
    client, registry = station
    head = _boss(registry)
    key = client.post("/v1/admin/people", json=ONBOARD, headers=head).json()["api_key"]

    before = next(p for p in client.get("/v1/admin/people", headers=head).json()["people"]
                  if p["id"] == "nina")
    assert before["last_seen"] is None

    client.post(f"/v1/forests/{MINE}/look", json={"id": "projects/_index"},
                headers={"Authorization": f"Bearer {key}"})
    after = next(p for p in client.get("/v1/admin/people", headers=head).json()["people"]
                 if p["id"] == "nina")
    assert after["last_seen"]


# -- maintenance from the same place ---------------------------------------


def test_clearing_the_password_removes_the_sign_in(station):
    client, registry = station
    head = _boss(registry)
    client.post("/v1/admin/people", json=ONBOARD, headers=head)

    r = client.post("/v1/admin/people",
                    json={"principal": "nina", "password": ""}, headers=head)
    assert r.json()["applied"] == ["password"]
    assert client.post("/v1/auth/login",
                       json={"username": "nina",
                             "password": ONBOARD["password"]}).status_code == 401


def test_revoking_every_key_stops_all_of_them(station):
    client, registry = station
    head = _boss(registry)
    first = client.post("/v1/admin/people", json=ONBOARD, headers=head).json()["api_key"]
    second = client.post("/v1/admin/people",
                         json={"principal": "nina", "issue_key": {"label": "ci"}},
                         headers=head).json()["api_key"]

    assert client.post("/v1/admin/people",
                       json={"principal": "nina", "revoke_keys": True},
                       headers=head).status_code == 200
    for key in (first, second):
        assert client.post(f"/v1/forests/{MINE}/look", json={"id": "projects/_index"},
                           headers={"Authorization": f"Bearer {key}"}).status_code == 401


def test_revoking_access_removes_the_grant(station):
    client, registry = station
    head = _boss(registry)
    client.post("/v1/admin/people", json=ONBOARD, headers=head)

    r = client.post("/v1/admin/people",
                    json={"principal": "nina", "revoke_access": MINE}, headers=head)
    assert r.json()["applied"] == ["revoke_access"]
    assert all(p["id"] != "nina"
               for p in client.get("/v1/admin/people", headers=head).json()["people"])


# -- several forests, one decision (J.2.3, v0.20) --------------------------


def test_one_grant_covers_several_forests(station):
    """The point of the set: a token for a group of forests is one request,
    not one request per forest that can stop halfway."""
    client, registry = station
    head = _boss(registry, forests=(MINE, THEIRS))

    r = client.post("/v1/admin/people", json={
        "principal": "ci",
        "grant": {"forests": [MINE, THEIRS], "caps": ["read"]},
        "issue_key": {"label": "pipeline"},
    }, headers=head)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == ["grant", "issue_key"]
    assert body["refused"] == []
    assert {g["forest"] for g in registry.grants_of("ci")} == {MINE, THEIRS}

    # And the key minted in the same request reads in both of them.
    work = {"Authorization": f"Bearer {body['api_key']}"}
    for forest in (MINE, THEIRS):
        assert client.post(f"/v1/forests/{forest}/look", json={"id": "_index"},
                           headers=work).status_code == 200


def test_the_scalar_form_still_means_one_forest(station):
    """v0.19 clients keep working: `forest` is a one-element `forests`."""
    client, registry = station
    head = _boss(registry, forests=(MINE, THEIRS))
    client.post("/v1/admin/people", json={
        "principal": "solo", "grant": {"forest": MINE, "caps": ["read"]},
    }, headers=head)
    assert [g["forest"] for g in registry.grants_of("solo")] == [MINE]


def test_a_forest_you_do_not_administer_is_refused_by_name(station):
    """Partial application *within* the step: the forests boss was entitled
    to grant still land, and the one they were not is named — a set must not
    become a way to smuggle a forest in beside a legitimate one."""
    client, registry = station
    head = _boss(registry)                      # administers MINE only

    r = client.post("/v1/admin/people", json={
        "principal": "creep", "grant": {"forests": [MINE, THEIRS], "caps": ["read"]},
    }, headers=head)

    assert r.status_code == 200
    body = r.json()
    assert body["applied"] == ["grant"]
    assert [(s["step"], s["forest"]) for s in body["refused"]] == [("grant", THEIRS)]
    assert [g["forest"] for g in registry.grants_of("creep")] == [MINE]


def test_a_grant_naming_only_forests_you_lack_applies_nothing(station):
    client, registry = station
    head = _boss(registry)
    r = client.post("/v1/admin/people", json={
        "principal": "creep", "grant": {"forests": [THEIRS], "caps": ["read"]},
    }, headers=head)
    assert r.status_code == 403
    assert r.json()["applied"] == []
    assert registry.grants_of("creep") == []


def test_scope_prefixes_apply_to_every_forest_named(station):
    """A grant is one policy expressed once (J.2.3)."""
    client, registry = station
    head = _boss(registry, forests=(MINE, THEIRS))
    client.post("/v1/admin/people", json={
        "principal": "scoped",
        "grant": {"forests": [MINE, THEIRS], "caps": ["read"], "allow": ["projects/"]},
    }, headers=head)
    assert all(g["allow"] == ["projects/"] for g in registry.grants_of("scoped"))


def test_revoking_access_takes_a_list(station):
    """Unticking forests in the console removes exactly those grants."""
    client, registry = station
    head = _boss(registry, forests=(MINE, THEIRS))
    registry.grant("wide", MINE, {"read"})
    registry.grant("wide", THEIRS, {"read"})

    r = client.post("/v1/admin/people",
                    json={"principal": "wide", "revoke_access": [THEIRS]}, headers=head)
    assert r.json()["applied"] == ["revoke_access"]
    assert [g["forest"] for g in registry.grants_of("wide")] == [MINE]


def test_revoking_a_forest_you_do_not_administer_is_refused_by_name(station):
    client, registry = station
    head = _boss(registry)                      # MINE only
    registry.grant("wide", MINE, {"read"})
    registry.grant("wide", THEIRS, {"read"})

    r = client.post("/v1/admin/people",
                    json={"principal": "wide", "revoke_access": [MINE, THEIRS]},
                    headers=head)
    body = r.json()
    assert body["applied"] == ["revoke_access"]
    assert [(s["step"], s["forest"]) for s in body["refused"]] \
        == [("revoke_access", THEIRS)]
    assert [g["forest"] for g in registry.grants_of("wide")] == [THEIRS]


def test_an_empty_forest_set_is_refused_not_silently_ignored(station):
    client, registry = station
    head = _boss(registry)
    r = client.post("/v1/admin/people", json={
        "principal": "x", "grant": {"forests": [], "caps": ["read"]},
    }, headers=head)
    assert r.status_code == 403
    assert "at least one forest" in r.json()["refused"][0]["message"]
    assert registry.grants_of("x") == []


# -- the composite is not an authority -------------------------------------


def test_a_partial_admin_may_grant_but_not_touch_credentials(station):
    """The load-bearing one. `boss` administers MINE only. `shared` also
    holds THEIRS, so their credentials are out of reach — but the grant on
    MINE that boss was entitled to make must still apply."""
    client, registry = station
    head = _boss(registry)
    registry.grant("shared", THEIRS, {"read"})

    r = client.post("/v1/admin/people", json={
        "principal": "shared",
        "grant": {"forest": MINE, "caps": ["read"]},
        "password": "should not be set",
        "issue_key": {"label": "should not exist"},
    }, headers=head)

    assert r.status_code == 200
    body = r.json()
    assert body["applied"] == ["grant"], body
    assert {s["step"] for s in body["refused"]} == {"password", "issue_key"}
    assert "api_key" not in body

    assert registry.has_password("shared") is False
    assert registry.keys_of(["shared"]) == []
    # The part they were entitled to did happen.
    assert any(g["forest"] == MINE for g in registry.grants_of("shared"))


def test_granting_a_forest_you_do_not_administer_is_refused(station):
    client, registry = station
    head = _boss(registry)
    r = client.post("/v1/admin/people", json={
        "principal": "sneak", "grant": {"forest": THEIRS, "caps": ["read"]},
    }, headers=head)
    assert r.status_code == 403
    assert r.json()["applied"] == []
    assert registry.grants_of("sneak") == []


def test_unknown_capabilities_are_refused(station):
    client, registry = station
    head = _boss(registry)
    r = client.post("/v1/admin/people", json={
        "principal": "x", "grant": {"forest": MINE, "caps": ["read", "root"]},
    }, headers=head)
    assert r.status_code == 403
    assert "root" in r.json()["refused"][0]["message"]


def test_the_environment_account_still_refuses_a_stored_password(
        two_forests, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.setenv("MONKEYLLM_STATION_ADMIN", "owner")
    monkeypatch.setenv("MONKEYLLM_STATION_PASSWORD", "env-only")
    app = build_app(root=two_forests, registry_path=tmp_path / "s.db", mcp=False)
    with TestClient(app) as client:
        key = client.post("/v1/auth/login",
                          json={"username": "owner", "password": "env-only"}).json()["key"]
        r = client.post("/v1/admin/people",
                        json={"principal": "owner", "password": "stored"},
                        headers={"Authorization": f"Bearer {key}"})
        assert r.json()["refused"][0]["step"] == "password"
        assert app.state.registry.has_password("owner") is False


def test_people_needs_admin(station):
    client, registry = station
    key = registry.issue_key("reader")
    registry.grant("reader", MINE, {"read", "write", "ingest"})
    head = {"Authorization": f"Bearer {key}"}
    assert client.get("/v1/admin/people", headers=head).status_code == 403
    assert client.post("/v1/admin/people", json={"principal": "x"},
                       headers=head).status_code == 403


def test_the_view_hides_forests_the_caller_does_not_administer(station):
    client, registry = station
    head = _boss(registry)
    registry.grant("dual", MINE, {"read"}, allow=["public/"])
    registry.grant("dual", THEIRS, {"read"}, allow=["confidential/"])

    body = client.get("/v1/admin/people", headers=head)
    dual = next(p for p in body.json()["people"] if p["id"] == "dual")
    assert [g["forest"] for g in dual["grants"]] == [MINE]
    assert "confidential/" not in body.text
    # Not fully administered, so their credentials are not listed either.
    assert dual["manageable"] is False and dual["tokens"] == []
