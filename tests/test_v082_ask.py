# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The ask that nobody could see (spec v0.82): F.206-F.211.

A consumer's client filtered `answer` out of its tool list and reported the
product had no way to ask. Everything they asked for afterwards was a gap on
this side: the token that says who may ask (J.2.7), the walk on the MCP
surface (J.10.5), a response the caller can carry (J.10.13), reasoning kept
out of the reply (J.10.8), the SDK's refusal in the envelope (J.1.2 rule 8)
and the `media:` reference named as a call (J.10.9).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

from monkeyllm_station import inference as _inference  # noqa: E402

# Captured before any fixture patches it: the reasoning test runs the real
# client against a stand-in transport.
_REAL_CHAT = _inference.chat_from_binding

FOREST = "forest-fixture"
NODE = "notes/_index"
MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def ask_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("ask-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def scripted(monkeypatch):
    """A model that says whatever the test queued and counts its turns.

    `script` is consumed one turn at a time; an empty script answers a
    fixed sweep reply, so the sweep tests need no script at all.
    """
    script: list[str] = []
    seen: dict = {"turns": 0}

    def fake(binding, **_kw):
        def chat(messages):
            seen["turns"] += 1
            return script.pop(0) if script else "stub answer"
        return chat, binding.get("model", "scripted")

    from monkeyllm_station import inference

    monkeypatch.setattr(inference, "chat_from_binding", fake)
    return script, seen


@pytest.fixture()
def station(ask_root, tmp_path, scripted, monkeypatch):
    """One deployment, both surfaces up: every rule here is asked of REST
    and MCP alike (C.12 rule 1)."""
    import shutil

    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    shutil.rmtree(ask_root / FOREST / "_derived" / "cache", ignore_errors=True)
    monkeypatch.setenv("MONKEYLLM_STATION_READERS", "0")
    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)
    app = build_app(root=ask_root, registry_path=tmp_path / "station.db",
                    mcp=True)
    registry = app.state.registry
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "scripted-model")
    with TestClient(app) as client:
        yield client, registry


def _key(registry, principal, caps, allow=("",)):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), allow=list(allow))
    return key


def _bearer(key):
    return {"Authorization": f"Bearer {key}"}


def _rest(client, key, **body):
    return client.post(f"/v1/forests/{FOREST}/answer", json=body,
                       headers=_bearer(key))


def _rpc(client, key, method, params=None, id=1):
    return client.post("/mcp/", headers={**MCP_HEADERS, **_bearer(key)},
                       json={"jsonrpc": "2.0", "id": id, "method": method,
                             **({"params": params} if params is not None else {})})


def _tools(client, key) -> dict:
    r = _rpc(client, key, "tools/list")
    assert r.status_code == 200, r.text
    return {t["name"]: t for t in r.json()["result"]["tools"]}


def _call(client, key, name, **arguments):
    scoped = {} if name == "forests" else {"forest": FOREST}
    r = _rpc(client, key, "tools/call",
             {"name": name, "arguments": {**scoped, **arguments}}, id=2)
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    return result, json.loads(result["content"][0]["text"])


def tool(name, **args):
    return json.dumps({"tool": name, "args": args})


def final(text, nodes=()):
    return json.dumps({"tool": "answer", "args": {"text": text,
                                                  "answer_nodes": list(nodes)}})


# ===========================================================================
# F.206 — the question is a capability (J.2.7)
# ===========================================================================


def test_read_alone_may_not_ask_and_no_provider_runs(station, scripted):
    client, registry = station
    _script, seen = scripted
    key = _key(registry, "reader", {"read"})

    r = _rest(client, key, question="architecture notes")
    assert r.status_code == 403, r.text
    err = r.json()["error"]
    assert err["code"] == "E_FORBIDDEN"
    assert "'answer'" in err["message"]
    assert seen["turns"] == 0, "a refused ask never reaches a provider"

    # And the composite is unchanged for a key that holds the token.
    asker = _key(registry, "asker", {"read", "answer"})
    r = _rest(client, asker, question="architecture notes")
    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "stub answer"


