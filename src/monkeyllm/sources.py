# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.3.1 (spec v0.84) — a source that is an object-store prefix.

Somebody whose corpus is already in object storage had one route into a
forest: mount the bucket and adopt the mount. It works, and it records a
lie — G.2.7 makes the Gardener fill `origin` with the source file's own
URI, and through a mount that URI is `file:///mnt/…`, an address that names
a machine's mount table rather than the object. The map is the part of this
product that outlives every deployment of it, so provenance that only
resolves inside one container is the one field this pipeline may not
fabricate.

Three properties this module exists to hold:

1. **A bucket is reached only through a configured store (J.19), and that is
   the containment rule** — the counterpart of `MONKEYLLM_INGEST_ROOTS` for
   directories. It is load-bearing rather than procedural: every S3 client in
   wide use falls back to an ambient credential chain and a default endpoint,
   so an unserved bucket would otherwise resolve *somewhere*, with whatever
   authority the host process happens to carry.
2. **The listing is eager** — G.10 promises `total` before the first step and
   J.9 refuses before it accepts.
3. **A step downloads ONE object**, into `_derived/staging/`, and the staged
   copy goes as the document lands. That removal is J.8.3's `consume` and it
   is safe here for the opposite reason: an upload's staged bytes are the only
   copy in existence, while a bucket object is still in the bucket.
"""

from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath

from monkeyllm.errors import E_FORBIDDEN, E_SCHEMA, VineError
from monkeyllm.fetch import get_object, list_objects, resolve_store, split_uri

BUCKET_SCHEME = "s3://"

# G.3 rule 3: a sub-prefix carrying this key is a forest somebody else's Vine
# writes, and it is pruned whole, children included.
FOREST_MARKER = "_index.md"


def is_bucket_source(raw) -> bool:
    return str(raw or "").strip().lower().startswith(BUCKET_SCHEME)


def _store_hint(stores) -> str:
    """What exists to be asked for — never a credential, and never nothing.

    A refusal names where a store is MADE, because the engine's only store is
    the implicit `env` one (J.19.4) and advice a reader cannot act on is not
    advice.
    """
    names = []
    listing = getattr(stores, "names", None)
    if callable(listing):
        try:
            names = sorted(str(n) for n in listing())
        except Exception:  # noqa: BLE001 - a resolver is a host's object
            names = []
    have = f"Configured stores: {', '.join(names)}. " if names else \
        "This deployment has no object store configured. "
    return (have + "A bucket is reached only through one (J.19): make it in "
            "the Storage console on a Station, or set MONKEYLLM_S3_BUCKET on "
            "an engine with no Station.")


class BucketSource:
    """One `s3://bucket/prefix`, listed once and fetched one object at a time."""

    kind = "bucket"

    def __init__(self, uri: str, creds, *, staging: Path,
                 ignored=None):
        self.uri = uri.rstrip("/")
        self.bucket, self.prefix = split_uri(self.uri)
        self.prefix = self.prefix.strip("/")
        self.creds = creds
        self.staging = Path(staging)
        self._ignored = ignored or (lambda rel: False)
        self.entries: list[dict] = []

    # -- listing ------------------------------------------------------------

    def open(self) -> "BucketSource":
        listing = list_objects(self.creds, f"{self.prefix}/" if self.prefix
                               else "")
        keys = [item for item in listing if not item["key"].endswith("/")]
        pruned = self._forest_prefixes(keys)
        out: list[dict] = []
        for item in keys:
            rel = self._relative(item["key"])
            if rel is None or not rel:
                continue
            if any(rel == p or rel.startswith(p + "/") for p in pruned):
                continue
            if self._ignored(rel):
                continue
            out.append({"rel": rel, "key": item["key"], "size": item["size"],
                        "etag": item["etag"],
                        "last_modified": item.get("last_modified")})
        out.sort(key=lambda e: e["rel"])
        self.entries = out
        return self

    def _forest_prefixes(self, keys: list[dict]) -> list[str]:
        """Sub-prefixes that are somebody else's forest (G.3 rule 3)."""
        out = []
        for item in keys:
            rel = self._relative(item["key"])
            if rel is None:
                continue
            parent = posixpath.dirname(rel)
            if parent and posixpath.basename(rel) == FOREST_MARKER:
                out.append(parent)
        return out

    def _relative(self, key: str) -> str | None:
        """The key relative to the prefix, or `None` when it leaves it.

        A key that normalises outside the prefix never becomes a node — the
        same comparison G.8 makes on a targeted path, decided on the string
        because a key is not a path and there is nothing to resolve.
        """
        key = str(key)
        if self.prefix:
            if key == self.prefix:
                return None
            if not key.startswith(self.prefix + "/"):
                return None
            key = key[len(self.prefix) + 1:]
        if not key or key.startswith("/") or "\\" in key:
            return None
        parts = PurePosixPath(key).parts
        if any(p == ".." for p in parts):
            return None
        return key

    # -- one object ---------------------------------------------------------

    def key_for(self, rel: str) -> str:
        return f"{self.prefix}/{rel}" if self.prefix else rel

    def object_uri(self, rel: str) -> str:
        """G.2.7 rule 1: the address that resolves from any machine holding
        the store's credentials, which is what a mount path never was."""
        return f"s3://{self.bucket}/{self.key_for(rel)}"

    def fetch(self, rel: str) -> Path:
        dest = self.staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        get_object(self.creds, self.key_for(rel), dest)
        return dest

    def release(self, path: Path) -> None:
        """The staged copy goes as the document lands — and on failure too.

        A file whose conversion FAILED is removed for the same reason: the
        evidence is the key, which the report names, and keeping bytes the
        store already holds would rebuild the invisible accumulation J.13.7
        exists to clear.
        """
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            return
        parent = Path(path).parent
        staging = self.staging.resolve()
        while parent.resolve() != staging and parent.is_dir():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def open_bucket_source(raw: str, *, stores=None, staging: Path,
                       ignored=None) -> BucketSource:
    """Resolve an `s3://bucket/prefix` source, refusing BEFORE any listing.

    Rules 1 and 2 are decided here, on the string and on the resolver, with
    zero calls made to the store: a bucket no configured store serves, and a
    prefix a store does not contain, are both `E_FORBIDDEN`.
    """
    uri = str(raw).strip().rstrip("/")
    bucket, prefix = split_uri(uri)
    if not bucket:
        raise VineError(
            E_SCHEMA, f"not an object-store source: {raw}",
            hint="A bucket source is s3://<bucket>/<prefix>.")
    creds = resolve_store(bucket=bucket, stores=stores)
    if creds is None:
        raise VineError(
            E_FORBIDDEN, f"no object store serves bucket '{bucket}'",
            hint=_store_hint(stores))
    if not creds.contains(prefix.strip("/") or creds.prefix):
        raise VineError(
            E_FORBIDDEN,
            f"prefix '{prefix}' is outside what store '{creds.name}' serves",
            hint="A store confined to a prefix serves only under it (G.3.1 "
                 "rule 2); the walk's reach is bounded where it is built.")
    return BucketSource(uri, creds, staging=staging, ignored=ignored).open()
