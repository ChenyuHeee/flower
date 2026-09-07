# Referencia de línea de comandos

Instalado, `flower` es un único ejecutable con 4 subcomandos y 23 flags. Esta página los lista todos:
tipo, valor por defecto y semántica exacta de cada flag, más cómo intervenir con la ejecución en marcha,
qué te pregunta la primera vez, cuáles son los códigos de salida y qué ficheros deja en tus directorios.
Después de leer esta página no hace falta abrir el código fuente.

Código fuente: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcomando | Qué hace | Argumento posicional | Flags propios |
|---|---|---|---|
| `go` | Todo en uno: clarificar la petición → fijar objetivos → repartir el trabajo → veredicto en cada ronda. Es el subcomando por defecto cuando no escribes ninguno | `ask` (opcional) | 11 |
| `run` | Ejecuta un [workflow](glossary.md#流程) escrito por ti | `target` (obligatorio) | 0 |
| `once` | Ejecuta un solo agent una vez, sin workflow y sin veredicto | `prompt` (obligatorio) | 6 |
| `setup` | Configura las credenciales y las escribe en `~/.config/flower/.env` | ninguno | 0 |

Total de flags: 23 = 5 globales + 11 propios de `go` + 6 propios de `once` + `-h/--help`. `run` y `setup`
no tienen flags propios.

---

## Formas de invocación {#调用形式}

Todo el argv de `flower` pasa primero por `_with_default_cmd()`, que completa el subcomando por defecto,
y luego se entrega a argparse (`cli.py:1253-1255`). Por eso `flower "帮我做一个 X"` funciona: se reescribe
como `flower go "帮我做一个 X"`.

Reglas para completar el subcomando por defecto (`cli.py:761-797`):

1. El conjunto de flags globales **se deriva del propio parser principal**, no es una lista hardcodeada.
   Los que tienen `nargs == 0` cuentan como flags puros; el resto, como flags con valor.
2. Se recorre de izquierda a derecha saltando los flags globales. Los que llevan valor se saltan junto con
   su valor, y también se reconoce la forma con `=`, como `--workspace=/tmp`.
3. Se para en el primer token que no es un flag global. Si es `go`, `run` u `once`, se entrega tal cual a
   argparse; **en caso contrario se inserta un `go` delante**, con lo que ese token pasa a ser el texto de
   la petición de `go`.
4. Si se termina el recorrido sin encontrar ningún argumento posicional (argv vacío, o solo flags globales)
   → se añade `go` al final y se entra en la entrada interactiva.
5. Excepción: si el argv contiene `-h` o `--help` se devuelve tal cual y argparse imprime la ayuda.

La constante que se usa para decidir es `_CMDS = ("go", "run", "once")` (`cli.py:758`) — **`setup` no está
en ella**; las consecuencias, en [`setup`](#setup).

### Cómo queda realmente la reescritura {#实际的改写结果}

| Lo que escribes | Cómo se parsea en realidad | Efecto |
|---|---|---|
| `flower` | `["go"]` | Pregunta de forma interactiva «要做什么?» |
| `flower -v` | `["-v", "go"]` | Igual, con verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Arranca directamente |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Los flags globales pueden ir delante |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | La forma con `=` también se reconoce |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Los flags del subcomando pueden ir detrás de la petición |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | También pueden ir delante |
| `flower --new` | `["go", "--new"]` | Solo flags y ninguna petición → entrada interactiva |
| `flower once "hi"` | `["once", "hi"]` | Tal cual |
| `flower run flows:main` | `["run", "flows:main"]` | Tal cual |
| `flower run` | `["run"]` | argparse se queja de que falta `target`; **no** lo toma como petición |
| `flower go run` | `["go", "run"]` | Desambiguación explícita: el texto de la petición es `run` |
| `flower setup` | `["go", "setup"]` | Lo que corre es `go`, con la petición igual a la cadena `setup`; ver [`setup`](#setup) |
| `flower --help` | Tal cual | argparse imprime la ayuda |

Las palabras `run` y `once` **no** pueden usarse directamente como texto de la petición; es una ambigüedad
conservada a propósito (`cli.py:770-771`). Para usarlas como petición, escribe `flower go run`.

### Seis formas válidas de escribirlo {#六种能用的写法}

```bash
flower                                    # 1. Sin nada: pregunta "要做什么?" o "接着上次?"
flower "帮我做一个 X"                       # 2. La petición como argumento posicional
echo "帮我做一个 X" | flower --timeout 0    # 3. La petición por stdin, con pipe
flower once "读一眼这个仓库"                 # 4. Un solo agent
flower run flows.py:main                  # 5. Ejecutar un workflow propio
flower go setup                           # 6. go explícito, con setup como texto de la petición
```

La forma de módulo `python -m flower.cli` equivale a `flower` (`cli.py:1263-1264`).
El wrapper de contenedor `docker/flowerbox` acepta exactamente los mismos argumentos que `flower`.

### La petición por pipe en stdin {#管道喂-stdin}

Cuando `sys.stdin.isatty()` es falso, `ask_for_prompt()` **no imprime la cabecera del prompt** y lee una
línea directamente con `input("> ")` (`cli.py:814-822`). Por eso `echo "..." | flower` funciona.

Pero justo después imprime un aviso, y el hilo de stdin llega inmediatamente a EOF y sale:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

Con pipe hay que usar `--timeout 0`: las preguntas dejan de fingir que esperan 30 minutos, se resuelven
en vacío al instante, y el agent decide por su cuenta y escribe las suposiciones en el apartado
«未知与假设» del brief.

---

## Subcomandos {#子命令}

### `go` {#go}

Texto de ayuda: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1096-1128`).

Argumento posicional `ask`, con `nargs="?"`: si no lo das, entra en la entrada interactiva. Es la puerta de
entrada más usada; `flower "做 X"` pasa por aquí.

Lo que hace (`cli.py:1011-1042`):

1. `ensure_credentials()`: comprueba las credenciales y lanza de verdad una sonda contra la API; ver
   [El flujo de configuración de la primera ejecución](#首次运行的配置流程).
2. Detección de [despertar](glossary.md#唤醒): mira en modo solo lectura si este directorio ya se ha usado,
   sin escribir un solo byte.
3. Si no diste `ask`, imprime el prompt y pregunta; escribir `/new` equivale a `--new`, y luego **vuelve a
   preguntar** la petición.
4. Si es una [continuidad](glossary.md#接续), imprime una línea de banner de despertar.
5. Construye un [workflow](glossary.md#流程) de tres pasos: `确认需求` → `设定目标` → `干活`, con un
   `干活·判定#N` detrás de cada ronda de trabajo. Con `--clarify-only` solo queda el primer paso.
6. Arranca.

El banner de despertar tiene esta pinta (el directorio home dentro de las rutas se sustituye por `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` aparece siempre; `目标 N 条` solo aparece si hay lista de veredicto; `干活上下文 X` requiere
poder consultar en `sessions.db` el contexto de la última ronda de esa [sesión](glossary.md#会话); si no se
encuentra, no se muestra.

!!! warning "`-W` y `-T` se sobrescriben en silencio en la ruta `go`"
    Estos dos flags globales no sirven de nada en `go`: no dan error y no avisan.

    - `-W/--workbench`: el workflow que construye `go` siempre trae su propio
      [banco de trabajo](glossary.md#工作台), y el código toma
      `getattr(wf, "workbench", None) or args.workbench` (`cli.py:859`) — el del propio workflow siempre
      tiene prioridad. Así que el banco de trabajo es siempre `<workspace>/.flower/`
      (con `--isolate`, `<workspace>.parent/.flower-<nombre>/`) y `-W` no lo cambia.
    - `-T/--trim`: `go` usa `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1042`), es decir, la negación
      de `--no-trim`, y **ni siquiera mira `args.trim`**. O sea que en la ruta `go` el
      [recorte](glossary.md#裁剪) está activado por defecto y la única forma de apagarlo es `--no-trim`.

    Estos dos flags solo tienen efecto en `run` (cuando el workflow no trae banco de trabajo propio) y en `once`.

#### Los 11 flags de `go` {#go-的-11-个开关}

| Flag | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `--asks N` | int | `-1` | Cupo de preguntas. `-1` o cualquier negativo = **sin límite**; `0` = no puede preguntar, la primera pregunta da `over_budget`; `N` = cupo duro. Al pasarse, la herramienta rechaza directamente sin bloquear la ejecución |
| `--rounds N` | int | `3` | Tope del **total de rondas** de trabajo, no rondas adicionales. Al final de cada ronda un [juez](glossary.md#判定者) independiente dictamina si «está hecho o no»; si no lo está, lo devuelve y continúa la misma sesión |
| `--no-goal` | flag | `False` | Apaga el [guardián de objetivos](glossary.md#目标看守): no genera `目标.md`, no hace [veredicto](glossary.md#判定), y en cuanto termina el trabajo se da por hecho |
| `--judge-can-run` | flag | `False` | Permite al juez ejecutar comandos. El veredicto es más duro, a cambio de que también puede modificar el workspace |
| `--timeout 秒` | float | `1800.0` | Cuánto esperar a que alguien responda. `0` o negativo = totalmente automático, todas las preguntas se resuelven en vacío **al instante**, sin fingir que esperan. Semántica en [Timeout](#超时) |
| `--isolate` | flag | `False` | Cada [subagent](glossary.md#subagent) recibe su propio git worktree, es decir, [aislamiento](glossary.md#隔离). **Exige que el workspace sea un repositorio git**; si no, código de salida 1. Además mueve el banco de trabajo fuera del repositorio |
| `--window N` | int | ninguno (se deduce del nombre del modelo) | Ventana de contexto del modelo. Si no se da: nombre de modelo que contiene `1m` o que no contiene `haiku` → 1,000,000; que contiene `haiku` → 200,000. Al llegar a `窗口 − 50000` escribe el [documento de handoff](glossary.md#交接书) y hace [handoff](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Apaga el handoff y vuelve al [compact](glossary.md#压缩) que trae el propio SDK |
| `--new` | flag | `False` | No enlazar con la vez anterior. **Mueve** (no borra) el `lineage.json` + `需求.md` + `目标.md` del tramo anterior a `notes/archive/<YYYYmmdd-HHMMSS>/` y empieza de cero |
| `--clarify-only` | flag | `False` | Hace solo la [clarificación previa](../guide/clarify.md), sin seguir con el trabajo: en el workflow queda únicamente el paso `确认需求` |
| `--no-trim` | flag | `False` | Apaga el recorte. En la ruta `go` el recorte está **activado** por defecto; esta es la única forma de apagarlo |

Casos límite de los valores, ninguno da error ni avisa:

- `--rounds 0` y `--rounds 1` son equivalentes: internamente es `retries = max(0, rounds - 1)`, ambos hacen 1 ronda.
- Cualquier negativo en `--asks` significa sin límite, no solo `-1`.
- Cualquier negativo en `--timeout` equivale a `0`, es decir, totalmente automático.
- `--window 0` se **ignora en silencio** (`0` es falsy y ni siquiera se propaga) y se vuelve al valor
  deducido del nombre del modelo. Un negativo sí se propaga, y luego se sube al suelo de `10000`.
- `--clarify-only` sobre un directorio ya clarificado es una **operación vacía**: el paso `确认需求` ve un
  `需求.md` completo y lo salta, y como en el workflow solo está ese paso, no ocurre nada (salvo que el
  contador de despertares sube en 1). Para volver a clarificar hay que combinarlo con `--new`.
- El `--help` de `go` termina diciendo «全局开关(-v/-w/-r/-T)见 `flower --help`», y esa línea
  **se deja fuera `-W`**.

### `run` {#run}

Texto de ayuda: `运行一个 workflow` (`cli.py:1130-1133`).

Argumento posicional `target`, con la forma `módulo:atributo`. Se soportan las dos variantes (`cli.py:831-852`):

```bash
flower run mypkg.flows:build     # import por nombre de módulo
flower run flows.py:build        # ruta de fichero; mete el directorio padre en sys.path e importa por nombre de fichero
```

Si el atributo obtenido es invocable se llama una vez y se toma su valor de retorno como
[workflow](glossary.md#流程); si ya es un objeto workflow, se usa directamente.

**`run` no tiene ningún flag propio**, solo los 5 globales. Por eso `--window`, `--no-handoff` y compañía
toman siempre su valor por defecto en esta ruta (el código tira de `getattr` como respaldo, `cli.py:862-864`).
Para ajustarlos, escribe esos parámetros dentro de tu propio workflow.

### `once` {#once}

Texto de ayuda: `跑一次单 agent` (`cli.py:1135-1145`). El argumento posicional `prompt` es obligatorio.

Construye un `AgentSpec(name="ad-hoc", …)` y lo ejecuta directamente, **sin pasar por `_drive`**. Por eso en
`once` no hay:

- Ctrl-C para interrumpir y decir algo (pulsarlo es un `KeyboardInterrupt` normal y corriente)
- Hilo de respuesta por stdin ni prompt de entrada fijo abajo
- Consultas al oráculo
- Rescate de la contabilidad ante SIGHUP / SIGTERM
- La línea final `总花费 … · 清单 …`
- Guía de reconfiguración automática tras un fallo de credenciales

En el [manifiesto de ejecución](glossary.md#运行清单), el nombre de este paso es siempre `ad-hoc`.

| Flag | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `-i`, `--instructions` | str | vacío | Instrucciones de dominio, [añadidas](glossary.md#叠加) **después** del prompt de sistema nativo de Claude Code, sin sustituirlo |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Lista blanca de herramientas separada por comas. Si no se da, son esas tres herramientas de solo lectura |
| `-p`, `--permission-mode` | str | `default` | Solo admite `default`, `acceptEdits`, `plan` o `bypassPermissions`; con otro valor argparse falla con código de salida 2 |
| `-b`, `--budget` | float | sin tope | Tope de [presupuesto](glossary.md#预算) en dólares; al superarlo, para |
| `--resume SESSION_ID` | str | ninguno | Continúa una sesión ya existente |
| `--fork` | flag | `False` | Bifurca en lugar de continuar; se usa junto con `--resume` |

!!! warning "El tiempo y el coste acumulado que muestra `once` son siempre 0"
    `once` crea una instancia nueva del renderizador con cada evento que recibe (`cli.py:579-581`,
    `cli.py:1060`), y tanto el instante de inicio como el coste acumulado viven en la instancia
    (`cli.py:393-394`). Resultado:

    - El `用时` de la línea final es siempre `0:00`
    - El `累计 $0.00` de la línea de estado es siempre 0, y el `上下文` tampoco acumula nunca

    El coste real de ese paso hay que mirarlo en el campo `cost_usd` de `runs/manifest.json`. Las rutas
    `go` y `run` mantienen una única instancia del renderizador y no tienen este problema.

### `setup` {#setup}

Texto de ayuda: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1147-1149`).
No tiene ningún flag.

Lo que hace: lee el `.env` → decide si ya está configurado → arranca el flujo de configuración interactiva,
con `reason` igual a `重新配置。` o `还没配过凭证。`. El contenido en pantalla está en
[El flujo de configuración de la primera ejecución](#首次运行的配置流程).

!!! warning "Hoy `flower setup` no llega a este subcomando"
    La constante que decide el subcomando por defecto, `_CMDS = ("go", "run", "once")` (`cli.py:758`),
    **se deja fuera `"setup"`**, aunque en el parser `setup` sí está registrado (`cli.py:1147`). Así que
    `flower setup` se reescribe como `flower go setup`: **lo que se ejecuta es el flujo completo de `go`,
    con la cadena `setup` como texto de la petición**; primero valida credenciales, luego pregunta los
    requisitos y después empieza de verdad a repartir trabajo. Con flags globales pasa lo mismo:
    `flower -v setup` → `["-v", "go", "setup"]`.

    **No existe ningún argv que llegue al subcomando `setup`.**

    Para configurar credenciales hoy solo quedan estos dos caminos, y ambos llegan a la misma interfaz
    interactiva:

    - Ejecutar directamente `flower "随便一句诉求"`: si no hay credenciales configuradas, preguntará antes;
    - o escribir a mano `~/.config/flower/.env`, con las claves de [Las claves que escribe](#写出来的键).

    También arrastran a este problema varios textos: el ``跑 `flower setup` 重配。`` que se imprime cuando
    se rechazan las credenciales, y el comentario de la primera línea del `.env`, ``由 `flower setup` 写``,
    apuntan todos a este comando inalcanzable.

---

## Flags globales {#全局开关}

Los 5 flags globales están colgados a la vez del parser principal y de cada subcomando (`cli.py:1071-1087`).
La copia de los subcomandos usa `argparse.SUPPRESS`, así que si no se dan no se escribe el atributo; por eso
**da igual escribirlos antes o después del subcomando**, no se pisan entre sí. El efecto colateral es que no
aparecen en el `--help` de los subcomandos: para verlos hay que ejecutar `flower --help`.

| Flag | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | Directorio de trabajo del agent. Se convierte a ruta absoluta con `resolve()` y se hace `mkdir -p`. El [banco de trabajo](glossary.md#工作台) `.flower/` se crea dentro |
| `-r`, `--run-dir` | str | `runs` | Directorio del [almacén de sesiones](glossary.md#会话存储) y del manifiesto de ejecución. **Relativo al CWD actual, no al workspace** |
| `-v`, `--verbose` | flag | `False` | Imprime más cosas; ver más abajo |
| `-W`, `--workbench` | flag | `False` | Activa el banco de trabajo. **No tiene efecto en `go`**, solo en `run` (cuando el workflow no trae uno propio) y en `once`, y en ese caso el banco de trabajo cae en `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | Al hacer resume, sustituye los resultados de herramienta grandes y antiguos por punteros a fichero, es decir, [recorte](glossary.md#裁剪). **No tiene efecto en `go`**; esa ruta se controla en negativo con `--no-trim` |
| `-h`, `--help` | flag | — | Está en todos los parsers. Si aparece en el argv se salta la reescritura del subcomando por defecto y se imprime la ayuda directamente |

Que `-r/--run-dir` sea relativo al CWD muerde: `flower -w /other/proj "做 X"` crea `runs/` en **el directorio
desde el que escribiste el comando**, mientras que `.flower/` se crea bajo `/other/proj/` — dos estados
separados. Para que estén juntos, da explícitamente `-r /other/proj/runs`.

La ayuda de `-v` dice «显示思考与工具结果», pero el pensamiento del [hilo principal](glossary.md#主线程)
**se muestra por defecto**. Lo que `-v` activa de verdad es:

- El cuerpo de texto de los subagents (por defecto no se muestra, solo sus llamadas a herramientas)
- Los resultados de herramienta normales (por defecto solo se muestran los que fallan)
- Los eventos `prompt`
- Un volcado de la configuración de credenciales efectiva antes de arrancar, con el token enmascarado
  dejando solo los 4 primeros caracteres

Esto último sale por un `print()` pelado: **no pasa por el saneado de salida, no se ajusta el ancho y no
está protegido por el lock de escritura del terminal**; si ejecutas varios `flower` en paralelo, esas líneas
pueden salir entremezcladas.

---

## Cómo hablar con él durante la ejecución {#运行中怎么和它说话}

Una vez arrancada la ejecución, el terminal **está leyendo tu entrada todo el rato**. No hace falta esperar
a que pregunte, ni pulsar nada para entrar en modo entrada: la última línea siempre es la línea en la que
puedes teclear.

### El prompt de entrada fijo abajo {#常驻在最下面的输入提示符}

Hay un hilo daemon `flower-stdin` que lee stdin de principio a fin (`cli.py:655-755`), sondeando con
`select` cada 0.2 segundos en vez de leer bloqueando (así la señal de parada puede despertarlo; en flujos
que no soportan `select`, como en Windows, degrada a lectura bloqueante).

**Lee siempre, no solo cuando hay una pregunta pendiente.** La razón: si solo leyera al preguntar, lo que
tecleases durante las horas de trabajo se quedaría en el búfer del terminal y se comería como respuesta a la
siguiente pregunta — la pregunta quedaría contestada antes de que llegaras a verla.

En pantalla, `_say()` es la única salida: antes de cada escritura borra el prompt y lo vuelve a pintar
después (`cli.py:299-305`), de forma que el prompt nunca queda empujado hacia arriba por la salida de
eventos. El prompt tiene dos textos, que alternan según haya o no una pregunta pendiente:

| Estado | Última línea de la pantalla |
|---|---|
| Con pregunta pendiente | `你的回答 (回车=跳过,让它自己判断) > ` |
| Sin pregunta pendiente | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Dónde va lo que tecleas {#你敲的东西去哪了}

| Lo que escribes | Con pregunta pendiente | Sin pregunta pendiente |
|---|---|---|
| **Línea vacía (intro directo)** | Salta esa pregunta y deja que decida solo | No hace nada |
| **Empieza por `?`** | Consulta al oráculo, ver abajo | Igual |
| **Solo dígitos**, dentro del rango de opciones | Se sustituye por esa opción y se responde | Se trata como texto normal |
| Cualquier otro texto | Se entrega como respuesta al agent que preguntó | Va a la bandeja de entrada, como requisito añadido |
| EOF (Ctrl-D o cierre del pipe) | Rechaza esa pregunta, retira el prompt y el hilo sale | Retira el prompt y el hilo sale |

Al entrar en la bandeja de entrada imprime una línea de acuse:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

Si no hay [brief](glossary.md#需求确认书) donde volcarlo, la segunda mitad pasa a ser
`没有确认书可落盘 —— 它可能活不过下一个步骤`. La bandeja de entrada **no interrumpe** al ejecutor que está
trabajando: se la lleva la próxima vez que consulte la bandeja por iniciativa propia. Esa misma frase se
añade además a `notes/需求.md`; sin volcarla a disco no sobrevive al límite del paso, porque el paso
siguiente es una sesión nueva que solo lee las piezas congeladas.

### Empezar por `?` = consulta al oráculo {#旁路问答}

Una línea que empieza por `?` no se entrega al agent en marcha, sino al [oráculo](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

Levanta un Runtime **independiente**, con `run_dir` igual a `<run_dir>/aside/`, de forma que su coste y su
linaje de sesiones no se mezclan con el `manifest.json` principal. Su rol es de solo lectura, con únicamente
las herramientas `Read`, `Glob` y `Grep`, un máximo de 12 rondas y un tope de coste de **$0.5**. El contexto
que ve son los **60** eventos más recientes (los eventos `thinking` y `prompt` no entran en esa ventana),
cada uno truncado a 200 caracteres, más la descripción de las rutas del banco de trabajo.

Se ejecuta **en paralelo**: la ejecución en marcha no espera ni un segundo. La respuesta tiene esta forma:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

Si falla imprime una línea en rojo, `# 旁路问答失败:<类型>: <消息>`, y **no afecta al flujo principal**.
Al salir espera como mucho **120** segundos a que terminen las consultas al oráculo, y antes de esperar
imprime una línea `(等 N 条旁路问答收尾…)`.

Lo que dice el oráculo no entra en el contexto de esa ejecución: preguntar no la altera, y la respuesta se
descarta en cuanto se ha leído.

!!! warning "El `？` de ancho completo no dispara la consulta al oráculo — los usuarios de IME chino tropiezan"
    La línea de código que decide si es una consulta al oráculo es (`cli.py:733`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Los dos caracteres **son el mismo `?` ASCII de ancho medio** (`0x3f`) — verificado byte a byte. Por
    cómo está escrito, la intención era claramente aceptar a la vez el `?` de ancho medio y el `？` de
    ancho completo (U+FF1F) que produce un IME chino, pero en la práctica quedaron como el mismo carácter.

    Consecuencia: **una línea que empieza por `？` de ancho completo no se toma como pregunta al oráculo**,
    sino que se manda en silencio a la bandeja de entrada como «requisito añadido», y de ahí se anexa a
    `notes/需求.md`. El acuse que ves es `+ 收到`, no `# 旁路`.

    Para preguntar al oráculo **hay que usar el `?` de ancho medio**: cambia el IME a inglés antes de
    escribir, o al menos teclea el primer carácter en ancho medio.

### Qué hay en la pantalla {#屏幕上都是什么}

Los iconos son **siempre ASCII**, no emoji (`cli.py:49-67`). La razón está en un comentario del código: los
emoji junto con caracteres de marco, geométricos y flechas disparan el fallback de glifos del terminal, y
eso ya provocó dos cuelgues de terminal.

| Icono | Significado | Icono | Significado |
|---|---|---|---|
| `=` | Separador de paso | `+` | Hecho / respondido / recibido |
| `~` | Pensando, reintento | `x` | Fallo / error |
| `>` | Reparto de trabajo | `#` | Handoff, oráculo, tarea |
| `*` | Llamada a herramienta | `-` | Línea de estado, elemento de lista |
| `?` | Pregunta | `<-` | Enlace con lo anterior, destino del handoff |
| `!` | Aviso / interrupción | `.` | Saltado |
| `\| ` | Barra vertical de sangrado del subagent | | |

!!! warning "El `❓` y el `↩` de la documentación antigua no existen en el terminal real"
    La documentación temprana usaba `❓` para las preguntas y `↩` para la línea de despertar. **En el
    código nunca fueron esos caracteres**: el icono de pregunta es el `?` de ancho medio, y el icono del
    despertar y del destino del handoff son los dos caracteres ASCII `<-`.

    Así que lo que sale de verdad en el terminal es:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    No `❓ 这个工具……`, ni `↩ 在 ~/proj 接上上次`. Si haces grep en los logs siguiendo la documentación
    antigua, no encontrarás nada.

Los cinco estados de una pregunta, tal como salen en pantalla:

| Estado | Salida en pantalla |
|---|---|
| Preguntada | `  ? <问题>`, seguido de las opciones una a una, `     1) 选项一`, y si hay cupo, `     (还能问 N 次)` |
| Respondida | `  + <答案>` |
| Timeout | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Cupo agotado | `  ! 提问额度用完` |
| La saltaste | `  . 已跳过` |

Cuando `--asks` es sin límite (el valor por defecto), esa última línea de «还能问 N 次» no se muestra.

Cuando el [handoff](glossary.md#换代) termina de escribir el documento, sale un bloque entero:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

Si el documento de handoff degrada, se inserta además una línea en rojo:
`交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

La salida hace además dos cosas que no ves: todas las líneas pasan primero por un saneado que **solo deja
pasar los códigos de color SGR del propio flower**, de modo que las secuencias de borrado de pantalla o
movimiento de cursor que escupan el modelo o las herramientas se descartan enteras; y el ancho se toma como
`max(40, min(columnas del terminal, 110))`, así que en terminales anchos no se ocupa toda la línea, y es a
propósito.

### El prompt de arranque {#起跑时的提示符}

Al ejecutar `flower` a secas (sin petición), pregunta primero. Hay dos textos:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

El segundo solo aparece si en este directorio ya se ha ejecutado antes y el `需求.md` tiene sus cuatro
apartados completos.

Este prompt lee con `input()`, **sin pasar por el parseo de la shell**. Puedes escribir comillas chinas,
espacios y exclamaciones directamente: esa es toda la razón de que exista. zsh, al encontrarse una comilla
derecha china, entra en continuación `dquote>` y parece colgado, cuando en realidad no ha arrancado ni una vez.

- Entrada vacía + primera vez → sale, imprimiendo ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Entrada vacía + despertar → **es válido**, significa «seguir con lo anterior»
- Escribir `/new` → equivale a `--new`: archiva el tramo anterior y **vuelve a preguntar** la petición
- Ctrl-C / Ctrl-D → sale, imprimiendo `已取消`

### Timeout {#超时}

`--timeout` es un float en segundos, con valor por defecto `1800.0`. Tres casos:

| Valor | Comportamiento |
|---|---|
| `> 0` | Espera esos segundos. Al agotarse, la pregunta se liquida como `timeout` y el agent decide por su cuenta |
| `0` o negativo | **Totalmente automático**. La pregunta no entra en la cola de espera, no emite evento `asked`, no aparece en pantalla y se liquida como `timeout` al instante |
| Esperar para siempre | **No se puede desde la línea de comandos**. Internamente sí existe «esperar para siempre», pero `--timeout` es float y tiene valor por defecto, así que no hay forma de producirlo. El máximo es dar un número de segundos muy grande |

`--timeout 0` y `--timeout -1` son completamente equivalentes. Es lo que se usa con pipe, en CI y en
ejecuciones desatendidas.

Cuando una pregunta no obtiene respuesta, el resultado de herramienta que se devuelve al modelo es un texto
fijo, de cuatro tipos:

| Resultado | Texto devuelto al modelo |
|---|---|
| Cupo agotado | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| La saltaste | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| Pregunta vacía | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**El Ctrl-C tiene semánticas completamente distintas en dos sitios.**

**Pulsado en el prompt de arranque `> `**: sale del programa directamente, imprimiendo `已取消`.

**Pulsado con la ejecución en marcha**: interrumpe la ronda actual y te da una oportunidad de hablar:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Pulsar intro aquí significa interrumpir sin decir nada y seguir. Si en ese momento había preguntas
pendientes, se imprime además una línea `  (有 N 个提问还等着,打断不影响它们)`.

**Pulsar Ctrl+C otra vez sale de verdad**, y como `KeyboardInterrupt` sin capturar: en pantalla verás un
traceback de Python, no una salida limpia.

La interrupción es cooperativa: corta limpiamente en un límite de mensaje, sin cancelar tareas a la fuerza.
**No cuenta como un intento fallido** y no consume reintentos. Al continuar se adjunta una explicación que
le dice al modelo que «las llamadas a herramienta en vuelo que devuelven interrupted son un efecto normal de
la interrupción, no un fallo del entorno».

Este Ctrl-C personalizado solo se instala cuando `sys.stdin.isatty()` (`cli.py:918`). Al ejecutar con pipe se
mantiene el comportamiento por defecto de Python, es decir, sale a la primera. La ruta `once` no pasa por
aquí, así que el Ctrl-C en `once` también sale a la primera.

### SIGHUP / SIGTERM {#sighup-sigterm}

Las rutas `go` y `run` instalan manejadores tanto para `SIGHUP` como para `SIGTERM`: primero escriben en
`manifest.json` también **el paso que estaba en vuelo**, marcado como `killed-by-signal`, y después
restauran la acción por defecto y se van de verdad.

El origen: cuando el terminal se cae, el kernel envía SIGHUP, cuya acción por defecto termina el proceso sin
más, con lo que el `finally` no corre, el manifiesto no se escribe y la contabilidad de esa ejecución se
pierde. Si no es el hilo principal del sistema operativo, o la plataforma no lo soporta, se salta en silencio.

---

## El flujo de configuración de la primera ejecución {#首次运行的配置流程}

Las tres puertas de entrada, `go`, `run` y `once`, llaman al principio a `ensure_credentials()`
(`cli.py:1213-1244`), que tiene **dos filtros**.

### Primer filtro: si hay credenciales {#第一道-有没有凭证}

Busca las credenciales por orden de prioridad. Si no encuentra ni `ANTHROPIC_API_KEY` ni
`ANTHROPIC_AUTH_TOKEN`, arranca la configuración interactiva; si no es interactivo (stdin no es un terminal)
no bloquea: imprime este bloque y sale:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Ese texto no cuadra con la implementación en dos puntos: el `flower setup` de la segunda línea hoy no se
alcanza (ver [`setup`](#setup)); y la cuarta línea **dice lo contrario que el código** — flower sí toma el
bloque `env` de `~/.claude/settings.json` y de `settings.local.json` como **último nivel de respaldo**,
tomando prestadas solo 9 claves de credenciales, sin apropiarse de ningún otro ajuste. El sitio que imprime
esa línea es `env.py:192` (la función `check_credentials()` se define en `env.py:184`), mientras que lo que
lee de verdad esos dos ficheros está en `env.py:56-75` y `:109-111`; anotado en
[issue #13](https://github.com/ChenyuHeee/flower/issues/13). **Manda el código: sí los lee.** El orden
completo de búsqueda y esas 9 claves están en la [referencia de configuración](config.md#借用).

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

- La pregunta 1 es **obligatoria**. Si la dejas vacía, imprime en rojo `没给 token,取消。` y abandona la configuración.
- Las preguntas 2 y 3 pueden dejarse vacías.
- Si stdin no es un terminal, todo el flujo se salta directamente, sin bloquear.

### Las claves que escribe {#写出来的键}

| Lo que introduces | La clave que se escribe |
|---|---|
| Token que empieza por `sk-ant-` | `ANTHROPIC_API_KEY` |
| Cualquier otro token | `ANTHROPIC_AUTH_TOKEN` |
| Dirección de gateway no vacía | `ANTHROPIC_BASE_URL` |
| Nombre de modelo no vacío | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` y `ANTHROPIC_DEFAULT_SONNET_MODEL`, las tres a la vez |

La ruta del fichero es `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, y el directorio padre se crea
automáticamente. La escritura es **sobrescritura completa**, saltando las claves con valor vacío; al
terminar hace `chmod 0600` y carga los valores inmediatamente — no hace falta reabrir la shell. La primera
línea es siempre un comentario que recuerda no subir el fichero al control de versiones.

### Segundo filtro: si las credenciales sirven {#第二道-凭证能不能用}

Una vez completada la configuración, imprime una línea `- 验一下凭证…` y **lanza una llamada real a la API**.

Detalles de la sonda: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, timeout por defecto de 20 segundos,
usando el `urllib` de la stdlib para no meter dependencias. El modelo se toma en el orden
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. Si hay
`ANTHROPIC_API_KEY` usa la cabecera `x-api-key`; si no, `authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` se puso a 16 y no a 1 a propósito: en pruebas, los modelos con cadena de pensamiento forzada no
tienen ni sitio para pensar y el servidor tarda hasta 30 segundos en responder; con 16 bastan 3.6 segundos.

Las conclusiones de la sonda se tratan en tres grupos, y **la diferencia importa**:

| Conclusión | Cuándo se dispara | Qué hace flower |
|---|---|---|
| `auth` | HTTP 401 / 403, o directamente no hay credenciales | Imprime `! 凭证被拒:<los primeros 160 caracteres del cuerpo>`, arranca la reconfiguración interactiva y vuelve a validar. Si no es interactivo, código de salida 1 |
| `config` | HTTP 404, o 400 con la palabra `model` en el cuerpo | Imprime `! 网关地址或模型名不对:<…>`, igual que arriba |
| `net` | Sin conexión / timeout / fallo de DNS / fallo de TLS / 5xx | Imprime `  (探针没打通:<los primeros 80 caracteres> —— 当作网络问题,照常开跑)` y **no te hace reconfigurar: arranca directamente** |
| `ok` | Menos de 400, o cualquier caso que no se pueda decidir | Continúa en silencio |

Lo de `net` es intencionado: un temblor de red no debería obligarte a reintroducir el token, y flower ya
tiene mecanismo para quedarse suspendido y reconectar cuando se cae la red. Si ves «探针没打通», ignóralo y
sigue.

La oportunidad de reconfigurar se da **como mucho una vez**. Si falla la segunda, sale.

### Reconfiguración automática después de un fallo {#跑挂了之后的自动重配}

Cuando el workflow falla, flower toma el mensaje de error del paso fallido y lo compara con una expresión
regular (401, `invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). Si hay coincidencia
y stdin es un terminal, imprime en el acto `! 看起来是凭证不对:<los primeros 120 caracteres>` y arranca la
configuración interactiva; una vez configurado imprime:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

Y en cualquier caso sale con código 1. La ruta `once` no tiene esta parte.

---

## Códigos de salida {#退出码}

| Código | Cuándo |
|---|---|
| `0` | Terminó con normalidad |
| `1` | Todas las salidas deliberadas. El mensaje va a **stderr**, sin traceback. Lista completa abajo |
| `2` | Error de argumentos de argparse: flag desconocido, falta un posicional, o `-p` con un valor fuera de choices |
| `130` | Dos Ctrl+C seguidos con la ejecución en marcha. Es un `KeyboardInterrupt` sin capturar, **con traceback de Python** |
| Muerto por señal | SIGHUP / SIGTERM: primero escribe en el manifiesto el paso en vuelo, y luego se va con la acción por defecto |

Todos los mensajes del código de salida 1:

| Mensaje | Cuándo |
|---|---|
| `已取消` | Ctrl-C o Ctrl-D en el prompt de arranque |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Directorio nuevo + intro directo |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 líneas en total) | No interactivo + sin credenciales |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | No interactivo + la sonda dictamina `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | No interactivo + la sonda dictamina `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` usado en un directorio que no es git |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Petición vacía y el directorio no despierta |
| `在步骤 '<步骤名>' 中止` | Un paso del workflow falla y la política es parar |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, sin los dos puntos |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | Falla el import del módulo objetivo |
| `'<模块>' 里没有 '<属性>'` | No se encuentra ese atributo en el módulo |

Al terminar (rutas `go` / `run`) se imprime una última línea:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

Ese importe cuenta solo el gasto de **este proceso**, no el de la ejecución anterior — aunque el propio
fichero de manifiesto sí acumula entre procesos.

---

## Qué crea dentro del proyecto {#它在项目里创建了什么}

Dos árboles: `<run_dir>/` (por defecto `./runs/`, relativo al CWD) guarda la contabilidad y las sesiones;
`<workspace>/.flower/` guarda el [banco de trabajo](glossary.md#工作台).

### `runs/` {#runs-目录}

| Ruta | Qué guarda |
|---|---|
| `runs/sessions.db` | SQLite con el transcript completo. Es la base material que hace posible la [continuidad](glossary.md#接续) |
| `runs/manifest.json` | El [manifiesto de ejecución](glossary.md#运行清单). Un array JSON que **acumula entre procesos**; todas las cifras de la página de casos se pueden recalcular aquí |
| `runs/lineage.json` | El [linaje](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Se escribe con reemplazo atómico |
| `runs/aside/` | Runtime independiente de las consultas al oráculo, con su propio `sessions.db` y su propio `manifest.json`. **Su coste y su linaje no se mezclan con el manifiesto principal** |
| `runs/workbench/` | Solo aparece si usaste `-W` y el workflow no trae banco de trabajo propio (rutas `run` / `once`) |

Campos de cada registro de `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` es la marca de este proceso, con formato `YYYYmmdd-HHMMSS-<6 dígitos hex>`. La política de escritura
es **añadir sin sobrescribir**: antes de cada escritura relee el fichero y deduplica por `run`, sustituyendo
las filas de este proceso por las más recientes y dejando intactas las de otros procesos.

Los nombres de paso tienen cuatro formas:

| Forma | Cuándo |
|---|---|
| `<步骤名>` | Primer intento |
| `<步骤名>#retry<N>` | Reintento normal |
| `<步骤名>#round<N>` | El veredicto no pasó y se devolvió para seguir |
| `<步骤名>·判定#<N>` | El paso del [juez](glossary.md#判定者) |

Al morir por señal, el paso en vuelo también se escribe, con el campo `error` igual a `killed-by-signal`.

**Varios flower en paralelo sobre el mismo directorio**: `manifest.json` es seguro (relectura + fusión por
`run`), pero `lineage.json` se sobrescribe entero, así que dos procesos se pisarán mutuamente el linaje de
los pasos con el mismo nombre. Si vas a paralelizar, usa distintos `-r`.

En `lineage.json` se guarda la ruta absoluta del workspace. Si no coincide se hace como si no existiera y se
vuelve **en silencio** a una sesión nueva, sin error: si el directorio se ha copiado a otro sitio, los viejos
`session_id` tampoco se podrían consultar.

### `.flower/` {#flower-目录}

| Ruta | Qué guarda |
|---|---|
| `.flower/scripts/` | Scripts que habrá que volver a ejecutar. La primera línea lleva `# desc: 一句话`, y esa frase aparece en el índice |
| `.flower/artifacts/` | Producciones largas, de más de 2000 caracteres: informes, datos, logs. En la conversación solo aparece la ruta |
| `.flower/notes/` | Registro de decisiones entre pasos |
| `.flower/spill/` | [Volcado](glossary.md#落盘): los resultados de herramienta de más de 4000 caracteres caen aquí, y en el contexto solo queda una línea de puntero más los primeros 400 caracteres. El nombre de fichero son los primeros 16 dígitos del sha256 del contenido más `.txt` |
| `.flower/INDEX.md` | Índice de los directorios anteriores, **inyectado en el prompt de sistema del coordinador** (los subagents no lo heredan) |

La ruta `go` genera siempre estos ficheros bajo `notes/`:

| Fichero | Contenido |
|---|---|
| `notes/需求.md` | El [brief](glossary.md#需求确认书) congelado, con cuatro apartados: objetivo / criterios de aceptación / límites / incógnitas y suposiciones |
| `notes/目标.md` | Los objetivos congelados, con dos apartados: objetivo / lista de veredicto |
| `notes/问答记录.md` | Registro acumulativo de todas las preguntas y respuestas (con su estado), incluyendo lo que dijiste por iniciativa propia. **No entra en el contexto, es solo archivo** |
| `notes/交接-<步骤名>.md` | El [documento de handoff](glossary.md#交接书) que se escribe al hacer el relevo; la generación anterior se recoge en `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | El `lineage.json`, `需求.md` y `目标.md` archivados por `--new` o `/new`. Es un **movimiento**, no un borrado |

Con `--isolate`, el banco de trabajo se mueve fuera del repositorio:
`<workspace>.parent/.flower-<nombre del workspace>/`. El worktree es la copia privada de cada agent, y el
banco de trabajo es la capa compartida entre agents: lo compartido no puede vivir dentro de un cercado
privado. En ese caso, la ruta del banco de trabajo que se le da al modelo es absoluta.
