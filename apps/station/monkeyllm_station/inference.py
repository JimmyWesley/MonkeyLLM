# SPDX-License-Identifier: AGPL-3.0-only
# Copyright 2026 Jimmy Wesley

"""Per-forest inference (spec J.10).

A forest is not one workload. Ingest wants a careful summariser that obeys
the scent contract; answering wants a fast reader that cites what it was
given. Binding a model per (forest, role) lets an operator pay for care
where care matters and speed where speed matters, and to keep a sensitive
corpus on a local endpoint while a public one runs on a hosted model.

Nothing here touches the engine: `Curator` already takes an injected `chat`
callable, and answering composes `harvest` — both public surfaces.
"""

from __future__ import annotations

import json
import time

from monkeyllm.errors import E_SCHEMA, VineError

ANSWER_SYSTEM = (
    "You answer strictly from the harvested forest material you are given. "
    "If the material does not contain the answer, say so plainly instead of "
    "guessing. Cite the node ids you used, in square brackets, at the end."
)

NO_BINDING = (
    "no model is bound to this forest for the '{role}' role",
)

DATASET_CAVEAT = (
    "\n\n=== ABOUT THE DATASETS ABOVE ===\n"
    "These are type:dataset nodes: {ids}. Their rows live in a SQLite payload "
    "that is NOT part of the material above — what you have is their prose. "
    "Do NOT answer a total, an average or any other figure about them from "
    "surrounding text: a target, a plan or a rounded mention is not the "
    "ledger. Say plainly that the figure requires a SQL query over the "
    "dataset, and name it."
)


def chat_from_binding(binding: dict, *, timeout: float = 180.0):
    """An OpenAI-compatible client for one binding. Mirrors the engine's own
    client (`curator.make_chat`) so behaviour matches what the CLI produces —
    including the reasoning-off default, without which hybrid thinkers spend
    the whole budget thinking and return empty content."""
    import httpx

    endpoint = (binding.get("endpoint") or "").rstrip("/")
    if not endpoint:
        raise VineError(E_SCHEMA, "provider has no endpoint")
    model = binding.get("model") or "local"
    max_tokens = int(binding.get("max_tokens") or 600)
    reasoning_on = str(binding.get("reasoning", "off")).lower() == "on"
    if reasoning_on:
        max_tokens += 1000

    client = httpx.Client(
        base_url=endpoint,
        headers={"Authorization": f"Bearer {binding.get('api_key') or 'no-key'}"},
        timeout=timeout,
    )

    def chat(messages: list[dict]) -> str:
        payload = {"model": model, "messages": messages,
                   "max_tokens": max_tokens, "temperature": 0.1}
        if "openrouter" in endpoint and not reasoning_on:
            payload["reasoning"] = {"enabled": False}
        resp = client.post("/chat/completions", json=payload)
        if resp.status_code >= 400:
            raise VineError(
                E_SCHEMA,
                f"inference endpoint {resp.status_code}",
                hint=resp.text[:300],
            )
        body = resp.json()
        # What the provider says it billed. Counting tokens ourselves would
        # be an estimate of somebody else's meter; `usage` is the meter.
        usage = body.get("usage") or {}
        chat.usage["prompt"] += int(usage.get("prompt_tokens") or 0)
        chat.usage["completion"] += int(usage.get("completion_tokens") or 0)
        chat.usage["calls"] += 1
        return body["choices"][0]["message"].get("content") or ""

    chat.usage = {"prompt": 0, "completion": 0, "calls": 0}
    return chat, model


def _usage_of(chat) -> dict:
    """A stubbed chat in a test has no meter, and that is not an error —
    it is a run with nothing to bill."""
    return dict(getattr(chat, "usage", None) or {"prompt": 0, "completion": 0,
                                                 "calls": 0})


