# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Payload bytes over REST (spec J.14, criterion F.49).

Every read primitive serves the textual proxy on purpose — text to find,
binary to consume (G.5) — and this route is the one place the person gets
the binary: the screenshot a console shows, the `.db` a browser saves.
What is load-bearing here is the discipline around the bytes: out-of-scope,
absent and payload-less answer ONE byte-identical envelope (no existence
oracle), a payload resolving outside the forest root is refused rather than
followed, and a remote URI is `E_SCHEMA` — fetching on a GET would hide a
network dependency inside a read.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"not-really-a-png-but-bytes-are-bytes" * 8


@pytest.fixture(scope="session")
def payload_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("payload-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(payload_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=payload_root, registry_path=tmp_path / "station.db",
                    mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, payload_root / FOREST


def _key(registry, caps=("read",), principal="alice", allow=None):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), allow=allow)
    return {"Authorization": f"Bearer {key}"}


def _plant_media(client, head, forest_dir: Path, node_id: str, payload: str,
                 data: bytes | None = None, payload_hash: str | None = None):
    """A media node the way an ingest leaves one: passport in the map,
    bytes under the branch's `_assets/` (written directly — the test is
    about serving, not about the Gardener)."""
    if data is not None:
        target = forest_dir / node_id.rsplit("/", 1)[0] / payload
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    node = {"id": node_id, "parent": f"{node_id.rsplit('/', 1)[0]}/_index",
            "type": "media", "title": node_id.rsplit("/", 1)[-1],
            "summary": "A media passport whose bytes this test serves.",
            "payload": payload, "payload_type": "image"}
    if payload_hash:
        node["payload_hash"] = payload_hash
    r = client.post(f"/v1/forests/{FOREST}/plant", json={"node": node},
                    headers=head)
    assert r.status_code == 200, r.text


def _repoint(passport: Path, payload: str) -> None:
    """C.7.5 (v0.77): a media node cannot be BORN pointing at nothing, so
    the passport is edited by hand after the plant — which is how the
    state these tests serve arises in the field."""
    import re
    text = passport.read_text(encoding="utf-8")
    text, n = re.subn(r"(?m)^payload:.*$", f"payload: {payload}", text)
    assert n == 1
    passport.write_text(text, encoding="utf-8")


def _get(client, head, node_id: str):
    return client.get(f"/v1/forests/{FOREST}/payload/{node_id}", headers=head)


# -- the bytes ----------------------------------------------------------------


def test_served_bytes_equal_disk_and_etag_is_the_payload_hash(station):
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "write"))
    digest = hashlib.sha256(PNG_BYTES).hexdigest()
    _plant_media(client, head, forest_dir, "notes/f49-shot",
                 "_assets/f49-shot.png", data=PNG_BYTES, payload_hash=digest)

    r = _get(client, head, "notes/f49-shot")
    assert r.status_code == 200, r.text
    assert r.content == PNG_BYTES
    assert r.headers["etag"] == digest
    assert r.headers["cache-control"] == "private"
    assert r.headers["content-type"] == "image/png"

    # Audited like a read (J.4): who, which node, how many bytes — never
    # the bytes.
    entry = registry.audit(limit=1, principal="alice")[0]
    assert entry["primitive"] == "payload"
    assert entry["size"] == len(PNG_BYTES)


def test_a_dataset_db_is_served_under_the_same_rules(station):
    client, registry, forest_dir = station
    head = _key(registry)
    on_disk = (forest_dir / "sales" / "report-q1-2026.db").read_bytes()

    r = _get(client, head, "sales/report-q1-2026")
    assert r.status_code == 200, r.text
    assert r.content == on_disk
    assert r.headers["cache-control"] == "private"


# -- no existence oracle (J.3 reaching this surface) ---------------------------


def test_out_of_scope_absent_and_payloadless_answer_one_envelope(station):
    """Three different truths, one byte-identical answer: a scoped principal
    must not learn which of them it was (F.49)."""
    client, registry, _ = station
    head = _key(registry, principal="scoped", allow=["projects/"])

    out_of_scope = _get(client, head, "sales/report-q1-2026")  # exists, hidden
    absent = _get(client, head, "projects/no-such-node")       # never existed
    no_payload = _get(client, head, "projects/audio-pipeline")  # visible, mapless

    assert out_of_scope.status_code == absent.status_code \
        == no_payload.status_code == 404
    assert out_of_scope.json()["error"]["code"] == "E_NOT_FOUND"
    # Byte-identical, not merely same-shaped — except for the id the caller
    # themselves supplied, which discloses nothing.
    bodies = {r.text.replace(r.request.url.path.split("/payload/")[1], "X")
              for r in (out_of_scope, absent, no_payload)}
    assert len(bodies) == 1, bodies


def test_reading_bytes_requires_the_read_capability(station):
    """A capability refusal, like the primitives (J.14) — not an existence
    answer: the caller holds a grant, so the forest is no secret."""
    client, registry, _ = station
    head = _key(registry, caps=("ingest",), principal="dropbox")
    r = _get(client, head, "sales/report-q1-2026")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "E_FORBIDDEN"


def test_no_grant_is_an_unknown_forest(station):
    client, registry, _ = station
    key = registry.issue_key("stranger")
    r = client.get(f"/v1/forests/{FOREST}/payload/sales/report-q1-2026",
                   headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 404
    assert "unknown forest" in r.json()["error"]["message"]


# -- containment and remoteness -------------------------------------------------


def test_a_payload_escaping_the_forest_is_refused_never_followed(station):
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "write"))
    # The escape target genuinely exists OUTSIDE the forest root, so a
    # served 200 here would be the actual leak, not a simulation of one.
    outside = forest_dir.parent / "f49-outside.txt"
    outside.write_text("host bytes the forest must not serve",
                       encoding="utf-8")
    _plant_media(client, head, forest_dir, "notes/f49-escape",
                 "_assets/f49-escape.txt", data=b"inside, at first")
    _repoint(forest_dir / "notes" / "f49-escape.md", "../../f49-outside.txt")

    r = _get(client, head, "notes/f49-escape")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "E_SCHEMA"
    assert "escapes the forest" in r.json()["error"]["message"]


