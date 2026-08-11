# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""The Station's MCP surface (spec J.1) — the same forests, the same policy,
spoken in the protocol agents already use.

This is what lets an existing agent harness point at a governed forest
instead of its own knowledge base: the tools are the Part C primitives, so a
client that works against `vine serve` works here, gaining only a key and a
scope.

Principal propagation: the mount runs in `stateless_http` mode, so each HTTP
request is handled in its own task and the `ContextVar` an ASGI middleware
sets is the one the tool body reads. With sessions enabled, a tool call could
be dispatched to a task created during an earlier request — the reason
statelessness is a correctness choice here, not a performance one.
"""

from __future__ import annotations

import contextvars
import os

PRINCIPAL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "station_principal", default=None
)

UNAUTHENTICATED = {
    "error": {"code": "E_FORBIDDEN", "message": "missing or invalid API key",
              "hint": "Send Authorization: Bearer <key>."}
}

INSTRUCTIONS = (
    "Governed MonkeyLLM forests. Call forests() first: it returns the forests "
    "this key may use and, for each, the `roots` to start from — a scoped key "
    "has no access to the master _index. Then harvest(forest, query) for "
    "one-shot retrieval, or navigate: look(forest, id), locate(forest, query), "
    "move(forest, id), sniff(forest, terms) for exact terms in bodies, "
    "pick(forest, id) to read, query(forest, id, sql) for datasets. "
    "Anything outside your scope reports E_NOT_FOUND, exactly as a missing "
    "node does."
)


def build_mcp_mount(pool, registry, in_forest_thread, run_primitive,
                    launch_ingest=None):
    """Returns `(asgi_app, session_lifespan)`.

    The session manager is started by the *parent* app's lifespan: a mounted
    Starlette app never gets its own lifespan run, and without it every
    request dies on "Task group is not initialized".

    `launch_ingest` starts an accepted batch's driver (spec J.9); the
    `ingest` tool waits on it by default, because an agent's poll loop
    would be context spent on plumbing.
    """
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError:  # pragma: no cover - mcp is an engine dependency
        return None, None

    from mcp.server.transport_security import TransportSecuritySettings

    # DNS-rebinding protection defends servers that trust the browser's
    # ambient credentials; every request here carries an API key the attacker
    # cannot supply, so the deployment's own host list is the right control
    # rather than a hardcoded one. Operators name their hosts; the default
    # covers a local install.
    hosts = [h.strip() for h in os.environ.get(
        "MONKEYLLM_STATION_ALLOWED_HOSTS",
        "localhost,localhost:8800,127.0.0.1,127.0.0.1:8800,testserver",
    ).split(",") if h.strip()]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection="*" not in hosts,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts],
    )

    mcp = MCPServer("monkeyllm-station", instructions=INSTRUCTIONS)

    async def call(forest: str, name: str, **kwargs) -> dict:
        principal = PRINCIPAL.get()
        if principal is None:
            return UNAUTHENTICATED
        result = await in_forest_thread(
            forest, lambda: run_primitive(principal, forest, name, kwargs)
        )
        if result is None:
            return {"error": {"code": "E_NOT_FOUND", "message": f"unknown forest: {forest}",
                              "hint": "Call forests() to list what this key may use."}}
        if isinstance(result, dict) and "_prepared" in result:
            # J.9: an accepted batch. Waiting is this surface's default —
            # kwargs carried the caller's choice through run_primitive.
            job = launch_ingest(result["_prepared"])
            if kwargs.get("wait", True) and job.task is not None:
                await job.task
            return {"job": job.snapshot()}
        return result

    @mcp.tool()
    async def forests() -> dict:
        """List the forests this key may use, with capabilities and roots."""
        principal = PRINCIPAL.get()
        if principal is None:
            return UNAUTHENTICATED
        granted = {g["forest"]: g for g in registry.grants_of(principal)}
        out = []
        for f in pool.list()["forests"]:
            if f["id"] not in granted:
                continue
            policy = registry.policy_for(principal, f["id"])
            out.append({"id": f["id"], "caps": granted[f["id"]]["caps"],
                        "roots": policy.roots() if policy else []})
        return {"forests": out}

    @mcp.tool()
    async def locate(forest: str, query: str, k: int = 5, scope: str = "all",
                     type_filter: str | None = None) -> dict:
        """Drop near the answer: ranked entry points over curated metadata."""
        return await call(forest, "locate", query=query, k=k, scope=scope,
                          type_filter=type_filter)

    @mcp.tool()
    async def look(forest: str, id: str, fields: list[str] | None = None) -> dict:
        """Cheap digest of one node: summary, edges, children, stats."""
        return await call(forest, "look", id=id, fields=fields)

    @mcp.tool()
    async def move(forest: str, id: str, rel: str | None = None,
                   direction: str = "out") -> dict:
        """Neighbours of a node along typed edges (rel='children' for a branch)."""
        return await call(forest, "move", id=id, rel=rel, direction=direction)

    @mcp.tool()
    async def pick(forest: str, id: str, section: str | None = None) -> dict:
        """Harvest the body, or one section of it."""
        return await call(forest, "pick", id=id, section=section)

    @mcp.tool()
    async def scan(forest: str, parent_id: str, filter: dict | None = None,
                   recursive: bool = False, limit: int = 50) -> dict:
        """Filter a branch's nodes by metadata."""
        return await call(forest, "scan", parent_id=parent_id, filter=filter,
                          recursive=recursive, limit=limit)

    @mcp.tool()
    async def sniff(forest: str, terms: list[str], scope: str | None = None,
                    k: int = 5) -> dict:
        """Literal search inside bodies — the facts summaries do not carry."""
        return await call(forest, "sniff", terms=terms, scope=scope, k=k)

    @mcp.tool()
    async def harvest(forest: str, query: str, terms: list[str] | None = None,
                      k: int = 3) -> dict:
        """One-shot retrieval: ranked evidence with exact snippets, no hops."""
        return await call(forest, "harvest", query=query, terms=terms, k=k)

    @mcp.tool()
    async def answer(forest: str, question: str, k: int = 3,
                     cache: bool = True) -> dict:
        """Ask the forest directly: scoped retrieval read by the model bound
        to this forest, returning a grounded answer with its evidence. The
        one call that replaces a knowledge-base lookup plus a summarisation
        round-trip. A repeat of a question may be served from the forest's
        answer store, labelled `cached: true`; pass `cache: false` to skip
        the store and buy a fresh run (which replaces the stored one)."""
        return await call(forest, "answer", question=question, k=k, cache=cache)

    @mcp.tool()
    async def query(forest: str, id: str, sql: str) -> dict:
        """Read-only SQL against a dataset node."""
        return await call(forest, "query", id=id, sql=sql)

    @mcp.tool()
    async def plant(forest: str, node: dict) -> dict:
        """Create a node (needs the 'write' capability)."""
        return await call(forest, "plant", node=node)

    @mcp.tool()
    async def graft(forest: str, id: str, patch: dict) -> dict:
        """Edit a node (needs the 'write' capability)."""
        return await call(forest, "graft", id=id, patch=patch)

    @mcp.tool()
    async def tend(forest: str, id: str, sql: str) -> dict:
        """Single-statement dataset write (needs the 'tend' capability)."""
        return await call(forest, "tend", id=id, sql=sql)

    @mcp.tool()
    async def ingest(forest: str, mode: str = "upload",
                     files: list[dict] | None = None, path: str | None = None,
                     dest: str | None = None, wait: bool = True) -> dict:
        """Put documents into the forest (needs the 'ingest' capability).

        `upload` sends the documents themselves as [{name, text}]; `adopt`
        and `sync` mirror a directory the Station host can read and
        additionally need 'admin'. Converters, summarisation and commits are
        the Gardener's, so an agent ingests exactly as an operator does.
        A batch runs as a job (spec J.9); by default this call waits for it
        and returns the finished job. Pass wait=false to get the running
        job's id back immediately instead.
        """
        return await call(forest, "ingest", mode=mode, files=files,
                          path=path, dest=dest, wait=wait)

    # Transport options belong to the app factory in mcp 2.x, not the
    # constructor. streamable_http_path="/" because this app gets mounted
    # under /mcp by the caller; leaving the default would serve it at /mcp/mcp.
    inner = mcp.streamable_http_app(
        streamable_http_path="/", stateless_http=True, json_response=True,
        transport_security=security,
    )

    class Authenticated:
        """Resolves the key once per request and publishes the principal."""

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.app(scope, receive, send)
            headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
            auth = headers.get(b"authorization", b"").decode(errors="ignore")
            key = (auth[7:].strip() if auth.lower().startswith("bearer ")
                   else headers.get(b"x-api-key", b"").decode(errors="ignore"))
            token = PRINCIPAL.set(registry.authenticate(key))
            try:
                await self.app(scope, receive, send)
            finally:
                PRINCIPAL.reset(token)

    return Authenticated(inner), mcp.session_manager.run
