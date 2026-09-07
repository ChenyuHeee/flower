# Primeros pasos

Esta página va desde «ya está instalado» hasta «lo he ejecutado una vez de verdad y entiendo lo que sale en pantalla». Cuatro tramos, en orden:
primero una sola tirada barata para probar que las credenciales y el binario funcionan, luego una ejecución completa del workflow sin escribir código,
después aprender a interrumpirlo mientras corre, y por último meterlo en un script para que corra desatendido.

Solo hay un requisito: `flower` instalado, en el PATH y con las credenciales configuradas. Si aún no lo has instalado, mira [Instalación](install.md).

## Paso uno: comprobarlo con la tirada más barata {#冒烟}

No arranques directamente con el workflow completo. Primero lanza una tirada con un solo agente y herramientas de solo lectura, para probar que credenciales y binario funcionan por ambos lados:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| Este trozo | Qué es |
|---|---|
| `once` | Ejecuta un solo agente una vez: no pregunta requisitos, no fija objetivos, no delega |
| `-w PATH` | Directorio de trabajo del agente. Si no lo das, es el directorio actual |
| `-v` | Antes de arrancar imprime la configuración de credenciales efectiva; del token solo se muestran los 4 primeros caracteres |

`once` da por defecto solo tres herramientas —— `Read`, `Glob`, `Grep`; no puede escribir nada, así que esta tirada es barata.
Referencia medida: Opus 5 con ventana de 1 millón a través de una pasarela de terceros, **el suelo de una ronda es $0.1741**; los modelos baratos, menos.

!!! tip "Si vienes de la página de instalación, sáltate esto"
    El apartado «comprobar que está instalado» de [Instalación](install.md) ejecuta exactamente este comando. Si ya lo has hecho, sigue adelante;
    lo de abajo solo te enseña a leer su salida.

Al terminar deberías ver esta forma —— los números y el texto serán distintos, **los iconos no**:

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

Hay cuatro cosas que debes reconocer; los pasos siguientes dependen de ellas:

- Las primeras líneas son la configuración efectiva que imprime `-v`. **Una pasarela equivocada se ve de un vistazo** —— esa es la razón principal por la que existe este flag.
- `- 验一下凭证…` es una sonda real a la API antes de arrancar. Si las credenciales son rechazadas imprime `! 凭证被拒:…` y te pregunta en el momento si quieres reconfigurarlas;
  si no hay conexión imprime `(探针没打通:… —— 当作网络问题,照常开跑)` y **no** te manda a reconfigurar un token que estaba perfectamente bien.
- Los iconos son siempre ASCII: `~` pensando, `*` llamada a herramienta, `>` delegar, `+` éxito, `x` fallo, `?` pregunta, `<-` retomar la anterior.
  No son emoji —— los emoji y los caracteres de recuadro disparan el fallback de glifos del terminal; en la práctica han tumbado el terminal dos veces. **Todos los ejemplos de terminal de esta documentación
  usan este mismo ASCII, idéntico a lo que verás en tu pantalla.**
- El `$` de la línea `+ 完成` es real; `累计` y `用时` son siempre 0 por la vía de `once`
  (cada evento crea un renderer nuevo, así que el estado no se acumula).

Si esta tirada funciona, credenciales, pasarela, nombre de modelo y binario incluido están todos bien. Si no funciona es asunto de instalación: vuelve a [Instalación](install.md).

## Paso dos: una ejecución completa del workflow, sin código {#跑一次}

No hace falta escribir nada de código, y **tampoco poner comillas en la shell**. Entra en el directorio de tu proyecto y teclea:

```bash
cd /path/to/your/project
flower
```

Te preguntará qué quieres hacer, con el cursor esperando en `>`:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Esa línea se lee de la entrada estándar y **no pasa por el parseo de la shell** —— comillas tipográficas, espacios y signos de exclamación se escriben tal cual.

