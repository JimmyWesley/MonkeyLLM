# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.7/G.8 (spec v0.11): tiered storage — content policies, targeted sync."""

import os
import subprocess
import textwrap

import pytest

from monkeyllm.errors import E_NOT_FOUND, VineError
from monkeyllm.forest import init_forest
from monkeyllm.gardener import Gardener
from monkeyllm.vine import Vine

ARTICLE = textwrap.dedent("""\
    # Heron Vision Q2

    The heron-vision line shipped 412 units from Valencia, a sixteen percent
    increase over the previous quarter despite the depth camera shortage that
    constrained the assembly schedule through April and May. The retrofit
    program for early adopters reached forty plants, and the field failure
    rate dropped below one percent for the first time since launch, which the
    quality team attributes to the revised calibration jig and the new
    supplier qualification gates introduced during the winter maintenance
    window of the Valencia facility.

    ## Risks

    Depth camera lead time is nine weeks. Codeword xylocarpus-77 marks the
    buried fact for the sniff test — body-only, invisible to the summary.
    """)


def make_forest(tmp_path, config: str = ""):
    root = tmp_path / "floresta"
    init_forest(root, title="F")
    if config:
        (root / "_meta").mkdir(exist_ok=True)
        (root / "_meta" / "gardener.yaml").write_text(config, encoding="utf-8")
    return root


def make_source(tmp_path):
    src = tmp_path / "dump"
    (src / "docs").mkdir(parents=True)
    (src / "docs" / "heron.md").write_text(ARTICLE, encoding="utf-8")
    (src / "docs" / "nested.json").write_text(
        '{"plant": {"city": "Valencia", "units": 412}}', encoding="utf-8")
    return src


class TestCachedPolicy:
    @pytest.fixture()
    def adopted(self, tmp_path):
        root = make_forest(tmp_path, "content: cached\n")
        src = make_source(tmp_path)
        vine = Vine(root, writable=True)
        Gardener(vine, hooks=[]).adopt(src)
        yield vine, root, src
        vine.close()

    def test_node_is_a_stub_and_flesh_lives_in_derived(self, adopted):
        vine, root, _ = adopted
        node = vine.forest.read("docs/heron")
        assert node.frontmatter["content"] == "cached"
        assert "xylocarpus-77" not in node.body  # stub only
        cache = root / "_derived" / "bodies" / "docs" / "heron.md"
        assert cache.is_file() and "xylocarpus-77" in cache.read_text(encoding="utf-8")
        # the flesh never enters git (derived layer)
        out = subprocess.run(["git", "-C", str(root), "ls-files"],
                             capture_output=True, text=True, check=True)
        assert not [l for l in out.stdout.split() if l.startswith("_derived")]

    def test_pick_and_sniff_resolve_transparently(self, adopted):
        vine, _, _ = adopted
        r = vine.pick("docs/heron")
        assert "xylocarpus-77" in r["body"]
        r2 = vine.pick("docs/heron", section="Risks")
        assert "nine weeks" in r2["body"]
        s = vine.sniff("xylocarpus-77")
        assert s["results"] and s["results"][0]["id"] == "docs/heron"

    def test_summary_was_derived_from_full_text(self, adopted):
        vine, _, _ = adopted
        assert "heron" in vine.forest.read("docs/heron").frontmatter["summary"].lower()

    def test_purged_cache_degrades_explicitly(self, adopted):
        vine, root, _ = adopted
        (root / "_derived" / "bodies" / "docs" / "heron.md").unlink()
        with pytest.raises(VineError) as e:
            vine.pick("docs/heron")
        assert e.value.code == E_NOT_FOUND and "sync" in (e.value.hint or "")
        # the MAP keeps working
        hits = vine.locate("heron vision")
        assert any(h["id"] == "docs/heron" for h in hits["results"])

    def test_reference_policy_falls_back_to_cached_for_converted(self, tmp_path):
        root = make_forest(tmp_path, "content: reference\n")
        src = make_source(tmp_path)
        vine = Vine(root, writable=True)
        try:
            Gardener(vine, hooks=[]).adopt(src)
            # .md source -> true reference; converted json -> cached
            assert vine.forest.read("docs/heron").frontmatter["content"] == "reference"
            assert vine.forest.read("docs/nested").frontmatter["content"] == "cached"
        finally:
            vine.close()


class TestReferencePolicy:
    @pytest.fixture()
    def adopted(self, tmp_path):
        root = make_forest(tmp_path, "content: reference\n")
        src = make_source(tmp_path)
        vine = Vine(root, writable=True)
        Gardener(vine, hooks=[]).adopt(src)
        yield vine, root, src
        vine.close()

    def test_pick_reads_the_source_live(self, adopted):
        vine, _, src = adopted
        assert "xylocarpus-77" in vine.pick("docs/heron")["body"]
        (src / "docs" / "heron.md").write_text(
            ARTICLE + "\nLive edit marker.\n", encoding="utf-8")
        assert "Live edit marker." in vine.pick("docs/heron")["body"]

    def test_missing_source_degrades_explicitly(self, adopted):
        vine, _, src = adopted
        (src / "docs" / "heron.md").unlink()
        with pytest.raises(VineError) as e:
            vine.pick("docs/heron")
        assert e.value.code == E_NOT_FOUND
        assert vine.look("docs/heron")["summary"]  # map intact


