# API de Python

Esta página agota los **62 símbolos públicos** del `__all__` de nivel superior de `flower`: firmas, parámetros, valores por defecto, semántica,
atributos y métodos públicos. Al terminarla ya no hace falta abrir el código fuente para buscar un parámetro.

La organización es por **aquello que te importa**, no por archivo de módulo — si quieres saber "cómo impedir que el [coordinador](glossary.md#协调者)
haga el trabajo por su cuenta", ve a la [capa de hooks](#hook); si quieres saber "cómo se pasa el resultado de un paso al siguiente", ve a [workflow](#流程).
La terminología sigue en todo momento el [glosario](glossary.md).

Versión `0.1.0`, depende de `claude-agent-sdk>=0.2.152`. Todas las firmas se corresponden literalmente con el código fuente.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## Qué hay en esta página {#索引}

| Lo que te importa | Símbolos |
|---|---|
| [Ejecutar un agente](#运行时) | `Runtime` `StepResult` |
| [Encadenar varios pasos](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Construir un rol](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Escribir definiciones de agente a mano](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Documentos estructurados](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Interceptar herramientas, recortar resultados, separar aislamientos](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [El directorio de trabajo del spill](#工作台) | `Workbench` |
| [Cómo y qué se almacena de las sesiones](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [Qué hacer si se cae la red](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Cambiar la UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Retomar entre procesos](#血缘) | `Lineage` |

## Seis valores por defecto que muerden {#危险默认值}

Estas seis líneas no son detalles marginales: son los seis vuelcos más frecuentes. Cada una está explicada por completo en su sección correspondiente.

| Valor por defecto | Consecuencia | Detalle |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | El `Bash`/`Write`/`Edit` del main thread **no tiene ni un solo hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Fuerza en la spec un `CompactPolicy(mode="no_summary")`, es decir `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Un paso con `resume_from=None` seguirá retomando esa sesión anterior entre procesos | [Workflow](#workflow) |
| `build_options(fork=True)` sin `resume` | Falla en silencio, sin error | [build_options](#build-options) |
| `clarify(max_turns=<número pequeño>)` | Convierte "puede preguntar sin límite" en palabra vacía — cada pregunta es un turno | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | Es a nivel de sesión: prohíbe también a los subagents | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Código fuente: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` es el núcleo de ejecución. Mantiene el espacio de trabajo, el [session store](glossary.md#会话存储), el [workbench](glossary.md#工作台),
la política de [resiliencia](glossary.md#韧性) y la política de [handoff](glossary.md#换代), y hacia fuera expone un único verbo: `run` de un paso.
Reintentos, continuación tras una interrupción, handoff cuando el contexto se llena: todo ocurre dentro de esa única llamada.

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

Los parámetros del constructor son **todos keyword-only** (`*` al principio), y `workspace` es obligatorio.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workspace` | `str \| Path` | obligatorio | El `cwd` del agente. Se hace resolve y `mkdir(parents=True, exist_ok=True)` en la construcción. La `project_key` del SDK se deriva de él — si mueves el directorio, el `session_id` antiguo deja de encontrarse |
| `run_dir` | `str \| Path` | `"runs"` | Aloja `sessions.db`, `manifest.json`, `lineage.json`, y el workbench por defecto cuando `workbench=True`. También se hace resolve y mkdir |
| `portable` | `bool` | `True` | Se pasa tal cual a `build_options(portable=)`, es decir `setting_sources=[]`: no lee el `~/.claude/` de la máquina anfitriona ni el `.claude/` del proyecto. Ver [portable](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Si le das una instancia, se usa directamente; si le das un `bool`, se convierte en `TrimPolicy(enabled=bool(trim))`. **Desactivarlo solo significa no recortar resultados grandes; el prune se sigue haciendo** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Mismas reglas de conversión. Va emparejado con `coordinator(glance=True)` — si dejas que el main thread ejecute `git status`, hay que garantizar que ese resultado caduque |
| `keep_denials` | `int` | `1` | Se pasa a `PrunePolicy(keep_denials=)`. Conserva las últimas N llamadas a herramienta denegadas; las anteriores se eliminan junto con la llamada y su resultado |
| `workbench` | `Workbench \| bool` | `False` | Si le das una instancia, se usa directamente; si le das `True`, se crea `Workbench(workspace, home=run_dir / "workbench")` (**por defecto queda fuera del espacio de trabajo**). Inmediatamente después se llama a `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | A partir de cuántos caracteres un resultado de herramienta hace [spill](glossary.md#落盘). `None` o `0` = no se instala `spill_guard` |
| `resilience` | `Resilience \| bool` | `True` | Mismas reglas de conversión |
| `handoff` | `HandoffPolicy \| bool` | `True` | Mismas reglas de conversión |

**El session store está fijado en el código**: siempre es
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Los parámetros del constructor **no ofrecen** ninguna vía para cambiar el backend — si lo necesitas, construye tú mismo `AgentSpec` + `build_options(session_store=...)`,
o sobrescribe `rt.store` después de construir.

Los dos últimos pasos de la construcción son `load_dotenv()` y `check_credentials()`, y **si el segundo falla, lanza `RuntimeError`**.
Sin credenciales revienta en la fase de construcción, no al llegar a `run()`.

!!! warning "`workbench=False` + `coordinator()` = el main thread sin un solo muro"
    `delegate_guard` solo se instala dentro de `workbench_hooks`, y `workbench_hooks` solo se invoca cuando `self.workbench is not None`;
    `whitelist_guard`, a su vez, se salta por el `if not spec.delegate_only`. Y `coordinator()` fija siempre
    `delegate_only=True` y por defecto `glance=True`, que concede `Bash`.

    **Conclusión: con un coordinador y `Runtime(workbench=False)`, su `Bash`/`Write`/`Edit` no tiene ningún hook que lo intercepte.**
    Si usas `coordinator()`, activa el workbench — `Runtime(..., workbench=True)` o pásale una instancia de
    `Workbench`.

!!! warning "`handoff=True` (por defecto) desactiva a la fuerza el auto-compact"
    Dentro de `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`,
    lo que en el subproceso se traduce en `DISABLE_AUTO_COMPACT=1`. La razón es que con los dos mecanismos activos a la vez no se puede saber quién provocó la caída del contexto.

    **El precio: el paso que escribe el handoff debe tener una ruta degradada** (`handoff.degraded`), porque ya no hay compact que lo cubra.
    Si quieres conservar el auto-compact, indica explícitamente `AgentSpec.compact` (si la spec lo trae, se respeta y no se sobrescribe).

#### Atributos públicos {#runtime-属性}

| Atributo | Tipo | Descripción |
|---|---|---|
| `workspace` | `Path` | Espacio de trabajo tras resolve |
| `run_dir` | `Path` | Directorio de ejecución tras resolve |
| `portable` | `bool` | Se guarda tal cual |
| `store` | `PruningSessionStore` | El session store. Para cambiar de backend solo cabe sobrescribirlo tras construir |
| `resilience` | `Resilience` | La instancia ya normalizada |
| `handoff` | `HandoffPolicy` | La instancia ya normalizada |
| `workbench` | `Workbench \| None` | Es `None` cuando `workbench=False` |
| `spill_threshold` | `int \| None` | Se guarda tal cual; en `_attempt` se pasa a `workbench_hooks` |
| `results` | `list[StepResult]` | Cada paso ejecutado en este proceso, añadido en orden |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Debe ser único por instancia** — `manifest.json` deduplica por el campo `run`, y si dos ids colisionan, el que escribe después borrará las filas del otro creyendo que son las suyas anteriores |
| `on_session` | `Callable[[str], None] \| None` | Callback **inmediato** al obtener un nuevo `session_id`, por defecto `None`. **Solo debe envolver la línea `runtime.run`** — el [judge](glossary.md#判定者) usa el mismo `Runtime`, y si sigue enganchado durante el gate escribirá la sesión del judge en el [linaje](glossary.md#血缘) del paso que hacía el trabajo |

Constantes de clase: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`,
`INTERRUPT_NOTE` (un fragmento que se añade tras las palabras de la persona al continuar después de una interrupción, explicando que "las llamadas a herramienta en vuelo que devuelven interrupted son un efecto secundario normal de la interrupción, no un fallo del entorno").

#### Métodos públicos {#runtime-方法}

| Método | Firma | Descripción |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Ejecuta un paso. Ver abajo |
| `interrupt` | `(message: str = "") -> None` | Solicita interrumpir el turno actual. **Invocable desde cualquier hilo**. Es cooperativo: corta limpiamente en un **límite de mensaje**, no cancela por la fuerza. Cadena vacía = interrumpir sin decir nada |
| `rescue` | `() -> None` | Intenta dejar la contabilidad completa antes de que lo maten a la fuerza; lo invocan los handlers de `SIGHUP`/`SIGTERM`. El paso en vuelo también se escribe en el manifest, con `error="killed-by-signal"`. Solo hace escrituras pequeñas y síncronas |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | En `str(workspace.resolve())`, `/`, `_` y `.` se sustituyen todos por `-`. **El SDK la deriva del cwd; quien llama no puede fijarla** |
| `has_session` | `(session_id: str) -> bool` | ¿Sigue encontrándose ese id bajo **este espacio de trabajo**? Síncrono, no lee el payload |
| `context_of` | `(session_id: str) -> int` | Tamaño de contexto del último turno de una sesión; delega en `store.last_context` |
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
| `step_name` | `str \| None` | `None` | La clave que queda en `StepResult.step`, el manifest y el linaje. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Continúa esta `session_id` |
| `fork` | `bool` | `False` | Bifurca una sesión nueva sin contaminar la original. **Solo surte efecto si `resume` es verdadero** |
| `resume_at` | `str \| None` | `None` | Continúa desde un mensaje concreto (rollback). También **solo surte efecto si `resume` es verdadero** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Salida de eventos, ver [`Event`](#event) |

Al comienzo de cada paso se pone a cero el nivel de contexto (`self._ctx, self._warned = 0, False`). Luego viene un bucle con cuatro salidas:

1. **Éxito** → se sale.
2. **Interrupción humana** (`result.error == INTERRUPTED`) → **no está sujeta a `max_attempts`**, no espera a la red.
   Con las palabras de la persona hace `resume` de la misma sesión, `attempt -= 1` (una interrupción no cuenta como intento fallido), y el prompt = palabras de la persona + `INTERRUPT_NOTE`.
   **Si no se obtuvo `session_id`, no queda más remedio que parar.**
3. **Contexto lleno** (`result.error == HANDOFF_DUE`, o bien `handoff.enabled` y se obtuvo `session_id` y
   se cumple `is_overflow(...)`) → **tampoco está sujeta a `max_attempts`**. Primero comprueba `len(result.retired) >= handoff.max_generations`;
   si se excede, sustituye el error por un diagnóstico y sale; si no, escribe el [documento de handoff](glossary.md#交接书) → `resume=None, fork=False`
   (**sesión completamente nueva**) → el prompt pasa a ser `h.prompt_block()` → nivel de contexto a cero → `attempt -= 1`.
4. **Fallo reintentable** → si `not resilience.enabled or attempt >= max_attempts`, sale;
   si `classify(error)` determina que no debe reintentarse, también sale; si no, emite `Event("retry")`, se queda esperando la red con `wait_online()`,
   y `sleep(delay_for(attempt))`; **si en algún momento hubo `session_id`, hace `resume`** (el prompt pasa a ser
   `resilience.resume_prompt`) y pone `result.resumed` a `True`.

Cierre: escribe `ended_at`, lo añade a `self.results`, y escribe `manifest.json`.

`manifest.json` tiene semántica de **append**: cada escritura relee el disco y deduplica por el campo `run` (renueva sus propias filas, conserva las de los demás),
así que ejecutar dos flower en paralelo bajo el mismo `run_dir` es seguro — siempre que los `run_id` no colisionen.

**Los tres puntos de observación del handoff** (todos `Event("handoff")`, distinguidos por `payload["phase"]`):
`near` (se acerca a `warn_at`, se emite una sola vez por generación), `writing` (está escribiendo el handoff, tarda una decena de segundos),
`done` (el payload trae `degraded` / `path` / `sections`). El turno que escribe el handoff se ejecuta con
`replace(spec, max_budget_usd=None)` — el handoff tiene que poder escribirse, no puede quedarse atascado en el presupuesto;
y con `on_event=None`, ese turno no se refresca en la UI.

El handoff se escribe en `<workbench.notes>/交接-<步骤名>.md`; **sin workbench no hay escritura a disco**, el documento se entrega igualmente a quien releva por medio del prompt, solo que después no se puede consultar. Los handoffs antiguos se mueven a `notes/archive/交接/<名>-<时间戳>.md`.

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

Toda la contabilidad de un paso terminado.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `step` | `str` | obligatorio | Nombre del paso (`step_name` o `spec.name`) |
| `session_id` | `str \| None` | `None` | **Siempre la última sesión que tomó el relevo** — las quemadas por handoffs intermedios están en `retired` |
| `ok` | `bool` | `False` | Si el paso salió bien o no |
| `cost_usd` | `float` | `0.0` | En dólares. Se **acumula** a través de reintentos y handoffs |
| `num_turns` | `int` | `0` | Número de turnos, también acumulado |
| `text` | `str` | `""` | **Solo el cuerpo del main thread**. Lo que dice un subagent queda en su propio transcript, y el task brief que se le asigna es `kind="prompt"`; ninguno de los dos entra aquí |
| `error` | `str \| None` | `None` | Motivo del fallo. Para los valores especiales ver `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Timestamps Unix |
| `attempts` | `int` | `1` | Número real de intentos. Las interrupciones y los handoffs **no cuentan** |
| `errors` | `list[str]` | `[]` | Mensajes de error sintéticos de la API recogidos; **no entran en `text`** |
| `resumed` | `bool` | `False` | Si hubo algún resume intermedio |
| `retired` | `list[str]` | `[]` | Los `session_id` quemados por handoff en este paso, en orden |
| `context` | `int` | `0` | El tamaño de contexto que realmente vio el main thread en el último turno, es decir, el criterio del handoff |

| Atributo | Tipo | Descripción |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`; `0.0` si no ha terminado |

---

## Flujo de trabajo {#流程}

Código fuente: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Un [flujo de trabajo](glossary.md#流程) es un conjunto de [pasos](glossary.md#步骤) encadenados en orden, más
cómo se pasa el estado entre pasos y cuándo se sale antes de tiempo. **El framework no trae flujos hechos: el flujo lo escribes tú** —— `starter_flow` no es más que una plantilla que funciona.

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

La **declaración** de un paso. `Step` no es una función —— lo que de verdad ejecuta es `Runtime.run(step.spec, prompt, ...)`.
Los tres primeros campos son posicionales: `Step("取词", terse, "读 seed.txt …")` es una escritura válida.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | obligatorio | Nombre del paso. **Clave estable entre procesos** —— aterriza en `ctx[name]`, `ctx["_results"]`, el manifiesto y el linaje. Renombrar = romper el linaje |
| `spec` | `AgentSpec` | obligatorio | Qué agent se ejecuta |
| `prompt` | `str \| Callable[[Ctx], str]` | obligatorio | Qué se le dice. Puede ser un closure que calcule sobre el `ctx` del momento |
| `resume_from` | `str \| None` | `None` | De qué paso se continúa la sesión. Si el paso apuntado no produjo sesión, **lanza `ValueError`**, no lo salta en silencio |
| `fork` | `bool` | `False` | Bifurca a partir de `resume_from`. **Sin `resume_from` no tiene efecto** |
| `retries` | `int` | `0` | Cuántas veces reintentar como máximo cuando el gate no pasa. `retries=0` = una sola ronda |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Decide si este intento cuenta como aprobado. **Puede ser async**. Devolver `False` se considera fallo. **Se llama una sola vez por intento** —— puede tener efectos secundarios (por ejemplo volcar el brief a disco) y no debe dispararse dos veces |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, ver abajo |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Si devuelve `False`, **se salta el paso entero**: no produce result ni entra en `ctx["_results"]`. **Puede ser async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | **Qué decir en la siguiente ronda** cuando el gate no pasa. **Puede ser async**. Si lo das, la semántica del reintento cambia, ver abajo |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt que se usa al continuar (en vez de empezar desde cero) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Decide qué se pone en `ctx[name]`. Por defecto, el `result.text` literal. **Tiene que ser una función síncrona** |

| Método | Firma | Descripción |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Si `resuming` y hay `resume_prompt`, usa este último; si no, `prompt`; si es un callable, lo llama pasándole `ctx` |

**Tres formas de enganchar sesiones** (dentro de una misma ejecución):

| Escritura | Efecto |
|---|---|
| `resume_from=None` (por defecto) | Sesión nueva, solo con el contexto que le pases en el prompt. Barato, aislado. **Pero con `Workflow(continuous=True)` recoge la sesión del paso con el mismo nombre en el linaje entre procesos** |
| `resume_from="上一步名"` | Continúa la misma sesión, contexto completo. Caro, coherente |
| `resume_from="上一步名", fork=True` | Bifurca sin contaminar la sesión original. Para revisión / varias alternativas en paralelo |

**`on_reject` cambia la semántica del reintento**:

- Si no lo das → el siguiente intento **se ejecuta desde cero** (mismo prompt, mismo `resume_from`).
- Si lo das → el siguiente intento **continúa la sesión que acaba de ser rechazada**, con el prompt sustituido por su valor de retorno y `fork` forzado a `False`.
- Si devuelve cadena vacía → no hay devolución, degrada a ejecutar desde cero.
- Si `result.session_id` es `None` → también degrada a ejecutar desde cero.

**Los tres valores de `on_fail`**:

| Valor | Comportamiento |
|---|---|
| `"stop"` (por defecto) | Escribe `ctx["_failed_at"] = name` e **interrumpe todo el workflow** |
| `"skip"` | Salta al siguiente paso, **sin escribir `ctx[name]`** —— un `lambda ctx: ctx["某步"]` aguas abajo dará `KeyError` |
| `"continue"` | `ctx[name] = result.text`, sigue adelante con el resultado incompleto |

Pase o no pase, siempre se escribe `ctx["_results"][name] = result`; si `result.session_id` no está vacío, además se escribe en
`ctx["_sessions"]` y se llama a `lineage.remember(...)`.

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

Ejecuta una serie de `Step` en orden y devuelve el `ctx` final. `steps` es posicional, `Workflow([...])` es válido.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `steps` | `list[Step]` | obligatorio | Se ejecutan en orden |
| `name` | `str` | `"workflow"` | Nombre del flujo |
| `context` | `Ctx` | `{}` | Diccionario de contexto inicial. **Si ejecutas dos veces el mismo `Workflow`, el ctx es el mismo dict** |
| `channel` | `HumanChannel \| None` | `None` | Aquí se cuelga el canal para cuando haya que parar y preguntar a una persona. `run()` engancha automáticamente su `on_event` a la misma salida, **solo si `channel.on_event is None`**; el driver también usa este campo para saber a quién responder |
| `workbench` | `Workbench \| None` | `None` | El workbench que designa el workflow, para que el driver pueda encontrarlo |
| `continuous` | `bool` | `True` | Misma ruta = misma conversación. Se implementa con [`Lineage`](#lineage) |

| Parámetros de `run()` | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `runtime` | `Runtime` | obligatorio, posicional | Con qué runtime se ejecuta |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Salida de eventos, se pasa tal cual a cada `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Callback una vez por paso terminado |

!!! warning "`continuous=True` es el valor por defecto: `resume_from=None` no significa sesión nueva"
    Con la continuidad activada, `run()` hace primero `Lineage.open(run_dir, workspace)` y luego verifica cada registro
    con `runtime.has_session(sid)` para ver si sigue en el almacén; solo los vivos entran en `ctx["_sessions"]`. Con lo cual
    **los pasos con `resume_from=None` también siguen hablando en la sesión de la vez anterior** —— igual si mataste el proceso o reiniciaste la máquina.

    Si quieres sesión nueva siempre, escribe explícitamente `Workflow(..., continuous=False)`.
    Y además: **el nombre del paso es la clave estable entre procesos; cambiarlo equivale a romper el linaje.**

**Claves privadas** que `run()` escribe en el ctx (todas empiezan por `_`, así no chocan con nombres de paso):

| Clave | Contenido |
|---|---|
| `_runtime` | El `Runtime` que se pasó. **Los gates lo necesitan para lanzar agents** |
| `_on_event` | Salida de eventos. El agent que va dentro de un gate también tiene que poder pintar en la UI, si no la pantalla se queda a oscuras |
| `_sessions` | `dict[nombre de paso, session_id]`, se lee con `setdefault` |
| `_results` | `dict[nombre de paso, StepResult]` |
| `_lineage` | Objeto `Lineage`. Solo existe con `continuous=True` y si el runtime tiene `run_dir` + `workspace` |
| `_woke` | Valor devuelto por `lineage.bump()`: cuántas veces se ha despertado |
| `_aborted` | El mensaje del `StepAbort` |
| `_failed_at` | Nombre del paso que falló con `on_fail="stop"` |

Payload de `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Etiquetas de reintento**: el intento 0 usa `step.name`; después, si hay `on_reject` usa `f"{name}#round{attempt+1}"`,
y si no `f"{name}#retry{attempt}"`. En el manifiesto se ve de un vistazo cómo terminó ese paso.
**Los nombres con sufijo no entran en el linaje entre procesos** —— `Lineage.remember` usa el nombre original.

`runtime.on_session` solo cubre la línea de `runtime.run`; un `try/finally` garantiza que se desmonta siempre antes del gate.
`prompt_cur` / `resume_cur` / `fork_cur` son variables locales y no se escriben de vuelta en `step` —— el mismo objeto `Step` puede ejecutarse una segunda vez.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Lanzarlo desde `gate` = **parar ya, no reintentar más**. La diferencia con devolver `False`: `False` es «esta vez no, otra ronda»;
`StepAbort` es «otra ronda tampoco sirve».

Al lanzarlo: `ctx["_aborted"] = str(exc)`, `passed = False`, **se sale del bucle de reintentos (sin consumir los `retries` restantes)**,
y después sigue el camino de fallo normal según `on_fail` (por defecto `"stop"`).

`with_goal` lo lanza en dos sitios: cuando no consigue `ctx["_runtime"]`, y cuando el veredicto es `unreachable` y nadie responde.

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

Produce un `Step` que hace la [clarificación previa](glossary.md#前置确认): preguntar hasta dejar claro el requisito → parsearlo a [`Brief`](#brief) →
si las cuatro secciones están completas, congelarlo y volcarlo a disco.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `channel` | `HumanChannel` | obligatorio, posicional | Canal de preguntas |
| `brief_path` | `str \| Path` | obligatorio | Dónde aterriza el [brief](glossary.md#需求确认书). **Tiene que caer en el workbench cuyo índice se inyecta de verdad** |
| `prompt` | `str \| Callable[[Ctx], str]` | obligatorio | La petición original de la persona |
| `name` | `str` | `"确认需求"` | Nombre del paso, y a la vez clave en el `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Si no lo das, usa `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instrucciones adicionales para el [clarificador](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = preguntar de nuevo siempre, exista o no el brief |
| `on_fail` | `str` | `"stop"` | Igual que `Step.on_fail` |
| `retries` | `int` | `0` | Cuántas veces volver a preguntar si no se completan las cuatro secciones |
| `**spec_kw` | | | Se pasa tal cual a [`clarify()`](#clarify-role), así que puedes escribir `can_read=False`, `max_budget_usd=...` |

Los campos del `Step` resultante quedan así:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: con `always_ask=True` → siempre `True`; si no, si `Brief.load(brief_path)` está completo lo inyecta en el ctx
  **y luego devuelve `False` (salta el paso)** —— hay que inyectarlo aunque se salte, si no aguas abajo no hay requisito.
- `gate`: `Brief.parse(result.text)`; si está incompleto, escribe `ctx[MISSING_KEY]` y devuelve `False`;
  si está completo, congela con `b.write(brief_path)`, lo inyecta en el ctx y devuelve `True`.
- `reduce`: devuelve `ctx[BRIEF_KEY].prompt_block()`, **no el texto original del modelo** —— en el original puede haber colado cosas de más.
- `resume_from` **se queda en `None` por defecto**: el paso siguiente es sesión nueva, recibe solo el brief, no ese intercambio de preguntas y respuestas.
  Las preguntas y respuestas de la clarificación previa **nunca entraron** en el contexto del coordinador; no es que entrasen y luego se recortaran.

Los tres sitios donde se inyecta en el ctx: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`, `ctx.pop(MISSING_KEY, None)`.

| Constante | Valor | Descripción |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` es el objeto `Brief`; `ctx[step.name]` es su `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Qué secciones faltan cuando la clarificación falla (nombres de sección en chino), para mostrarlas en la UI |
| `CLARIFY_RESUME` | un prompt en chino | «Continúa la clarificación de requisitos que quedó a medias —— **no empieces de cero**…». Sin esta frase, al continuar se reenvía la petición original como si fuera una tarea nueva y el clarificador puede repetir preguntas ya hechas |

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

Produce un `Step` que **fija el objetivo**: el [juez](glossary.md#判定者) lee el brief y escribe el objetivo + la lista de comprobaciones,
que se parsea a [`Goal`](#goal) y se congela en disco. Tiene la misma forma que `clarify_step`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `channel` | `HumanChannel` | obligatorio, posicional | Canal de preguntas |
| `goal_path` | `str \| Path` | obligatorio | Dónde aterriza el fichero de objetivo |
| `brief_key` | `str` | `"确认需求"` | Toma el texto del brief de `ctx[brief_key]` y lo mete en el prompt. **Si no lo encuentra, queda `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Nombre del paso |
| `spec` | `AgentSpec \| None` | `None` | Si no lo das, usa `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Instrucciones adicionales |
| `always_set` | `bool` | `False` | `True` = rehacer la lista, exista o no el fichero de objetivo |
| `on_fail` | `str` | `"stop"` | Igual que arriba |
| `retries` | `int` | `0` | Igual que arriba |
| `**spec_kw` | | | Se pasa a [`judge()`](#judge-role) |

**No hay parámetro `can_run`** —— si quieres que el juez que fija el objetivo pueda ejecutar comandos, hay que pasar `can_run=True` vía `**spec_kw`.
Si no lo pasas, no tendrá `Bash` y la regla de `JUDGE_RULES` que dice «primero mira bien en qué entorno estás» no se puede cumplir.

Además de parsear y congelar, el `gate` hace una cosa más: si el objetivo tiene entradas `[此环境无法验证:…]`, **en ese mismo momento**
emite un aviso vía `ctx["_on_event"]` con `Event("task", payload={"unverifiable", "total", "path"})` ——
el destino de esas entradas queda sellado justo al fijar el objetivo; cuando llega el veredicto ya te has gastado el dinero de una ronda entera de trabajo.

**No se define `resume_prompt`** —— fijar el objetivo debe reenviar el brief completo de todas formas.

| Constante | Valor | Descripción |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` es el objeto `Goal`; `ctx[step.name]` es markdown |
| `VERDICT_KEY` | `"_verdict"` | El último [`Verdict`](#verdict), para la UI |
| `ROUND_KEY` | `"_goal_rounds"` | Cuántas rondas de veredicto se han corrido |

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

Envuelve un `Step` existente con el [guardián de objetivos](glossary.md#目标看守): al final de cada ronda, un juez independiente dicta veredicto,
y si no se ha logrado el objetivo lo devuelve para seguir trabajando.

El resultado es `replace(step, retries=max(0, rounds - 1), gate=<nuevo gate>, on_reject=<nuevo on_reject>)` ——
con `dataclasses.replace` en vez de reconstruir campo a campo; una vez se reconstruyó y se olvidó `resume_prompt`, **y no dio ningún error**:
simplemente volvía a mandar el brief entero al continuar.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `step` | `Step` | obligatorio, posicional | El paso que se vigila |
| `channel` | `HumanChannel` | obligatorio, posicional | Canal para pedir ayuda a una persona cuando no se puede dictaminar |
| `goal_path` | `str \| Path` | obligatorio | Fichero de objetivo, se lee de aquí cuando `ctx[GOAL_KEY]` está incompleto |
| `spec` | `AgentSpec \| None` | `None` | Si no lo das, usa `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Rondas totales, no rondas extra**: `rounds=3` → `retries=2` → como mucho tres rondas de trabajo. `rounds=1` = una ronda, un veredicto, y si no pasa, falla |
| `instructions` | `str` | `""` | Instrucciones adicionales para el juez |
| `can_run` | `bool` | `False` | Si el juez puede ejecutar `Bash` |
| `name` | `str \| None` | `None` | Nombre del juez, por defecto `f"{step.name}·判定"` |
| `**spec_kw` | | | Se pasa a `judge()` |

El `gate` es **async**, y su recorrido es:

1. Falta `ctx["_runtime"]` → **lanza `StepAbort`** («no hay Runtime, no se puede dictaminar el objetivo»). **No finjas que ha pasado.**
2. `ctx[ROUND_KEY] += 1`.
3. Obtener el objetivo: primero un `Goal` completo en `ctx[GOAL_KEY]`; si no, `Goal.load(goal_path)`; si no, un `Goal()` vacío.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **El juez es un `Runtime.run` independiente, con `resume` siempre `None` —— siempre sesión nueva**; el `step_name` lleva el número de ronda,
   así que no entra en el linaje entre procesos.
5. `Verdict.parse(vr.text)` se escribe en `ctx[VERDICT_KEY]`.
6. `v.achieved` → devuelve `True`.
7. Si no es `unreachable` (incluidos los casos ambiguos con `v.ok=False`) → en caso ambiguo añade una razón por defecto y devuelve `False`.
   **Toda ambigüedad cuenta como no logrado** —— un «parece que está bien» no puede dar el trabajo por cerrado.
8. `unreachable` → `await channel.ask(...)` pregunta a la persona, con tres opciones:
   - Nadie responde (`a.state != "answered"`) → **lanza `StepAbort`**. Seguir girando en vacío es la opción más cara.
   - «Acepta este resultado y sigue adelante» → devuelve `True`.
   - «Modificar el objetivo» → vuelve a preguntar por el objetivo nuevo, `g.amend(...).write(goal_path)`, actualiza `ctx[GOAL_KEY]` y devuelve `False`.
   - El resto (incluida una respuesta libre escrita por la persona) → se toma como «te has equivocado en el veredicto», se anota lo que dijo en `v.reason` y devuelve `False`.

El `on_reject` es **síncrono**: devuelve `ctx[VERDICT_KEY].feedback()`, y si no hay `Verdict` devuelve `""`
(degrada a ejecutar desde cero).

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

Monta un flujo de tres pasos que funciona de fábrica: **clarificar requisitos → fijar objetivo → trabajar** (con guardián de objetivos). Es lo que usa el comando `flower`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `ask` | `str` | obligatorio, posicional | Una frase con la petición. **Al despertar no es una tarea nueva, es «una frase más que dijo la persona»** |
| `workspace` | `str \| Path` | `"."` | Espacio de trabajo |
| `run_dir` | `str \| Path` | `"runs"` | Directorio de ejecución |
| `new` | `bool` | `False` | `True` = archiva linaje + brief + objetivo (los tres a la vez) y empieza de cero |
| `isolate` | `bool` | `False` | Abre un worktree de [aislamiento](glossary.md#隔离) para el ejecutor. El workbench se traslada a `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Devuelve solo el Workflow con el paso de clarificación |
| `goal` | `bool` | `True` | Si se monta el [guardián de objetivos](glossary.md#目标看守). `False` = el paso de trabajo termina y se acabó |
| `rounds` | `int` | `3` | Se pasa a `with_goal(rounds=)`, rondas totales |
| `judge_can_run` | `bool` | `False` | Se pasa a `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Se pasa a `HumanChannel`, `None` = sin límite |
| `timeout_s` | `float \| None` | `1800.0` | Se pasa a `HumanChannel`. `0` = totalmente automático, toda pregunta cae en vacío al instante |
| `instructions` | `str` | `""` | Instrucciones adicionales para el clarificador |
| `worker_prompt` | `str` | ver firma | System prompt del ejecutor |
| `brief_name` | `str` | `"需求.md"` | Nombre del fichero de brief, aterriza en `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Nombre del fichero de objetivo, igual |
| `log_name` | `str` | `"问答记录.md"` | Nombre del fichero con el registro de preguntas y respuestas, igual |

Montaje fijo:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Ramas de comportamiento:

- `isolate=True` y el workspace no es un repositorio git → **lanza `ValueError`**, en vez de esperar a que la herramienta `Agent` dé error
  (para entonces ya te has gastado el dinero).
- **Detección de despertar**: si `Brief.load(brief_path)` existe y está `complete()`, se cuenta como despertar. Si no es un despertar y `ask` está vacío →
  **lanza `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- Al despertar, esa frase aterriza en **tres sitios** a la vez, y si falta uno el efecto se pierde en silencio: se anexa al brief
  (`ch.amend(said, label="唤醒时追加")`, si ya está en el fichero no se reescribe),
  hace que `goal_step(always_set=True)` rehaga la lista (si no se rehace, el juez sigue leyendo el objetivo viejo)
  y se le entrega directamente al coordinador (en su contexto está el objetivo **viejo**: si no se la das, trabaja con el criterio viejo y luego lo juzgan con el nuevo).

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

**Sondeo de solo lectura antes de arrancar: no escribe ni un byte.** Sirve para decirle a la persona, antes de empezar de verdad, si esto continúa lo anterior o empieza de cero.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Espacio de trabajo, posicional |
| `run_dir` | `str \| Path` | `"runs"` | Directorio de ejecución |
| `isolate` | `bool` | `False` | Determina la ubicación del workbench, tiene que ser el mismo valor que le pases a `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Nombre del fichero de brief |
| `goal_name` | `str` | `"目标.md"` | Nombre del fichero de objetivo |

El dict devuelto:

| Clave | Tipo | Descripción |
|---|---|---|
| `waking` | `bool` | El brief existe y tiene las cuatro secciones completas |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Número de entradas de la lista de objetivo, `0` si no hay objetivo |
| `woke` | `int` | `Lineage.woke`, cuántas veces se ha despertado ya |
| `steps` | `dict` | Copia de `Lineage.steps`, nombre de paso → `session_id` |

La ubicación del workbench **se define una sola vez, aquí y en `starter_flow`**: `isolate=True` → `<ws>.parent/.flower-<ws.name>`
(fuera del repositorio); si no, `<ws>/.flower`. Cuando el driver quiere saber dónde está el brief también pasa por esta función —— si construyes la ruta a mano y te equivocas no salta ningún error,
simplemente deja de funcionar en silencio.

---

## Fábrica de roles {#角色工厂}

Código fuente: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Los cinco roles son funciones fábrica. Cada rol = **un bloque de reglas inyectado + un conjunto de herramientas + un conjunto de hooks**.
`worker()` produce un `AgentDefinition` del SDK (para despachar a un subagent); los otros cuatro producen un [`AgentSpec`](#agentspec)
(abren su propia sesión).

Los roles en sí **no montan hooks**: interceptar herramientas lo hace `Runtime._attempt`, que los instala automáticamente según `spec.delegate_only`,
ver [capa de hooks](#hook).

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

Construye el [coordinador](glossary.md#协调者) que vive en el [hilo principal](glossary.md#主线程): descompone la tarea, reparte trabajo, lee informes, decide,
**pero no toca nada**. Los tres primeros parámetros son posicionales.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | obligatorio | Nombre del rol, y también nombre por defecto del paso |
| `instructions` | `str` | obligatorio | Instrucciones de dominio. Al final queda `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | obligatorio | Qué roles tiene a su cargo; va a `AgentSpec.agents`. **Además, sus herramientas web de solo lectura se fusionan en el propio `allowed_tools` del coordinador**, ver abajo |
| `channel` | `HumanChannel \| None` | `None` | Si se da, añade a la vez las herramientas `inbox` **y** `ask`, y fija `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → quita `Read` |
| `glance` | `bool` | `True` | Añade `"Bash"` y fija `AgentSpec.glance`. **Qué puede ejecutar realmente lo controla `delegate_guard`**, no esto |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | Límite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Límite de [presupuesto](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Modo de permisos. **Ojo con este valor por defecto**: pasárselo a `clarify()`/`judge()` desmonta la protección de esos dos roles |
| `compact` | `CompactPolicy \| None` | `None` | Si se da, `Runtime` no lo forzará a `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks adicionales; se fusionan con `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Variables de entorno adicionales |

Tres cosas quedan fijas en el `AgentSpec` producido: `delegate_only=True`, `agents=workers` y
`workbench` mantiene el valor por defecto `True` de `AgentSpec`.

#### Las herramientas web de `workers` se fusionan {#coordinator-web-merge}

Tras armar la lista, `coordinator()` recorre cada `AgentDefinition.tools` y, por cada herramienta que caiga dentro de
`WEB_TOOLS` (`WebFetch`, `WebSearch`, `roles.py:33`), añade también una copia al `allowed_tools`
del propio coordinador (`roles.py:523-526`).

**Motivo: `allowed_tools`, igual que `disallowed_tools`, es de ámbito de sesión.** Esta es la evidencia más dura de todo el documento sobre este punto:
no afecta solo al hilo principal. Una herramienta que no esté en esa lista de ámbito de sesión también pasa por aprobación de permisos cuando la invoca un **subagent**;
sin nadie vigilando no hay quien apruebe, y el harness responde
`Claude requested permissions to use X, but you haven't granted it yet`
(`toolDenialKind=user-rejected`), con el modelo reintentando la misma llamada una y otra vez. Comprobado a base de fallar: se le añadió
`WebFetch`/`WebSearch` al ejecutor pero solo se escribió en `AgentDefinition.tools`, y aquella ejecución de novel acumuló más de veinte
user-rejected sin escribir una sola palabra (`roles.py:513-518`).

Los dos campos tienen la misma naturaleza de ámbito de sesión, pero **los síntomas son distintos**: `disallowed_tools` falla en el acto,
`allowed_tools` reintenta en silencio hasta morir. El segundo es más difícil de diagnosticar, porque en pantalla nada parece un error.

**Solo se fusionan las de solo lectura, sin efectos secundarios.** `Write`/`Edit`/`Bash` **se dejan fuera a propósito**: en cuanto el hilo principal
no necesite aprobación para ellas, el muro de `delegate_guard` («el coordinador no toca nada») deja de tener sentido; y el `Bash`/`Write` de un subagent
ya funciona de todos modos (462 permisos concedidos medidos, `roles.py:520-522`).

En el código fuente está escrito explícitamente que **no se use `disallowed_tools` para implementar «solo coordinar, no tocar»**: es de ámbito de sesión
y prohibiría también el `Bash`/`Write` de los subagents, ver la advertencia en [`AgentSpec`](#agentspec).
La forma correcta es la de aquí: `delegate_only=True` + no conceder `allowed_tools`,
y dejar que [`delegate_guard`](#delegate-guard) bloquee solo el hilo principal según `agent_id`.

Si se da `channel`, **vienen las dos herramientas juntas**, no es opcional: al montar el MCP server están ambas, y
`allowed_tools` no es exclusivo, así que se pueden invocar estén listadas o no. Sin supervisión humana, cada `ask` se queda bloqueado hasta agotar `timeout_s`:
para esos casos, usar `HumanChannel(timeout_s=0)`.

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

Construye la definición del [subagent](glossary.md#subagent) que realmente trabaja. Los dos primeros parámetros son posicionales.
Devuelve un `AgentDefinition` del SDK, que se mete directamente en `coordinator(workers={...})`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `description` | `str` | obligatorio | **La base con la que el coordinador elige a quién asignar**: escribe con claridad «qué trabajo se le da» |
| `prompt` | `str` | obligatorio | Su system prompt. Con `discipline=True` queda `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | Al ejecutor no se le debe degradar |
| `effort` | `str \| int \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | Va al **`maxTurns`** del SDK (camelCase) |
| `permission_mode` | `str \| None` | `None` | Va al **`permissionMode`** del SDK (camelCase) |
| `skills` | `list[str] \| None` | `None` | Qué skills puede usar |
| `discipline` | `bool` | `True` | Si se concatena o no el bloque de disciplina de informe `WORKER_RULES` |
| `isolate` | `bool` | `False` | Marca de [aislamiento](glossary.md#隔离), pasa por `isolated()`; **no es un campo de `AgentDefinition`** |

`isolate=True` exige que el workspace sea un repositorio git; si no, la herramienta `Agent` falla directamente con `"not in a git repository"`,
**no degrada en silencio**. Y la marca es un atributo de Python: hacer `dataclasses.replace()` sobre el `AgentDefinition`
la pierde, y el aislamiento deja de funcionar sin avisar.

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

Construye el [clarificador](glossary.md#确认者): antes de tocar nada, deja claros los requisitos; no hace trabajo, solo pregunta, y al final produce exactamente cuatro secciones.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | obligatorio | Nombre del rol, posicional |
| `channel` | `HumanChannel` | obligatorio | Canal de preguntas, posicional |
| `instructions` | `str` | `""` | Instrucciones adicionales, concatenadas tras `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | Con `True` añade `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | **Sin límite de turnos** |
| `max_budget_usd` | `float \| None` | `None` | Límite de presupuesto |

El `AgentSpec` producido: `allowed_tools = [channel.tool_name] + (esas cinco si puede leer)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (no tiene herramientas de escritura, el índice no le sirve de nada),
y `permission_mode` hereda el `"default"` por defecto de `AgentSpec`.
**No tiene `Write` / `Edit` / `Bash` / `Agent`, ni tampoco `inbox`** (a diferencia del coordinador).

!!! warning "Poner un `max_turns` pequeño convierte en papel mojado lo de «preguntas ilimitadas»"
    Cada pregunta es un turno. `max_turns=16` equivale a «pregunta como mucho una docena», y aquella frase del canal
    de «no hay límite de turnos» queda invalidada al instante.

    Para abrir de verdad las preguntas hay que abrir **las dos** cosas: `HumanChannel.max_asks` (ya es `None` = sin límite por defecto)
    y `max_turns` (también `None` por defecto).

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

Construye el [juez](glossary.md#判定者): o bien fija el objetivo antes de arrancar, o bien emite el veredicto de cada ronda al terminarla.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | obligatorio | Nombre del rol, posicional |
| `channel` | `HumanChannel` | obligatorio | Canal de preguntas, posicional |
| `instructions` | `str` | `""` | Instrucciones adicionales, concatenadas tras `JUDGE_RULES` |
| `can_run` | `bool` | `False` | Con `True` añade `Bash` a la lista blanca; `whitelist_guard` deja pasar `Bash` pero sigue bloqueando `Write`/`Edit` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | Límite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Límite de presupuesto |

El `AgentSpec` producido: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (si `can_run`) `["Bash"]`,
`workbench=False`, el resto igual que `clarify()`. **No tiene `Write` / `Edit` / `Agent`, ni tampoco `inbox`.**

**Compromiso**: con `can_run=True` el veredicto es más sólido (puede ejecutar de verdad los comandos de aceptación), a cambio de que el juez
pueda modificar el área de trabajo: `Bash` por sí solo ya permite escribir ficheros. Si quieres un veredicto absolutamente neutral, no lo actives.

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

Construye el [oráculo](glossary.md#旁路顾问): con la ejecución todavía en marcha, le preguntas «¿por dónde va esto?» y responde tras echar un vistazo
a los eventos recientes y al banco de trabajo. **Lo que dice no entra en el contexto de esa ejecución.**

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Nombre del rol, posicional |
| `instructions` | `str` | `""` | Instrucciones adicionales, concatenadas tras `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | **`12`** | Con freno por defecto |
| `max_budget_usd` | `float \| None` | **`0.5`** | Con freno por defecto. Esto es «una pregunta de pasada», no debe descontrolarse |

El `AgentSpec` producido: `allowed_tools = ["Read", "Glob", "Grep"]` (**sin canal**: no pregunta,
solo responde), `workbench=True` (**el único de los cinco roles que no es coordinador y aun así abre el banco de trabajo**: precisamente necesita leer esos artefactos y notas).

### Los cinco bloques de reglas {#rules}

Las cinco constantes están en `__all__`, se pueden importar directamente para leerlas, concatenarlas o modificarlas.

| Constante | A quién se inyecta | Forma de inyección | Puntos clave |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Eres «una persona que sabe usar Claude Code», no un ejecutor; no puedes escribir ficheros, modificar código ni ejecutar tests; `Bash` solo da para «echar un vistazo» y el resultado caduca; **el [encargo de tarea](glossary.md#任务书) solo describe lo específico de esta tarea**; la única norma que aún hay que explicar es «dónde está el banco de trabajo + los artefactos largos van a `artifacts/` + en la respuesta solo se dan rutas»; consulta `inbox` cada vez que completes una acción de etapa; `ask` bloquea, úsalo solo en bifurcaciones reales |
| `WORKER_RULES` | `worker()` | Concatenado **después** del `prompt` del subagent | Formato de respuesta **conclusión / evidencia / artefactos / no verificado**, máximo 30 líneas; prohibido pegar contenido de ficheros, salida de comandos, logs o diffs literales; prohibido narrar el proceso de prueba y error; antes de actuar, mira `.flower/scripts/`. **A propósito no dice «los artefactos largos van a `artifacts/`»**: la ruta real la genera `Workbench`, y escribirla a fuego sería incorrecto |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | No hace trabajo, solo pregunta hasta dejar claros los requisitos; **sin límite de preguntas, hasta que esté claro**; puede que no haya nadie, si hay timeout decide tú y escríbelo en 「未知与假设」; salida de **exactamente cuatro secciones**; no escribas código, no pegues contenido de ficheros |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Dos cometidos, uno u otro. **Fijar el objetivo**: cada punto de la lista debe poder verificarse en el acto, la longitud de la lista la determina el número de formas de fallar, **los límites no son criterios de veredicto**, y a los puntos no verificables se les añade al final `[此环境无法验证:原因]`. **Emitir el veredicto de la ronda**: salida de **exactamente tres secciones**, se juzgan **los artefactos, no el código fuente**, por defecto no te creas «está hecho», «no lo ha conseguido» y «aquí no se puede verificar» son dos conclusiones distintas, y la segunda **jamás puede darse por aprobada** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Eres una vía lateral; esa ejecución sigue en marcha, no la interrumpes ni participas; **solo lectura**; una vez respondes, se descarta: lo que digas no entra en el contexto de esa ejecución; solo dispones de la «ventana de eventos recientes» y del «banco de trabajo»; mira antes de responder, si no puedes responder dilo, y sé breve |

---

## Definición de agente {#agent-定义}

Código fuente: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` es la declaración completa de un agente especializado, y `build_options` la compila al `ClaudeAgentOptions` del SDK.
Lo que produce la [fábrica de roles](#角色工厂) es precisamente un `AgentSpec`: cuando necesites una combinación fuera de la fábrica, constrúyelo directamente.

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
| `name` | `str` | obligatorio | Nombre del rol. También es el `step_name` por defecto de `Runtime.run`, y cómo se refiere a sí mismo en el texto de rechazo de `whitelist_guard` |
| `instructions` | `str` | obligatorio | Instrucciones de dominio. **Se [añade](glossary.md#叠加) después del system prompt nativo de Claude Code, no lo sustituye** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Lista de exención de aprobación, no lista blanca exclusiva**: el modelo puede seguir invocando herramientas que no estén en ella. La exclusividad la da [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **De ámbito de sesión**. Ver la advertencia de abajo |
| `model` | `str \| None` | `None` | Modelo |
| `effort` | `str \| None` | `None` | Intensidad de razonamiento |
| `max_turns` | `int \| None` | `None` | Límite de turnos |
| `max_budget_usd` | `float \| None` | `None` | Límite de [presupuesto](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Modo de permisos |
| `agents` | `dict[str, Any] \| None` | `None` | Tabla de definiciones de subagents; los valores son `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Tabla de MCP servers. `HumanChannel.mcp_servers()` se rellena aquí directamente |
| `hooks` | `dict[str, Any] \| None` | `None` | Hooks adicionales; `Runtime` los fusiona con los suyos vía `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | Si se da, `Runtime` no lo forzará a `no_summary` |
| `env` | `dict[str, str]` | `{}` | Variables de entorno inyectadas al subproceso. `compact.env()` se aplica encima con update |
| `glance` | `bool` | `False` | Permite al coordinador ejecutar por sí mismo un `Bash` de «solo echar un vistazo». Qué se deja pasar lo decide [`is_ephemeral`](#is-ephemeral), y el resultado queda marcado como caducado por `EphemeralPolicy` |
| `workbench` | `bool` | `True` | Si se inyecta el índice del banco de trabajo en el system prompt de este agente. **Los roles sin herramientas de escritura deben desactivarlo** (`clarify()` / `judge()` ya lo tienen en `False` por defecto) |
| `delegate_only` | `bool` | `False` | Solo coordina, no toca nada. Con `True`, `Runtime` monta `delegate_guard` y **no monta** `whitelist_guard` |

!!! warning "`disallowed_tools` es de ámbito de sesión y prohíbe también a los subagents"
    Texto literal del error medido: `"Bash is disabled for this session, in subagents as well as here"`.
    Es decir: si para que el coordinador no toque nada usas `disallowed_tools=["Bash"]`, los ejecutores que despaches tampoco podrán ejecutar comandos,
    y toda la ejecución se va al traste.

    Para «solo coordinar, no tocar», usa `delegate_only=True` + no conceder `allowed_tools`, y deja que
    [`delegate_guard`](#delegate-guard) bloquee solo el hilo principal según `agent_id`.

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
si conduces el SDK por tu cuenta (sin `Runtime`), también entras por aquí.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `spec` | `AgentSpec` | obligatorio, posicional | La declaración a compilar |
| `cwd` | `str \| Path \| None` | `None` | Solo se escribe `cwd` si no es `None` |
| `session_store` | `SessionStore \| None` | `None` | Solo si no es `None` se escriben `session_store` y `session_store_flush` |
| `resume` | `str \| None` | `None` | Qué sesión continuar |
| `fork` | `bool` | `False` | Va a `fork_session`. **Está anidado dentro de `if resume:`** |
| `resume_at` | `str \| None` | `None` | Va a `resume_session_at`. **También anidado dentro de `if resume:`** |
| `use_plugin` | `bool` | `True` | `True` y `PLUGIN_DIR` existe → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Directorios autorizados adicionales. **Obligatorio si el banco de trabajo está fuera del área de trabajo** |
| `flush` | `str` | `"eager"` | Va a `session_store_flush` |
| `prelude` | `str` | `""` | Bloque añadido tras `instructions` (por aquí entra el índice del banco de trabajo) |

Correspondencias:

| Clave de option producida | Valor |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Directamente de `spec` |
| `setting_sources` | `[]` (portable) o `["project"]` |
| `plugins` | Solo si existe el directorio `plugin/` en la raíz del repositorio |
| `cwd` / `add_dirs` | Se escriben solo si no están vacíos |
| `session_store` / `session_store_flush` | Solo si `session_store` no es `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Cada uno se escribe solo si no está vacío |
| `env` | `dict(spec.env)` y luego `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Solo surten efecto si `resume` es verdadero** |

`PLUGIN_DIR` es el directorio `plugin/` de la raíz del repositorio (tres niveles por encima de `flower/core/agent.py`). Tras instalar con pip ese directorio puede no existir,
y el código lo comprueba con `is_dir()`.

!!! warning "`fork=True` sin `resume` no hace nada, y en silencio"
    Tanto `fork_session` como `resume_session_at` están anidados dentro de `if resume:`: sin `resume` no surten ningún efecto
    **y tampoco hay error**. Del mismo modo, `Runtime.run(resume_at=...)` solo actúa si se da `resume`,
    y **`Workflow` nunca pasa `resume_at`**: para retroceder por mensaje hay que llamar directamente a `Runtime.run`.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

El panel de interruptores del auto-[compact](glossary.md#压缩); lo que produce es un conjunto de variables de entorno a inyectar en el subproceso.
El algoritmo de compact en sí vive en el binario del harness y no se puede cambiar; lo único que se puede cambiar es «si se dispara o no».

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = no fija nada, umbral = ventana − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (desactiva también `/compact`). **Cualquier otro valor lanza `ValueError`**, no se ignora en silencio |
| `window` | `int \| None` | `None` | Si no es `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. El CLI limita a 100k–1M; poner menos de 100k lo sube a 100k |

| Método | Firma | Descripción |
|---|---|---|
| `env` | `() -> dict[str, str]` | Produce las variables de entorno. **Un `mode` inválido lanza `ValueError` aquí, no en el constructor**: lo llama `build_options`, así que el error aflora dentro de `Runtime.run` |

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

El objeto de política para, cuando el contexto está a punto de llenarse, «escribir el documento de relevo y cambiar de sesión» en lugar de hacer compact.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `enabled` | `bool` | `True` | Al desactivarlo se vuelve al auto-compact |
| `window` | `int` | `default_window()` | Qué tamaño se supone que tiene la ventana de contexto del modelo |
| `headroom` | `int` | `50_000` | Cuánto margen dejar. Motivo: el auto-compact se dispara en ventana −33k, el relevo debe adelantarse a él, y «escribir el relevo» consume además una ronda |
| `max_generations` | `int` | `8` | Cuántas generaciones como máximo por paso. **Es un freno contra desbocarse, no planificación de capacidad** |

| Propiedad | Tipo | Descripción |
|---|---|---|
| `at` | `@property -> int` | Umbral de relevo `max(10_000, window - headroom)`. **Con suelo de 10k**: por debajo no da ni para escribir el relevo |
| `warn_at` | `@property -> int` | Punto de aviso de proximidad `max(1_000, at - 20_000)`, se emite una sola vez por generación |

!!! warning "Un `window` demasiado pequeño provoca relevos infinitos que queman dinero"
    Si `at` queda por debajo del **suelo de arranque** de ese rol (medido en unos 34k para el coordinador), cada sesión nueva cruza la línea en cuanto abre la boca; y
    **el relevo no consume cupo de reintentos** (`attempt -= 1`), así que gira en vacío indefinidamente. El único freno es `max_generations=8`,
    y al chocar con él el `error` se sustituye por un diagnóstico que sugiere subir `window` o desactivar el relevo.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Adivina la ventana de contexto a partir de la **cadena del nombre del modelo** en las variables de entorno `ANTHROPIC_MODEL` o `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Condición | Devuelve |
|---|---|
| El nombre contiene la palabra aislada `1m` (regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| El nombre contiene `haiku` | `200_000` |
| El resto (**incluido que no esté fijada ninguna de las dos variables**) | `1_000_000` |

**Por defecto tira por lo optimista.** Pasarse de grande no es un error duro: la API rechaza con `prompt is too long`, y `Runtime` reconoce esa señal
(el `is_overflow` interno) y hace relevo en el acto, pero el relevo de esa generación es una versión degradada.

---

## Documentos {#文书}

Código fuente: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Cuatro dataclasses, todas dedicadas a «parsear una respuesta del modelo en unas secciones fijas y volcarla a disco». Forma común:
`parse()` parsea, `missing()` / `complete()` comprueban si está completo, `to_markdown()` es para humanos,
`prompt_block()` es para el modelo de aguas abajo, `write()` / `load()` vuelcan y releen.

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

El [brief](glossary.md#需求确认书), **exactamente cuatro secciones**, en orden fijo
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
| `missing` | `() -> list[str]` | Los **nombres en chino** de las secciones que faltan, listos para mostrar |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Parsea las cuatro secciones de la respuesta del modelo. **Primero quita los bloques de código con cercas**; lo que no se parsee queda vacío |
| `to_markdown` | `() -> str` | Documento completo con metainformación de cabecera; las secciones vacías se escriben como `"(未填)"` |
| `prompt_block` | `() -> str` | Versión compacta para alimentar aguas abajo, **solo con las secciones no vacías**, sin metainformación |
| `write` | `(path: str \| Path) -> Path` | Crea el directorio padre, escribe a disco, fija `self.path` a la ruta resuelta y la devuelve |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Devuelve `None` si el fichero no existe o hay `OSError`. **Restaura el marcador `"(未填)"` a cadena vacía** |

Reglas de parseo (donde se concentran los fallos):

- Al quitar las cercas, **si encuentra un ``` o `~~~` sin cerrar, descarta desde ahí todo el resto**: se ha comprobado que el clarificador pega código entero en la respuesta.
  Cuando la salida del modelo se trunca, ninguna de las secciones posteriores se parsea, con lo que `complete()` es `False` y el gate lo devuelve para repetir.
- La regex de títulos tolera `## 目标` / `**目标**` / `目标:` / `3. 边界`, y también que el cuerpo venga inmediatamente tras el título.
- La tabla de alias se compila en orden inverso de longitud; si no, «未知» se comería antes a «未知与假设».
- Si una sección con el mismo nombre aparece repetida, **se toma la primera con contenido**.
- Si al editar el brief a mano se copia literalmente el marcador `"(未填)"` de `to_markdown()`, esa sección sigue contando como ausente.

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

El [documento de relevo](glossary.md#交接书) que se escribe al hacer [relevo](glossary.md#换代), cinco secciones.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `doing` | `str` | `""` | Qué se está haciendo. **Obligatorio** |
| `decided` | `str` | `""` | Qué se ha decidido |
| `deadends` | `str` | `""` | Caminos que no llevan a nada |
| `next` | `str` | `""` | Siguiente paso. **Obligatorio** |
| `scene` | `str` | `""` | Situación actual |
| `step` | `str` | `""` | Solo para la cabecera del documento, **no participa en el parseo** |
| `path` | `Path \| None` | `None` | Ubicación en disco |

**Solo son obligatorias `doing` y `next`**: exigir por narices que «caminos que no llevan a nada» no esté vacío obligaría al modelo a inventar.

| Miembro | Firma | Descripción |
|---|---|---|
| `missing` | `() -> list[str]` | **Solo comprueba esas dos secciones obligatorias** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Si el cuerpo lleva la marca de degradación `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Reutiliza el segmentador de `Brief` |
| `to_markdown` | `() -> str` | Las secciones vacías se escriben como `"(空)"` |
| `prompt_block` | `() -> str` | **La cabecera le dice explícitamente al que recoge el testigo que «estás tomando el relevo»**, para que no se dé la vuelta a pedirle contexto a alguien |
| `write` | `(path) -> Path` | Igual que `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Igual que `Brief.load` |

En el mismo módulo hay tres miembros **no exportados pero semánticamente clave**: `is_overflow(*texts)` casa con `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed`, etc., y convierte un «error duro» en «relevo en el acto»; `HANDOFF_PROMPT` es el prompt que hace que
**la propia sesión actual** escriba su relevo (contiene los marcadores `{used}` y `{window}`; **no es un rol nuevo**:
solo ella tiene ese contexto); `degraded(step, prompt, *, why="")` monta mecánicamente un relevo cuando no se ha logrado escribir,
metiendo en `scene` los primeros **1200** caracteres de la tarea original.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

El objetivo y la lista de comprobación del [guardián de objetivo](glossary.md#目标看守).

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `statement` | `str` | `""` | Enunciado del objetivo |
| `checks` | `list[str]` | `[]` | Lista de comprobación, una por línea |
| `path` | `Path \| None` | `None` | Ubicación en disco |

| Miembro | Firma | Descripción |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Los puntos de `checks` marcados con `[此环境无法验证:…]`. **En el momento de fijar el objetivo ya están condenados a no pasar** |
| `missing` | `() -> list[str]` | Requiere `statement` no vacío **y** `checks` no vacío |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` una por línea, quitando automáticamente marcas `-` / `*` / `1.` |
| `to_markdown` | `() -> str` | Si la lista está vacía, escribe `"(空)"` |
| `prompt_block` | `() -> str` | Versión compacta para alimentar aguas abajo |
| `write` / `load` | Igual que `Brief` | Volcado a disco y relectura |
| `amend` | `(extra: str) -> Goal` | **Añade, no sobrescribe**: concatena `"\n\n(已修改)" + extra` tras `statement` y devuelve `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

El resultado de una ronda de veredicto del [juez](glossary.md#判定者), **exactamente tres secciones**: conclusión / motivo / no superados.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`; `""` si no se pudo parsear |
| `reason` | `str` | `""` | Motivo |
| `failed` | `list[str]` | `[]` | Puntos de la lista que no se han superado |

| Miembro | Firma | Descripción |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Si se ha logrado parsear una conclusión o no. **`ok=False` hay que tratarlo como «no alcanzado», nunca como alcanzado** |
| `parse` | `@classmethod (text) -> Verdict` | Ver abajo |
| `feedback` | `() -> str` | Lo que se le devuelve al ejecutor: solo «qué falta», no la solución |

Orden de reconocimiento de `parse`:

1. Primero busca por sección con título 「结论」/「判定」.
2. Si no hay sección con título, tras hacer strip al bloque entero: `fullmatch(r"1|true")` → alcanzado; `fullmatch(r"0|false")` → aún no.
3. Si no, busca en el texto de la conclusión la primera coincidencia de la tabla de palabras de estado (**las palabras largas primero**).
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」 caen todas en `unreachable`**:
   comprobado a base de fallar: la plataforma objetivo era macOS, se ejecutaba en un contenedor Linux, y el juez miró la rama del código fuente y dio el visto bueno.
4. Si aún no hay nada → busca un `\b1\b` aislado → alcanzado; `\b0\b` → aún no.
5. Si nada casa → `state=""`, `ok=False`.

`unreachable` y `not_yet` **son dos conclusiones distintas**: la primera lleva por el camino de «parar y preguntar a una persona», no por el de «otra ronda».

---

## Capa de hooks {#hook}

Código fuente: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Esta capa es el **límite de ejecución** de flower: qué herramientas no puede tocar el hilo principal, cómo se recortan los resultados demasiado largos, qué rol va a un worktree independiente —
todo lo impone el hook del SDK, **no el prompt**. La razón es directa: el prompt es una sugerencia, el modelo puede ignorarlo; se ha medido que aunque el system prompt diga explícitamente «no uses worktree», la inyección de `isolate_guard` surte efecto igual (el modelo pasa `None`, lo que aterriza es `'worktree'`).

Nueve exportaciones: cinco fábricas de guard que devuelven `HookMatcher` (`whitelist_guard` puede devolver `None`), un ensamblador, un combinador y dos funciones de marcado de aislamiento.
No hace falta engancharlos a mano — [`Runtime`](#runtime) los monta automáticamente según el `AgentSpec`. Engancharlos a mano solo hace falta si conduces el SDK tú mismo (sin pasar por `Runtime`).

**La decisión de si es el hilo principal pasa siempre por una sola función**: `_is_main_thread(data) = not data.get("agent_id")` —
los datos del hook de tool-lifecycle de un subagent llevan `agent_id`, los del [hilo principal](glossary.md#主线程) no.
Todos los guards que «solo bloquean el hilo principal» se apoyan en esta línea.

Constantes de grupos de herramientas (a nivel de módulo, no exportadas, pero determinan los matchers por defecto):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Tabla rápida: qué guard va en qué evento del SDK {#hook-速查表}

| Función | Evento hook del SDK | matcher | Qué intercepta | Qué devuelve | Quién lo monta |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | de `Bash\|Write\|Edit\|NotebookEdit`, las que **no están en `allowed_tools`** | **solo el hilo principal** llamando a una herramienta prohibida | `permissionDecision: "deny"` + motivo | `Runtime._attempt`, **solo si `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (modificable con `tools=`) | **solo el hilo principal** actuando; con `allow_glance=True` se deja pasar el `Bash` que supere `is_ephemeral()` | `deny` + «despacha un subagent» | `workbench_hooks(delegate_only=True)`, **solo si `Runtime` tiene workbench** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` sin `cwd` ni `isolation`, y el `subagent_type` marcado con `isolated()` | `permissionDecision: "allow"` + `updatedInput` (inyecta `isolation="worktree"`) | `workbench_hooks`, **solo si hay algún rol marcado en `agents`** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` dentro de `workbench.root` | `{}` (el efecto es `workbench.refresh()`) | `workbench_hooks`, siempre |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **campos de tipo string** en `tool_response` con ≥ `threshold` caracteres; leer el propio directorio de spill se deja pasar | `updatedToolOutput` (volcado + una línea de puntero + los primeros 400 caracteres) | `workbench_hooks`, **solo si `spill_threshold` es verdadero** |

**La conclusión clave que se lee en esta tabla**: con `Runtime(workbench=False)` no se monta nada de `workbench_hooks`;
y para un coordinador con `delegate_only=True` también se salta `whitelist_guard` — **el hilo principal no tiene ni un muro**.
Ver el aviso en [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Hace que `allowed_tools` sea realmente excluyente para esas cuatro herramientas que actúan.**

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `allowed` | `list[str] \| None` | obligatorio, posicional | normalmente se le pasa directamente `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | cómo se autodenomina en el texto de rechazo. `Runtime` le pasa `spec.name` |

- **Va en `PreToolUse`**, el matcher es `"|".join(banned)`, donde `banned` = las de `Bash` `Write` `Edit` `NotebookEdit` que no estén en `allowed`.
- Si acierta, `permissionDecision: "deny"`, con un texto que viene a decir: «XX no tiene YY. **Es intencionado, no es que falte configuración.**
  Escribe la conclusión en el cuerpo de tu respuesta, el framework la recogerá de ahí — no intentes rodearlo con otra forma de escribirlo.»
- **Solo bloquea el hilo principal de esta sesión**, los subagents pasan — las herramientas de un subagent las decide `AgentDefinition.tools`.
- Si no hay nada que bloquear devuelve **`None`** (por ejemplo un rol como `worker()` con el juego completo de herramientas), y quien lo llama decide si lo monta o no.

**Por qué tiene que existir**: `allowed_tools` es una **lista de exención de aprobación, no una whitelist excluyente**. Dos pruebas medidas:
el juez que fijaba objetivos ejecutó `Bash` 11 veces; en la sonda de $0.1, un agent con
`allowed_tools=["Read"]` seguía pudiendo llamar a `Write`/`Bash`.
Por eso el «no tiene herramientas de escritura» de `clarify()` / `judge()` **se apoya en este hook**, no en la whitelist en sí.

La ventaja es que se deriva de `allowed_tools`, así que `judge(can_run=True)` conserva `Bash` automáticamente y sigue bloqueando `Write`/`Edit` — sin necesidad de un interruptor adicional.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**El hilo principal actúa por su cuenta → se rechaza, y se le indica el camino.**

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. Es una cadena regex, no una lista |
| `allow_glance` | `bool` | `False` | con `True`, si `tool_name == "Bash"` y [`is_ephemeral(command)`](#is-ephemeral) es verdadero, se deja pasar |

- **Va en `PreToolUse`**, el matcher es directamente `tools`.
- El hilo principal llama a una de esas cuatro herramientas → deny, y el motivo **indica el siguiente paso**: usa la herramienta `Agent` para despachar un subagent,
  escribe en el encargo el objetivo y los criterios de aceptación, y exígele que escriba los productos largos en `.flower/artifacts/` y que en la respuesta solo dé la ruta y la conclusión.
- Los subagents pasan siempre.

La diferencia con `whitelist_guard` está en la **formulación**: ambos bloquean el mismo conjunto de herramientas, pero este dice «despacha a alguien», que es lo pertinente.
Por eso un rol con `delegate_only=True` monta solo este; montar los dos haría que el modelo recibiera dos indicaciones contradictorias.

El criterio de paso de `allow_glance=True` y el de «¿se va a recortar este resultado?» son **la misma función** ([`is_ephemeral`](#is-ephemeral)):
el conjunto que se deja pasar debe ser igual al conjunto que caduca; si cambias uno, tienes que cambiar el otro.

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

Los resultados de herramienta que superen el umbral se [vuelcan a disco](glossary.md#落盘) **en el acto**, dejando en el contexto solo una línea de puntero — no se espera a que el contexto esté lleno para comprimir a posteriori.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workbench` | `Workbench` | obligatorio, posicional | el directorio de volcado es `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | a partir de cuántos caracteres se vuelca |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (por defecto) = también se vuelcan los resultados de los subagents |

- **Va en `PostToolUse`**, devuelve
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <lo recortado>}}`.
- El nombre del fichero volcado son los primeros 16 dígitos del `sha256` del contenido + `.txt`, y en el contexto se sustituye por una línea de puntero + los **primeros 400 caracteres**.
- `updatedToolOutput` **debe conservar la estructura de salida de la herramienta original**, así que solo se sustituyen los **campos string** demasiado largos del dict;
  **las list no se tocan nunca** (pueden contener bloques de imagen). Si la estructura no cuadra, se rechaza (el original queda tal cual, sin error).
- **Al leer el propio fichero volcado hay que dejar pasar** — si no, «léelo con `Read`» es una frase vacía: el texto completo que se lee vuelve a volcarse, bucle infinito.
  Se topó con esto en pruebas reales: el modelo intentó cinco formas seguidas de rodearlo.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Si se escribe algo en el [workbench](glossary.md#工作台), refresca `INDEX.md`, y el siguiente agent sabe desde el arranque que eso existe.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workbench` | `Workbench` | obligatorio, posicional | ámbito de la comprobación y objeto a refrescar |

**Va en `PostToolUse`**, matcher `"Write|Edit"`. Si `tool_input["file_path"]` tras resolverse cae dentro de
`workbench.root`, llama a `workbench.refresh()`. **Siempre devuelve `{}`** — no modifica nada, solo tiene efectos secundarios.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Asigna un git worktree independiente al subagent según su rol, implementando el [aislamiento](glossary.md#隔离).

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | obligatorio, posicional | tabla de roles, para consultar si el `subagent_type` está marcado |
| `on_inject` | `Any` | `None` | callback opcional, se llama como `on_inject(subagent_type, description)` |

**Va en `PreToolUse`**, matcher `"Agent"`. Solo se inyecta si se cumplen tres condiciones a la vez: `tool_name == "Agent"`,
`tool_input` **no tiene ni `cwd` ni `isolation`**, y el rol correspondiente al `subagent_type` está marcado con `isolated()`.
Si se cumplen, devuelve `permissionDecision: "allow"` + `updatedInput` (poniendo `isolation` a `"worktree"`).

`isolation` y `cwd` son **mutuamente excluyentes** en la herramienta `Agent` — si el modelo ha especificado `cwd` por su cuenta, se respeta.
«Aislar o no» es una **propiedad del rol**, no un interruptor global ni algo que se decida en cada despacho; a un rol que no necesita aislamiento no se le añade ni un byte.

**Si activas el aislamiento tienes que sacar el [workbench](glossary.md#工作台) del repositorio.** Un agent aislado no puede escribir en el checkout compartido,
así que el workbench debe apuntar fuera del repositorio con `home=`. `starter_flow(isolate=True)` usa
`<ws>.parent/.flower-<ws.name>`, y `Runtime(workbench=True)` usa `<run_dir>/workbench` —
ambos están fuera del repositorio, **pero no son el mismo directorio**, no los mezcles.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Marca una definición de subagent como «necesita espacio de trabajo propio», y lee esa marca de vuelta.

| Función | Parámetro | Por defecto | Descripción |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | obligatorio | la definición a marcar. **Devuelve el mismo objeto** |
| | `flag: bool` | `True` | posicional. `False` = quita la marca |
| `wants_isolation` | `agent: AgentDefinition \| None` | obligatorio | acepta también `None`, devuelve `False` |

La marca es un atributo del lado Python, `_flower_isolate`, puesto con `object.__setattr__`, **no un campo del dataclass** —
el SDK serializa con `asdict()` y solo reconoce los campos declarados, así que esta marca no se filtra al CLI (comprobado).

**El precio**: hacer `dataclasses.replace()` sobre un `AgentDefinition` pierde esta marca, y el aislamiento deja de funcionar en silencio.

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

Monta de una vez los hooks que necesita el workbench. Es lo que llama `Runtime._attempt`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workbench` | `Workbench` | obligatorio, posicional | se pasa a `index_guard` y a `spill_guard` |
| `delegate_only` | `bool` | `True` | solo con `True` se monta `delegate_guard` |
| `spill_threshold` | `int \| None` | `4000` | solo si es verdadero se monta `spill_guard` |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | si **alguno** está marcado con `isolated()`, se añade `isolate_guard` |
| `allow_glance` | `bool` | `False` | se pasa tal cual a `delegate_guard(allow_glance=)` |

Resultado:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  si hay roles marcados → se añade `isolate_guard(agents)`.
- `PostToolUse`: siempre `[index_guard(workbench)]`; si `spill_threshold` es verdadero → se añade
  `spill_guard(workbench, threshold=spill_threshold)`.
- **Las claves de evento con lista vacía se eliminan**, no se devuelven listas vacías.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Concatena** varios grupos de configuración de hooks por nombre de evento.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | variádico | tantos grupos como quieras. Los grupos `None` se saltan |

Usa `extend`, **no deduplica** — pasar el mismo guard dos veces lo monta dos veces. `Runtime` lo usa para combinar `spec.hooks`,
`workbench_hooks(...)` y `whitelist_guard`.

---

## Workbench {#工作台}

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

El directorio de trabajo donde se vuelca todo: tres subdirectorios + un índice. El índice **se inyecta en el system prompt**, así que el agent sabe en cada turno qué tiene a mano.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `workspace` | `Path` | obligatorio, posicional | el espacio de trabajo. `__post_init__` lo resuelve |
| `dirname` | `str` | `".flower"` | nombre del directorio del workbench, relativo a `workspace` |
| `max_index_entries` | `int` | `40` | **solo afecta a `prompt_block()`**: cuántas entradas por categoría se listan como máximo en el fragmento inyectado en el system prompt; el resto se resume en una línea «…y otras N». El propio `INDEX.md` no tiene límite, lista todo |
| `home` | `Path \| None` | `None` | si se da, se usa como `root` e **ignora `dirname`**. Cuando no es `None` también se resuelve |

| Miembro | Firma | Descripción |
|---|---|---|
| `root` | `@property -> Path` | si hay `home` se usa, si no `workspace / dirname` |
| `external` | `@property -> bool` | si `root` está **fuera** de `workspace`. En modo aislado debería ser `True` |
| `scripts` | `@property -> Path` | `root / "scripts"`, scripts que se van a ejecutar más de una vez |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, productos largos de más de 2000 caracteres |
| `notes` | `@property -> Path` | `root / "notes"`, decisiones clave, un fichero por decisión |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | la ruta que ve el modelo: relativa si está dentro del espacio de trabajo, absoluta si está fuera |
| `ensure` | `() -> Workbench` | hace mkdir de los tres directorios y devuelve `self` (encadenable: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(ruta mostrada, descripción, bytes)`. `rglob("*")` recursivo, se saltan los ficheros que empiezan por `.` |
| `refresh` | `() -> str` | reescribe `INDEX.md` y devuelve el contenido |
| `prompt_block` | `() -> str` | **el fragmento que se inyecta en el system prompt**. Deliberadamente corto — está presente en cada turno |

Formato de autodescripción de los scripts: `# desc: 一句话` dentro de las primeras 8 líneas (también acepta `//` y `--` como marcadores de comentario),
degradando al primer comentario no vacío o a la primera línea del docstring (truncada a 100 caracteres).

Las tres reglas que inyecta `prompt_block()`:

1. Los scripts que se vayan a ejecutar más de una vez se escriben en `scripts/`, con `# desc:` en la primera línea.
2. Los productos de más de **2000 caracteres** se escriben en `artifacts/`, y en la conversación solo se da la ruta y la conclusión.
3. Las decisiones clave se escriben en `notes/`, un fichero por decisión.

Con `external=True`, `prompt_block()` añade una frase extra: «accede a ello con ruta absoluta».

**El índice no lo heredan los subagents.** Va por el `system_prompt.append` a nivel de sesión, y un subagent tiene su propio
system prompt (medido: $0.2461). Por eso esas dos cosas —«los productos largos van a `artifacts/`» y «dónde está el workbench»— tiene que transmitirlas el
[coordinador](glossary.md#协调者) en el [brief de tarea](glossary.md#任务书): **ese es el único canal**, no es redundancia.
En `WORKER_RULES` **no está escrito a propósito**: la ruta real la genera `Workbench`, dejarla fija sería un error.

---

## Almacén de sesiones {#会话存储}

Código fuente: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Tres niveles de herencia: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime` **usa siempre el más externo**; las políticas de los tres niveles se controlan por parámetros del constructor.

Cada nivel se ocupa de una cosa: volcar a disco, [recortar](glossary.md#裁剪) por volumen y valor, y [podar](glossary.md#剪除) según «esto es un error o no».
Tanto el recorte como la poda ocurren en el momento de **`load()`** (es decir, cuando el resume devuelve el historial al modelo); el registro original en SQLite no se toca ni un byte.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implementa el protocolo `SessionStore` del SDK, con tres tablas: `entries` / `meta` / `summaries`.
La clave del store es `project_key/session_id[/subpath]` — **los transcripts de los subagents se distinguen por el subpath**.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `path` | `str \| Path` | obligatorio, posicional | fichero de base de datos. La conexión usa `check_same_thread=False` |

| Método | Firma | Descripción |
|---|---|---|
| `append` | `async (key, entries) -> None` | deduplicación idempotente por uuid (primero descarta lo ya persistido, luego los duplicados dentro del lote). Al reproducir un lote entero **no avanza el mtime ni vuelve a plegar el summary**; solo el transcript principal (`subpath is None`) participa en el summary |
| `projects` | `() -> list[str]` | los `project_key` que existen realmente en la base. **El SDK lo deriva del cwd; confírmalo con esto antes de consultar, no lo adivines** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **síncrono, no lee el payload**, solo consulta una fila de meta. Sirve para la «continuidad en la misma ruta»: hacer resume de una sesión inexistente no revienta hasta que arranca el subproceso |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | cuánto contexto vio realmente el modelo en el último turno; devuelve `0` si no se encuentra. Solo escanea hacia atrás las últimas `scan` entradas; cuenta los tres términos `input + cache_read + cache_creation` (mirar solo `input_tokens` subestima gravemente) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | ordenado por seq; si no hay filas devuelve `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | solo el transcript principal |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | lista los resúmenes de sesión |
| `delete` | `async (key) -> None` | al borrar el transcript principal **borra en cascada los de los subagents**, para evitar huérfanos |
| `list_subkeys` | `async (key) -> list[str]` | lista los subtranscripts de esa sesión |
| `close` | `() -> None` | cierra la conexión |

El `_next_mtime` interno garantiza **monotonía estricta** — `list_sessions` y el sidecar de summary comparten este reloj;
si no, la ruta rápida de staleness del SDK se equivocaría.

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
| `keep_recent` | `int` | `20` | los N `tool_result` más recientes conservan el texto original |
| `min_chars` | `int` | `2000` | los resultados cortos no merecen recorte |
| `spill_dirname` | `str` | `".flower/spill"` | **relativo a `workspace`, tiene que estar dentro del espacio de trabajo** — si no, el `Read` del agent no lo alcanza |
| `enabled` | `bool` | `True` | con `Runtime(trim=False)` esto es `False` |

| Método | Firma | Descripción |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | genera la línea de puntero que sustituye al cuerpo |

**Los dos directorios de spill no son el mismo.** `spill_guard` vuelca en `<workbench.root>/spill/` (puede estar fuera del espacio de trabajo);
`TrimPolicy.spill_dirname` vuelca en `<workspace>/.flower/spill/` (**tiene que estar dentro del espacio de trabajo**).
Corresponden respectivamente a «recortar en el acto» y «recortar al hacer resume»; que sean directorios distintos es intencionado, no los unifiques.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Política de caducidad de los resultados de los [comandos efímeros](glossary.md#一次性命令).

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `enabled` | `bool` | `True` | si se desactiva, no se marca nada como caducado |
| `keep_recent` | `int` | `6` | los N más recientes quedan exentos. **Mucho menor que el 20 de `TrimPolicy`** |
| `max_chars` | `int` | `2000` | si se supera se salta, y lo archiva `TrimPolicy` |
| `text` | `str` | ver la firma | texto de sustitución, con los dos marcadores `{cmd}` y `{age}` |

| Método | Firma | Descripción |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | aplica `text` para generar el cuerpo de sustitución |

**Solo actúa sobre los resultados de la herramienta `Bash`**, y el comando debe coincidir con la whitelist de comandos efímeros. **`Read` no entra aquí**:
el contenido de un fichero no se desvirtúa con el paso del tiempo hasta el punto de inducir a error. El contenido caducado **no se vuelca**, se tira directamente.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Decide si un comando Bash es un [comando efímero](glossary.md#一次性命令).
**La decisión de paso de `delegate_guard` y la de caducidad del recorte comparten esta misma función**: el conjunto de comandos que el coordinador puede ejecutar por sí mismo
tiene que ser igual al conjunto de resultados que se marcan como caducados. Dejar pasar sin recortar hace que un `git status` caducado ocupe contexto para siempre y además induzca a error;
recortar sin dejar pasar hace que el coordinador despache un subagent para un `ls`, cambiando 4.3k de coste de arranque por unas decenas de caracteres.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `cmd` | `str` | obligatorio, posicional | la línea de comandos completa |

Orden de decisión:

1. Vacío / todo espacios → `False`.
2. Sustitución de comandos (`$(`, comillas invertidas, `<(`, `>(`) o cualquier forma «que cambia estado» → `False`.
3. Si tras quitar las redirecciones seguras (`2>&1`, `&> /dev/null` y similares) sigue habiendo `>` o `<` → `False`.
4. Si tras quitar `&&` / `||` / `;` / `|` queda un `&` suelto (ejecución en segundo plano) → `False`.
5. Se parte por `&&` / `||` / `;` / `|`, y **cada tramo tiene que estar en la whitelist**.

Grandes categorías de verbos en la whitelist: subcomandos de `git` de solo lectura (`status`, `diff`, `log`, `show`, `branch`, `rev-parse`, etc.),
información de directorios y sistema (`ls`, `pwd`, `df`, `du`, `date`, `whoami`, `env`, etc.), procesos y contenedores
(`ps`, `top`, `lsof`, `docker ps`, `kubectl get`, etc.), ver ficheros (`cat`, `head`, `tail`, `wc`, `stat`, `find`, `tree`),
buscar rutas (`which`, `whereis`, `command -v`, `type`), procesamiento de texto (`grep`, `rg`, `sort`, `uniq`, `awk`, `sed`, `jq`, `diff`, etc.).

Aunque el verbo esté en la whitelist, estas formas se bloquean igual: `xargs`, `exec`, `eval`, `source`, `tee`,
`find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` y `print >` dentro de `awk`,
`git branch -D/-d/-m`, `git * --force/--hard/--prune`.

La primera versión rechazaba de un plumazo todos los comandos compuestos, y **en pruebas reales dejó el glance completamente inútil** (los tres intentos del coordinador fueron bloqueados),
así que se cambió a evaluar tramo por tramo.

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
| `path` | `str \| Path` | obligatorio | fichero de base de datos |
| `workspace` | `str \| Path` | obligatorio | base para el directorio de volcado |
| `policy` | `TrimPolicy \| None` | `None` | si no se da, se usa el `TrimPolicy()` por defecto |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | si no se da, se usa el `EphemeralPolicy()` por defecto |

Atributos públicos: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Orden de `load()`: `super().load()` → vaciar `last_report` → si `ephemeral.enabled`, `expire()` →
si `policy.enabled`, `trim()`. **Con `enabled=False` ese paso se salta entero.**

| Método | Descripción |
|---|---|
| `expire(entries)` | a los resultados de `Bash` caducados **solo les cambia el cuerpo, conserva el bloque**. El comando se busca en el `tool_use` del mensaje assistant anterior; se saltan los `isCompactSummary` / `isMeta`; los que superan `max_chars` se saltan (los archiva `trim`); los últimos `keep_recent` quedan exentos. Escribe `last_report["expired"]` |
| `trim(entries)` | el cuerpo de los `tool_result` con `>= min_chars` se vuelca a `<workspace>/<spill_dirname>/<primeros 16 dígitos del sha256>.txt`, y el contenido del bloque se sustituye por un puntero; los últimos `keep_recent` quedan exentos. Escribe `cleared` / `kept` / `chars_saved` en `last_report` |

**Solo recorta texto plano**: los bloques `image` / `document` se dejan tal cual.

**Dos líneas rojas estructurales**: el bloque `tool_result` **tiene que seguir ahí**, solo se puede cambiar el content (si falta uno, es
«Missing Tool Result Block»); las entradas `isCompactSummary` no se tocan.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Renderiza `store.last_report` en una línea en chino, para el log de la UI.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | obligatorio, posicional | acepta también la subclase `PruningSessionStore` |

Tres salidas posibles: sin acción → `"未裁剪"`; solo caducidades → `"N 个时效性结果标记为过期"`;
en otro caso `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, donde X = `chars_saved // 4`.

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    heal_orphans: bool = True
    orphan_text: str = "[这一步被打断了,没有结果。需要的话重做。]"
    keep_denials: int = 1
```

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | elimina los mensajes de error de API sintéticos (restos de una desconexión) |
| `neutralize_interrupts` | `bool` | `True` | sustituye por una explicación neutra los `tool_result` que quedaron de una interrupción |
| `interrupt_text` | `str` | ver la firma | texto de la explicación neutra |
| `heal_orphans` | `bool` | `True` | añade un resultado sintético a las llamadas huérfanas que tienen `tool_use` pero no `tool_result` |
| `orphan_text` | `str` | ver la firma | cuerpo del `tool_result` que se añade |
| `keep_denials` | `int` | `1` | conserva las N últimas llamadas de herramienta rechazadas |

`heal_orphans` cura el caso de **que tras una interrupción el resume dé 400 cada vez**: la interrupción corta en el límite de un mensaje, y el
`tool_use` que estaba en vuelo puede no tener ningún `tool_result` detrás, mientras que la API exige que vayan en pareja — ese historial corrupto se queda en el transcript,
y a partir de ahí **cada** resume rebota por su culpa. `heal_orphans()` inserta una entrada `user` justo después del assistant que contiene el huérfano
para completar el resultado que falta, y cambia el `parentUuid` que apuntaba a ese assistant para que apunte a la entrada añadida, manteniendo la cadena continua
(`prune.py:95-147`). **Se añade, no se borra**: borrar el huérfano obligaría a reconectar la cadena padre-hijo del assistant, y en esa misma entrada puede haber bloques normales,
texto y thinking, con riesgo de arrastrarlos (`prune.py:195-204`).

El motivo de `keep_denials`: una llamada rechazada nunca llegó a ejecutarse, su resultado no tiene información, pero ocupa bastante (medido: 273 caracteres en un caso =
93 caracteres de texto de rechazo + 180 caracteres del **comando muerto original**). Y lo más importante: **induce a error** — se observó que, tras leer unas cuantas
«no uses Bash directamente», el coordinador dejó de intentar incluso los `git status` permitidos, aprendiendo indefensión adquirida.
**Por defecto se deja 1 y no 0**: el rechazo más reciente evita que el modelo reintente una y otra vez el mismo comando bloqueado dentro del mismo turno.

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
| `path` | `str \| Path` | obligatorio | fichero de base de datos |
| `workspace` | `str \| Path` | obligatorio | base para el directorio de volcado |
| `policy` | `TrimPolicy \| None` | `None` | política de recorte |
| `prune` | `PrunePolicy \| None` | `None` | política de poda |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | política de caducidad |

Además de los del padre, tiene tres atributos públicos: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (primero `expire` + `trim`) → `self.prune(entries)`. `prune` hace tres cosas:

1. **Elimina las llamadas rechazadas antiguas**: se detectan por la marca estructural del harness `toolDenialKind == "permission-rule"`
   (más fiable que hacer coincidir el texto del rechazo), conserva las últimas `keep_denials` y en el resto elimina el bloque `tool_use` **y** el `tool_result`
   juntos. Si un mismo mensaje assistant tiene varios `tool_use`, **solo se elimina el afectado**; si no, se convertiría en un
   «Missing Tool Result Block». Los bloques de texto y de thinking se conservan.
2. **Elimina los mensajes de error de API sintéticos.** En SQLite se conservan tal cual, simplemente no se devuelven al modelo.
3. **Sustituye por una explicación neutra los `tool_result` que quedaron de una interrupción** — solo cambia el cuerpo, no elimina la entrada.

**La única línea roja estructural**: el transcript es una cadena simple por `parentUuid`, y al eliminar una entrada hay que reenganchar sus hijos al ancestro vivo más cercano.
El `entries` que recibe el `relink` interno **tiene que ser la lista completa (incluidas las que se van a eliminar)**, el filtrado lo hace él —
si quien lo llama las quita antes de pasarlas, la cadena se rompe ahí y se pierde todo el historial anterior (**ya pisado: no se manifiesta si las entradas eliminadas están al final,
pero revienta si están en medio**).

**El orden de los parámetros difiere del de la clase padre**: en el padre es `(path, workspace, policy, ephemeral)`, y en la subclase es
`(path, workspace, policy, prune, ephemeral)` — **el cuarto parámetro posicional pasa de `ephemeral` a `prune`**,
y pasarlos por posición desalinea silenciosamente. Pásalos siempre por palabra clave.

---

## Resiliencia {#韧性}

Código fuente: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

Cuando se cae la red, se queda esperando en vez de terminar con fallo. Cuatro exportaciones: un dataclass de política + tres funciones de sondeo utilizables por separado.

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
| `enabled` | `bool` | `True` | si se desactiva, ningún fallo se reintenta |
| `max_attempts` | `int` | `6` | **incluye el primer intento** |
| `base_delay` | `float` | `4.0` | base del backoff, en segundos |
| `max_delay` | `float` | `120.0` | tope del backoff, en segundos |
| `probe_timeout` | `float` | `5.0` | timeout de una sonda individual |
| `probe_interval` | `float` | `15.0` | cuánto se espera entre dos sondas |
| `max_offline_wait` | `float` | `3600.0` | cuánto se espera como máximo colgado; por defecto 1 hora |
| `retry_unknown` | `bool` | `True` | si se reintentan los errores que no se pueden clasificar |
| `resume_prompt` | `str` | ver la firma | lo que se dice al continuar. **Deliberadamente sin ningún detalle del error** — el modelo necesita saber «te interrumpieron, sigue», no si fue un `ENOTFOUND` o un 503 |

| Método | Firma | Descripción |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` multiplicado por `0.75 + random()*0.5` (jitter de ±25%) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, o `kind == "unknown"` con `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | espera colgado a que vuelva la red. Devuelve `True` si vuelve, `False` si se supera `max_offline_wait`. `notify` es un callback `(str) -> None`, que se emite una vez **la primera vez que no hay alcance** y otra **al recuperarse** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Clasifica el texto de error en tres categorías: `"transient"` / `"fatal"` / `"unknown"`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `text` | `str \| None` | obligatorio, posicional | el mensaje de error original. Si está vacío devuelve `"unknown"` |

**Primero se comprueba fatal y luego transient** — los textos de errores como 401 suelen llevar la palabra `connection`, y con el orden invertido se esperaría eternamente.

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
| `host` | `str` | obligatorio, posicional | nombre de host |
| `port` | `int` | obligatorio, posicional | puerto |
| `timeout` | `float` | `5.0` | segundos |

**Solo hace DNS (`getaddrinfo`) + handshake TCP**, no envía HTTP, no lleva credenciales, **no cuesta dinero**. Cualquier excepción cuenta como inalcanzable.

---

## Eventos e interacción {#事件与交互}

Código fuente: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

Un [evento](glossary.md#事件) es la estructura estable a la que se aplana el flujo de mensajes del SDK. **La [capa de interacción](glossary.md#交互层) solo conoce
`Event`, no importa ningún tipo del SDK** — esa es la frontera que permite cambiar de UI sin tocar el núcleo. Véase [cambiar la capa de interacción](../guide/interaction.md).

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
| `kind` | `EventKind` | obligatorio | véase la tabla siguiente |
| `text` | `str` | `""` | cuerpo del texto |
| `tool` | `str` | `""` | nombre de la herramienta, solo en `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | información adicional estructurada |
| `raw` | `Any` | `None` | objeto original del SDK, para cuando quieras escarbar |

`__str__`: en `tool_call` es `f"[{tool}] {text}"`, en el resto es `text`, y si `text` está vacío, `f"<{kind}>"`.
Así que `print(ev)` es directamente legible.

`EventKind` tiene **15** valores:

| kind | Quién lo emite | Descripción |
|---|---|---|
| `text` | `normalize` | cuerpo del assistant |
| `thinking` | `normalize` | bloque de pensamiento |
| `tool_call` | `normalize` | llamada a herramienta. `text` es un resumen de `file_path` / `command` / `pattern`, cortado a 200 caracteres |
| `tool_result` | `normalize` | resultado de herramienta. `text` cortado a 500 caracteres, el payload lleva `tool_use_id` / `is_error` |
| `task` | `normalize` | los tres tipos de mensaje Task. `text` **está vacío**, el nombre de clase va en `payload["kind"]` |
| `system` | `normalize` | el resto de mensajes de sistema, `text` es el subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, el payload lleva `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | mensaje sintético de error de API, el payload lleva `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **El cuerpo es entrada, no producción del modelo**, por eso no entra en `StepResult.text` |
| `unknown` | `normalize` | lo que no se reconoce |
| `retry` | `Runtime` | aviso de reintento |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | en el payload, `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | pregunta, **y también transporta «lo que la persona dice por iniciativa propia»** |

**Los cuatro últimos no los produce `normalize()`.**

El `payload` de todos los eventos de assistant / user lleva:

| Clave | Tipo | Descripción |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | solo cuando `subagent` es verdadero |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **Es la única fuente del criterio de [handoff](glossary.md#换代)**, y también el número que más merece verse en una ejecución long-horizon |

**El kind `ask` transporta a la vez «una pregunta» y «lo que la persona dice por iniciativa propia».** En el segundo caso `payload["kind"] == "mail"`,
y **no hay `options` / `remaining`**. La UI debe mirar primero `payload.get("kind")` antes de decidir cómo renderizar;
si no, dejará colgada una frase suelta como si fuera una pregunta pendiente de respuesta.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Aplana un mensaje del SDK en de 0 a N `Event`.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `message` | `Any` | obligatorio, posicional | cualquier objeto de mensaje del SDK |

Ramas clave:

- **Mensaje sintético de error de API** (`isApiErrorMessage=True` o `model == "<synthetic>"`) → un único
  `Event("error", payload={"synthetic": True})`. **Esto es deliberado** — si no, el texto de la caída se tomaría como cuerpo,
  entraría en `StepResult.text` y se pasaría al paso siguiente.
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
| `id` | `str` | obligatorio | se usa para localizarla al responder |
| `question` | `str` | obligatorio | texto de la pregunta |
| `options` | `list[str]` | `[]` | opciones. La persona también puede no elegir ninguna y escribir |
| `asked_at` | `float` | `time.time()` | momento de la pregunta |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | texto de la respuesta |

| Miembro | Firma | Descripción |
|---|---|---|
| `waited_s` | `@property -> float` | cuánto lleva esperando |
| `event` | `(remaining: int = 0) -> Event` | produce `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

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

Un **servidor MCP dentro del proceso** (dos herramientas) más un conjunto de métodos para la UI. El modelo solo ve
`mcp__human__ask` y `mcp__human__inbox`. Todos los parámetros del constructor son keyword-only.

| Parámetro | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | salida del modo **push**. Si lo das, `Workflow.run` ya no cablea nada |
| `max_asks` | `int \| None` | `None` | **sin límite de veces**. Un número es una cuota dura, `0` = prohibido preguntar (totalmente automático / CI). Al agotarse, la herramienta **rechaza directamente, sin bloquear** |
| `timeout_s` | `float \| None` | `1800.0` | 30 minutos. `None` = esperar para siempre; **`<= 0` = no esperar, todas las preguntas quedan en nada de inmediato** |
| `log_path` | `str \| Path \| None` | `None` | preguntas y respuestas **se añaden** a disco, no ocupan contexto |
| `amend_path` | `str \| Path \| None` | `None` | lo que la persona diga durante la ejecución se añade a este fichero (normalmente el brief). **Si no se escribe a disco no sobrevive al límite del paso** — el paso siguiente es una sesión nueva que solo lee el artefacto congelado |
| `over_budget_text` | `str` | constante del módulo | lo que se le devuelve al modelo al agotar la cuota |
| `timeout_text` | `str` | constante del módulo | lo que se le devuelve al modelo al vencer el plazo |
| `declined_text` | `str` | constante del módulo | lo que se le devuelve al modelo cuando se salta la pregunta |

Atributos públicos: los ocho con el mismo nombre que los parámetros del constructor, más `asks: list[Ask]`, `mail: list[Mail]` y
`ui_errors: list[str]` (**aquí se recogen las excepciones lanzadas por los callbacks de la UI, sin interrumpir la ejecución**).

| Miembro | Firma | Descripción |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | se pasa directo a `AgentSpec.mcp_servers`. **El nombre de la clave debe coincidir con el del server**, por eso lo da él mismo |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | se queda colgado esperando a la persona. **Nunca lanza excepciones salvo `CancelledError`** — que nadie responda también es una respuesta, se distingue con `ask.state` |
| `send` | `(text: str) -> Mail \| None` | la persona dice algo por iniciativa propia. **Se puede llamar desde cualquier hilo**. No interrumpe al agente; internamente llama a `amend()` |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | añade a `amend_path`. Devuelve si realmente escribió (sin ruta configurada, texto vacío o `OSError` dan `False`) |
| `pending_mail` | `() -> list[Mail]` | mail que aún no se ha recogido |
| `remaining` | `@property -> int` | cuántas preguntas quedan. **Con `max_asks=None` devuelve `-1`**, ni 0 ni infinito |
| `pending` | `() -> list[Ask]` | preguntas colgadas esperando respuesta |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | para el modo **pull**. Al vencer el plazo devuelve `None`; si se cancela, lanza |
| `answer` | `(ask_id: str, text: str) -> bool` | responder. `False` = esa pregunta ya no está esperando (venció / ya respondida) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | saltarla y dejar que el modelo decida por su cuenta |
| `transcript` | `() -> str` | markdown con el registro de preguntas y respuestas |

**Elige una de las dos formas de recoger**: **push** — construir `HumanChannel(on_event=...)`; **pull** — `await channel.next_ask()`.
`Workflow.run` solo cablea automáticamente cuando `channel.on_event is None`, así que si lo pasas tú no se sobrescribe.

**Entre hilos**: `answer` / `decline` / `send` pasan internamente por `loop.call_soon_threadsafe`,
lo normal es llamarlos directamente desde el backend web o el hilo de entrada de la TUI.

Las tres semánticas de «0 / None» son distintas, no las mezcles: `max_asks=None` = sin límite, `max_asks=0` = prohibido preguntar;
`timeout_s=None` = esperar para siempre, `timeout_s<=0` = vencer de inmediato; `remaining` con `max_asks=None` es `-1`.

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

Registra entre procesos «qué paso usó qué sesión»; la [continuidad](glossary.md#接续) se apoya en él para encontrar dónde se quedó la vez anterior.
El fichero es `<run_dir>/lineage.json`.

| Campo | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `path` | `Path` | obligatorio | ruta del fichero de linaje |
| `workspace` | `Path` | obligatorio | espacio de trabajo. `__post_init__` hace resolve |
| `steps` | `dict[str, str]` | `{}` | nombre del paso → `session_id` |
| `woke` | `int` | `0` | cuántas veces se ha despertado |

| Miembro | Firma | Descripción |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | lee `<run_dir>/lineage.json`. **Si el fichero no existe, no se puede leer o el campo `workspace` no cuadra, devuelve uno vacío sin error** |
| `remember` | `(step: str, session_id: str) -> None` | guarda el mapeo y **escribe a disco de inmediato**. Con step vacío o sid vacío retorna sin más |
| `bump` | `() -> int` | suma 1 al contador de despertares, escribe a disco y devuelve el nuevo valor (la primera ejecución es `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **mueve** el fichero de linaje más `extra` a `<into>/<YYYYmmdd-HHMMSS>/` y pone `steps` / `woke` a cero. **Mover no es borrar** |

La escritura usa reemplazo atómico `tmp.replace(path)`; los `OSError` se tragan en silencio — que falle la escritura a disco no debe llevarse por delante la ejecución.

**`workspace` es un guardia**: la `project_key` del SDK se deriva de la ruta del espacio de trabajo; si el directorio se copia a otro sitio, los `session_id` antiguos no se encuentran,
así que cuando la ruta no cuadra se hace como si no hubiera nada.

Cuando `Workflow.run` carga el linaje, verifica cada registro uno a uno con `runtime.has_session(sid)` para ver si sigue en la base, y solo usa los vivos —
el fichero de linaje puede sobrevivir a `sessions.db`.

---

## Ejemplos mínimos utilizables {#示例}

Los cinco fragmentos se pueden ejecutar tal cual. Requisitos: tener instalado `claude-agent-sdk` y disponer de `ANTHROPIC_API_KEY` o `ANTHROPIC_AUTH_TOKEN`
(si no, `Runtime(...)` lanza `RuntimeError` ya en la construcción).

### Un agente ejecuta un paso {#示例-单-agent}

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

    # workbench=True es obligatorio: delegate_guard se engancha en workbench_hooks,
    # sin workbench el Bash/Write del coordinador no tiene ningún hook que lo pare.
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

Los dos primeros parámetros de `worker()` son posicionales: `description` (lo que usa el coordinador para elegir a quién delegar) y `prompt` (su system prompt,
al que luego se le concatena `WORKER_RULES` automáticamente). Los tres primeros de `coordinator()` son posicionales: `name`, `instructions`, `workers`.

### Escribir tu propio Workflow {#示例-workflow}

Dos pasos; el segundo inyecta el resultado del primero en su propio prompt — barato, aislado, sin sesión compartida.

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
        # Sesión nueva + el resultado del paso anterior inyectado en el prompt (barato, evita contaminación)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Si quieres seguir hablando en la misma sesión, escribe resume_from="造句"; para bifurcar, añade fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (cuando no se da reduce)
    print(ctx["_sessions"])            # nombre del paso -> session_id
    print(ctx.get("_failed_at"))       # con on_fail="stop", en qué paso falló


asyncio.run(main())
```

Los tres primeros campos de `Step` (`name` / `spec` / `prompt`) son posicionales, y `steps` de `Workflow` también.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` posicional, los dos callbacks keyword-only.
**Ojo: `continuous=True` es el valor por defecto**: al ejecutar por segunda vez con el mismo `run_dir` y el mismo `workspace`,
incluso los pasos con `resume_from=None` seguirán hablando en la sesión de la vez anterior.

### Añadir un goal guard {#示例-目标}

Primero deja que el [judge](glossary.md#判定者) fije el objetivo y la lista de verificación, y luego que el paso que trabaja acepte el veredicto —
si no pasa, se repite con la retroalimentación, hasta tres rondas.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = totalmente automático: todas las preguntas quedan en nada de inmediato, sin fingir que se espera a alguien
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds es el **total de rondas**: rounds=3 → retries=2 → como mucho tres rondas de trabajo
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
    print(ctx["_verdict"])     # VERDICT_KEY: el Verdict más reciente
    print(ctx["_goal_rounds"]) # ROUND_KEY: cuántas rondas se han corrido
    print(ctx.get("_aborted")) # motivo del StepAbort (cuando es inalcanzable y nadie responde)


asyncio.run(main())
```

`with_goal` solo sustituye `gate` / `on_reject` / `retries`; el resto de campos se arrastran tal cual con `dataclasses.replace`.
El judge es una **sesión independiente**: dentro de `gate` se llama por separado a `rt.run(judger, ..., step_name=f"{label}#{轮次}")`,
con `resume` siempre a `None`.

### Cambiar la capa de interacción {#示例-交互层}

Para pasar del terminal a Web / TUI / HTTP solo hay que cambiar dos cosas: la función que renderiza los `Event` y la corrutina que recoge las preguntas.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """把 Event 渲染成你自己的 UI —— 这是唯一需要换的东西。"""
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
    # los kind == "ask" que no son mail los gestiona el answerer de abajo (modo pull)


async def answerer(ch: HumanChannel) -> None:
    """拉式取提问。换成 Web 后端 / HTTP 服务时,这个协程是唯一要改的地方。"""
    while True:
        ask = await ch.next_ask()          # sin timeout, espera indefinidamente
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # o ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # El Runtime usa el workbench que el propio workflow ya creó — no montes otro
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
`Workflow.run` solo cablea automáticamente cuando `channel.on_event is None`, así que si pasas tú un `on_event` no se sobrescribe.
`answer()` / `decline()` / `send()` / `interrupt()` **se pueden llamar desde otros hilos**.

---

## Trampas y errores frecuentes {#陷阱}

Ordenados por el orden en que se tropieza con ellos, no por módulo. Cada uno viene de una medición real.

### Montaje {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = el main thread no tiene ni un muro.**
   `delegate_guard` solo se instala si hay workbench, y `whitelist_guard` queda saltado por `delegate_only=True`.
   Si usas un coordinador, abre el workbench. Véase [Runtime](#runtime).
2. **Hay dos ubicaciones de workbench, no las confundas.** `Runtime(workbench=True)` cae en `<run_dir>/workbench`;
   `Workbench(ws)` por defecto es `<ws>/.flower`. Si montas `brief_path` a mano, hazlo según la segunda,
   porque **el brief se escribe en el directorio A, el índice inyectado escanea el directorio B, y no salta ningún error**.
   Lo correcto: que el workflow haga `Workbench(...).ensure()` y lo cuelgue en `Workflow.workbench`,
   y luego entregar **el mismo objeto** a `Runtime(workbench=wb)`.
3. **`allowed_tools` no es una lista blanca excluyente, es una lista de exención de aprobación.** El modelo puede seguir llamando a herramientas que no estén en ella.
   Que `clarify()` / `judge()` «no tengan herramientas de escritura» se apoya en el hook [`whitelist_guard`](#whitelist-guard).
   Y `coordinator()` trae por defecto `permission_mode="acceptEdits"` — quien pase ese valor a
   `clarify()` / `judge()` se queda sin protección.
4. **`disallowed_tools` es a nivel de sesión**, y prohíbe también las herramientas del mismo nombre en los subagents.
5. **El índice del workbench no llega a los subagents.** «Las salidas largas van a `artifacts/`» tiene que repetirlo el coordinador en el task brief;
   ese es el único canal.
6. **`Runtime(...)` lanza `RuntimeError` ya en la fase de construcción si no hay credenciales**, no espera a `run()`.
7. **`Runtime.run_id` debe ser único por instancia.** `manifest.json` deduplica por el campo `run`, y si dos id colisionan
   el que escriba después tomará las líneas del otro como «las que escribí yo la vez pasada» y las borrará.

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` es el valor por defecto**, `resume_from=None` no significa «sesión totalmente nueva».
   Si quieres abrir una nueva cada vez, pon explícitamente `continuous=False`. **Cambiar el nombre de un paso equivale a romper el linaje.**
9. **`with_goal(rounds=N)` es el total de rondas, no rondas adicionales**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` no escribe `ctx[step.name]`** — un `lambda ctx: ctx["某步"]` aguas abajo dará `KeyError`.
    Si quieres seguir adelante con un resultado incompleto, usa `on_fail="continue"`.
11. **Un `resume_from` que apunte a un paso no ejecutado o fallido lanza `ValueError`**, no se salta en silencio.
12. **`Step.reduce` debe ser una función síncrona; `gate` / `when` / `on_reject` pueden ser async.**
13. **`fork=True` sin `resume` no hace nada, en silencio.** `Workflow` nunca pasa `resume_at`;
    para retroceder por mensajes hay que llamar directamente a `Runtime.run`.
14. **Si conduces el `Runtime` tú mismo, hay que desenganchar `on_session` antes del gate**, o la sesión del judge acabará escrita en el linaje
    del paso que trabaja. `Workflow` lo garantiza con `try/finally`.
15. **`step_name` determina la clave en el manifest y en el linaje.** `Workflow` añade sufijos `#retryN` / `#roundN`,
    y el judge añade `#轮次` — **los nombres con sufijo no entran en el linaje entre procesos**, que es justo una de las formas de implementar «el judge siempre es sesión nueva».

### Roles {#陷阱-角色}

16. **`clarify(max_turns=<número pequeño>)` convierte «preguntar sin límite» en papel mojado** — cada pregunta es un turno.
17. **`goal_step()` no tiene un parámetro formal `can_run`**, solo se puede pasar `can_run=True` vía `**spec_kw`.
    Si no lo pasas, el judge que fija el objetivo no tendrá `Bash` y no podrá ejecutar la regla de `JUDGE_RULES` que dice «mira primero en qué entorno estás».
18. **`judge(can_run=True)` permite al judge modificar el espacio de trabajo** — `whitelist_guard` se deriva de `allowed_tools`,
    y si le das `Bash` deja pasar `Bash` (sigue bloqueando `Write`/`Edit`, pero `Bash` por sí solo puede escribir ficheros). Si quieres neutralidad absoluta, no lo actives.
19. **`worker(isolate=True)` exige que el workspace sea un repositorio git**, si no la herramienta `Agent` da directamente
    `"not in a git repository"`, no degrada en silencio. Además la marca de aislamiento es un atributo de Python,
    y **hacer `dataclasses.replace()` sobre un `AgentDefinition` la pierde**.
20. **Al construir `AgentDefinition` directamente los parámetros van en camelCase**: `maxTurns`, `permissionMode`.
    `worker()` ya hace la conversión por ti.

### Handoff y contexto {#陷阱-换代}

21. **Con el handoff activado, el auto-compact se apaga a la fuerza, sin red.** Por eso el paso que escribe el handoff document debe tener una vía de degradación.
    Si quieres conservar el auto-compact, da explícitamente `AgentSpec.compact`.
22. **Un `HandoffPolicy.window` demasiado pequeño provoca handoffs infinitos que queman dinero.** El único freno es `max_generations=8`.
    Por el otro lado, **`default_window()` devuelve `1_000_000` cuando ninguna de las dos variables de entorno está puesta** —
    si el juicio se pasa de largo lo recoge `is_overflow()` (se convierte en un handoff degradado), no es un error duro, pero el handoff de esa generación es degradado.
23. **Sin workbench el handoff no se escribe a disco.** El documento se le sigue entregando al sucesor vía prompt, pero después la persona no puede consultarlo.

### Almacenamiento {#陷阱-存储}

24. **`Runtime(trim=False)` (el valor por defecto) no significa «no se limpia nada».** El store siempre es `PruningSessionStore`,
    y `trim=False` solo desactiva el recorte de resultados grandes; **quitar restos de caídas, quitar llamadas rechazadas, neutralizar restos de interrupciones y caducar lo perecedero se siguen haciendo.**
25. **Los dos directorios de spill no son el mismo**: `spill_guard` cae en `<workbench.root>/spill/`,
    y `TrimPolicy.spill_dirname` cae en `<workspace>/.flower/spill/` (tiene que estar dentro del espacio de trabajo).
26. **El cuarto parámetro posicional de `PruningSessionStore.__init__` es `prune`, no `ephemeral`**,
    a diferencia de la clase padre. Pasarlo por posición desalinea en silencio.

### Documentos e interacción {#陷阱-文书}

27. **Si `Verdict` no consigue extraer una conclusión, `state=""` y `ok=False`, y eso jamás debe tomarse por logrado.**
    Además «无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable» se agrupan todos en `unreachable`,
    lo que dispara la vía de «parar y preguntar a la persona», no la de «otra ronda».
28. **`Brief.parse` descarta todo el contenido posterior a una valla de código sin cerrar** — si la salida del modelo se corta,
    las secciones siguientes no se parsean, `complete()` da `False` y el gate lo devuelve para repetir.
29. **`Brief.load` trata `"(未填)"` como vacío.** Si al editar el brief a mano copias el texto de marcador, esa sección sigue contando como ausente.
30. **Las tres semánticas de «0 / None» de `HumanChannel` son distintas**: `max_asks=None` sin límite, `max_asks=0` prohibido preguntar;
    `timeout_s=None` esperar para siempre, `timeout_s<=0` vencer de inmediato; `remaining` con `max_asks=None` devuelve **`-1`**.
31. **`Event("ask")` transporta a la vez preguntas y lo que la persona dice por iniciativa propia**, esto último con `payload["kind"] == "mail"`. La UI debe comprobarlo primero.
32. **`Workflow.run` solo cablea automáticamente cuando `channel.on_event is None`** —
    si construyes tú un `HumanChannel(on_event=...)`, los eventos de pregunta no entrarán además por la salida `on_event` del workflow.
