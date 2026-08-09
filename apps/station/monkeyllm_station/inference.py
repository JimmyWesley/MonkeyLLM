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

from monkeyllm.errors import E_SCHEMA, VineError

ANSWER_SYSTEM = (
    "You answer strictly from the harvested forest material you are given. "
    "If the material does not contain the answer, say so plainly instead of "
    "guessing. Cite the node ids you used, in square brackets, at the end."
)

NO_BINDING = (
    "no model is bound to this forest for the '{role}' role",
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
        return resp.json()["choices"][0]["message"].get("content") or ""

    return chat, model


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
    import httpx

    try:
        r = httpx.get(f"{endpoint.rstrip('/')}/models",
                      headers={"Authorization": f"Bearer {api_key or 'no-key'}"},
                      timeout=20.0)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
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


def answer(scoped_vine, question: str, binding: dict, k: int = 3) -> dict:
    """Retrieve inside the principal's scope, then let the bound model read.

    The retrieval half is deterministic and scoped; the model only ever sees
    material the caller was already allowed to read, so the answering model
    cannot become a way around the policy.
    """
    bundle = scoped_vine.harvest(question, k=k)
    if isinstance(bundle, dict) and "error" in bundle:
        return bundle

    chat, model = chat_from_binding(binding)
    reply = chat([
        {"role": "system", "content": ANSWER_SYSTEM},
        {"role": "user", "content":
            "=== HARVESTED MATERIAL ===\n"
            + json.dumps(bundle, ensure_ascii=False)
            + f"\n\n=== QUESTION ===\n{question}"},
    ])
    return {
        "answer": reply.strip(),
        "model": model,
        "evidence": [r.get("id") for r in bundle.get("results", [])],
        "harvest": bundle,
    }


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
