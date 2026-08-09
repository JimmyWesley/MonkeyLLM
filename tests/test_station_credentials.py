"""Credentials: the two doors and the token lifecycle (J.2.1/J.2.2, F.21).

The object that grants access was, until v0.17, the one object the
governance console could not govern: a key was minted by a CLI, never
listed, never expiring, never revocable. These tests hold the lifecycle to
the only standard that matters — that `authenticate()` itself refuses a
credential that should no longer work, since it is the single gate every
surface passes through.

The load-bearing test is `test_admin_of_one_forest_cannot_mint_a_key_that
_opens_another`: without that rule, delegated administration is a way to
reach across the registry.
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
OTHER = "other-forest"


@pytest.fixture(scope="session")
def two_forests(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("cred-root")
    build_forest(root / FOREST)
    build_forest(root / OTHER)
    return root


@pytest.fixture()
def station(two_forests, tmp_path, monkeypatch):
    """No environment super-admin unless a test asks for one: a Station that
    invents a password door on its own would be the bug."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    app = build_app(root=two_forests, registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry


def _admin(registry, forests=(FOREST,), principal="root"):
    key = registry.issue_key(principal)
    for f in forests:
        registry.grant(principal, f, {"read", "admin"})
    return {"Authorization": f"Bearer {key}"}


# -- J.2.1 the password door ------------------------------------------------


def test_no_environment_account_means_no_password_door(station):
    client, _ = station
    assert client.get("/v1/health").json()["password_login"] is False
    r = client.post("/v1/auth/login", json={"username": "admin", "password": ""})
    assert r.status_code == 401


def test_environment_account_logs_in_and_is_admin_everywhere(
        two_forests, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.setenv("MONKEYLLM_STATION_ADMIN", "owner")
    monkeypatch.setenv("MONKEYLLM_STATION_PASSWORD", "correct horse battery")
    app = build_app(root=two_forests, registry_path=tmp_path / "s.db", mcp=False)
    with TestClient(app) as client:
        assert client.get("/v1/health").json()["password_login"] is True

        bad = client.post("/v1/auth/login",
                          json={"username": "owner", "password": "wrong"})
        assert bad.status_code == 401

        r = client.post("/v1/auth/login",
                        json={"username": "owner", "password": "correct horse battery"})
        assert r.status_code == 200
        body = r.json()
        assert body["principal"] == "owner" and body["admin"] is True
        assert body["expires_at"]

        # The session is an ordinary key on the ordinary path (J.2.1).
        head = {"Authorization": f"Bearer {body['key']}"}
        me = client.get("/v1/me", headers=head).json()
        assert me["principal"] == "owner"
        assert {g["forest"] for g in me["grants"]} == {FOREST, OTHER}
        assert client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                           headers=head).status_code == 200

        # And it is never stored: the registry holds no hash for it.
        assert app.state.registry.has_password("owner") is False


