# Primer acceso

[English](../en/first-access.md) · [Português](../pt/first-access.md) · Español

[← Manual](./README.md)

El primer minuto en el Studio es deliberado. Según el estado de tu Station
te encontrarás con una de dos pantallas previas a la identidad la
configuración o la puerta y después, una sola vez, una breve presentación
de lo que en realidad has instalado. Esta página recorre las tres, y
después te muestra el lugar.

## La pantalla de configuración

Una Station se instala antes de tener administrador, así que la primerísima
visita a un despliegue recién hecho cae en la pantalla de configuración:
**"Configurar esta Station"**. Existe exactamente una vez. Mientras el
registro no guarda credencial de ningún tipo, `GET /v1/health` informa que
la configuración es necesaria y la consola muestra esta pantalla; en el
momento en que existe una persona dueña, la ruta desaparece
permanentemente y todo el mundo inicia sesión con normalidad la propia
pantalla lo dice al pie.

![La pantalla de configuración de una sola vez: la cuenta del dueño y la elección del primer bosque](../assets/setup.png)

*(Las capturas de pantalla muestran la consola en inglés.)*

Pide tres cosas y una elección:

| Campo | Qué significa |
|---|---|
| **Usuario** | Con él iniciarás sesión, y es el nombre que aparece en el registro de auditoría. |
| **Contraseña** | Al menos 12 caracteres. Esta cuenta es la dueña del despliegue gobierna todos los bosques, presentes y futuros así que hazla larga. |
| **Correo electrónico** | Opcional, y así etiquetado. Se guarda en el propio registro de la Station como contacto de la persona dueña nada se envía a ningún servicio externo, y la configuración se completa sin problema en un host aislado de la red. |

La cuenta creada aquí lleva el **bit de dueño**: `admin` sobre cada
bosque del registro, incluidos los bosques creados después, incluido
ninguno en absoluto. Hay exactamente una persona dueña, y el bit no
puede concederse a nadie más después.

Después, la elección del **primer bosque**:

| Elección | Qué pasa |
|---|---|
| **Empezar con un bosque de demostración** | Un bosque pequeño que explica MonkeyLLM siendo uno. Bórralo cuando quieras existe para que Preguntar y Explorar tengan algo que responder en tu primera visita. |
| **Empezar con un bosque vacío** | Aún sin nada dentro; tú lo nombras, la consola muestra el id en que se convierte su nombre, y lo llenas desde Ingesta. |
| **Dejarlo para después** | Un estado válido. Una persona dueña sin bosque es viable el estado vacío de la consola lleva la acción de crear, y eres administrador en todas partes. |

> **Nota** si la configuración falla porque alguien más llegó primero,
> la consola no reintenta: la ruta ya no existe, así que cae en la puerta.
> Y si tu despliegue está configurado con un superadministrador de
> entorno, la ruta de configuración nunca llega a existir ese despliegue
> ya declaró su primera identidad. Dónde encontrar la puerta se imprime en
> el log de arranque de la Station en la primera ejecución (ver
> [Instalación](./install.md)).

## La puerta

Cada visita después de la configuración empieza en la puerta:
**"Conéctate a tu Station"**. Tiene hasta dos entradas, y cuáles ves es un
hecho del despliegue que la consola le pregunta a la Station, nunca una
suposición.

![La puerta: inicia sesión con un usuario o con una clave de API](../assets/gate.png)

- **La entrada por contraseña** (la pestaña **Usuario**) existe cuando el
  inicio de sesión con contraseña es posible hay un superadministrador
  de entorno configurado, o al menos una persona ha recibido una
  contraseña en Accesos. Inicias sesión con usuario y contraseña; el token
  de sesión que recibes se comporta desde entonces como una clave
  ordinaria, así que todo lo que sigue es un único camino.
- **La entrada por clave** (la pestaña **Clave de API**) existe siempre.
  Pega una clave (`mk_…`) y conéctate. La Station guarda solo el digest de
  la clave la clave en sí nunca se almacena en el servidor.

En una Station sin contraseña configurada, las pestañas desaparecen y el
campo de clave es toda la puerta. Las claves las emite en Accesos un
administrador o se derivan de tu propia contraseña mediante el
emparejamiento, que es autoservicio (ver
[Conectar una IA](./connecting-ai.md)). Una clave rechazada dice
exactamente eso y nada más.

Las dos pantallas previas a la identidad llevan ellas mismas los controles
de idioma y tema: la primera pantalla que una persona ve no puede exigir
una sesión para ser legible.

## La presentación

La primera vez que inicias sesión, la consola ofrece una breve
presentación. Es el único momento en que el producto puede decir lo que
es, porque dejada a su suerte la mayoría de la gente concluye lo obvio y
equivocado que la consola es el producto.

![La bienvenida de una sola vez: un cerebro que tus IAs pueden cultivar](../assets/welcome.png)

Se titula **"Un cerebro que tus IAs pueden cultivar"**, y su subtítulo es
la frase a la que todo este manual vuelve una y otra vez: *la consola es
una ventana; el bosque detrás de ella es el producto*. MonkeyLLM mantiene
un bosque de conocimiento nodos markdown curados que una IA puede
navegar, interrogar y extender. El Studio es la forma en que las personas
lo observan, lo gobiernan y le enseñan, pero el bosque está hecho para ser
leído y alimentado por tus propios agentes, vía MCP, mientras sigas
haciéndolo crecer.

La presentación nombra las tres cosas que vale la pena hacer primero:

- **Conecta una IA** Claude Code o cualquier agente MCP se conecta a
  esta Station y gana las tools del bosque: recuperación, navegación, SQL,
  plantación.
- **Aliméntalo** sube documentos, espeja carpetas enteras, recorta
  páginas desde tu navegador; el Gardener los convierte en conocimiento
  curado y encontrable.
