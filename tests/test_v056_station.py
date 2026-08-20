# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.56 — the forest replaces the file (host half).

F.84: the export route serves the planted bytes, under J.14's discipline.
F.86: the first reply states the version, and a share link is a key with
one room — expiring, revocable, re-checked against its issuer's current
reach at every serve, and byte-identically dead however it died.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-doc"

FIDELITY_BODY = (
    "# Relatório\n\n"
    "## Tabela\n\n"
    "| col | válor |\n|---|---|\n| a✓ | ção |\n\n"
    "## Código\n\n"
    "```python\nprint('exact')\n```\n\n"
    "- nested\n  - deeper — em dash\n\n"
    "> quote with emoji 🐒\n"
)


@pytest.fixture()
def station(tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    root = tmp_path / "forests"
    root.mkdir()
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        yield client, app.state.registry, root


def _key(registry, principal, caps, allow=None):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps),
                   **({"allow": allow} if allow else {}))
    return {"Authorization": f"Bearer {key}"}


def _plant_report(client, headers):
    r = client.post(f"/v1/forests/{FOREST}/plant", headers=headers, json={
        "node": {"id": "notes/report", "type": "note",
                 "parent": "notes/_index", "title": "Relatório",
                 "summary": "The fidelity probe.", "body": FIDELITY_BODY}})
    assert r.status_code == 200, r.text
    return r.json()


# -- F.84: the document is a byte surface too --------------------------------


class TestExport:
    def test_the_export_is_the_planted_file(self, station):
        client, registry, root = station
        headers = _key(registry, "writer", {"read", "write"})
        _plant_report(client, headers)
        res = client.get(f"/v1/forests/{FOREST}/export/notes/report",
                         headers=headers)
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/markdown")
        assert 'filename="report.md"' in res.headers["content-disposition"]
        on_disk = (root / FOREST / "notes" / "report.md").read_text(
            encoding="utf-8")
        assert res.text == on_disk
        assert FIDELITY_BODY in res.text

    def test_out_of_scope_and_absent_answer_identically(self, station):
        client, registry, _ = station
        writer = _key(registry, "writer", {"read", "write"})
        _plant_report(client, writer)
        scoped = _key(registry, "narrow", {"read"}, allow=["sales/"])
        hidden = client.get(f"/v1/forests/{FOREST}/export/notes/report",
                            headers=scoped)
        absent = client.get(f"/v1/forests/{FOREST}/export/sales/never-was",
                            headers=scoped)
        assert hidden.status_code == absent.status_code == 404
        norm = lambda r, nid: r.text.replace(nid, "<id>")  # noqa: E731
        assert (norm(hidden, "notes/report")
                == norm(absent, "sales/never-was"))

    def test_export_needs_the_read_capability(self, station):
        client, registry, _ = station
        key = registry.issue_key("ingester")
        registry.grant("ingester", FOREST, {"ingest"})
        res = client.get(f"/v1/forests/{FOREST}/export/notes/report",
                         headers={"Authorization": f"Bearer {key}"})
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "E_FORBIDDEN"


# -- F.86: the first reply states the version --------------------------------


class TestStationVersion:
    def test_forests_carries_station(self, station):
        client, registry, _ = station
        headers = _key(registry, "reader", {"read"})
        body = client.get("/v1/forests", headers=headers).json()
        assert body["station"]
        health = client.get("/v1/health").json()
        assert body["station"] == health["version"]


# -- F.86: a share is a key with one room ------------------------------------


