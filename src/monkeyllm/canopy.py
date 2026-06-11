"""Canopy — the optional vector layer for `locate` (Phase 1 kickoff).

Phase 0 `locate` is BM25-only (zero embeddings) by design — that is a spec
exit criterion. Canopy adds an *optional* dense-retrieval layer on top
WITHOUT changing the `locate` contract (architecture doc §3):

    no index               -> BM25-only (Phase 0 behaviour, unchanged)
    index + an embedder     -> hybrid: RRF(vector, BM25), pheromone on top

Summaries of branches AND bananas are embedded (bge-m3 by default, served
locally by llama.cpp), stored as a flat index in the derived layer, and
fused with BM25 at query time via Reciprocal Rank Fusion.

Pure-Python, stdlib only (no numpy): the forest is small and the SLM hop
dominates latency (architecture doc §11), so a flat scan over a few thousand
1024-d vectors is trivially fast. Everything lives in `_derived/canopy/`
and is fully rebuildable — never a source of truth.
"""

from __future__ import annotations

import json
import math
import os
import struct
import time
from array import array
from pathlib import Path
from typing import Protocol, Sequence

CANOPY_DIRNAME = "canopy"
DEFAULT_EMBED_MODEL = "bge-m3"


class Embedder(Protocol):
    """Anything that turns text into unit vectors. The model id is recorded
    in the index so a model swap forces a rebuild."""

    model: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def normalize(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Dot product. Vectors stored in the index are pre-normalized, so this
    is cosine similarity for them."""
    return sum(x * y for x, y in zip(a, b))


# ----------------------------------------------------------------------------
# Embedder backend: llama.cpp / any OpenAI-compatible /v1/embeddings endpoint
# ----------------------------------------------------------------------------

class LlamaCppEmbedder:
    """Talks to an OpenAI-compatible `/embeddings` endpoint (llama.cpp's
    `llama-server --embedding`, vLLM, LM Studio, ...). Returns unit vectors."""

    def __init__(
        self,
        endpoint: str = "http://localhost:8091/v1",
        model: str = DEFAULT_EMBED_MODEL,
        api_key: str = "no-key",
        batch_size: int = 32,
        timeout: float = 120.0,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.batch_size = batch_size
        self.timeout = timeout
        self._client = None  # persistent keep-alive connection (lazy)

    def _http(self):
        import httpx

        if self._client is None:
            self._client = httpx.Client(
                timeout=self.timeout,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        client = self._http()
        for i in range(0, len(texts), self.batch_size):
            batch = list(texts[i : i + self.batch_size])
            resp = client.post(
                f"{self.endpoint}/embeddings",
                json={"model": self.model, "input": batch},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            # the endpoint may reorder; OpenAI guarantees `index`
            data.sort(key=lambda d: d.get("index", 0))
            out.extend(normalize(d["embedding"]) for d in data)
        return out


def embedder_from_env() -> "LlamaCppEmbedder | None":
    """Build the dense embedder from the environment, or None to stay
    BM25-only. Set MONKEYLLM_EMBED_ENDPOINT to activate the vector layer.

        MONKEYLLM_EMBED_ENDPOINT  OpenAI-compatible base_url (e.g. the
                                  llama.cpp embedding server's /v1)
        MONKEYLLM_EMBED_MODEL     model id (default: bge-m3)
        MONKEYLLM_EMBED_API_KEY   key the endpoint expects (default: no-key)
    """
    endpoint = os.environ.get("MONKEYLLM_EMBED_ENDPOINT")
    if not endpoint:
        return None
    return LlamaCppEmbedder(
        endpoint=endpoint,
        model=os.environ.get("MONKEYLLM_EMBED_MODEL", DEFAULT_EMBED_MODEL),
        api_key=os.environ.get("MONKEYLLM_EMBED_API_KEY", "no-key"),
    )


# ----------------------------------------------------------------------------
# The index
# ----------------------------------------------------------------------------

class CanopyIndex:
    """A flat, in-memory vector index persisted under `_derived/canopy/`.

    Layout:
        canopy/index.json   -> {model, dim, built_at, ids: [...]}
        canopy/vectors.f32  -> little-endian float32, dim per id, ids order
    """

    def __init__(self, model: str, dim: int):
        self.model = model
        self.dim = dim
        self.ids: list[str] = []
        self.vectors: list[list[float]] = []  # unit vectors
        self.built_at: float = 0.0

    # -- build / persist ----------------------------------------------------

    @classmethod
    def build(cls, rows: Sequence[tuple[str, str]], embedder: Embedder) -> "CanopyIndex":
        """`rows` is [(id, text_to_embed)]. text is normally the summary
        (the smell of the node) — that is what `locate` ranks against."""
        ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]
        vecs = embedder.embed(texts) if texts else []
        dim = len(vecs[0]) if vecs else 0
        idx = cls(model=embedder.model, dim=dim)
        idx.ids = ids
        idx.vectors = [normalize(v) for v in vecs]
        idx.built_at = time.time()
        return idx

    def save(self, derived_dir: Path) -> Path:
        d = Path(derived_dir) / CANOPY_DIRNAME
        d.mkdir(parents=True, exist_ok=True)
        flat = array("f")
        for v in self.vectors:
            flat.extend(v)
        (d / "vectors.f32").write_bytes(flat.tobytes())
        (d / "index.json").write_text(
            json.dumps(
                {"model": self.model, "dim": self.dim, "built_at": self.built_at, "ids": self.ids},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return d

    @classmethod
    def load(cls, derived_dir: Path) -> "CanopyIndex | None":
        d = Path(derived_dir) / CANOPY_DIRNAME
        meta_path = d / "index.json"
        vec_path = d / "vectors.f32"
        if not meta_path.exists() or not vec_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        idx = cls(model=meta["model"], dim=meta["dim"])
        idx.ids = meta["ids"]
        idx.built_at = meta.get("built_at", 0.0)
        raw = vec_path.read_bytes()
        dim = idx.dim
        if dim:
            count = len(raw) // (4 * dim)
            flat = struct.unpack(f"<{count * dim}f", raw)
            idx.vectors = [list(flat[i * dim : (i + 1) * dim]) for i in range(count)]
        return idx

    # -- incremental updates (lazy re-embedding, spec Phase 1) ---------------

    def upsert(self, node_id: str, vector: Sequence[float]) -> None:
        """Replace (or append) one node's vector — the lazy re-embed path."""
        vec = normalize(vector)
        try:
            i = self.ids.index(node_id)
            self.vectors[i] = vec
        except ValueError:
            self.ids.append(node_id)
            self.vectors.append(vec)

    def remove(self, node_id: str) -> None:
        try:
            i = self.ids.index(node_id)
        except ValueError:
            return
        del self.ids[i]
        del self.vectors[i]

    # -- query --------------------------------------------------------------

    def search(self, query_vec: Sequence[float], k: int = 50) -> list[tuple[str, float]]:
        q = normalize(query_vec)
        scored = [(self.ids[i], cosine(q, self.vectors[i])) for i in range(len(self.ids))]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def __len__(self) -> int:
        return len(self.ids)


# ----------------------------------------------------------------------------
# Reciprocal Rank Fusion (spec Phase 1: RRF fusing vector + BM25)
# ----------------------------------------------------------------------------

def rrf_fuse(
    *ranked_lists: Sequence[str],
    k: int = 60,
) -> dict[str, float]:
    """Reciprocal Rank Fusion. Each list is ids best-first. Returns
    id -> fused score (higher is better). Rank-based, so it needs no score
    calibration between the lexical and dense signals."""
    fused: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, node_id in enumerate(ranked):
            fused[node_id] = fused.get(node_id, 0.0) + 1.0 / (k + rank + 1)
    return fused
