"""G.4.2 — the Gardener's LLM curation stage (spec v0.9; edge proposals
G.4.2.1, spec v0.12).

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
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable

from monkeyllm.errors import E_SCHEMA, VineError
from monkeyllm.models import validate_summary
from monkeyllm.tokens import estimate_tokens

MAX_ATTEMPTS = 3
CONTENT_BUDGET_TOKENS = 1500  # how much of the body the model sees
MAX_TAGS = 5
# G.4.2.1 edge proposals
MAX_PROPOSALS = 3
PROPOSAL_CONFIDENCE = 0.3   # the C.8 ladder's bottom rung — Part H's scope
CANDIDATE_LIMIT = 8
NOTE_MAX_CHARS = 120
REPLY_KEPT_CHARS = 400  # enough of a rejected reply to see what went wrong

SYSTEM_PROMPT = """\
You write frontmatter summaries for nodes of a knowledge forest. An agent
will decide from the summary alone whether the node matters — the summary
is the SCENT. Rules (normative, spec A.4):
- 1 to 3 sentences, at most 60 tokens total. Shorter is better.
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
- Also propose up to {max_tags} tags: lowercase, single words, no accents.
{directives}
Reply with ONE JSON object only, no prose around it:
{{"summary": "...", "tags": ["...", "..."]}}"""

RETRY_PROMPT = ("Your previous summary was rejected: {error}. "
                "Rewrite it following the rules strictly. JSON only.")

BRANCH_PROMPT = """\
You summarize a REGION (branch) of a knowledge forest. Below are the entry
lines of its children — sub-branches and notes, each already summarized.
Write the branch's summary: the SCENT an agent reads to decide whether to
descend here. Rules (normative, spec A.4/A.5):
- 1 to 3 sentences, at most 60 tokens total. Shorter is better.
- Say WHAT lives here: themes, concrete names, time scope visible in the
  entries. Synthesize the region — do not enumerate every child.
- If the entries make it visible, add where to go for what is NOT here.
- NEVER start with boilerplate like "This folder contains" or "This branch
  groups" — go straight to the substance.
- Write in the SAME LANGUAGE as the entries.
Reply with ONE JSON object only, no prose around it:
{"summary": "..."}"""

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

_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _clip(text: str, budget: int = CONTENT_BUDGET_TOKENS) -> str:
    words = text.split()
    while words and estimate_tokens(" ".join(words)) > budget:
        del words[max(1, len(words) * 3 // 4):]
    return " ".join(words)


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


class Curator:
    """An `on_curate` hook (G.4.3) that fills summaries via the LLM (G.4.2)."""

    def __init__(self, chat: Callable[[list[dict]], str], directives: str = "",
                 candidates: Callable[[str], list[dict]] | None = None):
        self.chat = chat
        self.candidates = candidates  # G.4.2.1 provider; None = no proposals
        directives_block = (
            f"Operator directives (apply them):\n{directives.strip()}\n"
            if directives.strip() else ""
        )
        self.system = SYSTEM_PROMPT.format(max_tags=MAX_TAGS,
                                           directives=directives_block)
        self.stats = {"llm_summaries": 0, "fallbacks": 0, "retries": 0,
                      "links_proposed": 0, "proposal_fallbacks": 0,
                      "branch_rollups": 0, "branch_fallbacks": 0,
                      "transport_errors": 0, "rejected": 0}
        # Two different silences, and they need two different fixes.
        # `last_error`: the endpoint never answered (key, URL, model name).
        # `last_reject` + `last_reply`: it answered, and the answer failed
        # the A.4 contract every time — which is a prompt, budget or model
        # problem, not a connectivity one.
        self.last_error: str | None = None
        self.last_reject: str | None = None
        self.last_reply: str | None = None

    def __call__(self, draft: dict) -> dict:
        body = draft.get("body")
        if not body or draft.get("type") == "dataset":
            return draft  # datasets keep their factual template summary
        result = self._ask(draft.get("title", ""), body)
        if result is not None:
            summary, tags = result
            self.stats["llm_summaries"] += 1
            draft["summary"] = summary
            merged = list(draft.get("tags") or [])
            for tag in tags:
                if tag not in merged:
                    merged.append(tag)
            draft["tags"] = merged
        else:
            self.stats["fallbacks"] += 1  # the derived summary stays in place
        if self.candidates is not None:
            self._propose(draft)
        return draft

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

    def branch_summary(self, title: str, entry_lines: list[str]) -> str | None:
        """Synthesize a branch summary from its children's entry lines
        (G.4.4). Returns None on failure — the caller falls back."""
        entries = _clip_lines(entry_lines)
        if not entries:
            self.stats["branch_fallbacks"] += 1
            return None
        messages = [
            {"role": "system", "content": BRANCH_PROMPT},
            {"role": "user", "content": f"Branch: {title}\n\nChildren:\n{entries}"},
        ]
        result = self._validated(messages)
        if result is None:
            self.stats["branch_fallbacks"] += 1
            return None
        self.stats["branch_rollups"] += 1
        return result[0]

    def _ask(self, title: str, body: str) -> tuple[str, list[str]] | None:
        messages = [
            {"role": "system", "content": self.system},
            {"role": "user", "content": f"Title: {title}\n\nContent:\n{_clip(body)}"},
        ]
        return self._validated(messages)

    def _validated(self, messages: list[dict]) -> tuple[str, list[str]] | None:
        """Validate-and-retry loop shared by banana (_ask) and branch
        (branch_summary) summaries."""
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
                obj = _extract_json(reply)
                summary = (obj or {}).get("summary", "")
                if not isinstance(summary, str) or not summary.strip():
                    error = "no summary found in the JSON reply"
                else:
                    try:
                        validate_summary(summary.strip())
                    except VineError as e:
                        error = e.message
            if error is None:
                # The last rejection is NOT cleared here: a batch where the
                # last document happened to succeed still owes the operator
                # an example of the ones that did not.
                return summary.strip(), self._clean_tags((obj or {}).get("tags"))
            self.stats["retries"] += 1
            # Kept, not just counted. "The model answered and I threw all of
            # it away" is the state an operator cannot debug: the rejection
            # reason names the rule, the reply shows what broke it.
            self.last_reject = error
            self.last_reply = reply.strip()[:REPLY_KEPT_CHARS]
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user",
                             "content": RETRY_PROMPT.format(error=error)})
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

    @staticmethod
    def _clean_tags(tags) -> list[str]:
        out: list[str] = []
        for tag in tags if isinstance(tags, list) else []:
            t = str(tag).strip().lower()
            if _TAG_RE.match(t) and t not in out:
                out.append(t)
            if len(out) >= MAX_TAGS:
                break
        return out


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
