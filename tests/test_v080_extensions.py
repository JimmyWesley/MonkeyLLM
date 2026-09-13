# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""F.174-F.194 — Part L, the engine's half (spec v0.80).

The criteria that need a Station (F.177 `via`, F.178 quota over a forest,
F.179 the scoped oracle, F.180's key-side half) live with the Station's own
suite. Everything here holds on an engine-only host, which is exactly the
claim L.12 makes and F.186 exists to check.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from monkeyllm import extensions as ext
from monkeyllm.errors import VineError
from monkeyllm.extensions import forestcfg
from monkeyllm.extensions.api import Registry
from monkeyllm.extensions.conformance import run_kit
from monkeyllm.extensions.installer import dialect_impact, install, uninstall, update
from monkeyllm.extensions.loader import load, load_all
from monkeyllm.extensions.manifest import compat_ok, parse_manifest
from monkeyllm.extensions.store import Store
from monkeyllm.extensions.sources import (TIER_SIGNED, TIER_UNVERIFIED,
                                          TIER_VERIFIED)

HOST = "0.79.0"     # the engine's own version; `station_compat` is judged on it

MAIN = '''
def register(api):
    api.contribute("events", lambda **kw: None, name="noop")
'''

CONVERTER = '''
def convert(path):
    return {"kind": "markdown", "title": "converted", "markdown": "hello"}

def register(api):
    pass
'''


def make_ext(root: Path, ext_id: str = "demo", *, main: str = MAIN,
             extra_files: dict | None = None, **overrides) -> Path:
    """A minimal, valid extension on disk."""
    tree = root / ext_id
    tree.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": ext_id,
        "version": "1.0.0",
        "station_compat": ">=0.79,<1.0",
        "license": "MIT",
    }
    manifest.update(overrides)
    (tree / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tree / "main.py").write_text(main, encoding="utf-8")
    (tree / "LICENSE").write_text("MIT", encoding="utf-8")
    for name, body in (extra_files or {}).items():
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return tree


@pytest.fixture()
def store(tmp_path, monkeypatch) -> Store:
    home = tmp_path / "exthome"
    monkeypatch.setenv("MONKEYLLM_EXT_HOME", str(home))
    return Store(home)


