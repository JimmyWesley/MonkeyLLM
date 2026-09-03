# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

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

    def test_a_new_node_is_found_before_it_is_embedded(self, forest_rw):
        """K.2 as amended (v0.42): the read path embeds the query and nothing
        else. A node written a second ago is found by BM25 immediately and
        joins the dense half when somebody refreshes — the debt costs recall
        in one half, never findability."""
        emb = HashEmbedder()
        v = Vine(forest_rw, writable=True, embedder=emb, hybrid_locate=True)
        try:
            v.build_canopy()
            n0 = len(v.canopy)
            v.plant({
                "id": "notes/quantum-buzz",
                "type": "note",
                "title": "Quantum buzz",
                "summary": "Fictional quantum buzz phenomenon used to test the vector layer's refresh.",
                "parent": "notes/_index",
                "body": "# Quantum buzz\n\n## Content\n\nTest.",
                "source": "agent",
            })
            assert "notes/quantum-buzz" in v.catalog.stale_ids()

            out = v.locate("quantum buzz phenomenon", k=5)
            assert "notes/quantum-buzz" in [r["id"] for r in out["results"]]
            # The question paid for the question, and for nothing anybody
            # else wrote: no node was embedded by that read.
            assert len(v.canopy) == n0
            assert v.canopy_status["stale"] == 1

            out = v.refresh_canopy()
            assert out["refreshed"] == 1
            assert len(v.canopy) > n0
            assert v.catalog.stale_ids() == []
            assert v.canopy_status["stale"] == 0
        finally:
            v.close()

    def test_refresh_reembeds_a_changed_summary(self, forest_rw):
        emb = HashEmbedder()
        v = Vine(forest_rw, writable=True, embedder=emb, hybrid_locate=True)
        try:
            v.build_canopy()
            target = "notes/internal-faq"
            old_vec = list(v.canopy.vectors[v.canopy.ids.index(target)])
            v.graft(target, {"set_frontmatter": {
                "summary": "FAQ now covering the stellar xylophone protocol and the planting routine."
            }})
            v.locate("stellar xylophone protocol", k=5)
            # `list(...)` on both sides: the subject is that the vector
            # did not change, never which store holds it (a matrix under
            # numpy, a list of lists without it).
            assert list(v.canopy.vectors[v.canopy.ids.index(target)]) == old_vec, \
                "a read re-embedded a node"

            v.refresh_canopy()
            assert list(v.canopy.vectors[v.canopy.ids.index(target)]) != old_vec
            assert v.catalog.stale_ids() == []
        finally:
            v.close()

    def test_the_query_is_embedded_once_per_distinct_text(self, forest_rw):
        """K.6: embed(model, text) is pure, so the round trip is owed once
        per question rather than once per asking."""
        emb = HashEmbedder()
        calls = []
        original = emb.embed
        emb.embed = lambda texts: (calls.append(list(texts)), original(texts))[1]
        v = Vine(forest_rw, writable=True, embedder=emb, hybrid_locate=True)
        try:
            v.build_canopy()
            calls.clear()
            v.locate("stellar xylophone protocol", k=5)
            assert calls == [["stellar xylophone protocol"]]
            v.locate("stellar xylophone protocol", k=5)
            assert len(calls) == 1, "the same question paid twice"
            v.locate("a different question entirely", k=5)
            assert len(calls) == 2

            v.catalog.embed_memo_clear()
            v.locate("stellar xylophone protocol", k=5)
            assert len(calls) == 3, "dropping the memo must cost latency only"
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



