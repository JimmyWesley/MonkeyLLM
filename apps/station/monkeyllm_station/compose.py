# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""Two-phase compose: reviewing a passport before the forest keeps it (J.8.1).

Curation is the one ingest step whose output somebody may want to see first.
A summary is the scent every later hop navigates by (A.4) and a proposal is
what the Ranger spends the next month promoting or pruning (H.2); both are
cheap to fix in a draft and expensive to fix in a node that already exists,
already has a commit, and may already have been read.

Two functions, and the split between them is the whole design:

- `review_of` projects the Gardener's drafts into what a reviewer needs —
  including the *title* of every proposed target, because a review that
  shows an id without saying what it is is not a review.
- `approval_hook` turns the reviewer's answer back into an ordinary
  `on_curate` hook (G.4.3), so accepting walks the same converter, the same
  content policy, the same plant and the same commit as any adopted file.

The second function is where the security lives. A returned draft is a
client payload — it went to a browser and came back — so nothing in it is
trusted. Every field is re-derived under the same rules the Curator was held
to: the summary re-clipped to the A.4 budget, tags re-cleaned and capped,
and every link re-checked against G.4.2.1. Trusting the round-trip would
move the hallucination guard to the client, which is to say remove it.
"""

from __future__ import annotations

from typing import Callable

from monkeyllm.curator import (
    MAX_PROPOSALS, NOTE_MAX_CHARS, PROPOSAL_CONFIDENCE, Curator,
)
from monkeyllm.models import fit_summary

# What a reviewer is shown, and nothing else. Bodies are deliberately absent:
# the reviewer wrote the text, and a passport is scent, not flesh.
DRAFT_FIELDS = ("id", "parent", "type", "title", "summary", "tags")


def review_of(vine, policy, drafts: list[dict]) -> list[dict]:
    """Project staged drafts into the reviewable shape (J.8.1)."""
    out = []
    for draft in drafts:
        view = {k: draft.get(k) for k in DRAFT_FIELDS if k in draft}
        view["tags"] = list(draft.get("tags") or [])
        view["links"] = [
            {**link, "target_title": _title_of(vine, policy, link.get("target"))}
            for link in draft.get("links") or []
            if isinstance(link, dict)
        ]
        out.append(view)
    return out


def _title_of(vine, policy, node_id) -> str | None:
    """The title of a proposed target, or None when it has none to give.

    Scope-checked like everything else: the Curator's candidates were already
    filtered (J.10), but this reads the catalog directly and a projection
    that skipped the check would be a second, unfiltered way to ask.
    """
    if not isinstance(node_id, str) or not policy.in_scope(node_id):
        return None
    return _field(vine.catalog.get(node_id), "title")


def _field(row, name: str):
    """`Catalog.get` hands back a `sqlite3.Row`, which indexes but does not
    `.get` — and raises IndexError rather than returning None for a column
    it does not have."""
    if row is None:
        return None
    return row[name] if name in row.keys() else None


def approval_hook(approved: dict, vine, policy) -> Callable[[dict], dict]:
    """An `on_curate` hook that pins what the reviewer approved.

    Runs last, so third-party hooks still see the draft and the reviewer's
    decision still wins: they approved the tags those hooks produced.
    """

    def hook(draft: dict) -> dict:
        summary = _summary(approved.get("summary"), draft.get("summary"))
        if summary:
            draft["summary"] = summary
        if "tags" in approved:
            draft["tags"] = Curator._clean_tags(approved.get("tags"))
        if "links" in approved:
            draft["links"] = _links(approved.get("links"), draft, vine, policy)
        return draft

    return hook


def _summary(edited, derived: str | None) -> str | None:
    """The approved summary if it survives the A.4 budget, else what the
    pipeline derived. An empty edit is a reviewer clearing the field, not a
    request to plant a node with no scent."""
    text = str(edited or "").strip()
    if not text:
        return derived
    # `fit_summary` trims an over-long summary into the budget and returns
    # None only for what trimming cannot rescue (empty, boilerplate).
    return fit_summary(text) or derived


def _links(edited, draft: dict, vine, policy) -> list[dict]:
    """Re-apply G.4.2.1 to whatever came back, as if the reviewer had
    proposed it themselves — because they may well have."""
    kept: list[dict] = []
    seen: set[str] = set()
    for link in edited if isinstance(edited, list) else []:
        if len(kept) >= MAX_PROPOSALS:
            break
        if not isinstance(link, dict):
            continue
        # A reviewer approves proposals; structure is `graft`'s business.
        if str(link.get("rel") or "related-to") != "related-to":
            continue
        target = link.get("target")
        if not isinstance(target, str) or target in seen:
            continue
        if target in (draft.get("id"), draft.get("parent")):
            continue
        if not policy.in_scope(target) or not vine.forest.exists(target):
            continue
        if _field(vine.catalog.get(target), "type") == "branch" \
                or target.endswith("/_index"):
            continue  # a link to a folder carries no scent (G.4.2.1)
        # Confidence is not the reviewer's to raise. Glancing at a link is
        # not evidence that it is used, and 0.3 is exactly the population
        # the Ranger manages (H.2); a certain link is what `graft` is for.
        out = {"rel": "related-to", "target": target,
               "confidence": PROPOSAL_CONFIDENCE}
        note = link.get("note")
        if isinstance(note, str) and note.strip():
            out["note"] = note.strip()[:NOTE_MAX_CHARS]
        kept.append(out)
        seen.add(target)
    return kept
