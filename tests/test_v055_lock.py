# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""A lock is possession, not a file (spec v0.55 — F.75/F.76/F.77/F.78).

The 0.54.0 upgrade killed the container the way every upgrade does, and the
Station that came up could open nothing: an orphan `.vine.lock` per forest,
`E_LOCKED` on every primitive — while `/v1/health` said `ok` and `forests()`
listed both forests with full capabilities. Possession is now the kernel's
advisory lock (C.9), the lock is inspectable and releasable over HTTP
(J.13.5), availability tells the truth (J.1.3), and the served instructions
name every tool (J.1.2 rule 5).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from conftest import build_forest
from monkeyllm.errors import E_LOCKED, VineError
from monkeyllm.forest import WriterLock
from monkeyllm.vine import Vine

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}


# --- F.75, engine: the kernel decides, the card explains --------------------

class TestWriterLockPossession:
    def test_an_orphan_file_is_reclaimed_silently(self, forest_rw):
        (forest_rw / ".vine.lock").write_text("999999", encoding="utf-8")
        v = Vine(forest_rw, writable=True)  # no error, no manual step
        try:
            card = json.loads((forest_rw / ".vine.lock").read_text())
            assert card["pid"] == os.getpid()
            assert card["host"] and card["since"]
        finally:
            v.close()

    def test_a_live_writer_refuses_naming_its_card(self, forest_rw):
        v1 = Vine(forest_rw, writable=True)
        try:
            with pytest.raises(VineError) as e:
                Vine(forest_rw, writable=True)
            assert e.value.code == E_LOCKED
            assert str(os.getpid()) in e.value.message
            assert "reclaimed automatically" in (e.value.hint or "")
        finally:
            v1.close()
        Vine(forest_rw, writable=True).close()  # the close admitted us

    def test_probe_answers_free_orphan_and_held(self, forest_rw):
        assert WriterLock.probe(forest_rw)["state"] == "free"
        (forest_rw / ".vine.lock").write_text("999999", encoding="utf-8")
        probed = WriterLock.probe(forest_rw)
        assert probed["state"] == "orphan"
        assert probed["holder"] == {"pid": 999999}  # the legacy card parses
        (forest_rw / ".vine.lock").unlink()
        holder = WriterLock(forest_rw)
        holder.acquire()
        try:
            probed = WriterLock.probe(forest_rw)
            assert probed["state"] == "held"
            assert probed["holder"]["pid"] == os.getpid()
        finally:
            holder.release()
        assert WriterLock.probe(forest_rw)["state"] == "free"

    def test_break_orphan_removes_the_dead_and_refuses_the_living(self, forest_rw):
        assert WriterLock.break_orphan(forest_rw) == {"state": "free",
                                                      "removed": False}
        (forest_rw / ".vine.lock").write_text("999999", encoding="utf-8")
        out = WriterLock.break_orphan(forest_rw)
        assert out["removed"] is True and out["state"] == "orphan"
        assert not (forest_rw / ".vine.lock").exists()
        holder = WriterLock(forest_rw)
        holder.acquire()
        try:
            with pytest.raises(VineError) as e:
                WriterLock.break_orphan(forest_rw)
            assert e.value.code == E_LOCKED
            assert (forest_rw / ".vine.lock").exists()
        finally:
            holder.release()


# --- the station fixture ----------------------------------------------------

@pytest.fixture(scope="session")
def lock_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("lock-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(lock_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=lock_root, registry_path=tmp_path / "station.db",
                    mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry


def _close_pool(client):
    state = client.app.state
    for entry in state.pool.list()["forests"]:
        if entry["active"]:
            fid = entry["id"]
            state.forest_lane(fid).submit(
                lambda fid=fid: state.pool.close_one(fid)).result()


def _key(registry, caps=("read", "admin"), principal="boss"):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps))
    return {"Authorization": f"Bearer {key}"}


# --- F.76: the lock, inspected and released over HTTP -----------------------

