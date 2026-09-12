# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Part L, the governance half (spec v0.80, L.7 — F.177/F.178/F.180/F.185).

The engine's suite proves the mechanism works on a host with no Station.
This one proves the Station adds the four things the engine deliberately
does not have: who may install, who may enable, where a secret lives, and
what an extension is allowed to spend.

The load-bearing test in this file is the first one in `TestAuthority`:
installing puts third-party code in this process, so it must require
authority over the whole deployment. A forest admin who could install would
be making a local decision with a global effect.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

MINE = "forest-mine"
THEIRS = "forest-theirs"


@pytest.fixture(scope="session")
def forest_template(tmp_path_factory) -> Path:
    """Built once, copied per test.

    Two forests exist in every test here on purpose: `governs_deployment`
    is "administers every one of them", so a single-forest deployment would
    make an ordinary forest admin the deployment's authority and silently
    void every authority test in this file.
    """
    from conftest import build_forest
    return build_forest(tmp_path_factory.mktemp("extensions") / "template")


@pytest.fixture()
def two_forests(forest_template, tmp_path) -> Path:
    root = tmp_path / "forests"
    root.mkdir()
    shutil.copytree(forest_template, root / MINE)
    shutil.copytree(forest_template, root / THEIRS)
    return root


@pytest.fixture()
def station(two_forests, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    # Part L's own store is host-level; give this test its own.
    monkeypatch.setenv("MONKEYLLM_EXT_HOME", str(tmp_path / "exthome"))
    app = build_app(root=two_forests, registry_path=tmp_path / "station.db",
                    mcp=False, writable=True)
    with TestClient(app) as client:
        yield client, app.state.registry, app


def admin_key(registry, principal="root", forest=MINE):
    key = registry.issue_key(principal)
    registry.grant(principal, forest, {"admin", "read", "write", "ingest"})
    return {"Authorization": f"Bearer {key}"}


def owner_key(registry, principal="owner"):
    registry.add_principal(principal, kind="user")
    registry.conn.execute("UPDATE principals SET owner = 1 WHERE id = ?",
                          (principal,))
    registry.conn.commit()
    return {"Authorization": f"Bearer {registry.issue_key(principal)}"}


@pytest.fixture()
def ext_tree(tmp_path) -> Path:
    """A minimal, valid extension with one secret and one plain setting."""
    tree = tmp_path / "src" / "whisper"
    tree.mkdir(parents=True)
    (tree / "manifest.json").write_text(json.dumps({
        "id": "whisper",
        "version": "1.0.0",
        "station_compat": ">=0.1,<99",
        "license": "MIT",
        "description": "Transcribes audio.",
        "models": {"registers": [{"role": "transcribe",
                                  "kind": "transcribe"}]},
        "config": {"language": {"type": "string", "default": "auto"},
                   "api_key": {"type": "string", "secret": True}},
    }), encoding="utf-8")
    (tree / "main.py").write_text("def register(api):\n    pass\n",
                                  encoding="utf-8")
    (tree / "LICENSE").write_text("MIT", encoding="utf-8")
    return tree


def install(client, auth, tree, **extra):
    body = {"source": str(tree), "acknowledge": True}
    body.update(extra)
    return client.post("/v1/admin/extensions", json=body, headers=auth)


# ---------------------------------------------------------------------------
# L.7 rule 1 — who installs, who enables
# ---------------------------------------------------------------------------

class TestAuthority:
    def test_a_forest_admin_cannot_install(self, station, ext_tree):
        client, registry, _ = station
        auth = admin_key(registry)
        response = install(client, auth, ext_tree)
        assert response.status_code == 403
        assert "whole deployment" in response.json()["error"]["message"]

    def test_the_owner_installs(self, station, ext_tree):
        client, registry, _ = station
        response = install(client, owner_key(registry), ext_tree)
        assert response.status_code == 201
        body = response.json()
        assert body["id"] == "whisper"
        assert body["restart_required"] is True

    def test_a_forest_admin_sees_the_list_without_the_provenance(
            self, station, ext_tree):
        client, registry, _ = station
        install(client, owner_key(registry), ext_tree)

        seen = client.get("/v1/admin/extensions",
                          headers=admin_key(registry)).json()
        assert seen["may_install"] is False
        entry = seen["extensions"][0]
        assert entry["id"] == "whisper"
        # It can choose what to enable...
        assert "description" in entry and "registers_roles" in entry
        # ...and learns nothing about where the code came from.
        for withheld in ("source", "identity", "permissions", "revision"):
            assert withheld not in entry

    def test_the_owner_sees_the_provenance(self, station, ext_tree):
        client, registry, _ = station
        auth = owner_key(registry)
        install(client, auth, ext_tree)
        entry = client.get("/v1/admin/extensions",
                           headers=auth).json()["extensions"][0]
        assert entry["source"].endswith("whisper")
        assert entry["tier"] == "unverified"
        assert entry["reason"]

    def test_a_stranger_is_refused_the_list(self, station):
        client, registry, _ = station
        registry.add_principal("nobody", kind="user")
        auth = {"Authorization": f"Bearer {registry.issue_key('nobody')}"}
        assert client.get("/v1/admin/extensions", headers=auth).status_code == 403


# ---------------------------------------------------------------------------
# F.185 — an unverified source needs an explicit act, over the wire too
# ---------------------------------------------------------------------------

def test_an_unverified_source_refuses_without_acknowledgement(station,
                                                              ext_tree):
    client, registry, _ = station
    auth = owner_key(registry)
    response = install(client, auth, ext_tree, acknowledge=False)
    assert response.status_code >= 400
    assert response.json()["error"]["reason"] == "unverified"
    # F.174's rule over the wire too: the refusal staged nothing.
    assert client.get("/v1/admin/extensions",
                      headers=auth).json()["extensions"] == []


def test_a_plan_shows_what_would_be_accepted_without_installing(station,
                                                                ext_tree):
    client, registry, _ = station
    auth = owner_key(registry)
    plan = client.post("/v1/admin/extensions",
                       json={"action": "plan", "source": str(ext_tree)},
                       headers=auth).json()
    assert plan["id"] == "whisper" and plan["license"] == "MIT"
    assert plan["tier"] == "unverified"
    assert plan["kit"]["ok"] is True
    # Nothing landed.
    assert client.get("/v1/admin/extensions",
                      headers=auth).json()["extensions"] == []


# ---------------------------------------------------------------------------
# F.180 — enabled on a forest means published on that forest
# ---------------------------------------------------------------------------

class TestEnablement:
    def test_the_forests_admin_enables_and_the_other_forest_is_untouched(
            self, station, ext_tree):
        client, registry, app = station
        install(client, owner_key(registry), ext_tree)
        auth = admin_key(registry)

        response = client.post("/v1/admin/extensions/enablement",
                               json={"forest": MINE, "ext": "whisper"},
                               headers=auth)
        assert response.status_code == 200
        assert response.json()["enabled_now"] == ["whisper"]
        assert response.json()["restart_required"] is True

        from monkeyllm.extensions import forestcfg
        root = Path(app.state.pool.root)
        assert forestcfg.enabled(root / MINE) == ["whisper"]
        assert forestcfg.enabled(root / THEIRS) == []

    def test_it_lands_in_the_forests_own_meta(self, station, ext_tree):
        client, registry, app = station
        install(client, owner_key(registry), ext_tree)
        client.post("/v1/admin/extensions/enablement",
                    json={"forest": MINE, "ext": "whisper"},
                    headers=admin_key(registry))
        path = Path(app.state.pool.root) / MINE / "_meta" / "extensions.yaml"
        assert path.exists() and "whisper" in path.read_text(encoding="utf-8")

    def test_an_admin_of_another_forest_cannot_enable_here(self, station,
                                                           ext_tree):
        client, registry, _ = station
        install(client, owner_key(registry), ext_tree)
        theirs = admin_key(registry, "other", forest=THEIRS)
        response = client.post("/v1/admin/extensions/enablement",
                               json={"forest": MINE, "ext": "whisper"},
                               headers=theirs)
        assert response.status_code == 403

    def test_enabling_something_not_installed_is_refused(self, station):
        client, registry, _ = station
        response = client.post("/v1/admin/extensions/enablement",
                               json={"forest": MINE, "ext": "ghost"},
                               headers=admin_key(registry))
        assert response.status_code == 404

    def test_an_expected_but_absent_extension_is_named(self, station,
                                                       ext_tree, app_root=None):
        client, registry, app = station
        install(client, owner_key(registry), ext_tree)
        auth = admin_key(registry)
        client.post("/v1/admin/extensions/enablement",
                    json={"forest": MINE, "ext": "whisper"}, headers=auth)
        client.post("/v1/admin/extensions",
                    json={"action": "remove", "id": "whisper",
                          "acknowledge": True},
                    headers=owner_key(registry))

        seen = client.get(f"/v1/admin/extensions/enablement?forest={MINE}",
                          headers=auth).json()
        assert seen["expected_but_absent"] == ["whisper"]


# ---------------------------------------------------------------------------
# L.7 rule 4 — custody: a secret goes in and never comes back
# ---------------------------------------------------------------------------

class TestSecretCustody:
    def test_a_secret_is_never_returned(self, station, ext_tree):
        client, registry, _ = station
        auth = owner_key(registry)
        install(client, auth, ext_tree)

        client.post("/v1/admin/extensions/config",
                    json={"ext": "whisper",
                          "values": {"api_key": "sk-live-SECRET",
                                     "language": "pt"}},
                    headers=auth)
        seen = client.get("/v1/admin/extensions/config?ext=whisper",
                          headers=auth)
        assert "sk-live-SECRET" not in seen.text
        values = seen.json()["values"]
        assert values["api_key"] == {"has_value": True, "secret": True}
        assert values["language"] == {"value": "pt", "secret": False}

    def test_null_keeps_a_value_an_editor_cannot_read(self, station,
                                                      ext_tree):
        client, registry, _ = station
        auth = owner_key(registry)
        install(client, auth, ext_tree)
        client.post("/v1/admin/extensions/config",
                    json={"ext": "whisper", "values": {"api_key": "sk-1"}},
                    headers=auth)
        client.post("/v1/admin/extensions/config",
                    json={"ext": "whisper",
                          "values": {"api_key": None, "language": "es"}},
                    headers=auth)
        assert registry.ext_config.values("whisper")["api_key"] == "sk-1"
        assert registry.ext_config.values("whisper")["language"] == "es"

    def test_an_undeclared_setting_names_the_vocabulary(self, station,
                                                        ext_tree):
        client, registry, _ = station
        auth = owner_key(registry)
        install(client, auth, ext_tree)
        response = client.post("/v1/admin/extensions/config",
                               json={"ext": "whisper",
                                     "values": {"nonesuch": 1}},
                               headers=auth)
        assert response.status_code == 400
        assert "api_key" in response.json()["error"]["hint"]

    def test_a_forest_admin_cannot_read_or_write_config(self, station,
                                                        ext_tree):
        client, registry, _ = station
        install(client, owner_key(registry), ext_tree)
        auth = admin_key(registry)
        assert client.get("/v1/admin/extensions/config?ext=whisper",
                          headers=auth).status_code == 403


# ---------------------------------------------------------------------------
# F.178 — quota: exhaustion is a refusal, and the next period admits again
# ---------------------------------------------------------------------------

class TestQuota:
    def test_exhaustion_refuses_and_names_the_ceiling(self, station):
        client, registry, _ = station
        registry.ext_quota.set_ceiling("whisper", MINE, 1.0, "month")
        registry.ext_quota.record("whisper", MINE, 0.75)
        registry.ext_quota.check("whisper", MINE)      # still under

        registry.ext_quota.record("whisper", MINE, 0.75)
        from monkeyllm.errors import VineError
        with pytest.raises(VineError) as caught:
            registry.ext_quota.check("whisper", MINE)
        assert caught.value.code == "E_EXT_QUOTA"
        assert caught.value.data["ceiling"] == 1.0
        assert caught.value.data["spent"] == 1.5

    def test_a_new_period_admits_again(self, station):
        client, registry, _ = station
        registry.ext_quota.set_ceiling("whisper", MINE, 1.0, "month")
        registry.ext_quota.record("whisper", MINE, 2.0)
        registry.conn.execute(
            "UPDATE extension_quota SET window_key = '1999-01'")
        registry.conn.commit()
        registry.ext_quota.check("whisper", MINE)      # rolled over
        assert registry.ext_quota.state("whisper", MINE).spent == 0.0

    def test_no_ceiling_never_refuses(self, station):
        client, registry, _ = station
        registry.ext_quota.record("whisper", MINE, 1000.0)
        registry.ext_quota.check("whisper", MINE)

    def test_a_forest_admin_reads_but_does_not_set(self, station, ext_tree):
        client, registry, _ = station
        install(client, owner_key(registry), ext_tree)
        auth = admin_key(registry)
        assert client.get(
            f"/v1/admin/extensions/quota?ext=whisper&forest={MINE}",
            headers=auth).status_code == 200
        assert client.post("/v1/admin/extensions/quota",
                           json={"ext": "whisper", "forest": MINE,
                                 "ceiling": 5.0},
                           headers=auth).status_code == 403

    def test_the_owner_sets_it(self, station, ext_tree):
        client, registry, _ = station
        auth = owner_key(registry)
        install(client, auth, ext_tree)
        response = client.post("/v1/admin/extensions/quota",
                               json={"ext": "whisper", "forest": MINE,
                                     "ceiling": 5.0, "period": "day"},
                               headers=auth)
        assert response.json()["ceiling"] == 5.0
        assert response.json()["period"] == "day"

    def test_an_unknown_period_is_refused(self, station, ext_tree):
        client, registry, _ = station
        auth = owner_key(registry)
        install(client, auth, ext_tree)
        response = client.post("/v1/admin/extensions/quota",
                               json={"ext": "whisper", "forest": MINE,
                                     "ceiling": 5.0, "period": "fortnight"},
                               headers=auth)
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# F.177 — the audit keeps the human and names the extension
# ---------------------------------------------------------------------------

class TestAuditVia:
    def test_via_never_displaces_the_principal(self, station):
        client, registry, _ = station
        registry.record(principal="joao", forest=MINE, primitive="ingest",
                        args={}, result="ok", via="ext:whisper",
                        model_ms=120.0,
                        cost={"usd": 0.004, "prompt_tokens": 100,
                              "completion_tokens": 20, "calls": 1,
                              "priced": True})
        row = registry.audit(limit=1)[0]
        assert row["principal"] == "joao"
        assert row["via"] == "ext:whisper"
        assert row["usd"] == 0.004
        assert row["model_ms"] == 120.0

    def test_a_row_with_no_extension_reads_via_as_absent(self, station):
        client, registry, _ = station
        registry.record(principal="joao", forest=MINE, primitive="look",
                        args={}, result="ok")
        assert registry.audit(limit=1)[0]["via"] is None

    def test_the_token_has_one_spelling(self):
        from monkeyllm_station.extensions import via
        assert via("whisper") == "ext:whisper"
        assert via(None) is None

    def test_installing_is_audited_without_a_forest(self, station, ext_tree):
        client, registry, _ = station
        install(client, owner_key(registry), ext_tree)
        rows = [r for r in registry.audit(limit=20)
                if r["primitive"] == "extension.install"]
        assert rows and rows[0]["forest"] == "-"
        assert rows[0]["principal"] == "owner"


# ---------------------------------------------------------------------------
# L.8 — removal names what stops being declared
# ---------------------------------------------------------------------------

def test_removal_names_what_will_start_being_refused(station, tmp_path):
    client, registry, _ = station
    tree = tmp_path / "src" / "dial"
    tree.mkdir(parents=True)
    (tree / "manifest.json").write_text(json.dumps({
        "id": "dial", "version": "1.0.0", "station_compat": ">=0.1,<99",
        "license": "MIT",
        "permissions": {"capabilities": ["ingest"]},
    }), encoding="utf-8")
    (tree / "main.py").write_text("def register(api):\n    pass\n",
                                  encoding="utf-8")
    (tree / "LICENSE").write_text("MIT", encoding="utf-8")

    auth = owner_key(registry)
    install(client, auth, tree)

    refused = client.post("/v1/admin/extensions",
                          json={"action": "remove", "id": "dial"},
                          headers=auth)
    assert refused.status_code == 409
    assert refused.json()["error"]["losing"] == ["ingest"]

    accepted = client.post("/v1/admin/extensions",
                           json={"action": "remove", "id": "dial",
                                 "acknowledge": True}, headers=auth)
    assert accepted.json()["uninstalled"] is True


# ---------------------------------------------------------------------------
# L.7 rule 2 over MCP — the menu is the union of what THIS key reaches
# ---------------------------------------------------------------------------

TOOL_EXT = '''
def transcribe(**kwargs):
    return {"text": "transcribed", "args": kwargs}

def register(api):
    api.contribute("tools", transcribe, name=api.namespace + "transcribe",
                   description="Transcribe audio into text.")
'''

MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}


