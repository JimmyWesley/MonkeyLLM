# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The terms the caller authored (spec v0.67, J.10.3 + C.12 — F.141).

J.10.7's key has said "whether the caller supplied them or the sweep
derived them" since v0.33, and until this version the first half of that
sentence described a path no hosted surface offered: `harvest` took `terms`
and `answer` did not, so both key builders re-derived from the question and
a sweep's literal leg was always a guess made from the question's own
words. That guess is wrong exactly when the question's vocabulary is not
the corpus's — the measured case was a Portuguese question over an English
forest, which reached `sniff` as a substring search for `esta`.

`answer` takes `terms` now, and this file pins the four properties that
make it safe: they reach the `sniff` leg and the bundle says so; they name
the store entry; a walk refuses them rather than dropping them; and a call
that sends none is the call it always was — same retrieval, same key, same
stored entry.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
# The measured question: an English forest asked in Portuguese. Its derived
# terms are `["floresta"]`, a word the corpus does not contain.
PT_QUESTION = "Sobre o que é esta floresta?"
# A question this forest answers well, for the properties that need a
# bundle with material in it (an empty sweep never enters the store).
EN_QUESTION = "architecture notes"
# A fact that lives only in one body (the same one `test_harvest` uses to
# prove the sweep reaches buried text), so a hit on it is provably the
# literal leg's and not the lexical one's.
BURIED = "projects/mixerllm/experiment-log"


@pytest.fixture(scope="session")
def terms_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("terms-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(terms_root, tmp_path, monkeypatch):
    """The answer-store fixture's construction: every provider round trip is
    counted, so "one entry or two" is observable without reading the key."""
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    calls: list = []

    def fake(binding, **_kw):
        def chat(messages):
            calls.append(messages)
            return f"stub answer #{len(calls)}"
        return chat, binding.get("model", "stub-model")

    monkeypatch.setattr(inference, "chat_from_binding", fake)

    # The store lives in the forest's own `_derived/`, which is
    # session-scoped here; each test starts with an empty one.
    shutil.rmtree(terms_root / FOREST / "_derived" / "cache", ignore_errors=True)
    monkeypatch.setenv("MONKEYLLM_STATION_READERS", "0")

    app = build_app(root=terms_root, registry_path=tmp_path / "station.db",
                    mcp=False)
    registry = app.state.registry
    key = registry.issue_key("root")
    registry.grant("root", FOREST, {"read", "query"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, registry, calls, {"Authorization": f"Bearer {key}"}


@pytest.fixture()
def mcp_station(terms_root, tmp_path, monkeypatch):
    """The same deployment with the MCP mount up: C.12 rule 1's "identically
    on REST and MCP" is a claim about two surfaces, so it is asked of both."""
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    def fake(binding, **_kw):
        return (lambda messages: "stub answer"), binding.get("model", "stub-model")

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    shutil.rmtree(terms_root / FOREST / "_derived" / "cache", ignore_errors=True)
    monkeypatch.setenv("MONKEYLLM_STATION_READERS", "0")

    app = build_app(root=terms_root, registry_path=tmp_path / "station.db",
                    mcp=True)
    registry = app.state.registry
    key = registry.issue_key("agent")
    registry.grant("agent", FOREST, {"read"})
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, key


def _post(client, head, **body):
    return client.post(f"/v1/forests/{FOREST}/answer", json=body, headers=head)


def _ask(client, head, question=PT_QUESTION, **body):
    r = _post(client, head, question=question, **body)
    assert r.status_code == 200, r.text
    return r.json()


# -- the terms reach the sweep's literal leg ---------------------------------


def test_the_derived_terms_are_what_a_call_without_terms_still_gets(station):
    """The baseline, and the reason the parameter exists: derived from this
    question, the sweep searches for words the corpus never uses and comes
    back with nothing at all."""
    client, _, _, head = station
    bundle = _ask(client, head)["harvest"]
    assert bundle["terms"] == ["floresta"]
    assert bundle["results"] == []
    # C.6c rule 5: an empty sweep says what it swept, rather than reading as
    # a forest that knows nothing.
    assert bundle["searched"] >= 1 and bundle["hint"]


def test_supplied_terms_are_the_terms_the_sniff_leg_used(station):
    """F.141: the bundle reports the terms sent, not the derived ones — and
    the item they found says `sniff` found it."""
    client, _, _, head = station
    bundle = _ask(client, head, terms=["1045"])["harvest"]
    assert bundle["terms"] == ["1045"]
    assert bundle["query"] == PT_QUESTION, "the lexical leg still gets the question"

    found = {r["id"]: r for r in bundle["results"]}
    assert BURIED in found, "the buried fact is reachable only through the term"
    item = found[BURIED]
    assert "sniff" in item["found_by"]
    assert any("1045" in m["snippet"] for m in item["matches"])


def test_the_terms_ride_every_surface_the_same_way(station):
    """C.12: the table declares the parameter, so both surfaces enforce it
    identically. A list of integers is refused in `harvest`'s own words."""
    from monkeyllm.signatures import SIGNATURES

    assert SIGNATURES["answer"]["terms"] == SIGNATURES["harvest"]["terms"]

    client, _, calls, head = station
    r = _post(client, head, question=PT_QUESTION, terms=[123])
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "E_SCHEMA"
    assert "'terms'" in err["message"] and "string[]" in err["message"]
    assert not calls, "a malformed argument never reaches a provider"


def test_the_mcp_answer_tool_takes_them_too(mcp_station):
    """The other surface: declared in the tool schema and forwarded to the
    same sweep, so an agent holding a model can author the retrieval."""
    client, key = mcp_station
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json",
               "Authorization": f"Bearer {key}"}

    listed = client.post("/mcp/", headers=headers,
                         json={"jsonrpc": "2.0", "id": 1,
                               "method": "tools/list"})
    assert listed.status_code == 200, listed.text
    tool = next(t for t in listed.json()["result"]["tools"]
                if t["name"] == "answer")
    assert "terms" in tool["inputSchema"]["properties"]

    called = client.post(
        "/mcp/", headers=headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "answer",
                         "arguments": {"forest": FOREST,
                                       "question": PT_QUESTION,
                                       "terms": ["1045"]}}})
    assert called.status_code == 200, called.text
    body = json.loads(called.json()["result"]["content"][0]["text"])
    assert body["harvest"]["terms"] == ["1045"]
    assert BURIED in [r["id"] for r in body["harvest"]["results"]]


