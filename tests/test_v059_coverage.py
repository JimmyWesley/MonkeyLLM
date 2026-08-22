# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Spec v0.59 — the forest says what it holds (engine half).

F.103: `coverage` reports the roots, and the accounting closes.
F.104: the origin it publishes is the prefix `scan` takes.
F.105: ingest derives the name a document calls itself.
F.106: a rehearsal names every problem it can determine.
F.109: a warm `sniff` answers what the direct scan answers, for less.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from monkeyllm.errors import E_FRONTMATTER, E_NOT_FOUND, E_SCHEMA, VineError
from monkeyllm.gardener import Gardener, derive_aliases
from monkeyllm.vine import Vine


# -- F.103: what the forest holds --------------------------------------------


class TestCoverage:
    def test_the_roots_are_the_children_of_the_index(self, vine_ro):
        cov = vine_ro.coverage()
        listed = {r["id"] for r in cov["roots"]}
        children = {r["id"] for r in vine_ro.catalog.children("_index")}
        assert listed == children

    def test_the_accounting_closes(self, vine_ro):
        """Every node is under exactly one root, is the listing's own index,
        or is a `_meta/` file — and the report says which."""
        cov = vine_ro.coverage()
        assert sum(r["nodes"] for r in cov["roots"]) + 1 + cov["system"] \
            == cov["total"]

    def test_a_root_count_is_its_subtree(self, vine_ro):
        cov = vine_ro.coverage()
        for root in cov["roots"]:
            prefix = root["id"][: -len("_index")]
            counted = sum(
                1 for row in vine_ro.catalog.conn.execute("SELECT id FROM nodes")
                if (row[0].startswith(prefix) if root["kind"] == "branch"
                    else row[0] == root["id"]))
            assert counted == root["nodes"], root["id"]

    def test_the_totals_group_what_is_there(self, vine_ro):
        cov = vine_ro.coverage()
        assert cov["total"] == vine_ro.catalog.count_nodes()
        assert sum(cov["types"].values()) == cov["total"]
        assert cov["date_field"] == "created"
        assert cov["truncated"] is False

    def test_it_opens_no_file(self, vine_ro, monkeypatch):
        """C.17 rule 1: from the catalog alone — a `coverage` that read
        bodies would be the expensive call it exists to replace."""
        def refuse(*a, **kw):
            raise AssertionError("coverage opened a file")

        monkeypatch.setattr(Path, "read_text", refuse)
        assert vine_ro.coverage()["total"] > 0

    def test_scope_narrows_roots_and_totals(self, vine_ro):
        whole = vine_ro.coverage()
        part = vine_ro.coverage(scope="projects")
        assert part["scope"] == "projects"
        assert part["total"] < whole["total"]
        assert {r["id"] for r in part["roots"]} == {
            r["id"] for r in vine_ro.catalog.children("projects/_index")}

    def test_biggest_root_first(self, vine_ro):
        counts = [r["nodes"] for r in vine_ro.coverage()["roots"]]
        assert counts == sorted(counts, reverse=True)

    def test_updated_is_the_other_date_field(self, vine_ro):
        assert vine_ro.coverage(date_field="updated")["date_field"] == "updated"

    def test_an_unreadable_date_field_is_refused(self, vine_ro):
        with pytest.raises(VineError) as e:
            vine_ro.coverage(date_field="indexed")
        assert e.value.code == E_SCHEMA


# -- F.104: the origin it publishes is the prefix `scan` takes ---------------


def _ingest(tmp_path, files: dict[str, str], config: dict | None = None) -> Vine:
    import yaml

    from monkeyllm.forest import init_forest

    src = tmp_path / "dump"
    for rel, text in files.items():
        target = src / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    root = tmp_path / "forest"
    init_forest(root, title="Ingested")
    if config:
        meta = root / "_meta"
        meta.mkdir(parents=True, exist_ok=True)
        (meta / "gardener.yaml").write_text(yaml.safe_dump(config),
                                            encoding="utf-8")
    vine = Vine(root, writable=True)
    Gardener(vine).adopt(src)
    return vine


