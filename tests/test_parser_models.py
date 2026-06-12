import pytest

from monkeyllm.dialect import Dialect
from monkeyllm.errors import E_FRONTMATTER, E_SCHEMA, VineError
from monkeyllm.models import validate_frontmatter, validate_summary
from monkeyllm.parser import (
    extract_section,
    parse_node,
    replace_section,
    serialize_node,
    split_frontmatter,
)

GOOD = """---
id: notes/test
type: note
title: Test
summary: Test note with enough scent to navigate.
created: 2026-06-01
updated: 2026-06-10
---

# Test

## First section

Content A.

## Second section

Content B.
"""


def fm(**over):
    base = {
        "id": "notes/test",
        "type": "note",
        "title": "Test",
        "summary": "Test note with enough scent.",
        "created": "2026-06-01",
        "updated": "2026-06-10",
    }
    base.update(over)
    return base


class TestParser:
    def test_roundtrip(self):
        front, body = split_frontmatter(GOOD)
        assert front["id"] == "notes/test"
        assert body.startswith("# Test")
        again = serialize_node(front, body)
        front2, body2 = split_frontmatter(again)
        assert front2["id"] == front["id"]

    def test_missing_frontmatter_rejected(self):
        with pytest.raises(VineError) as e:
            split_frontmatter("# no frontmatter\n")
        assert e.value.code == E_FRONTMATTER

    def test_invalid_yaml_rejected(self):
        with pytest.raises(VineError) as e:
            split_frontmatter("---\nid: [unclosed\n---\nbody")
        assert e.value.code == E_FRONTMATTER

    def test_outline(self):
        node = parse_node("notes/test", GOOD)
        assert node.outline == ["First section", "Second section"]
        assert node.title == "Test"

    def test_extract_section_exact_and_prefix(self):
        _, body = split_frontmatter(GOOD)
        assert "Content A" in extract_section(body, "first section")
        assert "Content B" in extract_section(body, "Second")
        assert extract_section(body, "nonexistent") is None

    def test_replace_section(self):
        _, body = split_frontmatter(GOOD)
        new = replace_section(body, "First section", "New content.")
        assert "New content." in new
        assert "Content A" not in new
        assert "Content B" in new


class TestFrontmatterValidation:
    def setup_method(self):
        self.dialect = Dialect()

    def test_valid(self):
        validate_frontmatter(fm(), self.dialect)

    def test_missing_required_field(self):
        bad = fm()
        del bad["summary"]
        with pytest.raises(VineError) as e:
            validate_frontmatter(bad, self.dialect)
        assert e.value.code == E_FRONTMATTER
        assert "summary" in e.value.message

    def test_unknown_type_is_schema_error(self):
        with pytest.raises(VineError) as e:
            validate_frontmatter(fm(type="meme"), self.dialect)
        assert e.value.code == E_SCHEMA

    def test_unknown_rel_is_schema_error(self):
        bad = fm(links=[{"rel": "loves", "target": "people/x"}])
        with pytest.raises(VineError) as e:
            validate_frontmatter(bad, self.dialect)
        assert e.value.code == E_SCHEMA

    def test_entity_requires_entity_kind(self):
        with pytest.raises(VineError):
            validate_frontmatter(fm(type="entity"), self.dialect)
        validate_frontmatter(fm(type="entity", entity_kind="person"), self.dialect)

    def test_max_50_links(self):
        links = [{"rel": "related-to", "target": f"n{i}"} for i in range(51)]
        with pytest.raises(VineError) as e:
            validate_frontmatter(fm(links=links), self.dialect)
        assert e.value.code == E_SCHEMA

    def test_confidence_bounds(self):
        with pytest.raises(VineError):
            validate_frontmatter(fm(confidence=1.5), self.dialect)


class TestSummarySpec:
    def test_too_long_rejected(self):
        with pytest.raises(VineError) as e:
            validate_summary("word " * 120)
        assert e.value.code == E_FRONTMATTER

    def test_anti_patterns_rejected(self):
        for bad in ("This document describes things.", "File containing data."):
            with pytest.raises(VineError):
                validate_summary(bad)

    def test_good_summary_passes(self):
        validate_summary(
            "Sales by region and SKU, Jan-Mar 2026, 14,302 rows with margin and channel."
        )


class TestDialectParsing:
    def test_parse_from_schema_md(self):
        md = (
            "# Dialect\n\n## Node types (type)\n\n"
            "| `type` | D |\n|---|---|\n| `branch` | x |\n| `note` | x |\n\n"
            "## Edge types (rel)\n\n"
            "| `rel` | Inverse |\n|---|---|\n| `part-of` | `contains` |\n| `discovered-shortcut` | — |\n"
        )
        d = Dialect.parse(md)
        assert d.node_types == {"branch", "note"}
        assert d.rels == {"part-of": "contains", "discovered-shortcut": None}
        assert d.inverse("part-of") == "contains"
