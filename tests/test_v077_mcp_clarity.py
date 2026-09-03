# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The path was there and nothing named it (spec v0.77, F.171).

An agent planted a `type: media` node "with" an image, was told
`created: true`, got `E_NOT_FOUND` from `view`, and reported that the
product cannot store a binary. `ingest(mode="upload", files=[{name, b64}])`
had done exactly that since v0.48. This file is the round's acceptance:

- the whole path, end to end, through the MCP surface an agent actually
  holds — ingest a base64 image, `look` says what the bytes are, `view`
  serves them, `prune` moves them to the graveyard;
- the write that used to lie: `plant` of a media node without bytes is
  refused at the plant, with a hint naming the path (C.7.5), and the
  Gardener's own adopt under `archive: never` is exempt;
- the read that could not say: `look` carries `payload_missing` or
  `payload_type` + `payload_bytes` for media (C.2.2 rule 6), while `view`'s
  envelope is unchanged to the byte;
- the scope that named an id the caller never typed (C.6b);
- and the descriptions themselves (J.1.2 rule 7), read off the SERVED
  tool list rather than the source, because a description is a contract
  nobody else compares.
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

import pytest
from conftest import build_forest

from monkeyllm.errors import E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.forest import init_forest
from monkeyllm.vine import Vine

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
HEADERS = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"v077-bytes-that-view-must-serve" * 5


# -- helpers -------------------------------------------------------------------

@pytest.fixture(scope="session")
def clarity_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("v077-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(clarity_root, tmp_path):
    from starlette.testclient import TestClient
    from monkeyllm_station.app import build_app
    app = build_app(root=clarity_root, registry_path=tmp_path / "station.db",
                    mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry, clarity_root / FOREST


def _key(registry, caps=("read",), principal="alice"):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps))
    return key


