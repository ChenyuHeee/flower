# Continuidad

Vuelve a ejecutar `flower` en el mismo directorio y seguirá hablando desde donde quedó la conversación anterior —— da igual si mataron el proceso, si el terminal se cayó o si la máquina se reinició. No necesitas conocer la palabra «sesión» ni recordar ningún id. Esta página explica en qué se apoya, cuándo falla en silencio y cómo evitar la continuidad a propósito.

!!! note "La continuidad no es un relevo"
    La [continuidad](../reference/glossary.md#接续) es **entre procesos**: el siguiente proceso engancha con la [ejecución](../reference/glossary.md#运行) anterior.
    El [relevo](../reference/glossary.md#换代) ocurre **dentro de la misma ejecución**: el contexto está casi lleno, la [sesión](../reference/glossary.md#会话) actual
    escribe un [documento de relevo](../reference/glossary.md#交接书) y una sesión nueva toma el testigo —— ver [relevo](handoff.md).

    Ambos encajan solos, sin cableado extra: el [linaje](../reference/glossary.md#血缘) siempre registra la **última** sesión
    que tomó el relevo en ese paso, así que el siguiente despertar engancha con quien tomó el relevo.

## Qué problema resuelve {#解决什么问题}

En disco está todo, en realidad. `runs/sessions.db` guarda el transcript **completo** de cada sesión histórica, `需求.md` / `目标.md`
son piezas congeladas y el código está en el espacio de trabajo.

**Lo único que se pierde es una línea de mapeo** —— «qué sesión usó qué paso». Antes vivía solo en memoria, en `ctx["_sessions"]`,
y desaparecía al salir el proceso. Así que el proceso nuevo arrancaba y el [coordinador](../reference/glossary.md#协调者) era un recién llegado con amnesia: a quién había enviado,
qué callejones sin salida había probado, por qué había descartado cierta solución —— todo otra vez desde cero.

En [HT002](../cases/ht002.md) dio vueltas durante una hora probando flags de compilación. Cambia de proceso y esa hora se tira a la basura.

## Cómo se usa (código mínimo) {#怎么用最小代码}

En la línea de comandos no hay nada que configurar: esa ruta trae la continuidad activada por defecto:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # 第一次
# …跑完,或者你按 Ctrl-C 走人,或者机器重启了

cd ~/proj && flower "顺便支持代码块高亮"          # 接着上次那段对话
cd ~/proj && flower                              # 什么都不说 = 接着做
cd ~/proj && flower --new "另一件事"              # 这次别接上次
```

Cuando escribes tu propio [flujo de trabajo](../reference/glossary.md#流程), la continuidad también está activada por defecto —— el valor por defecto de `Workflow.continuous` es
`True`:

```python
import asyncio

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous 默认 True
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # 第几次唤醒,第一次跑是 1
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

Si ejecutas este mismo código por segunda vez en el mismo directorio, `ctx["_woke"]` vale `2` y `ctx["_sessions"]["取词"]`
**es el mismo id** que la primera vez —— el paso 取词 retomó aquella sesión en lugar de abrir una nueva.

!!! tip "Solo quiero saber si este directorio engancha o no"
    `wake_state()` es una sonda de solo lectura, **no escribe ni un byte**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    Devuelve `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = el brief existe y tiene las cuatro secciones completas;
    `checks` = cuántos puntos tiene la lista de veredicto; `woke` = cuántas veces se ha despertado ya; `steps` = mapa de nombre de paso a session_id.
    La línea de comandos se apoya en esto para decidir si el prompt pregunta «qué hay que hacer» o «seguimos con lo anterior».

## Qué hace en realidad {#它实际做了什么}

### Los tres archivos que quedan en disco {#落在磁盘上的三个文件}

`run_dir` es `./runs` por defecto, **relativo al directorio de trabajo actual, no al workspace**.

| Ruta | Qué guarda |
|---|---|
| `runs/lineage.json` | El linaje: `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. La continuidad depende entera de esto |
| `runs/sessions.db` | SQLite, transcripts completos. Las tablas son `entries` / `meta` / `summaries`, la clave es `project_key/session_id[/subpath]` —— los transcripts de subagentes se guardan aparte con el subpath |
| `runs/manifest.json` | Array JSON, el manifiesto de ejecución **acumulado entre procesos**. Una línea por paso; es el único sitio donde buscar un session_id a posteriori |

El archivo de linaje tiene esta pinta:

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

Cada línea de `manifest.json` lleva todos los campos de `StepResult` —— `step`, `session_id`, `ok`, `cost_usd`,
`num_turns`, `text`, `error`, `started_at`, `ended_at`, `attempts`, `errors[]`, `resumed`,
`retired[]`, `context` —— más dos añadidos a mano: `duration_s` (es una `@property`, `asdict()` no la recoge) y
`run` (marca de proceso, `YYYYmmdd-HHMMSS-<6 位 hex>`).

El nombre del paso aparece ahí en cuatro formas, y de un vistazo se ve cómo terminó ese paso: `<步骤名>` (primer intento),
`<步骤名>#retry<N>` (reintento normal), `<步骤名>#round<N>` (el veredicto no pasó, vuelve para seguir trabajando),
`<步骤名>·判定#<N>` (la ronda del [juez](../reference/glossary.md#判定者)).

La escritura **añade, no sobrescribe**: en cada volcado se relee el archivo entero y se deduplica por el campo `run` —— las líneas de este proceso se sustituyen por las últimas,
las de otros se dejan tal cual. Por eso es seguro correr varios flower en paralelo sobre el mismo directorio.

### `continuous=True` cambia la semántica de `resume_from` {#continuoustrue-改变了-resume_from-的语义}

Este es el punto que más se escapa: `Workflow.continuous` es `True` por defecto, así que `resume_from=None`
**no equivale a «sesión nueva»**.

| Forma | Dentro de la misma ejecución | Entre procesos (`continuous=True`) |
|---|---|---|
| `resume_from=None` (por defecto) | Sesión nueva, solo con el contexto que llega en el prompt | **Retoma la sesión que el linaje tiene para el paso con ese nombre** |
| `resume_from="上一步名"` | Retoma la misma sesión, contexto completo | Igual que a la izquierda |
| `resume_from=…, fork=True` | Bifurca, sin contaminar la sesión original | Igual que a la izquierda |

Para que cada proceso arranque con una sesión limpia hay que escribirlo explícitamente: `Workflow(..., continuous=False)`.

Al cargar el linaje hay además una verificación: cada `(nombre de paso, session_id)` que se lee pasa antes por `runtime.has_session(sid)`
para confirmar que sigue en `sessions.db`, y solo se usa si está vivo. La razón es que el archivo de linaje puede sobrevivir a `sessions.db`,
y hacer resume de una sesión inexistente no revienta hasta que arranca el subproceso.

!!! warning "El nombre del paso es la clave estable entre procesos"
    El linaje se indexa por `Step.name`. **Cambiar el nombre de un paso equivale a cortar el linaje** —— no da error, simplemente la siguiente ejecución empieza con una sesión nueva.
    Los nombres con sufijo (`#retry`, `#round`, `·判定#`) no entran en el linaje; `Lineage.remember` usa siempre el nombre original.

### Dos invariantes {#两条不变式}

**Uno: en cuanto se obtiene el session_id se escribe a disco, sin esperar a que el paso termine.**

Que maten el proceso a lo bruto es justo el escenario del que hay que protegerse. Ya nos costó una: el 2026-09-07 Terminal.app se cayó dos veces, el kernel mandó SIGHUP,
y la acción por defecto de SIGHUP es terminar directamente: el `finally` no ejecuta ni una línea. Entonces el linaje se escribía en los **límites de paso**,
así que en aquella ejecución que murió dentro del primer paso `steps` quedó vacío y hubo que responder otra vez preguntas ya respondidas (ver issue #6).

Ahora `Runtime.on_session` escribe a disco en el instante mismo en que obtiene el id —— en la práctica, lo más pronto es el primer mensaje del assistant,
porque el mensaje de sistema de init no trae `session_id` en el SDK de Python. Al escribir, primero un `.tmp` y luego reemplazo atómico:
si lo matan a mitad no queda medio archivo; si la escritura falla (`OSError`), se traga en silencio y no se lleva por delante la ejecución.

Este hook **solo cubre la línea de `runtime.run`**; antes del gate se desmonta con `try/finally`. El juez usa el mismo
`Runtime`, y si siguiera montado su sesión acabaría escrita en el linaje del paso 干活.

**Dos: si algo no cuadra, se hace como si no existiera; no se lanza error.**

Hay tres formas de que no cuadre: cambió la ruta del espacio de trabajo (el directorio se copió a otro sitio —— [HT001](../cases/ht001.md) se sacó justamente de un contenedor),
la sesión ya no está en la base (se borró `sessions.db`), o el archivo de linaje está corrupto. Cualquiera de las tres cae en silencio a «empezar de cero».

El campo `workspace` es el guardián: el `project_key` del SDK se deriva de la ruta del espacio de trabajo (`/`, `_` y `.` se sustituyen por `-`),
y tras copiar el directorio el session_id viejo no se encuentra en la ubicación nueva, así que si la ruta no cuadra se hace como si no existiera.

**La continuidad es un extra; que falle no debe impedir que la gente trabaje.**

### Proceso matado, y reinicio de la máquina {#进程被杀和机器重启}

El resultado de ambas cosas es el mismo —— se retoma —— pero el proceso es distinto:

| Caso | Qué ocurre | La siguiente ejecución |
|---|---|---|
| `Ctrl-C` una vez | Interrupción cooperativa, corte limpio en un **límite de mensaje**. Puedes aprovechar para decir algo y, dentro del mismo proceso, retomar esa misma sesión y seguir. La interrupción no cuenta como intento fallido ni consume cuota de reintentos | No implica continuidad |
| `Ctrl-C` dos veces | Lanza `KeyboardInterrupt` y sale. El cierre solo llega a cerrar el almacén: **el paso en vuelo no entra en `manifest.json`** | El linaje ya se escribió hace rato; engancha |
| `SIGTERM` / `SIGHUP` | El handler llama primero a `rescue()`, que escribe también el paso en vuelo en `manifest.json` (marcado `error="killed-by-signal"`), y luego restaura la acción por defecto y se va de verdad | Igual que arriba; engancha |
| `SIGKILL`, corte de luz, reinicio de la máquina | Ningún cierre en absoluto | Engancha igualmente —— los tres archivos están en disco y el linaje se escribió en el instante de obtener el id |

La única condición es una: **el mismo `workspace` más el mismo `run_dir`**. `run_dir` es relativo al directorio de trabajo actual,
así que si tecleas `flower` desde otro directorio irá a buscar otro `runs/` y no engancha.

### El juez siempre es una sesión nueva {#判定者永远是新会话}

Esto está **garantizado por construcción**, no por acordarse.

El juez no es un `Step` —— sale directamente de un `rt.run()` dentro del gate de `with_goal`
(ver [guardián de objetivos](goal.md)), y nunca pasa por la vía del linaje. Así que en cada ronda y en cada despertar es un par de ojos completamente nuevos.

Y ahí está todo su valor: **no sabe cuántas veces lo intentó el ejecutor ni lo mucho que sufrió, así que no le busca excusas.**
Si lo hicieras seguir la continuidad, el guardián de objetivos degeneraría en una autoauditoría.

La sección 4 de `tests/lineage_offline.py` deja esto clavado.

### Lo que dices al despertar tiene que aterrizar en tres sitios {#唤醒时说的那句话要落到三个地方}

`flower "顺便支持代码块高亮"` en un directorio ya usado **no es una tarea nueva: es otra frase más en la conversación**.
Hace tres cosas a la vez —— si falta una, falla en silencio:

| Dónde aterriza | Qué pasa si falta |
|---|---|
| Se añade a `需求.md` (`## 唤醒时追加`) | No sobrevive al límite de paso. El siguiente paso es una sesión nueva y solo lee las piezas congeladas |
| Se usa como prompt del paso 干活 | El coordinador ni se entera |
| **Dispara la rederivación de `目标.md`** | El juez sigue leyendo la lista vieja: **si lo recién añadido se hizo o no, ni siquiera entra en el veredicto** |

La tercera es la que más se escapa. El juez solo lee el `目标.md` congelado; lo que añadas a mitad de camino no lo ve —— si no se rederiva, dictará «cumplido» según la lista vieja
y aquello que tú querías no se habrá verificado en absoluto. El precio es una pasada extra de 设定目标 por cada añadido ([HT002](../cases/ht002.md) medido:
$0.41 / 3 minutos).

**Despertar sin decir nada** (pulsar Intro directamente) no añade ni rederiva: no cuesta ni un céntimo de más.

### También se retoma si murió dentro del primer paso (确认需求) {#崩在第一步确认需求之内也能接上}

`clarify_step` trae un `resume_prompt` (la constante `CLARIFY_RESUME`): si murió a mitad de la confirmación y vuelves a arrancar,
al [clarificador](../reference/glossary.md#确认者) se le dice «continúa con la confirmación de requisitos que quedó a medias ——
no empieces de nuevo», en lugar de reenviarle la petición original como si fuera una tarea nueva. Junto con la invariante de arriba («en cuanto hay session_id, a disco»),
aquella ejecución que moría en el primer paso con `需求.md` aún sin congelar también se retoma ahora, sin tener que responder otra vez.

Al revés, los pasos previos ya congelados **se saltan enteros**: si `需求.md` tiene las cuatro secciones completas se salta 确认需求 (pero el contenido igual se vuelca en ctx),
y si `目标.md` está completo se salta 设定目标.

### Al retomar no se envía la misma frase {#接续时发的不是同一句话}

De esto se encarga `Step.resume_prompt`. En el contexto del otro lado **ya están** el brief, los objetivos y hasta dónde llegó la vez anterior; reenviar
«haz esto según estos requisitos: <brief completo>» tal cual es puro ruido, y peor aún: se lee como «los requisitos han cambiado, vuelve a mirarlos».

Si no das `resume_prompt` se reutiliza `prompt` —— hay pasos en los que reenviar el texto completo es lo correcto (cuando 设定目标 rederiva la lista,
lo que necesita es justamente ese brief completo).

### Al despertar, primero una línea de informe {#唤醒时先报一行}

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Sin ese informe, «¿se acuerda o no se acuerda?» resulta completamente imperceptible, y eso es todo el valor de esta capa. En el banner,
`需求已确认` aparece siempre, `目标 N 条` solo si la lista de veredicto no está vacía, y `干活上下文 X` requiere poder consultar en `sessions.db`
el tamaño de contexto de la última ronda de esa sesión.

**Ese número de contexto está puesto ahí a propósito** —— la razón está en la sección «El precio», más abajo.

### Resiliencia: esperar colgado cuando se cae la red, y que los errores no entren en el contexto tras retomar {#韧性断网时挂着等而且错误不进接续后的上下文}

La [resiliencia](../reference/glossary.md#韧性) va emparejada con la continuidad: en una ejecución de varias horas la red se cae seguro, y el comportamiento por defecto es pésimo ——
en el instante del corte, el harness mete en el transcript un **mensaje de assistant sintético** (`isApiErrorMessage=true`,
`model="<synthetic>"`) cuyo cuerpo es "API Error: Can't reach the API server …". Ese mensaje queda como hoja de la sesión,
y a partir de ahí el resume se lo devuelve al modelo como «lo último que dijiste»: el modelo cree que está discutiendo una avería de red.

`Resilience` hace tres cosas:

**Uno: la sonda solo hace DNS + TCP.** `reachable(host, port, timeout=5.0)` solo ejecuta `getaddrinfo` más un handshake TCP,
**no manda HTTP, no lleva credenciales, no cuesta dinero**; cualquier excepción cuenta como inalcanzable. Qué dirección se sondea lo decide `endpoint()`, que sigue a
`ANTHROPIC_BASE_URL`, por defecto `https://api.anthropic.com`, con puerto por defecto `443` (`80` para http).
**Si usas tu propia pasarela, tienes que sondear la pasarela** —— que `api.anthropic.com` responda no dice nada sobre la pasarela.

**Dos: distinguir lo que hay que esperar de lo que hay que abortar.** `classify(text)` devuelve `"transient"` / `"fatal"` / `"unknown"`,
y **evalúa fatal antes que transient** —— los textos tipo 401 suelen llevar la palabra "connection", y con el orden invertido te quedas esperando eternamente.
Valores por defecto: `max_attempts=6` (incluido el primero), `base_delay=4.0`, `max_delay=120.0`, `probe_timeout=5.0`,
`probe_interval=15.0`, `max_offline_wait=3600.0` (1 hora), `retry_unknown=True`.
El backoff es `min(base_delay * 2**(attempt-1), max_delay)` multiplicado por un jitter de ±25%.

Si ya se obtuvo un session_id, **se retoma con resume en vez de empezar de cero**, y lo gastado antes no se tira. Al retomar se envía
`Resilience.resume_prompt`: «la ronda anterior se interrumpió a mitad y no llegó a terminar. Mira lo que ya está escrito en el banco de trabajo,
sigue desde donde se cortó y no empieces de nuevo». **Deliberadamente no incluye ningún detalle del error** —— el modelo necesita saber «te interrumpieron, sigue»,
no si fue un ENOTFOUND o un 503.

**Tres: los errores que genera la tormenta de reintentos no entran en el contexto después del resume.** De esto se encarga la [poda](../reference/glossary.md#剪除).
El almacén de sesiones de `Runtime` está fijado a `PruningSessionStore`, que en `load()` hace tres cosas:

- Quita los mensajes sintéticos de error de API. **En SQLite se conservan tal cual**, simplemente no se devuelven al modelo
- Quita las llamadas denegadas antiguas, dejando solo las `keep_denials=1` más recientes
- Sustituye los `tool_result` residuales de una interrupción por una nota neutra, «[la ronda anterior se interrumpió aquí, este resultado de herramienta no llegó a producirse]»; solo cambia el cuerpo, no elimina la entrada

Dejar 1 en vez de 0 tiene su razón: una llamada denegada nunca se ejecutó, su resultado no tiene información y sin embargo ocupa bastante
(medido una vez: 273 caracteres = 93 caracteres de negativa + 180 caracteres del **comando muerto original**), y además **induce a error** ——
en la práctica, tras leer varios «no uses Bash directamente», el coordinador dejaba de intentar incluso un `git status` permitido: aprendía indefensión.
Pero la más reciente sí sirve: evita que el modelo reintente una y otra vez el mismo comando bloqueado dentro de la misma ronda.

Quitar entradas tiene una línea roja estructural: el transcript es una cadena simple por `parentUuid`, así que al quitar una hay que reenganchar a sus hijos con el ancestro vivo más cercano;
si no, la cadena se corta ahí y se pierde todo el historial anterior.

En [HT001](../cases/ht001.md) se dio una vez de verdad: corte de red de 01:52:40 → 01:55:41, y ese paso figura en `manifest.json` con
`attempts=2` / `resumed=True` / `ok=True`; tras retomar siguió corriendo más de 8 horas hasta terminar.

Un último punto que se malinterpreta fácil: **`Runtime(trim=False)` no significa «no se limpia nada»**. `trim` es `False` por defecto,
pero solo apaga la capa de **[recorte](../reference/glossary.md#裁剪) de resultados grandes de herramientas**. Quitar residuos de corte de red, quitar llamadas denegadas,
neutralizar residuos de interrupción y marcar como caducados los resultados de [comandos efímeros](../reference/glossary.md#一次性命令) —— esas cuatro se siguen haciendo
(`ephemeral` por defecto `True`, `keep_denials` por defecto `1`).

### El precio: el contexto crece sin parar, y sin final {#代价上下文会一直涨而且没有尽头}

Este es el coste inherente de la continuidad, no un bug.

El paso 干活 de [HT001](../cases/ht001.md) corrió 10.44 horas seguidas, y el contexto del [hilo principal](../reference/glossary.md#主线程) fue
**28.7K** en la ronda 1, **35.2K** en la 20, **108.6K** en la 35, **158.2K** en la 50 y **185.9K** en la 70:
monótonamente creciente, con una pendiente de unos **2.2K/ronda**; sin ningún compact en todo el trayecto, consumiendo el **18.6%** de una ventana de 1M. Extrapolando con esa pendiente,
el muro llega hacia la ronda **440** —— el límite de «largo horizonte» en la forma actual es unas **6 veces** aquella ejecución. Continuidad permanente significa que algún día chocas con la ventana.

Dos mecanismos lo gestionan:

1. **Recorte** (`flower --no-trim` lo apaga; la ruta de `flower` lo trae activado) —— al retomar, sustituye los resultados grandes y viejos de herramientas por
   punteros a archivo: el contenido no se pierde, simplemente no reside en el contexto
2. **[Relevo](handoff.md)** —— al llegar al umbral se escribe un documento de relevo y se cambia a una sesión nueva. **No es [compact](../reference/glossary.md#压缩)**:
   el documento es legible y editable, ves qué se ha perdido. Por eso el contexto baja periódicamente en vez de subir sin parar hasta el muro

**Por eso la línea del despertar tiene que informar del tamaño de contexto**: si la persona lo ve, tiene la oportunidad de decidir por sí misma reabrir antes de chocar.

De paso: `--rounds` (el total de rondas de 干活) **se reinicia en cada despertar**. Es intencionado —— un despertar nuevo es una intención nueva,
y no debería heredar las rondas gastadas la vez anterior.

### Reabrir con otra cosa {#重开一件事}

```bash
flower --new "另一件事"
```

O directamente escribiendo `/new` en el prompt de despertar:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> /new
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> …
```

**Se archiva, no se borra.** `lineage.json`, `需求.md` y `目标.md` se **mueven** juntos a `notes/archive/<YYYYmmdd-HHMMSS>/`,
y a la vez se ponen a cero `steps` y `woke` del linaje. Los tres son tres caras del mismo trozo de historia; recoger solo una parte deja estados a medias del tipo «los objetivos siguen ahí pero la conversación se fue».

`sessions.db` no se toca —— es el archivo histórico, y cada transcript de dentro sigue siendo consultable.

En código, el equivalente es `Lineage.archive(into, extra=[...])`.

## Cuándo no deberías usarla {#什么时候不该用它}

- **Escenarios que exigen un punto de partida limpio cada vez.** Correr el mismo flujo en lote, hacer evaluaciones comparativas, reproducirle un bug a otra persona ——
  nada de eso debería arrastrar el contexto anterior. Escribe `Workflow(..., continuous=False)`, o cambia de `run_dir` en cada ejecución.
- **El directorio se va a mover o copiar, o el `run_dir` no es persistente.** Correr dentro de un contenedor con `runs/` en el sistema de archivos interno,
  o hacer rsync del espacio de trabajo a otra máquina —— la continuidad **fallará en silencio** (el guardián de rutas rechaza el linaje que no cuadra);
  no la trates como una garantía.
- **Esta vez es una intención nueva y el contexto ya es grande.** La continuidad te hace cargar con historia irrelevante y pagas tokens por ella en cada ronda.
  Antes que aguantarlo, `--new`: archiva y reabre.
- **Un agente único de usar y tirar.** `flower once` no pasa por `Workflow` y no tiene linaje; para retomar hay que dar `--resume <session_id>` a mano.
- **Usar la continuidad como copia de seguridad.** Solo registra «qué sesión usó qué paso». El código, los entregables y las decisiones deben aterrizar en el espacio de trabajo y en el
  [banco de trabajo](../reference/glossary.md#工作台); no esperes desenterrarlos del transcript.

## Qué leer a continuación {#相关}

- [Relevo](handoff.md) —— qué hacer cuando el contexto se llena dentro de la misma ejecución; es la misma cosa que esta página, en la otra dirección
- [Guardián de objetivos](goal.md) —— por qué el juez no hereda continuidad
- [Economía del contexto](context.md) —— de qué se encarga cada uno: recorte, poda y volcado
- [Python API](../reference/api.md) —— `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Línea de comandos](../reference/cli.md) —— `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Código fuente: [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
