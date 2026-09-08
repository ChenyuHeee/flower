# Handoff

Cuando el contexto está casi lleno, haz que **esa misma sesión** escriba un [documento de handoff](../reference/glossary.md#交接书) que una persona pueda leer y editar,
y luego abre una sesión nueva que tome el relevo. Sin compact. Todo el proceso lo ves en la terminal, y el documento queda en disco,
lo puedes editar cuando quieras — la sesión que toma el relevo lee exactamente ese archivo.

!!! note "El handoff no es continuidad"
    El [handoff](../reference/glossary.md#换代) cambia a una [sesión](../reference/glossary.md#会话) nueva **dentro de la misma run**;
    la [continuidad](../reference/glossary.md#接续) retoma la [run](../reference/glossary.md#运行) anterior **entre procesos**,
    ver [Continuidad](continuity.md).

    Las dos encajan automáticamente, no hace falta cablear nada: el [linaje](../reference/glossary.md#血缘) registra el `session_id`
    **final** de ese step, y ese es justamente el sucesor — así que el siguiente wake se engancha al sucesor, no a la generación quemada.

## Qué problema resuelve {#解决什么问题}

El auto-compact que trae el SDK se dispara en **ventana −33k** (medido: con ventana `200000` el umbral es `167000`;
el algoritmo de compresión vive dentro del binario del harness, no se puede tocar; lo único ajustable es si se dispara o no),
y lo que hace es **resumir el historial en un párrafo**.
Eso va a contrapelo del resto del framework:

| | Cuándo decide | Qué deja |
|---|---|---|
| `spill_guard` | En el instante en que la tool devuelve | El resultado grande va [a disco](../reference/glossary.md#落盘), en el contexto queda una línea con la ruta |
| Artefacto congelado (brief / objetivo) | Al terminar ese step | Un documento; el siguiente step solo lee eso |
| **auto-compact** | **Solo mira atrás cuando el contexto ya está lleno** | **Un resumen escrito por el propio modelo** |

Lo que flower hace de principio a fin es **decidir en el momento qué se queda**. El [compact](../reference/glossary.md#压缩) es el único punto de "remedio a posteriori",
y su producto tiene cuatro defectos:

- **Lo genera el modelo** — qué va en el resumen depende del criterio del modelo en ese momento, tú no participas
- **No es legible** — está escrito para el modelo de la siguiente vuelta, no para una persona
- **No es editable** — vive dentro del harness, no hay un archivo que puedas abrir
- **No sabes qué se perdió** — ni ves qué se fue, ni puedes decir "eso no lo tires" antes de que lo tire

El handoff devuelve esto al mismo enfoque: **otro artefacto congelado**, de la misma forma que el brief y el objetivo —
estructurado, en disco, **puedes abrirlo, cambiar una línea y dejarlo seguir**. Y es exactamente lo que hace este propio proyecto:
el `HANDOFF.md` en la raíz del repo es esa misma cosa, escrita a mano.

## Cómo se usa (código mínimo) {#怎么用最小代码}

La línea de comandos ya trae handoff por defecto:

```bash
flower                       # el handoff viene activado por defecto
flower --window 200000       # solo hace falta darlo si la detección falla (por defecto 1 millón)
flower --no-handoff          # apagarlo: se vuelve al auto-compact del SDK
```

Escribiendo código, el handoff se controla con `Runtime(handoff=…)`, y por defecto es `True`:

```python
from flower import HandoffPolicy, Runtime

# Por defecto: HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# Ventana explícita (esto es lo primero que hay que ajustar al cambiar de gateway o de modelo)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # apagado, se vuelve a auto-compact
```

`Runtime.__init__` es enteramente keyword-only y `workspace` es obligatorio. `handoff` acepta una instancia de `HandoffPolicy` o
un `bool`; con un `bool` equivale a `HandoffPolicy(enabled=…)`.

!!! warning "Handoff activado = auto-compact forzosamente apagado"
    `Runtime(handoff=True)` es el **valor por defecto**, y hace lo siguiente al montar cada intento: mientras
    `handoff.enabled` y `spec.compact is None`, sustituye la spec por
    `CompactPolicy(mode="no_summary")` — es decir, inyecta **`DISABLE_AUTO_COMPACT=1`** en el subproceso.

    La razón es que si los dos mecanismos corren a la vez, cuando el contexto baja de golpe ya no se puede saber quién lo hizo.
    El precio es que **no hay red de seguridad**: si falla la vuelta que escribe el handoff no se puede parar,
    ni se puede disimular y aguantar hasta el límite duro, así que hace falta una ruta degradada (ver más abajo).

    Para conservar el auto-compact como respaldo hay que dar **explícitamente** `AgentSpec(compact=CompactPolicy(mode="auto"))` —
    si la spec lo trae, se respeta y no se sobrescribe. Ojo: eso **gana en silencio** sobre los supuestos del lado del handoff.

## Qué hace realmente {#它实际做了什么}

### Cuándo se dispara: dos caminos hacia el handoff {#触发时机两条路进换代}

**Uno: el nivel llega al umbral.** El criterio es `_handoff_due`: `handoff.enabled`, **no estar en la vuelta que escribe el handoff**,
`_ctx >= handoff.at`, y que este step ya haya obtenido un `session_id`. `_ctx` es el tamaño de contexto que realmente vio la última vuelta
del **hilo principal** — solo mira el [hilo principal](../reference/glossary.md#主线程); el contexto de un [subagent](../reference/glossary.md#subagent)
es asunto de su propio transcript, se disuelve al terminar, y no debe forzar un handoff del hilo principal.

En `warn_at` se emite primero un aviso de proximidad, una sola vez por generación, sin llenar la pantalla.

**Dos: la API dice directamente "no cabe".** Ver la sección de `is_overflow` más abajo.

Ninguno de los dos caminos está **sujeto a `max_attempts`**, y **no consumen cupo de reintentos** (internamente `attempt -= 1`) —
un handoff no es un fallo.

### El documento de handoff: cinco secciones, solo dos obligatorias {#交接书五段必填只有两段}

Cada sección bloquea un tipo de error que comete quien toma el relevo:

| Sección | Campo | Qué bloquea |
|---|---|---|
| Qué se está haciendo | `doing` **obligatorio** | No saber dónde está uno parado |
| Ya decidido | `decided` | Volver a discutir lo ya decidido (con el **porqué**) |
| Callejones sin salida | `deadends` | **La sección más cara** — ver abajo |
| Siguiente paso | `next` **obligatorio** | Gastar media hora decidiendo qué hacer |
| Escena | `scene` | Las **rutas** de archivos y artefactos clave. Punteros, no contenido |

`Handoff.missing()` solo comprueba las dos secciones de `REQUIRED = ("doing", "next")`, y `complete()` es su negación.
**Exigir que "callejones sin salida" no esté vacío obliga a inventar** — al principio de una tarea es normal que esté vacío.
Y el veredicto de `complete()` tiene consecuencias: si falta una sección obligatoria, ese handoff se sustituye **entero por un artefacto degradado armado mecánicamente**
(ver abajo), lo cual es mucho peor que un handoff real al que le falta una sección. Por eso las otras tres son opcionales: si están, sirven; si no, no bloquean el handoff.

En `to_markdown()` las secciones vacías se escriben como `(空)`; el encabezado de `prompt_block()` le dice explícitamente a quien toma el relevo "estás tomando el relevo",
para que no se vuelva a pedir contexto a una persona. El campo `step` solo se usa en el encabezado del documento, no participa en el parseo.

#### Por qué "callejones sin salida" es la sección más cara {#走不通的路为什么最贵}

Porque es **lo que más caro le sale redescubrir a quien toma el relevo**, y lo que más fácil se le olvida a quien escribe.

El worker tiene un sesgo optimista sistemático ([Goal guard](goal.md) argumenta exactamente lo mismo): escribe lo que consiguió hacer
y olvida escribir lo que probó y no funcionó. Y eso segundo es lo verdaderamente caro — en [HT002](../cases/ht002.md) se dio una hora de vueltas a un problema de compilación,
y si la conclusión de esa hora no queda escrita, quien toma el relevo da exactamente las mismas vueltas.

Por eso `HANDOFF_PROMPT` dedica un párrafo entero a este punto, incluyendo ese coste medido.

### Qué aspecto tiene un handoff real {#长什么样}

```text
# 上下文 130.0K/200K · 还有约 20K 到换代

# 上下文 152.0K/200K —— 写交接准备换代
  - 现在在做  在给 Makefile 加 macOS 垫片头,让 sigemptyset 宏不再展开成语法错误。
  - 已定的事  不改业务源码 —— 用户明确说过边界,所以走 Makefile 生成 shim 这条路。
  - 走不通的  -D_ANSI_SOURCE 会把别的宏一起关掉;改 include 顺序无效。
  - 下一步    在干净 clone 上跑一次 make 验证 shim 成立。
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 152.0K 重新开始
```

**Totalmente automático, no se detiene a esperarte** — una run long-horizon no debería atascarse porque alguien se fue a comer.

El evento es `Event("handoff")`, y `payload["phase"]` tiene **tres** valores: `near` (proximidad), `writing` (escribiendo; escribir el handoff tarda una decena larga de segundos,
y sin este evento la interfaz parecería colgada) y `done` (handoff terminado). El payload de `done` además trae
`context`, `window`, `degraded`, `path` y `sections`.

### Cómo se calcula el umbral {#阈值怎么算}

```python
at      = max(10_000, window - headroom)   # línea de handoff, con suelo de 10k
warn_at = max(1_000, at - 20_000)          # línea de aviso de proximidad
```

El suelo de 10k de `at` es imprescindible — más bajo y ni siquiera da para escribir el handoff.

La escala de abajo usa `--window 200000` como ejemplo; **la ventana por defecto es 1 millón**:

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                       提醒  换代          硬上限
```

Si no se da `window`, `default_window()` decide a partir de la **cadena del nombre del modelo**, mirando solo estas dos variables de entorno,
`ANTHROPIC_MODEL` o `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Nombre del modelo | Se interpreta como |
|---|---|
| El nombre contiene la palabra suelta `1m` | `1_000_000` |
| El nombre contiene `haiku` | `200_000` |
| El resto, **y también si ninguna de las dos variables está definida** | `1_000_000` |

Ojo al orden: `1m` se comprueba primero, así que `claude-haiku[1m]` se interpreta como 1 millón, no como 200 mil.

Por qué `headroom` es `50_000`: el auto-compact se dispara en ventana −33k y el handoff tiene que llegar antes;
y "escribir el handoff" en sí requiere otra vuelta más. 50k cubre ambas cosas.

**`--window` es el interruptor que más hay que ajustar al cambiar de modelo o de gateway.** Del lado del SDK no se puede obtener un tamaño de ventana fiable,
solo se puede adivinar por el nombre. Si la ventana real es mayor → el handoff ocurre pronto (desperdicio, sin error); si es menor → llega tarde y hay que ajustarlo. Un dato medido que vale la pena:
el gateway de la máquina de desarrollo está configurado con `claude-opus-5[1m]`. Calculando con 200 mil, habría un handoff cada 150 mil,
cuando en realidad aguanta hasta 950 mil — **un factor 5 de diferencia**, y un trabajo long-horizon quedaría hecho trizas.

Con `flower -v` puedes ver, antes de arrancar, la configuración de credenciales en vigor (endpoint, nombre del modelo, token enmascarado dejando solo los 4 primeros caracteres).

### `is_overflow`: convertir un error duro en un handoff inmediato {#is_overflow把硬错变成当场换代}

Esto es la condición previa para **atreverse a poner 1 millón como valor por defecto de `default_window()`**.

Si la ventana se estima demasiado grande, el umbral nunca se alcanza, y como además el auto-compact está apagado, se choca de frente contra la API.
`is_overflow(*texts)` reconoce esa señal: `prompt is too long`, `context length exceeded`,
`maximum context length`, `too many total text bytes`, `input length and max_tokens exceed`, etc.

Una vez reconocida, se toma **la misma ruta de handoff**, solo que el handoff de esa generación será necesariamente degradado — esa sesión ya no puede
"correr una vuelta más para escribir el handoff", así que se usa directamente el artefacto degradado armado mecánicamente, se cambia a una sesión nueva y se sigue: **este step no falla**.

Así, el coste de haberse pasado en la estimación baja de "este step falla" a "el handoff de esta generación es degradado".

`is_overflow` es una **función a nivel de módulo**, no un método de `Handoff`, y es variádica.

### Cuando el handoff no se puede escribir: degradar, no parar {#交接写不出来时降级不是停下}

La vuelta que escribe el handoff también puede fallar — se cae la red, el modelo se descarrila, el parseo sale sin una sección obligatoria. Como
el auto-compact ya está apagado, **no hay respaldo**, y quedarse aquí equivale a chocar contra la ventana.

Qué se hace: se arma mecánicamente un **handoff incompleto** con lo que se sabe, se marca `doing` con `[降级:交接没写成]`
(constante `DEGRADED`), se mete en `scene` los primeros **1200** caracteres del prompt original, y se hace el handoff igual. A quien toma el relevo se le dice explícitamente
que lo que recibe está incompleto y que vaya a mirar la escena por sí mismo. Además, `StepResult.errors` gana una entrada "交接降级(…)",
y en `manifest.json` queda registrado el motivo.

La función correspondiente a nivel de módulo es `degraded(step, prompt, *, why="")`; `Handoff.degraded` es una property de solo lectura
que comprueba si `doing` lleva esa marca.

> **Un handoff incompleto es muchísimo mejor que chocar contra la ventana.**

La vuelta que escribe el handoff tiene además dos decisiones deliberadas: corre con `max_budget_usd=None` — **el handoff tiene que poder escribirse,
no puede atascarse por el presupuesto**; y con `on_event=None` — esa vuelta no emite hacia la UI.

### Una mina: la vuelta que escribe el handoff debe estar exenta del umbral {#一颗地雷写交接那一轮必须豁免阈值}

El handoff se escribe **después de haber cruzado la línea** — en ese momento el nivel sigue, naturalmente, por encima del umbral. Sin exención, el primer mensaje
de esa vuelta vuelve a decidir "toca handoff", así que se interrumpe sin haber escrito una sola palabra, **cada generación produce un artefacto degradado**,
y todo parece ir bien (la ruta degradada funciona de maravilla).

Se cayó en ello de verdad: la primera ejecución real de `tests/handoff_live.py` dio **dos generaciones con handoff degradado**. Los tests offline no lo detectaron —
allí se sustituía `_attempt` entero, y el doble no ejecutaba ese criterio. Ahora el criterio se ha extraído a `Runtime._handoff_due()`,
y offline se verifica directamente.

### Un freno contra la fuga {#一道防跑飞的闸}

`max_generations=8`.

!!! danger "Una `window` demasiado pequeña provoca handoffs infinitos y quema dinero"
    El peligro es este: si **el umbral queda por debajo del suelo de arranque de ese rol** (medido, el [coordinador](../reference/glossary.md#协调者) ronda los 34k,
    solo con el system prompt y el índice del [workbench](../reference/glossary.md#工作台) ya se lo come), entonces cada sesión nueva cruza la línea nada más abrir la boca
    → escribe handoff, cambia de generación, vuelve a cruzar, **sin parar nunca**. Y como el handoff no consume cupo de reintentos —eso es intencional—, el único freno es
    `max_generations=8`.

    Una run larga normal no llega a 8 generaciones; si se llega, casi seguro es que `window` está configurada demasiado pequeña — al alcanzar el límite el mensaje de error lo dice tal cual
    ("es muy probable que el umbral esté por debajo del suelo de arranque de este rol; sube window, o usa `--no-handoff`").

### El proceso completo de un handoff {#一次换代的完整过程}

```text
干活(session A)
  |  主线程上下文越过阈值   <- 只看主线程。subagent 的上下文是它自己那条
  |                            transcript 的事,跑完就散,不该逼主会话换代
  |- 在消息边界上断开       <- 和 Ctrl-C 打断同一个道理:干净地断,不撕裂状态
  |                            (代价一样:在飞的 subagent 会丢。50k 余量为此而留)
  |- 同一个 session 再跑一轮:写交接
  |     为什么是它自己写 —— 只有它有那段上下文。换谁来写都得先读一遍,那就白换了
  |- 冻结到 <工作台>/notes/交接-<步骤名>.md,上一代移进 notes/archive/交接/
  |- 新会话(resume=None、fork=False),prompt = 交接书的 prompt_block()
干活(session B)接着做
```

`HANDOFF_PROMPT` es el prompt con el que la sesión actual escribe el handoff; contiene los dos placeholders `{used}` y `{window}`.
**No es un rol nuevo** — solo la sesión actual tiene ese contexto.

### El handoff no cuenta como reintento: cómo se lleva la cuenta {#换代不算重试账怎么记}

| Campo | Qué le pasa en un handoff |
|---|---|
| `attempts` | **No sube** — cuenta intentos fallidos |
| `retired[]` | Los session_id quemados en este step se registran aquí **en orden** |
| `session_id` | Siempre el **último sucesor**, no el quemado |
| `context` | El tamaño de contexto que realmente vio la última vuelta del hilo principal |
| `cost_usd` / `num_turns` | **Se acumulan** a través de reintentos y handoffs |

Todos estos campos entran en `manifest.json`, y después se puede reconstruir por completo "cuántas generaciones quemó este step y cuánto costó cada una".

### Dónde queda el handoff {#交接落在哪}

`<工作台>/notes/交接-<步骤名去掉非法字符>.md`; la generación anterior, si existe, se mueve a
`notes/archive/交接/<步骤名>-<时间戳>.md`.

**Sin workbench no se escribe a disco** — en ese caso `_handoff_path` devuelve `None`, el documento igualmente llega a quien toma el relevo vía prompt
y el handoff ocurre con normalidad, solo que **después nadie puede ir a buscar ese archivo**. Para poder consultarlo después hay que activar el workbench
(`Runtime(workbench=True)`, o que el propio [workflow](../reference/glossary.md#流程) monte uno).

## Cuándo no usarlo {#什么时候不该用它}

- **Simplemente quieres usar compact.** `flower --no-handoff`, o `Runtime(handoff=False)`.
  El handoff apaga de paso el auto-compact; si ese efecto colateral no te sirve, no lo actives.
- **Quieres los dos a la vez.** Dar explícitamente `AgentSpec(compact=CompactPolicy(mode="auto"))` conserva el auto-compact,
  pero a partir de ahí "quién hizo bajar el contexto" deja de poder saberse, y diagnosticar se vuelve difícil. O confías en el handoff, o confías en compact, pero no en ambos.
- **Tareas cortas, trabajo de una sola vuelta.** El handoff nunca se dispara y configurarlo no tiene sentido — pero recuerda que `Runtime` con
  `handoff=True` por defecto sigue apagando el auto-compact.
- **No hay workbench y aun así esperas leer el handoff después.** Activa primero el workbench; si no, el documento solo existió en el contexto de aquella run.
- **Arrancar una run larga sin haber ajustado `window`.** Si la ventana real es menor que el valor por defecto, las primeras generaciones producirán handoffs degradados,
  y el degradado es justo el tipo de handoff más inútil. Ajusta primero con `--window`, o lanza antes una run corta y mira el nombre del modelo en `-v`.
- **Tomar el handoff como toda la gestión de contexto.** Es la última línea. Las capas que recortan en el momento
  (spill, [trim](../reference/glossary.md#裁剪), [prune](../reference/glossary.md#剪除)) son más baratas,
  ver [Economía del contexto](context.md).

## Tabla de síntomas: qué perilla girar {#旋钮}

| Síntoma | Qué girar |
|---|---|
| Handoffs demasiado frecuentes, el trabajo se interrumpe todo el rato | Ajusta `--window` a la ventana real del modelo (`-v` muestra el nombre del modelo en vigor) |
| Handoff nada más arrancar, con mensaje de "suelo de arranque" | Lo mismo: `window` está demasiado pequeña |
| El handoff sale siempre degradado | Mira `errors` en `runs/manifest.json`, ahí está el motivo de la degradación |
| Quien toma el relevo repite el trabajo de la generación anterior | La sección "callejones sin salida" está escrita demasiado floja. Puedes editar ese archivo directamente |
| Quieres leer el handoff después y no encuentras el archivo | No hay workbench. El handoff no se escribió a disco, solo fue por prompt |
| Simplemente quieres usar compact | `--no-handoff` |

## Qué leer a continuación {#相关}

- [Continuidad](continuity.md) — retomar la run anterior entre procesos; es la misma cosa que esta página, vista en la otra dirección
- [Economía del contexto](context.md) — las capas que recortan en el momento
- [Goal guard](goal.md) — el argumento de "el worker tiene un sesgo optimista sistemático"
- [Python API](../reference/api.md) — `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [Línea de comandos](../reference/cli.md) — `--window`, `--no-handoff`
- Código fuente: [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