class TestScanPaths:
    """The matmul and the Python loop are ONE ranking.

    The project's standing rule: two descriptions of one answer agree only
    where somebody compared them. numpy is an optional extra, so a
    deployment may run either path, and an index written by one is read by
    the other — which makes both the ordering and the bytes contractual.
    Skipped without numpy: there is only one path to compare there.
    """

    DIM = 64
    WORDS = ("sales southeast inference architecture latency budget forest "
             "retrieval vector index summary payload dataset commit").split()

    @classmethod
    def _rows(cls, n=80):
        import random
        rng = random.Random(11)
        return [(f"n{i}", " ".join(rng.sample(cls.WORDS, 6))) for i in range(n)]

    @classmethod
    def _query(cls, text="sales latency forest budget"):
        return HashEmbedder(cls.DIM).embed([text])[0]

    @staticmethod
    def _under(monkeypatch, numpy_off, fn):
        """Run `fn` with the module's numpy present or absent. The whole
        act runs inside — building under one store and scanning under the
        other would compare a path with itself."""
        from monkeyllm import canopy as mod
        with monkeypatch.context() as m:
            if numpy_off:
                m.setattr(mod, "np", None)
            assert (mod._np() is None) == numpy_off
            return fn()

    def test_both_paths_rank_identically(self, monkeypatch):
        pytest.importorskip("numpy")
        rows, q = self._rows(), self._query()

        def run():
            return CanopyIndex.build(rows, HashEmbedder(self.DIM)).search(q, k=25)

        fast = self._under(monkeypatch, False, run)
        slow = self._under(monkeypatch, True, run)

        assert [i for i, _ in fast] == [i for i, _ in slow], (
            "the matmul and the loop disagree on the ORDER — a ranking "
            "change nobody asked for")
        for (_, sa), (_, sb) in zip(fast, slow):
            assert abs(sa - sb) < 1e-4, (
                f"score drift {abs(sa - sb):.2e}: float32 accumulation moved a "
                "cosine further than the tie-rounding tolerates")

    def test_the_file_is_the_same_file(self, tmp_path, monkeypatch):
        pytest.importorskip("numpy")
        rows = self._rows(20)

        def save_to(where):
            def run():
                CanopyIndex.build(rows, HashEmbedder(self.DIM)).save(where)
                return (where / "canopy" / "vectors.f32").read_bytes()
            return run

        fast = self._under(monkeypatch, False, save_to(tmp_path / "a"))
        slow = self._under(monkeypatch, True, save_to(tmp_path / "b"))
        assert fast == slow, (
            "vectors.f32 must be byte-identical whichever path wrote it — an "
            "index built where numpy is installed is loaded where it is not")

    def test_a_numpy_index_reloads_without_numpy(self, tmp_path, monkeypatch):
        pytest.importorskip("numpy")
        rows, q = self._rows(20), self._query("vector index commit")

        def write():
            idx = CanopyIndex.build(rows, HashEmbedder(self.DIM))
            idx.save(tmp_path)
            return idx.search(q, k=10)

        expected = self._under(monkeypatch, False, write)
        reread = self._under(monkeypatch, True,
                             lambda: CanopyIndex.load(tmp_path).search(q, k=10))
        assert [i for i, _ in reread] == [i for i, _ in expected]

    def test_upsert_and_remove_agree(self, monkeypatch):
        pytest.importorskip("numpy")
        rows, q = self._rows(20), self._query("forest payload")
        extra = HashEmbedder(self.DIM).embed(["a brand new summary"])[0]

        def run():
            idx = CanopyIndex.build(rows, HashEmbedder(self.DIM))
            idx.upsert("n-new", extra)   # append: grows the store
            idx.upsert("n3", extra)      # replace: writes into it
            idx.remove("n7")             # shrink
            return list(idx.ids), [i for i, _ in idx.search(q, k=15)]

        fast = self._under(monkeypatch, False, run)
        slow = self._under(monkeypatch, True, run)
        assert fast[0] == slow[0], "ids diverged across the two stores"
        assert fast[1] == slow[1], "ranking diverged after upsert/remove"


