# Usando a floresta

[English](../en/using.md) · Português · [Español](../es/using.md)

[← Manual](./README.md)

Quatro consoles fazem o trabalho do dia a dia de ler uma floresta.
**Perguntar** responde perguntas com evidência. **Explorar** mostra a
própria floresta como grafo, como arquivos, como árvore. **Dados** é um
cliente de banco de dados sobre os seus datasets. **Playground** mostra as
chamadas cruas, exatamente como um agente as faz.

Os quatro são janelas sobre os mesmos primitivos que a sua IA recebe via
MCP. Nada nesta página é um poder exclusivo do console: o que você
consegue fazer aqui, um agente com a mesma chave consegue fazer de fora.

## Perguntar

Perguntar é o console de chegada porque não precisa de explicação: digite
uma pergunta, receba uma resposta. O que o diferencia de uma janela de
chat é o que acontece por baixo, e quanto disso é mostrado a você. A busca
roda primeiro dentro do seu escopo determinística, barata, sem modelo
envolvido e só então o modelo ligado à floresta lê o que foi encontrado
e escreve a resposta.

![O console Perguntar: uma pergunta, sua resposta e a lista de evidências com os nós que foram de fato lidos](../assets/ask.png)

*(As capturas de tela mostram o console em inglês.)*

**A evidência não é decoração.** Cada id listado sob a resposta foi de
fato lido para produzi-la. Clique em um e ele abre no Explorar, então uma
afirmação na resposta está sempre a um clique do texto de onde veio. O
painel **O que ele leu** vai além: os trechos e as seções exatos que o
modelo recebeu, com número de seção e de linha o resumo decide *qual*
nó, o corpo é o que é lido, e este painel mostra as duas metades.

Alguns controles ficam ao lado da caixa de pergunta:

- **Quanto ler** quantos nós a busca entrega ao modelo (2, 3 ou 6).
- **Tamanho da resposta** um controle deslizante de "Auto" até um teto
  rígido. Esta é uma preferência sua: fica lembrada no seu navegador, por
  pessoa, e nunca entra no endereço. "Auto" não envia nada, e quem manda
  é o vínculo da própria floresta. Quando você define um tamanho, ele não
  é só um corte o tamanho declarado é escrito no prompt, então o modelo
  molda a resposta para caber, em vez de ela ser truncada no meio de uma
  frase (spec J.10.8).
- **Deixar saltar (busca agêntica)** em vez de uma varredura
  determinística, o modelo fica com os primitivos e navega locate,
  look, move, pick até conseguir responder. Custa uma chamada de
  modelo por salto, e o painel **Por onde ele foi** mostra cada salto: o
  que o modelo escolheu, o que voltou, e os dois relógios (a chamada na
  floresta, e o turno do modelo que decidiu fazê-la).
- **Banco de respostas** ligado por padrão, porque é de graça: uma
  pergunta já respondida nesta floresta inalterada é servida do banco na
  hora, sem pagar o modelo de novo. Desligue para comprar uma execução
  nova e substituir a guardada.

**Respostas servidas do banco dizem que são.** Uma resposta servida
carrega o selo **Do banco**, e o custo registrado nunca é cobrado de
novo. Não é um
cache burro: a busca ainda roda em toda pergunta, e a resposta guardada
só é servida enquanto o que seria lido hoje coincide com o que foi lido
então uma floresta que mudou por baixo da pergunta recebe uma resposta
nova, não uma vencida (spec J.10.7).

**As respostas podem mostrar as imagens que o modelo de fato leu.**
Quando o material contém um nó `media` uma captura de tela, um
diagrama, uma foto que entrou com uma descrição o modelo pode
incorporá-la na resposta como `![caption](media:<node id>)` (spec
J.10.9). O console resolve essa referência com a *sua* credencial: um id
que o modelo inventou, ou um que o seu escopo não pode ler, é renderizado
como a própria legenda e nada mais nunca um erro que fale mais alto que
a resposta. Evidência do tipo `media` mostra sua imagem ao lado do resumo
de todo jeito, porque "de que esta resposta foi feita" inclui os pixels.

Você pode levar uma resposta com você **Copiar cURL** (a mesma chamada,
pronta para um script), **Baixar .md** (com as referências `media:`
reescritas para endereços buscáveis) ou **Salvar em PDF**. Toda execução
também fica guardada no histórico do próprio navegador só nesta
máquina, nunca enviada à Station para você restaurar uma execução
antiga e compará-la com uma nova.

> **Nota** as respostas são lidas do texto dos nós. Uma pergunta cuja
> resposta é um agregado sobre linhas de dataset é recusada em vez de
> chutada; use o console Dados para essas.

## Explorar

Explorar é um único console com três maneiras de olhar a mesma floresta
(spec J.5.4). A seleção sobrevive à troca de modo, de propósito: passar
do grafo para os arquivos não é uma pergunta nova, é o mesmo nó visto de
outro jeito.

