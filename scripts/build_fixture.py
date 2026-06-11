"""Build the Phase 0 test forest (forest-fixture/).

Deterministic: ~90+ nodes, 12 branches, 1 SQLite dataset, cross-links
designed to support the 10 multi-hop demo questions. Run:

    python scripts/build_fixture.py [--out forest-fixture]
"""

from __future__ import annotations

import argparse
import random
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monkeyllm.indexer import count_coverage, entry_line  # noqa: E402
from monkeyllm.parser import serialize_node  # noqa: E402

TODAY = "2026-06-10"
CREATED = "2026-06-01"

SCHEMA_MD = """---
id: _meta/schema
type: nota
title: Dialeto da floresta
summary: Tipos de nó e de aresta válidos nesta floresta. Novos tipos entram aqui antes do primeiro uso; o Vine rejeita o que não estiver declarado.
created: 2026-06-01
updated: 2026-06-10
---

# Dialeto da floresta

## Tipos de nó (type)

| `type` | Descrição | Verbo de colheita |
|---|---|---|
| `galho` | Arquivo de índice (_index.md) de uma pasta | look |
| `nota` | Conhecimento em texto livre | pick |
| `documento` | Documento convertido (origem PDF/DOCX) | pick |
| `dataset` | Dados tabulares (SQLite irmão) | query |
| `entidade` | Pessoa, organização, produto, lugar | pick |
| `conceito` | Definição/termo técnico | pick |
| `evento` | Fato datado (reunião, decisão, release) | pick |
| `midia` | Imagem/áudio/vídeo com descrição | pick |

## Tipos de aresta (rel)

| `rel` | Inversa | Semântica |
|---|---|---|
| `parte-de` | `contem` | Hierarquia lógica |
| `relacionado-com` | `relacionado-com` | Associação genérica (simétrica) |
| `mencionado-em` | `menciona` | Entidade citada em documento |
| `autor` | `autor-de` | Autoria |
| `comparado-com` | `comparado-com` | Contraste técnico (simétrica) |
| `derivado-de` | `origem-de` | Proveniência |
| `same-as` | `same-as` | Soft merge de entidades duplicadas |
| `atalho-descoberto` | — | Grito do macaco (criado por graft) |
| `sucede` | `precede` | Ordem temporal |
"""

# ---------------------------------------------------------------------------
# Node inventory. Each banana: (id, type, title, summary, tags, links, body)
# links: list of (rel, target). Bodies use ## sections so outline/pick work.
# ---------------------------------------------------------------------------

N = []  # populated below


def node(id, type, title, summary, tags=(), links=(), body="", **extra):
    N.append(
        {
            "id": id,
            "type": type,
            "title": title,
            "summary": summary,
            "tags": list(tags),
            "links": [{"rel": r, "target": t} for r, t in links],
            "body": body,
            "extra": extra,
        }
    )


# -- pessoas ----------------------------------------------------------------

PESSOAS = [
    ("jimmy-wesley", "Jimmy Wesley", "CTO da Tropicália Tech e autor da arquitetura do MixerLLM. Mora em Recife (PE). Lidera inferência local e o paper do MonkeyLLM.",
     ["cto", "inferencia"], [("autor", "projetos/mixerllm/arquitetura"), ("relacionado-com", "organizacoes/tropicalia-tech")],
     "## Perfil\n\nCTO e cofundador da Tropicália Tech. Mora em **Recife, Pernambuco**. Especialista em inferência local de SLMs e quantização.\n\n## Responsabilidades\n\n- Arquitetura do [[projetos/mixerllm/arquitetura|MixerLLM]]\n- Direção técnica do [[projetos/monkeyllm/visao|MonkeyLLM]]\n- Relação com a [[organizacoes/ufpe]] no workshop de 2026"),
    ("elena-souza", "Elena Souza", "CEO e cofundadora da Tropicália Tech. Responsável por vendas estratégicas; fechou o contrato com a DataCoop em fevereiro de 2026. Baseada em São Paulo.",
     ["ceo", "vendas"], [("relacionado-com", "organizacoes/tropicalia-tech"), ("mencionado-em", "eventos/2026-02-contrato-datacoop")],
     "## Perfil\n\nCEO e cofundadora da Tropicália Tech, baseada em São Paulo. Conduziu a negociação do contrato com a [[organizacoes/datacoop]].\n\n## Histórico\n\nEx-diretora comercial de uma scale-up de IoT industrial. MBA pela FGV."),
    ("ana-castro", "Ana Castro", "Engenheira de dados; dona do pipeline de vendas e do dataset Q1 2026. Mantém o export do ERP e o manual de consulta do relatório.",
     ["dados", "vendas"], [("autor", "vendas/relatorio-q1-2026"), ("relacionado-com", "organizacoes/tropicalia-tech")],
     "## Perfil\n\nEngenheira de dados responsável pelo export mensal do ERP para a floresta e pela qualidade do [[vendas/relatorio-q1-2026]].\n\n## Notas\n\nDefiniu a convenção de regiões IBGE usada na coluna `regiao`."),
    ("bruno-lima", "Bruno Lima", "Pesquisador de estigmergia e otimização por colônia de formigas. Escreveu as notas de feromônio digital e revisa o capítulo de related work do paper.",
     ["pesquisa", "estigmergia"], [("autor", "projetos/monkeyllm/feromonio"), ("relacionado-com", "conceitos/estigmergia")],
     "## Perfil\n\nPesquisador parceiro vindo do [[organizacoes/lab-amazonia]]. Trabalha com ACO (ant colony optimization) desde 2019.\n\n## Contribuições\n\nDesenhou o mecanismo de sussurro/grito do [[projetos/monkeyllm/feromonio]]."),
    ("carla-mendes", "Carla Mendes", "Product manager do MonkeyLLM. Define o roadmap de fases 0-4 e o glossário bilíngue do paper. Interface com clientes beta.",
     ["pm", "produto"], [("relacionado-com", "projetos/monkeyllm/visao")],
     "## Perfil\n\nPM do MonkeyLLM. Mantém o roadmap e prioriza o Monkey Bench como juiz das decisões.\n\n## Notas\n\nDefendeu a compatibilidade com Obsidian como feature de marketing."),
    ("diego-rocha", "Diego Rocha", "Engenheiro de infraestrutura: workstation 3090, cluster de borda e o deploy Docker do Vine. Cuida do espelho R2 e do volume da floresta.",
     ["infra", "docker"], [("autor", "infra/deploy-docker"), ("relacionado-com", "infra/workstation-3090")],
     "## Perfil\n\nSRE da Tropicália Tech. Mantém a [[infra/workstation-3090]] e o compose do [[infra/deploy-docker]].\n\n## Plantão\n\nResponde por sync R2 e backups da floresta."),
    ("fabio-nunes", "Fábio Nunes", "Engenheiro de inferência; implementou o block-loop do MixerLLM e os benchmarks de latência na 3090. Mantém o servidor llama.cpp.",
     ["inferencia", "benchmarks"], [("autor", "projetos/mixerllm/block-loop"), ("relacionado-com", "projetos/mixerllm/benchmarks")],
     "## Perfil\n\nEngenheiro de inferência focado em SLMs quantizados (Q4/Q5) e continuous batching.\n\n## Contribuições\n\nAutor do [[projetos/mixerllm/block-loop]] e dos números do [[projetos/mixerllm/benchmarks]]."),
    ("helena-prado", "Helena Prado", "Designer de produto; responsável pela identidade visual do monkeyllm.com e pelos diagramas da arquitetura em camadas L0-L4.",
     ["design"], [("relacionado-com", "projetos/monkeyllm/visao")],
     "## Perfil\n\nDesigner. Criou o sistema visual da floresta (galhos, bananas, trilhas) usado no site e no paper."),
    ("marcos-tavares", "Marcos Tavares", "Cientista de dados da DataCoop, contato técnico do contrato de fevereiro. Valida o piloto do MonkeyLLM sobre os dados da cooperativa.",
     ["cliente", "dados"], [("relacionado-com", "organizacoes/datacoop")],
     "## Perfil\n\nContato técnico do piloto na [[organizacoes/datacoop]]. Reporta bugs do Vine via canal compartilhado."),
    ("rita-azevedo", "Rita Azevedo", "Professora da UFPE, orientadora do workshop de maio de 2026 e coautora do paper. Especialista em recuperação de informação e BM25.",
     ["academia", "ir"], [("relacionado-com", "organizacoes/ufpe"), ("relacionado-com", "conceitos/bm25")],
     "## Perfil\n\nProfessora associada da [[organizacoes/ufpe]]. Coautora do paper do MonkeyLLM; revisa a seção de baselines."),
]
for slug, title, summary, tags, links, body in PESSOAS:
    node(f"pessoas/{slug}", "entidade", title, summary, tags, links, body, entity_kind="pessoa")

