# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The wire is for machines (spec v0.54, host half — F.68/F.73).

J.1.2: the MCP text block is compact and `isError` agrees with the envelope;
the server states its version and promises no empty capability. J.10.8: the
provider's cut is reported, a truncated reply is never stored, and the clamp
is echoed.
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
def wire_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("wire-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def mcp_station(wire_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=wire_root, registry_path=tmp_path / "station.db",
                    mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry


def rpc(client, method, params=None, key=None, rid=1):
    headers = dict(MCP_HEADERS)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp/", headers=headers, json=body)


def call(client, name, args, key=None) -> dict:
    r = rpc(client, "tools/call", {"name": name, "arguments": args}, key=key)
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _key(registry, principal="agent", caps=("read",)):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps))
    return key


# --- F.68: the block is for the model ---------------------------------------

def _is_compact(text: str) -> bool:
    """Structural whitespace only: the round trip through the compact
    serializer must be the identity. Values may contain anything."""
    return json.dumps(json.loads(text), ensure_ascii=False,
                      separators=(",", ":")) == text


class TestCompactBlock:
    def test_the_text_block_carries_no_formatting_whitespace(self, mcp_station):
        client, registry = mcp_station
        result = call(client, "locate",
                      {"forest": FOREST, "query": "model", "k": 5},
                      key=_key(registry))
        text = result["content"][0]["text"]
        assert _is_compact(text)
        assert json.loads(text)["results"]  # same keys, same values

    def test_every_read_tool_is_compact(self, mcp_station):
        client, registry = mcp_station
        key = _key(registry)
        for name, args in (
            ("look", {"id": "concepts/rag"}),
            ("scan", {"parent_id": "projects/_index"}),
            ("sniff", {"terms": ["mixerllm"]}),
            ("harvest", {"query": "stigmergy sales"}),
            ("forests", {}),
        ):
            result = call(client, name, {"forest": FOREST, **args} if name != "forests" else {}, key=key)
            assert _is_compact(result["content"][0]["text"]), name


class TestIsErrorAgrees:
    def test_a_domain_refusal_sets_the_flag_and_keeps_the_envelope(self, mcp_station):
        client, registry = mcp_station
        key = _key(registry)
        for name, args, code in (
            ("look", {"forest": "no-such-forest", "id": "x"}, "E_NOT_FOUND"),
            ("look", {"forest": FOREST, "id": "concepts/nope"}, "E_NOT_FOUND"),
            ("tend", {"forest": FOREST, "id": "concepts/rag",
                      "sql": "UPDATE t SET x=1 WHERE 1=1"}, None),
        ):
            result = call(client, name, args, key=key)
            assert result.get("isError") is True, (name, result)
            err = json.loads(result["content"][0]["text"])["error"]
            assert {"code", "message"} <= set(err)
            if code:
                assert err["code"] == code

    def test_an_unauthenticated_call_sets_the_flag(self, mcp_station):
        client, _ = mcp_station
        result = call(client, "locate", {"forest": FOREST, "query": "x"})
        assert result.get("isError") is True

    def test_a_successful_call_does_not(self, mcp_station):
        client, registry = mcp_station
        result = call(client, "locate",
                      {"forest": FOREST, "query": "model"},
                      key=_key(registry))
        assert not result.get("isError")


class TestHandshake:
    def test_serverinfo_states_the_installed_version(self, mcp_station):
        client, registry = mcp_station
        from monkeyllm_station.mcp_surface import package_version

        r = rpc(client, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"},
        }, key=_key(registry))
        assert r.status_code == 200, r.text
        result = r.json()["result"]
        version = result["serverInfo"]["version"]
        assert version and version == package_version()
        # J.1.2 rule 4: no empty promises.
        caps = result["capabilities"]
        assert not caps.get("resources") and not caps.get("prompts")

    def test_the_tools_are_all_still_served(self, mcp_station):
        client, registry = mcp_station
        r = rpc(client, "tools/list", key=_key(registry))
        names = {t["name"] for t in r.json()["result"]["tools"]}
        assert {"forests", "locate", "look", "move", "pick", "view", "scan",
                "sniff", "harvest", "calendar", "answer", "query", "plant",
                "graft", "tend", "ingest"} <= names

    def test_health_carries_the_same_version(self, mcp_station):
        client, _ = mcp_station
        from monkeyllm_station.mcp_surface import package_version

        body = client.get("/v1/health").json()
        assert body["version"] == package_version() != ""


# --- F.73: the provider's cut is reported -----------------------------------

@pytest.fixture()
def model_station(wire_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    state = {"finish": "stop"}
    prompts: list[list] = []

    def fake(binding, **kw):
        def chat(messages):
            prompts.append(messages)
            return "stub answer"
        chat.usage = {"prompt": 10, "completion": 5, "calls": 1}
        chat.finish_reason = state["finish"]
        return chat, binding.get("model", "stub-model")

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    import shutil
    shutil.rmtree(wire_root / FOREST / "_derived" / "cache",
                  ignore_errors=True)

    app = build_app(root=wire_root, registry_path=tmp_path / "station.db",
                    mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"admin", "read", "query", "write"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, state, prompts, {"Authorization": f"Bearer {key}"}


QUESTION = "architecture notes"


class TestReplyFlags:
    def test_a_cut_reply_is_flagged_and_never_stored(self, model_station):
        client, state, prompts, head = model_station
        state["finish"] = "length"
        r = client.post(f"/v1/forests/{FOREST}/answer",
                        json={"question": QUESTION, "reply_tokens": 40},
                        headers=head)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["truncated"] is True
        assert body["finish_reason"] == "length"
        # The clamp is reported: 40 was served by the floor.
        assert body["reply_tokens"] == 64
        # Not stored: the same question runs the model again.
        client.post(f"/v1/forests/{FOREST}/answer",
                    json={"question": QUESTION, "reply_tokens": 40},
                    headers=head)
        assert len(prompts) == 2

    def test_a_finished_reply_carries_no_flags_and_stores(self, model_station):
        client, state, prompts, head = model_station
        state["finish"] = "stop"
        r = client.post(f"/v1/forests/{FOREST}/answer",
                        json={"question": QUESTION, "reply_tokens": 40},
                        headers=head)
        body = r.json()
        assert "truncated" not in body and "finish_reason" not in body
        assert body["reply_tokens"] == 64
        again = client.post(f"/v1/forests/{FOREST}/answer",
                            json={"question": QUESTION, "reply_tokens": 40},
                            headers=head).json()
        assert again.get("cached") is True and len(prompts) == 1
        assert again["reply_tokens"] == 64

    def test_a_stubbed_chat_with_no_reason_reports_none(self, model_station):
        client, state, prompts, head = model_station
        state["finish"] = None
        body = client.post(f"/v1/forests/{FOREST}/answer",
                           json={"question": QUESTION}, headers=head).json()
        assert "truncated" not in body and "finish_reason" not in body
        assert "reply_tokens" not in body  # none was asked for
