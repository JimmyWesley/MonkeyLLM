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
import re
import subprocess
import zipfile
from pathlib import Path

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError

PAYLOAD_GLOBS = ("*.db", "*.sqlite")

# What a sidecar is allowed to contain, applied when unpacking one. The
# producer above writes only payloads, but a bundle arriving from outside was
# not necessarily produced here — J.13.2 already says an imported bundle
# "enters as it is: no converter, no curation and no review sees it" — and it
# is the consumer that decides what lands on disk.
#
# The extraction lands in a fresh git clone — a directory whose contents git
# itself reads and acts on afterwards, since the Station commits inside a
# forest on every plant, graft and tend. Discarding `..` is not a sufficient
# rule there, because reaching that directory needs no `..` at all. So the
# members are named positively — the payload files a sidecar exists to
# carry — instead of being filtered against known-bad shapes.
_SAFE_PAYLOAD_MEMBER = re.compile(r"^[\w\-. /]+\.(db|sqlite)$")

# An explicit ceiling on what a sidecar may expand to. Compressed archives
# expand at ratios a size limit on the upload cannot bound.
MAX_SIDECAR_UNCOMPRESSED = 2 * 1024 ** 3


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


def _accepted_members(zf: zipfile.ZipFile) -> list[str]:
    """The sidecar members that may be written, or a refusal naming the first
    one that may not.

    Refuse rather than skip: a sidecar carrying something else is not a
    sidecar with a stray file in it, it is an archive built by somebody who
    expected that file to land — and the operator is entitled to know before
    the forest is restored, not to discover a quietly incomplete restore.
    """
    accepted: list[str] = []
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if (name.startswith("/") or ".." in Path(name).parts
                or "\\" in name or not _SAFE_PAYLOAD_MEMBER.match(name)):
            raise VineError(
                E_SCHEMA, f"refused sidecar member: {name}",
                hint="A payload sidecar carries the forest's own database "
                     "files and nothing else.")
        total += info.file_size
        if total > MAX_SIDECAR_UNCOMPRESSED:
            raise VineError(
                E_SCHEMA, "sidecar expands past the uncompressed ceiling "
                          f"({MAX_SIDECAR_UNCOMPRESSED} bytes)")
        accepted.append(name)
    return accepted


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
            members = _accepted_members(zf)
            zf.extractall(dest, members=members)
            restored_payloads = len(members)

    # the derived layer is disposable — rebuild it fresh (C.6.1)
    from monkeyllm.catalog import Catalog
    from monkeyllm.forest import Forest

    catalog = Catalog(Forest(dest))
    nodes = catalog.reindex()
    catalog.close()
    return {"forest": str(dest), "nodes": nodes,
            "restored_payloads": restored_payloads}
