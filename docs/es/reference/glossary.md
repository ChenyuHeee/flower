# Glosario

Esta página es la base terminológica de la documentación de flower. Una misma cosa tiene un único nombre en todo el sitio; la correspondencia chino-inglés queda fijada aquí, y las versiones traducidas siguen esta misma tabla.

Cada entrada da tres cosas: **qué designa el término**, **qué es en el código** y **qué no es**. La tercera suele ser la más útil, porque la mayoría de los malentendidos vienen de confundir un término con otro.

---

## Framework y ejecución {#框架与运行}

### Long-horizon {#长程}

**long-horizon**

Una ejecución que abarca de horas a días, varias sesiones y reinicios de proceso, en lugar de una pregunta y una respuesta. Todos los mecanismos de flower existen para que ese tipo de ejecución no se desarme a mitad de camino.

Referencia medida: [HT001](../cases/ht001.md) corrió 10.4 horas seguidas.

### Ejecución {#运行}

**run**

El proceso completo de un `Runtime`, de principio a fin. Dentro de una ejecución puede haber varios [pasos](#步骤) y varias [sesiones](#会话), y puede interrumpirse y luego [continuar](#接续). El registro de la ejecución queda en `runs/manifest.json` y `runs/sessions.db`.

**No es**: una llamada a la API, ni una sesión.

### Sesión {#会话}

**session**

Un contexto del lado del modelo. Tiene su propio `session_id`, se puede hacer resume y se puede hacer fork. Una [ejecución](#运行) puede quemar varias sesiones: cada [relevo](#换代) abre una nueva.

### Paso {#步骤}

**step** · `Step`

Una unidad ejecutable dentro de un [flujo de trabajo](#流程). Recibe un diccionario de contexto, corre un agent y escribe el resultado de vuelta en el diccionario. `Step` es una clase; ver [Python API](api.md#step).

### Flujo de trabajo {#流程}

**workflow** · `Workflow`

Un conjunto de [pasos](#步骤) encadenados en orden, más cómo se pasa el estado entre pasos y cuándo se sale antes de tiempo.

!!! note "El framework no trae flujos hechos"
    flower solo aporta mecanismos. **El flujo lo escribes tú**. Ver [Diseñar el flujo](../guide/workflow.md).

---

## Roles {#角色}

Los roles son el reparto de trabajo que flower hace entre agents. Cada rol = un texto de reglas inyectado + un conjunto de herramientas + un conjunto de hooks. Los cinco roles son funciones fábrica; ver [Python API](api.md#角色工厂).

### Coordinador {#协调者}

**coordinator** · `coordinator()`

El agent que vive en el [hilo principal](#主线程). Descompone la tarea, reparte trabajo, lee informes y decide, **pero no toca nada**: no tiene `Write` / `Edit`. Las herramientas base son `Agent`, `TodoWrite`, `Read` (`roles.py:27`), pero esa no es la lista final: según los parámetros se le suman tres cosas más. `glance=True` (por defecto) añade un `Bash` restringido (solo alcanza para comandos de un vistazo, tipo `git status` / `ls`, controlado por `delegate_guard`); si se le da un canal de preguntas, se añaden `inbox` y `ask`; y si los [ejecutores](#执行者) a su cargo llevan `WebFetch` / `WebSearch`, esos dos también se fusionan hacia arriba, porque `allowed_tools` es **a nivel de sesión**: si no se fusionan, el subagent se queda colgado en una aprobación de permisos que nadie responde cuando los invoca (`roles.py:513-526`).

El rol está definido como «alguien que sabe usar Claude Code», no como un ejecutor.

**No es**: un agent más inteligente. Él y el [ejecutor](#执行者) usan por defecto la misma gama de modelo; lo que se ahorra es contexto, no modelo.

### Ejecutor {#执行者}

**worker** · `worker()`

El [subagent](#subagent) que realmente trabaja: escribe código, corre pruebas, busca información. Sus herramientas son `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`.

El formato de respuesta está restringido por el texto de reglas a cuatro secciones —— **conclusión / evidencia / entregables / no verificado**, no más de 30 líneas, prohibido pegar contenido de archivos, salida de comandos, logs o diffs en bruto.

### Clarificador {#确认者}

**clarifier** · `clarify()`

El rol que aclara el requisito antes de tocar nada. No hace, solo pregunta, hasta que quede claro (**sin límite de rondas**), y al final produce un [acta de requisitos](#需求确认书). Ver [Clarificación previa](../guide/clarify.md).

### Juez {#判定者}

**judge** · `judge()`

El rol que juzga si «está terminado». Hace una de dos cosas: antes de arrancar **fija el objetivo** (produce el objetivo + la lista de comprobación), o al final de cada ronda **juzga esa ronda** (produce un [veredicto](#判定)). Ver [Guardián del objetivo](../guide/goal.md).

**Clave**: el juez juzga el **artefacto producido**, no el código fuente.

En [HT001](../cases/ht001.md) esto falló una vez: el criterio de aceptación decía «ejecutarse directamente en la terminal de macOS»; al pasarle `file` al artefacto entregado salía `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`, y aun así el veredicto fue aprobado.

Dos cosas hay que dejar claras, o el ejemplo se malinterpreta:

1. **Lo que falló ahí no fue el guardián del objetivo** —— HT001 todavía no tenía ese mecanismo; quien juzgó mal fue un auditor que el coordinador despachó por iniciativa propia.
2. **El juez con la configuración por defecto probablemente también lo habría dejado pasar.** `judge()` trae `can_run=False` por defecto y solo tiene `Read/Glob/Grep` —— **no puede ejecutar `file`**; se limitaría a leer el `Makefile`, ver que efectivamente hay una rama Darwin y dar por cumplido el objetivo.

Lo que sí funciona es [HT002](../cases/ht002.md): allí el juez tenía `judge_can_run` activado, corrió `file` y `lsof` por su cuenta para mirar el terreno, y evitó explícitamente esa trampa. **Así que la frase «juzgar el artefacto» solo se sostiene con `can_run=True`.**

### Oráculo {#旁路顾问}

**oracle** · `oracle()`

Una vía lateral de solo lectura. Con la ejecución todavía en marcha puedes preguntarle «¿por dónde va esto?»; mira los eventos recientes y el [banco de trabajo](#工作台) y responde. **Lo que dice no entra en el contexto de esa ejecución**: preguntar no la afecta, y la respuesta se descarta.

### subagent {#subagent}

Concepto del Claude Agent SDK: un agent hijo que el agent principal despacha con la herramienta `Agent`. Tiene **su propia transcript**, donde quedan sus llamadas a herramientas y sus errores; el hilo principal solo recibe el informe final.

Esta es la primera capa de ahorro de contexto de flower, y la que más ahorra. Ver [Economía del contexto](../guide/context.md).

---

## Los cuatro mecanismos {#四个机制}

### Clarificación previa {#前置确认}

**clarify**

Aclarar el requisito antes de tocar nada, congelarlo en un [acta de requisitos](#需求确认书) y recién entonces empezar a ejecutar. Bloquea el «se construyó algo que no era lo que se quería». Ver [Clarificación previa](../guide/clarify.md).

### Acta de requisitos {#需求确认书}

**brief** · `Brief`

El documento que produce el [clarificador](#确认者) al terminar de preguntar, **exactamente cuatro secciones**. Los pasos siguientes lo leen y ya no vuelven a adivinar el requisito.

**No lo confundas** con el [encargo de tarea](#任务书). El acta de requisitos es «qué quiere la persona»; el encargo de tarea es «qué hace este subagent esta vez».

### Encargo de tarea {#任务书}

**task brief**

El texto que el [coordinador](#协调者) le escribe al [ejecutor](#执行者) al repartirle trabajo. **Solo lo específico de esta tarea**: no repitas disciplinas que el otro ya conoce.

Medido: 8/8 encargos de tarea repetían disciplinas que el destinatario ya conocía; en el más corto, de 521 caracteres, solo unos 120 caracteres eran específicos de la tarea, lo que desperdicia unos 4.8k de contexto permanente por ronda.

### Guardián del objetivo {#目标看守}

**goal guard**

El [juez](#判定者) determina de forma independiente, al final de cada ronda, si el objetivo se cumplió; si no, lo devuelve para seguir trabajando. Bloquea el «dice que terminó y en realidad no». Ver [Guardián del objetivo](../guide/goal.md).

### Veredicto {#判定}

**verdict** · `Verdict`

El resultado de una ronda de juicio del [juez](#判定者), **exactamente tres secciones**: conclusión / razones / no superado.

Hay tres conclusiones posibles: `ACHIEVED` (cumplido), `NOT_YET` (todavía no), `UNREACHABLE` (en este entorno no se puede verificar). **Las dos últimas son conclusiones distintas**: «aquí no se puede verificar» nunca se juzga como aprobado.

### Continuidad {#接续}

**continuity**

Volver a correr en el mismo directorio y retomar automáticamente el progreso anterior, incluso si el proceso fue matado o la máquina reiniciada. Bloquea el «corrió horas, se cayó y hay que empezar de cero». Ver [Continuidad](../guide/continuity.md).

**No lo confundas** con el [relevo](#换代): la continuidad retoma la ejecución anterior **entre procesos**; el relevo cambia a una sesión nueva **dentro de la misma ejecución**.

### Relevo {#换代}

**handoff**

Cuando el contexto está por llenarse, la sesión actual escribe un [documento de relevo](#交接书) que una persona puede leer y modificar, y luego una sesión nueva toma el testigo. Bloquea el «se llenó el contexto y todo quedó aplastado en un resumen». Ver [Relevo](../guide/handoff.md).

**No es** compact. Ver [compact](#压缩).

### Documento de relevo {#交接书}

**handoff document** · `Handoff`

El documento que se escribe en el relevo, con cinco secciones: `doing` (qué se está haciendo), `decided` (qué se decidió), `deadends` (caminos que no llevan a nada), `next` (siguiente paso), `scene` (el terreno).

**Solo `doing` y `next` son obligatorios**: exigir que «caminos que no llevan a nada» no esté vacío obliga al modelo a inventar.

### compact {#压缩}

**compact**

El mecanismo nativo de Claude Code: cuando el contexto se llena, resume la conversación anterior en un párrafo.

flower **no lo usa**; lo reemplaza por el [relevo](#换代). La diferencia: el resumen lo genera el modelo, no es legible ni editable, y no sabes qué se perdió; el documento de relevo es estructurado, está en disco, y puedes abrirlo, cambiar una línea y dejar que siga.

---

## Gestión del contexto {#上下文管理}

### Hilo principal {#主线程}

**main thread**

El contexto de sesión donde vive el [coordinador](#协调者). Es el único contexto que atraviesa toda la ejecución, así que es el que más hay que economizar.

Cómo se detecta el hilo principal en el código: los datos del hook **no tienen** `agent_id`. Los hooks de un subagent sí llevan `agent_id`.

### Banco de trabajo {#工作台}

**workbench** · `Workbench`

El directorio de trabajo en disco, con tres subdirectorios:

| Directorio | Qué va ahí |
|---|---|
| `scripts/` | Scripts que se van a ejecutar una segunda vez; primera línea `# desc: una frase` |
| `artifacts/` | Salidas largas, de más de 2000 caracteres |
| `notes/` | Decisiones clave, un archivo por decisión |

`INDEX.md` es el índice de esos tres directorios y se **inyecta en el system prompt**, así que el agent sabe en cada ronda qué tiene a mano.

!!! warning "Dos puntos de entrada, dos ubicaciones por defecto"
    Dónde queda el banco de trabajo depende de cómo se crea, y aquí es fácil tropezar:

    | Forma de crearlo | Raíz del banco de trabajo |
    |---|---|
    | `Workbench(workspace)` —— también el camino de `starter_flow()` / `wake_state()` | `<espacio-de-trabajo>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench` (por defecto `runs/workbench`) |

    La línea de comandos usa el primero, así que `flower` produce `.flower/`; pero llamar directamente a `Runtime(workbench=True)` desde Python te da `runs/workbench`. Si quieres fijar la ubicación, pasa una instancia de `Workbench` ya construida y no dependas del valor por defecto.

!!! warning "El índice no lo heredan los subagents"
    El índice va por `system_prompt.append` a nivel de sesión, y **el subagent no lo recibe**. Por eso la regla «las salidas largas van a `artifacts/`» tiene que retransmitirla el [coordinador](#协调者) dentro del [encargo de tarea](#任务书): ese es el único canal.

### Volcado {#落盘}

**spill**

Cuando el resultado de una herramienta supera el umbral (4000 caracteres por defecto), el hook `PostToolUse` lo escribe en `<raíz-del-banco-de-trabajo>/spill/` y en el contexto solo queda una línea con la ruta.

La ruta **sigue al [banco de trabajo](#工作台)**, no está fijada: solo cuando el banco de trabajo está en su ubicación por defecto `<espacio-de-trabajo>/.flower` resulta ser exactamente `.flower/spill/`. Si activas el [aislamiento](#隔离) y apuntas el banco de trabajo fuera del repositorio con `home=`, el spill se muda con él.

**Se recorta en el momento**, no se espera a que el contexto se llene para volver atrás y hacer [compact](#压缩).

### Comando efímero {#一次性命令}

**ephemeral command**

Comandos cuyo resultado caduca y no vale la pena conservar: `ls`, `git status`, `ps` y similares. Sus resultados no entran en el registro persistente de la sesión. Decidir «si se deja que el hilo principal eche un vistazo» y «si el resultado se recorta» usa la misma función, así que ambos conjuntos son siempre iguales.

### Recorte {#裁剪}

**trim** · `TrimmingSessionStore`

**Antes del resume**, reescribe la copia de los mensajes que se le devuelve al modelo (resultados de [comandos efímeros](#一次性命令), salidas de herramientas demasiado largas).

Solo sobreescribe `load()`: **el texto original en SQLite no se toca nunca**; lo recortado es únicamente la copia que entra al contexto en ese resume. Por eso el recorte es reversible: cambias de estrategia, haces resume otra vez y vuelves a tener el registro completo.

### Poda {#剪除}

**prune** · `PruningSessionStore`

Deja los **mensajes de error** fuera del contexto. La pila de errores generada durante los reintentos por caída de red no debería ocupar el contexto después del resume.

**No la confundas** con el [recorte](#裁剪): el recorte descarta por volumen y valor, la poda descarta por «es un error o no».

---

## Runtime {#运行时}

### Aislamiento {#隔离}

**isolation**

Los roles marcados van automáticamente a un git worktree independiente, forzado por hooks y no por el prompt. Así no chocan al modificar el mismo repositorio en paralelo.

!!! warning "Si activas el aislamiento, saca el banco de trabajo del repositorio"
    Con el aislamiento por worktree activado, el [banco de trabajo](#工作台) debe apuntar fuera del repositorio con `home=`; si no, el agent aislado no puede escribir en el checkout compartido.

### Resiliencia {#韧性}

**resilience** · `Resilience`

Cuando se cae la red, espera colgado en vez de fallar y salir: sondas de DNS + TCP vigilan, y al recuperarse la red se hace resume y sigue. Los mensajes de error generados durante la espera los deja fuera del contexto la [poda](#剪除).

### Linaje {#血缘}

**lineage** · `Lineage`

Registra entre procesos «de qué sesión hizo fork esta ejecución», y queda en `lineage.json`. La [continuidad](#接续) se apoya en él para encontrar dónde se quedó la vez anterior.

**No lo confundas** con el [manifiesto de ejecución](#运行清单): ese es `runs/manifest.json` y lleva la contabilidad de cada ejecución.

### Manifiesto de ejecución {#运行清单}

**run manifest** · `runs/manifest.json`

El registro contable de cada [ejecución](#运行): cuánto costó, cuánto duró, qué tan grande fue el contexto. Todos los números de las páginas de casos se pueden recalcular desde aquí.

### Despertar {#唤醒}

**wake** · `wake_state()`

Una **sonda de solo lectura** antes de arrancar: mira si este espacio de trabajo ya tiene un [acta de requisitos](#需求确认书) y un objetivo, y con eso decide si esta vez se empieza de cero o se [continúa](#接续). **No escribe ni un byte.**

`wake_state()` es el único lugar donde se define la ubicación del banco de trabajo: si tu programa quiere saber dónde está el acta, también tiene que pasar por ahí. Si armas la ruta a mano y te equivocas, no habrá error: fallará en silencio.

### Evento {#事件}

**event** · `Event`

La estructura estable a la que se aplana el flujo de mensajes del SDK. **La [capa de interacción](#交互层) solo conoce `Event` y no importa ningún tipo del SDK**: esa es la frontera que permite cambiar de UI sin tocar el núcleo.

### Capa de interacción {#交互层}

**interaction layer**

La capa de UI entre la persona y la ejecución. Por defecto es la terminal; puede cambiarse por web, TUI, HTTP, o modo totalmente automático sin supervisión. Ver [Cambiar la capa de interacción](../guide/interaction.md).

### Almacén de sesiones {#会话存储}

**session store** · `SessionStore`

El backend de persistencia de los mensajes de sesión. Por defecto `SqliteSessionStore` escribe en `runs/sessions.db`, y se le pueden poner encima las dos envolturas de [recorte](#裁剪) y [poda](#剪除).

### Presupuesto {#预算}

**budget** · `max_budget_usd`

El tope de gasto de una ejecución; al superarlo, para. Una ejecución long-horizon sin esto sale cara: [HT001](../cases/ht001.md) costó $171.62.

---

## Portabilidad {#可移植性}

### Portable {#可移植}

**portable**

Cambias de máquina y el comportamiento es el mismo. La forma es `setting_sources=[]`: no se lee el `~/.claude/` de la máquina anfitriona ni el `.claude/` del proyecto. Las capacidades de dominio viajan con el repositorio vía [plugin](#plugin), y las credenciales van en el `.env`.

El precio: **las credenciales hay que traerlas**, no se heredan automáticamente de la configuración del anfitrión.

### Añadido {#叠加}

**append**

Las instrucciones de dominio se añaden **después** del system prompt nativo de Claude Code, en vez de reemplazarlo:

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Así la especialización no cuesta capacidad general.

### plugin {#plugin}

Un paquete de capacidades de dominio que viaja con el repositorio. Se carga con `plugins=[local]`, y en su directorio puede haber `skills/`, `agents/`, `hooks/`, `.mcp.json`. Ver [Despliegue](deploy.md#plugin).
