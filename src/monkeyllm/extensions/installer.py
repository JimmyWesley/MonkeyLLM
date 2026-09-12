# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.2 / L.8 / L.9 — install, update, uninstall.

The order here is the contract, not an implementation detail:

    resolve to an immutable artifact  ->  conformance kit  ->  tier decision
    ->  operator acknowledgement  ->  environment  ->  stage  ->  record

Nothing is staged before the kit passes (F.174: a failing manifest installs
**nothing** — no environment, no record, no registration), and nothing is
recorded before the operator has been shown the licence, the source and the
tier (L.9 rule 4).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.extensions import sources
from monkeyllm.extensions.conformance import KitResult, run_kit
from monkeyllm.extensions.sources import (E_EXT_INSTALL, TIER_UNVERIFIED,
                                          Resolved)
from monkeyllm.extensions.store import Install, Store


@dataclass
class InstallPlan:
    """What the operator is being asked to accept, before anything happens."""

    resolved: Resolved
    kit: KitResult

    @property
    def manifest(self):
        return self.kit.manifest

    def to_dict(self) -> dict:
        m = self.manifest
        out = {
            "kit": self.kit.summary(),
            **self.resolved.record(),
        }
        if m:
            out.update({
                "id": m.id, "version": m.version, "license": m.license,
                "permissions": m.permissions.model_dump(),
                "requires_roles": list(m.models.requires),
                "registers_roles": [r.model_dump()
                                    for r in m.models.registers],
                "contributes": {
                    seam: len(getattr(m.contributes, seam))
                    for seam in ("converters", "curation", "events", "jobs",
                                 "tools", "routes", "ranking", "prompt")
                    if getattr(m.contributes, seam)
                },
            })
            if m.contributes.panel:
                out["contributes"]["panel"] = 1
        return out


def plan(source: str, host_version: str, *, workdir: Path | None = None,
         index: dict | None = None, verify: bool = True,
         bound_roles: set[str] | None = None) -> tuple[InstallPlan, Path]:
    """Resolve and validate without touching the store.

    Returns the plan and the temporary directory holding the artifact; the
    caller owns cleaning it up. Split from `install` so a console can show
    exactly what a confirmation would accept.
    """
    tmp = Path(workdir or tempfile.mkdtemp(prefix="monkeyllm-ext-"))
    resolved = sources.resolve(source, tmp, index=index, verify=verify)
    kit = run_kit(resolved.root, host_version, bound_roles=bound_roles)
    return InstallPlan(resolved=resolved, kit=kit), tmp


