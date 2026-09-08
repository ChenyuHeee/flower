# Preguntas frecuentes y resolución de problemas

Cuando algo falla, uno no sabe qué módulo se rompió — solo sabe lo que ha visto. Por eso esta
página se agrupa por **el síntoma que observas**, no por subsistema.

Cada entrada tiene la misma estructura: **síntoma** (lo que ves realmente) → **causa** → **qué hacer**.

Cinco de ellas son **defectos conocidos**, no decisiones de diseño. Esas entradas dicen
directamente que se trata de un bug, dan el enlace al issue y el rodeo — no las presentan como
algo intencionado.

## No se instala / no arranca {#装不上}

El procedimiento completo de instalación está en [install.md](../getting-started/install.md#一句话安装).
Esta sección solo recoge los casos de "se instaló, pero el comando no arranca".

### Versión de Python inferior a 3.10 {#python-版本}

**Síntoma**: durante la instalación aparecen errores de sintaxis, o pip dice directamente que no
encuentra ninguna versión que satisfaga los requisitos.

**Causa**: flower exige Python ≥ 3.10. La única dependencia en tiempo de ejecución es
`claude-agent-sdk`, y el binario nativo viene dentro de su wheel — así que si no se instala, casi
siempre es la versión del intérprete, no la red.

**Qué hacer**: primero confirma en qué intérprete lo vas a instalar.

```bash
python3 --version
```

Si es inferior a 3.10, cambia de intérprete y vuelve a instalar. El `python3` del sistema a menudo
no es el mismo al que apunta `python` en tu terminal; comprobar la versión antes de instalar sale
más barato que diagnosticar después (ver [install.md](../getting-started/install.md#装之前确认-python)).

### Instalado, pero `flower: command not found` {#command-not-found}

**Síntoma**:

```text
zsh: command not found: flower
```

**Causa**: el paquete sí se instaló, pero el directorio donde quedó el script ejecutable no está en
`PATH`. Eso es distinto de "no se instaló" — si `python3 -c "import flower"` no da error, el
paquete está bien.

**Qué hacer**: el shebang del script `flower` es una ruta absoluta, así que basta con enlazarlo
simbólicamente a un directorio que ya esté en `PATH`; no hace falta hacer source de nada.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS: añadí el PATH que indica `install.sh` y sigue dando command not found {#macos-path}

!!! warning "Problema conocido ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    Este consejo falla precisamente en la máquina que lo necesita.

**Síntoma**: en macOS ejecutas `install.sh`, añades `~/.local/bin` al `PATH` siguiendo su mensaje
final, reabres la terminal y `flower` sigue dando command not found.

**Causa**: cuando se llega al camino de respaldo con pip, el pip de macOS instala los scripts
ejecutables en `~/Library/Python/3.X/bin`, mientras que `install.sh` te dice que añadas
`~/.local/bin`. Los dos directorios no coinciden, así que seguir el mensaje no sirve de nada.

??? note "En qué orden elige `install.sh` el método de instalación, y el texto literal de ese mensaje"

    La prioridad tiene cuatro tramos, no dos (`install.sh:35-56`):

    ```text
    1. 有 uv        → uv tool install --force
    2. 否则有 pipx  → pipx install --force
    3. 否则         → curl astral.sh/uv/install.sh 自举 uv,成功则用 uv 装
    4. 自举也失败   → "$PY" -m pip install --user --upgrade    ← 出问题的是这一条
    ```

    El texto literal de ese último aviso sobre el PATH (`install.sh:62-68`, que solo se imprime
    cuando `command -v flower` no encuentra nada):

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` está fijado a `$HOME/.local/bin` (`install.sh:63`). Para los caminos 1 y 3 eso es
    correcto — uv instala ahí; **solo el camino 4, el respaldo con pip, no coincide en macOS**.
    Por eso esta trampa solo aparece en máquinas donde los tres primeros caminos fallaron.

**Qué hacer**: no adivines el directorio, pregúntaselo al intérprete.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Añade al `PATH` el directorio que imprima, o enlaza desde ahí a `~/.local/bin`:

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip no instalan el mismo flower {#三种装法}

**Síntoma**: `flower` funciona, pero los cambios en el código fuente no surten efecto; o tras
actualizar sigue siendo la versión antigua; o dos terminales de la misma máquina se comportan
distinto.

**Causa**: los tres métodos ponen el paquete y el ejecutable en sitios distintos, y se ejecuta el
primero que aparezca en `PATH`.

??? note "Dónde cae cada uno de los tres métodos"

    | Método | Script ejecutable | Cuándo usarlo |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | Cuando vas a tocar el código. Los cambios surten efecto al instante |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Solo usarlo sin tocarlo, con un entorno aislado |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Respaldo. El directorio está en la entrada anterior |

**Qué hacer**: confirma primero cuál se está ejecutando y luego decide cuál modificar.

```bash
which -a flower                      # 列出 PATH 上所有同名的
head -1 "$(which flower)"            # shebang 指向哪个解释器,包就在那个环境里
```

Si vas a tocar el código, usa venv + `-e .`, y no lo hagas convivir con la copia instalada por `uv`
o `pipx` — cuando conviven, diagnosticar cuesta mucho más que reinstalar una vez
(ver [install.md](../getting-started/install.md#从源码装)).

## Credenciales y gateway {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Síntoma**:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Causa**: flower aísla la configuración de la máquina anfitriona con `setting_sources=[]`, así que
las credenciales hay que aportarlas. El orden de búsqueda completo está en
[config.md](config.md#凭证查找优先级).

**Qué hacer**: escríbelas en el `.env` de la raíz del repositorio, o en el entorno del proceso.

```bash
cp .env.example .env        # 填 ANTHROPIC_AUTH_TOKEN 或 ANTHROPIC_API_KEY
```

`.env` ya está en gitignore. Para contenedores, ver [deploy.md](deploy.md#凭证).

### Dice «flower 不读 `~/.claude/settings.json`» — esa frase es falsa {#settings-json}

**Síntoma**: cuando las credenciales no están bien configuradas, `env.py:192` imprime:

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Causa**: esa frase no se corresponde con el código. `env.py:56-75` **sí lee**
`~/.claude/settings.json`, toma de ahí solo los campos de credenciales y los usa como último
respaldo — que es justo lo que anuncia `install.sh`. La frase solo se imprime cuando ese respaldo
ya ha quedado vacío, así que no hace fallar nada; pero lleva a concluir que "flower no puede usar
el token de mi Claude Code", y eso es falso. Anotado en
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**Qué hacer**: si tienes Claude Code instalado en la máquina, no hace falta pedir credenciales
nuevas, el respaldo las recoge solo
(ver [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
Si de verdad ves esa frase, significa que ese fichero tampoco tiene un campo de credenciales
utilizable — escribe el `.env` como en la entrada anterior.

### No estoy seguro de qué credenciales y qué endpoint están en vigor {#生效值}

**Síntoma**: has cambiado el `.env` y las peticiones siguen yendo al gateway antiguo; o no sabes
decir qué modelo se está usando.

**Causa**: las credenciales y el endpoint tienen varias fuentes (entorno del proceso, `.env`,
respaldo), y quién gana no se ve en el fichero de configuración, se ve en tiempo de ejecución.

**Qué hacer**: arranca una vez con `-v`. Al arrancar imprime `describe()`: la `BASE_URL` efectiva y
el mapeo de modelos, con el token enmascarado.

```bash
flower -v
```

La tabla completa de flags está en [cli.md](cli.md#全局开关); la de variables, en
[config.md](config.md#环境变量).

### Dejaste `KEY=` en el `.env` y ya nada aguas abajo puede rellenarlo {#空值占位}

**Síntoma**: has exportado el token en el entorno del proceso, el `.env` tiene además la línea
`ANTHROPIC_AUTH_TOKEN=`, y sigue diciendo "faltan credenciales".

**Causa**: un valor vacío también es una asignación. El `KEY=` de la fuente de mayor prioridad
**ocupa** esa clave, y las fuentes de menor prioridad ya no la rellenan; y `check_credentials()`
(definida en `env.py:184`) comprueba "valor no vacío", así que informa igualmente de la ausencia.
"Ocupada" y "ausente" son dos cosas distintas, pero el síntoma es idéntico — eso es lo que hace
que este tipo de problema sea el más difícil de ver por uno mismo.

**Qué hacer**: borra la línea entera, no dejes valores vacíos.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # 列出所有空值行
```

Después de borrar, confirma los valores efectivos otra vez con `-v`. Las reglas de parseo están en
[config.md](config.md#env-解析).

### Gateway de terceros: conecta, pero falla en la primera ronda {#网关}

**Síntoma**: 401 / 403; o dice que el nombre del modelo no existe; o hace un
[handoff](glossary.md#换代) nada más empezar y avisa del "suelo de arranque".

**Causa**: tres clases de error de configuración, cada una con su síntoma.

??? note "Cómo reconocer cada uno de los tres errores de configuración del gateway"

    | Síntoma | Casi seguro es | Dónde tocar |
    |---|---|---|
    | 401 / 403 | La credencial es válida, pero no la emitió este gateway; o a `BASE_URL` le falta la ruta o le sobra la barra final | [config.md](config.md#凭证变量) |
    | Dice que el nombre del modelo no existe | El gateway solo reconoce sus propios nombres de modelo y falta el mapeo | [config.md](config.md#模型变量) |
    | Handoff nada más empezar, con aviso de "suelo de arranque" | La ventana quedó pequeña: el umbral está por debajo del suelo de arranque del rol (el [coordinador](glossary.md#协调者) mide unos 34k) | `--window`, ver [handoff.md](../guide/handoff.md#阈值怎么算) |

**Qué hacer**: imprime primero los valores efectivos con `-v` antes de tocar la configuración. La
ventana merece especial atención — el gateway de la máquina de desarrollo está configurado con
`claude-opus-5[1m]`; calculando con 200k se cambiaba de generación cada 150k, cuando en realidad
aguanta hasta 950k: **5 veces de diferencia**, y el trabajo [long-horizon](glossary.md#长程) queda
troceado en pedazos.

---

## Arranca, pero se comporta mal {#行为不对}

Los síntomas de este grupo no son errores: **el comando termina, el código de salida es 0, y lo que
hace está mal**. Las cuatro primeras entradas son defectos de código confirmados, con issue abierto;
lo que se da aquí es el rodeo, no el arreglo. La última es diseño intencionado.

### `flower setup` arranca un agent {#setup-跑成了-agent}

**Síntoma**: ejecutas `flower setup` esperando que pregunte por el endpoint y el token, y en su
lugar empieza a preguntar "qué quieres hacer" y recorre el flujo completo de go, tomando la palabra
`setup` como descripción de la tarea. Al terminar no ha escrito ni una letra de credenciales.

**Causa**: el `_CMDS` de `cli.py:937` solo lista `"go"`, `"run"` y `"once"`, y se dejó fuera
`"setup"`. El paso que completa el subcomando por defecto reescribe entonces el argv `["setup"]`
como `["go", "setup"]` — `setup` deja de ser subcomando y pasa a ser el primer argumento posicional
de `go`, es decir, la petición en sí. **No hay ningún argv que llegue al asistente de
configuración.** Reportado en [#11](https://github.com/ChenyuHeee/flower/issues/11).

**Qué hacer**: corta con Ctrl-C y escribe el fichero de configuración directamente. Lo único que
hacía `setup` era escribir en ese fichero:

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Los nombres completos de las variables y el orden de búsqueda de credenciales están en
[config.md](config.md#凭证变量).
Después ejecuta `flower -v` en cualquier directorio: el endpoint efectivo que imprime al arrancar
es tu comprobación.

### El `？` de ancho completo no dispara la consulta al oracle {#全角问号}

**Síntoma**: escribes `？这个目录能删吗` en el prompt de entrada siguiendo la forma de
[consulta al oracle](cli.md#旁路问答), y no arranca el [oracle](glossary.md#旁路顾问): trata la
frase como respuesta a la pregunta en curso, o la mete tal cual en la bandeja de entrada.

**Causa**: `cli.py:907` hace dos comprobaciones `startswith("?")` seguidas, **y las dos usan el
mismo carácter ASCII**. Según la intención del código, la segunda debería comprobar el `？` de
ancho completo. Lo que produce por defecto un método de entrada chino es el de ancho completo — o
sea que justo el usuario principal de esta función no puede usarla. Reportado en
[#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "Esto contamina los requisitos"
    Un `？` fallido no da error ni se descarta. Se procesa como entrada normal:
    en la fase de clarify, como respuesta a la pregunta en curso; el resto del tiempo, a la bandeja
    de entrada.
    **Una frase que solo querías preguntar en privado acaba escrita en el brief.** Si te das cuenta
    del error, corrige en el momento `.flower/notes/需求.md`, que es el fichero que rige aguas
    abajo.

**Qué hacer**: cambia a ancho medio y escribe `?`, o escribe primero el `?` de ancho medio y luego
vuelve al chino para el cuerpo.

### En `once` el coste acumulado es siempre `$0.00` y el tiempo siempre `0:00` {#once-计数为零}

**Síntoma**: `flower once` corre de principio a fin y la línea de estado inferior muestra siempre
`累计 $0.00` como coste acumulado y `0:00` como cronómetro, mientras que el mismo modelo con el
mismo trabajo sí da cifras en `go`.

**Causa**: el `render()` de `once` **crea un `Render` nuevo con cada evento** que recibe, y los
acumuladores se reconstruyen con él, así que siempre parten de cero. Los acumulados se ponen a cero
una y otra vez; no es que no se contabilicen.
Reportado en [#14](https://github.com/ChenyuHeee/flower/issues/14).

**Qué hacer**: si quieres cifras exactas, usa `go`, ese camino no está afectado. Si quieres la
forma de una sola ronda de `once` y además ver la cuenta, consulta `runs/manifest.json` al terminar
— el coste de cada step está ahí, y ese registro es correcto. Detalles en
[config.md](config.md#run-dir).

### La skill que puse en `plugin/` nunca se carga {#plugin-不加载}

**Síntoma**: has escrito la skill siguiendo [deploy.md](deploy.md#写一个-skill完整例子), la
estructura de directorios es correcta, pero el agent se comporta como si no supiera que existe —
**sin errores y sin una sola línea de log**.

**Causa**: `plugin/` no se empaqueta en el wheel. En el paquete instalado, `PLUGIN_DIR` apunta a
`<site-packages>/plugin`, ese directorio no existe, y la comprobación de existencia previa a la
carga lo salta en silencio.
**Los tres caminos de `install.sh` caen en esto**; solo un repositorio con checkout del código
fuente puede cargarlas. Reportado en [#15](https://github.com/ChenyuHeee/flower/issues/15).

**Qué hacer**: comprueba primero a dónde se resuelve realmente la ruta.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Si imprime `False`, es esto. Para usar skills solo hay una vía hoy por hoy: **ejecutar desde un
checkout del código fuente**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Un paquete instalado con `-e` apunta de vuelta al directorio del checkout, `PLUGIN_DIR` cae sobre
el `plugin/` real, y volviendo a ejecutar la comprobación imprimirá `True`.

### `-T` no se nota en `go` {#trim-与-go}

**Síntoma**: le pasas `-T` a `flower go`, comparas con y sin, y el comportamiento es idéntico, como
si el flag estuviera roto.

**Causa**: **esto es diseño intencionado, no un defecto.** El camino `go` ya activa el
[trim](glossary.md#裁剪) por defecto, de modo que la intención que expresa `-T` ya está satisfecha
y pasarlo otra vez no cambia nada. En este camino el flag real es el inverso, `--no-trim` — solo
hay que pasarlo explícitamente si quieres desactivar el trim. `-T` solo es un flag con sentido en
`run` y en `once`.

**Qué hacer**: si quieres confirmar en `go` que el trim está activo, mira lo que imprime al
arrancar con `-v`, no lo juzgues por la presencia o ausencia de `-T`; si quieres desactivarlo, pasa
`--no-trim`. La semántica completa de los flags está en [cli.md](cli.md#全局开关).

## Dice que terminó pero no terminó {#没做完}

El [goal guard](../guide/goal.md) existe precisamente para frenar esto — el worker tiene un sesgo
optimista sistemático: sabe lo que ha hecho, no sabe lo que se ha dejado. Pero el propio guard
también se equivoca, y sus errores siguen un patrón. Las cinco entradas siguientes se separan en
"deja pasar lo que no debería" y "no deja pasar nunca".

### Dice "aquí no se puede verificar" y da el paso por bueno {#无法达成不是未达成}

**Síntoma**: el veredicto dice "en el entorno actual no se puede verificar este punto, se considera
alcanzado" y el workflow sigue adelante.

**Causa**: el [judge](glossary.md#判定者) ha fundido «inalcanzable» y «no alcanzado» en una sola
conclusión. Son **conclusiones distintas**, y de eso trata
[tres conclusiones, no dos](../guide/goal.md#三个结论不是两个):
«no alcanzado» es devolverlo para seguir trabajando; «inalcanzable» es **pararse y preguntar a una
persona**, para elegir entre aceptarlo, cambiar el objetivo o decir que el judge se equivocó.
Con solo dos conclusiones ("alcanzado/no alcanzado"), un objetivo que en realidad no se puede
cumplir hace que el coordinador gire en vacío ronda tras ronda hasta agotar el presupuesto.

**Qué hacer**: **"aquí no se puede verificar" nunca puede contar como alcanzado.** En las
`instructions` del judge, di explícitamente qué cuenta como imposible en tu escenario, para que dé
«inalcanzable» cuando corresponda. Si de verdad no quieres que se pare a preguntar, pasa
`--timeout 0`: ante lo inalcanzable se detiene sin más, y el motivo queda en disco, en lugar de
colarse de rondón.

### Lee el código fuente y declara el trabajo hecho {#判产出物}

**Síntoma**: el razonamiento del veredicto dice "X ya está implementado en el código", "la firma de
la función cumple lo pedido", pero no ha tocado ni el artefacto compilado, ni la salida del
comando, ni el servicio en marcha.

**Causa**: al judge lo han llevado al código fuente.
[Se juzga el artefacto, no el código fuente](../guide/goal.md#判的是产出物不是源码) — que el código
parezca correcto y que lo entregado sirva son dos cosas distintas. Lo primero es algo de lo que el
worker ya está convencido; volver a convencerse no aporta información nueva.

**Qué hacer**: los puntos del veredicto deben escribirse como afirmaciones sobre el **artefacto**.
"Se implementó la exportación" no vale; "ejecutar `./app export out.csv` y que `out.csv` tenga 3
columnas de cabecera" sí. Hay que escribirlo así ya en el paso de fijar objetivos; de lo contrario
el judge no tiene más remedio que completar por su cuenta unos puntos vagos.

### El judge no puede ejecutar comandos, así que lee el Makefile y da el visto bueno {#判定者不能跑命令}

**Síntoma**: el objetivo es "producir un binario que corra en Linux" y el veredicto es de
aprobado. Haces `file` tú mismo y el artefacto es Mach-O, ni de lejos un ELF.

**Causa**: el judge es por defecto `judge(can_run=False)` y solo tiene en la mano
**`Read` / `Glob` / `Grep`**. Con esas tres herramientas se pueden leer ficheros, pero
**no se puede ejecutar `file` ni `./app --version`**.
Así que se conforma con leer el Makefile, ve que la rama de Darwin declara compilación cruzada, y
concluye que la condición se cumple.
No ha mentido: simplemente **ha buscado lo más parecido a una evidencia dentro de sus
capacidades**.

??? note "Cuándo hay que activar `can_run`"
    El criterio es simple: **si en el objetivo aparecen palabras del tipo "lo que se construye",
    hay que activarlo.**

    - Artefactos: binarios, imágenes, paquetes, datos generados — activar
    - Comportamiento: que el servicio arranque, que el comando devuelva 0, que la salida encaje con
      un patrón — activar
    - Texto puro: si la documentación está escrita, si un campo se añadió al schema — no hace falta

    En la línea de comandos es `--judge-can-run`. Si lo cableas tú, las varias entradas se escriben
    distinto, pero todas acaban en ese mismo parámetro de `judge()`:

    | Entrada | Cómo se pasa | Origen |
    |---|---|---|
    | `judge()` | `can_run=` es un parámetro propio | `roles.py:361` |
    | `with_goal()` | `can_run=` es un parámetro y se reenvía a `judge()` | `goal.py:155` → `:170` |
    | `goal_step()` | **No tiene parámetro `can_run`**, pero cae en `**spec_kw`, y esa línea es justamente `judge(..., **spec_kw)` — llega igual | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, que se convierte en `with_goal(can_run=…)`; `--judge-can-run` va por aquí | `starter.py:105` → `:196` |

    El precio es que el judge ejecuta comandos de verdad, y una ronda de veredicto es más lenta y
    más cara; a cambio, verifica **la escena real** y no el manual de la escena. Ver
    [si el judge puede ejecutar comandos](../guide/goal.md#判定者能不能跑命令).

**Qué hacer**: si el objetivo va de artefactos, activa `--judge-can-run`. Cuando no lo actives,
toma "se puede juzgar solo leyendo" como restricción dura al escribir los puntos del veredicto — un
punto que no se puede formular así es un punto que necesita ejecutar comandos.

### La lista de veredicto tiene más de diez puntos y nunca se aprueba {#清单长度}

**Síntoma**: cada ronda vuelve rechazada con una larga lista de lo que falta, y cuanto más se
corrige más crece; el trabajo no termina.

**Causa**: la lista se escribió según "cuánto rigor quiero", no según "de cuántas formas puede
fallar esto".
[La longitud de la lista la determina cuántas formas de fallar hay](../guide/goal.md#清单的长度由有多少种失败方式决定):
para una tarea del tipo `git clone && make && ./app`, **con tres a cinco puntos basta** —
que compile, que arranque, que sirva.
En el descarrilamiento real de [HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了),
una tarea de "instalar el repositorio y ponerlo en marcha" se escribió con **15 puntos**: solo 5
verificaban si la cosa funcionaba, 6 verificaban si se habían respetado las reglas del proceso, y
otros 4 **eran imposibles de verificar en principio**.

**Qué hacer**: edita `.flower/notes/目标.md`, que es el fichero en el que se basa el veredicto.
Pregúntate punto por punto "¿a qué forma de fallo corresponde este?" y borra los que no sepas
responder. El paso de fijar objetivos ya avisa de los puntos no verificables; no te empeñes en
conservarlos.

### Los límites escritos como puntos de veredicto {#边界不是判定项}

**Síntoma**: en la lista aparecen puntos como "no se ha ejecutado `brew install`" o "no se han
modificado ficheros fuera del directorio del proyecto", y el judge, para demostrar su inocencia, se
pone a mirar el mtime de `~/.zshrc` y si alguien ha tocado el directorio `.flower/`.

**Causa**: los límites y los puntos de veredicto restringen cosas distintas; mezclarlos fue la
causa principal de aquel HT002
([causa raíz uno](../cases/ht002.md#根因一边界被当成了判定项)).

| | Qué restringe | Cómo se cumple |
|---|---|---|
| **Límites** | **Cómo trabajas** ("instala solo dentro del directorio del proyecto", "no toques el código de negocio") | **No cruzándolos**, no demostrándolo a posteriori |
| **Puntos de veredicto** | **Lo entregado** ("¿arranca?", "¿el resultado es correcto?") | Verificando en el momento |

Los límites son justamente la sección que la fase de clarify anima a rellenar. Trasladarlos uno a
uno a la lista equivale a añadir una comprobación por cada límite, y la mayoría de esas
comprobaciones no se pueden verificar — y un punto no verificable arrastra al fracaso a toda la
ronda de veredicto.

**Qué hacer**: los límites se quedan en la sección «límites» del brief, se cumplen no cruzándolos y
no entran en la lista de veredicto. Si de verdad hace falta dejar constancia, una frase basta; **no
lo desglosos en seis puntos**.

---

## Contexto y coste {#上下文与花费}

En una ejecución long-horizon, el contexto y el dinero son el mismo problema: el contexto crece
hasta el tope y entonces o hay handoff o ese step revienta; y todo lo que se repite en cada ronda
se vuelve a pagar en todas las rondas siguientes.

### A mitad de camino abre una sesión nueva y dice "handoff" {#换代打断}

**Síntoma** En el flujo de eventos aparece `handoff`, con `payload["phase"]` primero `near` y luego
`done`, se gasta una ronda extra escribiendo el [documento de handoff](glossary.md#交接书), y luego
el trabajo sigue con normalidad.

**Causa** El contexto se acercaba al umbral. flower **no hace compact** — escribe el estado de la
sesión actual como un documento de handoff de cinco secciones y arranca una sesión nueva que lo lee
y continúa. El [compact](glossary.md#压缩) borraría de paso la información más cara, como "los
caminos que no llevan a ninguna parte", mientras que el documento de handoff es explícito, está en
disco y se puede editar en cualquier momento: la sesión que toma el relevo lee exactamente ese
fichero.

**Qué hacer** Es el camino normal, no hay que hacer nada. Un handoff no cuenta como reintento —
`attempts` no sube (cuenta fallos), y el session_id quemado queda anotado en `StepResult.retired`;
el `session_id` que se ve desde fuera es siempre el sucesor que sigue vivo
(ver [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
Si de verdad quieres volver al auto-compact del SDK, usa `--no-handoff`.

??? note "De dónde sale el umbral y por qué el valor por defecto es tan agresivo"
    `at = window - headroom`. `window` es **1 millón por defecto**, decidido por el nombre del
    modelo: si el nombre lleva `haiku` cuenta como 200k, el resto como 1 millón. `headroom` es 50k
    por defecto — el auto-compact salta en −33k, el handoff tiene que adelantarse a él, y "escribir
    el handoff" requiere además otra ronda; 50k satisface ambas cosas a la vez.

    Estimar de más no es un error duro: si la ventana real es más pequeña, el umbral no se alcanza
    nunca, la petición la rechaza la API por «prompt demasiado largo», flower reconoce esa señal
    (`handoff.is_overflow()`) y hace handoff en el acto con una versión degradada montada
    mecánicamente, sin que ese step falle
    (ver [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    Un dato medido que merece mención: el gateway de la máquina de desarrollo está configurado con
    `claude-opus-5[1m]`. Calculando con 200k se cambiaba de generación cada 150k, cuando en realidad
    aguanta hasta 950k — **5 veces de diferencia**, y el trabajo long-horizon queda troceado en
    pedazos.

### Handoff nada más empezar, y no para {#一开局就换代}

**Síntoma** El error menciona el "suelo de arranque", o el mismo step hace handoff una y otra vez
hasta chocar con `max_generations=8`.

**Causa** La `window` se configuró demasiado pequeña y el umbral queda por debajo del suelo de
arranque de ese rol — en el coordinador se midió en unos 34k, que se van solo en el system prompt
más el índice del [workbench](glossary.md#工作台). La sesión nueva ya cruza la línea con la primera
frase, así que escribe el handoff, cambia de generación, vuelve a cruzarla, y así indefinidamente
(el handoff no consume presupuesto de reintentos, y eso es intencionado).

**Qué hacer** Ajusta `--window` a la ventana real del modelo; `-v` imprime el endpoint efectivo y el
mapeo de modelos. Una ejecución larga normal no llega a 8 generaciones, y si choca es casi seguro
por esto — el propio mensaje de error lo dice así
(ver [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
Otro síntoma relacionado es "el handoff siempre sale degradado": el motivo está en `errors`, dentro
de `runs/manifest.json`.

### Se detiene a medias diciendo que se agotó el presupuesto {#预算到顶}

**Síntoma** El [step](glossary.md#步骤) se detiene sin terminar, alegando que se superó el coste.

**Causa** `AgentSpec(max_budget_usd=...)` es un **techo duro**, no un aviso blando;
`Runtime.total_cost()` es el total de esa ejecución.

**Qué hacer** Antes de subir el techo, confirma que no está girando en vacío. Si ronda tras ronda
vuelve rechazado sin ningún avance, normalmente es que el judge debería haber dado «inalcanzable» y
dio «no alcanzado» — un objetivo imposible seguirá quemando presupuesto hasta el final
(ver [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Confirma que está trabajando de verdad y entonces sube el techo.

### Por qué ha salido tan cara esta ejecución {#为什么这么贵}

**Síntoma** El coste supera con mucho lo previsto, pero mirando la salida no se ve dónde se ha ido
el dinero.

**Causa** La cuenta no está en el contexto del modelo. El `session_id`, el coste, el número de
reintentos y el motivo del fallo de cada step solo se anotan en `runs/manifest.json`, **añadiéndose
entre procesos**. El historial de reintentos y el texto original de los errores también están solo
ahí — el modelo no los ve, y es a propósito: si las llamadas denegadas se acumulan en el contexto,
el coordinador aprende que "Bash se bloquea de todos modos" y ni siquiera intenta un `git status`
(`Runtime(keep_denials=1)` ya viene limpio por defecto, no lo subas).

**Qué hacer** Abre `runs/manifest.json` y contrasta el coste step a step (la disposición en disco
está en [config.md#磁盘布局](config.md#磁盘布局)).
Algunos valores medidos de referencia:

| | Coste |
|---|---|
| Suelo de arranque de un subagent (no amortizable) | ~4.3k tokens |
| Suelo de arranque del coordinador | ~34k tokens |
| `tests/smoke.py`, cadena completa de un solo agent | ~$0.21 |
| `tests/flow_demo.py`, tres formas de encadenar un workflow | ~$0.39 |
| `tests/delegation.py`, reparto + medición de la distribución de contexto | ~$0.71 |
| `tests/isolation.py`, tres issues en tres worktrees | ~$0.9 |

### El contexto crece más rápido de lo que avanza el trabajo {#上下文涨得快}

**Síntoma** En cada [task brief](glossary.md#任务书) se repite la misma tanda de disciplina ("lee el
fichero antes de modificarlo", "no toques el código de negocio", "pasa los tests al terminar"),
cuando el [worker](glossary.md#执行者) ya lo estaba haciendo.

**Causa** Todo lo que dice el coordinador entra en su propio transcript, y el transcript solo crece.
Repetir la disciplina se paga en esta ronda **y se vuelve a pagar en todas las rondas
siguientes**. Repetir algo que el otro ya sabe tiene beneficio cero y coste permanente.

**Qué hacer** La disciplina va en el mecanismo, no en lo que se dice cada ronda: lo que se pueda
expresar con `allowed_tools`, con la sección «límites» del brief o con el índice del workbench, que
no se escriba en el task brief; el task brief solo dice qué ha cambiado en esta ronda. El propio
reparto de trabajo es la capa que más ahorra
(ver [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
Al hacer resume, los resultados grandes de herramientas antiguos se pueden cambiar por punteros a
fichero con `-T`.

## Interrupciones y continuidad {#中断与接续}

### Mataron el proceso, se reinició la máquina {#进程被杀}

**Síntoma** Se cortó a mitad y, al reabrir la terminal, no sabes cómo recuperarlo.

**Causa** No hay nada que recuperar. El [linaje](glossary.md#血缘) (`runs/lineage.json`) anota
nombre de step → session_id, cae a disco al terminar cada step, y al escribir primero escribe un
`.tmp` y luego hace un reemplazo atómico — que lo maten a mitad no deja medio fichero.

**Qué hacer** Vuelve **al mismo directorio** y ejecuta `flower` otra vez; cada step retoma la
sesión anterior: no vuelve a interrogarte sobre los requisitos, no vuelve a fijar los objetivos, y
hasta recuerda qué callejones sin salida probó el coordinador. Si no quieres decir nada, pulsa
Enter directamente
(ver [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
El judge es la excepción — no es un `Step`, se despacha directamente desde el gate y nunca pasa por
el linaje, así que cada ronda son ojos completamente nuevos.

### Empieza siempre desde cero, no engancha con lo anterior {#接不上}

**Síntoma** Vuelves a ejecutar en el mismo directorio y te interroga otra vez sobre los requisitos.

**Causa** Ante tres tipos de "no cuadra", flower **vuelve a empezar desde cero en silencio, sin dar
error** — la [continuidad](glossary.md#接续) es un extra, y que falle no debe impedirte trabajar:

- `runs/lineage.json` no está, o el `workspace` que hay dentro no coincide con tu ruta actual
  (ocurre si copiaste el directorio a otro sitio)
- La sesión ya no está en `runs/sessions.db` (borraste la base de datos)
- El fichero de linaje está corrupto

**Qué hacer** Mira primero si existe `runs/lineage.json` y si su `workspace` es correcto
(las responsabilidades de los tres ficheros están en
[../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
Que no haya continuidad tras cambiar de directorio es **intencionado**: `project_key` se deriva de
la ruta del workspace, y una sesión antigua no se encuentra desde la ubicación nueva.

### Quiero empezar de nuevo sin perder el historial {#想重开}

**Síntoma** Los requisitos han cambiado de dirección y no quieres que siga hablando del asunto
anterior.

**Causa** El comportamiento por defecto es continuar. En un directorio ya usado,
`flower "顺便支持代码块高亮"` no es una tarea nueva, es una frase más.

**Qué hacer** `--new`. **Archiva, no borra**: lo antiguo se queda en `notes/archive/`.
Al hacer [wake](glossary.md#唤醒) informa primero, en una línea, del tamaño actual del contexto; si
te parece grande, este es también el camino.

### Se cayó la red, ni da error ni se mueve {#断网}

**Síntoma** No aparecen eventos nuevos en la interfaz, el proceso sigue vivo, parece atascado.

**Causa** Una caída de red se trata como "espera un poco", no como un fallo. flower se queda
esperando: primero sondea DNS, luego TCP, y solo continúa cuando hay conexión
(ver [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
En HT001 esto quedó validado por una avería real
(ver [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**Qué hacer** Espera; con `-v` se ven los sondeos en marcha. Los errores acumulados durante la
espera **no entran en el contexto posterior a la continuidad** — se quedan solo en
`runs/manifest.json`, y la sesión que toma el relevo ve una escena limpia, sin que una ristra de
timeouts la desvíe.

### Dos Ctrl-C seguidos y el cierre queda incompleto {#双重-ctrl-c}

**Síntoma** Cerrar con `kill` (SIGTERM) y pulsar dos veces Ctrl-C dejan escenas distintas.

**Causa** Hueco conocido. El doble Ctrl-C lanza `KeyboardInterrupt`: en `cli.py`, el `finally` de
`_drive` llama a `rt.close()`, pero **no** llama a `rt.rescue()` — solo los manejadores de
SIGHUP/SIGTERM llaman a `rescue()`.

**Qué hacer** El linaje queda a salvo por ambos caminos (cae a disco atómicamente al terminar cada
step), así que volver a ejecutar engancha igual y este hueco no te hace perder progreso. Para un
cierre completo, usa `kill <pid>` en lugar de aporrear Ctrl-C.

## Paralelismo y aislamiento {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Síntoma** Con el aislamiento activado no arranca y da `not in a git repository`.

**Causa** `worker(..., isolate=True)` usa git worktree para darle a cada agent una copia privada, y
si el workspace no es un repositorio git no se puede crear.

**Qué hacer** Esto **no degrada en silencio** — o ejecutas de verdad dentro de un repositorio, o
desactivas `isolate`. El aislamiento garantiza que "varios agents modifican a la vez sin verse el
árbol de trabajo del otro"; no te garantiza que la fusión no tenga conflictos.

### Un agent aislado no puede escribir en el workbench {#隔离写不进工作台}

**Síntoma** El subagent informa de "permiso de escritura denegado" y los scripts y artefactos no
caen a disco; o los artefactos caen dentro de un worktree y los demás agents no los ven.

**Causa** El worktree es una **copia privada** de cada agent; el workbench es una **capa compartida**
entre agents. Si metes lo compartido dentro de una valla privada, los demás no pueden alcanzarlo.

**Qué hacer** Con el aislamiento activado, apunta el workbench **fuera del repositorio**:

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

Cuando queda fuera del workspace, `Runtime` autoriza automáticamente con `add_dirs`;
`Runtime(workbench=True)` ya se ocupa de ello, pero si construyes tú el `Workbench`, la
autorización la tienes que dar tú.

!!! warning "El workbench tiene dos ubicaciones por defecto, y no son la misma"
    `Workbench(workspace)` — que es por donde van la CLI y `starter_flow()` — pone el workbench en
    `<workspace>/.flower`; mientras que `Runtime(workbench=True)` (o sea, `-W`) lo pone en
    `<run_dir>/workbench`, es decir `runs/workbench`.
    Así que ejecutar `flower` te da un `.flower/`, y llamar a `Runtime(workbench=True)` desde Python
    **no**.

### Ejecutando flower aparece `.flower/`, pero con mi propio script no {#两个工作台默认值}

**Síntoma** El brief se ha escrito claramente en `.flower/notes/需求.md` y el coordinador actúa
como si no lo hubiera leído; **sin errores**.

**Causa** Tienes dos objetos workbench entre manos. El brief se escribe en el directorio A, y el
índice que se inyecta en el system prompt escanea el directorio B: la promesa de "desde el primer
momento sabe dónde está el fichero de requisitos" **falla en silencio**. Las dos formas de
equivocarse son mudas: si te montas un `brief_path` relativo al cwd del proceso, ese es un
directorio distinto del `<run_dir>/workbench` que crea `-W`; y tampoco vale intentar sacarlo del
`Runtime` hacia atrás — `cli.py` llama primero a `main()` para construir el `Workflow`, y solo
después crea el `Runtime`, cuando `brief_path` ya está fijado desde hace rato.

**Qué hacer** Construye tú un `Workbench` y pasa **el mismo objeto** tanto al `Workflow` como al
`Runtime`; así la ubicación queda clavada:

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` fija esto: la quinta aserción comprueba que el brief aparece en
`prompt_block()`. Además, el índice solo se inyecta en el system prompt del **coordinador**, los
subagents no lo heredan (medido en $0.2461, `tests/prelude_live.py`) — las rutas se las tiene que
transmitir el coordinador, no las conoce cada subagent automáticamente
(ver [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
