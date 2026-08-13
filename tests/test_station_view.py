# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""C.6d `view` on the host (spec v0.48, F.50 host half): the image behind an
in-scope media node, served to a multimodal MCP client as image content.

The host adds exactly what it adds to every read — identity, scope, audit —
and nothing else: out-of-scope answers the same envelope as absent (J.3),
the REST surface does not serve the tool at all (J.14 is REST's byte
route), and a key whose capabilities lack `read` is refused before the
forest is touched.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
HEADERS = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"view-serves-these-bytes-verbatim" * 6


@pytest.fixture(scope="session")
def view_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("view-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(view_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=view_root, registry_path=tmp_path / "station.db",
                    mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry, view_root / FOREST


def _key(registry, caps=("read",), principal="alice", allow=None):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), allow=allow)
    return key


def _plant_media(client, key, forest_dir: Path, node_id: str, payload: str,
                 data: bytes | None = None, payload_hash: str | None = None):
    if data is not None:
        target = forest_dir / node_id.rsplit("/", 1)[0] / payload
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    node = {"id": node_id, "parent": f"{node_id.rsplit('/', 1)[0]}/_index",
            "type": "media", "title": node_id.rsplit("/", 1)[-1],
            "summary": "A media passport whose image this test views.",
            "payload": payload, "payload_type": "image"}
    if payload_hash:
        node["payload_hash"] = payload_hash
    r = client.post(f"/v1/forests/{FOREST}/plant", json={"node": node},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text


def _view(client, node_id, key=None):
    headers = dict(HEADERS)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    r = client.post("/mcp/", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "view",
                   "arguments": {"forest": FOREST, "id": node_id}},
    })
    assert r.status_code == 200, r.text
    return r.json()["result"]["content"]


def _text_block(content) -> dict:
    return json.loads(next(c["text"] for c in content if c["type"] == "text"))


def test_view_returns_the_header_and_the_image(station):
    client, registry, forest_dir = station
    key = _key(registry, caps=("read", "write"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    _plant_media(client, key, forest_dir, "notes/f50-shot",
                 "_assets/f50-shot.png", data=PNG_BYTES, payload_hash=digest)

    content = _view(client, "notes/f50-shot", key=key)
    kinds = [c["type"] for c in content]
    assert "image" in kinds, content

    header = _text_block(content)
    assert header["id"] == "notes/f50-shot"
    assert header["media_type"] == "image/png"
    assert header["size"] == len(PNG_BYTES)
    assert header["payload_hash"] == digest
    assert "path" not in header, "the lane's filesystem is not the caller's"

    image = next(c for c in content if c["type"] == "image")
    assert base64.b64decode(image["data"]) == PNG_BYTES
    assert image.get("mimeType", image.get("mime_type")) == "image/png"

    # Audited like a read (C.6d.7): the row names the node, never the bytes.
    entry = registry.audit(limit=1, principal="alice")[0]
    assert entry["primitive"] == "view"


def test_out_of_scope_answers_exactly_as_absent(station):
    client, registry, forest_dir = station
    full = _key(registry, caps=("read", "write"), principal="root")
    _plant_media(client, full, forest_dir, "notes/f50-hidden",
                 "_assets/f50-hidden.png", data=PNG_BYTES)
    scoped = _key(registry, principal="scoped", allow=["projects/"])

    hidden = _text_block(_view(client, "notes/f50-hidden", key=scoped))
    absent = _text_block(_view(client, "notes/never-existed", key=scoped))
    assert hidden["error"]["code"] == "E_NOT_FOUND"
    assert absent["error"]["code"] == "E_NOT_FOUND"
    # One envelope but for the id each caller supplied (J.3).
    assert (hidden["error"]["message"].replace("notes/f50-hidden", "X")
            == absent["error"]["message"].replace("notes/never-existed", "X"))
    assert hidden["error"].get("hint") == absent["error"].get("hint")


def test_a_dataset_is_refused_naming_the_type(station):
    client, registry, _ = station
    key = _key(registry, principal="dsreader")
    out = _text_block(_view(client, "sales/report-q1-2026", key=key))
    assert out["error"]["code"] == "E_SCHEMA"
    assert "not an image" in out["error"]["message"]


def test_view_requires_the_read_capability(station):
    client, registry, _ = station
    key = _key(registry, caps=("ingest",), principal="clipper")
    out = _text_block(_view(client, "notes/anything", key=key))
    assert out["error"]["code"] == "E_FORBIDDEN"
    assert "read" in out["error"]["message"]


def test_unauthenticated_view_is_refused(station):
    client, _, _ = station
    out = _text_block(_view(client, "notes/anything"))
    assert out["error"]["code"] == "E_FORBIDDEN"


def test_rest_does_not_serve_view(station):
    """C.6d.8: REST's byte route is J.14; a JSON twin would only disclose
    server paths. The generic primitive route refuses the name."""
    client, registry, _ = station
    key = _key(registry, principal="restless")
    r = client.post(f"/v1/forests/{FOREST}/view", json={"id": "notes/x"},
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "E_NOT_FOUND"
    assert "no such endpoint" in r.json()["error"]["message"]