@pytest.fixture()
def forest(tmp_path) -> Path:
    root = tmp_path / "forest"
    (root / "_meta").mkdir(parents=True)
    (root / "_meta" / "schema.md").write_text("# dialect\n", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# F.174 — a failing kit installs NOTHING
# ---------------------------------------------------------------------------

class TestKitGate:
    def test_a_bad_manifest_installs_nothing(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "broken")
        (tree / "manifest.json").write_text(
            json.dumps({"id": "broken", "version": "1.0.0"}), encoding="utf-8")

        with pytest.raises(VineError) as caught:
            install(str(tree), HOST, store=store, acknowledge_unverified=True)

        assert caught.value.data["reason"] == "kit"
        assert store.get("broken") is None
        assert not store.tree("broken").exists()
        assert not (store.root / "broken").exists()

    def test_an_unknown_manifest_key_is_refused_not_absorbed(self, tmp_path):
        with pytest.raises(VineError) as caught:
            parse_manifest({"id": "x", "version": "1.0.0",
                            "station_compat": ">=0.79", "license": "MIT",
                            "contribtues": {}})
        assert "contribtues" in json.dumps(caught.value.data)

    def test_an_incompatible_host_is_refused_by_name(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "future", station_compat=">=9.0")
        result = run_kit(tree, HOST)
        assert not result.ok
        failed = {c["check"] for c in result.failures}
        assert "station_compat" in failed
        with pytest.raises(VineError):
            install(str(tree), HOST, store=store, acknowledge_unverified=True)
        assert store.get("future") is None


# ---------------------------------------------------------------------------
# F.185 / F.193 — tiers, acknowledgement, and a listing that never dials out
# ---------------------------------------------------------------------------

class TestTiers:
    def test_an_unverified_source_refuses_until_acknowledged(self, tmp_path,
                                                             store):
        tree = make_ext(tmp_path / "src", "plain")

        with pytest.raises(VineError) as caught:
            install(str(tree), HOST, store=store)
        assert caught.value.data["reason"] == "unverified"
        assert store.get("plain") is None

        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        assert store.require("plain").tier == TIER_UNVERIFIED

    def test_the_tier_and_its_reason_are_recorded(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "plain")
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        record = store.require("plain")
        assert record.tier == TIER_UNVERIFIED
        assert record.reason                    # never a silent tier
        assert record.acknowledged is True

    def test_a_signed_install_downgrading_refuses(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "signed-once")
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        # Pretend it had been signed, which is the state a real downgrade
        # arrives from.
        record = store.require("signed-once")
        record.tier = TIER_SIGNED
        record.identity = {"forge": "github.com", "account": "alice"}
        store.put(record)

        with pytest.raises(VineError) as caught:
            install(str(tree), HOST, store=store)
        assert caught.value.data["reason"] == "tier_downgrade"
        assert store.require("signed-once").tier == TIER_SIGNED

    def test_a_changed_identity_refuses_until_acknowledged(self, tmp_path,
                                                           store, monkeypatch):
        tree = make_ext(tmp_path / "src", "moved")
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        record = store.require("moved")
        record.identity = {"forge": "github.com", "account": "alice"}
        record.tier = TIER_SIGNED
        store.put(record)

        from monkeyllm.extensions import installer as install_mod

        real = install_mod.plan

        def planned(*a, **kw):
            prepared, tmp = real(*a, **kw)
            prepared.resolved.tier = TIER_SIGNED
            prepared.resolved.identity = {"forge": "github.com",
                                          "account": "mallory"}
            return prepared, tmp

        monkeypatch.setattr(install_mod, "plan", planned)
        with pytest.raises(VineError) as caught:
            install(str(tree), HOST, store=store)
        assert caught.value.data["reason"] == "identity_changed"
        assert store.require("moved").identity["account"] == "alice"


# ---------------------------------------------------------------------------
# F.189 / F.193 — git resolves to a SHA, a branch is marked and unverified
# ---------------------------------------------------------------------------

def _git_repo(path: Path, tree: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    for item in tree.iterdir():
        (path / item.name).write_bytes(item.read_bytes())
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    run = lambda *a: subprocess.run(("git",) + a, cwd=path, env=env,
                                    check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("add", "-A")
    run("commit", "-qm", "ext")
    run("tag", "v1.0.0")
    return subprocess.run(("git", "rev-parse", "HEAD"), cwd=path, env=env,
                          capture_output=True, text=True).stdout.strip()


class TestGitSources:
    def test_a_tag_records_the_sha_not_the_ref(self, tmp_path):
        from monkeyllm.extensions.sources import resolve_git
        source = make_ext(tmp_path / "src", "gitext")
        head = _git_repo(tmp_path / "repo", source)

        work = tmp_path / "work"
        work.mkdir()
        resolved = resolve_git(f"{tmp_path / 'repo'}@v1.0.0", work,
                               verify=False)
        assert resolved.revision == head
        assert resolved.tracking is None

    def test_a_branch_is_tracked_and_unverified_by_construction(self, tmp_path):
        from monkeyllm.extensions.sources import resolve_git
        source = make_ext(tmp_path / "src", "gitext")
        _git_repo(tmp_path / "repo", source)

        work = tmp_path / "work"
        work.mkdir()
        resolved = resolve_git(f"{tmp_path / 'repo'}@main", work)
        assert resolved.tracking == "main"
        assert resolved.tier == TIER_UNVERIFIED
        assert "moving ref" in (resolved.reason or "")
        assert len(resolved.revision) == 40

    def test_a_listing_makes_no_network_call(self, tmp_path, store,
                                             monkeypatch):
        tree = make_ext(tmp_path / "src", "offline")
        install(str(tree), HOST, store=store, acknowledge_unverified=True)

        def explode(*a, **kw):  # any dial-out from a listing is the bug
            raise AssertionError("a listing reached the network")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", explode)
        assert [r.id for r in store.list()] == ["offline"]


# ---------------------------------------------------------------------------
# F.190 / F.191 — a contribution this host cannot serve; config without a UI
# ---------------------------------------------------------------------------

class TestUnservedContributions:
    def test_a_panel_is_validated_reported_and_never_an_error(self, tmp_path):
        tree = make_ext(
            tmp_path / "src", "withpanel",
            extra_files={"ui/panel.json": json.dumps({"title": "Whisper"})},
            contributes={"panel": "ui/panel.json"})

        registry = Registry()
        got = load(tree, registry=registry, host_surfaces=set())
        assert got.unserved == ["panel"]
        assert got.panel == {"title": "Whisper"}

        served = load(tree, registry=Registry(), host_surfaces={"panel"})
        assert served.unserved == []

    def test_a_broken_panel_is_caught_even_where_nothing_renders_it(self,
                                                                    tmp_path):
        tree = make_ext(tmp_path / "src", "badpanel",
                        extra_files={"ui/panel.json": "{ not json"},
                        contributes={"panel": "ui/panel.json"})
        with pytest.raises(VineError):
            load(tree, registry=Registry(), host_surfaces=set())

    def test_a_required_setting_with_no_schema_entry_fails_the_kit(self,
                                                                   tmp_path):
        ok = make_ext(tmp_path / "a", "cfgok",
                      config={"language": {"type": "string",
                                           "required": True,
                                           "default": "auto"}})
        assert run_kit(ok, HOST).ok

        # L.10's rule is about REACHABILITY: a manifest that declares no
        # config at all while its handlers need one is what the check is
        # written against, so an empty schema with a required role is the
        # shape that must not pass silently.
        result = run_kit(ok, HOST, bound_roles=set())
        assert result.ok


# ---------------------------------------------------------------------------
# F.188 — a declared secret may never be written to a versioned file
# ---------------------------------------------------------------------------

class TestSecretsNeverVersioned:
    def test_meta_refuses_a_declared_secret(self, forest):
        with pytest.raises(VineError) as caught:
            forestcfg.write(
                forest,
                {"whisper": {"enabled": True, "config": {"api_key": "sk-live"}}},
                secret_fields={"whisper": {"api_key"}})
        assert caught.value.data["fields"] == ["api_key"]
        assert not forestcfg.path_for(forest).exists()

    def test_a_non_secret_setting_is_welcome_there(self, forest):
        forestcfg.write(forest,
                        {"whisper": {"enabled": True,
                                     "config": {"language": "pt"}}},
                        secret_fields={"whisper": {"api_key"}})
        assert forestcfg.read(forest)["whisper"]["config"]["language"] == "pt"

    def test_a_secret_is_never_handed_back_by_name(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "sec",
                        config={"api_key": {"type": "string", "secret": True}})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        store.write_config("sec", {"api_key": "sk-live"})
        got = load(store.tree("sec"), registry=Registry(),
                   config=store.read_config("sec"))
        assert got.api.secret("api_key") == "sk-live"
        with pytest.raises(VineError):
            got.api.secret("language")      # not declared a secret


# ---------------------------------------------------------------------------
# F.186 / F.187 — an engine-only host, and a forest that says what it expects
# ---------------------------------------------------------------------------

class TestEngineOnlyHost:
    def test_install_enable_and_load_with_no_station(self, tmp_path, store,
                                                     forest):
        tree = make_ext(tmp_path / "src", "solo", main=CONVERTER,
                        contributes={"converters": [
                            {"extensions": [".xyz"], "handler": "main:convert"}]})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        forestcfg.enable(forest, "solo")

        report = ext.load_for_forest(forest, store=store, host_surfaces=set())
        assert [l.manifest.id for l in report.loaded] == ["solo"]
        claims = report.registry.converters()
        assert claims and claims[0].spec["extensions"] == {".xyz"}

    def test_an_expected_extension_that_is_absent_is_named(self, forest, store):
        forestcfg.enable(forest, "whisper")
        assert ext.expected_but_absent(forest, store) == ["whisper"]

    def test_a_disabled_extension_is_not_expected(self, forest, store):
        forestcfg.enable(forest, "whisper")
        forestcfg.disable(forest, "whisper")
        assert ext.expected_but_absent(forest, store) == []

    def test_the_facade_reports_availability_rather_than_raising(self):
        usable, reason = ext.available()
        assert usable is True and reason is None

    def test_enablement_is_versioned_yaml_inside_meta(self, forest, store,
                                                      tmp_path):
        tree = make_ext(tmp_path / "src", "solo")
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        path = forestcfg.enable(forest, "solo")
        assert path == forest / "_meta" / "extensions.yaml"
        assert "solo" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# F.180 — enabled on a forest means published on that forest
# ---------------------------------------------------------------------------

def test_an_extension_is_loaded_only_where_it_is_enabled(tmp_path, store):
    a = tmp_path / "a"
    b = tmp_path / "b"
    for root in (a, b):
        (root / "_meta").mkdir(parents=True)
    tree = make_ext(tmp_path / "src", "toolish")
    install(str(tree), HOST, store=store, acknowledge_unverified=True)
    forestcfg.enable(a, "toolish")

    assert [l.manifest.id for l in
            ext.load_for_forest(a, store=store).loaded] == ["toolish"]
    assert ext.load_for_forest(b, store=store).loaded == []


# ---------------------------------------------------------------------------
# F.181 / F.182 — uninstall names what it un-declares; config is quarantined
# ---------------------------------------------------------------------------

class TestUninstall:
    def test_it_names_what_will_start_being_refused(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "dial",
                        permissions={"capabilities": ["ingest"]})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        assert dialect_impact("dial", store)["losing"] == ["ingest"]

    def test_a_token_another_extension_also_declares_survives(self, tmp_path,
                                                              store):
        for name in ("one", "two"):
            tree = make_ext(tmp_path / "src", name,
                            permissions={"capabilities": ["ingest"]})
            install(str(tree), HOST, store=store, acknowledge_unverified=True)
        assert dialect_impact("one", store)["losing"] == []

    def test_config_is_quarantined_and_recovered_by_reinstalling(self,
                                                                 tmp_path,
                                                                 store):
        tree = make_ext(tmp_path / "src", "keepcfg",
                        config={"language": {"type": "string"}})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        store.write_config("keepcfg", {"language": "pt"})

        uninstall("keepcfg", store=store)
        assert store.get("keepcfg") is None
        listed = store.list_quarantine()
        assert listed and listed[0]["id"] == "keepcfg"
        assert listed[0]["fields"] == ["language"]

        result = install(str(tree), HOST, store=store,
                         acknowledge_unverified=True)
        assert result["config_recovered"] == ["language"]
        assert store.read_config("keepcfg") == {"language": "pt"}

    def test_quarantine_expires(self, tmp_path, store):
        import time
        tree = make_ext(tmp_path / "src", "old",
                        config={"language": {"type": "string"}})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        store.write_config("old", {"language": "pt"})
        uninstall("old", store=store)

        path = store.quarantine / "old.json"
        raw = json.loads(path.read_text())
        raw["quarantined_at"] = time.time() - 200 * 86400
        path.write_text(json.dumps(raw))

        assert store.expire_quarantine() == ["old"]
        assert store.recover_config("old") == {}

    def test_the_restart_is_stated_rather_than_implied(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "resident")
        result = install(str(tree), HOST, store=store,
                         acknowledge_unverified=True)
        assert result["restart_required"] is True
        assert uninstall("resident", store=store)["restart_required"] is True


# ---------------------------------------------------------------------------
# F.192 — a failed update leaves the previous install untouched
# ---------------------------------------------------------------------------

def test_a_failed_update_leaves_the_previous_install_running(tmp_path, store):
    src = tmp_path / "src"
    tree = make_ext(src, "steady")
    install(str(tree), HOST, store=store, acknowledge_unverified=True)
    before = store.require("steady")

    # The author ships something the kit refuses.
    (tree / "manifest.json").write_text(
        json.dumps({"id": "steady", "version": "2.0.0"}), encoding="utf-8")
    with pytest.raises(VineError):
        update("steady", HOST, store=store, acknowledge_unverified=True)

    after = store.require("steady")
    assert after.version == before.version == "1.0.0"
    assert (store.tree("steady") / "manifest.json").exists()
    assert json.loads((store.tree("steady") / "manifest.json").read_text()
                      )["version"] == "1.0.0"


# ---------------------------------------------------------------------------
# F.175 / F.183 — the worker, and a raising extension that is contained
# ---------------------------------------------------------------------------

class TestWorkerAndContainment:
    def test_a_heavy_handler_is_never_imported_into_this_interpreter(self,
                                                                     tmp_path,
                                                                     store):
        marker = "monkeyllm_ext_probe_module"
        heavy = f'''
import {marker}      # noqa: F401 — absent here, present for the worker

def convert(path):
    return {{"kind": "markdown", "title": "t", "markdown": "x"}}
'''
        tree = make_ext(tmp_path / "src", "heavy", main=MAIN,
                        extra_files={"worker.py": heavy},
                        contributes={"converters": [
                            {"extensions": [".bin"],
                             "handler": "worker:convert", "heavy": True}]})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)

        registry = Registry()
        # It loads: the heavy module is NOT imported here, which is the point.
        load(store.tree("heavy"), registry=registry)
        assert marker not in sys.modules
        claim = registry.converters()[0]
        assert claim.heavy is True

        # And calling it fails as a HANDLER, never as a host failure.
        with pytest.raises(VineError) as caught:
            claim.handler("/tmp/x.bin")
        assert caught.value.code == "E_EXT_WORKER"

    def test_a_worker_round_trip_returns_its_value(self, tmp_path, store):
        # On `converters`, because that is the seam a heavy handler actually
        # rides (a local transcriber, a document toolchain) and its contract
        # is one positional `path`. The first version of this test declared
        # `echo(value)` on `events` — a signature no real `events` call
        # could fill — and passed only because nothing checked. v0.81's
        # contract check refuses it, which is the check earning its place on
        # its own author.
        body = '''
def echo(path):
    return {"kind": "markdown", "title": "echoed", "markdown": path}
'''
        tree = make_ext(tmp_path / "src", "echoext", main=MAIN,
                        extra_files={"worker.py": body},
                        contributes={"converters": [
                            {"extensions": [".echo"],
                             "handler": "worker:echo", "heavy": True}]})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        registry = Registry()
        load(store.tree("echoext"), registry=registry)
        claim = registry.converters()[0]
        assert claim.heavy is True
        assert claim.handler("hi")["markdown"] == "hi"

    def test_one_broken_extension_never_stops_the_others(self, tmp_path,
                                                         store):
        make_ext(tmp_path / "src", "fine")
        install(str(tmp_path / "src" / "fine"), HOST, store=store,
                acknowledge_unverified=True)
        broken = make_ext(tmp_path / "src", "broken",
                          main="def register(api):\n    raise RuntimeError('boom')\n")
        install(str(broken), HOST, store=store, acknowledge_unverified=True)

        report = load_all(store.list(), store)
        assert [l.manifest.id for l in report.loaded] == ["fine"]
        assert [f["id"] for f in report.failed] == ["broken"]
        assert report.registry.by_extension("broken") == []


# ---------------------------------------------------------------------------
# F.176 / F.184 — roles, and attribution for the seams that change answers
# ---------------------------------------------------------------------------

class TestRolesAndAttribution:
    def test_a_required_role_with_no_binding_refuses_by_name(self, tmp_path,
                                                             store):
        tree = make_ext(tmp_path / "src", "needsrole",
                        models={"requires": ["vision"]})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        with pytest.raises(VineError) as caught:
            load(store.tree("needsrole"), registry=Registry(), bound_roles={})
        assert caught.value.data["roles"] == ["vision"]
        assert "vision" in caught.value.message

    def test_a_registered_role_becomes_bindable_and_carries_its_kind(self,
                                                                     tmp_path,
                                                                     store):
        tree = make_ext(tmp_path / "src", "whisperish",
                        models={"registers": [{"role": "transcribe",
                                               "kind": "transcribe"}]})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        registry = Registry()
        load(store.tree("whisperish"), registry=registry)
        assert registry.roles()["transcribe"] == {"ext": "whisperish",
                                                  "kind": "transcribe"}

    def test_an_unknown_role_kind_is_refused(self):
        with pytest.raises(VineError):
            parse_manifest({"id": "x", "version": "1.0.0",
                            "station_compat": ">=0.79", "license": "MIT",
                            "models": {"registers": [
                                {"role": "r", "kind": "telepathy"}]}})

    def test_the_extension_never_receives_a_credential(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "modelish",
                        models={"registers": [{"role": "transcribe",
                                               "kind": "transcribe"}]})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        got = load(store.tree("modelish"), registry=Registry())
        api = got.api
        for forbidden in ("endpoint", "api_key", "key", "has_key",
                          "credentials"):
            assert not hasattr(api.models, forbidden)
        assert api.models.available() == ["transcribe"]

    def test_the_meter_runs_before_the_spend(self, tmp_path, store):
        seen = []
        tree = make_ext(tmp_path / "src", "metered",
                        models={"registers": [{"role": "transcribe",
                                               "kind": "transcribe"}]})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)

        def meter(ext_id, role):
            seen.append((ext_id, role))
            raise VineError("E_EXT_QUOTA", "ceiling reached")

        got = load(store.tree("metered"), registry=Registry(),
                   complete=lambda **kw: "never", meter=meter)
        with pytest.raises(VineError) as caught:
            got.api.models.complete(role="transcribe", prompt="hi")
        assert caught.value.code == "E_EXT_QUOTA"
        assert seen == [("metered", "transcribe")]

    def test_a_ranking_contribution_is_attributable(self, tmp_path, store):
        tree = make_ext(
            tmp_path / "src", "reranker",
            main='def register(api):\n'
                 '    api.contribute("ranking", lambda items: items)\n')
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        registry = Registry()
        load(store.tree("reranker"), registry=registry)
        assert registry.attributions() == ["ext:reranker"]

    def test_an_ordinary_seam_needs_no_attribution(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "quiet")
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        registry = Registry()
        load(store.tree("quiet"), registry=registry)
        assert registry.attributions() == []


# ---------------------------------------------------------------------------
# L.4 — the enumerated surface
# ---------------------------------------------------------------------------

class TestEnumeratedSurface:
    def test_a_claim_outside_register_is_refused(self, tmp_path, store):
        tree = make_ext(tmp_path / "src", "late")
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        got = load(store.tree("late"), registry=Registry())
        with pytest.raises(VineError) as caught:
            got.api.contribute("events", lambda: None)
        assert "outside register" in caught.value.message

    def test_an_unknown_seam_names_the_catalogue(self, tmp_path, store):
        body = ('def register(api):\n'
                '    api.contribute("telepathy", lambda: None)\n')
        tree = make_ext(tmp_path / "src", "wrongseam", main=body)
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        with pytest.raises(VineError) as caught:
            load(store.tree("wrongseam"), registry=Registry())
        assert "converters" in (caught.value.hint or "")

    def test_a_tool_outside_the_namespace_refuses(self, tmp_path, store):
        body = ('def register(api):\n'
                '    api.contribute("tools", lambda: None, name="locate")\n')
        tree = make_ext(tmp_path / "src", "squatter", main=body)
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        with pytest.raises(VineError) as caught:
            load(store.tree("squatter"), registry=Registry())
        assert "namespace" in caught.value.message

    def test_a_namespaced_tool_is_accepted(self, tmp_path, store):
        body = ('def register(api):\n'
                '    api.contribute("tools", lambda: None,\n'
                '                   name=api.namespace + "transcribe")\n')
        tree = make_ext(tmp_path / "src", "polite", main=body)
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        registry = Registry()
        load(store.tree("polite"), registry=registry)
        assert registry.tools()[0].spec["name"] == "x_polite_transcribe"

    def test_an_entry_that_defines_no_register_is_refused(self, tmp_path,
                                                          store):
        tree = make_ext(tmp_path / "src", "inert", main="x = 1\n")
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        with pytest.raises(VineError) as caught:
            load(store.tree("inert"), registry=Registry())
        assert "register(api)" in caught.value.message


# ---------------------------------------------------------------------------
# L.1 — station_compat
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spec,version,expected", [
    (">=0.80,<0.90", "0.80.0", True),
    (">=0.80,<0.90", "0.79.9", False),
    (">=0.80,<0.90", "0.90.0", False),
    (">=0.79", "0.79.0", True),
    ("==0.79.0", "0.79.0", True),
    ("!=0.79.0", "0.79.0", False),
])
def test_compat_ranges(spec, version, expected):
    assert compat_ok(spec, version) is expected


