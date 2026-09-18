# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.9 — payload fetchers (spec v0.11): remote BONE, resolved on first use.

`payload` (and future remote references) MAY carry a URI scheme. Plain
paths mean local sibling files (zero change). Remote URIs resolve through
a hash-validated cache in `_derived/payloads/` — a corrupted or tampered
download never reaches the agent. The Ranger evicts cold entries (H.6).

Schemes: `file://` (built-in — also the test double for object storage)
and `s3://` (optional extra `monkeyllm[s3]`: boto3, Apache-2.0;
`MONKEYLLM_S3_ENDPOINT` points to S3-compatible stores like MinIO/R2).

**Object stores (J.19, v0.84).** A store is a named destination for the
BONE tier, and the credential that opens it never lives in this package: a
host resolves it and hands the engine ONE seam at construction, keyword-only
(G.9's "credentials arrive at construction"). The seam answers exactly two
questions — `by_name(name)`, which is a WRITE (a forest's `assets:` binding),
and `by_bucket(bucket)`, which is a READ (whatever an existing `payload:`
URI names). Reads resolve by bucket and never by binding, so a forest that
was re-bound last month still opens everything it wrote before.

An engine with no host has exactly one store, the implicit `env` one
declared by `MONKEYLLM_S3_BUCKET` (J.19.4), constituted here without a
resolver. With neither a resolver nor that variable, every path in this
module behaves exactly as it did in v0.83 — that is the negative control,
not a claim.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlparse
from urllib.request import url2pathname

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError

SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://")
CACHE_FLOOR_BYTES = 1  # evict() never drops below "keep nothing" semantics

# J.19.6: the archive runs inside an ingest step, which holds the forest's
# one writer lane, so the upload carries a wall clock. Same number and same
# reasoning as G.5.1's describer — it is the same question, and one project
# answers it once.
STORE_TIMEOUT_S = 60


def is_remote(ref) -> bool:
    return bool(ref) and bool(SCHEME_RE.match(str(ref)))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local_path(uri: str) -> Path:
    return Path(url2pathname(urlparse(uri).path))


def split_uri(uri: str) -> tuple[str, str]:
    """`s3://bucket/key` -> (bucket, key). The scheme is the caller's to check."""
    parsed = urlparse(str(uri))
    return parsed.netloc, parsed.path.lstrip("/")


# ===========================================================================
# J.19 — the store record and the resolver seam
# ===========================================================================

@dataclass
class StoreCredentials:
    """One object store, as the engine sees it (J.19.1).

    Held for the length of a call and never logged, traced, audited or
    returned from a primitive (J.19.8). `__repr__` is overridden rather
    than trusted: a dataclass prints every field, and the one place a
    secret leaks is the exception somebody pasted into a ticket.
    """

    bucket: str
    name: str = "env"
    endpoint: str | None = None
    prefix: str = ""
    region: str | None = None
    access_key: str | None = field(default=None, repr=False)
    secret_key: str | None = field(default=None, repr=False)
    path_style: bool = False

    def __repr__(self) -> str:  # pragma: no cover - trivial, asserted in tests
        return (f"StoreCredentials(name={self.name!r}, bucket={self.bucket!r}, "
                f"endpoint={self.endpoint!r}, prefix={self.prefix!r}, "
                f"has_key={bool(self.secret_key)})")

    __str__ = __repr__

    @property
    def has_key(self) -> bool:
        return bool(self.access_key and self.secret_key)

    def key_for(self, *parts: str) -> str:
        """A key under this store's own prefix. Nothing here is caller-authored."""
        pieces = [p.strip("/") for p in (self.prefix, *parts) if str(p).strip("/")]
        return "/".join(pieces)

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{str(key).lstrip('/')}"

    def contains(self, key: str) -> bool:
        """G.3.1 rule 2: a store confined to a prefix serves only under it."""
        prefix = self.prefix.strip("/")
        if not prefix:
            return True
        key = str(key).strip("/")
        return key == prefix or key.startswith(prefix + "/")


@runtime_checkable
class StoreResolver(Protocol):
    """The ONE seam a host hands the engine (J.19.8). Two questions, no more."""

    def by_name(self, name: str) -> StoreCredentials | None: ...

    def by_bucket(self, bucket: str) -> StoreCredentials | None: ...


class StoreMap:
    """A resolver over a fixed list of records — the shape a host builds.

    The engine never constructs one from a table; this exists so that a
    library caller, a test double and the Station's registry-backed resolver
    all answer the same two questions.
    """

    def __init__(self, stores: list[StoreCredentials] | None = None):
        self.stores = list(stores or [])

    def by_name(self, name: str) -> StoreCredentials | None:
        for store in self.stores:
            if store.name == name:
                return store
        return None

    def by_bucket(self, bucket: str) -> StoreCredentials | None:
        for store in self.stores:
            if store.bucket == bucket:
                return store
        return None

    def names(self) -> list[str]:
        """What exists to be asked for — OPTIONAL, and never a credential.

        Not part of the J.19.8 seam (which answers two questions and only
        two): a refusal that can name the stores that exist is a repair
        somebody can perform, so a resolver MAY offer this and G.3.1's
        refusal reads it by duck-typing when it is there.
        """
        return [store.name for store in self.stores]


def env_store() -> StoreCredentials | None:
    """J.19.4: `MONKEYLLM_S3_BUCKET` declares a store, read-only, named `env`.

    The credential is NOT read here: boto3's own chain (env vars, a profile,
    an instance role) resolves it at call time, so a deployment on EC2 or
    ECS holds no key at all and is never asked for one.
    """
    bucket = (os.environ.get("MONKEYLLM_S3_BUCKET") or "").strip()
    if not bucket:
        return None
    return StoreCredentials(
        bucket=bucket,
        name="env",
        endpoint=(os.environ.get("MONKEYLLM_S3_ENDPOINT") or "").strip() or None,
        prefix=(os.environ.get("MONKEYLLM_S3_PREFIX") or "").strip("/"),
        region=(os.environ.get("MONKEYLLM_S3_REGION") or "").strip() or None,
        path_style=_truthy(os.environ.get("MONKEYLLM_S3_PATH_STYLE")),
    )


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def resolve_store(*, bucket: str | None = None, name: str | None = None,
                  stores: StoreResolver | None = None) -> StoreCredentials | None:
    """The resolution order, in one place (J.19.6 write, J.19.7 read).

    By NAME: the host's resolver, then the `env` store when it is the one
    being named. By BUCKET: the host's resolver, then the `env` store when
    it serves that bucket. `None` means nothing is configured for it, and
    the caller decides what that means — a write falls back to `_assets/`,
    a read refuses naming the bucket.
    """
    if name:
        found = stores.by_name(name) if stores is not None else None
        if found is not None:
            return found
        env = env_store()
        return env if env is not None and env.name == name else None
    if bucket:
        found = stores.by_bucket(bucket) if stores is not None else None
        if found is not None:
            return found
        env = env_store()
        return env if env is not None and env.bucket == bucket else None
    return None


def bucket_served(bucket: str, stores: StoreResolver | None = None) -> bool:
    """Whether this deployment can open that bucket at all.

    True when a store serves it, and ALSO true when the deployment has
    declared nothing — no resolver and no `env` store — because there the
    ambient client of v0.83 is still the whole story and this version
    changes no behaviour it had. One predicate, read by the reader
    (`store_for_read`) and by the counter (`catalog.missing_payloads`), so
    "unreachable" means one thing in this codebase.
    """
    if resolve_store(bucket=bucket, stores=stores) is not None:
        return True
    return stores is None and env_store() is None


def store_for_read(bucket: str,
                   stores: StoreResolver | None = None) -> StoreCredentials | None:
    """The credential that opens an existing URI, or the G.9 refusal.

    `None` is returned for exactly one case: a deployment that has declared
    NOTHING — no resolver and no `env` store — where v0.83's ambient client
    is still the whole story and this module must behave byte-identically
    (F.221). Anywhere a deployment HAS declared its stores, a bucket none of
    them serves is `E_NOT_FOUND` naming the bucket and nothing else: never
    the key, never the endpoint, never the store.
    """
    found = resolve_store(bucket=bucket, stores=stores)
    if found is not None:
        return found
    if bucket_served(bucket, stores):
        return None
    raise VineError(
        E_NOT_FOUND,
        f"no object store serves bucket '{bucket}'",
        hint="This deployment has no credential for that bucket. Configure "
             "a store for it (the Storage console on a Station, "
             "MONKEYLLM_S3_BUCKET on an engine with no Station).",
    )


# ===========================================================================
# The S3 client
# ===========================================================================

def s3_client(creds: StoreCredentials | None = None, *,
              timeout: float | None = None):
    """An S3 client for one store, or v0.83's ambient one when there is none.

    Public and looked up through the module on every call so a test can put
    a double in its place: the object store this engine talks to is the one
    seam a suite must be able to hold in memory.
    """
    try:
        import boto3
    except ImportError as e:
        raise VineError(
            E_SCHEMA,
            "s3:// payloads need boto3 (optional extra)",
            hint='pip install "monkeyllm[s3]" — credentials come from a '
                 "configured store (J.19) or the standard AWS env vars; "
                 "MONKEYLLM_S3_ENDPOINT for S3-compatible stores (MinIO/R2).",
        ) from e
    if creds is None:
        endpoint = os.environ.get("MONKEYLLM_S3_ENDPOINT")
        return boto3.client("s3", endpoint_url=endpoint or None)
    config = None
    # A client built from a STORE RECORD signs with SigV4, always and
    # explicitly. Measured against a live MinIO: botocore resolves
    # `signature_version` to `s3v4` and still presigns with **SigV2**
    # (`AWSAccessKeyId=…&Signature=…&Expires=…`) unless the version was set
    # by hand — a compatibility default from before 2014. MinIO accepts
    # both, so nothing here fails; AWS S3 rejects SigV2 in every region
    # created since, so the URL J.14 hands a reader would be signed and
    # refused, and the refusal would arrive from the STORE, in the reader's
    # browser, with nothing on this side to read. The ambient client below
    # is deliberately untouched: it is v0.83's, and F.221's negative control
    # is that nothing about it changed.
    settings: dict = {"signature_version": "s3v4"}
    if creds.path_style:
        settings["s3"] = {"addressing_style": "path"}
    if timeout:
        settings.update(connect_timeout=timeout, read_timeout=timeout,
                        retries={"max_attempts": 1})
    try:
        from botocore.config import Config

        config = Config(**settings)
    except ImportError:  # pragma: no cover - botocore ships with boto3
        config = None
    kwargs: dict = {"endpoint_url": creds.endpoint or None}
    if creds.region:
        kwargs["region_name"] = creds.region
    if creds.has_key:
        kwargs["aws_access_key_id"] = creds.access_key
        kwargs["aws_secret_access_key"] = creds.secret_key
    if config is not None:
        kwargs["config"] = config
    return boto3.client("s3", **kwargs)


def head_object(creds: StoreCredentials, key: str, *,
                timeout: float | None = None) -> dict | None:
    """A stat, never a read. `None` when the object is not there."""
    client = s3_client(creds, timeout=timeout)
    try:
        return client.head_object(Bucket=creds.bucket, Key=key)
    except Exception as e:  # noqa: BLE001 - every SDK spells "absent" its own way
        if _is_absent(e):
            return None
        raise


def put_object(creds: StoreCredentials, key: str, data: bytes, *,
               timeout: float | None = None) -> None:
    s3_client(creds, timeout=timeout).put_object(
        Bucket=creds.bucket, Key=key, Body=data)


def delete_object(creds: StoreCredentials, key: str, *,
                  timeout: float | None = None) -> None:
    s3_client(creds, timeout=timeout).delete_object(Bucket=creds.bucket, Key=key)


def get_object(creds: StoreCredentials, key: str, dest: Path, *,
               timeout: float | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    s3_client(creds, timeout=timeout).download_file(
        creds.bucket, key, str(dest))
    return dest


def list_objects(creds: StoreCredentials, prefix: str = "", *,
                 timeout: float | None = None) -> list[dict]:
    """G.3.1 rule 3: the whole key listing, paginated, taken eagerly.

    Each entry is `{key, size, etag, last_modified}` — the store's own change
    signals (G.9 rule 3), which is what makes the freshness fast-path
    possible without an mtime no store will promise.
    """
    client = s3_client(creds, timeout=timeout)
    out: list[dict] = []
    token: str | None = None
    while True:
        kwargs: dict = {"Bucket": creds.bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs) or {}
        for item in page.get("Contents") or []:
            modified = item.get("LastModified")
            out.append({
                "key": item.get("Key") or "",
                "size": int(item.get("Size") or 0),
                "etag": str(item.get("ETag") or "").strip('"'),
                "last_modified": modified,
            })
        if not page.get("IsTruncated"):
            break
        token = page.get("NextContinuationToken")
        if not token:
            break
    return out


def _is_absent(error: Exception) -> bool:
    code = getattr(error, "response", {}).get("Error", {}).get("Code") \
        if hasattr(error, "response") else None
    if code in ("404", "NoSuchKey", "NotFound", "NoSuchBucket"):
        return True
    return type(error).__name__ in ("NoSuchKey", "ClientError404", "KeyNotFound")


def can_presign(uri: str) -> bool:
    """J.14: only a scheme that can sign a URL may be redirected to."""
    return urlparse(str(uri)).scheme == "s3"


def presign(uri: str, ttl: int = 300, *,
            stores: StoreResolver | None = None) -> str:
    """A short-lived GET URL for a remote payload (J.14, v0.84).

    Never recorded anywhere by this engine: it is a bearer credential with a
    clock on it, and the host's own rule is that it reaches no audit row, no
    log and no error.
    """
    if not can_presign(uri):
        scheme = urlparse(str(uri)).scheme
        raise VineError(
            E_SCHEMA,
            f"payload scheme '{scheme}' has no presigned form",
            hint="Bytes on a scheme that cannot sign a URL are served "
                 "through the host's payload route instead (J.14).")
    bucket, key = split_uri(uri)
    creds = store_for_read(bucket, stores)
    client = s3_client(creds)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": (creds.bucket if creds else bucket), "Key": key},
        ExpiresIn=int(ttl),
    )


def remote_size(uri: str, *, stores: StoreResolver | None = None) -> int | None:
    """The object's byte count, by a `HEAD` and never a fetch (C.6d rule 2)."""
    scheme = urlparse(str(uri)).scheme
    bucket, key = split_uri(uri)
    if scheme == "file":
        local = _local_path(uri)
        return local.stat().st_size if local.is_file() else None
    if scheme != "s3":
        raise VineError(E_SCHEMA, f"unsupported payload scheme: {scheme}://")
    creds = store_for_read(bucket, stores)
    if creds is None:
        try:
            head = s3_client(None).head_object(Bucket=bucket, Key=key)
        except Exception as e:  # noqa: BLE001
            if _is_absent(e):
                return None
            raise
    else:
        head = head_object(creds, key)
    if head is None:
        return None
    return int(head.get("ContentLength") or 0)


# ===========================================================================
# Fetchers
# ===========================================================================

def _fetch_file(uri: str, dest: Path, *,
                stores: StoreResolver | None = None) -> None:
    src = _local_path(uri)
    if not src.is_file():
        raise VineError(E_NOT_FOUND, f"remote payload not found: {uri}")
    shutil.copyfile(src, dest)


def _fetch_s3(uri: str, dest: Path, *,
              stores: StoreResolver | None = None) -> None:
    bucket, key = split_uri(uri)
    creds = store_for_read(bucket, stores)
    if creds is None:
        s3_client(None).download_file(bucket, key, str(dest))
        return
    get_object(creds, key, dest)


FETCHERS = {"file": _fetch_file, "s3": _fetch_s3}


def upload(path: Path, uri: str, *,
           stores: StoreResolver | None = None) -> None:
    """Push a local file to a remote URI (snapshots' `--to`, Part I)."""
    scheme = urlparse(uri).scheme
    if scheme == "file":
        dest = _local_path(uri)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        return
    if scheme == "s3":
        bucket, key = split_uri(uri)
        creds = resolve_store(bucket=bucket, stores=stores)
        if creds is None:
            s3_client(None).upload_file(str(path), bucket, key)
            return
        put_object(creds, key, Path(path).read_bytes())
        return
    raise VineError(E_SCHEMA, f"unsupported upload scheme: {scheme}://")


class PayloadCache:
    """Hash-validated, LRU-evictable cache for remote payloads (G.9/H.6).

    `stores` is the J.19 resolver, keyword-only and host-supplied at
    construction (G.2.5's construction, G.9's rule): the cache is where a
    remote URI becomes bytes, so it is where the credential is needed and
    the only place in the engine that holds one.
    """

    def __init__(self, derived_dir: Path, *,
                 stores: StoreResolver | None = None):
        self.dir = Path(derived_dir) / "payloads"
        self.stores = stores

    def _slot(self, uri: str) -> Path:
        name = Path(urlparse(uri).path).name or "payload"
        return self.dir / f"{hashlib.sha256(uri.encode()).hexdigest()[:16]}-{name}"

    def slot_for(self, uri: str) -> Path:
        """Where these bytes belong. Part I's restore writes here rather than
        letting an archive member's own path decide a destination."""
        return self._slot(uri)

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
            fetch(uri, tmp, stores=self.stores)
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

    def size(self, uri: str) -> int | None:
        """The object's size without fetching it (C.6d rule 2, J.14)."""
        return remote_size(uri, stores=self.stores)

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
