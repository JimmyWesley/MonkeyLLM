# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Where the material sits in time (spec C.13, criterion F.64).

"Last week I wrote something about this" is how a person addresses their own
knowledge, and the forest has always known the answer — every passport
carries `created` and `updated`. What it lacked was a way to use them, so an
agent asked about a period had to sweep everything and hope the ranking
floated something recent.

Three of these tests are the load-bearing ones, and each guards a way the
obvious implementation is wrong:

* `test_the_sql_grouping_agrees_with_the_python_fold` — the production path
  groups in SQLite and the reference fold is in Python; two spellings of
  "which period is this date in" agree only where somebody compared them.
* `test_the_sql_scope_agrees_with_in_scope` — same rule, applied to the
  policy prefixes that make a scoped `calendar` a GROUP BY instead of a walk.
* `test_an_empty_window_says_whether_the_window_was_the_reason` — the whole
  point of C.13.2. A window that holds nothing and a question that matched
  nothing are different mistakes with different repairs.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

import pytest

from conftest import build_forest

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))

from monkeyllm.errors import VineError  # noqa: E402
from monkeyllm.windows import (  # noqa: E402
    bucket_dates,
    buckets_from_rows,
    normalize_window,
    parse_bound,
)

FOREST = "forest-fixture"


def _spread_dates(root: Path) -> None:
    """Give the fixture a history: a forest built in one afternoon has one
    date, and a calendar over one date proves nothing."""
    for i, f in enumerate(sorted(root.rglob("*.md"))):
        day = dt.date(2026, 1 + (i % 8), 1 + (i % 27))
        text = f.read_text(encoding="utf-8")
        text = re.sub(r"^created: .*$", f"created: {day.isoformat()}",
                      text, count=1, flags=re.M)
        f.write_text(text, encoding="utf-8")


@pytest.fixture(scope="session")
def dated_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("dated-root")
    build_forest(root / FOREST)
    _spread_dates(root / FOREST)
    return root


@pytest.fixture(scope="session")
def dated(dated_root):
    from monkeyllm import Vine

    v = Vine(dated_root / FOREST, writable=True)
    v.reindex()
    yield v
    v.close()


# --- C.13.1: bounds ---------------------------------------------------------

@pytest.mark.parametrize("raw,upper,expected", [
    ("2026", False, "2026-01-01"),
    ("2026", True, "2026-12-31"),
    ("2026-02", False, "2026-02-01"),
    ("2026-02", True, "2026-02-28"),      # and a leap year is the calendar's
    ("2024-02", True, "2024-02-29"),
    ("2026-08-19", True, "2026-08-19"),
])
def test_a_partial_bound_means_its_whole_period(raw, upper, expected):
    assert parse_bound(raw, name="since", upper=upper) == expected


@pytest.mark.parametrize("bad", ["last week", "19/08/2026", "2026-13", "",
                                 "2026-02-30", 20260819])
def test_a_bound_it_cannot_read_is_refused_not_ignored(bad):
    """A filter silently dropped is a lie about what was searched, told to a
    caller who will read the result as covering their window."""
    with pytest.raises(VineError) as caught:
        normalize_window(since=bad)
    assert caught.value.code == "E_SCHEMA"


def test_a_backwards_window_is_refused():
    with pytest.raises(VineError):
        normalize_window(since="2026-08", until="2026-01")


def test_only_the_passport_is_a_clock():
    """C.13.1 rule 9: `_derived/` is disposable, so a window over an
    indexing timestamp would mean something else after a rebuild."""
    with pytest.raises(VineError) as caught:
        normalize_window(since="2026-01", date_field="indexed")
    assert "created" in caught.value.message and "updated" in caught.value.message


def test_a_window_is_never_a_default():
    assert normalize_window() is None
    assert normalize_window(date_field="updated") is None


# --- C.13.1: windowed reads -------------------------------------------------

def test_a_window_narrows_a_locate_and_is_echoed(dated):
    out = dated.locate("stigmergy", since="2026-03-01", until="2026-03-31", k=5)
    assert out["window"] == {"since": "2026-03-01", "until": "2026-03-31",
                             "date_field": "created"}
    for hit in out["results"]:
        created = dated.catalog.get(hit["id"])["created"]
        assert "2026-03-01" <= created[:10] <= "2026-03-31"


def test_a_partial_bound_and_its_expansion_are_one_search(dated):
    a = dated.locate("model", since="2026-03", until="2026-03", k=5)
    b = dated.locate("model", since="2026-03-01", until="2026-03-31", k=5)
    assert [h["id"] for h in a["results"]] == [h["id"] for h in b["results"]]


