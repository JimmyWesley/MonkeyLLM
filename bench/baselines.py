# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Jimmy Wesley

"""The two mandatory baselines (roadmap, Fase 1):

  (a) rag_topk  — classic top-k RAG: embed the question, stuff the top-k
      chunks into ONE completion, answer. No navigation, no iteration.
  (b) rag_iter  — iterative RAG agent: same chunk store, but the model can
      issue successive vector searches before answering. Still no indexes,
      no graph, no SQL — vector search is its only tool.

Both produce result dicts shaped like the MonkeyLLM demo's, with the same
metrics semantics:

  tokens_to_banana  — Σ estimated tokens of retrieved context handed to the
                      model (parallel to Σ tokens_out of Vine primitives)
  hops_to_banana    — number of retrieval rounds before answering
  banana_precision  — |answer_nodes ∩ expected| / |answer_nodes|
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monkeyllm.tokens import estimate_tokens, truncate_text  # noqa: E402

MAX_STEPS = 14
SNIPPET_TOKENS = 150  # per-chunk snippet size in iterative search results

TOPK_SYSTEM = """Você responde perguntas usando SOMENTE o contexto fornecido. Nunca invente fatos.
Responda com um único objeto JSON, nada além dele:
{"text": "resposta em português", "answer_nodes": ["ids dos documentos usados, ex: vendas/relatorio-q1-2026"]}
Os ids dos documentos aparecem entre colchetes no início de cada trecho do contexto."""

ITER_SYSTEM = """Você responde perguntas pesquisando um acervo com busca vetorial. Nunca invente fatos.
Responda SEMPRE com um único objeto JSON, nada além dele:
- {"tool": "search", "args": {"query": "..."}}   -> retorna os trechos mais similares
- {"tool": "answer", "args": {"text": "...", "answer_nodes": ["ids dos documentos usados"]}}
Os ids dos documentos aparecem entre colchetes no início de cada trecho. Pesquise quantas vezes
precisar (reformule a query se necessário) e responda quando tiver evidência suficiente."""


def parse_json_obj(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    for candidate in (m.group(0), text):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _grade(q: dict, answer: str | None, answer_nodes: list[str], *,
           context_tokens: int, rounds: int | None, llm_calls: int) -> dict:
    expected = set(q["expected_nodes"])
    # models may cite chunk ids ("node#3"); grade at node granularity
    harvested = {a.split("#")[0] for a in answer_nodes}
    correct_text = answer is not None and all(
        s.lower() in answer.lower() for s in q["answer_contains"]
    )
    precision = (len(harvested & expected) / len(harvested)) if harvested else 0.0
    return {
        "id": q["id"],
        "question": q["question"],
        "answer": answer,
        "answer_nodes": answer_nodes,
        "expected_nodes": q["expected_nodes"],
        "correct_text": correct_text,
        "banana_precision": round(precision, 2),
        "metrics": {
            "hops_to_banana": rounds,
            "tokens_to_banana": context_tokens,
            "llm_calls": llm_calls,
        },
    }


def rag_topk(chat, store, q: dict, k: int = 6, verbose: bool = True) -> dict:
    hits = store.search(q["question"], k=k)
    context = "\n\n---\n\n".join(h["text"] for h in hits)
    context_tokens = estimate_tokens(context)
    if verbose:
        print(f"    top-{k}: {[h['id'] for h in hits]}")
    reply = chat([
        {"role": "system", "content": TOPK_SYSTEM},
        {"role": "user", "content": f"Contexto:\n\n{context}\n\nPergunta: {q['question']}"},
    ])
    obj = parse_json_obj(reply) or {}
    answer = str(obj.get("text") or reply).strip() or None
    answer_nodes = list(obj.get("answer_nodes") or [])
    return _grade(q, answer, answer_nodes,
                  context_tokens=context_tokens, rounds=1, llm_calls=1)


def _shrink_history(messages: list[dict]) -> list[dict]:
    """Sliding window for the iterative agent: keep system + question + the
    last 4 exchange messages, summarizing the dropped middle as a stub."""
    if len(messages) <= 6:
        return messages
    head, tail = messages[:2], messages[-4:]
    stub = {"role": "user", "content": "(histórico anterior resumido: buscas antigas removidas por limite de contexto)"}
    return head + [stub] + tail


def rag_iter(chat, store, q: dict, k: int = 5, verbose: bool = True) -> dict:
    messages = [
        {"role": "system", "content": ITER_SYSTEM},
        {"role": "user", "content": f"Pergunta: {q['question']}"},
    ]
    context_tokens = 0
    searches = 0
    llm_calls = 0
    answer, answer_nodes = None, []
    for _ in range(MAX_STEPS):
        try:
            reply = chat(messages)
        except Exception as e:  # context overflow: slide the window and retry
            if "context" not in str(e).lower():
                raise
            messages = _shrink_history(messages)
            try:
                reply = chat(messages)
            except Exception:
                break  # still too fat -> this question fails (a RAG-iter trait)
        llm_calls += 1
        messages.append({"role": "assistant", "content": reply})
        obj = parse_json_obj(reply)
        if not obj or "tool" not in obj:
            messages.append({"role": "user", "content":
                             'Formato inválido. Responda apenas com o JSON {"tool": ..., "args": ...}.'})
            continue
        tool, args = obj.get("tool"), obj.get("args") or {}
        if tool == "answer":
            answer = str(args.get("text", "")).strip() or None
            answer_nodes = list(args.get("answer_nodes") or [])
            break
        if tool == "search":
            searches += 1
            hits = store.search(str(args.get("query", "")), k=k)
            payload = json.dumps(
                [{"id": h["id"], "text": truncate_text(h["text"], SNIPPET_TOKENS)} for h in hits],
                ensure_ascii=False,
            )
            context_tokens += estimate_tokens(payload)
            if verbose:
                print(f"    search#{searches}({str(args.get('query'))[:60]!r}) -> {[h['id'] for h in hits]}")
            messages.append({"role": "user", "content": payload})
        else:
            messages.append({"role": "user", "content":
                             json.dumps({"error": f"ferramenta desconhecida: {tool}"}, ensure_ascii=False)})
    return _grade(q, answer, answer_nodes,
                  context_tokens=context_tokens, rounds=searches or None, llm_calls=llm_calls)
