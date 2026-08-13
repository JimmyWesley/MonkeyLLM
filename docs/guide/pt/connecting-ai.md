# Conectando a sua IA

[English](../en/connecting-ai.md) · Português · [Español](../es/connecting-ai.md)

[← Manual](./README.md)

Esta é a página que todo o resto do manual veio preparando. Tudo até aqui —
[instalar a Station](./install.md), [entrar](./first-access.md),
[fazer perguntas](./using.md), [alimentar documentos](./feeding.md) aconteceu
pelo Studio. Mas o Studio é uma janela. O produto é a floresta atrás dele,
e a floresta foi feita para ser lida e cultivada pela *sua própria IA*.

## Por quê

Quando você conecta um agente a uma floresta, ele ganha algo que uma
transcrição de chat nunca lhe dá: uma **memória persistente, governada e
citável**.

- **Persistente** a floresta sobrevive a toda conversa. O que uma sessão
  planta, a sessão seguinte lembra. Outras pessoas e outros agentes também a
  alimentam, e ela continua crescendo enquanto você a mantiver.
- **Governada** o agente segura uma chave, a chave carrega as suas
  concessões, e toda leitura e toda escrita passam pelo mesmo ponto de
  controle por onde o console passa. O que a chave não alcança não existe
  para o agente.
- **Citável** tudo que o agente lê carrega um id de nó. Respostas
  fundamentadas na floresta podem dizer exatamente sobre quais nós se apoiam.

E não há nada de segunda classe nessa conexão. A Station não tem canal
lateral privilegiado: o que quer que o Studio mostre a você, um cliente de
API ou MCP segurando a mesma chave também poderia buscar. A página Perguntar
do console chama o mesmo `answer` que o seu agente vai chamar. Conectar uma
IA não é uma integração aparafusada do lado é a porta da frente.

> **Nota** os snippets abaixo usam `https://station.example.com` como
> espaço reservado. Você raramente precisa substituir algo à mão: os
> consoles de Skills e de Integrações renderizam exatamente estes snippets
> já com o endereço real da sua Station e a floresta preenchidos.

## As três superfícies

Um contêiner, três superfícies, as mesmas florestas governadas. As três
autenticam com as mesmas chaves de API, verificadas num portão único, e
todo acesso a floresta passa pela mesma aplicação de escopo.

| Superfície | A quem serve | Onde |
|---|---|---|
| **Studio** | Humanos este console web | `https://station.example.com/` |
| **REST** | Apps, scripts e integrações | `https://station.example.com/v1/…` |
| **MCP** | Qualquer harness de agente (HTTP streamable) | `https://station.example.com/mcp/` |

A superfície MCP é idêntica em contrato a um `vine serve` local: um agente
que funciona contra uma floresta no seu próprio disco funciona contra uma
floresta servida pela Station sem nenhuma mudança além do endpoint e de uma
credencial. O escopo só estreita *conteúdo* ele nunca muda a forma de uma
resposta.

## Pareie uma chave

O seu agente precisa de uma credencial que seja *sua* não uma que um
administrador tenha que cunhar. O pareamento é essa porta: `POST
/v1/auth/pair` é não autenticada como o login, recebe o seu usuário e a sua
senha, e responde com uma chave de API.

```bash
curl -sX POST https://station.example.com/v1/auth/pair \
  -H 'content-type: application/json' \
  -d '{"username": "you", "password": "…", "label": "claude-code"}'
```

A resposta carrega `api_key` (ela se parece com `mk_…`), o seu `principal`,
as `caps` da chave e o seu `expires_at`. O que torna uma chave pareada
segura de entregar a uma máquina é que ela **só pode estreitar, nunca
acrescentar**:

- **A máscara.** Uma chave pareada carrega uma máscara de capacidades —
  `{read, ingest}` por padrão, e esse conjunto é também o teto: pedir
  `write`, `tend`, `query` ou `admin` é recusado como `E_SCHEMA`. Essas
  continuam sendo o que um administrador cunha deliberadamente.
