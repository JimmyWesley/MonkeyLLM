# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Whisper extension — the first real one (spec Part L).

It exists to prove the claim the whole of Part L was written for: a
capability the deployment did not have arrives from outside, and **not one
package enters the engine's environment**. Whisper-through-an-API needs no
dependency at all — a transcription is a multipart upload the host already
knows how to make — so this suite also pins the property that makes that
true: the extension never holds an endpoint or a credential.

No network is touched here. The provider is stubbed at the one seam the
host owns (`transcribe_from_binding`), because what is under test is the
wiring, not OpenAI.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from monkeyllm.errors import VineError
from monkeyllm.extensions.api import Registry
from monkeyllm.extensions.conformance import run_kit
from monkeyllm.extensions.installer import install
from monkeyllm.extensions.loader import load
from monkeyllm.extensions.store import Store

WHISPER = Path(__file__).resolve().parents[1] / "extensions" / "whisper"
HOST = "0.79.0"

TRANSCRIPT = "Boa tarde. A reunião começa com o orçamento de 2026."


@pytest.fixture()
def store(tmp_path, monkeypatch) -> Store:
    monkeypatch.setenv("MONKEYLLM_EXT_HOME", str(tmp_path / "exthome"))
    return Store(tmp_path / "exthome")


@pytest.fixture()
def audio(tmp_path) -> Path:
    path = tmp_path / "reuniao-de-planejamento.mp3"
    path.write_bytes(b"\xff\xfb" + b"\0" * 4096)   # not real audio; never decoded
    return path


class Recorder:
    """A stand-in for the host's bound transcriber."""

    def __init__(self, text=TRANSCRIPT):
        self.text = text
        self.calls = []

    def __call__(self, role, audio, **kwargs):
        self.calls.append({"role": role, "audio": audio, **kwargs})
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


def _load(store, *, transcribe=None, config=None):
    from monkeyllm.extensions.api import ModelAccess

    install(str(WHISPER), HOST, store=store, acknowledge_unverified=True)
    registry = Registry()
    got = load(store.tree("whisper"), registry=registry,
               config=config or {},
               models_factory=lambda ext_id, roles: ModelAccess(
                   ext_id, None, roles, None, transcribe=transcribe))
    return registry, got


# ---------------------------------------------------------------------------
# It is a valid extension by the project's own kit
# ---------------------------------------------------------------------------

def test_it_passes_the_conformance_kit():
    result = run_kit(WHISPER, HOST)
    assert result.ok, result.summary()["failed"]


def test_it_carries_no_dependency():
    """The whole point: the capability arrives and the environment does not
    change. A `requirements.txt` here would mean the engine's process grows
    a package to transcribe through somebody else's API."""
    assert not (WHISPER / "requirements.txt").exists()


def test_it_claims_the_audio_extensions_the_engine_knows():
    from monkeyllm.gardener import AUDIO_EXTENSIONS

    manifest = json.loads((WHISPER / "manifest.json").read_text())
    claimed = set(manifest["contributes"]["converters"][0]["extensions"])
    # Exactly the set the built-in stub claims: an audio file the engine
    # calls media and this extension ignores would land as a stub with no
    # transcript and nobody told.
    assert claimed == AUDIO_EXTENSIONS


def test_it_registers_a_transcribe_role_rather_than_holding_a_key():
    manifest = json.loads((WHISPER / "manifest.json").read_text())
    assert manifest["models"]["registers"] == [
        {"role": "transcribe", "kind": "transcribe"}]
    # And it declares no secret of its own: the credential is the host's.
    assert all(not f.get("secret")
               for f in manifest["config"].values())
    assert manifest["permissions"]["network"] == []


# ---------------------------------------------------------------------------
# What it does with a recording
# ---------------------------------------------------------------------------

