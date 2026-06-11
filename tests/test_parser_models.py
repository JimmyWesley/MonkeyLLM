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
id: notas/teste
type: nota
title: Teste
summary: Nota de teste com cheiro suficiente para navegar.
created: 2026-06-01
updated: 2026-06-10
---

# Teste

## Primeira seção

Conteúdo A.

## Segunda seção

Conteúdo B.
"""


def fm(**over):
    base = {
        "id": "notas/teste",
        "type": "nota",
        "title": "Teste",
        "summary": "Nota de teste com cheiro suficiente.",
        "created": "2026-06-01",
        "updated": "2026-06-10",
    }
    base.update(over)
    return base


class TestParser:
    def test_roundtrip(self):
        front, body = split_frontmatter(GOOD)
        assert front["id"] == "notas/teste"
        assert body.startswith("# Teste")
        again = serialize_node(front, body)
        front2, body2 = split_frontmatter(again)
        assert front2["id"] == front["id"]

    def test_missing_frontmatter_rejected(self):
        with pytest.raises(VineError) as e:
            split_frontmatter("# sem frontmatter\n")
        assert e.value.code == E_FRONTMATTER

    def test_invalid_yaml_rejected(self):
        with pytest.raises(VineError) as e:
            split_frontmatter("---\nid: [unclosed\n---\nbody")
        assert e.value.code == E_FRONTMATTER

    def test_outline(self):
        node = parse_node("notas/teste", GOOD)
        assert node.outline == ["Primeira seção", "Segunda seção"]
        assert node.title == "Teste"

    def test_extract_section_exact_and_prefix(self):
        _, body = split_frontmatter(GOOD)
        assert "Conteúdo A" in extract_section(body, "primeira seção")
        assert "Conteúdo B" in extract_section(body, "Segunda")
        assert extract_section(body, "inexistente") is None

    def test_replace_section(self):
        _, body = split_frontmatter(GOOD)
        new = replace_section(body, "Primeira seção", "Novo conteúdo.")
        assert "Novo conteúdo." in new
        assert "Conteúdo A" not in new
        assert "Conteúdo B" in new


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
        bad = fm(links=[{"rel": "ama", "target": "pessoas/x"}])
        with pytest.raises(VineError) as e:
            validate_frontmatter(bad, self.dialect)
        assert e.value.code == E_SCHEMA

    def test_entity_requires_entity_kind(self):
        with pytest.raises(VineError):
            validate_frontmatter(fm(type="entidade"), self.dialect)
        validate_frontmatter(fm(type="entidade", entity_kind="pessoa"), self.dialect)

    def test_max_50_links(self):
        links = [{"rel": "relacionado-com", "target": f"n{i}"} for i in range(51)]
        with pytest.raises(VineError) as e:
            validate_frontmatter(fm(links=links), self.dialect)
        assert e.value.code == E_SCHEMA

    def test_confidence_bounds(self):
        with pytest.raises(VineError):
            validate_frontmatter(fm(confidence=1.5), self.dialect)


class TestSummarySpec:
    def test_too_long_rejected(self):
        with pytest.raises(VineError) as e:
            validate_summary("palavra " * 120)
        assert e.value.code == E_FRONTMATTER

    def test_anti_patterns_rejected(self):
        for bad in ("Este documento descreve coisas.", "Arquivo contendo dados."):
            with pytest.raises(VineError):
                validate_summary(bad)

    def test_good_summary_passes(self):
        validate_summary(
            "Vendas por região e SKU, jan-mar 2026, 14.302 linhas com margem e canal."
        )


class TestDialectParsing:
    def test_parse_from_schema_md(self):
        md = (
            "# Dialeto\n\n## Tipos de nó (type)\n\n"
            "| `type` | D |\n|---|---|\n| `galho` | x |\n| `nota` | x |\n\n"
            "## Tipos de aresta (rel)\n\n"
            "| `rel` | Inversa |\n|---|---|\n| `parte-de` | `contem` |\n| `atalho-descoberto` | — |\n"
        )
        d = Dialect.parse(md)
        assert d.node_types == {"galho", "nota"}
        assert d.rels == {"parte-de": "contem", "atalho-descoberto": None}
        assert d.inverse("parte-de") == "contem"
