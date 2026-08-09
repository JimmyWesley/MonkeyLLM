# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Chunk store for the RAG baselines (Monkey Bench v1).

Fairness rules (roadmap, Fase 1): the baselines see the SAME corpus with the
SAME embedder as MonkeyLLM. So this module ingests the forest the way a naive
RAG pipeline would ingest an Obsidian vault:

  - every node's markdown (frontmatter title + body) split into ~250-token
    chunks;
  - SQLite dataset payloads dumped to CSV text and chunked too (the rows ARE
    part of the corpus — MonkeyLLM reaches them via `query`, RAG gets them as
    text like any CSV ingest would);
  - chunks embedded with the same embedder (bge-m3) and stored via the same
    flat index used by the Canopy.

Artifacts land in `bench/_artifacts/<forest-name>/` and are reconstruible.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monkeyllm.canopy import CanopyIndex  # noqa: E402
from monkeyllm.forest import Forest  # noqa: E402
from monkeyllm.tokens import CHARS_PER_TOKEN  # noqa: E402

CHUNK_TOKENS = 250
CHUNK_CHARS = CHUNK_TOKENS * CHARS_PER_TOKEN


def _split(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Paragraph-aware splitting: pack whole paragraphs up to max_chars."""
    out: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if buf and len(buf) + len(para) + 2 > max_chars:
            out.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
        while len(buf) > max_chars:  # single paragraph longer than a chunk
            out.append(buf[:max_chars])
            buf = buf[max_chars:]
    if buf:
        out.append(buf)
    return out


def _dump_sqlite(db_path: Path) -> str:
    """CSV-ish dump of every table (what a naive ingest of the file yields)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        lines: list[str] = []
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        for t in tables:
            cur = conn.execute(f'SELECT * FROM "{t}"')  # noqa: S608 — ro connection, table from master
            cols = [d[0] for d in cur.description]
            lines.append(f"tabela {t}: " + ",".join(cols))
            for row in cur:
                lines.append(",".join(str(v) for v in row))
        return "\n".join(lines)
    finally:
        conn.close()


def build_chunks(forest_root: Path) -> list[dict]:
    """[{id, node, text}] over the whole forest (markdown + dataset dumps)."""
    forest = Forest(forest_root)
    chunks: list[dict] = []
    for node_id in forest.iter_ids():
        try:
            node = forest.read(node_id)
        except Exception:
            continue
        header = f"[{node_id}] {node.title}"
        body = f"{node.summary}\n\n{node.body}"
        for i, piece in enumerate(_split(body)):
            chunks.append({
                "id": f"{node_id}#{i}",
                "node": node_id,
                "text": f"{header}\n{piece}",
            })
        payload = node.frontmatter.get("payload")
        if payload and node.frontmatter.get("payload_type") == "sqlite":
            db_path = (forest_root / node_id).parent / payload
            if db_path.exists():
                for j, piece in enumerate(_split(_dump_sqlite(db_path))):
                    chunks.append({
                        "id": f"{node_id}#csv{j}",
                        "node": node_id,
                        "text": f"{header} (dados)\n{piece}",
                    })
    return chunks


class ChunkStore:
    """Embedded chunk corpus with the same flat vector index as the Canopy."""

    def __init__(self, chunks: list[dict], index: CanopyIndex, embedder):
        self.by_id = {c["id"]: c for c in chunks}
        self.index = index
        self.embedder = embedder

    @classmethod
    def build(cls, forest_root: Path, embedder, out_dir: Path) -> "ChunkStore":
        chunks = build_chunks(forest_root)
        index = CanopyIndex.build([(c["id"], c["text"]) for c in chunks], embedder)
        out_dir.mkdir(parents=True, exist_ok=True)
        index.save(out_dir)
        (out_dir / "chunks.json").write_text(
            json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
        )
        return cls(chunks, index, embedder)

    @classmethod
    def load(cls, out_dir: Path, embedder) -> "ChunkStore | None":
        index = CanopyIndex.load(out_dir)
        meta = out_dir / "chunks.json"
        if index is None or not meta.exists():
            return None
        if embedder is not None and index.model != embedder.model:
            return None  # embedder swap invalidates the store
        chunks = json.loads(meta.read_text(encoding="utf-8"))
        return cls(chunks, index, embedder)

    def search(self, query: str, k: int = 6) -> list[dict]:
        qvec = self.embedder.embed([query])[0]
        hits = self.index.search(qvec, k=k)
        return [
            {**self.by_id[cid], "score": round(score, 4)}
            for cid, score in hits
            if cid in self.by_id
        ]

    def __len__(self) -> int:
        return len(self.by_id)