def test_k_is_still_met_inside_a_window(dated):
    """C.13.1 rule 3: filtering the ranked top-k AFTER the cut returns fewer
    than k while the forest holds more, and the caller reads a scarcity the
    implementation invented."""
    year = dated.locate("the", since="2026-01-01", until="2026-12-31", k=5)
    assert len(year["results"]) == 5


def test_a_windowed_sniff_scans_only_that_window(dated):
    everything = dated.sniff(["monkeyllm"], k=20)
    windowed = dated.sniff(["monkeyllm"], since="2026-02-01",
                           until="2026-02-28", k=20)
    assert windowed["scanned_nodes"] < everything["scanned_nodes"]
    for hit in windowed["results"]:
        assert dated.catalog.get(hit["id"])["created"][:10].startswith("2026-02")


def test_a_windowed_scan_and_harvest_carry_the_window(dated):
    scanned = dated.scan("_index", recursive=True, since="2026-04-01",
                         until="2026-04-30")
    assert scanned["window"]["since"] == "2026-04-01"
    from monkeyllm.harvest import harvest

    swept = harvest(dated, "pheromone stigmergy", since="2026-01-01",
                    until="2026-12-31", k=2)
    assert swept["window"]["until"] == "2026-12-31"


def test_an_undated_node_is_in_no_window(dated_root, tmp_path):
    from monkeyllm import Vine

    root = tmp_path / "undated"
    build_forest(root)
    victim = next(p for p in sorted(root.rglob("*.md"))
                  if not p.name.startswith("_"))
    victim.write_text(
        re.sub(r"^created: .*$", "created: ", victim.read_text(encoding="utf-8"),
               count=1, flags=re.M), encoding="utf-8")
    node_id = re.search(r"^id: (.+)$", victim.read_text(encoding="utf-8"),
                        re.M).group(1).strip()
    v = Vine(root, writable=True)
    v.reindex()
    try:
        wide = v.locate("the", since="2000-01-01", until="2099-12-31", k=20)
        assert wide.get("undated_excluded", 0) >= 1
        assert node_id not in [h["id"] for h in wide["results"]]
        # …and it is still reachable without a window: a window narrows a
        # search, it does not delete a node.
        assert v.look(node_id)["id"] == node_id
        assert v.calendar()["undated"] >= 1
    finally:
        v.close()


# --- C.13.2: the empty window explains itself -------------------------------

def test_an_empty_window_says_whether_the_window_was_the_reason(dated):
    # (a) the window itself is empty: the question was never tested
    empty = dated.locate("stigmergy", since="2020-01-01", until="2020-12-31")
    assert empty["results"] == [] and empty["matched_window"] == 0
    assert "2026" in empty["hint"]        # where the material actually is
    assert "calendar()" in empty["hint"]

    # (b) the window held material and the question missed it
    missed = dated.locate("zzqqx-nothing-anywhere", since="2026-01-01",
                          until="2026-12-31")
    assert missed["results"] == [] and missed["matched_window"] > 0
    assert "not the reason" in missed["hint"]


def test_a_read_without_a_window_carries_neither(dated):
    out = dated.locate("zzqqx-nothing-anywhere")
    assert "window" not in out and "matched_window" not in out
    assert "searched" in out            # C.1.1 still applies


# --- C.13.3: the calendar ---------------------------------------------------

def test_the_calendar_is_most_recent_first_and_omits_empty_periods(dated):
    cal = dated.calendar(granularity="month", limit=24)
    periods = [b["period"] for b in cal["buckets"]]
    assert periods == sorted(periods, reverse=True)
    assert all(b["nodes"] > 0 for b in cal["buckets"])
    assert cal["range"]["first"] <= cal["range"]["last"]
    assert cal["undated"] == 0


def test_a_bucket_is_the_query(dated):
    """The map hands back the query: no arithmetic between finding a period
    and searching it."""
    cal = dated.calendar(granularity="month", limit=3)
    bucket = cal["buckets"][0]
    found = dated.scan("_index", recursive=True, since=bucket["since"],
                       until=bucket["until"], limit=50)
    assert len(found["nodes"]) == bucket["nodes"] or found["truncated"]


def test_weeks_are_iso_and_start_on_monday(dated):
    cal = dated.calendar(granularity="week", limit=6)
    for bucket in cal["buckets"]:
        start = dt.date.fromisoformat(bucket["since"])
        end = dt.date.fromisoformat(bucket["until"])
        assert start.weekday() == 0 and end.weekday() == 6
        iso_year, iso_week, _ = start.isocalendar()
        assert bucket["period"] == f"{iso_year}-W{iso_week:02d}"


