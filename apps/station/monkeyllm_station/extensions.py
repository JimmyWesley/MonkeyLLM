# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""Part L, the Station's half (spec v0.80, L.7 and L.12).

The engine owns the **mechanism** — manifests, sources, tiers, the loader,
the worker, the conformance kit — and this module owns the **governance**:
who may install, who may enable, where a secret lives, and what an
extension is allowed to spend. That is the cut that already separates
`Vine` from `ScopedVine`, applied to Part L rather than reinvented for it.

Nothing here re-implements what `monkeyllm.extensions` does. Where this
module needs an answer the engine can give, it asks the engine — two
descriptions of one contract agree only where somebody compared them.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from monkeyllm.errors import VineError

E_EXT_QUOTA = "E_EXT_QUOTA"
E_EXT_FORBIDDEN = "E_FORBIDDEN"

SCHEMA = """
-- L.7 rule 4: config and secrets live under the host's custody, with the
-- providers table's discipline — a secret is write-only over the API, and
-- `has_value` is the only thing a read surface ever learns about it.
CREATE TABLE IF NOT EXISTS extension_config (
    ext      TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT,
    secret   INTEGER NOT NULL DEFAULT 0,
    set_at   TEXT NOT NULL,
    PRIMARY KEY (ext, key)
);

-- L.7 rule 2: enablement per forest. The forest's own `_meta/` is the
-- authority a snapshot carries; this table is the deployment's index over
-- it, so a console can answer "where is this extension enabled" without
-- opening every forest on the volume. The forest wins on disagreement.
CREATE TABLE IF NOT EXISTS extension_enablement (
    ext        TEXT NOT NULL,
    forest     TEXT NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    by         TEXT,
    at         TEXT NOT NULL,
    PRIMARY KEY (ext, forest)
);

-- L.7 rule 6: a ceiling on what an extension may spend on one forest, and
-- the running total it is measured against. Exhaustion is a REFUSAL, never
-- a silent stop — a stop nobody can distinguish from a bug is worse than
-- no ceiling at all.
CREATE TABLE IF NOT EXISTS extension_quota (
    ext        TEXT NOT NULL,
    forest     TEXT NOT NULL,
    ceiling    REAL,             -- USD per period; NULL = no ceiling
    period     TEXT NOT NULL DEFAULT 'month',
    spent      REAL NOT NULL DEFAULT 0,
    calls      INTEGER NOT NULL DEFAULT 0,
    window_key TEXT,             -- which period `spent` belongs to
    PRIMARY KEY (ext, forest)
);
"""


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _window(period: str) -> str:
    """Which period a spend belongs to. Deliberately a STRING, so a rollover
    is a different key rather than a scheduled job nobody runs."""
    if period == "day":
        return time.strftime("%Y-%m-%d")
    if period == "hour":
        return time.strftime("%Y-%m-%dT%H")
    return time.strftime("%Y-%m")


# ---------------------------------------------------------------------------
# config (L.7 rule 4)
# ---------------------------------------------------------------------------

class Config:
    """The host's custody. A secret goes in and never comes back out."""

    def __init__(self, conn):
        self.conn = conn

    def set(self, ext: str, key: str, value, secret: bool = False) -> None:
        self.conn.execute(
            "INSERT INTO extension_config (ext, key, value, secret, set_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(ext, key) DO UPDATE SET "
            "  value = excluded.value, secret = excluded.secret, "
            "  set_at = excluded.set_at",
            (ext, key, None if value is None else json.dumps(value),
             int(bool(secret)), _now()))
        self.conn.commit()

    def values(self, ext: str) -> dict:
        """Everything, secrets included — for the LOADER, never for a route.

        The engine's `register(api)` needs the real value or the extension
        cannot work; a read surface gets `readable()` instead. Keeping the
        two as separate methods is what stops a route accidentally serving
        the first one.
        """
        return {r["key"]: (None if r["value"] is None else json.loads(r["value"]))
                for r in self.conn.execute(
                    "SELECT key, value FROM extension_config WHERE ext = ?",
                    (ext,))}

    def readable(self, ext: str) -> dict:
        """What a route may serve: a secret's PRESENCE, never its value."""
        out = {}
        for row in self.conn.execute(
                "SELECT key, value, secret FROM extension_config WHERE ext = ?",
                (ext,)):
            if row["secret"]:
                out[row["key"]] = {"has_value": row["value"] is not None,
                                   "secret": True}
            else:
                out[row["key"]] = {
                    "value": None if row["value"] is None
                    else json.loads(row["value"]), "secret": False}
        return out

    def forget(self, ext: str) -> int:
        cur = self.conn.execute("DELETE FROM extension_config WHERE ext = ?",
                                (ext,))
        self.conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# enablement (L.7 rules 1 and 2)