class TestAdminLockSurface:
    def test_locks_reports_the_three_states(self, station, lock_root):
        client, registry = station
        head = _key(registry)
        _close_pool(client)
        assert client.get(f"/v1/admin/locks?forest={FOREST}",
                          headers=head).json()["state"] == "free"
        (lock_root / FOREST / ".vine.lock").write_text("999999")
        try:
            assert client.get(f"/v1/admin/locks?forest={FOREST}",
                              headers=head).json()["state"] == "orphan"
        finally:
            (lock_root / FOREST / ".vine.lock").unlink(missing_ok=True)
        holder = WriterLock(lock_root / FOREST)
        holder.acquire()
        try:
            body = client.get(f"/v1/admin/locks?forest={FOREST}",
                              headers=head).json()
            assert body["state"] == "held"
            assert body["holder"]["pid"] == os.getpid()
            assert "self" not in body  # a foreign writer, not this Station
        finally:
            holder.release()

    def test_the_station_marks_its_own_lock_as_self(self, station):
        client, registry = station
        head = _key(registry)
        # Boot warming opened the forest, so the Station holds its own lock.
        body = client.get(f"/v1/admin/locks?forest={FOREST}",
                          headers=head).json()
        assert body["state"] == "held" and body.get("self") is True

    def test_unlock_removes_an_orphan_and_audits_it(self, station, lock_root):
        client, registry = station
        head = _key(registry)
        _close_pool(client)
        (lock_root / FOREST / ".vine.lock").write_text("999999")
        r = client.post("/v1/admin/unlock", json={"forest": FOREST},
                        headers=head)
        assert r.status_code == 200, r.text
        assert r.json()["removed"] is True
        assert not (lock_root / FOREST / ".vine.lock").exists()
        rows = registry.audit(limit=10, principal="boss")
        assert any(row["primitive"] == "admin.unlock" for row in rows)

    def test_unlock_refuses_a_live_writer(self, station, lock_root):
        client, registry = station
        head = _key(registry)
        _close_pool(client)
        holder = WriterLock(lock_root / FOREST)
        holder.acquire()
        try:
            r = client.post("/v1/admin/unlock", json={"forest": FOREST},
                            headers=head)
            assert r.status_code == 409, r.text
            assert r.json()["error"]["code"] == E_LOCKED
            assert (lock_root / FOREST / ".vine.lock").exists()
        finally:
            holder.release()

    def test_the_gate_and_the_schema_still_apply(self, station):
        client, registry = station
        head = _key(registry)
        r = client.post("/v1/admin/unlock", json={}, headers=head)
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "E_SCHEMA"
        reader = _key(registry, caps=("read",), principal="reader")
        r = client.post("/v1/admin/unlock", json={"forest": FOREST},
                        headers=reader)
        assert r.status_code == 403


# --- F.77: the door tells the truth about the rooms -------------------------

class TestAvailabilityTruth:
    def test_health_degrades_on_a_held_forest_and_leaks_no_id(
            self, station, lock_root):
        client, registry = station
        _close_pool(client)
        holder = WriterLock(lock_root / FOREST)
        holder.acquire()
        try:
            body = client.get("/v1/health").json()
            assert body["status"] == "degraded"
            assert body["forests"] == {"served": 0, "locked": 1}
            assert FOREST not in json.dumps(body)  # counts, never ids
        finally:
            holder.release()
        body = client.get("/v1/health").json()
        assert body["status"] == "ok"
        assert body["forests"]["locked"] == 0

    def test_an_orphan_marks_nothing(self, station, lock_root):
        client, registry = station
        _close_pool(client)
        (lock_root / FOREST / ".vine.lock").write_text("999999")
        body = client.get("/v1/health").json()
        assert body["status"] == "ok" and body["forests"]["locked"] == 0

    def test_forests_marks_the_locked_entry_on_both_surfaces(
            self, station, lock_root):
        client, registry = station
        key = registry.issue_key("agent")
        registry.grant("agent", FOREST, {"read"})
        head = {"Authorization": f"Bearer {key}"}
        _close_pool(client)
        holder = WriterLock(lock_root / FOREST)
        holder.acquire()
        try:
            rest = client.get("/v1/forests", headers=head).json()["forests"]
            assert rest[0]["id"] == FOREST and rest[0]["locked"] is True
            r = client.post("/mcp/", headers={**MCP_HEADERS, **head},
                            json={"jsonrpc": "2.0", "id": 1,
                                  "method": "tools/call",
                                  "params": {"name": "forests",
                                             "arguments": {}}})
            out = json.loads(r.json()["result"]["content"][0]["text"])
            assert out["forests"][0]["locked"] is True
        finally:
            holder.release()
        rest = client.get("/v1/forests", headers=head).json()["forests"]
        assert "locked" not in rest[0]


# --- F.78: the instructions name every tool ---------------------------------

def test_the_instructions_name_every_tool(station):
    client, registry = station
    head = _key(registry)
    init = client.post("/mcp/", headers={**MCP_HEADERS, **head},
                       json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2025-06-18",
                                        "capabilities": {},
                                        "clientInfo": {"name": "t",
                                                       "version": "0"}}})
    instructions = init.json()["result"]["instructions"]
    tools = client.post("/mcp/", headers={**MCP_HEADERS, **head},
                        json={"jsonrpc": "2.0", "id": 2,
                              "method": "tools/list"})
    names = [t["name"] for t in tools.json()["result"]["tools"]]
    assert len(names) >= 16
    missing = [n for n in names if f"{n}(" not in instructions]
    assert not missing, f"instructions never mention: {missing}"
