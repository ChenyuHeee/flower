# Guardián de objetivos

«¿Está terminado?» no lo decide el ejecutor. El [juez](../reference/glossary.md#判定者) es un rol que
solo fija el objetivo, solo emite veredicto y no toca nada: antes de arrancar convierte el
[brief](../reference/glossary.md#需求确认书) en un checklist verificable, y después, al final de cada
ronda de trabajo, **emite un veredicto de forma independiente** y produce un
[veredicto](../reference/glossary.md#判定) — si está alcanzado se sigue adelante, si no se devuelve con
el «qué falta» para continuar, y si dictamina que no se puede hacer, se detiene y pregunta a la persona.

## Qué problema resuelve {#解决什么问题}

La [clarificación previa](clarify.md) bloquea **«no es esto lo que quería»**. Esta capa bloquea otra cosa:
**«en realidad no está terminado, pero él dice que sí»**. Son dos asuntos que deben separarse, porque
fallan de forma distinta:

| | Cómo se ve el fallo | Cuándo se manifiesta |
|---|---|---|
| Requisito equivocado | Todo lo producido está construido sobre el requisito equivocado | Horas después, todo el resultado a la basura |
| Juicio de completitud equivocado | Tests a medio pasar, un sitio corregido y tres olvidados, «no debería haber problema» | Cuando lo vas a usar tú |

Por qué el segundo caso no puede quedar en manos del propio ejecutor: **tiene un sesgo optimista sistemático**.
No es que sea deshonesto — es que no ve sus propios puntos ciegos. Sabe lo que hizo, no sabe lo que se dejó.

Por eso el veredicto se le da a un rol que **no participó en el trabajo y corre en su propia
[sesión](../reference/glossary.md#会话)**. Solo ve el objetivo y el terreno; no sabe cuántas veces lo
intentó el ejecutor ni lo mucho que le costó, así que no le va a buscar excusas. Es la misma razón por la
que el clarificador corre en una sesión independiente.

## Cómo se usa (código mínimo) {#怎么用最小代码}

### Cero código: línea de comandos {#零代码命令行}

```bash
flower                      # el guardián de objetivos viene activado por defecto
flower --no-goal            # desactivarlo: al terminar el trabajo, se da por hecho
flower --rounds 5           # como mucho cinco rondas de trabajo (por defecto 3)
flower --judge-can-run      # dejar que el juez ejecute comandos (veredicto más duro)
```

### Cablearlo tú mismo {#自己接线}

Dos funciones, cada una con su mitad; no las mezcles: `goal_step()` **fija el objetivo** (un paso
independiente), y `with_goal()` es el **bucle de veredicto** (envuelve un paso de trabajo).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # por defecto, sin límite de preguntas
goal_path = wb.notes / "目标.md"

work = Step("干活", spec=协调者, prompt=lambda ctx: f"照这个做:\n{ctx['确认需求']}")

wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    goal_step(ch, goal_path=goal_path),
    with_goal(work, ch, goal_path=goal_path, rounds=3),
])
```

`goal_step(channel, *, goal_path, ...)`:

| Parámetro | Por defecto | Descripción |
|---|---|---|
| `goal_path` | — | Dónde aterriza el objetivo. Ponlo bajo `notes/` del [workbench](../reference/glossary.md#工作台), por la misma razón que el brief |
| `brief_key` | `"确认需求"` | De qué clave de `ctx` se lee el brief. **Si no lo encuentra, solo obtiene `"(没有确认书)"`** |
| `name` | `"设定目标"` | Nombre del paso, y también la clave en `ctx` |
| `spec` / `instructions` | `None` / `""` | Tu propio `AgentSpec`, o instrucciones de dominio añadidas al juez |
| `always_set` | `False` | `True` = volver a fijarlo cada vez |
| `on_fail` / `retries` | `"stop"` / `0` | Igual que en `Step` |
| `**spec_kw` | — | Se pasa a `judge()`: `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` envuelve un paso de trabajo en un bucle con veredicto:

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` es el número total de rondas, no el de rondas extra** — se traduce en
`retries = max(0, rounds - 1)`, así que `rounds=3` son como mucho tres rondas de trabajo, y `rounds=1`
significa «una ronda, un veredicto, y si no pasa, falla».
La firma completa y la semántica de los campos están en la [API de Python](../reference/api.md).

En `ctx` aparecen tres claves más:

```python
ctx[GOAL_KEY]     # "_goal" —— el objeto Goal; ctx["设定目标"] es su markdown
ctx[VERDICT_KEY]  # "_verdict" —— el último Verdict, para la UI
ctx[ROUND_KEY]    # "_goal_rounds" —— cuántas rondas se han corrido
```

El juez se lanza a través de `ctx["_runtime"]` — `Workflow.run` mete el runtime y la salida de eventos en
`ctx`, de modo que `gate` puede levantar su propio agente y el proceso de veredicto se sigue viendo en tu UI
(si no, esos diez y pico segundos con la pantalla en negro parecen un cuelgue).

Cuando algo no cuadra, toca primero estos mandos:

| Síntoma | Qué ajustar |
|---|---|
| Veredicto demasiado laxo, dice alcanzado y no lo está | `--judge-can-run` para que lo ejecute de verdad; o añade criterios de dominio en `instructions` |
| Veredicto demasiado estricto, devuelve siempre | Mira si el checklist de `目标.md` está escrito por encima del propio requisito. **Edita ese archivo** |
| Rondas que giran en vacío | El juez debería dar «inalcanzable» y da «aún no». Añádele instrucciones que expliquen qué cuenta como imposible |
| Demasiado caro | `--rounds 1`, o `--no-goal` para desactivarlo del todo |
| No quieres interrupciones | `--timeout 0`: al ser inalcanzable no pregunta, se detiene sin más (el motivo queda en disco) |

## Qué hace realmente {#它实际做了什么}

### Cómo es un objetivo {#目标长什么样}

`goal_step` lee el brief, produce dos secciones y las congela en `.flower/notes/目标.md`:

```markdown
# 目标
让 conv.py 能把 md 转成 html。

# 判定清单
- 跑 `python conv.py a.md` 产出 a.html
- 输出里含 `<h1>`
- 列表被转成 `<ul><li>`
```

**El checklist de veredicto es todo el valor de esta capa.** «Implementación completa» no se puede juzgar;
«qué se ejecuta y qué se ve» sí. El checklist sale de los «criterios de aceptación» del brief, pero hay que
reescribirlo de forma que cada línea sea verificable en el acto — las líneas vagas las completa el juez.
Solo se considera completo si las dos secciones son no vacías (`statement` con contenido, `checks` no vacío);
si no, este paso no deja pasar.

### La longitud del checklist la decide «cuántas formas de fallar hay» {#清单的长度由有多少种失败方式决定}

No la decide lo riguroso que sea el juez. Para una tarea del tipo `git clone && make && ./app`,
**con tres a cinco líneas basta**: compila, arranca, se puede usar.

**Tropezón medido** ([HT002](../cases/ht002.md)): una tarea de «instalar el repo y hacerlo correr» acabó con
un checklist de **15 líneas**, de las cuales solo **5** verificaban «si la cosa funciona», **6** verificaban
«si el proceso siguió las reglas» (incluida comprobar el mtime de `~/.zshrc` y si el directorio `.flower/`
había sido modificado — que es el directorio del propio framework), y **4** eran imposibles de verificar por
principio.

#### Los límites no son ítems del checklist {#边界不是判定项}

Esa fue la causa principal de aquella vez:

| | Qué restringe | Cómo se cumple |
|---|---|---|
| **Límites** | **Cómo trabajas** («instala solo dentro del directorio del proyecto», «no toques el código de negocio») | Con **no cruzarlos**, no con autocertificarse después |
| **Ítems del checklist** | **Lo que entregas** («¿arranca?», «¿el resultado es correcto?») | Con verificación en el acto |

Convertir «no ejecuté `brew install`» en un ítem del checklist equivale a que cada límite añadido genere una
comprobación más — y los límites son precisamente lo que se anima a escribir en abundancia durante la fase de
clarificación. Si de verdad hace falta rendir cuentas, una frase basta; no lo desgloses en seis líneas.

### Los ítems no verificables se avisan al fijar el objetivo {#验不了的条目设目标时就会喊}

Para los ítems marcados con `[此环境无法验证:原因]`, `goal_step` lanza un aviso **en el momento mismo de
congelar el objetivo**:

```text
  # 目标里有 4/15 条在这个环境里验不了 —— 判定时它们必然过不去,会停下来问你。
    现在改 .flower/notes/目标.md 还来得及:
      · 界面截图并实际看图 [此环境无法验证:屏幕录制未授权]
      · ...
```

**Por qué hay que adelantarlo**: el destino de esos ítems queda sellado en el instante en que se fija el
objetivo; en el veredicto no van a pasar. En HT002 primero se gastaron **$35.90 de trabajo + $1.40 de
veredicto** y solo después se descubrió — adelantar el descubrimiento al paso de fijar el objetivo baja el
coste de la misma información de **$37** a **$0**.

Solo avisa, no bloquea: la persona puede decidir correr igual (en HT002 al final se eligió «aceptar este
resultado»). `Goal.unverifiable` es esa lista, y el payload del evento lleva datos estructurados para la UI.

### Tres conclusiones, no dos {#三个结论不是两个}

```text
trabajo ──> veredicto ──alcanzado────> seguir adelante
                       ├─aún no──────> devolver con el «qué falta», se reanuda la misma sesión
                       └─inalcanzable─> parar y preguntar: aceptar / cambiar objetivo / te equivocaste
```

La tercera conclusión es la clave. Con solo «alcanzado / aún no», un objetivo que **en realidad no se puede
lograr** hace que el coordinador gire en vacío ronda tras ronda hasta agotar el crédito — eso sí que es
quemar dinero. Por eso al juez se le exige explícitamente: inalcanzable es «otra ronda tampoco serviría»
(falta una condición externa necesaria, el requisito se contradice a sí mismo, el ítem del checklist no se
puede verificar de ninguna manera); si es solo «todavía no está terminado», es aún no.

Cuando es inalcanzable, el framework se detiene y pregunta:

```text
  ? 目标被判为**无法达成**:缺少 X 依赖,判定项 2 无法验证
    怎么办?
     1) 接受这个结果,就这样往下走
     2) 修改目标
     3) 你判断错了,继续做
```

- **Aceptar** → este paso se da por pasado, el motivo queda en el registro
- **Cambiar el objetivo** → te pregunta cuál es el nuevo objetivo y lo **añade** al final del objetivo
  original (se ve qué cambió), y va otra ronda
- **Te equivocaste** (y cualquier respuesta libre que escribas) → se devuelve con lo que has dicho y va otra ronda

**Si no hay nadie que responda, se detiene**, no sigue girando en vacío — es intencionado. Si el veredicto
dice que no se puede y no hay a quién preguntar, seguir corriendo es quemar dinero ronda tras ronda, que es
justo lo que hay que evitar. Al detenerse lanza `StepAbort`, el motivo se escribe en `ctx["_aborted"]`, y
tanto el archivo de objetivo como `runs/manifest.json` siguen ahí para que la persona decida al volver.

!!! warning "«no se logró» y «aquí no se puede verificar» son dos conclusiones distintas"
    Los tres valores de `Verdict` son `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` no puede darse nunca por aprobado** — va por el camino de «parar y preguntar», no por el
    de «otra ronda». Todo lo que el juez escriba como «无法验证 / 没法验证 / 验证不了 / 无法判定 /
    unverifiable» cae **entero** en `UNREACHABLE`. Tomar «aquí no se puede verificar» como «alcanzado»
    equivale a cerrar el trabajo con un «parece que debería funcionar»; tomarlo como «aún no» es hacerle
    repetir ronda tras ronda algo que de entrada no se puede verificar.

### Veredicto ambiguo = aún no {#判定含糊--未达成}

Orden de reconocimiento de `Verdict.parse`: primero toma la sección titulada «结论 / 判定»; si no hay
secciones con título, un texto entero igual a `1` / `true` cuenta como alcanzado y `0` / `false` como aún no
(cuando al juez se le pide «devuelve solo 0/1», es muy probable que responda literalmente un número); si eso
falla, busca palabras clave en el texto de la conclusión (las largas primero); y por último busca un `1` / `0`
aislado.

**Si nada encaja, `state` queda vacío, `ok` es `False`, y el framework lo trata como aún no.** Esto es
deliberado: «no se pudo determinar» y «está terminado» son dos cosas distintas; lo ambiguo se trata siempre
como aún no, y se añade un motivo por defecto («el juez no dio una conclusión clara, se trata como aún no»).

### Se juzga el artefacto, no el código fuente {#判的是产出物不是源码}

!!! warning "Un veredicto que solo lee el código fuente no puede juzgar el entregable"
    En [HT001](../cases/ht001.md), el criterio de aceptación decía literalmente «compilar un ejecutable
    independiente que corra directamente en la terminal de macOS», y el veredicto se limitó a leer
    `Makefile:25-38`, ver que había una rama Darwin y dar **aprobado** — el artefacto entregado era
    `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **Quien se equivocó no fue el guardián de objetivos**: aquella ejecución todavía no tenía este mecanismo,
    y quien juzgó esa línea fue un auditor independiente que el propio coordinador lanzó sobre la marcha.
    Pero con el guardián de objetivos habría fallado igual — el juez lleva `can_run=False` por defecto y en
    la mano solo tiene `Read` / `Glob` / `Grep`: **no puede ejecutar `file`**, así que igualmente tendría que
    leer el `Makefile` e igualmente daría por alcanzado al ver la rama Darwin. El nudo de ese fallo no está en
    «quién juzga», sino en «con qué evidencia se juzga».

    Esa lección quedó escrita en `JUDGE_RULES`: se juzga el **artefacto**, y no se aceptan inferencias del
    tipo «en el código hay una rama macOS, así que debería correr».

[HT002](../cases/ht002.md) fue la vez que `judge_can_run` estaba activado y el juez fue de verdad a ejecutar
`file` / `lsof`, y por eso esquivó el agujero — su primera frase fue «no saco conclusiones de esa respuesta;
voy al terreno». Y entonces:

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → arrancó a las 16:10, a las 16:15 seguía vivo
```

La frase del prompt de veredicto dice justo eso: ve tú al terreno, recorre el checklist línea a línea, y
**un ítem del que no veas evidencia es un ítem no pasado**.

### «Devolver» es continuar, no empezar de cero {#打回是接着做不是重头做}

La devolución usa `Step.on_reject`: la siguiente ronda **hace `resume` de la sesión que acaba de ser
rechazada**, y el prompt se sustituye por el feedback del veredicto (`Verdict.feedback()` solo da el «qué
falta», no la solución). Así que el trabajo ya hecho, los archivos leídos y los callejones sin salida
recorridos siguen en el contexto; solo tiene que cubrir la diferencia.

La diferencia queda escrita en el nombre del paso, y se ve de un vistazo en `runs/manifest.json`:

```text
干活            primera ronda
干活#round2     continuar tras la devolución   ← on_reject activo, resume de la ronda anterior
干活#retry1     reintento normal (desde cero)  ← el comportamiento antiguo, sin on_reject
```

El juez, en cambio, **siempre corre en una sesión nueva**: el `gate` de `with_goal` llama directamente a
`Runtime.run` sin `resume`; el nombre del paso lleva el número de ronda (`干活·判定#1`), y los nombres con
sufijo no entran en el [linaje](../reference/glossary.md#血缘) entre procesos.
Si dentro del `gate` no consigue `ctx["_runtime"]`, lanza `StepAbort` y **no finge aprobar**.

### Saltar y volver a fijar {#跳过与重设}

Si el archivo de objetivo ya existe y está completo, este paso **se salta** (igual que con el brief) — cuando
una ejecución de [largo horizonte](../reference/glossary.md#长程) se cae y se reinicia, no hay que recalcular
las conclusiones anteriores. Para volver a fijarlo, borra el archivo, o usa `always_set=True`.

**Excepción: al despertar has dicho algo más.** Esa frase se añade al brief, y entonces este paso
**vuelve a derivar el objetivo** (`always_set=True`). Si no se rederivara, el juez seguiría leyendo el
checklist congelado antiguo y lo que acabas de pedir ni siquiera entraría en el veredicto — daría «alcanzado»
según el checklist viejo. El coste medido de rederivar es **$0.41 / 3 minutos**.
Ver [continuidad](continuity.md).

### Si el juez puede ejecutar comandos {#判定者能不能跑命令}

Por defecto **no**. La lista sin aprobación de `judge()` son las herramientas de pregunta más
`Read` / `Glob` / `Grep`; solo con `can_run=True` se añade `Bash`. El compromiso:

- Darle `Bash` (el `--judge-can-run` de la CLI) → puede ejecutar de verdad los comandos de aceptación, el
  veredicto es más duro
- Pero entonces puede modificar el workspace → puede «arreglarlo de paso» y después aprobar, y ese veredicto
  ya no vale nada

Igual que el clarificador, **no tiene `Write` / `Edit` / `Agent`**. Quien impone esto es el hook
`whitelist_guard`, **no `allowed_tools`** — esto último es una **lista sin aprobación, no una lista blanca
excluyente**, y el modelo puede seguir invocando herramientas que no estén en ella. Evidencia medida de que
ambas cosas siguen siendo ciertas: en HT002, el juez del paso «设定目标» ejecutó **11 veces `Bash`** cuando
`Bash` ni siquiera estaba en su lista sin aprobación; y en la **sonda de $0.1**, un agente con
`allowed_tools=["Read"]` emitió igualmente llamadas a `Write` y `Bash`, y fueron la capa de permisos y la
seguridad de rutas las que las frenaron
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Hoy esas dos llamadas las deniega el hook en el acto —
**quien lo para es el hook, no la lista**.

!!! warning "El juez que fija el objetivo no tiene `Bash` por defecto"
    `goal_step()` **no tiene parámetro `can_run`**; hay que pasarlo por `**spec_kw`:
    `goal_step(ch, goal_path=…, can_run=True)`. Si no se lo das explícitamente, no tiene `Bash`, y la línea de
    `JUDGE_RULES` que dice «primero `uname -a` para saber dónde estás» no se puede ejecutar — con lo que
    puede escribirte un checklist que en esta máquina no hay forma de verificar. `with_goal()` es otra cosa:
    tiene su propio parámetro `can_run` (por defecto `False`).

### Por qué las rondas tienen tope y las preguntas no {#为什么轮数有上限而提问次数没有}

Preguntar casi no cuesta dinero; una ronda de trabajo es dinero de verdad. Por eso:

- **Preguntas sin límite** (`max_asks=None`) — hasta que quede claro, lo decide el propio clarificador
- **Rondas con tope** (`rounds=3`) — pero el verdadero cortafuegos no es ese número, sino la tercera
  conclusión, «inalcanzable»: en cuanto aparece se para y se pregunta, sin esperar a agotar las rondas

## Cuándo no deberías usarlo {#什么时候不该用它}

**Cuando la tarea es tan pequeña que juzgarla es más engorroso que hacerla.** Esta capa complica los problemas
simples, y está medido: en HT002, aquello de «clonar un repo, instalarlo y hacerlo correr en macOS» acabó con
un checklist de 15 líneas, de las cuales 6 verificaban el cumplimiento del proceso y 4 eran imposibles de
verificar por principio; ese veredicto costó por sí solo **$1.4037 / 37 turnos / 0.09h**, y la ejecución
completa **$38.2409 / 0.97h**. Cuando la tarea solo tiene dos o tres formas de fallar, `--no-goal` sale más a
cuenta.

**Cuando el objetivo no se puede escribir como un checklist verificable.** El trabajo exploratorio
(«mira a ver de qué va este repo») no tiene criterio de «terminado»; forzar un objetivo solo produce un
checklist bonito e injuzgable. Para eso, usa `flower once`, o `--no-goal`.

**Cuando el ítem clave del checklist no se puede verificar en este entorno.** El juez lleva `can_run=False`
por defecto y sus herramientas son solo `Read` / `Glob` / `Grep` — **no puede ejecutar `file`**, solo leer el
código. Aquel criterio de [HT001](../cases/ht001.md), «correr directamente en la terminal de macOS», con toda
la ejecución dentro de un contenedor Linux: **ningún juez puede verificar un binario de macOS dentro del
contenedor**, sea autoevaluación o independiente. `--judge-can-run` salva una parte (al menos puede ejecutar
`file`); la parte que no salva debería marcarse ya al fijar el objetivo como `[此环境无法验证:…]`, para que
vaya por el camino de «parar y preguntar», en vez de esperar a que el juez se vuelva más listo.

**Cuando corre desatendido y no se permiten interrupciones.** Si el veredicto es inalcanzable y nadie
responde, este paso **se para** y el [flujo](../reference/glossary.md#流程) entero termina ahí. Si lo que
quieres es «que acabe y ya veremos», usa `--no-goal`; si lo que quieres es «que se pare pero sin esperar»,
usa `--timeout 0` — la pregunta se queda sin respuesta al instante y el motivo se escribe en disco.

**No comprueba si el requisito es correcto.** El checklist se deriva del brief; si el brief está mal, el
veredicto solo verificará con precisión algo equivocado. Eso es asunto de la capa de
[clarificación previa](clarify.md).
