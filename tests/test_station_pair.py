# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Pairing — a key that narrows (spec J.2.6, criterion F.47).

The third door: unauthenticated like `login`, self-service by construction,
and what it mints is an ordinary J.2.2 key whose row carries a capability
mask. The load-bearing assertions here are about the mask being a filter
over LIVE authority at the moment of use — a pair key held by a writer
cannot plant, a pair key held by the owner opens no admin door, over REST
and MCP alike — and about the two password doors sharing one rate-limit
window whose refusal never says whether the user exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"

MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def pair_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("pair-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(pair_root, tmp_path, monkeypatch):
    """Fresh registry per test: pairing spends passwords and rate-limit
    windows, and neither may leak between tests."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    app = build_app(root=pair_root, registry_path=tmp_path / "station.db",
                    mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry


@pytest.fixture()
def mcp_station(pair_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    app = build_app(root=pair_root, registry_path=tmp_path / "station.db",
                    mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry


def _writer(registry, principal="alice", password="orange-tabby-9"):
    """A person with more authority than a pair key may carry: read, write
    and ingest on the forest, plus the password the pairing gesture spends."""
    registry.grant(principal, FOREST, {"read", "write", "ingest"})
    registry.set_password(principal, password)
    return principal, password


def _pair(client, username, password, **extra):
    return client.post("/v1/auth/pair",
                       json={"username": username, "password": password,
                             **extra})


def _bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


PLANT = {"node": {"id": "notes/paired-plant", "parent": "notes/_index",
                  "type": "note", "title": "Paired plant",
                  "summary": "A node a pair key must never create."}}


# -- the mint -----------------------------------------------------------------


def test_pair_returns_a_key_with_expiry_and_default_caps(station):
    client, registry = station
    user, pw = _writer(registry)

    r = _pair(client, user, pw, label="desk clipper")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_key"].startswith("mk_")
    assert body["principal"] == user
    assert body["caps"] == ["ingest", "read"]
    assert body["expires_at"]

    # The row itself carries the expiry: every pair key expires (J.2.6),
    # the default being 90 days, never "unlimited".
    token = [k for k in registry.keys_of([user])
             if k["label"] == "desk clipper"][0]
    assert token["expires_at"]


def test_me_reports_the_masked_caps(station):
    """What a console renders from /v1/me is what the key can actually do
    (J.2.6) — the unmasked grant says write, the pair key must not."""
    client, registry = station
    user, pw = _writer(registry)
    key = _pair(client, user, pw).json()["api_key"]

    me = client.get("/v1/me", headers=_bearer(key)).json()
    assert me["grants"][0]["caps"] == ["ingest", "read"]
    assert me["admin"] is False

    # /v1/forests reads from the same projection.
    listed = client.get("/v1/forests", headers=_bearer(key)).json()["forests"]
    assert listed[0]["caps"] == ["ingest", "read"]

    # And the same principal through an UNMASKED key still shows the full
    # grant: the mask narrows the credential, never the person.
    plain = registry.issue_key(user)
    unmasked = client.get("/v1/me", headers=_bearer(plain)).json()
    assert unmasked["grants"][0]["caps"] == ["ingest", "read", "write"]


# -- grants ∩ mask at the moment of use ---------------------------------------


def test_masked_key_is_refused_the_plant_its_principal_holds(station):
    client, registry = station
    user, pw = _writer(registry)
    key = _pair(client, user, pw).json()["api_key"]

    r = client.post(f"/v1/forests/{FOREST}/plant", json=PLANT,
                    headers=_bearer(key))
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "E_FORBIDDEN"

    # The refusal is the mask, not the grant: the same principal through an
    # unmasked key plants exactly that node.
    plain = registry.issue_key(user)
    assert client.post(f"/v1/forests/{FOREST}/plant", json=PLANT,
                       headers=_bearer(plain)).status_code == 200


def test_masked_key_still_reads_and_ingests(station):
    client, registry = station
    user, pw = _writer(registry)
    key = _pair(client, user, pw).json()["api_key"]

    hits = client.post(f"/v1/forests/{FOREST}/locate",
                       json={"query": "stigmergy", "k": 3},
                       headers=_bearer(key))
    assert hits.status_code == 200 and hits.json()["results"]

    # `compose` is the Clipper's own write path (J.15): one document through
    # the whole Gardener pipeline, under the `ingest` capability the mask
    # keeps.
    clipped = client.post(
        f"/v1/forests/{FOREST}/ingest",
        json={"mode": "compose", "title": "Clipped page",
              "text": "The retro moved to Thursdays; the form lives on the "
                      "intranet under Equipment."},
        headers=_bearer(key))
    assert clipped.status_code == 200, clipped.text
    assert "error" not in clipped.json()


def test_owner_pair_key_opens_no_admin_or_owner_door(station):
    """A masked key held by the owner is refused every /v1/admin route
    exactly as if the owner bit were absent (J.2.6)."""
    client, registry = station
    setup = client.post("/v1/auth/setup",
                        json={"username": "boss",
                              "password": "a-long-owner-password"})
    assert setup.status_code == 200, setup.text
    session = setup.json()["key"]
    # The unmasked session proves what the pair key is being denied.
    assert client.get("/v1/admin/keys",
                      headers=_bearer(session)).status_code == 200

    pair = _pair(client, "boss", "a-long-owner-password").json()["api_key"]
    assert client.get("/v1/admin/keys",
                      headers=_bearer(pair)).status_code == 403
    # An owner-gated route, not merely an admin-gated one: the snapshot
    # download collapses every branch scope, so it answers to the owner bit
    # — which the mask must also cover.
    owned = client.get(f"/v1/admin/snapshots/{FOREST}/x.bundle",
                       headers=_bearer(pair))
    assert owned.status_code == 403

    me = client.get("/v1/me", headers=_bearer(pair)).json()
    assert me["admin"] is False and me["owner"] is False


def test_masked_key_cannot_plant_over_mcp(mcp_station):
    """The mask crosses surfaces (J.2.6): resolved once per MCP request,
    published beside the principal, and intersected before the lane."""
    client, registry = mcp_station
    user, pw = _writer(registry)
    key = _pair(client, user, pw).json()["api_key"]

    def tool(name, args):
        r = client.post("/mcp/",
                        headers={**MCP_HEADERS, **_bearer(key)},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": name, "arguments": args}})
        assert r.status_code == 200, r.text
        return json.loads(r.json()["result"]["content"][0]["text"])

    refused = tool("plant", {"forest": FOREST, "node": PLANT["node"]})
    assert refused["error"]["code"] == "E_FORBIDDEN"

    found = tool("locate", {"forest": FOREST, "query": "stigmergy", "k": 3})
    assert found["results"]

    # And the forests() listing tells the agent the masked truth.
    listed = tool("forests", {})
    assert listed["forests"][0]["caps"] == ["ingest", "read"]


# -- the door's own hygiene ---------------------------------------------------


def test_pair_says_the_same_thing_about_every_failure(station):
    """Wrong password, unknown user, user with no password: one body, or the
    pairing form becomes a directory of who exists (J.2.6 / J.2.1)."""
    client, registry = station
    _writer(registry, principal="alice")
    registry.grant("nopass", FOREST, {"read"})  # exists, has no password

    said = {
        _pair(client, u, p).text
        for u, p in [("alice", "wrong"), ("ghost", "wrong"), ("nopass", "x")]
    }
    assert len(said) == 1, said
    assert _pair(client, "alice", "wrong").status_code == 401


def test_sixth_failure_in_the_window_is_429_for_known_and_unknown_alike(station):
    client, registry = station
    _writer(registry, principal="alice")

    for _ in range(5):
        assert _pair(client, "alice", "wrong").status_code == 401
    over_known = _pair(client, "alice", "wrong")
    assert over_known.status_code == 429

    # A user that does not exist walks the identical path — the limiter must
    # not become the directory the login refusal already refuses to be.
    for _ in range(5):
        assert _pair(client, "ghost", "wrong").status_code == 401
    over_unknown = _pair(client, "ghost", "wrong")
    assert over_unknown.status_code == 429
    assert over_known.text == over_unknown.text

    # Past the limit, even the RIGHT password is refused: the check runs
    # before verification, so the window cannot be probed with candidates.
    assert _pair(client, "alice", "orange-tabby-9").status_code == 429


def test_login_and_pair_share_one_window_and_success_clears_it(station):
    client, registry = station
    _writer(registry, principal="carol", password="lilac-morning-7")

    # Failures on `login` count against `pair`: same password, same window.
    for _ in range(5):
        assert client.post("/v1/auth/login",
                           json={"username": "carol", "password": "wrong"}
                           ).status_code == 401
    assert _pair(client, "carol", "lilac-morning-7").status_code == 429

    # A distinct user shows a success clearing the slate: three failures,
    # one success, and the next failures start counting from zero.
    _writer(registry, principal="dave", password="cedar-brook-3")
    for _ in range(3):
        client.post("/v1/auth/login", json={"username": "dave", "password": "no"})
    assert client.post("/v1/auth/login",
                       json={"username": "dave", "password": "cedar-brook-3"}
                       ).status_code == 200
    for _ in range(5):
        assert client.post("/v1/auth/login",
                           json={"username": "dave", "password": "no"}
                           ).status_code == 401
    assert client.post("/v1/auth/login",
                       json={"username": "dave", "password": "no"}
                       ).status_code == 429


def test_caps_outside_read_ingest_are_schema(station):
    client, registry = station
    user, pw = _writer(registry)
    for asked in (["write"], ["read", "admin"], ["tend"], ["query"]):
        r = _pair(client, user, pw, caps=asked)
        assert r.status_code == 400, r.text
        assert r.json()["error"]["code"] == "E_SCHEMA"


def test_expiry_ceiling_is_stated_not_clamped(station):
    client, registry = station
    user, pw = _writer(registry)

    over = _pair(client, user, pw, expires_in_days=999)
    assert over.status_code == 400
    assert over.json()["error"]["code"] == "E_SCHEMA"

    negative = _pair(client, user, pw, expires_in_days=-1)
    assert negative.status_code == 400
    assert negative.json()["error"]["code"] == "E_SCHEMA"

    # Zero and absent both mean the default — never "unlimited" (J.2.6).
    for extra in ({"expires_in_days": 0}, {}):
        minted = _pair(client, user, pw, **extra)
        assert minted.status_code == 200, minted.text
        assert minted.json()["expires_at"]


def test_expiry_nan_is_schema_not_a_500(station):
    """NaN compares False against both bounds, so without an isfinite guard
    it sailed through validation and blew up inside timedelta — a 500 where
    the caller earned a 400. Sent as raw JSON: Python's parser accepts the
    bare NaN token, so a browser never has to."""
    client, registry = station
    user, pw = _writer(registry)

    r = client.post(
        "/v1/auth/pair",
        content=json.dumps({"username": user, "password": pw,
                            "expires_in_days": float("nan")}),
        headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "E_SCHEMA"


def test_auth_window_is_bounded_against_distinct_usernames():
    """The username on an unauthenticated door is caller-controlled, so a
    stream of one-shot usernames must not grow the failure map forever —
    an unauthenticated memory-exhaustion vector otherwise. Forgetting a
    window early merely restarts its count; the limit itself still bites."""
    from monkeyllm_station.app import AuthWindow

    window = AuthWindow(max_tracked=64)
    for i in range(1000):
        window.failed(f"user-{i}", "10.0.0.1")
    assert len(window._failures) <= 64

    # The ceiling never disables the limiter: a live window still counts.
    for _ in range(window.limit):
        window.failed("mallory", "10.0.0.1")
    assert window.over_limit("mallory", "10.0.0.1")


def test_a_revoked_pair_key_stops_authenticating(station):
    """The lifecycle is J.2.2's: revoked from People, dead everywhere —
    `resolve_key` is the single gate every surface passes through."""
    client, registry = station
    user, pw = _writer(registry)
    key = _pair(client, user, pw, label="stolen laptop").json()["api_key"]
    assert client.get("/v1/me", headers=_bearer(key)).status_code == 200

    token = [k for k in registry.keys_of([user])
             if k["label"] == "stolen laptop"][0]
    registry.revoke_key(token["id"])
    assert client.get("/v1/me", headers=_bearer(key)).status_code == 401
