"""Phase 0 demo (Part F criterion 5): an LLM navigates the forest with the
Vine primitives only, answering multi-hop questions with traces + metrics.

The model and endpoint are configurable (Hugging Face by default):

    MONKEYLLM_LLM_MODEL     model id (default: Qwen/Qwen2.5-7B-Instruct)
    MONKEYLLM_LLM_ENDPOINT  optional OpenAI-compatible base_url
                            (HF router, vLLM, llama.cpp server, LM Studio...)
    HF_TOKEN                Hugging Face token (or any API key the endpoint expects)

Examples:
    # Hugging Face serverless inference
    set HF_TOKEN=hf_xxx
    python demo/run_demo.py

    # Local llama.cpp / vLLM (OpenAI-compatible)
    set MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1
    set MONKEYLLM_LLM_MODEL=qwen2.5-7b
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
- {"tool": "look", "args": {"id": "..."}}               -> digest barato de um nó (summary, vizinhos, outline)
- {"tool": "move", "args": {"id": "...", "rel": null}}  -> vizinhos de um nó (rel "children" lista filhos de galho)
- {"tool": "pick", "args": {"id": "...", "section": null}} -> corpo completo (só quando o summary confirmar o alvo)
- {"tool": "query", "args": {"id": "...", "sql": "SELECT ..."}} -> SQL read-only em nós type:dataset
- {"tool": "scan", "args": {"parent_id": "...", "filter": {}}}  -> filtra filhos por metadados
- {"tool": "answer", "args": {"text": "...", "answer_nodes": ["id1", "id2"]}} -> resposta final

Estratégia: locate primeiro; look para farejar; pick/query só no alvo. Economize tokens.
O mapa da floresta (galho-mestre) está na primeira mensagem do usuário."""


def make_llm():
    from huggingface_hub import InferenceClient

    model = os.environ.get("MONKEYLLM_LLM_MODEL", DEFAULT_MODEL)
    endpoint = os.environ.get("MONKEYLLM_LLM_ENDPOINT")
    token = os.environ.get("HF_TOKEN") or os.environ.get("MONKEYLLM_LLM_API_KEY") or "no-key"
    client = InferenceClient(base_url=endpoint, token=token) if endpoint else InferenceClient(token=token)

    def chat(messages: list[dict]) -> str:
        resp = client.chat_completion(messages=messages, model=model, max_tokens=600, temperature=0.1)
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


def run_question(forest: Path, chat, q: dict, verbose: bool = True, embedder=None) -> dict:
    vine = Vine(forest, writable=False, session=f"demo-{q['id']}", embedder=embedder)
    try:
        master = vine.look("_index")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Galho-mestre da floresta:\n{json.dumps(master, ensure_ascii=False)}\n\nPergunta: {q['question']}",
            },
        ]
        answer, answer_nodes = None, []
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
            try:
                fn = {"locate": vine.locate, "look": vine.look, "move": vine.move,
                      "pick": vine.pick, "query": vine.query, "scan": vine.scan}.get(tool)
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
            "trace": str(vine.tracer.trace_path),
        }
    finally:
        vine.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--forest", default="forest-fixture")
    ap.add_argument("--questions", default=str(Path(__file__).parent / "questions.json"))
    ap.add_argument("--only", help="run a single question id (ex: q02)")
    args = ap.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] == args.only]
    chat, model = make_llm()
    print(f"modelo: {model}  endpoint: {os.environ.get('MONKEYLLM_LLM_ENDPOINT', 'huggingface serverless')}")

    from monkeyllm.canopy import embedder_from_env

    embedder = embedder_from_env()
    print(f"locate: {'híbrido (vetor+BM25)' if embedder else 'BM25-only'}")

    results = []
    for q in questions:
        print(f"\n== {q['id']}: {q['question']}")
        r = run_question(Path(args.forest), chat, q, embedder=embedder)
        results.append(r)
        m = r["metrics"]
        print(f"    resposta: {str(r['answer'])[:160]}")
        print(
            f"    hops-to-banana={m['hops_to_banana']}  tokens-to-banana={m['tokens_to_banana']}  "
            f"precision={r['banana_precision']}  texto_correto={r['correct_text']}"
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
    out = Path(args.forest) / "_derived" / "demo-report.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"relatório salvo em {out}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