- **Concessões ∩ máscara, no momento do uso.** A autoridade efetiva da
  chave são as suas próprias concessões filtradas pela máscara, calculadas
  ao vivo uma concessão revogada depois do pareamento some da chave
  imediatamente. Uma chave pareada nas mãos de um dono continua recusada em
  toda rota admin.
- **Ela sempre expira.** 90 dias por padrão, 365 no máximo; não existe
  "ilimitado". A chave é mostrada uma única vez só o digest dela é
  guardado.
- **Autosserviço por construção.** O pareamento não alcança nada que a sua
  senha já não alcançasse, então nenhum portão de admin fica na frente
  dele. Tanto `login` quanto `pair` têm limite de taxa, e a recusa nunca
  revela se um usuário existe.

A chave vive onde toda chave vive: o console de Acessos a lista, e um
administrador pode revogá-la lá a qualquer momento (veja
[Gerenciar a Station](./managing.md)).

## Claude Code em dois comandos

Se o seu agente é o Claude Code, a conexão inteira é a chamada de
pareamento acima mais um registro:

```bash
claude mcp add --transport http monkeyllm https://station.example.com/mcp/ \
  --header "Authorization: Bearer mk_…"
```

Daí em diante as tools da floresta estão em toda sessão. Duas coisas que
valem saber na primeira chamada:

- Faça o agente chamar `forests()` primeiro. Uma chave com escopo não tem
  índice mestre; essa chamada devolve as florestas que a chave pode usar e
  as raízes por onde começar.
- A superfície MCP só responde a hosts listados em
  `MONKEYLLM_STATION_ALLOWED_HOSTS`. Se você serve através de um domínio,
  nomeie-o lá (ou `*` para pular a verificação) toda requisição continua
  precisando de uma chave.

## O console de Skills

Um agente conectado sabe que as tools existem; ele ainda não tem o *hábito*
de usá-las. O console de Skills fecha essa lacuna. Uma skill é um pequeno
arquivo de instruções que um runtime de agente carrega, e esta ensina o seu
agente a tratar a floresta aberta como a sua memória: lembrar a partir dela
antes de responder, guardar o que vale manter, citar os ids dos nós que
leu.

![O console de Skills, gerando a skill de memória para esta Station e esta floresta](../assets/skills.png)

*(As capturas de tela mostram o console em inglês.)*

O console conduz você pelos mesmos três passos desta página parear uma
chave, apontar o Claude Code para a Station, entregar a ele o arquivo e
cada snippet nele já carrega o endereço da Station e o nome da floresta
aberta. A skill é gerada no seu navegador, para exatamente aquela
implantação; a Station não ganha nenhum endpoint para isso. Ela está
disponível para qualquer pessoa cuja chave tenha `read` na floresta —
nunca atrás de portão de admin, porque o pareamento tornou a credencial
autosserviço e aprender a conectar também precisa ser.

Para o Claude Code, o arquivo se instala em:

```
~/.claude/skills/monkeyllm-memory/SKILL.md
```

Vale espiar as próprias palavras do arquivo, porque elas são o contrato que
o seu agente vai seguir. Sob o título **"This forest is your memory"**, ele
ensina três seções:

- **Recall before you answer** para qualquer pergunta que a floresta
  possa responder, lembre primeiro e raciocine depois: `answer` quando a
  resposta da floresta *é* a resposta; `harvest` quando o agente vai
  raciocinar sobre o material por conta própria; `locate` → `look` → `pick`
  para navegar; `sniff` para texto literal dentro dos corpos; `query` para
  datasets, se a chave carrega `query` depois de um `look`, porque as
  `notes` de um dataset dizem o que as colunas significam. E: cite ids de
  nós para qualquer coisa afirmada a partir da floresta.
- **Save what is worth keeping** quando o usuário declara algo durável
  (uma decisão, um fato, uma preferência, uma correção), ofereça-se para
  guardar, com a escrita que a chave de fato permite: `ingest` um
  documento markdown através do Gardener é a escrita que uma chave
  pareada carrega por padrão; `plant` e `graft` são ensinados só para
  chaves que carregam `write`. Escreva em inglês e mantenha o resumo
  honesto o resumo é como a nota será encontrada.