def test_the_menu_lists_answer_only_for_a_key_that_holds_it(station):
    """J.2.7 rule 5: a tool that can only refuse costs every session its
    description and teaches nothing — L.7 rule 2, applied to `answer`."""
    client, registry = station

    reader = _key(registry, "reader", {"read"})
    listed = _tools(client, reader)
    assert "answer" not in listed
    for name in ("harvest", "locate", "look", "pick", "sniff", "view"):
        assert name in listed, f"{name} must still be listed"

    asker = _key(registry, "asker", {"read", "answer"})
    assert "answer" in _tools(client, asker)

    # `admin` implies it, as it implies every other token.
    admin = _key(registry, "boss", {"admin"})
    assert "answer" in _tools(client, admin)


def test_a_mask_narrows_the_menu_too(station):
    """The menu reads grants ∩ mask, as every other authority read does."""
    client, registry = station
    registry.grant("alice", FOREST, {"read", "answer", "ingest"})
    plain = registry.issue_key("alice")
    masked = registry.issue_key("alice", caps={"read", "ingest"})
    assert "answer" in _tools(client, plain)
    assert "answer" not in _tools(client, masked)


def test_forests_and_me_report_the_token(station):
    client, registry = station
    asker = _key(registry, "asker", {"read", "answer"})
    reader = _key(registry, "reader", {"read"})

    me = client.get("/v1/me", headers=_bearer(asker)).json()
    assert "answer" in me["grants"][0]["caps"]
    me = client.get("/v1/me", headers=_bearer(reader)).json()
    assert "answer" not in me["grants"][0]["caps"]

    _result, body = _call(client, asker, "forests")
    forests = {f["id"]: f for f in body["forests"]}
    assert "answer" in forests[FOREST]["caps"]


def test_granted_without_a_binding_gets_the_binding_refusal(station, scripted):
    """J.2.7 rule 2: the capability says who may ask; the binding says what
    answers. Decided in that order."""
    client, registry = station
    _script, seen = scripted
    registry.unbind_model(FOREST, "answer")
    asker = _key(registry, "asker", {"read", "answer"})
    r = _rest(client, asker, question="anything")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "E_SCHEMA"
    assert "no model is bound" in r.json()["error"]["message"]
    assert seen["turns"] == 0

    # A key without the token is refused BEFORE the binding is looked at:
    # it is told it may not ask, never which model it may not use.
    reader = _key(registry, "reader", {"read"})
    r = _rest(client, reader, question="anything")
    assert r.status_code == 403
    assert "no model" not in r.json()["error"]["message"]


def test_the_repair_adds_answer_once(tmp_path):
    """J.2.7 rule 3: a registry from before the token opens with `answer`
    wherever `read` was — grants comma-joined, masks as JSON — and only
    once: a grant narrowed to `read` afterwards stays narrowed."""
    from monkeyllm_station.registry import DATA_REPAIRS, Registry

    path = tmp_path / "old.db"
    registry = Registry(path)
    registry.grant("alice", FOREST, {"read", "query"})
    registry.grant("bob", FOREST, {"query"})
    registry.issue_key("alice", label="masked", caps={"read", "ingest"})
    registry.issue_key("alice", label="plain")
    registry.issue_key("bob", label="narrow", caps={"ingest"})

    # Turn the clock back: the rows as a v0.81 Station wrote them.
    conn = sqlite3.connect(path)
    conn.execute("UPDATE grants SET caps = 'query,read' WHERE principal = 'alice'")
    conn.execute("UPDATE api_keys SET caps = '[\"ingest\", \"read\"]' "
                 "WHERE label = 'masked'")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    reopened = Registry(path)
    caps = {g["forest"]: set(g["caps"]) for g in reopened.grants_of("alice")}
    assert caps[FOREST] == {"read", "query", "answer"}
    assert set(reopened.grants_of("bob")[0]["caps"]) == {"query"}, \
        "a grant that never carried read gains nothing"
    masks = {label: (json.loads(caps) if caps else None)
             for label, caps in reopened.conn.execute(
                 "SELECT label, caps FROM api_keys")}
    assert set(masks["masked"]) == {"read", "ingest", "answer"}
    assert masks["plain"] is None, "an unmasked key stays unmasked"
    assert set(masks["narrow"]) == {"ingest"}
    stamp = reopened.conn.execute("PRAGMA user_version").fetchone()[0]
    assert stamp == len(DATA_REPAIRS)

    # Once. An operator's narrowing survives the next open.
    reopened.grant("alice", FOREST, {"read"})
    again = Registry(path)
    assert set(again.grants_of("alice")[0]["caps"]) == {"read"}


