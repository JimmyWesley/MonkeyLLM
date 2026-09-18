# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Branch (`_index.md`) maintenance (spec A.5).

Entries replicate child summaries VERBATIM; the Vine keeps them in
sync on plant/graft. Humans never edit those lines by hand.
"""

from __future__ import annotations

import datetime as dt
import re

from monkeyllm.parser import ParsedNode, extract_section, serialize_node

SUBBRANCH_SECTION = "Sub-branches"
BANANAS_SECTION = "Direct bananas"

# A.5 (v0.84): how many entries a section RENDERS before it stops.
#
# Nothing capped this file. An entry is an id plus the child's summary copied
# verbatim, and A.4 caps a summary at 60 tokens, so a branch with ten
# thousand children rendered as roughly 800,000 tokens in the one file every
# reader of that region opens — a document no primitive's budget was ever
# going to contain, produced by a mirror doing exactly what it was told.
#
# **The cap is on the rendering and never on the truth.** Above it the
# section ends with ONE line stating how many entries are not shown and
# naming the call that enumerates them, and `count_coverage` reads that
# number back — so `coverage:` still counts every child, `look`, `scan` and
# `coverage()` are untouched, and the wall never lies about itself. It does
# not replace `needs_split` (150): that is advice to a human at the point a
# region stops being legible, and this is the wall that keeps an un-split
# region from becoming a file that breaks every reader of it.
INDEX_ENTRIES_MAX = 500

_ENTRY_RE_TPL = r"^- \[\[{id}(?:\|[^\]]*)?\]\].*$"
_ENTRY_RE = re.compile(r"^- \[\[", re.MULTILINE)
_OVERFLOW_RE = re.compile(r"^_\u2026 and (\d+) more[^\n]*_$", re.MULTILINE)


def entry_line(node_id: str, summary: str, coverage: str | None = None) -> str:
    line = f"- [[{node_id}]] — {summary.strip()}"
    if coverage:
        line += f" {coverage}."
    return line


def overflow_line(count: int) -> str:
    """The one line a capped section ends with (A.5, v0.84).

    It names `scan`, which pages through the catalog and has been the
    enumeration route since C.6.2 — a wall that does not say where the rest
    is would just be a truncation.
    """
    return (f"_\u2026 and {count} more not shown here; enumerate every child "
            f'with scan(parent_id, after="")._')


def _section_state(sec: str) -> tuple[int, int]:
    """`(entries rendered, entries counted but not shown)` for one section."""
    rendered = len(_ENTRY_RE.findall(sec or ""))
    m = _OVERFLOW_RE.search(sec or "")
    return rendered, int(m.group(1)) if m else 0


def _with_overflow(sec: str, count: int) -> str:
    """The section with its overflow line set to `count`. One line, always."""
    m = _OVERFLOW_RE.search(sec)
    if m:
        return sec[: m.start()] + overflow_line(count) + sec[m.end():]
    return sec.rstrip() + "\n" + overflow_line(count)


def ensure_section(body: str, section: str) -> str:
    if extract_section(body, section) is not None:
        return body
    return body.rstrip() + f"\n\n## {section}\n"


def _header_only(sec: str) -> bool:
    """A section that is its heading and nothing else."""
    return len(sec.strip().splitlines()) == 1


def add_entry(index_node: ParsedNode, child_id: str, summary: str, *, is_branch: bool,
              coverage: str | None = None) -> str:
    """Return new index body with the child's entry added (or replaced).

    Under `INDEX_ENTRIES_MAX` this is v0.83's append, to the byte. At the cap
    the entry is COUNTED and not rendered: the wall is on the rendering, and
    the count is what `count_coverage` reads back, so the branch's own claim
    about its size stays exact (A.5, v0.84).
    """
    section = SUBBRANCH_SECTION if is_branch else BANANAS_SECTION
    body = ensure_section(index_node.body, section)
    body = remove_entry_from_body(body, child_id)
    sec = extract_section(body, section)
    rendered, overflow = _section_state(sec)
    if rendered >= INDEX_ENTRIES_MAX:
        new_sec = _with_overflow(sec, overflow + 1)
    else:
        line = entry_line(child_id, summary, coverage)
        if overflow:
            # Keep the overflow line last: it is the section's closing
            # sentence, not one of its entries.
            m = _OVERFLOW_RE.search(sec)
            assert m is not None
            new_sec = sec[: m.start()] + line + "\n" + sec[m.start():]
        else:
            # A.5: a blank line between the heading and the first entry.
            # Markdown wants one — CommonMark reads `## Direct bananas`
            # followed immediately by `- [[…]]` as a heading and a list, but
            # every round trip through a renderer puts the blank line back,
            # so a forest rendered without it could not be opened in the
            # Studio editor's rich mode without the editor proposing a
            # change nobody made (measured: 12 of the fixture's 82 bodies
            # and 28 of the bench forest's 154, all of them `_index`).
            # Entries after the first already have their separator, so this
            # is the ONE place the gap can be missing. Nothing READS the
            # gap: `_ENTRY_RE` is per line and `extract_section` is by
            # heading, so both spellings parse identically and no existing
            # forest changes until the next entry lands in an empty section.
            gap = "\n\n" if _header_only(sec) else "\n"
            new_sec = sec.rstrip() + gap + line
    return body.replace(sec, new_sec, 1)


def remove_entry_from_body(body: str, child_id: str) -> str:
    pattern = re.compile(_ENTRY_RE_TPL.format(id=re.escape(child_id)), re.MULTILINE)
    return pattern.sub("", body).replace("\n\n\n", "\n\n")


def sync_summary(body: str, child_id: str, new_summary: str,
                 coverage: str | None = None) -> tuple[str, bool]:
    """Replace the child's entry line summary verbatim. Returns (body, changed).

    `coverage` preserves the sub-branch coverage suffix (A.5, spec v0.13):
    without it a sync rewrite would silently drop `. N bananas, ...`."""
    pattern = re.compile(_ENTRY_RE_TPL.format(id=re.escape(child_id)), re.MULTILINE)
    m = pattern.search(body)
    if not m:
        return body, False
    new_line = entry_line(child_id, new_summary, coverage)
    if m.group(0) == new_line:
        return body, False
    return body[: m.start()] + new_line + body[m.end():], True


def count_coverage(body: str) -> str:
    """The branch's own claim about its size — every child, never every line.

    A.5 (v0.84): above `INDEX_ENTRIES_MAX` a section renders the cap and
    then says how many more there are, and this reads BOTH. Counting the
    rendered lines alone would make the wall lie about itself in the one
    field C.1 and C.2 read for the size of a region.
    """
    counts = []
    for section in (BANANAS_SECTION, SUBBRANCH_SECTION):
        rendered, overflow = _section_state(extract_section(body, section) or "")
        counts.append(rendered + overflow)
    return f"{counts[0]} bananas, {counts[1]} sub-branches"


_COVERAGE_RE = re.compile(r"^(\d+) bananas?, (\d+) sub-branch(?:es)?\.?$")


def parse_coverage(text: str | None) -> dict | None:
    """C.1/C.2 (v0.54): machine fields carry numbers. The prose stays in
    the index bodies; API payloads report `{notes, branches}`. None for
    anything the render above did not produce — the caller then omits the
    field rather than serving a sentence as data."""
    m = _COVERAGE_RE.match((text or "").strip())
    if not m:
        return None
    return {"notes": int(m.group(1)), "branches": int(m.group(2))}


def render_index(index_node: ParsedNode, new_body: str, today: dt.date | None = None) -> str:
    fm = dict(index_node.frontmatter)
    fm["coverage"] = count_coverage(new_body)
    fm["updated"] = (today or dt.date.today()).isoformat()
    return serialize_node(fm, new_body)
