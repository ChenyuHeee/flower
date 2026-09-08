# Glosario

Esta página es la base terminológica de la documentación de flower. Una misma cosa tiene un solo
nombre en todo el sitio, y la correspondencia chino-inglés queda fijada aquí; las versiones
traducidas siguen esta misma tabla.

Cada entrada da tres cosas: **qué designa el término**, **qué es en el código** y **qué no es**.
La tercera suele ser la más útil, porque la mayoría de los malentendidos vienen de tomar un
término por otro.

---

## Framework y ejecución {#框架与运行}

### Largo horizonte {#长程}

**long-horizon**

Una ejecución que abarca de horas a días, varias sesiones y reinicios de proceso, en lugar de una
pregunta y una respuesta. Todos los mecanismos de flower existen para que ese tipo de ejecución no
se desmorone a mitad de camino.

Referencia medida: [HT001](../cases/ht001.md) corrió 10.4 horas seguidas.

### Ejecución {#运行}

**run**

El proceso completo de un `Runtime`, de principio a fin. Dentro de una ejecución puede haber varios
[pasos](#步骤) y varias [sesiones](#会话), y puede interrumpirse y luego [continuar](#接续).
El registro de la ejecución queda en `runs/manifest.json` y `runs/sessions.db`.

**No es**: una llamada a la API, ni una sesión.

### Sesión {#会话}

**session**

Un contexto del lado del modelo. Tiene su propio `session_id`, se puede hacer resume y se puede
hacer fork. Una [ejecución](#运行) puede consumir varias sesiones: cada [relevo](#换代) abre una
nueva.

### Paso {#步骤}

**step** · `Step`

Una unidad ejecutable dentro de un [flujo de trabajo](#流程). Recibe un diccionario de contexto,
corre un agente y escribe el resultado de vuelta en el diccionario. `Step` es una clase; ver
[Python API](api.md#step).

### Flujo de trabajo {#流程}

**workflow** · `Workflow`

Un conjunto de [pasos](#步骤) encadenados en orden, más cómo se pasa el estado entre pasos y cuándo
salir antes de tiempo.

!!! note "El framework no trae flujos de trabajo hechos"
    flower solo aporta mecanismos. **El flujo de trabajo lo escribes tú.** Ver
    [Diseñar el flujo de trabajo](../guide/workflow.md).

---

## Roles {#角色}

Los roles son la división del trabajo que flower impone a los agentes. Cada rol = un texto de
reglas inyectado + un conjunto de herramientas + un conjunto de hooks. Los cinco roles son
funciones fábrica; ver [Python API](api.md#角色工厂).

### Coordinador {#协调者}

**coordinator** · `coordinator()`

El agente que vive en el [hilo principal](#主线程). Descompone la tarea, reparte trabajo, lee
informes y toma decisiones, **pero no toca nada**: no recibe `Bash` / `Write` / `Edit`. Sus
herramientas son solo `Agent`, `TodoWrite` y `Read`.

Su rol es «una persona que sabe usar Claude Code», no un ejecutor.

**No es**: un agente más inteligente. Usa por defecto el mismo nivel de modelo que el
[ejecutor](#执行者); lo que ahorra es contexto, no modelo.

### Ejecutor {#执行者}

**worker** · `worker()`

El [subagent](#subagent) que realmente trabaja: escribe código, corre tests, investiga. Sus
herramientas son `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`.

El texto de reglas restringe su respuesta a cuatro secciones —— **conclusión / evidencia /
entregables / sin verificar**, no más de 30 líneas, y prohíbe pegar contenido de archivos, salidas
de comandos, logs y diffs en bruto.

### Clarificador {#确认者}

**clarifier** · `clarify()`

El rol que aclara los requisitos antes de empezar a trabajar. No hace nada, solo pregunta, hasta
que todo esté claro (**sin límite de rondas**), y al final produce un
[acta de requisitos](#需求确认书). Ver [Clarificación previa](../guide/clarify.md).

### Juez {#判定者}

**judge** · `judge()`

El rol que dictamina «¿está terminado o no?». Hace una de dos cosas: antes de arrancar,
**fija el objetivo** (produce el objetivo + la lista de comprobación de aceptación); o al final de
cada ronda, **dictamina esa ronda** (produce un [veredicto](#判定)). Ver
[Guardián de objetivos](../guide/goal.md).

**Clave**: el juez dictamina sobre **los entregables**, no sobre el código fuente.

En [HT001](../cases/ht001.md) esto falló una vez: el criterio de aceptación decía «se ejecuta
directamente en una terminal de macOS», y al pasar `file` sobre el entregable salía
`ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`, pero el dictamen fue «superado».

Hay dos cosas que aclarar, o el ejemplo se lee mal:

1. **Lo que falló entonces no fue el guardián de objetivos**: HT001 aún no tenía ese mecanismo;
   quien se equivocó fue un auditor que el coordinador despachó por su cuenta.
2. **El juez con la configuración por defecto también se lo habría saltado con alta probabilidad.**
   `judge()` usa `can_run=False` por defecto y solo tiene `Read/Glob/Grep`: **no puede ejecutar
   `file`**, solo puede leer el `Makefile`, ver que efectivamente hay una rama Darwin y dictaminar
   que se cumplió.

Lo que sí funcionó fue [HT002](../cases/ht002.md): el juez tenía `judge_can_run` activado, corrió
`file` y `lsof` él mismo para mirar el terreno y evitó explícitamente esta trampa. **Así que la
frase "dictaminar sobre los entregables" solo se sostiene con `can_run=True`.**

### Oráculo {#旁路顾问}

**oracle** · `oracle()`

Un canal lateral de solo lectura. Con la ejecución todavía en marcha, puedes preguntarle «¿por
dónde va esto?»; mira los eventos recientes y el [banco de trabajo](#工作台) y responde.
**Lo que dice no entra en el contexto de esa ejecución**: preguntar no la afecta, y la respuesta se
descarta.

### subagent {#subagent}

Concepto del Claude Agent SDK: un agente hijo que el agente principal despacha mediante la
herramienta `Agent`. Tiene **su propia transcripción**, donde quedan sus llamadas a herramientas y
sus ensayos y errores; el hilo principal solo recibe el informe final.

Esta es la primera capa de ahorro de contexto de flower, y la que más ahorra. Ver
[Economía del contexto](../guide/context.md).

---

## Los cuatro mecanismos {#四个机制}

### Clarificación previa {#前置确认}

**clarify**

Aclarar los requisitos antes de empezar, congelarlos en un [acta de requisitos](#需求确认书) y solo
entonces ejecutar. Evita «lo construido no es lo que se quería». Ver
[Clarificación previa](../guide/clarify.md).

### Acta de requisitos {#需求确认书}

**brief** · `Brief`

El documento que produce el [clarificador](#确认者) al terminar de preguntar, con **exactamente
cuatro secciones**. Los pasos posteriores la leen y ya no vuelven a adivinar los requisitos.

**No la confundas** con el [encargo de tarea](#任务书). El acta de requisitos es «qué quiere la
persona»; el encargo de tarea es «qué hace este subagent esta vez».

### Encargo de tarea {#任务书}

**task brief**

El texto que el [coordinador](#协调者) escribe al [ejecutor](#执行者) cuando le reparte trabajo.
**Solo lo específico de esta tarea**: no repitas la disciplina que la otra parte ya conoce.

Medido: 8/8 encargos de tarea repetían disciplina que el destinatario ya conocía; en el más corto,
de 521 caracteres, solo unos 120 caracteres eran específicos de la tarea, y una ronda desperdiciaba
unos 4.8k de contexto permanente.

### Guardián de objetivos {#目标看守}

**goal guard**

El [juez](#判定者) dictamina de forma independiente, al final de cada ronda, si el objetivo se
alcanzó; si no, lo devuelve para seguir trabajando. Evita «dice que terminó pero en realidad no».
Ver [Guardián de objetivos](../guide/goal.md).

### Veredicto {#判定}

**verdict** · `Verdict`

El resultado de una ronda de dictamen del [juez](#判定者), con **exactamente tres secciones**:
conclusión / motivo / no superado.

Hay tres conclusiones posibles: `ACHIEVED` (alcanzado), `NOT_YET` (todavía no) y `UNREACHABLE`
(este entorno no permite verificarlo). **Las dos últimas son conclusiones distintas**: «aquí no se
puede verificar» nunca se dictamina como superado.

### Continuidad {#接续}

**continuity**

Volver a ejecutar en el mismo directorio retoma automáticamente el progreso de la vez anterior,
igual si el proceso fue matado o la máquina se reinició. Evita «se cayó tras horas de ejecución y
hay que empezar de cero». Ver [Continuidad](../guide/continuity.md).

**No la confundas** con el [relevo](#换代): la continuidad retoma **entre procesos** la ejecución
anterior; el relevo cambia a una sesión nueva **dentro de la misma ejecución**.

### Relevo {#换代}

**handoff**

Cuando el contexto está a punto de llenarse, la sesión actual escribe un
[documento de relevo](#交接书) que una persona puede leer y modificar, y luego una sesión nueva toma
el testigo. Evita «se llenó el contexto y quedó comprimido en un resumen». Ver
[Relevo](../guide/handoff.md).

**No es** compact. Ver [compact](#压缩).

### Documento de relevo {#交接书}

**handoff document** · `Handoff`

El documento que se escribe al hacer el relevo, con cinco secciones: `doing` (qué se está
haciendo), `decided` (qué se decidió), `deadends` (caminos sin salida), `next` (siguiente paso) y
`scene` (estado del terreno).

**Solo `doing` y `next` son obligatorias**: exigir por norma que «caminos sin salida» no esté vacío
obliga al modelo a inventar.

### compact {#压缩}

**compact**

El mecanismo nativo de Claude Code: cuando el contexto se llena, resume la conversación previa en
un párrafo.

flower **no lo usa**; usa el [relevo](#换代) en su lugar. La diferencia: el resumen lo genera el
modelo, no es legible ni editable y no sabes qué se perdió; el documento de relevo es estructurado,
está en disco, y puedes abrirlo, cambiar una línea y dejar que siga.

---

## Gestión del contexto {#上下文管理}

### Hilo principal {#主线程}

**main thread**

El contexto de sesión donde vive el [coordinador](#协调者). Es el único contexto que atraviesa toda
la ejecución, así que es donde más hay que ahorrar.

En el código, el hilo principal se detecta así: los datos del hook **no tienen** `agent_id`. Los
hooks de un subagent sí llevan `agent_id`.

### Banco de trabajo {#工作台}

**workbench** · `Workbench`

Un directorio de trabajo en disco, con tres subdirectorios:

| Directorio | Qué contiene |
|---|---|
| `scripts/` | Scripts que se van a ejecutar más de una vez; la primera línea lleva `# desc: una frase` |
| `artifacts/` | Salidas largas, de más de 2000 caracteres |
| `notes/` | Decisiones clave, un archivo por decisión |

`INDEX.md` es el índice de estos tres directorios y se **inyecta en el system prompt**, de modo que
el agente sabe en cada ronda qué tiene a mano.

!!! warning "Dos entradas, dos ubicaciones por defecto"
    Dónde queda el banco de trabajo depende de cómo lo crees, y es fácil tropezar aquí:

    | Forma de creación | Raíz del banco de trabajo |
    |---|---|
    | `Workbench(workspace)` —— también es la ruta que siguen `starter_flow()` / `wake_state()` | `<espacio-de-trabajo>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench` (por defecto `runs/workbench`) |

    La línea de comandos usa la primera, así que `flower` produce `.flower/`; pero desde Python,
    `Runtime(workbench=True)` directamente da `runs/workbench`. Si quieres fijar la ubicación, pasa
    una instancia de `Workbench` ya construida y no dependas del valor por defecto.

!!! warning "Los subagents no heredan el índice"
    El índice va por `system_prompt.append` a nivel de sesión, y **los subagents no lo reciben**.
    Por eso la regla «las salidas largas van a `artifacts/`» tiene que transmitirla el
    [coordinador](#协调者) dentro del [encargo de tarea](#任务书): ese es el único canal.

### Volcado {#落盘}

**spill**

Cuando el resultado de una herramienta supera el umbral (4000 caracteres por defecto), el hook
`PostToolUse` lo escribe en `<raíz-del-banco-de-trabajo>/spill/` y en el contexto solo queda una
línea con la ruta.

La ruta **sigue al [banco de trabajo](#工作台)**, no está fijada: solo cuando el banco de trabajo
está en su ubicación por defecto `<espacio-de-trabajo>/.flower` resulta ser exactamente
`.flower/spill/`. Con [aislamiento](#隔离) activo, o si `home=` apunta el banco de trabajo fuera del
repositorio, el spill se mueve con él.

**Se recorta en el momento**, no se espera a que el contexto se llene para volver atrás y aplicar
[compact](#压缩).

### Comando efímero {#一次性命令}

**ephemeral command**

Un comando cuyo resultado caduca y no vale la pena conservar: `ls`, `git status`, `ps` y
similares. Sus resultados no entran en el registro persistente de la sesión. La decisión de «¿se
deja que el hilo principal lo ejecute para echar un vistazo?» y la de «¿se recorta el resultado?»
usan la misma función, así que ambos conjuntos son siempre iguales.

### Recorte {#裁剪}

**trim** · `TrimmingSessionStore`

**Antes del resume**, reescribe el conjunto de mensajes que se le devuelve al modelo (resultados de
[comandos efímeros](#一次性命令), salidas de herramientas demasiado largas).

Solo sobrescribe `load()`: **el texto original en SQLite nunca se toca**; lo recortado es
únicamente la copia que este resume mete en el contexto. Por eso el recorte es reversible: cambia
la política, vuelve a hacer resume y recuperas el registro completo.

### Poda {#剪除}

**prune** · `PruningSessionStore`

Mantiene los **mensajes de error** fuera del contexto. El montón de errores generado durante los
reintentos de una caída de red no debería ocupar contexto tras el resume.

**No la confundas** con el [recorte](#裁剪): el recorte descarta por volumen y por valor; la poda
descarta según «¿es un error o no?».

---

## Runtime {#运行时}

### Aislamiento {#隔离}

**isolation**

Los roles marcados se asignan automáticamente a un git worktree propio, impuesto por hooks y no por
el prompt. Así no se pisan al modificar el mismo repositorio en paralelo.

!!! warning "Si activas el aislamiento, saca el banco de trabajo del repositorio"
    Con el aislamiento por worktree activo, el [banco de trabajo](#工作台) debe apuntarse con
    `home=` fuera del repositorio; si no, el agente aislado no puede escribir en el checkout
    compartido.

### Resiliencia {#韧性}

**resilience** · `Resilience`

Cuando se cae la red, espera colgado en lugar de fallar y salir: sondas de DNS + TCP vigilan y, al
volver la red, hace resume y continúa. Los mensajes de error generados durante la espera los
mantiene fuera del contexto la [poda](#剪除).

### Linaje {#血缘}

**lineage** · `Lineage`

Registra entre procesos «de qué sesión se bifurcó esta ejecución», y queda en `lineage.json`. La
[continuidad](#接续) se apoya en él para encontrar hasta dónde llegó la vez anterior.

**No lo confundas** con el [manifiesto de ejecuciones](#运行清单): ese es `runs/manifest.json` y
registra las cuentas de cada ejecución.

### Manifiesto de ejecuciones {#运行清单}

**run manifest** · `runs/manifest.json`

Las cuentas de cada [ejecución](#运行): cuánto costó, cuánto duró, qué tamaño de contexto alcanzó.
Todas las cifras de las páginas de casos se pueden recalcular aquí.

### Despertar {#唤醒}

**wake** · `wake_state()`

Un sondeo **de solo lectura** antes de arrancar: mira si este espacio de trabajo ya tiene
[acta de requisitos](#需求确认书) y objetivo, y con eso decide si esta vez se empieza de cero o se
[continúa](#接续). **No escribe ni un byte.**

`wake_state()` es el único lugar donde se define la ubicación del banco de trabajo: si el programa
que lo invoca quiere saber dónde está el acta, también tiene que pasar por él. Si te armas la ruta
a mano y la equivocas, no habrá error: simplemente fallará en silencio.

### Evento {#事件}

**event** · `Event`

El flujo de mensajes del SDK aplanado en una estructura estable. **La [capa de
interacción](#交互层) solo conoce `Event` y no importa ningún tipo del SDK**: esa es la frontera que
permite cambiar de UI sin tocar el núcleo.

### Capa de interacción {#交互层}

**interaction layer**

La capa de UI entre la persona y la ejecución. Por defecto es la terminal; puede cambiarse por web,
TUI, HTTP, o por operación totalmente automática sin supervisión. Ver
[Cambiar la capa de interacción](../guide/interaction.md).

### Almacén de sesiones {#会话存储}

**session store** · `SessionStore`

El backend de persistencia de los mensajes de sesión. Por defecto, `SqliteSessionStore` escribe en
`runs/sessions.db`, y se le pueden envolver las dos capas de [recorte](#裁剪) y [poda](#剪除).

### Presupuesto {#预算}

**budget** · `max_budget_usd`

El tope de gasto de una ejecución; al superarlo, se detiene. Sin esto, una ejecución de largo
horizonte sale cara: [HT001](../cases/ht001.md) costó $171.62.

---

## Portabilidad {#可移植性}

### Portátil {#可移植}

**portable**

Cambias de máquina y el comportamiento es el mismo. Se consigue con `setting_sources=[]`: no lee el
`~/.claude/` de la máquina anfitriona ni el `.claude/` del proyecto. Las capacidades de dominio
viajan con el repositorio vía [plugin](#plugin), y las credenciales las trae el propio `.env`.

El precio: **las credenciales hay que traerlas**, no se hereda automáticamente la configuración de
la máquina anfitriona.

### Append {#叠加}

**append**

Las instrucciones de dominio se añaden **después** del system prompt nativo de Claude Code, en
lugar de sustituirlo:

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Así la especialización no se paga con pérdida de capacidad general.

### plugin {#plugin}

Un paquete de capacidades de dominio que viaja con el repositorio. Se carga con `plugins=[local]` y
su directorio puede contener `skills/`, `agents/`, `hooks/` y `.mcp.json`. Ver
[Despliegue](deploy.md#plugin).
