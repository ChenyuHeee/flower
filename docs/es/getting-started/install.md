# Instalación

Instalar flower solo requiere Python ≥ 3.10. La única dependencia en tiempo de ejecución es `claude-agent-sdk`: el binario nativo que envía las peticiones viene dentro de su wheel, así que **no hace falta instalar Node ni el CLI de Claude Code**. Esta página recorre el camino desde cero: instalación en una línea, instalación desde el código fuente, la primera configuración de credenciales y un comando que demuestra que «de verdad quedó bien instalado». Cuando funcione, sigue con [Inicio rápido](quickstart.md).

## Antes de instalar: comprueba Python {#装之前确认-python}

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Con una salida como `True 3.13.7` basta. Si imprime `False` o directamente no existe `python3`, instálalo primero (`brew install python` / `apt install python3`); en caso contrario el script de instalación sale de inmediato.

| Hace falta | No hace falta |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31` también lo comprueba por su cuenta) | Node.js |
| Red hasta el endpoint de la API | El CLI de Claude Code |
| Una API key o un token de gateway (se da después de instalar) | Los ajustes de `~/.claude/` de la máquina anfitriona (las credenciales son la única excepción, ver abajo) |

Nombre del paquete `flower`, versión `0.1.0`, única dependencia en tiempo de ejecución `claude-agent-sdk>=0.2.152` (`pyproject.toml:2-6`). `mkdocs-material` solo se usa en CI para construir el sitio de documentación; ejecutar flower no lo necesita.

## Instalación en una línea {#一句话安装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Al terminar, la terminal debería mostrar esto (colores aparte):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

Lo importante es esa línea `== 装好了 <ruta absoluta>`: es el resultado de que el propio script haya ejecutado un `command -v flower` (`install.sh:60-61`). Si imprime la ruta, `flower` ya está en el PATH.

### Qué hace realmente el instalador {#安装器实际做了什么}

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) hace solo tres cosas: elegir un instalador de herramientas Python, instalar desde GitHub y decirte el siguiente paso. **No toca ni una letra de tus credenciales** (`install.sh:7-8`). La fuente de instalación es fija: `git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

El instalador prueba en orden y se detiene en la primera opción que funcione (`install.sh:33-57`):

| Orden | Condición | Comando real | Dónde queda el ejecutable |
|---|---|---|---|
| 1 | `uv` está en el PATH | `uv tool install --force <REPO>` | El directorio bin de herramientas de uv, normalmente `~/.local/bin/flower` |
| 2 | No hay `uv`, pero sí `pipx` | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | No hay ninguno de los dos | Primero instala uv con `curl -LsSf https://astral.sh/uv/install.sh \| sh`; si se instala, vuelve al caso 1 | Igual que el caso 1 |
| 4 | En el caso 3 uv tampoco se instaló | `python3 -m pip install --user --upgrade <REPO>` | El directorio de scripts de usuario — **en macOS no es `~/.local/bin`** |

Los cuatro casos instalan el mismo console script: `flower = "flower.cli:main"` (`pyproject.toml:12`). Una vez instalado también puedes invocarlo con `python -m flower.cli`, con el mismo efecto (`cli.py:1451-1452`).

!!! warning "Volver a ejecutar el script de instalación sobrescribe a la fuerza, sin pedir confirmación"
    Los tres comandos de instalación llevan respectivamente `--force`, `--force` y `--upgrade` (`install.sh:37`, `:40`, `:54`). Volver a ejecutarlo pisa directamente la instalación existente — así es precisamente como se actualiza, pero no esperes que te pregunte antes.

### Cómo poner el comando `flower` en el PATH {#flower-命令怎么上-path}

