# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.9 fetchers + H.6 eviction + Part I snapshots (spec v0.11)."""

import hashlib
import os
import subprocess

import pytest

from monkeyllm.errors import E_QUERY_FORBIDDEN, E_SCHEMA, VineError
from monkeyllm.fetch import PayloadCache
from monkeyllm.parser import serialize_node

DATASET = "sales/report-q1-2026"


@pytest.fixture()
def remote_dataset(vine_rw, forest_rw, tmp_path):
    """Move the fixture dataset's .db to a fake bucket (file:// = the test
    double for object storage) and point the passport at the URI."""
    node = vine_rw.forest.read(DATASET)
    db = forest_rw / "sales" / "report-q1-2026.db"
    bucket = tmp_path / "bucket"
    bucket.mkdir()
    remote = bucket / "report-q1-2026.db"
    remote.write_bytes(db.read_bytes())
    digest = hashlib.sha256(remote.read_bytes()).hexdigest()

    fm = dict(node.frontmatter)
    fm["payload"] = remote.as_uri()
    fm["payload_hash"] = digest
    assert node.path is not None
    node.path.write_text(serialize_node(fm, node.body), encoding="utf-8", newline="\n")
    vine_rw.catalog.upsert_node(vine_rw.forest.read(DATASET))
    db.unlink()  # nothing local: only the bucket has the bytes now
    return remote, digest


class TestRemotePayloads:
    def test_query_downloads_once_then_serves_from_cache(self, vine_rw, forest_rw,
                                                         remote_dataset):
        remote, _ = remote_dataset
        q = vine_rw.query(DATASET, "SELECT COUNT(*) FROM sales")
        assert q["rows"][0][0] > 0
        cached = list((forest_rw / "_derived" / "payloads").iterdir())
        assert len(cached) == 1
        remote.unlink()  # bucket goes away: the cache keeps serving
        q2 = vine_rw.query(DATASET, "SELECT COUNT(*) FROM sales")
        assert q2["rows"][0][0] == q["rows"][0][0]

    def test_hash_mismatch_is_refused(self, vine_rw, remote_dataset):
        remote, _ = remote_dataset
        remote.write_bytes(b"tampered bytes")
        with pytest.raises(VineError) as e:
            vine_rw.query(DATASET, "SELECT COUNT(*) FROM sales")
        assert e.value.code == E_SCHEMA and "mismatch" in e.value.message

    def test_tend_rejects_remote_payloads(self, vine_rw, remote_dataset):
        with pytest.raises(VineError) as e:
            vine_rw.tend(DATASET, "INSERT INTO sales VALUES "
                                  "('2026-03-31','A-1','X','South','direct',1,1.0,0.5)")
        assert e.value.code == E_QUERY_FORBIDDEN
        assert "read-only" in e.value.message

    def test_prefetch_warms_the_region(self, vine_rw, forest_rw, remote_dataset):
        remote, _ = remote_dataset
        report = vine_rw.prefetch("sales")
        assert report["fetched"] == [DATASET] and not report["errors"]
        remote.unlink()  # parachute landed, camp is warm: bucket not needed
        assert vine_rw.query(DATASET, "SELECT COUNT(*) FROM sales")["rows"][0][0] > 0

    def test_unsupported_scheme(self, tmp_path):
        cache = PayloadCache(tmp_path)
        with pytest.raises(VineError) as e:
            cache.get("ftp://host/x.db")
        assert e.value.code == E_SCHEMA


class TestCacheEviction:
    def test_lru_eviction_drops_the_coldest(self, tmp_path):
        cache = PayloadCache(tmp_path)
        cache.dir.mkdir(parents=True)
        base = 1_700_000_000
        for i, name in enumerate(["cold.db", "warm.db", "hot.db"]):
            f = cache.dir / name
            f.write_bytes(b"x" * 10)
            os.utime(f, (base + i, base + i))
        report = cache.evict(20 / 1_000_000_000)  # budget: 20 bytes of 30
        assert report["evicted"] == 1
        assert not (cache.dir / "cold.db").exists()
        assert (cache.dir / "hot.db").exists() and (cache.dir / "warm.db").exists()

    def test_ranger_run_reports_cache(self, vine_rw):
        from monkeyllm.ranger import Ranger

        report = Ranger(vine_rw).run()
        assert "payload_cache" in report and report["payload_cache"]["evicted"] == 0


class TestSnapshots:
    def test_roundtrip_preserves_nodes_and_history(self, vine_rw, forest_rw, tmp_path):
        from monkeyllm.snapshot import create_snapshot, restore_snapshot
        from monkeyllm.vine import Vine

        commits = subprocess.run(
            ["git", "-C", str(forest_rw), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        info = create_snapshot(forest_rw, out=tmp_path / "f.bundle",
                               with_payloads=True)
        assert (tmp_path / "f.bundle").is_file() and info["payloads"] >= 1

        dest = tmp_path / "restored"
        r = restore_snapshot(tmp_path / "f.bundle", dest,
                             payload_sidecar=info["payload_sidecar"])
        assert r["nodes"] > 0 and r["restored_payloads"] >= 1
        commits2 = subprocess.run(
            ["git", "-C", str(dest), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        assert commits2 == commits  # full audit history travels along

        vine = Vine(dest, writable=False)
        try:
            assert vine.look("concepts/rag")["summary"]
            assert vine.query(DATASET, "SELECT COUNT(*) FROM sales")["rows"][0][0] > 0
        finally:
            vine.close()

    def test_restore_refuses_non_empty_target(self, forest_rw, tmp_path):
        from monkeyllm.snapshot import create_snapshot, restore_snapshot

        info = create_snapshot(forest_rw, out=tmp_path / "f.bundle")
        target = tmp_path / "busy"
        target.mkdir()
        (target / "x.txt").write_text("precious", encoding="utf-8")
        with pytest.raises(VineError) as e:
            restore_snapshot(info["bundle"], target)
        assert e.value.code == E_SCHEMA
        assert (target / "x.txt").read_text(encoding="utf-8") == "precious"
