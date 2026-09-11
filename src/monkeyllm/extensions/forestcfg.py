# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.12 — per-forest enablement lives in the forest, and is versioned.

`_meta/extensions.yaml` is git-tracked like the rest of `_meta/`, so a
forest carries **which extensions it expects**, a snapshot takes them along,
and `validate` can say "this forest expects `whisper` and it is not
installed" instead of quietly converting an `.mp3` with the built-in stub.

Two rules make that safe:

- **`_meta` declares expectation and never grants it.** An expectation the
  deployment has not installed is a health report line, never an install.
- **A declared secret may not be written here.** `_meta/` is versioned; a
  key committed to a forest's git is a key in every clone of it forever.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from monkeyllm.errors import E_SCHEMA, VineError

FILENAME = "extensions.yaml"


def path_for(forest_root: Path) -> Path:
    return Path(forest_root) / "_meta" / FILENAME


def read(forest_root: Path) -> dict:
    path = path_for(forest_root)
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise VineError(E_SCHEMA, f"{FILENAME} must be a mapping",
                        hint=f"got {type(raw).__name__}")
    return (raw.get("extensions") or {}) if "extensions" in raw else raw


def expected(forest_root: Path) -> list[str]:
    """Every extension this forest expects, enabled or not."""
    return sorted(read(forest_root))


def enabled(forest_root: Path) -> list[str]:
    cfg = read(forest_root)
    return sorted(k for k, v in cfg.items()
                  if (v or {}).get("enabled", True) is not False)


def write(forest_root: Path, config: dict,
          secret_fields: dict[str, set[str]] | None = None,
          message: str = "extensions: update enablement") -> Path:
    """Persist the enablement map, refusing any declared secret.

    The refusal is the point: `_meta/` is versioned, so this is the one
    place where a well-meaning "just put the key with the setting" becomes
    permanent and public.
    """
    secret_fields = secret_fields or {}
    for ext_id, entry in (config or {}).items():
        settings = (entry or {}).get("config") or {}
        offending = sorted(set(settings) & set(secret_fields.get(ext_id, ())))
        if offending:
            raise VineError(
                E_SCHEMA,
                f"{ext_id}: {FILENAME} may not carry a declared secret "
                f"({', '.join(offending)})",
                hint="_meta/ is versioned; a secret belongs in the host's "
                     "config store or the environment",
                data={"fields": offending})
    path = path_for(forest_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({"extensions": config}, sort_keys=True,
                          allow_unicode=True)
    path.write_text(body, encoding="utf-8", newline="\n")
    _commit(Path(forest_root), path, message)
    return path


def _commit(forest_root: Path, path: Path, message: str) -> None:
    """Written and COMMITTED, or the file is versioned in name only.

    L.12 says enablement travels in a Part I snapshot, and a snapshot is a
    git bundle — an untracked file does not travel in one. Best effort: a
    forest that is not a git repository (a bare directory in a test) is
    still a forest whose enablement must be readable.
    """
    if not (forest_root / ".git").exists():
        return
    try:
        from monkeyllm.gitops import GitRepo
        GitRepo(forest_root).commit_meta([path], message)
    except Exception:
        # Never fail an enablement because git refused; the file on disk is
        # what the loader reads, and the operator can commit it by hand.
        pass


def enable(forest_root: Path, ext_id: str, **entry) -> Path:
    cfg = read(forest_root)
    cfg[ext_id] = {**(cfg.get(ext_id) or {}), "enabled": True, **entry}
    return write(forest_root, cfg, message=f"extensions: enable {ext_id}")


def disable(forest_root: Path, ext_id: str) -> Path:
    cfg = read(forest_root)
    if ext_id in cfg:
        cfg[ext_id] = {**(cfg[ext_id] or {}), "enabled": False}
    return write(forest_root, cfg, message=f"extensions: disable {ext_id}")


def forget(forest_root: Path, ext_id: str) -> Path:
    cfg = read(forest_root)
    cfg.pop(ext_id, None)
    return write(forest_root, cfg, message=f"extensions: forget {ext_id}")
