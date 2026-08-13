# Administrar y gobernar

[English](../en/managing.md) · [Português](../pt/managing.md) · Español

[← Manual](./README.md)

El bosque es el producto; esta página trata de mantenerlo gobernado y sano.
Cinco consolas cargan con ese trabajo **Accesos**, **Modelos**, **Salud**,
**Auditoría** y la pestaña **Optimizar** de Ingesta. Las cuatro consolas
aparecen solo para una clave que tiene la capacidad `admin` sobre el bosque;
la pestaña Optimizar se muestra para cualquier clave que pueda hacer
`ingest` (una simple relectura de la carpeta espejada no exige más), con sus
tarjetas de Reconstruir y de Actualizar la capa vectorial reservadas para
`admin`. Todo lo que hacen viaja por las mismas rutas `/v1` que cualquier
cliente de la API podría llamar: no hay canal lateral privilegiado, y
deliberadamente no hay
un panel separado de superadministrador. Una consola, una API, con las
capacidades decidiendo qué aparece.

## Personas y accesos

La gobernanza en el Studio tiene la forma de una **persona**, no de una
tabla de concesiones. Añadir a alguien es un solo formulario quién es, qué
puede ver, cómo entra, y un token si sus scripts lo necesitan porque es
una sola decisión, y después cada cambio a esa persona empieza desde su fila
en la lista: su nivel, su alcance, si puede entrar, cuántos tokens vivos
tiene y cuándo se le vio por última vez.

![La consola de Accesos: todos los que pueden alcanzar tus bosques, una fila por persona](../assets/people.png)

*(Las capturas de pantalla muestran la consola en inglés.)*

El acceso se concede como **primero un nivel, después las capacidades**. Un
nivel es un punto de partida con nombre, y la consola documenta cada nivel
en la propia pantalla, así que elegir uno nunca exige salir de ella:

| Nivel | Puede | No puede |
|---|---|---|
| **Lector** | leer el material | todo lo demás |
| **Analista** | leer, ejecutar SQL de solo lectura | escribir nada |
| **Editor** | leer, consultar, crear y editar nodos, cambiar filas de dataset | añadir documentos nuevos, dar acceso |
| **Curador** | todo lo de un editor, más cargar documentos nuevos | dar acceso a otras personas |
| **Dueño** | control total, incluido dar acceso a otras personas | |

Un nivel es solo un punto de partida: una sección "Ajustar las capacidades"
permite que cualquier concesión se desvíe de él (las capacidades son `read`,
`query`, `write`, `tend`, `ingest`, `admin`), y el nivel elegido se reafirma
en palabras llanas justo debajo de la elección "Lee y ejecuta SQL de solo
lectura sobre los datasets." para que lo que estás por guardar quede dicho
antes de guardarlo.

Dos reglas más mantienen honesto el formulario:

- **Los bosques se eligen como conjunto.** El formulario ofrece todos los
  bosques que administras como selección múltiple una persona, una
  decisión, no una visita a este formulario por bosque. Si un paso es
  rechazado (digamos, un bosque que no administras), el resto se aplica de
  todos modos y el rechazo se lista por nombre; nada se descarta en
  silencio.
- **El alcance por ramas aparece solo cuando significa algo.** Con
  exactamente un bosque marcado, puedes estrechar la concesión a ramas
  elegidas del propio árbol de ese bosque ("Solo las ramas que yo elija").
  Con varios bosques marcados la concesión cubre cada bosque entero, y el
  formulario lo dice los nombres de ramas no se comparten entre bosques,
  así que aplicar los nombres de un bosque a otro sería una mentira.

> **Nota** Elige un alcance de cero ramas y la consola te lo advierte: esa
> persona no vería absolutamente nada. Un alcance vacío es una concesión
> válida; solo que rara vez es la que querías.

### Claves y tokens

La segunda pestaña de la misma consola lista **toda credencial que puede
alcanzar esta Station** dos vistas sobre una sola verdad. Cada token lleva
una etiqueta ("Pipeline de CI, Zapier, bot de staging"), un prefijo
reconocible, una caducidad (7, 30, 90 o 365 días, o nunca) y cuándo se usó
por última vez; cada uno puede revocarse en el acto. El secreto en sí se
muestra exactamente una vez, al crearlo solo se guarda su digest, así que
cópialo entonces o acuña otro.

Las claves emparejadas las claves de autoservicio que el Clipper y la
consola de Skills derivan de la propia contraseña de una persona (`POST
/v1/auth/pair`) también viven aquí. Son tokens ordinarios con un giro:
llevan una máscara de capacidades de a lo sumo `{read, ingest}`, su
autoridad son las concesiones propias de la persona **intersectadas con esa
máscara en el momento del uso** (una concesión revocada después desaparece
de la clave de inmediato), y siempre caducan 90 días por defecto, 365 como
máximo. Emparejar solo puede estrechar, nunca añadir, y por eso no necesita
administrador.

