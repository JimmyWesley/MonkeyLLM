# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""The Station's REST surface (spec J.1), Studio hosting and MCP mount.

Built on Starlette, which already ships as a transitive dependency of `mcp`
— the host adds no new runtime dependency, keeping J.6's one-image,
no-external-database posture.

Forest resolution reuses the engine's `ForestPool` (spec C.0) unchanged:
the Station is a privileged client, not a fork of the server.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import logging
import math
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from monkeyllm.errors import (
    E_ANCHORED,
    E_FRONTMATTER,
    E_INTERNAL,
    E_LOCKED,
    E_MOVED,
    E_NOT_FOUND,
    E_QUERY_FORBIDDEN,
    E_QUERY_INVALID,
    E_READONLY,
    E_SCHEMA,
    E_TIMEOUT,
    VineError,
)
from monkeyllm import links
from monkeyllm.server import ForestPool
from monkeyllm.signatures import validate_args
from monkeyllm.snapshot import CONTAINER_SUFFIX
from monkeyllm.windows import exclusive_end, normalize_window
from monkeyllm_station import answer_store, runs as runs_mod, vision, webhooks
from monkeyllm_station.jobs import JobBoard
from monkeyllm_station.policy import CAPS, E_FORBIDDEN, REQUIRED_CAP, ScopedVine
from monkeyllm_station.registry import Registry

log = logging.getLogger("monkeyllm_station")

READ_PRIMITIVES = frozenset(
    {"locate", "look", "move", "pick", "scan", "sniff", "harvest", "query",
     # C.13.3 (v0.52): the time map. A read like any other — catalog only,
     # no body opened, and scoped by the same policy.
     "calendar",
     # C.16 (v0.58): the document's past is a listing — a read.
     "history",
     # C.17 (v0.59): what the forest holds — catalog only, scoped, budgeted.
     "coverage"}
)
WRITE_PRIMITIVES = frozenset({"plant", "graft", "tend", "prune",
                              # C.15 (v0.58): a move edits every pointing
                              # node — it is a write, on the writer lane.
                              "transplant"})
# Not engine primitives: retrieval composed with the forest's bound model
# (J.10). `answer` reads, `curate` proposes a summary for a human to apply.
COMPOSITES = {"answer": ("read", "answer"), "curate": ("write", "ingest")}
# The Gardener over REST (J.8). Not a primitive either: `adopt`/`sync` are
# Part G, and the host only adds identity, scope and a staging area.
HOST_ACTIONS = frozenset({"ingest"})
SERVED_PRIMITIVES = READ_PRIMITIVES | WRITE_PRIMITIVES | set(COMPOSITES) | HOST_ACTIONS
# Calls that are several calls (J.10.4). A single primitive already reports
# its own latency to the caller who invoked it; these do not, because the
# work happens inside them.
EXPLAINED = frozenset({"answer", "harvest"})

# Map projections (J.11): a region in one payload, never a primitive. The
# default bound is generous enough that no ordinary forest meets it and low
# enough that meeting it is survivable; either way `truncated` says so.
MAP_KINDS = frozenset({"graph", "trails"})

# J.10.12 rule 5: a run id is a rendezvous, not a name. It is the
# caller's own opaque string, so it is bounded rather than parsed — the
# host never reads meaning out of it and never puts it in a forest.
RUN_ID_MAX = 120
MAP_LIMIT = 2000
MAP_MAX = 10000

# A forest id becomes a directory name under the registry root, so it is
# validated as a NAME before it is ever joined to a path (J.7). Separators
# and relative segments cannot survive this character set, which is why the
# check is a whitelist and not a blacklist of the escapes we thought of.
FOREST_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

# The owner's password governs every forest present and future (J.2.4), and
# it is set on a screen with no administrator behind it to advise. A floor is
# the least a deployment can do; anything more opinionated belongs to the
# operator's own policy, not to the host.
MIN_OWNER_PASSWORD = 12

# Uploaded documents are a source, not content: they stage under the
# forest's disposable `_derived/` (gitignored, A.3.1) and become nodes only
# by going through the same converters and commits as any adopted folder.
# One stable directory per forest, so a later `sync` still has its source.
UPLOAD_DIR = ("_derived", "uploads")

# J.2.6: what a pair key may ask for — clip and look. `write`, `tend`,
# `query` and `admin` stay what People and `station key` mint, deliberately.
PAIR_CAPS = frozenset({"read", "ingest"})
# A pair key MUST expire: absent or zero means the default, never
# "unlimited", and the ceiling is stated to the caller, never silently
# clamped.
PAIR_DEFAULT_DAYS = 90.0
PAIR_MAX_DAYS = 365.0

# J.2.6: `login` and `pair` both verify passwords and both are reachable
# from every browser that holds the origin, not only from the console — so
# both are rate limited. Fixed window per (username, client host).
AUTH_ATTEMPT_LIMIT = 5
AUTH_WINDOW_SECONDS = 60.0


class AuthWindow:
    """Fixed-window failure counter for the password doors (J.2.6).

    In-process on purpose: the registry is not a place to write on every
    wrong password, and a limiter forgotten by a restart limits again on
    the very next failure. One lock, one dict — a success clears the
    window, and the refusal never says whether the user exists, so the
    limiter cannot become the directory the login refusal already refuses
    to be (J.2.1).
    """

    def __init__(self, limit: int = AUTH_ATTEMPT_LIMIT,
                 seconds: float = AUTH_WINDOW_SECONDS,
                 max_tracked: int = 4096):
        self.limit = limit
        self.seconds = seconds
        # The username is caller-controlled on an unauthenticated route, so
        # without a ceiling a stream of distinct usernames grows this dict
        # forever — an unauthenticated memory-exhaustion vector. Expired
        # windows are only otherwise pruned when their exact key is asked
        # about again, which a one-shot username never is.
        self.max_tracked = max_tracked
        self._lock = threading.Lock()
        self._failures: dict[tuple[str, str], tuple[float, int]] = {}

    def over_limit(self, username: str, host: str) -> bool:
        """Checked BEFORE the password is verified: past the limit, the
        answer is 429 without spending a hash comparison."""
        now = time.monotonic()
        with self._lock:
            entry = self._failures.get((username, host))
            if entry is None:
                return False
            start, count = entry
            if now - start >= self.seconds:
                # The window closed on its own; forget it rather than let a
                # dead entry keep the dict growing.
                del self._failures[(username, host)]
                return False
            return count >= self.limit

    def failed(self, username: str, host: str) -> None:
        now = time.monotonic()
        with self._lock:
            start, count = self._failures.get((username, host), (now, 0))
            if now - start >= self.seconds:
                start, count = now, 0
            self._failures[(username, host)] = (start, count + 1)
            if len(self._failures) > self.max_tracked:
                self._sweep(now)

    def _sweep(self, now: float) -> None:
        """Callers hold the lock. Expired windows go first; if a flood of
        distinct usernames keeps the dict over the ceiling anyway, the
        oldest live windows go too — forgetting a window early merely
        restarts its count, it never locks anyone out."""
        for key in [k for k, (start, _) in self._failures.items()
                    if now - start >= self.seconds]:
            del self._failures[key]
        excess = len(self._failures) - self.max_tracked
        if excess > 0:
            for key in sorted(self._failures,
                              key=lambda k: self._failures[k][0])[:excess]:
                del self._failures[key]

    def clear(self, username: str, host: str) -> None:
        with self._lock:
            self._failures.pop((username, host), None)


def _too_many_attempts() -> JSONResponse:
    """One message whether the user exists or not (J.2.6)."""
    return _envelope(
        VineError(E_FORBIDDEN, "too many attempts; try again shortly"), 429)


@dataclass
class PreparedIngest:
    """An accepted batch, handed from the forest lane back to the event
    loop (J.9): everything the driver needs to step it — one document per
    lane task, so other calls to the forest interleave — and everything the
    finisher needs to close it exactly as the v0.31 response did."""

    job: object
    steps: object          # the G.10 step iterator
    gardener: object
    curator: object | None
    mode: str
    staged: list = field(default_factory=list)
    # J.8.4 (v0.78): the upload's passports by staged rel name, and the gate
    # that pinned them — what the finisher compares to name the unapplied.
    passports: dict = field(default_factory=dict)
    gate: object | None = None
    root: Path | None = None
    before: str | None = None
    principal: str = ""
    forest: str = ""
    payload: dict = field(default_factory=dict)


# J.13.6.1: the job's `mode`, which is the caller's own word everywhere else
# (J.9, v0.61). This caller is the recuration route, and this is its word —
# never "sync", never "ingest": nothing is being read from a source, and a
# console that labelled it so would offer the operator the wrong repair.
RECURATE_MODE = "recurate"


@dataclass
class PreparedRecurate:
    """An accepted scent recuration (J.13.6.1), handed from the forest lane
    back to the event loop: the same construction as `PreparedIngest` and
    for the same reason — one node per lane task, so the reads and writes
    queued behind it get their turn between model calls."""

    job: object
    steps: object          # the scent step iterator (G.10's shape)
    curator: object
    vine: object
    root: Path
    before: str | None = None
    principal: str = ""
    forest: str = ""


# The Studio is a React/Vite build: static files only, no server rendering,
# so it stays a plain REST client with no privileged side-channel (J.5).
STUDIO_DIST = Path(__file__).resolve().parents[2] / "studio" / "dist"

# The Clipper the Station hands out (J.15): one shared build, resolved like
# the Studio's — the sibling app in the repo or image, overridable for a
# deployment that stages it elsewhere. The server never ships a per-user
# binary; pairing supplies the origin and the credential, so the artifact
# itself carries no secrets and no configuration.
CLIPPER_DIR = Path(__file__).resolve().parents[2] / "clipper"
CLIPPER_DIR_ENV = "MONKEYLLM_STATION_CLIPPER_DIR"

# J.13.2 snapshot import: how many megabytes an uploaded bundle may be.
IMPORT_MAX_MB_ENV = "MONKEYLLM_STATION_IMPORT_MAX_MB"
DEFAULT_IMPORT_MAX_MB = 1024.0


