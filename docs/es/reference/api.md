# API de Python

Esta página agota los **62 símbolos públicos** del `__all__` de nivel superior de `flower`: firmas, parámetros, valores por defecto, semántica, atributos y métodos públicos. Al terminar de leerla no hace falta volver a abrir el código fuente para buscar un parámetro.

La organización sigue **aquello que te interesa**, no los archivos de módulo: si quieres saber "cómo impedir que el [coordinador](glossary.md#协调者) se ponga a hacer las cosas él mismo", ve a la [capa de hooks](#hook); si quieres saber "cómo se pasa el resultado del paso anterior al siguiente", ve a [workflow](#流程). La terminología sigue siempre el [glosario](glossary.md).

Versión `0.1.0`, depende de `claude-agent-sdk>=0.2.152`. Todas las firmas corresponden literalmente al código fuente.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## Qué hay en esta página {#索引}

| Lo que te interesa | Símbolos |
|---|---|
| [Ejecutar un agente](#运行时) | `Runtime` `StepResult` |
| [Encadenar varios pasos](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Construir un rol](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Escribir a mano una definición de agente](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Documentos estructurados](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Interceptar herramientas, recortar resultados, aislar](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [El directorio de trabajo del spill](#工作台) | `Workbench` |
| [Cómo se guardan las sesiones y qué se guarda](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [Qué hacer si se cae la red](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Cambiar la UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Retomar la anterior entre procesos](#血缘) | `Lineage` |

## Seis valores por defecto que muerden {#危险默认值}

Estas seis no son detalles menores: son los seis vuelcos más frecuentes. Cada una tiene explicación completa en su sección correspondiente.

| Valor por defecto | Consecuencia | Detalle |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | Los `Bash`/`Write`/`Edit` del main thread **no tienen ni un solo hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Fuerza `CompactPolicy(mode="no_summary")` en el spec, es decir `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Un paso con `resume_from=None` seguirá retomando aquella sesión anterior entre procesos | [Workflow](#workflow) |
| `build_options(fork=True)` sin `resume` | Se ignora en silencio, sin error | [build_options](#build-options) |
| `clarify(max_turns=<número pequeño>)` | Convierte "preguntar sin límite de veces" en papel mojado: cada pregunta es un turno | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | Es a nivel de sesión: prohíbe también a los subagents | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Código fuente: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` es el núcleo de ejecución. Mantiene el workspace, el [session store](glossary.md#会话存储), el [workbench](glossary.md#工作台), la política de [resiliencia](glossary.md#韧性) y la política de [handoff](glossary.md#换代), y hacia fuera expone un solo verbo: `run` un paso. Los reintentos, la continuación tras una interrupción y el handoff cuando el contexto se llena ocurren todos dentro de esa misma llamada.

### `Runtime` {#runtime}

```python
Runtime(
    *,
    workspace: str | Path,
    run_dir: str | Path = "runs",
    portable: bool = True,
    trim: TrimPolicy | bool = False,
    ephemeral: EphemeralPolicy | bool = True,
    keep_denials: int = 1,
    workbench: Workbench | bool = False,
    spill_threshold: int | None = 4000,
    resilience: Resilience | bool = True,
    handoff: HandoffPolicy | bool = True,
)
```

Los parámetros del constructor son **todos keyword-only** (el `*` va al principio); `workspace` es obligatorio.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workspace` | `str \| Path` | obligatorio | El `cwd` del agente. Se resuelve en la construcción y se hace `mkdir(parents=True, exist_ok=True)`. El `project_key` del SDK se deriva de él: si te llevas el directorio a otro sitio, los `session_id` antiguos dejan de encontrarse |
| `run_dir` | `str \| Path` | `"runs"` | Alberga `sessions.db`, `manifest.json`, `lineage.json`, y el workbench por defecto cuando `workbench=True`. También se resuelve y se hace mkdir |
| `portable` | `bool` | `True` | Se pasa tal cual a `build_options(portable=)`, es decir `setting_sources=[]`: no lee el `~/.claude/` de la máquina anfitriona, ni el `.claude/` del proyecto. Véase [portable](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Si le das una instancia, se usa directamente; si le das un `bool`, se convierte en `TrimPolicy(enabled=bool(trim))`. **Desactivarlo solo significa no recortar resultados grandes; el prune se sigue haciendo** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Misma regla de conversión. Forma pareja con `coordinator(glance=True)`: si dejas que el main thread ejecute `git status`, tienes que garantizar que ese resultado caduque |
| `keep_denials` | `int` | `1` | Se pasa a `PrunePolicy(keep_denials=)`. Conserva las últimas N llamadas a herramientas rechazadas; las anteriores se retiran junto con su resultado |
| `workbench` | `Workbench \| bool` | `False` | Si le das una instancia, se usa directamente; si le das `True`, se crea `Workbench(workspace, home=run_dir / "workbench")` (**por defecto queda fuera del workspace**). Acto seguido se llama a `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | A partir de cuántos caracteres un resultado de herramienta hace [spill](glossary.md#落盘). `None` o `0` = no se instala `spill_guard` |
| `resilience` | `Resilience \| bool` | `True` | Misma regla de conversión |
| `handoff` | `HandoffPolicy \| bool` | `True` | Misma regla de conversión |

**El session store está fijado en el código**: siempre es
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Los parámetros del constructor **no ofrecen** ninguna vía para cambiar de backend: si quieres cambiarlo, construye tú mismo un `AgentSpec` + `build_options(session_store=...)`, o sobrescribe `rt.store` después de construirlo.

Los dos últimos pasos de la construcción son `load_dotenv()` y `check_credentials()`, y **este último lanza `RuntimeError` si algo falla**. Sin credenciales revienta en la fase de construcción, no al llegar a `run()`.

!!! warning "`workbench=False` + `coordinator()` = ni un muro en el main thread"
    `delegate_guard` solo se instala dentro de `workbench_hooks`, y `workbench_hooks` solo se llama cuando `self.workbench is not None`; y `whitelist_guard` se salta por el `if not spec.delegate_only`. Además `coordinator()` fija siempre `delegate_only=True` y por defecto `glance=True`, lo que le da `Bash`.

    **Conclusión: con un coordinador y `Runtime(workbench=False)`, sus `Bash`/`Write`/`Edit` no tienen ningún hook que los intercepte.**
    Si usas `coordinator()`, activa el workbench: `Runtime(..., workbench=True)` o pásale una instancia de `Workbench`.

!!! warning "`handoff=True` (por defecto) fuerza la desactivación del auto-compact"
    Dentro de `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`, lo que en el subproceso se traduce en `DISABLE_AUTO_COMPACT=1`. La razón es que con ambos mecanismos activos a la vez no se puede saber quién provocó una caída del contexto.

    **El precio: el paso que escribe el handoff debe tener una vía degradada** (`handoff.degraded`), porque ya no hay compact que haga de red.
    Si quieres conservar el auto-compact, indica explícitamente `AgentSpec.compact` (si el spec lo trae, se respeta y no se sobrescribe).

#### Atributos públicos {#runtime-属性}

| Atributo | Tipo | Descripción |
|---|---|---|
| `workspace` | `Path` | El workspace ya resuelto |
| `run_dir` | `Path` | El directorio de run ya resuelto |
| `portable` | `bool` | Se guarda tal cual |
| `store` | `PruningSessionStore` | El session store. Para cambiar de backend solo cabe sobrescribirlo tras la construcción |
| `resilience` | `Resilience` | La instancia ya normalizada |
| `handoff` | `HandoffPolicy` | La instancia ya normalizada |
| `workbench` | `Workbench \| None` | Es `None` cuando `workbench=False` |
| `spill_threshold` | `int \| None` | Se guarda tal cual; en `_attempt` se pasa a `workbench_hooks` |
| `results` | `list[StepResult]` | Cada paso ejecutado en este proceso, añadido en orden |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Debe ser único por instancia**: `manifest.json` deduplica por el campo `run`, y si dos id colisionan, el que escriba después borrará las filas del otro creyendo que son las suyas anteriores |
| `on_session` | `Callable[[str], None] \| None` | Callback **inmediato** al obtener un nuevo `session_id`, `None` por defecto. **Solo debe envolver la línea de `runtime.run`**: si el [juez](glossary.md#判定者) usa el mismo `Runtime` y el callback sigue puesto durante el gate, la sesión del juez acabará escrita en el [linaje](glossary.md#血缘) del paso que hacía el trabajo |

Constantes de clase: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`, `INTERRUPT_NOTE` (el fragmento que se añade tras las palabras de la persona al continuar de una interrupción, explicando que "que las llamadas a herramientas en vuelo devuelvan interrupted es un efecto secundario normal de la interrupción, no un fallo del entorno").

#### Métodos públicos {#runtime-方法}

| Método | Firma | Descripción |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Ejecuta un paso. Véase abajo |
| `interrupt` | `(message: str = "") -> None` | Solicita interrumpir el turno actual. **Invocable desde cualquier hilo**. Es cooperativo: corta limpiamente en un **límite de mensaje**, no cancela por la fuerza. Cadena vacía = interrumpir sin decir nada |
| `rescue` | `() -> None` | Antes de que te maten a la fuerza, intenta dejar las cuentas completas; lo llaman los manejadores de `SIGHUP`/`SIGTERM`. El paso en vuelo también se escribe en el manifest, con `error="killed-by-signal"`. Solo hace pequeñas escrituras síncronas |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | En `str(workspace.resolve())`, todos los `/`, `_` y `.` se sustituyen por `-`. **El SDK lo deriva del cwd; quien llama no puede especificarlo** |
| `has_session` | `(session_id: str) -> bool` | ¿Se encuentra todavía este id bajo **este workspace**? Síncrono, no lee el payload |
| `context_of` | `(session_id: str) -> int` | El tamaño de contexto del último turno de una sesión; delega en `store.last_context` |
| `total_cost` | `() -> float` | `round(sum(r.cost_usd for r in self.results), 4)` |
| `close` | `() -> None` | `self.store.close()` |

#### `Runtime.run(...)` {#runtime-run}

```python
async def run(
    self,
    spec: AgentSpec,
    prompt: str,
    *,
    step_name: str | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> StepResult
```

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `spec` | `AgentSpec` | obligatorio, posicional | La declaración del agente a ejecutar |
| `prompt` | `str` | obligatorio, posicional | Lo que se dice en este turno |
| `step_name` | `str \| None` | `None` | La clave que aparece en `StepResult.step`, en el manifest y en el linaje. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Continuar este `session_id` |
| `fork` | `bool` | `False` | Bifurcar a una sesión nueva sin contaminar la original. **Solo surte efecto si `resume` es verdadero** |
| `resume_at` | `str \| None` | `None` | Continuar desde un mensaje concreto (rollback). También **solo surte efecto si `resume` es verdadero** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Salida de eventos, véase [`Event`](#event) |

Al principio de cada paso se pone a cero el nivel de contexto (`self._ctx, self._warned = 0, False`). Después viene un bucle con cuatro salidas:

1. **Éxito** → sale.
2. **Interrupción humana** (`result.error == INTERRUPTED`) → **no está sujeta a `max_attempts`**, no espera a la red. Hace `resume` de la misma sesión con las palabras de la persona, `attempt -= 1` (una interrupción no cuenta como intento fallido), y el prompt = las palabras de la persona + `INTERRUPT_NOTE`. **Si no se obtuvo `session_id`, no queda más que parar**.
3. **Contexto lleno** (`result.error == HANDOFF_DUE`, o `handoff.enabled` y se obtuvo `session_id` y `is_overflow(...)` da positivo) → **tampoco está sujeto a `max_attempts`**. Primero comprueba `len(result.retired) >= handoff.max_generations`; si se ha pasado, sustituye el error por un diagnóstico y sale; si no, escribe el [documento de handoff](glossary.md#交接书) → `resume=None, fork=False` (**sesión completamente nueva**) → el prompt pasa a ser `h.prompt_block()` → se pone a cero el nivel → `attempt -= 1`.
4. **Fallo reintentable** → si `not resilience.enabled or attempt >= max_attempts`, sale; si `classify(error)` determina que no debe reintentarse, también sale; en caso contrario emite `Event("retry")`, se queda esperando la red con `wait_online()` y hace `sleep(delay_for(attempt))`; **si en algún momento se obtuvo un `session_id`, continúa con `resume`** (el prompt pasa a ser `resilience.resume_prompt`) y pone `result.resumed` a `True`.

Cierre: escribe `ended_at`, añade a `self.results` y escribe `manifest.json`.

`manifest.json` tiene semántica de **append**: cada escritura releé el disco y deduplica por el campo `run` (renueva sus propias filas, deja las ajenas), por lo que ejecutar dos flower en paralelo bajo el mismo `run_dir` es seguro, siempre que los `run_id` no colisionen.

**Los tres puntos de observación del handoff** (todos `Event("handoff")`, distinguidos por `payload["phase"]`): `near` (acercándose a `warn_at`, se emite una sola vez por generación), `writing` (se está escribiendo el handoff, tarda una decena de segundos), `done` (el payload trae `degraded` / `path` / `sections`). El turno que escribe el handoff se ejecuta con `replace(spec, max_budget_usd=None)`: el handoff tiene que poder escribirse, no puede quedarse atascado por el presupuesto; y con `on_event=None`, ese turno no se vuelca a la UI.

El handoff se escribe en `<workbench.notes>/交接-<步骤名>.md`; **sin workbench no hay escritura a disco**, el documento se sigue entregando al sucesor vía prompt, solo que después no podrás consultarlo. Los handoffs antiguos se mueven a `notes/archive/交接/<名>-<时间戳>.md`.

### `StepResult` {#stepresult}

```python
@dataclass
class StepResult:
    step: str
    session_id: str | None = None
    ok: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    text: str = ""
    error: str | None = None
    started_at: float = 0.0
    ended_at: float = 0.0
    attempts: int = 1
    errors: list[str] = field(default_factory=list)
    resumed: bool = False
    retired: list[str] = field(default_factory=list)
    context: int = 0
```

Todas las cuentas de un paso terminado.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `step` | `str` | obligatorio | Nombre del paso (`step_name` o `spec.name`) |
| `session_id` | `str \| None` | `None` | **Siempre la última sesión que tomó el relevo**: las quemadas por handoffs intermedios están en `retired` |
| `ok` | `bool` | `False` | Si el paso salió bien |
| `cost_usd` | `float` | `0.0` | En dólares. **Se acumula** a lo largo de reintentos y handoffs |
| `num_turns` | `int` | `0` | Número de turnos, también acumulado |
| `text` | `str` | `""` | **Solo contiene el cuerpo del main thread**. Lo que dice un subagent se queda en su propio transcript, y el task brief que se le asigna es `kind="prompt"`; ninguno de los dos entra aquí |
| `error` | `str \| None` | `None` | Motivo del fallo. Para valores especiales véase `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Marcas de tiempo Unix |
| `attempts` | `int` | `1` | Número real de intentos. Las interrupciones y los handoffs **no cuentan** |
| `errors` | `list[str]` | `[]` | Mensajes de error sintéticos de la API recogidos, **no entran en `text`** |
| `resumed` | `bool` | `False` | Si hubo algún resume por el camino |
| `retired` | `list[str]` | `[]` | Los `session_id` quemados por handoff en este paso, en orden |
| `context` | `int` | `0` | El tamaño de contexto que realmente vio el main thread en el último turno, es decir, el criterio de handoff |

| Propiedad | Tipo | Descripción |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`; `0.0` si no ha terminado |

---

## Workflow {#流程}

Código fuente: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Un [workflow](glossary.md#流程) es un conjunto de [pasos](glossary.md#步骤) encadenados en orden, más
cómo se pasa el estado entre pasos y cuándo salir antes de tiempo. **El framework no trae workflows
hechos; el workflow lo escribes tú** —— `starter_flow` es solo una plantilla que funciona.

Alias de tipo `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, está en `flower.workflow.__all__`,
no en el `__all__` de nivel superior).

### `Step` {#step}

```python
@dataclass
class Step:
    name: str
    spec: AgentSpec
    prompt: str | Callable[[Ctx], str]

    resume_from: str | None = None
    fork: bool = False

    retries: int = 0
    gate: Callable[[StepResult, Ctx], bool] | None = None
    on_fail: str = "stop"
    when: Callable[[Ctx], bool] | None = None
    on_reject: Callable[[StepResult, Ctx], str] | None = None
    resume_prompt: str | Callable[[Ctx], str] | None = None
    reduce: Callable[[StepResult, Ctx], str] | None = None
```

La **declaración** de un paso. `Step` en sí no es una función —— lo que realmente se ejecuta es
`Runtime.run(step.spec, prompt, ...)`. Los tres primeros campos son posicionales, así que
`Step("取词", terse, "读 seed.txt …")` es una escritura válida.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | obligatorio | Nombre del paso. **Clave estable entre procesos** —— aterriza en `ctx[name]`, `ctx["_results"]`, el manifest y el linaje. Renombrar = romper el linaje |
| `spec` | `AgentSpec` | obligatorio | Qué agent se ejecuta |
| `prompt` | `str \| Callable[[Ctx], str]` | obligatorio | Qué se dice. Puede ser un closure que calcula al vuelo con `ctx` |
| `resume_from` | `str \| None` | `None` | De qué paso se continúa la sesión. Si el paso apuntado no produjo sesión, **lanza `ValueError`**; no se salta en silencio |
| `fork` | `bool` | `False` | Bifurca a partir de `resume_from`. **Sin `resume_from` no tiene efecto** |
| `retries` | `int` | `0` | Cuántas veces reintentar como máximo cuando el gate no pasa. `retries=0` = una sola ronda |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Decide si esta vez cuenta como aprobado. **Puede ser async**. Devolver `False` se considera fallo. **Se invoca una sola vez por intento** —— puede tener efectos secundarios (por ejemplo escribir el brief en disco) y no debe dispararse repetidamente |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, ver abajo |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Si devuelve `False` **se salta el paso entero**: no produce result ni entra en `ctx["_results"]`. **Puede ser async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | **Qué decir en la siguiente ronda** cuando el gate no pasa. **Puede ser async**. Si lo defines, la semántica del reintento cambia; ver abajo |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt usado al continuar (en vez de empezar de cero) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Decide qué se guarda en `ctx[name]`. Por defecto el `result.text` literal. **Debe ser una función síncrona** |

| Método | Firma | Descripción |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Si `resuming` y hay `resume_prompt`, usa este último; si no, `prompt`; si es un callable, lo llama pasándole `ctx` |

**Tres formas de enganchar sesiones** (dentro de un mismo run):

| Forma | Efecto |
|---|---|
| `resume_from=None` (por defecto) | Sesión nueva, solo con el contexto que va en el prompt. Barato, aislado. **Pero con `Workflow(continuous=True)` toma la sesión del paso homónimo del linaje entre procesos** |
| `resume_from="上一步名"` | Continúa la misma sesión, contexto completo. Caro, coherente |
| `resume_from="上一步名", fork=True` | Bifurca sin contaminar la sesión original. Para revisión o varias alternativas en paralelo |

**`on_reject` cambia la semántica del reintento**:

- Sin definir → el siguiente intento **arranca de cero** (mismo prompt, mismo `resume_from`).
- Definido → el siguiente intento **continúa la sesión que acaba de ser rechazada**, con el prompt
  sustituido por su valor de retorno y `fork` forzado a `False`.
- Devuelve cadena vacía → no hay devolución; degrada a arrancar de cero.
- `result.session_id` es `None` → también degrada a arrancar de cero.

**Los tres valores de `on_fail`**:

| Valor | Comportamiento |
|---|---|
| `"stop"` (por defecto) | Escribe `ctx["_failed_at"] = name` e **interrumpe el workflow entero** |
| `"skip"` | Salta al siguiente paso, **sin escribir `ctx[name]`** —— un `lambda ctx: ctx["某步"]` aguas abajo dará `KeyError` |
| `"continue"` | `ctx[name] = result.text`, y sigue adelante con un resultado incompleto |

Pase o no pase, siempre se escribe `ctx["_results"][name] = result`; si `result.session_id` no está
vacío, además se escribe en `ctx["_sessions"]` y se llama a `lineage.remember(...)`.

### `Workflow` {#workflow}

```python
@dataclass
class Workflow:
    steps: list[Step]
    name: str = "workflow"
    context: Ctx = field(default_factory=dict)
    channel: Any = None
    workbench: Any = None
    continuous: bool = True

    async def run(
        self,
        runtime: Runtime,
        *,
        on_event: Callable[[Event], None] | None = None,
        on_step: Callable[[Step, StepResult], None] | None = None,
    ) -> Ctx
```

Ejecuta una serie de `Step` en orden y devuelve el `ctx` final. `steps` es posicional, así que
`Workflow([...])` es válido.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `steps` | `list[Step]` | obligatorio | Se ejecutan en orden |
| `name` | `str` | `"workflow"` | Nombre del workflow |
| `context` | `Ctx` | `{}` | Diccionario de contexto inicial. **Si ejecutas el mismo `Workflow` una segunda vez, el ctx es el mismo dict** |
| `channel` | `HumanChannel \| None` | `None` | Aquí se cuelga el canal para cuando haya que parar y preguntar a una persona. `run()` engancha automáticamente su `on_event` a la misma salida, **solo si `channel.on_event is None`**; el driver también usa este campo para saber a quién responder |
| `workbench` | `Workbench \| None` | `None` | Workbench designado por el workflow, para que el driver pueda encontrarlo |
| `continuous` | `bool` | `True` | Misma ruta = misma conversación. Se materializa en [`Lineage`](#lineage) |

| Parámetro de `run()` | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `runtime` | `Runtime` | obligatorio, posicional | Con qué runtime se ejecuta |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Salida de eventos, se propaga a cada `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Se invoca una vez al terminar cada paso |

!!! warning "`continuous=True` es el valor por defecto; `resume_from=None` no equivale a una sesión nueva"
    Con la continuidad activada, `run()` primero hace `Lineage.open(run_dir, workspace)` y después
    verifica cada registro con `runtime.has_session(sid)` para comprobar que sigue en el almacén;
    solo los vivos se cargan en `ctx["_sessions"]`. Por eso
    **incluso los pasos con `resume_from=None` siguen hablando en la sesión anterior** —— también si
    el proceso fue matado o la máquina reinició.

    Para que sea siempre una sesión nueva, escribe explícitamente `Workflow(..., continuous=False)`.
    Además: **el nombre del paso es una clave estable entre procesos; cambiarlo equivale a romper el linaje.**

**Claves privadas** que `run()` escribe en el ctx (todas empiezan por `_`, no chocan con nombres de pasos):

| Clave | Contenido |
|---|---|
| `_runtime` | El `Runtime` que se pasó. **Es lo que permite lanzar agents desde un gate** |
| `_on_event` | Salida de eventos. Ese agent dentro del gate también tiene que poder pintar en la UI; si no, la interfaz se queda a oscuras |
| `_sessions` | `dict[步骤名, session_id]`, se lee con `setdefault` |
| `_results` | `dict[步骤名, StepResult]` |
| `_lineage` | Objeto `Lineage`. Solo existe si `continuous=True` y el runtime tiene `run_dir` + `workspace` |
| `_woke` | Valor devuelto por `lineage.bump()`: qué número de despertar es este |
| `_aborted` | El mensaje del `StepAbort` |
| `_failed_at` | Nombre del paso que falló con `on_fail="stop"` |

Payload de `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Etiquetas de reintento**: el intento 0 usa `step.name`; después, con `on_reject` se usa
`f"{name}#round{attempt+1}"`, y sin él `f"{name}#retry{attempt}"`. En el manifest se ve de un vistazo
cómo se completó ese paso.
**Los nombres con sufijo no entran en el linaje entre procesos** —— `Lineage.remember` usa el nombre original.

`runtime.on_session` solo envuelve la línea de `runtime.run`, con `try/finally` para garantizar que
se retira antes del gate. `prompt_cur` / `resume_cur` / `fork_cur` son variables locales y no se
escriben de vuelta en `step` —— el mismo objeto `Step` puede ejecutarse una segunda vez.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Lanzarlo desde el `gate` = **parar de inmediato, no reintentar**. La diferencia con devolver `False`:
`False` es "esta vez no, otra ronda"; `StepAbort` es "otra ronda tampoco servirá".

Al lanzarse: `ctx["_aborted"] = str(exc)`, `passed = False`, **se sale del bucle de reintentos (sin
consumir los `retries` restantes)** y luego se aplica `on_fail` como en un fallo normal (por defecto `"stop"`).

`with_goal` lo lanza en dos sitios: cuando no consigue `ctx["_runtime"]`, y cuando el veredicto es
`unreachable` y nadie responde.

### `clarify_step()` {#clarify-step}

```python
def clarify_step(
    channel: HumanChannel,
    *,
    brief_path: str | Path,
    prompt: str | Callable[[Ctx], str],
    name: str = "确认需求",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_ask: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw,
) -> Step
```

Produce un `Step` que hace la [clarificación previa](glossary.md#前置确认): preguntar hasta tener claros
los requisitos → parsear a [`Brief`](#brief) → si las cuatro secciones están completas, congelarlo y
escribirlo en disco.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `channel` | `HumanChannel` | obligatorio, posicional | Canal de preguntas |
| `brief_path` | `str \| Path` | obligatorio | Dónde aterriza el [brief](glossary.md#需求确认书). **Tiene que caer en el workbench que realmente se inyecta en el índice** |
| `prompt` | `str \| Callable[[Ctx], str]` | obligatorio | La petición original de la persona |
| `name` | `str` | `"确认需求"` | Nombre del paso, y a la vez clave en `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Si no se da, usa `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instrucciones adicionales para el [clarificador](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = preguntar de nuevo siempre, exista o no el brief |
| `on_fail` | `str` | `"stop"` | Igual que `Step.on_fail` |
| `retries` | `int` | `0` | Cuántas veces volver a preguntar si no se completan las cuatro secciones |
| `**spec_kw` | | | Se propaga directamente a [`clarify()`](#clarify-role), así que puedes escribir `can_read=False`, `max_budget_usd=...` |

Los campos del `Step` resultante se rellenan así:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: con `always_ask=True` → siempre `True`; si no, si `Brief.load(brief_path)` está completo lo
  carga en el ctx **y luego devuelve `False` (salta)** —— aunque salte hay que cargarlo, o aguas abajo
  nadie tendrá los requisitos.
- `gate`: `Brief.parse(result.text)`; si está incompleto → escribe `ctx[MISSING_KEY]` y devuelve `False`;
  si está completo → `b.write(brief_path)` para congelarlo, lo carga en el ctx y devuelve `True`.
- `reduce`: devuelve `ctx[BRIEF_KEY].prompt_block()`, **no el texto literal del modelo** —— en el
  literal puede venir mezclado todo lo que haya escrito de más.
- `resume_from` **se queda en el valor por defecto `None`**: el paso siguiente es una sesión nueva, solo
  recibe el brief, no ese intercambio de preguntas y respuestas.
  Las preguntas de la clarificación previa **nunca entraron** en el contexto del coordinador; no es que
  entraran y luego se recortaran.

Los tres sitios que se cargan en el ctx: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`,
`ctx.pop(MISSING_KEY, None)`.

| Constante | Valor | Descripción |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` es el objeto `Brief`; `ctx[step.name]` es su `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Qué secciones faltan cuando la clarificación falla (nombres de sección en chino), para mostrarlo en la UI |
| `CLARIFY_RESUME` | Un prompt en chino | "接着刚才那次没问完的需求确认继续 —— **不是重新开始**……". Sin esta frase, al continuar se reenvía la petición original como si fuera una tarea nueva y el clarificador puede volver a preguntar lo ya preguntado |

### `goal_step()` {#goal-step}

```python
def goal_step(
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    brief_key: str = "确认需求",
    name: str = "设定目标",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_set: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw: Any,
) -> Step
```

Produce un `Step` que **fija el objetivo**: el [juez](glossary.md#判定者) lee el brief y escribe el
objetivo más la lista de comprobaciones; se parsea a [`Goal`](#goal), se congela y se escribe en disco.
Tiene la misma forma que `clarify_step`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `channel` | `HumanChannel` | obligatorio, posicional | Canal de preguntas |
| `goal_path` | `str \| Path` | obligatorio | Dónde aterriza el fichero de objetivo |
| `brief_key` | `str` | `"确认需求"` | Toma el texto del brief de `ctx[brief_key]` para meterlo en el prompt. **Si no lo encuentra, queda `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Nombre del paso |
| `spec` | `AgentSpec \| None` | `None` | Si no se da, usa `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instrucciones adicionales |
| `always_set` | `bool` | `False` | `True` = rehacer la lista siempre, exista o no el fichero de objetivo |
| `on_fail` | `str` | `"stop"` | Igual que arriba |
| `retries` | `int` | `0` | Igual que arriba |
| `**spec_kw` | | | Se propaga a [`judge()`](#judge-role) |

**No hay parámetro `can_run`** —— si quieres que el juez que fija el objetivo pueda ejecutar comandos,
la única vía es pasar `can_run=True` por `**spec_kw`. Sin eso no dispone de `Bash`, y la regla de
`JUDGE_RULES` de "mira primero en qué entorno estás" no se puede ejecutar.

Además de parsear y congelar, el `gate` hace una cosa más: si el objetivo contiene entradas
`[此环境无法验证:…]`, emite **en ese mismo momento** a través de `ctx["_on_event"]` un
`Event("task", payload={"unverifiable", "total", "path"})` como aviso —— el destino de esas entradas
queda decidido justo al fijar el objetivo, y para cuando llegue el veredicto ya te habrás gastado el
dinero de una ronda entera de trabajo.

**No se define `resume_prompt`** —— fijar el objetivo debe reenviar el brief completo, por definición.

| Constante | Valor | Descripción |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` es el objeto `Goal`; `ctx[step.name]` es markdown |
| `VERDICT_KEY` | `"_verdict"` | El último [`Verdict`](#verdict), para la UI |
| `ROUND_KEY` | `"_goal_rounds"` | Cuántas rondas de veredicto se han hecho |

### `with_goal()` {#with-goal}

```python
def with_goal(
    step: Step,
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    spec: AgentSpec | None = None,
    rounds: int = 3,
    instructions: str = "",
    can_run: bool = False,
    name: str | None = None,
    **spec_kw: Any,
) -> Step
```

Envuelve un `Step` existente con el [guardián de objetivo](glossary.md#目标看守): al final de cada ronda
el juez emite un veredicto independiente y, si no se ha alcanzado, lo devuelve para seguir trabajando.

El resultado es `replace(step, retries=max(0, rounds - 1), gate=<nuevo gate>, on_reject=<nuevo on_reject>)` ——
con `dataclasses.replace` en lugar de reconstruir campo a campo; en una reconstrucción anterior se
olvidó `resume_prompt`, **y no dio ningún error**, simplemente al continuar se reenviaba otra vez el
brief entero.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `step` | `Step` | obligatorio, posicional | El paso vigilado |
| `channel` | `HumanChannel` | obligatorio, posicional | Canal para pedir ayuda a una persona cuando no se puede decidir |
| `goal_path` | `str \| Path` | obligatorio | Fichero de objetivo; se lee de aquí cuando `ctx[GOAL_KEY]` no está completo |
| `spec` | `AgentSpec \| None` | `None` | Si no se da, usa `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Rondas totales, no rondas adicionales**: `rounds=3` → `retries=2` → como mucho tres rondas de trabajo. `rounds=1` = una ronda, un veredicto, y si no pasa, falla |
| `instructions` | `str` | `""` | Instrucciones adicionales para el juez |
| `can_run` | `bool` | `False` | Si el juez puede ejecutar `Bash` |
| `name` | `str \| None` | `None` | Nombre del juez; por defecto `f"{step.name}·判定"` |
| `**spec_kw` | | | Se propaga a `judge()` |

El `gate` es **async**, y su flujo es:

1. Falta `ctx["_runtime"]` → **lanza `StepAbort`** ("no se puede obtener el Runtime, imposible juzgar el objetivo"). **No finjas que ha pasado.**
2. `ctx[ROUND_KEY] += 1`.
3. Obtiene el objetivo: primero un `Goal` completo en `ctx[GOAL_KEY]`; si no, `Goal.load(goal_path)`; si no, un `Goal()` vacío.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **El juez es un `Runtime.run` independiente, con `resume` siempre `None` —— siempre una sesión nueva**;
   `step_name` lleva el número de ronda, así que no entra en el linaje entre procesos.
5. `Verdict.parse(vr.text)` se escribe en `ctx[VERDICT_KEY]`.
6. `v.achieved` → devuelve `True`.
7. Si no es `unreachable` (incluidos los casos ambiguos con `v.ok=False`) → en los ambiguos añade una razón por defecto y devuelve `False`.
   **Todo lo ambiguo cuenta como no alcanzado** —— no se puede dar el trabajo por cerrado con un "parece que vale".
8. `unreachable` → `await channel.ask(...)` para preguntar a la persona, con tres opciones:
   - Nadie responde (`a.state != "answered"`) → **lanza `StepAbort`**. Seguir girando en vacío es la opción más cara.
   - «Aceptar este resultado y seguir así» → devuelve `True`.
   - «Modificar el objetivo» → pregunta otra vez por el nuevo objetivo, hace `g.amend(...).write(goal_path)`, actualiza `ctx[GOAL_KEY]` y devuelve `False`.
   - El resto (incluida una respuesta libre escrita por la persona) → se toma como "te has equivocado al juzgar", se anota lo que dijo en `v.reason` y devuelve `False`.

`on_reject` es **síncrono**: devuelve `ctx[VERDICT_KEY].feedback()`, o `""` si no hay `Verdict`
(degrada a arrancar de cero).

### `starter_flow()` {#starter-flow}

```python
def starter_flow(
    ask: str,
    *,
    workspace: str | Path = ".",
    run_dir: str | Path = "runs",
    new: bool = False,
    isolate: bool = False,
    clarify_only: bool = False,
    goal: bool = True,
    rounds: int = 3,
    judge_can_run: bool = False,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    instructions: str = "",
    worker_prompt: str = "你负责实现。每改一处就跑一次验证,别攒到最后。",
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
    log_name: str = "问答记录.md",
) -> Workflow
```

Monta un workflow de tres pasos listo para usar: **clarificar requisitos → fijar el objetivo → trabajar**
(con guardián de objetivo). Es lo que usa el comando `flower`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `ask` | `str` | obligatorio, posicional | Una frase con la petición. **Al despertar no es una tarea nueva, es "una frase más que se ha dicho"** |
| `workspace` | `str \| Path` | `"."` | Espacio de trabajo |
| `run_dir` | `str \| Path` | `"runs"` | Directorio de runs |
| `new` | `bool` | `False` | `True` = archiva linaje + brief + objetivo (los tres juntos) y empieza de cero |
| `isolate` | `bool` | `False` | Abre un worktree de [aislamiento](glossary.md#隔离) para el ejecutor. El workbench se traslada en consecuencia a `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Devuelve solo el Workflow con el paso de clarificación |
| `goal` | `bool` | `True` | Si se monta el [guardián de objetivo](glossary.md#目标看守). `False` = el paso de trabajo termina y ya está |
| `rounds` | `int` | `3` | Se propaga a `with_goal(rounds=)`, rondas totales |
| `judge_can_run` | `bool` | `False` | Se propaga a `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Se propaga a `HumanChannel`; `None` = sin límite |
| `timeout_s` | `float \| None` | `1800.0` | Se propaga a `HumanChannel`. `0` = totalmente automático, todas las preguntas caen en el vacío al instante |
| `instructions` | `str` | `""` | Instrucciones adicionales para el clarificador |
| `worker_prompt` | `str` | ver firma | System prompt del ejecutor |
| `brief_name` | `str` | `"需求.md"` | Nombre del fichero de brief, aterriza en `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Nombre del fichero de objetivo, ídem |
| `log_name` | `str` | `"问答记录.md"` | Nombre del fichero de registro de preguntas y respuestas, ídem |

Montaje fijo:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# coordinador = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Ramas de comportamiento:

- `isolate=True` y el workspace no es un repositorio git → **lanza `ValueError`**, en lugar de
  descubrirlo cuando la herramienta `Agent` da error (para entonces el dinero ya está gastado).
- **Detección de despertar**: si `Brief.load(brief_path)` existe y cumple `complete()`, cuenta como
  despertar. Si no es un despertar y `ask` está vacío →
  **lanza `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- Al despertar, esa frase aterriza a la vez en **tres sitios**, y si falta uno se pierde en silencio:
  se añade al brief (`ch.amend(said, label="唤醒时追加")`, sin reescribir si ya está en el fichero);
  hace que `goal_step(always_set=True)` rehaga la lista (si no se rehace, el juez sigue leyendo el
  objetivo viejo); y se entrega directamente al coordinador (en su contexto está el objetivo **viejo**,
  y si no se la das trabajará con el criterio viejo para luego ser juzgado con el nuevo).

### `wake_state()` {#wake-state}

```python
def wake_state(
    workspace: str | Path = ".",
    *,
    run_dir: str | Path = "runs",
    isolate: bool = False,
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
) -> dict
```

**Sondeo de solo lectura antes de arrancar; no escribe ni un byte.** Sirve para decirle a la persona,
antes de empezar de verdad, si esto continúa lo anterior o arranca de cero.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Espacio de trabajo, posicional |
| `run_dir` | `str \| Path` | `"runs"` | Directorio de runs |
| `isolate` | `bool` | `False` | Determina la ubicación del workbench; debe valer lo mismo que lo pasado a `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Nombre del fichero de brief |
| `goal_name` | `str` | `"目标.md"` | Nombre del fichero de objetivo |

El dict devuelto:

| Clave | Tipo | Descripción |
|---|---|---|
| `waking` | `bool` | El brief existe y sus cuatro secciones están completas |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Número de entradas de la lista del objetivo; `0` si no hay objetivo |
| `woke` | `int` | `Lineage.woke`, cuántas veces se ha despertado ya |
| `steps` | `dict` | Copia de `Lineage.steps`, nombre de paso → `session_id` |

La ubicación del workbench **se define una sola vez, aquí y en `starter_flow`**: `isolate=True` →
`<ws>.parent/.flower-<ws.name>` (fuera del repositorio); si no, `<ws>/.flower`. Si el driver quiere
saber dónde está el brief, también pasa por esta función —— componer la ruta por tu cuenta y
equivocarte no da error, simplemente falla en silencio.

---

## Fábrica de roles {#角色工厂}

Código fuente: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Los cinco roles son funciones fábrica. Cada rol = **un texto de reglas inyectado + un conjunto de herramientas + un conjunto de hooks**.
`worker()` produce un `AgentDefinition` del SDK (para usarlo como subagent); los otros cuatro producen un [`AgentSpec`](#agentspec)
(levantan su propia sesión).

Los roles en sí **no montan hooks** —— interceptar herramientas lo monta automáticamente `Runtime._attempt` según `spec.delegate_only`,
ver [la capa de hooks](#hook).

Constantes internas de grupos de herramientas (no exportadas, pero determinan los valores por defecto):

```python
COORDINATOR_TOOLS = ["Agent", "TodoWrite", "Read"]
WEB_TOOLS         = ["WebFetch", "WebSearch"]
WORKER_TOOLS      = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"]
```

### `coordinator()` {#coordinator}

```python
def coordinator(
    name: str,
    instructions: str,
    workers: dict[str, AgentDefinition],
    *,
    channel: Any = None,
    can_read: bool = True,
    glance: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    permission_mode: str = "acceptEdits",
    compact: Any = None,
    hooks: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> AgentSpec
```

Crea el [coordinator](glossary.md#协调者) que vive en el [main thread](glossary.md#主线程): descompone la tarea, reparte trabajo, lee informes, decide,
**pero no toca nada**. Los tres primeros parámetros son posicionales.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | obligatorio | Nombre del rol; también el nombre de step por defecto |
| `instructions` | `str` | obligatorio | Instrucciones de dominio. El resultado final es `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | obligatorio | Qué roles tiene a su cargo; acaba en `AgentSpec.agents` |
| `channel` | `HumanChannel \| None` | `None` | Si se da, añade a la vez las herramientas `inbox` **y** `ask`, y fija `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → sin `Read` |
| `glance` | `bool` | `True` | Añade `"Bash"` y fija `AgentSpec.glance`. **Qué se puede ejecutar realmente lo controla `delegate_guard`**, no esto |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | Límite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Límite de [presupuesto](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Modo de permisos. **Atención a este valor por defecto** —— pasárselo a `clarify()`/`judge()` desmonta la protección de esos dos roles |
| `compact` | `CompactPolicy \| None` | `None` | Si se da, `Runtime` no lo forzará a `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks extra; se fusionan con `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Variables de entorno extra |

Tres cosas fijas en el `AgentSpec` resultante: `delegate_only=True`, `agents=workers` y
`workbench` con el valor por defecto de `AgentSpec`, `True`.

En el código fuente está escrito explícitamente que **no se use `disallowed_tools` para implementar «solo coordina, no toca»** —— eso es a nivel de sesión
y desactivaría también `Bash`/`Write` en los subagents; ver la advertencia en [`AgentSpec`](#agentspec).
La forma correcta es la de aquí: `delegate_only=True` + no dar `allowed_tools`,
y que [`delegate_guard`](#delegate-guard) intercepte solo el main thread según el `agent_id`.

Si se da `channel`, **vienen las dos herramientas juntas**, no es opcional: al montar el MCP server están ambas, y
`allowed_tools` no es excluyente, así que se pueden invocar estén listadas o no. Sin supervisión humana, cada `ask` se comerá el `timeout_s` entero ——
para ese escenario, usa `HumanChannel(timeout_s=0)`.

### `worker()` {#worker}

```python
def worker(
    description: str,
    prompt: str,
    *,
    tools: list[str] | None = None,
    model: str = "inherit",
    effort: str | int | None = None,
    max_turns: int | None = None,
    permission_mode: str | None = None,
    skills: list[str] | None = None,
    discipline: bool = True,
    isolate: bool = False,
) -> AgentDefinition
```

Crea la definición del [subagent](glossary.md#subagent) que hace el trabajo de verdad. Los dos primeros parámetros son posicionales.
Devuelve un `AgentDefinition` del SDK, listo para meterlo en `coordinator(workers={...})`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `description` | `str` | obligatorio | **La base con la que el coordinator elige a quién asignar** —— deja claro «qué trabajo se le da» |
| `prompt` | `str` | obligatorio | Su system prompt. Con `discipline=True` se compone como `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | Al worker no se le debe degradar |
| `effort` | `str \| int \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | Acaba en el **`maxTurns`** del SDK (camelCase) |
| `permission_mode` | `str \| None` | `None` | Acaba en el **`permissionMode`** del SDK (camelCase) |
| `skills` | `list[str] \| None` | `None` | Qué skills puede usar |
| `discipline` | `bool` | `True` | Si se añade o no el bloque de disciplina de reporte `WORKER_RULES` |
| `isolate` | `bool` | `False` | Marca de [aislamiento](glossary.md#隔离); pasa por `isolated()`, **no es un campo de `AgentDefinition`** |

`isolate=True` exige que el workspace sea un repositorio git; si no, la herramienta `Agent` devuelve directamente `"not in a git repository"`,
**no degrada en silencio**. Además, la marca es un atributo de Python —— hacer `dataclasses.replace()` sobre el `AgentDefinition`
la pierde y el aislamiento deja de funcionar en silencio.

### `clarify()` {#clarify-role}

```python
def clarify(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_read: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

Crea el [clarifier](glossary.md#确认者): antes de tocar nada, deja claros los requisitos; no hace, solo pregunta, y al final produce exactamente cuatro secciones.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | obligatorio | Nombre del rol, posicional |
| `channel` | `HumanChannel` | obligatorio | Canal de preguntas, posicional |
| `instructions` | `str` | `""` | Instrucciones adicionales, añadidas tras `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | Con `True` añade `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | **Sin límite de turnos** |
| `max_budget_usd` | `float \| None` | `None` | Límite de presupuesto |

El `AgentSpec` resultante: `allowed_tools = [channel.tool_name] + (esas cinco si puede leer)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (no tiene herramientas de escritura, el índice no le sirve de nada),
y `permission_mode` hereda el `"default"` por defecto de `AgentSpec`.
**Sin `Write` / `Edit` / `Bash` / `Agent`, y sin `inbox`** (a diferencia del coordinator).

!!! warning "Poner un `max_turns` pequeño convierte «preguntas ilimitadas» en palabrería"
    Cada pregunta es un turno. `max_turns=16` equivale a «como mucho una docena de preguntas», y la frase del canal «no hay límite de turnos» queda anulada al instante.

    Para abrir las preguntas de verdad hay que abrir **las dos** cosas: `HumanChannel.max_asks` (ya viene en `None` = sin límite)
    y `max_turns` (ya viene en `None`).

### `judge()` {#judge-role}

```python
def judge(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_run: bool = False,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

Crea el [judge](glossary.md#判定者): o fija el objetivo antes de arrancar, o emite el verdict de cada ronda al terminarla.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | obligatorio | Nombre del rol, posicional |
| `channel` | `HumanChannel` | obligatorio | Canal de preguntas, posicional |
| `instructions` | `str` | `""` | Instrucciones adicionales, añadidas tras `JUDGE_RULES` |
| `can_run` | `bool` | `False` | Con `True` se añade `Bash` a la lista blanca; `whitelist_guard` deja pasar `Bash` y sigue interceptando `Write`/`Edit` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | Límite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Límite de presupuesto |

El `AgentSpec` resultante: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (con `can_run`) `["Bash"]`,
`workbench=False`, el resto igual que `clarify()`. **Sin `Write` / `Edit` / `Agent`, y sin `inbox`.**

**Compromiso**: con `can_run=True` el verdict es más duro (puede ejecutar de verdad los comandos de aceptación), a cambio de que el judge pueda modificar el workspace ——
`Bash` por sí solo ya permite escribir archivos. Si quieres un verdict absolutamente neutral, no lo actives.

### `oracle()` {#oracle}

```python
def oracle(
    name: str = "旁路问答",
    *,
    instructions: str = "",
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = 12,
    max_budget_usd: float | None = 0.5,
) -> AgentSpec
```

Crea el [oracle](glossary.md#旁路顾问): mientras el run sigue en marcha le preguntas «¿por dónde va esto?», y él mira los eventos recientes y el workbench
antes de responder. **Lo que diga no entra en el contexto de ese run.**

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Nombre del rol, posicional |
| `instructions` | `str` | `""` | Instrucciones adicionales, añadidas tras `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | **`12`** | Viene con freno por defecto |
| `max_budget_usd` | `float \| None` | **`0.5`** | Viene con freno por defecto. Esto es «una pregunta de pasada», no debe descontrolarse |

El `AgentSpec` resultante: `allowed_tools = ["Read", "Glob", "Grep"]` (**sin channel** —— no pregunta,
solo responde), `workbench=True` (**el único de los cinco roles que no es coordinator y tiene el workbench abierto** —— justamente necesita leer esos entregables y notas).

### Los cinco textos de reglas {#rules}

Las cinco constantes están en `__all__`: puedes importarlas para leerlas, componerlas o modificarlas.

| Constante | A quién se inyecta | Forma de inyección | Puntos clave |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Eres «una persona que sabe usar Claude Code», no un worker; no puedes escribir archivos / tocar código / correr tests; `Bash` solo alcanza para «echar un vistazo» y su resultado caduca; **el [task brief](glossary.md#任务书) solo lleva lo específico de esta tarea**; la única regla que aún hay que explicitar es «dónde está el workbench + los entregables largos van a `artifacts/` + en la respuesta solo se dan rutas»; revisa `inbox` cada vez que completes una acción de etapa; `ask` bloquea, úsalo solo en bifurcaciones reales |
| `WORKER_RULES` | `worker()` | Se añade **después** del `prompt` del subagent | Formato de respuesta **结论 / 依据 / 产出 / 未验证** (conclusión / evidencia / entregables / sin verificar), no más de 30 líneas; prohibido pegar contenido de archivos, salida de comandos, logs o diffs literales; prohibido narrar el proceso de prueba y error; antes de empezar, mira `.flower/scripts/`. **A propósito no dice «los entregables largos van a `artifacts/`»** —— la ruta real la genera `Workbench`, escribirla a fuego sería erróneo |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | No hace nada, solo aclara los requisitos; **sin límite de veces, pregunta hasta que quede claro**; puede que no haya nadie: si hay timeout, decide tú y escríbelo en 「未知与假设」; salida de **exactamente cuatro secciones**; no escribas código ni pegues contenido de archivos |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Una de dos cosas. **Fijar el objetivo**: cada ítem de la lista tiene que poder verificarse en el acto, la longitud de la lista la determina el número de formas de fallar, **los límites no son ítems de verdict**, y a los ítems no verificables se les añade al final `[此环境无法验证:原因]`. **Emitir el verdict de esta ronda**: salida de **exactamente tres secciones**, se juzga **el entregable, no el código fuente**, por defecto no te creas el «ya está hecho»; «no se logró» y «aquí no se puede verificar» son dos conclusiones distintas, y la segunda **jamás puede dar por aprobado** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Eres una vía lateral; ese run sigue corriendo, ni lo interrumpes ni participas; **solo lectura**; se responde y se descarta, lo que digas no entra en el contexto de ese run; solo tienes en la mano la «ventana de eventos recientes» y el «workbench»; mira antes de responder, si no puedes responder dilo, y sé breve |

---

## Definición de agent {#agent-定义}

Código fuente: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` es la declaración completa de un agent especializado, y `build_options` la compila al `ClaudeAgentOptions` del SDK.
Lo que produce la [fábrica de roles](#角色工厂) es precisamente un `AgentSpec` —— cuando necesites una combinación fuera de la fábrica, constrúyelo directamente.

### `AgentSpec` {#agentspec}

```python
@dataclass
class AgentSpec:
    name: str
    instructions: str
    allowed_tools: list[str] = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    permission_mode: str = "default"
    agents: dict[str, Any] | None = None
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, Any] | None = None
    compact: CompactPolicy | None = None
    env: dict[str, str] = field(default_factory=dict)
    glance: bool = False
    workbench: bool = True
    delegate_only: bool = False
```

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | obligatorio | Nombre del rol. También el `step_name` por defecto de `Runtime.run`, y cómo se autodenomina en el texto de rechazo de `whitelist_guard` |
| `instructions` | `str` | obligatorio | Instrucciones de dominio. **Se [añade](glossary.md#叠加) después del system prompt nativo de Claude Code, no lo reemplaza** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Lista de exención de aprobación, no lista blanca excluyente** —— el modelo igual puede invocar herramientas que no estén ahí. La exclusividad la da [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **A nivel de sesión**. Ver la advertencia de abajo |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | Límite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Límite de [presupuesto](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Modo de permisos |
| `agents` | `dict[str, Any] \| None` | `None` | Tabla de definiciones de subagents; los valores son `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Tabla de MCP servers. `HumanChannel.mcp_servers()` se rellena aquí directamente |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks extra; `Runtime` los fusiona con los suyos vía `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Si se da, `Runtime` no lo forzará a `no_summary` |
| `env` | `dict[str, str]` | `{}` | Variables de entorno inyectadas al subproceso. `compact.env()` hace update encima |
| `glance` | `bool` | `False` | Permite al coordinator ejecutar por su cuenta un `Bash` de «solo mirar». Qué pasa lo decide [`is_ephemeral`](#is-ephemeral), y el resultado queda marcado como caducado por `EphemeralPolicy` |
| `workbench` | `bool` | `True` | Si se inyecta el índice del workbench en el system prompt de este agent. **Los roles sin herramientas de escritura deben desactivarlo** (`clarify()` / `judge()` ya vienen con `False`) |
| `delegate_only` | `bool` | `False` | Solo coordina, no toca. Con `True`, `Runtime` monta `delegate_guard` y **no monta** `whitelist_guard` |

!!! warning "`disallowed_tools` es a nivel de sesión y desactiva también los subagents"
    Texto del error observado: `"Bash is disabled for this session, in subagents as well as here"`.
    Es decir: si para que el coordinator no toque nada usas `disallowed_tools=["Bash"]`, los workers que despaches tampoco podrán ejecutar comandos ——
    el run entero se va al traste.

    Para «solo coordinar sin tocar», usa `delegate_only=True` + no dar `allowed_tools`, y deja que
    [`delegate_guard`](#delegate-guard) intercepte solo el main thread según el `agent_id`.

### `build_options()` {#build-options}

```python
def build_options(
    spec: AgentSpec,
    *,
    cwd: str | Path | None = None,
    session_store: SessionStore | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    use_plugin: bool = True,
    portable: bool = True,
    add_dirs: list[str] | None = None,
    flush: str = "eager",
    prelude: str = "",
) -> ClaudeAgentOptions
```

Compila un `AgentSpec` al `ClaudeAgentOptions` del SDK. Es lo que llama internamente `Runtime._attempt`;
si manejas el SDK por tu cuenta (sin `Runtime`), también entras por aquí.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `spec` | `AgentSpec` | obligatorio, posicional | La declaración a compilar |
| `cwd` | `str \| Path \| None` | `None` | Solo se escribe `cwd` si no es `None` |
| `session_store` | `SessionStore \| None` | `None` | Solo si no es `None` se escriben `session_store` y `session_store_flush` |
| `resume` | `str \| None` | `None` | Qué sesión continuar |
| `fork` | `bool` | `False` | Acaba en `fork_session`. **Está anidado dentro de `if resume:`** |
| `resume_at` | `str \| None` | `None` | Acaba en `resume_session_at`. **También anidado dentro de `if resume:`** |
| `use_plugin` | `bool` | `True` | Con `True` y si existe `PLUGIN_DIR` → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Directorios autorizados adicionales. **Obligatorio cuando el workbench está fuera del workspace** |
| `flush` | `str` | `"eager"` | Acaba en `session_store_flush` |
| `prelude` | `str` | `""` | Bloque añadido tras `instructions` (por aquí va el índice del workbench) |

Correspondencias:

| Clave de option producida | Valor |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Tomados directamente de `spec` |
| `setting_sources` | `[]` (portable) o `["project"]` |
| `plugins` | Solo si existe el directorio `plugin/` en la raíz del repositorio |
| `cwd` / `add_dirs` | Solo se escriben si no están vacíos |
| `session_store` / `session_store_flush` | Solo se escriben si `session_store` no es `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Cada uno se escribe solo si no está vacío |
| `env` | `dict(spec.env)` y luego `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Solo surten efecto si `resume` es verdadero** |

`PLUGIN_DIR` es el directorio `plugin/` de la raíz del repositorio (tres niveles por encima de `flower/core/agent.py`). Tras instalar con pip ese directorio puede no existir,
y el código lo comprueba con `is_dir()`.

!!! warning "`fork=True` sin `resume` no hace nada, en silencio"
    Tanto `fork_session` como `resume_session_at` están anidados dentro de `if resume:` —— sin `resume` no surten efecto en absoluto
    **y tampoco dan error**. Igualmente, `Runtime.run(resume_at=...)` solo funciona si se da `resume`,
    y **`Workflow` nunca pasa `resume_at`**: para retroceder por mensaje solo queda llamar directamente a `Runtime.run`.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

El panel de interruptores del auto-[compact](glossary.md#压缩); su producto es un conjunto de variables de entorno a inyectar en el subproceso.
El algoritmo de compact en sí está dentro del binario del harness y no se puede cambiar; lo único ajustable es «si se dispara o no».

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = no fija nada, umbral = ventana − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (apaga también `/compact`). **Cualquier otro valor lanza `ValueError`**, no se ignora en silencio |
| `window` | `int \| None` | `None` | Si no es `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. El CLI lo limita a 100k–1M; poner menos de 100k lo sube a 100k |

| Método | Firma | Descripción |
|---|---|---|
| `env` | `() -> dict[str, str]` | Produce las variables de entorno. **El `ValueError` por un `mode` ilegal se lanza aquí, no en la construcción** —— lo llama `build_options`, así que el error aparece dentro de `Runtime.run` |

### `HandoffPolicy` {#handoffpolicy}

```python
@dataclass
class HandoffPolicy:
    enabled: bool = True
    window: int = field(default_factory=default_window)
    headroom: int = 50_000
    max_generations: int = 8

    @property
    def at(self) -> int: ...        # max(10_000, window - headroom)
    @property
    def warn_at(self) -> int: ...   # max(1_000, at - 20_000)
```

El objeto de política que, cuando el contexto está a punto de llenarse, «escribe el [handoff document](glossary.md#交接书) y abre una sesión nueva» en lugar de hacer compact.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `enabled` | `bool` | `True` | Al apagarlo se vuelve al auto-compact |
| `window` | `int` | `default_window()` | Cuál se considera que es la ventana de contexto del modelo |
| `headroom` | `int` | `50_000` | Cuánto margen se reserva. Razón: el auto-compact se dispara en ventana −33k, el handoff tiene que llegar antes, y «escribir el handoff» todavía consume una ronda |
| `max_generations` | `int` | `8` | Cuántas generaciones como máximo por step. **Es un freno anti-descontrol, no planificación de capacidad** |

| Propiedad | Tipo | Descripción |
|---|---|---|
| `at` | `@property -> int` | Umbral de handoff `max(10_000, window - headroom)`. **Con suelo de 10k** —— por debajo ni siquiera se puede escribir el handoff |
| `warn_at` | `@property -> int` | Posición del aviso de proximidad `max(1_000, at - 20_000)`; se emite una sola vez por generación |

!!! warning "Un `window` demasiado pequeño provoca handoffs infinitos y quema dinero"
    Si `at` queda por debajo del **suelo de arranque** de ese rol (medido en unos 34k para el coordinator), cada sesión nueva cruza la línea en cuanto abre la boca; y como
    **el handoff no consume cuota de reintentos** (`attempt -= 1`), se entra en un bucle vacío infinito. El único freno es `max_generations=8`:
    al llegar ahí, `error` se sustituye por un diagnóstico que sugiere subir `window` o desactivar el handoff.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Adivina la ventana de contexto a partir de la **cadena del nombre del modelo** en las variables de entorno `ANTHROPIC_MODEL` o `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Condición | Devuelve |
|---|---|
| El nombre contiene la palabra suelta `1m` (regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| El nombre contiene `haiku` | `200_000` |
| El resto (**incluido no tener ninguna de las dos variables definidas**) | `1_000_000` |

**Por defecto toma el valor agresivo.** Pasarse no es un error fatal: la API devuelve `prompt is too long`, y `Runtime` reconoce esa señal
(el `is_overflow` interno) y hace handoff en el acto —— pero el handoff de esa generación será la versión degradada.

---

## Documentos {#文书}

Código fuente: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Cuatro dataclasses, todas dedicadas a «parsear una respuesta del modelo en un número fijo de secciones y volcarla a disco». Forma común:
`parse()` parsea, `missing()` / `complete()` comprueban si está completo, `to_markdown()` es para humanos,
`prompt_block()` es para el modelo aguas abajo, y `write()` / `load()` vuelcan a disco y releen.

### `Brief` {#brief}

```python
@dataclass
class Brief:
    goal: str = ""
    accept: str = ""
    bounds: str = ""
    unknowns: str = ""
    path: Path | None = field(default=None, compare=False)
```

El [brief](glossary.md#需求确认书), **exactamente cuatro secciones**, en el orden fijo
`goal` → `accept` → `bounds` → `unknowns`; los nombres de sección en chino son 「目标」「验收标准」「边界」「未知与假设」.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `goal` | `str` | `""` | Objetivo |
| `accept` | `str` | `""` | Criterios de aceptación |
| `bounds` | `str` | `""` | Límites |
| `unknowns` | `str` | `""` | Incógnitas y supuestos |
| `path` | `Path \| None` | `None` | Ubicación en disco. `compare=False`, no participa en la comparación de igualdad |

| Método | Firma | Descripción |
|---|---|---|
| `missing` | `() -> list[str]` | **Nombres en chino** de las secciones que faltan; se pueden mostrar tal cual |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Parsea las cuatro secciones de la respuesta del modelo. **Primero quita los bloques de código con fences**; lo que no se parsea queda vacío |
| `to_markdown` | `() -> str` | Documento completo con cabecera de metadatos; las secciones vacías se escriben como `"(未填)"` |
| `prompt_block` | `() -> str` | Versión compacta para alimentar aguas abajo; **solo secciones no vacías**, sin metadatos |
| `write` | `(path: str \| Path) -> Path` | Crea el directorio padre, escribe a disco, fija `self.path` a la ruta resuelta y la devuelve |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Devuelve `None` si el archivo no existe o hay `OSError`. **Convierte el marcador `"(未填)"` de vuelta a cadena vacía** |

Reglas de parseo (donde se concentran los errores):

- Al quitar fences, **si encuentra un ``` o `~~~` sin cerrar, descarta todo desde ahí** —— se ha observado que el clarifier pega el código entero en su respuesta.
  Si la salida del modelo se trunca, ninguna sección posterior se parsea, así que `complete()` es `False` y el gate lo devuelve para repetir.
- La regex de títulos tolera `## 目标` / `**目标**` / `目标:` / `3. 边界`, y también que el cuerpo venga pegado al título.
- La tabla de alias se compila en orden decreciente de longitud; si no, "未知" se comería antes a "未知与假设".
- Si una misma sección aparece repetida, **se toma la primera con contenido**.
- Si al editar el brief a mano copias el marcador `"(未填)"` de `to_markdown()`, esa sección se sigue considerando faltante.

### `Handoff` {#handoff}

```python
@dataclass
class Handoff:
    doing: str = ""
    decided: str = ""
    deadends: str = ""
    next: str = ""
    scene: str = ""
    step: str = ""
    path: Path | None = field(default=None, compare=False)
```

El [handoff document](glossary.md#交接书) que se escribe en el [handoff](glossary.md#换代), cinco secciones.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `doing` | `str` | `""` | Qué se está haciendo. **Obligatorio** |
| `decided` | `str` | `""` | Qué se ha decidido |
| `deadends` | `str` | `""` | Caminos que no llevan a nada |
| `next` | `str` | `""` | Siguiente paso. **Obligatorio** |
| `scene` | `str` | `""` | Estado actual |
| `step` | `str` | `""` | Solo para la cabecera del documento, **no participa en el parseo** |
| `path` | `Path \| None` | `None` | Ubicación en disco |

**Solo son obligatorias `doing` y `next`** —— exigir por norma que «caminos que no llevan a nada» no esté vacío obliga al modelo a inventar.

| Miembro | Firma | Descripción |
|---|---|---|
| `missing` | `() -> list[str]` | **Solo comprueba esas dos secciones obligatorias** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Si el cuerpo lleva la marca de degradación `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Reutiliza el segmentador de `Brief` |
| `to_markdown` | `() -> str` | Las secciones vacías se escriben como `"(空)"` |
| `prompt_block` | `() -> str` | **La cabecera le dice explícitamente al que recoge «estás tomando el relevo»**, para que no se dé la vuelta a pedirle contexto a alguien |
| `write` | `(path) -> Path` | Igual que `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Igual que `Brief.load` |

Tres miembros del mismo módulo **no exportados pero semánticamente clave**: `is_overflow(*texts)` hace match con `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed`, etc., y convierte un «error duro» en «handoff inmediato»; `HANDOFF_PROMPT` es el prompt con el que
**la propia sesión actual** escribe su handoff (contiene los dos marcadores `{used}` y `{window}`; **no es un rol nuevo** ——
solo ella tiene ese contexto); y `degraded(step, prompt, *, why="")` compone mecánicamente un handoff cuando no se ha podido escribir,
metiendo en `scene` los primeros **1200** caracteres de la tarea original.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

El objetivo + la lista de comprobaciones del [goal guard](glossary.md#目标看守).

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `statement` | `str` | `""` | Enunciado del objetivo |
| `checks` | `list[str]` | `[]` | Lista de comprobaciones, una por línea |
| `path` | `Path \| None` | `None` | Ubicación en disco |

| Miembro | Firma | Descripción |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Los ítems de `checks` marcados con `[此环境无法验证:…]`. **Están condenados a no pasar desde el momento en que se fija el objetivo** |
| `missing` | `() -> list[str]` | Exige `statement` no vacío **y** `checks` no vacío |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` una por línea, quitando automáticamente las marcas `-` / `*` / `1.` |
| `to_markdown` | `() -> str` | Si la lista está vacía, escribe `"(空)"` |
| `prompt_block` | `() -> str` | Versión compacta para alimentar aguas abajo |
| `write` / `load` | Igual que `Brief` | Volcado a disco y relectura |
| `amend` | `(extra: str) -> Goal` | **Añade, no sobrescribe**: tras `statement` concatena `"\n\n(已修改)" + extra` y devuelve `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

El resultado del verdict del [judge](glossary.md#判定者) para una ronda, **exactamente tres secciones**: conclusión / motivo / no superado.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`; `""` si no se pudo parsear |
| `reason` | `str` | `""` | Motivo |
| `failed` | `list[str]` | `[]` | Ítems de la lista que no han pasado |

| Miembro | Firma | Descripción |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Si se logró parsear una conclusión. **`ok=False` debe tratarse como «no alcanzado», nunca como alcanzado** |
| `parse` | `@classmethod (text) -> Verdict` | Ver abajo |
| `feedback` | `() -> str` | Lo que se devuelve al worker: solo «qué falta», no la solución |

Orden de reconocimiento de `parse`:

1. Primero busca por sección titulada 「结论」/「判定」.
2. Si no hay sección titulada, sobre el texto entero tras strip: `fullmatch(r"1|true")` → alcanzado; `fullmatch(r"0|false")` → aún no.
3. Si no, busca en el texto de la conclusión la primera coincidencia de la tabla de palabras de estado (**las palabras largas primero**).
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」 van todas a `unreachable`** ——
   ya se ha tropezado con esto: plataforma objetivo macOS, ejecución en un contenedor Linux, y el judge dio por aprobado mirando una rama del código fuente.
4. Si sigue sin haber nada → busca un `\b1\b` suelto → alcanzado; `\b0\b` → aún no.
5. Si nada coincide → `state=""`, `ok=False`.

`unreachable` y `not_yet` **son dos conclusiones distintas**: la primera lleva por el camino de «parar y preguntar a una persona», no por el de «otra ronda».

---

## Capa hook {#hook}

Código fuente: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Esta capa es la **frontera de ejecución** de flower: qué herramientas no puede tocar el hilo principal,
cómo se recorta un resultado desmesurado, qué rol va a un worktree independiente —
todo lo impone el SDK vía hooks, **no el prompt**. La razón es directa: un prompt es una sugerencia y el
modelo puede ignorarla. Está medido: aunque el system prompt diga explícitamente «no uses worktree»,
la inyección de `isolate_guard` sigue surtiendo efecto (el modelo pasa `None`, lo que aterriza es `'worktree'`).

Nueve exportaciones: cinco fábricas de guard que devuelven `HookMatcher` (`whitelist_guard` puede devolver `None`), un ensamblador, un fusionador y dos funciones de marcado de aislamiento.
No hay que montarlas a mano: [`Runtime`](#runtime) las cablea automáticamente según el `AgentSpec`. Montarlas a mano solo hace falta si conduces el SDK tú mismo
(sin pasar por `Runtime`).

**La detección del hilo principal pasa por una única función**: `_is_main_thread(data) = not data.get("agent_id")` —
los datos de hook de ciclo de vida de herramienta de un subagent llevan `agent_id`, los del [hilo principal](glossary.md#主线程) no.
Todos los guards que «solo interceptan el hilo principal» se apoyan en esta línea.

Constantes de grupos de herramientas (a nivel de módulo, no exportadas, pero determinan los matchers por defecto):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Tabla rápida: qué guard va en qué evento del SDK {#hook-速查表}

| Función | Evento hook del SDK | matcher | Qué intercepta | Qué devuelve | Quién lo instala |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | los de `Bash\|Write\|Edit\|NotebookEdit` que **no están en `allowed_tools`** | **solo el hilo principal** llamando a una herramienta prohibida | `permissionDecision: "deny"` + motivo | `Runtime._attempt`, **solo si `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (modificable con `tools=`) | **solo el hilo principal** actuando por su cuenta; con `allow_glance=True` se deja pasar el `Bash` que supere `is_ephemeral()` | `deny` + «delega en un subagent» | `workbench_hooks(delegate_only=True)`, **solo si el `Runtime` tiene banco de trabajo** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` sin `cwd` ni `isolation`, y `subagent_type` marcado con `isolated()` | `permissionDecision: "allow"` + `updatedInput` (inyecta `isolation="worktree"`) | `workbench_hooks`, **solo si hay algún rol marcado en `agents`** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` cae dentro de `workbench.root` | `{}` (el efecto es `workbench.refresh()`) | `workbench_hooks`, siempre |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **campos de texto** de `tool_response` con ≥ `threshold` caracteres; leer el propio directorio de volcado se deja pasar | `updatedToolOutput` (volcado a disco + un puntero de una línea + los primeros 400 caracteres) | `workbench_hooks`, **solo si `spill_threshold` es verdadero** |

**La conclusión clave que se lee en esta tabla**: con `Runtime(workbench=False)` no se instala nada de `workbench_hooks`;
y para un coordinador con `delegate_only=True` también se salta `whitelist_guard` — **el hilo principal se queda sin una sola pared**.
Ver la advertencia de [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Hace que `allowed_tools` sea realmente excluyente para las cuatro herramientas que actúan.**

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `allowed` | `list[str] \| None` | obligatorio, posicional | Normalmente se le pasa directamente `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | Cómo se autodenomina en el texto de rechazo. `Runtime` le pasa `spec.name` |

- **Va en `PreToolUse`**, el matcher es `"|".join(banned)`, donde `banned` = los de `Bash` `Write` `Edit` `NotebookEdit`
  que no están en `allowed`.
- Si acierta, `permissionDecision: "deny"`, con un texto que viene a decir: «XX no tiene YY. **Es intencionado, no es un fallo de configuración.**
  Escribe la conclusión en el cuerpo de tu respuesta, el framework la tomará de ahí — no intentes rodearlo por otra vía».
- **Solo intercepta el hilo principal de esta sesión**, los subagents pasan — sus herramientas las decide `AgentDefinition.tools`.
- Cuando no hay nada que interceptar devuelve **`None`** (por ejemplo, un rol como `worker()` con todas las herramientas), y quien llama decide si instalarlo o no.

**Por qué tiene que existir**: `allowed_tools` es una **lista de exención de aprobación, no una whitelist excluyente**. Dos evidencias medidas:
el juez de fijación de objetivo ejecutó `Bash` 11 veces; en la sonda de $0.1
un agent con `allowed_tools=["Read"]` seguía pudiendo invocar `Write`/`Bash`.
Así que el «no tiene herramientas de escritura» de `clarify()` / `judge()` **lo sostiene este hook**, no la whitelist en sí.

La ventaja es que se deriva de `allowed_tools`, así que `judge(can_run=True)` conserva `Bash` automáticamente y sigue interceptando
`Write`/`Edit` — sin necesidad de un interruptor extra.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**El hilo principal se pone a trabajar por su cuenta → rechazo, y se le indica el camino.**

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | El matcher. Es una cadena de regex, no una lista |
| `allow_glance` | `bool` | `False` | Con `True`, si `tool_name == "Bash"` y [`is_ephemeral(command)`](#is-ephemeral) es verdadero, se deja pasar |

- **Va en `PreToolUse`**, el matcher es directamente `tools`.
- El hilo principal llama a una de esas cuatro herramientas → deny, y el motivo **indica el siguiente paso**: usa la herramienta `Agent` para delegar en un subagent,
  escribe en la tarea el objetivo y los criterios de aceptación, y exígele que escriba los productos largos en `.flower/artifacts/` y que en su respuesta solo dé rutas y conclusiones.
- Los subagents pasan siempre.

La diferencia con `whitelist_guard` está en **la redacción**: interceptan el mismo conjunto de herramientas, pero este dice «delega», que es lo pertinente.
Por eso un rol con `delegate_only=True` solo lleva este; instalar los dos haría que el modelo reciba dos indicaciones contradictorias.

El criterio de paso de `allow_glance=True` y el de «¿se recortará el resultado?» son **la misma función** ([`is_ephemeral`](#is-ephemeral)):
el conjunto que pasa debe ser igual al conjunto que caduca, cambiar un lado obliga a cambiar el otro.

### `spill_guard()` {#spill-guard}

```python
def spill_guard(
    workbench: Workbench,
    *,
    threshold: int = 4000,
    tools: str = BULKY,
    main_only: bool = False,
) -> HookMatcher
```

Los resultados de herramienta que superan el umbral se [vuelcan a disco](glossary.md#落盘) **en el acto**, dejando en el contexto solo un puntero de una línea —
no se espera a que el contexto se llene para comprimir después.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workbench` | `Workbench` | obligatorio, posicional | El directorio de volcado es `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | A partir de cuántos caracteres se vuelca |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | El matcher |
| `main_only` | `bool` | `False` | `False` (por defecto) = también se vuelcan los resultados de los subagents |

- **Va en `PostToolUse`**, devuelve
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <lo recortado>}}`.
- El nombre del archivo volcado son los primeros 16 caracteres del `sha256` del contenido + `.txt`, y en el contexto se sustituye por un puntero de una línea + **los primeros 400 caracteres**.
- `updatedToolOutput` **debe mantener la estructura de salida original de la herramienta**, así que solo se sustituyen los **campos de texto** demasiado largos del dict;
  **las listas no se tocan nunca** (dentro puede haber bloques de imagen). Si la estructura no cuadra se rechaza (el texto original se queda igual, sin error).
- **Leer el propio archivo volcado tiene que pasar sin más** — si no, «léelo con `Read`» es una frase vacía: el texto completo que se lee se vuelve a volcar, bucle infinito.
  Nos hemos topado con ello en la práctica: el modelo probó cinco formulaciones distintas para rodearlo.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Si se escribe algo en el [banco de trabajo](glossary.md#工作台), se refresca `INDEX.md`, y el siguiente agent sabe desde el arranque que existe.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workbench` | `Workbench` | obligatorio, posicional | Ámbito de la comprobación y objeto a refrescar |

**Va en `PostToolUse`**, matcher `"Write|Edit"`. Si `tool_input["file_path"]`, tras resolverse, cae dentro de
`workbench.root`, llama a `workbench.refresh()`. **Devuelve siempre `{}`** — no cambia nada, solo tiene efecto secundario.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Asigna a los subagents un git worktree independiente según el rol, para lograr el [aislamiento](glossary.md#隔离).

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | obligatorio, posicional | Tabla de roles, para comprobar si el `subagent_type` está marcado |
| `on_inject` | `Any` | `None` | Callback opcional, se llama como `on_inject(subagent_type, description)` |

**Va en `PreToolUse`**, matcher `"Agent"`. Solo inyecta si se cumplen tres condiciones a la vez: `tool_name == "Agent"`,
`tool_input` **no tiene ni `cwd` ni `isolation`**, y el rol correspondiente a `subagent_type` está marcado con `isolated()`.
Si se cumplen, devuelve `permissionDecision: "allow"` + `updatedInput` (poniendo `isolation` a `"worktree"`).

`isolation` y `cwd` son **mutuamente excluyentes** en la herramienta `Agent` — si el modelo ha indicado un `cwd`, se respeta.
«Aislar o no» es un **atributo del rol**, no un interruptor global ni una decisión que se tome en cada delegación; a un rol que no necesita aislamiento no se le añade ni un byte.

**Si activas el aislamiento tienes que sacar el [banco de trabajo](glossary.md#工作台) del repositorio.** Un agent aislado no puede escribir en el checkout compartido,
así que el banco de trabajo debe apuntar fuera del repositorio con `home=`. `starter_flow(isolate=True)` usa
`<ws>.parent/.flower-<ws.name>`, y `Runtime(workbench=True)` usa `<run_dir>/workbench` —
ambos están fuera del repositorio, **pero no son el mismo directorio**, no los mezcles.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Marca una definición de subagent como «necesita espacio de trabajo propio», y lee de vuelta esa marca.

| Función | Parámetro | Por defecto | Descripción |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | obligatorio | La definición a marcar. **Devuelve el mismo objeto** |
| | `flag: bool` | `True` | Posicional. `False` = quitar la marca |
| `wants_isolation` | `agent: AgentDefinition \| None` | obligatorio | Acepta `None`, devuelve `False` |

La marca es un atributo del lado Python, `_flower_isolate`, puesto con `object.__setattr__`, **no un campo del dataclass** —
el SDK serializa con `asdict()` y solo reconoce los campos declarados, así que esta marca no se filtra hacia el CLI (medido).

**El coste**: hacer `dataclasses.replace()` sobre un `AgentDefinition` pierde la marca, y el aislamiento deja de funcionar en silencio.

`worker(isolate=True)` internamente pasa por `isolated()`.

### `workbench_hooks()` {#workbench-hooks}

```python
def workbench_hooks(
    workbench: Workbench,
    *,
    delegate_only: bool = True,
    spill_threshold: int | None = 4000,
    agents: dict[str, AgentDefinition] | None = None,
    allow_glance: bool = False,
) -> dict[str, list[HookMatcher]]
```

Instala de una vez los hooks que necesita el banco de trabajo. Es lo que llama `Runtime._attempt`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workbench` | `Workbench` | obligatorio, posicional | Se pasa a `index_guard` y `spill_guard` |
| `delegate_only` | `bool` | `True` | Solo con `True` se instala `delegate_guard` |
| `spill_threshold` | `int \| None` | `4000` | Solo si es verdadero se instala `spill_guard` |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | Si **alguno** está marcado con `isolated()`, se añade `isolate_guard` |
| `allow_glance` | `bool` | `False` | Se pasa tal cual a `delegate_guard(allow_glance=)` |

Resultado:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  si hay roles marcados → se añade `isolate_guard(agents)`.
- `PostToolUse`: siempre `[index_guard(workbench)]`; si `spill_threshold` es verdadero → se añade
  `spill_guard(workbench, threshold=spill_threshold)`.
- **Las claves de evento con lista vacía se eliminan**, no se devuelve una list vacía.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Concatena** varios grupos de configuración de hooks por nombre de evento.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | variádico | Cualquier número de grupos. Los grupos `None` se saltan |

Usa `extend`, **no deduplica** — pasar el mismo guard dos veces lo instala dos veces. `Runtime` lo usa para fusionar `spec.hooks`,
`workbench_hooks(...)` y `whitelist_guard`.

---

## Banco de trabajo {#工作台}

Código fuente: [`flower/core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py)

### `Workbench` {#workbench}

```python
@dataclass
class Workbench:
    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
```

El directorio de trabajo donde se vuelca todo: tres subdirectorios + un índice. El índice **se inyecta en el system prompt**, así que el agent sabe en cada turno
qué tiene entre manos.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workspace` | `Path` | obligatorio, posicional | El espacio de trabajo. `__post_init__` lo resuelve |
| `dirname` | `str` | `".flower"` | Nombre del directorio del banco de trabajo, relativo a `workspace` |
| `max_index_entries` | `int` | `40` | **Solo afecta a `prompt_block()`**: cuántas entradas por categoría se listan como máximo en el fragmento inyectado en el system prompt; el resto se condensa en una línea «…y N más». `INDEX.md` no tiene ese límite, lista todo |
| `home` | `Path \| None` | `None` | Si se da, se usa como `root` e **ignora `dirname`**. Cuando no es `None` también se resuelve |

| Miembro | Firma | Descripción |
|---|---|---|
| `root` | `@property -> Path` | Si hay `home` se usa, si no `workspace / dirname` |
| `external` | `@property -> bool` | Si `root` está **fuera** de `workspace`. En modo aislado debería ser `True` |
| `scripts` | `@property -> Path` | `root / "scripts"`, scripts que se van a ejecutar una segunda vez |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, productos largos de más de 2000 caracteres |
| `notes` | `@property -> Path` | `root / "notes"`, decisiones clave, un archivo por decisión |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | La ruta que ve el modelo: relativa si está dentro del espacio de trabajo, absoluta si está fuera |
| `ensure` | `() -> Workbench` | Hace mkdir de los tres directorios y devuelve `self` (encadenable: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(ruta mostrada, descripción, bytes)`. `rglob("*")` recursivo, se salta los archivos que empiezan por `.` |
| `refresh` | `() -> str` | Reescribe `INDEX.md` y devuelve su contenido |
| `prompt_block` | `() -> str` | **El fragmento que se inyecta en el system prompt**. Corto a propósito: está en todos los turnos |

Formato de autodescripción de un script: un `# desc: 一句话` dentro de las primeras 8 líneas (también reconoce los comentarios `//` y `--`),
con degradación al primer comentario no vacío o a la primera línea del docstring (cortada a 100 caracteres).

Las tres reglas que inyecta `prompt_block()`:

1. Los scripts que se vayan a ejecutar una segunda vez van a `scripts/`, con `# desc:` en la primera línea.
2. Los productos de más de **2000 caracteres** van a `artifacts/`, y en la conversación solo se da la ruta y la conclusión.
3. Las decisiones clave van a `notes/`, un archivo por decisión.

Cuando `external=True`, `prompt_block()` añade además una frase: «accede a él con ruta absoluta».

**Los subagents no heredan el índice.** Va por el `system_prompt.append` a nivel de sesión, y un subagent tiene su propio
system prompt (medido: $0.2461). Por eso las dos reglas «los productos largos van a `artifacts/`» y «dónde está el banco de trabajo» tiene que retransmitirlas
el [coordinador](glossary.md#协调者) en el [pliego de tarea](glossary.md#任务书) — **ese es el único canal**, no es redundancia.
En `WORKER_RULES` **se omite a propósito**: la ruta real la genera `Workbench`, escribirla fija sería un error.

---

## Almacén de sesiones {#会话存储}

Código fuente: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Tres capas de herencia: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime` **usa siempre la más externa**, y las políticas de las tres capas se controlan con parámetros del constructor.

Cada capa hace una cosa: persistir, [recortar](glossary.md#裁剪) por volumen y valor, y [podar](glossary.md#剪除) según «es un error o no».
Tanto el recorte como la poda ocurren en **`load()`** (es decir, cuando el resume devuelve el historial al modelo), y el registro original en SQLite no se toca ni un byte.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implementa el protocolo `SessionStore` del SDK, con tres tablas: `entries` / `meta` / `summaries`.
La clave del store es `project_key/session_id[/subpath]` — **el transcript de un subagent se distingue por el subpath**.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `path` | `str \| Path` | obligatorio, posicional | Archivo de base de datos. La conexión usa `check_same_thread=False` |

| Método | Firma | Descripción |
|---|---|---|
| `append` | `async (key, entries) -> None` | Deduplicación idempotente por uuid (primero contra lo ya persistido, luego los duplicados dentro del lote). Al reproducir un lote entero **no avanza el mtime ni vuelve a plegar el summary**; solo el transcript principal (`subpath is None`) participa en el summary |
| `projects` | `() -> list[str]` | Los `project_key` que existen realmente en la base. **El SDK lo deriva del cwd; confírmalo con esto antes de consultar, no lo adivines** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **Síncrono, no lee el payload**, solo consulta una fila de meta. Para la «continuidad en la misma ruta»: hacer resume de una sesión inexistente no revienta hasta que arranca el subproceso |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | Cuánto contexto vio realmente el modelo en el último turno; devuelve `0` si no lo encuentra. Solo recorre hacia atrás las últimas `scan` entradas; suma las tres partes `input + cache_read + cache_creation` (mirar solo `input_tokens` subestima gravemente) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | Ordenado por seq; devuelve `None` si no hay filas |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | Solo el transcript principal |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | Lista los resúmenes de sesión |
| `delete` | `async (key) -> None` | Al borrar el transcript principal **borra en cascada los de los subagents**, para no dejar huérfanos |
| `list_subkeys` | `async (key) -> list[str]` | Lista los sub-transcripts de esa sesión |
| `close` | `() -> None` | Cierra la conexión |

El `_next_mtime` interno garantiza **monotonía estricta** — `list_sessions` y el sidecar de summary comparten ese reloj;
si no, el camino rápido de staleness del SDK se equivoca.

### `TrimPolicy` {#trimpolicy}

```python
@dataclass
class TrimPolicy:
    keep_recent: int = 20
    min_chars: int = 2000
    spill_dirname: str = ".flower/spill"
    enabled: bool = True
```

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `keep_recent` | `int` | `20` | Los N `tool_result` más recientes conservan el texto original |
| `min_chars` | `int` | `2000` | Los resultados cortos no merecen recorte |
| `spill_dirname` | `str` | `".flower/spill"` | **Relativo a `workspace`, tiene que estar dentro del espacio de trabajo** — si no, el `Read` del agent no lo alcanza |
| `enabled` | `bool` | `True` | Con `Runtime(trim=False)` esto es `False` |

| Método | Firma | Descripción |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | Genera la línea de puntero que sustituye al cuerpo |

**Los dos directorios de volcado no son el mismo.** `spill_guard` escribe en `<workbench.root>/spill/` (puede estar fuera del espacio de trabajo);
`TrimPolicy.spill_dirname` escribe en `<workspace>/.flower/spill/` (**tiene que estar dentro del espacio de trabajo**).
Corresponden respectivamente a «recortar en el acto» y «recortar en el resume»; que sean directorios distintos es intencionado, no los unifiques.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Política de caducidad de los resultados de [comandos efímeros](glossary.md#一次性命令).

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `enabled` | `bool` | `True` | Si se desactiva, no se marca nada como caducado |
| `keep_recent` | `int` | `6` | Los N más recientes quedan exentos. **Mucho menor que el 20 de `TrimPolicy`** |
| `max_chars` | `int` | `2000` | Por encima se salta, y lo archiva `TrimPolicy` |
| `text` | `str` | ver la firma | Texto de reemplazo, con los marcadores `{cmd}` y `{age}` |

| Método | Firma | Descripción |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | Aplica `text` para generar el cuerpo de reemplazo |

**Solo actúa sobre los resultados de la herramienta `Bash`**, y el comando tiene que coincidir con la whitelist de comandos efímeros. **`Read` no entra aquí**:
el contenido de un archivo no se desvirtúa con el paso del tiempo hasta el punto de inducir a error. El contenido caducado **no se vuelca a disco**, se tira directamente.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Determina si un comando Bash es un [comando efímero](glossary.md#一次性命令).
**La decisión de paso de `delegate_guard` y la de caducidad del recorte comparten esta misma función** — el conjunto de comandos que el coordinador puede ejecutar por su cuenta
debe ser igual al conjunto de resultados que se marcarán como caducados. Si dejas pasar sin recortar, un `git status` caducado ocupa el contexto para siempre y además induce a error;
si recortas sin dejar pasar, el coordinador delega un subagent para un `ls`, cambiando 4.3k de coste de arranque por unas decenas de caracteres.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `cmd` | `str` | obligatorio, posicional | La línea de comando completa |

Orden de decisión:

1. Vacío / solo espacios → `False`.
2. Sustitución de comandos (`$(`, comillas invertidas, `<(`, `>(`) o una construcción que «cambia el estado» → `False`.
3. Tras quitar las redirecciones seguras (`2>&1`, `&> /dev/null` y similares), si sigue conteniendo `>` o `<` → `False`.
4. Tras quitar `&&` / `||` / `;` / `|`, si queda un `&` suelto (ejecución en segundo plano) → `False`.
5. Se parte por `&&` / `||` / `;` / `|`, y **cada segmento tiene que estar en la whitelist**.

Grandes categorías de verbos en la whitelist: subcomandos de `git` de solo lectura (`status` `diff` `log` `show` `branch` `rev-parse`, etc.),
información de directorios y sistema (`ls` `pwd` `df` `du` `date` `whoami` `env`, etc.), procesos y contenedores
(`ps` `top` `lsof` `docker ps` `kubectl get`, etc.), ver archivos (`cat` `head` `tail` `wc` `stat` `find` `tree`),
buscar rutas (`which` `whereis` `command -v` `type`), procesamiento de texto (`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff`, etc.).

Aunque el verbo esté en la whitelist, estas construcciones se bloquean igualmente: `xargs`, `exec`, `eval`, `source`, `tee`,
`find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` y `print >` dentro de `awk`,
`git branch -D/-d/-m`, `git * --force/--hard/--prune`.

La primera versión rechazaba de plano todos los comandos compuestos, y **en la práctica dejó el glance completamente inútil** (los tres intentos del coordinador fueron bloqueados),
así que se cambió a la comprobación por segmentos.

### `TrimmingSessionStore` {#trimmingsessionstore}

```python
class TrimmingSessionStore(SqliteSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `path` | `str \| Path` | obligatorio | Archivo de base de datos |
| `workspace` | `str \| Path` | obligatorio | Base para el directorio de volcado |
| `policy` | `TrimPolicy \| None` | `None` | Si no se da, se usa el `TrimPolicy()` por defecto |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | Si no se da, se usa el `EphemeralPolicy()` por defecto |

Atributos públicos: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Orden de `load()`: `super().load()` → limpiar `last_report` → si `ephemeral.enabled`, `expire()` →
si `policy.enabled`, `trim()`. **Con `enabled=False` ese paso se salta entero.**

| Método | Descripción |
|---|---|
| `expire(entries)` | A los resultados `Bash` con caducidad ya vencida **solo les cambia el cuerpo, el bloque se conserva**. El comando se busca en el `tool_use` del mensaje assistant anterior; se saltan los `isCompactSummary` / `isMeta`; los que superan `max_chars` se saltan (los archiva `trim`); los últimos `keep_recent` quedan exentos. Escribe `last_report["expired"]` |
| `trim(entries)` | El cuerpo de los `tool_result` con `>= min_chars` se vuelca a `<workspace>/<spill_dirname>/<primeros 16 del sha256>.txt` y el contenido del bloque se sustituye por un puntero; los últimos `keep_recent` quedan exentos. Escribe `cleared` / `kept` / `chars_saved` en `last_report` |

**Solo recorta texto plano**: los bloques `image` / `document` se dejan tal cual.

**Dos líneas rojas estructurales**: el **bloque `tool_result` tiene que seguir ahí**, solo se puede cambiar su content (si falta uno, es
«Missing Tool Result Block»); las entradas `isCompactSummary` no se tocan.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Renderiza `store.last_report` como una línea en chino, para el log de la UI.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | obligatorio, posicional | También acepta la subclase `PruningSessionStore` |

Tres salidas posibles: sin acción → `"未裁剪"`; solo caducidades → `"N 个时效性结果标记为过期"`;
en el resto de casos `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, donde X = `chars_saved // 4`.

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    keep_denials: int = 1
```

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Elimina los mensajes de error de API sintéticos (residuos de desconexión) |
| `neutralize_interrupts` | `bool` | `True` | Sustituye por una nota neutra los `tool_result` que quedaron colgando tras una interrupción |
| `interrupt_text` | `str` | ver la firma | El texto de la nota neutra |
| `keep_denials` | `int` | `1` | Conserva los N rechazos de llamada más recientes |

El motivo de `keep_denials`: una llamada rechazada nunca se ejecutó, su resultado no lleva información, pero ocupa lo suyo (medido: 273 caracteres en un caso =
93 caracteres de texto de rechazo + 180 caracteres del **comando muerto literal**). Más importante aún: **induce a error** — medido, tras leer varios
«no uses Bash directamente», el coordinador dejó de intentar incluso los `git status` permitidos, y aprendió indefensión adquirida.
**Por defecto se conserva 1 y no 0**: el rechazo más reciente evita que el modelo reintente una y otra vez el mismo comando bloqueado dentro del mismo turno.

### `PruningSessionStore` {#pruningsessionstore}

```python
class PruningSessionStore(TrimmingSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        prune: PrunePolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

**El store por defecto de `Runtime`.**

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `path` | `str \| Path` | obligatorio | Archivo de base de datos |
| `workspace` | `str \| Path` | obligatorio | Base para el directorio de volcado |
| `policy` | `TrimPolicy \| None` | `None` | Política de recorte |
| `prune` | `PrunePolicy \| None` | `None` | Política de poda |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | Política de caducidad |

Además de los de la clase padre, expone tres atributos públicos: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (primero `expire` + `trim`) → `self.prune(entries)`. `prune` hace tres cosas:

1. **Elimina las llamadas rechazadas más antiguas**: se detectan por la marca estructural del harness `toolDenialKind == "permission-rule"`
   (más fiable que hacer match contra el texto del rechazo), se conservan las últimas `keep_denials` y del resto se eliminan tanto el bloque `tool_use`
   **como** el `tool_result`. Cuando un mismo mensaje assistant tiene varios `tool_use`, **solo se eliminan los afectados**, si no acaba en
   «Missing Tool Result Block»; los bloques de texto y de thinking se conservan.
2. **Elimina los mensajes de error de API sintéticos.** En SQLite se conservan tal cual, simplemente no se vuelven a alimentar al modelo.
3. **Sustituye por una nota neutra los `tool_result` colgando tras una interrupción** — solo cambia el cuerpo, no elimina la entrada.

**La única línea roja estructural**: el transcript es una cadena simple por `parentUuid`, así que al eliminar una entrada hay que reenganchar sus hijos al ancestro vivo más cercano.
El `entries` del `relink` interno **tiene que ser la lista completa (incluidas las que se van a eliminar)**, el filtrado lo hace él mismo —
si quien llama las quita antes de pasarlas, la cadena se rompe ahí y se pierde todo el historial anterior (**ya pisado: no se manifiesta cuando las entradas eliminadas están al final,
pero revienta si están en medio**).

**El orden de parámetros difiere del de la clase padre**: la padre es `(path, workspace, policy, ephemeral)`, la hija es
`(path, workspace, policy, prune, ephemeral)` — **el cuarto posicional pasa de `ephemeral` a `prune`**,
y pasarlo por posición desalinea en silencio. Pásalos siempre por palabra clave.

---

## Resiliencia {#韧性}

Código fuente: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

Cuando se cae la red, esperar colgado en vez de salir con error. Cuatro exportaciones: un dataclass de política + tres funciones de sondeo utilizables por separado.

### `Resilience` {#resilience}

```python
@dataclass
class Resilience:
    enabled: bool = True
    max_attempts: int = 6
    base_delay: float = 4.0
    max_delay: float = 120.0
    probe_timeout: float = 5.0
    probe_interval: float = 15.0
    max_offline_wait: float = 3600.0
    retry_unknown: bool = True
    resume_prompt: str = "上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"
```

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `enabled` | `bool` | `True` | Si se desactiva, ningún fallo se reintenta |
| `max_attempts` | `int` | `6` | **Incluye el primer intento** |
| `base_delay` | `float` | `4.0` | Base del backoff, en segundos |
| `max_delay` | `float` | `120.0` | Techo del backoff, en segundos |
| `probe_timeout` | `float` | `5.0` | Timeout de una sonda |
| `probe_interval` | `float` | `15.0` | Cuánto se espera entre dos sondas |
| `max_offline_wait` | `float` | `3600.0` | Cuánto se espera colgado como máximo, por defecto 1 hora |
| `retry_unknown` | `bool` | `True` | Si se reintentan los errores no clasificables |
| `resume_prompt` | `str` | ver la firma | Lo que se dice al continuar. **Deliberadamente sin ningún detalle del error** — el modelo necesita saber «te interrumpieron, sigue», no si fue un `ENOTFOUND` o un 503 |

| Método | Firma | Descripción |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` multiplicado por `0.75 + random()*0.5` (jitter de ±25%) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, o `kind == "unknown"` con `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | Espera colgado a que vuelva la red. Devuelve `True` si vuelve, `False` si se supera `max_offline_wait`. `notify` es un callback `(str) -> None`, se emite una vez **la primera vez que no hay alcance** y otra **al recuperarse** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Clasifica el texto de un error en tres categorías: `"transient"` / `"fatal"` / `"unknown"`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `text` | `str \| None` | obligatorio, posicional | El mensaje de error original. Si está vacío devuelve `"unknown"` |

**Primero se comprueba fatal y luego transient** — el texto de un 401 y similares suele llevar la palabra `connection`, y con el orden invertido se espera eternamente.

| Categoría | Qué la dispara |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

El host y el puerto a sondear, siguiendo `ANTHROPIC_BASE_URL`, con `https://api.anthropic.com` por defecto;
el puerto por defecto es `80` (http) o `443`.

**Si usas una pasarela propia hay que sondearla a ella** — que `api.anthropic.com` responda no dice nada sobre la pasarela.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `host` | `str` | obligatorio, posicional | Nombre de host |
| `port` | `int` | obligatorio, posicional | Puerto |
| `timeout` | `float` | `5.0` | Segundos |

**Solo hace DNS (`getaddrinfo`) + handshake TCP**: no envía HTTP, no lleva credenciales, **no cuesta dinero**. Cualquier excepción cuenta como inalcanzable.

---

## Eventos e interacción {#事件与交互}

Código fuente: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

Un [evento](glossary.md#事件) es la estructura estable a la que se aplana el flujo de mensajes del SDK. **La [capa de interacción](glossary.md#交互层) solo conoce
`Event`, no importa ningún tipo del SDK** — esa es la frontera que permite cambiar de UI sin tocar el núcleo. Ver [Cambiar la capa de interacción](../guide/interaction.md).

### `Event` {#event}

```python
@dataclass
class Event:
    kind: EventKind
    text: str = ""
    tool: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def __str__(self) -> str: ...
```

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `kind` | `EventKind` | obligatorio | Ver tabla siguiente |
| `text` | `str` | `""` | Cuerpo |
| `tool` | `str` | `""` | Nombre de la herramienta, solo en `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | Información adicional estructurada |
| `raw` | `Any` | `None` | Objeto original del SDK, para cuando quieras escarbar |

`__str__`: para `tool_call` es `f"[{tool}] {text}"`, en otro caso `text`, y si `text` está vacío, `f"<{kind}>"`.
Así que `print(ev)` ya es legible.

`EventKind` tiene **15** valores en total:

| kind | Quién lo emite | Descripción |
|---|---|---|
| `text` | `normalize` | Cuerpo del assistant |
| `thinking` | `normalize` | Bloque de pensamiento |
| `tool_call` | `normalize` | Llamada a herramienta. `text` es un resumen de `file_path` / `command` / `pattern`, cortado a 200 caracteres |
| `tool_result` | `normalize` | Resultado de herramienta. `text` cortado a 500 caracteres, payload trae `tool_use_id` / `is_error` |
| `task` | `normalize` | Los tres mensajes Task, `text` es el nombre de la clase del mensaje |
| `system` | `normalize` | El resto de mensajes de sistema, `text` es el subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, payload trae `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | Mensaje de error de API sintético, payload trae `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **El cuerpo es la entrada, no la salida del modelo**, por eso no entra en `StepResult.text` |
| `unknown` | `normalize` | Lo que no se reconoce |
| `retry` | `Runtime` | Aviso de reintento |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | En el payload, `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | Pregunta, **y también transporta "lo que la persona dice por iniciativa propia"** |

**Los últimos cuatro no los produce `normalize()`.**

El `payload` de todos los eventos de assistant / user lleva:

| Clave | Tipo | Descripción |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | Solo cuando `subagent` es verdadero |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **Es la única fuente del criterio de [handoff](glossary.md#换代)**, y también el número que más merece verse en una ejecución long-horizon |

**El kind `ask` transporta a la vez "una pregunta" y "lo que la persona dice por iniciativa propia".** En el segundo caso `payload["kind"] == "mail"`,
y **no hay `options` / `remaining`**. La UI debe mirar primero `payload.get("kind")` y luego decidir cómo renderizar;
si no, dejará colgada una frase como si fuese una pregunta pendiente de responder.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Aplana un mensaje del SDK en 0 a N `Event`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `message` | `Any` | obligatorio, posicional | Cualquier objeto de mensaje del SDK |

Ramas clave:

- **Mensaje de error de API sintético** (`isApiErrorMessage=True` o `model == "<synthetic>"`) → un único
  `Event("error", payload={"synthetic": True})`. **Esto es deliberado** — si no, el texto de la desconexión se tomaría como cuerpo
  y entraría en `StepResult.text`, para luego pasarse al paso siguiente.
- `AssistantMessage` → `kind="text"`; `UserMessage` → `kind="prompt"`.
- `ToolUseBlock` → `Event("tool_call", text=<resumen>, tool=block.name, payload={"id", "input"})`.
- `ToolResultBlock` → `Event("tool_result", text=content[:500], payload={"tool_use_id", "is_error"})`.
- `ResultMessage` → `Event("result", text=subtype, payload={"session_id", "cost_usd", "num_turns", "is_error"})`.
- `compact_boundary` / `microcompact_boundary` → `Event("reset", payload={"trigger", "pre_tokens", "post_tokens", "micro", "subtype"})`.

### `Ask` {#ask}

```python
@dataclass
class Ask:
    id: str
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"
    answer: str = ""
```

Una pregunta dirigida a la persona.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `id` | `str` | obligatorio | Se usa para localizarla al responder |
| `question` | `str` | obligatorio | Texto de la pregunta |
| `options` | `list[str]` | `[]` | Opciones. La persona también puede no elegir ninguna y escribir lo suyo |
| `asked_at` | `float` | `time.time()` | Momento de la pregunta |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | Texto de la respuesta |

| Miembro | Firma | Descripción |
|---|---|---|
| `waited_s` | `@property -> float` | Cuánto lleva esperando |
| `event` | `(remaining: int = 0) -> Event` | Produce `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

### `HumanChannel` {#humanchannel}

```python
HumanChannel(
    *,
    on_event: Callable[[Event], None] | None = None,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    log_path: str | Path | None = None,
    amend_path: str | Path | None = None,
    over_budget_text: str = OVER_BUDGET,
    timeout_text: str = TIMEOUT,
    declined_text: str = DECLINED,
)
```

Un **servidor MCP dentro del proceso** (dos herramientas) más un conjunto de métodos para la UI. Del lado del modelo solo se ven
`mcp__human__ask` y `mcp__human__inbox`. Todos los parámetros del constructor son keyword-only.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | La salida del modo **push**. Si lo das, `Workflow.run` ya no cablea nada |
| `max_asks` | `int \| None` | `None` | **Sin límite de veces**. Con un número es una cuota dura, `0` = prohibido preguntar (totalmente automático / CI). Al pasarse, la herramienta **rechaza directamente, sin bloquear** |
| `timeout_s` | `float \| None` | `1800.0` | 30 minutos. `None` = esperar para siempre; **`<= 0` = no esperar, todas las preguntas quedan en nada de inmediato** |
| `log_path` | `str \| Path \| None` | `None` | Las preguntas y respuestas se **añaden** a disco, no ocupan contexto |
| `amend_path` | `str \| Path \| None` | `None` | Lo que la persona dice durante la ejecución se añade a este fichero (normalmente el propio brief). **Lo que no se escribe a disco no sobrevive al límite del paso** — el paso siguiente es una sesión nueva que solo lee el artefacto congelado |
| `over_budget_text` | `str` | constante del módulo | Lo que se le devuelve al modelo al pasarse de cuota |
| `timeout_text` | `str` | constante del módulo | Lo que se le devuelve al modelo al agotarse el tiempo |
| `declined_text` | `str` | constante del módulo | Lo que se le devuelve al modelo cuando se omite la pregunta |

Atributos públicos: los ocho con el mismo nombre que los parámetros del constructor, más `asks: list[Ask]`, `mail: list[Mail]` y
`ui_errors: list[str]` (**aquí se recogen las excepciones lanzadas por los callbacks de la UI, sin interrumpir la ejecución**).

| Miembro | Firma | Descripción |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | Se pasa tal cual a `AgentSpec.mcp_servers`. **El nombre de la clave debe coincidir con el del server**, por eso lo entrega él mismo |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | Se queda esperando a la persona. **Nunca lanza excepciones salvo `CancelledError`** — que nadie responda también es una respuesta, se distingue con `ask.state` |
| `send` | `(text: str) -> Mail \| None` | La persona dice algo por iniciativa propia. **Se puede llamar desde cualquier hilo**. No interrumpe al agente; internamente llama a `amend()` |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | Añade a `amend_path`. Devuelve si realmente escribió (sin ruta configurada, texto vacío o `OSError` dan `False`) |
| `pending_mail` | `() -> list[Mail]` | El mail que aún no se ha recogido |
| `remaining` | `@property -> int` | Cuántas preguntas quedan. **Con `max_asks=None` devuelve `-1`**, ni 0 ni infinito |
| `pending` | `() -> list[Ask]` | Las preguntas actualmente colgadas esperando respuesta |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | Para el modo **pull**. Devuelve `None` al agotarse el tiempo; si se cancela, lanza |
| `answer` | `(ask_id: str, text: str) -> bool` | Responder. `False` = esa pregunta ya no está esperando (timeout / ya respondida) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | Omitir, dejar que el modelo juzgue por su cuenta |
| `transcript` | `() -> str` | El markdown del registro de preguntas y respuestas |

**Elige una de las dos formas de recoger**: **push** — construir `HumanChannel(on_event=...)`; **pull** — `await channel.next_ask()`.
`Workflow.run` solo cablea automáticamente cuando `channel.on_event is None`, así que si lo pasas tú no se sobrescribe.

**Entre hilos**: `answer` / `decline` / `send` van internamente por `loop.call_soon_threadsafe`,
así que llamarlos directamente desde el backend web o el hilo de entrada de la TUI es lo normal.

Los tres "0 / None" tienen semánticas distintas, no los mezcles: `max_asks=None` = sin límite, `max_asks=0` = prohibido preguntar;
`timeout_s=None` = esperar para siempre, `timeout_s<=0` = timeout inmediato; `remaining` es `-1` cuando `max_asks=None`.

`Mail`, que no se exporta pero aparece en valores de retorno, es un dataclass con los campos `id` / `text` / `sent_at` / `taken`.

---

## Linaje {#血缘}

Código fuente: [`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

Registra entre procesos "qué paso usó qué sesión"; la [continuidad](glossary.md#接续) se apoya en él para encontrar hasta dónde se llegó la vez anterior.
El fichero es `<run_dir>/lineage.json`.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `path` | `Path` | obligatorio | Ruta del fichero de linaje |
| `workspace` | `Path` | obligatorio | Espacio de trabajo. `__post_init__` hace resolve |
| `steps` | `dict[str, str]` | `{}` | Nombre del paso → `session_id` |
| `woke` | `int` | `0` | Cuántas veces se ha despertado |

| Miembro | Firma | Descripción |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | Lee `<run_dir>/lineage.json`. **Si el fichero no existe, no se puede leer o el campo `workspace` no cuadra, devuelve uno vacío sin dar error** |
| `remember` | `(step: str, session_id: str) -> None` | Recuerda el mapeo y **lo escribe a disco de inmediato**. Con step o sid vacíos vuelve directamente |
| `bump` | `() -> int` | Suma 1 al contador de despertares, escribe a disco y devuelve el nuevo valor (la primera ejecución es `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **Mueve** el fichero de linaje más `extra` a `<into>/<YYYYmmdd-HHMMSS>/` y pone `steps` / `woke` a cero. **Mueve, no borra** |

La escritura a disco usa el reemplazo atómico `tmp.replace(path)`; los `OSError` se tragan en silencio — un fallo de escritura no debería llevarse por delante la ejecución.

**`workspace` es la guarda**: el `project_key` del SDK se deriva de la ruta del espacio de trabajo, y si el directorio se copia a otro sitio los `session_id` antiguos no se encuentran,
así que si la ruta no cuadra se hace como si no hubiera nada.

Cuando `Workflow.run` carga el linaje, valida cada registro uno a uno con `runtime.has_session(sid)` para ver si sigue en la base, y solo usa los vivos —
el fichero de linaje puede sobrevivir a `sessions.db`.

---

## Ejemplos mínimos ejecutables {#示例}

Los cinco fragmentos se pueden ejecutar tal cual. Requisito: tener instalado `claude-agent-sdk` y disponible `ANTHROPIC_API_KEY` o `ANTHROPIC_AUTH_TOKEN`
(si no, `Runtime(...)` lanza `RuntimeError` ya en la construcción).

### Un agente ejecutando un paso {#示例-单-agent}

Esqueleto mínimo: declarar un `AgentSpec`, crear un `Runtime`, `await rt.run(...)`, leer el `StepResult`.

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime

spec = AgentSpec(
    name="reader",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob", "Grep"],
    max_turns=4,
)


async def main() -> None:
    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        r = await rt.run(spec, "读 README.md,一句话说它是干什么的。",
                         on_event=lambda ev: print(ev))
        print(f"ok={r.ok} session={r.session_id} ${r.cost_usd:.4f} {r.duration_s}s")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

Los parámetros de `Runtime` son **todos keyword-only**; en `rt.run()`, `spec` y `prompt` son posicionales y el resto keyword-only.
`AgentSpec` trae por defecto `allowed_tools=["Read", "Glob", "Grep"]` y `delegate_only=False`,
así que `Runtime` le instala automáticamente [`whitelist_guard`](#whitelist-guard), que bloquea `Bash`/`Write`/`Edit`/`NotebookEdit`.

### Coordinador + worker {#示例-协调}

Un [coordinador](glossary.md#协调者) que no toca nada con un [worker](glossary.md#执行者) que hace el trabajo.
Esta es la primera capa de ahorro de contexto de flower.

```python
import asyncio
from pathlib import Path

from flower import Runtime, coordinator, worker


async def main() -> None:
    analyst = worker(
        "分析文件内容:统计、查找、比对。要真读文件、跑命令的活派给它。",
        "你负责在 data/ 下做文本分析。用命令行完成,不要手工估算。",
        tools=["Read", "Write", "Bash", "Glob", "Grep"],
    )
    boss = coordinator(
        "主控",
        "目标:摸清 data/ 下几个文件的规模。做完给一句话结论。",
        {"分析员": analyst},
        max_turns=14,
        max_budget_usd=1.5,
    )

    # workbench=True es obligatorio: delegate_guard va colgado de workbench_hooks,
    # sin abrir el workbench, el Bash/Write del coordinador no tiene ningún hook que lo pare.
    rt = Runtime(workspace=Path("."), run_dir="runs", workbench=True)
    try:
        r = await rt.run(boss, "统计 data/ 下每个 .txt 的行数和总字符数,告诉我哪个最大。",
                         on_event=lambda ev: None)
        print(f"ok={r.ok} turns={r.num_turns} ${r.cost_usd:.4f}")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

Los dos primeros parámetros de `worker()` son posicionales: `description` (lo que usa el coordinador para elegir) y `prompt` (su system prompt,
al que se le concatena automáticamente `WORKER_RULES`). Los tres primeros de `coordinator()` son posicionales: `name`, `instructions`, `workers`.

### Escribir tu propio Workflow {#示例-workflow}

Dos pasos, donde el segundo inyecta el resultado del primero en su propio prompt — barato, aislado, sin compartir sesión.

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([
        # Sesión nueva: solo consume lo que hay en el prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Sesión nueva + resultado del paso anterior inyectado en el prompt (barato, evita contaminación)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Si quieres seguir hablando en la misma sesión, escribe resume_from="造句"; para bifurcar, añade fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (cuando no se da reduce)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # con on_fail="stop", en qué paso falló


asyncio.run(main())
```

Los tres primeros campos de `Step` (`name` / `spec` / `prompt`) son posicionales, y el `steps` de `Workflow` también.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` posicional, los dos callbacks keyword-only.
**Ojo con que `continuous=True` es el valor por defecto**: al ejecutar por segunda vez con el mismo `run_dir` y el mismo `workspace`,
incluso los pasos con `resume_from=None` seguirán hablando en la sesión de la vez anterior.

### Añadir una guarda de objetivo {#示例-目标}

Primero dejas que el [juez](glossary.md#判定者) fije el objetivo y la lista de criterios, y luego haces que el paso de trabajo se someta al veredicto —
si no pasa, se vuelve a empezar con la retroalimentación, hasta tres rondas.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = totalmente automático: todas las preguntas quedan en nada de inmediato, sin fingir que se espera a nadie
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds es el **número total de rondas**: rounds=3 → retries=2 → como mucho tres rondas de trabajo
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # El prompt de goal_step lee ctx["确认需求"] (valor por defecto de brief_key).
        # Sin clarify_step hay que rellenarlo a mano, si no solo verá "(没有确认书)".
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY: objeto Goal
    print(ctx["_verdict"])     # VERDICT_KEY: último Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY: cuántas rondas se corrieron
    print(ctx.get("_aborted")) # Motivo del StepAbort (cuando es inalcanzable y nadie responde)


asyncio.run(main())
```

`with_goal` solo sustituye `gate` / `on_reject` / `retries`; el resto de campos se arrastran tal cual con `dataclasses.replace`.
El juez es una **sesión independiente**: dentro de `gate` se llama por separado a `rt.run(judger, ..., step_name=f"{label}#{轮次}")`,
con `resume` siempre en `None`.

### Cambiar la capa de interacción {#示例-交互层}

Para pasar del terminal a web / TUI / HTTP solo hay que cambiar dos cosas: la función que renderiza los `Event` y la corrutina que recoge las preguntas.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Renderiza el Event en tu propia UI — es lo único que hay que cambiar."""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ handoff/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ retry: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # Los kind == "ask" que no son mail los gestiona el answerer de abajo (modo pull)


async def answerer(ch: HumanChannel) -> None:
    """Recogida de preguntas en modo pull. Al pasar a backend web / servicio HTTP, esta corrutina es lo único que cambia."""
    while True:
        ask = await ch.next_ask()          # sin timeout, espera indefinidamente
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # o ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime usa el workbench que el propio workflow ya ha creado — no montes otro aparte
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push y pull: **elige uno**. Push es construir `HumanChannel(on_event=...)`, pull es `await channel.next_ask()`.
`Workflow.run` solo cablea automáticamente cuando `channel.on_event is None`, así que si pasas tú `on_event` no se sobrescribe.
`answer()` / `decline()` / `send()` / `interrupt()` **se pueden llamar todos desde otro hilo**.

---

## Trampas y errores frecuentes {#陷阱}

Ordenados por el momento en que te los encuentras, no por módulo. Cada uno tiene su origen medido.

### Montaje {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = el hilo principal sin ni un muro.**
   `delegate_guard` solo se instala si hay workbench, y `whitelist_guard` se salta por `delegate_only=True`.
   Si usas coordinador, abre el workbench. Ver [Runtime](#runtime).
2. **Hay dos ubicaciones de workbench, no las mezcles.** `Runtime(workbench=True)` cae en `<run_dir>/workbench`;
   `Workbench(ws)` está por defecto en `<ws>/.flower`. Si montas tú mismo `brief_path`, hazlo según la segunda,
   porque **el brief se escribe en el directorio A, el índice inyectado escanea el directorio B, y no salta ningún error**.
   Lo correcto: que el workflow haga su propio `Workbench(...).ensure()` y lo cuelgue de `Workflow.workbench`,
   y luego entregar **ese mismo objeto** a `Runtime(workbench=wb)`.
3. **`allowed_tools` no es una lista blanca excluyente, es una lista de exención de aprobación.** El modelo igualmente puede invocar herramientas que no estén ahí.
   El "no tiene herramientas de escritura" de `clarify()` / `judge()` se sostiene sobre el hook [`whitelist_guard`](#whitelist-guard).
   Y `coordinator()` trae por defecto `permission_mode="acceptEdits"` — quien pase ese valor a
   `clarify()` / `judge()` se queda sin la protección.
4. **`disallowed_tools` es a nivel de sesión**, y prohíbe también las herramientas homónimas de los subagentes.
5. **El índice del workbench no llega a los subagentes.** El "las salidas largas van a `artifacts/`" tiene que reformularlo el coordinador en el task brief;
   ese es el único canal.
6. **`Runtime(...)` lanza `RuntimeError` ya en la fase de construcción si no hay credenciales**, no al llegar a `run()`.
7. **`Runtime.run_id` debe ser único por instancia.** `manifest.json` deduplica por el campo `run`, y si dos ids chocan,
   el que escribe después borra las líneas del otro tomándolas por "lo que yo mismo escribí la vez pasada".

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` es el valor por defecto**, y `resume_from=None` no significa "sesión totalmente nueva".
   Si quieres abrir una nueva cada vez, pon explícitamente `continuous=False`. **Cambiar el nombre de un paso equivale a romper el linaje.**
9. **`with_goal(rounds=N)` es el número total de rondas, no rondas adicionales**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` no escribe `ctx[step.name]`** — un `lambda ctx: ctx["某步"]` aguas abajo dará `KeyError`.
    Si quieres seguir adelante con un resultado incompleto, usa `on_fail="continue"`.
11. **Un `resume_from` que apunte a un paso no ejecutado o fallido lanza `ValueError`**, no se salta en silencio.
12. **`Step.reduce` tiene que ser una función síncrona; `gate` / `when` / `on_reject` pueden ser async.**
13. **`fork=True` sin `resume` no hace nada y no avisa.** `Workflow` nunca pasa `resume_at`;
    para retroceder por mensajes hay que llamar directamente a `Runtime.run`.
14. **Si conduces `Runtime` tú mismo, hay que quitar `on_session` antes del gate**, o la sesión del juez acabará escrita en el linaje
    del paso de trabajo. `Workflow` lo garantiza con `try/finally`.
15. **`step_name` determina la clave en el manifest y en el linaje.** `Workflow` añade sufijos `#retryN` / `#roundN`,
    y el juez añade `#轮次` — **los nombres con sufijo no entran en el linaje entre procesos**, y esa es precisamente una de las formas en que se implementa el "el juez siempre es una sesión nueva".

### Roles {#陷阱-角色}

16. **`clarify(max_turns=<número pequeño>)` convierte el "preguntar sin límite de veces" en papel mojado** — cada pregunta es un turno.
17. **`goal_step()` no tiene parámetro formal `can_run`**, solo se puede pasar `can_run=True` por `**spec_kw`.
    Si no lo pasas, el juez que fija el objetivo no tiene `Bash` y no puede cumplir la regla de `JUDGE_RULES` de "primero entérate bien de en qué entorno estás".
18. **`judge(can_run=True)` permite al juez modificar el espacio de trabajo** — `whitelist_guard` se deriva de `allowed_tools`,
    y si le das `Bash` deja pasar `Bash` (sigue bloqueando `Write`/`Edit`, pero `Bash` por sí mismo puede escribir ficheros). Si quieres neutralidad absoluta, no lo actives.
19. **`worker(isolate=True)` exige que el workspace sea un repositorio git**, si no la herramienta `Agent` da directamente
    `"not in a git repository"`, sin degradación silenciosa. Además, la marca de aislamiento es un atributo de Python,
    y **hacer `dataclasses.replace()` sobre un `AgentDefinition` la pierde**.
20. **Al construir `AgentDefinition` directamente, los parámetros van en camelCase**: `maxTurns`, `permissionMode`.
    `worker()` ya hace la conversión por ti.

### Handoff y contexto {#陷阱-换代}

21. **Con el handoff activado, el auto-compact se desactiva a la fuerza, sin red de seguridad.** Por eso el paso que escribe el handoff document debe tener una vía de degradación.
    Si quieres conservar el auto-compact, pasa explícitamente `AgentSpec.compact`.
22. **Un `HandoffPolicy.window` demasiado pequeño provoca handoffs infinitos y quema dinero.** La única barrera es `max_generations=8`.
    Por el otro lado, **`default_window()` devuelve `1_000_000` también cuando ninguna de las dos variables de entorno está definida** —
    si el valor queda alto, `is_overflow()` lo recoge (se convierte en un handoff degradado), no es un error duro, pero el handoff de esa generación es degradado.
23. **Sin workbench, el handoff no se escribe a disco.** El documento se sigue entregando al sucesor por el prompt, pero después nadie puede consultarlo.

### Almacenamiento {#陷阱-存储}

24. **`Runtime(trim=False)` (el valor por defecto) no significa "no se limpia nada".** El store es siempre `PruningSessionStore`;
    `trim=False` solo desactiva el recorte de resultados grandes; **se siguen quitando los restos de desconexión, las llamadas rechazadas, la neutralización de residuos de interrupción y la caducidad por vigencia.**
25. **Los dos directorios de spill no son el mismo**: `spill_guard` cae en `<workbench.root>/spill/`,
    y `TrimPolicy.spill_dirname` en `<workspace>/.flower/spill/` (tiene que estar dentro del espacio de trabajo).
26. **El cuarto parámetro posicional de `PruningSessionStore.__init__` es `prune`, no `ephemeral`**,
    a diferencia de la clase padre. Pasarlo por posición desalinea en silencio.

### Documentos e interacción {#陷阱-文书}

27. **Cuando `Verdict` no consigue extraer una conclusión, `state=""` y `ok=False`, y eso nunca debe tomarse como logrado.**
    Además, "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" se agrupan todos en `unreachable`,
    lo que dispara la vía de "parar y preguntar a la persona", no la de "otra ronda más".
28. **Si `Brief.parse` encuentra una valla de código sin cerrar, descarta todo el contenido posterior** — cuando la salida del modelo se trunca,
    ninguna de las secciones siguientes se parsea, `complete()` da `False` y el gate lo devuelve para rehacerlo.
29. **`Brief.load` trata `"(未填)"` como vacío.** Si al editar el brief a mano copias el texto de marcador, esa sección sigue contando como ausente.
30. **Los tres "0 / None" de `HumanChannel` tienen semánticas distintas**: `max_asks=None` sin límite, `max_asks=0` prohibido preguntar;
    `timeout_s=None` esperar para siempre, `timeout_s<=0` timeout inmediato; `remaining` devuelve **`-1`** cuando `max_asks=None`.
31. **`Event("ask")` transporta a la vez preguntas y lo que la persona dice por iniciativa propia**, esto último con `payload["kind"] == "mail"`. La UI debe mirarlo primero.
32. **`Workflow.run` solo cablea automáticamente cuando `channel.on_event is None`** —
    si construyes tú `HumanChannel(on_event=...)`, los eventos de pregunta no entrarán además por la salida `on_event` del workflow.
