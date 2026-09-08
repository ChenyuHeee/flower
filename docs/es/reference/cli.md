# Referencia de línea de comandos

Una vez instalado, `flower` es un único ejecutable: 4 subcomandos y 23 opciones. Esta página las lista
todas: el tipo de cada opción, su valor por defecto, su semántica exacta, además de cómo intervenir
mientras corre, qué te pregunta la primera vez, cuáles son los códigos de salida y qué ficheros deja en
tu directorio. Después de leer esta página no hace falta abrir el código fuente.

Código fuente: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcomando | Qué hace | Argumento posicional | Opciones propias |
|---|---|---|---|
| `go` | Todo en uno: aclarar el requisito → fijar objetivos → repartir el trabajo → veredicto en cada ronda. Es el predeterminado cuando no escribes subcomando | `ask` (opcional) | 11 |
| `run` | Ejecuta un [workflow](glossary.md#流程) escrito por ti | `target` (obligatorio) | 0 |
| `once` | Ejecuta un solo agente una vez, sin workflow y sin veredicto | `prompt` (obligatorio) | 6 |
| `setup` | Configura las credenciales y las escribe en `~/.config/flower/.env` | ninguno | 0 |

Total de 23 opciones = 5 globales + 11 propias de `go` + 6 propias de `once` + `-h/--help`. `run` y
`setup` no tienen opciones propias.

---

## Formas de invocación {#调用形式}

Todos los argv de `flower` pasan primero por `_with_default_cmd()`, que completa el subcomando
predeterminado, y luego se entregan a argparse (`cli.py:1437-1439`). Por eso funciona
`flower "帮我做一个 X"`: se reescribe a `flower go "帮我做一个 X"`.

Reglas para completar el subcomando predeterminado (`cli.py:940-976`):

1. El conjunto de opciones globales **se deriva del propio parser principal**, no es una lista
   codificada a mano. Las de `nargs == 0` cuentan como flags puros; el resto, como opciones con valor.
2. Se recorre de izquierda a derecha saltando las opciones globales. Las que llevan valor se saltan
   junto con su valor, y también se reconoce la forma con `=`, tipo `--workspace=/tmp`.
3. Se para en el primer token que no sea una opción global. Si es `go`, `run` u `once`, se pasa tal
   cual a argparse; **en caso contrario se inserta un `go` delante**, con lo que ese token pasa a ser
   el cuerpo de la petición de `go`.
4. Si se recorre todo sin encontrar un argumento posicional (argv vacío, o solo opciones globales) → se
   añade `go` al final y se entra en la entrada interactiva.
5. Excepción: si argv contiene `-h` o `--help`, se devuelve tal cual y argparse imprime la ayuda.

La constante que se usa para decidir es `_CMDS = ("go", "run", "once")` (`cli.py:937`): **`setup` no
está ahí dentro**, con las consecuencias que se ven en [`setup`](#setup).

### El resultado real de la reescritura {#实际的改写结果}

| Lo que tecleas | Lo que se parsea de verdad | Efecto |
|---|---|---|
| `flower` | `["go"]` | Pregunta en interactivo «¿qué hay que hacer?» |
| `flower -v` | `["-v", "go"]` | Igual, con verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Arranca directamente |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Las opciones globales pueden ir delante |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | También se reconoce la forma con `=` |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Las opciones del subcomando pueden ir detrás de la petición |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | También pueden ir delante |
| `flower --new` | `["go", "--new"]` | Solo opciones y ninguna petición → entrada interactiva |
| `flower once "hi"` | `["once", "hi"]` | Tal cual |
| `flower run flows:main` | `["run", "flows:main"]` | Tal cual |
| `flower run` | `["run"]` | argparse se queja de que falta `target`; **no** lo toma como petición |
| `flower go run` | `["go", "run"]` | Desambiguación explícita: el cuerpo de la petición es `run` |
| `flower setup` | `["go", "setup"]` | Lo que corre es `go`, con la petición igual a la cadena `setup`; ver [`setup`](#setup) |
| `flower --help` | Tal cual | argparse imprime la ayuda |

Las palabras `run` y `once` **no** pueden usarse directamente como cuerpo de la petición: es una
ambigüedad reservada a propósito (`cli.py:949-950`). Para usarlas como petición, escribe
`flower go run`.

### Seis formas válidas de escribirlo {#六种能用的写法}

```bash
flower                                    # 1. En seco: pregunta “要做什么?” o “接着上次?”
flower "帮我做一个 X"                       # 2. La petición como argumento posicional
echo "帮我做一个 X" | flower --timeout 0    # 3. stdin por tubería
flower once "读一眼这个仓库"                 # 4. Un solo agente
flower run flows.py:main                  # 5. Ejecuta un workflow propio
flower go setup                           # 6. go explícito, con setup como cuerpo de la petición
```

La forma de módulo `python -m flower.cli` es equivalente a `flower` (`cli.py:1451-1452`).
El wrapper de contenedor `docker/flowerbox` acepta exactamente los mismos argumentos que `flower`.

### stdin por tubería {#管道喂-stdin}

Cuando `sys.stdin.isatty()` es falso, `ask_for_prompt()` **no imprime la cabecera del prompt** y lee
una línea directamente con `input("> ")` (`cli.py:993-1001`). Por eso funciona `echo "..." | flower`.

Pero justo después imprime un aviso, y el hilo de stdin llega inmediatamente a EOF y termina:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

Ejecutar por tubería pide `--timeout 0`: las preguntas dejan de fingir que esperan 30 minutos, quedan
sin respuesta al instante, el agente decide por su cuenta y escribe sus supuestos en el apartado
«未知与假设» del brief.

---

## Subcomandos {#子命令}

### `go` {#go}

Texto de ayuda: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1275-1307`).

Argumento posicional `ask`, con `nargs="?"`: si no lo das, entra en la entrada interactiva. Es la
puerta de entrada más usada; `flower "做 X"` pasa por aquí.

Lo que hace (`cli.py:1190-1221`):

1. `ensure_credentials()`: comprueba las credenciales y lanza de verdad una sonda contra la API; ver
   [el flujo de configuración de la primera ejecución](#首次运行的配置流程).
2. Sondeo de [despertar](glossary.md#唤醒): solo mira si este directorio se ha usado antes, sin
   escribir un solo byte.
3. Si no diste `ask`, imprime el prompt y pregunta; escribir `/new` equivale a `--new`, y entonces
   **vuelve a preguntar** la petición.
4. Si es una [continuidad](glossary.md#接续), imprime una línea de banner de despertar.
5. Construye un [workflow](glossary.md#流程) de tres pasos: `确认需求` → `设定目标` → `干活`,
   con un `干活·判定#N` detrás de cada ronda de trabajo. Con `--clarify-only` solo queda el primer paso.
6. Arranca.

El banner de despertar tiene esta pinta (el directorio home dentro de las rutas se sustituye por `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` aparece siempre; `目标 N 条` solo si hay lista de veredicto; `干活上下文 X` requiere poder
consultar en `sessions.db` el contexto de la última vuelta de esa [sesión](glossary.md#会话), y si no
se encuentra no se muestra.

!!! warning "`-W` y `-T` quedan silenciosamente anulados en la ruta `go`"
    Estas dos opciones globales no sirven de nada en `go`: no dan error ni avisan.

    - `-W/--workbench`: el workflow que construye `go` siempre trae su propio
      [banco de trabajo](glossary.md#工作台), y el código toma
      `getattr(wf, "workbench", None) or args.workbench` (`cli.py:1038`): el del workflow tiene
      prioridad siempre. Así que el banco de trabajo es invariablemente `<workspace>/.flower/`
      (con `--isolate`, `<workspace>.parent/.flower-<nombre>/`), y `-W` no lo cambia.
    - `-T/--trim`: `go` pasa por `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1221`), es decir,
      usa la negación de `--no-trim` y **ni siquiera mira `args.trim`**. O sea: en la ruta `go` el
      [recorte](glossary.md#裁剪) está activado por defecto y solo se puede apagar con `--no-trim`.

    Estas dos opciones solo surten efecto en `run` (cuando el workflow no trae banco de trabajo propio)
    y en `once`.

#### Las 11 opciones de `go` {#go-的-11-个开关}

| Opción | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `--asks N` | int | `-1` | Cupo de preguntas. `-1` o cualquier negativo = **sin límite**; `0` = prohibido preguntar, la primera pregunta ya es `over_budget`; `N` = cupo estricto. Al pasarse, la herramienta rechaza directamente sin bloquear la ejecución |
| `--rounds N` | int | `3` | Tope del **número total de rondas** de trabajo, no rondas adicionales. Al final de cada ronda un [juez](glossary.md#判定者) independiente decide «¿está terminado?»; si no, lo devuelve y se continúa en la misma sesión |
| `--no-goal` | flag | `False` | Desactiva el [guardián de objetivos](glossary.md#目标看守): no genera `目标.md`, no emite [veredicto](glossary.md#判定), y en cuanto termina el trabajo se da por hecho |
| `--judge-can-run` | flag | `False` | Permite al juez ejecutar comandos. El veredicto es más duro, a cambio de que también puede modificar el espacio de trabajo |
| `--timeout 秒` | float | `1800.0` | Cuánto esperar una respuesta humana. `0` o negativo = totalmente automático: todas las preguntas quedan **de inmediato** sin respuesta, sin fingir espera. Semántica en [Timeout](#超时) |
| `--isolate` | flag | `False` | Da a cada [subagent](glossary.md#subagent) su propio git worktree, es decir [aislamiento](glossary.md#隔离). **Exige que el workspace sea un repositorio git**; si no, código de salida 1. Además saca el banco de trabajo fuera del repositorio |
| `--window N` | int | ninguno (se deduce del nombre del modelo) | Ventana de contexto del modelo. Si no se da: nombre de modelo que contiene `1m` o que no contiene `haiku` → 1,000,000; que contiene `haiku` → 200,000. Al llegar a `ventana − 50000` se escribe el [documento de relevo](glossary.md#交接书) y se hace el [relevo](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Desactiva el relevo y vuelve al [compact](glossary.md#压缩) que trae el SDK |
| `--new` | flag | `False` | No continúes lo anterior esta vez. **Mueve** (no borra) el `lineage.json` + `需求.md` + `目标.md` del tramo previo a `notes/archive/<YYYYmmdd-HHMMSS>/` y empieza de cero |
| `--clarify-only` | flag | `False` | Solo hace la [clarificación previa](../guide/clarify.md), sin seguir trabajando: en el workflow solo queda el paso `确认需求` |
| `--no-trim` | flag | `False` | Desactiva el recorte. En la ruta `go` el recorte está **activado** por defecto, y esta es la única forma de apagarlo |

Casos límite en los valores; ninguno da error ni avisa:

- `--rounds 0` y `--rounds 1` son equivalentes: internamente es `retries = max(0, rounds - 1)`, ambos
  ejecutan 1 ronda.
- Cualquier valor negativo de `--asks` significa sin límite, no solo `-1`.
- Cualquier valor negativo de `--timeout` equivale a `0`, es decir, totalmente automático.
- `--window 0` se **ignora en silencio** (`0` es falsy y ni siquiera se propaga) y se vuelve al valor
  por defecto deducido del nombre del modelo. Los negativos sí se propagan y luego se elevan a `10000`.
- `--clarify-only` es **una operación vacía** en un directorio ya clarificado: el paso `确认需求` ve un
  `需求.md` completo y lo salta, y como en el workflow solo está ese paso, no ocurre nada (salvo que el
  contador de despertares sube en 1). Para volver a clarificar hay que combinarlo con `--new`.
- El `--help` de `go` termina diciendo «全局开关(-v/-w/-r/-T)见 `flower --help`», y esa línea **se
  deja `-W`**.

### `run` {#run}

Texto de ayuda: `运行一个 workflow` (`cli.py:1309-1312`).

Argumento posicional `target`, escrito como `módulo:atributo`. Se admiten ambas formas
(`cli.py:1010-1031`):

```bash
flower run mypkg.flows:build     # import por nombre de módulo
flower run flows.py:build        # ruta de fichero; mete el directorio padre en sys.path e importa por nombre de fichero
```

Si el atributo obtenido es invocable se llama una vez y su valor de retorno se toma como
[workflow](glossary.md#流程); si ya es un objeto workflow, se usa directamente.

**`run` no tiene ninguna opción propia**, solo las 5 globales. Por tanto `--window`, `--no-handoff` y
demás toman siempre su valor por defecto en esta ruta (el código usa `getattr` como respaldo,
`cli.py:1041-1043`). Para ajustarlas, escríbelas dentro de tu propio workflow.

### `once` {#once}

Texto de ayuda: `跑一次单 agent` (`cli.py:1314-1324`). El argumento posicional `prompt` es obligatorio.

Construye un `AgentSpec(name="ad-hoc", …)` y lo ejecuta directamente, **sin pasar por `_drive`**. Por
eso en `once` no hay:

- Interrupción con Ctrl-C acompañada de un mensaje (pulsarlo es un `KeyboardInterrupt` normal)
- Hilo de respuesta por stdin ni prompt de entrada fijo al pie
- Preguntas al oráculo
- Rescate contable ante SIGHUP / SIGTERM
- La línea final `总花费 … · 清单 …`
- La guía de reconfiguración automática tras un fallo de credenciales

En el [manifiesto de ejecución](glossary.md#运行清单), el nombre de este paso es siempre `ad-hoc`.

| Opción | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `-i`, `--instructions` | str | vacío | Instrucciones de dominio, que se [añaden](glossary.md#叠加) **después** del prompt de sistema nativo de Claude Code, sin sustituirlo |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Lista blanca de herramientas separadas por comas. Si no se da, son esas tres herramientas de solo lectura |
| `-p`, `--permission-mode` | str | `default` | Solo admite `default`, `acceptEdits`, `plan` o `bypassPermissions`; con otro valor argparse falla con código de salida 2 |
| `-b`, `--budget` | float | sin tope | Tope de [presupuesto](glossary.md#预算) en dólares; al superarlo, se para |
| `--resume SESSION_ID` | str | ninguno | Continúa una sesión existente |
| `--fork` | flag | `False` | Bifurca en lugar de continuar; se usa junto con `--resume` |

!!! warning "El tiempo y el coste acumulado que muestra `once` son siempre 0"
    `once` crea una instancia nueva del renderizador con cada evento que recibe (`cli.py:688-690`,
    `cli.py:1239`), mientras que el instante de inicio y el coste acumulado viven en la instancia
    (`cli.py:500-501`). De ahí que:

    - El `用时` de la línea final sea siempre `0:00`
    - El `累计 $0.00` de la línea de estado sea siempre 0, y el `上下文` nunca se acumule

    El coste real de ese único paso hay que mirarlo en el campo `cost_usd` de `runs/manifest.json`. Las
    rutas `go` y `run` mantienen una única instancia del renderizador y no tienen este problema.

### `setup` {#setup}

Texto de ayuda: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1326-1328`).
No tiene ninguna opción.

Lo que hace: lee el `.env` → decide si ya está configurado → lanza el flujo de configuración
interactivo, con `reason` igual a `重新配置。` o `还没配过凭证。`. El contenido de la pantalla está en
[el flujo de configuración de la primera ejecución](#首次运行的配置流程).

!!! warning "`flower setup` no llega hoy a ese subcomando"
    La constante que decide el subcomando predeterminado, `_CMDS = ("go", "run", "once")`
    (`cli.py:937`), **se deja `"setup"`**, pero el parser sí registra `setup` (`cli.py:1326`). Así que
    `flower setup` se reescribe a `flower go setup`: **lo que corre es el flujo completo de `go`, con la
    cadena `setup` como cuerpo de la petición**; primero valida credenciales, luego pregunta el
    requisito y después se pone de verdad a repartir trabajo. Con opciones globales pasa lo mismo:
    `flower -v setup` → `["-v", "go", "setup"]`.

    **No hay ningún argv que llegue al subcomando `setup`.**

    Para configurar las credenciales hoy solo quedan dos caminos, ambos desembocan en la misma pantalla
    interactiva:

    - Ejecutar directamente `flower "随便一句诉求"`: si no hay credenciales configuradas, preguntará antes;
    - O escribir a mano `~/.config/flower/.env`, con los nombres de clave de
      [Las claves que escribe](#写出来的键).

    También quedan afectados varios textos: el ``跑 `flower setup` 重配。`` que se imprime cuando se
    rechazan las credenciales, y el comentario de la primera línea del `.env`, ``由 `flower setup` 写``,
    apuntan todos a este comando inalcanzable.

---

## Opciones globales {#全局开关}

Las 5 opciones globales están registradas a la vez en el parser principal y en cada subcomando
(`cli.py:1250-1266`). La copia del subcomando usa `argparse.SUPPRESS`, así que si no se da no escribe
el atributo: por eso **da igual escribirlas antes o después del subcomando**, no se pisan entre sí. El
efecto secundario es que no aparecen en el `--help` del subcomando; para verlas hay que ejecutar
`flower --help`.

| Opción | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | Directorio de trabajo del agente. Se resuelve con `resolve()` a ruta absoluta y se hace `mkdir -p`. El [banco de trabajo](glossary.md#工作台) `.flower/` se crea aquí dentro |
| `-r`, `--run-dir` | str | `runs` | Directorio del [almacén de sesiones](glossary.md#会话存储) y del manifiesto de ejecución. **Relativo al CWD actual, no al workspace** |
| `-v`, `--verbose` | flag | `False` | Imprime más cosas; ver abajo |
| `-W`, `--workbench` | flag | `False` | Activa el banco de trabajo. **No hace nada en `go`**; solo surte efecto en `run` (cuando el workflow no trae banco propio) y en `once`, y entonces el banco cae en `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | Al hacer resume, sustituye los resultados grandes de herramientas antiguos por punteros a fichero, es decir, [recorte](glossary.md#裁剪). **No hace nada en `go`**, esa ruta se controla al revés con `--no-trim` |
| `-h`, `--help` | flag | — | Está en todos los parsers. Si aparece en argv se salta la reescritura del subcomando predeterminado y se imprime la ayuda |

Lo de que `-r/--run-dir` sea relativo al CWD muerde: `flower -w /other/proj "做 X"` crea `runs/` en **el
directorio desde el que lanzaste el comando**, mientras que `.flower/` se crea bajo `/other/proj/`: los
dos estados quedan separados. Para tenerlos juntos, da explícitamente `-r /other/proj/runs`.

La ayuda de `-v` dice «显示思考与工具结果», pero el pensamiento del [hilo principal](glossary.md#主线程)
**se muestra por defecto**. Lo que `-v` activa de verdad además es:

- El cuerpo del subagent (por defecto no se muestra, solo sus llamadas a herramientas)
- Los resultados normales de herramientas (por defecto solo se muestran los que dan error)
- El evento `prompt`
- Un volcado, antes de arrancar, de la configuración de credenciales vigente, con el token enmascarado
  dejando solo los 4 primeros caracteres

Esto último sale por un `print()` pelado, **sin pasar por la desinfección de salida, sin ajuste de
ancho y sin la protección del cerrojo de escritura del terminal**: al ejecutar varios `flower` en
paralelo, esas líneas pueden salir mezcladas.

---

## Cómo hablarle mientras corre {#运行中怎么和它说话}

Una vez arrancada la ejecución, el terminal **está leyendo tu entrada todo el tiempo**. No hace falta
esperar a que pregunte ni pulsar nada para entrar en modo entrada: la última línea es siempre la línea
en la que puedes escribir.

### El prompt de entrada fijo al pie {#常驻在最下面的输入提示符}

Hay un hilo daemon `flower-stdin` que lee stdin de principio a fin (`cli.py:764-934`), con `select`
sondeando cada 0.2 segundos en lugar de lectura bloqueante (así la señal de parada puede despertarlo; en
flujos que no soportan `select`, como en Windows, degrada a lectura bloqueante).

**Lee siempre, no solo cuando hay una pregunta pendiente.** El motivo: si solo leyera al preguntar, lo
que teclees durante las horas de trabajo quedaría en el búfer del terminal y, en la siguiente pregunta,
se tomaría como respuesta; la pregunta quedaría contestada antes de que la vieras.

En cuanto a la pantalla, `_say()` es la única salida: antes de imprimir borra el prompt y después lo
vuelve a dibujar (`cli.py:309-315`), de modo que el prompt no acaba empujado hacia arriba por la salida
de eventos. **Al redibujarlo también repinta los caracteres que habías tecleado a medias sin pulsar
intro**: viven en `_PROMPT["buf"]` (`cli.py:183-192`). Sin eso el contenido no se perdería de verdad
(sigue en el búfer de línea del terminal y el intro lo enviaría igual), pero no lo verías, dudarías y lo
volverías a escribir.

El prompt tiene dos textos, según haya o no una pregunta pendiente de respuesta:

| Estado | Última línea de la pantalla |
|---|---|
| Con pregunta pendiente | `你的回答 (回车=跳过,让它自己判断) > ` |
| Sin pregunta pendiente | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Modo de entrada carácter a carácter y teclas {#逐字符输入}

Para poder repintar «los caracteres a medias», flower tiene que tomar el control de la entrada. Cuando
stdin es un terminal y se puede `import termios`, pone el terminal en `cbreak` **antes** de arrancar el
hilo `flower-stdin` (`cli.py:793-807`): se usa `cbreak` y no `raw` para que Ctrl+C siga generando
`SIGINT` y todo lo de [Ctrl-C](#ctrl-c) siga funcionando. Tiene que ser antes de arrancar el hilo:
meterlo dentro del hilo abre una carrera real, y los caracteres tecleados en el instante en que el hilo
aún no ha conseguido CPU se los come el modo de línea, lo que se manifiesta como «se ha perdido la
entrada» (reproducido de forma estable una de cada tres veces en pruebas, `cli.py:928-934`).

Si no se puede configurar, se vuelve al `readline()` de línea completa de siempre (stdin no es terminal,
`termios` no disponible, o `tcgetattr` falla). Ambos caminos funcionan; simplemente, en modo línea no
existen las teclas de abajo (`cli.py:883-899`).

La lógica de edición vive en `LineEditor` (`cli.py:320-414`), pura máquina de estados que no toca el
terminal:

| Tecla | Efecto |
|---|---|
| Carácter imprimible | Se inserta en el cursor. UTF-8 usa un decodificador incremental y solo entra al búfer cuando hay un carácter completo |
| Backspace / Ctrl+H | Borra **un carácter** delante del cursor. En modo línea el terminal borra por bytes, un ideograma exige tres pulsaciones y deja basura; aquí no |
| ← / → | Mueven el cursor de verdad. La secuencia de escape completa se consume, así que no acaban insertándose cosas como `[A` |
| Home / End (o `[1~` / `[4~`) | Salta al inicio / fin de línea |
| Delete (`[3~`) | Borra un carácter hacia delante |
| Ctrl+A / Ctrl+E | Inicio / fin de línea |
| Ctrl+U | Vacía la línea entera |
| Ctrl+D | Solo es EOF con el búfer vacío; con contenido se ignora |
| ↑ / ↓ | **No hacen nada**. No hay historial, y moverlas haría creer que se ha perdido algo (`cli.py:335`) |
| Otros caracteres de control | Se ignoran |

El intro entrega el búfer y lo vacía, y a la vez salta de línea en pantalla: lo que dijiste queda arriba
(`cli.py:811-827`).

### Adónde va lo que tecleas {#你敲的东西去哪了}

| Lo que escribes | Con pregunta pendiente | Sin pregunta pendiente |
|---|---|---|
| **Línea vacía (intro a secas)** | Salta esa pregunta y deja que decida solo | No hace nada |
| **Empieza por `?`** | Consulta al oráculo, ver abajo | Igual |
| **Solo dígitos**, dentro del rango de opciones | Se convierte en esa opción y se responde | Se trata como texto normal |
| Cualquier otro texto | Se envía como respuesta al agente que preguntó | Entra en la bandeja de entrada como requisito añadido |
| EOF (Ctrl-D o tubería cerrada) | Rechaza esa pregunta, retira el prompt y el hilo termina | Retira el prompt y el hilo termina |

Al entrar en la bandeja de entrada se imprime un acuse:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

Cuando no hay [brief](glossary.md#需求确认书) donde volcarlo, la segunda mitad pasa a ser
`没有确认书可落盘 —— 它可能活不过下一个步骤`. La bandeja de entrada **no interrumpe** al ejecutor que
está trabajando: solo se lo lleva cuando consulta la bandeja por iniciativa propia. La misma frase se
añade además a `notes/需求.md`; sin volcarla a disco no sobrevive al límite del paso, porque el
siguiente paso es una sesión nueva que solo lee el documento congelado.

### Empezar por `?` = consulta al oráculo {#旁路问答}

Una línea que empieza por `?` no se envía al agente que está corriendo, sino al
[oráculo](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

Arranca un Runtime **independiente**, con `run_dir` en `<run_dir>/aside/`, de modo que su coste y su
linaje de sesiones no se mezclan con el `manifest.json` principal. El rol es de solo lectura, con las
herramientas `Read`, `Glob` y `Grep`, un máximo de 12 vueltas y un tope de coste de **$0.5**. El
contexto que ve son los últimos **60** eventos (los eventos `thinking` y `prompt` no entran en esa
ventana), cada uno truncado a 200 caracteres, más la descripción de las rutas del banco de trabajo.

Corre **en paralelo**: la ejecución en curso no espera ni un segundo. La respuesta se ve así:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

Si falla, imprime una línea en rojo `# 旁路问答失败:<类型>: <消息>`, **sin afectar al flujo principal**.
Al salir espera como mucho **120 segundos** a que terminen las consultas al oráculo, y antes de esperar
imprime una línea `(等 N 条旁路问答收尾…)`.

Lo que dice no entra en el contexto de esa ejecución: preguntar no la altera, y la respuesta se descarta
al terminar.

!!! warning "El `？` de ancho completo no dispara la consulta al oráculo: los usuarios de IME chino tropiezan aquí"
    La línea de código que decide si es una consulta al oráculo es (`cli.py:907`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Los dos caracteres son **`?` ASCII de ancho medio** (`0x3f`), verificado byte a byte. Por la forma
    de escribirlo, la intención era claramente aceptar a la vez el `?` de ancho medio y el `？` de ancho
    completo (U+FF1F) que produce el IME chino, pero acabaron siendo el mismo carácter.

    Consecuencia: **una línea que empiece por `？` de ancho completo no se toma como pregunta al
    oráculo**, sino que entra en silencio en la bandeja de entrada como «requisito añadido» y, de ahí,
    se anexa a `notes/需求.md`. El acuse que ves es `+ 收到`, no `# 旁路`.

    Para preguntar al oráculo **hay que usar el `?` de ancho medio**: cambia el IME a inglés antes de
    escribir, o al menos teclea el primer carácter en ancho medio.

### Qué se ve en pantalla {#屏幕上都是什么}

Los iconos son **todos ASCII**, no emoji (`cli.py:51-69`). La razón está escrita en un comentario del
código: los emoji y los caracteres de marco, geométricos y de flecha disparan el fallback de glifos del
terminal, y eso ya provocó dos cuelgues del terminal.

| Icono | Significado | Icono | Significado |
|---|---|---|---|
| `=` | Separador de paso | `+` | Hecho / respondido / recibido |
| `~` | Pensamiento, reintento | `x` | Fallo / error |
| `>` | Reparto de trabajo | `#` | Relevo, oráculo, tarea |
| `*` | Llamada a herramienta | `-` | Línea de estado, elemento de lista |
| `?` | Pregunta | `<-` | Continuación, punto de aterrizaje del relevo |
| `!` | Aviso / interrupción | `.` | Saltado |
| `\| ` | Barra vertical de sangrado del subagent | | |

!!! warning "El `❓` y el `↩` de la documentación antigua no existen en un terminal real"
    La documentación temprana usaba `❓` para las preguntas y `↩` para la línea de despertar. **En el
    código nunca fueron esos caracteres**: el icono de pregunta es un `?` de ancho medio, y el del
    despertar y el punto de aterrizaje del relevo son los dos caracteres ASCII `<-`.

    Así que lo que imprime un terminal real es:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    No `❓ 这个工具……`, ni `↩ 在 ~/proj 接上上次`. Buscar en los logs con grep según la documentación
    antigua no encuentra nada.

Los cinco estados de una pregunta se ven así en pantalla:

| Estado | Salida en pantalla |
|---|---|
| Se ha preguntado | `  ? <问题>`, seguido de las opciones una a una `     1) 选项一`, y si hay cupo, además `     (还能问 N 次)` |
| Respondida | `  + <答案>` |
| Timeout | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Cupo agotado | `  ! 提问额度用完` |
| La has saltado | `  . 已跳过` |

Cuando `--asks` es sin límite (el valor por defecto), esa última línea de «还能问 N 次» no se muestra.

Cuando el [relevo](glossary.md#换代) termina de escribir el documento de relevo, sale un bloque entero:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

Si el documento de relevo se degrada, se inserta una línea más en rojo:
`交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

La salida hace además dos cosas que no ves: todas las líneas pasan por una desinfección que **solo deja
pasar los códigos de color SGR del propio flower**, de modo que las secuencias de borrado de pantalla o
movimiento de cursor que escupan el modelo o las herramientas se tragan enteras; y el ancho se toma como
`max(40, min(columnas del terminal, 110))`, así que en terminales anchos no se ocupa toda la línea, y es
a propósito.

### El prompt del arranque {#起跑时的提示符}

Al ejecutar `flower` en seco (sin petición), primero pregunta. Hay dos textos:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

El segundo solo aparece si en ese directorio ya se ha ejecutado antes y `需求.md` tiene los cuatro
apartados completos.

Este prompt lee con `input()`, **sin pasar por la interpretación del shell**. Las comillas chinas, los
espacios y los signos de exclamación se pueden escribir tal cual: esa es toda la razón de que exista.
zsh, al encontrarse una comilla derecha china, entra en continuación `dquote>` y parece colgado, cuando
en realidad no ha arrancado ni una vez.

- Entrada vacía + primera vez → sale, imprimiendo ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Entrada vacía + despertar → **es válido**, significa «sigue con lo de antes»
- Escribir `/new` → equivale a `--new`: archiva el tramo anterior y **vuelve a preguntar** la petición
- Ctrl-C / Ctrl-D → sale, imprimiendo `已取消`

### Timeout {#超时}

`--timeout` es un float en segundos, por defecto `1800.0`. Tres tipos de valor:

| Valor | Comportamiento |
|---|---|
| `> 0` | Espera esos segundos. Al agotarse, esa pregunta se liquida como `timeout` y el agente decide por su cuenta |
| `0` o negativo | **Totalmente automático**. La pregunta no entra en la cola de espera, no emite evento `asked`, no aparece en pantalla, y se liquida de inmediato como `timeout` |
| Esperar para siempre | **No se puede desde la línea de comandos**. Internamente se soporta «esperar para siempre», pero `--timeout` es un float con valor por defecto y no hay forma de escribirlo que lo produzca. El límite es dar un número de segundos muy grande |

`--timeout 0` y `--timeout -1` son exactamente equivalentes. Por tubería, en CI o desatendido, se usa
siempre esto.

Cuando una pregunta no obtiene respuesta, el resultado de herramienta que se devuelve al modelo es un
texto fijo, de cuatro tipos:

| Resultado | Texto devuelto al modelo |
|---|---|
| Cupo agotado | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| La has saltado | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| La pregunta está vacía | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**La semántica de Ctrl-C es completamente distinta en dos sitios.**

**Pulsado en el prompt de arranque `> `**: sale del programa directamente, imprimiendo `已取消`.

**Pulsado durante la ejecución**: interrumpe la ronda actual y te da una oportunidad de hablar:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Pulsar intro aquí significa interrumpir sin decir nada y seguir. Si en ese momento hay preguntas
pendientes, se imprime una línea más: `  (有 N 个提问还等着,打断不影响它们)`.

**Pulsar Ctrl+C otra vez sí sale de verdad**, y como `KeyboardInterrupt` no capturado: en pantalla queda
un traceback de Python, no es una salida limpia.

La interrupción es cooperativa: corta limpiamente en un límite de mensaje, sin cancelar tareas a la
fuerza. **No cuenta como un intento fallido** y no consume reintentos. Al continuar se adjunta una nota
que le dice al modelo que «una llamada a herramienta en vuelo que devuelve interrupted es un efecto
normal de la interrupción, no un fallo del entorno».

Este Ctrl-C personalizado solo se instala cuando `sys.stdin.isatty()` (`cli.py:1097`). Ejecutando por
tubería se mantiene el comportamiento por defecto de Python, es decir, salir a la primera. La ruta
`once` no pasa por aquí, así que allí Ctrl-C también sale a la primera.

### SIGHUP / SIGTERM {#sighup-sigterm}

Las rutas `go` y `run` instalan manejadores para `SIGHUP` y `SIGTERM`: primero escriben también en
`manifest.json` **el paso que estaba en vuelo** marcándolo como `killed-by-signal`, y después restauran
la acción por defecto y se van de verdad.

El origen: cuando el terminal se cae, el kernel envía SIGHUP, cuya acción por defecto termina el proceso
directamente, el `finally` no corre y el manifiesto no se escribe, y se pierde la contabilidad de una
ejecución entera. Si no es el hilo principal del sistema operativo o la plataforma no lo soporta, se
salta en silencio.

---

## El flujo de configuración de la primera ejecución {#首次运行的配置流程}

Las tres puertas de entrada `go`, `run` y `once` llaman al principio a `ensure_credentials()`
(`cli.py:1392-1428`), con **dos filtros**.

### Primer filtro: ¿hay credenciales? {#第一道-有没有凭证}

Busca las credenciales por orden de prioridad. Si no encuentra `ANTHROPIC_API_KEY` ni
`ANTHROPIC_AUTH_TOKEN`, lanza la configuración interactiva; en modo no interactivo (stdin no es
terminal) no bloquea: imprime esto y sale:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Este texto no cuadra con la implementación en dos puntos: el `flower setup` de la segunda línea hoy no
se alcanza (ver [`setup`](#setup)); y la cuarta línea **dice lo contrario que el código**: flower sí toma
el bloque `env` de `~/.claude/settings.json` y de `settings.local.json` como **último nivel de
respaldo**, tomando prestadas de ahí 9 claves de credenciales y sin apropiarse de ningún otro ajuste. El
sitio que imprime esa línea es `env.py:192` (la función `check_credentials()` está definida en
`env.py:184`), mientras que lo que lee de verdad esos dos ficheros está en `env.py:56-75` y `:109-111`;
anotado en [issue #13](https://github.com/ChenyuHeee/flower/issues/13).
**Manda el código: sí los lee.** La prioridad de búsqueda completa y esas 9 claves están en la
[referencia de configuración](config.md#借用).

### Qué pregunta la configuración interactiva {#交互配置问什么}

```text
== 配置 flower ========================================
<为什么要配这一行>
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   > 

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   > 

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   > 

+ 存好了:/Users/you/.config/flower/.env
```

- La pregunta 1 es **obligatoria**. Si la dejas vacía, imprime en rojo `没给 token,取消。` y abandona la
  configuración.
- Las preguntas 2 y 3 pueden dejarse vacías.
- Si stdin no es un terminal, todo el flujo se salta sin bloquear.

### Las claves que escribe {#写出来的键}

| Lo que introduces | Clave que escribe |
|---|---|
| Token que empieza por `sk-ant-` | `ANTHROPIC_API_KEY` |
| Cualquier otro token | `ANTHROPIC_AUTH_TOKEN` |
| Dirección de gateway no vacía | `ANTHROPIC_BASE_URL` |
| Nombre de modelo no vacío | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` y `ANTHROPIC_DEFAULT_SONNET_MODEL`, las tres a la vez |

La ruta del fichero es `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, y el directorio padre se crea
automáticamente. La escritura es **sobrescritura completa**, saltando las claves con valor vacío;
al terminar hace `chmod 0600` y carga los valores de inmediato: no hace falta reabrir la shell.
La primera línea es siempre un comentario que recuerda no subirlo al control de versiones.

### Segundo filtro: ¿funcionan las credenciales? {#第二道-凭证能不能用}

Una vez completada la configuración, imprime una línea `- 验一下凭证…` y **lanza de verdad una llamada a
la API**.

Detalles de la sonda: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, timeout por defecto de 20
segundos, usando `urllib` de la stdlib, sin dependencias. El modelo se toma en el orden
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. Si hay
`ANTHROPIC_API_KEY` usa la cabecera `x-api-key`; si no, `authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` está puesto a 16 y no a 1 a propósito: en pruebas, los modelos con cadena de pensamiento
forzada ni siquiera caben con el pensamiento y el servidor tarda hasta 30 segundos en responder; con 16
bastan 3.6 segundos.

El resultado de la sonda se trata en tres categorías, y **la diferencia importa**:

| Resultado | Condición | Qué hace flower |
|---|---|---|
| `auth` | HTTP 401 / 403, o directamente no hay credenciales | Imprime `! 凭证被拒:<响应体前 160 字>`, lanza la reconfiguración interactiva y vuelve a validar. En no interactivo, código de salida 1 |
| `config` | HTTP 404, o 400 **y además** el cuerpo dice explícitamente que no se encuentra / no existe (`not_found`, `not found`, `does not exist`, `unknown model`, `no such model` o `invalid model`) | Imprime `! 网关地址或模型名不对:<…>`, igual que arriba |
| `net` | No conecta / timeout / fallo de DNS / fallo de TLS / 5xx | Imprime `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **no te obliga a reconfigurar, arranca directamente** |
| `ok` | Menos de 400, o cualquier caso no concluyente, se deja pasar | Continúa en silencio |

El criterio de `config` está **apretado a propósito**: en el JSON de error de estilo Anthropic aparece
casi con seguridad la palabra `model`, y tomarla como «el nombre del modelo está mal» convertiría un 400
transitorio en un error de configuración y forzaría a reconfigurar; tiene que decir explícitamente «no
se encuentra / no existe» para contar (`env.py:176-182`).

Lo de `net` es deliberado: un bache de red no debe obligarte a reintroducir el token, y además flower
tiene su propio mecanismo de suspensión y reconexión ante caída de red. Si ves «探针没打通», ignóralo y
sigue.

La oportunidad de reconfigurar se da **como mucho una vez**. Si la segunda también falla, sale.

**La sonda solo se lanza en un terminal interactivo.** `ensure_credentials()` retorna directamente sin
hacer esa llamada a la API si se cumple cualquiera de estas condiciones (`cli.py:1413`): quien llama pasó
`probe=False`, está puesta [`FLOWER_NO_PROBE`](config.md#行为开关), o **stdin no es un terminal**
(tubería / CI / pruebas offline). El motivo es que en no interactivo, aunque la sonda detecte un
problema, no se puede arreglar: el único efecto sería «fallar antes», y fallar antes por un **falso
positivo** es peor que no sondear. Si las credenciales son malas de verdad, la ejecución reventará sola,
y ese camino lo recoge la
[reconfiguración automática tras un fallo](#跑挂了之后的自动重配).

### Reconfiguración automática tras un fallo {#跑挂了之后的自动重配}

Cuando el workflow falla, flower toma el mensaje de error del paso que falló y lo compara con una
expresión regular (401, `invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). Si
hay coincidencia y stdin es un terminal, imprime en el acto `! 看起来是凭证不对:<前 120 字>` y lanza la
configuración interactiva; una vez configurado, imprime:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

Y después sale con código 1 en cualquier caso. La ruta `once` no tiene esta parte.

---

## Códigos de salida {#退出码}

| Código | Cuándo |
|---|---|
| `0` | Terminó bien |
| `1` | Todas las salidas voluntarias. El mensaje va a **stderr**, sin traceback. Lista abajo |
| `2` | Error de argumentos de argparse: opción desconocida, falta un posicional, o `-p` con un valor fuera de las choices |
| `130` | Dos Ctrl+C seguidos durante la ejecución. Es un `KeyboardInterrupt` no capturado, **con traceback de Python** |
| Muerto por señal | SIGHUP / SIGTERM: primero escribe en el manifiesto el paso en vuelo, y luego sigue la acción por defecto |

Todos los mensajes del código de salida 1:

| Mensaje | Cuándo |
|---|---|
| `已取消` | Ctrl-C o Ctrl-D en el prompt de arranque |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Directorio nuevo + intro a secas |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 líneas en total) | No interactivo + sin credenciales |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | No interactivo + sonda con resultado `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | No interactivo + sonda con resultado `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` usado en un directorio que no es git |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Petición vacía y el directorio no despierta |
| `在步骤 '<步骤名>' 中止` | Un paso del workflow falla y la política es parar |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, faltan los dos puntos |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | Falla el import del módulo objetivo |
| `'<模块>' 里没有 '<属性>'` | El módulo no tiene ese atributo |

Al terminar (rutas `go` / `run`) se imprime una última línea:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

Ese importe cuenta solo el gasto **de este proceso**, sin incluir la ejecución anterior, aunque el
propio fichero de manifiesto sí acumula entre procesos.

---

## Qué crea en el proyecto {#它在项目里创建了什么}

Dos árboles: `<run_dir>/` (por defecto `./runs/`, relativo al CWD) guarda la contabilidad y las
sesiones; `<workspace>/.flower/` guarda el [banco de trabajo](glossary.md#工作台).

### `runs/` {#runs-目录}

| Ruta | Qué contiene |
|---|---|
| `runs/sessions.db` | SQLite con el transcript completo. Es la base material que permite la [continuidad](glossary.md#接续) |
| `runs/manifest.json` | El [manifiesto de ejecución](glossary.md#运行清单). Array JSON, **acumulado entre procesos**; todas las cifras de las páginas de casos se pueden recalcular aquí |
| `runs/lineage.json` | El [linaje](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Se escribe con reemplazo atómico |
| `runs/aside/` | El Runtime independiente de las consultas al oráculo, con su propio `sessions.db` y `manifest.json`. **Su coste y su linaje no se mezclan con el manifiesto principal** |
| `runs/workbench/` | Solo aparece si se usó `-W` y el workflow no trae banco de trabajo propio (rutas `run` / `once`) |

Campos de cada registro de `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` es la marca de este proceso, con formato `YYYYmmdd-HHMMSS-<6 位 hex>`. La política de volcado es
**añadir sin sobrescribir**: antes de cada escritura se relee el fichero y se deduplica por `run`; las
filas de este proceso se sustituyen por las más recientes y las de otros procesos se dejan tal cual.

El nombre del paso tiene cuatro formas:

| Forma | Cuándo |
|---|---|
| `<步骤名>` | Primer intento |
| `<步骤名>#retry<N>` | Reintento normal |
| `<步骤名>#round<N>` | Devuelto por un veredicto no superado y continuado |
| `<步骤名>·判定#<N>` | El paso del [juez](glossary.md#判定者) |

Cuando lo mata una señal, el paso en vuelo también se escribe, con el campo `error` a
`killed-by-signal`.

**Varios flower en paralelo sobre el mismo directorio**: `manifest.json` es seguro (relectura + fusión
por `run`), pero `lineage.json` se sobrescribe entero, y dos procesos se pisarán mutuamente el linaje de
los pasos con el mismo nombre. Para ir en paralelo, usa un `-r` distinto.

`lineage.json` guarda la ruta absoluta del workspace. Si no cuadra, se hace como si no existiera y se
vuelve **en silencio** a una sesión nueva, sin error: después de copiar el directorio a otro sitio, el
viejo `session_id` tampoco se podría consultar.

### `.flower/` {#flower-目录}

| Ruta | Qué contiene |
|---|---|
| `.flower/scripts/` | Scripts que se van a ejecutar una segunda vez. La primera línea lleva `# desc: 一句话`, y esa frase aparece en el índice |
| `.flower/artifacts/` | Productos largos de más de 2000 caracteres: informes, datos, logs. En la conversación solo aparece la ruta |
| `.flower/notes/` | Registro de decisiones entre pasos |
| `.flower/spill/` | [Volcado](glossary.md#落盘): los resultados de herramientas de más de 4000 caracteres caen aquí, y en el contexto solo queda una línea de puntero más los primeros 400 caracteres. El nombre de fichero son los primeros 16 dígitos del sha256 del contenido más `.txt` |
| `.flower/INDEX.md` | Índice de los directorios anteriores, **inyectado en el prompt de sistema del coordinador** (los subagents no lo heredan) |

La ruta `go` genera siempre estos ficheros bajo `notes/`:

| Fichero | Contenido |
|---|---|
| `notes/需求.md` | El [brief](glossary.md#需求确认书) congelado, con cuatro apartados: objetivo / criterios de aceptación / límites / incógnitas y supuestos |
| `notes/目标.md` | Los objetivos congelados, con dos apartados: objetivo / lista de veredicto |
| `notes/问答记录.md` | Registro por anexado de todas las preguntas y respuestas (con su estado), incluyendo lo que dijiste por iniciativa propia. **No entra en el contexto, es solo archivo** |
| `notes/交接-<步骤名>.md` | El [documento de relevo](glossary.md#交接书) escrito al hacer el relevo; el de la generación anterior se guarda en `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | El `lineage.json`, `需求.md` y `目标.md` archivados por `--new` o `/new`. Es un **movimiento**, no un borrado |

Con `--isolate`, el banco de trabajo se traslada fuera del repositorio:
`<workspace>.parent/.flower-<nombre del workspace>/`. El worktree es la copia privada de cada agente y el
banco de trabajo es la capa compartida entre agentes; lo compartido no puede vivir dentro de una valla
privada. En ese caso, la ruta del banco de trabajo que se le da al modelo es absoluta.
