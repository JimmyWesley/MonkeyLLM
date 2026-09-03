# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The passport travels with the bytes (spec v0.78, J.8.4, F.172).

The agent that followed v0.77's path uploaded a screenshot it had already
looked at, and the scent it knew — what the picture shows, which nodes it
belongs beside — had nowhere to go until a second call and a second
commit. An `upload` entry may now carry `passport`, applied under exactly
the rules a reviewed draft gets (J.8.1), in the one plant.

- the whole path over MCP: a base64 image with a passport lands as a
  media node whose `look` carries the declared scent and the link, whose
  body holds the declared `## Notes`, with `payload_type`/`payload_bytes`;
- a batch that mixes one entry with a passport and one without plants
  both, the second with the derived summary;
- a malformed passport is E_SCHEMA before anything stages — the staging
  area holds no file from that batch;
- a link to a branch or to an absent node is dropped, the node still lands.
"""
from __future__ import annotations

import base64
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
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"v078-bytes-with-a-passport" * 5
B64 = base64.b64encode(PNG_BYTES).decode()


@pytest.fixture(scope="session")
def passport_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("v078-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(passport_root, tmp_path):
    from starlette.testclient import TestClient
    from monkeyllm_station.app import build_app
    app = build_app(root=passport_root, registry_path=tmp_path / "station.db",
                    mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry, passport_root / FOREST


def _key(registry, caps=("read", "ingest", "write"), principal="alice"):
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


def _rest_ingest(client, key, body):
    return client.post(f"/v1/forests/{FOREST}/ingest",
                       headers={"Authorization": f"Bearer {key}",
                                "Content-Type": "application/json"},
                       json=body)


def _a_note(client, key) -> str:
    """Some existing, in-scope, non-branch node to link to."""
    listing = _text(_call(client, key, "scan", parent_id="_index", recursive=True,
                          fields=["id", "type"], limit=50))
    for node in listing["nodes"]:
        if node.get("type") == "note" and not node["id"].endswith("/_index"):
            return node["id"]
    raise AssertionError("fixture forest holds no note to link to")


def _staged(forest_dir: Path) -> set[str]:
    staging = forest_dir / "_derived" / "uploads"
    if not staging.exists():
        return set()
    return {p.name for p in staging.rglob("*") if p.is_file()}


# -- F.172: the whole path, with the scent --------------------------------------

def test_passport_is_planted_with_the_bytes_over_mcp(station):
    client, registry, forest_dir = station
    key = _key(registry)
    target = _a_note(client, key)

    job = _text(_call(client, key, "ingest", mode="upload", dest="notes", wait=True,
                      files=[{"name": "v078-shot.png", "b64": B64,
                              "passport": {
                                  "title": "Templates library — first screen",
                                  "summary": "The templates library as shipped: filter bar and three cards per row.",
                                  "tags": ["Templates", "screenshot", "templates"],
                                  "aliases": ["templates library print"],
                                  "links": [{"target": target,
                                             "note": "the screen this task describes"}],
                                  "notes": "Taken on staging; the third card is a placeholder.",
                              }}]))["job"]
    assert job["state"] == "done", job
    report = job["report"]
    assert len(report["planted"]) == 1, report
    node_id = report["planted"][0]

    digest = _text(_call(client, key, "look", id=node_id))
    assert digest["type"] == "media"
    assert digest["title"] == "Templates library — first screen"
    assert digest["summary"] == ("The templates library as shipped: filter bar and "
                                 "three cards per row.")
    assert "templates" in digest["tags"] and "screenshot" in digest["tags"]
    assert "templates library print" in digest.get("aliases", [])
    assert any(e.get("rel") == "related-to" and e.get("target") == target
               for e in digest["edges_out"]), digest["edges_out"]
    # The bytes are there exactly as v0.77 promised — the passport added
    # scent, it took nothing away.
    assert digest["payload_type"] == "image"
    assert digest["payload_bytes"] == len(PNG_BYTES)
    assert "payload_missing" not in digest

    body = _text(_call(client, key, "pick", id=node_id))["body"]
    assert "## Notes" in body
    assert "third card is a placeholder" in body

    # One plant, one commit: nothing left in the courier.
    assert "v078-shot.png" not in _staged(forest_dir)


def test_a_batch_mixes_passported_and_derived_entries(station):
    client, registry, forest_dir = station
    key = _key(registry)

    job = _text(_call(client, key, "ingest", mode="upload", dest="notes", wait=True,
                      files=[
                          {"name": "v078-with.png", "b64": B64,
                           "passport": {"summary": "A declared scent for the first picture."}},
                          {"name": "v078-without.png", "b64": B64},
                      ]))["job"]
    assert job["state"] == "done", job
    planted = job["report"]["planted"]
    assert len(planted) == 2, job["report"]

    digests = {d["id"]: d for d in _text(_call(client, key, "look", id=planted))["nodes"]}
    summaries = {d["summary"] for d in digests.values()}
    assert "A declared scent for the first picture." in summaries
    # The other entry kept whatever the pipeline derived — and it is not
    # the declared one: the gate decides per draft, never per batch.
    assert len(summaries) == 2


def test_a_malformed_passport_stages_nothing(station):
    client, registry, forest_dir = station
    key = _key(registry)
    before = _staged(forest_dir)

    cases = [
        ({"summary": "fine", "colour": "blue"}, "unknown field"),
        ({"summary": "This document describes"}, "A.4 budget"),
        ({"links": [{"target": "notes/x", "rel": "part-of"}]}, "related-to"),
        ({"tags": "not-a-list"}, "list of strings"),
        ({"aliases": ["x" * 81]}, "80 characters"),
        ("a string", "must be an object"),
    ]
    for passport, expected in cases:
        r = _rest_ingest(client, key, {
            "mode": "upload", "dest": "notes",
            "files": [{"name": "v078-good-first.png", "b64": B64},
                      {"name": "v078-bad.png", "b64": B64, "passport": passport}]})
        assert r.status_code == 400, (passport, r.text)
        err = r.json()["error"]
        assert err["code"] == "E_SCHEMA", err
        assert "v078-bad.png" in err["message"], err
        assert expected in err["message"] or expected in (err.get("hint") or ""), (expected, err)

    # Not even the well-formed first entry landed: a batch with one bad
    # passport stages nothing (the source_url rule, applied to scent).
    assert _staged(forest_dir) - before == set()


def test_a_link_that_fails_the_check_is_dropped_not_fatal(station):
    client, registry, forest_dir = station
    key = _key(registry)

    job = _text(_call(client, key, "ingest", mode="upload", dest="notes", wait=True,
                      files=[{"name": "v078-links.png", "b64": B64,
                              "passport": {
                                  "summary": "A picture whose links point at the wrong things.",
                                  "links": [{"target": "notes/_index"},
                                            {"target": "notes/this-node-does-not-exist"}],
                              }}]))["job"]
    assert job["state"] == "done", job
    node_id = job["report"]["planted"][0]
    digest = _text(_call(client, key, "look", id=node_id))
    assert digest["summary"] == "A picture whose links point at the wrong things."
    assert [e for e in digest["edges_out"] if e.get("rel") == "related-to"] == []


def test_the_served_description_names_the_passport(station):
    """J.1.2 rule 7, read off the SERVED tool list, not the source."""
    client, registry, _ = station
    key = _key(registry, caps=("read",))
    tools = {t["name"]: t for t in _rpc(client, key, "tools/list")["tools"]}
    text = tools["ingest"]["description"]
    for needle in ("passport", "summary", "related-to", "## Notes", "before any byte stages"):
        assert needle in text, needle


# -- the review's additions: counted refusals, the unapplied named, notes read --

def test_refused_tags_and_clipped_aliases_are_counted(station):
    """G.4.2 rule 1, applied to the caller's passport: a tag the rule
    refuses and an alias the cap clips are counted, never lost in silence."""
    client, registry, _ = station
    key = _key(registry)
    # Sixteen aliases is the most the shape check admits (more is E_SCHEMA
    # before staging); the file's own name derives at least `291` (G.2.6),
    # and the derived ones come first — so the merge overflows the cap by
    # exactly the number of derived aliases, and that number is counted.
    declared = [f"alias-{i}" for i in range(16)]
    job = _text(_call(client, key, "ingest", mode="upload", dest="notes", wait=True,
                      files=[{"name": "291-counted.png", "b64": B64,
                              "passport": {
                                  "summary": "A picture whose passport overflows.",
                                  "tags": ["fine", "a tag with spaces", "x" * 41],
                                  "aliases": declared,
                              }}]))["job"]
    assert job["state"] == "done", job
    report = job["report"]
    assert report["tags_dropped"] == 2, report
    assert report["passports_ignored"] == []
    digest = _text(_call(client, key, "look", id=report["planted"][0]))
    assert digest["tags"] == ["fine"]
    derived = [a for a in digest["aliases"] if a not in declared]
    assert derived, digest["aliases"]
    assert len(digest["aliases"]) == 16
    assert report["aliases_clipped"] == len(derived), report


def test_a_resent_passport_is_named_not_applied(station):
    """A refresh never curates (G.3): the old scent stands, and the report
    says whose passport it did not apply — the caller's next move is graft."""
    client, registry, _ = station
    key = _key(registry)
    first = {"name": "v078-again.png", "b64": B64,
             "passport": {"summary": "The first declared scent."}}
    job1 = _text(_call(client, key, "ingest", mode="upload", dest="notes",
                       wait=True, files=[first]))["job"]
    assert job1["report"]["passports_ignored"] == []
    node_id = job1["report"]["planted"][0]

    again = {**first, "passport": {"summary": "A second scent for the same bytes."}}
    job2 = _text(_call(client, key, "ingest", mode="upload", dest="notes",
                       wait=True, files=[again]))["job"]
    assert job2["state"] == "done", job2
    assert job2["report"]["planted"] == []
    assert job2["report"]["passports_ignored"] == ["v078-again.png"]
    digest = _text(_call(client, key, "look", id=node_id))
    assert digest["summary"] == "The first declared scent."


