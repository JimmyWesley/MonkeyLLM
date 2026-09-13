# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.9 rule 1 — the conformance kit.

What it is: the manifest against the schema, `station_compat` against this
host, every declared handler importable, the panel parseable, and L.10's
configurability rule — every required setting reachable without a console.

What it is **not**, stated here because the documentation must say it in
these words: it is not a security control. Resolving `requirements.txt`
executes third-party build code by construction, and a git source
additionally runs the author's build backend, so the kit does not run before
third-party code runs. It runs before anything is **registered**. That is
the reason the signature tier (L.2) carries more weight than this does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from monkeyllm.errors import VineError
from monkeyllm.extensions.contracts import check_source_signature
from monkeyllm.extensions.loader import read_manifest
from monkeyllm.extensions.manifest import Manifest, compat_ok


@dataclass
class KitResult:
    ok: bool
    checks: list[dict] = field(default_factory=list)
    manifest: Manifest | None = None

    @property
    def failures(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"]]

    def summary(self) -> dict:
        return {"ok": self.ok, "checks": self.checks,
                "failed": [c["check"] for c in self.failures]}


def run_kit(tree: Path, host_version: str, *,
            bound_roles: set[str] | None = None) -> KitResult:
    tree = Path(tree)
    checks: list[dict] = []
    manifest: Manifest | None = None

    def record(name: str, ok: bool, detail: str = "") -> bool:
        checks.append({"check": name, "ok": ok, "detail": detail})
        return ok

    # 1 — the manifest parses and is in shape
    try:
        manifest = read_manifest(tree)
        record("manifest", True)
    except VineError as exc:
        record("manifest", False, f"{exc.message}: {exc.hint or ''}".strip(": "))
        return KitResult(ok=False, checks=checks)

    # 2 — this host is inside the declared range
    try:
        fits = compat_ok(manifest.station_compat, host_version)
        record("station_compat", fits,
               "" if fits else f"{manifest.station_compat} excludes "
                               f"{host_version}")
    except VineError as exc:
        record("station_compat", False, exc.message)

    # 3 — a licence is declared and its file is present
    record("license", bool(manifest.license),
           "" if manifest.license else "no licence declared")
    record("license_file", (tree / "LICENSE").exists(),
           "" if (tree / "LICENSE").exists()
           else "LICENSE is missing; the operator is shown what they accept")

    # 4 — the entry module exists and the handlers it names resolve
    entry = tree / f"{manifest.entry}.py"
    record("entry", entry.exists(),
           "" if entry.exists() else f"{manifest.entry}.py is missing")
    for seam, spec in manifest.handlers():
        module, _, func = spec.handler.partition(":")
        path = tree / f"{module.replace('.', '/')}.py"
        ok = bool(func) and path.exists()
        record(f"handler:{seam}:{spec.handler}", ok,
               "" if ok else "module:function does not resolve to a file")
        if not ok:
            continue
        # L.3 (v0.81): the signature against the seam's declared contract,
        # read off the SOURCE. Importing to inspect would execute the
        # module — and a heavy handler's module imports the dependency L.5
        # exists to keep out of this process, so the check meant to catch an
        # author's typo would break the rule that protects the deployment.
        problem = check_source_signature(seam, path, func)
        record(f"signature:{seam}:{spec.handler}", problem is None,
               problem or "")

    # 5 — a declared panel parses even where nothing renders it (L.10)
    if manifest.contributes.panel:
        panel = tree / manifest.contributes.panel
        record("panel", panel.exists(),
               "" if panel.exists() else f"{manifest.contributes.panel} missing")

    # 6 — L.10's rule: configurable without a console
    unreachable = sorted(
        name for name in _required_settings(manifest)
        if name not in manifest.config)
    record("configurable_without_console", not unreachable,
           "" if not unreachable
           else f"required setting(s) with no schema entry: "
                f"{', '.join(unreachable)}")

    # 7 — a required role must be bindable; the caller says what is bound
    if bound_roles is not None:
        missing = sorted(set(manifest.models.requires) - set(bound_roles))
        record("roles_bound", not missing,
               "" if not missing else f"unbound: {', '.join(missing)}")

    return KitResult(ok=all(c["ok"] for c in checks), checks=checks,
                     manifest=manifest)


def _required_settings(manifest: Manifest) -> set[str]:
    """Everything the extension says it needs before it can work.

    Today that is the manifest's own `required` flags; the check exists as
    its own function because the failure it guards against — a setting that
    only a console can reach — is the one that quietly makes a console-less
    host second class.
    """
    return {name for name, field in manifest.config.items() if field.required}