class TestConversion:
    def test_the_transcript_becomes_the_body(self, store, audio):
        seen = Recorder()
        registry, _got = _load(store, transcribe=seen)
        claim = registry.converters()[0]

        out = claim.handler(str(audio))

        assert out["kind"] == "markdown"
        assert out["title"] == "reuniao de planejamento"
        assert TRANSCRIPT in out["markdown"]
        assert "## Transcript" in out["markdown"]
        # The recording is still described, because the node keeps it.
        assert "reuniao-de-planejamento.mp3" in out["markdown"]

    def test_the_extension_never_sees_a_credential(self, store, audio):
        seen = Recorder()
        registry, got = _load(store, transcribe=seen)
        registry.converters()[0].handler(str(audio))

        for forbidden in ("endpoint", "api_key", "key", "has_key"):
            assert not hasattr(got.api.models, forbidden)
        assert set(seen.calls[0]) == {"role", "audio", "language", "prompt"}
        assert seen.calls[0]["role"] == "transcribe"

    def test_settings_reach_the_provider(self, store, audio):
        seen = Recorder()
        registry, _got = _load(store, transcribe=seen,
                               config={"language": "pt",
                                       "vocabulary": "Plastexpress, BE-291",
                                       "heading": "Ata"})
        out = registry.converters()[0].handler(str(audio))

        assert seen.calls[0]["language"] == "pt"
        # The vocabulary rides the provider's `prompt` field VERBATIM: it is
        # a decoder bias, not an instruction, so wrapping a sentence around
        # it would bias the decoder toward transcribing that sentence.
        assert seen.calls[0]["prompt"] == "Plastexpress, BE-291"
        assert "## Ata" in out["markdown"]

    def test_an_empty_setting_is_not_sent(self, store, audio):
        seen = Recorder()
        registry, _got = _load(store, transcribe=seen,
                               config={"language": "", "vocabulary": "  "})
        registry.converters()[0].handler(str(audio))
        assert seen.calls[0]["language"] is None
        assert seen.calls[0]["prompt"] is None

    def test_an_empty_transcription_raises_so_the_stub_wins(self, store,
                                                            audio):
        registry, _got = _load(store, transcribe=Recorder("   "))
        with pytest.raises(RuntimeError):
            registry.converters()[0].handler(str(audio))

    def test_a_provider_failure_raises_rather_than_planting_a_lie(self, store,
                                                                  audio):
        registry, _got = _load(
            store, transcribe=Recorder(VineError("E_SCHEMA", "provider down")))
        with pytest.raises(VineError):
            registry.converters()[0].handler(str(audio))

    def test_an_unbound_role_refuses_by_name(self, store, audio):
        from monkeyllm.extensions.api import ModelAccess

        install(str(WHISPER), HOST, store=store, acknowledge_unverified=True)
        registry = Registry()
        # A host that binds nothing: `roles` is what the operator bound.
        load(store.tree("whisper"), registry=registry,
             models_factory=lambda ext_id, roles: ModelAccess(
                 ext_id, None, {}, None, transcribe=lambda **kw: "never"))
        with pytest.raises(VineError) as caught:
            registry.converters()[0].handler(str(audio))
        assert "transcribe" in caught.value.message


# ---------------------------------------------------------------------------
# It outranks the stub, which is the only reason it is worth installing
# ---------------------------------------------------------------------------

def test_it_outranks_the_built_in_media_stub(store):
    from monkeyllm.gardener import discover_converters

    registry, _got = _load(store, transcribe=Recorder())
    convs = discover_converters({}, registry=registry)
    first = next(c for c in convs if ".mp3" in getattr(c, "extensions", ()))
    assert type(first).__name__ == "ExtensionConverter"
    assert first.ext_id == "whisper"


def test_config_edited_after_load_is_read_live(store, audio):
    """L.8 says installing needs a restart; editing a SETTING must not.

    A snapshot taken at load would make the console's Save a lie until the
    next restart — L.8's honesty rule arriving from the other side.
    """
    from monkeyllm.extensions.api import ModelAccess

    live = {"heading": "Transcript"}
    install(str(WHISPER), HOST, store=store, acknowledge_unverified=True)
    registry = Registry()
    seen = Recorder()
    from monkeyllm.extensions.loader import load as _load_one
    _load_one(store.tree("whisper"), registry=registry,
              config_provider=lambda: live,
              models_factory=lambda ext_id, roles: ModelAccess(
                  ext_id, None, roles, None, transcribe=seen))

    live["heading"] = "Ata da reunião"
    out = registry.converters()[0].handler(str(audio))
    assert "## Ata da reunião" in out["markdown"]