# -- organizacoes -------------------------------------------------------------

ORGS = [
    ("tropicalia-tech", "Tropicália Tech", "Empresa por trás do MixerLLM e do MonkeyLLM. Sede em São Paulo, P&D em Recife. CEO: Elena Souza; CTO: Jimmy Wesley. 18 pessoas.",
     [("relacionado-com", "pessoas/elena-souza"), ("relacionado-com", "pessoas/jimmy-wesley")],
     "## Sobre\n\nFundada em 2024. Produtos: [[produtos/mixerllm-engine]], [[produtos/monkeyllm-server]] e a linha de hardware de borda ([[produtos/sensor-x]], [[produtos/gateway-m]], [[produtos/kit-borda]]).\n\n## Pessoas-chave\n\n- CEO: [[pessoas/elena-souza]]\n- CTO: [[pessoas/jimmy-wesley]]"),
    ("datacoop", "DataCoop", "Cooperativa de dados agrícolas, cliente do piloto MonkeyLLM. Contrato assinado em fevereiro de 2026 incluindo 200 unidades do Sensor X e o piloto de memória.",
     [("relacionado-com", "pessoas/marcos-tavares"), ("mencionado-em", "eventos/2026-02-contrato-datacoop")],
     "## Sobre\n\nCooperativa com 40 fazendas associadas no Centro-Oeste. Compra sensores de borda e contratou o piloto do MonkeyLLM como memória dos agrônomos.\n\n## Contato técnico\n\n[[pessoas/marcos-tavares]]"),
    ("lab-amazonia", "Lab Amazônia", "Laboratório independente de pesquisa em sistemas bioinspirados; origem do Bruno Lima e parceiro no mecanismo de estigmergia.",
     [("relacionado-com", "pessoas/bruno-lima")],
     "## Sobre\n\nLaboratório de pesquisa em computação bioinspirada (formigas, abelhas, estigmergia). Parceria informal de pesquisa desde 2025."),
    ("ufpe", "UFPE", "Universidade Federal de Pernambuco; parceira acadêmica do paper. Sediou o workshop de maio de 2026 sobre navegação por índices.",
     [("relacionado-com", "pessoas/rita-azevedo"), ("mencionado-em", "eventos/2026-05-workshop-ufpe")],
     "## Sobre\n\nParceira acadêmica via [[pessoas/rita-azevedo]] (CIn/UFPE). Coautoria no paper e bolsistas no Monkey Bench."),
]
for slug, title, summary, links, body in ORGS:
    node(f"organizacoes/{slug}", "entidade", title, summary, ["organizacao"], links, body, entity_kind="organizacao")

# -- produtos ------------------------------------------------------------------

PRODUTOS = [
    ("sensor-x", "Sensor X", "Sensor de borda para telemetria agrícola, SKU A-101. Carro-chefe de receita no Q1 2026; vendido em lotes para cooperativas.",
     [("relacionado-com", "vendas/relatorio-q1-2026")],
     "## Ficha\n\n- **SKU:** A-101\n- Telemetria de solo e clima, LoRa, bateria de 2 anos.\n\n## Comercial\n\nVendido em lotes de 50; principal item do contrato [[eventos/2026-02-contrato-datacoop]]."),
    ("gateway-m", "Gateway M", "Gateway de campo que agrega sensores via LoRa e roda inferência leve, SKU B-202. Margem maior que o Sensor X.",
     [("relacionado-com", "vendas/relatorio-q1-2026")],
     "## Ficha\n\n- **SKU:** B-202\n- Agrega até 200 sensores; roda SLM quantizado para alertas locais."),
    ("kit-borda", "Kit Borda", "Bundle de implantação rápida (1 Gateway M + 10 Sensor X + suporte), SKU C-303. Canal preferido: parceiros.",
     [("relacionado-com", "vendas/relatorio-q1-2026")],
     "## Ficha\n\n- **SKU:** C-303\n- Bundle de entrada para fazendas médias."),
    ("mixerllm-engine", "MixerLLM Engine", "Runtime de inferência hot/cold com mixer-lang; licenciado como SDK. Em beta com dois clientes.",
     [("derivado-de", "projetos/mixerllm/arquitetura")],
     "## Ficha\n\nSDK do runtime descrito em [[projetos/mixerllm/arquitetura]]. Beta fechado."),
    ("monkeyllm-server", "MonkeyLLM Server", "Servidor MCP (Vine) + floresta como produto de memória para agentes. Distribuição via Docker Compose e pip.",
     [("derivado-de", "projetos/monkeyllm/visao")],
     "## Ficha\n\nProduto de entrada do MonkeyLLM: qualquer cliente MCP pluga a floresta como memória."),
]
for slug, title, summary, links, body in PRODUTOS:
    node(f"produtos/{slug}", "entidade", title, summary, ["produto"], links, body, entity_kind="produto")

