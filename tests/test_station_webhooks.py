# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Webhooks (spec J.16, criteria F.65/F.66/F.67).

The suite runs a real HTTP receiver on loopback rather than a stubbed
client, because three of the rules under test are only true on the wire:
the signature covers the exact bytes that were sent, the retry re-sends
those same bytes, and the destination check is about where a name
resolves rather than what it spells.

The rule the whole section hangs on is J.16.1 — **a delivery leaves the
Station's authority behind** — so the first tests here are about what is
*absent* from a body. A body that carries a summary nobody asked for is
not a cosmetic defect: it is curated material outside every scope that
governs it, at an address that cannot be revoked.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

MINE = "forest-mine"
THEIRS = "forest-theirs"


class Receiver:
    """A destination that records what it was sent and answers as told."""

    def __init__(self):
        self.received: list[dict] = []
        self.status = 200
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                with outer._lock:
                    outer.received.append({
                        "body": body,
                        "json": json.loads(body.decode("utf-8")),
                        "headers": {k.lower(): v for k, v in self.headers.items()},
                    })
                self.send_response(outer.status)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"thanks")

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/hook"

    def wait(self, count: int = 1, timeout: float = 5.0) -> list[dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if len(self.received) >= count:
                    return list(self.received)
            time.sleep(0.02)
        with self._lock:
            return list(self.received)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def receiver():
    r = Receiver()
    yield r
    r.close()


@pytest.fixture(scope="session")
def forest_template(tmp_path_factory) -> Path:
    """Built once, copied per test.

    Per test rather than per session because half of J.16.2 is about how
    many forests EXIST: `governs_deployment` is "administers every one of
    them", so a test that adds a second forest would otherwise decide what
    the deployment looks like for every test after it.
    """
    return build_forest(tmp_path_factory.mktemp("webhooks") / "template")


@pytest.fixture()
def two_forests(forest_template, tmp_path) -> Path:
    root = tmp_path / "forests"
    root.mkdir()
    shutil.copytree(forest_template, root / MINE)
    return root


def second_forest(app) -> None:
    """A forest appears. Nobody is granted it — which is the point: it
    narrows deployment authority by existing (v0.50, J.16.2)."""
    root = Path(app.state.pool.root)
    shutil.copytree(root / MINE, root / THEIRS)


@pytest.fixture()
def station(two_forests, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    # The receiver is on loopback, which J.16.4 refuses by default — the
    # same switch a local llama.cpp or a self-hosted n8n needs (J.10.2).
    monkeypatch.setenv("MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE", "1")
    app = build_app(root=two_forests, registry_path=tmp_path / "station.db",
                    mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, app


def admin_key(registry, principal="root", forest=MINE):
    key = registry.issue_key(principal)
    registry.grant(principal, forest, {"admin", "read", "write", "ingest"})
    return {"Authorization": f"Bearer {key}"}


def owner_key(registry, principal="owner"):
    """The J.2.4 owner bit: authority over every forest present and future,
    which is what J.16.2 requires of a deployment webhook."""
    registry.add_principal(principal, kind="user")
    registry.conn.execute("UPDATE principals SET owner = 1 WHERE id = ?",
                          (principal,))
    registry.conn.commit()
    return {"Authorization": f"Bearer {registry.issue_key(principal)}"}


def create(client, auth, forest=MINE, **body):
    """`auth` rather than `headers`: a webhook HAS a `headers` field, and a
    helper that shadowed it could not test the field at all."""
    body.setdefault("url", "https://example.invalid/hook")
    body.setdefault("events", ["node.planted"])
    return client.post(f"/v1/forests/{forest}/webhooks", json=body,
                       headers=auth)


def plant(client, headers, node_id, forest=MINE, **extra):
    node = {"id": node_id, "type": "note", "parent": "_index",
            "title": "A contract with Acme",
            "summary": "Renewal for 2026 with an inflation-linked adjustment.",
            "source": "manual", "body": "# A contract\n\nSecret terms here.\n",
            **extra}
    return client.post(f"/v1/forests/{forest}/plant", json={"node": node},
                       headers=headers)


# -- F.65: what travels, and what does not ---------------------------------


def test_a_plant_delivers_identity_and_no_content(station, receiver):
    """The rule the whole section hangs on (J.16.1).

    The body says a node was planted, where, by whom. It does not say what
    the node is *about* — because the receiver holds no grant, and title
    and summary are curated material that would be leaving every scope
    that governs them at an address nobody can revoke.
    """
    client, registry, _ = station
    headers = admin_key(registry)
    assert create(client, headers, url=receiver.url,
                  events=["node.planted"]).status_code == 201

    assert plant(client, headers, "note-one").status_code == 200
    got = receiver.wait(1)
    assert len(got) == 1, "the plant announced itself exactly once"

    body = got[0]["json"]
    assert body["event"] == "node.planted"
    assert body["forest"] == MINE
    assert body["principal"] == "root"
    assert body["data"]["node"] == "note-one"
    assert body["data"]["type"] == "note"
    assert body["data"]["parent"] == "_index"
    assert body["data"]["commit"]

    flat = json.dumps(body)
    for forbidden in ("Secret terms", "A contract with Acme", "Renewal for 2026"):
        assert forbidden not in flat, f"content escaped in the payload: {forbidden}"
    assert "title" not in body["data"] and "summary" not in body["data"]


def test_the_opt_in_adds_the_two_curated_fields_and_nothing_else(station, receiver):
    """`include_metadata` is bounded by construction: `title` and `summary`
    are what `locate` already returns, and the body still never travels."""
    client, registry, _ = station
    headers = admin_key(registry)
    create(client, headers, url=receiver.url, events=["node.planted"],
           include_metadata=True)

    plant(client, headers, "note-two")
    body = receiver.wait(1)[0]["json"]
    assert body["data"]["title"] == "A contract with Acme"
    assert body["data"]["summary"].startswith("Renewal for 2026")
    assert "Secret terms" not in json.dumps(body)


def test_a_graft_states_no_metadata_even_with_the_opt_in(station, receiver):
    """J.16.1 rule 3: the opt-in adds what the ACT already knew.

    `graft` was handed a patch, not a title. An event that went and read
    the node to describe itself would put an unbounded, unaudited
    retrieval on the path of every write.
    """
    client, registry, _ = station
    headers = admin_key(registry)
    plant(client, headers, "note-three")
    create(client, headers, url=receiver.url, events=["node.grafted"],
           include_metadata=True)

    reply = client.post(f"/v1/forests/{MINE}/graft", headers=headers, json={
        "id": "note-three",
        "patch": {"append_section": {"header": "Notes", "body": "more"}},
    })
    assert reply.status_code == 200, reply.text
    body = receiver.wait(1)[0]["json"]
    assert body["event"] == "node.grafted"
    assert body["data"]["node"] == "note-three"
    assert "title" not in body["data"] and "summary" not in body["data"]
    assert "more" not in json.dumps(body), "the grafted text is content"


def test_a_branch_plant_announces_both_names(station, receiver):
    client, registry, _ = station
    headers = admin_key(registry)
    create(client, headers, url=receiver.url,
           events=["node.planted", "branch.created"])
    reply = client.post(f"/v1/forests/{MINE}/plant", headers=headers, json={
        "node": {"id": "vendors/_index", "type": "branch", "parent": "_index",
                 "title": "Vendors", "summary": "Where vendor notes live.",
                 "source": "manual",
                 "body": "# Vendors\n\n> Where vendor notes live.\n\n"
                         "## Sub-branches\n\n## Direct bananas\n\n## Cross trails\n"}})
    assert reply.status_code == 200, reply.text
    events = {g["json"]["event"] for g in receiver.wait(2)}
    assert events == {"node.planted", "branch.created"}


def test_a_dead_destination_does_not_slow_the_write(station):
    """J.16.4's first rule. The socket is opened by a worker thread that the
    caller never waits on, so a black hole costs the primitive nothing."""
    client, registry, _ = station
    headers = admin_key(registry)
    # Reserved for documentation, never routable, and it will hang or fail
    # slowly — which is the point.
    create(client, headers, url="http://192.0.2.1:9/hook",
           events=["node.planted"])
    started = time.perf_counter()
    assert plant(client, headers, "note-fast").status_code == 200
    assert time.perf_counter() - started < 2.0


def test_the_branch_filter_narrows_only_events_that_name_a_node(station, receiver):
    client, registry, _ = station
    headers = admin_key(registry)
    create(client, headers, url=receiver.url, events=["node.planted"],
           branches=["projects/"])
    assert plant(client, headers, "elsewhere-note").status_code == 200
    assert plant(client, headers, "projects/kept-note",
                 parent="projects/_index").status_code == 200
    got = receiver.wait(1)
    assert [g["json"]["data"]["node"] for g in got] == ["projects/kept-note"]


# -- F.66: a scope is a ceiling --------------------------------------------


def test_a_forest_webhook_cannot_subscribe_to_a_deployment_event(station):
    client, registry, _ = station
    headers = admin_key(registry)
    reply = create(client, headers, events=["auth.login.failed"])
    assert reply.status_code == 400
    assert reply.json()["error"]["code"] == "E_SCHEMA"
    assert "auth.login.failed" in reply.json()["error"]["message"]


def test_a_forest_admin_cannot_open_the_deployment_scope(station):
    client, registry, app = station
    # A single-forest deployment IS governed by its admin (J.10.2), so the
    # refusal only exists once there is a second forest to cross into.
    second_forest(app)
    headers = admin_key(registry)
    reply = create(client, headers, scope="deployment",
                   events=["auth.login.failed"])
    assert reply.status_code == 403
    assert client.get(f"/v1/forests/{MINE}/webhooks",
                      headers=headers).json()["scopes"] == ["forest"]


def test_the_owner_hears_a_refused_sign_in(station, receiver):
    client, registry, _ = station
    headers = owner_key(registry)
    assert create(client, headers, url=receiver.url, scope="deployment",
                  events=["auth.login.failed"]).status_code == 201

    client.post("/v1/auth/login", json={"username": "ghost", "password": "no"})
    body = receiver.wait(1)[0]["json"]
    assert body["event"] == "auth.login.failed"
    assert body["forest"] == "-"
    assert body["data"]["username"] == "ghost"


def test_authority_is_re_read_at_delivery_and_suspends_the_webhook(station,
                                                                   receiver):
    """J.16.2. The webhook was made by somebody who governed the deployment;
    the authority lapsed afterwards. A standing instruction that outlived
    the grant behind it would make v0.50's rule stop at the door."""
    client, registry, app = station
    headers = admin_key(registry, "solo")  # sole forest → governs the deployment
    assert create(client, headers, url=receiver.url, scope="deployment",
                  events=["forest.created"]).status_code == 201

    # A second forest exists now, and `solo` administers only the first.
    build_forest(Path(app.state.pool.root) / THEIRS)
    reply = client.post("/v1/forests/-/webhooks", headers=headers, json={})
    assert reply.status_code in (400, 403)

    hooks = app.state.webhooks
    hook = registry.webhooks()[0]
    hooks.emit("-", "forest.created", "solo", {"forest": THEIRS})
    time.sleep(0.4)
    assert receiver.received == [], "a lapsed authority delivers nothing"
    assert registry.webhook(hook["id"])["suspended"] == "authority"


# -- F.67: signature, retries, custody -------------------------------------


def test_the_signature_covers_the_timestamp_and_the_exact_bytes(station,
                                                                receiver):
    client, registry, _ = station
    headers = admin_key(registry)
    reply = create(client, headers, url=receiver.url, events=["node.planted"])
    secret = reply.json()["secret"]
    assert secret.startswith("whsec_")

    plant(client, headers, "note-signed")
    got = receiver.wait(1)[0]
    sent = got["headers"]
    expected = hmac.new(secret.encode(),
                        sent["x-monkeyllm-timestamp"].encode() + b"." + got["body"],
                        hashlib.sha256).hexdigest()
    assert sent["x-monkeyllm-signature"] == f"sha256={expected}"
    assert sent["x-monkeyllm-event"] == "node.planted"
    assert sent["x-monkeyllm-attempt"] == "1"
    assert sent["x-monkeyllm-delivery"] == got["json"]["id"]


def test_the_secret_is_shown_once_and_never_read_back(station):
    client, registry, _ = station
    headers = admin_key(registry)
    made = create(client, headers).json()
    hook_id = made["webhook"]["id"]
    assert "secret" not in json.dumps(made["webhook"])

    listing = client.get(f"/v1/forests/{MINE}/webhooks", headers=headers).json()
    assert "whsec_" not in json.dumps(listing)
    detail = client.get(f"/v1/forests/{MINE}/webhooks/{hook_id}",
                        headers=headers).json()
    assert "whsec_" not in json.dumps(detail)

    rotated = client.post(f"/v1/forests/{MINE}/webhooks/{hook_id}",
                          json={"action": "rotate"}, headers=headers).json()
    assert rotated["secret"].startswith("whsec_")
    assert rotated["secret"] != made["secret"]


def test_a_retry_re_sends_the_same_body_under_one_delivery_id(station,
                                                              receiver,
                                                              monkeypatch):
    from monkeyllm_station import webhooks as wh

    monkeypatch.setattr(wh, "BACKOFF_SECONDS", (0.05, 0.05, 0.05, 0.05))
    client, registry, _ = station
    headers = admin_key(registry)
    create(client, headers, url=receiver.url, events=["node.planted"])
    receiver.status = 500

    plant(client, headers, "note-retried")
    got = receiver.wait(wh.MAX_ATTEMPTS, timeout=6.0)
    assert len(got) == wh.MAX_ATTEMPTS, "bounded, and it stops"
    assert len({g["body"] for g in got}) == 1, "byte-identical on every retry"
    assert len({g["json"]["id"] for g in got}) == 1, "one event, deduplicable"
    assert [g["headers"]["x-monkeyllm-attempt"] for g in got] == [
        str(i) for i in range(1, wh.MAX_ATTEMPTS + 1)]

    hook = registry.webhooks()[0]
    # The receiver sees the last attempt BEFORE the dispatcher records its
    # outcome — one wire, two writers — so on a slow runner the streak and
    # the delivery rows land moments after `wait` returns. Poll the
    # registry the way the suspension test below does, then assert.
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        if (registry.webhook(hook["id"])["fail_streak"] == 1
                and len(registry.deliveries(hook["id"])) == wh.MAX_ATTEMPTS):
            break
        time.sleep(0.05)
    assert registry.webhook(hook["id"])["fail_streak"] == 1
    rows = registry.deliveries(hook["id"])
    assert len(rows) == wh.MAX_ATTEMPTS
    assert {r["status"] for r in rows} == {500}


def test_repeated_failure_suspends_the_webhook(station, receiver, monkeypatch):
    from monkeyllm_station import webhooks as wh

    monkeypatch.setattr(wh, "BACKOFF_SECONDS", (0.01,))
    monkeypatch.setattr(wh, "MAX_ATTEMPTS", 2)
    monkeypatch.setattr(wh, "SUSPEND_AFTER", 2)
    client, registry, app = station
    headers = admin_key(registry)
    create(client, headers, url=receiver.url, events=["node.planted"])
    receiver.status = 500

    plant(client, headers, "note-a")
    plant(client, headers, "note-b")
    hook_id = registry.webhooks()[0]["id"]
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        if registry.webhook(hook_id)["suspended"]:
            break
        time.sleep(0.05)
    assert registry.webhook(hook_id)["suspended"] == "failing"

    # Suspended, never deleted, and it says so where it is listed.
    listed = client.get(f"/v1/forests/{MINE}/webhooks",
                        headers=headers).json()["webhooks"]
    assert listed[0]["suspended"] == "failing"


def test_a_non_public_destination_is_refused_without_the_switch(station,
                                                               monkeypatch):
    monkeypatch.delenv("MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE", raising=False)
    client, registry, _ = station
    headers = admin_key(registry)
    reply = create(client, headers, url="http://127.0.0.1:9/hook")
    assert reply.status_code == 400
    assert "non-public" in reply.json()["error"]["message"]
    assert create(client, headers, url="ftp://example.com/x").status_code == 400


def test_a_header_value_is_never_returned_by_any_endpoint(station, receiver):
    client, registry, _ = station
    headers = admin_key(registry)
    made = create(client, headers, url=receiver.url, events=["node.planted"],
                  headers={"Authorization": "Bearer downstream-secret"})
    hook_id = made.json()["webhook"]["id"]
    assert made.json()["webhook"]["headers"] == ["Authorization"]

    for reply in (client.get(f"/v1/forests/{MINE}/webhooks", headers=headers),
                  client.get(f"/v1/forests/{MINE}/webhooks/{hook_id}",
                             headers=headers)):
        assert "downstream-secret" not in reply.text

    # It still reaches the destination — write-only is not "discarded".
    plant(client, headers, "note-headers")
    got = receiver.wait(1)[0]
    assert got["headers"]["authorization"] == "Bearer downstream-secret"


def test_an_edit_keeps_a_header_it_was_not_given(station, receiver):
    """The custody rule the console depends on: a value that can never be
    READ back has to be leavable alone, so `null` means keep."""
    client, registry, _ = station
    headers = admin_key(registry)
    hook_id = create(client, headers, url=receiver.url, events=["node.planted"],
                     headers={"X-Token": "kept"}).json()["webhook"]["id"]
    client.post(f"/v1/forests/{MINE}/webhooks", headers=headers,
                json={"id": hook_id, "url": receiver.url,
                      "events": ["node.planted"],
                      "headers": {"X-Token": None}})
    plant(client, headers, "note-kept")
    assert receiver.wait(1)[0]["headers"]["x-token"] == "kept"


def test_the_station_owns_its_own_header_names(station):
    client, registry, _ = station
    headers = admin_key(registry)
    for name in ("X-MonkeyLLM-Signature", "Host", "Content-Length"):
        reply = create(client, headers, headers={name: "x"})
        assert reply.status_code == 400, name


# -- the console's surface --------------------------------------------------


def test_the_catalogue_is_served_and_scoped(station):
    from monkeyllm_station import webhooks as wh

    client, registry, app = station
    # Two forests, so the forest admin is only that (J.10.2's reach rule).
    second_forest(app)
    forest_view = client.get(f"/v1/forests/{MINE}/webhooks",
                             headers=admin_key(registry)).json()
    assert {e["event"] for e in forest_view["events"]} == set(wh.FOREST_EVENTS)
    assert wh.TEST_EVENT not in {e["event"] for e in forest_view["events"]}

    owner_view = client.get(f"/v1/forests/{MINE}/webhooks",
                            headers=owner_key(registry)).json()
    assert {e["event"] for e in owner_view["events"]} == (
        set(wh.FOREST_EVENTS) | set(wh.DEPLOYMENT_EVENTS))
    assert owner_view["scopes"] == ["forest", "deployment"]


def test_every_catalogue_event_is_grouped_and_scoped(station):
    """A catalogue entry the console cannot place is an entry nobody
    subscribes to."""
    from monkeyllm_station import webhooks as wh

    for entry in wh.CATALOGUE:
        assert entry["group"] in wh.GROUPS, entry
        assert entry["scope"] in ("forest", "deployment"), entry
    assert len(wh.EVENTS) == len(wh.CATALOGUE), "duplicate event name"


def test_a_test_delivery_reports_the_whole_answer(station, receiver):
    client, registry, _ = station
    headers = admin_key(registry)
    hook_id = create(client, headers, url=receiver.url).json()["webhook"]["id"]
    reply = client.post(f"/v1/forests/{MINE}/webhooks/{hook_id}",
                        json={"action": "test"}, headers=headers)
    record = reply.json()["delivery"]
    assert record["ok"] and record["status"] == 200
    assert record["response"] == "thanks"
    assert record["ms"] >= 0
    assert receiver.received[0]["json"]["event"] == "webhook.test"


def test_a_delivery_can_be_re_sent_unchanged(station, receiver):
    client, registry, _ = station
    headers = admin_key(registry)
    hook_id = create(client, headers, url=receiver.url,
                     events=["node.planted"]).json()["webhook"]["id"]
    plant(client, headers, "note-redeliver")
    first = receiver.wait(1)[0]

    delivery = first["json"]["id"]
    # One wire, two writers (the retry test above says it too): the receiver
    # has the request before the dispatcher has written the row it re-sends,
    # so a redelivery asked at `wait`'s speed asks for a delivery that is not
    # recorded yet — and reads back E_NOT_FOUND, on a slow runner only.
    deadline = time.monotonic() + 6.0
    while (registry.delivery(hook_id, delivery) is None
           and time.monotonic() < deadline):
        time.sleep(0.05)
    reply = client.post(f"/v1/forests/{MINE}/webhooks/{hook_id}",
                        json={"action": "redeliver", "delivery": delivery},
                        headers=headers)
    assert reply.json()["delivery"]["ok"]
    again = receiver.wait(2)[1]
    assert again["body"] == first["body"]
    assert again["headers"]["x-monkeyllm-attempt"] == "2"


def test_a_webhook_of_another_scope_is_absent_rather_than_forbidden(station):
    client, registry, app = station
    second_forest(app)
    theirs = owner_key(registry)
    hook_id = create(client, theirs, scope="deployment",
                     events=["key.issued"]).json()["webhook"]["id"]
    mine = admin_key(registry)
    reply = client.get(f"/v1/forests/{MINE}/webhooks/{hook_id}", headers=mine)
    assert reply.status_code == 404
    assert reply.json()["error"]["code"] == "E_NOT_FOUND"


def test_a_non_admin_is_refused_the_console(station):
    client, registry, _ = station
    key = registry.issue_key("reader")
    registry.grant("reader", MINE, {"read"})
    headers = {"Authorization": f"Bearer {key}"}
    assert client.get(f"/v1/forests/{MINE}/webhooks",
                      headers=headers).status_code == 403
    assert create(client, headers).status_code == 403


def test_the_lifecycle_is_audited_by_host_and_never_by_url(station, receiver):
    client, registry, _ = station
    headers = admin_key(registry)
    secret_url = f"{receiver.url}/T00000/B00000/xoxb-a-token-in-the-path"
    hook_id = create(client, headers, url=secret_url).json()["webhook"]["id"]
    client.post(f"/v1/forests/{MINE}/webhooks/{hook_id}",
                json={"action": "test"}, headers=headers)
    client.delete(f"/v1/forests/{MINE}/webhooks/{hook_id}", headers=headers)

    rows = [r for r in registry.audit(limit=200)
            if r["primitive"].startswith("admin.webhook")]
    assert {r["primitive"] for r in rows} == {
        "admin.webhook.create", "admin.webhook.test", "admin.webhook.delete"}
    assert "xoxb-a-token-in-the-path" not in json.dumps(rows)


def test_a_refusal_is_announced_as_access_denied(station, receiver):
    client, registry, _ = station
    headers = admin_key(registry)
    create(client, headers, url=receiver.url, events=["access.denied"])

    # Deliberately a CAPABILITY refusal. A branch out of scope answers
    # `E_NOT_FOUND` by design (J.3) — announcing that as a denial would
    # tell a webhook which ids exist outside somebody's scope.
    key = registry.issue_key("narrow")
    registry.grant("narrow", MINE, {"read"})
    reply = client.post(f"/v1/forests/{MINE}/plant",
                        json={"node": {"id": "x", "type": "note",
                                       "parent": "_index", "title": "x",
                                       "summary": "x", "source": "manual",
                                       "body": "x"}},
                        headers={"Authorization": f"Bearer {key}"})
    assert reply.status_code == 403
    body = receiver.wait(1)[0]["json"]
    assert body["event"] == "access.denied"
    assert body["data"]["primitive"] == "plant"
    assert body["data"]["code"] == "E_FORBIDDEN"
    assert body["principal"] == "narrow"
