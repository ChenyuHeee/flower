# Instalación

Instalar flower solo requiere Python ≥ 3.10. La única dependencia en tiempo de ejecución es `claude-agent-sdk` —— el binario nativo que hace las peticiones viene dentro de su wheel, así que **no hay que instalar Node ni el CLI de Claude Code**. Esta página recorre todo desde cero: instalación en una línea, instalación desde el código fuente, configuración de credenciales la primera vez, y un comando que demuestra que "sí, quedó bien instalado". Cuando funcione, sigue con [Inicio rápido](quickstart.md).

## Antes de instalar: confirma Python

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Basta con una salida tipo `True 3.13.7`. Si imprime `False` o no existe `python3`, instálalo primero (`brew install python` / `apt install python3`); de lo contrario el script de instalación se cerrará de inmediato.

| Necesario | No necesario |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31` también lo comprueba por su cuenta) | Node.js |
| Red hacia el endpoint de la API | CLI de Claude Code |
| Una API key o un token de gateway (se da después de instalar) | Los ajustes del `~/.claude/` de la máquina (las credenciales son la única excepción, ver abajo) |

Nombre del paquete `flower`, versión `0.1.0`, única dependencia en tiempo de ejecución `claude-agent-sdk>=0.2.152` (`pyproject.toml:2-6`). `mkdocs-material` solo se usa cuando CI construye el sitio de documentación; para ejecutar flower no hace falta.

## Instalación en una línea

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Al terminar, la terminal debería mostrar algo así (sin los colores):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

Lo importante es esa línea `== 装好了 <ruta absoluta>` —— es el resultado de que el propio script ejecutó una vez `command -v flower` (`install.sh:60-61`). Si imprime una ruta, `flower` ya está en el PATH.

### Qué hace realmente el instalador

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) hace solo tres cosas: elegir un instalador de herramientas Python, instalar desde GitHub y decirte el siguiente paso. **No toca ni una letra de tus credenciales** (`install.sh:7-8`). La fuente de instalación está fija en `git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

El instalador prueba en orden y se detiene en la primera opción que funcione (`install.sh:33-57`):

| Orden | Condición | Comando real | Dónde queda el ejecutable |
|---|---|---|---|
| 1 | `uv` está en el PATH | `uv tool install --force <REPO>` | El directorio bin de herramientas de uv, normalmente `~/.local/bin/flower` |
| 2 | No hay `uv`, pero sí `pipx` | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | No hay ninguno de los dos | Primero instala uv con `curl -LsSf https://astral.sh/uv/install.sh \| sh`; si se instala, vuelve al caso 1 | Igual que el caso 1 |
| 4 | En el caso 3 uv tampoco se instaló | `python3 -m pip install --user --upgrade <REPO>` | El directorio de scripts del usuario —— **en macOS no es `~/.local/bin`** |

Las cuatro vías instalan el mismo console script: `flower = "flower.cli:main"` (`pyproject.toml:12`). Una vez instalado también puedes invocarlo con `python -m flower.cli`, con el mismo efecto (`cli.py:1263-1264`).

!!! warning "Volver a ejecutar el script de instalación sobrescribe a la fuerza, sin pedir confirmación"
    Los tres comandos de instalación llevan `--force`, `--force` y `--upgrade` respectivamente (`install.sh:37`, `:40`, `:54`). Volver a ejecutarlo pisa directamente la instalación existente —— así es exactamente como se actualiza, pero no esperes que te pregunte antes.

### Cómo llega el comando `flower` al PATH

