# MonkeyLLM — Roadmap de Desenvolvimento (Fases 0 → 4)

**Audiência:** time de desenvolvimento e gestão do projeto.
**Documentos companheiros:** `monkeyllm-arquitetura.md` (visão), `monkeyllm-spec-v0.1.md` (contratos normativos da Fase 0).
**Regra de ouro do projeto:** nenhuma fase começa sem a anterior ter passado nos critérios de saída. Nenhuma otimização é feita sem medição que a justifique (o Monkey Bench é o juiz, não a intuição).

---

## Visão geral

| Fase | Nome | Pergunta que responde | Duração estimada | Status |
|---|---|---|---|---|
| 0 | Floresta Navegável | Um SLM navega só por índices? | 1-2 semanas | **Especificada (spec v0.1)** |
| 1 | Helicóptero Completo | Navegação por índices + locate vetorial supera RAG? | 3-4 semanas | Escopo definido abaixo |
| 1.5 | Tropa | Enxame paralelo reduz tempo de relógio a custo aceitável? | 1-2 semanas | Protocolo na spec, Parte E |
| 2 | Banco Vivo | O conhecimento compõe e a navegação converge com o uso? | 4-6 semanas | Escopo definido abaixo |
| 3 | Motor Próprio (condicional) | Onde o stack Python engasga de verdade? | a medir | Só se os dados exigirem |
| 4 | Produto & Paper | MonkeyLLM como sistema publicável e utilizável | contínua | — |

---

## Fase 0 — Floresta Navegável

**Objetivo:** provar que um SLM local navega uma floresta real usando apenas as primitivas e os índices — zero embeddings.

**Escopo:** spec v0.1 integral. Vine (MCP, Python) com `locate` (BM25-only via Catálogo FTS5), `look` (+`fields`), `move`, `pick`, `query`, `scan`, `plant`, `graft` (com reforçar-antes-de-criar). Floresta de teste manual (~100 nós, 10 galhos, ≥1 dataset SQLite). Telemetria (traces JSONL).

**Entregáveis:**
1. Repositório `vine/` com servidor MCP + suíte de testes.
2. Floresta de teste com Git próprio (`forests/forest-fixture/`, gerada por
   `forests/scripts/build_fixture.py`; florestas geradas não entram no repo).
3. CLI mínima: `vine serve`, `vine reindex`, `vine validate` (lint da floresta contra o schema).
4. Demo gravada: Qwen 7-14B Q4 respondendo 10 perguntas multi-hop com traces.

**Critérios de saída:** os 6 da Parte F da spec (contratos exatos, atomicidade com Git, orçamentos de token com truncamento explícito, segurança do `query`, demo com métricas, latências p95).

**Riscos da fase:** parser de frontmatter permissivo demais (rejeitar cedo é melhor que aceitar lixo); esquecimento da sincronia summary↔índice no `graft`.

---

## Fase 1 — Helicóptero Completo

**Objetivo:** ativar a camada vetorial do `locate` (dois níveis: galhos e bananas) e provar a tese central contra baselines.

**Escopo:**
- Embeddings dos summaries (bananas E galhos) com **bge-m3** (multilíngue PT/EN), truncamento Matryoshka 1024→256, **binary quantization + rescore top-100** com vetores full.
- Armazenamento: LanceDB embarcado (Apache 2.0) ou índice numpy próprio se <50k nós — decisão do time, a interface do `locate` não muda.
- RRF fundindo vetorial + BM25; feromônio no ranking (`α` configurável).
- Re-embedding lazy de nós stale (marcados por `plant`/`graft`).
- **Monkey Bench v1:** corpus de avaliação (sugestão: floresta gerada a partir de um domínio real + perguntas multi-hop estilo HotpotQA adaptadas), harness que roda agente + baselines, relatório automático.
- Baselines obrigatórios: (a) RAG top-k clássico (mesmo corpus em chunks + mesmo embedder), (b) RAG iterativo (agente com busca vetorial mas sem índices/grafo).

**Entregáveis:** Canopy v1 (módulo de embeddings + índice), Monkey Bench v1 (repo + relatório), comparativo MonkeyLLM × baselines.

**Critérios de saída:**
1. `locate` vetorial: recall@5 ≥ 0.85 nas perguntas do bench (resposta-alvo entre os 5 pontos de pouso).
2. MonkeyLLM ≥ baseline RAG em *banana precision* E ≤ 60% dos *tokens-to-banana* do RAG iterativo nas perguntas multi-hop. (Se falhar: investigar summaries antes de culpar a arquitetura — eles são o sistema.)
3. p95 do `locate` < 100ms com vetores ativos.
4. Pipeline de re-embedding lazy testado (graft → stale → busca reflete a mudança em < 60s).

**Riscos da fase:** vazamento de avaliação (perguntas do bench triviais demais ou que casam literalmente com summaries); comparação injusta com baseline (mesmo embedder e mesmo corpus são obrigatórios).

---

## Fase 1.5 — Tropa

**Objetivo:** caçada paralela por estigmergia intra-sessão (spec, Parte E).

**Escopo:** orquestrador asyncio; partição de fronteira via top-N do `locate`; `session_heat` com namespace; cache compartilhado de visitados; juiz agregador; conversão de heat apenas da trilha vencedora; servidor de inferência com continuous batching (vLLM ou llama.cpp parallel slots) na 3090.

**Entregáveis:** módulo `troop/` no orquestrador + extensão do Monkey Bench (N como parâmetro).

**Critérios de saída:**
1. N=3 reduz o tempo de relógio mediano em ≥ 35% vs N=1 nas perguntas difíceis do bench (≥4 hops), com custo total de tokens ≤ 2.5×.
2. Zero duplicação de `look` na mesma sessão (cache de visitados verificado por trace).
3. Relatório do trade-off velocidade × custo por classe de pergunta (alimenta a decisão de tropa adaptativa na Fase 2).

