"""Normative data models (spec A.3/A.4, C.7, C.8)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from monkeyllm import dialect as dlt
from monkeyllm.errors import E_FRONTMATTER, E_SCHEMA, VineError
from monkeyllm.tokens import estimate_tokens

IMMUTABLE_FIELDS = {"id", "type", "created"}
MUTABLE_FRONTMATTER_FIELDS = {"title", "summary", "tags", "confidence"}


class Link(BaseModel):
    model_config = ConfigDict(extra="allow")

    rel: str
    target: str

    def key(self) -> tuple[str, str]:
        return (self.rel, self.target)


def _coerce_date(v: Any) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str):
        return dt.date.fromisoformat(v[:10])
    raise ValueError(f"invalid date: {v!r}")


class Frontmatter(BaseModel):
    """Required + optional frontmatter fields (A.3)."""

    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    title: str
    summary: str
    created: dt.date
    updated: dt.date

    tags: list[str] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    confidence: float = 1.0
    source: str | None = None
    payload: str | None = None
    payload_type: str | None = None
    payload_hash: str | None = None
    entity_kind: str | None = None
    aliases: list[str] = Field(default_factory=list)
    coverage: str | None = None  # branch only

    @field_validator("created", "updated", mode="before")
    @classmethod
    def _dates(cls, v: Any) -> dt.date:
        return _coerce_date(v)

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")
        return v


def validate_summary(summary: str) -> None:
    """A.4: <= 60 tokens, no scent-free anti-patterns."""
    if not summary or not summary.strip():
        raise VineError(E_FRONTMATTER, "summary: must not be empty")
    if estimate_tokens(summary) > dlt.SUMMARY_MAX_TOKENS:
        raise VineError(
            E_FRONTMATTER,
            f"summary: exceeds {dlt.SUMMARY_MAX_TOKENS} tokens "
            f"(~{estimate_tokens(summary)})",
            hint="Summaries are the scent. 1-3 sentences, <= 60 tokens.",
        )
    low = summary.strip().lower()
    for anti in dlt.SUMMARY_ANTI_PATTERNS:
        if low.startswith(anti):
            raise VineError(
                E_FRONTMATTER,
                f'summary: anti-pattern "{anti}..." wastes tokens without scent',
                hint="Start with WHAT it is (category + subject), not boilerplate.",
            )


def validate_frontmatter(fm: dict, dialect: dlt.Dialect, *, strict_summary: bool = True) -> Frontmatter:
    """Validate raw frontmatter dict against A.1-A.4. Raises VineError."""
    try:
        model = Frontmatter.model_validate(fm)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first["loc"]) or "<root>"
        raise VineError(E_FRONTMATTER, f"{loc}: {first['msg']}") from e

    if model.type not in dialect.node_types:
        raise VineError(
            E_SCHEMA,
            f"unknown node type '{model.type}'",
            hint="New types must be added to _meta/schema.md before first use.",
        )
    for link in model.links:
        if link.rel not in dialect.rels:
            raise VineError(
                E_SCHEMA,
                f"unknown rel '{link.rel}' (links -> {link.target})",
                hint="The rel table grows by editing _meta/schema.md, never ad-hoc.",
            )
    if len(model.links) > dlt.MAX_LINKS_PER_NODE:
        raise VineError(
            E_SCHEMA,
            f"node has {len(model.links)} links (max {dlt.MAX_LINKS_PER_NODE})",
            hint="A node this connected is a branch candidate (Ranger signal).",
        )
    if model.type == "entity":
        if model.entity_kind not in dlt.ENTITY_KINDS:
            raise VineError(
                E_FRONTMATTER,
                f"entity_kind: must be one of {sorted(dlt.ENTITY_KINDS)}",
            )
    if model.payload_type is not None and model.payload_type not in dlt.PAYLOAD_TYPES:
        raise VineError(E_FRONTMATTER, f"payload_type: must be one of {sorted(dlt.PAYLOAD_TYPES)}")
    if model.source is not None and model.source not in dlt.SOURCES:
        raise VineError(E_FRONTMATTER, f"source: must be one of {sorted(dlt.SOURCES)}")
    if strict_summary:
        validate_summary(model.summary)
    return model


class NodeSpec(BaseModel):
    """Input of plant() (C.7): full frontmatter + body + parent branch id."""

    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    title: str
    summary: str
    parent: str
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    confidence: float = 1.0
    source: str = "agent"
    payload: str | None = None
    payload_type: str | None = None
    payload_hash: str | None = None
    entity_kind: str | None = None
    aliases: list[str] = Field(default_factory=list)

    def frontmatter_dict(self, today: dt.date | None = None) -> dict:
        today = today or dt.date.today()
        fm: dict = {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "summary": self.summary,
            "created": today.isoformat(),
            "updated": today.isoformat(),
        }
        if self.tags:
            fm["tags"] = self.tags
        if self.links:
            fm["links"] = [{"rel": l.rel, "target": l.target} for l in self.links]
        if self.confidence != 1.0:
            fm["confidence"] = self.confidence
        fm["source"] = self.source
        for k in ("payload", "payload_type", "payload_hash", "entity_kind"):
            v = getattr(self, k)
            if v is not None:
                fm[k] = v
        if self.aliases:
            fm["aliases"] = self.aliases
        return fm


class SectionPatch(BaseModel):
    header: str
    body: str


class GraftPatch(BaseModel):
    """Input of graft() (C.8). All operations optional and combinable."""

    set_frontmatter: dict[str, Any] = Field(default_factory=dict)
    add_links: list[Link] = Field(default_factory=list)
    remove_links: list[Link] = Field(default_factory=list)
    append_section: SectionPatch | None = None
    replace_section: SectionPatch | None = None

    def is_empty(self) -> bool:
        return not (
            self.set_frontmatter
            or self.add_links
            or self.remove_links
            or self.append_section
            or self.replace_section
        )

    def summary_line(self) -> str:
        parts = []
        if self.set_frontmatter:
            parts.append("set " + ",".join(sorted(self.set_frontmatter)))
        if self.add_links:
            parts.append(f"+{len(self.add_links)} links")
        if self.remove_links:
            parts.append(f"-{len(self.remove_links)} links")
        if self.append_section:
            parts.append(f"append '{self.append_section.header}'")
        if self.replace_section:
            parts.append(f"replace '{self.replace_section.header}'")
        return "; ".join(parts) or "noop"