_INLINE_SCRIPT = re.compile(
    rb"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)


def _inline_script_hashes(shell: Path) -> list[str]:
    """CSP sources for the shell's own inline scripts, read from the build.

    The console boots the saved theme before first paint and registers its
    service worker inline, and both have to keep running under a policy that
    otherwise forbids inline script. Hashing the built file rather than
    writing the digests down here is what keeps them true: a hash maintained
    by hand goes stale the first time somebody edits the boot script, and it
    fails silently — the page still loads, it just stops doing the one thing
    the script was there for.
    """
    try:
        html = shell.read_bytes()
    except OSError:
        return []
    return [f"'sha256-{base64.b64encode(hashlib.sha256(body).digest()).decode()}'"
            for body in _INLINE_SCRIPT.findall(html)]


def studio_csp() -> str:
    """What the console's page is allowed to load (J.5).

    Studio renders two kinds of untrusted text as markdown: what a model
    wrote, and the body of an ingested document. The product's own premise is
    that ingested content comes from outside — the Clipper exists to capture
    third-party pages. Whatever such text can talk the page into fetching, it
    fetches from the operator's authenticated browser, and the Station is not
    on that path at all: no server-side check can be the control here, which
    is why the browser has to be told the rules up front.

    `img-src 'self' data: blob:` is the load-bearing line. A legitimate image
    is fetched through J.14 with the viewer's credential and shown as a
    `blob:`, so it still renders; an off-origin address never loads, and
    nothing legitimate needs one.
    `style-src` keeps `'unsafe-inline'` because React style attributes and
    mermaid's injected CSS both need it; script has no such need — the bundle
    contains no `eval` or `new Function` — so it is hashes and same-origin
    only.
    """
    hashes = " ".join(_inline_script_hashes(STUDIO_DIST / "index.html"))
    return "; ".join([
        "default-src 'self'",
        "base-uri 'none'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",
        f"script-src 'self' {hashes}".rstrip(),
        "connect-src 'self'",
        "worker-src 'self'",
    ])


class SecurityHeaders:
    """Baseline response headers on every surface.

    Pure ASGI rather than `BaseHTTPMiddleware`: headers are stamped on the
    response-start message, so a file download and a job report stream
    through untouched.

    Set with `setdefault`, so a route that has a reason to state its own
    policy keeps it.
    """

    def __init__(self, app, csp: str) -> None:
        self.app = app
        self.csp = csp

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("content-security-policy", self.csp)
                # A JSON envelope sniffed as HTML is a stored-XSS primitive;
                # the forest's own content is what fills those envelopes.
                headers.setdefault("x-content-type-options", "nosniff")
                # A console address names the forest and the node being read.
                # That belongs to the reader, not to whatever host a page
                # happens to reference.
                headers.setdefault("referrer-policy", "no-referrer")
                # `frame-ancestors` above says the same thing to browsers that
                # implement CSP; this covers the ones that do not.
                headers.setdefault("x-frame-options", "DENY")
            await send(message)

        await self.app(scope, receive, send_with_headers)


class StudioFiles(StaticFiles):
    """The build, plus the console's own addresses (J.5.8).

    Studio's URLs are real paths — `/f/{forest}/explore` — so a reload, a
    bookmark or a shared link arrives here as a GET of a path that has no
    file behind it. Answering 404 is what made the console lose the place
    on F5: the application that could have read the address never loaded.

    Only for **document** requests. A request that accepts HTML is a browser
    asking for a page; a script, a stylesheet or a `fetch` is not, and
    handing those the shell would serve an HTML body under a JavaScript MIME
    type — a failure that surfaces later, elsewhere, and unrecognisably.
    A missing asset stays a missing asset.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            accept = Headers(scope=scope).get("accept", "")
            if "text/html" not in accept:
                raise
            shell = await super().get_response("index.html", scope)
            # The shell names one build's hashed assets, so a cached copy
            # asks a later deployment for files it no longer has. The assets
            # themselves are content-addressed and may be cached forever.
            shell.headers["Cache-Control"] = "no-cache"
            return shell

STATUS_BY_CODE = {
    E_NOT_FOUND: 404,
    E_SCHEMA: 400,
    E_FRONTMATTER: 400,
    E_FORBIDDEN: 403,
    E_READONLY: 403,
    E_QUERY_FORBIDDEN: 403,
    # C.5.2 (v0.47): 403 says the principal may not, 400 says the request
    # was wrong. A client retrying a 403 is confused; a client retrying a
    # 400 with a corrected statement is doing exactly the right thing.
    E_QUERY_INVALID: 400,
    E_LOCKED: 409,
    # C.14 (v0.56): the forest's current shape said no — same family as
    # E_LOCKED: the request was fine, the state refuses it.
    E_ANCHORED: 409,
    # C.15 (v0.58): it is not at this address — and the envelope says
    # where it went, when the reader's scope may know.
    E_MOVED: 404,
    E_TIMEOUT: 504,
    # C.12 rule 5 (v0.52): a defect on this side, said in the shape every
    # other refusal uses — so a caller can classify it instead of guessing.
    E_INTERNAL: 500,
}


def _envelope(err: VineError, status: int | None = None) -> JSONResponse:
    return JSONResponse(err.to_dict(),
                        status_code=status or STATUS_BY_CODE.get(err.code, 400))


PROVIDER_ALLOW_PRIVATE_ENV = "MONKEYLLM_STATION_PROVIDER_ALLOW_PRIVATE"


def _allow_private_endpoints() -> bool:
    """Whether the provider-test route may reach loopback and private hosts.

    Off by default. A local llama.cpp or Ollama lives on localhost, so a
    deployment that runs its own inference turns this on explicitly; a
    deployment that only reaches hosted providers never should.
    """
    raw = os.environ.get(PROVIDER_ALLOW_PRIVATE_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _reject_internal_endpoint(endpoint: str) -> JSONResponse | None:
    """Refuse a destination the server should not connect to on request.

    The provider-test route lets the caller choose an address the Station
    then fetches. Unguarded that is a request-forgery primitive aimed at the
    host's own network — cloud metadata, internal ports, panels that trust
    their origin. So the address is validated: http/https only, and every IP
    the host name resolves to must be public. Returns an envelope to send, or
    None when the endpoint is allowed.
    """
    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return _envelope(VineError(
            E_SCHEMA, "endpoint must be an http(s) URL with a host"))
    if _allow_private_endpoints():
        return None
    host = parts.hostname
    try:
        # Resolve the name and judge every address it maps to. Inspecting the
        # string would decide on what the URL says rather than on where it
        # goes, and a name can be made to say anything.
        infos = socket.getaddrinfo(host, parts.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return _envelope(VineError(
            E_SCHEMA, f"endpoint host does not resolve: {host}"))
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if (addr.is_loopback or addr.is_private or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return _envelope(VineError(
                E_SCHEMA, "endpoint resolves to a non-public address",
                hint=f"Set {PROVIDER_ALLOW_PRIVATE_ENV}=1 to allow local or "
                     "private providers (e.g. a llama.cpp on localhost)."))
    return None


def _server_timing(clocks: dict) -> str:
    """The host's own clocks as the standard header (J.10.6).

    A body is the agent's context window and it is budgeted in tokens, so
    the console's instruments travel outside it: the header costs the
    response nothing and a browser's network panel already draws it.

    Shape only, like a trace — durations, no ids, no counts — so a timing
    can never say more than the response it rides on. `cache` appears only
    when the answer store was consulted (J.10.7); on a hit `model` is
    absent, because no provider ran.

    `embed` and `dense` (J.10.4.1, v0.71) are SHARES OF `vine`, not clocks
    beside it: they name what a hybrid entry spent on a provider round trip
    and on the vector scan, and `vine` still reports the whole engine span.
    A consumer that wants the forest's own work subtracts them; one that
    sums every clock to reconstruct the request must not.
    """
    return ", ".join(f"{name};dur={clocks[name]}"
                     for name in ("vine", "embed", "dense", "model", "cache", "host")
                     if name in clocks)


def _no_such_endpoint(path: str) -> JSONResponse:
    """The answer for a path under `/v1` that matches nothing.

    One function rather than one string per caller, because J.2.4 requires a
    *closed* setup route to be indistinguishable from a path that was never
    routed — and two copies of a message drift the first time one is edited.
    `path` is the tail after `/v1`, which is what the catch-all reports.
    """
    return _envelope(VineError(
        E_NOT_FOUND, f"no such endpoint: {path}",
        hint="Check the method too: several /v1/admin routes are POST-only."))


def _unknown_forest(forest: str) -> JSONResponse:
    """One response for 'no such forest' AND 'not granted to you'.

    Distinguishing them would let a principal enumerate the registry — the
    same existence-oracle reasoning J.3 applies to nodes, applied to forests.
    """
    return _envelope(
        VineError(E_NOT_FOUND, f"unknown forest: {forest}",
                  hint="GET /v1/forests lists the forests available to you.")
    )


def _forest_list(value: object, fallback: object = None) -> list[str]:
    """One forest or several, as the caller pleased (J.2.3, v0.20).

    `grant` and `revoke_access` accept a list, and the scalar form means a
    one-element list — so a client written against v0.19 keeps working. The
    order the caller sent is preserved (refusals are reported against it) and
    duplicates collapse, because granting the same forest twice in one
    request is a typo, not an instruction.
    """
    raw = value if value not in (None, "", [], ()) else fallback
    items = raw if isinstance(raw, (list, tuple, set)) else [raw]
    out: list[str] = []
    for item in items:
        name = str(item or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _iso(epoch: float) -> str:
    """A file mtime as the same ISO shape every other timestamp uses."""
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args],
                         capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def stamp_principal(root: Path, principal: str, before: str | None) -> str | None:
    """Write the acting principal into the commit the engine just made (J.4).

    The engine commits with a fixed identity and the host may not change it
    (J.11 forbids engine edits), so the Station amends the message it just
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


def super_admin_from_env() -> tuple[str, str] | None:
    """The break-glass account (J.2.1), or None.

    Absent variables mean the password door does not exist — a deployment
    that never sets them has no default credential, which is the only safe
    default. An empty password is treated as absent for the same reason.
    """
    user = os.environ.get("MONKEYLLM_STATION_ADMIN", "").strip()
    password = os.environ.get("MONKEYLLM_STATION_PASSWORD", "")
    return (user, password) if user and password else None


WARM_ENV = "MONKEYLLM_STATION_WARM"


def warm_from_env() -> bool:
    """Whether boot opens every forest (J.6.1). Default on.

    The inverse of the usual rule for a switch: this one is off only where
    somebody decided it should be, because leaving it off costs the first
    caller of every forest and nobody sees the bill. The cost of on is
    resident memory proportional to the number of forests, which is the one
    reason to turn it off and the reason it can be.
    """
    raw = os.environ.get(WARM_ENV, "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


INGEST_ROOTS_ENV = "MONKEYLLM_INGEST_ROOTS"


def ingest_roots_from_env() -> list[Path]:
    """The directories this Station will read on a caller's behalf (J.8.2).

    Absent means NONE, and that is the point. `upload` and `compose` carry
    their own bytes and keep working; every host path is refused. A control
    that has to be switched on is off wherever nobody knew to look for it,
    and the deployment that most needs this boundary is run by the operator
    who never read the spec.
    """
    raw = os.environ.get(INGEST_ROOTS_ENV, "")
    return [Path(p).expanduser().resolve()
            for p in raw.split(os.pathsep) if p.strip()]


class IngestRoots:
    """J.8.2 gate: resolve first, then compare — `..` and symlinks are the
    escape, so a decision made on the string is a decision about the wrong
    path."""

    def __init__(self, roots: list[Path], registry_root: Path):
        self.registry_root = registry_root.expanduser().resolve()
        missing = [r for r in roots if not r.is_dir()]
        if missing:
            # A mistyped mount is a boot-time fact. Discovering it months
            # later, from an ingest that refuses a path the operator can see
            # in their own compose file, is the expensive way to learn it.
            raise ValueError(
                f"{INGEST_ROOTS_ENV} names directories that do not exist: "
                f"{', '.join(str(m) for m in missing)}")
        # The registry root is never an ingest root, listed or not, and
        # neither is any ancestor of it: one forest reading the volume that
        # holds every forest is the tenant boundary failing in the only
        # direction that counts. Silently dropping it beats refusing to
        # boot — the Station still serves, and the ingest that would have
        # crossed the boundary is the only thing that stops working.
        self.roots = [r for r in roots if not self._holds_registry(r)]
        self.rejected = [r for r in roots if self._holds_registry(r)]

    def _holds_registry(self, root: Path) -> bool:
        return self.registry_root == root or self.registry_root.is_relative_to(root)

    def check(self, path: str | Path) -> VineError | None:
        """None when `path` may be read; the error to return otherwise."""
        if not self.roots:
            return VineError(
                E_FORBIDDEN,
                "this Station reads no host paths",
                hint=f"Set {INGEST_ROOTS_ENV} to the directories it may "
                     f"ingest from, or use mode 'upload' to send the "
                     f"documents themselves.")
        try:
            target = Path(path).expanduser().resolve()
        except (OSError, RuntimeError):  # symlink loops, unresolvable drives
            return VineError(E_SCHEMA, f"unusable source path: {path}")
        if any(target == r or target.is_relative_to(r) for r in self.roots):
            return None
        return VineError(
            E_FORBIDDEN, f"'{path}' is outside this Station's ingest roots",
            hint=f"Allowed: {[str(r) for r in self.roots]}. Widen "
                 f"{INGEST_ROOTS_ENV} to add one.")


# The variables this project already documents (`.env.example`) — the same
# ones the CLI, the bench and the measurement scripts read. A deployment that
# has already configured them has said everything the console's provider form
# would ask for, so the Station publishes them instead of asking again.
ENV_PROVIDERS = (
    ("chat", "MONKEYLLM_LLM_PROVIDER", "MONKEYLLM_LLM_ENDPOINT",
     "MONKEYLLM_LLM_API_KEY"),
    ("embed", "MONKEYLLM_EMBED_PROVIDER", "MONKEYLLM_EMBED_ENDPOINT",
     "MONKEYLLM_EMBED_API_KEY"),
)


def _json_object(parsed):
    """A request body is an OBJECT or it is `E_SCHEMA` (C.12).

    Every route here reads its arguments with `body.get(...)`, so a body that
    parses as a bare string, list or number reached that call as whatever it
    was and raised `AttributeError` — answered as `E_INTERNAL`/500, which
    tells the caller "this is a defect on the server" about a malformed
    request they sent. A double-encoded body is the way this actually
    happens: `JSON.stringify` applied twice parses back to a `str`, which is
    exactly the bug the Studio console had on `recurate` and `clearStaging`.

    Returns the dict, or raises the refusal that names what arrived.
    """
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise VineError(
            E_SCHEMA,
            f"request body must be a JSON object, got {type(parsed).__name__}",
            hint="Send the arguments as an object, e.g. {\"forest\": \"...\"}. "
                 "A body encoded to JSON twice arrives as a string.")
    return parsed


def _name_from_endpoint(endpoint: str) -> str:
    """`https://openrouter.ai/api/v1` → `openrouter.ai`, and the port comes
    along when there is one so two local servers do not become one name."""
    parts = urlsplit(endpoint if "//" in endpoint else f"//{endpoint}")
    host = parts.hostname or endpoint
    return f"{host}:{parts.port}" if parts.port else host


def providers_from_env(environ: dict | None = None) -> list[dict]:
    """Providers declared by the deployment (J.10.1).

    An endpoint is what makes a provider exist here; the name is optional
    (derived from the host) and the key is optional (local servers need
    none). Nothing is declared when no endpoint is set — the console form
    stays the only way in, exactly as before.
    """
    env = os.environ if environ is None else environ
    out: list[dict] = []
    named: set[str] = set()
    for role, name_var, endpoint_var, key_var in ENV_PROVIDERS:
        endpoint = (env.get(endpoint_var) or "").strip().rstrip("/")
        if not endpoint:
            continue
        explicit = (env.get(name_var) or "").strip()
        entry = {"name": explicit or _name_from_endpoint(endpoint),
                 "endpoint": endpoint,
                 "api_key": (env.get(key_var) or "").strip() or None}
        # Identity is the endpoint and the key, not the variable that named
        # it: one gateway serving both roles is one provider in the console.
        same = next((p for p in out
                     if (p["endpoint"], p["api_key"])
                     == (entry["endpoint"], entry["api_key"])), None)
        if same is not None:
            if explicit and same["name"] not in named:
                named.discard(same["name"])
                same["name"] = entry["name"]
                named.add(entry["name"])
            continue
        if any(p["name"] == entry["name"] for p in out):
            # Same name over a different endpoint or key. Merging them would
            # bind one role to the other's server.
            entry["name"] = f"{entry['name']}-{role}"
        out.append(entry)
        if explicit:
            named.add(entry["name"])
    return out


def build_app(
    *,
    root: str | Path,
    registry_path: str | Path,
    writable: bool = True,
    mcp: bool = True,
    warm: bool | None = None,
) -> Starlette:
    pool = ForestPool(root=Path(root), writable=writable)
    # On by default: a console is judged on the speed of its first call, and
    # the cost is one open per forest, which the registry pays anyway. Off is
    # for the registry big enough that holding every forest open at once is
    # the wrong trade — the explicit argument wins over the environment,
    # because a deployment that passes one has already decided.
    warm_forests = warm if warm is not None else warm_from_env()
    ingest_roots = IngestRoots(ingest_roots_from_env(), Path(root))
    if ingest_roots.rejected:
        print(f"station: refusing {INGEST_ROOTS_ENV} entries that contain the "
              f"forest registry: {[str(r) for r in ingest_roots.rejected]}",
              file=sys.stderr)
    registry = Registry(registry_path)
    registry.adopt_env_providers(providers_from_env())
    super_admin = super_admin_from_env()
    if super_admin:
        registry.ensure_super_admin(
            super_admin[0], [f["id"] for f in pool.list()["forests"]])

    # A SQLite connection belongs to the thread that opened it, and the engine
    # rightly does not weaken that guarantee for the host's convenience. So the
    # Station confines every forest touch — open, call, close — to one
    # dedicated thread. It also keeps the blocking reads off the event loop.
    # One lane PER forest (J.9 isolation): a call on one forest never waits
    # on another forest's work. Lanes open lazily with the forest and close
    # with the pool; the `None` lane is host work that belongs to no open
    # forest — creating one, or answering for a forest that does not exist.
    class ForestLanes:
        def __init__(self):
            self._lanes: dict[str | None, ThreadPoolExecutor] = {}
            self._lock = threading.Lock()

        def lane(self, forest: str | None) -> ThreadPoolExecutor:
            with self._lock:
                ex = self._lanes.get(forest)
                if ex is None:
                    name = f"forest-{forest}" if forest else "station-host"
                    ex = ThreadPoolExecutor(max_workers=1,
                                            thread_name_prefix=name)
                    self._lanes[forest] = ex
                return ex

        def shutdown(self) -> None:
            with self._lock:
                lanes, self._lanes = list(self._lanes.values()), {}
            for ex in lanes:
                ex.shutdown(wait=True)

    lanes = ForestLanes()

    # J.6.2 (v0.57): reads scale. K read-only Vines per forest, each
    # confined to its own thread exactly as the writer is to its lane — a
    # read never again waits for a plant, a batch, or a model call. Readers
    # take no lock (C.9: the lock is possession of the WRITE), deposit
    # pheromone exactly as any read does, and see every write that
    # committed before their transaction began (WAL). Opened lazily, on
    # their own lane, on first use: boot warming warms the writer, and
    # multiplying boot cost by K would move the cold-start problem, not
    # solve it.
    class ReaderLanes:
        def __init__(self, size: int):
            self.size = max(0, size)
            self._lanes: dict[tuple[str, int], ThreadPoolExecutor] = {}
            self._vines: dict[tuple[str, int], object] = {}
            self._rr: dict[str, int] = {}
            self._lock = threading.Lock()

        def slot(self, forest: str) -> int:
            with self._lock:
                i = self._rr.get(forest, 0)
                self._rr[forest] = (i + 1) % self.size
                return i

        def lane(self, forest: str, slot: int) -> ThreadPoolExecutor:
            key = (forest, slot)
            with self._lock:
                ex = self._lanes.get(key)
                if ex is None:
                    ex = ThreadPoolExecutor(
                        max_workers=1,
                        thread_name_prefix=f"forest-{forest}-r{slot}")
                    self._lanes[key] = ex
                return ex

        def vine(self, forest: str, slot: int):
            """The slot's read-only Vine — called ON the slot's own thread,
            so the SQLite connections it opens belong where they are used."""
            key = (forest, slot)
            v = self._vines.get(key)
            if v is None:
                from monkeyllm.vine import Vine

                assert pool.root is not None
                v = Vine(pool.root / forest, writable=False)
                self._vines[key] = v
            return v

        def reset(self, forest: str) -> None:
            """Drop a forest's readers so they reopen fresh — after a
            restore replaces the directory, or an admin rebuild replaces
            what a held-open index points at. Vines close on their own
            lanes; the lanes stay for reuse."""
            with self._lock:
                keys = [k for k in self._vines if k[0] == forest]
            for key in keys:
                ex = self._lanes.get(key)
                v = self._vines.pop(key, None)
                if v is not None and ex is not None:
                    ex.submit(v.close)

        def shutdown(self) -> None:
            with self._lock:
                pairs = [(self._lanes[k], self._vines.get(k))
                         for k in self._lanes]
                self._lanes, self._vines = {}, {}
            for ex, v in pairs:
                if v is not None:
                    ex.submit(v.close)
                ex.shutdown(wait=True)

    try:
        reader_count = int(os.environ.get("MONKEYLLM_STATION_READERS", "4"))
    except ValueError:
        reader_count = 4
    readers = ReaderLanes(reader_count)

    # J.10.11 (v0.57): phase 2's stated ceiling. Parallel because the lane
    # hold is gone — the load report measured 0.3 req/s pinned, one model
    # call at a time — and bounded because the provider is metered and the
    # operator pays it. A call over the ceiling waits in the host, and the
    # wait shows in the `host` clock, never the `model` one.
    try:
        model_slots = int(os.environ.get(
            "MONKEYLLM_STATION_MODEL_CONCURRENCY", "8"))
    except ValueError:
        model_slots = 8
    model_slots = max(0, model_slots)
    model_gate = asyncio.Semaphore(model_slots) if model_slots else None

    # J.10.7 (v0.58): identical questions in flight share one generation.
    # The old single lane had an accidental virtue — queued identical
    # misses hit the entry the first had just stored — and J.10.11's
    # parallel phase 2 un-made it. Keyed by (forest, store key); a leader
    # that errors or declines to store releases its followers to their own
    # calls, because coalescing is an optimisation OVER the store, never a
    # second source of truth. Host memory, emptied by its own finally.
    inflight: dict[tuple[str, str], asyncio.Event] = {}

    def _servable(forest: str) -> bool:
        """Whether this name earns its own lane — a filesystem stat, safe
        from any thread. Names that are not forests share the host lane,
        where they get the same unknown-forest answer they always got;
        without this check, unauthenticated garbage in the URL would mint
        one thread per guess."""
        if not forest or pool.root is None:
            return False
        target = (pool.root / forest).resolve()
        return (target.is_relative_to(pool.root) and target != pool.root
                and (target / "_index.md").is_file())

    async def in_forest_thread(forest: str | None, fn):
        lane = lanes.lane(forest if forest and _servable(forest) else None)
        return await asyncio.get_running_loop().run_in_executor(lane, fn)

    # J.6.2: which lane a primitive belongs to. Writes, the one composite
    # that writes, and ingest keep the writer lane; every read — and the
    # sweep's retrieval — runs on the reader pool when one is configured.
    WRITER_BOUND = WRITE_PRIMITIVES | {"curate"} | HOST_ACTIONS

    def reader_slot(forest: str, name: str) -> int | None:
        """The reader slot this call rides, or None for the writer lane."""
        if (readers.size <= 0 or name in WRITER_BOUND
                or not forest or not _servable(forest)):
            return None
        return readers.slot(forest)

    async def in_reader_thread(forest: str, slot: int, fn):
        lane = readers.lane(forest, slot)
        return await asyncio.get_running_loop().run_in_executor(lane, fn)

    async def in_lane(forest: str, slot: int | None, fn):
        if slot is None:
            return await in_forest_thread(forest, fn)
        return await in_reader_thread(forest, slot, fn)

    # -- the progress of one answer (J.10.12) --------------------------------

    # Host memory, like the job board below and for the same reason: a
    # restart forgets records and never work.
    runs = runs_mod.RunBoard()

    def publish(sample: dict, kind: str, data) -> None:
        """One progress event, if this call is being watched.

        Reached from a forest lane. `RunBoard.publish` never blocks and
        never raises, so an answer cannot be slowed or failed by a
        spectator (J.10.12 rule 4).
        """
        key = sample.get("run_key")
        if key is not None:
            runs.publish(key, kind, data)

    async def answer_events(request: Request):
        """`GET /v1/forests/{forest}/answer/{run}/events` (J.10.12).

        The progress of one `answer` the same principal is making, on a
        channel of its own so the response's shape never moves.

        No forest is touched here — no lane, no trace, no pheromone. Like a
        J.9 job record this reads host memory alone, which is also why it
        cannot lie about a Station that restarted: the record is gone and
        the channel closes.
        """
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        # Asked before the run is looked up, so no principal can learn
        # whether somebody else's run exists by watching which spelling of
        # "no" comes back.
        if registry.policy_for(principal, forest) is None:
            return _unknown_forest(forest)

        # The key IS the authorization, and that is the whole of it: a
        # record exists only because THIS principal's `answer` on THIS
        # forest claimed it, and a principal without `read` could never have
        # made that call. So there is no capability to re-test here — an
        # id nobody claimed keys nothing, and a channel for it closes.
        key = (principal, forest, request.path_params["run"][:RUN_ID_MAX])

        async def frames():
            # An unknown or finished run yields what it has and closes
            # (rule 6). `stream` is what decides that; this only renders.
            async for event in runs.stream(key):
                data = json.dumps(event["data"], ensure_ascii=False,
                                  default=str)
                yield f"event: {event['event']}\ndata: {data}\n\n".encode()

        return StreamingResponse(
            frames(), media_type="text/event-stream",
            headers={
                # A progress channel behind a buffering proxy is a progress
                # channel that arrives all at once, at the end, which is the
                # problem this section exists to solve.
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            })

    # -- ingest jobs (J.9) ---------------------------------------------------

    board = JobBoard()

    def _advance(steps):
        """One G.10 step, shaped for the executor: `next` raising
        StopIteration through a Future would poison the awaiting
        coroutine, so exhaustion is `None` and the report is read off
        `steps.result`."""
        try:
            return next(steps)
        except StopIteration:
            return None

    def _finish_ingest(prep: PreparedIngest, cancelled: bool) -> dict:
        """On the forest lane: the tail every v0.31 ingest ran — rollup,
        HEAD, curation stats — plus the audit row, written now because the
        ingest had not happened until now (J.9)."""
        report = (prep.steps.report.as_dict() if cancelled
                  else prep.steps.result)
        if prep.passports:
            # J.8.4: bytes re-sent for a node that already existed were
            # refreshed and their passport was NOT applied — a refresh never
            # curates (G.3). The caller is told, by entry, so the next move
            # is `graft` and not a second look at scent that did not change.
            applied = getattr(prep.gate, "applied", None) or set()
            report = {**(report or {}), "passports_ignored":
                      sorted(name for name in prep.passports if name not in applied)}
        # A cancelled batch spends no further model calls: the rollup
        # describes branches somebody just decided not to finish filling.
        rollup = (prep.gardener.rollup(prep.curator)
                  if (prep.curator and not cancelled) else None)
        after = _git(prep.root, "rev-parse", "HEAD")
        # `curated` is what the model DID, not what the operator configured
        # — same reasoning as the compose path (G.4 rule 6).
        stats = dict(prep.curator.stats) if prep.curator else None
        if stats and prep.curator.last_error:
            stats["error"] = prep.curator.last_error
        if stats and prep.curator.last_reject:
            stats["rejected_because"] = prep.curator.last_reject
            stats["last_reply"] = prep.curator.last_reply or ""
        written = bool(stats and (stats["llm_summaries"] or stats["branch_rollups"]))
        result = {
            **report, "mode": prep.mode, "staged": prep.staged,
            "rollup": rollup,
            "commit": after or None, "commit_before": prep.before,
            "curated": written, "bound": prep.curator is not None,
            "curation": stats,
        }
        result.pop("drafts", None)  # an ordinary ingest has none
        registry.record(
            principal=prep.principal, forest=prep.forest, primitive="ingest",
            args={**prep.payload, "job": prep.job.id}, result="ok",
            size=len(json.dumps(result, default=str)),
            commit_sha=result.get("commit"),
        )
        return result

    async def _drive_ingest(prep: PreparedIngest) -> None:
        """The job, from accept to finish: each step is one lane task, so
        between steps every queued call to this forest gets its turn (J.9
        fairness). Cancellation is honoured at step boundaries — a document
        is whole or absent, never half."""
        job, steps = prep.job, prep.steps
        try:
            while True:
                if job.cancel_requested:
                    final = await in_forest_thread(
                        prep.forest, lambda: _finish_ingest(prep, cancelled=True))
                    board.finish(job, "cancelled", report=final)
                    hooks.emit(prep.forest, "ingest.cancelled", prep.principal,
                               {"job": job.id, "mode": prep.mode,
                                "done": job.done, "total": job.total,
                                **ingest_counts(final)})
                    return
                step = await in_forest_thread(
                    prep.forest, lambda: _advance(steps))
                if step is None:
                    final = await in_forest_thread(
                        prep.forest, lambda: _finish_ingest(prep, cancelled=False))
                    board.finish(job, "done", report=final)
                    # `ingest_counts` carries the report's own `errors`,
                    # which is the same fact as `job.errors` and is spread
                    # in last — one of them would silently win, so only one
                    # is stated.
                    hooks.emit(prep.forest, "ingest.finished", prep.principal,
                               {"job": job.id, "mode": prep.mode,
                                "total": job.total,
                                "commit": (final or {}).get("commit"),
                                "curated": bool((final or {}).get("curated")),
                                **ingest_counts(final)})
                    return
                board.note_step(job, step)
                if step.get("action") == "error":
                    # The one signal in a batch that wants a human: routed
                    # per document, so a 900-file adopt with two failures
                    # does not have to be read to find them.
                    hooks.emit(prep.forest, "ingest.document.failed",
                               prep.principal,
                               {"job": job.id, "document": step.get("file"),
                                "index": step.get("index"),
                                "total": job.total})
        except Exception as e:  # noqa: BLE001 — a job must land somewhere
            err = (e.to_dict() if isinstance(e, VineError)
                   else VineError(E_SCHEMA, f"ingest failed: {e}"[:300]).to_dict())
            partial = {**prep.steps.report.as_dict(), "mode": prep.mode,
                       "staged": prep.staged}
            board.finish(job, "error", report=partial, error=err.get("error", err))
            hooks.emit(prep.forest, "ingest.failed", prep.principal,
                       {"job": job.id, "mode": prep.mode, "done": job.done,
                        "total": job.total,
                        "code": (err.get("error") or {}).get("code")
                        if isinstance(err.get("error"), dict) else None})
            registry.record(
                principal=prep.principal, forest=prep.forest, primitive="ingest",
                args={**prep.payload, "job": job.id}, result="error",
                size=len(json.dumps(err)))

    def _launch_ingest(prep: PreparedIngest):
        prep.job.task = asyncio.get_running_loop().create_task(
            _drive_ingest(prep))
        hooks.emit(prep.forest, "ingest.started", prep.principal,
                   {"job": prep.job.id, "mode": prep.mode,
                    "total": prep.job.total})
        return prep.job

    # -- re-curating the scent (J.13.6.1) ------------------------------------

    def _recurate_report(prep: PreparedRecurate) -> dict:
        """On the forest lane: the pass's account, finished or partial.

        The curation block is the ingest report's, verbatim — five states,
        not two (G.4 rule 6): the Curator falls back silently by contract,
        so "never answered" and "answered and was rejected" produce the same
        nodes and need opposite fixes. A re-curation is the one run where
        that distinction is the whole story, since a pass that fell back on
        every node changed nothing and cost a model call each time.
        """
        from monkeyllm.gardener import scent_result

        out = scent_result(prep.steps)
        stats = dict(prep.curator.stats)
        if prep.curator.last_error:
            stats["error"] = prep.curator.last_error
        if prep.curator.last_reject:
            stats["rejected_because"] = prep.curator.last_reject
            stats["last_reply"] = prep.curator.last_reply or ""
        after = _git(prep.root, "rev-parse", "HEAD")
        out.update({
            "forest": prep.forest, "mode": RECURATE_MODE, "derive": ["scent"],
            "curated": bool(stats.get("llm_summaries")),
            "bound": True, "curation": stats,
            "commit_before": prep.before,
            # A pass that changed nothing moved no HEAD, and printing
            # `abc → abc` would read as a commit that is not there.
            "commit": (after or None) if after and after != prep.before else None,
        })
        return out

    def _step_recurate(prep: PreparedRecurate):
        """One node, with the principal on its commits (J.4).

        The trailer is set and cleared around THIS step rather than held for
        the life of the job: between steps the writer lane serves other
        calls, and a trailer left standing would stamp somebody else's
        `plant` with the name of whoever started the re-curation.
        """
        prep.vine.commit_trailers = [f"station-principal: {prep.principal}"]
        try:
            return _advance(prep.steps)
        finally:
            prep.vine.commit_trailers = []

    def _record_recurate(prep: PreparedRecurate, final: dict, state: str) -> None:
        registry.record(
            principal=prep.principal, forest=prep.forest, primitive="recurate",
            args={"derive": ["scent"], "job": prep.job.id, "state": state},
            result="ok", size=int(final.get("changed", 0)),
            commit_sha=final.get("commit"),
        )

    async def _drive_recurate(prep: PreparedRecurate) -> None:
        """One node per lane task (J.9 fairness), so a 1,877-node pass never
        holds this forest's writer lane for the length of 1,877 model calls.

        Cancellation is honoured at step boundaries: a node is curated and
        committed, or untouched — never half-written.
        """
        job, steps = prep.job, prep.steps
        try:
            while True:
                if job.cancel_requested:
                    final = await in_forest_thread(
                        prep.forest, lambda: _recurate_report(prep))
                    board.finish(job, "cancelled", report=final)
                    readers.reset(prep.forest)
                    _record_recurate(prep, final, "cancelled")
                    return
                step = await in_forest_thread(prep.forest,
                                              lambda: _step_recurate(prep))
                if step is None:
                    final = await in_forest_thread(
                        prep.forest, lambda: _recurate_report(prep))
                    board.finish(job, "done", report=final)
                    # J.6.2: a held-open reader view of a catalog that was
                    # just rewritten under it is not trusted.
                    readers.reset(prep.forest)
                    _record_recurate(prep, final, "done")
                    hooks.emit(prep.forest, "recurate.finished", prep.principal,
                               {"scanned": final.get("scanned", 0),
                                "changed": final.get("changed", 0),
                                "fallbacks": final.get("fallbacks", 0),
                                "derive": ["scent"], "job": job.id})
                    return
                board.note_step(job, step)
        except Exception as e:  # noqa: BLE001 — a job must land somewhere
            err = (e.to_dict() if isinstance(e, VineError)
                   else VineError(E_SCHEMA,
                                  f"re-curation failed: {e}"[:300]).to_dict())
            try:
                # A run that died still committed what it stepped through,
                # and the operator reading the failure is the one who needs
                # to know how much of it landed.
                partial = _recurate_report(prep)
            except Exception:  # noqa: BLE001 — the error is the report now
                from monkeyllm.gardener import scent_result

                partial = scent_result(steps)
            board.finish(job, "error", report=partial,
                         error=err.get("error", err))
            registry.record(
                principal=prep.principal, forest=prep.forest,
                primitive="recurate",
                args={"derive": ["scent"], "job": job.id}, result="error",
                size=len(json.dumps(err)))

    def _launch_recurate(prep: PreparedRecurate):
        prep.job.task = asyncio.get_running_loop().create_task(
            _drive_recurate(prep))
        return prep.job

    mcp_lifespan = None  # set below when the MCP surface is mounted

    async def _warm_boot() -> dict:
        """`warm_all`, one lane at a time: each forest must open on the
        thread that will serve it. Same shape, same best-effort rule —
        one locked forest never stops the others (J.6.1)."""
        opened, skipped = [], {}
        for entry in pool.list()["forests"]:
            fid = entry["id"]
            if entry["active"]:
                continue
            try:
                await in_forest_thread(fid, lambda fid=fid: pool.get(fid))
                opened.append(fid)
            except Exception as e:  # noqa: BLE001 — mirror warm_all
                skipped[fid] = str(e)
        for fid, why in skipped.items():
            # J.6.1 says one forest that cannot open never stops the others;
            # it does not say who finds out. Nothing serves this report —
            # `/v1/health` counts the forest among `served` and the listing
            # shows it exactly as it shows a cold one — so without this line
            # a forest can be unreachable for the whole life of the process
            # with every signal reading green. Same `station:` channel as
            # the other boot refusals, and one line per forest at boot, never
            # per request. Serving it over the API would add contract and is
            # left to a spec cut; being unable to SEE it is not a contract
            # question.
            print(f"station: forest {fid!r} did not open: {why}",
                  file=sys.stderr)
        return {"warmed": opened, "skipped": skipped}

    @asynccontextmanager
    async def lifespan(_app):
        async with AsyncExitStack() as stack:
            if mcp_lifespan is not None:
                await stack.enter_async_context(mcp_lifespan())
            # J.6.1: the first visitor should not be the one who measures a
            # cold process. Opening costs a few MB per forest and happens
            # either way — this only moves who waits for it, from whoever
            # arrives first to the boot nobody is watching.
            if warm_forests:
                _app.state.warmed = await _warm_boot()
            # J.16: one worker thread owning every outbound request. Started
            # here rather than at construction so a built-but-never-served
            # app (the test suite builds many) leaves no thread behind.
            hooks.start()
            try:
                yield
            finally:
                # Each vine closes on its own lane — the thread that opened it.
                for entry in pool.list()["forests"]:
                    if entry["active"]:
                        fid = entry["id"]
                        await in_forest_thread(
                            fid, lambda fid=fid: pool.close_one(fid))
                readers.shutdown()
                lanes.shutdown()
                hooks.stop()
                registry.close()

    # -- auth ---------------------------------------------------------------

    def principal_of(request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        key = header[7:].strip() if header.lower().startswith("bearer ") else None
        resolved = registry.resolve_key(key or request.headers.get("x-api-key"))
        # J.2.6: the mask rides with the request from the one place the key
        # is resolved, so every later authority read can intersect without
        # a second registry lookup. None = unmasked, today's behaviour.
        request.state.caps_mask = resolved["caps"] if resolved else None
        return resolved["principal"] if resolved else None

    def mask_of(request: Request):
        return getattr(request.state, "caps_mask", None)

    def require_principal(request: Request):
        principal = principal_of(request)
        if principal is None:
            return None, _envelope(VineError(E_FORBIDDEN, "missing or invalid API key"), 401)
        return principal, None

    def admin_gate(principal: str, forest: str, request: Request):
        """The two questions, answered separately (C.12 rule 6, v0.52).

        "Which forest" is a question about the request; "may I" is a
        question about the principal. Collapsing the first into the second
        told a key holding `admin` on every forest that it lacked `admin` —
        and sent its holder to audit grants over a missing query parameter.
        Naming the parameter discloses nothing: the caller already knows
        which forests it may name, and one it may not is still 403.
        """
        if not forest:
            return _envelope(VineError(
                E_SCHEMA, "parameter 'forest' is required",
                hint="Name the forest: ?forest=<id>, or \"forest\" in the body."))
        if not is_admin(principal, forest, mask=mask_of(request)):
            return _envelope(VineError(
                E_FORBIDDEN, "requires the 'admin' capability on that forest"), 403)
        return None

    def is_admin(principal: str, forest: str | None = None,
                 mask: frozenset[str] | None = None) -> bool:
        # J.2.6: the mask filters live authority at the moment of use, so a
        # masked key without 'admin' answers False before any grant — or
        # the owner bit — is read. A pair key held by the owner opens no
        # admin console, exactly as if the bit were absent.
        if mask is not None and "admin" not in mask:
            return False
        # The owner bit (J.2.4) is authority over every forest present and
        # future, so it answers before the grants are even read — including
        # when there are no forests, which is the state it exists for.
        if registry.is_owner(principal):
            return True
        grants = registry.grants_of(principal)
        if forest is not None:
            grants = [g for g in grants if g["forest"] == forest]
        return any("admin" in g["caps"] for g in grants)

    # A governance action belongs to no forest: it is about who may open them
    # (J.2), or about configuration every one of them shares (J.10). The audit
    # table wants a forest, so these rows carry this — one value, so that
    # "show me the governance trail" is a filter and not a guess.
    NO_FOREST = "-"

    def record_governance(principal: str, primitive: str, args: dict,
                          result: str, forest: str = NO_FOREST) -> None:
        """Audit a change to who may do what (J.4, A09).

        Part D records what was read and what was written. This records the
        changes that decide who gets to do either, because that is the
        question any later review starts from: when was this key made, and by
        whom.

        Same discipline as every other row: `record` digests arguments, and
        nothing secret is passed here in the first place. A key is identified
        by its non-secret prefix, a password only by the fact that one was
        set.
        """
        try:
            registry.record(principal=principal, forest=forest,
                            primitive=primitive, args=args, result=result)
        except Exception:  # pragma: no cover - the log must never break the act
            log.warning("could not audit %s by %s", primitive, principal)

    def governs_deployment(principal: str, mask: frozenset[str] | None = None) -> bool:
        """May this principal edit configuration shared by every forest?

        A provider (J.10) is one row serving all forests: its endpoint decides
        where every forest's material is sent, and its key pays for every
        forest's calls. Authority over it is therefore authority over the whole
        deployment, and administering *one* forest is not that. J.3.2 calls
        providers a host resource and leaves the reach unstated; this is the
        reach.

        Expressed as reach rather than as the owner bit alone, so the two
        accounts that legitimately have deployment-wide authority keep it: the
        break-glass environment account, which falls back to grants on every
        forest when the owner seat is taken (J.2.1), and any administrator of a
        single-forest deployment, where there is no other forest to cross into.
        A newly created forest narrows that authority the moment it exists.
        """
        if mask is not None and "admin" not in mask:
            return False
        if registry.is_owner(principal):
            return True
        forests = {f["id"] for f in pool.list()["forests"]}
        return bool(forests) and forests <= administered(principal)

    def administered(principal: str) -> set[str]:
        """The forests this principal governs (J.3.2).

        `is_admin` answers "may they in at all"; this answers "over what".
        Conflating the two is how a host route ends up returning every
        forest's governance data to whoever administers one of them.
        """
        if registry.is_owner(principal):
            return {f["id"] for f in pool.list()["forests"]}
        return {g["forest"] for g in registry.grants_of(principal)
                if "admin" in g["caps"]}

    # -- webhooks (J.16) ----------------------------------------------------

    def webhook_authority(owner: str, scope: str) -> bool:
        """Whether the principal a webhook is owned by still has the reach
        to hold it.

        Asked at every DELIVERY, not only at creation (J.16.2). A webhook is
        a standing instruction to send data outward, and v0.50's rule — a
        second forest narrows deployment authority the moment it exists,
        with nobody revoking anything — would otherwise stop at the door:
        the webhook was created while the authority held and would keep
        firing after it lapsed.

        The two reach tests are the host's own, passed in rather than
        reimplemented. A second copy of either would agree with the original
        only where somebody thought to compare them (v0.50, C.5.3).
        """
        if scope == webhooks.DEPLOYMENT:
            return governs_deployment(owner)
        return is_admin(owner, scope)

    def audit_webhook(principal: str, hook: dict, action: str,
                      extra: dict | None = None) -> None:
        """The lifecycle is a governance change, so J.4.1 records it.

        By id and destination **host**: never the path, which routinely
        carries a token (a Slack or n8n URL is a secret in its tail); never
        the secret; never a header value.
        """
        record_governance(
            principal, f"admin.webhook.{action}",
            {"webhook": hook.get("id"),
             "host": urlsplit(hook.get("url") or "").hostname or "-",
             **(extra or {})},
            "ok", forest=hook.get("scope") or NO_FOREST)

    hooks = webhooks.Dispatcher(
        registry, webhook_authority,
        audit=lambda hook, action, extra: audit_webhook(
            hook.get("owner") or NO_FOREST, hook, action, extra))

    def emit_write(principal: str, forest: str, name: str, payload: dict,
                   result: dict, commit_sha: str | None) -> None:
        """What a successful write announces (J.16.3).

        Identity only, and only what this call ALREADY held: the id, the
        type, the parent, the commit. `title` and `summary` travel
        separately as J.16.1's opt-in material — the dispatcher merges them
        per webhook, so a webhook without the opt-in never sees them and no
        webhook ever causes a read to fetch them.

        A branch and a dataset also announce themselves as one: `plant`
        fires `node.planted` for every node, and the narrower name beside
        it for the two types an automation usually cares about separately.
        """
        spec = payload.get("node") if isinstance(payload.get("node"), dict) else {}
        node_id = result.get("id") or spec.get("id") or payload.get("id")
        if name == "plant":
            kind = spec.get("type") or "note"
            data = {"node": node_id, "type": kind, "parent": spec.get("parent"),
                    "source": spec.get("source"), "commit": commit_sha}
            meta = {"title": spec.get("title"), "summary": spec.get("summary")}
            hooks.emit(forest, "node.planted", principal, data, meta)
            if kind == "branch":
                hooks.emit(forest, "branch.created", principal, data, meta)
            elif kind == "dataset":
                hooks.emit(forest, "dataset.created", principal, data, meta)
        elif name == "graft":
            patch = payload.get("patch") if isinstance(payload.get("patch"), dict) else {}
            # The operation NAMES, never the text they carried.
            hooks.emit(forest, "node.grafted", principal,
                       {"node": node_id, "operations": sorted(patch),
                        "commit": commit_sha})
        elif name == "prune":
            # C.14 rule 7: identity only, like every event — the id, what
            # it was, how many backlinks left with it, the commit.
            hooks.emit(forest, "node.pruned", principal,
                       {"node": node_id,
                        "backlinks_removed": result.get("backlinks_removed"),
                        "commit": commit_sha})
        elif name == "transplant":
            # C.15: both ids and how many pointers followed — identity,
            # never content, like every event.
            hooks.emit(forest, "node.transplanted", principal,
                       {"node": result.get("id"),
                        "moved_from": result.get("moved_from"),
                        "backlinks_rewritten":
                            result.get("backlinks_rewritten"),
                        "commit": commit_sha})
        elif name == "tend":
            hooks.emit(forest, "dataset.changed", principal,
                       {"node": node_id,
                        "rows_affected": result.get("rows_affected"),
                        "commit": commit_sha})

    def emit_answer(principal: str, forest: str, result: dict) -> None:
        """J.10 answered. The question and the reply stay behind (J.16.1):
        what goes out is that it happened, what it cost and how much
        material it stood on."""
        error = result.get("error") if isinstance(result, dict) else None
        if isinstance(error, dict):
            hooks.emit(forest, "answer.failed", principal,
                       {"code": error.get("code")})
            return
        hooks.emit(forest, "answer.served", principal, {
            "mode": result.get("mode"),
            "cached": bool(result.get("cached")),
            "evidence": len(result.get("evidence") or []),
            "cost": result.get("cost"),
        })

    def refusal_code(result) -> str | None:
        """The envelope's code, or None when nothing was refused (J.4.2).

        The CODE and never the message: a code is a closed vocabulary, while
        a message carries hints that name nodes, terms and table names — and
        the audit log records access, not content (J.4).
        """
        error = result.get("error") if isinstance(result, dict) else None
        return (error or {}).get("code") or None

    def engine_ms(events) -> float | None:
        """This call's own span, off the Part D slice it already produced.

        `None` when the slice is empty, which is not the same as zero: a
        call refused by the policy never reached the engine, and a row
        claiming it took 0.0 ms would be describing work that did not
        happen (J.4.2).
        """
        total = sum(e["elapsed_ms"] for e in events or ())
        return round(float(total), 3) if events else None

    def emit_refusal(principal: str, forest: str, name: str, result) -> None:
        """A scoped call was refused. The security signal an automation
        actually wants, and it costs nothing to say: the refusal already
        happened and is already audited."""
        code = refusal_code(result)
        if code in (E_FORBIDDEN, E_QUERY_FORBIDDEN):
            hooks.emit(forest, "access.denied", principal,
                       {"primitive": name, "code": code})

    def ingest_counts(report: dict | None) -> dict:
        """A G.10 report as COUNTS. The report itself is lists of file names
        and a batch can be thousands of them — a webhook body is a
        notification, not an export (J.16.1)."""
        return {k: len(v) for k, v in (report or {}).items()
                if isinstance(v, list)}

    # -- forest calls -------------------------------------------------------

    # One embedder per (endpoint, model, key). The Vine caches per forest and
    # exposes `embedder` as a plain attribute for exactly this — the Station
    # supplies one without forking `ForestPool` (J.0).
    _embedders: dict[tuple, object] = {}

    def attach_embedder(vine, forest: str) -> None:
        # Switching the Gauntlet off is expressed as "there is no embedder",
        # deliberately: that is the state Part K already promises to be
        # byte-identical to v0.20, and it is the one the suite proves. A
        # second, parallel "disabled" path would need its own proof.
        binding = (registry.binding(forest, "embed")
                   if registry.setting(forest, "gauntlet", True) else None)
        if not binding or not binding.get("endpoint") or not binding.get("model"):
            vine.embedder = None
            return
        key = (binding["endpoint"], binding["model"], binding.get("api_key"))
        if key not in _embedders:
            from monkeyllm_station import inference

            _embedders[key] = inference.embedder_from_binding(binding)
        vine.embedder = _embedders[key]

    def run_primitive(principal: str, forest: str, name: str, payload: dict,
                      clocks: dict | None = None,
                      caps_mask: frozenset[str] | None = None,
                      sample: dict | None = None,
                      defer_model: bool = False,
                      get_vine=None):
        """Executed on the forest thread: resolve, scope, call, attribute.

        `caps_mask` is J.2.6's narrowing, resolved by the surface BEFORE the
        thread hop — a contextvar does not cross the lane, and the mask
        belongs to the credential, which only the surface saw.

        `clocks`, when a caller supplies one, is filled with the three
        durations of J.10.6: the engine, the provider round trip when there
        was one, and whatever is left of the host's span — policy, the audit
        record, serialisation, the thread hop. An out-parameter rather than a
        second return value, because the MCP surface calls this too and has
        no header to carry them: a timing is the console's channel, never the
        agent's.

        The engine figure is read off the tracer, so it is the same slice
        J.10.4 already reports and not a second instrumentation.

        `get_vine` (J.6.2, v0.57) resolves this lane's own Vine — the
        reader pool's slot when the call rides one, `pool.get` otherwise.
        `defer_model` (J.10.11) makes a sweep `answer` stop at the lane
        boundary instead of holding it through the provider round trip:
        the miss path returns `{"_deferred": …}` for the loop to finish.
        `sample` may be handed in so the deferring caller reads what the
        prepare phase left behind.
        """
        span = time.perf_counter()
        if sample is None:
            sample = {}
        if defer_model:
            sample["defer_model"] = True
        try:
            return dispatch(principal, forest, name, payload, sample,
                            caps_mask=caps_mask, get_vine=get_vine)
        except VineError as e:
            return e.to_dict()
        except Exception as e:
            # C.12 rule 5, on the path both surfaces share: MCP has no HTTP
            # handler of ours to fall back to, and an agent reading a
            # transport-level failure cannot tell it from its own bad call.
            log.exception("unhandled error in %s on %s", name, forest)
            return VineError(
                E_INTERNAL,
                f"'{name}' failed inside the Station ({type(e).__name__})",
                hint="This is a defect on the server, not in your call.",
            ).to_dict()
        finally:
            if clocks is not None:
                tracer, mark = sample.get("tracer"), sample.get("mark", 0)
                slice_ = tracer.events[mark:] if tracer is not None else []
                engine = float(sum(e["elapsed_ms"] for e in slice_))
                model = sample.get("model")
                store_ms = sample.get("cache")
                clocks["vine"] = round(engine, 3)
                # J.10.4.1 (v0.71): the dense layer's two shares, as clocks.
                # A single primitive gets no `trace` — the body would carry a
                # one-step list saying what the header already says — so
                # without these a bare hybrid `locate` had nowhere to report
                # that 68 of its 80 ms were a vector scan.
                #
                # They are shares INSIDE `vine`, never beside it: `host`
                # keeps subtracting `engine` alone, and a client summing
                # every clock must not add these twice.
                for key, field in (("embed", "embed_ms"), ("dense", "dense_ms")):
                    share = sum(e.get(field) or 0.0 for e in slice_)
                    if share:
                        clocks[key] = round(share, 3)
                if model is not None:
                    clocks["model"] = round(model, 3)
                if store_ms is not None:
                    clocks["cache"] = round(store_ms, 3)
                # The remainder, floored at zero: the clocks present add up
                # to the span, so subtracting them from a client's stopwatch
                # leaves transport and nothing else.
                clocks["host"] = round(max(0.0, (time.perf_counter() - span) * 1000
                                           - engine - (model or 0.0)
                                           - (store_ms or 0.0)), 3)

    def dispatch(principal: str, forest: str, name: str, payload: dict,
                 sample: dict, caps_mask: frozenset[str] | None = None,
                 get_vine=None):
        """The call itself. `sample` is where it leaves what it alone knows:
        the tracer to read the engine's clock off, and the provider's."""
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return None
        # J.2.6: grants ∩ mask, at the moment of use — this is the ONE seam
        # where the registry's policy feeds the primitive dispatch, so every
        # primitive, composite and ingest below inherits the narrowing.
        policy = policy.masked(caps_mask)
        try:
            vine = get_vine() if get_vine is not None else pool.get(forest)
        except VineError as e:
            # Past the policy check the forest's existence is no longer a
            # secret from this caller — they hold a grant on it and
            # `GET /v1/forests` already lists it. Laundering the real reason
            # into "unknown forest" here sent operators hunting for a naming
            # mistake that was not there: the usual cause is `E_LOCKED`, a
            # writer lock left behind by a Station that did not shut down.
            return e.to_dict()
        attach_embedder(vine, forest)
        # K.3, entry search: set on every call, never left over from the last
        # one. `False` is both the default and the reset.
        vine.hybrid_locate = bool(payload.pop("hybrid", False))
        # J.10.12: the progress channel's rendezvous. Popped here for the
        # reason `hybrid` is — it is the host's field, not the primitive's,
        # so what `validate_args` checks below is what the composite reads.
        # An id nobody claimed keys nothing, so an unwatched call publishes
        # into a record that does not exist and pays a dict lookup for it.
        run_id = payload.pop("run", None)
        if isinstance(run_id, str) and run_id:
            sample["run_key"] = (principal, forest, run_id[:RUN_ID_MAX])
        mark = len(vine.tracer.events)
        # Where the engine's own clock starts for this call (J.10.6). Read
        # after the fact rather than accumulated here, so there is still only
        # one instrumentation and it is Part D's.
        sample.update(tracer=vine.tracer, mark=mark)

        if name in COMPOSITES or name in HOST_ACTIONS:
            if name in COMPOSITES:
                try:
                    # C.12 rule 1: the composites read the same declaration
                    # the primitives do. `hybrid` was popped above, so what
                    # is checked here is what the composite will read.
                    payload = validate_args(name, payload)
                except VineError as e:
                    return e.to_dict()
                result = run_composite(principal, forest, vine, policy, name,
                                       payload, sample)
            else:
                result = run_ingest(principal, forest, vine, policy, name, payload)
            if isinstance(result, dict) and "_prepared" in result:
                # J.9: an accepted batch. The audit row waits for the job to
                # finish — the ingest is the fact being recorded, and it has
                # not happened yet.
                return result
            if isinstance(result, dict) and "_deferred" in result:
                # J.10.11: the sweep's miss path, stopping at the lane
                # boundary. The trace slice is captured HERE — the lane
                # serves other calls while the model writes, and a trace
                # read later would carry a stranger's hops.
                result["_deferred"].update(
                    vine=vine, mark=mark,
                    events=list(vine.tracer.events[mark:]))
                return result
            return composite_tail(principal, forest, vine, name, payload,
                                  sample, result, mark)

        root_path = Path(vine.forest.root)
        # J.4 (v0.57): the principal is stamped at the commit, never amended
        # after — the engine's `commit_trailers` seam carries it into the
        # original commit. The amend survives only as the fallback for an
        # engine without the seam.
        trailer_seam = (name in WRITE_PRIMITIVES
                        and hasattr(vine, "commit_trailers"))
        before = (_git(root_path, "rev-parse", "HEAD")
                  if name in WRITE_PRIMITIVES and not trailer_seam else None)
        if trailer_seam:
            vine.commit_trailers = [f"station-principal: {principal}"]
        try:
            result = ScopedVine(vine, policy).call(name, **payload)
        finally:
            if trailer_seam:
                vine.commit_trailers = []
        if name in EXPLAINED:
            result = explain(result, vine, mark)

        commit_sha = None
        if name in WRITE_PRIMITIVES and isinstance(result, dict) and "error" not in result:
            commit_sha = (result.get("commit") if trailer_seam
                          else stamp_principal(root_path, principal, before))
            if commit_sha and result.get("commit"):
                result["commit"] = commit_sha
            if isinstance(result.get("trail"), list):
                result["trail"] = [t for t in result["trail"] if policy.in_scope(t)]

        registry.record(
            principal=principal, forest=forest, primitive=name, args=payload,
            result="error" if (isinstance(result, dict) and "error" in result) else "ok",
            size=len(json.dumps(result, default=str)), commit_sha=commit_sha,
            # J.4.2: the same slice `Server-Timing: vine` reports, read here
            # rather than measured again — one instrumentation, two readers.
            ms=engine_ms(vine.tracer.events[mark:]),
            error_code=refusal_code(result),
        )
        if (name in WRITE_PRIMITIVES and isinstance(result, dict)
                and "error" not in result):
            emit_write(principal, forest, name, payload, result, commit_sha)
        emit_refusal(principal, forest, name, result)
        return result

    def composite_tail(principal, forest, vine, name, payload, sample,
                       result, mark, events=None):
        """The composite's close: trace, cost, store, audit, webhooks —
        one function because the deferred answer (J.10.11) finishes with
        exactly the steps the lane-bound path always ran. `events` is the
        prepare phase's captured trace slice; absent, the live tracer is
        read as ever.

        A sweep hit is explained like any call — the retrieval that
        produced its trace is this call's own work (J.10.7 v0.35). Only a
        walk hit is a whole record and keeps its stored trace. Cost is
        attached only when a provider actually ran: a hit already carries
        the original run's cost as the record it is, and re-billing the
        recorded usage would spend it twice.
        """
        hit = isinstance(result, dict) and result.get("cached")
        if isinstance(result, dict) and not hit:
            sample["model"] = result.get("model_ms")
        if name in EXPLAINED and not (hit and sample.get("cache_walk_hit")):
            result = explain(result, vine, mark, events=events)
            if name in COMPOSITES and isinstance(result, dict) \
                    and "error" not in result and not hit:
                billed = cost_of(result, registry.binding(forest, COMPOSITES[name][1]) or {})
                if billed:
                    result["cost"] = billed
        if not hit:
            # The deposit happens after the trace and the cost are
            # attached, so the entry is the response exactly as served.
            store_answer(sample, result)
        digest = sample.get("cache_hit")
        registry.record(
            principal=principal, forest=forest, primitive=name,
            args={**payload, "cache_key": digest} if digest else payload,
            result="cache" if hit
            else ("error" if isinstance(result.get("error"), dict) else "ok"),
            size=len(json.dumps(result, default=str)),
            commit_sha=result.get("commit"),
            # J.4.2. The clocks come apart on purpose (J.10.4.1's reason):
            # a deployment dominated by the forest buys a different fix from
            # one dominated by the provider, and one merged figure sends
            # half its readers to repair the wrong half.
            ms=engine_ms(events if events is not None
                         else vine.tracer.events[mark:]),
            model_ms=sample.get("model"),
            error_code=refusal_code(result),
            # On a hit this is the ORIGINAL run's figure and the row's own
            # `result` is what says it was avoided rather than spent (J.4.2):
            # two fields saying that would eventually disagree.
            cost=result.get("cost") if isinstance(result, dict) else None,
        )
        # J.16: after the record, before the return. The act is complete
        # and audited; the announcement is O(1) when nobody subscribes
        # and a queue push when somebody does, so the caller waits for
        # neither DNS nor a socket.
        if name in COMPOSITES:
            emit_answer(principal, forest, result)
        emit_refusal(principal, forest, name, result)
        return result

    def settle_answer(principal, forest, payload, sample, deferred, served):
        """J.10.11 phase 3, on the lane of phase 1: whisper, then the tail.

        The whisper closes the hunt either way (v0.35): a hit and a miss
        heat identically, because the knowledge was used identically.
        """
        whisper(deferred["vine"], served.get("evidence")
                if isinstance(served, dict) else None)
        reply = deferred.get("reply")
        if reply and isinstance(served, dict) and "error" not in served:
            served.setdefault("reply_tokens", reply)
        return composite_tail(principal, forest, deferred["vine"], "answer",
                              payload, sample, served, deferred["mark"],
                              events=deferred["events"])

    async def run_answer(principal, forest, payload, clocks, mask,
                         slot: int | None):
        """J.10.11: prepare on a lane, the model on none, settle back.

        Phase 1 completes hits, refusals, floors and errors on the lane,
        byte-identical to before. Only the miss path crosses: the bundle,
        binding and question leave the lane as values, the provider round
        trip runs on an anonymous executor thread, and the settle is
        pinned to the lane of phase 1 — the vine whose trails the whisper
        feeds belongs to that thread.
        """
        from monkeyllm_station import inference

        span = time.perf_counter()
        sample: dict = {}
        get_vine = ((lambda: readers.vine(forest, slot))
                    if slot is not None else None)
        prep = await in_lane(
            forest, slot,
            lambda: run_primitive(principal, forest, "answer", payload,
                                  clocks, mask, sample=sample,
                                  defer_model=True, get_vine=get_vine))
        if not (isinstance(prep, dict) and "_deferred" in prep):
            return prep
        deferred = prep["_deferred"]

        # J.10.7 (v0.58): identical questions in flight share one
        # generation. A follower awaits the leader on the loop — no lane
        # held — then re-consults the store under its OWN reading
        # fingerprint; the reading check decides, exactly as ever.
        stash = sample.get("cache_store")
        flight_key = ((forest, stash["key"])
                      if stash and payload.get("cache", True) is not False
                      else None)
        leading = False
        if flight_key is not None:
            waiting = inflight.get(flight_key)
            if waiting is not None:
                await waiting.wait()
                served = recheck_store(forest, sample, deferred["bundle"])
                if served is not None:
                    return await in_lane(
                        forest, slot,
                        lambda: settle_answer(principal, forest, payload,
                                              sample, deferred, served))
            else:
                inflight[flight_key] = asyncio.Event()
                leading = True
        try:
            if model_gate is not None:
                # J.10.11: admitted under the deployment's stated ceiling.
                async with model_gate:
                    served = await asyncio.to_thread(
                        inference.answer, deferred["scoped"],
                        deferred["question"], deferred["binding"],
                        k=deferred["k"], bundle=deferred["bundle"],
                        reply_tokens=deferred["reply"])
            else:
                served = await asyncio.to_thread(
                    inference.answer, deferred["scoped"],
                    deferred["question"], deferred["binding"],
                    k=deferred["k"], bundle=deferred["bundle"],
                    reply_tokens=deferred["reply"])
        except VineError as e:
            served = e.to_dict()
        except Exception as e:  # provider outages must not 500 the Station
            served = VineError(E_SCHEMA, f"answer failed: {e}"[:300]).to_dict()
        try:
            result = await in_lane(
                forest, slot,
                lambda: settle_answer(principal, forest, payload, sample,
                                      deferred, served))
        finally:
            if leading:
                # Released after the settle, so a follower waking up finds
                # the entry already deposited — and released even when the
                # leader errored or declined to store, because coalescing
                # is an optimisation over the store, never a second source
                # of truth: the followers simply run their own calls.
                inflight.pop(flight_key).set()
        if clocks is not None:
            # J.10.6 across the phases: `vine` is phase 1's captured engine
            # time (already in clocks), `model` is phase 2's round trip,
            # `host` the remainder of the whole span.
            model = sample.get("model")
            store_ms = sample.get("cache")
            if model is not None:
                clocks["model"] = round(model, 3)
            if store_ms is not None:
                clocks["cache"] = round(store_ms, 3)
            clocks["host"] = round(max(0.0, (time.perf_counter() - span) * 1000
                                       - clocks.get("vine", 0.0)
                                       - (model or 0.0)
                                       - (store_ms or 0.0)), 3)
        return result

    async def execute_call(principal, forest, name, payload, clocks, mask):
        """One door for both surfaces (REST and MCP): route the call to its
        lane (J.6.2), and take the sweep `answer` through the three phases
        of J.10.11. The walk (`hops`) stays lane-bound by design — it
        interleaves reads with model turns, opt-in per call."""
        slot = reader_slot(forest, name)
        if name == "answer" and not (payload or {}).get("hops"):
            return await run_answer(principal, forest, payload, clocks, mask,
                                    slot)
        get_vine = ((lambda: readers.vine(forest, slot))
                    if slot is not None else None)
        return await in_lane(
            forest, slot,
            lambda: run_primitive(principal, forest, name, payload, clocks,
                                  mask, get_vine=get_vine))

    # Per-token prices, as the provider itself states them (J.10). Fetched
    # once per endpoint and kept for the life of the process: a price list is
    # not something to re-download on every question, and a stale one is
    # fixed by the restart that any other configuration change needs anyway.
    _prices: dict[str, dict] = {}

    def price_of(binding: dict) -> dict | None:
        endpoint, model = binding.get("endpoint"), binding.get("model")
        if not endpoint or not model:
            return None
        if endpoint not in _prices:
            from monkeyllm_station import inference

            probed = inference.probe(endpoint, binding.get("api_key"))
            _prices[endpoint] = {m["id"]: m for m in (probed.get("models") or [])}
        entry = _prices[endpoint].get(model)
        if not entry or (entry.get("prompt") is None and entry.get("completion") is None):
            return None
        return entry

    def cost_of(result: dict, binding: dict) -> dict | None:
        """What this answer cost, when the provider states a price.

        Never an estimate: the tokens are the provider's own `usage` and the
        rates are its own catalogue. A local Ollama publishes neither, and
        that is reported as "not priced" rather than as free — the same rule
        the model picker already follows, because silence is not zero.
        """
        usage = result.get("usage") or {}
        if not usage.get("calls"):
            return None
        out = {"prompt_tokens": usage.get("prompt", 0),
               "completion_tokens": usage.get("completion", 0),
               "calls": usage["calls"], "priced": False}
        rates = price_of(binding)
        if rates:
            prompt_usd = (rates.get("prompt") or 0) * out["prompt_tokens"]
            completion_usd = (rates.get("completion") or 0) * out["completion_tokens"]
            out.update(priced=True, prompt_usd=round(prompt_usd, 8),
                       completion_usd=round(completion_usd, 8),
                       usd=round(prompt_usd + completion_usd, 8))
        return out

    def explain(result: dict, vine, mark: int, events=None) -> dict:
        """Attach what the call actually did, step by step (J.10.4).

        A composite is opaque from outside: `answer` is one request and six
        forest calls plus a provider round trip, and "it took 1.8 s" says
        nothing about which of those to fix. The engine already times every
        primitive it runs (Part D), so this is a slice of that trace — the
        events this call appended — not a second instrumentation.

        `events` (J.10.11, v0.57) is the prepare phase's captured slice: a
        deferred answer settles after the lane served other calls, so a
        live read of `tracer.events[mark:]` would carry a stranger's hops.

        Only the shape of the work is reported: the primitive, the node when
        the primitive takes one, the milliseconds and the tokens it emitted.
        No arguments and no content, so a trace can never disclose what a
        scoped response withheld.
        """
        if not isinstance(result, dict) or "error" in result:
            return result
        steps = [
            {"step": e["primitive"], "ms": e["elapsed_ms"], "tokens": e["tokens_out"],
             **({"id": e["id"]} if e["id"] else {}),
             # The K.2 embed's share of this step (v0.68): a provider round
             # trip inside the engine's span, named so the panel never
             # reads it as the forest's own work.
             **({"embed_ms": e["embed_ms"]} if e.get("embed_ms") is not None else {}),
             # The Canopy scan's share (v0.71): the same discipline, the
             # other provider-less half of a hybrid entry.
             **({"dense_ms": e["dense_ms"]} if e.get("dense_ms") is not None else {})}
            for e in (events if events is not None
                      else vine.tracer.events[mark:])
        ]
        # A forager's forest calls ARE its hops, in the same order, minus the
        # entry `locate` it did not choose and minus the ones the policy
        # refused before they reached the engine. Numbering them here lets
        # one panel show a step and the decision that caused it.
        walked = iter([h for h in result.get("hops") or [] if h.get("ok")])
        nxt = next(walked, None)
        for step in steps[1:] if result.get("hops") is not None else []:
            if nxt and step["step"] == nxt["tool"] and step.get("id") == nxt.get("id"):
                step["hop"] = nxt["n"]
                nxt = next(walked, None)
        if result.get("model_ms") is not None:
            steps.append({"step": "model", "ms": result["model_ms"],
                          "detail": result.get("model")})
        result["trace"] = {
            "steps": steps,
            "retrieval_ms": round(sum(s["ms"] for s in steps if s["step"] != "model"), 1),
            "total_ms": round(sum(s["ms"] for s in steps), 1),
        }
        # J.10.4 (v0.68): the embedder's summed share, only when one ran —
        # `retrieval_ms` keeps its meaning (the whole engine span) and the
        # console subtracts, so no shipped number is redefined.
        embed_total = round(sum(s.get("embed_ms", 0.0) for s in steps), 1)
        if embed_total:
            result["trace"]["embed_ms"] = embed_total
        dense_total = round(sum(s.get("dense_ms", 0.0) for s in steps), 1)
        if dense_total:
            result["trace"]["dense_ms"] = dense_total
        return result

    # The answer store's per-forest switches (J.10.7). `ttl_hours` is
    # hygiene, never correctness — the key already invalidates — so its
    # default is off; the bound is a stated cap, because a silent unbounded
    # store is C.6's sin in yet another costume.
    CACHE_DEFAULTS = {"enabled": True, "max_entries": 500, "ttl_hours": None}

    def cache_settings(forest: str) -> dict:
        cfg = dict(CACHE_DEFAULTS)
        stored = registry.setting(forest, "answer_cache", None)
        if isinstance(stored, dict):
            cfg.update({key: stored[key] for key in CACHE_DEFAULTS if key in stored})
        return cfg

    def whisper(vine, evidence) -> None:
        """Part D's close for a hosted answer (J.10.7 v0.35): heat on the
        winning trail, hit or miss alike, through the trails store — the
        channel the engine's own session close uses, never a primitive."""
        ids = [e for e in (evidence or []) if isinstance(e, str)]
        if ids:
            vine.trails.add_heat(ids)

    def consult_walk_store(sample, forest, vine, policy, binding, payload,
                           question, k, budget, reply_tokens=None,
                           window=None):
        """The walk's J.10.7 lookup, unchanged from v0.33: HEAD in the key
        (a walk cannot be re-walked without paying the model per hop), the
        stored response served whole, and heat deposited through the trails
        store — the one place the store still skips the forest entirely.

        Reached only past the policy and the binding, so nobody the forest
        refuses can be answered by its store. Returns the served record on a
        hit; otherwise arms the deposit in `sample` and returns None.
        """
        cfg = cache_settings(forest)
        if sample is None or not cfg["enabled"]:
            return None
        from monkeyllm.harvest import derive_terms

        t0 = time.perf_counter()
        head = _git(Path(vine.forest.root), "rev-parse", "HEAD")
        # The walk's `k` is not capped by C.6c and keys as given. Its
        # effective terms are the derived ones and can be nothing else:
        # `terms` beside `hops` is refused before this point (J.10.3), so
        # this IS the "or the sweep derived them" half of J.10.7 rule 2.
        key = answer_store.build_key(
            question=question, terms=derive_terms(question),
            k=k, hops=budget, window=window,
            hybrid=bool(getattr(vine, "hybrid_locate", False)),
            binding=binding, policy=policy, head=head,
            reply_tokens=reply_tokens)
        store = answer_store.AnswerStore(Path(vine.forest.root))
        sample["cache_store"] = {"store": store, "key": key,
                                 "question": question,
                                 "bound": cfg["max_entries"]}
        entry = None
        if payload.get("cache", True) is not False:
            entry = store.get(key, ttl_hours=cfg["ttl_hours"])
            if entry is None:
                store.count_miss()
        if entry is None:
            sample["cache"] = sample.get("cache", 0.0) \
                + (time.perf_counter() - t0) * 1000
            return None
        result = json.loads(entry["response"])
        result["cached"] = True
        result["cached_at"] = entry["created"]
        # No primitive ran and none may appear to have (v0.33): heat goes
        # through the trails store, and the stored trace is served as the
        # record it is.
        trail = [t for t in json.loads(entry["trail"] or "[]")
                 if isinstance(t, str)]
        if trail:
            vine.trails.add_heat(trail)
        store.touch(key, priced=bool(entry["priced"]), usd=entry["usd"])
        digest = key[:answer_store.DIGEST_CHARS]
        sample["cache_hit"] = digest
        sample["cache_walk_hit"] = True
        sample["cache"] = sample.get("cache", 0.0) \
            + (time.perf_counter() - t0) * 1000
        log.info("answer served from the store: forest=%s key=%s", forest, digest)
        return result

    def serve_from_reading(sample, forest, vine, policy, binding, payload,
                           question, k, bundle, reply_tokens=None,
                           window=None, include_superseded=False):
        """The sweep's J.10.7 check (v0.35): the key finds the entry, the
        reading decides the model. The sweep already ran — this function
        never touches a primitive, so a hit's trace and pheromone are the
        retrieval's own.

        Returns the assembled response on a hit — fresh retrieval fields,
        stored model fields. Otherwise counts the miss (absent entry or a
        reading that changed), arms the deposit in `sample`, and returns
        None so the model runs on the bundle it was going to read anyway.
        """
        cfg = cache_settings(forest)
        if sample is None or not cfg["enabled"]:
            return None
        from monkeyllm.harvest import clamp_k, derive_terms

        t0 = time.perf_counter()
        # J.10.7 rule 2 (v0.67): the EFFECTIVE terms — the ones the call
        # actually used, whether the caller supplied them (J.10.3) or the
        # sweep derived them. The bundle states them (C.6c), so the key
        # reads them off the retrieval that just ran instead of deriving a
        # second copy of the same list. A caller who sends none keys exactly
        # as before this version, so no stored entry is invalidated.
        terms = bundle.get("terms")
        if terms is None:  # a bundle with no terms field: derive, as ever.
            terms = derive_terms(question)
        # The sweep's answer is shaped by the C.6c cap, so the capped value
        # is what names it (J.10.7): a cap raised between restarts misses
        # cleanly instead of serving five-banana answers under a ten-banana
        # promise.
        key = answer_store.build_key(
            question=question, terms=terms,
            k=clamp_k(k), hops=None, window=window,
            hybrid=bool(getattr(vine, "hybrid_locate", False)),
            binding=binding, policy=policy, head=None,
            reply_tokens=reply_tokens,
            # C.6c.4 rule 4: the history view is a different reading, so it
            # is a different entry. The fingerprint would already refuse to
            # serve one for the other, but a key that cannot tell them apart
            # makes each one evict the other on a forest where both are
            # asked.
            include_superseded=include_superseded)
        fingerprint = answer_store.reading_fingerprint(bundle)
        store = answer_store.AnswerStore(Path(vine.forest.root))
        sample["cache_store"] = {"store": store, "key": key,
                                 "question": question,
                                 "fingerprint": fingerprint,
                                 "bound": cfg["max_entries"]}
        served = None
        if payload.get("cache", True) is not False and bundle.get("results"):
            entry = store.get(key, ttl_hours=cfg["ttl_hours"])
            if entry is not None and entry["fingerprint"] == fingerprint:
                served = assemble_stored(entry, bundle)
                store.touch(key, priced=bool(entry["priced"]), usd=entry["usd"])
                digest = key[:answer_store.DIGEST_CHARS]
                sample["cache_hit"] = digest
                log.info("answer served from the store: forest=%s key=%s",
                         forest, digest)
            else:
                store.count_miss()
        sample["cache"] = sample.get("cache", 0.0) \
            + (time.perf_counter() - t0) * 1000
        return served

    def assemble_stored(entry, bundle: dict) -> dict:
        """One stored entry, served against THIS call's retrieval.

        Which half is which (J.10.7 v0.35): retrieval fields are this
        call's own; model fields are the record, as bought. No `model_ms`,
        so neither the trace nor the clocks claim a provider ran.
        """
        stored = json.loads(entry["response"])
        served = {
            "answer": stored.get("answer"),
            "model": stored.get("model"),
            "usage": stored.get("usage"),
            "cached": True,
            "cached_at": entry["created"],
            "evidence": [r.get("id") for r in bundle.get("results", [])],
            "sources": [{"id": r.get("id"), "title": r.get("title"),
                         "summary": r.get("summary"), "type": r.get("type")}
                        for r in bundle.get("results", [])],
            "harvest": bundle,
        }
        if stored.get("cost"):
            served["cost"] = stored["cost"]
        return served

    def recheck_store(forest: str, sample: dict, bundle: dict):
        """J.10.7 (v0.58): the follower's second look, after the leader.

        Runs on no lane and touches no primitive — the stash from this
        call's own prepare phase already holds the store, the key and
        THIS caller's reading fingerprint, so a follower whose reading
        matches the leader's is served the reply the leader bought, and
        one whose reading differs falls through to its own model call,
        exactly as the reading check always ruled.
        """
        stash = sample.get("cache_store")
        if not stash:
            return None
        t0 = time.perf_counter()
        cfg = cache_settings(forest)
        entry = stash["store"].get(stash["key"], ttl_hours=cfg["ttl_hours"])
        served = None
        if entry is not None and entry["fingerprint"] == stash.get("fingerprint"):
            served = assemble_stored(entry, bundle)
            stash["store"].touch(stash["key"], priced=bool(entry["priced"]),
                                 usd=entry["usd"])
            digest = stash["key"][:answer_store.DIGEST_CHARS]
            sample["cache_hit"] = digest
            log.info("answer coalesced onto a leader: forest=%s key=%s",
                     forest, digest)
        sample["cache"] = sample.get("cache", 0.0) \
            + (time.perf_counter() - t0) * 1000
        return served

    def store_answer(sample: dict, result) -> None:
        """The miss path's deposit (J.10.7), armed by the consult above.

        `storable` refuses the empty and the broken: an errored or truncated
        run, a turn that wrote, an answer with no text or no evidence — none
        of them are worth a key.
        """
        stash = sample.get("cache_store")
        if not stash or not answer_store.storable(
                result if isinstance(result, dict) else {}):
            return
        t0 = time.perf_counter()
        cost = result.get("cost") or {}
        stash["store"].put(
            stash["key"], question=stash["question"],
            response=json.dumps(result, default=str),
            trail=[e for e in result.get("evidence") or []
                   if isinstance(e, str)],
            priced=bool(cost.get("priced")), usd=cost.get("usd"),
            bound=stash["bound"], fingerprint=stash.get("fingerprint"))
        sample["cache"] = sample.get("cache", 0.0) \
            + (time.perf_counter() - t0) * 1000

    def declined_for_evidence(payload: dict, bundle: dict, k: int):
        """J.10.10: `answer` that does not answer, and says why.

        `min_evidence` is NOT part of the J.10.7 key: it cannot change what
        the model would write, only whether it is asked — and a refusal
        never enters the store, so no entry can be created under it. The
        count is of items that carry content: a result with a title and no
        body is a pointer, and a floor that counted pointers would be
        satisfied by exactly the material it exists to refuse.

        `min_score` (v0.59) is the other half. Counting items alone made
        the guard fire only on a nearly empty forest: the sweep returns `k`
        items whatever their scores, so a question with no answer in the
        corpus came back with three items scoring 0.0164, 0.0164 and 0.0161
        and passed a floor of two. The threshold is applied BEFORE the
        count, so the two compose into one floor — n items that clear s —
        and it shares every property of `min_evidence`: outside the key,
        never billed, never stored.
        """
        from monkeyllm.harvest import clamp_k

        raw = payload.get("min_evidence") or 0
        floor = max(0, min(int(raw), clamp_k(k)))
        try:
            threshold = max(0.0, float(payload.get("min_score") or 0))
        except (TypeError, ValueError):
            raise VineError(
                E_SCHEMA, "min_score must be a number",
                hint="It is a retrieval score threshold, e.g. 0.02.")
        if not floor:
            return None
        carrying = [r for r in bundle.get("results") or [] if r.get("content")]
        items = [r for r in carrying
                 if not threshold or (r.get("score") or 0) >= threshold]
        if len(items) >= floor:
            return None
        out = {"answer": None, "reason": "insufficient_evidence",
               "evidence_count": len(items), "min_evidence": floor}
        if threshold:
            # A refusal that hides which knob fired is a knob nobody can
            # tune.
            out["min_score"] = threshold
        # J.10.10 rule 8 (v0.61): which half refused. RRF output is
        # compressed, so a threshold that means anything usually admits the
        # ONE item that is top of both retrievers — and `min_evidence: 2`,
        # the value a caller picks to mean "I want two sources", then
        # refuses questions the forest answers correctly. Measured twice on
        # one live forest. `evidence_count + below_min_score` is the count
        # with no threshold, which is what tells a caller whether to lower
        # the floor or the threshold.
        out["below_min_score"] = len(carrying) - len(items)
        out["harvest"] = bundle
        return out

    def run_composite(principal, forest, vine, policy, name, payload,
                      sample: dict | None = None) -> dict:
        """Retrieval (scoped, deterministic) plus the forest's bound model.

        The model only ever sees material the principal could already read,
        so binding a model cannot become a way around the policy. For
        `answer`, the store of J.10.7 sits exactly here — after the
        capability and the binding were checked, before the model is paid.
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
                question = payload.get("question") or payload.get("query") or ""
                k = int(payload.get("k", 3))
                # C.13.1 through the composite: the window bounds the sweep's
                # retrieval, so it also names the entry (J.10.7). The same
                # question asked of June and of July is two questions, and an
                # entry shared between them would answer one with the other.
                window = normalize_window(payload.get("since"),
                                          payload.get("until"),
                                          payload.get("date_field"))
                # J.10.8: per-call reply size, clamped once — the same value
                # caps the model call, rides the prompt and names the key.
                # Zero and absent both mean "the binding rules": a console's
                # slider at "auto" and a call that never heard of the knob
                # must be the same call, and the same key.
                raw_reply = payload.get("reply_tokens") or None
                reply = (inference.clamp_reply_tokens(raw_reply)
                         if raw_reply is not None else None)
                # J.10.5: hops are opt-in and cost one model call each, so the
                # sweep stays the default. `hops: true` means "use the budget
                # you would have picked"; a number sets it.
                hops = payload.get("hops")
                budget = (6 if hops is True else int(hops)) if hops else None
                # J.10.3 (v0.67): the caller's own terms, on the sweep only.
                # Shape is the C.12 table's business (`string[]`, refused in
                # `harvest`'s own words); what belongs here is the one thing
                # the table cannot say — that a walk takes none. It authors
                # its retrieval from hop 1 (J.10.5), so accepting a list and
                # dropping it would be a lie about what ran, which is C.13
                # rule 4's judgement of a silently ignored window applied to
                # a silently ignored parameter.
                terms = payload.get("terms")
                if budget and terms is not None:
                    raise VineError(
                        E_SCHEMA,
                        "answer: 'terms' is not accepted with 'hops'",
                        hint="A walk authors its own retrieval from hop 1. "
                             "Drop 'hops' to hand the sweep your terms, or "
                             "drop 'terms' to let the walk search for itself.")
                # C.6c.4 rule 4: the history view — forwarded to the
                # retrieval that does the suppressing, and into the J.10.7
                # key, because it changes the reading. Deliberately NOT
                # refused beside `hops` the way `terms` is, and rule 5 is the
                # whole difference: navigation never suppresses, so a walk
                # already sees the replaced document at every hop. The flag
                # asks a walk for exactly what a walk already does, where
                # terms handed to a walk would be searched by nobody.
                superseded = bool(payload.get("include_superseded"))
                if budget:
                    served = consult_walk_store(
                        sample, forest, vine, policy, binding, payload,
                        question, k, budget, reply, window)
                    if served is None:
                        served = inference.forage(
                            scoped, question, binding, k=k, max_hops=budget,
                            reply_tokens=reply, window=window,
                            on_hop=lambda hop: publish(sample, "hop", hop))
                        whisper(vine, served.get("evidence")
                                if isinstance(served, dict) else None)
                    # J.10.8 (v0.54): the clamp is reported — a caller who
                    # asked for 40 learns it was served by the floor, 64.
                    if reply and isinstance(served, dict) and "error" not in served:
                        served.setdefault("reply_tokens", reply)
                    return served
                # The sweep's retrieval always runs — it is the cheap half,
                # and its reading is what decides the hit (J.10.7 v0.35).
                bundle = scoped.harvest(question, terms=terms, k=k,
                                        since=payload.get("since"),
                                        until=payload.get("until"),
                                        date_field=payload.get("date_field"),
                                        include_superseded=superseded)
                if isinstance(bundle, dict) and "error" in bundle:
                    return bundle
                # J.10.12: 19 ms in, against a reply 10 s out. The SAME
                # object the response carries as `harvest` (rule 2: an event
                # is a prefix of the answer, never a second rendering of it).
                publish(sample, "retrieval", bundle)
                # J.10.10 (v0.52): the floor, counted before the store is
                # consulted and before the provider is called — so a refusal
                # is never billed, never cached, and never a stored answer
                # served back under a question it was too thin to answer.
                floor = declined_for_evidence(payload, bundle, k)
                if floor is not None:
                    return floor
                served = serve_from_reading(
                    sample, forest, vine, policy, binding, payload,
                    question, k, bundle, reply, window, superseded)
                if served is None:
                    if sample is not None and sample.get("defer_model"):
                        # J.10.11 (v0.57): the provider is not a lane. The
                        # bundle, the binding and the question leave as
                        # values; the loop runs the model on no lane and
                        # settles back on this one. `inference.answer`
                        # handed a bundle touches no vine — the property
                        # this hand-off makes load-bearing.
                        sample.pop("defer_model", None)
                        return {"_deferred": {
                            "scoped": scoped, "question": question,
                            "binding": binding, "k": k, "bundle": bundle,
                            "reply": reply}}
                    served = inference.answer(scoped, question, binding, k=k,
                                              bundle=bundle,
                                              reply_tokens=reply)
                # The whisper closes the hunt either way (v0.35): a hit and
                # a miss heat identically, because the knowledge was used
                # identically. (A walk hit deposits its stored trail in
                # consult_walk_store instead.)
                whisper(vine, served.get("evidence")
                        if isinstance(served, dict) else None)
                # J.10.8 (v0.54): the clamp is reported.
                if reply and isinstance(served, dict) and "error" not in served:
                    served.setdefault("reply_tokens", reply)
                return served
            return inference.recurate(scoped, payload.get("id"), binding)
        except VineError as e:
            return e.to_dict()
        except Exception as e:  # provider outages must not 500 the Station
            return VineError(E_SCHEMA, f"{name} failed: {e}"[:300]).to_dict()

    def upload_source_url(entry: dict) -> str | None:
        """J.8 (v0.48): an upload entry MAY say where its bytes came from.

        `http`/`https` only and bounded at 2048 characters — anything else
        is `E_SCHEMA` naming the entry, because a provenance line that is
        a `javascript:` URL or an unbounded string is not an address, and
        the Gardener will append it to a body verbatim.
        """
        url = entry.get("source_url")
        if url is None:
            return None
        name = str(entry.get("name") or "").strip() or "<unnamed>"
        if not isinstance(url, str):
            raise VineError(E_SCHEMA,
                            f"'{name}': source_url must be a string")
        if not url.startswith(("http://", "https://")):
            raise VineError(
                E_SCHEMA, f"'{name}': source_url must be http:// or https://",
                hint="Provenance names an address a person can follow.")
        if len(url) > 2048:
            raise VineError(
                E_SCHEMA,
                f"'{name}': source_url is over 2048 characters")
        if any(ord(c) < 0x21 or ord(c) == 0x7F for c in url):
            # A raw space or control character is not legal in a URL — and
            # a newline here would let the client author arbitrary prose
            # (a fake heading, a second Source line) into a body the
            # server writes. The address is one token or it is refused.
            raise VineError(
                E_SCHEMA,
                f"'{name}': source_url must not contain spaces or "
                "control characters",
                hint="Percent-encode them (%20) if the address needs one.")
        return url

    def stage_upload(root: Path,
                     files: list) -> tuple[Path, list[str], dict[str, str], dict[str, dict]]:
        """Write uploaded documents into the forest's staging directory.

        Each name is resolved and then checked to still be *under* the
        staging root. Inspecting the string for `..` would miss symlinks and
        absolute paths; comparing the resolved paths cannot.

        An entry carries either `text` (UTF-8 source) or `b64` (the raw
        bytes). The Gardener's `.docx`/`.xlsx` converters read bytes, so a
        text-only upload path left them reachable from a shell and from
        nowhere else — the operator with only a browser is exactly who this
        surface exists for (J.8).

        Returns the provenance map alongside: staged rel name -> the
        entry's validated `source_url`, keyed exactly as the Gardener
        records `source_path`, so the map matches on adopt AND on the
        upload->sync flip. Validated for EVERY entry before the first byte
        lands — a bad third entry must not leave two staged files behind
        for the next batch's hash-diff to mistake for changed documents.

        And the passport map (J.8.4, v0.78): staged rel name -> the entry's
        validated `passport`, the scent the caller already knows for the
        node these bytes become. Same key, same rule — shape-checked for
        every entry before anything stages.
        """
        from monkeyllm_station.compose import validate_passport

        staging = root.joinpath(*UPLOAD_DIR)
        staging.mkdir(parents=True, exist_ok=True)
        staging_root = staging.resolve()
        validated: dict[int, dict] = {}
        for i, entry in enumerate(files):
            if isinstance(entry, dict):
                upload_source_url(entry)  # E_SCHEMA before anything stages
                if entry.get("passport") is not None:
                    validated[i] = validate_passport(
                        str(entry.get("name") or "?"), entry["passport"])
        written = []
        provenance: dict[str, str] = {}
        passports: dict[str, dict] = {}
        for i, entry in enumerate(files):
            if not isinstance(entry, dict):
                raise VineError(E_SCHEMA, "each file must be an object "
                                          "{name, text|b64, source_url?, passport?}")
            name = str(entry.get("name") or "").strip()
            if not name:
                raise VineError(E_SCHEMA, "each file needs a name")
            # An absolute name is refused rather than quietly re-read as
            # relative: stripping the slash would land the file somewhere safe
            # while hiding the caller's bug.
            if Path(name).is_absolute() or name.startswith(("/", "\\")):
                raise VineError(E_SCHEMA, f"file name must be relative: {name}")
            target = (staging / name).resolve()
            if not target.is_relative_to(staging.resolve()):
                raise VineError(E_SCHEMA, f"file name escapes the upload area: {name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry.get("b64") is not None:
                import base64
                import binascii

                try:
                    data = base64.b64decode(str(entry["b64"]), validate=True)
                except (binascii.Error, ValueError) as e:
                    # Writing the undecodable string as bytes would stage a
                    # file the converter then blames the document for.
                    raise VineError(E_SCHEMA,
                                    f"'{name}' is not valid base64: {e}") from None
                target.write_bytes(data)
            else:
                target.write_text(str(entry.get("text") or ""), encoding="utf-8")
            written.append(name)
            url = entry.get("source_url")
            if url:
                # Keyed by the path relative to the staging root the walk
                # will use — the exact string the Gardener writes into
                # `source_path` — not by the raw entry name, whose
                # separators the resolve may have normalised.
                provenance[target.relative_to(staging_root).as_posix()] = url
            if i in validated:
                passports[target.relative_to(staging_root).as_posix()] = validated[i]
        return staging, written, provenance, passports

    def run_ingest(principal, forest, vine, policy, _name, payload) -> dict:
        """The Gardener over REST (J.8), with the host's three additions:
        the `ingest` capability, a scope check on where it may write, and a
        staging area for operators who have a browser and no shell."""
        from monkeyllm.gardener import (Gardener, discover_hooks,
                                         normalize_dest)
        from monkeyllm_station import compose, inference

        if not policy.grants("ingest"):
            return VineError(E_FORBIDDEN, "ingest requires the 'ingest' capability",
                             hint=f"This principal holds: {sorted(policy.caps)}.").to_dict()
        if not writable:
            # Checked before anything is staged. The Gardener catches per-file
            # write failures and reports them as `errors`, so without this the
            # caller gets a list of identical "read-only" lines instead of the
            # one fact that matters: this deployment does not accept writes.
            return VineError(
                E_READONLY, "this Station serves read-only forests",
                hint="Start it with --writable to accept ingest and writes.").to_dict()

        mode = str(payload.get("mode") or "adopt")
        if mode not in ("adopt", "sync", "upload", "compose"):
            return VineError(E_SCHEMA, f"unknown ingest mode: {mode}",
                             hint="One of: adopt, sync, upload, compose.").to_dict()

        # The two phases of J.8.1. `stage` previews, `draft` accepts a
        # preview; the review itself is stateless, because the alternative is
        # server-side drafts with a lifetime, an owner and a garbage
        # collector, and every field has to be re-validated on the way back
        # regardless of who held it in the meantime.
        stage = bool(payload.get("stage"))
        approved = payload.get("draft")
        if approved is not None and not isinstance(approved, dict):
            return VineError(E_SCHEMA, "draft must be an object").to_dict()
        if stage and approved is not None:
            # Two intentions in one body; picking either would be guessing.
            return VineError(
                E_SCHEMA, "a request may stage or accept, not both",
                hint="Send stage:true to preview, then the returned draft to "
                     "accept it.").to_dict()
        if (stage or approved is not None) and mode != "compose":
            return VineError(
                E_SCHEMA, f"review is not available for mode '{mode}'",
                hint="adopt, sync and upload are batches; there is no single "
                     "draft to decide on. Use mode 'compose'.").to_dict()

        # J.9: batches answer with a job; compose answers in place. Decided
        # here, before compose rewrites itself into an upload.
        composed = mode == "compose"
        if mode == "compose":
            # Authored prose is a source like any other (J.8): it becomes one
            # staged document and then walks the whole pipeline — converter,
            # curation, closed-candidate edge proposals, commit. Planting it
            # directly would be a second write path with its own idea of what
            # a passport is, and nothing would keep the two honest.
            title = str(payload.get("title") or "").strip()
            text = str(payload.get("text") or "")
            if not title:
                return VineError(E_SCHEMA, "compose needs a title",
                                 hint="The title names the node and its file.").to_dict()
            if not text.strip():
                return VineError(E_SCHEMA, "compose needs text").to_dict()
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:63]
            if not slug:
                # A title of punctuation alone leaves nothing to name a file.
                return VineError(
                    E_SCHEMA, "the title has no letters or digits to name a file by",
                    hint="Titles become filenames, so they need something to slug.",
                ).to_dict()
            # The H1 is how every converter and the Curator learn the title;
            # a composer who already wrote one keeps theirs.
            document = text if text.lstrip().startswith("# ") else f"# {title}\n\n{text}"
            payload = {k: v for k, v in payload.items() if k not in ("path", "source")}
            payload["files"] = [{"name": f"{slug}.md", "text": document}]
            mode = "upload"

        # `dest` is a branch *path segment*: everything the Gardener writes
        # lands under `dest/`. So the prefix is what must be in scope — testing
        # the bare name would reject `projects` for a principal allowed
        # `projects/`, and testing nothing would let it write anywhere.
        # G.3 (v0.61): a branch is addressed by its id, and `dest` accepts
        # either spelling. Normalised HERE, before the scope test, so the
        # test and the write agree about which branch is meant — the bare
        # form was the only one accepted and the canonical one built
        # `x/_index/_index`, refused with an `expected_parent` naming the
        # exact string the caller had sent.
        dest = normalize_dest(payload.get("dest"))
        allowed_dests = [a.rstrip("/") for a in policy.allow if a]
        if dest and not policy.in_scope(f"{dest}/"):
            return VineError(E_FORBIDDEN, f"'{dest}' is outside this principal's scope",
                             hint="Ingest may only write where the principal can read.").to_dict()
        if not dest and not policy.unrestricted:
            return VineError(
                E_SCHEMA, "a scoped principal must say where the documents go",
                hint=f"Pass dest as one of: {allowed_dests}.").to_dict()
        if dest and not policy.unrestricted and not vine.forest.exists(f"{dest}/_index"):
            # A brand-new top-level dest would make the Gardener graft an entry
            # into the master index — a node this principal may not even read.
            return VineError(
                E_SCHEMA, f"'{dest}' is not an existing branch",
                hint="A scoped principal adopts into a branch that already "
                     "exists; creating one at the root touches the master index.",
            ).to_dict()

        # `path` means two different things and only one of them is a host
        # path. For `adopt` it names a directory on the Station's filesystem;
        # for `sync` it is a file *relative to* the source root a prior adopt
        # recorded, which G.8 contains. Reading them through one variable is
        # how a relative path ends up being measured against absolute roots.
        if mode == "sync":
            source = payload.get("source") or None
        else:
            source = payload.get("path") or payload.get("source") or None

        # Naming a host path spends the Station's filesystem authority, not the
        # caller's, so it needs 'admin' on top of 'ingest' — otherwise a content
        # capability would read anything the container can see. A targeted sync
        # keeps the same requirement here: J.8 exempts it, and being stricter
        # than the spec costs an operator one capability they already hold.
        if (source or payload.get("path")) and not policy.grants("admin"):
            return VineError(
                E_FORBIDDEN, "reading a host path requires the 'admin' capability",
                hint="Use mode 'upload' to send the documents themselves.").to_dict()
        # J.8.2: the capability answered who may ask; the roots answer what
        # exists to be asked for. Both, or the host's whole filesystem sits
        # one grant away — and in a self-hosted deployment the operator holds
        # that grant by construction.
        if source:
            denied = ingest_roots.check(source)
            if denied is not None:
                return denied.to_dict()

        root = Path(vine.forest.root)
        before = _git(root, "rev-parse", "HEAD")
        staged: list[str] = []
        if mode == "upload":
            files = payload.get("files")
            if not isinstance(files, list) or not files:
                return VineError(
                    E_SCHEMA, "upload needs a non-empty 'files' list",
                    hint='Each entry is {"name": "notes.md", "text": "…"} '
                         'or {"name": "report.docx", "b64": "…"}.').to_dict()

        # J.9: a batch claims its job before anything is staged. The refusal
        # has to come first — batches share one staging area per forest, and
        # a second upload must not overwrite files the running job is still
        # reading. A claim that fails validation below is abandoned, so the
        # caller who got an error never also got a job.
        job = None
        if not composed:
            job = board.claim(forest, mode, 0, principal)
            if job is None:
                running = board.running(forest)
                return VineError(
                    E_LOCKED,
                    "an ingest job is already running on this forest"
                    + (f": {running.id}" if running else ""),
                    hint="Watch it under GET /v1/forests/{forest}/jobs, "
                         "cancel it, or wait for it to finish.").to_dict()
        provenance: dict[str, str] = {}
        passports: dict[str, dict] = {}
        gate = None
        try:
            if mode == "upload":
                source, staged, provenance, passports = stage_upload(root, payload["files"])

            curator = inference.curator_from_binding(
                vine, policy, registry.binding(forest, "ingest"))
            # G.5.1: the describer is the host's half of the media story —
            # a forest with a `vision` binding reads its images at ingest,
            # once; without one the engine's stub still plants `media`,
            # never `unsupported`. The Gardener ranks `extra_converters`
            # after the operator's command hooks, so a configured `.png`
            # hook keeps winning, and a describer that raises falls back
            # down the chain to the stub (G.4.3 reaching conversion).
            describer = vision.image_converter(registry.binding(forest, "vision"))
            # Accepting a reviewed draft replaces the model's curation with
            # the reviewer's, as an ordinary `on_curate` hook (J.8.1). The
            # Curator object is still built — `rollup` below is a different
            # write about a different node — but it does not curate this one
            # again: it would answer differently, and what shipped would then
            # not be what was approved.
            hooks = discover_hooks()
            if approved is not None:
                hooks.append(compose.approval_hook(approved, vine, policy))
            elif passports:
                # J.8.4: an entry that came with its passport is never shown
                # to the curation model — the caller declared knowing more
                # than a model would guess — while the rest of the batch
                # keeps the bound curator. One gate, decided per draft.
                gate = compose.passport_gate(passports, vine, policy, curator)
                hooks.append(gate)
            elif curator is not None:
                hooks.append(curator)
            # G.10.1: the Gardener names the phase it is in and the job
            # carries it. This is called from the forest lane mid-step and
            # suspends nothing — a step is still a whole document — but it
            # is what lets a batch of ONE large file show movement instead
            # of standing at 0/1 for a minute, which reads as a hang.
            watched = job
            # The provenance map rides the ONE Gardener construction, so it
            # reaches the adopt path and the upload->sync flip below alike —
            # that flip is why this is a map and not a curation hook: a
            # refresh re-converts the body, and curation never runs on
            # refreshes (J.8 v0.48).
            gardener = Gardener(
                vine, hooks=hooks, dry_run=stage,
                extra_converters=([describer] if describer else None),
                provenance=(provenance or None),
                on_stage=(None if watched is None
                          else lambda f, st: board.note_stage(watched, f, st)))

            if mode == "upload":
                # J.8 (v0.61): ONE path for every upload, first or hundredth.
                #
                # It used to be `adopt` the first time and a full refresh of
                # the staging DIRECTORY thereafter, and both halves were
                # wrong. `adopt` records its source as the forest's mirror
                # root — so one upload repointed a forest that really did
                # mirror `/data/handbook` at the upload staging area, and the
                # operator's Sync button then offered to re-read the courier.
                # And the refresh walked the whole directory, so every file
                # any previous batch had ever uploaded was re-examined on
                # every upload: one whose node had since been pruned had no
                # passport to diff against, was read as new, and was planted
                # again — a removal that undid itself on somebody else's
                # next upload.
                #
                # The scoped refresh does both jobs correctly by itself: an
                # entry with no passport is planted, an entry with one is
                # refreshed, and nothing else in the directory is touched or
                # even looked at. Nothing is recorded: an upload is bytes
                # arriving, not a folder this forest mirrors, and `consume`
                # says the bytes may go once they are a node.
                steps = gardener.sync_iter(source, dest=dest, paths=staged,
                                           consume=True)
            elif mode == "sync":
                # A targeted path here is relative to the source root a prior
                # adopt recorded — vetted then, and contained by G.8 now.
                if source is None:
                    # The recorded root was inside the roots when it was
                    # adopted; it need not be inside them today. Re-checking
                    # is what makes narrowing the list take effect on the
                    # forests that were already pointed somewhere. A forest
                    # with nothing recorded falls through to the Gardener,
                    # which refuses it as E_SCHEMA rather than inventing a
                    # directory (G.3).
                    recorded = str(gardener.config.get("source_root") or "").strip()
                    if recorded:
                        denied = ingest_roots.check(recorded)
                        if denied is not None:
                            raise denied
                steps = gardener.sync_iter(source, path=payload.get("path"))
            else:
                steps = gardener.adopt_iter(source, dest=dest)

            if not composed:
                # Accepted (J.9): iterator construction was the eager half —
                # source resolved, walk done, total known — so the response
                # is the job and the report arrives on it. The driver on the
                # event loop steps the iterator from here; the audit row
                # waits for the finish.
                job.mode, job.total = mode, steps.total
                return {"_prepared": PreparedIngest(
                    job=job, steps=steps, gardener=gardener, curator=curator,
                    mode=mode, staged=staged, root=root,
                    before=before or None, principal=principal, forest=forest,
                    payload=payload, passports=passports, gate=gate)}

            # compose answers in place (J.9): one document, and the J.8.1
            # review is a conversation, not a batch.
            for _ in steps:
                pass
            report = steps.result
            rollup = gardener.rollup(curator) if (curator and not stage) else None
        except VineError as e:
            if job is not None:
                board.abandon(job)
            return e.to_dict()
        except Exception as e:
            if job is not None:
                board.abandon(job)
            return VineError(E_SCHEMA, f"ingest failed: {e}"[:300]).to_dict()

        after = _git(root, "rev-parse", "HEAD")
        # `curated` is what the model DID, not what the operator configured.
        # Reading it off the binding made a dead endpoint indistinguishable
        # from a working one: the Curator falls back silently by design (G.4
        # rule 6), so every document still planted, with derived summaries,
        # under a report that said the model wrote them.
        stats = dict(curator.stats) if curator else None
        if stats and curator.last_error:
            stats["error"] = curator.last_error
        if stats and curator.last_reject:
            # A model that answers and is rejected every time looks exactly
            # like one that never answered — same fallback, same output. The
            # fixes are opposite, so the report has to separate them.
            stats["rejected_because"] = curator.last_reject
            stats["last_reply"] = curator.last_reply or ""
        written = bool(stats and (stats["llm_summaries"] or stats["branch_rollups"]))
        if stage:
            # Ids alone would make the reviewer open another console to find
            # out what they are agreeing to (J.8.1).
            report["drafts"] = compose.review_of(vine, policy, report["drafts"])
        else:
            report.pop("drafts", None)  # an ordinary ingest has none
        return {
            **report, "mode": mode, "staged": staged,
            **({"preview": True} if stage else {}),
            "rollup": rollup,
            # A batch is many commits; the Station reports the range instead of
            # amending the last one and claiming the whole ingest (J.8). A
            # preview produced none, and reporting HEAD unchanged as `commit`
            # would put a sha in the audit log for a call that wrote nothing.
            "commit": None if stage else (after or None),
            "commit_before": before or None,
            "curated": written, "bound": curator is not None, "curation": stats,
        }

    def run_ingest_status(principal: str, forest: str,
                          caps_mask: frozenset[str] | None = None):
        """What a refresh would re-read, before anyone asks for one (J.8).

        `sync` is the one ingest call whose reach comes from configuration
        rather than from the request, so it is the one the operator cannot
        see. A console that offers it without this is offering a button
        whose scope is invisible — which is how v0.25 shipped, and how a
        forest ingested the Station's own source tree.
        """
        from monkeyllm.gardener import Gardener

        policy = registry.policy_for(principal, forest)
        if policy is None:
            return None
        policy = policy.masked(caps_mask)
        if not policy.grants("ingest"):
            return VineError(E_FORBIDDEN, "ingest requires the 'ingest' capability",
                             hint=f"This principal holds: {sorted(policy.caps)}."
                             ).to_dict()
        try:
            vine = pool.get(forest)
        except VineError as e:
            return e.to_dict()   # see run_primitive: not an existence question
        # Built fresh rather than read off a cached Forest attribute: an
        # adopt that just recorded a root must be visible to the next call,
        # and this is the same loader the Gardener itself uses.
        recorded = str(Gardener(vine, hooks=[]).config.get("source_root") or "").strip()
        return {
            "source": recorded or None,
            # Both halves matter and they fail for different reasons: no
            # source at all, or a source this Station may no longer read
            # because the roots were narrowed under it.
            "can_sync": bool(recorded) and ingest_roots.check(recorded) is None,
            # Whether "mirror a host folder" is worth offering at all.
            "host_paths": bool(ingest_roots.roots),
        }

    # -- map projections (J.11) ---------------------------------------------

    def run_map(principal: str, forest: str, kind: str, params: dict,
                caps_mask: frozenset[str] | None = None, get_vine=None):
        """A whole region in one payload, under the caller's own policy.

        Executed on the forest thread like every other forest touch — a
        reader lane's when the pool has one (J.6.2): the graph is the
        console's first read of a forest, and it was the read the incident
        measured waiting behind a plant. This is
        not a primitive and grants nothing new: every id it returns is one
        the same principal could reach through `look`, and the filtering is
        `policy.in_scope` — the same predicate `ScopedVine` applies node by
        node (J.3). What it adds is shape, which a per-node walk cannot give
        without asking once per node.
        """
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return None
        policy = policy.masked(caps_mask)
        if not policy.grants("read"):
            return VineError(
                E_FORBIDDEN, f"'{kind}' requires the 'read' capability",
                hint=f"This principal holds: {sorted(policy.caps)}.").to_dict()
        try:
            vine = get_vine() if get_vine is not None else pool.get(forest)
        except VineError as e:
            return e.to_dict()   # see run_primitive: not an existence question

        try:
            limit = max(1, min(int(params.get("limit") or MAP_LIMIT), MAP_MAX))
        except (TypeError, ValueError):
            return VineError(E_SCHEMA, "limit must be a number").to_dict()

        # A branch id (`projects/_index`) and the bare branch (`projects`)
        # both name the same region; the operator picked it from a tree that
        # shows the first and reads like the second.
        branch = str(params.get("scope") or "").strip().strip("/")
        if branch.endswith("/_index"):
            branch = branch[: -len("/_index")]
        if branch in ("", "_index"):
            branch = ""
        elif not policy.in_scope(f"{branch}/_index"):
            # Out of scope is absent, exactly as everywhere else (J.3).
            return VineError(E_NOT_FOUND, f"node not found: {branch}/_index",
                             hint="Use locate() to find entry points.").to_dict()

        def in_region(node_id: str) -> bool:
            if branch and not (node_id == f"{branch}/_index"
                               or node_id.startswith(f"{branch}/")):
                return False
            return policy.in_scope(node_id)

        heat = vine.trails.heat_all()
        try:
            if kind == "trails":
                return _trails_payload(vine, in_region, heat, limit)
            return _graph_payload(vine, in_region, heat, limit)
        except VineError as e:
            return e.to_dict()

    def _trails_payload(vine, in_region, heat: dict, limit: int) -> dict:
        """Persistent heat, for nodes that exist and are visible.

        A row in `trails.db` for a node the caller may not see would be an
        existence oracle with a number attached, and `stats` computed over
        the whole forest would be the same disclosure in aggregate — so both
        are derived from what survived.
        """
        known = {r[0] for r in vine.catalog.conn.execute("SELECT id FROM nodes")}
        warm = sorted(
            ({"id": nid, "heat": value} for nid, value in heat.items()
             if nid in known and in_region(nid)),
            key=lambda row: (-row["heat"], row["id"]),
        )
        shown = warm[:limit]
        values = [row["heat"] for row in shown]
        return {
            "heat": shown,
            "stats": {
                "rows": len(shown),
                "max": round(max(values), 4) if values else 0.0,
                "mean": round(sum(values) / len(values), 4) if values else 0.0,
            },
            "truncated": len(warm) > limit,
            "derived": True,
        }

    def _graph_payload(vine, in_region, heat: dict, limit: int) -> dict:
        """Nodes and trails as a graph.

        Two rules from J.11 shape the order of what follows. An edge needs
        BOTH ends visible, because one visible end discloses the other. And
        `degree` is recomputed from the edges that survived — the Catalog's
        own degree counted the hidden ones, and publishing it would leak the
        size of what was withheld.
        """
        conn = vine.catalog.conn
        rows = [
            row for row in conn.execute(
                "SELECT id, kind, type, title, summary, tags, parent, coverage, "
                "body_tokens, payload, payload_type, created, updated "
                "FROM nodes ORDER BY id")
            if in_region(row["id"])
        ]
        edges_all = [
            e for e in conn.execute("SELECT src, rel, dst, confidence FROM edges")
            if in_region(e["src"]) and in_region(e["dst"])
        ]

        keep = {row["id"] for row in rows}
        truncated = len(rows) > limit
        if truncated:
            # Over the bound, the most connected nodes are the ones a map is
            # for. Ranked over the in-scope edge set, so the choice cannot be
            # steered by edges the caller may not see.
            ranked: dict[str, int] = {}
            for e in edges_all:
                ranked[e["src"]] = ranked.get(e["src"], 0) + 1
                ranked[e["dst"]] = ranked.get(e["dst"], 0) + 1
            rows.sort(key=lambda row: (-ranked.get(row["id"], 0), row["id"]))
            rows = rows[:limit]
            keep = {row["id"] for row in rows}
            rows.sort(key=lambda row: row["id"])

        edges = [
            {"src": e["src"], "rel": e["rel"], "dst": e["dst"],
             "confidence": round(float(e["confidence"] or 1.0), 3)}
            for e in edges_all if e["src"] in keep and e["dst"] in keep
        ]
        degree: dict[str, int] = {}
        for e in edges:
            degree[e["src"]] = degree.get(e["src"], 0) + 1
            degree[e["dst"]] = degree.get(e["dst"], 0) + 1

        nodes = []
        for row in rows:
            try:
                tags = json.loads(row["tags"] or "[]")
            except json.JSONDecodeError:
                tags = []
            nodes.append({
                "id": row["id"], "kind": row["kind"], "type": row["type"],
                "title": row["title"], "summary": row["summary"], "tags": tags,
                "parent": row["parent"] if row["parent"] in keep else None,
                "coverage": row["coverage"], "body_tokens": row["body_tokens"],
                "payload": row["payload"], "payload_type": row["payload_type"],
                # Passport dates, day precision (J.11 v0.38): `created` is
                # what lets a console replay the forest as it grew.
                "created": row["created"], "updated": row["updated"],
                # `nodes.stale` is deliberately NOT here. In the engine it
                # means "this node's vector needs re-embedding after a write"
                # (Part K bookkeeping), not "this node is unhealthy" — and a
                # field of that name on a map would be read as the second by
                # everyone who has not read the Catalog.
                "degree": degree.get(row["id"], 0),
                "heat": heat.get(row["id"], 0.0),
            })

        return {
            "nodes": nodes, "edges": edges, "truncated": truncated,
            # The dialect the forest declares, so a legend names what this
            # forest actually holds instead of a list compiled into a console.
            "types": sorted(vine.forest.dialect.node_types),
            "rels": sorted(vine.forest.dialect.rels),
            # C.6.1: the Catalog is derived and rebuildable. A consumer that
            # finds it stale reindexes; it never reconciles.
            "derived": True,
        }

    # -- routes -------------------------------------------------------------

    def setup_open() -> bool:
        """J.2.4: one door at a time. A deployment that declared an
        environment super-admin has already chosen its first identity, so the
        setup route does not exist there — the two must never race for it."""
        return super_admin is None and registry.setup_available()

    # J.1.1 rule 3 (v0.52): whether the MCP surface is mounted at all is
    # decided further down, when the routes are built — health closes over
    # the holder so the answer is the deployment's, not a guess.
    mcp_state = {"enabled": False}

    def mcp_status(request: Request) -> dict:
        """What MCP would say to THIS request's Host.

        The operator curls the domain they published and reads the verdict
        for that domain, in the document they were already looking at. The
        allow-list is never listed: the only host named is the one the
        caller sent.
        """
        if not mcp_state["enabled"]:
            return {"enabled": False}
        from monkeyllm_station.mcp_surface import host_allowed

        out: dict = {"enabled": True}
        verdict = host_allowed(request.headers.get("host"))
        if verdict is not None:
            out["host_allowed"] = verdict
        return out

    async def health(request: Request) -> JSONResponse:
        # `password_login` lets the console decide whether to offer the door
        # at all. It reveals that a door exists, not who may walk through it.
        # `setup_required` is the same kind of fact: which of the two
        # pre-identity screens the console must render (J.5.6). Deciding that
        # locally is how a console ends up offering a sign-in form on a
        # Station nobody can sign in to.
        from monkeyllm_station.mcp_surface import package_version

        # J.1.3 (v0.55): the door tells the truth about the rooms. Counts,
        # never ids — health is unauthenticated and forest ids are J.3's to
        # disclose. `locked` counts live foreign writers only: an orphan
        # lock heals at the next open (C.9) and is not an outage.
        listing = pool.list()["forests"]
        locked = sum(1 for f in listing if f.get("locked"))
        return JSONResponse({
            "status": "degraded" if locked else "ok",
            "mode": pool.mode, "writable": writable,
            # J.1.2 rule 3 (v0.54): which build answered — the same number
            # the MCP handshake states, in the place an operator curls.
            "version": package_version(),
            "forests": {"served": len(listing) - locked, "locked": locked},
            "setup_required": setup_open(),
            "password_login": super_admin is not None or registry.has_any_password(),
            "mcp": mcp_status(request),
            # J.10.11 (v0.57): the deployment states its shape — the team
            # discovered every ceiling by experiment and asked for this.
            # Counts of capacity, never per-forest data: health stays the
            # unauthenticated surface it is.
            "concurrency": {"readers": readers.size, "model": model_slots},
        })

    def effective_grants(principal: str,
                         mask: frozenset[str] | None = None) -> list[dict]:
        """The principal's grants as policy resolves them.

        For everyone this is the grant table. For the owner (J.2.4) there is
        no grant table to read — the authority is a bit — so the forests the
        pool currently holds are projected as full-capability grants. Both
        `/v1/me` and `/v1/forests` read from here, because a console that saw
        an owner with zero forests would render an empty product for the one
        principal who may do everything.

        A masked key is reported the MASKED caps (J.2.6): what a console
        renders from here is what the key can actually do, or every
        disabled button becomes a support ticket.
        """
        if not registry.is_owner(principal):
            grants = registry.grants_of(principal)
        else:
            grants = [{"forest": f["id"], "caps": sorted(CAPS), "allow": [""],
                       "deny": [], "tables": {}}
                      for f in pool.list()["forests"]]
        if mask is not None:
            grants = [{**g, "caps": sorted(set(g["caps"]) & mask)}
                      for g in grants]
        return grants

    async def me(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        mask = mask_of(request)
        grants = effective_grants(principal, mask)
        for g in grants:
            policy = registry.policy_for(principal, g["forest"])
            g["roots"] = policy.roots() if policy else []
        return JSONResponse({"principal": principal, "grants": grants,
                             "admin": is_admin(principal, mask=mask),
                             # The owner bit is masked with `admin` (J.2.6):
                             # a pair key held by the owner is refused every
                             # owner door, so reporting the bit would render
                             # buttons the key cannot press.
                             "owner": registry.is_owner(principal)
                             and (mask is None or "admin" in mask)})

    async def forests(request: Request) -> JSONResponse:
        from monkeyllm_station.mcp_surface import package_version

        principal, err = require_principal(request)
        if err:
            return err
        granted = {g["forest"]: g
                   for g in effective_grants(principal, mask_of(request))}
        listed = []
        for f in pool.list()["forests"]:
            if f["id"] not in granted:
                continue
            policy = registry.policy_for(principal, f["id"])
            listed.append({**f, "caps": granted[f["id"]]["caps"],
                           "roots": policy.roots() if policy else []})
        # J.1.2 rule 6 (v0.56): the first reply states the version — same
        # string as MCP's forests() and serverInfo.version.
        return JSONResponse({"forests": listed, "mode": pool.mode,
                             "station": package_version()})

    # -- credentials (J.2.1 / J.2.2) ----------------------------------------

    def administers_fully(principal: str, target: str) -> bool:
        """May `principal` mint or revoke credentials for `target`?

        A key authenticates a principal, and a principal may hold grants on
        several forests — so issuing one needs `admin` on EVERY forest the
        target is granted, not merely on one of them. Otherwise the
        administrator of one forest could mint a credential that opens
        another (J.2.2).
        """
        # The owner administers every forest, so the subset test is trivially
        # true — and stays true for a target holding forests that do not exist
        # yet, which `mine` could not express.
        if registry.is_owner(principal):
            return True
        # The owner's authority is a bit on the principal, not a row in
        # `grants` (J.2.4), so a rule that reasons about grants has to name the
        # owner in its own right rather than infer them: only the owner
        # administers the owner.
        if registry.is_owner(target):
            return False
        theirs = {g["forest"] for g in registry.grants_of(target)}
        mine = {g["forest"] for g in registry.grants_of(principal)
                if "admin" in g["caps"]}
        # Sharing no forest with someone is not the same as administering
        # every forest they hold, and the subset test below cannot tell those
        # two apart on its own. Onboarding is unaffected: J.2.3 applies the
        # grant before the password and the key, in that order and for this
        # reason.
        if not theirs:
            return False
        return bool(mine) and theirs <= mine

    async def auth_setup(request: Request) -> JSONResponse:
        """J.2.4: the one unauthenticated route, open until it is used once.

        It is unauthenticated because there is nobody to authenticate, and
        that is only safe under one condition: the registry holds no
        credential at all, so there is no privilege here to escalate from.
        The moment it succeeds the condition is false and the route is gone.

        A closed route answers exactly as an unrouted path does. "Already
        configured" would publish the deployment's state to anyone who asks,
        and the answer to "is this Station up for grabs?" is not public.
        """
        if not setup_open():
            return _no_such_endpoint("/auth/setup")
        try:
            body = _json_object(await request.json())
        except json.JSONDecodeError:
            return _envelope(VineError(E_SCHEMA, "invalid JSON body"))
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if not username or not password:
            return _envelope(VineError(
                E_SCHEMA, "username and password are required",
                hint="The owner is an ordinary principal that carries a bit."))
        if len(password) < MIN_OWNER_PASSWORD:
            # The one credential that governs everything should not be able to
            # be three characters long because nobody said otherwise.
            return _envelope(VineError(
                E_SCHEMA, f"password must be at least {MIN_OWNER_PASSWORD} "
                          "characters"))

        # Racing callers both arrive here; exactly one wins inside the
        # transaction, and the loser is told the door closed — which by then
        # is simply true.
        if not registry.create_owner(username, password,
                                     str(body.get("email") or "") or None):
            return _no_such_endpoint("/auth/setup")

        session = registry.open_session(username)
        record_governance(username, "auth.setup", {"username": username}, "ok")
        return JSONResponse({"key": session["key"], "principal": username,
                             "expires_at": session["expires_at"],
                             "admin": True, "owner": True})

    # One limiter for both password doors (J.2.6): the window is keyed by
    # (username, client host), so hammering `pair` spends the same budget as
    # hammering `login` — they verify the same password.
    auth_window = AuthWindow()

    def verify_login(username: str, password: str) -> bool:
        """The ONE password check both doors run (J.2.1 / J.2.6): the
        environment super-admin compare included, and False alike for a
        wrong password, an unknown user and a user with no password."""
        if not username or not password:
            return False
        if super_admin and secrets.compare_digest(username, super_admin[0]):
            # Break-glass: compared against the environment, never stored.
            return secrets.compare_digest(password, super_admin[1])
        return registry.verify_password(username, password)

    async def auth_login(request: Request) -> JSONResponse:
        """Password in, session token out (J.2.1).

        The session is an ordinary API key with a short life, so everything
        downstream — authenticate, policy, audit — is the single path it
        already was. The door decides how the principal was established,
        never what it may do.
        """
        try:
            body = _json_object(await request.json())
        except json.JSONDecodeError:
            return _envelope(VineError(E_SCHEMA, "invalid JSON body"))
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        host = request.client.host if request.client else ""
        # Before the password is verified (J.2.6): past the limit, the
        # answer costs nothing and says nothing about who exists.
        if auth_window.over_limit(username, host):
            return _too_many_attempts()

        if not verify_login(username, password):
            auth_window.failed(username, host)
            # Recorded, because "was anyone trying yesterday?" has no other
            # answer: the limiter counts in memory and forgets on restart.
            # The attempted username is stored as given — it is what was
            # tried, which is the fact worth keeping.
            record_governance(username or "-", "auth.login",
                              {"username": username, "host": host}, "refused")
            hooks.emit(webhooks.DEPLOYMENT, "auth.login.failed",
                       username or "-", {"username": username, "host": host})
            # One message for a wrong password, an unknown user and a user
            # with no password at all: distinguishing them would turn the
            # login form into a directory of who exists.
            return _envelope(VineError(E_FORBIDDEN, "invalid username or password"), 401)
        auth_window.clear(username, host)

        session = registry.open_session(username)
        record_governance(username, "auth.login",
                          {"username": username, "host": host}, "ok")
        hooks.emit(webhooks.DEPLOYMENT, "auth.login.succeeded", username,
                   {"username": username, "host": host})
        return JSONResponse({"key": session["key"], "principal": username,
                             "expires_at": session["expires_at"],
                             "admin": is_admin(username),
                             "owner": registry.is_owner(username)})

    async def auth_pair(request: Request) -> JSONResponse:
        """The third door (J.2.6): a key that narrows.

        Unauthenticated like `login`, self-service by construction: pairing
        reaches nothing the password could not already reach — refusing it
        would only route the same authority through a wider credential. The
        minted key is an ordinary J.2.2 key whose row carries a capability
        mask; the mask is intersected with the live grants at the moment of
        use, so it never adds a capability and never outlives a revocation.
        """
        try:
            body = _json_object(await request.json())
        except json.JSONDecodeError:
            return _envelope(VineError(E_SCHEMA, "invalid JSON body"))
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        host = request.client.host if request.client else ""
        if auth_window.over_limit(username, host):
            return _too_many_attempts()

        if not verify_login(username, password):
            auth_window.failed(username, host)
            record_governance(username or "-", "auth.pair",
                              {"username": username, "host": host}, "refused")
            # Same single message as `login`, verbatim (J.2.6).
            return _envelope(VineError(E_FORBIDDEN, "invalid username or password"), 401)
        auth_window.clear(username, host)

        raw_caps = body.get("caps")
        if raw_caps in (None, []):
            caps = set(PAIR_CAPS)
        elif not isinstance(raw_caps, list):
            return _envelope(VineError(E_SCHEMA, "caps must be a list"))
        else:
            caps = {str(c) for c in raw_caps}
            if not caps <= PAIR_CAPS:
                return _envelope(VineError(
                    E_SCHEMA,
                    f"pair caps must be within {sorted(PAIR_CAPS)}",
                    hint="write, tend, query and admin stay what People "
                         "and `station key` mint, deliberately."))

        raw_days = body.get("expires_in_days")
        if raw_days in (None, "", 0):
            # Absent or zero means the default, never "unlimited" (J.2.6).
            days = PAIR_DEFAULT_DAYS
        else:
            try:
                days = float(raw_days)
            except (TypeError, ValueError):
                return _envelope(VineError(
                    E_SCHEMA, "expires_in_days must be a number"))
            if not math.isfinite(days):
                # NaN compares False against both bounds below, so without
                # this it would sail through validation and blow up inside
                # timedelta — a 500 where the caller earned a 400.
                return _envelope(VineError(
                    E_SCHEMA, "expires_in_days must be a number"))
            if days <= 0:
                return _envelope(VineError(
                    E_SCHEMA, "expires_in_days must be positive"))
            if days > PAIR_MAX_DAYS:
                # Stated, not silently clamped: a caller who asked for two
                # years should learn the ceiling, not discover it in 365
                # days.
                return _envelope(VineError(
                    E_SCHEMA,
                    f"expires_in_days must be at most {PAIR_MAX_DAYS:g}"))

        key = registry.issue_key(
            username, label=str(body.get("label") or "").strip() or "clipper",
            expires_in_days=days, kind="api", caps=caps)
        # A pair key is self-service, so nobody else witnesses it being made.
        # The row is how it can be accounted for later.
        record_governance(username, "auth.pair",
                          {"username": username, "caps": ",".join(sorted(caps)),
                           "prefix": key[:9], "expires_in_days": days}, "ok")
        # The prefix, never the key (J.4.1 rule 1). A webhook body is read
        # by whoever holds its URL, so the rule is stricter here, not looser.
        hooks.emit(webhooks.DEPLOYMENT, "pair.issued", username,
                   {"principal": username, "caps": sorted(caps),
                    "prefix": key[:9], "expires_in_days": days})
        # Second-resolution, like `open_session`'s reply: the row's own
        # timestamp may differ by the second the mint took.
        expires_at = (datetime.now(timezone.utc)
                      + timedelta(days=days)).isoformat(timespec="seconds")
        return JSONResponse({"api_key": key, "principal": username,
                             "caps": sorted(caps), "expires_at": expires_at})

    async def admin_keys(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        if not is_admin(principal, mask=mask_of(request)):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)

        if request.method == "GET":
            # Only principals this caller fully administers — the same rule
            # that governs issuing, applied to seeing (J.2.2).
            visible = [p["id"] for p in registry.principals()
                       if administers_fully(principal, p["id"])]
            return JSONResponse({"keys": registry.keys_of(visible),
                                 "principals": visible})

        body = _json_object(await request.json())
        if body.get("revoke"):
            # Authorize BEFORE the effect. Revoking first and checking after
            # would answer 403 while the token was already dead — a refusal
            # that refuses nothing.
            owner = registry.owner_of_key(str(body["revoke"]))
            if owner is None:
                return _envelope(VineError(E_NOT_FOUND, "no such token"))
            if not administers_fully(principal, owner):
                return _envelope(VineError(
                    E_FORBIDDEN, f"'{owner}' holds forests you do not administer"), 403)
            registry.revoke_key(str(body["revoke"]))
            record_governance(principal, "admin.key.revoke",
                              {"target": owner, "key": str(body["revoke"])}, "ok")
            hooks.emit(webhooks.DEPLOYMENT, "key.revoked", principal,
                       {"principal": owner, "key": str(body["revoke"])})
            return JSONResponse({"revoked": body["revoke"], "principal": owner})

        target = str(body.get("principal") or "").strip()
        if not target:
            return _envelope(VineError(E_SCHEMA, "principal is required"))
        if not administers_fully(principal, target):
            return _envelope(VineError(
                E_FORBIDDEN, f"'{target}' holds forests you do not administer",
                hint="Minting a key for a principal needs 'admin' on every "
                     "forest it is granted, or the key would reach further "
                     "than you can."), 403)
        try:
            days = body.get("expires_in_days")
            days = float(days) if days not in (None, "", 0) else None
        except (TypeError, ValueError):
            return _envelope(VineError(E_SCHEMA, "expires_in_days must be a number"))
        key = registry.issue_key(target, label=body.get("label") or None,
                                 expires_in_days=days)
        # The key itself never enters the log — the prefix is the identifier
        # meant for naming one out loud.
        record_governance(principal, "admin.key.issue",
                          {"target": target, "label": body.get("label") or "",
                           "prefix": key[:9], "expires_in_days": days}, "ok")
        hooks.emit(webhooks.DEPLOYMENT, "key.issued", principal,
                   {"principal": target, "label": body.get("label") or "",
                    "prefix": key[:9], "expires_in_days": days})
        return JSONResponse({"api_key": key, "principal": target,
                             "keys": registry.keys_of([target])})

    async def admin_password(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        # J.2.6: this route's gate is `administers_fully` below, which reads
        # the requester's grants unmasked (it also serves questions about
        # OTHER principals) — so the mask is honoured here, at the door.
        mask = mask_of(request)
        if mask is not None and "admin" not in mask:
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)
        body = _json_object(await request.json())
        target = str(body.get("principal") or "").strip()
        if not target or not administers_fully(principal, target):
            return _envelope(VineError(
                E_FORBIDDEN, "requires 'admin' on every forest that principal holds"), 403)
        if super_admin and target == super_admin[0]:
            return _envelope(VineError(
                E_FORBIDDEN, "the environment account has no stored password",
                hint="Rotate MONKEYLLM_STATION_PASSWORD and restart."), 403)
        registry.set_password(target, body.get("password") or None)
        # That a password was set, never the password and never its hash.
        record_governance(principal, "admin.password",
                          {"target": target,
                           "cleared": not body.get("password")}, "ok")
        return JSONResponse({"principal": target,
                             "has_password": registry.has_password(target)})

    async def admin_canopy(request: Request) -> JSONResponse:
        """Index health and rebuild (Part K).

        Building is offline work by design — it re-embeds every summary — so
        it runs on the forest thread like every other forest touch, and the
        caller waits. A fire-and-forget build would leave the console unable
        to say whether the index it is about to rely on exists.
        """
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.query_params.get("forest")
        body = _json_object(await request.json() if request.method == "POST" else {})
        if not forest:
            forest = body.get("forest")
        if not is_admin(principal, forest, mask=mask_of(request)):
            return _envelope(VineError(E_FORBIDDEN, "requires 'admin' on that forest"), 403)

        def work():
            try:
                vine = pool.get(forest)
            except VineError:
                return None
            attach_embedder(vine, forest)
            if request.method == "POST" and "enabled" in body:
                registry.set_setting(forest, "gauntlet", bool(body["enabled"]))
                attach_embedder(vine, forest)
                return {**vine.canopy_status,
                        "enabled": registry.setting(forest, "gauntlet", True)}
            if request.method == "POST":
                if vine.embedder is None:
                    return {"error": VineError(
                        E_SCHEMA, "no embedding model is bound to this forest",
                        hint="Bind one under Models, then build the index.").to_dict()["error"]}
                # J.13.4: refresh embeds what changed, build embeds
                # everything. They are not interchangeable — a model change
                # requires the build, because a partial re-embed would leave
                # the index in two spaces at once (K.4).
                if body.get("refresh"):
                    try:
                        return {**vine.refresh_canopy(),
                                "enabled": registry.setting(forest, "gauntlet", True)}
                    except VineError as e:
                        return e.to_dict()
                vine.build_canopy()
            return {**vine.canopy_status,
                    "enabled": registry.setting(forest, "gauntlet", True)}

        status = await in_forest_thread(forest, work)
        if status is None:
            return _unknown_forest(forest)
        if "error" in status:
            return JSONResponse(status, status_code=400)
        if request.method == "POST":
            # J.6.2: reader vines hold the canopy they loaded at open; a
            # rebuilt index reaches them by reopening, not by luck.
            readers.reset(forest)
            hooks.emit(forest, "canopy.built", principal,
                       {"embedded": status.get("embedded"),
                        "nodes": status.get("nodes"),
                        "stale": status.get("stale"),
                        "model": status.get("model"),
                        "refresh": bool(body.get("refresh"))})
        return JSONResponse(status)

    async def admin_people(request: Request) -> JSONResponse:
        """Governance shaped like a person, not like the tables (J.2.3).

        Grants, passwords and keys are three tables and one thought: nobody
        administers a grant, they onboard somebody. This endpoint applies
        any combination of those changes in one call so the console can ask
        once.

        It is a composite, never a new authority: every step re-checks the
        rule that already governed it, and a step the caller may not perform
        is refused *without abandoning the steps they may*. Silently
        dropping half a submitted form is worse than doing it or failing it.
        """
        principal, err = require_principal(request)
        if err:
            return err
        if not is_admin(principal, mask=mask_of(request)):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)
        mine = administered(principal)

        if request.method == "GET":
            people = []
            for p in registry.principals():
                grants = [g for g in registry.grants_of(p["id"]) if g["forest"] in mine]
                if not grants:
                    continue
                tokens = registry.keys_of([p["id"]])
                seen = [t["last_used_at"] for t in tokens if t["last_used_at"]]
                people.append({
                    "id": p["id"], "kind": p["kind"], "created": p["created"],
                    "has_password": p["has_password"], "grants": grants,
                    # Credentials are only shown for a principal this caller
                    # administers in full (J.2.2), so a partial administrator
                    # sees the person without their keys.
                    "manageable": administers_fully(principal, p["id"]),
                    "tokens": tokens if administers_fully(principal, p["id"]) else [],
                    "live_tokens": sum(1 for t in tokens if t["status"] == "active"),
                    "last_seen": max(seen) if seen else None,
                })
            return JSONResponse({"people": people, "forests": sorted(mine)})

        body = _json_object(await request.json())
        target = str(body.get("principal") or "").strip()
        if not target:
            return _envelope(VineError(E_SCHEMA, "principal is required"))

        applied: list[str] = []
        refused: list[dict] = []

        def deny(step: str, message: str, hint: str | None = None,
                 forest: str | None = None) -> None:
            entry = {"step": step, "message": message, "hint": hint}
            if forest is not None:
                # Which forest was refused, so a partly applied multi-forest
                # grant can be reported as the operator submitted it (J.2.3).
                entry["forest"] = forest
            refused.append(entry)

        # 1. grant — the order is normative (J.2.3): it lands first so a
        #    principal that did not exist a moment ago is administrable by
        #    the time its password and key are created below.
        #
        #    A grant may name several forests (v0.20). The set is a
        #    convenience for the operator, never a relaxation: each forest is
        #    authorised, applied and refused on its own, so an administrator
        #    of two forests out of three grants the two and is told, by id,
        #    about the third.
        grant = body.get("grant")
        if isinstance(grant, dict):
            targets = _forest_list(grant.get("forests"), grant.get("forest"))
            caps = set(grant.get("caps") or ["read"])
            if not targets:
                deny("grant", "a grant must name at least one forest")
            elif caps - CAPS:
                deny("grant", f"unknown capabilities: {sorted(caps - CAPS)}")
            else:
                landed = False
                for forest in targets:
                    if not is_admin(principal, forest, mask=mask_of(request)):
                        deny("grant", f"you do not administer '{forest}'", forest=forest)
                        continue
                    try:
                        # allow/deny travel with the grant, not with the
                        # forest: a grant is one policy expressed once.
                        registry.grant(target, forest, caps, allow=grant.get("allow"),
                                       deny=grant.get("deny"), tables=grant.get("tables"))
                        landed = True
                    except ValueError as e:
                        deny("grant", str(e), forest=forest)
                if landed:
                    applied.append("grant")

        # 2. revoke access — the same set, under the same per-forest rule.
        drop = _forest_list(body.get("revoke_access"))
        if drop:
            dropped = False
            for forest in drop:
                if not is_admin(principal, forest, mask=mask_of(request)):
                    deny("revoke_access", f"you do not administer '{forest}'", forest=forest)
                    continue
                registry.revoke(target, forest)
                dropped = True
            if dropped:
                applied.append("revoke_access")

        # From here on the target's *credentials* are at stake, and a key
        # spans forests — so the whole-person rule applies (J.2.2).
        full = administers_fully(principal, target)

        # 3. password
        if "password" in body:
            if not full:
                deny("password", f"'{target}' holds forests you do not administer")
            elif super_admin and target == super_admin[0]:
                deny("password", "the environment account has no stored password",
                     "Rotate MONKEYLLM_STATION_PASSWORD and restart.")
            else:
                registry.set_password(target, body.get("password") or None)
                applied.append("password")

        # 4. issue a key
        issued = None
        issue = body.get("issue_key")
        if issue:
            if not full:
                deny("issue_key", f"'{target}' holds forests you do not administer")
            else:
                spec = issue if isinstance(issue, dict) else {}
                try:
                    days = spec.get("expires_in_days")
                    days = float(days) if days not in (None, "", 0) else None
                except (TypeError, ValueError):
                    days = None
                issued = registry.issue_key(target, label=spec.get("label") or None,
                                            expires_in_days=days)
                applied.append("issue_key")

        # 5. revoke keys
        kill = body.get("revoke_keys")
        if kill:
            if not full:
                deny("revoke_keys", f"'{target}' holds forests you do not administer")
            else:
                ids = ([k["id"] for k in registry.keys_of([target])]
                       if kill is True else list(kill))
                for key_id in ids:
                    if registry.owner_of_key(key_id) == target:
                        registry.revoke_key(key_id)
                applied.append("revoke_keys")

        out = {"principal": target, "applied": applied, "refused": refused}
        if issued:
            out["api_key"] = issued
        # One row for the request, listing the steps that landed and the ones
        # that did not: this route is where a person is made, credentialed and
        # unmade, so "what happened to this account, and when" is answerable
        # from a single place. A refusal is worth recording too — that is what
        # an attempt looks like afterwards.
        if applied or refused:
            record_governance(
                principal, "admin.people",
                {"target": target, "applied": ",".join(applied) or "-",
                 "refused": ",".join(r["step"] for r in refused) or "-"},
                "ok" if applied else "refused")
        # 403 only when nothing at all could be done; a partial success has
        # to report as one, or the console cannot tell the two apart.
        return JSONResponse(out, status_code=200 if applied else
                            (403 if refused else 200))

    async def admin_create_forest(request: Request) -> JSONResponse:
        """J.7: a deployment reaches its second forest without shell access.

        Creation is A.5 `init_forest` and nothing else — the Station adds no
        second way to make a forest, so what it produces is byte-identical to
        what `vine init` produces.
        """
        principal, err = require_principal(request)
        if err:
            return err
        if pool.mode != "registry":
            return _envelope(VineError(
                E_SCHEMA, "this Station serves a single forest",
                hint="Start it with --root <registry> to host more than one."))
        if not writable:
            return _envelope(VineError(
                E_READONLY, "this Station serves read-only forests",
                hint="Start it with --writable to create forests."), 403)
        # J.7 as amended in v0.25: `admin` on an existing forest, or the owner
        # bit — the authority that precedes every forest, and the only one an
        # empty registry can offer.
        if not is_admin(principal, mask=mask_of(request)):
            return _envelope(
                VineError(E_FORBIDDEN, "creating a forest requires the 'admin' "
                                       "capability on an existing forest"), 403)
        body = _json_object(await request.json())
        forest_id = str(body.get("id") or "").strip()
        title = str(body.get("title") or "").strip()
        if not FOREST_ID.match(forest_id):
            return _envelope(VineError(
                E_SCHEMA, f"invalid forest id: {forest_id!r}",
                hint="Lowercase letters, digits, '-' and '_'; up to 63 characters."))
        if not title:
            return _envelope(VineError(E_SCHEMA, "title is required",
                                       hint="It becomes the master index heading."))

        target = pool.root / forest_id
        if target.exists():
            # Returning the existing forest because the name matched would be
            # an access-control bug wearing a convenience feature (J.7).
            return _envelope(VineError(E_SCHEMA, f"'{forest_id}' already exists",
                                       hint="Pick another id."))

        # J.2.4: the first forest may arrive seeded, so an operator who has
        # just finished setup lands on a console that can answer something.
        # It is the same `init_forest` either way — the seed is planted
        # afterwards through the public primitives, adding no second way to
        # make a forest.
        seed = str(body.get("seed") or "").strip().lower()
        if seed not in ("", "demo"):
            return _envelope(VineError(
                E_SCHEMA, f"unknown seed: {seed!r}", hint="Omit it, or 'demo'."))

        def create():
            from monkeyllm.forest import init_forest

            if seed == "demo":
                from monkeyllm_station.demo_forest import build_demo

                return build_demo(target, title=title)
            return init_forest(target, title=title,
                               summary=body.get("summary") or None)

        try:
            info = await in_forest_thread(forest_id, create)
        except VineError as e:
            return _envelope(e)
        except Exception as e:
            # A half-planted seed would leave a forest nobody asked for, so it
            # is removed rather than reported as a success with a hole in it.
            shutil.rmtree(target, ignore_errors=True)
            return _envelope(VineError(
                E_SCHEMA, f"could not create '{forest_id}': {e}",
                hint="Nothing was left behind; try again."))
        # A forest nobody can open is a silent failure with a 200 (J.7).
        registry.grant(principal, forest_id, set(CAPS))
        record_governance(principal, "admin.forest.create",
                          {"title": title, "seed": seed or "-"}, "ok",
                          forest=forest_id)
        hooks.emit(webhooks.DEPLOYMENT, "forest.created", principal,
                   {"forest": forest_id, "title": title, "seed": seed or None,
                    "commit": info.get("commit")})
        return JSONResponse({"forest": {"id": forest_id, "title": title,
                                        "commit": info.get("commit")},
                             "grants": registry.grants_of(principal)})

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

        # J.10.6: what the call cost, in a header rather than in the body.
        # Emitted for refusals too — how long a 403 took is not a fact about
        # the forest behind it, and a route that timed only its successes
        # would say which forests exist by staying silent.
        clocks: dict = {}
        # Read off the request BEFORE the lane, like the MCP surface does:
        # the mask belongs to the credential and the lane never saw one.
        mask = mask_of(request)
        # J.10.12: a caller may watch this call's progress. Claimed HERE, on
        # the loop, because the record captures the loop a forest lane will
        # later wake it from — and claimed before the call so the channel can
        # be opened without racing the first event.
        run_key = None
        if name == "answer" and isinstance(payload.get("run"), str) and payload["run"]:
            run_key = (principal, forest, payload["run"][:RUN_ID_MAX])
            if not runs.claim(run_key):
                return _envelope(VineError(
                    E_SCHEMA, "that run id is already in flight",
                    hint="A run identifies ONE call while it runs (J.10.12). "
                         "Use a fresh id per question."))
        try:
            result = await execute_call(principal, forest, name, payload,
                                        clocks, mask)
        finally:
            # The channel closes whatever happened — an errored call that
            # left its watcher waiting would be a spinner with no end.
            if run_key is not None:
                runs.finish(run_key)
        timing = _server_timing(clocks)
        if result is None:
            response = _unknown_forest(forest)
            response.headers["Server-Timing"] = timing
            return response
        if isinstance(result, dict) and "_prepared" in result:
            # J.9: the batch was accepted on the lane; the driver steps it
            # from the event loop. 202 now — or, for a caller that said
            # `wait`, the finished job in one response.
            job = _launch_ingest(result["_prepared"])
            if payload.get("wait"):
                await job.task
                return JSONResponse({"job": job.snapshot()},
                                    headers={"Server-Timing": timing})
            return JSONResponse({"job": job.snapshot()}, status_code=202,
                                headers={"Server-Timing": timing})
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400),
                                headers={"Server-Timing": timing})
        return JSONResponse(result, headers={"Server-Timing": timing})

    # -- governance (J.5's console needs a surface, not a side-channel) ------

    async def admin_principals(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        if not is_admin(principal, mask=mask_of(request)):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)
        # J.3.2: a branch prefix describes somebody's world. It does not
        # become readable because the reader administers a different forest.
        mine = administered(principal)
        people = []
        for p in registry.principals():
            detail = [g for g in registry.grants_of(p["id"]) if g["forest"] in mine]
            if detail:
                people.append({**p, "grants_detail": detail,
                               "grants": len(detail)})
        return JSONResponse({"principals": people})

    async def admin_grant(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        body = _json_object(await request.json())
        forest = body.get("forest")
        gate = admin_gate(principal, forest, request)
        if gate is not None:
            return gate
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
        # A grant is recorded against the forest it is about, so the forest's
        # own administrator can read it back (the audit filter is per forest).
        record_governance(principal, "admin.grant",
                          {"target": target, "caps": ",".join(sorted(caps))},
                          "ok", forest=forest)
        hooks.emit(forest, "grant.changed", principal,
                   {"principal": target, "caps": sorted(caps),
                    "branches": len(body.get("allow") or [])})
        out = {"principal": target, "grants": registry.grants_of(target)}
        if body.get("issue_key"):
            out["api_key"] = registry.issue_key(target, label=forest)
            record_governance(principal, "admin.key.issue",
                              {"target": target, "label": forest,
                               "prefix": out["api_key"][:9]}, "ok")
            hooks.emit(webhooks.DEPLOYMENT, "key.issued", principal,
                       {"principal": target, "label": forest,
                        "prefix": out["api_key"][:9]})
        return JSONResponse(out)

    # J.4.2: the fields a row gained in v0.73. Emitted only when the row
    # actually carries them — a row written by an older Station makes no
    # claim about its cost, its refusal or its clock, and answering `0` on
    # its behalf would invent one.
    AUDIT_OPTIONAL = ("ms", "model_ms", "error_code", "usd", "tokens",
                      "calls", "priced")

    def audit_entry(row: dict) -> dict:
        out = {k: v for k, v in row.items()
               if k not in AUDIT_OPTIONAL or v is not None}
        if "priced" in out:
            out["priced"] = bool(out["priced"])
        return out

    async def admin_audit(request: Request) -> JSONResponse:
        """The access log, filtered and totalled (J.4, J.4.3).

        Every filter is applied in SQL, before the page is cut, and the
        totals are computed over the same filtered set rather than over the
        page that came back. That is the whole difference between a summary
        and a fact about the page size — and it is why the filter is built
        in one place in the registry and read three ways from there.
        """
        principal, err = require_principal(request)
        if err:
            return err
        if not is_admin(principal, mask=mask_of(request)):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)
        q = request.query_params
        try:
            limit = min(max(int(q.get("limit", 100)), 1), 500)
        except (TypeError, ValueError):
            return _envelope(VineError(
                E_SCHEMA, f"limit must be an integer, got {q.get('limit')!r}"))
        # C.13's rule, on the one route where being wrong about it is a
        # false statement about who did what: a bound we cannot read is
        # refused, never quietly dropped.
        try:
            window = normalize_window(q.get("since"), q.get("until"), None)
        except VineError as e:
            return _envelope(e)
        # An audit entry records what somebody read. Same rule as J.3.2: the
        # scope decides first, and since v0.73 it decides in SQL — a total
        # over rows this caller may not read would be a finer size oracle
        # than the page ever was.
        mine = administered(principal)
        # Governance rows belong to no forest, and they describe the whole
        # deployment: who was granted what, which keys exist, where the
        # provider points. Showing those to an administrator of one forest
        # would hand them the shape of every other one — the same mistake
        # J.3.2 corrected for content.
        if registry.is_owner(principal):
            mine = mine | {NO_FOREST}
        scope = {"forests": mine,
                 "since": (window or {}).get("since"),
                 "before": exclusive_end(window["until"])
                 if window and window.get("until") else None}
        filters = {**scope,
                   "principal": q.get("principal"),
                   "forest": q.get("forest"),
                   "primitive": q.get("primitive"),
                   "result": q.get("result"),
                   "errors": q.get("errors") in ("1", "true", "yes")}
        return JSONResponse({
            "entries": [audit_entry(e) for e in registry.audit(limit=limit, **filters)],
            "totals": registry.audit_totals(**filters),
            # Narrowed by the scope and the window only: choosing a
            # primitive must not empty the list of primitives (J.4.3).
            "filters": registry.audit_facets(**scope),
        })

    async def admin_providers(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        mask = mask_of(request)
        if not is_admin(principal, mask=mask):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)
        if request.method == "GET":
            # Listing is readable by any forest administrator: the name and
            # endpoint are what a per-forest model binding points at, and no
            # secret is returned (`has_key` is a bool).
            return JSONResponse({"providers": registry.providers()})
        if not governs_deployment(principal, mask):
            return _envelope(VineError(
                E_FORBIDDEN, "managing providers requires authority over every forest",
                hint="A provider serves every forest; administering one of "
                     "several does not cover it."), 403)
        body = _json_object(await request.json())
        try:
            if body.get("remove"):
                registry.delete_provider(body["name"])
            else:
                registry.put_provider(body.get("name"), body.get("endpoint"),
                                      body.get("api_key"))
        except (ValueError, KeyError) as e:
            record_governance(principal, "admin.provider",
                              {"name": str(body.get("name") or ""),
                               "endpoint": str(body.get("endpoint") or "")}, "refused")
            return _envelope(VineError(E_SCHEMA, str(e)))
        # Where a provider points is where every forest's material goes, so a
        # change of address is the entry somebody will want to find later.
        record_governance(
            principal, "admin.provider",
            {"name": str(body.get("name") or ""),
             "endpoint": "" if body.get("remove") else str(body.get("endpoint") or ""),
             "removed": bool(body.get("remove")),
             "key_supplied": bool(body.get("api_key"))}, "ok")
        hooks.emit(webhooks.DEPLOYMENT, "provider.changed", principal,
                   {"name": str(body.get("name") or ""),
                    "endpoint": "" if body.get("remove")
                    else str(body.get("endpoint") or ""),
                    "removed": bool(body.get("remove")),
                    "key_supplied": bool(body.get("api_key"))})
        return JSONResponse({"providers": registry.providers()})

    async def admin_provider_test(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        # Testing a provider spends the deployment's stored credential against
        # a destination the caller names, so it carries the same authority as
        # editing one.
        if not governs_deployment(principal, mask_of(request)):
            return _envelope(VineError(
                E_FORBIDDEN, "testing a provider requires authority over every forest",
                hint="A provider serves every forest; administering one of "
                     "several does not cover it."), 403)
        from monkeyllm_station import inference

        body = _json_object(await request.json())
        secret = registry.provider_secret(body.get("name", ""))
        stored_endpoint = (secret or {}).get("endpoint")
        endpoint = body.get("endpoint") or stored_endpoint
        if not endpoint:
            return _envelope(VineError(E_SCHEMA, "endpoint is required"))
        # The stored key belongs to the address it was stored against. A
        # caller-supplied endpoint that differs from the stored one is a new
        # destination: it brings its own key, or it goes with none. Only when
        # the target is the provider's own address does the stored key attach.
        if body.get("endpoint") and endpoint.rstrip("/") != (stored_endpoint or "").rstrip("/"):
            key = body.get("api_key")
        else:
            key = body.get("api_key") or (secret or {}).get("api_key")
        guard = _reject_internal_endpoint(endpoint)
        if guard is not None:
            record_governance(principal, "admin.provider.test",
                              {"name": str(body.get("name") or ""),
                               "endpoint": endpoint}, "refused")
            return guard
        # This route makes the server open a connection to an address the
        # caller chose. Even refused, that is worth a row.
        record_governance(principal, "admin.provider.test",
                          {"name": str(body.get("name") or ""),
                           "endpoint": endpoint,
                           "stored_key": bool(key and not body.get("api_key"))}, "ok")
        return JSONResponse(await asyncio.get_running_loop().run_in_executor(
            None, lambda: inference.probe(endpoint, key)))

    async def admin_models(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        if request.method == "GET":
            forest = request.query_params.get("forest")
            if not is_admin(principal, forest, mask=mask_of(request)):
                return _envelope(VineError(E_FORBIDDEN, "requires 'admin' on that forest"), 403)
            return JSONResponse({"bindings": registry.bindings(forest)})
        body = _json_object(await request.json())
        forest = body.get("forest")
        if not is_admin(principal, forest, mask=mask_of(request)):
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
        # Which model reads a forest's material is a property of that forest,
        # so this row carries its id and its administrator can read it back.
        record_governance(principal, "admin.model.bind",
                          {"role": str(body.get("role") or ""),
                           "provider": str(body.get("provider") or ""),
                           "model": str(body.get("model") or ""),
                           "removed": bool(body.get("remove"))},
                          "ok", forest=forest)
        hooks.emit(forest, "model.bound", principal,
                   {"role": str(body.get("role") or ""),
                    "provider": str(body.get("provider") or ""),
                    "model": str(body.get("model") or ""),
                    "removed": bool(body.get("remove"))})
        return JSONResponse({"bindings": registry.bindings(forest)})

    async def forest_map(request: Request) -> JSONResponse:
        """`GET /v1/forests/{forest}/graph` and `.../trails` (J.11)."""
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        kind = request.path_params["kind"]
        mask = mask_of(request)
        if kind == "ingest":
            # The GET beside the POST: what a refresh would re-read (J.8).
            result = await in_forest_thread(
                forest, lambda: run_ingest_status(principal, forest, mask))
            if result is None:
                return _unknown_forest(forest)
            if isinstance(result.get("error"), dict):
                code = result["error"].get("code", E_SCHEMA)
                return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
            return JSONResponse(result)
        if kind not in MAP_KINDS:
            return _envelope(VineError(
                E_NOT_FOUND, f"no such endpoint: {kind}",
                hint=f"Map projections: {sorted(MAP_KINDS)}. "
                     "Primitives are POSTed to this path."))
        params = dict(request.query_params)
        # J.6.2: the graph is a read — it rides the reader pool, so an open
        # Explore never waits behind a plant or a batch.
        slot = reader_slot(forest, "look")
        get_vine = ((lambda: readers.vine(forest, slot))
                    if slot is not None else None)
        result = await in_lane(
            forest, slot,
            lambda: run_map(principal, forest, kind, params, mask,
                            get_vine=get_vine))
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        return JSONResponse(result)

    # -- ingest jobs, read side (J.9) ---------------------------------------

    # -- webhooks over REST (J.16) ------------------------------------------

    # A header name, and the ceiling on what one may carry. Bounded because
    # every one of them rides on every delivery, and unbounded configuration
    # is how a notification becomes a payload.
    HEADER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    HEADER_VALUE_MAX = 1024
    LABEL_MAX = 80
    BRANCHES_MAX = 20

    def webhook_public(hook: dict) -> dict:
        """One webhook as the wire may see it.

        The secret never appears — it was shown once, at creation (J.16.4).
        Headers appear as NAMES: a value that can be read back is a value
        that leaks through anyone who can read the configuration, which is
        the custody rule a provider's key already gets.
        """
        return {
            "id": hook["id"], "scope": hook["scope"], "owner": hook["owner"],
            "label": hook["label"] or "", "url": hook["url"],
            "events": hook["events"], "branches": hook["branches"],
            "headers": sorted(hook["headers"] or {}),
            "include_metadata": hook["include_metadata"],
            "enabled": hook["enabled"], "suspended": hook["suspended"],
            "fail_streak": hook["fail_streak"], "created": hook["created"],
            "last_status": hook["last_status"], "last_at": hook["last_at"],
        }

    def webhook_scopes(principal: str, forest: str,
                       mask: frozenset[str] | None) -> list[str]:
        """Which scopes this caller may hold a webhook in, on this console.

        Deployment scope is J.10.2's reach rule unchanged: the owner, or an
        administrator of every forest there is. A forest admin who is not
        that never sees a deployment webhook and cannot make one — the
        scope is a ceiling, not a filter (J.16.2).
        """
        scopes = []
        if is_admin(principal, forest, mask=mask):
            scopes.append(forest)
        if governs_deployment(principal, mask):
            scopes.append(webhooks.DEPLOYMENT)
        return scopes

    def webhook_or_refusal(principal: str, forest: str, webhook_id: str,
                           mask: frozenset[str] | None):
        """The row, or the one answer that covers absent and out-of-scope.

        Byte-identical for both, on J.14's terms: which webhooks exist on a
        forest this caller does not administer is itself something they do
        not administer.
        """
        allowed = webhook_scopes(principal, forest, mask)
        hook = registry.webhook(webhook_id)
        if hook is None or hook["scope"] not in allowed:
            return None, _envelope(VineError(E_NOT_FOUND, "no such webhook"))
        return hook, None

    def read_webhook_body(body: dict, scope: str,
                          existing: dict | None) -> tuple[dict, JSONResponse | None]:
        """Validate a submitted webhook. Refuses; never repairs."""
        url = str(body.get("url") or "").strip()
        if not url:
            return {}, _envelope(VineError(E_SCHEMA, "url is required"))
        # A webhook URL is a caller-supplied address the Station will
        # connect to repeatedly and unattended — J.10.2's problem, so
        # J.10.2's answer, resolved rather than read (v0.50).
        refusal = _reject_internal_endpoint(url)
        if refusal is not None:
            return {}, refusal

        events = body.get("events")
        if not isinstance(events, list) or not events:
            return {}, _envelope(VineError(
                E_SCHEMA, "events must be a non-empty list",
                hint="GET this endpoint for the catalogue this scope may use."))
        allowed = webhooks.allowed_events(scope)
        outside = [e for e in events if e not in allowed]
        if outside:
            # Named, and refused rather than dropped: a subscription
            # silently narrowed reads as coverage the operator does not have.
            unknown = [e for e in outside if e not in webhooks.EVENTS]
            return {}, _envelope(VineError(
                E_SCHEMA,
                f"events outside this webhook's scope: {sorted(outside)}",
                hint="Unknown event name." if unknown else
                     "Deployment events need a webhook in the deployment "
                     "scope, held by a principal who administers every "
                     "forest (J.16.2)."))

        branches = body.get("branches") or []
        if not isinstance(branches, list) or len(branches) > BRANCHES_MAX:
            return {}, _envelope(VineError(
                E_SCHEMA, f"branches must be a list of at most {BRANCHES_MAX} prefixes"))
        branches = [str(b) for b in branches if str(b).strip()]

        headers, refusal = read_webhook_headers(body, existing)
        if refusal is not None:
            return {}, refusal

        label = str(body.get("label") or "").strip()[:LABEL_MAX]
        return {
            "url": url, "events": [str(e) for e in events],
            "branches": branches, "headers": headers, "label": label,
            "include_metadata": bool(body.get("include_metadata")),
            "enabled": bool(body.get("enabled", True)),
        }, None

    def read_webhook_headers(body: dict,
                             existing: dict | None) -> tuple[dict, JSONResponse | None]:
        """The operator's own headers, with the custody rule spelled out.

        Absent from the body: keep what is stored. Present: it replaces the
        map, and a value of `null` means "keep this one" — which is the
        only way an editor that can never READ a value can leave it alone.
        """
        stored = (existing or {}).get("headers") or {}
        if "headers" not in body:
            return dict(stored), None
        submitted = body.get("headers")
        if submitted in (None, ""):
            return {}, None
        if not isinstance(submitted, dict):
            return {}, _envelope(VineError(E_SCHEMA, "headers must be an object"))
        if len(submitted) > webhooks.MAX_HEADERS:
            return {}, _envelope(VineError(
                E_SCHEMA, f"at most {webhooks.MAX_HEADERS} headers"))
        out = {}
        for name, value in submitted.items():
            if not HEADER_NAME.match(str(name)):
                return {}, _envelope(VineError(
                    E_SCHEMA, f"not a header name: {name!r}"))
            lower = str(name).lower()
            if lower in webhooks.RESERVED_HEADERS or lower.startswith(
                    webhooks.HEADER_PREFIX):
                return {}, _envelope(VineError(
                    E_SCHEMA, f"'{name}' is set by the Station",
                    hint="The framing and the signed X-MonkeyLLM-* set "
                         "belong to the delivery, not to its configuration."))
            if value is None:
                if name in stored:
                    out[name] = stored[name]
                continue
            if not isinstance(value, str) or len(value) > HEADER_VALUE_MAX:
                return {}, _envelope(VineError(
                    E_SCHEMA,
                    f"header '{name}' must be a string of at most "
                    f"{HEADER_VALUE_MAX} characters"))
            out[name] = value
        return out, None

    async def forest_webhooks(request: Request) -> JSONResponse:
        """List and create (J.16). The catalogue rides on the GET, so no
        console hard-codes it and an integration can enumerate it."""
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        mask = mask_of(request)
        scopes = webhook_scopes(principal, forest, mask)
        if not scopes:
            return _envelope(VineError(
                E_FORBIDDEN, "requires the 'admin' capability on that forest"), 403)

        if request.method == "GET":
            return JSONResponse({
                "webhooks": [webhook_public(h) for h in registry.webhooks(scopes)],
                "events": webhooks.catalogue(
                    webhooks.DEPLOYMENT if webhooks.DEPLOYMENT in scopes else forest),
                "groups": list(webhooks.GROUPS),
                "scopes": ["forest"] + (["deployment"]
                                        if webhooks.DEPLOYMENT in scopes else []),
                "limits": {"attempts": webhooks.MAX_ATTEMPTS,
                           "suspend_after": webhooks.SUSPEND_AFTER,
                           "timeout_seconds": webhooks.TIMEOUT_SECONDS,
                           "max_headers": webhooks.MAX_HEADERS,
                           "keep_deliveries": webhooks.KEEP_DELIVERIES},
                "queue": {"pending": hooks.pending(), "dropped": hooks.dropped},
            })

        try:
            body = _json_object(await request.json())
        except json.JSONDecodeError as e:
            return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
        if not isinstance(body, dict):
            return _envelope(VineError(E_SCHEMA, "body must be a JSON object"))

        webhook_id = str(body.get("id") or "").strip() or None
        existing = None
        if webhook_id:
            existing, refusal = webhook_or_refusal(principal, forest,
                                                   webhook_id, mask)
            if refusal is not None:
                return refusal
            scope = existing["scope"]
        else:
            wanted = str(body.get("scope") or "forest")
            scope = webhooks.DEPLOYMENT if wanted == "deployment" else forest
            if scope not in scopes:
                return _envelope(VineError(
                    E_FORBIDDEN,
                    "a deployment webhook requires authority over every forest",
                    hint="It hears events that belong to no forest, so "
                         "administering one of several does not cover it."), 403)

        fields, refusal = read_webhook_body(body, scope, existing)
        if refusal is not None:
            return refusal

        secret = None if existing else webhooks.new_secret()
        try:
            hook = registry.put_webhook(webhook_id=webhook_id, scope=scope,
                                        owner=principal, secret=secret, **fields)
        except ValueError as e:
            return _envelope(VineError(E_SCHEMA, str(e)))
        hooks.refresh()
        audit_webhook(principal, hook, "update" if existing else "create",
                      {"events": len(fields["events"])})
        out = {"webhook": webhook_public(hook)}
        if secret:
            # Once. The console says so at the moment it shows it (J.5.4).
            out["secret"] = secret
        return JSONResponse(out, status_code=200 if existing else 201)

    async def forest_webhook(request: Request) -> JSONResponse:
        """One webhook: its deliveries, its three actions, its removal."""
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        mask = mask_of(request)
        hook, refusal = webhook_or_refusal(principal, forest,
                                           request.path_params["hook"], mask)
        if refusal is not None:
            return refusal

        if request.method == "GET":
            limit = min(int(request.query_params.get("limit", 50)),
                        webhooks.KEEP_DELIVERIES)
            return JSONResponse({
                "webhook": webhook_public(hook),
                # The stored body travels back: it is what the console shows
                # as "this is what your endpoint received", and it is already
                # the J.16.1 payload — there is nothing in it to withhold.
                "deliveries": registry.deliveries(hook["id"], limit),
            })

        if request.method == "DELETE":
            registry.delete_webhook(hook["id"])
            hooks.refresh()
            audit_webhook(principal, hook, "delete")
            return JSONResponse({"deleted": hook["id"]})

        try:
            body = _json_object(await request.json() if await request.body() else {})
        except json.JSONDecodeError as e:
            return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
        action = str(body.get("action") or "").strip()

        if action == "rotate":
            secret = webhooks.new_secret()
            registry.put_webhook(
                webhook_id=hook["id"], scope=hook["scope"], owner=hook["owner"],
                url=hook["url"], events=hook["events"], label=hook["label"],
                branches=hook["branches"], headers=hook["headers"],
                include_metadata=hook["include_metadata"],
                enabled=hook["enabled"], secret=secret)
            hooks.refresh()
            audit_webhook(principal, hook, "rotate")
            return JSONResponse({"webhook": webhook_public(registry.webhook(hook["id"])),
                                 "secret": secret})

        if action == "test":
            # Off the event loop: this opens a socket and waits up to the
            # delivery timeout. Synchronous for the caller on purpose — the
            # operator is asking about the address, not about the queue.
            record = await in_forest_thread(None, lambda: hooks.test(hook))
            audit_webhook(principal, hook, "test",
                          {"status": record.get("status") or 0})
            return JSONResponse({"delivery": record})

        if action == "redeliver":
            stored = registry.delivery(hook["id"], str(body.get("delivery") or ""))
            if stored is None:
                return _envelope(VineError(E_NOT_FOUND, "no such delivery"))
            record = await in_forest_thread(
                None, lambda: hooks.redeliver(hook, stored))
            return JSONResponse({"delivery": record})

        return _envelope(VineError(
            E_SCHEMA, f"unknown action: {action or '(none)'}",
            hint="One of: test, rotate, redeliver."))

    def _job_watch_refusal(principal: str, forest: str,
                           mask: frozenset[str] | None = None
                           ) -> JSONResponse | None:
        """Who may watch: whoever could have asked (J.9). Touches only the
        host registry — never the forest, never a lane — which is what
        keeps polling free while the batch runs."""
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return _unknown_forest(forest)
        policy = policy.masked(mask)
        if not policy.grants("ingest"):
            return _envelope(VineError(
                E_FORBIDDEN, "watching ingest jobs requires the 'ingest' capability",
                hint=f"This principal holds: {sorted(policy.caps)}."), 403)
        return None

    async def jobs_list(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        refused = _job_watch_refusal(principal, forest, mask_of(request))
        if refused is not None:
            return refused
        listed, truncated = board.list(forest)
        out: dict = {"jobs": listed}
        if truncated:
            out["truncated"] = True
        return JSONResponse(out)

    async def job_get(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        refused = _job_watch_refusal(principal, forest, mask_of(request))
        if refused is not None:
            return refused
        job = board.get(forest, request.path_params["job"])
        if job is None:
            # Absence of the record is not failure of the work (J.9): a
            # restart forgets jobs, never commits.
            return _envelope(VineError(
                E_NOT_FOUND, f"no such job: {request.path_params['job']}",
                hint="A restart forgets job records, never the work — the "
                     "forest's own account is the audit log and git log."), 404)
        return JSONResponse({"job": job.snapshot()})

    async def job_cancel(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        refused = _job_watch_refusal(principal, forest, mask_of(request))
        if refused is not None:
            return refused
        job = board.get(forest, request.path_params["job"])
        if job is None:
            return _envelope(VineError(
                E_NOT_FOUND, f"no such job: {request.path_params['job']}"), 404)
        # Asked here, honoured by the driver at the next step boundary
        # (J.9): a document is whole or absent, never half. On a finished
        # job this is a no-op, not an error — "make it not run" is already
        # true.
        board.cancel(job)
        return JSONResponse({"job": job.snapshot()})

    # -- payload bytes (J.14) -------------------------------------------------

    async def forest_payload(request: Request):
        """`GET /v1/forests/{forest}/payload/{node}`: the raw bytes behind a
        node's textual proxy (J.14).

        A human surface: the console shows the screenshot, the browser saves
        the `.db`. Payload bytes MUST NOT enter model material through it —
        G.5's line stands, and the describer (G.5.1) is the one place a
        model sees the image, at ingest, once. Served by a read-only Station
        too: it writes nothing.
        """
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        node_id = request.path_params["node"]
        policy = registry.policy_for(principal, forest)
        if policy is None:
            # No grant and no such forest answer identically, exactly as the
            # primitive dispatch does — the registry is not enumerable.
            return _unknown_forest(forest)
        policy = policy.masked(mask_of(request))
        if not policy.grants("read"):
            return _envelope(VineError(
                E_FORBIDDEN, "'payload' requires the 'read' capability",
                hint=f"This principal holds: {sorted(policy.caps)}."), 403)

        def work():
            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            # ONE envelope for out-of-scope, absent and payload-less (J.14 /
            # F.49): byte-identical, mirroring `ScopedVine._gate`, so this
            # surface is no more an existence oracle than the primitives.
            not_found = VineError(
                E_NOT_FOUND, f"node not found: {node_id}",
                hint="Use locate() to find entry points.").to_dict()
            if not policy.in_scope(node_id) or not vine.forest.exists(node_id):
                return not_found
            try:
                node = vine.forest.read(node_id)
            except VineError:
                # Unparseable frontmatter behind a URL-guessed id reads as
                # absent, not as a distinguishable third state.
                return not_found
            payload = str(node.frontmatter.get("payload") or "")
            if not payload:
                # Absence is explicit — the map keeps working (G.7).
                return not_found
            if "://" in payload:
                scheme = payload.split("://", 1)[0]
                # Fetching on a GET would hide a network dependency inside a
                # read (G.9); a remote region is warmed by `vine prefetch`.
                return VineError(
                    E_SCHEMA,
                    f"remote payload scheme '{scheme}' is not served",
                    hint="This surface serves local bytes only.").to_dict()
            # Relative to the node's own directory, exactly as the Gardener
            # writes it (`_assets/<name>` or a sibling `.db`) — and contained
            # after resolution, J.8.2's posture: this surface hands out file
            # contents, so a payload field pointing outside the forest is
            # refused, never followed.
            root_dir = Path(vine.forest.root).resolve()
            assert node.path is not None
            target = (node.path.parent / payload).resolve()
            if not target.is_relative_to(root_dir):
                return VineError(
                    E_SCHEMA, "payload escapes the forest").to_dict()
            if not target.is_file():
                # The map said bytes exist and the disk disagrees: to the
                # reader that is the same absent payload as no field at all.
                return not_found
            return {"path": str(target),
                    "etag": str(node.frontmatter.get("payload_hash") or ""),
                    "size": target.stat().st_size}

        result = await in_forest_thread(forest, work)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        # Audited like a read (J.4): who fetched which node's bytes, and how
        # many — never the bytes.
        registry.record(principal=principal, forest=forest, primitive="payload",
                        args={"node": node_id}, result="ok",
                        size=result["size"])
        headers = {"Cache-Control": "private"}
        if result["etag"]:
            # The passport's own hash: a client that cached the bytes can
            # revalidate against the map instead of re-downloading — and the
            # revalidation is honoured HERE, because FileResponse never
            # reads If-None-Match, so without this a console revisiting a
            # media node re-downloads the whole payload every time.
            headers["ETag"] = result["etag"]
            if request.headers.get("if-none-match") == result["etag"]:
                return Response(status_code=304, headers=headers)
        media_type = (mimetypes.guess_type(result["path"])[0]
                      or "application/octet-stream")
        return FileResponse(result["path"], media_type=media_type,
                            headers=headers)

    async def forest_export(request: Request):
        """`GET /v1/forests/{forest}/export/{node}`: the document as
        text/markdown (J.14.1) — J.14's discipline for the map's own text.

        No token budget: this is a download for people and pipelines;
        budgets protect a model's context window and none is on this path.
        `content: inline` is served verbatim (byte-identical to what was
        planted, F.84); cached/reference bodies are resolved (G.7).
        """
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        node_id = request.path_params["node"]
        # J.14.1 (v0.57): an unknown query parameter is E_SCHEMA, never
        # silence — `?recursive=true` was accepted with 200 and ignored,
        # the exact defect C.8 fixed for graft, alive on the route beside
        # it. A download URL is pasted and hand-edited more than any JSON
        # body; the silent-parameter failure mode is worse here.
        unknown = [k for k in request.query_params if k != "recursive"]
        if unknown:
            return _envelope(VineError(
                E_SCHEMA, f"unknown query parameter {unknown[0]!r}",
                hint="This route accepts: recursive."))
        raw_recursive = request.query_params.get("recursive")
        if raw_recursive is not None and raw_recursive.lower() not in (
                "true", "1", "false", "0"):
            return _envelope(VineError(
                E_SCHEMA,
                f"recursive must be true or false, got {raw_recursive!r}"))
        recursive = (raw_recursive or "").lower() in ("true", "1")
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return _unknown_forest(forest)
        policy = policy.masked(mask_of(request))
        if not policy.grants("read"):
            return _envelope(VineError(
                E_FORBIDDEN, "'export' requires the 'read' capability",
                hint=f"This principal holds: {sorted(policy.caps)}."), 403)

        def work(vine=None):
            try:
                if vine is None:
                    vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            try:
                scoped = ScopedVine(vine, policy)
                # ScopedVine._gate answers out-of-scope and absent with one
                # byte-identical envelope — this surface is no more an
                # existence oracle than the primitives (J.14 / F.49). The
                # gate runs FIRST even for the subtree form, so a leaf vs
                # branch question is only ever answered about a node the
                # caller may read.
                text = scoped.export(node_id)
                if not recursive:
                    return {"text": text}
                row = vine.catalog.get(node_id)
                if row is None or row["kind"] != "branch":
                    # J.14.1 (v0.57): a leaf has no subtree, and pretending
                    # otherwise is the silence this rule removes.
                    return VineError(
                        E_SCHEMA,
                        f"recursive=true needs a branch; '{node_id}' is not one",
                        hint="Export the node without the flag.").to_dict()
                # The caller's scope's view, exactly as scan's: out-of-scope
                # nodes are absent — silently, because a manifest of what a
                # scope may not see would be the size oracle J.3 prevents.
                members = [node_id] + sorted(
                    r["id"] for r in vine.catalog.children(node_id,
                                                           recursive=True)
                    if policy.in_scope(r["id"]))
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for mid in members:
                        # Each member byte-identical to its single export
                        # (F.93); the id is a path, so the zip unpacks as
                        # the subtree it is.
                        zf.writestr(f"{mid}.md",
                                    text if mid == node_id
                                    else scoped.export(mid))
                return {"zip": buf.getvalue(), "members": len(members)}
            except VineError as e:
                return e.to_dict()

        slot = reader_slot(forest, "pick")
        result = await in_lane(
            forest, slot,
            lambda: work(readers.vine(forest, slot))
            if slot is not None else work())
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        leaf = node_id.rsplit("/", 1)[-1] or "node"
        if "zip" in result:
            # The zip is named for the region, not the index file: a
            # `monkeyllm/_index` subtree downloads as `monkeyllm.zip`. The
            # single `.md` keeps its v0.56 name to the byte.
            zip_leaf = (node_id.rsplit("/", 2)[-2]
                        if leaf == "_index" and "/" in node_id
                        else (forest if node_id == "_index" else leaf))
            registry.record(principal=principal, forest=forest,
                            primitive="export",
                            args={"node": node_id, "recursive": True},
                            result="ok", size=len(result["zip"]))
            return Response(
                result["zip"], media_type="application/zip",
                headers={
                    "Cache-Control": "private",
                    "Content-Disposition":
                        f'attachment; filename="{zip_leaf}.zip"',
                })
        text = result["text"]
        registry.record(principal=principal, forest=forest, primitive="export",
                        args={"node": node_id}, result="ok", size=len(text))
        return Response(
            text, media_type="text/markdown; charset=utf-8",
            headers={
                "Cache-Control": "private",
                "Content-Disposition": f'attachment; filename="{leaf}.md"',
            })

    # -- the tag vocabulary (J.5.18 rule 4) ----------------------------------

    async def forest_tags(request: Request) -> JSONResponse:
        """`GET /v1/forests/{forest}/tags`: the tags that actually occur,
        with the number of nodes each carries (J.5.18 rule 4).

        Reading, so a read-only Station serves it and it rides the reader
        pool — a console browsing a vocabulary must not wait behind
        somebody's plant.

        `limit` cuts the LISTING and nothing else. Every count is computed
        over the caller's whole scope in SQL, for J.4.3's reason: a total
        assembled from the page on screen changes when somebody changes the
        page size, and this number exists to make `invoice` beside
        `invoices` visible — which it cannot do if it moves.
        """
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        unknown = [k for k in request.query_params if k != "limit"]
        if unknown:
            return _envelope(VineError(
                E_SCHEMA, f"unknown query parameter {unknown[0]!r}",
                hint="This route accepts: limit."))
        raw_limit = request.query_params.get("limit")
        limit = None
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except ValueError:
                return _envelope(VineError(
                    E_SCHEMA, f"limit must be an integer, got {raw_limit!r}"))
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return _unknown_forest(forest)
        policy = policy.masked(mask_of(request))
        if not policy.grants("read"):
            return _envelope(VineError(
                E_FORBIDDEN, "'tags' requires the 'read' capability",
                hint=f"This principal holds: {sorted(policy.caps)}."), 403)

        def work(vine=None):
            try:
                if vine is None:
                    vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            try:
                # C.13.3's rule: the policy's own prefixes as SQL, so the
                # filtering happens inside the GROUP BY rather than after
                # it — a vocabulary counted globally and trimmed afterwards
                # would size regions nobody granted.
                return vine.tags(
                    policy_where=(None if policy.unrestricted
                                  else policy.sql_scope()),
                    limit=limit)
            except VineError as e:
                return e.to_dict()

        slot = reader_slot(forest, "scan")
        result = await in_lane(
            forest, slot,
            lambda: work(readers.vine(forest, slot)) if slot is not None else work())
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        registry.record(principal=principal, forest=forest, primitive="tags",
                        args={"limit": limit}, result="ok",
                        size=len(json.dumps(result, default=str)))
        return JSONResponse(result)

    # -- the uncertain links, read and voted on (J.18) -----------------------

    def _vote_gate(principal: str, forest: str, request: Request):
        """`write`, on the forest, at the caller's OWN scope (J.18).

        Not `admin`: this is a per-node frontmatter edit, and a principal
        who may write inside a branch may settle the proposals inside it.
        The scope is not narrowed here either — it rides into the engine as
        `visible`, exactly as `scan`'s does, so a link with an endpoint the
        caller cannot see is absent rather than refused with a reason that
        would name it (H.2.1 rule 6).
        """
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return None, _unknown_forest(forest)
        policy = policy.masked(mask_of(request))
        if not policy.grants("write"):
            return None, _envelope(VineError(
                E_FORBIDDEN, "settling a proposal requires the 'write' capability",
                hint=f"This principal holds: {sorted(policy.caps)}."), 403)
        return policy, None

    async def links_uncertain(request: Request) -> JSONResponse:
        """`GET /v1/forests/{forest}/links/uncertain` (J.18).

        Reviewing what is pending is reading, so a read-only Station serves
        it — and it rides the reader pool for the same reason Explore does:
        an open review console must not wait behind somebody's plant.
        """
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        unknown = [k for k in request.query_params if k not in ("after", "limit")]
        if unknown:
            return _envelope(VineError(
                E_SCHEMA, f"unknown query parameter {unknown[0]!r}",
                hint="This route accepts: after, limit."))
        raw_limit = request.query_params.get("limit")
        limit = links.DEFAULT_GROUPS
        if raw_limit is not None:
            try:
                limit = int(raw_limit)
            except ValueError:
                return _envelope(VineError(
                    E_SCHEMA, f"limit must be an integer, got {raw_limit!r}"))
        after = request.query_params.get("after")
        policy, refusal = _vote_gate(principal, forest, request)
        if refusal is not None:
            return refusal

        def work(vine=None):
            try:
                if vine is None:
                    vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            try:
                return links.uncertain_links(
                    vine, after=after, limit=limit,
                    visible=(None if policy.unrestricted else policy.in_scope))
            except VineError as e:
                return e.to_dict()

        slot = reader_slot(forest, "scan")
        result = await in_lane(
            forest, slot,
            lambda: work(readers.vine(forest, slot)) if slot is not None else work())
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        registry.record(principal=principal, forest=forest,
                        primitive="links.uncertain",
                        args={"after": after, "limit": limit},
                        result="ok", size=len(json.dumps(result, default=str)))
        return JSONResponse(result)

    async def links_vote(request: Request) -> JSONResponse:
        """`POST /v1/forests/{forest}/links/vote` (J.18, H.2.1).

        Not all-or-nothing: each vote is its own `.md` commit, its own audit
        row and its own `node.grafted`, and the response reports the outcome
        of every vote sent. Failing fifty decisions because one target had
        since been pruned would throw away work a person actually did.

        There is deliberately no MCP twin (H.2.1 rule 5): the whole point of
        a 0.3 link is that a model asserted it and something else has to
        confirm it.
        """
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        try:
            body = _json_object(await request.json() if await request.body() else {})
        except json.JSONDecodeError as e:
            return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
        policy, refusal = _vote_gate(principal, forest, request)
        if refusal is not None:
            return refusal
        if not writable:
            # J.18: reviewing what is pending is reading; settling it is a
            # commit inside the forest.
            return _envelope(VineError(
                E_READONLY, "this Station is read-only",
                hint="Start it with --writable to settle proposals."), 403)
        votes = body.get("votes")

        def work():
            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            # J.4 (v0.57): the acting principal is stamped INTO each commit,
            # never amended on afterwards — the same seam every other hosted
            # write uses.
            vine.commit_trailers = [f"station-principal: {principal}"]
            try:
                return {"votes": links.vote(
                    vine, votes,
                    visible=(None if policy.unrestricted else policy.in_scope))}
            except VineError as e:
                return e.to_dict()
            finally:
                vine.commit_trailers = []

        # The writer lane: a vote is a commit, and the pool's writer is where
        # commits happen (J.6.2).
        result = await in_forest_thread(forest, work)
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            registry.record(principal=principal, forest=forest, primitive="vote",
                            args={"votes": len(votes) if isinstance(votes, list) else 0},
                            result="error", size=0,
                            error_code=result["error"].get("code"))
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))

        counts: dict[str, int] = {}
        for record in result["votes"]:
            outcome = record["outcome"]
            counts[outcome] = counts.get(outcome, 0) + 1
            # J.4: one row per vote, because one vote is one decision about
            # one node — a row per BATCH would make an access log that
            # cannot say which link a principal settled.
            registry.record(
                principal=principal, forest=forest, primitive="vote",
                args={"id": record["id"], "rel": record["rel"],
                      "target": record["target"], "vote": record["vote"]},
                result="ok" if outcome in ("accepted", "rejected", "unchanged")
                       else "error",
                size=len(json.dumps(record, default=str)),
                commit_sha=record.get("commit"),
                # `missing` is J.3's one answer for gone AND out of scope, so
                # the row it writes is the same row for both.
                error_code=(record.get("code") if outcome == "refused"
                            else E_NOT_FOUND if outcome == "missing" else None),
            )
            if outcome in ("accepted", "rejected"):
                # J.16: identity only — the two ids and the rel. A note and
                # a summary are content and never leave with an event.
                hooks.emit(forest, "node.grafted", principal, {
                    "node": record["id"], "operations": ["vote"],
                    "rel": record["rel"], "target": record["target"],
                    "vote": record["vote"], "commit": record.get("commit"),
                })
        result["counts"] = counts
        return JSONResponse(result)

    # -- shares (J.17): a share is a key with one room -----------------------

    # Failed token lookups share the login limiter's discipline (J.17 rule
    # 6): the token space makes guessing hopeless, the limiter makes it loud.
    share_window = AuthWindow()

    _SHARE_NOT_FOUND = ("share not found",
                        "The link may have expired or been revoked.")

    def _share_not_found() -> JSONResponse:
        """ONE envelope for absent, revoked, expired and suspended (J.17
        rule 3): a share URL in the wild must not become an oracle for why
        it stopped working."""
        return _envelope(VineError(E_NOT_FOUND, *_SHARE_NOT_FOUND), 404)

    async def forest_share(request: Request):
        """`POST /v1/forests/{forest}/share {node, days?}` (J.17)."""
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return _unknown_forest(forest)
        policy = policy.masked(mask_of(request))
        if not policy.grants("read"):
            # Rule 2: a share is a delegation, and nobody delegates what
            # they do not hold.
            return _envelope(VineError(
                E_FORBIDDEN, "'share' requires the 'read' capability",
                hint=f"This principal holds: {sorted(policy.caps)}."), 403)
        try:
            body = _json_object(await request.json())
        except Exception:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("node"), str) \
                or not body["node"]:
            return _envelope(VineError(
                E_SCHEMA, "share requires a 'node' (string)"))
        node_id = body["node"]
        days = body.get("days")
        if days is not None and (isinstance(days, bool)
                                 or not isinstance(days, int)
                                 or not 1 <= days <= Registry.SHARE_MAX_DAYS):
            return _envelope(VineError(
                E_SCHEMA,
                f"days must be an integer 1..{Registry.SHARE_MAX_DAYS}",
                hint="A share always expires (J.17 rule 4)."))

        def work():
            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            if not policy.in_scope(node_id) or not vine.forest.exists(node_id):
                # Byte-identical to the gate: out of scope IS absent (J.3).
                return VineError(
                    E_NOT_FOUND, f"node not found: {node_id}",
                    hint="Use locate() to find entry points.").to_dict()
            return {}

        gate = await in_forest_thread(forest, work)
        if gate is None:
            return _unknown_forest(forest)
        if gate.get("error"):
            code = gate["error"].get("code", E_SCHEMA)
            return JSONResponse(gate, status_code=STATUS_BY_CODE.get(code, 400))
        share = registry.create_share(forest=forest, node=node_id,
                                      issuer=principal, days=days)
        record_governance(principal, "share.created",
                          {"share": share["id"], "node": node_id,
                           "days": days or Registry.SHARE_DEFAULT_DAYS},
                          "ok", forest=forest)
        # The token rides ONCE, inside the URL it exists for; no endpoint
        # returns it again (rule 5).
        return JSONResponse({"id": share["id"], "url": f"/s/{share['token']}",
                             "expires": share["expires"]})

    def _forest_admin(policy) -> bool:
        return policy is not None and policy.grants("admin") and policy.unrestricted

    async def forest_shares(request: Request):
        """`GET .../shares`: the issuer's own; all of them for the forest's
        admin — a share is a grant, and grants are visible to who governs
        the forest (J.17 rule 5). Never the token."""
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return _unknown_forest(forest)
        policy = policy.masked(mask_of(request))
        if not policy.grants("read"):
            return _envelope(VineError(
                E_FORBIDDEN, "'shares' requires the 'read' capability",
                hint=f"This principal holds: {sorted(policy.caps)}."), 403)
        issuer = None if _forest_admin(policy) else principal
        return JSONResponse({"shares": registry.shares_of(forest, issuer)})

    async def forest_share_revoke(request: Request):
        """`DELETE .../shares/{share}`: issuer or admin. A share somebody
        else issued answers as absent — nothing is disclosed."""
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        share_id = request.path_params["share"]
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return _unknown_forest(forest)
        policy = policy.masked(mask_of(request))
        rows = registry.shares_of(
            forest, None if _forest_admin(policy) else principal)
        if not any(r["id"] == share_id for r in rows):
            return _share_not_found()
        revoked = registry.revoke_share(share_id, forest)
        if revoked is None:
            return _share_not_found()
        record_governance(principal, "share.revoked",
                          {"share": share_id, "node": revoked["node"]},
                          "ok", forest=forest)
        return JSONResponse({"id": share_id, "revoked": True})

    async def share_serve(request: Request):
        """`GET /v1/share/{token}`: the shared document, no session (J.17).

        Authority is re-read at every serve (rule 3): the share must be
        live AND its issuer must still hold `read` with the node in scope —
        a lapsed grant suspends every share it issued, the moment it
        lapses. Every miss wears one byte-identical envelope.
        """
        token = request.path_params["token"]
        host = request.client.host if request.client else ""
        if share_window.over_limit("share", host):
            return _too_many_attempts()
        row = registry.resolve_share(token)
        if row is None:
            share_window.failed("share", host)
            return _share_not_found()
        policy = registry.policy_for(row["issuer"], row["forest"])
        if policy is None or not policy.grants("read") \
                or not policy.in_scope(row["node"]):
            return _share_not_found()

        def work():
            try:
                vine = pool.get(row["forest"])
            except VineError as e:
                return e.to_dict()
            try:
                node = vine.forest.read(row["node"])
            except VineError as e:
                return e.to_dict()
            body = node.body
            if node.frontmatter.get("content") in ("cached", "reference"):
                body = vine._resolved_body(node)
            return {"title": node.title, "markdown": body,
                    "outline": node.outline}

        result = await in_forest_thread(row["forest"], work)
        if result is None or result.get("error"):
            return _share_not_found()
        # Audited by share id under the issuer's authority — the reader is
        # anonymous, the authority is not (rule 6).
        registry.record(principal=row["issuer"], forest=row["forest"],
                        primitive="share", args={"share": row["id"]},
                        result="ok", size=len(result["markdown"]))
        return JSONResponse({"title": result["title"],
                             "markdown": result["markdown"],
                             "outline": result["outline"],
                             "expires": row["expires"]})

    async def share_page(request: Request):
        """`GET /s/{token}`: one address, two representations (J.17 r8).

        This was a console route, so the SPA fallback served it only to a
        request that accepts HTML — and the first thing anybody does to
        debug a share is curl it, which answered 404 while the browser
        worked. A link that works for people and 404s for machines reads as
        a broken feature.

        A document request gets the reading page; everything else gets
        exactly what `/v1/share/{token}` returns, from that same handler,
        so authority, rate limit, audit row and the byte-identical
        `E_NOT_FOUND` of every dead state are one implementation and not
        two.
        """
        if "text/html" in request.headers.get("accept", ""):
            if studio_app is not None:
                return await studio_app.get_response("index.html",
                                                     request.scope)
            return await studio_missing(request)
        return await share_serve(request)

    # -- maintenance (J.13) -------------------------------------------------

    def snapshot_dir(forest: str) -> Path:
        """Bundles are host state, beside the registry — never inside a forest.

        A snapshot in the tree would be a binary where A.3.1 keeps binaries
        out, and the next snapshot would package the previous one.
        """
        return Path(registry_path).resolve().parent / "snapshots" / forest

    async def admin_health(request: Request) -> JSONResponse:
        """The Ranger's H.3 report, relayed rather than recomputed."""
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.query_params.get("forest") or ""
        gate = admin_gate(principal, forest, request)
        if gate is not None:
            return gate
        policy = registry.policy_for(principal, forest)
        # J.13: the report counts and names things across the whole forest, so
        # a scoped principal cannot be served a filtered version — the numbers
        # would quietly describe nodes they may not see. Refused with the
        # reason, which is more useful than a half-report.
        if policy is None or not policy.unrestricted:
            return _envelope(VineError(
                E_FORBIDDEN, "the health report covers the whole forest",
                hint="It counts lint errors and names nodes everywhere, so it "
                     "needs an admin grant that is not limited to a branch."), 403)

        def work():
            from monkeyllm.ranger import Ranger

            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            # Reporting only: evaporation and promote/prune are the Ranger's
            # own scheduled run, never a side effect of opening a console.
            return Ranger(vine).health()

        result = await in_forest_thread(forest, work)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        return JSONResponse(result)

    async def admin_reindex(request: Request) -> JSONResponse:
        """Rebuild one forest's catalog from its files (J.13.3).

        The repair the whole derived layer is designed around, finally
        reachable by the operator the host layer exists for: every
        divergence in this system ends with "the files win and the catalog
        rebuilds", and until now the console said so without being able to
        do it.

        Offered by a read-only Station too. `_derived/` is not the content —
        rebuilding it plants nothing and commits nothing — and a Station
        that could never repair its own index would degrade permanently
        with no way back that does not involve a shell.
        """
        principal, err = require_principal(request)
        if err:
            return err
        try:
            body = _json_object(await request.json() if await request.body() else {})
        except json.JSONDecodeError as e:
            return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
        forest = str(body.get("forest") or request.query_params.get("forest") or "")
        gate = admin_gate(principal, forest, request)
        if gate is not None:
            return gate
        policy = registry.policy_for(principal, forest)
        # J.13.3, health's rule with one addition: the count IS the size of
        # the whole forest, and every row rewritten includes nodes a scoped
        # principal may not read.
        if policy is None or not policy.unrestricted:
            return _envelope(VineError(
                E_FORBIDDEN, "a rebuild covers the whole forest",
                hint="It rewrites the row of every node and reports how many "
                     "there are, so it needs an admin grant that is not "
                     "limited to a branch."), 403)

        def work():
            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            t0 = time.perf_counter()
            # Storage only, like `warm()` (J.6.1): no primitive runs, so no
            # trace event and no pheromone claim a caller went anywhere.
            nodes = vine.catalog.reindex()
            return {"forest": forest, "nodes": nodes,
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}

        result = await in_forest_thread(forest, work)
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        # J.6.2: the readers reopen fresh rather than trusting a held-open
        # view of an index that was just rewritten underneath them.
        readers.reset(forest)
        registry.record(principal=principal, forest=forest, primitive="reindex",
                        args={}, result="ok", size=result["nodes"])
        hooks.emit(forest, "reindex.finished", principal,
                   {"nodes": result["nodes"], "ms": result["ms"]})
        return JSONResponse(result)

    async def recurate_scent(principal: str, forest: str,
                             policy) -> JSONResponse:
        """`derive: ["scent"]` — re-curate the scent with the ingest model
        (J.13.6.1). Reached only through `admin_recurate`, which has already
        decided admin, writability and the unrestricted scope (rule 6).

        G.4.2 and G.4.3 changed a derivation that is not arithmetic, so
        every forest already ingested carries the old, thinner scent — and
        the forests that need this most are the oldest ones. It is one model
        call per node, so it is a J.9 job with everything a J.9 job has: the
        record, the stage reporting, the cancel, and the one-batch-per-forest
        lock it shares with ingest (a re-curation and an ingest write the
        same passports).
        """
        from monkeyllm.gardener import Gardener
        from monkeyllm_station import inference

        # Rule 5, and it comes first: the count is the bill. A binding that
        # is missing is decided before any of it — a job that would fall
        # back on every node spends nothing and repairs nothing, and the
        # operator would read a "done" with a forest unchanged.
        binding = registry.binding(forest, "ingest")
        if binding is None:
            return _envelope(VineError(
                E_SCHEMA,
                f"no model is bound to '{forest}' for the 'ingest' role",
                hint="Re-curating the scent is one model call per node, so "
                     "with nothing bound it would fall back on every one of "
                     "them and change nothing. Bind a model in Studio → "
                     "Models, or POST /v1/admin/models."))
        # The lock is claimed before anything is prepared, exactly as an
        # ingest claims it: both write passports, and the second one to
        # arrive must be refused rather than interleaved.
        job = board.claim(forest, RECURATE_MODE, 0, principal)
        if job is None:
            running = board.running(forest)
            return _envelope(VineError(
                E_LOCKED,
                "an ingest job is already running on this forest"
                + (f": {running.id}" if running else ""),
                hint="Watch it under GET /v1/forests/{forest}/jobs, cancel "
                     "it, or wait for it to finish."), 409)

        def prepare():
            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            curator = inference.curator_from_binding(vine, policy, binding,
                                                     propose=False)
            if curator is None:  # defensive: `binding` was read above
                return VineError(E_SCHEMA,
                                 "the ingest binding could not be opened").to_dict()
            gardener = Gardener(
                vine, hooks=[curator],
                on_stage=lambda f, st: board.note_stage(job, f, st))
            try:
                steps = gardener.recurate_scent_iter()
            except VineError as e:
                return e.to_dict()
            return {"_prepared": PreparedRecurate(
                job=job, steps=steps, curator=curator, vine=vine,
                root=Path(vine.forest.root),
                before=_git(Path(vine.forest.root), "rev-parse", "HEAD") or None,
                principal=principal, forest=forest)}

        prepared = await in_forest_thread(forest, prepare)
        if prepared is None:
            board.abandon(job)
            return _unknown_forest(forest)
        if isinstance(prepared.get("error"), dict):
            board.abandon(job)
            code = prepared["error"].get("code", E_SCHEMA)
            return JSONResponse(prepared,
                                status_code=STATUS_BY_CODE.get(code, 400))
        prep = prepared["_prepared"]
        job.total = prep.steps.total
        _launch_recurate(prep)
        # Rule 5: the number of nodes in scope, in the response that STARTS
        # the job, because it is also the number of model calls the operator
        # is about to pay for. J.10.8's rule applied to a batch — the budget
        # is said whatever chose it.
        return JSONResponse({"job": job.snapshot(), "nodes": job.total,
                             "derive": ["scent"]}, status_code=202)

    async def admin_recurate(request: Request) -> JSONResponse:
        """Re-derive what ingest derives, from the passports (J.13.6).

        `reindex` repairs what FINDS a node; `sync` repairs what a node
        SAYS by re-reading its source. This is the repair neither performs:
        a derivation rule that improved after the material was ingested.
        Every input is already in the passport, so it opens no source file,
        calls no converter and pays no model — and it was nevertheless
        reachable only through `sync`, which needs a host root and `admin`
        over it. A forest of 1,877 nodes therefore had the feature in the
        code and not in the corpus.

        Unlike `reindex` it COMMITS, so a read-only Station refuses it.
        """
        principal, err = require_principal(request)
        if err:
            return err
        try:
            body = _json_object(await request.json() if await request.body() else {})
        except json.JSONDecodeError as e:
            return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
        forest = str(body.get("forest") or request.query_params.get("forest") or "")
        gate = admin_gate(principal, forest, request)
        if gate is not None:
            return gate
        if not writable:
            return _envelope(VineError(
                E_READONLY, "this Station is read-only",
                hint="Start it with --writable to accept writes."), 403)
        policy = registry.policy_for(principal, forest)
        # J.13.6 rule 4, `reindex`'s rule: it visits every passport and the
        # count IS the forest's size, so a branch-limited admin grant is not
        # the authority for it.
        if policy is None or not policy.unrestricted:
            return _envelope(VineError(
                E_FORBIDDEN, "a re-derivation covers the whole forest",
                hint="It visits every ingested passport and reports how many "
                     "there are, so it needs an admin grant that is not "
                     "limited to a branch."), 403)
        derive = body.get("derive") or ["aliases"]
        if not isinstance(derive, list) or not all(isinstance(d, str) for d in derive):
            return _envelope(VineError(
                E_SCHEMA, "derive must be a list of strings",
                hint='e.g. {"derive": ["aliases"]}.'))
        if "scent" in derive:
            # J.13.6.1: a different contract behind the same route. The two
            # members are not mixable and the refusal is the honest answer:
            # `aliases` is arithmetic the caller waits for, `scent` is one
            # model call per node and answers 202 with a job, and ONE
            # response cannot be both. Asking twice costs nothing.
            if len(set(derive)) > 1:
                return _envelope(VineError(
                    E_SCHEMA, "'scent' cannot be combined with another derivation",
                    hint="`aliases` is passport arithmetic and the caller "
                         "waits for it; `scent` is one model call per node "
                         "and answers with a job. Send them as two calls."))
            return await recurate_scent(principal, forest, policy)

        def work():
            from monkeyllm.gardener import Gardener

            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            t0 = time.perf_counter()
            try:
                # J.4: the principal rides the commits this pass writes,
                # exactly as it rides a scoped write.
                vine.commit_trailers = [f"station-principal: {principal}"]
                out = Gardener(vine).recurate(derive)
            except VineError as e:
                return e.to_dict()
            finally:
                vine.commit_trailers = []
            out["forest"] = forest
            out["ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return out

        # The writer lane: it commits, and the caller waits (J.13.3's shape).
        result = await in_forest_thread(forest, work)
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        readers.reset(forest)
        registry.record(principal=principal, forest=forest, primitive="recurate",
                        args={"derive": derive}, result="ok",
                        size=result.get("changed", 0))
        hooks.emit(forest, "recurate.finished", principal,
                   {"scanned": result.get("scanned", 0),
                    "changed": result.get("changed", 0),
                    "derive": derive})
        return JSONResponse(result)

    # How many unrecorded names a listing spells out. The count is the
    # number an operator acts on; the names are so they can recognise them.
    STAGING_NAMES_SHOWN = 50

    async def admin_staging(request: Request) -> JSONResponse:
        """What is in the upload staging area that is not a document (J.8).

        Uploaded bytes are a courier: since v0.61 an entry that becomes a
        node has its staged file removed as it lands. What stays is a batch
        that failed conversion, a batch that was cancelled, or — on a forest
        ingested by an older Station — a document whose node was later
        pruned. Before this route none of it was visible, so it accumulated
        where nobody could see it, and once it came back to life.

        Reporting and clearing are the same resource because they are the
        same question asked twice: GET says what is there, POST removes what
        no passport records. Removal is a MOVE into the graveyard, like
        C.14's: `_derived/` is disposable, and the operator empties it.
        """
        principal, err = require_principal(request)
        if err:
            return err
        clearing = request.method == "POST"
        try:
            body = _json_object(await request.json() if (clearing and await request.body()) else {})
        except json.JSONDecodeError as e:
            return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
        forest = str(body.get("forest") or request.query_params.get("forest") or "")
        gate = admin_gate(principal, forest, request)
        if gate is not None:
            return gate
        policy = registry.policy_for(principal, forest)
        if policy is None or not policy.unrestricted:
            return _envelope(VineError(
                E_FORBIDDEN, "the staging area belongs to the whole forest",
                hint="It holds bytes headed for any branch, so it needs an "
                     "admin grant that is not limited to one."), 403)
        if clearing and not writable:
            return _envelope(VineError(
                E_READONLY, "this Station is read-only",
                hint="Start it with --writable to clear the staging area."), 403)
        if clearing:
            # A running batch is reading these files right now, and one
            # cancelled halfway leaves the rest of its bytes here.
            running = board.running(forest)
            if running is not None:
                return _envelope(VineError(
                    E_LOCKED,
                    f"an ingest job is running on this forest: {running.id}",
                    hint="Clearing would remove bytes it has not read yet. "
                         "Wait for it, or cancel it first."), 409)

        def work():
            from monkeyllm.gardener import Gardener

            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            staging = Path(vine.forest.root).joinpath(*UPLOAD_DIR)
            unrecorded = Gardener(vine, hooks=[]).unrecorded_sources(staging)
            total = sum(size for _, size in unrecorded)
            out = {"forest": forest,
                   "unrecorded": len(unrecorded),
                   "bytes": total,
                   "names": [rel for rel, _ in unrecorded[:STAGING_NAMES_SHOWN]],
                   "truncated": len(unrecorded) > STAGING_NAMES_SHOWN}
            if not clearing:
                return out
            grave = Path(vine.forest.root) / "_derived" / "graveyard" / "_staging"
            cleared = 0
            for rel, _size in unrecorded:
                src_file = staging / rel
                dest = grave / rel
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src_file), str(dest))
                    cleared += 1
                except OSError:
                    # A file that will not move is reported by the count it
                    # is missing from, never by a half-done answer.
                    continue
            out["cleared"] = cleared
            return out

        result = await in_forest_thread(forest, work)
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        if clearing:
            registry.record(principal=principal, forest=forest,
                            primitive="staging.clear", args={}, result="ok",
                            size=result.get("cleared", 0))
        return JSONResponse(result)

    def _lock_root(forest: str):
        """The forest's directory for a lock probe — containment without
        opening anything (J.13.5: a diagnostic must not need the patient
        healthy)."""
        if pool.root is not None:
            return (pool.root / forest) if _servable(forest) else None
        if pool.default is not None and forest == pool.default:
            return pool.get(None).forest.root
        return None

    def _lock_active(forest: str) -> bool:
        return any(f["id"] == forest and f.get("active")
                   for f in pool.list()["forests"])

    async def admin_locks(request: Request) -> JSONResponse:
        """The C.9 lock's state: free, orphan, or held (J.13.5).

        A probe, never an open — it asks the kernel and reads the card,
        touching no catalog and no lane. `self: true` marks the one holder
        that is not a problem: this Station's own open vine.
        """
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.query_params.get("forest") or ""
        gate = admin_gate(principal, forest, request)
        if gate is not None:
            return gate
        from monkeyllm.forest import WriterLock

        root = _lock_root(forest)
        if root is None:
            return _unknown_forest(forest)
        state = WriterLock.probe(root)
        if state["state"] == "held" and _lock_active(forest):
            state["self"] = True
        return JSONResponse({"forest": forest, **state})

    async def admin_unlock(request: Request) -> JSONResponse:
        """Remove an orphan `.vine.lock`; refuse a held one (J.13.5).

        The API cannot break a live writer's lock — two writers is the
        corruption C.9 exists to prevent, and there is no override flag.
        What it CAN do is what the old hint demanded a shell for: clear a
        file whose writer is gone, from the console, audited.
        """
        principal, err = require_principal(request)
        if err:
            return err
        try:
            body = _json_object(await request.json() if await request.body() else {})
        except json.JSONDecodeError as e:
            return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
        forest = str(body.get("forest") or request.query_params.get("forest") or "")
        gate = admin_gate(principal, forest, request)
        if gate is not None:
            return gate
        from monkeyllm.forest import WriterLock

        root = _lock_root(forest)
        if root is None:
            return _unknown_forest(forest)
        if _lock_active(forest):
            return _envelope(VineError(
                E_LOCKED, "this Station itself holds the lock",
                hint="The forest is open and serving; there is nothing to "
                     "release."), 409)
        try:
            result = WriterLock.break_orphan(root)
        except VineError as e:
            record_governance(principal, "admin.unlock",
                              {"refused": "held"}, "refused", forest=forest)
            return _envelope(e, STATUS_BY_CODE.get(e.code, 400))
        record_governance(principal, "admin.unlock",
                          {"state": result["state"],
                           "holder": result.get("holder") or {}},
                          "removed" if result.get("removed") else "kept",
                          forest=forest)
        return JSONResponse({"forest": forest, **result})

    async def admin_cache(request: Request) -> JSONResponse:
        """The answer store's switches and its economy (J.10.7).

        Per forest, behind `admin` on that forest. GET reads settings and
        stats; POST updates the settings it names, and `clear: true` empties
        the entries — which costs money, never truth. The tallies survive a
        clear: what was saved so far is history, not cache.
        """
        principal, err = require_principal(request)
        if err:
            return err
        body: dict = {}
        if request.method == "GET":
            forest = request.query_params.get("forest") or ""
        else:
            try:
                body = _json_object(await request.json() if await request.body() else {})
            except json.JSONDecodeError as e:
                return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
            forest = str(body.get("forest") or "")
        gate = admin_gate(principal, forest, request)
        if gate is not None:
            return gate

        if request.method == "POST":
            cfg = cache_settings(forest)
            if "enabled" in body:
                cfg["enabled"] = bool(body["enabled"])
            if "max_entries" in body:
                try:
                    bound = int(body["max_entries"])
                except (TypeError, ValueError):
                    return _envelope(VineError(
                        E_SCHEMA, "max_entries must be an integer"))
                if bound < 1:
                    return _envelope(VineError(
                        E_SCHEMA, "max_entries must be at least 1",
                        hint="Switch the store off with enabled: false "
                             "rather than starving it."))
                cfg["max_entries"] = bound
            if "ttl_hours" in body:
                ttl = body["ttl_hours"]
                if ttl is not None:
                    try:
                        ttl = float(ttl)
                    except (TypeError, ValueError):
                        return _envelope(VineError(
                            E_SCHEMA, "ttl_hours must be a number, or null "
                                      "to disable the hygiene sweep"))
                    if ttl <= 0:
                        return _envelope(VineError(
                            E_SCHEMA, "ttl_hours must be positive "
                                      "(null disables it)"))
                cfg["ttl_hours"] = ttl
            registry.set_setting(forest, "answer_cache", cfg)

        def work():
            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            store = answer_store.AnswerStore(Path(vine.forest.root))
            out: dict = {}
            if request.method == "POST" and body.get("clear"):
                out["cleared"] = store.clear()
            out["stats"] = store.stats()
            return out

        result = await in_forest_thread(forest, work)
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        return JSONResponse({"forest": forest,
                             "settings": cache_settings(forest), **result})

    async def admin_snapshots(request: Request) -> JSONResponse:
        """Part I over REST: take a bundle, list the ones taken.

        Restore into a live forest is absent by design (J.13): Part I
        restores into an *empty* destination, so there is nothing to offer a
        console pointed at an existing forest, and taking a filesystem
        destination from an HTTP caller would spend the Station's authority
        rather than the caller's. Import (J.13.2) is neither of those things:
        it restores into a forest that does not exist yet, at a destination
        the host derives from a validated name.
        """
        principal, err = require_principal(request)
        if err:
            return err

        if request.method == "GET":
            forest = request.query_params.get("forest") or ""
        else:
            try:
                body = _json_object(await request.json() if await request.body() else {})
            except json.JSONDecodeError as e:
                return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
            forest = str(body.get("forest") or "")
        gate = admin_gate(principal, forest, request)
        if gate is not None:
            return gate

        directory = snapshot_dir(forest)
        if request.method == "GET":
            # J.13.1 (v0.74): one snapshot is one row. A container is that
            # row on its own; a pre-v0.74 bundle keeps the second control
            # for its sidecar, because those halves are real and hiding one
            # would lose it.
            taken = sorted(
                [*directory.glob(f"*{CONTAINER_SUFFIX}"), *directory.glob("*.bundle")],
                key=lambda f: f.stat().st_mtime, reverse=True,
            ) if directory.is_dir() else []
            return JSONResponse({"snapshots": [
                {"name": b.name, "bytes": b.stat().st_size,
                 "created": _iso(b.stat().st_mtime),
                 "container": b.suffix == CONTAINER_SUFFIX,
                 "payloads": b.with_suffix(b.suffix + ".payloads.zip").is_file()}
                for b in taken]})

        def work():
            from monkeyllm.snapshot import create_snapshot

            try:
                vine = pool.get(forest)
            except VineError as e:
                return e.to_dict()
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            # Two snapshots inside the same second must not become one. The
            # name is second-resolution because a person reads it, so the
            # collision is resolved by counting rather than by borrowing
            # digits nobody wants — overwriting would silently destroy the
            # bundle somebody took a moment before doing something risky.
            out = directory / f"{forest}-{stamp}{CONTAINER_SUFFIX}"
            attempt = 2
            while out.exists():
                out = directory / f"{forest}-{stamp}-{attempt}{CONTAINER_SUFFIX}"
                attempt += 1
            try:
                # Part I (v0.74): payloads travel unless the caller says
                # otherwise. A default that loses data is not a default.
                return create_snapshot(
                    Path(vine.forest.root), out=out,
                    with_payloads=body.get("with_payloads", True) is not False)
            except VineError as e:
                return e.to_dict()

        result = await in_forest_thread(forest, work)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        registry.record(principal=principal, forest=forest, primitive="snapshot",
                        args={}, result="ok", size=result.get("bytes", 0))
        hooks.emit(forest, "snapshot.created", principal,
                   {"name": Path(result["snapshot"]).name,
                    "bytes": result["bytes"],
                    "payloads": result.get("payloads"),
                    "payloads_omitted": result.get("payloads_omitted")})
        # The absolute path is host detail; the caller gets the name it will
        # see in the listing.
        return JSONResponse({"name": Path(result["snapshot"]).name,
                             "bytes": result["bytes"],
                             "payloads": result.get("payloads"),
                             "payloads_omitted": result.get("payloads_omitted")})

    async def admin_snapshot_file(request: Request):
        """One bundle or sidecar, streamed out (J.13.1).

        Owner-only: a bundle is the whole forest with its whole history, so
        every branch scope the grant table enforces collapses the moment the
        bytes leave — there is no such thing as a scoped bundle. `admin` on
        the forest is authority over its *service*, not over every byte it
        has ever held under every other principal's scope.
        """
        principal, err = require_principal(request)
        if err:
            return err
        # J.2.6: a masked key held by the owner is refused the owner doors
        # exactly as if the bit were absent — same envelope, so the mask
        # discloses nothing about who holds the key.
        mask = mask_of(request)
        if (mask is not None and "admin" not in mask) \
                or not registry.is_owner(principal):
            return _envelope(VineError(
                E_FORBIDDEN, "downloading a snapshot requires the owner",
                hint="A bundle carries the whole forest with its full "
                     "history; no per-forest grant covers that."), 403)
        forest = request.path_params["forest"]
        name = request.path_params["file"]
        # J.8.2 posture: a name before it is a path, contained after
        # resolution. Anything the listing would not return is the same
        # not-found — never a probe into the volume.
        directory = snapshot_dir(forest).resolve()
        plausible = (FOREST_ID.match(forest)
                     and "/" not in name and "\\" not in name
                     and not name.startswith(".")
                     and (name.endswith(CONTAINER_SUFFIX)
                          or name.endswith(".bundle")
                          or name.endswith(".bundle.payloads.zip")))
        target = (directory / name).resolve() if plausible else None
        if target is None or target.parent != directory or not target.is_file():
            return _envelope(VineError(E_NOT_FOUND, "no such snapshot"), 404)
        registry.record(principal=principal, forest=forest,
                        primitive="snapshot-download", args={"file": name},
                        result="ok", size=target.stat().st_size)
        # Host state only (J.13.1): no lane, no trace, no pheromone, no
        # commit — the audit row above is the only record this leaves.
        return FileResponse(target, filename=name,
                            media_type="application/octet-stream")

    async def admin_snapshot_import(request: Request) -> JSONResponse:
        """A forest from a snapshot (J.13.2): J.7 creation, with content.

        Owner-only: an imported snapshot bypasses every converter, curation
        pass and review the J.8 surface imposes on bytes entering a forest —
        a snapshot is already forest and enters as-is. It arrives servable
        (restore rebuilds the catalog) and arrives cold: no model call, no
        canopy — `locate` stays BM25-only until an operator asks (C.6).

        The upload is a v0.74 container or a pre-v0.74 bundle, decided by
        its CONTENT (Part I): the filename came with the request, so here it
        is a claim by whoever is importing. The response says how many
        passports name a payload the snapshot did not carry — importing a
        bare bundle is allowed and produces exactly that, and the operator
        is entitled to learn it now rather than from a 404 two days later.
        """
        principal, err = require_principal(request)
        if err:
            return err
        if pool.mode != "registry":
            return _envelope(VineError(
                E_SCHEMA, "this Station serves a single forest",
                hint="Start it with --root <registry> to host more than one."))
        if not writable:
            return _envelope(VineError(
                E_READONLY, "this Station serves read-only forests",
                hint="Start it with --writable to import forests."), 403)
        # J.2.6: the owner bit is masked with 'admin', same as the download.
        mask = mask_of(request)
        if (mask is not None and "admin" not in mask) \
                or not registry.is_owner(principal):
            return _envelope(VineError(
                E_FORBIDDEN, "importing a snapshot requires the owner",
                hint="A bundle enters as-is — no converter, curation or "
                     "review sees it — so only the authority over the whole "
                     "volume may plant one."), 403)

        form = await request.form()
        forest_id = str(form.get("id") or "").strip()
        bundle = form.get("bundle")
        sidecar = form.get("payloads")
        if not FOREST_ID.match(forest_id):
            return _envelope(VineError(
                E_SCHEMA, f"invalid forest id: {forest_id!r}",
                hint="Lowercase letters, digits, '-' and '_'; up to 63 characters."))
        if bundle is None or isinstance(bundle, str):
            return _envelope(VineError(
                E_SCHEMA, "a snapshot file is required",
                hint="Send multipart/form-data with the snapshot in 'bundle'; "
                     "a pre-v0.74 snapshot adds its payload sidecar in "
                     "'payloads'."))
        target = pool.root / forest_id
        if target.exists():
            # Same rule as J.7 creation: adopting the existing forest because
            # the name matched would be an access-control bug wearing a
            # convenience feature.
            return _envelope(VineError(E_SCHEMA, f"'{forest_id}' already exists",
                                       hint="Pick another id."))

        # The body is the source (J.13.2): staged outside every forest,
        # beside the bundles the host already keeps.
        # A ceiling by default, because an unbounded upload is a way to fill
        # the volume that every other forest lives on. `0` still means no
        # limit, for a deployment that decided so — the difference is that it
        # is now decided rather than inherited.
        raw_cap = os.environ.get(IMPORT_MAX_MB_ENV)
        cap_mb = float(raw_cap) if raw_cap not in (None, "") else DEFAULT_IMPORT_MAX_MB
        incoming = Path(registry_path).resolve().parent / "snapshots" / "_incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=incoming))
        try:
            paths: dict[str, Path] = {}
            for field_name, upload in (("bundle", bundle), ("payloads", sidecar)):
                if upload is None or isinstance(upload, str):
                    continue
                suffix = "bundle" if field_name == "bundle" else "payloads.zip"
                dest = staging / f"{forest_id}.{suffix}"
                written = 0
                with dest.open("wb") as fh:
                    while chunk := await upload.read(1 << 20):
                        written += len(chunk)
                        if cap_mb and written > cap_mb * 1024 * 1024:
                            return _envelope(VineError(
                                E_SCHEMA,
                                f"snapshot exceeds this deployment's "
                                f"{cap_mb:g} MB import cap",
                                hint="MONKEYLLM_STATION_IMPORT_MAX_MB."))
                        fh.write(chunk)
                paths[field_name] = dest
            uploaded = paths["bundle"].stat().st_size

            def work():
                from monkeyllm.snapshot import restore_snapshot

                try:
                    return restore_snapshot(
                        paths["bundle"], target,
                        payload_sidecar=paths.get("payloads"))
                except VineError as e:
                    shutil.rmtree(target, ignore_errors=True)
                    return e.to_dict()
                except Exception as e:  # noqa: BLE001 — a corrupt snapshot fails the clone
                    # A half-restored tree would be a forest nobody asked
                    # for, so it is removed rather than reported as a
                    # success with a hole in it (J.7).
                    shutil.rmtree(target, ignore_errors=True)
                    return VineError(
                        E_SCHEMA, f"could not import '{forest_id}': {e}",
                        hint="Nothing was left behind; is this a Part I "
                             "snapshot?").to_dict()

            result = await in_forest_thread(forest_id, work)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))

        # A forest nobody can open is a silent failure with a 200 (J.7) —
        # and an imported one opens and warms like any other (J.6.1), best
        # effort, on the lane that will serve it.
        registry.grant(principal, forest_id, set(CAPS))
        try:
            await in_forest_thread(forest_id, lambda: pool.get(forest_id))
        except Exception:  # noqa: BLE001 — mirror the boot warm's rule
            pass
        commit = _git(target, "rev-parse", "HEAD") or None
        registry.record(principal=principal, forest=forest_id,
                        primitive="snapshot-import",
                        args={"nodes": result.get("nodes"),
                              "payloads": result.get("restored_payloads"),
                              "payloads_missing": result.get("payloads_missing")},
                        result="ok", size=uploaded, commit_sha=commit)
        return JSONResponse({"forest": {"id": forest_id, "commit": commit},
                             "nodes": result.get("nodes"),
                             "payloads": result.get("restored_payloads"),
                             "payloads_missing": result.get("payloads_missing"),
                             "grants": registry.grants_of(principal)})

    # One instance: `/s/{token}` renders the same shell without going
    # through the mount, which its own Route would otherwise shadow.
    studio_app = (StudioFiles(directory=STUDIO_DIST, html=True)
                  if (STUDIO_DIST / "index.html").is_file() else None)

    async def studio_missing(request: Request):
        return JSONResponse(
            {"error": {"code": E_NOT_FOUND, "message": "the Studio build is not present",
                       "hint": "Run `npm ci && npm run build` in apps/studio "
                               "(the Docker image does this for you)."}},
            status_code=404,
        )

    # -- the Clipper build (J.15) --------------------------------------------

    clipper_dir = Path(os.environ.get(CLIPPER_DIR_ENV) or CLIPPER_DIR)
    # (signature, bytes, etag): rebuilt when any file moves under it, so a
    # developer editing the extension is never handed yesterday's zip. The
    # signature is a stat scan — ~30 small files — not a re-read.
    clipper_cache: dict[str, object] = {}

    def _clipper_signature(src: Path) -> str:
        h = hashlib.sha256()
        for p in sorted(src.rglob("*")):
            if p.is_dir() or p.name == ".DS_Store":
                continue
            st = p.stat()
            h.update(f"{p.relative_to(src).as_posix()}\0{st.st_size}"
                     f"\0{st.st_mtime_ns}\n".encode())
        return h.hexdigest()

    def _build_clipper_zip(src: Path) -> bytes:
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(src.rglob("*")):
                if p.is_dir() or p.name == ".DS_Store":
                    continue
                # A fixed date keeps the zip reproducible: the same build
                # yields the same bytes, so the ETag means what it says.
                info = zipfile.ZipInfo(p.relative_to(src).as_posix(),
                                       date_time=(2026, 1, 1, 0, 0, 0))
                info.external_attr = 0o644 << 16
                z.writestr(info, p.read_bytes())
        return buf.getvalue()

    async def clipper_zip(request: Request) -> Response:
        """One shared build, downloadable by anybody who can see the console
        (J.15). Unauthenticated like the Studio shell it sits beside: the
        extension is public software carrying no secrets and no origin —
        pairing supplies both — and pairing is self-service (J.2.6), so
        distribution must be too, or the administrator becomes the
        gatekeeper the pair route exists to remove."""
        if not (clipper_dir / "manifest.json").is_file():
            return JSONResponse(
                {"error": {"code": E_NOT_FOUND,
                           "message": "this deployment ships no Clipper build",
                           "hint": f"Stage apps/clipper beside the Station or "
                                   f"point {CLIPPER_DIR_ENV} at a build."}},
                status_code=404)
        # Stat scan + zip both walk the filesystem: host lane, not the loop.
        def fresh():
            signature = _clipper_signature(clipper_dir)
            if clipper_cache.get("signature") != signature:
                data = _build_clipper_zip(clipper_dir)
                clipper_cache.update(
                    signature=signature, data=data,
                    etag=f'"{hashlib.sha256(data).hexdigest()[:16]}"')
            return clipper_cache["data"], clipper_cache["etag"]

        data, etag = await in_forest_thread(None, fresh)
        headers = {"ETag": etag, "Cache-Control": "no-cache",
                   "Content-Disposition":
                       'attachment; filename="monkeyllm-clipper.zip"'}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(data, media_type="application/zip", headers=headers)

    routes = [
        Route("/v1/health", health),
        Route("/v1/me", me),
        Route("/v1/forests", forests),
        Route("/v1/auth/login", auth_login, methods=["POST"]),
        # The third door (J.2.6): unauthenticated like login, rate-limited
        # like login, and what it mints is narrower than what login opens.
        Route("/v1/auth/pair", auth_pair, methods=["POST"]),
        # Registered unconditionally and gated inside, so it can close without
        # the route table being rebuilt — and so a closed setup answers with
        # the same body an unrouted path would (J.2.4).
        Route("/v1/auth/setup", auth_setup, methods=["POST"]),
        Route("/v1/admin/canopy", admin_canopy, methods=["GET", "POST"]),
        Route("/v1/admin/people", admin_people, methods=["GET", "POST"]),
        Route("/v1/admin/keys", admin_keys, methods=["GET", "POST"]),
        Route("/v1/admin/password", admin_password, methods=["POST"]),
        Route("/v1/admin/forests", admin_create_forest, methods=["POST"]),
        Route("/v1/admin/principals", admin_principals),
        Route("/v1/admin/grant", admin_grant, methods=["POST"]),
        Route("/v1/admin/audit", admin_audit),
        Route("/v1/admin/providers", admin_providers, methods=["GET", "POST"]),
        Route("/v1/admin/providers/test", admin_provider_test, methods=["POST"]),
        Route("/v1/admin/models", admin_models, methods=["GET", "POST"]),
        Route("/v1/admin/health", admin_health),
        Route("/v1/admin/cache", admin_cache, methods=["GET", "POST"]),
        Route("/v1/admin/reindex", admin_reindex, methods=["POST"]),
        Route("/v1/admin/recurate", admin_recurate, methods=["POST"]),
        Route("/v1/admin/staging", admin_staging, methods=["GET", "POST"]),
        Route("/v1/admin/locks", admin_locks),
        Route("/v1/admin/unlock", admin_unlock, methods=["POST"]),
        Route("/v1/admin/snapshots", admin_snapshots, methods=["GET", "POST"]),
        Route("/v1/admin/snapshots/import", admin_snapshot_import,
              methods=["POST"]),
        Route("/v1/admin/snapshots/{forest}/{file}", admin_snapshot_file),
        # Before the primitive catch-all, which is POST-only: these are GETs
        # of a projection, not calls of a primitive.
        # Jobs before the generic pair: `/jobs` is a literal, and the
        # `{kind}` GET below would otherwise swallow it (J.9).
        Route("/v1/forests/{forest}/jobs", jobs_list, methods=["GET"]),
        Route("/v1/forests/{forest}/webhooks", forest_webhooks,
              methods=["GET", "POST"]),
        Route("/v1/forests/{forest}/webhooks/{hook}", forest_webhook,
              methods=["GET", "POST", "DELETE"]),
        # Shares (J.17): literals before the generic {kind}/{primitive} pair.
        Route("/v1/forests/{forest}/share", forest_share, methods=["POST"]),
        Route("/v1/forests/{forest}/shares", forest_shares, methods=["GET"]),
        Route("/v1/forests/{forest}/shares/{share}", forest_share_revoke,
              methods=["DELETE"]),
        Route("/v1/share/{token}", share_serve, methods=["GET"]),
        # J.17 rule 8 (v0.59): the human spelling of the same resource.
        Route("/s/{token}", share_page, methods=["GET"]),
        Route("/v1/forests/{forest}/jobs/{job}", job_get, methods=["GET"]),
        Route("/v1/forests/{forest}/jobs/{job}/cancel", job_cancel,
              methods=["POST"]),
        # Payload bytes (J.14) before the `{kind}` GET below: Starlette
        # matches in order, and `payload/...` would otherwise be read as a
        # map projection named "payload". `:path` because node ids carry
        # slashes.
        # The progress channel (J.10.12) before the `{kind}` GET below, for
        # the reason `payload` and `export` are: Starlette matches in order,
        # and `answer/...` would otherwise read as a map projection.
        Route("/v1/forests/{forest}/answer/{run}/events", answer_events,
              methods=["GET"]),
        Route("/v1/forests/{forest}/payload/{node:path}", forest_payload,
              methods=["GET"]),
        # The document as text/markdown (J.14.1): same ordering reason and
        # the same `:path` — node ids carry slashes.
        Route("/v1/forests/{forest}/export/{node:path}", forest_export,
              methods=["GET"]),
        # J.5.18: literal before the catch-alls, and here it is not a
        # formality — `{kind:str}` is a single segment, so an unregistered
        # `/tags` would be read as a map projection and refused as one.
        Route("/v1/forests/{forest}/tags", forest_tags, methods=["GET"]),
        # J.18: literal before the catch-alls. `{kind}`/`{primitive}` are
        # single segments, so these two could not be swallowed — but the
        # ordering is the rule (J.13.6), not the accident of a slash.
        Route("/v1/forests/{forest}/links/uncertain", links_uncertain,
              methods=["GET"]),
        Route("/v1/forests/{forest}/links/vote", links_vote,
              methods=["POST"]),
        Route("/v1/forests/{forest}/{kind:str}", forest_map, methods=["GET"]),
        Route("/v1/forests/{forest}/{primitive}", primitive, methods=["POST"]),
    ]

    if mcp:
        from monkeyllm_station.mcp_surface import build_mcp_mount

        mcp_app, mcp_lifespan = build_mcp_mount(pool, registry, in_forest_thread,
                                                run_primitive, _launch_ingest,
                                                execute=execute_call)
        if mcp_app is not None:
            routes.append(Mount("/mcp", app=mcp_app))
            mcp_state["enabled"] = True

    # Before the SPA: anything under /v1 that reached here matched no route,
    # so it answers as the API rather than falling through to the static file
    # server — which would hand an HTML 404 (or, for a mistyped path, the
    # console itself) to something expecting JSON.
    async def api_not_found(request: Request) -> JSONResponse:
        return _no_such_endpoint(f"/{request.path_params['rest']}")

    routes.append(Route("/v1/{rest:path}", api_not_found,
                        methods=["GET", "POST", "PUT", "PATCH", "DELETE"]))

    # Before the SPA mount, or the catch-all would answer the download with
    # the console shell. A fixed path, not /v1: it is a static artifact like
    # the shell itself, not an API surface (J.15).
    routes.append(Route("/clipper.zip", clipper_zip, methods=["GET"]))

    # Last: the SPA catch-all must not shadow the API routes above it.
    if studio_app is not None:
        routes.append(Mount("/", app=studio_app))
    else:
        # Every console address, not just the root: a Station with no build
        # should answer a deep link with the reason it has nothing to serve
        # rather than with a bare 404 that reads like a broken route.
        routes.append(Route("/", studio_missing))
        routes.append(Route("/{rest:path}", studio_missing))

    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """C.12 rule 5: no route answers a bare 500.

        The name of the exception is the whole disclosure — no message, no
        traceback, no path, no SQL. What the caller needs is the
        classification ("this is the server's fault, not my argument"), and
        what the operator needs is in the log, where it already is.
        """
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _envelope(
            VineError(
                E_INTERNAL,
                f"the Station failed handling this request ({type(exc).__name__})",
                hint="This is a defect on the server, not in your call; the "
                     "Station's log carries the detail.",
            ),
            500,
        )

    async def refused(request: Request, exc: VineError) -> JSONResponse:
        """A `VineError` that reaches the top is still the caller's answer.

        Without this, the only registered handler was `Exception`, so a
        refusal raised outside a route's own try/except was re-labelled
        `E_INTERNAL`/500 — telling the caller "this is a defect on the
        server" about their own malformed argument. The code the refusal
        already carries decides the status (C.12).
        """
        return _envelope(exc, STATUS_BY_CODE.get(exc.code, 400))

    app = Starlette(routes=routes, lifespan=lifespan,
                    exception_handlers={VineError: refused,
                                        Exception: unhandled},
                    middleware=[Middleware(SecurityHeaders, csp=studio_csp())])
    app.state.pool = pool
    app.state.registry = registry
    # J.10.12: reachable for the same reason the job board is — a test, and
    # a future console, ask the host what is in flight without a forest.
    app.state.runs = runs
    app.state.ingest_roots = ingest_roots
    app.state.run_primitive = run_primitive
    # Exposing the pool without the threads it may be touched from was an
    # invitation to break its own invariant: a SQLite connection belongs to
    # the thread that opened it, and since boot warming the pool is rarely
    # empty. Anything reaching for `state.pool` submits through the owning
    # forest's lane (J.9: one worker thread per forest).
    app.state.forest_lane = lambda forest=None: lanes.lane(
        forest if forest and _servable(forest) else None)
    app.state.jobs = board
    # J.16: the one worker that owns every outbound request.
    app.state.webhooks = hooks
    return app
