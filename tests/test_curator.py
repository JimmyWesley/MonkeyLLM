"""G.4.2: the Curator — LLM summaries with A.4 validate-and-retry,
plus G.4.2.1 edge proposals (spec v0.12)."""

import json

from monkeyllm.curator import (
    MAX_PROPOSALS,
    NOTE_MAX_CHARS,
    PROPOSAL_CONFIDENCE,
    Curator,
    make_candidates,
)
from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.models import validate_summary

GOOD = json.dumps({
    "summary": "Discount policy 2026: up to 8% direct and 15% via partner "
               "with approval. Does not cover bundles.",
    "tags": ["sales", "discounts", "Policy!!", "sales"],
})
TOO_LONG = json.dumps({"summary": "word " * 120, "tags": []})
ANTI_PATTERN = json.dumps({"summary": "This document describes the discount "
                                      "policy in detail.", "tags": []})

DRAFT = {
    "id": "sales/policy", "type": "note", "title": "Policy",
    "body": "# Policy\n\nLong text about discounts and commercial rules.",
    "summary": "Derived fallback summary.", "tags": ["adopted"],
}


def scripted_chat(replies):
    it = iter(replies)

    def chat(messages):
        return next(it)

    return chat


class TestCurator:
    def test_good_first_reply(self):
        c = Curator(scripted_chat([GOOD]))
        out = c(dict(DRAFT))
        assert out["summary"].startswith("Discount policy 2026")
        validate_summary(out["summary"])
        # tags: cleaned (lowercase slug only), deduped, merged after defaults
        assert out["tags"] == ["adopted", "sales", "discounts"]
        assert c.stats == {"llm_summaries": 1, "fallbacks": 0, "retries": 0,
                           "links_proposed": 0, "proposal_fallbacks": 0,
                           "branch_rollups": 0, "branch_fallbacks": 0,
                           "transport_errors": 0, "rejected": 0}
        assert c.last_error is None and c.last_reject is None

    def test_retry_then_accept(self):
        c = Curator(scripted_chat([TOO_LONG, ANTI_PATTERN, GOOD]))
        out = c(dict(DRAFT))
        assert out["summary"].startswith("Discount policy 2026")
        assert c.stats["retries"] == 2 and c.stats["llm_summaries"] == 1

    def test_exhausted_retries_fall_back(self):
        c = Curator(scripted_chat([TOO_LONG, TOO_LONG, TOO_LONG]))
        out = c(dict(DRAFT))
        assert out["summary"] == "Derived fallback summary."  # untouched
        assert c.stats["fallbacks"] == 1 and c.stats["llm_summaries"] == 0
        # A model that answered and was rejected must not read as one that
        # never answered: same fallback, opposite fix.
        assert c.stats["rejected"] == 1 and c.stats["transport_errors"] == 0
        assert c.last_error is None
        assert "60 tokens" in c.last_reject
        assert c.last_reply and "word word" in c.last_reply

    def test_an_empty_reply_is_named_as_such(self):
        """A thinking model that spends its whole budget reasoning returns
        content that is empty, not content that lacks JSON — and only the
        first phrasing points at the fix (raise max_tokens)."""
        c = Curator(scripted_chat(["", "   ", ""]))
        c(dict(DRAFT))
        assert c.stats["rejected"] == 1
        assert c.last_reject == "the model returned an empty message"
        assert c.last_reply == ""

    def test_a_rejection_survives_a_later_success(self):
        """A batch whose last document happened to pass still owes the
        operator an example of the ones that did not."""
        c = Curator(scripted_chat([TOO_LONG, TOO_LONG, TOO_LONG, GOOD]))
        c(dict(DRAFT))
        c(dict(DRAFT))
        assert c.stats["llm_summaries"] == 1 and c.stats["rejected"] == 1
        assert c.last_reject, "the earlier rejection is the only clue left"

    def test_transport_error_falls_back(self):
        def chat(messages):
            raise ConnectionError("server down")

        c = Curator(chat)
        out = c(dict(DRAFT))
        assert out["summary"] == "Derived fallback summary."
        # Falling back silently is what makes a dead endpoint look like a
        # working ingest: the caller has to be able to tell the difference.
        assert c.stats["transport_errors"] == 1
        assert "server down" in c.last_error

    def test_the_endpoint_hint_survives_into_last_error(self):
        """A VineError from the inference client carries the provider's own
        reply in `hint` — the 401 body, the unknown-model line. That is the
        part that tells an operator what to fix."""
        def chat(messages):
            raise VineError(E_SCHEMA, "inference endpoint 401",
                            hint='{"error":"invalid api key"}')

        c = Curator(chat)
        c(dict(DRAFT))
        assert "401" in c.last_error and "invalid api key" in c.last_error

    def test_non_json_reply_retries(self):
        c = Curator(scripted_chat(["I think the summary should be...", GOOD]))
        out = c(dict(DRAFT))
        assert out["summary"].startswith("Discount policy 2026")
        assert c.stats["retries"] == 1

    def test_datasets_are_not_curated(self):
        c = Curator(scripted_chat([GOOD]))
        draft = {"id": "d", "type": "dataset", "summary": "Tabular data.",
                 "schema": {"t": {"columns": {"a": "TEXT"}}}}
        assert c(dict(draft))["summary"] == "Tabular data."
        assert c.stats["llm_summaries"] == 0

    def test_directives_reach_the_prompt(self):
        seen = {}

        def chat(messages):
            seen["system"] = messages[0]["content"]
            return GOOD

        Curator(chat, directives="Prioritize contract numbers.")(dict(DRAFT))
        assert "Prioritize contract numbers." in seen["system"]