# -- the walk refuses them, rather than dropping them ------------------------


@pytest.mark.parametrize("hops", [True, 2])
def test_terms_beside_hops_is_e_schema_naming_the_parameter(station, hops):
    """J.10.3: a walk authors its own retrieval from hop 1, so accepting a
    term list and dropping it would be a lie about what ran."""
    client, _, calls, head = station
    r = _post(client, head, question=PT_QUESTION, terms=["1045"], hops=hops)
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "E_SCHEMA"
    assert "'terms'" in err["message"] and "hops" in err["message"]
    assert err.get("hint")
    assert not calls, "a refusal is never billed"


def test_a_walk_without_terms_is_untouched(station, monkeypatch):
    """The refusal is about the pair, never about `hops`."""
    from monkeyllm_station import inference

    walked = []

    def fake_forage(scoped, question, binding, **kw):
        walked.append(question)
        return {"answer": "walked", "model": "stub-model", "model_ms": 1.0,
                "hops": [], "read": [], "evidence": [], "sources": []}

    monkeypatch.setattr(inference, "forage", fake_forage)
    client, _, _, head = station
    body = _ask(client, head, hops=True)
    assert body["answer"] == "walked" and walked == [PT_QUESTION]


# -- the key: two term lists are two entries ---------------------------------


def test_two_sweeps_differing_only_in_terms_are_two_entries(station):
    """F.141's key half. The question, `k`, the binding and the scope are
    all equal; only the retrieval the caller authored differs, and it is
    what the model reads, so it must name the entry."""
    client, _, calls, head = station
    _ask(client, head, question=EN_QUESTION, terms=["1045"])
    assert len(calls) == 1
    repeated = _ask(client, head, question=EN_QUESTION, terms=["1045"])
    assert len(calls) == 1, "the same terms name the same entry"
    assert repeated["cached"] is True

    other = _ask(client, head, question=EN_QUESTION, terms=["stigmergy"])
    assert len(calls) == 2, "another term list is another entry"
    assert "cached" not in other


def test_supplying_the_derived_terms_hits_the_entry_the_derivation_made(station):
    """The key is on the EFFECTIVE terms, not on how they were chosen: a
    caller who sends exactly what the sweep would have derived is asking the
    identical question of the identical material, and is served the entry it
    already bought. This is also the proof that the upgrade invalidates
    nothing — an existing entry is keyed by the list this call supplies."""
    from monkeyllm.harvest import derive_terms

    client, _, calls, head = station
    first = _ask(client, head, question=EN_QUESTION)
    assert len(calls) == 1
    derived = derive_terms(EN_QUESTION)
    assert first["harvest"]["terms"] == derived
    served = _ask(client, head, question=EN_QUESTION, terms=derived)
    assert len(calls) == 1, "same effective terms, same entry"
    assert served["cached"] is True


def test_a_call_without_terms_is_the_call_it_always_was(station):
    """Byte-stability: absent `terms` changes neither the retrieval nor the
    key nor the response's shape — the parameter is not echoed back, and the
    second ask is the store's, exactly as before this version."""
    client, _, calls, head = station
    first = _ask(client, head, question="architecture notes")
    assert "terms" not in first, "the response gains no field"
    assert len(calls) == 1

    second = _ask(client, head, question="architecture notes")
    assert len(calls) == 1
    assert second["cached"] is True
    assert second["answer"] == first["answer"]
