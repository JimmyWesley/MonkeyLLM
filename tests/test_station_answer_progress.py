# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The progress of an answer, while it is still being answered (J.10.12, F.138).

The claim this section rests on is that an event is a **prefix of the
response** — `retrieval` is that response's own `harvest`, `hop` is its own
`hops[n]` — which is what makes the channel safe without J.16's rationing:
it discloses nothing the caller was not already about to receive. A claim of
that shape is checkable by comparison rather than by a list of allowed
fields, so that is how it is checked here, field for field, against the very
response the same call returned.

The rest is about a spectator costing nothing. `RunBoard` is exercised
directly for that, because the properties are about threads and timing: that
`publish` returns without waiting for anybody, that a buffer which fills
drops and counts instead of applying back-pressure, and that a channel for a
run that is finished — or never existed — ends rather than hangs.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
QUESTION = "what is retrieval augmented generation?"


# --------------------------------------------------------------------------
# The board itself: what it costs to be watched.
# --------------------------------------------------------------------------

def _drain(board, key):
    """Read a channel to its end, synchronously."""
    async def go():
        return [event async for event in board.stream(key)]
    return asyncio.run(go())


def test_a_channel_for_a_run_that_never_existed_closes():
    """J.10.12 rule 6. A stream that hangs on a typo is indistinguishable
    from one whose call is merely slow, and the person watching cannot tell
    which they have. Bounded, not instant: an unclaimed run may simply be a
    watcher that opened its channel before firing the call."""
    from monkeyllm_station import runs as runs_mod

    started = time.monotonic()
    assert _drain(runs_mod.RunBoard(), ("alice", FOREST, "never-claimed")) == []
    waited = time.monotonic() - started
    assert waited < runs_mod.CLAIM_GRACE_SECONDS + 2, f"waited {waited:.1f}s"


def test_a_channel_may_be_opened_before_its_call_claims_the_run():
    """The order a console must take: awaiting the POST means awaiting the
    whole answer, so the channel is opened first and the claim races it."""
    from monkeyllm_station.runs import RunBoard

    board = RunBoard()
    key = ("alice", FOREST, "early")

    async def go():
        seen = []

        def later():                     # the POST handler, a moment behind
            time.sleep(0.2)
            board.claim(key)
            board.publish(key, "retrieval", {"results": [{"id": "a"}]})
            board.finish(key)

        threading.Thread(target=later, daemon=True).start()
        async for event in board.stream(key):
            seen.append(event["event"])
        return seen

    assert asyncio.run(go()) == ["retrieval", "done"]


def test_a_finished_run_yields_what_it_has_and_closes():
    from monkeyllm_station.runs import RunBoard

    board = RunBoard()
    key = ("alice", FOREST, "r1")

    async def go():
        assert board.claim(key)
        board.publish(key, "retrieval", {"results": [{"id": "a"}]})
        board.publish(key, "hop", {"n": 1, "tool": "sniff"})
        board.finish(key)
        return [event async for event in board.stream(key)]

    events = asyncio.run(go())
    assert [e["event"] for e in events] == ["retrieval", "hop", "done"]
    assert events[1]["data"]["tool"] == "sniff"


def test_a_run_id_in_flight_cannot_be_claimed_twice():
    """J.10.12 rule 5: a run identifies ONE call while it runs."""
    from monkeyllm_station.runs import RunBoard

    board = RunBoard()
    key = ("alice", FOREST, "r1")

    async def go():
        assert board.claim(key) is True
        assert board.claim(key) is False, "a live run was claimed twice"
        board.finish(key)
        # Finished is not live: the id is free again.
        assert board.claim(key) is True

    asyncio.run(go())


def test_a_run_is_scoped_to_its_principal_and_forest():
    """The key IS the authorization, so it must not be addressable by
    anybody else — the route re-derives it from the credential rather than
    trusting the path."""
    from monkeyllm_station.runs import RunBoard

    board = RunBoard()

    async def go():
        assert board.claim(("alice", FOREST, "r1"))
        board.publish(("alice", FOREST, "r1"), "hop", {"n": 1})
        board.finish(("alice", FOREST, "r1"))
        mine = [e async for e in board.stream(("alice", FOREST, "r1"))]
        # Same id, different principal and different forest: both are other
        # runs entirely, and both are simply absent.
        theirs = [e async for e in board.stream(("bob", FOREST, "r1"))]
        elsewhere = [e async for e in board.stream(("alice", "other", "r1"))]
        return mine, theirs, elsewhere

    mine, theirs, elsewhere = asyncio.run(go())
    assert [e["event"] for e in mine] == ["hop", "done"]
    assert theirs == [] and elsewhere == []


