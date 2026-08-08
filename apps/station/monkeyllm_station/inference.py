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


def probe(endpoint: str, api_key: str | None) -> dict:
    """Console 'test connection': prove the endpoint answers before an
    operator binds a model to it and discovers the typo during an ingest."""
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
        data = r.json().get("data") or r.json().get("models") or []
        names = [m.get("id") or m.get("name") for m in data if isinstance(m, dict)]
    except Exception:
        names = []
    return {"ok": True, "models": [n for n in names if n][:200], "count": len(names)}


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
