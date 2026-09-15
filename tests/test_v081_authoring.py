# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""F.199-F.205 — the door an author could not find (spec v0.81, L.2/L.3/L.16).

Part L shipped a mechanism and left the person it was built for with no way
in. Three gaps, and the first one is not a missing button: the console's
install box asks for "a path", and a path is on the **host** — through a
browser that is the container's filesystem, so an operator holding an
extension they had just written had no route to a remote Station short of
publishing it to git first.

The load-bearing test in this file is `test_the_authoring_schema_is_derived`:
it adds a seam to the catalogue at runtime and asserts the served document
changes. A generated reference that has to be remembered is a written one.
"""

from __future__ import annotations

import base64
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from monkeyllm.errors import VineError
from monkeyllm.extensions import authoring
from monkeyllm.extensions.conformance import run_kit
from monkeyllm.extensions.contracts import (CONTRACTS, DECLARATIVE,
                                            check_source_signature)
from monkeyllm.extensions.installer import install
from monkeyllm.extensions.manifest import SEAMS
from monkeyllm.extensions.sources import (TIER_UNVERIFIED, resolve_upload,
                                          upload_ceiling)
from monkeyllm.extensions.store import Store

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

# The installed build's own number, never a copy (the whisper suite's
# reason, tests/test_v080_whisper.py): the shipped extension pins
# `station_compat` to the minor it was tested against, so a literal here
# would have to be edited at every bump and would silently stop testing
# the range. A failure at the next MINOR is the pin working.
HOST = __import__("monkeyllm").__version__
MINE = "forest-mine"


def ext_zip(*, main: str = "def register(api):\n    pass\n",
            manifest: dict | None = None, extra: dict | None = None) -> bytes:
    """An extension as the bytes a browser would send."""
    body = {"id": "uploaded", "version": "1.0.0",
            "station_compat": ">=0.1,<99", "license": "MIT"}
    body.update(manifest or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pkg/manifest.json", json.dumps(body))
        z.writestr("pkg/main.py", main)
        z.writestr("pkg/LICENSE", "MIT")
        for name, text in (extra or {}).items():
            z.writestr(f"pkg/{name}", text)
    return buf.getvalue()


@pytest.fixture()
def store(tmp_path, monkeypatch) -> Store:
    monkeypatch.setenv("MONKEYLLM_EXT_HOME", str(tmp_path / "exthome"))
    return Store(tmp_path / "exthome")


# ---------------------------------------------------------------------------
# F.199 / F.200 / F.201 — an uploaded archive
# ---------------------------------------------------------------------------

class TestUpload:
    def test_it_installs_with_no_path_on_the_host(self, store):
        result = install("", HOST, store=store, upload=("x.zip", ext_zip()),
                         acknowledge_unverified=True)
        assert result["installed"] is True
        record = store.require("uploaded")
        assert record.kind == "upload"
        assert record.source == "upload:x.zip"

    def test_it_is_unverified_by_construction(self, store):
        # There is no forge and no index behind an upload, so nothing could
        # have been verified — and the tier says that rather than implying
        # a check happened.
        with pytest.raises(VineError) as caught:
            install("", HOST, store=store, upload=("x.zip", ext_zip()))
        assert caught.value.data["reason"] == "unverified"
        assert store.get("uploaded") is None

        install("", HOST, store=store, upload=("x.zip", ext_zip()),
                acknowledge_unverified=True)
        record = store.require("uploaded")
        assert record.tier == TIER_UNVERIFIED
        assert "no signature" in (record.reason or "")

    def test_an_oversized_upload_is_refused_before_it_is_written(
            self, store, tmp_path, monkeypatch):
        monkeypatch.setenv("MONKEYLLM_STATION_EXT_UPLOAD_MAX_MB", "1")
        work = tmp_path / "work"
        work.mkdir()
        with pytest.raises(VineError) as caught:
            resolve_upload("big.zip", b"\0" * (2 * 1024 * 1024), work)
        assert caught.value.data["reason"] == "too_large"
        # Nothing was written: spending the disk to be told no costs exactly
        # what refusing was meant to save.
        assert list(work.iterdir()) == []

    def test_the_ceiling_is_configurable_and_garbage_is_refused(
            self, monkeypatch):
        assert upload_ceiling() == 25
        monkeypatch.setenv("MONKEYLLM_STATION_EXT_UPLOAD_MAX_MB", "80")
        assert upload_ceiling() == 80
        monkeypatch.setenv("MONKEYLLM_STATION_EXT_UPLOAD_MAX_MB", "lots")
        with pytest.raises(VineError):
            upload_ceiling()

    def test_an_escaping_member_refuses_the_whole_archive(self, store,
                                                          tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("pkg/manifest.json", "{}")
            z.writestr("../escaped.py", "print('hi')")
        work = tmp_path / "work"
        work.mkdir()
        with pytest.raises(VineError) as caught:
            resolve_upload("evil.zip", buf.getvalue(), work)
        assert "escapes" in caught.value.message
        assert not (tmp_path / "escaped.py").exists()

    def test_a_bad_manifest_in_an_upload_still_installs_nothing(self, store):
        bad = ext_zip(manifest={"version": None})
        with pytest.raises(VineError):
            install("", HOST, store=store, upload=("x.zip", bad),
                    acknowledge_unverified=True)
        assert store.list() == []


# ---------------------------------------------------------------------------
# F.202 / F.205 — the seam contracts
# ---------------------------------------------------------------------------

class TestSeamContracts:
    def test_every_seam_has_a_contract_and_every_contract_a_seam(self):
        assert set(CONTRACTS) == set(SEAMS)

    def test_a_misspelled_parameter_fails_the_kit(self, tmp_path):
        tree = tmp_path / "typo"
        tree.mkdir()
        (tree / "manifest.json").write_text(json.dumps({
            "id": "typo", "version": "1.0.0", "station_compat": ">=0.1,<99",
            "license": "MIT",
            "contributes": {"events": [{"name": "w",
                                        "handler": "main:on_event"}]},
        }), encoding="utf-8")
        (tree / "main.py").write_text(
            "def on_event(event, forrest, data, **rest):\n    pass\n"
            "def register(api):\n    pass\n", encoding="utf-8")
        (tree / "LICENSE").write_text("MIT", encoding="utf-8")

        result = run_kit(tree, HOST)
        assert not result.ok
        failed = [c for c in result.failures
                  if c["check"].startswith("signature:")]
        assert failed, result.summary()["failed"]
        assert "forrest" in failed[0]["detail"]
        assert "forest" in failed[0]["detail"]      # names what IS passed

    def test_kwargs_and_omitted_parameters_both_pass(self, tmp_path):
        for body in ("def on_event(**anything):\n    pass\n",
                     "def on_event(event, forest):\n    pass\n",
                     "def on_event(event, forest, principal, data, "
                     "metadata):\n    pass\n"):
            tree = tmp_path / f"ok{abs(hash(body))}"
            tree.mkdir()
            (tree / "manifest.json").write_text(json.dumps({
                "id": "okext", "version": "1.0.0",
                "station_compat": ">=0.1,<99", "license": "MIT",
                "contributes": {"events": [{"name": "w",
                                            "handler": "main:on_event"}]},
            }), encoding="utf-8")
            (tree / "main.py").write_text(
                body + "def register(api):\n    pass\n", encoding="utf-8")
            (tree / "LICENSE").write_text("MIT", encoding="utf-8")
            assert run_kit(tree, HOST).ok, body

    def test_the_check_never_imports_the_module(self, tmp_path):
        """A heavy handler's module imports the dependency L.5 exists to
        keep out of this process, so the check that catches an author's
        typo must not be the thing that breaks the rule."""
        tree = tmp_path / "heavy"
        tree.mkdir()
        (tree / "worker.py").write_text(
            "import a_module_that_does_not_exist_anywhere\n"
            "def convert(path):\n    return {}\n", encoding="utf-8")
        # It reads the signature fine, and importing would have raised.
        assert check_source_signature("converters", tree / "worker.py",
                                      "convert") is None
        assert "a_module_that_does_not_exist_anywhere" not in sys.modules

    def test_the_shipped_extension_passes_its_own_contracts(self):
        whisper = Path(__file__).resolve().parents[1] / "extensions" / "whisper"
        result = run_kit(whisper, HOST)
        assert result.ok, result.summary()["failed"]
        assert any(c["check"].startswith("signature:") for c in result.checks)


# ---------------------------------------------------------------------------
# F.203 — the authoring schema is DERIVED
# ---------------------------------------------------------------------------

class TestDerivedSchema:
    def test_it_carries_every_seam_and_the_hosts_version(self):
        doc = authoring.schema("9.9.9")
        assert doc["station"] == "9.9.9"
        assert [s["seam"] for s in doc["seams"]] == list(SEAMS)
        assert doc["manifest"]["title"] == "Manifest"

    def test_adding_a_seam_changes_it_with_no_second_edit(self, monkeypatch):
        """The test of a generated document is not that it looks right."""
        from monkeyllm.extensions import contracts as C
        from monkeyllm.extensions.contracts import SeamContract

        before = authoring.seam_reference("0.81.0")
        assert "smoke_signals" not in before

        monkeypatch.setattr(C, "CONTRACTS", {**C.CONTRACTS, "smoke_signals":
                            SeamContract(seam="smoke_signals",
                                         summary="A seam invented by a test.",
                                         params=(("puff", "how many"),),
                                         returns="nothing",
                                         precedence="none")})
        monkeypatch.setattr("monkeyllm.extensions.authoring.CONTRACTS",
                            C.CONTRACTS)
        monkeypatch.setattr("monkeyllm.extensions.authoring.SEAMS",
                            tuple(SEAMS) + ("smoke_signals",))

        after = authoring.seam_reference("0.81.0")
        assert "smoke_signals" in after
        assert "A seam invented by a test." in after
        assert "def handler(puff, **kwargs)" in after

    def test_the_attributed_seams_say_so(self):
        doc = authoring.schema("0.81.0")
        attributed = {s["seam"] for s in doc["seams"] if s["attributed"]}
        assert attributed == {"ranking", "prompt"}

    def test_the_declarative_seams_offer_no_signature(self):
        doc = authoring.schema("0.81.0")
        for s in doc["seams"]:
            if s["seam"] in DECLARATIVE:
                assert s["signature"] is None and s["declarative"] is True
            else:
                assert s["signature"]

    def test_the_generated_reference_says_it_is_generated(self):
        for text in (authoring.seam_reference("0.81.0"),
                     authoring.manifest_reference("0.81.0")):
            assert "GENERATED" in text.splitlines()[0]
            assert "0.81.0" in text


# ---------------------------------------------------------------------------
# F.199 / F.204 — over the wire
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def forest_template(tmp_path_factory) -> Path:
    from conftest import build_forest
    return build_forest(tmp_path_factory.mktemp("authoring") / "template")


@pytest.fixture()
def station(forest_template, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.setenv("MONKEYLLM_EXT_HOME", str(tmp_path / "exthome"))
    root = tmp_path / "forests"
    root.mkdir()
    shutil.copytree(forest_template, root / MINE)
    shutil.copytree(forest_template, root / "forest-theirs")
    app = build_app(root=root, registry_path=tmp_path / "station.db",
                    mcp=False, writable=True)
    with TestClient(app) as client:
        yield client, app.state.registry


def owner(registry):
    registry.add_principal("owner", kind="user")
    registry.conn.execute("UPDATE principals SET owner = 1 WHERE id = ?",
                          ("owner",))
    registry.conn.commit()
    return {"Authorization": f"Bearer {registry.issue_key('owner')}"}


def reader(registry):
    """Someone who may open the console and may NOT install anything."""
    key = registry.issue_key("reader")
    registry.grant("reader", MINE, {"read"})
    return {"Authorization": f"Bearer {key}"}


class TestOverTheWire:
    def test_an_upload_installs_with_no_path_on_the_host(self, station):
        client, registry = station
        body = {"action": "install", "acknowledge": True,
                "upload": {"name": "uploaded.zip",
                           "b64": base64.b64encode(ext_zip()).decode()}}
        r = client.post("/v1/admin/extensions", json=body,
                        headers=owner(registry))
        assert r.status_code == 201, r.text
        assert r.json()["id"] == "uploaded"
        assert r.json()["tier"] == "unverified"

    def test_a_malformed_upload_is_refused_by_shape(self, station):
        client, registry = station
        auth = owner(registry)
        for bad in ({"upload": "a string"}, {"upload": {"name": "x.zip"}},
                    {"upload": {"name": "x.zip", "b64": "not base64!!"}}):
            r = client.post("/v1/admin/extensions",
                            json={"action": "install", **bad}, headers=auth)
            assert r.status_code == 400, bad

    def test_a_plan_of_an_upload_installs_nothing(self, station):
        client, registry = station
        auth = owner(registry)
        r = client.post("/v1/admin/extensions", json={
            "action": "plan",
            "upload": {"name": "u.zip",
                       "b64": base64.b64encode(ext_zip()).decode()}},
            headers=auth)
        assert r.json()["id"] == "uploaded"
        assert r.json()["tier"] == "unverified"
        assert client.get("/v1/admin/extensions",
                          headers=auth).json()["extensions"] == []

    def test_authoring_reaches_somebody_who_may_not_install(self, station):
        """L.16 rule 3. An extension is written on a laptop and installed by
        whoever governs the deployment, so gating the documentation on the
        authority to install withholds it from the only person who needs
        it."""
        client, registry = station
        auth = reader(registry)
        # They cannot install, and cannot even list what is installed.
        assert client.post("/v1/admin/extensions", json={"source": "x"},
                           headers=auth).status_code == 403
        assert client.get("/v1/admin/extensions",
                          headers=auth).status_code == 403
        # And they can read how to write one.
        doc = client.get("/v1/extensions/authoring", headers=auth)
        assert doc.status_code == 200
        assert len(doc.json()["seams"]) == len(SEAMS)

    def test_authoring_refuses_an_anonymous_caller(self, station):
        client, _registry = station
        assert client.get("/v1/extensions/authoring").status_code == 401

    def test_it_serves_the_generated_markdown(self, station):
        client, registry = station
        auth = reader(registry)
        for doc, needle in (("seams", "# Seams"), ("manifest", "JSON Schema")):
            r = client.get(f"/v1/extensions/authoring?as=markdown&doc={doc}",
                           headers=auth)
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/markdown")
            assert needle in r.text
            assert "GENERATED" in r.text

    def test_the_served_document_names_the_hosts_version(self, station):
        from monkeyllm_station.mcp_surface import package_version

        client, registry = station
        doc = client.get("/v1/extensions/authoring",
                         headers=reader(registry)).json()
        assert doc["station"] == package_version()
