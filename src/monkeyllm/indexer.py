"""Branch (`_index.md`) maintenance (spec A.5).

Entries replicate child summaries VERBATIM; the Vine keeps them in
sync on plant/graft. Humans never edit those lines by hand.
"""

from __future__ import annotations

import datetime as dt
import re

from monkeyllm.parser import ParsedNode, extract_section, serialize_node

SUBBRANCH_SECTION = "Sub-galhos"
BANANAS_SECTION = "Bananas diretas"

_ENTRY_RE_TPL = r"^- \[\[{id}(?:\|[^\]]*)?\]\].*$"


def entry_line(node_id: str, summary: str, coverage: str | None = None) -> str:
    line = f"- [[{node_id}]] — {summary.strip()}"
    if coverage:
        line += f" {coverage}."
    return line


def _ensure_section(body: str, section: str) -> str:
    if extract_section(body, section) is not None:
        return body
    return body.rstrip() + f"\n\n## {section}\n"


def add_entry(index_node: ParsedNode, child_id: str, summary: str, *, is_branch: bool,
              coverage: str | None = None) -> str:
    """Return new index body with the child's entry added (or replaced)."""
    section = SUBBRANCH_SECTION if is_branch else BANANAS_SECTION
    body = _ensure_section(index_node.body, section)
    body = remove_entry_from_body(body, child_id)
    sec = extract_section(body, section)
    new_sec = sec.rstrip() + "\n" + entry_line(child_id, summary, coverage)
    return body.replace(sec, new_sec, 1)


def remove_entry_from_body(body: str, child_id: str) -> str:
    pattern = re.compile(_ENTRY_RE_TPL.format(id=re.escape(child_id)), re.MULTILINE)
    return pattern.sub("", body).replace("\n\n\n", "\n\n")


def sync_summary(body: str, child_id: str, new_summary: str) -> tuple[str, bool]:
    """Replace the child's entry line summary verbatim. Returns (body, changed)."""
    pattern = re.compile(_ENTRY_RE_TPL.format(id=re.escape(child_id)), re.MULTILINE)
    m = pattern.search(body)
    if not m:
        return body, False
    new_line = entry_line(child_id, new_summary)
    if m.group(0) == new_line:
        return body, False
    return body[: m.start()] + new_line + body[m.end():], True


def count_coverage(body: str) -> str:
    bananas = len(re.findall(r"^- \[\[", extract_section(body, BANANAS_SECTION) or "", re.MULTILINE))
    subs = len(re.findall(r"^- \[\[", extract_section(body, SUBBRANCH_SECTION) or "", re.MULTILINE))
    return f"{bananas} bananas, {subs} sub-galhos"


def render_index(index_node: ParsedNode, new_body: str, today: dt.date | None = None) -> str:
    fm = dict(index_node.frontmatter)
    fm["coverage"] = count_coverage(new_body)
    fm["updated"] = (today or dt.date.today()).isoformat()
    return serialize_node(fm, new_body)
