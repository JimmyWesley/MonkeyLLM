# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The gauntlet rides inside the forest's clock (Part D + K.2, v0.68, F.143).

The embedder is the one provider on the read path, and it runs inside
whichever traced primitive needed the query vector — so without a named
share its round trip is billed to `locate`, or to the hop that embedded
the goal, and the panel indicts a forest that did forty milliseconds of
work for the provider's eight seconds. These tests pin the share to the
event that paid it, and pin every other event to v0.67's bytes.
"""

from __future__ import annotations

import time

from monkeyllm.canopy import CanopyIndex
from monkeyllm.vine import Vine

from test_gauntlet import FakeEmbedder, wide  # noqa: F401  (pytest fixture)


class SlowEmbedder(FakeEmbedder):
    """A round trip long enough to dwarf the memo lookup beside it, so the
    two are distinguishable on a busy machine without a network."""

    DELAY = 0.1

    def embed(self, texts):
        time.sleep(self.DELAY)
        return super().embed(texts)


def _with_canopy(root, embedder, **kw):
    v = Vine(root, writable=False, embedder=embedder, **kw)
    rows = [(r["id"], f"{r['title']}. {r['summary']}")
            for r in v.catalog.conn.execute("SELECT id, title, summary FROM nodes")]
    v.canopy = CanopyIndex.build(rows, embedder)
    return v


def test_a_hybrid_locate_names_the_embedders_share(wide):
    v = _with_canopy(wide, SlowEmbedder(), hybrid_locate=True)
    v.locate("alpha")
    ev = v.tracer.events[-1]
    assert ev["primitive"] == "locate"
    assert ev["embed_ms"] >= SlowEmbedder.DELAY * 1000
    # The whole span is still the whole span: the share subdivides it,
    # never shrinks it.
    assert ev["elapsed_ms"] >= ev["embed_ms"]
    v.close()


def test_a_call_that_ran_no_embed_emits_the_v067_event(wide):
    v = Vine(wide, writable=False)
    v.locate("alpha")
    assert "embed_ms" not in v.tracer.events[-1]
    v.close()


def test_the_lazy_goal_bills_the_hop_that_paid_it(wide):
    """K.2 defers the goal to the first hop that needs it, so that is the
    event that must carry the share — a `locate` reporting a cost it
    deferred would be the original misattribution with the sign flipped."""
    v = _with_canopy(wide, SlowEmbedder())      # gauntlet ready, hybrid off
    v.locate("alpha")                           # goal remembered, not embedded
    assert "embed_ms" not in v.tracer.events[-1]
    v.look("region/_index")                     # the first real hop pays
    ev = v.tracer.events[-1]
    assert ev["primitive"] == "look"
    assert ev["embed_ms"] >= SlowEmbedder.DELAY * 1000
    v.close()


def test_a_memo_hit_still_carries_the_share_near_zero(wide):
    """A hit's near-zero is the memo working (K.6) — and it is also why
    the original figure never reproduced on the retry meant to confirm it,
    so the field is present, small, rather than absent."""
    v = _with_canopy(wide, SlowEmbedder(), hybrid_locate=True)
    v.locate("alpha")
    v.locate("alpha")
    ev = v.tracer.events[-1]
    assert "embed_ms" in ev
    assert ev["embed_ms"] < SlowEmbedder.DELAY * 1000
    v.close()
