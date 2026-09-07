# Conceptos básicos

flower tiene su propio vocabulario: ejecución, paso, sesión, coordinador, ejecutor, clarificación previa, guardián de objetivos, continuidad, traspaso.
Esta página los explica todos de una vez; después de leerla, el resto de páginas ya no habrá que ir adivinando sobre la marcha. Cinco minutos de lectura.

Aquí solo se explican conceptos, **no se dan firmas de API** —— para firmas ve a [Python API](../reference/api.md),
para definiciones de una línea y equivalencias chino-inglés ve al [glosario](../reference/glossary.md), para los flags de línea de comandos ve a
[Referencia de línea de comandos](../reference/cli.md).

## Qué forma tiene una ejecución {#形状}

Tres niveles, de mayor a menor:

| Término | Qué es | Dónde se registra |
|---|---|---|
| [ejecución](../reference/glossary.md#运行) run | El proceso completo de un `Runtime`, de principio a fin. Por la ruta por defecto, una ejecución es una vez que tecleas `flower` | `runs/manifest.json` |
| [paso](../reference/glossary.md#步骤) step | Una unidad ejecutable dentro de la ejecución: recibe un diccionario de contexto, corre un agent y escribe el resultado de vuelta en el diccionario. Cada línea de `==` en pantalla es un límite de paso | Igual que arriba, una línea por paso |
| [sesión](../reference/glossary.md#会话) session | Un contexto del lado del modelo. Tiene su propio `session_id`, se puede hacer resume y fork | `runs/sessions.db` |

El anidamiento entre ellos no es uno a uno:

```text
ejecución ── esta vez que tecleaste flower
 ├── paso Confirmar requisitos ── sesión A
 ├── paso Fijar objetivo ─────── sesión B
 └── paso Trabajar ───────────── sesión C ──[contexto casi lleno]──> sesión C'
      └── Trabajar·veredicto#1 ─ sesión D
```

- **Un paso puede consumir varias sesiones.** Cuando el contexto está casi lleno no hace compact, sino que escribe un documento de traspaso y abre una sesión nueva que toma el relevo ——
  esto se llama [traspaso](../reference/glossary.md#换代) y ocurre **dentro de la misma ejecución**.
- **Una ejecución nueva puede engancharse a sesiones viejas.** Si tecleas `flower` otra vez en el mismo directorio, cada paso vuelve a engancharse a la sesión de la vez anterior ——
  esto se llama [continuidad](../reference/glossary.md#接续) y ocurre **entre procesos**. Se apoya en `runs/lineage.json`
  para recordar "qué nombre de paso corresponde a qué `session_id`".
- **La ronda de veredicto siempre es una sesión nueva.** No tiene continuidad ni entra en el linaje —— quien juzga "si está hecho o no" no puede ser el mismo ejecutor de antes.

Un conjunto de pasos encadenados en orden es un [workflow](../reference/glossary.md#流程).
Cuando ejecutas `flower` en seco, se usa el workflow de tres pasos que trae el framework: confirmar requisitos → fijar objetivo → trabajar.

## Reparto: el coordinador no toca nada {#分工}

**Esta es la línea sobre la que se construye todo el framework.**

El [coordinador](../reference/glossary.md#协调者) es el agent que corre en el [hilo principal](../reference/glossary.md#主线程).
Descompone tareas, reparte trabajo, lee informes y toma decisiones —— pero **no tiene `Write` ni `Edit`**,
y su `Bash` solo alcanza para [comandos efímeros](../reference/glossary.md#一次性命令) tipo `ls` o `git status` para echar un vistazo
(controlado por un hook, no por restricciones en el prompt, y además esos resultados no entran en el registro persistente de la sesión).
Su tabla de herramientas es `Agent`, `TodoWrite`, `Read` y ese `Bash` restringido.

Quien trabaja de verdad es el [ejecutor](../reference/glossary.md#执行者) —— un
[subagent](../reference/glossary.md#subagent) despachado por la herramienta `Agent`.

**Por qué este reparto.** Un subagent tiene **su propia transcript**: cuántos ficheros leyó, cuántas veces corrió los tests,
cuántos rodeos dio probando cosas, todo queda ahí; el hilo principal solo recibe el informe final. Y el hilo principal es el único contexto que atraviesa toda la ejecución,
así que es el que más hay que ahorrar.

Medido ([HT001](../cases/ht001.md), una ejecución de 10.4 horas):

| | Hilo principal | subagent | Proporción hundida |
|---|---|---|---|
| Turnos de modelo | 70 | 3.0K | 97.7 % |
| Caracteres de texto | 200.1K | 3.6M | **94.8 %** |
| Llamadas a herramientas | 32 | 1,893 | —— |

Por cada delegación, en promedio, **82 llamadas a herramientas que el hilo principal nunca llega a ver**. Esta es la primera capa de ahorro de contexto, y la que más ahorra;
la argumentación completa está en [Economía del contexto](../guide/context.md).

Dos cosas que se malinterpretan con facilidad:

- **El coordinador no es un agent más listo.** Por defecto usa el mismo nivel de modelo que el ejecutor; lo que se ahorra es contexto, no modelo.
- **El formato de respuesta está restringido.** La respuesta del ejecutor tiene exactamente cuatro secciones —— conclusión / evidencia / entregables / no verificado, no más de 30 líneas,
  prohibido pegar contenido de ficheros, salida de comandos, logs o diffs en bruto. Lo largo se escribe en `artifacts/` del [workbench](../reference/glossary.md#工作台);
  en la respuesta solo va la ruta.

flower tiene cinco roles en total, todos con el mismo patrón: un texto de reglas inyectado + un conjunto de herramientas + un conjunto de hooks.

| Rol | Qué hace | Qué tiene en la mano |
|---|---|---|
| [coordinador](../reference/glossary.md#协调者) coordinator | Descomponer, delegar, decidir | `Agent` `TodoWrite` `Read` + `Bash` restringido |
| [ejecutor](../reference/glossary.md#执行者) worker | Escribir código, correr tests, investigar | `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| [clarificador](../reference/glossary.md#确认者) clarify | Antes de tocar nada, solo pregunta, hasta que quede claro | Herramienta de preguntas + herramientas de solo lectura, **ninguna herramienta de escritura** |
| [juez](../reference/glossary.md#判定者) judge | Fijar el objetivo, o juzgar si "esta ronda está hecha o no" | Herramienta de preguntas + `Read` `Glob` `Grep` (para que pueda ejecutar comandos hay que habilitarlo explícitamente) |
| [oráculo](../reference/glossary.md#旁路顾问) oracle | Responder a mitad de ejecución "por dónde vamos" | `Read` `Glob` `Grep`. **Lo que dice no entra en el contexto de esa ejecución** |

Los parámetros y valores por defecto de las funciones factoría están en [Python API](../reference/api.md#角色工厂).

## El largo horizonte se rompe por cuatro sitios {#四个机制}

Una ejecución de [largo horizonte](../reference/glossary.md#长程) abarca de horas a días, varias sesiones y reinicios de proceso.
Las formas en que se desmorona son unas pocas, y cada una tiene su mecanismo:

| Lo que temes | Mecanismo | Qué hace | Detalle |
|---|---|---|---|
| Que lo construido no sea lo que querías | [clarificación previa](../reference/glossary.md#前置确认) | Antes de tocar nada, deja claros los requisitos y los congela en un [brief](../reference/glossary.md#需求确认书); cada paso posterior lo lee, sin volver a adivinar | [Clarificación previa](../guide/clarify.md) |
| Que diga que está hecho cuando no lo está | [guardián de objetivos](../reference/glossary.md#目标看守) | Al final de cada ronda, un juez que no participó en el trabajo emite un veredicto independiente; si no se cumplió, se devuelve para seguir | [Guardián de objetivos](../guide/goal.md) |
| Que reviente tras varias horas y haya que empezar de cero | [continuidad](../reference/glossary.md#接续) | Ejecutar otra vez en el mismo directorio retoma automáticamente el progreso anterior —— igual si mataron el proceso o se reinició la máquina | [Continuidad](../guide/continuity.md) |
| Que el contexto se llene y quede reducido a un resumen | [traspaso](../reference/glossary.md#换代) | Cuando está casi lleno, la sesión actual escribe un [documento de traspaso](../reference/glossary.md#交接书) legible y editable por una persona, y una sesión nueva toma el relevo | [Traspaso](../guide/handoff.md) |

Dos puntos que conviene recordar aparte:

**El [veredicto](../reference/glossary.md#判定) tiene tres conclusiones, no dos.** Cumplido, no alcanzado y **este entorno no lo puede verificar**.
Las dos últimas son conclusiones distintas —— "aquí no se puede verificar" nunca se juzga como aprobado, sino que se para y se pregunta a una persona.
Y además el juez juzga los **entregables**, no el código fuente: en [HT002](../cases/ht002.md) se cayó una vez,
miró solo la rama macOS del Makefile y dio el visto bueno cuando lo entregado era un ELF de Linux.

**El traspaso no es [compact](../reference/glossary.md#压缩).** El compact es el modelo resumiendo por su cuenta, a oscuras, la conversación previa en un párrafo:
ilegible, inmodificable, y no sabes qué se perdió. El documento de traspaso es estructurado, está en disco, y puedes abrirlo, cambiar una línea y dejar que siga.
flower desactiva por defecto el auto-compact nativo y usa el traspaso en su lugar.

Hay otras dos capas que no están en esa tabla, pero que corren en cada ejecución:

- [spill](../reference/glossary.md#落盘) —— un resultado de herramienta que pase de 4000 caracteres se escribe en `.flower/spill/`,
  y en el contexto solo queda una línea con la ruta. **Se recorta en el acto**, no se espera a que se llene para hacer compact hacia atrás.
- [workbench](../reference/glossary.md#工作台) —— los tres directorios `scripts/`, `artifacts/` y `notes/` bajo `.flower/`,
  más un índice `INDEX.md` inyectado en el system prompt, de modo que el agent sabe en cada ronda qué tiene en la mano.
  En HT001 se acumularon **61 scripts, ejecutados 331 veces**, de los cuales el **92 %** se ejecutó más de una vez.

## Lo que flower no hace {#不做什么}

**Uno: no proporciona workflows hechos.** El framework solo se ocupa de los mecanismos: cómo corre un paso, cómo se ahorra contexto, cómo se retoma tras una caída de red,
cómo evitar que varias ejecuciones en paralelo sobre el mismo repositorio choquen, cómo pararse cuando hay que preguntar a una persona. **El workflow lo escribes tú.**
Los tres pasos que se usan al ejecutar `flower` en seco vienen de
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py),
tan genéricos que no contienen ninguna suposición de dominio —— están para que arranques, no son el límite de lo que el framework puede hacer.
Para escribir el tuyo, ve a [Diseñar un workflow](../guide/workflow.md).

**Dos: no hereda la configuración de la máquina anfitriona.** flower corre con `setting_sources=[]`: no lee el `~/.claude/` de la máquina
ni el `.claude/` del proyecto. Eso es ser [portable](../reference/glossary.md#可移植) —— mismo comportamiento al cambiar de máquina.
Las capacidades de dominio las trae un [plugin](../reference/glossary.md#plugin) que viaja con el repositorio, no lo que casualmente esté instalado en esta máquina.

**Tres: las credenciales las tienes que aportar tú.** Es el precio del punto dos. flower busca credenciales con una prioridad fija (variables de entorno del proceso →
`$FLOWER_ENV` → `.env` del directorio actual → `~/.config/flower/.env` → `.env` de la raíz del repositorio de código),
y al final toma prestadas las 9 claves de credenciales del bloque `env` de `~/.claude/settings.json` como último recurso ——
**solo toma prestado eso: dónde buscar el token**; ninguna otra cosa de settings.json afecta al comportamiento del agent.
El orden completo y la semántica de cada variable están en [Referencia de configuración](../reference/config.md).

**Cuatro: no reemplaza el system prompt.** Las instrucciones de dominio se [anexan](../reference/glossary.md#叠加) **después** del
system prompt nativo de Claude Code, no lo sustituyen. Por eso la especialización no cuesta capacidad general.

---

Llegado aquí, las salidas que aparecen en [Inicio rápido](quickstart.md) deberían resultarte legibles.
Si quieres saber cómo se ajusta cada mecanismo y cuándo no conviene usarlo, sigue desde [Economía del contexto](../guide/context.md);
si solo quieres copiar comandos, ve a [Referencia de línea de comandos](../reference/cli.md).
