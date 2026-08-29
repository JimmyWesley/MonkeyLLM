# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""A request body is an object, or it is a refusal (spec C.12).

Every admin route reads its arguments with `body.get(...)`, and none of them
checked that `request.json()` had returned a mapping. A body that parses as
a bare string reached that call as a `str` and raised `AttributeError`,
which the `Exception` handler dressed as `E_INTERNAL`/500 — telling the
caller "this is a defect on the server, not in your call" about a request
they had malformed.

The way it actually happened is worth writing down, because it is not
exotic: `apps/studio/src/api.js` stringifies the body inside `request()`,
and two call sites added in the v0.61 batch (`recurate`, `clearStaging`)
passed an ALREADY stringified body. JSON encoded twice parses back to a
string. Both buttons answered 500 on every press; `reindex`, written for
v0.41 and sitting on the next line, passes the object and always worked.

So this file has two halves, because the bug had two:

* the server must refuse a non-object body with `E_SCHEMA`, whoever sent it;
* the console must not send one — checked by reading the source, the same
  trick `test_studio_calls` and `test_studio_i18n` use, for the same reason
  (the console is JavaScript and CI has no node).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from conftest import build_forest

REPO = Path(__file__).resolve().parents[1]
STATION = REPO / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

API_JS = REPO / "apps" / "studio" / "src" / "api.js"
FOREST = "forest-fixture"


@pytest.fixture()
def station(tmp_path):
    from starlette.testclient import TestClient

    from monkeyllm_station.app import build_app

    root = tmp_path / "root"
    build_forest(root / FOREST)
    app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=False)
    with TestClient(app) as client:
        registry = app.state.registry
        key = registry.issue_key("boss")
        registry.grant("boss", FOREST, {"read", "write", "admin"})
        yield client, key


# ------------------------------------------------------------------ server
# The routes that take a body and are reachable with an admin grant. Each is
# asked the same wrong question.
BODY_ROUTES = ["/v1/admin/recurate", "/v1/admin/staging", "/v1/admin/reindex"]

# Every shape that is valid JSON and is not an object. The first is what a
# double `JSON.stringify` produces and is the one that shipped.
NOT_OBJECTS = ['"{\\"forest\\": \\"forest-fixture\\"}"', '"forest-fixture"',
               "[1, 2]", "42", "true"]


@pytest.mark.parametrize("route", BODY_ROUTES)
@pytest.mark.parametrize("payload", NOT_OBJECTS, ids=range(len(NOT_OBJECTS)))
def test_a_non_object_body_is_e_schema(station, route, payload):
    """Not a 500. The caller sent the wrong shape and gets told so."""
    client, key = station
    r = client.post(route, headers={"Authorization": f"Bearer {key}",
                                    "Content-Type": "application/json"},
                    content=payload)
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "E_SCHEMA"
    # The refusal names what arrived: an operator reading it must be able to
    # tell this from "the forest does not exist".
    assert "object" in err["message"]


@pytest.mark.parametrize("route", BODY_ROUTES)
def test_an_object_body_still_works(station, route):
    """The guard refuses a shape, never a request. These are the same calls
    the console makes, and they must be untouched by the check above."""
    client, key = station
    r = client.post(route, headers={"Authorization": f"Bearer {key}",
                                    "Content-Type": "application/json"},
                    json={"forest": FOREST})
    assert r.status_code == 200, r.text
    assert "error" not in r.json()


def test_an_absent_body_still_works(station):
    """`?forest=` in the query with no body at all — the other legal shape."""
    client, key = station
    r = client.post(f"/v1/admin/reindex?forest={FOREST}",
                    headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text


def test_a_vine_error_keeps_its_own_status(station):
    """The handler that makes the guard reachable: before it, the only
    registered handler was `Exception`, so a refusal raised outside a
    route's own try/except was re-labelled 500."""
    client, key = station
    r = client.post("/v1/admin/reindex",
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"},
                    content='"not an object"')
    assert r.status_code != 500
    assert r.json()["error"]["code"] == "E_SCHEMA"


# ------------------------------------------------------------------ client
def test_the_console_never_stringifies_a_body_twice():
    """`request()` stringifies. A call site that does it too sends JSON of
    JSON, which the server reads back as a string.

    Read as text on purpose: this is the only harness that sees the console,
    and the failure it guards against is invisible to every Python test of
    the wire contract — those send the right shape.
    """
    source = API_JS.read_text(encoding="utf-8")
    helper = re.search(r"async function request\(.*?\n}", source, re.S)
    assert helper, "api.js no longer has the request() helper this reads"
    assert "JSON.stringify(body)" in helper.group(0), (
        "request() no longer stringifies; this check's premise is stale")

    offenders = [
        line.strip()
        for line in source.splitlines()
        if "body: JSON.stringify" in line
        and "JSON.stringify(body)" not in line  # the helper's own line
    ]
    assert not offenders, (
        "these call sites encode the body twice; pass the object:\n  "
        + "\n  ".join(offenders))