def test_publishing_never_blocks_and_never_raises():
    """J.10.12 rule 4, the property the whole design turns on.

    `publish` is called from a forest lane in the middle of a hunt. If it
    could wait on a consumer, a walk's speed would become a function of who
    happened to be watching it — and the console's whole subject is how
    long things take.
    """
    from monkeyllm_station import runs as runs_mod

    board = runs_mod.RunBoard()
    key = ("alice", FOREST, "flood")

    async def go():
        assert board.claim(key)
        # Nobody is reading, and the buffer is deliberately overrun.
        started = time.monotonic()
        for n in range(runs_mod.MAX_EVENTS + 50):
            board.publish(key, "hop", {"n": n})
        elapsed = time.monotonic() - started
        board.finish(key)
        return elapsed, [e async for e in board.stream(key)]

    elapsed, events = asyncio.run(go())
    assert elapsed < 1.0, f"publishing into a full buffer took {elapsed:.2f}s"

    # What was dropped is COUNTED, not hidden: a gap nobody mentions reads
    # as a hunt that simply did not take those steps.
    kinds = [e["event"] for e in events]
    assert kinds[-2:] == ["dropped", "done"], kinds[-4:]
    assert events[-2]["data"]["count"] == 50
    assert kinds.count("hop") == runs_mod.MAX_EVENTS


def test_publish_reaches_the_loop_from_another_thread():
    """The writer is a forest lane and the reader is the event loop, which
    is exactly the case an asyncio primitive cannot serve — so this is the
    arrangement that must be shown to work, not assumed."""
    from monkeyllm_station.runs import RunBoard

    board = RunBoard()
    key = ("alice", FOREST, "threaded")

    async def go():
        assert board.claim(key)
        seen = []

        def lane():                      # stands in for a reader lane
            time.sleep(0.05)
            board.publish(key, "hop", {"n": 1, "tool": "pick"})
            board.finish(key)

        threading.Thread(target=lane, daemon=True).start()
        async for event in board.stream(key):
            seen.append(event["event"])
        return seen

    assert asyncio.run(go()) == ["hop", "done"]


def test_a_publish_after_the_close_is_ignored():
    """Nothing outlives its call (rule 6): a late hop from a hunt whose
    channel already closed must not reopen it."""
    from monkeyllm_station.runs import RunBoard

    board = RunBoard()
    key = ("alice", FOREST, "late")

    async def go():
        assert board.claim(key)
        board.finish(key)
        board.publish(key, "hop", {"n": 99})
        return [e async for e in board.stream(key)]

    assert [e["event"] for e in asyncio.run(go())] == ["done"]


