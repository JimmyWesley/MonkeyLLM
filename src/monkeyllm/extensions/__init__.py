# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Part L — extensions (spec v0.80).

The public face of the extension runtime. **The mechanism is the engine's;
the governance is the Station's** (L.12), so everything here works on an
engine-only host: an operator with `pip install monkeyllm` installs
extensions, and that is required rather than incidental — a capability
reachable only through the AGPL host would make every extension author a
client of that host.

Import safety is part of the contract (L.12, F.187). `available()` answers
whether this build can run extensions and says why not when it cannot;
`load_for_forest` returns an empty report rather than raising. Today the
`extensions` extra adds no third-party dependency — the guard exists so that
adding one later cannot turn a base install into an import error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = [
    "available", "load_for_forest", "expected_but_absent", "Registry",
    "Store", "install", "update", "uninstall", "plan", "run_kit",
    "TIER_VERIFIED", "TIER_SIGNED", "TIER_UNVERIFIED",
]

_REASON: str | None = None

try:  # pragma: no cover - exercised by the absent-extra path
    from monkeyllm.extensions.api import Registry
    from monkeyllm.extensions.conformance import run_kit
    from monkeyllm.extensions.installer import (install, plan, uninstall,
                                              update)
    from monkeyllm.extensions.loader import load_all
    from monkeyllm.extensions.sources import (TIER_SIGNED, TIER_UNVERIFIED,
                                              TIER_VERIFIED)
    from monkeyllm.extensions.store import Store
    from monkeyllm.extensions import forestcfg
except Exception as exc:  # pragma: no cover
    _REASON = f"{type(exc).__name__}: {exc}"
    Registry = Store = None            # type: ignore[assignment]
    install = update = uninstall = plan = run_kit = load_all = None  # type: ignore
    forestcfg = None                   # type: ignore[assignment]
    TIER_VERIFIED, TIER_SIGNED, TIER_UNVERIFIED = "verified", "signed", "unverified"


def available() -> tuple[bool, str | None]:
    """(usable, why not). A host asks once and behaves accordingly."""
    return (_REASON is None), _REASON


def expected_but_absent(forest_root: Path, store: Any = None) -> list[str]:
    """L.12 — what this forest expects and this deployment does not have.

    The reason `validate` reports it: without this line an `.mp3` is
    converted by the built-in stub, the node is planted, nothing errors, and
    nobody is told that the extension which was supposed to transcribe it is
    not here.
    """
    if _REASON is not None:
        return []
    store = store or Store()
    installed = {record.id for record in store.list()}
    return [ext for ext in forestcfg.enabled(forest_root)
            if ext not in installed]


def load_for_forest(forest_root: Path, *, store: Any = None,
                    host_surfaces: set[str] | None = None, **kwargs):
    """Load exactly what this forest enables. Never raises for a bad
    extension: `load_all` collects failures, because one broken extension
    must not stop the others (G.2's standing rule)."""
    if _REASON is not None:
        return None
    store = store or Store()
    enabled = set(forestcfg.enabled(forest_root))
    installs = [r for r in store.list() if r.id in enabled]
    return load_all(installs, store, host_surfaces=host_surfaces, **kwargs)
