# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""J.19 object stores, G.7 rule 5 lossiness, A.3 `video`/`file` (spec v0.84).

The engine halves of F.219-F.228. Two doubles and no network:

* a **fake S3 client** — an in-memory dict with `head_object`, `put_object`,
  `get_object`, `download_file`, `delete_object`, `list_objects_v2` and
  `generate_presigned_url` — injected by replacing `fetch.s3_client`, which
  every call site looks up through the module for exactly this reason;
* a **fake resolver**, which is the J.19.8 seam itself: two questions,
  `by_name` and `by_bucket`, handed at construction.

The negative controls are the point of the file: with nothing configured
every path here is byte-identical to v0.83, compared as bytes and not as a
flag (F.222), and a secret never reaches a repr, a report or an error.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from monkeyllm import fetch
from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.fetch import StoreCredentials, StoreMap
from monkeyllm.forest import Forest, init_forest
from monkeyllm.gardener import Conversion, Gardener, unmet_store
from monkeyllm.vine import Vine

SECRET = "s3cr3t-never-printed"
PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


# ---------------------------------------------------------------------------
# The doubles
# ---------------------------------------------------------------------------

class Absent(Exception):
    response = {"Error": {"Code": "404"}}


class FakeS3:
    """An object store in a dict, which records every call it was given."""

    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.calls: list[tuple] = []
        self.fail_put = False

    # -- the operations the engine uses ------------------------------------
    def head_object(self, Bucket, Key):  # noqa: N803 - boto3's own spelling
        self.calls.append(("head", Bucket, Key))
        if (Bucket, Key) not in self.objects:
            raise Absent()
        data = self.objects[(Bucket, Key)]
        return {"ContentLength": len(data),
                "ETag": '"' + hashlib.md5(data).hexdigest() + '"'}

    def put_object(self, Bucket, Key, Body):  # noqa: N803
        self.calls.append(("put", Bucket, Key))
        if self.fail_put:
            raise RuntimeError("store refused the upload")
        self.objects[(Bucket, Key)] = bytes(Body)

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.calls.append(("delete", Bucket, Key))
        self.objects.pop((Bucket, Key), None)

    def download_file(self, bucket, key, dest):
        self.calls.append(("get", bucket, key))
        if (bucket, key) not in self.objects:
            raise Absent()
        Path(dest).write_bytes(self.objects[(bucket, key)])

    def list_objects_v2(self, **kwargs):
        bucket = kwargs["Bucket"]
        prefix = kwargs.get("Prefix") or ""
        self.calls.append(("list", bucket, prefix))
        items = [
            {"Key": key, "Size": len(data),
             "ETag": '"' + hashlib.md5(data).hexdigest() + '"',
             "LastModified": None}
            for (b, key), data in sorted(self.objects.items())
            if b == bucket and key.startswith(prefix)
        ]
        return {"Contents": items, "IsTruncated": False}

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
        self.calls.append(("sign", Params["Bucket"], Params["Key"]))
        return (f"https://example.invalid/{Params['Bucket']}/{Params['Key']}"
                f"?X-Amz-Expires={ExpiresIn}&X-Amz-Signature=deadbeef")

    # -- assertions the tests make -----------------------------------------
    def kinds(self, kind: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == kind]


@pytest.fixture()
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(fetch, "s3_client",
                        lambda creds=None, timeout=None: fake)
    return fake


def store(name="backups", bucket="bones", prefix="mk", **kw) -> StoreCredentials:
    return StoreCredentials(name=name, bucket=bucket, prefix=prefix,
                            endpoint="https://minio.invalid",
                            access_key="AKIA-FAKE", secret_key=SECRET, **kw)


@pytest.fixture()
def clean_env(monkeypatch):
    for var in ("MONKEYLLM_S3_BUCKET", "MONKEYLLM_S3_PREFIX",
                "MONKEYLLM_S3_ENDPOINT", "MONKEYLLM_S3_REGION",
                "MONKEYLLM_S3_PATH_STYLE"):
        monkeypatch.delenv(var, raising=False)


class Pdf:
    """A lossy converter for a format the engine ships no reader for."""

    extensions = {".pdf"}

    def convert(self, path: Path) -> Conversion:
        return Conversion(kind="markdown", title=path.stem,
                          markdown=f"# {path.stem}\n\nExtracted text.\n")


