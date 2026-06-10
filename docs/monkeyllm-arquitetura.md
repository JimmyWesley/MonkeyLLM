# MonkeyLLM — Arquitetura de Banco de Conhecimento Navegável por Agentes

**Domínio:** monkeyllm.com
**Conceito:** Um sistema de memória para LLMs onde o conhecimento vive em arquivos markdown organizados como uma floresta hierárquica de índices. O agente (macaco) não varre a floresta: ele lê índices (galhos), salta entre nós (hops) e coleta apenas a informação-alvo (bananas).
**Tese central:** Navegação hierárquica por índices pré-computados supera busca vetorial plana (RAG) em eficiência de contexto, número de operações e acurácia em perguntas multi-hop.

---

## 1. Vocabulário do Projeto

| Termo MonkeyLLM | Significado técnico |
|---|---|
| **Floresta** | O corpus completo (volume Docker ou bucket S3/R2) |
| **Galho** | Arquivo de índice (`_index.md`) de uma pasta |
| **Galho-mestre** | Índice raiz da floresta (`/_index.md`) — visão do alto da árvore |
| **Banana** | Unidade atômica de conhecimento (um arquivo `.md` final) |
| **Hop** | Uma operação de navegação (abrir um índice ou seguir um link) |
| **Trilha** | Sequência de hops da raiz até a banana |
| **Cheiro** | Metadados/resumo que permitem decidir o próximo hop sem abrir o conteúdo |
| **Passaporte** | Arquivo `.md` irmão que representa um arquivo não-markdown (PDF, XLSX, SQLite, JSON) na floresta e ensina o agente a consultá-lo |
| **Feromônio (sussurro)** | Peso de calor em arestas/nós, reforçado por travessias bem-sucedidas, que reordena resultados; evapora com o tempo |
| **Grito (atalho)** | Wikilink lateral permanente criado pelo agente quando descobre uma banana valiosa por trilha longa |
| **Tropa** | N macacos caçando em paralelo, coordenados por feromônio de sessão (estigmergia intra-sessão) |
| **Catálogo** | SQLite em `_derived/` com o frontmatter de todos os nós, servindo consultas por metadados (`scan`) sem abrir arquivos |

Métricas do paper: **hops-to-banana** (quantos saltos até a resposta), **tokens-to-banana** (custo de contexto total da trilha), **banana precision** (a banana coletada respondia a pergunta?).

---

## 2. Princípios de Design

1. **Files are the database.** A verdade canônica são arquivos markdown puros. Qualquer índice binário (vetores, grafo serializado) é camada derivada, descartável e reconstruível.
2. **Every folder is self-describing.** Toda pasta contém um `_index.md` que resume o que existe nela e para onde apontam os caminhos. Um agente que cai em qualquer pasta sabe onde está.
3. **Navigation over search.** Busca vetorial serve apenas para achar o ponto de entrada (teleporte). A partir dali, o agente navega pela estrutura, como um humano navega uma wiki.
4. **Token-frugal by design.** Cada arquivo de índice é otimizado para máxima informação de roteamento por token. O agente decide o próximo hop lendo ~200-500 tokens, nunca lendo conteúdo bruto.
5. **Human-compatible.** Tudo abre no Obsidian, no VS Code, no GitHub. Humanos e agentes editam o mesmo substrato.
6. **Git-native.** O compounding knowledge é auditável: cada escrita do agente é um commit. Merge de entidades, correções e decay têm histórico.

---

## 3. Estrutura da Floresta (Layout Físico)

```
floresta/
├── _index.md                  # Galho-mestre: mapa global, regiões, landmarks
├── _meta/
│   ├── schema.md              # Tipos de nós e arestas válidos (o "dialeto" da floresta)
│   ├── aliases.md             # Tabela de resolução de entidades (Apple = Apple Inc)
│   └── stats.md               # Contagens, datas, saúde dos índices
├── _derived/                  # Camada derivada (NUNCA é fonte de verdade)
│   ├── embeddings.lance/      # Vetores dos digests (opcional, reconstruível)
│   ├── graph.cache.json       # Grafo de links materializado
│   └── lexical.idx/           # Índice BM25/FTS (opcional)
├── pessoas/
│   ├── _index.md              # Galho: lista digests de cada pessoa + links cruzados
│   ├── jimmy-wesley.md
│   └── ...
├── projetos/
│   ├── _index.md
│   ├── mixerllm/
│   │   ├── _index.md          # Sub-galho: arquitetura, decisões, experimentos
│   │   ├── arquitetura.md
│   │   └── decisoes/
│   │       ├── _index.md
│   │       └── 2026-03-mixer-lang-v2.md
│   └── monkeyllm/
└── conceitos/
    ├── _index.md
    └── ...
```

