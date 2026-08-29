# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The audit row and the audit route (spec J.4.2 + J.4.3, F.154 - F.156).

The log recorded who called what and answered `ok`. What it never recorded
was the three things anybody actually opens it for: what the call cost, which
refusal it was, and how long it took. The first of those is the strangest
absence — J.4 has said since v0.35 that a store hit is audited with "the cost
avoided, never a second spend", which is a sentence about a column that did
not exist.

The route is the other half. It took `limit` and `principal`, so every other
question was answered by whoever was reading, over whatever page they held —
and a count over a page is a fact about the page size. These tests put the
same request twice with different limits and demand the same totals.

Two properties are load-bearing and are checked directly rather than through
the console:

* **A store hit's cost is avoided, not spent.** Both numbers come off the
  same column and only `result` tells them apart, so a sum that forgot the
  split would bill a deployment for the calls it did not make.
* **Absent is not zero.** A row written before v0.73 makes no claim about its
  cost or its clock, and answering `0` on its behalf invents one.
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

MINE = "forest-mine"
THEIRS = "forest-theirs"
QUESTION = "architecture notes"


@pytest.fixture(scope="session")
def audit_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("audit")
    build_forest(root / MINE)
    build_forest(root / THEIRS)
    return root


@pytest.fixture()
def station(audit_root, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from monkeyllm_station import inference
    from monkeyllm_station.app import build_app

    # A provider that reports usage and publishes a price. Both halves
    # matter: `cost_of` needs the round trip's own token counts, and the
    # catalogue is what turns them into money. Without the catalogue the
    # call is "not priced", which is the other case under test.
    def fake_chat(binding, **_kw):
        def chat(messages):
            chat.usage["prompt"] += 100
            chat.usage["completion"] += 50
            chat.usage["calls"] += 1
            return "stub answer"
        chat.usage = {"prompt": 0, "completion": 0, "calls": 0}
        return chat, binding.get("model", "stub-model")

    def fake_probe(endpoint, api_key=None, **_kw):
        return {"models": [{"id": "stub-model", "prompt": 1e-5,
                            "completion": 2e-5}]}

    monkeypatch.setattr(inference, "chat_from_binding", fake_chat)
    monkeypatch.setattr(inference, "probe", fake_probe)
    # The answer store lives in the forest's own `_derived/`, and the forest
    # is session-scoped: without this, one test's entry is served to the
    # next one and "the second ask came from the store" stops being a fact
    # this file established.
    shutil.rmtree(audit_root / MINE / "_derived" / "cache", ignore_errors=True)
    monkeypatch.delenv("MONKEYLLM_STATION_ADMIN", raising=False)
    monkeypatch.delenv("MONKEYLLM_STATION_PASSWORD", raising=False)

    app = build_app(root=audit_root, registry_path=tmp_path / "station.db",
                    mcp=False)
    registry = app.state.registry
    registry.put_provider("p", "http://stub/v1", None)
    registry.bind_model(MINE, "answer", "p", "stub-model")
    with TestClient(app) as client:
        yield client, registry


def head_for(registry, principal, forests, caps=("read", "admin")):
    key = registry.issue_key(principal)
    for forest in forests:
        registry.grant(principal, forest, set(caps))
    return {"Authorization": f"Bearer {key}"}


def audit(client, head, **params):
    r = client.get("/v1/admin/audit", params=params, headers=head)
    assert r.status_code == 200, r.text
    return r.json()


def timing(response, clock: str) -> float | None:
    for part in (response.headers.get("Server-Timing") or "").split(","):
        name, _, tail = part.strip().partition(";")
        if name == clock and tail.startswith("dur="):
            return float(tail[4:])
    return None


# -- F.154: what a row carries ---------------------------------------------


def test_a_read_records_the_engines_own_clock(station):
    """`ms` is the Part D slice, not a second stopwatch: the row and the
    header of the same call must agree to the digit."""
    client, registry = station
    head = head_for(registry, "reader", [MINE])
    r = client.post(f"/v1/forests/{MINE}/look", json={"id": "_index"},
                    headers=head)
    assert r.status_code == 200

    row = registry.audit(limit=1, principal="reader")[0]
    assert row["primitive"] == "look"
    assert row["ms"] == timing(r, "vine")
    assert row["ms"] > 0
    # A `look` reaches no provider, so it makes no claim about money.
    assert row["usd"] is None and row["tokens"] is None
    assert row["priced"] is None and row["model_ms"] is None
    assert row["error_code"] is None


def test_a_refusal_records_its_code_and_never_its_message(station):
    """The code is a closed vocabulary; the message carries hints that name
    nodes and terms, and the audit log records access, not content (J.4)."""
    client, registry = station
    head = head_for(registry, "narrow", [MINE], caps=("read",))
    registry.grant("narrow", MINE, {"read"}, allow=["decisions/"])
    r = client.post(f"/v1/forests/{MINE}/look",
                    json={"id": "no-such-node-anywhere"}, headers=head)
    assert r.status_code == 404

    row = registry.audit(limit=1, principal="narrow")[0]
    assert row["result"] == "error"
    assert row["error_code"] == "E_NOT_FOUND"
    message = r.json()["error"]["message"]
    assert message not in str(dict(row)), "the message must not be stored"


def test_an_answer_records_what_the_provider_charged(station):
    """The bill is read off the response, never recomputed here."""
    client, registry = station
    head = head_for(registry, "asker", [MINE])
    r = client.post(f"/v1/forests/{MINE}/answer",
                    json={"question": QUESTION, "cache": False}, headers=head)
    assert r.status_code == 200, r.text
    cost = r.json().get("cost")
    assert cost and cost["priced"], "the stub catalogue prices this model"

    row = registry.audit(limit=1, principal="asker")[0]
    assert row["primitive"] == "answer"
    assert row["usd"] == cost["usd"]
    assert row["tokens"] == cost["prompt_tokens"] + cost["completion_tokens"]
    assert row["calls"] == cost["calls"]
    assert row["priced"] == 1
    # Two clocks, apart on purpose (J.10.4.1's reason).
    assert row["ms"] is not None and row["model_ms"] is not None


def test_a_row_written_before_the_upgrade_reads_as_absent(station):
    """`0.0 ms` and `$0.00` are claims. A row from an older Station makes
    neither, so the route must omit the fields rather than answer zero."""
    client, registry = station
    head = head_for(registry, "boss", [MINE])
    registry.conn.execute(
        "INSERT INTO audit (ts, principal, forest, primitive, args, result, size) "
        "VALUES ('2020-01-01T00:00:00+00:00', 'ancient', ?, 'look', '{}', 'ok', 12)",
        (MINE,))
    registry.conn.commit()

    entry = audit(client, head, principal="ancient")["entries"][0]
    for field in ("ms", "model_ms", "error_code", "usd", "tokens", "calls",
                  "priced"):
        assert field not in entry, f"{field} was invented for an old row"
    # The fields it always had are still there, unchanged.
    assert entry["primitive"] == "look" and entry["size"] == 12


# -- F.155: the totals describe the query ----------------------------------


def test_totals_describe_the_set_and_not_the_page(station):
    client, registry = station
    head = head_for(registry, "boss", [MINE])
    reader = head_for(registry, "busy", [MINE], caps=("read",))
    for _ in range(6):
        client.post(f"/v1/forests/{MINE}/look", json={"id": "_index"},
                    headers=reader)

    small = audit(client, head, limit=1)
    large = audit(client, head, limit=500)
    assert len(small["entries"]) == 1
    assert len(large["entries"]) > 1
    for field in ("calls", "errors", "cached", "usd", "usd_saved", "people"):
        assert small["totals"][field] == large["totals"][field], field
    assert small["totals"]["calls"] == len(large["entries"])


def test_a_store_hit_is_avoided_never_spent(station):
    """Both figures come off one column and only `result` separates them."""
    client, registry = station
    head = head_for(registry, "boss", [MINE])
    asker = head_for(registry, "twice", [MINE], caps=("read",))
    for _ in range(2):
        r = client.post(f"/v1/forests/{MINE}/answer", json={"question": QUESTION},
                        headers=asker)
        assert r.status_code == 200, r.text
    assert r.json().get("cached"), "the second ask must come from the store"

    totals = audit(client, head, principal="twice")["totals"]
    assert totals["cached"] == 1
    assert totals["usd"] > 0, "the run that paid is a spend"
    assert totals["usd_saved"] > 0, "the run that did not pay is a saving"
    rows = registry.audit(limit=10, principal="twice")
    paid = [r for r in rows if r["result"] == "ok"]
    assert totals["usd"] == pytest.approx(sum(r["usd"] for r in paid))


def test_every_filter_narrows_the_entries_and_the_totals(station):
    """A filter honoured on one and not the other is the bug this route was
    rebuilt to remove."""
    client, registry = station
    head = head_for(registry, "boss", [MINE])
    reader = head_for(registry, "mixed", [MINE], caps=("read",))
    for _ in range(3):
        client.post(f"/v1/forests/{MINE}/look", json={"id": "_index"},
                    headers=reader)
    client.post(f"/v1/forests/{MINE}/scan", json={"parent_id": "_index"},
                headers=reader)
    client.post(f"/v1/forests/{MINE}/look", json={"id": "nope"}, headers=reader)

    everything = audit(client, head, principal="mixed", limit=500)
    assert everything["totals"]["calls"] == len(everything["entries"])

    looks = audit(client, head, principal="mixed", primitive="look", limit=500)
    assert {e["primitive"] for e in looks["entries"]} == {"look"}
    assert looks["totals"]["calls"] == len(looks["entries"]) == 4

    refused = audit(client, head, principal="mixed", errors="1", limit=500)
    assert refused["totals"]["calls"] == 1
    assert refused["entries"][0]["error_code"] == "E_NOT_FOUND"

    # Narrowing, never widening: a filter can only ever shrink the set.
    assert looks["totals"]["calls"] <= everything["totals"]["calls"]


def test_an_unreadable_bound_is_refused_rather_than_dropped(station):
    """C.13's rule. A window silently ignored is a false statement about
    which calls were looked at."""
    client, registry = station
    head = head_for(registry, "boss", [MINE])
    r = client.get("/v1/admin/audit", params={"since": "last tuesday"},
                   headers=head)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "E_SCHEMA"


def test_a_window_narrows_and_says_what_it_covers(station):
    client, registry = station
    head = head_for(registry, "boss", [MINE])
    reader = head_for(registry, "dated", [MINE], caps=("read",))
    client.post(f"/v1/forests/{MINE}/look", json={"id": "_index"}, headers=reader)

    today = audit(client, head, principal="dated", since="2020-01-01")
    assert today["totals"]["calls"] == 1
    assert today["totals"]["first"] and today["totals"]["last"]

    long_ago = audit(client, head, principal="dated", until="2020-12-31")
    assert long_ago["totals"]["calls"] == 0
    assert long_ago["entries"] == []


# -- F.156: the scope decides first ----------------------------------------


def test_totals_stop_at_the_scope(station):
    """An administrator of one forest can no more COUNT the others than read
    them: a total is a finer size oracle than a page ever was."""
    client, registry = station
    theirs = head_for(registry, "stranger", [THEIRS], caps=("read",))
    for _ in range(4):
        client.post(f"/v1/forests/{THEIRS}/look", json={"id": "_index"},
                    headers=theirs)
    mine = head_for(registry, "ours", [MINE], caps=("read",))
    client.post(f"/v1/forests/{MINE}/look", json={"id": "_index"}, headers=mine)

    head = head_for(registry, "boss-of-mine", [MINE])
    body = audit(client, head, limit=500)
    assert {e["forest"] for e in body["entries"]} == {MINE}
    assert body["totals"]["calls"] == len(body["entries"])
    assert body["filters"]["forests"] == [MINE]
    assert "stranger" not in body["filters"]["principals"]
    assert THEIRS not in str(body)

    both = head_for(registry, "boss-of-both", [MINE, THEIRS])
    wide = audit(client, both, limit=500)
    assert wide["totals"]["calls"] > body["totals"]["calls"]
    assert set(wide["filters"]["forests"]) == {MINE, THEIRS}


def test_governance_rows_are_counted_for_the_owner_alone(station):
    """J.4.1 rule 3, applied to a sum: a placeholder row describes the whole
    deployment, and administering one forest is not a licence to count it."""
    client, registry = station
    registry.record(principal="somebody", forest="-", primitive="auth.login",
                    args={"username": "somebody"}, result="ok")

    head = head_for(registry, "boss", [MINE])
    body = audit(client, head, limit=500)
    assert "-" not in body["filters"]["forests"]
    assert all(e["forest"] != "-" for e in body["entries"])

    owner = head_for(registry, "chief", [MINE])
    registry.conn.execute("UPDATE principals SET owner = 1 WHERE id = ?",
                          ("chief",))
    registry.conn.commit()
    seen = audit(client, owner, limit=500)
    assert any(e["primitive"] == "auth.login" for e in seen["entries"])


def test_the_facets_only_narrow_by_scope_and_window(station):
    """Choosing a primitive must not empty the list of primitives (J.4.3):
    a filter that offers nothing teaches an operator the log is empty."""
    client, registry = station
    head = head_for(registry, "boss", [MINE])
    reader = head_for(registry, "varied", [MINE], caps=("read",))
    client.post(f"/v1/forests/{MINE}/look", json={"id": "_index"}, headers=reader)
    client.post(f"/v1/forests/{MINE}/scan", json={"parent_id": "_index"},
                headers=reader)

    body = audit(client, head, primitive="look", limit=500)
    assert {e["primitive"] for e in body["entries"]} == {"look"}
    assert {"look", "scan"} <= set(body["filters"]["primitives"])
