# Handoff

Cuando el contexto está a punto de llenarse, dejas que **la propia sesión actual** escriba un
[handoff document](../reference/glossary.md#交接书) que una persona puede leer y editar, y luego
abres una nueva sesión que toma el relevo. Sin compact. Todo el proceso lo ves en la terminal, el
documento queda en disco, y lo puedes editar cuando quieras —— la sesión que toma el relevo lee
exactamente ese archivo.

!!! note "El handoff no es la continuity"
    El [handoff](../reference/glossary.md#换代) cambia a una nueva [session](../reference/glossary.md#会话)
    **dentro de la misma run**; la [continuity](../reference/glossary.md#接续) reengancha **entre procesos**
    con la [run](../reference/glossary.md#运行) anterior, ver [continuity](continuity.md).

    Ambos encajan automáticamente, sin cableado extra: la [lineage](../reference/glossary.md#血缘) registra
    el `session_id` **final** de ese step, y ese es precisamente el sucesor —— así que el próximo wake
    engancha con el sucesor, no con la generación que se quemó.

## Qué problema resuelve {#解决什么问题}

El auto-compact que trae el SDK se dispara en **ventana −33k** (medido: cuando la ventana es `200000` el
umbral es `167000`; el algoritmo de compactación en sí está en el binario del harness, no se puede cambiar,
lo único que se puede cambiar es si se dispara o no), y lo que hace es **resumir el historial en un párrafo**.
Va a contracorriente del resto de este framework:

| | Cuándo decide | Qué deja |
|---|---|---|
| `spill_guard` | En el instante en que la herramienta retorna | El resultado grande [spill](../reference/glossary.md#落盘) al disco, en el contexto queda una línea con la ruta |
| Piezas congeladas (brief / goal) | Al terminar ese step | Un documento, el siguiente step solo lo lee |
| **auto-compact** | **Solo mira atrás cuando el contexto se llenó** | **Un resumen que el modelo escribe él mismo** |

Lo que flower hace de principio a fin es **decidir en el momento qué se debe conservar**. El
[compact](../reference/glossary.md#压缩) es el único lugar de "remedio a posteriori", y su producto tiene
cuatro defectos:

- **Generado por el modelo** —— qué se escribe en el resumen lo decide el juicio del modelo en ese momento, tú no participaste
- **Ilegible** —— está escrito para el modelo de la siguiente ronda, no para una persona
- **Inmodificable** —— está dentro del harness, no hay ningún archivo que puedas abrir
- **No sabes qué se perdió** —— ni ves qué se perdió, ni puedes decir "eso no lo pierdas" antes de que lo pierda

El handoff devuelve esto al mismo enfoque: **otra pieza congelada**, con la misma forma que el brief y el goal
—— estructurada, en disco, **puedes abrirla, cambiar una línea y hacer que siga corriendo**. Y esto es
precisamente el propio enfoque de este proyecto —— el `HANDOFF.md` en la raíz del repositorio es exactamente
lo mismo, escrito por una persona.

## Cómo se usa (código mínimo) {#怎么用最小代码}

La línea de comandos trae el handoff por defecto:

```bash
flower                       # trae el handoff por defecto
flower --window 200000       # solo hace falta darlo si lo juzgó mal (por defecto 1 millón)
flower --no-handoff          # apagarlo —— vuelve al auto-compact que trae el SDK
```

Al escribir tu propio código, el handoff se controla con `Runtime(handoff=…)`, por defecto `True`:

```python
from flower import HandoffPolicy, Runtime

# por defecto: HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# configurar la ventana explícitamente (esto es lo que más conviene ajustar al cambiar gateway o modelo)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # apagarlo, vuelve al auto-compact
```

`Runtime.__init__` es todo keyword-only, `workspace` es obligatorio. `handoff` acepta una instancia de
`HandoffPolicy` o un `bool`, y dar un `bool` equivale a `HandoffPolicy(enabled=…)`.

!!! warning "handoff activado = auto-compact forzado a apagarse"
    `Runtime(handoff=True)` es el **valor por defecto**, y al ensamblar cada intento hace esto: siempre que
    `handoff.enabled` y `spec.compact is None`, cambia el spec a `CompactPolicy(mode="no_summary")` —— es decir,
    inyecta **`DISABLE_AUTO_COMPACT=1`** en el subproceso.

    La razón es que si los dos mecanismos corren a la vez, no queda claro quién causó cierta caída del contexto.
    El costo es que **no hay red de seguridad**: cuando la ronda que escribe el handoff falla no se puede parar,
    ni tampoco aguantar como si nada hasta el límite duro, así que tiene que haber una ruta de degradación (ver abajo).

    Para conservar el auto-compact como respaldo, hay que dar **explícitamente**
    `AgentSpec(compact=CompactPolicy(mode="auto"))` —— si el spec lo da él mismo se respeta, no se sobrescribe.
    Ojo que esto **gana silenciosamente** sobre las suposiciones de la mitad del handoff.

## Qué hace realmente {#它实际做了什么}

### Momento del disparo: dos caminos hacia el handoff {#触发时机两条路进换代}

**Uno, el nivel llega al umbral.** El criterio es `_handoff_due`: `handoff.enabled` y **no estar en la ronda que
escribe el handoff** y `_ctx >= handoff.at` y este step ya haber obtenido un `session_id`. `_ctx` es el tamaño de
contexto que el **main thread** vio realmente en su última ronda —— solo mira el
[main thread](../reference/glossary.md#主线程), el contexto del [subagent](../reference/glossary.md#subagent)
es asunto de su propio transcript, se disipa al terminar, y no debe forzar el handoff del main thread.

En `warn_at` primero se emite un aviso de aproximación, una sola vez por generación, sin inundar.

**Dos, la API reporta directamente "no cabe".** Ver la sección de `is_overflow` más abajo.

Ambos caminos **no están sujetos a `max_attempts`**, y además **no consumen cuota de reintentos** (internamente
`attempt -= 1`) —— el handoff no es un fallo.

### El handoff document: cinco secciones, solo dos obligatorias {#交接书五段必填只有两段}

Cada sección bloquea un tipo de error que "quien toma el relevo va a cometer":

| Sección | Campo | Qué bloquea |
|---|---|---|
| Qué se está haciendo ahora | `doing` **obligatorio** | No saber dónde uno está parado |
| Lo ya decidido | `decided` | Volver a discutir algo ya decidido (debe llevar el **porqué**) |
| Caminos sin salida | `deadends` | **La sección más cara** —— ver abajo |
| Siguiente paso | `next` **obligatorio** | Gastar media hora primero decidiendo qué hacer |
| Escena | `scene` | Las **rutas** de archivos clave y productos. Punteros, no contenido |

`Handoff.missing()` solo revisa esas dos secciones `REQUIRED = ("doing", "next")`, y `complete()` es su negación.
**Exigir por la fuerza que "caminos sin salida" no esté vacío obliga a inventar** —— justo al comienzo de una tarea
debe estar vacío. Y el juicio de `complete()` tiene consecuencias: si falta una sección obligatoria, este handoff se
**reemplaza entero por una pieza degradada ensamblada mecánicamente** (ver abajo), y eso es mucho peor que un handoff
real al que le falta una sección. Por eso las otras tres secciones son opcionales —— sirven si se escriben, y no las
escribes no bloquea el handoff.

En `to_markdown()` las secciones vacías se escriben como `(vacío)`; el encabezado de `prompt_block()` le dice
claramente a quien toma el relevo "estás tomando el relevo", para que no vuelva a pedirle a alguien el contexto.
El campo `step` solo se usa en el encabezado del documento, no participa en el parseo.

#### Por qué "caminos sin salida" es la más cara {#走不通的路为什么最贵}

Porque es **lo que a quien toma el relevo le cuesta más caro redescubrir**, y lo que quien escribe más fácilmente omite.

El worker tiene un sesgo optimista sistemático (el [goal guard](goal.md) argumenta lo mismo): escribe lo que logró,
y olvida escribir qué probó que no funcionó. Y esto último es lo verdaderamente caro —— en [HT002](../cases/ht002.md)
se dio vueltas una hora por un problema de compilación, y si la conclusión de esa hora no se hubiera escrito, quien
toma el relevo daría exactamente las mismas vueltas.

Por eso el `HANDOFF_PROMPT` dedica un párrafo específico a señalar esto, e incluye ese costo medido.

### Cómo se ve {#长什么样}

```text
# Contexto 130.0K/200K · quedan unos 20K para el handoff

# Contexto 152.0K/200K —— escribiendo el handoff para preparar el relevo
  - Haciendo ahora  añadiendo un header shim de macOS al Makefile para que la macro sigemptyset ya no se expanda en un error de sintaxis.
  - Ya decidido     no tocar el código fuente de negocio —— el usuario marcó explícitamente el límite, así que se va por generar el shim en el Makefile.
  - Sin salida      -D_ANSI_SOURCE apaga otras macros a la vez; cambiar el orden de include no sirve.
  - Siguiente paso  correr make una vez en un clone limpio para verificar que el shim se sostiene.
<- handoff escrito en ~/proj/.flower/notes/交接-干活.md
<- la nueva sesión toma el relevo, el contexto reinicia desde 152.0K
```

**Totalmente automático, no se detiene a esperarte** —— una run long-horizon no debe atascarse porque una persona
se fue a comer.

El evento es `Event("handoff")`, y `payload["phase"]` tiene **tres** valores: `near` (aproximación),
`writing` (escribiendo, escribir el handoff toma una decena de segundos, si no se emite esta la interfaz parece
colgada) y `done` (relevo terminado). El payload de `done` además lleva `context`, `window`, `degraded`, `path`,
`sections`.

### Cómo se calcula el umbral {#阈值怎么算}

```python
at      = max(10_000, window - headroom)   # línea del handoff, con piso de 10k
warn_at = max(1_000, at - 20_000)          # línea del aviso de aproximación
```

El piso de 10k de `at` es imprescindible —— más bajo no alcanza ni para escribir el handoff.

El siguiente diagrama de escala usa `--window 200000` como ejemplo, la **ventana por defecto es 1 millón**:

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                       aviso handoff       límite duro
```

Cuando no se da `window`, `default_window()` lo juzga por el **string del nombre del modelo**, mirando solo las dos
variables de entorno `ANTHROPIC_MODEL` o `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Nombre del modelo | Se juzga como |
|---|---|
| Con la palabra `1m` aislada en el nombre | `1_000_000` |
| Con `haiku` en el nombre | `200_000` |
| El resto, **y también cuando ninguna de las dos variables está seteada** | `1_000_000` |

Ojo con el orden: `1m` matchea primero, así que `claude-haiku[1m]` se juzga como 1 millón, no como 200 mil.

Por qué `headroom` es `50_000`: el auto-compact se dispara en ventana −33k, y el handoff tiene que adelantársele;
además "escribir el handoff" en sí requiere correr una ronda más. 50k satisface ambas cosas.

**`--window` es el interruptor que más conviene ajustar al cambiar de modelo / gateway.** El lado del SDK no puede
obtener un tamaño de ventana confiable, solo puede adivinarlo por el nombre. Si la ventana real es mayor → el handoff
llega temprano (desperdicio, pero no error); si es menor → llega tarde, hay que ajustarlo. Un valor medido que vale
la pena mencionar: el gateway configurado en la máquina de desarrollo es `claude-opus-5[1m]`. Si antes se calculaba
como 200 mil, cambiaría de generación cada 150 mil, cuando en realidad puede correr hasta 950 mil —— **una diferencia
de 5 veces**, y una tarea long-horizon quedaría hecha trizas.

Con `flower -v` puedes ver antes de arrancar la configuración de credenciales vigente (endpoint, nombre del modelo,
token enmascarado dejando solo los primeros 4 dígitos).

### `is_overflow`: convertir un error duro en un handoff en el momento {#is_overflow把硬错变成当场换代}

Este es el requisito previo para **atreverse a tomar 1 millón como valor por defecto de `default_window()`**.

Si la ventana se juzga demasiado grande, el umbral nunca se alcanza, y el auto-compact además está apagado —— entonces
se choca duro contra la API. `is_overflow(*texts)` reconoce esta señal: `prompt is too long`, `context length exceeded`,
`maximum context length`, `too many total text bytes`, `input length and max_tokens exceed`, etcétera.

Una vez reconocido va por **la misma ruta del handoff**, solo que el handoff de esta generación es necesariamente
degradado —— esa sesión ya no puede correr "otra ronda para escribir el handoff", así que usa directamente la pieza
degradada ensamblada mecánicamente, cambia de sesión como de costumbre y sigue, **este step no falla**.

Así el costo de juzgarla demasiado grande baja de "este step falla" a "el handoff de esta generación es degradado".

`is_overflow` es una **función a nivel de módulo**, no un método de `Handoff`, y es de argumentos variables.

### Cuando el handoff no se puede escribir: degradación, no parada {#交接写不出来时降级不是停下}

La ronda que escribe el handoff también puede fallar —— se cortó la red, el modelo tuvo un fallo, el parseo salió con
una sección obligatoria faltante. Como el auto-compact ya está apagado, **no hay respaldo**, y parar aquí equivale a
chocar contra la ventana.

El enfoque: ensamblar mecánicamente un **handoff incompleto** con lo que ya se conoce a mano, marcando en `doing`
`[degradado: el handoff no se pudo escribir]` (la constante `DEGRADED`), metiendo en `scene` los primeros **1200**
caracteres de la tarea original, y cambiando de generación igual. A quien toma el relevo se le dice explícitamente que
lo que recibe está incompleto y que debe ir a mirar la escena por su cuenta. Al mismo tiempo `StepResult.errors`
lleva una entrada extra "handoff degradado (…)", y en `manifest.json` se puede consultar la razón.

Corresponde a la función a nivel de módulo `degraded(step, prompt, *, why="")`; `Handoff.degraded` es una property
de solo lectura, que juzga si `doing` tiene esa marca.

> **Un handoff incompleto es muy superior a chocar contra la ventana.**

La ronda que escribe el handoff tiene además dos arreglos deliberados: corre con `max_budget_usd=None` —— **el
handoff tiene que poder escribirse, no puede atascarse en el presupuesto**; y `on_event=None` —— esta ronda no
refresca la UI.

### Una mina: la ronda que escribe el handoff tiene que estar exenta del umbral {#一颗地雷写交接那一轮必须豁免阈值}

El handoff se escribe **después de cruzar la línea** —— en ese momento el nivel de por sí sigue por encima del umbral.
Sin la exención, el primer mensaje de la ronda del handoff volvería a juzgar "hay que hacer handoff", y entonces se
interrumpiría sin haber escrito ni una palabra, **cada generación produce una pieza degradada**, y todo parece normal
(la ruta de degradación funciona muy bien).

Cayó en esto en la práctica: la primera vez que `tests/handoff_live.py` corrió de verdad, **ambas generaciones del
handoff fueron versiones degradadas**. Los tests offline no lo atraparon —— allí `_attempt` se reemplaza por completo,
y el falso no corre este criterio. Ahora el criterio se elevó a `Runtime._handoff_due()`, y offline se verifica
directamente.

### Un cierre contra el descontrol {#一道防跑飞的闸}

`max_generations=8`.

!!! danger "un `window` configurado pequeño lleva a handoffs infinitos que queman dinero"
    El peligro es: **el umbral por debajo del piso de arranque de este rol** (el
    [coordinator](../reference/glossary.md#协调者) mide alrededor de 34k, solo el system prompt más el índice del
    [workbench](../reference/glossary.md#工作台) ya lo ocupan), entonces cada nueva sesión cruza la línea en cuanto
    abre la boca → escribe el handoff, cambia de generación, vuelve a cruzar, **nunca para**. Y como el handoff no
    consume cuota de reintentos, que es intencional, el único cierre es `max_generations=8`.

    Una long-horizon normal no llega a 8 generaciones; si de verdad choca, casi con seguridad `window` está configurado
    pequeño —— al llegar al límite el mensaje de error lo dice directamente ("el umbral muy probablemente está por
    debajo del piso de arranque de este rol, sube window, o `--no-handoff`").

### El proceso completo de un handoff {#一次换代的完整过程}

```text
Trabajando (session A)
  |  el contexto del main thread cruza el umbral   <- solo mira el main thread. El contexto del subagent es asunto de su propio
  |                            transcript, se disipa al terminar, y no debe forzar el handoff de la sesión principal
  |- corta en un límite de mensaje       <- el mismo razonamiento que interrumpir con Ctrl-C: cortar limpio, sin desgarrar el estado
  |                            (el costo es el mismo: los subagents en vuelo se pierden. El margen de 50k está reservado para esto)
  |- correr una ronda más en la misma session: escribir el handoff
  |     por qué lo escribe ella misma —— solo ella tiene ese contexto. Cualquier otro que escriba tendría que leerlo antes, y entonces el cambio no sirvió de nada
  |- congelar a <workbench>/notes/交接-<nombre del step>.md, la generación anterior se mueve a notes/archive/交接/
  |- nueva sesión (resume=None, fork=False), prompt = prompt_block() del handoff document
Trabajando (session B) sigue
```

`HANDOFF_PROMPT` es el prompt que hace que la sesión actual escriba el handoff, con dos placeholders `{used}` y
`{window}`. **No es un rol nuevo** —— solo esta sesión actual tiene ese contexto.

### El handoff no cuenta como reintento, cómo se lleva la cuenta {#换代不算重试账怎么记}

| Campo | Cómo cambia en el handoff |
|---|---|
| `attempts` | **no sube** —— cuenta los intentos fallidos |
| `retired[]` | los session_id quemados en este step se registran aquí **en orden** |
| `session_id` | siempre es **el último sucesor**, no el que se quemó |
| `context` | el tamaño de contexto que el main thread vio realmente en la última ronda |
| `cost_usd` / `num_turns` | **se acumulan** a través de reintentos y handoffs |

Todos estos campos entran en `manifest.json`, y a posteriori se puede reconstruir por completo "cuántas generaciones
quemó este step, cuánto costó cada una".

### Dónde queda el handoff {#交接落在哪}

`<workbench>/notes/交接-<nombre del step con caracteres ilegales quitados>.md`; la generación anterior existente se
mueve a `notes/archive/交接/<nombre del step>-<timestamp>.md`.

**Sin workbench no hay spill al disco** —— entonces `_handoff_path` retorna `None`, el documento igual se entrega a
quien toma el relevo vía prompt, el handoff procede como de costumbre, solo que **la persona no puede recuperar ese
archivo después**. Para poder recuperarlo, hay que activar el workbench (`Runtime(workbench=True)`, o que el
[workflow](../reference/glossary.md#流程) monte uno él mismo).

## Cuándo no deberías usarlo {#什么时候不该用它}

- **Simplemente quieres usar compact.** `flower --no-handoff`, o `Runtime(handoff=False)`. El handoff apaga de paso
  el auto-compact, y si no quieres ese efecto colateral, no lo actives.
- **Quieres que ambos mecanismos estén a la vez.** Dar explícitamente `AgentSpec(compact=CompactPolicy(mode="auto"))`
  conserva el auto-compact, pero después de eso "quién causó cierta caída del contexto" no queda claro, y depurar se
  vuelve más difícil. O confías en el handoff o confías en el compact, no en ambos.
- **Tareas cortas, trabajo de una sola ronda.** El handoff nunca se dispara, configurarlo no tiene sentido —— pero
  recuerda que el `Runtime` por defecto con `handoff=True` igual apagó el auto-compact.
- **Sin workbench y esperando leer el handoff después.** Activa primero el workbench, si no el documento solo aparece
  en el contexto de esa única run.
- **Empezar una long-horizon sin haber emparejado `window`.** Cuando la ventana real es menor que el valor por defecto,
  las primeras generaciones del handoff serán todas piezas degradadas, y la pieza degradada es precisamente el tipo de
  handoff más inútil. Empareja primero con `--window`, o corre primero una run corta y mira el nombre del modelo en `-v`.
- **Tomar el handoff como todo el gobierno del contexto.** Es la última línea. Las capas que recortan en el momento
  (spill, [trim](../reference/glossary.md#裁剪), [prune](../reference/glossary.md#剪除)) son más baratas, ver
  [economía del contexto](context.md).

## Perillas {#旋钮}

| Síntoma | Cuál ajustar |
|---|---|
| Handoffs demasiado frecuentes, el trabajo siempre se interrumpe | Ajusta `--window` a la ventana real del modelo (`-v` muestra el nombre del modelo vigente) |
| Handoff apenas empieza, y reporta "piso de arranque" | Lo mismo, `window` configurado pequeño |
| El handoff siempre queda degradado | Mira `errors` en `runs/manifest.json`, ahí está la razón de la degradación |
| Quien toma el relevo repite siempre el trabajo de la generación anterior | La sección "caminos sin salida" del handoff quedó demasiado fina. Puedes editar ese archivo directamente |
| Quieres leer el handoff después pero no encuentras el archivo | No activaste el workbench. El handoff no hace spill, solo fue por prompt |
| Simplemente quieres usar compact | `--no-handoff` |

## Relacionado {#相关}

- [continuity](continuity.md) —— reengancha entre procesos con la run anterior, es lo mismo que esta página en el otro sentido
- [economía del contexto](context.md) —— las capas que recortan en el momento
- [goal guard](goal.md) —— el argumento de "el worker tiene un sesgo optimista sistemático"
- [Python API](../reference/api.md) —— `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [línea de comandos](../reference/cli.md) —— `--window`, `--no-handoff`
- Código fuente: [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
