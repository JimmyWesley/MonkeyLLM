# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""Object stores (spec J.19): the deployment's named destinations for BONE.

Shaped after a provider (J.10) deliberately — an operator who has configured
one has configured the other, and every rule that made a provider safe is a
rule this needs for the same reason: the credential is write-only over the
API, the address is validated before it is contacted, the reach matches what
the resource serves, and a deployment that declared one in its environment is
published rather than asked again.

What crosses the licensing boundary is ONE seam (J.19.8): a resolver handed
to the engine at construction, answering `by_name` and `by_bucket` and
nothing else. The engine reads no registry table and MUST NOT log, trace,
audit or return what the resolver hands it.

Nothing here opens a socket of its own: the client is the engine's
`fetch.s3_client`, looked up through that module on every call, which is
the one door a test puts a double in — a second door here would be a second
answer to "is this store reachable".
"""

from __future__ import annotations

import os
import re
import secrets

# The engine's own record (G.9/J.19.8), imported rather than re-declared:
# two descriptions of one credential agree only where somebody compared
# them, and this one crosses the licensing boundary on every call.
from monkeyllm.fetch import StoreCredentials

# J.19.1: a name is a name before it is anything else — it is typed into a
# forest's `_meta/` and read back by a resolver, so it is an identifier and
# not free text (the J.7/J.13.1 posture).
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")

# The environment-declared store (J.19.4). `MONKEYLLM_S3_ENDPOINT` already
# exists and already means this; the bucket is what makes a store exist.
S3_BUCKET_ENV = "MONKEYLLM_S3_BUCKET"
S3_ENDPOINT_ENV = "MONKEYLLM_S3_ENDPOINT"
S3_PREFIX_ENV = "MONKEYLLM_S3_PREFIX"
S3_REGION_ENV = "MONKEYLLM_S3_REGION"
S3_PATH_STYLE_ENV = "MONKEYLLM_S3_PATH_STYLE"
ENV_STORE_NAME = "env"

# The probe object (J.19.3 rule 2): the test is a WRITE, because a read-only
# grant passes every check a listing could make and fails at the first
# archive, at whatever hour ingest runs.
PROBE_PREFIX = ".monkeyllm-probe-"
PROBE_BODY = b"monkeyllm store probe\n"
# A console is waiting on this call, so the probe does not inherit boto3's
# own patience with an address that answers nothing.
PROBE_TIMEOUT = 10.0


def is_bucket_uri(value) -> bool:
    """Whether this source names an object store rather than a directory."""
    return isinstance(value, str) and value.strip().lower().startswith("s3://")


def normalise_prefix(prefix: str | None) -> str:
    """A prefix is a path inside a bucket: no leading or trailing separator,
    so `teams/` and `/teams` are one value and the engine's own containment
    test (`StoreCredentials.contains`) has one spelling to compare against.

    Splitting a URI and deciding containment are the ENGINE's
    (`fetch.split_uri`, `StoreCredentials.contains`) and are not restated
    here: a second answer to "is this key inside that prefix" is how the
    walk and the refusal come to disagree.
    """
    return str(prefix or "").strip().strip("/")


def escapes(key: str) -> bool:
    """A key the caller sent that must never become a path (G.8, J.20).

    Absolute, `..` anywhere, or a backslash: a notification arrives from
    outside and is caller input like any other.
    """
    raw = str(key or "").strip()
    if not raw or raw.startswith("/") or "\\" in raw:
        return True
    parts = raw.split("/")
    # `..` and `.` are refused wherever they sit, and so is an empty
    # component: a key is normalised before it is compared, so a spelling
    # that normalises to something else is refused rather than normalised.
    return any(p in ("..", ".", "") for p in parts)


# ---------------------------------------------------------------------------
# The record the engine is handed (J.19.8 / G.9)
# ---------------------------------------------------------------------------


def credentials_of(row: dict | None) -> StoreCredentials | None:
    """A secret-bearing registry row as the engine's record.

    Built field by field against whatever the engine's dataclass declares,
    so this host runs against an engine that has grown a field and one that
    has not — the integrator reconciles names, never call sites.
    """
    if not row:
        return None
    fields = {
        "name": row.get("name") or "",
        # Empty is ABSENT here, not a blank address: the engine reads
        # `endpoint or None` as "the provider's own public endpoint", and a
        # record that says `''` where the type says `str | None` is one more
        # thing for a later reader to check.
        "endpoint": (row.get("endpoint") or "").strip() or None,
        "bucket": row.get("bucket") or "",
        "prefix": normalise_prefix(row.get("prefix")),
        "region": (row.get("region") or "").strip() or None,
        "access_key": row.get("access_key") or None,
        "secret_key": row.get("secret_key") or None,
        "path_style": bool(row.get("path_style")),
    }
    declared = getattr(StoreCredentials, "__dataclass_fields__", None)
    if declared is not None:
        fields = {k: v for k, v in fields.items() if k in declared}
    return StoreCredentials(**fields)


class StoreResolver:
    """The J.19.8 seam: two questions, and only two.

    Read at CALL time out of the registry, never cached: a store edited in
    the console reaches the next ingest without a restart, and a store
    removed stops resolving instead of living on in a closure (L.7 rule 4's
    live read, applied to a credential).
    """

    def __init__(self, registry):
        self.registry = registry

    def by_name(self, name: str):
        """What a forest's `assets:` binding resolves to. This is a write."""
        return credentials_of(self.registry.store_secret(str(name or "")))

    def by_bucket(self, bucket: str):
        """Which credential opens an existing URI. This is a read."""
        return credentials_of(
            self.registry.store_secret_for_bucket(str(bucket or "")))

    def names(self) -> list[str]:
        """What exists to be asked for (G.3.1 rule 1).

        Not part of the two-question seam: the engine reads it by
        duck-typing when it is there, so a refusal it raises can name the
        stores that exist — a repair somebody can perform — without this
        host restating the sentence.
        """
        return sorted(store["name"] for store in self.registry.stores())


