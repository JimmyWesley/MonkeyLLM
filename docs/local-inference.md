# Inferência local — runbook (Fase 0 demo + Fase 1 vetores)

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
python -m monkeyllm.cli canopy build --forest forest-fixture
#    -> _derived/canopy/  (vetores normalizados, reconstruível)

# 5. rodar a demo das 10 perguntas multi-hop (critério F.5)
python demo/run_demo.py --forest forest-fixture
#    -> _derived/traces/*.jsonl  +  _derived/demo-report.json

# 6. benchmark do locate (qualidade + velocidade, critério F.6)
python scripts/bench_locate.py --forest forest-fixture
#    -> _derived/bench-locate.json
```

Sem o passo 3/4, tudo funciona em **BM25-only** (a Fase 0 é assim por design —
zero embeddings). O benchmark do passo 6 roda sem nenhum servidor para a linha
`bm25`; com `MONKEYLLM_EMBED_ENDPOINT` + canopy construído ele acrescenta a
linha `hybrid` lado a lado.

## Variáveis de ambiente

| Var | Default | Uso |
|---|---|---|
| `MONKEYLLM_LLM_ENDPOINT` | HF serverless | base_url OpenAI do chat |
| `MONKEYLLM_LLM_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | id/alias do modelo de chat |
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
