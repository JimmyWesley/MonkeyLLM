# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.75 A.3.2 — a node MAY state its language (criterion F.164).

`lang` is a fact or it is absent. The tests here are the acceptance
criterion taken clause by clause:

* planted, it comes back from `look`;
* it selects on `scan`/`locate`/`sniff`/`harvest` and excludes on all four;
* `graft` changes it and `null` clears it;
* `portuguese`, `pt BR` and forty characters are `E_SCHEMA` naming the
  field — never coerced;
* no stage the ENGINE owns invents one (plant, graft and reindex are the
  surfaces this file can prove; the Gardener's converter and configuration
  sources are rule 3's other half and live elsewhere);
* `coverage` counts the languages per root and groups the nodes carrying
  none;
* and a forest that sets no language anywhere answers byte-identically to
  v0.74 — which is the clause the rest of them are worth nothing without.
"""

from __future__ import annotations

import copy

import pytest

from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.harvest import harvest
from monkeyllm.models import is_lang, validate_lang

# Two documents that differ only in the language they declare, sharing the
# vocabulary the searches below are run with: the ONLY thing separating
# them in any result is the filter.
PT = {"id": "notes/relatorio-cambial", "type": "note",
      "parent": "notes/_index", "title": "Relatorio cambial",
      "summary": "Relatorio do cambio de agosto com a taxa apurada.",
      "lang": "pt-BR",
      "body": "# Relatorio cambial\n\nA taxa CAMBIAL9021 foi apurada.\n"}
EN = {"id": "notes/exchange-report", "type": "note",
      "parent": "notes/_index", "title": "Exchange report",
      "summary": "Exchange report for August with the measured rate.",
      "lang": "en",
      "body": "# Exchange report\n\nThe CAMBIAL9021 rate was measured.\n"}
BARE = {"id": "notes/unlabelled", "type": "note",
        "parent": "notes/_index", "title": "Unlabelled note",
        "summary": "A note whose frontmatter never mentioned a language.",
        "body": "# Unlabelled\n\nThe CAMBIAL9021 rate is here too.\n"}


def _plant_all(vine) -> None:
    for spec in (PT, EN, BARE):
        vine.plant(copy.deepcopy(spec))


def _ids(payload: dict, key: str = "results") -> set[str]:
    return {r["id"] for r in payload[key]}


# -- the shape (A.3.2 rule 1) -------------------------------------------------


class TestTheShape:
    GOOD = ["pt", "en", "pt-BR", "zh-Hans", "zh-Hans-CN", "es-419", "sr-Latn"]
    BAD = ["portuguese", "pt BR", "p", "e" * 40, "pt-", "-pt", "pt_BR",
           "pt-BRA-XX", "", "   ", "en-US-x-private-use-that-is-long"]

    def test_a_tag_is_a_tag(self):
        for tag in self.GOOD:
            assert validate_lang(tag) == tag
            assert is_lang(tag)

    def test_a_name_is_not_a_tag(self):
        for bad in self.BAD:
            with pytest.raises(VineError) as e:
                validate_lang(bad)
            assert e.value.code == E_SCHEMA
            # Naming the field is the whole of the refusal's usefulness:
            # a caller reading "E_SCHEMA" alone cannot tell which of a
            # dozen frontmatter fields it was about.
            assert "lang" in e.value.message
            assert not is_lang(bad)

    def test_nothing_is_coerced(self):
        """The 40-character case is the one that could plausibly be
        truncated into something valid, and must not be."""
        with pytest.raises(VineError):
            validate_lang("e" * 40)
        assert not is_lang("e" * 40)
        # Nor a name shortened to its first two letters.
        assert not is_lang("portuguese")

    def test_a_type_that_is_not_a_string(self):
        for bad in (None, 42, ["pt"], {"lang": "pt"}, True):
            with pytest.raises(VineError) as e:
                validate_lang(bad)
            assert e.value.code == E_SCHEMA


# -- planted, read back, changed, cleared (A.3.2 rule 2) ----------------------


class TestPlantAndGraft:
    def test_a_planted_lang_comes_back_from_look(self, vine_rw):
        vine_rw.plant(copy.deepcopy(PT))
        assert vine_rw.look(PT["id"])["lang"] == "pt-BR"
        # And it is on the passport, not only in the index: the file is
        # the truth and `_derived/` is disposable.
        assert vine_rw.forest.read(PT["id"]).frontmatter["lang"] == "pt-BR"

    def test_graft_changes_it_and_null_clears_it(self, vine_rw):
        vine_rw.plant(copy.deepcopy(PT))
        vine_rw.graft(PT["id"], {"set_frontmatter": {"lang": "pt"}})
        assert vine_rw.look(PT["id"])["lang"] == "pt"
        assert vine_rw.catalog.get(PT["id"])["lang"] == "pt"
        vine_rw.graft(PT["id"], {"set_frontmatter": {"lang": None}})
        assert "lang" not in vine_rw.look(PT["id"])
        assert "lang" not in vine_rw.forest.read(PT["id"]).frontmatter
        assert not vine_rw.catalog.get(PT["id"])["lang"]

    def test_a_malformed_lang_is_refused_by_plant_and_graft(self, vine_rw):
        vine_rw.plant(copy.deepcopy(BARE))
        for bad in ("portuguese", "pt BR", "e" * 40):
            with pytest.raises(VineError) as e:
                vine_rw.plant(dict(copy.deepcopy(PT), lang=bad))
            assert e.value.code == E_SCHEMA and "lang" in e.value.message
            assert not vine_rw.forest.exists(PT["id"]), "nothing was written"
            with pytest.raises(VineError) as e:
                vine_rw.graft(BARE["id"], {"set_frontmatter": {"lang": bad}})
            assert e.value.code == E_SCHEMA and "lang" in e.value.message
            assert "lang" not in vine_rw.forest.read(BARE["id"]).frontmatter

    def test_no_engine_stage_invents_one(self, vine_rw):
        """A.3.2 rule 3, on the surfaces this file owns: a node whose
        frontmatter never mentioned a language has none after a plant, a
        graft that touches something else, and a full reindex."""
        vine_rw.plant(copy.deepcopy(BARE))
        vine_rw.graft(BARE["id"], {"set_frontmatter": {"title": "Renamed"}})
        vine_rw.reindex()
        assert "lang" not in vine_rw.forest.read(BARE["id"]).frontmatter
        assert not vine_rw.catalog.get(BARE["id"])["lang"]
        assert "lang" not in vine_rw.look(BARE["id"])

    def test_norwegian_survives_yaml(self, vine_rw):
        """`yaml.safe_load` reads a bare `no` as False, and `no` is
        Norwegian. A node written by hand that way must still be readable —
        the alternative is a field that works in every language except one,
        which is the shape of failure rule 6 is written about."""
        from monkeyllm.models import Frontmatter

        vine_rw.plant(dict(copy.deepcopy(BARE), lang="no"))
        node = vine_rw.forest.read(BARE["id"])
        # What the engine writes is quoted, so it round-trips as a string.
        assert node.frontmatter["lang"] == "no"
        assert vine_rw.look(BARE["id"])["lang"] == "no"
        # And a hand-written unquoted one is read back as the tag, not a
        # boolean the model would refuse.
        fm = dict(node.frontmatter, lang=False)
        assert Frontmatter.model_validate(fm).lang == "no"

    def test_the_column_survives_a_reindex(self, vine_rw):
        vine_rw.plant(copy.deepcopy(PT))
        vine_rw.reindex()
        assert vine_rw.catalog.get(PT["id"])["lang"] == "pt-BR"


# -- a filter, never a boost (A.3.2 rule 5) -----------------------------------


class TestTheFilter:
    def test_scan_selects_and_excludes(self, vine_rw):
        _plant_all(vine_rw)
        got = vine_rw.scan("notes/_index", filter={"lang": "pt-BR"},
                           fields=["id", "lang"])
        assert _ids(got, "nodes") == {PT["id"]}
        assert got["nodes"][0]["lang"] == "pt-BR"
        assert _ids(vine_rw.scan("notes/_index", filter={"lang": "en"}),
                    "nodes") == {EN["id"]}
        # A language nobody declared selects nothing, and says so by
        # returning nothing rather than by refusing.
        assert vine_rw.scan("notes/_index", filter={"lang": "fr"})["nodes"] == []

    def test_scan_refuses_a_value_it_cannot_read(self, vine_rw):
        _plant_all(vine_rw)
        with pytest.raises(VineError) as e:
            vine_rw.scan("notes/_index", filter={"lang": "portuguese"})
        assert e.value.code == E_SCHEMA and "lang" in e.value.message

    def test_locate_selects_and_excludes(self, vine_rw):
        _plant_all(vine_rw)
        both = _ids(vine_rw.locate("report cambial", k=10))
        assert {PT["id"], EN["id"]} <= both
        assert _ids(vine_rw.locate("report cambial", k=10, lang="pt-BR")) \
            == {PT["id"]}
        assert _ids(vine_rw.locate("report cambial", k=10, lang="en")) \
            == {EN["id"]}

    def test_locate_meets_k_inside_the_filter(self, vine_rw):
        """The reason the predicate is applied where candidates are chosen:
        the node a k of 1 does NOT have room for still comes back when the
        filter names its language. A filter applied to the ranked top-k
        would answer nothing here, and the caller would read a scarcity the
        implementation invented."""
        _plant_all(vine_rw)
        lang_of = {PT["id"]: "pt-BR", EN["id"]: "en"}
        ranked = [r["id"] for r in vine_rw.locate("report cambial",
                                                  k=10)["results"]]
        assert set(lang_of) <= set(ranked), "the premise of this test"
        top = vine_rw.locate("report cambial", k=1)["results"]
        assert len(top) == 1
        # Whichever of the two lost the single seat: naming its language
        # gives it back, at the same k.
        lost = next(nid for nid in lang_of if nid != top[0]["id"])
        got = vine_rw.locate("report cambial", k=1, lang=lang_of[lost])
        assert [r["id"] for r in got["results"]] == [lost]

    def test_locate_refuses_a_value_it_cannot_read(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.locate("anything", lang="portuguese")
        assert e.value.code == E_SCHEMA and "lang" in e.value.message

    def test_sniff_selects_and_excludes(self, vine_rw):
        _plant_all(vine_rw)
        assert {PT["id"], EN["id"], BARE["id"]} <= _ids(
            vine_rw.sniff(["CAMBIAL9021"], k=10))
        assert _ids(vine_rw.sniff(["CAMBIAL9021"], k=10, lang="pt-BR")) \
            == {PT["id"]}
        assert _ids(vine_rw.sniff(["CAMBIAL9021"], k=10, lang="en")) \
            == {EN["id"]}

    def test_sniff_refuses_a_value_it_cannot_read(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.sniff(["CAMBIAL9021"], lang="pt BR")
        assert e.value.code == E_SCHEMA and "lang" in e.value.message

    def test_harvest_forwards_it_to_both_halves(self, vine_rw):
        _plant_all(vine_rw)
        assert {PT["id"], EN["id"]} <= _ids(
            harvest(vine_rw, "CAMBIAL9021 exchange report", k=5))
        pt = harvest(vine_rw, "CAMBIAL9021 exchange report", k=5,
                     lang="pt-BR")
        assert _ids(pt) == {PT["id"]}
        # Both halves, not one: `found_by` says which retrievers produced
        # the item, and a filter that held for only one of them would let
        # the other's material through.
        assert _ids(harvest(vine_rw, "CAMBIAL9021 exchange report", k=5,
                            lang="en")) == {EN["id"]}

    def test_harvest_refuses_a_value_it_cannot_read(self, vine_rw):
        with pytest.raises(VineError) as e:
            harvest(vine_rw, "anything", lang="portuguese")
        assert e.value.code == E_SCHEMA and "lang" in e.value.message

    def test_the_language_does_not_change_a_score(self, vine_rw):
        """Ranking is untouched: the same node scores the same before and
        after somebody tells the forest what language it is in."""
        vine_rw.plant(copy.deepcopy(BARE))
        before = vine_rw.locate("unlabelled note", k=5)["results"]
        vine_rw.graft(BARE["id"], {"set_frontmatter": {"lang": "en"}})
        after = vine_rw.locate("unlabelled note", k=5)["results"]
        assert [(r["id"], r["score"]) for r in before] \
            == [(r["id"], r["score"]) for r in after]

    def test_lang_is_not_scent(self, vine_rw):
        """A.3.2 rule 5: the tag is a column and MUST NOT enter the FTS
        row, or `pt` becomes a word that ranks."""
        _plant_all(vine_rw)
        cols = {r[1] for r in vine_rw.catalog.conn.execute(
            "PRAGMA table_info(nodes_fts)")}
        assert "lang" not in cols
        assert _ids(vine_rw.locate("pt-BR", k=10)) & {PT["id"]} == set()


# -- coverage counts the languages (A.3.2 rule 6) -----------------------------


class TestCoverage:
    def test_languages_per_root_and_in_the_totals(self, vine_rw):
        _plant_all(vine_rw)
        cov = vine_rw.coverage()
        assert cov["languages"]["pt-BR"] == 1
        assert cov["languages"]["en"] == 1
        # The nodes carrying no language are their own group, and it is the
        # whole rest of the forest — not only the one note planted here.
        assert cov["without_lang"] == cov["total"] - 2
        notes = next(r for r in cov["roots"] if r["id"] == "notes/_index")
        assert notes["languages"] == {"pt-BR": 1, "en": 1}
        assert notes["without_lang"] == notes["nodes"] - 2

    def test_no_body_is_opened(self, vine_rw):
        """C.17 rule 1 still holds: the counting is metadata only. Proved
        by taking the whole forest's markdown away from `pick`'s reach —
        the count comes out of the catalog either way."""
        _plant_all(vine_rw)
        expected = vine_rw.coverage()["languages"]
        opened = []
        original = vine_rw.forest.read

        def watched(node_id, *a, **kw):
            opened.append(node_id)
            return original(node_id, *a, **kw)

        vine_rw.forest.read = watched
        try:
            assert vine_rw.coverage()["languages"] == expected
        finally:
            vine_rw.forest.read = original
        assert opened == []

    def test_a_root_with_no_labelled_node_reports_none(self, vine_rw):
        vine_rw.plant(copy.deepcopy(PT))
        cov = vine_rw.coverage()
        other = [r for r in cov["roots"] if r["id"] != "notes/_index"]
        assert other, "the fixture has more than one root"
        for root in other:
            assert "languages" not in root
            assert "without_lang" not in root


# -- byte-identical where nobody has said anything ----------------------------


class TestSilenceIsUnchanged:
    """The clause the rest of F.164 is worth nothing without: a forest that
    sets no language anywhere must answer exactly as it did before v0.75.
    """

    def test_reads_are_unchanged(self, vine_rw):
        vine_rw.plant(copy.deepcopy(BARE))
        loc = vine_rw.locate("unlabelled note", k=5)
        sn = vine_rw.sniff(["CAMBIAL9021"], k=5)
        sc = vine_rw.scan("notes/_index")
        hv = harvest(vine_rw, "CAMBIAL9021", k=3)
        for payload in (loc, sn, sc, hv):
            assert "lang" not in payload
        for item in loc["results"] + sn["results"] + sc["nodes"] + hv["results"]:
            assert "lang" not in item
        assert "lang" not in vine_rw.look(BARE["id"])

    def test_coverage_says_nothing_about_languages(self, vine_rw):
        cov = vine_rw.coverage()
        assert "languages" not in cov
        assert "without_lang" not in cov
        for root in cov["roots"]:
            assert "languages" not in root
            assert "without_lang" not in root

    def test_a_filterless_call_matches_a_none_filtered_one(self, vine_rw):
        """`lang=None` is not a filter — the C.12 rule that a null argument
        is a missing argument, applied to this field."""
        _plant_all(vine_rw)
        assert vine_rw.locate("report", k=5) == \
            vine_rw.locate("report", k=5, lang=None)
        assert vine_rw.scan("notes/_index") == \
            vine_rw.scan("notes/_index", filter={})


# -- the Curator is told, when the forest knows (A.3.2 rule 4) ----------------


class _Recorder:
    """A chat callable that records the messages and answers valid JSON."""

    def __init__(self):
        self.messages = []

    def __call__(self, messages):
        self.messages.append(messages)
        return ('{"summary": "Relatorio do cambio de agosto, com a taxa '
                'apurada e a fonte.", "tags": ["cambio"], "aliases": []}')


def _curate(draft: dict):
    from monkeyllm.curator import Curator

    chat = _Recorder()
    Curator(chat)(dict(draft))
    return chat.messages[0][0]["content"]


class TestTheCuratorIsTold:
    DRAFT = {"id": "notes/x", "title": "Relatorio", "summary": "",
             "body": "# Relatorio\n\nTexto suficiente para curar." * 4}

    def test_an_absent_lang_leaves_the_prompt_byte_identical(self):
        from monkeyllm.curator import Curator

        assert _curate(self.DRAFT) == Curator(lambda m: "").system

    def test_a_stated_lang_replaces_the_inference(self):
        from monkeyllm.curator import (
            INFER_LANGUAGE_SUMMARY,
            INFER_LANGUAGE_TAGS,
        )

        prompt = _curate(dict(self.DRAFT, lang="pt-BR"))
        assert "The document's language is pt-BR" in prompt
        assert "write the summary and tags in it" in prompt
        # Stated INSTEAD of asked for, which is rule 4's word: leaving the
        # inference in beside the statement is two instructions about one
        # decision.
        assert INFER_LANGUAGE_SUMMARY not in prompt
        assert INFER_LANGUAGE_TAGS not in prompt
        assert "written in pt-BR and" in prompt

    def test_a_malformed_draft_lang_is_ignored_not_pasted(self):
        """A draft is not a passport yet, so the tag has met no validator.
        The Curator's job is a summary; `plant` is where a bad tag is
        refused, and pasting one into a prompt would put a model's next
        summary in a language named by a bug."""
        from monkeyllm.curator import Curator

        prompt = _curate(dict(self.DRAFT, lang="portuguese"))
        assert prompt == Curator(lambda m: "").system
        assert "portuguese" not in prompt

    def test_the_branch_rollup_takes_it_too(self):
        from monkeyllm.curator import Curator

        chat = _Recorder()
        cur = Curator(chat)
        cur.branch_summary("Relatorios", ["- one entry", "- another entry"])
        without = chat.messages[-1][0]["content"]
        cur.branch_summary("Relatorios", ["- one entry", "- another entry"],
                           lang="pt-BR")
        with_lang = chat.messages[-1][0]["content"]
        assert "SAME LANGUAGE" in without
        assert "The material's language is pt-BR" in with_lang
        assert "SAME LANGUAGE" not in with_lang


# -- the wire declares it (C.12) ----------------------------------------------


def test_the_signature_table_declares_lang():
    from monkeyllm.signatures import SIGNATURES, validate_args

    for primitive in ("locate", "sniff", "harvest"):
        assert SIGNATURES[primitive]["lang"] == {"type": "string",
                                                 "required": False}
    assert validate_args("locate", {"query": "x", "lang": "pt-BR"}) == \
        {"query": "x", "lang": "pt-BR"}
    # A null is a missing argument, never a value (C.12 rule 3).
    assert validate_args("locate", {"query": "x", "lang": None}) == {"query": "x"}
    with pytest.raises(VineError) as e:
        validate_args("sniff", {"terms": "x", "lang": 42})
    assert e.value.code == E_SCHEMA and "lang" in e.value.message
