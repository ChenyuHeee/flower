# Configuración

flower no tiene formato de archivo de configuración, ni un subcomando de configuración al que de
verdad se llegue — toda la configuración son **variables de entorno** más **archivos `.env`**, más
un puñado de objetos de política que solo se pueden pasar desde Python. Esta página recoge en un
solo sitio lo que está repartido en cinco: cada variable, en qué orden se buscan las credenciales,
qué sintaxis acepta `.env`, qué aísla exactamente `setting_sources=[]`, qué deja una ejecución en
disco, qué tira cada una de las tres capas del almacén de sesiones y cómo se espera cuando se cae la
red. La terminología sigue siempre el [glosario](glossary.md).

| Qué quieres saber | Dónde |
|---|---|
| Qué variables de entorno lee flower | [Tabla completa de variables de entorno](#环境变量) |
| De dónde sale realmente mi token | [Prioridad de búsqueda de credenciales](#凭证查找优先级) |
| Por qué esa línea de mi `.env` no surte efecto | [Reglas de parseo de `.env`](#env-解析) |
| Qué llevarme al cambiar de máquina | [El precio de la portabilidad](#可移植性) |
| Qué hay dentro de `.flower/` y `runs/` | [Distribución en disco](#磁盘布局) |
| Qué mensajes no se devuelven al modelo | [Las tres capas del almacén de sesiones](#会话存储) |
| Qué está esperando cuando se cae la red | [Resiliencia ante caídas de red](#韧性) |

## Tabla completa de variables de entorno {#环境变量}

Cuatro grupos: credenciales y endpoint que flower lee directamente, selección de modelo, rutas de
búsqueda, y las que flower **escribe para** el subproceso del agente. Este último grupo no lo pones
tú — y si lo pones, se sobrescribe.

### Credenciales y endpoint {#凭证变量}

| Variable | Función | Por defecto | Obligatoria | Origen |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Key oficial de Anthropic. Si existe, las peticiones van con la cabecera `x-api-key` | ninguno | **Obligatoria una de las dos**, junto con `ANTHROPIC_AUTH_TOKEN` | `env.py:28`, `:146`, `:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Token emitido por un gateway. Sin `ANTHROPIC_API_KEY` se usa `authorization: Bearer` | ninguno | Ídem | `env.py:28`, `:147`, `:159-160` |
| `ANTHROPIC_BASE_URL` | Raíz del endpoint de la API. Un gateway de terceros pone aquí su propia dirección, **sin `/v1`** — la sonda compone `<BASE_URL>/v1/messages` | `https://api.anthropic.com` | No | `env.py:151`, `:162`, `:210`; `resilience.py:70` |

Si no está ninguna de las dos (o ambas son cadena vacía), `check_credentials()` devuelve ese error de
cuatro líneas y `Runtime.__init__` lanza un `RuntimeError` (`env.py:184-194`; `runtime.py:156-158`).

### Selección de modelo {#模型变量}

flower solo lee tres de ellas para sus propias decisiones; el resto se cargan y se pasan tal cual al SDK.

| Variable | Función | Por defecto | Obligatoria | Origen |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | Nombre del modelo principal. También decide el valor por defecto de la ventana de [relevo](glossary.md#换代): si el nombre lleva `1m` o no lleva `haiku` → 1 000 000; si lleva `haiku` → 200 000 | ninguno (lo decide el endpoint) | No | `env.py:153`; `agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Mapeo del modelo de la gama opus. Si `ANTHROPIC_MODEL` está vacía, el cálculo de la ventana cae a esta | ninguno | No | `agent.py:78`; `cli.py:1205` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Mapeo del modelo de la gama sonnet. flower no la lee; solo la carga y la toma prestada | ninguno | No | `env.py:34`; `cli.py:1206` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Mapeo del modelo de la gama haiku. **La sonda de credenciales la usa con prioridad** | la sonda cae a `ANTHROPIC_MODEL`, y luego a `claude-3-5-haiku-20241022` | No | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Qué modelo usan los [subagent](glossary.md#subagent). flower no la interpreta; la consume el SDK | ninguno | No | `env.py:35`; `.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Nivel de esfuerzo de razonamiento. Ídem: solo se carga, no se interpreta | ninguno | No | `env.py:35` |

Si le das un nombre de modelo a `flower setup`, se escriben **las tres a la vez**:
`ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` y `ANTHROPIC_DEFAULT_SONNET_MODEL`
(`cli.py:1204-1206`).

### Rutas y búsqueda {#路径变量}

| Variable | Función | Por defecto | Obligatoria | Origen |
|---|---|---|---|---|
| `FLOWER_ENV` | Indica la ruta de un `.env` que se coloca **antes** de todos los demás archivos | ninguno | No | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Decide dónde está el archivo global de credenciales: `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | No | `env.py:41-42` |
| `HOME` | Origen de `Path.home()`; de ahí se deducen tanto `~/.config` como `~/.claude` | lo da el sistema | No | `env.py:41`, `:67` |

### Lo que flower escribe para el subproceso del agente {#写出的变量}

Estas tres las genera `CompactPolicy.env()` y se inyectan en `ClaudeAgentOptions.env`
(`agent.py:48-58`, `:241-245`); controlan el [compact](glossary.md#压缩) integrado en el harness.
**No tiene sentido definirlas en tu shell** — lo que vale es la copia que flower le pasa al
subproceso.

| Variable | Función | Por defecto | Obligatoria | Origen |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` apaga el compact automático. Con el [relevo](glossary.md#换代) activo se **escribe a la fuerza** — con los dos mecanismos corriendo a la vez no se distingue quién provocó la caída de contexto | el relevo está activo por defecto, así que en la práctica siempre es `1` | No (la escribe flower) | `agent.py:51`; `runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` apaga también `/compact`. Solo se escribe con `CompactPolicy(mode="off")` | no se escribe | No (la escribe flower) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Ventana (en tokens) del compact automático. Solo se escribe con `CompactPolicy(window=N)` | no se escribe | No (la escribe flower) | `agent.py:56-57` |

### Las que lee el wrapper de contenedor {#容器变量}

Estas dos no las lee flower en sí, sino el wrapper de shell `docker/flowerbox`. El uso completo está
en [Despliegue](deploy.md).

| Variable | Función | Por defecto | Obligatoria | Origen |
|---|---|---|---|---|
| `FLOWER_HOME` | Dónde buscar el `.env` que se pasa a `--env-file` | el directorio padre de la ubicación del propio script | No | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Qué imagen usar | `flower-box` | No | `docker/flowerbox:13` |

**Las claves del `.env` no se limitan a las de arriba.** El parser carga **todas** las líneas `k=v`
en `os.environ`, sin lista blanca (`env.py:30`, `:102-107`). El conjunto `KNOWN`, formado por esas 9
claves de credenciales, solo actúa en dos sitios: como lista blanca al tomar prestada la
configuración de `~/.claude` (`env.py:72`), y para delimitar los campos que imprime `describe()` al
arrancar con `-v` (`env.py:205`).

## Prioridad de búsqueda de credenciales {#凭证查找优先级}

Cuando `load_dotenv()` se llama sin ruta, lee por orden **todos los archivos que existan**
(`env.py:45-53`, `:78-112`):

1. **Variables de entorno del proceso** — siempre la máxima prioridad. Ningún `.env` puede pisar un
   valor ya exportado. (`env.py:91`)
2. **El archivo al que apunta `$FLOWER_ENV`** — solo si la has definido. (`env.py:48-49`)
3. **`$PWD/.env`** — el directorio de trabajo actual. Según a qué proyecto hagas `cd`, lee el más
   cercano. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — la ubicación global, una por usuario; es la que
   escribe `flower setup`. (`env.py:51`, `:39-42`)
5. **El `.env` en la raíz del repositorio de código fuente** — tres niveles por encima de
   `flower/core/env.py`. Solo existe si ejecutas desde el código fuente; una instalación con pip /
   pipx / uv deja flower en site-packages y esta entrada no existe. (`env.py:52`)
6. **El bloque `env` de `~/.claude/settings.json` y después el de `~/.claude/settings.local.json`** —
   el último recurso, y **solo toma las 9 claves de credenciales**. (`env.py:56-75`, `:109-111`)

**Qué archivo gana**: la entrada 3 (el `.env` del proyecto) gana a la 4 (el `.env` global), la 4 gana
a la 5 (el `.env` de la raíz del repo), las tres ganan a la 6 (la configuración de Claude Code), y
ninguna gana a la 1 (el entorno del proceso).

La implementación es «**una clave que ya tiene valor no se sobrescribe**» (`env.py:90-93`): los
primeros ocupan las claves y los siguientes solo rellenan huecos. Por eso la prioridad se calcula
**por clave, no por archivo** — si el `.env` del proyecto solo define `ANTHROPIC_BASE_URL`, el token
puede venir perfectamente del global. Para una misma clave, el primer valor que aparece queda fijado
de por vida.

La entrada 6 solo se activa en la **búsqueda automática**. Si das una ruta explícita
(`load_dotenv("/path/to/.env")`) se lee solo ese archivo, sin ningún fallback
(`env.py:86-87`, `:109`).

### Entrada 6: tomar prestado el token de Claude Code {#借用}

Lee por orden `~/.claude/settings.json` y `~/.claude/settings.local.json`, coge el dict `data["env"]`
y de ahí selecciona estas 9 claves (`env.py:31-36`, `:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

Si el archivo no existe, no se puede leer, o no es JSON válido (`OSError` / `ValueError`), devuelve un
dict vacío y sigue adelante — **que falle el fallback no debe llevarse por delante la ejecución**
(`env.py:62-63`, `:66-69`).

La postura del código es: lo único que se toma prestado es «dónde encontrar el token»; nada más de
settings.json (reglas de permisos, hooks, ajustes de modelo) se hereda, así que esto no rompe la
promesa de portabilidad de `setting_sources=[]` (`env.py:17-19`, `:59-61`). `install.sh:77` lo vende
como una característica: quien ya tenga Claude Code configurado en su máquina ni siquiera verá la
pantalla de configuración.

!!! warning "El texto de error del producto dice lo contrario del comportamiento real"
    Cuando no encuentra ninguna credencial, la última línea del error que imprime flower es:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, esa frase está en `:192`; la misma afirmación aparece además en
    `.env.example:2`, `env.py:3-4`, `agent.py:10-12`.) **Manda el código: sí lo lee.**
    `env.py:56-75` más `:109-111` leen explícitamente esos dos archivos, y `install.sh:77` lo
    presenta como argumento de venta. Ese texto es hoy engañoso — en una máquina con Claude Code
    configurado, es muy probable que tu token venga justo de ahí.

## Reglas de parseo de `.env` {#env-解析}

Las reglas son tan cortas que se memorizan (`env.py:95-107`, 13 líneas): `strip` línea a línea; se
saltan las líneas vacías, las que empiezan por `#` y las que no contienen `=`; el resto se parte por
el **primer** `=` en clave y valor, se hace `strip` a ambos lados, y al valor se le aplica además
`.strip("'\"")` — las comillas simples o dobles al principio y al final se eliminan siempre,
**sin exigir que estén emparejadas**.

**Acepta estas formas**:

| Forma | Resultado |
|---|---|
| `KEY=VALUE` | Normal |
| `KEY = VALUE` | Normal — los espacios alrededor del `=` se eliminan con strip |
| `KEY="VALUE"` / `KEY='VALUE'` | Normal — las comillas de los extremos se quitan |
| `KEY=a=b` | El valor es `a=b` — se parte por el primer `=`, los demás quedan tal cual en el valor |
| `# comentario` | Línea entera saltada |
| Línea vacía | Saltada |

**No acepta estas.** No dan error: simplemente obtienes un valor inesperado en silencio:

| Forma | Resultado real |
|---|---|
| `export KEY=VALUE` | La clave pasa a ser `export KEY`; `KEY` en sí sigue sin valor |
| `KEY=value # nota` | El valor es `value # nota` — los comentarios al final de línea no se quitan |
| `KEY=$OTHER` | El literal `$OTHER`; no hay interpolación de variables |
| Valor multilínea (con comillas que cruzan líneas) | Se procesa línea a línea; la segunda no contiene `=` y se salta entera |

**Un valor vacío ocupa la clave.** Si `ANTHROPIC_AUTH_TOKEN=` aparece en un archivo de alta
prioridad, `take()` ejecuta `os.environ["ANTHROPIC_AUTH_TOKEN"] = ""`, y los archivos posteriores ya
no pueden rellenarla porque «la clave ya existe» (`env.py:90-93`); mientras que `check_credentials()`
evalúa por veracidad y una cadena vacía cuenta como no configurada (`env.py:186`).
**El resultado es que no tienes credencial ni fallback.** Si no quieres una clave, borra la línea
entera; no la dejes vacía.

## El precio de la portabilidad {#可移植性}

Todo el mecanismo cabe en una línea de `build_options()` (`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` es el valor por defecto de `Runtime`, y **no hay ningún flag de línea de comandos que
lo desactive** — para apagarlo hay que ir por la API de Python y escribir `Runtime(portable=False)`,
que lo convierte en `["project"]`, es decir, lee el `.claude/` del proyecto.

### Qué queda aislado

| Qué queda aislado | Consecuencia |
|---|---|
| Los ajustes de `~/.claude/` de la máquina anfitriona | Sus reglas de permisos, hooks y ajustes de modelo no surten efecto. **Las credenciales son la única excepción**, ver [tomar prestado](#借用) |
| El `.claude/` del proyecto | Ídem; solo se lee con `portable=False` |

Las capacidades de dominio no pasan por ahí — se distribuyen con el repositorio y se cargan mediante
`plugins=[{"type": "local", "path": PLUGIN_DIR}]` (`agent.py:26`, `:210-212`); ver
[Despliegue](deploy.md). Las instrucciones de dominio se **anexan** después del system prompt nativo
de Claude Code, no lo sustituyen (`agent.py:198-202`), así que la especialización no se paga con
pérdida de capacidad general.

### Qué llevarte al cambiar de máquina

- **Credenciales: un archivo.** Copia `~/.config/flower/.env`, o vuelve a configurarlo en la máquina
  nueva. Sin él no arranca nada — no se hereda nada automáticamente.
- **Estado de continuidad: el directorio entero.** `runs/` (la base de sesiones, el manifiesto, el
  linaje) y `.flower/` (el workbench).
- **Pero las rutas deben coincidir.** `lineage.json` guarda la ruta absoluta del workspace; si no
  coincide, se ignora y se cae en silencio a una sesión nueva, **sin error** (`lineage.py:65-66`).
  El motivo es que el `project_key` del SDK se deduce de la ruta del workspace (`/`, `_` y `.` se
  sustituyen todos por `-`, `runtime.py:40-41`): si el directorio cambia de sitio, el `session_id`
  antiguo ya no se encuentra.

## Distribución en disco {#磁盘布局}

Una ejecución de flower escribe dos árboles: `<run_dir>/` guarda la contabilidad y las sesiones,
`<workspace>/.flower/` guarda el [workbench](glossary.md#工作台). Por defecto ambos cuelgan del
directorio actual, pero **su punto de referencia es distinto**.

!!! warning "`runs/` sigue al directorio actual, no a `-w`"
    `-r/--run-dir` es `"runs"` por defecto, y lo que `Runtime` hace con él es
    `Path(run_dir).resolve()` (`runtime.py:93-94`) — relativo al **directorio de trabajo actual**, no
    al workspace indicado con `-w`. Si ejecutas `flower -w /path/to/proj` desde `~`, la base de
    sesiones acaba en `~/runs/`, no dentro del proyecto.

### `<run_dir>/` — por defecto `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite, transcript completo (incluida la línea propia de cada subagent)
  manifest.json      Manifiesto de ejecución: session_id / coste / reintentos / causa de fallo por paso, acumulado entre procesos
  lineage.json       Linaje: nombre de paso → session_id; permite retomar al volver a ejecutar en el mismo directorio
  aside/             Runtime independiente del oráculo, con su propio sessions.db + manifest.json
  workbench/         Solo por la vía run / once y si se pasa -W
```

| Ruta | Contenido | Origen |
|---|---|---|
| `runs/sessions.db` | Transcript completo. Lo escribe `PruningSessionStore`; las tres capas de política están [más abajo](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | Array JSON, el [manifiesto de ejecución](glossary.md#运行清单) **acumulado entre procesos**. Campos en la tabla siguiente | `runtime.py:532-533`, `:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Escribe primero un `.tmp` y luego hace `replace`: sustitución atómica | `lineage.py:31`, `:87-97` |
| `runs/aside/` | Runtime independiente del [oráculo](glossary.md#旁路顾问). **Su coste y su linaje no se mezclan con el manifiesto principal** | `cli.py:632-634` |
| `runs/workbench/` | Ubicación por defecto del workbench con `Runtime(workbench=True)`, fuera del workspace. La vía `go` no lo usa | `runtime.py:148-151` |

Cada línea de `manifest.json` es un `asdict(StepResult)` con dos parches
(`runtime.py:44-71`, `:579-582`):

| Campo | Tipo | Significado |
|---|---|---|
| `step` | `str` | Nombre del paso. Cuatro formas: `<名>`, `<名>#round<N>` (devuelto para rehacer), `<名>#retry<N>` (reintento normal), `<名>·判定#<N>` ([juez](glossary.md#判定者)) |
| `session_id` | `str \| None` | La última [sesión](glossary.md#会话) viva de este paso |
| `ok` | `bool` | Si salió bien |
| `cost_usd` | `float` | Cuánto costó este paso |
| `num_turns` | `int` | Cuántos turnos corrió |
| `text` | `str` | La respuesta final de este paso |
| `error` | `str \| None` | Causa del fallo. Si lo mató un SIGHUP / SIGTERM, es `killed-by-signal` (`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | Segundos epoch |
| `attempts` | `int` | Número real de intentos. `>1` significa que hubo reintentos |
| `errors` | `list[str]` | Causas de todos los fallos previos. **Solo aquí; el modelo no las ve** |
| `resumed` | `bool` | Si se retomó desde la interrupción con resume en vez de empezar de cero |
| `retired` | `list[str]` | Los session_id quemados en el [relevo](glossary.md#换代) de este paso, en orden |
| `context` | `int` | Tamaño de contexto que realmente vio el [hilo principal](glossary.md#主线程) en el último turno |
| `duration_s` | `float` | Añadido a mano — es una `@property` y `asdict()` no lo recoge |
| `run` | `str` | Marca de este proceso: `YYYYmmdd-HHMMSS-<6 位 hex>`. **Debe ser único por instancia** |

La estrategia de escritura es **añadir, no sobrescribir**: antes de volcar se relee el archivo, se
reemplazan por su versión más reciente las líneas cuyo `run` coincide con el propio, y las de los
demás se dejan intactas (`runtime.py:564-586`). Por eso varios flower en paralelo sobre el mismo
directorio no se pisan la contabilidad.

Lo que hay en `runs/` son datos puros: puedes revisarlos offline cuando quieras con sqlite3 o con
[`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py).

### `<workspace>/.flower/` — el workbench {#工作台目录}

```text
.flower/
  INDEX.md      Índice autogenerado, inyectado en el system prompt del agente principal
  scripts/      Scripts que se van a ejecutar más de una vez. La primera línea `# desc: una frase` aparece en el índice
  artifacts/    Salidas largas de más de 2000 caracteres: informes, datos, logs
  notes/        Registro de decisiones entre pasos
  spill/        Resultados de herramienta grandes volcados a disco; nombre de archivo = primeros 16 dígitos del sha256 del contenido + `.txt`
```

Los tres subdirectorios y el índice los crea `Workbench` (`workbench.py:73-92`). `INDEX.md` va por el
`system_prompt.append` a nivel de sesión, y **los subagent no lo heredan** — por eso la regla «las
salidas largas van a `artifacts/`» tiene que retransmitirla el [coordinador](glossary.md#协调者) en el
[brief de tarea](glossary.md#任务书); ese es el único canal.

La vía `go` genera siempre estos archivos bajo `notes/`:

| Archivo | Contenido | Origen |
|---|---|---|
| `notes/需求.md` | El [brief](glossary.md#需求确认书) congelado, cuatro secciones: objetivo / criterios de aceptación / límites / incógnitas y supuestos | `brief.py:44-45`; `clarify.py:105` |
| `notes/目标.md` | Las dos secciones congeladas: objetivo / lista de comprobación del veredicto | `workflow/goal.py:124` |
| `notes/问答记录.md` | Registro acumulado de todas las preguntas y respuestas, incluidas las entradas de bandeja de «lo que la persona dice por iniciativa propia». **No entra en el contexto; solo queda como archivo** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | El [documento de relevo](glossary.md#交接书). El de la generación anterior se guarda en `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | El `lineage.json` + `需求.md` + `目标.md` archivados por `--new` / `/new` (**se mueven, no se borran**) | `lineage.py:100-117` |

**Con `--isolate` el workbench se mueve fuera del repositorio**: a
`<directorio padre del workspace>/.flower-<nombre del workspace>/` (`starter.py:47-55`). El worktree
es la copia privada de cada agente y el workbench es la capa compartida entre agentes; lo compartido
no puede quedar dentro de una valla privada. En ese caso la ruta que se le da al modelo es absoluta
(`workbench.py:69-71`, `:142-145`).

**`spill/` tiene dos escritores, con algoritmos de destino distintos**:

| Quién escribe | Cuándo | Dónde escribe | Umbral |
|---|---|---|---|
| `spill_guard` (hook `PostToolUse`) | **Antes** de que el resultado de la herramienta llegue al modelo | `<root del workbench>/spill/` (`guard.py:130`) | `spill_threshold`, 4000 caracteres por defecto |
| `TrimPolicy` (en `load`) | Al reproducir el historial antes de un resume | `<workspace>/.flower/spill/` — cadena fija relativa al workspace (`trim.py:49`, `:303`) | `min_chars`, 2000 caracteres por defecto |

Con la distribución por defecto son el mismo directorio. Pero cuando el workbench se mueve (con `-W`
para que caiga en `runs/workbench/`, o con `--isolate` para que caiga fuera del repositorio) los dos
se separan — la copia de `TrimPolicy` está siempre dentro del workspace, porque el `Read` del agente
tiene que poder alcanzarla.

Lo que `spill_guard` deja en su lugar no es una línea, sino un puntero más los **primeros 400
caracteres** (`guard.py:132-140`). Las llamadas que leen el propio archivo volcado se dejan pasar; si
no, «usa Read para leer el contenido completo» sería una frase hueca — se lee de vuelta, vuelve a
superar el umbral, vuelve a volcarse, bucle infinito (`guard.py:155-170`).

### Estructura de tablas de `sessions.db` {#sessions-db}

Tres tablas; el DDL está en `stores/sqlite.py:27-51`:

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
| `entries` | Una entrada del transcript; `payload` es el JSON original | `uid` es el `uuid` de la entrada y actúa como **clave de idempotencia**: los lotes fallidos se reintentan 3 veces y la reproducción no debe generar filas duplicadas. Las entradas sin `uuid` (títulos, etiquetas, marcas de modo) no se deduplican, de ahí el `WHERE uid IS NOT NULL` del índice único |
| `meta` | El cursor de una sesión | `next_seq` es el siguiente número de secuencia; `mtime` es un timestamp en milisegundos y es **estrictamente monótono** (`sqlite.py:72-79`) — `list_sessions` y los summaries comparten este reloj, y si no fuera monótono el SDK tomaría el camino rápido equivocado al comparar antigüedad |
| `summaries` | El sidecar de resumen de un hilo principal | **Solo participa el transcript principal**; los de los subagent no cuentan (`sqlite.py:122-123`) |

Construcción de `store_key` (`sqlite.py:54-58`): `<project_key>/<session_id>`, y para un subagent se
añade un tramo más de `subpath`. El `project_key` lo deduce el SDK de la ruta del workspace — `/`,
`_` y `.` se sustituyen todos por `-`.

Un vistazo con una muestra real
([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

Esa copia tiene 956 `entries`, 10 `meta` y 4 `summaries` — de las 10 sesiones, 4 son transcripts
principales y 6 son de subagent, y `summaries` coincide exactamente con el número de transcripts
principales.

## Las tres capas del almacén de sesiones {#会话存储}

!!! note "Las tres capas son una cadena de herencia, no una combinación opcional"
    `PruningSessionStore` hereda de `TrimmingSessionStore`, que hereda de `SqliteSessionStore`.
    `Runtime` construye **siempre** la capa más externa (`runtime.py:109-112`) y no hay ningún
    parámetro de construcción para cambiar el backend. La forma de «apagar una capa» es poner
    `enabled` a `False` en su objeto de política, no cambiar de clase.

`append` (escritura) vuelca siempre todo a disco, sin tocar un solo carácter. Las tres capas solo
afectan a `load` (la copia que se devuelve al modelo). El orden real de `load` es:

```text
SqliteSessionStore.load     lee todo de la tabla entries ordenado por seq
  → TrimmingSessionStore.expire()   resultados Bash con caducidad → sustituidos por "caducado"
  → TrimmingSessionStore.trim()     tool_result grandes y antiguos → volcados a disco + sustituidos por un puntero
    → PruningSessionStore.prune()   mensajes de error sintéticos / llamadas denegadas antiguas → entrada eliminada y cadena reenlazada
```

| Capa | Clase | Qué tira | Criterio |
|---|---|---|---|
| 1 | `SqliteSessionStore` | Nada | —— |
| 2 | `TrimmingSessionStore` | El cuerpo de resultados de herramienta grandes, resultados caducados de comandos efímeros | Tamaño + caducidad |
| 3 | `PruningSessionStore` | Restos de desconexión, llamadas denegadas antiguas | Si es un error o no |

La capa 2 es [recorte](glossary.md#裁剪) y la capa 3 es [poda](glossary.md#剪除) —
**el recorte tira por tamaño y valor, la poda tira por «es o no un error»**; no los mezcles. Las
firmas completas están en [Python API](api.md).

### `SqliteSessionStore` — los cimientos {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

Implementación en SQLite sin dependencias externas. Para cambiar a Postgres / S3 / Redis basta con
implementar el mismo protocolo; el SDK trae la suite de conformidad
`claude_agent_sdk.testing.session_store_conformance` para validarlo directamente (`sqlite.py:1-8`).

Además de los métodos del protocolo, tiene tres consultas **síncronas** para uso interno de flower:

| Método | Devuelve | Para qué |
|---|---|---|
| `projects()` | `list[str]` | Los `project_key` que existen realmente en la base. El SDK lo deduce del cwd; confírmalo con esto antes de consultar, no lo adivines |
| `has_session(project_key, session_id)` | `bool` | Solo consulta una fila de `meta`, no lee el payload. Compruébalo antes de arrancar la [continuidad](glossary.md#接续) — hacer resume de una sesión inexistente revienta después de arrancar el subproceso, cuando ya has gastado dinero y tiempo |
| `last_context(project_key, session_id, scan=60)` | `int` | Cuánto contexto vio esta sesión en su último turno. Solo escanea hacia atrás las últimas 60 entradas. Suma `input_tokens` y los dos `cache_*` — mirar solo el primero da casi 0 cuando hay acierto de caché, y subestima gravemente |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Dos reglas ortogonales. `TrimPolicy` se ocupa del **tamaño**:

| Parámetro | Tipo | Por defecto | Semántica |
|---|---|---|---|
| `keep_recent` | `int` | `20` | Los N `tool_result` más recientes conservan el texto original — el contexto en uso no debe recortarse |
| `min_chars` | `int` | `2000` | Por debajo de esto no se recorta. Sustituirlo por un puntero gastaría más tokens |
| `spill_dirname` | `str` | `".flower/spill"` | Directorio de archivo, **relativo al workspace**. Debe estar dentro del workspace o el `Read` del agente no lo alcanza |
| `enabled` | `bool` | `True` | Es `False` con `Runtime(trim=False)` (el valor por defecto) |

El cuerpo recortado se escribe como `<primeros 16 dígitos del sha256>.txt`, y en su lugar queda
`[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` (`trim.py:54-57`, `:308-317`).

`EphemeralPolicy` se ocupa de la **caducidad**: resultados como los de `git status`, `ls` o `ps` son
muy cortos y por tamaño nunca les tocaría el recorte, pero su corrección se degrada con el tiempo —
ese `git status` de hace 20 turnos no es «inútil», es que **induce a error**.

| Parámetro | Tipo | Por defecto | Semántica |
|---|---|---|---|
| `enabled` | `bool` | `True` | Se deriva de `Runtime(ephemeral=…)`; **activo por defecto** |
| `keep_recent` | `int` | `6` | Los N más recientes conservan el texto original. Mucho menos que el 20 de `TrimPolicy` — para este tipo de cosas la ventana de «reciente» ya es corta de por sí |
| `max_chars` | `int` | `2000` | Por encima de esto se lo queda `TrimPolicy` para volcarlo y archivarlo; no pasa por aquí |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Texto de sustitución |

Solo actúa sobre resultados de la herramienta **Bash**, y el comando debe coincidir con
`EPHEMERAL_CMD`. `Read` no entra: el contenido de un archivo no se distorsiona con el paso del tiempo
hasta el punto de inducir a error, y además puede ser justamente la base del razonamiento del modelo
(`trim.py:153-160`). El contenido caducado **no se vuelca a disco** — archivar un `git status`
caducado no tiene sentido; se vuelve a ejecutar y ya está.

La función de decisión es `is_ephemeral(cmd)`, y **es a la vez la lista de permisos que se le
devuelve al coordinador**: `delegate_guard(allow_glance=True)` usa la misma función
(`trim.py:63-68`, `:128-150`). Los dos conjuntos deben ser siempre iguales — si dejas pasar un
comando pero no lo recortas, un `git status` caducado ocupa el contexto para siempre; si lo recortas
pero no lo dejas pasar, el coordinador despacha un subagent por un simple `ls`, cambiando 4.3k de
coste de arranque por unas decenas de caracteres. Añadir un comando a la lista blanca es decir
ambas cosas a la vez.

**Cuándo usar cada uno**:

- Solo quieres que los restos de desconexión no entren en el contexto → no hagas nada, `Runtime` ya
  usa `PruningSessionStore` por defecto. `trim=False` únicamente deja de recortar los resultados
  grandes; la poda se sigue haciendo.
- Ejecuciones largas con salidas de herramienta muy grandes → `trim=True`. En la vía `go` el CLI ya
  lo trae activo; se apaga con `--no-trim`.
- El [coordinador](glossary.md#协调者) tiene `glance=True` → `ephemeral` debe seguir activo, por el
  motivo del párrafo anterior.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Parámetro | Tipo | Por defecto | Semántica |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Elimina los mensajes sintéticos con `isApiErrorMessage=true` o `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | Para los `tool_result` de `[Request interrupted …]` **sustituye el cuerpo, no elimina el bloque** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Texto de sustitución de lo anterior |
| `keep_denials` | `int` | `1` | Conserva las N últimas llamadas a herramienta denegadas por el hook de permisos; las anteriores se eliminan **junto con la llamada y su resultado** |

`keep_denials` es el único parámetro de construcción de `Runtime` que se propaga hasta esta capa
(`Runtime(keep_denials=N)`). El motivo de que sea 1 y no 0: la denegación más reciente es una señal
útil, evita que el modelo reintente una y otra vez el mismo comando bloqueado dentro del mismo turno.
**No lo subas** — las llamadas denegadas nunca llegaron a ejecutarse, su resultado no contiene
información alguna, y medido ocupa 273 caracteres por vez (93 caracteres de mensaje de denegación más
180 del comando muerto original); y además **induce a error**: en pruebas reales, tras leer unas
cuantas líneas de «no uses Bash directamente», el coordinador dejaba de intentar incluso el
`git status` permitido y decía directamente «Bash está restringido, despacho un agente para mirarlo»
(`prune.py:135-148`).

Tres líneas rojas estructurales; violarlas hace que la API dé error directamente:

1. **El propio bloque `tool_result` tiene que seguir ahí**, solo se puede sustituir `content`. Si
   falta uno es «Missing Tool Result Block» (`trim.py:20-22`; `prune.py:79-92`).
2. **Las entradas `isCompactSummary` / `isMeta` no se tocan** — son la única forma en que existe ese
   tramo de historia que fue compactado (`trim.py:179-181`).
3. **Al eliminar una entrada hay que enganchar sus hijos a su padre.** El transcript es una cadena
   simple de `parentUuid`; el harness recorre desde la hoja hacia atrás, y donde se rompa la cadena
   se pierde toda la historia anterior (`prune.py:95-122`). Por eso `relink()` debe recibir la lista
   completa **incluyendo** las entradas a eliminar: el filtrado lo hace ella misma.

**El texto original en SQLite no se altera ni en un carácter** — las tres capas solo afectan a «la
copia que se devuelve al modelo» (`trim.py:18`; `prune.py:8`).

## Resiliencia ante caídas de red {#韧性}

Un workflow de largo alcance corre durante horas, y la red se va a caer al menos una vez. El
comportamiento por defecto es malo: en el instante de la desconexión el harness mete en el transcript
un mensaje de assistant sintético (`model="<synthetic>"`, `isApiErrorMessage=true`) cuyo cuerpo es
`API Error: Can't reach the API server …`; ese mensaje pasa a ser la hoja de la sesión, y en el
siguiente resume se devuelve como «lo último que dijo el modelo», con lo que el modelo cree que está
hablando de un fallo de red; además se cuela en `StepResult.text` y viaja por el workflow hasta el
prompt del paso siguiente (`resilience.py:1-22`).

La capa de [resiliencia](glossary.md#韧性) hace tres cosas, y las tres son imprescindibles: sondear,
continuar en vez de empezar de cero, y mantener los errores fuera del contexto.

### Parámetros de `Resilience` {#resilience}

| Parámetro | Tipo | Por defecto | Semántica |
|---|---|---|---|
| `enabled` | `bool` | `True` | Se deriva de `Runtime(resilience=…)` |
| `max_attempts` | `int` | `6` | Cuántos intentos como máximo para un [paso](glossary.md#步骤), **incluido el primero** |
| `base_delay` | `float` | `4.0` | Punto de partida del backoff exponencial, en segundos |
| `max_delay` | `float` | `120.0` | Techo del backoff, en segundos |
| `probe_timeout` | `float` | `5.0` | Timeout de una sonda, en segundos |
| `probe_interval` | `float` | `15.0` | Cada cuánto se sondea mientras no hay red, en segundos |
| `max_offline_wait` | `float` | `3600.0` | Cuánto se espera como máximo sin red. Por defecto 1 hora — más que eso normalmente no es una oscilación, es que algo se ha roto de verdad |
| `retry_unknown` | `bool` | `True` | Reintenta también los errores que no se pueden clasificar. La mayoría de los errores desconocidos son transitorios, y los fatales ya están filtrados aparte |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | Lo que se le dice al modelo al continuar |

Fórmula del backoff (`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

Es decir, jitter de `±25%`, para evitar que en el instante en que vuelve la red un montón de procesos
se abalancen a la vez. Con los valores por defecto: el 1.º espera 4 segundos (en la práctica 3~5),
el 2.º 8 segundos (6~10), y a partir del 5.º se topa en 120 segundos (90~150).

### Estrategia de sondeo {#探针}

- **Se sondea el host:port de `ANTHROPIC_BASE_URL`**, no `api.anthropic.com` (`resilience.py:67-72`).
  Con un gateway propio, que el segundo responda no dice nada sobre el primero.
- **Solo DNS más handshake TCP**: `getaddrinfo`, luego `connect_tcp`, y cerrar de inmediato. No envía
  HTTP, no lleva credenciales, no cuesta dinero (`resilience.py:75-85`). La sonda tiene que ser
  gratis, o «sondear cada 15 segundos mientras no hay red» se convierte ella misma en la avería.
- Cualquier fallo cuenta como inalcanzable — no se distingue si ha caído el DNS o si el TCP ha sido
  rechazado.
- `wait_online()` se queda ahí esperando: devuelve `True` si vuelve la conexión, y `False` si se
  agota `max_offline_wait`. La primera vez que detecta que es inalcanzable notifica una línea,
  `<host>:<port> 不可达,等待恢复(最多 60 分钟)`, y al recuperarse notifica otra,
  `<host>:<port> 恢复,继续`, **sin spamear la pantalla entre medias** (`resilience.py:126-140`).

La sonda de credenciales previa al arranque es otra cosa: esa sí hace un `POST <BASE_URL>/v1/messages`
real, con `max_tokens=16` y timeout de 20 segundos por defecto (`env.py:126-181`). **No pongas
`max_tokens` a 1** — medido, un modelo con cadena de razonamiento forzada no tiene ni sitio para
pensar y el servidor forcejea hasta 30 segundos antes de responder; con 16 tarda solo 3.6 segundos
(`env.py:120-123`).

### Clasificación de errores {#错误分类}

`classify(text)` devuelve uno de tres valores. **Primero comprueba si es fatal**: los textos de un 401
y similares suelen incluir también palabras como "connection", y con el orden invertido te quedarías
esperando eternamente (`resilience.py:53-64`).

| Clase | Qué encaja (las regex están en `resilience.py:37-50`) | Comportamiento |
|---|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` | Parar de inmediato, sin reintentar. Por muchas veces que reintentes el resultado es el mismo, y cada intento cuesta dinero |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `timeout`, `service unavailable` | Esperar a que vuelva la red y continuar con resume |
| `unknown` | No encaja en ninguna | Con `retry_unknown=True` (por defecto) también se reintenta |

Distinguir lo reintentable de lo no reintentable es el núcleo de esta capa: **ante una oscilación de
red hay que esperar; ante una credencial incorrecta hay que parar de inmediato** — esperar
indefinidamente cuando no hay red es lo correcto, pero esperar indefinidamente porque la key está mal
escrita es quemar tiempo.

### Qué se queda fuera del contexto {#错误不进上下文}

1. **Los mensajes de error sintéticos.** `PruningSessionStore` los elimina enteros en `load` y
   reenlaza `parentUuid` (`prune.py:27-32`, `:191-195`). **En SQLite se conservan tal cual**;
   simplemente no se devuelven al modelo.
2. **En el flujo de eventos son `kind="error"` y no `"text"`**, así que no entran en
   `StepResult.text` y por tanto no viajan por el workflow hasta el prompt del paso siguiente
   (`resilience.py:17-18`).
3. **`resume_prompt` no contiene ningún detalle del error, a propósito.** El modelo necesita saber
   «te interrumpieron, sigue»; no necesita saber si fue `ENOTFOUND` o `503`. **Eso pertenece a los
   logs, no al contexto** (`resilience.py:112-113`). Para los logs, mira el campo `errors` de
   `manifest.json`.

Continuar en vez de empezar de cero: cuando ocurre el fallo ya se tiene el `session_id`, se usa
resume para retomar desde la interrupción y lo gastado antes no se pierde.

## Relacionado {#相关}

- [Línea de comandos](cli.md) — cómo se mapea cada flag a la configuración de esta página.
- [Python API](api.md) — firmas completas de `Runtime`, los tres stores y `Resilience`.
- [Despliegue](deploy.md) — ejecutar en contenedor y distribuir capacidades de dominio con plugins.
- [Glosario](glossary.md) — el significado exacto de cada término usado en esta página.
