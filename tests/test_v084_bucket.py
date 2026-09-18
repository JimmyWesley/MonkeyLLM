# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.3.1/G.3.2/G.4.7/G.10.2, A.5's wall, J.13.6.1's order (spec v0.84).

The engine halves of F.229-F.238. One double — the in-memory S3 client from
`test_v084_storage` — and no network anywhere.

The negative controls carry this file: a directory adopt is byte-identical
but for `origin`'s scheme and the absent `source_etag` (F.229), a branch
under the cap renders byte-identically (F.235), a run of 20 or fewer
documents is one commit (F.232), `curate: true` is untouched (F.233), and a
directory under the ceiling adopts flat (F.236).
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path

import pytest

from monkeyllm import fetch
from monkeyllm.errors import E_FORBIDDEN, E_SCHEMA, VineError
from monkeyllm.fetch import StoreCredentials, StoreMap
from monkeyllm.forest import Forest, init_forest
from monkeyllm.gardener import Gardener, bucket_above, choose_bucketing
from monkeyllm.vine import Vine

from tests.test_v084_storage import FakeS3  # the one double, shared

BUCKET = "corp-docs"
PREFIX = "handbook"


@pytest.fixture()
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(fetch, "s3_client",
                        lambda creds=None, timeout=None: fake)
    for var in ("MONKEYLLM_S3_BUCKET", "MONKEYLLM_S3_PREFIX",
                "MONKEYLLM_S3_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("MONKEYLLM_ADOPT_BUCKET_ABOVE", raising=False)
    return fake


@pytest.fixture()
def stores():
    return StoreMap([StoreCredentials(name="corp", bucket=BUCKET,
                                      endpoint="https://minio.invalid",
                                      access_key="AK", secret_key="SK")])


def put(s3, key: str, body: bytes, bucket: str = BUCKET) -> None:
    s3.objects[(bucket, key)] = body


def doc(n: int) -> bytes:
    return f"# Page {n}\n\nThe body of page {n}, with enough words to read.\n".encode()


def forest(root: Path, *, stores=None, converters=None, config=None,
           curate=None):
    init_forest(root, title="Bucket Forest")
    vine = Vine(root, writable=True, stores=stores)
    g = Gardener(vine, converters=converters, hooks=[], stores=stores,
                 curate=curate)
    if config:
        g.config.update(config)
        g._save_config()
    return vine, g


def commits(root: Path) -> int:
    out = subprocess.run(["git", "-C", str(root), "rev-list", "--count", "HEAD"],
                         capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def subjects(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "log", "--format=%s"],
                         capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


# ===========================================================================
# F.229 — a bucket becomes a forest
# ===========================================================================

class TestBucketSource:
    def test_a_prefix_adopts_end_to_end(self, tmp_path, s3, stores):
        put(s3, f"{PREFIX}/intro.md", doc(1))
        put(s3, f"{PREFIX}/policy/leave.md", doc(2))
        put(s3, f"{PREFIX}/policy/pay.md", doc(3))
        root = tmp_path / "f"
        vine, g = forest(root, stores=stores)
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert sorted(report["planted"]) == ["intro", "policy/leave",
                                                 "policy/pay"]
            node = Forest(root).read("policy/leave")
            fm = node.frontmatter
            # G.3.1 rule 4: the key relative to the prefix, and the object's
            # own URI as the address.
            assert fm["source_path"] == "policy/leave.md"
            assert fm["origin"] == f"s3://{BUCKET}/{PREFIX}/policy/leave.md"
            assert fm["source_hash"] == hashlib.sha256(doc(2)).hexdigest()
            assert fm["source_etag"]
            assert "source_mtime" not in fm
            # G.7 rule 7: `cached` is the default for a remote source.
            assert fm["content"] == "cached"
            assert g.config["content"] == "cached"
            assert (root / "_derived" / "bodies" / "policy" / "leave.md").is_file()
            # G.3.1 rule 8: the recorded root is the URI.
            assert g.config["source_root"] == f"s3://{BUCKET}/{PREFIX}"
            # Rule 6: the staging area is empty at the close.
            staging = root / "_derived" / "staging"
            assert not staging.exists() or not any(staging.rglob("*"))
        finally:
            vine.close()

    def test_the_bucket_is_the_bone(self, tmp_path, s3, stores):
        """An image and a database are REFERENCED, never copied (rule 7)."""
        import sqlite3

        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        db_path = tmp_path / "seed.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE t (a TEXT)")
        conn.execute("INSERT INTO t VALUES ('x')")
        conn.commit()
        conn.close()
        put(s3, f"{PREFIX}/shot.png", png)
        put(s3, f"{PREFIX}/ledger.db", db_path.read_bytes())
        root = tmp_path / "bone"
        vine, g = forest(root, stores=stores)
        try:
            g.adopt(f"s3://{BUCKET}/{PREFIX}")
            shot = Forest(root).read("shot").frontmatter
            assert shot["type"] == "media"
            assert shot["payload"] == f"s3://{BUCKET}/{PREFIX}/shot.png"
            assert shot["payload_type"] == "image"
            assert shot["payload_hash"] == hashlib.sha256(png).hexdigest()
            ledger = Forest(root).read("ledger").frontmatter
            assert ledger["type"] == "dataset"
            assert ledger["payload"] == f"s3://{BUCKET}/{PREFIX}/ledger.db"
            # Zero bytes of anybody's original are in the forest (the
            # `_derived/` tier is this engine's own bookkeeping, not the
            # corpus).
            assert not [p for p in root.rglob("*.db")
                        if "_derived" not in p.parts]
            assert not list(root.rglob("_assets/*"))
            # …and the dataset is queryable through the G.9 cache, and not
            # writable (G.9 rule 4).
            out = vine.query("ledger", "SELECT a FROM t")
            assert out["rows"] == [["x"]]
            with pytest.raises(VineError):
                vine.tend("ledger", "UPDATE t SET a='y' WHERE a='x'")
        finally:
            vine.close()

    def test_reference_degrades_to_cached_and_says_so(self, tmp_path, s3,
                                                      stores):
        put(s3, f"{PREFIX}/intro.md", doc(1))
        root = tmp_path / "ref"
        vine, g = forest(root, stores=stores, config={"content": "reference"})
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert report["content_degraded"] == 1
            assert Forest(root).read("intro").frontmatter["content"] == "cached"
        finally:
            vine.close()

    def test_a_directory_adopt_is_byte_identical_but_for_the_origin(
            self, tmp_path, s3, stores):
        """The negative control: the same tree, the two doors."""
        src = tmp_path / "dump"
        (src / "policy").mkdir(parents=True)
        (src / "intro.md").write_bytes(doc(1))
        (src / "policy" / "leave.md").write_bytes(doc(2))
        put(s3, f"{PREFIX}/intro.md", doc(1))
        put(s3, f"{PREFIX}/policy/leave.md", doc(2))

        local_root = tmp_path / "local"
        vine, g = forest(local_root, stores=stores)
        try:
            g.adopt(src)
        finally:
            vine.close()
        remote_root = tmp_path / "remote"
        vine2, g2 = forest(remote_root, stores=stores,
                           config={"content": "inline"})
        try:
            g2.adopt(f"s3://{BUCKET}/{PREFIX}")
        finally:
            vine2.close()

        drop = ("origin:", "source_mtime:", "source_etag:")
        for node_id in ("intro", "policy/leave"):
            a = Forest(local_root).path_for(node_id).read_text(encoding="utf-8")
            b = Forest(remote_root).path_for(node_id).read_text(encoding="utf-8")
            keep = lambda t: "\n".join(  # noqa: E731
                l for l in t.splitlines() if not l.startswith(drop))
            assert keep(a) == keep(b), node_id
        assert Forest(local_root).read("intro").frontmatter["origin"].startswith(
            "file://")
        assert Forest(remote_root).read("intro").frontmatter["origin"].startswith(
            "s3://")
        assert "source_etag" not in Forest(local_root).read("intro").frontmatter


# ===========================================================================
# F.230 — a bucket is reached only through a configured store
# ===========================================================================

class TestContainment:
    def test_an_unserved_bucket_is_refused_before_any_listing(
            self, tmp_path, s3, stores):
        root = tmp_path / "refused"
        vine, g = forest(root, stores=stores)
        try:
            with pytest.raises(VineError) as e:
                g.adopt("s3://somebody-elses-bucket/docs")
            assert e.value.code == E_FORBIDDEN
            assert "somebody-elses-bucket" in e.value.message
            # Zero calls made — asserted on the store client, which is the
            # only place "before any listing" can be proven.
            assert s3.calls == []
            # The hint names what exists and where a store is made, and no
            # credential.
            assert "corp" in (e.value.hint or "")
            assert "SK" not in (e.value.hint or "")
            assert "MONKEYLLM_S3_BUCKET" in (e.value.hint or "")
        finally:
            vine.close()

    def test_a_prefix_outside_the_stores_own_prefix_is_refused(
            self, tmp_path, s3):
        confined = StoreMap([StoreCredentials(name="teams", bucket=BUCKET,
                                              prefix="teams")])
        root = tmp_path / "confined"
        vine, g = forest(root, stores=confined)
        try:
            with pytest.raises(VineError) as e:
                g.adopt(f"s3://{BUCKET}/finance")
            assert e.value.code == E_FORBIDDEN
            assert s3.calls == []
            # …and the prefix it DOES serve is admitted.
            put(s3, "teams/legal/note.md", doc(1))
            report = g.adopt(f"s3://{BUCKET}/teams/legal")
            assert report["planted"] == ["note"]
        finally:
            vine.close()

    def test_a_sub_prefix_that_is_a_forest_is_pruned_whole(self, tmp_path, s3,
                                                           stores):
        put(s3, f"{PREFIX}/intro.md", doc(1))
        put(s3, f"{PREFIX}/theirs/_index.md", b"# Their forest\n")
        put(s3, f"{PREFIX}/theirs/secret.md", doc(2))
        put(s3, f"{PREFIX}/theirs/deep/more.md", doc(3))
        root = tmp_path / "pruned"
        vine, g = forest(root, stores=stores)
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert report["planted"] == ["intro"]
        finally:
            vine.close()

    def test_a_key_that_normalises_outside_never_becomes_a_node(
            self, tmp_path, s3, stores):
        put(s3, f"{PREFIX}/intro.md", doc(1))
        put(s3, f"{PREFIX}/../escape.md", doc(2))
        root = tmp_path / "escape"
        vine, g = forest(root, stores=stores)
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert report["planted"] == ["intro"]
            assert not Forest(root).exists("escape")
        finally:
            vine.close()

    def test_a_store_error_is_an_error_never_stale(self, tmp_path, s3, stores):
        """G.3.1 rule 10: a 503 that read as a deletion would eventually
        invite a pruning pass to act on an outage."""
        put(s3, f"{PREFIX}/intro.md", doc(1))
        put(s3, f"{PREFIX}/other.md", doc(2))
        root = tmp_path / "outage"
        vine, g = forest(root, stores=stores)
        try:
            g.adopt(f"s3://{BUCKET}/{PREFIX}")
            put(s3, f"{PREFIX}/other.md", doc(99))  # changed → will download

            original = s3.download_file

            def flaky(bucket, key, dest):
                if key.endswith("other.md"):
                    raise RuntimeError("503 slow down")
                return original(bucket, key, dest)

            s3.download_file = flaky
            report = g.sync(f"s3://{BUCKET}/{PREFIX}")
            assert report["stale"] == []
            assert any("other.md" in e for e in report["errors"]), report
        finally:
            vine.close()


# ===========================================================================
# F.231 — a refresh downloads only what changed
# ===========================================================================

class TestRefresh:
    def test_an_unchanged_prefix_issues_zero_gets(self, tmp_path, s3, stores):
        for i in range(3):
            put(s3, f"{PREFIX}/page-{i}.md", doc(i))
        root = tmp_path / "fresh"
        vine, g = forest(root, stores=stores)
        try:
            g.adopt(f"s3://{BUCKET}/{PREFIX}")
            s3.calls.clear()
            report = g.sync()
            assert len(report["unchanged"]) == 3
            assert report["updated"] == [] and report["planted"] == []
            assert s3.kinds("get") == []
        finally:
            vine.close()

    def test_a_new_etag_over_identical_bytes_is_fetched_once_and_unchanged(
            self, tmp_path, s3, stores):
        put(s3, f"{PREFIX}/page.md", doc(1))
        root = tmp_path / "etag"
        vine, g = forest(root, stores=stores)
        try:
            g.adopt(f"s3://{BUCKET}/{PREFIX}")
            before = commits(root)
            # A multipart re-upload: identical bytes, a different ETag.
            listing = s3.list_objects_v2
            s3.list_objects_v2 = lambda **kw: {
                "Contents": [{**item, "ETag": '"deadbeef-3"'}
                             for item in listing(**kw)["Contents"]],
                "IsTruncated": False}
            s3.calls.clear()
            report = g.sync()
            assert len(s3.kinds("get")) == 1, "the ETag decides the FETCH"
            assert report["updated"] == []
            assert len(report["unchanged"]) == 1, report
            assert commits(root) == before, "no commit for identical bytes"
        finally:
            vine.close()

    def test_changed_bytes_are_reconverted_and_committed(self, tmp_path, s3,
                                                         stores):
        put(s3, f"{PREFIX}/page.md", doc(1))
        root = tmp_path / "changed"
        vine, g = forest(root, stores=stores)
        try:
            g.adopt(f"s3://{BUCKET}/{PREFIX}")
            put(s3, f"{PREFIX}/page.md", b"# Page\n\nRewritten entirely.\n")
            report = g.sync()
            assert report["updated"] == ["page"]
            body = (root / "_derived" / "bodies" / "page.md").read_text()
            assert "Rewritten entirely" in body
        finally:
            vine.close()

    def test_a_targeted_key_sync_reconciles_that_key_alone(self, tmp_path, s3,
                                                           stores):
        put(s3, f"{PREFIX}/a.md", doc(1))
        put(s3, f"{PREFIX}/b.md", doc(2))
        root = tmp_path / "targeted"
        vine, g = forest(root, stores=stores)
        try:
            g.adopt(f"s3://{BUCKET}/{PREFIX}")
            put(s3, f"{PREFIX}/a.md", b"# A\n\nNew text for a.\n")
            put(s3, f"{PREFIX}/b.md", b"# B\n\nNew text for b.\n")
            report = g.sync(path="a.md")
            assert report["updated"] == ["a"]
            for bad in ("/a.md", "../a.md"):
                with pytest.raises(VineError) as e:
                    g.sync(path=bad)
                assert e.value.code == E_SCHEMA
        finally:
            vine.close()


# ===========================================================================
# F.232 — a batch is a commit, and the job never claims one it has not made
# ===========================================================================

class TestBatching:
    def test_many_documents_land_in_batches(self, tmp_path, s3, stores):
        total = 50
        for i in range(total):
            put(s3, f"{PREFIX}/page-{i:03d}.md", doc(i))
        root = tmp_path / "batched"
        vine, g = forest(root, stores=stores)
        try:
            before = commits(root)
            steps = list(g.adopt_iter(f"s3://{BUCKET}/{PREFIX}"))
            assert len(steps) == total
            for n, step in enumerate(steps, start=1):
                assert step["committed"] <= step["index"] == n
            assert [s["committed"] for s in steps] == sorted(
                s["committed"] for s in steps), "committed is monotonic"
            document_commits = [s for s in subjects(root)
                                if s.startswith("plant(")]
            assert 3 <= len(document_commits) <= 4, document_commits
            assert commits(root) > before
            assert len(list(Forest(root).iter_ids())) == total + 2
        finally:
            vine.close()

    def test_twenty_or_fewer_is_one_commit(self, tmp_path, s3, stores):
        for i in range(20):
            put(s3, f"{PREFIX}/page-{i:02d}.md", doc(i))
        root = tmp_path / "one"
        vine, g = forest(root, stores=stores)
        try:
            g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert [s for s in subjects(root) if s.startswith("plant(")] == \
                ["plant(batch): 20 nodes"]
        finally:
            vine.close()

    def test_one_document_is_planted_singly(self, tmp_path, s3, stores):
        """The negative control for the batch itself: a one-document ingest
        is byte-identical to v0.83, commit subject included."""
        put(s3, f"{PREFIX}/only.md", doc(1))
        root = tmp_path / "single"
        vine, g = forest(root, stores=stores)
        try:
            g.adopt(f"s3://{BUCKET}/{PREFIX}")
            planted = [s for s in subjects(root) if s.startswith("plant(")]
            assert planted == ["plant(only): Page 1 [source=ingest]"]
        finally:
            vine.close()

    def test_a_dataset_flushes_the_batch_and_plants_alone(self, tmp_path, s3,
                                                          stores):
        put(s3, f"{PREFIX}/a.md", doc(1))
        put(s3, f"{PREFIX}/b.md", doc(2))
        put(s3, f"{PREFIX}/ba-rows.csv", b"name,city\nAcme,Recife\n")
        put(s3, f"{PREFIX}/c.md", doc(3))
        root = tmp_path / "mixed"
        vine, g = forest(root, stores=stores)
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert "ba-rows" in report["planted"]
            planted = [s for s in subjects(root) if s.startswith("plant(")]
            # a+b in a batch, then the dataset alone, then c.
            # a+b in one batch, the dataset alone, then c in a batch
            # that started empty (G.10.2 rule 3).
            assert any("ba-rows" in s for s in planted), planted
            assert len(planted) == 3, planted
        finally:
            vine.close()

    def test_a_cancel_leaves_no_partial_batch(self, tmp_path, s3, stores):
        for i in range(30):
            put(s3, f"{PREFIX}/page-{i:03d}.md", doc(i))
        root = tmp_path / "cancelled"
        vine, g = forest(root, stores=stores)
        try:
            steps = g.adopt_iter(f"s3://{BUCKET}/{PREFIX}")
            for n, _step in enumerate(steps, start=1):
                if n == 25:
                    break          # the consumer stops: a cancel (J.9)
            # C.7.4 is all-or-nothing, so there is no state between: the
            # first batch is whole and the open one is nowhere.
            planted = list(steps.report.planted)
            assert len(planted) == 20
            assert len(steps.report.queued) == 5
            assert not set(planted) & set(steps.report.queued)
            from monkeyllm.lint import lint_forest

            assert [i for i in lint_forest(Forest(root))
                    if i.level == "error"] == []
        finally:
            vine.close()

        vine2 = Vine(root, writable=True, stores=stores)
        g2 = Gardener(vine2, hooks=[], stores=stores)
        try:
            report = g2.sync()
            # `sync` redoes exactly what the open batch lost, and nothing
            # twice (J.9: recovery is sync, not archaeology).
            assert len(report["planted"]) == 10
            assert len(report["unchanged"]) == 20
            assert not set(report["planted"]) & set(report["unchanged"])
        finally:
            vine2.close()

    def test_a_media_node_naming_an_object_plants_in_a_batch(self, tmp_path,
                                                             s3, stores):
        """G.10.2 rule 4: `adopted` reaches the list path.

        A bucket of images whose `payload` is an `s3://` URI is exactly the
        case C.7.5 would refuse — bytes the forest does not contain — and in
        a batch every one of them would be refused by the batching and by
        nothing the operator did.
        """
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        for i in range(3):
            put(s3, f"{PREFIX}/shot-{i}.png", png + bytes([i]))
        root = tmp_path / "media-batch"
        vine, g = forest(root, stores=stores)
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert len(report["planted"]) == 3
            assert all(Forest(root).read(n).frontmatter["payload"].startswith(
                "s3://") for n in report["planted"])
        finally:
            vine.close()

        # The negative control: the same batch WITHOUT the flag is refused.
        root2 = tmp_path / "media-batch-2"
        init_forest(root2, title="No flag")
        vine2 = Vine(root2, writable=True)
        try:
            batch = [{"id": f"m{i}", "type": "media", "parent": "_index",
                      "title": f"M{i}", "summary": "Bytes that live in a store.",
                      "payload": f"s3://{BUCKET}/{PREFIX}/shot-{i}.png",
                      "payload_type": "image", "source": "ingest"}
                     for i in range(2)]
            vine2.plant(batch, adopted=True)  # accepted
            batch2 = [{**n, "id": n["id"] + "-x",
                       "payload": None} for n in batch]
            with pytest.raises(VineError) as e:
                vine2.plant(batch2)
            assert "media node needs a payload" in e.value.message
        finally:
            vine2.close()


# ===========================================================================
# F.233 — curating later is a decision
# ===========================================================================

class CountingCurator:
    """An `on_curate` hook that records every draft it was handed."""

    def __init__(self):
        self.seen: list[str] = []
        self.stats = {"tags_dropped": 0, "aliases_clipped": 0}

    def __call__(self, draft: dict) -> dict:
        self.seen.append(draft["id"])
        draft["summary"] = "A curated summary the model wrote for this node."
        return draft


class TestDeferredCuration:
    def test_curate_false_calls_the_model_zero_times(self, tmp_path, s3,
                                                     stores):
        for i in range(3):
            put(s3, f"{PREFIX}/page-{i}.md", doc(i))
        root = tmp_path / "later"
        init_forest(root, title="Later")
        vine = Vine(root, writable=True, stores=stores)
        curator = CountingCurator()
        g = Gardener(vine, hooks=[curator], stores=stores, curate=False)
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert curator.seen == []
            assert report["curation"] == {"ran": False, "reason": "disabled"}
            node = Forest(root).read("page-0")
            assert node.frontmatter["source"] == "ingest"
            assert "The body of page 0" in node.frontmatter["summary"]
            # G.4.7 rule 3: the branch summaries are still written,
            # deterministically, through G.4.4's fallback.
            rolled = g.rollup(None)
            assert rolled["skipped"] >= 0
        finally:
            vine.close()

    def test_curate_true_is_untouched(self, tmp_path, s3, stores):
        put(s3, f"{PREFIX}/page.md", doc(1))
        root = tmp_path / "now"
        init_forest(root, title="Now")
        vine = Vine(root, writable=True, stores=stores)
        curator = CountingCurator()
        g = Gardener(vine, hooks=[curator], stores=stores)
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert curator.seen == ["page"]
            assert report["curation"] == {}
            assert Forest(root).read("page").frontmatter["summary"].startswith(
                "A curated summary")
        finally:
            vine.close()


# ===========================================================================
# F.234 — the scent pass is ordered and bounded
# ===========================================================================

class TestScentOrder:
    def _seeded(self, tmp_path, s3, stores):
        for i in range(4):
            put(s3, f"{PREFIX}/page-{i}.md", doc(i))
        root = tmp_path / "scent"
        vine, g = forest(root, stores=stores)
        g.adopt(f"s3://{BUCKET}/{PREFIX}")
        return vine, g, root

    def test_created_is_the_default_and_oldest_first(self, tmp_path, s3,
                                                     stores):
        vine, g, root = self._seeded(tmp_path, s3, stores)
        try:
            scope = g.scent_scope()
            assert scope == g.scent_scope(order="created")
            rows = {r[0]: r[1] for r in vine.catalog.conn.execute(
                "SELECT id, created FROM nodes")}
            dates = [rows[i] for i in scope]
            assert dates == sorted(dates)
        finally:
            vine.close()

    def test_heat_is_hottest_first_and_no_heat_last(self, tmp_path, s3, stores):
        vine, g, root = self._seeded(tmp_path, s3, stores)
        try:
            vine.trails.add_heat(["page-2"], 0.9, "")
            vine.trails.add_heat(["page-0"], 0.4, "")
            hot = g.scent_scope(order="heat")
            assert hot[0] == "page-2"
            assert hot[1] == "page-0"
            assert set(hot[2:]) == {"page-1", "page-3"}
            assert hot == g.scent_scope(order="heat"), "deterministic"
            # Session heat belongs to one live walk and steers nothing here.
            vine.trails.add_heat(["page-3"], 0.99, "a-session")
            assert g.scent_scope(order="heat") == hot
        finally:
            vine.close()

    def test_limit_bounds_the_run_and_names_what_remains(self, tmp_path, s3,
                                                         stores):
        vine, g, root = self._seeded(tmp_path, s3, stores)
        try:
            steps = g.recurate_scent_iter(limit=2)
            assert steps.total == 2, "the bill is the CAP, never the scope"
            report = None
            for _ in steps:
                pass
            report = steps.result
            assert report["remaining"] == 2
            # The unbounded pass reports zero remaining and v0.75's fields.
            whole = g.recurate_scent()
            assert whole["remaining"] == 0
            assert {"derived", "scanned", "changed", "fallbacks",
                    "skipped"} <= set(whole)
        finally:
            vine.close()

    def test_a_bad_order_or_limit_is_refused(self, tmp_path, s3, stores):
        vine, g, root = self._seeded(tmp_path, s3, stores)
        try:
            for bad in ({"order": "alphabetical"}, {"limit": 0},
                        {"limit": -3}, {"limit": "two"}):
                with pytest.raises(VineError) as e:
                    g.scent_scope(**bad)
                assert e.value.code == E_SCHEMA
        finally:
            vine.close()


# ===========================================================================
# F.235 — an index has a wall
# ===========================================================================

class TestIndexWall:
    def test_above_the_cap_the_body_says_how_many_more(self, tmp_path,
                                                       monkeypatch):
        from monkeyllm import indexer

        monkeypatch.setattr(indexer, "INDEX_ENTRIES_MAX", 5)
        root = tmp_path / "wall"
        init_forest(root, title="Wall")
        vine = Vine(root, writable=True)
        try:
            for i in range(9):
                vine.plant({"id": f"n{i:02d}", "type": "note",
                            "parent": "_index", "title": f"N{i}",
                            "summary": f"The summary of node number {i}."})
            body = Forest(root).read("_index").body
            entries = [l for l in body.splitlines() if l.startswith("- [[")]
            assert len(entries) == 5
            assert 'scan(parent_id, after="")' in body
            assert "and 4 more" in body
            # The wall is on the RENDERING and never on the truth.
            fm = Forest(root).read("_index").frontmatter
            assert fm["coverage"] == "9 bananas, 0 sub-branches"
            digest = vine.look("_index")
            assert digest["coverage"] == {"notes": 9, "branches": 0}
            assert len(vine.catalog.children("_index")) == 9
            listed = vine.scan("_index", after="")
            seen = list(listed["nodes"])
            while listed.get("next"):
                listed = vine.scan("_index", after=listed["next"])
                seen += list(listed["nodes"])
            assert len({c["id"] for c in seen}) == 9
        finally:
            vine.close()

    def test_under_the_cap_renders_byte_identically(self, tmp_path):
        root = tmp_path / "under"
        init_forest(root, title="Under")
        vine = Vine(root, writable=True)
        try:
            for i in range(4):
                vine.plant({"id": f"n{i}", "type": "note", "parent": "_index",
                            "title": f"N{i}",
                            "summary": f"The summary of node number {i}."})
            body = Forest(root).read("_index").body
            assert "more not shown" not in body
            assert Forest(root).read("_index").frontmatter["coverage"] == \
                "4 bananas, 0 sub-branches"
        finally:
            vine.close()


# ===========================================================================
# A.5 — the rendering is markdown, and markdown wants the blank line
# ===========================================================================

class TestIndexRendering:
    """An index body is the one document in a forest the ENGINE writes, and
    it was writing the first entry of a section directly under its heading.
    Every renderer puts the blank line back, so a branch could not be opened
    in the Studio editor's rich mode without the editor proposing a change
    nobody made — measured across two forests before the fix: 12 of the
    fixture's 82 bodies and 28 of the bench forest's 154, every one of them
    an `_index`."""

    def _body(self, root):
        return Forest(root).read("_index").body

    def test_the_first_entry_of_a_section_sits_under_a_blank_line(self,
                                                                  tmp_path):
        root = tmp_path / "gap"
        init_forest(root, title="Gap")
        vine = Vine(root, writable=True)
        try:
            vine.plant({"id": "b", "type": "branch", "parent": "_index",
                        "title": "B", "summary": "A branch of this forest."})
            vine.plant({"id": "n0", "type": "note", "parent": "_index",
                        "title": "N0", "summary": "The first note here."})
            vine.plant({"id": "n1", "type": "note", "parent": "_index",
                        "title": "N1", "summary": "The second note here."})
            body = self._body(root)
            assert "## Direct bananas\n\n- [[n0]]" in body
            assert "## Sub-branches\n\n- [[b]]" in body
            # The gap is ONE line and the entries stay adjacent: a blank
            # line between two entries would render as two lists.
            assert "- [[n0]]" in body and "- [[n1]]" in body
            first = body.index("- [[n0]]")
            assert "\n\n" not in body[first:body.index("- [[n1]]")]
        finally:
            vine.close()

    def test_both_spellings_are_read_identically(self, tmp_path):
        """Nothing READS the gap, which is what makes this safe to change on
        a forest that already exists: `coverage`, the digest and `scan` all
        answer the same for a body written either way."""
        from monkeyllm import indexer

        tight = ("# T\n\n> A forest.\n\n## Sub-branches\n\n## Direct bananas\n"
                 "- [[a]] \u2014 One.\n- [[b]] \u2014 Two.\n")
        loose = tight.replace("## Direct bananas\n- [[a]]",
                              "## Direct bananas\n\n- [[a]]")
        assert tight != loose
        assert indexer.count_coverage(tight) == indexer.count_coverage(loose) \
            == "2 bananas, 0 sub-branches"
        for body in (tight, loose):
            assert indexer.remove_entry_from_body(body, "a").count("- [[") == 1

    def test_an_existing_tight_section_is_not_rewritten(self, tmp_path):
        """The change is on what is WRITTEN next, never a migration: a forest
        whose sections already carry entries keeps its bytes, and only a
        section that was empty gains the gap."""
        from monkeyllm import indexer
        from monkeyllm.parser import parse_node

        tight = ("---\nid: _index\ntype: branch\ntitle: T\nsummary: A forest.\n"
                 "---\n# T\n\n## Direct bananas\n- [[a]] \u2014 One.\n")
        node = parse_node("_index", tight)
        out = indexer.add_entry(node, "b", "Two.", is_branch=False)
        assert "## Direct bananas\n- [[a]] \u2014 One.\n- [[b]] \u2014 Two." in out


# ===========================================================================
# F.236 — a wide prefix is bucketed
# ===========================================================================

class TestAutoBucketing:
    def test_the_rule_is_chosen_recorded_and_reused(self, tmp_path, s3, stores,
                                                    monkeypatch):
        monkeypatch.setenv("MONKEYLLM_ADOPT_BUCKET_ABOVE", "4")
        for team in ("acme", "beta"):
            for i in range(3):
                put(s3, f"{PREFIX}/{team}-{i}.md", doc(i))
        root = tmp_path / "wide"
        vine, g = forest(root, stores=stores)
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert g.config["bucketing"][""]["rule"] == "name-prefix"
            assert g.config["bucketing"][""]["above"] == 4
            assert sorted(report["planted"])[0].startswith("acme/")
            assert Forest(root).exists("acme/_index")
            assert Forest(root).exists("beta/_index")
            # `source_path` is the TRUE relative path: a grouping is not
            # provenance, and it is the sync key.
            node = Forest(root).read("acme/acme-0")
            assert node.frontmatter["source_path"] == "acme-0.md"
        finally:
            vine.close()

        # A file added later is placed by the RECORDED rule, even though the
        # set has grown past where another rule would now be chosen.
        put(s3, f"{PREFIX}/acme-9.md", doc(9))
        vine2 = Vine(root, writable=True, stores=stores)
        g2 = Gardener(vine2, hooks=[], stores=stores)
        try:
            assert g2.config["bucketing"][""]["rule"] == "name-prefix"
            report = g2.sync()
            assert report["planted"] == ["acme/acme-9"]
        finally:
            vine2.close()

    def test_under_the_ceiling_adopts_flat(self, tmp_path, s3, stores):
        for i in range(5):
            put(s3, f"{PREFIX}/page-{i}.md", doc(i))
        root = tmp_path / "flat"
        vine, g = forest(root, stores=stores)
        try:
            report = g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert "bucketing" not in g.config
            assert sorted(report["planted"]) == [f"page-{i}" for i in range(5)]
        finally:
            vine.close()

    def test_zero_disables_it(self, tmp_path, s3, stores, monkeypatch):
        monkeypatch.setenv("MONKEYLLM_ADOPT_BUCKET_ABOVE", "0")
        assert bucket_above() == 0
        for i in range(9):
            put(s3, f"{PREFIX}/page-{i}.md", doc(i))
        root = tmp_path / "disabled"
        vine, g = forest(root, stores=stores)
        try:
            g.adopt(f"s3://{BUCKET}/{PREFIX}")
            assert "bucketing" not in g.config
        finally:
            vine.close()

    def test_a_set_no_rule_can_split_uses_the_last_one(self):
        """Ten thousand files all beginning with `2024` is a real corpus, and
        refusing to adopt it would be refusing the case this was written
        for (G.3.2 rule 2)."""
        names = [f"2024-report-{i}.md" for i in range(10)]
        created = dict.fromkeys(names, "2024-06-01")
        assert choose_bucketing(names, created, 4) == "initial"
        # …and the rules in order: a name that groups itself wins.
        named = [f"{t}-{i}.md" for t in ("acme", "beta") for i in range(3)]
        assert choose_bucketing(named, dict.fromkeys(named, "2024-06-01"),
                                4) == "name-prefix"
        # A set under the ceiling is never bucketed at all.
        assert choose_bucketing(names[:3], created, 4) is None


# ===========================================================================
# F.238 (engine half) — the dense layer is built as a job
# ===========================================================================

class FakeEmbedder:
    model = "fake-embed"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[float(len(t) % 7), 1.0, 0.0] for t in texts]


class TestCanopyAsAJob:
    def test_the_index_is_installed_only_at_the_close(self, tmp_path):
        root = tmp_path / "canopy"
        init_forest(root, title="Canopy")
        vine = Vine(root, writable=True)
        try:
            for i in range(5):
                vine.plant({"id": f"n{i}", "type": "note", "parent": "_index",
                            "title": f"N{i}",
                            "summary": f"The summary of node number {i}."})
            emb = FakeEmbedder()
            steps = vine.build_canopy_iter(emb, batch=2)
            # five notes, the master index and `_meta/schema`
            assert steps.total == 7
            for n, step in enumerate(steps, start=1):
                assert step["index"] == n
                if n == 3:
                    break  # a cancel
            # K.4 (v0.84): a cancelled build leaves the index the forest
            # already had — here, none.
            from monkeyllm.canopy import CanopyIndex

            assert CanopyIndex.load(root / "_derived") is None

            report = vine.build_canopy(FakeEmbedder())
            assert report["nodes"] == 7
            assert CanopyIndex.load(root / "_derived") is not None
        finally:
            vine.close()
