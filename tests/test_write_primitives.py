"""Part F criterion 2: plant/graft atomic, git-committed, index-synced."""

import shutil
import stat
import subprocess

import pytest

from monkeyllm.errors import E_NOT_FOUND, E_READONLY, E_SCHEMA, VineError


def git_log(forest, n=1) -> str:
    out = subprocess.run(
        ["git", "-C", str(forest), "log", f"-{n}", "--pretty=%s"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def good_spec(**over):
    spec = {
        "id": "notas/aprendizado-teste",
        "type": "nota",
        "title": "Aprendizado de teste",
        "summary": "Nota plantada pela suíte de testes para verificar atomicidade de escrita e sincronia de índice.",
        "parent": "notas/_index",
        "body": "# Aprendizado de teste\n\n## Conteúdo\n\nPlantada pelo teste.",
        "source": "agente",
    }
    spec.update(over)
    return spec


class TestPlant:
    def test_plant_creates_file_index_entry_and_commit(self, vine_rw, forest_rw):
        before = git_log(forest_rw)
        r = vine_rw.plant(good_spec())
        assert r["id"] == "notas/aprendizado-teste"
        assert r["trail"] == ["_index", "notas/_index"]
        assert (forest_rw / "notas" / "aprendizado-teste.md").is_file()

        # parent index got the entry with the VERBATIM summary
        idx = (forest_rw / "notas" / "_index.md").read_text(encoding="utf-8")
        assert "[[notas/aprendizado-teste]] — Nota plantada pela suíte" in idx

        # git commit with the standard message
        head = git_log(forest_rw)
        assert head != before
        assert head.startswith("plant(notas/aprendizado-teste):")
        assert "[source=agente]" in head
        assert r["commit"]

        # node is immediately navigable
        d = vine_rw.look("notas/aprendizado-teste")
        assert d["summary"].startswith("Nota plantada")

    def test_duplicate_id_rejected(self, vine_rw):
        vine_rw.plant(good_spec())
        with pytest.raises(VineError) as e:
            vine_rw.plant(good_spec())
        assert e.value.code == E_SCHEMA

    def test_unknown_type_rejected(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.plant(good_spec(type="meme"))
        assert e.value.code == E_SCHEMA

    def test_bad_summary_rejected(self, vine_rw):
        with pytest.raises(VineError):
            vine_rw.plant(good_spec(summary="Este documento descreve uma nota."))

    def test_parent_must_exist_and_match_id_path(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.plant(good_spec(parent="nao/_index"))
        assert e.value.code == E_NOT_FOUND
        with pytest.raises(VineError) as e:
            vine_rw.plant(good_spec(parent="vendas/_index"))
        assert e.value.code == E_SCHEMA

    def test_rollback_on_commit_failure(self, vine_rw, forest_rw):
        idx_before = (forest_rw / "notas" / "_index.md").read_text(encoding="utf-8")
        git_dir = forest_rw / ".git"
        moved = forest_rw / ".git-moved"
        git_dir.rename(moved)  # break git -> commit fails mid-transaction
        try:
            with pytest.raises(Exception):
                vine_rw.plant(good_spec())
        finally:
            moved.rename(git_dir)
        assert not (forest_rw / "notas" / "aprendizado-teste.md").exists()
        assert (forest_rw / "notas" / "_index.md").read_text(encoding="utf-8") == idx_before

    def test_readonly_vine_cannot_plant(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.plant(good_spec())
        assert e.value.code == E_READONLY


class TestGraft:
    def test_immutable_fields_rejected(self, vine_rw):
        for field in ("id", "type", "created"):
            with pytest.raises(VineError) as e:
                vine_rw.graft("conceitos/rag", {"set_frontmatter": {field: "x"}})
            assert e.value.code == E_READONLY

    def test_set_title_and_commit(self, vine_rw, forest_rw):
        r = vine_rw.graft("conceitos/rag", {"set_frontmatter": {"title": "RAG clássico"}})
        assert r["commit"]
        assert git_log(forest_rw).startswith("graft(conceitos/rag):")
        assert vine_rw.look("conceitos/rag")["title"] == "RAG clássico"

    def test_summary_change_propagates_verbatim_to_index(self, vine_rw, forest_rw):
        new_summary = "Resumo novo do RAG, reescrito pelo teste para verificar propagação verbatim ao índice pai."
        vine_rw.graft("conceitos/rag", {"set_frontmatter": {"summary": new_summary}})
        idx = (forest_rw / "conceitos" / "_index.md").read_text(encoding="utf-8")
        assert f"[[conceitos/rag]] — {new_summary}" in idx

    def test_append_and_replace_section(self, vine_rw):
        vine_rw.graft(
            "conceitos/rag",
            {"append_section": {"header": "Aprendizado do agente", "body": "Observação nova."}},
        )
        p = vine_rw.pick("conceitos/rag", section="Aprendizado do agente")
        assert "Observação nova." in p["body"]

        vine_rw.graft(
            "conceitos/rag",
            {"replace_section": {"header": "Aprendizado do agente", "body": "Observação revista."}},
        )
        p = vine_rw.pick("conceitos/rag", section="Aprendizado do agente")
        assert "Observação revista." in p["body"]
        assert "Observação nova." not in p["body"]

    def test_replace_missing_section_not_found(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.graft("conceitos/rag", {"replace_section": {"header": "Nada", "body": "x"}})
        assert e.value.code == E_NOT_FOUND

    def test_add_link_then_duplicate_becomes_fortification(self, vine_rw, forest_rw):
        link = {"rel": "atalho-descoberto", "target": "vendas/relatorio-q1-2026"}
        r1 = vine_rw.graft("projetos/monkeyllm/monkey-bench", {"add_links": [link]})
        assert r1["commit"] and r1["fortified"] == []
        node = vine_rw.forest.read("projetos/monkeyllm/monkey-bench")
        planted = [l for l in node.frontmatter["links"] if l.get("rel") == "atalho-descoberto"]
        assert planted[0]["confidence"] == 0.5  # shout default
        assert planted[0]["discovered_by"] == "agente"

        heat_before = vine_rw.trails.get_heat("vendas/relatorio-q1-2026")
        head_before = git_log(forest_rw)
        r2 = vine_rw.graft("projetos/monkeyllm/monkey-bench", {"add_links": [link]})
        # reinforce-before-create: no new edge, no commit, heat goes up
        assert r2["commit"] is None
        assert r2["fortified"] == [link]
        assert git_log(forest_rw) == head_before
        assert vine_rw.trails.get_heat("vendas/relatorio-q1-2026") > heat_before
        node = vine_rw.forest.read("projetos/monkeyllm/monkey-bench")
        again = [l for l in node.frontmatter["links"] if l.get("rel") == "atalho-descoberto"]
        assert len(again) == 1  # never duplicated

    def test_remove_link(self, vine_rw):
        vine_rw.graft(
            "conceitos/rag",
            {"remove_links": [{"rel": "comparado-com", "target": "projetos/monkeyllm/visao"}]},
        )
        node = vine_rw.forest.read("conceitos/rag")
        assert not node.frontmatter.get("links")

    def test_unknown_rel_rejected(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.graft("conceitos/rag", {"add_links": [{"rel": "odeia", "target": "conceitos/bm25"}]})
        assert e.value.code == E_SCHEMA

    def test_empty_patch_rejected(self, vine_rw):
        with pytest.raises(VineError):
            vine_rw.graft("conceitos/rag", {})

    def test_updated_date_refreshed(self, vine_rw):
        import datetime as dt

        vine_rw.graft("conceitos/rag", {"set_frontmatter": {"title": "RAG!"}})
        node = vine_rw.forest.read("conceitos/rag")
        assert str(node.frontmatter["updated"]) == dt.date.today().isoformat()
