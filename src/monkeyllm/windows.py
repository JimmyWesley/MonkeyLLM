# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Time windows and periods (spec C.13, v0.52).

Every passport carries `created` and `updated`, git versions them and
`reindex` rebuilds them identically — so the forest has always known when
its material arrived. What it lacked was a way to say so. This module is
the arithmetic behind that: normalising a bound a caller wrote by hand into
the two dates a search actually uses, and folding a column of dates into the
periods that hold something.

Two rules shape all of it.

**A bound is expanded, never guessed.** `2026-08` means the whole of August
— its first day as a `since`, its last as an `until` — and anything that is
not one of the three accepted shapes is refused. A filter quietly dropped is
a lie about what was searched, told to a caller who will read the result as
covering their window.

**The label is derived from the boundary, not the other way round.** A week
is Monday to Sunday and its name is the ISO one; a caller never has to agree
with us about what "week 34" means, because every bucket carries the two
dates it stands for.
"""

from __future__ import annotations

import datetime as dt
import re

from monkeyllm.errors import E_SCHEMA, VineError

DATE_FIELDS = ("created", "updated")
GRANULARITIES = ("day", "week", "month", "year")
MAX_CALENDAR_BUCKETS = 120

_YEAR = re.compile(r"^(\d{4})$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_ACCEPTED = "YYYY, YYYY-MM or YYYY-MM-DD"


def _end_of_month(year: int, month: int) -> dt.date:
    return (dt.date(year, month, 1) + dt.timedelta(days=32)).replace(day=1) \
        - dt.timedelta(days=1)


def parse_bound(value, *, name: str, upper: bool) -> str:
    """One bound, expanded to a day. `upper` picks the period's last day."""
    if not isinstance(value, str):
        raise VineError(
            E_SCHEMA,
            f"{name} must be a date string ({_ACCEPTED}), got "
            f"{type(value).__name__}")
    raw = value.strip()
    try:
        if _DAY.match(raw):
            return dt.date.fromisoformat(raw).isoformat()
        m = _MONTH.match(raw)
        if m:
            year, month = int(m.group(1)), int(m.group(2))
            day = _end_of_month(year, month) if upper else dt.date(year, month, 1)
            return day.isoformat()
        y = _YEAR.match(raw)
        if y:
            year = int(y.group(1))
            return (dt.date(year, 12, 31) if upper else dt.date(year, 1, 1)).isoformat()
    except ValueError as e:
        raise VineError(E_SCHEMA, f"{name}: {e}",
                        hint=f"Dates are {_ACCEPTED}.") from e
    raise VineError(
        E_SCHEMA,
        f"{name} is not a date I can read: {value!r}",
        hint=f"Accepted: {_ACCEPTED}. A partial date means its whole period "
             "(since='2026-08' is the 1st, until='2026-08' is the 31st).",
    )


def parse_field(date_field) -> str:
    """The date a read is judged by — a passport field, and only that.

    "When it was indexed" is deliberately not offered: `_derived/` is
    disposable and rebuilt on demand, so a window over an indexing
    timestamp would mean one thing today and another after a `reindex`,
    with no way for a caller to know which (C.13.1 rule 9). The date a
    document entered the forest is already `created`.
    """
    field = date_field or "created"
    if field not in DATE_FIELDS:
        raise VineError(
            E_SCHEMA,
            f"date_field must be one of {list(DATE_FIELDS)}, got {field!r}",
            hint="The passport's dates are the only clock: an index "
                 "timestamp lives in the disposable layer and would mean "
                 "something else after a rebuild (spec C.13.1 rule 9).",
        )
    return field