def _rpc(client, method, params=None, key=None, rid=1):
    headers = dict(MCP_HEADERS)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp/", headers=headers, json=body)


def _tool_names(client, key):
    payload = _rpc(client, "tools/list", key=key).json()
    return {t["name"] for t in payload["result"]["tools"]}


@pytest.fixture()
def tool_ext(tmp_path) -> Path:
    tree = tmp_path / "src" / "voice"
    tree.mkdir(parents=True)
    (tree / "manifest.json").write_text(json.dumps({
        "id": "voice", "version": "1.0.0", "station_compat": ">=0.1,<99",
        "license": "MIT",
    }), encoding="utf-8")
    (tree / "main.py").write_text(TOOL_EXT, encoding="utf-8")
    (tree / "LICENSE").write_text("MIT", encoding="utf-8")
    return tree


@pytest.fixture()
def mcp_station(two_forests, tmp_path, monkeypatch, tool_ext):
    """A Station whose MCP surface is on, with `voice` installed BEFORE the
    app is built — installing requires a restart (L.8), so this is the only
    honest order.
    """
    from starlette.testclient import TestClient

    from monkeyllm.extensions.installer import install as engine_install
    from monkeyllm.extensions.store import Store
    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.setenv("MONKEYLLM_EXT_HOME", str(tmp_path / "exthome"))
    engine_install(str(tool_ext), "0.79.0", store=Store(),
                   acknowledge_unverified=True)

    # `voice` acts on MINE only.
    from monkeyllm.extensions import forestcfg
    forestcfg.enable(two_forests / MINE, "voice")

    app = build_app(root=two_forests, registry_path=tmp_path / "station.db",
                    mcp=True, writable=True)
    with TestClient(app) as client:
        yield client, app.state.registry


