# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""The Audit console (spec J.5.16, criterion F.157).

Read as source, for the reason `test_studio_calls` and `test_studio_i18n`
already give: the console is JavaScript, CI has no node, and every rule worth
guarding here is visible in the text.

The numbers themselves are the route's and the route has its own suite
(`test_station_audit.py`). What is checked here is narrower and is the thing
that actually goes wrong in a console: that it did not grow a second opinion
about them — a page summed locally, a saving folded into a spend, a hard-coded
table of error codes that goes stale the release after it is written.
"""

from __future__ import annotations

import re
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1] / "apps" / "studio" / "src"
AUDIT = (STUDIO / "views" / "Audit.jsx").read_text(encoding="utf-8")
API = (STUDIO / "api.js").read_text(encoding="utf-8")

# The filters J.4.3 names, and the address key each one rides on (J.5.16
# rule 5). The console may spell the keys as it likes; what it may not do is
# keep one of them somewhere the address cannot restore.
FILTER_KEYS = ("who", "call", "where", "outcome", "since", "until")


def code(text: str) -> str:
    """The source with its comments removed — prose about a rule is not the
    rule, and this file's own explanations name the things it forbids."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


BODY = code(AUDIT)


def test_the_cards_read_the_hosts_totals():
    """J.5.16 rule 2. A console that adds up its own page is describing the
    page size, and the number falls the moment somebody changes the limit."""
    assert "totals = log.data?.totals" in BODY
    for field in ("calls", "errors", "usd", "usd_saved", "cached", "people"):
        assert f"totals.{field}" in BODY, f"no card reads totals.{field}"
    # Nothing is derived from the rows: no reduce, no length-as-a-count, no
    # filter-then-count over `entries`.
    assert ".reduce(" not in BODY, "a total computed in the console"
    assert "rows.length" not in re.sub(r"rows\.length === 0", "", BODY), \
        "the page's length is not a total"


def test_the_saving_is_never_added_into_the_spend():
    """J.4.2's rule, on the surface that would hide it. The two figures come
    off one column and only `result` separates them: a single 'cost' covering
    both bills a deployment for the calls it avoided."""
    spend = re.findall(r"totals\.usd\b[^_]", BODY)
    assert spend, "the spend card must read totals.usd"
    assert not re.search(r"usd\s*\+\s*\w*usd_saved", BODY)
    assert not re.search(r"usd_saved\s*\+\s*\w*totals\.usd", BODY)
    # Both appear, in two different tiles: one figure would be the bug.
    assert BODY.count("totals.usd_saved") >= 1


def test_an_unpriced_call_is_not_shown_as_free():
    """J.5.16 rule 4. A local provider publishes no catalogue, and rendering
    its calls at $0.00 invents a price the deployment never had."""
    assert "totals.unpriced" in BODY, "the spend card must say when nothing was priced"
    assert "audit.tokens_only" in BODY, "an unpriced row shows its tokens, not a price"
    # The row's money is gated on the provider having actually priced it.
    assert re.search(r"e\.priced\s*\?", BODY)


def test_an_unknown_refusal_renders_as_itself():
    """J.5.16 rule 6. A Station newer than this console must not lose the
    reason it refused: there is no table of codes to fall out of."""
    assert re.search(r"\{e\.error_code\}", BODY)
    for invented in ("E_FORBIDDEN", "E_NOT_FOUND", "E_SCHEMA"):
        assert invented not in BODY, \
            f"{invented} is spelled in the console; codes are the host's"


def test_every_filter_rides_the_address():
    """J.5.8/J.5.16 rule 5: a filtered view is a link somebody can send."""
    for key in FILTER_KEYS:
        assert f"useRouteState('{key}'" in BODY, f"{key} is not in the address"
    assert "useState" not in BODY, \
        "a filter kept in component state is a filter no address restores"


def test_the_filter_choices_come_from_the_response():
    """J.5.16 rule 8. A list carried in the console goes stale silently: the
    filter simply stops offering the call that was added."""
    assert "facets = log.data?.filters" in BODY
    for facet in ("principals", "primitives", "forests"):
        assert f"facets.{facet}" in BODY


def test_the_timestamp_is_read_off_the_field_the_row_carries():
    """The column is `ts` and always was. The console read `e.at`, so the
    one field every row of this log has ever had rendered empty."""
    assert "e.ts" in BODY
    assert "e.at" not in BODY


def test_the_forests_own_clock_is_reported_apart_from_the_providers():
    """J.4.2: two clocks, because the fix for each is a different purchase."""
    assert "e.ms" in BODY and "e.model_ms" in BODY
    assert not re.search(r"e\.ms\s*\+\s*e\.model_ms", BODY)


def test_the_client_sends_the_filters_and_drops_the_empty_ones():
    """`?primitive=` would be a filter for the call named "" — the route
    would apply it and answer nothing, which reads as an empty log."""
    call = re.search(r"audit: \(params = \{\}\) => \{(.*?)\n  \},", API, re.S)
    assert call, "api.audit must take the filters as an object"
    assert "URLSearchParams" in call.group(1)
    assert "!== ''" in call.group(1)
