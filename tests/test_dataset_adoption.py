# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.2.2 / G.2.3 / G.2.4 (spec v0.44) — F.43.

A SQLite source is adopted rather than rebuilt, every dataset passport
carries the sample map, and a workbook is one table per sheet.
"""

import hashlib
import sqlite3

import pytest

from monkeyllm.errors import VineError
from monkeyllm.forest import init_forest
from monkeyllm.gardener import Gardener
from monkeyllm.models import SAMPLE_MAX_TABLES, dataset_map
from monkeyllm.parser import extract_section
from monkeyllm.vine import Vine


def build_db(path, rows=(("/login", "warning", "no autocomplete"),)):
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE findings (page TEXT, kind TEXT, detail TEXT)")
    conn.executemany("INSERT INTO findings VALUES (?, ?, ?)", rows)
    conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, started_at TEXT)")
    conn.execute("INSERT INTO runs VALUES (1, '2026-08-01T10:00:00')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def garden(tmp_path):
    root = tmp_path / "forest"
    init_forest(root, title="Test Forest")
    vine = Vine(root, writable=True)
    src = tmp_path / "dump"
    src.mkdir()
    return Gardener(vine, hooks=[]), vine, src


# --- G.2.2: the file is the payload ----------------------------------------

def test_sqlite_source_is_adopted_byte_for_byte(garden):
    g, vine, src = garden
    db = build_db(src / "audit.db")
    report = g.adopt(src)

    assert report["planted"] == ["audit"]
    assert report["errors"] == []
    node = vine.forest.read("audit")
    assert node.frontmatter["type"] == "dataset"
    assert node.frontmatter["payload"] == "audit.db"
    assert node.frontmatter["payload_type"] == "sqlite"

    installed = vine.forest.payload_path(node)
    assert installed.read_bytes() == db.read_bytes()
    assert node.frontmatter["payload_hash"] == hashlib.sha256(
        db.read_bytes()).hexdigest()
    # A.3.1: the binary never enters git.
    tracked = vine.git._run("ls-files").stdout.split()
    assert not [p for p in tracked if p.endswith(".db")]


def test_every_table_is_mapped_and_queryable(garden):
    g, vine, src = garden
    build_db(src / "audit.db")
    g.adopt(src)
    body = vine.forest.read("audit").body

    manual = extract_section(body, "Query manual")
    assert "findings(page TEXT, kind TEXT, detail TEXT)" in manual
    assert "runs(id INTEGER, started_at TEXT)" in manual

    sample = extract_section(body, "Sample rows")
    assert "### findings — 1 row" in sample
    assert "### runs — 1 row" in sample
    assert "no autocomplete" in sample

    # The second table answers without any further ingest.
    assert vine.query("audit", "SELECT started_at FROM runs")["rows"] == [
        ["2026-08-01T10:00:00"]]


def test_the_map_lists_tables_the_way_look_does(garden):
    """A view survives the copy and stays queryable, but the map does not
    claim it: C.2's `query_manual` lists tables, and the body must not
    disagree with the digest about what this dataset holds."""
    g, vine, src = garden
    db = build_db(src / "audit.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE VIEW warnings AS SELECT * FROM findings WHERE kind='warning'")
    conn.commit()
    conn.close()
    g.adopt(src)

    body = vine.forest.read("audit").body
    assert "warnings" not in body
    assert vine.look("audit")["query_manual"]["tables"].keys() == {"findings", "runs"}
    # …and the view is still there, because the file was copied whole.
    assert vine.query("audit", "SELECT COUNT(*) FROM warnings")["rows"] == [[1]]


def test_the_map_is_what_sniff_can_see(garden):
    """C.6b searches bodies; a payload is opaque to it. The map is the only
    reason a value living inside the database is findable at all."""
    g, vine, src = garden
    build_db(src / "audit.db")
    g.adopt(src)
    hits = [r["id"] for r in vine.sniff("autocomplete")["results"]]
    assert hits == ["audit"]


def test_a_file_that_is_not_sqlite_is_an_error_not_a_crash(garden):
    g, vine, src = garden
    (src / "fake.db").write_bytes(b"definitely not a database")
    report = g.adopt(src)
    assert report["planted"] == []
    assert report["errors"] == ["fake.db: not a SQLite database: fake.db"]
    assert not (vine.forest.root / "fake.db").exists()


def test_a_refused_plant_leaves_no_orphan_payload(garden, monkeypatch):
    """C.7's atomicity extends to the copy (G.2.2 rule 5)."""
    g, vine, src = garden
    build_db(src / "audit.db")

    def refuse(node):
        raise VineError("E_SCHEMA", "refused for the test")

    monkeypatch.setattr(vine, "plant", refuse)
    report = g.adopt(src)
    assert report["planted"] == []
    assert report["errors"]
    assert not (vine.forest.root / "audit.db").exists()


