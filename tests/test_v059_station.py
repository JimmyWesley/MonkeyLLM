# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.59 — the forest says what it holds (host half).

F.103/F.104 over the wire: `coverage` under a policy counts only what the
principal may see.
F.107: `min_score` counts evidence, not items.
F.108: a citation carries its scope.
F.110: the share link is one address with two representations, and the
MCP surfaces serve twenty tools.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-holds"

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


# -- F.103/F.104: coverage is scoped like every read -------------------------


class TestScopedCoverage:
    def test_the_roots_are_the_principals_own(self, root, tmp_path, monkeypatch):
        app, client, registry, head = _build(tmp_path, monkeypatch, root)
        try:
            whole = client.post(f"/v1/forests/{FOREST}/coverage", headers=head,
                                json={}).json()
            key = registry.issue_key("narrow")
            registry.grant("narrow", FOREST, {"read"}, allow=["projects/"])
            narrow = {"Authorization": f"Bearer {key}"}

            r = client.post(f"/v1/forests/{FOREST}/coverage", headers=narrow,
                            json={})
            assert r.status_code == 200, r.text
            part = r.json()
            assert [x["id"] for x in part["roots"]] == ["projects/_index"]
            # J.3: the totals describe the grant, never the forest.
            assert part["total"] < whole["total"]
            assert part["total"] == part["roots"][0]["nodes"]

        finally:
            client.__exit__(None, None, None)

    def test_a_read_only_principal_may_ask(self, root, tmp_path, monkeypatch):
        app, client, registry, head = _build(tmp_path, monkeypatch, root)
        try:
            key = registry.issue_key("reader")
            registry.grant("reader", FOREST, {"read"})
            r = client.post(f"/v1/forests/{FOREST}/coverage",
                            headers={"Authorization": f"Bearer {key}"},
                            json={})
            assert r.status_code == 200
            # ... and one without `read` may not.
            key = registry.issue_key("writer")
            registry.grant("writer", FOREST, {"write"})
            r = client.post(f"/v1/forests/{FOREST}/coverage",
                            headers={"Authorization": f"Bearer {key}"},
                            json={})
            assert r.status_code == 403
        finally:
            client.__exit__(None, None, None)


# -- F.107: the floor that counts evidence -----------------------------------


QUESTION = "architecture notes"


class _Chat:
    """A provider that records whether it was asked anything at all."""

    def __init__(self):
        self.calls = 0

    def __call__(self, messages, **kw):
        self.calls += 1
        return "An answer."


class TestMinScore:
    def test_weak_evidence_no_longer_satisfies_the_floor(
            self, root, tmp_path, monkeypatch):
        chat = _Chat()
        app, client, registry, head = _build(tmp_path, monkeypatch, root,
                                             chat=chat)
        try:
            body = {"question": QUESTION, "min_evidence": 1,
                    "min_score": 9.0}
            r = client.post(f"/v1/forests/{FOREST}/answer", headers=head,
                            json=body)
            assert r.status_code == 200, r.text
            out = r.json()
            assert out["answer"] is None
            assert out["reason"] == "insufficient_evidence"
            assert out["min_score"] == 9.0
            assert out["min_evidence"] == 1
            assert "harvest" in out
            assert chat.calls == 0, "a refusal is never billed"
        finally:
            client.__exit__(None, None, None)

    def test_without_it_the_answer_is_what_it_was(
            self, root, tmp_path, monkeypatch):
        chat = _Chat()
        app, client, registry, head = _build(tmp_path, monkeypatch, root,
                                             chat=chat)
        try:
            r = client.post(f"/v1/forests/{FOREST}/answer", headers=head,
                            json={"question": QUESTION,
                                  "min_evidence": 1})
            assert r.json()["answer"] == "An answer."
            assert chat.calls == 1
        finally:
            client.__exit__(None, None, None)

    def test_it_does_not_enter_the_cache_key(self, root, tmp_path, monkeypatch):
        """J.10.10: it cannot change what the model would write, only
        whether it is asked — so two questions differing only in it hit the
        same entry."""
        chat = _Chat()
        app, client, registry, head = _build(tmp_path, monkeypatch, root,
                                             chat=chat)
        try:
            q = {"question": QUESTION}
            first = client.post(f"/v1/forests/{FOREST}/answer", headers=head,
                                json=q).json()
            assert not first.get("cached")
            again = client.post(f"/v1/forests/{FOREST}/answer", headers=head,
                                json={**q, "min_evidence": 1,
                                      "min_score": 0.0001}).json()
            assert again.get("cached") is True
            assert chat.calls == 1
        finally:
            client.__exit__(None, None, None)

    def test_garbage_is_refused_by_name(self, root, tmp_path, monkeypatch):
        chat = _Chat()
        app, client, registry, head = _build(tmp_path, monkeypatch, root,
                                             chat=chat)
        try:
            r = client.post(f"/v1/forests/{FOREST}/answer", headers=head,
                            json={"question": "x", "min_evidence": 1,
                                  "min_score": "loads"})
            assert r.status_code == 400
            assert "min_score" in r.json()["error"]["message"]
        finally:
            client.__exit__(None, None, None)


