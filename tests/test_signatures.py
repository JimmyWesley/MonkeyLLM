# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Every exit is an envelope (spec C.12, criterion F.60).

The seven malformed calls tabled in C.12 were measured against a served
Station and produced five different behaviours — three bare `500`s, a
`TypeError` leaking through `message`, a `null` coerced into the string
`"None"` and looked up, and an integer accepted as a search term and
answered with an empty result set. The last is the worst of them: to a
model, "your argument was wrong" and "this forest has nothing" are opposite
findings, and one of them ends the hunt.

Two of the tests here are the load-bearing ones:

* `test_the_mcp_tools_and_the_table_agree` is the mechanical comparison
  C.12 rule 1 demands. The MCP schemas and the signature table describe one
  contract, and two descriptions agree only where somebody compared them.
* `test_an_unhandled_exception_is_still_an_envelope` proves the last
  resort, because the paths it covers are by definition the ones nobody
  thought of.
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

from monkeyllm.signatures import SIGNATURES  # noqa: E402

FOREST = "forest-fixture"
MCP_HEADERS = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def sig_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("signatures-root")
    build_forest(root / FOREST)
    return root


@pytest.fixture()
def station(sig_root, tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    app = build_app(root=sig_root, registry_path=tmp_path / "station.db", mcp=True)
    with TestClient(app) as client:
        yield client, app.state.registry


def _key(registry, principal="agent", caps=("read", "write", "query", "tend")):
    key = registry.issue_key(principal)
    registry.grant(principal, FOREST, set(caps))
    return {"Authorization": f"Bearer {key}"}


def call(client, head, primitive, body):
    return client.post(f"/v1/forests/{FOREST}/{primitive}", json=body, headers=head)


# --- C.12 rules 2-4: the seven calls, all in the envelope -------------------

MALFORMED = [
    ("pick", {"id": ["a", "b"], "section": 3}),      # section is not a string
    ("look", {"id": 123}),
    ("locate", {"query": ["a"]}),
    ("locate", {"query": "x", "k": "tres"}),
    ("sniff", {"terms": [123]}),
    ("locate", {"scent": "x"}),                       # a parameter that never existed
    ("query", {"id": "x"}),                           # a required one that is missing
]


@pytest.mark.parametrize("primitive,body", MALFORMED)
def test_a_malformed_call_is_e_schema_and_says_what_was_wrong(station, primitive, body):
    client, registry = station
    r = call(client, _key(registry), primitive, body)
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "E_SCHEMA"
    # The parameter is named, and so is what arrived: a message that names
    # neither is a stack trace wearing an envelope.
    assert primitive in err["message"]
    assert "not supported between instances" not in err["message"]
    assert err.get("hint")


def test_null_is_a_missing_argument_not_the_string_none(station):
    client, registry = station
    r = call(client, _key(registry), "look", {"id": None})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "E_SCHEMA" and "'id'" in err["message"]
    # The old behaviour: 404 for a node called "None".
    assert "None" not in err["message"].replace("never a value", "")


def test_an_optional_null_still_means_the_default(station):
    """C.12 rule 3's other half: `null` where the primitive has a default is
    the default, not a refusal — every client that omits a field by writing
    it as null keeps working."""
    client, registry = station
    r = call(client, _key(registry), "locate",
             {"query": "stigmergy", "type_filter": None, "include": None})
    assert r.status_code == 200, r.text
    assert "results" in r.json()


def test_a_valid_call_is_untouched(station):
    client, registry = station
    r = call(client, _key(registry), "locate", {"query": "stigmergy", "k": 3})
    assert r.status_code == 200 and r.json()["results"]


# --- C.12 rule 5: the last resort ------------------------------------------

def test_an_unhandled_exception_is_still_an_envelope(station, monkeypatch):
    client, registry = station
    from monkeyllm_station.policy import ScopedVine

    def boom(self, *a, **kw):
        raise RuntimeError("a defect nobody planned for")

    monkeypatch.setattr(ScopedVine, "locate", boom)
    r = call(client, _key(registry), "locate", {"query": "anything"})
    assert r.status_code == 500, r.text
    err = r.json()["error"]
    assert err["code"] == "E_INTERNAL"
    assert "locate" in err["message"] and "RuntimeError" in err["message"]
    # The classification is the disclosure; the detail belongs in the log.
    assert "a defect nobody planned for" not in json.dumps(r.json())
    assert "Traceback" not in json.dumps(r.json())


# --- C.12 rule 6: a missing parameter is not a denial -----------------------

def test_a_missing_forest_parameter_is_e_schema_for_an_admin(station):
    client, registry = station
    head = _key(registry, "boss", caps=("read", "admin"))
    r = client.get("/v1/admin/health", headers=head)
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "E_SCHEMA" and "forest" in err["message"]
    # And with the parameter, the same key is served.
    assert client.get(f"/v1/admin/health?forest={FOREST}", headers=head).status_code == 200


def test_a_named_forest_without_admin_is_still_forbidden(station):
    client, registry = station
    head = _key(registry, "reader", caps=("read",))
    r = client.get(f"/v1/admin/health?forest={FOREST}", headers=head)
    assert r.status_code == 403 and r.json()["error"]["code"] == "E_FORBIDDEN"


# --- C.12 rule 1: the two descriptions, compared ----------------------------

_JSON_TYPES = {
    "string": {"string"}, "integer": {"integer"}, "boolean": {"boolean"},
    "object": {"object"}, "string[]": {"array"}, "object[]": {"array"},
    "string|string[]": {"string", "array"},
    # C.7.4 (v0.58): one node, or a batch of them.
    "object|object[]": {"object", "array"},
    "boolean|integer": {"boolean", "integer"},
    # J.10.10 (v0.59): min_score is a threshold, not a count.
    "number": {"number"},
}


def _schema_types(schema: dict) -> set[str]:
    if "type" in schema:
        return {schema["type"]}
    out: set[str] = set()
    for member in schema.get("anyOf", []) or schema.get("oneOf", []):
        out |= _schema_types(member)
    return out - {"null"}


def test_the_mcp_tools_and_the_table_agree(station):
    client, registry = station
    head = _key(registry)
    r = client.post("/mcp/", headers={**MCP_HEADERS, **head},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    assert tools, "no tools listed, which would make this vacuous"

    checked = 0
    for tool in tools:
        table = SIGNATURES.get(tool["name"])
        if table is None:
            # `forests` and `view` shaped tools with no arguments of their
            # own may exist; anything with parameters must be declared.
            props = set((tool.get("inputSchema") or {}).get("properties", {})) - {"forest"}
            assert not props, f"{tool['name']} takes {sorted(props)} and is not in the table"
            continue
        schema = tool.get("inputSchema") or {}
        props = schema.get("properties", {})
        names = set(props) - {"forest"}
        unknown = names - set(table)
        assert not unknown, f"{tool['name']} accepts {sorted(unknown)}, off the table"

        for name in names:
            declared = _JSON_TYPES[table[name]["type"]]
            offered = _schema_types(props[name])
            assert offered & declared, (
                f"{tool['name']}.{name}: MCP says {sorted(offered)}, "
                f"the table says {table[name]['type']}")

        required = set(schema.get("required", [])) - {"forest"}
        table_required = {n for n, s in table.items() if s["required"]} & names
        assert table_required <= required, (
            f"{tool['name']}: the table requires {sorted(table_required)}, "
            f"the tool requires {sorted(required)}")
        checked += 1

    assert checked >= 10, f"only {checked} tools compared"