def test_a_remote_payload_uri_is_schema_naming_the_scheme(station):
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "write"))
    _plant_media(client, head, forest_dir, "notes/f49-remote",
                 "s3://bucket/x")

    r = _get(client, head, "notes/f49-remote")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "E_SCHEMA"
    assert "s3" in r.json()["error"]["message"]


def test_bytes_missing_on_disk_answer_the_not_found_envelope(station):
    """The map says bytes exist and the disk disagrees: to the reader that
    is the same absent payload as no field at all (J.14)."""
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "write"))
    _plant_media(client, head, forest_dir, "notes/f49-gone",
                 "_assets/f49-gone.png", data=b"here, then gone")
    (forest_dir / "notes" / "_assets" / "f49-gone.png").unlink()

    gone = _get(client, head, "notes/f49-gone")
    absent = _get(client, head, "notes/f49-never-was")
    assert gone.status_code == absent.status_code == 404
    assert gone.json()["error"]["code"] == "E_NOT_FOUND"
    assert gone.text.replace("f49-gone", "X") \
        == absent.text.replace("f49-never-was", "X")


# -- provenance over the upload surface (J.8 v0.48) ----------------------------
#
# An upload entry may say where its bytes came from; the host validates the
# address and hands the Gardener a provenance map, and the map — not a
# curation hook — is what keeps the `Source:` line alive across the
# upload->sync flip. End to end here because the seam under test IS the
# hand-off: stage_upload's rel-name keys against the Gardener's
# `source_path` keys, through the one Gardener construction site.

URL = "https://example.com/articles/how-monkeys-forage"

import base64 as _b64  # noqa: E402


def _ingest(client, head, files):
    return client.post(f"/v1/forests/{FOREST}/ingest",
                       json={"mode": "upload", "files": files,
                             "dest": "clips", "wait": True},
                       headers=head)


def test_uploaded_source_url_lands_in_the_planted_bodies(station):
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "ingest"), principal="clipper")

    r = _ingest(client, head, [
        {"name": "clip-note.md",
         "text": "# Clip note\n\nWhat the page said.\n",
         "source_url": URL},
        {"name": "page-shot.png",
         "b64": _b64.b64encode(PNG_BYTES).decode("ascii"),
         "source_url": URL},
    ])
    assert r.status_code == 200, r.text
    report = r.json()["job"]["report"]
    assert report["errors"] == []
    assert set(report["planted"]) == {"clips/clip-note", "clips/page-shot"}

    note = (forest_dir / "clips" / "clip-note.md").read_text(encoding="utf-8")
    assert note.rstrip("\n").endswith(f"Source: {URL}")
    # The stub media body carries the address too: the node says what page
    # it is a screenshot OF (J.15 — every clip carries its address).
    shot = (forest_dir / "clips" / "page-shot.md").read_text(encoding="utf-8")
    assert shot.rstrip("\n").endswith(f"Source: {URL}")


def test_reupload_keeps_the_source_line_through_the_sync_flip(station):
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "ingest"), principal="clipper")
    first = _ingest(client, head, [
        {"name": "clip-refresh.md", "text": "# Refresh\n\nDraft one.\n",
         "source_url": URL}])
    assert first.status_code == 200, first.text

    # Same staged name, changed bytes: the host flips upload to sync and
    # the refresh rebuilds the body from the converter — where a
    # curation-time stamp would have vanished (J.8 v0.48).
    second = _ingest(client, head, [
        {"name": "clip-refresh.md", "text": "# Refresh\n\nDraft two.\n",
         "source_url": URL}])
    assert second.status_code == 200, second.text
    report = second.json()["job"]["report"]
    # J.9 (v0.61): `mode` is the caller's own word on every call. It used to
    # be rewritten to "sync" by the upload flip, which is gone.
    assert report["mode"] == "upload"
    assert "clips/clip-refresh" in report["updated"]

    text = (forest_dir / "clips" / "clip-refresh.md").read_text(encoding="utf-8")
    assert "Draft two." in text
    assert text.rstrip("\n").endswith(f"Source: {URL}")
    # Once in the body, never twice — the refresh rebuilds it, it does not
    # append to it. (G.2.7, v0.58: the passport ALSO carries the address as
    # `origin`, which is a field, not a second stamp in the prose.)
    body = text.split("\n---\n", 2)[-1]
    assert body.count(URL) == 1
    assert f"origin: {URL}" in text


@pytest.mark.parametrize("bad_url", [
    "ftp://mirror.example.com/x",          # only http(s) is an address here
    "https://example.com/" + "a" * 3000,   # over the 2048-character bound
    12345,                                  # not a string at all
])
def test_a_bad_source_url_is_schema_and_stages_nothing(station, bad_url):
    client, registry, forest_dir = station
    head = _key(registry, caps=("read", "ingest"), principal="clipper")

    r = _ingest(client, head, [
        {"name": "never-staged.md", "text": "# Never\n\nRefused whole.\n",
         "source_url": bad_url}])

    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "E_SCHEMA"
    assert "never-staged.md" in err["message"]  # names the offending entry
    # Refused BEFORE the first byte landed: nothing staged for a later
    # batch's hash-diff to mistake for a changed document, nothing planted.
    assert not (forest_dir / "_derived" / "uploads" / "never-staged.md").exists()
    assert not (forest_dir / "clips" / "never-staged.md").exists()