def test_the_pair_ceiling_and_default_carry_answer(station):
    """J.2.7 rule 4: a door that minted `read` alone yesterday mints `read`
    and `answer` today. `write` stays refused (J.2.6)."""
    client, registry = station
    registry.grant("alice", FOREST, {"read", "answer", "ingest"})
    registry.set_password("alice", "orange-tabby-9")

    def pair(**extra):
        return client.post("/v1/auth/pair",
                           json={"username": "alice",
                                 "password": "orange-tabby-9", **extra})

    default = pair()
    assert default.status_code == 200, default.text
    assert default.json()["caps"] == ["answer", "ingest", "read"]

    explicit = pair(caps=["answer"])
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()["caps"] == ["answer"]
    only = explicit.json()["api_key"]
    assert client.get("/v1/me", headers=_bearer(only)).json()["grants"][0]["caps"] == ["answer"]

    refused = pair(caps=["write"])
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "E_SCHEMA"


def test_the_owner_holds_it(station, monkeypatch):
    client, registry = station
    assert registry.create_owner("owner", "a-long-enough-password-1")
    key = registry.issue_key("owner")
    me = client.get("/v1/me", headers=_bearer(key)).json()
    assert "answer" in me["grants"][0]["caps"]
    assert "answer" in _tools(client, key)


# ===========================================================================
# F.207 — the walk is on both surfaces (J.10.5)
# ===========================================================================


def _walk_script():
    return [tool("look", id=NODE), tool("pick", id=NODE),
            final("it is in the notes", [NODE])]


def test_hops_over_mcp_is_the_walk_rest_serves(station, scripted):
    client, registry = station
    script, _seen = scripted
    registry.set_setting(FOREST, "answer_cache", {"enabled": False})
    key = _key(registry, "root", {"admin"})

    script += _walk_script()
    rest = _rest(client, key, question="architecture notes", hops=2).json()
    script += _walk_script()
    _result, mcp = _call(client, key, "answer", question="architecture notes",
                         hops=2)

    def stripped(hops):
        return [{k: v for k, v in h.items() if k not in ("ms", "model_ms")}
                for h in hops]

    assert mcp["answer"] == rest["answer"] == "it is in the notes"
    assert stripped(mcp["hops"]) == stripped(rest["hops"])
    assert mcp["read"] == rest["read"]
    assert [h["tool"] for h in mcp["hops"]] == ["look", "pick"]

    # The schema publishes the parameter, both spellings (J.10.5).
    schema = _tools(client, key)["answer"]["inputSchema"]["properties"]
    assert "hops" in schema and "detail" in schema


def test_terms_beside_hops_is_an_envelope_over_mcp(station, scripted):
    client, registry = station
    key = _key(registry, "root", {"admin"})
    result, body = _call(client, key, "answer", question="x",
                         terms=["1045"], hops=True)
    assert result["isError"] is True
    assert body["error"]["code"] == "E_SCHEMA"
    assert "terms" in body["error"]["message"]


def test_a_hop_is_progress(station, scripted, monkeypatch):
    """One progress report per completed hop, `progress` the hop's `n`, the
    budget as `total`; a sweep reports nothing. The SDK is what makes the
    report a no-op without a `progressToken`; what is asserted here is the
    Station's half: that it reports at all, and per hop."""
    from mcp.server.mcpserver.context import Context

    reported: list[tuple] = []

    async def record(self, progress, total=None, message=None):
        reported.append((progress, total, message))

    monkeypatch.setattr(Context, "report_progress", record)

    client, registry = station
    script, _seen = scripted
    registry.set_setting(FOREST, "answer_cache", {"enabled": False})
    key = _key(registry, "root", {"admin"})

    script += _walk_script()
    _result, body = _call(client, key, "answer", question="architecture notes",
                          hops=3)
    assert [h["tool"] for h in body["hops"]] == ["look", "pick"]
    assert [(p, t) for p, t, _m in reported] == [(1, 3), (2, 3)]
    assert "look" in reported[0][2] and "pick" in reported[1][2]

    reported.clear()
    _result, body = _call(client, key, "answer", question="architecture notes")
    assert "hops" not in body
    assert reported == [], "a sweep is one call and reports no progress"


