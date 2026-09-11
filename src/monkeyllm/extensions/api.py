# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.3 / L.4 — the seam registry and the one object an extension is handed.

`ExtensionAPI` is **enumerated**. It exposes what Part L lists and nothing
more, and a new engine capability needs its own line here before an
extension can reach it. That is `ScopedVine`'s construction, for the same
reason: a surface that forwards whatever it is given is not a surface.

The registry keeps claims in **install order** so precedence is decidable
and stable — G.2's `discover_converters` already reads that way, and this
generalises it rather than inventing a second ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.extensions.manifest import (ATTRIBUTED_SEAMS, SEAMS, Manifest)

E_EXT_QUOTA = "E_EXT_QUOTA"


@dataclass
class Claim:
    """One contribution: which extension, which seam, what it handles."""

    ext_id: str
    seam: str
    handler: Callable
    spec: dict = field(default_factory=dict)
    heavy: bool = False

    @property
    def attributed(self) -> bool:
        """L.3: a contribution that changes what the product answers must be
        nameable in the trace, or it is not admitted."""
        return self.seam in ATTRIBUTED_SEAMS


class Registry:
    """Every claim made by every loaded extension, in install order."""

    def __init__(self) -> None:
        self._claims: list[Claim] = []
        self._roles: dict[str, dict] = {}

    def add(self, claim: Claim) -> None:
        self._claims.append(claim)

    def for_seam(self, seam: str, only: set[str] | None = None) -> list[Claim]:
        """Claims for one seam, optionally narrowed to a set of extensions.

        `only` is how enablement enters: extensions are loaded ONCE per
        process (installing requires a restart, L.8), and which of them may
        act is decided per forest at the moment of use. A second load per
        forest would give one extension two module instances and two answers
        to "is it registered".
        """
        return [c for c in self._claims
                if c.seam == seam and (only is None or c.ext_id in only)]

    def converters(self, only: set[str] | None = None) -> list[Claim]:
        return self.for_seam("converters", only)

    def tools(self, only: set[str] | None = None) -> list[Claim]:
        return self.for_seam("tools", only)

    def first(self, seam: str, only: set[str] | None = None) -> Claim | None:
        """L.3: `ranking` and `prompt` are first-claimant-wins."""
        claims = self.for_seam(seam, only)
        return claims[0] if claims else None

    def view(self, only: set[str]) -> "RegistryView":
        """A Registry-shaped window onto the extensions one forest enabled.

        Shaped like the real thing so every consumer — the Gardener's
        `discover_converters` included — takes one type and never asks
        whether it is looking at the whole deployment or one forest's share.
        """
        return RegistryView(self, set(only))

    def register_role(self, ext_id: str, role: str, kind: str) -> None:
        if role in self._roles and self._roles[role]["ext"] != ext_id:
            raise VineError(
                E_SCHEMA, f"role {role!r} is already registered by "
                          f"{self._roles[role]['ext']!r}",
                hint="a role name is a deployment-wide identifier")
        self._roles[role] = {"ext": ext_id, "kind": kind}

    def roles(self) -> dict[str, dict]:
        return dict(self._roles)

    def by_extension(self, ext_id: str) -> list[Claim]:
        return [c for c in self._claims if c.ext_id == ext_id]

    def drop(self, ext_id: str) -> None:
        self._claims = [c for c in self._claims if c.ext_id != ext_id]
        self._roles = {r: v for r, v in self._roles.items()
                       if v["ext"] != ext_id}

    def attributions(self, only: set[str] | None = None) -> list[str]:
        """L.3 — what the Part D trace must be able to name."""
        return sorted({f"ext:{c.ext_id}" for c in self._claims
                       if c.attributed and (only is None or c.ext_id in only)})

    def extensions(self) -> list[str]:
        seen = []
        for claim in self._claims:
            if claim.ext_id not in seen:
                seen.append(claim.ext_id)
        return seen


class RegistryView:
    """One forest's share of the loaded registry (L.7 rule 2).

    Not a copy: the claims are the same objects, and the only thing this
    adds is the enablement filter. A copy would be a second registry to
    keep in step with the first.
    """

    __slots__ = ("_registry", "_only")

    def __init__(self, registry: Registry, only: set[str]):
        self._registry = registry
        self._only = only

    @property
    def enabled(self) -> set[str]:
        return set(self._only)

    def for_seam(self, seam: str) -> list[Claim]:
        return self._registry.for_seam(seam, self._only)

    def converters(self) -> list[Claim]:
        return self._registry.converters(self._only)

    def tools(self) -> list[Claim]:
        return self._registry.tools(self._only)

    def first(self, seam: str) -> Claim | None:
        return self._registry.first(seam, self._only)

    def roles(self) -> dict[str, dict]:
        return {r: v for r, v in self._registry.roles().items()
                if v["ext"] in self._only}

    def by_extension(self, ext_id: str) -> list[Claim]:
        return (self._registry.by_extension(ext_id)
                if ext_id in self._only else [])

    def attributions(self) -> list[str]:
        return self._registry.attributions(self._only)

    def extensions(self) -> list[str]:
        return [e for e in self._registry.extensions() if e in self._only]


