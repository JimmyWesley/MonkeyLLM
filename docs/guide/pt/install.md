# Instalar e implantar

[English](../en/install.md) · Português · [Español](../es/install.md)

[← Manual](./README.md)

A **Station** é o host auto-hospedável: um contêiner serve a API REST
(`/v1`), a superfície MCP (`/mcp`) e o console web **Studio** (`/`). O
Studio é um bundle estático embutido na imagem — não há serviço de
frontend separado para rodar. Lembre o que você está implantando: o
console é uma janela; as florestas atrás dele são o produto, e tudo o que
vale guardar vive em volumes, então o contêiner em si é descartável.

## Docker (recomendado)

A partir da raiz do repositório:

```bash
cp .env.example .env      # optional but recommended — fill in what you use
docker compose up --build -d
docker compose logs station   # the first boot says how to get in
```

### Os volumes

Uma queda, um rebuild ou uma atualização nunca perde dados, porque tudo o
que importa vive em volumes nomeados:

| Volume | Montado em | Guarda |
|---|---|---|
| `forests` | `/forests` | cada floresta: markdown, seu histórico git embutido, payloads `.db` de datasets, caches `_derived/` |
| `registry` | `/registry` | o registro do host (`station.db`): identidades, digests de chaves de API, concessões, auditoria — um único arquivo SQLite |
| `models` | `/models` | pesos GGUF para os sidecars opcionais de inferência local — multi-GB, mantidos fora da imagem |

> **Nota** — um quarto volume, `documents`, é montado em `/data` como o
> diretório de trabalho do contêiner e como um lugar para colocar arquivos
> que a Station pode espelhar. Troque-o por um bind mount de uma pasta sua
> (`./documents:/data`) e defina `MONKEYLLM_INGEST_ROOTS=/data` para
> deixar o console lê-la — a lista de permissão é vazia por padrão, e
> vazia significa nenhuma. Veja [Alimentando a floresta](./feeding.md).

### O essencial do `.env`

O arquivo compose lê o `.env` nativamente; o que ficar comentado cai nos
padrões do próprio código. O catálogo comentado é o
[`.env.example`](../../../.env.example) — a versão curta:

```dotenv
# Chat provider (any OpenAI-compatible /v1 endpoint):
MONKEYLLM_LLM_ENDPOINT=https://openrouter.ai/api/v1
MONKEYLLM_LLM_API_KEY=sk-or-your-key-here
MONKEYLLM_LLM_MODEL=google/gemma-3-12b-it

# Where the Station answers. Loopback by default — on a server, a reverse
# proxy reaches the container over the docker network, never the host port.
#STATION_PORT=8800
#STATION_BIND=127.0.0.1

# Hosts the MCP surface answers to; add your domain when serving through one.
#MONKEYLLM_STATION_ALLOWED_HOSTS=localhost,localhost:8800,127.0.0.1,127.0.0.1:8800
```

Um provedor configurado assim chega pré-configurado e somente leitura em
*Studio → Modelos*, marcado como "do ambiente" — a chave nunca é copiada
para o registro, e você a rotaciona editando a variável e reiniciando.

### Primeiro boot: a tela de configuração

Iniciar uma Station não cunha nada (spec J.2.5): o registro é exatamente
tão autoritativo depois do boot quanto antes dele, e o log do primeiro
boot nomeia a URL do console — `http://localhost:8800`. Abra-a, e uma
Station sem ninguém dentro mostra a **tela de configuração** (spec J.2.4):
escolha um usuário e uma senha e você é a pessoa **dona** — administradora
de todas as florestas, presentes e futuras, inclusive antes de a primeira
existir. A tela também oferece começar com uma floresta de demonstração já
semeada, uma vazia, ou nada.

![A tela de configuração da primeira execução, onde a primeira pessoa a chegar cria a conta dona](../assets/setup.png)

*(A captura de tela mostra o console em inglês.)*

A configuração existe apenas enquanto o registro não guarda credencial
nenhuma, e fecha permanentemente no momento em que é usada. Daí em diante
o console mostra o login comum.

> **Nota** — uma Station publicada em uma URL pública com o posto de dona
> em aberto é uma corrida contra estranhos. Aponte o seu domínio para ela
> e complete a configuração você mesmo antes de anunciar o endereço; o log
> do primeiro boot diz exatamente isso.

### Implantações sem navegador: a chave de bootstrap

Um servidor headless, uma CI ou um cliente só-MCP ainda precisam de uma
primeira porta. Inicie a Station uma vez com `--bootstrap-key` (ou defina
`MONKEYLLM_STATION_BOOTSTRAP_KEY=1` — UIs de plataforma sem campo de argv
podem pedir pelo ambiente) e o boot cunha **uma** chave de API de
autoridade plena, com o bit de dona, e a imprime no log exatamente uma vez
— só o digest dela é armazenado, então salve-a antes de os logs
rotacionarem.

A flag e a tela de configuração são duas portas para a mesma janela de uso
único: a que você usar a gasta, e cunhar a chave fecha a configuração. Um
reinício com a flag em uma Station que já tem uma forma de entrar não
cunha nada.

> **Nota** — você não precisa de `MONKEYLLM_STATION_ADMIN` /
> `MONKEYLLM_STATION_PASSWORD`. Essas duas são uma conta break-glass
> mantida no ambiente, comparada no login e nunca armazenada; defini-las
> *substitui* a tela de configuração em vez de complementá-la. Quando
> estão definidas, o log do primeiro boot nomeia o usuário com que entrar
> — ele nunca imprime a senha.

## Modelos locais

Nenhum provedor externo é necessário: dois sidecars llama.cpp acompanham
por trás de perfis do compose, então chat e embeddings podem rodar ao lado
da Station.

```bash
docker compose --profile local-llm --profile local-embed up -d
```

