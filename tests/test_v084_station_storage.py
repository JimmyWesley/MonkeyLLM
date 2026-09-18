# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Object stores over REST (spec J.19 + J.14 + Part I, F.219-F.228).

The host halves of the storage round: the registry row and its write-only
credential, the reach that matches what the resource serves, the probe that
proves a WRITE, the environment-declared store, the payload route that
proxies under the ceiling and redirects over it, and the snapshot flag that
says which tier it is not carrying.

Nothing here opens a socket. Every store client comes from the engine's
`fetch.s3_client`, which is the ONE door a deployment uses — so a fake here
is the real code path with a different client behind it, not a second code
path deciding what "reachable" means.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
OTHER = "forest-second"

SECRET = "s3cr3t-nobody-may-read-it"
ACCESS = "AKIAEXAMPLEIDENTITY"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"pixels" * 64


# -- a store with no network ------------------------------------------------


class NoSuchKey(Exception):
    """What a store's SDK raises for an object it does not hold; the engine
    reads the name (`fetch._is_absent`) rather than a boto3 type, which is
    exactly what lets this fake stand in for one."""


class FakeS3:
    """What `make_client` hands back: every call recorded, every refusal
    explicit. `credentials` is what the store record carried, so a test can
    assert that a stored secret never travelled to a destination the caller
    typed."""

    def __init__(self, creds=None, objects: dict | None = None, *,
                 writable: bool = True, deletable: bool = True,
                 signs: bool = True):
        self.creds = creds
        self.objects: dict[str, bytes] = dict(objects or {})
        self.calls: list[tuple] = []
        self.writable, self.deletable, self.signs = writable, deletable, signs

    # the probe (J.19.3)
    def head_bucket(self, Bucket):
        self.calls.append(("head_bucket", Bucket))
        return {}

    def put_object(self, Bucket, Key, Body):
        self.calls.append(("put_object", Key))
        if not self.writable:
            raise PermissionError("AccessDenied: this grant may not write")
        self.objects[Key] = Body
        return {}

    def delete_object(self, Bucket, Key):
        self.calls.append(("delete_object", Key))
        if not self.deletable:
            raise PermissionError("AccessDenied: this grant may not delete")
        self.objects.pop(Key, None)
        return {}

    # the payload route (J.14)
    def head_object(self, Bucket, Key):
        self.calls.append(("head_object", Key))
        if Key not in self.objects:
            raise NoSuchKey(Key)
        return {"ContentLength": len(self.objects[Key])}

    def download_file(self, Bucket, Key, dest):
        self.calls.append(("download_file", Key))
        Path(dest).write_bytes(self.objects[Key])

    def generate_presigned_url(self, op, Params, ExpiresIn):
        self.calls.append(("presign", Params["Key"], ExpiresIn))
        if not self.signs:
            raise RuntimeError("this client cannot sign")
        return (f"https://store.example/{Params['Bucket']}/{Params['Key']}"
                f"?X-Amz-Signature=deadbeef&X-Amz-Expires={ExpiresIn}")