def normalize_window(since=None, until=None, date_field=None) -> dict | None:
    """The C.13.1 window, or None when the caller asked for no window.

    Returned normalized because that is what the search will use, and what
    the caller can reuse without repeating the arithmetic.
    """
    field = parse_field(date_field)
    if since is None and until is None:
        return None
    lo = parse_bound(since, name="since", upper=False) if since is not None else None
    hi = parse_bound(until, name="until", upper=True) if until is not None else None
    if lo and hi and lo > hi:
        raise VineError(
            E_SCHEMA,
            f"since ({lo}) is later than until ({hi})",
            hint="A window whose start is after its end can hold nothing; "
                 "swap them.",
        )
    return {"since": lo, "until": hi, "date_field": field}


def window_sql(window: dict | None) -> tuple[list[str], list]:
    """The window as a predicate over the catalog's own columns.

    **Bare comparisons, never a function on the column.** A passport date
    is an ISO string, so `created >= ?` is already the right order — while
    `substr(created, 1, 10) >= ?` computes the same answer and throws away
    the index on the way, which on a large forest is the difference between
    a seek and a scan of everything.

    The upper bound is therefore EXCLUSIVE and one day past `until`: that
    keeps the comparison a plain range while still holding a column that
    carries a time (`2026-08-31T14:02` is inside a window that ends on the
    31st, and `<= '2026-08-31'` would have dropped it).

    `!= ''` is the C.13.1 rule 5 half: an undated node is not early and not
    late, so it belongs to no window at all — and an empty string sorts
    below every date, which would otherwise smuggle it into an
    upper-bound-only window. NULL is excluded by both comparisons already.
    """
    if not window:
        return [], []
    field = window["date_field"]
    where: list[str] = [f"{{n}}{field} != ''", f"{{n}}{field} IS NOT NULL"]
    params: list = []
    if window["since"]:
        where.append(f"{{n}}{field} >= ?")
        params.append(window["since"])
    if window["until"]:
        where.append(f"{{n}}{field} < ?")
        params.append(exclusive_end(window["until"]))
    return where, params


def exclusive_end(until: str) -> str:
    """The day after an inclusive upper bound."""
    return (dt.date.fromisoformat(until) + dt.timedelta(days=1)).isoformat()


# The period a date belongs to, as SQL over the column itself. One row per
# period comes back instead of one row per node, so a forest of 40,000
# nodes answers `calendar` with a dozen rows and SQLite does the counting.
#
# The week expression is the only interesting one: `%w` is 0 for Sunday, so
# `(%w + 6) % 7` is the number of days back to Monday — the same Monday
# `period_of` finds in Python, which is what the equivalence test checks.
PERIOD_SQL = {
    "day": "substr({col}, 1, 10)",
    "week": "date({col}, '-' || ((strftime('%w', {col}) + 6) % 7) || ' days')",
    "month": "substr({col}, 1, 7) || '-01'",
    "year": "substr({col}, 1, 4) || '-01-01'",
}


def period_sql(field: str, granularity: str, alias: str = "") -> str:
    if granularity not in GRANULARITIES:
        raise VineError(
            E_SCHEMA,
            f"granularity must be one of {list(GRANULARITIES)}, got {granularity!r}")
    return PERIOD_SQL[granularity].format(col=f"{alias}{field}")


def buckets_from_rows(rows, granularity: str, limit: int) -> dict:
    """The C.13.3 response, folded from (period_start, count, first, last).

    The aggregation happened in SQLite; what is left is naming each period
    and stating its two dates — and those come from the boundary the
    grouping produced, never from a label somebody has to agree with us
    about.
    """
    limit = min(max(1, int(limit)), MAX_CALENDAR_BUCKETS)
    buckets, first, last, total = [], None, None, 0
    for start, count, lo, hi in rows:
        if not start:
            continue
        label, since, until = period_of(dt.date.fromisoformat(str(start)[:10]),
                                        granularity)
        buckets.append({"period": label, "since": since, "until": until,
                        "nodes": int(count)})
        total += int(count)
        lo, hi = str(lo or "")[:10], str(hi or "")[:10]
        first = lo if lo and (first is None or lo < first) else first
        last = hi if hi and (last is None or hi > last) else last
    buckets.sort(key=lambda b: b["since"], reverse=True)
    return {"range": {"first": first, "last": last, "nodes": total},
            "buckets": buckets[:limit], "truncated": len(buckets) > limit}


