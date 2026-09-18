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

import asyncio
import contextvars
import json
import logging
import os
from typing import Literal

log = logging.getLogger("monkeyllm_station")

# J.10.5 (v0.82): the `answer` tool takes the SDK's request context to
# report a hop as progress. Imported at module level because annotations
# are strings here (PEP 563) and the SDK evaluates them in this module's
# globals when it registers the tool; `mcp` is an engine dependency.
try:
    from mcp.server.mcpserver import Context
except ImportError:  # pragma: no cover - mcp is an engine dependency
    Context = None  # type: ignore[assignment,misc]


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


# J.1.2 rule 4: the two families this Station registers nothing behind, so
# announcing them would instruct every client to spend a round trip learning
# "empty". The list reaches those two families and stops there (amended
# v0.64): `subscriptions/listen` was on it once, and it is not a feature a
# client lists — at the 2026-07-28 era it is the only server-to-client
# channel, so withholding it ends the connection rather than saving anything
# (J.1.4). A test asserts the shape of this tuple for that reason.
def hybrid_ready(pool, registry, forest_id: str) -> bool:
    """K.3 (v0.82): whether `hybrid: true` would fuse the vector layer on
    this forest — an `embed` binding AND a canopy index built for that
    binding's model. Read off the registry row and the index manifest, never
    by opening the forest: this rides the listing every session starts
    with, and a listing touches no lane (J.9's rule for the job board). A
    half-written manifest reads as "not ready", never as an error."""
    try:
        from pathlib import Path

        from monkeyllm.canopy import CANOPY_DIRNAME

        binding = registry.binding(forest_id, "embed")
        root = getattr(pool, "root", None)
        if not binding or root is None:
            return False
        meta_path = Path(root) / forest_id / "_derived" / CANOPY_DIRNAME / "index.json"
        if not meta_path.is_file():
            return False
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return bool(meta.get("ids")) and meta.get("model") == binding.get("model")
    except Exception:
        return False


UNSERVED_METHODS = (
    "prompts/list", "prompts/get", "resources/list",
    "resources/templates/list", "resources/read",
    "resources/subscribe", "resources/unsubscribe",
)


def _is_jsonrpc_error(body: bytes) -> bool:
    """Whether these bytes are a JSON-RPC error object (J.1.4).

    The test is on the shape rather than on the code: every refusal the
    dispatcher spells is `{"jsonrpc": ..., "error": {...}}`, and a 404 the
    ROUTER spells (a wrong path under the mount) is not JSON at all. Any
    doubt answers False, because the fallback is the status the SDK chose.
    """
    if not body or len(body) > 64 * 1024:
        return False
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return False
    return (isinstance(parsed, dict) and parsed.get("jsonrpc") == "2.0"
            and isinstance(parsed.get("error"), dict))


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
    "start from (a scoped key has no access to the master _index), "
    "`locked: true` while a forest temporarily cannot serve, and "
    "`station`, this server's version — if it is newer than the skill "
    "you navigate by, tell your operator to re-download the skill. "
    "Retrieval: harvest(forest, query) for one-shot ranked evidence; "
    "answer(forest, question) for a grounded reply from the forest's own "
    "model — listed for a key holding the answer capability; hops=true "
    "makes it navigate the forest itself (one model call per hop, a walk "
    "may take minutes), detail=\"sources\" returns the reply and its "
    "citations without the excerpts, and a media:<id> inside a reply is an "
    "image you open with view(forest, id). hybrid=true on locate, harvest "
    "and answer fuses the vector layer into entry search where forests() "
    "reports hybrid: true, and the reply says whether it took part. "
    "Navigate: locate(forest, query) ranks entry points over "
    "curated metadata (titles, summaries, tags — never bodies); "
    "look(forest, id) is a cheap digest, up to 10 ids per call; "
    "pick(forest, id) opens the body — up to 5 ids, a list of sections, "
    "or page a large body with after=<next>; "
    "move(forest, id) follows typed edges; scan(forest, parent_id) lists "
    "a branch — pass after=\"\" and follow `next` to enumerate a whole "
    "forest; sniff(forest, terms, scope?) greps exact terms inside bodies "
    "(scope is a branch id or a node id); "
    "calendar(forest) maps where material sits in time; "
    "coverage(forest) says what the forest holds — the roots, their sizes "
    "and their sources — so a silence can be told from an absence; "
    "view(forest, id) shows the image behind a type:media node whose bytes "
    "are in the forest (look() says payload_missing when they are not); "
    "history(forest, id) says what happened to a node and who did it; "
    "query(forest, id, sql) runs read-only SQL on type:dataset nodes. "
    "Write, per capability: plant(forest, node) creates (a LIST of nodes "
    "lands in one commit or not at all), "
    "graft(forest, id, patch) edits, prune(forest, id) removes one node "
    "(force=true also strips its backlinks), "
    "transplant(forest, id, new_id) moves one to a new address and leaves "
    "the old id as a waymark, tend(forest, id, sql) is "
    "single-statement dataset DML, ingest(forest, mode=\"upload\", "
    "files=[{name, text|b64}]) sends documents through the Gardener — b64 "
    "for any file that is not text; an image or audio file becomes a "
    "type:media node and its bytes are what view() serves. plant() carries "
    "no bytes: a media node planted without a payload is refused. Anything "
    "outside your scope reports E_NOT_FOUND, exactly as a missing node does."
)