# -- conceitos -------------------------------------------------------------------

CONCEITOS = [
    ("rag", "RAG", "Retrieval-Augmented Generation: recuperação top-k de chunks por similaridade vetorial injetados no contexto. Baseline principal do Monkey Bench.",
     [("comparado-com", "projetos/monkeyllm/visao")],
     "## Definição\n\nRecupera chunks por similaridade e injeta no prompt. Falha estruturalmente em perguntas multi-hop e dados tabulares grandes.\n\n## No projeto\n\nBaseline obrigatório do [[projetos/monkeyllm/monkey-bench]]."),
    ("graphrag", "GraphRAG", "Variante de RAG da Microsoft que constrói grafo de entidades e comunidades para sumarização hierárquica. Related work direto do paper.",
     [("comparado-com", "projetos/monkeyllm/visao")],
     "## Definição\n\nConstrói grafo de conhecimento + resumos de comunidades. Indexa uma vez; não aprende com o uso — diferença central para o MonkeyLLM."),
    ("raptor", "RAPTOR", "Árvore recursiva de resumos por clustering para recuperação em vários níveis de abstração. Related work do paper.",
     [], "## Definição\n\nResumos recursivos em árvore. Parecido com os galhos do MonkeyLLM, mas estático e sem navegação por agente."),
    ("speculative-decoding", "Speculative decoding", "Técnica de aceleração onde um modelo rascunho propõe tokens que o modelo alvo verifica. Contraste técnico do block-loop do MixerLLM.",
     [("comparado-com", "projetos/mixerllm/arquitetura")],
     "## Definição\n\nDraft model propõe, target verifica em paralelo. O block-loop do MixerLLM inverte a relação: o modelo quente delega blocos semânticos ao frio."),
    ("quantizacao", "Quantização", "Redução de precisão de pesos (Q4/Q5, GGUF) para rodar SLMs em GPUs de consumo como a RTX 3090. Pré-requisito do agente navegador local.",
     [], "## Definição\n\nQ4_K_M é o ponto doce para Qwen 7-14B na 3090: ~6-9 GB de VRAM, perda mínima de qualidade de navegação."),
    ("estigmergia", "Estigmergia", "Coordenação indireta via marcas no ambiente (Grassé, 1959): formigas e feromônio. Base teórica do sussurro e do grito do MonkeyLLM.",
     [("relacionado-com", "projetos/monkeyllm/feromonio")],
     "## Definição\n\nAgentes coordenam-se modificando o ambiente, não trocando mensagens. No MonkeyLLM: heat nas trilhas ([[projetos/monkeyllm/feromonio]]) e atalhos permanentes."),
    ("aco", "Ant Colony Optimization", "Meta-heurística de Dorigo inspirada em formigas: trilhas de feromônio com reforço e evaporação. Fundamento do mecanismo de heat.",
     [("relacionado-com", "conceitos/estigmergia")],
     "## Definição\n\nProbabilidade de escolha proporcional ao feromônio; evaporação evita convergência prematura — exatamente o papel da meia-vida de 30 dias do heat."),
    ("bm25", "BM25", "Função de ranking léxico clássica de IR; serve o locate da Fase 0 via SQLite FTS5. Complementa vetores na fusão RRF.",
     [], "## Definição\n\nTF-IDF saturado com normalização de tamanho. Imbatível para termos exatos, IDs e SKUs — por isso permanece mesmo com vetores."),
    ("rrf", "Reciprocal Rank Fusion", "Fusão de rankings por soma de 1/(k+posição). Combina BM25 e busca vetorial no locate sem calibrar scores.",
     [("relacionado-com", "conceitos/bm25")],
     "## Definição\n\nscore(d) = Σ 1/(k + rank_i(d)), k≈60. Robusta a escalas diferentes dos rankers de origem."),
    ("embeddings", "Embeddings", "Vetores densos de texto; entram só na Fase 1 (bge-m3, Matryoshka 1024→256, quantização binária + rescore). Cobrem summaries, nunca corpos.",
     [], "## Definição\n\nNo MonkeyLLM os vetores existem num único lugar: o locate. Apagar a pasta _derived os destrói sem perda de verdade."),
    ("mcp", "Model Context Protocol", "Protocolo aberto que expõe ferramentas a LLMs; o Vine fala MCP (stdio e HTTP). É o produto de entrada do MonkeyLLM.",
     [], "## Definição\n\nPadrão de tool-use entre clientes (Claude, IDEs) e servidores. As 8 primitivas do Vine são tools MCP."),
    ("slm", "SLM", "Small Language Model (1-14B): barato o suficiente para navegar por índices localmente. O macaco do MonkeyLLM é um Qwen 7-14B Q4.",
     [], "## Definição\n\nA tese: um SLM bem guiado por índices navega melhor que um LLM grande afogado em chunks de RAG."),
    ("wikilink", "Wikilink", "Sintaxe de dupla colchete para ligação entre notas; resolvida só contra IDs canônicos, sem fuzzy match. Ambiguidade é erro de lint, não adivinhação.",
     [], "## Definição\n\nFormato de dupla colchete com id canônico, opcionalmente com texto alternativo após a barra vertical. Compatibilidade Obsidian é feature de marketing da floresta."),
    ("frontmatter", "Frontmatter", "Bloco YAML no topo de cada nó: a interface máquina da banana. Campos obrigatórios: id, type, title, summary, created, updated.",
     [], "## Definição\n\nO summary do frontmatter é o componente mais crítico do sistema: é o cheiro que decide hops."),
    ("hierarchical-navigation", "Navegação hierárquica", "Tese central do MonkeyLLM: descer por índices auto-descritivos supera busca vetorial plana em perguntas multi-hop, custo e acurácia.",
     [("relacionado-com", "projetos/monkeyllm/visao")],
     "## Definição\n\nO agente lê ~200-500 tokens de índice por hop em vez de carregar chunks gordos; profundidade ≤4 mantém trilhas em ≤5 hops."),
    ("continuous-batching", "Continuous batching", "Técnica de servir N sequências na mesma GPU intercalando tokens; faz a Tropa (N=3-5 macacos) custar quase o mesmo wall-clock que 1.",
     [], "## Definição\n\nvLLM e llama.cpp parallel slots implementam; pré-requisito da Fase 1.5."),
    ("hotpotqa", "HotpotQA", "Benchmark clássico de perguntas multi-hop; inspira o formato das perguntas do Monkey Bench v1.",
     [("relacionado-com", "projetos/monkeyllm/monkey-bench")],
     "## Definição\n\nPerguntas que exigem compor evidência de 2+ documentos — o caso de uso onde RAG plano mais sofre."),
    ("memgpt", "MemGPT/Letta", "Sistema de memória paginada para LLMs com função de SO; related work de memória de agentes do paper.",
     [], "## Definição\n\nPagina contexto entre memória principal e externa. Contraste: MonkeyLLM externaliza a memória como floresta navegável e auditável em Git."),
    ("sqlite-fts5", "SQLite FTS5", "Extensão de full-text search do SQLite; serve o lado léxico do locate e vive no catálogo derivado.",
     [("relacionado-com", "conceitos/bm25")],
     "## Definição\n\nÍndice invertido embarcado com bm25() nativo, tokenizer unicode61 e remoção de diacríticos — suficiente para a Fase 0 inteira."),
    ("token-budget", "Orçamento de tokens", "Princípio transversal do Vine: toda resposta cabe num orçamento declarado (look 500, move 600, locate/scan 800) e trunca explicitamente.",
     [], "## Definição\n\nTruncamento silencioso é proibido: truncated: true sempre. O agente nunca recebe resposta cortada sem saber."),
]
for slug, title, summary, links, body in CONCEITOS:
    node(f"conceitos/{slug}", "conceito", title, summary, ["conceito"], links, body)

