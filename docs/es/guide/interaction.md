# Cambiar la capa de interacción

El núcleo de flower no sabe que la UI existe. Todo lo que ocurre en una ejecución —el modelo habla, llama a una herramienta, el contexto casi se llena, hay que preguntarle algo a una persona— se aplana a una única estructura de datos: [`Event`](../reference/glossary.md#事件).
**La [capa de interacción](../reference/glossary.md#交互层) solo conoce `Event`; no importa ningún tipo del SDK.**
Esa es la frontera que permite cambiar de UI sin tocar el núcleo: terminal, Web, servicio HTTP, modo totalmente automático sin supervisión; lo que se sustituye es el consumidor de `Event`, y no hace falta cambiar ni una línea más.

## Qué problema resuelve {#解决什么问题}

El flujo de mensajes del SDK son **tipos internos**: `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`, `ResultMessage`, `SystemMessage`… Consumirlos directamente desde la UI tiene dos consecuencias: cada actualización del SDK obliga a cambiar el frontend, y como cada mensaje tiene una forma distinta, cada UI tiene que reescribir desde cero la lógica de "esto es texto o es una llamada a herramienta".

`normalize(message)` convierte un mensaje del SDK en 0 a N `Event`
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
El coste es una conversión; a cambio, no hay dependencia de tipos entre la capa de interacción y el SDK.

Esta frontera resuelve de paso cuatro cosas menos evidentes, las cuatro dentro de `normalize()`:

1. **Las intervenciones de los [subagent](../reference/glossary.md#subagent) quedan marcadas** (`payload["subagent"]`).
   Si no, el [task brief](../reference/glossary.md#任务书) del reparto y las intervenciones intermedias del subagent se mezclarían con el texto del [hilo principal](../reference/glossary.md#主线程) y, siguiendo el [workflow](../reference/glossary.md#流程), contaminarían el prompt del paso siguiente.
2. **Los mensajes de error sintéticos por caída de conexión se desvían a `kind="error"`**. Al caerse la conexión, el lado del SDK escribe `API Error: …` en el transcript como si fuera un mensaje del assistant; tiene el aspecto de algo dicho por el modelo (`model` es `"<synthetic>"`).
   Si no se intercepta aquí, acaba en `StepResult.text` y se pasa al [paso](../reference/glossary.md#步骤) siguiente.
3. **Los límites de compact se reportan explícitamente** (`kind="reset"`). Después de ese límite, lo único que el modelo "recuerda" es el resumen, y la caché de prompts se corta ahí: una ejecución de [largo horizonte](../reference/glossary.md#长程) tiene que poder verlo.
4. **El nivel de contexto sale con cada mensaje** (`payload["context"]` = `input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens`). Es la única fuente del criterio de [relevo](../reference/glossary.md#换代).

## Cómo se usa (código mínimo) {#怎么用最小代码}

Una capa de interacción tiene que conectar tres cosas: **la salida de eventos** (dónde renderizar), **el canal de preguntas** (quién responde) y **la interrupción** (cómo parar).
Este fragmento las conecta todas y se puede ejecutar tal cual:

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Renderiza el Event en tu propia UI: esto es lo único que hay que cambiar."""
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
    """Obtención pull de las preguntas. Al pasar a Web / HTTP, esta corutina es el otro punto a cambiar."""
    while True:
        ask = await ch.next_ask()           # sin timeout, espera indefinidamente
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # o ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime usa el workbench que ya creó el workflow: no montes otro
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

Dos remates que se olvidan con facilidad: `rt.close()` siempre en el `finally`; si `ctx["_failed_at"]` tiene valor, la ejecución se detuvo a mitad (`on_fail="stop"`), no lo tomes por éxito.

!!! note "Solo hay un workbench, no montes otro"
    El [workbench](../reference/glossary.md#工作台) que crea `Runtime(workbench=True)` está en `<run_dir>/workbench`, mientras que `Workbench(ws)` está por defecto en `<ws>/.flower`: no son el mismo directorio. Si el programa que orquesta arma la ruta a mano para buscar `需求.md`, acabas con "el brief escrito en el directorio A y el índice inyectado escaneando el directorio B", y sin ningún error.
    O le pasas a `Runtime` el que creó el workflow (como arriba), o usas la sonda de solo lectura `wake_state()` para preguntarle dónde está.

### Tres salidas de eventos {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. un solo agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. todo el workflow, se propaga a cada paso
wf = Workflow(steps=[...], channel=ch)                  # 3. canal de preguntas, conectado a la misma salida
```

La tercera se conecta dentro de `Workflow.run`: **solo se conecta automáticamente si `on_event` no es `None` y `channel.on_event` sigue siendo `None`**. Si ya lo has conectado tú, no se sobrescribe:

```python
ch = HumanChannel(on_event=my_own_sink)     # conectado por ti; Workflow no lo toca
```

`on_step(step, result)` es otro callback: se llama una vez al terminar cada paso (**incluidos los fallidos**) y recibe el `StepResult` completo. Barras de progreso, escritura a disco y alertas van aquí; no intentes reconstruirlo a partir del flujo de `Event`: el texto queda partido en varios trozos por los relevos y los reintentos.

### Terminal: la que viene por defecto {#终端默认的那个}

También hay una sin escribir código. `flower "帮我做一个 X"` pasa por
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py),
que es la **implementación de referencia de la capa de interacción, no parte del framework**: se puede sustituir entera; los interruptores están en la [referencia de la CLI](../reference/cli.md).
Sin adornos sobre el tamaño. `cli.py` entero son 1264 líneas, 57KB, pero **lo que hay que cambiar no es el archivo entero**.
El punto de sustitución real es la `class Render` que hay dentro (`cli.py:489-687`, 197 líneas), cuyo docstring dice literalmente "Event → terminal. Cambiar de UI es cambiar esta única clase". Las otras mil y pico líneas son la interrupción, el oráculo, los acuses de la bandeja de entrada, el rescate por señales: piezas **específicas de la terminal** que, al pasar a Web o HTTP, no hace falta trasladar.

Así que "unas 200 líneas sustituibles en bloque" es cierto, siempre que se refiera a `Render` y no a `cli.py`.

Si escribes tu propia UI de terminal, lo importante es el hilo que lee la entrada estándar:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Lee stdin sin parar: si hay una pregunta pendiente es la respuesta; si no, va a la bandeja. Devuelve el flag de parada."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # sondeo: solo así responde al flag de parada
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
                ch.send(raw)                    # va a la bandeja, no interrumpe el trabajo en vuelo

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

Las tres reglas salieron de tropezar:

- **Usa un hilo daemon, no `asyncio.to_thread(input, ...)`.** `input()` no se puede cancelar mientras bloquea, y `asyncio.run` hace join de los hilos del ejecutor por defecto antes de salir: el resultado es que, con el trabajo ya terminado, hay que pulsar Enter otra vez para poder salir.
- **Sondea con `select`, no llames a `input()` directamente en el bucle.** Mismo problema: un hilo bloqueado en `input()` ya no se despierta con `stop.set()`.
- **Lee siempre, no solo cuando hay una pregunta.** Si solo lees cuando hay pregunta, lo que se teclee durante esas horas de trabajo se queda en el búfer de la terminal y se comerá como respuesta en la siguiente pregunta: la persona ni siquiera ha visto la pregunta y ya está "respondida".

### Web: cola + WebSocket {#web队列--websocket}

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # síncrona, en el hilo del bucle de eventos, no puede bloquear
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # un fallo del frontend no debe llevarse tres horas de trabajo
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # hilo que atiende la petición: otro hilo, y es lo normal
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` es el objeto original del SDK (en los eventos `ask`, un `Ask`): **no es serializable a JSON y tampoco debe llegar al frontend**. Usar `raw` equivale a volver a atar el frontend a los tipos del SDK, y esta capa deja de servir para nada. Con los cuatro campos `kind` / `text` / `tool` / `payload` basta.

### HTTP: número de secuencia + sondeo {#http序号--轮询}

Cuando no hay conexión persistente, numera los eventos para que el cliente los recoja:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # solo lo reciente: la memoria no crece con la duración de la ejecución


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # qué está esperando respuesta ahora mismo
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = esa pregunta ya no está esperando
```

Hay dos límites que conviene asumir: cuando `maxlen` se llena se descarta lo más antiguo, así que un cliente que vuelva con un `after` muy viejo ya no podrá recuperarlo todo; el intervalo de sondeo tiene que ser coherente con esa longitud. Y **hay que dar a `timeout_s` un valor finito**: si nadie sondea, la pregunta no termina por sí sola, y `timeout_s=None` deja toda la ejecución colgada para siempre. El valor por defecto de `1800.0` segundos es adecuado.

### Totalmente automático, sin supervisión: no hay nadie {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # se descartan todos los eventos
```

El equivalente en línea de comandos es `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (y cualquier valor negativo) es el modo totalmente automático: la pregunta **no entra en la cola de espera ni emite el evento `asked`**, se liquida de inmediato como `state="timeout"` y la herramienta devuelve este texto fijo:

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

—y así la ejecución sigue sin detenerse. Las preguntas y respuestas se siguen anexando a `HumanChannel(log_path=...)` (`starter_flow` lo conecta por defecto a `<workbench>/notes/问答记录.md`), de modo que después puedes ver qué preguntó y qué asumió por su cuenta.

Si no quieres que abra la boca, usa `max_asks=0`: la pregunta se rechaza directamente (`state="over_budget"`) y tampoco bloquea.
Ojo: esto **no** es "quitarle la herramienta". `allowed_tools` no es excluyente: en cuanto el [coordinador](../reference/glossary.md#协调者) tiene un `channel` conectado, recibe las dos herramientas `mcp__human__ask` y `mcp__human__inbox` juntas, y puede llamarlas estén o no en la lista. Lo único que frena las preguntas son la cuota y el timeout.

!!! warning "Sin supervisión, no dejes que una pregunta espere para siempre"
    `timeout_s=None` significa "espera indefinida". Si no hay nadie mirando, una sola pregunta puede dejar clavada una ejecución de diez horas, sin error, sin timeout y sin que el log muestre diferencia alguna. Sin supervisión solo hay dos valores correctos: `0` (falla al instante) o un número finito de segundos.

## Qué hace en realidad {#它实际做了什么}

### La forma de `Event` {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15 valores posibles, ver tabla abajo
    text: str = ""
    tool: str = ""                      # solo tool_call trae valor
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # objeto original del SDK / Ask; tocarlo es volver a atarse al SDK
```

`str(ev)`: para `tool_call` es `[工具名] 摘要`, para el resto es `text`; si `text` está vacío, es `<kind>`.

### Los 15 `EventKind` {#15-个-eventkind}

| `kind` | Quién lo emite | Cuándo aparece | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | Texto del modelo | El texto | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | Bloque de razonamiento | El contenido del razonamiento | Igual que arriba |
| `prompt` | `normalize()` | **Entrada**: tu prompt, el task brief repartido a un subagent | El texto de entrada | Igual que arriba |
| `tool_call` | `normalize()` | El modelo inicia una llamada a herramienta | Resumen (`file_path` / `command` / `pattern`, cortado a 200 caracteres) | `id`, `input` + lo anterior; `tool` es el nombre de la herramienta |
| `tool_result` | `normalize()` | La herramienta devuelve | Los primeros 500 caracteres (vacío si el contenido no es una cadena) | `tool_use_id`, `is_error` + lo anterior |
| `result` | `normalize()` | Termina una consulta al SDK | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | Mensaje sintético por caída de conexión | El texto del error | `synthetic: True` |
| `reset` | `normalize()` | Límite de compact o reinicio de sesión | `压缩(trigger) 167000 → 42000 tokens`; en el reinicio de sesión, `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (vacío en el reinicio de sesión) |
| `system` | `normalize()` | Los demás mensajes de sistema del SDK | subtype | `data` tal cual |
| `task` | `normalize()` | Mensajes de progreso de tarea | **vacío** | `kind` = nombre de la clase de mensaje del SDK |
| `unknown` | `normalize()` | Tipo de mensaje no reconocido | Nombre de la clase | — |

!!! note "El texto de `task` está vacío, no lo imprimas sin más"
    `TaskProgressMessage` y similares son tipos de mensaje internos del SDK. Antes `normalize()` emitía el nombre de la clase como texto: en pantalla es puro ruido, y mezclado con el texto del agent parece un error (verificado en la práctica). Ahora se clasifica como un evento **sin texto**, con el nombre de la clase en `payload["kind"]`: mostrarlo o no lo decide la capa de interacción (`events.py`).
| `ask` | `HumanChannel` | Hay que responder, una pregunta llegó a su desenlace, o la persona dijo algo por iniciativa propia | La pregunta / lo que dijo la persona | Dos identidades, ver abajo |
| `retry` | `Runtime` | Reintentando / esperando a que vuelva la red | Una línea de explicación | `step`, `attempt` |
| `step` | `Workflow.run` | Límite de paso | Nombre del paso | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | Relevo: acercándose / escribiendo / terminado | Una línea con el nivel de contexto | `phase`, `step`, `context`, `window` + ver abajo |

**Cuatro kind no los produce `normalize()`**: `ask` viene de `HumanChannel`, `retry` y `handoff` de `Runtime`, y `step` de `Workflow.run`. Ponerlos en el mismo `EventKind` es deliberado: **la UI solo conoce un único `Event` y no necesita otro camino para "hay que responder" o "límite de paso".**

Al escribir la UI, deja una rama `else`. `EventKind` seguirá ganando miembros nuevos, y una UI antigua no debería romperse por eso.

### Las tres phase de `handoff` {#handoff-的三个-phase}

| `phase` | Cuándo se emite | Extra en `payload` |
|---|---|---|
| `near` | El nivel superó `warn_at`. **Solo una vez por generación**, no satura la pantalla | `at` (umbral de relevo) |
| `writing` | Empieza a escribirse el [documento de relevo](../reference/glossary.md#交接书). Tarda una decena de segundos; sin este evento la interfaz parece colgada | — |
| `done` | Relevo escrito y sesión nueva | `degraded` (si es la versión degradada), `path` (dónde se escribió; cadena vacía si no hay workbench), `sections` |

El mecanismo en sí está en [relevo](handoff.md).

### Las dos identidades de `ask` {#ask-的两种身份}

`Event("ask")` transporta a la vez "una pregunta" y "algo que dijo la persona por iniciativa propia": **la UI tiene que mirar primero `payload["kind"]`**.

| Identidad | Cómo se reconoce | `payload` |
|---|---|---|
| Una pregunta | No tiene la clave `kind` | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`; `raw` es ese `Ask` |
| Algo dicho por la persona | `payload["kind"] == "mail"` | `kind`, `state` (`queued` al depositarlo / `delivered` al recogerlo), `id`, `amended` (a qué archivo se anexó; cadena vacía si no está configurado). **No tiene `options` ni `remaining`** |

Una pregunta emite **dos eventos o más**: uno al preguntar (`state="asked"`) y otro al llegar a su desenlace (`answered` / `timeout` / `declined` / `over_budget` / `invalid`). A la UI le basta con actualizar la misma entrada según `payload["id"]`.

### Preguntar a una persona: `Ask` y `HumanChannel` {#问人ask-与-humanchannel}

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
    def waited_s(self) -> float: ...                    # segundos esperados, un decimal
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` es un servidor MCP en proceso más un conjunto de métodos para la UI. El modelo solo ve dos herramientas: `mcp__human__ask` (preguntar, se queda esperando) y `mcp__human__inbox` (consultar la bandeja, **no bloquea**; si está vacía devuelve de inmediato una línea explicativa). Constructor completo:

```python
HumanChannel(
    *,                                  # todo keyword-only
    on_event=None,                      # salida push. Workflow solo la conecta si es None
    max_asks=None,                      # None = sin límite; 0 = no puede preguntar. Al exceder, rechazo directo, sin bloquear
    timeout_s=1800.0,                   # None = espera indefinida; <= 0 = falla al instante
    log_path=None,                      # las preguntas y respuestas se anexan a este archivo, no ocupan contexto
    amend_path=None,                    # lo que diga la persona durante la ejecución se anexa a este archivo, normalmente el brief
    over_budget_text=OVER_BUDGET,       # tres respuestas fijas, se pueden sustituir por las tuyas
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` es el que más se olvida, y decide si "lo que la persona cambia del requisito a mitad de camino" sobrevive al límite de paso.
Cada paso es una [sesión](../reference/glossary.md#会话) nueva sobre un congelado de solo lectura: lo dicho durante la ejecución solo entró en el contexto de aquel agent, y el paso siguiente (por ejemplo el [veredicto](../reference/glossary.md#判定)) es una sesión completamente nueva que lee `需求.md` y `目标.md` y **no ve esa frase que dijiste**, así que juzga con los límites viejos y marca como fuera de alcance justo lo que se acaba de corregir.
`amend_path` **anexa** cada mensaje al [brief](../reference/glossary.md#需求确认书): anexa, no sobrescribe; el requisito original es historia, y ver qué cambió es mejor que no verlo. `starter_flow` lo conecta por defecto a `<workbench>/notes/需求.md`.

En la práctica ($0.6767) esto funcionó incluso mejor de lo esperado: la persona dijo "de paso, informa del total de bytes"; el coordinador lo vio al consultar la bandeja y respondió que "hand ya lo ha leído y calculado a partir del añadido en ejecución de `.flower/notes/需求.md`, no hace falta repartirlo otra vez".
**El subagent lo leyó del archivo, no dependió de que nadie se lo contara.**

Miembros públicos:

| Miembro | Firma | Semántica |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | Se pasa directamente a `AgentSpec.mcp_servers`. La clave tiene que coincidir con el nombre del server, por eso lo entrega él mismo |
| `ask` | `async (question, options=None) -> Ask` | Se queda esperando a la persona. **Nunca lanza excepciones salvo `CancelledError`**: que nadie responda también es una respuesta, se distingue con `ask.state` |
| `pending` | `() -> list[Ask]` | Preguntas que ahora mismo esperan respuesta |
| `next_ask` | `async (timeout=None) -> Ask \| None` | Para UI en modo pull. Devuelve `None` al agotar el timeout; si se cancela, lanza |
| `answer` | `(ask_id, text) -> bool` | Responder. `False` = esa pregunta ya no está esperando (timeout / ya respondida) |
| `decline` | `(ask_id, reason="") -> bool` | Saltarla: que el modelo decida por su cuenta y escriba la suposición en 「未知与假设」 |
| `send` | `(text) -> Mail \| None` | La persona dice algo por iniciativa propia, va a la bandeja. No interrumpe al agent; internamente llama a `amend()` |
| `amend` | `(text, *, label="运行中补充") -> bool` | Anexa a `amend_path`. Devuelve si realmente escribió (sin ruta configurada / texto vacío / `OSError` dan `False`) |
| `pending_mail` | `() -> list[Mail]` | Lo dicho que aún no se ha recogido |
| `remaining` | `-> int` | Cuántas preguntas quedan. Con `max_asks=None` devuelve **`-1`**, no 0 |
| `transcript` | `() -> str` | El markdown del registro de preguntas y respuestas |
| `asks` / `mail` / `ui_errors` | `list` | Todas las preguntas / todo lo dicho por la persona / las excepciones lanzadas por los callbacks de la UI |

`answer`, `decline` y `send` **se pueden llamar desde cualquier hilo**. El hilo que atiende peticiones en un backend Web o el hilo de entrada de una TUI están en otro hilo: eso es lo normal, no un caso límite. Por dentro va por `loop.call_soon_threadsafe`, porque `asyncio.Future.set_result` no es seguro entre hilos.

Push y pull son dos formas de obtenerlas: **elige una**.

| | Cómo se obtiene | Para qué sirve |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, cuando llega `kind == "ask"` con `payload["state"] == "asked"` | UI dirigida por eventos (push Web, redibujado de TUI) |
| **Pull** | `await channel.next_ask()` | Una tarea de entrada independiente |

Los tres "0 / None" tienen semánticas distintas; confundirlos significa quedarse colgado sin supervisión o no preguntar nunca:

| Escritura | Significado |
|---|---|
| `max_asks=None` | Sin límite de veces (por defecto) |
| `max_asks=0` | Prohibido preguntar, rechazo directo |
| `timeout_s=None` | Espera indefinida |
| `timeout_s<=0` | No espera, la pregunta falla al instante |
| `remaining` devuelve `-1` | El valor cuando `max_asks=None`, no 0 |

### Interrupción: cualquier hilo puede pedir parar {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")`; con cadena vacía se interrumpe sin decir nada. Tres propiedades:

- **Continúa la misma sesión** (`resume`), no empieza de cero: el trabajo ya hecho y el contexto siguen ahí. Reutiliza el camino ya existente del reintento por caída de red, cambiando solo el "motivo del fallo" por "una persona ha interrumpido" y el `resume_prompt` por lo que dijo esa persona.
- **No consume `max_attempts`**. Esa cuota es para las averías, no para las personas.
- **Es cooperativa**: corta en un límite de mensaje, no cancela la tarea a la fuerza. El coste es la latencia hasta el mensaje siguiente (si hay un subagent en marcha, hay que esperar a que vuelva); a cambio, no se desgarra el estado a mitad de camino.

El coste, dicho tal cual: interrumpir hace que **un subagent en vuelo pierda su trabajo a medias** (verificado en la caída de red de HT001, ver [issue #2](https://github.com/ChenyuHeee/flower/issues/2)). La implementación de referencia de terminal lo indica en su mensaje, para que la persona lo sepa antes de pulsar; si escribes tu propia UI, deberías hacer lo mismo.

Si no quieres interrumpir y solo quieres añadir un requisito, usa la bandeja de entrada (`ch.send(...)`): no interrumpe nada, y la latencia es hasta el siguiente punto de control del agent.

### Oráculo: preguntar algo sin molestar a la ejecución {#旁路顾问问一句而不打扰运行}

Para saber "por dónde va ahora" no hace falta interrumpir, y tampoco hay que preguntárselo al coordinador: esa conversación **ocuparía permanentemente el contexto del hilo principal** (que contiene decisiones, no registros de preguntas), y además tendría que soltar lo que está haciendo. En una ejecución de diez horas, tres preguntas sueltas ya pagan ambos costes.

El [oráculo](../reference/glossary.md#旁路顾问) es una vía lateral de solo lectura. Sus únicas herramientas son `Read` / `Glob` / `Grep`, tiene el workbench abierto y viene con freno por defecto: `max_turns=12`, `max_budget_usd=0.5`. En la terminal se dispara con una línea que empiece por `?`, y responde con dos cosas: la ventana de eventos reciente (60 fijos) y el brief, los objetivos, las notas y los productos del workbench.
Usa un `Runtime` independiente (`<run_dir>/aside`), así que su coste y su [linaje](../reference/glossary.md#血缘) de sesiones **no se mezclan con el manifiesto principal**: ese manifiesto registra "qué pasos hizo esta ejecución", y preguntar algo de pasada no es un paso.

Verificado: dos preguntas por un total de $0.5190, y el manifiesto de la ejecución principal no creció ni un byte.

### Dos reglas duras {#两条硬规矩}

!!! warning "on_event ni puede bloquear ni puede dejar escapar excepciones"
    **Uno: `on_event` es una función síncrona y se llama en el hilo del bucle de eventos.** Por eso `asyncio.Queue.put_nowait()` es seguro y `await` no lo es (no es una corutina), y **bloquearla es bloquear toda la ejecución**. Si hay trabajo lento, mételo en una cola y que otra tarea lo haga.

    **Dos: lanzar una excepción dentro de `on_event` daña la ejecución en sí.** Los eventos de texto se emiten dentro del bloque `try` de `Runtime._attempt`, y la excepción se registra como `result.error`: ese paso se da por fallido. Los eventos `retry` se emiten fuera de ese bloque, y la excepción sale directamente de `Runtime.run`. El frontend no debe llevarse tres horas de trabajo: **envuélvelo tú en un try**.

    Excepción: los eventos `ask` que emite el propio `HumanChannel` ya vienen envueltos; las excepciones se recogen en `channel.ui_errors` y no interrumpen la ejecución.

## Cuándo no deberías usarlo {#什么时候不该用它}

### Lo que no debe hacer la capa de interacción {#交互层里不该做的事}

| No hacer | Por qué | Qué hacer en su lugar |
|---|---|---|
| `from claude_agent_sdk import ...` | En cuanto la capa de interacción depende de tipos del SDK, cada actualización del SDK arrastra al frontend, y esta capa deja de servir | Usa solo `kind` / `text` / `tool` / `payload` de `Event` |
| Leer `ev.raw` | Igual que arriba, y además no es serializable a JSON | Si falta algún detalle, añádelo al `payload` de `normalize()`, no rodees la frontera |
| Hacer `await`, peticiones de red o escrituras lentas dentro de `on_event` | Es síncrona y se llama en el hilo del bucle de eventos; bloquearla es bloquear toda la ejecución | `put_nowait()` a una cola y consúmela desde otra tarea |
| Dejar que `on_event` lance excepciones | La excepción en un evento de texto se convierte en `result.error` y ese paso se da por fallido | Envuelve todo el cuerpo del callback en `try` |
| Usar `disallowed_tools` para desactivar las preguntas | Es de **ámbito de sesión** y deshabilita también la herramienta homónima en los subagent (error real observado: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` o `timeout_s=0` |
| Quitar `mcp__human__ask` de `allowed_tools` creyendo que así se prohíben las preguntas | `allowed_tools` no es excluyente: es una lista de exención de aprobación, no una lista blanca; con el `channel` conectado se entregan las dos herramientas juntas | Igual que arriba |
| Armar rutas a mano para buscar `需求.md` / `目标.md` | El workbench puede estar en dos sitios; equivocarse no da error, solo falla en silencio | `wake_state()` o `wf.workbench` |
| Reconstruir progreso y resultado a partir del flujo de `Event` | El texto queda partido en varios trozos por los relevos y los reintentos | `on_step(step, result)` te da el `StepResult` completo |
| Usar `timeout_s=None` sin supervisión | Nadie responde, la ejecución queda colgada para siempre, sin error y sin timeout | `0`, o un número finito de segundos |

### Cuándo directamente no hace falta cambiar nada {#什么时候根本不用换}

- **Solo quieres cambiar colores o imprimir una línea más o menos**: con tocar la función de renderizado basta. En la implementación de referencia de terminal, la interrupción, el oráculo, los acuses de la bandeja de entrada, el rescate ante SIGHUP / SIGTERM y la espera al cierre de la vía lateral antes de salir no son baratos de reescribir.
- **Solo quieres ejecutar un paso, sin interacción**: usa `flower once`. No pasa por el camino de la interacción, así que de entrada no tiene interrupción con Ctrl+C, ni hilo de respuesta por entrada estándar, ni oráculo, ni rescate por señales.
- **Lo que en realidad quieres cambiar es el workflow, no la UI**: ver [diseñar el workflow](workflow.md). La capa de interacción solo decide quién mira y quién responde; cuántos pasos se ejecutan, cómo se juzga y cuándo se sale antes lo decide `Workflow`.
- **Lo que quieres cambiar es el almacén de sesiones, el modelo o el presupuesto**: ninguna de esas tres cosas está en esta frontera, ver la [referencia de la API de Python](../reference/api.md).