Regras:
- Profundidade máxima recomendada: **4 níveis** (mantém qualquer trilha em ≤5 hops).
- Uma pasta "explode" (ganha subpastas) quando seu `_index.md` ultrapassa ~150 entradas ou ~3k tokens — análogo ao split de página em B-tree, mas guiado por semântica.
- Nomes de arquivo são slugs estáveis (`jimmy-wesley.md`), nunca renomeados; títulos mudam no frontmatter.

---

## 4. Anatomia dos Arquivos

### 4.1 Banana (arquivo de conhecimento)

```markdown
---
id: mixerllm-arquitetura          # identidade estável (slug)
type: documento-tecnico            # tipo do schema.md
title: Arquitetura do MixerLLM
summary: >                         # O CHEIRO — 1-3 frases, decide hops
  Arquitetura de inferência com modelo quente e frio colaborando
  via linguagem simbólica comprimida (mixer-lang), com block-loop
  e delegação inversa.
tags: [inferencia, slm, arquitetura]
links:
  - rel: parte-de
    target: projetos/mixerllm
  - rel: comparado-com
    target: conceitos/speculative-decoding
  - rel: autor
    target: pessoas/jimmy-wesley
created: 2026-06-10
updated: 2026-06-10
confidence: 1.0                    # para compounding: conhecimento incerto < 1.0
source: manual                     # manual | ingest | agente
---

# Arquitetura do MixerLLM

(conteúdo completo aqui — o agente SÓ lê isto depois de decidir
que esta é a banana certa)

## Relações
- Parte de [[projetos/mixerllm/_index]]
- Contrasta com [[conceitos/speculative-decoding]]
```

O frontmatter YAML é a interface máquina; o corpo é a interface humano/LLM. `summary` é o campo mais importante do sistema inteiro: é ele que o índice replica e é nele que a navegação se apoia.

### 4.2 Galho (`_index.md`)

```markdown
---
id: projetos/_index
type: galho
coverage: 12 bananas, 3 sub-galhos
updated: 2026-06-10
---

# Projetos

> Projetos técnicos ativos e arquivados. Para pessoas envolvidas,
> ver [[pessoas/_index]]. Para fundamentos teóricos, [[conceitos/_index]].

## Sub-galhos
- [[mixerllm/_index]] — Arquitetura de inferência hot/cold com
  mixer-lang. 8 bananas. Ativo.
- [[monkeyllm/_index]] — Banco de conhecimento navegável (este
  sistema). 4 bananas. Ativo.

## Bananas diretas
- [[pipeline-audio]] — Pipeline de transcrição/diarização na 3090;
  migração pyannote → NeMo Sortformer. Concluído.

## Trilhas cruzadas (links laterais)
- Inferência local e quantização → [[conceitos/quantizacao]]
- Hardware de referência → [[infra/workstation-3090]]
```

Três seções fixas: **sub-galhos** (descida), **bananas diretas** (folhas), **trilhas cruzadas** (atalhos laterais — é isso que transforma a árvore em grafo e reduz hops drasticamente).

### 4.3 Galho-mestre (`/_index.md`)

Igual ao galho, mas inclui:
- **Landmarks:** os 10-20 nós de maior grau/importância da floresta, com digest — pontos de entrada diretos sem descer a hierarquia.
- **Mapa de regiões:** uma frase por pasta de topo.
- **Convenções:** link para `_meta/schema.md` para o agente aprender o dialeto em 1 hop.

---

### 4.4 Passaporte (arquivos heterogêneos)

A floresta aceita qualquer formato, mas **nenhum arquivo entra sem passaporte**: um `.md` irmão que é o nó oficial daquele arquivo no grafo. O agente sempre toca o passaporte primeiro; o arquivo nativo é carga útil.

Regras de conversão no ingest (Gardener):

| Formato de origem | Tratamento | O agente consome via |
|---|---|---|
| PDF, DOCX | Convertido para `.md` (corpo vira a banana); original preservado em `_assets/` | `pick()` |
| XLSX, CSV, JSON tabular | Convertido para **SQLite** (`.db`, arquivo único, consultável); passaporte contém o manual de consulta | `query()` |
| JSON hierárquico pequeno | Embutido no corpo do passaporte como bloco de código | `pick()` |
| Imagens, áudio | Passaporte com descrição/transcrição gerada no ingest | `pick()` |

Exemplo de passaporte de planilha:

