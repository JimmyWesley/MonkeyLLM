"""The Station's REST surface (spec J.1), Studio hosting and MCP mount.

Built on Starlette, which already ships as a transitive dependency of `mcp`
— the host adds no new runtime dependency, keeping J.6's one-image,
no-external-database posture.

Forest resolution reuses the engine's `ForestPool` (spec C.0) unchanged:
the Station is a privileged client, not a fork of the server.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

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
from monkeyllm_station.policy import CAPS, E_FORBIDDEN, REQUIRED_CAP, ScopedVine
from monkeyllm_station.registry import Registry

READ_PRIMITIVES = frozenset(
    {"locate", "look", "move", "pick", "scan", "sniff", "harvest", "query"}
)
WRITE_PRIMITIVES = frozenset({"plant", "graft", "tend"})
# Not engine primitives: retrieval composed with the forest's bound model
# (J.10). `answer` reads, `curate` proposes a summary for a human to apply.
COMPOSITES = {"answer": ("read", "answer"), "curate": ("write", "ingest")}
SERVED_PRIMITIVES = READ_PRIMITIVES | WRITE_PRIMITIVES | set(COMPOSITES)

# The Studio is a React/Vite build: static files only, no server rendering,
# so it stays a plain REST client with no privileged side-channel (J.5).
STUDIO_DIST = Path(__file__).resolve().parents[2] / "studio" / "dist"

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
    return JSONResponse(err.to_dict(),
                        status_code=status or STATUS_BY_CODE.get(err.code, 400))


def _unknown_forest(forest: str) -> JSONResponse:
    """One response for 'no such forest' AND 'not granted to you'.

    Distinguishing them would let a principal enumerate the registry — the
    same existence-oracle reasoning J.3 applies to nodes, applied to forests.
    """
    return _envelope(
        VineError(E_NOT_FOUND, f"unknown forest: {forest}",
                  hint="GET /v1/forests lists the forests available to you.")
    )


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args],
                         capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def stamp_principal(root: Path, principal: str, before: str | None) -> str | None:
    """Write the acting principal into the commit the engine just made (J.4).

    The engine commits with a fixed identity and the host may not change it
    (J.7 forbids engine edits), so the Station amends the message it just
    produced. Amending rewrites the sha, so the caller is handed the new one —
    a response carrying a sha that no longer exists would be worse than no
    attribution at all. Safe because forest access is serialised on one
    thread: nothing else can be committing in between.
    """
    after = _git(root, "rev-parse", "HEAD")
    if not after or after == before:
        return None
    message = _git(root, "log", "-1", "--format=%B")
    if "station-principal:" in message:
        return after
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=vine",
         "-c", "user.email=vine@monkeyllm.local", "commit", "--quiet", "--amend",
         "-m", f"{message.rstrip()}\n\nstation-principal: {principal}"],
        capture_output=True, text=True,
    )
    return _git(root, "rev-parse", "HEAD") or after


def build_app(
    *,
    root: str | Path,
    registry_path: str | Path,
    writable: bool = True,
    mcp: bool = True,
) -> Starlette:
    pool = ForestPool(root=Path(root), writable=writable)
    registry = Registry(registry_path)

    # A SQLite connection belongs to the thread that opened it, and the engine
    # rightly does not weaken that guarantee for the host's convenience. So the
    # Station confines every forest touch — open, call, close — to one
    # dedicated thread. It also keeps the blocking reads off the event loop.
    # Serialising across forests is a simplification; a worker per forest is
    # the scale-out step, and it changes nothing above this line.
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forest")

    async def in_forest_thread(fn):
        return await asyncio.get_running_loop().run_in_executor(worker, fn)

    mcp_lifespan = None  # set below when the MCP surface is mounted

    @asynccontextmanager
    async def lifespan(_app):
        async with AsyncExitStack() as stack:
            if mcp_lifespan is not None:
                await stack.enter_async_context(mcp_lifespan())
            try:
                yield
            finally:
                await in_forest_thread(pool.close)  # vines close in their own thread
                worker.shutdown(wait=True)
                registry.close()

    # -- auth ---------------------------------------------------------------

    def principal_of(request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        key = header[7:].strip() if header.lower().startswith("bearer ") else None
        return registry.authenticate(key or request.headers.get("x-api-key"))

    def require_principal(request: Request):
        principal = principal_of(request)
        if principal is None:
            return None, _envelope(VineError(E_FORBIDDEN, "missing or invalid API key"), 401)
        return principal, None

    def is_admin(principal: str, forest: str | None = None) -> bool:
        grants = registry.grants_of(principal)
        if forest is not None:
            grants = [g for g in grants if g["forest"] == forest]
        return any("admin" in g["caps"] for g in grants)

    # -- forest calls -------------------------------------------------------

    def run_primitive(principal: str, forest: str, name: str, payload: dict):
        """Executed on the forest thread: resolve, scope, call, attribute."""
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return None
        try:
            vine = pool.get(forest)
        except VineError:
            return None

        if name in COMPOSITES:
            result = run_composite(principal, forest, vine, policy, name, payload)
            registry.record(
                principal=principal, forest=forest, primitive=name, args=payload,
                result="error" if isinstance(result.get("error"), dict) else "ok",
                size=len(json.dumps(result, default=str)),
            )
            return result

        root_path = Path(vine.forest.root)
        before = _git(root_path, "rev-parse", "HEAD") if name in WRITE_PRIMITIVES else None
        result = ScopedVine(vine, policy).call(name, **payload)

        commit_sha = None
        if name in WRITE_PRIMITIVES and isinstance(result, dict) and "error" not in result:
            commit_sha = stamp_principal(root_path, principal, before)
            if commit_sha and result.get("commit"):
                result["commit"] = commit_sha
            if isinstance(result.get("trail"), list):
                result["trail"] = [t for t in result["trail"] if policy.in_scope(t)]

        registry.record(
            principal=principal, forest=forest, primitive=name, args=payload,
            result="error" if (isinstance(result, dict) and "error" in result) else "ok",
            size=len(json.dumps(result, default=str)), commit_sha=commit_sha,
        )
        return result

    def run_composite(principal, forest, vine, policy, name, payload) -> dict:
        """Retrieval (scoped, deterministic) plus the forest's bound model.

        The model only ever sees material the principal could already read,
        so binding a model cannot become a way around the policy.
        """
        from monkeyllm_station import inference

        cap, role = COMPOSITES[name]
        if not policy.grants(cap):
            return VineError(E_FORBIDDEN, f"'{name}' requires the '{cap}' capability",
                             hint=f"This principal holds: {sorted(policy.caps)}.").to_dict()
        binding = registry.binding(forest, role)
        if binding is None:
            return VineError(
                E_SCHEMA, f"no model is bound to '{forest}' for the '{role}' role",
                hint="Bind one in Studio → Models, or POST /v1/admin/models.",
            ).to_dict()
        scoped = ScopedVine(vine, policy)
        try:
            if name == "answer":
                return inference.answer(scoped, payload.get("question") or
                                        payload.get("query") or "",
                                        binding, k=int(payload.get("k", 3)))
            return inference.recurate(scoped, payload.get("id"), binding)
        except VineError as e:
            return e.to_dict()
        except Exception as e:  # provider outages must not 500 the Station
            return VineError(E_SCHEMA, f"{name} failed: {e}"[:300]).to_dict()

    # -- routes -------------------------------------------------------------

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "mode": pool.mode})

    async def me(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        grants = registry.grants_of(principal)
        for g in grants:
            policy = registry.policy_for(principal, g["forest"])
            g["roots"] = policy.roots() if policy else []
        return JSONResponse({"principal": principal, "grants": grants,
                             "admin": is_admin(principal)})

    async def forests(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        granted = {g["forest"]: g for g in registry.grants_of(principal)}
        listed = []
        for f in pool.list()["forests"]:
            if f["id"] not in granted:
                continue
            policy = registry.policy_for(principal, f["id"])
            listed.append({**f, "caps": granted[f["id"]]["caps"],
                           "roots": policy.roots() if policy else []})
        return JSONResponse({"forests": listed, "mode": pool.mode})

    async def primitive(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err

        name = request.path_params["primitive"]
        if name not in SERVED_PRIMITIVES:
            return _envelope(
                VineError(E_NOT_FOUND, f"no such endpoint: {name}",
                          hint=f"Served primitives: {sorted(SERVED_PRIMITIVES)}.")
            )

        forest = request.path_params["forest"]
        try:
            payload = await request.json() if await request.body() else {}
        except json.JSONDecodeError as e:
            return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
        if not isinstance(payload, dict):
            return _envelope(VineError(E_SCHEMA, "body must be a JSON object"))

        result = await in_forest_thread(
            lambda: run_primitive(principal, forest, name, payload)
        )
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        return JSONResponse(result)

    # -- governance (J.5's console needs a surface, not a side-channel) ------

    async def admin_principals(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        if not is_admin(principal):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)
        people = registry.principals()
        for p in people:
            p["grants_detail"] = registry.grants_of(p["id"])
        return JSONResponse({"principals": people})

    async def admin_grant(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        body = await request.json()
        forest = body.get("forest")
        if not forest or not is_admin(principal, forest):
            return _envelope(
                VineError(E_FORBIDDEN, "requires the 'admin' capability on that forest"), 403
            )
        caps = set(body.get("caps") or ["read"])
        if caps - CAPS:
            return _envelope(VineError(E_SCHEMA, f"unknown capabilities: {sorted(caps - CAPS)}"))
        target = body.get("principal")
        if not target:
            return _envelope(VineError(E_SCHEMA, "principal is required"))
        try:
            registry.grant(target, forest, caps,
                           allow=body.get("allow"), deny=body.get("deny"),
                           tables=body.get("tables"))
        except ValueError as e:
            return _envelope(VineError(E_SCHEMA, str(e)))
        out = {"principal": target, "grants": registry.grants_of(target)}
        if body.get("issue_key"):
            out["api_key"] = registry.issue_key(target, label=forest)
        return JSONResponse(out)

    async def admin_audit(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        if not is_admin(principal):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)
        limit = min(int(request.query_params.get("limit", 100)), 500)
        return JSONResponse({"entries": registry.audit(limit=limit,
                                                       principal=request.query_params.get("principal"))})

    async def admin_providers(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        if not is_admin(principal):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)
        if request.method == "GET":
            return JSONResponse({"providers": registry.providers()})
        body = await request.json()
        try:
            if body.get("remove"):
                registry.delete_provider(body["name"])
            else:
                registry.put_provider(body.get("name"), body.get("endpoint"),
                                      body.get("api_key"))
        except (ValueError, KeyError) as e:
            return _envelope(VineError(E_SCHEMA, str(e)))
        return JSONResponse({"providers": registry.providers()})

    async def admin_provider_test(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        if not is_admin(principal):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)
        from monkeyllm_station import inference

        body = await request.json()
        secret = registry.provider_secret(body.get("name", ""))
        endpoint = body.get("endpoint") or (secret or {}).get("endpoint")
        if not endpoint:
            return _envelope(VineError(E_SCHEMA, "endpoint is required"))
        key = body.get("api_key") or (secret or {}).get("api_key")
        return JSONResponse(await asyncio.get_running_loop().run_in_executor(
            None, lambda: inference.probe(endpoint, key)))

    async def admin_models(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        if request.method == "GET":
            forest = request.query_params.get("forest")
            if not is_admin(principal, forest):
                return _envelope(VineError(E_FORBIDDEN, "requires 'admin' on that forest"), 403)
            return JSONResponse({"bindings": registry.bindings(forest)})
        body = await request.json()
        forest = body.get("forest")
        if not is_admin(principal, forest):
            return _envelope(VineError(E_FORBIDDEN, "requires 'admin' on that forest"), 403)
        try:
            if body.get("remove"):
                registry.unbind_model(forest, body.get("role"))
            else:
                registry.bind_model(forest, body.get("role"), body.get("provider"),
                                    body.get("model"),
                                    max_tokens=body.get("max_tokens", 600),
                                    reasoning=body.get("reasoning", "off"))
        except (ValueError, KeyError, TypeError) as e:
            return _envelope(VineError(E_SCHEMA, str(e)))
        return JSONResponse({"bindings": registry.bindings(forest)})

    async def studio_missing(request: Request):
        return JSONResponse(
            {"error": {"code": E_NOT_FOUND, "message": "the Studio build is not present",
                       "hint": "Run `npm ci && npm run build` in apps/studio "
                               "(the Docker image does this for you)."}},
            status_code=404,
        )

    routes = [
        Route("/v1/health", health),
        Route("/v1/me", me),
        Route("/v1/forests", forests),
        Route("/v1/admin/principals", admin_principals),
        Route("/v1/admin/grant", admin_grant, methods=["POST"]),
        Route("/v1/admin/audit", admin_audit),
        Route("/v1/admin/providers", admin_providers, methods=["GET", "POST"]),
        Route("/v1/admin/providers/test", admin_provider_test, methods=["POST"]),
        Route("/v1/admin/models", admin_models, methods=["GET", "POST"]),
        Route("/v1/forests/{forest}/{primitive}", primitive, methods=["POST"]),
    ]

    if mcp:
        from monkeyllm_station.mcp_surface import build_mcp_mount

        mcp_app, mcp_lifespan = build_mcp_mount(pool, registry, in_forest_thread,
                                                run_primitive)
        if mcp_app is not None:
            routes.append(Mount("/mcp", app=mcp_app))

    # Last: the SPA catch-all must not shadow the API routes above it.
    if (STUDIO_DIST / "index.html").is_file():
        routes.append(Mount("/", app=StaticFiles(directory=STUDIO_DIST, html=True)))
    else:
        routes.append(Route("/", studio_missing))

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.pool = pool
    app.state.registry = registry
    app.state.run_primitive = run_primitive
    return app