def _rpc(client, key, method, params=None, rid=1):
    headers = {**HEADERS, "Authorization": f"Bearer {key}"}
    r = client.post("/mcp/", headers=headers, json={
        "jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def _call(client, key, name, **arguments):
    return _rpc(client, key, "tools/call",
                {"name": name, "arguments": {"forest": FOREST, **arguments}})


def _text(result) -> dict:
    return json.loads(next(c["text"] for c in result["content"]
                           if c["type"] == "text"))


@pytest.fixture()
def vine(tmp_path):
    root = tmp_path / "forest"
    init_forest(root, title="v0.77 clarity")
    v = Vine(root, writable=True)
    yield v
    v.close()


def _media(node_id="shot", payload="_assets/shot.png", **extra) -> dict:
    return {"id": node_id, "parent": "_index", "type": "media",
            "title": node_id, "summary": "A media passport under test.",
            "payload": payload, "payload_type": "image", **extra}


def _write(vine, rel: str, data: bytes = PNG_BYTES) -> Path:
    target = vine.forest.root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


# -- F.171: the whole path, through the MCP surface ---------------------------

def test_an_image_travels_ingest_look_view_prune_over_mcp(station):
    """One test for the path the report said did not exist."""
    client, registry, forest_dir = station
    key = _key(registry, caps=("read", "ingest", "write"))

    job = _text(_call(client, key, "ingest", mode="upload", dest="notes",
                      files=[{"name": "v077-shot.png",
                              "b64": base64.b64encode(PNG_BYTES).decode()}],
                      wait=True))["job"]
    assert job["state"] == "done", job
    planted = job["report"]["planted"]
    assert len(planted) == 1, job["report"]
    node_id = planted[0]

    # `look` says what the bytes are BEFORE anybody spends a view.
    digest = _text(_call(client, key, "look", id=node_id))
    assert digest["type"] == "media"
    assert digest["payload_type"] == "image"
    assert digest["payload_bytes"] == len(PNG_BYTES)
    assert "payload_missing" not in digest

    # `view` serves exactly the bytes that were uploaded.
    shown = _call(client, key, "view", id=node_id)
    image = next(c for c in shown["content"] if c["type"] == "image")
    assert base64.b64decode(image["data"]) == PNG_BYTES
    assert _text(shown)["size"] == len(PNG_BYTES)

    # `prune` takes the passport out and moves the bytes to the graveyard.
    pruned = _text(_call(client, key, "prune", id=node_id))
    assert "error" not in pruned, pruned
    graveyard = forest_dir / "_derived" / "graveyard"
    assert any(p.is_file() and p.read_bytes() == PNG_BYTES
               for p in graveyard.rglob("*")), "the bytes left with the node"
    gone = _text(_call(client, key, "look", id=node_id))
    assert gone["error"]["code"] == "E_NOT_FOUND"


# -- C.7.5: a media passport names bytes the forest holds ---------------------

class TestMediaPlant:
    def test_no_payload_is_refused_with_the_path_named(self, vine):
        node = _media()
        del node["payload"]
        with pytest.raises(VineError) as exc:
            vine.plant(node)
        assert exc.value.code == E_SCHEMA
        assert "needs a payload" in exc.value.message
        assert "ingest(" in exc.value.hint and "b64" in exc.value.hint
        assert not vine.forest.exists("shot")

    def test_a_payload_naming_no_file_is_refused_at_the_plant(self, vine):
        with pytest.raises(VineError) as exc:
            vine.plant(_media(payload="_assets/never-written.png"))
        assert exc.value.code == E_SCHEMA
        assert "payload not found" in exc.value.message
        assert "ingest(" in exc.value.hint

    def test_a_payload_outside_the_forest_is_refused_at_the_plant(
            self, vine, tmp_path):
        (tmp_path / "outside.png").write_bytes(PNG_BYTES)
        with pytest.raises(VineError) as exc:
            vine.plant(_media(payload="../outside.png"))
        assert exc.value.code == E_SCHEMA
        assert "escapes the forest" in exc.value.message

    def test_it_rehearses_and_it_refuses_a_batch(self, vine):
        node = _media()
        del node["payload"]
        with pytest.raises(VineError) as exc:
            vine.plant(node, dry_run=True)
        assert exc.value.code == E_SCHEMA
        note = {"id": "fine", "parent": "_index", "type": "note",
                "title": "fine", "summary": "A note that must not land alone."}
        with pytest.raises(VineError):
            vine.plant([note, node])
        assert not vine.forest.exists("fine"), "a batch is one plant (C.7.4)"

    def test_bytes_already_in_the_forest_may_be_referenced(self, vine):
        _write(vine, "_assets/shot.png")
        out = vine.plant(_media())
        assert out["created"] is True

    def test_a_remote_uri_is_accepted_as_written(self, vine):
        out = vine.plant(_media(node_id="remote", payload="s3://bucket/x.png"))
        assert out["created"] is True
        digest = vine.look("remote")
        assert digest["payload_type"] == "image"
        assert "payload_bytes" not in digest
        assert "payload_missing" not in digest

    def test_the_gardener_is_exempt_under_archive_never(self, vine, tmp_path):
        """G.7: an adopted image is referenced, not copied — its passport
        names no payload by design, and `look` says so instead of the
        plant refusing the Gardener's own tier."""
        from monkeyllm.gardener import Gardener
        src = tmp_path / "src"
        src.mkdir()
        (src / "team.png").write_bytes(PNG_BYTES)
        Gardener(vine, hooks=[]).adopt(src)
        node = vine.forest.read("team")
        assert node.frontmatter["type"] == "media"
        assert not node.frontmatter.get("payload")
        assert vine.look("team")["payload_missing"] is True


# -- C.2.2 rule 6: look says whether the bytes are there ----------------------

class TestLookPayload:
    def test_present_bytes_are_typed_and_sized(self, vine):
        _write(vine, "_assets/shot.png")
        vine.plant(_media())
        digest = vine.look("shot")
        assert digest["payload_type"] == "image"
        assert digest["payload_bytes"] == len(PNG_BYTES)
        assert "payload_missing" not in digest

    def test_vanished_bytes_are_a_flag_and_view_is_unchanged(self, vine):
        _write(vine, "_assets/shot.png")
        vine.plant(_media())
        (vine.forest.root / "_assets" / "shot.png").unlink()
        digest = vine.look("shot")
        assert digest["payload_missing"] is True
        assert "payload_bytes" not in digest
        # The flag survives a `fields` filter, exactly as a dataset's does.
        assert vine.look("shot", fields=["summary"])["payload_missing"] is True
        # And `view` keeps C.6d rule 1 to the byte: the missing-node envelope.
        with pytest.raises(VineError) as exc:
            vine.view("shot")
        assert exc.value.code == E_NOT_FOUND
        assert exc.value.message == "node not found: shot"

    def test_a_note_without_a_payload_carries_no_flag(self, vine):
        vine.plant({"id": "plain", "parent": "_index", "type": "note",
                    "title": "plain", "summary": "A note has no bytes to miss."})
        digest = vine.look("plain")
        assert "payload_missing" not in digest
        assert "payload_type" not in digest


# -- C.6b: a wrong scope is told what a scope is ------------------------------

class TestScope:
    def test_the_dialect_is_not_a_scope(self, vine):
        with pytest.raises(VineError) as exc:
            vine.sniff(["anything"], scope="_meta")
        assert exc.value.code == E_SCHEMA
        assert "dialect" in exc.value.message
        assert "branch id" in exc.value.hint

    def test_an_unknown_scope_names_what_the_caller_sent(self, vine):
        with pytest.raises(VineError) as exc:
            vine.sniff(["anything"], scope="nope")
        assert exc.value.code == E_NOT_FOUND
        assert exc.value.message == "scope not found: nope"
        assert "_index" not in exc.value.message
        assert "branch id" in exc.value.hint

    def test_calendar_shares_the_reading(self, vine):
        with pytest.raises(VineError) as exc:
            vine.calendar(scope="_meta")
        assert exc.value.code == E_SCHEMA


# -- J.1.2 rule 7: the served descriptions name their neighbours --------------

def test_every_refusing_tool_names_the_neighbour_that_does_it(station):
    client, registry, _ = station
    key = _key(registry)
    tools = _rpc(client, key, "tools/list")["tools"]
    desc = {t["name"]: t["description"] for t in tools}

    assert "b64" in desc["ingest"] and "media" in desc["ingest"]
    assert "unsupported" in desc["ingest"]
    assert "payload_missing" in desc["view"] and "ingest(" in desc["view"]
    assert "carries no bytes" in desc["plant"] and "ingest(" in desc["plant"]
    assert "scope" in desc["sniff"] and "_meta" in desc["sniff"]
    assert "payload_missing" in desc["look"]

    init = _rpc(client, key, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"}})
    instructions = init["instructions"]
    assert "b64" in instructions
    assert "payload_missing" in instructions
    assert "carries no bytes" in instructions
    # Rule 5 still holds beside rule 7: every tool is still named.
    missing = [n for n in desc if f"{n}(" not in instructions]
    assert not missing, missing


def test_a_hand_written_media_passport_still_reads(vine):
    """C.7.5 rule 5: a pre-v0.77 passport without bytes — written by hand
    here, since the plant now refuses it — opens, grafts and prunes."""
    passport = vine.forest.root / "old.md"
    passport.write_text(
        "---\nid: old\ntype: media\ntitle: old\n"
        "summary: A media passport from before the rule.\n"
        "created: 2026-01-01\nupdated: 2026-01-01\nsource: manual\n"
        "confidence: 1.0\ntags: []\nlinks: []\n---\n\nAn image nobody sent.\n",
        encoding="utf-8")
    vine.reindex()
    assert vine.look("old")["payload_missing"] is True
    vine.graft("old", {"set_frontmatter": {"title": "old, retitled"}})
    assert vine.look("old")["title"] == "old, retitled"
