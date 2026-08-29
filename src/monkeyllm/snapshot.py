# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Part I (spec v0.11; the container, v0.74) — forest snapshots: one file.

A snapshot is a **container**: a zip carrying the forest's git repository
as a `git bundle` (every plant/tend/gardener/ranger commit, verifiable and
clonable by git alone), the payload bytes git cannot hold (A.3.1), and a
README saying how to open the whole thing without this software.

It was two files between v0.11 and v0.74 — a bundle plus an *optional*
payload sidecar — and they came apart in the field, silently, because
nothing tied them and nothing counted the loss. What is read back here is
decided by the file's CONTENT, so every snapshot written before v0.74
still restores.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError

CONTAINER_SUFFIX = ".forest"
BUNDLE_MEMBER = "forest.bundle"
README_MEMBER = "README.txt"
PAYLOAD_PREFIX = "payloads/"

# The BONE tier (A.3.1): what git is not allowed to hold, and therefore
# everything a bundle cannot carry. `_assets/` is here as of v0.74 — it is
# in the forest's own `.gitignore` and was in no sidecar either, so a
# `type: media` node survived no snapshot at all.
PAYLOAD_GLOBS = ("*.db", "*.sqlite")
ASSETS_DIR = "_assets"
_SKIP_DIRS = {"_derived", ".git"}

# What a legacy sidecar is allowed to contain, applied when unpacking one.
# The producer wrote only payloads, but an archive arriving from outside
# was not necessarily produced here — J.13.2 already says an imported
# bundle "enters as it is: no converter, no curation and no review sees
# it" — and it is the consumer that decides what lands on disk.
#
# The extraction lands in a fresh git clone — a directory whose contents
# git itself reads and acts on afterwards, since the Station commits inside
# a forest on every plant, graft and tend. Discarding `..` is not a
# sufficient rule there, because reaching that directory needs no `..` at
# all. So the members are named positively — the payload files an archive
# exists to carry — instead of being filtered against known-bad shapes.
_SAFE_PAYLOAD_MEMBER = re.compile(r"^[\w\-. /]+\.(db|sqlite)$")

# An explicit ceiling on what an archive may expand to. Compressed archives
# expand at ratios a size limit on the upload cannot bound.
MAX_SIDECAR_UNCOMPRESSED = 2 * 1024 ** 3

_README = """MonkeyLLM forest snapshot: {name} ({stamp})

This file is a ZIP archive, and nothing inside it needs MonkeyLLM to read:

    unzip <this file>
    git clone {bundle} {name}

That gives you the forest back as ordinary Markdown files, with its full
commit history. A backup nobody can open without the vendor is not a
backup, which is why the history travels as a plain git bundle and why
these two commands are written down here rather than assumed.

Dataset databases and media live under {prefix} at the paths they occupy
inside the forest — git does not carry binaries (spec A.3.1), so they ride
beside the bundle instead of in it. Copy them over the clone:

    cp -R {prefix}. {name}/

A snapshot taken without payloads has no {prefix} directory at all.
"""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True)


def _payload_files(root: Path) -> list[Path]:
    """The payload bytes a snapshot must carry because git will not.

    Dataset databases anywhere in the tree, plus everything under any
    `_assets/`: the Gardener archives media under the OWNING BRANCH's
    `_assets/` (G.5.1), so this is a directory name at any depth and never
    one directory at the root. `_derived/` is excluded because it is
    disposable by contract (C.6.1) and `reindex` is its repair.
    """
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        if ASSETS_DIR in here.relative_to(root).parts:
            out.extend(here / f for f in filenames)
            continue
        out.extend(here / f for f in filenames
                   if any(fnmatch(f, g) for g in PAYLOAD_GLOBS))
    return sorted(out)


def create_snapshot(forest_root: Path, out: Path | None = None,
                    with_payloads: bool = True) -> dict:
    """One file: the bundle, the payloads, and the note that opens both.

    `with_payloads` defaults TRUE as of v0.74. A snapshot that omits the
    payloads is the only kind that loses data, and it was the default; it
    is a legitimate artifact (a metadata-only backup is a real thing) but
    it MUST be chosen, and the count left behind is reported so that
    `payloads: 0` never means both *this forest has none* and *you did not
    ask*.
    """
    root = Path(forest_root).resolve()
    if not (root / ".git").exists():
        raise VineError(E_SCHEMA, f"not a forest git repo: {root}",
                        hint="Snapshots package the forest's own git history.")
    stamp = dt.date.today().isoformat()
    out = Path(out) if out else root.parent / f"{root.name}-{stamp}{CONTAINER_SUFFIX}"
    out.parent.mkdir(parents=True, exist_ok=True)

    payloads = _payload_files(root)
    with tempfile.TemporaryDirectory() as tmp:
        # Built outside the forest: a bundle written into the tree would be
        # a binary where A.3.1 keeps binaries out, and the next snapshot
        # would package the previous one.
        bundle = Path(tmp) / BUNDLE_MEMBER
        _git(root, "bundle", "create", str(bundle), "--all")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(README_MEMBER, _README.format(
                name=root.name, stamp=stamp,
                bundle=BUNDLE_MEMBER, prefix=PAYLOAD_PREFIX))
            zf.write(bundle, BUNDLE_MEMBER)
            if with_payloads:
                for p in payloads:
                    zf.write(p, PAYLOAD_PREFIX + p.relative_to(root).as_posix())

    return {"snapshot": str(out), "bytes": out.stat().st_size,
            "payloads": len(payloads) if with_payloads else 0,
            "payloads_omitted": 0 if with_payloads else len(payloads)}


