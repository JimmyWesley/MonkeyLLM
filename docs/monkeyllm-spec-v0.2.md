# MonkeyLLM Especificação Técnica v0.2 (Fase 0)

**Audiência:** time de desenvolvimento.
**Escopo:** especificação normativa do dialeto da floresta (`schema.md`), dos contratos de I/O das primitivas do protocolo Vine (MCP), e dos critérios de aceitação da Fase 0.
**Documento companheiro:** `monkeyllm-arquitetura.md` (visão arquitetural).
**Convenção:** as palavras DEVE, NÃO DEVE, PODE seguem o espírito do RFC 2119.

**Changelog v0.1 → v0.2:**

- Nova primitiva de leitura **C.6b `sniff`** (o farejador): busca literal sobre os **corpos** dos nós, devolvendo nó + seção + trecho. Complementa o `locate` (que continua restrito a metadados curados contrato C.1 intacto) cobrindo o caso "termo exato enterrado no corpo, invisível para summary/tags".
- **A.3.1 Política de payloads binários**: binário nunca entra no Git da floresta Vine versiona somente `.md` (guarda na camada de commit); payloads são referenciados por `payload` + `payload_hash` e excluídos pelo `.gitignore` da floresta.
- Critério de aceitação F.1 atualizado para incluir C.6b; novos critérios F.7 (qualidade do sniff) e F.8 (payloads fora do Git).
- Nada mais muda: todos os demais contratos são idênticos à v0.1 (que permanece arquivada para histórico).

---

## Parte A O Dialeto da Floresta (`_meta/schema.md`)

O `schema.md` é um arquivo vivo dentro da floresta que declara os tipos válidos. O Vine DEVE validar toda escrita (`plant`/`graft`) contra ele. O agente PODE lê-lo via `look("_meta/schema")` para aprender o dialeto em 1 hop.

### A.1 Tipos de nó (`type`)

| `type` | Descrição | Payload | Verbo de colheita |
|---|---|---|---|
| `galho` | Arquivo de índice (`_index.md`) de uma pasta | | `look` |
| `nota` | Conhecimento em texto livre (banana padrão) | | `pick` |
| `documento` | Documento convertido (origem PDF/DOCX) | original em `_assets/` | `pick` |
| `dataset` | Dados tabulares | SQLite irmão (`.db`) | `query` |
| `entidade` | Pessoa, organização, produto, lugar (subtipo em `entity_kind`) | | `pick` |
| `conceito` | Definição/termo técnico | | `pick` |
| `evento` | Fato datado (reunião, decisão, release) | | `pick` |
| `midia` | Imagem/áudio/vídeo com descrição ou transcrição | original em `_assets/` | `pick` |

Regras:
- Novos tipos DEVEM ser adicionados ao `schema.md` antes do primeiro uso; o Vine rejeita `type` desconhecido (erro `E_SCHEMA`).
- `entidade` DEVE ter `entity_kind` ∈ {`pessoa`, `organizacao`, `produto`, `lugar`, `outro`}.

### A.2 Tipos de aresta (`rel`)

Arestas são direcionadas, tipadas, e declaradas no frontmatter (`links:`) do nó de origem. A camada derivada materializa as inversas automaticamente.

| `rel` | Inversa (derivada) | Semântica |
|---|---|---|
| `parte-de` | `contem` | Hierarquia lógica (não confundir com a hierarquia física de pastas) |
| `relacionado-com` | `relacionado-com` | Associação genérica (simétrica) |
| `mencionado-em` | `menciona` | Entidade citada em documento |
| `autor` | `autor-de` | Autoria |
| `comparado-com` | `comparado-com` | Contraste técnico (simétrica) |
| `derivado-de` | `origem-de` | Proveniência (nota derivada de documento, dataset de export, etc.) |
| `same-as` | `same-as` | **Soft merge** de entidades duplicadas (simétrica) |
| `atalho-descoberto` | | Grito do macaco (criado por `graft`, ver Parte C.8) |
| `sucede` | `precede` | Ordem temporal entre eventos/versões |

