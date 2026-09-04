# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The walk had no clock and no window (spec v0.79, F.173).

An operator asked a walk for the two screenshots uploaded that day. The
forest held them — `coverage` counted two media nodes in the walk's own
first hop — and the walk read the root, scanned it flat, grepped every body
for the word "media" and answered that the product keeps no pictures. Every
parameter it needed existed on the wire and none was named where the model
reads; no prompt said what day it was; and the hop record could not show
the filter that made a scan return zero.

The model is scripted, so what is under test is the harness: what the menu
says, what the loop forwards, what the record carries, what the key holds.
Whether a real model USES the window is criterion F.5's business.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from conftest import build_forest

REPO = Path(__file__).resolve().parents[1]
STATION = REPO / "apps" / "station"
STUDIO = REPO / "apps" / "studio"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

FOREST = "forest-fixture"


@pytest.fixture(scope="session")
def forage_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("v079-root")
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


def _station(forage_root, tmp_path, *, cache: bool):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=forage_root, registry_path=tmp_path / "station.db",
                    mcp=False)
    registry = app.state.registry
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "scripted-model")
    registry.set_setting(FOREST, "answer_cache", {"enabled": cache})
    return app, registry


@pytest.fixture()
def station(forage_root, tmp_path, scripted):
    from starlette.testclient import TestClient

    app, registry = _station(forage_root, tmp_path, cache=False)
    with TestClient(app) as client:
        yield client, registry


@pytest.fixture()
def cached_station(forage_root, tmp_path, scripted):
    from starlette.testclient import TestClient

    app, registry = _station(forage_root, tmp_path, cache=True)
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


def _system(seen) -> str:
    return seen["messages"][0]["content"]


def _first_user(seen) -> str:
    return seen["messages"][1]["content"]


# -- the menu names what the tools take -------------------------------------


def test_calendar_is_on_the_whitelist_and_answers_through_the_scope(station, scripted):
    """C.13.3 is the read that turns "today" into a window instead of a
    guess; the loop offers it for the reason it offers `coverage`."""
    from monkeyllm_station.inference import FORAGE_TOOLS

    assert "calendar" in FORAGE_TOOLS
    client, registry = station
    script, seen = scripted
    script += [tool("calendar", granularity="month"), final("ok")]

    out = _ask(client, _key(registry), question="what arrived this month", hops=3)
    hop = out["hops"][0]
    assert hop["tool"] == "calendar" and hop["ok"] is True, hop
    # One number for what came back: buckets, because periods are not nodes.
    assert hop["out"] == {"buckets": hop["out"]["buckets"]} and hop["out"]["buckets"] >= 1
    assert hop["args"] == {"granularity": "month"}
    assert "ids" not in hop
    # And the model was handed the map, buckets and the exact bounds they carry.
    shown = seen["messages"][-1]["content"]
    assert '"buckets"' in shown and '"since"' in shown and '"until"' in shown


def test_the_menu_names_what_the_tools_take():
    """A parameter the model is never told about is a parameter the
    whitelist did not admit. Every one of these worked on the wire before
    this version; none was named."""
    from monkeyllm_station.inference import FORAGE_SYSTEM

    for needle in ('"tool": "calendar"', '"granularity"', '"since"', '"until"',
                   'date_field', '"type_filter"', '"recursive"',
                   '"filter": {"type"'):
        assert needle in FORAGE_SYSTEM, needle
    lower = FORAGE_SYSTEM.lower()
    # Rule 4: a kind of node is found by its filter, and a sniff for the
    # type's NAME is named as the wrong move.
    assert "type_filter" in lower and "kind of node" in lower
    assert "merely mentions it" in lower


def test_the_walk_is_told_what_day_it_is(station, scripted):
    """J.10.5 rule 3. One clock: the prompt's date is `date.today()`, which
    is what stamps `created` on a node this host plants."""
    from monkeyllm_station.inference import host_today

    assert host_today() == dt.date.today().isoformat()
    client, registry = station
    script, seen = scripted
    script += [final("ok")]
    _ask(client, _key(registry), question="what came in today", hops=2)
    assert f"Today is {host_today()}" in _system(seen)


# -- what the loop forwards ---------------------------------------------------


def test_a_model_authored_window_reaches_the_engine(station, scripted):
    """The loop forwards the model's arguments as they are: a `since` the
    model wrote narrows the listing, and the record says so."""
    client, registry = station
    script, _ = scripted
    script += [tool("scan", parent_id="_index", recursive=True, since="2099"),
               tool("scan", parent_id="_index", recursive=True),
               final("ok")]

    out = _ask(client, _key(registry), question="q", hops=4)
    windowed, whole = out["hops"][0], out["hops"][1]
    assert windowed["ok"] is True and windowed["out"] == {"nodes": 0}, windowed
    assert "ids" not in windowed
    assert windowed["args"] == {"parent_id": "_index", "recursive": True,
                                "since": "2099"}
    assert whole["out"]["nodes"] > 0 and whole["ids"]
    assert whole["args"] == {"parent_id": "_index", "recursive": True}