def in_window(value, window: dict | None) -> bool:
    """The same decision in Python, for the scoped paths that cannot push a
    predicate into SQL. One rule, spelled twice — so the two are tested
    against each other rather than trusted."""
    if not window:
        return True
    if not value:
        return False
    day = str(value)[:10]
    if window["since"] and day < window["since"]:
        return False
    return not (window["until"] and day > window["until"])


def period_of(day: dt.date, granularity: str) -> tuple[str, str, str]:
    """(label, since, until) of the period `day` falls in."""
    if granularity == "day":
        return day.isoformat(), day.isoformat(), day.isoformat()
    if granularity == "week":
        monday = day - dt.timedelta(days=day.weekday())
        sunday = monday + dt.timedelta(days=6)
        iso_year, iso_week, _ = monday.isocalendar()
        return f"{iso_year}-W{iso_week:02d}", monday.isoformat(), sunday.isoformat()
    if granularity == "month":
        first = day.replace(day=1)
        return (f"{day.year:04d}-{day.month:02d}", first.isoformat(),
                _end_of_month(day.year, day.month).isoformat())
    if granularity == "year":
        return (f"{day.year:04d}", dt.date(day.year, 1, 1).isoformat(),
                dt.date(day.year, 12, 31).isoformat())
    raise VineError(
        E_SCHEMA,
        f"granularity must be one of {list(GRANULARITIES)}, got {granularity!r}")


def bucket_dates(values, granularity: str, limit: int) -> dict:
    """The same fold, done in Python over raw dates.

    The production path groups in SQLite (`period_sql`); this is the
    reference the suite compares it against, node by node, because two
    spellings of "which period is this date in" agree only where somebody
    checked. It is also what a caller of the library gets when it hands
    over a list of dates rather than a database.

    Empty periods are omitted on purpose: a three-year gap costs nothing to
    report, and the buckets that exist are exactly the answer to "which
    weeks have anything". Most recent first, because that is the end the
    question comes from.
    """
    if granularity not in GRANULARITIES:
        raise VineError(
            E_SCHEMA,
            f"granularity must be one of {list(GRANULARITIES)}, got {granularity!r}")
    limit = min(max(1, int(limit)), MAX_CALENDAR_BUCKETS)
    counts: dict[str, dict] = {}
    undated, first, last = 0, None, None
    for raw in values:
        text = str(raw or "")[:10]
        try:
            day = dt.date.fromisoformat(text)
        except ValueError:
            undated += 1
            continue
        first = day if first is None or day < first else first
        last = day if last is None or day > last else last
        label, lo, hi = period_of(day, granularity)
        bucket = counts.setdefault(
            label, {"period": label, "since": lo, "until": hi, "nodes": 0})
        bucket["nodes"] += 1
    ordered = sorted(counts.values(), key=lambda b: b["since"], reverse=True)
    return {
        "range": {"first": first.isoformat() if first else None,
                  "last": last.isoformat() if last else None,
                  "nodes": sum(b["nodes"] for b in counts.values())},
        "buckets": ordered[:limit],
        "undated": undated,
        "truncated": len(ordered) > limit,
    }


def nearest_periods(rows, window: dict | None, granularity: str = "month",
                    limit: int = 3) -> dict:
    """What a caller should have asked for (C.13.2).

    An empty window is a guess that missed, and the repair is a fact the
    catalog already holds: where the material actually is. Computed only on
    the empty path.
    """
    folded = buckets_from_rows(rows, granularity, MAX_CALENDAR_BUCKETS)
    anchor = (window or {}).get("since") or (window or {}).get("until")
    buckets = folded["buckets"]
    if anchor:
        buckets = sorted(buckets, key=lambda b: abs_days(b["since"], anchor))
    return {"range": folded["range"], "nearest": buckets[:limit]}


def abs_days(a: str, b: str) -> int:
    return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)
