# Guardián de objetivos

Si el trabajo está hecho o no, no lo dice el ejecutor. El [juez](../reference/glossary.md#判定者) es un rol que solo fija el objetivo,
solo dictamina y no toca nada: antes de arrancar convierte el [brief](../reference/glossary.md#需求确认书) en una lista
verificable, y después de cada ronda de trabajo **dictamina una vez de forma independiente**, produciendo un [veredicto](../reference/glossary.md#判定) —
si se logró, se sigue adelante; si no, se devuelve con el «qué falta» para continuar,
y si dictamina que es inalcanzable, se detiene y pregunta a la persona.

## Qué problema resuelve {#解决什么问题}

La [clarificación previa](clarify.md) bloquea **«hacer algo que no es lo que se quería»**. Esta capa bloquea otra cosa:
**«en realidad no está terminado, pero él mismo dice que sí»**. Son dos cosas que hay que separar, porque los modos de fallo son distintos:

| | Cómo se ve el fallo | Cuándo se manifiesta |
|---|---|---|
| Requisito equivocado | Todo lo producido está construido sobre el requisito equivocado | Horas después, todo el resultado se tira |
| Juicio de completitud equivocado | Tests corridos a medias, un sitio arreglado y tres olvidados, «no debería haber problema» | Cuando vas a usarlo tú |

Por qué el segundo caso no puede quedar en manos del propio ejecutor: **tiene un sesgo optimista sistemático**.
No es que sea deshonesto — es que no ve sus propios puntos ciegos. Sabe lo que hizo, no sabe lo que se le pasó.

Por eso el veredicto se le da a un rol **que no participó en el trabajo y corre en su propia [sesión](../reference/glossary.md#会话)**.
Solo ve el objetivo y el terreno; no sabe cuántas veces lo intentó el ejecutor ni lo que le costó, así que no le buscará excusas.
Es la misma razón por la que el clarificador corre en una sesión independiente.

## Cómo se usa (código mínimo) {#怎么用最小代码}

### Cero código: línea de comandos {#零代码命令行}

```bash
flower                      # el guardián de objetivos viene activado por defecto
flower --no-goal            # apagarlo: terminar el trabajo cuenta como terminar
flower --rounds 5           # como máximo cinco rondas de trabajo (por defecto 3)
flower --judge-can-run      # dejar que el juez ejecute comandos (veredicto más duro)
```

### Cablearlo tú mismo {#自己接线}

Dos funciones cubren cada mitad, no las mezcles: `goal_step()` **fija el objetivo** (un paso independiente),
y `with_goal()` es el **bucle de veredicto** (envuelve un paso de trabajo).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # por defecto, preguntas ilimitadas
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
| `goal_path` | — | Dónde aterriza el objetivo. Ponlo bajo `notes/` del [banco de trabajo](../reference/glossary.md#工作台), por la misma razón que el brief |
| `brief_key` | `"确认需求"` | De qué clave de `ctx` leer el brief. **Si no la encuentra, solo obtiene `"(没有确认书)"`** |
| `name` | `"设定目标"` | Nombre del paso, y también el nombre de la clave en `ctx` |
| `spec` / `instructions` | `None` / `""` | Traer tu propio `AgentSpec`, o añadir instrucciones de dominio al juez |
| `always_set` | `False` | `True` = volver a fijarlo cada vez |
| `on_fail` / `retries` | `"stop"` / `0` | Igual que en `Step` |
| `**spec_kw` | — | Se pasan a `judge()`: `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` envuelve un paso de trabajo en un bucle con veredicto:

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` es el total de rondas, no rondas adicionales** — aterriza como `retries = max(0, rounds - 1)`,
así que `rounds=3` corre como máximo tres rondas de trabajo, y `rounds=1` es «corre una ronda, dictamina una vez, y si no pasa, falla».
La firma completa y la semántica de los campos están en la [Python API](../reference/api.md).

En `ctx` aparecen tres claves nuevas:

```python
ctx[GOAL_KEY]     # "_goal" —— el objeto Goal; ctx["设定目标"] es su markdown
ctx[VERDICT_KEY]  # "_verdict" —— el último Verdict, para la UI
ctx[ROUND_KEY]    # "_goal_rounds" —— cuántas rondas se corrieron
```

El juez se despacha a través de `ctx["_runtime"]` — `Workflow.run` mete el runtime y la salida de eventos en `ctx`,
de modo que el `gate` puede levantar su propio agente y el proceso de veredicto sigue llegando a tu UI
(si no, esa docena de segundos con la pantalla en negro parece un cuelgue).

Cuando no acaba de salir bien, mueve primero estas perillas:

| Síntoma | Qué ajustar |
|---|---|
| Veredicto demasiado laxo, dice logrado y no lo está | `--judge-can-run` para que lo corra de verdad; o añade criterios de dominio en `instructions` |
| Veredicto demasiado estricto, devuelve todo el tiempo | Mira si la lista de verificación de `目标.md` está escrita más alta que el propio requisito. **Edita ese archivo** |
| Ronda tras ronda girando en vacío | El juez debería dar «inalcanzable» y da «no todavía». Añádele instrucciones sobre qué cuenta como imposible |
| Demasiado caro | `--rounds 1`, o `--no-goal` para apagarlo del todo |
| No quieres que te interrumpan | `--timeout 0`: cuando sea inalcanzable no pregunta, se detiene directamente (el motivo queda en disco) |

## Qué hace en realidad {#它实际做了什么}

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

**La lista de verificación es todo el valor de esta capa.** «Implementación completa» no se puede dictaminar; «qué se corre, qué se ve» sí.
La lista sale de la sección «验收标准» del brief, pero se reescribe para que cada línea sea verificable en el momento — las líneas vagas las completa el juez.
Solo cuando las dos secciones no están vacías (`statement` dice algo, `checks` no está vacío) se considera completo; si no, este paso no deja pasar.

### La longitud de la lista la decide «cuántos modos de fallo hay» {#清单的长度由有多少种失败方式决定}

No la decide lo escrupuloso que sea el juez. Para una tarea como `git clone && make && ./app`, **tres a cinco líneas bastan**:
la construcción funciona, arranca, se puede usar.

**Nos estrellamos en la práctica** ([HT002](../cases/ht002.md)): una tarea de «instalar el repo y ponerlo a correr» se escribió como una lista de **15** líneas,
de las cuales solo **5** verificaban «si la cosa funciona», **6** verificaban «si el proceso siguió las reglas»
(incluido consultar el mtime de `~/.zshrc` y comprobar si el directorio `.flower/` había sido modificado — ese es el propio directorio del framework),
y **4** eran verificables en principio.

#### Los límites no son ítems de veredicto {#边界不是判定项}

Esa fue la causa principal en aquel caso:

| | Qué restringe | Cómo se cumple |
|---|---|---|
| **Límite** | **Cómo trabajas** («instala solo dentro del directorio del proyecto», «no toques el código de negocio») | **No cruzándolo**, no autocertificándolo después |
| **Ítem de veredicto** | **Lo que entregas** («¿arranca?», «¿el resultado es correcto?») | Verificándolo en el momento |

Escribir «no ejecuté `brew install`» como ítem de veredicto equivale a que cada límite añadido sume una comprobación —
y los límites son justo lo que la fase de clarificación anima a escribir en abundancia. Si de verdad hace falta dar cuentas, una frase basta; no lo desgloses en seis líneas.

### Los ítems que no se pueden verificar se avisan al fijar el objetivo {#验不了的条目设目标时就会喊}

Para los ítems marcados con `[此环境无法验证:原因]`, `goal_step` emite un aviso **en el momento mismo de congelar el objetivo**:

```text
  # 目标里有 4/15 条在这个环境里验不了 —— 判定时它们必然过不去,会停下来问你。
    现在改 .flower/notes/目标.md 还来得及:
      · 界面截图并实际看图 [此环境无法验证:屏幕录制未授权]
      · ...
```

**Por qué avisar antes**: el destino de esos ítems queda sellado en el instante en que se fija el objetivo; en el veredicto no van a pasar, seguro.
En HT002 se gastaron primero **$35.90 de trabajo + $1.40 de veredicto** y solo después se descubrió —
adelantar el hallazgo al paso de fijar el objetivo baja el coste de la misma información de **$37** a **$0**.

Solo avisa, no bloquea: la persona puede elegir correr así (en HT002 al final se eligió «aceptar este resultado»).
`Goal.unverifiable` es esa lista, y el payload del evento lleva datos estructurados para la UI.

### Tres conclusiones, no dos {#三个结论不是两个}

```text
干活 ──> 判定 ──达成────> 往下走
              ├─未达成──> 打回,带上“差在哪”,续跑同一个会话接着做
              └─无法达成─> 停下来问人:接受 / 改目标 / 你判断错了
```

La tercera conclusión es la clave. Con solo «logrado / no todavía», un objetivo **que en realidad es imposible** haría que el coordinador
girara en vacío ronda tras ronda hasta agotar el saldo — eso sí es quemar dinero. Por eso al juez se le exige explícitamente:
solo cuenta como inalcanzable cuando «otra ronda tampoco serviría de nada» (falta una condición externa necesaria, el requisito se contradice a sí mismo, el ítem de veredicto es imposible de verificar);
si simplemente «aún no está terminado», eso es no todavía.

Cuando es inalcanzable, el framework se detiene y pregunta:

```text
  ? 目标被判为**无法达成**:缺少 X 依赖,判定项 2 无法验证
    怎么办?
     1) 接受这个结果,就这样往下走
     2) 修改目标
     3) 你判断错了,继续做
```

- **Aceptar** → este paso cuenta como pasado, el motivo queda en el registro
- **Modificar el objetivo** → te pregunta cuál es el nuevo objetivo y lo **añade** al final del objetivo original (se ve qué cambió), y va otra ronda
- **Te equivocaste al juzgar** (y cualquier respuesta libre que escribas) → se devuelve con lo que has dicho, y va otra ronda

**Si nadie responde, se detiene**, no sigue girando en vacío — es intencionado. Dictaminado como imposible y sin nadie a quien preguntar,
seguir corriendo es quemar dinero ronda tras ronda, y eso es precisamente lo que más hay que evitar. Al detenerse lanza `StepAbort`, el motivo se escribe en
`ctx["_aborted"]`, el archivo de objetivo y `runs/manifest.json` siguen ahí, y la persona decide cuando vuelve.

!!! warning ""No se logró" y "aquí no se puede verificar" son dos conclusiones distintas"
    Los tres valores de `Verdict` son `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` no puede dictaminarse como aprobado bajo ningún concepto** — sigue el camino de «detenerse y preguntar», no el de «otra ronda».
    Todo lo que escriba el juez del tipo «无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable» va **entero** a
    `UNREACHABLE`. Tomar «aquí no se puede verificar» por «logrado» equivale a cerrar el trabajo con un «parece que debería funcionar»;
    tomarlo por «no todavía» es hacerle repetir ronda tras ronda algo que de entrada no se puede verificar.

### Veredicto ambiguo = no todavía {#判定含糊--未达成}

Orden de reconocimiento de `Verdict.parse`: primero toma por sección titulada el bloque «结论 / 判定»; si no hay secciones tituladas,
un texto entero igual a `1` / `true` cuenta como logrado, y `0` / `false` como no todavía (cuando al juez se le pide «devuelve solo 0/1»,
es muy probable que devuelva de verdad solo un número); si eso tampoco encaja, busca palabras clave en el texto de la conclusión (las palabras largas primero); por último busca un `1` / `0` aislado.

**Cuando nada encaja, `state` queda vacío y `ok` es `False`, y el framework lo trata como no todavía.** Esto es deliberado:
«no se puede dictaminar» y «está terminado» son dos cosas distintas; la ambigüedad va siempre a no todavía, con un motivo por defecto añadido
(«el juez no dio una conclusión clara, se trata como no todavía»).

### Se dictamina sobre el artefacto, no sobre el código fuente {#判的是产出物不是源码}

!!! warning "Un veredicto que solo lee el código fuente no puede dictaminar sobre el entregable"
    En [HT001](../cases/ht001.md), el criterio de aceptación decía literalmente «compilar un ejecutable independiente que corra directamente
    en la terminal de macOS», y el veredicto se limitó a leer que en `Makefile:25-38` había efectivamente una rama Darwin y lo dio por **aprobado** —
    el artefacto entregado era `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **Quien se equivocó no fue el guardián de objetivos**: aquella ejecución todavía no tenía este mecanismo, y quien dictaminó esa línea fue un
    auditor independiente que el propio coordinador despachó sobre la marcha. Pero con el guardián de objetivos también se habría escapado — el juez tiene `can_run=False` por defecto,
    solo dispone de `Read` / `Glob` / `Grep`, **no puede ejecutar `file`**, así que igualmente solo podría leer el `Makefile` y
    dictaminar «logrado» al ver la rama Darwin. La clave de ese fallo no está en «quién dictamina», sino en «con qué evidencia se dictamina».

    Esta lección quedó escrita en `JUDGE_RULES`: se dictamina sobre el **artefacto**, no se aceptan inferencias del tipo «en el código fuente hay una rama macOS, así que
    debería funcionar».

[HT002](../cases/ht002.md) es la vez en que `judge_can_run` estaba activado y el juez fue de verdad a ejecutar `file` / `lsof`,
por eso esquivó esa trampa — su primera frase fue «no saco conclusiones de esa respuesta. Voy al terreno». Y luego:

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → 起于 16:10,16:15 仍活着
```

Esa frase del prompt del juez significa exactamente eso: ve tú mismo al terreno, línea por línea contra la lista de verificación, y **un ítem de veredicto del que no ves evidencia
es un ítem no superado**.

### «Devolver» es seguir trabajando, no empezar de cero {#打回是接着做不是重头做}

La devolución usa `Step.on_reject`: la ronda siguiente hace **`resume` de la sesión que acaba de ser rechazada**, con el prompt cambiado por el feedback del veredicto
(`Verdict.feedback()` solo da «qué falta», no da la solución). Así que el trabajo ya hecho, los archivos ya leídos y los desvíos ya recorridos
siguen en el contexto; solo tiene que cubrir la diferencia.

La distinción se escribe en el nombre del paso, y se ve de un vistazo en `runs/manifest.json`:

```text
干活            第一轮
干活#round2     被打回后接着做      ← on_reject 生效,resume 上一轮
干活#retry1     普通重试(重头跑)    ← 没有 on_reject 时的老行为
```

El juez, en cambio, **siempre es una sesión nueva**: el gate de `with_goal` llama directamente a `Runtime.run`, sin `resume`;
el nombre del paso lleva la ronda (`干活·判定#1`), y los nombres con sufijo no entran en el [linaje](../reference/glossary.md#血缘) entre procesos.
Cuando el gate no consigue `ctx["_runtime"]`, lanza `StepAbort`, **no finge que ha pasado**.

### Saltar y volver a fijar {#跳过与重设}

Cuando el archivo de objetivo ya existe y está completo, este paso **se salta** (igual que el brief) — si una ejecución de [largo horizonte](../reference/glossary.md#长程)
se cae y se reinicia, no hay que recalcular las conclusiones anteriores. Para volver a fijarlo, borra ese archivo, o usa `always_set=True`.

**Excepción: al despertar has dicho algo más.** Esa frase se añade al brief, así que este paso **vuelve a derivarse**
(`always_set=True`). Sin volver a derivar, el juez seguiría leyendo la lista congelada vieja, y lo que acabas de añadir
ni siquiera entraría en el veredicto — dictaminaría «logrado» según la lista vieja. El coste medido de volver a derivar es **$0.41 / 3 minutos**.
Ver [continuidad](continuity.md).

### Si el juez puede ejecutar comandos {#判定者能不能跑命令}

Por defecto **no**. La lista sin aprobación de `judge()` son las herramientas de pregunta más `Read` / `Glob` / `Grep`;
solo con `can_run=True` se añade `Bash`. El compromiso:

- Darle `Bash` (el `--judge-can-run` de la CLI) → puede ejecutar de verdad los comandos de aceptación, veredicto más duro
- Pero entonces puede modificar el área de trabajo → puede «arreglarlo de paso» y luego dictaminar aprobado, con lo que ese veredicto pierde todo sentido

Igual que el clarificador, **no tiene `Write` / `Edit` / `Agent`**. Quien impone esto es el hook `whitelist_guard`,
**no `allowed_tools`** — este último es una **lista sin aprobación, no una lista blanca excluyente**: el modelo puede seguir invocando herramientas que no están en ella.
Dos pruebas medidas de que esto sigue siendo cierto: en HT002, el juez del paso «设定目标» ejecutó `Bash` **11 veces**,
cuando su lista sin aprobación no incluía `Bash` en absoluto; y en la **sonda de $0.1**,
un agente con `allowed_tools=["Read"]` emitió igualmente llamadas a `Write` y `Bash`, y fueron la capa de permisos y la seguridad de rutas las que las frenaron
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Hoy esas dos llamadas serían denegadas en el acto (`deny`) por el hook —
**quien las para es el hook, no la lista**.

!!! warning "El juez que fija el objetivo no tiene `Bash` por defecto"
    `goal_step()` **no tiene parámetro `can_run`**, solo se puede pasar vía `**spec_kw`: `goal_step(ch, goal_path=…, can_run=True)`.
    Si no se lo das explícitamente, no tiene `Bash`, y la regla de `JUDGE_RULES` que dice «primero `uname -a` para ver dónde estás» no se puede ejecutar —
    con lo que puede escribirte una lista que en esta máquina es directamente imposible de verificar. `with_goal()` es otra cosa,
    tiene su propio parámetro `can_run` (por defecto `False`).

### Por qué las rondas tienen tope y las preguntas no {#为什么轮数有上限而提问次数没有}

Preguntar casi no cuesta dinero; una ronda de trabajo es dinero contante. Por eso:

- **Preguntas sin límite** (`max_asks=None`) — hasta que quede claro, lo decide el propio clarificador
- **Rondas con tope** (`rounds=3`) — pero el verdadero cortafuegos no es ese número, sino la tercera conclusión, «inalcanzable»:
  en cuanto aparece, se detiene y pregunta, sin esperar a agotar las rondas

## Cuándo no deberías usarlo {#什么时候不该用它}

**Cuando la tarea es tan pequeña que dictaminarla es más engorroso que hacerla.** Esta capa complica los problemas simples, y está medido:
en HT002, aquello de «clonar un repo, instalarlo en macOS y ponerlo a correr», la lista de verificación se escribió con 15 líneas,
de las cuales 6 verificaban el cumplimiento del proceso y 4 eran inverificables en principio; ese veredicto en sí costó **$1.4037 / 37 turnos / 0.09h**,
y la ejecución completa **$38.2409 / 0.97h**. Cuando la tarea solo tiene dos o tres modos de fallo, `--no-goal` sale más a cuenta.

**Cuando el objetivo no se puede escribir como lista verificable.** El trabajo exploratorio («a ver de qué va este repo») no tiene criterio de «terminado»;
forzar un objetivo solo produce una lista bonita e indictaminable. Para eso usa `flower once`, o `--no-goal`.

**Cuando el ítem de veredicto clave no se puede verificar en este entorno.** El juez tiene `can_run=False` por defecto, y sus herramientas son solo
`Read` / `Glob` / `Grep` — **no puede ejecutar `file`**, solo puede leer el código fuente. En [HT001](../cases/ht001.md),
aquel criterio de «corre directamente en la terminal de macOS» tenía toda la ejecución dentro de un contenedor Linux:
**ningún juez puede verificar un binario de macOS dentro del contenedor**, sea autoevaluación o independiente.
`--judge-can-run` salva una parte (al menos puede ejecutar `file`); la parte que no salva debería marcarse al fijar el objetivo
como `[此环境无法验证:…]`, para que siga el camino de «detenerse y preguntar», en lugar de esperar a que el juez se vuelva más listo.

**Cuando corre desatendido y no se permite interrupción.** Si se dictamina inalcanzable y nadie responde, este paso **se detiene**, y todo el [flujo de trabajo](../reference/glossary.md#流程) acaba ahí.
Si lo que quieres es «que termine y luego ya veremos», usa `--no-goal`; si lo que quieres es «que se detenga pero sin esperar», usa `--timeout 0` —
la pregunta cae en el vacío al instante y el motivo se escribe en disco.

**No se ocupa de si el requisito es correcto.** La lista de verificación se deriva del brief; si el brief está mal, el veredicto solo verificará con precisión algo equivocado.
Eso es asunto de la capa de [clarificación previa](clarify.md).