---

## Fase 2 — Banco Vivo

**Objetivo:** o compounding: ingest automático, escrita pelo agente, feromônio de longo prazo, manutenção autônoma. É aqui que o MonkeyLLM deixa de ser um leitor esperto e vira memória que aprende.

**Escopo:**
- **Gardener v1 (ingest):** PDF/DOCX → markdown (docling ou marker); XLSX/CSV/JSON tabular → SQLite + passaporte com manual de consulta; geração de `summary` por SLM com validação contra A.4 (compute generoso — é offline); extração de entidades e arestas com `confidence` por origem; `payload_hash` e regeneração de passaporte em drift.
- **Ranger v1 (manutenção):** evaporação do heat (meia-vida configurável); promoção/poda de atalhos e propostas (reuso confirma, abandono poda); detecção de `needs_split` e split assistido de galhos; lint contínuo (links quebrados, summaries fora do padrão, índices dessincronizados); blocking de candidatos a `same-as` por similaridade de embedding (fusão física = compaction, ainda manual/aprovada).
- **Compounding loop fechado:** sessões de caçada gravam aprendizado (fortificação, atalhos, propostas) e o bench mede a convergência.
- Tropa adaptativa (opcional, se os dados da 1.5 justificarem): começa com 1 macaco, recruta se a fronteira estagnar.

**Entregáveis:** `gardener/`, `ranger/`, Monkey Bench v2 (medição longitudinal), floresta real ingerida (dogfooding: as notas e documentos do próprio projeto).

**Critérios de saída:**
1. Ingest end-to-end: 100 documentos mistos (PDF/DOCX/XLSX/MD) entram sem intervenção manual, com ≥ 95% dos summaries passando na validação A.4 e zero links quebrados pós-ingest.
2. **Curva de convergência:** sobre um conjunto fixo de perguntas recorrentes, hops-to-banana médio cai ≥ 25% após 2 semanas de uso simulado (o gráfico-assinatura do paper).
3. Ranger roda como serviço: evaporação e poda verificadas por teste de longo prazo acelerado (clock sintético).
4. Nenhuma degradação dos índices auditada por humano em revisão amostral (a poluição está contida).

**Riscos da fase:** summaries de ingest piores que os manuais (medir separadamente!); `same-as` fundindo entidades distintas (por isso fusão física fica atrás de aprovação); florestas de dogfooding pequenas demais para a curva de convergência aparecer.

---

## Fase 3 — Motor Próprio (CONDICIONAL)

**Gatilho — esta fase só existe se a telemetria mostrar pelo menos um destes:**
- p95 de `locate`/`scan` estourando os orçamentos com a floresta alvo (>100k nós);
- custo de serialização/IPC entre componentes Python dominando o caminho de leitura;
- fila única de escrita virando gargalo real (medido, não imaginado).

**Escopo (se disparado):** reescrita dirigida por perfil — primeiro o componente que o profiling apontar (provavelmente Catálogo+Canopy como uma lib Rust com bindings Python via PyO3; o Vine/MCP e o orquestrador permanecem em Python). Nunca reescrita big-bang.

**Critério de saída:** os mesmos benchmarks das fases anteriores, com os orçamentos restaurados e zero regressão de contrato (a spec v0.1 é a verdade; clientes não percebem a troca de motor).

**Anti-padrão proibido:** começar a Fase 3 "porque Rust é mais rápido". A tabela de latência (arquitetura, seção 11) mostra que o SLM domina o custo; Rust entra para resolver gargalos medidos de storage/índice, não para acelerar o que a GPU limita.

---

## Fase 4 — Produto & Paper (paralela às fases 2-3)

**Trilha paper:**
- Tese: navegação hierárquica por índices auto-descritivos + estigmergia supera RAG plano em eficiência e converge com o uso.
- Resultados-chave: (1) tabela MonkeyLLM × RAG × GraphRAG × RAPTOR (precision, hops, tokens); (2) curva de convergência (Fase 2); (3) trade-off da Tropa (Fase 1.5).
- Glossário bilíngue: termos lúdicos apresentados uma vez ao lado do termo técnico — *shortcut grafting (the "shout")*, *session-scoped pheromone (the "whisper")*, *troop (parallel foragers)* — depois uso livre.
- Related work a posicionar: RAG, GraphRAG (Microsoft), RAPTOR, MemGPT/Letta, stigmergy/ACO (Grassé; Dorigo), Hebbian learning, spreading activation.

**Trilha produto (monkeyllm.com):**
- Distribuição: Docker Compose (vine + gardener + ranger) com volume local e espelho R2 opcional; instalação `pip install monkeyllm` para o modo embarcado.
- Compatibilidade Obsidian como feature de marketing: "sua floresta é um vault".
- O servidor MCP é o produto de entrada: qualquer Claude/cliente MCP pluga a floresta como memória.

---

## Mapa de dependências

```
Fase 0 ──→ Fase 1 ──→ Fase 1.5 ──→ Fase 2 ──→ (Fase 3 se medições exigirem)
                │                      │
                └──────→ Fase 4 (paper/produto, em paralelo a partir da 1)
```

## Princípios que valem em todas as fases

1. **A spec é a verdade.** Mudança de contrato = nova versão da spec antes do código.
2. **Summaries são o sistema.** Qualquer queda de qualidade de navegação: investigar summaries primeiro.
3. **Truncamento sempre explícito.** O agente nunca recebe resposta cortada em silêncio.
4. **Arquivos são o banco.** Tudo em `_derived/` é descartável e reconstruível por `vine reindex`.
5. **Medir antes de otimizar.** O Monkey Bench decide as brigas de engenharia.