![O console Explorar no modo grafo: a floresta como nós e trilhas, com calor e estrutura visíveis](../assets/explore.png)

| Modo | Mostra | Bom para |
|---|---|---|
| **Grafo** | nós e trilhas tipadas, dispostos espacialmente | ver a forma: regiões quentes, propostas, atalhos, órfãos |
| **Arquivos** | a floresta como ela vive em disco, um arquivo aberto por vez | ler prosa como prosa, um banco de dados como tabela, a fonte a um clique |
| **Árvore** | a hierarquia de galhos como lista, com busca | escopos estreitos, e descobrir onde algo vive |

No **grafo**, cada canal visual é um fato que a floresta guarda: a cor é
o tipo do nó ou o galho onde ele mora, tamanho e brilho seguem o calor (o
feromônio que as leituras depositam), e um link proposto um que o
Ranger administra, ainda não promovido é desenhado diferente de uma
trilha curada. A linha do tempo reproduz o crescimento da floresta na
ordem de plantio, e tem duas pontas: arraste o início para a frente para
ver só o que foi plantado entre dois dias, cada nó ainda onde a floresta
inteira o colocou. **Agora** traz a floresta inteira de volta. Arraste um
nó, role para dar zoom, clique para selecionar, dê dois cliques para
abri-lo em Arquivos.

Em **Arquivos**, um nó abre como o que ele é. A visão **Leitura**
renderiza o markdown; **Fonte** mostra com honestidade as duas metades
armazenadas o passaporte como o catálogo o guarda, e o corpo como está
armazenado. O painel lateral carrega três abas: **Passaporte** (tipo,
resumo, tags, trilhas de saída), **Índice** (a entrada deste nó no índice
do pai derivada, nunca editada à mão) e **Trilhas** (calor, e onde ele
se conecta). O `.db` de um dataset abre como tabelas navegáveis —
servidas pelo mesmo primitivo somente leitura `query` de todos os outros
lugares, com teto e timeout, nunca um canal lateral privado.

**Ler um passaporte vs ler um corpo:** o passaporte (o que `look`
devolve) é o cheiro curado id, tipo, resumo, tags, trilhas. É o que a
busca casa e por onde um agente navega. O corpo (o que `pick` devolve) é
o texto completo, e custa mais para ler um corpo acima do orçamento de
leitura volta como seu sumário, seção por seção, em vez de fingir que
está inteiro.

**Editar é governado.** Com a capacidade de write, o botão **Editar**
abre o editor de nó: texto rico ou markdown, você escolhe. O id, o tipo e
a data de criação são fixos por toda a vida do nó; o resumo é validado
contra seu orçamento de tokens; um corpo grande é editado uma seção por
vez, porque uma seção é o que um `graft` substitui de forma atômica. O
painel **Mudanças pendentes** mostra exatamente o que será enviado, no
formato que a API recebe e o resultado é um commit git carimbado com o
seu principal. Nenhuma superfície, este console incluído, escreve um
arquivo diretamente: o commit, a validação e o registro de auditoria
*são* a escrita.

Prosa nova em folha entra pela aba **Escrever** do console de Ingestão:
escrever com revisão a mesma esteira que um arquivo enviado percorre lê
o seu texto, escreve o resumo, propõe onde ele se conecta e mostra tudo a
você antes de qualquer coisa ser plantada. Veja
[Alimentando a floresta](./feeding.md).

## Dados

Datasets são o único tipo de nó cujo conteúdo a busca textual não
enxerga: os fatos vivem num payload SQLite ao lado do passaporte. O
console Dados é um cliente de banco de dados sobre eles e tudo que ele
faz passa pelos mesmos dois primitivos que um agente recebe: `query` para
ler, `tend` para escrever.

![O console Dados: as tabelas de um dataset, as linhas e a aba SQL](../assets/data.png)

Escolha um dataset e as tabelas dele aparecem logo abaixo; a primeira já
abre com as linhas carregadas. Quatro abas:

| Aba | O que ela guarda |
|---|---|
| **Linhas** | a tabela como um grid paginar, ordenar, filtrar, exportar CSV e (com a capacidade `tend`) editar |
| **Estrutura** | colunas, tipos e a declaração armazenada somente leitura por design |
| **SQL** | consultas livres somente leitura, com os exemplos do próprio manual a um clique |
| **Notas** | o que você ensina ao agente sobre estes dados |

**Todo dataset carrega seu próprio mapa.** Na ingestão, o Gardener
escreve um `## Query manual` (toda tabela, toda coluna) e um
`## Sample rows` (as três primeiras linhas por tabela, células cortadas)
no passaporte para que um agente, ou você, veja o que é consultável sem
abrir um payload de cinco gigabytes. A aba SQL oferece as consultas de
exemplo do manual como pontos de partida.