class TestOriginIsListable:
    @pytest.fixture()
    def ingested(self, tmp_path):
        vine = _ingest(tmp_path, {
            "alpha/1-one.md": "# 1 — One\n\nFirst.\n",
            "alpha/2-two.md": "# 2 — Two\n\nSecond.\n",
            "beta/3-three.md": "# 3 — Three\n\nThird.\n",
        })
        yield vine
        vine.close()

    def test_the_map_names_the_string_the_read_takes(self, ingested):
        cov = ingested.coverage()
        root = next(r for r in cov["roots"] if r["id"].startswith("alpha"))
        assert "origin" in root, "an ingested root must declare where it came from"
        listed = ingested.scan(root["id"], recursive=True,
                               filter={"origin_prefix": root["origin"]},
                               limit=50)
        assert listed["total"] == root["nodes"] - root.get("without_origin", 0)

    def test_a_full_uri_still_matches_one_node(self, ingested):
        node = ingested.look("alpha/1-one")
        one = ingested.scan("alpha/_index", recursive=True,
                            filter={"origin": node["origin"]})
        assert [n["id"] for n in one["nodes"]] == ["alpha/1-one"]

    def test_a_forest_with_no_origins_says_so(self, vine_ro):
        cov = vine_ro.coverage()
        for root in cov["roots"]:
            assert "origin" not in root
            assert root["without_origin"] == root["nodes"]


# -- F.105: the name a document calls itself ---------------------------------


class TestDerivedAliases:
    def test_the_folder_initials_need_no_map(self):
        assert derive_aliases(Path("tasks/back-end/291-budget.md"), {},
                              title="291 — Budget") == \
            ["BE-291", "back-end/291", "291"]

    def test_the_declared_prefix_suppresses_the_guess(self):
        assert derive_aliases(Path("tasks/back-end/291-budget.md"),
                              {"back-end": "BE"}, title="291 — Budget") == \
            ["BE-291", "back-end/291", "291"]
        assert derive_aliases(Path("tasks/back-end/291-budget.md"),
                              {"back-end": "TASK"}, title="291") == \
            ["TASK-291", "back-end/291", "291"]

    def test_a_single_word_folder_derives_no_letters(self):
        assert derive_aliases(Path("notes/7-thing.md"), {},
                              title="7 — Thing") == ["notes/7", "7"]

    def test_a_document_that_states_its_own_code(self):
        assert "ADR-0002" in derive_aliases(
            Path("adr/0002-publishing.md"), {},
            title="ADR-0002 Non-blocking publishing")

    def test_a_code_in_the_body_is_not_derived(self, tmp_path):
        vine = _ingest(tmp_path, {
            "docs/notes.md": "# Plain title\n\nSee BE-291 for the rule.\n"})
        assert vine.look("docs/notes").get("aliases") in (None, [], ["docs/notes"])
        vine.close()

    def test_nothing_is_invented_for_a_document_with_no_name(self):
        assert derive_aliases(Path("notes/free-form.md"), {},
                              title="Just prose") == []

    def test_locate_finds_the_derived_name(self, tmp_path):
        vine = _ingest(tmp_path, {
            "back-end/291-provider-budget.md":
                "# 291 — Provider budget enforcement\n\nGate 3 rules.\n"})
        hits = vine.locate("BE-291")
        assert hits["results"], hits
        assert hits["results"][0]["id"] == "back-end/291-provider-budget"
        vine.close()


# -- F.106: a rehearsal names every problem ----------------------------------


BAD = {"id": "nowhere/probe", "parent": "nowhere/_index", "type": "note",
       "title": "Probe", "summary": " ".join(["word"] * 90),
       "body": "# Probe\n"}


