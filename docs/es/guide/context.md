# Economía del contexto

El contexto del [main thread](../reference/glossary.md#主线程) es lo único que persiste de principio a
fin en una ejecución [long-horizon](../reference/glossary.md#长程); lo que lleva y lo que no lleva
determina hasta dónde puede llegar esa ejecución. La forma de flower —el
[coordinator](../reference/glossary.md#协调者) no ejecuta, las salidas largas hacen spill, los hooks
podan en el acto— se deriva toda de esta única premisa. Esta página explica por qué.

## Qué problema resuelve {#解决什么问题}

El [compact](../reference/glossary.md#压缩) espera a que el contexto se llene para resumir en
retrospectiva; trata el síntoma. El problema real es:
**lo trivial no debería entrar al main thread desde el principio.**

La diferencia está en el momento. La salida de un `pytest` fácilmente llega a decenas de miles de
caracteres; el modelo le echa un vistazo, saca una conclusión, y el resto de los caracteres se
reenvían enteros en cada turno a partir de ahí; cuando la ventana se llena, el compact los resume
junto con la decisión de al lado en un único resumen —lo que ahorra es volumen, lo que pierde es
"por qué se decidió así en su momento". El umbral que dispara el auto-compact es
**ventana − 33k** ([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py));
para ese momento, lo que debía descartarse y lo que no ya yacen juntos.

flower lo resuelve con cuatro capas, cuyo orden es la prioridad —ordenadas por cuánto ahorran:

| Capa | Qué hace | Dónde |
|---|---|---|
| 1. División del trabajo | El trabajo de ejecución se delega a un [subagent](../reference/glossary.md#subagent); el ensayo y error va a su propio transcript | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. Workbench | Scripts / salidas largas / decisiones hacen spill, el índice se inyecta en el system prompt | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. Spill en el acto | El hook `PostToolUse` hace spill de los resultados de herramienta que superan el umbral, dejando en el contexto solo una línea con la ruta | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. Trim y prune | Reescribe la sesión antes del resume: resultados caducos, llamadas rechazadas y restos de desconexión ya no se reintroducen | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

Las dos primeras capas gobiernan **si las cosas entran**, las dos últimas gobiernan **si lo que ya
entró se queda**. El orden no se puede invertir: por más agresiva que sea la cuarta capa, no puede
recuperar el volumen que se coló en la primera.

## Cómo se usa (código mínimo) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model por defecto "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

Estas pocas líneas instalan las tres primeras capas: `coordinator()` fija siempre
`delegate_only=True` (capa uno); `workbench=True` crea el [workbench](../reference/glossary.md#工作台)
e inyecta el índice en el system prompt del coordinator (capa dos), y a la vez hace que `Runtime`
instale `spill_guard` (capa tres). La cuarta capa está por defecto —el
[session store](../reference/glossary.md#会话存储) de `Runtime` está fijado en código a
`PruningSessionStore`, sin ningún punto de entrada en los parámetros del constructor para cambiarlo.

!!! warning "`workbench=True` no es opcional"
    El `delegate_guard` que impide que el coordinator ejecute está enganchado en `workbench_hooks`, y
    `workbench_hooks` solo se instala cuando `Runtime` tiene workbench; el `whitelist_guard`, a su
    vez, se salta porque `delegate_only=True`.
    Conclusión: **con `Runtime(workbench=False)` junto a `coordinator()`, el Bash / Write / Edit del
    main thread no tiene ni un muro.**

## Qué hace en realidad {#它实际做了什么}

### Capa uno: división del trabajo (la que más ahorra) {#第一层分工省得最多}

El coordinator interpreta el papel de "una persona que sabe usar Claude Code": descompone, delega,
lee informes, decide. No tiene acceso a Bash / Write / Edit —sus únicas herramientas son `Agent`,
`TodoWrite` y `Read` (con `glance=True` se añade además un `Bash` restringido, ver abajo). Todo el
trabajo de ejecución se delega a los [workers](../reference/glossary.md#执行者).

**Cuándo se dispara**: cada vez que el main thread llama a `Bash|Write|Edit|NotebookEdit`, el hook
`PreToolUse` `delegate_guard` hace deny en el acto e indica el camino —"usa la herramienta Agent para
despachar un subagent, escribe en la tarea el objetivo y los criterios de aceptación con claridad, y
exígele que escriba las salidas largas en `.flower/artifacts/` y solo devuelva la ruta y la
conclusión". Los subagents se dejan pasar siempre. El criterio es si en los datos del hook hay
`agent_id`: **el que no lo tiene es el main thread**.

**Cuánto ahorra**: las llamadas a herramientas y el ensayo y error del subagent **van a su propio
transcript** (el session store los distingue con `subpath`), y en el main thread solo queda esa única
llamada `Agent` y el informe final. El proceso de ensayo y error no es que se comprima, es que **nunca
entró al main thread**.

- Medido (una tarea que produce mucha salida de herramienta): el 83 % del transcript cae en los
  subagents, con el main thread en 13 entradas, 21K caracteres, y los subagents en 105K caracteres.
- Medido (a escala real, una ejecución de 10.4 horas, ver [HT001](../cases/ht001.md)): los subagents
  asumen el **97.7 %** de los turnos y el **94.8 %** de los caracteres de cuerpo; 1,893 llamadas a
  herramientas de ejecución vs. 32 del main thread (**59:1**). El compact temprano deja de ser la
  línea principal.

Las dos líneas son dos mediciones distintas: la de arriba es una prueba temprana a pequeña escala, la
de abajo es una remedición a escala real. El mismo mecanismo, cuanto mayor la escala más ahorra.

Lo que se ahorra es contexto, no la categoría del modelo: `worker()` tiene `model="inherit"` por
defecto —el worker no debería degradarse.

El único coste inverso de la división del trabajo es el [task brief](../reference/glossary.md#任务书)
—ese texto que el coordinator escribe al delegar, que entra al main thread y además se queda
permanentemente. Medido: los 8/8 task briefs repetían la disciplina que la otra parte ya conocía; el
más corto tenía 521 caracteres de los cuales solo unos 120 eran específicos de la tarea, ocupando en un
turno unos 4.8k de contexto permanente en balde. Por eso en `COORDINATOR_RULES` está fijado en código
una regla: **el task brief solo escribe lo que es específico de esta tarea**. La única norma que aún hay
que transmitir es "dónde está el workbench + escribir salidas largas en `artifacts/` + devolver solo la
ruta y la conclusión" —porque el índice del workbench no llega al subagent, el task brief es el único
canal.

### Capa dos: workbench (trata el "reescribir cada vez") {#第二层工作台治每次重写}

Bajo `.flower/`, tres directorios que acompañan al workspace:

| Directorio | Qué guarda | Qué resuelve |
|---|---|---|
| `scripts/` | Scripts de verificación / reproducción que se ejecutarán una segunda vez, con la primera línea `# desc: 一句话` | Se escribe una vez, luego se ejecuta directamente. Ya no "se pierde tras el compact y hay que reescribirlo cada vez" |
| `artifacts/` | Salidas largas de más de 2000 caracteres: logs, datos, informes, diffs | En la conversación solo aparecen la ruta y la conclusión |
| `notes/` | Decisiones clave y su justificación, un archivo por decisión | Comprimido, reiniciado, cambiado de máquina, las conclusiones siguen ahí |

**Cuándo se dispara**: `INDEX.md` se genera automáticamente (por defecto hasta 40 entradas),
`refresh()` lo invoca el `index_guard` de `PostToolUse` cuando un `Write` / `Edit` cae dentro del
workbench, y también se refresca una vez antes de arrancar cada step. Estas tres reglas de arriba las
inyecta `prompt_block()` en el system prompt del coordinator —desde el inicio ya sabe qué scripts hay
disponibles, sin gastar primero una llamada a herramienta para descubrirlo.

**Cuánto ahorra**: medido en una ejecución de 10.4 horas, **61 scripts se escribieron 95 veces y se
ejecutaron 331 veces; el 92 % se ejecutó más de una vez, 0 se escribieron sin ejecutarse**.
Cualitativamente, `audit-fake-ai-server.py` fue reutilizado por 7 scripts.

Esta capa funciona gracias a una diferencia: el compact puede limpiar el contexto, pero **no puede
limpiar el disco, ni el índice en el system prompt**.

!!! warning "El índice no lo heredan los subagents"
    El índice va por el `system_prompt.append` a nivel de sesión; los subagents tienen su propio system
    prompt y **no lo heredan** (medido $0.2461, `tests/prelude_live.py`). Por eso "dónde está el
    workbench + escribir salidas largas en `artifacts/`" tiene que transmitirlo el coordinator en el
    task brief —ese es el único canal, no es redundancia.

### Capa tres: spill en el acto {#第三层当场落盘}

`spill_guard` es un hook `PostToolUse` que echa un vistazo a los resultados de herramienta **antes de
que entren al modelo**: los que superan el `threshold` (por defecto **4000** caracteres) hacen
[spill](../reference/glossary.md#落盘) al directorio `spill/` del workbench, y en el contexto se
sustituyen por una línea con el puntero + los **primeros 400 caracteres**. El contenido no se pierde,
solo deja de residir permanentemente.

**Cuándo se dispara**: el matcher es `Bash|Read|Grep|Glob|WebFetch|WebSearch`; por defecto
`main_only=False`, así que los resultados de los subagents también hacen spill. Solo reemplaza los
**campos de tipo string** demasiado largos de la estructura de salida de la herramienta, sin tocar
nunca las listas (dentro puede haber bloques de imagen), porque `updatedToolOutput` debe mantener la
estructura de salida de la herramienta original.

**Leer el propio archivo de spill se deja pasar y no vuelve a hacer spill.** De lo contrario, el "hay
que usar Read para leer el texto completo" de esa línea de aviso sería palabra vacía: se lee de vuelta,
vuelve a superar el umbral, vuelve a hacer spill y vuelve a darle una línea con el puntero, en un bucle
infinito. Medido: se topó con ello (`tests/handoff_live.py` en su primera ejecución real), el modelo
intentó cinco formas distintas de rodearlo, dijo por sí mismo "The spill read loops back on itself", y
al final tuvo que masticarlo a la fuerza en tramos de 40 líneas, quemando siete u ocho turnos en balde.
El sentido del spill es "**no** meter automáticamente cosas grandes en el contexto"; si él decide leer
el texto completo, esa es su elección.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None o 0 = no instalar este hook
```

**Cuánto ahorra**: en aquella ejecución de [HT001](../cases/ht001.md), 103 spills, 791.4K caracteres
sustituidos por punteros de ruta, sin residir en el contexto.

### Capa cuatro: trim y prune {#第四层裁剪与剪除}

Esta capa está en el [session store](../reference/glossary.md#会话存储). El store de `Runtime` es
siempre `PruningSessionStore` (cadena de herencia `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`), que en `load()` —es decir, **antes del resume**— reescribe el historial que va a
reintroducirse. El texto original en SQLite no se toca ni una letra. Cuatro cosas:

**① Caducidad por temporalidad** (`ephemeral`, activo por defecto). Los resultados de
[ephemeral commands](../reference/glossary.md#一次性命令) como `git status`, `ls`, `cat`: tras unos
turnos, el cuerpo se sustituye por una nota y se conservan los 6 más recientes. El contenido caducado
**no hace spill** —archivar un `git status` viejo no tiene sentido, con volver a ejecutarlo se tiene:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

Medido en un resume en vivo `expired: 2`; en un transcript real, subiendo `keep_recent` a 2, caducaron
5 entradas.

**② [Trim](../reference/glossary.md#裁剪)** (`trim`, **desactivado por defecto**). El cuerpo de
tool_result con `>= 2000` caracteres hace spill a `<workspace>/.flower/spill/`, el contenido del bloque
se sustituye por un puntero de archivo y se conservan los 20 textos originales más recientes. Nótese que
este directorio y el directorio de spill de `spill_guard` de la capa tres **no son el mismo**: aquel
escribe bajo la raíz del workbench, mientras que el de aquí tiene que caer dentro del workspace, o si no
el `Read` del agent no lo alcanza.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True también vale
```

**③ [Prune](../reference/glossary.md#剪除) de las llamadas rechazadas** (`keep_denials`, por defecto
1). El acto mismo de bloquear también contamina el contexto: el mensaje de rechazo es un `tool_result`,
y se queda permanentemente junto con ese **comando que nunca se ejecutó**. Medido: una vez fueron 273
caracteres (93 caracteres de mensaje de rechazo + 180 caracteres de comando muerto); el comando muerto
sale más caro que el mensaje de rechazo.

Más importante que los tokens es que **induce a error**: medido, tras leer unos cuantos "no usar Bash
directamente", el coordinator dejó de intentar incluso el `git status` que se dejaba pasar, y directamente
dijo "Bash está restringido, despacha un agent para mirar" —aprendió una indefensión aprendida, y encima
gastó de más un arranque de subagent. Por defecto se conserva 1 en vez de 0: el último rechazo es una
señal válida, capaz de evitar que el modelo reintente repetidamente el mismo comando bloqueado dentro del
mismo turno. El reconocimiento se apoya en la marca estructural `toolDenialKind: "permission-rule"` que el
propio harness pone, no en emparejar el texto —el texto puede cambiar en cualquier momento, la marca no.
Medido en vivo: 2 rechazos → se quita 1 y se conserva 1, la cadena no se rompe, el resume funciona
normalmente y el modelo sigue sabiendo qué pasó.

**④ Prune de los restos de desconexión**. Los mensajes de error de API sintéticos generados durante los
reintentos por caída de red no se reintroducen; el `tool_result` que dejó una interrupción se sustituye
por una nota neutra (`[上一轮在此处被中断,该工具结果未产生]`), conservando la entrada misma.

**Línea roja al retirar**: `tool_use` y su `tool_result` deben retirarse **juntos** (a falta de uno es
`Missing Tool Result Block`), las demás llamadas dentro del mismo mensaje de assistant no pueden verse
afectadas por error, y la cadena de `parentUuid` debe volver a empalmarse.

`Runtime(trim=False)` (por defecto) **no equivale a no limpiar nada**: solo desactiva el trim de
resultados grandes; caducidad, llamadas rechazadas y restos de desconexión se siguen haciendo.

### Contraejemplo: el trabajo de echar un vistazo lo haces tú mismo {#反例看一眼的活自己干}

Las tres primeras capas dicen "delegar hacia fuera", pero hay un contraejemplo: comandos como
`git status`, `ls`, `cat`, cuyo resultado son unas decenas de caracteres, mientras que **despachar un
subagent cuesta unos 4.3k de contexto solo por arrancar** (medido, no amortizable). Pagar ese precio por
un `ls` es pérdida neta.

Por eso el coordinator recupera un Bash restringido (`coordinator(..., glance=True)`, activo por
defecto). El criterio no es "el comando es corto", sino **si el resultado va a caducar**, y el
"dejar pasar" y el "caducar" los decide la misma función `is_ephemeral()`:

| | Se deja pasar para ejecutarse | El resultado se marcará como caducado |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ delegar | — |

Ambos lados deben ser la misma tabla, de lo contrario que cualquiera de los dos se cumpla por separado es
dañino: **dejar pasar sin trim** y el `git status` caducado ocupa el contexto permanentemente y encima se
toma como estado actual e induce a error en las decisiones; **hacer trim sin dejar pasar** y el
coordinator tiene que pagar 4.3k por un `ls`. `tests/glance.py` fija esta invariante como aserción
—medido: 46 comandos con juicio completamente idéntico en ambos lados, incluyendo 10 muestras
adversariales.

**Trampa (pisada dos veces)**: el modelo no escribe comandos sueltos, escribe
`git status -s && echo "--- LOG ---" && git log --oneline -10`. La primera versión rechazaba de un tajo
todos los comandos que contenían `&&` / `|` / `2>&1`, y el resultado fue que **glance dejó de funcionar por
completo** —medido: los tres intentos del coordinator fueron bloqueados, y no le quedó más que volver a
despachar un subagent. Ahora se descompone segmento a segmento: solo se deja pasar si cada segmento está en
la whitelist, y `git status && rm -rf x` se bloquea igual (el segundo segmento no está en la tabla).

### Append, no reemplazo {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Cuando `build_options()` compila el `AgentSpec` en opciones del SDK, `instructions` va por
[`append`](../reference/glossary.md#叠加) —se añade **después** del system prompt nativo de Claude Code,
no lo reemplaza. Por eso los textos de disciplina de arriba (`COORDINATOR_RULES`, `WORKER_RULES`, etc.) son
adición: **la especialización no se hace a costa de perder capacidad general.**

El índice del workbench también va por este canal. Está presente en cada turno, pero es parte del system
prompt, no ocupa historial de conversación, y el compact tampoco puede limpiarlo —el coste es justo el de
arriba: **solo llega al coordinator**.

!!! warning "No uses `disallowed_tools` para impedir que el coordinator ejecute"
    `disallowed_tools` es a **nivel de sesión**, y deshabilita también a los subagents. Texto del error
    medido:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    La forma correcta son dos pasos: no darlo en `allowed_tools`, y luego usar un hook `PreToolUse` para
    bloquear solo el main thread según `agent_id`. `coordinator()` ya lo hace así —fija `delegate_only=True`,
    y `delegate_guard` bloquea el main thread y deja pasar los subagents.

    Apoyarse solo en `allowed_tools` tampoco basta: es una **lista sin aprobación, no una whitelist
    excluyente**. Medido, el modelo puede invocar herramientas que no están en ella —en una sonda de $0.1,
    un agent con `allowed_tools=["Read"]` seguía pudiendo invocar Write / Bash. Lo que de verdad bloquea es
    el hook.

## Cuándo no deberías usarlo {#什么时候不该用它}

Lo que ahorran estas cuatro capas es todo **material en vivo**. Los siguientes problemas no los resuelven,
y algunos incluso se vuelven más difíciles de ver por su culpa:

1. **La comprensión del objetivo es errónea —estas cuatro capas la agravan.** Tras descartar el material en
   vivo, lo que queda es precisamente esa decisión construida sobre una premisa errónea, y encima **tiene
   exactamente el mismo aspecto que una decisión correcta**. El long-horizon la amplifica al peor caso: la
   premisa errónea corre primero varias horas, despacha una docena de subagents, deja un montón de salidas en
   disco, y solo después se destapa. Para entonces lo caro no son los tokens, es que cada salida está
   construida sobre un requisito equivocado. Lo que ataja esto es el [clarify](clarify.md), no ninguna de las
   capas de esta página.
2. **El main thread sigue creciendo monótonamente.** Las cuatro capas comprimen la pendiente, no la
   dirección. Medido: el main thread pasó de 28.7K a 185.9K en 70 turnos, pendiente 2.2K/turno, sin comprimir
   en todo el trayecto, consumiendo el 18.6 % de una ventana de 1M, **extrapolando choca contra el muro en
   unos 440 turnos**. Cruzar ese muro se apoya en el [handoff](handoff.md).
3. **Tras apagar el compact total no hay red de seguridad.** Con el handoff activo, `Runtime` fuerza en el
   spec `CompactPolicy(mode="no_summary")`, y el auto-compact queda apagado (si el spec dio explícitamente su
   propio `compact`, se respeta). Chocar contra el límite es un error duro, así que estas cuatro capas deben
   usarse en conjunto con el handoff, no basta con apagar el compact y ya.
4. **La cuarta capa solo surte efecto en el resume.** El trim y el prune ocurren ambos en `load()`; una
   sesión que corre continuamente no se encoge por su culpa. Después de dividir el trabajo como arriba, esta
   capa casi seguramente tampoco haga falta —el main thread de por sí no cabe muchos resultados de
   herramienta.
5. **Delegar el trabajo de echar un vistazo es pérdida neta.** El arranque de un subagent son unos 4.3k, ver
   la sección de glance arriba.
6. **Antes de reordenar el contexto, calcula la cuenta de caché.** Medido: una ejecución de entrada de 299.4M
   tokens, **96.1 % de aciertos de caché**, y $171 solo se sostiene gracias a eso. Cualquier optimización que
   reescriba el historial tiene que calcular primero esta cuenta.
7. **Los resultados de herramienta de tipo imagen o documento no hacen spill.** `spill_guard` solo cambia los
   campos de tipo string de la estructura de salida, sin tocar nunca las listas.

Los valores por defecto completos y las firmas de los parámetros están en la [API de Python](../reference/api.md);
la terminología, en el [glosario](../reference/glossary.md).
