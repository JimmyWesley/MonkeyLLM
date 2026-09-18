# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""F.228 — the heavy worker is told its settings (spec L.5, v0.84).

A heavy handler received a path and nothing else, so the one shipped
converter that has knobs reads every one of them from the host's
environment and declares an empty `config` block — L.10's "the config
schema is the source of truth" defeated by the transport.

The four properties this file holds to, each of which is a way the obvious
implementation is wrong:

1. The request carries the **resolved** config — the manifest's declared
   defaults under the operator's stored values — and it is resolved at CALL
   time, so a console Save reaches the next call without a restart.
2. A handler that did not ask receives the v0.83 request **byte for byte**.
   That is why the decision is made on the host, off the author's source:
   deciding in the child would mean sending a `config` the child discards,
   which is a different request.
3. A declared secret goes to the worker and to nothing else — not a log,
   not a report, not a refusal's hint, not a crash trace.
4. The value rides the request BESIDE the arguments, not inside them, so a
   non-Python worker reads it as an ordinary field.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from monkeyllm.errors import VineError
from monkeyllm.extensions.api import Registry
from monkeyllm.extensions.contracts import declares_config
from monkeyllm.extensions.loader import load
from monkeyllm.extensions.manifest import parse_manifest

HOST = "0.84.0"

MAIN = '''
def register(api):
    pass
'''

# The handler ASKS. It answers with what it was given, so the assertion is
# about what crossed the pipe and not about what the host intended.
ASKS = '''
def convert(path, config=None):
    return {"kind": "markdown", "title": "asked",
            "markdown": repr(sorted((config or {}).items()))}
'''

# The v0.83 shape: one positional path, nothing else.
SILENT = '''
def convert(path):
    return {"kind": "markdown", "title": "silent", "markdown": path}
'''


def make_ext(root: Path, ext_id: str, *, worker: str,
             config: dict | None = None) -> Path:
    tree = root / ext_id
    tree.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": ext_id,
        "version": "1.0.0",
        "station_compat": ">=0.84,<1.0",
        "license": "MIT",
        "contributes": {"converters": [
            {"extensions": [".bin"], "handler": "worker:convert",
             "heavy": True}]},
    }
    if config is not None:
        manifest["config"] = config
    (tree / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tree / "main.py").write_text(MAIN, encoding="utf-8")
    (tree / "worker.py").write_text(worker, encoding="utf-8")
    (tree / "LICENSE").write_text("MIT", encoding="utf-8")
    return tree


@pytest.fixture()
def requests(monkeypatch):
    """Every worker request, as the bytes that actually went down the pipe."""
    seen: list[dict] = []
    real = subprocess.run

    def spy(*args, **kwargs):
        if kwargs.get("input"):
            seen.append(json.loads(kwargs["input"]))
        return real(*args, **kwargs)

    monkeypatch.setattr("monkeyllm.extensions.worker.subprocess.run", spy)
    return seen


def _converter(tree: Path, *, stored: dict | None = None, live=None):
    registry = Registry()
    load(tree, registry=registry, config=dict(stored or {}),
         config_provider=live)
    return registry.converters()[0]


# ---------------------------------------------------------------------------
# F.228 rule 1 — the resolved config, resolved at call time
# ---------------------------------------------------------------------------

def test_a_handler_that_asks_receives_defaults_under_stored_values(
        tmp_path, requests):
    tree = make_ext(tmp_path, "asks", worker=ASKS, config={
        "tables": {"type": "boolean", "default": False},
        "max_pages": {"type": "integer", "default": 500},
        # Declared with NO default: absent is a real state, and inventing a
        # null would make the worker read a setting nobody chose.
        "layout": {"type": "string"},
    })
    claim = _converter(tree, stored={"tables": True})

    out = claim.handler("/tmp/x.bin")
    assert out["title"] == "asked"
    # The operator's value wins over the declared default; the default
    # arrives for what the operator never touched; the undeclared-default
    # field is absent rather than None.
    assert eval(out["markdown"]) == [("max_pages", 500), ("tables", True)]

    assert requests[-1]["config"] == {"max_pages": 500, "tables": True}
    # Rule 4: beside the arguments, never inside them — a non-Python worker
    # reads it as a field of the request.
    assert requests[-1]["kwargs"] == {}
    assert requests[-1]["args"] == ["/tmp/x.bin"]


