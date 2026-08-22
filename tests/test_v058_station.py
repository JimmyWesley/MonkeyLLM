# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.58 — the document has a past (host half).

F.96: a scoped move refuses what it cannot see, and a waymark is never a
periscope.
F.97/F.98 over the wire: history and the batch plant, under a policy.
F.101: identical questions in flight share one generation.
F.102: both new tools are served, capability-gated, and named in the
instructions.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-past"
QUESTION = "architecture notes"

MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}


@pytest.fixture()
def root(tmp_path):
    root = tmp_path / "forests"
    root.mkdir()
    build_forest(root / FOREST)
    return root


def _build(tmp_path, monkeypatch, root, *, chat=None):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    if chat is not None:
        monkeypatch.setattr(
            inference, "chat_from_binding",
            lambda binding, **_kw: (chat, binding.get("model", "stub")))
    app = build_app(root=root, registry_path=tmp_path / "station.db",
                    mcp=chat is None)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"admin", "read", "write", "query"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    client = TestClient(app)
    client.__enter__()
    return app, client, registry, {"Authorization": f"Bearer {key}"}


def _plant(client, head, node_id, title, *, parent=None, links=None):
    node = {"id": node_id, "type": "note",
            "parent": parent or f"{node_id.rsplit('/', 1)[0]}/_index",
            "title": title, "summary": f"{title}, for the v0.58 host suite.",
            "body": f"# {title}\n\nBody of {title}."}
    if links:
        node["links"] = links
    r = client.post(f"/v1/forests/{FOREST}/plant", headers=head,
                    json={"node": node})
    assert r.status_code == 200, r.text
    return r.json()


# -- F.96: the scoped move, and the waymark that is not a periscope ----------


class TestScopedTransplant:
    def test_a_hidden_backlink_refuses_the_whole_move(
            self, root, tmp_path, monkeypatch):
        app, client, registry, head = _build(tmp_path, monkeypatch, root)
        try:
            _plant(client, head, "notes/target", "Target")
            _plant(client, head, "sales/pointer", "Pointer",
                   links=[{"rel": "related-to", "target": "notes/target"}])
            key = registry.issue_key("narrow")
            registry.grant("narrow", FOREST, {"read", "write"},
                           allow=["notes/", "concepts/"])
            narrow = {"Authorization": f"Bearer {key}"}

            r = client.post(f"/v1/forests/{FOREST}/transplant", headers=narrow,
                            json={"id": "notes/target",
                                  "new_id": "concepts/target"})
            assert r.status_code == 409, r.text
            err = r.json()["error"]
            assert err["code"] == "E_ANCHORED"
            assert "sales/pointer" not in str(err), \
                "an out-of-scope anchor is a count, never a name"
            # Nothing moved.
            assert client.post(f"/v1/forests/{FOREST}/look", headers=head,
                               json={"id": "notes/target"}).status_code == 200
        finally:
            client.__exit__(None, None, None)

    def test_a_destination_outside_the_grant_is_forbidden(
            self, root, tmp_path, monkeypatch):
        app, client, registry, head = _build(tmp_path, monkeypatch, root)
        try:
            _plant(client, head, "notes/target", "Target")
            key = registry.issue_key("narrow")
            registry.grant("narrow", FOREST, {"read", "write"},
                           allow=["notes/"])
            narrow = {"Authorization": f"Bearer {key}"}
            r = client.post(f"/v1/forests/{FOREST}/transplant", headers=narrow,
                            json={"id": "notes/target",
                                  "new_id": "concepts/target"})
            assert r.status_code == 403
            assert r.json()["error"]["code"] == "E_FORBIDDEN"
        finally:
            client.__exit__(None, None, None)

    def test_a_waymark_out_of_scope_is_a_plain_not_found(
            self, root, tmp_path, monkeypatch):
        app, client, registry, head = _build(tmp_path, monkeypatch, root)
        try:
            _plant(client, head, "notes/secret-move", "Secret move")
            moved = client.post(f"/v1/forests/{FOREST}/transplant",
                                headers=head,
                                json={"id": "notes/secret-move",
                                      "new_id": "sales/secret-move"})
            assert moved.status_code == 200, moved.text

            key = registry.issue_key("narrow")
            registry.grant("narrow", FOREST, {"read"}, allow=["notes/"])
            narrow = {"Authorization": f"Bearer {key}"}
            waymark = client.post(f"/v1/forests/{FOREST}/look", headers=narrow,
                                  json={"id": "notes/secret-move"})
            absent = client.post(f"/v1/forests/{FOREST}/look", headers=narrow,
                                 json={"id": "notes/never-existed"})
            assert waymark.status_code == absent.status_code == 404
            # Byte-identical once each envelope's own id is masked: the
            # waymark discloses nothing about where the node went.
            norm = lambda r, nid: r.text.replace(nid, "<id>")  # noqa: E731
            assert norm(waymark, "notes/secret-move") == norm(
                absent, "notes/never-existed")

            # In scope, the same read names the new address.
            told = client.post(f"/v1/forests/{FOREST}/look", headers=head,
                               json={"id": "notes/secret-move"})
            assert told.status_code == 404
            assert told.json()["error"]["code"] == "E_MOVED"
            assert told.json()["error"]["moved_to"] == "sales/secret-move"
        finally:
            client.__exit__(None, None, None)

    def test_the_move_is_stamped_audited_and_announced(
            self, root, tmp_path, monkeypatch):
        app, client, registry, head = _build(tmp_path, monkeypatch, root)
        try:
            _plant(client, head, "notes/stamped-move", "Stamped move")
            r = client.post(f"/v1/forests/{FOREST}/transplant", headers=head,
                            json={"id": "notes/stamped-move",
                                  "new_id": "concepts/stamped-move"})
            assert r.status_code == 200, r.text
            message = subprocess.run(
                ["git", "-C", str(root / FOREST), "log", "-1", "--format=%B"],
                capture_output=True, text=True, check=True).stdout
            assert "transplant(notes/stamped-move -> " in message
            assert "station-principal: root" in message
            audit = client.get(f"/v1/admin/audit?forest={FOREST}&limit=20",
                               headers=head).json()
            assert any(row["primitive"] == "transplant"
                       for row in audit["entries"])
        finally:
            client.__exit__(None, None, None)


