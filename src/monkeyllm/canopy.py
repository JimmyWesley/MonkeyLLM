# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Canopy — the optional vector layer for `locate` (Phase 1 kickoff).

Phase 0 `locate` is BM25-only (zero embeddings) by design — that is a spec
exit criterion. Canopy adds an *optional* dense-retrieval layer on top
WITHOUT changing the `locate` contract (architecture doc §3):

    no index               -> BM25-only (Phase 0 behaviour, unchanged)
    index + an embedder     -> hybrid: RRF(vector, BM25), pheromone on top

Summaries of branches AND bananas are embedded (bge-m3 by default, served
locally by llama.cpp), stored as a flat index in the derived layer, and
fused with BM25 at query time via Reciprocal Rank Fusion.

The scan is a matmul where numpy is installed and a Python loop where it is
not (`monkeyllm[canopy]` pulls it in; the engine's own dependencies stay at
three). Both paths are one ranking, and a test compares them.

"Pure-Python, stdlib only (no numpy): the forest is small ... so a flat scan
over a few thousand 1024-d vectors is trivially fast" was true when it was
written and stopped being true at 1,877 nodes. Measured there: the loop
cost 67.3 ms per `locate` against 0.52 ms for the same arithmetic through
BLAS, and `load` spent 49 ms taking the contiguous float32 block `save` had
just written and unpacking it into 1,877 Python lists — destroying a layout
the file already had right. The quotable form of the old sentence carries
its date; this one carries its corpus size.

Everything lives in `_derived/canopy/` and is fully rebuildable — never a
source of truth.
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

_UNSET = object()
np = _UNSET  # resolved on FIRST USE by `_np()` — never at import


def _np():
    """numpy on first use, or None: the optional `monkeyllm[canopy]` extra.

    Resolved lazily and never at import, which is the v0.62 rule about the
    fold table applied to a dependency: measured, `import numpy` costs
    32.2 ms of process start-up, and a `plant`, a `validate` or a BM25-only
    forest must not pay it for a dense layer they never touch. A forest that
    HAS an index resolves it in `CanopyIndex.load`, i.e. inside `Vine`
    construction — so the Station pays at boot and warm, never on a first
    read (J.6.1).
    """
    global np
    if np is _UNSET:
        try:
            import numpy as _mod
        except ImportError:
            _mod = None
        np = _mod
    return np

# On disk the vectors are float32 (`vectors.f32`, unchanged); in memory they
# are float64. The scan's accumulator is what this decides, and the pre-matrix
# code summed Python floats — float64 — so this is the dtype that reproduces
# the ranking it replaced rather than merely approximating it. Measured on the
# 1,877x1024 index: against that older calculation a float32 accumulator
# drifts 2.04e-08 while float64 drifts 5.55e-17, and the tightest gap between
# neighbouring hits observed across six real bge-m3 indexes is 5.51e-07 — a
# 27x margin against a ~10^10 one. The bill for the certainty is 7.7 MB per
# index and 311 us instead of 69 on the scan, against 67,300 us before either.
STORE_DTYPE = "float64"

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
    xp = _np()
    if xp is not None and isinstance(b, xp.ndarray):
        # `b` is a row of the matrix store, and iterating it scalar-wise
        # boxes every element: measured 110.3 us against 27.8 for one `dot`
        # — and against 77.3 for the list-of-lists store the matrix
        # replaced, so the dispatch is what keeps `_rank_frontier` from
        # paying for `search`'s win. `float()` because the frontier sorts
        # on this and np.float32 is not a JSON number.
        return float(xp.dot(a, b))
    return sum(x * y for x, y in zip(a, b))


def _as_matrix(vectors: Sequence[Sequence[float]], dim: int):
    """The index's vector store: a contiguous `STORE_DTYPE` matrix under
    numpy, the list of lists it already was without it. `zip(ids, vectors)`
    yields one node's vector either way — that is the shape callers depend
    on, and it is why the matrix is not hidden behind a property."""
    xp = _np()
    if xp is None:
        return [list(v) for v in vectors]
    if len(vectors) == 0:
        return xp.zeros((0, dim), dtype=STORE_DTYPE)
    return xp.asarray(vectors, dtype=STORE_DTYPE)


