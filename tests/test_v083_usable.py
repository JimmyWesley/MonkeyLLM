# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The extension that could not be used (spec v0.83 — F.213-F.217).

An operator installed two extensions through the console, enabled both, and
could use neither: the ingest console kept a list of formats of its own and
greyed out the `.pdf` a loaded converter claimed; the Models console kept a
list of roles of its own and the bind route refused the role a loaded
extension registered. Nothing had failed. The surfaces had never been told
what the mechanism under them changed.

The tests here pin the four answers the host now gives — what a forest's
chain takes (F.213/F.214), what may be bound (F.215), what is loaded and
active without a restart (F.216), and enabling in the same act as the
install (F.217) — and one loader defect found on the way: only the FIRST
extension on a volume read its settings live. F.218 is the static check in
`apps/studio/check-usable.mjs`, run from `test_v083_usable_console.py`.
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


# ---------------------------------------------------------------------------
# fixtures — the shape of test_v080_station_extensions, on purpose
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def forest_template(tmp_path_factory) -> Path:
    from conftest import build_forest
    return build_forest(tmp_path_factory.mktemp("usable") / "template")


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
    key = registry.issue_key(principal)
    # The owner administers both forests here, so `enable_on` has a forest
    # to land on and F.217's refusal has a principal who does NOT.
    for forest in (MINE, THEIRS):
        registry.grant(principal, forest, {"admin", "read", "write", "ingest"})
    return {"Authorization": f"Bearer {key}"}