class TestArchivePolicy:
    def test_durable_source_is_not_copied(self, tmp_path):
        root = make_forest(tmp_path)  # defaults: archive never
        src = tmp_path / "dump"
        src.mkdir()
        (src / "orders.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        vine = Vine(root, writable=True)
        try:
            Gardener(vine, hooks=[]).adopt(src)
            assert not (root / "_assets").exists()
            assert vine.query("orders", "SELECT COUNT(*) FROM orders")["rows"][0][0] == 1
        finally:
            vine.close()

    def test_archive_always_restores_inbox_behavior(self, tmp_path):
        root = make_forest(tmp_path, "archive: always\n")
        src = tmp_path / "dump"
        src.mkdir()
        (src / "orders.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        vine = Vine(root, writable=True)
        try:
            Gardener(vine, hooks=[]).adopt(src)
            assets = list((root / "_assets").glob("*.csv"))
            assert len(assets) == 1
        finally:
            vine.close()


class TestTargetedSync:
    @pytest.fixture()
    def adopted(self, tmp_path):
        root = make_forest(tmp_path)
        src = make_source(tmp_path)
        (src / "docs" / "other.md").write_text("# Other\n\nSecond doc.", encoding="utf-8")
        vine = Vine(root, writable=True)
        g = Gardener(vine, hooks=[])
        g.adopt(src)
        yield g, vine, src
        vine.close()

    def test_sync_path_touches_exactly_one_file(self, adopted):
        g, vine, src = adopted
        (src / "docs" / "heron.md").write_text(ARTICLE + "\nDelta one.\n", encoding="utf-8")
        (src / "docs" / "other.md").write_text("# Other\n\nDelta two.\n", encoding="utf-8")
        report = g.sync(src, path="docs/heron.md")
        assert report["updated"] == ["docs/heron"]
        assert "Delta one." in vine.forest.read("docs/heron").body
        assert "Delta two." not in vine.forest.read("docs/other").body  # untouched

    def test_sync_path_detects_new_and_deleted(self, adopted):
        g, _, src = adopted
        (src / "docs" / "novo.md").write_text("# Novo\n\nFresh.", encoding="utf-8")
        assert g.sync(src, path="docs/novo.md")["planted"] == ["docs/novo"]
        (src / "docs" / "other.md").unlink()
        assert g.sync(src, path="docs/other.md")["stale"] == ["docs/other"]

    def test_fast_path_skips_hashing_on_same_size_and_mtime(self, adopted):
        g, _, src = adopted
        f = src / "docs" / "other.md"
        st = f.stat()
        # different bytes, SAME size, mtime restored -> fast-path says unchanged
        original = f.read_text(encoding="utf-8")
        f.write_text(original[:-1] + "X", encoding="utf-8")
        os.utime(f, (st.st_atime, st.st_mtime))
        report = g.sync(src, path="docs/other.md")
        assert report["unchanged"] == ["docs/other"]
        # touching mtime breaks the fast-path -> hash sees the change
        os.utime(f, None)
        report = g.sync(src, path="docs/other.md")
        assert report["updated"] == ["docs/other"]


class TestReferenceContainment:
    """G.7: a reference body lives under the adopted source root. `pick` is a
    read primitive — it must not become a file reader for the whole host."""

    def test_source_path_cannot_escape_the_source_root(self, tmp_path):
        root = make_forest(tmp_path, "content: reference\n")
        src = make_source(tmp_path)
        secret = tmp_path / "secret.txt"
        secret.write_text("BOOTSTRAP_KEY=hunter2", encoding="utf-8")

        vine = Vine(root, writable=True)
        try:
            Gardener(vine, hooks=[]).adopt(src)
            # `source_path` is ordinary frontmatter (models.py keeps
            # extra="allow" for the Gardener's own G.1 fields), so anything
            # that can plant can aim it. Aiming it outside must not read.
            vine.plant({
                "id": "docs/decoy", "parent": "docs/_index", "type": "note",
                "title": "Decoy",
                "summary": "A planted node whose reference body points at a "
                           "file outside the adopted source root entirely.",
                "body": "placeholder", "content": "reference",
                "source_path": os.path.relpath(secret, src)})
            with pytest.raises(VineError) as e:
                vine.pick("docs/decoy")
            assert e.value.code == E_NOT_FOUND
            assert "hunter2" not in str(e.value.hint or "")
        finally:
            vine.close()