# ---------------------------------------------------------------------------
# The host's own transcription client — the half that leaves the process
# ---------------------------------------------------------------------------

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))


class Provider:
    """A loopback `/audio/transcriptions`, on the wire.

    A real server rather than a patched client, for the webhooks suite's
    reason: what is under test is the shape of the request that actually
    leaves — the multipart body, the model field, the Authorization header
    — and none of that is true of a mock.
    """

    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload or {"text": TRANSCRIPT}
        self.received = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — the base class's name
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                outer.received.append({
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                })
                out = json.dumps(outer.payload).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a):  # keep the suite quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.server.server_address
        self.endpoint = f"http://{host}:{port}"
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


class TestTranscriptionClient:
    def _binding(self, endpoint, model="whisper-1"):
        return {"endpoint": endpoint, "api_key": "sk-test-not-a-real-key",
                "model": model}

    def test_it_posts_a_multipart_upload_to_the_right_path(self, audio):
        from monkeyllm_station.inference import transcribe_from_binding

        with Provider() as provider:
            text, _usage = transcribe_from_binding(
                self._binding(provider.endpoint), audio, language="pt")

        assert text == TRANSCRIPT
        sent = provider.received[0]
        assert sent["path"].endswith("/audio/transcriptions")
        assert sent["headers"]["content-type"].startswith("multipart/form-data")
        assert sent["headers"]["authorization"].startswith("Bearer ")
        body = sent["body"]
        assert b'name="model"' in body and b"whisper-1" in body
        assert b'name="language"' in body and b"pt" in body
        assert audio.name.encode() in body

    def test_an_empty_setting_is_absent_from_the_body(self, audio):
        from monkeyllm_station.inference import transcribe_from_binding

        with Provider() as provider:
            transcribe_from_binding(self._binding(provider.endpoint), audio)
        body = provider.received[0]["body"]
        assert b'name="language"' not in body
        assert b'name="prompt"' not in body

    def test_a_refusal_carries_the_providers_own_words(self, audio):
        from monkeyllm_station.inference import transcribe_from_binding

        with Provider(status=401, payload={"error": "bad key"}) as provider:
            with pytest.raises(VineError) as caught:
                transcribe_from_binding(self._binding(provider.endpoint), audio)
        assert "401" in caught.value.message
        assert "bad key" in (caught.value.hint or "")

    def test_an_empty_transcription_is_a_refusal_not_an_empty_body(self,
                                                                   audio):
        from monkeyllm_station.inference import transcribe_from_binding

        with Provider(payload={"text": "   "}) as provider:
            with pytest.raises(VineError) as caught:
                transcribe_from_binding(self._binding(provider.endpoint), audio)
        assert "empty" in caught.value.message

    def test_an_oversized_file_is_refused_before_it_is_uploaded(self, tmp_path):
        from monkeyllm_station.inference import (MAX_AUDIO_BYTES,
                                                 transcribe_from_binding)

        big = tmp_path / "long-meeting.mp3"
        big.write_bytes(b"\0" * (MAX_AUDIO_BYTES + 1))
        with Provider() as provider:
            with pytest.raises(VineError) as caught:
                transcribe_from_binding(self._binding(provider.endpoint), big)
        # Refused HERE: spending the upload to be told no costs the forest's
        # lane for as long as the transfer takes.
        assert provider.received == []
        assert "over the" in caught.value.message

    def test_a_missing_file_says_so(self, tmp_path):
        from monkeyllm_station.inference import transcribe_from_binding

        with pytest.raises(VineError):
            transcribe_from_binding(self._binding("http://127.0.0.1:1"),
                                    tmp_path / "gone.mp3")


# ---------------------------------------------------------------------------
# End to end: a recording ingested through the Station
# ---------------------------------------------------------------------------

MINE = "forest-mine"


@pytest.fixture(scope="session")
def forest_template(tmp_path_factory) -> Path:
    from conftest import build_forest
    return build_forest(tmp_path_factory.mktemp("whisper") / "template")


