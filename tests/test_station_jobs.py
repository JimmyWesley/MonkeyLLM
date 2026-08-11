# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Ingest jobs (spec J.9 / G.10, criterion F.36).

A batch is not a request: adopt/sync/upload answer 202 with a job, the
work advances one document per step on the forest's own lane, and watching
the job never touches the forest. These tests slow the batch down with an
`on_curate` hook — the seam G.4.3 already offers — so the in-flight states
are observable without patching any internals.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"


def _station(tmp_path, *, writable=True):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "registry"
    if not root.exists():
        root.mkdir()
        build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db",
                    writable=writable, mcp=False)
    return TestClient(app), app.state.registry, root


@pytest.fixture()
def station(tmp_path):
    client, registry, root = _station(tmp_path)
    with client:
        yield client, registry, root


def _key(registry, caps, principal="alice", allow=None, forest=FOREST):
    key = registry.issue_key(principal)
    registry.grant(principal, forest, set(caps), allow=allow)
    return {"Authorization": f"Bearer {key}"}


def _docs(n, prefix="doc"):
    return [{"name": f"{prefix}-{i}.md",
             "text": f"# {prefix.title()} {i}\n\nFact number {i}.\n"}
            for i in range(n)]


def _slow_hook(monkeypatch, seconds):
    """Every document's step takes at least `seconds`: the hook runs inside
    the G.10 step (curation is part of a step by design), so a batch of N
    holds the lane for at most one document at a time, N times."""

    def naps(draft):
        time.sleep(seconds)
        return draft

    monkeypatch.setattr("monkeyllm.gardener.discover_hooks", lambda: [naps])


def _poll(client, head, job_id, *, until=("done", "error", "cancelled"),
          timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/v1/forests/{FOREST}/jobs/{job_id}", headers=head)
        assert r.status_code == 200, r.text
        job = r.json()["job"]
        if job["state"] in until:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached {until}")


# -- the job ------------------------------------------------------------------


def test_a_batch_answers_202_with_a_job_before_it_finishes(station, monkeypatch):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    _slow_hook(monkeypatch, 0.15)

    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": _docs(5), "dest": "uploads"},
                    headers=head)
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["state"] == "running" and job["total"] == 5
    assert job["id"].startswith("ing-")

    done = _poll(client, head, job["id"])
    assert done["state"] == "done" and done["done"] == done["total"] == 5
    # The report is the v0.31 body, unabridged (J.8 rule kept).
    report = done["report"]
    assert len(report["planted"]) == 5 and report["errors"] == []
    assert report["commit"] and report["commit"] != report["commit_before"]
    assert report["mode"] == "upload" and report["curated"] is False


def test_wait_true_returns_the_finished_job_in_one_response(station):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": _docs(2), "dest": "uploads",
                          "wait": True},
                    headers=head)
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["state"] == "done" and len(job["report"]["planted"]) == 2


def test_refusal_is_still_synchronous_and_leaves_no_job(station):
    """A 202 for a request that was always going to fail validation would
    teach the caller to distrust 202 (J.9)."""
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": []}, headers=head)
    assert r.status_code == 400
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload",
                          "files": [{"name": "../out.md", "text": "x"}]},
                    headers=head)
    assert r.status_code == 400
    listed = client.get(f"/v1/forests/{FOREST}/jobs", headers=head).json()
    assert listed["jobs"] == [], "a refused batch must not leave a job record"


def test_a_second_batch_is_refused_naming_the_running_job(station, monkeypatch):
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    _slow_hook(monkeypatch, 0.2)

    first = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "upload", "files": _docs(5),
                              "dest": "uploads"},
                        headers=head)
    assert first.status_code == 202
    running_id = first.json()["job"]["id"]

    second = client.post(f"/v1/forests/{FOREST}/ingest",
                         json={"mode": "upload", "files": _docs(2, "other"),
                               "dest": "uploads"},
                         headers=head)
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "E_LOCKED"
    assert running_id in second.json()["error"]["message"]

    _poll(client, head, running_id)
    # The lane is free again: the next batch is accepted.
    third = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "upload", "files": _docs(2, "later"),
                              "dest": "uploads", "wait": True},
                        headers=head)
    assert third.status_code == 200 and third.json()["job"]["state"] == "done"


# -- isolation and fairness ---------------------------------------------------


def test_a_read_on_the_same_forest_lands_between_steps(station, monkeypatch):
    """F.36 fairness: a `look` mid-batch is answered within one document's
    work, not the folder's — under the v0.31 single worker it would have
    queued behind the whole batch, and the job could never still be running
    when it returned."""
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    _slow_hook(monkeypatch, 0.3)

    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": _docs(8), "dest": "uploads"},
                    headers=head)
    assert r.status_code == 202
    job_id = r.json()["job"]["id"]

    look = client.post(f"/v1/forests/{FOREST}/look", json={"id": "_index"},
                       headers=head)
    assert look.status_code == 200 and look.json()["id"] == "_index"
    still = client.get(f"/v1/forests/{FOREST}/jobs/{job_id}", headers=head)
    assert still.json()["job"]["state"] == "running", \
        "the read must not have waited for the batch"
    _poll(client, head, job_id)


