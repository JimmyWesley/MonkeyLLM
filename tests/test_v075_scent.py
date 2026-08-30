# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""v0.75 — the scent the Curator writes (G.4.2, G.4.3; F.162, F.163).

`locate` reads curated metadata and never a body, so the tags and aliases
a node is planted with are the only text by which it can be found. Two
failures lived there for two years, and both are silent by construction.

The tag filter was `^[a-z0-9][a-z0-9_-]*$`, against a Curator instructed to
work in the language of the content: every accented tag a Portuguese forest
produced was discarded with no error, no count and no line in the report,
and the operator watching saw a model that would not write tags (F.162).
The accent was never a matching concern — `nodes_fts` is tokenized
`unicode61 remove_diacritics 2`, so a tag stored as `produção` is matched
by a query for `producao`, which is what these tests measure rather than
assume.

The second is the identifiers (F.163). `be-291` and `iso-27001` always
passed the validator and always survived the tokenizer; only the prompt,
asking for "single words" next to a cap of five, stood between a document
and its own ticket number. And the one participant that reads the whole
document never proposed an alias, so a document introducing itself as
"BE-291 (Rate Limiter)" planted a node findable by neither.
"""

from __future__ import annotations

import json
import re

import pytest

from monkeyllm.curator import MAX_TAGS, Curator
from monkeyllm.errors import E_FRONTMATTER, VineError
from monkeyllm.forest import init_forest
from monkeyllm.gardener import Gardener
from monkeyllm.models import TAG_MAX_CHARS, validate_tag
from monkeyllm.parser import serialize_node
from monkeyllm.vine import Vine

# The document, in the language it was written in. `manutenção` is the
# controlled term of these tests: it appears in the BODY and in the model's
# tags, and in neither the title nor the summary — so a `locate` that finds
# it found it through the tag, which is the only claim F.162 makes.
PT_DOC = """# Plano de produção 2026

O plano da fábrica de Recife cobre a segurança operacional e o orçamento
anual, com uma janela de manutenção mensal.
"""

PT_REPLY = json.dumps({
    "summary": "Plano da fábrica de Recife para 2026: segurança operacional, "
               "orçamento anual e a janela mensal.",
    "tags": ["produção", "segurança", "manutenção"],
})

# BE-291 in the title, ISO 27001 and the component in the body: the shape
# the changelog describes, where every identifier is in the document and
# none of them is in the metadata `locate` reads.
TICKET_DOC = """# BE-291 rate limiter

