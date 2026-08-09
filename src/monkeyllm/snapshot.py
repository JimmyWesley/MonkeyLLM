# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Part I (spec v0.11) — forest snapshots: one file, full history.

A snapshot is the forest's git repository packaged as a `git bundle`: every
plant/tend/gardener/ranger commit travels along, verifiable, restorable
with plain git. Payload binaries are NOT inside (they are not in git,
A.3.1); `--with-payloads` adds a sidecar zip.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import zipfile
from pathlib import Path

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError

PAYLOAD_GLOBS = ("*.db", "*.sqlite")


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def create_snapshot(forest_root: Path, out: Path | None = None,
                    with_payloads: bool = False) -> dict:
    root = Path(forest_root).resolve()
    if not (root / ".git").exists():
        raise VineError(E_SCHEMA, f"not a forest git repo: {root}",
                        hint="Snapshots package the forest's own git history.")
    stamp = dt.date.today().isoformat()
    out = Path(out) if out else root.parent / f"{root.name}-{stamp}.bundle"
    out.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "bundle", "create", str(out), "--all")
    result = {"bundle": str(out), "bytes": out.stat().st_size}

    if with_payloads:
        sidecar = out.with_suffix(out.suffix + ".payloads.zip")
        n = 0
        with zipfile.ZipFile(sidecar, "w", zipfile.ZIP_DEFLATED) as zf:
            for glob in PAYLOAD_GLOBS:
                for p in sorted(root.rglob(glob)):
                    if "_derived" in p.parts:
                        continue
                    zf.write(p, p.relative_to(root).as_posix())
                    n += 1
        result["payload_sidecar"] = str(sidecar)
        result["payloads"] = n
    return result


def restore_snapshot(bundle: Path, dest: Path,
                     payload_sidecar: Path | None = None) -> dict:
    bundle = Path(bundle).resolve()
    dest = Path(dest).resolve()
    if not bundle.is_file():
        raise VineError(E_NOT_FOUND, f"bundle not found: {bundle}")
    if dest.exists() and any(dest.iterdir()):
        raise VineError(E_SCHEMA, f"restore target is not empty: {dest}",
                        hint="Refusing to overwrite — pick a fresh directory.")
    subprocess.run(["git", "clone", "--quiet", str(bundle), str(dest)],
                   capture_output=True, text=True, check=True)
    restored_payloads = 0
    if payload_sidecar:
        with zipfile.ZipFile(payload_sidecar) as zf:
            zf.extractall(dest)
            restored_payloads = len(zf.namelist())

    # the derived layer is disposable — rebuild it fresh (C.6.1)
    from monkeyllm.catalog import Catalog
    from monkeyllm.forest import Forest

    catalog = Catalog(Forest(dest))
    nodes = catalog.reindex()
    catalog.close()
    return {"forest": str(dest), "nodes": nodes,
            "restored_payloads": restored_payloads}