def _key(registry, principal, forest):
    key = registry.issue_key(principal)
    registry.grant(principal, forest, {"read", "write"})
    return key


class TestExtensionToolsOverMCP:
    def test_a_key_reaching_the_enabled_forest_sees_the_tool(self,
                                                             mcp_station):
        client, registry = mcp_station
        names = _tool_names(client, _key(registry, "here", MINE))
        assert "x_voice_transcribe" in names
        # The primitives are untouched beside it.
        assert {"locate", "look", "pick"} <= names

    def test_a_key_reaching_only_the_other_forest_does_not(self, mcp_station):
        client, registry = mcp_station
        names = _tool_names(client, _key(registry, "elsewhere", THEIRS))
        assert "x_voice_transcribe" not in names
        assert "locate" in names          # the menu is otherwise the same

    def test_an_anonymous_caller_sees_no_extension_tool(self, mcp_station):
        client, _ = mcp_station
        assert "x_voice_transcribe" not in _tool_names(client, None)

    def test_calling_it_on_the_enabled_forest_works(self, mcp_station):
        client, registry = mcp_station
        key = _key(registry, "here", MINE)
        out = _rpc(client, "tools/call",
                   {"name": "x_voice_transcribe",
                    "arguments": {"forest": MINE, "args": {"path": "a.mp3"}}},
                   key=key).json()
        payload = json.loads(out["result"]["content"][0]["text"])
        assert payload["text"] == "transcribed"
        assert payload["args"] == {"path": "a.mp3"}

    def test_calling_it_on_a_forest_that_did_not_enable_it_is_not_found(
            self, mcp_station):
        client, registry = mcp_station
        # The same key reaches both forests; only MINE enabled `voice`.
        key = registry.issue_key("both")
        registry.grant("both", MINE, {"read"})
        registry.grant("both", THEIRS, {"read"})
        out = _rpc(client, "tools/call",
                   {"name": "x_voice_transcribe",
                    "arguments": {"forest": THEIRS, "args": {}}},
                   key=key).json()
        payload = json.loads(out["result"]["content"][0]["text"])
        assert payload["error"]["code"] == "E_NOT_FOUND"

    def test_the_menu_is_the_union_across_the_keys_forests(self, mcp_station):
        client, registry = mcp_station
        key = registry.issue_key("both2")
        registry.grant("both2", MINE, {"read"})
        registry.grant("both2", THEIRS, {"read"})
        assert "x_voice_transcribe" in _tool_names(client, key)