def test_look_and_the_sweep_carry_the_media_notes(station):
    """C.2.1 rule 2 and rule 6 for media (v0.78): the uploader's notes ride
    in look and in the sweep's item, not only in pick."""
    client, registry, _ = station
    key = _key(registry)
    job = _text(_call(client, key, "ingest", mode="upload", dest="notes", wait=True,
                      files=[{"name": "v078-quokka.png", "b64": B64,
                              "passport": {
                                  "title": "Quokka zebra dashboard",
                                  "summary": "The quokka zebra dashboard as shipped.",
                                  "tags": ["quokka", "zebra"],
                                  "notes": "The zebra widget is a placeholder.",
                              }}]))["job"]
    node_id = job["report"]["planted"][0]
    digest = _text(_call(client, key, "look", id=node_id))
    assert "zebra widget is a placeholder" in digest["notes"]
    assert "zebra widget is a placeholder" in \
        _text(_call(client, key, "look", id=node_id, fields=["notes"]))["notes"]
    sweep = _text(_call(client, key, "harvest", query="quokka zebra dashboard", k=3))
    item = next((r for r in sweep["results"] if r["id"] == node_id), None)
    assert item is not None, sweep
    assert "zebra widget is a placeholder" in item["notes"]


def test_the_review_hook_counts_its_refusals_too():
    """J.8.1's approval hook had the same silent drop; fixed with the gate."""
    from monkeyllm_station.compose import approval_hook
    hook = approval_hook({"tags": ["fine", "a tag with spaces", "x" * 41]},
                         vine=None, policy=None)
    draft = hook({"id": "x", "tags": []})
    assert draft["tags"] == ["fine"]
    assert hook.stats["tags_dropped"] == 2
