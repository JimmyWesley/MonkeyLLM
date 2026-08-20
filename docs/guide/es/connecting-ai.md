# Conectar tu IA

[English](../en/connecting-ai.md) · [Português](../pt/connecting-ai.md) · Español

[← Manual](./README.md)

Esta es la página a la que conduce todo el resto del manual. Todo
lo anterior [instalar la Station](./install.md), [iniciar
sesión](./first-access.md), [hacer preguntas](./using.md), [alimentar
documentos](./feeding.md) ocurrió a través del Studio. Pero el Studio es
una ventana. El producto es el bosque detrás de ella, y el bosque está
construido para que lo lea y lo cultive *tu propia IA*.

## Por qué

Cuando conectas un agente a un bosque, gana algo que una transcripción de
chat nunca le da: una **memoria persistente, gobernada y citable**.

- **Persistente** el bosque sobrevive a cada conversación. Lo que una
  sesión planta, la siguiente lo recuerda. Otras personas y otros agentes
  también lo alimentan, y sigue creciendo mientras tú lo conserves.
- **Gobernada** el agente sostiene una clave, la clave lleva tus
  concesiones, y cada lectura y cada escritura pasa por la misma costura de
  control que la consola. Lo que la clave no puede alcanzar no existe para
  el agente.
- **Citable** todo lo que el agente lee lleva un id de nodo. Las
  respuestas fundamentadas en el bosque pueden decir exactamente sobre qué
  nodos se paran.

Y no hay nada de segunda clase en la conexión. La Station no tiene canal
lateral privilegiado: lo que sea que el Studio te muestre, un cliente de API
o MCP con la misma clave también podría obtenerlo. La página Preguntar de la
consola llama al mismo `answer` que llamará tu agente. Conectar una IA no es
una integración atornillada a un costado es la puerta principal.

> **Nota** los snippets de abajo usan `https://station.example.com` como
> marcador de posición. Rara vez tienes que sustituir algo a mano: las
> consolas de Skills y de Integraciones muestran estos mismos snippets con la
> dirección real de tu Station y el bosque ya rellenados.

## Las tres superficies

Un contenedor, tres superficies, los mismos bosques gobernados. Las tres se
autentican con las mismas claves de API, verificadas en una sola puerta, y
todo acceso a un bosque pasa por el mismo control de alcance.

| Superficie | A quién sirve | Dónde |
|---|---|---|
| **Studio** | Humanos esta consola web | `https://station.example.com/` |
| **REST** | Apps, scripts e integraciones | `https://station.example.com/v1/…` |
| **MCP** | Cualquier harness de agente (streamable HTTP) | `https://station.example.com/mcp/` |

La superficie MCP es idéntica en contrato a un `vine serve` local: un agente
que funciona contra un bosque en tu propio disco funciona contra un bosque
servido por la Station sin más cambio que el endpoint y una credencial. El
alcance solo estrecha *contenido* nunca cambia la forma de una respuesta.

## Emparejar una clave

Tu agente necesita una credencial que sea *tuya* no una que un
administrador tenga que acuñar. Emparejar es esa puerta: `POST
/v1/auth/pair` no exige autenticación, igual que el login, toma tu usuario y
tu contraseña, y responde con una clave de API.

```bash
curl -sX POST https://station.example.com/v1/auth/pair \
  -H 'content-type: application/json' \
  -d '{"username": "you", "password": "…", "label": "claude-code"}'
```

La respuesta lleva `api_key` (se ve como `mk_…`), tu `principal`, las `caps`
de la clave y su `expires_at`. Lo que hace que una clave emparejada sea
segura de entregar a una máquina es que **solo puede estrechar, nunca
añadir**:

- **La máscara.** Una clave emparejada lleva una máscara de capacidades —
  `{read, ingest}` por defecto, y ese conjunto es también el techo: pedir
  `write`, `tend`, `query` o `admin` se rechaza como `E_SCHEMA`. Esos siguen
  siendo lo que un administrador acuña deliberadamente.
- **Concesiones ∩ máscara, en el momento del uso.** La autoridad efectiva de
  la clave son tus propias concesiones filtradas por la máscara, calculadas
  en vivo una concesión revocada después del emparejamiento desaparece de
  la clave de inmediato. Una clave emparejada en manos de un dueño sigue
  siendo rechazada en toda ruta de admin.
