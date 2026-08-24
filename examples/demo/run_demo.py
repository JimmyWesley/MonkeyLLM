# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""Phase 0 demo (Part F criterion 5): an LLM navigates the forest with the
Vine primitives only, answering multi-hop questions with traces + metrics.

The model and endpoint are configurable; provider resolution order:

  1. MONKEYLLM_LLM_ENDPOINT set        -> that OpenAI-compatible endpoint
                                          (llama.cpp local, vLLM, LM Studio...)
  2. OPENROUTER_API_KEY set            -> OpenRouter (online, no local GPU)
  3. otherwise                         -> Hugging Face serverless (HF_TOKEN)

    MONKEYLLM_LLM_MODEL       model id (defaults per provider)
    MONKEYLLM_LLM_API_KEY     key for custom endpoints (default: no-key)
    MONKEYLLM_LLM_MAX_TOKENS  completion budget (default 1500; sized for the
                              `answer` action, not for a tool call. Raise
                              further for reasoning models)

Examples:
    # Local llama.cpp (scripts/serve_llm.py)
    set MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1
    set MONKEYLLM_LLM_MODEL=gemma-4
    python examples/demo/run_demo.py

    # Online via OpenRouter (no local GPU needed)
    set OPENROUTER_API_KEY=sk-or-...
    set MONKEYLLM_LLM_MODEL=google/gemma-4-12b-it
    python examples/demo/run_demo.py --questions examples/demo/questions.json

Optional Phase 1 vector layer: if MONKEYLLM_EMBED_ENDPOINT is set and the
canopy is built (`vine canopy build`), locate runs hybrid (RRF vector+BM25)
instead of BM25-only — the rest of the demo is identical.

Each question runs in its own Vine session; traces land in
<forest>/_derived/traces/<session>.jsonl and the report prints
hops-to-banana, tokens-to-banana and banana precision.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from monkeyllm import Vine, VineError  # noqa: E402

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_STEPS = 14

# Confidence gate (v0.12 demo policy): the answer action carries a self-reported
# confidence, the harness audits grounding from session state, and the effective
# confidence is min(reported, audited) — the model cannot talk its way up, only
# harvesting can. Low-confidence answers are rejected while budget remains; from
# RELOCATE_AFTER rejections on, the monkey is relocated to unexplored branches.
CONF_ACCEPT = 0.7      # effective confidence needed to accept an answer mid-run
MAX_REJECTIONS = 3     # bounced answers per session (each refunds its step)
RELOCATE_AFTER = 2     # from this rejection on, suggest unexplored branches


def step_budget(q: dict) -> int:
    """Width-aware step budget. MAX_STEPS was calibrated on single-chain
    questions (v1-v3); a fork question does `fork_width` x the navigation
    work BY DEFINITION, so a fixed budget conflates "cannot navigate" with
    "ran out of steps". +3 steps per extra declared sub-chain keeps the
    per-chain budget constant. (The troop needs no scaling: each sub-hunt
    already gets a full MAX_STEPS for its one chain — this restores the
    same per-chain parity for the solo monkey.)"""
    return MAX_STEPS + 3 * (int(q.get("fork_width", 1)) - 1)

SYSTEM_PROMPT = """You are a navigator monkey in a knowledge forest. Answer the question \
using ONLY the tools below. Never invent facts: navigate, harvest and answer.

Tools (always respond with a SINGLE JSON object, nothing else):
- {"tool": "locate", "args": {"query": "...", "k": 5}}  -> entry points (the helicopter)
- {"tool": "sniff", "args": {"terms": ["..."], "scope": null}} -> literal grep on BODIES: exact term
  (code, name, number) -> node + section + snippet. optional scope restricts to a branch or node.
- {"tool": "look", "args": {"id": "..."}}               -> cheap digest of a node (summary, neighbors, outline)
- {"tool": "move", "args": {"id": "...", "rel": null}}  -> neighbors of a node (rel "children" lists branch children)
- {"tool": "pick", "args": {"id": "...", "section": null}} -> full body (only when summary confirms the target)
- {"tool": "query", "args": {"id": "...", "sql": "SELECT ..."}} -> read-only SQL on type:dataset nodes
- {"tool": "scan", "args": {"parent_id": "...", "filter": {}}}  -> filter children by metadata
- {"tool": "answer", "args": {"text": "...", "answer_nodes": ["full/id"], "confidence": 0.9, "proof": "sentence copied EXACTLY from a tool result"}} -> final answer

Strategy: does the question have an EXACT rare term (code, proper name, number)? sniff first — it
lands directly in the right section and you harvest with pick(id, section). Conceptual question? locate
first; look to sniff around; pick/query only on the target. sniff returned too many? restrict with scope.
Question about ALL members of a set ("which of the...", "who among...", "which ... did NOT...")?
ENUMERATE, never sample: move(branch, rel "children") to list every member, then look each one —
a negative or a complete list is only provable after visiting the whole set. Save tokens.
Important rules:
- If a response has "truncated": true, the list was CUT by budget: do not conclude something does
  not exist — refine with locate (more specific terms) or scan(parent_id, filter).
- Repeating the SAME call with the SAME arguments returns the same result; change tool or terms.
- type:dataset nodes respond via SQL: read the manual in look and use query (aggregates are not in text).
- answer rules: answer_nodes = exact full ids from tool results, only nodes you opened (look/pick/query)
  or sniff hit. proof = ONE sentence copied verbatim from a tool result that states the answer; text
  must repeat EVERY number in proof. confidence: 0.9 proof states the answer, 0.5 partial, 0.2 guess.
  A low-confidence answer is rejected with a fix — do the fix, then answer again.
- totals/highest/sums exist ONLY via query on the dataset node (the SQL is in its Query manual).
The forest map (master index) is in the first user message."""

