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
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

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


def _server_timing(clocks: dict) -> str:
    """The host's own clocks as the standard header (J.10.6).

    A body is the agent's context window and it is budgeted in tokens, so
    the console's instruments travel outside it: the header costs the
    response nothing and a browser's network panel already draws it.

    Shape only, like a trace — three durations, no ids, no counts — so a
    timing can never say more than the response it rides on.
    """
    return ", ".join(f"{name};dur={clocks[name]}"
                     for name in ("vine", "model", "host") if name in clocks)


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
) -> Starlette:
    pool = ForestPool(root=Path(root), writable=writable)
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
        # The owner bit (J.2.4) is authority over every forest present and
        # future, so it answers before the grants are even read — including
        # when there are no forests, which is the state it exists for.
        if registry.is_owner(principal):
            return True
        grants = registry.grants_of(principal)
        if forest is not None:
            grants = [g for g in grants if g["forest"] == forest]
        return any("admin" in g["caps"] for g in grants)

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
                      clocks: dict | None = None):
        """Executed on the forest thread: resolve, scope, call, attribute.

        `clocks`, when a caller supplies one, is filled with the three
        durations of J.10.6: the engine, the provider round trip when there
        was one, and whatever is left of the host's span — policy, the audit
        record, serialisation, the thread hop. An out-parameter rather than a
        second return value, because the MCP surface calls this too and has
        no header to carry them: a timing is the console's channel, never the
        agent's.

        The engine figure is read off the tracer, so it is the same slice
        J.10.4 already reports and not a second instrumentation.
        """
        span = time.perf_counter()
        sample: dict = {}
        try:
            return dispatch(principal, forest, name, payload, sample)
        finally:
            if clocks is not None:
                tracer, mark = sample.get("tracer"), sample.get("mark", 0)
                engine = float(sum(e["elapsed_ms"] for e in tracer.events[mark:])
                               if tracer is not None else 0.0)
                model = sample.get("model")
                clocks["vine"] = round(engine, 3)
                if model is not None:
                    clocks["model"] = round(model, 3)
                # The remainder, floored at zero: three clocks that add up to
                # the span, so subtracting them from a client's stopwatch
                # leaves transport and nothing else.
                clocks["host"] = round(max(0.0, (time.perf_counter() - span) * 1000
                                           - engine - (model or 0.0)), 3)

    def dispatch(principal: str, forest: str, name: str, payload: dict,
                 sample: dict):
        """The call itself. `sample` is where it leaves what it alone knows:
        the tracer to read the engine's clock off, and the provider's."""
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return None
        try:
            vine = pool.get(forest)
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
        mark = len(vine.tracer.events)
        # Where the engine's own clock starts for this call (J.10.6). Read
        # after the fact rather than accumulated here, so there is still only
        # one instrumentation and it is Part D's.
        sample.update(tracer=vine.tracer, mark=mark)

        if name in COMPOSITES or name in HOST_ACTIONS:
            runner = run_composite if name in COMPOSITES else run_ingest
            result = runner(principal, forest, vine, policy, name, payload)
            if isinstance(result, dict):
                sample["model"] = result.get("model_ms")
            if name in EXPLAINED:
                result = explain(result, vine, mark)
                if name in COMPOSITES and isinstance(result, dict) and "error" not in result:
                    billed = cost_of(result, registry.binding(forest, COMPOSITES[name][1]) or {})
                    if billed:
                        result["cost"] = billed
            registry.record(
                principal=principal, forest=forest, primitive=name, args=payload,
                result="error" if isinstance(result.get("error"), dict) else "ok",
                size=len(json.dumps(result, default=str)),
                commit_sha=result.get("commit"),
            )
            return result

        root_path = Path(vine.forest.root)
        before = _git(root_path, "rev-parse", "HEAD") if name in WRITE_PRIMITIVES else None
        result = ScopedVine(vine, policy).call(name, **payload)
        if name in EXPLAINED:
            result = explain(result, vine, mark)

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

    def explain(result: dict, vine, mark: int) -> dict:
        """Attach what the call actually did, step by step (J.10.4).

        A composite is opaque from outside: `answer` is one request and six
        forest calls plus a provider round trip, and "it took 1.8 s" says
        nothing about which of those to fix. The engine already times every
        primitive it runs (Part D), so this is a slice of that trace — the
        events this call appended — not a second instrumentation.

        Only the shape of the work is reported: the primitive, the node when
        the primitive takes one, the milliseconds and the tokens it emitted.
        No arguments and no content, so a trace can never disclose what a
        scoped response withheld.
        """
        if not isinstance(result, dict) or "error" in result:
            return result
        steps = [
            {"step": e["primitive"], "ms": e["elapsed_ms"], "tokens": e["tokens_out"],
             **({"id": e["id"]} if e["id"] else {})}
            for e in vine.tracer.events[mark:]
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
                question = payload.get("question") or payload.get("query") or ""
                k = int(payload.get("k", 3))
                # J.10.5: hops are opt-in and cost one model call each, so the
                # sweep stays the default. `hops: true` means "use the budget
                # you would have picked"; a number sets it.
                hops = payload.get("hops")
                if hops:
                    return inference.forage(
                        scoped, question, binding, k=k,
                        max_hops=6 if hops is True else int(hops))
                return inference.answer(scoped, question, binding, k=k)
            return inference.recurate(scoped, payload.get("id"), binding)
        except VineError as e:
            return e.to_dict()
        except Exception as e:  # provider outages must not 500 the Station
            return VineError(E_SCHEMA, f"{name} failed: {e}"[:300]).to_dict()

    def stage_upload(root: Path, files: list) -> tuple[Path, list[str]]:
        """Write uploaded documents into the forest's staging directory.

        Each name is resolved and then checked to still be *under* the
        staging root. Inspecting the string for `..` would miss symlinks and
        absolute paths; comparing the resolved paths cannot.

        An entry carries either `text` (UTF-8 source) or `b64` (the raw
        bytes). The Gardener's `.docx`/`.xlsx` converters read bytes, so a
        text-only upload path left them reachable from a shell and from
        nowhere else — the operator with only a browser is exactly who this
        surface exists for (J.8).
        """
        staging = root.joinpath(*UPLOAD_DIR)
        staging.mkdir(parents=True, exist_ok=True)
        written = []
        for entry in files:
            if not isinstance(entry, dict):
                raise VineError(E_SCHEMA, "each file must be an object "
                                          "{name, text|b64}")
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
        return staging, written

    def run_ingest(principal, forest, vine, policy, _name, payload) -> dict:
        """The Gardener over REST (J.8), with the host's three additions:
        the `ingest` capability, a scope check on where it may write, and a
        staging area for operators who have a browser and no shell."""
        from monkeyllm.gardener import Gardener, discover_hooks
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
        dest = (payload.get("dest") or "").strip("/") or None
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
        try:
            if mode == "upload":
                files = payload.get("files")
                if not isinstance(files, list) or not files:
                    return VineError(
                        E_SCHEMA, "upload needs a non-empty 'files' list",
                        hint='Each entry is {"name": "notes.md", "text": "…"} '
                             'or {"name": "report.docx", "b64": "…"}.').to_dict()
                source, staged = stage_upload(root, files)

            curator = inference.curator_from_binding(
                vine, policy, registry.binding(forest, "ingest"))
            # Accepting a reviewed draft replaces the model's curation with
            # the reviewer's, as an ordinary `on_curate` hook (J.8.1). The
            # Curator object is still built — `rollup` below is a different
            # write about a different node — but it does not curate this one
            # again: it would answer differently, and what shipped would then
            # not be what was approved.
            hooks = discover_hooks()
            if approved is not None:
                hooks.append(compose.approval_hook(approved, vine, policy))
            elif curator is not None:
                hooks.append(curator)
            gardener = Gardener(vine, hooks=hooks, dry_run=stage)

            if mode == "upload" and gardener.config.get("source_root") == \
                    Path(source).resolve().as_posix():
                # The staging area is stable per forest, so re-sending a
                # filename means "this document changed". `adopt` would plant a
                # second node beside the first; the Gardener's update path is
                # the G.8 hash diff, which is exactly what `sync` runs.
                #
                # `dest` is carried through: this is still an upload, and the
                # operator picked a destination for THESE files. Letting the
                # config's dest win would file every later batch wherever the
                # first one went, without saying so. Comparing resolved paths
                # keeps the flip working when the forest root reaches the
                # Station through a symlink — otherwise adopt runs twice and
                # plants a duplicate of every staged document.
                mode, report = "sync", gardener.sync(source, dest=dest)
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
                            return denied.to_dict()
                report = gardener.sync(source, path=payload.get("path"))
            else:
                report = gardener.adopt(source, dest=dest)
            rollup = gardener.rollup(curator) if (curator and not stage) else None
        except VineError as e:
            return e.to_dict()
        except Exception as e:
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

    def run_ingest_status(principal: str, forest: str):
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

    def run_map(principal: str, forest: str, kind: str, params: dict):
        """A whole region in one payload, under the caller's own policy.

        Executed on the forest thread like every other forest touch. This is
        not a primitive and grants nothing new: every id it returns is one
        the same principal could reach through `look`, and the filtering is
        `policy.in_scope` — the same predicate `ScopedVine` applies node by
        node (J.3). What it adds is shape, which a per-node walk cannot give
        without asking once per node.
        """
        policy = registry.policy_for(principal, forest)
        if policy is None:
            return None
        if not policy.grants("read"):
            return VineError(
                E_FORBIDDEN, f"'{kind}' requires the 'read' capability",
                hint=f"This principal holds: {sorted(policy.caps)}.").to_dict()
        try:
            vine = pool.get(forest)
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
                "body_tokens, payload, payload_type, updated "
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
                "updated": row["updated"],
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

    async def health(request: Request) -> JSONResponse:
        # `password_login` lets the console decide whether to offer the door
        # at all. It reveals that a door exists, not who may walk through it.
        # `setup_required` is the same kind of fact: which of the two
        # pre-identity screens the console must render (J.5.6). Deciding that
        # locally is how a console ends up offering a sign-in form on a
        # Station nobody can sign in to.
        return JSONResponse({
            "status": "ok", "mode": pool.mode, "writable": writable,
            "setup_required": setup_open(),
            "password_login": super_admin is not None or registry.has_any_password(),
        })

    def effective_grants(principal: str) -> list[dict]:
        """The principal's grants as policy resolves them.

        For everyone this is the grant table. For the owner (J.2.4) there is
        no grant table to read — the authority is a bit — so the forests the
        pool currently holds are projected as full-capability grants. Both
        `/v1/me` and `/v1/forests` read from here, because a console that saw
        an owner with zero forests would render an empty product for the one
        principal who may do everything.
        """
        if not registry.is_owner(principal):
            return registry.grants_of(principal)
        return [{"forest": f["id"], "caps": sorted(CAPS), "allow": [""],
                 "deny": [], "tables": {}}
                for f in pool.list()["forests"]]

    async def me(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        grants = effective_grants(principal)
        for g in grants:
            policy = registry.policy_for(principal, g["forest"])
            g["roots"] = policy.roots() if policy else []
        return JSONResponse({"principal": principal, "grants": grants,
                             "admin": is_admin(principal),
                             "owner": registry.is_owner(principal)})

    async def forests(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        granted = {g["forest"]: g for g in effective_grants(principal)}
        listed = []
        for f in pool.list()["forests"]:
            if f["id"] not in granted:
                continue
            policy = registry.policy_for(principal, f["id"])
            listed.append({**f, "caps": granted[f["id"]]["caps"],
                           "roots": policy.roots() if policy else []})
        return JSONResponse({"forests": listed, "mode": pool.mode})

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
        theirs = {g["forest"] for g in registry.grants_of(target)}
        mine = {g["forest"] for g in registry.grants_of(principal)
                if "admin" in g["caps"]}
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
            body = await request.json()
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
        return JSONResponse({"key": session["key"], "principal": username,
                             "expires_at": session["expires_at"],
                             "admin": True, "owner": True})

    async def auth_login(request: Request) -> JSONResponse:
        """Password in, session token out (J.2.1).

        The session is an ordinary API key with a short life, so everything
        downstream — authenticate, policy, audit — is the single path it
        already was. The door decides how the principal was established,
        never what it may do.
        """
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return _envelope(VineError(E_SCHEMA, "invalid JSON body"))
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")

        ok = False
        if username and password:
            if super_admin and secrets.compare_digest(username, super_admin[0]):
                # Break-glass: compared against the environment, never stored.
                ok = secrets.compare_digest(password, super_admin[1])
            else:
                ok = registry.verify_password(username, password)
        if not ok:
            # One message for a wrong password, an unknown user and a user
            # with no password at all: distinguishing them would turn the
            # login form into a directory of who exists.
            return _envelope(VineError(E_FORBIDDEN, "invalid username or password"), 401)

        session = registry.open_session(username)
        return JSONResponse({"key": session["key"], "principal": username,
                             "expires_at": session["expires_at"],
                             "admin": is_admin(username),
                             "owner": registry.is_owner(username)})

    async def admin_keys(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        if not is_admin(principal):
            return _envelope(VineError(E_FORBIDDEN, "requires the 'admin' capability"), 403)

        if request.method == "GET":
            # Only principals this caller fully administers — the same rule
            # that governs issuing, applied to seeing (J.2.2).
            visible = [p["id"] for p in registry.principals()
                       if administers_fully(principal, p["id"])]
            return JSONResponse({"keys": registry.keys_of(visible),
                                 "principals": visible})

        body = await request.json()
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
        return JSONResponse({"api_key": key, "principal": target,
                             "keys": registry.keys_of([target])})

    async def admin_password(request: Request) -> JSONResponse:
        principal, err = require_principal(request)
        if err:
            return err
        body = await request.json()
        target = str(body.get("principal") or "").strip()
        if not target or not administers_fully(principal, target):
            return _envelope(VineError(
                E_FORBIDDEN, "requires 'admin' on every forest that principal holds"), 403)
        if super_admin and target == super_admin[0]:
            return _envelope(VineError(
                E_FORBIDDEN, "the environment account has no stored password",
                hint="Rotate MONKEYLLM_STATION_PASSWORD and restart."), 403)
        registry.set_password(target, body.get("password") or None)
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
        body = await request.json() if request.method == "POST" else {}
        if not forest:
            forest = body.get("forest")
        if not is_admin(principal, forest):
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
                vine.build_canopy()
            return {**vine.canopy_status,
                    "enabled": registry.setting(forest, "gauntlet", True)}

        status = await in_forest_thread(work)
        if status is None:
            return _unknown_forest(forest)
        if "error" in status:
            return JSONResponse(status, status_code=400)
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
        if not is_admin(principal):
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

        body = await request.json()
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
                    if not is_admin(principal, forest):
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
                if not is_admin(principal, forest):
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
        if not is_admin(principal):
            return _envelope(
                VineError(E_FORBIDDEN, "creating a forest requires the 'admin' "
                                       "capability on an existing forest"), 403)
        body = await request.json()
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
            info = await in_forest_thread(create)
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
        result = await in_forest_thread(
            lambda: run_primitive(principal, forest, name, payload, clocks)
        )
        timing = _server_timing(clocks)
        if result is None:
            response = _unknown_forest(forest)
            response.headers["Server-Timing"] = timing
            return response
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
        if not is_admin(principal):
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
        # An audit entry records what somebody read. Same rule as J.3.2:
        # over-fetch, then keep only the forests this caller governs, so a
        # short page is a short page rather than a leak.
        mine = administered(principal)
        entries = [e for e in registry.audit(
            limit=limit * 4, principal=request.query_params.get("principal"))
            if e["forest"] in mine]
        return JSONResponse({"entries": entries[:limit]})

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

    async def forest_map(request: Request) -> JSONResponse:
        """`GET /v1/forests/{forest}/graph` and `.../trails` (J.11)."""
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.path_params["forest"]
        kind = request.path_params["kind"]
        if kind == "ingest":
            # The GET beside the POST: what a refresh would re-read (J.8).
            result = await in_forest_thread(
                lambda: run_ingest_status(principal, forest))
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
        result = await in_forest_thread(
            lambda: run_map(principal, forest, kind, params))
        if result is None:
            return _unknown_forest(forest)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        return JSONResponse(result)

    # -- maintenance (J.13) -------------------------------------------------

    def snapshot_dir(forest: str) -> Path:
        """Bundles are host state, beside the registry — never inside a forest.

        A `.bundle` in the tree would be a binary where A.3.1 keeps binaries
        out, and the next snapshot would package the previous one.
        """
        return Path(registry_path).resolve().parent / "snapshots" / forest

    async def admin_health(request: Request) -> JSONResponse:
        """The Ranger's H.3 report, relayed rather than recomputed."""
        principal, err = require_principal(request)
        if err:
            return err
        forest = request.query_params.get("forest") or ""
        if not forest or not is_admin(principal, forest):
            return _envelope(VineError(
                E_FORBIDDEN, "requires the 'admin' capability on that forest"), 403)
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

        result = await in_forest_thread(work)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        return JSONResponse(result)

    async def admin_snapshots(request: Request) -> JSONResponse:
        """Part I over REST: take a bundle, list the ones taken.

        Restore is absent by design (J.13): Part I restores into an *empty*
        destination, so there is nothing to offer a console pointed at a live
        forest, and taking a filesystem destination from an HTTP caller would
        spend the Station's authority rather than the caller's.
        """
        principal, err = require_principal(request)
        if err:
            return err

        if request.method == "GET":
            forest = request.query_params.get("forest") or ""
        else:
            try:
                body = await request.json() if await request.body() else {}
            except json.JSONDecodeError as e:
                return _envelope(VineError(E_SCHEMA, f"invalid JSON body: {e}"))
            forest = str(body.get("forest") or "")
        if not forest or not is_admin(principal, forest):
            return _envelope(VineError(
                E_FORBIDDEN, "requires the 'admin' capability on that forest"), 403)

        directory = snapshot_dir(forest)
        if request.method == "GET":
            bundles = sorted(directory.glob("*.bundle"), reverse=True) \
                if directory.is_dir() else []
            return JSONResponse({"snapshots": [
                {"name": b.name, "bytes": b.stat().st_size,
                 "created": _iso(b.stat().st_mtime),
                 "payloads": b.with_suffix(b.suffix + ".payloads.zip").is_file()}
                for b in bundles]})

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
            out = directory / f"{forest}-{stamp}.bundle"
            attempt = 2
            while out.exists():
                out = directory / f"{forest}-{stamp}-{attempt}.bundle"
                attempt += 1
            try:
                return create_snapshot(
                    Path(vine.forest.root), out=out,
                    with_payloads=bool(body.get("with_payloads")))
            except VineError as e:
                return e.to_dict()

        result = await in_forest_thread(work)
        if isinstance(result.get("error"), dict):
            code = result["error"].get("code", E_SCHEMA)
            return JSONResponse(result, status_code=STATUS_BY_CODE.get(code, 400))
        registry.record(principal=principal, forest=forest, primitive="snapshot",
                        args={}, result="ok", size=result.get("bytes", 0))
        # The absolute path is host detail; the caller gets the name it will
        # see in the listing.
        return JSONResponse({"name": Path(result["bundle"]).name,
                             "bytes": result["bytes"],
                             "payloads": result.get("payloads")})

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
        Route("/v1/auth/login", auth_login, methods=["POST"]),
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
        Route("/v1/admin/snapshots", admin_snapshots, methods=["GET", "POST"]),
        # Before the primitive catch-all, which is POST-only: these are GETs
        # of a projection, not calls of a primitive.
        Route("/v1/forests/{forest}/{kind:str}", forest_map, methods=["GET"]),
        Route("/v1/forests/{forest}/{primitive}", primitive, methods=["POST"]),
    ]

    if mcp:
        from monkeyllm_station.mcp_surface import build_mcp_mount

        mcp_app, mcp_lifespan = build_mcp_mount(pool, registry, in_forest_thread,
                                                run_primitive)
        if mcp_app is not None:
            routes.append(Mount("/mcp", app=mcp_app))

    # Before the SPA: anything under /v1 that reached here matched no route,
    # so it answers as the API rather than falling through to the static file
    # server — which would hand an HTML 404 (or, for a mistyped path, the
    # console itself) to something expecting JSON.
    async def api_not_found(request: Request) -> JSONResponse:
        return _no_such_endpoint(f"/{request.path_params['rest']}")

    routes.append(Route("/v1/{rest:path}", api_not_found,
                        methods=["GET", "POST", "PUT", "PATCH", "DELETE"]))

    # Last: the SPA catch-all must not shadow the API routes above it.
    if (STUDIO_DIST / "index.html").is_file():
        routes.append(Mount("/", app=StaticFiles(directory=STUDIO_DIST, html=True)))
    else:
        routes.append(Route("/", studio_missing))

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.pool = pool
    app.state.registry = registry
    app.state.ingest_roots = ingest_roots
    app.state.run_primitive = run_primitive
    return app
