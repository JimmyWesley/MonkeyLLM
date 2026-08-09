"""The answer that navigates (spec J.10.5).

The model is scripted here, so what is under test is the harness around it:
the budget, the whitelist, the scope, and what happens when the budget runs
out. Whether a real model navigates *well* is criterion F.5 and is measured
offline against a corpus — not something a unit test can assert.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"
NODE = "notes/_index"


@pytest.fixture(scope="session")
def forage_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("forage-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def scripted(monkeypatch):
    """A model that says whatever the test queued, and records what it saw."""
    script: list[str] = []
    seen: dict = {"turns": 0, "messages": []}

    def fake(binding, **_kw):
        def chat(messages):
            seen["turns"] += 1
            seen["messages"] = list(messages)
            return script.pop(0) if script else json.dumps(
                {"tool": "answer", "args": {"text": "out of script"}})
        return chat, binding.get("model", "scripted")

    from monkeyllm_station import inference

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    return script, seen


@pytest.fixture()
def station(forage_root, tmp_path, scripted):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=forage_root, registry_path=tmp_path / "station.db", mcp=False)
    registry = app.state.registry
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "scripted-model")
    with TestClient(app) as client:
        yield client, registry


def _key(registry, principal="root", caps=("admin", "read", "query", "write"),
         allow=("",)):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), allow=list(allow))
    return {"Authorization": f"Bearer {key}"}


def _ask(client, head, **body):
    r = client.post(f"/v1/forests/{FOREST}/answer", json=body, headers=head)
    assert r.status_code == 200, r.text
    return r.json()


def tool(name, **args):
    return json.dumps({"tool": name, "args": args})


def final(text, nodes=()):
    return json.dumps({"tool": "answer", "args": {"text": text,
                                                  "answer_nodes": list(nodes)}})


# -- opting in --------------------------------------------------------------


def test_the_sweep_is_still_the_default(station, scripted):
    """One model call, no hops: the cheap path must not become opt-out."""
    client, registry = station
    _script, seen = scripted
    out = _ask(client, _key(registry), question="architecture notes")
    assert "hops" not in out
    assert seen["turns"] == 1


def test_asking_for_hops_navigates_and_reports_the_path(station, scripted):
    client, registry = station
    script, _seen = scripted
    script += [tool("look", id=NODE), tool("pick", id=NODE),
               final("it is in the notes", [NODE])]

    out = _ask(client, _key(registry), question="architecture notes", hops=True)
    assert out["answer"] == "it is in the notes"
    assert [h["tool"] for h in out["hops"]] == ["look", "pick"]
    assert all(h["ok"] for h in out["hops"])
    # J.10.4 still applies, and now it carries the walk itself.
    assert [s["step"] for s in out["trace"]["steps"]][:3] == ["locate", "look", "pick"]


def test_the_hunt_starts_from_entry_search(station, scripted):
    """The first message hands over `locate` results — otherwise the model's
    opening move is always the same call, paid for with a turn."""
    client, registry = station
    script, seen = scripted
    script.append(final("done", [NODE]))
    _ask(client, _key(registry), question="architecture notes", hops=True)
    assert "locate" in seen["messages"][1]["content"]


# -- the budget -------------------------------------------------------------


def test_a_spent_budget_still_answers(station, scripted):
    """Running out must not discard the hunt: the tokens are already spent,
    and everything needed is in the context."""
    client, registry = station
    script, seen = scripted
    # Distinct calls: identical ones are collapsed by the repeat guard, and
    # this test is about the budget, not about that.
    script += [tool("look", id=NODE), tool("pick", id=NODE),
               tool("sniff", terms=["architecture"]), final("late but real", [NODE])]

    out = _ask(client, _key(registry), question="architecture notes", hops=3)
    assert out["answer"] == "late but real"
    assert len(out["hops"]) == 3
    assert "Step budget spent" in seen["messages"][-1]["content"]


def test_the_budget_is_bounded_however_it_is_asked_for(station, scripted):
    client, registry = station
    script, _ = scripted
    script += [tool("look", id=NODE)] * 100

    out = _ask(client, _key(registry), question="q", hops=10_000)
    from monkeyllm_station.inference import MAX_HOPS

    assert len(out["hops"]) <= MAX_HOPS


# -- what the loop may do ---------------------------------------------------


def test_a_question_cannot_become_an_edit(station, scripted):
    """The principal HOLDS `write`. The loop still must not offer it: they
    asked a question, and a whitelist is the only thing that says so."""
    client, registry = station
    script, _ = scripted
    script += [tool("plant", id="notes/new", title="x"), final("no", [])]

    out = _ask(client, _key(registry), question="q", hops=2)
    assert [h["tool"] for h in out["hops"]] == []
    assert "plant" not in [s["step"] for s in out["trace"]["steps"]]


def test_the_loop_reads_through_the_same_scope_as_its_caller(station, scripted):
    """J.10.3's invariant, unchanged: retrieval runs through `ScopedVine`, so
    a restricted principal's loop cannot open what they could not open."""
    client, registry = station
    script, _ = scripted
    script += [tool("pick", id="people/_index"), final("tried", [])]
    head = _key(registry, principal="alice", caps=("read",), allow=("projects/",))

    out = _ask(client, head, question="q", hops=2)
    assert out["hops"][0]["ok"] is False
    assert out["evidence"] == []


def test_a_cited_node_that_was_never_opened_is_not_evidence(station, scripted):
    """Evidence is what was read. An id the model produced from memory is a
    claim about the forest, not a reading of it."""
    client, registry = station
    script, _ = scripted
    script += [tool("look", id=NODE),
               final("x", ["notes/_index", "invented/node"])]

    out = _ask(client, _key(registry), question="q", hops=3)
    assert "invented/node" not in out["evidence"]