def install(source: str, host_version: str, *, store: Store | None = None,
            acknowledge_unverified: bool = False, index: dict | None = None,
            verify: bool = True, bound_roles: set[str] | None = None,
            build_env: bool = True) -> dict:
    store = store or Store()
    prepared, tmp = plan(source, host_version, index=index, verify=verify,
                         bound_roles=bound_roles)
    try:
        return _finish(prepared, store, acknowledge_unverified, build_env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _finish(prepared: InstallPlan, store: Store, acknowledged: bool,
            build_env: bool) -> dict:
    kit, resolved = prepared.kit, prepared.resolved

    # F.174 — nothing is staged when the kit fails.
    if not kit.ok:
        raise VineError(
            E_EXT_INSTALL, "the extension did not pass the conformance kit",
            hint="; ".join(f"{c['check']}: {c['detail']}".rstrip(": ")
                           for c in kit.failures)[:400],
            data={"reason": "kit", "failed": [c["check"] for c in kit.failures],
                  "checks": kit.checks})

    manifest = kit.manifest
    previous = store.get(manifest.id)

    # L.2 rule 3 — an extension never changes tier quietly.
    if previous and previous.tier != TIER_UNVERIFIED \
            and resolved.tier == TIER_UNVERIFIED and not acknowledged:
        raise VineError(
            E_EXT_INSTALL,
            f"{manifest.id} was {previous.tier} and this source is unverified",
            hint=resolved.reason or "acknowledge to accept the downgrade",
            data={"reason": "tier_downgrade", "was": previous.tier})

    # L.2 rule 4 — a changed verifying identity is surfaced, never accepted.
    if previous and previous.identity and resolved.identity and \
            previous.identity.get("account") != resolved.identity.get("account") \
            and not acknowledged:
        raise VineError(
            E_EXT_INSTALL,
            f"{manifest.id} now verifies as "
            f"{resolved.identity.get('account')!r}, not "
            f"{previous.identity.get('account')!r}",
            hint="a repo transfer or a key rotation; acknowledge to accept it",
            data={"reason": "identity_changed",
                  "was": previous.identity, "now": resolved.identity})

    # L.9 rule 4 — an unverified source installs only on an explicit act.
    if resolved.tier == TIER_UNVERIFIED and not acknowledged:
        raise VineError(
            E_EXT_INSTALL,
            f"{manifest.id} is unverified",
            hint=resolved.reason or "no signature could be checked",
            data={"reason": "unverified", "tier": resolved.tier,
                  "detail": resolved.reason})

    # Only now does anything land on disk.
    tree = store.stage(manifest.id, resolved.root)
    env = _build_env(store, manifest.id, tree) if build_env else None

    record = Install(
        id=manifest.id, version=manifest.version, tier=resolved.tier,
        source=resolved.source, kind=resolved.kind,
        installed_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        license=manifest.license, revision=resolved.revision,
        tracking=resolved.tracking, identity=resolved.identity,
        reason=resolved.reason, acknowledged=acknowledged,
        permissions=manifest.permissions.model_dump())
    store.put(record)

    # L.8 — a reinstall recovers what uninstall quarantined.
    recovered = store.recover_config(manifest.id)

    return {
        "installed": True, "id": manifest.id, "version": manifest.version,
        "tier": resolved.tier, "tracking": resolved.tracking,
        "revision": resolved.revision, "license": manifest.license,
        "environment": str(env) if env else None,
        "config_recovered": sorted(recovered) or None,
        "restart_required": True,   # L.8: stated, never implied
        "kit": kit.summary(),
    }


def _build_env(store: Store, ext_id: str, tree: Path) -> Path | None:
    """L.5 — the extension's own environment, and only where it asked.

    An extension with no third-party requirement needs no environment;
    building one anyway would be ceremony that buys nothing and costs every
    install a hundred megabytes.
    """
    reqs = tree / "requirements.txt"
    if not reqs.exists() or not reqs.read_text(encoding="utf-8").strip():
        return None
    venv = store.venv(ext_id)
    if not venv.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True,
                       capture_output=True)
    python = venv / "bin" / "python"
    if not python.exists():
        python = venv / "Scripts" / "python.exe"
    proc = subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", "-r", str(reqs)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        shutil.rmtree(venv, ignore_errors=True)
        raise VineError(E_EXT_INSTALL,
                        f"{ext_id}: dependencies could not be installed",
                        hint=(proc.stderr or proc.stdout).strip()[-400:],
                        data={"reason": "requirements"})
    return venv


def update(ext_id: str, host_version: str, *, store: Store | None = None,
           **kwargs) -> dict:
    """F.192 — a failed update leaves the previous install untouched.

    The mechanism is the order: resolve and validate the new artifact
    completely before the old tree is replaced, and let any refusal happen
    while the old one is still the installed one.
    """
    store = store or Store()
    previous = store.require(ext_id)
    return install(previous.source, host_version, store=store, **kwargs)


def uninstall(ext_id: str, *, store: Store | None = None,
              forests: list[Path] | None = None) -> dict:
    """L.8 — the forest is not touched, and what will start being refused
    is named before this is called (the caller shows `dialect_impact`)."""
    store = store or Store()
    store.require(ext_id)
    quarantined = store.quarantine_config(ext_id)
    store.remove_tree(ext_id)
    store.drop(ext_id)
    return {"uninstalled": True, "id": ext_id,
            "config_quarantined": bool(quarantined),
            "restart_required": True}


def dialect_impact(ext_id: str, store: Store | None = None) -> dict:
    """L.8 — every `type`/`rel` that will start being refused (A.2).

    Computed against the OTHER installed extensions, because a token two
    extensions declare survives one of them leaving.
    """
    store = store or Store()
    from monkeyllm.extensions.loader import read_manifest
    mine, others = set(), set()
    for record in store.list():
        try:
            manifest = read_manifest(store.tree(record.id))
        except VineError:
            continue
        tokens = set(manifest.permissions.capabilities)
        (mine if record.id == ext_id else others).update(tokens)
    return {"id": ext_id, "losing": sorted(mine - others)}