Tras el retorno de carro va en tres pasos. Cada línea de guiones `==` en pantalla es un límite de [step](../reference/glossary.md#步骤),
y el `1/3` de la derecha es el progreso:

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

Tres puntos merecen una segunda mirada:

- Las dos últimas líneas `+ 完成` no son un duplicado. La primera es la ronda de trabajo, la segunda es la ronda de **verdict** ——
  el verdict corre en su propia sesión, pero **no abre otra línea `==`**, porque es una ronda interna del paso `干活`.
  Su nombre en el [run manifest](../reference/glossary.md#运行清单) es `干活·判定#1`.
- El `$` de la línea `+ 完成` es el dinero de **esa ronda**; `用时` es el tiempo total **desde el arranque hasta ahora**: dos métricas distintas.
- Las líneas de estado tipo `- 上下文 … · 累计 … · …` siguen solo al [main thread](../reference/glossary.md#主线程);
  el contexto de los subagents no entra ahí. Las llamadas a herramientas de los subagents sí se muestran por defecto, indentadas tras una barra vertical `|`;
  para ver **lo que dicen** hace falta `-v` —— eso es la escena, no la decisión.

### Qué son estos tres pasos que estás viendo {#三步}

| Paso en pantalla | Quién corre | Qué hace | Se congela en | Detalles |
|---|---|---|---|---|
| `确认需求` | [clarifier](../reference/glossary.md#确认者) | Solo pregunta, no toca nada, **pregunta hasta que esté claro, sin límite de rondas**; al final produce un [brief](../reference/glossary.md#需求确认书) de cuatro secciones | `.flower/notes/需求.md` | [Clarify](../guide/clarify.md) |
| `设定目标` | [judge](../reference/glossary.md#判定者) | Traduce el brief a «objetivo + lista de verdict», y cada entrada tiene que ser verificable en el acto | `.flower/notes/目标.md` | [Goal guard](../guide/goal.md) |
| `干活` | El [coordinator](../reference/glossary.md#协调者) delega en [subagents](../reference/glossary.md#subagent) | El coordinator descompone el trabajo, delega, lee informes y decide; al final de cada ronda un judge que **no participó en el trabajo** dictamina de forma independiente si «está hecho»; si no se cumple, lo devuelve para seguir | El propio código | [Goal guard](../guide/goal.md) |

Los dos primeros pasos son la materialización de los mecanismos de [clarify](../reference/glossary.md#前置确认) y [goal guard](../reference/glossary.md#目标看守);
el tercero es el tramo que ambos vigilan conjuntamente. Por defecto se ejecutan como máximo 3 rondas de verdict (`--rounds`),
y `--no-goal` lo desactiva entero —— desactivado, «dice que está hecho» significa que está hecho.

El verdict solo tiene tres conclusiones: cumplido, no cumplido y **no verificable en este entorno**. Las dos últimas son conclusiones distintas ——
«aquí no se puede verificar» nunca se aprueba: se para y te pregunta.

Una ejecución completa no es barata. Referencia medida: [HT002](../cases/ht002.md) instaló y puso en marcha un proyecto existente en macOS,
4 pasos, alrededor de 1 hora, **$38.24**; [HT001](../cases/ht001.md) escribió un IDE de terminal desde cero,
**10.4 horas, $171.62**. Si quieres ver primero qué te va a preguntar antes de decidir si sigues, usa `--clarify-only`.

### Cómo responder a las preguntas {#答提问}

El bloque que empieza por `?` es él preguntándote; hay tres formas de responder:

- **Escribe un número** (`1` / `2` / `3`) —— elige esa opción; la pantalla devuelve una línea `+ <la opción elegida>`.
- **Escribe directamente** —— respuesta libre, no tiene que ser una de las opciones.
- **Pulsa Intro** —— saltar y dejar que decida él; la pantalla devuelve una línea `. 已跳过`.

Por defecto te espera 1800 segundos (`--timeout`). Si nadie contesta imprime
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` y sigue adelante, sin bloquearse.
El número de preguntas es **ilimitado por defecto** (`--asks` por defecto `-1`); si le das un número positivo, es una cuota dura, y al agotarla imprime `! 提问额度用完`.

### Ejecutarlo otra vez es continuar la anterior {#再跑一次}

Teclea `flower` de nuevo en el mismo directorio y la primera línea cambia:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

La línea `<-` es el banner de [wake](../reference/glossary.md#唤醒) y reporta el estado actual de ese directorio.
No volverá a interrogarte sobre los requisitos ni a refijar los objetivos; da igual que hayas matado el proceso o reiniciado la máquina.
Lo que digas ahí se añade a `需求.md` y **dispara una nueva derivación de la lista de verdict** ——
sin volver a derivarla, el judge seguiría leyendo la lista vieja y lo que acabas de añadir nunca entraría en el verdict.
Los detalles y el coste (el contexto no para de crecer) están en [Continuidad](../guide/continuity.md).

Si no quieres continuar la anterior, escribe `/new`: los requisitos, objetivos y [linaje](../reference/glossary.md#血缘) del tramo anterior
se **mueven** a `notes/archive/<时间戳>/` (no se borran) y se empieza de cero.

## Paso tres: mientras corre, todavía puedes hablar {#插话}

Al pie de la pantalla siempre hay una línea de prompt donde puedes escribir. No es decorativa —— se borra antes de cada salida y se redibuja después,
así que **los logs nunca la empujan hacia arriba**. Hay dos textos, que alternan según si hay una pregunta pendiente:

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

Cuando no hay pregunta pendiente puedes hacer dos cosas.

**Escribir una frase = añadir un requisito.** No se le interrumpe; lo verá la próxima vez que consulte la bandeja de entrada. El acuse de recibo es así:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

Ese «已追加进确认书» importa: la frase también aterriza en `需求.md`, así que sobrevive al límite del paso ——
el siguiente paso es una sesión nueva que solo lee los artefactos congelados; si no se escribe a disco, decirlo equivale a no decir nada.

**Empezar por `?` = preguntar de paso.** Abre una sesión aparte de solo lectura para responderte, con solo los últimos 60 eventos y
lo que hay en el [workbench](../reference/glossary.md#工作台) a mano. Esta vía la ejecuta el
[oracle](../reference/glossary.md#旁路顾问), con un tope por defecto de 12 rondas / $0.5:

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Se descarta al terminar** —— ese intercambio no entra en el contexto de la ejecución, y su coste no entra en el run manifest principal:
se anota aparte, bajo `runs/aside/`. Así que preguntar no afecta a la ejecución y tampoco duele que ese gasto vaya a la cuenta.

!!! warning "El `？` de ancho completo no cuenta; tiene que ser `?` de ancho medio"
    El reconocimiento de la consulta lateral solo acepta el `?` de **ancho medio** (ASCII `0x3f`). El `？` de ancho completo que produce por defecto el IME chino no se reconoce ——
    esa línea se toma como «añadir requisito» y va a la bandeja de entrada, **sin error**, solo que la respuesta que esperas no llega nunca.
    Es una errata en el código, ya anotada en la lista de defectos; hasta que se arregle, cambia el IME a inglés antes de escribir `?`.

De paso, sobre Ctrl+C: pulsarlo la primera vez durante la ejecución **interrumpe esa ronda y te deja decir algo**, no sale.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

Solo la segunda pulsación sale de verdad. (Si pulsas Ctrl-C en el prompt inicial `要做什么?`, sale directamente e imprime `已取消`.)

## Paso cuatro: meterlo en un script {#脚本}

La petición también puede pasarse como argumento, y los flags pueden ir antes o después de ella:

```bash
flower "帮我做一个 X"                      # la petición como argumento
flower --rounds 5 "帮我做一个 X"           # flag delante
flower "帮我做一个 X" --rounds 5           # flag detrás, equivalente
echo "帮我做一个 X" | flower --timeout 0   # por tubería a la entrada estándar, totalmente automático
```

También vale dar solo flags sin petición —— `flower --clarify-only` te preguntará primero qué quieres hacer y luego seguirá.

**Por qué se mantiene la vía de «Intro y luego escribir».** Ese par de comillas en la línea de comandos es puro lastre. Caso real:
la comilla de cierre se tecleó como la `”` china, zsh se quedó esperando la comilla de cierre de verdad (cayendo en el prompt de continuación `dquote>`),
parecía que el programa se había colgado, y en realidad no había arrancado ni una vez. Al ejecutar `flower` pelado se lee de la entrada estándar, sin parseo de shell,
así que comillas tipográficas, espacios, signos de exclamación y saltos de línea se escriben tal cual. La vía de la tubería usa la misma entrada ——
cuando la entrada estándar no es un terminal no imprime la cabecera del prompt: lee una línea directamente.

!!! danger "Sin supervisión hay que pasar `--timeout 0` explícitamente"
    En una tubería, con `nohup` o en CI no hay nadie que responda a las preguntas. Sin `--timeout 0`: la primera pregunta se salta porque
    «la entrada está cerrada», y **cada pregunta posterior espera los 1800 segundos completos**; unas pocas preguntas son varias horas girando en vacío,
    y ese tiempo está quemando dinero.
    `--timeout 0` hace que toda pregunta caiga al vacío de inmediato devolviendo «nadie responde», y él decide y sigue.
    Cuando la entrada estándar no es un terminal, flower imprime primero un aviso:
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## Qué leer a continuación {#接下来}

| Si quieres saber | Lee |
|---|---|
| Qué significan exactamente estas palabras de la pantalla | [Conceptos básicos](concepts.md) |
| Todos los subcomandos y flags, sin dejarse ninguno | [Referencia de la línea de comandos](../reference/cli.md) |
| Por qué pregunta tanto al principio y cómo hacer que pregunte menos | [Clarify](../guide/clarify.md) |
| Quién dictamina si «está hecho» y cómo se escribe la lista de verdict | [Goal guard](../guide/goal.md) |
| Por qué al ejecutarlo otra vez en el mismo directorio retoma donde iba | [Continuidad](../guide/continuity.md) |
| Qué hace cuando el contexto se llena (no es compact) | [Handoff](../guide/handoff.md) |
| Credenciales, pasarela, nombre de modelo, variables de entorno | [Referencia de configuración](../reference/config.md) |
| Sustituir el terminal, conectar Web / TUI / totalmente automático | [Capa de interacción](../guide/interaction.md) |
| No usar los tres pasos incluidos y escribir tu propio workflow | [Diseñar un workflow](../guide/workflow.md) · [API de Python](../reference/api.md) |
| Qué ocurrió de verdad en una ejecución larga real | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| La definición precisa de algún término | [Glosario](../reference/glossary.md) |
