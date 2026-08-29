# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.9 fetchers + H.6 eviction + Part I snapshots (spec v0.11; v0.74)."""

import hashlib
import os
import subprocess
import zipfile
from pathlib import Path

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

def _plant_asset(root: Path) -> Path:
    """A media byte under a branch's own `_assets/` (G.5.1).

    Placed one level down on purpose: the Gardener archives media under the
    OWNING branch, so `_assets` is a directory name at any depth and a
    collector that looks only at the forest root finds nothing.
    """
    asset = root / "sales" / "_assets" / "photo.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"pixels" * 40)
    return asset


def _legacy_pair(root: Path, tmp_path: Path):
    """A pre-v0.74 snapshot: a bare bundle and a separate payload sidecar.

    The producer stopped writing this shape in v0.74, so the test writes it
    — otherwise "yesterday's backups still restore" is a claim with nothing
    behind it.
    """
    bundle = tmp_path / "legacy.bundle"
    subprocess.run(["git", "-C", str(root), "bundle", "create", str(bundle), "--all"],
                   capture_output=True, text=True, check=True)
    sidecar = tmp_path / "legacy.bundle.payloads.zip"
    n = 0
    with zipfile.ZipFile(sidecar, "w") as zf:
        for f in sorted(root.rglob("*.db")):
            if "_derived" in f.parts:
                continue
            zf.write(f, f.relative_to(root).as_posix())
            n += 1
    return bundle, sidecar, n


