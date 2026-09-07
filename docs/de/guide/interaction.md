# Interaktionsschicht austauschen

Der Kern von flower weiß nichts von einer UI. Alles, was in einem Lauf passiert – das Modell redet, ruft ein Tool, der Kontext läuft voll, es will jemanden fragen – wird auf eine einzige Datenstruktur flachgeklopft: [`Event`](../reference/glossary.md#事件).
**Die [Interaktionsschicht](../reference/glossary.md#交互层) kennt nur `Event` und importiert keinen einzigen SDK-Typ.**
Das ist die Grenze, an der man die UI austauscht, ohne den Kern anzufassen: Terminal, Web, HTTP-Dienst, vollautomatisch unbeaufsichtigt – ausgetauscht wird der Konsument der `Event`s, sonst keine Zeile.

## Welches Problem das löst

Der Nachrichtenstrom des SDK besteht aus **internen Typen**: `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`, `ResultMessage`, `SystemMessage` … Konsumiert eine UI die direkt, hat das zwei Folgen: Bei jedem SDK-Upgrade muss das Frontend nachziehen; und weil jede Nachrichtenform anders aussieht, schreibt jede UI die Entscheidung „ist das Fließtext oder ein Tool-Aufruf" neu.

`normalize(message)` verwandelt eine SDK-Nachricht in 0 bis N `Event`s
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
Der Preis ist eine Konvertierung, der Gewinn ist: keine Typabhängigkeit zwischen Interaktionsschicht und SDK.

Diese Grenze erledigt nebenbei vier weniger offensichtliche Dinge, alle vier stecken in `normalize()`:

1. **Äußerungen eines [subagent](../reference/glossary.md#subagent) werden markiert** (`payload["subagent"]`).
   Sonst mischen sich der delegierte [Task Brief](../reference/glossary.md#任务书) und die Zwischenäußerungen des subagent in den Fließtext des
   [Main Thread](../reference/glossary.md#主线程) und verseuchen über den [Workflow](../reference/glossary.md#流程)
   den Prompt des nächsten Schritts.
2. **Die synthetische Fehlermeldung beim Verbindungsabbruch wird nach `kind="error"` umgeleitet.** Bei einem Abbruch schreibt die SDK-Seite `API Error: …`
   als Assistant-Nachricht ins Transcript; das sieht aus wie eine Äußerung des Modells (`model` ist `"<synthetic>"`).
   Fängt man es hier nicht ab, landet es in `StepResult.text` und geht an den nächsten [Schritt](../reference/glossary.md#步骤).
3. **Compact-Grenzen werden explizit gemeldet** (`kind="reset"`). Hinter der Grenze „erinnert" sich das Modell nur noch an die Zusammenfassung, und der Prompt-Cache
   reißt genau hier ab – ein [long-horizon](../reference/glossary.md#长程) Lauf muss das sehen können.
4. **Der Kontextpegel kommt mit jeder Nachricht mit** (`payload["context"]` = `input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`). Er ist die einzige Quelle für das
   [Handoff](../reference/glossary.md#换代)-Kriterium.

## Wie man es benutzt (minimaler Code)

Eine Interaktionsschicht muss drei Dinge anschließen: **den Event-Ausgang** (wohin gerendert wird), **den Frage-Kanal** (wer antwortet) und **die Unterbrechung** (wie man Stopp ruft).
Der folgende Ausschnitt schließt alle drei an und läuft direkt:

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Event in deine eigene UI rendern — das Einzige, was ausgetauscht werden muss."""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ 换代/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ 重试: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # kind == "ask" und kein mail: übernimmt der answerer unten (Pull-Modus)


async def answerer(ch: HumanChannel) -> None:
    """Fragen im Pull-Modus abholen. Bei Web / HTTP ist diese Coroutine die zweite Stelle, die sich ändert."""
    while True:
        ask = await ch.next_ask()           # ohne timeout wird unbegrenzt gewartet
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # oder ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime benutzt die Workbench, die der Workflow selbst angelegt hat — keine zweite zusammenbauen
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        ctx = await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()                          # SQLite-Verbindung schließen
    print(rt.total_cost(), ctx.get("_failed_at"))


asyncio.run(main())
```

Zwei Aufräumschritte, die gern vergessen werden: `rt.close()` gehört unbedingt ins `finally`; und wenn `ctx["_failed_at"]` einen Wert hat, ist der Lauf unterwegs stehengeblieben
(`on_fail="stop"`) – das nicht als Erfolg werten.

!!! note "Es gibt genau eine Workbench, bau keine zweite"
    Die [Workbench](../reference/glossary.md#工作台) von `Runtime(workbench=True)` liegt unter
    `<run_dir>/workbench`, `Workbench(ws)` liegt per Default unter `<ws>/.flower` –
    das sind nicht dieselben Verzeichnisse. Baut das Treiberprogramm sich den Pfad zu `需求.md` selbst zusammen, entsteht
    „der Brief wird nach A geschrieben, der injizierte Index scannt B" – und zwar ohne Fehlermeldung.
    Entweder gibst du die vom Workflow angelegte Workbench an `Runtime` weiter (wie oben),
    oder du fragst über die reine Lesesonde `wake_state()` nach, wo sie liegt.

### Drei Event-Ausgänge

```python
await rt.run(spec, "…", on_event=sink)                  # 1. einzelner Agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. ganzer Workflow, an jeden Schritt weitergereicht
wf = Workflow(steps=[...], channel=ch)                  # 3. Frage-Kanal, an denselben Ausgang gehängt
```

Der dritte Anschluss passiert in `Workflow.run`: **automatisch nur dann, wenn `on_event` nicht `None` ist und `channel.on_event` noch
`None` ist.** Wer selbst angeschlossen hat, wird nicht überschrieben:

```python
ch = HumanChannel(on_event=my_own_sink)     # selbst angeschlossen, Workflow rührt es nicht an
```

`on_step(step, result)` ist ein zweiter Callback, einmal pro fertigem Schritt (**auch bei Fehlschlag**), und bekommt das vollständige
`StepResult`. Fortschrittsbalken, Persistenz, Alarme hängen hier – bau das nicht aus dem `Event`-Strom zusammen: Der Fließtext wird von Handoffs und
Retries in mehrere Stücke zerrissen.

### Terminal: das Mitgelieferte

Auch ohne eigenen Code gibt es eins. `flower "帮我做一个 X"` läuft über
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py);
das ist die **Referenzimplementierung der Interaktionsschicht, nicht Teil des Frameworks** und komplett austauschbar; die Schalter stehen in der [CLI-Referenz](../reference/cli.md).
Ehrlich zur Größenordnung: `cli.py` hat insgesamt 1264 Zeilen, 57KB – **auszutauschen ist aber nicht die ganze Datei**.
Der eigentliche Austauschpunkt ist die darin enthaltene `class Render` (`cli.py:382-578`, 197 Zeilen), deren Docstring genau das sagt:
„Event → Terminal. UI wechseln heißt: diese eine Klasse wechseln." Die übrigen tausend Zeilen sind Unterbrechung, Oracle, Inbox-Quittungen und
Signal-Rettung – **terminalspezifisches** Beiwerk, das man bei Web oder HTTP ohnehin nicht übernimmt.

Die Aussage „rund 200 Zeilen, komplett ersetzbar" stimmt also – vorausgesetzt, sie meint `Render` und nicht `cli.py`.

Wer eine eigene Terminal-UI schreibt: der springende Punkt ist der Thread, der Standardeingabe liest.

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Liest dauerhaft stdin: gibt es eine offene Frage, ist die Zeile die Antwort, sonst geht sie in die Inbox. Gibt das Stopp-Flag zurück."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # Polling, nur so reagiert das Stopp-Flag
            line = sys.stdin.readline()
            if not line:                        # EOF
                return
            raw = line.strip()
            if not raw:
                continue
            pend = ch.pending()
            if pend:
                ch.answer(pend[0].id, raw)      # threadübergreifend sicher
            else:
                ch.send(raw)                    # in die Inbox, unterbricht laufende Arbeit nicht

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

Alle drei Punkte sind Lehrgeld:

- **Daemon-Thread benutzen, nicht `asyncio.to_thread(input, ...)`.** Ein blockierendes `input()` lässt sich nicht abbrechen, und
  `asyncio.run` joint vor dem Beenden die Threads des Default-Executors – Ergebnis: Die Arbeit ist fertig, aber man muss noch einmal Enter drücken, um rauszukommen.
- **Mit `select` pollen, nicht direkt `input()` in der Schleife.** Dasselbe Problem: Ein in `input()` blockierender Thread
  wacht durch `stop.set()` nie wieder auf.
- **Durchgehend lesen, nicht nur wenn eine Frage offen ist.** Liest man nur bei offener Frage, bleibt alles, was in den stundenlangen Arbeitsphasen getippt wurde, im Terminalpuffer liegen
  und wird bei der nächsten Frage als Antwort verschluckt – der Mensch hat die Frage noch nicht gesehen, da ist sie schon „beantwortet".

### Web: Queue + WebSocket

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # synchron, im Thread der Event-Loop, darf nicht blockieren
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # ein Frontend-Fehler darf keine drei Stunden Arbeit mitreißen
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # Request-Thread — ein anderer Thread, das ist der Normalfall
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` ist das rohe SDK-Objekt (bei `ask`-Events ein `Ask`), **nicht JSON-serialisierbar und nichts fürs Frontend** –
wer `raw` benutzt, bindet das Frontend wieder an SDK-Typen und hat sich die ganze Schicht gespart. `kind` / `text` / `tool` / `payload`
reichen aus.

### HTTP: Sequenznummer + Polling

Ohne dauerhafte Verbindung nummeriert man die Events und lässt den Client ziehen:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # nur das Neueste behalten, damit der Speicher nicht mit der Laufzeit wächst


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # was gerade auf eine Antwort wartet
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = diese Frage wartet nicht mehr
```

Zwei Grenzen muss man kennen: Ist `maxlen` voll, fällt das Älteste raus – kommt ein Client mit einem sehr alten `after` zurück, bekommt er nicht mehr alles; das Polling-Intervall muss
zu dieser Länge passen. Und **`timeout_s` braucht zwingend einen endlichen Wert** – wenn niemand pollt, endet eine Frage nicht von selbst,
und `timeout_s=None` hängt den ganzen Lauf für immer auf. Die voreingestellten `1800.0` Sekunden sind passend.

### Vollautomatisch unbeaufsichtigt: niemand da

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # Events werden komplett verworfen
```

Das Kommandozeilen-Äquivalent ist `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (negative Werte genauso) ist der Vollautomatik-Modus: Fragen kommen **nicht in die Warteschlange und lösen kein `asked`-Event aus**, sondern werden sofort als
`state="timeout"` abgerechnet, und das Tool liefert diesen festen Text zurück –

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

– und der Lauf geht ungestört weiter. Die Fragen und Antworten werden weiterhin an `HumanChannel(log_path=...)` angehängt (`starter_flow` hängt sie per Default an
`<工作台>/notes/问答记录.md`), sodass man hinterher sieht, was gefragt und was angenommen wurde.

Soll es gar nicht erst fragen: `max_asks=0`. Fragen werden dann direkt abgelehnt (`state="over_budget"`), ebenfalls ohne zu blockieren.
Achtung: Das ist **nicht** dasselbe wie „das Tool wegnehmen" – `allowed_tools` ist nicht exklusiv;
sobald der [Koordinator](../reference/glossary.md#协调者) einen `channel` bekommt, bekommt er `mcp__human__ask` und
`mcp__human__inbox` gemeinsam und kann beide aufrufen, ob sie in der Liste stehen oder nicht. Fragen aufhalten können nur Kontingent und Timeout.

!!! warning "Unbeaufsichtigt niemals eine Frage ewig warten lassen"
    `timeout_s=None` heißt „ewig warten". Wenn niemand zuschaut, hält eine einzige Frage einen Zehn-Stunden-Lauf an Ort und Stelle an –
    ohne Fehler, ohne Timeout, im Log nicht von normalem Betrieb zu unterscheiden. Unbeaufsichtigt gibt es nur zwei richtige Werte: `0` (sofort ins Leere)
    oder eine endliche Sekundenzahl.

## Was es tatsächlich tut

### Die Form von `Event`

```python
@dataclass
class Event:
    kind: EventKind                     # 15 Werte, siehe Tabelle unten
    text: str = ""
    tool: str = ""                      # nur bei tool_call gesetzt
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # rohes SDK-Objekt / Ask; wer es anfasst, ist wieder ans SDK gebunden
```

`str(ev)`: bei `tool_call` ist es `[Toolname] Zusammenfassung`, sonst `text`; ist `text` leer, dann `<kind>`.

### Die 15 `EventKind`s

| `kind` | Wer sendet | Wann es auftritt | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | Fließtext des Modells | Fließtext | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | Thinking-Block | Denkinhalt | wie oben |
| `prompt` | `normalize()` | **Eingabe**: dein Prompt, der an einen subagent delegierte Task Brief | Eingabetext | wie oben |
| `tool_call` | `normalize()` | Modell startet einen Tool-Aufruf | Zusammenfassung (`file_path` / `command` / `pattern`, auf 200 Zeichen gekürzt) | `id`, `input` + wie oben; `tool` ist der Toolname |
| `tool_result` | `normalize()` | Tool antwortet | erste 500 Zeichen (leer, wenn der Inhalt kein String ist) | `tool_use_id`, `is_error` + wie oben |
| `result` | `normalize()` | eine SDK-Query ist zu Ende | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | synthetische Nachricht bei Verbindungsabbruch | Fehlertext | `synthetic: True` |
| `reset` | `normalize()` | Compact-Grenze oder Session-Reset | `压缩(trigger) 167000 → 42000 tokens`; beim Session-Reset `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (beim Session-Reset leer) |
| `system` | `normalize()` | sonstige SDK-Systemnachrichten | subtype | `data` unverändert durchgereicht |
| `task` | `normalize()` | Task-Fortschrittsnachricht | Klassenname der Nachricht | — |
| `unknown` | `normalize()` | nicht erkannter Nachrichtentyp | Klassenname | — |
| `ask` | `HumanChannel` | jemand soll antworten, eine Frage hat ein Ergebnis, oder ein Mensch sagt von sich aus etwas | Frage / das Gesagte | zwei Rollen, siehe unten |
| `retry` | `Runtime` | Retry läuft / wartet auf Netz | ein erklärender Satz | `step`, `attempt` |
| `step` | `Workflow.run` | Schrittgrenze | Schrittname | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | Handoff: nähert sich / wird geschrieben / fertig | ein Satz mit Pegelstand | `phase`, `step`, `context`, `window` + siehe unten |

**Vier Kinds stammen nicht aus `normalize()`**: `ask` kommt von `HumanChannel`, `retry` und `handoff` von
`Runtime`, `step` von `Workflow.run`. Dass sie im selben `EventKind` stecken, ist Absicht –
**die UI kennt genau einen `Event`-Typ und braucht keinen Extraweg für „jemand soll antworten" oder „Schrittgrenze".**

Lass beim Schreiben der UI einen `else`-Zweig stehen. `EventKind` bekommt weitere Mitglieder, und eine alte UI soll daran nicht zerbrechen.

### Die drei Phasen von `handoff`

| `phase` | Wann gesendet | zusätzlich im `payload` |
|---|---|---|
| `near` | Pegel hat `warn_at` überschritten. **Pro Generation nur einmal**, kein Zuspammen | `at` (Handoff-Schwelle) |
| `writing` | das [Handoff-Dokument](../reference/glossary.md#交接书) wird geschrieben. Das dauert gut zehn Sekunden; ohne dieses Event sieht die Oberfläche aus, als hinge sie | — |
| `done` | Handoff geschrieben, neue Session gestartet | `degraded` (ob es die abgestufte Variante ist), `path` (wohin geschrieben, ohne Workbench ein leerer String), `sections` |

Zum Mechanismus selbst siehe [Handoff](handoff.md).

### Die zwei Rollen von `ask`

`Event("ask")` trägt gleichzeitig „eine Frage" und „etwas, das ein Mensch von sich aus gesagt hat"; **die UI muss zuerst `payload["kind"]` prüfen**:

| Rolle | Woran erkennbar | `payload` |
|---|---|---|
| eine Frage | kein Schlüssel `kind` | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`; `raw` ist das `Ask` |
| eine spontane Äußerung | `payload["kind"] == "mail"` | `kind`, `state` (`queued` = eingelegt / `delivered` = abgeholt), `id`, `amended` (an welche Datei angehängt, ohne Konfiguration ein leerer String). **Kein `options`, kein `remaining`** |

Eine Frage sendet **mindestens zwei** Events: eines beim Stellen (`state="asked"`) und eines beim Ergebnis
(`answered` / `timeout` / `declined` / `over_budget` / `invalid`). Die UI aktualisiert anhand von `payload["id"]` denselben Eintrag.

### Menschen fragen: `Ask` und `HumanChannel`

```python
@dataclass
class Ask:
    id: str                                             # "q1", "q2" …
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # die fünf Ergebnisse von oben
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # wie viele Sekunden gewartet, eine Nachkommastelle
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` ist ein prozessinterner MCP-Server plus eine Handvoll Methoden für die UI. Das Modell sieht nur zwei Tools:
`mcp__human__ask` (fragen, bleibt hängen und wartet) und `mcp__human__inbox` (Inbox prüfen, **blockiert nicht**, bei leerer Inbox kommt sofort
ein erklärender Satz zurück). Vollständiger Konstruktor:

```python
HumanChannel(
    *,                                  # alles keyword-only
    on_event=None,                      # Push-Ausgang. Workflow schließt nur an, wenn er None ist
    max_asks=None,                      # None = unbegrenzt; 0 = darf nicht fragen. Über Kontingent wird direkt abgelehnt, ohne zu blockieren
    timeout_s=1800.0,                   # None = ewig warten; <= 0 = sofort ins Leere
    log_path=None,                      # Fragen und Antworten werden an diese Datei angehängt, kosten keinen Kontext
    amend_path=None,                    # was ein Mensch während des Laufs sagt, wird an diese Datei angehängt, üblicherweise der Brief
    over_budget_text=OVER_BUDGET,       # drei feste Antworten, austauschbar
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` wird am häufigsten übersehen, und genau er entscheidet, ob eine unterwegs geänderte Anforderung die Schrittgrenze überlebt.
Jeder Schritt ist eine neue [Session](../reference/glossary.md#会话) mit eingefrorenen Nur-Lese-Artefakten: Was während des Laufs gesagt wird, landet nur im Kontext des
damals laufenden Agents; der nächste Schritt (etwa das [Verdict](../reference/glossary.md#判定)) ist eine brandneue Session, liest
`需求.md` und `目标.md` und **sieht deinen Satz nicht** – er urteilt also nach den alten Grenzen und erklärt das Korrigierte für außerhalb des Rahmens.
`amend_path` **hängt** jede Nachricht an den [Brief](../reference/glossary.md#需求确认书) an – anhängen statt überschreiben; die ursprüngliche Anforderung ist Historie, und zu sehen, was geändert wurde, ist besser als es nicht zu sehen. `starter_flow` hängt per Default an
`<工作台>/notes/需求.md`.

Im Test ($0.6767) wirkt das besser als erwartet: Ein Mensch sagt „bitte gleich noch die Gesamtzahl der Bytes berichten", der Koordinator sieht es beim Inbox-Check und meldet –
„hand hat es bereits aus der Ergänzung während des Laufs in `.flower/notes/需求.md` gelesen und mitgerechnet, es muss nicht noch einmal delegiert werden".
**Der subagent hat es aus der Datei gelesen, nicht über eine Weitererzählung.**

Öffentliche Mitglieder:

| Mitglied | Signatur | Bedeutung |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | direkt in `AgentSpec.mcp_servers` stecken. Der Schlüsselname muss zum Servernamen passen, deshalb wird er gleich mitgeliefert |
| `ask` | `async (question, options=None) -> Ask` | wartet auf einen Menschen. **Wirft außer `CancelledError` nie eine Exception** – keine Antwort ist auch eine Antwort, unterschieden über `ask.state` |
| `pending` | `() -> list[Ask]` | aktuell auf Antwort wartende Fragen |
| `next_ask` | `async (timeout=None) -> Ask \| None` | für Pull-UIs. Bei Timeout `None`, bei Cancel wird geworfen |
| `answer` | `(ask_id, text) -> bool` | antworten. `False` = diese Frage wartet nicht mehr (Timeout / bereits beantwortet) |
| `decline` | `(ask_id, reason="") -> bool` | überspringen; das Modell entscheidet selbst und schreibt seine Annahme in den Abschnitt 「未知与假设」 |
| `send` | `(text) -> Mail \| None` | ein Mensch sagt von sich aus etwas, geht in die Inbox. Unterbricht den Agent nicht; ruft intern automatisch `amend()` |
| `amend` | `(text, *, label="运行中补充") -> bool` | an `amend_path` anhängen. Gibt zurück, ob tatsächlich geschrieben wurde (kein Pfad konfiguriert / leerer Text / `OSError` ergeben `False`) |
| `pending_mail` | `() -> list[Mail]` | noch nicht abgeholte Äußerungen |
| `remaining` | `-> int` | wie oft noch gefragt werden darf. Bei `max_asks=None` kommt **`-1`** zurück, nicht 0 |
| `transcript` | `() -> str` | das Frage-Antwort-Protokoll als Markdown |
| `asks` / `mail` / `ui_errors` | `list` | alle Fragen / alle menschlichen Äußerungen / von UI-Callbacks geworfene Exceptions |

`answer`, `decline` und `send` **dürfen aus jedem Thread aufgerufen werden**. Der Request-Thread eines Web-Backends und der Eingabe-Thread eines TUI laufen in
anderen Threads – das ist der Normalfall, kein Randfall. Intern geht es über `loop.call_soon_threadsafe`, weil
`asyncio.Future.set_result` nicht threadsicher ist.

Push und Pull: **eins von beiden wählen**:

| | Wie geholt wird | Passt zu |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, bei `kind == "ask"` und `payload["state"] == "asked"` | eventgetriebene UIs (Web-Push, TUI-Neuzeichnen) |
| **Pull** | `await channel.next_ask()` | ein eigenständiger Eingabe-Task |

Die drei „0 / None" bedeuten jeweils etwas anderes; wer sie verwechselt, hängt unbeaufsichtigt fest oder bekommt keine einzige Frage:

| Schreibweise | Bedeutung |
|---|---|
| `max_asks=None` | unbegrenzt viele Fragen (Default) |
| `max_asks=0` | Fragen verboten, wird direkt abgelehnt |
| `timeout_s=None` | ewig warten |
| `timeout_s<=0` | nicht warten, Frage läuft sofort ins Leere |
| `remaining` gibt `-1` zurück | der Wert bei `max_asks=None`, nicht 0 |

### Unterbrechen: jeder Thread darf Stopp rufen

`rt.interrupt("别改 Makefile,那两行直接改")`, ein leerer String unterbricht nur, ohne etwas zu sagen. Drei Eigenschaften:

- **Es läuft dieselbe Session weiter** (`resume`), kein Neustart von vorn – die bereits erledigte Arbeit und der Kontext bleiben. Wiederverwendet wird der vorhandene Weg für Retries bei Netzabbruch;
  ersetzt wird nur der „Fehlergrund" durch „ein Mensch hat unterbrochen" und der `resume_prompt` durch das Gesagte.
- **Es verbraucht kein `max_attempts`.** Das Kontingent ist für Störungen da, nicht für Menschen.
- **Es ist kooperativ**: Abbruch an einer Nachrichtengrenze, kein hartes Cancel des Tasks. Der Preis ist die Verzögerung bis zur nächsten Nachricht (läuft gerade ein subagent, muss man auf ihn warten),
  der Gewinn ist, dass der Zustand nicht mittendrin zerrissen wird.

Der Preis ehrlich benannt: Eine Unterbrechung lässt einen **laufenden subagent seine halbfertige Arbeit verlieren** (im HT001-Netzabbruch gemessen, siehe
[issue #2](https://github.com/ChenyuHeee/flower/issues/2)). Die Terminal-Referenzimplementierung schreibt das in den Hinweis,
damit man es weiß, bevor man drückt; wer selbst eine UI schreibt, sollte es genauso machen.

Wenn du nicht unterbrechen, sondern nur etwas ergänzen willst, nimm die Inbox (`ch.send(...)`) – sie unterbricht nichts, die Verzögerung ist der
nächste Checkpoint des Agents.

### Oracle: kurz nachfragen, ohne den Lauf zu stören

Wer wissen will, „wo stehen wir gerade", muss nicht unterbrechen und sollte nicht den Koordinator fragen: Dieser Dialog **belegt dauerhaft Kontext im Main Thread**
(dort stehen Entscheidungen, kein Frage-Antwort-Protokoll), und der Koordinator muss dafür seine Arbeit unterbrechen. Bei einem Zehn-Stunden-Lauf zahlt man mit drei beiläufigen Fragen
beide Kosten.

Das [Oracle](../reference/glossary.md#旁路顾问) ist ein reiner Lese-Nebenweg. Seine Tools sind nur `Read` / `Glob` /
`Grep`, die Workbench ist offen, und es hat per Default Bremsen: `max_turns=12`, `max_budget_usd=0.5`. Im Terminal löst eine mit `?` beginnende Zeile es aus,
und es antwortet aus zwei Quellen: dem jüngsten Event-Fenster (fest 60 Einträge) und dem Brief, den Zielen, den Notizen und den Artefakten in der Workbench.
Es benutzt eine eigene `Runtime` (`<run_dir>/aside`), sodass Kosten und Session-[Lineage](../reference/glossary.md#血缘)
**nicht ins Haupt-Manifest wandern** – dieses Manifest hält fest, „welche Schritte dieser Lauf gemacht hat", und eine Zwischenfrage ist kein Schritt.

Gemessen: zwei Fragen für zusammen $0.5190, und das Manifest des Hauptlaufs ist um kein einziges Byte gewachsen.

### Zwei harte Regeln

!!! warning "on_event darf weder blockieren noch Exceptions herauslassen"
    **Erstens: `on_event` ist eine synchrone Funktion und wird im Thread der Event-Loop aufgerufen.** Deshalb ist
    `asyncio.Queue.put_nowait()` sicher, `await` nicht (es ist keine Coroutine), und **wer sie blockiert, blockiert den gesamten Lauf**.
    Langsames gehört in eine Queue und wird von einem anderen Task erledigt.

    **Zweitens: Eine Exception in `on_event` beschädigt den Lauf selbst.** Fließtext-Events werden im `try`-Block von `Runtime._attempt`
    gesendet, eine Exception wird als `result.error` festgehalten – dieser Schritt gilt dann als fehlgeschlagen; `retry`-Events werden außerhalb davon gesendet, die Exception
    steigt direkt aus `Runtime.run` auf. Ein Frontend darf keine drei Stunden Arbeit mitreißen – **pack selbst ein try darum**.

    Ausnahme: Die von `HumanChannel` selbst gesendeten `ask`-Events sind bereits gekapselt; Exceptions landen in `channel.ui_errors`
    und unterbrechen den Lauf nicht.

## Wann man es nicht benutzen sollte

### Was in der Interaktionsschicht nichts zu suchen hat

| Nicht tun | Warum | Stattdessen |
|---|---|---|
| `from claude_agent_sdk import ...` | sobald die Interaktionsschicht von SDK-Typen abhängt, muss das Frontend bei jedem SDK-Upgrade nachziehen – die Schicht ist umsonst | nur `kind` / `text` / `tool` / `payload` des `Event` benutzen |
| `ev.raw` lesen | wie oben, und es ist nicht JSON-serialisierbar | fehlende Details ins `payload` von `normalize()` nachtragen, nicht die Grenze umgehen |
| in `on_event` `await`, Netzwerk-Requests, langsam auf Platte schreiben | sie ist synchron und wird im Event-Loop-Thread aufgerufen; sie zu blockieren blockiert den gesamten Lauf | `put_nowait()` in eine Queue, ein eigener Task konsumiert |
| `on_event` Exceptions herauslassen | Exceptions bei Fließtext-Events werden zu `result.error`, der Schritt gilt als fehlgeschlagen | den ganzen Callback-Körper in `try` packen |
| Fragen über `disallowed_tools` abschalten | das gilt **session-weit** und sperrt gleichnamige Tools der subagents mit (gemessener Fehlertext: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` oder `timeout_s=0` |
| `mcp__human__ask` aus `allowed_tools` streichen und das für ein Frageverbot halten | `allowed_tools` ist nicht exklusiv, es ist eine Freigabeliste, keine Whitelist; mit angehängtem `channel` kommen beide Tools mit | wie oben |
| sich den Pfad zu `需求.md` / `目标.md` selbst zusammenbauen | es gibt zwei mögliche Workbench-Orte; ein falscher Pfad wirft keinen Fehler, sondern versagt still | `wake_state()` oder `wf.workbench` |
| Fortschritt und Ergebnis aus dem `Event`-Strom zusammensetzen | der Fließtext wird von Handoffs und Retries in mehrere Stücke zerrissen | über `on_step(step, result)` das vollständige `StepResult` nehmen |
| unbeaufsichtigt `timeout_s=None` benutzen | niemand antwortet, der Lauf hängt für immer, ohne Fehler und ohne Timeout | `0` oder eine endliche Sekundenzahl |

### Wann sich der Austausch gar nicht lohnt

- **Nur Farben ändern, eine Zeile mehr oder weniger ausgeben** – dann reicht die Renderfunktion. Unterbrechung, Oracle,
  Inbox-Quittungen, SIGHUP-/SIGTERM-Rettung und das Abwarten des Nebenwegs vor dem Beenden aus der Terminal-Referenzimplementierung noch einmal zu schreiben, ist nicht billig.
- **Nur einen Schritt laufen lassen, ohne Interaktion** – nimm `flower once`. Es geht nicht über den interaktiven Treiberweg und hat von vornherein keine Ctrl+C-Unterbrechung,
  keinen stdin-Antwort-Thread, kein Oracle und keine Signal-Rettung.
- **Eigentlich willst du den Workflow ändern, nicht die UI** – siehe [Workflow entwerfen](workflow.md). Die Interaktionsschicht bestimmt nur, wer zusieht und wer antwortet;
  wie viele Schritte laufen, wie geurteilt wird und wann vorzeitig abgebrochen wird, bestimmt `Workflow`.
- **Eigentlich willst du Session-Store, Modell oder Budget wechseln** – keines der drei liegt an dieser Grenze, siehe
  [Python-API-Referenz](../reference/api.md).