Cuando `command -v flower` no lo encuentra, el script sugiere añadir `$HOME/.local/bin` a `~/.zshrc` o `~/.bashrc` (`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Tanto `uv tool install` como `pipx install` colocan el ejecutable ahí, así que para ellos la sugerencia es correcta. **Pero para la cuarta vía (`pip install --user`) no necesariamente** —— el directorio de esa sugerencia está escrito a mano, mientras que el directorio de scripts de usuario de pip depende de la plataforma. En macOS es `~/Library/Python/3.13/bin`. Compruébalo tú mismo:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

Sale, por ejemplo, `/Users/you/Library/Python/3.13/bin` —— añade ese directorio al PATH en lugar de `~/.local/bin`, y luego reabre la terminal o haz `source`.

## Instalación desde el código fuente

Si quieres leer el código, modificar el framework o ejecutar las verificaciones offline de `tests/`, instala desde el código fuente:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

Después de eso, `.venv/bin/flower --help` debería imprimir las líneas de uso.

El shebang de ese ejecutable dentro del venv es una **ruta absoluta**, así que no hace falta activarlo: con un enlace simbólico funciona desde cualquier directorio:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Si `~/.local/bin` está en el PATH, al hacer `cd` a cualquier directorio de proyecto y escribir `flower` se usará el intérprete de ese venv y este código fuente.

La instalación desde el código fuente añade además un lugar más para las credenciales: **el `.env` en la raíz del repositorio** (quinto en el orden de búsqueda, ver [Configuración · Prioridad de búsqueda de credenciales](../reference/config.md#凭证查找优先级)). Durante el desarrollo:

```bash
cp .env.example .env        # rellena ANTHROPIC_AUTH_TOKEN
```

`.env` ya está ignorado por `.gitignore`, así que no entrará en el repositorio. Una instalación de flower hecha con pip / pipx / uv **no** tiene disponible esa ubicación —— vive en site-packages, no hay "raíz del repositorio" —— así que en ese caso hay que usar el archivo global de credenciales descrito abajo.

## Primera ejecución: configurar credenciales

Las tres vías de ejecución `go`, `run` y `once` llaman al principio a `ensure_credentials()` (`cli.py:1013`, `:981`, `:1046`), con dos filtros:

1. **¿Existen?** —— busca por orden de prioridad y, si no encuentra nada, te pregunta en el momento.
2. **¿Funcionan?** —— hace una llamada real a la API. Una petición mínima con `max_tokens=16` (`env.py:120-123`), que casi no cuesta nada. Un token caducado o una dirección de gateway mal escrita no se detectan mirando las variables de entorno; sin la sonda, reventaría minutos más tarde.

Si no hay credenciales, la primera ejecución de `flower` se detiene en esta pantalla (`cli.py:1179-1209`):

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

La pregunta 1 es obligatoria; si la dejas vacía imprime en rojo `没给 token,取消。` y sale. En las preguntas 2 y 3 basta con pulsar Enter. Si usas el endpoint oficial, deja la pregunta 2 vacía; con un gateway de terceros pon su dirección raíz, **sin `/v1`** —— la sonda de flower llama a `<BASE_URL>/v1/messages` (`env.py:162`).

Las claves que se escriben según tus respuestas (`cli.py:1199-1207`):

| Lo que introduces | Clave escrita en `.env` |
|---|---|
| Token que empieza por `sk-ant-` | `ANTHROPIC_API_KEY` |
| Cualquier otro token | `ANTHROPIC_AUTH_TOKEN` |
| Dirección de gateway no vacía | `ANTHROPIC_BASE_URL` |
| Nombre de modelo no vacío | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` **las tres a la vez** |

La ubicación del archivo es `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), se escribe **sobrescribiendo el archivo completo** y al terminar se le aplica `chmod 0o600` (`cli.py:1157-1168`). Ese es el archivo del "se configura una vez y vale en todas partes" —— no hay que reconfigurar al cambiar de directorio de proyecto; el significado de cada variable está en [Configuración](../reference/config.md#环境变量).

### Si ya tienes Claude Code instalado en la máquina, puede que no te pregunte nada

La búsqueda de credenciales tiene un **último recurso**: leer `~/.claude/settings.json` y luego `~/.claude/settings.local.json`, tomando 9 claves de credenciales del bloque `env` de esos archivos (`env.py:56-75`, `:109-111`). Quien ya tenga Claude Code configurado en su máquina puede ejecutar `flower` y ponerse a trabajar directamente: la pantalla de configuración no aparecerá —— eso es exactamente lo que anuncia `install.sh:77`.

!!! warning "La frase del producto «flower 不读 ~/.claude/settings.json» es falsa"
    Cuando no encuentra credenciales en ningún sitio, la última línea del error que imprime flower es
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`, esa frase está en `:192`). **El código manda: sí lo lee.**
    `env.py:56-75` lee explícitamente el bloque `env` de esos dos archivos, solo que toma únicamente 9 claves de credenciales y no asume ningún otro ajuste. Al leer esa frase no concluyas que se ignora la configuración de Claude Code de tu máquina. La cadena completa está en [Configuración · Prioridad de búsqueda de credenciales](../reference/config.md#凭证查找优先级).

### Cuando quieras reconfigurar

El subcomando `flower setup` está registrado (`cli.py:1147-1149`), pero falta en `_CMDS` (`cli.py:758`), de modo que `flower setup` se reescribe como `flower go setup` —— tomando "setup" como una petición y ejecutando el flujo completo. **Ahora mismo no hay ninguna forma de línea de comandos que llegue a ese subcomando**, aunque varios textos de error todavía te digan que lo ejecutes. Para cambiar las credenciales:

```bash
$EDITOR ~/.config/flower/.env
```

O borra el token de ese archivo y ejecuta `flower` otra vez —— el filtro de credenciales ausentes volverá a preguntar (siempre que tampoco existan en otras ubicaciones, como `~/.claude/settings.json`). Cuando las credenciales son rechazadas (HTTP 401 / 403) también aparece en el momento esa misma pantalla para reconfigurar, con una sola oportunidad como máximo (`cli.py:1229-1244`).

## Verificar que quedó instalado

Dos niveles, de lo barato a lo caro.

**Primer nivel —— ¿existe el comando? (gratis)**:

```bash
flower --help
```

Ver estas líneas significa que el console script está instalado y en el PATH:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Segundo nivel —— credenciales, endpoint y binario nativo funcionando (unos céntimos)**: la ejecución real más barata es `once` —— un solo agent, con solo las tres herramientas de lectura `Read` / `Glob` / `Grep` por defecto, sin [goal guard](../reference/glossary.md#目标看守) y sin [workbench](../reference/glossary.md#工作台):

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` imprime la configuración efectiva **antes** de arrancar, dejando solo los 4 primeros caracteres del token (`cli.py:1257-1259`; `env.py:197-211`):

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

**No hay cabecera de step.** `once` va por `_run_once` → `rt.run()`, sin pasar por `_drive` / `Workflow.run`, y `Event("step", …)` solo se emite en `workflow/base.py:220` —— por eso las líneas separadoras tipo `== 步骤名 ===== 1/1` no aparecen con `once`, solo con `go` / `run`.

**Que aparezca la línea `+ 完成` cuenta como aprobado**, y demuestra tres cosas a la vez: las credenciales funcionan, el endpoint es alcanzable y el binario nativo del wheel de `claude-agent-sdk` arranca en esta máquina. Si debajo de `- 验一下凭证…` ves `! 凭证被拒` o `! 网关地址或模型名不对`, ve a la tabla de resolución de problemas de abajo.

!!! note "El tiempo y el coste acumulado de `once` se muestran como 0"
    `once` crea un renderizador nuevo para cada evento (`cli.py:1060`, `:579-581`), así que `用时` es siempre `0:00` y el `累计 $` de la línea de estado nunca acumula —— **el coste de ese único paso es real, el tiempo no**.

    El `1 轮 · $0.1741` de la línea anterior es una **medición real con procedencia**: el 2026-09-06, en un contenedor Linux/arm64, una petición real enviada a través de `cloud.infini-ai.com/maas` (`docker/README.md:24-25`), es decir, el **precio suelo de una ronda** con Opus 5 + ventana de 1M. Si ejecutas tú el comando de arriba tendrá que leer el repositorio, habrá más rondas y el coste será algo mayor que ese suelo. La cuenta completa está en `runs/manifest.json`, ver [Configuración · Disposición en disco](../reference/config.md#磁盘布局).

## Cuando no se instala

| Síntoma | Causa | Qué hacer |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Ni `python3` ni `python` cumplen 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3`, y vuelve a ejecutar el script |
| El script dice que quedó instalado, pero `flower: command not found` | Se instaló en un directorio que no está en el PATH | Ver arriba "Cómo llega el comando `flower` al PATH". Si se usó la vía `pip --user`, en macOS es `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | Todas las vías fallaron, normalmente por falta de red hacia GitHub o PyPI | Ejecuta manualmente lo que indica y mira el error real |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 líneas) | Entorno no interactivo (pipe, CI, `nohup`) sin credenciales —— ahí no aparece la pantalla de configuración, sale directamente | Ejecuta primero `flower` una vez en una terminal real para configurarlo, o escribe directamente `~/.config/flower/.env` |
| `! 凭证被拒:HTTP 401 …` | Token caducado o mal escrito | En una terminal interactiva te deja reconfigurar en el momento; si no es interactiva, sale |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` o el nombre del modelo son incorrectos | Escribe BASE_URL hasta la raíz del gateway, sin `/v1`; usa los nombres de modelo propios del gateway |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / timeout / 5xx | **No es un problema de credenciales**; flower deliberadamente no te deja reconfigurar, arranca igual y lo delega en la capa de [resiliencia](../reference/glossary.md#韧性) |
| `! 标准输入不是终端,没人能回答提问` | Se está ejecutando en un pipe o en CI | Añade `--timeout 0` para que decida por sí mismo y no espere a nadie |
| `flower setup` arranca y pregunta "qué hay que hacer" | Falta `setup` en `_CMDS` (`cli.py:758`) | Edita directamente `~/.config/flower/.env`, ver arriba "Cuando quieras reconfigurar" |

## Siguiente paso

- [Inicio rápido](quickstart.md) —— entra en un directorio de proyecto y saca adelante el primer trabajo real.
- [Configuración](../reference/config.md) —— todas las variables de entorno, la prioridad de credenciales, la sintaxis de `.env` y qué queda en disco.
- [Línea de comandos](../reference/cli.md) —— todos los subcomandos y flags.
- [Despliegue](../reference/deploy.md) —— ejecutar en contenedor, distribuir capacidades de dominio con plugins.
- [Glosario](../reference/glossary.md) —— el significado exacto de cada término de la documentación.