def test_an_edit_reaches_the_next_call_without_a_restart(tmp_path, requests):
    """L.7 rule 4 from the worker's side: installing takes a restart,
    configuring does not. A value captured at load would make the console's
    Save a lie until the next one."""
    tree = make_ext(tmp_path, "live", worker=ASKS,
                    config={"mode": {"type": "string", "default": "fast"}})
    live = {"mode": "careful"}
    claim = _converter(tree, live=lambda: dict(live))

    claim.handler("/tmp/x.bin")
    assert requests[-1]["config"] == {"mode": "careful"}
    live["mode"] = "exhaustive"
    claim.handler("/tmp/x.bin")
    assert requests[-1]["config"] == {"mode": "exhaustive"}


# ---------------------------------------------------------------------------
# F.228 rule 2 — a handler that does not ask is unchanged, byte for byte
# ---------------------------------------------------------------------------

def test_a_handler_that_never_asked_gets_the_v083_request(tmp_path, requests):
    tree = make_ext(tmp_path, "silent", worker=SILENT,
                    config={"knob": {"type": "string", "default": "x"}})
    claim = _converter(tree, stored={"knob": "y"})

    assert claim.handler("/tmp/x.bin")["markdown"] == "/tmp/x.bin"
    request = requests[-1]
    assert "config" not in request
    assert sorted(request) == ["args", "handler", "kwargs", "paths", "root"]


def test_whether_it_asked_is_read_off_the_source_never_imported(tmp_path):
    """The check may not import the module: a heavy handler's module imports
    the very dependency L.5 exists to keep out of this process."""
    marker = "monkeyllm_ext_absent_probe"
    body = f"import {marker}\n\ndef convert(path, config=None):\n    return {{}}\n"
    tree = make_ext(tmp_path, "unimportable", worker=body)
    assert declares_config(tree / "worker.py", "convert") is True
    assert declares_config(tree / "worker.py", "nosuchfunction") is False
    # And loading it still works, because nothing here imported it.
    claim = _converter(tree)
    assert claim.heavy is True


# ---------------------------------------------------------------------------
# F.228 rule 3 — a secret reaches the worker and nothing else
# ---------------------------------------------------------------------------

def test_a_secret_reaches_the_worker_and_no_refusal_repeats_it(tmp_path,
                                                               requests):
    secret = "sk-live-do-not-print-4d9f"
    tree = make_ext(tmp_path, "secretive", worker=ASKS, config={
        "api_key": {"type": "string", "secret": True}})
    claim = _converter(tree, stored={"api_key": secret})
    claim.handler("/tmp/x.bin")
    assert requests[-1]["config"] == {"api_key": secret}

    # Now the worker dies. The refusal carries the child's stderr and the
    # handler's name; it must never carry the request.
    broken = make_ext(tmp_path, "secretive2", worker=(
        "def convert(path, config=None):\n    raise RuntimeError('boom')\n"),
        config={"api_key": {"type": "string", "secret": True}})
    claim = _converter(broken, stored={"api_key": secret})
    with pytest.raises(VineError) as caught:
        claim.handler("/tmp/x.bin")
    rendered = json.dumps(caught.value.to_dict())
    assert caught.value.code == "E_EXT_WORKER"
    assert secret not in rendered
    assert secret not in (caught.value.hint or "")


def test_a_declared_secret_is_readable_by_the_extension_alone(tmp_path):
    """L.7 rule 4's existing rule, unchanged: `api.secret` refuses a key the
    manifest never declared secret, and the resolution is the same one the
    worker request carries."""
    tree = make_ext(tmp_path, "declared", worker=ASKS, config={
        "api_key": {"type": "string", "secret": True},
        "plain": {"type": "string", "default": "open"}})
    registry = Registry()
    loaded = load(tree, registry=registry, config={"api_key": "s3cr3t"})
    assert loaded.api.secret("api_key") == "s3cr3t"
    assert loaded.api.resolved_config == {"api_key": "s3cr3t", "plain": "open"}
    with pytest.raises(VineError):
        loaded.api.secret("plain")


