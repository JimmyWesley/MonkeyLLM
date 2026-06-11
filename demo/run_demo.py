"""Phase 0 demo (Part F criterion 5): an LLM navigates the forest with the
Vine primitives only, answering multi-hop questions with traces + metrics.

The model and endpoint are configurable; provider resolution order:

  1. MONKEYLLM_LLM_ENDPOINT set        -> that OpenAI-compatible endpoint
                                          (llama.cpp local, vLLM, LM Studio...)
  2. OPENROUTER_API_KEY set            -> OpenRouter (online, no local GPU)
  3. otherwise                         -> Hugging Face serverless (HF_TOKEN)

    MONKEYLLM_LLM_MODEL       model id (defaults per provider)
    MONKEYLLM_LLM_API_KEY     key for custom endpoints (default: no-key)
    MONKEYLLM_LLM_MAX_TOKENS  completion budget (default 600; raise for
                              reasoning models if thinking is enabled)

Examples:
    # Local llama.cpp (scripts/serve_llm.py)
    set MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1
    set MONKEYLLM_LLM_MODEL=gemma-4
    python demo/run_demo.py

    # Online via OpenRouter (no local GPU needed)
    set OPENROUTER_API_KEY=sk-or-...
    set MONKEYLLM_LLM_MODEL=google/gemma-4-12b-it
    python demo/run_demo.py --questions demo/questions.json

Optional Phase 1 vector layer: if MONKEYLLM_EMBED_ENDPOINT is set and the
canopy is built (`vine canopy build`), locate runs hybrid (RRF vector+BM25)
instead of BM25-only — the rest of the demo is identical.

Each question runs in its own Vine session; traces land in
forest-fixture/_derived/traces/<session>.jsonl and the report prints
hops-to-banana, tokens-to-banana and banana precision.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monkeyllm import Vine, VineError  # noqa: E402

DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"
MAX_STEPS = 14

SYSTEM_PROMPT = """Você é um macaco navegador numa floresta de conhecimento. Responda a pergunta \
usando SOMENTE as ferramentas abaixo. Nunca invente fatos: navegue, colha e responda.

Ferramentas (responda SEMPRE com um único objeto JSON, nada além dele):
- {"tool": "locate", "args": {"query": "...", "k": 5}}  -> pontos de entrada (o helicóptero)
- {"tool": "sniff", "args": {"terms": ["..."], "scope": null}} -> grep literal nos CORPOS: termo exato
  (código, nome, número) -> nó + seção + trecho. scope opcional restringe a um galho ou a um nó.
- {"tool": "look", "args": {"id": "..."}}               -> digest barato de um nó (summary, vizinhos, outline)
- {"tool": "move", "args": {"id": "...", "rel": null}}  -> vizinhos de um nó (rel "children" lista filhos de galho)
- {"tool": "pick", "args": {"id": "...", "section": null}} -> corpo completo (só quando o summary confirmar o alvo)
- {"tool": "query", "args": {"id": "...", "sql": "SELECT ..."}} -> SQL read-only em nós type:dataset
- {"tool": "scan", "args": {"parent_id": "...", "filter": {}}}  -> filtra filhos por metadados
- {"tool": "answer", "args": {"text": "...", "answer_nodes": ["id1", "id2"]}} -> resposta final

Estratégia: a pergunta tem termo EXATO e raro (código, nome próprio, número)? sniff primeiro — ele
cai direto na seção certa e você colhe com pick(id, section). Pergunta conceitual? locate primeiro;
look para farejar; pick/query só no alvo. sniff devolveu demais? restrinja com scope. Economize tokens.
Regras importantes:
- Se a resposta vier com "truncated": true, a lista foi CORTADA por orçamento: não conclua que algo
  não existe — refine com locate (termos mais específicos) ou scan(parent_id, filter).
- Repetir a MESMA chamada com os MESMOS argumentos devolve o mesmo resultado; mude ferramenta ou termos.
- Nós type:dataset respondem por SQL: leia o manual no look e use query (os agregados não estão no texto).
O mapa da floresta (galho-mestre) está na primeira mensagem do usuário."""

# Prompt pré-sniff (spec v0.1), mantido VERBATIM para o braço baseline do A/B
# (--no-sniff): mede o ganho do farejador contra o macaco de 6 ferramentas.
SYSTEM_PROMPT_BASELINE = """Você é um macaco navegador numa floresta de conhecimento. Responda a pergunta \
usando SOMENTE as ferramentas abaixo. Nunca invente fatos: navegue, colha e responda.