class Epub:
    """A converter for an extension `PAYLOAD_TYPE_BY_EXT` does not name."""

    extensions = {".epub"}

    def convert(self, path: Path) -> Conversion:
        return Conversion(kind="markdown", title=path.stem,
                          markdown=f"# {path.stem}\n\nChapters.\n")


def make_forest(root: Path, *, stores=None, converters=None, config=None):
    init_forest(root, title="Storage Forest")
    vine = Vine(root, writable=True, stores=stores)
    gardener = Gardener(vine, converters=converters, hooks=[], stores=stores)
    if config:
        gardener.config.update(config)
        gardener._save_config()
    return vine, gardener


def staged(root: Path, name: str, data: bytes) -> Path:
    """A file in the forest's own upload staging — the courier's copy."""
    staging = root / "_derived" / "uploads"
    staging.mkdir(parents=True, exist_ok=True)
    f = staging / name
    f.write_bytes(data)
    return f


# ===========================================================================
# F.219 / J.19.8 — the record, and what it is never allowed to say
# ===========================================================================

class TestTheRecord:
    def test_a_credential_prints_nothing(self):
        creds = store()
        for text in (repr(creds), str(creds), f"{creds}", "%s" % (creds,)):
            assert SECRET not in text
            assert "AKIA-FAKE" not in text
        assert creds.has_key is True
        assert "has_key=True" in repr(creds)

    def test_a_credential_never_reaches_an_error(self, tmp_path, s3, clean_env):
        """A refusal names the bucket and nothing else (G.9, v0.84)."""
        stores = StoreMap([store(bucket="ours")])
        with pytest.raises(VineError) as e:
            fetch.store_for_read("theirs", stores)
        text = f"{e.value.code} {e.value.message} {e.value.hint}"
        assert "theirs" in text
        assert SECRET not in text and "AKIA-FAKE" not in text
        assert "minio.invalid" not in text and "backups" not in text
        assert e.value.code == E_NOT_FOUND

    def test_the_seam_answers_two_questions(self):
        stores = StoreMap([store(), store(name="cold", bucket="deep")])
        assert stores.by_name("cold").bucket == "deep"
        assert stores.by_bucket("bones").name == "backups"
        assert stores.by_name("nope") is None
        assert stores.by_bucket("nope") is None

    def test_a_store_client_presigns_with_sigv4(self, clean_env):
        """J.14: the URL a redirect hands out must be one the store accepts.

        Found against a live MinIO and fixed here, because no double could
        have found it: botocore resolves `signature_version` to `s3v4` and
        then presigns with **SigV2** unless the version was set by hand — a
        compatibility default from before 2014. MinIO takes both, so nothing
        failed anywhere we looked; AWS S3 rejects SigV2 in every region
        created since, so the reader would have been redirected to a URL
        their own store refuses, with the refusal arriving in a browser and
        nothing on this side to read.

        No network: building a client and signing a URL makes no request.
        """
        pytest.importorskip("boto3")
        client = fetch.s3_client(store())
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": "bones", "Key": "mk/x.pdf"},
            ExpiresIn=60)
        assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url
        assert "AWSAccessKeyId=" not in url, "SigV2 — see the docstring"

    def test_key_is_built_under_the_prefix_and_contains_decides(self):
        creds = store(prefix="teams/")
        assert creds.key_for("forest-a", "abc.pdf") == "teams/forest-a/abc.pdf"
        assert creds.contains("teams/legal")
        assert not creds.contains("finance")
        assert StoreCredentials(bucket="b").contains("anything")


# ===========================================================================
# F.221 — the environment-declared store, and the untouched default
# ===========================================================================

class TestEnvStore:
    def test_the_variables_declare_it(self, monkeypatch, clean_env):
        assert fetch.env_store() is None
        monkeypatch.setenv("MONKEYLLM_S3_BUCKET", "envbucket")
        monkeypatch.setenv("MONKEYLLM_S3_PREFIX", "forests/")
        monkeypatch.setenv("MONKEYLLM_S3_ENDPOINT", "https://minio.invalid")
        env = fetch.env_store()
        assert env is not None
        assert (env.name, env.bucket, env.prefix) == ("env", "envbucket", "forests")
        # J.19.4: the credential is NOT read here — boto3's own chain
        # resolves it, so an instance-role deployment holds no key at all.
        assert env.access_key is None and env.secret_key is None

    def test_nothing_configured_is_v083(self, clean_env):
        """The floor: with nothing declared, a bucket is not refused."""
        assert fetch.bucket_served("anything") is True
        assert fetch.store_for_read("anything") is None

    def test_an_engine_with_one_store_refuses_every_other_bucket(
            self, monkeypatch, clean_env):
        monkeypatch.setenv("MONKEYLLM_S3_BUCKET", "mine")
        assert fetch.bucket_served("mine") is True
        assert fetch.bucket_served("yours") is False
        with pytest.raises(VineError) as e:
            fetch.store_for_read("yours")
        assert "yours" in e.value.message
        assert "MONKEYLLM_S3_BUCKET" in (e.value.hint or "")


