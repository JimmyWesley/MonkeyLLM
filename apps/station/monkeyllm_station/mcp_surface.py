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
import json
import logging
import os
from typing import Literal

log = logging.getLogger("monkeyllm_station")


def package_version() -> str:
    """The installed build's number (J.1.2 rule 3), read from package
    metadata so the answer is what pip installed, never a hand-kept copy —
    a whole report cycle was once spent against a build nobody could
    identify."""
    try:
        from importlib.metadata import version

        return version("monkeyllm")
    except Exception:
        try:
            from monkeyllm import __version__

            return __version__
        except Exception:  # pragma: no cover - no package, no number
            return ""

ALLOWED_HOSTS_ENV = "MONKEYLLM_STATION_ALLOWED_HOSTS"
DEFAULT_ALLOWED_HOSTS = "localhost,localhost:8800,127.0.0.1,127.0.0.1:8800,testserver"
# J.1.1 (v0.52): the host-level code for a transport refusal. It lives here,
# beside the surface that can be refused, on the same terms as E_FORBIDDEN
# living beside the policy that decides it.
E_HOST_NOT_ALLOWED = "E_HOST_NOT_ALLOWED"


# Names that mean "this machine". A list built only from these is a local
# install's list, however it got there — which is the state J.1.1 rule 2
# warns about, and `docker-compose.yml` reaches it by SETTING the variable
# to that default rather than by leaving it unset.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0",
                         "[::1]", "testserver"})


def local_only(hosts: list[str]) -> bool:
    return bool(hosts) and all(h.rsplit(":", 1)[0] in LOCAL_HOSTS or h in LOCAL_HOSTS
                               for h in hosts)


def allowed_hosts() -> list[str]:
    """The deployment's list, read per call — a Station and its tests see the
    environment they run under."""
    raw = os.environ.get(ALLOWED_HOSTS_ENV, DEFAULT_ALLOWED_HOSTS)
    return [h.strip() for h in raw.split(",") if h.strip()]


def _settings(hosts: list[str]):
    from mcp.server.transport_security import TransportSecuritySettings

    return TransportSecuritySettings(
        enable_dns_rebinding_protection="*" not in hosts,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts],
    )


def host_allowed(host: str | None) -> bool | None:
    """Would the MCP mount accept this `Host`? (J.1.1 rule 3)

    Answered by the SDK's own validator rather than by a second reading of
    the same list — an exact match here and a wildcard-port match there
    would make `/v1/health` say the opposite of what MCP does, which is
    worse than saying nothing. `None` means the guard could not be asked,
    and the field then says exactly that.
    """
    try:
        from mcp.server.transport_security import TransportSecurityMiddleware
    except ImportError:  # pragma: no cover - mcp is an engine dependency
        return None
    guard = TransportSecurityMiddleware(_settings(allowed_hosts()))
    if not guard.settings.enable_dns_rebinding_protection:
        return True
    validate = getattr(guard, "_validate_host", None)
    if validate is None:  # pragma: no cover - the SDK renamed its check
        return None
    return bool(validate(host))


def _refusal_body(host: str | None) -> bytes:
    """J.1.1 rule 1: the refusal wears the envelope.

    The host named here is the one the caller sent — a quotation, not a
    disclosure — and the allow-list is never printed.
    """
    return json.dumps({"error": {
        "code": E_HOST_NOT_ALLOWED,
        "message": f"the MCP surface does not answer to Host {host or '(absent)'!r}",
        "hint": f"Add that host to {ALLOWED_HOSTS_ENV} (comma-separated) and "
                "restart the Station. Do not use '*': it turns off Origin "
                "checking as well.",
    }}, ensure_ascii=False).encode("utf-8")

PRINCIPAL: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "station_principal", default=None
)
# J.2.6: the capability mask riding on the key that authenticated this
# request. Published beside PRINCIPAL by the same middleware, for the same
# reason — and, like PRINCIPAL, it must be read on the request's own task:
# a contextvar does not cross `in_forest_thread`.
CAPS_MASK: contextvars.ContextVar[frozenset | None] = contextvars.ContextVar(
    "station_caps_mask", default=None
)

