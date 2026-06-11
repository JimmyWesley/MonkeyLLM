"""Part G (spec v0.9): the Gardener — adopt, sync, converters, hooks."""

import subprocess
import sys
import textwrap

import pytest

from monkeyllm.forest import Forest, init_forest
from monkeyllm.gardener import Gardener, derive_summary
from monkeyllm.lint import lint_forest
from monkeyllm.vine import Vine

VISAO_MD = textwrap.dedent("""\
    # Visão Geral

    O projeto Maracatu controla sensores industriais no Nordeste e integra
    os dados de campo com o ERP central. A meta de 2026 é dobrar a frota
    monitorada sem aumentar o time de operação.

    ## Detalhes

    Mais texto aqui sobre telemetria e manutenção preditiva.
    """)

CLIENTES_CSV = textwrap.dedent("""\
    nome,cidade,valor
    Acme Indústria,Recife,1250.50
    Beta Comércio,Olinda,300
    Gama Serviços,Caruaru,87.25
    """)

CONTRATOS_JSON = '[{"contrato": "CT-01", "cliente": "Acme", "ano": 2026},' \
                 ' {"contrato": "CT-02", "cliente": "Beta", "ano": 2025}]'


@pytest.fixture()
def source_tree(tmp_path):
    src = tmp_path / "dump"
    (src / "notas").mkdir(parents=True)
    (src / "dados").mkdir()
    (src / "notas" / "visao.md").write_text(VISAO_MD, encoding="utf-8")
    (src / "notas" / "leiame.txt").write_text(
        "Pasta de notas operacionais do projeto Maracatu.", encoding="utf-8")
    (src / "dados" / "clientes.csv").write_text(CLIENTES_CSV, encoding="utf-8")
    (src / "dados" / "contratos.json").write_text(CONTRATOS_JSON, encoding="utf-8")
    (src / "relatorio.bin").write_bytes(b"\x00\x01\x02")
    return src


@pytest.fixture()
def garden(tmp_path):
    root = tmp_path / "floresta"
    init_forest(root, title="Floresta de Teste")
    vine = Vine(root, writable=True)
    g = Gardener(vine, hooks=[])
    yield g, vine, root
    vine.close()


class TestAdopt:
    def test_adopt_mirrors_tree(self, garden, source_tree):
        g, vine, root = garden
        report = g.adopt(source_tree)

        assert sorted(report["branches"]) == ["dados/_index", "notas/_index"]
        assert sorted(report["planted"]) == [
            "dados/clientes", "dados/contratos", "notas/leiame", "notas/visao"]
        assert report["unsupported"] == ["relatorio.bin"]
        assert not report["errors"]

        # G.1: passports carry source_path + source_hash
        node = vine.forest.read("notas/visao")
        assert node.frontmatter["source_path"] == "notas/visao.md"
        assert len(node.frontmatter["source_hash"]) == 64
        assert node.frontmatter["source"] == "ingest"
        assert "Maracatu" in node.frontmatter["summary"]

        # F.13: the adopted forest lints clean and git carries no binary
        issues = lint_forest(Forest(root))
        assert not [i for i in issues if i.level == "error"]
        out = subprocess.run(["git", "-C", str(root), "ls-files"],
                             capture_output=True, text=True, check=True)
        assert not [f for f in out.stdout.split()
                    if f.endswith((".db", ".csv", ".bin", ".json"))]

    def test_csv_becomes_queryable_dataset(self, garden, source_tree):
        g, vine, _ = garden
        g.adopt(source_tree)
        q = vine.query("dados/clientes", "SELECT COUNT(*) FROM clientes")
        assert q["rows"][0][0] == 3
        # type inference: valor is numeric, SUM works
        q2 = vine.query("dados/clientes", "SELECT SUM(valor) FROM clientes")
        assert abs(q2["rows"][0][0] - 1637.75) < 0.01
        # tabular json too
        q3 = vine.query("dados/contratos",
                        "SELECT cliente FROM contratos WHERE ano = 2026")
        assert q3["rows"][0][0] == "Acme"

    def test_adopt_is_recorded_in_config(self, garden, source_tree):
        g, _, root = garden
        g.adopt(source_tree)
        assert (root / "_meta" / "gardener.yaml").is_file()
        assert Gardener(g.vine).config["source_root"] == source_tree.resolve().as_posix()


