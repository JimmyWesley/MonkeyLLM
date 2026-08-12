# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Part F criterion 4: query() rejects every write/escape attempt."""

import sqlite3

import pytest

from monkeyllm.errors import E_QUERY_FORBIDDEN, E_TIMEOUT, VineError

DS = "sales/report-q1-2026"

INJECTIONS = [
    "SELECT 1; DROP TABLE sales",
    "DROP TABLE sales",
    "DELETE FROM sales",
    "INSERT INTO sales VALUES ('x','x','x','x','x',1,1,1)",
    "UPDATE sales SET value = 0",
    "ALTER TABLE sales ADD COLUMN hacked TEXT",
    "CREATE TABLE pwn (x)",
    "ATTACH DATABASE 'other.db' AS pwn",
    "PRAGMA journal_mode = DELETE",
    "PRAGMA writable_schema = 1",
    "WITH x AS (SELECT 1) INSERT INTO sales SELECT * FROM x",
    "VACUUM",
    "SELECT * FROM sales; PRAGMA writable_schema=1",
]


class TestInjectionSuite:
    @pytest.mark.parametrize("sql", INJECTIONS)
    def test_rejected(self, vine_ro, sql):
        with pytest.raises(VineError) as e:
            vine_ro.query(DS, sql)
        assert e.value.code == E_QUERY_FORBIDDEN

    def test_must_start_with_select_or_with(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.query(DS, "EXPLAIN SELECT 1")
        assert e.value.code == E_QUERY_FORBIDDEN

    def test_non_dataset_node_rejected(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.query("concepts/rag", "SELECT 1")
        assert e.value.code == E_QUERY_FORBIDDEN

    def test_database_not_mutated_after_suite(self, vine_ro):
        r = vine_ro.query(DS, "SELECT COUNT(*) AS n FROM sales")
        assert r["rows"][0][0] == 600


class TestQueryContract:
    def test_columnar_format(self, vine_ro):
        r = vine_ro.query(DS, "SELECT region, SUM(value) AS total FROM sales GROUP BY region ORDER BY total DESC")
        assert set(r.keys()) == {"columns", "rows", "row_count", "limited", "elapsed_ms"}
        assert r["columns"] == ["region", "total"]
        assert r["rows"][0][0] == "Southeast"  # rigged winner
        assert isinstance(r["rows"][0], list)

    def test_limit_injected(self, vine_ro):
        r = vine_ro.query(DS, "SELECT * FROM sales")
        # `limited` reports the injected LIMIT 200 being reached — what the
        # *query* matched — and is decided before C.5.1's token budget
        # trims what is *returned*. The two are independent by design.
        assert r["limited"] is True
        assert 0 < r["row_count"] <= 200

    def test_explicit_limit_respected(self, vine_ro):
        r = vine_ro.query(DS, "SELECT * FROM sales LIMIT 5")
        assert r["row_count"] == 5
        assert r["limited"] is False

    def test_with_cte_allowed(self, vine_ro):
        r = vine_ro.query(DS, "WITH t AS (SELECT value FROM sales) SELECT COUNT(*) FROM t")
        assert r["row_count"] == 1

    def test_readonly_connection_blocks_writes_in_depth(self, vine_ro):
        node = vine_ro.forest.read(DS)
        db = vine_ro.forest.payload_path(node)
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM sales")
        conn.close()

    @pytest.mark.timeout(15)
    def test_runaway_query_times_out(self, vine_ro):
        sql = (
            "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) "
            "SELECT COUNT(*) FROM c"
        )
        with pytest.raises(VineError) as e:
            vine_ro.query(DS, sql)
        assert e.value.code == E_TIMEOUT


def test_an_unknown_name_says_what_is_there(tmp_path):
    """C.5 (v0.46): an agent that has not `look`ed guesses the table from
    the node's id — a reasonable guess, normally wrong. Without the hint it
    spends a whole hop discovering what the failing call already had open."""
    from monkeyllm.forest import init_forest
    from monkeyllm.gardener import Gardener
    from monkeyllm.vine import Vine

    root = tmp_path / "forest"
    init_forest(root, title="T")
    src = tmp_path / "src"
    src.mkdir()
    (src / "sales.csv").write_text("region,total\nSouth,10\n", encoding="utf-8")
    vine = Vine(root, writable=True)
    Gardener(vine, hooks=[]).adopt(src)

    with pytest.raises(VineError) as caught:
        vine.query("sales", "SELECT * FROM sales_report")
    assert "no such table" in caught.value.message
    assert caught.value.hint == "Tables in this dataset: sales."

    with pytest.raises(VineError) as caught:
        vine.query("sales", "SELECT nope FROM sales")
    assert "no such column" in caught.value.message
    assert "sales(region, total)" in caught.value.hint

    # A statement refused by the guards is not a naming mistake, and must
    # not be dressed up as one.
    with pytest.raises(VineError) as caught:
        vine.query("sales", "DROP TABLE sales")
    assert caught.value.hint is None
