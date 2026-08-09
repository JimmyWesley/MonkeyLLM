# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""C.7.1 dataset planting (spec v0.8): declarative schema births the payload."""

import copy
import hashlib
import sqlite3
import subprocess

import pytest

from monkeyllm.errors import E_SCHEMA, VineError

SPEC = {
    "id": "sales/prospecting-2026",
    "type": "dataset",
    "parent": "sales/_index",
    "title": "Client Prospecting 2026",
    "summary": "Clients prospected in 2026 with site, segment and collection date. Fed by agent via tend.",
    "schema": {
        "clients": {
            "columns": {"name": "TEXT", "site": "TEXT", "segment": "TEXT",
                        "collected_at": "TEXT"},
            "primary_key": ["name"],
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
        db = forest_rw / "sales" / "prospecting-2026.db"
        assert db.is_file()
        node = vine_rw.forest.read(SPEC["id"])
        assert node.frontmatter["payload"] == "prospecting-2026.db"
        assert node.frontmatter["payload_type"] == "sqlite"
        assert node.frontmatter["payload_hash"] == hashlib.sha256(db.read_bytes()).hexdigest()

        # auto query manual feeds the C.2 dataset digest from birth
        assert "## Query manual" in node.body
        digest = vine_rw.look(SPEC["id"])
        assert digest["query_manual"]["tables"] == {
            "clients": ["name", "site", "segment", "collected_at"]
        }
        assert "SELECT * FROM clients LIMIT 5" in digest["query_manual"]["example_queries"]

        # query and tend work immediately — the living-bank loop closes
        assert vine_rw.query(SPEC["id"], "SELECT COUNT(*) FROM clients")["rows"][0][0] == 0
        w = vine_rw.tend(
            SPEC["id"],
            "INSERT INTO clients VALUES ('Acme','acme.com','industry','2026-06-11'),"
            " ('Beta','beta.io','retail','2026-06-11')",
        )
        assert w["rows_affected"] == 2
        assert vine_rw.query(SPEC["id"], "SELECT COUNT(*) FROM clients")["rows"][0][0] == 2

        # A.3.1: the commit carries only markdown
        out = subprocess.run(["git", "-C", str(forest_rw), "ls-files"],
                             capture_output=True, text=True, check=True)
        assert not [f for f in out.stdout.split() if f.endswith((".db", ".sqlite"))]

    def test_primary_key_is_enforced(self, vine_rw):
        vine_rw.plant(SPEC)
        vine_rw.tend(SPEC["id"], "INSERT INTO clients VALUES ('Acme','a','x','2026-01-01')")
        with pytest.raises(VineError):  # duplicate pk surfaces as SQL error
            vine_rw.tend(SPEC["id"], "INSERT INTO clients VALUES ('Acme','b','y','2026-01-02')")

    def test_caller_manual_kept_verbatim(self, vine_rw):
        s = copy.deepcopy(SPEC)
        s["body"] = "# Prospecting\n\n## Query manual\n\nManual query. `SELECT name FROM clients`"
        vine_rw.plant(s)
        body = vine_rw.forest.read(SPEC["id"]).body
        assert "Manual query" in body
        assert body.count("## Query manual") == 1

    def test_multi_table_schema(self, vine_rw):
        s = spec_with_schema({
            "clients": {"columns": {"name": "TEXT"}},
            "contacts": {"columns": {"client": "TEXT", "email": "TEXT"}},
        })
        vine_rw.plant(s)
        tables = vine_rw.look(SPEC["id"])["query_manual"]["tables"]
        assert set(tables) == {"clients", "contacts"}


class TestInitialRows:
    def test_rows_loaded_at_birth(self, vine_rw, forest_rw):
        s = copy.deepcopy(SPEC)
        # a value containing SQL keywords is DATA, not SQL — parameterized
        # loading must store it literally (C.7.1 rule 7)
        s["rows"] = {"clients": [
            ["Acme", "acme.com", "industry", "2026-06-11"],
            ["Robert'); DROP TABLE clients;--", "x.io", "retail", "2026-06-11"],
        ]}
        r = vine_rw.plant(s)
        q = vine_rw.query(SPEC["id"], "SELECT COUNT(*) FROM clients")
        assert q["rows"][0][0] == 2
        q2 = vine_rw.query(SPEC["id"],
                           "SELECT name FROM clients WHERE site = 'x.io'")
        assert q2["rows"][0][0] == "Robert'); DROP TABLE clients;--"
        db = forest_rw / "sales" / "prospecting-2026.db"
        assert r and hashlib.sha256(db.read_bytes()).hexdigest() == \
            vine_rw.forest.read(SPEC["id"]).frontmatter["payload_hash"]

    @pytest.mark.parametrize("rows", [
        {"nonexistent": [["a", "b", "c", "d"]]},     # table not in schema
        {"clients": [["only", "three", "values"]]},  # wrong width
    ])
    def test_bad_rows_rejected(self, vine_rw, forest_rw, rows):
        s = copy.deepcopy(SPEC)
        s["rows"] = rows
        with pytest.raises(VineError) as e:
            vine_rw.plant(s)
        assert e.value.code == E_SCHEMA
        assert not (forest_rw / "sales" / "prospecting-2026.db").exists()

    def test_rows_without_schema_rejected(self, vine_rw):
        s = copy.deepcopy(SPEC)
        del s["schema"]
        s["rows"] = {"clients": [["a", "b", "c", "d"]]}
        with pytest.raises(VineError) as e:
            vine_rw.plant(s)
        assert e.value.code == E_SCHEMA


class TestSchemaValidation:
    @pytest.mark.parametrize("schema", [
        {},                                                        # no tables
        {"clients; DROP TABLE x": {"columns": {"a": "TEXT"}}},    # name injection
        {"clients": {"columns": {}}},                             # no columns
        {"clients": {"columns": {"a b": "TEXT"}}},                # bad column name
        {"clients": {"columns": {"a": "TEXT); DROP TABLE x;--"}}},  # type injection
        {"clients": {"columns": {"a": "VARCHAR(99)"}}},           # type not allowlisted
        {"clients": {"columns": {"a": "TEXT"}, "primary_key": ["zz"]}},  # pk not a column
        {f"t{i}": {"columns": {"a": "TEXT"}} for i in range(11)},  # > 10 tables
    ])
    def test_bad_schema_rejected_and_nothing_born(self, vine_rw, forest_rw, schema):
        with pytest.raises(VineError) as e:
            vine_rw.plant(spec_with_schema(schema))
        assert e.value.code == E_SCHEMA
        assert not (forest_rw / "sales" / "prospecting-2026.db").exists()
        assert not vine_rw.forest.exists(SPEC["id"])

    def test_schema_on_non_dataset_rejected(self, vine_rw):
        s = copy.deepcopy(SPEC)
        s["type"] = "note"
        with pytest.raises(VineError) as e:
            vine_rw.plant(s)
        assert e.value.code == E_SCHEMA

    def test_payload_must_be_bare_db_filename(self, vine_rw):
        for bad in ("../outside.db", "sub/inside.db", "clients.csv"):
            s = copy.deepcopy(SPEC)
            s["payload"] = bad
            with pytest.raises(VineError) as e:
                vine_rw.plant(s)
            assert e.value.code == E_SCHEMA

    def test_existing_payload_never_overwritten(self, vine_rw, forest_rw):
        target = forest_rw / "sales" / "prospecting-2026.db"
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
        assert not (forest_rw / "sales" / "prospecting-2026.db").exists()
        assert not (forest_rw / "sales" / "prospecting-2026.md").exists()