# ===========================================================================
# F.222 — the write, the dedup, and the negative control
# ===========================================================================

# One fixed instant for the staged file of a comparison, so that "byte
# identical" can mean it. `source_mtime` is the source file's OWN clock
# (G.8's fast-path reads it back), so two forests built one after the other
# differ in it by however long the first one took — which under a loaded
# machine is however long anything took. Stripping the line would compare
# everything else; pinning the clock compares everything.
FIXED_MTIME = 1_700_000_000


def tree_bytes(root: Path) -> dict[str, bytes]:
    """Every file the forest holds, git and derived excluded."""
    out = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        # `.git/` is history, `_derived/` is disposable by contract, and
        # `.vine.lock` is this process's own pid and clock — none of them is
        # the forest, and the lock would make any two runs differ by a
        # second.
        if rel.startswith((".git/", "_derived/")) or rel == ".vine.lock":
            continue
        out[rel] = p.read_bytes()
    return out


class TestTheWrite:
    def test_content_addressed_key_and_three_fields(self, tmp_path, s3, clean_env):
        creds = store()
        stores = StoreMap([creds])
        root = tmp_path / "f1"
        vine, g = make_forest(root, stores=stores, converters=[Pdf()],
                              config={"assets": "backups"})
        try:
            data = b"%PDF-1.4 report bytes"
            digest = hashlib.sha256(data).hexdigest()
            src = staged(root, "report.pdf", data)
            report = g.sync(root / "_derived" / "uploads",
                            paths=["report.pdf"], consume=True)
            assert report["planted"] == ["report"]
            node = Forest(root).read("report")
            expected = f"s3://bones/mk/{root.name}/{digest}.pdf"
            assert node.frontmatter["payload"] == expected
            assert node.frontmatter["payload_type"] == "pdf"
            assert node.frontmatter["payload_hash"] == digest
            assert ("bones", f"mk/{root.name}/{digest}.pdf") in s3.objects
            # The courier consumed its copy and the original still exists.
            assert not src.exists()
            assert report["archived_remote"] == 1
        finally:
            vine.close()

    def test_the_head_dedups_the_same_bytes(self, tmp_path, s3, clean_env):
        """An upload whose key already exists is skipped after a `HEAD`.

        The key carries the FOREST ID (J.19.6), so the dedup is within one
        bucket's forest prefix: two forests sharing a store can never
        collide, which is the property that paragraph buys and the reason
        the same bytes in a second forest are a second object.
        """
        stores = StoreMap([store()])
        root = tmp_path / "dedup"
        vine, g = make_forest(root, stores=stores, converters=[Pdf()],
                              config={"assets": "backups"})
        try:
            data = b"%PDF-1.4 same bytes"
            staged(root, "a.pdf", data)
            g.sync(root / "_derived" / "uploads", paths=["a.pdf"], consume=True)
            assert len(s3.kinds("put")) == 1
            # The same bytes under a different name are the same object.
            staged(root, "b.pdf", data)
            g.sync(root / "_derived" / "uploads", paths=["b.pdf"], consume=True)
            assert len(s3.kinds("put")) == 1
            assert len(s3.kinds("head")) == 2
            assert Forest(root).read("a").frontmatter["payload"] == \
                Forest(root).read("b").frontmatter["payload"]
        finally:
            vine.close()

    def test_nothing_configured_is_byte_identical(self, tmp_path, s3, clean_env):
        """The negative control, compared as BYTES and not as a flag."""
        made = {}
        for name, stores, config in (("bare", None, None),
                                     ("bare2", None, None)):
            root = tmp_path / name
            vine, g = make_forest(root, stores=stores, converters=[Pdf()],
                                  config=config)
            try:
                src = staged(root, "report.pdf", b"%PDF-1.4 report bytes")
                # The one field that is a CLOCK rather than a fact about the
                # forest (G.8's fast-path records the source's own mtime).
                # Pinned rather than stripped, so the comparison below is
                # every byte and not every byte we thought to keep.
                os.utime(src, (FIXED_MTIME, FIXED_MTIME))
                g.sync(root / "_derived" / "uploads", paths=["report.pdf"],
                       consume=True)
                made[name] = tree_bytes(root)
            finally:
                vine.close()
        a, b = made["bare"], made["bare2"]
        assert set(a) == set(b)
        for rel in a:
            assert a[rel] == b[rel], rel
        # …and the original is under _assets/, named by v0.83's own formula,
        # with no call made to any store.
        digest = hashlib.sha256(b"%PDF-1.4 report bytes").hexdigest()
        assert f"_assets/{digest[:8]}-report.pdf" in a
        assert s3.calls == []

    def test_unmet_binding_falls_back_and_is_named(self, tmp_path, s3, clean_env):
        root = tmp_path / "unmet"
        stores = StoreMap([])  # a deployment that has no such store
        vine, g = make_forest(root, stores=stores, converters=[Pdf()],
                              config={"assets": "gone"})
        try:
            staged(root, "report.pdf", b"%PDF-1.4 report bytes")
            report = g.sync(root / "_derived" / "uploads", paths=["report.pdf"],
                            consume=True)
            node = Forest(root).read("report")
            assert node.frontmatter["payload"].startswith("_assets/")
            assert (root / "report._assets").exists() is False
            assert report["archived_remote"] == 0
            # validate says it…
            assert unmet_store(g.config, stores) == "gone"
            # …and so does the H.3 health report.
            from monkeyllm.ranger import Ranger

            health = Ranger(vine).health()
            assert health["stores_missing"]["binding"] == "gone"
        finally:
            vine.close()

    def test_a_failed_upload_keeps_the_bytes_locally_and_says_so(
            self, tmp_path, s3, clean_env):
        root = tmp_path / "flaky"
        stores = StoreMap([store()])
        vine, g = make_forest(root, stores=stores, converters=[Pdf()],
                              config={"assets": "backups"})
        try:
            s3.fail_put = True
            staged(root, "report.pdf", b"%PDF-1.4 report bytes")
            report = g.sync(root / "_derived" / "uploads", paths=["report.pdf"],
                            consume=True)
            node = Forest(root).read("report")
            # The passport records what ACTUALLY happened. The reverse
            # failure — naming an object the store does not hold — is the
            # one that must never occur.
            assert node.frontmatter["payload"].startswith("_assets/")
            assert (root / node.frontmatter["payload"]).is_file()
            assert len(report["archive_fallbacks"]) == 1
            named = report["archive_fallbacks"][0]
            assert "report.pdf" in named and "backups" in named
            assert SECRET not in named
            assert s3.objects == {}
        finally:
            vine.close()

    def test_the_binding_travels_in_git(self, tmp_path, s3, clean_env):
        root = tmp_path / "committed"
        vine, g = make_forest(root, config={"assets": "backups"})
        try:
            tracked = subprocess.run(
                ["git", "-C", str(root), "ls-files", "_meta"],
                capture_output=True, text=True, check=True).stdout.split()
            assert "_meta/gardener.yaml" in tracked
        finally:
            vine.close()