# -- F.108: a citation carries its scope -------------------------------------


class TestSourcesCarryTheTrail:
    def test_every_source_says_where_it_lives(self, root, tmp_path,
                                              monkeypatch):
        chat = _Chat()
        app, client, registry, head = _build(tmp_path, monkeypatch, root,
                                             chat=chat)
        try:
            out = client.post(f"/v1/forests/{FOREST}/answer", headers=head,
                              json={"question": QUESTION}).json()
            assert out["sources"], out
            by_id = {r["id"]: r for r in out["harvest"]["results"]}
            for source in out["sources"]:
                assert source["trail"] == by_id[source["id"]]["trail"]
        finally:
            client.__exit__(None, None, None)


# -- F.110: one address, two representations; twenty tools -------------------


class TestShareIsOneAddress:
    def _mint(self, client, head):
        r = client.post(f"/v1/forests/{FOREST}/share", headers=head,
                        json={"node": "_index"})
        assert r.status_code == 200, r.text
        return r.json()["url"].rsplit("/", 1)[-1]

    def test_a_machine_gets_the_document(self, root, tmp_path, monkeypatch):
        app, client, registry, head = _build(tmp_path, monkeypatch, root)
        try:
            token = self._mint(client, head)
            direct = client.get(f"/v1/share/{token}")
            assert direct.status_code == 200, direct.text
            page = client.get(f"/s/{token}", headers={"Accept": "*/*"})
            assert page.status_code == 200, page.text
            assert page.json() == direct.json()
        finally:
            client.__exit__(None, None, None)

    def test_every_dead_state_is_one_answer_on_both_paths(
            self, root, tmp_path, monkeypatch):
        app, client, registry, head = _build(tmp_path, monkeypatch, root)
        try:
            missing = client.get("/v1/share/nosuchtoken")
            other = client.get("/s/nosuchtoken", headers={"Accept": "*/*"})
            assert missing.status_code == other.status_code == 404
            assert missing.json() == other.json()
        finally:
            client.__exit__(None, None, None)


def test_the_new_tool_is_served_and_named(root, tmp_path, monkeypatch):
    app, client, registry, head = _build(tmp_path, monkeypatch, root)
    try:
        r = client.post("/mcp/", headers={**MCP_HEADERS, **head},
                        json={"jsonrpc": "2.0", "id": 1,
                              "method": "tools/list"})
        assert r.status_code == 200, r.text
        names = {t["name"] for t in r.json()["result"]["tools"]}
        assert "coverage" in names
        assert len(names) == 20, sorted(names)

        init = client.post("/mcp/", headers={**MCP_HEADERS, **head},
                           json={"jsonrpc": "2.0", "id": 2,
                                 "method": "initialize",
                                 "params": {"protocolVersion": "2025-06-18",
                                            "capabilities": {},
                                            "clientInfo": {"name": "t",
                                                           "version": "1"}}})
        assert "coverage" in init.json()["result"]["instructions"]
    finally:
        client.__exit__(None, None, None)
