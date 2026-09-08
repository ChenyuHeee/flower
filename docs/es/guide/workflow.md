# Diseñar un workflow

El framework solo se ocupa del mecanismo: cómo corre un step, cómo se enlaza la sesión, qué pasa cuando algo falla, cómo ahorrar contexto.
**El [workflow](../reference/glossary.md#流程) lo escribes tú** —— el framework no sabe en qué proyecto trabajas ni en qué lenguaje,
y tampoco debería saberlo. Esta página trata de cómo diseñar un workflow; la tabla completa de campos de
`Step` y `Workflow` está en [Python API](../reference/api.md).

## Qué problema resuelve {#解决什么问题}

Un run [long-horizon](../reference/glossary.md#长程) no es algo que se despache con un solo prompt: primero se aclara el requisito,
luego se investiga, luego se implementa, luego se revisa; cada tramo tiene su propio rol, su propio contexto y su propia condición de aceptación.
Si lo metes todo en un único prompt, el modelo decide por su cuenta qué tramo saltarse; si lo escribes como workflow, **el orden, las condiciones de salida y el paso de estado se convierten en
código Python** —— legible, testeable, y puedes volver a correr solo el step que se rompió.

`Workflow` hace únicamente tres cosas:

- correr una serie de [steps](../reference/glossary.md#步骤) en orden
- decidir qué ve cada step de lo anterior (tres formas de enlazar sesiones + un diccionario `ctx`)
- decidir cuándo reintentar y cuándo salir antes de tiempo

No contiene ninguna suposición de dominio. Dónde cortar, qué se acepta en cada step, qué hacer si no pasa —— esas cuatro cosas son "diseñar el workflow".

## Cómo se usa (código mínimo) {#怎么用最小代码}

```python
# flows.py
from flower import AgentSpec, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


def main() -> Workflow:
    return Workflow([
        # Sesión nueva: solo consume lo que le pasas por el prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Otra sesión nueva; inyecta la salida del step anterior en el prompt (barato, evita contaminación)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

El argumento de `flower run` es `módulo:atributo` o `ruta_de_archivo:atributo`. Si el objeto obtenido es invocable, se llama una vez;
con el `Workflow` resultante se corre. Al terminar, la terminal imprime el coste total y la ruta del run manifest.

También puedes escribir tu propio driver; el primer argumento de `Workflow.run` es un `Runtime`:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## Qué hace realmente {#它实际做了什么}

### Qué recibe un Step y qué tiene que devolver {#一个-step-收到什么必须返回什么}

`Step` no es una función, es una **declaración**. Lo que se ejecuta de verdad es `Runtime.run(step.spec, prompt renderizado, ...)` ——
**un step = una llamada a `Runtime.run` = una [sesión](../reference/glossary.md#会话)**.

Los tres primeros campos son posicionales, `Step(name, spec, prompt)`:

- `name` —— el nombre del step. Es a la vez la clave dentro de `ctx`, el nombre de la fila en `runs/manifest.json`
  y la clave del [linaje](../reference/glossary.md#血缘) entre procesos.
- `spec` —— con qué `AgentSpec` se corre. Determina la lista blanca de herramientas, el modelo y el presupuesto de este step.
- `prompt` —— `str`, o `(ctx) -> str`. Si es invocable recibe el `ctx` actual;
  **esta es la forma más barata de meterle la salida del step anterior** (la otra es enlazar la sesión, ver más abajo).

Lo que el step "devuelve" es un `StepResult`, pero dentro del workflow lo que tienes en la mano son dos cosas:

- `ctx[step.name]` —— por defecto es `result.text`; si diste `reduce`, es el valor de retorno de `reduce`;
- `ctx["_results"][step.name]` —— el `StepResult` completo (coste, turnos, número de intentos, `session_id`).

`result.text` **solo recoge el cuerpo del main thread**: lo que dice un subagent queda en su propio transcript, el
[task brief](../reference/glossary.md#任务书) que se le encarga es `kind="prompt"`, y el error sintético de una desconexión es `kind="error"`
—— ninguno de los tres entra.

### reduce: no es azúcar {#reduce不是糖}

Por defecto, lo que se pasa hacia abajo son las palabras textuales del modelo. Las palabras textuales de algunos steps **no** deberían pasarse tal cual:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

En la práctica, ese paso **pega el código entero** además de las cuatro secciones. Lo que se pasa aguas abajo tiene que ser las cuatro secciones ya parseadas;
si no, todo ese código entra en el prompt del siguiente step. `clarify_step` se sostiene precisamente con este campo.

`reduce` **tiene que ser una función síncrona**; `gate` / `when` / `on_reject` pueden ser async.

### Cómo fluye el estado por ctx {#状态怎么在-ctx-里流动}

`ctx` es un `dict[str, Any]`, es el propio `Workflow.context`. Cada step, al terminar, escribe según esta tabla:

| Caso | `ctx[nombre_del_paso]` | Lo demás |
|---|---|---|
| `when(ctx)` devuelve False | **no se escribe**, el step entero se salta | no produce result ni entra en `_results` |
| Pasa | `reduce(result, ctx)`, o `result.text` si no lo diste | |
| Falla + `on_fail="stop"` (por defecto) | **no se escribe** | escribe `ctx["_failed_at"]`, el workflow entero se detiene en este step |
| Falla + `on_fail="skip"` | **no se escribe** | sigue hacia abajo |
| Falla + `on_fail="continue"` | `result.text` (incompleto, **sin pasar por `reduce`**) | sigue hacia abajo |

Pase o no pase, `ctx["_results"][nombre_del_paso]` siempre se escribe; si `result.session_id` no está vacío, además se escribe en
`ctx["_sessions"]` y se registra en el linaje.

**Para saber si el workflow ha ido bien, mira `ctx.get("_failed_at")`**, no si el último step produjo salida.

Las claves que empiezan por guion bajo las pone `Workflow.run`: `_runtime`, `_on_event`, `_sessions`, `_results`,
`_lineage`, `_woke`, `_aborted`, `_failed_at`; no las uses como nombres de tus steps. Cada mecanismo además pone las suyas
(`_brief` / `_goal` / `_verdict`, etc.); la lista completa está en [Python API](../reference/api.md).

De esas, `_runtime` y `_on_event` son para el `gate`: un gate puede despachar por su cuenta un agent para emitir un verdict,
y ese proceso de verdict se sigue pintando en la UI —— si no, la interfaz se queda a oscuras esos diez y pico segundos y parece colgada.
El [goal guard](goal.md) está implementado justo así.

`ctx` es el mismo dict: **si corres el mismo objeto `Workflow` una segunda vez, las claves de la vez anterior siguen ahí**.
Para empezar limpio, crea uno nuevo o pasa explícitamente `context={}`.

!!! warning "Con on_fail=skip no se escribe `ctx[nombre_del_paso]`"
    Si aguas abajo escribes `lambda ctx: ctx["algún_paso"]` te llevas un `KeyError` directo. Para seguir adelante con el resultado incompleto usa
    `on_fail="continue"`; si de verdad quieres saltar, aguas abajo tendrás que cubrirte con `ctx.get(...)`.

### Verdict y devolución: gate, on_reject, StepAbort {#判定与打回gateon_rejectstepabort}

`gate(result, ctx) -> bool` juzga "terminó, pero ¿es aceptable?". Dos detalles imprescindibles:

- **Si `result.ok` es falso, `gate` ni siquiera se llama** (cortocircuito).
- **Se llama una sola vez por intento**, y la conclusión se guarda para después —— puede tener efectos secundarios. El gate de `clarify_step` hace spill
  del [brief](../reference/glossary.md#需求确认书) a disco, así que dispararlo repetidamente lo reescribe repetidamente.

Cómo se reintenta cuando el gate no pasa depende de si diste `on_reject`:

| | Cómo corre la siguiente ronda | Nombre en el manifest |
|---|---|---|
| Solo `retries` | Desde cero, con el prompt original y el `resume_from` original | `X#retry1` |
| Con `on_reject` | **Continúa la sesión que acaba de ser rechazada**, el prompt pasa a ser el valor de retorno de `on_reject`, `fork` forzado a False | `X#round2` |

La segunda opción es "te lo devuelvo, te digo qué falta, sigue completándolo" —— el trabajo ya hecho y el contexto siguen ahí.
Si `on_reject` devuelve cadena vacía, o si ese intento nunca llegó a obtener un `session_id`, degrada a correr desde cero.

`gate` también puede lanzar `StepAbort`, que significa **reintentar no sirve de nada, no gastes los turnos restantes**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

Tras lanzarlo: el motivo se registra en `ctx["_aborted"]`, el step se trata como fallo y pasa por `on_fail` (por defecto `"stop"`),
**el bucle de reintentos hace break en el acto**, y no se consume ni uno de los `retries` restantes.

Graba la diferencia: **devolver False es "esta vez no, otra ronda"; `StepAbort` es "otra ronda tampoco servirá".**
El caso típico es cuando se determina que el objetivo es imposible en este entorno y no hay a quién preguntar —— seguir girando en vacío es la opción más cara.

### No mezcles las dos capas de reintento {#两层重试别混}

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| De qué se ocupa | Fallos de negocio: el `gate` no pasa, `result.ok` es falso | Infraestructura: inestabilidad de red, caída de red, 5xx |
| Cómo reintenta | **El step entero desde cero**, mismo prompt y mismo `resume_from` | **Resume desde el punto de corte**, el coste anterior no se tira |
| Qué hace mientras tanto | Nada | Sondas DNS + TCP esperando a que vuelva la red (sin HTTP, sin credenciales; la sonda tiene que ser gratis) |
| No reintentables | —— | Credencial errónea o parámetro erróneo paran de inmediato, sin esperar en balde |

El prompt que se usa para continuar **deliberadamente no contiene ningún detalle del error** —— el modelo necesita saber "te interrumpieron, sigue",
no necesita saber si fue ENOTFOUND o 503.

### Encadenar los steps {#把步骤串起来}

Hay tres formas de pasar estado entre steps, y la que elijas determina qué ve el siguiente:

| Forma | Qué ve el siguiente step | Dónde se usa |
|---|---|---|
| `resume_from=None` (por defecto) + inyección en el prompt | Solo las palabras que inyectaste | Steps independientes. Barato, evita contaminación |
| `resume_from="nombre del step anterior"` | El historial completo de la sesión | Cuando hace falta memoria continua |
| `resume_from="nombre del step anterior"` + `fork=True` | El historial completo, pero abriendo otra rama | Revisión / varias alternativas en paralelo / reintentos que no ensucian la línea original |

El step al que apunta `resume_from` **tiene que haber producido realmente una sesión**. Si lo saltó un `when`, o si nunca llegó a correr,
`Workflow.run` lanza `ValueError` directamente —— no degrada en silencio a sesión nueva, porque eso haría que la suposición de "memoria continua"
dejara de cumplirse sin avisar.

Unas cuantas lecciones de diseño pagadas a base de golpes:

1. **Un step, un objetivo aceptable.** El límite del step es el límite del contexto: donde pones `resume_from=None`,
   todos esos resultados de herramientas anteriores dejan de residir ahí. Ver [Economía del contexto](context.md).
2. **Si dudas, empieza con `clarify_step`.** En long-horizon, "entendí mal el objetivo" es el error más caro,
   y es justamente del tipo que las capas de ahorro de contexto no pueden limpiar. Ver [clarify](clarify.md).
3. **La tarea que despachas tiene que ser autosuficiente.** El subagent tiene contexto limpio, no sabe lo que sabe el
   [coordinator](../reference/glossary.md#协调者). Mete el contexto necesario en el task brief, o dile qué artifact leer.
4. **Las salidas largas van a disco, no de vuelta en el mensaje.** Esto ya está escrito en `WORKER_RULES`; que tus `instructions` no lo
   anulen ("pégame el log completo aquí").
5. **El `gate` bloquea primero con condiciones duras.** Si el archivo existe o no, si el exit code es 0: eso se decide con una línea de Python, no despaches un modelo.
   Si de verdad hace falta que juzgue un modelo, usa el `with_goal` ya hecho —— sustituye el gate por una implementación que corre un
   [judge](../reference/glossary.md#判定者) independiente; no te fabriques uno a mano dentro del gate.
6. **Si hay paralelismo sobre el mismo repositorio, `worker(isolate=True)`.** El cierre (fusionar, limpiar el worktree, abrir el PR) queda de momento
   a cargo de tu propio workflow; el harness solo garantiza que los cambios caigan cada uno en su worktree.

### El workbench va colgado del Workflow {#工作台要挂在-workflow-上}

Siempre que el workflow tenga que escribir archivos en el [workbench](../reference/glossary.md#工作台) —— el caso típico es
`clarify_step(brief_path=...)` —— tienes que crear tú mismo un `Workbench` y colgarlo **a la vez** de `Workflow.workbench`
y pasárselo al `Runtime`:

```python
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=1800.0)

主控 = coordinator("协调者", "", {
    "coder": worker("写代码与测试。要动手实现的活派给它。",
                    "你负责实现。每改一处就跑一次验证,别攒到最后。"),
}, channel=ch)

wf = Workflow(
    [
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
    ],
    channel=ch,
    workbench=wb,
)

rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
```

Colgar `channel` del workflow tiene dos razones: `run()` conecta su `on_event` a la misma salida de eventos
(solo si `channel.on_event` sigue siendo `None`), y el driver se apoya en ese campo para saber a quién responder.

!!! warning "Componer la ruta del workbench a mano falla en silencio"
    La ubicación por defecto de `Runtime(workbench=True)` es `<run_dir>/workbench`, mientras que la de `Workbench(ws)` es
    `<ws>/.flower` —— **no son el mismo directorio**. Cuando la CLI invoca el workflow, este no ve `run_dir`, así que componer la ruta a mano
    solo la compone en otro sitio: el brief se escribe en el directorio A y el índice inyectado escanea el directorio B, **y no salta ningún error**.
    Crea un objeto y compártelo en ambos lados y el problema desaparece; cuando `Workflow.workbench` existe, el `-W` de la línea de comandos se ignora
    y manda este.

### `continuous=True`: correr otra vez por el mismo camino {#continuoustrue同一个路径再跑一次}

Las tres formas de enlazar de arriba hablan de step a step **dentro de un mismo run**. Entre procesos es otro eje:

```python
Workflow([...], continuous=True)     # valor por defecto
```

Si corres otra vez en el mismo workspace, cada step continúa hablando en la sesión de la vez anterior —— apoyándose en el mapa
«nombre de step → session_id» de `<run_dir>/lineage.json`. Al cargarlo, cada registro pasa por `runtime.has_session()` para verificar que la sesión sigue en la base,
y solo se usa si está viva: el archivo de linaje puede sobrevivir a `sessions.db`, y hacer resume de una sesión inexistente no revienta hasta que arranca el subproceso.

Tres consecuencias:

- **`resume_from=None` no equivale a "sesión totalmente nueva".** La primera vez sí, la segunda no. Si quieres sesión nueva siempre,
  escribe explícitamente `Workflow(..., continuous=False)`.
- **En la [continuidad](../reference/glossary.md#接续) el contexto crece sin parar.** Si al continuar quieres decir otra cosa, usa
  `Step.resume_prompt` —— lo que ya está en su contexto no debería reenviarse.
- Los steps con `resume_from` explícito no se ven afectados: ese tiene prioridad.

!!! warning "El nombre del step es la clave entre procesos"
    Cambiar el nombre de un step equivale a cortar el linaje de ese step: la próxima vez ya no continúa, y **no salta ningún error**. Los nombres de reintento con sufijo `#retry1` /
    `#round2` **no entran en el linaje** (siempre se registra el nombre original), y esta es también una de las formas en que se implementa "el judge siempre es una sesión nueva".

El diseño completo y `--new` están en [continuidad](continuity.md).

## Cuándo no deberías usarlo {#什么时候不该用它}

- **Solo corres un agent y no necesitas verdict** —— no envuelvas nada en `Workflow`. Llama directamente a `await rt.run(spec, "…")`,
  o desde la línea de comandos `flower once "读一眼这个仓库"`.
- **La forma es exactamente "aclarar el requisito → fijar el objetivo → trabajar"** —— usa el
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py) ya hecho,
  no lo escribas tú:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    Son **tres steps**: `确认需求` → `设定目标` → `干活` (con bucle de verdict; el step de verdict se llama `干活·判定#N`).
    Con `goal=False` no hay segundo step ni bucle de verdict; con `clarify_only=True` solo queda el primero.
    Trae su propio `HumanChannel` y su `Workbench` colgados del workflow, así que
    `Runtime(workbench=wf.workbench)` se usa tal cual; no montes otro aparte.

    Tampoco hace falta escribir código: entra en el directorio del proyecto y `flower "帮我做一个 X"` corre exactamente eso.
    **No es "el diseño de workflow recomendado"**, solo es lo que te permite arrancar con cero configuración.

- **Los steps están cortados más fino que "un objetivo aceptable"** —— pérdida neta. Cada step abre una sesión nueva,
  y una sesión nueva tiene un suelo de arranque (medido: unos 34k de contexto para el coordinator) que no se amortiza.
- **Quieres hacer rollback a un mensaje concreto a posteriori** —— por la vía de `Workflow` no se puede, nunca pasa `resume_at`.
  Llama directamente a `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)`.

Cómo elegir el rol (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) y la semántica campo por campo de `Step` y `Workflow`
están en [Python API](../reference/api.md); los términos, en el [glosario](../reference/glossary.md).
