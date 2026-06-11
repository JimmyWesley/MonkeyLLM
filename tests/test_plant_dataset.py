"""C.7.1 dataset planting (spec v0.8): declarative schema births the payload."""

import copy
import hashlib
import sqlite3
import subprocess

import pytest

from monkeyllm.errors import E_SCHEMA, VineError

SPEC = {
    "id": "vendas/prospeccao-2026",
    "type": "dataset",
    "parent": "vendas/_index",
    "title": "Prospecção de clientes 2026",
    "summary": "Clientes prospectados em 2026 com site, segmento e data de coleta. Alimentado por agente via tend.",
    "schema": {
        "clientes": {
            "columns": {"nome": "TEXT", "site": "TEXT", "segmento": "TEXT",
                        "coletado_em": "TEXT"},
            "primary_key": ["nome"],
        }
    },
}


def spec_with_schema(schema: dict) -> dict:
    s = copy.deepcopy(SPEC)
    s["schema"] = schema
    return s


class TestDatasetBirth:
    def test_plant_births_queryable_payload(self, vine_rw, forest_rw):
        r = vine_rw.plant(SPEC)
        assert r["id"] == SPEC["id"]

        # payload born on the filesystem, hash anchored in the frontmatter
        db = forest_rw / "vendas" / "prospeccao-2026.db"
        assert db.is_file()
        node = vine_rw.forest.read(SPEC["id"])
        assert node.frontmatter["payload"] == "prospeccao-2026.db"
        assert node.frontmatter["payload_type"] == "sqlite"
        assert node.frontmatter["payload_hash"] == hashlib.sha256(db.read_bytes()).hexdigest()

        # auto query manual feeds the C.2 dataset digest from birth
        assert "## Query manual" in node.body
        digest = vine_rw.look(SPEC["id"])
        assert digest["query_manual"]["tables"] == {
            "clientes": ["nome", "site", "segmento", "coletado_em"]
        }
        assert "SELECT * FROM clientes LIMIT 5" in digest["query_manual"]["example_queries"]

        # query and tend work immediately — the living-bank loop closes
        assert vine_rw.query(SPEC["id"], "SELECT COUNT(*) FROM clientes")["rows"][0][0] == 0
        w = vine_rw.tend(
            SPEC["id"],
            "INSERT INTO clientes VALUES ('Acme','acme.com','industria','2026-06-11'),"
            " ('Beta','beta.io','varejo','2026-06-11')",
        )
        assert w["rows_affected"] == 2
        assert vine_rw.query(SPEC["id"], "SELECT COUNT(*) FROM clientes")["rows"][0][0] == 2

        # A.3.1: the commit carries only markdown
        out = subprocess.run(["git", "-C", str(forest_rw), "ls-files"],
                             capture_output=True, text=True, check=True)
        assert not [f for f in out.stdout.split() if f.endswith((".db", ".sqlite"))]

    def test_primary_key_is_enforced(self, vine_rw):
        vine_rw.plant(SPEC)
        vine_rw.tend(SPEC["id"], "INSERT INTO clientes VALUES ('Acme','a','x','2026-01-01')")
        with pytest.raises(VineError):  # duplicate pk surfaces as SQL error
            vine_rw.tend(SPEC["id"], "INSERT INTO clientes VALUES ('Acme','b','y','2026-01-02')")

    def test_caller_manual_kept_verbatim(self, vine_rw):
        s = copy.deepcopy(SPEC)
        s["body"] = "# Prospecção\n\n## Query manual\n\nManual artesanal. `SELECT nome FROM clientes`"
        vine_rw.plant(s)
        body = vine_rw.forest.read(SPEC["id"]).body
        assert "Manual artesanal" in body
        assert body.count("## Query manual") == 1

    def test_multi_table_schema(self, vine_rw):
        s = spec_with_schema({
            "clientes": {"columns": {"nome": "TEXT"}},
            "contatos": {"columns": {"cliente": "TEXT", "email": "TEXT"}},
        })
        vine_rw.plant(s)
        tables = vine_rw.look(SPEC["id"])["query_manual"]["tables"]
        assert set(tables) == {"clientes", "contatos"}


class TestSchemaValidation:
    @pytest.mark.parametrize("schema", [
        {},                                                       # no tables
        {"clientes; DROP TABLE x": {"columns": {"a": "TEXT"}}},   # name injection
        {"clientes": {"columns": {}}},                            # no columns
        {"clientes": {"columns": {"a b": "TEXT"}}},               # bad column name
        {"clientes": {"columns": {"a": "TEXT); DROP TABLE x;--"}}},  # type injection
        {"clientes": {"columns": {"a": "VARCHAR(99)"}}},          # type not allowlisted
        {"clientes": {"columns": {"a": "TEXT"}, "primary_key": ["zz"]}},  # pk not a column
        {f"t{i}": {"columns": {"a": "TEXT"}} for i in range(11)},  # > 10 tables
    ])
    def test_bad_schema_rejected_and_nothing_born(self, vine_rw, forest_rw, schema):
        with pytest.raises(VineError) as e:
            vine_rw.plant(spec_with_schema(schema))
        assert e.value.code == E_SCHEMA
        assert not (forest_rw / "vendas" / "prospeccao-2026.db").exists()
        assert not vine_rw.forest.exists(SPEC["id"])

    def test_schema_on_non_dataset_rejected(self, vine_rw):
        s = copy.deepcopy(SPEC)
        s["type"] = "note"
        with pytest.raises(VineError) as e:
            vine_rw.plant(s)
        assert e.value.code == E_SCHEMA

    def test_payload_must_be_bare_db_filename(self, vine_rw):
        for bad in ("../fora.db", "sub/dentro.db", "clientes.csv"):
            s = copy.deepcopy(SPEC)
            s["payload"] = bad
            with pytest.raises(VineError) as e:
                vine_rw.plant(s)
            assert e.value.code == E_SCHEMA

    def test_existing_payload_never_overwritten(self, vine_rw, forest_rw):
        target = forest_rw / "vendas" / "prospeccao-2026.db"
        target.write_bytes(b"precious bytes")
        with pytest.raises(VineError) as e:
            vine_rw.plant(SPEC)
        assert e.value.code == E_SCHEMA
        assert target.read_bytes() == b"precious bytes"


class TestAtomicity:
    def test_failed_plant_removes_newborn_db(self, vine_rw, forest_rw, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("git exploded")

        monkeypatch.setattr(vine_rw.git, "commit", boom)
        with pytest.raises(RuntimeError):
            vine_rw.plant(SPEC)
        assert not (forest_rw / "vendas" / "prospeccao-2026.db").exists()
        assert not (forest_rw / "vendas" / "prospeccao-2026.md").exists()
