# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.5.1 (spec v0.48, F.48 engine half): the media stub converter, the
media typing rule, the staging-archive amendment, the `extra_converters`
seam, and converter-failure fallback."""

import pytest

from monkeyllm.forest import init_forest
from monkeyllm.gardener import (
    CommandConverter,
    Conversion,
    Gardener,
    MediaStubConverter,
    builtin_converters,
    discover_converters,
)
from monkeyllm.vine import Vine

# Real magic bytes are irrelevant here on purpose: the stub never opens the
# file as an image — it reports name, format and size, nothing more.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
MP3_BYTES = b"ID3" + b"\x00" * 61

STUB_SENTENCE = "No description has been generated for this media yet."


class FakeDescriber:
    """Stands in for a host-injected vision describer (G.5.1 seam)."""

    extensions = {".png"}

    def convert(self, path):
        return Conversion(
            kind="markdown", title="described image",
            markdown="# described image\n\nA fake model description.\n")


class RaisingDescriber:
    """A describer whose endpoint is down: G.5.1 says it falls back."""

    extensions = {".png"}

    def convert(self, path):
        raise RuntimeError("vision endpoint down")


@pytest.fixture()
def garden(tmp_path):
    root = tmp_path / "forest"
    init_forest(root, title="Media Test Forest")
    vine = Vine(root, writable=True)
    g = Gardener(vine, hooks=[])
    yield g, vine, root
    vine.close()


class TestMediaStub:
    def test_png_plants_media_with_stub_body(self, garden, tmp_path):
        g, vine, _ = garden
        src = tmp_path / "dump"
        src.mkdir()
        (src / "team_photo.png").write_bytes(PNG_BYTES)

        report = g.adopt(src)

        # G.5.1: an image is never `unsupported` again
        assert report["unsupported"] == []
        assert report["errors"] == []
        assert report["planted"] == ["team_photo"]

        node = vine.forest.read("team_photo")
        fm = node.frontmatter
        assert fm["type"] == "media"
        assert fm["title"] == "team photo"
        assert STUB_SENTENCE in node.body
        assert "team_photo.png" in node.body  # the original filename
        assert str(len(PNG_BYTES)) in node.body  # the byte size
        # default archive:never + durable source -> referenced is nothing:
        # the source stays where it is, no payload fields at all
        assert "payload" not in fm
        assert "payload_type" not in fm

    def test_mp3_plants_media_stub(self, garden, tmp_path):
        g, vine, _ = garden
        src = tmp_path / "dump"
        src.mkdir()
        (src / "standup-recording.mp3").write_bytes(MP3_BYTES)

        report = g.adopt(src)

        assert report["unsupported"] == []
        assert report["planted"] == ["standup-recording"]
        node = vine.forest.read("standup-recording")
        assert node.frontmatter["type"] == "media"
        assert STUB_SENTENCE in node.body

    def test_staged_media_is_archived_despite_policy(self, garden):
        """G.5.1 amendment to G.7: a source under the forest's `_derived/`
        is disposable by contract, so the `_assets/` copy becomes the only
        durable bytes — even under the default `archive: never`."""
        g, vine, root = garden
        staging = root / "_derived" / "upload" / "batch-1"
        staging.mkdir(parents=True)
        (staging / "shot.png").write_bytes(PNG_BYTES)

        report = g.adopt(staging)

        assert report["planted"] == ["shot"]
        node = vine.forest.read("shot")
        fm = node.frontmatter
        assert fm["type"] == "media"
        assert fm["payload_type"] == "image"
        assert len(fm["payload_hash"]) == 64
        assert fm["payload"].startswith("_assets/")
        # payload is branch-relative; `shot` planted at the forest root
        archived = root / fm["payload"]
        assert archived.is_file()
        assert archived.read_bytes() == PNG_BYTES

    def test_resynced_staged_media_rearchives(self, garden):
        """A re-uploaded screenshot moves the `_assets/` copy with it: the
        refresh used to update body and source_hash while the payload kept
        the OLD bytes under a hash that still validated — and once the
        disposable staging was cleaned, the new image existed nowhere
        durable (v0.48 review finding)."""
        g, vine, root = garden
        staging = root / "_derived" / "upload" / "batch-1"
        staging.mkdir(parents=True)
        (staging / "shot.png").write_bytes(PNG_BYTES)
        g.adopt(staging)
        first = vine.forest.read("shot").frontmatter

        changed = PNG_BYTES + b"\x00" * 8  # a new size defeats the G.8 fast-path
        (staging / "shot.png").write_bytes(changed)
        report = g.sync(staging)

        assert report["updated"] == ["shot"]
        fm = vine.forest.read("shot").frontmatter
        assert fm["payload"] != first["payload"]
        assert fm["payload_hash"] != first["payload_hash"]
        assert (root / fm["payload"]).read_bytes() == changed
        # The digest names the copy, so the stale one is removed, not left
        # to accumulate beside every future re-upload.
        assert not (root / first["payload"]).exists()


class TestConverterOrder:
    def test_stub_is_last_builtin(self):
        assert isinstance(builtin_converters()[-1], MediaStubConverter)

    def test_seam_ranks_between_hooks_and_builtins(self):
        """G.5.1: command hooks > extras > entry points > built-ins. The
        operator who configured a `.png` hook keeps it; everyone else gets
        the injected describer over the stub."""
        convs = discover_converters(
            {"converters": {".png": 'some-tool "{input}" -o "{output}"'}},
            extra=[FakeDescriber()])
        png_order = [type(c).__name__ for c in convs if ".png" in c.extensions]
        assert png_order.index("CommandConverter") \
            < png_order.index("FakeDescriber") \
            < png_order.index("MediaStubConverter")
        assert isinstance(convs[0], CommandConverter)

    def test_extra_converter_wins_over_stub_end_to_end(self, tmp_path):
        root = tmp_path / "forest"
        init_forest(root, title="Seam Forest")
        vine = Vine(root, writable=True)
        try:
            g = Gardener(vine, hooks=[], extra_converters=[FakeDescriber()])
            src = tmp_path / "dump"
            src.mkdir()
            (src / "diagram.png").write_bytes(PNG_BYTES)

            report = g.adopt(src)

            assert report["planted"] == ["diagram"]
            node = vine.forest.read("diagram")
            # the describer's body wins, but typing follows the SOURCE:
            # a described image is still a `media` node
            assert "A fake model description." in node.body
            assert STUB_SENTENCE not in node.body
            assert node.frontmatter["type"] == "media"
        finally:
            vine.close()

    def test_explicit_converters_ignore_extras(self, garden):
        _, vine, _ = garden
        g = Gardener(vine, converters=[MediaStubConverter()], hooks=[],
                     extra_converters=[FakeDescriber()])
        assert len(g.converters) == 1
        assert isinstance(g.converters[0], MediaStubConverter)


class TestFallback:
    def test_failed_describer_falls_back_to_stub(self, tmp_path):
        """G.5.1: a describer that fails MUST fall back to the stub, with
        the failure in the report's errors — a broken model never aborts
        ingest, and never silently swallows what it broke on either."""
        root = tmp_path / "forest"
        init_forest(root, title="Fallback Forest")
        vine = Vine(root, writable=True)
        try:
            g = Gardener(vine, hooks=[], extra_converters=[RaisingDescriber()])
            src = tmp_path / "dump"
            src.mkdir()
            (src / "shot.png").write_bytes(PNG_BYTES)

            report = g.adopt(src)

            # the file still planted, through the stub
            assert report["planted"] == ["shot"]
            node = vine.forest.read("shot")
            assert node.frontmatter["type"] == "media"
            assert STUB_SENTENCE in node.body
            # and the failure is on the record, naming who failed on what
            assert any("RaisingDescriber" in e and "shot.png" in e
                       for e in report["errors"])
        finally:
            vine.close()

    def test_all_claimants_failing_keeps_terminal_error(self, garden, tmp_path):
        """The last claimant keeps the pre-G.5.1 contract: the file lands
        in errors and is neither planted nor unsupported."""
        g, vine, _ = garden
        g.converters = [RaisingDescriber()]  # the only claimant there is
        src = tmp_path / "dump"
        src.mkdir()
        (src / "shot.png").write_bytes(PNG_BYTES)

        report = g.adopt(src)

        assert report["planted"] == []
        assert report["unsupported"] == []
        assert any("shot.png" in e and "converter error" in e
                   for e in report["errors"])


URL = "https://example.com/articles/how-monkeys-forage"


class TestProvenance:
    """J.8 (v0.48): the Gardener's provenance MAP — source path -> URL —
    stamps a final `Source:` line onto markdown conversions. A map at
    construction and not an `on_curate` hook on purpose: curation never
    runs on refreshes (G.3), so provenance recorded there would vanish
    with the first sync. The map is consulted on adopt and on every body
    refresh alike."""

    def test_adopted_stub_body_ends_with_the_source_line(self, garden):
        _, vine, root = garden
        staging = root / "_derived" / "upload" / "batch-1"
        staging.mkdir(parents=True)
        (staging / "shot.png").write_bytes(PNG_BYTES)
        g = Gardener(vine, hooks=[], provenance={"shot.png": URL})

        report = g.adopt(staging)

        assert report["planted"] == ["shot"]
        node = vine.forest.read("shot")
        # The stub still admits it described nothing — but the body now
        # says what page this is a screenshot OF, where `sniff` can see it.
        assert STUB_SENTENCE in node.body
        assert node.body.rstrip("\n").endswith(f"Source: {URL}")

    def test_a_deeper_link_on_the_same_site_does_not_eat_the_stamp(self, garden):
        """Idempotence is by the stamped LINE, never by substring: a clipped
        page citing `…/blog/post-123` under source `…/blog` contains the
        URL as a prefix, and a substring test silently dropped the
        provenance for exactly the common case (v0.48 review finding)."""
        _, vine, root = garden
        staging = root / "_derived" / "upload" / "batch-1"
        staging.mkdir(parents=True)
        url = "https://example.com/blog"
        (staging / "clip.md").write_text(
            "# A clip\n\nSee https://example.com/blog/post-123 for more.\n",
            encoding="utf-8")
        g = Gardener(vine, hooks=[], provenance={"clip.md": url})

        report = g.adopt(staging)

        assert report["planted"] == ["clip"]
        body = vine.forest.read("clip").body
        assert body.rstrip("\n").endswith(f"Source: {url}")
        # …while a body already carrying the exact line is still left alone.
        report2 = g.sync(staging)
        assert report2["errors"] == []
        assert vine.forest.read("clip").body.count(f"Source: {url}") == 1

    def test_refresh_keeps_the_line_beside_the_rearchived_payload(self, garden):
        """The sync flip: a refresh rebuilds the body from the converter,
        so an address stamped only at adopt would vanish here. The Station
        rebuilds the map per request, so the syncing Gardener is a FRESH
        construction carrying the same entry — exactly the shape J.8's
        re-upload takes."""
        _, vine, root = garden
        staging = root / "_derived" / "upload" / "batch-1"
        staging.mkdir(parents=True)
        (staging / "shot.png").write_bytes(PNG_BYTES)
        Gardener(vine, hooks=[], provenance={"shot.png": URL}).adopt(staging)
        first = vine.forest.read("shot").frontmatter

        changed = PNG_BYTES + b"\x00" * 8  # a new size defeats the G.8 fast-path
        (staging / "shot.png").write_bytes(changed)
        report = Gardener(vine, hooks=[],
                          provenance={"shot.png": URL}).sync(staging)

        assert report["updated"] == ["shot"]
        node = vine.forest.read("shot")
        # The address survived the refresh…
        assert node.body.rstrip("\n").endswith(f"Source: {URL}")
        assert node.body.count(URL) == 1
        # …alongside the re-archived payload the G.5.1 amendment demands.
        fm = node.frontmatter
        assert fm["payload"] != first["payload"]
        assert (root / fm["payload"]).read_bytes() == changed

    def test_a_body_already_naming_the_url_is_not_stamped_twice(
            self, garden, tmp_path):
        _, vine, _ = garden
        src = tmp_path / "dump"
        src.mkdir()
        (src / "clip.md").write_text(
            f"# Clip\n\nQuoting {URL} right in the prose.\n", encoding="utf-8")
        g = Gardener(vine, hooks=[], provenance={"clip.md": URL})

        report = g.adopt(src)

        assert report["planted"] == ["clip"]
        body = vine.forest.read("clip").body
        # A prose mention is not provenance: the stamped line still lands
        # (idempotence keys on the exact `Source:` line, not on the URL
        # appearing anywhere — v0.48 review finding), and refreshes keep
        # exactly ONE stamp, not one per sync.
        assert body.rstrip("\n").endswith(f"Source: {URL}")
        assert body.count(f"Source: {URL}") == 1
        g.sync(src)
        assert vine.forest.read("clip").body.count(f"Source: {URL}") == 1

    def test_dataset_conversions_are_untouched(self, garden, tmp_path):
        """Provenance is a markdown affair: a dataset's body is the G.2.3
        map, not prose, and a Source line inside it would be a claim the
        sample-map rewrite (`sync`) does not own."""
        _, vine, _ = garden
        src = tmp_path / "dump"
        src.mkdir()
        (src / "sales.csv").write_text("region,total\nnorth,12\n",
                                       encoding="utf-8")
        g = Gardener(vine, hooks=[], provenance={"sales.csv": URL})

        report = g.adopt(src)

        assert report["planted"] == ["sales"]
        assert URL not in vine.forest.read("sales").body
