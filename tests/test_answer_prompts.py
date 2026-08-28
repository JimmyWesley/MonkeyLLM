# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""What the answering prompts may not leave out (J.10.3, J.10.5, v0.67).

How a prompt is worded is implementation freedom and stays so — these pins
are deliberately loose substrings, not the sentences themselves, so wording
can be tuned without a test to repair. What is pinned is the *fact stated*,
for the reason J.10.8 gave about the reply cap: a constraint a model can
only discover by hitting it is a constraint the model was never given, and
here being hit is silent — a top-`k` sample answered as if it were the
corpus reads exactly like a good answer.
"""

from __future__ import annotations

import sys
from pathlib import Path

STATION = Path(__file__).resolve().parents[1] / "apps" / "station"
if str(STATION) not in sys.path:
    sys.path.insert(0, str(STATION))


def _sweep() -> str:
    from monkeyllm_station.inference import ANSWER_SYSTEM

    return ANSWER_SYSTEM.lower()


def _walk() -> str:
    from monkeyllm_station.inference import FORAGE_SYSTEM

    return FORAGE_SYSTEM.lower()


def test_the_sweep_is_told_its_material_is_a_sample():
    """J.10.3 (v0.67). Five items out of twelve hundred arrive in the exact
    shape twelve hundred out of twelve hundred would take, and a model told
    they are "the forest material" answers about the five and is OBEYING the
    prompt — faithful, cited, traced, and wrong about its subject."""
    text = _sweep()
    assert "top-k" in text
    assert "corpus" in text
    # And the sentence must not be a softening of the strict-material rule
    # it sits beside: the material is still the only source.
    assert "strictly from the harvested forest material" in text


def test_the_walk_is_told_its_entry_was_nobody_s_retrieval():
    """J.10.5 rule 1 (v0.67). The loop labels the entry with the question,
    which reads as a retrieval somebody meant; in fact nobody translated it
    and nobody chose a rarer term, so re-authoring retrieval must read as a
    first move rather than as a repetition of work already done."""
    text = _walk()
    assert "verbatim" in text
    assert "locate" in text


def test_the_walk_is_told_where_a_question_about_the_corpus_goes():
    """J.10.5 rule 2 (v0.67). C.17's own motivating story, one surface
    later: a single document is one node's claim and is never the corpus,
    however confidently it describes it."""
    text = _walk()
    assert "corpus" in text
    assert "coverage" in text and "_index" in text
    assert "more than one branch" in text


def test_the_tool_menu_names_every_tool_the_whitelist_admits():
    """F.139's last clause: a tool the model is never offered is a tool the
    whitelist did not admit. The menu is the only place it is offered."""
    from monkeyllm_station.inference import FORAGE_SYSTEM, FORAGE_TOOLS

    for name in FORAGE_TOOLS:
        assert f'"tool": "{name}"' in FORAGE_SYSTEM, name