# -- projetos/mixerllm --------------------------------------------------------------

node("projetos/mixerllm/arquitetura", "documento",
     "Arquitetura do MixerLLM",
     "Arquitetura de inferência com modelo quente e frio colaborando via linguagem simbólica comprimida (mixer-lang), com block-loop e delegação inversa. Autor: Jimmy Wesley.",
     ["inferencia", "slm", "arquitetura"],
     [("parte-de", "projetos/mixerllm/_index"), ("comparado-com", "conceitos/speculative-decoding"), ("autor", "pessoas/jimmy-wesley")],
     "## Visão geral\n\nDois modelos colaboram: um **quente** (rápido, quantizado, sempre residente) e um **frio** (maior, carregado sob demanda). A comunicação usa [[projetos/mixerllm/mixer-lang]], uma linguagem simbólica comprimida.\n\n## Mixer-lang\n\nProtocolo de delegação: o quente emite blocos `@delega{...}` que o frio expande. Compressão média de 5:1 sobre prosa equivalente.\n\n## Block-loop\n\nVer [[projetos/mixerllm/block-loop]]: o loop de execução processa blocos semânticos, não tokens — a delegação é inversa ao speculative decoding.\n\n## Benchmarks\n\nNúmeros completos em [[projetos/mixerllm/benchmarks]]: 2.4x de throughput vs baseline single-model na 3090.")

node("projetos/mixerllm/mixer-lang", "documento",
     "Mixer-lang",
     "Linguagem simbólica comprimida de delegação entre modelo quente e frio. Blocos @delega com compressão 5:1; gramática estável desde a decisão v2 de março de 2026.",
     ["mixer-lang", "protocolo"],
     [("parte-de", "projetos/mixerllm/_index"), ("derivado-de", "projetos/mixerllm/arquitetura")],
     "## Gramática\n\nBlocos `@delega{intent, contexto, orçamento}` e respostas `@expande{...}`. Vocabulário fechado de 64 símbolos.\n\n## Histórico\n\nA v2 da gramática foi aprovada na decisão de março ([[eventos/2026-03-release-mixerllm-v2]]).")

node("projetos/mixerllm/block-loop", "documento",
     "Block-loop",
     "Loop de execução por blocos semânticos com delegação inversa: o modelo quente decide, o frio expande. Implementado por Fábio Nunes; contraste direto com speculative decoding.",
     ["inferencia", "block-loop"],
     [("parte-de", "projetos/mixerllm/_index"), ("autor", "pessoas/fabio-nunes"), ("comparado-com", "conceitos/speculative-decoding")],
     "## Mecanismo\n\nNo speculative decoding o modelo pequeno propõe e o grande verifica token a token. No block-loop a relação inverte: o quente (pequeno) é o dono da decisão e delega **blocos semânticos** inteiros ao frio.\n\n## Implementação\n\nFila de blocos com prioridade; o frio é acordado em batch a cada 3 blocos pendentes.")

node("projetos/mixerllm/benchmarks", "documento",
     "Benchmarks do MixerLLM",
     "Resultados na RTX 3090: 2.4x de throughput vs single-model, latência p95 de 380ms por bloco, 9.2 GB de VRAM com par Qwen 14B/7B Q4. Medidos por Fábio Nunes em maio de 2026.",
     ["benchmarks", "3090"],
     [("parte-de", "projetos/mixerllm/_index"), ("autor", "pessoas/fabio-nunes"), ("relacionado-com", "infra/workstation-3090")],
     "## Setup\n\nHardware: [[infra/workstation-3090]]. Par de modelos: Qwen2.5 14B (frio) + 7B (quente), ambos Q4_K_M.\n\n## Resultados\n\n| Métrica | Valor |\n|---|---|\n| Throughput vs single-model | 2.4x |\n| Latência p95 por bloco | 380 ms |\n| VRAM total | 9.2 GB |\n\n## Observações\n\nO ganho cai para 1.6x em prompts curtos (<200 tokens), onde a delegação não compensa.")

_exp_sections = "\n".join(
    f"## Experimento {i:02d}\n\nRodada com semente {1000+i}: variação de temperatura {0.1*(i%7):.1f}, "
    f"orçamento de blocos {4+i%5}, compressão observada {4.0+(i%10)/10:.1f}:1. "
    f"Resultado: {'aprovado' if i % 3 else 'descartado'} — latência média {300+7*i} ms, "
    f"throughput relativo {1.5+(i%9)*0.1:.1f}x. Notas: ajuste fino do vocabulário de símbolos, "
    f"reavaliar a fila de prioridade quando o frio satura, repetir com lote maior na próxima janela. "
    f"Observações adicionais da rodada {i}: o perfil de VRAM ficou estável em {8.0+(i%5)*0.3:.1f} GB, "
    f"sem fragmentação após {100+i} delegações consecutivas; o cache de blocos atingiu hit-rate de "
    f"{60+(i%30)}% e o tempo de expansão do modelo frio variou entre {40+i} e {90+2*i} ms por bloco."
    for i in range(1, 49)
)
node("projetos/mixerllm/log-experimentos", "nota",
     "Log de experimentos do MixerLLM",
     "Diário bruto de 40 rodadas de experimento do mixer-lang (sementes, temperaturas, compressão, latência). Consultar por seção; o corpo inteiro passa de 4 mil tokens.",
     ["experimentos", "log"],
     [("parte-de", "projetos/mixerllm/_index")],
     "## Como ler\n\nUma seção por rodada; use pick(section=) — o corpo completo estoura o orçamento de leitura.\n\n" + _exp_sections)

