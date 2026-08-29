# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The demonstratives that were only English (spec v0.67, C.6c).

`derive_terms` drops grammar so that `sniff`'s literal search is spent on
words that carry scent. The set it dropped grammar by carried `this` and
`that` and neither `esta` nor `este`, so "Sobre o que e esta floresta?"
reached the sweep's literal leg as a search for `esta` — and `sniff` folds
and finds a SUBSTRING, so that term matches inside `restart`, `timestamp`
and `estado`, scoring a flat hit on documents that have nothing to do with
the question. A junk term is not merely useless: `strength` is
`terms_hit / len(terms)`, so it also halves the score of the real one.

This is not a contract and this file is not asserting one — C.6b
deliberately does not enumerate the set. What is pinned here is the
behaviour the gap produced: a demonstrative is grammar in every language
the set claims to cover, and a word that carries meaning stays a term.
"""

from __future__ import annotations

import pytest

from monkeyllm.harvest import STOPWORDS, derive_terms


def test_the_portuguese_question_reaches_sniff_with_one_real_term():
    """The measured case, verbatim: the noun survives alone."""
    assert derive_terms("Sobre o que e esta floresta?") == ["floresta"]
    # And with the accent it is written with — the fold is what compares.
    assert derive_terms("Sobre o que é esta floresta?") == ["floresta"]


@pytest.mark.parametrize("query,kept,dropped", [
    ("esta floresta", {"floresta"}, {"esta"}),
    ("este documento", {"documento"}, {"este"}),
    ("estas decisoes", {"decisoes"}, {"estas"}),
    ("estes registos", {"registos"}, {"estes"}),
    ("essa politica", {"politica"}, {"essa"}),
    ("esse relatorio", {"relatorio"}, {"esse"}),
    ("aquele contrato", {"contrato"}, {"aquele"}),
    ("aquela reuniao", {"reuniao"}, {"aquela"}),
    ("aquilo mudou tudo", {"mudou"}, {"aquilo"}),
    ("isto e importante", {"importante"}, {"isto"}),
    ("isso quebrou o deploy", {"quebrou", "deploy"}, {"isso"}),
    # Spanish, on the same rule.
    ("esto significa algo", {"significa"}, {"esto"}),
    ("estos informes", {"informes"}, {"estos"}),
    ("aquel proyecto", {"proyecto"}, {"aquel"}),
    ("aquella decision", {"decision"}, {"aquella"}),
    ("aquellos contratos", {"contratos"}, {"aquellos"}),
])
def test_a_demonstrative_is_grammar_in_every_language_the_set_covers(
        query, kept, dropped):
    terms = set(derive_terms(query))
    assert kept <= terms
    assert not (dropped & terms)


@pytest.mark.parametrize("word", [
    # The nouns and verbs that live next door to the words added. A stopword
    # list earns its keep by what it does NOT swallow.
    "estado", "estados", "estatuto", "estimativa", "essencial", "esteira",
    "aquisicao", "estrutura", "estagio", "isolamento",
])
def test_a_content_word_is_never_swallowed(word):
    assert word not in STOPWORDS
    assert derive_terms(f"o {word} do projeto") == [word, "projeto"]


def test_the_english_rows_are_untouched():
    """The gap was one-sided and the repair is too: nothing English moved."""
    assert {"this", "that", "what", "which", "where", "when", "who",
            "does", "with", "from", "have", "about", "were"} <= STOPWORDS
    assert derive_terms("what does that mean for this deployment") \
        == ["mean", "deployment"]


def test_code_shaped_tokens_still_outrank_grammar():
    """C.6c v0.52's rule survives the wider set: a technical question is
    still searched by the tokens a technical corpus is searched by."""
    assert derive_terms("como corrigir esta 421 do MCP") \
        == ["421", "MCP", "corrigir"]