Regras:
- `rel` fora desta tabela → erro `E_SCHEMA` (a tabela cresce via edição do `schema.md`, nunca ad-hoc).
- `same-as` NÃO DEVE apagar nós; a fusão física é responsabilidade exclusiva da compaction do Ranger (fora do escopo da Fase 0).
- Máximo de 50 `links` por nó; acima disso o nó é candidato a virar galho (sinal para o Ranger).

### A.3 Frontmatter normativo

Campos obrigatórios em **todo** nó:

```yaml
id: string            # slug estável, único na floresta, = caminho relativo sem .md
type: string          # um dos tipos da A.1
title: string         # título humano (mutável; id nunca muda)
summary: string       # 1-3 frases, ≤ 60 tokens. O CHEIRO. Ver A.4.
created: date         # ISO 8601
updated: date         # ISO 8601, atualizado em todo graft
```

Campos opcionais:

```yaml
tags: [string]            # vocabulário livre, minúsculas, sem acento
links: [{rel, target}]    # arestas tipadas (A.2)
confidence: float         # 0.0-1.0; default 1.0; <1.0 = conhecimento não confirmado
source: enum              # manual | ingest | agente
payload: string           # nome do arquivo irmão (datasets/midia)
payload_type: enum        # sqlite | pdf | docx | image | audio
payload_hash: string      # sha256 do payload (detecção de drift)
entity_kind: enum         # somente para type: entidade
aliases: [string]         # nomes alternativos (usados pelo locate léxico)
```

Regras:
- `id` é imutável. Renomear = criar novo nó + `same-as` + tombstone (fora do escopo Fase 0; na Fase 0, renomear é proibido).
- Parser DEVE rejeitar frontmatter inválido com `E_FRONTMATTER` e caminho do campo.

#### A.3.1 Política de payloads binários (v0.2)

Binário **nunca entra no Git da floresta**. Normativo:

1. O Vine NÃO DEVE versionar nada além de `.md`: `plant`/`graft` adicionam ao stage somente arquivos markdown (guarda dura na camada de commit, não convenção).
2. O `.gitignore` da floresta DEVE excluir payloads binários (`*.db`, `*.sqlite`, `_assets/`), além de `_derived/` e `.vine.lock`.
3. O payload vive no filesystem ao lado do nó (ou em storage externo, em fases futuras) e o **nó** versiona apenas a referência: `payload` (nome) + `payload_hash` (sha256). Drift do binário é detectado por hash, não por diff.
4. Racional: Git delta-comprime texto, não binário payloads atualizados com frequência estourariam o repositório. O conhecimento versionado é a camada destilada (markdown); o dado pesado é referenciado, não embarcado.

### A.4 Especificação do `summary` (o componente mais crítico)

O `summary` DEVE permitir que um SLM decida "este nó me interessa?" sem abrir o corpo. Formato normativo:

1. **Frase 1:** o que é (categoria + assunto). 
2. **Frase 2:** diferencial/conteúdo-chave (números, nomes, escopo temporal).
3. **Frase 3 (opcional):** o que NÃO está aqui / onde está o complemento.

- Limite: 60 tokens (validado pelo Vine no `plant`).
- PROIBIDO: "Este documento descreve...", "Arquivo contendo..." (anti-padrões que gastam tokens sem cheiro).
- Bom: `"Vendas por região e SKU, jan-mar 2026, 14.302 linhas com margem e canal. Não inclui devoluções (ver vendas/devolucoes-q1)."`

### A.5 Especificação do `_index.md` (galho)

Estrutura obrigatória, nesta ordem:

```markdown
---
id: <pasta>/_index
type: galho
coverage: "N bananas, M sub-galhos"
updated: <data>
---

# <Título da região>

> <1-2 frases: o que vive aqui + para onde ir se não for aqui>

## Sub-galhos
- [[<id>]] <summary do sub-galho>. <coverage>.

## Bananas diretas
- [[<id>]] <summary copiado do frontmatter da banana>

## Trilhas cruzadas
- <motivo> → [[<id>]]
```

Regras:
- As entradas replicam o `summary` dos nós filhos VERBATIM (o Gardener/Vine mantém a sincronia; humanos não editam essas linhas à mão).
- Galho com > 150 entradas ou > 3.000 tokens → flag `needs_split` para o Ranger.
- O galho-mestre (`/_index.md`) DEVE conter adicionalmente a seção `## Landmarks` (10-20 nós de maior grau, com summary).