```markdown
---
id: vendas/relatorio-q1-2026
type: dataset
title: Relatório de Vendas Q1 2026
summary: >
  Vendas por região e produto, jan-mar 2026. 14.302 linhas.
  Inclui SKU, margem e canal. Fonte: ERP, export manual.
payload: relatorio-q1-2026.db        # SQLite irmão
payload_type: sqlite
links:
  - rel: parte-de
    target: vendas/_index
  - rel: relacionado-com
    target: produtos/_index
---

# Relatório de Vendas Q1 2026

## Manual de consulta
**Tabelas:** `vendas(data, sku, produto, regiao, canal, qtd, valor, margem)`

**Colunas-chave:** `sku` cruza com [[produtos/_index]]; `regiao` usa
nomes IBGE; `valor` em BRL.

**Queries de exemplo:**
- Total por região: `SELECT regiao, SUM(valor) FROM vendas GROUP BY regiao;`
- Top 10 SKUs por margem: `SELECT sku, SUM(margem) m FROM vendas GROUP BY sku ORDER BY m DESC LIMIT 10;`

**Amostra (3 linhas):**
| data | sku | produto | regiao | valor |
|---|---|---|---|---|
| 2026-01-05 | A-101 | Sensor X | Sudeste | 1.250,00 |
| ... | | | | |
```

Princípio: **tabela não vira texto — tabela vira banco consultável.** O agente nunca carrega 14 mil linhas no contexto; ele lê o manual (1 hop, ~400 tokens) e pergunta à planilha com SQL (1 query, ~50 tokens de resposta). Isso é o que torna o sistema viável para dados tabulares grandes, onde RAG por chunking falha estruturalmente.



```
┌─────────────────────────────────────────────────┐
│  L4 · AGENTE NAVEGADOR (o Macaco)               │
│  SLM (Qwen 7-14B Q4/Q5) com 3 primitivas        │
├─────────────────────────────────────────────────┤
│  L3 · PROTOCOLO DE NAVEGAÇÃO (MCP server)       │
│  locate() · look() · move() · pick() · query()  │
│  plant() · graft()                              │
├─────────────────────────────────────────────────┤
│  L2 · CAMADA DERIVADA (aceleração, descartável) │
│  embeddings (locate) · BM25 (locate exato)      │
│  grafo materializado (move barato)              │
├─────────────────────────────────────────────────┤
│  L1 · ÍNDICES SEMÂNTICOS (_index.md)            │
│  mantidos pelo Jardineiro (pipeline de ingest)  │
├─────────────────────────────────────────────────┤
│  L0 · FLORESTA (markdown + frontmatter + links) │
│  volume Docker local ←sync assíncrono→ S3/R2    │
└─────────────────────────────────────────────────┘
```

A regra de ouro: **L0 e L1 são o produto. L2 é cache. L3 é a interface. L4 é o usuário.** Se você apagar L2 inteira, o sistema continua funcional (mais lento no `locate`, idêntico no resto). Isso é o que diferencia MonkeyLLM de um banco vetorial: o RAG sem índice vetorial morre; o MonkeyLLM sem índice vetorial vira uma wiki — que ainda navega.

---

## 6. As Primitivas do Protocolo (L3)

Expostas como ferramentas MCP. Assinaturas conceituais:

### `locate(query, k=5) → [pontos_de_entrada]`
O **helicóptero**: o macaco nunca parte do tronco — é largado na região mais próxima do alvo. Funde busca vetorial (digests) + BM25 (termos exatos, IDs, SKUs) via RRF, em **dois níveis**: bananas (folhas) e galhos (zonas de pouso — para perguntas amplas, pousar na região certa e navegar localmente supera cair numa folha errada). Retorna id, trilha, summary e score de cada candidato. **Único lugar do sistema onde vetores existem.**

### `look(id) → digest`
A operação mais usada. Retorna, em formato compacto:
frontmatter + seções do índice (se galho) ou frontmatter + outline de headers (se banana) + vizinhança de 1 hop com labels. Custo alvo: **≤500 tokens**. Nunca retorna corpo completo.

### `move(id, rel?) → [vizinhos]`
Navegação estrutural: filhos, pai, ou arestas de um tipo (`rel: comparado-com`). Sai do grafo materializado (L2) ou, sem cache, do parse dos links (L0).

### `pick(id, section?) → conteúdo`
Colhe a banana: retorna o corpo (ou só uma seção). O agente só chama `pick` quando o `summary` já indicou que é o alvo. A razão `pick/look` baixa é sinal de navegação eficiente.