@pytest.fixture()
def whisper_station(forest_template, tmp_path, monkeypatch):
    """A Station with `whisper` installed, enabled, and its role bound to a
    loopback provider. Everything an operator would do, minus the key."""
    from starlette.testclient import TestClient

    from monkeyllm.extensions import forestcfg
    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.setenv("MONKEYLLM_EXT_HOME", str(tmp_path / "exthome"))
    monkeypatch.setenv("MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE", "1")

    root = tmp_path / "forests"
    root.mkdir()
    shutil.copytree(forest_template, root / MINE)

    install(str(WHISPER), HOST, store=Store(), acknowledge_unverified=True)
    forestcfg.enable(root / MINE, "whisper")

    app = build_app(root=root, registry_path=tmp_path / "station.db",
                    mcp=False, writable=True)
    with TestClient(app) as client:
        yield client, app.state.registry, app


def _bind(registry, endpoint):
    """What an operator does in the Models console: name the provider, then
    bind the role the extension registered. The key never leaves here."""
    registry.put_provider("openai-test", endpoint,
                          api_key="sk-test-not-a-real-key")
    registry.bind_model(MINE, "transcribe", "openai-test", "whisper-1",
                        extra_roles={"transcribe"})


def _admin(registry, principal="root"):
    key = registry.issue_key(principal)
    registry.grant(principal, MINE, {"admin", "read", "write", "ingest"})
    return {"Authorization": f"Bearer {key}"}


def test_an_ingested_recording_becomes_a_searchable_media_node(
        whisper_station, monkeypatch):
    import base64

    client, registry, app = whisper_station
    with Provider() as provider:
        _bind(registry, provider.endpoint)
        auth = _admin(registry)

        payload = base64.b64encode(b"\xff\xfb" + b"\0" * 2048).decode()
        job = client.post(f"/v1/forests/{MINE}/ingest", headers=auth, json={
            "mode": "upload", "wait": True,
            "files": [{"name": "reuniao-de-orcamento.mp3", "b64": payload}],
        })
        assert job.status_code in (200, 202), job.text
        report = job.json().get("job", job.json())

    planted = (report.get("report") or {}).get("planted") or []
    assert planted, report
    node_id = planted[0]

    look = client.post(f"/v1/forests/{MINE}/look", headers=auth,
                       json={"id": node_id}).json()
    # The type follows the PAYLOAD, not the conversion: the recording is
    # kept and the transcript is its body, which is the whole shape of
    # G.5's "text to find, binary to consume".
    assert look["type"] == "media"
    assert look.get("payload_bytes")

    body = client.post(f"/v1/forests/{MINE}/pick", headers=auth,
                       json={"id": node_id}).json()
    assert TRANSCRIPT in body["body"]

    # And it is findable by a word that was only ever spoken.
    found = client.post(f"/v1/forests/{MINE}/sniff", headers=auth,
                        json={"terms": ["orçamento"]}).json()
    assert any(r["id"] == node_id for r in found.get("results", []))


def test_without_a_binding_the_recording_still_lands_as_a_stub(
        whisper_station):
    """L.7 rule 5, on the path that matters most: an extension may fail to
    help and may not fail the act. No binding means no transcript — and a
    findable-by-name media node a later sync can fill in, never a lost
    file."""
    import base64

    client, registry, app = whisper_station
    auth = _admin(registry)          # no _bind() call: the role is unbound

    payload = base64.b64encode(b"\xff\xfb" + b"\0" * 2048).decode()
    job = client.post(f"/v1/forests/{MINE}/ingest", headers=auth, json={
        "mode": "upload", "wait": True,
        "files": [{"name": "sem-modelo.mp3", "b64": payload}],
    })
    report = job.json().get("job", job.json())
    planted = (report.get("report") or {}).get("planted") or []
    assert planted, report

    body = client.post(f"/v1/forests/{MINE}/pick", headers=auth,
                       json={"id": planted[0]}).json()
    from monkeyllm.gardener import MEDIA_STUB_SENTINEL
    assert MEDIA_STUB_SENTINEL in body["body"]
