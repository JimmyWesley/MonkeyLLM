"""Markdown node parsing: frontmatter, outline, sections, wikilinks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from monkeyllm.errors import E_FRONTMATTER, VineError
from monkeyllm.tokens import estimate_tokens

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
HEADER_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)
FM_DELIM = "---"


@dataclass
class ParsedNode:
    id: str
    frontmatter: dict
    body: str
    path: Path | None = None
    title_from_body: str | None = None
    quote_from_body: str | None = None
    outline: list[str] = field(default_factory=list)

    @property
    def type(self) -> str:
        return str(self.frontmatter.get("type", ""))

    @property
    def is_branch(self) -> bool:
        return self.type == "branch"

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title") or self.title_from_body or self.id)

    @property
    def summary(self) -> str:
        return str(self.frontmatter.get("summary") or self.quote_from_body or "").strip()

    @property
    def body_tokens(self) -> int:
        return estimate_tokens(self.body)

    def wikilinks(self) -> list[str]:
        return [m.group(1).strip() for m in WIKILINK_RE.finditer(self.body)]


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into (frontmatter dict, body). E_FRONTMATTER on bad YAML."""
    if not text.startswith(FM_DELIM):
        raise VineError(E_FRONTMATTER, "missing frontmatter block (file must start with ---)")
    parts = text.split("\n" + FM_DELIM, 2)
    # parts[0] == '---' + yaml head fragment when delimiter on own line
    end = text.find("\n---", len(FM_DELIM))
    if end == -1:
        raise VineError(E_FRONTMATTER, "unterminated frontmatter block")
    raw_yaml = text[len(FM_DELIM): end]
    body_start = text.find("\n", end + 1)
    body = text[body_start + 1:] if body_start != -1 else ""
    try:
        fm = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise VineError(E_FRONTMATTER, f"invalid YAML frontmatter: {e}") from e
    if not isinstance(fm, dict):
        raise VineError(E_FRONTMATTER, "frontmatter must be a YAML mapping")
    return fm, body.lstrip("\n")


def extract_outline(body: str) -> tuple[str | None, str | None, list[str]]:
    """Return (first H1 title, first blockquote line, list of section headers).

    Section headers = all H2/H3 headers (the H1 is the document title).
    """
    title = None
    headers: list[str] = []
    for m in HEADER_RE.finditer(body):
        level, text = len(m.group(1)), m.group(2)
        if level == 1 and title is None:
            title = text
        elif level in (2, 3):
            headers.append(text)
    quote = None
    for line in body.splitlines():
        if line.startswith(">"):
            quote = line.lstrip("> ").strip()
            break
        if line.startswith("#") or not line.strip():
            continue
        break
    return title, quote, headers


def parse_node(node_id: str, text: str, path: Path | None = None) -> ParsedNode:
    fm, body = split_frontmatter(text)
    title, quote, headers = extract_outline(body)
    return ParsedNode(
        id=node_id,
        frontmatter=fm,
        body=body,
        path=path,
        title_from_body=title,
        quote_from_body=quote,
        outline=headers,
    )


def extract_section(body: str, section: str) -> str | None:
    """Extract one section's content by header (case-insensitive; exact
    match first, then prefix match). Returns header + content until the
    next header of same-or-higher level, or None if not found."""
    matches = list(HEADER_RE.finditer(body))
    want = section.strip().lower()
    target = None
    for m in matches:
        if m.group(2).strip().lower() == want:
            target = m
            break
    if target is None:
        for m in matches:
            if m.group(2).strip().lower().startswith(want):
                target = m
                break
    if target is None:
        return None
    level = len(target.group(1))
    start = target.start()
    end = len(body)
    for m in matches:
        if m.start() > target.start() and len(m.group(1)) <= level:
            end = m.start()
            break
    return body[start:end].rstrip()


def replace_section(body: str, header: str, new_body: str) -> str | None:
    """Replace a section's content (header line kept). None if header missing."""
    current = extract_section(body, header)
    if current is None:
        return None
    header_line = current.splitlines()[0]
    replacement = f"{header_line}\n\n{new_body.strip()}\n"
    return body.replace(current, replacement.rstrip(), 1)


def append_section(body: str, header: str, new_body: str, level: int = 2) -> str:
    hashes = "#" * level
    return body.rstrip() + f"\n\n{hashes} {header}\n\n{new_body.strip()}\n"


def serialize_node(frontmatter: dict, body: str) -> str:
    fm_yaml = yaml.safe_dump(
        frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip()
    return f"---\n{fm_yaml}\n---\n\n{body.rstrip()}\n"