Cuando `command -v flower` no encuentra nada, el script sugiere añadir `$HOME/.local/bin` a `~/.zshrc` o `~/.bashrc` (`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Tanto `uv tool install` como `pipx install` colocan ahí el ejecutable, así que para ellos ese aviso es correcto. **Pero para el cuarto caso (`pip install --user`) no necesariamente**: el directorio de ese mensaje está escrito a fuego, mientras que el directorio de scripts de usuario de pip depende de la plataforma. En macOS es `~/Library/Python/3.13/bin`. Compruébalo tú mismo:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

Sale algo como `/Users/you/Library/Python/3.13/bin`: añade ese directorio al PATH en lugar de `~/.local/bin`, y luego reabre la terminal o haz `source`.

## Instalar desde el código fuente {#从源码装}

Si quieres leer el código, modificar el framework o ejecutar las verificaciones offline de `tests/`, instala desde el código fuente:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

Al terminar, `.venv/bin/flower --help` debería imprimir esas líneas de usage.

El shebang de ese ejecutable dentro del venv es una **ruta absoluta**, así que no hace falta activar nada: con un enlace simbólico funciona desde cualquier directorio:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Si `~/.local/bin` está en el PATH, teclear `flower` desde cualquier directorio de proyecto usará el intérprete de ese venv y este código fuente.

La instalación desde código fuente añade además otra ubicación para las credenciales: el **`.env` en la raíz del repositorio** (quinto lugar en el orden de búsqueda, ver [Configuración · Prioridad de búsqueda de credenciales](../reference/config.md#凭证查找优先级)). Durante el desarrollo:

```bash
cp .env.example .env        # rellena ANTHROPIC_AUTH_TOKEN
```

`.env` ya está ignorado por `.gitignore`, no entra al control de versiones. Un flower instalado con pip / pipx / uv **no** dispone de esta ubicación —vive en site-packages, no hay «raíz del repositorio»—, así que en ese caso se usa el fichero global de credenciales que se explica abajo.

## Actualización automática {#自动更新}

flower todavía itera rápido, así que **la copia instalada con pip / pipx / uv se actualiza sola por defecto**: quien reporta un bug con una versión de hace tres días puede estar reportando algo ya corregido, y ambos lados pierden el tiempo. Aquí no hay una pregunta del tipo «¿lo activas o no?»: está activo por defecto, y para apagarlo se usa una variable de entorno.

Lo que hace (`update.py:116-129`):

1. En cada arranque de `flower`, consulta en un **hilo en segundo plano** el último commit de `main` en GitHub (`update.py:70-80`). El flujo principal no espera ni un segundo — esa es la primera invariante.
2. Si difiere del commit instalado localmente, ejecuta el comando de actualización acorde a la forma original de instalación: si hay `uv`, `uv tool install --force`; si hay `pipx`, `pipx install --force`; si no hay ninguno, `pip install --user --upgrade` (`update.py:83-93`).
3. **Aunque se instale, no reemplaza el proceso en curso**: la versión nueva se usa en la siguiente ejecución de `flower` (`update.py:113`). Que te cambien el código a mitad de ejecución es de los fallos más difíciles de rastrear.
4. Límite de frecuencia: como mucho una consulta cada 24 horas, con la marca de tiempo en `~/.config/flower/.update` (`update.py:32`, `:36-37`, `:124`).
5. **Los fallos son siempre silenciosos**. Sin red, GitHub caído, instalación fallida — nada de eso interrumpe tu trabajo (`update.py:79`, `:108-110`).

**Ejecutar desde el código fuente (git) no se ve afectado.** El paso del comando de actualización mira primero si hay un `.git` en el repositorio; si lo hay, devuelve `None` directamente y no hace nada (`update.py:83-87`): tu workspace lo gestiona `git`, no él. En entornos no interactivos (stdin no es una terminal, p. ej. una tubería o CI) también se salta por completo (`update.py:121`).

Para apagarlo:

```bash
export FLOWER_NO_UPDATE=1
```

Cualquier valor no vacío sirve (`update.py:33`, `:121`). Úsalo en CI, en entornos sin red o cuando quieras reproducir el comportamiento de una versión antigua.

## Primera ejecución: configurar credenciales {#第一次跑配凭证}

Las tres entradas de ejecución `go`, `run` y `once` llaman al principio a `ensure_credentials()` (`cli.py:1192`, `:1160`, `:1225`), con dos comprobaciones:

1. **Si existen**: busca según la prioridad y, si no encuentra nada, te pregunta en el acto.
2. **Si sirven**: lanza una llamada real a la API. Una petición mínima con `max_tokens=16` (`env.py:120-123`), casi sin coste. Un token caducado o una URL de gateway mal escrita no se detectan mirando variables de entorno; sin sonda, revientan varios minutos después.

Sin credenciales, la primera ejecución de `flower` se detiene en esta pantalla (`cli.py:1358-1388`):

```text
== 配置 flower ========================================
第一次用?给一次凭证就行。
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   >

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   >

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   >

+ 存好了:/Users/you/.config/flower/.env
```

La pregunta 1 es obligatoria; si la dejas vacía imprime en rojo `没给 token,取消。` y sale. Las preguntas 2 y 3 se pueden pasar con Enter. Con el endpoint oficial, deja la 2 vacía; con un gateway de terceros, pon su dirección raíz, **sin `/v1`**: la sonda de flower golpea `<BASE_URL>/v1/messages` (`env.py:162`).

Claves que se escriben tras responder (`cli.py:1378-1386`):

| Lo que introduces | Clave escrita en `.env` |
|---|---|
| El token empieza por `sk-ant-` | `ANTHROPIC_API_KEY` |
| Cualquier otro token | `ANTHROPIC_AUTH_TOKEN` |
| URL del gateway no vacía | `ANTHROPIC_BASE_URL` |
| Nombre de modelo no vacío | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`: **las tres a la vez** |

La ubicación del fichero es `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), se **sobrescribe entero** y al terminar se le aplica `chmod 0o600` (`cli.py:1336-1347`). Ese es el fichero del «configúralo una vez y vale en todas partes»: al cambiar de directorio de proyecto no hay que reconfigurar nada. El significado de cada variable está en [Configuración](../reference/config.md#环境变量).

### Si ya tienes Claude Code instalado, puede que no te pregunte nada {#本机装过-claude-code-的话可能一个问题都不问}

La búsqueda de credenciales tiene un **último recurso**: lee `~/.claude/settings.json` y después `~/.claude/settings.local.json`, y toma de sus bloques `env` 9 claves de credenciales (`env.py:56-75`, `:109-111`). Quien ya tenga Claude Code configurado en la máquina puede ejecutar `flower` directamente y ponerse a trabajar: la pantalla de configuración ni siquiera aparece. Es justo lo que anuncia `install.sh:77`.

!!! warning "La frase del producto «flower no lee ~/.claude/settings.json» es falsa"
    Cuando no encuentra credenciales por ningún lado, la última línea del error que imprime flower es `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。` (`env.py:184-194`, la frase está en `:192`). **Manda el código: sí lo lee.** `env.py:56-75` lee explícitamente el bloque `env` de esos dos ficheros, solo que toma únicamente 9 claves de credenciales y no adopta ningún otro ajuste. Al leer esa frase, no des por hecho que se ignora la configuración local de Claude Code. La cadena completa está en [Configuración · Prioridad de búsqueda de credenciales](../reference/config.md#凭证查找优先级).

### Cuando quieras reconfigurar {#想重新配的时候}

El subcomando `flower setup` está registrado (`cli.py:1326-1328`), pero `_CMDS` se lo dejó fuera (`cli.py:937`), de modo que `flower setup` se reescribe a `flower go setup`, es decir: toma "setup" como una petición y ejecuta el workflow completo. **Hoy no existe ninguna forma en línea de comandos de alcanzar ese subcomando**, aunque varios mensajes de error todavía te digan que lo ejecutes. Para cambiar las credenciales:

```bash
$EDITOR ~/.config/flower/.env
```

O borra el token de ese fichero y vuelve a ejecutar `flower`: la comprobación de credenciales faltantes te preguntará de nuevo (siempre que tampoco estén en otra ubicación, como `~/.claude/settings.json`). Si las credenciales son rechazadas (HTTP 401 / 403) también aparece en el acto esa misma pantalla para reconfigurar, con una sola oportunidad (`cli.py:1416-1428`).

## Verificar que está bien instalado {#验证装好了没有}

Dos niveles, de barato a caro.

**Nivel uno — ¿existe el comando? (sin coste)**:

```bash
flower --help
```

Ver estas líneas significa que el console script está instalado y en el PATH:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Nivel dos — credenciales, endpoint y binario nativo funcionando (unos céntimos)**: la ejecución real más barata es `once`: un solo agente, por defecto con únicamente las tres herramientas de solo lectura `Read` / `Glob` / `Grep`, sin [guardián de objetivos](../reference/glossary.md#目标看守) y sin [banco de trabajo](../reference/glossary.md#工作台):

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` imprime la configuración efectiva **antes** de arrancar, dejando solo los 4 primeros caracteres del token (`cli.py:1445-1447`; `env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

Estas líneas confirman que no te has conectado al gateway equivocado. Después vienen la sonda de credenciales y la ejecución real:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**No hay cabecera de paso.** `once` pasa por `_run_once` → `rt.run()`, sin atravesar `_drive` / `Workflow.run`, y `Event("step", …)` solo se emite en `workflow/base.py:220`; por eso, con `once` no aparecen líneas separadoras del tipo `== 步骤名 ===== 1/1`: solo las tienen `go` y `run`.

**Si aparece la línea `+ 完成`, ha pasado la prueba**, y demuestra tres cosas a la vez: las credenciales funcionan, el endpoint es alcanzable y el binario nativo del wheel de `claude-agent-sdk` arranca en esta máquina. Si debajo de `- 验一下凭证…` ves `! 凭证被拒` o `! 网关地址或模型名不对`, ve a la tabla de diagnóstico de abajo.

!!! note "`once` muestra 0 en tiempo y coste acumulado"
    `once` crea un renderizador nuevo por cada evento (`cli.py:1239`, `:579-581`), así que `用时` es siempre `0:00` y el `累计 $` de la línea de estado nunca se acumula: **el coste de ese paso único es real, el tiempo no**.

    El `1 轮 · $0.1741` de la línea de arriba es una **medición real con procedencia**: el 2026-09-06, en un contenedor Linux/arm64, una petición real enviada a través de `cloud.infini-ai.com/maas` (`docker/README.md:24-25`), es decir, el **precio suelo de una sola ronda** con Opus 5 + ventana de 1M. Si ejecutas tú el comando de arriba, tendrá que leer el repositorio, habrá más rondas y el coste será algo mayor que ese suelo. La cuenta completa está en `runs/manifest.json`, ver [Configuración · Disposición en disco](../reference/config.md#磁盘布局).

## Cuando la instalación falla {#装不上的时候}

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Ni `python3` ni `python` cumplen 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3` y vuelve a ejecutar el script |
| El script dice que se instaló, pero `flower: command not found` | Se instaló en un directorio que no está en el PATH | Ver arriba «Cómo poner el comando `flower` en el PATH». Si se tomó la vía `pip --user`, en macOS es `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | Fallaron todas las vías, normalmente porque no hay red hacia GitHub o PyPI | Ejecuta manualmente lo que sugiere y mira el error real |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 líneas) | Entorno no interactivo (tubería, CI, `nohup`) sin credenciales: allí no aparece la pantalla de configuración, sale directamente | Ejecuta primero `flower` en una terminal real y configúralo, o escribe directamente `~/.config/flower/.env` |
| `! 凭证被拒:HTTP 401 …` | Token caducado o mal escrito | En una terminal interactiva te deja reconfigurarlo en el acto; en no interactivo, sale |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` o el nombre del modelo son incorrectos | Escribe la BASE_URL hasta la raíz del gateway, sin `/v1`; usa los nombres de modelo propios del gateway |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / timeout / 5xx | **No es un problema de credenciales**; flower deliberadamente no te hace reconfigurar, arranca igualmente y lo deja en manos de la capa de [resiliencia](../reference/glossary.md#韧性) |
| `! 标准输入不是终端,没人能回答提问` | Se ejecuta en una tubería o en CI | Añade `--timeout 0` para que decida por sí mismo y no espere a nadie |
| `flower setup` arranca preguntando «qué quieres hacer» | `_CMDS` se dejó fuera `setup` (`cli.py:937`) | Edita directamente `~/.config/flower/.env`, ver arriba «Cuando quieras reconfigurar» |

## Siguientes pasos {#下一步}

- [Inicio rápido](quickstart.md) — entra en un directorio de proyecto y saca adelante el primer trabajo real.
- [Configuración](../reference/config.md) — todas las variables de entorno, la prioridad de credenciales, la sintaxis de `.env` y qué queda en disco.
- [Línea de comandos](../reference/cli.md) — todos los subcomandos y flags.
- [Despliegue](../reference/deploy.md) — ejecutar en contenedor, distribuir capacidades de dominio con plugins.
- [Glosario](../reference/glossary.md) — el significado exacto de cada término de la documentación.
