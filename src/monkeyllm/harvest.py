# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Harvest (spec C.6c) — zero-LLM, one-shot retrieval over the forest.

Composite tool for bring-your-own-model clients: a deterministic
locate+sniff sweep (RRF-fused) that returns the bananas themselves — full
body when it fits, matched sections when it does not, always with exact
snippets and the trail — so the caller's LLM decides the next steps.
"""

from __future__ import annotations

import re
import unicodedata

from monkeyllm.canopy import rrf_fuse
from monkeyllm.errors import VineError
from monkeyllm.tokens import shrink_list_to_budget

BUDGET_HARVEST = 4000
HARVEST_MAX_K = 5
MAX_TERMS = 8
MAX_SECTIONS_PER_NODE = 2
MAX_CONTENT_TOKENS_PER_NODE = 1200
MAX_REFINED_MATCHES = 5

# Question-words and connectives that carry no scent (PT + EN); everything
# else >= 4 chars is a candidate sniff term.
STOPWORDS = {
    "qual", "quais", "como", "para", "com", "das", "dos", "uma", "que",
    "quando", "onde", "quem", "sobre", "foram", "pela", "pelo",
    "what", "which", "where", "when", "who", "does", "with", "from",
    "this", "that", "have", "about", "were",
}


def derive_terms(query: str) -> list[str]:
    """Sniffable terms from a free-text query: rare-ish words, no stopwords."""
    words = re.findall(r"[\w-]{4,}", query, re.UNICODE)
    seen, terms = set(), []
    for w in words:
        folded = "".join(unicodedata.normalize("NFD", ch)[0] for ch in w).lower()
        if folded in STOPWORDS or folded in seen:
            continue
        seen.add(folded)
        terms.append(w)
    return terms[:MAX_TERMS]


def _refined_matches(vine, node_id: str, terms: list[str]) -> list[dict]:
    """Per-term sniff scoped to the node, rarest term first (spec C.6c.2).

    A common term ("experiment") matches every section and drowns the rare
    one ("1045") under the per-node match cap; scarcity ordering puts the
    most specific evidence on top.
    """
    per_term = []
    for t in terms:
        try:
            r = vine.sniff([t], scope=node_id, k=1)
        except VineError:
            continue
        if r["results"]:
            hit = r["results"][0]
            per_term.append((hit["match_count"], hit["matches"]))
    per_term.sort(key=lambda x: x[0])  # rarest first
    out, seen = [], set()
    for _count, matches in per_term:
        for m in matches:
            key = (m["section"], m["line"])
            if key not in seen:
                seen.add(key)
                out.append(m)
    return out[:MAX_REFINED_MATCHES]


def _content_for(vine, node_id: str, matches: list[dict]) -> list[dict]:
    """Body if it fits the per-node budget; otherwise the matched sections
    (spec C.6c.3)."""
    try:
        full = vine.pick(node_id)
    except VineError:
        return []
    if not full.get("truncated") and full.get("body_tokens", 0) <= MAX_CONTENT_TOKENS_PER_NODE:
        return [{"section": None, "body": full["body"], "body_tokens": full["body_tokens"]}]
    sections, out = [], []
    for m in matches:
        if m["section"] and m["section"] not in sections:
            sections.append(m["section"])
    for sec in sections[:MAX_SECTIONS_PER_NODE]:
        try:
            part = vine.pick(node_id, section=sec)
            out.append({"section": sec, "body": part["body"], "body_tokens": part["body_tokens"]})
        except VineError:
            continue
    if not out:  # big body, no section attribution: give the outline as a map
        out.append({"section": None, "outline": full.get("outline"),
                    "body_tokens": full.get("body_tokens"), "hint": full.get("hint")})
    return out


def harvest(vine, query: str, terms: list[str] | None = None, k: int = 3) -> dict:
    k = min(max(1, k), HARVEST_MAX_K)
    loc = vine.locate(query, k=k * 2)
    terms = terms or derive_terms(query)
    sn = vine.sniff(terms, k=k * 2) if terms else {"results": []}

    loc_ids = [r["id"] for r in loc["results"]]
    sniff_ids = [r["id"] for r in sn["results"]]
    fused = rrf_fuse(loc_ids, sniff_ids)
    ranked = sorted(fused, key=fused.get, reverse=True)[:k]

    loc_by = {r["id"]: r for r in loc["results"]}
    sniff_by = {r["id"]: r for r in sn["results"]}
    results = []
    for nid in ranked:
        meta = loc_by.get(nid) or sniff_by.get(nid)
        matches = (sniff_by.get(nid) or {}).get("matches", [])
        if nid in sniff_by and terms:
            matches = _refined_matches(vine, nid, terms) or matches
        results.append(
            {
                "id": nid,
                "title": meta.get("title"),
                "type": meta.get("type"),
                "trail": meta.get("trail"),
                "summary": meta.get("summary") or vine.look(nid, fields=["summary"]).get("summary"),
                "score": round(fused[nid], 4),
                "found_by": [name for name, ids in (("locate", loc_ids), ("sniff", sniff_ids)) if nid in ids],
                "matches": matches,
                "content": _content_for(vine, nid, matches),
            }
        )
    payload = {"query": query, "terms": terms, "results": results, "truncated": False}
    # budget: drop whole tail results, never slice a body silently (C.6c)
    return shrink_list_to_budget(payload, "results", BUDGET_HARVEST)
