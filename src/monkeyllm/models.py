"""Normative data models (spec A.3/A.4, C.7, C.8)."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from monkeyllm import dialect as dlt
from monkeyllm.errors import E_FRONTMATTER, E_SCHEMA, VineError
from monkeyllm.tokens import estimate_tokens

IMMUTABLE_FIELDS = {"id", "type", "created"}
MUTABLE_FRONTMATTER_FIELDS = {"title", "summary", "tags", "confidence"}

# C.7.1 dataset planting (spec v0.8): the model never writes DDL — the schema
# is data, validated whole, and the Vine generates the CREATE TABLEs itself.
DATASET_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,63}$")
DATASET_COLUMN_TYPES = {"TEXT", "INTEGER", "REAL", "BLOB"}
MAX_DATASET_TABLES = 10
MAX_DATASET_COLUMNS = 50


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


class TableSchema(BaseModel):
    """One table of a C.7.1 declarative dataset schema."""

    columns: dict[str, str]
    primary_key: list[str] = Field(default_factory=list)


def validate_dataset_rows(schema: dict[str, TableSchema],
                          rows: dict[str, list[list]]) -> None:
    """C.7.1 rule 7 (v0.9): initial rows must fit the declared schema."""
    for tname, table_rows in rows.items():
        if tname not in schema:
            raise VineError(
                E_SCHEMA, f"rows: table '{tname}' is not declared in schema"
            )
        width = len(schema[tname].columns)
        for i, row in enumerate(table_rows):
            if not isinstance(row, (list, tuple)) or len(row) != width:
                raise VineError(
                    E_SCHEMA,
                    f"rows: {tname}[{i}] has {len(row) if isinstance(row, (list, tuple)) else 'non-list'}"
                    f" values (table has {width} columns)",
                )


def validate_dataset_schema(schema: dict[str, TableSchema]) -> None:
    """C.7.1: names regex-checked, types allowlisted, limits enforced."""
    if not schema:
        raise VineError(E_SCHEMA, "schema: must declare at least one table")
    if len(schema) > MAX_DATASET_TABLES:
        raise VineError(E_SCHEMA, f"schema: max {MAX_DATASET_TABLES} tables per dataset")
    for tname, table in schema.items():
        if not DATASET_NAME_RE.fullmatch(tname):
            raise VineError(
                E_SCHEMA,
                f"schema: invalid table name '{tname}'",
                hint="Names must match ^[a-z_][a-z0-9_]*$ (<= 64 chars).",
            )
        if not table.columns:
            raise VineError(E_SCHEMA, f"schema: table '{tname}' has no columns")
        if len(table.columns) > MAX_DATASET_COLUMNS:
            raise VineError(
                E_SCHEMA, f"schema: table '{tname}' exceeds {MAX_DATASET_COLUMNS} columns"
            )
        for cname, ctype in table.columns.items():
            if not DATASET_NAME_RE.fullmatch(cname):
                raise VineError(
                    E_SCHEMA,
                    f"schema: invalid column name '{cname}' in table '{tname}'",
                    hint="Names must match ^[a-z_][a-z0-9_]*$ (<= 64 chars).",
                )
            if ctype.upper() not in DATASET_COLUMN_TYPES:
                raise VineError(
                    E_SCHEMA,
                    f"schema: invalid type '{ctype}' for {tname}.{cname}",
                    hint=f"Allowed types: {sorted(DATASET_COLUMN_TYPES)}.",
                )
        for pk in table.primary_key:
            if pk not in table.columns:
                raise VineError(
                    E_SCHEMA,
                    f"schema: primary_key '{pk}' is not a column of '{tname}'",
                )


def dataset_ddl(schema: dict[str, TableSchema]) -> list[str]:
    """Generate the CREATE TABLE statements from a validated schema."""
    stmts = []
    for tname, table in schema.items():
        cols = [f"{c} {t.upper()}" for c, t in table.columns.items()]
        if table.primary_key:
            cols.append("PRIMARY KEY (" + ", ".join(table.primary_key) + ")")
        stmts.append(f"CREATE TABLE {tname} ({', '.join(cols)})")
    return stmts


def dataset_manual(schema: dict[str, TableSchema]) -> str:
    """Auto `## Query manual` body section (C.7.1) — feeds C.2's query_manual."""
    lines = ["## Query manual", "", "Tables:"]
    for tname, table in schema.items():
        cols = ", ".join(f"{c} {t.upper()}" for c, t in table.columns.items())
        lines.append(f"- `{tname}({cols})`")
    lines += ["", "Example queries:"]
    for tname in schema:
        lines.append(f"- `SELECT * FROM {tname} LIMIT 5`")
        lines.append(f"- `SELECT COUNT(*) FROM {tname}`")
    return "\n".join(lines)


class NodeSpec(BaseModel):
    """Input of plant() (C.7): full frontmatter + body + parent branch id."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

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
    # C.7.1: declarative dataset schema ("schema" on the wire; aliased because
    # pydantic reserves the bare name). Creation directive, not frontmatter.
    table_schema: dict[str, TableSchema] | None = Field(default=None, alias="schema")
    # C.7.1 rule 7 (v0.9): initial rows per table, loaded parameterized at birth
    rows: dict[str, list[list]] | None = None

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
        # extra="allow": custom frontmatter fields pass through (e.g. the
        # Gardener's source_path/source_hash, spec G.1)
        for k, v in (self.model_extra or {}).items():
            if k not in fm and v is not None:
                fm[k] = v
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
