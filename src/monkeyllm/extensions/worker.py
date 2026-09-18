# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.5 — a heavy handler runs in the extension's own process.

This is the module that makes the whole design pay: a transcriber's
machine-learning stack, a converter's document toolchain, a binary that is
not Python at all — none of it is imported into the process that serves the
forest. The host keeps the registration and gives up the execution.

The protocol is deliberately language-neutral in shape: one JSON request in,
one JSON response out, over the child's stdio. A future non-Python worker is
then a packaging question and not a contract change.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from monkeyllm.errors import E_TIMEOUT, VineError

E_EXT_WORKER = "E_EXT_WORKER"

DEFAULT_TIMEOUT = float(os.environ.get("MONKEYLLM_EXT_WORKER_TIMEOUT", "300"))

# The child's whole program. It is written out beside the extension rather
# than imported, because the point is that the host's interpreter never
# touches the extension's dependencies.
_RUNNER = r'''
import importlib.util, json, sys, traceback
from pathlib import Path

def _load(root, module):
    path = Path(root) / (module.replace(".", "/") + ".py")
    spec = importlib.util.spec_from_file_location(f"_mlx_{module}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

def main():
    req = json.loads(sys.stdin.read())
    sys.path.insert(0, req["root"])
    for extra in req.get("paths", []):
        sys.path.insert(0, extra)
    try:
        module, _, func = req["handler"].partition(":")
        target = getattr(_load(req["root"], module), func)
        kwargs = dict(req.get("kwargs") or {})
        # L.5 (v0.84): `config` is a field of the REQUEST, beside the
        # arguments, so a non-Python worker reads it like any other field.
        # It is present only when the host saw the handler ask for it, so
        # there is nothing to decide here.
        if "config" in req:
            kwargs["config"] = req["config"]
        out = target(*req.get("args", []), **kwargs)
        print(json.dumps({"ok": True, "value": out}, default=str))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                          "trace": traceback.format_exc()[-2000:]}))

main()
'''


@dataclass
class Worker:
    """One extension's out-of-process execution surface."""

    ext_id: str
    root: Path
    python: str
    extra_paths: tuple[str, ...] = ()
    timeout: float = DEFAULT_TIMEOUT

    def call(self, handler: str, *args, config: dict | None = None,
             **kwargs):
        """One JSON request in, one JSON response out.

        `config` (L.5, v0.84) is the extension's RESOLVED configuration and
        rides the request beside the arguments — never inside `kwargs`,
        because a non-Python worker reads it as a field of the request and
        not as a parameter of the call. `None` omits the key entirely, so a
        handler that did not ask for its settings gets the v0.83 request
        byte for byte.

        It is also the one place a declared secret crosses into another
        process (L.5 rule 2), which is why nothing here ever puts the
        request into an error, a log or a trace: the refusals below carry
        the child's stderr and the handler's name, and neither is the
        request.
        """
        body = {
            "root": str(self.root), "handler": handler,
            "paths": list(self.extra_paths),
            "args": list(args), "kwargs": kwargs,
        }
        if config is not None:
            body["config"] = config
        request = json.dumps(body)
        try:
            proc = subprocess.run(
                [self.python, "-c", _RUNNER], input=request,
                capture_output=True, text=True, timeout=self.timeout,
                cwd=str(self.root))
        except subprocess.TimeoutExpired:
            raise VineError(
                E_TIMEOUT,
                f"{self.ext_id}: {handler} exceeded {self.timeout:g}s",
                hint="MONKEYLLM_EXT_WORKER_TIMEOUT raises the wall clock",
            ) from None
        if proc.returncode != 0 or not proc.stdout.strip():
            # L.7 rule 5: a worker's death is a HANDLER failure. The caller
            # falls back; the host does not.
            raise VineError(
                E_EXT_WORKER, f"{self.ext_id}: {handler} did not answer",
                hint=(proc.stderr or "").strip()[-400:] or "no output")
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        if not payload.get("ok"):
            raise VineError(E_EXT_WORKER,
                            f"{self.ext_id}: {handler} raised",
                            hint=payload.get("error", "")[:400])
        return payload.get("value")


def interpreter_for(venv: Path) -> str:
    """The extension's own interpreter where it has one, this one otherwise.

    An extension with no third-party requirement needs no environment, and
    building one for it would be ceremony that buys nothing.
    """
    for candidate in (venv / "bin" / "python", venv / "Scripts" / "python.exe"):
        if candidate.exists():
            return str(candidate)
    return sys.executable
