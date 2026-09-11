# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.12 / L.8 — where an installation lives, and what survives removing it.

Global install is a **host-level directory**, never `_derived/`: that tree is
declaredly disposable and `reindex` is entitled to delete it, so an
installation living there would evaporate on a repair.

Uninstall quarantines config rather than deleting it (L.8). A failed upgrade
has to be recoverable, and a secret that outlives its extension while being
visible to nobody is the worst of both choices — so quarantine expires and
is listable.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from monkeyllm.errors import E_NOT_FOUND, VineError

QUARANTINE_DAYS = 90


def ext_home() -> Path:
    """The host-level directory. One env var, because a deployment that
    relocates its data directory relocates this with it."""
    raw = os.environ.get("MONKEYLLM_EXT_HOME")
    root = Path(raw).expanduser() if raw else Path.home() / ".monkeyllm" / "extensions"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class Install:
    id: str
    version: str
    tier: str
    source: str
    kind: str
    installed_at: str
    license: str = ""
    revision: str | None = None
    tracking: str | None = None
    identity: dict | None = None
    reason: str | None = None
    acknowledged: bool = False
    permissions: dict | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, raw: dict) -> "Install":
        known = {k: raw.get(k) for k in cls.__dataclass_fields__}
        known["id"] = raw["id"]
        return cls(**{k: v for k, v in known.items() if v is not None or
                      k in ("id", "version", "tier", "source", "kind",
                            "installed_at")})


class Store:
    """The install register. A JSON file, because the engine's own hosts
    include one with no database at all."""

    def __init__(self, root: Path | None = None):
        self.root = root or ext_home()
        self.root.mkdir(parents=True, exist_ok=True)
        self.records = self.root / "installed.json"
        self.quarantine = self.root / "quarantine"

    # -- records -----------------------------------------------------------

    def _read(self) -> dict:
        if not self.records.exists():
            return {}
        try:
            return json.loads(self.records.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.records.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True),
                       encoding="utf-8")
        tmp.replace(self.records)

    def list(self) -> list[Install]:
        return [Install.from_dict(r) for r in
                sorted(self._read().values(), key=lambda r: r["id"])]

    def get(self, ext_id: str) -> Install | None:
        raw = self._read().get(ext_id)
        return Install.from_dict(raw) if raw else None

    def put(self, install: Install) -> None:
        data = self._read()
        data[install.id] = install.to_dict()
        self._write(data)

    def drop(self, ext_id: str) -> None:
        data = self._read()
        data.pop(ext_id, None)
        self._write(data)

    # -- trees -------------------------------------------------------------

    def tree(self, ext_id: str) -> Path:
        return self.root / ext_id / "tree"

    def venv(self, ext_id: str) -> Path:
        return self.root / ext_id / "venv"

    def stage(self, ext_id: str, source_tree: Path) -> Path:
        dest = self.tree(ext_id)
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_tree, dest)
        return dest

    def remove_tree(self, ext_id: str) -> None:
        shutil.rmtree(self.root / ext_id, ignore_errors=True)

    # -- config ------------------------------------------------------------

    def config_path(self, ext_id: str) -> Path:
        return self.root / ext_id / "config.json"

    def read_config(self, ext_id: str) -> dict:
        path = self.config_path(ext_id)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_config(self, ext_id: str, values: dict) -> None:
        path = self.config_path(ext_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values, indent=2, sort_keys=True),
                        encoding="utf-8")
        os.chmod(path, 0o600)

    # -- quarantine (L.8) --------------------------------------------------

    def quarantine_config(self, ext_id: str) -> Path | None:
        values = self.read_config(ext_id)
        if not values:
            return None
        self.quarantine.mkdir(parents=True, exist_ok=True)
        dest = self.quarantine / f"{ext_id}.json"
        dest.write_text(json.dumps(
            {"id": ext_id, "quarantined_at": time.time(), "config": values},
            indent=2, sort_keys=True), encoding="utf-8")
        os.chmod(dest, 0o600)
        return dest

    def recover_config(self, ext_id: str) -> dict:
        path = self.quarantine / f"{ext_id}.json"
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        age_days = (time.time() - raw.get("quarantined_at", 0)) / 86400
        if age_days > QUARANTINE_DAYS:
            path.unlink(missing_ok=True)
            return {}
        values = raw.get("config") or {}
        if values:
            self.write_config(ext_id, values)
        path.unlink(missing_ok=True)
        return values

    def list_quarantine(self) -> list[dict]:
        """A quarantined secret nobody can see is the failure this answers."""
        if not self.quarantine.exists():
            return []
        out = []
        for path in sorted(self.quarantine.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            at = raw.get("quarantined_at", 0)
            age = (time.time() - at) / 86400
            out.append({"id": raw.get("id", path.stem),
                        "quarantined_at": at,
                        "expires_in_days": round(QUARANTINE_DAYS - age, 1),
                        "fields": sorted((raw.get("config") or {}).keys())})
        return out

    def expire_quarantine(self) -> list[str]:
        dropped = []
        for entry in self.list_quarantine():
            if entry["expires_in_days"] <= 0:
                (self.quarantine / f"{entry['id']}.json").unlink(missing_ok=True)
                dropped.append(entry["id"])
        return dropped

    # -- lookups -----------------------------------------------------------

    def require(self, ext_id: str) -> Install:
        install = self.get(ext_id)
        if not install:
            raise VineError(E_NOT_FOUND, f"extension not installed: {ext_id}",
                            hint="`vine ext list` shows what is installed")
        return install
