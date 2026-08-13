# Instalación y despliegue

[English](../en/install.md) · [Português](../pt/install.md) · Español

[← Manual](./README.md)

La **Station** es el host autoalojable: un contenedor sirve la API REST
(`/v1`), la superficie MCP (`/mcp`) y la consola web **Studio** (`/`).
El Studio es un bundle estático construido dentro de la imagen — no hay
ningún servicio de frontend aparte que ejecutar. Recuerda qué estás
desplegando: la consola es una ventana; los bosques detrás de ella son el
producto, y todo lo que vale la pena conservar vive en volúmenes, así que
el contenedor en sí es desechable.

## Docker (recomendado)

Desde la raíz del repositorio:

```bash
cp .env.example .env      # optional but recommended — fill in what you use
docker compose up --build -d
docker compose logs station   # the first boot says how to get in
```

### Los volúmenes

Un fallo, una reconstrucción o una actualización nunca pierde datos, porque
todo lo que importa vive en volúmenes con nombre:

| Volumen | Montado en | Contiene |
|---|---|---|
| `forests` | `/forests` | cada bosque: markdown, su historial git embebido, payloads `.db` de datasets, cachés `_derived/` |
| `registry` | `/registry` | el registro del host (`station.db`): principals, digests de claves de API, concesiones, auditoría — un solo archivo SQLite |
| `models` | `/models` | pesos GGUF para los sidecars opcionales de inferencia local — varios GB, fuera de la imagen |

> **Nota** — un cuarto volumen, `documents`, se monta en `/data` como
> directorio de trabajo del contenedor y como lugar donde poner archivos
> que la Station puede espejar. Cámbialo por un bind mount de una carpeta
> tuya (`./documents:/data`) y define `MONKEYLLM_INGEST_ROOTS=/data` para
> que la consola pueda leerla — la lista de permitidos está vacía por
> defecto, y vacía significa ninguna. Ver
> [Alimentar el bosque](./feeding.md).

### Lo esencial de `.env`

El archivo compose lee `.env` de forma nativa; todo lo que quede comentado
cae en los valores por defecto del propio código. El catálogo comentado es
[`.env.example`](../../../.env.example) — la versión corta:

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

Un proveedor configurado así llega preconfigurado y en solo lectura en
*Studio → Modelos*, marcado como “del entorno” — la clave nunca se copia
al registro, y la rotas editando la variable y reiniciando.

### Primer arranque: la pantalla de configuración

Arrancar una Station no acuña nada (spec J.2.5): el registro es exactamente
tan autoritativo después del arranque como antes, y el log del primer
arranque nombra la URL de la consola — `http://localhost:8800`. Ábrela, y
una Station sin nadie dentro muestra la **pantalla de configuración**
(spec J.2.4): elige un usuario y una contraseña y eres la persona
**propietaria** — administradora de cada bosque, presente y futuro,
incluso antes de que exista el primero. La pantalla también ofrece
empezarte con un bosque de demostración ya sembrado, uno vacío o nada en
absoluto.

![La pantalla de configuración de la primera ejecución, donde la primera persona en llegar crea la cuenta propietaria](../assets/setup.png)

*(Las capturas de pantalla muestran la consola en inglés.)*

La configuración existe solo mientras el registro no guarda ninguna
credencial, y se cierra permanentemente en el momento en que se usa. Desde
entonces la consola muestra el inicio de sesión ordinario.

> **Nota** — una Station publicada en una URL pública con el asiento de
> propietario sin reclamar es una carrera contra desconocidos. Apunta tu
> dominio hacia ella y completa tú la configuración antes de anunciar la
> dirección; el log del primer arranque lo dice tal cual.

### Despliegues sin navegador: la clave bootstrap

Un servidor sin interfaz, la CI o un cliente solo-MCP siguen necesitando
una primera puerta. Arranca la Station una vez con `--bootstrap-key` (o
define `MONKEYLLM_STATION_BOOTSTRAP_KEY=1` — las UIs de plataformas sin
campo de argv pueden pedirlo a través del entorno) y el arranque acuña
**una** clave de API con autoridad plena, con el bit de propietario, y la
imprime en el log exactamente una vez — solo se almacena su digest, así
que guárdala antes de que los logs roten.

La bandera y la pantalla de configuración son dos puertas hacia la misma
ventana de un solo uso: la que uses la gasta, y acuñar la clave cierra la
configuración. Un reinicio con la bandera en una Station que ya tiene una
forma de entrar no acuña nada.

> **Nota** — no necesitas `MONKEYLLM_STATION_ADMIN` /
> `MONKEYLLM_STATION_PASSWORD`. Esas dos son una cuenta de emergencia
> guardada en el entorno, comparada al iniciar sesión y nunca almacenada;
> definirlas *reemplaza* la pantalla de configuración en lugar de
> complementarla. Cuando están definidas, el log del primer arranque
> nombra el usuario con el que iniciar sesión — nunca imprime la
> contraseña.

## Modelos locales

No se necesita ningún proveedor externo: dos sidecars llama.cpp vienen
detrás de perfiles de compose, para que el chat y los embeddings puedan
correr junto a la Station.

```bash
docker compose --profile local-llm --profile local-embed up -d
```

El primer arranque descarga los pesos desde Hugging Face al volumen
`models` (por defecto: Qwen2.5-7B-Instruct Q4_K_M para chat, bge-m3 Q8_0
para embeddings — se cambian con `LLAMA_CHAT_HF` / `LLAMA_EMBED_HF`); los
arranques siguientes los reutilizan. Después apunta la Station a los
sidecars por sus nombres de servicio de compose, en `.env`:

```dotenv
MONKEYLLM_LLM_ENDPOINT=http://llm:8090/v1
MONKEYLLM_EMBED_ENDPOINT=http://embed:8091/v1
```

La Station lee estas variables al arrancar, así que el sidecar es solo la
mitad del trabajo — define la variable **y** reinicia la Station. En una
plataforma de compose sin bandera `--profile` (Dokploy, Coolify), define
`COMPOSE_PROFILES=local-llm,local-embed` en el entorno; Compose lo lee por
su cuenta.

> **Nota** — los sidecars corren en CPU por defecto, lo que basta para el
> navegador 7B Q4. Deja el embedder apagado para mantener la búsqueda de
> entrada (`locate`) en su contrato solo-BM25 — la capa vectorial es
> opcional por diseño.

## Desde el código fuente

Instala el motor y la Station, construye la consola una vez y sirve.

```bash
pip install -e .                # the engine (add ".[dev]" for the test suite)
pip install -e apps/station     # the host: REST, MCP, serves the Studio
```

```bash
cd apps/studio
npm ci && npm run build         # the console, built once into apps/studio/dist
```

La Station sirve el bundle desde `apps/studio/dist`; si te saltas la
construcción, responde con exactamente esa pista en lugar de una consola.

```bash
station serve --root /forests --registry /registry/station.db --port 8800 --writable
```

- `--root` — el directorio del registro de bosques (por defecto
  `/forests`, o `MONKEYLLM_STATION_ROOT`).
- `--registry` — el archivo SQLite del registro del host (por defecto
  `/registry/station.db`, o `MONKEYLLM_STATION_REGISTRY`).
- `--port` — por defecto `8800`; `--host` es por defecto `127.0.0.1`.
- `--writable` — acepta escrituras, ingesta y creación de bosques. Sin él
  la Station es de solo lectura: las lecturas siguen funcionando, las
  escrituras se rechazan de entrada con `E_READONLY`.
- `--bootstrap-key` y `--no-warm` funcionan aquí exactamente igual que en
  Docker.

> **Nota** — fuera de Docker, nada carga `.env` por ti (no hay
> python-dotenv). Cárgalo tú en la shell:
> `set -a; source .env; set +a`.

## Referencia de entorno

Estas son las variables que documenta la consola de integraciones
(*Studio → MCP / API / Integraciones → Referencia de entorno*); el
catálogo completo comentado vive en `.env.example`.

| Variable | Significado |
|---|---|
| `MONKEYLLM_STATION_ADMIN`, `MONKEYLLM_STATION_PASSWORD` | Inicio de sesión de emergencia de la consola. Ambas deben estar definidas; nunca se almacenan; se rotan reiniciando. |
| `MONKEYLLM_STATION_ALLOWED_HOSTS` | Hosts a los que responde la superficie MCP. Añade tu dominio, o `*` para saltarte la comprobación. |
| `STATION_PORT` | Puerto publicado del servicio de compose — `8800` por defecto. |
| `MONKEYLLM_LLM_ENDPOINT`, `MONKEYLLM_LLM_API_KEY`, `MONKEYLLM_LLM_PROVIDER` | Proveedor de chat, preconfigurado y en solo lectura bajo Modelos; la clave nunca se copia al registro. |
| `MONKEYLLM_LLM_MODEL`, `MONKEYLLM_LLM_MAX_TOKENS`, `MONKEYLLM_LLM_REASONING` | Id de modelo por defecto, presupuesto de respuesta y modo de razonamiento para ese proveedor. |
| `MONKEYLLM_EMBED_ENDPOINT`, `MONKEYLLM_EMBED_MODEL`, `MONKEYLLM_EMBED_API_KEY` | Endpoint y modelo de embeddings para la capa vectorial opcional. Sin definir, la búsqueda de entrada se queda en su contrato solo-BM25. |
| `MONKEYLLM_S3_ENDPOINT` | Endpoint compatible con S3 para payloads remotos — MinIO, R2. |

## Actualizaciones y solo lectura

**Las actualizaciones** son una reconstrucción: `docker compose up --build
-d` (o redespliega, en un host administrado). La imagen se reemplaza, los
volúmenes quedan intactos, y el trabajo continúa donde estaba.

**Haz una instantánea antes de actualizar.** Cada bosque se empaqueta como
un bundle de git con todo su historial (spec Parte I):

```bash
docker compose exec station vine snapshot create --forest /forests/<name>
```

Respalda el volumen `registry` (un archivo SQLite) junto con las
instantáneas — las concesiones y los digests de claves pertenecen a los
bosques que gobiernan. `vine snapshot restore <bundle>` trae un bosque de
vuelta.

**Station de solo lectura.** Quita `--writable` de la línea `command:` y
redespliega: las lecturas siguen funcionando, mientras que las escrituras,
la ingesta y la creación de bosques se rechazan de entrada con
`E_READONLY`. Una excepción deliberada: una Station de solo lectura sigue
sirviendo `POST /v1/admin/reindex` (spec J.13.3), porque una
reconstrucción del catálogo escribe solo la capa desechable `_derived/` —
un índice que la Station nunca pudiera reparar se degradaría para siempre.

## A dónde ir después

La Station está en marcha y la pantalla de configuración espera. [Primer
acceso](./first-access.md) recorre la reclamación del asiento de
propietario, el recorrido de bienvenida y tu primer bosque — y desde ahí,
[Conectar tu IA](./connecting-ai.md) es donde el cerebro empieza a crecer.
