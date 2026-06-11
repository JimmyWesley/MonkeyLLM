"""G.9 — payload fetchers (spec v0.11): remote BONE, resolved on first use.

`payload` (and future remote references) MAY carry a URI scheme. Plain
paths mean local sibling files (zero change). Remote URIs resolve through
a hash-validated cache in `_derived/payloads/` — a corrupted or tampered
download never reaches the agent. The Ranger evicts cold entries (H.6).

Schemes: `file://` (built-in — also the test double for object storage)
and `s3://` (optional extra: boto3, MIT; `MONKEYLLM_S3_ENDPOINT` points to
S3-compatible stores like MinIO/R2).
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError

SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://")
CACHE_FLOOR_BYTES = 1  # evict() never drops below "keep nothing" semantics


def is_remote(ref) -> bool:
    return bool(ref) and bool(SCHEME_RE.match(str(ref)))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local_path(uri: str) -> Path:
    return Path(url2pathname(urlparse(uri).path))


def _fetch_file(uri: str, dest: Path) -> None:
    src = _local_path(uri)
    if not src.is_file():
        raise VineError(E_NOT_FOUND, f"remote payload not found: {uri}")
    shutil.copyfile(src, dest)


def _s3_client():
    try:
        import boto3
    except ImportError as e:
        raise VineError(
            E_SCHEMA,
            "s3:// payloads need boto3 (optional extra)",
            hint="pip install boto3 — credentials via the standard AWS env vars; "
                 "MONKEYLLM_S3_ENDPOINT for S3-compatible stores (MinIO/R2).",
        ) from e
    endpoint = os.environ.get("MONKEYLLM_S3_ENDPOINT")
    return boto3.client("s3", endpoint_url=endpoint or None)


def _fetch_s3(uri: str, dest: Path) -> None:
    parsed = urlparse(uri)
    _s3_client().download_file(parsed.netloc, parsed.path.lstrip("/"), str(dest))


FETCHERS = {"file": _fetch_file, "s3": _fetch_s3}


def upload(path: Path, uri: str) -> None:
    """Push a local file to a remote URI (snapshots' `--to`, Part I)."""
    scheme = urlparse(uri).scheme
    if scheme == "file":
        dest = _local_path(uri)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        return
    if scheme == "s3":
        parsed = urlparse(uri)
        _s3_client().upload_file(str(path), parsed.netloc, parsed.path.lstrip("/"))
        return
    raise VineError(E_SCHEMA, f"unsupported upload scheme: {scheme}://")


class PayloadCache:
    """Hash-validated, LRU-evictable cache for remote payloads (G.9/H.6)."""

    def __init__(self, derived_dir: Path):
        self.dir = Path(derived_dir) / "payloads"

    def _slot(self, uri: str) -> Path:
        name = Path(urlparse(uri).path).name or "payload"
        return self.dir / f"{hashlib.sha256(uri.encode()).hexdigest()[:16]}-{name}"

    def get(self, uri: str, expected_hash: str | None = None) -> Path:
        slot = self._slot(uri)
        if slot.is_file():
            if expected_hash is None or _sha256(slot) == expected_hash:
                os.utime(slot, None)  # LRU touch (H.6 reads mtime)
                return slot
            slot.unlink()  # upstream changed: refetch
        scheme = urlparse(uri).scheme
        fetch = FETCHERS.get(scheme)
        if fetch is None:
            raise VineError(E_SCHEMA, f"unsupported payload scheme: {scheme}://")
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = slot.with_suffix(slot.suffix + ".part")
        try:
            fetch(uri, tmp)
            if expected_hash and _sha256(tmp) != expected_hash:
                raise VineError(
                    E_SCHEMA,
                    f"remote payload hash mismatch: {uri}",
                    hint="The remote object does not match payload_hash — "
                         "out of date or tampered. Refusing to serve it.",
                )
            tmp.replace(slot)
        finally:
            tmp.unlink(missing_ok=True)
        return slot

    def evict(self, max_gb: float) -> dict:
        """H.6: LRU eviction — always safe, every entry is re-fetchable."""
        if not self.dir.is_dir():
            return {"evicted": 0, "kept_bytes": 0}
        files = sorted((p for p in self.dir.iterdir() if p.is_file()),
                       key=lambda p: p.stat().st_mtime)
        budget = max(int(max_gb * 1_000_000_000), CACHE_FLOOR_BYTES)
        total = sum(p.stat().st_size for p in files)
        evicted = 0
        for p in files:
            if total <= budget:
                break
            total -= p.stat().st_size
            p.unlink(missing_ok=True)
            evicted += 1
        return {"evicted": evicted, "kept_bytes": total}