# --- G.3: the map follows the data -----------------------------------------

def test_sync_replaces_the_payload_and_the_map_only(garden):
    g, vine, src = garden
    db = build_db(src / "audit.db")
    g.adopt(src)
    vine.graft("audit", {"append_section": {"header": "Notes",
                                            "body": "Curated by hand."}})
    head = vine.git.head()

    build_db(db, rows=(("/checkout", "error", "brand new detail"),
                       ("/x", "note", "second")))
    report = g.sync()
    assert report["updated"] == ["audit"]

    node = vine.forest.read("audit")
    assert vine.forest.payload_path(node).read_bytes() == db.read_bytes()
    assert node.frontmatter["payload_hash"] == hashlib.sha256(
        db.read_bytes()).hexdigest()
    sample = extract_section(node.body, "Sample rows")
    assert "brand new detail" in sample
    assert "no autocomplete" not in sample
    # A curator's own section is not the Gardener's to overwrite.
    assert "Curated by hand." in extract_section(node.body, "Notes")
    # …and the commit carried only the `.md`.
    assert vine.git.head() != head
    changed = vine.git._run("show", "--name-only", "--pretty=format:").stdout.split()
    assert all(p.endswith(".md") for p in changed if p)


# --- G.2.4: one table per sheet --------------------------------------------

def test_workbook_plants_one_table_per_sheet(garden):
    openpyxl = pytest.importorskip("openpyxl")
    g, vine, src = garden
    wb = openpyxl.Workbook()
    first = wb.active
    first.title = "Clients"
    first.append(["name", "city"])
    first.append(["Ana", "Recife"])
    second = wb.create_sheet("Orders 2026")
    second.append(["id", "total"])
    second.append([1, 99.5])
    wb.create_sheet("Empty")
    wb.save(src / "book.xlsx")

    assert g.adopt(src)["planted"] == ["book"]
    manual = extract_section(vine.forest.read("book").body, "Query manual")
    assert "clients(" in manual and "orders_2026(" in manual
    # A workbook float stays a float: int(99.5) truncates where int("99.5")
    # raises, and the money column must not be rounded by the type guess.
    assert vine.query("book", "SELECT total FROM orders_2026")["rows"] == [[99.5]]


def test_a_workbook_over_the_table_limit_is_refused_by_name(garden):
    openpyxl = pytest.importorskip("openpyxl")
    g, vine, src = garden
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for i in range(11):
        ws = wb.create_sheet(f"Sheet{i}")
        ws.append(["a"])
        ws.append([i])
    wb.save(src / "wide.xlsx")

    report = g.adopt(src)
    assert report["planted"] == []
    assert report["errors"] == ["wide.xlsx: workbook has 11 sheets with data: wide.xlsx"]


# --- G.2.3: the map is bounded, and says when it stops ----------------------

def test_the_map_clips_cells_and_names_blobs():
    tables = {"t": {"long": "TEXT", "raw": "BLOB", "gone": "TEXT"}}
    samples = {"t": [["x" * 400, b"\x00\x01\x02", None]]}
    body = dataset_map(tables, samples, {"t": 1})
    assert "…" in body
    assert "<blob 3 bytes>" in body
    assert "x" * 200 not in body


def test_the_map_never_stops_silently():
    tables = {f"t{i}": {"a": "TEXT"} for i in range(SAMPLE_MAX_TABLES + 3)}
    body = dataset_map(tables, {})
    # every table is still named in the manual…
    assert f"`t{SAMPLE_MAX_TABLES + 2}(a TEXT)`" in body
    # …and the omission from the sample is stated, not hidden.
    assert "3 further table(s) not sampled" in body


def test_a_pipe_in_a_value_cannot_break_the_row():
    body = dataset_map({"t": {"a": "TEXT", "b": "TEXT"}},
                       {"t": [["x | y", "line\nbreak"]]}, {"t": 1})
    row = [l for l in body.splitlines() if l.startswith("| x")][0]
    assert row == "| x \\| y | line break |"
