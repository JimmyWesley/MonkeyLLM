# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""G.4.2 — the Gardener's LLM curation stage (spec v0.9; edge proposals
G.4.2.1, spec v0.12; the tag rule and alias proposals, spec v0.75).

The Curator is deliberately shaped as an `on_curate` hook: it receives the
draft node dict and returns it enriched. Plug it into the Gardener's hook
pipeline and every adopted markdown/document node gets an A.4 summary
written by the model (validate-and-retry), plus tags — guided by the
operator's curation directives (G.6 config) — and, when a candidate
provider is wired (`make_candidates`), `related-to` link proposals at
link-level confidence 0.3 toward catalog-offered EXISTING nodes only
(the hallucination guard is structural): the Gardener proposes, usage
heats, the Ranger promotes or prunes (Part H).

It NEVER blocks the pipeline: any failure (bad JSON, invalid summary after
retries, transport error) falls back to the deterministic derived summary
and is counted in `stats` — the >= 95% acceptance criterion is measured,
not assumed.

Never blocking is not the same as never telling. A bound model that never
answers produces exactly the output of no model at all, so the failure has
to leave a trace the caller can read: `stats["transport_errors"]` counts
them and `last_error` keeps the most recent one. Without that, a wrong key
or a typo in the model name is indistinguishable from a working ingest.

v0.75 applies that same sentence to the tags. What the model wrote was
filtered against an ASCII pattern and the losses were never counted, so a
Portuguese forest read as a model that would not write tags — the filter is
now the shared rule (`models.validate_tag`, Unicode, accents KEPT because
the index folds them at match time) and every refusal is in
`stats["tags_dropped"]`. The Curator also proposes ALIASES now (G.4.3),
kept only where they occur in the document under C.6b's own fold: it is the
one participant that reads the whole text, and until v0.75 it never
proposed a single name.
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable

from monkeyllm.dialect import SUMMARY_MAX_TOKENS
from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.models import (
    ALIAS_MAX_CHARS,
    MAX_ALIASES,
    fit_summary,
    is_lang,
    tag_key,
    validate_summary,
    validate_tag,
)
from monkeyllm.tokens import CHARS_PER_TOKEN, estimate_tokens
from monkeyllm.vine import fold

MAX_ATTEMPTS = 3
CONTENT_BUDGET_TOKENS = 1500  # how much of the body the model sees
# G.4.2 rule 4 (v0.75): the cap is a passport budget, and five of them were
# sized for generic words. It starves a node the moment the tags are
# specific enough to be worth having — a document with a ticket, a
# standard, a component and a client has spent four of five before it names
# what it is about.
MAX_TAGS = 12
# G.4.2.1 edge proposals
MAX_PROPOSALS = 3
PROPOSAL_CONFIDENCE = 0.3   # the C.8 ladder's bottom rung — Part H's scope
CANDIDATE_LIMIT = 8
NOTE_MAX_CHARS = 120
REPLY_KEPT_CHARS = 400  # enough of a rejected reply to see what went wrong
# The A.4 ceiling as the model can actually measure it. "60 tokens" is a
# number no model counts reliably; characters it can approximate. Derived
# from the estimator so the two can never drift apart.
SUMMARY_MAX_CHARS = SUMMARY_MAX_TOKENS * CHARS_PER_TOKEN