def make_ext(root: Path, ext_id: str, *, extensions=(".pdf",), roles=(),
             main: str | None = None) -> Path:
    """A valid extension claiming `extensions` and registering `roles`."""
    tree = root / ext_id
    tree.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": ext_id, "version": "1.0.0", "station_compat": ">=0.1,<99",
        "license": "MIT", "description": f"{ext_id} for the tests.",
        "models": {"registers": [dict(r) for r in roles]},
        "contributes": {"converters": [
            {"extensions": list(extensions), "handler": "main:convert"}]
            if extensions else []},
        "config": {"language": {"type": "string", "default": "auto"}},
    }
    (tree / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    (tree / "main.py").write_text(main or (
        "_API = {}\n"
        "def register(api):\n    _API['api'] = api\n"
        "def convert(path):\n"
        "    return {'kind': 'markdown', 'title': 'x', 'markdown': '# x\\n\\nbody'}\n"
        "def language():\n    return dict(_API['api'].config).get('language')\n"),
        "utf-8")
    (tree / "LICENSE").write_text("MIT", "utf-8")
    return tree


def install(client, auth, tree, **extra):
    body = {"source": str(tree), "acknowledge": True}
    body.update(extra)
    return client.post("/v1/admin/extensions", json=body, headers=auth)


def enable(client, auth, ext_id, forest=MINE):
    return client.post("/v1/admin/extensions/enablement",
                       json={"forest": forest, "ext": ext_id}, headers=auth)


# ---------------------------------------------------------------------------
# F.213 — the chain can be asked, in precedence order
# ---------------------------------------------------------------------------

class TestSupportedFormats:
    def test_built_ins_answer_with_no_forest_and_no_file_open(self):
        from monkeyllm.gardener import supported_formats
        formats = {f["extension"]: f["via"] for f in supported_formats({})}
        assert formats[".md"] == "builtin"
        assert formats[".png"] == "builtin"        # the media stub (G.5.1)
        assert ".pdf" not in formats                # nothing ships for it

    def test_a_command_hook_outranks_everything(self):
        from monkeyllm.gardener import supported_formats
        config = {"converters": {".png": 'tool "{input}" "{output}"',
                                 ".pdf": 'tool "{input}" "{output}"'}}
        formats = {f["extension"]: f["via"] for f in supported_formats(config)}
        assert formats[".pdf"] == "hook"
        assert formats[".png"] == "hook"            # above the built-in stub

    def test_an_extension_outranks_the_built_in_and_yields_to_a_hook(
            self, tmp_path):
        from monkeyllm.extensions.api import Registry
        from monkeyllm.extensions.installer import install as engine_install
        from monkeyllm.extensions.loader import load
        from monkeyllm.extensions.store import Store
        from monkeyllm.gardener import supported_formats

        store = Store(tmp_path / "home")
        tree = make_ext(tmp_path / "src", "pdfx", extensions=(".pdf", ".png"))
        engine_install(str(tree), "0.83.0", store=store,
                       acknowledge_unverified=True)
        registry = Registry()
        load(store.tree("pdfx"), registry=registry)

        formats = {f["extension"]: f["via"]
                   for f in supported_formats({}, registry=registry)}
        assert formats[".pdf"] == "ext:pdfx"
        assert formats[".png"] == "ext:pdfx"        # above the stub

        hooked = {f["extension"]: f["via"] for f in supported_formats(
            {"converters": {".png": 'tool "{input}" "{output}"'}},
            registry=registry)}
        assert hooked[".png"] == "hook"
        assert hooked[".pdf"] == "ext:pdfx"

    def test_the_order_is_the_discovery_order(self):
        """Read and run agree: every extension the chain claims is answered,
        and the first claimant named is the one `discover_converters` would
        hand the file to."""
        from monkeyllm.gardener import discover_converters, supported_formats
        config = {"converters": {".pdf": 'tool "{input}" "{output}"'}}
        chain = discover_converters(config)
        answered = {f["extension"] for f in supported_formats(config)}
        claimed = {e for c in chain for e in c.extensions}
        assert answered == claimed
        first = {f["extension"]: f["via"] for f in supported_formats(config)}
        for ext in claimed:
            head = next(c for c in chain if ext in c.extensions)
            assert (first[ext] == "hook") == (type(head).__name__ == "CommandConverter")


# ---------------------------------------------------------------------------
# F.214 — the ingest status carries what THIS forest converts
# ---------------------------------------------------------------------------

def test_formats_follow_enablement_per_forest(station, tmp_path):
    client, registry, _ = station
    owner = owner_key(registry)
    tree = make_ext(tmp_path / "src", "pdfx", extensions=(".pdf",))
    assert install(client, owner, tree).status_code == 201

    def formats(forest):
        r = client.get(f"/v1/forests/{forest}/ingest", headers=owner)
        assert r.status_code == 200, r.text
        return {f["extension"]: f["via"] for f in r.json()["formats"]}

    before = formats(MINE)
    assert ".pdf" not in before
    assert before[".md"] == "builtin"

    assert enable(client, owner, "pdfx", MINE).status_code == 200
    assert formats(MINE)[".pdf"] == "ext:pdfx"
    assert ".pdf" not in formats(THEIRS)            # not enabled there


# ---------------------------------------------------------------------------
# F.215 — a registered role is bindable wherever a role is bound
# ---------------------------------------------------------------------------

class TestBindableRoles:
    def test_the_catalogue_names_built_ins_and_registered_roles(
            self, station, tmp_path):
        client, registry, _ = station
        owner = owner_key(registry)
        tree = make_ext(tmp_path / "src", "whisper", extensions=(".mp3",),
                        roles=({"role": "transcribe", "kind": "transcribe",
                                "description": "Turns a recording into text."},
                               {"role": "frames", "kind": "vision"}))
        assert install(client, owner, tree).status_code == 201

        roles = client.get(f"/v1/admin/models?forest={MINE}",
                           headers=owner).json()["roles"]
        by_name = {r["role"]: r for r in roles}
        assert [r["role"] for r in roles][:4] == ["ingest", "answer", "vision",
                                                  "embed"]
        assert by_name["ingest"] == {"role": "ingest", "kind": "chat",
                                     "builtin": True, "description": ""}
        assert by_name["transcribe"] == {
            "role": "transcribe", "kind": "transcribe", "builtin": False,
            "ext": "whisper", "description": "Turns a recording into text."}
        assert by_name["frames"]["kind"] == "vision"
        assert by_name["frames"]["ext"] == "whisper"

    def test_a_registered_role_binds_through_the_route(self, station,
                                                       tmp_path):
        client, registry, _ = station
        owner = owner_key(registry)
        tree = make_ext(tmp_path / "src", "whisper", extensions=(".mp3",),
                        roles=({"role": "transcribe", "kind": "transcribe"},))
        install(client, owner, tree)
        registry.put_provider("openai-test", "https://api.example.test/v1",
                              api_key="sk-test")
        r = client.post("/v1/admin/models", headers=owner, json={
            "forest": MINE, "role": "transcribe", "provider": "openai-test",
            "model": "whisper-1"})
        assert r.status_code == 200, r.text
        bound = {b["role"]: b for b in r.json()["bindings"]}
        assert bound["transcribe"]["model"] == "whisper-1"
        # …and the extension's own model access resolves it.
        assert registry.binding(MINE, "transcribe")["model"] == "whisper-1"

    def test_an_unknown_role_is_refused_by_listing_what_would_bind(
            self, station):
        client, registry, _ = station
        owner = owner_key(registry)
        registry.put_provider("p", "https://api.example.test/v1", api_key="k")
        r = client.post("/v1/admin/models", headers=owner, json={
            "forest": MINE, "role": "transcribe", "provider": "p",
            "model": "whisper-1"})
        assert r.status_code == 400
        message = r.json()["error"]["message"]
        assert "role must be one of" in message and "vision" in message


# ---------------------------------------------------------------------------
# F.216 — a first install is active at once; an update keeps the restart
# ---------------------------------------------------------------------------

class TestLiveActivation:
    def test_a_first_install_is_loaded_and_serving_without_a_restart(
            self, station, tmp_path):
        client, registry, app = station
        owner = owner_key(registry)
        tree = make_ext(tmp_path / "src", "pdfx", extensions=(".pdf",),
                        roles=({"role": "transcribe", "kind": "transcribe"},))
        r = install(client, owner, tree)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["activated"] is True
        assert body["restart_required"] is False
        assert body["formats"] == [".pdf"]
        assert [x["role"] for x in body["registers_roles"]] == ["transcribe"]

        listed = client.get("/v1/admin/extensions", headers=owner).json()
        (entry,) = listed["extensions"]
        assert entry["loaded"] is True
        assert entry["formats"] == [".pdf"]

        # Its role is bindable now…
        roles = {x["role"] for x in client.get(
            f"/v1/admin/models?forest={MINE}", headers=owner).json()["roles"]}
        assert "transcribe" in roles
        # …and, once enabled, its format is accepted now.
        assert enable(client, owner, "pdfx").json()["restart_required"] is False
        formats = {f["extension"]: f["via"] for f in client.get(
            f"/v1/forests/{MINE}/ingest", headers=owner).json()["formats"]}
        assert formats[".pdf"] == "ext:pdfx"

    def test_the_activated_converter_actually_converts(self, station,
                                                       tmp_path):
        import base64
        client, registry, app = station
        owner = owner_key(registry)
        install(client, owner, make_ext(tmp_path / "src", "pdfx",
                                        extensions=(".pdf",)))
        enable(client, owner, "pdfx")
        payload = base64.b64encode(b"%PDF-1.4 not really").decode()
        job = client.post(f"/v1/forests/{MINE}/ingest", headers=owner, json={
            "mode": "upload", "wait": True,
            "files": [{"name": "relatorio.pdf", "b64": payload}]})
        assert job.status_code in (200, 202), job.text
        report = (job.json().get("job") or job.json()).get("report") or {}
        assert report.get("planted"), report
        assert report.get("unsupported") == []

    def test_a_reinstall_of_a_loaded_id_keeps_the_restart(self, station,
                                                          tmp_path):
        client, registry, _ = station
        owner = owner_key(registry)
        tree = make_ext(tmp_path / "src", "pdfx", extensions=(".pdf",))
        assert install(client, owner, tree).json()["activated"] is True
        again = install(client, owner, tree).json()
        assert again["activated"] is False
        assert again["restart_required"] is True
        assert "restart" in again["activation_note"]
        # Still listed as loaded: the code that serves is the first one.
        (entry,) = client.get("/v1/admin/extensions",
                              headers=owner).json()["extensions"]
        assert entry["loaded"] is True

    def test_an_activation_failure_does_not_fail_the_install(self, station,
                                                             tmp_path):
        client, registry, _ = station
        owner = owner_key(registry)
        tree = make_ext(tmp_path / "src", "broken", extensions=(".pdf",),
                        main="def register(api):\n    raise RuntimeError('boom')\n"
                             "def convert(path):\n    return {}\n")
        r = install(client, owner, tree)
        assert r.status_code == 201, r.text
        assert r.json()["activated"] is False
        assert r.json()["restart_required"] is True
        assert "boom" in r.json()["activation_note"]
        (entry,) = client.get("/v1/admin/extensions",
                              headers=owner).json()["extensions"]
        assert entry["loaded"] is False


# ---------------------------------------------------------------------------
# F.217 — enabling rides the install, for the forest's admin only
# ---------------------------------------------------------------------------

class TestEnableOnInstall:
    def test_the_owner_installs_and_enables_in_one_act(self, station,
                                                       tmp_path):
        client, registry, app = station
        owner = owner_key(registry)
        tree = make_ext(tmp_path / "src", "pdfx", extensions=(".pdf",))
        body = install(client, owner, tree, enable_on=MINE).json()
        assert body["enabled_on"] == [MINE]
        assert "enable_error" not in body

        from monkeyllm.extensions import forestcfg
        root = Path(app.state.pool.root)
        assert forestcfg.enabled(root / MINE) == ["pdfx"]
        assert forestcfg.enabled(root / THEIRS) == []
        assert client.get(f"/v1/admin/extensions/enablement?forest={MINE}",
                          headers=owner).json()["enabled"] == ["pdfx"]

    def test_a_forest_that_cannot_be_enabled_refuses_only_the_enablement(
            self, station, tmp_path):
        """Whoever may install administers every forest (J.10.2's reach
        rule), so the refusal a real installer can meet is a forest the
        deployment does not have — and it must not undo the install."""
        client, registry, app = station
        owner = owner_key(registry)
        tree = make_ext(tmp_path / "src", "pdfx", extensions=(".pdf",))
        r = install(client, owner, tree, enable_on="no-such-forest")
        assert r.status_code == 201, r.text          # the install landed
        body = r.json()
        assert "enabled_on" not in body
        assert "no-such-forest" in body["enable_error"]
        assert body["activated"] is True
        (entry,) = client.get("/v1/admin/extensions",
                              headers=owner).json()["extensions"]
        assert entry["loaded"] is True
        from monkeyllm.extensions import forestcfg
        root = Path(app.state.pool.root)
        assert forestcfg.enabled(root / MINE) == []
        assert forestcfg.enabled(root / THEIRS) == []


# ---------------------------------------------------------------------------
# the loader defect — every extension reads its settings live, not the first
# ---------------------------------------------------------------------------

def test_every_extension_reads_its_config_live_not_only_the_first(tmp_path):
    from monkeyllm.extensions.api import Registry
    from monkeyllm.extensions.installer import install as engine_install
    from monkeyllm.extensions.loader import load_all
    from monkeyllm.extensions.store import Store

    store = Store(tmp_path / "home")
    for ext_id in ("alpha", "beta"):
        engine_install(str(make_ext(tmp_path / "src", ext_id)), "0.83.0",
                       store=store, acknowledge_unverified=True)
    live = {"alpha": {"language": "pt"}, "beta": {"language": "es"}}
    report = load_all(store.list(), store, registry=Registry(),
                      config_factory=lambda ext_id: (lambda: live[ext_id]))
    assert [l.manifest.id for l in report.loaded] == ["alpha", "beta"]
    assert report.loaded[0].api.config["language"] == "pt"
    # Before the fix `beta` read the store's snapshot ("auto"): the factory
    # had been popped from the kwargs by `alpha`'s iteration.
    assert report.loaded[1].api.config["language"] == "es"
    live["beta"]["language"] = "fr"
    assert report.loaded[1].api.config["language"] == "fr"
