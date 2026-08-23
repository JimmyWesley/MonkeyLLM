# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

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
        ("/v1/admin/cache", "GET"), ("/v1/admin/cache", "POST"),
        ("/v1/admin/canopy", "GET"), ("/v1/admin/canopy", "POST"),
        ("/v1/admin/forests", "POST"),
        ("/v1/admin/grant", "POST"),
        ("/v1/admin/health", "GET"),
        ("/v1/admin/keys", "GET"), ("/v1/admin/keys", "POST"),
        # The C.9 lock, inspected (v0.55, J.13.5): admin_gate like health,
        # so the sweeps below cover it as they do every gated route.
        ("/v1/admin/locks", "GET"),
        ("/v1/admin/models", "GET"), ("/v1/admin/models", "POST"),
        ("/v1/admin/password", "POST"),
        ("/v1/admin/people", "GET"), ("/v1/admin/people", "POST"),
        ("/v1/admin/principals", "GET"),
        ("/v1/admin/providers", "GET"), ("/v1/admin/providers", "POST"),
        ("/v1/admin/providers/test", "POST"),
        # Re-derive what ingest derives (v0.61, J.13.6): the same gate as the
        # rebuild, plus a write — so a read-only Station refuses it too.
        ("/v1/admin/recurate", "POST"),
        # The catalog rebuild (v0.41, J.13.3): `admin` on the forest and an
        # unrestricted scope, so the sweeps below cover it as they do health.
        ("/v1/admin/reindex", "POST"),
        ("/v1/admin/snapshots", "GET"), ("/v1/admin/snapshots", "POST"),
        # Snapshot travel (v0.39): both owner-only, so the non-admin and
        # anonymous sweeps below cover them like every other admin route.
        ("/v1/admin/snapshots/import", "POST"),
        ("/v1/admin/snapshots/{forest}/{file}", "GET"),
        # The upload staging area, seen and cleared (v0.61, J.8): the same
        # gate as the rebuild, so the sweeps below cover it.
        ("/v1/admin/staging", "GET"), ("/v1/admin/staging", "POST"),
        # An orphan lock, released over HTTP (v0.55, J.13.5): admin_gate,
        # audited, and constitutionally unable to break a live writer.
        ("/v1/admin/unlock", "POST"),
    ]