Los tokens de sesión el subproducto de entrar con contraseña nunca
aparecen en esta lista. No son una credencial que un operador gestione.

Una regla de escalación da forma a lo que puedes ver: una clave autentica a
un *principal*, y un principal puede tener concesiones en varios bosques,
así que acuñar o revocar sus credenciales exige `admin` en **todos** los
bosques que tiene. Una persona que además tiene un bosque que tú no
administras aparece en tu lista, pero sus credenciales quedan fuera de tu
alcance la consola lo dice en su fila.

### La ventana de configuración, y por qué arrancar no acuña nada

Una Station recién nacida no es de nadie, y así se queda hasta que una
persona la reclama: **arrancar una Station no acuña nada**. El registro
tiene exactamente la misma autoridad después del arranque que antes de él —
ninguna clave, ninguna contraseña, ningún principal que pueda actuar. Eso es
lo que deja que la ventana de configuración del primer arranque sobreviva
para ser usada.

Mientras el registro no guarda credencial de ningún tipo, `POST
/v1/auth/setup` está abierta: la primera persona que abre la consola se
convierte en el **dueño**, el único principal que tiene `admin` en todos los
bosques, presentes y futuros. El primer arranque lo anuncia en la salida
estándar la URL de la consola, y una advertencia de que un asiento de
dueño sin reclamar en una interfaz pública es una carrera contra
desconocidos. Una vez que la configuración corrió, la ruta se cierra de
forma permanente y responde exactamente como una ruta que nunca existió.

Dos despliegues renuncian a la pantalla de configuración, cada uno
explícitamente:

- **Las máquinas headless** pasan `--bootstrap-key` (o
  `MONKEYLLM_STATION_BOOTSTRAP_KEY=1`) y la primera clave de API con el
  bit de dueño se imprime una sola vez en el arranque, dentro de esa misma
  ventana de un solo tiro y nunca más.
- **Los despliegues break-glass** definen `MONKEYLLM_STATION_ADMIN` y
  `MONKEYLLM_STATION_PASSWORD`: una cuenta sostenida por el entorno, nunca
  almacenada, que se rota reiniciando. Configurarla cierra la configuración
  inicial, porque el despliegue ya declaró su primera identidad.

## Modelos

Un bosque responde preguntas, resume lo que entra y describe imágenes solo
si le enlazas un modelo. La consola de Modelos es donde eso ocurre por
bosque, en dos mitades: proveedores y roles.

![La consola de Modelos: los proveedores de un lado, los tres roles que un bosque enlaza del otro](../assets/models.png)

**Los proveedores** son endpoints con nombre sirve cualquier URL base
`/v1` compatible con OpenAI: OpenRouter, LiteLLM, vLLM, un llama.cpp local.
Las claves son de solo escritura en todas las superficies: la consola
informa únicamente si hay una guardada, y dejar el campo en blanco al
actualizar conserva la actual, así que un endpoint puede corregirse sin
volver a pegar un secreto. Los proveedores declarados por el propio entorno
del despliegue (`MONKEYLLM_LLM_ENDPOINT`, `MONKEYLLM_EMBED_ENDPOINT`) llegan
preconfigurados y de solo lectura cambia las variables y reinicia la
Station para cambiarlos.

Cuando eliges un modelo, la consola ofrece el catálogo del propio proveedor
(obtenido de su ruta `/models`) para que elijas un identificador real en vez
de escribir uno pero todavía puedes escribir un modelo que el proveedor no
anuncie, porque los gateways declaran de menos.

**Los roles** son lo que un bosque enlaza de verdad `(forest, role) →
(provider, model, reply length, reasoning)`:

| Rol | La consola lo llama | Para qué optimizar |
|---|---|---|
| `answer` | Responder preguntas | Velocidad lee el material recuperado y escribe la respuesta, en cada pregunta. |
| `ingest` | Resumir lo que entra | Cuidado escribe el resumen por el que navega toda búsqueda posterior, una vez por documento. |
| `vision` | Describir imágenes | Fidelidad lee diapositivas, diagramas y capturas de pantalla en la ingesta, y su descripción es todo lo que una imagen dirá jamás. |

Cada enlace lleva un **largo de la respuesta** (la respuesta entera que el
modelo puede escribir demasiado bajo corta a mitad de frase, y un modelo
de razonamiento necesita espacio para pensar antes) y un interruptor de
**razonamiento**, apagado por defecto y que vale la pena encender solo para
modelos de pensamiento híbrido.

Dos hechos que conviene retener:

- **Enlazar un modelo nunca amplía el acceso.** La recuperación corre dentro
  del alcance de quien pregunta antes de llamar a modelo alguno, así que el
  modelo solo lee lo que esa persona ya podía haber leído primitivo a
  primitivo.
- **Un bosque sin enlace de `answer` sigue haciendo todo menos Preguntar.**
  Explorar, Datos, ingesta, búsqueda todo funciona; el Resumen lo dice sin
  rodeos: "No hay ningún modelo enlazado a este bosque, así que Preguntar
  aún no responde. Lo demás funciona."

## Salud

El cuidador del bosque es el **Ranger**, y la consola de Salud es su informe
— "Lo que el Ranger informaría en su próxima pasada. Leerlo no cambia nada."

![La consola de Salud: el informe del Ranger, y el bosque empaquetado como instantánea](../assets/health.png)

Lo que el Ranger atiende, en sus propias pasadas:

- **Evaporación del calor.** Cada lectura deposita feromona; sin olvido,
  cada sendero se saturaría y el calor dejaría de discriminar. El calor
  decae exponencialmente (vida media de 30 días por defecto), y las filas
  que se enfrían por debajo de 0.01 se eliminan como polvo. La evaporación
  vive por entero en la capa derivada nunca commitea.
- **Promoción y poda solo de enlaces inciertos.** El Ranger gestiona
  exactamente los enlaces nacidos por debajo de la confianza total:
  propuestas de agentes y atajos descubiertos. Una propuesta cuyos dos
  extremos siguen calientes queda confirmada por el uso y se promueve; una
  cuyos dos extremos se enfriaron del todo se poda. Las aristas
  estructurales y los enlaces a confianza 1.0 nunca se tocan, cada cambio es
  un commit auditado solo de `.md` (`ranger(promote)`, `ranger(prune)`), y
  un enlace que no está ni bastante caliente ni bastante frío se deja en paz
  la paciencia es una característica. El Ranger nunca borra nodos.

El **informe** exige `admin` sobre el bosque y un alcance sin restricciones
— cuenta problemas a lo largo de todo el bosque, así que una concesión
limitada a una rama se rechaza en vez de servirle números que en silencio
describen nodos que no puede ver. Cubre: ramas para dividir (demasiado
anchas para cualquier lector), nodos sobrecargados (más senderos de los que
alguien puede seguir desde un solo lugar), errores y advertencias de lint,
fuentes que desaparecieron (el nodo permanece; el archivo del que vino ya no
está), propuestas de enlace esperando al Ranger, y la feromona de un vistazo
— cuántos nodos calientes, pico y promedio del calor.

Leer el informe no cambia nada. El cuidado en sí es una corrida programada
en una shell, un ciclo o como servicio:

```bash
vine ranger --forest /forests/<id>              # one cycle: evaporate → tend links → report
vine ranger --forest /forests/<id> --every 3600 # service mode, repeat every N seconds
```

En un despliegue con Docker, el mismo comando corre dentro del contenedor:
`docker compose exec station vine ranger --forest /forests/<id>`.

### Instantáneas

Una instantánea es el bosque empaquetado en **un solo archivo** su
repositorio git como bundle, historial completo incluido, cada plant y cada
commit de auditoría viajando con él. Desde la consola de Salud puedes tomar
una ("Incluir los payloads de los datasets" añade un archivo sidecar para
los `.db` que git nunca guarda), y el **dueño** puede descargar el bundle y
el sidecar.

Importar pasa por el selector de bosques: **Importar snapshot** crea un
bosque nuevo a partir de un bundle, historial incluido, solo para el dueño —
el bundle entra tal cual, sin pasada de curación, que es exactamente la
razón de que solo el principal que gobierna el volumen pueda plantar uno. El
bosque importado llega servible (la Station lo reindexa al llegar) y frío:
no se gasta ninguna llamada a modelo, y la búsqueda queda solo por palabra
clave hasta que alguien construya la capa vectorial.

> **Nota** Restaurar *sobre* un bosque vivo deliberadamente no se ofrece
> en la consola; eso queda en la línea de comandos (`vine snapshot
> restore`). Un snapshot viaja: descárgalo aquí, impórtalo como bosque nuevo
> allá.

## Auditoría

La consola de Auditoría responde "quién vio qué". Sus dos mitades se guardan
donde le corresponde a cada una:

- **Las lecturas** aterrizan en el log de auditoría: quién, qué bosque, qué
  llamada, un digest de los argumentos, el tamaño del resultado y cuándo.
  Los cuerpos y los fragmentos nunca se copian dentro el log registra
  acceso, no contenido y la consola lo dice en pantalla.
- **Las escrituras** ya son commits en el historial git del propio bosque,
  cada una con un trailer de commit `station-principal: <name>` que nombra
  al principal que actúa, así que la historia de lo que cambió es la del
  propio bosque.

