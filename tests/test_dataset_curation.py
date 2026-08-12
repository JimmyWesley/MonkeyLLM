# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.4.6 / G.10.1 / J.8 (v0.45, F.44) and C.2.1 (v0.46, F.45).

A dataset is curated from its map and never from its payload; the Gardener
names the phase it is in without pausing in it; a batch that needed no
model says so instead of accusing one; and what a person teaches about the
data comes back on every `look` of it.
"""

import csv
import io
import json
import sqlite3

import pytest

from monkeyllm.curator import Curator, _clip
from monkeyllm.forest import init_forest
from monkeyllm.gardener import STAGES, Gardener
from monkeyllm.vine import Vine

REPLY = json.dumps({
    "summary": "Sales leads pipeline to May 2026: company, city, value in BRL "
               "and stage for each lead.",
    "tags": ["leads", "sales"],
})


def big_csv(path, target=2_000_000):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["lead_id", "company", "city", "value", "stage"])
    n = 0
    while buf.tell() < target:
        n += 1
        w.writerow([n, f"Company {n}", "Recife", 1000 + n, "qualified",
                    "padding that makes the row weigh something " * 3])
    path.write_text(buf.getvalue(), encoding="utf-8")
    return n


@pytest.fixture()
def garden(tmp_path):
    root = tmp_path / "forest"
    init_forest(root, title="Test Forest")
    src = tmp_path / "dump"
    src.mkdir()
    return Vine(root, writable=True), src


# --- G.4.6: the scent comes from the map -----------------------------------

def test_the_model_sees_the_map_not_the_file(garden):
    vine, src = garden
    rows = big_csv(src / "leads-90d.csv")
    seen = []

    def chat(messages):
        seen.append(messages[-1]["content"])
        return REPLY

    Gardener(vine, hooks=[Curator(chat)]).adopt(src)

    assert len(seen) == 1, "one dataset, one model call"
    prompt = seen[0]
    # Bounded by the map, not by the source: a 2 MB CSV and a 2 GB database
    # cost the same. The margin is wide on purpose — this asserts an order
    # of magnitude, not a formatting detail.
    assert len(prompt) < 4000, f"the model was sent {len(prompt)} chars"
    assert "## Sample rows" in prompt
    assert "leads_90d(lead_id INTEGER" in prompt
    assert "Company 1 " in prompt.replace("|", " ")
    # …and only three rows of it, out of thousands.
    assert f"Company {rows}" not in prompt

    node = vine.forest.read("leads-90d")
    assert node.frontmatter["summary"].startswith("Sales leads pipeline")
    assert "leads" in node.frontmatter["tags"]


def test_an_adopted_database_is_curated_the_same_way(garden):
    vine, src = garden
    conn = sqlite3.connect(src / "audit.db")
    conn.execute("CREATE TABLE findings (page TEXT, detail TEXT)")
    conn.execute("INSERT INTO findings VALUES ('/login', 'submit returns 404')")
    conn.commit()
    conn.close()
    seen = []

    def chat(messages):
        seen.append(messages[-1]["content"])
        return json.dumps({"summary": "Audit findings for the login and admin "
                                      "pages, one row per defect.", "tags": ["audit"]})

    Gardener(vine, hooks=[Curator(chat)]).adopt(src)
    assert "submit returns 404" in seen[0]
    assert vine.forest.read("audit").frontmatter["summary"].startswith("Audit findings")


def test_a_refused_answer_leaves_the_factual_template(garden):
    """G.4.6 rule 2: ingest never blocks on a model."""
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)
    curator = Curator(lambda messages: "not json at all")

    Gardener(vine, hooks=[curator]).adopt(src)

    assert vine.forest.read("leads-90d").frontmatter["summary"].startswith(
        "Tabular data")
    assert curator.stats["fallbacks"] == 1
    assert curator.stats["llm_summaries"] == 0


def test_curation_never_rewrites_the_generated_map(garden):
    """G.4.6 rule 3: the body's two sections are the Gardener's."""
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)

    def chat(messages):
        return json.dumps({"summary": "A summary that is perfectly fine.",
                           "tags": []})

    Gardener(vine, hooks=[Curator(chat)]).adopt(src)
    body = vine.forest.read("leads-90d").body
    assert "## Query manual" in body and "## Sample rows" in body
    assert "A summary that is perfectly fine." not in body


def test_the_map_reaches_the_model_as_a_table(garden):
    """Flattening newlines would leave the model guessing where a row ended."""
    text = "## Sample rows\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert _clip(text) == text


# --- J.8: nothing to do is not a rejection ---------------------------------

def test_a_draft_with_nothing_to_read_is_skipped_not_failed():
    curator = Curator(lambda messages: pytest.fail("the model must not be asked"))
    out = curator({"id": "x", "title": "X", "type": "note"})
    assert "summary" not in out, "an untouched draft keeps whatever it had"
    assert curator.stats["skipped"] == 1
    # No fallback and no retry: that pair is what separates "needed no
    # model" from "asked one and was refused" (J.8, v0.45).
    assert curator.stats["fallbacks"] == 0
    assert curator.stats["retries"] == 0
    assert curator.stats["llm_summaries"] == 0
    assert curator.stats["transport_errors"] == 0


# --- G.10.1: the stage inside the step -------------------------------------

def test_stages_are_reported_in_order_within_one_step(garden):
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)
    seen = []

    steps = Gardener(vine, hooks=[], on_stage=lambda f, s: seen.append((f, s))
                     ).adopt_iter(src)
    # Everything below happens inside ONE step: `done` is still 0 while the
    # stages run, which is the whole point of reporting them.
    stages_before_first_step = []
    for step in steps:
        stages_before_first_step = list(seen)
        assert step["index"] == 1

    assert [s for _, s in stages_before_first_step] == list(STAGES)
    assert {f for f, _ in stages_before_first_step} == {"leads-90d.csv"}


def test_an_observer_that_raises_changes_nothing(garden):
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)

    def explode(file, stage):
        raise RuntimeError("the observer is broken")

    report = Gardener(vine, hooks=[], on_stage=explode).adopt(src)
    assert report["planted"] == ["leads-90d"]
    assert report["errors"] == []


def test_a_sync_reports_convert_and_plant_but_never_curate(garden):
    """A refresh keeps the scent somebody already approved (G.3)."""
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)
    g = Gardener(vine, hooks=[])
    g.adopt(src)

    seen = []
    g.on_stage = lambda f, s: seen.append(s)
    big_csv(src / "leads-90d.csv", target=80_000)
    assert g.sync()["updated"] == ["leads-90d"]
    assert seen == ["convert", "plant"]


# --- C.2.1: what a person teaches the agent (v0.46) ------------------------

def test_look_returns_the_notes_a_person_wrote(garden):
    """The path to a dataset is `look` then `query`; a note reachable only
    through `pick` is a note the agent will not read."""
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)
    Gardener(vine, hooks=[]).adopt(src)

    assert "notes" not in vine.look("leads-90d")
    vine.graft("leads-90d", {"append_section": {
        "header": "Notes",
        "body": "`value` is BRL, not USD. Stage 'qualified' means contacted.",
    }})
    digest = vine.look("leads-90d")
    assert digest["notes"].startswith("`value` is BRL")
    assert "Notes" not in digest["notes"], "the heading is the key, not content"


def test_notes_survive_a_sync_that_rewrites_the_map(garden):
    """G.2.3 rule 4 is what makes this section trustworthy to maintain."""
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)
    g = Gardener(vine, hooks=[])
    g.adopt(src)
    vine.graft("leads-90d", {"append_section": {
        "header": "Notes", "body": "Ask the finance team before trusting `value`."}})

    big_csv(src / "leads-90d.csv", target=90_000)
    assert g.sync()["updated"] == ["leads-90d"]

    digest = vine.look("leads-90d")
    assert digest["notes"] == "Ask the finance team before trusting `value`."
    # …and the map really was rewritten around it.
    assert digest["query_manual"]["tables"]


def test_curation_never_writes_the_notes(garden):
    """G.4.6: a model's guess about what a column means is exactly what
    this section exists to correct."""
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)
    Gardener(vine, hooks=[Curator(lambda m: REPLY)]).adopt(src)
    assert "notes" not in vine.look("leads-90d")


def test_long_notes_are_clipped_and_say_so(garden):
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)
    Gardener(vine, hooks=[]).adopt(src)
    vine.graft("leads-90d", {"append_section": {
        "header": "Notes", "body": "a sentence that keeps going. " * 400}})

    digest = vine.look("leads-90d")
    assert digest["truncated"] is True
    assert digest["notes"].endswith("…")
    assert len(digest["notes"]) < 1200


def test_pick_hands_back_the_whole_section_to_edit(garden):
    """The console edits from `pick`, never from the clipped digest —
    saving a clipped copy would be the console deleting the tail."""
    vine, src = garden
    big_csv(src / "leads-90d.csv", target=50_000)
    Gardener(vine, hooks=[]).adopt(src)
    long_note = "a sentence that keeps going. " * 400
    vine.graft("leads-90d", {"append_section": {"header": "Notes", "body": long_note}})

    picked = vine.pick("leads-90d", section="Notes")
    assert picked["truncated"] is False
    assert picked["body"].startswith("## Notes")
    assert long_note.strip() in picked["body"]