- **Respect the contract** a chave decide o que o agente vê e o que ele
  pode escrever; nunca contorne uma recusa diga o que foi recusado e
  qual capacidade seria necessária. Toda leitura tem orçamento, e
  `truncated: true` significa pergunte mais estreito, não insista mais
  forte. Datasets mudam através de `tend` só onde a chave o carrega, uma
  instrução por vez, nunca DDL.

> **Nota** o corpo do arquivo da skill é em inglês independentemente do
> idioma do console, de propósito: ele fala com o modelo, não com você. O
> passo a passo em volta dele é traduzido como qualquer outra parte do
> console.

## As tools MCP

As tools são as primitivas do motor mais as compostas, cada uma atrás da
capacidade de que precisa. `forests` responde a qualquer chave válida; todo
o resto é guardado como mostrado.

| Tool | Exige | O que faz |
|---|---|---|
| `forests` | qualquer chave | Lista as florestas que esta chave pode usar, com capacidades e raízes de partida. |
| `locate` | `read` | Pontos de entrada ordenados sobre os metadados curados onde cair dentro da floresta. |
| `look` | `read` | Um apanhado barato de um nó: resumo, arestas, filhos, estatísticas. |
| `move` | `read` | Vizinhos de um nó ao longo de arestas tipadas. |
| `pick` | `read` | Lê o corpo, ou uma seção dele. |
| `scan` | `read` | Filtra os nós de um galho por metadados. |
| `sniff` | `read` | Busca literal dentro dos corpos os fatos que os resumos não carregam. |
| `harvest` | `read` | Recuperação de um golpe só: evidência ordenada com trechos exatos, sem saltos. |
| `answer` | `read` | Uma resposta fundamentada escrita pelo modelo ligado à floresta, com a sua evidência. |
| `view` | `read` | O payload de imagem de um nó media, como conteúdo de imagem que um cliente multimodal lê para o próprio contexto. |
| `query` | `query` | SQL somente leitura contra um nó de dataset. |
| `plant` | `write` | Cria um nó. |
| `graft` | `write` | Edita um nó. |
| `tend` | `tend` | Escrita de dataset em uma instrução única. |
| `ingest` | `ingest` | Coloca documentos dentro da floresta através do Gardener. |

Um modelo mental razoável: `answer` e `harvest` são os de-um-golpe-só, a
família `locate`/`look`/`move`/`pick`/`scan`/`sniff` é navegação, `query` e
`tend` são o par de dataset, e `plant`/`graft`/`ingest` são como a floresta
cresce.

## A superfície REST em cinco minutos

Scripts e aplicações falam com as mesmas florestas por HTTP/JSON puro.
Envie a chave como bearer token em toda requisição. Se em vez disso você
tem usuário e senha, um login devolve um **token de sessão** uma chave
comum com vida de 12 horas então, passada a porta, existe exatamente um
caminho de autorização:

```bash
curl -sX POST https://station.example.com/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username": "admin", "password": "…"}'
```

Um único formato de rota cobre todas as primitivas: faça POST dos
argumentos como JSON no nome da primitiva, por floresta —
`POST /v1/forests/{forest}/{name}`. Três exemplos, para uma floresta
chamada `handbook`:

```bash
# ask for a grounded answer
curl -sX POST https://station.example.com/v1/forests/handbook/answer \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"question": "what is our expense policy?"}'
```

```bash
# retrieve evidence without a model
curl -sX POST https://station.example.com/v1/forests/handbook/harvest \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"query": "expense policy", "terms": ["receipt"], "k": 3}'
```

```bash
# upload documents
curl -sX POST https://station.example.com/v1/forests/handbook/ingest \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"mode": "upload", "dest": "policies",
       "files": [{"name": "expenses.md", "text": "# Expenses…"}]}'
```

Falhas são um único envelope, mapeado em códigos HTTP, e o `hint` é escrito
para quem chama mostre-o:

```json
{
  "error": {
    "code": "E_FORBIDDEN",
    "message": "missing or invalid API key",
    "hint": "Send Authorization: Bearer <key>."
  }
}
```