SYSTEM_PROMPT = """\
You write frontmatter summaries for nodes of a knowledge forest. An agent
will decide from the summary alone whether the node matters — the summary
is the SCENT. Rules (normative, spec A.4):
- 1 to 3 sentences, AT MOST {max_chars} CHARACTERS in total — count the
  characters, this is a hard limit and long summaries are rejected.
  Shorter is better.
- Sentence 1: WHAT it is (category + subject).
- Sentence 2: the key content — concrete numbers, names, time scope.
- Dated content (events, reports, meetings, releases, deadlines): the date
  (at least month + year) MUST appear in the summary. Search over the
  forest matches summaries only — a date left in the body is invisible to
  time-scoped searches.
- Optional sentence 3: what is NOT here / where the complement lives.
- NEVER start with boilerplate like "This document describes" or
  "File containing" — go straight to the substance.
- Write the summary in the SAME LANGUAGE as the content.
- Also propose up to {max_tags} tags: the tokens somebody would actually
  SEARCH this document by, written in the same language as the content and
  keeping its own spelling — accents included, never stripped. Take them
  from: identifiers and codes (ticket, contract, SKU, standard, version,
  metric), proper names (product, system, client, team, place), the
  categories the document belongs to, and the recurring patterns or
  techniques it is about. A tag is ONE token of letters and digits, with
  `-` or `_` inside it and no spaces, so compound tokens like
  `rate-limit`, `iso-27001` or `be-291` are wanted. Prefer lowercase.
  Generic words nobody would type into a search are worth nothing.
- Optionally propose aliases: OTHER NAMES for this node's subject that are
  not its title — acronyms and their expansions, product or project codes,
  ticket or contract identifiers, former names, alternative spellings.
  Every alias MUST occur in the content you were given; one that does not
  is discarded. No alias is a fine answer.
{directives}
Reply with ONE JSON object only, no prose around it:
{{"summary": "...", "tags": ["...", "..."], "aliases": ["..."]}}"""

# A.3.2 rule 4 (v0.75): where the forest KNOWS the language, the prompt
# states it instead of asking the model to work it out. The two phrasings
# below are the exact substrings of the prompts above that ask for the
# inference — written down here so the substitution is targeted and so a
# call with no `lang` produces a prompt that is byte-identical to the
# pre-v0.75 one. A forest that has never set a language must behave
# exactly as it did, and "exactly" includes the bytes sent to a provider,
# which is what the answer store keys on.
#
# The Curator's own inference stays fine for writing a summary; what rule 3
# forbids is writing that inference back into the passport. This is the
# other half of the same rule: when somebody HAS said, stop guessing.
INFER_LANGUAGE_SUMMARY = "- Write the summary in the SAME LANGUAGE as the content."
INFER_LANGUAGE_TAGS = "written in the same language as the content and"
INFER_LANGUAGE_BRANCH = "- Write in the SAME LANGUAGE as the entries."


def stated_lang(draft: dict) -> str | None:
    """The draft's own `lang`, when it is one (A.3.2 rules 1 and 4).

    A draft is not a passport yet, so the tag reaching here has not met
    `validate_lang`. Anything that is not the stated shape is IGNORED
    rather than refused — the Curator's job is a summary, and `plant` is
    where a malformed tag is refused, loudly, naming the field. Ignoring it
    here costs one prompt that asks the model to infer, which is exactly
    what happens today.
    """
    lang = draft.get("lang")
    return lang if is_lang(lang) else None


def _state_language(prompt: str, lang: str) -> str:
    """One prompt with the language stated rather than inferred."""
    stated = (f"- The document's language is {lang}; write the summary and "
              f"tags in it.")
    return (prompt
            .replace(INFER_LANGUAGE_SUMMARY, stated)
            .replace(INFER_LANGUAGE_TAGS, f"written in {lang} and")
            .replace(INFER_LANGUAGE_BRANCH,
                     f"- The material's language is {lang}; write in it."))


RETRY_PROMPT = ("Your previous summary was rejected: {error}. Rewrite it "
                "following the rules strictly and keep the summary under "
                "{max_chars} characters. JSON only.")

# `.replace` rather than `.format`: this prompt ends with a literal JSON
# object, and escaping those braces to satisfy the formatter would make the
# example the model copies harder to read than the rule it illustrates.
BRANCH_PROMPT = """\
You summarize a REGION (branch) of a knowledge forest. Below are the entry
lines of its children — sub-branches and notes, each already summarized.
Write the branch's summary: the SCENT an agent reads to decide whether to
descend here. Rules (normative, spec A.4/A.5):
- 1 to 3 sentences, AT MOST {max_chars} CHARACTERS in total — count the
  characters, this is a hard limit. Shorter is better.
- Say WHAT lives here: themes, concrete names, time scope visible in the
  entries. Synthesize the region — do not enumerate every child.
- If the entries make it visible, add where to go for what is NOT here.
- NEVER start with boilerplate like "This folder contains" or "This branch
  groups" — go straight to the substance.
- Write in the SAME LANGUAGE as the entries.
Reply with ONE JSON object only, no prose around it:
{"summary": "..."}""".replace("{max_chars}", str(SUMMARY_MAX_CHARS))