# ===========================================================================
# F.223 — the read follows the bucket
# ===========================================================================

class TestTheRead:
    def _forest_with_remote_image(self, tmp_path, s3, stores, bucket="bones"):
        root = tmp_path / "remote"
        init_forest(root, title="Remote")
        vine = Vine(root, writable=True, stores=stores)
        digest = hashlib.sha256(PNG).hexdigest()
        key = f"mk/{root.name}/{digest}.png"
        s3.objects[(bucket, key)] = PNG
        vine.plant({
            "id": "shot", "type": "media", "parent": "_index",
            "title": "Shot", "summary": "A screenshot kept in an object store.",
            "payload": f"s3://{bucket}/{key}", "payload_type": "image",
            "payload_hash": digest, "source": "ingest",
        }, adopted=True)
        return vine, f"s3://{bucket}/{key}", digest

    def test_a_rebound_forest_still_reads_its_old_bucket(self, tmp_path, s3,
                                                         clean_env):
        old = store(name="old", bucket="bucket-a")
        new = store(name="new", bucket="bucket-b")
        stores = StoreMap([old, new])
        vine, uri, digest = self._forest_with_remote_image(
            tmp_path, s3, stores, bucket="bucket-a")
        try:
            # The forest is bound to `new`; the payload names bucket-a, and
            # the BUCKET decides the credential.
            got = vine.view("shot")
            assert Path(got["path"]).read_bytes() == PNG
            assert got["payload_hash"] == digest
            assert vine.look("shot")["payload_remote"] is True
        finally:
            vine.close()

    def test_an_unserved_bucket_names_the_bucket_and_nothing_else(
            self, tmp_path, s3, clean_env):
        stores = StoreMap([store(bucket="ours")])
        vine, uri, digest = self._forest_with_remote_image(
            tmp_path, s3, stores, bucket="theirs")
        try:
            with pytest.raises(VineError) as e:
                vine.view("shot")
            text = f"{e.value.message} {e.value.hint}"
            assert e.value.code == E_NOT_FOUND
            assert "theirs" in text
            assert digest not in text          # never the key
            assert "minio.invalid" not in text  # never the endpoint
            assert "backups" not in text        # never the store
        finally:
            vine.close()

    def test_absent_and_payload_less_stay_one_envelope(self, tmp_path, s3,
                                                       clean_env):
        root = tmp_path / "j3"
        init_forest(root, title="J3")
        vine = Vine(root, writable=True)
        try:
            vine.plant({"id": "plain", "type": "note", "parent": "_index",
                        "title": "Plain", "summary": "A note with no bytes at all."})
            with pytest.raises(VineError) as absent:
                vine.view("no-such-node")
            with pytest.raises(VineError) as payload_less:
                vine.view("plain")
            assert absent.value.code == payload_less.value.code == E_NOT_FOUND
            assert (absent.value.message.replace("no-such-node", "X")
                    == payload_less.value.message.replace("plain", "X"))
            assert absent.value.hint == payload_less.value.hint
        finally:
            vine.close()

    def test_a_hash_mismatch_refetches(self, tmp_path, s3, clean_env):
        stores = StoreMap([store()])
        vine, uri, digest = self._forest_with_remote_image(tmp_path, s3, stores)
        try:
            slot = vine.payload_cache.slot_for(uri)
            slot.parent.mkdir(parents=True, exist_ok=True)
            slot.write_bytes(b"not the object")
            got = vine.view("shot")
            assert Path(got["path"]).read_bytes() == PNG
        finally:
            vine.close()