def test_environment_password_is_not_stored_and_cannot_be_set(
        two_forests, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.setenv("MONKEYLLM_STATION_ADMIN", "owner")
    monkeypatch.setenv("MONKEYLLM_STATION_PASSWORD", "s3cret")
    app = build_app(root=two_forests, registry_path=tmp_path / "s.db", mcp=False)
    with TestClient(app) as client:
        key = client.post("/v1/auth/login",
                          json={"username": "owner", "password": "s3cret"}).json()["key"]
        r = client.post("/v1/admin/password",
                        json={"principal": "owner", "password": "shadow"},
                        headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 403
        assert "environment account" in r.json()["error"]["message"]


def test_a_principal_password_is_set_by_an_admin_and_hashed(station):
    client, registry = station
    head = _admin(registry)
    registry.grant("alice", FOREST, {"read"})

    assert client.post("/v1/auth/login",
                       json={"username": "alice", "password": "hunter2"}).status_code == 401

    assert client.post("/v1/admin/password",
                       json={"principal": "alice", "password": "hunter2"},
                       headers=head).status_code == 200

    r = client.post("/v1/auth/login", json={"username": "alice", "password": "hunter2"})
    assert r.status_code == 200 and r.json()["admin"] is False

    # Stored as a salted hash, never as the password.
    row = registry.conn.execute(
        "SELECT pw_salt, pw_hash FROM principals WHERE id = 'alice'").fetchone()
    assert row["pw_hash"] and "hunter2" not in row["pw_hash"]
    assert len(row["pw_salt"]) == 32

    # Clearing removes the door rather than leaving a blank one.
    client.post("/v1/admin/password", json={"principal": "alice", "password": ""},
                headers=head)
    assert client.post("/v1/auth/login",
                       json={"username": "alice", "password": ""}).status_code == 401
    assert client.post("/v1/auth/login",
                       json={"username": "alice", "password": "hunter2"}).status_code == 401


def test_login_says_the_same_thing_about_every_failure(station):
    """A distinguishable 'no such user' turns the form into a directory."""
    client, registry = station
    _admin(registry)
    registry.grant("alice", FOREST, {"read"})
    client.post("/v1/admin/password", json={"principal": "alice", "password": "pw"},
                headers=_admin(registry, principal="root2"))

    said = {
        client.post("/v1/auth/login", json={"username": u, "password": p}).text
        for u, p in [("ghost", "pw"), ("alice", "wrong"), ("root", "pw")]
    }
    assert len(said) == 1, said


# -- J.2.2 the token lifecycle ----------------------------------------------


def test_issue_list_and_revoke(station):
    client, registry = station
    head = _admin(registry)
    registry.grant("svc", FOREST, {"read"})

    made = client.post("/v1/admin/keys",
                       json={"principal": "svc", "label": "ci pipeline",
                             "expires_in_days": 30}, headers=head)
    assert made.status_code == 200, made.text
    key = made.json()["api_key"]

    listed = client.get("/v1/admin/keys", headers=head).json()["keys"]
    mine = [k for k in listed if k["principal"] == "svc"]
    assert len(mine) == 1
    token = mine[0]
    assert token["label"] == "ci pipeline"
    assert token["status"] == "active" and token["expires_at"]
    # The prefix identifies without disclosing.
    assert key.startswith(token["prefix"]) and len(token["prefix"]) < 12
    assert key not in client.get("/v1/admin/keys", headers=head).text

    work = {"Authorization": f"Bearer {key}"}
    assert client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                       headers=work).status_code == 200
    after = [k for k in client.get("/v1/admin/keys", headers=head).json()["keys"]
             if k["id"] == token["id"]][0]
    assert after["last_used_at"], "last use is what makes a token safe to remove"

    assert client.post("/v1/admin/keys", json={"revoke": token["id"]},
                       headers=head).status_code == 200
    assert client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                       headers=work).status_code == 401
    revoked = [k for k in client.get("/v1/admin/keys", headers=head).json()["keys"]
               if k["id"] == token["id"]][0]
    assert revoked["status"] == "revoked"


def test_an_expired_key_is_refused_like_an_unknown_one(station):
    client, registry = station
    _admin(registry)
    registry.grant("svc", FOREST, {"read"})
    key = registry.issue_key("svc", label="stale")
    # Backdate expiry directly: the clock is the one thing a test may not wait for.
    registry.conn.execute(
        "UPDATE api_keys SET expires_at = '2020-01-01T00:00:00+00:00' "
        "WHERE key_hash = ?", (__import__("monkeyllm_station.registry",
                                          fromlist=["hash_key"]).hash_key(key),))
    registry.conn.commit()

    expired = client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                          headers={"Authorization": f"Bearer {key}"})
    unknown = client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                          headers={"Authorization": "Bearer mk_nonexistent"})
    assert expired.status_code == unknown.status_code == 401
    assert expired.text == unknown.text


def test_sessions_never_appear_in_the_token_console(station):
    client, registry = station
    head = _admin(registry)
    registry.set_password("root", "pw")
    client.post("/v1/auth/login", json={"username": "root", "password": "pw"})

    listed = client.get("/v1/admin/keys", headers=head).json()["keys"]
    assert all(k["label"] != "session" for k in listed)


def test_a_key_is_returned_once_and_never_again(station):
    client, registry = station
    head = _admin(registry)
    registry.grant("svc", FOREST, {"read"})
    key = client.post("/v1/admin/keys", json={"principal": "svc"},
                      headers=head).json()["api_key"]
    body = client.get("/v1/admin/keys", headers=head).text
    assert key not in body
    assert key[9:] not in body