def test_the_description_names_the_cost_and_the_duration(station):
    """J.10.5 rule 3 and F.211: the served description says what a hop costs,
    that a walk outlasts a client's clock, and that a media: reference is
    opened with view."""
    client, registry = station
    key = _key(registry, "asker", {"read", "answer"})
    desc = _tools(client, key)["answer"]["description"]
    assert "one model call" in desc
    assert "minutes" in desc
    assert "progressToken" in desc
    assert "media:<id>" in desc and "view(forest, id)" in desc
    assert "`detail`" in desc

    init = _rpc(client, key, "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {},
                 "clientInfo": {"name": "t", "version": "0"}})
    instructions = init.json()["result"]["instructions"]
    assert "hops=true" in instructions
    assert "media:<id>" in instructions and "view(forest, id)" in instructions
    assert "answer capability" in instructions


# ===========================================================================
# F.208 — the answer at the size the caller can carry (J.10.13)
# ===========================================================================

TEXTUAL = ("harvest", "read", "turns", "trace")


def test_three_levels_one_entry(station, scripted):
    client, registry = station
    _script, seen = scripted
    key = _key(registry, "asker", {"read", "answer"})
    q = "architecture notes"

    _miss = _rest(client, key, question=q).json()
    bare = _rest(client, key, question=q).json()  # the hit, like the rest
    full = _rest(client, key, question=q, detail="full").json()
    sources = _rest(client, key, question=q, detail="sources").json()
    answer = _rest(client, key, question=q, detail="answer").json()

    # `full` is the call without the parameter (the trace carries clocks, so
    # the comparison is by shape and content, never by the millisecond).
    assert set(full) == set(bare)
    assert full["harvest"]["results"] == bare["harvest"]["results"]

    assert not any(k in sources for k in TEXTUAL)
    for k in ("answer", "sources", "evidence", "cost", "model"):
        assert sources.get(k) == full.get(k), k
    assert sources["sources"], "the citations survive"

    assert not any(k in answer for k in TEXTUAL + ("sources", "hops"))
    assert answer["answer"] == full["answer"]
    assert answer["evidence"] == full["evidence"]

    # One entry: the model ran once, and every later call is a hit whatever
    # its level — `detail` never enters the key.
    assert seen["turns"] == 1
    assert full["cached"] and sources["cached"] and answer["cached"]

    # The audit row is the record's size, not the projection's (rule 5):
    # the most recent row is the `answer`-level call, and it is bigger than
    # what that call was served.
    latest = registry.audit(limit=1)[0]
    assert latest["primitive"] == "answer"
    assert latest["size"] > len(json.dumps(answer))


def test_an_unknown_level_is_refused_before_anything_runs(station, scripted):
    client, registry = station
    _script, seen = scripted
    key = _key(registry, "asker", {"read", "answer"})
    r = _rest(client, key, question="x", detail="brief")
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "E_SCHEMA" and "detail" in err["message"]
    assert seen["turns"] == 0


def test_the_refusal_is_unshaped(station, scripted):
    """J.10.13 rule 6: `insufficient_evidence` IS the evidence."""
    client, registry = station
    key = _key(registry, "asker", {"read", "answer"})
    r = _rest(client, key, question="architecture notes", min_evidence=1,
              min_score=0.9, detail="answer")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] is None
    assert body["reason"] == "insufficient_evidence"
    assert "harvest" in body


def test_detail_rides_the_mcp_tool(station, scripted):
    client, registry = station
    key = _key(registry, "asker", {"read", "answer"})
    _result, body = _call(client, key, "answer", question="architecture notes",
                          detail="sources")
    assert body["answer"] == "stub answer"
    assert "harvest" not in body and "trace" not in body
    assert body["sources"]


# ===========================================================================
# F.209 — the reasoning is not the reply (J.10.8)
# ===========================================================================


