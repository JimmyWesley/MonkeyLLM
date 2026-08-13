# Primeiro acesso

[English](../en/first-access.md) · Português · [Español](../es/first-access.md)

[← Manual](./README.md)

O primeiro minuto no Studio é deliberado. Dependendo do estado da sua
Station você vai encontrar uma de duas telas pré-identidade — a
configuração ou o portão — e depois, uma única vez, uma curta apresentação
do que você de fato instalou. Esta página percorre as três, e depois
mostra o caminho.

## A tela de configuração

Uma Station é instalada antes de ter uma pessoa administradora, então a
primeiríssima visita a uma implantação recém-criada cai na tela de
configuração: **"Configurar esta Station"**. Ela existe exatamente uma
vez. Enquanto o registro não guarda credencial de espécie alguma, `GET
/v1/health` reporta que a configuração é necessária e o console mostra
esta tela; no momento em que existe uma pessoa dona, a rota some
permanentemente e todo mundo entra normalmente — a própria tela diz isso
no rodapé.

![A tela de configuração de uma única vez: conta dona e escolha da primeira floresta](../assets/setup.png)

*(As capturas de tela mostram o console em inglês.)*

Ela pede três coisas e uma escolha:

| Campo | O que significa |
|---|---|
| **Usuário** | É com ele que você entra, e é o nome que aparece no log de auditoria. |
| **Senha** | No mínimo 12 caracteres. Esta conta é dona da implantação — governa todas as florestas, presentes e futuras — então capriche no tamanho. |
| **E-mail** | Opcional, e rotulado como tal. Fica guardado no próprio registro da Station como contato da pessoa dona — nada é enviado a nenhum serviço externo, e a configuração se completa bem em um host isolado da internet. |

A conta criada aqui carrega o **bit de dona**: `admin` em todas as
florestas do registro, inclusive florestas criadas depois, inclusive
nenhuma. Existe exatamente uma pessoa dona, e o bit não pode ser concedido
a mais ninguém depois.

Depois, a escolha da **primeira floresta**:

| Escolha | O que acontece |
|---|---|
| **Começar com uma floresta de demonstração** | Uma floresta pequena que explica o MonkeyLLM sendo uma. Apague quando quiser — ela existe para que Perguntar e Explorar tenham o que responder na sua primeira visita. |
| **Começar com uma floresta vazia** | Sem nada dentro ainda; você dá o nome, o console mostra o id em que o nome se transforma, e você a preenche pela Ingestão. |
| **Deixar para depois** | Um estado válido. Uma pessoa dona sem floresta funciona — o estado vazio do console carrega a ação de criar, e você é administradora em todo lugar. |

> **Nota** — se a configuração falhar porque outra pessoa chegou nela
> primeiro, o console não tenta de novo: a rota se foi, então ele recua
> para o portão. E se a sua implantação está configurada com um
> super-admin de ambiente, a rota de configuração nunca chega a existir —
> essa implantação já declarou a sua primeira identidade. Onde encontrar a
> porta é impresso no log de inicialização da Station na primeira execução
> (veja [Instalar](./install.md)).

## O portão

Toda visita depois da configuração começa no portão: **"Conecte-se à sua
Station"**. Ele tem até duas portas, e quais você vê é um fato da
implantação que o console pergunta à Station, nunca um chute.

![O portão: entre com um usuário ou com uma chave de API](../assets/gate.png)

- **A porta da senha** (a aba **Usuário**) existe quando entrar com senha
  é possível — um super-admin de ambiente está configurado, ou pelo menos
  uma pessoa recebeu uma senha em Acessos. Você entra com usuário e senha;
  o token de sessão que recebe se comporta como uma chave comum dali em
  diante, então tudo o que vem depois é um caminho só.
- **A porta da chave** (a aba **Chave de API**) sempre existe. Cole uma
  chave (`mk_…`) e conecte. A Station guarda apenas o digest da chave — a
  chave em si nunca é armazenada no servidor.

Em uma Station sem senha configurada, as abas desaparecem e o campo da
chave é o portão inteiro. Chaves são emitidas em Acessos por quem
administra — ou derivadas da sua própria senha pelo pareamento, que é
autosserviço (veja [Conectando uma IA](./connecting-ai.md)). Uma chave
rejeitada diz exatamente isso e nada mais.

As duas telas pré-identidade carregam elas mesmas os controles de idioma e
tema: a primeira tela que uma pessoa vê não pode exigir uma sessão para
ser legível.

## A apresentação

Na primeira vez que você entra, o console oferece uma curta apresentação.
É o único momento em que o produto pode dizer o que ele é, porque,
deixadas por conta própria, a maioria das pessoas conclui a coisa óbvia e
errada — que o console é o produto.

![As boas-vindas de uma única vez: um cérebro que as suas IAs podem cultivar](../assets/welcome.png)

O título é **"Um cérebro que as suas IAs podem cultivar"**, e o subtítulo
é a frase a que este manual inteiro fica voltando: *o console é uma
janela; a floresta atrás dele é o produto*. O MonkeyLLM mantém uma
floresta de conhecimento — nós de markdown curados que uma IA pode
navegar, questionar e estender. O Studio é como pessoas a observam,
governam e ensinam, mas a floresta foi feita para ser lida e alimentada
pelos seus próprios agentes, via MCP, enquanto você a mantiver crescendo.

A apresentação nomeia as três coisas que valem ser feitas primeiro:

- **Conecte uma IA** — o Claude Code ou qualquer agente MCP se pluga nesta
  Station e ganha as tools da floresta: recuperação, navegação, SQL,
  plantio.