# -- projetos/monkeyllm ---------------------------------------------------------------

node("projetos/monkeyllm/visao", "documento",
     "Visão do MonkeyLLM",
     "Banco de conhecimento navegável por agentes: floresta de markdown com índices auto-descritivos, 8 primitivas MCP e estigmergia. Tese: navegação hierárquica supera RAG plano em multi-hop.",
     ["visao", "arquitetura"],
     [("parte-de", "projetos/monkeyllm/_index"), ("comparado-com", "conceitos/rag"), ("comparado-com", "conceitos/graphrag")],
     "## Tese\n\nNavegação por índices pré-computados ([[conceitos/hierarchical-navigation]]) supera busca vetorial plana em eficiência de contexto e acurácia multi-hop.\n\n## Camadas\n\nL0 floresta → L1 índices → L2 derivada → L3 protocolo (Vine) → L4 agente. L0/L1 são o produto; L2 é cache descartável.\n\n## Diferencial\n\nNem RAG nem GraphRAG melhoram com o uso; o MonkeyLLM converge via feromônio e atalhos.")

node("projetos/monkeyllm/primitivas", "documento",
     "As 8 primitivas do Vine",
     "Contratos das ferramentas MCP: locate, look (500 tokens), move (600), pick, query (SQL read-only), scan (catálogo), plant e graft (escrita atômica com Git). Orçamentos sempre explícitos.",
     ["mcp", "protocolo"],
     [("parte-de", "projetos/monkeyllm/_index"), ("relacionado-com", "conceitos/mcp"), ("relacionado-com", "conceitos/token-budget")],
     "## Leitura\n\n`locate` é o helicóptero (BM25 na Fase 0); `look` é a operação central (≤500 tokens); `move` navega arestas; `pick` colhe corpo ou seção; `query` consulta datasets SQLite; `scan` filtra metadados via catálogo.\n\n## Escrita\n\n`plant` cria (valida schema, atualiza índice pai, commita); `graft` edita com política reforçar-antes-de-criar para atalhos.")

node("projetos/monkeyllm/feromonio", "documento",
     "Feromônio: sussurro e grito",
     "Mecanismo de estigmergia do MonkeyLLM: heat volátil em trilhas vencedoras (sussurro, evapora em 30 dias) e atalhos permanentes via graft (grito, trilhas ≥4 hops). Autor: Bruno Lima.",
     ["estigmergia", "feromonio"],
     [("parte-de", "projetos/monkeyllm/_index"), ("autor", "pessoas/bruno-lima"), ("relacionado-com", "conceitos/estigmergia"), ("relacionado-com", "conceitos/aco")],
     "## Sussurro\n\nCada caçada bem-sucedida incrementa `heat` na trilha (em _derived/trails.db). locate/look reordenam por score × (1 + α·heat). Evaporação exponencial com meia-vida de 30 dias.\n\n## Grito\n\nTrilha longa (≥4 hops) gera atalho permanente `atalho-descoberto` com confidence 0.5 — commit no Git, auditável.\n\n## Política\n\nReforçar antes de criar: atalho existente é fortificado, nunca duplicado.")

node("projetos/monkeyllm/monkey-bench", "documento",
     "Monkey Bench",
     "Harness de avaliação do MonkeyLLM: perguntas multi-hop estilo HotpotQA, métricas hops-to-banana, tokens-to-banana e banana precision. Baselines: RAG top-k clássico e RAG iterativo.",
     ["benchmark", "avaliacao"],
     [("parte-de", "projetos/monkeyllm/_index"), ("relacionado-com", "conceitos/hotpotqa"), ("comparado-com", "conceitos/rag")],
     "## Métricas\n\n- **hops-to-banana**: chamadas look+move até o primeiro pick/query da resposta.\n- **tokens-to-banana**: Σ tokens de saída da sessão.\n- **banana precision**: nós-resposta corretos / colhidos.\n\n## Baselines\n\n(a) RAG top-k clássico com o mesmo corpus em chunks e mesmo embedder; (b) RAG iterativo sem índices nem grafo.\n\n## Critério da Fase 1\n\nPrecision ≥ baseline e ≤60% dos tokens do RAG iterativo.")

node("projetos/pipeline-audio", "nota",
     "Pipeline de áudio",
     "Pipeline de transcrição e diarização na 3090; migração de pyannote para NeMo Sortformer concluída em 2025. Projeto encerrado, mantido como referência.",
     ["audio", "concluido"],
     [("relacionado-com", "infra/workstation-3090")],
     "## Resumo\n\nTranscrição Whisper + diarização Sortformer, 6x tempo real na 3090. Encerrado; lições aproveitadas no servidor de inferência do MixerLLM.")

# -- vendas -----------------------------------------------------------------------------

node("vendas/relatorio-q1-2026", "dataset",
     "Relatório de Vendas Q1 2026",
     "Vendas por região e SKU, jan-mar 2026, 600 linhas com canal, quantidade, valor e margem em BRL. Não inclui devoluções (ver vendas/devolucoes-q1). Fonte: ERP, export de Ana Castro.",
     ["vendas", "q1", "dataset"],
     [("parte-de", "vendas/_index"), ("autor", "pessoas/ana-castro"), ("relacionado-com", "produtos/_index")],
     "## Manual de consulta\n\n**Tabelas:** `vendas(data, sku, produto, regiao, canal, qtd, valor, margem)`\n\n**Colunas-chave:** `sku` cruza com [[produtos/_index]] (A-101 Sensor X, B-202 Gateway M, C-303 Kit Borda); `regiao` usa as 5 macrorregiões IBGE; `valor` e `margem` em BRL.\n\n**Queries de exemplo:**\n- Total por região: `SELECT regiao, SUM(valor) AS total FROM vendas GROUP BY regiao ORDER BY total DESC`\n- Receita por SKU: `SELECT sku, produto, SUM(valor) AS receita FROM vendas GROUP BY sku ORDER BY receita DESC`\n- Margem por canal: `SELECT canal, ROUND(SUM(margem),2) AS m FROM vendas GROUP BY canal`",
     payload="relatorio-q1-2026.db", payload_type="sqlite")

node("vendas/devolucoes-q1", "nota",
     "Devoluções Q1 2026",
     "Resumo das devoluções do trimestre: 14 unidades de Sensor X (lote 22-B, falha de vedação) e 2 Gateway M. Valor devolvido: R$ 41.300. Não consta no dataset principal.",
     ["vendas", "devolucoes"],
     [("parte-de", "vendas/_index"), ("relacionado-com", "vendas/relatorio-q1-2026")],
     "## Detalhe\n\nO lote 22-B do [[produtos/sensor-x]] apresentou falha de vedação; troca coberta por garantia. Processo de qualidade aberto com o fornecedor da carcaça.")

