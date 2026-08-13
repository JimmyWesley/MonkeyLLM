# Alimentar el bosque

[English](../en/feeding.md) · [Português](../pt/feeding.md) · Español

[← Manual](./README.md)

Un bosque crece al ser alimentado. Todo lo de esta página — una carpeta
soltada, un artículo pegado, una hoja de cálculo, una captura de
pantalla, una página web recortada — recorre el mismo pipeline:
convertido a markdown o a un dataset, dotado de un resumen (el *olor* por
el que navega cada salto posterior) y commiteado en el git propio del
bosque. La consola es la ventana por la que lo alimentas; los nodos que
planta son el producto, y siguen siendo útiles mucho después de que la
pestaña se cierre.

## La consola de ingesta

La consola de ingesta (“Añadir documentos”) es donde los archivos se
vuelven bosque: convertidos, resumidos, enlazados y commiteados — el
mismo pipeline que usa la línea de comandos. Ofrece hasta cuatro
pestañas:

![La consola de ingesta con archivos preparados para subir](../assets/ingest.png)

(Las capturas de pantalla muestran la interfaz en inglés.)

| Pestaña | Qué hace | Cómo responde |
|---|---|---|
| **Enviar archivos** | sube archivos desde tu computadora; la Station los deja en preparación y los adopta | un job que puedes seguir |
| **Escribir** | un documento escrito por ti, curado y mostrado *antes* de plantar | en el lugar, con revisión |
| **Espejar una carpeta** | espeja un directorio que el **host de la Station** puede leer | un job que puedes seguir |
| **Optimizar** | relee la carpeta espejada (sync), reconstruye el índice, actualiza la capa vectorial | corre mientras esperas |

Cada modo pregunta **dónde ponerlos**: una rama existente, y todo
aterriza debajo de ella. Añadir documentos exige la capacidad `ingest`.

### Enviar archivos