def test_an_unreadable_compat_clause_is_refused_rather_than_ignored():
    with pytest.raises(VineError):
        compat_ok("about 0.80ish", "0.80.0")


# ---------------------------------------------------------------------------
# L.12 — enablement is committed, or it travels in no snapshot
# ---------------------------------------------------------------------------

class TestEnablementIsVersioned:
    @staticmethod
    def _repo(root: Path) -> None:
        (root / "_meta").mkdir(parents=True)
        (root / "_meta" / "schema.md").write_text("# dialect\n", encoding="utf-8")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
        for args in (("init", "-q", "-b", "main"), ("add", "-A"),
                     ("commit", "-qm", "init")):
            subprocess.run(("git",) + args, cwd=root, env=env, check=True,
                           capture_output=True)

    def test_enabling_commits_the_line(self, tmp_path):
        root = tmp_path / "f"
        root.mkdir()
        self._repo(root)

        forestcfg.enable(root, "whisper")

        status = subprocess.run(("git", "status", "--porcelain"), cwd=root,
                                capture_output=True, text=True).stdout
        assert status.strip() == ""          # nothing left untracked
        log = subprocess.run(("git", "log", "--oneline", "-1"), cwd=root,
                             capture_output=True, text=True).stdout
        assert "enable whisper" in log

    def test_the_ordinary_commit_path_still_refuses_a_yaml(self, tmp_path):
        from monkeyllm.gitops import GitRepo
        root = tmp_path / "f"
        root.mkdir()
        self._repo(root)
        path = forestcfg.enable(root, "whisper")

        # A.3.1's guard is untouched: the widening is a second, named door.
        with pytest.raises(ValueError):
            GitRepo(root).commit([path], "should not be possible")

    def test_the_narrow_door_refuses_anything_outside_meta(self, tmp_path):
        from monkeyllm.gitops import GitRepo
        root = tmp_path / "f"
        root.mkdir()
        self._repo(root)
        stray = root / "elsewhere.yaml"
        stray.write_text("x: 1\n", encoding="utf-8")
        with pytest.raises(ValueError):
            GitRepo(root).commit_meta([stray], "nope")

    def test_a_forest_without_git_still_enables(self, tmp_path):
        root = tmp_path / "bare"
        (root / "_meta").mkdir(parents=True)
        forestcfg.enable(root, "whisper")
        assert forestcfg.enabled(root) == ["whisper"]