node("vendas/politica-descontos", "nota",
     "Política de descontos 2026",
     "Regras comerciais vigentes: até 8% direto, até 15% via parceiro com aprovação da CEO, bundles (Kit Borda) já precificados com 10% embutido.",
     ["vendas", "politica"],
     [("parte-de", "vendas/_index")],
     "## Regras\n\n- Canal direto: até 8% sem aprovação.\n- Parceiro: até 15%, aprovação de [[pessoas/elena-souza]].\n- [[produtos/kit-borda]] não acumula desconto."),

node("vendas/metas-2026", "nota",
     "Metas comerciais 2026",
     "Meta anual de R$ 9,5 mi com 55% no segundo semestre; Q1 fechou em ~R$ 1,9 mi (20% da meta). Expansão Nordeste planejada para o Q3.",
     ["vendas", "metas"],
     [("parte-de", "vendas/_index"), ("relacionado-com", "vendas/relatorio-q1-2026")],
     "## Quadro\n\nQ1 realizado ≈ R$ 1,9 mi. O plano de expansão Nordeste depende da contratação de dois representantes em Recife.")

# -- eventos ---------------------------------------------------------------------------

EVENTOS = [
    ("2026-01-kickoff-monkeyllm", "Kickoff do MonkeyLLM", "Reunião de 12 de janeiro de 2026 que aprovou o roadmap de fases 0-4 e nomeou Carla Mendes como PM. Decisão: validar navegação antes de ingest.",
     [("mencionado-em", "projetos/monkeyllm/visao"), ("relacionado-com", "pessoas/carla-mendes")],
     "## Ata\n\n12/01/2026. Presentes: Elena, Jimmy, Carla, Bruno. Aprovado: Fase 0 valida um SLM navegando só por índices; servidor MCP antes do pipeline de ingest."),
    ("2026-02-contrato-datacoop", "Contrato DataCoop", "Contrato assinado em 18 de fevereiro de 2026 com a DataCoop: 200 unidades de Sensor X, 4 Gateway M e piloto do MonkeyLLM. Valor: R$ 480 mil. Negociado por Elena Souza.",
     [("relacionado-com", "organizacoes/datacoop"), ("relacionado-com", "produtos/sensor-x"), ("relacionado-com", "pessoas/elena-souza")],
     "## Termos\n\n18/02/2026. 200× [[produtos/sensor-x]] + 4× [[produtos/gateway-m]] + piloto de memória de agentes. Faturamento em 3 parcelas; contato técnico [[pessoas/marcos-tavares]]."),
    ("2026-03-release-mixerllm-v2", "Release MixerLLM v2 (mixer-lang v2)", "Release de 30 de março de 2026: gramática v2 do mixer-lang aprovada — vocabulário fechado de 64 símbolos, retrocompatível, compressão de 4:1 para 5:1.",
     [("relacionado-com", "projetos/mixerllm/mixer-lang"), ("sucede", "eventos/2026-01-kickoff-monkeyllm")],
     "## Decisão\n\n30/03/2026. A v2 fecha o vocabulário em 64 símbolos e melhora a compressão média para 5:1. Aprovada por Jimmy após os experimentos 21-28 do [[projetos/mixerllm/log-experimentos]]."),
    ("2026-04-paper-submissao", "Submissão do paper (deadline interno)", "Deadline interno de 30 de abril de 2026 para o draft do paper do MonkeyLLM; seção de related work ficou com Bruno e baselines com Rita Azevedo.",
     [("relacionado-com", "pessoas/rita-azevedo"), ("sucede", "eventos/2026-03-release-mixerllm-v2")],
     "## Status\n\nDraft circulado em 28/04. Pendências: curva de convergência (precisa da Fase 2) e números da Tropa."),
    ("2026-05-workshop-ufpe", "Workshop UFPE", "Workshop de 15 de maio de 2026 no CIn/UFPE sobre navegação por índices; 40 participantes, organizado com Rita Azevedo. Gerou 2 bolsistas para o Monkey Bench.",
     [("relacionado-com", "organizacoes/ufpe"), ("relacionado-com", "pessoas/rita-azevedo"), ("sucede", "eventos/2026-04-paper-submissao")],
     "## Resumo\n\n15/05/2026, CIn/UFPE. Demo ao vivo do Vine navegando a floresta de teste; feedback incorporado na spec v0.1."),
    ("2026-06-spec-v01", "Spec v0.1 aprovada", "Aprovação em 8 de junho de 2026 da especificação técnica v0.1 da Fase 0 pelo time de arquitetura: contratos das 8 primitivas, dialeto e critérios de aceitação.",
     [("sucede", "eventos/2026-05-workshop-ufpe"), ("relacionado-com", "projetos/monkeyllm/primitivas")],
     "## Registro\n\n08/06/2026. Spec v0.1 vira a verdade dos contratos; mudanças exigem nova versão da spec antes do código."),
]
for slug, title, summary, links, body in EVENTOS:
    node(f"eventos/{slug}", "evento", title, summary, ["evento"], links, body)

# -- infra ----------------------------------------------------------------------------

INFRA = [
    ("workstation-3090", "Workstation 3090", "Máquina de referência de P&D: RTX 3090 com 24 GB de VRAM, 128 GB de RAM, NVMe 4 TB. Roda o servidor de inferência e os benchmarks do MixerLLM.",
     [("relacionado-com", "projetos/mixerllm/benchmarks")],
     "## Especificação\n\n- GPU: **RTX 3090, 24 GB VRAM**\n- RAM 128 GB, NVMe 4 TB, Ryzen 9.\n\n## Uso\n\nServe Qwen 7-14B Q4 via llama.cpp; floresta local em NVMe (look <1ms)."),
    ("cluster-borda", "Cluster de borda", "Três Gateway M de bancada usados para testar inferência embarcada e o modo offline do MonkeyLLM em campo.",
     [("relacionado-com", "produtos/gateway-m")],
     "## Setup\n\n3× [[produtos/gateway-m]] em bancada com sensores reais; simula fazenda da DataCoop."),
    ("deploy-docker", "Deploy Docker do Vine", "Compose de produção: vine (MCP server) com volume da floresta, gardener com GPU passthrough e ranger em cron; espelho assíncrono via rclone para R2.",
     [("relacionado-com", "infra/sync-r2"), ("autor", "pessoas/diego-rocha")],
     "## Compose\n\nServiços: `vine` (HTTP/SSE), `gardener` (ingest, GPU), `ranger` (cron). A pasta _derived nunca sincroniza — cada nó reconstrói a própria copa."),
    ("sync-r2", "Sync R2", "Espelho assíncrono da floresta no Cloudflare R2 (egress zero) via rclone a cada 15 min; nunca entra no caminho de leitura.",
     [("parte-de", "infra/_index")],
     "## Política\n\nLocal-first: leitura/escrita sempre no volume local. R2 é backup e multi-device; byte-range remoto adiciona 30-80ms por hop, aceitável só em deploy remoto."),
]
for slug, title, summary, links, body in INFRA:
    node(f"infra/{slug}", "nota", title, summary, ["infra"], links, body)

