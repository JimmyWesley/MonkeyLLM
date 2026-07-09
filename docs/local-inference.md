# Inference — runbook (local and online)

How to run MonkeyLLM end to end with local models via **llama.cpp** on the
RTX 3090, downloading weights from Hugging Face. Everything under `models/`
and `bin/` is git-ignored and rebuildable.

## Stack

| Role | Model | Server | Port |
|---|---|---|---|
| Navigator monkey (SLM) | Qwen2.5-7B-Instruct Q4_K_M | `llama-server` | 8090 |
| Embedder (Canopy layer) | bge-m3 Q8_0 | `llama-server --embedding` | 8091 |

(8080/8081 were avoided: on Windows, 8080 is often reserved by HTTP.sys —
`netstat` shows PID 4 "System" LISTENING.)

Both are OpenAI-compatible. Phase 0 (the 10-question demo) needs only the
chat one; the embedder is optional and activates hybrid `locate` (Phase 1).

## Step by step

```powershell
# 1. download the llama.cpp binary (CUDA) + both GGUFs (only step needing network)
python scripts/setup_models.py

# 2. start both servers on the GPU (leave this terminal open)
python scripts/serve_llm.py

# 3. in ANOTHER terminal, point the client at the local servers
#    PowerShell:
$env:MONKEYLLM_LLM_ENDPOINT   = "http://localhost:8090/v1"
$env:MONKEYLLM_LLM_MODEL      = "qwen2.5-7b"
$env:MONKEYLLM_EMBED_ENDPOINT = "http://localhost:8091/v1"   # optional (Phase 1)
$env:MONKEYLLM_EMBED_MODEL    = "bge-m3"
#    Git Bash / MINGW64:
#    export MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1 MONKEYLLM_LLM_MODEL=qwen2.5-7b
#    export MONKEYLLM_EMBED_ENDPOINT=http://localhost:8091/v1 MONKEYLLM_EMBED_MODEL=bge-m3

# 4. (optional, Phase 1) build the forest's vector layer
python -m monkeyllm.cli canopy build --forest forests/forest-fixture
#    -> _derived/canopy/  (normalized vectors, rebuildable)

# 5. run the 10 multi-hop question demo (criterion F.5)
python examples/demo/run_demo.py
#    -> _derived/traces/*.jsonl  +  _derived/demo-report.json

# 6. locate benchmark (quality + speed, criterion F.6)
python scripts/bench_locate.py
#    -> _derived/bench-locate.json
```

Without step 3/4, everything works in **BM25-only** mode (Phase 0 is
designed this way — zero embeddings). Step 6's benchmark runs with no
server at all for the `bm25` row; with `MONKEYLLM_EMBED_ENDPOINT` + a built
canopy it adds the `hybrid` row alongside.

## macOS (Apple Silicon / Metal)

The same scripts work on a Mac. `setup_models.py --only bin` downloads the
official `macos-arm64` build, but those are compiled against the latest
macOS — on older systems (e.g. macOS 14) they fail with a Metal dyld error.
Fallback: `brew install llama.cpp`; `serve_llm.py` probes each candidate
with `--version` and falls back to the PATH `llama-server` automatically
when the one under `bin/llamacpp/` is missing or does not run on this OS.

Evaluating a 1B navigator (MiniCPM5-1B, Q8_0):

```bash
python scripts/setup_models.py --only llm \
    --llm-repo openbmb/MiniCPM5-1B-GGUF --llm-file MiniCPM5-1B-Q8_0.gguf
python scripts/serve_llm.py        # newest GGUF wins; alias "minicpm5-1b"
export MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1
export MONKEYLLM_LLM_MODEL=minicpm5-1b
```

Use the official `openbmb/MiniCPM5-1B-GGUF` — the community
"Agentic-toolUse" fine-tune needs a custom raw prompt format and does not
speak the OpenAI chat/tools interface this stack relies on.

## Online model (OpenRouter) — no local GPU

If you don't want (or can't) run a local model, use OpenRouter: the same
OpenAI interface, small and cheap hosted models, zero VRAM. Just the key —
the client detects it on its own:

```bash
export OPENROUTER_API_KEY=sk-or-...
# optional: pick the model (default: google/gemma-4-26b-a4b-it:free)
# export MONKEYLLM_LLM_MODEL=google/gemma-4-31b-it
python examples/demo/run_demo.py
```

Watch the model id: OpenRouter's catalog differs from Hugging Face's (e.g.
there is no 12B there; the hosted Gemma 4 models are
`google/gemma-4-26b-a4b-it` and `google/gemma-4-31b-it`, with `:free`
variants). A wrong id means HTTP 400, and the client now surfaces the
provider's own message in the error.

Notes:

- Provider resolution order: `MONKEYLLM_LLM_ENDPOINT` (explicit) >
  `OPENROUTER_API_KEY` (OpenRouter) > `HF_TOKEN` (HF serverless).
- The client already retries with backoff on 429/5xx — important on
  OpenRouter's free tier (~20 req/min).
- Hybrid `locate` still requires the local embedder (OpenRouter does not
  serve embeddings); without one it gracefully falls back to BM25-only —
  the demo still works 100% online either way.
- Expected latency: higher than local (network + queue), but zero machine
  cost.

## Environment variables

| Var | Default | Use |
|---|---|---|
| `MONKEYLLM_LLM_ENDPOINT` | (empty) | chat's OpenAI base_url (local llama.cpp, vLLM...) |
| `OPENROUTER_API_KEY` | (empty) | activates OpenRouter when there's no local endpoint |
| `MONKEYLLM_LLM_MODEL` | per provider | chat model id/alias |
| `MONKEYLLM_LLM_MAX_TOKENS` | `600` | completion budget (raise for reasoning models) |
| `MONKEYLLM_EMBED_ENDPOINT` | (empty = BM25-only) | embedder's OpenAI base_url |
| `MONKEYLLM_EMBED_MODEL` | `bge-m3` | embedder id/alias |
| `HF_TOKEN` | — | HF token (download + serverless) |

## Notes

- **VRAM:** Qwen 7B Q4 (~5 GB) + bge-m3 Q8 (~0.7 GB) fit comfortably in the
  3090's 24 GB. For better multi-hop quality: `setup_models.py --llm-file
  Qwen2.5-14B-Instruct-Q4_K_M.gguf --llm-repo bartowski/Qwen2.5-14B-Instruct-GGUF`.
- **Switching embedders** invalidates the index: re-run `canopy build` (the
  model is recorded in `_derived/canopy/index.json`).
- `locate` only turns hybrid when **there is an index AND an embedder** —
  any other combination stays BM25-only, with no contract change
  (architecture doc, §3).