def static_candidates(cands):
    def provider(query):
        return list(cands)

    return provider


class TestEdgeProposals:
    """G.4.2.1: links proposed from a closed catalog-offered list only."""

    CANDS = [
        {"id": "sales/prices", "title": "Price table",
         "summary": "Current prices for 2026 contracts."},
        {"id": "sales/partners", "title": "Partners",
         "summary": "Partner network and margins."},
        {"id": "hr/vacation", "title": "Vacation",
         "summary": "Vacation policy."},
        {"id": "ops/maintenance", "title": "Maintenance",
         "summary": "Maintenance plans."},
    ]

    def curator(self, replies, cands=None):
        return Curator(scripted_chat(replies),
                       candidates=static_candidates(
                           self.CANDS if cands is None else cands))

    def test_valid_pick_becomes_low_confidence_link(self):
        reply = json.dumps({"related": [
            {"id": "sales/prices", "note": "both govern discount limits"}]})
        c = self.curator([GOOD, reply])
        out = c(dict(DRAFT))
        assert out["links"] == [{
            "rel": "related-to", "target": "sales/prices",
            "confidence": PROPOSAL_CONFIDENCE,
            "note": "both govern discount limits"}]
        assert c.stats["links_proposed"] == 1

    def test_hallucinated_target_dropped(self):
        reply = json.dumps({"related": [{"id": "made/up"}, "also-fake", 42]})
        c = self.curator([GOOD, reply])
        out = c(dict(DRAFT))
        assert "links" not in out
        assert c.stats["links_proposed"] == 0
        assert c.stats["proposal_fallbacks"] == 0  # valid reply, zero picks

    def test_cap_and_within_reply_dedup(self):
        reply = json.dumps({"related": [
            {"id": "sales/prices"}, {"id": "sales/prices"},
            {"id": "sales/partners"}, {"id": "hr/vacation"},
            {"id": "ops/maintenance"}]})
        c = self.curator([GOOD, reply])
        out = c(dict(DRAFT))
        assert [l["target"] for l in out["links"]] == [
            "sales/prices", "sales/partners", "hr/vacation"]
        assert len(out["links"]) == MAX_PROPOSALS
        assert all(l["confidence"] == PROPOSAL_CONFIDENCE for l in out["links"])

    def test_existing_link_not_duplicated(self):
        draft = dict(DRAFT)
        draft["links"] = [{"rel": "related-to", "target": "sales/prices"}]
        c = self.curator([GOOD, json.dumps({"related": [{"id": "sales/prices"}]})])
        out = c(draft)
        assert out["links"] == [{"rel": "related-to", "target": "sales/prices"}]
        assert c.stats["links_proposed"] == 0

    def test_self_and_parent_never_offered(self):
        # the only candidates are the draft itself and its parent — there is
        # nothing to offer, so the proposal call never happens (a second
        # chat call would exhaust the script and count as a fallback)
        draft = dict(DRAFT, parent="sales/_index")
        cands = [{"id": draft["id"], "title": "t", "summary": "s"},
                 {"id": "sales/_index", "title": "t", "summary": "s"}]
        c = self.curator([GOOD], cands=cands)
        out = c(draft)
        assert "links" not in out
        assert c.stats["proposal_fallbacks"] == 0

    def test_empty_pick_is_a_good_answer(self):
        c = self.curator([GOOD, json.dumps({"related": []})])
        out = c(dict(DRAFT))
        assert "links" not in out
        assert c.stats["proposal_fallbacks"] == 0

    def test_bad_json_never_blocks(self):
        c = self.curator([GOOD, "I would connect them all!"])
        out = c(dict(DRAFT))
        assert "links" not in out
        assert c.stats["proposal_fallbacks"] == 1

    def test_proposals_run_even_after_summary_fallback(self):
        reply = json.dumps({"related": [{"id": "hr/vacation"}]})
        c = self.curator([TOO_LONG, TOO_LONG, TOO_LONG, reply])
        out = c(dict(DRAFT))
        assert out["summary"] == "Derived fallback summary."
        assert out["links"][0]["target"] == "hr/vacation"
        assert c.stats["fallbacks"] == 1 and c.stats["links_proposed"] == 1

    def test_note_is_clipped(self):
        reply = json.dumps({"related": [
            {"id": "sales/prices", "note": "x" * 500}]})
        c = self.curator([GOOD, reply])
        out = c(dict(DRAFT))
        assert len(out["links"][0]["note"]) == NOTE_MAX_CHARS


