"""The Station's REST surface (spec J.1).

Built on Starlette, which already ships as a transitive dependency of `mcp`
— the host adds no new runtime dependency, keeping J.6's one-image,
no-external-database posture.

Forest resolution reuses the engine's `ForestPool` (spec C.0) unchanged:
the Station is a privileged client, not a fork of the server.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from monkeyllm.errors import (
    E_FRONTMATTER,
    E_LOCKED,
    E_NOT_FOUND,
    E_QUERY_FORBIDDEN,
    E_READONLY,
    E_SCHEMA,
    E_TIMEOUT,
    VineError,
)
from monkeyllm.server import ForestPool
from monkeyllm_station.policy import E_FORBIDDEN, ScopedVine
from monkeyllm_station.registry import Registry

# Phase A serves reads only. Writes wait for J.4 principal-stamped commits
# (task T07 Phase B) — exposing them earlier would produce unattributed
# history, which is worse than no write endpoint at all.
READ_PRIMITIVES = frozenset(
    {"locate", "look", "move", "pick", "scan", "sniff", "harvest", "query"}
)

STATUS_BY_CODE = {
    E_NOT_FOUND: 404,
    E_SCHEMA: 400,
    E_FRONTMATTER: 400,
    E_FORBIDDEN: 403,
    E_READONLY: 403,
    E_QUERY_FORBIDDEN: 403,
    E_LOCKED: 409,
    E_TIMEOUT: 504,
}


def _envelope(err: VineError, status: int | None = None) -> JSONResponse:
    body = err.to_dict()
    return JSONResponse(body, status_code=status or STATUS_BY_CODE.get(err.code, 400))


def _unknown_forest(forest: str) -> JSONResponse:
    """One response for 'no such forest' AND 'not granted to you'.

    Distinguishing them would let a principal enumerate the registry — the
    same existence-oracle reasoning J.3 applies to nodes, applied to forests.
    """
    return _envelope(
        VineError(
            E_NOT_FOUND,
            f"unknown forest: {forest}",
            hint="GET /v1/forests lists the forests available to you.",
        )
    )


def build_app(
    *,
    root: str | Path,
    registry_path: str | Path,
    writable: bool = False,
) -> Starlette:
    pool = ForestPool(root=Path(root), writable=writable)
    registry = Registry(registry_path)

    # A SQLite connection belongs to the thread that opened it, and the engine
    # rightly does not weaken that guarantee for the host's convenience. So the
    # Station confines every forest touch — open, call, close — to one
    # dedicated thread. It also keeps the blocking reads off the event loop.
    # Serialising across forests is a Phase A simplification; a worker per
    # forest is the scale-out step, and it changes nothing above this line.
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forest")

    async def in_forest_thread(fn):
        return await asyncio.get_running_loop().run_in_executor(worker, fn)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await in_forest_thread(pool.close)  # vines close in their own thread
        worker.shutdown(wait=True)
        registry.close()

    def principal_of(request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        key = header[7:].strip() if header.lower().startswith("bearer ") else None
        return registry.authenticate(key or request.headers.get("x-api-key"))

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "mode": pool.mode})

    async def forests(request: Request) -> JSONResponse:
        principal = principal_of(request)
        if principal is None:
            return _envelope(VineError(E_FORBIDDEN, "missing or invalid API key"), 401)
        granted = set(registry.forests_for(principal))
        listed = [f for f in pool.list()["forests"] if f["id"] in granted]
        return JSONResponse({"forests": listed, "mode": pool.mode})

    async def primitive(request: Request) -> JSONResponse:
        principal = principal_of(request)
        if principal is None:
            return _envelope(VineError(E_FORBIDDEN, "missing or invalid API key"), 401)

        name = request.path_params["primitive"]
        if name not in READ_PRIMITIVES:
            return _envelope(
                VineError(
                    E_NOT_FOUND,
                    f"no such endpoint: {name}",
                    hint=f"Phase A serves reads: {sorted(READ_PRIMITIVES)}.",
                )
            )

        forest = request.path_params["forest"]
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return _unknown_forest(forest)

        try:
            payload = await request.json() if await request.body() else {}
        except json.JSONDecodeError as e:
            return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
        if not isinstance(payload, dict):
            return _envelope(VineError(E_SCHEMA, "body must be a JSON object"))

        def work():
            try:
                vine = pool.get(forest)
            except VineError:
                return None  # resolution failure -> the same answer as absent
            return ScopedVine(vine, policy).call(name, **payload)

        result = await in_forest_thread(work)
        if result is None:
            return _unknown_forest(forest)
        if "error" in result and isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        return JSONResponse(result)

    app = Starlette(
        routes=[
            Route("/v1/health", health),
            Route("/v1/forests", forests),
            Route("/v1/forests/{forest}/{primitive}", primitive, methods=["POST"]),
        ],
        lifespan=lifespan,
    )
    app.state.pool = pool
    app.state.registry = registry
    return app
