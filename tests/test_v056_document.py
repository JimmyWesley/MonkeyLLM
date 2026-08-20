# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.56 — the forest replaces the file (engine half).

F.79/F.80: pick pages a large body and reassembles it byte-identically;
`section` accepts a list under one budget. F.81: an unknown patch key is
refused, never absorbed. F.82: the passport says who and when. F.83: the
metaphor stays in the prose — no wire field speaks the internal spelling.
"""

from __future__ import annotations

import json

import pytest

from monkeyllm.errors import VineError
from monkeyllm.tokens import estimate_tokens
from monkeyllm.vine import PICK_MAX_BODY_TOKENS

GIANT = "projects/mixerllm/experiment-log"


def _resolved_body(vine, node_id: str) -> str:
    return vine.forest.read(node_id).body


# -- F.79: the over-budget read answers pages, not a dead end ---------------


class TestPickPages:
    def test_first_page_is_material_within_budget(self, vine_ro):
        p = vine_ro.pick(GIANT)
        assert p["truncated"] is True
        assert p["body"]
        assert estimate_tokens(p["body"]) <= PICK_MAX_BODY_TOKENS
        assert p["next"].startswith("b")
        assert p["total"] > p["returned"] > 0
        assert "after" in p["hint"]
        assert p["outline"]

    def test_unknown_cursor_is_named(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.pick(GIANT, after="page-3")
        assert e.value.code == "E_SCHEMA"
        assert "page-3" in e.value.message

    def test_after_beside_section_is_refused(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.pick(GIANT, section="Experiment 07", after="")
        assert e.value.code == "E_SCHEMA"

    def test_after_pages_one_document_never_a_batch(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.pick([GIANT, "sales/returns-q1"], after="")
        assert e.value.code == "E_SCHEMA"

    def test_a_body_within_budget_keeps_the_old_shape(self, vine_ro):
        p = vine_ro.pick("sales/returns-q1")
        assert set(p) == {"id", "title", "body", "body_tokens", "truncated"}
        assert p["truncated"] is False

    def test_cursor_past_the_end_states_the_truth(self, vine_ro):
        total = vine_ro.pick(GIANT)["total"]
        p = vine_ro.pick(GIANT, after=f"b{total + 5}")
        assert p["returned"] == 0 and p["body"] == ""
        assert p["truncated"] is False and "next" not in p

    # F.80: the property that lets an agent trust the reassembly.
    def test_pages_concatenated_are_the_body_byte_identical(self, vine_ro):
        body = _resolved_body(vine_ro, GIANT)
        pages, cursor, hops = [], "", 0
        while True:
            p = vine_ro.pick(GIANT, after=cursor)
            pages.append(p["body"])
            hops += 1
            assert hops < 50, "cursor failed to advance"
            if "next" not in p:
                break
            cursor = p["next"]
        assert "".join(pages) == body

    def test_a_real_report_completes_in_five_calls(self, vine_rw):
        # The consumer team's own number: 19,420 characters, complete and
        # ordered, in at most 5 calls — not 28.
        blocks = []
        while sum(len(b) for b in blocks) < 19_420:
            blocks.append(f"## Section {len(blocks):02d}\n\n" + "word " * 80)
        body = "\n".join(blocks)[:19_420]
        vine_rw.plant({
            "id": "notes/team-report", "type": "note", "parent": "notes/_index",
            "title": "A real report", "summary": "The size the team measured.",
            "body": body,
        })
        calls, cursor, got = 0, "", []
        while True:
            p = vine_rw.pick("notes/team-report", after=cursor)
            calls += 1
            got.append(p["body"])
            if "next" not in p:
                break
            cursor = p["next"]
        assert "".join(got) == _resolved_body(vine_rw, "notes/team-report")
        assert calls <= 5


# -- C.4.1 rule 4: sections come in lists -----------------------------------


class TestPickSections:
    def test_two_sections_one_call(self, vine_ro):
        p = vine_ro.pick(GIANT, section=["Experiment 07", "Experiment 29"])
        assert [s["section"] for s in p["sections"]] == [
            "Experiment 07", "Experiment 29"]
        assert all(s["body"] for s in p["sections"])
        assert p["missing"] == [] and p["dropped"] == []
        assert p["truncated"] is False

    def test_a_bare_string_keeps_the_old_shape(self, vine_ro):
        p = vine_ro.pick(GIANT, section="Experiment 07")
        assert set(p) == {"id", "title", "section", "body", "body_tokens",
                          "truncated"}

    def test_missing_names_are_named_not_fatal(self, vine_ro):
        p = vine_ro.pick(GIANT, section=["Experiment 07", "No Such Header"])
        assert [s["section"] for s in p["sections"]] == ["Experiment 07"]
        assert p["missing"] == ["No Such Header"]
        assert "hint" in p

    def test_every_request_lands_in_exactly_one_bucket(self, vine_ro):
        names = [f"Experiment {i:02d}" for i in range(1, 11)]
        p = vine_ro.pick(GIANT, section=names)
        seen = ([s["section"] for s in p["sections"]] + p["missing"]
                + p["dropped"])
        assert sorted(seen) == sorted(names)
        if p["dropped"]:
            assert p["truncated"] is True

    def test_the_list_is_bounded(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.pick(GIANT, section=[f"S{i}" for i in range(11)])
        assert e.value.code == "E_SCHEMA"
        with pytest.raises(VineError):
            vine_ro.pick(GIANT, section=[])


# -- F.81: an unknown patch key is refused, never absorbed ------------------


class TestGraftStrict:
    def test_unknown_key_alone_is_named(self, vine_rw):
        with pytest.raises(VineError) as e:
            vine_rw.graft("sales/returns-q1", {"regenerate_summary": True})
        assert e.value.code == "E_SCHEMA"
        assert "regenerate_summary" in e.value.message
        assert "append_section" in (e.value.hint or "")

    def test_unknown_key_beside_a_legal_op_writes_nothing(self, vine_rw):
        before = vine_rw.forest.read("sales/returns-q1").body
        with pytest.raises(VineError) as e:
            vine_rw.graft("sales/returns-q1", {
                "regenerate_summary": True,
                "append_section": {"header": "Smuggled", "body": "in."},
            })
        assert e.value.code == "E_SCHEMA"
        after = vine_rw.forest.read("sales/returns-q1").body
        assert after == before, "the legal half of a refused patch was applied"


# -- F.82: the passport says who and when -----------------------------------


class TestProvenance:
    def test_look_returns_created_and_source(self, vine_ro):
        d = vine_ro.look("sales/returns-q1")
        assert d["created"]
        assert "source" in d

    def test_aliases_ride_the_digest_when_present(self, vine_rw):
        vine_rw.graft("sales/returns-q1",
                      {"set_frontmatter": {"aliases": ["ZZ-999"]}})
        d = vine_rw.look("sales/returns-q1")
        assert d["aliases"] == ["ZZ-999"]
        bare = vine_rw.look("projects/mixerllm/experiment-log")
        assert "aliases" not in bare

    def test_scan_filters_by_source(self, vine_rw):
        vine_rw.plant({
            "id": "notes/agent-note", "type": "note", "parent": "notes/_index",
            "title": "Agent note", "summary": "Planted by an agent.",
            "body": "Text.",
        })
        r = vine_rw.scan("_index", recursive=True,
                         filter={"source": "agent"}, fields=["id", "source"])
        ids = [n["id"] for n in r["nodes"]]
        assert "notes/agent-note" in ids
        assert all(n["source"] == "agent" for n in r["nodes"])


# -- F.83: the metaphor stays in the prose ----------------------------------


class TestMetaphorOffTheWire:
    def test_locate_kind_speaks_the_wire(self, vine_ro):
        r = vine_ro.locate("sales", k=8)
        kinds = {x["kind"] for x in r["results"]}
        assert kinds <= {"note", "branch"} and kinds

    def test_scope_notes_and_its_deprecated_alias_agree(self, vine_ro):
        a = vine_ro.locate("stigmergy ants", scope="notes")
        b = vine_ro.locate("stigmergy ants", scope="bananas")
        assert a["results"] == b["results"]
        assert all(x["kind"] == "note" for x in a["results"])

    def test_scope_refusal_teaches_the_new_word(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.locate("sales", scope="typo")
        assert "notes" in e.value.message and "bananas" not in e.value.message

    def test_scan_kind_field_and_filter_agree(self, vine_ro):
        r = vine_ro.scan("_index", recursive=True, limit=50,
                         fields=["id", "kind"])
        assert {n["kind"] for n in r["nodes"]} <= {"note", "branch"}
        notes = vine_ro.scan("_index", recursive=True, limit=50,
                             filter={"kind": "note"}, fields=["id", "kind"])
        assert notes["nodes"] and all(n["kind"] == "note"
                                      for n in notes["nodes"])

    def test_no_listing_field_carries_the_internal_spelling(self, vine_ro):
        listing = vine_ro.scan("_index", recursive=True, limit=50,
                               fields=["id", "kind", "type", "coverage"])
        assert "banana" not in json.dumps(listing)