# -- F.97/F.98 over the wire --------------------------------------------------


def test_history_is_read_gated_and_scoped(root, tmp_path, monkeypatch):
    app, client, registry, head = _build(tmp_path, monkeypatch, root)
    try:
        _plant(client, head, "notes/past", "Past")
        r = client.post(f"/v1/forests/{FOREST}/history", headers=head,
                        json={"id": "notes/past"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["entries"][0]["action"] == "plant"
        assert body["entries"][0]["by"] == "root", \
            "the host's own stamp, read back"

        key = registry.issue_key("narrow")
        registry.grant("narrow", FOREST, {"read"}, allow=["sales/"])
        narrow = {"Authorization": f"Bearer {key}"}
        hidden = client.post(f"/v1/forests/{FOREST}/history", headers=narrow,
                             json={"id": "notes/past"})
        assert hidden.status_code == 404
        assert hidden.json()["error"]["code"] == "E_NOT_FOUND"
    finally:
        client.__exit__(None, None, None)


def test_a_batch_plant_is_one_commit_over_the_wire(root, tmp_path,
                                                   monkeypatch):
    app, client, registry, head = _build(tmp_path, monkeypatch, root)
    try:
        before = subprocess.run(
            ["git", "-C", str(root / FOREST), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        nodes = [{"id": f"notes/wire-{i}", "type": "note",
                  "parent": "notes/_index", "title": f"Wire {i}",
                  "summary": f"Node {i} of a batch sent over REST.",
                  "body": f"# Wire {i}\n\nBody."} for i in range(3)]
        r = client.post(f"/v1/forests/{FOREST}/plant", headers=head,
                        json={"node": nodes})
        assert r.status_code == 200, r.text
        assert r.json()["count"] == 3
        after = subprocess.run(
            ["git", "-C", str(root / FOREST), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        assert int(after) == int(before) + 1

        # C.7.4 under a policy: EVERY node is gated before anything lands.
        key = registry.issue_key("narrow")
        registry.grant("narrow", FOREST, {"read", "write"}, allow=["notes/"])
        narrow = {"Authorization": f"Bearer {key}"}
        mixed = client.post(
            f"/v1/forests/{FOREST}/plant", headers=narrow,
            json={"node": [
                {"id": "notes/allowed", "type": "note",
                 "parent": "notes/_index", "title": "Allowed",
                 "summary": "Inside the grant, and refused with its batch."},
                {"id": "sales/forbidden", "type": "note",
                 "parent": "sales/_index", "title": "Forbidden",
                 "summary": "Outside the grant: the whole batch refuses."}]})
        assert mixed.status_code == 403
        assert client.post(f"/v1/forests/{FOREST}/look", headers=head,
                           json={"id": "notes/allowed"}).status_code == 404
    finally:
        client.__exit__(None, None, None)


# -- F.101: identical questions in flight share one generation ---------------


def test_two_identical_cold_asks_buy_one_generation(root, tmp_path,
                                                    monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls: list = []

    def chat(messages):
        calls.append(messages)
        entered.set()
        assert release.wait(10), "the test forgot to release the model"
        return f"stub answer #{len(calls)}"

    app, client, _registry, head = _build(tmp_path, monkeypatch, root,
                                          chat=chat)
    try:
        results: dict = {}

        def ask(tag):
            results[tag] = client.post(
                f"/v1/forests/{FOREST}/answer",
                json={"question": QUESTION}, headers=head)

        leader = threading.Thread(target=ask, args=("leader",))
        leader.start()
        assert entered.wait(10), "the leader never reached the provider"
        follower = threading.Thread(target=ask, args=("follower",))
        follower.start()
        # The follower is now waiting on the leader, not on a provider.
        time.sleep(0.3)
        assert len(calls) == 1
        release.set()
        leader.join(timeout=15)
        follower.join(timeout=15)
        assert not leader.is_alive() and not follower.is_alive()

        assert len(calls) == 1, "one generation for two identical questions"
        assert results["leader"].status_code == 200
        assert results["follower"].status_code == 200, \
            results["follower"].text
        served = results["follower"].json()
        assert served["cached"] is True
        assert served["answer"] == results["leader"].json()["answer"]
        assert served["harvest"]["results"], "its own retrieval, fresh"
    finally:
        release.set()
        client.__exit__(None, None, None)


def test_cache_false_never_coalesces(root, tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls: list = []

    def chat(messages):
        calls.append(messages)
        entered.set()
        release.wait(10)
        return f"stub answer #{len(calls)}"

    app, client, _registry, head = _build(tmp_path, monkeypatch, root,
                                          chat=chat)
    try:
        def ask():
            client.post(f"/v1/forests/{FOREST}/answer",
                        json={"question": QUESTION, "cache": False},
                        headers=head)

        first = threading.Thread(target=ask)
        first.start()
        assert entered.wait(10)
        second = threading.Thread(target=ask)
        second.start()
        time.sleep(0.3)
        release.set()
        first.join(timeout=15)
        second.join(timeout=15)
        assert len(calls) == 2, "opting out of the store opts out of sharing"
    finally:
        release.set()
        client.__exit__(None, None, None)


def test_a_failing_leader_releases_its_followers(root, tmp_path, monkeypatch):
    calls: list = []

    def chat(messages):
        calls.append(messages)
        if len(calls) == 1:
            raise RuntimeError("provider outage")
        return "stub answer after the outage"

    app, client, _registry, head = _build(tmp_path, monkeypatch, root,
                                          chat=chat)
    try:
        first = client.post(f"/v1/forests/{FOREST}/answer",
                            json={"question": QUESTION}, headers=head)
        assert first.status_code == 400
        # The flight table emptied itself: the next ask runs its own call
        # rather than waiting on an event nobody will set.
        second = client.post(f"/v1/forests/{FOREST}/answer",
                             json={"question": QUESTION}, headers=head)
        assert second.status_code == 200, second.text
        assert second.json()["answer"] == "stub answer after the outage"
    finally:
        client.__exit__(None, None, None)


# -- F.102: the surface serves both new tools --------------------------------


def test_the_mcp_surface_serves_and_names_them(root, tmp_path, monkeypatch):
    app, client, registry, head = _build(tmp_path, monkeypatch, root)
    try:
        r = client.post("/mcp/", headers={**MCP_HEADERS, **head},
                        json={"jsonrpc": "2.0", "id": 1,
                              "method": "tools/list"})
        assert r.status_code == 200, r.text
        names = {t["name"] for t in r.json()["result"]["tools"]}
        assert {"transplant", "history"} <= names
        # C.17 (v0.59) added `coverage`.
        assert len(names) == 20, sorted(names)

        init = client.post("/mcp/", headers={**MCP_HEADERS, **head},
                           json={"jsonrpc": "2.0", "id": 2,
                                 "method": "initialize",
                                 "params": {"protocolVersion": "2025-06-18",
                                            "capabilities": {},
                                            "clientInfo": {"name": "t",
                                                           "version": "1"}}})
        instructions = init.json()["result"]["instructions"]
        for tool in ("transplant", "history"):
            assert tool in instructions, f"{tool} is not named"
    finally:
        client.__exit__(None, None, None)


def test_the_capabilities_are_the_ones_declared(root, tmp_path, monkeypatch):
    app, client, registry, head = _build(tmp_path, monkeypatch, root)
    try:
        _plant(client, head, "notes/capped", "Capped")
        key = registry.issue_key("reader")
        registry.grant("reader", FOREST, {"read"})
        reader = {"Authorization": f"Bearer {key}"}

        # `history` rides read...
        ok = client.post(f"/v1/forests/{FOREST}/history", headers=reader,
                         json={"id": "notes/capped"})
        assert ok.status_code == 200
        # ...and `transplant` rides write.
        denied = client.post(f"/v1/forests/{FOREST}/transplant",
                             headers=reader,
                             json={"id": "notes/capped",
                                   "new_id": "concepts/capped"})
        assert denied.status_code == 403
        assert "write" in denied.json()["error"]["message"]
    finally:
        client.__exit__(None, None, None)