# ---------------------------------------------------------------------------
# The environment-declared store (J.19.4)
# ---------------------------------------------------------------------------


def store_from_env(environ: dict | None = None) -> dict | None:
    """The deployment's own store, as a registry-shaped row (J.19.4).

    WHICH variables declare it is the engine's answer, not a second list
    here: `fetch.env_store()` reads them and an operator with no Station
    gets object storage from exactly the same ones. What this adds is the
    two things a console needs and a fetcher does not — the row shape the
    listing serves, and whether a credential is sitting in the environment
    (`has_key`). The pair is read for that answer and to hand the engine an
    explicit credential; when it is absent, boto3's own chain (a profile,
    an instance role) still resolves one, so `has_key: false` means "not in
    the environment" and never "this store cannot write".

    Nothing here is persisted: the registry file is a backup target and the
    environment is not (J.10.1's sentence, unchanged).
    """
    env = os.environ if environ is None else environ
    if environ is None:
        from monkeyllm import fetch

        declared = fetch.env_store()
        if declared is None:
            return None
        row = {"name": declared.name, "endpoint": declared.endpoint or "",
               "bucket": declared.bucket, "prefix": declared.prefix,
               "region": declared.region or "",
               "path_style": bool(declared.path_style)}
    else:
        # A caller-supplied environment (a test, a probe): the same reading,
        # against the mapping it handed in.
        bucket = (env.get(S3_BUCKET_ENV) or "").strip()
        if not bucket:
            return None
        raw_style = (env.get(S3_PATH_STYLE_ENV) or "").strip().lower()
        row = {"name": ENV_STORE_NAME,
               "endpoint": (env.get(S3_ENDPOINT_ENV) or "").strip().rstrip("/"),
               "bucket": bucket,
               "prefix": normalise_prefix(env.get(S3_PREFIX_ENV)),
               "region": (env.get(S3_REGION_ENV) or "").strip(),
               "path_style": raw_style in {"1", "true", "yes", "on"}}
    return {
        **row,
        "access_key": (env.get("AWS_ACCESS_KEY_ID") or "").strip() or None,
        "secret_key": (env.get("AWS_SECRET_ACCESS_KEY") or "").strip() or None,
    }


# ---------------------------------------------------------------------------
# The one door to a socket
# ---------------------------------------------------------------------------


def probe(store: dict) -> dict:
    """The J.19.3 test: reach the bucket, write under the prefix, remove it.

    Three steps and three facts. "OK" about a three-step check is three
    facts a reader cannot separate when one of them later fails, so each is
    reported by name — and a probe this credential can create and cannot
    remove is a fact about the grant that will matter when a forest wants
    its bytes back.

    The client is the engine's (`fetch.s3_client`), looked up through the
    module on every call: the object store this product talks to is ONE
    seam, and a test puts its double there rather than in a second one the
    host would keep for itself.
    """
    from monkeyllm import fetch

    creds = credentials_of(store)
    bucket = (creds.bucket if creds else "") or ""
    key = creds.key_for(f"{PROBE_PREFIX}{secrets.token_hex(6)}") if creds \
        else f"{PROBE_PREFIX}{secrets.token_hex(6)}"
    steps: list[dict] = []

    def _step(name: str, fn) -> bool:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — every client raises its own
            steps.append({"step": name, "ok": False,
                          "error": f"{type(e).__name__}: {e}"[:200]})
            return False
        steps.append({"step": name, "ok": True})
        return True

    try:
        client = fetch.s3_client(creds, timeout=PROBE_TIMEOUT)
    except Exception as e:  # noqa: BLE001 — boto3 absent, or a bad config
        return {"ok": False, "bucket": bucket,
                "steps": [{"step": "client", "ok": False,
                           "error": f"{type(e).__name__}: {e}"[:200]}]}

    if not _step("head", lambda: client.head_bucket(Bucket=bucket)):
        return {"ok": False, "bucket": bucket, "steps": steps}
    if not _step("write", lambda: client.put_object(
            Bucket=bucket, Key=key, Body=PROBE_BODY)):
        return {"ok": False, "bucket": bucket, "steps": steps}
    deleted = _step("delete", lambda: client.delete_object(
        Bucket=bucket, Key=key))
    return {"ok": bool(deleted), "bucket": bucket, "steps": steps,
            # The probe never leaves the prefix, and the caller is told
            # where it went so an operator can find it if the delete failed.
            "probe": key}