# --------------------------------------------------------------------------
# The channel against a real Station: an event IS a prefix of the response.
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def progress_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("progress-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(progress_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    def fake(binding, **_kw):
        def chat(_messages):
            return "stub answer"
        return chat, binding.get("model", "stub-model")

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    # A stored answer serves without re-running the model; these tests are
    # about what a LIVE call publishes, so each starts with an empty store.
    shutil.rmtree(progress_root / FOREST / "_derived" / "cache", ignore_errors=True)

    app = build_app(root=progress_root, registry_path=tmp_path / "station.db",
                    mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"admin", "read", "query", "write"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, {"Authorization": f"Bearer {key}"}


def _events(client, head, run):
    """Read a finished run's channel to its end (rule 6 makes this safe)."""
    out = []
    with client.stream("GET", f"/v1/forests/{FOREST}/answer/{run}/events",
                       headers=head) as r:
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/event-stream")
        kind = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                import json as _json
                out.append({"event": kind, "data": _json.loads(line[6:])})
    return out


def test_a_run_changes_nothing_about_the_response(station):
    """J.10.12 rule 1: the response to a call with `run` is byte-identical
    to the response without it."""
    client, head = station
    plain = client.post(f"/v1/forests/{FOREST}/answer",
                        json={"question": QUESTION, "cache": False}, headers=head)
    watched = client.post(f"/v1/forests/{FOREST}/answer",
                          json={"question": QUESTION, "cache": False,
                                "run": "run-1"}, headers=head)
    assert plain.status_code == watched.status_code == 200, watched.text
    a, b = plain.json(), watched.json()
    # The two calls are two calls, so their clocks differ; everything that
    # describes the ANSWER must not. `model_ms` belongs here for the same
    # reason `trace` does — it is how long a provider took, not what it
    # said — and it is here because it caught this test being imprecise
    # rather than the channel being wrong.
    for volatile in ("ms", "model_ms", "trace", "timing", "cost", "usage"):
        a.pop(volatile, None)
        b.pop(volatile, None)
    assert a == b
    assert "run" not in b, "the rendezvous must not ride the response"


def test_the_retrieval_event_is_the_response_harvest(station):
    """F.138, the load-bearing comparison: not 'the event has sensible
    fields' but 'the event IS what the response carried'."""
    client, head = station
    r = client.post(f"/v1/forests/{FOREST}/answer",
                    json={"question": QUESTION, "cache": False, "run": "run-2"},
                    headers=head)
    assert r.status_code == 200, r.text
    events = _events(client, head, "run-2")

    kinds = [e["event"] for e in events]
    assert kinds[0] == "retrieval" and kinds[-1] == "done", kinds
    harvest = r.json()["harvest"]
    # Guards the guard: two empty dicts compare equal, and this comparison
    # is the whole criterion.
    assert harvest.get("results"), "the fixture answered nothing to compare"
    assert events[0]["data"] == harvest


def test_every_hop_event_is_the_response_hop(station, monkeypatch):
    """The walk's half of F.138, extended by F.140 (v0.67). A hop is
    published the moment it happens and the response carries the same record
    at the end, so the two must agree field for field — `ids` included, which
    is compared here rather than asserted separately, because the equality is
    the criterion and a second assertion would only restate it.
    """
    from monkeyllm_station import inference

    def scripted(binding, **_kw):
        script = iter([
            '{"tool": "locate", "args": {"query": "retrieval", "k": 3}}',
            '{"tool": "look", "args": {"id": "concepts/rag"}}',
            '{"tool": "pick", "args": {"id": "concepts/rag"}}',
            '{"tool": "answer", "args": {"text": "walked", '
            '"answer_nodes": ["concepts/rag"]}}',
        ])

        def chat(_messages):
            return next(script)
        return chat, "scripted-model"

    monkeypatch.setattr(inference, "chat_from_binding", scripted)
    client, head = station

    r = client.post(f"/v1/forests/{FOREST}/answer",
                    json={"question": QUESTION, "hops": 3, "cache": False,
                          "run": "run-3"}, headers=head)
    assert r.status_code == 200, r.text
    hops = r.json()["hops"]
    assert len(hops) == 3, hops
    # Guards the guard: a `locate` that named nothing would make the
    # comparison below true without ever comparing the new field.
    assert hops[0]["tool"] == "locate" and hops[0]["ids"], hops[0]

    streamed = [e["data"] for e in _events(client, head, "run-3")
                if e["event"] == "hop"]
    assert streamed == hops, "a hop event diverged from the response's own record"


def test_an_unknown_run_closes_instead_of_hanging(station):
    """Rule 6 over the wire, and the reason it matters: a hang and a slow
    hunt look the same to whoever is waiting."""
    client, head = station
    started = time.monotonic()
    assert _events(client, head, "never-asked") == []
    assert time.monotonic() - started < 5.0


def test_the_channel_is_scoped_like_every_other_route(station):
    client, head = station
    r = client.get(f"/v1/forests/{FOREST}/answer/x/events")
    assert r.status_code == 401, r.text
    missing = client.get("/v1/forests/no-such-forest/answer/x/events", headers=head)
    assert missing.status_code == 404, missing.text


def test_a_second_call_on_a_live_run_is_refused(station):
    """Rule 5 over the wire. The refusal names the rule rather than the
    forest: a run id is the caller's own string and collides with nothing
    but their own call."""
    client, head = station
    from monkeyllm_station.runs import RunBoard  # noqa: F401  (documents the type)

    board = client.app.state.runs
    key = ("root", FOREST, "held")
    held = threading.Event()

    async def hold():
        board.claim(key)
        held.set()

    asyncio.run(hold())
    r = client.post(f"/v1/forests/{FOREST}/answer",
                    json={"question": QUESTION, "run": "held"}, headers=head)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "E_SCHEMA"
    board.finish(key)