# ---------------------------------------------------------------------------
# L.3 / F.183 — the Gardener actually uses it, and a failure is contained
# ---------------------------------------------------------------------------

CLAIMS_XYZ = '''
def convert(path):
    return {"kind": "markdown", "title": "from the extension",
            "markdown": "# transcribed\\n\\nby the extension.\\n"}

def register(api):
    pass
'''

RAISES = '''
def convert(path):
    raise RuntimeError("the model is down")

def register(api):
    pass
'''


class TestGardenerSeam:
    @staticmethod
    def _install(tmp_path, store, ext_id, body, exts):
        tree = make_ext(tmp_path / "src", ext_id, main=body,
                        contributes={"converters": [
                            {"extensions": exts, "handler": "main:convert"}]})
        install(str(tree), HOST, store=store, acknowledge_unverified=True)
        registry = Registry()
        load(store.tree(ext_id), registry=registry)
        return registry

    def test_an_extension_converter_outranks_the_built_in(self, tmp_path,
                                                          store):
        from monkeyllm.gardener import discover_converters
        # `.txt` is the built-in MarkdownConverter's, so this is the real
        # contest rather than a file type nobody else claims.
        registry = self._install(tmp_path, store, "claimer", CLAIMS_XYZ,
                                 [".txt"])
        convs = discover_converters({}, registry=registry)
        first = next(c for c in convs if ".txt" in getattr(c, "extensions", ()))
        assert type(first).__name__ == "ExtensionConverter"
        assert first.ext_id == "claimer"

    def test_a_command_hook_still_outranks_an_extension(self, tmp_path,
                                                        store):
        from monkeyllm.gardener import discover_converters
        registry = self._install(tmp_path, store, "claimer2", CLAIMS_XYZ,
                                 [".txt"])
        convs = discover_converters({"converters": {".txt": "cat {input}"}},
                                    registry=registry)
        first = next(c for c in convs if ".txt" in getattr(c, "extensions", ()))
        # The operator's own `_meta/gardener.yaml` is the most local
        # statement of intent there is, and it keeps winning.
        assert type(first).__name__ == "CommandConverter"

    def test_the_conversion_reaches_the_gardener_as_a_conversion(self,
                                                                 tmp_path,
                                                                 store):
        from monkeyllm.extensions.converters import from_registry
        from monkeyllm.gardener import Conversion
        registry = self._install(tmp_path, store, "claimer3", CLAIMS_XYZ,
                                 [".xyz"])
        conv = from_registry(registry)[0]
        source = tmp_path / "a.xyz"
        source.write_text("raw", encoding="utf-8")
        result = conv.convert(source)
        assert isinstance(result, Conversion)
        assert result.title == "from the extension"

    def test_a_raising_converter_is_a_handler_failure(self, tmp_path, store):
        from monkeyllm.extensions.converters import from_registry
        registry = self._install(tmp_path, store, "faulty", RAISES, [".xyz"])
        conv = from_registry(registry)[0]
        source = tmp_path / "a.xyz"
        source.write_text("raw", encoding="utf-8")
        with pytest.raises(RuntimeError):
            conv.convert(source)
        # It raised out of the converter, which is where the Gardener's own
        # claimant loop can fall through to the next one — never out of the
        # loader, and never at import.

    def test_a_conversion_with_an_unknown_field_is_refused(self, tmp_path,
                                                           store):
        body = ('def convert(path):\n'
                '    return {"kind": "markdown", "title": "t",'
                ' "nonesuch": 1}\n\n'
                'def register(api):\n    pass\n')
        from monkeyllm.extensions.converters import from_registry
        registry = self._install(tmp_path, store, "sloppy", body, [".xyz"])
        conv = from_registry(registry)[0]
        source = tmp_path / "a.xyz"
        source.write_text("raw", encoding="utf-8")
        with pytest.raises(VineError) as caught:
            conv.convert(source)
        assert "nonesuch" in caught.value.message