---

## Parte B Identidade, Trilha e Endereçamento

- **ID canônico:** caminho relativo à raiz, sem extensão. Ex: `projetos/mixerllm/arquitetura`.
- **Trilha:** lista de IDs da raiz até o nó. Ex: `["_index", "projetos/_index", "projetos/mixerllm/_index", "projetos/mixerllm/arquitetura"]`.
- Wikilinks no corpo usam `[[id]]` ou `[[id|texto]]`. O parser resolve `[[...]]` apenas contra IDs canônicos (sem fuzzy match ambiguidade é erro de lint do Ranger, não adivinhação do runtime).

---

## Parte C Contratos das Primitivas (servidor Vine, MCP)

Transporte: MCP (stdio para dev; HTTP/SSE no Docker). Todas as respostas em JSON. Erros seguem `{error: {code, message, hint}}` com códigos `E_NOT_FOUND`, `E_SCHEMA`, `E_FRONTMATTER`, `E_READONLY`, `E_QUERY_FORBIDDEN`, `E_TIMEOUT`, `E_LOCKED`.

Princípio transversal: **toda resposta DEVE caber no orçamento de tokens declarado**. O Vine trunca com marcador explícito `"truncated": true` nunca silenciosamente.

### C.1 `locate(query: string, k: int = 5, scope: "all"|"branches"|"bananas" = "all", type_filter?: string) → LocateResult`

O **helicóptero**: motor de localização que larga o macaco na região mais próxima do alvo ele nunca parte do tronco. Fusão RRF de busca vetorial (sobre summaries) + BM25 (sobre title, aliases, tags, summary). Na Fase 0, PODE ser somente BM25 (SQLite FTS5); a interface não muda quando vetores entrarem.

O índice cobre **dois níveis**: bananas (folhas) e galhos (regiões todo galho tem summary próprio, logo é indexável). Resultado de galho = **zona de pouso**: o macaco aterrissa na região certa e navega 1-2 hops com contexto local, em vez de cair numa folha possivelmente errada. `scope: "branches"` é útil para perguntas amplas ("o que sabemos sobre vendas?"); `scope: "bananas"` para perguntas pontuais.

```json
{
  "results": [
    {
      "id": "vendas/_index",
      "kind": "branch",
      "type": "galho",
      "title": "Vendas",
      "summary": "...",
      "trail": ["_index"],
      "coverage": "23 bananas, 4 sub-galhos",
      "score": 0.91,
      "heat": 0.40
    },
    {
      "id": "projetos/mixerllm/arquitetura",
      "kind": "banana",
      "type": "documento",
      "title": "Arquitetura do MixerLLM",
      "summary": "...",
      "trail": ["_index", "projetos/_index", "projetos/mixerllm/_index"],
      "score": 0.82,
      "heat": 0.31
    }
  ],
  "truncated": false
}
```

Orçamento: ≤ 800 tokens. Ordenação: `score_final = rrf_score × (1 + α·heat)`, α default 0.3 (configurável; α=0 desliga feromônio).

### C.2 `look(id: string, fields?: [string]) → Digest`

A operação central. Orçamento rígido: **≤ 500 tokens**.

`fields` (opcional): lista de campos desejados (ex: `["summary", "edges_out"]`). Quando presente, a resposta contém SOMENTE esses campos (+ `id`, sempre). Uso típico: macaco em modo varredura pedindo só `summary` de vários nós custo cai de ~400 para ~70 tokens por look.

Resposta para **banana** (`nota`/`documento`/`conceito`/`entidade`/`evento`):

```json
{
  "id": "projetos/mixerllm/arquitetura",
  "type": "documento",
  "title": "Arquitetura do MixerLLM",
  "summary": "...",
  "tags": ["inferencia", "slm"],
  "confidence": 1.0,
  "updated": "2026-06-10",
  "outline": ["Visão geral", "Mixer-lang", "Block-loop", "Benchmarks"],
  "edges_out": [
    {"rel": "parte-de", "target": "projetos/mixerllm/_index", "target_summary": "..."},
    {"rel": "comparado-com", "target": "conceitos/speculative-decoding", "target_summary": "..."}
  ],
  "edges_in": [
    {"rel": "menciona", "source": "pessoas/jimmy-wesley"}
  ],
  "stats": {"body_tokens": 2840, "degree": 7, "heat": 0.45}
}
```

