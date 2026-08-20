# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The leak suite (spec F.18): prefix scoping across every primitive.

The load-bearing test here is `test_no_primitive_leaks_any_out_of_scope_id`,
which does not check field by field. It walks the WHOLE response of every
primitive and asserts that no string anywhere in it is the id of a node the
principal may not see. Field-by-field assertions only catch the leaks you
thought of; this one catches the ones you did not — it is how `coverage`,
`stats.degree` and `scanned_nodes` were found.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

from monkeyllm_station.policy import Policy, ScopedVine  # noqa: E402

GRANT = "projects/"


@pytest.fixture(scope="session")
def all_ids(vine_ro) -> set[str]:
    return {r["id"] for r in vine_ro.catalog.conn.execute("SELECT id FROM nodes")}


@pytest.fixture()
def scoped(vine_ro):
    return ScopedVine(vine_ro, Policy(forest="f", caps=frozenset({"read", "query"}),
                                      allow=(GRANT,)))


def _strings(blob):
    """Every string anywhere in a JSON-ish structure."""
    if isinstance(blob, str):
        yield blob
    elif isinstance(blob, dict):
        for k, v in blob.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(blob, (list, tuple)):
        for item in blob:
            yield from _strings(item)


def _leaked(blob, all_ids: set[str], policy: Policy) -> set[str]:
    """Node ids present in the payload that the policy forbids.

    Bodies are author-written prose and may mention any id; `pick` is
    therefore checked on its own terms (a scoped principal cannot reach an
    out-of-scope body at all), not by this sweep.
    """
    found = set()
    for s in _strings(blob):
        candidate = s.strip()
        if candidate in all_ids and not policy.in_scope(candidate):
            found.add(candidate)
    return found


def test_no_primitive_leaks_any_out_of_scope_id(scoped, all_ids):
    policy = scoped.policy
    in_scope = sorted(i for i in all_ids if policy.in_scope(i))
    assert in_scope, "fixture must have nodes under the grant for this to mean anything"

    payloads = {
        "locate": scoped.locate("stigmergy monkey sales report", k=5),
        "locate_broad": scoped.locate("the", k=5),
        "sniff": scoped.sniff(["the"], k=5),
        "scan": scoped.scan(f"{GRANT}_index", recursive=True, limit=50),
        "harvest": scoped.harvest("stigmergy sales region", k=3),
        "look_branch": scoped.look(f"{GRANT}_index"),
        "look_node": scoped.look(in_scope[0]),
        "move": scoped.move(f"{GRANT}_index", rel="children"),
    }
    for name, payload in payloads.items():
        assert not _leaked(payload, all_ids, policy), f"{name} leaked out-of-scope ids"


def test_locate_only_returns_granted_nodes(scoped):
    hits = scoped.locate("stigmergy", k=5)["results"]
    assert all(h["id"].startswith(GRANT) for h in hits)


def test_out_of_scope_look_is_identical_to_absent(scoped, all_ids):
    """No existence oracle (J.3): 'you may not' must read exactly like
    'there is nothing there'."""
    hidden = next(i for i in sorted(all_ids) if not i.startswith(GRANT))
    from monkeyllm.errors import VineError

    with pytest.raises(VineError) as forbidden:
        scoped.look(hidden)
    with pytest.raises(VineError) as absent:
        scoped.look("projects/definitely-not-a-node")

    assert forbidden.value.code == absent.value.code == "E_NOT_FOUND"
    assert forbidden.value.to_dict()["error"]["hint"] == absent.value.to_dict()["error"]["hint"]
    # and the message differs only by the id the caller itself supplied
    assert forbidden.value.message == f"node not found: {hidden}"


def test_engine_and_scoped_not_found_texts_match(vine_ro, scoped, all_ids):
    """If the engine's own wording drifts, the disguise stops working — this
    test is the tripwire."""
    from monkeyllm.errors import VineError

    with pytest.raises(VineError) as engine:
        vine_ro.look("nope/not-here")
    with pytest.raises(VineError) as scoped_err:
        scoped.look("nope/not-here")
    assert engine.value.message == scoped_err.value.message
    assert engine.value.hint == scoped_err.value.hint


def test_move_omits_out_of_scope_neighbours(scoped, vine_ro, all_ids):
    policy = scoped.policy
    node = next(
        (i for i in sorted(all_ids)
         if i.startswith(GRANT)
         and any(not policy.in_scope(n["id"])
                 for n in vine_ro.move(i, direction="both")["neighbors"])),
        None,
    )
    assert node, "fixture must have a granted node with an out-of-scope neighbour"
    unscoped = vine_ro.move(node, direction="both")["neighbors"]
    scoped_neighbours = scoped.move(node, direction="both")["neighbors"]
    assert len(scoped_neighbours) < len(unscoped)
    assert all(policy.in_scope(n["id"]) for n in scoped_neighbours)


