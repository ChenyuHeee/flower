# Cambiar la capa de interacción

El núcleo de flower no sabe que exista una UI. Todo lo que ocurre dentro de una ejecución —el modelo habla, llama a una herramienta, el contexto está a punto de llenarse, hay que preguntarle algo a una persona— se aplana a una única estructura de datos: [`Event`](../reference/glossary.md#事件).
**La [capa de interacción](../reference/glossary.md#交互层) solo conoce `Event`, no importa ningún tipo del SDK.**
Esa es la frontera que permite cambiar de UI sin tocar el núcleo: terminal, web, servicio HTTP, modo totalmente automático sin supervisión — lo que se sustituye es el consumidor de `Event`, y nada más.

## Qué problema resuelve

El flujo de mensajes del SDK son **tipos internos**: `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`,
`ResultMessage`, `SystemMessage`… Consumirlos directamente desde la UI tiene dos consecuencias: cada vez que el SDK sube de versión, el frontend tiene que cambiar; y como cada mensaje tiene una forma distinta, cada UI vuelve a escribir desde cero la lógica de «esto es texto o es una llamada a herramienta».

`normalize(message)` convierte un mensaje del SDK en 0 a N `Event`
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
El coste es una conversión; a cambio, no hay ninguna dependencia de tipos entre la capa de interacción y el SDK.

Esa frontera resuelve de paso cuatro cosas menos evidentes, las cuatro dentro de `normalize()`:

1. **Lo que dice un [subagent](../reference/glossary.md#subagent) queda marcado** (`payload["subagent"]`).
   Si no, el [pliego de tarea](../reference/glossary.md#任务书) del reparto y las intervenciones intermedias del subagent se mezclarían con el texto del [hilo principal](../reference/glossary.md#主线程) y contaminarían, a través del [flujo](../reference/glossary.md#流程), el prompt del paso siguiente.
2. **Los mensajes de error sintéticos de las desconexiones se desvían a `kind="error"`.** Al caerse la conexión, el lado del SDK escribe `API Error: …` en el transcript como si fuera un mensaje de assistant; parece algo dicho por el modelo (`model` es `"<synthetic>"`).
   Si no se intercepta aquí, acaba dentro de `StepResult.text` y se pasa al [paso](../reference/glossary.md#步骤) siguiente.
3. **La frontera de compact se reporta explícitamente** (`kind="reset"`). Después de esa frontera, lo único que el modelo «recuerda» es el resumen, y la caché de prompt también se corta ahí — una ejecución de [horizonte largo](../reference/glossary.md#长程) tiene que poder verlo.
4. **El nivel de contexto sale con cada mensaje** (`payload["context"]` = `input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`). Es la única fuente del criterio de [handoff](../reference/glossary.md#换代).

## Cómo se usa (código mínimo)

Una capa de interacción tiene que conectar tres cosas: **la salida de eventos** (dónde se renderiza), **el canal de preguntas** (quién responde) y **la interrupción** (cómo se para). El fragmento siguiente las conecta todas y se puede ejecutar tal cual:

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Renderiza el Event en tu propia UI — esto es lo único que hay que cambiar."""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ 换代/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ 重试: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # los kind == "ask" que no son mail los gestiona el answerer de abajo (modo pull)


async def answerer(ch: HumanChannel) -> None:
    """Recoge preguntas en modo pull. Al pasar a Web / HTTP, esta corrutina es el otro punto a cambiar."""
    while True:
        ask = await ch.next_ask()           # sin timeout, espera indefinidamente
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # o ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime usa el banco de trabajo que el workflow ya ha creado — no montes otro
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        ctx = await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()                          # cierra la conexión SQLite
    print(rt.total_cost(), ctx.get("_failed_at"))


asyncio.run(main())
```

Dos remates que se olvidan con facilidad: `rt.close()` siempre en `finally`; y si `ctx["_failed_at"]` tiene valor es que la ejecución se detuvo a mitad (`on_fail="stop"`), no lo tomes por éxito.

!!! note "Solo hay un banco de trabajo, no montes otro"
    El [banco de trabajo](../reference/glossary.md#工作台) que crea `Runtime(workbench=True)` está en
    `<run_dir>/workbench`, mientras que `Workbench(ws)` está por defecto en `<ws>/.flower` —
    no son el mismo directorio. Si el programa que orquesta arma la ruta a mano para buscar `需求.md`,
    acabas con «el brief se escribe en el directorio A y el índice inyectado escanea el directorio B», y sin ningún error.
    O le pasas a `Runtime` el que ya creó el workflow (como arriba),
    o usas la sonda de solo lectura `wake_state()` para preguntarle dónde está.

### Tres salidas de eventos

```python
await rt.run(spec, "…", on_event=sink)                  # 1. un solo agente
await wf.run(rt, on_event=sink, on_step=progress)       # 2. todo el flujo, propagado a cada paso
wf = Workflow(steps=[...], channel=ch)                  # 3. canal de preguntas, conectado a la misma salida
```

La conexión del tercer caso está en `Workflow.run`: **solo se conecta automáticamente si `on_event` no es `None` y `channel.on_event` sigue siendo `None`**. Si ya lo conectaste tú, no se sobrescribe:

```python
ch = HumanChannel(on_event=my_own_sink)     # lo conectas tú, Workflow no lo toca
```

`on_step(step, result)` es otro callback: se llama una vez al terminar cada paso (**incluidos los fallidos**) y recibe el `StepResult` completo. Barra de progreso, escritura a disco y alertas van aquí; no intentes reconstruirlo a partir del flujo de `Event` — el texto queda partido en varios trozos por los handoff y los reintentos.

### Terminal: la que viene por defecto

Hay una sin escribir código. `flower "帮我做一个 X"` pasa por
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py),
que es la **implementación de referencia de la capa de interacción, no parte del framework**: se puede sustituir entera; para los interruptores, ver la [referencia de la CLI](../reference/cli.md).

Digamos el tamaño tal cual es. `cli.py` entero son 1264 líneas, 57KB — pero **lo que hay que cambiar no es el fichero entero**. El punto de sustitución real es la `class Render` de dentro (`cli.py:382-578`, 197 líneas), cuyo docstring ya lo dice: «Event → terminal. Cambiar de UI es cambiar esta única clase.» Las otras mil y pico líneas son la interrupción, el oráculo, los acuses de la bandeja de entrada, el rescate por señales: complementos **específicos de la terminal** que, al pasar a Web o HTTP, no hacía falta copiar de todos modos.

Así que la afirmación «unas 200 líneas sustituibles de una pieza» se sostiene — siempre que se refiera a `Render` y no a `cli.py`.

Si escribes tu propia UI de terminal, la clave está en el hilo que lee la entrada estándar:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Lee la entrada estándar continuamente: si hay una pregunta pendiente es la respuesta, si no va a la bandeja. Devuelve el bit de parada."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # polling, para poder atender el bit de parada
            line = sys.stdin.readline()
            if not line:                        # EOF
                return
            raw = line.strip()
            if not raw:
                continue
            pend = ch.pending()
            if pend:
                ch.answer(pend[0].id, raw)      # seguro entre hilos
            else:
                ch.send(raw)                    # a la bandeja, sin interrumpir el trabajo en vuelo

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

Los tres puntos salen de tropezar con ellos:

- **Usa un hilo daemon, no `asyncio.to_thread(input, ...)`.** `input()` no se puede cancelar mientras bloquea, y `asyncio.run` hace join de los hilos del executor por defecto antes de salir — el resultado es que, con el trabajo terminado, hay que pulsar Enter otra vez para poder salir.
- **Usa `select` con polling, no `input()` directamente dentro del bucle.** Mismo problema de cancelación: a un hilo bloqueado en `input()`, `stop.set()` ya no lo despierta.
- **Lee siempre, no solo cuando hay una pregunta.** Si solo lees cuando hay pregunta, todo lo que se teclee durante esas horas de trabajo queda en el búfer de la terminal y, en la siguiente pregunta, se consume como respuesta — la persona ni siquiera ha visto la pregunta y ya está «respondida».

### Web: cola + WebSocket

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # síncrono, en el hilo del bucle de eventos, no puede bloquear
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # un error del frontend no debe llevarse tres horas de trabajo
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # hilo que atiende la petición — otro hilo, y esto es lo normal
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` es el objeto original del SDK (en los eventos `ask`, un `Ask`), **no es serializable a JSON y tampoco lo mandes al frontend** — usar `raw` equivale a atar el frontend otra vez a los tipos del SDK, y entonces esta capa no sirve de nada. Con los cuatro campos `kind` / `text` / `tool` / `payload` hay de sobra.

### HTTP: número de secuencia + polling

Cuando no hay conexión persistente, numera los eventos para que el cliente los tire:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # solo los más recientes, la memoria no crece con la duración de la ejecución


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # qué hay ahora mismo esperando respuesta
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = esa pregunta ya no está esperando
```

Hay que asumir dos límites: cuando `maxlen` se llena se pierden los más antiguos, así que si el cliente vuelve con un `after` muy viejo ya no lo recupera todo, y el intervalo de polling tiene que estar a la altura de esa longitud; y además **hay que darle a `timeout_s` un valor finito** — si nadie hace polling, la pregunta no termina sola, y `timeout_s=None` deja la ejecución entera colgada para siempre. El valor por defecto de `1800.0` segundos es adecuado.

### Totalmente automático, sin supervisión: no hay nadie

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # se descartan todos los eventos
```

El equivalente en línea de comandos es `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (y cualquier valor negativo) es el modo totalmente automático: las preguntas **no entran en la cola de espera ni emiten evento `asked`**, se liquidan al instante como `state="timeout"` y la herramienta devuelve este texto fijo:

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

—y así la ejecución sigue sin detenerse. Las preguntas y respuestas se siguen anexando a `HumanChannel(log_path=...)` (`starter_flow` lo conecta por defecto a `<工作台>/notes/问答记录.md`), de modo que después puedes ver qué preguntó y qué supuso por su cuenta.

Si no quieres que abra la boca, usa `max_asks=0`: la pregunta se rechaza directamente (`state="over_budget"`) y tampoco bloquea.
Ojo: esto **no es** «quitarle la herramienta» — `allowed_tools` no es excluyente; en cuanto el [coordinador](../reference/glossary.md#协调者) tiene un `channel` colgado, se le dan las dos herramientas `mcp__human__ask` y `mcp__human__inbox`, y puede llamarlas estén o no en la lista. Lo único que frena las preguntas son la cuota y el timeout.

!!! warning "Sin supervisión, no dejes preguntas esperando para siempre"
    `timeout_s=None` significa «esperar siempre». Cuando no hay nadie mirando, una sola pregunta puede dejar clavada una ejecución de diez horas, sin error, sin timeout y sin que se note nada en el log. Sin supervisión solo hay dos valores correctos: `0` (falla al instante) o un número finito de segundos.

## Qué hace en realidad

### La forma de `Event`

```python
@dataclass
class Event:
    kind: EventKind                     # 15 valores, ver la tabla de abajo
    text: str = ""
    tool: str = ""                      # solo tiene valor en tool_call
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # objeto original del SDK / Ask; tocarlo es volver a atarse al SDK
```

`str(ev)`: en `tool_call` es `[nombre de la herramienta] resumen`, en el resto es `text`; si `text` está vacío, es `<kind>`.

### Los 15 `EventKind`

| `kind` | Quién lo emite | Cuándo aparece | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | Texto del modelo | El texto | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | Bloque de razonamiento | El contenido del razonamiento | Igual que arriba |
| `prompt` | `normalize()` | **Entrada**: tu prompt, el pliego de tarea repartido a un subagent | El texto de entrada | Igual que arriba |
| `tool_call` | `normalize()` | El modelo inicia una llamada a herramienta | Resumen (`file_path` / `command` / `pattern`, cortado a 200 caracteres) | `id`, `input` + igual que arriba; `tool` es el nombre de la herramienta |
| `tool_result` | `normalize()` | Retorno de la herramienta | Los primeros 500 caracteres (vacío si el contenido no es una cadena) | `tool_use_id`, `is_error` + igual que arriba |
| `result` | `normalize()` | Fin de una consulta al SDK | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | Mensaje sintético de una desconexión | El texto del error | `synthetic: True` |
| `reset` | `normalize()` | Frontera de compact o reinicio de sesión | `压缩(trigger) 167000 → 42000 tokens`; en un reinicio de sesión, `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (vacío en el reinicio de sesión) |
| `system` | `normalize()` | Los demás mensajes de sistema del SDK | subtype | `data` tal cual |
| `task` | `normalize()` | Mensaje de progreso de tarea | Nombre de la clase del mensaje | — |
| `unknown` | `normalize()` | Tipo de mensaje no reconocido | Nombre de la clase | — |
| `ask` | `HumanChannel` | Hay que responder algo, una pregunta ha terminado, o una persona ha dicho algo por su cuenta | La pregunta / lo que dijo la persona | Dos identidades, ver abajo |
| `retry` | `Runtime` | Reintentando / esperando a que vuelva la red | Una línea de explicación | `step`, `attempt` |
| `step` | `Workflow.run` | Frontera de paso | Nombre del paso | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | Handoff: acercándose / escribiendo / hecho | Una línea con el nivel de contexto | `phase`, `step`, `context`, `window` + ver abajo |

**Cuatro `kind` no los produce `normalize()`**: `ask` viene de `HumanChannel`, `retry` y `handoff` de `Runtime`, y `step` de `Workflow.run`. Meterlos en el mismo `EventKind` es deliberado: **la UI solo conoce un tipo de `Event` y no necesita una vía aparte para «hay que responder» o «frontera de paso».**

Cuando escribas la UI, deja una rama `else`. `EventKind` seguirá ganando miembros nuevos, y una UI vieja no debería romperse por eso.

### Las tres phase de `handoff`

| `phase` | Cuándo se emite | Extra en `payload` |
|---|---|---|
| `near` | El nivel de contexto ha pasado `warn_at`. **Se emite una sola vez por generación**, sin inundar la pantalla | `at` (umbral de handoff) |
| `writing` | Empieza a escribirse el [documento de handoff](../reference/glossary.md#交接书). Escribirlo lleva más de diez segundos; sin este evento la interfaz parece colgada | — |
| `done` | El traspaso está escrito y se ha cambiado de sesión | `degraded` (si es la versión degradada), `path` (dónde se escribió; cadena vacía si no hay banco de trabajo), `sections` |

El mecanismo en sí está en [handoff](handoff.md).

### Las dos identidades de `ask`

`Event("ask")` transporta a la vez «una pregunta» y «algo que dijo una persona por su cuenta»; **la UI tiene que mirar primero `payload["kind"]`**:

| Identidad | Cómo se reconoce | `payload` |
|---|---|---|
| Una pregunta | No hay clave `kind` | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`; `raw` es ese `Ask` |
| Algo dicho por una persona | `payload["kind"] == "mail"` | `kind`, `state` (`queued` al entrar / `delivered` al recogerse), `id`, `amended` (en qué fichero se anexó; cadena vacía si no está configurado). **No hay `options` ni `remaining`** |

Una pregunta emite eventos **dos veces o más**: una al preguntar (`state="asked"`) y otra al terminar (`answered` / `timeout` / `declined` / `over_budget` / `invalid`). A la UI le basta con actualizar la misma entrada según `payload["id"]`.

### Preguntar a una persona: `Ask` y `HumanChannel`

```python
@dataclass
class Ask:
    id: str                                             # "q1", "q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # los cinco desenlaces de arriba
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # segundos esperados, con un decimal
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` es un servidor MCP dentro del proceso más un conjunto de métodos para la UI. El modelo solo ve dos herramientas: `mcp__human__ask` (preguntar, se queda esperando) y `mcp__human__inbox` (consultar la bandeja de entrada, **no bloquea**: si está vacía devuelve enseguida una línea de explicación). El constructor completo:

```python
HumanChannel(
    *,                                  # todo keyword-only
    on_event=None,                      # salida push. Workflow solo la conecta automáticamente si es None
    max_asks=None,                      # None = sin límite; 0 = no puede preguntar. Al pasarse, se rechaza sin bloquear
    timeout_s=1800.0,                   # None = esperar siempre; <= 0 = falla al instante
    log_path=None,                      # las preguntas y respuestas se anexan a este fichero, no ocupan contexto
    amend_path=None,                    # lo que diga la persona durante la ejecución se anexa a este fichero, normalmente el brief
    over_budget_text=OVER_BUDGET,       # tres respuestas fijas, se pueden sustituir por las tuyas
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` es el que más se olvida, y es el que decide si un cambio de requisitos hecho a mitad sobrevive a la frontera de paso.
Cada paso es una [sesión](../reference/glossary.md#会话) nueva sobre una copia congelada de solo lectura: lo dicho durante la ejecución solo entró en el contexto de aquel agente concreto; el paso siguiente (por ejemplo el [veredicto](../reference/glossary.md#判定)) es una sesión totalmente nueva que lee `需求.md` y `目标.md`, **no ve esa frase que dijiste**, así que juzga con los límites viejos y declara fuera de alcance justo lo que se acaba de corregir.
`amend_path` **anexa** cada mensaje al [brief](../reference/glossary.md#需求确认书) — anexa, no sobrescribe: el requisito original es historia y es mejor ver qué cambió que no verlo. Lo que `starter_flow` conecta por defecto es `<工作台>/notes/需求.md`.

En una prueba real ($0.6767) esto funcionó incluso mejor de lo esperado: la persona dijo «de paso, reporta el total de bytes», el coordinador lo vio al consultar la bandeja y respondió que «hand ya lo ha leído del apartado de añadidos en ejecución de `.flower/notes/需求.md` y lo ha calculado, no hace falta repartirlo otra vez».
**El subagent lo leyó del fichero, no dependió de que nadie se lo contara.**

Miembros públicos:

| Miembro | Firma | Semántica |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | Se pasa directamente a `AgentSpec.mcp_servers`. El nombre de la clave debe coincidir con el del server, por eso lo da él mismo |
| `ask` | `async (question, options=None) -> Ask` | Espera a una persona. **Nunca lanza excepciones salvo `CancelledError`** — que nadie responda también es una respuesta; se distingue con `ask.state` |
| `pending` | `() -> list[Ask]` | Preguntas que ahora mismo esperan respuesta |
| `next_ask` | `async (timeout=None) -> Ask \| None` | Para UI en modo pull. Devuelve `None` al agotarse el timeout; si se cancela, lanza |
| `answer` | `(ask_id, text) -> bool` | Responder. `False` = esa pregunta ya no está esperando (timeout / ya respondida) |
| `decline` | `(ask_id, reason="") -> bool` | Saltarla: el modelo decide por su cuenta y escribe el supuesto en 「未知与假设」 |
| `send` | `(text) -> Mail \| None` | Una persona dice algo por su cuenta, va a la bandeja. No interrumpe al agente; internamente llama a `amend()` |
| `amend` | `(text, *, label="运行中补充") -> bool` | Anexa a `amend_path`. Devuelve si realmente escribió (sin ruta configurada / texto vacío / `OSError` dan `False`) |
| `pending_mail` | `() -> list[Mail]` | Mensajes que aún no se han recogido |
| `remaining` | `-> int` | Cuántas preguntas quedan. Con `max_asks=None` devuelve **`-1`**, no 0 |
| `transcript` | `() -> str` | El markdown del registro de preguntas y respuestas |
| `asks` / `mail` / `ui_errors` | `list` | Todas las preguntas / todo lo dicho por personas / las excepciones lanzadas por los callbacks de la UI |

`answer`, `decline` y `send` **se pueden llamar desde cualquier hilo**. El hilo que atiende peticiones del backend web o el hilo de entrada de la TUI están en otro hilo — eso es lo normal, no un caso límite. Por dentro va por `loop.call_soon_threadsafe`, porque `asyncio.Future.set_result` no es seguro entre hilos.

Push y pull son dos formas de recogida: **elige una**:

| | Cómo se recoge | Para qué sirve |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, recibiendo `kind == "ask"` con `payload["state"] == "asked"` | UI dirigidas por eventos (push web, repintado de TUI) |
| **Pull** | `await channel.next_ask()` | Una tarea de entrada independiente |

Los tres «0 / None» tienen semánticas distintas, y confundirlos significa quedarse colgado sin supervisión o no preguntar ni una vez:

| Forma | Significado |
|---|---|
| `max_asks=None` | Sin límite de veces (por defecto) |
| `max_asks=0` | No puede preguntar, se rechaza directamente |
| `timeout_s=None` | Espera para siempre |
| `timeout_s<=0` | No espera, la pregunta falla al instante |
| `remaining` devuelve `-1` | Es el valor con `max_asks=None`, no 0 |

### Interrupción: cualquier hilo puede parar

`rt.interrupt("别改 Makefile,那两行直接改")`; con la cadena vacía, solo interrumpe sin decir nada. Tres propiedades:

- **Continúa en la misma sesión** (`resume`), no empieza de cero: el trabajo hecho y el contexto siguen ahí. Reutiliza el camino ya existente de los reintentos por caída de red, cambiando solo el «motivo del fallo» por «una persona ha interrumpido» y el `resume_prompt` por lo que dijo esa persona.
- **No consume `max_attempts`.** Esa cuota es para las averías, no para las personas.
- **Es cooperativa**: corta en la frontera de un mensaje, no cancela la tarea a la fuerza. El coste es la latencia hasta el mensaje siguiente (si hay un subagent corriendo, hay que esperar a que vuelva); a cambio, el estado no se rompe a mitad.

Digamos el coste tal cual: una interrupción hace que **un subagent en vuelo pierda el trabajo a medias** (comprobado en la caída de red de HT001, ver [issue #2](https://github.com/ChenyuHeee/flower/issues/2)). La implementación de referencia de terminal lo dice explícitamente en el aviso, para que la persona lo sepa antes de pulsar; si escribes tu propia UI, deberías hacer lo mismo.

Si no quieres interrumpir y solo quieres añadir un requisito, usa la bandeja de entrada (`ch.send(...)`) — no interrumpe nada, y la latencia es hasta el siguiente punto de control del agente.

### Oráculo: preguntar sin molestar a la ejecución

Si quieres saber «por dónde va ahora», no hace falta interrumpir, y tampoco deberías preguntárselo al coordinador: ese intercambio **ocupa el contexto del hilo principal de forma permanente** (que está para decisiones, no para registros de preguntas y respuestas), y además le obliga a soltar lo que tiene entre manos. En una ejecución de diez horas, tres preguntas sueltas ya pagan ambos costes.

El [oráculo](../reference/glossary.md#旁路顾问) es una vía lateral de solo lectura. Sus únicas herramientas son `Read` / `Glob` / `Grep`, tiene el banco de trabajo abierto y trae frenos por defecto: `max_turns=12`, `max_budget_usd=0.5`. En la terminal se dispara con una línea que empiece por `?`, y responde con dos cosas: la ventana de eventos reciente (60 fijos) y el brief, los objetivos, las notas y los artefactos del banco de trabajo.
Usa un `Runtime` independiente (`<run_dir>/aside`), así que el coste y el [linaje](../reference/glossary.md#血缘) de sesiones **no se mezclan con el manifiesto principal** — ese manifiesto registra «qué pasos hizo esta ejecución», y una pregunta de pasada no es un paso.

Medido: dos preguntas por un total de $0.5190, y el manifiesto de la ejecución principal no creció ni un byte.

### Dos reglas duras

!!! warning "on_event ni puede bloquear ni puede dejar escapar excepciones"
    **Una: `on_event` es una función síncrona y se llama en el hilo del bucle de eventos.** Por eso
    `asyncio.Queue.put_nowait()` es seguro y `await` no lo es (no es una corrutina), y **bloquearla es bloquear la ejecución entera**.
    Si hay trabajo lento, mételo en una cola y que lo haga otra tarea.

    **Dos: lanzar una excepción dentro de `on_event` daña la propia ejecución.** Los eventos de texto se emiten dentro del bloque `try` de `Runtime._attempt` y la excepción se registra como `result.error` — ese paso queda como fallido; los eventos `retry` se emiten fuera de ese bloque, así que la excepción sale directamente por `Runtime.run`. El frontend no debería llevarse tres horas de trabajo: **envuelve tú el callback en un try**.

    Excepción: los eventos `ask` que emite el propio `HumanChannel` ya vienen envueltos; la excepción se recoge en `channel.ui_errors` y no interrumpe la ejecución.

## Cuándo no usarlo

### Lo que no se debe hacer en la capa de interacción

| Qué no hacer | Por qué | Qué hacer en su lugar |
|---|---|---|
| `from claude_agent_sdk import ...` | En cuanto la capa de interacción depende de tipos del SDK, cada subida de versión del SDK arrastra al frontend, y esta capa no sirve de nada | Usa solo `kind` / `text` / `tool` / `payload` de `Event` |
| Leer `ev.raw` | Igual que arriba, y además no es serializable a JSON | Si te falta algún detalle, añádelo al `payload` de `normalize()`, no rodees la frontera |
| Hacer `await`, peticiones de red o escrituras lentas dentro de `on_event` | Es síncrona y se llama en el hilo del bucle de eventos; bloquearla es bloquear toda la ejecución | `put_nowait()` a una cola y consúmela desde otra tarea |
| Dejar que `on_event` lance excepciones hacia fuera | La excepción en un evento de texto se convierte en `result.error` y ese paso se da por fallido | Envuelve todo el cuerpo del callback en un `try` |
| Usar `disallowed_tools` para desactivar las preguntas | Es **a nivel de sesión**: desactiva también la herramienta homónima en los subagents (error real observado: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` o `timeout_s=0` |
| Quitar `mcp__human__ask` de `allowed_tools` creyendo que así se prohíben las preguntas | `allowed_tools` no es excluyente: es una lista de exención de aprobación, no una lista blanca; con un `channel` colgado se dan las dos herramientas | Igual que arriba |
| Armar rutas a mano para buscar `需求.md` / `目标.md` | El banco de trabajo puede estar en dos sitios; si te equivocas no hay error, simplemente deja de funcionar en silencio | `wake_state()` o `wf.workbench` |
| Reconstruir progreso y resultados a partir del flujo de `Event` | El texto queda partido en varios trozos por los handoff y los reintentos | `on_step(step, result)` te da el `StepResult` completo |
| Usar `timeout_s=None` sin supervisión | No hay quien responda, la ejecución queda colgada para siempre, sin error y sin timeout | `0`, o un número finito de segundos |

### Cuándo no hace falta cambiar nada

- **Solo quieres cambiar colores o imprimir una línea más o menos** — con modificar la función de renderizado basta. Reescribir desde cero la interrupción, el oráculo, los acuses de la bandeja, el rescate ante SIGHUP / SIGTERM y la espera al cierre de la vía lateral que hay en la implementación de referencia de terminal no sale barato.
- **Solo quieres ejecutar un paso, sin interacción** — usa `flower once`. No pasa por la vía dirigida por interacción, así que de entrada no tiene interrupción con Ctrl+C, ni hilo de respuesta por entrada estándar, ni oráculo, ni rescate por señales.
- **Lo que quieres cambiar es en realidad el flujo, no la UI** — ver [Diseñar flujos](workflow.md). La capa de interacción solo decide quién mira y quién responde; cuántos pasos se ejecutan, cómo se juzga y cuándo se sale antes lo decide `Workflow`.
- **Lo que quieres cambiar es el almacén de sesiones, el modelo o el presupuesto** — esas tres cosas no están en esta frontera, ver la [referencia de la API de Python](../reference/api.md).
