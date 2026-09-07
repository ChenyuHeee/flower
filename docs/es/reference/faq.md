# Preguntas frecuentes y diagnóstico de fallos

Cuando algo se rompe, uno no sabe qué módulo falló — sólo sabe lo que ha visto. Por eso esta página
está agrupada por **el síntoma que observas**, no por subsistema.

Todas las entradas tienen la misma estructura: **síntoma** (lo que ves realmente) → **causa** → **qué hacer**.

Cinco de ellas son **defectos conocidos**, no decisiones de diseño. Esas entradas dicen directamente que
son un bug, dan el enlace al issue y el rodeo — no las presentan como algo intencionado.

## No instala / no arranca {#装不上}

El proceso completo de instalación está en [install.md](../getting-started/install.md#一句话安装). Esta sección
sólo recoge los casos de «ya instalé, pero el comando no arranca».

### Versión de Python inferior a 3.10 {#python-版本}

**Síntoma**: durante la instalación saltan errores de sintaxis, o pip dice directamente que no encuentra
ninguna versión que satisfaga los requisitos.

**Causa**: flower exige Python ≥ 3.10. La única dependencia de ejecución es `claude-agent-sdk`, y el binario
nativo va dentro de su wheel — así que si no instala, casi siempre es la versión del intérprete, no la red.

**Qué hacer**: confirma primero en qué intérprete quieres instalarlo.

```bash
python3 --version
```

Si es inferior a 3.10, cambia de intérprete y vuelve a instalar. El `python3` que trae el sistema a menudo no es
al que apunta `python` en tu terminal; comprobar la versión antes de instalar sale más barato que diagnosticarlo
después (ver [install.md](../getting-started/install.md#装之前确认-python)).

### Instalado, pero `flower: command not found` {#command-not-found}

**Síntoma**:

```text
zsh: command not found: flower
```

**Causa**: el paquete sí está instalado, pero el directorio donde quedó el script ejecutable no está en el `PATH`.
Eso es distinto de «no se instaló» — si `python3 -c "import flower"` no da error, el paquete está bien.

**Qué hacer**: el shebang del script `flower` es una ruta absoluta, así que basta con enlazarlo a un directorio que
ya esté en el `PATH`; no hace falta hacer source de nada.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS: añadí el PATH que indica `install.sh` y sigue dando command not found {#macos-path}

!!! warning "Problema conocido ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    Este consejo falla precisamente en la máquina que lo necesita.

**Síntoma**: en macOS ejecutas `install.sh`, sigues su última indicación y añades `~/.local/bin` al `PATH`,
reabres el terminal y `flower` sigue siendo command not found.

**Causa**: cuando se cae por la rama de respaldo de pip, el pip de macOS instala los scripts ejecutables en
`~/Library/Python/3.X/bin`, mientras que `install.sh` te dice que añadas `~/.local/bin`. Los dos directorios no
coinciden, y seguir la indicación no sirve de nada.

??? note "En qué orden elige `install.sh` el método, y el texto literal de esa indicación"

    La prioridad tiene cuatro tramos, no dos (`install.sh:35-56`):

    ```text
    1. hay uv          → uv tool install --force
    2. si no, hay pipx → pipx install --force
    3. si no           → curl astral.sh/uv/install.sh para autoarrancar uv; si funciona, instala con uv
    4. falla también   → "$PY" -m pip install --user --upgrade    ← el problema está aquí
    ```

    El texto literal de esa última indicación de PATH (`install.sh:62-68`, sólo se imprime cuando
    `command -v flower` no encuentra nada):

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` está fijado a `$HOME/.local/bin` (`install.sh:63`). Para los caminos 1 y 3 eso es correcto
    —— uv instala justo ahí; **sólo el camino 4, el respaldo de pip, no coincide en macOS**. Por eso este agujero
    sólo aparece en máquinas donde no ha funcionado ninguno de los tres primeros.

**Qué hacer**: no adivines el directorio, pregúntaselo al intérprete.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Añade al `PATH` el directorio que imprima, o enlaza desde ahí a `~/.local/bin`:

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip no instalan el mismo flower {#三种装法}

**Síntoma**: `flower` funciona, pero los cambios en el código fuente no surten efecto; o después de actualizar
sigue siendo la versión antigua; o dos terminales de la misma máquina se comportan distinto.

**Causa**: los tres métodos dejan el paquete y el script ejecutable en sitios distintos, y se ejecuta el que
aparezca primero en el `PATH`.

??? note "Dónde cae cada uno de los tres métodos"

    | Método de instalación | Script ejecutable | Cuándo usarlo |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | Vas a tocar el código. Los cambios surten efecto al instante |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Sólo lo usas, no lo tocas, y quieres un entorno aislado |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Respaldo. El directorio, en la entrada anterior |

**Qué hacer**: confirma primero cuál se está ejecutando y luego decide cuál tocas.

```bash
which -a flower                      # lista todos los homónimos que hay en el PATH
head -1 "$(which flower)"            # el shebang apunta al intérprete; el paquete está en ese entorno
```

Si vas a tocar el código usa venv + `-e .`, y no lo hagas convivir con la copia instalada por `uv` / `pipx`
—— cuando conviven, diagnosticar cuesta mucho más que reinstalar una vez
(ver [install.md](../getting-started/install.md#从源码装)).

## Credenciales y gateway {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Síntoma**:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Causa**: flower aísla la configuración de la máquina anfitriona con `setting_sources=[]`, así que las
credenciales hay que traerlas puestas. El orden completo de búsqueda está en
[config.md](config.md#凭证查找优先级).

**Qué hacer**: escríbelas en el `.env` de la raíz del repositorio, o en el entorno del proceso.

```bash
cp .env.example .env        # rellena ANTHROPIC_AUTH_TOKEN o ANTHROPIC_API_KEY
```

El `.env` ya está en gitignore. Cómo hacerlo dentro de un contenedor está en [deploy.md](deploy.md#凭证).

### Dice «flower 不读 `~/.claude/settings.json`» —— esa frase es falsa {#settings-json}

**Síntoma**: cuando las credenciales no están bien configuradas, `env.py:192` imprime esta línea:

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Causa**: esa frase no se corresponde con el código. `env.py:56-75` **sí lee** `~/.claude/settings.json`, coge
sólo los campos de credenciales y los usa como último respaldo —— que es justo lo que anuncia `install.sh`.
Esa frase sólo se imprime cuando el respaldo ya ha venido vacío, así que no hace fallar nada; pero lleva a la
gente a concluir que «flower no puede usar el token de mi Claude Code», y eso es falso. Está anotado en
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**Qué hacer**: si tienes Claude Code instalado en la máquina, no hace falta que pidas credenciales nuevas: el
respaldo las recoge solo
(ver [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
Si de verdad ves esa frase, es que en ese fichero tampoco hay ningún campo de credencial aprovechable —— escribe
el `.env` según la entrada anterior.

### No sabes con seguridad qué credenciales y qué endpoint están en vigor {#生效值}

**Síntoma**: has cambiado el `.env` y las peticiones siguen yendo al gateway antiguo; o no sabes decir qué
modelo se está usando.

**Causa**: las credenciales y el endpoint tienen varias procedencias (entorno del proceso, `.env`, respaldo), y
quién gana no se ve en el fichero de configuración, se ve en tiempo de ejecución.

**Qué hacer**: arranca una vez con `-v`. Al arrancar se imprime `describe()`: la `BASE_URL` en vigor y el mapeo de
modelos, con el token enmascarado.

```bash
flower -v
```

La tabla completa de opciones está en [cli.md](cli.md#全局开关), y la de variables en
[config.md](config.md#环境变量).

### Dejaste `KEY=` en el `.env` y ya nadie puede rellenarlo {#空值占位}

**Síntoma**: tienes el token exportado en el entorno del proceso, en el `.env` está la línea
`ANTHROPIC_AUTH_TOKEN=`, y aun así sale «faltan credenciales».

**Causa**: un valor vacío también es una asignación. El `KEY=` de la fuente de mayor prioridad **ocupa** esa clave,
y las fuentes de menor prioridad ya no la rellenan; y `check_credentials()` (definida en `env.py:184`) comprueba
«valor no vacío», así que informa de que falta igualmente. «Ocupada» y «ausente» son dos cosas distintas, pero el
síntoma es idéntico —— y ahí está lo más difícil de ver por uno mismo en esta clase de problemas.

**Qué hacer**: borra la línea entera, no dejes valores vacíos.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # lista todas las líneas con valor vacío
```

Después de borrarlas, confirma los valores en vigor con `-v`. Las reglas de análisis están en
[config.md](config.md#env-解析).

### Gateway de terceros: conecta, pero falla en la primera ronda {#网关}

**Síntoma**: 401 / 403; o dice que el nombre del modelo no existe; o hace un [handoff](glossary.md#换代) nada más
empezar, informando además del «suelo de arranque».

**Causa**: tres clases de error de configuración, cada una con su síntoma.

??? note "Cómo reconocer cada uno de los tres errores de configuración de gateway"

    | Síntoma | Casi seguro que es | Dónde tocar |
    |---|---|---|
    | 401 / 403 | La credencial es válida, pero no la emitió este gateway; o a `BASE_URL` le falta la ruta o le sobra la barra final | [config.md](config.md#凭证变量) |
    | Dice que el nombre del modelo no existe | El gateway sólo reconoce sus propios nombres de modelo y el mapeo no está configurado | [config.md](config.md#模型变量) |
    | Handoff nada más empezar, informando del «suelo de arranque» | La ventana está configurada demasiado pequeña: el umbral queda por debajo del suelo de arranque del rol (el del [coordinador](glossary.md#协调者), medido, ronda 34k) | `--window`, ver [handoff.md](../guide/handoff.md#阈值怎么算) |

**Qué hacer**: imprime los valores en vigor con `-v` antes de tocar la configuración. La ventana merece
especialmente la pena comprobarla —— el gateway de la máquina de desarrollo está configurado con
`claude-opus-5[1m]`, y calculando con 200 mil como antes se hacía un handoff cada 150 mil, cuando en realidad
llega a 950 mil: **un factor de 5**, y el trabajo de [largo horizonte](glossary.md#长程) queda troceado en pedazos.

---

## Arranca, pero se comporta mal {#行为不对}

Los síntomas de este grupo no son errores: **el comando termina, el código de salida es 0, y lo que ha hecho no
es lo que debía**. Las cuatro primeras entradas son defectos de código confirmados, con issue abierto; lo que se
da aquí es el rodeo, no el arreglo. La última es diseño intencionado.

### `flower setup` arranca un agent {#setup-跑成了-agent}

**Síntoma**: ejecutas `flower setup` esperando que te pregunte por el endpoint y el token, y en vez de eso empieza
a preguntar «qué hay que hacer», recorre el flujo completo de go y trata la palabra `setup` como la descripción
de la tarea. Al terminar no ha escrito ni una letra de credenciales.

**Causa**: el `_CMDS` de `cli.py:758` sólo lista `"go"`, `"run"` y `"once"`, y se dejó fuera `"setup"`. El paso que
completa el subcomando por defecto reescribe entonces el argv `["setup"]` a `["go", "setup"]` ——
`setup` deja de ser un subcomando y pasa a ser el primer argumento posicional de `go`, es decir, la petición misma.
**No hay ningún argv que llegue al asistente de configuración.** Reportado en
[#11](https://github.com/ChenyuHeee/flower/issues/11).

**Qué hacer**: córtalo con Ctrl-C y escribe el fichero de configuración a mano. Lo único que hacía `setup` era,
justamente, escribir en ese fichero:

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Los nombres completos de las variables y el orden de búsqueda de credenciales están en
[config.md](config.md#凭证变量).
Cuando termines, ejecuta `flower -v` en cualquier directorio: el endpoint en vigor que se imprime al arrancar es
la comprobación.

### El `？` de ancho completo no dispara la consulta lateral {#全角问号}

**Síntoma**: siguiendo lo que dice [consulta lateral](cli.md#旁路问答), escribes en el prompt de entrada
`？este directorio se puede borrar`, y no arranca el [oracle](glossary.md#旁路顾问): trata la frase como respuesta a
la pregunta en curso, o la mete tal cual en la bandeja de entrada.

**Causa**: `cli.py:733` hace dos comprobaciones `startswith("?")` seguidas, **y las dos con el mismo carácter
ASCII**. Según la intención del código, la segunda debería comprobar el `？` de ancho completo. Lo que escriben por
defecto los IME chinos es precisamente el de ancho completo —— o sea, que justo los usuarios principales de esta
función no pueden usarla. Reportado en [#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "Esto contamina los requisitos"
    Un `？` que no acierta no da error ni se descarta. Se trata como entrada normal:
    en la fase de clarify se toma como respuesta a la pregunta en curso, y el resto del tiempo va a la bandeja
    de entrada.
    **Una frase que sólo querías preguntar en privado acaba escrita en el brief.** Si te das cuenta de que has
    escrito mal, corrige en el momento `.flower/notes/需求.md`: ese fichero es la referencia para todo lo que
    viene después.

**Qué hacer**: cambia a media anchura y escribe `?`, o escribe primero el `?` de media anchura y luego vuelve al
chino para el texto.

### El coste acumulado de `once` siempre es `$0.00` y el tiempo siempre `0:00` {#once-计数为零}

**Síntoma**: `flower once` se ejecuta de principio a fin, la línea de estado inferior muestra siempre
`累计 $0.00` como coste acumulado y el cronómetro se queda en `0:00`, mientras que con el mismo modelo y el mismo
trabajo `go` sí da cifras.

**Causa**: el `render()` de `once` **crea un `Render` nuevo cada vez que recibe un evento**, y los acumuladores se
reconstruyen con él, así que cada vez se empieza desde cero. Los acumulados se ponen a cero una y otra vez; no es
que no se cuenten. Reportado en [#14](https://github.com/ChenyuHeee/flower/issues/14).

**Qué hacer**: si quieres cifras exactas usa `go`, ese camino no está afectado. Si quieres la forma de una sola
ronda de `once` y además ver la cuenta, mira `runs/manifest.json` al terminar —— el coste de cada paso está
anotado ahí, y ese registro sí es correcto. Detalles en [config.md](config.md#run-dir).

### Las skills que pones en `plugin/` nunca se cargan {#plugin-不加载}

**Síntoma**: has escrito la skill siguiendo [deploy.md](deploy.md#写一个-skill完整例子), la estructura de
directorios es correcta, y el agent se comporta como si no supiera que existe —— **sin error y sin una línea de
log**.

**Causa**: `plugin/` no se empaqueta en el wheel. En el paquete instalado, `PLUGIN_DIR` apunta a
`<site-packages>/plugin`, ese directorio no existe, y la comprobación de existencia previa a la carga lo salta en
silencio. **Los tres caminos de `install.sh` caen en esto**; sólo carga si trabajas desde un checkout del código
fuente. Reportado en [#15](https://github.com/ChenyuHeee/flower/issues/15).

**Qué hacer**: comprueba primero a dónde se resuelve realmente la ruta.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Si imprime `False`, es esto. Si quieres usar skills, ahora mismo sólo hay una salida:
**ejecutar desde un checkout del código fuente**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

El paquete instalado con `-e` apunta de vuelta al directorio del checkout, `PLUGIN_DIR` cae sobre el `plugin/`
real, y esa misma comprobación imprime `True`.

### `-T` no tiene ningún efecto visible en `go` {#trim-与-go}

**Síntoma**: añades `-T` a `flower go`, comparas con y sin él, y el comportamiento es idéntico, como si la opción
estuviera rota.

**Causa**: **esto es diseño, no un defecto.** El camino de `go` ya activa el [recorte](glossary.md#裁剪) por defecto,
así que la intención que expresa `-T` ya está satisfecha y pedirlo otra vez no cambia nada. La opción real en este
camino es la inversa, `--no-trim` —— hay que darla explícitamente para apagar el recorte. `-T` sólo es una opción
con sentido en `run` y `once`.

**Qué hacer**: si en `go` quieres confirmar que el recorte está activo, mira lo que se imprime al arrancar con
`-v`, no lo juzgues por la presencia o ausencia de `-T`; si quieres apagarlo, pasa `--no-trim`. La semántica
completa de las opciones está en [cli.md](cli.md#全局开关).

## Dice que ha terminado pero no ha terminado {#没做完}

El [goal guard](../guide/goal.md) existe precisamente para frenar esto —— el ejecutor tiene un sesgo optimista
sistemático: sabe lo que ha hecho, no sabe lo que se ha dejado. Pero el propio guard también se equivoca, y sus
errores tienen una dirección regular. Las cinco entradas siguientes se separan entre «dejó pasar lo que no debía»
y «no deja pasar nunca».

### Dice «esto no se puede verificar aquí» y lo da por bueno {#无法达成不是未达成}

**Síntoma**: el veredicto dice «en el entorno actual no se puede verificar este punto, se considera alcanzado», y
el workflow sigue adelante.

**Causa**: el [juez](glossary.md#判定者) ha mezclado «inalcanzable» y «no alcanzado» en una sola conclusión. Son
**conclusiones distintas**, y de eso trata [Son tres conclusiones, no dos](../guide/goal.md#三个结论不是两个):
«no alcanzado» es devolverlo para seguir trabajando, «inalcanzable» es **parar y preguntar a una persona**, que
decida si lo acepta, cambia el objetivo o dice que el juez se ha equivocado. Con sólo dos conclusiones
(alcanzado / no alcanzado), un objetivo que en realidad no se puede cumplir hace que el coordinador gire en vacío
ronda tras ronda hasta agotar el presupuesto.

**Qué hacer**: **«aquí no se puede verificar» nunca puede contar como alcanzado**. En las `instructions` del juez,
di con nombre y apellidos qué cuenta como imposible en tu escenario, para que dé «inalcanzable» cuando toca dar
«inalcanzable». Si de verdad no quieres que te pare a preguntar, pasa `--timeout 0`: al ser inalcanzable para
directamente y el motivo queda en disco, en lugar de colarse de rondón.

### Lee el código fuente y dice que está hecho {#判产出物}

**Síntoma**: el razonamiento del veredicto dice «el código ya implementa X», «la firma de la función cumple lo
pedido», y sin embargo no ha tocado ni el artefacto compilado, ni la salida del comando, ni el servicio
levantado.

**Causa**: al juez se le ha llevado al código fuente.
[Se juzga el artefacto, no el código fuente](../guide/goal.md#判的是产出物不是源码) —— que el código parezca
correcto y que lo entregado funcione son dos cosas distintas. Lo primero es algo de lo que el ejecutor ya estaba
convencido, y volver a convencerse no produce información nueva.

**Qué hacer**: los criterios del veredicto se escriben como afirmaciones sobre el **artefacto**. «Implementada la
función de exportación» no vale; «ejecutar `./app export out.csv` y que `out.csv` tenga 3 columnas de cabecera»
sí. Hay que escribirlo así ya en el paso de fijar objetivos, porque si no el juez sólo puede completar por su
cuenta unos criterios vagos.

### El juez no puede ejecutar comandos, así que lee el Makefile y lo aprueba {#判定者不能跑命令}

**Síntoma**: el objetivo es «construir un binario que corra en Linux» y el veredicto pasa. Haces `file` tú mismo
y el artefacto es Mach-O, no un ELF.

**Causa**: el juez es por defecto `judge(can_run=False)`, y sólo tiene en la mano **`Read` / `Glob` / `Grep`**.
Esas tres herramientas leen ficheros, pero **no ejecutan `file` ni `./app --version`**. Así que se conforma con lo
segundo mejor: lee el Makefile, ve que la rama de Darwin hace compilación cruzada y concluye que la condición se
cumple. No ha mentido; simplemente **ha encontrado lo más parecido a una prueba dentro de sus capacidades**.

??? note "Cuándo hay que activar obligatoriamente `can_run`"
    El criterio es simple: **si en el objetivo aparecen palabras del tipo «lo construido», hay que activarlo.**

    - Artefactos: binario, imagen, paquete, datos generados —— activar
    - Comportamiento: el servicio levanta, el comando devuelve 0, la salida encaja con un patrón —— activar
    - Sólo texto: si la documentación está escrita, si un campo se ha añadido al schema —— no hace falta

    En la línea de comandos es `--judge-can-run`. Al cablearlo tú mismo, cada entrada se escribe distinto, pero
    todas acaban en ese mismo parámetro de `judge()`:

    | Entrada | Cómo se pasa | Dónde está |
    |---|---|---|
    | `judge()` | `can_run=` es un parámetro formal | `roles.py:361` |
    | `with_goal()` | `can_run=` es parámetro formal y se reenvía a `judge()` | `goal.py:155` → `:170` |
    | `goal_step()` | **no tiene parámetro `can_run`**, pero cae dentro de `**spec_kw`, y esa línea es justamente `judge(..., **spec_kw)` —— llega | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, se convierte en `with_goal(can_run=…)`; `--judge-can-run` va por aquí | `starter.py:105` → `:196` |

    El precio es que el juez ejecuta comandos de verdad, y cada ronda de veredicto es más lenta y más cara; a
    cambio, verifica **la escena real** y no el manual de la escena.
    Ver [¿Puede el juez ejecutar comandos?](../guide/goal.md#判定者能不能跑命令).

**Qué hacer**: si el objetivo va de artefactos, activa `--judge-can-run`. Si no lo activas, toma «se tiene que
poder juzgar leyendo» como restricción dura al escribir los criterios —— un criterio que no se pueda escribir así
es, precisamente, un criterio que necesitaba ejecutar comandos.

### La lista de veredicto tiene una docena de puntos y nunca pasa {#清单长度}

**Síntoma**: cada ronda vuelve rechazada, con una larga lista de lo que falta; cuanto más arreglas, más aparece, y
el trabajo no acaba.

**Causa**: la lista se escribió pensando en «cuánto rigor quiero», no en «de cuántas maneras puede fallar esto».
[La longitud de la lista la decide cuántas formas de fallo hay](../guide/goal.md#清单的长度由有多少种失败方式决定):
para una tarea del tipo `git clone && make && ./app`, **con tres a cinco puntos basta** —— compila, arranca, sirve.
En el accidente real de [HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了), una tarea de «instalar
el repositorio y hacerlo funcionar» se escribió con **15 puntos**: sólo 5 verificaban si la cosa funcionaba,
6 verificaban si se habían respetado las reglas del proceso, y otros 4 **eran imposibles de verificar por
principio**.

**Qué hacer**: edita `.flower/notes/目标.md`, que es el fichero que sirve de base al veredicto. Pregunta punto por
punto «¿a qué forma de fallo corresponde esto?» y borra aquellos que no sepas responder. El paso de fijar
objetivos ya avisa de los criterios que no se pueden verificar; no te empeñes en dejar dentro los que ha señalado.

### Los límites se han escrito como criterios de veredicto {#边界不是判定项}

**Síntoma**: en la lista aparecen puntos del tipo «no se ha ejecutado `brew install`» o «no se han modificado
ficheros fuera del directorio del proyecto», y el juez, para demostrar su inocencia, se pone a mirar el mtime de
`~/.zshrc` y si alguien ha tocado el directorio `.flower/`.

**Causa**: los límites y los criterios de veredicto restringen cosas distintas, y mezclarlos fue la causa
principal de lo que pasó en HT002
([causa raíz uno](../cases/ht002.md#根因一边界被当成了判定项)).

| | Qué restringe | Cómo se cumple |
|---|---|---|
| **Límites** | **Cómo trabajas** («instala sólo dentro del directorio del proyecto», «no toques el código de negocio») | **No pasándose de la raya**, no demostrándolo a posteriori |
| **Criterios de veredicto** | **Lo que se entrega** («¿arranca?», «¿el resultado es correcto?») | Verificándolo en el momento |

Los límites son precisamente lo que la fase de clarify anima a escribir en abundancia. Trasladarlos punto por
punto a la lista significa que cada límite añadido es una comprobación más, y esa clase de comprobación casi
nunca se puede verificar —— y un criterio no verificable arrastra a toda la ronda de veredicto al fracaso.

**Qué hacer**: los límites se quedan en la sección «límites» del brief, se cumplen no pasándose de la raya y no
entran en la lista de veredicto. Si de verdad hace falta dar cuentas, una frase basta; **no lo desglosses en seis
puntos**.

---

## Contexto y coste {#上下文与花费}

En una ejecución de largo horizonte, el contexto y el dinero son el mismo problema: el contexto llega al tope y o
hay handoff o ese paso revienta; y todo lo que se repite en cada ronda hay que volver a pagarlo en todas las
rondas siguientes.

### A mitad de camino abre una sesión nueva y dice «handoff» {#换代打断}

**Síntoma** En el flujo de eventos aparece `handoff`, con `payload["phase"]` primero `near` y luego `done`, se
gasta una ronda extra en escribir el [documento de handoff](glossary.md#交接书), y después el trabajo continúa
normalmente.

**Causa** El contexto se acerca al umbral. flower **no hace compact** —— escribe el estado de la sesión actual en
un documento de handoff de cinco secciones y arranca una sesión nueva que lo lee y sigue. El
[compact](glossary.md#压缩) borraría también la información más cara, como «los caminos que no llevan a ningún
sitio», mientras que el documento de handoff es explícito, está en disco y se puede editar en cualquier momento:
lo que lee la sesión que toma el relevo es ese fichero.

**Qué hacer** Es un camino normal, no hay que hacer nada. Un handoff no cuenta como reintento —— `attempts` no
sube (cuenta fallos), el session_id quemado queda anotado en `StepResult.retired`, y el `session_id` que se
expone hacia fuera es siempre el del sucesor, que sigue vivo
(ver [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
Si de verdad quieres volver al auto-compact del SDK, usa `--no-handoff`.

??? note "De dónde sale el umbral y por qué el valor por defecto es tan agresivo"
    `at = window - headroom`. `window` **es 1 millón por defecto**, decidido por el nombre del modelo: si el
    nombre lleva `haiku` cuenta como 200 mil, y el resto como 1 millón. `headroom` es 50k por defecto —— el
    auto-compact salta en −33k, el handoff tiene que llegar antes que él, y «escribir el handoff» todavía
    necesita una ronda más; 50k cubre las dos cosas a la vez.

    Estimar de más no es un error duro: si la ventana real es más pequeña, el umbral no se alcanza nunca, la API
    rechaza la petición con «prompt demasiado largo», flower reconoce esa señal (`handoff.is_overflow()`) y hace
    el handoff en el acto con una pieza degradada ensamblada mecánicamente, sin que el paso falle
    (ver [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    Un dato medido que merece mención: el gateway de la máquina de desarrollo está configurado con
    `claude-opus-5[1m]`. Calculando con 200 mil como antes se hacía un handoff cada 150 mil, cuando en realidad
    llega a 950 mil —— **un factor de 5**, y el trabajo de largo horizonte queda troceado en pedazos.

### Handoff nada más empezar, y no para {#一开局就换代}

**Síntoma** El error menciona el «suelo de arranque», o el mismo paso hace handoff una y otra vez hasta chocar con
`max_generations=8`.

**Causa** `window` está configurado demasiado pequeño y el umbral queda por debajo del suelo de arranque de ese
rol —— el del coordinador, medido, ronda 34k, sólo con el system prompt más el índice del
[workbench](glossary.md#工作台). La sesión nueva cruza la línea en cuanto abre la boca, así que escribe el handoff,
hace handoff, vuelve a cruzar la línea, y así indefinidamente (el handoff no consume presupuesto de reintentos, y
eso es intencionado).

**Qué hacer** Ajusta `--window` a la ventana real del modelo; `-v` imprime el endpoint y el mapeo de modelos en
vigor. Una ejecución larga normal no llega a 8 generaciones, y si choca con ese límite es casi seguro por este
motivo; el propio mensaje de error lo dice así
(ver [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
Otro síntoma relacionado es «el handoff siempre sale degradado»: el motivo está en `errors`, dentro de
`runs/manifest.json`.

### Se para a mitad diciendo que el presupuesto se ha agotado {#预算到顶}

**Síntoma** El [paso](glossary.md#步骤) se detiene sin terminar, con el motivo de que se ha superado el límite de
coste.

**Causa** `AgentSpec(max_budget_usd=...)` es un **tope duro**, no un aviso blando; `Runtime.total_cost()` es el
total de esa ejecución.

**Qué hacer** Antes de subir el tope, confirma que no está girando en vacío. Si ronda tras ronda vuelve rechazado
y ninguna ronda avanza, normalmente es que el juez debería dar «inalcanzable» y está dando «no alcanzado» —— un
objetivo que en realidad no se puede cumplir quema hasta agotar el presupuesto
(ver [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Confirma que está trabajando de verdad y luego sube el tope.

### Por qué ha salido tan caro este run {#为什么这么贵}

**Síntoma** El coste supera con mucho lo previsto, pero mirando la salida no se ve en qué se ha ido el dinero.

**Causa** La cuenta no está en el contexto del modelo. El `session_id` de cada paso, el coste, el número de
reintentos y el motivo del fallo se anotan sólo en `runs/manifest.json`, **añadiendo entre procesos**. El
historial de reintentos y el texto original de los errores también están sólo ahí —— el modelo no los ve, y es
intencionado: si las llamadas denegadas se acumulan en el contexto, el coordinador aprende que «Bash lo van a
bloquear igual» y ni siquiera intenta un `git status`
(`Runtime(keep_denials=1)` ya lo limpia por defecto; no lo subas).

**Qué hacer** Abre `runs/manifest.json` y compara el coste por paso (la distribución en disco está en
[config.md#磁盘布局](config.md#磁盘布局)). Algunos valores medidos como referencia:

| | Coste |
|---|---|
| Suelo de arranque de un subagent (no amortizable) | ~4.3k tokens |
| Suelo de arranque del coordinador | ~34k tokens |
| `tests/smoke.py`, cadena completa de un solo agent | ~$0.21 |
| `tests/flow_demo.py`, tres formas de cablear el workflow | ~$0.39 |
| `tests/delegation.py`, reparto de trabajo + medición de la distribución de contexto | ~$0.71 |
| `tests/isolation.py`, tres issues en tres worktrees | ~$0.9 |

### El contexto crece más rápido que el trabajo {#上下文涨得快}

**Síntoma** En cada ronda el [task brief](glossary.md#任务书) repite la misma tanda de disciplina («lee el fichero
antes de modificarlo», «no toques el código de negocio», «pasa los tests después de cambiar»), cuando el
[ejecutor](glossary.md#执行者) ya lo estaba haciendo así.

**Causa** Todo lo que dice el coordinador entra en su propio transcript, y el transcript sólo crece. Repetir la
disciplina se paga en esa ronda **y se vuelve a pagar en todas las rondas siguientes**. Repetir algo que el otro
ya sabe tiene beneficio cero y coste permanente.

**Qué hacer** La disciplina va en el mecanismo, no en lo que se dice cada ronda: si se puede expresar con
`allowed_tools`, con la sección «límites» del brief o con el índice del workbench, que no entre en el task brief;
el task brief sólo dice qué ha cambiado en esta ronda. El propio reparto de trabajo es la capa que más ahorra
(ver [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
Al hacer resume, los resultados de herramienta antiguos y grandes se pueden cambiar por punteros a fichero con
`-T`.

## Interrupciones y continuidad {#中断与接续}

### Han matado el proceso, la máquina se ha reiniciado {#进程被杀}

**Síntoma** Se cortó a mitad y, al reabrir el terminal, no sabes cómo recuperarlo.

**Causa** No hay nada que recuperar. El [linaje](glossary.md#血缘) (`runs/lineage.json`) anota nombre de paso →
session_id y se escribe en disco al terminar cada paso; al escribir usa primero un `.tmp` y luego un reemplazo
atómico —— si lo matan a mitad no queda medio fichero.

**Qué hacer** Vuelve **al mismo directorio** y ejecuta `flower` otra vez: cada paso continúa en la sesión de la
vez anterior, no vuelve a interrogarte sobre los requisitos, no vuelve a fijar los objetivos, y hasta recuerda qué
callejones sin salida ya probó el coordinador. Si no quieres decir nada, pulsa Enter directamente
(ver [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
El juez es la excepción —— no es un `Step`, sale despachado directamente desde el gate y nunca pasa por el linaje,
así que cada ronda son un par de ojos completamente nuevos.

### Empieza siempre desde cero, no engancha con lo anterior {#接不上}

**Síntoma** Ejecutas otra vez en el mismo directorio y vuelve a interrogarte sobre los requisitos.

**Causa** Ante tres tipos de «no cuadra», flower **vuelve en silencio a empezar desde cero, sin dar error** —— la
[continuidad](glossary.md#接续) es un extra, y que falle no debería impedirte trabajar:

- `runs/lineage.json` no está, o el `workspace` que contiene no coincide con tu ruta actual (pasa si has copiado
  el directorio a otro sitio)
- La sesión ya no está en `runs/sessions.db` (has borrado la base de datos)
- El fichero de linaje está corrupto

**Qué hacer** Mira primero si `runs/lineage.json` existe y si el `workspace` es correcto
(las responsabilidades de los tres ficheros están en
[../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
Que no haya continuidad después de cambiar de directorio es **intencionado**: `project_key` se deriva de la ruta
del área de trabajo, y las sesiones antiguas no se encuentran desde la posición nueva.

### Quiero empezar de nuevo, pero sin perder el historial {#想重开}

**Síntoma** Los requisitos han cambiado de rumbo y no quieres que siga hablando de lo anterior.

**Causa** El comportamiento por defecto es continuar. En un directorio ya usado,
`flower "de paso añade resaltado de bloques de código"` no es una tarea nueva: es una frase más.

**Qué hacer** `--new`. Es **archivar, no borrar**: lo viejo se queda en `notes/archive/`. Al
[despertar](glossary.md#唤醒) se imprime primero una línea con el tamaño actual del contexto; si te parece grande,
este es también el camino.

### Se ha caído la red, ni da error ni se mueve {#断网}

**Síntoma** No aparecen eventos nuevos en la interfaz, el proceso sigue vivo, parece colgado.

**Causa** La caída de red se trata como «espera un poco», no como un fallo. flower se queda esperando: primero
sondea DNS, luego TCP, y sólo continúa cuando hay conexión
(ver [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
En HT001 esto quedó validado por un fallo real
(ver [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**Qué hacer** Espérale; con `-v` se ven los sondeos ejecutándose. Los errores acumulados durante la espera
**no entran en el contexto posterior a la continuidad** —— quedan sólo en `runs/manifest.json`, y la sesión que
toma el relevo ve una escena limpia, sin que una ristra de timeouts la desvíe.

### Dos Ctrl-C seguidos y el cierre queda a medias {#双重-ctrl-c}

**Síntoma** Cerrar con `kill` (SIGTERM) y pulsar dos veces Ctrl-C dejan escenas distintas.

**Causa** Hueco conocido. El doble Ctrl-C lanza `KeyboardInterrupt`: el `finally` de `_drive` en `cli.py` llama a
`rt.close()`, pero **no** llama a `rt.rescue()` —— sólo el manejador de SIGHUP/SIGTERM llama a `rescue()`.

**Qué hacer** El linaje se conserva por ambos caminos (se escribe atómicamente al terminar cada paso), así que al
volver a ejecutar engancha igual y este hueco no te hace perder progreso. Para un cierre completo, usa
`kill <pid>` en vez de aporrear Ctrl-C.

## Paralelismo y aislamiento {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Síntoma** Con el aislamiento activado no arranca y da `not in a git repository`.

**Causa** `worker(..., isolate=True)` se apoya en git worktree para dar a cada agent una copia privada, y si el
workspace no es un repositorio git no se puede crear.

**Qué hacer** Esto **no degrada en silencio** —— o ejecutas de verdad dentro de un repositorio, o apagas
`isolate`. El aislamiento garantiza que «varios agents modifican a la vez sin verse los árboles de trabajo entre
sí»; no te garantiza que la fusión no tenga conflictos.

### Un agent aislado no puede escribir en el workbench {#隔离写不进工作台}

**Síntoma** El subagent informa de «permiso de escritura denegado» y los scripts y artefactos no llegan a disco; o
los artefactos caen dentro de un worktree y los demás agents no los ven.

**Causa** El worktree es la **copia privada** de cada agent, y el workbench es la **capa compartida** entre
agents. Si metes lo compartido dentro de una valla privada, los demás no lo alcanzan, claro.

**Qué hacer** Con el aislamiento activado, apunta el workbench **fuera del repositorio**:

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

Cuando queda fuera del área de trabajo, `Runtime` autoriza automáticamente con `add_dirs`;
`Runtime(workbench=True)` ya se encarga de esto, pero si construyes tú el `Workbench` la autorización la das tú.

!!! warning "El workbench tiene dos posiciones por defecto, y no son la misma"
    `Workbench(workspace)` —— que es por donde van la CLI y `starter_flow()` —— coloca el workbench en
    `<workspace>/.flower`; mientras que `Runtime(workbench=True)` (es decir, `-W`) lo coloca en
    `<run_dir>/workbench`, o sea `runs/workbench`. Por eso al ejecutar `flower` obtienes un `.flower/`, y llamando
    a `Runtime(workbench=True)` desde Python **no**.

### Ejecutando flower aparece `.flower/`, pero con mi propio script no {#两个工作台默认值}

**Síntoma** El brief se ha escrito en `.flower/notes/需求.md` y el coordinador se comporta como si no lo hubiera
leído; **sin error**.

**Causa** Tienes dos objetos workbench en la mano. El brief se escribe en el directorio A, y el índice que se
inyecta en el system prompt escanea el directorio B: la promesa de «desde el arranque sabe dónde está el fichero
de requisitos» **falla en silencio**. Las dos formas de equivocarse son mudas: si construyes tú un `brief_path`
relativo al cwd del proceso, es otro directorio distinto del `<run_dir>/workbench` que crea `-W`; y sacarlo del
`Runtime` a la inversa tampoco vale —— `cli.py` llama primero a `main()` para construir el `Workflow` y sólo
después crea el `Runtime`, cuando `brief_path` ya está fijado.

**Qué hacer** Constrúyete un `Workbench` y cuelga **el mismo objeto** del `Workflow` y del `Runtime`; así la
posición queda clavada:

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` fija esto: la quinta aserción comprueba que el brief aparece en `prompt_block()`.
Además, el índice sólo se inyecta en el system prompt del **coordinador**; los subagents no lo heredan (medido:
$0.2461, `tests/prelude_live.py`) —— las rutas tiene que transmitirlas el coordinador hacia abajo, no las conoce
cada subagent automáticamente
(ver [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