class TestSync:
    def test_sync_classifies_new_changed_deleted(self, garden, source_tree):
        g, vine, _ = garden
        g.adopt(source_tree)

        # curated frontmatter must survive a sync (G.3)
        vine.graft("notas/visao", {"set_frontmatter": {
            "summary": "Resumo curado pelo humano, intocável pelo sync."}})

        (source_tree / "notas" / "visao.md").write_text(
            VISAO_MD + "\n## Novidade\n\nFrota ampliada para 900 sensores.\n",
            encoding="utf-8")
        (source_tree / "notas" / "novo.md").write_text(
            "# Novo\n\nNota recém-criada na fonte.", encoding="utf-8")
        (source_tree / "notas" / "leiame.txt").unlink()

        report = g.sync(source_tree)
        assert report["updated"] == ["notas/visao"]
        assert report["planted"] == ["notas/novo"]
        assert report["stale"] == ["notas/leiame"]
        assert set(report["unchanged"]) == {"dados/clientes", "dados/contratos"}

        node = vine.forest.read("notas/visao")
        assert "900 sensores" in node.body
        assert node.frontmatter["summary"].startswith("Resumo curado")
        head = subprocess.run(
            ["git", "-C", str(vine.forest.root), "log", "-1", "--pretty=%s"],
            capture_output=True, text=True, check=True).stdout
        assert "gardener(sync): notas/visao" in head \
            or "plant(notas/novo)" in head  # last commit is one of the two writes

    def test_sync_rebuilds_changed_dataset(self, garden, source_tree):
        g, vine, _ = garden
        g.adopt(source_tree)
        (source_tree / "dados" / "clientes.csv").write_text(
            CLIENTES_CSV + "Delta Engenharia,Petrolina,42\n", encoding="utf-8")
        report = g.sync(source_tree)
        assert report["updated"] == ["dados/clientes"]
        q = vine.query("dados/clientes", "SELECT COUNT(*) FROM clientes")
        assert q["rows"][0][0] == 4
        # drift-free: refreshed payload_hash matches the rebuilt file
        assert not [i for i in lint_forest(Forest(vine.forest.root))
                    if "payload drift" in i.message]

    def test_sync_with_no_changes_is_idempotent(self, garden, source_tree):
        g, _, root = garden
        g.adopt(source_tree)
        count = subprocess.run(["git", "-C", str(root), "rev-list", "--count", "HEAD"],
                               capture_output=True, text=True, check=True).stdout
        report = g.sync(source_tree)
        assert not report["planted"] and not report["updated"] and not report["stale"]
        count2 = subprocess.run(["git", "-C", str(root), "rev-list", "--count", "HEAD"],
                                capture_output=True, text=True, check=True).stdout
        assert count == count2


class TestConverterPlugins:
    def test_command_hook_takes_precedence_over_builtin(self, garden, source_tree, tmp_path):
        g, vine, root = garden
        script = tmp_path / "shout.py"
        script.write_text(textwrap.dedent("""\
            import pathlib, sys
            src = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
            pathlib.Path(sys.argv[2]).write_text(
                "# Converted Externally\\n\\n" + src.upper(), encoding="utf-8")
            """), encoding="utf-8")
        cfg = root / "_meta" / "gardener.yaml"
        cfg.write_text(
            f'converters:\n  ".txt": \'"{sys.executable}" "{script}" '
            '"{input}" "{output}"\'\n', encoding="utf-8")

        g2 = Gardener(vine, hooks=[])  # re-discovers converters with config
        g2.adopt(source_tree)
        node = vine.forest.read("notas/leiame")
        assert "MARACATU" in node.body  # the external command, not passthrough
        assert node.frontmatter["title"] == "Converted Externally"

    def test_on_curate_hook_enriches_and_crash_is_contained(self, garden, source_tree):
        _, vine, _ = garden

        def add_tag(draft):
            draft.setdefault("tags", []).append("compliance")
            return draft

        def explodes(draft):
            raise RuntimeError("plugin quebrado")

        g = Gardener(vine, hooks=[add_tag, explodes])
        report = g.adopt(source_tree)
        assert "compliance" in vine.forest.read("notas/visao").frontmatter["tags"]
        assert any("on_curate" in e and "plugin quebrado" in e for e in report["errors"])
        assert len(report["planted"]) == 4  # the crash aborted nothing


class TestCuration:
    def test_derived_summary_respects_a4(self):
        s = derive_summary(VISAO_MD, "Visão Geral")
        assert "Maracatu" in s and not s.lower().startswith("this document")
        from monkeyllm.models import validate_summary
        validate_summary(s)  # must not raise

    def test_giant_content_truncates_with_marker(self):
        s = derive_summary("# T\n\n" + "palavra " * 500, "T")
        from monkeyllm.tokens import estimate_tokens
        assert estimate_tokens(s) <= 60 and s.endswith("…")
