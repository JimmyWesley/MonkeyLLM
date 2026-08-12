# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""C.5.1 + C.5.2 (v0.47): the result is budgeted, and invalid is not forbidden.

`query` was the only read primitive without a token bound — a row cap of
200 and no ceiling, so `SELECT *` on a wide table returned tens of
thousands of tokens into a loop that carries its history forward. And
every SQLite failure wore the code for attempting a write, so a typo was
indistinguishable from a policy denial.
"""

import pytest

from monkeyllm.errors import E_QUERY_FORBIDDEN, E_QUERY_INVALID, VineError
from monkeyllm.models import NodeSpec
from monkeyllm.vine import BUDGET_QUERY
from monkeyllm.tokens import estimate_payload_tokens

WIDE = "sales/wide-export"
WIDE_COLUMNS = 141
WIDE_ROWS = 40


@pytest.fixture()
def wide(vine_rw):
    """A dataset shaped like the ERP export that exposed all of this.

    Planted `adopted=True` (G.2.5): C.7.1's <=50-column limit guards a
    model inventing DDL, not real data arriving from a file.
    """
    columns = {f"col_{i:03d}": "TEXT" for i in range(WIDE_COLUMNS)}
    # Cells sized like the export's, not like a toy's: descriptions, names
    # and formatted currency, ~58 characters. Width alone is not the cost —
    # width times cell length is, and a row of tiny cells would let 141
    # columns slip under the budget and prove nothing.
    rows = [[f"{i:03d}-{c:03d}-" + "abcdefghij" * 5 for c in range(WIDE_COLUMNS)]
            for i in range(WIDE_ROWS)]
    vine_rw.plant(NodeSpec(
        id=WIDE, type="dataset", title="Wide export", parent="sales/_index",
        summary="A 141-column export, one table, forty rows.",
        schema={"report": {"columns": columns}}, rows={"report": rows},
    ), adopted=True)
    return vine_rw


class TestResultBudget:
    def test_select_star_on_a_wide_table_keeps_no_rows_and_all_columns(self, wide):
        r = wide.query(WIDE, "SELECT * FROM report")
        # Not one row of this table fits, and that is the honest answer:
        # the columns are the map back, so they survive whole.
        assert r["rows"] == []
        assert r["row_count"] == 0
        assert r["truncated"] is True
        assert len(r["columns"]) == WIDE_COLUMNS
        assert estimate_payload_tokens(r) <= BUDGET_QUERY * 2  # hint included

    def test_the_refused_result_says_how_to_ask_again(self, wide):
        r = wide.query(WIDE, "SELECT * FROM report")
        hint = r["hint"]
        assert str(WIDE_COLUMNS) in hint          # how wide
        assert str(WIDE_ROWS) in hint             # how many matched
        assert "column" in hint.lower()           # what to change

    def test_the_hint_says_the_missing_rows_exist(self, wide):
        """A live walk read "truncated to 5 of 15" as "only 5 rows matched"
        and offered them as the answer. Truncation is never absence, and the
        sentence that says so must come before the advice."""
        for sql in ("SELECT * FROM report",
                    "SELECT " + ", ".join(f"col_{i:03d}" for i in range(20))
                    + " FROM report"):
            hint = wide.query(WIDE, sql)["hint"]
            assert "exist" in hint
            assert "not by your filter" in hint or "Nothing is missing" in hint

    def test_naming_columns_returns_the_rows_untruncated(self, wide):
        r = wide.query(WIDE, "SELECT col_000, col_001 FROM report")
        assert r["row_count"] == WIDE_ROWS
        assert r.get("truncated") is not True
        assert "hint" not in r

    def test_an_aggregate_is_never_truncated(self, wide):
        r = wide.query(WIDE, "SELECT COUNT(*) FROM report")
        assert r["rows"] == [[WIDE_ROWS]]
        assert r.get("truncated") is not True

    def test_partial_truncation_keeps_whole_rows_and_counts_them(self, wide):
        projection = ", ".join(f"col_{i:03d}" for i in range(20))
        r = wide.query(WIDE, f"SELECT {projection} FROM report")
        assert r["truncated"] is True
        assert 0 < r["row_count"] < WIDE_ROWS
        assert r["row_count"] == len(r["rows"])
        for row in r["rows"]:
            assert len(row) == 20  # whole rows dropped, never a sliced one
        assert f"of {WIDE_ROWS} rows" in r["hint"]

    def test_truncated_and_limited_are_independent(self, vine_ro):
        """`limited` is what the query matched; `truncated` is what came back."""
        r = vine_ro.query("sales/report-q1-2026", "SELECT * FROM sales")
        assert r["limited"] is True        # the injected LIMIT 200 was reached
        assert r["row_count"] == len(r["rows"])
        if r.get("truncated"):
            assert r["row_count"] < 200

    def test_a_narrow_result_is_unchanged(self, vine_ro):
        r = vine_ro.query("sales/report-q1-2026", "SELECT COUNT(*) AS n FROM sales")
        assert set(r) == {"columns", "rows", "row_count", "limited", "elapsed_ms"}


class TestInvalidIsNotForbidden:
    def test_unknown_table_is_invalid_and_names_what_exists(self, wide):
        with pytest.raises(VineError) as e:
            wide.query(WIDE, "SELECT * FROM wide_export")
        assert e.value.code == E_QUERY_INVALID
        assert "report" in (e.value.hint or "")

    def test_unknown_column_is_invalid_and_names_what_exists(self, wide):
        with pytest.raises(VineError) as e:
            wide.query(WIDE, "SELECT nonexistent FROM report")
        assert e.value.code == E_QUERY_INVALID
        assert "col_000" in (e.value.hint or "")

    def test_syntax_error_is_invalid(self, wide):
        with pytest.raises(VineError) as e:
            wide.query(WIDE, "SELECT FROM WHERE report")
        assert e.value.code == E_QUERY_INVALID

    @pytest.mark.parametrize("sql", [
        "DROP TABLE report",
        "SELECT 1; DROP TABLE report",
        "ATTACH DATABASE 'other.db' AS pwn",
        "EXPLAIN SELECT 1",
    ])
    def test_the_guard_still_forbids(self, wide, sql):
        """The split must not soften the guard: what it refuses, it refuses."""
        with pytest.raises(VineError) as e:
            wide.query(WIDE, sql)
        assert e.value.code == E_QUERY_FORBIDDEN

    def test_a_non_dataset_node_is_forbidden_not_invalid(self, wide):
        with pytest.raises(VineError) as e:
            wide.query("concepts/rag", "SELECT 1")
        assert e.value.code == E_QUERY_FORBIDDEN


class TestTheManualStatesTheWidth:
    def test_a_wide_table_warns_and_still_names_every_column(self, wide):
        body = wide.pick(WIDE)["body"]
        assert f"has {WIDE_COLUMNS} columns" in body
        assert "SELECT * FROM report LIMIT 5" not in body  # would not fit
        assert "col_140" in body                           # all of them, still

    def test_a_narrow_table_keeps_its_select_star_example(self):
        """Generated directly: the fixture's dataset carries an author's own
        manual, which C.7.1 rule 4 keeps verbatim."""
        from monkeyllm.models import dataset_map
        body = dataset_map({"t": {"a": "TEXT", "b": "INTEGER"}})
        assert "SELECT * FROM t LIMIT 5" in body
        assert "columns, so" not in body