def test_a_kind_of_node_is_found_by_its_filter_and_the_record_shows_it(
        station, scripted):
    """`scan _index -> 0` used to read as an empty root. It was a flat scan
    with a type filter over branches, and the record could not say so."""
    client, registry = station
    script, _ = scripted
    script += [tool("scan", parent_id="_index", filter={"type": "dataset"}),
               tool("scan", parent_id="_index", filter={"type": "dataset"},
                    recursive=True),
               final("ok")]

    out = _ask(client, _key(registry), question="the datasets", hops=4)
    flat, deep = out["hops"][0], out["hops"][1]
    assert flat["out"] == {"nodes": 0}
    assert flat["args"] == {"parent_id": "_index", "filter": {"type": "dataset"}}
    assert deep["out"]["nodes"] >= 1 and len(deep["ids"]) == deep["out"]["nodes"]
    assert deep["args"] == {"parent_id": "_index", "filter": {"type": "dataset"},
                            "recursive": True}


def test_the_callers_window_replaces_the_models(station, scripted):
    """C.13.1 rule 7: a bounded hunt is bounded at every hop, `calendar`
    included, and the caller's bound lands last. `coverage` stays outside
    it (it takes no window at all)."""
    client, registry = station
    script, seen = scripted
    script += [tool("scan", parent_id="_index", recursive=True, since="2099"),
               tool("calendar", since="2099"),
               tool("coverage"),
               final("ok")]

    out = _ask(client, _key(registry), question="q", hops=5,
               since="2020", until="2030")
    scan, cal, cov = out["hops"][:3]
    # The bound arrives normalised (C.13.1 rule 6): the record shows the two
    # dates the search actually used, which are also the two a reader can
    # reuse — never the model's "2099".
    assert scan["args"]["since"] == "2020-01-01"
    assert scan["args"]["until"] == "2030-12-31"
    assert scan["out"]["nodes"] > 0, scan
    assert cal["ok"] is True and cal["args"]["since"] == "2020-01-01"
    assert cal["args"]["until"] == "2030-12-31"
    assert cov["ok"] is True and cov["args"] == {}
    assert "replaces any since/until you send" in _first_user(seen)


def test_a_hop_carries_only_what_the_model_set(station, scripted):
    """An argument the model did not set is absent, never a default
    written in — a consumer reads the absent field as *not set*."""
    client, registry = station
    script, _ = scripted
    script += [tool("locate", query="architecture"), final("ok")]

    out = _ask(client, _key(registry), question="q", hops=2)
    assert out["hops"][0]["args"] == {"query": "architecture"}


# -- the key ------------------------------------------------------------------


def _policy():
    return types.SimpleNamespace(allow=[""], deny=[], tables={})


def test_the_walk_key_moves_with_the_date_and_the_sweep_key_does_not():
    """J.10.7 (v0.79): the prompt states the date, so a hunt asked on two
    days is two hunts. Only the walk's: a date in the sweep's key would
    expire every stored answer nightly for nothing."""
    from monkeyllm_station.answer_store import build_key

    common = dict(question="what came in today", terms=["today"], k=3,
                  hybrid=False, binding={"provider": "p", "model": "m"},
                  policy=_policy())
    day1 = build_key(hops=3, head="abc", today="2026-09-03", **common)
    day2 = build_key(hops=3, head="abc", today="2026-09-04", **common)
    assert day1 != day2
    # A sweep passes no date and keys exactly as before this version.
    sweep = build_key(hops=None, head=None, **common)
    assert sweep == build_key(hops=None, head=None, today=None, **common)
    assert sweep != day1


def test_a_walk_stored_yesterday_is_not_served_today(cached_station, scripted,
                                                     monkeypatch):
    """The stored walk is served whole on its key; across midnight the key
    is a different one, so "today" is never answered with yesterday's walk."""
    from monkeyllm_station import inference

    client, registry = cached_station
    script, seen = scripted
    head = _key(registry)

    monkeypatch.setattr(inference, "host_today", lambda: "2026-01-01")
    script += [tool("look", id="notes/_index"), final("day one", ["notes/_index"])]
    first = _ask(client, head, question="what came in today", hops=2)
    assert "cached" not in first and first["answer"] == "day one"
    turns = seen["turns"]

    again = _ask(client, head, question="what came in today", hops=2)
    assert again.get("cached") is True and again["answer"] == "day one"
    assert seen["turns"] == turns

    monkeypatch.setattr(inference, "host_today", lambda: "2026-01-02")
    script += [tool("look", id="notes/_index"), final("day two", ["notes/_index"])]
    later = _ask(client, head, question="what came in today", hops=2)
    assert "cached" not in later and later["answer"] == "day two"
    assert seen["turns"] > turns
    assert "Today is 2026-01-02" in _system(seen)


# -- the console (J.5.19) -----------------------------------------------------


CHECKER = STUDIO / "check-ask-window.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_console_meets_its_criteria():
    """Studio has no test runner: the criteria live beside the code in
    `check-ask-window.mjs` (F.137's boundary — the source, never the
    rendered page) and run from here so they cannot quietly stop holding."""
    r = subprocess.run(["node", str(CHECKER)], capture_output=True, text=True,
                       cwd=STUDIO)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("PASS") >= 8, r.stdout


def test_the_window_is_named_in_every_language():
    for lang in ("en", "pt", "es"):
        d = json.loads((STUDIO / "src" / "locales" / "ask" / f"{lang}.json")
                       .read_text(encoding="utf-8"))
        for key in ("ask.window", "ask.window_hint", "ask.window_since",
                    "ask.window_until", "ask.window_used", "ask.window_clear",
                    "ask.history_window", "ask.hop_buckets"):
            assert d.get(key), (lang, key)
        assert d["ask.window_since"] != d["ask.window_until"], lang
