# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""C.10 tend (spec v0.7): dataset writes with guard rails + audit commit."""

import hashlib
import sqlite3
import subprocess

import anyio
import pytest

from monkeyllm.errors import (
    E_QUERY_FORBIDDEN,
    E_QUERY_INVALID,
    E_READONLY,
    VineError,
)
from monkeyllm.forest import Forest
from monkeyllm.lint import lint_forest

DATASET = "sales/report-q1-2026"
GOOD_INSERT = (
    "INSERT INTO sales VALUES "
    "('2026-03-31','A-101','Sensor X','Southeast','direct',1,1250.0,250.0)"
)


def db_path(forest):
    return forest / "sales" / "report-q1-2026.db"


def row_count(forest) -> int:
    conn = sqlite3.connect(db_path(forest))
    try:
        return conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    finally:
        conn.close()


def git_head(forest) -> str:
    return subprocess.run(["git", "-C", str(forest), "log", "-1", "--pretty=%s"],
                          capture_output=True, text=True, check=True).stdout.strip()


class TestTendWrites:
    def test_insert_updates_hash_and_commits_md_only(self, vine_rw, forest_rw):
        before = row_count(forest_rw)
        r = vine_rw.tend(DATASET, GOOD_INSERT)
        assert r["rows_affected"] == 1
        assert row_count(forest_rw) == before + 1

        # audit: hash refreshed and matches the file; commit message standard
        assert r["payload_hash"] == hashlib.sha256(db_path(forest_rw).read_bytes()).hexdigest()
        node = vine_rw.forest.read(DATASET)
        assert node.frontmatter["payload_hash"] == r["payload_hash"]
        assert git_head(forest_rw).startswith(f"tend({DATASET}): INSERT 1 row(s)")

        # A.3.1 intact: the commit carries only .md — no binary ever tracked
        out = subprocess.run(["git", "-C", str(forest_rw), "ls-files"],
                             capture_output=True, text=True, check=True)
        assert not [f for f in out.stdout.split() if f.endswith((".db", ".sqlite"))]

        # the new row is immediately queryable
        q = vine_rw.query(DATASET, "SELECT COUNT(*) FROM sales WHERE date = '2026-03-31'")
        assert q["rows"][0][0] >= 1

    def test_update_and_delete_require_where(self, vine_rw):
        for bad in ("UPDATE sales SET qty = 0", "DELETE FROM sales"):
            with pytest.raises(VineError) as e:
                vine_rw.tend(DATASET, bad)
            assert e.value.code == E_QUERY_FORBIDDEN
        r = vine_rw.tend(DATASET, "UPDATE sales SET qty = qty WHERE sku = 'A-101'")
        assert r["rows_affected"] > 0

    def test_injection_suite(self, vine_rw):
        for bad in (
            "SELECT * FROM sales",
            "INSERT INTO sales VALUES (1); DROP TABLE sales",
            "DROP TABLE sales",
            "CREATE TABLE hack (x)",
            "ATTACH DATABASE 'x.db' AS x",
            "PRAGMA writable_schema = 1",
            "BEGIN",
        ):
            with pytest.raises(VineError) as e:
                vine_rw.tend(DATASET, bad)
            assert e.value.code == E_QUERY_FORBIDDEN

    def test_failed_sql_leaves_payload_untouched(self, vine_rw, forest_rw):
        before = db_path(forest_rw).read_bytes()
        with pytest.raises(VineError) as e:
            vine_rw.tend(DATASET, "INSERT INTO nonexistent VALUES (1)")
        # C.5.2: naming a table that is not there is the caller writing bad
        # SQL, not the guard denying a write. Same split as query().
        assert e.value.code == E_QUERY_INVALID
        assert db_path(forest_rw).read_bytes() == before

    def test_invalid_is_not_forbidden(self, vine_rw):
        """C.5.2 (v0.47): the guard's refusals keep the forbidden code."""
        with pytest.raises(VineError) as invalid:
            vine_rw.tend(DATASET, "INSERT INTO sales (nonexistent) VALUES (1)")
        assert invalid.value.code == E_QUERY_INVALID
        with pytest.raises(VineError) as forbidden:
            vine_rw.tend(DATASET, "DROP TABLE sales")
        assert forbidden.value.code == E_QUERY_FORBIDDEN

    def test_non_dataset_rejected(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.tend("concepts/rag", GOOD_INSERT)
        assert e.value.code == E_QUERY_FORBIDDEN

    def test_readonly_vine_cannot_tend(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.tend(DATASET, GOOD_INSERT)
        assert e.value.code == E_READONLY


class TestDriftDetection:
    def test_validate_warns_on_payload_drift(self, vine_rw, forest_rw):
        vine_rw.tend(DATASET, GOOD_INSERT)  # establishes a fresh hash
        conn = sqlite3.connect(db_path(forest_rw))  # edit OUTSIDE tend
        conn.execute("DELETE FROM sales WHERE rowid = 1")
        conn.commit()
        conn.close()
        issues = lint_forest(Forest(forest_rw))
        drift = [i for i in issues if "payload drift" in i.message]
        assert drift and drift[0].level == "warning" and drift[0].node_id == DATASET


class TestTableScope:
    """J.3: a grant may narrow which tables of a dataset a principal touches.

    It governs writing as well as reading, and it has to: writing is a way
    of reading. A statement that writes only where it may can still take its
    value from a table it may not read, and leave it somewhere readable — so
    policing the destination while ignoring the source is not a scope.
    """

    @staticmethod
    def _with_payroll(forest):
        """A second table in the same payload, to have something withheld."""
        conn = sqlite3.connect(db_path(forest))
        try:
            conn.execute("CREATE TABLE payroll (id INTEGER, amount REAL)")
            conn.execute("INSERT INTO payroll VALUES (42, 999999.0)")
            conn.commit()
        finally:
            conn.close()

    def test_a_write_outside_the_allow_list_is_refused(self, vine_rw, forest_rw):
        self._with_payroll(forest_rw)
        before = row_count(forest_rw)
        with pytest.raises(VineError) as e:
            vine_rw.tend(DATASET, "DELETE FROM payroll WHERE id = 42",
                         tables=("sales",))
        assert e.value.code == E_QUERY_FORBIDDEN
        assert row_count(forest_rw) == before

    def test_a_permitted_write_still_goes_through(self, vine_rw, forest_rw):
        """The refusals must be the scope, not the scope breaking `tend`."""
        self._with_payroll(forest_rw)
        before = row_count(forest_rw)
        assert vine_rw.tend(DATASET, GOOD_INSERT, tables=("sales",))["rows_affected"] == 1
        assert row_count(forest_rw) == before + 1

    def test_a_permitted_write_may_not_read_a_withheld_table(self, vine_rw, forest_rw):
        """The side channel, and the reason denying the write actions alone is
        not enough: this statement writes only where it may."""
        self._with_payroll(forest_rw)
        with pytest.raises(VineError) as e:
            vine_rw.tend(
                DATASET,
                "UPDATE sales SET value = (SELECT amount FROM payroll WHERE id = 42) "
                "WHERE rowid = 1",
                tables=("sales",))
        assert e.value.code == E_QUERY_FORBIDDEN

        conn = sqlite3.connect(db_path(forest_rw))
        try:
            leaked = conn.execute(
                "SELECT COUNT(*) FROM sales WHERE value = 999999.0").fetchone()[0]
        finally:
            conn.close()
        assert leaked == 0, "the withheld value reached a table the caller may read"

    def test_the_host_hands_the_allow_list_to_the_engine(self, vine_rw, forest_rw):
        """The engine enforces; the grant is what says so. If `ScopedVine`
        stops forwarding the list, everything above stays correct and stops
        being reached, which is a failure no test of the engine alone sees."""
        import sys
        from pathlib import Path

        station = Path(__file__).resolve().parents[1] / "apps" / "station"
        if str(station) not in sys.path:
            sys.path.insert(0, str(station))
        from monkeyllm_station.policy import Policy, ScopedVine

        self._with_payroll(forest_rw)
        scoped = ScopedVine(vine_rw, Policy(
            forest="f", caps=frozenset({"read", "query", "tend"}),
            allow=("sales/",), tables={DATASET: ("sales",)}))
        out = scoped.call("tend", id=DATASET, sql="DELETE FROM payroll WHERE id = 42")
        assert out["error"]["code"] in ("E_FORBIDDEN", "E_QUERY_FORBIDDEN")


class TestMcpExposure:
    def test_tend_is_an_mcp_tool(self, forest_rw):
        from monkeyllm.server import build_server

        mcp = build_server(forest_root=forest_rw, writable=False)
        try:
            tools = anyio.run(mcp.list_tools)
            assert "tend" in {t.name for t in tools}
        finally:
            mcp._close()
