# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.57 — the forest serves a hundred readers (host half).

F.92: reads ride a reader pool and never wait for the writer lane; the
sweep `answer`'s provider call runs on no lane at all, and its trace
carries only its own retrieval; `MONKEYLLM_STATION_READERS=0` restores
the single lane.
F.93: `export?recursive=true` zips the in-scope subtree, member by member
byte-identical to the single export; unknown query parameters refuse.
F.94 (host half): the acting principal rides the original commit through
the engine's trailer seam — the amend fallback never runs.
"""

from __future__ import annotations

import io
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-readers"
QUESTION = "architecture notes"


def _build(tmp_path, monkeypatch, root, *, readers=None, chat=None):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    if readers is None:
        monkeypatch.delenv("MONKEYLLM_STATION_READERS", raising=False)
    else:
        monkeypatch.setenv("MONKEYLLM_STATION_READERS", str(readers))
    if chat is not None:
        monkeypatch.setattr(
            inference, "chat_from_binding",
            lambda binding, **_kw: (chat, binding.get("model", "stub")))
    app = build_app(root=root, registry_path=tmp_path / "station.db",
                    mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"admin", "read", "write", "query"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    client = TestClient(app)
    client.__enter__()
    return app, client, registry, {"Authorization": f"Bearer {key}"}


@pytest.fixture()
def root(tmp_path):
    root = tmp_path / "forests"
    root.mkdir()
    build_forest(root / FOREST)
    return root


# -- F.92: reads never wait for the writer lane -------------------------------


def test_a_read_completes_while_the_writer_lane_is_held(
        root, tmp_path, monkeypatch):
    app, client, _, head = _build(tmp_path, monkeypatch, root)
    try:
        writer_lane = app.state.forest_lane(FOREST)
        held = writer_lane.submit(time.sleep, 3.0)
        t0 = time.perf_counter()
        r = client.post(f"/v1/forests/{FOREST}/look",
                        json={"id": "_index"}, headers=head)
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, r.text
        assert not held.done(), \
            "the read finished while the writer lane was still held"
        assert elapsed < 2.5
        held.result()
    finally:
        client.__exit__(None, None, None)


def test_the_graph_projection_rides_the_readers_too(
        root, tmp_path, monkeypatch):
    app, client, _, head = _build(tmp_path, monkeypatch, root)
    try:
        held = app.state.forest_lane(FOREST).submit(time.sleep, 3.0)
        r = client.get(f"/v1/forests/{FOREST}/graph", headers=head)
        assert r.status_code == 200 and r.json()["nodes"]
        assert not held.done()
        held.result()
    finally:
        client.__exit__(None, None, None)


def test_zero_restores_the_single_lane(root, tmp_path, monkeypatch):
    app, client, _, head = _build(tmp_path, monkeypatch, root, readers=0)
    try:
        r = client.post(f"/v1/forests/{FOREST}/look",
                        json={"id": "_index"}, headers=head)
        assert r.status_code == 200
        # The single lane serialises: a held writer lane delays the read.
        held = app.state.forest_lane(FOREST).submit(time.sleep, 0.5)
        t0 = time.perf_counter()
        r = client.post(f"/v1/forests/{FOREST}/look",
                        json={"id": "_index"}, headers=head)
        assert r.status_code == 200
        assert time.perf_counter() - t0 >= 0.4
        held.result()
    finally:
        client.__exit__(None, None, None)


def test_the_readers_share_one_trails_store(root, tmp_path, monkeypatch):
    """The whisper lands on a reader vine; the trails projection reads it
    from another. One `_derived/` store, N connections — WAL's promise,
    with `busy_timeout` making the concurrent deposits survivable."""
    app, client, _, head = _build(tmp_path, monkeypatch, root,
                                  chat=lambda messages: "stub answer")
    try:
        first = client.post(f"/v1/forests/{FOREST}/answer",
                            json={"question": QUESTION}, headers=head)
        assert first.status_code == 200, first.text
        evidence = first.json()["evidence"]
        assert evidence
        body = client.get(f"/v1/forests/{FOREST}/trails",
                          headers=head).json()
        heat = {row["id"]: row["heat"] for row in body["heat"]}
        assert any(heat.get(nid, 0.0) > 0.0 for nid in evidence), \
            "the whisper crossed the reader vines"
    finally:
        client.__exit__(None, None, None)


# -- F.92: the provider is not a lane -----------------------------------------


def test_the_model_call_holds_no_lane_and_the_trace_stays_its_own(
        root, tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    replies: list = []

    def chat(messages):
        replies.append(messages)
        if len(replies) > 1:
            entered.set()
            assert release.wait(10), "the test forgot to release the model"
        return f"stub answer #{len(replies)}"

    # ONE reader slot: the interleaved read must land on the very lane the
    # answer prepared on, so the captured trace slice is what protects it.
    app, client, _, head = _build(tmp_path, monkeypatch, root,
                                  readers=1, chat=chat)
    try:
        clean = client.post(
            f"/v1/forests/{FOREST}/answer",
            json={"question": QUESTION, "cache": False}, headers=head)
        assert clean.status_code == 200, clean.text
        baseline = [s["step"] for s in clean.json()["trace"]["steps"]]

        result: dict = {}

        def ask():
            result["r"] = client.post(
                f"/v1/forests/{FOREST}/answer",
                json={"question": QUESTION, "cache": False}, headers=head)

        worker = threading.Thread(target=ask)
        worker.start()
        assert entered.wait(10), "the provider call never started"
        # The model is mid-write and the ONLY reader lane is free: a read
        # of the same forest completes now.
        t0 = time.perf_counter()
        r = client.post(f"/v1/forests/{FOREST}/look",
                        json={"id": "_index"}, headers=head)
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200 and elapsed < 2.0
        release.set()
        worker.join(timeout=10)
        assert not worker.is_alive()
        served = result["r"]
        assert served.status_code == 200, served.text
        # The interleaved look ran on the same lane between prepare and
        # settle — the captured slice keeps it out of this call's trace.
        steps = [s["step"] for s in served.json()["trace"]["steps"]]
        assert steps == baseline
        assert "vine" in served.headers.get("server-timing", "")
    finally:
        release.set()
        client.__exit__(None, None, None)


def test_two_cold_asks_run_their_model_calls_concurrently(
        root, tmp_path, monkeypatch):
    """P-01, measured by the team as 0.3 req/s pinned: one model call at a
    time. With the lane hold gone, two misses generate in parallel — the
    barrier below deadlocks unless both are inside the provider at once."""
    barrier = threading.Barrier(2, timeout=15)

    def chat(messages):
        barrier.wait()
        return "parallel stub answer"

    app, client, _, head = _build(tmp_path, monkeypatch, root, chat=chat)
    try:
        results: list = []

        def ask(question):
            results.append(client.post(
                f"/v1/forests/{FOREST}/answer",
                json={"question": question, "cache": False}, headers=head))

        workers = [threading.Thread(target=ask, args=(q,))
                   for q in (QUESTION, "stigmergy sales")]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=20)
        assert not any(w.is_alive() for w in workers), \
            "the two model calls never overlapped"
        assert all(r.status_code == 200 for r in results), \
            [r.text for r in results]
    finally:
        client.__exit__(None, None, None)


def test_health_states_the_deployments_shape(root, tmp_path, monkeypatch):
    monkeypatch.setenv("MONKEYLLM_STATION_MODEL_CONCURRENCY", "3")
    app, client, _, _head = _build(tmp_path, monkeypatch, root, readers=2)
    try:
        h = client.get("/v1/health").json()
        assert h["concurrency"] == {"readers": 2, "model": 3}
    finally:
        client.__exit__(None, None, None)


def test_the_store_still_serves_across_the_phases(root, tmp_path, monkeypatch):
    calls: list = []

    def chat(messages):
        calls.append(messages)
        return f"stub answer #{len(calls)}"

    app, client, _, head = _build(tmp_path, monkeypatch, root, chat=chat)
    try:
        first = client.post(f"/v1/forests/{FOREST}/answer",
                            json={"question": QUESTION}, headers=head)
        assert first.status_code == 200 and len(calls) == 1
        second = client.post(f"/v1/forests/{FOREST}/answer",
                             json={"question": QUESTION}, headers=head)
        assert second.status_code == 200
        assert second.json()["cached"] is True and len(calls) == 1
        assert second.json()["answer"] == first.json()["answer"]
    finally:
        client.__exit__(None, None, None)


def test_the_reading_fingerprint_reads_the_time(root):
    from monkeyllm_station import answer_store

    base = {"results": [{"id": "a", "type": "note", "title": "A",
                         "summary": "s", "matches": [], "content": None}]}
    dated = {"results": [dict(base["results"][0], updated="2026-08-01")]}
    ordered = {"results": [dict(base["results"][0],
                                superseded_by=["b"])]}
    fp = answer_store.reading_fingerprint
    assert fp(base) != fp(dated), "material re-dated is material re-read"
    assert fp(base) != fp(ordered), "material re-ordered is material re-read"


# -- F.93: the subtree exports too --------------------------------------------


def _plant(client, head, node_id, title, *, body="# Doc\n\nText."):
    r = client.post(f"/v1/forests/{FOREST}/plant", headers=head, json={
        "node": {"id": node_id, "type": "note",
                 "parent": f"{node_id.rsplit('/', 1)[0]}/_index",
                 "title": title, "summary": f"{title} for the zip suite.",
                 "body": body}})
    assert r.status_code == 200, r.text


class TestRecursiveExport:
    def test_the_zip_is_the_subtree_member_by_member(
            self, root, tmp_path, monkeypatch):
        app, client, _, head = _build(tmp_path, monkeypatch, root)
        try:
            _plant(client, head, "notes/zip-one", "Zip one")
            _plant(client, head, "notes/zip-two", "Zip two")
            r = client.get(
                f"/v1/forests/{FOREST}/export/notes/_index?recursive=true",
                headers=head)
            assert r.status_code == 200, r.text
            assert r.headers["content-type"].startswith("application/zip")
            assert 'filename="notes.zip"' in r.headers["content-disposition"]
            zf = zipfile.ZipFile(io.BytesIO(r.content))
            names = set(zf.namelist())
            assert {"notes/_index.md", "notes/zip-one.md",
                    "notes/zip-two.md"} <= names
            single = client.get(
                f"/v1/forests/{FOREST}/export/notes/zip-one", headers=head)
            assert zf.read("notes/zip-one.md") == single.content
        finally:
            client.__exit__(None, None, None)

    def test_a_scope_sees_its_own_zip(self, root, tmp_path, monkeypatch):
        app, client, registry, head = _build(tmp_path, monkeypatch, root)
        try:
            _plant(client, head, "notes/zip-one", "Zip one")
            key = registry.issue_key("narrow")
            registry.grant("narrow", FOREST, {"read"}, allow=["notes/"])
            narrow = {"Authorization": f"Bearer {key}"}
            r = client.get(
                f"/v1/forests/{FOREST}/export/notes/_index?recursive=true",
                headers=narrow)
            assert r.status_code == 200, r.text
            names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
            assert all(n.startswith("notes/") for n in names)
            # And a subtree outside the scope answers the byte-identical
            # not-found of a branch that never existed (J.14).
            hidden = client.get(
                f"/v1/forests/{FOREST}/export/sales/_index?recursive=true",
                headers=narrow)
            absent = client.get(
                f"/v1/forests/{FOREST}/export/nowhere/_index?recursive=true",
                headers=narrow)
            assert hidden.status_code == absent.status_code == 404
            # Byte-identical once each envelope's own id is masked out —
            # J.14's rule is about one id under two reasons, and the id
            # itself is the caller's own input.
            norm = lambda r, nid: r.content.replace(nid.encode(), b"<id>")  # noqa: E731
            assert norm(hidden, "sales/_index") == norm(absent,
                                                        "nowhere/_index")
        finally:
            client.__exit__(None, None, None)

    def test_a_leaf_and_an_unknown_parameter_refuse(
            self, root, tmp_path, monkeypatch):
        app, client, _, head = _build(tmp_path, monkeypatch, root)
        try:
            _plant(client, head, "notes/zip-one", "Zip one")
            r = client.get(
                f"/v1/forests/{FOREST}/export/notes/zip-one?recursive=true",
                headers=head)
            assert r.status_code == 400
            assert r.json()["error"]["code"] == "E_SCHEMA"
            r = client.get(
                f"/v1/forests/{FOREST}/export/notes/zip-one?recusrive=true",
                headers=head)
            assert r.status_code == 400
            assert "recusrive" in r.json()["error"]["message"]
            # And the plain export is untouched, to the byte (F.84).
            r = client.get(f"/v1/forests/{FOREST}/export/notes/zip-one",
                           headers=head)
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/markdown")
        finally:
            client.__exit__(None, None, None)


# -- F.94: the principal rides the original commit ----------------------------


def test_the_stamp_is_a_trailer_and_the_amend_never_runs(
        root, tmp_path, monkeypatch):
    import subprocess

    import monkeyllm_station.app as app_module

    def boom(*_a, **_kw):  # pragma: no cover - the point is it never runs
        raise AssertionError("the amend fallback ran with the seam present")

    monkeypatch.setattr(app_module, "stamp_principal", boom)
    app, client, _, head = _build(tmp_path, monkeypatch, root)
    try:
        _plant(client, head, "notes/stamped", "Stamped")
        message = subprocess.run(
            ["git", "-C", str(root / FOREST), "log", "-1", "--format=%B"],
            capture_output=True, text=True, check=True).stdout
        assert "station-principal: root" in message
        head_sha = subprocess.run(
            ["git", "-C", str(root / FOREST), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        r = client.post(f"/v1/forests/{FOREST}/look",
                        json={"id": "notes/stamped"}, headers=head)
        assert r.status_code == 200
    finally:
        client.__exit__(None, None, None)


def test_dry_run_reaches_the_wire_and_gates_like_the_real_call(
        root, tmp_path, monkeypatch):
    app, client, registry, head = _build(tmp_path, monkeypatch, root)
    try:
        node = {"id": "notes/wire-rehearsed", "type": "note",
                "parent": "notes/_index", "title": "Wire rehearsed",
                "summary": "The rehearsal over REST.", "body": "# X\n\nY."}
        r = client.post(f"/v1/forests/{FOREST}/plant", headers=head,
                        json={"node": node, "dry_run": True})
        assert r.status_code == 200, r.text
        assert r.json() == {"id": "notes/wire-rehearsed", "valid": True,
                            "dry_run": True}
        gone = client.post(f"/v1/forests/{FOREST}/look",
                           json={"id": "notes/wire-rehearsed"}, headers=head)
        assert gone.status_code == 404, "nothing was written"
        key = registry.issue_key("reader")
        registry.grant("reader", FOREST, {"read"})
        r = client.post(f"/v1/forests/{FOREST}/plant",
                        headers={"Authorization": f"Bearer {key}"},
                        json={"node": node, "dry_run": True})
        assert r.status_code == 403, \
            "a rehearsal a read-only key could run would be an oracle"
    finally:
        client.__exit__(None, None, None)