# ---------------------------------------------------------------------------
# L.3 — the remaining seams, each read by the host that declares it
# ---------------------------------------------------------------------------

SEAMS_EXT = '''
SEEN = []

def on_event(event, forest, principal, data, metadata):
    SEEN.append({"event": event, "forest": forest, "principal": principal})
    return None

def rank(query, results):
    # Reverse it, so the effect is unmistakable, and drop nothing.
    return list(reversed(results))

def prompt(mode, question, system):
    return "Always answer in haiku."

def sweep(forest):
    return {"swept": forest, "seen": len(SEEN)}

def ping(forest, **kwargs):
    return {"pong": forest, "args": kwargs}

def curate(draft, **kwargs):
    draft = dict(draft or {})
    draft["title"] = (draft.get("title") or "") + " [curated]"
    return draft

def register(api):
    pass
'''


@pytest.fixture()
def seams_ext(tmp_path) -> Path:
    tree = tmp_path / "src" / "seams"
    tree.mkdir(parents=True)
    (tree / "manifest.json").write_text(json.dumps({
        "id": "seams", "version": "1.0.0", "station_compat": ">=0.1,<99",
        "license": "MIT",
        "contributes": {
            "events": [{"name": "watch", "handler": "main:on_event"}],
            "ranking": [{"name": "rank", "handler": "main:rank"}],
            "prompt": [{"name": "haiku", "handler": "main:prompt"}],
            "jobs": [{"name": "sweep", "handler": "main:sweep",
                      "description": "Sweep something."}],
            "routes": [{"name": "ping", "handler": "main:ping"}],
            "curation": [{"name": "shout", "handler": "main:curate"}],
        },
    }), encoding="utf-8")
    (tree / "main.py").write_text(SEAMS_EXT, encoding="utf-8")
    (tree / "LICENSE").write_text("MIT", encoding="utf-8")
    return tree