def test_the_manifest_defaults_are_read_from_the_schema(tmp_path):
    """L.10: the config schema is the source of truth, and the defaults are
    DERIVED from it — a second list of defaults would drift silently."""
    tree = make_ext(tmp_path, "schema", worker=ASKS, config={
        "a": {"type": "integer", "default": 7},
        "b": {"type": "string"},
        "c": {"type": "boolean", "default": False}})
    manifest = parse_manifest(json.loads(
        (tree / "manifest.json").read_text(encoding="utf-8")))
    assert manifest.config_defaults() == {"a": 7, "c": False}


def test_the_kit_accepts_the_shape_the_documentation_teaches(tmp_path):
    """L.9 + L.16: the check and the prose are one declaration.

    `docs/extending.md` teaches `def convert(path, config): ...`, and before
    `config` was a DECLARED parameter of the seam the conformance kit
    refused exactly that signature — the kit saying no to the shape the
    document said to write, which is the v0.81 failure (an `events` handler
    declaring `echo(value)`) arriving from the other side.
    """
    from monkeyllm.extensions.authoring import seam_reference
    from monkeyllm.extensions.contracts import check_source_signature

    worker = tmp_path / "w.py"
    worker.write_text("def convert(path, config):\n    return {}\n",
                      encoding="utf-8")
    assert check_source_signature("converters", worker, "convert", True) is None
    # …and a LIGHT handler naming it is still a fault: nothing passes it one,
    # so the parameter would bind to nothing and fail at call time, which is
    # the silence this check exists to break.
    light = check_source_signature("converters", worker, "convert", False)
    assert light and "config" in light

    worker.write_text("def convert(path, config=None):\n    return {}\n",
                      encoding="utf-8")
    for heavy in (True, False):
        assert check_source_signature("converters", worker, "convert",
                                      heavy) is None

    # And a misspelling is still the fault this check exists for.
    worker.write_text("def convert(path, confg):\n    return {}\n",
                      encoding="utf-8")
    problem = check_source_signature("converters", worker, "convert", True)
    assert problem and "confg" in problem and "config" in problem

    # L.16: the reference is DERIVED, so the parameter is documented by the
    # same declaration the check reads.
    reference = seam_reference(HOST)
    assert "`config`" in reference
    assert "`heavy: true`" in reference

    teaching = (Path(__file__).resolve().parents[1] / "docs" / "extending.md")
    assert "def convert(path, config)" in teaching.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The shipped converter this amendment was written for
# ---------------------------------------------------------------------------

PDF_WORKER = Path(__file__).resolve().parents[1] / "ideias" / "extensions" \
    / "pdf" / "worker.py"


@pytest.mark.skipif(not PDF_WORKER.is_file(),
                    reason="the pdf extension is not in this checkout")
def test_the_pdf_converter_reads_a_passed_key_over_the_environment(
        monkeypatch):
    """The motivating case, end to end at the settings layer: the extension
    declared every knob as an environment variable because the transport
    carried nothing, and a passed key is a per-install decision while the
    environment is the whole deployment's."""
    assert declares_config(PDF_WORKER, "convert") is True

    spec = importlib.util.spec_from_file_location("_pdf_worker_probe",
                                                  PDF_WORKER)
    module = importlib.util.module_from_spec(spec)
    # `@dataclass` resolves its annotations through `sys.modules`, so a
    # module executed without being registered there raises inside
    # `dataclasses` rather than in anything this test is about.
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)          # stdlib only at module level

    monkeypatch.setitem(os.environ, "MONKEYLLM_EXT_PDF_TABLES", "1")
    assert module._settings().tables is True
    assert module._settings({"tables": "0"}).tables is False
    assert module._settings({"max_pages": 12}).max_pages == 12