def test_branch_look_recomputes_coverage_and_degree(scoped, vine_ro):
    branch = f"{GRANT}_index"
    unscoped, scoped_digest = vine_ro.look(branch), scoped.look(branch)
    assert scoped_digest["stats"]["degree"] <= unscoped["stats"]["degree"]
    assert scoped_digest["stats"]["degree"] == (
        len(scoped_digest["edges_out"]) + len(scoped_digest["edges_in"])
    )
    if "coverage" in scoped_digest:
        branches = sum(1 for c in scoped_digest["children"] if c["id"].endswith("/_index"))
        bananas = len(scoped_digest["children"]) - branches
        assert scoped_digest["coverage"] == f"{bananas} bananas, {branches} sub-branches."


def test_sniff_scanned_nodes_is_not_a_size_oracle(scoped, vine_ro):
    """The engine counts every body it opened; a scoped caller must not learn
    how big the forest it cannot see is."""
    scoped_out = scoped.sniff(["the"], k=5)
    unscoped_out = vine_ro.sniff(["the"], k=5)
    assert scoped_out["scanned_nodes"] <= len(scoped_out["results"])
    assert scoped_out["scanned_nodes"] < unscoped_out["scanned_nodes"]


def test_master_index_is_not_implicitly_granted(scoped):
    from monkeyllm.errors import VineError

    with pytest.raises(VineError):
        scoped.look("_index")
    assert scoped.policy.roots() == [f"{GRANT}_index"]


def test_deny_wins_over_allow(vine_ro, all_ids):
    victim = next(i for i in sorted(all_ids) if i.startswith(GRANT) and not i.endswith("_index"))
    branch = victim.rsplit("/", 1)[0] + "/"
    policy = Policy(forest="f", caps=frozenset({"read"}), allow=(GRANT,), deny=(branch,))
    assert not policy.in_scope(victim)
    scoped = ScopedVine(vine_ro, policy)
    assert all(not h["id"].startswith(branch) for h in scoped.locate("the", k=5)["results"])


def test_prefix_boundary_is_not_substring_matching(vine_ro):
    """A grant on `projects/` must not swallow `projects-secret/`."""
    policy = Policy(forest="f", caps=frozenset({"read"}), allow=("projects",))
    assert policy.in_scope("projects/mixerllm/architecture")
    assert not policy.in_scope("projects-secret/plan")


def test_scoped_and_unscoped_share_response_shape(scoped, vine_ro):
    """No truncation oracle: a scoped answer must not be recognisable by its
    shape (J.3)."""
    assert set(scoped.locate("stigmergy", k=3)) == set(vine_ro.locate("stigmergy", k=3))
    assert set(scoped.sniff(["the"], k=3)) == set(vine_ro.sniff(["the"], k=3))
    branch = f"{GRANT}_index"
    assert set(scoped.look(branch)) == set(vine_ro.look(branch))


def test_overfetch_recovers_hits_a_naive_post_filter_would_lose(scoped, vine_ro):
    """Filtering the engine's already-cut top-k would hand a scoped caller
    whatever scraps happened to survive. Asking for headroom first is what
    makes scope cost recall only at the margins — and it is why a scoped
    answer looks like a full answer (J.3, no truncation oracle)."""
    query = "model"  # unscoped top-3 holds no projects/ node; the top-8 holds three
    naive = [h for h in vine_ro.locate(query, k=3)["results"] if h["id"].startswith(GRANT)]
    scoped_hits = scoped.locate(query, k=3)["results"]
    assert not naive, "fixture drifted: pick a query whose unscoped top-3 is all out of scope"
    assert len(scoped_hits) == 3
    assert all(h["id"].startswith(GRANT) for h in scoped_hits)


def test_pick_and_scan_gate_on_scope(scoped):
    from monkeyllm.errors import VineError

    with pytest.raises(VineError):
        scoped.pick("people/jimmy-wesley")
    with pytest.raises(VineError):
        scoped.scan("_index", recursive=True)


def test_query_table_allow_list(vine_ro):
    dataset = "sales/report-q1-2026"
    policy = Policy(forest="f", caps=frozenset({"read", "query"}),
                    allow=("sales/",), tables={dataset: ("nothing_here",)})
    scoped = ScopedVine(vine_ro, policy)
    denied = scoped.call("query", id=dataset, sql="SELECT * FROM sales LIMIT 1")
    assert denied["error"]["code"] == "E_FORBIDDEN"

    allowed = ScopedVine(vine_ro, Policy(forest="f", caps=frozenset({"read", "query"}),
                                         allow=("sales/",), tables={dataset: ("sales",)}))
    assert "rows" in allowed.call("query", id=dataset, sql="SELECT * FROM sales LIMIT 1")


