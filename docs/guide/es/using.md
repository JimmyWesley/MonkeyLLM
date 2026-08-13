# Usar el bosque

[English](../en/using.md) · [Português](../pt/using.md) · Español

[← Manual](./README.md)

Cuatro consolas hacen el trabajo diario de leer un bosque. **Preguntar**
responde preguntas con evidencia. **Explorar** muestra el bosque en sí —
como grafo, como archivos, como árbol. **Datos** es un cliente de base de
datos sobre tus datasets. **Playground** te muestra las llamadas crudas,
exactamente como las hace un agente.

Las cuatro son ventanas sobre las mismas primitivas que tu IA recibe por
MCP. Nada en esta página es un poder exclusivo de la consola: todo lo que
puedes hacer aquí, un agente con la misma clave puede hacerlo desde fuera.

## Preguntar

Preguntar es la consola de llegada porque no necesita explicación:
escribes una pregunta y recibes una respuesta. Lo que la distingue de una
ventana de chat es lo que ocurre por debajo, y cuánto de eso se te
muestra. La búsqueda corre primero dentro de tu alcance — determinista,
barata, sin ningún modelo de por medio — y solo entonces el modelo
enlazado del bosque lee lo que se encontró y escribe la respuesta.

![La consola Preguntar: una pregunta, su respuesta y la lista de evidencia con los nodos realmente leídos](../assets/ask.png)

(Las capturas de pantalla muestran la interfaz en inglés.)

**La evidencia no es decoración.** Cada id listado bajo la respuesta fue
realmente leído para producirla. Haz clic en uno y se abre en Explorar,
así que una afirmación de la respuesta está siempre a un clic del texto
del que salió. El panel **Lo que leyó** va más lejos: los fragmentos y
las secciones exactos que recibió el modelo, con sección y número de
línea — el resumen decide *qué* nodo, el cuerpo es lo que se lee, y este
panel muestra las dos mitades.

Unos pocos controles acompañan la caja de pregunta:

- **Cuánto leer** — cuántos nodos entrega la recuperación al modelo
  (2, 3 o 6).
- **Tamaño de la respuesta** — un deslizador desde “Auto” hasta un techo
  duro. Es una preferencia tuya: se recuerda en tu navegador, por
  persona, y nunca entra en la dirección. “Auto” no envía nada y mandan
  las reglas del propio enlace del bosque. Cuando sí fijas un tamaño, no
  es solo un corte — el tamaño declarado se escribe en el prompt, así que
  el modelo da forma a la respuesta para que quepa, en vez de quedar
  truncada a media frase (spec J.10.8).
- **Dejar que salte (búsqueda agéntica)** — en vez de un barrido
  determinista, el modelo sostiene las primitivas y navega — locate,
  look, move, pick — hasta poder responder. Cuesta una llamada al modelo
  por salto, y el panel **Por dónde fue** muestra cada salto: qué eligió
  el modelo, qué volvió, y los dos relojes (la llamada al bosque, y el
  turno del modelo que decidió hacerla).
- **Banco de respuestas** — encendido por defecto, porque es gratis: una
  pregunta ya respondida sobre este bosque sin cambios se sirve del banco
  al instante, sin pagar el modelo otra vez. Apágalo para comprar una
  ejecución nueva y reemplazar la guardada.

**Las respuestas servidas lo dicen.** Una respuesta servida lleva la
insignia **Del banco**, y el costo registrado nunca se vuelve a cobrar.
No es un caché tonto: la recuperación corre igual en cada pregunta, y la
respuesta guardada se sirve solo mientras lo que se leería hoy coincide
con lo que se leyó entonces — un bosque que cambió bajo la pregunta
recibe una respuesta fresca, no una rancia (spec J.10.7).

**Las respuestas pueden mostrar las imágenes que el modelo realmente
leyó.** Cuando el material contiene un nodo `media` — una captura de
pantalla, un diagrama, una foto que entró con descripción — el modelo
puede incrustarla en la respuesta como `![caption](media:<node id>)`
(spec J.10.9). La consola resuelve esa referencia con *tu* credencial: un
id que el modelo inventó, o uno que tu alcance no puede leer, se
renderiza como su leyenda y nada más — nunca un error que eclipse la
respuesta. La evidencia de tipo `media` muestra su imagen junto a su
resumen de todos modos, porque “de qué se construyó esta respuesta”
incluye los píxeles.

Puedes llevarte una respuesta contigo — **Copiar cURL** (la misma
llamada, lista para un script), **Descargar .md** (con las referencias
`media:` reescritas a direcciones descargables) o **Guardar en PDF**.
Cada ejecución queda además en el historial propio de tu navegador —
solo en esta máquina, nunca enviado a la Station — para que restaures
una ejecución vieja y la compares con una fresca.

> **Nota** — las respuestas se leen del texto de los nodos. Una pregunta
> cuya respuesta es un agregado sobre filas de dataset se rechaza en vez
> de adivinarse; usa la consola Datos para esas.

## Explorar

