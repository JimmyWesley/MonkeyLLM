"""Canopy vector layer (Phase 1 kickoff): index build/persist, RRF fusion,
and the locate contract (BM25-only unchanged; hybrid when index+embedder).

No network/GPU: a deterministic bag-of-words HashEmbedder stands in for
bge-m3 — similar text yields similar vectors, enough to exercise dense
retrieval and the fusion logic.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from monkeyllm import Vine
from monkeyllm.canopy import CanopyIndex, rrf_fuse


class HashEmbedder:
    """Bag-of-words hashed into a fixed-dim vector. Deterministic, offline,
    and roughly semantic at the lexical level (word overlap -> cosine)."""

    model = "hash-test-v1"

    def __init__(self, dim: int = 64):
        self.dim = dim

    def embed(self, texts):
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for w in re.findall(r"\w+", t.lower()):
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                vec[h % self.dim] += 1.0
            out.append(vec)
        return out


class TestRRF:
    def test_rewards_agreement(self):
        # "b" is #2 in both lists -> should beat items ranked once
        fused = rrf_fuse(["a", "b", "c"], ["x", "b", "y"])
        assert max(fused, key=fused.get) == "b"

    def test_unions_both_lists(self):
        fused = rrf_fuse(["a"], ["z"])
        assert set(fused) == {"a", "z"}


class TestIndex:
    def test_build_save_load_roundtrip(self, tmp_path):
        rows = [("n1", "sales in the southeast"), ("n2", "inference architecture")]
        idx = CanopyIndex.build(rows, HashEmbedder())
        assert len(idx) == 2 and idx.dim == 64
        idx.save(tmp_path)
        again = CanopyIndex.load(tmp_path)
        assert again is not None
        assert again.ids == ["n1", "n2"]
        assert again.dim == 64
        # vectors survive the float32 round-trip
        for a, b in zip(idx.vectors[0], again.vectors[0]):
            assert a == pytest.approx(b, abs=1e-6)

    def test_load_missing_returns_none(self, tmp_path):
        assert CanopyIndex.load(tmp_path) is None

    def test_search_ranks_by_similarity(self):
        rows = [("sales", "total sales by region"), ("infra", "gpu vram 3090")]
        idx = CanopyIndex.build(rows, HashEmbedder())
        emb = HashEmbedder()
        hits = idx.search(emb.embed(["sales region"])[0], k=2)
        assert hits[0][0] == "sales"


class TestLocateContract:
    def test_bm25_only_when_no_embedder(self, vine_ro):
        assert vine_ro.hybrid is False
        out = vine_ro.locate("inference architecture")
        assert out["results"]  # still works, Phase 0 path

    def test_hybrid_is_opt_in_even_when_the_layer_is_ready(self, forest_ro):
        """Availability is not consent (Part K). Measurement showed RRF
        degrades an already-correct BM25, so a built index must NOT switch
        entry search over by merely existing — the Gauntlet needs the same
        index and must not drag fusion in with it."""
        emb = HashEmbedder()
        ready = Vine(forest_ro, writable=False, embedder=emb)
        try:
            info = ready.build_canopy()
            assert info["nodes"] > 0
            assert ready.dense_ready is True
            assert ready.hybrid is False, "the layer being usable is not a decision"
        finally:
            ready.close()

        v = Vine(forest_ro, writable=False, embedder=emb, hybrid_locate=True)
        try:
            assert v.hybrid is True
            out = v.locate("arquitetura do mixerllm", k=5)
            ids = [r["id"] for r in out["results"]]
            assert any("mixerllm" in i for i in ids)
        finally:
            v.close()

    def test_lazy_reembed_after_plant(self, forest_rw):
        """Spec Fase 1, exit criterion 4: write → stale → next hybrid search
        reflects the change, without an offline rebuild."""
        emb = HashEmbedder()
        v = Vine(forest_rw, writable=True, embedder=emb, hybrid_locate=True)
        try:
            v.build_canopy()
            n0 = len(v.canopy)
            v.plant({
                "id": "notes/quantum-buzz",
                "type": "note",
                "title": "Quantum buzz",
                "summary": "Fictional quantum buzz phenomenon used to test lazy re-embedding of the vector layer.",
                "parent": "notes/_index",
                "body": "# Quantum buzz\n\n## Content\n\nTest.",
                "source": "agent",
            })
            assert "notes/quantum-buzz" in v.catalog.stale_ids()
            out = v.locate("quantum buzz phenomenon", k=5)
            ids = [r["id"] for r in out["results"]]
            assert "notes/quantum-buzz" in ids
            # vector layer grew and stale flags were consumed
            assert len(v.canopy) > n0
            assert v.catalog.stale_ids() == []
        finally:
            v.close()

    def test_lazy_reembed_after_graft_summary_change(self, forest_rw):
        emb = HashEmbedder()
        v = Vine(forest_rw, writable=True, embedder=emb, hybrid_locate=True)
        try:
            v.build_canopy()
            target = "notes/internal-faq"
            old_vec = list(v.canopy.vectors[v.canopy.ids.index(target)])
            v.graft(target, {"set_frontmatter": {
                "summary": "FAQ now covering the stellar xylophone protocol and the planting routine."
            }})
            v.locate("stellar xylophone protocol", k=5)  # triggers the refresh
            new_vec = v.canopy.vectors[v.canopy.ids.index(target)]
            assert new_vec != old_vec
            assert v.catalog.stale_ids() == []
        finally:
            v.close()

    def test_index_persists_and_reloads_into_new_vine(self, forest_ro):
        emb = HashEmbedder()
        v = Vine(forest_ro, writable=False, embedder=emb)
        try:
            v.build_canopy()
        finally:
            v.close()
        # A fresh Vine picks the saved index up. That makes the dense layer
        # *ready*; whether entry search uses it is a separate choice.
        v2 = Vine(forest_ro, writable=False, embedder=emb)
        try:
            assert v2.canopy is not None and v2.dense_ready is True
            assert v2.hybrid is False
            assert Vine(forest_ro, writable=False, embedder=emb,
                        hybrid_locate=True).hybrid is True
        finally:
            v2.close()
        # ...but with no embedder it stays BM25-only even if vectors exist
        v3 = Vine(forest_ro, writable=False)
        try:
            assert v3.hybrid is False
        finally:
            v3.close()
