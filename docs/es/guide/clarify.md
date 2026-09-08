# Clarificación previa

Antes de mover un dedo, deja el requisito claro. El [clarificador](../reference/glossary.md#确认者) es un rol que solo pregunta y no toca nada;
pregunta hasta que queda claro y al final emite un [brief](../reference/glossary.md#需求确认书) de exactamente cuatro secciones,
congelado en disco. Cada [paso](../reference/glossary.md#步骤) posterior arranca leyendo ese documento, sin volver a adivinar el requisito —
y ese interrogatorio **nunca entró** en el contexto de los pasos de abajo.

## Qué problema resuelve {#解决什么问题}

Todo lo que los mecanismos de limpieza de contexto de flower eliminan es **material de trabajo**: caducidad por antigüedad, extirpación de llamadas rechazadas, extirpación de mensajes de error,
[volcado a disco](../reference/glossary.md#落盘) de resultados grandes. Perder ese material no importa: se vuelve a ejecutar y ahí está otra vez.

Hay una clase de error que no funciona así: **entender mal el objetivo**. Es la única clase de error que **la limpieza de contexto agrava**. Una vez descartado el material de trabajo,
lo que queda es justamente aquella decisión construida sobre una premisa equivocada, y se parece exactamente a una decisión correcta —
no queda ningún rastro que indique que su premisa es sospechosa.

Un contexto [long-horizon](../reference/glossary.md#长程) lo amplifica hasta el peor caso: la premisa equivocada corre unas horas,
lanza una docena de [subagents](../reference/glossary.md#subagent), deja un montón de artefactos en disco, y solo entonces se descubre.
A esas alturas lo caro no son los tokens: es que **cada artefacto está construido contra el requisito equivocado**.
Las cuentas de [HT001](../cases/ht001.md) dan la proporción: el paso de clarificar el requisito, **$0.3704 / 5 turnos / 0.06h**;
el paso de hacer el trabajo, **$171.2476 / 31 turnos / 10.44h**.

Por eso hace falta un canal capaz de «parar y preguntar», y tiene que estar **antes** de empezar.

## Cómo se usa (código mínimo) {#怎么用最小代码}

### Cero código: línea de comandos {#零代码命令行}

Entra en el directorio del proyecto y ejecuta:

```bash
cd /path/to/your/project
flower
```

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

En el terminal verás preguntas así:

```text
  ? 这个工具是给命令行用,还是要有 Web 界面?
     1) 纯命令行
     2) Web 界面
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
```

- Escribe el **número** para elegir una opción, o responde directamente con texto
- **Enter = saltar** esa pregunta: decide él y anota el supuesto en «未知与假设» (incógnitas y supuestos)
- Solo pasa con las cuatro secciones completas; el brief queda congelado en `.flower/notes/需求.md`
- **Volver a ejecutar no repite el interrogatorio** — para reclarificar, borra ese fichero o añade `--new`

Si solo quieres ver qué pregunta, sin que siga trabajando: `flower --clarify-only`. Para poner un cupo duro de preguntas: `--asks 12`
(solo si lo das aparece una línea extra bajo las opciones, `(还能问 N 次)`; por defecto no hay límite y esa línea no sale). Si no hay nadie delante: `--timeout 0`.
La implementación de esta ruta está en
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "Las respuestas van por la entrada estándar: ejecútalo en un terminal real"
    En una tubería, bajo `nohup` o en CI no hay nadie que conteste: en cuanto stdin llega a EOF, la pregunta que estuviera colgando se trata como «entrada cerrada» y se salta,
    y cada pregunta posterior espera el `--timeout` entero en balde. En ese escenario, pon directamente `--timeout 0` —
    todas las preguntas quedan sin respuesta al instante, él decide y escribe los supuestos en «未知与假设».

### Cablearlo tú mismo {#自己接线}

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # sin límite de preguntas por defecto, espera 30 minutos a la persona
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

En `prompt` escribe solo **tu** petición original, con una frase basta. Qué preguntar lo decide el propio clarificador —
qué preguntas hay que hacerte en tu dominio, el framework no lo sabe ni debería saberlo. El `协调者` de arriba es un `AgentSpec` que has construido tú con `coordinator()`,
ver [Diseñar el workflow](workflow.md).

Parámetros de `clarify_step()`:

| Parámetro | Por defecto | Descripción |
|---|---|---|
| `channel` | — | `HumanChannel`. **La misma instancia** debe engancharse también a `Workflow(channel=...)` |
| `brief_path` | — | Dónde cae el brief. Tiene que estar dentro del [workbench](../reference/glossary.md#工作台) que has enganchado, ver abajo |
| `prompt` | — | Tu petición original. `str` o `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Nombre del paso, y también la clave dentro de `ctx` |
| `spec` | `None` | Trae tu propio `AgentSpec`; si lo das, no se usa `clarify()` para construirlo |
| `instructions` | `""` | Instrucciones de dominio añadidas después de `CLARIFIER_RULES` |
| `always_ask` | `False` | `True` = reclarificar siempre (útil al cambiar el requisito) |
| `on_fail` | `"stop"` | A dónde ir cuando faltan secciones, igual que `Step.on_fail` |
| `retries` | `0` | Cuántos reintentos cuando faltan secciones |
| `**spec_kw` | — | Se pasan a `clarify()`: `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

Al terminar, en `ctx` hay tres cosas:

```python
ctx["确认需求"]     # str, versión compacta de las cuatro secciones (prompt_block), se inserta tal cual en el prompt de abajo; clave = nombre del paso
ctx[BRIEF_KEY]     # "_brief" —— objeto Brief, para acceder sección a sección
ctx[MISSING_KEY]   # "_brief_missing" —— solo existe si faltan secciones: cuáles faltan, para mostrarlo en la UI
```

Cuando no salga bien, toca primero estos mandos:

| Síntoma | Qué ajustar |
|---|---|
| Pregunta demasiado, y en trozos | Dale un cupo duro con `max_asks`; escribe en `instructions` qué es obvio en tu dominio |
| Pregunta poco y se pone a trabajar | Nombra en `instructions` qué cosas tiene que dejar claras sí o sí (el número ya es ilimitado por defecto, tocar el cupo no sirve) |
| Rellena las cuatro secciones de cualquier manera | Da en `instructions` un ejemplo de tu propio dominio |
| Se queda bloqueado sin nadie delante | `timeout_s=0` |
| Quiero reclarificar cada vez | `always_ask=True`, o borra el fichero del brief |

## Qué hace realmente {#它实际做了什么}

### Cuándo se dispara: tres enganches, ni un campo nuevo {#触发时机三处接线一个新字段都没加}

Lo que construye `clarify_step()` es un `Step` normal y corriente, solo que con tres callbacks rellenos:

| Dónde engancha | Cuándo se ejecuta | Qué hace |
|---|---|---|
| `Step.when` | Antes de entrar en este paso | Si el brief ya existe y tiene las cuatro secciones, **se salta** el paso y lo inyecta en `ctx` |
| `Step.gate` | Al terminar el paso, antes de entregar el resultado abajo | Si las cuatro secciones no están completas, **no deja continuar**; si lo están, `write()` lo **congela** |
| `Step.reduce` | Tras pasar el gate | Pasa hacia abajo **las cuatro secciones parseadas**, no el texto original del modelo |

**Saltar también inyecta en `ctx`.** Este detalle se escapa fácil: cuando `when` devuelve `False`, `Workflow` no ejecuta el paso
y, por tanto, tampoco escribe `ctx[step.name]` — por eso `clarify_step` inyecta ahí mismo, dentro de `when`, el brief ya existente.
Si no, al volver a ejecutar los pasos de abajo se comerían un `KeyError`.

Lo que pasa `reduce` es `Brief.prompt_block()` y no el texto original del modelo, porque en el original puede colarse todo lo que haya escrito de más
(medido: pega el código entero dentro de la respuesta).

En la [continuidad](../reference/glossary.md#接续) este paso abre con otra frase — `CLARIFY_RESUME`:
«continúa aquella clarificación de requisitos que quedó a medias — **no empieces de cero**…». Sin esa frase,
la continuidad reenvía la petición original como si fuera una tarea nueva y el clarificador puede repetir preguntas ya hechas.

### Límite: el interrogatorio no entra en el contexto de abajo {#边界问答不进下游的上下文}

```text
Clarificar          sesión aislada  ────→  brief de 4 secciones congelado en disco
                                                     │
Trabajo (siguiente) sesión nueva (resume_from=None)◄──┘   solo recibe esas 4 secciones
```

El `resume_from` de `clarify_step` se queda en su valor por defecto `None`, así que el paso siguiente es una **sesión nueva** que solo recibe el brief.
Ese interrogatorio **nunca entró** en el contexto del [coordinador](../reference/glossary.md#协调者) —
no es que «entrara y luego se podara». La diferencia es sustancial: lo podado sigue estando en `sessions.db`
y puede volver con un resume; lo que nunca entró no tiene ese problema.

El interrogatorio en sí **se añade a `log_path`**. Esa copia no ocupa contexto, no le afecta la compactación y sigue ahí si cambias de máquina —
la misma idea que el workbench.

### Cada sección para en seco una clase de fallo {#四段各挡一类失败}

| Sección | Qué escribir | Qué pasa si falta |
|---|---|---|
| **目标** (objetivo) | Una frase: qué se hace y para quién | Sale otra cosa distinta |
| **验收标准** (criterios de aceptación) | Condiciones decidibles, una por línea. «Que quede bien» no vale; «ejecutar `x` produce `y`» sí | Nadie puede decidir si «está terminado» |
| **边界** (límites) | **Qué queda explícitamente fuera** | Deriva de alcance. Esta sección sujeta a **cada uno** de los subagents |
| **未知与假设** (incógnitas y supuestos) | Lo que no se llegó a preguntar, lo que caducó por timeout, lo que él mismo supuso; uno por línea | **Las premisas equivocadas quedan enterradas en silencio** |

La cuarta sección es el fusible de una ejecución long-horizon. Si cualquiera de las tres primeras está mal, mientras el supuesto figure explícito en la cuarta, quien lo lea después tiene ocasión de pararlo;
si queda enterrado, solo se descubre horas más tarde, cuando todo el resultado está para tirar. Las premisas equivocadas no se pueden evitar del todo, pero sí se pueden hacer **explícitas**.

Solo pasa con las cuatro secciones completas; qué falta lo reporta `Brief.missing()` — devuelve los nombres de sección en chino, listos para mostrar tal cual.

El parseo es muy tolerante con la forma: reconoce `## 目标` / `**目标**` / `目标:` / `3. 边界`, reconoce que el cuerpo venga pegado al título
(`目标: 做一个 X`), y reconoce los alias habituales (`验收条件`→验收标准、`不做什么`→边界、
`未知项与假设`→未知与假设); si una sección aparece varias veces, toma la primera con contenido. Hay dos excepciones que conviene saber:

- `Brief.parse()` **quita primero los bloques de código con vallas**, y si encuentra una valla **sin cerrar** descarta desde ahí todo lo que sigue.
  Cuando la salida del modelo viene truncada, las secciones posteriores no se parsean → faltan secciones → el `gate` lo devuelve.
- `Brief.load()` trata `"(未填)"` como vacío. Si al editar el brief a mano copias el texto de relleno de `to_markdown()`, esa sección sigue contando como ausente.

### Límite: qué puede tocar el clarificador {#边界确认者能碰什么}

Se ejecutó un clarificador **sin restricciones** (`/tmp/probe_ask.py`, **$0.8908 / 230 segundos**):
tras dos preguntas **se puso directamente a escribir código**; cuando los permisos lo pararon, **pegó el código entero en el cuerpo de la respuesta**.
Escribir «no escribas código» en el prompt no lo frena — en aquel momento su propio system prompt ya decía algo parecido. Por eso hay dos mecanismos:

**Uno: un hook le quita las herramientas de escritura.** La lista de preaprobación de `clarify()` es
`mcp__human__ask` más (cuando `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch`,
sin `Write` / `Edit` / `Bash` / `Agent`. Quien lo ejecuta de verdad es el `whitelist_guard` que `Runtime` instala automáticamente:
a partir de la lista de preaprobación deduce a la inversa cuáles de `Bash` / `Write` / `Edit` / `NotebookEdit` hay que bloquear,
y las que caen ahí reciben `deny`. No es que «se le pida no trabajar», es que **no puede** trabajar.

Darle lectura sale a cuenta: echar un vistazo al repositorio le ahorra varias preguntas, y esta sesión es de usar y tirar, así que da igual ensuciarla
(con `can_read=False` puedes quitarle también la lectura).

**Esto tiene que ser un hook, no basta con `allowed_tools`.** Eso último es una **lista de preaprobación, no una lista blanca excluyente** —
el modelo puede seguir invocando herramientas que no están dentro. Dos pruebas medidas que siguen en pie:

- En [HT002](../cases/ht002.md), el [juez](../reference/glossary.md#判定者) del paso «fijar el objetivo»
  ejecutó de hecho **11 veces `Bash`**, cuando `judge()` tiene `can_run=False` por defecto y `Bash` ni siquiera aparece en la lista
  (aquella ejecución todavía no tenía este hook — hoy esa misma llamada recibiría un `deny` de `whitelist_guard` en el acto,
  lo que precisamente demuestra que quien lo para es el hook y no la lista).
- **Sonda de $0.1**: a un agent con `allowed_tools=["Read"]` se le pide escribir un fichero —
  `Write` lo rechaza la capa de permisos (`"requested permissions to write ... but you haven't granted it yet"`),
  `Bash` lo rechaza la seguridad de rutas (`"Output redirection was blocked. For security, Claude Code may
  only write to files in the allowed working directories"`). **La llamada salió**;
  la pararon otras capas.

`clarify()` no fija explícitamente `permission_mode`, hereda el `"default"` del `AgentSpec`.
`coordinator()` usa por defecto `"acceptEdits"` — si alguien pasa ese valor al clarificador, esa protección desaparece.

**Dos: el framework solo parsea esas cuatro secciones y tira todo lo demás.** `Brief.parse()` extrae primero los bloques de código con vallas y luego busca los títulos —
aunque pegue código, no llega abajo. Esta es la última compuerta contra «que contamine los pasos siguientes».

### Límite: el canal de preguntas {#边界提问通道}

La herramienta de preguntar, del lado del modelo, se llama `mcp__human__ask` (parámetro `question`, `options` opcional).
`HumanChannel` es un servidor MCP en proceso y **registra dos herramientas** —
`mcp__human__ask` y `mcp__human__inbox`; en la lista de preaprobación del clarificador solo está la primera
(la bandeja de entrada es para el coordinador).

```python
HumanChannel(
    on_event=None,        # callback para UI de tipo push. Al engancharlo a un Workflow lo conecta Workflow.run automáticamente
    max_asks=None,        # sin límite de preguntas por defecto
    timeout_s=1800.0,     # 30 minutos. None = esperar siempre; <= 0 = totalmente automático
    log_path=None,        # el interrogatorio se añade a este fichero, no ocupa contexto
    amend_path=None,      # lo que la persona diga durante la ejecución se añade a este fichero (normalmente el propio brief)
    over_budget_text=..., timeout_text=..., declined_text=...,   # las tres redacciones para cuando la pregunta queda sin respuesta
)
```

Lo normal en un agent long-horizon es que **no haya nadie mirando**, así que «pararse a esperar a alguien» tiene que fallar con elegancia:

| Ajuste | Comportamiento |
|---|---|
| `timeout_s=1800.0` (por defecto) | Espera media hora; al vencer devuelve una explicación, **no un error** |
| `timeout_s=None` | Espera para siempre. Úsalo solo si sabes que hay alguien delante (la CLI no puede dar este valor: `--timeout` es un float) |
| `timeout_s=0` (o negativo) | **Totalmente automático**: todas las preguntas quedan sin respuesta al instante, sin fingir que espera |
| `max_asks=None` (por defecto) | **Sin límite** — cuántas veces preguntar lo decide el propio clarificador |
| `max_asks=N` | Cupo duro. Las preguntas que lo excedan reciben **un rechazo directo** de la herramienta, sin bloquear ni dar error |
| `max_asks=0` | Prohibido preguntar (CI / sin supervisión) |

Con `max_asks=None`, `remaining` devuelve `-1` (ni 0 ni infinito), y por eso el terminal no muestra «quedan N preguntas».

El texto literal que devuelve un timeout es:

> Nadie ha contestado. Continúa según tu propio criterio y escribe esta pregunta y el supuesto que adoptes en la sección «未知与假设».
> No repitas la pregunta ni te detengas aquí.

Las tres formas de quedarse sin respuesta (timeout / cupo agotado / la persona salta la pregunta) apuntan todas a la misma acción: **escribir el supuesto en la cuarta sección**.
Por eso la cuarta sección sigue teniendo contenido sin supervisión, y por eso una ejecución long-horizon puede seguir adelante.
Escribir el cupo en el prompt es una sugerencia; **contarlo en el canal es la garantía**.

Un hecho de mecánica ya medido: dentro del handler de una herramienta MCP en proceso, hacer `await` sobre un future externo **no produce deadlock** —
mientras el handler está colgado el event loop sigue girando, y otra tarea o **incluso otro hilo** puede depositar la respuesta.
Así que `answer()` / `decline()` se pueden llamar directamente desde un backend web o desde el hilo de entrada de una TUI (por dentro pasa por
`loop.call_soon_threadsafe`); esto es el caso normal, no un caso límite. Las excepciones que lance el callback de UI se recogen en `ui_errors`
y **no interrumpen la ejecución** — que se caiga el frontend no debería llevarse por delante tres horas de trabajo. La lista completa de miembros está en la [API de Python](../reference/api.md).

!!! warning "Si `max_turns` es pequeño, «preguntar hasta que quede claro» es papel mojado"
    El `max_turns` de `clarify()` es `None` (sin límite) por defecto. **Cada pregunta es un turno** —
    ponerlo en 16 equivale a «como mucho una docena de preguntas», y además hace efecto **en silencio**: al otro lado el canal sigue con `max_asks=None`,
    diciendo «sin límite», y nadie ve quién lo estranguló. Para dejar las preguntas abiertas, `HumanChannel.max_asks`
    y `clarify(max_turns=...)` **tienen que quedarse los dos en `None`**.

### Dónde cae el brief: en el workbench que has enganchado {#确认书落在哪必须是挂上去的那个工作台}

El índice del workbench se inyecta en el system prompt, así que el coordinador sabe desde el principio dónde está el fichero de requisitos y, al repartir trabajo, basta con pasar la ruta hacia abajo:
no hace falta copiar el contenido dentro del [brief de tarea](../reference/glossary.md#任务书).

!!! warning "El índice solo llega al coordinador"
    Los subagents tienen su propio system prompt y **no heredan** ese trozo de nivel de sesión (medido: **$0.2461**,
    `tests/prelude_live.py`). O sea que es «el coordinador transmite la ruta», no «cada subagent lo sabe automáticamente».

La clave es **cuál** workbench. Solo hay una forma correcta: constrúyelo tú, engánchalo al `Workflow`,
y deja que el programa conductor entregue ese mismo objeto al `Runtime`.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← enganchado
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Dos formas equivocadas, ninguna de las cuales **da error**, así que hay que tener especial cuidado:

```python
# ✗ Componer la ruta a mano: es relativa al cwd del proceso, y el <run_dir>/workbench que crea
#   Runtime(workbench=True) es otro directorio. El brief se escribe en A y el índice inyectado escanea B —
#   la promesa de arriba falla en silencio.
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ Intentar sacarlo del Runtime hacia atrás: pasando por cli.py no se puede. Primero llama a main() para construir el Workflow
#   y solo después crea el Runtime —— para entonces brief_path ya está fijado.
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

Si escribes tu propio conductor (sin pasar por `cli.py`), crea primero el `Workbench` y entrega **el mismo objeto** a la vez a
`Workflow(workbench=wb)` y a `Runtime(workbench=wb)`. El punto 5 de `tests/trial_offline.py`
asserta directamente que «el brief aparece dentro de `prompt_block()`», y el punto 11 confirma que ese assert captura la regresión.

### Qué está verificado y qué no {#验证状态}

**Todo verde offline** (`tests/clarify.py`, **52 casos**, sin coste): las cinco semánticas del canal de preguntas (bloquear esperando respuesta /
cupo agotado / timeout sin respuesta / saltar / responder desde otro hilo), el parseo de las cuatro secciones (incluyendo una muestra con «me ha pegado código dentro»),
que el rol de `clarify()` **no tiene** herramientas de escritura, y los tres enganches de `clarify_step`.

**La ruta de la CLI funciona offline de punta a punta**: se precarga un brief completo → el primer paso se salta → el canal conecta automáticamente con el hilo de entrada estándar →
el brief se inyecta en `ctx` → salida limpia.

**No se ha probado contra la API real.** La sonda de $0.8908 sí fue una **petición real**, pero medía «qué hace un clarificador sin restricciones»,
no esta ruta actual.

## Cuándo no usarlo {#什么时候不该用它}

**Cuando el requisito ya está congelado.** El requisito está escrito en un fichero, lo fija un sistema de arriba, o esta vez se trata de repetir lo mismo —
entonces no hay nada que preguntar. Mete el texto del requisito directamente en el paso de trabajo, o deja el `clarify_step` y que su `when` lo salte
(si el brief está, ya no pregunta).

**Cuando no hay a quién preguntar y no quieres que adivine.** Con `timeout_s=0` todas las preguntas quedan sin respuesta al instante
y la cuarta sección se llena de supuestos suyos — está diseñado así, pero la fiabilidad de ese brief es exactamente la de esos supuestos.
En CI es más limpio `max_asks=0` (prohibido preguntar) y dar el requisito completo desde fuera.

**Trabajos pequeños de una sola vez.** El paso de clarificar cuesta dinero: en [HT002](../cases/ht002.md),
para algo como «clonar un repositorio, instalarlo y hacerlo arrancar en macOS», clarificar el requisito costó **$0.5306 / 9 turnos / 0.10h**.
Cuanto más pequeño es el trabajo, peor pinta esa proporción. La ruta de un solo agent, `flower once`, no lleva este paso.

**Al cambiar el requisito no hay que volver a dialogar.** El brief es una pieza congelada: desde el momento en que cae a disco, el requisito es el fichero —
lo correcto es **editar ese fichero**. `--clarify-only` sobre un directorio ya clarificado es una **no-op**
(ese workflow solo tiene ese paso, y ese paso se salta); para reclarificar hay que añadir `--new`,
o poner `always_ask=True` si lo cableas tú.

**No decide si «está terminado».** Eso es otra capa, ver [guardián de objetivo](goal.md). La clarificación previa para
«lo que sale no es lo que se quería», no para «dice que ha terminado y en realidad no».