def test_the_same_call_twice_is_answered_with_a_nudge_not_a_repeat(station, scripted):
    """The search spiral, observed live: sniff, sniff, locate, sniff — the
    same query re-phrased until the budget is gone. A repeat returns the
    identical result, so running it again buys nothing and costs a hop."""
    client, registry = station
    script, _ = scripted
    script += [tool("look", id=NODE), tool("look", id=NODE), final("ok", [NODE])]

    out = _ask(client, _key(registry), question="q", hops=4)
    assert [h["tool"] for h in out["hops"]] == ["look"]
    assert [s["step"] for s in out["trace"]["steps"]].count("look") == 1


def test_it_reports_the_material_it_read(station, scripted):
    """Same question as the sweep's: what was this answer built from? A walk
    has no bundle, so the evidence is assembled from the hops."""
    client, registry = station
    script, _ = scripted
    script += [tool("sniff", terms=["architecture"]), tool("pick", id=NODE),
               final("ok", [NODE])]

    out = _ask(client, _key(registry), question="q", hops=4)
    read = {r["id"]: r for r in out["read"]}

    picked = read[NODE]
    assert "pick" in picked["found_by"]
    assert picked["content"][0]["body"]           # the text, not a summary
    sniffed = [r for r in out["read"] if r["matches"]]
    assert sniffed and all("snippet" in m for r in sniffed for m in r["matches"])


def test_a_hop_says_what_it_chose_and_what_came_back(station, scripted):
    """"sniff, sniff, locate" and "sniff → 0, sniff → 0, locate → 5" are the
    same list of verbs and opposite stories. Without the arguments and the
    count, a walk cannot be read."""
    client, registry = station
    script, _ = scripted
    script += [tool("sniff", terms=["architecture"]), tool("pick", id=NODE),
               final("ok", [NODE])]

    hops = _ask(client, _key(registry), question="q", hops=4)["hops"]
    assert [h["n"] for h in hops] == [1, 2]
    assert hops[0]["args"]["terms"] == ["architecture"]
    assert hops[0]["out"]["results"] >= 0
    assert hops[1]["out"]["tokens"] > 0


def test_a_hop_carries_both_clocks(station, scripted):
    """The forest call and the model turn that chose it are two costs. One
    number would hide which half a slow hunt is spending."""
    client, registry = station
    script, _ = scripted
    script += [tool("pick", id=NODE), final("ok", [NODE])]

    hop = _ask(client, _key(registry), question="q", hops=3)["hops"][0]
    assert hop["ms"] >= 0 and hop["model_ms"] >= 0


def test_the_right_hand_panel_can_name_the_hop_behind_a_step(station, scripted):
    """The walk and the timings are the same run seen twice; a step with no
    way back to the decision that caused it is a list of primitives."""
    client, registry = station
    script, _ = scripted
    script += [tool("sniff", terms=["architecture"]), tool("pick", id=NODE),
               final("ok", [NODE])]

    steps = _ask(client, _key(registry), question="q", hops=4)["trace"]["steps"]
    numbered = {s["step"]: s["hop"] for s in steps if "hop" in s}
    assert numbered == {"sniff": 1, "pick": 2}
    # The entry `locate` is not a hop: the forager did not choose it.
    assert "hop" not in steps[0]


def test_a_refused_hop_reports_the_refusal(station, scripted):
    client, registry = station
    script, _ = scripted
    script += [tool("pick", id="people/_index"), final("no", [])]
    head = _key(registry, principal="bob", caps=("read",), allow=("projects/",))

    hops = _ask(client, head, question="q", hops=2)["hops"]
    assert hops[0]["ok"] is False
    assert hops[0]["out"]["error"]


def test_query_rows_come_back_as_a_table_not_as_a_string(station, scripted):
    """A grid is what rows are. Serialising them would ask the console to
    parse a JSON string back into the table it already knows how to draw."""
    client, registry = station
    script, _ = scripted
    script += [tool("query", id="sales/report-q1-2026",
                    sql="SELECT region, SUM(value) AS total FROM sales GROUP BY region"),
               final("ok", ["sales/report-q1-2026"])]

    out = _ask(client, _key(registry), question="q", hops=3)
    rows = out["read"][0]["content"][0]
    assert rows["columns"] == ["region", "total"]
    assert isinstance(rows["rows"], list) and isinstance(rows["rows"][0], list)
    assert rows["sql"].startswith("SELECT region")


def test_a_look_is_a_digest_not_material(station, scripted):
    """`look` returns a summary. Filing it as an excerpt would undo the one
    distinction the panel exists to draw."""
    client, registry = station
    script, _ = scripted
    script += [tool("look", id=NODE), final("ok", [NODE])]

    out = _ask(client, _key(registry), question="q", hops=3)
    assert out["read"] == []
    assert [h["tool"] for h in out["hops"]] == ["look"]


def test_prose_around_the_json_is_tolerated(station, scripted):
    """Models fence and preface. Spending the budget on formatting rather
    than navigation would be a self-inflicted failure."""
    client, registry = station
    script, _ = scripted
    script += [f"Sure, let me look.\n```json\n{tool('look', id=NODE)}\n```",
               final("ok", [NODE])]

    out = _ask(client, _key(registry), question="q", hops=3)
    assert [h["tool"] for h in out["hops"]] == ["look"]
    assert out["answer"] == "ok"