def build_mcp_mount(pool, registry, in_forest_thread, run_primitive,
                    launch_ingest=None, execute=None, extensions=None):
    """Returns `(asgi_app, session_lifespan)`.

    The session manager is started by the *parent* app's lifespan: a mounted
    Starlette app never gets its own lifespan run, and without it every
    request dies on "Task group is not initialized".

    `launch_ingest` starts an accepted batch's driver (spec J.9); the
    `ingest` tool waits on it by default, because an agent's poll loop
    would be context spent on plumbing.

    `execute` (J.6.2/J.10.11, v0.57) is the host's routed door — reader
    lanes for reads, the writer lane for writes, the three-phase sweep
    `answer`. When absent, calls take the writer lane as they always did.

    `extensions` (Part L, v0.80) is the loaded runtime. Its `tools` claims
    are published here, and the menu is filtered per key — see
    `_extension_tools` below for why that filter is the contract and not a
    refinement of it.
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
    # J.1.2 rule 4, and only what it names: see UNSERVED_METHODS.
    try:
        handlers = mcp._lowlevel_server._request_handlers
        for method in UNSERVED_METHODS:
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

    async def run(forest: str, name: str, *, progress=None, **kwargs) -> dict:
        # `progress` (J.10.5, v0.82) is keyword-only and never part of the
        # payload: it is the transport's observer, not the caller's argument.
        principal = PRINCIPAL.get()
        if principal is None:
            return UNAUTHENTICATED
        # Read HERE, before the lane: the lambda below runs on the forest
        # thread, where this request's contextvars do not exist (J.2.6).
        mask = CAPS_MASK.get()
        if execute is not None:
            result = await execute(principal, forest, name, kwargs, None, mask,
                                   progress=progress)
        else:
            sample = {"progress": progress} if progress is not None else None
            result = await in_forest_thread(
                forest, lambda: run_primitive(principal, forest, name, kwargs,
                                              caps_mask=mask, sample=sample)
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

    async def call(forest: str, name: str, *, progress=None,
                   **kwargs) -> CallToolResult:
        # One seam for every tool (J.1.2): the dict becomes the compact
        # block here, and the flag is set beside it.
        return done(await run(forest, name, progress=progress, **kwargs))

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
                     "roots": policy.roots() if policy else [],
                     # K.3 (v0.82): which forests have the vector layer.
                     "hybrid": hybrid_ready(pool, registry, f["id"])}
            if f.get("locked"):
                # J.1.3: the first call the instructions prescribe must
                # not send the agent into a room that does not open.
                entry["locked"] = True
            out.append(entry)
        # J.1.2 rule 6 (v0.56): the first reply states the version, where
        # the MODEL reads — a downloaded skill is a snapshot of this
        # surface, and this is what ages it visibly.
        return done({"forests": out, "station": package_version()})

    @mcp.tool()
    async def locate(forest: str, query: str, k: int = 5, scope: str = "all",
                     type_filter: str | None = None,
                     include: list[str] | None = None,
                     since: str | None = None, until: str | None = None,
                     date_field: str | None = None,
                     lang: str | None = None,
                     hybrid: bool = False):
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
        like an empty forest. `lang` filters by the node's declared
        language tag (A.3.2), exact match — a node that declares none is
        in no language filter. `type_filter` narrows to one node type: the
        pictures are `type_filter="media"`, not a query for the word.
        `hybrid: true` fuses the vector layer into the ranking where
        forests() reports `hybrid: true`; the reply says `hybrid` and,
        when the layer could not take part, `hybrid_reason`."""
        return await call(forest, "locate", query=query, k=k, scope=scope,
                          type_filter=type_filter, include=include,
                          since=since, until=until, date_field=date_field,
                          lang=lang,
                          **({"hybrid": True} if hybrid else {}))

    @mcp.tool()
    async def look(forest: str, id: str | list[str],
                   fields: list[str] | None = None):
        """Cheap digest of one node: summary, edges, children, provenance
        (created/updated/source, aliases and origin when set), stats.

        `id` may be a list of up to 10 ids — one call, one budget: the
        answer is `{nodes, missing, dropped, truncated}`, every id you sent
        accounted for in exactly one of them (`missing` covers absent and
        out-of-scope alike). `fields` names just the fields you want
        (e.g. ["summary"], ["edges_out","edges_in"]) and is the cost
        lever: a digest asked to carry less rarely clips at all. When the
        budget does clip, the clipped fields are NAMED in
        `truncated_fields` — an empty edge list without that flag really
        is empty, and `stats.degree` is the arithmetic truth either
        way. For a type:media node (or any node naming a `payload`) the
        digest says whether the bytes are in the forest: `payload_type`
        and `payload_bytes` when they are, `payload_missing: true` when
        they are not — ask this BEFORE view(), which answers a node
        without bytes exactly as it answers a missing node."""
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
                   section: str | list[str] | None = None,
                   after: str | None = None):
        """Harvest the body, or sections of it.

        `id` may be a list of up to 5 ids, sharing ONE 4000-token budget:
        whole bodies drop from the tail and are named in `dropped`, never
        sliced. `section` may be a list of up to 10 headers of one
        document — every name comes back in `sections`, `missing` or
        `dropped`, and each served section echoes the `header` that
        actually matched. A body over the budget arrives in PAGES: the response
        carries `next`, `returned` and `total`; pass `next` back as
        `after` until none comes, and the concatenated pages reproduce
        the body byte-identically. `section` applies to every id in a
        batch; `after` pages a single id."""
        return await call(forest, "pick", id=id, section=section, after=after)

    @mcp.tool()
    async def view(forest: str, id: str):
        """The image behind an in-scope media node, as MCP image content
        (spec C.6d). A media node's body is a machine-written description
        of the image; view() hands your model the pixels themselves —
        images only, local payloads only, bounded at 6 MiB. Returns a JSON
        header (id, media_type, size, payload_hash) beside the image block.
        Out-of-scope answers E_NOT_FOUND, exactly as a missing node does —
        and so does a media node whose bytes are not in the forest, on
        purpose (spec C.6d): ask look() first, a viewable node carries
        `payload_type` and `payload_bytes`, one without bytes carries
        `payload_missing`. Bytes reach a media node only through
        ingest(mode="upload", files=[{name, b64}]); plant() cannot attach
        them, and `origin` is a pointer the forest never follows."""
        # C.6d rule 2 (v0.84): a remote image resolves through the G.9
        # cache — the size decided by a HEAD before a byte moves, the 6 MiB
        # ceiling refusing an oversized object WITHOUT fetching it, and a
        # `payload_type: video` refused by type with the J.14 byte route
        # named. All of that is `Vine.view`'s, so it runs on the forest's
        # lane like every other primitive. LEFT OPEN, and named rather than
        # silent: J.10.11's argument applies to a provider round trip and a
        # store is one, so a 6 MiB object over a slow link holds the lane
        # for its whole fetch. Splitting `view` into resolve-then-fetch is
        # the repair — the resolve stays on the lane, the fetch goes off it
        # exactly as J.14's does in `app.py` — and it is an engine contract,
        # so it waits for a spec version rather than being improvised here.
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
        id/type/summary/body_tokens) — and it is the PAGE lever: the token
        budget cuts the page, so fewer fields per item means more items
        per page (`fields=["id"]` enumerates a large forest in a fraction
        of the calls). `filter` matches passport fields: `{"type": "media"}`
        lists the pictures, `{"source": "agent"}` what agents wrote. Without
        `recursive` only the DIRECT children are listed, and a root's direct
        children are its branches, not its documents. `since`/`until` bound
        it by date."""
        return await call(forest, "scan", parent_id=parent_id, filter=filter,
                          fields=fields, recursive=recursive, limit=limit,
                          after=after, since=since,
                          until=until, date_field=date_field)

    @mcp.tool()
    async def sniff(forest: str, terms: list[str], scope: str | None = None,
                    k: int = 5, type_filter: str | None = None,
                    since: str | None = None,
                    until: str | None = None,
                    date_field: str | None = None,
                    lang: str | None = None):
        """Literal search inside bodies — the facts summaries do not carry.

        `scope` is a branch id ("notes") or a node id, exactly as scan/look
        name it; omit it to search the whole forest. `_meta/` is the
        dialect, not content — pick("_meta/schema") reads it. `since`/`until`
        bound it by date, and here that is also the cheapest thing you can
        do: a windowed sniff opens the files of those days and no others.

        A KIND of node — the pictures, the datasets, the decisions — is
        `type_filter` ("media", "dataset", "note"), never a term: sniffing
        for the word "media" greps bodies for that word and returns every
        document that mentions it, and not one picture."""
        return await call(forest, "sniff", terms=terms, scope=scope, k=k,
                          type_filter=type_filter,
                          since=since, until=until, date_field=date_field,
                          lang=lang)

    @mcp.tool()
    async def harvest(forest: str, query: str, terms: list[str] | None = None,
                      k: int = 3, since: str | None = None,
                      until: str | None = None,
                      date_field: str | None = None,
                      lang: str | None = None,
                      include_superseded: bool = False,
                      hybrid: bool = False):
        """One-shot retrieval: ranked evidence with exact snippets, no hops.
        `since`/`until` bound both of its legs to a period.

        Every item states its time (`created`/`updated`), and a document
        that a live node `supersedes` is left OUT with its seat refilled —
        `superseded_excluded` names what was set aside and by what, so a
        replaced policy never answers for the current one.
        `include_superseded=true` brings the history back.
        `hybrid: true` fuses the vector layer into the entry search where
        forests() reports `hybrid: true`; the reply says `hybrid` and,
        when the layer could not take part, `hybrid_reason`."""
        return await call(forest, "harvest", query=query, terms=terms, k=k,
                          since=since, until=until, date_field=date_field,
                          lang=lang,
                          **({"hybrid": True} if hybrid else {}),
                          **({"include_superseded": True}
                             if include_superseded else {}))

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
    async def coverage(forest: str, scope: str | None = None,
                       date_field: str = "created"):
        """What this forest actually holds: the roots you can start from,
        how many nodes sit under each, where that material came from and
        when it arrived. Read from metadata alone — it opens nothing.

        Call it BEFORE trusting a silence. An empty result and a refusal
        both mean "not in the material I searched", and this is the only
        call that tells you what that material is. If the subject you were
        asked about has no root here, say so and look elsewhere — a forest
        answering faithfully from a partial corpus produces a citation, a
        source and a wrong answer, which is the one failure that looks
        exactly like a right one.

        Each root carries `origin` (the source prefix `scan`'s
        `origin_prefix` filter takes, so you can list what came from it
        without composing anything) and `without_origin`, the count of its
        nodes that declare no source at all. `scope` narrows everything to
        one branch."""
        return await call(forest, "coverage", scope=scope,
                          date_field=date_field)

    @mcp.tool()
    async def answer(forest: str, question: str, ctx: Context, k: int = 3,
                     terms: list[str] | None = None,
                     hops: bool | int | None = None,
                     detail: Literal["full", "sources", "answer"] | None = None,
                     hybrid: bool = False,
                     cache: bool = True,
                     reply_tokens: int | None = None,
                     min_evidence: int = 0,
                     min_score: float = 0.0,
                     since: str | None = None,
                     until: str | None = None,
                     date_field: str | None = None,
                     include_superseded: bool = False):
        """Ask the forest directly: scoped retrieval read by the model bound
        to this forest, returning a grounded answer with its evidence. The
        one call that replaces a knowledge-base lookup plus a summarisation
        round-trip. Listed for a key holding the `answer` capability.
        A repeat of a question may be served from the forest's
        answer store, labelled `cached: true`; pass `cache: false` to skip
        the store and buy a fresh run (which replaces the stored one).
        `hops` makes the forest's model NAVIGATE instead of reading one
        ranked bundle: `true` for the default budget, an integer for your
        own. Every hop is one model call and the walk holds a reader lane
        for its whole duration — a walk may take minutes, so raise your
        client's timeout or ask for progress (a `progressToken` on the
        request receives one notification per hop). `terms` is refused
        beside `hops`: a walk authors its own retrieval.
        `detail` is the size of the response: `full` (default) is the whole
        record, excerpts and trace included; `sources` keeps the reply, its
        citations (`sources[]`: id, title, summary, type, trail), the
        evidence ids and the hop records, and drops the excerpts and the
        trace; `answer` keeps the reply and the evidence ids only. Choose
        `sources` when the forest's model did the reading so yours would
        not have to — `pick(forest, id)` opens any cited node in full.
        A `![caption](media:<id>)` in the reply, or a `sources[]` item of
        type `media`, is an image the forest holds: open it with
        `view(forest, id)` if your model can see images. The bytes never
        ride this response.
        `terms` hands the sweep the literal words its `sniff` leg should
        look for, exactly as `harvest` takes them. Absent, they are derived
        from the question — which is the wrong move whenever the question's
        vocabulary is not the corpus's: a question in one language over a
        forest written in another, or a word the material spells some other
        way. You hold a model; translate the question into the forest's own
        terms and pass them here rather than letting the derivation guess.
        `reply_tokens` bounds the reply's size per call (clamped to
        [64, 4000]); absent, the forest's own binding decides.
        `min_evidence` is the floor below which no model runs: the sweep's
        material is counted first and, if it is thinner than you asked for,
        the reply is `answer: null` with `reason: "insufficient_evidence"`
        and the retrieval attached — nothing is billed. Use it when you
        would rather see the evidence than a confident paragraph over two
        weak snippets. `min_score` is the other half of that floor: an item
        counts as evidence only if its retrieval score reaches it, so a
        handful of barely-related snippets no longer satisfies
        `min_evidence`. The score is a rank artifact (~0.016 means "top of
        one retriever", ~0.033 "top of both"), comparable inside this
        deployment and meaningless outside it — read a few answers'
        `harvest` scores before choosing a number.
        `since`/`until` bound the retrieval to a period, exactly as they do
        on `locate` — ask `calendar` which periods hold anything first.
        A document a live node `supersedes` is left out of the material by
        default and named in `superseded_excluded`;
        `include_superseded: true` answers from the history too.
        `hybrid: true` fuses the vector layer into the sweep's entry
        search where forests() reports `hybrid: true`; the reply says
        `hybrid` and, when the layer could not take part, `hybrid_reason`
        — never silence."""
        progress = None
        pending: list = []
        if hops:
            # J.10.5 (v0.82): one protocol progress notification per hop.
            # The observer runs on the forest lane; the notification is sent
            # from the loop, and the SDK makes it a no-op when the request
            # carried no `progressToken`. A failed send never fails the hunt.
            loop = asyncio.get_running_loop()
            budget = 6 if hops is True else int(hops)

            async def _send(n: int, message: str) -> None:
                try:
                    await ctx.report_progress(n, budget, message)
                except Exception:
                    log.debug("progress notification failed on hop %s", n,
                              exc_info=True)

            def _schedule(n: int, message: str) -> None:
                # On the loop thread: the task is kept so the result waits
                # for every report it preceded — a hop's notification comes
                # BEFORE the answer, never after.
                pending.append(loop.create_task(_send(n, message)))

            def progress(hop: dict) -> None:
                n = int(hop.get("n") or 0)
                out = hop.get("out") or {}
                said = (", ".join(f"{k} {v}" for k, v in out.items())
                        if isinstance(out, dict) and out else "")
                message = (f"hop {n}/{budget}: {hop.get('tool')} → "
                           f"{said or ('ok' if hop.get('ok') else 'refused')}")
                try:
                    loop.call_soon_threadsafe(_schedule, n, message)
                except RuntimeError:  # loop shutting down
                    pass

        result = await call(forest, "answer", progress=progress,
                          question=question, k=k,
                          terms=terms,
                          cache=cache, since=since, until=until,
                          date_field=date_field,
                          **({"hops": hops} if hops is not None else {}),
                          **({"detail": detail} if detail is not None else {}),
                          **({"hybrid": True} if hybrid else {}),
                          **({"reply_tokens": reply_tokens}
                             if reply_tokens is not None else {}),
                          **({"min_evidence": min_evidence}
                             if min_evidence else {}),
                          **({"min_score": min_score}
                             if min_score else {}),
                          **({"include_superseded": True}
                             if include_superseded else {}))
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return result

    @mcp.tool()
    async def query(forest: str, id: str, sql: str):
        """Read-only SQL against a dataset node."""
        return await call(forest, "query", id=id, sql=sql)

    @mcp.tool()
    async def plant(forest: str, node: dict | list[dict],
                    if_absent: bool = False, dry_run: bool = False):
        """Create a node (needs the 'write' capability).

        `node` (spec A.3/C.7): required `id` (a path under its parent —
        the id IS the address and it is forever; every intermediate level
        must already exist as a branch), `type` (declared in this forest's
        `_meta/schema` — pick("_meta/schema") before your first write in
        an unknown forest), `title`, `summary` (1-3 sentences, <= 60
        tokens — the scent every search finds this node by), `parent`
        (the branch `_index` id, determined by the id). Optional: `body`
        (markdown), `tags`, `aliases` (the findability lever — the names
        people will actually type: a ticket code, a short name; locate
        reads curated metadata and never bodies), `links` ([{rel,
        target}], rels from `_meta/schema`), `origin` (one URI: where
        this document came from), `source`, `confidence`. For
        type:dataset pass `schema` and the Vine births the SQLite payload
        (spec C.7.1). For type:media, `payload` is REQUIRED and must name
        a file already in the forest (spec C.7.5): plant carries no bytes.
        To add an image or audio file, do not plant — send it through
        ingest(mode="upload", files=[{name, b64}]), which plants the media
        node, keeps the bytes and writes the description for you.

        A duplicate id is refused, so a write that timed out cannot simply
        be repeated — pass `if_absent=true` to make the call idempotent by
        id: it answers `created: false` for an id already taken, writing
        nothing and comparing nothing. Changing what is there is `graft`.
        `dry_run=true` rehearses: every validation, no write, no commit —
        answers `{valid: true}` or the exact error the real call would
        raise (spec C.7.3); use it before shipping a large body.
        `node` may be a LIST of up to 20 nodes (spec C.7.4): every one is
        validated BEFORE any is written and the whole batch lands in one
        commit or none of it does — so a set of related documents and the
        links between them never exists half-built. The answer is
        `{created, existing, commit, count}`. Plant datasets (`schema`)
        one at a time."""
        return await call(forest, "plant", node=node, if_absent=if_absent,
                          dry_run=dry_run)

    @mcp.tool()
    async def graft(forest: str, id: str, patch: dict):
        """Edit a node (needs the 'write' capability).

        `patch` operations (spec C.8): `set_frontmatter` (mutable fields:
        title, summary, tags, confidence, aliases, origin),
        `append_section`/`replace_section` ({header, body}),
        `replace_body`, `add_links`/`remove_links` ([{rel, target}]). An
        unknown key is refused naming the accepted set. A body edit
        without a summary edit answers `summary_stale: true` — refresh
        the summary when the content moved."""
        return await call(forest, "graft", id=id, patch=patch)

    @mcp.tool()
    async def prune(forest: str, id: str, force: bool = False):
        """Remove one node (needs the 'write' capability, spec C.14).

        The passport leaves through git — history keeps it — the parent
        index is refreshed and a local payload moves to the graveyard.
        A node other nodes point at refuses with E_ANCHORED listing the
        anchors; `force=true` removes it and strips those backlinks in
        the same commit. A branch with children never prunes — remove
        the children first. A pruned id is free to plant again."""
        return await call(forest, "prune", id=id, force=force)

    @mcp.tool()
    async def transplant(forest: str, id: str, new_id: str):
        """Move one leaf node to a new address (needs 'write', spec C.15).

        The repair for a misplaced document: the passport moves, every
        node pointing at it follows, both parent indexes are refreshed and
        a local payload travels along — one commit for the lot. The old id
        becomes a WAYMARK: `locate` still finds the node by it, and a read
        of the old id answers E_MOVED naming where it went. Branches do
        not transplant — move their leaves. A pointing node outside your
        scope refuses the whole move rather than silently dropping the
        link."""
        return await call(forest, "transplant", id=id, new_id=new_id)

    @mcp.tool()
    async def history(forest: str, id: str, limit: int = 20):
        """What happened to this node, and who did it (spec C.16).

        The node's commits, newest first, across renames: each carries the
        full timestamp (`at`, with time of day — frontmatter dates are
        day-precision), the `action` (plant, graft, tend, transplant,
        gardener(sync), ranger(promote)…), the commit subject, and `by`
        when the write went through a Station that stamped its principal.
        A listing, not time travel: it says what happened, not what the
        body said at the time."""
        return await call(forest, "history", id=id, limit=limit)

    @mcp.tool()
    async def tend(forest: str, id: str, sql: str):
        """Single-statement dataset write (needs the 'tend' capability)."""
        return await call(forest, "tend", id=id, sql=sql)

    @mcp.tool()
    async def ingest(forest: str, mode: str = "upload",
                     files: list[dict] | None = None, path: str | None = None,
                     dest: str | None = None, wait: bool = True,
                     source: str | None = None, curate: bool | None = None,
                     content: str | None = None):
        """Put documents into the forest (needs the 'ingest' capability).

        `upload` sends the documents themselves as [{name, text}] — or
        [{name, b64}] for ANY file that is not text (the raw bytes, base64):
        this is the one path bytes take into a forest. What a file becomes
        is decided by its extension: .md/.txt land as notes; .csv/.json/
        .xlsx/.xls/.db/.sqlite as datasets; .docx as a document (when the
        deployment carries that converter); .png/.jpg/.jpeg/.gif/.webp and
        .mp3/.wav/.m4a/.ogg/.flac as type:media nodes whose bytes are kept
        in the forest — view() shows an image, and a vision model writes
        its description when one is bound. A file no converter claims is
        named in the job report as `unsupported` and nothing is planted.
        `adopt` and `sync` mirror a directory the Station host can read and
        additionally need 'admin'. Converters, summarisation and commits are
        the Gardener's, so an agent ingests exactly as an operator does.
        A batch runs as a job (spec J.9); by default this call waits for it
        and returns the finished job. Pass wait=false to get the running
        job's id back immediately instead.

        `dest` names an existing branch, in either spelling: "notes" and
        "notes/_index" are the same destination. An upload entry may carry
        `source_url` — for an uploaded document that IS its `origin`, and
        nothing else fills it.

        An upload entry may also carry `passport: {title?, summary?, tags?,
        aliases?, links?: [{target, note?}], notes?}` — the scent YOU already
        know for what the bytes become (a screenshot you have seen, a file
        you wrote). Bytes alone are a picture nobody can find; a passport is
        what locate() searches. An entry with a passport is never sent to
        the curation model: what you declare is what is planted, after the
        same checks a reviewed draft gets (summary within the A.4 budget,
        tags cleaned, links `related-to` only, to existing in-scope nodes,
        at most 3). `notes` becomes the node's `## Notes` section. A
        malformed passport is refused before any byte stages.

        `source` names an object store prefix — `s3://bucket/prefix` — for
        `adopt` and `sync`, and needs 'admin' for a second reason: it spends
        the deployment's stored credentials against a store an operator
        configured. A bucket no configured store serves is refused before
        anything is listed. `curate: false` lands the documents with derived
        summaries and calls no model, which is what makes ten thousand
        objects searchable this afternoon instead of after ten thousand
        model calls; the report says the curation was skipped and whether a
        model IS bound, so the pass can be run later. `content` is `inline`
        or `cached` — a bucket source defaults to `cached`, so the bodies
        live in `_derived/` and the map stays small.
        """
        # C.12: `source`, `curate` and `content` are declared in
        # `SIGNATURES["ingest"]` (src/monkeyllm/signatures.py) beside
        # `mode`/`files`/`path`/`dest`/`wait`, so a J.1.2 r8 restatement of
        # an SDK validation error naming one of them says what it is and
        # what was expected instead of "unknown parameter".
        return await call(forest, "ingest", mode=mode, files=files,
                          path=path, dest=dest, wait=wait, source=source,
                          curate=curate, content=content)

    # ======================================================================
    # Part L — extension tools (L.3, L.7 rule 2)
    # ======================================================================
    #
    # `tools/list` is per CONNECTION and enablement is per FOREST, so the
    # menu a key sees is **the union of the extensions enabled on the
    # forests that key reaches**. Two consequences are deliberate: two keys
    # on one deployment can see different menus, and an extension enabled
    # nowhere the key reaches is invisible rather than merely refusing —
    # a tool that only ever refuses costs every session its description and
    # teaches nothing (v0.60's rule about what a menu is for).
    #
    # The per-call check is separate and is the real gate: listing is about
    # what is worth showing, calling is about what is allowed.

    EXTENSION_TOOLS: dict[str, object] = {}

    def _ext_forests_for(principal: str, ext_id: str) -> list[str]:
        """Forests this principal reaches where this extension is enabled."""
        if extensions is None or principal is None:
            return []
        out = []
        for grant in registry.grants_of(principal):
            forest = grant["forest"]
            root = pool.root / forest if pool.root is not None else None
            if root is None or not root.is_dir():
                continue
            try:
                if ext_id in extensions.enabled_for(forest, root):
                    out.append(forest)
            except Exception:
                continue
        return out

    def _make_extension_tool(claim, name):
        _claim_id = claim.ext_id
        """One tool, closed over its claim.

        A closure factory rather than default arguments: the SDK reads the
        signature to build the tool's schema and refuses a parameter whose
        name starts with `_`, so the carrying trick would make the tool
        unregistrable. It also resolves annotations against the MODULE's
        globals, which is why nothing here is annotated with a name imported
        inside this factory.
        """

        async def handler(forest: str, args: dict = None):
            principal = PRINCIPAL.get()
            if principal is None:
                return done(UNAUTHENTICATED)
            # The gate, and it is separate from the menu on purpose: listing
            # is about what is worth showing, calling is about what is
            # allowed. An extension not enabled on THIS forest is not an
            # extension this call may reach, whatever the menu said.
            if forest not in _ext_forests_for(principal, claim.ext_id):
                return done({"error": {
                    "code": "E_NOT_FOUND",
                    "message": f"unknown tool on this forest: {name}",
                    "hint": "An extension acts where an administrator "
                            "enabled it. forests() lists what this key "
                            "may use."}})
            try:
                # L.6: the handler's model access resolves the forest and
                # the principal from here — `register(api)` ran once at boot
                # and could know neither.
                from monkeyllm_station.extensions import EXT_CONTEXT

                def _run():
                    token = EXT_CONTEXT.set({"forest": forest,
                                             "principal": principal,
                                             "ext": _claim_id})
                    try:
                        return claim.handler(**(args or {}))
                    finally:
                        EXT_CONTEXT.reset(token)

                value = await in_forest_thread(forest, _run)
            except Exception as exc:
                # L.7 rule 5: contained, named, and never a host failure.
                return done({"error": {
                    "code": "E_EXT_WORKER",
                    "message": f"{claim.ext_id}: {name} failed",
                    "hint": f"{type(exc).__name__}: {exc}"}})
            return done(value if isinstance(value, dict)
                        else {"result": value})

        handler.__name__ = name
        handler.__doc__ = (str(claim.spec.get("description") or "").strip()
                           or f"Contributed by the {claim.ext_id} extension.")
        return handler

    def _register_extension_tools() -> None:
        if extensions is None or extensions.registry is None:
            return
        for claim in extensions.registry.tools():
            name = str(claim.spec.get("name") or "")
            if not name:
                continue
            EXTENSION_TOOLS[name] = claim
            try:
                mcp.tool()(_make_extension_tool(claim, name))
            except Exception as exc:
                # An extension that cannot be published must not stop the
                # ones that can, nor the Station (L.7 rule 5).
                EXTENSION_TOOLS.pop(name, None)
                log.warning("extension tool %s could not be published: %s",
                            name, exc)

    _register_extension_tools()

    def _holds_answer(principal) -> bool:
        """J.2.7 rule 5: does this key hold `answer`, through its mask, on
        any forest it reaches? The owner holds every token and has no row;
        `admin` implies it as it implies every other (`Policy.grants`)."""
        if principal is None:
            return False
        if registry.is_owner(principal):
            return True
        mask = CAPS_MASK.get()
        for grant in registry.grants_of(principal):
            caps = set(grant["caps"])
            if mask is not None:
                caps &= set(mask)
            if "answer" in caps or "admin" in caps:
                return True
        return False

    def _hidden_tools(principal) -> set[str]:
        """What this key's menu leaves out: extension tools enabled nowhere
        it reaches (L.7 rule 2), and `answer` when it holds the token
        nowhere (J.2.7 rule 5) — the same reasoning both times: a tool that
        can only refuse costs every session its description and teaches
        nothing."""
        hidden = {
            name for name, claim in EXTENSION_TOOLS.items()
            if not _ext_forests_for(principal, claim.ext_id)
        }
        if not _holds_answer(principal):
            hidden.add("answer")
        return hidden

    import dataclasses as _dc

    # Filter the menu per key. Wrapping the handler rather than keeping a
    # second tool table: the SDK owns the list, and a copy of it here would
    # be a second description of one surface. Installed unconditionally
    # since v0.82 — `answer` is filtered on every deployment, extensions or
    # not.
    _entry = mcp._lowlevel_server._request_handlers.get("tools/list")

    if _entry is not None:
        # The registry holds a `HandlerEntry` (handler + params_type), not a
        # bare callable: replacing it with a function makes the runner fail
        # on `params_type`. So the ENTRY is rebuilt around a wrapped handler,
        # and the SDK keeps owning the list itself.
        _list_tools = _entry.handler

        async def _filtered_list_tools(*args, **kwargs):
            # Signature taken as given: the runner calls the handler with
            # (ctx, params) at this era, and pinning that shape here would
            # break on the next one for no benefit.
            result = await _list_tools(*args, **kwargs)
            principal = PRINCIPAL.get()
            hidden = _hidden_tools(principal)
            tools = getattr(result, "tools", None)
            if tools is None:  # pragma: no cover - the SDK shape moved
                # Fail CLOSED. This filter decides what a key is shown, so
                # a shape we no longer recognise must publish fewer tools,
                # never more — and it must say so, because a silently
                # unfiltered menu is the failure itself.
                log.warning("tools/list has an unfamiliar shape; "
                            "filtered tools are withheld")
                return result
            result.tools = [t for t in tools if t.name not in hidden]
            return result

        mcp._lowlevel_server._request_handlers["tools/list"] = \
            _dc.replace(_entry, handler=_filtered_list_tools)

    # J.1.2 rule 8 (v0.82): a call the SDK refuses before the tool runs —
    # arguments the input schema rejects, a tool that does not exist — comes
    # back as the SDK's own prose under `isError`. Rule 2 made the flag agree
    # with the envelope; this makes the BODY agree too. The SDK still
    # decides (as it decides J.1.1's 421); the host rewrites the sentence.
    _SDK_PREFIX = "Error executing tool "

    def _is_envelope(text: str) -> bool:
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return False
        return isinstance(parsed, dict) and "error" in parsed

    def _restate(name: str, arguments: dict, text: str) -> dict | None:
        from monkeyllm.errors import E_INTERNAL, E_NOT_FOUND, E_SCHEMA, VineError
        from monkeyllm.signatures import validate_args

        known = {t.name for t in mcp._tool_manager.list_tools()}
        if name not in known:
            return VineError(
                E_NOT_FOUND, f"no such tool: {name}",
                hint=f"Served tools: {sorted(known)}.").to_dict()
        prefix = f"{_SDK_PREFIX}{name}"
        if not text.startswith(prefix):
            return None
        rest = text[len(prefix):].lstrip(":").strip()
        if "validation error" in rest:
            # REST's own sentence for the same arguments, when the C.12
            # table refuses them too — `forest` is the tool's, not the
            # primitive's, so it is set aside before the table looks.
            try:
                validate_args(name, {k: v for k, v in dict(arguments).items()
                                     if k != "forest"})
            except VineError as e:
                return e.to_dict()
            except Exception:  # pragma: no cover - the table never crashes
                pass
            fields = [ln.strip() for ln in rest.splitlines()[1:]
                      if ln and not ln.startswith(" ")]
            named = fields[0] if fields else "arguments"
            return VineError(
                E_SCHEMA,
                f"{name}: parameter {named!r} was refused by the tool's "
                f"input schema",
                hint=(f"{name} refused: {', '.join(fields) or 'the arguments as sent'}. "
                      "Check the type of each named parameter against "
                      "tools/list.")).to_dict()
        if not rest:
            # The SDK's generic crash message: C.12's last resort, naming
            # the tool and nothing else.
            return VineError(E_INTERNAL, f"{name}: the tool failed").to_dict()
        return VineError(E_INTERNAL, f"{name}: {rest}").to_dict()

    _call_entry = mcp._lowlevel_server._request_handlers.get("tools/call")

    if _call_entry is not None:
        _call_tool = _call_entry.handler

        async def _enveloped_call_tool(*args, **kwargs):
            params = next((a for a in (*args, *kwargs.values())
                           if hasattr(a, "name") and hasattr(a, "arguments")),
                          None)
            result = await _call_tool(*args, **kwargs)
            if params is None or not getattr(result, "is_error", False):
                return result
            content = getattr(result, "content", None) or []
            if len(content) != 1 or getattr(content[0], "type", None) != "text":
                return result
            text = getattr(content[0], "text", "") or ""
            if _is_envelope(text):
                return result  # ours already (J.1.2 rule 2)
            restated = _restate(str(params.name), params.arguments or {}, text)
            if restated is None:
                return result
            return CallToolResult(
                content=[TextContent(type="text", text=compact(restated))],
                is_error=True)

        mcp._lowlevel_server._request_handlers["tools/call"] = \
            _dc.replace(_call_entry, handler=_enveloped_call_tool)

    # Transport options belong to the app factory in mcp 2.x, not the
    # constructor. streamable_http_path="/" because this app gets mounted
    # under /mcp by the caller; leaving the default would serve it at /mcp/mcp.
    inner = mcp.streamable_http_app(
        streamable_http_path="/", stateless_http=True, json_response=True,
        transport_security=security,
    )

    class SoftRefusal:
        """J.1.4 (v0.64): a refusal is not a disconnection.

        On this transport 404 carries a meaning of its own — the session
        named by the request no longer exists (streamable HTTP 2.5.3) — so
        a conforming client that reads one correctly stops using the
        connection. The SDK also spends it on `-32601 Method not found`,
        and at the 2026-07-28 era that is what a client meets: it asks for
        a method this Station does not serve, is told its session ended,
        and tears down a connection that was healthy. The call that then
        fails is the NEXT one, which is why the symptom arrives with the
        wrong name attached.

        The mount is stateless, so it issues no session id and no 404 it
        produces can be about a session. A 404 whose body is a JSON-RPC
        error is re-stated as 200 with that body untouched — the refusal
        is unchanged, only the layer it was spoken at. A 404 that is not a
        JSON-RPC body (a wrong path under the mount) is left alone: that
        one really is about an address.
        """

        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.app(scope, receive, send)
            start: dict | None = None
            chunks: list[bytes] = []

            async def send_wrapper(message):
                nonlocal start
                if message["type"] == "http.response.start":
                    if message.get("status") == 404:
                        start = dict(message)
                        return  # held until the body says what it is
                    return await send(message)
                if start is not None and message["type"] == "http.response.body":
                    chunks.append(message.get("body") or b"")
                    if message.get("more_body"):
                        return
                    body = b"".join(chunks)
                    if _is_jsonrpc_error(body):
                        start["status"] = 200
                    await send(start)
                    return await send({"type": "http.response.body",
                                       "body": body, "more_body": False})
                await send(message)

            await self.app(scope, receive, send_wrapper)

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

    return (Authenticated(HostRefusal(SoftRefusal(inner))),
            mcp.session_manager.run)