- **Pregúntale** respuestas fundamentadas en el bosque, que llegan con
  sus fuentes: nodos que puedes abrir, leer y corregir.

Aparece **como mucho una vez por navegador** la bandera vive en el
almacenamiento del navegador, un ajuste personal como tu preferencia de
tamaño de respuesta y no gasta nada: mostrarla o descartarla no emite
ninguna llamada a modelo, ningún commit, ninguna escritura más allá de esa
bandera. Nunca bloquea la consola, y solo *enlaza* a las consolas que
hacen el trabajo real. **Enseñar a mi IA** te lleva a Skills; **Echar un
vistazo** simplemente la cierra. Si la descartaste el día uno y necesitas
la puerta el día treinta, Resumen conserva una pequeña reafirmación
permanente *"Tu IA también puede leer esto"* que apunta a Skills y al
manual de integración.

## Orientarte

El menú responde tres preguntas en lugar de listar nombres: **Usar**lo,
**Construir**lo, **Gobernar**lo. Cada entrada lleva un icono y una línea
de descripción, y el menú muestra solo lo que tu clave permite una
entrada que solo pudiera rechazar no enseña nada. Ocultar es presentación,
nunca el control: la API rechaza de todos modos.

![La consola Resumen, con el menú agrupado a la izquierda](../assets/overview.png)

| Grupo | Consola | Para qué sirve | Requiere |
|---|---|---|---|
| Usar | **Resumen** | Qué hay en este bosque y qué puedes hacer aquí | todo el mundo |
| Usar | **Preguntar** | Haz una pregunta y recibe la respuesta con sus fuentes | read |
| Usar | **Explorar** | Recorre el árbol y lee lo que guarda cada nodo | read |
| Usar | **Playground** | Mira exactamente lo que ve un agente, llamada a llamada | read |
| Usar | **Datos** | Navega, consulta y edita tus datasets | query |
| Usar | **Skills** | Enseña a tu IA a usar este bosque como su memoria | read |
| Construir | **Ingesta** | Mete tus documentos en el bosque | ingest |
| Construir | **Modelos** | Qué modelo lee este bosque y cuál resume lo que entra | admin |
| Gobernar | **Accesos** | Quién existe, qué puede ver, cómo entra | admin |
| Gobernar | **Auditoría** | Quién vio qué | admin |
| Gobernar | **Salud** | Lo que ve el Ranger, y toma una instantánea | admin |
| Gobernar | **MCP / API / Integraciones** | Conecta agentes, apps y despliegues a esta Station | admin |

Skills está en *Usar* a propósito: es autoservicio, disponible para
cualquiera que pueda leer el bosque, nunca restringido a admin. Al pie del
menú, a toda persona con sesión iniciada se le ofrece **Descargar la
extensión Clipper** la extensión de navegador que recorta la página que
estás leyendo hacia este bosque.

En un teléfono, el menú se convierte en una hoja y una barra inferior
lleva hasta cuatro consolas junto a un **Más** permanente. Cuáles cuatro
es elección tuya: la estrella junto a cada entrada del menú fija un atajo
en la barra. Hasta que elijas, la barra lleva las cuatro primeras consolas
que tu concesión permite, en el orden del menú, para que la barra y el
menú cuenten la misma historia. Los fijados viven en tu navegador y
siempre se filtran por la concesión actual un fijado conservado de un
bosque donde tenías `admin` no ocupa un lugar en uno donde no lo tienes.

## Idioma y tema

La consola incluye **inglés, portugués y español**, completos una
traducción que falta es un defecto, no un fallback. Detecta el idioma de
tu navegador en la primera carga y persiste una elección explícita en
cuanto la haces. La apariencia funciona igual: **claro y oscuro**,
siguiendo la preferencia de tu sistema operativo hasta que se le diga otra
cosa. Ambos controles aparecen también en la pantalla de configuración y
en la puerta, antes de que exista sesión alguna.

> **Nota** el contenido no es el chrome. Los ids de nodos, los títulos,
> los resúmenes, los cuerpos, el SQL y la salida del modelo son datos del
> bosque y se muestran exactamente como están guardados; la consola
> traduce solo sus propias palabras.

## Tu alcance

La primera tarjeta de Resumen es **Nodos a tu alcance**, y la palabra
*alcance* es precisa: cada número de la página se cuenta sobre lo que
**tu clave** puede alcanzar de verdad, no sobre el bosque. Nada está
oculto detrás de un filtro y un principal acotado que viera el total
verdadero aprendería el tamaño de la parte que se le negó, así que la
consola nunca lo muestra. Un recuento que podría quedarse corto lo dice:
`82` significa que el recorrido fue completo, `82+` significa que una rama
desbordó el presupuesto de escaneo.

Al lado: **Ramas** y **Datasets** a tu alcance, y **Tu alcance** —
*Bosque entero*, o el número de ramas que cubre tu concesión, con sus
nombres. **Empiezas en** lista tus ramas raíz como enlaces, y dos listas
detallan **lo que puedes hacer aquí** y **lo que no puedes hacer aquí**,
directamente desde las capacidades que lleva tu concesión. Dos personas
abriendo el mismo bosque pueden ver dos Resúmenes distintos, y ambos
dicen la verdad.

## Próximos pasos

- [Usar el bosque](./using.md) Preguntar, Explorar, Playground y Datos:
  las superficies de lectura del día a día.
- [Alimentar el bosque](./feeding.md) Ingesta, el Gardener y el Clipper:
  cómo los documentos se convierten en conocimiento curado.
- [Conectar una IA](./connecting-ai.md) emparejar una clave, la consola
  Skills y conectar un agente MCP a tu Station.
