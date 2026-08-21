# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.57 — the forest serves a hundred readers (engine half).

F.87: `look` never drops a field in silence — the budget clips in declared
order and names every field it touched.
F.88: the sweep knows what time it is — dated items, recency tie-break,
succession annotated.
F.89: `plant(dry_run=true)` rehearses every validation and writes nothing.
F.90: `origin` says where a document came from, and the engine never
dereferences it.
F.91: a served section echoes the header that actually matched.
F.94 (engine half): a commit trailer rides the original commit, and the
Ranger tends the repo.
"""

from __future__ import annotations

import subprocess

import pytest

from monkeyllm.errors import E_FRONTMATTER, E_SCHEMA, VineError
from monkeyllm.harvest import harvest
from monkeyllm.tokens import estimate_payload_tokens


def _rewrite_dates(vine, node_id: str, created: str, updated: str) -> None:
    """Backdate a passport the way an ingested corpus arrives: on disk,
    then indexed. Frontmatter dates are day-precision, so two same-day
    writes cannot exercise a tie-break without this."""
    from monkeyllm.parser import serialize_node

    node = vine.forest.read(node_id)
    fm = dict(node.frontmatter)
    fm["created"], fm["updated"] = created, updated
    vine.forest.write(node_id, serialize_node(fm, node.body))
    vine.catalog.upsert_node(vine.forest.read(node_id))


# -- F.87: look never drops a field in silence --------------------------------


class TestLookNamesItsCuts:
    def _plant_wide_outline(self, vine, n_sections=40):
        body = "# Wide\n\n" + "\n\n".join(
            f"## Section {i:02d} of the measured verification report, "
            f"with the finding and its severity\n\nParagraph {i}."
            for i in range(n_sections))
        vine.plant({"id": "notes/wide-report", "type": "note",
                    "parent": "notes/_index", "title": "Wide report",
                    "summary": "A report with a 30-item outline, to push "
                               "the digest over its budget.",
                    "body": body,
                    "links": [{"rel": "related-to",
                               "target": "concepts/rag"}]})
        vine.graft("concepts/stigmergy", {
            "add_links": [{"rel": "related-to",
                           "target": "notes/wide-report"}]})

    def test_the_edges_outlive_the_outline(self, vine_rw):
        # The team's shape: 28-item outline, degree 2 — and the old shrink
        # answered edges_out: [] beside stats.degree: 2.
        self._plant_wide_outline(vine_rw)
        d = vine_rw.look("notes/wide-report")
        assert d["stats"]["degree"] == 2
        assert d["edges_out"] and d["edges_in"], \
            "the outline is the big, re-derivable field; it goes first"
        assert d["truncated"] is True
        assert "outline" in d["truncated_fields"]
        assert "edges_out" not in d["truncated_fields"]
        assert estimate_payload_tokens(d) <= 500

    def test_an_unclipped_digest_names_nothing(self, vine_ro):
        d = vine_ro.look("concepts/rag")
        assert "truncated_fields" not in d
        assert "truncated" not in d

    def test_a_dataset_keeps_its_sample_rows_over_its_edges(self, vine_ro):
        # The digest of a dataset exists to feed `query`: edges clip
        # before the sample map does, and every clip is named.
        d = vine_ro.look("sales/report-q1-2026")
        assert "sample_rows" in d
        if "truncated_fields" in d:
            assert "sample_rows" not in d["truncated_fields"]

    def test_degree_is_the_arithmetic_truth_either_way(self, vine_rw):
        self._plant_wide_outline(vine_rw)
        full = vine_rw.look("notes/wide-report",
                            fields=["edges_out", "edges_in"])
        d = vine_rw.look("notes/wide-report")
        assert d["stats"]["degree"] == (len(full["edges_out"])
                                        + len(full["edges_in"]))


# -- F.88: the sweep knows what time it is ------------------------------------


class TestSweepTime:
    TERM = "zebraquokka"

    def _plant_rounds(self, vine):
        for rid, day in (("notes/round-one", "2026-03-01"),
                         ("notes/round-two", "2026-07-01")):
            vine.plant({"id": rid, "type": "note", "parent": "notes/_index",
                        "title": f"Round {rid[-3:]}",
                        "summary": f"A dated test round mentioning "
                                   f"{self.TERM}.",
                        "body": f"# Round\n\nThe {self.TERM} finding."})
            _rewrite_dates(vine, rid, day, day)
        vine.graft("notes/round-two", {
            "add_links": [{"rel": "succeeds", "target": "notes/round-one"}]})
        _rewrite_dates(vine, "notes/round-two", "2026-07-01", "2026-07-01")

    def test_items_state_their_time(self, vine_rw):
        self._plant_rounds(vine_rw)
        out = harvest(vine_rw, self.TERM)
        by_id = {r["id"]: r for r in out["results"]}
        assert by_id["notes/round-one"]["created"] == "2026-03-01"
        assert by_id["notes/round-two"]["updated"] == "2026-07-01"

    def test_a_succession_inside_the_set_is_annotated_never_suppressed(
            self, vine_rw):
        self._plant_rounds(vine_rw)
        out = harvest(vine_rw, self.TERM)
        by_id = {r["id"]: r for r in out["results"]}
        assert set(by_id) >= {"notes/round-one", "notes/round-two"}, \
            "history is evidence too — the older node stays"
        assert by_id["notes/round-two"]["supersedes"] == ["notes/round-one"]
        assert by_id["notes/round-one"]["superseded_by"] == [
            "notes/round-two"]

    def test_equal_relevance_prefers_the_newer(self, vine_rw):
        # One node carries the term only in curated metadata (locate's
        # world), the other only in its body (sniff's world): rank 0 in
        # one list each, so RRF fuses them to the same score and only the
        # tie-break decides.
        vine_rw.plant({"id": "notes/scent-side", "type": "note",
                       "parent": "notes/_index", "title": "Scent side",
                       "summary": "Curated mention of flumtoken here.",
                       "body": "# Scent side\n\nNothing literal."})
        vine_rw.plant({"id": "notes/body-side", "type": "note",
                       "parent": "notes/_index", "title": "Body side",
                       "summary": "A note about something else entirely.",
                       "body": "# Body side\n\nThe flumtoken appears."})
        _rewrite_dates(vine_rw, "notes/scent-side",
                       "2026-01-01", "2026-01-01")
        _rewrite_dates(vine_rw, "notes/body-side", "2026-06-01", "2026-06-01")
        ids = [r["id"] for r in harvest(vine_rw, "flumtoken")["results"]]
        assert ids.index("notes/body-side") < ids.index("notes/scent-side")
        # A tie-break, never a boost: swap the dates and the order follows.
        _rewrite_dates(vine_rw, "notes/scent-side",
                       "2026-08-01", "2026-08-01")
        ids = [r["id"] for r in harvest(vine_rw, "flumtoken")["results"]]
        assert ids.index("notes/scent-side") < ids.index("notes/body-side")


# -- F.89: a write rehearsed --------------------------------------------------


VALID_NODE = {"id": "notes/rehearsed", "type": "note",
              "parent": "notes/_index", "title": "Rehearsed",
              "summary": "A valid node used to rehearse the plant.",
              "body": "# Rehearsed\n\nContent."}


class TestDryRun:
    def test_a_valid_rehearsal_writes_nothing(self, vine_rw):
        head = vine_rw.git.head()
        r = vine_rw.plant(dict(VALID_NODE), dry_run=True)
        assert r == {"id": "notes/rehearsed", "valid": True, "dry_run": True}
        assert "created" not in r, "nothing was"
        assert not vine_rw.forest.exists("notes/rehearsed")
        assert vine_rw.catalog.get("notes/rehearsed") is None
        assert vine_rw.git.head() == head
        # Repeated forever, the forest stays byte-identical — and the real
        # plant still succeeds afterwards.
        vine_rw.plant(dict(VALID_NODE), dry_run=True)
        assert vine_rw.plant(dict(VALID_NODE))["created"] is True

    def test_the_failure_is_the_exact_envelope_of_the_real_call(self, vine_rw):
        fat = dict(VALID_NODE)
        fat["summary"] = ("word " * 80).strip()  # far over the 60-token A.4
        with pytest.raises(VineError) as dry:
            vine_rw.plant(fat, dry_run=True)
        with pytest.raises(VineError) as wet:
            vine_rw.plant(fat)
        assert dry.value.code == wet.value.code == E_FRONTMATTER
        assert dry.value.message == wet.value.message
        assert dry.value.to_dict() == wet.value.to_dict()

    def test_the_parent_chain_is_rehearsed_too(self, vine_rw):
        node = dict(VALID_NODE, id="reports/monkeyllm/one",
                    parent="_index")
        with pytest.raises(VineError) as e:
            vine_rw.plant(node, dry_run=True)
        assert "expected parent" in e.value.message

    def test_dry_run_composes_with_if_absent(self, vine_rw):
        vine_rw.plant(dict(VALID_NODE))
        head = vine_rw.git.head()
        r = vine_rw.plant(dict(VALID_NODE), if_absent=True, dry_run=True)
        assert r["created"] is False and r["dry_run"] is True
        assert vine_rw.git.head() == head

    def test_a_dataset_schema_is_validated_and_no_payload_is_born(
            self, vine_rw):
        node = {"id": "sales/rehearsed-ds", "type": "dataset",
                "parent": "sales/_index", "title": "Rehearsed dataset",
                "summary": "A dataset rehearsal: schema checked, no birth.",
                "schema": {"rows": {"columns": {"a": "TEXT"}}}}
        r = vine_rw.plant(dict(node), dry_run=True)
        assert r["valid"] is True
        assert not (vine_rw.forest.root / "sales"
                    / "rehearsed-ds.db").exists()
        bad = dict(node, schema={"rows": {"columns": {"a": "VARCHAR"}}})
        with pytest.raises(VineError) as e:
            vine_rw.plant(bad, dry_run=True)
        assert e.value.code == E_SCHEMA


# -- F.90: a document says where it came from ---------------------------------


class TestOrigin:
    ORIGIN = "https://github.com/example/repo/blob/main/report.md"

    def test_planted_origin_returns_in_look_and_filters_in_scan(self, vine_rw):
        vine_rw.plant(dict(VALID_NODE, origin=self.ORIGIN))
        assert vine_rw.look("notes/rehearsed")["origin"] == self.ORIGIN
        hits = vine_rw.scan("_index", recursive=True,
                            filter={"origin": self.ORIGIN},
                            fields=["id", "origin"])
        assert [n["id"] for n in hits["nodes"]] == ["notes/rehearsed"]
        assert hits["nodes"][0]["origin"] == self.ORIGIN

    def test_a_node_without_origin_says_nothing(self, vine_ro):
        assert "origin" not in vine_ro.look("concepts/rag")

    def test_origin_is_graft_mutable_and_clearable(self, vine_rw):
        vine_rw.plant(dict(VALID_NODE))
        vine_rw.graft("notes/rehearsed",
                      {"set_frontmatter": {"origin": self.ORIGIN}})
        assert vine_rw.look("notes/rehearsed")["origin"] == self.ORIGIN
        vine_rw.graft("notes/rehearsed", {"set_frontmatter": {"origin": None}})
        assert "origin" not in vine_rw.look("notes/rehearsed")
        node = vine_rw.forest.read("notes/rehearsed")
        assert "origin" not in node.frontmatter

    def test_prose_wearing_the_field_is_refused(self, vine_rw):
        for bad in ("two words", "line\nbreak", "x" * 2049, "", "  "):
            with pytest.raises(VineError) as e:
                vine_rw.plant(dict(VALID_NODE, origin=bad))
            assert e.value.code == E_SCHEMA
            with pytest.raises(VineError):
                vine_rw.graft("concepts/rag",
                              {"set_frontmatter": {"origin": bad}})


# -- F.91: a section answers by name ------------------------------------------


class TestSectionHeader:
    def test_the_matched_header_is_echoed(self, vine_rw):
        vine_rw.plant({
            "id": "notes/sectioned", "type": "note", "parent": "notes/_index",
            "title": "Sectioned", "summary": "Sections with numbered names.",
            "body": ("# Sectioned\n\n## 1. Executive summary\n\nShort.\n\n"
                     "## 7. Reading of the round\n\nLonger.")})
        out = vine_rw.pick("notes/sectioned",
                           section=["1. Executive", "7. Reading"])
        assert [s["section"] for s in out["sections"]] == [
            "1. Executive", "7. Reading"]
        # Prefix matching resolved a longer header than was asked; the
        # echo says which one.
        assert [s["header"] for s in out["sections"]] == [
            "1. Executive summary", "7. Reading of the round"]

    def test_the_single_section_shape_is_unchanged(self, vine_ro):
        # v0.56's contract TO THE BYTE: a bare string still returns the
        # old flat shape, no `sections`, no `header`.
        out = vine_ro.pick("concepts/rag", section="Definition")
        assert "sections" not in out and "header" not in out


# -- F.94 (engine half): the trailer rides the original commit ----------------


class TestCommitTrailers:
    def test_the_trailer_lands_in_the_commit_it_stamps(self, vine_rw):
        vine_rw.commit_trailers = ["station-principal: tester"]
        try:
            r = vine_rw.plant(dict(VALID_NODE))
        finally:
            vine_rw.commit_trailers = []
        message = subprocess.run(
            ["git", "-C", str(vine_rw.forest.root), "log", "-1",
             "--format=%B"],
            capture_output=True, text=True, check=True).stdout
        assert "station-principal: tester" in message
        # The sha the caller received is the only sha that ever existed.
        assert r["commit"] == vine_rw.git.head()

    def test_cleared_trailers_leave_the_next_commit_clean(self, vine_rw):
        vine_rw.commit_trailers = ["station-principal: tester"]
        vine_rw.plant(dict(VALID_NODE))
        vine_rw.commit_trailers = []
        vine_rw.graft("notes/rehearsed", {
            "set_frontmatter": {"tags": ["clean"]}})
        message = subprocess.run(
            ["git", "-C", str(vine_rw.forest.root), "log", "-1",
             "--format=%B"],
            capture_output=True, text=True, check=True).stdout
        assert "station-principal" not in message

    def test_the_repo_is_tended_best_effort(self, vine_rw):
        head = vine_rw.git.head()
        assert vine_rw.git.maintain() in ("ran", "unavailable")
        assert vine_rw.git.head() == head, "maintenance commits nothing"
