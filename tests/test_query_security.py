"""Part F criterion 4: query() rejects every write/escape attempt."""

import sqlite3

import pytest

from monkeyllm.errors import E_QUERY_FORBIDDEN, E_TIMEOUT, VineError

DS = "vendas/relatorio-q1-2026"

INJECTIONS = [
    "SELECT 1; DROP TABLE vendas",
    "DROP TABLE vendas",
    "DELETE FROM vendas",
    "INSERT INTO vendas VALUES ('x','x','x','x','x',1,1,1)",
    "UPDATE vendas SET valor = 0",
    "ALTER TABLE vendas ADD COLUMN hacked TEXT",
    "CREATE TABLE pwn (x)",
    "ATTACH DATABASE 'outro.db' AS pwn",
    "PRAGMA journal_mode = DELETE",
    "PRAGMA writable_schema = 1",
    "WITH x AS (SELECT 1) INSERT INTO vendas SELECT * FROM x",
    "VACUUM",
    "SELECT * FROM vendas; PRAGMA writable_schema=1",
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
            vine_ro.query("conceitos/rag", "SELECT 1")
        assert e.value.code == E_QUERY_FORBIDDEN

    def test_database_not_mutated_after_suite(self, vine_ro):
        r = vine_ro.query(DS, "SELECT COUNT(*) AS n FROM vendas")
        assert r["rows"][0][0] == 600


class TestQueryContract:
    def test_columnar_format(self, vine_ro):
        r = vine_ro.query(DS, "SELECT regiao, SUM(valor) AS total FROM vendas GROUP BY regiao ORDER BY total DESC")
        assert set(r.keys()) == {"columns", "rows", "row_count", "limited", "elapsed_ms"}
        assert r["columns"] == ["regiao", "total"]
        assert r["rows"][0][0] == "Sudeste"  # rigged winner
        assert isinstance(r["rows"][0], list)

    def test_limit_injected(self, vine_ro):
        r = vine_ro.query(DS, "SELECT * FROM vendas")
        assert r["row_count"] == 200
        assert r["limited"] is True

    def test_explicit_limit_respected(self, vine_ro):
        r = vine_ro.query(DS, "SELECT * FROM vendas LIMIT 5")
        assert r["row_count"] == 5
        assert r["limited"] is False

    def test_with_cte_allowed(self, vine_ro):
        r = vine_ro.query(DS, "WITH t AS (SELECT valor FROM vendas) SELECT COUNT(*) FROM t")
        assert r["row_count"] == 1

    def test_readonly_connection_blocks_writes_in_depth(self, vine_ro):
        node = vine_ro.forest.read(DS)
        db = vine_ro.forest.payload_path(node)
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM vendas")
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