Resposta para **galho**: substitui `outline` por `children` (sub-galhos e bananas diretas, cada um com `id` + `summary`) e `cross_trails`.

Resposta para **dataset**: inclui `query_manual` (tabelas, colunas-chave, 2-3 example_queries) e `sample_rows` (≤ 3 linhas). 

Regras:
- `edges_out`/`edges_in` limitados a 12 cada, ordenados por heat desc; excedente indicado em `stats.degree`.
- `target_summary` DEVE vir truncado a 25 tokens (é cheiro de vizinho, não digest completo).
- `body_tokens` permite ao agente estimar o custo de um `pick` antes de fazê-lo.

### C.3 `move(id: string, rel?: string, direction: "out"|"in"|"both" = "out") → [Neighbor]`

```json
{
  "neighbors": [
    {"id": "...", "rel": "comparado-com", "direction": "out", "type": "conceito", "summary": "...", "heat": 0.1}
  ],
  "truncated": false
}
```

Sem `rel`: todos os vizinhos. Orçamento: ≤ 600 tokens. `move(id, "children")` é açúcar para filhos físicos de um galho.

### C.4 `pick(id: string, section?: string) → Content`

```json
{
  "id": "...",
  "title": "...",
  "section": "Mixer-lang",
  "body": "<markdown da seção ou do corpo inteiro>",
  "body_tokens": 612,
  "truncated": false
}
```

- `section` casa contra os headers do `outline` (case-insensitive, match exato primeiro, depois prefixo).
- Corpo > 4.000 tokens sem `section` → retorna somente o outline expandido + `truncated: true` + hint `"use section="`. (Força o agente a colher a seção, não a árvore inteira.)

### C.5 `query(id: string, sql: string) → Rows`

- Pré-condições: nó `type: dataset`, `payload_type: sqlite`.
- Validação: somente um statement; DEVE começar com `SELECT` ou `WITH`; proibidos `ATTACH`, `PRAGMA` de escrita, `INSERT/UPDATE/DELETE/DROP/ALTER` → `E_QUERY_FORBIDDEN`. Conexão aberta em modo read-only (`mode=ro`).
- `LIMIT` forçado: se ausente, injeta `LIMIT 200`. Timeout 2s → `E_TIMEOUT`.

```json
{
  "columns": ["regiao", "total"],
  "rows": [["Sudeste", 1250000.0], ["Sul", 740000.0]],
  "row_count": 5,
  "limited": false,
  "elapsed_ms": 3
}
```

Formato colunar (`columns` + `rows` como arrays) não objetos repetindo as chaves; economiza ~40% dos tokens.

### C.6 `scan(parent_id: string, filter?: Filter, fields?: [string], recursive: bool = false, limit: int = 50) → [PartialNode]`

Consulta por **metadados** sobre os filhos de um galho, sem abrir arquivo nenhum. Servida pelo **Catálogo** (ver C.6.1).

`Filter` suporta igualdade e comparação sobre campos do frontmatter:

```json
{
  "parent_id": "projetos/_index",
  "filter": {"type": "dataset", "updated_after": "2026-03-01", "tags_any": ["vendas"]},
  "fields": ["id", "summary", "payload_type"],
  "recursive": true
}
```

Resposta: lista de nós parciais (somente os `fields` pedidos), ordenada por `heat` desc. Orçamento: ≤ 800 tokens, com `truncated` explícito.

Caso de uso canônico: "quero só os datasets sobre vendas atualizados este trimestre" → 1 chamada, ~3ms, ~200 tokens em vez de descer a hierarquia abrindo índices.

#### C.6.1 O Catálogo (`_derived/catalog.db`)

