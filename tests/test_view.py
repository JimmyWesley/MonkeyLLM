# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""C.6d `view` (spec v0.48, F.50 engine half): the image payload behind a
media node, resolved for a multimodal client.

What is load-bearing: absent node, payload-less node and missing file all
answer the SAME `E_NOT_FOUND` envelope (a host layers its scope rule on the
same shape); a remote URI is refused rather than fetched inside a read; a
payload resolving outside the forest root is refused, never followed; and
anything that is not an image stays with the surfaces that already serve it.
"""

import pytest

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.forest import init_forest
from monkeyllm.vine import Vine

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"pixels-do-not-matter-here" * 4


@pytest.fixture()
def vine(tmp_path):
    root = tmp_path / "forest"
    init_forest(root, title="View Test Forest")
    v = Vine(root, writable=True)
    yield v
    v.close()


def _plant_media(vine, node_id="shot", payload="_assets/shot.png",
                 data=PNG_BYTES, payload_hash="abc123"):
    if data is not None:
        target = vine.forest.root / payload
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    vine.plant({
        "id": node_id, "parent": "_index", "type": "media",
        "title": node_id, "summary": "A media passport whose image view serves.",
        "payload": payload, "payload_type": "image",
        "payload_hash": payload_hash,
    })


def _envelope(exc: VineError) -> tuple:
    return (exc.code, exc.message, getattr(exc, "hint", None))


class TestView:
    def test_view_resolves_the_image(self, vine):
        _plant_media(vine)
        out = vine.view("shot")
        assert out["id"] == "shot"
        assert out["media_type"] == "image/png"
        assert out["size"] == len(PNG_BYTES)
        assert out["payload_hash"] == "abc123"
        from pathlib import Path
        assert Path(out["path"]).read_bytes() == PNG_BYTES

    def test_payloadless_node_answers_exactly_as_missing(self, vine):
        """One envelope for absent and payload-less (C.6d.1): a note is not
        a distinguishable third state, it simply has nothing to view."""
        vine.plant({"id": "prose", "parent": "_index", "type": "note",
                    "title": "prose", "summary": "A note with no payload."})
        with pytest.raises(VineError) as no_payload:
            vine.view("prose")
        with pytest.raises(VineError) as missing:
            vine.view("prose-that-never-existed")
        assert no_payload.value.code == E_NOT_FOUND
        assert missing.value.code == E_NOT_FOUND
        # Byte-identical but for the id each caller supplied.
        a = _envelope(no_payload.value)
        b = _envelope(missing.value)
        assert a[1].replace("prose", "X") == b[1].replace(
            "prose-that-never-existed", "X")
        assert a[0] == b[0] and a[2] == b[2]

    def test_missing_file_answers_exactly_as_missing_node(self, vine):
        _plant_media(vine, node_id="gone", payload="_assets/gone.png",
                     data=None)
        with pytest.raises(VineError) as exc:
            vine.view("gone")
        assert exc.value.code == E_NOT_FOUND
        assert "node not found: gone" in exc.value.message

    def test_a_dataset_is_queried_not_viewed(self, vine):
        vine.plant({
            "id": "ledger", "parent": "_index", "type": "dataset",
            "title": "ledger", "summary": "A dataset born with a schema.",
            "schema": {"rows": {"columns": {"n": "INTEGER"}}},
        })
        with pytest.raises(VineError) as exc:
            vine.view("ledger")
        assert exc.value.code == E_SCHEMA
        assert "not an image" in exc.value.message

    def test_a_remote_uri_is_refused_not_fetched(self, vine):
        _plant_media(vine, node_id="remote", payload="s3://bucket/shot.png",
                     data=None)
        with pytest.raises(VineError) as exc:
            vine.view("remote")
        assert exc.value.code == E_SCHEMA
        assert "s3" in exc.value.message

    def test_a_payload_escaping_the_forest_is_refused(self, vine, tmp_path):
        outside = tmp_path / "outside.png"
        outside.write_bytes(PNG_BYTES)
        _plant_media(vine, node_id="escape", payload="../outside.png",
                     data=None)
        with pytest.raises(VineError) as exc:
            vine.view("escape")
        assert exc.value.code == E_SCHEMA
        assert "escapes the forest" in exc.value.message

    def test_over_the_byte_bound_is_refused_with_the_size(self, vine,
                                                          monkeypatch):
        monkeypatch.setattr("monkeyllm.vine.VIEW_MAX_BYTES", 8)
        _plant_media(vine)
        with pytest.raises(VineError) as exc:
            vine.view("shot")
        assert exc.value.code == E_SCHEMA
        assert str(len(PNG_BYTES)) in exc.value.message

    def test_view_is_traced_like_a_read(self, vine):
        _plant_media(vine)
        before = len(vine.tracer.events)
        vine.view("shot")
        events = vine.tracer.events[before:]
        assert any(e.get("primitive") == "view" for e in events)
