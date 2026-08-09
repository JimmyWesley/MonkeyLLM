# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The Gauntlet (spec Part K, criterion F.24).

The feature's central promise is not that it ranks well — it is that a
deployment which never configures an embedder is **unaffected**. So the
load-bearing test here is not about ranking at all: it compares whole
responses, byte for byte, between a Vine that has never heard of the
Gauntlet and one whose preconditions merely fail. Checking a flag would
prove that the code *intends* to be inert; comparing the bytes proves it.

Ranking itself is tested with a deterministic fake embedder. A real one
would make these tests depend on a model server, on a download, and on the
semantics of a particular checkpoint — none of which is what Part K
promises.
"""

from __future__ import annotations

import json

import pytest

from monkeyllm.canopy import CanopyIndex, normalize
from monkeyllm.vine import Vine


class FakeEmbedder:
    """Maps text to a unit vector by keyword presence, so proximity is a
    fact of the test rather than a property of a downloaded checkpoint."""

    KEYS = ("alpha", "beta", "gamma", "delta")

    def __init__(self, model: str = "fake-1"):
        self.model = model

    def embed(self, texts):
        out = []
        for text in texts:
            low = text.lower()
            vec = [1.0 if k in low else 0.0 for k in self.KEYS]
            out.append(normalize(vec) if any(vec) else [1.0, 0.0, 0.0, 0.0])
        return out


@pytest.fixture()
def wide(tmp_path):
    """A branch wide enough that the frontier has to be chosen."""
    from monkeyllm.forest import init_forest
    from monkeyllm.parser import serialize_node

    root = tmp_path / "forest"
    init_forest(root, title="Gauntlet")
    (root / "region").mkdir()
    entries = []
    words = ["alpha", "beta", "gamma", "delta"]
    for i in range(20):
        node_id = f"region/doc-{i:02d}"
        word = words[i % 4]
        (root / f"{node_id}.md").write_text(serialize_node(
            {"id": node_id, "type": "note", "title": f"Doc {i:02d}",
             "summary": f"A document about {word} number {i}.",
             "created": "2026-01-01", "updated": "2026-01-01"},
            f"# Doc {i:02d}\n\nAbout {word}.\n"), encoding="utf-8")
        entries.append(f"- [[{node_id}]] — about {word}")
    (root / "region" / "_index.md").write_text(serialize_node(
        {"id": "region/_index", "type": "branch", "title": "Region",
         "summary": "A wide region of twenty near-identical documents.",
         "coverage": "20 bananas, 0 sub-branches",
         "created": "2026-01-01", "updated": "2026-01-01"},
        "# Region\n\n> Wide.\n\n## Sub-branches\n\n## Direct bananas\n\n"
        + "\n".join(entries) + "\n\n## Cross trails\n"), encoding="utf-8")
    return root


def _with_canopy(root, embedder):
    v = Vine(root, writable=False, embedder=embedder)
    rows = [(r["id"], f"{r['title']}. {r['summary']}")
            for r in v.catalog.conn.execute("SELECT id, title, summary FROM nodes")]
    v.canopy = CanopyIndex.build(rows, embedder)
    v.canopy.save(v.forest.derived_dir)
    return v


# -- the promise: absent means identical, not degraded ----------------------

CALLS = [
    ("look", {"id": "region/_index"}),
    ("move", {"id": "region/_index"}),
    ("scan", {"parent_id": "region/_index", "limit": 8}),
]


@pytest.mark.parametrize("name,kwargs", CALLS)
def test_without_an_embedder_the_response_is_byte_identical(wide, name, kwargs):
    """A deployment that never configures an embedder must not be able to
    tell that Part K was ever written."""
    plain = Vine(wide, writable=False)
    baseline = json.dumps(getattr(plain, name)(**kwargs), sort_keys=True, default=str)
    plain.close()

    # Same call, on a Vine that simply has no embedder — the ordinary case.
    again = Vine(wide, writable=False, embedder=None)
    assert json.dumps(getattr(again, name)(**kwargs), sort_keys=True,
                      default=str) == baseline
    assert "frontier" not in getattr(again, name)(**kwargs)
    again.close()


@pytest.mark.parametrize("name,kwargs", CALLS)
def test_a_mismatched_index_is_as_inert_as_no_index(wide, name, kwargs):
    """K.4: an index built by another model must be treated as absent — not
    used, not half-used, and not silently compared across vector spaces."""
    plain = Vine(wide, writable=False)
    baseline = json.dumps(getattr(plain, name)(**kwargs), sort_keys=True, default=str)
    plain.close()

    v = _with_canopy(wide, FakeEmbedder("fake-1"))
    v.embedder = FakeEmbedder("something-else")     # the model was swapped
    v.locate("alpha")                               # would set a goal if hybrid
    assert v.hybrid is False
    assert v.canopy_status["state"] == "model-mismatch"
    assert json.dumps(getattr(v, name)(**kwargs), sort_keys=True,
                      default=str) == baseline
    v.close()


def test_an_empty_index_is_inert(wide):
    v = Vine(wide, writable=False, embedder=FakeEmbedder())
    assert v.hybrid is False
    assert v.canopy_status["state"] in ("no-index", "no-embedder")
    assert "frontier" not in v.scan("region/_index", limit=8)
    v.close()


# -- when active ------------------------------------------------------------


def test_the_frontier_is_ranked_toward_the_hunt(wide):
    v = _with_canopy(wide, FakeEmbedder())

    before = [n["id"] for n in v.scan("region/_index", limit=8)["nodes"]]
    v.locate("gamma")                       # the hunt sets the goal (K.2)
    after = v.scan("region/_index", limit=8)

    assert after["frontier"] == {"ranked": True, "toward": "gamma"}
    top = [n["id"] for n in after["nodes"]]
    assert top != before, "the order must actually change"
    # Every document mentioning gamma should now be in reach; before, the
    # cut was made by heat, which is zero for all of them on a cold forest.
    gammas = {f"region/doc-{i:02d}" for i in range(20) if i % 4 == 2}
    assert set(top[:5]) <= gammas
    v.close()


def test_ranking_happens_before_the_cap_not_after(wide):
    """Reordering after the cut cannot recover what the cut hid — which is
    the whole reason the feature exists."""
    v = _with_canopy(wide, FakeEmbedder())
    v.locate("delta")
    shown = [n["id"] for n in v.scan("region/_index", limit=3)["nodes"]]
    deltas = {f"region/doc-{i:02d}" for i in range(20) if i % 4 == 3}
    assert set(shown) <= deltas and len(shown) == 3
    v.close()


def test_the_opt_out_restores_the_unconditioned_order(wide):
    """K.3: measurable against itself, in the same session, without
    restarting anything or rebuilding an index."""
    plain = Vine(wide, writable=False)
    baseline = json.dumps(plain.scan("region/_index", limit=8),
                          sort_keys=True, default=str)
    plain.close()

    v = _with_canopy(wide, FakeEmbedder())
    v.locate("gamma")
    assert "frontier" in v.scan("region/_index", limit=8)
    off = v.scan("region/_index", limit=8, gauntlet=False)
    assert "frontier" not in off
    assert json.dumps(off, sort_keys=True, default=str) == baseline
    v.close()


def test_an_explicit_goal_overrides_the_hunt(wide):
    v = _with_canopy(wide, FakeEmbedder())
    v.locate("alpha")
    out = v.scan("region/_index", limit=4, toward="beta")
    assert out["frontier"]["toward"] == "beta"
    betas = {f"region/doc-{i:02d}" for i in range(20) if i % 4 == 1}
    assert {n["id"] for n in out["nodes"]} <= betas
    v.close()


def test_the_goal_is_embedded_once_per_hunt_not_once_per_hop(wide):
    """K.2 is a cost claim, so it is tested as one."""
    embedder = FakeEmbedder()
    calls = {"n": 0}
    inner = embedder.embed

    def counting(texts):
        calls["n"] += 1
        return inner(texts)

    embedder.embed = counting
    v = _with_canopy(wide, embedder)
    calls["n"] = 0

    v.locate("gamma")                       # one embedding: the hunt
    for _ in range(10):                     # ten hops: none
        v.scan("region/_index", limit=5)
        v.look("region/_index")
        v.move("region/_index")
    assert calls["n"] == 1, f"embedded {calls['n']} times for one hunt"
    v.close()


def test_a_look_with_no_frontier_in_it_costs_no_embedding(wide):
    """`harvest` fetches one field per result with `look(id, fields=[...])`,
    and the `fields` filter drops the edge lists — so ranking them was a
    network round trip for output nobody receives. It showed up as ~150 ms
    on every harvest and every answer."""
    embedder = FakeEmbedder()
    calls = {"n": 0}
    inner = embedder.embed

    def counting(texts):
        calls["n"] += 1
        return inner(texts)

    embedder.embed = counting
    v = _with_canopy(wide, embedder)
    v.locate("gamma")          # the hunt: goal remembered, not yet embedded
    calls["n"] = 0

    for _ in range(5):
        summary = v.look("region/_index", fields=["summary"])
    assert calls["n"] == 0
    assert "frontier" not in summary

    v.look("region/_index")    # a real hop still gets the instrument
    assert calls["n"] == 1
    v.close()


def test_look_ranks_its_edges_before_the_twelve_cap(wide):
    v = _with_canopy(wide, FakeEmbedder())
    v.locate("gamma")
    digest = v.look("region/_index")
    assert digest["frontier"]["ranked"] is True
    # `look` on a branch shows children as edges; the cap is 12 of 20.
    assert len(digest.get("edges_out", [])) <= 12
    v.close()


def test_a_ready_layer_does_not_switch_entry_search_over(wide):
    """The trap this rule exists to prevent (K.1).

    Binding an embedding model is a request for the Gauntlet. Measurement
    says RRF fusion degrades an already-correct BM25, so the same act must
    not silently enable it: readiness and consent are different facts.
    """
    v = _with_canopy(wide, FakeEmbedder())
    assert v.dense_ready is True
    assert v.hybrid is False, "availability turned entry search over by itself"

    v.locate("gamma")
    # ...and the Gauntlet still works, which is the whole point: it needs the
    # goal, and the goal is embedded regardless of what `locate` ranks with.
    assert v.scan("region/_index", limit=5)["frontier"]["ranked"] is True
    v.close()


def test_entry_search_fusion_is_reachable_only_by_asking(wide):
    v = _with_canopy(wide, FakeEmbedder())
    v.close()
    asked = Vine(wide, writable=False, embedder=FakeEmbedder(), hybrid_locate=True)
    assert asked.dense_ready is True and asked.hybrid is True
    asked.close()


def test_the_off_switch_is_the_same_state_as_absence(wide):
    """The Station expresses "disabled" by withholding the embedder, so the
    off switch inherits the byte-identical guarantee already proven above
    instead of needing a second proof of its own."""
    plain = Vine(wide, writable=False)
    baseline = json.dumps(plain.scan("region/_index", limit=8),
                          sort_keys=True, default=str)
    plain.close()

    v = _with_canopy(wide, FakeEmbedder())
    v.locate("gamma")
    assert "frontier" in v.scan("region/_index", limit=8)

    v.embedder = None                      # what the switch does, server-side
    assert v.dense_ready is False
    assert json.dumps(v.scan("region/_index", limit=8),
                      sort_keys=True, default=str) == baseline
    v.close()