def test_every_admin_route_refuses_a_non_admin(station):
    client, registry, app = station
    head = _key(registry, "reader", MINE, {"read", "query", "write", "tend", "ingest"})

    got = {}
    for path, method in _admin_routes(app):
        # The forest travels in the query AND in the body: since v0.52 a
        # route that was not told which forest answers E_SCHEMA (C.12 rule
        # 6), and a sweep that sent malformed requests would be asserting
        # that a missing parameter is a denial — the exact confusion that
        # rule removes. Every request here is well-formed, so the status is
        # about authority and nothing else.
        got[f"{method} {path}"] = client.request(
            method, path, params={"forest": MINE},
            json={"forest": MINE, "principal": "reader"},
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


# -- (3) whose credentials may they touch (J.2.2 + J.2.4) -------------------


def test_the_owner_is_not_administered_by_a_forest_admin(station):
    """The owner's authority is a bit, not grant rows (J.2.4).

    J.2.2 decides "may I touch this person's credentials?" by comparing the
    forests they hold against the forests I administer. The owner holds no
    grants at all, so that comparison has nothing to say about them and the
    rule has to name them outright: minting a key for the owner, or resetting
    their password, is the owner's alone.
    """
    client, registry, _ = station
    assert client.post("/v1/auth/setup",
                       json={"username": "boss",
                             "password": "correct-horse-battery"}).status_code == 200
    head = _key(registry, "mallory", MINE, {"read", "admin"})

    r = client.post("/v1/admin/people",
                    json={"principal": "boss", "issue_key": {"label": "x"}},
                    headers=head)
    assert "api_key" not in r.json()
    assert r.json()["refused"]

    r = client.post("/v1/admin/people",
                    json={"principal": "boss", "password": "some-other-password"},
                    headers=head)
    assert "password" not in r.json()["applied"]
    # The real owner's password still works, so this was a refusal and not a
    # silent change.
    assert client.post("/v1/auth/login",
                       json={"username": "boss",
                             "password": "correct-horse-battery"}).status_code == 200


def test_a_principal_with_no_grant_is_not_everybody_s_to_credential(station):
    """The same comparison, for a principal with no grants and no owner bit:
    sharing no forest with me is not the same as my administering every
    forest they hold. Onboarding is unaffected — J.2.3 applies the grant
    first, in the same request, and that ordering is why."""
    client, registry, _ = station
    registry.add_principal("orphan", kind="user")
    head = _key(registry, "boss", MINE, {"read", "admin"})

    r = client.post("/v1/admin/people",
                    json={"principal": "orphan", "issue_key": {"label": "x"}},
                    headers=head)
    assert "api_key" not in r.json()
    assert r.json()["refused"]

    r = client.post("/v1/admin/people",
                    json={"principal": "newcomer",
                          "grant": {"forest": MINE, "caps": ["read"]},
                          "issue_key": {"label": "x"}}, headers=head)
    assert r.json()["api_key"], "granting then crediting in one call must still work"


# -- (4) deployment-wide configuration (J.10) -------------------------------


def test_an_admin_of_one_forest_cannot_edit_a_provider(station):
    """A provider is one row serving every forest: its endpoint decides where
    all of their material is sent and its key pays for all of their calls.
    Administering one forest of several is not authority over that."""
    client, registry, _ = station
    registry.put_provider("prod", "https://api.example/v1", "sk-stored")
    head = _key(registry, "mallory", MINE, {"read", "admin"})

    assert client.post("/v1/admin/providers",
                       json={"name": "prod", "endpoint": "http://elsewhere/v1"},
                       headers=head).status_code == 403
    assert client.post("/v1/admin/providers/test",
                       json={"name": "prod", "endpoint": "http://elsewhere/v1"},
                       headers=head).status_code == 403
    # Reading the list stays open to any administrator: a per-forest model
    # binding points at these names, and no secret is in the answer.
    listed = client.get("/v1/admin/providers", headers=head)
    assert listed.status_code == 200
    assert "sk-stored" not in listed.text

    secret = registry.provider_secret("prod")
    assert secret["endpoint"] == "https://api.example/v1"


# -- (5) governance leaves a trail (J.4) ------------------------------------


GOVERNANCE_CALLS = [
    ("/v1/admin/grant", {"principal": "newbie", "forest": MINE, "caps": ["read"]}),
    ("/v1/admin/people", {"principal": "newbie", "issue_key": {"label": "ci"}}),
    ("/v1/admin/password", {"principal": "newbie", "password": "a-long-enough-one"}),
    ("/v1/admin/models", {"forest": MINE, "role": "answer",
                          "provider": "p", "model": "m"}),
]


@pytest.mark.parametrize("path,body", GOVERNANCE_CALLS,
                         ids=[c[0] for c in GOVERNANCE_CALLS])
def test_a_governance_change_is_recorded(station, path, body):
    """Part D audits what was read and written. These are the changes that
    decide who may do either, and a review after the fact starts from them:
    when was this key made, this grant widened, this password reset."""
    client, registry, _ = station
    key = registry.issue_key("boss")
    for forest in (MINE, THEIRS):
        registry.grant("boss", forest, {"read", "admin"})
    head = {"Authorization": f"Bearer {key}"}
    client.post("/v1/admin/providers", headers=head,
                json={"name": "p", "endpoint": "https://api.example/v1",
                      "api_key": "sk-x"})
    # The credential steps need a target that already holds a forest (J.2.2),
    # which the grant case below is what creates in real onboarding.
    registry.grant("newbie", MINE, {"read"})

    before = len(registry.audit(limit=1000))
    res = client.post(path, json=body, headers=head)
    assert res.status_code == 200, res.text
    after = registry.audit(limit=1000)
    assert len(after) > before, f"{path} left no trace"
    assert not any("sk-x" in str(e["args"]) or "a-long-enough-one" in str(e["args"])
                   for e in after), "a secret reached the log"


def test_a_login_is_recorded_whether_or_not_it_works(station):
    """The limiter counts failures in memory and forgets them on restart, so
    without this there is no answer to "was anyone trying yesterday?"."""
    client, registry, _ = station
    client.post("/v1/auth/setup", json={"username": "boss", "password": "correct-horse"})

    client.post("/v1/auth/login", json={"username": "boss", "password": "wrong"})
    client.post("/v1/auth/login", json={"username": "boss", "password": "correct-horse"})

    logins = [e for e in registry.audit(limit=1000) if e["primitive"] == "auth.login"]
    assert {e["result"] for e in logins} == {"ok", "refused"}
    assert not any("correct-horse" in str(e["args"]) for e in logins)


def test_the_governance_trail_is_not_read_by_one_forest_s_admin(station):
    """Those rows describe the deployment — who holds what, where the
    provider points. Handing them to an administrator of one forest is the
    mistake J.3.2 corrected for content."""
    client, registry, _ = station
    client.post("/v1/auth/setup", json={"username": "boss", "password": "correct-horse"})
    owner = client.post("/v1/auth/login",
                        json={"username": "boss", "password": "correct-horse"}).json()["key"]
    head = _key(registry, "mallory", MINE, {"read", "admin"})

    seen = client.get("/v1/admin/audit?limit=200", headers=head).json()["entries"]
    assert not any(e["forest"] == "-" for e in seen)
    assert not any(e["primitive"].startswith("auth.") for e in seen)

    owner_sees = client.get("/v1/admin/audit?limit=200",
                            headers={"Authorization": f"Bearer {owner}"}).json()["entries"]
    assert any(e["forest"] == "-" for e in owner_sees)


def test_an_admin_of_every_forest_may_edit_a_provider(station):
    """The rule is reach, not the owner bit — otherwise the break-glass
    account (J.2.1) and every single-forest deployment lose provider repair."""
    client, registry, _ = station
    key = registry.issue_key("both")
    for forest in (MINE, THEIRS):
        registry.grant("both", forest, {"read", "admin"})
    head = {"Authorization": f"Bearer {key}"}

    assert client.post("/v1/admin/providers",
                       json={"name": "prod", "endpoint": "https://api.example/v1",
                             "api_key": "sk-stored"},
                       headers=head).status_code == 200