- **Siempre caduca.** 90 días por defecto, 365 como máximo; no existe
  "ilimitado". La clave se muestra una sola vez solo se guarda su digest.
- **Autoservicio por construcción.** El emparejamiento no alcanza nada que
  tu contraseña no alcanzara ya, así que ninguna puerta de admin se
  interpone. Tanto `login` como `pair` tienen límite de tasa, y el rechazo
  nunca revela si un usuario existe.

La clave vive donde viven todas las claves: la consola de Accesos la lista,
y quien administra puede revocarla ahí en cualquier momento (ver
[Administrar la Station](./managing.md)).

## Claude Code en dos comandos

Si tu agente es Claude Code, la conexión entera es la llamada de
emparejamiento de arriba más un registro:

```bash
claude mcp add --transport http monkeyllm https://station.example.com/mcp/ \
  --header "Authorization: Bearer mk_…"
```

Desde entonces, las tools del bosque están en cada sesión. Dos cosas que
vale la pena saber en la primera llamada:

- Haz que el agente llame primero a `forests()`. Una clave con alcance no
  tiene índice maestro; esa llamada devuelve los bosques que la clave puede
  usar y las raíces por donde empezar.
- La superficie MCP solo responde a los hosts listados en
  `MONKEYLLM_STATION_ALLOWED_HOSTS`. Si sirves a través de un dominio,
  nómbralo ahí (o `*` para omitir la verificación) cada solicitud sigue
  necesitando una clave.

## La consola de Skills

Un agente conectado sabe que las tools existen; todavía no tiene el *hábito*
de usarlas. La consola de Skills cierra esa brecha. Una skill es un pequeño
archivo de instrucciones que un runtime de agente carga, y esta le enseña a
tu agente a tratar el bosque abierto como su memoria: recordar a partir de
él antes de responder, guardar lo que vale la pena conservar, citar los ids
de los nodos que leyó.

![La consola de Skills, generando la skill de memoria para esta Station y este bosque](../assets/skills.png)

*(Las capturas de pantalla muestran la consola en inglés.)*

La consola te guía por los mismos tres pasos que esta página empareja una
clave, apunta Claude Code a la Station, entrégale el archivo y cada
snippet en ella ya lleva la dirección de la Station y el nombre del bosque
abierto. La skill se genera en tu navegador, para exactamente ese
despliegue; la Station no gana ningún endpoint por ella. Está disponible
para cualquiera cuya clave pueda hacer `read` sobre el bosque nunca detrás
de una puerta de admin, porque el emparejamiento hizo de la credencial un
autoservicio y aprender a conectarse también debe serlo.

Para Claude Code, el archivo se instala en:

```
~/.claude/skills/monkeyllm-memory/SKILL.md
```

Vale la pena previsualizar las palabras del propio archivo, porque son el
contrato que tu agente seguirá. Bajo el título **"This forest is your
memory"** (este bosque es tu memoria), enseña tres secciones:

- **"Recall before you answer"** (recuerda antes de responder) para
  cualquier pregunta que el bosque pudiera responder, primero recordar y
  después razonar: `answer` cuando la respuesta del bosque *es* la
  respuesta; `harvest` cuando el agente va a razonar él mismo sobre el
  material; `locate` → `look` → `pick` para navegar; `sniff` para texto
  literal dentro de los cuerpos; `query` para datasets, si la clave lleva
  `query` después de un `look`, porque las `notes` de un dataset dicen
  qué significan las columnas. Y: citar ids de nodo para todo lo afirmado a
  partir del bosque.
- **"Save what is worth keeping"** (guarda lo que vale la pena conservar) —
  cuando el usuario dice algo durable (una decisión, un hecho, una
  preferencia, una corrección), ofrecerse a guardarlo, con la escritura que
  la clave realmente permite: `ingest` un documento markdown a través del
  Gardener es la escritura que una clave emparejada lleva por defecto;
  `plant` y `graft` se enseñan solo para claves que llevan `write`.
  Escribir en inglés y mantener honesto el resumen el resumen es cómo se
  encontrará la nota.