def test_issuing_needs_admin(station):
    client, registry = station
    reader = registry.issue_key("bob")
    registry.grant("bob", FOREST, {"read"})
    r = client.post("/v1/admin/keys", json={"principal": "bob"},
                    headers={"Authorization": f"Bearer {reader}"})
    assert r.status_code == 403


# -- the escalation rule ----------------------------------------------------


def test_admin_of_one_forest_cannot_mint_a_key_that_opens_another(station):
    """The rule that makes delegated token issuance safe (J.2.2).

    `partial` administers only forest-fixture. `wide` is granted both
    forests. If partial could mint a key for wide, that key would open
    other-forest — a forest partial cannot read, let alone administer.
    """
    client, registry = station
    partial = _admin(registry, forests=(FOREST,), principal="partial")
    registry.grant("wide", FOREST, {"read"})
    registry.grant("wide", OTHER, {"read"})

    r = client.post("/v1/admin/keys", json={"principal": "wide"}, headers=partial)
    assert r.status_code == 403
    assert "do not administer" in r.json()["error"]["message"]

    # And `wide` is invisible in the console for the same reason.
    listing = client.get("/v1/admin/keys", headers=partial).json()
    assert "wide" not in listing["principals"]
    assert all(k["principal"] != "wide" for k in listing["keys"])

    # An admin of both may do it.
    both = _admin(registry, forests=(FOREST, OTHER), principal="full")
    assert client.post("/v1/admin/keys", json={"principal": "wide"},
                       headers=both).status_code == 200


def test_revoking_across_forests_is_refused_too(station):
    client, registry = station
    partial = _admin(registry, forests=(FOREST,), principal="partial")
    registry.grant("wide", FOREST, {"read"})
    registry.grant("wide", OTHER, {"read"})
    victim = registry.issue_key("wide", label="theirs")
    token = [k for k in registry.keys_of(["wide"]) if k["label"] == "theirs"][0]

    r = client.post("/v1/admin/keys", json={"revoke": token["id"]}, headers=partial)
    assert r.status_code == 403
    # And the key still works, i.e. the refusal happened before the effect.
    assert client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                       headers={"Authorization": f"Bearer {victim}"}).status_code == 200


def test_password_setting_obeys_the_same_rule(station):
    client, registry = station
    partial = _admin(registry, forests=(FOREST,), principal="partial")
    registry.grant("wide", FOREST, {"read"})
    registry.grant("wide", OTHER, {"read"})
    r = client.post("/v1/admin/password",
                    json={"principal": "wide", "password": "x"}, headers=partial)
    assert r.status_code == 403
    assert registry.has_password("wide") is False


def test_registry_survives_two_threads(tmp_path):
    """The Station touches the registry from two threads by design (J.1).

    The event loop authenticates every request; the forest worker writes the
    audit record after the call has run. Sharing one `sqlite3.Connection`
    between them shares its transaction state, so one thread's `commit()`
    lands inside the other's open transaction and the loser raises "cannot
    commit - no transaction is active" — a 500 for the caller and a silently
    dropped audit row.

    This test hammers both paths at once because the defect is intermittent:
    a sequential suite never reproduces it, and the console does, under an
    operator simply clicking through consoles.
    """
    import threading

    from monkeyllm_station.registry import Registry

    registry = Registry(tmp_path / "race.db")
    key = registry.issue_key("alice")
    registry.grant("alice", "forest", {"read"})

    failures: list[str] = []
    ROUNDS = 200

    def authenticating() -> None:
        for _ in range(ROUNDS):
            try:
                assert registry.authenticate(key) == "alice"
            except Exception as e:      # noqa: BLE001 - the point is to catch any
                failures.append(f"authenticate: {e}")

    def auditing() -> None:
        for _ in range(ROUNDS):
            try:
                registry.record(principal="alice", forest="forest",
                                primitive="look", args={}, result="ok", size=1)
            except Exception as e:      # noqa: BLE001
                failures.append(f"record: {e}")

    threads = [threading.Thread(target=authenticating),
               threading.Thread(target=auditing),
               threading.Thread(target=authenticating),
               threading.Thread(target=auditing)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not failures, f"{len(failures)} concurrent failure(s): {failures[:3]}"
    # Every audit row was written, not merely attempted: a dropped commit
    # loses the record without raising anywhere the caller can see.
    assert len(registry.audit(limit=10_000)) == ROUNDS * 2
    registry.close()