class _Reply:
    def __init__(self, content, finish="stop"):
        self.status_code = 200
        self.text = ""
        self._body = {"choices": [{"message": {"content": content},
                                   "finish_reason": finish}],
                      "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    def json(self):
        return self._body


def _client_answering(content, finish="stop"):
    """A stand-in for `httpx.Client` whose one endpoint answers `content`."""
    class Client:
        def __init__(self, **_kw):
            pass

        def post(self, _path, json=None):
            return _Reply(content, finish)
    return Client


@pytest.mark.parametrize("content,expect,flag", [
    ("<think>x</think>Answer", "Answer", True),
    ("<THINKING>\nlong\n</THINKING>\n\nAnswer", "Answer", True),
    ("Answer", "Answer", False),
])
def test_a_think_block_is_stripped_at_the_one_place_it_is_read(
        monkeypatch, content, expect, flag):
    import httpx

    from monkeyllm_station import inference

    monkeypatch.setattr(httpx, "Client", _client_answering(content))
    chat, _model = inference.chat_from_binding(
        {"endpoint": "http://stub/v1", "model": "m"})
    assert chat([{"role": "user", "content": "q"}]) == expect
    flags = inference.reply_flags(chat)
    assert flags.get("reasoning_stripped", False) is flag
    if not flag:
        assert flags == {}, "a reply without a block is byte-identical to before"


def test_an_open_block_is_all_thinking_and_the_cut_says_why(monkeypatch):
    import httpx

    from monkeyllm_station import inference

    monkeypatch.setattr(httpx, "Client",
                        _client_answering("<think>never closes", "length"))
    chat, _model = inference.chat_from_binding(
        {"endpoint": "http://stub/v1", "model": "m"})
    assert chat([{"role": "user", "content": "q"}]) == ""
    flags = inference.reply_flags(chat)
    assert flags["truncated"] is True
    assert flags["finish_reason"] == "length"
    assert flags["reasoning_stripped"] is True


def test_a_provider_field_is_untouched():
    """Reasoning in a field of its own was never read; only content is."""
    from monkeyllm_station.inference import strip_reasoning

    assert strip_reasoning("plain") == ("plain", False)
    assert strip_reasoning("<think>a</think><think>b</think> c") == ("c", True)
    assert strip_reasoning("text <think>not leading</think>") == \
        ("text <think>not leading</think>", False)


def test_a_walk_turn_parses_after_stripping(station, scripted, monkeypatch):
    """The sweep and the walk read content through the same `chat`, so the
    walk's tool call parses once the block is gone."""
    import httpx

    from monkeyllm_station import inference

    client, registry = station
    registry.set_setting(FOREST, "answer_cache", {"enabled": False})
    key = _key(registry, "root", {"admin"})

    turns = ["<think>which tool?</think>" + tool("look", id=NODE),
             final("found", [NODE])]

    class Client:
        def __init__(self, **_kw):
            pass

        def post(self, _path, json=None):
            return _Reply(turns.pop(0))

    # Undo the scripted stub so the real `chat_from_binding` runs.
    monkeypatch.setattr(inference, "chat_from_binding", _REAL_CHAT)
    monkeypatch.setattr(httpx, "Client", Client)

    out = _rest(client, key, question="architecture notes", hops=2).json()
    assert out["answer"] == "found"
    assert [h["tool"] for h in out["hops"]] == ["look"]
    assert out["reasoning_stripped"] is True


# ===========================================================================
# F.210 — the SDK's refusal wears the envelope (J.1.2 rule 8)
# ===========================================================================


def test_a_schema_refusal_is_rest_s_own_sentence(station, scripted):
    client, registry = station
    _script, seen = scripted
    key = _key(registry, "asker", {"read", "answer"})

    result, body = _call(client, key, "answer", question="x", k="many")
    assert result["isError"] is True
    assert body["error"]["code"] == "E_SCHEMA"
    assert "'k'" in body["error"]["message"]

    rest = _rest(client, key, question="x", k="many")
    assert rest.status_code == 400
    assert rest.json()["error"]["message"] == body["error"]["message"]
    assert seen["turns"] == 0


def test_a_missing_parameter_names_it(station):
    client, registry = station
    key = _key(registry, "asker", {"read", "answer"})
    r = _rpc(client, key, "tools/call",
             {"name": "view", "arguments": {"forest": FOREST}}, id=3)
    result = r.json()["result"]
    body = json.loads(result["content"][0]["text"])
    assert result["isError"] is True
    assert body["error"]["code"] == "E_SCHEMA"
    assert "'id'" in body["error"]["message"]


def test_an_unknown_tool_is_e_not_found(station):
    client, registry = station
    key = _key(registry, "asker", {"read", "answer"})
    r = _rpc(client, key, "tools/call",
             {"name": "nosuch", "arguments": {"forest": FOREST}}, id=4)
    result = r.json()["result"]
    body = json.loads(result["content"][0]["text"])
    assert result["isError"] is True
    assert body["error"]["code"] == "E_NOT_FOUND"
    assert "nosuch" in body["error"]["message"]
    assert "locate" in body["error"]["hint"]


def test_a_domain_refusal_is_untouched(station):
    """Rule 8 rewrites the SDK's sentence and never ours: a C.12 envelope
    the tool produced passes through byte-identical."""
    client, registry = station
    key = _key(registry, "asker", {"read", "answer"})
    result, body = _call(client, key, "look", id="no/such/node")
    assert result["isError"] is True
    assert body["error"]["code"] == "E_NOT_FOUND"


# ===========================================================================
# F.212 — hybrid on every surface, and the reply says whether it happened
# ===========================================================================


class FakeEmbedder:
    model = "fake-embed"

    def embed(self, texts):
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


@pytest.fixture()
def dense_station(tmp_path, scripted, monkeypatch):
    """A forest whose canopy index was built for the bound embedder, as a
    J.13.4 build leaves it: saved, model recorded."""
    from starlette.testclient import TestClient

    from monkeyllm import Vine
    from monkeyllm.canopy import CanopyIndex
    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    root = tmp_path / "root"
    build_forest(root / FOREST)
    seed = Vine(root / FOREST, writable=False)
    rows = [(r["id"], f"{r['title']}. {r['summary']}")
            for r in seed.catalog.conn.execute(
                "SELECT id, title, summary FROM nodes")]
    CanopyIndex.build(rows, FakeEmbedder()).save(seed.forest.derived_dir)
    seed.close()

    monkeypatch.setattr(inference, "embedder_from_binding",
                        lambda binding: FakeEmbedder())
    monkeypatch.setenv("MONKEYLLM_STATION_READERS", "0")
    app = build_app(root=root, registry_path=tmp_path / "dense.db", mcp=True)
    registry = app.state.registry
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(FOREST, "answer", "p", "scripted-model")
    registry.bind_model(FOREST, "embed", "p", "fake-embed")
    with TestClient(app) as client:
        yield client, registry


def test_the_three_tools_publish_hybrid(station):
    client, registry = station
    key = _key(registry, "asker", {"read", "answer"})
    tools = _tools(client, key)
    for name in ("locate", "harvest", "answer"):
        assert "hybrid" in tools[name]["inputSchema"]["properties"], name


def test_a_layer_asked_for_and_absent_is_said(station, scripted):
    """K.3 rule 2: BM25 in silence was the lie C.13 forbids a filter to
    tell. A call that did not ask carries neither field."""
    client, registry = station
    key = _key(registry, "asker", {"read", "answer"})
    q = "architecture notes"

    plain = _rest(client, key, question=q).json()
    assert "hybrid" not in plain and "hybrid_reason" not in plain

    asked = _rest(client, key, question=q, hybrid=True).json()
    assert asked["answer"] == "stub answer"
    assert asked["hybrid"] is False
    assert asked["hybrid_reason"] == "no-embedder"

    for name, args in (("answer", {"question": q}),
                       ("harvest", {"query": q}),
                       ("locate", {"query": "architecture"})):
        _result, body = _call(client, key, name, hybrid=True, **args)
        assert body["hybrid"] is False, name
        assert body["hybrid_reason"] == "no-embedder", name
        _result, body = _call(client, key, name, **args)
        assert "hybrid" not in body, name

    _result, listed = _call(client, key, "forests")
    assert {f["id"]: f["hybrid"] for f in listed["forests"]}[FOREST] is False
    rest = client.get("/v1/forests", headers=_bearer(key)).json()["forests"]
    assert {f["id"]: f["hybrid"] for f in rest}[FOREST] is False


def test_a_layer_present_is_fused_and_listed(dense_station, scripted):
    """K.3 rule 3 and the per-serve echo: a hit says what is true today."""
    client, registry = dense_station
    key = _key(registry, "asker", {"read", "answer"})
    q = "architecture notes"

    asked = _rest(client, key, question=q, hybrid=True).json()
    assert asked["hybrid"] is True and "hybrid_reason" not in asked
    again = _rest(client, key, question=q, hybrid=True).json()
    assert again["cached"] is True and again["hybrid"] is True

    _result, body = _call(client, key, "answer", question=q, hybrid=True)
    assert body["hybrid"] is True
    _result, body = _call(client, key, "locate", query="architecture", hybrid=True)
    assert body["hybrid"] is True

    _result, listed = _call(client, key, "forests")
    assert {f["id"]: f["hybrid"] for f in listed["forests"]}[FOREST] is True
    rest = client.get("/v1/forests", headers=_bearer(key)).json()["forests"]
    assert {f["id"]: f["hybrid"] for f in rest}[FOREST] is True