def _price(value) -> float | None:
    """Providers quote per-token prices as strings ('0.0000006'), and the
    free ones quote '0'. Anything unparseable becomes None — an unknown
    price must not render as free."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price >= 0 else None


def probe(endpoint: str, api_key: str | None) -> dict:
    """Connection test *and* catalogue (J.10).

    One call answers both questions an operator has at this moment — does
    this endpoint respond, and what does it serve — because they are the
    same HTTP request. Prices come back when the provider states them;
    a local Ollama or llama.cpp states none, and silence is reported as
    silence rather than as zero.
    """
    try:
        import httpx

        r = httpx.get(f"{endpoint.rstrip('/')}/models",
                      headers={"Authorization": f"Bearer {api_key or 'no-key'}"},
                      timeout=20.0)
    except Exception as e:
        # The import belongs inside the guard: a probe that cannot run is a
        # failed probe, and answering `{ok: false}` names the reason on the
        # card. Escaping as a 500 told the operator only that the provider
        # was unreachable, which pointed the search at their key.
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    if r.status_code >= 400:
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    try:
        payload = r.json()
        data = payload.get("data") or payload.get("models") or []
    except Exception:
        data = []

    models = []
    for m in data:
        if not isinstance(m, dict):
            continue
        ident = m.get("id") or m.get("name")
        if not ident:
            continue
        pricing = m.get("pricing") if isinstance(m.get("pricing"), dict) else {}
        models.append({
            "id": ident,
            "name": m.get("name") if m.get("name") != ident else None,
            "prompt": _price(pricing.get("prompt")),
            "completion": _price(pricing.get("completion")),
            "context": m.get("context_length") or m.get("context") or None,
        })
    models.sort(key=lambda m: m["id"])
    return {"ok": True, "models": models[:1000], "count": len(models)}


def answer(scoped_vine, question: str, binding: dict, k: int = 3,
           bundle: dict | None = None) -> dict:
    """Retrieve inside the principal's scope, then let the bound model read.

    The retrieval half is deterministic and scoped; the model only ever sees
    material the caller was already allowed to read, so the answering model
    cannot become a way around the policy. The host may hand in the sweep's
    `bundle` it already ran — the answer store's reading check (J.10.7,
    v0.35) needs the retrieval before it knows whether the model runs, and
    running the sweep twice would double-deposit its pheromone.
    """
    if bundle is None:
        bundle = scoped_vine.harvest(question, k=k)
    if isinstance(bundle, dict) and "error" in bundle:
        return bundle

    # A dataset's figures are in its payload, which harvest does NOT include —
    # it returns the node's prose. Without saying so, the model answers an
    # aggregate from whatever prose is nearest: asked for Q1 revenue it
    # quoted a *targets* note ("Q1 closed at ~$1.9M") and cited it, while the
    # ledger summed to $29.49M. Faithful to a node, wrong about the forest,
    # and indistinguishable from a good answer.
    datasets = [r.get("id") for r in bundle.get("results", [])
                if r.get("type") == "dataset"]
    caveat = DATASET_CAVEAT.format(ids=", ".join(datasets)) if datasets else ""

    chat, model = chat_from_binding(binding)
    # Timed here rather than around the whole composite: the retrieval half
    # is measured per primitive by the engine's own tracer, and reporting one
    # number for both would hide the only split that matters — how much of a
    # slow answer was the forest and how much was the provider.
    t0 = time.perf_counter()
    reply = chat([
        {"role": "system", "content": ANSWER_SYSTEM},
        {"role": "user", "content":
            "=== HARVESTED MATERIAL ===\n"
            + json.dumps(bundle, ensure_ascii=False)
            + caveat
            + f"\n\n=== QUESTION ===\n{question}"},
    ])
    return {
        "answer": reply.strip(),
        "model": model,
        "model_ms": round((time.perf_counter() - t0) * 1000, 1),
        "usage": _usage_of(chat),
        "evidence": [r.get("id") for r in bundle.get("results", [])],
        "sources": [{"id": r.get("id"), "title": r.get("title"),
                     "summary": r.get("summary"), "type": r.get("type")}
                    for r in bundle.get("results", [])],
        "harvest": bundle,
    }


# -- foraging: the answer that navigates (J.10.5) ---------------------------

# Reads only. The policy would already refuse a write to a principal without
# the capability — but a principal who HAS `write` asked a question, not for
# an edit, and a loop that could plant would turn one into the other.
FORAGE_TOOLS = ("locate", "sniff", "look", "move", "pick", "scan", "query")

MAX_HOPS = 16

FORAGE_SYSTEM = """You are a navigator in a knowledge forest. Answer the \
question using ONLY the tools below. Never invent facts: navigate, read, answer.