# -- notas ----------------------------------------------------------------------------

NOTAS = [
    ("ideias-paper", "Ideias para o paper", "Backlog de ideias: curva de convergência como gráfico-assinatura, glossário bilíngue dos termos lúdicos, posicionamento contra RAG/GraphRAG/RAPTOR/MemGPT.",
     [("relacionado-com", "projetos/monkeyllm/monkey-bench")],
     "## Lista\n\n1. Curva hops-to-banana por semana de uso.\n2. Tabela comparativa vs [[conceitos/rag]], [[conceitos/graphrag]], [[conceitos/raptor]], [[conceitos/memgpt]].\n3. Trade-off da Tropa (velocidade × custo)."),
    ("glossario-bilingue", "Glossário bilíngue", "Mapeamento dos termos lúdicos para inglês técnico: grito = shortcut grafting (the shout), sussurro = session-scoped pheromone (the whisper), tropa = troop (parallel foragers).",
     [], "## Tabela\n\n| PT | EN |\n|---|---|\n| grito | shortcut grafting (the \"shout\") |\n| sussurro | session-scoped pheromone (the \"whisper\") |\n| tropa | troop (parallel foragers) |\n| cheiro | scent (summary) |"),
    ("riscos-projeto", "Riscos do projeto", "Top riscos: qualidade dos summaries (o sistema inteiro), índices dessincronizados, poluição de feromônio, florestas >100k bananas, drift payload-passaporte.",
     [("relacionado-com", "projetos/monkeyllm/visao")],
     "## Mitigações\n\nSummaries: compute generoso no ingest + medição no bench. Índices: escrita só via plant/graft. Poluição: confidence baixa + poda do Ranger."),
    ("leituras-recomendadas", "Leituras recomendadas", "Bibliografia viva do time: Grassé (estigmergia), Dorigo (ACO), papers de GraphRAG, RAPTOR, MemGPT e spreading activation.",
     [("relacionado-com", "conceitos/estigmergia")],
     "## Lista\n\n- Grassé 1959 — estigmergia em cupins.\n- Dorigo 1996 — Ant System.\n- Edge et al. 2024 — GraphRAG.\n- Sarthi et al. 2024 — RAPTOR."),
    ("faq-interno", "FAQ interno", "Perguntas frequentes do time: por que markdown e não banco, por que BM25 antes de vetores, por que Git em toda escrita, quando a Fase 3 (Rust) dispara.",
     [], "## Por que arquivos?\n\nFiles are the database: auditável, compatível com Obsidian, derivada descartável.\n\n## Quando Rust?\n\nSó com gargalo medido (>100k nós ou p95 estourado) — nunca porque \"Rust é mais rápido\"."),
    ("onboarding-time", "Onboarding do time", "Trilha de entrada para novos membros: ler a visão, o dialeto em _meta/schema, as primitivas, e rodar a demo das 10 perguntas localmente.",
     [("relacionado-com", "projetos/monkeyllm/primitivas")],
     "## Passos\n\n1. [[projetos/monkeyllm/visao]] → 2. [[_meta/schema]] → 3. [[projetos/monkeyllm/primitivas]] → 4. demo local."),
]
for slug, title, summary, links, body in NOTAS:
    node(f"notas/{slug}", "nota", title, summary, ["nota"], links, body)

# ---------------------------------------------------------------------------
# Branch definitions: id -> (title, summary/blurb, cross-trails)
# ---------------------------------------------------------------------------

BRANCHES = {
    "pessoas/_index": (
        "Pessoas",
        "Pessoas do ecossistema Tropicália Tech: time interno, parceiros acadêmicos e contatos de clientes, com papéis e responsabilidades.",
        ["Organizações onde trabalham → [[organizacoes/_index]]", "Autoria de documentos técnicos → [[projetos/_index]]"],
    ),
    "organizacoes/_index": (
        "Organizações",
        "Empresas, clientes, laboratórios e universidades do ecossistema: Tropicália Tech, DataCoop, Lab Amazônia e UFPE.",
        ["Pessoas de cada organização → [[pessoas/_index]]", "Contratos e marcos → [[eventos/_index]]"],
    ),
    "produtos/_index": (
        "Produtos",
        "Linha de produtos: hardware de borda (Sensor X A-101, Gateway M B-202, Kit Borda C-303) e software (MixerLLM Engine, MonkeyLLM Server).",
        ["Números de venda por SKU → [[vendas/relatorio-q1-2026]]", "Arquiteturas de origem → [[projetos/_index]]"],
    ),
    "projetos/_index": (
        "Projetos",
        "Projetos técnicos ativos e arquivados: MixerLLM (inferência hot/cold), MonkeyLLM (memória navegável) e o pipeline de áudio concluído.",
        ["Fundamentos teóricos → [[conceitos/_index]]", "Hardware de referência → [[infra/workstation-3090]]"],
    ),
    "projetos/mixerllm/_index": (
        "MixerLLM",
        "Arquitetura de inferência hot/cold com mixer-lang: arquitetura, gramática, block-loop, benchmarks na 3090 e o log bruto de experimentos.",
        ["Contraste técnico → [[conceitos/speculative-decoding]]", "Release v2 → [[eventos/2026-03-release-mixerllm-v2]]"],
    ),
    "projetos/monkeyllm/_index": (
        "MonkeyLLM",
        "Banco de conhecimento navegável (este sistema): visão e tese, as 8 primitivas do Vine, o mecanismo de feromônio e o Monkey Bench.",
        ["Base teórica → [[conceitos/estigmergia]]", "Spec aprovada → [[eventos/2026-06-spec-v01]]"],
    ),
    "conceitos/_index": (
        "Conceitos",
        "Definições técnicas de referência: RAG e variantes, estigmergia e ACO, BM25/RRF/FTS5, quantização, MCP, SLMs e os princípios do protocolo.",
        ["Aplicação prática dos conceitos → [[projetos/_index]]"],
    ),
    "vendas/_index": (
        "Vendas",
        "Dados e regras comerciais: dataset Q1 2026 consultável por SQL, devoluções do trimestre, política de descontos e metas do ano.",
        ["Fichas dos produtos vendidos → [[produtos/_index]]", "Contrato DataCoop → [[eventos/2026-02-contrato-datacoop]]"],
    ),
    "eventos/_index": (
        "Eventos",
        "Linha do tempo 2026: kickoff, contrato DataCoop, release do mixer-lang v2, submissão do paper, workshop UFPE e aprovação da spec v0.1.",
        ["Pessoas e organizações citadas → [[pessoas/_index]]"],
    ),
    "infra/_index": (
        "Infraestrutura",
        "Hardware e operação: workstation 3090 de P&D, cluster de borda, deploy Docker do Vine e o espelho assíncrono no R2.",
        ["Benchmarks que rodam aqui → [[projetos/mixerllm/benchmarks]]"],
    ),
    "notas/_index": (
        "Notas",
        "Notas transversais do time: ideias do paper, glossário bilíngue, riscos, leituras recomendadas, FAQ e onboarding.",
        ["Projetos referenciados → [[projetos/_index]]"],
    ),
}