- **"Respect the contract"** (respeta el contrato) la clave decide lo que
  el agente ve y lo que puede escribir; nunca rodear un rechazo decir qué
  fue rechazado y qué capacidad necesita. Toda lectura tiene presupuesto, y
  `truncated: true` significa preguntar más estrecho, no reintentar más
  fuerte. Los datasets cambian a través de `tend` solo donde la clave lo
  lleva, una sentencia a la vez, nunca DDL.

> **Nota** el cuerpo del archivo de la skill está en inglés sin importar
> el idioma de la consola, a propósito: le habla al modelo, no a ti. El
> recorrido a su alrededor se traduce como cualquier otra parte de la
> consola.

## Las tools MCP

Las tools son los primitivos del motor más los compuestos, cada una detrás
de la capacidad que necesita. `forests` responde a cualquier clave válida;
todo lo demás está detrás de la puerta que se indica.

| Tool | Exige | Qué hace |
|---|---|---|
| `forests` | cualquier clave | Lista los bosques que esta clave puede usar, con capacidades y raíces de partida. |
| `locate` | `read` | Puntos de entrada ordenados sobre metadatos curados dónde caer dentro del bosque. |
| `look` | `read` | Digest barato de un nodo: resumen, aristas, hijos, estadísticas. |
| `move` | `read` | Los vecinos de un nodo a lo largo de aristas tipadas. |
| `pick` | `read` | Lee el cuerpo, o una sección de él. |
| `scan` | `read` | Filtra los nodos de una rama por metadatos. |
| `sniff` | `read` | Búsqueda literal dentro de los cuerpos los hechos que los resúmenes no llevan. |
| `calendar` | `read` | Dónde está en el tiempo el material del bosque: cuántos nodos guarda cada período, del más reciente hacia atrás. |
| `harvest` | `read` | Recuperación de un solo tiro: evidencia ordenada con fragmentos exactos, sin saltos. |
| `answer` | `read` | Una respuesta fundamentada escrita por el modelo enlazado al bosque, con su evidencia. |
| `view` | `read` | El payload de imagen de un nodo media, como contenido de imagen que un cliente multimodal lee en su propio contexto. |
| `query` | `query` | SQL de solo lectura contra un nodo dataset. |
| `plant` | `write` | Crea un nodo. |
| `graft` | `write` | Edita un nodo. |
| `tend` | `tend` | Escritura de dataset de una sola sentencia. |
| `ingest` | `ingest` | Mete documentos en el bosque a través del Gardener. |

Toda llamada de búsqueda acepta una ventana opcional `since`/`until` sobre
las fechas de los nodos, y `calendar` dice qué períodos guardan algo — así
"qué decidimos la semana pasada" son dos fechas leídas de un mapa en lugar de
un barrido del bosque entero. `look` y `pick` también aceptan una lista de
ids: una llamada, un presupuesto, cada id rendido cuentas.

Un modelo mental razonable: `answer` y `harvest` son los de un solo tiro, la
familia `locate`/`look`/`move`/`pick`/`scan`/`sniff` es navegación, `query`
y `tend` son el par de datasets, y `plant`/`graft`/`ingest` son cómo crece
el bosque.

## La superficie REST en cinco minutos

Los scripts y las aplicaciones hablan con los mismos bosques por HTTP/JSON
llano. Envía la clave como token bearer en cada solicitud. Si en cambio
tienes usuario y contraseña, un login devuelve un **token de sesión** una
clave ordinaria con 12 horas de vida de modo que, pasada la puerta, hay
exactamente un camino de autorización:

```bash
curl -sX POST https://station.example.com/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username": "admin", "password": "…"}'
```

Una sola forma de ruta cubre todos los primitivos: haz POST de los
argumentos como JSON al nombre del primitivo, por bosque —
`POST /v1/forests/{forest}/{name}`. Tres ejemplos, para un bosque llamado
`handbook`:

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

Los fallos son un solo sobre, mapeado sobre códigos HTTP, y el `hint` está
escrito para quien llama muéstralo:

```json
{
  "error": {
    "code": "E_FORBIDDEN",
    "message": "missing or invalid API key",
    "hint": "Send Authorization: Bearer <key>."
  }
}
```

