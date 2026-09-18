# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""J.19 / G.3.1 / J.14 against a REAL object store (spec v0.84).

Every other test in this round puts a double behind `fetch.s3_client`, which
is the right shape — the engine has ONE door to a socket and the suite holds
it in memory — and it proves everything except the one thing a double cannot:
that the door opens. A double answers what we thought S3 answers. This module
asks MinIO.

What that difference has actually caught, and why each step is here:

* **path-style addressing.** A virtual-hosted request to a homelab MinIO
  resolves `<bucket>.<host>` and fails at DNS, not at the API — a fake never
  builds a URL, so it never has an opinion about this.
* **the `HEAD`-then-`PUT` dedup.** `head_object` raising `404` versus
  `NoSuchKey` versus a `ClientError` with a code inside is exactly the
  variation `fetch._is_absent` reads by NAME instead of by type, and a
  double that raises our own class proves that reading works on our own
  class.
* **presigning.** A signature that is merely a string in a fake is a
  signature a store either accepts or rejects here.
* **the ETag fast-path.** `sync` skips an object whose size and ETag match,
  and the ETag of a multipart or server-side-encrypted object is not the
  digest anybody expects.

**Skipped unless the deployment is named in the environment.** Four
variables, and no endpoint, bucket or credential is ever written into this
file or any other — `MONKEYLLM_TEST_S3_ENDPOINT`, `MONKEYLLM_TEST_S3_BUCKET`,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. Everything this module writes
goes under one unique prefix per run and is deleted in a `finally`, whatever
happened above it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request
import uuid
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

ENDPOINT_ENV = "MONKEYLLM_TEST_S3_ENDPOINT"
BUCKET_ENV = "MONKEYLLM_TEST_S3_BUCKET"

REQUIRED = (ENDPOINT_ENV, BUCKET_ENV, "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY")

pytestmark = pytest.mark.skipif(
    not all(os.environ.get(v) for v in REQUIRED),
    reason=f"live object store not configured ({', '.join(REQUIRED)})")

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" * 512
PDF = b"%PDF-1.4 the original nobody kept\n" + b"x" * 4096
DOCS = 30


# ---------------------------------------------------------------------------
# The store, and the prefix everything this run writes lives under
# ---------------------------------------------------------------------------

def _raw_client(creds):
    from monkeyllm import fetch

    return fetch.s3_client(creds, timeout=20)


@pytest.fixture(scope="module")
def live():
    """One store record, one prefix, and a `finally` that empties it.

    The prefix is the containment: `StoreCredentials.contains` refuses a key
    outside it (G.3.1 rule 2), so nothing this module writes can land beside
    somebody else's objects, and the cleanup can delete everything it sees
    under the prefix without reading what it is.
    """
    from monkeyllm.fetch import StoreCredentials

    prefix = f"itest/{uuid.uuid4().hex[:12]}"
    creds = StoreCredentials(
        name="live",
        bucket=os.environ[BUCKET_ENV],
        endpoint=os.environ[ENDPOINT_ENV],
        prefix=prefix,
        region=os.environ.get("AWS_DEFAULT_REGION") or "us-east-1",
        access_key=os.environ["AWS_ACCESS_KEY_ID"],
        secret_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        # A homelab MinIO answers on a host, not on `<bucket>.<host>`: a
        # virtual-hosted request fails at DNS before it is ever a request.
        path_style=True,
    )
    try:
        yield creds
    finally:
        client = _raw_client(creds)
        token = None
        while True:
            kwargs = {"Bucket": creds.bucket, "Prefix": prefix + "/"}
            if token:
                kwargs["ContinuationToken"] = token
            page = client.list_objects_v2(**kwargs) or {}
            for item in page.get("Contents") or []:
                client.delete_object(Bucket=creds.bucket, Key=item["Key"])
            if not page.get("IsTruncated"):
                break
            token = page.get("NextContinuationToken")


@pytest.fixture()
def stores(live):
    from monkeyllm.fetch import StoreMap

    return StoreMap([live])


def put(creds, key: str, body: bytes) -> str:
    """An object under this run's prefix. Returns its `s3://` URI."""
    full = creds.key_for(key)
    _raw_client(creds).put_object(Bucket=creds.bucket, Key=full, Body=body)
    return creds.uri(full)


def keys_under(creds, sub: str = "") -> list[str]:
    from monkeyllm.fetch import list_objects

    prefix = creds.key_for(sub) if sub else creds.prefix
    return sorted(o["key"] for o in list_objects(creds, prefix))