Ferramentas (responda SEMPRE com um único objeto JSON, nada além dele):
- {"tool": "locate", "args": {"query": "...", "k": 5}}  -> pontos de entrada (o helicóptero)
- {"tool": "look", "args": {"id": "..."}}               -> digest barato de um nó (summary, vizinhos, outline)
- {"tool": "move", "args": {"id": "...", "rel": null}}  -> vizinhos de um nó (rel "children" lista filhos de galho)
- {"tool": "pick", "args": {"id": "...", "section": null}} -> corpo completo (só quando o summary confirmar o alvo)
- {"tool": "query", "args": {"id": "...", "sql": "SELECT ..."}} -> SQL read-only em nós type:dataset
- {"tool": "scan", "args": {"parent_id": "...", "filter": {}}}  -> filtra filhos por metadados
- {"tool": "answer", "args": {"text": "...", "answer_nodes": ["id1", "id2"]}} -> resposta final

Estratégia: locate primeiro; look para farejar; pick/query só no alvo. Economize tokens.
Regras importantes:
- Se a resposta vier com "truncated": true, a lista foi CORTADA por orçamento: não conclua que algo
  não existe — refine com locate (termos mais específicos) ou scan(parent_id, filter).
- Repetir a MESMA chamada com os MESMOS argumentos devolve o mesmo resultado; mude ferramenta ou termos.
- Nós type:dataset respondem por SQL: leia o manual no look e use query (os agregados não estão no texto).
O mapa da floresta (galho-mestre) está na primeira mensagem do usuário."""


OPENROUTER_ENDPOINT = "" #"https://openrouter.ai/api/v1"
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
    # reasoning models spend tokens thinking before the final content —
    # give them room (or disable thinking server-side) or content comes empty
    max_tokens = int(os.environ.get("MONKEYLLM_LLM_MAX_TOKENS", "600"))

    if endpoint:  # any OpenAI-compatible server: llama.cpp, OpenRouter, vLLM...
        import time as _t

        import httpx

        headers = {"Authorization": f"Bearer {api_key}"}
        if "openrouter" in endpoint:
            headers["HTTP-Referer"] = "https://monkeyllm.com"
            headers["X-Title"] = "MonkeyLLM"
        client = httpx.Client(base_url=endpoint.rstrip("/"), headers=headers, timeout=180.0)

        # lean by default (same policy as the local server): thinking off
        # unless MONKEYLLM_LLM_REASONING=on. OpenRouter normalizes the
        # `reasoning` param across providers.
        reasoning_on = os.environ.get("MONKEYLLM_LLM_REASONING", "off").lower() == "on"

        def chat(messages: list[dict]) -> str:
            payload = {"model": model, "messages": messages,
                       "max_tokens": max_tokens, "temperature": 0.1}
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


def run_question(forest: Path, chat, q: dict, verbose: bool = True, embedder=None,
                 use_sniff: bool = True, learn: bool = False) -> dict:
    vine = Vine(forest, writable=learn, session=f"demo-{q['id']}", embedder=embedder)
    try:
        master = vine.look("_index")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT if use_sniff else SYSTEM_PROMPT_BASELINE},
            {
                "role": "user",
                "content": f"Galho-mestre da floresta:\n{json.dumps(master, ensure_ascii=False)}\n\nPergunta: {q['question']}",
            },
        ]
        answer, answer_nodes = None, []
        entry_id: str | None = None  # landing zone: first node the monkey touches
        visited: set[str] = set()  # visited-cache (spec E.1.3): identical calls are not re-run
        for step in range(MAX_STEPS):
            reply = chat(messages)
            messages.append({"role": "assistant", "content": reply})
            action = parse_action(reply)
            if action is None:
                messages.append({"role": "user", "content": 'Formato inválido. Responda apenas com o JSON {"tool": ..., "args": ...}.'})
                continue
            tool, args = action.get("tool"), action.get("args") or {}
            if verbose:
                print(f"    [{step+1}] {tool}({json.dumps(args, ensure_ascii=False)[:110]})")
            if tool == "answer":
                answer = str(args.get("text", "")).strip()
                answer_nodes = list(args.get("answer_nodes") or [])
                break
            if entry_id is None and tool in ("look", "move", "pick", "query", "scan"):
                entry_id = args.get("id") or args.get("parent_id")
            call_key = f"{tool}:{json.dumps(args, ensure_ascii=False, sort_keys=True)}"
            if call_key in visited:
                hint = ("Chamada idêntica à anterior — o resultado seria o mesmo. "
                        "Mude os termos, a ferramenta, ou responda com o que já tem.")
                if use_sniff:
                    hint += (' Dica: sniff({"terms": ["termo exato"]}) procura o termo '
                             "dentro dos corpos e devolve a seção certa.")
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
                    result = {"error": {"code": "E_SCHEMA", "message": f"ferramenta desconhecida: {tool}"}}
                else:
                    result = fn(**args)
            except VineError as e:
                result = e.to_dict()
            except TypeError as e:
                result = {"error": {"code": "E_SCHEMA", "message": str(e)}}
            messages.append({"role": "user", "content": json.dumps(result, ensure_ascii=False, default=str)})

        expected = set(q["expected_nodes"])
        harvested = set(answer_nodes)
        correct_text = answer is not None and all(
            s.lower() in answer.lower() for s in q["answer_contains"]
        )
        success = bool(answer) and bool(harvested & expected)
        outcome = vine.close_session(success, answer_nodes)

        # The shout (spec C.8 / Part D): close_session only SUGGESTS shortcuts;
        # acting on them is the orchestrator's call. With --learn we graft an
        # atalho-descoberto from the landing zone to each suggested banana —
        # graft's reinforce-before-create turns repeats into fortification.
        shortcuts = []
        if learn and entry_id:
            for nid in outcome.get("suggest_shortcuts", []):
                if nid == entry_id or not vine.forest.exists(nid):
                    continue
                try:
                    g = vine.graft(entry_id, {"add_links": [{"rel": "atalho-descoberto", "target": nid}]})
                    shortcuts.append({"from": entry_id, "to": nid,
                                      "fortified": bool(g["fortified"]), "commit": g["commit"]})
                except VineError as e:
                    shortcuts.append({"from": entry_id, "to": nid, "error": e.to_dict()["error"]["code"]})
        if verbose and shortcuts:
            for s in shortcuts:
                print(f"    GRITO: atalho {s['from']} -> {s['to']} "
                      f"({'fortificado' if s.get('fortified') else s.get('error', 'plantado')})")

        precision = (len(harvested & expected) / len(harvested)) if harvested else 0.0
        return {
            "id": q["id"],
            "question": q["question"],
            "answer": answer,
            "answer_nodes": answer_nodes,
            "expected_nodes": q["expected_nodes"],
            "correct_text": correct_text,
            "banana_precision": round(precision, 2),
            "metrics": outcome["metrics"],
            "shortcuts": shortcuts,
            "trace": str(vine.tracer.trace_path),
        }
    finally:
        vine.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forest", default="forest-fixture")
    ap.add_argument("--questions", default=str(Path(__file__).parent / "questions.json"))
    ap.add_argument("--only", help="run a single question id (ex: q02)")
    ap.add_argument("--no-sniff", action="store_true",
                    help="baseline arm: hide the sniff tool (pre-v0.2 monkey) for A/B runs")
    ap.add_argument("--learn", action="store_true",
                    help="writable forest: graft suggested shortcuts (the shout) after each hunt")
    ap.add_argument("--out", help="report path (default: <forest>/_derived/demo-report.json)")
    args = ap.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] == args.only]
    chat, model = make_llm()
    endpoint, _, _ = resolve_provider()
    print(f"modelo: {model}  endpoint: {endpoint or 'huggingface serverless'}")

    from monkeyllm.canopy import embedder_from_env

    embedder = embedder_from_env()
    print(f"locate: {'híbrido (vetor+BM25)' if embedder else 'BM25-only'}")
    print(f"sniff: {'off (baseline)' if args.no_sniff else 'on'}")
    print(f"learn: {'on (gritos efetivados via graft)' if args.learn else 'off'}")

    import time as _time

    results = []
    for q in questions:
        print(f"\n== {q['id']}: {q['question']}")
        t0 = _time.perf_counter()
        r = run_question(Path(args.forest), chat, q, embedder=embedder,
                         use_sniff=not args.no_sniff, learn=args.learn)
        r["wall_s"] = round(_time.perf_counter() - t0, 1)
        results.append(r)
        m = r["metrics"]
        print(f"    resposta: {str(r['answer'])[:160]}")
        print(
            f"    hops-to-banana={m['hops_to_banana']}  tokens-to-banana={m['tokens_to_banana']}  "
            f"precision={r['banana_precision']}  texto_correto={r['correct_text']}  tempo={r['wall_s']}s"
        )

    ok = sum(1 for r in results if r["correct_text"])
    hops = [r["metrics"]["hops_to_banana"] for r in results if r["metrics"]["hops_to_banana"] is not None]
    toks = [r["metrics"]["tokens_to_banana"] for r in results]
    print("\n===== RELATÓRIO =====")
    print(f"perguntas corretas: {ok}/{len(results)}")
    if hops:
        print(f"hops-to-banana médio: {sum(hops)/len(hops):.1f}")
    print(f"tokens-to-banana médio: {sum(toks)/len(toks):.0f}")
    print(f"banana precision média: {sum(r['banana_precision'] for r in results)/len(results):.2f}")
    walls = [r["wall_s"] for r in results]
    print(f"tempo por pergunta: médio {sum(walls)/len(walls):.1f}s  max {max(walls):.1f}s  total {sum(walls):.1f}s")
    out = Path(args.out) if args.out else Path(args.forest) / "_derived" / "demo-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"relatório salvo em {out}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
