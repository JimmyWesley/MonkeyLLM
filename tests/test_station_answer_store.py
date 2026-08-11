# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The answer already given (spec v0.33, J.10.7 — F.37).

The provider round trip is the only expensive line in the product, and a
deployment in front of traffic is asked the same questions all day. The
store makes the second ask free — without ever serving a stale answer (the
forest's HEAD is in the key), without ever crossing a scope (the scope is
in the key), and without ever lying about it (`cached: true`, a `cache`
clock, an audit row marked as served from the store, and heat still
deposited on the trail the answer was built from).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
QUESTION = "architecture notes"
OTHER_QUESTION = "sales report q1 2026 revenue"


@pytest.fixture(scope="session")
def store_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("store-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(store_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    # Every provider round trip is counted, and every reply is numbered —
    # so a served entry is provably the answer that was bought, not a fresh
    # draw that happens to match.
    calls: list = []

    def fake(binding, **_kw):
        def chat(messages):
            calls.append(messages)
            return f"stub answer #{len(calls)}"
        return chat, binding.get("model", "stub-model")

    monkeypatch.setattr(inference, "chat_from_binding", fake)

    # The store lives in the forest's own `_derived/`, which is
    # session-scoped here; each test starts with an empty store so no test
    # is served another test's entries.
    shutil.rmtree(store_root / FOREST / "_derived" / "cache", ignore_errors=True)

    app = build_app(root=store_root, registry_path=tmp_path / "station.db", mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"admin", "read", "query", "write"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, registry, app.state.pool, calls, \
            {"Authorization": f"Bearer {key}"}


def _ask(client, head, question=QUESTION, **body):
    r = client.post(f"/v1/forests/{FOREST}/answer",
                    json={"question": question, **body}, headers=head)
    assert r.status_code == 200, r.text
    return r


def _clock_names(response) -> set:
    raw = response.headers.get("Server-Timing", "")
    return {part.strip().partition(";")[0] for part in raw.split(",") if part.strip()}


# -- the hit ----------------------------------------------------------------


def test_the_second_ask_makes_one_provider_call(station):
    """F.37's headline: same question, unchanged forest — one round trip.
    The second response is the original run's answer, says it was served
    from the store, and its header carries `cache` and no `model`."""
    client, _, _, calls, head = station

    first = _ask(client, head)
    assert len(calls) == 1
    assert "cached" not in first.json()
    assert {"vine", "model", "cache", "host"} <= _clock_names(first)

    second = _ask(client, head)
    assert len(calls) == 1, "the store must answer, not the provider"
    body = second.json()
    assert body["cached"] is True
    assert body["cached_at"]
    assert body["answer"] == first.json()["answer"]
    clocks = _clock_names(second)
    assert "cache" in clocks
    assert "model" not in clocks, "no provider ran, so no header may claim one"


def test_a_hit_serves_the_record_over_a_live_reading(station):
    """v0.35: the model fields are the record; the retrieval fields are this
    call's own. Same reading, so same evidence — but the trace is fresh and
    no step in it may claim a provider ran."""
    client, _, _, _, head = station
    first = _ask(client, head).json()
    second = _ask(client, head).json()
    assert second["answer"] == first["answer"]
    assert second["model"] == first["model"]
    assert second["evidence"] == first["evidence"]
    steps = [s["step"] for s in second["trace"]["steps"]]
    assert steps, "the sweep's own trace, freshly recorded"
    assert "model" not in steps, "no provider ran, so no step may claim one"


def test_the_hit_is_audited_as_one(station):
    """J.4: the row is marked as served from the store and carries the
    entry's key digest, so a served answer still reconstructs."""
    client, _, _, _, head = station
    _ask(client, head)
    _ask(client, head)
    entries = client.get("/v1/admin/audit", headers=head).json()["entries"]
    served = [e for e in entries
              if e["primitive"] == "answer" and e["result"] == "cache"]
    assert len(served) == 1
    assert "cache_key" in served[0]["args"]


# -- the invalidation -------------------------------------------------------


def test_a_foreign_write_invalidates_nothing(station):
    """v0.35's point: HEAD left the sweep's key. A `plant` in material the
    question never reads leaves the reading unchanged — still one provider
    call, still served."""
    client, _, _, calls, head = station
    first = _ask(client, head)
    # Foreign means foreign to the READING: planting under a branch whose
    # index the question retrieves would edit that index's body, which is a
    # legitimate change of reading. `concepts/` is not in this evidence.
    assert not any(e.startswith("concepts/") for e in first.json()["evidence"])
    r = client.post(
        f"/v1/forests/{FOREST}/plant",
        json={"node": {"id": "concepts/f37-watering", "parent": "concepts/_index",
                       "type": "concept", "title": "Watering schedule",
                       "summary": "Weekly watering rota for the greenhouse "
                                  "shelves; unrelated to any architecture."}},
        headers=head)
    assert r.status_code == 200, r.text
    second = _ask(client, head)
    assert len(calls) == 1, "a foreign write must not empty the store"
    assert second.json()["cached"] is True


def test_an_edit_in_the_reading_is_a_miss(station):
    """A `graft` on a node the question reads changes the reading — there
    may be new information, so the model runs and the entry is replaced."""
    client, _, _, calls, head = station
    first = _ask(client, head)
    node = first.json()["evidence"][0]
    r = client.post(
        f"/v1/forests/{FOREST}/graft",
        json={"id": node,
              "patch": {"set_frontmatter": {
                  "summary": "MixerLLM architecture notes, edited so the "
                             "reading under the store changes."}}},
        headers=head)
    assert r.status_code == 200, r.text
    second = _ask(client, head)
    assert len(calls) == 2
    assert "cached" not in second.json()
    third = _ask(client, head)
    assert len(calls) == 2, "the fresh run replaced the entry"
    assert third.json()["cached"] is True


def test_the_key_is_the_closed_list(station):
    """A change to `k` or to the question is a different key; a change of
    spelling (case, whitespace) is not — normalisation is for writing."""
    client, _, _, calls, head = station
    _ask(client, head, k=3)
    _ask(client, head, k=2)
    assert len(calls) == 2, "k is on the list"
    _ask(client, head, question=f"  {QUESTION.upper()}  ", k=3)
    assert len(calls) == 2, "case and whitespace are not"
    _ask(client, head, question=OTHER_QUESTION)
    assert len(calls) == 3, "another question is another key"


def test_the_key_holds_the_effective_k(station, monkeypatch):
    """F.38's host half: the C.6c cap shapes the sweep's answer, so the
    capped value is what names it. Two asks past the cap are one call —
    and a cap changed between them is a clean miss, never a five-banana
    answer served under a seven-banana promise."""
    client, _, _, calls, head = station
    # Cap 3 rather than the default 5: the whisper of the first ask nudges
    # heat, and on this small forest the top-5 boundary is a near-tie that
    # can honestly reshuffle the SET (a real change of reading, v0.35). The
    # top-3 is stable, and the property under test is the key, not the tie.
    monkeypatch.setenv("MONKEYLLM_HARVEST_MAX_K", "3")

    _ask(client, head, k=10)
    second = _ask(client, head, k=50)
    assert len(calls) == 1, "both clamp to 3, so both name one entry"
    assert second.json()["cached"] is True

    monkeypatch.setenv("MONKEYLLM_HARVEST_MAX_K", "2")
    third = _ask(client, head, k=10)
    assert len(calls) == 2, "a changed cap is a different effective k"
    assert "cached" not in third.json()


# -- the scope --------------------------------------------------------------


def test_an_entry_never_crosses_scopes(station):
    """The scope is in the key: a principal narrowed to a branch is never
    served the whole-forest entry, however equal the question."""
    client, registry, _, calls, head = station
    _ask(client, head)
    assert len(calls) == 1

    narrow_key = registry.issue_key("narrow")
    registry.grant("narrow", FOREST, {"read", "query"}, allow=["notes/"])
    narrow = {"Authorization": f"Bearer {narrow_key}"}
    r = _ask(client, narrow)
    assert len(calls) == 2, "a narrowed scope must buy its own run"
    assert "cached" not in r.json()


def test_an_entry_is_shared_inside_one_scope(station):
    """Two principals under one scope are asking one forest: the second is
    served the first's entry. Capabilities are not retrieval — only the
    scope is."""
    client, registry, _, calls, head = station
    _ask(client, head)
    twin_key = registry.issue_key("twin")
    registry.grant("twin", FOREST, {"read", "query"})
    twin = {"Authorization": f"Bearer {twin_key}"}
    r = _ask(client, twin)
    assert len(calls) == 1
    assert r.json()["cached"] is True


# -- what never enters ------------------------------------------------------


def test_nothing_empty_enters_the_store(station):
    """A run whose retrieval found nothing is never stored: the empty
    answer must not become the fastest response the product gives."""
    client, _, _, calls, head = station
    gibberish = "qqzzwxyz flurble grommet nonexistent"
    _ask(client, head, question=gibberish)
    r = _ask(client, head, question=gibberish)
    assert len(calls) == 2
    assert "cached" not in r.json()


# -- the bypass -------------------------------------------------------------


def test_cache_false_bypasses_and_refreshes(station):
    """One flag: the read is skipped, the model runs, and the fresh run
    replaces the entry its key names."""
    client, _, _, calls, head = station
    first = _ask(client, head)
    assert first.json()["answer"] == "stub answer #1"

    fresh = _ask(client, head, cache=False)
    assert len(calls) == 2
    assert "cached" not in fresh.json()
    assert fresh.json()["answer"] == "stub answer #2"

    served = _ask(client, head)
    assert len(calls) == 2
    assert served.json()["cached"] is True
    assert served.json()["answer"] == "stub answer #2", \
        "the bypass must have replaced the entry"


# -- the forest is still used -----------------------------------------------


def test_a_hit_runs_the_retrieval_and_the_whisper_closes_both(station):
    """v0.35: a sweep hit is a live retrieval with only the bill skipped —
    the tracer gains this call's own events — and the whisper of Part D
    lands on the evidence for hit and miss alike, so the Ranger reads the
    deployment's questions as the heat they are."""
    client, _, pool, calls, head = station
    first = _ask(client, head, question=OTHER_QUESTION).json()

    def heat_of(nid):
        body = client.get(f"/v1/forests/{FOREST}/trails", headers=head).json()
        return {row["id"]: row["heat"] for row in body["heat"]}.get(nid, 0.0)

    # Heat saturates at 1.0, so the rise is asserted on an evidence node
    # with headroom — index nodes answer most questions and run hot.
    node = next((i for i in first["evidence"] if heat_of(i) <= 0.8),
                first["evidence"][0])
    heat_after_miss = heat_of(node)
    assert heat_after_miss > 0, "a bought answer whispers too"
    events_before = len(pool.get(FOREST).tracer.events)

    second = _ask(client, head, question=OTHER_QUESTION)
    assert second.json()["cached"] is True and len(calls) == 1
    assert len(pool.get(FOREST).tracer.events) > events_before, \
        "the hit's sweep really ran"
    assert heat_of(node) > heat_after_miss, \
        "a served answer whispers exactly like a bought one"


# -- the operator's surface -------------------------------------------------


def test_the_bound_evicts_oldest_served_first(station):
    client, _, _, calls, head = station
    r = client.post("/v1/admin/cache",
                    json={"forest": FOREST, "max_entries": 2}, headers=head)
    assert r.status_code == 200, r.text

    _ask(client, head, question=QUESTION)          # call 1
    _ask(client, head, question=OTHER_QUESTION)    # call 2
    _ask(client, head, question="jimmy wesley")    # call 3, evicts QUESTION

    stats = client.get(f"/v1/admin/cache?forest={FOREST}",
                       headers=head).json()["stats"]
    assert stats["held"] == 2

    _ask(client, head, question="jimmy wesley")    # still held
    assert len(calls) == 3
    _ask(client, head, question=QUESTION)          # evicted: bought again
    assert len(calls) == 4


def test_the_economy_is_stated_and_money_is_never_invented(station):
    """Hits and misses are counted; the money not spent appears only when
    priced runs were avoided — an unpriced saving is unpriced, never
    $0.00."""
    client, _, _, _, head = station
    _ask(client, head)
    _ask(client, head)
    body = client.get(f"/v1/admin/cache?forest={FOREST}", headers=head).json()
    assert body["settings"]["enabled"] is True
    stats = body["stats"]
    assert stats["held"] == 1 and stats["hits"] == 1 and stats["misses"] == 1
    assert "avoided_usd" not in stats


def test_clearing_costs_money_never_truth(station):
    client, _, _, calls, head = station
    _ask(client, head)
    r = client.post("/v1/admin/cache",
                    json={"forest": FOREST, "clear": True}, headers=head)
    assert r.json()["cleared"] == 1 and r.json()["stats"]["held"] == 0
    _ask(client, head)
    assert len(calls) == 2, "a cleared entry is simply bought again"


def test_a_disabled_store_is_not_consulted(station):
    client, _, _, calls, head = station
    r = client.post("/v1/admin/cache",
                    json={"forest": FOREST, "enabled": False}, headers=head)
    assert r.status_code == 200
    first = _ask(client, head)
    second = _ask(client, head)
    assert len(calls) == 2
    assert "cached" not in second.json()
    assert "cache" not in _clock_names(first) | _clock_names(second)


def test_a_walk_answer_stays_pinned_to_head(station, monkeypatch):
    """F.37's walk clause: a forager's path cannot be re-walked without
    paying the model per hop, so walk entries keep HEAD in their key and
    ANY commit — related to the question or not — invalidates them."""
    from monkeyllm_station import inference

    turns = []

    def scripted(binding, **_kw):
        script = iter([
            '{"tool": "look", "args": {"id": "concepts/rag"}}',
            '{"tool": "answer", "args": {"text": "walked answer", '
            '"answer_nodes": ["concepts/rag"]}}',
        ])

        def chat(messages):
            turns.append(messages)
            return next(script)
        return chat, "scripted-model"

    monkeypatch.setattr(inference, "chat_from_binding", scripted)
    client, _, _, _, head = station

    first = _ask(client, head, hops=2)
    assert first.json()["answer"] == "walked answer"
    assert len(turns) == 2

    second = _ask(client, head, hops=2)
    assert len(turns) == 2, "a walk hit pays no model turn"
    assert second.json()["cached"] is True

    r = client.post(
        f"/v1/forests/{FOREST}/plant",
        json={"node": {"id": "notes/f37-walk-bust", "parent": "notes/_index",
                       "type": "note", "title": "Walk bust",
                       "summary": "Planted only to move HEAD: any commit "
                                  "unpins a stored walk."}},
        headers=head)
    assert r.status_code == 200, r.text
    third = _ask(client, head, hops=2)
    assert len(turns) == 4, "the walk is bought again on a moved HEAD"
    assert "cached" not in third.json()


def test_the_admin_surface_needs_admin_on_that_forest(station):
    client, registry, _, _, _ = station
    reader_key = registry.issue_key("reader")
    registry.grant("reader", FOREST, {"read"})
    reader = {"Authorization": f"Bearer {reader_key}"}
    assert client.get(f"/v1/admin/cache?forest={FOREST}",
                      headers=reader).status_code == 403
    assert client.post("/v1/admin/cache",
                       json={"forest": FOREST, "enabled": False},
                       headers=reader).status_code == 403
