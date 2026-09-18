# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""L.1 — the extension manifest.

The manifest is the whole contract between an author and a host: what the
extension is, which hosts it fits, what it wants, and what it contributes.
Everything else in Part L reads it and nothing invents around it.

Shape is refused rather than absorbed (`extra="forbid"`, the C.8 rule for
graft patches): an unknown key beside a legal one used to mean the host
silently did less than the author asked.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from monkeyllm.errors import E_SCHEMA, VineError

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# L.6: a role says which API shape it speaks. Without it a transcriber has
# nowhere to bind, because transcription is not /chat/completions.
ROLE_KINDS = ("chat", "embed", "vision", "transcribe", "rerank")

# L.3: the catalogue. A seam absent from here is not an extension point.
SEAMS = ("converters", "curation", "events", "jobs", "tools", "routes",
         "panel", "ranking", "prompt", "roles")

# L.3: the two seams that change what the product answers, and therefore
# MUST be named in the Part D trace of every call they touch.
ATTRIBUTED_SEAMS = ("ranking", "prompt")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Permissions(_Strict):
    network: list[str] = Field(default_factory=list)
    filesystem: Literal["none", "read", "readwrite"] = "none"
    capabilities: list[str] = Field(default_factory=list)


class RoleSpec(_Strict):
    role: str
    kind: str  # one of ROLE_KINDS; validated below so the message names them
    # L.1 (v0.83): what a console says about the role on its binding card.
    # Optional, because a manifest written for v0.80 is still a manifest.
    description: str = ""

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in ROLE_KINDS:
            raise ValueError(f"kind must be one of {', '.join(ROLE_KINDS)}")
        return v

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError("role must be a lowercase identifier")
        return v


class Models(_Strict):
    requires: list[str] = Field(default_factory=list)
    registers: list[RoleSpec] = Field(default_factory=list)


class ConverterSpec(_Strict):
    extensions: list[str]
    handler: str
    heavy: bool = False

    @field_validator("extensions")
    @classmethod
    def _exts(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("a converter claims at least one file extension")
        for ext in v:
            if not ext.startswith(".") or len(ext) < 2:
                raise ValueError(f"not a file extension: {ext!r}")
        return [e.lower() for e in v]


class HandlerSpec(_Strict):
    name: str
    handler: str
    heavy: bool = False
    description: str = ""


class ConfigField(_Strict):
    type: Literal["string", "integer", "number", "boolean"] = "string"
    default: Any = None
    required: bool = False
    secret: bool = False
    description: str = ""


class Contributes(_Strict):
    converters: list[ConverterSpec] = Field(default_factory=list)
    curation: list[HandlerSpec] = Field(default_factory=list)
    events: list[HandlerSpec] = Field(default_factory=list)
    jobs: list[HandlerSpec] = Field(default_factory=list)
    tools: list[HandlerSpec] = Field(default_factory=list)
    routes: list[HandlerSpec] = Field(default_factory=list)
    ranking: list[HandlerSpec] = Field(default_factory=list)
    prompt: list[HandlerSpec] = Field(default_factory=list)
    panel: str | None = None


class Manifest(_Strict):
    id: str
    version: str
    station_compat: str
    license: str
    description: str = ""
    entry: str = "main"
    permissions: Permissions = Field(default_factory=Permissions)
    models: Models = Field(default_factory=Models)
    contributes: Contributes = Field(default_factory=Contributes)
    config: dict[str, ConfigField] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError(
                "id is 2-40 chars, lowercase letters, digits and hyphens, "
                "starting with a letter")
        return v

    @field_validator("config")
    @classmethod
    def _config(cls, v: dict) -> dict:
        for key in v:
            if not NAME_RE.match(key):
                raise ValueError(f"config key is not an identifier: {key!r}")
        return v

    # -- derived -----------------------------------------------------------

    @property
    def namespace(self) -> str:
        """L.4 rule 5: everything the extension creates begins with this."""
        return f"x_{self.id.replace('-', '_')}_"

    def secret_fields(self) -> set[str]:
        return {k for k, f in self.config.items() if f.secret}

    def config_defaults(self) -> dict:
        """L.10: what the schema says a setting is worth when nobody said.

        A declared field with no `default` is NOT a key here: `None` and
        "the operator never chose" are the same state, and manufacturing a
        null would make a worker read a setting that does not exist.
        """
        return {k: f.default for k, f in self.config.items()
                if f.default is not None}

    def required_fields(self) -> set[str]:
        return {k for k, f in self.config.items()
                if f.required and f.default is None}

    def handlers(self) -> list[tuple[str, HandlerSpec | ConverterSpec]]:
        out: list[tuple[str, Any]] = []
        for seam in ("converters", "curation", "events", "jobs", "tools",
                     "routes", "ranking", "prompt"):
            for spec in getattr(self.contributes, seam):
                out.append((seam, spec))
        return out


def parse_manifest(raw: dict) -> Manifest:
    """L.1 — refuse a manifest by naming what is wrong with it.

    A `ValidationError` traceback is not an answer an operator can act on,
    so it is translated into the envelope shape (C.12) naming the field.
    """
    if not isinstance(raw, dict):
        raise VineError(E_SCHEMA, "manifest must be a JSON object",
                        hint=f"got {type(raw).__name__}")
    try:
        return Manifest(**raw)
    except Exception as exc:  # pydantic ValidationError and friends
        problems = []
        for err in getattr(exc, "errors", lambda: [])():
            loc = ".".join(str(p) for p in err.get("loc", ())) or "manifest"
            problems.append(f"{loc}: {err.get('msg', 'invalid')}")
        raise VineError(
            E_SCHEMA,
            "manifest is not valid",
            hint="; ".join(problems[:6]) or str(exc),
            data={"problems": problems},
        ) from None


# ---------------------------------------------------------------------------
# L.1 — station_compat
# ---------------------------------------------------------------------------

_SPEC_RE = re.compile(r"^(>=|<=|==|!=|>|<)?\s*([0-9]+(?:\.[0-9]+)*)$")


def _parts(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"[0-9]+", version))


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return (a > b) - (a < b)


def compat_ok(spec: str, host_version: str) -> bool:
    """Every clause of a comma-separated range must hold.

    Deliberately tiny and dependency-free: the engine takes three runtime
    dependencies and a version range is not worth a fourth.
    """
    host = _parts(host_version)
    for clause in (c.strip() for c in spec.split(",") if c.strip()):
        m = _SPEC_RE.match(clause)
        if not m:
            raise VineError(E_SCHEMA, f"station_compat clause is unreadable: "
                                      f"{clause!r}",
                            hint="use >=, >, <=, <, ==, != and a version")
        op, ver = m.group(1) or "==", m.group(2)
        c = _cmp(host, _parts(ver))
        ok = {">=": c >= 0, ">": c > 0, "<=": c <= 0, "<": c < 0,
              "==": c == 0, "!=": c != 0}[op]
        if not ok:
            return False
    return True
