# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The query is derived before it is searched (spec C.1.2, F.147-F.148).

`locate` used to hand the whole sentence to FTS5 — split on whitespace,
each token quoted, joined by OR — so every article and preposition in a
question was a search term with a vote. `harvest` has always derived terms
first; the entry search it calls did not.

The half worth testing hardest is rule 2, not rule 1. Derivation can return
NOTHING: "api", "sql" and a sentence made entirely of grammar all derive to
the empty list, because the floor that keeps grammar out also keeps short
lowercase tokens out. A `locate` that passed that through would answer
nothing at all to a caller who typed one word — which is precisely the
failure C.1.1 exists to prevent, manufactured on purpose. So the fallback
is asserted per-query and by equivalence to the raw path, not by eyeball.
"""

from __future__ import annotations

import pytest

from monkeyllm.harvest import derive_terms

# Queries whose derivation is empty. Each MUST behave exactly as it did
# before v0.70. They are not hypothetical: `api` and `sql` are how a
# technical corpus is actually searched.
EMPTY_DERIVATION = ["api", "sql", "ui", "o que e isso", "qual e o uso",
                    "como", "quem sou eu"]


def _raw_ids(vine, query, k=5):
    """What `fts_search` returns for the raw sentence — the pre-v0.70 path."""
    cand = max(k * 5, 25)
    return [r["id"] for r in vine.catalog.fts_search(query, limit=cand)]


def _located(vine, query, k=5):
    return [r["id"] for r in vine.locate(query, k=k).get("results", [])]


@pytest.mark.parametrize("query", EMPTY_DERIVATION)
def test_empty_derivation_falls_back_to_the_sentence(vine_ro, query):
    """F.148: rule 2. The derivation is empty, so the search is the raw
    query and the caller cannot tell v0.70 happened."""
    assert derive_terms(query) == [], "probe is wrong: this query derives terms"
    got = _located(vine_ro, query)
    want_pool = _raw_ids(vine_ro, query)
    # locate ranks and budgets on top of the candidate pool; the assertion
    # that matters is that the pool is the raw one, i.e. the results are
    # drawn from it and a non-empty pool did not become an empty answer.
    assert all(i in want_pool for i in got)
    assert bool(got) == bool(want_pool)


def test_a_single_short_token_still_finds_something(vine_ro):
    """The concrete shape of the failure rule 2 prevents: one word in, and
    the forest holds it. Before the fallback existed this returned []."""
    ids = _located(vine_ro, "mcp")
    assert ids, "a one-word query must not be consumed by the filter"


def test_non_empty_derivation_searches_the_derived_terms(vine_ro):
    """F.148: rule 1. A question with grammar searches what survives it."""
    question = "what is the difference between the block loop and speculative decoding"
    derived = derive_terms(question)
    assert derived and len(derived) < len(question.split())
    assert _located(vine_ro, question) == _located(vine_ro, " ".join(derived))


def test_grammar_no_longer_reaches_the_index(vine_ro):
    """The behaviour change itself, stated as a difference rather than as a
    score: the raw sentence and the derived one build different candidate
    pools, and `locate` now uses the second."""
    question = "what is the central difference of the block loop"
    raw = _raw_ids(vine_ro, question)
    derived = _raw_ids(vine_ro, " ".join(derive_terms(question)))
    assert raw != derived, "probe is stale: this question no longer has grammar"
    assert _located(vine_ro, question) == [i for i in derived][:5]


def test_scope_window_and_filters_are_untouched(vine_ro):
    """C.1.2 rule 3: this section changes which terms are searched and
    nothing about what happens to what is found."""
    out = vine_ro.locate("speculative decoding", k=3, scope="notes")
    assert len(out["results"]) <= 3
    assert all(r["kind"] == "note" for r in out["results"])
    typed = vine_ro.locate("speculative decoding", type_filter="concept")
    assert all(r["type"] == "concept" for r in typed["results"])


def test_the_empty_path_still_explains_itself(vine_ro):
    """C.1.1 is unchanged: a query that genuinely matches nothing still
    carries `searched` and the `sniff` hint. The point of rule 2 is that
    this path is reached for the right reason, never because the filter
    ate the question."""
    out = vine_ro.locate("zzqx-nothing-here-at-all-zzqx")
    assert out["results"] == []
    assert "searched" in out and out.get("hint")