# Pre-sniff prompt (spec v0.1), kept VERBATIM for the A/B baseline arm
# (--no-sniff): measures the sniff gain against the 6-tool monkey.
SYSTEM_PROMPT_BASELINE = """You are a navigator monkey in a knowledge forest. Answer the question \
using ONLY the tools below. Never invent facts: navigate, harvest and answer.

Tools (always respond with a SINGLE JSON object, nothing else):
- {"tool": "locate", "args": {"query": "...", "k": 5}}  -> entry points (the helicopter)
- {"tool": "look", "args": {"id": "..."}}               -> cheap digest of a node (summary, neighbors, outline)
- {"tool": "move", "args": {"id": "...", "rel": null}}  -> neighbors of a node (rel "children" lists branch children)
- {"tool": "pick", "args": {"id": "...", "section": null}} -> full body (only when summary confirms the target)
- {"tool": "query", "args": {"id": "...", "sql": "SELECT ..."}} -> read-only SQL on type:dataset nodes
- {"tool": "scan", "args": {"parent_id": "...", "filter": {}}}  -> filter children by metadata
- {"tool": "answer", "args": {"text": "...", "answer_nodes": ["id1", "id2"]}} -> final answer

Strategy: locate first; look to sniff around; pick/query only on the target. Save tokens.
Important rules:
- If a response has "truncated": true, the list was CUT by budget: do not conclude something does
  not exist — refine with locate (more specific terms) or scan(parent_id, filter).
- Repeating the SAME call with the SAME arguments returns the same result; change tool or terms.
- type:dataset nodes respond via SQL: read the manual in look and use query (aggregates are not in text).
The forest map (master index) is in the first user message."""


# Deadline synthesis: a hunt that ends without an answer wastes every token
# it spent. When the step budget runs out, force ONE closing call — the
# evidence (sniff snippets, picked bodies) is already in the context.
FORCED_ANSWER_MSG = (
    "Step budget exhausted. Do NOT call more tools. Based ONLY on what you have "
    "already seen above (sniff snippets, picked bodies, query rows, locate summaries), "
    'answer now with {"tool": "answer", "args": {"text": "...", "answer_nodes": ["..."], '
    '"confidence": 0.5, "proof": "sentence copied from a result above"}}. '
    "If evidence appeared in a snippet, copy it literally. Keep text under 2 sentences."
)

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"
# Qwen 3.5 35B-A3B (MoE, ~3B active params: fast and cheap). Append ":free"
# for the gratis tier (rate-limited ~20 req/min; the client retries on 429).
OPENROUTER_DEFAULT_MODEL = "qwen/qwen3.5-35b-a3b"
RETRY_STATUS = {429, 500, 502, 503}  # rate limits / transient upstream errors


def resolve_provider() -> tuple[str | None, str, str]:
    """(endpoint, model, api_key) per the resolution order in the docstring."""
    model = os.environ.get("MONKEYLLM_LLM_MODEL")
    endpoint = os.environ.get("MONKEYLLM_LLM_ENDPOINT")
    api_key = os.environ.get("MONKEYLLM_LLM_API_KEY") or os.environ.get("HF_TOKEN") or "no-key"
    if not endpoint and os.environ.get("OPENROUTER_API_KEY"):
        endpoint = OPENROUTER_ENDPOINT
        api_key = os.environ["OPENROUTER_API_KEY"]
        model = model or OPENROUTER_DEFAULT_MODEL
    return endpoint, model or DEFAULT_MODEL, api_key