class TestSnapshots:
    """Part I: a snapshot is ONE file, and it says what it left behind."""

    def test_roundtrip_preserves_nodes_history_and_payloads(self, forest_rw, tmp_path):
        from monkeyllm.snapshot import create_snapshot, restore_snapshot
        from monkeyllm.vine import Vine

        commits = subprocess.run(
            ["git", "-C", str(forest_rw), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        info = create_snapshot(forest_rw, out=tmp_path / "f.forest")
        assert (tmp_path / "f.forest").is_file() and info["payloads"] >= 1
        assert info["payloads_omitted"] == 0

        dest = tmp_path / "restored"
        r = restore_snapshot(tmp_path / "f.forest", dest)
        assert r["nodes"] > 0 and r["restored_payloads"] == info["payloads"]
        assert r["payloads_missing"] == 0
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

        info = create_snapshot(forest_rw, out=tmp_path / "f.forest")
        target = tmp_path / "busy"
        target.mkdir()
        (target / "x.txt").write_text("precious", encoding="utf-8")
        with pytest.raises(VineError) as e:
            restore_snapshot(info["snapshot"], target)
        assert e.value.code == E_SCHEMA
        assert (target / "x.txt").read_text(encoding="utf-8") == "precious"


class TestContainer:
    """F.158: one file, and it opens without this software."""

    def test_members_are_the_bundle_the_readme_and_the_payloads(self, forest_rw,
                                                                tmp_path):
        from monkeyllm.snapshot import create_snapshot

        _plant_asset(forest_rw)
        info = create_snapshot(forest_rw, out=tmp_path / "f.forest")
        with zipfile.ZipFile(tmp_path / "f.forest") as zf:
            names = set(zf.namelist())
        assert "forest.bundle" in names and "README.txt" in names
        payloads = {n for n in names if n.startswith("payloads/")}
        assert names == payloads | {"forest.bundle", "README.txt"}
        assert "payloads/sales/report-q1-2026.db" in payloads
        # the wider hole v0.74 closed: media rode in no git and no sidecar
        assert "payloads/sales/_assets/photo.png" in payloads
        assert info["payloads"] == len(payloads)

    def test_payload_bytes_survive_byte_for_byte(self, forest_rw, tmp_path):
        from monkeyllm.snapshot import create_snapshot, restore_snapshot

        asset = _plant_asset(forest_rw)
        db = forest_rw / "sales" / "report-q1-2026.db"
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (asset, db)}

        info = create_snapshot(forest_rw, out=tmp_path / "f.forest")
        dest = tmp_path / "restored"
        restore_snapshot(info["snapshot"], dest)
        for original, digest in before.items():
            copy = dest / original.relative_to(forest_rw)
            assert copy.is_file()
            assert hashlib.sha256(copy.read_bytes()).hexdigest() == digest

    def test_it_opens_with_unzip_and_git_alone(self, forest_rw, tmp_path):
        """The anti-lock-in property, which a container is able to hide.

        A backup nobody can open without the vendor is not a backup, so the
        container is asked to give the forest back using only tools the
        README names.
        """
        from monkeyllm.snapshot import create_snapshot

        info = create_snapshot(forest_rw, out=tmp_path / "f.forest")
        manual = tmp_path / "byhand"
        with zipfile.ZipFile(info["snapshot"]) as zf:
            zf.extractall(manual)
            readme = zf.read("README.txt").decode("utf-8")
        assert "git clone" in readme and "unzip" in readme

        subprocess.run(["git", "clone", "--quiet", str(manual / "forest.bundle"),
                        str(manual / "clone")],
                       capture_output=True, text=True, check=True)
        assert (manual / "clone" / "_index.md").is_file()
        assert (manual / "payloads" / "sales" / "report-q1-2026.db").is_file()


class TestPayloadAccounting:
    """F.159: the loss is counted at both ends, and the two zeroes differ."""

    def test_an_omission_is_stated_by_the_producer(self, forest_rw, tmp_path):
        from monkeyllm.snapshot import create_snapshot

        full = create_snapshot(forest_rw, out=tmp_path / "full.forest")
        bare = create_snapshot(forest_rw, out=tmp_path / "bare.forest",
                               with_payloads=False)
        assert full["payloads"] >= 1 and full["payloads_omitted"] == 0
        assert bare["payloads"] == 0 and bare["payloads_omitted"] == full["payloads"]
        # `payloads: 0` must not mean two different things
        assert bare["payloads"] == 0 and bare["payloads_omitted"] != 0

    def test_a_restore_counts_the_nodes_it_left_dead(self, forest_rw, tmp_path):
        from monkeyllm.snapshot import create_snapshot, restore_snapshot

        bare = create_snapshot(forest_rw, out=tmp_path / "bare.forest",
                               with_payloads=False)
        r = restore_snapshot(bare["snapshot"], tmp_path / "bare-dest")
        assert r["restored_payloads"] == 0
        assert r["payloads_missing"] >= 1  # the passports outlived their bytes

        full = create_snapshot(forest_rw, out=tmp_path / "full.forest")
        r2 = restore_snapshot(full["snapshot"], tmp_path / "full-dest")
        assert r2["payloads_missing"] == 0

    def test_a_remote_payload_is_not_a_hole(self, vine_rw, forest_rw,
                                            remote_dataset, tmp_path):
        """G.9: those bytes were never local, so their absence is not this.

        The fixture has just deleted the local `.db` and pointed the
        passport at a URI — the exact shape a naive counter reports as a
        dead node.
        """
        from monkeyllm.catalog import count_missing_payloads

        assert not (forest_rw / "sales" / "report-q1-2026.db").exists()
        assert count_missing_payloads(vine_rw.catalog, vine_rw.forest) == 0


class TestSnapshotShape:
    """F.160: the shape is read from content, never from the name."""

    def test_a_container_named_bundle_still_restores(self, forest_rw, tmp_path):
        from monkeyllm.snapshot import create_snapshot, restore_snapshot

        info = create_snapshot(forest_rw, out=tmp_path / "lying.bundle")
        r = restore_snapshot(info["snapshot"], tmp_path / "dest")
        assert r["nodes"] > 0 and r["restored_payloads"] >= 1

    def test_a_bare_bundle_named_forest_still_restores(self, forest_rw, tmp_path):
        from monkeyllm.snapshot import restore_snapshot

        bundle, _, _ = _legacy_pair(forest_rw, tmp_path)
        lying = tmp_path / "lying.forest"
        bundle.rename(lying)
        r = restore_snapshot(lying, tmp_path / "dest")
        assert r["nodes"] > 0 and r["restored_payloads"] == 0
        assert r["payloads_missing"] >= 1

    def test_a_pre_v074_pair_still_restores(self, forest_rw, tmp_path):
        from monkeyllm.snapshot import restore_snapshot

        bundle, sidecar, n = _legacy_pair(forest_rw, tmp_path)
        assert n >= 1
        r = restore_snapshot(bundle, tmp_path / "dest", payload_sidecar=sidecar)
        assert r["restored_payloads"] == n and r["payloads_missing"] == 0
        assert (tmp_path / "dest" / "sales" / "report-q1-2026.db").is_file()


class TestContainerMembers:
    """F.161: refused, not skipped, and the positive naming survives.

    What a snapshot unpacks into is a fresh git clone (J.13.2). The producer
    writes payloads only, but an imported snapshot is by definition an
    artifact from somewhere else — that is what importing is — and the
    consumer is what decides where its bytes land. `..` is stripped by
    CPython; `.git/config` needs no `..`, and git reads several of its values
    as commands to run on the next ordinary index operation, which the
    Station performs inside a forest on every plant, graft and tend.
    """

    @staticmethod
    def _forge(path, source_container, extra):
        """A real container with one extra member welded in."""
        with zipfile.ZipFile(source_container) as src, \
                zipfile.ZipFile(path, "w") as out:
            for info in src.infolist():
                out.writestr(info.filename, src.read(info.filename))
            for name, body in extra.items():
                out.writestr(name, body)
        return path

    @pytest.mark.parametrize("member", [
        "notes.md",                              # outside payloads/
        "payloads/../escape.db",                 # a relative segment
        "payloads/.git/config",                  # no `..` needed at all
        "payloads/nested/.git/hooks/pre-commit",
        # These two ride the `_assets/` clause: without the dot-component
        # rule the extension check waves them through, and the second one
        # writes inside the repository's own .git.
        "payloads/_assets/.git/config",
        "payloads/.git/_assets/hook.png",
        "/payloads/absolute.db",
        "payloads/notes.md",                     # neither database nor asset
        "payloads/payload.db.txt",
    ])
    def test_a_container_carries_payloads_and_nothing_else(self, forest_rw,
                                                           tmp_path, member):
        from monkeyllm.snapshot import create_snapshot, restore_snapshot

        info = create_snapshot(forest_rw, out=tmp_path / "good.forest")
        evil = self._forge(tmp_path / "evil.forest", info["snapshot"],
                           {member: "[core]\n\tfsmonitor = touch /tmp/pwned\n"})
        dest = tmp_path / "restored"
        with pytest.raises(VineError) as e:
            restore_snapshot(evil, dest)
        assert e.value.code == E_SCHEMA
        # judged before anything lands: no half-restored forest behind it
        assert not dest.exists()

    def test_a_real_asset_and_database_are_accepted(self, forest_rw, tmp_path):
        """The refusal must be about the member, not about payloads."""
        from monkeyllm.snapshot import create_snapshot, restore_snapshot

        _plant_asset(forest_rw)
        info = create_snapshot(forest_rw, out=tmp_path / "f.forest")
        r = restore_snapshot(info["snapshot"], tmp_path / "restored")
        assert r["restored_payloads"] == info["payloads"] >= 2
        assert (tmp_path / "restored" / "sales" / "report-q1-2026.db").is_file()
        assert (tmp_path / "restored" / "sales" / "_assets" / "photo.png").is_file()

    def test_the_uncompressed_ceiling_names_itself(self, forest_rw, tmp_path,
                                                   monkeypatch):
        from monkeyllm import snapshot as snap

        info = snap.create_snapshot(forest_rw, out=tmp_path / "f.forest")
        monkeypatch.setattr(snap, "MAX_SIDECAR_UNCOMPRESSED", 8)
        with pytest.raises(VineError) as e:
            snap.restore_snapshot(info["snapshot"], tmp_path / "restored")
        assert e.value.code == E_SCHEMA and "ceiling" in str(e.value)

    @pytest.mark.parametrize("member", [
        ".git/config",
        "nested/.git/hooks/pre-commit",
        "notes.md",
        "../escape.db",
        "payload.db.txt",
    ])
    def test_a_legacy_sidecar_keeps_its_own_rule(self, forest_rw, tmp_path, member):
        """Pre-v0.74 archives are validated exactly as they always were."""
        from monkeyllm.snapshot import restore_snapshot

        bundle, _, _ = _legacy_pair(forest_rw, tmp_path)
        sidecar = tmp_path / "evil.payloads.zip"
        with zipfile.ZipFile(sidecar, "w") as zf:
            zf.writestr(member, "[core]\n\tfsmonitor = touch /tmp/pwned\n")
        dest = tmp_path / "restored"
        with pytest.raises(VineError) as e:
            restore_snapshot(bundle, dest, payload_sidecar=sidecar)
        assert e.value.code == E_SCHEMA
        config = dest / ".git" / "config"
        assert "fsmonitor" not in config.read_text(encoding="utf-8")