### `query(id, sql) → linhas`
Consulta read-only a um payload SQLite (datasets tabulares). O agente aprende o schema pelo passaporte (`look`) e pergunta ao dado em vez de carregá-lo. Guard-rails: somente `SELECT`, `LIMIT` forçado (ex: 200 linhas), timeout de 2s. Resposta em tabela compacta.

### `plant(node) / graft(id, patch)` — escrita
Criar banana nova / editar existente. Toda escrita: (a) valida contra `schema.md`; (b) atualiza o `_index.md` da pasta; (c) registra commit Git; (d) marca embeddings derivados como stale. Merge de entidades é **soft**: aresta `same_as` + entrada em `aliases.md`; compaction periódica funde fisicamente.

---

## 7. Componentes de Software (o que construir)

| # | Componente | Papel | Stack sugerido (v1) |
|---|---|---|---|
| 1 | **Forest Spec** | Especificação formal do layout, frontmatter, schema de links | Documento (este + schema.md) |
| 2 | **Gardener (Jardineiro)** | Pipeline de ingest: parse (PDF/DOCX/MD → MD), chunking semântico, extração de entidades/relações via SLM, geração de summaries, atualização de índices | Python + Qwen quantizado na 3090; PDF via docling/marker |
| 3 | **Ranger (Guarda-florestal)** | Manutenção: detecta índices desatualizados, links quebrados, pastas que precisam explodir, candidatos a merge de entidades | Python, jobs periódicos |
| 4 | **Canopy (Copa)** | Camada derivada: embeddings (bge-m3, Matryoshka 1024→256, binary quantization + rescore), BM25 (Tantivy ou SQLite FTS5), grafo cache | Python; LanceDB embarcado (Apache 2.0, grátis) ou até numpy puro na v0 |
| 5 | **Vine (Cipó)** | Servidor MCP expondo as 6 primitivas | Python FastMCP (você já domina FastAPI) |
| 6 | **Monkey Bench** | Harness de avaliação: corpus + perguntas multi-hop + métricas (hops-to-banana, tokens-to-banana, precision) vs baseline RAG | Python |

Ordem de construção: **1 → 5 (com L2 vazio, navegação pura por arquivos) → 6 → 2 → 4 → 3.** Repare: o servidor MCP vem antes do pipeline de ingest — você valida a navegação numa floresta montada à mão (ex: seu próprio vault de notas) antes de automatizar a ingestão.

## 8. Deploy

```
┌────────────── Docker Compose ──────────────┐
│  vine (MCP server) ── volume: /floresta    │
│  gardener (ingest worker, GPU passthrough) │
│  ranger (cron)                             │
└──────────────┬─────────────────────────────┘
               │ rclone/litestream sync assíncrono
               ▼
        S3 / Cloudflare R2 (cold, backup, multi-device)
```

- Local-first: leitura/escrita sempre no volume local; R2 é espelho assíncrono (R2 tem egress zero, bom para multi-máquina).
- A pasta `_derived/` **não** sincroniza — cada nó reconstrói a própria copa.
- Git bare repo no volume = log de auditoria do compounding.

## 9. Roteiro de Validação (e do Paper)

**Fase 0 (1 semana):** Forest Spec + floresta de teste montada à mão (~100 bananas, 10 galhos). Vine com `look/move/pick` apenas (zero embeddings). Pergunta a responder: *um SLM navega só por índices?*

**Fase 1 (3-4 semanas):** `locate` com embeddings + BM25. Monkey Bench com 50-100 perguntas multi-hop. Baseline: RAG top-k clássico sobre o mesmo corpus. Hipótese do paper: **MonkeyLLM responde perguntas multi-hop com maior acurácia e menor custo de tokens que RAG plano.**

**Fase 2 (4-6 semanas):** Gardener — ingest automático de PDF/DOCX/MD. Medir qualidade dos summaries gerados pelo SLM (eles são o coração do sistema). Compounding: `plant/graft` + Git.

**Fase 3:** Se (e só se) o protocolo provar valor e o stack Python engasgar, reescrever Canopy/Vine em Rust — agora com requisitos medidos, não imaginados.

**Esqueleto do paper:** (1) problema: agentes desperdiçam contexto com RAG plano; (2) proposta: navegação hierárquica por índices auto-descritivos; (3) protocolo de 6 primitivas; (4) Monkey Bench vs RAG/GraphRAG; (5) métricas hops/tokens/precision; (6) compounding via filesystem versionado. Posicionamento contra: RAG clássico, GraphRAG (Microsoft), RAPTOR, MemGPT/Letta.

## 10. Trilhas de Feromônio — o Banco Vivo (Estigmergia)