SQLite na camada derivada com uma linha por nó da floresta: todos os campos do frontmatter + trilha + degree + heat. Reconstruível do zero por varredura completa (`vine reindex`); atualizado incrementalmente a cada `plant`/`graft`. É o que serve `scan()` e o lado léxico do `locate` (FTS5 sobre title/aliases/tags/summary na mesma base). **Não é fonte de verdade** se divergir dos arquivos, os arquivos mandam e o catálogo se reconstrói.

### C.6b `sniff(terms: string | [string], scope?: string, k: int = 5, type_filter?: string) → SniffResult`

O **farejador** (sniper): busca **literal** sobre os corpos markdown dos nós, devolvendo nó + seção + trecho da ocorrência. É o complemento do `locate`: o helicóptero voa sobre metadados curados (summary/tags/title); o farejador desce ao chão e segue o rastro de um termo exato código de erro, nome próprio, número de NF, identificador que ninguém teve o cuidado (nem a obrigação) de subir para o summary. A divisão de contrato é normativa: **`locate` NÃO DEVE indexar corpos; `sniff` NÃO DEVE consultar metadados curados** (exceto para exibição do resultado).

Parâmetros:

- `terms`: 1 a 8 termos **literais** (string única é promovida a lista de 1). Casamento por substring, insensível a caixa e a diacríticos (NFD, remoção de combining marks). Termo com espaço = frase exata. Termo normalizado com < 2 caracteres → `E_SCHEMA`. **Regex NÃO é aceita** (Fase 0): SLMs escrevem regex frágil e regex arbitrária abre custo imprevisível; termos literais dão 95% do valor com contrato simples.
- `scope` (opcional): id de **qualquer nó**. Galho (`vendas/_index` ou `vendas`) restringe a busca à subárvore física correspondente; banana restringe ao corpo daquele único nó (grep-dentro-do-nó o encadeamento natural depois de um `locate`/`look` que já achou o alvo). Sem `scope`, floresta inteira. Nó inexistente → `E_NOT_FOUND`.
- `k`: máximo de nós no resultado (default 5, teto 20).
- `type_filter`: como no `locate`.

Semântica de busca:

- Varre **somente o corpo** dos arquivos `.md` (frontmatter excluído; `_derived`, `_assets` e payloads binários ignorados).
- Um nó casa quando **pelo menos um** termo ocorre no corpo; nós que casam **mais termos distintos** vêm primeiro (AND-preferido, OR-tolerante).
- `match` = linha da ocorrência, atribuída à seção (header H2/H3) que a contém. Máximo de **3 matches por nó** na resposta (`match_count` informa o total; excedente sinalizado por `truncated_matches: true`).
- `snippet` = janela da linha centrada na primeira ocorrência, truncada a ~25 tokens.

Ordenação (mesma fórmula de feromônio do C.1): `score = strength × (1 + α·heat)`, onde `strength = termos_casados/termos_pedidos`, desempate por `match_count`.

```json
{
  "results": [
    {
      "id": "vendas/politica-trocas",
      "type": "nota",
      "title": "Política de trocas",
      "trail": ["_index", "vendas/_index"],
      "score": 0.95,
      "heat": 0.31,
      "match_count": 4,
      "truncated_matches": true,
      "matches": [
        {"section": "Prazos", "line": 23, "snippet": "…devolução com NF-4412 em até 30 dias…"}
      ]
    }
  ],
  "scanned_nodes": 82,
  "truncated": false
}
```

Orçamento: ≤ 800 tokens, truncamento explícito (`truncated: true`) cortando nós do fim da lista.

Uso canônico (decisão do macaco, ensinada no system prompt do orquestrador):

1. Pergunta contém termo exato/raro → `sniff` direto: cai na seção certa e colhe com `pick(id, section)` derruba hops-to-banana.
2. Pergunta conceitual → `locate` (inalterado).
3. Encadeado: `locate` acha a região, `sniff(terms, scope=galho)` caça o trecho dentro dela.

Implementação Fase 0: varredura direta dos arquivos a cada chamada (grep-like, sem índice novo) sempre fresco por construção, sem estado derivado adicional. PODE ganhar índice (FTS5 de corpo em tabela separada) em fase futura **sem mudança de interface**, desde que a separação de contrato com o `locate` se mantenha.