The BE-291 ticket rewrites the rate limiter of the public API. The control
is audited against ISO 27001 and the p95 budget is 120 ms.
"""

TICKET_REPLY = json.dumps({
    "summary": "Rewrite of the public API rate limiter: audited control, "
               "120 ms p95 budget, delivered in 2026.",
    "tags": ["be-291", "iso-27001", "rate-limiter", "p95"],
    # RLX-9 occurs nowhere in the document: a plausible code, invented.
    "aliases": ["BE-291", "ISO 27001", "RLX-9"],
})


def always(reply):
    def chat(messages):
        return reply

    return chat


@pytest.fixture()
def garden(tmp_path):
    """A forest and a source directory, the Part G pair."""
    root = tmp_path / "forest"
    init_forest(root, title="Test Forest")
    src = tmp_path / "dump"
    src.mkdir()
    vine = Vine(root, writable=True)
    yield vine, src
    vine.close()


def ingest(garden, name, text, reply, **kw):
    """One document through the whole pipeline: convert, curate, plant."""
    vine, src = garden
    (src / name).write_text(text, encoding="utf-8")
    curator = Curator(always(reply), **kw)
    report = Gardener(vine, hooks=[curator]).adopt(src)
    assert report["errors"] == [], report["errors"]
    return curator, report, vine.forest.read(report["planted"][0])


def located(vine, query):
    return [r["id"] for r in vine.locate(query).get("results", [])]


# --- F.162: a tag is bounded, never silently dropped -----------------------

class TestAccentedTags:
    def test_the_accents_survive_to_the_passport(self, garden):
        vine, _ = garden
        curator, report, node = ingest(garden, "plano.md", PT_DOC, PT_REPLY)
        assert node.frontmatter["tags"] == ["produção", "segurança",
                                            "manutenção"]
        # `look` is what an agent reads, and it reads the spelling on disk.
        digest = vine.look(node.frontmatter["id"])
        assert "produção" in digest["tags"] and "manutenção" in digest["tags"]
        # Nothing was refused, so nothing is counted — that is the other
        # half of rule 1 and the half that makes the count readable.
        assert curator.stats["tags_dropped"] == 0
        assert report["tags_dropped"] == 0

    def test_locate_finds_the_node_by_the_unaccented_query(self, garden):
        """The tokenizer folds on the way in and on the way out; the
        passport does not. `manutenção` is in the body and in the tags and
        in nothing else `locate` reads, so this measures the tag."""
        vine, _ = garden
        _, _, node = ingest(garden, "plano.md", PT_DOC, PT_REPLY)
        node_id = node.frontmatter["id"]
        for field in ("title", "summary"):
            assert "manuten" not in node.frontmatter[field].lower(), \
                "the term must reach the index through the tag alone"
        assert located(vine, "manutencao") == [node_id]
        assert located(vine, "manutenção") == [node_id]

    def test_the_rule_this_replaces_would_have_dropped_them(self):
        """The negative control. Put the v0.74 filter back and the accented
        tags vanish — which is the failure F.162 exists to pin — while the
        identifiers it was blamed for were never affected by it."""
        legacy = re.compile(r"^[a-z0-9][a-z0-9_-]*$")  # the v0.74 rule
        for tag in ("produção", "segurança", "orçamento"):
            assert not legacy.match(tag), "the old rule kept it after all"
            assert validate_tag(tag) == tag
        for tag in ("be-291", "p95", "iso-27001"):
            assert legacy.match(tag) and validate_tag(tag) == tag


class TestTagsAreCounted:
    def refusals(self, tags):
        kept, dropped = Curator.clean_tags(tags)
        return kept, dropped

    def test_whitespace_over_length_and_over_cap_are_counted(self):
        long_tag = "a" * (TAG_MAX_CHARS + 1)
        kept, dropped = self.refusals(["rate limiter", long_tag, "-leading",
                                       "produção"])
        assert kept == ["produção"]
        assert dropped == 3, "three refusals, three counted"

    def test_the_cap_is_twelve_and_the_overflow_is_counted(self):
        assert MAX_TAGS == 12
        kept, dropped = self.refusals([f"tag-{i}" for i in range(15)])
        assert len(kept) == 12 and kept[-1] == "tag-11", "clipped from the tail"
        assert dropped == 3

    def test_a_repeated_tag_is_not_a_refusal(self):
        """Two spellings of one word are one tag (rule 2), and nothing was
        lost — counting a duplicate would make the report accuse a filter
        that never ran."""
        kept, dropped = self.refusals(["Produção", "produção", "PRODUÇÃO"])
        assert kept == ["produção"] and dropped == 0

    def test_the_count_reaches_the_ingest_report(self, garden):
        """`tags_dropped` travels exactly as `aliases_clipped` does: a
        filter nobody is told about is indistinguishable from a model that
        wrote nothing, and the two have opposite fixes."""
        reply = json.dumps({
            "summary": "Plano da fábrica de Recife para 2026: segurança "
                       "operacional e orçamento anual.",
            "tags": ["produção", "rate limiter", "não|válido"],
        })
        curator, report, node = ingest(garden, "plano.md", PT_DOC, reply)
        assert node.frontmatter["tags"] == ["produção"]
        assert curator.stats["tags_dropped"] == 2
        assert report["tags_dropped"] == 2

    def test_a_clean_run_reports_zero(self, garden):
        _, report, _ = ingest(garden, "plano.md", PT_DOC, PT_REPLY)
        assert report["tags_dropped"] == 0 and report["aliases_clipped"] == 0


# --- F.163: the scent carries what the corpus is searched by ---------------

class TestIdentifiersReachTheScent:
    def test_the_identifiers_become_tags_and_aliases(self, garden):
        _, _, node = ingest(garden, "ticket.md", TICKET_DOC, TICKET_REPLY)
        fm = node.frontmatter
        assert fm["tags"] == ["be-291", "iso-27001", "rate-limiter", "p95"]
        assert "BE-291" in fm["aliases"] and "ISO 27001" in fm["aliases"]

    def test_locate_returns_the_node_for_each_of_them(self, garden):
        vine, _ = garden
        _, _, node = ingest(garden, "ticket.md", TICKET_DOC, TICKET_REPLY)
        node_id = node.frontmatter["id"]
        summary = node.frontmatter["summary"].lower()
        for query in ("BE-291", "ISO 27001", "rate limiter", "p95"):
            assert node_id in located(vine, query), query
        # `be-291`, `iso` and `27001` are in no field `locate` reads except
        # the tags and the aliases this pass wrote — the body is where they
        # were, and the body is the one thing `locate` never opens.
        for term in ("be-291", "iso", "27001"):
            assert term not in summary

    def test_an_invented_alias_is_refused(self, garden):
        """The guard is structural (G.4.3 rule 2): an alias must OCCUR in
        the document under C.6b's fold. A model inventing a plausible
        acronym is refused by the check, not trusted by the prompt."""
        vine, _ = garden
        _, _, node = ingest(garden, "ticket.md", TICKET_DOC, TICKET_REPLY)
        assert "RLX-9" not in node.frontmatter["aliases"]
        assert located(vine, "RLX-9") == []

    def test_an_alias_equal_to_the_title_is_dropped_as_a_duplicate(self,
                                                                  garden):
        reply = json.dumps({
            "summary": "Rewrite of the public API rate limiter: audited "
                       "control, 120 ms p95 budget, delivered in 2026.",
            "tags": ["be-291"],
            "aliases": ["BE-291 rate limiter", "BE-291"],
        })
        _, _, node = ingest(garden, "ticket.md", TICKET_DOC, reply)
        assert node.frontmatter["aliases"] == ["BE-291"]

    def test_a_hand_written_alias_survives_the_pass(self):
        """G.4.3 rule 4: union, never displacement. An operator who taught
        a forest a name outranks a model that guessed one — so the pass
        adds behind what it found and never reorders or drops it."""
        curator = Curator(always(TICKET_REPLY))
        draft = curator({
            "id": "ticket", "type": "note", "title": "BE-291 rate limiter",
            "summary": "S.", "body": TICKET_DOC,
            "aliases": ["Limitador de taxa"]})
        assert draft["aliases"][0] == "Limitador de taxa", "displaced"
        assert draft["aliases"] == ["Limitador de taxa", "BE-291", "ISO 27001"]

    def test_a_derived_alias_is_never_displaced_or_duplicated(self, garden):
        """The ingest path: G.2.6 derives `BE-291` from the title before
        curation, and the model proposes it too. Twice is once."""
        vine, _ = garden
        _, _, node = ingest(garden, "ticket.md", TICKET_DOC, TICKET_REPLY)
        assert node.frontmatter["aliases"] == ["BE-291", "ISO 27001"]

    def test_a_model_that_never_answers_still_plants_the_node(self, garden):
        """G.4.3 rule 5: failure never blocks. No proposal survives a dead
        endpoint, the derived aliases are untouched, and the node plants."""
        vine, src = garden
        (src / "ticket.md").write_text(TICKET_DOC, encoding="utf-8")

        def dead(messages):
            raise ConnectionError("endpoint down")

        curator = Curator(dead)
        report = Gardener(vine, hooks=[curator]).adopt(src)
        node = vine.forest.read(report["planted"][0])
        assert node.frontmatter["aliases"] == ["BE-291"], "G.2.6's own"
        assert curator.stats["transport_errors"] == 1

    def test_the_prompt_names_the_classes_and_asks_for_no_single_words(self):
        """Rule 3 is a prompt rule, so the prompt is what the test reads."""
        seen = {}

        def chat(messages):
            seen["system"] = messages[0]["content"]
            return TICKET_REPLY

        Curator(chat)({"id": "x", "type": "note", "title": "BE-291",
                       "summary": "S.", "body": TICKET_DOC})
        system = seen["system"]
        for wanted in ("identifiers", "proper names", "aliases",
                       "iso-27001", "be-291", "rate-limit"):
            assert wanted in system, wanted
        assert "single words" not in system
        assert "no accents" not in system
        assert '"aliases"' in system, "the JSON example must show the field"


# --- G.4.2 rule 6: the rule is enforced where writes enter ------------------

class TestTheEngineEnforcesTheRule:
    def plant(self, vine, node_id, tags):
        return vine.plant({
            "id": node_id, "type": "note", "parent": "_index",
            "title": "A node", "summary": "A node planted by a test, with "
                                          "tags that answer to the rule.",
            "tags": tags, "body": "Body."})

    def test_plant_accepts_an_accented_tag(self, garden):
        vine, _ = garden
        self.plant(vine, "aceito", ["produção", "iso-27001", "p95"])
        assert vine.forest.read("aceito").frontmatter["tags"] == [
            "produção", "iso-27001", "p95"]

    def test_plant_refuses_an_invalid_tag_naming_it_and_the_rule(self, garden):
        vine, _ = garden
        with pytest.raises(VineError) as e:
            self.plant(vine, "recusado", ["ok", "rate limiter"])
        assert e.value.code == E_FRONTMATTER
        assert "rate limiter" in e.value.message, "the refusal names the tag"
        assert "whitespace" in e.value.message
        assert "G.4.2" in (e.value.hint or ""), "and names the rule"
        assert not vine.forest.exists("recusado")

    def test_reading_a_pre_v075_node_is_untouched(self, garden):
        """A rule that strands every old node behind its own editor is not
        a repair: the parser accepts what is already on disk."""
        vine, _ = garden
        node_id = self.legacy_node(vine)
        assert vine.look(node_id)["tags"] == ["rate limiter", "ok"]

    def test_graft_keeps_the_tags_it_found(self, garden):
        """An editor round-tripping an old node's tags still works."""
        vine, _ = garden
        node_id = self.legacy_node(vine)
        vine.graft(node_id, {"set_frontmatter":
                             {"tags": ["rate limiter", "ok", "novo"]}})
        assert vine.forest.read(node_id).frontmatter["tags"] == [
            "rate limiter", "ok", "novo"]

    def test_graft_refuses_a_tag_the_node_does_not_carry(self, garden):
        vine, _ = garden
        node_id = self.legacy_node(vine)
        with pytest.raises(VineError) as e:
            vine.graft(node_id, {"set_frontmatter":
                                 {"tags": ["rate limiter", "another one"]}})
        assert e.value.code == E_FRONTMATTER
        assert "another one" in e.value.message
        # Refused before anything was written.
        assert vine.forest.read(node_id).frontmatter["tags"] == [
            "rate limiter", "ok"]

    def legacy_node(self, vine):
        """A node as a pre-v0.75 Station left it: a tag the rule refuses,
        already on disk. Written past `plant` on purpose — the point is
        that this file exists in forests nobody is going to rewrite."""
        node_id = "antigo"
        self.plant(vine, node_id, ["ok"])
        node = vine.forest.read(node_id)
        fm = dict(node.frontmatter)
        fm["tags"] = ["rate limiter", "ok"]
        vine.forest.path_for(node_id).write_text(
            serialize_node(fm, node.body), encoding="utf-8", newline="\n")
        vine.catalog.upsert_node(vine.forest.read(node_id))
        return node_id