# ===========================================================================
# F.224 — a lossy original survives its own upload
# ===========================================================================

class TestLossiness:
    def test_a_staged_pdf_is_archived_under_archive_never(self, tmp_path, s3,
                                                          clean_env):
        root = tmp_path / "pdf"
        vine, g = make_forest(root, converters=[Pdf()])
        try:
            assert g.config.get("archive", "never") == "never"
            staged(root, "report.pdf", b"%PDF-1.4 lossy")
            g.sync(root / "_derived" / "uploads", paths=["report.pdf"],
                   consume=True)
            node = Forest(root).read("report")
            payload = node.frontmatter["payload"]
            assert payload.startswith("_assets/")
            assert (root / payload).read_bytes() == b"%PDF-1.4 lossy"
            assert node.frontmatter["payload_type"] == "pdf"
        finally:
            vine.close()

    def test_a_staged_markdown_is_not_archived(self, tmp_path, s3, clean_env):
        root = tmp_path / "md"
        vine, g = make_forest(root)
        try:
            staged(root, "note.md", b"# Note\n\nThe body IS the bytes.\n")
            g.sync(root / "_derived" / "uploads", paths=["note.md"],
                   consume=True)
            node = Forest(root).read("note")
            assert "payload" not in node.frontmatter
            assert not list(root.rglob("_assets/*"))
        finally:
            vine.close()

    def test_a_staged_database_is_stored_exactly_once(self, tmp_path, s3,
                                                      clean_env):
        import sqlite3

        root = tmp_path / "db"
        vine, g = make_forest(root)
        try:
            db = tmp_path / "seed.db"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE t (a TEXT)")
            conn.execute("INSERT INTO t VALUES ('x')")
            conn.commit()
            conn.close()
            staged(root, "seed.db", db.read_bytes())
            g.sync(root / "_derived" / "uploads", paths=["seed.db"],
                   consume=True)
            node = Forest(root).read("seed")
            assert node.frontmatter["payload"] == "seed.db"
            assert not list(root.rglob("_assets/*"))
        finally:
            vine.close()

    def test_a_durable_source_is_referenced_not_copied(self, tmp_path, s3,
                                                       clean_env):
        root = tmp_path / "durable"
        src = tmp_path / "dump"
        src.mkdir()
        (src / "report.pdf").write_bytes(b"%PDF-1.4 durable")
        vine, g = make_forest(root, converters=[Pdf()])
        try:
            g.adopt(src)
            node = Forest(root).read("report")
            assert "payload" not in node.frontmatter
            assert not list(root.rglob("_assets/*"))
            assert node.frontmatter["source_path"] == "report.pdf"
        finally:
            vine.close()

    def test_archive_always_still_means_always(self, tmp_path, s3, clean_env):
        root = tmp_path / "always"
        src = tmp_path / "dump2"
        src.mkdir()
        (src / "report.pdf").write_bytes(b"%PDF-1.4 durable")
        vine, g = make_forest(root, converters=[Pdf()],
                              config={"archive": "always"})
        try:
            g.adopt(src)
            node = Forest(root).read("report")
            assert node.frontmatter["payload"].startswith("_assets/")
        finally:
            vine.close()


