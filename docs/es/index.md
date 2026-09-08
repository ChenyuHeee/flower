# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Framework portable de agentes de largo horizonte, construido sobre el Claude Agent SDK.</p>

<p class="fl-hero__sub">Sin sacrificar las capacidades de Claude Code, lo convierte en un agente especializado que puedes llevarte, cuya interacción puedes personalizar y que puede correr durante días.
El agente del hilo principal solo toma decisiones; todo el trabajo manual se delega a subagents. Los requisitos se aclaran antes de empezar, y si algo está terminado o no lo juzga otro rol.
En otra máquina se comporta igual: no lee la configuración del host y trae sus propias credenciales.</p>

[Primeros pasos](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>coste de una ejecución</span></div>
<div class="fl-stat"><b>10.4 horas</b><span>corriendo sin parar; se cayó la red y se reenganchó solo</span></div>
<div class="fl-stat"><b>185.9K</b><span>pico de contexto del hilo principal, sin un solo compact</span></div>
<div class="fl-stat"><b>94.8%</b><span>de los caracteres de texto cayeron en subagents</span></div>
</div>

Los cuatro números salen de [HT001](cases/ht001.md): la ejecución en la que un agente escribió desde cero un IDE de terminal bajo flower.

## Se instala con un comando, sin Node {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

El script busca automáticamente `uv` / `pipx` / `pip` para instalar el comando `flower`; solo hace falta Python ≥ 3.10,
y tampoco hay que instalar el CLI de Claude Code. Cuando termine, haz `cd` a cualquier directorio de proyecto y escribe `flower`: la primera vez te pedirá una API key
o la dirección de un gateway; se configura una vez, se guarda en `~/.config/flower/.env` y vale en todas partes. Si en esta máquina ya tienes Claude Code instalado y configurado,
toma prestado ese token directamente, sin preguntar nada. Los pasos completos y la resolución de problemas están en [Instalación](getting-started/install.md).

## Te protege de cuatro tipos de fallo {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Confirmación previa](guide/clarify.md) {#前置确认}

Miedo a que lo construido no sea lo que querías: antes de tocar nada hay un rol que solo pregunta y no ejecuta, y pregunta hasta que todo quede claro; congela los requisitos en un documento
que cada paso posterior lee al arrancar.
</div>

<div class="fl-card" markdown>
### [Guardián de objetivos](guide/goal.md) {#目标看守}

Miedo a que diga que ha terminado cuando en realidad no: al final de cada ronda de trabajo otro rol emite un juicio independiente; si se cumple, se sigue adelante; si no, se devuelve;
y si en este entorno no se puede verificar, se detiene y pregunta a una persona.
</div>

<div class="fl-card" markdown>
### [Continuidad](guide/continuity.md) {#接续}

Miedo a que se caiga tras varias horas y haya que empezar de cero: basta escribir `flower` otra vez en el mismo directorio para retomar el progreso anterior; da igual que el proceso se haya matado
o que la máquina se haya reiniciado, y no tienes que recordar ningún id.
</div>

<div class="fl-card" markdown>
### [Relevo](guide/handoff.md) {#换代}

Miedo a que el contexto se llene y quede reducido a un resumen: la sesión actual escribe por sí misma un documento de relevo legible y editable por una persona, y una sesión nueva toma el mando,
sin compact.
</div>

</div>

## Qué lo hace "de largo horizonte" {#长程}

El [coordinador](reference/glossary.md#协调者) del hilo principal solo carga decisiones y no tiene acceso a `Write` ni `Edit`:
escribir código, correr tests y buscar información se delegan todos a [subagents](reference/glossary.md#subagent),
y el ensayo y error del subagent va a **otra** transcript; el hilo principal solo recibe un informe de no más de 30 líneas.
En aquella ejecución de 10.4 horas de HT001, el **94.8% de los caracteres de texto cayó en subagents**,
y de las 1,893 llamadas a herramientas de trabajo manual solo 32 entraron en el campo de visión del coordinador.
Por eso el hilo principal solo llegó a 185.9K en 70 turnos y no hubo ni un compact en toda la ejecución. Cómo está hecha esta capa y cuáles son las otras tres,
en [Economía del contexto](guide/context.md).

## Registros crudos de dos ejecuciones largas reales {#真的跑过}

- **[HT001](cases/ht001.md)** — escribir un IDE de terminal desde cero. $171.62 / 10.4 horas /
  el contexto del hilo principal subió a 185.9K, entregó 12,212 líneas de código de producto, se cayó la red una vez y siguió hasta el final por su cuenta.
- **[HT002](cases/ht002.md)** — instalarlo y ponerlo en marcha en macOS. $38.24 / alrededor de 1 hora, la primera vez con guardián de objetivos;
  el programa arrancó de verdad, pero el veredicto fue **no alcanzable**, y salió a preguntar a una persona.

Las dos páginas escriben también lo que no se sostiene: en HT001 el agente se equivocó en un punto de su propia aceptación,
y HT002 convirtió `git clone && make && ./cppide` en una hora. Todos los números se pueden recalcular en `runs/manifest.json`
y `sessions.db`: es un registro, no propaganda.

## Por dónde empezar a leer {#从哪读起}

- **Si quieres ponerlo en marcha ya** — [Primeros pasos](getting-started/quickstart.md): tres comandos para arrancar,
  y luego te enseña a leer lo que pasa por la pantalla.
- **Si quieres entender los conceptos primero** — [Conceptos básicos](getting-started/concepts.md): ejecución, paso, sesión y los cinco roles,
  todo de una vez en cinco minutos.
- **Si quieres integrarlo en tu propio código** — [API de Python](reference/api.md): `Runtime`, `Step`, las cinco factorías de roles,
  y las firmas y valores por defecto de 62 símbolos públicos.
