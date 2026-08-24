# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The MCP surface (spec J.1): the same forests, the same policy, spoken in
the protocol agents already use.

This is the surface that lets an existing agent harness swap its own
knowledge base for a governed forest, so the scoping guarantees are asserted
here again rather than assumed from the REST tests — F.18 asks for one test
per primitive per surface, and this is the second surface.
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
HEADERS = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def mcp_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("mcp-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def mcp_station(mcp_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=mcp_root, registry_path=tmp_path / "station.db", mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry


def rpc(client, method, params=None, key=None, rid=1):
    headers = dict(HEADERS)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp/", headers=headers, json=body)


def tool(client, name, args, key=None):
    r = rpc(client, "tools/call", {"name": name, "arguments": args}, key=key)
    assert r.status_code == 200, r.text
    return json.loads(r.json()["result"]["content"][0]["text"])


def _scoped_key(registry, principal="agent", caps=("read",), allow=("projects/",)):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps), allow=list(allow))
    return key


def test_tools_are_the_primitives(mcp_station):
    client, registry = mcp_station
    key = _scoped_key(registry)
    names = {t["name"] for t in rpc(client, "tools/list", key=key).json()["result"]["tools"]}
    assert {"forests", "locate", "look", "move", "pick", "scan", "sniff",
            "harvest", "query", "plant", "graft", "tend"} <= names


def test_unauthenticated_call_is_refused(mcp_station):
    client, _ = mcp_station
    out = tool(client, "locate", {"forest": FOREST, "query": "stigmergy"})
    assert out["error"]["code"] == "E_FORBIDDEN"


def test_forests_tool_reports_roots(mcp_station):
    client, registry = mcp_station
    out = tool(client, "forests", {}, key=_scoped_key(registry))
    assert out["forests"][0]["id"] == FOREST
    assert out["forests"][0]["roots"] == ["projects/_index"]


def test_locate_is_scoped_through_mcp(mcp_station):
    client, registry = mcp_station
    out = tool(client, "locate", {"forest": FOREST, "query": "model", "k": 5},
               key=_scoped_key(registry))
    assert out["results"] and all(h["id"].startswith("projects/") for h in out["results"])
    # the ancestor trail must not smuggle the master index back in
    assert all("_index" not in h["trail"] for h in out["results"])


def test_out_of_scope_node_is_absent_through_mcp(mcp_station):
    client, registry = mcp_station
    key = _scoped_key(registry)
    hidden = tool(client, "look", {"forest": FOREST, "id": "people/jimmy-wesley"}, key=key)
    absent = tool(client, "look", {"forest": FOREST, "id": "projects/nope-not-real"}, key=key)
    assert hidden["error"]["code"] == absent["error"]["code"] == "E_NOT_FOUND"
    assert hidden["error"]["hint"] == absent["error"]["hint"]


def test_ungranted_forest_is_absent_through_mcp(mcp_station):
    client, registry = mcp_station
    out = tool(client, "locate", {"forest": "no-such-forest", "query": "x"},
               key=_scoped_key(registry))
    assert out["error"]["code"] == "E_NOT_FOUND"


def test_harvest_composite_stays_scoped_through_mcp(mcp_station):
    client, registry = mcp_station
    out = tool(client, "harvest", {"forest": FOREST, "query": "stigmergy sales", "k": 3},
               key=_scoped_key(registry))
    blob = json.dumps(out)
    for hidden_branch in ("people/", "sales/", "concepts/"):
        assert f'"{hidden_branch}' not in blob


def test_write_tools_need_the_write_cap(mcp_station):
    client, registry = mcp_station
    out = tool(client, "plant",
               {"forest": FOREST,
                "node": {"id": "projects/x", "parent": "projects/_index",
                         "type": "note", "title": "X", "summary": "y"}},
               key=_scoped_key(registry, principal="reader", caps=("read",)))
    assert out["error"]["code"] == "E_FORBIDDEN"


def test_mcp_calls_are_audited(mcp_station):
    client, registry = mcp_station
    tool(client, "locate", {"forest": FOREST, "query": "stigmergy"},
         key=_scoped_key(registry, principal="watched-agent"))
    entries = registry.audit(limit=5, principal="watched-agent")
    assert entries and entries[0]["primitive"] == "locate"


# --- J.1.2 rule 4 as amended, and J.1.4 (v0.64) ---------------------------

MODERN = "2026-07-28"
_ENVELOPE = {
    "io.modelcontextprotocol/protocolVersion": MODERN,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "t", "version": "1"},
}


def _modern(client, method, key, params=None, rid=1):
    """One request on the 2026-07-28 wire, where the envelope rides `_meta`
    and the method is named again in a header."""
    body = {"jsonrpc": "2.0", "id": rid, "method": method,
            "params": {**(params or {}), "_meta": _ENVELOPE}}
    return client.post("/mcp/", json=body, headers={
        **HEADERS, "Authorization": f"Bearer {key}",
        "MCP-Protocol-Version": MODERN, "MCP-Method": method})


def test_what_is_withheld_is_the_two_families_and_nothing_else(mcp_station):
    """F.135. J.1.2 rule 4 withholds `prompts` and `resources`, and the list
    that implements it once reached one method further —
    `subscriptions/listen`, which is not a feature a client lists but the
    2026-07-28 era's only server-to-client channel. Withholding it did not
    save a round trip; it ended the connection (J.1.4). The shape of the
    list is the guard, because the next name added to it will be added for
    rule 4's reason and may not be rule 4's kind of thing."""
    from monkeyllm_station.mcp_surface import UNSERVED_METHODS

    assert UNSERVED_METHODS
    assert all(m.startswith(("prompts/", "resources/")) for m in UNSERVED_METHODS)


def test_list_changed_is_announced_only_where_the_handler_derives_it(mcp_station):
    """F.135. Serving the handler flips `tools.listChanged` at the modern era
    and at no other: the earlier eras derive the flag from notification
    options, so they are unchanged to the bit."""
    client, registry = mcp_station
    key = _scoped_key(registry)
    for version, expected in (("2025-06-18", False), ("2025-11-25", False)):
        reply = client.post("/mcp/", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {},
                       "clientInfo": {"name": "t", "version": "1"}}},
            headers={**HEADERS, "Authorization": f"Bearer {key}"})
        caps = reply.json()["result"]["capabilities"]
        assert caps["tools"]["listChanged"] is expected, version

    caps = _modern(client, "server/discover", key).json()["result"]["capabilities"]
    assert caps["tools"]["listChanged"] is True


@pytest.mark.parametrize("method", ["resources/list", "prompts/list",
                                    "nonsense/method"])
def test_an_unserved_method_is_not_a_lost_session(mcp_station, method):
    """F.136. On this transport 404 means the session is gone, so a client
    that reads one stops using a connection that was healthy — and the call
    that fails is the next one. A method this Station does not serve is a
    JSON-RPC error under a 2xx; the refusal itself is unchanged."""
    client, registry = mcp_station
    reply = _modern(client, method, _scoped_key(registry))
    assert reply.status_code == 200, reply.text
    assert reply.json()["error"]["code"] == -32601


def test_a_wrong_path_under_the_mount_is_still_absent(mcp_station):
    """F.136's boundary: the rule is about a refusal spoken by the
    dispatcher, never about an address. A 404 that is not a JSON-RPC body
    is left exactly as it was."""
    client, registry = mcp_station
    reply = client.get("/mcp/nope",
                       headers={"Authorization": f"Bearer {_scoped_key(registry)}"})
    assert reply.status_code == 404
