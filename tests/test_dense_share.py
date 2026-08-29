# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The dense layer's two clocks (spec J.10.4.1, F.149-F.150).

v0.68 found a provider round trip inside `locate`'s span and named it
`embed_ms`. That was half the bill. On a corpus of 1,877 nodes the SAME
query asked twice shows the other half: the embed becomes a K.6 memo hit
worth 0.13 ms and 74 ms is still charged to `locate`. It is the Canopy
scan — 68 ms measured in isolation, 36 us per vector — and it had no name,
so an operator reading the panel saw seventy milliseconds of forest work
the forest never did.

The two shares stay APART on purpose (rule 2): whoever is dominated by
`embed_ms` buys a closer embedder, and whoever is dominated by `dense_ms`
needs an index instead of a scan. One merged "hybrid overhead" number sends
half of them to fix the wrong thing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "apps" / "studio" / "src" / "views" / "shared.jsx"


class FakeCanopy:
    """A canopy that is slow on purpose. The point is not the number but
    that whatever it costs lands on `dense_ms` and not on the primitive.

    `model` and `__len__` are here because `Vine.dense_ready` asks for
    them: a mismatched index is no index (K.4), so a fake that skips the
    check would be testing a path the product does not take.
    """

    dim = 4
    model = "fake-embed"

    def __init__(self, ids):
        self.ids = list(ids)

    def __len__(self):
        return len(self.ids)

    def search(self, _vec, k=10):
        import time
        time.sleep(0.02)          # 20 ms of "scan"
        return [(i, 0.9) for i in self.ids[:k]]


class FakeEmbedder:
    model = "fake-embed"

    def embed(self, texts):
        import time
        time.sleep(0.01)          # 10 ms of "provider"
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


def _hybrid(vine):
    ids = [r["id"] for r in vine.catalog.conn.execute(
        "SELECT id FROM nodes LIMIT 5")]
    vine.canopy = FakeCanopy(ids)
    vine.embedder = FakeEmbedder()
    # `hybrid` is derived (embedder + index + matching model + asked for),
    # never assigned: the switch is `hybrid_locate`, which is what a caller
    # turning the layer on actually sets.
    vine.hybrid_locate = True
    assert vine.hybrid, "the fake layer did not satisfy dense_ready"
    return vine


def _last(vine, primitive):
    return [e for e in vine.tracer.events if e["primitive"] == primitive][-1]


# ------------------------------------------------------------------- F.149
def test_the_scan_is_named_and_is_not_the_embed(vine_rw):
    """Both shares present, both smaller than the span, neither absorbing
    the other."""
    v = _hybrid(vine_rw)
    v.locate("stigmergy")
    e = _last(v, "locate")
    assert e.get("dense_ms") is not None, "the scan has no name"
    assert e.get("embed_ms") is not None
    # The fakes sleep 20 ms and 10 ms; the assertion is the ORDER, not the
    # numbers, because a loaded machine moves the numbers and not the order.
    assert e["dense_ms"] > e["embed_ms"], (e["dense_ms"], e["embed_ms"])
    assert e["embed_ms"] + e["dense_ms"] <= e["elapsed_ms"] + 0.5


def test_the_lexical_work_is_what_is_left(vine_rw):
    """`elapsed - embed - dense` is the forest's own work. With 30 ms of
    fakes in the way it must still be small — that is the whole complaint
    this section answers."""
    v = _hybrid(vine_rw)
    v.locate("stigmergy")
    e = _last(v, "locate")
    net = e["elapsed_ms"] - e["embed_ms"] - e["dense_ms"]
    assert net < e["elapsed_ms"] / 2, (net, e)


def test_no_dense_layer_no_fields(vine_ro):
    """Rule 1's other half: a BM25-only event is byte-identical to a
    pre-v0.71 one. This is the default configuration, so it is the one most
    callers see."""
    assert not vine_ro.hybrid, "fixture came up hybrid; this test is void"
    vine_ro.locate("stigmergy")
    e = _last(vine_ro, "locate")
    assert "dense_ms" not in e
    assert "embed_ms" not in e


def test_a_share_does_not_leak_to_the_outer_call(vine_rw):
    """Rule 4: `harvest` contains a `locate`, and the inner call's share is
    the inner call's. Save/restore, the same discipline `embed_ms` has."""
    from monkeyllm.harvest import harvest

    v = _hybrid(vine_rw)
    # `hybrid` is the vine's own state here, not an argument of the sweep.
    harvest(v, "stigmergy")
    inner = _last(v, "locate")
    assert inner.get("dense_ms") is not None
    # `sniff` runs inside the same sweep and scans nothing: if the share
    # leaked upward or sideways it would land here.
    sniffed = [e for e in v.tracer.events if e["primitive"] == "sniff"]
    assert sniffed, "the sweep ran no sniff; this test is void"
    assert all(e.get("dense_ms") is None for e in sniffed), sniffed


# ------------------------------------------------------------------- F.150
def test_the_console_nets_both_and_lists_both():
    """Rule 3 lives in JSX: the host names, the panel subtracts. Read off
    the source — the same reason F.142 gives, and the same trick
    `test_trail_panel` uses."""
    source = SHARED.read_text(encoding="utf-8")
    assert "denseTotal" in source, "the panel does not sum the scan's share"
    # Each row loses BOTH shares, clamped so a rounding wobble can never
    # print a negative millisecond.
    assert re.search(r"Math\.min\(\(s\.embed_ms \|\| 0\) \+ \(s\.dense_ms \|\| 0\), s\.ms\)",
                     source), "a row still keeps one of the two shares"
    # And both are listed, apart (rule 2).
    assert re.search(r"step: 'dense'", source)
    assert re.search(r"step: 'embed'", source)