def test_the_calendar_takes_a_window_and_a_scope(dated):
    half = dated.calendar(granularity="month", since="2026-05-01")
    assert all(b["since"] >= "2026-05-01" or b["until"] >= "2026-05-01"
               for b in half["buckets"])
    scoped = dated.calendar(scope="concepts", granularity="year")
    assert scoped["range"]["nodes"] < dated.calendar(granularity="year")["range"]["nodes"]


def test_an_unknown_granularity_is_refused(dated):
    with pytest.raises(VineError):
        dated.calendar(granularity="fortnight")


def test_the_sql_grouping_agrees_with_the_python_fold(dated):
    """The production path groups in SQLite; `bucket_dates` is the reference
    fold in Python. Two spellings of one rule agree only where compared."""
    for granularity in ("day", "week", "month", "year"):
        from_sql = buckets_from_rows(
            dated.catalog.date_buckets("created", granularity), granularity, 120)
        from_python = bucket_dates(
            dated.catalog.date_column("created"), granularity, 120)
        assert from_sql["buckets"] == from_python["buckets"], granularity
        assert from_sql["range"] == from_python["range"], granularity


# --- J.3: a map is not a size oracle ---------------------------------------

def test_the_sql_scope_agrees_with_in_scope(dated):
    from monkeyllm_station.policy import Policy

    ids = [r["id"] for r in
           dated.catalog.conn.execute("SELECT id FROM nodes").fetchall()]
    for allow, deny in ((("concepts/",), ()), (("",), ("people/",)),
                        (("projects/", "notes/"), ("projects/monkeyllm/",))):
        policy = Policy(forest=FOREST, allow=allow, deny=deny)
        where, params = policy.sql_scope()
        counted = dated.catalog.count_nodes(where, params)
        assert counted == sum(1 for i in ids if policy.in_scope(i)), (allow, deny)


def test_a_scoped_calendar_counts_only_what_the_scope_holds(dated):
    from monkeyllm_station.policy import Policy, ScopedVine

    scoped = ScopedVine(dated, Policy(forest=FOREST, allow=("concepts/",)))
    mine = scoped.calendar(granularity="year")
    everything = dated.calendar(granularity="year")
    assert mine["range"]["nodes"] < everything["range"]["nodes"]
    assert sum(b["nodes"] for b in mine["buckets"]) == mine["range"]["nodes"]


def test_a_scoped_empty_window_never_quotes_the_whole_forest(dated):
    """The hint is prose, but "this forest holds 82 nodes from January to
    August" is a measurement — and a scoped caller must not read one about a
    region it was never granted. Same oracle C.1.1 refused for `searched`,
    arriving through a sentence."""
    from monkeyllm_station.policy import Policy, ScopedVine

    scoped = ScopedVine(dated, Policy(forest=FOREST, allow=("concepts/",)))
    out = scoped.locate("stigmergy", since="2020-01-01", until="2020-12-31")
    assert out["results"] == [] and out["matched_window"] == 0

    total = dated.catalog.count_nodes()
    mine = scoped.calendar(granularity="year")["range"]["nodes"]
    assert out["searched"] < total
    assert f"{total} dated node" not in out["hint"]
    assert f"{mine} dated node" in out["hint"]


def test_the_window_uses_the_index_rather_than_scanning(dated):
    """The performance property, asserted rather than assumed.

    `created >= ?` seeks; `substr(created, 1, 10) >= ?` computes the same
    answer and scans the whole table. The second is the natural thing to
    write when a column might hold a timestamp, which is exactly why it
    needs a test standing in front of it.
    """
    from monkeyllm.windows import window_sql

    where, params = window_sql(normalize_window("2026-02-01", "2026-02-28"))
    clauses = " AND ".join(c.format(n="") for c in where)
    plan = " ".join(
        row[-1] for row in dated.catalog.conn.execute(
            f"EXPLAIN QUERY PLAN SELECT count(*) FROM nodes WHERE {clauses}",
            params))
    assert "idx_nodes_created" in plan, plan
    assert "SCAN nodes" not in plan, plan


def test_the_calendar_reads_the_index_and_groups_in_sqlite(dated):
    from monkeyllm.windows import period_sql

    plan = " ".join(
        row[-1] for row in dated.catalog.conn.execute(
            "EXPLAIN QUERY PLAN SELECT " + period_sql("created", "month") +
            ", count(*) FROM nodes WHERE created != '' GROUP BY 1"))
    assert "idx_nodes_created" in plan, plan
    assert "GROUP BY" in plan.upper()
