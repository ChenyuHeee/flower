# Despliegue y extensión

Llevar flower a otro sitio implica tres cosas: el contenedor (encerrar el Bash sin restricciones y, de paso, comprobar aquello de "sin depender del CLI"), los
[plugin](glossary.md#plugin) (las capacidades de dominio viajan con el repositorio, sin mirar qué hay instalado en el anfitrión) y el sitio de documentación (push a `main`
y se publica solo; `install.sh` cuelga del dominio de Pages). Las tres secciones son independientes; lee la que necesites.

## 1. Contenedor {#一容器}

### Por qué un contenedor {#为什么要容器}

**Primero, para encerrarlo.** El [worker](glossary.md#执行者) que hace el trabajo tiene **Bash sin restricciones** —— la lista blanca de Bash de flower
(`delegate_guard`) solo cubre el [main thread](glossary.md#主线程); quien sale delegado tiene que poder ejecutar pruebas, así que es intencionado.
En el contenedor solo se monta el directorio de tu proyecto; el código fuente del framework vive en `/opt/flower` dentro de la imagen, y del anfitrión no se ve nada más.

**Segundo, es en sí mismo la comprobación de la restricción de [portable](glossary.md#可移植).** En la imagen no hay Claude Code CLI,
no hay Node, solo Python y `claude-agent-sdk` —— las peticiones salen por el binario nativo que trae la propia wheel.
Si aquí arranca, "sin depender del CLI" deja de ser una afirmación sobre el papel.

Verificado en la práctica (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0):

| Qué se verifica | Resultado |
|---|---|
| ¿Hay CLI en la imagen? | `claude`, `node`, `npm`, `npx` **no existen** |
| Binario incluido | `\177ELF` (207M) |
| Petición real | Enviada por `cloud.infini-ai.com/maas` y con respuesta recibida, `$0.1741 / 1 turno` (el suelo de un solo turno con Opus 5 + ventana de 1M es exactamente ese precio) |
| Propiedad de los ficheros | Un fichero escrito en `/work` dentro del contenedor aparece como `hechenyu:staff` en el anfitrión: el mapeo es correcto |
| Visibilidad del anfitrión | Dentro del contenedor, `ls /Users` → `No such file or directory` |

### Qué lleva instalado la imagen {#镜像里装了什么}

Imagen base `python:3.13-slim`, y encima apt instala solo tres paquetes. Cada uno tiene su motivo:

| Instalado | Por qué |
|---|---|
| `python:3.13-slim` | Solo hace falta Python ≥ 3.10. Sin Node, sin CLI de claude |
| `git` | `--isolate` necesita dar un worktree a cada [subagent](glossary.md#subagent) |
| `ca-certificates` | Se pasa por una pasarela HTTPS |
| `libstdc++6` | El binario que trae el SDK es un fichero único compilado con Bun; en Linux lo necesita, y la imagen slim no lo trae |

El código fuente del framework entra en la imagen por `COPY`, **no por bind mount** —— por eso el agent del contenedor no puede tocar el código fuente del framework en el anfitrión:

| Ruta en la imagen | Contenido | De dónde viene |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, y aquí se hace `pip install .` | `COPY` |
| `/work` | Directorio de trabajo (`WORKDIR`), donde en tiempo de ejecución se monta el `$PWD` del anfitrión | `docker run -v` |

El entrypoint es `ENTRYPOINT ["flower"]` y `CMD` está vacío —— al ejecutar el contenedor sin argumentos entra en modo interactivo
(te pregunta qué quieres hacer) en lugar de imprimir `--help`. Así no hace falta entrecomillar en el shell una petición escrita en chino.

### Por qué no se puede montar el `.venv` del anfitrión {#为什么不能把宿主的-venv-挂进去}

El SDK publica wheels por plataforma, y el binario que traen es específico de cada plataforma:

```text
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude 是 Mach-O 64-bit arm64,191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Montado no funciona, así que la imagen tiene que hacer su propio `pip install`. Visto al revés, esto también es prueba de portabilidad: con el mismo
`pyproject.toml`, cambiar de plataforma cambia el binario nativo y no hay que tocar ni una línea del código del framework.

### Los dos scripts {#两个脚本}

| Script | Qué hace |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | Construye la imagen. Hace `cd` a la raíz del repositorio, `docker build -f docker/Dockerfile -t flower-box .`; con `FLOWER_MIRRORS=1` (por defecto) primero tira `python:3.13-slim` desde un registry espejo y le hace retag, y añade los `--build-arg` de pip / apt |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | Ejecuta una vez. Comprueba el fichero de credenciales → comprueba si `$PWD` se puede montar → detecta si hay TTY → `docker run` |

Los interruptores de `docker/build`, todos por variables de entorno:

| Variable | Por defecto | Semántica |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | Tag de la imagen |
| `FLOWER_MIRRORS` | `1` | `0` = no se cambia ni un espejo, todo va a upstream |
| `FLOWER_REGISTRY` | `dockerproxy.net` | Desde aquí se tira la imagen base y se le hace retag a `python:3.13-slim`, para que el `FROM` acierte en local |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | Se pasa como `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | Se pasa como `--build-arg APT_MIRROR` |

Las tres últimas solo tienen efecto con `FLOWER_MIRRORS=1` —— la rama de `FLOWER_MIRRORS=0` sencillamente no define ningún build-arg.

`docker/flowerbox` reconoce dos:

| Variable | Por defecto | Semántica |
|---|---|---|
| `FLOWER_HOME` | Un nivel por encima de la ubicación del propio script (es decir, la raíz del repositorio) | Dónde buscar el `.env`. Si no encuentra `$FLOWER_HOME/.env`, sale con 1 |
| `FLOWER_IMAGE` | `flower-box` | Qué imagen ejecutar |

`FLOWER_HOME` se deduce de la ubicación del propio script, sin rutas fijas, así que funciona clones el repositorio donde lo clones.

### Construir la imagen y levantar el contenedor {#跑起来}

```bash
docker/build                       # 一次就够
cd ~/任意项目目录                   # 必须在 $HOME 下面,见下面的挂载边界
/path/to/flower/docker/flowerbox   # 不带参数 → 它问你要做什么,不用打引号
```

Si la red a pypi.org / Docker Hub va bien, la construcción se lanza así:

```bash
FLOWER_MIRRORS=0 docker/build
```

Los argumentos de `flowerbox` son exactamente los de `flower` —— pasa `"$@"` tal cual detrás del `ENTRYPOINT`.
`--clarify-only`, `--asks N`, `--timeout segundos`, `--isolate`, `-v` valen todos; la tabla completa está en [línea de comandos](cli.md):

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "帮我做一个 X"
```

Lo que se ejecuta realmente es esta línea (`-t` solo se añade si hay TTY, ver más abajo):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### Límites del montaje y persistencia {#挂载边界与持久化}

```text
宿主 $PWD  ──挂载──>  /work       ← agent 在这里干活,产出留在宿主
镜像内                /opt/flower ← 框架源码,**没挂载**,改不到宿主
```

Por eso también es seguro ejecutarlo dentro de un subdirectorio del repositorio como `flower/human-test/HT001`: lo único montado es `HT001`,
y el código fuente del framework queda fuera del ámbito del montaje.

| Cosa | ¿Sigue estando tras salir? | Por qué |
|---|---|---|
| Todo lo que hay bajo el `$PWD` del anfitrión, incluido `runs/` y el [workbench](glossary.md#工作台) `.flower/` | Sí | Es justo el directorio que se monta como `/work` |
| Lo escrito en cualquier otra ruta del contenedor | No | `--rm`: el contenedor se borra al salir |
| Credenciales | No entran en las capas de la imagen | Van por `--env-file`; `.env` está excluido en `.dockerignore`, así que ni con `COPY . .` entraría |

!!! danger "El directorio del proyecto tiene que estar bajo `$HOME`, o los resultados se pierden en silencio"
    **colima por defecto solo monta `$HOME` dentro de la VM** (`mount | grep virtiofs` → `mount0 on /Users/<tú>`).
    Si lo ejecutas en un sitio como `/tmp`, `-v` creará un **directorio vacío** dentro de la VM, lo que escribas ahí el anfitrión no lo verá jamás,
    **y encima no da error** —— resultados, [brief](glossary.md#需求确认书), `runs/`, todo perdido. Ya pasó una vez:
    un `once` terminó, se gastaron $0.17, y `runs/` sencillamente no existía en el anfitrión.

    `flowerbox` ahora bloquea este caso: si `$PWD` está bajo `$HOME`, pasa directamente; si no, escribe un fichero sonda en `$PWD`
    y levanta otro contenedor para comprobarlo de verdad con `test -f /work/<sonda>` (si has configurado montajes adicionales, también pasa). Si no pasa, sale con 1
    y te dice `colima start --mount '<ruta>:w'`. La sonda necesita levantar un contenedor, así que antes hay que hacer `docker/build`.

### Cómo entran las credenciales en el contenedor {#凭证}

Por `docker run --env-file`, **no entran en las capas de la imagen**. `flowerbox` lee `$FLOWER_HOME/.env`,
que por defecto es el `.env` de la raíz del repositorio:

```bash
cp .env.example .env       # 填 token;.env 已被 gitignore
```

Ojo: `flower setup` escribe en `~/.config/flower/.env`, y **esa ruta `flowerbox` no la mira**.
Si ya lo configuraste con `setup` y no quieres duplicar el fichero, apunta `FLOWER_HOME` allí:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Nombres de clave, prioridad y cómo rellenar la pasarela: ver [configuración](config.md).

!!! warning "Sin TTY, las preguntas se quedan bloqueadas hasta el `--timeout`"
    `flowerbox` solo añade `-t` cuando `[ -t 0 ]` —— `docker run -t` en una tubería o en CI da directamente
    "the input device is not a TTY"; `-i` siempre hace falta, si no la stdin no entra.

    Las respuestas a las preguntas van por entrada estándar. Sin TTY, `input()` lanza `EOFError` en la primera llamada → la pregunta actual se trata como
    "entrada cerrada" y se salta, y además **el hilo de respuestas termina**, así que a partir de la segunda pregunta no hay nadie escuchando y solo queda esperar
    hasta el `--timeout` (1800 segundos por defecto). Para ejecución desatendida hay que poner explícitamente `--timeout 0`. Cuando el script detecta que no hay TTY,
    imprime antes una línea de aviso.

### git submodule {#git-submodule}

En `.gitmodules` solo hay una entrada:

| path | url | Qué es |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | El repositorio de código **producido por** aquella run de [HT001](../cases/ht001.md), guardado como registro |

Un `git clone` normal no lo trae, y `human-test/HT001` es un directorio vacío (el `-` delante en
`git submodule status` es justo ese estado). Si te importa o no:

| Qué quieres hacer | ¿Hay que inicializarlo? |
|---|---|
| Ejecutar flower, construir la imagen | **No**. `.dockerignore` excluye `human-test/`, y `Dockerfile` de por sí solo hace `COPY` de `pyproject.toml` / `flower` / `examples` |
| Revisar en local el código producido por HT001 | Sí: `git submodule update --init human-test/HT001`, o directamente `git clone --recurse-submodules` desde el principio |

### Red en China: por qué toda esa tanda de espejos {#国内网络为什么有那一堆镜像替换}

Instalar todo esto detrás del muro no es lento por ancho de banda, sino por las rutas internacionales. El `docker/build` por defecto ya sustituye todo lo que hay que sustituir,
y `FLOWER_MIRRORS=0` lo desactiva todo de golpe. Abajo están las medidas reales y el porqué de las cuatro sustituciones —— si tu red no tiene este problema, no hace falta que lo leas.

??? note "Tabla de velocidades medidas y las cuatro sustituciones (2026-09-06, macOS/arm64)"

    | Origen | Velocidad |
    |---|---|
    | `pypi.org` (índice) | 32 KB/s |
    | `files.pythonhosted.org` (ficheros de paquete) | **284 B/s** |
    | `github.com` (release asset directo) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com` (dentro de la VM) | 26 KB/s |
    | `download.docker.com` | **inalcanzable** (HTTP 000); dentro de la VM 4 KB/s |
    | `mirrors.tuna.tsinghua.edu.cn` | **inalcanzable** |
    | `mirrors.aliyun.com/pypi` (**ficheros de paquete**) | 1.4 MB/s (anfitrión) / 152 KB/s (dentro de la VM) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports` (dentro de la VM) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top` (proxy de GitHub) | **2.5 MB/s** |
    | `gh-proxy.com` (proxy de GitHub) | 1.5 MB/s |
    | `dockerproxy.net` (proxy de Docker Hub) | funciona (devuelve el manifest directamente) |

    Al medir, no confundas la **página de índice** con los ficheros de paquete: la página `mirrors.aliyun.com/pypi/simple/` da 7.4 MB/s,
    mientras que la wheel real de 95.9 MB va a 1.4 MB/s (152 KB/s dentro de la VM —— la red en espacio de usuario de colima tiene pérdidas).
    Estima los tiempos con las cifras de los ficheros de paquete.

    **Sustitución 1 —— la imagen de VM de colima.** colima no usa una imagen cloud de Ubuntu normal, sino su propia
    imagen personalizada **con docker preinstalado** (un release asset de `abiosoft/colima-core`), de modo que al arrancar la VM no hace falta
    instalar docker con apt, y eso esquiva el inalcanzable `download.docker.com`. Descárgala tú y pásasela con `--disk-image`:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # 校验:digest 从 GitHub API 拿。别跳过 —— 这是要当 VM 跑的东西
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    El proxy corta el flujo a mitad (medido: curl 56); con `-C -` reanudas y con repetirlo unas cuantas veces basta.

    **Sustitución 2 —— el apt dentro de la VM.** Incluso usando la imagen con docker preinstalado, el script de arranque de lima
    `30-install-packages.sh` sigue ejecutando un `apt-get update` para instalar `rsync` ——
    golpeando `ports.ubuntu.com` (26 KB/s) y `download.docker.com` (4 KB/s), lo que se puede atascar decenas de minutos.

    Solución (**lee `/mnt/lima-cidata/boot.sh` antes de tocar nada**: ante un script de arranque fallido solo emite `WARNING` +
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
      pkill -f "apt-get update"          # boot.sh 会继续走完并写完成标记
    '
    # colima start 随即正常退出;之后补上 rsync(现在 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    Ya de paso, añade `127.0.0.1 lima-colima` al `/etc/hosts` de la VM para quitar esa ristra de avisos `sudo: unable to resolve host`.

    **Sustitución 3 —— la imagen base.** `docker/build` primero tira `python:3.13-slim` desde `dockerproxy.net`
    y le hace retag, para que el `FROM` del Dockerfile acierte en local. Medido: `dockerproxy.net` devuelve el manifest directamente
    (HTTP 200); `docker.1ms.run` / `docker.m.daocloud.io` devuelven 401, `hub.rat.dev` 302,
    `docker.xuanyuan.me` 403.

    **Sustitución 4 —— el apt y el pip dentro del contenedor.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s) y
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Ojo: `PIP_INDEX_URL`
    es a la vez una variable de entorno que pip reconoce por sí solo, así que en cuanto se declara el `ARG`, el pip del RUN la lee ——
    funciona sin escribir explícitamente `--index-url`.

    El tiempo total de preparación (con las condiciones de red de arriba), una sola vez, ronda los 25 minutos; el grueso son los 364 MB de la imagen de VM y los 95.9 MB
    de la wheel del SDK. A partir de ahí, arrancar `flowerbox` es cuestión de segundos.

## 2. plugin {#plugin}

### Qué es un plugin y cómo lo carga el SDK {#它是什么}

Un **paquete de capacidades de dominio** que viaja con el repositorio. El código del framework no contiene ningún conocimiento de dominio; todo el conocimiento de dominio va en el directorio `plugin/`
de la raíz del repositorio, y se clona, se revisa y se etiqueta junto con el código.

El cableado del lado del SDK está en `build_options()`, en
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py),
dos líneas:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Junto con `setting_sources=[]` (explicado aparte más abajo), esta es la razón por la que flower puede a la vez ser "[portable](glossary.md#可移植)"
y "entender tu dominio": no pregunta qué hay instalado en el anfitrión, solo reconoce ese único directorio que trae el repositorio.

### Estructura de directorios {#目录布局}

| Ruta | Qué contiene | Cuándo se activa | Quién decide |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | La identidad del paquete: `name`, `description`, `version`, `author` | Se lee una vez al cargar | — |
| `plugin/skills/<name>/SKILL.md` | Conocimiento de dominio, cargado bajo demanda | **Probabilístico** —— solo se usa si el modelo lo juzga relevante | El modelo |
| `plugin/agents/<name>.md` | subagent, con ventana de contexto propia | Delegación del modelo, o indicado explícitamente en el [workflow](glossary.md#流程) | El modelo / tú |
| `plugin/hooks/hooks.json` | Intercepta llamadas a herramientas | **Determinista** —— si casa, se ejecuta | El código |
| `plugin/.mcp.json` | Conexión de herramientas externas | Se registran como herramientas, igual que las integradas | El modelo |

**La diferencia entre probabilístico y determinista es la clave de la elección, no un matiz de redacción:**

- Una skill es **conocimiento puesto ahí**. El modelo ve su `description` y solo va a leerla si le parece relevante para la tarea actual.
  El juicio de relevancia lo hace el modelo, así que la misma frase ejecutada dos veces puede usarla una vez y la otra no.
- Un hook es **código**. Si casa con el evento, se ejecuta, al margen de si el modelo quiere o si se entera.
  El [spill](glossary.md#落盘) y el [isolation](glossary.md#隔离) del propio flower son hooks, precisamente porque no pueden "activarse a veces".

Así que el criterio es uno solo: **¿esto tiene que ocurrir siempre?** Si sí —— escribe un hook. Si solo es "viene bien saberlo" ——
escribe una skill. Escribir como skill algo obligatorio equivale a apostar la disciplina a un único juicio del modelo.

Ahora mismo en el repositorio `plugin/` solo tiene dos cosas: `.claude-plugin/plugin.json` y `skills/example/SKILL.md`.
`agents/`, `hooks/` y `.mcp.json` **todavía no existen** —— si los quieres, créalos tú, con los nombres de directorio exactos de la tabla de arriba.

### Escribir una skill: ejemplo completo {#写一个-skill完整例子}

Tomemos "generar notas de versión" como ejemplo, de cero hasta confirmar que está activa.

**Paso uno: crear el directorio.** El nombre del directorio es el nombre de la skill, y coincide con el `name` del frontmatter.

```bash
mkdir -p plugin/skills/release-notes
```

**Paso dos: escribir `plugin/skills/release-notes/SKILL.md`.** El nombre del fichero tiene que ser `SKILL.md`, en mayúsculas.
El formato es frontmatter YAML + cuerpo Markdown, con dos campos en el frontmatter:

| Campo | Función |
|---|---|
| `name` | El identificador de la skill. Coincide con el nombre del directorio |
| `description` | **Que el modelo la elija o no depende solo de esta línea**. Escribe con claridad "cuándo hay que usarla", no "qué es" |

Un fichero mínimo listo para usar:

````markdown
---
name: release-notes
description: 整理发版说明时使用。当用户说"写 release notes""这版改了什么""发版"时用它。
---

# 发版说明

## 怎么取素材

```bash
git describe --tags --abbrev=0        # 上一个 tag
git log --oneline <上一个 tag>..HEAD   # 这一版的提交
```

## 输出格式

按三段分,每段是无序列表,每条一行,写用户能感知的变化,不写内部重构:

- **新增** —— 这版能干什么以前干不了的事
- **修复** —— 修了什么,一句话说清症状
- **不兼容** —— 升级要动手改什么。没有就整段不写

## 边界

- 版本号不要自己编,从 `pyproject.toml` 的 `version` 读。
- 拿不准某条提交对用户有没有感知,列出来问,不要替用户决定。
````

El cuerpo no tiene formato obligatorio —— es simplemente un texto que se lee dentro del contexto. Toma como referencia
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md):
dejar claro **cuándo usarla**, los **pasos**, **cómo debe salir la salida** y **dónde están los límites** es más útil que amontonar conocimiento de fondo.

**Paso tres: confirmar que se ha cargado.** Comprueba una sola cosa segura —— si el directorio existe o no:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Solo si imprime `/path/to/flower/plugin True` se entrará en aquel `if` de `build_options()`.
Si imprime `False`, no está cargado, y **en tiempo de ejecución no dará ningún error**; ver el aviso más abajo.

**No tomes como verificación "ejecuto una frase y miro si se invoca la skill `example`".** Las skills son probabilísticas: que el modelo no la invoque
puede significar que no está instalada o simplemente que no le pareció necesaria para la tarea —— esa señal no distingue entre las dos cosas. Además,
`build_options()` nunca define la opción `skills=` a nivel de session del SDK, y si las skills del plugin aparecen o no en la lista de opciones del
coordinator no se ha comprobado en la práctica. El `True`/`False` de `PLUGIN_DIR` de arriba sí es determinista: usa ese.

Para activar por nombre unas skills concretas en un [worker](glossary.md#执行者), usa `worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py));
el nombre es el `name` del `SKILL.md`, y el SDK también acepta la forma cualificada `nombre-de-plugin:nombre-de-skill`.

!!! warning "En una flower instalada no hay `plugin/` —— con ninguna de las tres formas de instalación"
    `PLUGIN_DIR` sube tres niveles desde `flower/core/agent.py` y entra en `plugin/`. Al ejecutar desde un checkout del código fuente, eso es el
    `plugin/` de la raíz del repositorio; pero la wheel solo empaqueta el directorio `flower` (en `pyproject.toml`,
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`), así que una vez instalada en site-packages
    `site-packages/plugin` no existe y `PLUGIN_DIR.is_dir()` es falso —— **se salta en silencio, sin error ni aviso**.

    **Esto no es un problema del contenedor, el alcance es mucho mayor.** Todas las rutas de `install.sh` —— `uv tool install`,
    `pipx install`, autoinstalar uv y luego usar uv, y el `pip install --user` de reserva —— instalan la wheel.
    Es decir, **en una flower instalada con una sola orden, el paquete de capacidades de dominio queda desactivado en silencio, siempre**. El contenedor es solo una instancia del mismo problema:
    `docker/Dockerfile` solo hace `COPY` de `pyproject.toml`, `flower/` y `examples/`; `plugin/` no entra en la imagen.

    Anotado en la [issue #15](https://github.com/ChenyuHeee/flower/issues/15). Tras instalar, ejecuta primero la orden de
    `PLUGIN_DIR` de arriba para autocomprobarlo: si imprime `False`, esta instalación no tiene paquete de capacidades de dominio. Para usarlo,
    de momento hay que ejecutar desde un checkout del código fuente.

### Por qué `setting_sources=[]` obliga a que las capacidades de dominio pasen por plugin {#setting_sources-为什么逼着领域能力走-plugin}

En la misma función está también esta línea:

```python
"setting_sources": [] if portable else ["project"],
```

El valor por defecto del SDK es `None` = leer los tres orígenes: `~/.claude/settings.json` (usuario),
`.claude/settings.json` (proyecto) y `.claude/settings.local.json` (local). flower pasa `[]` por defecto,
y los **desactiva todos**.

| | ¿Se lee? | Consecuencia |
|---|---|---|
| `~/.claude/` (anfitrión) | No | El comportamiento es igual al cambiar de máquina, no varía el resultado porque "en esta máquina lo tengo configurado" |
| `.claude/` del proyecto | No | Lo que pongas en `.claude/skills/` o `.claude/agents/` **no tiene ningún efecto** bajo flower |
| `plugin/` | Sí | La ruta está fijada en el código y viaja con el repositorio |
| Credenciales | No van por aquí | Hay que traer un `.env` propio; los bloques `env` de `~/.claude/settings.json` y `settings.local.json` solo actúan como último recurso, y **solo se toman 9 claves de credenciales**, ver [configuración](config.md) |

Que `.claude/` no tenga efecto **no es una configuración que falte, es la definición de esta restricción**: mientras se lea un solo byte del anfitrión, "el comportamiento es igual al cambiar de máquina"
deja de sostenerse. Las capacidades de dominio tienen entonces un único canal: el `plugin/` que viaja con el repositorio.

Dos interruptores (ambos en `build_options()`, y los valores por defecto son los de la portabilidad):

| Parámetro | Por defecto | Qué pasa si lo cambias |
|---|---|---|
| `portable` | `True` | Con `False` → `setting_sources` pasa a ser `["project"]` y empieza a leer el `.claude/` del proyecto (lado SDK: para leer `CLAUDE.md` hay que incluir `"project"`). La portabilidad se pierde con ello |
| `use_plugin` | `True` | Con `False` → no se monta `plugin/` en absoluto, y las capacidades de dominio dependen enteramente de `AgentSpec.instructions` |

De paso: `instructions` va por [append](glossary.md#叠加) (el `append` del `system_prompt`),
y es un canal distinto del plugin —— lo primero está en el contexto en cada turno, lo segundo se carga bajo demanda. La disciplina corta y obligatoria va en `instructions`;
el conocimiento largo y de uso ocasional, en una skill.

## 3. Sitio de documentación {#三文档站}

El sitio que estás leyendo está hecho con mkdocs-material; los ficheros fuente están en `docs/` dentro del repositorio, y con un push a `main` se publica solo.

| Pieza | Qué es |
|---|---|
| Configuración | `mkdocs.yml`, `docs_dir: docs` |
| Multiidioma | `mkdocs-static-i18n`, `docs_structure: folder` —— `docs/zh/`, `docs/en/`… el idioma por defecto es `zh` |
| Dependencias | `docs-requirements.txt` (versiones fijadas). **No es** el extra `docs` de `pyproject.toml` —— CI instala el primero |
| Construcción | `mkdocs build --strict`. Un enlace interno roto o una nav que apunta a una página inexistente hacen fallar la construcción directamente, en vez de publicar un 404 en silencio |
| Redirecciones | `hooks/redirects.py`, **después** de la construcción escribe páginas puente con meta-refresh según las URL finales, enlazando las viejas direcciones planas (`/start/`, `/workflow/`, `/case-ht001/`…) a las nuevas ubicaciones |
| Despliegue | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, publicado en GitHub Pages |

Editar la documentación en local:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # 本地预览
mkdocs build --strict         # 提交前跑一遍,和 CI 同一条命令
```

CI se dispara con un push a `main` **y** siempre que los cambios toquen estas rutas; además se puede lanzar a mano desde la página de Actions con
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

La razón es muy práctica: **`raw.githubusercontent.com` no es accesible desde China, y `*.github.io` sí** (medido).
El script vive en la raíz del repositorio; solo se copia una vez más al publicar —— no hay que mantener dos contenidos ni hace falta una CDN adicional.

Lo que hace `install.sh` por sí mismo: elegir un instalador de herramientas Python (`uv` > `pipx` > instalar `uv` > `pip --user`),
instalar flower desde GitHub y luego indicar el siguiente paso. **No toca las credenciales** —— la primera vez que ejecutes `flower` te preguntará y las guardará en
`~/.config/flower/.env`.
