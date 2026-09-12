# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.3 — an extension's converter, wearing G.2's `Converter` protocol.

The Gardener already knows how to rank claimants for a file extension; an
extension does not need a second mechanism, it needs to look like the ones
that exist. So this adapter presents `extensions` and `convert(path)` and
nothing else.

A heavy handler answers across a pipe, so it answers in JSON — which means
the adapter must accept a plain dict and build the `Conversion` itself. That
is not a convenience: `Conversion` is a dataclass in the host's interpreter
and the worker cannot construct one.
"""

from __future__ import annotations

from pathlib import Path

from monkeyllm.errors import VineError


class ExtensionConverter:
    """One `converters` claim, adapted to G.2."""

    def __init__(self, claim, on_error=None):
        self.claim = claim
        self.ext_id = claim.ext_id
        self.extensions = set(claim.spec.get("extensions") or ())
        self.heavy = claim.heavy
        self._on_error = on_error

    def __repr__(self) -> str:  # what a report names
        return f"<ExtensionConverter {self.ext_id} {sorted(self.extensions)}>"

    def convert(self, path: Path):
        from monkeyllm.gardener import Conversion
        result = self.claim.handler(str(path))
        if isinstance(result, Conversion):
            return result
        if isinstance(result, dict):
            allowed = {f for f in Conversion.__dataclass_fields__}
            unknown = sorted(set(result) - allowed)
            if unknown:
                raise VineError(
                    "E_EXT_WORKER",
                    f"{self.ext_id}: conversion carries unknown field(s): "
                    f"{', '.join(unknown)}",
                    hint=f"a conversion carries {', '.join(sorted(allowed))}")
            return Conversion(**result)
        raise VineError("E_EXT_WORKER",
                        f"{self.ext_id}: converter returned "
                        f"{type(result).__name__}, not a conversion")


def from_registry(registry, on_error=None) -> list[ExtensionConverter]:
    """Install order is precedence order (L.3); the registry already keeps
    claims in it, so this is a projection and never a re-sort."""
    return [ExtensionConverter(c, on_error) for c in registry.converters()]
