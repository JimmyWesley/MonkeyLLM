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
from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.models import (
    ALIAS_MAX_CHARS, MAX_ALIASES, NOTES_SECTION, fit_summary,
)
from monkeyllm.parser import append_section

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
            # G.4.2 rule 1 (v0.78): a tag the rule refuses is counted here
            # exactly as the Curator counts its own — the reviewer's tags
            # are not a way to lose one in silence.
            tags, dropped = Curator.clean_tags(approved.get("tags"))
            draft["tags"] = tags
            hook.stats["tags_dropped"] += dropped
        if "links" in approved:
            draft["links"] = _links(approved.get("links"), draft, vine, policy)
        return draft

    hook.stats = {"tags_dropped": 0, "aliases_clipped": 0}
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


# -- J.8.4 (v0.78): the passport travels with the bytes -------------------------

# What an upload entry may say about the node its bytes become. Anything
# else is E_SCHEMA before the first byte stages — a passport is a contract
# about scent, and an unknown key is a typo the caller would otherwise never
# hear about.
PASSPORT_FIELDS = frozenset({"title", "summary", "tags", "aliases", "links", "notes"})
TITLE_MAX_CHARS = 200
NOTES_MAX_CHARS = 4000


def validate_passport(name: str, passport) -> dict:
    """Check the SHAPE of an upload entry's `passport` before anything stages.

    Resolution — whether a link's target exists and is in scope — is the
    hook's business at curation time (G.4.2.1), exactly as for a reviewed
    draft; here the question is only whether the caller sent something a
    passport can be made of. A batch with one malformed passport stages
    nothing, so a retry never meets its own half-staged files.
    """
    if not isinstance(passport, dict):
        raise VineError(E_SCHEMA, f"'{name}': passport must be an object",
                        hint="{title?, summary?, tags?, aliases?, links?, notes?}")
    unknown = sorted(set(passport) - PASSPORT_FIELDS)
    if unknown:
        raise VineError(E_SCHEMA,
                        f"'{name}': passport has unknown field(s): {unknown}",
                        hint=f"Allowed: {sorted(PASSPORT_FIELDS)}.")
    out: dict = {}
    if "title" in passport:
        title = passport["title"]
        if not isinstance(title, str) or not title.strip():
            raise VineError(E_SCHEMA, f"'{name}': passport.title must be a non-empty string")
        if len(title.strip()) > TITLE_MAX_CHARS:
            raise VineError(E_SCHEMA,
                            f"'{name}': passport.title is over {TITLE_MAX_CHARS} characters")
        out["title"] = title.strip()
    if "summary" in passport:
        summary = passport["summary"]
        if not isinstance(summary, str) or not summary.strip():
            raise VineError(E_SCHEMA, f"'{name}': passport.summary must be a non-empty string")
        fitted = fit_summary(summary.strip())
        if not fitted:
            # `fit_summary` trims an over-long summary into the A.4 budget and
            # returns None only for what trimming cannot rescue (boilerplate,
            # nothing left). That is the one summary refused outright: the
            # caller asked for a scent the forest cannot navigate by.
            raise VineError(E_SCHEMA,
                            f"'{name}': passport.summary does not fit the A.4 budget",
                            hint="One or two plain sentences saying what the node holds.")
        out["summary"] = fitted
    if "tags" in passport:
        tags = passport["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise VineError(E_SCHEMA, f"'{name}': passport.tags must be a list of strings")
        out["tags"] = tags
    if "aliases" in passport:
        aliases = passport["aliases"]
        if (not isinstance(aliases, list)
                or not all(isinstance(a, str) and a.strip() for a in aliases)):
            raise VineError(E_SCHEMA,
                            f"'{name}': passport.aliases must be a list of non-empty strings")
        if len(aliases) > MAX_ALIASES:
            raise VineError(E_SCHEMA,
                            f"'{name}': passport.aliases holds more than {MAX_ALIASES} entries")
        if any(len(a.strip()) > ALIAS_MAX_CHARS for a in aliases):
            raise VineError(E_SCHEMA,
                            f"'{name}': an alias is over {ALIAS_MAX_CHARS} characters")
        out["aliases"] = [a.strip() for a in aliases]
    if "links" in passport:
        links = passport["links"]
        if not isinstance(links, list):
            raise VineError(E_SCHEMA, f"'{name}': passport.links must be a list")
        for link in links:
            if not isinstance(link, dict) or not isinstance(link.get("target"), str):
                raise VineError(E_SCHEMA,
                                f"'{name}': each passport link is {{target, rel?, note?}}")
            rel = link.get("rel", "related-to")
            if rel != "related-to":
                raise VineError(E_SCHEMA,
                                f"'{name}': passport links carry rel 'related-to' only",
                                hint="A certain link is what graft(add_links) is for.")
        out["links"] = links
    if "notes" in passport:
        notes = passport["notes"]
        if not isinstance(notes, str) or not notes.strip():
            raise VineError(E_SCHEMA, f"'{name}': passport.notes must be a non-empty string")
        if len(notes) > NOTES_MAX_CHARS:
            raise VineError(E_SCHEMA,
                            f"'{name}': passport.notes is over {NOTES_MAX_CHARS} characters")
        out["notes"] = notes.strip()
    return out


class PassportGate:
    """An `on_curate` hook that pins the caller's passport on the entries
    that carry one and lets the bound curator speak for the rest (J.8.4).

    One hook object for the whole batch rather than one per entry, because
    the decision is per DRAFT: an upload may mix a screenshot the agent
    already described with a spreadsheet it never opened. A draft whose
    `source_path` has a passport is never shown to the model — what ships
    is what the caller declared, re-validated under the reviewer's rules
    (J.8.1). Any other draft goes to `curator` exactly as before, and the
    curator's `stats` stay readable through this object so the report's
    counters (G.4) keep counting what the model did.
    """

    def __init__(self, passports: dict[str, dict], vine, policy, curator=None):
        self.passports = dict(passports)
        self.vine = vine
        self.policy = policy
        self.curator = curator
        # Staged rel names whose passport was pinned. Keyed like `passports`
        # so the finisher can name what was NOT applied (a refresh never
        # curates, G.3) — `passports_ignored` in the report.
        self.applied: set[str] = set()
        self._own = {"tags_dropped": 0, "aliases_clipped": 0}

    @property
    def stats(self) -> dict:
        # One dict the report reads deltas off (G.4.2 rule 1): the model's
        # counters for the drafts it curated PLUS this gate's own for the
        # passports it pinned. A passport tag the rule refuses is a refusal
        # like any other — counted, never silent.
        out = dict(getattr(self.curator, "stats", None) or {})
        for name, count in self._own.items():
            out[name] = int(out.get(name, 0) or 0) + count
        return out

    def __call__(self, draft: dict) -> dict:
        passport = self.passports.get(str(draft.get("source_path") or ""))
        if passport is None:
            if self.curator is not None:
                result = self.curator(draft)
                return result if isinstance(result, dict) else draft
            return draft
        return self._apply(draft, passport)

    def _apply(self, draft: dict, passport: dict) -> dict:
        if passport.get("title"):
            draft["title"] = passport["title"]
        summary = _summary(passport.get("summary"), draft.get("summary"))
        if summary:
            draft["summary"] = summary
        if "tags" in passport:
            tags, dropped = Curator.clean_tags(passport.get("tags"))
            draft["tags"] = tags
            self._own["tags_dropped"] += dropped
        if "aliases" in passport:
            # The file's own name still counts (G.2.6): what the caller adds
            # joins what the walk derived, first come first kept, capped —
            # and the cap's overflow is counted (`aliases_clipped`), as a
            # sync counts its own.
            merged: list[str] = []
            for alias in list(draft.get("aliases") or []) + list(passport["aliases"]):
                if alias not in merged:
                    merged.append(alias)
            if len(merged) > MAX_ALIASES:
                self._own["aliases_clipped"] += len(merged) - MAX_ALIASES
            draft["aliases"] = merged[:MAX_ALIASES]
        if "links" in passport:
            draft["links"] = _links(passport.get("links"), draft, self.vine, self.policy)
        if passport.get("notes"):
            # C.2.1: the section a person writes and `look` carries everywhere.
            body = str(draft.get("body") or "")
            draft["body"] = append_section(body, NOTES_SECTION, passport["notes"])
        self.applied.add(str(draft.get("source_path") or ""))
        return draft


def passport_gate(passports: dict[str, dict], vine, policy, curator=None) -> PassportGate:
    """The J.8.4 hook: caller's passports over the model's curation, per draft."""
    return PassportGate(passports, vine, policy, curator)