class Stub:
    """One fake per test, remembering every credential record it was built
    from — which is how a test asserts that a stored secret never travelled
    to a destination the caller typed."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.seen: list = []
        self.clients: list[FakeS3] = []
        self.objects: dict[str, bytes] = {}

    def __call__(self, creds=None, *, timeout=None) -> FakeS3:
        self.seen.append(creds)
        client = FakeS3(creds, self.objects, **self.kwargs)
        self.clients.append(client)
        return client

    @property
    def calls(self) -> list[tuple]:
        return [c for client in self.clients for c in client.calls]

    def secret_of(self, index: int = -1):
        return getattr(self.seen[index], "secret_key", None)


@pytest.fixture()
def stub(monkeypatch):
    """The engine's own seam: `fetch.s3_client` is looked up through the
    module on every call precisely so a suite can hold the object store in
    memory."""
    from monkeyllm import fetch

    made = Stub()
    monkeypatch.setattr(fetch, "s3_client", made)
    return made


# -- the Station ------------------------------------------------------------


@pytest.fixture(scope="session")
def two_forests(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("v084-storage")
    build_forest(root / FOREST)
    build_forest(root / OTHER)
    return root


@pytest.fixture()
def station(two_forests, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    for var in ("MONKEYLLM_STATION_ADMIN", "MONKEYLLM_STATION_PASSWORD",
                "MONKEYLLM_S3_BUCKET", "MONKEYLLM_S3_ENDPOINT",
                "MONKEYLLM_S3_PREFIX", "MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE"):
        monkeypatch.delenv(var, raising=False)
    app = build_app(root=two_forests, registry_path=tmp_path / "station.db",
                    mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, two_forests


def _key(registry, principal, forests, caps=("read", "admin")):
    key = registry.issue_key(principal)
    for forest in forests:
        registry.grant(principal, forest, set(caps))
    return {"Authorization": f"Bearer {key}"}


def _both(registry, principal="boss"):
    return _key(registry, principal, (FOREST, OTHER))


def _one(registry, principal="half"):
    return _key(registry, principal, (FOREST,))


STORE = {"name": "backups", "endpoint": "https://objects.example.com",
         "bucket": "forest-assets", "prefix": "teams", "region": "us-east-1",
         "path_style": True, "access_key": ACCESS, "secret_key": SECRET}


def _create(client, head, **over):
    return client.post("/v1/admin/stores", json={**STORE, **over}, headers=head)


def _local(client, head, monkeypatch, **over):
    """A store the probe may actually reach: a local MinIO, which is the
    case `MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE` exists for — and an IP
    literal, so no test in this file ever asks a resolver anything."""
    monkeypatch.setenv("MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE", "1")
    return _create(client, head, endpoint="http://127.0.0.1:9000", **over)


# ===========================================================================
# F.219 — the row and its secret
# ===========================================================================


def test_a_store_is_listed_without_its_secret_or_its_access_key(station):
    """J.19.1: the credential is write-only across every surface, and the
    access key id is withheld too — it names an identity in somebody's
    account and a console can do nothing with it."""
    client, registry, _ = station
    head = _both(registry)
    assert _create(client, head).status_code == 201

    r = client.get("/v1/admin/stores", headers=head)
    assert r.status_code == 200, r.text
    body = r.text
    assert SECRET not in body and ACCESS not in body
    store = r.json()["stores"][0]
    assert store == {"name": "backups", "endpoint": "https://objects.example.com",
                     "bucket": "forest-assets", "prefix": "teams",
                     "region": "us-east-1", "path_style": True,
                     "origin": "console", "created": store["created"],
                     "has_key": True}


def test_an_update_omitting_the_credential_keeps_it(station):
    """`null` means keep — the only way an editor that cannot READ a value
    can leave it alone (J.16's rule for headers)."""
    client, registry, _ = station
    head = _both(registry)
    _create(client, head)

    r = client.put("/v1/admin/stores/backups",
                   json={"region": "eu-west-1"}, headers=head)
    assert r.status_code == 200, r.text
    assert r.json()["store"]["has_key"] is True
    assert r.json()["store"]["region"] == "eu-west-1"
    # And the credential is still the one that was stored.
    assert registry.store_secret("backups")["secret_key"] == SECRET


def test_half_a_credential_is_refused(station):
    client, registry, _ = station
    head = _both(registry)
    r = _create(client, head, secret_key=None)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "E_SCHEMA"
    assert "travel together" in r.json()["error"]["message"]


def test_a_changed_destination_does_not_carry_the_old_credential(station):
    """J.3.2's custody rule with "address" reading as endpoint AND bucket: a
    bucket is part of where the credential was stored to point."""
    client, registry, _ = station
    head = _both(registry)
    _create(client, head)

    moved = client.put("/v1/admin/stores/backups",
                       json={"bucket": "somewhere-else"}, headers=head)
    assert moved.status_code == 400, moved.text
    assert "credential again" in moved.json()["error"]["message"]

    endpoint = client.put("/v1/admin/stores/backups",
                          json={"endpoint": "https://elsewhere.example.com"},
                          headers=head)
    assert endpoint.status_code == 400
    # Supplying it again is how the move happens.
    ok = client.put("/v1/admin/stores/backups",
                    json={"bucket": "somewhere-else", "access_key": ACCESS,
                          "secret_key": "another-secret"}, headers=head)
    assert ok.status_code == 200, ok.text


def test_one_store_per_bucket_and_the_refusal_names_the_other(station):
    """J.19.1: this is what makes the by-bucket lookup total — a read is a
    question with one answer, not a tie-break nobody could predict."""
    client, registry, _ = station
    head = _both(registry)
    _create(client, head)

    r = _create(client, head, name="second")
    assert r.status_code == 400, r.text
    assert "backups" in r.json()["error"]["message"]
    # A different bucket on the same endpoint is fine.
    assert _create(client, head, name="second",
                   bucket="other-bucket").status_code == 201


def test_listing_is_any_admins_and_managing_is_every_forests(station):
    """J.19.2: a store has no forest column — any forest may bind it and its
    credential pays for all of them."""
    client, registry, _ = station
    both, half = _both(registry), _one(registry)
    assert _create(client, both).status_code == 201

    assert client.get("/v1/admin/stores", headers=half).status_code == 200
    assert client.get("/v1/admin/stores", headers=half).json()["may_manage"] is False
    assert client.get("/v1/admin/stores", headers=both).json()["may_manage"] is True

    for call in (
        lambda h: client.post("/v1/admin/stores", json={**STORE, "name": "x",
                                                        "bucket": "bx"}, headers=h),
        lambda h: client.put("/v1/admin/stores/backups", json={}, headers=h),
        lambda h: client.delete("/v1/admin/stores/backups", headers=h),
        lambda h: client.post("/v1/admin/stores/backups/test", json={}, headers=h),
    ):
        assert call(half).status_code == 403
    assert client.delete("/v1/admin/stores/backups", headers=both).status_code == 200


def test_break_glass_reach_needs_no_owner_bit(station):
    """Stated as reach and not as the owner bit (J.2.1): a principal holding
    per-forest admin over EVERY forest governs the deployment."""
    client, registry, _ = station
    head = _both(registry, principal="glass")
    assert registry.is_owner("glass") is False
    assert _create(client, head).status_code == 201


def test_removing_a_store_leaves_every_forest_untouched(station, tmp_path):
    """J.19.2: a binding is a line in a forest's versioned `_meta/`, and a
    host MUST NOT rewrite a forest's content to reflect a registry change."""
    client, registry, root = station
    head = _both(registry)
    _create(client, head)
    bind = client.put(f"/v1/forests/{FOREST}/ingest/config",
                      json={"assets": "backups"}, headers=head)
    assert bind.status_code == 200, bind.text
    config = root / FOREST / "_meta" / "gardener.yaml"
    before = config.read_bytes()

    assert client.delete("/v1/admin/stores/backups", headers=head).status_code == 200
    assert config.read_bytes() == before
    # The expectation simply stops being met, and the surface says so.
    status = client.get(f"/v1/forests/{FOREST}/ingest", headers=head).json()
    assert status["assets"] == "backups" and status["assets_missing"] is True


def test_every_store_act_is_audited_and_carries_no_secret(station):
    """J.4.1: name, endpoint, bucket, prefix, whether a credential was
    supplied — and an audit table is read by more people, for longer, than
    anything else the Station keeps."""
    client, registry, _ = station
    head = _both(registry)
    _create(client, head)
    client.put("/v1/admin/stores/backups", json={"region": "eu-west-1"},
               headers=head)
    client.delete("/v1/admin/stores/backups", headers=head)

    rows = [r for r in registry.audit(limit=50)
            if str(r["primitive"]).startswith("admin.store")]
    assert {r["primitive"] for r in rows} == {
        "admin.store.create", "admin.store.update", "admin.store.remove"}
    blob = json.dumps(rows, default=str)
    assert SECRET not in blob and ACCESS not in blob
    assert "forest-assets" in blob and "backups" in blob


# ===========================================================================
# F.220 — the test proves the write
# ===========================================================================


def test_the_probe_heads_writes_and_deletes_under_the_prefix(station, stub,
                                                             monkeypatch):
    client, registry, _ = station
    head = _both(registry)
    _local(client, head, monkeypatch)

    r = client.post("/v1/admin/stores/backups/test", json={}, headers=head)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert [s["step"] for s in body["steps"]] == ["head", "write", "delete"]
    assert all(s["ok"] for s in body["steps"])
    # The probe never leaves the prefix (J.19.3 rule 3).
    assert body["probe"].startswith("teams/")
    assert [c[0] for c in stub.calls] == ["head_bucket", "put_object",
                                          "delete_object"]


def test_a_read_only_grant_fails_at_the_write_and_says_so(station, monkeypatch):
    """L.6's rule about a required role with no binding, applied to a
    credential: a read-only grant passes every check a listing could make
    and fails at the first archive, at whatever hour ingest runs."""
    from monkeyllm import fetch

    client, registry, _ = station
    head = _both(registry)
    _local(client, head, monkeypatch)
    monkeypatch.setattr(fetch, "s3_client", Stub(writable=False))

    body = client.post("/v1/admin/stores/backups/test", json={},
                       headers=head).json()
    assert body["ok"] is False
    assert [s["step"] for s in body["steps"]] == ["head", "write"]
    assert body["steps"][-1]["ok"] is False
    assert "AccessDenied" in body["steps"][-1]["error"]


def test_a_probe_that_cannot_be_deleted_is_not_a_pass(station, monkeypatch):
    from monkeyllm import fetch

    client, registry, _ = station
    head = _both(registry)
    _local(client, head, monkeypatch)
    monkeypatch.setattr(fetch, "s3_client", Stub(deletable=False))

    body = client.post("/v1/admin/stores/backups/test", json={},
                       headers=head).json()
    assert body["ok"] is False
    assert [s["step"] for s in body["steps"]] == ["head", "write", "delete"]
    assert body["steps"][0]["ok"] and body["steps"][1]["ok"]
    assert body["steps"][2]["ok"] is False


def test_a_private_endpoint_is_refused_by_the_provider_variable(station, stub,
                                                                monkeypatch):
    """The SAME variable the provider route reads: it states one deployment
    posture, and a deployment that is half-guarded is guarded by nobody."""
    client, registry, _ = station
    head = _both(registry)
    _create(client, head, name="local", bucket="local-bucket",
            endpoint="http://127.0.0.1:9000")

    r = client.post("/v1/admin/stores/local/test", json={}, headers=head)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "E_SCHEMA"
    assert "MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE" in r.json()["error"]["hint"]
    assert stub.calls == [], "refused before it is contacted"

    monkeypatch.setenv("MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE", "1")
    ok = client.post("/v1/admin/stores/local/test", json={}, headers=head)
    assert ok.status_code == 200 and ok.json()["ok"] is True
    # ...and the provider route reads the same switch, unchanged.
    probe = client.post("/v1/admin/providers/test",
                        json={"endpoint": "http://127.0.0.1:9000/v1"},
                        headers=head)
    assert probe.status_code == 200


def test_a_typed_destination_sends_no_stored_credential(station, stub,
                                                        monkeypatch):
    """J.3.2 custody rule 2, asserted at the stub, which records what it was
    given."""
    client, registry, _ = station
    head = _both(registry)
    _local(client, head, monkeypatch)

    client.post("/v1/admin/stores/backups/test",
                json={"bucket": "somebody-elses-bucket"}, headers=head)
    assert stub.secret_of() is None
    assert stub.seen[-1].access_key is None

    # The store's own destination still attaches it.
    client.post("/v1/admin/stores/backups/test", json={}, headers=head)
    assert stub.secret_of() == SECRET


# ===========================================================================
# F.221 — the environment-declared store
# ===========================================================================


@pytest.fixture()
def env_station(two_forests, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.setenv("MONKEYLLM_S3_BUCKET", "declared-bucket")
    monkeypatch.setenv("MONKEYLLM_S3_ENDPOINT", "https://minio.example.com")
    monkeypatch.setenv("MONKEYLLM_S3_PREFIX", "forests/")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", ACCESS)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", SECRET)
    path = tmp_path / "station.db"
    app = build_app(root=two_forests, registry_path=path, mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, path


def test_the_environment_store_is_published_read_only(env_station):
    client, registry, db_path = env_station
    head = _both(registry)

    listed = client.get("/v1/admin/stores", headers=head).json()["stores"]
    assert [s["name"] for s in listed] == ["env"]
    env = listed[0]
    assert env["origin"] == "environment" and env["bucket"] == "declared-bucket"
    assert env["prefix"] == "forests" and env["has_key"] is True
    assert SECRET not in json.dumps(listed)

    # The registry file is a backup target and the environment is not.
    assert SECRET.encode() not in db_path.read_bytes()
    assert ACCESS.encode() not in db_path.read_bytes()

    for r in (client.put("/v1/admin/stores/env", json={"region": "x"}, headers=head),
              client.delete("/v1/admin/stores/env", headers=head)):
        assert r.status_code == 400, r.text
        assert "environment" in r.json()["error"]["message"]


def test_the_environment_store_claims_its_bucket_too(env_station):
    """One store per bucket includes the declared one: otherwise the
    by-bucket lookup would stop being total the moment somebody typed the
    same bucket into the console."""
    client, registry, _ = env_station
    head = _both(registry)
    r = client.post("/v1/admin/stores",
                    json={**STORE, "name": "typed", "endpoint":
                          "https://minio.example.com", "bucket": "declared-bucket"},
                    headers=head)
    assert r.status_code == 400
    assert "env" in r.json()["error"]["message"]


def test_no_variables_means_no_store(station):
    client, registry, _ = station
    assert client.get("/v1/admin/stores",
                      headers=_both(registry)).json()["stores"] == []


# ===========================================================================
# The resolver (J.19.7/J.19.8) — reads follow the BUCKET
# ===========================================================================


def test_the_resolver_answers_by_name_and_by_bucket(station):
    client, registry, _ = station
    head = _both(registry)
    _create(client, head)
    _create(client, head, name="archive", bucket="cold-bucket")

    from monkeyllm_station.stores import StoreResolver

    resolver = StoreResolver(registry)
    assert resolver.by_name("backups").bucket == "forest-assets"
    assert resolver.by_name("backups").secret_key == SECRET
    assert resolver.by_bucket("cold-bucket").name == "archive"
    assert resolver.by_name("nope") is None and resolver.by_bucket("nope") is None

    # A forest re-bound to another store still reads the bucket its
    # passports name (J.19.7): the lookup never consults a binding.
    client.put(f"/v1/forests/{FOREST}/ingest/config",
               json={"assets": "archive"}, headers=head)
    assert resolver.by_bucket("forest-assets").name == "backups"


def test_the_binding_is_a_name_and_it_is_committed(station):
    """G.6 rule 3: a setting that decides where a forest's bytes live MUST
    travel with the forest, so writing `assets` commits it through the
    narrow `_meta` door."""
    client, registry, root = station
    head = _both(registry)
    _create(client, head)

    r = client.put(f"/v1/forests/{FOREST}/ingest/config",
                   json={"assets": "backups"}, headers=head)
    assert r.status_code == 200, r.text
    config = (root / FOREST / "_meta" / "gardener.yaml").read_text()
    assert re.search(r"(?m)^assets: backups$", config)
    assert SECRET not in config and "objects.example.com" not in config

    import subprocess
    tracked = subprocess.run(
        ["git", "ls-files", "_meta/gardener.yaml"], cwd=root / FOREST,
        capture_output=True, text=True).stdout
    assert "_meta/gardener.yaml" in tracked, "an untracked file travels in no snapshot"

    # And it clears.
    client.put(f"/v1/forests/{FOREST}/ingest/config", json={"assets": None},
               headers=head)
    assert client.get(f"/v1/forests/{FOREST}/ingest",
                      headers=head).json()["assets"] is None


def test_binding_an_unconfigured_store_is_refused(station):
    client, registry, _ = station
    head = _both(registry)
    r = client.put(f"/v1/forests/{FOREST}/ingest/config",
                   json={"assets": "nowhere"}, headers=head)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "E_SCHEMA"


# ===========================================================================
# F.226 — proxied under the ceiling, redirected over it
# ===========================================================================


def _plant_remote(client, head, forest_dir: Path, node_id: str, uri: str,
                  digest: str):
    """A media node pointing at an object. C.7.5 forbids planting one that
    names no bytes, so the passport is edited after the plant — which is
    also how this state arises in the field (a forest whose archive went to
    a store an older Station knew nothing about)."""
    local = f"_assets/{node_id.rsplit('/', 1)[-1]}.png"
    target = forest_dir / node_id.rsplit("/", 1)[0] / local
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PNG_BYTES)
    node = {"id": node_id, "parent": f"{node_id.rsplit('/', 1)[0]}/_index",
            "type": "media", "title": node_id.rsplit("/", 1)[-1],
            "summary": "A media passport whose bytes live in an object store.",
            "payload": local, "payload_type": "image", "payload_hash": digest}
    r = client.post(f"/v1/forests/{FOREST}/plant", json={"node": node},
                    headers=head)
    assert r.status_code == 200, r.text
    passport = forest_dir / f"{node_id}.md"
    text = passport.read_text(encoding="utf-8")
    text, n = re.subn(r"(?m)^payload:.*$", f"payload: {uri}", text)
    assert n == 1
    passport.write_text(text, encoding="utf-8")
    target.unlink()


def _remote_station(client, registry, head, stub, objects: dict):
    _create(client, head)
    stub.objects.update(objects)


def test_a_small_remote_payload_is_proxied_through_the_cache(station, stub):
    client, registry, root = station
    head = _key(registry, "reader", (FOREST, OTHER), caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    _remote_station(client, registry, head, stub,
                    {"teams/shot.png": PNG_BYTES})
    _plant_remote(client, head, root / FOREST, "notes/v84-shot",
                  "s3://forest-assets/teams/shot.png", digest)

    r = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-shot", headers=head)
    assert r.status_code == 200, r.text
    assert r.content == PNG_BYTES
    assert r.headers["etag"] == digest
    assert ("head_object", "teams/shot.png") in stub.calls
    assert ("download_file", "teams/shot.png") in stub.calls

    # The conditional request is honoured, exactly as it is for local bytes.
    again = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-shot",
                       headers={**head, "If-None-Match": digest})
    assert again.status_code == 304

    entry = registry.audit(limit=1, principal="reader")[0]
    assert entry["primitive"] == "payload" and entry["size"] == len(PNG_BYTES)


def test_a_large_remote_payload_is_redirected_and_the_url_is_never_recorded(
        station, stub, monkeypatch):
    monkeypatch.setenv("MONKEYLLM_STATION_PAYLOAD_PROXY_MAX_MB", "0.0001")
    monkeypatch.setenv("MONKEYLLM_STATION_PAYLOAD_PRESIGN_TTL", "120")
    client, registry, root = station
    head = _key(registry, "reader", (FOREST, OTHER),
                caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    _remote_station(client, registry, head, stub, {"teams/big.mp4": PNG_BYTES})
    _plant_remote(client, head, root / FOREST, "notes/v84-big",
                  "s3://forest-assets/teams/big.mp4", digest)

    r = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-big",
                   headers=head, follow_redirects=False)
    assert r.status_code == 302, r.text
    assert "X-Amz-Signature" in r.headers["location"]
    assert ("presign", "teams/big.mp4", 120) in stub.calls
    # Nothing was downloaded to redirect it.
    assert not any(c[0] == "download_file" for c in stub.calls)

    row = registry.audit(limit=1, principal="reader")[0]
    blob = json.dumps(row, default=str)
    assert "X-Amz-Signature" not in blob and "store.example" not in blob
    assert row["size"] == len(PNG_BYTES)


def test_the_url_may_be_asked_for_instead_of_followed(station, stub,
                                                      monkeypatch):
    """J.14 rule 5: the SAME URL on a second line.

    It exists because both obvious alternatives fail for a console: J.5.13
    pins the page to `connect-src 'self'`, so a credentialed fetch cannot
    follow a 302 to a store's origin, and a bare link to this route is a
    top-level navigation carrying no credential — J.2 authenticates by
    header and never by cookie — so it would answer 401 to everyone.
    """
    monkeypatch.setenv("MONKEYLLM_STATION_PAYLOAD_PROXY_MAX_MB", "0.0001")
    monkeypatch.setenv("MONKEYLLM_STATION_PAYLOAD_PRESIGN_TTL", "120")
    client, registry, root = station
    head = _key(registry, "reader", (FOREST, OTHER),
                caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    _remote_station(client, registry, head, stub, {"teams/ask.mp4": PNG_BYTES})
    _plant_remote(client, head, root / FOREST, "notes/v84-ask",
                  "s3://forest-assets/teams/ask.mp4", digest)
    url = f"/v1/forests/{FOREST}/payload/notes/v84-ask"

    redirected = client.get(url, headers=head, follow_redirects=False)
    asked = client.get(url, headers={**head, "Accept": "application/json"})
    assert redirected.status_code == 302
    assert asked.status_code == 200, asked.text
    body = asked.json()
    # The same URL the `Location` would have carried, minted the same way.
    assert body["url"].split("X-Amz-Expires")[0] == \
        redirected.headers["location"].split("X-Amz-Expires")[0]
    assert "X-Amz-Signature" in body["url"]
    assert [c for c in stub.calls if c[0] == "presign"] == \
        [("presign", "teams/ask.mp4", 120)] * 2
    # Rule 4: still no bytes, and rule 1's authority was spent first.
    assert not any(c[0] == "download_file" for c in stub.calls)
    assert asked.headers["cache-control"] == "private, no-store"
    expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    ahead = (expires - datetime.now(timezone.utc)).total_seconds()
    assert 0 < ahead <= 120

    # Rule 5: the SAME audit row — `Accept:` is a rendering choice, not a
    # different act — and rule 2 holds on it, signature and all.
    row = registry.audit(limit=1, principal="reader")[0]
    blob = json.dumps(row, default=str)
    assert "X-Amz-Signature" not in blob and "store.example" not in blob
    assert row["size"] == len(PNG_BYTES)

    # A wildcard is not an ask: a browser and a bare `curl` both send `*/*`,
    # and answering them a document about the download is the one thing this
    # rule must not do.
    wild = client.get(url, headers={**head, "Accept": "*/*"},
                      follow_redirects=False)
    assert wild.status_code == 302


def test_the_json_form_is_only_for_what_would_redirect(station, stub):
    """Under the ceiling there is no URL to hand out: the bytes are served
    through the cache, and `Accept: application/json` changes nothing."""
    client, registry, root = station
    head = _key(registry, "reader", (FOREST, OTHER),
                caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    _remote_station(client, registry, head, stub,
                    {"teams/small.png": PNG_BYTES})
    _plant_remote(client, head, root / FOREST, "notes/v84-small",
                  "s3://forest-assets/teams/small.png", digest)

    r = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-small",
                   headers={**head, "Accept": "application/json"})
    assert r.status_code == 200
    assert r.content == PNG_BYTES
    assert not any(c[0] == "presign" for c in stub.calls)


def test_a_scheme_that_cannot_sign_is_proxied_or_refused(station, tmp_path):
    """J.14 rule 3: inventing a redirect for a scheme that cannot sign one
    would hand out an unauthenticated URL."""
    client, registry, root = station
    head = _key(registry, "reader", (FOREST, OTHER),
                caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    elsewhere = tmp_path / "elsewhere.png"
    elsewhere.write_bytes(PNG_BYTES)
    _plant_remote(client, head, root / FOREST, "notes/v84-file",
                  elsewhere.as_uri(), digest)

    under = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-file",
                       headers=head)
    assert under.status_code == 200 and under.content == PNG_BYTES


def test_a_file_payload_over_the_ceiling_names_the_ceiling(station, tmp_path,
                                                           monkeypatch):
    monkeypatch.setenv("MONKEYLLM_STATION_PAYLOAD_PROXY_MAX_MB", "0.0001")
    client, registry, root = station
    head = _key(registry, "reader", (FOREST, OTHER),
                caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    elsewhere = tmp_path / "big.png"
    elsewhere.write_bytes(PNG_BYTES)
    _plant_remote(client, head, root / FOREST, "notes/v84-filebig",
                  elsewhere.as_uri(), digest)

    r = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-filebig",
                   headers=head)
    assert r.status_code == 400, r.text
    assert "MONKEYLLM_STATION_PAYLOAD_PROXY_MAX_MB" in r.json()["error"]["hint"]


def test_an_object_the_store_does_not_hold_reads_as_absent(station, stub):
    """The map says bytes exist and the store disagrees: to the reader that
    is the same absent payload a missing local file is (J.14/J.3)."""
    client, registry, root = station
    head = _key(registry, "reader", (FOREST, OTHER),
                caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    _remote_station(client, registry, head, stub, {})
    _plant_remote(client, head, root / FOREST, "notes/v84-absent",
                  "s3://forest-assets/teams/absent.png", digest)

    r = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-absent", headers=head)
    other = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-nothing",
                       headers=head)
    assert r.status_code == other.status_code == 404
    assert r.text.replace("v84-absent", "X") == other.text.replace("v84-nothing", "X")
    assert not any(c[0] == "download_file" for c in stub.calls)


def test_a_store_that_errors_is_not_reported_as_an_absence(station, monkeypatch):
    """An outage is not an absence: `E_NOT_FOUND` here would tell an
    operator their payload is gone, which is the one wrong thing to say."""
    from monkeyllm import fetch

    client, registry, root = station
    head = _key(registry, "reader", (FOREST, OTHER),
                caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    made = Stub()
    monkeypatch.setattr(fetch, "s3_client", made)
    _create(client, head)
    _plant_remote(client, head, root / FOREST, "notes/v84-down",
                  "s3://forest-assets/teams/down.png", digest)

    def explode(creds=None, *, timeout=None):
        raise RuntimeError("EndpointConnectionError")

    monkeypatch.setattr(fetch, "s3_client", explode)
    r = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-down", headers=head)
    assert r.status_code == 502, r.text
    assert r.json()["error"]["code"] == "E_INTERNAL"
    assert "forest-assets" not in r.text and "teams/down.png" not in r.text


def test_a_tampered_object_is_refused_and_reads_as_absent(station, stub):
    """G.9 rule 1: a corrupted or tampered download never reaches the agent
    — and to the reader it is the same absent payload a missing local file
    is (J.3's invariant)."""
    client, registry, root = station
    head = _key(registry, "reader", (FOREST, OTHER),
                caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    _remote_station(client, registry, head, stub,
                    {"teams/wrong.png": b"different bytes entirely"})
    _plant_remote(client, head, root / FOREST, "notes/v84-wrong",
                  "s3://forest-assets/teams/wrong.png", digest)

    r = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-wrong", headers=head)
    absent = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-never",
                        headers=head)
    assert r.status_code == absent.status_code == 404
    assert r.text.replace("v84-wrong", "X") == absent.text.replace("v84-never", "X")


def test_out_of_scope_is_the_same_envelope_as_an_unserved_bucket_is_not(
        station, stub):
    """The store refusal may differ because it is reachable only for a node
    the caller already holds; the SCOPE refusal may not."""
    client, registry, root = station
    admin = _key(registry, "reader", (FOREST,), caps=("read", "write", "admin"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    _plant_remote(client, admin, root / FOREST, "notes/v84-scope",
                  "s3://nobodys-bucket/x.png", digest)

    scoped = _key(registry, "narrow", (), caps=())
    registry.grant("narrow", FOREST, {"read"}, allow=["ops/"])
    hidden = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-scope",
                        headers=scoped)
    absent = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-nothing",
                        headers=scoped)
    assert hidden.status_code == absent.status_code == 404
    assert hidden.text.replace("v84-scope", "X") \
        == absent.text.replace("v84-nothing", "X")
    assert stub.calls == [], "the store lookup never runs before the scope check"

    named = client.get(f"/v1/forests/{FOREST}/payload/notes/v84-scope",
                       headers=admin)
    assert named.status_code == 404
    assert "nobodys-bucket" in named.json()["error"]["message"]


# ===========================================================================
# Part I — a snapshot counts the tier it does not hold
# ===========================================================================


def test_the_snapshot_route_forwards_with_remote_and_reports_the_counts(
        station, monkeypatch):
    """Part I (v0.84): the default packs the local tier and not the remote
    one, and the count is what keeps `payloads: N` from meaning both *this
    is everything* and *this is everything I bothered with*."""
    client, registry, _ = station
    head = _both(registry)
    registry.set_owner("boss") if hasattr(registry, "set_owner") else None
    seen = {}

    def fake_create(root, *, out, with_payloads=True, with_remote=False,
                    stores=None):
        seen["with_payloads"] = with_payloads
        seen["with_remote"] = with_remote
        # J.19.8: packing a remote object is a READ of a store. Without the
        # resolver every object would be reported unreachable on the very
        # deployment that serves it, and the snapshot would be silently
        # short — so the forwarding is asserted, not assumed.
        seen["stores"] = stores
        Path(out).write_bytes(b"PACK")
        return {"snapshot": str(out), "bytes": 4, "payloads": 2,
                "payloads_omitted": 0, "payloads_remote": 7,
                "remote_packed": 7 if with_remote else 0}

    monkeypatch.setattr("monkeyllm.snapshot.create_snapshot", fake_create)

    plain = client.post("/v1/admin/snapshots", json={"forest": FOREST},
                        headers=head)
    assert plain.status_code == 200, plain.text
    assert seen["with_remote"] is False
    assert plain.json()["payloads_remote"] == 7

    packed = client.post("/v1/admin/snapshots",
                         json={"forest": FOREST, "with_remote": True},
                         headers=head)
    assert packed.status_code == 200, packed.text
    assert seen["with_remote"] is True
    assert seen["stores"] is not None
    assert packed.json()["remote_packed"] == 7