def make_llm():
    endpoint, model, api_key = resolve_provider()
    # The `answer` action is the longest single emission in the protocol —
    # text + answer_nodes + confidence + a `proof` copied VERBATIM from a tool
    # result — so the budget is sized for IT and not for a tool call. Measured
    # at 600 on the 18-question suite: two questions were cut mid-object after
    # the model had already run the right query and reached the right node,
    # and both scored as wrong ANSWERS rather than as truncation, which is the
    # treacherous part. Reasoning models still need room on top of this.
    max_tokens = int(os.environ.get("MONKEYLLM_LLM_MAX_TOKENS", "1500"))

    if endpoint:  # any OpenAI-compatible server: llama.cpp, OpenRouter, vLLM...
        import time as _t

        import httpx

        headers = {"Authorization": f"Bearer {api_key}"}
        if "openrouter" in endpoint:
            headers["HTTP-Referer"] = "https://monkeyllm.com"
            headers["X-Title"] = "MonkeyLLM"
        client = httpx.Client(base_url=endpoint.rstrip("/"), headers=headers, timeout=180.0)

        if model == DEFAULT_MODEL and "openrouter" not in endpoint:
            # Single-model servers (llama.cpp) ignore the request's `model`
            # field, so the placeholder default would be reported as if it ran.
            # Ask the endpoint what it actually serves.
            try:
                served = client.get("/models").json().get("data") or []
                if served:
                    model = served[0]["id"]
            except Exception:
                pass  # endpoint without /models: keep the placeholder name

        # lean by default (same policy as the local server): thinking off
        # unless MONKEYLLM_LLM_REASONING=on. OpenRouter normalizes the
        # `reasoning` param across providers.
        reasoning_on = os.environ.get("MONKEYLLM_LLM_REASONING", "off").lower() == "on"
        if reasoning_on:  # give the thinking tokens room beyond the content budget
            max_tokens += 1000

        # 0.1 keeps big instruct models deterministic. Small hybrid reasoners
        # (MiniCPM5 1B etc.) are sometimes shipped with a high default sampling
        # temperature for open-ended chat/thinking, but for THIS harness — a
        # strict single-JSON-object-per-turn tool loop — that same high
        # temperature causes wide run-to-run swings (observed 40-90% on a
        # 10-question suite at 0.6 vs a stable 70-80% at 0.2-0.3). Keep it low
        # for agentic tool use; raise it only if a specific model demonstrably
        # needs more sampling entropy to escape repetitive search loops.
        temperature = float(os.environ.get("MONKEYLLM_LLM_TEMPERATURE", "0.1"))
        top_p = float(os.environ.get("MONKEYLLM_LLM_TOP_P", "1.0"))

        def chat(messages: list[dict]) -> str:
            payload = {"model": model, "messages": messages,
                       "max_tokens": max_tokens, "temperature": temperature,
                       "top_p": top_p}
            if "openrouter" in endpoint and not reasoning_on:
                payload["reasoning"] = {"enabled": False}
            for attempt in range(4):
                resp = client.post("/chat/completions", json=payload)
                if resp.status_code in RETRY_STATUS and attempt < 3:
                    _t.sleep(2 ** (attempt + 1))  # 2s, 4s, 8s
                    continue
                if resp.status_code >= 400:
                    # surface the provider's own message (model id errado, etc.)
                    raise RuntimeError(f"LLM endpoint {resp.status_code}: {resp.text[:400]}")
                return resp.json()["choices"][0]["message"].get("content") or ""
            raise RuntimeError("unreachable")

        return chat, model

    # no endpoint: Hugging Face serverless
    from huggingface_hub import InferenceClient

    hf = InferenceClient(token=api_key if api_key != "no-key" else None)

    def chat(messages: list[dict]) -> str:
        resp = hf.chat_completion(messages=messages, model=model, max_tokens=max_tokens, temperature=0.1)
        return resp.choices[0].message.content or ""

    return chat, model