O MonkeyLLM não é estático: ele **aprende com o próprio uso**. O mecanismo é estigmergia — comunicação indireta via ambiente, como trilhas de feromônio de formigas. Cada navegação bem-sucedida torna as próximas mais baratas. Dois mecanismos complementares:

### 10.1 Sussurro (feromônio — camada derivada, volátil)
- Cada travessia de aresta numa trilha que terminou em sucesso (a banana respondeu a pergunta) incrementa um peso `heat` na aresta e no nó destino.
- `heat` vive em `_derived/trails.db` (alta frequência de escrita; não polui o Git).
- Efeito: `locate()` e `look()` reordenam resultados por `score × f(heat)` — bananas e galhos quentes sobem no ranking.
- **Evaporação:** o Ranger aplica decaimento exponencial (ex: meia-vida de 30 dias). Sem evaporação, o sistema vicia em caminhos antigos e novas bananas nunca competem.

### 10.2 Grito (atalho — camada canônica, permanente)
- **Política: reforçar antes de criar.** Ao encontrar a banana, a cascata é: (1) atalho já existe na trilha? → fortifica (heat + confidence sobem, nada novo é criado); (2) não existe e a trilha foi longa (≥4 hops)? → `graft` cria o wikilink lateral (`rel: atalho-descoberto`, `confidence: 0.5`); (3) o macaco percebeu conexões laterais novas com sentido? → propõe `relacionado-com` com `confidence: 0.3`, que o Ranger confirma ou poda.
- O caso (1) é o caminho comum: o sistema converge para uma malha estável de atalhos fortificados, em vez de acumular links redundantes.
- Atalhos viram commit no Git → auditáveis, reversíveis, visíveis para humanos no Obsidian.
- O Ranger poda atalhos e propostas que nunca foram reutilizados.

### 10.3 Por que isso importa para o paper
Nem RAG, nem GraphRAG, nem RAPTOR melhoram com o uso — eles indexam uma vez e ficam parados. O MonkeyLLM converge: **hops-to-banana cai ao longo do tempo para distribuições de perguntas recorrentes.** Essa curva de convergência (hops médios por semana de uso) é um gráfico de resultado inédito e é a materialização do "compounding knowledge".

## 11. Orçamento de Latência

A latência por hop é dominada pela inferência do agente, não pelo storage — e o design explora isso:

| Operação | Custo típico (local, NVMe) |
|---|---|
| `look` / `move` / `pick` (leitura de arquivo) | < 1 ms |
| `query` (SQLite indexado) | 1–5 ms |
| `locate` (BQ + rescore + BM25 + RRF) | 5–15 ms |
| **Decisão de hop pelo SLM (Qwen 7-14B Q4, 3090)** | **100–500 ms** |

Conclusões de design que saem dessa tabela:
1. Otimizar storage abaixo de ~10ms é irrelevante; otimizar **número de hops** e **tokens por hop** é tudo. Feromônio, atalhos, digests ≤500 tokens e landmarks existem por isso.
2. Sync com S3/R2 jamais entra no caminho de leitura (é espelho assíncrono). Em deploy remoto-only, byte-range requests no R2 adicionam 30-80ms por hop — aceitável, mas o modo local-first continua sendo o alvo.
3. Meta de ponta a ponta: pergunta multi-hop respondida em **< 5 s** com SLM local (≈ 4-6 hops × decisão do SLM), contra dezenas de segundos de um agente RAG iterativo que carrega chunks gordos por rodada.

## 12. Riscos Conhecidos

1. **Qualidade dos summaries é o sistema inteiro.** Summary ruim = cheiro errado = macaco perdido. Mitigação: gastar compute generoso no ingest (é offline) e medir summaries no Monkey Bench.
2. **Índices desatualizados** (escrita sem atualizar `_index.md`). Mitigação: toda escrita passa por `plant/graft` (atualização atômica) + Ranger audita.
3. **Concorrência de escrita.** Filesystem não tem transação. Mitigação v1: fila única de escrita no Vine (um escritor, N leitores).
4. **Florestas gigantes (>100k bananas).** Índices em markdown podem não escalar. Resposta honesta: esse é exatamente o limite que o Monkey Bench vai revelar e que justificaria a Fase 3 (motor próprio). Não resolver antes de medir.
5. **Poluição de feromônio/atalhos.** Agente que "grita" demais enche os galhos de links laterais e degrada os índices. Mitigação: atalhos nascem com `confidence` baixa, exigem reuso para promoção, e o Ranger poda; evaporação garante que heat antigo não domine.
6. **Drift entre payload e passaporte.** A planilha muda e o manual de consulta fica velho. Mitigação: Gardener regenera passaporte ao detectar mudança de hash do payload.
