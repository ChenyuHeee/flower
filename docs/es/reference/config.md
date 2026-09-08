# Configuración

flower no tiene formato de fichero de configuración, ni ningún subcomando de configuración que llegue a ejecutarse de verdad — toda la configuración son **variables de entorno** más
**ficheros `.env`**, más un puñado de objetos de política que solo se pueden pasar desde Python. Esta página reúne en un solo sitio lo que está repartido por cinco lugares:
cada variable, en qué orden se buscan las credenciales, qué sintaxis acepta `.env`, qué aísla realmente `setting_sources=[]`,
qué deja una ejecución en disco, qué tira cada una de las tres capas del almacén de sesiones y cómo se espera cuando se cae la red. La terminología sigue el [glosario](glossary.md).

| Qué quieres saber | Dónde |
|---|---|
| Qué variables de entorno reconoce flower | [Tabla completa de variables de entorno](#环境变量) |
| De dónde sale realmente mi token | [Prioridad de búsqueda de credenciales](#凭证查找优先级) |
| Por qué esa línea de mi `.env` no hace nada | [Reglas de parseo de `.env`](#env-解析) |
| Qué llevarme al cambiar de máquina | [El precio de la portabilidad](#可移植性) |
| Qué hay dentro de `.flower/` y `runs/` | [Disposición en disco](#磁盘布局) |
| Qué mensajes no se le devuelven al modelo | [Las tres capas del almacén de sesiones](#会话存储) |
| Qué está esperando cuando se cae la red | [Resiliencia ante caídas de red](#韧性) |

## Tabla completa de variables de entorno {#环境变量}

Cinco grupos: credenciales y endpoint que flower lee directamente, selección de modelo, búsqueda de rutas, interruptores de comportamiento, y las que flower **escribe hacia** el subproceso del agente.
Este último grupo no lo configuras tú — si lo haces, se sobrescribe.

### Credenciales y endpoint {#凭证变量}

| Variable | Función | Por defecto | Requerido | Origen |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Key oficial de Anthropic. Si existe, la petición va con cabecera `x-api-key` | ninguno | **una de las dos, obligatorio** junto a `ANTHROPIC_AUTH_TOKEN` | `env.py:28`, `:146`, `:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Token emitido por una pasarela. Sin `ANTHROPIC_API_KEY`, se usa `authorization: Bearer` | ninguno | ídem | `env.py:28`, `:147`, `:159-160` |
| `ANTHROPIC_BASE_URL` | Raíz del endpoint de la API. Una pasarela de terceros pone aquí su propia dirección, **sin `/v1`** — la sonda compone `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | No | `env.py:151`, `:162`, `:210`; `resilience.py:70` |

Si no hay ninguna de las dos (o ambas son cadena vacía), `check_credentials()` devuelve ese error de cuatro líneas y `Runtime.__init__`
lanza `RuntimeError` (`env.py:184-194`; `runtime.py:156-158`).

### Selección de modelo {#模型变量}

flower solo lee tres de ellas para sus propias decisiones; el resto se cargan y se pasan tal cual al SDK.

| Variable | Función | Por defecto | Requerido | Origen |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | Nombre del modelo principal. Determina además el valor por defecto de la ventana de [relevo](glossary.md#换代): si el nombre lleva `1m` o no lleva `haiku` → 1 millón; si lleva `haiku` → 200 mil | ninguno (lo decide el extremo) | No | `env.py:153`; `agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Mapeo del modelo para el nivel opus. Si `ANTHROPIC_MODEL` está vacío, la decisión de ventana cae aquí | ninguno | No | `agent.py:78`; `cli.py:1384` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Mapeo del modelo para el nivel sonnet. flower no lo lee; solo lo carga y lo toma prestado | ninguno | No | `env.py:34`; `cli.py:1385` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Mapeo del modelo para el nivel haiku. **La sonda de credenciales lo prefiere** | la sonda cae a `ANTHROPIC_MODEL` y luego a `claude-3-5-haiku-20241022` | No | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Qué modelo usan los [subagent](glossary.md#subagent). flower no la interpreta; la consume el SDK | ninguno | No | `env.py:35`; `.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Nivel de razonamiento. Ídem: solo se carga, no se interpreta | ninguno | No | `env.py:35` |

Si en `flower setup` pones un nombre de modelo, se escriben `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` y
`ANTHROPIC_DEFAULT_SONNET_MODEL` **las tres a la vez** (`cli.py:1383-1385`).

### Rutas y búsqueda {#路径变量}

| Variable | Función | Por defecto | Requerido | Origen |
|---|---|---|---|---|
| `FLOWER_ENV` | Indica la ruta de un fichero `.env` que va **antes** de todos los demás | ninguno | No | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Determina la ubicación del fichero global de credenciales `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | No | `env.py:41-42` |
| `HOME` | Origen de `Path.home()`; de ahí salen tanto `~/.config` como `~/.claude` | lo da el sistema | No | `env.py:41`, `:67` |

### Interruptores de comportamiento {#行为开关}

Los dos son vías de escape: lo normal es no ponerlos; se ponen para que flower haga una cosa menos. **Cualquier valor no vacío las activa**,
el valor en sí no se interpreta (`update.py:121`; `cli.py:1413`).

| Variable | Función | Por defecto | Requerido | Origen |
|---|---|---|---|---|
| `FLOWER_NO_UPDATE` | Desactiva la [actualización automática](../getting-started/install.md#自动更新). Si no está puesta, un flower instalado con pip / pipx / uv lanza al arrancar un hilo en segundo plano que comprueba si hay versión nueva y la instala; **solo surte efecto en la siguiente ejecución de `flower`**; como mucho una comprobación cada 24 horas, con la marca de tiempo en `~/.config/flower/.update` | ninguno (actualización automática activada) | No | `update.py:32-33`, `:121-124` |
| `FLOWER_NO_PROBE` | Salta la [sonda de credenciales](cli.md#第二道-凭证能不能用) del arranque. En no interactivo (pipe / CI / stdin redirigido) no se sondea de todas formas; esta variable es la salida para terminales interactivas | ninguno (en interactivo sí sondea) | No | `cli.py:1413` |

Un flower ejecutado desde el código fuente en git no se ve afectado por la actualización automática; `FLOWER_NO_UPDATE` es un no-op para él — el paso del comando de actualización
detecta que hay un `.git` en el repositorio y devuelve `None` directamente (`update.py:83-87`).

### Las que flower escribe hacia el subproceso del agente {#写出的变量}

Estas tres las genera `CompactPolicy.env()` y se meten en `ClaudeAgentOptions.env` (`agent.py:48-58`, `:241-245`),
y controlan el [compact](glossary.md#压缩) integrado del harness. **Ponerlas en tu shell no sirve de nada** —
lo que manda es la copia que flower pasa al subproceso.

| Variable | Función | Por defecto | Requerido | Origen |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` desactiva el compact automático. Con el [relevo](glossary.md#换代) activo **se escribe siempre** — con los dos mecanismos corriendo a la vez no se distingue quién provocó la bajada de contexto | el relevo está activo por defecto, así que en la práctica es siempre `1` | No (lo escribe flower) | `agent.py:51`; `runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` desactiva también `/compact`. Solo se escribe con `CompactPolicy(mode="off")` | no se escribe | No (lo escribe flower) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Ventana del compact automático (tokens). Solo se escribe con `CompactPolicy(window=N)` | no se escribe | No (lo escribe flower) | `agent.py:56-57` |

### Las que lee el wrapper de contenedor {#容器变量}

Estas dos no las lee flower en sí, sino el wrapper de shell `docker/flowerbox`. Uso completo en [despliegue](deploy.md).

| Variable | Función | Por defecto | Requerido | Origen |
|---|---|---|---|---|
| `FLOWER_HOME` | Dónde buscar el `.env` que se pasa a `--env-file` | el directorio padre de la ubicación del propio script | No | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Qué imagen usar | `flower-box` | No | `docker/flowerbox:13` |

**Las claves de `.env` no se limitan a las de arriba.** El parser carga en `os.environ` **todas** las líneas `k=v`, sin lista blanca
(`env.py:30`, `:102-107`). El `KNOWN` formado por esas 9 claves de credenciales solo actúa en dos sitios: la lista blanca al tomar prestada la
configuración de `~/.claude` (`env.py:72`), y el conjunto de campos que imprime `describe()` al arrancar con `-v` (`env.py:205`).

## Prioridad de búsqueda de credenciales {#凭证查找优先级}

Cuando a `load_dotenv()` no se le pasa ruta, lee en el siguiente orden **todos los ficheros que existan**
(`env.py:45-53`, `:78-112`):

1. **Variables de entorno del proceso** — siempre las de mayor prioridad. Ningún `.env` puede sobreescribir un valor ya exportado. (`env.py:91`)
2. **El fichero al que apunta `$FLOWER_ENV`** — solo existe si la has puesto. (`env.py:48-49`)
3. **`$PWD/.env`** — el directorio de trabajo actual. Según a qué proyecto hagas `cd`, se lee el suyo. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — la ubicación global, una por usuario; es la que escribe `flower setup`. (`env.py:51`, `:39-42`)
5. **El `.env` de la raíz del repositorio de código** — tres niveles por encima de `flower/core/env.py`. Solo existe si se ejecuta desde el código fuente; un flower instalado con pip / pipx / uv vive en site-packages y no tiene esta entrada. (`env.py:52`)
6. **El bloque `env` de `~/.claude/settings.json`, y después el de `~/.claude/settings.local.json`** — el último recurso, **solo esas 9 claves de credenciales**. (`env.py:56-75`, `:109-111`)

**Qué fichero gana**: la entrada 3 (`.env` del proyecto) gana a la 4 (`.env` global), la 4 gana a la 5 (`.env` de la raíz del repositorio),
las tres ganan a la 6 (la configuración de Claude Code), y todas pierden frente a la 1 (el entorno del proceso).

La implementación es "**una clave que ya tiene valor no se sobrescribe**" (`env.py:90-93`): los primeros ocupan las claves y los siguientes solo rellenan huecos.
Así que la prioridad **se calcula por clave, no por fichero** — si el `.env` del proyecto solo define `ANTHROPIC_BASE_URL`,
el token puede seguir viniendo del global. El primer valor con que aparece una clave es el definitivo.

La entrada 6 solo se activa en la **búsqueda automática**. Si se da una ruta explícita (`load_dotenv("/path/to/.env")`), se lee ese único fichero
y no se aplica ningún fallback (`env.py:86-87`, `:109`).

### Entrada 6: tomar prestado el token de Claude Code {#借用}

Se leen en orden `~/.claude/settings.json` y `~/.claude/settings.local.json`, se coge el dict `data["env"]`
y de ahí se extraen estas 9 claves (`env.py:31-36`, `:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

Si el fichero no existe, no se puede leer, o no es JSON válido (`OSError` / `ValueError`), se devuelve un dict vacío y se sigue adelante —
**que falle el fallback no debe llevarse por delante esta ejecución** (`env.py:62-63`, `:66-69`).

La postura en el código es: lo único que se toma prestado es "dónde encontrar el token"; nada más de settings.json (reglas de permisos, hook,
ajustes de modelo) se hereda, así que esto no contradice la promesa de portabilidad de `setting_sources=[]` (`env.py:17-19`, `:59-61`).
`install.sh:77` lo anuncia como una característica: quien ya tenga Claude Code configurado en su máquina no verá ni la pantalla de configuración.

!!! warning "El texto de error del producto dice lo contrario de lo que hace"
    Cuando no se encuentra ninguna credencial, la última línea del error que imprime flower es:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, esa frase está en `:192`; la misma afirmación aparece también en `.env.example:2`, `env.py:3-4`,
    `agent.py:10-12`.) **Manda el código: sí lo lee.** `env.py:56-75` más `:109-111` leen explícitamente esos dos ficheros,
    e `install.sh:77` lo vende como argumento. Ese texto es hoy engañoso —
    en una máquina donde hayas configurado Claude Code, es muy probable que tu token venga precisamente de ahí.

## Reglas de parseo de `.env` {#env-解析}

Las reglas son tan cortas que se memorizan (`env.py:95-107`, 13 líneas): `strip` línea a línea; se saltan las líneas vacías, las que empiezan por `#`
y las que no contienen `=`; el resto se parte por el **primer** `=` en clave y valor, se hace `strip` a cada lado, y al valor se le aplica además
`.strip("'\"")` — se quitan las comillas simples o dobles del principio y del final, **sin exigir que estén emparejadas**.

**Se reconoce esto**:

| Forma | Resultado |
|---|---|
| `KEY=VALUE` | Normal |
| `KEY = VALUE` | Normal — los espacios a ambos lados del igual se eliminan con strip |
| `KEY="VALUE"` / `KEY='VALUE'` | Normal — se quitan las comillas de los extremos |
| `KEY=a=b` | el valor es `a=b` — se parte por el primer `=`, los demás iguales quedan tal cual en el valor |
| `# comentario` | línea entera saltada |
| Línea vacía | saltada |

**Esto no se reconoce**. No da error: simplemente obtienes en silencio un valor inesperado:

| Forma | Resultado real |
|---|---|
| `export KEY=VALUE` | la clave pasa a ser `export KEY`; `KEY` en sí sigue sin valor |
| `KEY=value # nota` | el valor es `value # nota` — los comentarios de fin de línea no se eliminan |
| `KEY=$OTHER` | el literal `$OTHER`, no hay interpolación de variables |
| Valores multilínea (entrecomillados a varias líneas) | se procesa línea a línea; la segunda no contiene `=` y se salta entera |

**Un valor vacío ocupa la clave.** Si `ANTHROPIC_AUTH_TOKEN=` aparece en un fichero de prioridad alta, `take()` ejecuta
`os.environ["ANTHROPIC_AUTH_TOKEN"] = ""`, y entonces los ficheros posteriores no pueden rellenarla porque "la clave ya existe"
(`env.py:90-93`); mientras que `check_credentials()` evalúa por valor de verdad, y la cadena vacía cuenta igualmente como no configurada (`env.py:186`).
**El resultado es que no tienes ni credencial ni fallback.** Si no quieres una clave, borra la línea entera; no dejes una vacía.

## El precio de la portabilidad {#可移植性}

Todo el mecanismo es esa línea de `build_options()` (`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` es el valor por defecto de `Runtime`, y **no hay ningún interruptor de línea de comandos para desactivarlo** — solo se puede desactivar desde la API de Python
escribiendo `Runtime(portable=False)`, lo que lo convierte en `["project"]`, es decir, leer el `.claude/` del proyecto.

### Qué queda aislado {#被隔绝的东西}

| Qué queda aislado | Consecuencia |
|---|---|
| Los ajustes de `~/.claude/` de la máquina anfitriona | Las reglas de permisos, hook y ajustes de modelo de ahí no surten efecto. **Las credenciales son la única excepción**, ver [préstamo](#借用) |
| El `.claude/` del proyecto | Ídem; solo se lee con `portable=False` |

Las capacidades de dominio no van por esta vía — se distribuyen con el repositorio y se cargan mediante `plugins=[{"type": "local", "path": PLUGIN_DIR}]`
(`agent.py:26`, `:210-212`), ver [despliegue](deploy.md). Las instrucciones de dominio se **añaden** después del prompt de sistema nativo de Claude Code,
no lo sustituyen (`agent.py:198-202`), así que la especialización no se paga con pérdida de capacidad general.

### Qué llevarse al cambiar de máquina {#换台机器要带什么}

- **Credenciales: un fichero**. Basta con copiar `~/.config/flower/.env`, o volver a configurarlo en la máquina nueva.
  Si no lo llevas, no arranca nada — no se hereda nada automáticamente.
- **Estado de continuidad: el directorio entero**. `runs/` (almacén de sesiones, manifiesto, linaje) y `.flower/` (workbench).
- **Pero las rutas tienen que coincidir**. `lineage.json` guarda la ruta absoluta del espacio de trabajo; si no coincide se ignora y se cae en silencio a una sesión nueva,
  **sin error** (`lineage.py:65-66`). La razón es que el SDK deriva el `project_key` de la ruta del espacio de trabajo
  (`/`, `_` y `.` se sustituyen por `-`, `runtime.py:40-41`): si el directorio cambia de sitio, el `session_id` antiguo ya no se encuentra.

## Disposición en disco {#磁盘布局}

Una ejecución de flower escribe dos árboles: `<run_dir>/` guarda la contabilidad y las sesiones, y `<workspace>/.flower/` guarda el [workbench](glossary.md#工作台).
Por defecto ambos cuelgan del directorio actual, pero **su base no es la misma**.

!!! warning "`runs/` sigue al directorio actual, no a `-w`"
    `-r/--run-dir` es `"runs"` por defecto, y lo que `Runtime` hace con él es `Path(run_dir).resolve()`
    (`runtime.py:93-94`) — relativo al **directorio de trabajo actual**, no al espacio de trabajo indicado con `-w`.
    Si ejecutas `flower -w /path/to/proj` desde `~`, el almacén de sesiones acaba en `~/runs/`, no dentro del proyecto.

### `<run_dir>/` — por defecto `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite, transcript completo (incluida la propia de cada subagent)
  manifest.json      manifiesto de ejecución: session_id / coste / reintentos / motivo de fallo de cada paso, acumulado entre procesos
  lineage.json       linaje: nombre de paso → session_id; volver a ejecutar en el mismo directorio se engancha gracias a él
  aside/             Runtime independiente para las preguntas al oráculo, con su propio sessions.db + manifest.json
  workbench/         solo por la vía run / once y si se pasa -W
```

| Ruta | Contenido | Origen |
|---|---|---|
| `runs/sessions.db` | Transcript completo. Lo escribe `PruningSessionStore`; las tres capas de política están [más abajo](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | Array JSON, el [manifiesto de ejecución](glossary.md#运行清单) **acumulado entre procesos**. Campos en la tabla siguiente | `runtime.py:532-533`, `:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Se escribe primero un `.tmp` y luego `replace`: sustitución atómica | `lineage.py:31`, `:87-97` |
| `runs/aside/` | Runtime independiente del [oráculo](glossary.md#旁路顾问). **Su coste y su linaje no se mezclan con el manifiesto principal** | `cli.py:741-743` |
| `runs/workbench/` | Ubicación por defecto del workbench con `Runtime(workbench=True)`, fuera del espacio de trabajo. La vía `go` no lo usa | `runtime.py:148-151` |

Cada fila de `manifest.json` es un `asdict(StepResult)` más dos parches (`runtime.py:44-71`, `:579-582`):

| Campo | Tipo | Significado |
|---|---|---|
| `step` | `str` | Nombre del paso. Cuatro formas: `<名>`, `<名>#round<N>` (devuelto para rehacer), `<名>#retry<N>` (reintento normal), `<名>·判定#<N>` ([juez](glossary.md#判定者)) |
| `session_id` | `str \| None` | La [sesión](glossary.md#会话) que quedó viva al final de este paso |
| `ok` | `bool` | Si salió bien o no |
| `cost_usd` | `float` | Cuánto costó este paso |
| `num_turns` | `int` | Cuántos turnos se dieron |
| `text` | `str` | La respuesta final de este paso |
| `error` | `str \| None` | Motivo del fallo. Si lo mató SIGHUP / SIGTERM es `killed-by-signal` (`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | Segundos epoch |
| `attempts` | `int` | Número real de intentos. `>1` significa que hubo reintentos |
| `errors` | `list[str]` | Motivos de todos los fallos. **Solo aquí; el modelo no los ve** |
| `resumed` | `bool` | Si se enganchó desde el punto de interrupción con resume en vez de empezar de cero |
| `retired` | `list[str]` | Los session_id quemados en el [relevo](glossary.md#换代) de este paso, en orden |
| `context` | `int` | El tamaño de contexto que realmente vio el [hilo principal](glossary.md#主线程) en el último turno |
| `duration_s` | `float` | Parcheado a mano — es una `@property` y `asdict()` no la recoge |
| `run` | `str` | Marca de este proceso: `YYYYmmdd-HHMMSS-<6 位 hex>`. **Debe ser único por instancia** |

La estrategia de escritura es **añadir, no sobrescribir**: en cada volcado se relee primero el fichero, se reemplazan por las versiones nuevas las filas cuyo `run` coincide con el propio,
y las filas de otros se dejan intactas (`runtime.py:564-586`). Así, varios flower en paralelo sobre el mismo directorio no se pisan la contabilidad.

Lo que hay en `runs/` son datos puros: se pueden inspeccionar en cualquier momento con sqlite3 o
[`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py)
sin conexión.

### `<workspace>/.flower/` — el workbench {#工作台目录}

```text
.flower/
  INDEX.md      índice autogenerado, inyectado en el system prompt del agente principal
  scripts/      scripts que se van a ejecutar una segunda vez. La primera línea `# desc: una frase` aparece en el índice
  artifacts/    salidas largas de más de 2000 caracteres: informes, datos, logs
  notes/        registro de decisiones entre pasos
  spill/        resultados de herramienta grandes volcados a disco; nombre de fichero = primeros 16 caracteres del sha256 del contenido + `.txt`
```

Los tres subdirectorios y el índice los crea `Workbench` (`workbench.py:73-92`). `INDEX.md` va por el `system_prompt.append` de la sesión,
y **los subagent no lo heredan** — por eso la regla de "las salidas largas van a `artifacts/`" tiene que repetirla el
[coordinador](glossary.md#协调者) en el [task brief](glossary.md#任务书): ese es el único canal.

La vía `go` genera siempre estos ficheros bajo `notes/`:

| Fichero | Contenido | Origen |
|---|---|---|
| `notes/需求.md` | El [brief](glossary.md#需求确认书) congelado, cuatro secciones: objetivo / criterios de aceptación / límites / incógnitas y supuestos | `brief.py:44-45`; `clarify.py:105` |
| `notes/目标.md` | Dos secciones congeladas: objetivo / lista de comprobación del veredicto | `workflow/goal.py:124` |
| `notes/问答记录.md` | Registro acumulado de todas las preguntas y respuestas, incluidas las entradas de la bandeja de "lo que la persona dice por iniciativa propia". **No entra en el contexto; solo queda archivado** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | El [documento de relevo](glossary.md#交接书). La generación anterior se guarda en `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | El `lineage.json` + `需求.md` + `目标.md` archivados por `--new` / `/new` (**se mueven, no se borran**) | `lineage.py:100-117` |

**Con `--isolate` el workbench se mueve fuera del repositorio**: `<directorio padre del workspace>/.flower-<nombre del workspace>/`
(`starter.py:47-55`). El worktree es una copia privada de cada agente y el workbench es la capa compartida entre agentes:
lo compartido no puede vivir dentro de una valla privada. En ese caso, la ruta que se le da al modelo es absoluta (`workbench.py:69-71`, `:142-145`).

**`spill/` tiene dos escritores, con algoritmos de destino distintos**:

| Quién escribe | Cuándo | Dónde escribe | Umbral |
|---|---|---|---|
| `spill_guard` (hook `PostToolUse`) | **antes** de que el resultado de la herramienta entre en el modelo | `<root del workbench>/spill/` (`guard.py:130`) | `spill_threshold`, 4000 caracteres por defecto |
| `TrimPolicy` (en `load`) | al reproducir el historial antes de un resume | `<workspace>/.flower/spill/` — cadena fija relativa al espacio de trabajo (`trim.py:49`, `:303`) | `min_chars`, 2000 caracteres por defecto |

Con la disposición por defecto es el mismo directorio. Pero cuando el workbench se mueve (con `-W` acaba en `runs/workbench/`, o con `--isolate`
acaba fuera del repositorio) los dos se separan — la copia de `TrimPolicy` está siempre dentro del espacio de trabajo, porque el `Read`
del agente tiene que poder llegar a ella.

Lo que `spill_guard` deja en su lugar no es una línea, sino una línea de puntero más **los primeros 400 caracteres** (`guard.py:132-140`).
Las llamadas que leen el propio fichero volcado se dejan pasar; si no, "usa Read para leer el contenido completo" sería una frase vacía — lo lees, vuelve a superar el umbral, se vuelve a volcar,
bucle infinito (`guard.py:155-170`).

### Esquema de tablas de `sessions.db` {#sessions-db}

Tres tablas; las sentencias de creación están en `stores/sqlite.py:27-51`:

```sql
CREATE TABLE entries (
    store_key TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    uid       TEXT,
    payload   TEXT NOT NULL,
    PRIMARY KEY (store_key, seq)
);
CREATE UNIQUE INDEX entries_uid
    ON entries(store_key, uid) WHERE uid IS NOT NULL;
CREATE TABLE meta (
    store_key TEXT PRIMARY KEY,
    mtime     INTEGER NOT NULL,
    next_seq  INTEGER NOT NULL
);
CREATE TABLE summaries (
    project_key TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    mtime       INTEGER NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (project_key, session_id)
);
```

| Tabla | Qué es una fila | Puntos clave |
|---|---|---|
| `entries` | Una entrada del transcript; `payload` es el JSON original | `uid` es el `uuid` de la entrada y hace de **clave de idempotencia**: los lotes fallidos se reintentan 3 veces y la reproducción no puede generar filas duplicadas. Las entradas sin `uuid` (títulos, etiquetas, marcas de modo) no se deduplican, de ahí el `WHERE uid IS NOT NULL` del índice único |
| `meta` | El cursor de una sesión | `next_seq` es el siguiente número de secuencia y `mtime` es una marca de tiempo en milisegundos **estrictamente monótona** (`sqlite.py:72-79`) — `list_sessions` y los resúmenes comparten este reloj, y si no es monótono el SDK toma el camino rápido equivocado al decidir qué es más reciente |
| `summaries` | El sidecar de resumen de un hilo principal | **Solo participa el transcript principal**; los de los subagent no cuentan (`sqlite.py:122-123`) |

Construcción de `store_key` (`sqlite.py:54-58`): `<project_key>/<session_id>`, y los subagent añaden otro tramo
`subpath`. El `project_key` lo deriva el SDK de la ruta del espacio de trabajo: `/`, `_` y `.` se sustituyen por `-`.

Un vistazo a una muestra real ([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

Esa muestra tiene 956 `entries`, 10 `meta` y 4 `summaries` — de las 10 sesiones, 4 son transcripts principales
y 6 son de subagent, y `summaries` coincide exactamente con el número de transcripts principales.

## Las tres capas del almacén de sesiones {#会话存储}

!!! note "Las tres capas son una cadena de herencia, no una combinación opcional"
    `PruningSessionStore` hereda de `TrimmingSessionStore`, que hereda de `SqliteSessionStore`.
    `Runtime` construye **siempre** la capa más externa (`runtime.py:109-112`), y sus parámetros de construcción no ofrecen ninguna vía para cambiar de backend.
    La forma de "desactivar una capa" es poner a `False` el `enabled` de su objeto de política, no cambiar de clase.

`append` (escritura) siempre vuelca todo a disco sin cambiar ni un carácter. Las tres capas solo afectan a `load` (la copia que se le devuelve al modelo).
El orden real de `load` es:

```text
SqliteSessionStore.load     lee todo de la tabla entries por seq
  → TrimmingSessionStore.expire()   resultados de Bash con caducidad → sustituidos por "caducado"
  → TrimmingSessionStore.trim()     tool_result grandes y antiguos → volcado a disco + puntero
    → PruningSessionStore.prune()   mensajes de error sintéticos / llamadas denegadas antiguas → entrada eliminada y cadena reenganchada
```

| Capa | Clase | Qué tira | Criterio |
|---|---|---|---|
| 1 | `SqliteSessionStore` | Nada | —— |
| 2 | `TrimmingSessionStore` | El cuerpo de resultados de herramienta grandes, resultados caducados de comandos efímeros | Tamaño + caducidad |
| 3 | `PruningSessionStore` | Restos de desconexión, llamadas denegadas antiguas | Si es un error o no |

La capa 2 es el [recorte](glossary.md#裁剪) y la capa 3 es la [poda](glossary.md#剪除) —
**el recorte tira por tamaño y valor, la poda tira por "es un error o no"**; no los mezcles. Firmas completas en la [API de Python](api.md).

### `SqliteSessionStore` — los cimientos {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

Implementación en SQLite sin dependencias externas. Para cambiar a Postgres / S3 / Redis basta con implementar el mismo protocolo; el SDK trae una suite
de tests de conformidad, `claude_agent_sdk.testing.session_store_conformance`, que se puede usar directamente para verificarlo (`sqlite.py:1-8`).

Aparte de los métodos del protocolo, hay tres consultas **síncronas** para uso interno de flower:

| Método | Devuelve | Para qué |
|---|---|---|
| `projects()` | `list[str]` | Los `project_key` que realmente existen en la base. El SDK lo deriva del cwd; confírmalo con esto antes de consultar, no lo adivines |
| `has_session(project_key, session_id)` | `bool` | Consulta una sola fila de `meta`, sin leer el payload. Consúltalo antes de arrancar la [continuidad](glossary.md#接续) — hacer resume de una sesión inexistente revienta solo después de haber levantado el subproceso, y para entonces ya has gastado dinero y tiempo |
| `last_context(project_key, session_id, scan=60)` | `int` | Cuánto contexto vio esta sesión en su último turno. Solo escanea hacia atrás las últimas 60 entradas. Cuenta `input_tokens` más los dos `cache_*` — mirar solo el primero da casi 0 cuando hay acierto de caché y subestima gravemente |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Dos reglas ortogonales. `TrimPolicy` se ocupa del **tamaño**:

| Parámetro | Tipo | Por defecto | Semántica |
|---|---|---|---|
| `keep_recent` | `int` | `20` | Los N `tool_result` más recientes conservan el texto original — el contexto en uso no se debe recortar |
| `min_chars` | `int` | `2000` | Nada más corto se recorta. Sustituirlo por un puntero gastaría más tokens |
| `spill_dirname` | `str` | `".flower/spill"` | Directorio de archivo, **relativo al workspace**. Debe estar dentro del espacio de trabajo o el `Read` del agente no llega |
| `enabled` | `bool` | `True` | Con `Runtime(trim=False)` (el valor por defecto) es `False` |

El cuerpo recortado se escribe como `<primeros 16 caracteres del sha256>.txt`, y en su lugar queda
`[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` (`trim.py:54-57`, `:308-317`).

`EphemeralPolicy` se ocupa de la **caducidad**: los resultados de `git status`, `ls`, `ps` y similares son muy cortos, así que por tamaño nunca les tocaría el recorte,
pero su corrección decae con el tiempo — aquel `git status` de hace 20 turnos no es "inútil", es que **induce a error**.

| Parámetro | Tipo | Por defecto | Semántica |
|---|---|---|---|
| `enabled` | `bool` | `True` | Se deriva de `Runtime(ephemeral=…)`; **activado por defecto** |
| `keep_recent` | `int` | `6` | Los N más recientes conservan el texto original. Mucho menor que los 20 de `TrimPolicy` — para este tipo de cosas la ventana de "reciente" es corta de por sí |
| `max_chars` | `int` | `2000` | Por encima de esto pasa a `TrimPolicy` para archivarse en disco, y no sigue esta vía |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Texto de sustitución |

Solo actúa sobre resultados de la herramienta **Bash**, y el comando debe casar con `EPHEMERAL_CMD`. `Read` no entra aquí: el contenido de un fichero no se distorsiona
con el paso del tiempo hasta el punto de inducir a error, y además puede ser justo la base del razonamiento del modelo (`trim.py:153-160`). El contenido caducado
**no se vuelca a disco** — archivar un `git status` caducado no tiene sentido: se vuelve a ejecutar y ya está.

La función de decisión es `is_ephemeral(cmd)`, y **es a la vez la lista de permisos que se le devuelve al coordinador**: `delegate_guard(allow_glance=True)`
usa esa misma función (`trim.py:63-68`, `:128-150`). Los dos conjuntos tienen que ser siempre iguales —
si permites pero no recortas, un `git status` caducado ocupa el contexto para siempre; si recortas pero no permites, el coordinador
despacha un subagent para un simple `ls`, 4,3k de coste de arranque a cambio de unas decenas de caracteres. Añadir un comando a la lista blanca equivale a decir las dos cosas a la vez.

**Cuándo usar cada cosa**:

- Si solo quieres que los restos de desconexión no entren en el contexto → no hace falta hacer nada: `Runtime` ya usa `PruningSessionStore` por defecto.
  `trim=False` solo significa no recortar los resultados grandes; la eliminación se sigue haciendo.
- Ejecuciones largas con salidas de herramienta muy grandes → `trim=True`. La CLI de la vía `go` ya lo tiene activado por defecto; se desactiva con `--no-trim`.
- Si el [coordinador](glossary.md#协调者) tiene `glance=True` → `ephemeral` debe seguir activado, por el motivo del párrafo anterior.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Parámetro | Tipo | Por defecto | Semántica |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Elimina los mensajes sintéticos con `isApiErrorMessage=true` o `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | En los `tool_result` con `[Request interrupted …]` **se sustituye el cuerpo, no se elimina el bloque** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Texto de sustitución de lo anterior |
| `heal_orphans` | `bool` | `True` | **Añade** un resultado sintético a las llamadas huérfanas que tienen `tool_use` pero no `tool_result` |
| `orphan_text` | `str` | `"[这一步被打断了,没有结果。需要的话重做。]"` | Cuerpo del `tool_result` añadido |
| `keep_denials` | `int` | `1` | Conserva las N llamadas de herramienta más recientes denegadas por el permission hook; las anteriores se eliminan **junto con la llamada y su resultado** |

`keep_denials` es el único parámetro de construcción de `Runtime` que se propaga hasta esta capa (`Runtime(keep_denials=N)`).
La razón de que sea 1 y no 0: la denegación más reciente es una señal útil, evita que el modelo reintente en el mismo turno una y otra vez el mismo comando bloqueado.
**No lo subas** — las llamadas denegadas nunca se ejecutaron, así que en su resultado no hay información alguna; medido, cada una ocupa 273 caracteres
(93 caracteres de texto de denegación más 180 del comando muerto original), y además **induce a error**: en pruebas, tras leer varias veces "no uses Bash directamente", el coordinador
dejaba de intentar incluso el `git status` permitido y decía directamente "Bash está restringido, despacho un agente para mirarlo" (`prune.py:135-148`).

`heal_orphans` cura el caso de **cada resume da 400 después de una interrupción**: la interrupción corta en un límite de mensaje, y el `tool_use` que estaba en vuelo
puede quedarse sin `tool_result` detrás, mientras que la API exige que vayan en pareja. Ese historial roto se queda en el transcript y no desaparece solo,
así que todos los resume posteriores rebotan por su culpa. La cura consiste en insertar una entrada `user` después de la assistant que contiene los huérfanos,
completando de golpe los resultados de todos los huérfanos de esa entrada, y luego reapuntar a esa nueva entrada el `parentUuid` que apuntaba a la assistant original
(`prune.py:95-147`). **Se completa, no se borra**: borrar los huérfanos obligaría a reenganchar la cadena padre-hijo, y en esa misma assistant puede haber bloques normales,
texto y thinking, con riesgo de llevárselos por delante (`prune.py:195-204`).

Tres líneas rojas estructurales; violarlas hace que la API dé error directamente:

1. **El bloque `tool_result` tiene que seguir ahí**, solo se puede sustituir su `content`. Si falta uno, es "Missing Tool Result Block"
   (`trim.py:20-22`; `prune.py:79-92`).
2. **Las entradas `isCompactSummary` / `isMeta` no se tocan** — son la única forma en la que existe ese tramo de historial ya compactado
   (`trim.py:179-181`).
3. **Si eliminas una entrada, tienes que enganchar sus hijos a su padre.** El transcript es una cadena simple de `parentUuid` y el harness recorre desde la hoja
   hacia atrás: donde se rompa la cadena, todo el historial anterior se pierde (`prune.py:95-122`). Por eso `relink()` necesita recibir la lista completa **incluyendo** las
   entradas a eliminar; el filtrado lo hace ella misma.

**En SQLite no se cambia ni un carácter del original** — las tres capas solo afectan a "la copia que se le devuelve al modelo" (`trim.py:18`; `prune.py:8`).

## Resiliencia ante caídas de red {#韧性}

Un workflow de largo horizonte corre durante horas, y la red se va a caer alguna vez, seguro. El comportamiento por defecto es pésimo: en el instante de la desconexión el harness mete en el transcript
un mensaje assistant sintético (`model="<synthetic>"`, `isApiErrorMessage=true`) cuyo cuerpo es
`API Error: Can't reach the API server …`; ese mensaje pasa a ser la hoja de la sesión, y a partir de ahí cada resume se lo devuelve al modelo como "lo último que dijo él",
así que el modelo cree que está hablando de un fallo de red; además se cuela en `StepResult.text` y viaja por el workflow hasta el prompt del paso siguiente
(`resilience.py:1-22`).

La capa de [resiliencia](glossary.md#韧性) hace tres cosas, y las tres son imprescindibles: sondear, continuar en vez de empezar de cero, y mantener los errores fuera del contexto.

### Parámetros de `Resilience` {#resilience}

| Parámetro | Tipo | Por defecto | Semántica |
|---|---|---|---|
| `enabled` | `bool` | `True` | Se deriva de `Runtime(resilience=…)` |
| `max_attempts` | `int` | `6` | Cuántos intentos como máximo por [paso](glossary.md#步骤), **incluido el primero** |
| `base_delay` | `float` | `4.0` | Punto de partida del backoff exponencial, en segundos |
| `max_delay` | `float` | `120.0` | Tope del backoff, en segundos |
| `probe_timeout` | `float` | `5.0` | Timeout de una sonda, en segundos |
| `probe_interval` | `float` | `15.0` | Cada cuánto sondear mientras no hay red, en segundos |
| `max_offline_wait` | `float` | `3600.0` | Cuánto esperar como máximo sin red. Por defecto 1 hora — más que eso normalmente no es una fluctuación, es que ha pasado algo de verdad |
| `retry_unknown` | `bool` | `True` | Reintentar también los errores que no se pueden clasificar. La mayoría de los errores desconocidos son transitorios, y los fatales ya están bloqueados por separado |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | Lo que se le dice al modelo al continuar |

Fórmula del backoff (`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

Es decir, `±25%` de jitter, para evitar que en el instante en que vuelve la red un montón de procesos se abalancen a la vez. Con los valores por defecto: el primer backoff es de 4 segundos (en la práctica 3~5),
el segundo de 8 (6~10), y a partir del quinto se topa en 120 segundos (90~150).

### Estrategia de la sonda {#探针}

- **Se sondea el host:port de `ANTHROPIC_BASE_URL`**, no `api.anthropic.com` (`resilience.py:67-72`).
  Con una pasarela propia, que lo segundo responda no dice nada de lo primero.
- **Solo DNS más handshake TCP**: `getaddrinfo`, luego `connect_tcp`, y cerrar inmediatamente. No se manda HTTP,
  no lleva credenciales, no cuesta dinero (`resilience.py:75-85`). La sonda tiene que ser gratis; si no, "sondear cada 15 segundos mientras no hay red"
  se convierte ella misma en la avería.
- Cualquier fallo cuenta como inalcanzable — no se distingue si se cayó el DNS o si TCP rechazó.
- `wait_online()` se queda ahí esperando: devuelve `True` si vuelve la conexión, y `False` si se agota `max_offline_wait`.
  En la primera vez que detecta inalcanzabilidad notifica una línea `<host>:<port> 不可达,等待恢复(最多 60 分钟)`, y al recuperarse otra línea
  `<host>:<port> 恢复,继续`; **en medio no inunda la pantalla** (`resilience.py:126-140`).

La sonda de credenciales previa al arranque es otra cosa: esa sí lanza un `POST <BASE_URL>/v1/messages` de verdad, con `max_tokens=16`
y timeout de 20 segundos por defecto (`env.py:126-181`). **No pongas `max_tokens` a 1** — medido: los modelos con cadena de pensamiento forzada no tienen ni sitio para pensar,
y el servidor tarda 30 segundos en responder a duras penas; con 16 tarda solo 3,6 segundos (`env.py:120-123`).

### Clasificación de errores {#错误分类}

`classify(text)` devuelve uno de tres valores. **Primero se comprueba lo fatal**: el texto de un 401, por ejemplo, suele traer también palabras como "connection",
y con el orden invertido te quedas esperando eternamente (`resilience.py:53-64`).

| Clase | Qué casa (regex en `resilience.py:37-50`) | Comportamiento |
|---|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` | Parar de inmediato, sin reintentos. Reintentar da el mismo resultado siempre, y cada intento cuesta dinero |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `timeout`, `service unavailable` | Esperar a que vuelva la red y continuar con resume |
| `unknown` | No casa con nada | Con `retry_unknown=True` (por defecto) también se reintenta |

Distinguir lo reintentable de lo no reintentable es el núcleo de esta capa: **una fluctuación de red merece espera, una credencial incorrecta merece parada inmediata** —
esperar sin red es lo correcto; esperar con la key mal escrita es quemar tiempo.

### Qué se queda fuera del contexto {#错误不进上下文}

1. **Los mensajes de error sintéticos.** `PruningSessionStore` los elimina enteros en el `load` y reengancha el `parentUuid`
   (`prune.py:27-32`, `:191-195`). **En SQLite se conservan tal cual**; simplemente no se devuelven al modelo.
2. **En el flujo de eventos son `kind="error"` y no `"text"`**, así que no entran en `StepResult.text`
   y por tanto no viajan por el workflow hasta el prompt del paso siguiente (`resilience.py:17-18`).
3. **`resume_prompt` no contiene ningún detalle del error, a propósito.** El modelo necesita saber "te interrumpieron, sigue"; no necesita saber si fue
   `ENOTFOUND` o `503`. **Eso pertenece al log, no al contexto** (`resilience.py:112-113`).
   Para el log, mira el campo `errors` de `manifest.json`.

Continuar en vez de empezar de cero: cuando ocurre el fallo ya se tiene el `session_id`, así que se engancha con resume desde el punto de interrupción y el gasto anterior no se tira.

## Relacionado {#相关}

- [Línea de comandos](cli.md) — cómo se mapea cada interruptor a la configuración de esta página.
- [API de Python](api.md) — firmas completas de `Runtime`, los tres stores y `Resilience`.
- [Despliegue](deploy.md) — ejecutar en contenedor, distribuir capacidades de dominio con plugin.
- [Glosario](glossary.md) — el significado exacto de cada término usado en esta página.