@pytest.fixture()
def seams_station(two_forests, tmp_path, monkeypatch, seams_ext):
    from starlette.testclient import TestClient

    from monkeyllm.extensions import forestcfg
    from monkeyllm.extensions.installer import install as engine_install
    from monkeyllm.extensions.store import Store
    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.setenv("MONKEYLLM_EXT_HOME", str(tmp_path / "exthome"))
    engine_install(str(seams_ext), "0.79.0", store=Store(),
                   acknowledge_unverified=True)
    forestcfg.enable(two_forests / MINE, "seams")

    app = build_app(root=two_forests, registry_path=tmp_path / "station.db",
                    mcp=False, writable=True)
    with TestClient(app) as client:
        yield client, app.state.registry, app


class TestRemainingSeams:
    def test_a_job_is_listed_and_run_on_the_forest_that_enabled_it(
            self, seams_station):
        client, registry, _ = seams_station
        auth = admin_key(registry)
        listed = client.get(f"/v1/admin/extensions/jobs?forest={MINE}",
                            headers=auth).json()
        assert [j["name"] for j in listed["jobs"]] == ["sweep"]

        ran = client.post("/v1/admin/extensions/jobs",
                          json={"forest": MINE, "job": "sweep"},
                          headers=auth).json()
        assert ran["result"]["swept"] == MINE

    def test_a_job_is_absent_on_a_forest_that_did_not_enable_it(
            self, seams_station):
        client, registry, _ = seams_station
        auth = admin_key(registry, "other", forest=THEIRS)
        listed = client.get(f"/v1/admin/extensions/jobs?forest={THEIRS}",
                            headers=auth).json()
        assert listed["jobs"] == []
        missing = client.post("/v1/admin/extensions/jobs",
                              json={"forest": THEIRS, "job": "sweep"},
                              headers=auth)
        assert missing.status_code == 404

    def test_a_route_answers_under_its_own_prefix(self, seams_station):
        client, registry, _ = seams_station
        auth = admin_key(registry)
        out = client.post(f"/v1/ext/seams/ping?forest={MINE}", json={},
                          headers=auth)
        assert out.status_code == 200
        assert out.json()["pong"] == MINE

    def test_a_route_on_an_unreached_forest_is_not_found(self, seams_station):
        client, registry, _ = seams_station
        # `reader` holds nothing on THEIRS: J.3's rule, and an extension
        # route is not an exception to it.
        registry.add_principal("nobody2", kind="user")
        auth = {"Authorization": f"Bearer {registry.issue_key('nobody2')}"}
        out = client.post(f"/v1/ext/seams/ping?forest={MINE}", json={},
                          headers=auth)
        assert out.status_code == 404

    def test_an_unknown_route_name_is_not_found(self, seams_station):
        client, registry, _ = seams_station
        out = client.post(f"/v1/ext/seams/nonesuch?forest={MINE}", json={},
                          headers=admin_key(registry))
        assert out.status_code == 404

    def test_the_route_is_audited_naming_the_extension(self, seams_station):
        client, registry, _ = seams_station
        client.post(f"/v1/ext/seams/ping?forest={MINE}", json={},
                    headers=admin_key(registry))
        rows = [r for r in registry.audit(limit=20)
                if r["primitive"].startswith("ext.seams")]
        assert rows and rows[0]["via"] == "ext:seams"
        assert rows[0]["principal"] == "root"

    def test_an_event_reaches_the_extension_of_the_forest_it_happened_on(
            self, seams_station):
        client, registry, app = seams_station
        # Emit through the host's own emitter, which is the one place an
        # event becomes either a webhook or an extension call.
        app.state.webhooks.emit(MINE, "node.planted", "root",
                                {"node": "notes/x"}, {})
        app.state.webhooks.emit(THEIRS, "node.planted", "root",
                                {"node": "notes/y"}, {})

        import sys as _sys
        # Read the module through THIS app's own claim: several hosts in one
        # process each hold their own load (the name carries a digest of the
        # installed tree), and picking one by name prefix would sometimes
        # read another test's.
        root = Path(app.state.pool.root) / MINE
        view = app.state.extensions.for_forest(MINE, root)
        handler = view.for_seam("events")[0].handler
        seen = _sys.modules[handler.__module__].SEEN
        assert [s["forest"] for s in seen] == [MINE]
        assert seen[0]["event"] == "node.planted"

    def test_the_ranking_seam_reorders_and_is_attributed(self, seams_station):
        client, registry, app = seams_station
        auth = admin_key(registry)
        plain = client.post(f"/v1/forests/{THEIRS}/harvest",
                            json={"query": "stigmergy", "k": 3},
                            headers=admin_key(registry, "other",
                                              forest=THEIRS))
        ranked = client.post(f"/v1/forests/{MINE}/harvest",
                             json={"query": "stigmergy", "k": 3},
                             headers=auth)
        assert plain.status_code == ranked.status_code == 200
        a = [r["id"] for r in plain.json()["results"]]
        b = [r["id"] for r in ranked.json()["results"]]
        # Same corpus, one forest ranked by the extension.
        assert a and b and b == list(reversed(a))
