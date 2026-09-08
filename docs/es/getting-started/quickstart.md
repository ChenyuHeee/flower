# Primeros pasos

Tres comandos y ya está corriendo: instalar, entrar al directorio del proyecto, teclear `flower`.
Esta página pone esos tres al principio y luego explica qué pasa en pantalla después de pulsar Enter,
cómo responder cuando te pregunta algo y qué mirar primero si no arranca.

## Instalar, entrar al directorio, teclear flower {#跑起来}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
cd /path/to/your/project
flower
```

El primer script busca automáticamente `uv` / `pipx` / `pip` para instalar el comando `flower`;
basta con Python ≥ 3.10, sin Node y sin el CLI de Claude Code. El tercero no lleva ningún argumento
y **no hay que poner comillas en el shell**.

Si prefieres otra forma de instalar (pipx / pip / desde el código fuente), o si ese script no funciona
en tu máquina, mira [Instalación](install.md) — pero no hace falta leer esa página entera antes de volver aquí.

## Después de pulsar Enter {#回车之后}

La primera vez que lo ejecutas en esta máquina te pide credenciales: API key o dirección de la pasarela.
Se configura una vez, se guarda en `~/.config/flower/.env` y vale para todo desde entonces. Si ya tienes
Claude Code instalado y configurado en esta máquina, toma prestado ese token directamente, sin preguntar.

Con las credenciales listas, el cursor se queda en `>`:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Esa línea lee de la entrada estándar y **no pasa por el shell** — puedes escribir comillas chinas,
espacios y signos de exclamación tal cual.

Antes de arrancar imprime una línea `- 验一下凭证…`: es una sonda real contra la API. Si rechazan las
credenciales imprime `! 凭证被拒:…` y te pregunta en el momento si quieres reconfigurarlas; si no hay
conexión imprime `(探针没打通:… —— 当作网络问题,照常开跑)`, y **no** te manda a reconfigurar un
token que estaba perfectamente bien.

Si la sonda pasa, empieza a trabajar en tres pasos. Cada línea de guiones `==` en pantalla es un límite
de [paso](../reference/glossary.md#步骤), y el `1/3` de la derecha es el progreso:

```text
== 确认需求 ======================================================== 1/3

  ? X 要跑在什么环境上?
     1) 只在我这台 macOS 上
     2) Linux 服务器
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
  + 只在我这台 macOS 上

  ? 「做完了」以什么为准?
你的回答 (回车=跳过,让它自己判断) > 能跑起来,并且 pytest 全绿
  + 能跑起来,并且 pytest 全绿

  + 完成 9 轮 · $0.53 · 用时 6:02

== 设定目标 ======================================================== 2/3

  ~ 把这份需求拆成能当场验证的条目
  + 完成 12 轮 · $0.41 · 用时 9:06

== 干活 ============================================================ 3/3

  ~ 先看一眼现在有什么,再决定第一刀切哪
  * Read README.md
  > 派人 coder 实现 X 的第一版,带最小测试
  先让 coder 把骨架搭起来,我再看要不要拆第二个人。
  - 上下文 36.8K · 累计 $0.94 · 12:44
  + 完成 12 轮 · $12.34 · 用时 52:53
  + 完成 37 轮 · $1.40 · 用时 58:19

总花费 $14.68 · 清单 /path/to/your/project/runs/manifest.json
```

Los iconos son siempre ASCII: `~` pensar, `*` llamada a herramienta, `>` delegar, `+` éxito, `x` fallo,
`?` pregunta, `<-` retomar lo anterior. No son emoji — los emoji y los caracteres de marco disparan el
fallback de glifos del terminal, y en pruebas reales tumbaron el terminal dos veces. **Todos los ejemplos
de terminal de esta documentación usan este mismo ASCII, idéntico a lo que ves en tu pantalla.**

Hay otros tres puntos que merecen una segunda mirada:

- Las dos últimas líneas `+ 完成` no son un duplicado. La primera es la ronda de trabajo; la segunda es la
  ronda de **veredicto** — el veredicto corre en su propia sesión, pero **no abre una línea `==` nueva**,
  porque es una ronda interna del paso `干活`. En el [manifiesto de ejecución](../reference/glossary.md#运行清单)
  aparece con el nombre `干活·判定#1`.