- **Alimente-a** — envie documentos, espelhe pastas inteiras, recorte
  páginas do navegador; o Gardener os transforma em conhecimento curado e
  encontrável.
- **Pergunte a ela** — respostas fundamentadas na floresta, chegando com
  as fontes: nós que você pode abrir, ler e corrigir.

Ela aparece **no máximo uma vez por navegador** — a flag vive no
armazenamento do navegador, uma preferência pessoal como o seu tamanho de
resposta — e não gasta nada: renderizá-la ou dispensá-la não emite nenhuma
chamada de modelo, nenhum commit, nenhuma escrita além dessa flag. Ela
nunca bloqueia o console, e só *aponta* para os consoles que fazem o
trabalho de verdade. **Ensinar a minha IA** leva você a Skills; **Dar uma
olhada** simplesmente a fecha. Se você a dispensou no primeiro dia e
precisa da porta no trigésimo, a Visão geral mantém uma pequena
reafirmação permanente — *"A sua IA também lê isto"* — apontando para
Skills e para o manual de integração.

## Encontrando o caminho

O menu responde a três perguntas em vez de listar nomes: **Usar**,
**Construir**, **Governar**. Cada entrada carrega um ícone e uma descrição
de uma linha, e o menu mostra apenas o que a sua chave permite — uma
entrada que só poderia recusar não ensina nada. Esconder é apresentação,
nunca o controle: a API recusa de qualquer forma.

![O console de Visão geral, com o menu agrupado à esquerda](../assets/overview.png)

| Grupo | Console | Para que serve | Exige |
|---|---|---|---|
| Usar | **Visão geral** | O que existe nesta floresta e o que você pode fazer aqui | todo mundo |
| Usar | **Perguntar** | Faça uma pergunta e receba a resposta com as fontes | read |
| Usar | **Explorar** | Percorra a árvore e leia o que cada nó guarda | read |
| Usar | **Playground** | Veja exatamente o que um agente vê, chamada a chamada | read |
| Usar | **Dados** | Navegue, consulte e edite seus datasets | query |
| Usar | **Skills** | Ensine a sua IA a usar esta floresta como memória | read |
| Construir | **Ingestão** | Coloque seus documentos dentro da floresta | ingest |
| Construir | **Modelos** | Qual modelo lê esta floresta e qual resume o que entra | admin |
| Governar | **Acessos** | Quem existe, o que pode ver, como entra | admin |
| Governar | **Auditoria** | Quem viu o quê | admin |
| Governar | **Saúde** | O que o Ranger enxerga, e tire um snapshot | admin |
| Governar | **MCP / API / Integrações** | Conecte agentes, apps e implantações a esta Station | admin |

Skills fica em *Usar* de propósito: é autosserviço, disponível a qualquer
pessoa que possa ler a floresta, nunca atrás de admin. No pé do menu, toda
pessoa conectada recebe a oferta **Baixar a extensão Clipper** — a
extensão de navegador que recorta a página que você está lendo para
dentro desta floresta.

No celular, o menu vira uma folha e uma barra inferior carrega até quatro
consoles ao lado de um **Mais** permanente. Quais quatro é escolha sua: a
estrela ao lado de cada entrada do menu fixa um atalho na barra. Até você
escolher, a barra guarda os quatro primeiros consoles que a sua concessão
permite, na ordem do menu, para que a barra e o menu contem a mesma
história. Os atalhos fixados vivem no seu navegador e são sempre filtrados
pela concessão atual — um atalho guardado de uma floresta onde você tinha
`admin` não segura uma vaga em uma onde você não tem.

## Idioma e tema

O console vem com **inglês, português e espanhol**, completos — uma
tradução faltando é um defeito, não um fallback. Ele detecta o idioma do
seu navegador no primeiro carregamento e persiste uma escolha explícita
assim que você fizer uma. A aparência funciona do mesmo jeito: **claro e
escuro**, seguindo a preferência do seu sistema operacional até que se
diga o contrário. Os dois controles aparecem também na tela de
configuração e no portão, antes de qualquer sessão existir.

> **Nota** — conteúdo não é interface. Ids de nós, títulos, resumos,
> corpos, SQL e saída de modelo são dados da floresta e são renderizados
> exatamente como armazenados; o console traduz apenas as próprias
> palavras.

## Seu escopo

O primeiro cartão da Visão geral é **Nós ao seu alcance**, e a palavra
*alcance* é precisa: cada número da página é contado sobre o que a **sua
chave** de fato alcança, não sobre a floresta. Nada está escondido atrás
de um filtro — e uma identidade com escopo que visse o total verdadeiro
aprenderia o tamanho da parte que lhe foi negada, então o console nunca o
mostra. Uma contagem que pode estar aquém diz isso: `82` significa que a
caminhada foi completa, `82+` significa que algum galho estourou o
orçamento do scan.

Ao lado dele: **Galhos** e **Datasets** ao alcance, e **Seu escopo** —
*Floresta inteira*, ou o número de galhos que a sua concessão cobre,
nomeados. **Você começa em** lista os seus galhos-raiz como links, e duas
listas soletram **o que você pode fazer aqui** e **o que você não pode**,
direto das capacidades que a sua concessão carrega. Duas pessoas abrindo a
mesma floresta podem ver duas Visões gerais diferentes, e as duas estão
dizendo a verdade.

## Próximos passos

- [Usando a floresta](./using.md) — Perguntar, Explorar, Playground e
  Dados: as superfícies de leitura do dia a dia.
- [Alimentando a floresta](./feeding.md) — a Ingestão, o Gardener e o
  Clipper: como documentos viram conhecimento curado.
- [Conectando uma IA](./connecting-ai.md) — parear uma chave, o console de
  Skills e plugar um agente MCP na sua Station.