> **Nota** fuera de alcance es indistinguible de ausente. Un nodo que la
> clave no puede ver reporta `E_NOT_FOUND`, byte a byte igual que un nodo
> que no existe. Es deliberado: un error que dijera "prohibido" revelaría
> por sí mismo el nodo.

## Cualquier otro runtime

Nada de lo de arriba es particular de Claude Code más allá de la ruta de
instalación. Cualquier runtime capaz de MCP se conecta con el mismo endpoint
y la misma clave emparejada regístralo donde sea que tu runtime configure
servidores MCP:

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

Entrégale las mismas instrucciones del `SKILL.md`, adaptadas a como sea que
tu runtime cargue system prompts o skills. El archivo le habla al modelo,
así que viaja.

## Lo que tu agente nunca puede hacer

Conectar una IA no abre un agujero en la gobernanza el agente es un
principal como cualquier otro, y el contrato se sostiene en todas las
superficies.

**Los alcances se sostienen.** Una concesión ata a un principal a un bosque
con capacidades y alcance por prefijo de rama: listas de permitidos y
negados de prefijos de subárbol, negar gana a cualquier profundidad, y sin
concesión no hay acceso. Las capacidades son exactamente seis:

| Capacidad | Permite |
|---|---|
| `read` | leer el material |
| `query` | ejecutar SQL de solo lectura |
| `write` | crear y editar nodos |
| `tend` | cambiar filas de dataset |
| `ingest` | añadir documentos nuevos |
| `admin` | dar acceso a otras personas |

El filtrado por alcance se aplica *antes* del ranking y de los presupuestos,
así que un agente no puede inferir contenido oculto a partir de los conteos
de resultados ni de las marcas de truncado y un nodo fuera de alcance
responde exactamente como uno que falta.

**Los presupuestos se sostienen.** Todo primitivo de lectura responde dentro
de un presupuesto de tokens declarado, y un resultado recortado siempre dice
`truncated: true` nunca un corte silencioso:

| Llamada | Presupuesto (tokens) |
|---|---|
| `look` | 500 |
| `move` | 600 |
| `locate`, `scan`, `sniff`, `calendar` | 800 cada uno |
| `query` | 2000 |
| `pick`, `harvest` | 4000 |

Un cuerpo por encima del presupuesto de `pick` vuelve como su esquema más
una pista para pedir una sección. Los presupuestos son la razón de que un
bosque siga siendo navegable por un modelo pequeño y de que la skill
enseñe "ask narrower, not retry harder": pregunta más estrecho en vez de
reintentar más fuerte.

**Las escrituras siguen disciplinadas.** `plant` y `graft` son commits de
git atómicos dentro del bosque; los datasets cambian solo a través de
`tend`, una sentencia DML a la vez, WHERE obligatorio en UPDATE y DELETE,
nunca DDL. No existe ruta por la que un agente borre un nodo.

**La auditoría lo ve todo.** Toda lectura con alcance aterriza en el
registro del host: principal, bosque, primitivo, un digest de los
argumentos, el tamaño del resultado y la marca de tiempo nunca cuerpos.
Toda escritura es un commit de git sellado con el principal que actúa. Qué
agente leyó qué nodos, y en qué orden, es reconstruible después del hecho —
ver [Administrar la Station](./managing.md).

## Dónde vive el manual completo

Esta página es el camino del operador. La referencia exhaustiva cada ruta,
cada tool, cada perilla de despliegue y variable de entorno vive dentro
del propio Studio, en la consola **MCP / API / Integraciones**. Está detrás
de admin, porque habla el vocabulario del administrador: credenciales,
hosts, el contenedor.

![La consola de Integraciones: el manual del despliegue, dentro del despliegue que describe](../assets/integrations.png)

Es una consola y no un sitio estático a propósito: cada ejemplo ahí lleva el
origen de esa misma Station, así que cada snippet está listo para copiar
para el host que el administrador está mirando de verdad documentación que
no puede desviarse del despliegue que documenta. Cuando algo de esta página
y algo de esa consola no concuerden, confía en la consola: se está
describiendo a sí misma.