def is_container(path: Path) -> bool:
    """Container or bare bundle, decided by the file's content (v0.74).

    The bundle signature sits at offset 0 and cannot be mistaken, while a
    zip's end-of-central-directory is searched from the tail and a packfile
    is arbitrary bytes — so the bundle is asked FIRST. Never the filename:
    that arrived with the request, and on the import route (J.13.2) it is a
    claim by whoever is importing.
    """
    with Path(path).open("rb") as fh:
        head = fh.read(16)
    if head.startswith(b"# v") and b"git bundle" in head:
        return False
    return zipfile.is_zipfile(path)


def _refuse(name: str) -> None:
    raise VineError(
        E_SCHEMA, f"refused snapshot member: {name}",
        hint=f"A snapshot carries {BUNDLE_MEMBER}, {README_MEMBER} and the "
             f"forest's own payload files under {PAYLOAD_PREFIX} — nothing "
             f"else.")


def _check_container_member(name: str) -> None:
    """The v0.50 positive naming, widened to `_assets/` and no further.

    Widening is where such a rule gets lost, so the shape is spelled out:
    a member lands under `payloads/` and nowhere else, and inside that it
    is a dataset database or a file under an `_assets/`, because those two
    are exactly what A.3.1 keeps out of git.

    The dot-component clause is the one that is easy to omit and expensive
    to omit: `payloads/.git/config` reaches the repository git reads on the
    next commit without using a single relative segment.
    """
    if not name.startswith(PAYLOAD_PREFIX) or "\\" in name:
        _refuse(name)
    rel = name[len(PAYLOAD_PREFIX):]
    if not rel or rel.startswith("/"):
        _refuse(name)
    parts = PurePosixPath(rel).parts
    if not parts or any(p == ".." or p.startswith(".") for p in parts):
        _refuse(name)
    if not (rel.endswith((".db", ".sqlite")) or ASSETS_DIR in parts):
        _refuse(name)


def _accepted(zf: zipfile.ZipFile, *, container: bool) -> list[str]:
    """The members that may be written, or a refusal naming the first that
    may not.

    Refuse rather than skip: an archive carrying something else is not an
    archive with a stray file in it, it is an archive built by somebody who
    expected that file to land — and the operator is entitled to know
    before the forest is restored, not to discover a quietly incomplete
    restore.
    """
    accepted: list[str] = []
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if container:
            if name in (BUNDLE_MEMBER, README_MEMBER):
                continue
            _check_container_member(name)
        elif (name.startswith("/") or ".." in Path(name).parts
                or "\\" in name or not _SAFE_PAYLOAD_MEMBER.match(name)):
            _refuse(name)
        total += info.file_size
        if total > MAX_SIDECAR_UNCOMPRESSED:
            raise VineError(
                E_SCHEMA, "snapshot expands past the uncompressed ceiling "
                          f"({MAX_SIDECAR_UNCOMPRESSED} bytes)")
        accepted.append(name)
    return accepted


def _clone(bundle: Path, dest: Path) -> None:
    subprocess.run(["git", "clone", "--quiet", str(bundle), str(dest)],
                   capture_output=True, text=True, check=True)


def _extract(zf: zipfile.ZipFile, member: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(member) as src, target.open("wb") as out:
        shutil.copyfileobj(src, out)


def restore_snapshot(snapshot: Path, dest: Path,
                     payload_sidecar: Path | None = None) -> dict:
    """A forest from a snapshot, and an honest count of what did not arrive.

    `payloads_missing` is the passports naming a LOCAL payload the
    filesystem does not have — not how many payload files were unpacked,
    which describes the archive, but how many nodes are dead, which
    describes the forest. Producing them is allowed (a pre-v0.74 bare
    bundle has none to give, and refusing would make yesterday's backups
    unrestorable); producing them in silence is not.
    """
    snapshot = Path(snapshot).resolve()
    dest = Path(dest).resolve()
    if not snapshot.is_file():
        raise VineError(E_NOT_FOUND, f"snapshot not found: {snapshot}")
    if dest.exists() and any(dest.iterdir()):
        raise VineError(E_SCHEMA, f"restore target is not empty: {dest}",
                        hint="Refusing to overwrite — pick a fresh directory.")

    restored = 0
    if is_container(snapshot):
        with zipfile.ZipFile(snapshot) as zf:
            if BUNDLE_MEMBER not in zf.namelist():
                raise VineError(
                    E_SCHEMA, f"snapshot carries no {BUNDLE_MEMBER}",
                    hint="Is this a Part I snapshot?")
            # Every member judged before anything lands (J.13.2).
            members = _accepted(zf, container=True)
            with tempfile.TemporaryDirectory() as tmp:
                bundle = Path(tmp) / BUNDLE_MEMBER
                _extract(zf, BUNDLE_MEMBER, bundle)
                _clone(bundle, dest)
            for name in members:
                _extract(zf, name, dest / name[len(PAYLOAD_PREFIX):])
                restored += 1
    else:
        _clone(snapshot, dest)
        if payload_sidecar:
            with zipfile.ZipFile(payload_sidecar) as zf:
                members = _accepted(zf, container=False)
                zf.extractall(dest, members=members)
                restored = len(members)

    # the derived layer is disposable — rebuild it fresh (C.6.1)
    from monkeyllm.catalog import Catalog, count_missing_payloads
    from monkeyllm.forest import Forest

    forest = Forest(dest)
    catalog = Catalog(forest)
    nodes = catalog.reindex()
    missing = count_missing_payloads(catalog, forest)
    catalog.close()
    return {"forest": str(dest), "nodes": nodes,
            "restored_payloads": restored, "payloads_missing": missing}
