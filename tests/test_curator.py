"""G.4.2: the Curator — LLM summaries with A.4 validate-and-retry."""

import json

from monkeyllm.curator import Curator
from monkeyllm.models import validate_summary

GOOD = json.dumps({
    "summary": "Política de descontos 2026: até 8% direto e 15% via parceiro "
               "com aprovação. Não cobre bundles.",
    "tags": ["vendas", "descontos", "Política!!", "vendas"],
})
TOO_LONG = json.dumps({"summary": "palavra " * 120, "tags": []})
ANTI_PATTERN = json.dumps({"summary": "This document describes the discount "
                                      "policy in detail.", "tags": []})

DRAFT = {
    "id": "vendas/politica", "type": "note", "title": "Política",
    "body": "# Política\n\nTexto longo sobre descontos e regras comerciais.",
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
        assert out["summary"].startswith("Política de descontos 2026")
        validate_summary(out["summary"])
        # tags: cleaned (lowercase slug only), deduped, merged after defaults
        assert out["tags"] == ["adopted", "vendas", "descontos"]
        assert c.stats == {"llm_summaries": 1, "fallbacks": 0, "retries": 0}

    def test_retry_then_accept(self):
        c = Curator(scripted_chat([TOO_LONG, ANTI_PATTERN, GOOD]))
        out = c(dict(DRAFT))
        assert out["summary"].startswith("Política de descontos 2026")
        assert c.stats["retries"] == 2 and c.stats["llm_summaries"] == 1

    def test_exhausted_retries_fall_back(self):
        c = Curator(scripted_chat([TOO_LONG, TOO_LONG, TOO_LONG]))
        out = c(dict(DRAFT))
        assert out["summary"] == "Derived fallback summary."  # untouched
        assert c.stats["fallbacks"] == 1 and c.stats["llm_summaries"] == 0

    def test_transport_error_falls_back(self):
        def chat(messages):
            raise ConnectionError("server down")

        out = Curator(chat)(dict(DRAFT))
        assert out["summary"] == "Derived fallback summary."

    def test_non_json_reply_retries(self):
        c = Curator(scripted_chat(["I think the summary should be...", GOOD]))
        out = c(dict(DRAFT))
        assert out["summary"].startswith("Política de descontos 2026")
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


class TestGardenerIntegration:
    def test_curator_as_hook_in_adopt(self, tmp_path):
        from monkeyllm.forest import init_forest
        from monkeyllm.gardener import Gardener
        from monkeyllm.vine import Vine

        src = tmp_path / "dump"
        src.mkdir()
        (src / "politica.md").write_text(
            "# Política\n\nTexto sobre descontos comerciais vigentes em 2026.",
            encoding="utf-8")
        root = tmp_path / "floresta"
        init_forest(root, title="F")
        vine = Vine(root, writable=True)
        try:
            curator = Curator(scripted_chat([GOOD]))
            g = Gardener(vine, hooks=[curator])
            report = g.adopt(src)
            assert report["planted"] == ["politica"]
            node = vine.forest.read("politica")
            assert node.frontmatter["summary"].startswith("Política de descontos")
            assert "vendas" in node.frontmatter["tags"]
            assert curator.stats["llm_summaries"] == 1
        finally:
            vine.close()
