# Economía del contexto

El contexto del [hilo principal](../reference/glossary.md#主线程) es lo único que atraviesa de principio a fin una ejecución [de largo horizonte](../reference/glossary.md#长程): lo que mete y lo que no mete decide hasta dónde llega esa ejecución. La forma de flower —el [coordinador](../reference/glossary.md#协调者) no toca nada, las salidas largas van a disco, los hooks podan en el acto— sale entera de ahí. Esta página explica por qué.

## Qué problema resuelve {#解决什么问题}

La [compactación](../reference/glossary.md#压缩) espera a que el contexto se llene para resumir hacia atrás: trata el síntoma. El problema real es: **lo trivial no debería haber entrado nunca al hilo principal.**

La diferencia está en el momento. La salida de un `pytest` son fácilmente decenas de miles de caracteres; el modelo la mira una vez, saca una conclusión, y el resto de los caracteres se reenvían íntegros en cada turno a partir de ahí; cuando la ventana se llena, la compactación los resume junto con las decisiones que había al lado en un solo párrafo —lo que se ahorra es volumen, lo que se pierde es «por qué se decidió así». El umbral de disparo del auto-compact es **ventana − 33k** ([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)); llegado ese momento, lo que había que tirar y lo que no ya están tumbados juntos.

flower lo resuelve en cuatro capas, y el orden es la prioridad —ordenadas por cuánto ahorran:

| Capa | Qué hace | Dónde |
|---|---|---|
| 1. Reparto | El trabajo manual se delega a un [subagent](../reference/glossary.md#subagent); el ensayo y error va a su propio transcript | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. Banco de trabajo | Scripts / salidas largas / decisiones van a disco; el índice se inyecta en el system prompt | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. Volcado en el acto | El hook `PostToolUse` vuelca a disco los resultados de herramienta que superan el umbral; en el contexto solo queda una línea con la ruta | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. Recorte y poda | Reescribe la sesión antes del resume: resultados caducados, llamadas denegadas y restos de desconexión ya no se vuelven a alimentar | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

Las dos primeras controlan **si las cosas entran**; las dos últimas, **si lo que ya entró se queda**. El orden no se puede invertir: por dura que sea la cuarta capa, no recupera el volumen que dejó pasar la primera.

## Cómo se usa (código mínimo) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model por defecto "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

Estas pocas líneas montan las tres primeras capas: `coordinator()` fija siempre `delegate_only=True` (capa uno); `workbench=True` crea el [banco de trabajo](../reference/glossary.md#工作台) e inyecta el índice en el system prompt del coordinador (capa dos), y además hace que `Runtime` monte `spill_guard` (capa tres). La cuarta capa está activa por defecto: el [almacén de sesiones](../reference/glossary.md#会话存储) de `Runtime` está fijado a `PruningSessionStore`, y los parámetros del constructor no ofrecen ninguna vía para cambiarlo.

!!! warning "`workbench=True` no es opcional"
    El `delegate_guard`, que impide que el coordinador toque nada, cuelga de `workbench_hooks`, y `workbench_hooks` solo se monta cuando `Runtime` tiene banco de trabajo; y `whitelist_guard` se salta por culpa de `delegate_only=True`.
    Conclusión: **con `Runtime(workbench=False)` y `coordinator()`, Bash / Write / Edit del hilo principal no tienen ni un muro delante.**

## Qué hace en realidad {#它实际做了什么}

### Capa uno: reparto (la que más ahorra) {#第一层分工省得最多}

El coordinador hace de «persona que sabe usar Claude Code»: descompone, reparte, lee informes, decide. No tiene acceso a Bash / Write / Edit —sus herramientas son solo `Agent`, `TodoWrite` y `Read` (con `glance=True` se añade un `Bash` restringido, ver más abajo). Todo el trabajo manual se delega a los [ejecutores](../reference/glossary.md#执行者).

**Cuándo se dispara**: cada vez que el hilo principal llama a `Bash|Write|Edit|NotebookEdit`, el hook `PreToolUse` `delegate_guard` deniega en el acto y señala el camino: «usa la herramienta Agent para lanzar un subagent, escribe en la tarea el objetivo y los criterios de aceptación, y pídele que escriba las salidas largas en `.flower/artifacts/` y que en la respuesta solo dé rutas y conclusiones». Los subagents pasan siempre. El criterio es si en los datos del hook hay `agent_id`: **si no lo hay, es el hilo principal**.

**Cuánto ahorra**: las llamadas a herramientas y el ensayo y error del subagent **van a su propio transcript** (en el almacén de sesiones se distinguen por `subpath`); en el hilo principal solo quedan esa llamada a `Agent` y el informe final. El proceso de ensayo y error no es que se haya compactado: es que **nunca entró en el hilo principal**.

- Medido (una tarea que genera mucha salida de herramientas): el 83% del transcript cae en los subagents; hilo principal 13 entradas, 21K caracteres; subagents 105K caracteres.
- Medido (a escala real, una ejecución de 10.4 horas, ver [HT001](../cases/ht001.md)): los subagents asumen el **97.7%** de los turnos y el **94.8%** de los caracteres de cuerpo; 1,893 llamadas a herramientas de acción frente a 32 del hilo principal (**59:1**). La compactación temprana deja de ser el asunto principal.

Las dos líneas son dos mediciones distintas: arriba, una prueba pequeña anterior; abajo, la remedición a escala real. El mismo mecanismo: cuanto mayor la escala, más ahorra.

Lo que se ahorra es contexto, no categoría de modelo: `worker()` usa por defecto `model="inherit"` —el ejecutor no debería ser degradado.

El único coste en contra del reparto es el [brief de tarea](../reference/glossary.md#任务书): ese párrafo que escribe el coordinador al repartir, que entra en el hilo principal y se queda para siempre. Medido: 8/8 briefs de tarea repetían disciplinas que el otro lado ya conocía; en el más corto, de 521 caracteres, solo unos 120 eran específicos de la tarea, con lo que un turno ocupa en vano unos 4.8k de contexto permanente. Por eso `COORDINATOR_RULES` fija una regla: **el brief de tarea solo escribe lo que es específico de esta tarea**. Lo único que aún hay que explicar es «dónde está el banco de trabajo + escribir las salidas largas en `artifacts/` + responder solo con rutas y conclusiones», porque el índice del banco de trabajo no llega al subagent y el brief de tarea es el único canal.

### Capa dos: el banco de trabajo (cura el «reescribirlo cada vez») {#第二层工作台治每次重写}

Tres directorios bajo `.flower/` que viajan con el espacio de trabajo:

| Directorio | Qué guarda | Qué resuelve |
|---|---|---|
| `scripts/` | Scripts de verificación / reproducción que se van a ejecutar una segunda vez, con `# desc: una frase` en la primera línea | Se escribe una vez y luego se ejecuta directamente. Se acabó el «se pierde con la compactación y hay que reescribirlo cada vez» |
| `artifacts/` | Salidas largas de más de 2000 caracteres: logs, datos, informes, diffs | En la conversación solo aparecen la ruta y la conclusión |
| `notes/` | Decisiones clave y sus razones, un fichero por decisión | Aunque se compacte, se reinicie o se cambie de máquina, las conclusiones siguen ahí |

**Cuándo se dispara**: `INDEX.md` se genera automáticamente (por defecto, como mucho 40 entradas); a `refresh()` lo llama `index_guard`, en `PostToolUse`, cuando un `Write` / `Edit` cae dentro del banco de trabajo, y también se refresca antes de arrancar cada paso. Estas tres reglas las inyecta `prompt_block()` en el system prompt del coordinador: desde el primer momento sabe qué scripts ya existen, sin gastar una llamada a herramienta en descubrirlos.

**Cuánto ahorra**: medido en una ejecución de 10.4 horas, **61 scripts escritos 95 veces y ejecutados 331 veces; el 92% se ejecutó más de una vez, y 0 se escribieron sin ejecutarse**. Cualitativamente, `audit-fake-ai-server.py` fue reutilizado por 7 scripts.

Esta capa funciona por una diferencia: la compactación puede limpiar el contexto, pero **no puede limpiar el disco, ni el índice que está en el system prompt**.

!!! warning "El índice no lo heredan los subagents"
    El índice va por el `system_prompt.append` de nivel de sesión; los subagents tienen su propio system prompt y **no lo heredan** (medido, $0.2461, `tests/prelude_live.py`). Por eso «dónde está el banco de trabajo + escribir las salidas largas en `artifacts/`» tiene que repetirlo el coordinador en el brief de tarea: es el único canal, no es redundancia.

### Capa tres: volcado en el acto {#第三层当场落盘}

`spill_guard` es un hook `PostToolUse` que mira el resultado de la herramienta **antes de que entre al modelo**: lo que supera el `threshold` (por defecto **4000** caracteres) se [vuelca a disco](../reference/glossary.md#落盘) en el directorio `spill/` del banco de trabajo, y en el contexto se sustituye por una línea de puntero + los **primeros 400 caracteres**. El contenido no se pierde, simplemente no reside en el contexto.

**Cuándo se dispara**: el matcher es `Bash|Read|Grep|Glob|WebFetch|WebSearch`; por defecto `main_only=False`, así que también se vuelcan los resultados de los subagents. Solo sustituye los **campos de texto** demasiado largos dentro de la estructura de salida de la herramienta; las listas no se tocan nunca (dentro puede haber bloques de imagen), porque `updatedToolOutput` tiene que conservar la estructura de salida de la herramienta original.

**Leer el propio fichero volcado se deja pasar y no se vuelve a volcar.** Si no, el «si necesitas el texto completo, léelo con Read» de esa línea de aviso sería papel mojado: se lee, vuelve a superar el umbral, se vuelve a volcar, se le vuelve a dar una línea de puntero, bucle infinito. Nos lo encontramos de verdad (la primera vez que `tests/handoff_live.py` corrió en serio): el modelo probó cinco formas de esquivarlo, dijo él mismo "The spill read loops back on itself", y al final lo royó a trozos de 40 líneas, quemando siete u ocho turnos en balde. El sentido del volcado es «**no** meter automáticamente cosas grandes en el contexto»; si él decide que quiere ver el texto completo, esa es su decisión.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None o 0 = no monta este hook
```

**Cuánto ahorra**: en aquella ejecución de [HT001](../cases/ht001.md), 103 volcados sustituyeron 791.4K caracteres por punteros de ruta, sin residir en el contexto.

### Capa cuatro: recorte y poda {#第四层裁剪与剪除}

Esta capa vive en el [almacén de sesiones](../reference/glossary.md#会话存储). El store de `Runtime` es siempre `PruningSessionStore` (cadena de herencia `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`), y en `load()` —es decir, **antes del resume**— reescribe el historial que se va a alimentar de vuelta. El texto original en SQLite no se toca ni una letra. Cuatro cosas:

**① Caducidad por vigencia** (`ephemeral`, activado por defecto). Los resultados de [comandos efímeros](../reference/glossary.md#一次性命令) como `git status`, `ls` o `cat` se sustituyen, al cabo de unos turnos, por una nota; se conservan los 6 más recientes. El contenido caducado **no se vuelca a disco**: archivar un `git status` viejo no tiene sentido, basta con volver a ejecutarlo:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

Medido en un resume en vivo: `expired: 2`; sobre un transcript real, bajando `keep_recent` a 2, caducaron 5 entradas.

**② [Recorte](../reference/glossary.md#裁剪)** (`trim`, **desactivado por defecto**). Los cuerpos de `tool_result` de `>= 2000` caracteres se vuelcan a `<workspace>/.flower/spill/` y el contenido del bloque se sustituye por un puntero a fichero; se conservan los 20 originales más recientes. Ojo: este directorio **no es el mismo** que el del volcado de `spill_guard` de la capa tres: aquel escribe en la raíz del banco de trabajo, mientras que este tiene que caer dentro del espacio de trabajo, o el `Read` del agente no lo alcanza.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True también sirve
```

**③ [Poda](../reference/glossary.md#剪除) de las llamadas denegadas** (`keep_denials`, por defecto 1). El propio acto de bloquear también contamina el contexto: el mensaje de rechazo es un `tool_result` y se queda para siempre junto con **el comando que nunca llegó a ejecutarse**. Medido: 273 caracteres por vez (93 caracteres de texto de rechazo + 180 del comando muerto); el comando muerto sale más caro que el rechazo.

Más grave que los tokens es que **induce a error**: medido, después de leer unos cuantos «no uses Bash directamente», el coordinador dejaba de intentar incluso el `git status` que sí estaba permitido y decía directamente «Bash está restringido, lanzo un agente a mirar» —había aprendido indefensión aprendida, y encima gastaba un arranque de subagent de más. Por defecto se deja 1 en vez de 0: el rechazo más reciente es señal útil, evita que el modelo reintente una y otra vez el mismo comando bloqueado dentro del mismo turno. La identificación se apoya en la marca estructural que pone el propio harness, `toolDenialKind: "permission-rule"`, no en emparejar el texto: el texto puede cambiar en cualquier momento, la marca no. Medido en vivo: 2 denegaciones → se quita 1 y se deja 1; la cadena no se rompe, el resume funciona y el modelo sigue sabiendo qué pasó.

**④ Poda de los restos de desconexión**. Los mensajes sintéticos de error de API generados durante los reintentos por caída de red no se vuelven a alimentar; los `tool_result` que dejó una interrupción se sustituyen por una nota neutra (`[上一轮在此处被中断,该工具结果未产生]`), conservando la entrada.

**La línea roja al quitar entradas**: un `tool_use` y su `tool_result` hay que quitarlos **juntos** (si falta uno, es `Missing Tool Result Block`), las demás llamadas del mismo mensaje de assistant no pueden verse afectadas, y la cadena de `parentUuid` hay que volver a empalmarla.

`Runtime(trim=False)` (el valor por defecto) **no significa que no se limpie nada**: solo desactiva el recorte de resultados grandes; la caducidad, las llamadas denegadas y los restos de desconexión se siguen tratando.

### Contraejemplo: el trabajo de echar un vistazo se hace uno mismo {#反例看一眼的活自己干}

Las tres primeras capas dicen «delega», pero hay un contraejemplo: comandos como `git status`, `ls` o `cat` dan resultados de unas decenas de caracteres, mientras que **lanzar un subagent cuesta unos 4.3k de contexto solo en arrancar** (medido, no amortizable). Pagar ese precio por un `ls` es pérdida neta.

Por eso el coordinador recupera un Bash restringido (`coordinator(..., glance=True)`, activado por defecto). El criterio no es «el comando es corto», sino **si el resultado va a caducar**, y «dejar pasar» y «caducar» los decide la misma función, `is_ephemeral()`:

| | Se deja pasar y lo ejecuta él | El resultado se marcará como caducado |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ delegar | — |

Ambos lados tienen que ser la misma tabla; si uno se sostuviera solo, sería dañino: **dejar pasar sin recortar** hace que un `git status` caducado ocupe contexto para siempre y encima se tome por el estado actual y desvíe decisiones; **recortar sin dejar pasar** obliga al coordinador a pagar 4.3k por un `ls`. `tests/glance.py` clava esta invariante como aserción: medido sobre 46 comandos, las dos decisiones coinciden por completo, incluyendo 10 muestras adversariales.

**Trampa (pisada dos veces)**: el modelo no escribe comandos sueltos; escribe `git status -s && echo "--- LOG ---" && git log --oneline -10`. La primera versión rechazaba de un tajo todo comando con `&&` / `|` / `2>&1`, y el resultado fue que **glance quedó completamente inutilizado**: medido, los tres intentos del coordinador fueron bloqueados y tuvo que volver a lanzar un subagent. Ahora se trocea y se comprueba segmento a segmento: solo pasa si cada segmento está en la lista blanca; `git status && rm -rf x` se sigue bloqueando (el segundo segmento no está en la tabla).

### Append, no reemplazo {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Cuando `build_options()` compila un `AgentSpec` a opciones del SDK, `instructions` va por [`append`](../reference/glossary.md#叠加): se añade **después** del system prompt nativo de Claude Code, no lo reemplaza. Por eso todos esos textos de disciplina (`COORDINATOR_RULES`, `WORKER_RULES`, etc.) son suma: **la especialización no se paga con pérdida de capacidad general.**

El índice del banco de trabajo va por el mismo canal. Está presente en cada turno, pero es parte del system prompt: no ocupa historial de conversación y la compactación tampoco lo borra. El precio es el de arriba: **solo llega al coordinador**.

!!! warning "No uses `disallowed_tools` para que el coordinador no toque nada"
    `disallowed_tools` es de **nivel de sesión**: deshabilita también a los subagents. Texto literal del error medido:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    Lo correcto son dos pasos: no darlo en `allowed_tools` y, además, usar un hook `PreToolUse` que bloquee solo el hilo principal según `agent_id`. `coordinator()` ya lo hace: fija `delegate_only=True`, y `delegate_guard` bloquea el hilo principal y deja pasar a los subagents.

    Apoyarse solo en `allowed_tools` tampoco basta: es una **lista de exención de aprobación, no una lista blanca excluyente**. Medido: el modelo puede llamar a herramientas que no están en ella —en una sonda de $0.1, un agente con `allowed_tools=["Read"]` seguía pudiendo llamar a Write / Bash. Lo que de verdad bloquea es el hook.

    **`allowed_tools` también es de nivel de sesión; la misma lección aprendida dos veces.** Las herramientas que no están en esa lista pasan igualmente por aprobación de permisos cuando las llama un **subagent**. Sin supervisión no hay quien apruebe, así que ni da error ni se para: el modelo reintenta la misma llamada una y otra vez (`toolDenialKind=user-rejected`). Medido: se añadieron `WebFetch`/`WebSearch` a los ejecutores pero solo se escribieron en `AgentDefinition.tools`; aquella ejecución acumuló más de veinte user-rejected y no produjo ni una palabra (`roles.py:513-518`). El síntoma es más difícil de diagnosticar que el de `disallowed_tools`: aquel da error en el acto, este no parece un error en pantalla.
    Por eso `coordinator()` ahora fusiona en su propio `allowed_tools` las herramientas web de solo lectura de los ejecutores a su cargo (`roles.py:523-526`), mientras que `Write`/`Edit`/`Bash` **se dejan fuera a propósito**: fusionarlas equivaldría a desmontar el hook de arriba.

## Cuándo no deberías usarlo {#什么时候不该用它}

Estas cuatro capas ahorran **material de trabajo**. Los problemas siguientes no los resuelven, y algunos se vuelven más difíciles de ver precisamente por ellas:

1. **Entender mal el objetivo: estas cuatro capas lo agravan.** Una vez descartado el material de trabajo, lo que queda es justo esa decisión construida sobre una premisa equivocada, y **se ve exactamente igual que una decisión correcta**. El largo horizonte lo amplifica al máximo: la premisa errónea corre varias horas, lanza una docena de subagents, deja un montón de salidas en disco, y solo entonces se destapa. A esas alturas lo caro no son los tokens: es que cada salida está construida sobre el requisito equivocado. Lo que para esto es la [clarificación previa](clarify.md), no ninguna de las capas de esta página.
2. **El hilo principal sigue creciendo monótonamente.** Las cuatro capas aplanan la pendiente, no cambian la dirección. Medido: en 70 turnos el hilo principal pasó de 28.7K a 185.9K, pendiente de 2.2K/turno, sin ninguna compactación en todo el recorrido, consumiendo el 18.6% de una ventana de 1M; **extrapolando, choca contra el muro hacia el turno 440**. Cruzar ese muro depende del [relevo](handoff.md).
3. **Al desactivar la compactación completa no queda red de seguridad.** Con el relevo activado, `Runtime` fuerza en el spec `CompactPolicy(mode="no_summary")` y el auto-compact queda desactivado (si el spec da explícitamente su propio `compact`, se respeta). Chocar con el límite es un error duro, así que estas cuatro capas hay que usarlas junto con el relevo; no basta con apagar la compactación y ya.
4. **La capa cuatro solo actúa en el resume.** El recorte y la poda ocurren en `load()`; una sesión que lleva rato corriendo no se encoge por ellos. Además, si haces el reparto como se describe arriba, esta capa casi nunca hará falta: el hilo principal ya no aloja muchos resultados de herramientas de todos modos.
5. **Delegar el trabajo de echar un vistazo es pérdida neta.** Arrancar un subagent cuesta unos 4.3k; ver la sección de glance más arriba.
6. **Antes de reordenar el contexto, haz las cuentas de la caché.** Medido en una ejecución: 299.4M tokens de entrada, **96.1% de aciertos de caché**; que $171 salga solo se sostiene gracias a eso. Cualquier optimización que reescriba el historial tiene que hacer antes esa cuenta.
7. **Los resultados de herramientas de tipo imagen o documento no se vuelcan.** `spill_guard` solo modifica los campos de texto de la estructura de salida; las listas no se tocan nunca.

Los valores por defecto completos y las firmas de los parámetros están en [Python API](../reference/api.md); los términos, en el [glosario](../reference/glossary.md).