Juntas, las dos reconstruyen el rastro completo de cualquier respuesta
después del hecho: qué principal, qué primitivos, qué nodos, en qué orden.
Una respuesta servida del banco (ver abajo) se audita como tal la fila
lleva el digest de la clave de la entrada, queda marcada como servida del
banco, y el costo que registra es el costo *evitado*, nunca un segundo
gasto.

El log se puede filtrar por persona, y leerlo exige la capacidad `admin`.

## Optimizar

La pestaña **Optimizar** de la consola de Ingesta reúne un mismo encargo
contado tres veces: mantener el contenido al día, mantener al día lo que lo
encuentra, y mantener pagada la mitad densa. Tres botones, y saber cuál
apretar es la mayor parte de la destreza:

| Botón | Qué hace | Cuándo apretarlo |
|---|---|---|
| **Ingerir** (el botón de envío de la pestaña) | Relee la carpeta que este bosque espejó por última vez y actualiza solo lo que cambió. | Los documentos de origen avanzaron y el bosque debería seguirlos. |
| **Reconstruir** | Reconstruye el índice de búsqueda a partir de los archivos los archivos son la verdad, el índice es derivado. | Cualquier cosa parece desactualizada: una búsqueda que no encuentra un nodo que sí puedes leer, un bosque que llegó de un snapshot o de una versión anterior. |
| **Actualizar** | Embebe solo los nodos escritos desde la última construcción de la capa vectorial. | La consola dice "*n* nodos se escribieron desde la última construcción, así que la búsqueda híbrida ordena sin ellos." |

Reconstruir (`POST /v1/admin/reindex`) exige `admin` y un alcance sin
restricciones el conteo que devuelve es el tamaño del bosque entero.
Escribe solo la capa derivada: ningún commit, ningún cambio de historial,
que es también la razón de que una Station de solo lectura igual lo ofrezca
— un índice que nunca pudiera reparar se degradaría para siempre.

Actualizar existe porque **una lectura embebe solo la pregunta**: preguntar
nunca paga por embeber documentos, así que la deuda de embedding de una
ingesta se acumula de forma visible como un conteo de "atrasados" en vez de
esconderse dentro de la latencia de búsqueda de alguien. Hasta que lo
aprietas, los nodos nuevos igual se encuentran por palabra clave; solo la
mitad vectorial del ranking híbrido está atrasada. Una actualización contra
un índice ausente o de otro modelo se rehúsa antes que llenar a medias dos
espacios incompatibles; ese caso pide una construcción completa de la capa
vectorial.

## Costos y presupuestos

Todo primitivo de lectura responde dentro de un **presupuesto de tokens**
declarado, y el truncado siempre es explícito una marca `truncated: true`,
nunca un corte silencioso. La ventana de contexto de un agente es el recurso
más escaso del sistema, y los presupuestos son la manera en que el bosque la
respeta:

| Primitivo | Presupuesto (tokens) |
|---|---|
| `look` | 500 |
| `move` | 600 |
| `locate`, `scan`, `sniff` | 800 |
| `query` | 2000 filas enteras caen desde el final; la lista de columnas nunca cae |
| `pick` | un cuerpo de más de 4000 devuelve en su lugar su esquema, dirigiendo al agente a una sección |
| `harvest` | 4000 para todo el compuesto |

La única llamada que cuesta dinero de verdad es `answer` la llamada al
modelo detrás de Preguntar. Por eso la Station mantiene un **banco de
respuestas**, por bosque: una pregunta repetida se sirve del banco, no se
vuelve a cobrar. La recuperación igual corre en cada pregunta (es la mitad
barata), y lo que recuperó decide la frescura una entrada se sirve solo
mientras el material detrás de ella es byte a byte lo que era, así que un
acierto caducado es estructuralmente imposible y cualquier escritura al
bosque invalida toda entrada hecha antes. Las entradas nunca cruzan alcances
de acceso, una respuesta servida lo dice ("Del banco" en Preguntar,
`cached: true` en la API), y la fila de auditoría registra el costo evitado
en vez de gastarlo dos veces.

Los controles del banco están en la consola de Modelos: encendido o apagado
por bosque (encendido por defecto), cuántas entradas se conservan, una
caducidad opcional en horas (higiene, no corrección), un botón para
vaciarlo, y el marcador en curso aciertos, fallos y tokens **no
gastados**.

---

Dos lugares adonde ir desde aquí: [Instalar y desplegar](./install.md) para
actualizar la Station en sí todo lo que vale la pena conservar vive en los
volúmenes con nombre, así que una actualización es una reconstrucción, no
una migración y [Conectar tu IA](./connecting-ai.md), porque un bosque
bien gobernado sigue estando solo tan vivo como los agentes que lo leen y lo
alimentan.
