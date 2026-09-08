# Clarify

Antes de mover un dedo, deja el requisito claro. El [clarificador](../reference/glossary.md#确认者) es un rol que solo pregunta y no ejecuta nada:
pregunta hasta que todo queda claro y al final emite un [brief](../reference/glossary.md#需求确认书) de exactamente cuatro secciones,
congelado en disco. Cada [paso](../reference/glossary.md#步骤) posterior arranca leyendo ese documento y ya no vuelve a adivinar el requisito —
y ese interrogatorio **nunca entró** en el contexto de los pasos siguientes.

## Qué problema resuelve {#解决什么问题}

Todo lo que los mecanismos de limpieza de contexto de flower eliminan es **material en curso**: caducidad por tiempo, poda de llamadas rechazadas, poda de mensajes de error,
[spill](../reference/glossary.md#落盘) de resultados grandes. Perder material en curso no importa: se vuelve a ejecutar y aparece otra vez.

Hay una clase de error que no funciona así: **entender mal el objetivo**. Es la única clase de error que **empeora cuando limpias el contexto**. Una vez descartado el material en curso,
lo que queda es justamente la decisión construida sobre la premisa equivocada, y se ve exactamente igual que una decisión correcta —
sin ninguna huella que indique que su premisa es sospechosa.

El [long-horizon](../reference/glossary.md#长程) lo amplifica hasta el peor caso: la premisa equivocada corre primero varias horas,
despacha una docena de [subagents](../reference/glossary.md#subagent), deja un montón de artefactos en disco, y solo después se destapa.
Para entonces lo caro no son los tokens: es que **cada artefacto está construido sobre el requisito equivocado**.
Las cuentas de [HT001](../cases/ht001.md) permiten medir esa proporción: el paso de confirmar el requisito costó **$0.3704 / 5 turnos / 0.06h**,
y el paso que hace el trabajo, **$171.2476 / 31 turnos / 10.44h**.

Por eso hace falta un canal capaz de «parar y preguntar», y tiene que estar **antes** de empezar a trabajar.

## Cómo se usa (código mínimo) {#怎么用最小代码}

### Cero código: línea de comandos {#零代码命令行}

Entra en el directorio del proyecto y ejecuta directamente:

```bash
cd /path/to/your/project
flower
```

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

En la terminal verás preguntas como esta:

```text
  ? 这个工具是给命令行用,还是要有 Web 界面?
     1) 纯命令行
     2) Web 界面
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
```

- Escribe el **número** para elegir una opción, o responde escribiendo directamente
- **Enter = saltar** esa pregunta; el agente decide por su cuenta y anota el supuesto en «未知与假设» (incógnitas y supuestos)
- Solo pasa con las cuatro secciones completas; el brief queda congelado en `.flower/notes/需求.md`
- **Volver a ejecutar no repite el interrogatorio** — para reconfirmar, borra ese archivo o añade `--new`

Si solo quieres ver qué pregunta, sin que siga trabajando: `flower --clarify-only`. Para poner una cuota dura de preguntas: `--asks 12`
(solo si la das aparece bajo las opciones la línea extra `(还能问 N 次)`; por defecto no hay límite y esa línea no sale). Si no hay nadie delante: `--timeout 0`.
La implementación de este camino está en
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "Las respuestas van por stdin: hay que ejecutarlo en una terminal real"
    En pipes, `nohup` o CI no hay nadie que conteste: en cuanto stdin lee EOF, la pregunta que estaba colgada se trata como «entrada cerrada» y se salta,
    y a partir de ahí cada pregunta se queda esperando el `--timeout` completo. En ese escenario pon directamente `--timeout 0` —
    todas las preguntas caen en vacío al instante, el agente decide solo y escribe los supuestos en «未知与假设».

### Cableado manual {#自己接线}

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # sin límite de preguntas por defecto; espera 30 minutos a la persona
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

En `prompt` va solo **tu** petición original; una frase basta. Qué preguntar lo decide el propio clarificador —
qué cuestiones tiene que hacerte en tu dominio el framework no lo sabe ni debería saberlo. El `协调者` de arriba es un `AgentSpec`
que has construido tú con `coordinator()`; ver [Diseñar el workflow](workflow.md).

Parámetros de `clarify_step()`:

| Parámetro | Por defecto | Descripción |
|---|---|---|
| `channel` | — | `HumanChannel`. **La misma instancia** debe engancharse también en `Workflow(channel=...)` |
| `brief_path` | — | Dónde cae el brief. Tiene que estar dentro del [workbench](../reference/glossary.md#工作台) que enganchaste; ver más abajo |
| `prompt` | — | Tu petición original. `str` o `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Nombre del paso, y también la clave dentro de `ctx` |
| `spec` | `None` | Trae tu propio `AgentSpec`; si lo das, ya no se construye con `clarify()` |
| `instructions` | `""` | Instrucciones de dominio que se añaden después de `CLARIFIER_RULES` |
| `always_ask` | `False` | `True` = reconfirmar siempre (útil al cambiar el requisito) |
| `on_fail` | `"stop"` | Qué hacer si faltan secciones; igual que `Step.on_fail` |
| `retries` | `0` | Cuántos reintentos si faltan secciones |
| `**spec_kw` | — | Se pasan a `clarify()`: `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

Al terminar hay tres cosas en `ctx`:

```python
ctx["确认需求"]     # str, versión compacta de las cuatro secciones (prompt_block), lista para insertar en el prompt siguiente; clave = nombre del paso
ctx[BRIEF_KEY]     # "_brief" —— objeto Brief; úsalo si quieres las secciones por separado
ctx[MISSING_KEY]   # "_brief_missing" —— solo existe si faltan secciones: cuáles faltan, para mostrarlo en la UI
```

Cuando no acaba de ir fino, empieza por estas perillas:

| Síntoma | Qué tocar |
|---|---|
| Pregunta demasiado, demasiado fragmentado | Dale una cuota dura con `max_asks`; escribe en `instructions` qué es obvio en tu dominio |
| Pregunta poco y se lanza a trabajar | En `instructions`, nombra explícitamente qué cosas debe aclarar (el número de preguntas ya es ilimitado por defecto: tocar la cuota no sirve) |
| Rellena las cuatro secciones de forma superficial | Da en `instructions` un ejemplo de tu propio dominio |
| Se atasca sin nadie de guardia | `timeout_s=0` |
| Quieres reconfirmar siempre | `always_ask=True`, o borra el archivo del brief |

## Qué hace en realidad {#它实际做了什么}

### Cuándo se dispara: tres puntos de cableado, ni un campo nuevo {#触发时机三处接线一个新字段都没加}

Lo que construye `clarify_step()` es un `Step` normal y corriente; solo rellena tres callbacks:

| Dónde engancha | Cuándo corre | Qué hace |
|---|---|---|
| `Step.when` | Antes de entrar en el paso | Si el brief ya existe y tiene las cuatro secciones, **salta** el paso y lo vuelca en `ctx` |
| `Step.gate` | Al terminar el paso, antes de pasar el resultado adelante | Si faltan secciones, **no deja continuar**; si están completas, hace `write()` y lo **congela** |
| `Step.reduce` | Tras pasar el gate | Pasa hacia adelante **las cuatro secciones parseadas**, no el texto original del modelo |

**Al saltar también rellena `ctx`.** Este detalle se escapa fácil: cuando `when` devuelve `False`, `Workflow` no ejecuta el paso
y por tanto tampoco escribe `ctx[step.name]` — así que `clarify_step` vuelca el brief existente dentro del propio `when`.
Si no, al reejecutar los pasos siguientes se comerían un `KeyError`.

`reduce` pasa `Brief.prompt_block()` y no el texto original del modelo, porque en ese texto puede colarse cosas de más
(medido: pega el código entero dentro de la respuesta).

En la [continuidad](../reference/glossary.md#接续), este paso abre con otra frase — `CLARIFY_RESUME`:
«continúa la confirmación de requisitos que quedó a medias, **no empieces de nuevo**…». Sin esa frase,
la continuidad reenvía la petición original como si fuera una tarea nueva y el clarificador puede repetir preguntas ya hechas.

### Límite: el interrogatorio no entra en el contexto de los pasos siguientes {#边界问答不进下游的上下文}

```text
确认需求        独立会话  ────→  磁盘上一份冻结的四段确认书
                                          │
干活(下一步)   新会话(resume_from=None)◄─┘   只拿到那四段
```

El `resume_from` de `clarify_step` se queda en su valor por defecto `None`, así que el paso siguiente es una **sesión nueva** y solo recibe el brief.
Ese interrogatorio **nunca entró** en el contexto del [coordinador](../reference/glossary.md#协调者) —
no es que «entrara y luego se podara». La diferencia es sustancial: lo podado sigue en `sessions.db`
y todavía puede volver con un resume; lo que nunca entró no tiene ese problema.

El interrogatorio en sí se **añade a `log_path`**. Esa copia no ocupa contexto, no la afecta el compact y sigue ahí si cambias de máquina —
la misma idea que el workbench.

### Cada sección bloquea un tipo de fallo {#四段各挡一类失败}

| Sección | Qué se escribe | Qué pasa si no se escribe |
|---|---|---|
| **目标** (Objetivo) | Una frase: qué se hace y para quién | Se construye otra cosa |
| **验收标准** (Criterios de aceptación) | Condiciones decidibles, una por línea. «Que esté bien» no vale; «ejecutar `x` produce `y`» sí | Nadie puede decidir si «está terminado» |
| **边界** (Límites) | **Qué explícitamente no se hace** | Deriva de alcance. Esta sección sujeta a **todos** los subagents posteriores |
| **未知与假设** (Incógnitas y supuestos) | Lo que no se llegó a preguntar, lo que cayó por timeout, lo que se adivinó; una línea por ítem | **La premisa equivocada queda enterrada en silencio** |

La cuarta sección es el fusible de una ejecución long-horizon. Si cualquiera de las tres primeras está mal, mientras el supuesto esté escrito explícitamente en la cuarta, quien lo lea después tiene la oportunidad de frenarlo;
si queda enterrado, solo te enteras horas más tarde, cuando todos los artefactos están para tirar. La premisa equivocada no se puede evitar del todo, pero sí se puede hacer **explícita**.

Solo pasa con las cuatro secciones completas; cuál falta lo reporta `Brief.missing()` — devuelve los nombres de sección en chino, listos para mostrarse tal cual.

El parser es muy tolerante con el formato: reconoce `## 目标` / `**目标**` / `目标:` / `3. 边界`, reconoce que el cuerpo venga pegado al título
(`目标: 做一个 X`) y reconoce los alias habituales (`验收条件`→验收标准, `不做什么`→边界,
`未知项与假设`→未知与假设); si una sección aparece varias veces, se toma la primera con contenido. Hay dos excepciones que conviene saber:

- `Brief.parse()` **primero quita los bloques con fences**; si encuentra un fence **sin cerrar**, descarta todo desde ahí hacia adelante.
  Si la salida del modelo se trunca, las secciones posteriores no se parsean → faltan secciones → el `gate` lo devuelve.
- `Brief.load()` trata `"(未填)"` como vacío. Si al editar el brief a mano copias el texto de relleno de `to_markdown()`,
  esa sección sigue contando como ausente.

### Límite: qué puede tocar el clarificador {#边界确认者能碰什么}

Se probó un clarificador **sin restricciones** (`/tmp/probe_ask.py`, **$0.8908 / 230 segundos**):
tras dos preguntas **se puso directamente a escribir código**; cuando los permisos lo pararon, **pegó el código entero en el cuerpo de la respuesta**.
Escribir «no escribas código» en el prompt no lo detiene — su system prompt de entonces ya tenía una frase parecida. Por eso hay dos mecanismos:

**Uno: un hook le corta las herramientas de escritura.** La lista de exención de aprobación de `clarify()` es
`mcp__human__ask` más (cuando `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch`;
sin `Write` / `Edit` / `Bash` / `Agent`. Quien lo ejecuta de verdad es el `whitelist_guard` que `Runtime` instala automáticamente:
deduce de la lista de exención cuáles de `Bash` / `Write` / `Edit` / `NotebookEdit` hay que bloquear
y hace `deny` al acertar. No es que «se le pida no trabajar»: es que **no puede** trabajar.

Darle lectura sale a cuenta: un vistazo al repositorio ahorra varias preguntas, y esta sesión se tira al terminar, así que ensuciarla leyendo da igual
(con `can_read=False` puedes quitarle también la lectura).

**Esto tiene que ser un hook, no basta con `allowed_tools`.** Este último es una **lista de exención de aprobación, no una whitelist excluyente** —
el modelo puede invocar igualmente herramientas que no estén en ella. Dos evidencias medidas que siguen en pie:

- En [HT002](../cases/ht002.md), el [juez](../reference/glossary.md#判定者) del paso «fijar objetivo»
  ejecutó de hecho **11 veces `Bash`**, cuando `judge()` tiene `can_run=False` por defecto y `Bash` ni siquiera estaba en la lista
  (esa ejecución todavía no tenía este hook — hoy la misma llamada la haría `deny` el `whitelist_guard` en el acto,
  lo cual demuestra precisamente que quien lo para es el hook y no la lista).
- **Una sonda de $0.1**: a un agente con `allowed_tools=["Read"]` se le pide escribir un archivo —
  `Write` lo rechaza la capa de permisos (`"requested permissions to write ... but you haven't granted it yet"`),
  y `Bash` lo rechaza la seguridad de rutas (`"Output redirection was blocked. For security, Claude Code may
  only write to files in the allowed working directories"`). **La llamada salió**;
  la pararon otras capas.

`clarify()` no fija `permission_mode` explícitamente: hereda el `"default"` de `AgentSpec`.
`coordinator()` usa `"acceptEdits"` por defecto — quien pase ese valor al clarificador se queda sin esa protección.

**Dos: el framework solo parsea esas cuatro secciones y descarta todo lo demás.** `Brief.parse()` primero arranca los bloques con fences y luego busca los títulos —
aunque lo pegue, no llega a los pasos siguientes. Es la última compuerta contra «que contamine lo de abajo».

### Límite: el canal de preguntas {#边界提问通道}

La herramienta de preguntar del lado del modelo se llama `mcp__human__ask` (parámetro `question`, `options` opcional).
`HumanChannel` es un servidor MCP dentro del proceso y **registra dos herramientas** —
`mcp__human__ask` y `mcp__human__inbox`; en la lista de exención del clarificador solo está la primera
(el buzón es para el coordinador).

```python
HumanChannel(
    on_event=None,        # callback para UI push. Al engancharlo al Workflow, lo conecta Workflow.run automáticamente
    max_asks=None,        # sin límite por defecto
    timeout_s=1800.0,     # 30 minutos. None = esperar para siempre; <= 0 = totalmente automático
    log_path=None,        # el interrogatorio se añade a este archivo, no ocupa contexto
    amend_path=None,      # lo que la persona diga durante la ejecución se añade a este archivo (normalmente el propio brief)
    over_budget_text=..., timeout_text=..., declined_text=...,   # redacción de los tres tipos de respuesta en vacío
)
```

Lo normal en un agente long-horizon es que **no haya nadie mirando**, así que «parar y esperar a una persona» tiene que fallar con elegancia:

| Ajuste | Comportamiento |
|---|---|
| `timeout_s=1800.0` (por defecto) | Espera media hora; al vencer devuelve una frase explicativa, **no un error** |
| `timeout_s=None` | Espera para siempre. Solo con guardia humana confirmada (la CLI no puede dar este valor: `--timeout` es un float) |
| `timeout_s=0` (y negativos) | **Totalmente automático**: todas las preguntas caen en vacío al instante, sin fingir que espera |
| `max_asks=None` (por defecto) | **Sin límite** — cuántas veces preguntar lo decide el propio clarificador |
| `max_asks=N` | Cuota dura. Las preguntas que la excedan las **rechaza la herramienta directamente**, sin bloquear ni dar error |
| `max_asks=0` | Prohibido preguntar (CI / sin guardia) |

Con `max_asks=None`, `remaining` devuelve `-1` (no 0, ni infinito), y por eso la terminal no muestra «还能问 N 次».

El texto literal que se devuelve al vencer el timeout es:

> Nadie ha respondido. Continúa según tu propio criterio y escribe esta pregunta y el supuesto que adoptes en la sección «未知与假设».
> No repitas la pregunta ni te quedes parado aquí.

Los tres tipos de respuesta en vacío (timeout / cuota agotada / la persona salta la pregunta) apuntan todos a la misma acción: **escribir el supuesto en la cuarta sección**.
Por eso la cuarta sección sigue teniendo contenido sin guardia humana, y por eso la ejecución long-horizon puede seguir adelante.
Una cuota escrita en el prompt es una sugerencia; **el contador en el canal es la garantía**.

Un hecho mecánico ya comprobado: dentro del handler de una herramienta MCP en proceso, hacer `await` sobre un future externo **no produce deadlock** —
mientras el handler está colgado el event loop sigue girando, y tanto otra tarea como **otro hilo** pueden rellenar la respuesta.
Por eso `answer()` / `decline()` se pueden llamar directamente desde un backend web o desde el hilo de entrada de una TUI (por dentro pasan por
`loop.call_soon_threadsafe`); es el caso normal, no un caso límite. Las excepciones lanzadas por los callbacks de UI se recogen en `ui_errors` y
**no interrumpen la ejecución** — que se caiga el frontend no debería llevarse por delante tres horas de trabajo. La tabla completa de miembros está en [API de Python](../reference/api.md).

!!! warning "Con un `max_turns` pequeño, «preguntar hasta que quede claro» es papel mojado"
    El `max_turns` de `clarify()` es `None` por defecto (sin límite). **Cada pregunta consume un turno** —
    ponerlo en 16 equivale a «como mucho una docena de preguntas», y lo hace de forma **silenciosa**: el canal sigue diciendo `max_asks=None`,
    «sin límite», y la persona no ve quién lo estranguló. Para dejar las preguntas abiertas, `HumanChannel.max_asks`
    y `clarify(max_turns=...)` **tienen que quedarse los dos en `None`**.

### Dónde cae el brief: tiene que ser el workbench que enganchaste {#确认书落在哪必须是挂上去的那个工作台}

El índice del workbench se inyecta en el system prompt, así que el coordinador sabe desde el principio dónde está el archivo de requisitos; al repartir trabajo basta con pasar la ruta,
sin copiar el contenido dentro del [task brief](../reference/glossary.md#任务书).

!!! warning "El índice solo llega al coordinador"
    Los subagents tienen su propio system prompt y **no heredan** el de nivel de sesión (medido: **$0.2461**,
    `tests/prelude_live.py`). Así que es «el coordinador transmite la ruta», no «cada subagent lo sabe automáticamente».

Lo importante es **cuál** workbench. Solo hay una forma correcta: créalo tú, engánchalo al `Workflow`
y deja que el programa que arranca todo entregue el mismo objeto al `Runtime`.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← enganchado
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Dos formas de hacerlo mal, y ninguna **da error**, así que hay que tener especial cuidado:

```python
# ✗ Construir la ruta a mano: es relativa al cwd del proceso, y el <run_dir>/workbench que crea
#   Runtime(workbench=True) es otro directorio. El brief se escribe en A y el índice inyectado escanea B —
#   la promesa de arriba se rompe en silencio.
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ Intentar sacarlo del Runtime hacia atrás: por cli.py no se puede. Primero llama a main() para construir el Workflow
#   y solo después crea el Runtime —— para entonces brief_path ya está fijado.
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

Si escribes tu propio arranque (sin pasar por `cli.py`), crea primero el `Workbench` y entrega el **mismo objeto** a
`Workflow(workbench=wb)` y a `Runtime(workbench=wb)`. El ítem 5 de `tests/trial_offline.py`
afirma directamente que «el brief aparece dentro de `prompt_block()`», y el ítem 11 confirma que esa aserción detecta la regresión.

### Estado de verificación {#验证状态}

**Todo en verde offline** (`tests/clarify.py`, **52 ítems**, sin coste): las cinco semánticas del canal de preguntas (esperar bloqueando la respuesta /
cuota agotada / caer por timeout / saltar / responder desde otro hilo), el parseo de las cuatro secciones (incluida una muestra con «me pegó código dentro»),
que el rol de `clarify()` **no tiene** herramientas de escritura, y los tres puntos de cableado de `clarify_step`.

**El camino de la CLI corre offline de punta a punta**: brief completo precargado → el primer paso se salta → el canal engancha automáticamente el hilo de stdin →
el brief se vuelca en `ctx` → salida limpia.

**No se ha probado contra la API real.** La sonda de $0.8908 sí fue una **petición real**, pero medía «qué hace un clarificador sin restricciones»,
no este camino tal como está ahora.

## Cuándo no usarlo {#什么时候不该用它}

**El requisito ya es un artefacto congelado.** Si el requisito está en un archivo, viene dado por un sistema aguas arriba, o esta vez se trata de repetir lo mismo —
no hay nada que preguntar. Pasa el texto del requisito directamente al paso que trabaja, o deja el `clarify_step` y que su `when` lo salte
(si el brief está ahí, de todas formas no pregunta).

**No hay nadie a quien preguntar y no quieres que adivine.** Con `timeout_s=0` todas las preguntas caen en vacío al instante
y la cuarta sección se llena de supuestos propios — está diseñado así, pero la fiabilidad de ese brief es exactamente la de esos supuestos.
En CI, la forma más limpia es `max_asks=0` (prohibido preguntar explícitamente) y que el requisito venga completo desde fuera.

**Trabajos pequeños de una sola vez.** El paso de confirmar cuesta dinero por sí mismo: en [HT002](../cases/ht002.md),
para algo como «clona un repositorio, instálalo y ponlo a correr en macOS», confirmar el requisito costó **$0.5306 / 9 turnos / 0.10h**.
Cuanto más pequeño es el trabajo, peor pinta la proporción de este paso. El camino de agente único de `flower once` no lo incluye.

**Al cambiar el requisito no hay que volver a conversar.** El brief es un artefacto congelado: desde el momento en que cae a disco, el requisito lo manda el archivo —
lo correcto es **editar ese archivo**. `--clarify-only` sobre un directorio ya confirmado es una **operación vacía**
(ese workflow solo tiene ese paso, y ese paso se salta); para reconfirmar hay que combinarlo con `--new`,
o poner `always_ask=True` en tu propio cableado.

**No decide si «está terminado».** Eso es otra capa; ver [guardián de objetivo](goal.md). El clarify frena «se ha construido algo que no era»,
no frena «dice que está terminado cuando en realidad no lo está».
