# Model notes navigator SLM candidates

Which chat models work well as the navigator monkey (and for Gardener
curation), measured with the Phase 0 demo (`examples/demo/run_demo.py`,
10 multi-hop questions over `forests/forest-fixture`). Runs of 2026-07-01
via OpenRouter, single run each expect provider/network variance;
for serious comparisons use the Monkey Bench (`bench/run_bench.py`).

## Recommended models

| Model | Where | Notes |
|---|---|---|
| `qwen/qwen3.5-flash-02-23` | OpenRouter | **Default pick.** 10/10, fastest of the whole batch (4.0s avg, 6.5s worst), precision 0.88, ~$0.065/$0.26 per M tokens. |
| `qwen/qwen3.6-35b-a3b` | OpenRouter | 10/10, 5.6s avg, best navigation (1.1 hops, 1018 tokens-to-banana). Hybrid reasoning model needs thinking disabled (see below). |
| `google/gemma-4-26b-a4b-it` | OpenRouter | 10/10, 5.9s avg, most consistent latency (9.0s worst). MoE, 4B active. |
| Gemma 4 12B (`gemma-4-12b-it`) | **local only** | Phenomenal in local llama.cpp testing on the 3090. NOT available on OpenRouter the hosted family starts at 26B-A4B. |
| `z-ai/glm-4.7-flash` | OpenRouter | Honorable backup: 9/10 at 6.0s avg. |

## Full sweep (demo, 2026-07-01)

| Model | Correct | Avg time | Precision | $/M in–out |
|---|---|---|---|---|
| qwen/qwen3.5-flash-02-23 | 10/10 | 4.0s | 0.88 | 0.065–0.26 |
| qwen/qwen3.6-35b-a3b | 10/10 | 5.6s | 0.88 | |
| google/gemma-4-26b-a4b-it | 10/10 | 5.9s | 0.83 | 0.06–0.33 |
| qwen/qwen3-30b-a3b-instruct-2507 | 10/10 | 11.3s | 0.92 | 0.048–0.19 |
| z-ai/glm-4.7-flash | 9/10 | 6.0s | 0.83 | 0.06–0.40 |
| meta-llama/llama-3.1-8b-instruct | 7/10 | 7.0s | 0.80 | 0.02–0.03 |
| google/gemma-3-4b-it | 6/10 | 14.2s | 0.67 | 0.05–0.10 |
| inclusionai/ling-2.6-flash | 2/10 | 13.2s | 0.20 | 0.01–0.03 |
| liquid/lfm-2-24b-a2b | 0/10 | 7.7s | 0.00 | 0.03–0.12 |

## Gotchas

- **Reasoning models return empty content by default.** Hybrid thinkers
  (Qwen3.x) burn `max_tokens` on thinking. Both LLM clients (curator and
  demo) send `reasoning: {enabled: false}` to OpenRouter unless
  `MONKEYLLM_LLM_REASONING=on`; when on, +1000 is added to `max_tokens`.
- **Some models refuse `reasoning: off`** (`openai/gpt-oss-20b`,
  `openai/gpt-5-nano` → HTTP 400 "Reasoning is mandatory"). They only run
  with `MONKEYLLM_LLM_REASONING=on` and are slower by design.
- **Always set `MONKEYLLM_LLM_MODEL` explicitly with OpenRouter** the
  `local` fallback picks the first entry of the huge `/models` list.
- **Ultra-cheap models collapse on the navigation protocol** (ling-2.6-flash,
  lfm-2-24b-a2b): below a capability floor the tool-call loop falls apart —
  cheap per token is not cheap per correct answer.
- **OpenRouter serves no `/v1/embeddings`** Canopy/bench-RAG need a local
  embedder or another provider; without one, `locate` stays BM25-only
  (the Phase 0 contract).
