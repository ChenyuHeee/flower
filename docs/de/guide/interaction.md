# Interaktionsschicht austauschen

Der Kern von flower weiß nichts von einer UI. Jedes Ereignis in einem Run – das Modell spricht, es ruft ein Tool auf, der Kontext läuft voll, es will einen Menschen fragen – wird auf dieselbe Datenstruktur flachgedrückt: [`Event`](../reference/glossary.md#事件).
**Die [Interaktionsschicht](../reference/glossary.md#交互层) kennt nur `Event` und importiert keinen einzigen SDK-Typ.**
Das ist die Grenze, an der man die UI austauscht, ohne den Kern anzufassen: Terminal, Web, HTTP-Dienst, vollautomatisch ohne Aufsicht – ausgetauscht wird der Konsument der `Event`s, sonst keine Zeile.

## Welches Problem das löst {#解决什么问题}

Der Message-Stream des SDK besteht aus **internen Typen**: `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`, `ResultMessage`, `SystemMessage` … Werden sie direkt in der UI konsumiert, hat das zwei Folgen: Jedes SDK-Upgrade zwingt das Frontend zur Anpassung; und weil jede Nachrichtenform anders aussieht, muss jede UI die Unterscheidung „ist das Fließtext oder ein Tool-Aufruf" neu schreiben.

`normalize(message)` wandelt eine SDK-Nachricht in 0 bis N `Event`s um
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
Der Preis ist eine Umwandlung, der Gewinn ist: keine Typabhängigkeit mehr zwischen Interaktionsschicht und SDK.

Diese Grenze erledigt nebenbei vier weniger offensichtliche Dinge, alle vier in `normalize()`:

1. **Äußerungen von [subagents](../reference/glossary.md#subagent) werden markiert** (`payload["subagent"]`).
   Sonst mischen sich der delegierte [Task-Brief](../reference/glossary.md#任务书) und die Zwischenäußerungen des subagents in den Fließtext des [Main Threads](../reference/glossary.md#主线程) und verschmutzen über den [Workflow](../reference/glossary.md#流程) den Prompt des nächsten Schritts.
2. **Synthetische Fehlermeldungen bei Verbindungsabbruch werden nach `kind="error"` abgezweigt.** Bei einem Abbruch schreibt die SDK-Seite `API Error: …` als Assistant-Nachricht ins Transcript; das sieht aus wie eine Äußerung des Modells (`model` ist `"<synthetic>"`). Fängt man das hier nicht ab, landet es in `StepResult.text` und wird an den nächsten [Schritt](../reference/glossary.md#步骤) weitergereicht.
3. **Compact-Grenzen werden explizit gemeldet** (`kind="reset"`). Hinter der Grenze „erinnert" sich das Modell nur noch an die Zusammenfassung, und der Prompt-Cache reißt hier ab – ein [Long-Horizon](../reference/glossary.md#长程)-Run muss das sehen können.
4. **Der Kontextpegel kommt mit jeder Nachricht mit** (`payload["context"]` = `input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens`). Er ist die einzige Quelle für das [Handoff](../reference/glossary.md#换代)-Kriterium.

## Wie man es benutzt (Minimalcode) {#怎么用最小代码}

Eine Interaktionsschicht muss drei Dinge anschließen: **Event-Ausgang** (wohin gerendert wird), **Frage-Kanal** (wer antwortet) und **Unterbrechung** (wie man Stopp ruft). Der folgende Ausschnitt schließt alles an und läuft direkt:

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
    # Runtime nutzt die Workbench, die der Workflow selbst angelegt hat — keine zweite zusammenbauen
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

Zwei Aufräumschritte, die leicht vergessen werden: `rt.close()` gehört unbedingt in `finally`; hat `ctx["_failed_at"]` einen Wert, wurde unterwegs abgebrochen (`on_fail="stop"`) – nicht als Erfolg verbuchen.

!!! note "Es gibt nur eine Workbench — bau dir keine zweite zusammen"
    Die von `Runtime(workbench=True)` angelegte [Workbench](../reference/glossary.md#工作台) liegt unter `<run_dir>/workbench`, `Workbench(ws)` liegt standardmäßig unter `<ws>/.flower` — das sind nicht dieselben Verzeichnisse. Baut sich das Treiberprogramm den Pfad zu `需求.md` selbst zusammen, passiert es, dass „der Brief nach Verzeichnis A geschrieben wird, der injizierte Index aber Verzeichnis B scannt" — ohne jede Fehlermeldung.
    Entweder gibst du die vom Workflow angelegte Workbench an `Runtime` weiter (wie oben), oder du fragst mit der reinen Lesesonde `wake_state()` nach, wo sie liegt.

### Drei Event-Ausgänge {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. einzelner Agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. ganzer Workflow, an jeden Schritt weitergereicht
wf = Workflow(steps=[...], channel=ch)                  # 3. Frage-Kanal, an denselben Ausgang
```

Der dritte Anschluss passiert in `Workflow.run`: **automatisch nur dann, wenn `on_event` nicht `None` ist und `channel.on_event` noch `None` ist**. Ein selbst gesetzter Ausgang wird nicht überschrieben:

```python
ch = HumanChannel(on_event=my_own_sink)     # selbst angeschlossen, Workflow fasst es nicht an
```

`on_step(step, result)` ist ein zweiter Callback; er wird nach jedem Schritt genau einmal aufgerufen (**auch bei Fehlschlag**) und bekommt das vollständige `StepResult`. Fortschrittsanzeige, Persistenz, Alarmierung hängen hier – nicht dafür den `Event`-Strom zusammenstückeln: Der Fließtext wird von Handoffs und Retries in mehrere Stücke zerhackt.

### Terminal: die Standardvariante {#终端默认的那个}

Eine gibt es auch ohne eigenen Code. `flower "帮我做一个 X"` läuft über
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py);
das ist die **Referenzimplementierung der Interaktionsschicht, nicht Teil des Frameworks** und kann komplett ersetzt werden; die Schalter stehen in der [CLI-Referenz](../reference/cli.md).
Zur Größenordnung, ehrlich: Die gesamte `cli.py` hat 1264 Zeilen, 57KB — aber **auszutauschen ist nicht die ganze Datei**.
Der eigentliche Austauschpunkt ist die darin enthaltene `class Render` (`cli.py:489-687`, 197 Zeilen), deren Docstring genau das sagt: „Event → Terminal. UI austauschen heißt, diese eine Klasse austauschen." Die übrigen tausend Zeilen sind Unterbrechung, Oracle, Inbox-Quittungen, Signal-Rettung – lauter **terminalspezifisches** Beiwerk, das man bei Web oder HTTP ohnehin nicht übernehmen will.

Die Aussage „rund 200 Zeilen, komplett austauschbar" stimmt also — vorausgesetzt, sie meint `Render` und nicht `cli.py`.

Schreibst du deine eigene Terminal-UI, liegt der Kern im Thread, der stdin liest:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Dauerhaft stdin lesen: gibt es eine offene Frage, ist es die Antwort, sonst ab in die Inbox. Gibt das Stop-Flag zurück."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # Polling — nur so reagiert der Thread auf das Stop-Flag
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
                ch.send(raw)                    # ab in die Inbox, unterbricht laufende Arbeit nicht

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

Alle drei Punkte sind erlitten:

- **Daemon-Thread benutzen, nicht `asyncio.to_thread(input, ...)`.** Ein blockierendes `input()` lässt sich nicht abbrechen, und `asyncio.run` joint vor dem Beenden die Threads des Default-Executors – Ergebnis: Die Arbeit ist fertig, aber man muss noch einmal Enter drücken, damit das Programm endet.
- **Mit `select` pollen, nicht direkt `input()` in der Schleife.** Genauso wenig abbrechbar: Ein Thread, der in `input()` hängt, wacht von `stop.set()` nie wieder auf.
- **Dauerhaft lesen, nicht nur wenn eine Frage offen ist.** Liest man nur bei offener Frage, bleibt alles, was in den Arbeitsstunden getippt wurde, im Terminalpuffer liegen und wird bei der nächsten Frage als Antwort verschluckt – der Mensch hat die Frage noch nicht gesehen, da ist sie schon „beantwortet".

### Web: Queue + WebSocket {#web队列--websocket}

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

`ev.raw` ist das rohe SDK-Objekt (bei `ask`-Events ein `Ask`), **nicht JSON-serialisierbar und nichts fürs Frontend** — wer `raw` benutzt, bindet das Frontend wieder an SDK-Typen und hat sich diese Schicht gespart. Die vier Felder `kind` / `text` / `tool` / `payload` reichen.

### HTTP: Sequenznummern + Polling {#http序号--轮询}

Ohne dauerhafte Verbindung nummeriert man die Events und lässt den Client ziehen:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # nur die jüngsten behalten, Speicher wächst nicht mit der Laufzeit


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

Zwei Grenzen muss man kennen: Ist `maxlen` voll, fallen die ältesten Einträge weg; kommt ein Client mit einem sehr alten `after` zurück, bekommt er nicht mehr alles – das Polling-Intervall muss zur Länge passen. Und: **`timeout_s` braucht zwingend einen endlichen Wert** — pollt niemand, endet eine Frage nie von selbst, und `timeout_s=None` hängt den gesamten Run für immer auf. Die voreingestellten `1800.0` Sekunden sind angemessen.

### Vollautomatisch ohne Aufsicht: kein Mensch da {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # alle Events werden verworfen
```

Auf der Kommandozeile entspricht das `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (negative Werte genauso) ist der Vollautomatikmodus: Eine Frage **kommt weder in die Warteschlange noch löst sie ein `asked`-Event aus**, sie wird sofort als `state="timeout"` abgerechnet, und das Tool gibt diesen festen Text zurück —

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

— und der Run läuft ungestört weiter. Frage und Antwort werden weiterhin an `HumanChannel(log_path=...)` angehängt (`starter_flow` verdrahtet standardmäßig `<工作台>/notes/问答记录.md`), man kann hinterher nachlesen, was gefragt und welche Annahme getroffen wurde.

Soll es gar nicht erst den Mund aufmachen, nimm `max_asks=0`: Fragen werden direkt abgelehnt (`state="over_budget"`), ebenfalls ohne zu blockieren.
Achtung, das ist **nicht** dasselbe wie „das Tool wegnehmen" — `allowed_tools` ist nicht exklusiv; sobald der [Koordinator](../reference/glossary.md#协调者) einen `channel` hat, bekommt er `mcp__human__ask` und `mcp__human__inbox` gemeinsam, ob sie gelistet sind oder nicht. Fragen aufhalten können nur Kontingent und Timeout.

!!! warning "Ohne Aufsicht keine Frage ewig warten lassen"
    `timeout_s=None` heißt „ewig warten". Sieht niemand hin, kann eine einzige Frage einen zehnstündigen Run auf der Stelle anhalten – ohne Fehler, ohne Timeout, im Log nicht von normaler Arbeit zu unterscheiden. Ohne Aufsicht gibt es nur zwei richtige Werte: `0` (sofort ins Leere) oder eine endliche Sekundenzahl.

## Was es tatsächlich tut {#它实际做了什么}

### Die Form von `Event` {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15 Werte, siehe Tabelle unten
    text: str = ""
    tool: str = ""                      # nur bei tool_call gesetzt
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # rohes SDK-Objekt / Ask — wer es anfasst, bindet sich ans SDK
```

`str(ev)`: bei `tool_call` ist es `[工具名] 摘要`, sonst `text`; ist `text` leer, ist es `<kind>`.

### Die 15 `EventKind` {#15-个-eventkind}

| `kind` | Wer sendet | Wann | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | Fließtext des Modells | Fließtext | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | Thinking-Block | Denkinhalt | wie oben |
| `prompt` | `normalize()` | **Eingabe**: dein Prompt, der an einen subagent delegierte Task-Brief | Eingabetext | wie oben |
| `tool_call` | `normalize()` | Modell startet einen Tool-Aufruf | Zusammenfassung (`file_path` / `command` / `pattern`, auf 200 Zeichen gekürzt) | `id`, `input` + wie oben; `tool` ist der Tool-Name |
| `tool_result` | `normalize()` | Tool antwortet | erste 500 Zeichen (leer, wenn der Inhalt kein String ist) | `tool_use_id`, `is_error` + wie oben |
| `result` | `normalize()` | eine SDK-Query ist zu Ende | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | synthetische Nachricht bei Verbindungsabbruch | Fehlertext | `synthetic: True` |
| `reset` | `normalize()` | Compact-Grenze oder Session-Reset | `压缩(trigger) 167000 → 42000 tokens`; beim Session-Reset `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (beim Session-Reset leer) |
| `system` | `normalize()` | sonstige SDK-Systemnachrichten | subtype | `data` unverändert durchgereicht |
| `task` | `normalize()` | Task-Fortschrittsnachricht | **leer** | `kind` = Klassenname der SDK-Nachricht |
| `unknown` | `normalize()` | unerkannter Nachrichtentyp | Klassenname | — |

!!! note "`task` hat leeren Fließtext — nicht einfach ausgeben"
    `TaskProgressMessage` und Verwandte sind interne Nachrichtentypen des SDK. Früher gab `normalize()` den Klassennamen als Fließtext aus; auf dem Bildschirm ist das reines Rauschen, und zwischen dem Fließtext des Agents sieht es aus wie ein Fehler (in der Praxis genau so erlebt). Jetzt ist es ein Event **ohne Fließtext**, der Klassenname steht in `payload["kind"]` — ob es angezeigt wird, entscheidet die Interaktionsschicht selbst (`events.py`).
| `ask` | `HumanChannel` | jemand soll antworten, eine Frage hat ein Ergebnis, oder ein Mensch sagt von sich aus etwas | Frage / das Gesagte | zwei Rollen, siehe unten |
| `retry` | `Runtime` | Retry läuft / wartet auf das Netz | ein Satz Erklärung | `step`, `attempt` |
| `step` | `Workflow.run` | Schrittgrenze | Schrittname | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | Handoff: naht / wird geschrieben / fertig | ein Satz mit Pegelangabe | `phase`, `step`, `context`, `window` + siehe unten |

**Vier kinds entstehen nicht in `normalize()`**: `ask` kommt vom `HumanChannel`, `retry` und `handoff` von `Runtime`, `step` von `Workflow.run`. Dass sie im selben `EventKind` stecken, ist Absicht — **die UI kennt genau einen `Event`-Satz und braucht keinen zweiten Weg für „jemand soll antworten" oder „Schrittgrenze".**

Lass beim Schreiben der UI einen `else`-Zweig stehen. `EventKind` bekommt weitere Mitglieder, und eine alte UI soll daran nicht zerbrechen.

### Die drei Phasen von `handoff` {#handoff-的三个-phase}

| `phase` | Wann gesendet | zusätzlich im `payload` |
|---|---|---|
| `near` | Pegel hat `warn_at` überschritten. **Pro Generation genau einmal**, kein Fluten des Bildschirms | `at` (Handoff-Schwelle) |
| `writing` | Das [Handoff-Dokument](../reference/glossary.md#交接书) wird geschrieben. Das dauert gut zehn Sekunden; ohne dieses Event sieht die Oberfläche aus, als hinge sie | — |
| `done` | Übergabe geschrieben, neue Session gestartet | `degraded` (ob es die abgespeckte Version ist), `path` (wohin geschrieben, ohne Workbench ein leerer String), `sections` |

Zum Mechanismus selbst siehe [Handoff](handoff.md).

### Die zwei Rollen von `ask` {#ask-的两种身份}

`Event("ask")` transportiert sowohl „eine Frage" als auch „ein Mensch sagt von sich aus etwas", **die UI muss zuerst `payload["kind"]` prüfen**:

| Rolle | Woran erkennbar | `payload` |
|---|---|---|
| eine Frage | kein `kind`-Schlüssel | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`; `raw` ist das `Ask` |
| ein Mensch sagt etwas | `payload["kind"] == "mail"` | `kind`, `state` (`queued` eingestellt / `delivered` abgeholt), `id`, `amended` (an welche Datei angehängt, ohne Konfiguration ein leerer String). **Kein `options`, kein `remaining`** |

Eine Frage löst **mindestens zwei** Events aus: eines beim Stellen (`state="asked"`) und eines beim Ergebnis (`answered` / `timeout` / `declined` / `over_budget` / `invalid`). Die UI aktualisiert anhand von `payload["id"]` einfach denselben Eintrag.

### Menschen fragen: `Ask` und `HumanChannel` {#问人ask-与-humanchannel}

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

`HumanChannel` ist ein prozessinterner MCP-Server plus eine Handvoll Methoden für die UI. Das Modell sieht nur zwei Tools: `mcp__human__ask` (fragen, hängt und wartet) und `mcp__human__inbox` (Inbox prüfen, **blockiert nicht**, gibt bei leerer Inbox sofort einen Hinweis zurück). Vollständiger Konstruktor:

```python
HumanChannel(
    *,                                  # alles keyword-only
    on_event=None,                      # Push-Ausgang. Workflow schließt nur an, wenn er None ist
    max_asks=None,                      # None = unbegrenzt; 0 = kein Fragen erlaubt. Über Kontingent = direkt abgelehnt, ohne Blockieren
    timeout_s=1800.0,                   # None = ewig warten; <= 0 = sofort ins Leere
    log_path=None,                      # Fragen/Antworten werden an diese Datei angehängt, kostet keinen Kontext
    amend_path=None,                    # was ein Mensch während des Runs sagt, wird an diese Datei angehängt, üblicherweise der Brief
    over_budget_text=OVER_BUDGET,       # drei feste Antworten, ersetzbar
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` wird am leichtesten übersehen, und es entscheidet darüber, ob eine unterwegs geänderte Anforderung die Schrittgrenze überlebt.
Jeder Schritt ist eine neue [Session](../reference/glossary.md#会话) mit eingefrorenem Nur-Lese-Stand: Was unterwegs gesagt wird, landet nur im Kontext des damals laufenden Agents; der nächste Schritt (etwa das [Verdict](../reference/glossary.md#判定)) ist eine völlig neue Session, liest `需求.md` und `目标.md` und **sieht deinen Satz nicht** — und urteilt weiter nach der alten Grenze, erklärt also das Verbesserte für außerhalb des Rahmens.
`amend_path` **hängt** jede Nachricht an den [Brief](../reference/glossary.md#需求确认书) an — anhängen, nicht überschreiben; die ursprüngliche Anforderung ist Historie, und zu sehen, was geändert wurde, ist besser, als es nicht zu sehen. `starter_flow` verdrahtet standardmäßig `<工作台>/notes/需求.md`.

In der Praxis ($0.6767) wirkt das noch besser als erwartet: Ein Mensch sagt „meld bitte nebenbei die Gesamtbytezahl", der Koordinator sieht es in der Inbox und meldet — „hand hat das schon aus dem Laufzeit-Nachtrag in `.flower/notes/需求.md` gelesen und mitgerechnet, keine zweite Delegation nötig".
**Der subagent hat es aus der Datei gelesen, nicht über eine Weitergabe erfahren.**

Öffentliche Member:

| Member | Signatur | Bedeutung |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | direkt an `AgentSpec.mcp_servers` weiterreichen. Der Schlüsselname muss dem Server-Namen entsprechen, deshalb wird er gleich mitgeliefert |
| `ask` | `async (question, options=None) -> Ask` | hängt und wartet auf den Menschen. **Wirft außer `CancelledError` nie eine Exception** — keine Antwort ist auch eine Antwort, unterschieden über `ask.state` |
| `pending` | `() -> list[Ask]` | Fragen, die gerade auf Antwort warten |
| `next_ask` | `async (timeout=None) -> Ask \| None` | für Pull-UIs. Bei Timeout `None`, bei Abbruch wirft es |
| `answer` | `(ask_id, text) -> bool` | antworten. `False` = diese Frage wartet nicht mehr (Timeout / bereits beantwortet) |
| `decline` | `(ask_id, reason="") -> bool` | überspringen, das Modell soll selbst entscheiden und die Annahme in den Abschnitt 「未知与假设」 schreiben |
| `send` | `(text) -> Mail \| None` | ein Mensch sagt von sich aus etwas, geht in die Inbox. Unterbricht den Agent nicht; ruft intern automatisch `amend()` auf |
| `amend` | `(text, *, label="运行中补充") -> bool` | an `amend_path` anhängen. Rückgabe: ob wirklich geschrieben wurde (kein Pfad konfiguriert / leerer Text / `OSError` ergeben `False`) |
| `pending_mail` | `() -> list[Mail]` | noch nicht abgeholte Nachrichten |
| `remaining` | `-> int` | wie viele Fragen noch übrig sind. Bei `max_asks=None` kommt **`-1`** zurück, nicht 0 |
| `transcript` | `() -> str` | Markdown des Frage-Antwort-Protokolls |
| `asks` / `mail` / `ui_errors` | `list` | alle Fragen / alles vom Menschen Gesagte / Exceptions aus UI-Callbacks |

`answer`, `decline` und `send` **dürfen aus jedem Thread aufgerufen werden**. Der Request-Thread eines Web-Backends und der Eingabe-Thread einer TUI liegen in anderen Threads — das ist der Normalfall, kein Randfall. Intern läuft es über `loop.call_soon_threadsafe`, weil `asyncio.Future.set_result` nicht threadsicher ist.

Push und Pull sind **eine Entweder-oder-Wahl**:

| | Wie geholt wird | Passend für |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, reagiert auf `kind == "ask"` mit `payload["state"] == "asked"` | eventgetriebene UIs (Web-Push, TUI-Neuzeichnen) |
| **Pull** | `await channel.next_ask()` | ein eigenständiger Eingabe-Task |

Drei „0 / None"-Bedeutungen sind jeweils verschieden; verwechselt man sie, hängt der unbeaufsichtigte Run oder es wird kein einziges Mal gefragt:

| Schreibweise | Bedeutung |
|---|---|
| `max_asks=None` | unbegrenzt viele Fragen (Standard) |
| `max_asks=0` | Fragen nicht erlaubt, direkt abgelehnt |
| `timeout_s=None` | ewig warten |
| `timeout_s<=0` | nicht warten, Frage läuft sofort ins Leere |
| `remaining` liefert `-1` | der Wert bei `max_asks=None`, nicht 0 |

### Unterbrechung: Stopp rufen kann jeder Thread {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")`, ein leerer String unterbricht nur, ohne etwas zu sagen. Drei Eigenschaften:

- **Es läuft dieselbe Session weiter** (`resume`), kein Neustart von vorn – geleistete Arbeit und Kontext bleiben erhalten. Genutzt wird der bestehende Weg des Netzausfall-Retrys, nur mit „Mensch hat unterbrochen" statt einer Fehlerursache und dem Gesagten als `resume_prompt`.
- **Es verbraucht kein `max_attempts`.** Das ist das Kontingent für Störungen, nicht für Menschen.
- **Kooperativ**: Abbruch an der Nachrichtengrenze, kein hartes Canceln des Tasks. Der Preis ist die Verzögerung bis zur nächsten Nachricht (läuft gerade ein subagent, muss man auf dessen Rückkehr warten), der Gewinn ist ein Zustand, der nicht mittendrin zerreißt.

Der Preis ehrlich benannt: Eine Unterbrechung lässt einen **fliegenden subagent sein Halbfertiges verlieren** (bei dem HT001-Netzausfall in der Praxis gemessen, siehe [issue #2](https://github.com/ChenyuHeee/flower/issues/2)). Die Terminal-Referenzimplementierung schreibt das im Hinweis aus, damit man es vor dem Drücken weiß; wer eine eigene UI schreibt, sollte es genauso halten.

Wer nicht unterbrechen, sondern nur eine Anforderung nachreichen will, nimmt die Inbox (`ch.send(...)`) — sie unterbricht nichts, die Verzögerung ist der nächste Checkpoint des Agents.

### Oracle: eine Frage stellen, ohne den Run zu stören {#旁路顾问问一句而不打扰运行}

Wenn du wissen willst, „wo stehen wir gerade", musst du nicht unterbrechen – und den Koordinator solltest du nicht fragen: Dieser Wortwechsel **belegt dauerhaft Kontext im Main Thread** (dort gehören Entscheidungen hinein, kein Frage-Antwort-Protokoll), und er muss seine Arbeit dafür liegen lassen. Bei einem zehnstündigen Run zahlt man beide Kosten schon, wenn man nur mal eben drei Fragen stellt.

Das [Oracle](../reference/glossary.md#旁路顾问) ist ein reiner Lese-Nebenweg. Es hat nur `Read` / `Glob` / `Grep`, sieht die Workbench und hat standardmäßig Bremsen: `max_turns=12`, `max_budget_usd=0.5`. Im Terminal löst eine mit `?` beginnende Zeile es aus; es antwortet aus zwei Quellen: dem jüngsten Event-Fenster (fest 60 Einträge) sowie Brief, Ziel, Notizen und Artefakten in der Workbench. Es benutzt ein eigenes `Runtime` (`<run_dir>/aside`), deshalb landen Kosten und Session-[Lineage](../reference/glossary.md#血缘) **nicht im Haupt-Manifest** — dieses Manifest hält fest, welche Schritte dieser Run gemacht hat, und eine Zwischenfrage ist kein Schritt.

Gemessen: zwei Fragen zusammen $0.5190, das Manifest des Hauptlaufs ist um kein einziges Byte gewachsen.

### Zwei harte Regeln {#两条硬规矩}

!!! warning "on_event darf weder blockieren noch Exceptions herauslassen"
    **Erstens: `on_event` ist eine synchrone Funktion und wird im Thread der Event-Loop aufgerufen.** `asyncio.Queue.put_nowait()` ist also sicher, `await` nicht (es ist keine Coroutine), und **es zu blockieren blockiert den gesamten Run**. Langsames gehört in eine Queue, die ein anderer Task abarbeitet.

    **Zweitens: Eine Exception aus `on_event` schadet dem Run selbst.** Fließtext-Events werden im `try`-Block von `Runtime._attempt` gesendet, eine Exception wird als `result.error` verbucht — dieser Schritt gilt damit als gescheitert; `retry`-Events werden außerhalb davon gesendet, eine Exception blubbert direkt aus `Runtime.run` heraus. Das Frontend darf keine drei Stunden Arbeit mitreißen, also **selbst ein try darum legen**.

    Ausnahme: Die vom `HumanChannel` selbst gesendeten `ask`-Events sind bereits umschlossen, Exceptions landen in `channel.ui_errors` und brechen den Run nicht ab.

## Wann man es nicht benutzen sollte {#什么时候不该用它}

### Was in der Interaktionsschicht nichts zu suchen hat {#交互层里不该做的事}

| Nicht tun | Warum | Stattdessen |
|---|---|---|
| `from claude_agent_sdk import ...` | Sobald die Interaktionsschicht von SDK-Typen abhängt, muss das Frontend bei jedem SDK-Upgrade nachziehen — die Schicht war umsonst | nur `kind` / `text` / `tool` / `payload` des `Event` benutzen |
| `ev.raw` lesen | wie oben, und außerdem nicht JSON-serialisierbar | fehlende Details in das `payload` von `normalize()` nachtragen, nicht die Grenze umgehen |
| in `on_event` `await`en, Netzwerkanfragen senden, langsam auf Platte schreiben | es ist synchron und wird im Event-Loop-Thread aufgerufen; es zu blockieren blockiert den gesamten Run | `put_nowait()` in eine Queue, ein eigener Task konsumiert |
| `on_event` Exceptions herauslassen | eine Exception bei Fließtext-Events wird zu `result.error`, der Schritt gilt als gescheitert | den ganzen Callback-Körper in `try` einpacken |
| Fragen über `disallowed_tools` abschalten | das gilt **sessionweit** und sperrt gleichnamige Tools auch in subagents (gemessener Fehlertext: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` oder `timeout_s=0` |
| `mcp__human__ask` aus `allowed_tools` entfernen und das für ein Frageverbot halten | `allowed_tools` ist nicht exklusiv, es ist eine Freigabeliste, keine Whitelist; mit `channel` gibt es beide Tools zusammen | wie oben |
| sich den Pfad zu `需求.md` / `目标.md` selbst zusammenbauen | es gibt zwei mögliche Workbench-Orte; ein falscher Pfad wirft keinen Fehler, er wirkt nur still nicht | `wake_state()` oder `wf.workbench` |
| Fortschritt und Ergebnis aus dem `Event`-Strom zusammensetzen | der Fließtext wird von Handoffs und Retries in mehrere Stücke zerhackt | `on_step(step, result)` liefert das vollständige `StepResult` |
| unbeaufsichtigt `timeout_s=None` benutzen | niemand antwortet, der Run hängt für immer, ohne Fehler und ohne Timeout | `0` oder eine endliche Sekundenzahl |

### Wann sich ein Austausch gar nicht lohnt {#什么时候根本不用换}

- **Du willst nur Farben ändern oder eine Zeile mehr bzw. weniger ausgeben** — dann reicht die Render-Funktion. Unterbrechung, Oracle, Inbox-Quittungen, SIGHUP-/SIGTERM-Rettung und das Abwarten des Nebenwegs vor dem Beenden aus der Terminal-Referenzimplementierung noch einmal zu schreiben, kostet einiges.
- **Du willst nur einen Schritt laufen lassen, ohne Interaktion** — nimm `flower once`. Es geht nicht über den interaktiven Treiber und hat von vornherein kein Ctrl+C-Unterbrechen, keinen stdin-Antwort-Thread, kein Oracle und keine Signal-Rettung.
- **Was du eigentlich austauschen willst, ist der Workflow, nicht die UI** — siehe [Workflow entwerfen](workflow.md). Die Interaktionsschicht bestimmt nur, wer zusieht und wer antwortet; wie viele Schritte laufen, wie geurteilt wird und wann vorzeitig abgebrochen wird, bestimmt `Workflow`.
- **Was du austauschen willst, ist der Session Store, das Modell oder das Budget** — die drei liegen nicht an dieser Grenze, siehe [Python-API-Referenz](../reference/api.md).
