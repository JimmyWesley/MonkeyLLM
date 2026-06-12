"""Monkey Bench v1 machinery, offline: chunker, chunk store, and the two
RAG baselines driven by a scripted chat (no network, no GPU)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.baselines import parse_json_obj, rag_iter, rag_topk  # noqa: E402
from bench.chunks import ChunkStore, build_chunks  # noqa: E402
from tests.test_canopy_vector import HashEmbedder  # noqa: E402

Q = {
    "id": "q07",
    "question": "How much memory does the experiments GPU have?",
    "expected_nodes": ["infra/workstation-3090"],
    "answer_contains": ["24"],
}


def scripted(replies):
    it = iter(replies)
    return lambda messages: next(it)


class TestChunker:
    def test_covers_all_nodes_and_dataset_rows(self, forest_ro):
        chunks = build_chunks(forest_ro)
        nodes = {c["node"] for c in chunks}
        assert len(nodes) == 82  # every node is in the corpus
        csv = [c for c in chunks if "#csv" in c["id"]]
        assert csv, "dataset rows must be ingested as text (fairness rule)"
        assert any("Southeast" in c["text"] for c in csv)

    def test_store_roundtrip_and_search(self, forest_ro, tmp_path):
        emb = HashEmbedder()
        store = ChunkStore.build(forest_ro, emb, tmp_path / "store")
        again = ChunkStore.load(tmp_path / "store", emb)
        assert again is not None and len(again) == len(store)
        hits = again.search("workstation 3090 vram", k=5)
        assert any(h["node"] == "infra/workstation-3090" for h in hits)

    def test_load_rejects_other_embedder(self, forest_ro, tmp_path):
        emb = HashEmbedder()
        ChunkStore.build(forest_ro, emb, tmp_path / "store")
        other = HashEmbedder()
        other.model = "other-model"
        assert ChunkStore.load(tmp_path / "store", other) is None


class TestBaselines:
    def _store(self, forest, tmp_path):
        return ChunkStore.build(forest, HashEmbedder(), tmp_path / "store")

    def test_topk_grades_and_counts_tokens(self, forest_ro, tmp_path):
        store = self._store(forest_ro, tmp_path)
        chat = scripted([json.dumps({
            "text": "The GPU has 24 GB of VRAM.",
            "answer_nodes": ["infra/workstation-3090"],
        })])
        r = rag_topk(chat, store, Q, verbose=False)
        assert r["correct_text"] is True
        assert r["banana_precision"] == 1.0
        assert r["metrics"]["tokens_to_banana"] > 0
        assert r["metrics"]["llm_calls"] == 1

    def test_iter_searches_then_answers(self, forest_ro, tmp_path):
        store = self._store(forest_ro, tmp_path)
        chat = scripted([
            '{"tool": "search", "args": {"query": "workstation gpu vram"}}',
            "resposta solta inválida",  # format recovery
            '{"tool": "search", "args": {"query": "3090 24 GB"}}',
            '{"tool": "answer", "args": {"text": "It has 24 GB.", "answer_nodes": ["infra/workstation-3090"]}}',
        ])
        r = rag_iter(chat, store, Q, verbose=False)
        assert r["correct_text"] is True
        assert r["metrics"]["hops_to_banana"] == 2  # two searches
        assert r["metrics"]["llm_calls"] == 4
        assert r["metrics"]["tokens_to_banana"] > 0

    def test_parse_json_obj_inside_prose(self):
        assert parse_json_obj('sure!\n{"tool": "search", "args": {}}')["tool"] == "search"
        assert parse_json_obj("nothing here") is None