> **Nota** fora de escopo é indistinguível de inexistente. Um nó que a
> chave não pode ver reporta `E_NOT_FOUND`, byte a byte igual a um nó que
> não existe. Isso é deliberado: um erro que dissesse "proibido" revelaria,
> ele mesmo, o nó.

## Qualquer outro runtime

Nada acima é particular ao Claude Code além do caminho de instalação.
Qualquer runtime capaz de MCP conecta com o mesmo endpoint e a mesma chave
pareada registre-o onde quer que o seu runtime configure servidores MCP:

```json
{
  "mcpServers": {
    "monkeyllm": {
      "type": "http",
      "url": "https://station.example.com/mcp/",
      "headers": { "Authorization": "Bearer mk_…" }
    }
  }
}
```

Entregue a ele as mesmas instruções do `SKILL.md`, adaptadas à maneira como
o seu runtime carrega system prompts ou skills. O arquivo fala com o
modelo, então ele viaja.

## O que o seu agente nunca pode fazer

Conectar uma IA não abre um buraco na governança o agente é um principal
como qualquer outro, e o contrato vale em toda superfície.

**Escopos valem.** Uma concessão vincula um principal a uma floresta com
capacidades e escopo por prefixo de galho: listas allow e deny de prefixos
de subárvore, deny vence em qualquer profundidade, e sem concessão não há
acesso. As capacidades são exatamente seis:

| Capacidade | Permite |
|---|---|
| `read` | ler o material |
| `query` | rodar SQL somente leitura |
| `write` | criar e editar nós |
| `tend` | alterar linhas de dataset |
| `ingest` | adicionar documentos novos |
| `admin` | conceder acesso a outras pessoas |

O filtro de escopo é aplicado *antes* da ordenação e do orçamento, então um
agente não consegue inferir conteúdo escondido a partir de contagens de
resultados ou de marcadores de truncamento e um nó fora de escopo
responde exatamente como um que não existe.

**Orçamentos valem.** Toda primitiva de leitura responde dentro de um
orçamento de tokens declarado, e um resultado cortado sempre diz
`truncated: true` nunca um corte silencioso:

| Chamada | Orçamento (tokens) |
|---|---|
| `look` | 500 |
| `move` | 600 |
| `locate`, `scan`, `sniff` | 800 cada |
| `query` | 2000 |
| `pick`, `harvest` | 4000 |

Um corpo acima do orçamento do `pick` volta como o seu sumário de seções
mais uma dica para pedir uma seção. Os orçamentos são o motivo de uma
floresta continuar navegável por um modelo pequeno e de a skill ensinar
"ask narrower, not retry harder" (pergunte mais estreito, não insista mais
forte).

**Escritas continuam disciplinadas.** `plant` e `graft` são commits git
atômicos dentro da floresta; datasets mudam só através de `tend`, uma
instrução DML por vez, WHERE obrigatório em UPDATE e DELETE, DDL nunca.
Não existe rota pela qual um agente apague um nó.

**A auditoria vê tudo.** Toda leitura com escopo cai no registro do host:
principal, floresta, primitiva, um digest dos argumentos, tamanho do
resultado e timestamp nunca corpos. Toda escrita é um commit git
carimbado com o principal que agiu. Qual agente leu quais nós, em qual
ordem, é reconstruível depois do fato veja
[Gerenciar a Station](./managing.md).

## Onde vive o manual completo

Esta página é o caminho do operador. A referência exaustiva cada rota,
cada tool, cada ajuste de implantação e variável de ambiente vive dentro
do próprio Studio, no console **MCP / API / Integrações**. Ele fica atrás
de admin, porque fala o vocabulário do administrador: credenciais, hosts, o
contêiner.

![O console de Integrações: o manual da implantação, dentro da implantação que ele descreve](../assets/integrations.png)

Ele é um console, e não um site estático, de propósito: cada exemplo lá
carrega o origin daquela Station, então cada snippet está pronto para
copiar para o host que o administrador está de fato olhando documentação
que não consegue descolar da implantação que documenta. Quando algo nesta
página e algo naquele console discordarem, confie no console: ele está
descrevendo a si mesmo.
