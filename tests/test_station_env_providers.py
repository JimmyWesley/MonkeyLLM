# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Providers declared by the deployment (spec J.10.1).

A Station whose endpoint and key already live in environment variables knows
everything the console's provider form would ask for. Asking anyway makes an
operator copy a secret out of the place that governs it and into a place that
does not — so the Station publishes the provider instead, and keeps the key
where it was.

That is the whole point of these tests: the row shows up, the secret does
not, and the console cannot edit a row whose truth lives elsewhere.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
SECRET = "sk-or-not-in-the-registry-please"

ENV = {
    "MONKEYLLM_LLM_ENDPOINT": "https://openrouter.ai/api/v1",
    "MONKEYLLM_LLM_API_KEY": SECRET,
    "MONKEYLLM_LLM_MODEL": "google/gemma-3-12b-it",
}


@pytest.fixture(scope="session")
def env_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("env-providers")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def clean_env(monkeypatch):
    """Every variable this feature reads, unset. Otherwise a developer's own
    `.env` decides what the suite measures."""
    for name in ("MONKEYLLM_LLM_PROVIDER", "MONKEYLLM_LLM_ENDPOINT",
                 "MONKEYLLM_LLM_API_KEY", "MONKEYLLM_EMBED_PROVIDER",
                 "MONKEYLLM_EMBED_ENDPOINT", "MONKEYLLM_EMBED_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture()
def station(env_root, tmp_path, clean_env):
    """Builds a Station with `ENV` declared, and hands back an admin client."""
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    for k, v in ENV.items():
        clean_env.setenv(k, v)
    db = tmp_path / "station.db"
    app = build_app(root=env_root, registry_path=db, mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"admin", "read"})
    with TestClient(app) as client:
        yield client, registry, db, {"Authorization": f"Bearer {key}"}


# -- what the operator sees ------------------------------------------------


def test_a_declared_endpoint_arrives_already_configured(station):
    client, _, _, head = station
    providers = client.get("/v1/admin/providers", headers=head).json()["providers"]
    assert [p["name"] for p in providers] == ["openrouter.ai"]
    p = providers[0]
    assert p["endpoint"] == "https://openrouter.ai/api/v1"
    assert p["origin"] == "env"
    # The point of the feature: nobody has to paste the key.
    assert p["has_key"] is True


def test_the_key_is_still_write_only(station):
    """J.10 says credentials never travel back to a client. Coming from the
    environment must not become a way around that."""
    client, _, _, head = station
    body = client.get("/v1/admin/providers", headers=head).text
    assert SECRET not in body


# -- where the secret lives ------------------------------------------------


def test_the_registry_file_never_holds_the_key(station):
    client, registry, db, head = station
    client.get("/v1/admin/providers", headers=head)
    row = sqlite3.connect(db).execute(
        "SELECT api_key, origin FROM providers WHERE name = 'openrouter.ai'"
    ).fetchone()
    assert row == (None, "env")
    # And not anywhere else in the file either — a registry backup that
    # carries the deployment's key would defeat the whole arrangement.
    assert SECRET.encode() not in Path(db).read_bytes()


def test_a_binding_still_resolves_the_key(station):
    """Not storing it is only acceptable if calls still work."""
    _, registry, _, _ = station
    registry.bind_model(FOREST, "answer", "openrouter.ai", "google/gemma-3-12b-it")
    binding = registry.binding(FOREST, "answer")
    assert binding["endpoint"] == "https://openrouter.ai/api/v1"
    assert binding["api_key"] == SECRET


# -- what the console may not do -------------------------------------------


@pytest.mark.parametrize("body", [
    {"name": "openrouter.ai", "endpoint": "http://evil.local/v1"},
    {"name": "openrouter.ai", "remove": True},
])
def test_the_console_cannot_overwrite_what_the_environment_declares(station, body):
    """Accepting the edit would be worse than refusing it: the next restart
    would silently undo it, and until then the operator would be looking at
    a configuration the deployment does not have."""
    client, _, _, head = station
    r = client.post("/v1/admin/providers", json=body, headers=head)
    assert r.status_code == 400
    assert "environment" in r.json()["error"]["message"]
    after = client.get("/v1/admin/providers", headers=head).json()["providers"]
    assert [p["endpoint"] for p in after] == ["https://openrouter.ai/api/v1"]


def test_console_providers_are_untouched(station):
    client, _, _, head = station
    client.post("/v1/admin/providers",
                json={"name": "local", "endpoint": "http://localhost:8090/v1"},
                headers=head)
    providers = client.get("/v1/admin/providers", headers=head).json()["providers"]
    local = next(p for p in providers if p["name"] == "local")
    assert local["origin"] == "console"
    assert client.post("/v1/admin/providers",
                       json={"name": "local", "remove": True},
                       headers=head).status_code == 200


# -- reading the environment ------------------------------------------------


def _declared(**env):
    from monkeyllm_station.app import providers_from_env

    return providers_from_env(env)


def test_nothing_declared_is_nothing_published():
    """The console form stays the only way in for a deployment that sets
    none of this — the behaviour every existing test relies on."""
    assert _declared() == []
    assert _declared(MONKEYLLM_LLM_API_KEY="sk-orphan") == []


def test_the_name_follows_the_host_unless_it_is_given():
    assert _declared(MONKEYLLM_LLM_ENDPOINT="https://openrouter.ai/api/v1"
                     )[0]["name"] == "openrouter.ai"
    assert _declared(MONKEYLLM_LLM_ENDPOINT="https://openrouter.ai/api/v1",
                     MONKEYLLM_LLM_PROVIDER="boost")[0]["name"] == "boost"