**A leitura tem orçamento, e truncated quer dizer: estreite a sua
pergunta.** `query` aceita um único `SELECT` (ou `WITH`), injeta
`LIMIT 200` quando você não dá nenhum, e limita a *resposta* a 2.000
tokens (spec C.5.1). Duas flags dizem duas coisas diferentes:

| Flag | O que aconteceu | A saída |
|---|---|---|
| `limited` | o `LIMIT 200` injetado foi atingido a consulta casou mais linhas | estreite o seu filtro |
| `truncated` | o orçamento de tokens derrubou linhas que a consulta retornou | estreite a sua projeção nomeie as colunas de que você precisa |

A lista `columns` nunca é derrubada: um resultado cujas linhas foram
todas recusadas ainda diz exatamente quais colunas a sua instrução
produz, que é o mapa de volta. E as linhas que faltam *existem* —
`truncated` nunca significa "nada mais casou". Agregados não são
afetados, por construção: `SELECT SUM(x)` é uma linha curta, e computar o
agregado no SQL em vez de puxar linhas é a jogada certa para você e para
o agente igualmente.

**Notas é onde uma pessoa ensina o agente** (spec C.2.1). Estrutura e
amostra saem do arquivo; o *significado* não qual coluna é USD e qual é
BRL, o que um código de status quer dizer, qual join responde à pergunta
que as pessoas fazem de verdade. O que você escrever na aba Notas volta
em todo `look` deste dataset, e viaja com ele para dentro de toda
resposta que o host monta antes de qualquer SQL ser escrito. É salvo
como um `graft`, um commit; o Gardener nunca o sobrescreve, então
sobrevive a todo sync e a toda reimportação.

**Escritas são instruções únicas, mostradas antes.** Dê dois cliques numa
célula para editá-la, use a lixeira para derrubar uma linha, acrescente
linhas com **Nova linha** as mudanças ficam na tela, destacadas e
reversíveis, até você salvar. Salvar mostra as instruções `INSERT`,
`UPDATE` e `DELETE` exatas que o `tend` vai rodar; nada é escrito até
você aplicá-las, e cada instrução vira seu próprio commit git. `tend`
exige um `WHERE` em todo `UPDATE` e `DELETE`, e recusa DDL para sempre
(spec C.10): uma tabela nasce pelo schema declarativo do `plant` e muda
sendo reconstruída e é por isso que a aba Estrutura não tem botão de
editar, em vez de ter um que sempre falha.

> **Nota** criar e importar datasets também mora aqui: **Novo dataset**
> declara tabelas e colunas e as planta em uma chamada (o console nunca
> escreve DDL), e **Importar** envia arquivos `.db`, `.csv`, `.json`,
> `.xls` e `.xlsx` ao Gardener como um lote de ingestão de verdade —
> nada é interpretado no navegador. Veja
> [Alimentando a floresta](./feeding.md).

## Playground

O Playground é a janela honesta para o MCP: as mesmas chamadas que um
agente faz, com os mesmos orçamentos nada aqui é simulação. Escolha um
primitivo, preencha seus argumentos, execute e leia exatamente o que
voltou: a requisição como foi enviada, a resposta como foi recebida, e os
relógios separados para que o tempo do motor nunca se confunda com o da
sua rede.

| Chamada | O que faz | Orçamento (tokens) |
|---|---|---|
| `locate` | acha pontos de entrada pelos metadados curados | 800 |
| `sniff` | busca literal dentro dos corpos | 800 |
| `harvest` | recuperação de um golpe só, com trechos | 4.000 |
| `look` | o passaporte de um nó | 500 |
| `move` | as trilhas de um nó | 600 |
| `answer` | recuperação mais o modelo ligado | |

É aqui que "o que o agente realmente vê?" é respondido chamada a
chamada: execute o `locate` de onde a sua pergunta partiria, depois o
`look` que viria em seguida, e leia o mesmo JSON que o modelo lê —
orçamentos, flags `truncated` e tudo. O painel também reporta o tamanho
do corpus buscado e o que o próprio relógio do motor diz, de modo que um
`locate` de meio milissegundo é reportado como um `locate` de meio
milissegundo mesmo quando a ida e volta levou trinta.

Toda execução vem com seu cURL mesma rota, mesma chave, mesmas regras
que as suas aplicações recebem e o painel nomeia o endpoint MCP: aponte
qualquer harness de agente para `/mcp/` na sua Station como um servidor
MCP streamable-HTTP, com a mesma chave, e ele ganha estas chamadas como
ferramentas.

## Esta página também é da sua IA

Tudo acima é uma janela humana sobre uma superfície de máquina. Perguntar
é o primitivo `answer`; Explorar lê com `look`, `pick` e `move`; Dados é
`query` e `tend`; o Playground é todos eles, sem disfarce. Um agente
conectado via MCP segura as mesmas ferramentas sob o mesmo escopo e os
mesmos orçamentos o console é uma janela, e a floresta atrás dele é o
produto. Para entregar estas chamadas à sua IA, veja
[Conectando a sua IA](./connecting-ai.md).
