# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Harvest (spec C.6c) — zero-LLM, one-shot retrieval over the forest.

Composite tool for bring-your-own-model clients: a deterministic
locate+sniff sweep (RRF-fused) that returns the bananas themselves — full
body when it fits, matched sections when it does not, always with exact
snippets and the trail — so the caller's LLM decides the next steps.
"""

from __future__ import annotations

import os
import re
import unicodedata

from monkeyllm.canopy import rrf_fuse
from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.tokens import shrink_list_to_budget

BUDGET_HARVEST = 4000
DEFAULT_HARVEST_MAX_K = 5
MAX_TERMS = 8
MAX_SECTIONS_PER_NODE = 2
MAX_CONTENT_TOKENS_PER_NODE = 1200
MAX_REFINED_MATCHES = 5

# Question-words, connectives and demonstratives that carry no scent
# (PT + EN + ES); everything else >= 4 chars is a candidate sniff term.
# Compared against the folded, lower-cased token, so accented spellings
# ("está") are covered by their unaccented row.
#
# Not a contract: C.6b does not enumerate this set and must not — a list
# fixed in the specification is a specification amended in every language
# somebody asks a question in.
STOPWORDS = {
    "qual", "quais", "como", "para", "com", "das", "dos", "uma", "que",
    "quando", "onde", "quem", "sobre", "foram", "pela", "pelo",
    # PT demonstratives: the English ones were here from the start and
    # their counterparts were not, so "esta" reached `sniff` as a literal
    # search that matches inside "restart" and "timestamp".
    "esta", "este", "estas", "estes", "essa", "esse", "essas", "esses",
    "isto", "isso", "aquele", "aquela", "aqueles", "aquelas", "aquilo",
    # ES demonstratives, on the same rule.
    "esa", "ese", "eso", "esas", "esos", "esto", "estos",
    "aquel", "aquella", "aquello", "aquellos", "aquellas",
    "what", "which", "where", "when", "who", "does", "with", "from",
    "this", "that", "have", "about", "were",
}


def _code_shaped(word: str) -> bool:
    """A token a technical corpus is searched BY, whatever its length
    (C.6c, v0.52): it carries a digit, is written in capitals, or holds one
    of `-`, `_`, `.`, `/`.

    The four-character floor below is right for grammar and wrong for
    exactly these: `RAG`, `MCP`, `JWT`, `SSO`, `421`, `p95` are the most
    discriminative tokens in the question and the shortest ones in it.
    """
    if any(ch.isdigit() for ch in word):
        return True
    letters = [ch for ch in word if ch.isalpha()]
    if letters and all(ch.isupper() for ch in letters):
        return True
    return any(ch in "-_./" for ch in word)


def derive_terms(query: str) -> list[str]:
    """Sniffable terms from a free-text query: rare-ish words, no stopwords.

    Code-shaped tokens survive the length floor AND are ordered first, so
    the MAX_TERMS cap drops grammar before it drops signal. The floor stays
    for ordinary words: a short common word is grammar, and every junk term
    lowers the `strength` of a real hit (C.6b).
    """
    words = re.findall(r"[\w\-./]{2,}", query, re.UNICODE)
    seen, ordinary, coded = set(), [], []
    for w in words:
        w = w.strip("./-")
        if len(w) < 2:
            continue
        folded = "".join(unicodedata.normalize("NFD", ch)[0] for ch in w).lower()
        if folded in seen:
            continue
        # Code-shape is asked FIRST, and the order is the whole point: the
        # stopword set is a list of grammar in three languages and a fold
        # erases the one thing that told `ESA` from `esa`, `DOS` from `dos`,
        # `WHO` from `who`. Testing membership before shape drops exactly
        # the tokens the floor was written to exempt — the ones a technical
        # corpus is searched BY. Nothing else moves: a token that is not
        # code-shaped meets the same set it always did.
        if _code_shaped(w):
            seen.add(folded)
            coded.append(w)
        elif folded in STOPWORDS:
            continue
        elif len(w) >= 4:
            seen.add(folded)
            ordinary.append(w)
    return (coded + ordinary)[:MAX_TERMS]


def _refined_matches(vine, node_id: str, terms: list[str]) -> list[dict]:
    """Per-term sniff scoped to the node, rarest term first (spec C.6c.2).

    A common term ("experiment") matches every section and drowns the rare
    one ("1045") under the per-node match cap; scarcity ordering puts the
    most specific evidence on top.

    Never for an index node (v0.35): sniff resolves an index id to its
    whole subtree, so "refining" one silently grepped the forest under it —
    children's snippets attributed to the index, picked by heat rank and
    therefore different on every read. The caller falls back to the global
    sniff's matches, which are found inside the node's own body.
    """
    if node_id == "_index" or node_id.endswith("/_index"):
        return []
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


def harvest_max_k() -> int:
    """The C.6c cap: the deployment's number, not the caller's.

    Read per call so a Station and its tests see the environment they run
    under; garbage is refused, never rounded — a cap silently corrected is
    a bundle sized by a typo.
    """
    raw = os.environ.get("MONKEYLLM_HARVEST_MAX_K")
    if raw is None or not raw.strip():
        return DEFAULT_HARVEST_MAX_K
    try:
        cap = int(raw.strip())
    except ValueError:
        cap = 0
    if cap < 1:
        raise VineError(
            E_SCHEMA,
            f"MONKEYLLM_HARVEST_MAX_K must be an integer >= 1, got {raw!r}",
            hint="Unset it to keep the default cap of "
                 f"{DEFAULT_HARVEST_MAX_K}.")
    return cap


def clamp_k(k: int) -> int:
    """The effective `k` of a sweep — what J.10.7 keys an answer under."""
    return min(max(1, int(k)), harvest_max_k())


def harvest(vine, query: str, terms: list[str] | None = None, k: int = 3,
            since: str | None = None, until: str | None = None,
            date_field: str | None = None, lang: str | None = None,
            include_superseded: bool = False, *, visible=None) -> dict:
    """`visible` (C.6c.4 rule 6) is the host policy's predicate, passed by
    the scoped wrapper exactly as `scan` receives it: a successor the
    caller cannot see cannot suppress what they can."""
    k = clamp_k(k)
    # C.13.1: the window rides both legs or neither. A sweep whose lexical
    # half was bounded and whose literal half was not would return material
    # from outside the window under a response that says it was bounded.
    win = {"since": since, "until": until, "date_field": date_field}
    # A.3.2 rule 5 travels the same way and for the same reason: a sweep
    # whose lexical half was filtered by language and whose literal half
    # was not would return material in another one under a response that
    # says it was filtered.
    #
    # Added only when it was ASKED for, so a call that names no language
    # reaches both legs with the argument list it reached them with before
    # v0.75 — which is A.3.2's closing clause, and the reason a surface
    # that has not been taught the parameter keeps working untouched.
    if lang is not None:
        win["lang"] = lang
    loc = vine.locate(query, k=k * 2, **win)
    terms = terms or derive_terms(query)
    sn = vine.sniff(terms, k=k * 2, **win) if terms else {"results": []}

    loc_ids = [r["id"] for r in loc["results"]]
    sniff_ids = [r["id"] for r in sn["results"]]
    fused = rrf_fuse(loc_ids, sniff_ids)
    # C.6c.3 (v0.57): equal relevance prefers the newer. A tie-break, never
    # a boost — recency decides only where the fusion could not, then
    # `created`, then id for determinism.
    dates = vine.catalog.dates_of(list(fused))
    order = sorted(sorted(fused), reverse=True,
                   key=lambda nid: (fused[nid], dates.get(nid, ("", ""))[1],
                                    dates.get(nid, ("", ""))[0]))
    # C.6c.4 (v0.58): a replacement suppresses what it replaced — excluded
    # from the selection, the seat refilled, and NOTHING hidden silently.
    # A successor the caller cannot see cannot suppress what they can.
    sup_map = vine.catalog.superseded_by_map(order)
    if visible is not None:
        sup_map = {t: kept for t, srcs in sup_map.items()
                   if (kept := [s for s in srcs if visible(s)])}
    excluded: list[dict] = []
    if include_superseded or not sup_map:
        ranked = order[:k]
    else:
        ranked = []
        for nid in order:
            if len(ranked) == k:
                break
            if nid in sup_map:
                excluded.append({"id": nid, "by": sorted(sup_map[nid])})
                continue
            ranked.append(nid)
    # C.6c.3: a succession inside the result set is annotated, never
    # suppressed — the older node stays (history is evidence too), but the
    # model is no longer the only one who could have discovered the order.
    # The `supersedes` rel (C.6c.4) annotates in the same voice, wherever
    # its target survived into the set (the history view, or a scoped
    # suppression that could not apply).
    succ_of: dict[str, list[str]] = {}
    pred_of: dict[str, list[str]] = {}
    for rel in ("succeeds", "supersedes"):
        for edge in vine.catalog.edges_among(ranked, rel):
            succ_of.setdefault(edge["src"], []).append(edge["dst"])
            pred_of.setdefault(edge["dst"], []).append(edge["src"])
    for nid in ranked:
        for successor in sup_map.get(nid, []):
            pred_of.setdefault(nid, []).append(successor)

    loc_by = {r["id"]: r for r in loc["results"]}
    sniff_by = {r["id"]: r for r in sn["results"]}
    results = []
    for nid in ranked:
        meta = loc_by.get(nid) or sniff_by.get(nid)
        matches = (sniff_by.get(nid) or {}).get("matches", [])
        if nid in sniff_by and terms:
            matches = _refined_matches(vine, nid, terms) or matches
        item = {
            "id": nid,
            "title": meta.get("title"),
            "type": meta.get("type"),
            "trail": meta.get("trail"),
            "summary": meta.get("summary") or vine.look(nid, fields=["summary"]).get("summary"),
            "score": round(fused[nid], 4),
            "found_by": [name for name, ids in (("locate", loc_ids), ("sniff", sniff_ids)) if nid in ids],
            # C.6c rule 4 (v0.54): the whole body's size, so a caller
            # deciding to pick past the excerpt knows the price. Both legs
            # carry it since v0.54, so it is already in hand.
            "body_tokens": meta.get("body_tokens"),
            "matches": matches,
            "content": _content_for(vine, nid, matches),
        }
        # C.6c.3 (v0.57): every item states its time — read off the catalog
        # row already in hand, never a file open. Undated stays absent.
        created, updated = dates.get(nid, ("", ""))
        if created:
            item["created"] = created
        if updated:
            item["updated"] = updated
        if nid in succ_of:
            item["supersedes"] = sorted(set(succ_of[nid]))
        if nid in pred_of:
            item["superseded_by"] = sorted(set(pred_of[nid]))
        # C.2.1 (v0.46): a dataset's notes travel with it — and (v0.78) a
        # media node's, what its uploader wrote about the picture. The sweep
        # is `locate` + `sniff` + the matched sections — it never calls
        # `look`, so a teaching that only rides in the digest reaches the
        # walk and not the console's ordinary ask. And whether the notes
        # section happens to match the question's terms is not a good reason
        # to withhold what a person wrote about how to read this data.
        if meta.get("type") in ("dataset", "media"):
            notes = vine.look(nid, fields=["notes"]).get("notes")
            if notes:
                item["notes"] = notes
        results.append(item)
    payload = {"query": query, "terms": terms, "results": results, "truncated": False}
    if excluded:
        # C.6c.4 rule 3: the reader is told what was set aside and by what,
        # in the same breath — the difference between "nothing matches" and
        # "what matched has been replaced".
        payload["superseded_excluded"] = excluded
    if loc.get("window") or sn.get("window"):
        payload["window"] = loc.get("window") or sn.get("window")
    excluded = max(loc.get("undated_excluded", 0), sn.get("undated_excluded", 0))
    if excluded:
        payload["undated_excluded"] = excluded
    # budget: drop whole tail results, never slice a body silently (C.6c)
    payload = shrink_list_to_budget(payload, "results", BUDGET_HARVEST)
    if not payload["results"]:
        # C.6c rule 5 (v0.52): the sweep is the call a caller makes INSTEAD
        # of navigating, so an empty one with no coverage is C.1.1's silence
        # arriving where there is no next primitive to try.
        payload["searched"] = loc.get("searched", sn.get("scanned_nodes", 0))
        if "matched_window" in loc:
            # C.13.2: whether the WINDOW was the reason is the first thing a
            # caller needs, and the sweep is the call made INSTEAD of
            # navigating — there is no next primitive to try.
            payload["matched_window"] = loc["matched_window"]
            payload["hint"] = loc.get("hint", "")
        else:
            payload["hint"] = (
                "Nothing matched the curated scent or the bodies. The terms "
                "above were derived from the question — pass `terms` "
                "explicitly, or ask a narrower question."
            )
    return payload