- El `$` de la línea `+ 完成` es el dinero de **esa ronda**; `用时` es el tiempo total **desde el arranque
  hasta ahora**. Son dos medidas distintas.
- Las líneas de estado del tipo `- 上下文 … · 累计 … · …` solo siguen al [hilo principal](../reference/glossary.md#主线程);
  el contexto de los subagentes no entra ahí. Las llamadas a herramientas de los subagentes sí se muestran por
  defecto, indentadas tras una línea vertical `|`; para ver **lo que dicen** hace falta `-v` — eso es el
  detalle del terreno, no la decisión.

## Quién ejecuta cada uno de esos tres pasos {#三步}

| Paso en pantalla | Quién lo ejecuta | Qué hace | Se congela en | Detalle |
|---|---|---|---|---|
| `确认需求` | [Clarificador](../reference/glossary.md#确认者) | Solo pregunta, no toca nada, **pregunta hasta que quede claro, sin límite de rondas**; al final produce un [brief](../reference/glossary.md#需求确认书) de cuatro apartados | `.flower/notes/需求.md` | [Clarificación](../guide/clarify.md) |
| `设定目标` | [Juez](../reference/glossary.md#判定者) | Traduce el brief a "objetivo + lista de veredicto", donde cada punto tiene que poder verificarse en el momento | `.flower/notes/目标.md` | [Guardián de objetivos](../guide/goal.md) |
| `干活` | El [coordinador](../reference/glossary.md#协调者) delega en [subagentes](../reference/glossary.md#subagent) | El coordinador reparte el trabajo, lee los informes y decide; al final de cada ronda un juez que **no participó en el trabajo** dictamina de forma independiente si "está terminado", y si no se alcanzó lo devuelve para seguir | El código mismo | [Guardián de objetivos](../guide/goal.md) |

Los dos primeros pasos son la materialización de los mecanismos de [clarificación](../reference/glossary.md#前置确认)
y [guardián de objetivos](../reference/glossary.md#目标看守); el tercero es el tramo que ambos gobiernan juntos.
Por defecto corren como mucho 3 rondas de veredicto (`--rounds`), y `--no-goal` lo desactiva por completo —
desactivado, "él dice que está terminado" cuenta realmente como terminado.

El veredicto solo tiene tres conclusiones: alcanzado, no alcanzado y **no verificable en este entorno**.
Las dos últimas son conclusiones distintas — "aquí no se puede verificar" nunca se juzga como aprobado:
se para y te pregunta.

Una ejecución completa no es barata. Referencias medidas: [HT002](../cases/ht002.md) instaló y puso en marcha
un proyecto existente en macOS en 4 pasos, alrededor de 1 hora, **$38.24**; [HT001](../cases/ht001.md) escribió
un IDE de terminal desde cero, **10.4 horas, $171.62**. Si quieres ver primero qué te va a preguntar antes de
decidir si sigues, usa `--clarify-only`.

## Cómo responder a las preguntas {#答提问}

El bloque que empieza con `?` es él preguntándote. Tres formas de responder:

- **Teclear el número** (`1` / `2` / `3`) — elige esa opción; la pantalla devuelve una línea `+ <la opción elegida>`.
- **Escribir directamente** — respuesta libre, no tiene que ser una de las opciones.
- **Pulsar Enter a secas** — saltar y dejar que decida él; la pantalla devuelve una línea `. 已跳过`.

Por defecto espera 1800 segundos (`--timeout`). Si no llega nadie imprime
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` y sigue adelante, sin bloquearse.
El número de preguntas **no está limitado por defecto** (`--asks` vale `-1` por defecto); si le das un número
positivo se convierte en una cuota estricta, y al agotarla imprime `! 提问额度用完`.

## Mientras corre, tú puedes seguir hablando {#插话}

Abajo del todo siempre hay un prompt en el que puedes escribir. No es decorativo — se borra antes de cada
salida y se vuelve a dibujar después, así que **los logs no se lo llevan hacia arriba**. Tiene dos textos,
según haya o no una pregunta pendiente:

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

Cuando no hay pregunta pendiente puedes hacer dos cosas.

**Escribir una frase = añadir un requisito.** No se le interrumpe: lo verá la próxima vez que consulte la
bandeja de entrada. El acuse de recibo tiene esta pinta:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

Ese "ya anexado al brief" es importante: la frase cae también en `需求.md`, así que sobrevive al límite de paso —
el paso siguiente es una sesión nueva que solo lee los artefactos congelados; sin volcado a disco, decirlo
equivale a no haberlo dicho.

**Empezar con `?` = preguntar de paso.** Abre una sesión aparte de solo lectura para responderte, con nada más
que los últimos 60 eventos y lo que haya en el [banco de trabajo](../reference/glossary.md#工作台). Ese desvío lo
ejecuta el [oráculo](../reference/glossary.md#旁路顾问), con un tope por defecto de 12 rondas / $0.5:

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Se responde y se tira** — ese intercambio no entra en el contexto de la ejecución, y su coste tampoco entra en
el manifiesto principal: queda registrado en su propio archivo bajo `runs/aside/`. Así que preguntar no afecta a
la ejecución, y tampoco hay que lamentar ese gasto en la cuenta.

!!! warning "El `？` de ancho completo no cuenta: tiene que ser `?` de ancho medio"
    Para reconocer una pregunta de desvío solo vale el `?` **de ancho medio** (ASCII `0x3f`). El `？` de ancho
    completo que produce por defecto un IME chino no se reconoce — esa línea se toma como "añadir un requisito"
    y va a la bandeja de entrada **sin error alguno**; simplemente la respuesta que esperas no llega nunca.
    Es una errata en el código, ya anotada en la lista de defectos; hasta que se arregle, cambia el IME a inglés
    antes de escribir `?`.

De paso, sobre Ctrl+C: pulsarlo por primera vez durante la ejecución **interrumpe esa ronda y te deja decir algo**,
no sale del programa.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

Solo al pulsarlo una segunda vez sale de verdad. (En el prompt inicial `要做什么?`, Ctrl-C sale directamente e
imprime `已取消`.)

## Ejecutarlo otra vez es continuar lo anterior {#再跑一次}

Si tecleas `flower` de nuevo en el mismo directorio, la primera frase cambia:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

Esa línea `<-` es el banner de [despertar](../reference/glossary.md#唤醒) e informa del estado actual de este
directorio. No vuelve a interrogarte sobre los requisitos ni a fijar los objetivos otra vez; da igual que el
proceso muriera por un kill o que se reiniciara la máquina.
La frase que digas ahí se anexa a `需求.md` y **dispara una nueva derivación de la lista de veredicto** —
sin volver a derivarla, el juez seguiría leyendo la lista vieja y lo que acabas de añadir no entraría en el veredicto.
Los detalles y el coste (el contexto no deja de crecer) están en [Continuidad](../guide/continuity.md).

Si no quieres continuar lo anterior, escribe `/new`: los requisitos, objetivos y [linaje](../reference/glossary.md#血缘)
del tramo anterior se **mueven** a `notes/archive/<时间戳>/` (no se borran) y se empieza desde cero.

## Meterlo en un script, sin supervisión {#脚本}

La petición también puede pasarse como argumento, y las opciones pueden ir antes o después de ella:

```bash
flower "帮我做一个 X"                      # la petición como argumento
flower --rounds 5 "帮我做一个 X"           # opciones delante
flower "帮我做一个 X" --rounds 5           # opciones detrás, equivalente
echo "帮我做一个 X" | flower --timeout 0   # tubería a la entrada estándar, totalmente automático
```

También vale dar solo opciones y ninguna petición — `flower --clarify-only` te preguntará primero qué quieres hacer
y seguirá desde ahí.

**Por qué sigue existiendo la vía de "escribir después de pulsar Enter".** Ese par de comillas en la línea de comandos
es puro lastre. Ocurrió de verdad: la comilla de cierre se tecleó como el `”` chino, zsh se quedó esperando la comilla
de cierre real (cayendo en el prompt de continuación `dquote>`) y parecía que el programa se había colgado, cuando en
realidad no había arrancado ni una vez. Al ejecutar `flower` a secas se lee de la entrada estándar, sin pasar por el
shell: comillas chinas, espacios, signos de exclamación y saltos de línea se escriben tal cual. La vía de la tubería
entra por el mismo sitio — cuando la entrada estándar no es un terminal no imprime la cabecera del prompt y lee una línea
directamente.

!!! danger "Sin supervisión hay que dar `--timeout 0` explícitamente"
    En una tubería, con `nohup` o en CI no hay nadie que responda preguntas. Sin `--timeout 0`: la primera pregunta se
    salta porque "la entrada está cerrada", y **cada pregunta posterior espera los 1800 segundos completos**; unas pocas
    preguntas son unas cuantas horas girando en vacío, y ese tiempo está quemando dinero.
    `--timeout 0` hace que todas las preguntas fallen de inmediato devolviendo "nadie responde", y él decide por su cuenta
    y sigue adelante.
    Cuando la entrada estándar no es un terminal, flower imprime primero una línea de aviso:
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## Si no arranca {#冒烟}

Si tecleas `flower` y no pasa nada, si da error de credenciales, o si la salida se ve mal a simple vista, verifica primero
las credenciales y el binario por separado con el disparo más barato posible. Un solo agente, herramientas de solo lectura,
un tiro para ver si ambos extremos responden:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| Este trozo | Qué es |
|---|---|
| `once` | Ejecuta un solo agente una vez: sin clarificar requisitos, sin fijar objetivos, sin delegar |
| `-w PATH` | Directorio de trabajo del agente. Si no se da, el directorio actual |
| `-v` | Antes de arrancar imprime la configuración de credenciales en vigor, dejando solo los 4 primeros caracteres del token |

`once` solo da tres herramientas por defecto — `Read`, `Glob`, `Grep` — así que no puede escribir nada y el disparo sale
barato. Referencia medida: Opus 5 con ventana de 1 millón a través de una pasarela de terceros, **el suelo de una sola ronda
es $0.1741**; los modelos baratos cuestan menos. El apartado "verificar que quedó instalado" de la página
[Instalación](install.md) ejecuta exactamente este comando.

Si funciona, tiene esta forma — los números y el texto serán distintos, **los iconos no**:

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 19 位)
ANTHROPIC_BASE_URL = https://your-gateway.example.com
ANTHROPIC_MODEL = claude-opus-5[1m]
- 验一下凭证…
  ~ 先看目录结构,再挑一两个文件读
  * Glob **/*.py
  * Read README.md
  这是一个用 Rust 写的命令行 HTTP 压测工具。
  - 累计 $0.00 · 0:00
  + 完成 4 轮 · $0.0932 · 用时 0:00
```

Dos cosas que hay que reconocer:

- Las primeras líneas son la configuración en vigor que imprime `-v`. **Conectarse a la pasarela equivocada se ve de un
  vistazo** — esa es la razón principal por la que existe esta opción.
- El `$` de la línea `+ 完成` es real; `累计` y `用时` valen siempre 0 por esta vía de `once`
  (cada evento crea un renderizador nuevo, así que el estado no se acumula).

Si este disparo funciona, significa que credenciales, pasarela, nombre de modelo y binario incluido están todos bien, y el
problema está en otra parte. Si no funciona, es asunto de instalación: vuelve a [Instalación](install.md).

## Qué leer a continuación {#接下来}

| Si quieres saber | Lee |
|---|---|
| Qué significan exactamente esas palabras de la pantalla | [Conceptos centrales](concepts.md) |
| Todos los subcomandos y opciones, sin dejarse ninguno | [Referencia de la línea de comandos](../reference/cli.md) |
| Por qué empieza haciendo un montón de preguntas y cómo hacer que pregunte menos | [Clarificación](../guide/clarify.md) |
| Quién dictamina si "está terminado" y cómo se escribe la lista de veredicto | [Guardián de objetivos](../guide/goal.md) |
| Por qué volver a ejecutarlo en el mismo directorio retoma lo anterior | [Continuidad](../guide/continuity.md) |
| Qué hace cuando el contexto se llena (no es compact) | [Relevo](../guide/handoff.md) |
| Credenciales, pasarela, nombre de modelo, variables de entorno | [Referencia de configuración](../reference/config.md) |
| Cambiar el terminal por otra cosa: Web / TUI / totalmente automático | [Capa de interacción](../guide/interaction.md) |
| Prescindir de los tres pasos que trae y escribir tu propio flujo de trabajo | [Diseñar flujos de trabajo](../guide/workflow.md) · [API de Python](../reference/api.md) |
| Qué pasó exactamente en una carrera larga real | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| La definición exacta de algún término | [Glosario](../reference/glossary.md) |