Explorar es una sola consola con tres maneras de mirar el mismo bosque
(spec J.5.4). La selección sobrevive al cambio de modo, deliberadamente:
pasar del grafo a los archivos no es una pregunta nueva, es el mismo nodo
visto de otra forma.

![La consola Explorar en modo grafo: el bosque como nodos y senderos, con el calor y la estructura visibles](../assets/explore.png)

| Modo | Muestra | Sirve para |
|---|---|---|
| **Grafo** | nodos y senderos tipados, dispuestos espacialmente | ver la forma: regiones calientes, propuestas, atajos, huérfanos |
| **Archivos** | el bosque tal como vive en disco, un archivo abierto a la vez | leer — la prosa como prosa, una base de datos como tabla, la fuente a un clic |
| **Árbol** | la jerarquía de ramas como lista, con búsqueda | alcances estrechos, y encontrar dónde vive algo |

En el **grafo**, cada canal visual es un hecho que el bosque guarda: el
color es el tipo del nodo o su rama de origen, el tamaño y el brillo
siguen al calor (lo que depositan las lecturas de feromona), y un enlace
propuesto — uno que el Ranger administra, aún no promovido — se dibuja
distinto de un sendero curado. La línea de tiempo reproduce el
crecimiento del bosque en orden de plantado. Arrastra un nodo, haz zoom
con el scroll, clic para seleccionar, doble clic para abrirlo en
Archivos.

En **Archivos**, un nodo se abre como lo que es. La vista **Lectura**
renderiza el markdown; **Fuente** muestra con honestidad las dos mitades
guardadas — el pasaporte tal como lo guarda el catálogo, y el cuerpo tal
como está almacenado. El panel lateral lleva tres pestañas: **Pasaporte**
(tipo, resumen, etiquetas, senderos de salida), **Índice** (la entrada de
este nodo en el índice de su padre — derivada, nunca editada a mano) y
**Senderos** (calor, y con qué conecta). El `.db` de un dataset se abre
como tablas navegables — servidas por la misma primitiva de solo lectura
`query` que en todas partes, con tope y tiempo máximo, nunca un canal
lateral privado.

**Leer un pasaporte vs. leer un cuerpo:** el pasaporte (lo que devuelve
`look`) es el olor curado — id, tipo, resumen, etiquetas, senderos. Es lo
que la búsqueda coteja y por lo que navega un agente. El cuerpo (lo que
devuelve `pick`) es el texto completo, y cuesta más leerlo — un cuerpo
por encima del presupuesto de lectura vuelve como su esquema, sección por
sección, en vez de fingirse entero.

**Editar está gobernado.** Con la capacidad de escritura, el botón
**Editar** abre el editor de nodos: texto enriquecido o markdown, a tu
elección. El id, el tipo y la fecha de creación quedan fijos durante toda
la vida del nodo; el resumen se valida contra su presupuesto de tokens;
un cuerpo grande se edita una sección a la vez, porque una sección es lo
que un `graft` reemplaza de forma atómica. El panel **Cambios
pendientes** muestra exactamente lo que se enviará, con la forma que
recibe la API — y el resultado es un commit de git sellado con tu
principal. Ninguna superficie, esta consola incluida, escribe un archivo
directamente: el commit, la validación y el registro de auditoría *son*
la escritura.

La prosa recién nacida entra por la pestaña **Escribir** de la consola de
ingesta: componer con revisión — el mismo pipeline que recorre un archivo
subido lee tu texto, escribe el resumen, propone dónde conecta y te
muestra todo antes de plantar nada. Ver
[Alimentar el bosque](./feeding.md).

## Datos

Los datasets son el único tipo de nodo cuyo contenido la búsqueda de
texto no puede ver: los hechos viven en un payload SQLite junto al
pasaporte. La consola Datos es un cliente de base de datos sobre ellos —
y todo lo que hace pasa por las mismas dos primitivas que recibe un
agente: `query` para leer, `tend` para escribir.

![La consola Datos: las tablas de un dataset, sus filas y la pestaña SQL](../assets/data.png)

Elige un dataset y sus tablas aparecen debajo; la primera abre con sus
filas ya cargadas. Cuatro pestañas:

| Pestaña | Qué contiene |
|---|---|
| **Filas** | la tabla como un grid — pagina, ordena, filtra, exporta CSV y (con la capacidad `tend`) edita |
| **Estructura** | columnas, tipos y la declaración guardada — de solo lectura por diseño |
| **SQL** | consultas libres de solo lectura, con los ejemplos del propio manual a un clic |
| **Notas** | lo que le enseñas al agente sobre estos datos |

**Cada dataset lleva su propio mapa.** Al ingerir, el Gardener escribe un
`## Query manual` (cada tabla, cada columna) y `## Sample rows` (las
primeras tres filas por tabla, celdas recortadas) en el pasaporte — para
que un agente, o tú, vea qué es consultable sin abrir un payload de cinco
gigabytes. La pestaña SQL ofrece las consultas de ejemplo del manual como
puntos de partida.

