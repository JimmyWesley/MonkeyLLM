# El Manual de MonkeyLLM

[English](../en/README.md) · [Português](../pt/README.md) · Español

## La propuesta

Este despliegue mantiene un **bosque de conocimiento**: nodos markdown
curados, cada uno con un pasaporte de título, resumen, etiquetas y aristas
tipadas, más los índices ligeros que los hacen encontrables. A una IA no se
le entrega un volcado de recuperación *navega*: entra por la búsqueda,
recorre las aristas, lee exactamente el nodo que necesita y planta lo que
aprende como un nodo nuevo. El bosque recuerda entre conversaciones, entre
agentes, mientras sigas haciéndolo crecer.

La primera vez que inicias sesión, la consola lo dice sin rodeos: **"Un
cerebro que tus IAs pueden cultivar. La consola es una ventana. El bosque
detrás de ella es el producto."** Esa frase es toda la arquitectura. Tenla
presente en cada página de este manual nada de lo que ves en el navegador
es la cosa en sí; es una vista sobre un bosque que tus propios agentes leen
y alimentan vía MCP.

![La presentación del primer acceso: un cerebro que tus IAs pueden cultivar](../assets/welcome.png)

*(Las capturas de pantalla muestran la consola en inglés.)*

Alrededor del bosque está la **Station**, el host autoalojable: un
contenedor, REST bajo `/v1`, MCP bajo `/mcp`, identidad, política por
bosque y un registro de auditoría para que un bosque pueda ser un activo
compartido y gobernado en lugar de un directorio personal. La Station
también sirve el **Studio**, la consola web donde las personas observan,
gobiernan y enseñan al bosque: hacer preguntas fundamentadas, recorrer el
árbol, ingerir documentos, conceder accesos, enlazar modelos.

La audiencia real, sin embargo, son tus IAs. Claude Code o cualquier agente
con MCP se conecta a la Station y gana las tools del bosque recuperación,
navegación, SQL sobre datasets, plantación. Lo que un agente guarda hoy,
otro lo recuerda el mes que viene; las correcciones que una persona hace en
la consola son lo que lee el siguiente agente. El bosque es la memoria
compartida; la consola y los agentes son dos manos alimentando el mismo
cerebro.

Cuando abres un bosque, la consola Resumen te orienta: cuántos nodos, ramas
y datasets alcanza tu clave, por dónde empezar y qué puedes hacer aquí.
Todo lo que cuenta está al alcance de cualquier agente que conectes esa
simetría es el punto.

![La consola Resumen: qué hay en este bosque y qué puedes hacer aquí](../assets/overview.png)

> **Nota** Todo lo que hace el Studio viaja por las mismas rutas que
> cualquier cliente puede llamar; no hay ningún canal lateral privilegiado.
> Sea lo que sea que la consola te muestre, un cliente de la API con la
> misma clave también podría obtenerlo.

## Cómo encajan las piezas

| Pieza | En una línea |
|---|---|
| **Bosque** | El producto: nodos markdown curados con pasaportes, índices ligeros y su propio historial git el conocimiento en sí. |
| **Primitivas Vine** | Las diez tools MCP con las que navega un agente `locate`, `look`, `move`, `pick`, `scan`, `sniff`, `query` para leer; `plant`, `graft`, `tend` para escribir más compuestas como `harvest` y `answer`. |
| **Station** | El host autoalojable: REST `/v1`, MCP `/mcp`, identidad, política por bosque y auditoría envueltas alrededor del motor intacto. |
| **Studio** | La consola web que sirve la Station cómo las personas observan, gobiernan y enseñan al bosque. Una ventana, nunca el producto. |
| **Clipper** | Una extensión de navegador que recorta la página que estás leyendo hacia un bosque el artículo o la selección como markdown, la captura de pantalla como un nodo media. |
| **Skills** | La consola que entrega a tu agente un pequeño archivo de instrucciones que le enseña a usar este bosque como su memoria persistente. |

## Índice

| Página | Al terminarla, puedes |
|---|---|
| [Instalación y despliegue](./install.md) | Levantar una Station con Docker Compose o desde el código fuente y mantener todo lo que vale la pena conservar en volúmenes con nombre. |
| [Primer acceso](./first-access.md) | Iniciar sesión por primera vez, reclamar el despliegue y entender exactamente qué alcanza tu clave. |
| [Usar el bosque](./using.md) | Hacer preguntas que llegan con sus fuentes, recorrer el árbol en Explorar y consultar datasets en Datos. |
| [Alimentarlo](./feeding.md) | Subir documentos, adoptar carpetas enteras y recortar páginas desde tu navegador y dejar que el Gardener los convierta en conocimiento curado y encontrable. |
| [Conectar tu IA](./connecting-ai.md) | Emparejar una clave propia, apuntar Claude Code o cualquier agente MCP a esta Station y entregarle la skill que hace del bosque su memoria. |
| [Administrar y gobernar](./managing.md) | Conceder y acotar accesos, enlazar modelos, leer la auditoría y mantener el bosque sano con el tiempo. |

## Si solo vas a leer una página

Lee [Conectar tu IA](./connecting-ai.md). La consola puede preguntar,
navegar e ingerir por sí sola, pero el bosque está hecho para ser leído y
alimentado por tus propios agentes un bosque tocado únicamente a través
de la ventana es un cerebro que nadie está cultivando. Esa página te lleva
hasta el final en tres pasos: empareja una clave que sea tuya (solo puede
estrechar tu acceso, nunca ampliarlo), registra la Station como servidor
MCP y entrega a tu agente el archivo de skill que el Studio genera para
este despliegue exacto. Todas las demás páginas profundizan lo que esa
empieza.
