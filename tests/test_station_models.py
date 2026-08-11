# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Per-forest inference (spec J.10): providers, role bindings, and the
model-backed composites.

The model half is stubbed here. What these tests are for is the wiring that
must hold regardless of which model answers: secrets never travel back to a
client, a binding cannot point at a provider that does not exist, and — the
one that matters — the answering model sees only what the principal could
already read, so binding a model can never become a way around the policy.
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


@pytest.fixture(scope="session")
def models_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("models-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(models_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=models_root, registry_path=tmp_path / "station.db", mcp=False)
    # Binding tests assert what a fresh provider run returns; the answer
    # store (J.10.7) has its own suite.
    app.state.registry.set_setting(FOREST, "answer_cache", {"enabled": False})
    with TestClient(app) as client:
        yield client, app.state.registry


def _admin(registry, principal="root"):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, {"admin", "read", "query", "write"})
    return {"Authorization": f"Bearer {key}"}


def _reader(registry, principal="alice", allow=("projects/",)):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, {"read"}, allow=list(allow))
    return {"Authorization": f"Bearer {key}"}


@pytest.fixture()
def stub_chat(monkeypatch):
    """Replaces the provider call, recording what the model was shown."""
    seen = {}

    def fake(binding, **_kw):
        def chat(messages):
            seen["prompt"] = messages[-1]["content"]
            seen["binding"] = binding
            return "stub answer [evidence]"
        return chat, binding.get("model", "stub")

    from monkeyllm_station import inference

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    return seen


def test_provider_key_never_comes_back(station):
    client, registry = station
    headers = _admin(registry)
    r = client.post("/v1/admin/providers", headers=headers,
                    json={"name": "openrouter", "endpoint": "https://openrouter.ai/api/v1",
                          "api_key": "sk-or-super-secret"})
    assert r.status_code == 200
    body = r.text
    assert "sk-or-super-secret" not in body
    assert r.json()["providers"][0]["has_key"] is True
    assert "sk-or-super-secret" not in client.get("/v1/admin/providers", headers=headers).text


def test_blank_key_keeps_the_stored_one(station):
    """So an operator can fix a typo in the endpoint without re-pasting a
    secret they may not have anymore."""
    client, registry = station
    headers = _admin(registry)
    client.post("/v1/admin/providers", headers=headers,
                json={"name": "p", "endpoint": "https://a/v1", "api_key": "keep-me"})
    client.post("/v1/admin/providers", headers=headers,
                json={"name": "p", "endpoint": "https://b/v1", "api_key": ""})
    stored = registry.provider_secret("p")
    assert stored["endpoint"] == "https://b/v1" and stored["api_key"] == "keep-me"


def test_non_admin_cannot_touch_providers(station):
    client, registry = station
    r = client.get("/v1/admin/providers", headers=_reader(registry))
    assert r.status_code == 403


def test_binding_requires_a_known_provider(station):
    client, registry = station
    r = client.post("/v1/admin/models", headers=_admin(registry),
                    json={"forest": FOREST, "role": "answer",
                          "provider": "ghost", "model": "x"})
    assert r.status_code == 400 and "unknown provider" in r.json()["error"]["message"]


def test_binding_rejects_unknown_role(station):
    client, registry = station
    headers = _admin(registry)
    client.post("/v1/admin/providers", headers=headers,
                json={"name": "p", "endpoint": "https://a/v1", "api_key": "k"})
    r = client.post("/v1/admin/models", headers=headers,
                    json={"forest": FOREST, "role": "sideways", "provider": "p", "model": "x"})
    assert r.status_code == 400


def test_answer_without_a_binding_says_so(station):
    client, registry = station
    r = client.post(f"/v1/forests/{FOREST}/answer", headers=_reader(registry),
                    json={"question": "anything"})
    assert r.status_code == 400
    assert "no model is bound" in r.json()["error"]["message"]
    assert "Studio" in r.json()["error"]["hint"]


def _bind(client, headers, role="answer", model="stub-model"):
    client.post("/v1/admin/providers", headers=headers,
                json={"name": "p", "endpoint": "https://provider/v1", "api_key": "k"})
    client.post("/v1/admin/models", headers=headers,
                json={"forest": FOREST, "role": role, "provider": "p", "model": model})


def test_answer_returns_grounded_reply_with_evidence(station, stub_chat):
    client, registry = station
    admin = _admin(registry)
    _bind(client, admin)
    r = client.post(f"/v1/forests/{FOREST}/answer", headers=admin,
                    json={"question": "who wrote the MixerLLM architecture?", "k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "stub answer [evidence]"
    assert body["model"] == "stub-model"
    assert body["evidence"], "the answer must carry the nodes it was given"


def test_answer_shows_the_model_only_in_scope_material(station, stub_chat):
    """The load-bearing guarantee of J.10: retrieval is scoped first, so a
    bound model cannot be used to read around a grant."""
    client, registry = station
    _bind(client, _admin(registry))
    r = client.post(f"/v1/forests/{FOREST}/answer",
                    headers=_reader(registry, allow=("projects/",)),
                    json={"question": "who is Jimmy Wesley and where does he live?", "k": 3})
    assert r.status_code == 200
    prompt = stub_chat["prompt"]
    for hidden in ("people/", "sales/", "concepts/"):
        assert f'"{hidden}' not in prompt, f"{hidden} reached the model"
    assert all(e.startswith("projects/") for e in r.json()["evidence"])


def test_answer_requires_the_read_cap(station, stub_chat):
    client, registry = station
    _bind(client, _admin(registry))
    key = registry.issue_key("writer-only")
    registry.grant("writer-only", FOREST, {"write"})
    r = client.post(f"/v1/forests/{FOREST}/answer",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"question": "x"})
    assert r.status_code == 403


def test_curate_uses_the_ingest_binding_and_requires_write(station, stub_chat):
    client, registry = station
    admin = _admin(registry)
    _bind(client, admin, role="ingest", model="careful-summariser")
    # a reader may not spend the ingest model's tokens
    assert client.post(f"/v1/forests/{FOREST}/curate", headers=_reader(registry),
                       json={"id": "projects/mixerllm/architecture"}).status_code == 403
    r = client.post(f"/v1/forests/{FOREST}/curate", headers=admin,
                    json={"id": "projects/mixerllm/architecture"})
    assert r.status_code == 200
    assert r.json()["model"] == "careful-summariser"
    assert stub_chat["binding"]["role"] == "ingest"


def test_roles_can_use_different_models(station):
    client, registry = station
    headers = _admin(registry)
    client.post("/v1/admin/providers", headers=headers,
                json={"name": "p", "endpoint": "https://a/v1", "api_key": "k"})
    for role, model in (("ingest", "big-careful"), ("answer", "small-fast")):
        client.post("/v1/admin/models", headers=headers,
                    json={"forest": FOREST, "role": role, "provider": "p", "model": model})
    bound = {b["role"]: b["model"] for b in registry.bindings(FOREST)}
    assert bound == {"ingest": "big-careful", "answer": "small-fast"}


def test_provider_removal_drops_its_bindings(station):
    client, registry = station
    headers = _admin(registry)
    _bind(client, headers)
    assert registry.bindings(FOREST)
    client.post("/v1/admin/providers", headers=headers, json={"name": "p", "remove": True})
    assert registry.bindings(FOREST) == []
