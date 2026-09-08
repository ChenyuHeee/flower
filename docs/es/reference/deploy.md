# Despliegue y extensión

Llevar flower a otro sitio implica resolver tres cosas: el contenedor (encerrar el Bash sin restricciones y, de paso, verificar aquello de «sin CLI»),
el [plugin](glossary.md#plugin) (las capacidades de dominio viajan con el repositorio, sin depender de lo que haya instalado la máquina anfitriona) y el sitio de documentación (push a `main`
y se publica solo; `install.sh` cuelga del dominio de Pages). Las tres secciones son independientes, léelas según necesites.

## 1. Contenedor {#一容器}

### Por qué un contenedor {#为什么要容器}

**Primero, para encerrarlo.** El [ejecutor](glossary.md#执行者) que hace el trabajo tiene **Bash sin restricciones** —— la lista blanca de Bash de flower
(`delegate_guard`) solo cubre el [hilo principal](glossary.md#主线程); quien sale delegado tiene que poder correr los tests, así que es intencionado.
En el contenedor solo se monta tu directorio de proyecto; el código del framework está dentro de la imagen en `/opt/flower`, y el resto del anfitrión no se ve.

**Segundo, porque es en sí mismo la verificación de la restricción de [portabilidad](glossary.md#可移植).** En la imagen no hay Claude Code CLI,
no hay Node, solo Python y `claude-agent-sdk` —— las peticiones salen a través del binario nativo que trae el propio wheel.
Si arranca aquí, «sin CLI» deja de ser una afirmación sobre el papel.

Verificado en la práctica (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0):

| Qué se verifica | Resultado |
|---|---|
| ¿Hay CLI en la imagen? | `claude`, `node`, `npm`, `npx` **no existen** |
| Binario incluido | `\177ELF` (207M) |
| Petición real | Enviada por `cloud.infini-ai.com/maas` y con respuesta, `$0.1741 / 1 turno` (ese es el suelo de un solo turno con Opus 5 + ventana de 1M) |
| Propiedad de los archivos | Los archivos escritos en `/work` dentro del contenedor aparecen como `hechenyu:staff` en el anfitrión, mapeo correcto |
| Visibilidad del anfitrión | Dentro del contenedor `ls /Users` → `No such file or directory` |

### Qué lleva instalado la imagen {#镜像里装了什么}

Imagen base `python:3.13-slim`, y encima apt instala solo tres paquetes. Cada uno tiene su motivo:

| Instalado | Por qué |
|---|---|
| `python:3.13-slim` | Basta con Python ≥ 3.10. Sin Node, sin claude CLI |
| `git` | `--isolate` necesita dar un worktree a cada [subagent](glossary.md#subagent) |
| `ca-certificates` | Se sale por un gateway HTTPS |
| `libstdc++6` | El binario que trae el SDK es un archivo único compilado con Bun; en Linux lo necesita, y la imagen slim no lo trae |

El código del framework entra en la imagen mediante `COPY`, **no por bind mount** —— por eso el agente dentro del contenedor no puede tocar el código del framework del anfitrión:

| Ruta en la imagen | Contenido | Origen |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, y ahí se hace `pip install .` | `COPY` |
| `/work` | Directorio de trabajo (`WORKDIR`), en ejecución se monta el `$PWD` del anfitrión | `docker run -v` |

El entrypoint es `ENTRYPOINT ["flower"]` y `CMD` está vacío —— al correr el contenedor sin argumentos entra en entrada interactiva
(te pregunta qué quieres hacer) en vez de imprimir `--help`. Así no hace falta entrecomillar una petición en lenguaje natural en el shell.

### Por qué no se puede montar el `.venv` del anfitrión {#为什么不能把宿主的-venv-挂进去}

El SDK publica wheels por plataforma, y el binario que incluye es específico de la plataforma:

```text
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude 是 Mach-O 64-bit arm64,191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Montarlo no funciona, así que la imagen tiene que hacer su propio `pip install`. Visto al revés, esto es también la prueba de la portabilidad: el mismo
`pyproject.toml`, al cambiar de plataforma cambia el binario nativo, y el código del framework no cambia ni una línea.

### Los dos scripts {#两个脚本}

| Script | Qué hace |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | Construye la imagen. `cd` a la raíz del repositorio, `docker build -f docker/Dockerfile -t flower-box .`; con `FLOWER_MIRRORS=1` (por defecto) primero descarga `python:3.13-slim` desde un mirror de registry y le hace retag, y añade los `--build-arg` de pip / apt |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | Ejecuta una vez. Comprueba el archivo de credenciales → comprueba si `$PWD` se puede montar → determina si hay TTY → `docker run` |

Los interruptores de `docker/build` van todos por variables de entorno:

| Variable | Por defecto | Significado |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | Tag de la imagen |
| `FLOWER_MIRRORS` | `1` | `0` = no se cambia ningún mirror, todo va contra upstream |
| `FLOWER_REGISTRY` | `dockerproxy.net` | De aquí se baja la imagen base y se le hace retag a `python:3.13-slim` para que el `FROM` acierte en local |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | Se pasa como `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | Se pasa como `--build-arg APT_MIRROR` |

Las tres últimas solo tienen efecto con `FLOWER_MIRRORS=1` —— la rama de `FLOWER_MIRRORS=0` directamente no define ningún build-arg.

`docker/flowerbox` reconoce dos:

| Variable | Por defecto | Significado |
|---|---|---|
| `FLOWER_HOME` | Un nivel por encima de la ubicación del propio script (es decir, la raíz del repositorio) | Dónde buscar el `.env`. Si no encuentra `$FLOWER_HOME/.env`, sale con 1 |
| `FLOWER_IMAGE` | `flower-box` | Qué imagen ejecutar |

`FLOWER_HOME` se deduce de la ubicación del propio script, sin rutas fijas, así que funciona clones el repositorio donde lo clones.

### Ponerlo en marcha {#跑起来}

```bash
docker/build                       # 一次就够
cd ~/任意项目目录                   # tiene que estar bajo $HOME, ver los límites de montaje más abajo
/path/to/flower/docker/flowerbox   # sin argumentos → te pregunta qué quieres hacer, sin comillas
```

Si la red llega bien a pypi.org / Docker Hub, la construcción se hace así:

```bash
FLOWER_MIRRORS=0 docker/build
```

Los argumentos de `flowerbox` son exactamente los de `flower` —— pasa `"$@"` tal cual detrás del `ENTRYPOINT`.
`--clarify-only`, `--asks N`, `--timeout segundos`, `--isolate`, `-v` se pasan igual; la tabla completa está en [línea de comandos](cli.md):

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "帮我做一个 X"
```

Lo que se ejecuta realmente es esta línea (`-t` solo se añade si hay TTY, ver abajo):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### Límites de montaje y persistencia {#挂载边界与持久化}

```text
宿主 $PWD  ──montaje──>  /work       ← el agente trabaja aquí, los resultados quedan en el anfitrión
镜像内                /opt/flower ← código del framework, **sin montar**, no puede tocar el anfitrión
```

Por eso también es seguro ejecutarlo en un subdirectorio dentro del repositorio como `flower/human-test/HT001`: lo único montado es `HT001`,
y el código del framework queda fuera del ámbito del montaje.

| Cosa | ¿Sobrevive al salir? | Por qué |
|---|---|---|
| Todo lo que hay bajo el `$PWD` del anfitrión, incluidos `runs/` y el [banco de trabajo](glossary.md#工作台) `.flower/` | Sí | Es justo el directorio montado como `/work` |
| Lo escrito en otras rutas dentro del contenedor | No | `--rm`, el contenedor se borra al salir |
| Credenciales | No entran en las capas de la imagen | Van por `--env-file`; `.env` está excluido en `.dockerignore`, así que ni con `COPY . .` entrarían |

!!! danger "El directorio del proyecto tiene que estar bajo `$HOME`, o los resultados se pierden en silencio"
    **colima por defecto solo monta `$HOME` dentro de la VM** (`mount | grep virtiofs` → `mount0 on /Users/<tú>`).
    Si lo ejecutas en sitios como `/tmp`, `-v` creará un **directorio vacío** dentro de la VM, y lo que escribas ahí el anfitrión no lo verá nunca,
    **y además no da error** —— resultados, [brief](glossary.md#需求确认书) y `runs/` se pierden enteros. Pisado una vez:
    una ejecución `once` completa, $0.17 gastados, y `runs/` sencillamente no existía en el anfitrión.

    `flowerbox` ahora bloquea este caso: si `$PWD` está bajo `$HOME` pasa directamente; si no, escribe un
    archivo sonda en `$PWD` y levanta un contenedor para comprobarlo de verdad con `test -f /work/<sonda>` (así también pasa si tienes montajes extra). Si no pasa, sale con 1
    y te indica `colima start --mount '<ruta>:w'`. La sonda necesita levantar un contenedor, así que primero hay que hacer `docker/build`.

### Credenciales {#凭证}

Van por `docker run --env-file`, **no entran en las capas de la imagen**. `flowerbox` lee `$FLOWER_HOME/.env`,
que por defecto es el `.env` de la raíz del repositorio:

```bash
cp .env.example .env       # 填 token;.env 已被 gitignore
```

Ojo: `flower setup` escribe en `~/.config/flower/.env`, y **esa ruta `flowerbox` no la mira**.
Si ya lo configuraste con `setup` y no quieres duplicarlo, apunta `FLOWER_HOME` allí:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Nombres de claves, prioridades y cómo rellenar el gateway están en [configuración](config.md).

!!! warning "Sin TTY, las preguntas se quedan colgadas hasta el `--timeout`"
    `flowerbox` solo añade `-t` cuando `[ -t 0 ]` —— `docker run -t` en una tubería o en CI da directamente
    «the input device is not a TTY»; `-i` hace falta siempre, si no stdin no entra.

    Las respuestas a las preguntas van por entrada estándar. Sin TTY, `input()` lanza `EOFError` a la primera → la pregunta actual se trata como
    «entrada cerrada» y se salta, y además **el hilo de respuesta termina**, de modo que a partir de la segunda pregunta ya no hay nadie que conteste y solo queda esperar
    a que se agote el `--timeout` (1800 segundos por defecto). Para ejecuciones desatendidas hay que poner explícitamente `--timeout 0`. El script, cuando detecta que no hay TTY,
    imprime primero una línea de aviso.

### git submodule {#git-submodule}

En `.gitmodules` hay una sola entrada:

| path | url | Qué es |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | El repositorio de código **producido por** la ejecución de [HT001](../cases/ht001.md), guardado como archivo |

Un `git clone` normal no lo descarga, y `human-test/HT001` queda como un directorio vacío (el `-` delante en
`git submodule status` es justo ese estado). Si hay que ocuparse de él:

| Qué quieres hacer | ¿Hay que inicializarlo? |
|---|---|
| Ejecutar flower, construir la imagen | **No**. `.dockerignore` excluye `human-test/`, y el `Dockerfile` de todos modos solo hace `COPY` de `pyproject.toml` / `flower` / `examples` |
| Consultar en local el código producido en HT001 | Sí: `git submodule update --init human-test/HT001`, o directamente `git clone --recurse-submodules` desde el principio |

### Redes en China continental: por qué todo ese montón de mirrors {#国内网络为什么有那一堆镜像替换}

Al instalar esto detrás del cortafuegos, lo lento no es el ancho de banda sino la ruta internacional. El `docker/build` por defecto ya sustituye todo lo que hay que sustituir,
y `FLOWER_MIRRORS=0` lo apaga todo de golpe. Abajo están los datos medidos y el porqué de las cuatro sustituciones —— si tu red no tiene este problema, no hace falta leerlo.

??? note "Tabla de velocidades medidas y las cuatro sustituciones (2026-09-06, macOS/arm64)"

    | Origen | Velocidad |
    |---|---|
    | `pypi.org` (índice) | 32 KB/s |
    | `files.pythonhosted.org` (archivos de paquete) | **284 B/s** |
    | `github.com` (release asset directo) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com` (dentro de la VM) | 26 KB/s |
    | `download.docker.com` | **inalcanzable** (HTTP 000); dentro de la VM 4 KB/s |
    | `mirrors.tuna.tsinghua.edu.cn` | **inalcanzable** |
    | `mirrors.aliyun.com/pypi` (**archivos de paquete**) | 1.4 MB/s (anfitrión) / 152 KB/s (dentro de la VM) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports` (dentro de la VM) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top` (proxy de GitHub) | **2.5 MB/s** |
    | `gh-proxy.com` (proxy de GitHub) | 1.5 MB/s |
    | `dockerproxy.net` (proxy de Docker Hub) | Funciona (devuelve el manifest directamente) |

    Al medir, no confundas la **página de índice** con los archivos de paquete: la página de `mirrors.aliyun.com/pypi/simple/` da 7.4 MB/s,
    mientras que el wheel real de 95.9 MB va a 1.4 MB/s (152 KB/s dentro de la VM —— la red en espacio de usuario de colima tiene pérdidas).
    Estima los tiempos con los números de los archivos de paquete.

    **Sustitución 1 —— la imagen de VM de colima.** colima no usa una imagen cloud de Ubuntu normal, sino una imagen propia
    **con docker preinstalado** (un release asset de `abiosoft/colima-core`), así que al arrancar la VM no hace falta instalar docker con apt,
    lo que esquiva el inalcanzable `download.docker.com`. Descárgala tú y pásasela con `--disk-image`:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # verificación: el digest se obtiene de la API de GitHub. No te lo saltes —— esto se va a ejecutar como VM
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    El proxy corta el flujo a mitad (medido: curl 56); con `-C -` se reanuda y basta con reintentar unas cuantas veces.

    **Sustitución 2 —— apt dentro de la VM.** Aunque uses la imagen con docker preinstalado, el script de boot de lima
    `30-install-packages.sh` ejecuta igualmente un `apt-get update` para instalar `rsync` ——
    golpea `ports.ubuntu.com` (26 KB/s) y `download.docker.com` (4 KB/s), y se queda colgado decenas de minutos.

    Solución (**lee antes `/mnt/lima-cidata/boot.sh` y luego actúa**: ante un script de boot fallido solo emite `WARNING` +
    `CODE=1` y continúa, y al final **siempre** escribe `/run/lima-boot-done`, así que hacer fallar ese paso es seguro):

    ```bash
    export LIMA_HOME=~/.colima/_lima
    limactl shell colima -- sudo sh -c '
      cat > /etc/apt/sources.list.d/ubuntu.sources <<EOF
    Types: deb
    URIs: https://mirrors.ustc.edu.cn/ubuntu-ports/
    Suites: noble noble-updates noble-backports noble-security
    Components: main restricted universe multiverse
    Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
    EOF
      sed -i "s|https://download.docker.com|https://mirrors.ustc.edu.cn/docker-ce|g" \
          /etc/apt/sources.list.d/docker.list
      pkill -f "apt-get update"          # boot.sh seguirá hasta el final y escribirá la marca de completado
    '
    # colima start sale a continuación con normalidad; después se instala rsync (ahora a 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    De paso, añade `127.0.0.1 lima-colima` al `/etc/hosts` de la VM para quitar esa ristra de avisos de `sudo: unable to resolve host`.

    **Sustitución 3 —— la imagen base.** `docker/build` baja primero `python:3.13-slim` desde `dockerproxy.net`
    y le hace retag, para que el `FROM` del Dockerfile acierte en local. Medido: `dockerproxy.net` devuelve el manifest directamente
    (HTTP 200); `docker.1ms.run` / `docker.m.daocloud.io` devuelven 401, `hub.rat.dev` 302,
    `docker.xuanyuan.me` 403.

    **Sustitución 4 —— apt y pip dentro del contenedor.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s) y
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Ojo: `PIP_INDEX_URL`
    es a la vez una variable de entorno que pip reconoce por sí mismo, así que basta con declarar el `ARG` para que el pip del RUN la lea ——
    funciona sin escribir `--index-url` explícitamente.

    La preparación inicial completa (con las condiciones de red de arriba) lleva unos 25 minutos, y el grueso son los 364 MB de la imagen de VM y los 95.9 MB
    del wheel del SDK. Después, arrancar `flowerbox` es cuestión de segundos.

## 2. plugin {#plugin}

### Qué es {#它是什么}

Un **paquete de capacidades de dominio** que viaja con el repositorio. El código del framework no contiene ningún conocimiento de dominio; todo el conocimiento de dominio vive en el directorio `plugin/`
de la raíz del repositorio, y se clona, se revisa y se etiqueta junto con el código.

El cableado por el lado del SDK está en `build_options()` de
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py),
dos líneas:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Junto con `setting_sources=[]` (que se explica aparte más abajo), esta es la razón de que flower pueda ser a la vez «[portable](glossary.md#可移植)»
y «entender tu dominio»: no pregunta qué hay instalado en la máquina anfitriona, solo reconoce este directorio que llega con el repositorio.

### Estructura de directorios {#目录布局}

| Ruta | Qué contiene | Cuándo aplica | Quién decide |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | Identidad del paquete: `name`, `description`, `version`, `author` | Se lee una vez al cargar | — |
| `plugin/skills/<name>/SKILL.md` | Conocimiento de dominio, cargado bajo demanda | **Probabilístico** —— solo se usa si el modelo lo considera relevante | El modelo |
| `plugin/agents/<name>.md` | subagent, ventana de contexto propia | Delegación del modelo, o indicado explícitamente en el [flujo](glossary.md#流程) | El modelo / tú |
| `plugin/hooks/hooks.json` | Intercepta llamadas a herramientas | **Determinista** —— si coincide, se ejecuta | El código |
| `plugin/.mcp.json` | Conexión de herramientas externas | Se registran como herramientas, igual que las integradas | El modelo |

**La diferencia entre probabilístico y determinista es la clave de la elección, no un matiz de redacción:**

- Una skill es **conocimiento puesto ahí**. El modelo ve su `description` y solo la lee si le parece relevante para la tarea actual.
  El juicio de relevancia lo hace el modelo, así que la misma petición ejecutada dos veces puede usarla una vez y la otra no.
- Un hook es **código**. Si el evento coincide, se ejecuta, con independencia de lo que el modelo quiera o sepa. El [volcado a disco](glossary.md#落盘)
  y el [aislamiento](glossary.md#隔离) del propio flower son hooks, precisamente porque no pueden aplicar «a veces».

Así que el criterio es uno solo: **¿esto tiene que ocurrir siempre?** Si sí —— escribe un hook. Si solo es «viene bien saberlo» ——
escribe una skill. Escribir como skill algo obligatorio equivale a apostar la disciplina a un único juicio del modelo.

Ahora mismo en el repositorio `plugin/` solo tiene dos cosas: `.claude-plugin/plugin.json` y `skills/example/SKILL.md`.
`agents/`, `hooks/` y `.mcp.json` **todavía no existen** —— si los quieres, créalos tú, con los nombres de directorio exactos de la tabla de arriba.

### Escribir una skill: ejemplo completo {#写一个-skill完整例子}

Tomamos «generar notas de versión» como ejemplo, de cero hasta confirmar que está activa.

**Paso 1: crear el directorio.** El nombre del directorio es el nombre de la skill, y debe coincidir con el `name` del frontmatter.

```bash
mkdir -p plugin/skills/release-notes
```

**Paso 2: escribir `plugin/skills/release-notes/SKILL.md`.** El nombre del archivo tiene que ser `SKILL.md`, en mayúsculas.
El formato es frontmatter YAML + cuerpo Markdown, con dos campos en el frontmatter:

| Campo | Para qué sirve |
|---|---|
| `name` | Identificador de la skill. Coincide con el nombre del directorio |
| `description` | **Que el modelo la elija o no depende solo de esta línea**. Deja claro «cuándo hay que usarla», no «qué es» |

Un archivo mínimo que funciona directamente:

````markdown
---
name: release-notes
description: Se usa al preparar notas de versión. Úsala cuando el usuario diga «escribe las release notes», «qué ha cambiado en esta versión» o «publicar versión».
---

# Notas de versión

## Cómo obtener el material

```bash
git describe --tags --abbrev=0        # el tag anterior
git log --oneline <上一个 tag>..HEAD   # los commits de esta versión
```

## Formato de salida

Divide en tres bloques; cada bloque es una lista sin ordenar, una línea por entrada, describiendo cambios perceptibles por el usuario, sin refactors internos:

- **Nuevo** —— qué puede hacer esta versión que antes no se podía
- **Corregido** —— qué se ha arreglado, con el síntoma explicado en una frase
- **Incompatible** —— qué hay que cambiar a mano al actualizar. Si no hay nada, se omite el bloque entero

## Límites

- No te inventes el número de versión, léelo del campo `version` de `pyproject.toml`.
- Si no tienes claro si un commit es perceptible para el usuario, ponlo en la lista y pregunta, no decidas por el usuario.
````

El cuerpo no tiene formato obligatorio —— es simplemente un texto que se lee al contexto. Sigue el estilo de
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md):
dejar claro **cuándo se usa**, **los pasos**, **cómo debe ser la salida** y **dónde están los límites** rinde más que acumular conocimiento de fondo.

**Paso 3: confirmar que se ha cargado.** Comprueba una sola cosa cierta —— si el directorio está o no:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Solo si imprime `/path/to/flower/plugin True` se entrará en ese `if` de `build_options()`.
Si imprime `False` es que no se ha cargado, y **en ejecución no dará ningún error**; ver la advertencia de abajo.

**No uses «ejecuto una petición a ver si se invoca la skill `example`» como verificación.** Las skills son probabilísticas: que el modelo no la invoque
puede significar que no está instalada, o simplemente que no le pareció necesaria para la tarea —— esa señal no distingue ambos casos. Además,
`build_options()` nunca fija la opción `skills=` a nivel de sesión del SDK, así que si las skills del plugin acaban apareciendo o no en la lista de opciones
del coordinador no está verificado. El `True`/`False` de `PLUGIN_DIR` de arriba sí es cierto; usa ese.

Para habilitar skills concretas en un [ejecutor](glossary.md#执行者) determinado, usa `worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py));
los nombres son los `name` de `SKILL.md`, y el SDK también acepta la forma cualificada `nombre-de-plugin:nombre-de-skill`.

!!! warning "El flower instalado no tiene `plugin/` —— ninguna de las tres formas de instalar lo tiene"
    `PLUGIN_DIR` sube tres niveles desde `flower/core/agent.py` y entra en `plugin/`. Ejecutando desde un checkout del código fuente eso es el
    `plugin/` de la raíz del repositorio; pero el wheel solo empaqueta el directorio `flower` (en `pyproject.toml`,
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`), y una vez instalado en site-packages
    `site-packages/plugin` no existe, `PLUGIN_DIR.is_dir()` es falso —— **se salta en silencio, sin error ni aviso**.

    **Esto no es un problema del contenedor, su alcance es mucho mayor.** Todas las rutas de `install.sh` —— `uv tool install`,
    `pipx install`, autoinstalar uv y luego usar uv, y el `pip install --user` de respaldo —— instalan el wheel.
    Es decir, **en un flower instalado con una sola línea, el paquete de capacidades de dominio queda inactivo en silencio, siempre**. El contenedor es solo una instancia del mismo problema:
    `docker/Dockerfile` solo hace `COPY` de `pyproject.toml`, `flower/` y `examples/`; `plugin/` no entra en la imagen.

    Registrado en [issue #15](https://github.com/ChenyuHeee/flower/issues/15). Tras instalar, ejecuta primero el comando de
    `PLUGIN_DIR` de arriba para autocomprobarlo: si imprime `False`, esta instalación no tiene el paquete de capacidades de dominio. Para usarlo,
    por ahora solo queda ejecutar desde un checkout del código fuente.

### Por qué `setting_sources=[]` obliga a que las capacidades de dominio pasen por plugin {#setting_sources-为什么逼着领域能力走-plugin}

En la misma función hay también esta línea:

```python
"setting_sources": [] if portable else ["project"],
```

El valor por defecto del SDK es `None` = leer las tres fuentes: `~/.claude/settings.json` (usuario),
`.claude/settings.json` (proyecto) y `.claude/settings.local.json` (local). flower pasa `[]` por defecto,
y las **desactiva todas**.

| | ¿Se lee? | Consecuencia |
|---|---|---|
| `~/.claude/` (máquina anfitriona) | No | El comportamiento es igual al cambiar de máquina, sin resultados distintos por «yo aquí lo tenía configurado» |
| `.claude/` del proyecto | No | Lo que pongas en `.claude/skills/` o `.claude/agents/` **no tiene ningún efecto** bajo flower |
| `plugin/` | Sí | La ruta está fija en el código y viaja con el repositorio |
| Credenciales | No van por aquí | Hay que traer un `.env` propio; los bloques `env` de `~/.claude/settings.json` y `settings.local.json` solo sirven como último respaldo, y **solo se toman 9 claves de credenciales**, ver [configuración](config.md) |

Que `.claude/` no tenga efecto **no es una configuración olvidada, es la definición de esta restricción**: mientras se lea un solo byte de la máquina anfitriona, «el comportamiento es igual al cambiar de máquina»
deja de ser cierto. Así que a las capacidades de dominio les queda un único canal —— el `plugin/` que viaja con el repositorio.

Dos interruptores (ambos en `build_options()`, con los valores por defecto de la variante portable):

| Parámetro | Por defecto | Qué pasa si lo cambias |
|---|---|---|
| `portable` | `True` | Con `False` → `setting_sources` pasa a `["project"]` y empieza a leer el `.claude/` del proyecto (por el lado del SDK: para leer `CLAUDE.md` hay que incluir `"project"`). La portabilidad se pierde con ello |
| `use_plugin` | `True` | Con `False` → no se monta `plugin/` en absoluto, y las capacidades de dominio dependen enteramente de `AgentSpec.instructions` |

De paso: `instructions` va por [append](glossary.md#叠加) (el `append` del `system_prompt`),
y es un canal distinto del plugin —— el primero está en el contexto en cada turno, el segundo se carga bajo demanda. La disciplina corta y obligatoria va en `instructions`;
el conocimiento largo y de uso ocasional va en una skill.

## 3. Sitio de documentación {#三文档站}

Este sitio que estás leyendo está hecho con mkdocs-material, los archivos fuente están en `docs/` del repositorio, y con un push a `main` se publica solo.

| Pieza | Qué es |
|---|---|
| Configuración | `mkdocs.yml`, `docs_dir: docs` |
| Multiidioma | `mkdocs-static-i18n`, `docs_structure: folder` —— `docs/zh/`, `docs/en/`… el idioma por defecto es `zh` |
| Dependencias | `docs-requirements.txt` (versiones fijadas). **No** el extra `docs` de `pyproject.toml` —— CI instala el primero |
| Construcción | `mkdocs build --strict`. Enlaces internos rotos o entradas de nav apuntando a páginas inexistentes hacen fallar la construcción, en vez de publicar un 404 en silencio |
| Redirecciones | `hooks/redirects.py`, **después** de la construcción escribe páginas puente con meta-refresh según las URL finales, conectando las direcciones planas antiguas (`/start/`, `/workflow/`, `/case-ht001/`…) con las nuevas ubicaciones |
| Despliegue | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, publicado en GitHub Pages |

Editar la documentación en local:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # vista previa local
mkdocs build --strict         # ejecútalo antes de commitear, es el mismo comando que CI
```

CI se dispara con un push a `main` **y** cambios que caigan en estas rutas; además se puede lanzar a mano desde la página de Actions con
`workflow_dispatch`:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### Por qué `install.sh` se publica desde Pages {#installsh-为什么从-pages-发}

Al final del paso de construcción hay una línea:

```yaml
- run: cp install.sh site/install.sh
```

El script de instalación se mete en el artefacto del sitio, así que cuelga del dominio del sitio de documentación, y la instalación en una línea queda así:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

El motivo es muy práctico: **`raw.githubusercontent.com` no es accesible desde China continental, y `*.github.io` sí** (medido).
El script vive en la raíz del repositorio, simplemente se copia una vez más al publicar —— no hay que mantener dos contenidos ni hace falta una CDN adicional.

Lo que hace `install.sh` por su cuenta: elegir un instalador de herramientas Python (`uv` > `pipx` > instalar `uv` > `pip --user`),
instalar flower desde GitHub, y luego indicar el siguiente paso. **No toca las credenciales** —— la primera vez que ejecutes `flower` te preguntará y las guardará en
`~/.config/flower/.env`.
