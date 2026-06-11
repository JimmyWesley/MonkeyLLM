# MonkeyLLM — guia para o agente

Floresta de conhecimento navegável por um SLM: markdown + índices, percorridos
pelas primitivas MCP do **Vine**. A `docs/monkeyllm-spec-v0.1.md` é normativa —
**a spec é a verdade**; mudança de contrato exige nova versão da spec antes do código.

## Layout

- `src/monkeyllm/` — pacote `monkeyllm`, CLI `vine`. `vine.py` (8 primitivas),
  `catalog.py` (SQLite + FTS5 = lado BM25 do locate + scan), `canopy.py`
  (camada vetorial opcional, Fase 1), `parser.py`/`models.py` (frontmatter),
  `forest.py`/`gitops.py` (arquivos + commits), `telemetry.py`/`trails.py`
  (traces + feromônio).
- `forest-fixture/` — floresta de teste (82 nós, 12 galhos, 1 dataset SQLite),
  com repo git próprio embarcado. Gerada por `scripts/build_fixture.py`.
- `demo/` — loop agente↔Vine das 10 perguntas multi-hop (critério F.5).
- `scripts/` — `setup_models.py`, `serve_llm.py`, `bench_locate.py`.
- `_derived/` é descartável e reconstruível (`vine reindex`); nunca é fonte de verdade.

## Comandos

```powershell
.venv\Scripts\python.exe -m pytest -q          # suíte (deve ficar verde)
python -m monkeyllm.cli validate --forest forest-fixture
python -m monkeyllm.cli reindex  --forest forest-fixture
python -m monkeyllm.cli canopy build --forest forest-fixture   # camada vetorial
python scripts/bench_locate.py --forest forest-fixture          # qualidade+latência
```

Modelos locais (llama.cpp na 3090): ver `docs/local-inference.md`.

## Convenções e armadilhas

- **Orçamentos de token** com truncamento sempre explícito (`truncated: true`):
  look 500, move 600, locate/scan 800. Nunca cortar em silêncio.
- **`locate` é BM25-only por padrão** (Fase 0, zero embeddings). Vira híbrido
  (RRF vetor+BM25) só quando há índice Canopy **e** um embedder — qualquer outra
  combinação mantém o contrato BM25-only intacto.
- `query` é SQL read-only sobre nós `type:dataset`: rejeitar toda escrita
  (`;DROP`, `ATTACH`, multi-statement, `PRAGMA`) — há suíte de injeção.
- `plant`/`graft` são atômicos e fazem `git commit` **dentro da floresta**
  (spec C.7/C.8). Isso é comportamento do produto e é correto.
- **NUNCA fazer commit no repo externo do projeto** — o usuário commita à mão.
  (A floresta-fixture e florestas de teste têm git próprio; isso é outra coisa.)
- Parser de frontmatter rejeita cedo: melhor recusar lixo que aceitar.