def _append_row(vectors, vec: Sequence[float], dim: int):
    """Grow the store by one node (the J.13.4 refresh path, never a read)."""
    xp = _np()
    if xp is None:
        vectors.append(list(vec))
        return vectors
    return xp.vstack([vectors, xp.asarray(vec, dtype=STORE_DTYPE)])


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
        self.vectors = _as_matrix([], dim)  # unit vectors
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
        idx.vectors = _as_matrix([normalize(v) for v in vecs], dim)
        idx.built_at = time.time()
        return idx

    def save(self, derived_dir: Path) -> Path:
        d = Path(derived_dir) / CANOPY_DIRNAME
        d.mkdir(parents=True, exist_ok=True)
        xp = _np()
        if xp is not None:
            raw = xp.ascontiguousarray(self.vectors, dtype="<f4").tobytes()
        else:
            flat = array("f")
            for v in self.vectors:
                flat.extend(v)
            raw = flat.tobytes()
        (d / "vectors.f32").write_bytes(raw)
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
            # The index is `ids` paired with `vectors`, one each; a file
            # that breaks that pairing is a partial write, and the damage
            # is silent — `zip(ids, vectors)` in the frontier ranking drops
            # the unpaired tail, so those nodes score -1.0 and rank last
            # forever with nothing saying why.
            #
            # `struct.unpack` refused a buffer that was not an exact
            # multiple and `np.frombuffer` takes the whole vectors and
            # discards the remainder, so the two stores disagreed here
            # until this check; the id-count half was silent in BOTH from
            # the start. `_derived/` is rebuildable — `vine reindex` and a
            # canopy build are the repair.
            if len(raw) != count * dim * 4 or count != len(idx.ids):
                raise ValueError(
                    f"canopy vectors.f32 is a partial write: {len(raw)} bytes "
                    f"is {len(raw) / (4 * dim):.2f} vectors of dim {dim} "
                    f"against {len(idx.ids)} ids in index.json — rebuild the "
                    f"canopy ({vec_path})")
            if (xp := _np()) is not None:
                # `save` already wrote the layout the scan wants, so this
                # reads the block rather than rebuilding it. Copied, not
                # viewed: `frombuffer` over `bytes` is read-only and the
                # J.13.4 refresh writes into the store through `upsert`.
                # `astype` both widens to the accumulator dtype and copies,
                # which the store needs anyway: `frombuffer` over `bytes` is
                # read-only and the J.13.4 refresh writes through `upsert`.
                idx.vectors = xp.frombuffer(
                    raw, dtype="<f4", count=count * dim
                ).reshape(count, dim).astype(STORE_DTYPE)
            else:
                flat = struct.unpack(f"<{count * dim}f", raw)
                idx.vectors = [list(flat[i * dim : (i + 1) * dim]) for i in range(count)]
        return idx

    # -- incremental updates (lazy re-embedding, spec Phase 1) ---------------

    def upsert(self, node_id: str, vector: Sequence[float]) -> None:
        """Replace (or append) one node's vector — the lazy re-embed path."""
        vec = normalize(vector)
        try:
            i = self.ids.index(node_id)
        except ValueError:
            self.ids.append(node_id)
            self.vectors = _append_row(self.vectors, vec, self.dim)
        else:
            self.vectors[i] = vec

    def remove(self, node_id: str) -> None:
        try:
            i = self.ids.index(node_id)
        except ValueError:
            return
        del self.ids[i]
        if (xp := _np()) is None:
            del self.vectors[i]
        else:
            self.vectors = xp.delete(self.vectors, i, axis=0)

    # -- query --------------------------------------------------------------

    def search(self, query_vec: Sequence[float], k: int = 50) -> list[tuple[str, float]]:
        q = normalize(query_vec)
        if (xp := _np()) is not None and len(self.ids):
            # One BLAS call over the whole index. `argsort` and not
            # `argpartition`: a full sort of a few thousand scores is tens of
            # microseconds against the matmul's hundreds, and it settles ties
            # by index exactly as the stable `list.sort` below does — which
            # is what keeps the two paths one ranking instead of two.
            scores = self.vectors @ xp.asarray(q, dtype=STORE_DTYPE)
            order = xp.argsort(-scores, kind="stable")[:k]
            return [(self.ids[int(i)], float(scores[int(i)])) for i in order]
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