class TestShares:
    def _mint(self, client, headers, node="notes/report", days=None):
        payload = {"node": node}
        if days is not None:
            payload["days"] = days
        r = client.post(f"/v1/forests/{FOREST}/share", headers=headers,
                        json=payload)
        return r

    def test_the_shared_document_serves_with_no_session(self, station):
        client, registry, _ = station
        headers = _key(registry, "writer", {"read", "write"})
        _plant_report(client, headers)
        minted = self._mint(client, headers)
        assert minted.status_code == 200
        share = minted.json()
        assert share["url"].startswith("/s/") and share["expires"]
        token = share["url"].rsplit("/", 1)[-1]
        served = client.get(f"/v1/share/{token}")
        assert served.status_code == 200
        doc = served.json()
        assert doc["title"] == "Relatório"
        assert doc["markdown"] == FIDELITY_BODY
        assert doc["outline"]

    def test_every_dead_share_wears_one_envelope(self, station):
        client, registry, _ = station
        headers = _key(registry, "writer", {"read", "write"})
        _plant_report(client, headers)
        token = self._mint(client, headers).json()["url"].rsplit("/", 1)[-1]
        share_id = client.get(f"/v1/forests/{FOREST}/shares",
                              headers=headers).json()["shares"][0]["id"]
        never = client.get("/v1/share/deadbeefdeadbeefdeadbeefdeadbeef")
        client.delete(f"/v1/forests/{FOREST}/shares/{share_id}",
                      headers=headers)
        revoked = client.get(f"/v1/share/{token}")
        assert revoked.status_code == never.status_code == 404
        assert revoked.text == never.text

    def test_a_lapsed_grant_suspends_the_share(self, station):
        client, registry, _ = station
        headers = _key(registry, "writer", {"read", "write"})
        _plant_report(client, headers)
        token = self._mint(client, headers).json()["url"].rsplit("/", 1)[-1]
        assert client.get(f"/v1/share/{token}").status_code == 200
        registry.revoke("writer", FOREST)
        gone = client.get(f"/v1/share/{token}")
        assert gone.status_code == 404
        never = client.get("/v1/share/deadbeefdeadbeefdeadbeefdeadbeef")
        assert gone.text == never.text

    def test_the_listing_never_carries_the_token(self, station):
        client, registry, _ = station
        headers = _key(registry, "writer", {"read", "write"})
        _plant_report(client, headers)
        token = self._mint(client, headers).json()["url"].rsplit("/", 1)[-1]
        listing = client.get(f"/v1/forests/{FOREST}/shares",
                             headers=headers)
        assert token not in listing.text
        assert listing.json()["shares"][0]["node"] == "notes/report"

    def test_a_share_is_issued_inside_the_issuers_reach(self, station):
        client, registry, _ = station
        writer = _key(registry, "writer", {"read", "write"})
        _plant_report(client, writer)
        narrow = _key(registry, "narrow", {"read"}, allow=["sales/"])
        refused = self._mint(client, narrow)
        assert refused.status_code == 404
        assert refused.json()["error"]["code"] == "E_NOT_FOUND"

    def test_days_are_bounded(self, station):
        client, registry, _ = station
        headers = _key(registry, "writer", {"read", "write"})
        _plant_report(client, headers)
        assert self._mint(client, headers, days=91).status_code == 400
        assert self._mint(client, headers, days=0).status_code == 400
        assert self._mint(client, headers, days=90).status_code == 200

    def test_another_issuers_share_is_invisible_to_revoke(self, station):
        client, registry, _ = station
        writer = _key(registry, "writer", {"read", "write"})
        _plant_report(client, writer)
        share_id = self._mint(client, writer).json()["id"]
        other = _key(registry, "other", {"read"})
        listing = client.get(f"/v1/forests/{FOREST}/shares", headers=other)
        assert listing.json()["shares"] == []
        refused = client.delete(f"/v1/forests/{FOREST}/shares/{share_id}",
                                headers=other)
        assert refused.status_code == 404


# -- C.14 over the wire ------------------------------------------------------


class TestPruneOverRest:
    def test_prune_rides_the_write_capability(self, station):
        client, registry, _ = station
        writer = _key(registry, "writer", {"read", "write"})
        _plant_report(client, writer)
        reader = _key(registry, "reader", {"read"})
        refused = client.post(f"/v1/forests/{FOREST}/prune", headers=reader,
                              json={"id": "notes/report"})
        assert refused.json()["error"]["code"] == "E_FORBIDDEN"
        assert "'write'" in refused.json()["error"]["message"]
        done = client.post(f"/v1/forests/{FOREST}/prune", headers=writer,
                           json={"id": "notes/report"})
        assert done.status_code == 200
        body = done.json()
        assert body["pruned"] is True and body["commit"]

    def test_the_refusal_carries_the_anchors(self, station):
        client, registry, _ = station
        writer = _key(registry, "writer", {"read", "write"})
        _plant_report(client, writer)
        client.post(f"/v1/forests/{FOREST}/graft", headers=writer, json={
            "id": "sales/returns-q1",
            "patch": {"add_links": [{"rel": "related-to",
                                     "target": "notes/report"}]}})
        refused = client.post(f"/v1/forests/{FOREST}/prune", headers=writer,
                              json={"id": "notes/report"})
        assert refused.status_code == 409
        err = refused.json()["error"]
        assert err["code"] == "E_ANCHORED"
        assert err["anchors"][0]["source"] == "sales/returns-q1"
