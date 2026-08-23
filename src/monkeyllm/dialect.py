# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The forest dialect (spec Part A).

Valid node types and edge rels. The source of truth at runtime is the
forest's own `_meta/schema.md` (a living file); the constants below are
the spec v0.5 defaults, used as fallback and by the fixture builder.
Unknown `type` or `rel` on write -> E_SCHEMA.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_NODE_TYPES = {
    "branch",
    "note",
    "document",
    "dataset",
    "entity",
    "concept",
    "event",
    "media",
}

# rel -> derived inverse (None = no inverse)
DEFAULT_RELS: dict[str, str | None] = {
    "part-of": "contains",
    "related-to": "related-to",
    "mentioned-in": "mentions",
    "author": "author-of",
    "compared-with": "compared-with",
    "derived-from": "origin-of",
    "same-as": "same-as",
    "discovered-shortcut": None,
    "succeeds": "precedes",
    # A.2 (v0.58): the judgement, distinct from succeeds' timeline — the
    # successor makes the predecessor history, and the sweep suppresses
    # the target by default (C.6c.4).
    "supersedes": "superseded-by",
}

# How many declared tokens a refusal spells out before it starts counting.
# A forest may declare more than a hint can carry; a hint that scrolls is
# not a hint, and the count is what tells the reader to go read the file.
DECLARED_IN_HINT = 20


def declared_hint(names, kind: str) -> str:
    """A.2 (v0.61): a refusal for an undeclared token names the set.

    The forest's own `_meta/schema.md` is the authority at runtime, so a
    rel the engine ships may legitimately be absent from a given forest —
    a forest created before `supersedes` existed declares nine rels and
    refuses the tenth, which is A.2 working as designed. What was not
    working is that the refusal said only which token was wrong, in the
    one case where naming the accepted set answers the question
    completely (C.12: every refusal carries an actionable hint).
    """
    listed = sorted(names)
    shown = ", ".join(listed[:DECLARED_IN_HINT])
    more = len(listed) - DECLARED_IN_HINT
    if more > 0:
        shown += f" (+{more} more)"
    return (f"This forest declares these {kind}: {shown}. "
            f"The table grows by editing _meta/schema.md, never ad-hoc.")


ENTITY_KINDS = {"person", "organization", "product", "place", "other"}
PAYLOAD_TYPES = {"sqlite", "pdf", "docx", "image", "audio"}
SOURCES = {"manual", "ingest", "agent"}

MAX_LINKS_PER_NODE = 50
SUMMARY_MAX_TOKENS = 60
SUMMARY_ANTI_PATTERNS = ("this document describes", "file containing")

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
        token. Rows in a section mentioning 'edge'/'rel' feed the rel
        table (second cell = inverse, '—'/'-' = none); other backticked
        rows feed node types.
        """
        node_types: set[str] = set()
        rels: dict[str, str | None] = {}
        in_rel_section = False
        for line in schema_md.splitlines():
            low = line.lower()
            if low.startswith("#"):
                in_rel_section = "edge" in low or "rel" in low
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