### C.7 `plant(node: NodeSpec) → PlantResult`

`NodeSpec` = frontmatter completo + `body` + `parent` (id do galho destino).

Operação atômica (nesta ordem; falha em qualquer passo = rollback total):
1. Valida frontmatter contra schema (A.3) e `summary` (A.4);
2. Verifica unicidade do `id`;
3. Escreve o arquivo;
4. Insere a entrada no `## Bananas diretas` (ou `## Sub-galhos`) do `_index.md` pai;
5. `git commit` com mensagem padronizada `plant(<id>): <title> [source=<source>]`;
6. Marca o nó como stale na camada derivada (re-embedding lazy).

Retorno: `{id, commit, trail}`.

### C.8 `graft(id: string, patch: GraftPatch) → GraftResult`

`GraftPatch` suporta três operações (combináveis):
- `set_frontmatter: {campo: valor}` campos mutáveis apenas (`title`, `summary`, `tags`, `confidence`); `id`, `type`, `created` são imutáveis (`E_READONLY`);
- `add_links: [{rel, target}]` / `remove_links: [...]`;
- `append_section: {header, body}` ou `replace_section: {header, body}`.

Regras especiais:
- Mudança de `summary` propaga para todos os `_index.md` que o replicam (mesma transação).
- **Política reforçar-antes-de-criar (atalhos):** ao fim de uma caçada bem-sucedida, a cascata de decisão é: (1) se já existe atalho cobrindo a conexão entrada→banana na trilha, NÃO criar apenas incrementar `heat` e `confidence` do existente (fortificação, sem commit); (2) se não existe e a trilha foi ≥ 4 hops, `graft` de `atalho-descoberto` novo com `confidence: 0.5` e `discovered_by: agente`; (3) ligações laterais novas que o agente perceber (`relacionado-com` entre a banana e vizinhos semânticos) entram como **proposta** com `confidence: 0.3`, sujeitas a confirmação ou poda pelo Ranger. O Vine DEVE implementar a verificação do passo 1 dentro do próprio `graft` (idempotência de atalho): `graft` de link duplicado vira fortificação automaticamente, nunca erro nem duplicata.
- Commit: `graft(<id>): <resumo do patch>`.

### C.9 Concorrência e consistência (Fase 0)

- **Um escritor, N leitores:** `plant`/`graft` passam por fila única (mutex global no Vine). Leitura nunca bloqueia.
- Leitores PODEM ver estado de até 1 escrita atrás (consistência eventual de segundos) aceitável por design.
- Lock file `.vine.lock` na raiz impede dois Vines escritores na mesma floresta (`E_LOCKED`).

---

## Parte D Telemetria (alimenta o feromônio e o Monkey Bench)

Toda sessão de navegação gera um trace em `_derived/traces/<session>.jsonl`, um evento por chamada de primitiva: `{ts, session, primitive, id, tokens_in, tokens_out, elapsed_ms}`.

Ao final, o orquestrador DEVE fechar a sessão com `outcome: {success: bool, answer_nodes: [ids]}`. É esse fechamento que:
1. Incrementa `heat` em toda a trilha vencedora (sussurro);
2. Dispara avaliação de grito (trilha ≥ 4 hops → sugerir `graft` de atalho);
3. Alimenta as métricas do Monkey Bench: **hops-to-banana** = nº de chamadas `look`+`move` até o primeiro `pick`/`query` da resposta; **tokens-to-banana** = Σ tokens_out da sessão; **banana precision** = answer_nodes corretos / answer_nodes colhidos.

---

## Parte E A Tropa (Navegação Paralela por Enxame)

N macacos (instâncias do SLM navegador) caçam a mesma banana em paralelo, coordenados por **estigmergia intra-sessão**: eles não trocam mensagens eles sentem o cheiro das trilhas uns dos outros. O Vine já é N-leitores por design (C.9); a Tropa é um componente do **orquestrador** (lado cliente do MCP), não do banco.

### E.1 Protocolo da caçada