class ModelAccess:
    """L.6 — the extension never receives an endpoint, a key, or `has_key`.

    It receives a bound caller. The host owns the binding, the custody and
    the meter; the extension owns the question.
    """

    def __init__(self, ext_id: str, complete: Callable | None,
                 roles: dict[str, dict], meter: Callable | None = None,
                 transcribe: Callable | None = None):
        self._ext = ext_id
        self._complete = complete
        self._transcribe = transcribe
        self._roles = roles
        self._meter = meter

    def available(self) -> list[str]:
        return sorted(self._roles)

    def _check(self, role: str) -> None:
        if role not in self._roles:
            raise VineError(
                E_SCHEMA, f"no model bound for role {role!r}",
                hint="an operator binds a role before an extension can use it")
        if self._meter is not None:
            self._meter(self._ext, role)      # L.7 rule 6, before the spend

    def complete(self, role: str, **kwargs) -> Any:
        """A chat turn. `kind: "chat"` / `"vision"` roles."""
        self._check(role)
        if self._complete is None:
            raise VineError(E_SCHEMA,
                            "this host binds no models",
                            hint="bind the role, or run on a host that does")
        return self._complete(role=role, **kwargs)

    def transcribe(self, role: str, audio, **kwargs) -> str:
        """Audio to text, for a role whose `kind` is `transcribe`.

        A separate method rather than a `complete` with different arguments
        because it is a different API: transcription is a multipart upload
        to a different path, and pretending one shape covers both would put
        the difference in a caller's arguments where the binding cannot see
        it (L.6's reason for `kind`).

        `audio` is a path the extension already holds — the host reads it
        and posts it; the extension never sees an endpoint or a key.
        """
        self._check(role)
        if self._transcribe is None:
            raise VineError(
                E_SCHEMA, "this host cannot transcribe",
                hint="bind a role whose kind is 'transcribe', on a host that "
                     "serves one")
        return self._transcribe(role=role, audio=audio, **kwargs)


class ExtensionAPI:
    """L.4 — the enumerated surface. Six members, and they are the contract."""

    def __init__(self, manifest: Manifest, registry: Registry, *,
                 config: dict | None = None, vine: Any = None,
                 models: ModelAccess | None = None, log: Any = None,
                 config_provider: Callable | None = None):
        self._manifest = manifest
        self._registry = registry
        self._sealed = False
        self._config = dict(config or {})
        # Config is read LIVE where a host can supply it. An extension is
        # loaded once (installing requires a restart, L.8) but its settings
        # are edited while it runs, and a snapshot taken at load would make
        # the console's Save a lie until the next restart — the one thing
        # L.8's honesty rule exists to prevent, arriving from the other
        # side.
        self._config_provider = config_provider
        self.vine = vine
        self.models = models or ModelAccess(manifest.id, None, {})
        self.log = log
        self.namespace = manifest.namespace

    # -- 1. contribute -----------------------------------------------------

    def contribute(self, seam: str, handler: Callable, **spec) -> None:
        """The only way to claim a seam. Claims outside `register` are
        refused: an extension that can register later is an extension whose
        surface nobody can enumerate."""
        if self._sealed:
            raise VineError(
                E_SCHEMA,
                f"{self._manifest.id}: contribute() outside register()",
                hint="every claim is made during activation")
        if seam not in SEAMS:
            raise VineError(
                E_SCHEMA, f"unknown seam: {seam!r}",
                hint=f"the catalogue is {', '.join(SEAMS)}")
        if not callable(handler):
            raise VineError(E_SCHEMA,
                            f"{seam} handler is not callable")
        name = spec.get("name")
        if seam in ("tools", "routes") and name:
            # L.4 rule 5: named outside the namespace refuses, never renamed
            # silently — a renamed tool is a tool nobody's client can call.
            if not str(name).startswith(self.namespace):
                raise VineError(
                    E_SCHEMA,
                    f"{seam} name {name!r} is outside the extension's "
                    f"namespace",
                    hint=f"names begin with {self.namespace!r}")
        self._registry.add(Claim(ext_id=self._manifest.id, seam=seam,
                                 handler=handler, spec=dict(spec),
                                 heavy=bool(spec.get("heavy"))))

    @property
    def config(self) -> dict:
        if self._config_provider is None:
            return self._config
        try:
            live = self._config_provider()
        except Exception:
            return self._config
        return {**self._config, **(live or {})}

    # -- housekeeping ------------------------------------------------------

    def seal(self) -> None:
        self._sealed = True

    def secret(self, key: str) -> str | None:
        """L.7 rule 4 — readable by the extension, never by a read surface."""
        if key not in self._manifest.secret_fields():
            raise VineError(E_SCHEMA,
                            f"{key!r} is not declared a secret in the manifest")
        return self.config.get(key)