# ---------------------------------------------------------------------------

class Enablement:
    def __init__(self, conn):
        self.conn = conn

    def set(self, ext: str, forest: str, enabled: bool, by: str) -> None:
        self.conn.execute(
            "INSERT INTO extension_enablement (ext, forest, enabled, by, at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(ext, forest) DO UPDATE SET "
            "  enabled = excluded.enabled, by = excluded.by, at = excluded.at",
            (ext, forest, int(bool(enabled)), by, _now()))
        self.conn.commit()

    def forests_for(self, ext: str) -> list[str]:
        return [r["forest"] for r in self.conn.execute(
            "SELECT forest FROM extension_enablement "
            "WHERE ext = ? AND enabled = 1 ORDER BY forest", (ext,))]

    def for_forest(self, forest: str) -> list[str]:
        return [r["ext"] for r in self.conn.execute(
            "SELECT ext FROM extension_enablement "
            "WHERE forest = ? AND enabled = 1 ORDER BY ext", (forest,))]

    def forget(self, ext: str) -> None:
        self.conn.execute("DELETE FROM extension_enablement WHERE ext = ?",
                          (ext,))
        self.conn.commit()


# ---------------------------------------------------------------------------
# quota (L.7 rule 6)
# ---------------------------------------------------------------------------

@dataclass
class QuotaState:
    ceiling: float | None
    period: str
    spent: float
    calls: int
    window: str

    def to_dict(self) -> dict:
        out = {"period": self.period, "spent": round(self.spent, 6),
               "calls": self.calls, "window": self.window}
        if self.ceiling is not None:
            out["ceiling"] = self.ceiling
            out["remaining"] = round(max(0.0, self.ceiling - self.spent), 6)
        return out


class Quota:
    """The freeze on an extension in a loop with the operator's key.

    The check runs BEFORE the provider is called and the spend is recorded
    after it, which is the only order where a ceiling means anything: a
    check after the fact is a report.
    """

    def __init__(self, conn):
        self.conn = conn

    def state(self, ext: str, forest: str) -> QuotaState:
        row = self.conn.execute(
            "SELECT ceiling, period, spent, calls, window_key FROM "
            "extension_quota WHERE ext = ? AND forest = ?",
            (ext, forest)).fetchone()
        if row is None:
            return QuotaState(None, "month", 0.0, 0, _window("month"))
        window = _window(row["period"])
        if row["window_key"] != window:
            # A new period. Rolling over on READ is what keeps the ceiling
            # true without a scheduler nobody deployed.
            return QuotaState(row["ceiling"], row["period"], 0.0, 0, window)
        return QuotaState(row["ceiling"], row["period"], float(row["spent"]),
                          int(row["calls"]), window)

    def set_ceiling(self, ext: str, forest: str, ceiling: float | None,
                    period: str = "month") -> None:
        if period not in ("hour", "day", "month"):
            raise VineError("E_SCHEMA",
                            f"unknown quota period: {period!r}",
                            hint="hour, day or month")
        self.conn.execute(
            "INSERT INTO extension_quota (ext, forest, ceiling, period, "
            "  window_key) VALUES (?,?,?,?,?) "
            "ON CONFLICT(ext, forest) DO UPDATE SET "
            "  ceiling = excluded.ceiling, period = excluded.period",
            (ext, forest, ceiling, period, _window(period)))
        self.conn.commit()

    def check(self, ext: str, forest: str) -> None:
        """Raise `E_EXT_QUOTA` when the ceiling is already reached."""
        state = self.state(ext, forest)
        if state.ceiling is None or state.spent < state.ceiling:
            return
        raise VineError(
            E_EXT_QUOTA,
            f"extension {ext!r} has reached its ceiling on {forest!r}",
            hint=f"spent {state.spent:.4f} of {state.ceiling:.4f} this "
                 f"{state.period}; the ceiling is the operator's to raise",
            data={"ext": ext, "forest": forest, **state.to_dict()})

    def record(self, ext: str, forest: str, usd: float | None) -> None:
        state = self.state(ext, forest)
        self.conn.execute(
            "INSERT INTO extension_quota (ext, forest, ceiling, period, "
            "  spent, calls, window_key) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(ext, forest) DO UPDATE SET "
            "  spent = excluded.spent, calls = excluded.calls, "
            "  window_key = excluded.window_key",
            (ext, forest, state.ceiling, state.period,
             state.spent + float(usd or 0.0), state.calls + 1, state.window))
        self.conn.commit()

    def forget(self, ext: str) -> None:
        self.conn.execute("DELETE FROM extension_quota WHERE ext = ?", (ext,))
        self.conn.commit()


