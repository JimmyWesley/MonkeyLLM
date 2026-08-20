# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The v0.52 host halves: a batch under a policy (C.11 / F.57), a write you
can repeat (C.7.2 / F.61), the surface that answers only to itself
(J.1.1 / F.62), and the answer it should not give (J.10.10 / F.63).

Three of these are about a caller being able to tell two situations apart.
The fourth — J.1.1 — is about an operator being able to: a Station published
under a domain refused every MCP request while `/v1/health` said `ok`, and
the only signal that reached anybody was `Failed to connect`.
"""

from __future__ import annotations

import shutil
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
def v52_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("v52-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(v52_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=v52_root, registry_path=tmp_path / "station.db", mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry


def _key(registry, principal="agent", caps=("read", "write"), allow=("",)):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), allow=list(allow))
    return {"Authorization": f"Bearer {key}"}


def call(client, head, primitive, body):
    return client.post(f"/v1/forests/{FOREST}/{primitive}", json=body, headers=head)


# --- C.11 / F.57: a batch under a policy -----------------------------------

def test_a_batch_returns_the_caller_s_order_over_rest(station):
    client, registry = station
    ids = ["concepts/stigmergy", "concepts/rrf"]
    out = call(client, _key(registry), "look", {"id": ids}).json()
    assert [n["id"] for n in out["nodes"]] == ids


def test_out_of_scope_and_absent_are_the_same_word_in_a_batch(station):
    """J.3's rule survives the new shape: a batch MUST NOT become the
    surface that tells a hidden node from a missing one."""
    client, registry = station
    head = _key(registry, "scoped", caps=("read",), allow=("concepts/",))
    out = call(client, head, "look",
               {"id": ["concepts/stigmergy", "people/jimmy-wesley",
                       "concepts/not-a-real-node"]}).json()
    assert [n["id"] for n in out["nodes"]] == ["concepts/stigmergy"]
    assert set(out["missing"]) == {"people/jimmy-wesley", "concepts/not-a-real-node"}


def test_a_scoped_empty_locate_never_counts_the_whole_forest(station):
    """C.1.1: `searched` is bounded by what the principal may see —
    otherwise an entry search becomes a size oracle for the region they
    were not granted."""
    client, registry = station
    head = _key(registry, "narrow", caps=("read",), allow=("concepts/",))
    out = call(client, head, "locate", {"query": "zzqqx-nothing-here"}).json()
    assert out["results"] == []
    assert 0 < out["searched"] < 82
    assert "sniff" in out["hint"]


def test_a_batch_over_the_cap_is_e_schema_over_rest(station):
    client, registry = station
    r = call(client, _key(registry), "pick", {"id": [f"x{i}" for i in range(6)]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "E_SCHEMA"


def test_the_mcp_tool_takes_a_batch_too(station):
    import json

    client, registry = station
    head = _key(registry)
    r = client.post("/mcp/", headers={**MCP_HEADERS, **head}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "look", "arguments": {
            "forest": FOREST, "id": ["concepts/aco", "concepts/rrf"]}}})
    assert r.status_code == 200, r.text
    out = json.loads(r.json()["result"]["content"][0]["text"])
    assert [n["id"] for n in out["nodes"]] == ["concepts/aco", "concepts/rrf"]


# --- C.7.2 / F.61: a write you can repeat ----------------------------------

NODE = {"id": "concepts/idempotence", "type": "concept", "parent": "concepts/_index",
        "title": "Idempotence", "summary": "An operation whose repetition changes "
        "nothing after the first time, which is what makes a write retryable.",
        "body": "# Idempotence\n\nRepeating it is free.\n"}


def test_a_plant_says_it_created_and_a_repeat_is_refused(station):
    client, registry = station
    head = _key(registry)
    first = call(client, head, "plant", {"node": NODE})
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True and first.json()["commit"]

    again = call(client, head, "plant", {"node": NODE})
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "E_SCHEMA"
    assert "already exists" in again.json()["error"]["message"]


def test_if_absent_makes_the_write_repeatable(station):
    client, registry = station
    head = _key(registry)
    node = {**NODE, "id": "concepts/retry-safety",
            "summary": "The property that lets an agent repeat a write whose "
                       "outcome it never learned."}
    assert call(client, head, "plant", {"node": node}).json()["created"] is True

    changed = {**node, "body": "# Retry safety\n\nA DIFFERENT body.\n"}
    out = call(client, head, "plant",
               {"node": changed, "if_absent": True}).json()
    assert out["created"] is False
    assert "commit" not in out
    assert out["trail"]

    # Nothing was written: the existing node is byte-identical, and the
    # submitted content was never compared, merged or applied (C.7.2).
    body = call(client, head, "pick", {"id": node["id"]}).json()["body"]
    assert "A DIFFERENT body" not in body


def test_if_absent_still_plants_when_the_id_is_free(station):
    client, registry = station
    head = _key(registry)
    node = {**NODE, "id": "concepts/first-time",
            "summary": "A node planted by an if_absent call that found the "
                       "id free, which must behave exactly like a plant."}
    out = call(client, head, "plant", {"node": node, "if_absent": True}).json()
    assert out["created"] is True and out["commit"]


def test_if_absent_cannot_probe_outside_the_grant(station):
    client, registry = station
    head = _key(registry, "scoped-writer", caps=("read", "write"),
                allow=("concepts/",))
    r = call(client, head, "plant",
             {"node": {**NODE, "id": "people/someone-else",
                       "parent": "people/_index"}, "if_absent": True})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "E_FORBIDDEN"


# --- J.1.1 / F.62: the surface that answers only to itself ------------------

def test_a_refused_host_gets_the_envelope_not_nineteen_bytes(station):
    client, registry = station
    head = _key(registry)
    r = client.post("/mcp/", headers={**MCP_HEADERS, **head, "Host": "evil.example"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 421, r.text
    err = r.json()["error"]
    assert err["code"] == "E_HOST_NOT_ALLOWED"
    assert "evil.example" in err["message"]
    assert "MONKEYLLM_STATION_ALLOWED_HOSTS" in err["hint"]


def test_the_allow_list_is_never_disclosed(station):
    client, registry = station
    r = client.post("/mcp/", headers={**MCP_HEADERS, **_key(registry),
                                      "Host": "evil.example"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    body = r.text
    assert "testserver" not in body and "localhost" not in body


def test_an_allowed_host_still_completes_the_handshake(station):
    client, registry = station
    r = client.post("/mcp/", headers={**MCP_HEADERS, **_key(registry)},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200 and r.json()["result"]["tools"]


def test_health_reports_the_verdict_for_this_request_s_host(station):
    client, _ = station
    good = client.get("/v1/health").json()["mcp"]
    assert good == {"enabled": True, "host_allowed": True}
    bad = client.get("/v1/health", headers={"Host": "evil.example"}).json()["mcp"]
    assert bad["host_allowed"] is False
    # It reports; it does not list.
    assert "allowed_hosts" not in bad


def test_a_station_without_mcp_says_so(v52_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=v52_root, registry_path=tmp_path / "off.db", mcp=False)
    with TestClient(app) as client:
        assert client.get("/v1/health").json()["mcp"] == {"enabled": False}


def test_the_boot_warns_when_the_allow_list_is_the_default(v52_root, tmp_path,
                                                           monkeypatch, caplog):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app
    from monkeyllm_station.mcp_surface import ALLOWED_HOSTS_ENV

    monkeypatch.delenv(ALLOWED_HOSTS_ENV, raising=False)
    with caplog.at_level("WARNING", logger="monkeyllm_station"):
        app = build_app(root=v52_root, registry_path=tmp_path / "warn.db", mcp=True)
        with TestClient(app):
            pass
    warned = [r.getMessage() for r in caplog.records
              if ALLOWED_HOSTS_ENV in r.getMessage()]
    assert warned, [r.getMessage() for r in caplog.records]
    assert "421" in warned[0] or "and nothing else" in warned[0]


def test_a_named_host_is_accepted_and_reported(v52_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app
    from monkeyllm_station.mcp_surface import ALLOWED_HOSTS_ENV

    monkeypatch.setenv(ALLOWED_HOSTS_ENV, "srv1.example.com,testserver")
    app = build_app(root=v52_root, registry_path=tmp_path / "named.db", mcp=True)
    registry = app.state.registry
    head = _key(registry)
    with TestClient(app) as client:
        r = client.post("/mcp/", headers={**MCP_HEADERS, **head,
                                          "Host": "srv1.example.com"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 200, r.text
        assert client.get("/v1/health",
                          headers={"Host": "srv1.example.com"}
                          ).json()["mcp"]["host_allowed"] is True


# --- J.10.10 / F.63: the answer it should not give -------------------------

@pytest.fixture()
def answering(v52_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    calls: list = []

    def fake(binding, **kw):
        def chat(messages):
            calls.append(messages)
            return "a stub answer"
        return chat, binding.get("model", "stub-model")

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    shutil.rmtree(v52_root / FOREST / "_derived" / "cache", ignore_errors=True)
    app = build_app(root=v52_root, registry_path=tmp_path / "ask.db", mcp=False)
    registry = app.state.registry
    key = registry.issue_key("asker")
    registry.grant("asker", FOREST, {"read", "admin"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, calls, {"Authorization": f"Bearer {key}"}


def _ask(client, head, **body):
    r = client.post(f"/v1/forests/{FOREST}/answer", json=body, headers=head)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_floor_above_the_evidence_declines_before_the_model(answering):
    client, calls, head = answering
    out = _ask(client, head, question="zzqqx yyzzw qqxxz", k=3, min_evidence=2)
    assert out["answer"] is None
    assert out["reason"] == "insufficient_evidence"
    assert out["evidence_count"] < out["min_evidence"]
    # The retrieval comes back: the caller asked a question, and "here is
    # everything the forest has, and it is not enough" is the honest reply.
    assert "harvest" in out
    assert calls == [], "the provider was called for a refused answer"
    assert "cost" not in out and "usage" not in out


def test_the_same_question_without_the_floor_answers(answering):
    client, calls, head = answering
    out = _ask(client, head, question="stigmergy pheromone", k=3)
    assert out.get("answer")
    assert calls, "the provider should have run"


def test_a_floor_the_evidence_meets_is_invisible(answering):
    client, calls, head = answering
    out = _ask(client, head, question="stigmergy pheromone", k=3, min_evidence=1)
    assert out.get("answer") and out.get("reason") is None
    assert calls


def test_min_evidence_is_clamped_to_what_the_sweep_can_return(answering):
    """A floor above the number of items the sweep may produce would be a
    refusal by arithmetic (J.10.10 rule 5)."""
    client, _calls, head = answering
    out = _ask(client, head, question="stigmergy pheromone", k=2, min_evidence=99)
    # Clamped to the effective k: either the sweep met it and the answer is
    # ordinary, or it did not and the floor reported is the clamped one —
    # never the 99 that no sweep could ever satisfy.
    assert out.get("answer") or out["min_evidence"] <= 2


def test_a_refusal_is_never_stored(answering):
    client, calls, head = answering
    _ask(client, head, question="zzqqx yyzzw qqxxz", min_evidence=2)
    after = _ask(client, head, question="zzqqx yyzzw qqxxz")
    # The second ask ran the model: no entry was left behind by the refusal.
    assert after.get("cached") is not True
    assert calls


# --- C.13.1 rule 8: a window names the answer it produced ------------------

def test_two_windows_are_two_entries(answering):
    """`min_evidence` cannot change what the model would write; a window
    changes what it could read. So this one keys, and that one does not."""
    client, calls, head = answering
    first = _ask(client, head, question="stigmergy pheromone",
                 since="2026-01-01", until="2026-12-31")
    assert first.get("answer") and len(calls) == 1

    # same question, same window: served from the store, no second call
    again = _ask(client, head, question="stigmergy pheromone",
                 since="2026-01-01", until="2026-12-31")
    assert again.get("cached") is True and len(calls) == 1

    # same question, a different window: a different entry, and the model runs
    other = _ask(client, head, question="stigmergy pheromone",
                 since="2020-01-01", until="2020-12-31")
    assert other.get("cached") is not True


def test_a_windowless_ask_is_unaffected(answering):
    client, calls, head = answering
    _ask(client, head, question="pheromone whisper")
    before = len(calls)
    hit = _ask(client, head, question="pheromone whisper")
    assert hit.get("cached") is True and len(calls) == before