UNAUTHENTICATED = {
    "error": {"code": "E_FORBIDDEN", "message": "missing or invalid API key",
              "hint": "Send Authorization: Bearer <key>."}
}

# J.1.2 rule 5 (v0.55): these instructions are the one description of the
# surface every client receives unasked, and an agent that trusts them uses
# exactly what they name — so every registered tool is named here, and
# tests/test_v055_lock.py compares the two lists mechanically.
INSTRUCTIONS = (
    "Governed MonkeyLLM forests. Call forests() first: it returns the "
    "forests this key may use, each with its capabilities, the `roots` to "
    "start from (a scoped key has no access to the master _index), and "
    "`locked: true` while a forest temporarily cannot serve. "
    "Retrieval: harvest(forest, query) for one-shot ranked evidence; "
    "answer(forest, question) for a grounded reply from the forest's own "
    "model. Navigate: locate(forest, query) ranks entry points over "
    "curated metadata (titles, summaries, tags — never bodies); "
    "look(forest, id) is a cheap digest, up to 10 ids per call; "
    "pick(forest, id) opens the body or one section, up to 5 ids; "
    "move(forest, id) follows typed edges; scan(forest, parent_id) lists "
    "a branch — pass after=\"\" and follow `next` to enumerate a whole "
    "forest; sniff(forest, terms) greps exact terms inside bodies; "
    "calendar(forest) maps where material sits in time; "
    "view(forest, id) shows the image behind a type:media node; "
    "query(forest, id, sql) runs read-only SQL on type:dataset nodes. "
    "Write, per capability: plant(forest, node) creates, "
    "graft(forest, id, patch) edits, tend(forest, id, sql) is single-"
    "statement dataset DML, ingest(forest, ...) sends documents through "
    "the Gardener. Anything outside your scope reports E_NOT_FOUND, "
    "exactly as a missing node does."
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

    # DNS-rebinding protection defends servers that trust the browser's
    # ambient credentials; every request here carries an API key the attacker
    # cannot supply, so the deployment's own host list is the right control
    # rather than a hardcoded one. Operators name their hosts; the default
    # covers a local install.
    hosts = allowed_hosts()
    security = _settings(hosts)
    # J.1.1 rule 2 (v0.52): a deployment whose main surface cannot answer
    # must not boot silently. Published under a domain, the default list
    # refuses every MCP request — while REST, Studio and /v1/health all stay
    # green, so nothing else the operator looks at says so.
    if "*" in hosts:
        log.warning(
            "%s contains '*': DNS-rebinding protection AND Origin checking "
            "are off for the MCP surface. Name your hosts instead.",
            ALLOWED_HOSTS_ENV)
    elif local_only(hosts):
        # Read off the effective list, not off "did somebody set the
        # variable": the shipped compose file sets it TO the local default,
        # so a check for an unset variable would stay quiet in exactly the
        # deployment this warning exists for.
        log.warning(
            "%s names local addresses only (%s): the MCP surface will "
            "refuse every request under a domain with 421, while REST, "
            "Studio and /v1/health all stay green. Name your domain there.",
            ALLOWED_HOSTS_ENV, ", ".join(hosts))

    mcp = MCPServer("monkeyllm-station", instructions=INSTRUCTIONS,
                    version=package_version())
    # J.1.2 rule 4: no empty promises. The SDK registers resource/prompt
    # handlers unconditionally and derives capabilities from their
    # presence; this Station serves neither, so announcing them makes
    # every connecting client spend two round trips to learn "empty".
    try:
        handlers = mcp._lowlevel_server._request_handlers
        for method in ("prompts/list", "prompts/get", "resources/list",
                       "resources/templates/list", "resources/read",
                       "resources/subscribe", "resources/unsubscribe",
                       "subscriptions/listen"):
            handlers.pop(method, None)
    except AttributeError:  # pragma: no cover - the SDK moved its registry
        pass

    from mcp.types import CallToolResult, TextContent

    def compact(result) -> str:
        # J.1.2 rule 1: the block goes into a model's context, billed by
        # the token. Pretty-printing measured at 15-30% of every read.
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"),
                          default=str)

    def done(result) -> CallToolResult:
        # J.1.2 rule 2: the protocol's flag and the C.12 envelope are two
        # spellings of one fact, and a harness reads exactly one of them.
        return CallToolResult(
            content=[TextContent(type="text", text=compact(result))],
            is_error=isinstance(result, dict) and "error" in result,
        )

    async def run(forest: str, name: str, **kwargs) -> dict:
        principal = PRINCIPAL.get()
        if principal is None:
            return UNAUTHENTICATED
        # Read HERE, before the lane: the lambda below runs on the forest
        # thread, where this request's contextvars do not exist (J.2.6).
        mask = CAPS_MASK.get()
        result = await in_forest_thread(
            forest, lambda: run_primitive(principal, forest, name, kwargs,
                                          caps_mask=mask)
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

    async def call(forest: str, name: str, **kwargs) -> CallToolResult:
        # One seam for every tool (J.1.2): the dict becomes the compact
        # block here, and the flag is set beside it.
        return done(await run(forest, name, **kwargs))

    @mcp.tool()
    async def forests():
        """List the forests this key may use, with capabilities and roots."""
        principal = PRINCIPAL.get()
        if principal is None:
            return done(UNAUTHENTICATED)
        mask = CAPS_MASK.get()
        granted = {g["forest"]: g for g in registry.grants_of(principal)}
        out = []
        for f in pool.list()["forests"]:
            if f["id"] not in granted:
                continue
            policy = registry.policy_for(principal, f["id"])
            caps = granted[f["id"]]["caps"]
            if mask is not None:
                # J.2.6: what an agent is told it may do is what the key
                # can actually do — same rule as /v1/me for a console.
                caps = sorted(set(caps) & mask)
            entry = {"id": f["id"], "caps": caps,
                     "roots": policy.roots() if policy else []}
            if f.get("locked"):
                # J.1.3: the first call the instructions prescribe must
                # not send the agent into a room that does not open.
                entry["locked"] = True
            out.append(entry)
        return done({"forests": out})

    @mcp.tool()
    async def locate(forest: str, query: str, k: int = 5, scope: str = "all",
                     type_filter: str | None = None,
                     include: list[str] | None = None,
                     since: str | None = None, until: str | None = None,
                     date_field: str | None = None):
        """Drop near the answer: ranked entry points over curated metadata —
        titles, summaries and tags, never bodies. Each result carries
        `body_tokens`, so you can size what you are about to open;
        `include=["outline"]` adds each result's section headers, which is
        what `pick(section=…)` takes. An empty result says how many nodes
        were searched and points at `sniff`, which is where an exact term
        that nobody lifted into a summary is waiting.

        `since`/`until` (YYYY, YYYY-MM or YYYY-MM-DD, inclusive) bound the
        search to when nodes were created — `date_field="updated"` for when
        they last changed. Call `calendar` first to see which periods hold
        anything: an empty window says so explicitly rather than looking
        like an empty forest."""
        return await call(forest, "locate", query=query, k=k, scope=scope,
                          type_filter=type_filter, include=include,
                          since=since, until=until, date_field=date_field)

    @mcp.tool()
    async def look(forest: str, id: str | list[str],
                   fields: list[str] | None = None):
        """Cheap digest of one node: summary, edges, children, stats.

        `id` may be a list of up to 10 ids — one call, one budget: the
        answer is `{nodes, missing, dropped, truncated}`, every id you sent
        accounted for in exactly one of them (`missing` covers absent and
        out-of-scope alike)."""
        return await call(forest, "look", id=id, fields=fields)

    @mcp.tool()
    async def move(forest: str, id: str, rel: str | None = None,
                   direction: Literal["out", "in", "both"] = "out"):
        """Neighbours of a node along typed edges (rel='children' for a
        branch). `direction` is out | in | both — 'both' is this tool's
        word for every direction at once."""
        return await call(forest, "move", id=id, rel=rel, direction=direction)

    @mcp.tool()
    async def pick(forest: str, id: str | list[str],
                   section: str | None = None):
        """Harvest the body, or one section of it.

        `id` may be a list of up to 5 ids, sharing ONE 4000-token budget:
        whole bodies drop from the tail and are named in `dropped`, never
        sliced. `section` applies to every id in the batch."""
        return await call(forest, "pick", id=id, section=section)

    @mcp.tool()
    async def view(forest: str, id: str):
        """The image behind an in-scope media node, as MCP image content
        (spec C.6d). A media node's body is a machine-written description
        of the image; view() hands your model the pixels themselves —
        images only, local payloads only, bounded at 6 MiB. Returns a JSON
        header (id, media_type, size, payload_hash) beside the image block.
        Out-of-scope answers E_NOT_FOUND, exactly as a missing node does."""
        meta = await run(forest, "view", id=id)
        if not isinstance(meta, dict) or "error" in meta or "path" not in meta:
            return done(meta)
        from mcp.server.mcpserver.utilities.types import Image

        # The path is the lane's answer, never the caller's to see: the
        # bytes ride in the image block, the header carries identity only.
        path = meta.pop("path")
        fmt = meta["media_type"].split("/", 1)[1]
        return CallToolResult(content=[
            TextContent(type="text", text=compact(meta)),
            Image(path=path, format=fmt).to_image_content(),
        ])

    @mcp.tool()
    async def scan(forest: str, parent_id: str, filter: dict | None = None,
                   fields: list[str] | None = None,
                   recursive: bool = False, limit: int = 50,
                   after: str | None = None,
                   since: str | None = None, until: str | None = None,
                   date_field: str | None = None):
        """Filter a branch's nodes by metadata — and enumerate them.

        Budget: <= 800 tokens and <= 50 items per page, whichever cuts
        first; every response carries `total` (what the scope holds) and
        `returned`. To walk a whole forest, start
        `scan("_index", recursive=true, after="")` and keep passing the
        response's `next` back as `after` until none comes: id order, no
        loss, no duplicates. `fields` picks the columns (default
        id/type/summary/body_tokens); `since`/`until` bound it by date."""
        return await call(forest, "scan", parent_id=parent_id, filter=filter,
                          fields=fields, recursive=recursive, limit=limit,
                          after=after, since=since,
                          until=until, date_field=date_field)

    @mcp.tool()
    async def sniff(forest: str, terms: list[str], scope: str | None = None,
                    k: int = 5, since: str | None = None,
                    until: str | None = None,
                    date_field: str | None = None):
        """Literal search inside bodies — the facts summaries do not carry.

        `since`/`until` bound it by date, and here that is also the cheapest
        thing you can do: a windowed sniff opens the files of those days and
        no others."""
        return await call(forest, "sniff", terms=terms, scope=scope, k=k,
                          since=since, until=until, date_field=date_field)

    @mcp.tool()
    async def harvest(forest: str, query: str, terms: list[str] | None = None,
                      k: int = 3, since: str | None = None,
                      until: str | None = None,
                      date_field: str | None = None):
        """One-shot retrieval: ranked evidence with exact snippets, no hops.
        `since`/`until` bound both of its legs to a period."""
        return await call(forest, "harvest", query=query, terms=terms, k=k,
                          since=since, until=until, date_field=date_field)

    @mcp.tool()
    async def calendar(forest: str, scope: str | None = None,
                       date_field: str = "created",
                       granularity: str = "month",
                       since: str | None = None, until: str | None = None,
                       limit: int = 24):
        """Where this forest's material sits in time: how many nodes each
        period holds, most recent first, read from curated metadata without
        opening anything.

        Call it when a question is about a period — "last week", "since the
        contract", "what changed in June". Each bucket carries the exact
        `since`/`until` that `locate`, `sniff`, `scan` and `harvest` take,
        so you never have to compute dates: read the period you want off
        this map and pass its two dates straight back. `granularity` is
        day | week | month | year, and `date_field="updated"` asks when
        nodes last changed rather than when they arrived."""
        return await call(forest, "calendar", scope=scope,
                          date_field=date_field, granularity=granularity,
                          since=since, until=until, limit=limit)

    @mcp.tool()
    async def answer(forest: str, question: str, k: int = 3,
                     cache: bool = True,
                     reply_tokens: int | None = None,
                     min_evidence: int = 0,
                     since: str | None = None,
                     until: str | None = None,
                     date_field: str | None = None):
        """Ask the forest directly: scoped retrieval read by the model bound
        to this forest, returning a grounded answer with its evidence. The
        one call that replaces a knowledge-base lookup plus a summarisation
        round-trip. A repeat of a question may be served from the forest's
        answer store, labelled `cached: true`; pass `cache: false` to skip
        the store and buy a fresh run (which replaces the stored one).
        `reply_tokens` bounds the reply's size per call (clamped to
        [64, 4000]); absent, the forest's own binding decides.
        `min_evidence` is the floor below which no model runs: the sweep's
        material is counted first and, if it is thinner than you asked for,
        the reply is `answer: null` with `reason: "insufficient_evidence"`
        and the retrieval attached — nothing is billed. Use it when you
        would rather see the evidence than a confident paragraph over two
        weak snippets.
        `since`/`until` bound the retrieval to a period, exactly as they do
        on `locate` — ask `calendar` which periods hold anything first."""
        return await call(forest, "answer", question=question, k=k,
                          cache=cache, since=since, until=until,
                          date_field=date_field,
                          **({"reply_tokens": reply_tokens}
                             if reply_tokens is not None else {}),
                          **({"min_evidence": min_evidence}
                             if min_evidence else {}))

    @mcp.tool()
    async def query(forest: str, id: str, sql: str):
        """Read-only SQL against a dataset node."""
        return await call(forest, "query", id=id, sql=sql)

    @mcp.tool()
    async def plant(forest: str, node: dict, if_absent: bool = False):
        """Create a node (needs the 'write' capability).

        A duplicate id is refused, so a write that timed out cannot simply
        be repeated — pass `if_absent=true` to make the call idempotent by
        id: it answers `created: false` for an id already taken, writing
        nothing and comparing nothing. Changing what is there is `graft`."""
        return await call(forest, "plant", node=node, if_absent=if_absent)

    @mcp.tool()
    async def graft(forest: str, id: str, patch: dict):
        """Edit a node (needs the 'write' capability)."""
        return await call(forest, "graft", id=id, patch=patch)

    @mcp.tool()
    async def tend(forest: str, id: str, sql: str):
        """Single-statement dataset write (needs the 'tend' capability)."""
        return await call(forest, "tend", id=id, sql=sql)

    @mcp.tool()
    async def ingest(forest: str, mode: str = "upload",
                     files: list[dict] | None = None, path: str | None = None,
                     dest: str | None = None, wait: bool = True):
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

    class HostRefusal:
        """J.1.1 rule 1: rewrite the transport guard's `421` body, never its
        verdict.

        The decision stays where it is made — one decider, as everywhere
        else in this codebase. What changes is that the nineteen bytes the
        SDK returns become the envelope every other refusal on this Station
        wears, naming the host that was refused and the variable that admits
        it. A caller that reads `Failed to connect` cannot act; a caller
        that reads this can.
        """

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.app(scope, receive, send)
            headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
            host = headers.get(b"host", b"").decode(errors="ignore")
            body = _refusal_body(host)
            refused = False

            async def send_wrapper(message):
                nonlocal refused
                if message["type"] == "http.response.start":
                    if message.get("status") == 421:
                        refused = True
                        message = dict(message)
                        message["headers"] = [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ]
                    return await send(message)
                if message["type"] == "http.response.body" and refused:
                    # Swallow the SDK's text; answer once, at the end.
                    if message.get("more_body"):
                        return
                    return await send({"type": "http.response.body",
                                       "body": body, "more_body": False})
                await send(message)

            await self.app(scope, receive, send_wrapper)

    class Authenticated:
        """Resolves the key once per request and publishes the principal
        and its J.2.6 capability mask side by side."""

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.app(scope, receive, send)
            headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
            auth = headers.get(b"authorization", b"").decode(errors="ignore")
            key = (auth[7:].strip() if auth.lower().startswith("bearer ")
                   else headers.get(b"x-api-key", b"").decode(errors="ignore"))
            resolved = registry.resolve_key(key)
            token = PRINCIPAL.set(resolved["principal"] if resolved else None)
            mask_token = CAPS_MASK.set(resolved["caps"] if resolved else None)
            try:
                await self.app(scope, receive, send)
            finally:
                CAPS_MASK.reset(mask_token)
                PRINCIPAL.reset(token)

    return Authenticated(HostRefusal(inner)), mcp.session_manager.run