# ---------------------------------------------------------------------------
# the principal trailer (L.7 rule 3)
# ---------------------------------------------------------------------------

def via(ext_id: str | None) -> str | None:
    """The audit row's `via`. One place builds the token, so no route can
    invent a second spelling of it."""
    return f"ext:{ext_id}" if ext_id else None


# ---------------------------------------------------------------------------
# the loaded set (L.3, L.7 rule 2, L.8)
# ---------------------------------------------------------------------------

class Runtime:
    """Every installed extension, loaded ONCE for the life of the process.

    Once, because installing requires a restart (L.8): a per-call load would
    give one extension several module instances and several answers to "is
    it registered", and a long-lived cache that could go stale would be a
    second opinion about what is loaded.

    Enablement is therefore not a loading question but a **use** question:
    `for_forest` returns the share of the registry that forest enabled, and
    every consumer takes that view rather than the whole thing.
    """

    def __init__(self, root=None, *, host_surfaces=None, registry=None,
                 **load_kwargs):
        self.root = root
        self.host_registry = registry
        self.registry = None
        self.report = None
        self.failed: list[dict] = []
        self.unserved: list[dict] = []
        self._host_surfaces = host_surfaces
        self._load_kwargs = load_kwargs
        self._enabled: dict[str, set[str]] = {}

    def load(self) -> "Runtime":
        from monkeyllm import extensions as engine
        from monkeyllm.extensions.api import Registry
        from monkeyllm.extensions.loader import load_all
        from monkeyllm.extensions.store import Store

        usable, why = engine.available()
        self.registry = Registry()
        if not usable:
            self.failed = [{"id": "-", "message": why or "unavailable"}]
            return self
        store = Store()
        installs = store.list()
        if not installs:
            return self
        # One broken extension never stops the others — `load_all` collects
        # failures rather than raising, which is G.2's standing rule.
        kwargs = dict(self._load_kwargs)
        if self.host_registry is not None and "config_factory" not in kwargs:
            # L.7 rule 4: on a Station the config of record is the REGISTRY's
            # — that is where custody lives — not the engine store's file.
            # Two sources would disagree the moment somebody used the
            # console, and the one the extension read would be the stale one.
            kwargs["config_factory"] = (
                lambda ext_id: (lambda: self.host_registry.ext_config
                                .values(ext_id)))
        if self.host_registry is not None and "models_factory" not in kwargs:
            # L.6: one access object per extension, so metering, quota and
            # the audit row can all name which one spent.
            kwargs["models_factory"] = (
                lambda ext_id, roles: model_access(self.host_registry,
                                                   ext_id, roles))
        self.report = load_all(installs, store, registry=self.registry,
                               host_surfaces=self._host_surfaces, **kwargs)
        self.failed = self.report.failed
        self.unserved = self.report.unserved
        return self

    # -- enablement --------------------------------------------------------

    def enabled_for(self, forest: str, forest_root) -> set[str]:
        """What this forest enables, read from ITS `_meta/` — the versioned
        copy, which is the authority a snapshot carries."""
        if forest in self._enabled:
            return self._enabled[forest]
        from monkeyllm.extensions import forestcfg
        try:
            enabled = set(forestcfg.enabled(forest_root))
        except Exception:
            enabled = set()
        self._enabled[forest] = enabled
        return enabled

    def invalidate(self, forest: str | None = None) -> None:
        """Enablement changed. Only the map is dropped; nothing reloads,
        because nothing new can be loaded without a restart."""
        if forest is None:
            self._enabled.clear()
        else:
            self._enabled.pop(forest, None)

    def for_forest(self, forest: str, forest_root):
        """The registry view this forest may act through, or None."""
        if self.registry is None:
            return None
        enabled = self.enabled_for(forest, forest_root)
        if not enabled:
            return None
        return self.registry.view(enabled)

    # -- what a console and the MCP menu need ------------------------------

    def forests_enabling(self, ext_id: str, forests) -> list[str]:
        return [f for f, root in forests
                if ext_id in self.enabled_for(f, root)]

    def loaded_ids(self) -> list[str]:
        return self.registry.extensions() if self.registry else []


