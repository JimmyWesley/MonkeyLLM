# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""What a read says about itself (spec C.1.1, C.6b, C.6c, C.11 — criteria
F.56, F.57, F.58, F.59).

These are the engine halves of the v0.52 release. Every one of them exists
because a live agent reading a served forest could not tell two situations
apart, and the two demanded opposite next moves:

* `locate` returning `[]` on a subject the forest has eight paragraphs
  about, because none of them reached a summary. The model that reads that
  as "the forest does not know" answers from its own parameters — the one
  failure this project exists to prevent.
* An auto-generated index outranking the note it points at, because heat
  was the only term separating them.
* `421` and `MCP` dropped from a question on the way in, because they are
  short — which is also why they are the tokens worth searching for.
"""

from __future__ import annotations

import math

import pytest

from monkeyllm.errors import VineError
from monkeyllm.harvest import derive_terms
from monkeyllm.vine import BUDGET_LOOK_BATCH, SNIFF_DENSITY_BETA


# --- C.1.1 / F.56: the entry list says what it looked at ---------------------

def test_every_result_carries_the_size_of_what_it_offers(vine_ro):
    out = vine_ro.locate("stigmergy", k=3)
    assert out["results"]
    for hit in out["results"]:
        assert hit["body_tokens"] == vine_ro.look(hit["id"], fields=["stats"])["stats"]["body_tokens"]


def test_include_outline_adds_the_sections_pick_takes(vine_ro):
    plain = vine_ro.locate("pheromone", k=3)
    with_outline = vine_ro.locate("pheromone", k=3, include=["outline"])
    assert all("outline" not in h for h in plain["results"])
    assert all("outline" in h for h in with_outline["results"])
    first = with_outline["results"][0]
    if first["outline"]:
        # What locate handed over is what pick answers to.
        section = first["outline"][0]
        assert vine_ro.pick(first["id"], section=section)["section"] == section


def test_include_refuses_a_field_it_does_not_have(vine_ro):
    with pytest.raises(VineError) as caught:
        vine_ro.locate("pheromone", include=["body"])
    assert caught.value.code == "E_SCHEMA"


def test_an_empty_entry_list_says_how_much_it_searched(vine_ro):
    out = vine_ro.locate("zzqqx-nothing-in-this-forest", k=5)
    assert out["results"] == []
    assert out["searched"] == vine_ro.catalog.count_nodes()
    assert "sniff" in out["hint"]
    # The hint is about the surface, never about the content (C.1.1).
    assert "zzqqx" not in out["hint"]


def test_a_result_carries_no_coverage_and_no_hint(vine_ro):
    """The count answers "is there anything here at all"; a non-empty list
    answers it better, and paying for it on every call would put a table
    scan inside the primitive with the tightest budget."""
    out = vine_ro.locate("stigmergy", k=3)
    assert "searched" not in out and "hint" not in out


def test_the_split_with_sniff_is_unchanged(vine_ro):
    """C.1.1 changes what an empty answer SAYS, never what locate searches."""
    body_only = vine_ro.sniff(["p95"], k=5)
    assert len(body_only["results"]) > len(vine_ro.locate("p95", k=5)["results"])


# --- C.11 / F.57: a batch is one call ---------------------------------------

def test_a_list_of_ids_answers_one_accounted_for_batch(vine_ro):
    ids = ["concepts/stigmergy", "concepts/aco", "concepts/rrf"]
    out = vine_ro.look(ids)
    assert [n["id"] for n in out["nodes"]] == ids  # the caller's order
    assert out["missing"] == [] and out["dropped"] == []
    assert out["truncated"] is False


def test_a_batch_accounts_for_every_id_it_was_given(vine_ro):
    ids = ["concepts/stigmergy", "concepts/not-a-real-node", "concepts/aco"]
    out = vine_ro.look(ids)
    seen = {n["id"] for n in out["nodes"]} | set(out["missing"]) | set(out["dropped"])
    assert seen == set(ids)
    assert out["missing"] == ["concepts/not-a-real-node"]


def test_one_bad_id_does_not_cost_the_others(vine_ro):
    out = vine_ro.look(["concepts/nope", "concepts/stigmergy"])
    assert [n["id"] for n in out["nodes"]] == ["concepts/stigmergy"]


def test_a_single_id_keeps_the_single_shape(vine_ro):
    digest = vine_ro.look("concepts/stigmergy")
    assert "nodes" not in digest and digest["id"] == "concepts/stigmergy"
    body = vine_ro.pick("concepts/stigmergy")
    assert "nodes" not in body and "body" in body


def test_a_one_element_list_is_still_a_list(vine_ro):
    """The shape follows the request: a client that built a list must not
    have to branch on how many ids it happened to hold."""
    out = vine_ro.look(["concepts/stigmergy"])
    assert [n["id"] for n in out["nodes"]] == ["concepts/stigmergy"]


def test_duplicates_collapse_keeping_the_first_position(vine_ro):
    out = vine_ro.look(["concepts/aco", "concepts/stigmergy", "concepts/aco"])
    assert [n["id"] for n in out["nodes"]] == ["concepts/aco", "concepts/stigmergy"]


def test_a_batch_is_sized_by_one_budget(vine_ro):
    from monkeyllm.tokens import estimate_payload_tokens

    ids = [r["id"] for r in vine_ro.catalog.conn.execute(
        "SELECT id FROM nodes WHERE kind='branch' ORDER BY id LIMIT 10")]
    out = vine_ro.look(ids)
    assert estimate_payload_tokens(out) <= BUDGET_LOOK_BATCH
    if out["truncated"]:
        # Whole items leave, from the tail, and are NAMED.
        assert out["dropped"] and out["dropped"][-1] == ids[-1]
        assert set(out["dropped"]) & set(ids) == set(out["dropped"])


def test_pick_shares_one_body_budget_and_never_slices(vine_ro):
    from monkeyllm.vine import BUDGET_PICK_BATCH
    from monkeyllm.tokens import estimate_payload_tokens

    ids = [r["id"] for r in vine_ro.catalog.conn.execute(
        "SELECT id FROM nodes WHERE kind='banana' ORDER BY body_tokens DESC LIMIT 5")]
    out = vine_ro.pick(ids)
    assert estimate_payload_tokens(out) <= BUDGET_PICK_BATCH
    for node in out["nodes"]:
        # A body that was kept was kept whole (pick's own outline fallback
        # for a huge body is not a slice — it is pick's documented answer).
        assert "body" in node or node.get("outline")


def test_a_batch_over_the_cap_is_refused_naming_it(vine_ro):
    with pytest.raises(VineError) as caught:
        vine_ro.look([f"concepts/x{i}" for i in range(11)])
    assert caught.value.code == "E_SCHEMA" and "10" in caught.value.message
    with pytest.raises(VineError):
        vine_ro.pick([f"concepts/x{i}" for i in range(6)])


def test_an_empty_batch_is_a_caller_with_a_bug(vine_ro):
    with pytest.raises(VineError) as caught:
        vine_ro.look([])
    assert caught.value.code == "E_SCHEMA"


def test_a_missing_section_is_not_a_missing_node(vine_ro):
    """Burying it in `missing` would report a node the caller can see as
    absent — and the caller would go looking for the wrong mistake."""
    with pytest.raises(VineError) as caught:
        vine_ro.pick(["concepts/stigmergy"], section="No Such Header")
    assert caught.value.code == "E_NOT_FOUND" and "section" in caught.value.message


# --- C.6b / F.58: a pointer never outranks what it points at ----------------

def test_an_index_ranks_below_content_however_hot_it_is(vine_rw):
    vine_rw.trails.add_heat(["concepts/_index"], amount=0.9)
    out = vine_rw.sniff(["stigmergy"], k=6)
    ids = [h["id"] for h in out["results"]]
    indexes = [i for i, nid in enumerate(ids) if nid.endswith("_index")]
    content = [i for i, nid in enumerate(ids) if not nid.endswith("_index")]
    assert indexes and content, ids
    assert min(indexes) > max(content), ids
    # The score is reported unadjusted: the demotion is in the order, and a
    # number bent to force a position would be a number that lies.
    hottest = next(h for h in out["results"] if h["id"] == "concepts/_index")
    assert hottest["score"] > out["results"][0]["score"]


def test_occurrences_are_part_of_the_score(vine_ro):
    out = vine_ro.sniff(["pheromone", "heat"], k=5)
    two = next(h for h in out["results"] if h["match_count"] == 2)
    one = next(h for h in out["results"]
               if h["match_count"] == 1 and h["score"] < two["score"])
    assert two["score"] > one["score"]
    assert two["score"] == pytest.approx(
        round(1.0 * (1 + SNIFF_DENSITY_BETA * math.log2(2)), 4))


def test_heat_still_decides_between_equals(vine_rw):
    """Density did not replace the pheromone: between two bodies holding the
    same term the same number of times, the trail somebody wore still wins."""
    vine_rw.trails.add_heat(["notes/recommended-readings"], amount=0.8)
    out = vine_rw.sniff(["stigmergy"], k=8)
    hits = {h["id"]: h for h in out["results"] if not h["id"].endswith("_index")}
    warm, cold = hits["notes/recommended-readings"], hits["concepts/stigmergy"]
    assert warm["match_count"] == cold["match_count"]
    assert warm["score"] > cold["score"]
    assert list(hits)[0] == "notes/recommended-readings"


# --- C.6c / F.59: short is not the same as noise ----------------------------

@pytest.mark.parametrize("query,kept,dropped", [
    ("how do I fix the 421 from MCP", {"421", "MCP"}, {"fix", "the"}),
    ("como corrigir o 421 do MCP", {"421", "MCP"}, {"como", "do"}),
    ("what does RAG mean for p95 latency", {"RAG", "p95"}, {"for"}),
    ("rotate the x-api-key", {"x-api-key"}, {"the"}),
    ("JWT and SSO", {"JWT", "SSO"}, {"and"}),
])
def test_code_shaped_tokens_survive_the_length_floor(query, kept, dropped):
    terms = set(derive_terms(query))
    assert kept <= terms
    assert not (dropped & terms)


def test_code_shaped_tokens_are_kept_when_the_cap_bites():
    query = ("investigate whether the 421 refusal from MCP relates to "
             "allowed hosts configuration during deployment rollout again")
    terms = derive_terms(query)
    assert len(terms) == 8
    assert terms[:2] == ["421", "MCP"]


def test_an_empty_sweep_says_what_it_swept(vine_ro):
    from monkeyllm.harvest import harvest

    out = harvest(vine_ro, "zzqqx yyzzw qqxxz")
    assert out["results"] == []
    assert out["searched"] >= 1
    assert "terms" in out and "hint" in out


def test_a_sweep_that_found_something_says_neither(vine_ro):
    from monkeyllm.harvest import harvest

    out = harvest(vine_ro, "stigmergy pheromone", k=2)
    assert out["results"] and "hint" not in out