class TestGardenerIntegration:
    def test_curator_as_hook_in_adopt(self, tmp_path):
        from monkeyllm.forest import init_forest
        from monkeyllm.gardener import Gardener
        from monkeyllm.vine import Vine

        src = tmp_path / "dump"
        src.mkdir()
        (src / "policy.md").write_text(
            "# Policy\n\nText about commercial discounts in effect in 2026.",
            encoding="utf-8")
        root = tmp_path / "forest"
        init_forest(root, title="F")
        vine = Vine(root, writable=True)
        try:
            curator = Curator(scripted_chat([GOOD]))
            g = Gardener(vine, hooks=[curator])
            report = g.adopt(src)
            assert report["planted"] == ["policy"]
            node = vine.forest.read("policy")
            assert node.frontmatter["summary"].startswith("Discount policy 2026")
            assert "sales" in node.frontmatter["tags"]
            assert curator.stats["llm_summaries"] == 1
        finally:
            vine.close()

    def test_proposed_link_plants_and_ranger_manages_it(self, tmp_path):
        """F.16 end-to-end: catalog offers a real node, the proposal survives
        plant with link-level confidence 0.3, and Part H takes it over."""
        from monkeyllm.forest import init_forest
        from monkeyllm.gardener import Gardener
        from monkeyllm.ranger import Ranger
        from monkeyllm.vine import Vine

        src = tmp_path / "dump"
        src.mkdir()
        (src / "policy.md").write_text(
            "# Policy\n\nText about commercial discounts in effect in 2026.",
            encoding="utf-8")
        root = tmp_path / "forest"
        init_forest(root, title="F")
        vine = Vine(root, writable=True)
        try:
            vine.plant({
                "id": "prices", "type": "note", "parent": "_index",
                "title": "Price table",
                "summary": "Current prices for 2026 contracts.",
                "body": "# Price table\n\nValues per SKU.",
            })
            propose = json.dumps({"related": [
                {"id": "prices", "note": "discounts reference the price table"}]})
            curator = Curator(scripted_chat([GOOD, propose]),
                              candidates=make_candidates(vine))
            report = Gardener(vine, hooks=[curator]).adopt(src)
            assert report["planted"] == ["policy"]
            node = vine.forest.read("policy")
            link = node.frontmatter["links"][0]
            assert link["target"] == "prices" and link["rel"] == "related-to"
            assert link["confidence"] == PROPOSAL_CONFIDENCE
            assert link["note"] == "discounts reference the price table"
            # Part H: exactly the population the Ranger manages (H.2)
            managed = Ranger(vine)._managed_links(node.frontmatter)
            assert [l["target"] for l in managed] == ["prices"]
        finally:
            vine.close()


class TestBranchSummary:
    """G.4.4 (spec v0.13): branch rollup summaries."""

    def test_good_reply(self):
        c = Curator(scripted_chat([json.dumps(
            {"summary": "Alpha region: sensors and budget for 2026."})]))
        s = c.branch_summary("alpha", ["- [[a]] — Sensors.", "- [[b]] — Budget."])
        validate_summary(s)
        assert s.startswith("Alpha region")
        assert c.stats["branch_rollups"] == 1
        assert c.stats["branch_fallbacks"] == 0

    def test_invalid_after_retries_returns_none(self):
        bad = json.dumps({"summary": "word " * 120})
        c = Curator(scripted_chat([bad, bad, bad]))
        assert c.branch_summary("alpha", ["- [[a]] — Sensors."]) is None
        assert c.stats["branch_fallbacks"] == 1

    def test_transport_error_returns_none(self):
        def chat(messages):
            raise RuntimeError("down")
        c = Curator(chat)
        assert c.branch_summary("alpha", ["- [[a]] — Sensors."]) is None
        assert c.stats["branch_fallbacks"] == 1

    def test_empty_entries_short_circuit(self):
        def chat(messages):
            raise AssertionError("must not be called")
        c = Curator(chat)
        assert c.branch_summary("alpha", []) is None