class TestPartialWrite:
    """A half-written `vectors.f32` is refused, whichever store reads it.

    The damage is silent otherwise: `ids` outlives `vectors`, the frontier
    ranking's `zip` drops the unpaired tail, and those nodes score -1.0 —
    last, forever, with nothing saying why. `_derived/` is rebuildable, so
    refusing to load is the cheap half of this trade.
    """

    @staticmethod
    def _index(tmp_path, dim=8, n=10):
        from monkeyllm import canopy as mod
        idx = CanopyIndex(model="m", dim=dim)
        idx.ids = [f"n{i}" for i in range(n)]
        vecs = HashEmbedder(dim).embed([f"node {i}" for i in range(n)])
        idx.vectors = mod._as_matrix(vecs, dim)
        idx.save(tmp_path)
        return tmp_path / "canopy" / "vectors.f32"

    @pytest.mark.parametrize("numpy_off", [False, True])
    @pytest.mark.parametrize(
        "cut, why",
        [(10, "cut in the middle of a vector"),
         (8 * 4, "one whole vector short of the id list")],
    )
    def test_a_short_file_is_refused(self, tmp_path, monkeypatch, numpy_off, cut, why):
        from monkeyllm import canopy as mod
        if numpy_off is False and mod._np() is None:
            pytest.skip("no numpy installed: only one store to check")
        f = self._index(tmp_path)
        f.write_bytes(f.read_bytes()[:-cut])
        with monkeypatch.context() as m:
            if numpy_off:
                m.setattr(mod, "np", None)
            with pytest.raises(ValueError, match="partial write"):
                CanopyIndex.load(tmp_path)

    def test_an_intact_file_still_loads(self, tmp_path):
        self._index(tmp_path)
        assert len(CanopyIndex.load(tmp_path).ids) == 10