def test_a_read_on_another_forest_never_waits(station, monkeypatch):
    """F.36 isolation: one forest's batch is not another forest's problem
    (J.9) — each forest has its own lane."""
    client, registry, _ = station
    admin = _key(registry, ["admin", "read", "ingest"])
    assert client.post("/v1/admin/forests",
                       json={"id": "beta", "title": "Beta"},
                       headers=admin).status_code == 200

    _slow_hook(monkeypatch, 0.3)
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": _docs(8), "dest": "uploads"},
                    headers=admin)
    assert r.status_code == 202
    job_id = r.json()["job"]["id"]

    other = client.post("/v1/forests/beta/look", json={"id": "_index"},
                        headers=admin)
    assert other.status_code == 200
    still = client.get(f"/v1/forests/{FOREST}/jobs/{job_id}", headers=admin)
    assert still.json()["job"]["state"] == "running", \
        "the other forest's read must not have waited for this batch"
    _poll(client, admin, job_id)


# -- watching is free ---------------------------------------------------------


def test_polling_a_job_touches_no_forest(station):
    """No trace event, no pheromone (J.9): a job is a host record, and the
    poll that queued behind the work it reports would be the old deadlock
    one level up."""
    client, registry, _ = station
    head = _key(registry, ["read", "ingest"])
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "upload", "files": _docs(2), "dest": "uploads",
                          "wait": True},
                    headers=head)
    job_id = r.json()["job"]["id"]

    state = client.app.state
    before = state.forest_lane(FOREST).submit(
        lambda: (len(state.pool.get(FOREST).tracer.events),
                 dict(state.pool.get(FOREST).trails.heat_all()))).result()
    for _ in range(3):
        assert client.get(f"/v1/forests/{FOREST}/jobs", headers=head).status_code == 200
        assert client.get(f"/v1/forests/{FOREST}/jobs/{job_id}",
                          headers=head).status_code == 200
    after = state.forest_lane(FOREST).submit(
        lambda: (len(state.pool.get(FOREST).tracer.events),
                 dict(state.pool.get(FOREST).trails.heat_all()))).result()
    assert after == before


def test_watching_requires_the_ingest_capability(station):
    client, registry, _ = station
    reader = _key(registry, ["read"], principal="bob")
    assert client.get(f"/v1/forests/{FOREST}/jobs",
                      headers=reader).status_code == 403


# -- cancel, and the recovery that is just `sync` -----------------------------


@pytest.fixture()
def ingest_station(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setenv("MONKEYLLM_INGEST_ROOTS", str(inbox))
    client, registry, root = _station(tmp_path)
    with client:
        yield client, registry, root, inbox


def test_cancel_stops_at_a_step_boundary_and_sync_finishes_the_rest(
        ingest_station, monkeypatch):
    """F.36: a cancel after k steps leaves exactly k documents planted and
    committed, and a later `sync` completes the remainder without
    duplicating any — which requires, and thereby tests, that the source
    root was recorded before the first step (G.10)."""
    client, registry, _, inbox = ingest_station
    src = inbox / "handbook"
    src.mkdir()
    total = 6
    for i in range(total):
        (src / f"page-{i}.md").write_text(f"# Page {i}\n\nBody {i}.\n",
                                          encoding="utf-8")

    head = _key(registry, ["read", "ingest", "admin"])
    _slow_hook(monkeypatch, 0.3)
    r = client.post(f"/v1/forests/{FOREST}/ingest",
                    json={"mode": "adopt", "path": str(src), "dest": "handbook"},
                    headers=head)
    assert r.status_code == 202, r.text
    job_id = r.json()["job"]["id"]

    # Let at least one step land, then ask it to stop.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/v1/forests/{FOREST}/jobs/{job_id}",
                         headers=head).json()["job"]
        if job["done"] >= 1:
            break
        time.sleep(0.02)
    assert client.post(f"/v1/forests/{FOREST}/jobs/{job_id}/cancel",
                       headers=head).status_code == 200

    job = _poll(client, head, job_id)
    assert job["state"] == "cancelled"
    planted = job["report"]["planted"]
    assert 1 <= len(planted) < total, planted
    assert job["report"]["commit"], "the steps taken are commits and stand"

    # The recovery is sync, not archaeology (J.9): the remainder lands,
    # nothing is planted twice.
    monkeypatch.setattr("monkeyllm.gardener.discover_hooks", lambda: [])
    done = client.post(f"/v1/forests/{FOREST}/ingest",
                       json={"mode": "sync", "wait": True}, headers=head)
    assert done.status_code == 200, done.text
    report = done.json()["job"]["report"]
    assert len(report["planted"]) == total - len(planted)
    assert sorted(report["unchanged"]) == sorted(planted)
    assert not set(report["planted"]) & set(planted)


# -- the records are process state, the work is commits -----------------------


def test_a_restart_forgets_the_record_and_keeps_the_work(tmp_path):
    client, registry, root = _station(tmp_path)
    with client:
        head = _key(registry, ["read", "ingest", "admin"])
        r = client.post(f"/v1/forests/{FOREST}/ingest",
                        json={"mode": "upload", "files": _docs(2),
                              "dest": "uploads", "wait": True},
                        headers=head)
        assert r.status_code == 200
        job = r.json()["job"]
        planted = job["report"]["planted"]

    # A fresh Station on the same registry: same forests, same keys.
    client2, _, _ = _station(tmp_path)
    with client2:
        gone = client2.get(f"/v1/forests/{FOREST}/jobs/{job['id']}", headers=head)
        assert gone.status_code == 404
        assert gone.json()["error"]["code"] == "E_NOT_FOUND"
        # The work survived: the nodes answer, and so does the audit row.
        look = client2.post(f"/v1/forests/{FOREST}/look",
                            json={"id": planted[0]}, headers=head)
        assert look.status_code == 200
        entries = client2.get("/v1/admin/audit", headers=head).json()["entries"]
        assert any(e["primitive"] == "ingest" and e["result"] == "ok"
                   for e in entries)