Always respond with a SINGLE JSON object, nothing else:
- {"tool": "locate", "args": {"query": "...", "k": 5}} -> entry points by curated metadata
- {"tool": "sniff", "args": {"terms": ["..."], "scope": null}} -> literal grep on BODIES: an exact
  term (code, name, number) -> node + section + snippet. `scope` restricts to a branch or node.
- {"tool": "look", "args": {"id": "..."}} -> cheap digest of a node: summary, neighbours, outline
- {"tool": "move", "args": {"id": "...", "rel": null}} -> neighbours ("children" lists a branch's)
- {"tool": "pick", "args": {"id": "...", "section": null}} -> the body, or one section of it
- {"tool": "scan", "args": {"parent_id": "...", "filter": {}}} -> filter children by metadata
- {"tool": "query", "args": {"id": "...", "sql": "SELECT ..."}} -> read-only SQL on type:dataset nodes
- {"tool": "answer", "args": {"text": "...", "answer_nodes": ["full/id"]}} -> the final answer

Strategy: an exact rare term (code, proper name, number)? sniff first — it lands in the section and
you read it with pick(id, section). Conceptual? locate first, look around, pick only the target.
Rules:
- "truncated": true means the result was CUT by budget — do not conclude something does not exist;
  refine with more specific terms or scan(parent_id, filter). On a query it means rows were
  dropped, never that they failed the filter: never present a truncated result as the complete
  set, and never state a count from one. Read the "hint" and ask again, narrower.
- Repeating the same call with the same arguments returns the same result. Change tool or terms.
- type:dataset nodes answer through SQL: read the manual in look, then query. Aggregates are not
  in the prose. A "notes" field on a dataset is what its operator wrote about how to read it —
  follow it. Never `SELECT *` on a wide table: results are token-budgeted, so name the columns
  you need or the rows come back truncated.
- answer_nodes are exact ids from tool results, and only nodes you actually opened.
Entry points for this question are in the first message."""

FORAGE_DEADLINE = (
    "Step budget spent. Do NOT call another tool. Using ONLY what you have already "
    'seen above, answer now with {"tool": "answer", "args": {"text": "...", '
    '"answer_nodes": ["..."]}}. If the material does not contain the answer, say so.'
)


def _tool_call(raw: str) -> dict | None:
    """The one JSON object a turn is supposed to be.

    Models wrap it in prose or a fence often enough that refusing anything but
    a bare object would spend the budget on formatting rather than navigation.
    """
    for candidate in (json_block(raw), raw):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "tool" in obj:
            return obj
    return None


def json_block(text: str) -> str | None:
    start, depth = None, 0
    for i, ch in enumerate(text or ""):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


# What a hop is allowed to report about itself. Small scalars the model
# chose, so a reader can see the *decision*, not just the tool name — "sniff"
# says nothing; `sniff terms=[architecture]` says what it was thinking.
HOP_ARGS = ("query", "terms", "sql", "section", "rel", "scope", "parent_id",
            "direction", "k")


def _hop_args(args: dict) -> dict:
    out = {}
    for key in HOP_ARGS:
        value = args.get(key)
        if value in (None, "", [], {}):
            continue
        out[key] = value if not isinstance(value, str) else value[:160]
    return out


def _outcome(tool: str, result: dict) -> dict:
    """One number per hop: did it find anything, and how much.

    Without it a walk reads as a list of verbs. `sniff → 0` followed by
    `sniff → 0` is the story of a hunt going nowhere, and it is invisible
    unless the count is there.
    """
    if isinstance(result, dict) and "error" in result:
        # J.10.5 (v0.47): the code alone made two different mistakes render
        # as the same word twice — a guessed table name and a guessed column
        # name both read as "forbidden", when the engine had in fact answered
        # both with the C.5 hint. The model already receives the whole
        # envelope; this is the console catching up. Nothing is disclosed
        # that the caller's own statement did not produce.
        err = result.get("error") or {}
        out = {"error": err.get("code")}
        if err.get("message"):
            out["message"] = str(err["message"])[:160]
        return out
    if not isinstance(result, dict):
        return {}
    for key, field in (("results", "results"), ("nodes", "nodes"),
                       ("neighbors", "neighbors"), ("children", "children")):
        if isinstance(result.get(key), list):
            return {field: len(result[key])}
    if tool == "pick":
        return {"tokens": result.get("body_tokens")}
    if tool == "query":
        return {"rows": result.get("row_count")}
    if tool == "look":
        return {"edges": len(result.get("edges_out") or [])
                + len(result.get("edges_in") or [])}
    return {}


def _identify(known: dict, result) -> None:
    """Collect `{id, title, summary}` from anything a tool returned.

    A list of ids tells a reader nothing — `projects/leads-2d` could be
    anything. Every primitive that names a node already carries its scent
    (that is what scent is *for*), so the label is free: it is picked up
    from results already fetched, never with an extra call.
    """
    if isinstance(result, dict):
        node_id = result.get("id")
        if isinstance(node_id, str) and (result.get("title") or result.get("summary")):
            known.setdefault(node_id, {
                "id": node_id, "title": result.get("title"),
                "summary": result.get("summary"), "type": result.get("type")})
        for value in result.values():
            if isinstance(value, (dict, list)):
                _identify(known, value)
    elif isinstance(result, list):
        for value in result:
            _identify(known, value)


def _sources(known: dict, cited: list, opened: list, read: dict) -> list[dict]:
    """The scent of the nodes this answer actually involved — not of every
    node the walk ever glimpsed, which on a wide branch is the whole forest.
    """
    wanted = [i for i in (list(read) + opened + list(cited)) if i in known]
    out, seen = [], set()
    for node_id in wanted:
        if node_id not in seen:
            seen.add(node_id)
            out.append(known[node_id])
    return out


def _absorb(read: dict, tool: str, args: dict, result: dict) -> None:
    """Keep the material a hop produced, in `harvest`'s shape (J.10.4).

    The sweep can show what the model was given because `harvest` hands the
    material back in one bundle. A forager has no bundle — it has a walk —
    so the same evidence is assembled here, hop by hop, and the console
    renders one thing either way.

    Only what actually carries text: `pick` bodies, `sniff` snippets, `query`
    rows. A `look` is a digest, and calling a summary an excerpt would blur
    exactly the distinction this panel exists to make.
    """
    def slot(node_id: str, found_by: str) -> dict:
        entry = read.setdefault(node_id, {"id": node_id, "found_by": [],
                                          "matches": [], "content": []})
        if found_by not in entry["found_by"]:
            entry["found_by"].append(found_by)
        return entry

    if tool == "sniff":
        for hit in result.get("results") or []:
            if isinstance(hit.get("id"), str):
                slot(hit["id"], "sniff")["matches"].extend(hit.get("matches") or [])
    elif tool == "pick" and isinstance(args.get("id"), str):
        entry = slot(args["id"], "pick")
        entry["content"].append({"section": args.get("section"),
                                 "body": result.get("body"),
                                 "outline": result.get("outline"),
                                 "body_tokens": result.get("body_tokens")})
    elif tool == "query" and isinstance(args.get("id"), str):
        entry = slot(args["id"], "query")
        # Structured, not serialised: rows ARE a table, and handing the
        # console a JSON blob would make it re-derive one from a string.
        entry["content"].append({
            "sql": args.get("sql"),
            "columns": result.get("columns") or [],
            "rows": result.get("rows") or [],
            "row_count": result.get("row_count"),
            "limited": result.get("limited"),
        })


def _teach_datasets(scoped_vine, entry: dict) -> None:
    """C.2.1 rule 6: a dataset arrives with what its operator wrote about it.

    The walk's first message is the entry `locate`, which is curated
    metadata — no body, no manual, no notes. On a dataset the natural next
    move is `query`, not `look`, so a model that never looks never reads a
    word the operator wrote: the mode with more freedom became the mode with
    less information, and it looked exactly like the agent ignoring them.

    In place, so the notes sit on the result they belong to rather than in a
    block the model has to re-associate. Bounded by `k`, and best effort —
    a note that cannot be read must not cost the walk its entry points.
    """
    for result in (entry.get("results") if isinstance(entry, dict) else None) or []:
        if not isinstance(result, dict) or result.get("type") != "dataset":
            continue
        node_id = result.get("id")
        if not isinstance(node_id, str):
            continue
        digest = scoped_vine.call("look", id=node_id, fields=["notes"])
        if isinstance(digest, dict) and digest.get("notes"):
            result["notes"] = digest["notes"]


def forage(scoped_vine, question: str, binding: dict, k: int = 3,
           max_hops: int = 6) -> dict:
    """Answer by navigating (J.10.5), instead of by one deterministic sweep.

    `answer`'s default is `harvest`: entry search, no hops, one model call —
    cheap, predictable, and blind to anything that is not reachable from the
    entry list. This is the other half of the thesis: the model holds the
    primitives and decides where to go, which is what the Gauntlet orders and
    what the whole forest metaphor is for.

    It is opt-in because it is not free: one model call per hop, against one
    for the sweep. The budget is a hop count, and running out does not waste
    the hunt — a deadline turn forces an answer from what was already read.
    """
    max_hops = max(1, min(int(max_hops or 1), MAX_HOPS))
    chat, model = chat_from_binding(binding)

    entry = scoped_vine.call("locate", query=question, k=k)
    _teach_datasets(scoped_vine, entry)
    messages = [
        {"role": "system", "content": FORAGE_SYSTEM},
        {"role": "user", "content":
            f"QUESTION: {question}\n\nlocate({question!r}) returned:\n"
            + json.dumps(entry, ensure_ascii=False)},
    ]

    hops: list[dict] = []
    opened: list[str] = []
    asked: set[str] = set()
    read: dict[str, dict] = {}
    known: dict[str, dict] = {}
    _identify(known, entry)
    model_ms = 0.0
    turns = 0

    for turn in range(max_hops + 1):
        deadline = turn == max_hops
        if deadline:
            messages.append({"role": "user", "content": FORAGE_DEADLINE})
        t0 = time.perf_counter()
        raw = chat(messages)
        turn_ms = (time.perf_counter() - t0) * 1000
        model_ms += turn_ms
        turns += 1

        call = _tool_call(raw)
        if call is None:
            messages.append({"role": "user", "content":
                             "That was not a single JSON object. Reply with one."})
            continue

        tool = str(call.get("tool") or "")
        args = call.get("args") if isinstance(call.get("args"), dict) else {}

        if tool == "answer":
            said = [i for i in (args.get("answer_nodes") or []) if isinstance(i, str)]
            return {
                "answer": str(args.get("text") or "").strip(),
                "model": model, "model_ms": round(model_ms, 1),
                "turns": turns, "hops": hops, "read": list(read.values()),
            "usage": _usage_of(chat),
            "sources": _sources(known, [], opened, read),
                "usage": _usage_of(chat),
                # Only what was actually opened. A cited id the model never
                # read is a claim about the forest, not evidence from it.
                "evidence": [i for i in said if i in opened] or opened[:k],
            }

        # The deadline turn said "do not call another tool". Executing one
        # anyway would make the budget advisory, and a budget that can be
        # talked out of is not a budget.
        if deadline:
            break

        if tool not in FORAGE_TOOLS:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content":
                             f"'{tool}' is not a tool here. Choose one of: "
                             + ", ".join(FORAGE_TOOLS)})
            continue

        # The observed failure mode of a bare loop is the search spiral:
        # sniff, sniff, locate, sniff, locate — re-phrasing the same query
        # instead of opening a node, until the budget is gone. Repeats are
        # free to answer (the result is identical) and expensive to ignore,
        # so the loop says so and points at the move that makes progress.
        key = f"{tool}:{json.dumps(args, sort_keys=True, default=str)}"
        if key in asked:
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content":
                             "You already made that exact call; it returns the same "
                             "result. Open one of the nodes you have seen with "
                             "look(id) or pick(id), or answer."})
            continue
        asked.add(key)

        h0 = time.perf_counter()
        result = scoped_vine.call(tool, **args)
        hop_ms = (time.perf_counter() - h0) * 1000
        failed = isinstance(result, dict) and "error" in result
        node = args.get("id") or args.get("parent_id")
        hops.append({"n": len(hops) + 1, "tool": tool,
                     **({"id": node} if isinstance(node, str) else {}),
                     "args": _hop_args(args), "out": _outcome(tool, result),
                     # Two numbers, because they are two different costs: the
                     # forest call, and the model turn that decided to make it.
                     "ms": round(hop_ms, 3), "model_ms": round(turn_ms, 1),
                     "ok": not failed})
        if not failed and tool in ("look", "pick", "query") and isinstance(node, str):
            if node not in opened:
                opened.append(node)
        if not failed:
            _absorb(read, tool, args, result)
            _identify(known, result)
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": json.dumps(result, ensure_ascii=False,
                                                               default=str)})

    # The deadline turn was spent and still produced no answer.
    return {"answer": "", "model": model, "model_ms": round(model_ms, 1),
            "turns": turns, "hops": hops, "read": list(read.values()),
            "evidence": opened[:k], "exhausted": True}


def curator_from_binding(vine, policy, binding: dict | None):
    """The Gardener's `on_curate` hook, driven by the forest's ingest model.

    Returns None when nothing is bound, and that is a supported state, not a
    degraded one (J.8): the Gardener falls back to the deterministic G.4
    derivation, so a forest with no model still ingests. Requiring a model
    to accept a document would make the cheapest thing a knowledge base does
    depend on the most expensive.

    The G.4.2.1 candidate list is filtered through the policy. It is offered
    to the model and its picks are written into the new node's frontmatter,
    so an unfiltered list would publish out-of-scope ids to whoever may read
    that node — the leak would arrive through curation rather than retrieval,
    but it would be the same leak.
    """
    if not binding:
        return None
    import yaml

    from monkeyllm.curator import CANDIDATE_LIMIT, Curator, make_candidates

    chat, _model = chat_from_binding(binding)
    directives = ""
    cfg = vine.forest.root / "_meta" / "gardener.yaml"
    if cfg.is_file():
        loaded = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        directives = (loaded.get("curation") or {}).get("directives") or ""

    wide = make_candidates(vine, limit=CANDIDATE_LIMIT * 4)

    def candidates(query: str) -> list[dict]:
        keep = [c for c in wide(query) if policy.in_scope(c["id"])]
        return keep[:CANDIDATE_LIMIT]

    return Curator(chat, directives=directives, candidates=candidates)


def recurate(scoped_vine, node_id: str, binding: dict) -> dict:
    """Re-summarise one node with the forest's ingest model (G.4.2 rules).

    The Curator validates against the scent contract and retries, so a model
    that writes a 200-token 'summary' is corrected rather than trusted.
    """
    from monkeyllm.curator import Curator

    node = scoped_vine.look(node_id)
    body = scoped_vine.pick(node_id).get("body", "")
    chat, model = chat_from_binding(binding)
    draft = {"id": node_id, "title": node.get("title", ""),
             "summary": node.get("summary", ""), "body": body,
             "type": node.get("type", "note")}
    enriched = Curator(chat)(draft)
    return {
        "id": node_id,
        "model": model,
        "before": node.get("summary", ""),
        "after": enriched.get("summary", ""),
        "tags": enriched.get("tags", []),
    }


class BoundEmbedder:
    """An OpenAI-compatible `/v1/embeddings` client for one binding (Part K).

    The Canopy records the model that built it and refuses a mismatch, so
    `model` here is not decoration — it is the identity the index compares
    itself against.
    """

    def __init__(self, endpoint: str, model: str, api_key: str | None = None,
                 timeout: float = 120.0):
        import httpx

        self.model = model
        self._client = httpx.Client(
            base_url=endpoint.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key or 'no-key'}"},
            timeout=timeout,
        )

    def embed(self, texts):
        from monkeyllm.canopy import normalize

        resp = self._client.post("/embeddings",
                                 json={"model": self.model, "input": list(texts)})
        if resp.status_code >= 400:
            raise VineError(E_SCHEMA, f"embedding endpoint {resp.status_code}",
                            hint=resp.text[:300])
        rows = sorted(resp.json()["data"], key=lambda d: d.get("index", 0))
        return [normalize(r["embedding"]) for r in rows]


def embedder_from_binding(binding: dict | None):
    """The forest's `embed` binding as an Embedder, or None.

    None is a supported state, not a degraded one: without it every
    primitive keeps its Phase 0 behaviour exactly (K.1).
    """
    if not binding or not binding.get("endpoint") or not binding.get("model"):
        return None
    return BoundEmbedder(binding["endpoint"], binding["model"],
                         binding.get("api_key"))