# ===========================================================================
# F.225 — `video` and `file`
# ===========================================================================

class TestPayloadTypes:
    def test_a_video_plants_media_with_payload_type_video(self, tmp_path, s3,
                                                          clean_env):
        root = tmp_path / "video"
        vine, g = make_forest(root)
        try:
            staged(root, "standup.mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 32)
            report = g.sync(root / "_derived" / "uploads",
                            paths=["standup.mp4"], consume=True)
            assert report["planted"] == ["standup"]
            node = Forest(root).read("standup")
            assert node.frontmatter["type"] == "media"
            assert node.frontmatter["payload_type"] == "video"
        finally:
            vine.close()

    def test_an_unnamed_extension_is_referenced_as_file(self, tmp_path, s3,
                                                        clean_env):
        root = tmp_path / "epub"
        vine, g = make_forest(root, converters=[Epub()])
        try:
            staged(root, "book.epub", b"PK\x03\x04epub")
            g.sync(root / "_derived" / "uploads", paths=["book.epub"],
                   consume=True)
            node = Forest(root).read("book")
            # Before v0.84 these bytes were copied and referenced by nothing.
            assert node.frontmatter["payload_type"] == "file"
            assert (root / node.frontmatter["payload"]).is_file()
        finally:
            vine.close()

    def test_sync_never_retypes_a_pre_v084_node(self, tmp_path, s3, clean_env):
        """A node's type is decided at birth and is never recomputed."""
        root = tmp_path / "retype"
        src = tmp_path / "dump3"
        src.mkdir()
        (src / "clip.mp4").write_bytes(b"first")
        vine, g = make_forest(root)
        try:
            g.adopt(src)
            node_path = Forest(root).path_for("clip")
            text = node_path.read_text(encoding="utf-8")
            # Hand-edit the passport back to what v0.83 would have written.
            node_path.write_text(text.replace("type: media", "type: document"),
                                 encoding="utf-8")
            vine.catalog.upsert_node(Forest(root).read("clip"))
            (src / "clip.mp4").write_bytes(b"second")
            g.sync(src)
            assert Forest(root).read("clip").frontmatter["type"] == "document"
        finally:
            vine.close()

    def test_the_enum_accepts_both_and_refuses_an_invented_one(self, tmp_path):
        root = tmp_path / "enum"
        init_forest(root, title="Enum")
        vine = Vine(root, writable=True)
        try:
            (root / "clip.mp4").write_bytes(b"bytes")
            for ptype in ("video", "file"):
                vine.plant({"id": f"n-{ptype}", "type": "document",
                            "parent": "_index", "title": ptype.title(),
                            "summary": "A node naming bytes of a known kind.",
                            "payload": "clip.mp4", "payload_type": ptype})
            with pytest.raises(VineError) as e:
                vine.plant({"id": "bad", "type": "document", "parent": "_index",
                            "title": "Bad", "summary": "A node naming a kind "
                            "of bytes nobody declared.",
                            "payload": "clip.mp4", "payload_type": "hologram"})
            assert "video" in e.value.message and "file" in e.value.message
        finally:
            vine.close()


# ===========================================================================
# F.227 — `view` reaches a remote image and never a video
# ===========================================================================

class TestView:
    def _media(self, tmp_path, s3, stores, *, ptype, name, data):
        root = tmp_path / f"view-{ptype}"
        init_forest(root, title="View")
        vine = Vine(root, writable=True, stores=stores)
        digest = hashlib.sha256(data).hexdigest()
        key = f"mk/{root.name}/{digest}{Path(name).suffix}"
        s3.objects[("bones", key)] = data
        vine.plant({"id": "m", "type": "media", "parent": "_index",
                    "title": "M", "summary": "Bytes kept in an object store.",
                    "payload": f"s3://bones/{key}", "payload_type": ptype,
                    "payload_hash": digest, "source": "ingest"}, adopted=True)
        return vine, key

    def test_a_remote_image_is_reached(self, tmp_path, s3, clean_env):
        stores = StoreMap([store()])
        vine, key = self._media(tmp_path, s3, stores, ptype="image",
                                name="a.png", data=PNG)
        try:
            got = vine.view("m")
            assert Path(got["path"]).read_bytes() == PNG
            assert got["media_type"] == "image/png"
            assert got["remote_uri"] == f"s3://bones/{key}"
        finally:
            vine.close()

    def test_an_oversized_image_is_refused_without_being_fetched(
            self, tmp_path, s3, clean_env):
        from monkeyllm.vine import VIEW_MAX_BYTES

        stores = StoreMap([store()])
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (VIEW_MAX_BYTES + 16)
        vine, key = self._media(tmp_path, s3, stores, ptype="image",
                                name="big.png", data=big)
        try:
            s3.calls.clear()
            with pytest.raises(VineError) as e:
                vine.view("m")
            assert e.value.code == E_SCHEMA
            assert "view limit" in e.value.message
            assert "J.14" in (e.value.hint or "") or "payload route" in (e.value.hint or "")
            # One HEAD, no GET — asserted at the stub.
            assert len(s3.kinds("head")) == 1
            assert s3.kinds("get") == []
        finally:
            vine.close()

    def test_a_video_is_refused_by_type_and_named_to_the_byte_route(
            self, tmp_path, s3, clean_env):
        stores = StoreMap([store()])
        vine, key = self._media(tmp_path, s3, stores, ptype="video",
                                name="clip.mp4", data=b"\x00" * 128)
        try:
            s3.calls.clear()
            with pytest.raises(VineError) as e:
                vine.view("m")
            assert e.value.code == E_SCHEMA
            assert "not an image" in e.value.message
            assert "J.14" in (e.value.hint or "")
            assert s3.calls == []  # decided by type, before any network call
        finally:
            vine.close()


# ===========================================================================
# resolve_payload — the one resolution the byte route and `view` share
# ===========================================================================

class TestResolvePayload:
    def test_local_and_remote_answer_the_same_shape(self, tmp_path, s3,
                                                    clean_env):
        stores = StoreMap([store()])
        root = tmp_path / "resolve"
        init_forest(root, title="Resolve")
        vine = Vine(root, writable=True, stores=stores)
        try:
            (root / "local.png").write_bytes(PNG)
            vine.plant({"id": "local", "type": "media", "parent": "_index",
                        "title": "Local", "summary": "Bytes beside the passport.",
                        "payload": "local.png", "payload_type": "image",
                        "payload_hash": hashlib.sha256(PNG).hexdigest()})
            digest = hashlib.sha256(PNG).hexdigest()
            s3.objects[("bones", "mk/x.png")] = PNG
            vine.plant({"id": "far", "type": "media", "parent": "_index",
                        "title": "Far", "summary": "Bytes kept in a store.",
                        "payload": "s3://bones/mk/x.png", "payload_type": "image",
                        "payload_hash": digest, "source": "ingest"}, adopted=True)

            near = vine.resolve_payload("local")
            assert near["local_path"] and near["remote_uri"] is None
            assert near["bytes"] == len(PNG)
            assert near["media_type"] == "image/png"

            s3.calls.clear()
            far = vine.resolve_payload("far")
            assert far["local_path"] is None
            assert far["remote_uri"] == "s3://bones/mk/x.png"
            assert far["bytes"] == len(PNG)
            assert s3.kinds("get") == []   # a HEAD, never a fetch

            pulled = vine.resolve_payload("far", fetch=True)
            assert Path(pulled["local_path"]).read_bytes() == PNG

            with pytest.raises(VineError) as e:
                vine.resolve_payload("nope")
            assert e.value.code == E_NOT_FOUND
        finally:
            vine.close()

    def test_presign_is_minted_and_never_for_a_scheme_that_cannot_sign(
            self, tmp_path, s3, clean_env):
        stores = StoreMap([store()])
        s3.objects[("bones", "mk/x.png")] = PNG
        url = fetch.presign("s3://bones/mk/x.png", 300, stores=stores)
        assert "X-Amz-Signature" in url
        assert fetch.can_presign("file:///tmp/x.png") is False
        with pytest.raises(VineError) as e:
            fetch.presign("file:///tmp/x.png", 300, stores=stores)
        assert e.value.code == E_SCHEMA
        assert "J.14" in (e.value.hint or "")


# ===========================================================================
# Part I — a snapshot says what it did not pack
# ===========================================================================

class TestSnapshot:
    def _remote_forest(self, tmp_path, s3, stores):
        root = tmp_path / "snap"
        init_forest(root, title="Snap")
        vine = Vine(root, writable=True, stores=stores)
        digest = hashlib.sha256(PNG).hexdigest()
        s3.objects[("bones", "mk/shot.png")] = PNG
        vine.plant({"id": "shot", "type": "media", "parent": "_index",
                    "title": "Shot", "summary": "A screenshot in an object store.",
                    "payload": "s3://bones/mk/shot.png", "payload_type": "image",
                    "payload_hash": digest, "source": "ingest"}, adopted=True)
        vine.close()
        return root

    def test_remote_payloads_are_counted_and_not_packed_by_default(
            self, tmp_path, s3, clean_env):
        from monkeyllm.snapshot import create_snapshot

        stores = StoreMap([store()])
        root = self._remote_forest(tmp_path, s3, stores)
        info = create_snapshot(root, out=tmp_path / "plain.forest", stores=stores)
        assert info["payloads_remote"] == 1
        assert info["remote_packed"] == 0
        import zipfile

        with zipfile.ZipFile(tmp_path / "plain.forest") as zf:
            assert not [n for n in zf.namelist() if "_remote/" in n]

    def test_with_remote_packs_them_under_the_uris_own_shape(
            self, tmp_path, s3, clean_env):
        import zipfile

        from monkeyllm.snapshot import create_snapshot, restore_snapshot

        stores = StoreMap([store()])
        root = self._remote_forest(tmp_path, s3, stores)
        out = tmp_path / "full.forest"
        info = create_snapshot(root, out=out, with_remote=True, stores=stores)
        assert info["remote_packed"] == 1
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
            assert "payloads/_remote/bones/mk/shot.png" in names
            readme = zf.read("README.txt").decode()
            assert "_remote" in readme

        dest = tmp_path / "restored"
        result = restore_snapshot(out, dest, stores=stores)
        assert result["remote_restored"] == 1
        assert result["payloads_missing"] == 0
        assert result["buckets_unserved"] == []
        # The bytes landed in the slot the CACHE computes, never at the
        # member's own path.
        from monkeyllm.fetch import PayloadCache

        cache = PayloadCache(dest / "_derived", stores=stores)
        assert cache.slot_for("s3://bones/mk/shot.png").read_bytes() == PNG
        assert not (dest / "payloads").exists()

    def test_restore_onto_a_deployment_with_no_store_names_the_bucket(
            self, tmp_path, s3, clean_env):
        from monkeyllm.snapshot import create_snapshot, restore_snapshot

        stores = StoreMap([store()])
        root = self._remote_forest(tmp_path, s3, stores)
        out = tmp_path / "moved.forest"
        create_snapshot(root, out=out, stores=stores)
        result = restore_snapshot(out, tmp_path / "elsewhere",
                                  stores=StoreMap([]))
        assert result["payloads_missing"] == 1
        assert result["buckets_unserved"] == ["bones"]

    def test_a_malformed_remote_member_is_refused_never_skipped(self, tmp_path):
        import zipfile

        from monkeyllm.snapshot import _check_container_member

        _check_container_member("payloads/_remote/bones/mk/shot.png")
        for bad in ("payloads/_remote/bones",
                    "payloads/_remote/../escape/x",
                    "payloads/_remote/bones/../../x"):
            with pytest.raises(VineError):
                _check_container_member(bad)

    def test_the_readme_names_a_cached_forests_source(self, tmp_path, s3,
                                                      clean_env):
        import zipfile

        from monkeyllm.snapshot import create_snapshot

        root = tmp_path / "cached"
        vine, g = make_forest(root, config={"content": "cached",
                                            "source_root": "s3://corp/handbook"})
        vine.close()
        out = tmp_path / "cached.forest"
        create_snapshot(root, out=out)
        with zipfile.ZipFile(out) as zf:
            readme = zf.read("README.txt").decode()
        assert "s3://corp/handbook" in readme
        assert "cached" in readme