LANDMARKS = [
    "projetos/monkeyllm/visao",
    "projetos/mixerllm/arquitetura",
    "vendas/relatorio-q1-2026",
    "pessoas/jimmy-wesley",
    "organizacoes/tropicalia-tech",
    "projetos/monkeyllm/feromonio",
    "conceitos/rag",
    "eventos/2026-02-contrato-datacoop",
    "infra/workstation-3090",
    "projetos/monkeyllm/monkey-bench",
]


def build_sales_db(path: Path) -> None:
    rng = random.Random(42)
    skus = [("A-101", "Sensor X", 1250.0), ("B-202", "Gateway M", 6800.0), ("C-303", "Kit Borda", 14900.0)]
    regioes = ["Sudeste", "Sul", "Nordeste", "Norte", "Centro-Oeste"]
    pesos = [0.38, 0.22, 0.18, 0.07, 0.15]  # Sudeste wins deterministically
    canais = ["direto", "parceiro", "online"]
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE vendas (data TEXT, sku TEXT, produto TEXT, regiao TEXT, canal TEXT, qtd INTEGER, valor REAL, margem REAL)"
    )
    start = date(2026, 1, 2)
    rows = []
    for _ in range(600):
        d = start + timedelta(days=rng.randint(0, 88))
        sku, produto, preco = rng.choice(skus)
        regiao = rng.choices(regioes, weights=pesos)[0]
        canal = rng.choice(canais)
        qtd = rng.randint(1, 12)
        valor = round(qtd * preco * rng.uniform(0.92, 1.0), 2)
        margem = round(valor * rng.uniform(0.18, 0.34), 2)
        rows.append((d.isoformat(), sku, produto, regiao, canal, qtd, valor, margem))
    conn.executemany("INSERT INTO vendas VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="forest-fixture")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        def _clear_readonly(func, path, exc):
            import os, stat
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(out, onexc=_clear_readonly)
    out.mkdir(parents=True)

    (out / "_meta").mkdir()
    (out / "_meta" / "schema.md").write_text(SCHEMA_MD, encoding="utf-8", newline="\n")

    by_id = {n["id"]: n for n in N}

    # bananas
    for n in N:
        fm = {
            "id": n["id"], "type": n["type"], "title": n["title"], "summary": n["summary"],
            "created": CREATED, "updated": TODAY,
        }
        if n["tags"]:
            fm["tags"] = n["tags"]
        if n["links"]:
            fm["links"] = n["links"]
        fm["source"] = "manual"
        fm.update(n["extra"])
        body = f"# {n['title']}\n\n{n['body'].strip()}\n"
        path = out / f"{n['id']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")

    build_sales_db(out / "vendas" / "relatorio-q1-2026.db")

    # branch indexes
    def children_of(branch_id: str) -> tuple[list[str], list[str]]:
        folder = branch_id[: -len("/_index")]
        subs, bananas = [], []
        for nid in sorted(by_id):
            parent = nid.rsplit("/", 1)[0] if "/" in nid else ""
            if parent == folder:
                bananas.append(nid)
        for b in BRANCHES:
            if b == branch_id:
                continue
            bf = b[: -len("/_index")]
            if "/" in bf and bf.rsplit("/", 1)[0] == folder:
                subs.append(b)
        return subs, bananas

    for branch_id, (title, blurb, cross) in BRANCHES.items():
        subs, bananas = children_of(branch_id)
        lines = [f"# {title}", "", f"> {blurb}", ""]
        if subs:
            lines.append("## Sub-galhos")
            for s in subs:
                lines.append(entry_line(s, BRANCHES[s][1]))
            lines.append("")
        lines.append("## Bananas diretas")
        for b in bananas:
            lines.append(entry_line(b, by_id[b]["summary"]))
        lines.append("")
        if cross:
            lines.append("## Trilhas cruzadas")
            for c in cross:
                lines.append(f"- {c}")
            lines.append("")
        body = "\n".join(lines)
        fm = {
            "id": branch_id, "type": "galho", "title": title, "summary": blurb,
            "coverage": count_coverage(body), "created": CREATED, "updated": TODAY,
        }
        path = out / f"{branch_id}.md"
        path.write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")

    # master index
    top_branches = [b for b in BRANCHES if "/" not in b[: -len("/_index")]]
    lines = [
        "# Floresta Tropicália",
        "",
        "> Base de conhecimento da Tropicália Tech: pessoas, projetos (MixerLLM, MonkeyLLM), "
        "conceitos, vendas, eventos e infraestrutura. Dialeto em [[_meta/schema]].",
        "",
        "## Sub-galhos",
    ]
    for b in sorted(top_branches):
        lines.append(entry_line(b, BRANCHES[b][1]))
    lines += ["", "## Bananas diretas", "", "## Landmarks"]
    for lm in LANDMARKS:
        lines.append(entry_line(lm, by_id[lm]["summary"]))
    lines += ["", "## Trilhas cruzadas", "- Dialeto da floresta (tipos e arestas) → [[_meta/schema]]", ""]
    body = "\n".join(lines)
    fm = {
        "id": "_index", "type": "galho", "title": "Floresta Tropicália",
        "summary": "Galho-mestre da base de conhecimento da Tropicália Tech: regiões de pessoas, organizações, produtos, projetos, conceitos, vendas, eventos, infra e notas.",
        "coverage": count_coverage(body), "created": CREATED, "updated": TODAY,
    }
    (out / "_index.md").write_text(serialize_node(fm, body), encoding="utf-8", newline="\n")

    # git init + initial commit
    def git(*a):
        subprocess.run(["git", "-C", str(out), "-c", "user.name=fixture", "-c", "user.email=fixture@monkeyllm.local", *a],
                       check=True, capture_output=True, text=True)
    git("init", "--quiet")
    (out / ".gitignore").write_text("_derived/\n.vine.lock\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "--quiet", "-m", "fixture: initial forest (~100 nodes, 12 branches, 1 dataset)")

    total = len(N) + len(BRANCHES) + 2  # + master index + schema
    print(f"forest written to {out}: {total} nodes ({len(BRANCHES) + 1} branches, {len(N)} bananas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