class TestCorruptIndexAtTheStation:
    """Where a refused index lands, and what still cannot be seen from outside.

    The guard belongs to the engine; an operator meets it at the host, and
    "the forest stopped opening" is only actionable if the repair it names
    actually repairs it. That is the load-bearing test here — it failed
    before the lock fix.

    The blast radius is deliberate but not obviously right: the dense layer
    is OPTIONAL and `_derived/` is disposable, so degrading to BM25-only
    would be the proportionate answer. It is not taken here because K.4
    enumerates `canopy_status.state` and a new value is a contract change —
    a spec cut, not a patch.
    """

    FOREST = "forest-fixture"

    @staticmethod
    def _corrupt_canopy(derived, dim=8, n=10):
        """More ids than whole vectors: the condition that used to load."""
        from monkeyllm import canopy as mod
        idx = CanopyIndex(model="bge-m3", dim=dim)
        idx.ids = [f"n{i}" for i in range(n)]
        idx.vectors = mod._as_matrix(
            [mod.normalize([1.0] * dim) for _ in range(n)], dim)
        idx.save(derived)
        f = derived / "canopy" / "vectors.f32"
        f.write_bytes(f.read_bytes()[:-dim * 4])
        return f

    @staticmethod
    def _station(tmp_path, forests):
        import sys
        from pathlib import Path as P
        station_dir = P(__file__).resolve().parents[1] / "apps" / "station"
        if str(station_dir) not in sys.path:
            sys.path.insert(0, str(station_dir))
        from starlette.testclient import TestClient
        from conftest import build_forest
        from monkeyllm_station.app import build_app

        root = tmp_path / "root"
        for f in forests:
            build_forest(root / f)
        app = build_app(root=root, registry_path=tmp_path / "station.db", mcp=False)
        return app, TestClient(app), root

    # -- the engine half ---------------------------------------------------

    def test_the_repair_the_error_names_actually_repairs(self, tmp_path):
        """The one that failed before the lock fix.

        `Vine.__init__` acquires the writer lock and the release lives in
        `close()`, so a raise between them held it forever: an operator who
        rebuilt the canopy exactly as told found the forest still refusing,
        now blaming a live writer that did not exist.
        """
        import shutil
        from conftest import build_forest
        from monkeyllm import Vine
        from monkeyllm.forest import WriterLock

        root = tmp_path / "f"
        build_forest(root)
        self._corrupt_canopy(root / "_derived")

        with pytest.raises(ValueError, match="partial write"):
            Vine(root, writable=True)
        assert WriterLock.probe(root).get("state") == "free", (
            "a constructor that raised left the writer lock held")

        shutil.rmtree(root / "_derived" / "canopy")   # the named repair
        v = Vine(root, writable=True)
        try:
            assert v.canopy is None
        finally:
            v.close()

    # -- the host half -----------------------------------------------------

    def test_the_boot_report_names_the_file_and_the_repair(self, tmp_path):
        app, client, root = self._station(tmp_path, [self.FOREST])
        self._corrupt_canopy(root / self.FOREST / "_derived")
        with client:
            why = app.state.warmed["skipped"].get(self.FOREST, "")
        assert "partial write" in why and "vectors.f32" in why
        assert "rebuild the canopy" in why, (
            "a refusal an operator cannot act on is half a refusal")

    def test_an_intact_forest_beside_it_still_serves(self, tmp_path):
        """J.6.1: one forest that cannot open never stops the others."""
        app, client, root = self._station(tmp_path, ["broken", "intact"])
        self._corrupt_canopy(root / "broken" / "_derived")
        with client:
            reg = app.state.registry
            key = reg.issue_key("boss")
            for f in ("broken", "intact"):
                reg.grant("boss", f, {"read", "write", "admin"})
            body = client.get("/v1/forests",
                              headers={"Authorization": f"Bearer {key}"}).json()
            state = {f["id"]: f for f in body["forests"]}
            assert app.state.warmed["skipped"].keys() == {"broken"}
            assert "intact" in app.state.warmed["warmed"]
            assert not state["broken"].get("locked"), (
                "a forest nobody is writing must not read as write-locked")
            assert not state["intact"].get("locked")

    def test_boot_says_out_loud_that_a_forest_did_not_open(self, tmp_path, capsys):
        """The silence half of the gap, closed without touching contract.

        `app.state.warmed["skipped"]` held the reason and nothing served it,
        so a forest could be unreachable for the whole life of the process
        with every signal reading green. One line per forest at boot, on the
        `station:` channel the other boot refusals already use.
        """
        app, client, root = self._station(tmp_path, [self.FOREST])
        self._corrupt_canopy(root / self.FOREST / "_derived")
        with client:
            pass
        err = capsys.readouterr().err
        assert f"forest {self.FOREST!r} did not open" in err, (
            "a forest that cannot serve must not boot in silence")
        assert "partial write" in err and "rebuild the canopy" in err, (
            "the line has to carry the repair, not just the fact")

    def test_over_the_api_it_looks_exactly_like_a_cold_forest(self, tmp_path):
        """Pinned, NOT endorsed: the other half of the gap.

        Boot says it on stderr (above), which is the half that needed no
        contract. Over the API a forest that could not open is still
        byte-identical to a cold one nobody has touched — no `locked`, and
        `/v1/health` reports `ok` because `served` is computed as
        `len(listing) - locked` and a forest that cannot open is in neither
        term. An operator reading a dashboard rather than a log sees
        nothing.

        Two shapes would close it: degrade to no-index and say so through a
        new `canopy_status.state`, or serve the boot report. K.4 enumerates
        those states and nothing serves that report, so both ADD contract —
        spec before code. Recorded here so the next person finds a test
        instead of a mystery, and so closing it is a deliberate change with
        a test to update.
        """
        app, client, root = self._station(tmp_path, [self.FOREST])
        self._corrupt_canopy(root / self.FOREST / "_derived")
        with client:
            reg = app.state.registry
            key = reg.issue_key("boss")
            reg.grant("boss", self.FOREST, {"read", "write", "admin"})
            h = {"Authorization": f"Bearer {key}"}
            health = client.get("/v1/health", headers=h).json()
            entry = next(f for f in client.get("/v1/forests", headers=h).json()["forests"]
                         if f["id"] == self.FOREST)
            # The process itself knows; nothing it serves does.
            assert self.FOREST in app.state.warmed["skipped"]

        assert health["status"] == "ok", "pinned: a forest that cannot serve, served as ok"
        assert health["forests"]["locked"] == 0
        assert "locked" not in entry and entry["active"] is False, (
            "pinned: indistinguishable from a forest nobody has opened yet")
