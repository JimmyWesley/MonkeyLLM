"""The forest dialect (spec Part A).

Valid node types and edge rels. The source of truth at runtime is the
forest's own `_meta/schema.md` (a living file); the constants below are
the spec v0.1 defaults, used as fallback and by the fixture builder.
Unknown `type` or `rel` on write -> E_SCHEMA.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_NODE_TYPES = {
    "galho",
    "nota",
    "documento",
    "dataset",
    "entidade",
    "conceito",
    "evento",
    "midia",
}

# rel -> derived inverse (None = no inverse)
DEFAULT_RELS: dict[str, str | None] = {
    "parte-de": "contem",
    "relacionado-com": "relacionado-com",
    "mencionado-em": "menciona",
    "autor": "autor-de",
    "comparado-com": "comparado-com",
    "derivado-de": "origem-de",
    "same-as": "same-as",
    "atalho-descoberto": None,
    "sucede": "precede",
}

ENTITY_KINDS = {"pessoa", "organizacao", "produto", "lugar", "outro"}
PAYLOAD_TYPES = {"sqlite", "pdf", "docx", "image", "audio"}
SOURCES = {"manual", "ingest", "agente"}

MAX_LINKS_PER_NODE = 50
SUMMARY_MAX_TOKENS = 60
SUMMARY_ANTI_PATTERNS = ("este documento descreve", "arquivo contendo")

_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]*)\|")


@dataclass
class Dialect:
    node_types: set[str] = field(default_factory=lambda: set(DEFAULT_NODE_TYPES))
    rels: dict[str, str | None] = field(default_factory=lambda: dict(DEFAULT_RELS))

    def inverse(self, rel: str) -> str | None:
        return self.rels.get(rel)

    @classmethod
    def load(cls, forest_root: Path) -> "Dialect":
        schema_path = forest_root / "_meta" / "schema.md"
        if not schema_path.is_file():
            return cls()
        return cls.parse(schema_path.read_text(encoding="utf-8"))

    @classmethod
    def parse(cls, schema_md: str) -> "Dialect":
        """Parse the type and rel tables from _meta/schema.md.

        Heuristic: markdown table rows whose first cell is a backticked
        token. Rows in a section mentioning 'aresta'/'rel' feed the rel
        table (second cell = inverse, '—'/'-' = none); other backticked
        rows feed node types.
        """
        node_types: set[str] = set()
        rels: dict[str, str | None] = {}
        in_rel_section = False
        for line in schema_md.splitlines():
            low = line.lower()
            if low.startswith("#"):
                in_rel_section = "aresta" in low or "rel" in low
                continue
            m = _ROW_RE.match(line.strip())
            if not m:
                continue
            token = m.group(1).strip()
            if token in ("type", "rel"):
                continue
            if in_rel_section:
                inv_raw = m.group(2).strip().strip("`")
                inv = None if inv_raw in ("", "—", "-", "–") else inv_raw
                rels[token] = inv
            else:
                node_types.add(token)
        return cls(
            node_types=node_types or set(DEFAULT_NODE_TYPES),
            rels=rels or dict(DEFAULT_RELS),
        )