def forest_at(root: Path, *, stores, converters=None, config=None):
    from monkeyllm.forest import init_forest
    from monkeyllm.gardener import Gardener
    from monkeyllm.vine import Vine

    init_forest(root, title="Live Forest")
    vine = Vine(root, writable=True, stores=stores)
    gardener = Gardener(vine, converters=converters, hooks=[], stores=stores,
                        curate=False)
    if config:
        gardener.config.update(config)
        gardener._save_config()
    return vine, gardener


class Pdf:
    """A lossy converter, so G.7 rule 5's archive actually runs."""

    extensions = {".pdf"}

    def convert(self, path: Path):
        from monkeyllm.gardener import Conversion

        return Conversion(kind="markdown", title=path.stem,
                          markdown=f"# {path.stem}\n\nExtracted text.\n")


# ===========================================================================
# F.223 / J.19.6 — the archive, against a store that really refuses or writes
# ===========================================================================

def test_a_lossy_original_is_archived_once_and_the_second_time_is_a_head(
        tmp_path, live, stores, monkeypatch):
    from monkeyllm import fetch, gardener as gardener_mod

    puts: list[str] = []
    real_put = fetch.put_object

    def counted(creds, key, data, **kw):
        puts.append(key)
        return real_put(creds, key, data, **kw)

    # Counted around the REAL call, never in place of it: what is being
    # measured is that the second ingest asked and did not write, and a
    # double would be measuring itself.
    monkeypatch.setattr(gardener_mod, "put_object", counted)

    root = tmp_path / "archive"
    vine, g = forest_at(root, stores=stores, converters=[Pdf()],
                        config={"assets": "live"})
    try:
        staging = root / "_derived" / "uploads"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "report.pdf").write_bytes(PDF)
        report = g.sync(staging, paths=["report.pdf"], consume=True)
        assert report["planted"] == ["report"], report

        digest = hashlib.sha256(PDF).hexdigest()
        node = vine.forest.read("report")
        expected = live.uri(live.key_for(root.name, f"{digest}.pdf"))
        assert node.frontmatter["payload"] == expected
        assert node.frontmatter["payload_hash"] == digest
        assert node.frontmatter["payload_type"] == "pdf"
        assert report["archived_remote"] == 1
        # It is really there, under this run's prefix and nowhere else.
        assert expected.rsplit("/", 1)[-1] == f"{digest}.pdf"
        assert live.key_for(root.name, f"{digest}.pdf") in keys_under(live)
        assert len(puts) == 1

        # J.19.6: content-addressed, so the same bytes under another name
        # are the same object — asked for with a HEAD and not written again.
        (staging / "copy.pdf").write_bytes(PDF)
        again = g.sync(staging, paths=["copy.pdf"], consume=True)
        assert again["planted"] == ["copy"]
        assert vine.forest.read("copy").frontmatter["payload"] == expected
        assert len(puts) == 1, "the second ingest uploaded bytes the store had"
    finally:
        vine.close()


def test_the_cache_validates_the_hash_and_refetches_a_corrupted_copy(
        tmp_path, live, stores):
    """G.9: a corrupted or tampered download never reaches the agent — and
    the repair is automatic, because the object is still the truth."""
    from monkeyllm.fetch import PayloadCache

    uri = put(live, "cache/shot.png", PNG)
    digest = hashlib.sha256(PNG).hexdigest()
    cache = PayloadCache(tmp_path / "_derived", stores=stores)

    slot = cache.get(uri, digest)
    assert slot.read_bytes() == PNG

    slot.write_bytes(b"not the object at all")
    healed = cache.get(uri, digest)
    assert healed.read_bytes() == PNG

    with pytest.raises(Exception) as caught:
        cache.get(uri, "0" * 64)
    assert "hash mismatch" in str(caught.value)


def test_a_presigned_url_is_sigv4_and_fetches_the_bytes(live, stores):
    """J.14: the URL a 302 hands out is a bearer credential with a clock on
    it, and the only way to know a store accepts our signature is to use it.

    This is the assertion the live store earned. botocore resolves
    `signature_version` to `s3v4` and still presigns with **SigV2** unless
    the version is set by hand — a compatibility default from before 2014.
    MinIO takes both, so the double and the homelab were both happy; AWS S3
    rejects SigV2 in every region created since, so a deployment there would
    have handed its readers a URL its own store refuses, with the refusal
    arriving in a browser and nothing on this side to read.
    """
    from monkeyllm.fetch import presign

    uri = put(live, "sign/big.mp4", PNG)
    url = presign(uri, 120, stores=stores)
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url, url.split("?", 1)[-1][:80]
    assert "X-Amz-Signature" in url and "X-Amz-Expires=120" in url
    with urllib.request.urlopen(url, timeout=20) as response:
        assert response.read() == PNG