PROPOSE_PROMPT = """\
You connect nodes of a knowledge forest. Below is a NEW node and a closed
list of EXISTING candidate nodes. Pick the candidates (0 to {max_proposals})
whose content is genuinely related to the new node — the relation must be
visible in the summaries, not guessed. Most nodes have NO related candidate;
an empty list is a good answer. Never invent ids outside the list.

NEW node:
{node}

Candidates:
{candidates}

Reply with ONE JSON object only, no prose around it:
{{"related": [{{"id": "<candidate id>", "note": "<short reason>"}}]}}"""


def _clip(text: str, budget: int = CONTENT_BUDGET_TOKENS) -> str:
    """The content the model sees, cut to the budget — by LINE.

    Flattening every newline, as this did until v0.45, is invisible on
    prose and destructive on structure: a dataset's map (G.2.3) and a
    converted document's pipe tables (G.2.1) both stop being tables, and
    the model is left guessing where a row ended. Horizontal whitespace
    still collapses, because that carries nothing.

    Every loop here is guaranteed to make progress, and the final slice
    catches the pathological input both loops can't shrink: one enormous
    unbroken word.
    """
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.splitlines()]
    while len(lines) > 1 and estimate_tokens("\n".join(lines)) > budget:
        del lines[max(1, len(lines) * 3 // 4):]
    out = "\n".join(lines).strip()
    if estimate_tokens(out) <= budget:
        return out
    words = out.split()
    while len(words) > 1 and estimate_tokens(" ".join(words)) > budget:
        del words[max(1, len(words) * 3 // 4):]
    return " ".join(words)[:budget * CHARS_PER_TOKEN]


def _clip_lines(lines: list[str], budget: int = CONTENT_BUDGET_TOKENS) -> str:
    """Whole-line clipping: keep entry lines intact up to the budget."""
    kept: list[str] = []
    used = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        tokens = estimate_tokens(line)
        if kept and used + tokens > budget:
            kept.append(f"(... {len(lines) - len(kept)} more entries)")
            break
        kept.append(line)
        used += tokens
    return "\n".join(kept)


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


# `"summary": "…` up to wherever the reply stopped. The closing quote is
# deliberately optional.
_SUMMARY_FIELD = re.compile(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)', re.DOTALL)


def _salvage(text: str) -> dict | None:
    """Recover the summary from a reply that was cut off mid-JSON.

    `max_tokens` truncates the message, not the sentence the model meant to
    write: the summary is usually complete and only the closing brace is
    missing. Rejecting that as "no JSON" spends three model calls to arrive
    at the deterministic fallback, over a reply that was already good. What
    comes back here is still put through `validate_summary` like any other —
    this widens what can be READ, never what is accepted.
    """
    m = _SUMMARY_FIELD.search(text)
    if not m:
        return None
    try:  # json.loads unescapes \n, \uXXXX and friends
        summary = json.loads(f'"{m.group(1)}"')
    except json.JSONDecodeError:
        return None
    return {"summary": summary, "tags": []} if isinstance(summary, str) else None


class Curator:
    """An `on_curate` hook (G.4 rule 3) that fills the scent via the LLM:
    the A.4 summary and the G.4.2 tags, plus the G.4.3 alias proposals and
    the G.4.2.1 edge proposals."""

    def __init__(self, chat: Callable[[list[dict]], str], directives: str = "",
                 candidates: Callable[[str], list[dict]] | None = None):
        self.chat = chat
        self.candidates = candidates  # G.4.2.1 provider; None = no proposals
        directives_block = (
            f"Operator directives (apply them):\n{directives.strip()}\n"
            if directives.strip() else ""
        )
        self.system = SYSTEM_PROMPT.format(max_tags=MAX_TAGS,
                                           max_chars=SUMMARY_MAX_CHARS,
                                           directives=directives_block)
        # A.3.2 rule 4: one variant per stated language, built on demand.
        # A batch is usually one language, so this is one substitution per
        # ingest rather than one per document.
        self._system_by_lang: dict[str, str] = {}
        # `skipped` (v0.45) is the third outcome beside a summary and a
        # fallback: a draft with nothing for a model to read. Without it, a
        # batch that needed no model is four zeros — indistinguishable from
        # a model that answered and was refused, and the two have opposite
        # fixes (J.8).
        # `tags_dropped` (G.4.2 rule 1, v0.75) is the count that did not
        # exist while an accented tag was discarded in silence: a filter
        # nobody is told about is indistinguishable from a model that wrote
        # nothing, and the operator sent to repair the wrong half is the
        # cost. `aliases_clipped` is G.2.6's own counter, kept here for the
        # G.4.3 proposals that overflow the field's cap.
        self.stats = {"llm_summaries": 0, "fallbacks": 0, "retries": 0,
                      "skipped": 0,
                      "links_proposed": 0, "proposal_fallbacks": 0,
                      "branch_rollups": 0, "branch_fallbacks": 0,
                      "transport_errors": 0, "rejected": 0, "repaired": 0,
                      "tags_dropped": 0, "aliases_clipped": 0}
        # Two different silences, and they need two different fixes.
        # `last_error`: the endpoint never answered (key, URL, model name).
        # `last_reject` + `last_reply`: it answered, and the answer failed
        # the A.4 contract every time — which is a prompt, budget or model
        # problem, not a connectivity one.
        self.last_error: str | None = None
        self.last_reject: str | None = None
        self.last_reply: str | None = None

    def __call__(self, draft: dict) -> dict:
        # G.4.6 (v0.45): a dataset is curated from its G.2.3 map — structure
        # and three rows per table, already in the draft's body — and never
        # from the payload or the source. The map is bounded by its own
        # rules, so a 5 MB CSV and a 5 GB database cost the model the same.
        # (It used to be skipped outright: before v0.44 there was nothing to
        # read but a column list, which the factual template already stated
        # better than a model would.)
        body = draft.get("body")
        if not body:
            self.stats["skipped"] += 1
            return draft
        result = self._ask(draft.get("title", ""), body,
                           lang=stated_lang(draft))
        if result is not None:
            summary, tags, aliases = result
            self.stats["llm_summaries"] += 1
            draft["summary"] = summary
            merged = list(draft.get("tags") or [])
            seen = {tag_key(t) for t in merged}
            for tag in tags:
                # G.4.2 rule 2: uniqueness is decided on the NFC + folded
                # key, so two spellings of one word are one tag.
                if tag_key(tag) not in seen:
                    seen.add(tag_key(tag))
                    merged.append(tag)
            draft["tags"] = merged
            self._merge_aliases(draft, aliases, body)
        else:
            self.stats["fallbacks"] += 1  # the derived summary stays in place
        if self.candidates is not None:
            self._propose(draft)
        return draft

    # -- G.4.3: alias proposals ---------------------------------------------

    def _merge_aliases(self, draft: dict, proposed, body: str) -> None:
        """G.4.3: keep the proposed names the document actually contains,
        and union them into what the draft already carries.

        Two rules do the work. **The guard is structural** (rule 2): an
        alias must OCCUR in the curated content under C.6b's fold — the
        same fold `sniff` matches with, imported rather than rewritten — so
        a model inventing a plausible acronym is refused by the check
        instead of trusted by the prompt. And the merge is **union, never
        displacement** (rule 4, G.2.6 rule 3): adds only, twice is once,
        and the path-derived and hand-written aliases already in the draft
        outrank a model that guessed one. Overflow past the field's own cap
        is counted with G.2.6's `aliases_clipped`, never dropped in
        silence.
        """
        if not isinstance(proposed, list) or not proposed:
            return
        # The title is part of the haystack: a document titled "BE-291
        # (Rate Limiter)" contains its own ticket number, and the alias
        # that matters most is the one the title carries beside the words.
        haystack = fold(f"{draft.get('title', '')}\n{body}")
        title = fold(str(draft.get("title", "")).strip())
        have = [str(a) for a in (draft.get("aliases") or [])]
        keys = {fold(a.strip()) for a in have}
        kept = list(have)
        clipped = 0
        for raw in proposed:
            if not isinstance(raw, str):
                continue
            alias = raw.strip()
            if not alias or len(alias) > ALIAS_MAX_CHARS:
                continue
            key = fold(alias)
            if key not in haystack or key == title or key in keys:
                continue
            if len(kept) >= MAX_ALIASES:
                clipped += 1
                continue
            keys.add(key)
            kept.append(alias)
        if clipped:
            self.stats["aliases_clipped"] += clipped
        if len(kept) > len(have):
            draft["aliases"] = kept

    # -- G.4.2.1: edge proposals --------------------------------------------

    def _propose(self, draft: dict) -> None:
        query = f"{draft.get('title', '')} {draft.get('summary', '')}".strip()
        offered: dict[str, dict] = {}
        for c in self.candidates(query) or []:
            cid = c.get("id")
            # the draft itself and its parent are never candidates (G.4.2.1)
            if cid and cid not in (draft.get("id"), draft.get("parent")):
                offered[cid] = c
        if not offered:
            return
        cand_block = "\n".join(
            f"- id: {cid}\n  title: {c.get('title', '')}\n"
            f"  summary: {c.get('summary', '')}"
            for cid, c in list(offered.items())[:CANDIDATE_LIMIT]
        )
        node_block = (f"id: {draft.get('id', '')}\ntitle: {draft.get('title', '')}\n"
                      f"summary: {draft.get('summary', '')}")
        prompt = PROPOSE_PROMPT.format(max_proposals=MAX_PROPOSALS,
                                       node=node_block, candidates=cand_block)
        try:
            reply = self.chat([{"role": "user", "content": prompt}])
        except Exception as e:
            self.stats["proposal_fallbacks"] += 1  # never blocks the plant
            self._record(e)
            return
        picks = (_extract_json(reply) or {}).get("related")
        if not isinstance(picks, list):
            self.stats["proposal_fallbacks"] += 1
            return
        links = list(draft.get("links") or [])
        existing = {(l.get("rel"), l.get("target"))
                    for l in links if isinstance(l, dict)}
        added = 0
        for pick in picks:
            if added >= MAX_PROPOSALS:
                break
            cid = pick.get("id") if isinstance(pick, dict) else pick
            # hallucination guard is structural: only offered ids exist
            if not isinstance(cid, str) or cid not in offered:
                continue
            if ("related-to", cid) in existing:
                continue
            link = {"rel": "related-to", "target": cid,
                    "confidence": PROPOSAL_CONFIDENCE}
            note = pick.get("note") if isinstance(pick, dict) else None
            if isinstance(note, str) and note.strip():
                link["note"] = note.strip()[:NOTE_MAX_CHARS]
            links.append(link)
            existing.add(("related-to", cid))
            added += 1
        if added:
            draft["links"] = links
            self.stats["links_proposed"] += added

    # -- G.4.4: branch rollup ------------------------------------------------

    def branch_summary(self, title: str, entry_lines: list[str],
                       lang: str | None = None) -> str | None:
        """Synthesize a branch summary from its children's entry lines
        (G.4.4). Returns None on failure — the caller falls back.

        `lang` is A.3.2 rule 4 on the rollup: where the branch states a
        language, the prompt states it too. Absent — which is every caller
        that has not been taught to pass it — the prompt is the one that
        shipped, to the byte.
        """
        entries = _clip_lines(entry_lines)
        if not entries:
            self.stats["branch_fallbacks"] += 1
            return None
        prompt = (_state_language(BRANCH_PROMPT, lang)
                  if is_lang(lang) else BRANCH_PROMPT)
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Branch: {title}\n\nChildren:\n{entries}"},
        ]
        result = self._validated(messages)
        if result is None:
            self.stats["branch_fallbacks"] += 1
            return None
        self.stats["branch_rollups"] += 1
        return result[0]

    def _system_prompt(self, lang: str | None) -> str:
        """A.3.2 rule 4: the stated language, or the prompt unchanged.

        `None` returns `self.system` itself — the same object, so a forest
        that has never set a language sends the bytes it always sent.
        """
        if not lang:
            return self.system
        if lang not in self._system_by_lang:
            self._system_by_lang[lang] = _state_language(self.system, lang)
        return self._system_by_lang[lang]

    def _ask(self, title: str, body: str,
             lang: str | None = None) -> tuple[str, list[str], list] | None:
        messages = [
            {"role": "system", "content": self._system_prompt(lang)},
            {"role": "user", "content": f"Title: {title}\n\nContent:\n{_clip(body)}"},
        ]
        return self._validated(messages)

    def _validated(self,
                   messages: list[dict]) -> tuple[str, list[str], list] | None:
        """Validate-and-retry loop shared by banana (_ask) and branch
        (branch_summary) summaries. Returns (summary, tags, raw aliases) —
        the aliases are still raw because only the caller holds the
        document they have to be found in (G.4.3 rule 2).

        Exhausting the retries is not the end: an over-long summary is
        trimmed to the budget rather than discarded (G.4.2). The model's
        words, cut to fit, beat the first-sentences heuristic every time —
        and the operator paid for them already.
        """
        overlong: tuple[str, dict] | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                reply = self.chat(messages)
            except Exception as e:
                self._record(e)
                return None  # transport problems: fall back, never block
            error = None
            if not reply.strip():
                # Distinct from "no JSON here": an empty message is the
                # signature of a thinking model that spent its whole token
                # budget reasoning, and it needs a different fix.
                error = "the model returned an empty message"
            else:
                obj = _extract_json(reply) or _salvage(reply)
                summary = (obj or {}).get("summary", "")
                if not isinstance(summary, str) or not summary.strip():
                    error = "no summary found in the JSON reply"
                else:
                    try:
                        validate_summary(summary.strip())
                    except VineError as e:
                        error = e.message
                        if "exceeds" in e.message:
                            overlong = (summary.strip(), obj or {})
            if error is None:
                # The last rejection is NOT cleared here: a batch where the
                # last document happened to succeed still owes the operator
                # an example of the ones that did not.
                return (summary.strip(), self._tags((obj or {}).get("tags")),
                        (obj or {}).get("aliases") or [])
            self.stats["retries"] += 1
            # Kept, not just counted. "The model answered and I threw all of
            # it away" is the state an operator cannot debug: the rejection
            # reason names the rule, the reply shows what broke it.
            self.last_reject = error
            self.last_reply = reply.strip()[:REPLY_KEPT_CHARS]
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user",
                             "content": RETRY_PROMPT.format(
                                 error=error, max_chars=SUMMARY_MAX_CHARS)})

        if overlong is not None:
            trimmed = fit_summary(overlong[0])
            if trimmed is not None:
                self.stats["repaired"] += 1
                return (trimmed, self._tags(overlong[1].get("tags")),
                        overlong[1].get("aliases") or [])
        self.stats["rejected"] += 1
        return None

    def _record(self, exc: Exception) -> None:
        """Keep why the model stayed silent. A `VineError` carries the
        endpoint's own reply in `hint` — the 401 body, the unknown-model
        line — which is the part that tells an operator what to fix."""
        self.stats["transport_errors"] += 1
        detail = getattr(exc, "hint", None)
        self.last_error = (f"{exc}: {detail}" if detail else str(exc))[:300] \
            or exc.__class__.__name__

    def _tags(self, tags) -> list[str]:
        """The kept tags, with every loss counted into the stats (G.4.2
        rule 1)."""
        kept, dropped = self.clean_tags(tags)
        self.stats["tags_dropped"] += dropped
        return kept

    @staticmethod
    def clean_tags(tags) -> tuple[list[str], int]:
        """G.4.2 rules 1, 2 and 4: the tags that survive, and how many did
        not.

        There are two ways to lose a tag and both are counted: the rule
        refused it (rule 2, one spelling of it — `validate_tag`), or the
        passport budget was already full (rule 4, clipped from the tail).
        A duplicate is neither: the same tag twice was always one tag.

        Tags are lowercased on the way in — every forest planted before
        v0.75 is lowercase — and never case-FOLDED, because folding
        rewrites spellings (`Straße` -> `strasse`) and a tag silently
        rewritten is the same failure as a tag silently dropped (rule 6).
        Folding decides uniqueness only, through `tag_key`.
        """
        out: list[str] = []
        seen: set[str] = set()
        dropped = 0
        for tag in tags if isinstance(tags, list) else []:
            t = str(tag).strip().lower()
            try:
                validate_tag(t)
            except VineError:
                dropped += 1
                continue
            key = tag_key(t)
            if key in seen:
                continue
            if len(out) >= MAX_TAGS:
                dropped += 1
                continue
            seen.add(key)
            out.append(t)
        return out, dropped

    @staticmethod
    def _clean_tags(tags) -> list[str]:
        """The kept tags alone, for callers that re-derive them outside a
        curation run (the Station's compose review, J.8.1, which re-cleans
        a draft that went to a browser and came back)."""
        return Curator.clean_tags(tags)[0]


def make_candidates(vine, limit: int = CANDIDATE_LIMIT) -> Callable[[str], list[dict]]:
    """G.4.2.1 candidate provider: BM25 over curated metadata (C.6.1).
    Branches are excluded — a link to a folder carries no scent."""

    def candidates(query: str) -> list[dict]:
        out: list[dict] = []
        for row in vine.catalog.fts_search(query, limit=limit * 3):
            if row["type"] == "branch":
                continue
            out.append({"id": row["id"], "title": row["title"],
                        "summary": row["summary"]})
            if len(out) >= limit:
                break
        return out

    return candidates


def make_chat() -> tuple[Callable[[list[dict]], str], str]:
    """Minimal OpenAI-compatible client from the environment:
    MONKEYLLM_LLM_ENDPOINT (required), _MODEL, _API_KEY, _MAX_TOKENS."""
    import httpx

    endpoint = os.environ.get("MONKEYLLM_LLM_ENDPOINT")
    if not endpoint:
        raise VineError(
            E_SCHEMA,
            "curation needs MONKEYLLM_LLM_ENDPOINT (an OpenAI-compatible /v1)",
            hint="e.g. set MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1",
        )
    model = os.environ.get("MONKEYLLM_LLM_MODEL", "local")
    api_key = os.environ.get("MONKEYLLM_LLM_API_KEY", "no-key")
    max_tokens = int(os.environ.get("MONKEYLLM_LLM_MAX_TOKENS", "300"))
    # thinking off unless MONKEYLLM_LLM_REASONING=on (OpenRouter normalizes
    # the `reasoning` param across providers); when on, add room for the
    # thinking tokens or the final content comes back empty/truncated
    reasoning_on = os.environ.get("MONKEYLLM_LLM_REASONING", "off").lower() == "on"
    if reasoning_on:
        max_tokens += 1000
    client = httpx.Client(base_url=endpoint.rstrip("/"),
                          headers={"Authorization": f"Bearer {api_key}"},
                          timeout=180.0)
    if model == "local":
        try:  # single-model servers report what they actually serve
            served = client.get("/models").json().get("data") or []
            if served:
                model = served[0]["id"]
        except Exception:
            pass

    def chat(messages: list[dict]) -> str:
        payload = {"model": model, "messages": messages,
                   "max_tokens": max_tokens, "temperature": 0.1}
        if "openrouter" in endpoint and not reasoning_on:
            payload["reasoning"] = {"enabled": False}
        resp = client.post("/chat/completions", json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM endpoint {resp.status_code}: {resp.text[:300]}")
        return resp.json()["choices"][0]["message"].get("content") or ""

    return chat, model