def test_a_keyless_local_server_is_still_a_provider():
    declared = _declared(MONKEYLLM_LLM_ENDPOINT="http://localhost:8090/v1")
    assert declared == [{"name": "localhost:8090",
                         "endpoint": "http://localhost:8090/v1", "api_key": None}]


def test_two_servers_on_one_host_do_not_collapse_into_one():
    """Merging them would bind the embedder to the chat server's port —
    well-formed, accepted, and wrong until the first call."""
    names = [p["name"] for p in _declared(
        MONKEYLLM_LLM_ENDPOINT="http://localhost:8090/v1",
        MONKEYLLM_EMBED_ENDPOINT="http://localhost:8091/v1")]
    assert names == ["localhost:8090", "localhost:8091"]


def test_one_gateway_serving_both_roles_is_one_provider():
    declared = _declared(MONKEYLLM_LLM_ENDPOINT="http://gw.local/v1",
                         MONKEYLLM_LLM_API_KEY="k",
                         MONKEYLLM_EMBED_ENDPOINT="http://gw.local/v1",
                         MONKEYLLM_EMBED_API_KEY="k")
    assert [p["name"] for p in declared] == ["gw.local"]


def test_naming_one_role_does_not_split_a_shared_gateway():
    """Identity is the endpoint and the key. Naming only the chat variable
    must not turn one Ollama into `ollama` plus `ollama.local`."""
    declared = _declared(MONKEYLLM_LLM_PROVIDER="ollama",
                         MONKEYLLM_LLM_ENDPOINT="http://ollama.local/v1",
                         MONKEYLLM_EMBED_ENDPOINT="http://ollama.local/v1")
    assert [p["name"] for p in declared] == ["ollama"]

    # Named on the embed side instead: same one provider, same chosen name.
    declared = _declared(MONKEYLLM_LLM_ENDPOINT="http://ollama.local/v1",
                         MONKEYLLM_EMBED_PROVIDER="ollama",
                         MONKEYLLM_EMBED_ENDPOINT="http://ollama.local/v1")
    assert [p["name"] for p in declared] == ["ollama"]


def test_the_same_host_with_a_different_key_stays_two(clean_env):
    declared = _declared(MONKEYLLM_LLM_ENDPOINT="http://gw.local/v1",
                         MONKEYLLM_LLM_API_KEY="chat-key",
                         MONKEYLLM_EMBED_ENDPOINT="http://gw.local/v1",
                         MONKEYLLM_EMBED_API_KEY="embed-key")
    assert [p["name"] for p in declared] == ["gw.local", "gw.local-embed"]


# -- withdrawing the declaration -------------------------------------------


def test_taking_over_a_typed_name_does_not_destroy_its_key(station):
    """Somebody typed `house` yesterday; today the deployment declares one
    with the same name. The declaration wins while it stands — but throwing
    the stored key away would leave nothing to fall back to when it is
    withdrawn, and nobody can re-read a write-only secret to restore it."""
    _, registry, _, _ = station
    registry.put_provider("house", "http://typed.local/v1", "typed-key")

    registry.adopt_env_providers([{"name": "house",
                                   "endpoint": "http://declared.local/v1",
                                   "api_key": "declared-key"}])
    secret = registry.provider_secret("house")
    assert (secret["endpoint"], secret["api_key"]) == ("http://declared.local/v1",
                                                       "declared-key")

    registry.adopt_env_providers([])
    assert registry.provider_secret("house")["api_key"] == "typed-key"


def test_undeclaring_hands_the_row_back_instead_of_deleting_it(station):
    """Deleting it would take its bindings with it (J.10), so a renamed
    variable would silently unbind a forest. It becomes an ordinary console
    provider missing its key — visibly broken, and fixable in the console."""
    _, registry, _, _ = station
    registry.bind_model(FOREST, "answer", "openrouter.ai", "google/gemma-3-12b-it")

    registry.adopt_env_providers([])

    provider = registry.providers()[0]
    assert provider["origin"] == "console"
    assert provider["has_key"] is False
    assert registry.binding(FOREST, "answer")["provider"] == "openrouter.ai"
    assert registry.binding(FOREST, "answer")["api_key"] is None


# -- when the connection test itself is what is broken ---------------------


def test_a_probe_that_cannot_run_still_answers(station, monkeypatch):
    """`httpx` missing from the image made the Test button raise inside the
    handler, so the card said "could not reach it" and the operator went
    looking at their key. A probe that cannot run is a failed probe with a
    reason, never a 500 — the reason is the only thing that points at the
    real fault."""
    client, _, _, head = station
    monkeypatch.setitem(sys.modules, "httpx", None)  # as if it were not installed

    r = client.post("/v1/admin/providers/test",
                    json={"name": "openrouter.ai"}, headers=head)

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "httpx" in body["error"]


def test_the_host_declares_what_it_imports():
    """The probe worked on every developer machine and on none of the
    deployments, because `httpx` was a `dev` extra and `mcp` brings `httpx2`
    — a different distribution. A dependency the host imports at runtime
    belongs in `dependencies`, or the image is the only place it is missing."""
    text = (STATION / "pyproject.toml").read_text(encoding="utf-8")
    runtime = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert "httpx>=" in runtime
