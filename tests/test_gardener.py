"""Part G (spec v0.9): the Gardener — adopt, sync, converters, hooks."""

import subprocess
import sys
import textwrap

import pytest

from monkeyllm.forest import Forest, init_forest
from monkeyllm.gardener import Gardener, derive_summary
from monkeyllm.lint import lint_forest
from monkeyllm.vine import Vine

OVERVIEW_MD = textwrap.dedent("""\
    # Project Overview

    The Maracatu project controls industrial sensors in the Northeast and integrates
    field data with the central ERP. The 2026 goal is to double the monitored fleet
    without increasing the operations team.

    ## Details

    More text here about telemetry and predictive maintenance.
    """)

CLIENTS_CSV = textwrap.dedent("""\
    name,city,value
    Acme Industry,Recife,1250.50
    Beta Commerce,Olinda,300
    Gama Services,Caruaru,87.25
    """)

CONTRACTS_JSON = '[{"contract": "CT-01", "client": "Acme", "year": 2026},' \
                 ' {"contract": "CT-02", "client": "Beta", "year": 2025}]'


@pytest.fixture()
def source_tree(tmp_path):
    src = tmp_path / "dump"
    (src / "notes").mkdir(parents=True)
    (src / "data").mkdir()
    (src / "notes" / "overview.md").write_text(OVERVIEW_MD, encoding="utf-8")
    (src / "notes" / "readme.txt").write_text(
        "Operational notes folder for the Maracatu project.", encoding="utf-8")
    (src / "data" / "clients.csv").write_text(CLIENTS_CSV, encoding="utf-8")
    (src / "data" / "contracts.json").write_text(CONTRACTS_JSON, encoding="utf-8")
    (src / "report.bin").write_bytes(b"\x00\x01\x02")
    return src


@pytest.fixture()
def garden(tmp_path):
    root = tmp_path / "forest"
    init_forest(root, title="Test Forest")
    vine = Vine(root, writable=True)
    g = Gardener(vine, hooks=[])
    yield g, vine, root
    vine.close()


class TestAdopt:
    def test_adopt_mirrors_tree(self, garden, source_tree):
        g, vine, root = garden
        report = g.adopt(source_tree)

        assert sorted(report["branches"]) == ["data/_index", "notes/_index"]
        assert sorted(report["planted"]) == [
            "data/clients", "data/contracts", "notes/overview", "notes/readme"]
        assert report["unsupported"] == ["report.bin"]
        assert not report["errors"]

        # G.1: passports carry source_path + source_hash
        node = vine.forest.read("notes/overview")
        assert node.frontmatter["source_path"] == "notes/overview.md"
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
        q = vine.query("data/clients", "SELECT COUNT(*) FROM clients")
        assert q["rows"][0][0] == 3
        # type inference: value is numeric, SUM works
        q2 = vine.query("data/clients", "SELECT SUM(value) FROM clients")
        assert abs(q2["rows"][0][0] - 1637.75) < 0.01
        # tabular json too
        q3 = vine.query("data/contracts",
                        "SELECT client FROM contracts WHERE year = 2026")
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
        vine.graft("notes/overview", {"set_frontmatter": {
            "summary": "Human-curated summary, untouched by sync."}})

        (source_tree / "notes" / "overview.md").write_text(
            OVERVIEW_MD + "\n## Update\n\nFleet expanded to 900 sensors.\n",
            encoding="utf-8")
        (source_tree / "notes" / "new.md").write_text(
            "# New\n\nNote newly created at source.", encoding="utf-8")
        (source_tree / "notes" / "readme.txt").unlink()

        report = g.sync(source_tree)
        assert report["updated"] == ["notes/overview"]
        assert report["planted"] == ["notes/new"]
        assert report["stale"] == ["notes/readme"]
        assert set(report["unchanged"]) == {"data/clients", "data/contracts"}

        node = vine.forest.read("notes/overview")
        assert "900 sensors" in node.body
        assert node.frontmatter["summary"].startswith("Human-curated")
        head = subprocess.run(
            ["git", "-C", str(vine.forest.root), "log", "-1", "--pretty=%s"],
            capture_output=True, text=True, check=True).stdout
        assert "gardener(sync): notes/overview" in head \
            or "plant(notes/new)" in head  # last commit is one of the two writes

    def test_sync_rebuilds_changed_dataset(self, garden, source_tree):
        g, vine, _ = garden
        g.adopt(source_tree)
        (source_tree / "data" / "clients.csv").write_text(
            CLIENTS_CSV + "Delta Engineering,Petrolina,42\n", encoding="utf-8")
        report = g.sync(source_tree)
        assert report["updated"] == ["data/clients"]
        q = vine.query("data/clients", "SELECT COUNT(*) FROM clients")
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
        node = vine.forest.read("notes/readme")
        assert "MARACATU" in node.body  # the external command, not passthrough
        assert node.frontmatter["title"] == "Converted Externally"

    def test_on_curate_hook_enriches_and_crash_is_contained(self, garden, source_tree):
        _, vine, _ = garden

        def add_tag(draft):
            draft.setdefault("tags", []).append("compliance")
            return draft

        def explodes(draft):
            raise RuntimeError("broken plugin")

        g = Gardener(vine, hooks=[add_tag, explodes])
        report = g.adopt(source_tree)
        assert "compliance" in vine.forest.read("notes/overview").frontmatter["tags"]
        assert any("on_curate" in e and "broken plugin" in e for e in report["errors"])
        assert len(report["planted"]) == 4  # the crash aborted nothing


class TestCuration:
    def test_derived_summary_respects_a4(self):
        s = derive_summary(OVERVIEW_MD, "Project Overview")
        assert "Maracatu" in s and not s.lower().startswith("this document")
        from monkeyllm.models import validate_summary
        validate_summary(s)  # must not raise

    def test_giant_content_truncates_with_marker(self):
        s = derive_summary("# T\n\n" + "word " * 500, "T")
        from monkeyllm.tokens import estimate_tokens
        assert estimate_tokens(s) <= 60 and s.endswith("…")
