# Inferência — runbook (local e online)

Como rodar o MonkeyLLM ponta a ponta com modelos locais via **llama.cpp** na
RTX 3090, baixando os pesos do Hugging Face. Tudo que cai em `models/` e
`bin/` é git-ignored e reconstruível.

## Stack

| Papel | Modelo | Servidor | Porta |
|---|---|---|---|
| Macaco navegador (SLM) | Qwen2.5-7B-Instruct Q4_K_M | `llama-server` | 8090 |
| Embedder (camada Canopy) | bge-m3 Q8_0 | `llama-server --embedding` | 8091 |

(8080/8081 foram evitadas: no Windows a 8080 costuma estar reservada pelo
HTTP.sys — `netstat` mostra LISTENING do PID 4 "System".)

Os dois são OpenAI-compatible. A Fase 0 (demo das 10 perguntas) precisa só do
chat; o embedder é opcional e ativa o `locate` híbrido (Fase 1).

## Passo a passo

```powershell
# 1. baixar binário llama.cpp (CUDA) + os dois GGUFs  (único passo com rede)
python scripts/setup_models.py

# 2. subir os dois servidores na GPU (deixe este terminal aberto)
python scripts/serve_llm.py

# 3. em OUTRO terminal, apontar o cliente para os servidores locais
#    PowerShell:
$env:MONKEYLLM_LLM_ENDPOINT   = "http://localhost:8090/v1"
$env:MONKEYLLM_LLM_MODEL      = "qwen2.5-7b"
$env:MONKEYLLM_EMBED_ENDPOINT = "http://localhost:8091/v1"   # opcional (Fase 1)
$env:MONKEYLLM_EMBED_MODEL    = "bge-m3"
#    Git Bash / MINGW64:
#    export MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1 MONKEYLLM_LLM_MODEL=qwen2.5-7b
#    export MONKEYLLM_EMBED_ENDPOINT=http://localhost:8091/v1 MONKEYLLM_EMBED_MODEL=bge-m3

# 4. (opcional, Fase 1) construir a camada vetorial da floresta
python -m monkeyllm.cli canopy build --forest forests/forest-fixture
#    -> _derived/canopy/  (vetores normalizados, reconstruível)

# 5. rodar a demo das 10 perguntas multi-hop (critério F.5)
python examples/demo/run_demo.py
#    -> _derived/traces/*.jsonl  +  _derived/demo-report.json

# 6. benchmark do locate (qualidade + velocidade, critério F.6)
python scripts/bench_locate.py
#    -> _derived/bench-locate.json
```

Sem o passo 3/4, tudo funciona em **BM25-only** (a Fase 0 é assim por design —
zero embeddings). O benchmark do passo 6 roda sem nenhum servidor para a linha
`bm25`; com `MONKEYLLM_EMBED_ENDPOINT` + canopy construído ele acrescenta a
linha `hybrid` lado a lado.

## Modelo online (OpenRouter) — sem GPU local

Quem não quer (ou não pode) rodar modelo local usa o OpenRouter: mesma
interface OpenAI, modelos pequenos e baratos hospedados, zero VRAM. Basta a
chave — o cliente detecta sozinho:

```bash
export OPENROUTER_API_KEY=sk-or-...
# opcional: escolher o modelo (default: google/gemma-4-26b-a4b-it:free)
# export MONKEYLLM_LLM_MODEL=google/gemma-4-31b-it
python examples/demo/run_demo.py
```

Atenção ao id do modelo: o catálogo do OpenRouter é diferente do Hugging Face
(ex.: lá não existe o 12B; os Gemma 4 hospedados são `google/gemma-4-26b-a4b-it`
e `google/gemma-4-31b-it`, com variantes `:free`). Id errado = HTTP 400, e o
cliente agora mostra a mensagem do provedor no erro.

Notas:

- A resolução de provedor é: `MONKEYLLM_LLM_ENDPOINT` (explícito) >
  `OPENROUTER_API_KEY` (OpenRouter) > `HF_TOKEN` (HF serverless).
- O cliente já faz retry com backoff em 429/5xx — importante no tier
  gratuito do OpenRouter (~20 req/min).
- O `locate` híbrido continua exigindo o embedder local (OpenRouter não serve
  embeddings); sem ele, cai graciosamente para BM25-only — a demo funciona
  100% online mesmo assim.
- Latência esperada: maior que local (rede + fila), mas sem custo de máquina.

## Variáveis de ambiente

| Var | Default | Uso |
|---|---|---|
| `MONKEYLLM_LLM_ENDPOINT` | (vazio) | base_url OpenAI do chat (llama.cpp local, vLLM...) |
| `OPENROUTER_API_KEY` | (vazio) | ativa o OpenRouter quando não há endpoint local |
| `MONKEYLLM_LLM_MODEL` | por provedor | id/alias do modelo de chat |
| `MONKEYLLM_LLM_MAX_TOKENS` | `600` | orçamento de completion (aumente p/ modelos raciocinadores) |
| `MONKEYLLM_EMBED_ENDPOINT` | (vazio = BM25-only) | base_url OpenAI do embedder |
| `MONKEYLLM_EMBED_MODEL` | `bge-m3` | id/alias do embedder |
| `HF_TOKEN` | — | token HF (download + serverless) |

## Notas

- **VRAM:** Qwen 7B Q4 (~5 GB) + bge-m3 Q8 (~0,7 GB) cabem folgados nos 24 GB da
  3090. Para mais qualidade no multi-hop: `setup_models.py --llm-file
  Qwen2.5-14B-Instruct-Q4_K_M.gguf --llm-repo bartowski/Qwen2.5-14B-Instruct-GGUF`.
- **Trocar de embedder** invalida o índice: rode `canopy build` de novo (o modelo
  fica gravado em `_derived/canopy/index.json`).
- O `locate` só vira híbrido quando **há índice E um embedder** — qualquer outra
  combinação permanece BM25-only, sem mudança de contrato (arquitetura §3).