# ===========================================================================
# F.229-F.231 / G.3.1 — a forest from a bucket
# ===========================================================================

def _seed_corpus(live) -> dict[str, bytes]:
    made = {}
    for i in range(DOCS):
        ext = ".md" if i % 3 else ".txt"
        name = f"doc-{i:02d}{ext}"
        body = (f"# Document {i}\n\nTelemetry note number {i} about the "
                f"gateway fleet and its backhaul.\n").encode()
        made[name] = body
        put(live, f"corpus/{name}", body)
    made["picture.png"] = PNG
    put(live, "corpus/picture.png", PNG)
    return made


def test_a_bucket_is_a_source_and_every_address_is_the_object(tmp_path, live,
                                                              stores):
    """G.3.1: the honest answer to "I have ten thousand documents in a
    bucket" — and `origin` names the OBJECT, which is the whole reason a
    mount was not the answer."""
    seeded = _seed_corpus(live)
    root = tmp_path / "bucket"
    vine, g = forest_at(root, stores=stores)
    try:
        source = f"s3://{live.bucket}/{live.key_for('corpus')}"
        report = g.adopt(source)
        assert len(report["planted"]) == len(seeded), report
        assert report["errors"] == []
        # G.4.7: nobody paid for a model, and the report says so rather than
        # looking like one that failed.
        assert report["curation"]["reason"] == "disabled"

        # G.3.1 rule 8: the recorded root is the URI, and it is what a later
        # `sync` re-reads.
        assert g.config["source_root"] == source
        assert g.config["content"] == "cached"

        for node_id in report["planted"]:
            node = vine.forest.read(node_id)
            rel = node.frontmatter["source_path"]
            assert node.frontmatter["origin"] == \
                f"s3://{live.bucket}/{live.key_for('corpus/' + rel)}"
            assert "file://" not in json.dumps(node.frontmatter)
        # The BONE stays in the bucket: a binary's payload is the object's
        # own URI and this forest holds zero bytes of it.
        picture = next(n for n in report["planted"] if n.endswith("picture"))
        shot = vine.forest.read(picture)
        assert shot.frontmatter["payload"] == \
            f"s3://{live.bucket}/{live.key_for('corpus/picture.png')}"
        assert shot.frontmatter["payload_type"] == "image"
        assert not list((root).rglob("_assets/*"))
        # Rule 9: the staged copy went as each document landed.
        assert not list((root / "_derived" / "staging").rglob("*.md"))
    finally:
        vine.close()


def test_a_sync_after_one_object_changed_refreshes_exactly_that_one(
        tmp_path, live, stores):
    """G.8 / G.3.1 rule 5: the freshness fast-path is size + ETag, the
    store's own change signal — an object has no mtime anybody may trust."""
    _seed_corpus(live)
    root = tmp_path / "resync"
    vine, g = forest_at(root, stores=stores)
    try:
        source = f"s3://{live.bucket}/{live.key_for('corpus')}"
        planted = g.adopt(source)["planted"]
        assert len(planted) == DOCS + 1

        quiet = g.sync()
        assert quiet["updated"] == [] and quiet["planted"] == []
        assert len(quiet["unchanged"]) == DOCS + 1

        put(live, "corpus/doc-07.md",
            b"# Document 7\n\nThe gateway fleet moved to a new backhaul.\n")
        after = g.sync()
        assert after["updated"] == ["doc-07"], after
        assert after["planted"] == []
        assert len(after["unchanged"]) == DOCS
        body = vine.pick("doc-07")["body"]
        assert "new backhaul" in body
    finally:
        vine.close()


# ===========================================================================
# J.19.3 / J.14 — the Station, against the same store
# ===========================================================================

