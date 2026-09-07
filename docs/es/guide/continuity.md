# Continuidad

Vuelve a ejecutar `flower` en el mismo directorio y seguirá hablando desde donde se quedó la
conversación anterior — da igual que hayan matado el proceso, que el terminal se cayera o que la
máquina se reiniciara. No necesitas saber qué es una session ni recordar ningún id. Esta página
explica en qué se apoya, cuándo falla en silencio y cómo evitar reenganchar a propósito.

!!! note "Continuidad no es relevo"
    La [continuidad](../reference/glossary.md#接续) es **entre procesos**: el siguiente proceso
    reengancha con la [ejecución](../reference/glossary.md#运行) anterior.
    El [relevo](../reference/glossary.md#换代) es **dentro de la misma ejecución**: el contexto está
    a punto de llenarse, la [sesión](../reference/glossary.md#会话) actual escribe un
    [documento de relevo](../reference/glossary.md#交接书) y una sesión nueva toma el testigo —
    ver [Relevo](handoff.md).

    Ambos encajan automáticamente, sin cableado extra: el [linaje](../reference/glossary.md#血缘)
    registra siempre la **última** sesión que tomó el relevo en ese paso, así que el siguiente
    despertar reengancha con la sucesora.

## Qué problema resuelve

En disco está todo, en realidad. `runs/sessions.db` tiene el transcript **completo** de cada sesión
histórica, `需求.md` / `目标.md` son piezas congeladas y el código está en el espacio de trabajo.

**Lo único que se pierde es una línea de mapeo** — «qué paso usó qué session». Antes vivía solo en
memoria, dentro de `ctx["_sessions"]`, y desaparecía en cuanto el proceso salía. Así que el proceso
nuevo arranca y el [coordinador](../reference/glossary.md#协调者) es un recién llegado con amnesia:
a quién despachó, qué callejones sin salida probó, por qué descartó cierto plan — todo otra vez
desde cero.

En [HT002](../cases/ht002.md) se pasó una hora dando vueltas probando flags de compilación. Cambia
de proceso y esa hora se tira a la basura.

## Cómo se usa (código mínimo)

En la línea de comandos no hay nada que configurar: por la ruta `flower` la continuidad viene
activada por defecto:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # la primera vez
# …termina, o te vas con Ctrl-C, o la máquina se reinicia

cd ~/proj && flower "顺便支持代码块高亮"          # sigue la conversación anterior
cd ~/proj && flower                              # no decir nada = seguir donde iba
cd ~/proj && flower --new "另一件事"              # esta vez, no reenganchar
```

Cuando escribes tu propio [workflow](../reference/glossary.md#流程), la continuidad también está
activada por defecto — el valor por defecto de `Workflow.continuous` es `True`:

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
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous es True por defecto
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # número de despertar; en la primera ejecución es 1
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

Ejecuta este código por segunda vez en el mismo directorio: `ctx["_woke"]` vale `2` y
`ctx["_sessions"]["取词"]` es **el mismo id** que la primera vez — el paso `取词` continuó aquella
sesión en lugar de abrir una nueva.

!!! tip "Solo quieres saber si este directorio reengancha"
    `wake_state()` es una sonda de solo lectura, **no escribe ni un byte**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    Devuelve `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = el brief existe y
    tiene las cuatro secciones completas; `checks` = cuántos ítems tiene la lista de veredicto;
    `woke` = cuántas veces se ha despertado ya; `steps` = mapeo de nombre de paso a session_id.
    La línea de comandos se apoya en esto para decidir si el prompt pregunta «qué hay que hacer» o
    «seguir donde iba».

## Qué hace realmente

### Los tres archivos que quedan en disco

`run_dir` es `./runs` por defecto, **relativo al directorio de trabajo actual, no al workspace**.

| Ruta | Qué guarda |
|---|---|
| `runs/lineage.json` | Linaje: `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. La continuidad depende enteramente de esto |
| `runs/sessions.db` | SQLite, transcript completo. Las tablas son `entries` / `meta` / `summaries`; la clave es `project_key/session_id[/subpath]` — el transcript de los subagents se guarda aparte mediante subpath |
| `runs/manifest.json` | Array JSON, el manifiesto de ejecución **acumulado entre procesos**. Una línea por paso; es el único sitio donde consultar un session_id a posteriori |

El archivo de linaje tiene esta pinta:

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

Cada línea de `manifest.json` lleva todos los campos de `StepResult` — `step`, `session_id`, `ok`,
`cost_usd`, `num_turns`, `text`, `error`, `started_at`, `ended_at`, `attempts`, `errors[]`,
`resumed`, `retired[]`, `context` — más `duration_s` añadido a mano (es una `@property` y
`asdict()` no la recoge) y `run` (marca de proceso, `YYYYmmdd-HHMMSS-<6 dígitos hex>`).

Dentro, el nombre de paso aparece en cuatro formas, y de un vistazo se ve cómo terminó ese paso:
`<步骤名>` (primer intento), `<步骤名>#retry<N>` (reintento normal), `<步骤名>#round<N>` (el
veredicto no pasó y se devuelve para seguir), `<步骤名>·判定#<N>` (la ronda del
[juez](../reference/glossary.md#判定者)).

La escritura es **append, no sobrescritura**: cada volcado relee el archivo y deduplica por el campo
`run` — las líneas de este proceso se reemplazan por las últimas, las de otros se dejan tal cual.
Por eso es seguro correr varios flower en paralelo sobre el mismo directorio.

### `continuous=True` cambia la semántica de `resume_from`

Esta es la más fácil de pasar por alto: `Workflow.continuous` es `True` por defecto, así que
`resume_from=None` **no equivale a «sesión nueva»**.

| Cómo se escribe | Dentro de la misma ejecución | Entre procesos (`continuous=True`) |
|---|---|---|
| `resume_from=None` (por defecto) | Sesión nueva, solo con el contexto que llega en el prompt | **Continúa la session del paso homónimo registrada en el linaje** |
| `resume_from="上一步名"` | Continúa la misma sesión, contexto completo | Igual que a la izquierda |
| `resume_from=…, fork=True` | Bifurca, sin contaminar la sesión original | Igual que a la izquierda |

Para que cada proceso arranque con una sesión nueva y limpia hay que escribir explícitamente
`Workflow(..., continuous=False)`.

Al cargar el linaje hay además una verificación: para cada `(nombre de paso, session_id)` que se lee
se comprueba con `runtime.has_session(sid)` que siga en `sessions.db`, y solo se usa si está vivo.
La razón es que el archivo de linaje puede sobrevivir a `sessions.db`, y hacer resume de una session
inexistente no revienta hasta que arranca el subproceso.

!!! warning "El nombre de paso es la clave estable entre procesos"
    El linaje se indexa por `Step.name`. **Cambiar el nombre de un paso equivale a cortar el
    linaje** — no da error, simplemente la siguiente ejecución arranca con una sesión nueva.
    Los nombres con sufijo (`#retry`, `#round`, `·判定#`) no entran en el linaje; `Lineage.remember`
    usa siempre el nombre original.

### Dos invariantes

**Uno: en cuanto se obtiene el session_id se escribe a disco, sin esperar a que el paso termine.**

Que maten el proceso a lo bruto es justo el escenario del que hay que protegerse. Ya nos costó una
vez: el 2026-09-07 Terminal.app se cayó dos veces, el kernel envió SIGHUP, y la acción por defecto
de SIGHUP es terminar directamente — el `finally` no ejecuta ni una línea. Entonces el linaje se
escribía en los **límites de paso**, así que la ejecución que murió dentro del primer paso tenía
`steps` vacío y hubo que volver a responder preguntas ya respondidas (ver issue #6).

Ahora `Runtime.on_session` vuelca a disco en el instante en que obtiene el id — en la práctica lo
más pronto es el primer mensaje assistant, porque el mensaje de sistema init no lleva `session_id`
en el SDK de Python. Al escribir se crea primero un `.tmp` y luego se reemplaza atómicamente, así
que si lo matan a medias no queda medio archivo; si el volcado falla (`OSError`), el error se traga
en silencio y no se lleva por delante la ejecución.

Este hook **solo cubre la llamada `runtime.run`**; antes del gate se desmonta con `try/finally`. El
juez usa el mismo `Runtime`, y si el hook siguiera puesto su session acabaría escrita en el linaje
del paso `干活`.

**Dos: si algo no cuadra, se hace como si no existiera; no se lanza error.**

Hay tres formas de que no cuadre: la ruta del espacio de trabajo cambió (el directorio se copió a
otro sitio — [HT001](../cases/ht001.md) se sacó justamente de un contenedor), la session ya no está
en la base (se borró `sessions.db`), o el archivo de linaje está corrupto. Cualquiera de ellas cae
en silencio a «empezar desde cero».

El campo `workspace` es el guardián: el `project_key` del SDK se deriva de la ruta del espacio de
trabajo (`/`, `_` y `.` se sustituyen por `-`), y tras copiar el directorio los session_id antiguos
simplemente no se encuentran en la nueva ubicación, así que si la ruta no cuadra se hace como si no
existiera.

**La continuidad es un extra; que falle no debe impedir que la gente trabaje.**

### Proceso matado y reinicio de la máquina

El resultado de ambas cosas es el mismo — reengancha — pero el camino es distinto:

| Caso | Qué pasa | Siguiente ejecución |
|---|---|---|
| `Ctrl-C` una vez | Interrupción cooperativa: corta limpio en un **límite de mensaje**. Puedes decir algo de paso y, dentro del mismo proceso, hacer resume de la misma sesión y seguir. La interrupción no cuenta como intento fallido ni consume cupo de reintentos | No afecta a la continuidad |
| `Ctrl-C` dos veces | Lanza `KeyboardInterrupt` y sale. El cierre solo llega a cerrar el almacén; **el paso en vuelo no entra en `manifest.json`** | El linaje ya estaba en disco hace rato: reengancha |
| `SIGTERM` / `SIGHUP` | El handler llama primero a `rescue()`, escribe también el paso en vuelo en `manifest.json` (marcado con `error="killed-by-signal"`) y luego restaura la acción por defecto y se va de verdad | Igual: reengancha |
| `SIGKILL`, corte de luz, reinicio de la máquina | No hay ningún cierre | Reengancha igualmente — los tres archivos están en disco y el linaje se escribió en el instante en que se obtuvo el id |

La única condición es una: **el mismo `workspace` y el mismo `run_dir`**. `run_dir` es relativo al
directorio de trabajo actual, así que lanzar `flower` desde otro directorio busca otro `runs/` y no
reengancha.

### El juez siempre es una sesión nueva

Esto está **garantizado por construcción**, no por acordarse.

El juez no es un `Step` — se despacha directamente con `rt.run()` dentro del gate de `with_goal`
(ver [Guardián de objetivos](goal.md)) y nunca pasa por la vía del linaje. Por eso, en cada ronda y
en cada despertar, es un par de ojos completamente nuevo.

Ahí está todo su valor: **no sabe cuántas veces lo intentó el ejecutor ni cuánto sufrió, así que
tampoco le va a buscar excusas.** Si lo dejas seguir la continuidad, el guardián de objetivos
degenera en una autoauditoría.

La sección 4 de `tests/lineage_offline.py` deja esto clavado.

### Lo que dices al despertar tiene que llegar a tres sitios

`flower "顺便支持代码块高亮"` en un directorio ya usado **no es una tarea nueva: es otra frase más en
la misma conversación**. Hace tres cosas a la vez — si falta una, falla en silencio:

| Dónde aterriza | Qué pasa si falta |
|---|---|
| Se añade a `需求.md` (`## 唤醒时追加`) | No sobrevive al límite de paso. El paso siguiente es una session nueva y solo lee las piezas congeladas |
| Se usa como prompt del paso `干活` | El coordinador no lo recibe nunca |
| **Dispara la rederivación de `目标.md`** | El juez sigue leyendo la lista vieja: **si lo recién añadido está hecho o no, ni siquiera entra en el veredicto** |

La tercera es la que más se escapa. El juez solo lee el `目标.md` congelado, y lo que añadiste a
mitad de camino no lo ve — sin rederivar, dictará «cumplido» según la lista vieja y la cosa que
querías no se habrá verificado en absoluto. El coste es una ejecución extra de `设定目标` por cada
añadido (medido en [HT002](../cases/ht002.md): $0.41 / 3 minutos).

**Despertar sin decir nada** (Enter directo) no añade ni rederiva, y no cuesta ni un céntimo más.

### También reengancha si revienta dentro del primer paso (`确认需求`)

`clarify_step` lleva un `resume_prompt` (la constante `CLARIFY_RESUME`): si revienta a mitad de la
clarificación y se vuelve a arrancar, al [clarificador](../reference/glossary.md#确认者) se le dice
«sigue con la clarificación de requisitos que quedó a medias — no empieces de nuevo», en lugar de
reenviar la petición original como si fuera una tarea nueva. Junto con la invariante de arriba
(«en cuanto llega el session_id se escribe a disco»), la ejecución que muere en el primer paso, con
`需求.md` aún sin congelar, ahora también reengancha y no hay que volver a responder nada.

A la inversa, los pasos previos ya congelados se **saltan enteros**: si `需求.md` tiene las cuatro
secciones completas se salta `确认需求` (pero el contenido igualmente se inyecta en ctx), y si
`目标.md` está completo se salta `设定目标`.

### Al reenganchar no se envía la misma frase

De esto se encarga `Step.resume_prompt`. En el contexto del otro lado **ya están** el brief, los
objetivos y por dónde iba la última vez; reenviar tal cual «haz esto según estos requisitos:
<brief entero>» es puro ruido, y peor aún: se lee como «los requisitos han cambiado, vuelve a
mirarlos».

Si no das `resume_prompt`, se reutiliza `prompt` — hay pasos que sí deben reenviar el texto completo
(cuando `设定目标` rederiva la lista, lo que necesita es exactamente ese brief completo).

### Al despertar, una línea de informe

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Sin ese informe, «¿se acuerda realmente de algo?» es completamente imperceptible, y eso es justo todo
el valor de esta capa. En el banner, `需求已确认` aparece siempre; `目标 N 条` solo si la lista de
veredicto no está vacía; `干活上下文 X` requiere poder consultar en `sessions.db` el tamaño de
contexto de la última ronda de esa sesión.

**Ese número de contexto se muestra a propósito** — la razón está en la sección «El coste» de abajo.

### Resiliencia: esperar colgado cuando se cae la red, y que los errores no entren en el contexto tras reenganchar

La [resiliencia](../reference/glossary.md#韧性) y la continuidad van juntas: en una ejecución de
varias horas la red se cae seguro alguna vez, y el comportamiento por defecto es malísimo — en el
instante de la desconexión, el harness mete en el transcript un **mensaje assistant sintético**
(`isApiErrorMessage=true`, `model="<synthetic>"`) cuyo cuerpo es "API Error: Can't reach the API
server …". Ese mensaje se convierte en la hoja de la sesión, y a partir de ahí el resume se lo
vuelve a dar de comer como «lo último que dijo el modelo», con lo que el modelo cree que está
hablando de una avería de red.

`Resilience` hace tres cosas:

**Uno: la sonda solo hace DNS + TCP.** `reachable(host, port, timeout=5.0)` únicamente ejecuta
`getaddrinfo` más un handshake TCP: **no envía HTTP, no lleva credenciales, no cuesta dinero**, y
cualquier excepción cuenta como inalcanzable. Qué dirección se sondea lo decide `endpoint()`, que
sigue a `ANTHROPIC_BASE_URL`, por defecto `https://api.anthropic.com`, con puerto `443` por defecto
(`80` para http). **Si usas una pasarela propia, tienes que sondear la pasarela** — que
`api.anthropic.com` responda no dice nada sobre la pasarela.

**Dos: distinguir lo que hay que esperar de lo que hay que abortar.** `classify(text)` devuelve
`"transient"` / `"fatal"` / `"unknown"`, y **evalúa fatal antes que transient** — los textos de
errores tipo 401 suelen llevar la palabra "connection", y con el orden invertido te quedas esperando
para siempre. Valores por defecto: `max_attempts=6` (incluido el primer intento), `base_delay=4.0`,
`max_delay=120.0`, `probe_timeout=5.0`, `probe_interval=15.0`, `max_offline_wait=3600.0` (1 hora),
`retry_unknown=True`. El backoff es `min(base_delay * 2**(attempt-1), max_delay)` multiplicado por un
jitter de ±25 %.

Si ya se obtuvo un session_id, se hace **resume y se continúa en lugar de empezar de nuevo**, así que
el gasto previo no se pierde. Al continuar se envía el `Resilience.resume_prompt`: «la ronda anterior
se interrumpió a mitad y no llegó a terminar. Mira lo que ya está volcado en el banco de trabajo y
sigue desde donde se cortó; no empieces otra vez desde el principio.» **Deliberadamente no contiene
ningún detalle del error** — el modelo necesita saber «te interrumpieron, sigue», no si fue un
ENOTFOUND o un 503.

**Tres: los errores generados por la tormenta de reintentos no entran en el contexto tras el resume.**
De eso se encarga la [poda](../reference/glossary.md#剪除). El almacén de sesiones de `Runtime` está
fijado a `PruningSessionStore`, que en `load()` hace tres cosas:

- Quita los mensajes sintéticos de error de API. **En SQLite se conservan tal cual**; simplemente no
  se vuelven a inyectar
- Quita las llamadas denegadas más antiguas y deja solo las `keep_denials=1` más recientes
- Sustituye los `tool_result` que quedaron colgando por una interrupción por una nota neutra
  «[la ronda anterior se interrumpió aquí; este resultado de herramienta no llegó a producirse]»;
  cambia solo el cuerpo, no elimina la entrada

Dejar 1 en vez de 0 tiene su razón: una llamada denegada nunca se ejecutó, su resultado no contiene
información y sin embargo ocupa lo suyo (medido una vez: 273 caracteres = 93 de mensaje de rechazo +
180 del **texto original del comando muerto**), y además **induce a error** — se comprobó que, tras
leer varios «no uses Bash directamente», el coordinador dejaba de intentar incluso un `git status`
permitido: indefensión aprendida. Pero mantener la más reciente sí sirve: evita que el modelo
reintente una y otra vez el mismo comando bloqueado dentro de la misma ronda.

La poda tiene una línea roja estructural: el transcript es una cadena simple por `parentUuid`, así
que al quitar una entrada hay que reenganchar sus hijos al ancestro vivo más cercano; si no, la
cadena se rompe ahí y se pierde todo el historial anterior.

En [HT001](../cases/ht001.md) esto se dio una vez de verdad: la caída de red va de 01:52:40 →
01:55:41, ese paso aparece en `manifest.json` con `attempts=2` / `resumed=True` / `ok=True`, y tras
continuar siguió corriendo más de 8 horas hasta terminar.

Un último punto que se malinterpreta fácil: **`Runtime(trim=False)` no significa «no se limpia
nada»**. `trim` ya es `False` por defecto, pero solo apaga la capa de **[recorte](../reference/glossary.md#裁剪)
de resultados grandes de herramientas**. Quitar los restos de la desconexión, quitar las llamadas
denegadas, neutralizar los restos de interrupción y marcar como caducados los resultados de
[comandos efímeros](../reference/glossary.md#一次性命令) — esas cuatro se siguen haciendo
(`ephemeral` es `True` por defecto, `keep_denials` es `1` por defecto).

### El coste: el contexto no para de crecer, y no tiene final

Este es el coste inherente de la continuidad, no un bug.

El paso `干活` de [HT001](../cases/ht001.md) corrió 10.44 horas seguidas; el contexto del
[hilo principal](../reference/glossary.md#主线程) fue de **28.7K** en la ronda 1, **35.2K** en la 20,
**108.6K** en la 35, **158.2K** en la 50 y **185.9K** en la 70: crecimiento monótono, con una
pendiente de unos **2.2K/ronda**; sin ningún compact en todo el trayecto, consumiendo el **18.6 %** de
la ventana de 1M. Extrapolando con esa pendiente, el muro está en unas **440 rondas** — el techo de
lo «largo horizonte» en su forma actual es unas **6 veces** aquella ejecución. Continuidad perpetua
significa que algún día se choca contra la ventana.

Hay dos mecanismos que lo gestionan:

1. **Recorte** (`flower --no-trim` lo apaga; por la ruta `flower` está activado por defecto) — al
   hacer resume, sustituye los resultados grandes y antiguos de herramientas por punteros a archivo:
   el contenido no se pierde, simplemente no reside en el contexto
2. **[Relevo](handoff.md)** — al llegar al umbral se escribe un documento de relevo y se cambia a una
   sesión nueva. **No es [compact](../reference/glossary.md#压缩)**: el documento se puede leer y
   editar, y ves qué se perdió. Gracias a eso el contexto baja periódicamente en vez de subir sin
   parar hasta el muro

**Por eso esa línea del despertar tiene que mostrar la cifra de contexto**: si la persona la ve,
tiene la oportunidad de decidir por sí misma empezar de cero antes de chocar.

Un apunte adicional: `--rounds` (el total de rondas de `干活`) **se reinicia en cada despertar**. Es
intencionado — un nuevo despertar es una nueva intención y no debe heredar las rondas gastadas la vez
anterior.

### Empezar otra cosa de cero

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

**Se archiva, no se borra.** `lineage.json`, `需求.md` y `目标.md` se **mueven** juntos a
`notes/archive/<YYYYmmdd-HHMMSS>/`, y a la vez se ponen a cero `steps` y `woke` del linaje. Los tres
son tres caras de un mismo trozo de historia; recoger solo una parte dejaría un estado a medias del
tipo «los objetivos siguen ahí pero la conversación ha desaparecido».

`sessions.db` no se toca — es el archivo histórico, y cada transcript de dentro sigue siendo
consultable.

En código, esto corresponde a `Lineage.archive(into, extra=[...])`.

## Cuándo no usarlo

- **Escenarios que exigen un punto de partida limpio cada vez.** Ejecutar el mismo workflow en lote,
  hacer evaluaciones comparativas, reproducirle un bug a otra persona — nada de eso debe arrastrar el
  contexto de la vez anterior. Escribe `Workflow(..., continuous=False)`, o usa un `run_dir` distinto
  cada vez.
- **Directorios que se mueven o se copian, o un `run_dir` no persistente.** Correr dentro de un
  contenedor con `runs/` en el sistema de archivos interno del contenedor, o hacer rsync del espacio
  de trabajo a otra máquina — la continuidad **falla en silencio** (el guardián de rutas rechaza el
  linaje que no cuadra). No lo tomes como una garantía.
- **Cuando esta vez es una intención nueva y el contexto ya es grande.** La continuidad carga a
  cuestas todo el historial irrelevante y pagas tokens por él en cada ronda. En lugar de aguantarlo,
  archiva y empieza de cero con `--new`.
- **Un agent único de usar y tirar.** `flower once` no pasa por `Workflow` y no tiene linaje; para
  continuar tienes que pasar tú mismo `--resume <session_id>`.
- **Usar la continuidad como copia de seguridad.** Solo registra «qué paso usó qué session». El
  código, los resultados y las decisiones deben aterrizar en el espacio de trabajo y en el
  [banco de trabajo](../reference/glossary.md#工作台); no cuentes con desenterrarlos del transcript.

## Relacionado

- [Relevo](handoff.md) — qué hacer cuando el contexto se llena dentro de una misma ejecución; son las
  dos direcciones de lo mismo que esta página
- [Guardián de objetivos](goal.md) — por qué el juez no reengancha
- [Economía del contexto](context.md) — de qué se ocupa cada uno: recorte, poda y volcado
- [API de Python](../reference/api.md) — `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Línea de comandos](../reference/cli.md) — `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Código fuente: [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