**La lectura tiene presupuesto, y truncado significa estrecha tu
pregunta.** `query` acepta un único `SELECT` (o `WITH`), inyecta
`LIMIT 200` cuando no das ninguno, y acota la *respuesta* a 2,000 tokens
(spec C.5.1). Dos banderas te dicen dos cosas distintas:

| Bandera | Qué pasó | La salida |
|---|---|---|
| `limited` | se alcanzó el `LIMIT 200` inyectado — la consulta coincidía con más filas | estrecha tu filtro |
| `truncated` | el presupuesto de tokens descartó filas que la consulta devolvió | estrecha tu proyección — nombra las columnas que necesitas |

La lista `columns` nunca se descarta: un resultado cuyas filas fueron
todas rechazadas todavía te dice exactamente qué columnas produce tu
sentencia, que es el mapa de vuelta. Y las filas ausentes *existen* —
`truncated` nunca significa “nada más coincidió”. Los agregados no se
ven afectados por construcción: `SELECT SUM(x)` es una fila corta, y
calcular el agregado en SQL en vez de traer filas es la jugada correcta
para ti y para el agente por igual.

**Las notas son donde una persona le enseña al agente** (spec C.2.1). La
estructura y las filas de muestra se leen del archivo; el *significado*
no — qué columna es USD y cuál BRL, qué representa un código de estado,
qué join responde la pregunta que la gente realmente hace. Lo que
escribas en la pestaña Notas vuelve en cada `look` de este dataset, y
viaja con él a cada respuesta que el host arma — antes de que se escriba
cualquier SQL. Se guarda como un `graft`, un commit; el Gardener nunca lo
sobrescribe, así que sobrevive a cada sync y a cada reimportación.

**Las escrituras son sentencias sueltas, mostradas antes.** Haz doble
clic en una celda para editarla, usa la papelera para borrar una fila,
añade filas con **Nueva fila** — los cambios quedan en pantalla,
resaltados y reversibles, hasta que guardes. Al guardar se muestran las
sentencias `INSERT`, `UPDATE` y `DELETE` exactas que ejecutará `tend`;
nada se escribe hasta que las apliques, y cada sentencia se vuelve su
propio commit de git. `tend` exige un `WHERE` en cada `UPDATE` y
`DELETE`, y rechaza DDL para siempre (spec C.10): una tabla nace por el
schema declarativo de `plant` y cambia reconstruyéndose — por eso la
pestaña Estructura no tiene botón de editar, en vez de tener uno que
siempre falla.

> **Nota** — crear e importar datasets también vive aquí: **Nuevo
> dataset** declara tablas y columnas y las planta en una sola llamada
> (la consola nunca escribe DDL), e **Importar** envía archivos `.db`,
> `.csv`, `.json`, `.xls` y `.xlsx` al Gardener como un lote de ingesta
> hecho y derecho — nada se parsea en el navegador. Ver
> [Alimentar el bosque](./feeding.md).

## Playground

El Playground es la ventana honesta hacia MCP: las mismas llamadas que
hace un agente, con los mismos presupuestos — nada aquí es una
simulación. Elige una primitiva, completa sus argumentos, ejecútala y lee
exactamente lo que volvió: la petición tal como se envió, la respuesta
tal como se recibió, y los relojes separados para que el tiempo del motor
nunca se confunda con el de tu red.

| Llamada | Qué hace | Presupuesto (tokens) |
|---|---|---|
| `locate` | encuentra puntos de entrada por metadatos curados | 800 |
| `sniff` | búsqueda literal dentro de los cuerpos | 800 |
| `harvest` | recuperación de una sola pasada, con fragmentos | 4,000 |
| `look` | el pasaporte de un nodo | 500 |
| `move` | los senderos de un nodo | 600 |
| `answer` | recuperación más el modelo enlazado | — |

Aquí es donde “¿qué ve el agente en realidad?” se responde llamada a
llamada: ejecuta el `locate` con el que arrancaría tu pregunta, luego el
`look` con el que seguiría, y lee el mismo JSON que lee el modelo —
presupuestos, banderas `truncated` y todo. El panel también reporta qué
tan grande era el corpus buscado y qué dice el propio reloj del motor,
así que un `locate` de medio milisegundo se reporta como un `locate` de
medio milisegundo aunque la ida y vuelta haya tardado treinta.

Cada ejecución viene con su cURL — misma ruta, misma clave, mismas reglas
que reciben tus aplicaciones — y el panel nombra el endpoint MCP: apunta
cualquier harness de agentes a `/mcp/` en tu Station como servidor MCP
streamable-HTTP, con la misma clave, y obtiene estas llamadas como
herramientas.

## Esta página también es de tu IA

Todo lo de arriba es una ventana humana sobre una superficie de máquina.
Preguntar es la primitiva `answer`; Explorar lee con `look`, `pick` y
`move`; Datos es `query` y `tend`; el Playground es todas ellas, sin
disfraz. Un agente conectado por MCP sostiene las mismas herramientas
bajo el mismo alcance y los mismos presupuestos — la consola es una
ventana, y el bosque detrás de ella es el producto. Para entregar estas
llamadas a tu IA, ver [Conectar tu IA](./connecting-ai.md).