O primeiro início baixa os pesos do Hugging Face para o volume `models`
(padrões: Qwen2.5-7B-Instruct Q4_K_M para chat, bge-m3 Q8_0 para
embeddings — sobrescreva com `LLAMA_CHAT_HF` / `LLAMA_EMBED_HF`); os
inícios seguintes os reutilizam. Depois aponte a Station para os sidecars
pelos seus nomes de serviço no compose, no `.env`:

```dotenv
MONKEYLLM_LLM_ENDPOINT=http://llm:8090/v1
MONKEYLLM_EMBED_ENDPOINT=http://embed:8091/v1
```

A Station lê essas variáveis na inicialização, então o sidecar é só metade
do trabalho — defina a variável **e** reinicie a Station. Em uma
plataforma compose sem a flag `--profile` (Dokploy, Coolify), defina
`COMPOSE_PROFILES=local-llm,local-embed` no ambiente em vez disso; o
Compose a lê sozinho.

> **Nota** — os sidecars rodam em CPU por padrão, o que basta para o
> modelo navegador 7B Q4. Deixe o embedder desligado para manter a busca
> de entrada (`locate`) no seu contrato BM25-only — a camada vetorial é
> opcional por design.

## A partir do código-fonte

Instale o motor e a Station, construa o console uma vez e sirva.

```bash
pip install -e .                # the engine (add ".[dev]" for the test suite)
pip install -e apps/station     # the host: REST, MCP, serves the Studio
```

```bash
cd apps/studio
npm ci && npm run build         # the console, built once into apps/studio/dist
```

A Station serve o bundle de `apps/studio/dist`; se você pular o build, ela
responde exatamente com essa dica em vez de um console.

```bash
station serve --root /forests --registry /registry/station.db --port 8800 --writable
```

- `--root` — o diretório-registro de florestas (padrão `/forests`, ou
  `MONKEYLLM_STATION_ROOT`).
- `--registry` — o arquivo SQLite do registro do host (padrão
  `/registry/station.db`, ou `MONKEYLLM_STATION_REGISTRY`).
- `--port` — padrão `8800`; `--host` tem padrão `127.0.0.1`.
- `--writable` — aceita escritas, ingestão e criação de florestas. Sem ela
  a Station é somente leitura: leituras continuam funcionando, escritas
  são recusadas de saída com `E_READONLY`.
- `--bootstrap-key` e `--no-warm` funcionam aqui exatamente como no
  Docker.

> **Nota** — fora do Docker, nada carrega o `.env` por você (não há
> python-dotenv). Carregue-o no shell você mesmo:
> `set -a; source .env; set +a`.

## Referência de ambiente

Estas são as variáveis que o console de Integrações documenta (*Studio →
MCP / API / Integrações → Referência de ambiente*); o catálogo comentado
completo vive no `.env.example`.

| Variável | Significado |
|---|---|
| `MONKEYLLM_STATION_ADMIN`, `MONKEYLLM_STATION_PASSWORD` | Login break-glass do console. As duas precisam estar definidas; nunca armazenadas; rotacione reiniciando. |
| `MONKEYLLM_STATION_ALLOWED_HOSTS` | Hosts aos quais a superfície MCP responde. Adicione seu domínio, ou `*` para pular a checagem. |
| `STATION_PORT` | Porta publicada do serviço compose — `8800` por padrão. |
| `MONKEYLLM_LLM_ENDPOINT`, `MONKEYLLM_LLM_API_KEY`, `MONKEYLLM_LLM_PROVIDER` | Provedor de chat, pré-configurado e somente leitura em Modelos; a chave nunca é copiada para o registro. |
| `MONKEYLLM_LLM_MODEL`, `MONKEYLLM_LLM_MAX_TOKENS`, `MONKEYLLM_LLM_REASONING` | Id de modelo padrão, orçamento de resposta e modo de raciocínio desse provedor. |
| `MONKEYLLM_EMBED_ENDPOINT`, `MONKEYLLM_EMBED_MODEL`, `MONKEYLLM_EMBED_API_KEY` | Endpoint e modelo de embedding para a camada vetorial opcional. Sem definir, a busca de entrada mantém o contrato BM25-only. |
| `MONKEYLLM_S3_ENDPOINT` | Endpoint compatível com S3 para payloads remotos — MinIO, R2. |

## Atualização e somente leitura

**Atualizações** são um rebuild: `docker compose up --build -d` (ou um
redeploy, em um host gerenciado). A imagem é substituída, os volumes ficam
intocados, e o trabalho continua de onde estava.

**Tire um snapshot antes de atualizar.** Cada floresta se empacota como um
git bundle com o histórico completo (spec Part I):

```bash
docker compose exec station vine snapshot create --forest /forests/<name>
```

Faça backup do volume `registry` (um único arquivo SQLite) junto com os
snapshots — concessões e digests de chaves pertencem às florestas que
governam. `vine snapshot restore <bundle>` traz uma floresta de volta.

**Station somente leitura.** Remova `--writable` da linha `command:` e
faça o redeploy: leituras continuam funcionando, enquanto escritas,
ingestão e criação de florestas são recusadas de saída com `E_READONLY`.
Uma exceção deliberada: uma Station somente leitura ainda serve `POST
/v1/admin/reindex` (spec J.13.3), porque a reconstrução do catálogo
escreve apenas a camada descartável `_derived/` — um índice que a Station
nunca pudesse reparar degradaria para sempre.

## Para onde ir agora

A Station está no ar e a tela de configuração está esperando. [Primeiro
acesso](./first-access.md) percorre a criação da conta dona, a
apresentação de boas-vindas e a sua primeira floresta — e dali,
[Conectando a IA](./connecting-ai.md) é onde o cérebro começa a crescer.