@pytest.fixture()
def station(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    for var in ("MONKEYLLM_STATION_ADMIN", "MONKEYLLM_STATION_PASSWORD",
                "MONKEYLLM_S3_BUCKET", "MONKEYLLM_S3_ENDPOINT",
                "MONKEYLLM_S3_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    # J.10.2's rule, which a homelab endpoint is exactly the case for: a
    # private address is refused unless the deployment says otherwise. This
    # is configuration, not a credential.
    monkeypatch.setenv("MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE", "1")
    root = tmp_path / "registry"
    build_forest(root / "forest-live")
    app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, root


def _admin(registry, principal="boss"):
    key = registry.issue_key(principal)
    registry.grant(principal, "forest-live", {"read", "write", "admin"})
    return {"Authorization": f"Bearer {key}"}


def _store_body(live, name="live"):
    """The record the console POSTs. Read from the environment at call time;
    no endpoint and no key is written into this repository."""
    return {"name": name, "endpoint": live.endpoint, "bucket": live.bucket,
            "prefix": live.prefix, "region": live.region,
            "path_style": True,
            "access_key": live.access_key, "secret_key": live.secret_key}


def test_the_store_probe_writes_and_removes_a_real_object(station, live):
    """J.19.3: the test WRITES, because a read-only grant passes a `HEAD`
    and fails at the first ingest instead."""
    client, registry, _ = station
    head = _admin(registry)
    made = client.post("/v1/admin/stores", json=_store_body(live), headers=head)
    assert made.status_code == 201, made.text
    assert "secret_key" not in json.dumps(made.json())

    r = client.post("/v1/admin/stores/live/test", headers=head)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body
    assert [s["step"] for s in body["steps"]] == ["head", "write", "delete"]
    assert all(s["ok"] for s in body["steps"])
    # It left nothing behind, which is the third step's whole claim.
    assert body["probe"] not in keys_under(live)


def test_the_payload_route_redirects_and_answers_the_url_as_json(
        station, live, monkeypatch):
    """J.14 rules 1-5 against a real signature: the 302's `Location` and the
    JSON's `url` both fetch the object, and neither reaches the audit row."""
    monkeypatch.setenv("MONKEYLLM_STATION_PAYLOAD_PROXY_MAX_MB", "0.0001")
    monkeypatch.setenv("MONKEYLLM_STATION_PAYLOAD_PRESIGN_TTL", "120")
    client, registry, root = station
    head = _admin(registry)
    assert client.post("/v1/admin/stores", json=_store_body(live),
                       headers=head).status_code == 201

    uri = put(live, "route/movie.mp4", PNG)
    digest = hashlib.sha256(PNG).hexdigest()
    node = {"id": "notes/live-movie", "parent": "notes/_index",
            "type": "media", "title": "movie",
            "summary": "A recording whose bytes live in an object store.",
            "payload": "_assets/movie.mp4", "payload_type": "video",
            "payload_hash": digest}
    local = root / "forest-live" / "notes" / "_assets" / "movie.mp4"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(PNG)
    planted = client.post("/v1/forests/forest-live/plant",
                          json={"node": node}, headers=head)
    assert planted.status_code == 200, planted.text
    # C.7.5 forbids planting a media node that names no bytes, so the
    # passport is pointed at the object afterwards — which is also how this
    # state arises in the field.
    passport = root / "forest-live" / "notes" / "live-movie.md"
    text, n = re.subn(r"(?m)^payload:.*$", f"payload: {uri}",
                      passport.read_text(encoding="utf-8"))
    assert n == 1
    passport.write_text(text, encoding="utf-8")
    local.unlink()

    url = "/v1/forests/forest-live/payload/notes/live-movie"
    redirected = client.get(url, headers=head, follow_redirects=False)
    assert redirected.status_code == 302, redirected.text
    with urllib.request.urlopen(redirected.headers["location"],
                                timeout=20) as response:
        assert response.read() == PNG

    asked = client.get(url, headers={**head, "Accept": "application/json"})
    assert asked.status_code == 200, asked.text
    with urllib.request.urlopen(asked.json()["url"], timeout=20) as response:
        assert response.read() == PNG

    # Rule 2, on a signature a real store minted. The endpoint IS in the
    # governance row on purpose (J.4.1: name, endpoint, bucket, prefix,
    # whether a credential was supplied); what may never be there is the
    # credential — the stored one, or the one in a signed URL's tail.
    rows = json.dumps(registry.audit(limit=6, principal="boss"), default=str)
    for forbidden in ("X-Amz-Signature", "X-Amz-Credential", live.secret_key):
        assert forbidden not in rows, forbidden
    payloads = [r for r in registry.audit(limit=6, principal="boss")
                if r["primitive"] == "payload"]
    assert len(payloads) == 2 and all(r["size"] == len(PNG) for r in payloads)
    assert all('"redirect": "True"' in r["args"] for r in payloads), \
        "the row says the bytes left by address, whichever line carried it"
