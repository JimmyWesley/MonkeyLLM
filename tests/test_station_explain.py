# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Explaining a composite (spec J.10.4) and the entry-search switch (K.3).

Two things an operator cannot get from a total: *which* call was slow, and
whether the dense layer helped or hurt on **their** corpus. Both are here
because both are claims the project makes in public and must be checkable
from the console rather than taken on trust.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
QUESTION = "architecture notes"


@pytest.fixture(scope="session")
def explain_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("explain-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(explain_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    def fake(binding, **_kw):
        return (lambda messages: "stub answer"), binding.get("model", "stub")

    monkeypatch.setattr(inference, "chat_from_binding", fake)

    app = build_app(root=explain_root, registry_path=tmp_path / "station.db", mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"admin", "read", "query"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, app.state.pool, {"Authorization": f"Bearer {key}"}


def _call(client, head, primitive, **body):
    r = client.post(f"/v1/forests/{FOREST}/{primitive}", json=body, headers=head)
    assert r.status_code == 200, r.text
    return r.json()


# -- what the trace says ----------------------------------------------------


def test_answer_reports_the_calls_it_made(station):
    client, _, head = station
    trace = _call(client, head, "answer", question=QUESTION)["trace"]

    steps = [s["step"] for s in trace["steps"]]
    # The composite IS these calls: entry search, then the provider.
    assert "locate" in steps and "sniff" in steps
    assert steps[-1] == "model"
    assert all(isinstance(s["ms"], (int, float)) for s in trace["steps"])


def test_the_two_halves_are_reported_apart(station):
    """The whole point: a slow answer is almost never the forest, and one
    number cannot say so."""
    client, _, head = station
    trace = _call(client, head, "answer", question=QUESTION)["trace"]

    model = next(s for s in trace["steps"] if s["step"] == "model")
    forest = sum(s["ms"] for s in trace["steps"] if s["step"] != "model")
    assert trace["retrieval_ms"] == pytest.approx(forest, abs=0.2)
    assert trace["total_ms"] == pytest.approx(forest + model["ms"], abs=0.2)


def test_harvest_is_explained_too_and_a_plain_primitive_is_not(station):
    """`harvest` is several calls; `locate` is one, and its caller already
    knows how long its own request took."""
    client, _, head = station
    assert "trace" in _call(client, head, "harvest", query=QUESTION)
    assert "trace" not in _call(client, head, "locate", query=QUESTION)


def test_a_trace_carries_shape_not_content(station):
    """A step names what ran and what it cost. If the query itself could
    ride along, a trace would be a second, unscoped response channel."""
    client, _, head = station
    trace = _call(client, head, "answer", question=QUESTION)["trace"]
    for step in trace["steps"]:
        assert set(step) <= {"step", "ms", "tokens", "id", "detail"}
        assert QUESTION not in str(step.get("id") or "")


def test_each_call_is_explained_on_its_own(station):
    """The tracer accumulates for the life of the session; a request must
    report what IT did, not everything the forest has ever done."""
    client, _, head = station
    first = _call(client, head, "answer", question=QUESTION)["trace"]
    second = _call(client, head, "answer", question=QUESTION)["trace"]
    assert len(second["steps"]) == len(first["steps"])


def test_a_failed_call_is_not_dressed_up_as_a_trace(station):
    client, _, head = station
    r = client.post(f"/v1/forests/{FOREST}/harvest", json={"query": ""}, headers=head)
    body = r.json()
    assert "trace" not in body or "error" not in body


# -- answering about a dataset without its rows -----------------------------


def test_a_dataset_in_the_bundle_is_flagged_as_not_readable_from_prose(
        explain_root, tmp_path, monkeypatch):
    """The sweep cannot run SQL, so an aggregate question is answered from
    whatever prose is nearest — which is how "what was Q1 revenue?" came back
    as a *target* note's rounded figure, cited, while the ledger said 15x
    more. The model has to be told the rows are not in front of it."""
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    seen = {}

    def fake(binding, **_kw):
        def chat(messages):
            seen["prompt"] = messages[-1]["content"]
            return "stub"
        return chat, "stub-model"

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    app = build_app(root=explain_root, registry_path=tmp_path / "ds.db", mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"read", "query"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    head = {"Authorization": f"Bearer {key}"}

    with TestClient(app) as client:
        _call(client, head, "answer", question="sales report q1 2026 revenue", k=6)
        assert "ABOUT THE DATASETS ABOVE" in seen["prompt"]
        assert "sales/report-q1-2026" in seen["prompt"]

        # And no caveat where there is no dataset — a warning that is always
        # on is a warning nobody reads.
        _call(client, head, "answer", question="who wrote the architecture notes", k=2)
        assert "ABOUT THE DATASETS ABOVE" not in seen["prompt"]


# -- what it cost -----------------------------------------------------------


def test_an_unpriced_provider_reports_unknown_not_free(station):
    """A local Ollama publishes no rate. Reporting $0.00 would be a claim
    about money, made from silence."""
    client, _, head = station
    out = _call(client, head, "answer", question=QUESTION)
    assert out.get("cost") is None or out["cost"]["priced"] is False


def test_cost_uses_the_providers_own_meter_and_its_own_rates(
        explain_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    def fake_chat(binding, **_kw):
        def chat(messages):
            chat.usage["prompt"] += 1000
            chat.usage["completion"] += 200
            chat.usage["calls"] += 1
            return "stub"
        chat.usage = {"prompt": 0, "completion": 0, "calls": 0}
        return chat, binding.get("model")

    monkeypatch.setattr(inference, "chat_from_binding", fake_chat)
    monkeypatch.setattr(inference, "probe", lambda *_a, **_k: {
        "ok": True, "models": [{"id": "priced-model", "prompt": 1e-6,
                                "completion": 2e-6}]})

    app = build_app(root=explain_root, registry_path=tmp_path / "cost.db", mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"read"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "priced-model")

    with TestClient(app) as client:
        cost = _call(client, {"Authorization": f"Bearer {key}"},
                     "answer", question=QUESTION)["cost"]
    assert cost["priced"] is True
    assert cost["prompt_tokens"] == 1000 and cost["completion_tokens"] == 200
    # 1000 * 1e-6 + 200 * 2e-6
    assert cost["usd"] == pytest.approx(0.0014)


# -- the entry-search switch (K.3) ------------------------------------------


def test_the_hybrid_flag_is_accepted_and_never_sticky(station):
    """`hybrid` is per call and defaults to false on every call. Sticky state
    would make one experiment silently change every request after it."""
    client, pool, head = station
    _call(client, head, "locate", query=QUESTION, hybrid=True)
    assert pool.get(FOREST).hybrid_locate is True
    _call(client, head, "locate", query=QUESTION)
    assert pool.get(FOREST).hybrid_locate is False


def test_asking_for_hybrid_without_a_layer_changes_nothing(station):
    """No embedder ⇒ `hybrid` is a flag with nothing behind it, and the
    BM25-only contract holds — it must not error, and it must not differ."""
    client, _, head = station
    plain = _call(client, head, "locate", query=QUESTION)
    asked = _call(client, head, "locate", query=QUESTION, hybrid=True)
    assert [r["id"] for r in asked["results"]] == [r["id"] for r in plain["results"]]


def test_the_flag_does_not_reach_the_primitive(station):
    """It is host state, not an engine argument: `locate` has no such
    parameter and would raise if it were forwarded."""
    client, _, head = station
    assert "results" in _call(client, head, "harvest", query=QUESTION, hybrid=True)