1. **Partição de fronteira:** `locate(query, k=N)` → cada macaco recebe um ponto de entrada distinto (top-N resultados). Sem partição, todos exploram a mesma trilha e o paralelismo é desperdiçado.
2. **Feromônio de sessão:** cada macaco, ao avaliar um nó como promissor (decisão do próprio SLM: "relevante para a pergunta? sim/não"), deposita `session_heat` no escopo da caçada (`_derived/trails.db`, namespace da sessão). `locate`/`look`/`scan` dentro da sessão aplicam `score × (1 + β·session_heat)` macacos gravitam para regiões onde outros acharam sinal.
3. **Conjunto de visitados compartilhado:** digests de `look`/`scan` já feitos na sessão ficam num cache compartilhado; macaco que tocaria nó já visitado recebe o digest do cache (custo zero) e o orquestrador o redireciona para fronteira inexplorada.
4. **Parada:** a caçada encerra quando (a) um macaco colhe banana com confiança alta (auto-avaliação acima de limiar), (b) orçamento de hops da tropa esgota, ou (c) fronteira esvazia. Um **juiz** (pode ser o próprio modelo principal) agrega as colheitas e sintetiza a resposta.
5. **Pós-sessão:** somente a(s) trilha(s) vencedora(s) convertem `session_heat` em `heat` persistente (Parte D). Trilhas perdedoras evaporam com a sessão o enxame não polui o feromônio de longo prazo.

### E.2 Notas de implementação

- **Concorrência:** asyncio no orquestrador; os macacos passam ~95% do tempo aguardando inferência. Na 3090, servir os N macacos pelo mesmo servidor de inferência com *continuous batching* (vLLM/llama.cpp parallel slots) faz N=3-5 custar quase o mesmo wall-clock que N=1.
- **Dimensionamento:** N=3 é o default; acima de N≈5 o retorno cai (fronteiras se sobrepõem em florestas pequenas). N é parâmetro do Monkey Bench, não constante.
- **Métrica nova:** *speedup da tropa* = hops-de-relógio (rodadas paralelas) vs hops totais do macaco solitário, e custo total de tokens (a tropa gasta mais tokens somados o trade-off velocidade × custo deve ser medido, não assumido).
- **Fase:** Tropa é Fase 1.5 exige Vine completo + telemetria (Parte D) funcionando. Nada na Fase 0 muda, exceto garantir que `trails.db` suporte namespace de sessão (já previsto no schema de traces).

## Parte F Critérios de Aceitação da Fase 0

Entregável: Vine (MCP, Python) + floresta de teste manual (~100 nós, 10 galhos, ≥1 dataset SQLite) + suíte de testes.

1. Todas as primitivas C.1–C.6b funcionais com os contratos exatos acima (locate pode ser BM25-only), incluindo `fields` no `look` e o Catálogo servindo `scan`.
2. `plant`/`graft` atômicos com commit Git e atualização de índice verificada por teste.
3. Orçamentos de tokens respeitados (testes com nós sintéticos gigantes verificando truncamento explícito).
4. `query` rejeita todo SQL de escrita (suíte de injeção: `;DROP`, `ATTACH`, multi-statement, PRAGMA).
5. Demo: um SLM local (Qwen 7-14B Q4), recebendo apenas as ferramentas MCP e o galho-mestre, responde 10 perguntas multi-hop sobre a floresta de teste, com traces gravados e métricas calculadas.
6. Latência: p95 de `look`/`move`/`pick` < 10ms, `query` < 50ms, `locate` < 100ms, `sniff` < 100ms (floresta local, NVMe).
7. `sniff`: encontra fato presente SOMENTE no corpo (invisível ao `locate`), atribui a seção correta, respeita `scope`, normaliza caixa/diacríticos, e rejeita termos vazios (`E_SCHEMA`) tudo coberto por teste.
8. Payloads fora do Git (A.3.1): o commit do Vine ignora não-`.md` mesmo que solicitado, e o `git ls-files` da floresta de teste não contém nenhum binário ambos verificados por teste.

Fora do escopo da Fase 0 (não implementar): embeddings/vetores, evaporação e promoção de atalhos (Ranger), compaction de `same-as`, ingest automático (Gardener), sync S3/R2, multi-escritor, Tropa (Parte E Fase 1.5; apenas garantir namespace de sessão no trails.db).