Suelta archivos o una carpeta en la pestaña **Enviar archivos**.
Markdown, texto, CSV, JSON, Word y Excel se entienden todos; los archivos
tabulares se vuelven datasets consultables ([ver abajo](#datasets)). Los
archivos de más de 25 MB — o sin conversor para su formato — quedan
fuera, y la consola lo dice en vez de omitirlos en silencio. Nada se
parsea en el navegador: los bytes viajan a la Station y el Gardener hace
la lectura.

### Escribir en el lugar, con revisión

La pestaña **Escribir** es para el artículo que acabas de pegar, la nota
que acabas de terminar, lo que acabas de aprender. Recorre el mismo
pipeline que un archivo subido — pero se detiene antes de plantar y te
muestra el borrador primero (spec J.8.1):

- el id del nodo y la rama bajo la que vivirá,
- el **resumen** — el olor por el que navega cada salto posterior,
- las etiquetas,
- las **conexiones propuestas**, cada una nombrada por el título de
  aquello a lo que apunta.

Nada se ha escrito en ese punto: ni nodo, ni commit, ni rama. Puedes
editar el resumen, descartar un enlace propuesto o desechar el borrador
entero. Cuando publicas, el resumen aprobado se planta exactamente como
lo aprobaste — nunca re-curado a tus espaldas.

> **Nota** — los enlaces conservados quedan en confianza 0.3, que es
> precisamente la población que el Ranger promueve o poda según el
> tráfico real. Un enlace del que estás *seguro* se hace editando el
> nodo, no por la ingesta.

### Espejar una carpeta del servidor

**Espejar una carpeta** adopta un directorio que vive en el disco propio
de la Station — útil cuando el corpus ya está en el servidor, o es
demasiado grande para empujarlo por un navegador. Como la ruta se lee con
el acceso a archivos de la Station (no el tuyo), es un acto privilegiado:
exige la capacidad `admin` sobre el bosque, *y* la ruta debe estar dentro
de una de las **raíces de ingesta** configuradas de la Station:

```bash
# OS path-separated list of directories the Station may read on request.
MONKEYLLM_INGEST_ROOTS=/srv/dumps:/srv/exports
```

El valor por defecto es **vacío, y vacío significa ninguna** (spec
J.8.2): una Station sin configurar rechaza toda ruta del host — para el
admin y para el dueño por igual — mientras **Enviar archivos** y
**Escribir** siguen funcionando, porque traen sus propios bytes. `admin`
no es un bypass: la capacidad responde *quién puede pedir*, las raíces
responden *qué existe para ser pedido*. Cuando no hay raíces
configuradas, la pestaña de espejado no aparece en absoluto, y el rechazo
nombra la variable, para que un operador que *sí* quería espejar una
carpeta aprenda exactamente qué configurar.

Una vez espejada una carpeta, la pestaña **Optimizar** ofrece
**Actualizar**: relee la carpeta que espejaste la última vez — mostrada
junto al botón, para que siempre veas qué se va a releer — y actualiza
solo lo que cambió, por diff de hash. Una actualización conserva los
resúmenes que alguien ya aprobó: la curación nunca corre en un sync.

### Los lotes son jobs

Los modos por lote — enviar, espejar, actualizar — responden de inmediato
con un **job** (spec J.9), y el trabajo corre en la Station:

- **Un lote por bosque a la vez.** Un segundo lote mientras uno corre se
  rechaza, nombrando el job en marcha — así la consola puede mostrártelo
  en vez de arrancar trabajo invisible.
- **La página sigue al job, no lo sostiene.** El id del job en marcha
  viaja en la dirección (`?job=`), así que una recarga restaura la vista
  de progreso leyendo un registro — nunca re-ejecutando nada. Navegar a
  otro lado no pierde nada; el job no necesita a su público.
- **La píldora te sigue.** Desde cada consola del bosque, un pequeño
  indicador anuncia el lote en marcha — cuántos documentos van del total,
  el documento en mano, los errores hasta ahora — y se expande para
  ofrecer el cancelar y el camino de vuelta a la consola de ingesta.
- **El siguiente lote espera en la pestaña.** Mientras un job corre, el
  botón ofrece **Entrar en la cola**: los lotes arrancan solos, en orden,
  cuando termina el que corre. La cola es visible donde espera, vive en
  tu pestaña y muere con ella — el host en sí nunca encola trabajo
  invisible. Si *detienes* un lote, la cola se queda quieta y te espera.
- **Cancelar es limpio.** Una cancelación surte efecto en la siguiente
  frontera de documento — un documento está entero o ausente, nunca a
  medias. Lo plantado queda en pie (eso son commits), y **Actualizar**
  completa el resto sin duplicar nada.

> **Nota** — un reinicio de la Station olvida los *registros* de jobs,
> nunca el *trabajo*: el trabajo son commits, y la cuenta propia del
> bosque es el rastro de auditoría y el `git log`. Una dirección que
> nombra un job olvidado lo dice con claridad.

Cuando el lote termina recibes el reporte sin abreviar: creados,
actualizados, sin cambios, omitidos, sin soporte, errores. Una ingesta
parcialmente exitosa que reportara éxito sería peor que una que falla.

## Curación — la única etapa con LLM, siempre omitible

Entre la conversión y el plantado está la **curación** (spec G.4), la
única etapa donde puede intervenir un modelo — y la única etapa que jamás
se bloquea por un modelo ausente:

- **Sin un modelo enlazado**, el resumen se deriva del texto inicial del
  documento, marcado `source: ingest` con confianza 0.7. Todo se ingiere
  igual; la consola te dice que un modelo enlazado haría mejores
  resúmenes.
- **Con el enlace `ingest` del bosque** (definido en Modelos — ver
  [Administrar](./managing.md)), el Curator escribe un resumen y
  etiquetas de verdad, propone hasta tres enlaces `related-to` y
  consolida los resúmenes de rama hacia arriba, para que cada región
  lleve también un olor.

Los enlaces propuestos se eligen de una **lista cerrada de candidatos**
que ofrece el catálogo — el modelo puede elegir de la lista o no elegir
nada, así que un destino de enlace alucinado es estructuralmente
imposible. No elegir nada es una respuesta válida y común.

**“Nada que hacer” no es un rechazo.** Un lote de archivos sin cambios,
o de datasets (que se resumen desde su estructura), no necesita modelo —
y el reporte lo dice: *“Nada en este lote necesitaba el modelo… El
enlace está bien.”* Un rechazo genuino del modelo siempre deja atrás un
fallback o un reintento en el reporte; ese es el discriminador. Los dos
tienen arreglos opuestos — uno es otro modelo u otro prompt, el otro es
nada en absoluto — y la consola jamás te mandará a afinar un modelo al
que nunca se le preguntó nada.

## Datasets

Los archivos tabulares se vuelven **datasets**: payloads SQLite de verdad
que un agente puede consultar con `query`, SQL de solo lectura. Pasan dos
cosas distintas según lo que le des (spec G.2.2):

- **Un `.db` se adopta entero.** Un archivo SQLite es el único formato
  que el bosque ya habla — el payload de un dataset *es* una base de
  datos SQLite — así que los bytes se copian a su lugar, nunca se
  reinsertan fila por fila. Tipos, vistas, índices y BLOBs sobreviven
  todos, y una base de 5 GB cuesta lo mismo de adoptar que una de 5 MB.
- **Un `.csv`, `.json`, `.xls` o `.xlsx` se convierte** en un dataset
  recién nacido con tipos de columna inferidos. Un workbook convierte
  **todas** las hojas, una tabla por hoja — tomar la hoja uno y descartar
  el resto es como una hoja de cálculo llega sin los datos por los que
  alguien la adoptó.

De cualquier forma, el pasaporte del dataset lleva el **mapa de muestra**
(spec G.2.3): un `## Query manual` que nombra cada tabla y cada columna
con su tipo, y `## Sample rows` con las primeras tres filas de cada
tabla — celdas recortadas, tablas anchas muestreadas a doce columnas, a
lo sumo veinte tablas muestreadas, y toda omisión declarada. El mapa
importa porque un `.db` es opaco para toda primitiva de texto del bosque:
esas tres filas por tabla son lo que `sniff` puede ver dentro de un
payload — el vocabulario, el formato de los ids, el formato de las
fechas. No es un sustituto de `query`; es el olor que le dice a un agente
*qué* dataset consultar.

> **Nota** — los topes usuales de schema (10 tablas, 50 columnas)
> protegen contra un *modelo* inventando un schema; no aplican a datos
> que ya son tuyos. Un export ERP real de 141 columnas se adopta sin
> problema — el costo acotado vive en el mapa, no en un rechazo.

Los datasets también pueden **nacer en la consola Datos** (spec J.5.10):
**Nuevo dataset** pide un nombre, una rama, y las tablas y columnas que
declaras — campos, no SQL. La consola nunca escribe DDL; la Vine genera
el `CREATE TABLE`, crea el `.db` y solo commitea el `.md` — una llamada
`plant`. El id se compone a partir del nombre, se muestra antes de la
llamada y es inmutable después de ella. El **Importar** de la consola
Datos hace lo mismo que el Enviar archivos de la consola de ingesta —
mismos conversores, misma curación, mismo job, misma píldora — nunca un
parser privado en el navegador.

## Media

Una imagen nunca es “sin soporte” (spec G.5.1). Las imágenes (`.png`,
`.jpg`, `.jpeg`, `.gif`, `.webp`) y el audio (`.mp3`, `.wav`, `.m4a`,
`.ogg`, `.flac`) se plantan como nodos **`media`**: los bytes originales
se vuelven el payload, y el cuerpo es el proxy textual que el bosque
busca — texto para encontrar, binario para consumir.

Lo que ese cuerpo dice depende de los modelos del bosque:

- Sin un modelo de visión enlazado, un stub incorporado escribe lo que se
  sabe: el formato, el tamaño, y que todavía no hay descripción
  disponible. El nodo existe, es encontrable por su nombre de archivo y
  su lugar, y puede describirse más tarde.
- Con un modelo enlazado al rol **vision** (“Describir imágenes” en
  Modelos), el descriptor escribe lo que la imagen muestra **y cualquier
  texto legible en ella** — que es lo que hace que una diapositiva, una
  pizarra o un diagrama de flujo sean encontrables por `sniff`, pues
  `sniff` lee el proxy textual y nada más. Corre una vez por imagen al
  ingerir, y su descripción es todo lo que una imagen dirá jamás — vale
  la pena enlazar un modelo fiel.

Un descriptor que falla — endpoint caído, imagen rechazada, demasiado
lento — cae al stub con la razón en el reporte. Un modelo roto nunca
aborta una ingesta.

## El Clipper

El **Clipper** (spec J.15) es una extensión de navegador que recorta la
página que estás leyendo hacia un bosque — un cliente como cualquier
otro, que usa los mismos caminos de escritura que usa la consola:

- **El artículo legible, o solo tu selección,** llega como markdown por
  el mismo pipeline de compose, revisión incluida.
- **Una captura de pantalla** — la vista visible, o una región arrastrada
  que puedes ajustar y anotar — llega como nodo `media` por upload,
  descrita por el modelo de visión enlazado como cualquier otra imagen.
- **Una nota viaja al lado**: el selector de región acepta una nota,
  tecleada o dictada, que viaja como un compose emparejado que nombra la
  captura — así la imagen y tus palabras sobre ella aterrizan como dos
  nodos que se referencian entre sí.
- **Cada recorte lleva su dirección.** Los composes terminan con una
  línea `Source:`; los uploads llevan la URL de la página — y sobrevive a
  cada actualización, así que el nodo de una captura siempre dice de qué
  página es captura.

En el primer uso pide el origin de la Station y tu usuario y contraseña,
una vez. La contraseña se intercambia en el momento y nunca se guarda: lo
que el Clipper conserva es una **clave emparejada** estrechada a `read` +
`ingest`, que caduca en 90 días, revocable en cualquier momento en
Accesos. El emparejamiento solo puede estrechar tu propia autoridad,
nunca ampliarla.

Si el bosque está ocupado — un lote a medio correr responde `E_LOCKED` —
el Clipper encola el recorte del lado del cliente y reintenta,
resolviéndose con una notificación mientras sigues navegando. La cola
muere con el navegador; el host nunca encola.

Descárgalo desde el menú lateral — **Descargar la extensión Clipper** —
o desde `GET /clipper.zip` en el origin de tu Station. La consola MCP /
API / Integraciones te guía por la instalación (cargar sin empaquetar,
fijar a la barra de herramientas). La distribución es autoservicio, como
el emparejamiento: toda persona con sesión iniciada recibe la descarga,
no solo quienes administran. Solo lee una página cuando tú haces clic
ahí.

## Enseñar — la sección `## Notes`

El mapa de muestra dice qué hay *en* un dataset. No puede decir qué
*significa* — que una columna es USD mientras otra es BRL, que `status`
usa códigos de una letra, qué join responde la pregunta que la gente
realmente hace. Ese conocimiento vive en la cabeza de alguien, y un
agente que escribe SQL sin él escribe SQL que corre y responde mal — la
peor falla que este sistema puede producir, porque se ve como un éxito.

Por eso un dataset lleva una sección **`## Notes`** (spec C.2.1), y es
tuya:

- **Escríbela en la consola Datos**, en la pestaña **Notas** junto a
  Filas, Estructura y SQL (necesita la capacidad `write`). Guardar es un
  graft, un commit — versionado y atribuido como todo lo demás.
- **Nada más la toca.** El Gardener reescribe las dos secciones generadas
  y solo esas, así que tus notas sobreviven a cada sync, a cada
  re-adopción, a cada reemplazo de payload. La curación tampoco la
  escribe jamás: la suposición de un modelo sobre lo que significa una
  columna es exactamente lo que esta sección existe para corregir.
- **Viaja con el dataset por todos los caminos.** Cualquier material que
  el host arma para un modelo lleva las notas de cada dataset que
  contenga — `look` las devuelve, el harvest de una sola pasada las
  lleva, la entrada de la respuesta que navega las lleva.
  Incondicionalmente: que tu nota comparta vocabulario con la pregunta de
  hoy no es razón para retener tus instrucciones sobre cómo leer los
  datos.

El placeholder de la propia consola muestra el registro en el que
escribir:

```
valor_total_invoice es USD; valor_cambio es BRL.
status: A = abierto, C = cancelado, F = cerrado.
Las importaciones directas son las filas donde arrendatario está vacío.
```

Unas pocas frases aquí son las palabras de mayor palanca en el bosque:
escritas una vez, leídas en cada pregunta que toque el dataset.

---

El bosque está alimentado. Ahora conecta las IA que van a leerlo — y a
hacerlo crecer — desde fuera: [Conectar tus IA →](./connecting-ai.md)