class TestRehearsalNamesEveryProblem:
    def test_both_problems_in_one_call(self, vine_rw):
        with pytest.raises(VineError) as exc:
            vine_rw.plant(dict(BAD), dry_run=True)
        err = exc.value
        assert err.code == E_FRONTMATTER
        codes = [e["code"] for e in err.data["errors"]]
        assert codes == [E_FRONTMATTER, E_NOT_FOUND]
        assert err.data["errors"][0]["message"] == err.message

    def test_the_envelope_is_what_it_always_was(self, vine_rw):
        """The first problem still decides code, message and hint: a client
        reading the code sees exactly what v0.58 gave it."""
        one_problem = dict(BAD, parent="notes/_index", id="notes/probe")
        with pytest.raises(VineError) as exc:
            vine_rw.plant(one_problem, dry_run=True)
        assert exc.value.code == E_FRONTMATTER
        assert "60 tokens" in exc.value.hint
        assert len(exc.value.data["errors"]) == 1

    def test_a_valid_rehearsal_is_unchanged(self, vine_rw):
        good = {"id": "notes/fine", "parent": "notes/_index", "type": "note",
                "title": "Fine", "summary": "A well-formed node.",
                "body": "# Fine\n"}
        assert vine_rw.plant(good, dry_run=True) == {
            "id": "notes/fine", "valid": True, "dry_run": True}
        assert not vine_rw.forest.exists("notes/fine")

    def test_a_batch_rehearses_every_node(self, vine_rw):
        batch = [
            {"id": "notes/ok-one", "parent": "notes/_index", "type": "note",
             "title": "One", "summary": "Fine.", "body": "# One\n"},
            dict(BAD, id="notes/bad-summary", parent="notes/_index"),
            {"id": "notes/ok-two", "parent": "notes/_index", "type": "note",
             "title": "Two", "summary": "Fine.", "body": "# Two\n"},
            {"id": "elsewhere/bad-parent", "parent": "elsewhere/_index",
             "type": "note", "title": "Three", "summary": "Fine.",
             "body": "# Three\n"},
        ]
        with pytest.raises(VineError) as exc:
            vine_rw.plant(batch, dry_run=True)
        errors = exc.value.data["errors"]
        assert [e["index"] for e in errors] == [1, 3]
        assert [e["id"] for e in errors] == ["notes/bad-summary",
                                             "elsewhere/bad-parent"]
        assert [e["code"] for e in errors] == [E_FRONTMATTER, E_NOT_FOUND]

    def test_a_bad_branch_does_not_echo_through_its_children(self, vine_rw):
        """A node that failed a check keeps its id and type in the batch's
        pending map, or every child would report a missing parent too."""
        batch = [
            {"id": "notes/team/_index", "parent": "notes/_index",
             "type": "branch", "title": "Team",
             "summary": " ".join(["word"] * 90)},
            {"id": "notes/team/one", "parent": "notes/team/_index",
             "type": "note", "title": "One", "summary": "Fine.",
             "body": "# One\n"},
        ]
        with pytest.raises(VineError) as exc:
            vine_rw.plant(batch, dry_run=True)
        assert len(exc.value.data["errors"]) == 1

    def test_the_real_plant_still_stops_at_the_first(self, vine_rw):
        with pytest.raises(VineError) as exc:
            vine_rw.plant(dict(BAD))
        assert "errors" not in exc.value.data
        assert not vine_rw.forest.exists("nowhere/probe")


# -- F.109: the warm scan answers what the direct scan answers ---------------


class TestWarmSniffCosts:
    def test_the_memo_changes_latency_and_nothing_else(self, vine_rw):
        terms = ["ledger", "the"]
        cold = vine_rw.sniff(terms, k=5)
        warm = vine_rw.sniff(terms, k=5)
        assert warm == cold

    def test_a_non_matching_body_is_never_carried_into_python(self, vine_rw,
                                                              monkeypatch):
        """C.6b.1 (v0.59): a remembered non-match is a count, not a row.
        ~95% of a forest holds none of the terms, and fetching, loading and
        parsing all of them was the cost of a warm sniff."""
        rare = ["zzqq-777"]
        vine_rw.sniff(rare)                       # populate the memo
        loads = {"n": 0}
        rows = {"n": 0}
        real_loads, real_rows = json.loads, vine_rw.catalog.rows_by_id

        def counted(*args, **kwargs):
            loads["n"] += 1
            return real_loads(*args, **kwargs)

        def counted_rows(ids, *args, **kwargs):
            rows["n"] += len(ids)
            return real_rows(ids, *args, **kwargs)

        monkeypatch.setattr(json, "loads", counted)
        monkeypatch.setattr(vine_rw.catalog, "rows_by_id", counted_rows)
        warm = vine_rw.sniff(rare)
        assert warm["results"] == []
        assert warm["scanned_nodes"] > 50, "every node was still covered"
        assert loads["n"] == 0, f"{loads['n']} records parsed for nothing"
        assert rows["n"] == 0, f"{rows['n']} catalog rows loaded for nothing"

    def test_heat_is_asked_for_once(self, vine_rw, monkeypatch):
        """Ranking is recomputed on every call (C.6b.1) — with ONE query,
        not one per matching node."""
        asked = {"n": 0}
        real = vine_rw.trails.heat_map

        def counted(*args, **kwargs):
            asked["n"] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(vine_rw.trails, "heat_map", counted)
        monkeypatch.setattr(vine_rw.trails, "get_heat", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("sniff asked for heat one node at a time")))
        vine_rw.sniff(["the"], k=5)
        assert asked["n"] == 1