DATASET = "sales/report-q1-2026"

# Five spellings of one statement. The first is the one a person writes; the
# rest are the ones somebody writes on purpose, and each was chosen because a
# name-matching regex reads it differently from SQLite: no space after FROM, a
# comment where the space goes, the forbidden table hidden in a subquery
# behind a permitted one, and a CTE. The point is not this list — it is that
# the list has no end while the control is textual, which is why the control
# is not textual any more.
EQUIVALENT_TO_SELECTING_FROM_SALES = [
    "SELECT * FROM sales LIMIT 1",
    "SELECT * FROM(sales) LIMIT 1",
    "SELECT * FROM/**/sales LIMIT 1",
    "SELECT (SELECT COUNT(*) FROM(sales)) AS leaked",
    "WITH c AS (SELECT * FROM(sales)) SELECT * FROM c",
]


@pytest.mark.parametrize("sql", EQUIVALENT_TO_SELECTING_FROM_SALES)
def test_the_table_scope_is_decided_by_sqlite(vine_ro, sql):
    """C.5/J.3 say the allow-list is checked against the *parsed* statement.

    Reading table names out of SQL text is a second parser, and it disagrees
    with the real one wherever nobody looked. SQLite's authorizer is asked
    once per table the statement actually touches, so every spelling of the
    same read is the same answer.
    """
    scoped = ScopedVine(vine_ro, Policy(
        forest="f", caps=frozenset({"read", "query"}),
        allow=("sales/",), tables={DATASET: ("nothing_here",)}))
    out = scoped.call("query", id=DATASET, sql=sql)
    assert out["error"]["code"] in ("E_FORBIDDEN", "E_QUERY_FORBIDDEN"), sql
    assert "rows" not in out, sql


def test_the_scope_does_not_narrow_what_it_was_not_asked_to(vine_ro):
    """The refusals above must not be the primitive simply refusing: a
    permitted table still reads, including through the same unusual syntax."""
    scoped = ScopedVine(vine_ro, Policy(
        forest="f", caps=frozenset({"read", "query"}),
        allow=("sales/",), tables={DATASET: ("sales",)}))
    assert "rows" in scoped.call("query", id=DATASET, sql="SELECT * FROM sales LIMIT 1")
    assert "rows" in scoped.call("query", id=DATASET, sql="SELECT * FROM(sales) LIMIT 1")
    # And an ungoverned principal keeps the whole dataset.
    whole = ScopedVine(vine_ro, Policy(forest="f", caps=frozenset({"read", "query"}),
                                       allow=("sales/",)))
    assert "rows" in whole.call("query", id=DATASET, sql="SELECT * FROM sales LIMIT 1")


def test_the_not_found_hint_does_not_name_what_is_withheld(vine_ro):
    """Under a table scope, the hint names only permitted tables. An
    inventory of everything in the file is, to a caller who may read part of
    it, a list of what is being withheld — and a misspelling is not a reason
    to hand that over."""
    scoped = ScopedVine(vine_ro, Policy(
        forest="f", caps=frozenset({"read", "query"}),
        allow=("sales/",), tables={DATASET: ("nothing_here",)}))
    out = scoped.call("query", id=DATASET, sql="SELECT * FROM no_such_table_here")
    assert "sales" not in json.dumps(out)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM pragma_database_list",
    "SELECT * FROM pragma_table_list",
    "SELECT * FROM pragma_table_info('sales')",
])
def test_the_pragma_functions_are_refused(vine_ro, sql):
    """The keyword and the `pragma_*` functions are separate syntax and both
    are refused. The read-only connection stops what changes state; these
    describe instead — the schema, and where the payload sits — and neither
    is the caller's to read."""
    scoped = ScopedVine(vine_ro, Policy(forest="f", caps=frozenset({"read", "query"}),
                                        allow=("sales/",)))
    out = scoped.call("query", id=DATASET, sql=sql)
    assert out["error"]["code"] in ("E_FORBIDDEN", "E_QUERY_FORBIDDEN"), sql


def test_write_outside_grant_is_forbidden_not_notfound(vine_ro):
    """The caller supplied the id, so refusing plainly discloses nothing."""
    scoped = ScopedVine(vine_ro, Policy(forest="f", caps=frozenset({"write"}), allow=(GRANT,)))
    out = scoped.call("plant", node={"id": "people/intruder", "type": "note",
                                     "title": "x", "summary": "y"})
    assert out["error"]["code"] == "E_FORBIDDEN"