def parse_action(text: str) -> dict | None:
    """Extract the first JSON object from the model output."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    for candidate in (m.group(0), text):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "tool" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


SEARCH_TOOLS = {"locate", "sniff"}
OPEN_TOOLS = {"look", "pick", "query"}
_STOPWORDS = {"the", "a", "an", "of", "in", "on", "for", "and", "or", "to", "with",
              "was", "is", "are", "what", "which", "who", "how", "many", "much",
              "did", "does", "do", "by", "from"}
_NUM_RE = re.compile(r"\d[\d.,:/]*")
_NEG_CLAIM_RE = re.compile(
    r"\b(?:not|no|never|cannot|can't|doesn't|don't|unable)\b"
    r".{0,60}?\b(?:available|provided?|included?|present|specified|contains?|"
    r"exists?|found|determine|in the (?:data|dataset))", re.I | re.S)


def _norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _number_tokens(s: str) -> list[str]:
    return [t for t in _NUM_RE.findall(s or "") if sum(c.isdigit() for c in t) >= 2]


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _call_key(tool: str, args: dict) -> str:
    """Visited-cache key. Search calls are normalized (lowercase, sorted terms,
    stopword-free) so re-phrased near-duplicates collide with the repeat hint
    instead of silently burning budget (the locate spiral of q02/q04/q06)."""
    if tool == "locate":
        terms = sorted(set(re.findall(r"[a-z0-9]+", str(args.get("query", "")).lower())) - _STOPWORDS)
        return "locate:" + " ".join(terms)
    if tool == "sniff":
        terms = sorted(str(t).lower() for t in (args.get("terms") or []))
        return f"sniff:{' '.join(terms)}:{args.get('scope')}"
    return f"{tool}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"


def _collect_ids(obj, out: dict) -> None:
    """Every node id (+type when adjacent) present in a tool result."""
    if isinstance(obj, dict):
        if isinstance(obj.get("id"), str):
            out.setdefault(obj["id"], obj.get("type"))
        for v in obj.values():
            _collect_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_ids(v, out)


def _top_hit(result) -> str | None:
    hits = _hit_ids(result)
    return hits[0] if hits else None


def _hit_ids(result) -> list[str]:
    """Ordered ids of the actual hits (never edge targets or trail entries)."""
    ids: list[str] = []
    if isinstance(result, dict):
        for key in ("results", "hits", "matches"):
            for h in result.get(key) or []:
                if isinstance(h, dict) and isinstance(h.get("id"), str):
                    ids.append(h["id"])
    return ids


_ID_SHAPE_RE = re.compile(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)+")


def _clean_node_id(s: str) -> str:
    """Rescue an id from a garbled answer_nodes entry ("{id: 'a/b', ..." -> "a/b")."""
    s = str(s).strip()
    m = _ID_SHAPE_RE.search(s)
    return m.group(0) if m and not re.fullmatch(r"[A-Za-z0-9_./-]+", s) else s


def _extract_answer_fields(raw: str) -> tuple[str | None, list[str]]:
    """Salvage text/answer_nodes from a malformed or truncated answer JSON."""
    text = None
    m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)', raw)
    if m:
        try:
            text = json.loads('"' + m.group(1).rstrip("\\") + '"')
        except json.JSONDecodeError:
            text = m.group(1)
    nodes: list[str] = []
    mn = re.search(r'"answer_nodes"\s*:\s*\[([^\]]*)', raw)
    if mn:
        nodes = re.findall(r'"([^"]+)"', mn.group(1))
    return (text.strip() or None) if text else None, nodes


def _audit_answer(nodes: list, text: str, proof: str, ground: dict,
                  skip: set) -> tuple[float, str, str]:
    """Harness-side grounding score for an answer: (score, code, fix-hint).
    Checked most-severe first; `skip` holds soft codes already bounced once
    (paraphrase/derived-figure false positives get one bounce, never a loop)."""
    if not nodes:
        return 0.0, "no_nodes", ("answer_nodes is empty. Cite the exact full ids of "
                                 "the nodes that contain your facts (open them first).")
    unknown = [n for n in nodes if n not in ground["seen_ids"] and not ground["exists"](n)]
    if unknown:
        return 0.0, "bad_ids", (f'unknown node id "{unknown[0]}" — use the exact full '
                                "id as returned by the tools (never shorten it).")
    unqueried = [n for n in nodes
                 if ground["seen_ids"].get(n) == "dataset" and n not in ground["queried"]]
    if unqueried:
        return 0.2, "dataset", (f"you cite the dataset {unqueried[0]} but never ran query on it. "
                                "Aggregates are not in text: look shows its Query manual, then "
                                f'{{"tool": "query", "args": {{"id": "{unqueried[0]}", "sql": "..."}}}}.')
    if _NEG_CLAIM_RE.search(text):
        ds = [i for i, t in ground["seen_ids"].items()
              if t == "dataset" and i not in ground["queried"]]
        if ds:
            return 0.2, "negative", (f"you claim data is unavailable but never ran query on {ds[0]} "
                                     "— run the SQL from its Query manual first.")
    unharvested = [n for n in nodes if n not in ground["harvested"]]
    if unharvested and "unharvested" not in skip:
        return 0.3, "unharvested", (f"you cite {unharvested[0]} without having opened it: "
                                    f'{{"tool": "pick", "args": {{"id": "{unharvested[0]}"}}}} '
                                    "to confirm the fact, then answer again.")
    if "numbers" not in skip:
        missing = [t for t in _number_tokens(text)
                   if not any(b == _digits(t) or b.startswith(_digits(t))
                              for b in ground["nums"])]
        if missing:
            return 0.3, "numbers", (f'the number "{missing[0]}" never appeared in any tool result '
                                    "you saw. Open the node that states it, or correct the number.")
    if proof and "proof" not in skip and _norm_text(proof) not in ground["blob"]:
        return 0.5, "proof", ("proof must be ONE sentence copied EXACTLY from a tool "
                              "result you received — copy it verbatim.")
    if not proof and "no_proof" not in skip:
        return 0.6, "no_proof", ('add "proof": copy the exact sentence from a tool '
                                 "result that states your answer.")
    return 0.9, "ok", ""


def run_question(forest: Path, chat, q: dict, verbose: bool = True, embedder=None,
                 use_sniff: bool = True, learn: bool = False,
                 hybrid: bool = False) -> dict:
    vine = Vine(forest, writable=learn, session=f"demo-{q['id']}", embedder=embedder,
                hybrid_locate=hybrid)
    try:
        master = vine.look("_index")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT if use_sniff else SYSTEM_PROMPT_BASELINE},
            {
                "role": "user",
                "content": f"Forest master index:\n{json.dumps(master, ensure_ascii=False)}\n\nQuestion: {q['question']}",
            },
        ]
        answer, answer_nodes = None, []
        entry_id: str | None = None  # landing zone: first node the monkey touches
        visited: set[str] = set()  # visited-cache (spec E.1.3): identical calls are not re-run
        # grounding state for the confidence audit: everything the model saw
        seen_ids: dict[str, str | None] = {}
        _collect_ids(master, seen_ids)
        ground = {
            "seen_ids": seen_ids,
            "harvested": set(),  # ids opened via look/pick/query, or hit by sniff
            "queried": set(),    # dataset ids that answered a query
            "nums": {_digits(t) for t in _number_tokens(json.dumps(master, default=str))},
            "blob": _norm_text(json.dumps(master, ensure_ascii=False, default=str)),
            "exists": vine.forest.exists,
        }
        branches = sorted(i for i, t in seen_ids.items()
                          if (t == "branch" or "/" not in i) and i != "_index")
        rejections, bounced, confidence = 0, set(), None
        last_top: str | None = None
        consec_search = 0
        # stall ladder: a 1B ignores textual hints, so on repeated stalls the
        # harness ACTS — it opens the next unopened hit itself (auto-look)
        stall, auto_opens = 0, 0
        pending_hits: list[str] = []  # unopened hit ids, accumulated across searches
        node_text: dict[str, str] = {}  # nid -> normalized evidence the model saw from it
        node_nums: dict[str, set] = {}  # nid -> digit tokens seen in its evidence
        max_steps = step_budget(q)
        turn, deadline_sent = 0, False

        def absorb(nid: str | None, payload, global_too: bool = True) -> None:
            """Register a tool result as seen evidence (global + per-node)."""
            _collect_ids(payload, seen_ids)
            blob = json.dumps(payload, ensure_ascii=False, default=str)
            norm = _norm_text(blob)
            nums = {_digits(t) for t in _number_tokens(blob)}
            if global_too:
                ground["blob"] += " " + norm
                ground["nums"].update(nums)
            if nid:
                node_text[nid] = node_text.get(nid, "") + " " + norm
                node_nums.setdefault(nid, set()).update(nums)

        def open_digest(nid: str):
            """look(nid) + full evidence bookkeeping; None when not openable."""
            if nid in ground["harvested"] or nid == "_index":
                return None
            try:
                d = vine.look(nid)
            except VineError:
                return None
            ground["harvested"].add(nid)
            absorb(nid, d)
            return d

        def auto_open_next():
            while pending_hits:
                d = open_digest(pending_hits.pop(0))
                if d is not None:
                    return d
            return None

        def attribute_nodes(text: str, proof: str) -> list[str]:
            """When the model forgets answer_nodes, find which harvested nodes
            actually back its proof/numbers instead of bouncing it (q04 died
            re-sending the same uncited answer three times)."""
            p = _norm_text(proof)
            cands = [i for i, t in node_text.items() if p and p in t]
            if not cands:
                nums = {_digits(t) for t in _number_tokens(text)}
                scored = sorted(((len(nums & ns), i) for i, ns in node_nums.items()
                                 if nums & ns), reverse=True)
                cands = [i for _, i in scored[:2]]
            return cands[:2]
        while (turn - rejections) < max_steps:  # a rejected answer refunds its step
            remaining = max_steps - (turn - rejections)
            if remaining == 2 and not deadline_sent:
                deadline_sent = True
                messages.append({"role": "user", "content": json.dumps(
                    {"deadline": "2 steps left — harvest the last missing fact or answer NOW"})})
            turn += 1
            reply = chat(messages)
            messages.append({"role": "assistant", "content": reply})
            action = parse_action(reply)
            if action is None:
                stall += 1
                messages.append({"role": "user", "content": 'Invalid format. Respond only with the JSON {"tool": ..., "args": ...}.'})
                continue
            tool, args = action.get("tool"), action.get("args") or {}
            if verbose:
                print(f"    [{turn}] {tool}({json.dumps(args, ensure_ascii=False)[:110]})")
            if tool == "answer":
                text = str(args.get("text", "")).strip()
                proof = str(args.get("proof") or "").strip()
                nodes = [_clean_node_id(n) for n in (args.get("answer_nodes") or [])]
                # auto-repair shortened ids (basename only, e.g. "leaf" -> "branch/leaf")
                for i, n in enumerate(nodes):
                    if n not in seen_ids and not vine.forest.exists(n):
                        cand = [s for s in seen_ids if s.split("/")[-1] == n]
                        if len(cand) == 1:
                            nodes[i] = cand[0]
                if not nodes:  # cite for it instead of bouncing (q04 never self-fixed)
                    nodes = attribute_nodes(text, proof)
                try:
                    reported = max(0.0, min(1.0, float(args.get("confidence"))))
                except (TypeError, ValueError):
                    reported = None
                audit, code, hint = _audit_answer(nodes, text, proof, ground, bounced)
                eff = audit if reported is None else min(reported, audit)
                if eff >= CONF_ACCEPT or rejections >= MAX_REJECTIONS or remaining <= 1:
                    if proof and _norm_text(proof) in ground["blob"] \
                            and _norm_text(proof) not in _norm_text(text):
                        # append the verified quote: the deliverable carries the
                        # forest's own words, immune to 1B paraphrase token loss
                        text += f' [evidence: "{proof}"]'
                    answer, answer_nodes, confidence = text, nodes, round(eff, 2)
                    break
                rejections += 1
                if code in ("unharvested", "numbers", "proof", "no_proof"):
                    bounced.add(code)  # soft checks bounce once, never loop
                rej = {"answer_rejected": True, "confidence": round(eff, 2),
                       "fix": hint or ("your own confidence is low: verify the fact "
                                       "(pick the node) or hunt in another area.")}
                explored = {h.split("/")[0] for h in ground["harvested"]}
                unexplored = [b for b in branches if b not in explored][:3]
                if rejections >= RELOCATE_AFTER and unexplored:
                    rej["relocate"] = {
                        "unexplored_branches": unexplored,
                        "hint": ("the fact may live in another area: locate with NEW "
                                 "terms or move() into one of these branches")}
                if verbose:
                    print(f"    [reject] confidence={rej['confidence']} ({code}) "
                          f"rejections={rejections}")
                messages.append({"role": "user",
                                 "content": json.dumps(rej, ensure_ascii=False)})
                continue
            if entry_id is None and tool in ("look", "move", "pick", "query", "scan"):
                entry_id = args.get("id") or args.get("parent_id")
            call_key = _call_key(tool, args)
            if call_key in visited:
                stall += 1
                if stall >= 2 and auto_opens < 3:
                    digest = auto_open_next()
                    if digest is not None:
                        auto_opens += 1
                        payload = {"auto_opened": digest.get("id"),
                                   "note": ("you were stuck repeating searches, so the "
                                            "harness opened this node for you"),
                                   "digest": digest}
                        if digest.get("type") == "dataset":
                            payload["hint"] = ("this is a dataset: totals/aggregates exist "
                                               "ONLY via query — copy the SQL from its Query manual.")
                        if verbose:
                            print(f"    [auto] opened {digest.get('id')} (stall rescue)")
                        messages.append({"role": "user", "content": json.dumps(
                            payload, ensure_ascii=False, default=str)})
                        stall = 0
                        continue
                    break  # stuck with nothing left to open: synthesize from context
                hint = ("Identical call to the previous one — the result would be the same. "
                        "Change the terms, the tool, or answer with what you already have.")
                if use_sniff:
                    hint += (' Hint: sniff({"terms": ["exact term"]}) searches the term '
                             "inside bodies and returns the right section.")
                messages.append({"role": "user", "content": json.dumps(
                    {"repeat": True, "hint": hint}, ensure_ascii=False)})
                continue
            visited.add(call_key)
            try:
                tools = {"locate": vine.locate, "look": vine.look, "move": vine.move,
                         "pick": vine.pick, "query": vine.query, "scan": vine.scan}
                if use_sniff:
                    tools["sniff"] = vine.sniff
                fn = tools.get(tool)
                if fn is None:
                    result = {"error": {"code": "E_SCHEMA", "message": f"unknown tool: {tool}"}}
                else:
                    result = fn(**args)
            except VineError as e:
                result = e.to_dict()
            except (TypeError, ValueError, AttributeError) as e:
                # model-fabricated args must never kill the hunt
                result = {"error": {"code": "E_SCHEMA", "message": str(e)}}
            # grounding bookkeeping + harness-side navigation nudges
            ok = isinstance(result, dict) and "error" not in result
            nid = args.get("id") or args.get("parent_id")
            absorb(nid if (ok and tool in OPEN_TOOLS) else None, result)
            stall = stall + 1 if not ok else 0  # errors stall too; progress resets
            if ok and tool in OPEN_TOOLS and nid:
                ground["harvested"].add(nid)
                if tool == "query":
                    ground["queried"].add(nid)
            if not ok and tool == "query":
                result["hint"] = ("only type:dataset nodes answer SQL — read text nodes "
                                  'with {"tool": "pick", "args": {"id": "..."}} instead.')
            if ok and tool == "sniff":
                for key in ("results", "hits", "matches"):
                    for h in result.get(key) or []:
                        if isinstance(h, dict) and isinstance(h.get("id"), str):
                            ground["harvested"].add(h["id"])  # the snippet was shown
                            absorb(h["id"], h, global_too=False)
            if ok and tool == "look" and result.get("type") == "dataset":
                result["hint"] = ("this is a dataset: totals/aggregates exist ONLY via "
                                  "query — copy the SQL from the Query manual above.")
            if ok and tool in SEARCH_TOOLS:
                hit_list = _hit_ids(result)
                pending_hits.extend(i for i in hit_list
                                    if i not in pending_hits and i not in ground["harvested"])
                if tool == "locate":
                    # eager harvest: the helicopter drops the monkey AT the tree —
                    # top hits come back already opened (a 1B ignores "go look"
                    # hints, but reads evidence placed inside the result), and the
                    # top hit also brings its full body: a local SLM drinks tokens
                    # cheaply, so feed it the flesh, not just the scent
                    digests = [d for d in (open_digest(h) for h in hit_list[:2]) if d]
                    if digests:
                        try:
                            body = vine.pick(digests[0]["id"])
                            absorb(digests[0]["id"], body)
                            digests[0]["body"] = body.get("body")
                        except (VineError, KeyError):
                            pass
                        result["digests"] = digests
                        result["digests_note"] = ("the top hits are already opened above: "
                                                  "answer from these digests citing their ids, "
                                                  "or go deeper with pick/query")
                        if verbose:
                            print(f"    [digest] {', '.join(d.get('id', '?') for d in digests)}")
                top = _top_hit(result)
                consec_search += 1
                if top and top == last_top and consec_search >= 2:
                    result["hint"] = ('the digests above may already contain the answer — reply '
                                      'with {"tool": "answer", ...} citing those ids, or query '
                                      "the dataset using its query_manual.")
                if consec_search >= 3 and auto_opens < 3:
                    # new-but-useless searches evade the visited cache (q06 pasted
                    # result summaries as queries); rescue here too
                    digest = auto_open_next()
                    if digest is not None:
                        auto_opens += 1
                        result["rescue_digest"] = digest
                        result["rescue_note"] = ("stop searching — the harness opened the "
                                                 "next unread hit for you; answer from it "
                                                 "or from the digests above")
                        if verbose:
                            print(f"    [auto] opened {digest.get('id')} (search-spiral rescue)")
                last_top = top or last_top
            elif ok:
                consec_search = 0
            messages.append({"role": "user", "content": json.dumps(result, ensure_ascii=False, default=str)})

        if answer is None:
            # forced synthesis is a short loop, not one shot (q06 died on a single
            # parse failure); the last resort salvages the raw reply — the evidence
            # is already in context and an unanswered hunt wastes every token spent.
            messages.append({"role": "user", "content": FORCED_ANSWER_MSG})
            forced_replies, forced_bounced = [], False
            for _attempt in range(3):
                raw = chat(messages)
                messages.append({"role": "assistant", "content": raw})
                forced_replies.append(raw)
                action = parse_action(raw)
                fargs = None
                if action and action.get("tool") == "answer":
                    fargs = action.get("args") or {}
                else:  # malformed/truncated JSON: salvage its text field
                    etext, enodes = _extract_answer_fields(raw)
                    if etext:
                        fargs = {"text": etext, "answer_nodes": enodes}
                if fargs is None:
                    messages.append({"role": "user", "content":
                                     'Output ONLY the JSON object — the first character of your reply must be "{".'})
                    continue
                text = str(fargs.get("text", "")).strip()
                proof = str(fargs.get("proof") or "").strip()
                nodes = [_clean_node_id(n) for n in (fargs.get("answer_nodes") or [])]
                for i, n in enumerate(nodes):
                    if n not in seen_ids and not vine.forest.exists(n):
                        cand = [s for s in seen_ids if s.split("/")[-1] == n]
                        if len(cand) == 1:
                            nodes[i] = cand[0]
                if not nodes:
                    nodes = attribute_nodes(text, proof)
                audit, code, hint = _audit_answer(
                    nodes, text, proof, ground, bounced | {"no_proof"})
                if audit <= 0.3 and not forced_bounced:
                    # one bounce even at the deadline: an ungrounded forced
                    # answer (invented number, unopened node) wastes the hunt
                    forced_bounced = True
                    messages.append({"role": "user", "content": json.dumps(
                        {"answer_rejected": True, "fix": hint,
                         "note": "fix it and answer again, same JSON format"},
                        ensure_ascii=False)})
                    continue
                if text and proof and _norm_text(proof) in ground["blob"] \
                        and _norm_text(proof) not in _norm_text(text):
                    text += f' [evidence: "{proof}"]'
                answer = text or None
                answer_nodes = nodes
                confidence = round(min(audit, 0.5), 2)
                if verbose and answer:
                    print("    [force] synthesis after exhausting steps")
                break
            if answer is None:
                for raw in reversed(forced_replies):  # last-resort text salvage
                    etext, enodes = _extract_answer_fields(raw)
                    if etext:
                        answer = etext
                        answer_nodes = [_clean_node_id(n) for n in enodes] or sorted(
                            n for n in ground["harvested"] if "/" in n)[:3]
                        confidence = 0.2
                        if verbose:
                            print("    [force] salvaged answer text from malformed reply")
                        break
            if answer is None and forced_replies:
                # absolute last resort: no reply ever contained a "text" field
                # (plain prose, JSON with a different key, or truncated mid-key)
                # — never return None, a hunt that answers nothing wastes every
                # token spent; use the raw reply itself as the answer text.
                answer = re.sub(r"\s+", " ", forced_replies[-1]).strip()[:400] or None
                answer_nodes = sorted(n for n in ground["harvested"] if "/" in n)[:3] \
                    or ([last_top] if last_top else [])
                confidence = 0.1
                if verbose and answer:
                    print("    [force] salvaged raw reply verbatim (no JSON text field found)")

        expected = set(q["expected_nodes"])
        harvested = set(answer_nodes)
        correct_text = answer is not None and all(
            s.lower() in answer.lower() for s in q["answer_contains"]
        )
        success = bool(answer) and bool(harvested & expected)
        outcome = vine.close_session(success, answer_nodes)

        # The shout (spec C.8 / Part D): close_session only SUGGESTS shortcuts;
        # acting on them is the orchestrator's call. With --learn we graft a
        # discovered-shortcut from the landing zone to each suggested banana —
        # graft's reinforce-before-create turns repeats into fortification.
        shortcuts = []
        if learn and entry_id:
            for nid in outcome.get("suggest_shortcuts", []):
                if nid == entry_id or not vine.forest.exists(nid):
                    continue
                try:
                    g = vine.graft(entry_id, {"add_links": [{"rel": "discovered-shortcut", "target": nid}]})
                    shortcuts.append({"from": entry_id, "to": nid,
                                      "fortified": bool(g["fortified"]), "commit": g["commit"]})
                except VineError as e:
                    shortcuts.append({"from": entry_id, "to": nid, "error": e.to_dict()["error"]["code"]})
        if verbose and shortcuts:
            for s in shortcuts:
                print(f"    SHOUT: shortcut {s['from']} -> {s['to']} "
                      f"({'fortified' if s.get('fortified') else s.get('error', 'planted')})")

        precision = (len(harvested & expected) / len(harvested)) if harvested else 0.0
        return {
            "id": q["id"],
            "question": q["question"],
            "answer": answer,
            "answer_nodes": answer_nodes,
            "expected_nodes": q["expected_nodes"],
            "correct_text": correct_text,
            "banana_precision": round(precision, 2),
            "confidence": confidence,
            "rejections": rejections,
            "metrics": outcome["metrics"],
            "shortcuts": shortcuts,
            "trace": str(vine.tracer.trace_path),
        }
    finally:
        vine.close()


def run_troop(forest: Path, chat, q: dict, troop: int, embedder=None,
              use_sniff: bool = True, learn: bool = False,
              hybrid: bool = False) -> dict:
    """Launch `troop` concurrent hunts for a single question; return the best result.

    Selection is confidence-first (self-reported x harness audit — no ground
    truth involved), tie-broken by fewer tokens; correct_text is printed for
    analysis only. All individual runs are stored in result["troop_runs"].
    """
    import concurrent.futures as _cf

    def hunt(monkey_idx: int) -> dict:
        return run_question(forest, chat, q, verbose=False, embedder=embedder,
                            use_sniff=use_sniff, learn=learn, hybrid=hybrid)

    with _cf.ThreadPoolExecutor(max_workers=troop) as pool:
        futures = [pool.submit(hunt, i) for i in range(troop)]
        runs = [f.result() for f in _cf.as_completed(futures)]

    # Selection: audited confidence first; among near-ties (two monkeys can
    # both get capped at the same low tier, e.g. "cited an unqueried dataset"),
    # break by cross-monkey agreement (self-consistency, ground-truth-free) —
    # a distractor is rarely reproduced independently by other monkeys, while
    # the real fact's ids/numbers tend to recur across hunts.
    top_conf = max((r.get("confidence") or 0.0) for r in runs)
    tied = [r for r in runs if (r.get("confidence") or 0.0) >= top_conf - 0.01]

    def _fingerprint(r: dict) -> set:
        nums = set(_number_tokens(str(r.get("answer") or "")))
        nodes = set(r.get("answer_nodes") or [])
        return {_digits(n) for n in nums} | nodes

    prints = {id(r): _fingerprint(r) for r in runs}

    def _agreement(r: dict) -> int:
        mine = prints[id(r)]
        return sum(1 for o in runs if o is not r and mine & prints[id(o)])

    if len(tied) > 1:
        best = max(tied, key=lambda r: (_agreement(r),
                                        -(r["metrics"]["tokens_to_banana"] or 10 ** 9)))
    else:
        best = tied[0]

    # print all runs so the user can see what each monkey did
    for i, r in enumerate(runs):
        m = r["metrics"]
        tag = "WINNER" if r is best else "      "
        print(f"    monkey-{i+1} [{tag}] conf={r.get('confidence')}  "
              f"precision={r['banana_precision']}  correct={r['correct_text']}  "
              f"hops={m['hops_to_banana']}  tokens={m['tokens_to_banana']}")
        print(f"             answer: {str(r['answer'])[:120]}")

    best["troop_runs"] = [
        {"monkey": i + 1, "answer": r["answer"], "confidence": r.get("confidence"),
         "answer_nodes": r["answer_nodes"], "correct_text": r["correct_text"],
         "banana_precision": r["banana_precision"], "metrics": r["metrics"]}
        for i, r in enumerate(runs)
    ]
    best["troop_size"] = troop
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forest", default=str(REPO / "forests" / "forest-fixture"))
    ap.add_argument("--questions", default=str(Path(__file__).parent / "questions.json"))
    ap.add_argument("--only", help="run a single question id (ex: q02)")
    ap.add_argument("--no-sniff", action="store_true",
                    help="baseline arm: hide the sniff tool (pre-v0.2 monkey) for A/B runs")
    ap.add_argument("--learn", action="store_true",
                    help="writable forest: graft suggested shortcuts (the shout) after each hunt")
    ap.add_argument("--troop", type=int, default=1, metavar="N",
                    help="run N monkeys per question in parallel and keep the best answer "
                         "(requires the llama-server to have been started with --parallel N)")
    ap.add_argument("--hybrid", action="store_true",
                    help="fuse vector search into locate (RRF) — needs an embedder "
                         "(MONKEYLLM_EMBED_ENDPOINT) and a built Canopy index; the "
                         "engine default is BM25-only (hybrid_locate=False)")
    ap.add_argument("--out", help="report path (default: <forest>/_derived/demo-report.json)")
    args = ap.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] == args.only]
    chat, model = make_llm()
    endpoint, _, _ = resolve_provider()
    print(f"model: {model}  endpoint: {endpoint or 'huggingface serverless'}")

    from monkeyllm.canopy import embedder_from_env

    embedder = embedder_from_env()
    if args.hybrid and embedder is None:
        raise SystemExit("--hybrid needs an embedder (set MONKEYLLM_EMBED_ENDPOINT).")
    if args.hybrid:
        locate_mode = "hybrid (vector+BM25; falls back to BM25 without a built Canopy index)"
    else:
        locate_mode = "BM25-only (pass --hybrid to fuse vectors)"
    print(f"locate: {locate_mode}")
    print(f"sniff: {'off (baseline)' if args.no_sniff else 'on'}")
    print(f"learn: {'on (shortcuts grafted via shout)' if args.learn else 'off'}")
    print(f"troop: {args.troop} monkey{'s' if args.troop > 1 else ''} per question")

    import time as _time

    results = []
    for q in questions:
        print(f"\n== {q['id']}: {q['question']}")
        t0 = _time.perf_counter()
        if args.troop > 1:
            r = run_troop(Path(args.forest), chat, q, troop=args.troop,
                          embedder=embedder, use_sniff=not args.no_sniff, learn=args.learn,
                          hybrid=args.hybrid)
        else:
            r = run_question(Path(args.forest), chat, q, embedder=embedder,
                             use_sniff=not args.no_sniff, learn=args.learn,
                             hybrid=args.hybrid)
        r["wall_s"] = round(_time.perf_counter() - t0, 1)
        results.append(r)
        m = r["metrics"]
        if args.troop <= 1:
            print(f"    answer: {str(r['answer'])[:160]}")
        print(
            f"    hops-to-banana={m['hops_to_banana']}  tokens-to-banana={m['tokens_to_banana']}  "
            f"precision={r['banana_precision']}  correct_text={r['correct_text']}  "
            f"conf={r.get('confidence')}  time={r['wall_s']}s"
        )

    ok = sum(1 for r in results if r["correct_text"])
    hops = [r["metrics"]["hops_to_banana"] for r in results if r["metrics"]["hops_to_banana"] is not None]
    toks = [r["metrics"]["tokens_to_banana"] for r in results]
    print("\n===== REPORT =====")
    print(f"correct questions: {ok}/{len(results)}")
    if hops:
        print(f"avg hops-to-banana: {sum(hops)/len(hops):.1f}")
    print(f"avg tokens-to-banana: {sum(toks)/len(toks):.0f}")
    print(f"avg banana precision: {sum(r['banana_precision'] for r in results)/len(results):.2f}")
    walls = [r["wall_s"] for r in results]
    print(f"time per question: avg {sum(walls)/len(walls):.1f}s  max {max(walls):.1f}s  total {sum(walls):.1f}s")
    out = Path(args.out) if args.out else Path(args.forest) / "_derived" / "demo-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report saved to {out}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
