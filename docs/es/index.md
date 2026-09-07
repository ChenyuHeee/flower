# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Framework de agentes de largo horizonte, portable, construido sobre el Claude Agent SDK.</p>

<p class="fl-hero__sub">Sin sacrificar la capacidad de Claude Code, lo convierte en un agente especializado que puedes llevarte contigo, cuya interacción puedes personalizar y que puede correr durante días.
El agente del hilo principal solo toma decisiones; todo el trabajo manual se delega a subagents. Los requisitos se aclaran antes de empezar, y otro rol decide si está terminado o no.
Cambias de máquina y el comportamiento es idéntico: no lee la configuración de la máquina anfitriona y trae sus propias credenciales.</p>

[Inicio rápido](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>coste de una ejecución</span></div>
<div class="fl-stat"><b>10.4 horas</b><span>seguidas, con una caída de red que se reanudó sola</span></div>
<div class="fl-stat"><b>185.9K</b><span>pico de contexto en el hilo principal, sin un solo compact</span></div>
<div class="fl-stat"><b>94.8 %</b><span>de los caracteres de texto quedan en los subagents</span></div>
</div>

Los cuatro números salen de [HT001](cases/ht001.md): la ejecución en la que un agente escribió desde cero un IDE de terminal bajo flower.

## Instalación

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Busca automáticamente `uv` / `pipx` / `pip` e instala el comando `flower`. Basta con Python ≥ 3.10: no hace falta Node
ni la CLI de Claude Code. Al terminar, haz `cd` a cualquier directorio de proyecto y escribe `flower`: la primera vez te pedirá la API key
o la dirección del gateway; se configura una vez, se guarda en `~/.config/flower/.env` y vale en todas partes. Si ya tienes Claude Code instalado y configurado en la máquina,
toma prestado ese token directamente, sin preguntar nada. Los pasos completos y la resolución de problemas están en [Instalación](getting-started/install.md).

## Te protege de cuatro clases de fallo

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Clarificación previa](guide/clarify.md)

Miedo a que lo construido no sea lo que querías: antes de empezar hay un rol que solo pregunta, no toca nada, y pregunta hasta que todo queda claro; congela los requisitos en un documento
que cada paso posterior lee al arrancar.
</div>

<div class="fl-card" markdown>
### [Guardián de objetivo](guide/goal.md)

Miedo a que diga que ha terminado cuando no ha terminado: al final de cada ronda de trabajo otro rol emite un juicio independiente; si se ha cumplido, sigue adelante; si no, lo devuelve,
y si en este entorno no se puede verificar, se detiene y pregunta a una persona.
</div>

<div class="fl-card" markdown>
### [Continuidad](guide/continuity.md)

Miedo a que tras horas de ejecución se caiga y haya que empezar de cero: vuelve a escribir `flower` en el mismo directorio y retoma el progreso anterior; si el proceso muere por un kill o
la máquina se reinicia, igual. No tienes que recordar ningún id.
</div>

<div class="fl-card" markdown>
### [Relevo](guide/handoff.md)

Miedo a que, al llenarse el contexto, todo quede reducido a un resumen: la sesión actual escribe por sí misma un documento de relevo legible y editable por una persona, y una sesión nueva toma el mando,
sin necesidad de compact.
</div>

</div>

## Por qué es "de largo horizonte"

El [coordinador](reference/glossary.md#协调者) del hilo principal solo carga decisiones y no tiene acceso a `Write` ni a `Edit`:
escribir código, ejecutar tests y buscar información se delegan todos a [subagents](reference/glossary.md#subagent),
y el ensayo y error del subagent va a **otra** transcript, de la que el hilo principal solo recibe un informe de no más de 30 líneas.
En aquella ejecución de 10.4 horas de HT001, el **94.8 % de los caracteres de texto quedó en los subagents**:
de las 1,893 llamadas a herramientas de trabajo manual, solo 32 entraron en el campo de visión del coordinador.
Por eso el hilo principal llegó a 185.9K recién en la ronda 70 y no hubo ni un compact en toda la ejecución. Cómo se logra esta capa y cuáles son las otras tres,
en [Economía del contexto](guide/context.md).

## Se ha ejecutado de verdad

- **[HT001](cases/ht001.md)** — escribir un IDE de terminal desde cero. $171.62 / 10.4 horas /
  el contexto del hilo principal subió a 185.9K, entregó 12,212 líneas de código de producto, con una caída de red por medio de la que se recuperó y terminó solo.
- **[HT002](cases/ht002.md)** — instalarlo y ponerlo en marcha en macOS. $38.24 / alrededor de 1 hora, la primera vez con guardián de objetivo;
  el programa arrancó de verdad, y sin embargo el veredicto fue **no cumplido**, y lo elevó a una persona.

Ambas páginas describen también lo que no se sostiene: en HT001 el agente se equivocó en uno de los criterios de aceptación que él mismo se puso,
y HT002 convirtió `git clone && make && ./cppide` en una hora de trabajo. Cada número se puede recalcular en `runs/manifest.json`
y `sessions.db`: es el registro original, no propaganda.

## Por dónde empezar a leer

- **Quieres ejecutarlo ya** — [Inicio rápido](getting-started/quickstart.md): primero gasta unos céntimos en validar las credenciales,
  y luego completa un flujo de trabajo de tres pasos sin escribir código.
- **Quieres entender antes los conceptos** — [Conceptos centrales](getting-started/concepts.md): ejecución, paso, sesión y los cinco roles,
  todo explicado de una vez en cinco minutos.
- **Quieres integrarlo en tu propio código** — [API de Python](reference/api.md): `Runtime`, `Step`, las cinco factorías de roles,
  y las firmas y valores por defecto de los 62 símbolos públicos.
