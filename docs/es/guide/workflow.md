# Diseñar un flujo

El framework solo se ocupa del mecanismo: cómo se ejecuta un paso, cómo se enlazan las sesiones,
qué hacer cuando algo falla, cómo ahorrar contexto.
**El [flujo](../reference/glossary.md#流程) lo escribes tú** —— el framework no sabe en qué proyecto
trabajas ni en qué lenguaje, y tampoco debería saberlo. Esta página trata de cómo diseñar un flujo;
la tabla completa de campos de `Step` y `Workflow` está en la [API de Python](../reference/api.md).

## Qué problema resuelve {#解决什么问题}

Una ejecución de [largo horizonte](../reference/glossary.md#长程) no cabe en un solo prompt: primero
aclarar los requisitos, luego investigar, luego implementar, luego revisar; cada tramo tiene su propio
rol, su propio contexto y sus propios criterios de aceptación.
Si lo metes todo en una sola frase de prompt, el modelo decide por su cuenta qué tramo se salta;
si lo escribes como flujo, **el orden, las condiciones de salida y el paso de estado se convierten en
código Python** —— legible, testeable, y puedes reejecutar solo el paso que se rompió.

`Workflow` hace únicamente tres cosas:

- ejecutar en orden una serie de [pasos](../reference/glossary.md#步骤)
- decidir qué ve cada paso de lo anterior (tres formas de enlazar sesiones + un diccionario `ctx`)
- decidir cuándo reintentar y cuándo salir antes de tiempo

No contiene ninguna suposición de dominio. Dónde cortar, qué se acepta en cada paso, qué hacer cuando
no pasa —— esas cuatro cosas son «diseñar un flujo».

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
        # Sesión nueva: solo consume lo que le pasas en el prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Otra sesión nueva: inyecta en el prompt la salida del paso anterior (barato, evita contaminación)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

El argumento de `flower run` es `模块:属性` o `文件路径:属性`. Si el objeto obtenido es invocable se
llama una vez primero, se toma el `Workflow` y se ejecuta; al terminar, la terminal imprime el coste
total y la ruta del manifiesto de ejecución.

También puedes escribir tu propio programa controlador; el primer argumento de `Workflow.run` es un
`Runtime`:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## Qué hace realmente {#它实际做了什么}

### Qué recibe un Step y qué debe devolver {#一个-step-收到什么必须返回什么}

`Step` no es una función, es una **declaración**. Lo que se ejecuta de verdad es
`Runtime.run(step.spec, 渲染出来的 prompt, ...)` ——
**un paso = una llamada a `Runtime.run` = una [sesión](../reference/glossary.md#会话)**.

Los tres primeros campos son posicionales, `Step(name, spec, prompt)`:

- `name` —— nombre del paso. Es a la vez la clave en `ctx`, el nombre de la fila en
  `runs/manifest.json` y la clave del [linaje](../reference/glossary.md#血缘) entre procesos.
- `spec` —— con qué `AgentSpec` se ejecuta. Determina la lista blanca de herramientas, el modelo y el
  presupuesto de ese paso.
- `prompt` —— un `str`, o bien `(ctx) -> str`. Si es invocable recibe el `ctx` actual;
  **es la forma más barata de alimentar la salida del paso anterior** (la otra es enlazar sesiones,
  ver abajo).

Lo que ese paso «devuelve» es un `StepResult`, pero dentro del flujo lo que tú recibes son dos cosas:

- `ctx[step.name]` —— por defecto `result.text`; si diste un `reduce`, el valor que devuelva `reduce`;
- `ctx["_results"][step.name]` —— el `StepResult` completo (coste, turnos, número de intentos,
  `session_id`).

`result.text` **solo recoge el cuerpo del hilo principal**: lo que dice un subagent queda en su propia
transcripción, el [encargo de tarea](../reference/glossary.md#任务书) que se le asigna es
`kind="prompt"`, y el error sintético de una desconexión es `kind="error"` —— ninguno de los tres entra.

### reduce: no es azúcar sintáctico {#reduce不是糖}

Por defecto, lo que se pasa hacia abajo son las palabras textuales del modelo. Hay pasos cuyas palabras
textuales **no deben** pasarse tal cual:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

En la práctica, el paso de aclaración de requisitos **pega el código entero** además de las cuatro
secciones. Lo que se pasa aguas abajo tiene que ser las cuatro secciones ya parseadas; si no, todo ese
código acaba en el prompt del paso siguiente. `clarify_step` se sostiene precisamente sobre este campo.

`reduce` **debe ser una función síncrona**; `gate` / `when` / `on_reject` sí pueden ser async.

### Cómo fluye el estado por ctx {#状态怎么在-ctx-里流动}

`ctx` es un `dict[str, Any]`, es el propio `Workflow.context`. Al terminar cada paso se escribe según
esta tabla:

| Situación | `ctx[步骤名]` | Lo demás |
|---|---|---|
| `when(ctx)` devuelve False | **no se escribe**, el paso entero se salta | no genera result, tampoco entra en `_results` |
| Pasa | `reduce(result, ctx)`; si no se dio, `result.text` | |
| Falla + `on_fail="stop"` (por defecto) | **no se escribe** | escribe `ctx["_failed_at"]`, el flujo entero se detiene en ese paso |
| Falla + `on_fail="skip"` | **no se escribe** | continúa hacia abajo |
| Falla + `on_fail="continue"` | `result.text` (incompleto, **sin pasar por `reduce`**) | continúa hacia abajo |

Pase o no, `ctx["_results"][步骤名]` siempre se escribe; si `result.session_id` no está vacío, además se
escribe en `ctx["_sessions"]` y se registra en el linaje.

**Para saber si esta ejecución del flujo tuvo éxito, mira `ctx.get("_failed_at")`**, no si el último
paso produjo salida.

Todas las claves que empiezan por guion bajo las pone el propio `Workflow.run`: `_runtime`,
`_on_event`, `_sessions`, `_results`, `_lineage`, `_woke`, `_aborted`, `_failed_at`; no las uses como
nombres de tus pasos. Cada mecanismo pone además las suyas (`_brief` / `_goal` / `_verdict`, etc.);
la lista completa está en la [API de Python](../reference/api.md).

De ellas, `_runtime` y `_on_event` son para el `gate`: un gate puede lanzar por su cuenta un agente que
emita el veredicto, y ese proceso sigue llegando a la UI —— si no, esos diez y pico segundos con la
interfaz en negro parecen un cuelgue.
El [guardián de objetivo](goal.md) está implementado justo así.

`ctx` es el mismo dict: **si ejecutas dos veces el mismo objeto `Workflow`, las claves de la primera
vez siguen ahí**. Para empezar limpio, crea uno nuevo o pasa explícitamente `context={}`.

!!! warning "Con on_fail=skip no se escribe `ctx[步骤名]`"
    Si aguas abajo escribes `lambda ctx: ctx["某步"]` obtendrás un `KeyError` directo. Para seguir
    adelante con un resultado incompleto, usa `on_fail="continue"`; si de verdad quieres saltar el
    paso, los pasos siguientes tienen que protegerse con `ctx.get(...)`.

### Veredicto y devolución: gate, on_reject, StepAbort {#判定与打回gateon_rejectstepabort}

`gate(result, ctx) -> bool` juzga «terminó, pero ¿es aceptable?». Dos detalles que hay que conocer:

- **Si `result.ok` es falso, `gate` no se llama en absoluto** (cortocircuito).
- **Se llama una sola vez por intento** y la conclusión se guarda para después —— puede tener efectos
  secundarios. El gate de `clarify_step` vuelca a disco el [brief](../reference/glossary.md#需求确认书);
  dispararlo de nuevo vuelve a escribir en disco.

Cómo se reintenta después de no pasar el gate depende de si diste `on_reject`:

| | Cómo se ejecuta la ronda siguiente | Nombre en el manifest |
|---|---|---|
| Solo `retries` | Se reejecuta desde cero, con el prompt original y el `resume_from` original | `X#retry1` |
| Con `on_reject` | **Se reanuda la sesión que acaba de ser rechazada**, el prompt pasa a ser el valor devuelto por `on_reject`, `fork` se fuerza a False | `X#round2` |

La segunda es «te lo devuelvo, te digo qué falta, sigue completándolo» —— el trabajo ya hecho y el
contexto siguen ahí.
Si `on_reject` devuelve cadena vacía, o si ese intento nunca obtuvo un `session_id`, degrada a
reejecutar desde cero.

El `gate` también puede lanzar `StepAbort`, que significa **reintentar no sirve de nada, no gastes los
turnos restantes**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

Tras lanzarlo: el motivo se registra en `ctx["_aborted"]`, el paso se trata como fallido y sigue
`on_fail` (por defecto `"stop"`), **el bucle de reintentos hace break en el acto** y no se consume ni
uno de los `retries` restantes.

Ten clara la diferencia: **devolver False es «esta vez no, otra ronda»; `StepAbort` es «otra ronda
tampoco sirve»**.
El caso típico es que se dictamine que el objetivo no es alcanzable en este entorno y no haya a quién
preguntar —— seguir girando en vacío es la opción más cara.

### No confundas las dos capas de reintento {#两层重试别混}

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| Qué cubre | Fallos de negocio: el `gate` no pasa, `result.ok` es falso | Infraestructura: red inestable, caída de red, 5xx |
| Cómo reintenta | **Reejecuta el paso entero**, con el mismo prompt y el mismo `resume_from` | **Reanuda desde el punto de corte**, el coste anterior no se pierde |
| Qué hace antes | Nada | Sondas DNS + TCP esperando a que vuelva la red (sin HTTP, sin credenciales; la sonda tiene que ser gratis) |
| Lo no reintentable | —— | Credenciales erróneas o parámetros erróneos paran de inmediato, sin esperar indefinidamente |

La frase de prompt con la que se reanuda **no incluye a propósito ningún detalle del error** —— el
modelo necesita saber «te interrumpieron, sigue», no si fue un ENOTFOUND o un 503.

### Encadenar los pasos {#把步骤串起来}

Hay tres formas de pasar estado entre pasos, y la que elijas determina qué ve el paso siguiente:

| Forma | Qué ve el paso siguiente | Dónde se usa |
|---|---|---|
| `resume_from=None` (por defecto) + inyección en el prompt | Solo el texto que hayas inyectado | Pasos independientes. Barato, evita contaminación |
| `resume_from="上一步名"` | El historial completo de la sesión | Cuando hace falta memoria continua |
| `resume_from="上一步名"` + `fork=True` | Historial completo, pero en una rama aparte | Revisión / varias alternativas en paralelo / reintentos que no ensucian la línea original |

El paso al que apunta `resume_from` **tiene que haber producido realmente una sesión**. Si fue saltado
por `when`, o si nunca se ejecutó, `Workflow.run` lanza directamente `ValueError` —— no degrada en
silencio a una sesión nueva, porque eso invalidaría calladamente la suposición de «memoria continua».

Unas cuantas lecciones de diseño pagadas a base de golpes:

1. **Un paso, un objetivo aceptable.** El límite del paso es el límite del contexto: donde pones
   `resume_from=None`, todos esos resultados de herramientas anteriores dejan de residir en contexto.
   Ver [economía del contexto](context.md).
2. **Si no estás seguro, empieza con `clarify_step`.** En largo horizonte, «entender mal el objetivo»
   es el error más caro, y es justamente el tipo de error que ninguna de las capas de ahorro de
   contexto puede limpiar. Ver [aclaración previa](clarify.md).
3. **El trabajo que delegas debe ser autosuficiente.** El subagent parte de contexto limpio, no sabe lo
   que sabe el [coordinador](../reference/glossary.md#协调者). El contexto necesario va escrito en el
   encargo de tarea, o le dices qué artefacto leer.
4. **Las salidas largas van a disco, no al diálogo.** Esto ya está escrito en `WORKER_RULES`; que tus
   `instructions` no lo anulen («pégame el log completo para que lo vea»).
5. **En el `gate`, prioriza las condiciones duras.** Si el archivo existe o no, si el código de salida
   es 0: eso se decide con una línea de Python, no despachando un modelo. Si quieres que juzgue el
   modelo, usa el `with_goal` que ya existe —— sustituye el gate por una implementación que lanza un
   [juez](../reference/glossary.md#判定者) independiente; no te fabriques uno a mano dentro del gate.
6. **Si en paralelo se modifica el mismo repositorio, usa `worker(isolate=True)`.** El cierre (fusionar,
   limpiar el worktree, abrir el PR) hoy por hoy queda en manos de tu flujo; el harness solo garantiza
   que los cambios caen en el worktree de cada uno.

### El banco de trabajo se cuelga del Workflow {#工作台要挂在-workflow-上}

Siempre que el flujo tenga que escribir archivos en el
[banco de trabajo](../reference/glossary.md#工作台) —— el caso típico es
`clarify_step(brief_path=...)` —— tienes que crear tú un `Workbench` y colgarlo **a la vez** de
`Workflow.workbench` y del `Runtime`:

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

Colgar `channel` del workflow tiene dos razones: `run()` engancha su `on_event` a la misma salida de
eventos (solo si `channel.on_event` sigue siendo `None`), y el programa controlador se apoya en ese
campo para saber a quién responder.

!!! warning "Componer la ruta del banco de trabajo a mano falla en silencio"
    La posición por defecto de `Runtime(workbench=True)` es `<run_dir>/workbench`, mientras que la de
    `Workbench(ws)` es `<ws>/.flower` —— **no son el mismo directorio**. Cuando la CLI invoca el flujo,
    este no ve `run_dir`, así que componer la ruta a mano solo la compone en otro sitio: el brief se
    escribe en el directorio A y el índice inyectado escanea el directorio B, **y no salta ningún
    error**. Si creas un único objeto y lo compartes en ambos lados, el problema no existe; cuando
    `Workflow.workbench` está presente, el `-W` de la línea de comandos se ignora y manda él.

### `continuous=True`: volver a ejecutar la misma ruta {#continuoustrue同一个路径再跑一次}

Las tres formas de enlazar de arriba hablan de paso a paso **dentro de una misma ejecución**. Entre
procesos hay otro eje:

```python
Workflow([...], continuous=True)     # valor por defecto
```

Si ejecutas otra vez sobre el mismo espacio de trabajo, cada paso continúa hablando en la sesión de la
vez anterior —— gracias al mapa «nombre de paso → session_id» de `<run_dir>/lineage.json`. Al cargarlo,
cada registro pasa por `runtime.has_session()` para verificar que la sesión sigue en la base; solo se
usa si está viva: el archivo de linaje puede sobrevivir a `sessions.db`, y reanudar una sesión
inexistente no revienta hasta que arranca el subproceso.

Tres consecuencias:

- **`resume_from=None` no equivale a «sesión totalmente nueva».** La primera ejecución sí, la segunda
  no. Si quieres sesión nueva siempre, escribe explícitamente `Workflow(..., continuous=False)`.
- **Con [continuidad](../reference/glossary.md#接续) el contexto crece sin parar.** Si al continuar
  quieres decir otra cosa, usa `Step.resume_prompt` —— lo que ya está en el contexto del interlocutor no
  debería reenviarse.
- Los pasos que declaran explícitamente `resume_from` no se ven afectados: ese tiene prioridad.

!!! warning "El nombre del paso es la clave entre procesos"
    Cambiar el nombre de un paso equivale a cortar su linaje: la próxima vez ya no continúa, y **no
    salta ningún error**. Los nombres de reintento con sufijo `#retry1` / `#round2` **no entran en el
    linaje** (siempre se registra el nombre original), y esa es una de las formas en que se implementa
    que «el juez siempre sea una sesión nueva».

El diseño completo y `--new` están en [continuidad](continuity.md).

## Cuándo no usarlo {#什么时候不该用它}

- **Solo ejecutas un agente y no necesitas veredicto** —— no envuelvas nada en `Workflow`. Llama
  directamente a `await rt.run(spec, "…")`, o desde la línea de comandos
  `flower once "读一眼这个仓库"`.
- **La forma es exactamente «aclarar requisitos → fijar objetivo → trabajar»** —— usa el
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py) que ya
  existe, no lo escribas tú:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    Son **tres pasos**: `确认需求` → `设定目标` → `干活` (con bucle de veredicto; el paso de veredicto
    se llama `干活·判定#N`). Con `goal=False` no hay segundo paso ni bucle de veredicto; con
    `clarify_only=True` solo queda el primero.
    Trae su propio `HumanChannel` y su propio `Workbench` colgados del workflow, así que
    `Runtime(workbench=wf.workbench)` se usa tal cual, no montes otro aparte.

    Tampoco hace falta escribir código: dentro del directorio del proyecto,
    `flower "帮我做一个 X"` ejecuta justamente eso.
    **No es «el diseño de flujo recomendado»**, solo es lo que te permite arrancar con cero
    configuración.

- **Cortas los pasos más fino que «un objetivo aceptable»** —— pérdida neta. Cada paso abre una sesión
  nueva, y una sesión nueva tiene un suelo de arranque (medido en el coordinador: unos 34k de
  contexto) que no se amortiza.
- **Quieres retroceder a posteriori a un mensaje concreto** —— por la vía de `Workflow` no se puede,
  nunca pasa `resume_at`. Llama directamente a
  `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)`.

Cómo elegir el rol (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) y la semántica campo a
campo de `Step` y `Workflow` están en la [API de Python](../reference/api.md); los términos, en el
[glosario](../reference/glossary.md).