# ---------------------------------------------------------------------------
# L.6 — models by role, metered, attributed
# ---------------------------------------------------------------------------

import contextvars

# The forest and principal an extension handler is running for. A contextvar
# for the same reason `PRINCIPAL` is one: `register(api)` happens ONCE at
# boot and cannot know either, while every call knows both. The host sets it
# around the handler; the extension never touches it.
EXT_CONTEXT: contextvars.ContextVar = contextvars.ContextVar(
    "monkeyllm_ext_context", default=None)


class _Bound:
    """Model access for one extension, resolved per call.

    Three things happen around the provider call and their order is the
    contract: the quota is checked BEFORE (a check afterwards is a report),
    the spend is recorded AFTER, and the audit row carries `via` with the
    HUMAN principal intact.
    """

    def __init__(self, registry, ext_id: str):
        self.registry = registry
        self.ext_id = ext_id

    def _context(self) -> tuple[str, str]:
        ctx = EXT_CONTEXT.get() or {}
        forest = ctx.get("forest") or "-"
        principal = ctx.get("principal") or "-"
        return forest, principal

    def meter(self, ext_id: str, role: str) -> None:
        forest, _principal = self._context()
        self.registry.ext_quota.check(ext_id, forest)

    def _binding(self, role: str):
        forest, principal = self._context()
        binding = self.registry.binding(forest, role)
        if binding is None:
            raise VineError(
                "E_SCHEMA",
                f"no model bound for role {role!r} on {forest!r}",
                hint="An operator binds a role in the Models console before "
                     "an extension can use it.")
        return forest, principal, binding

    def _settle(self, role: str, forest: str, principal: str,
                model_ms: float, usage: dict) -> None:
        """One place records the spend and the row, so the quota and the
        audit can never describe different calls."""
        self.registry.ext_quota.record(self.ext_id, forest, usage.get("usd"))
        try:
            # L.7 rule 3: `principal` stays whoever caused the act.
            self.registry.record(
                principal=principal, forest=forest,
                primitive=f"model.{role}", args={"ext": self.ext_id},
                result="ok", model_ms=model_ms, via=via(self.ext_id),
                cost=usage or None)
        except Exception:
            # An audit write must never fail the act it describes (J.4.2).
            pass

    def transcribe(self, role: str, audio, **kwargs):
        from monkeyllm_station.inference import transcribe_from_binding

        forest, principal, binding = self._binding(role)
        started = time.time()
        text, usage = transcribe_from_binding(binding, audio, **kwargs)
        self._settle(role, forest, principal,
                     (time.time() - started) * 1000.0, usage)
        return text

    def complete(self, role: str, messages=None, **kwargs):
        from monkeyllm_station.inference import chat_from_binding

        forest, principal, binding = self._binding(role)
        chat = chat_from_binding(binding, **{
            k: v for k, v in kwargs.items() if k in ("timeout",
                                                     "reply_tokens")})
        started = time.time()
        text = chat(messages or [])
        model_ms = (time.time() - started) * 1000.0
        usage = getattr(chat, "usage", None) or {}
        self._settle(role, forest, principal, model_ms, usage)
        return text


def model_access(registry, ext_id: str, roles: dict):
    """The `ModelAccess` an extension is handed at load (L.6).

    It never receives an endpoint, a key, or `has_key` — it receives a bound
    caller and the host keeps custody, exactly as J.10.2 already requires of
    every other consumer.
    """
    from monkeyllm.extensions.api import ModelAccess

    bound = _Bound(registry, ext_id)
    return ModelAccess(ext_id, bound.complete, roles, bound.meter,
                       transcribe=bound.transcribe)
