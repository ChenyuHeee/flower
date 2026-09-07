# Workflows entwerfen

Das Framework kümmert sich nur um den Mechanismus: wie ein Schritt läuft, wie Sessions verkettet werden, was bei einem Fehler passiert, wie Kontext gespart wird.
**Den [Workflow](../reference/glossary.md#流程) schreibst du** — das Framework weiß nicht, an welchem Projekt du arbeitest oder welche Sprache du benutzt,
und es soll es auch nicht wissen. Diese Seite erklärt, wie man einen Workflow entwirft; die vollständigen Feldtabellen von
`Step` und `Workflow` stehen in der [Python-API](../reference/api.md).

## Welches Problem das löst

Ein [Long-Horizon](../reference/glossary.md#长程)-Run ist nichts, was sich in einem einzigen Prompt sagen ließe: erst die Anforderungen klären,
dann recherchieren, dann implementieren, dann prüfen — jeder Abschnitt hat seine eigene Rolle, seinen eigenen Kontext, seine eigenen Abnahmekriterien.
Schreibt man alles in einen einzigen Prompt, entscheidet das Modell selbst, welchen Abschnitt es überspringt; schreibt man es als Workflow, werden
**Reihenfolge, Abbruchbedingungen und Zustandsweitergabe zu Python-Code** — lesbar, testbar, und man kann nur den kaputten Schritt neu laufen lassen.

`Workflow` macht genau drei Dinge:

- eine Folge von [Schritten](../reference/glossary.md#步骤) der Reihe nach ausführen
- entscheiden, was jeder Schritt vom Vorherigen sieht (drei Arten der Session-Verkettung + ein `ctx`-Dictionary)
- entscheiden, wann wiederholt und wann vorzeitig abgebrochen wird

Es enthält keinerlei Domänenannahmen. Wo man schneidet, was jeder Schritt abnimmt, was bei Nichtbestehen passiert — genau diese vier Dinge sind „einen Workflow entwerfen".

## Verwendung (Minimalcode)

```python
# flows.py
from flower import AgentSpec, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


def main() -> Workflow:
    return Workflow([
        # Neue Session: bekommt nur das, was im Prompt übergeben wird
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Ebenfalls neue Session, das Ergebnis des Vorschritts wird in den Prompt injiziert (billig, verhindert Verschmutzung)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

Das Argument von `flower run` ist `Modul:Attribut` oder `Dateipfad:Attribut`. Ist das aufgelöste Objekt aufrufbar, wird es einmal aufgerufen;
das dabei entstehende `Workflow` wird dann ausgeführt. Am Ende druckt das Terminal die Gesamtkosten und den Pfad des Run-Manifests.

Ein eigenes Treiberprogramm geht auch; das erste Argument von `Workflow.run` ist ein `Runtime`:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## Was es tatsächlich tut

### Was ein Step bekommt und was er zurückgeben muss

`Step` ist keine Funktion, sondern eine **Deklaration**. Ausgeführt wird tatsächlich `Runtime.run(step.spec, gerenderter Prompt, ...)` —
**ein Schritt = ein `Runtime.run` = eine [Session](../reference/glossary.md#会话)**.

Die ersten drei Felder sind Positionsargumente, `Step(name, spec, prompt)`:

- `name` — der Schrittname. Er ist gleichzeitig der Schlüssel in `ctx`, der Zeilenname in `runs/manifest.json`
  und der Schlüssel der prozessübergreifenden [Lineage](../reference/glossary.md#血缘).
- `spec` — mit welchem `AgentSpec` gelaufen wird. Er bestimmt Tool-Whitelist, Modell und Budget dieses Schritts.
- `prompt` — ein `str` oder `(ctx) -> str`. Ist es aufrufbar, bekommt es das aktuelle `ctx`;
  **das ist der billigste Weg, das Ergebnis des Vorschritts einzuspeisen** (die andere Variante ist Session-Verkettung, siehe unten).

„Zurückgegeben" wird ein `StepResult`, aber im Workflow bekommst du zwei Dinge in die Hand:

- `ctx[step.name]` — standardmäßig `result.text`; ist `reduce` gesetzt, stattdessen dessen Rückgabewert;
- `ctx["_results"][step.name]` — das vollständige `StepResult` (Kosten, Turns, Anzahl Versuche, `session_id`).

`result.text` **sammelt nur den Fließtext des Main Threads** ein: Äußerungen eines Subagents stehen in dessen eigenem Transcript, der an ihn
vergebene [Task Brief](../reference/glossary.md#任务书) hat `kind="prompt"`, der synthetische Fehler bei Verbindungsabbruch hat `kind="error"`
— keines der drei geht ein.

### reduce: kein Zucker

Standardmäßig wird der Wortlaut des Modells weitergereicht. Bei manchen Schritten **darf** dieser Wortlaut nicht unverändert weitergereicht werden:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

Gemessen: der Clarify-Schritt **klebt neben den vier Abschnitten den gesamten Code** mit hinein. Nach unten weitergereicht werden dürfen nur die
geparsten vier Abschnitte, sonst landet dieser ganze Code im Prompt des nächsten Schritts. `clarify_step` fängt genau das über dieses Feld ab.

`reduce` **muss eine synchrone Funktion sein**; `gate` / `when` / `on_reject` dürfen async sein.

### Wie der Zustand durch ctx fließt

`ctx` ist ein `dict[str, Any]` — nämlich `Workflow.context` selbst. Nach jedem Schritt wird nach dieser Tabelle geschrieben:

| Fall | `ctx[Schrittname]` | Sonstiges |
|---|---|---|
| `when(ctx)` liefert False | **wird nicht geschrieben**, der ganze Schritt wird übersprungen | erzeugt kein Result, landet auch nicht in `_results` |
| Bestanden | `reduce(result, ctx)`, ohne Angabe `result.text` | |
| Fehlgeschlagen + `on_fail="stop"` (Default) | **wird nicht geschrieben** | schreibt `ctx["_failed_at"]`, der gesamte Workflow bleibt bei diesem Schritt stehen |
| Fehlgeschlagen + `on_fail="skip"` | **wird nicht geschrieben** | läuft weiter |
| Fehlgeschlagen + `on_fail="continue"` | `result.text` (unvollständig, **ohne `reduce`**) | läuft weiter |

Ob bestanden oder nicht: `ctx["_results"][Schrittname]` wird immer geschrieben; ist `result.session_id` nicht leer, wird zusätzlich
`ctx["_sessions"]` geschrieben und die Lineage vermerkt.

**Ob dieser Workflow erfolgreich war, entscheidest du an `ctx.get("_failed_at")`** — nicht daran, ob der letzte Schritt eine Ausgabe hatte.

Alle Schlüssel mit führendem Unterstrich setzt `Workflow.run` selbst: `_runtime`, `_on_event`, `_sessions`, `_results`,
`_lineage`, `_woke`, `_aborted`, `_failed_at` — benutze sie nicht als eigene Schrittnamen. Die einzelnen Mechanismen legen weitere eigene ab
(`_brief` / `_goal` / `_verdict` usw.), die vollständige Liste steht in der [Python-API](../reference/api.md).

Davon sind `_runtime` und `_on_event` für `gate` gedacht: ein Gate kann selbst einen Agent zur Beurteilung losschicken,
und dieser Vorgang wird trotzdem auf die UI gedruckt — sonst bleibt der Bildschirm zehn und mehr Sekunden schwarz und es sieht aus wie ein Hänger.
Der [Goal Guard](goal.md) ist genau so implementiert.

`ctx` ist dasselbe dict: **läuft dasselbe `Workflow`-Objekt ein zweites Mal, sind die Schlüssel vom letzten Mal noch da**.
Für einen sauberen Neustart legst du ein neues an oder übergibst explizit `context={}`.

!!! warning "Bei on_fail=skip wird `ctx[Schrittname]` nicht geschrieben"
    Schreibt ein späterer Schritt `lambda ctx: ctx["某步"]`, gibt es direkt einen `KeyError`. Willst du mit dem unvollständigen Ergebnis
    weiterlaufen, nimm `on_fail="continue"`; willst du wirklich überspringen, muss der spätere Schritt selbst mit `ctx.get(...)` absichern.

### Verdict und Zurückweisung: gate, on_reject, StepAbort

`gate(result, ctx) -> bool` beurteilt „ist durchgelaufen, aber taugt es was?". Zwei Details, die man kennen muss:

- **Ist `result.ok` falsch, wird `gate` gar nicht erst aufgerufen** (Kurzschluss).
- **Pro Versuch wird es genau einmal aufgerufen**, das Ergebnis wird für später aufbewahrt — es kann Nebenwirkungen haben. Das Gate von `clarify_step`
  schreibt den [Brief](../reference/glossary.md#需求确认书) auf Platte; ein wiederholter Aufruf würde wiederholt schreiben.

Wie nach einem nicht bestandenen Gate neu gestartet wird, hängt davon ab, ob `on_reject` gesetzt ist:

| | Wie die nächste Runde läuft | Name im Manifest |
|---|---|---|
| Nur `retries` | von vorn, mit ursprünglichem Prompt und ursprünglichem `resume_from` | `X#retry1` |
| Plus `on_reject` | **die gerade abgelehnte Session wird fortgesetzt**, der Prompt wird durch den Rückgabewert von `on_reject` ersetzt, `fork` wird auf False gezwungen | `X#round2` |

Die zweite Variante heißt „zurückgeben, sagen woran es hakt, nachbessern lassen" — die bereits geleistete Arbeit und der Kontext sind noch da.
Gibt `on_reject` einen leeren String zurück, oder hat dieser Versuch gar keine `session_id` erhalten, fällt es auf einen Neustart von vorn zurück.

`gate` darf außerdem `StepAbort` werfen, was bedeutet: **weitere Versuche bringen nichts, verbrauche die restlichen Runden nicht**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

Nach dem Wurf: der Grund wird in `ctx["_aborted"]` vermerkt, der Schritt gilt als fehlgeschlagen und geht durch `on_fail` (Default `"stop"`),
**die Retry-Schleife bricht auf der Stelle ab**, von den restlichen `retries` wird kein einziger verbraucht.

Den Unterschied gut merken: **False zurückgeben heißt „diesmal nicht, noch eine Runde"; `StepAbort` heißt „noch eine Runde bringt nichts".**
Der typische Fall ist ein Ziel, das in dieser Umgebung als nicht machbar beurteilt wurde und zu dem niemand befragt werden kann — weiter leerzulaufen ist dann die teuerste Option.

### Die zwei Retry-Ebenen nicht verwechseln

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| Zuständig für | fachliche Fehler: `gate` nicht bestanden, `result.ok` falsch | Infrastruktur: Netzwerkzucken, Verbindungsabbruch, 5xx |
| Wie neu gestartet wird | **der ganze Schritt von vorn**, mit demselben Prompt und demselben `resume_from` | **Resume ab der Unterbrechungsstelle**, die bisherigen Kosten sind nicht umsonst |
| Vorher | nichts | DNS- + TCP-Probe hängt und wartet, bis das Netz zurück ist (kein HTTP, keine Credentials, die Probe muss kostenlos sein) |
| Nicht wiederholbar | — | Credential-Fehler und Parameterfehler stoppen sofort, kein Warten bis zum Tod |

Der Prompt für das Fortsetzen **enthält absichtlich keinerlei Fehlerdetails** — das Modell muss wissen „du wurdest unterbrochen, mach weiter",
nicht ob es ENOTFOUND oder 503 war.

### Schritte verketten

Zustand zwischen Schritten weiterzugeben geht auf drei Arten; welche du wählst, bestimmt, was der nächste Schritt sieht:

| Schreibweise | Was der nächste Schritt sieht | Wofür |
|---|---|---|
| `resume_from=None` (Default) + Injektion in den Prompt | nur die von dir injizierten Zeichen | unabhängige Schritte. Billig, verhindert Verschmutzung |
| `resume_from="Name des Vorschritts"` | die vollständige Session-Historie | wenn zusammenhängendes Gedächtnis nötig ist |
| `resume_from="Name des Vorschritts"` + `fork=True` | vollständige Historie, aber auf einem eigenen Zweig | Prüfung / mehrere Varianten parallel / Retries, die die Originallinie nicht verschmutzen |

Der Schritt, auf den `resume_from` zeigt, **muss tatsächlich eine Session erzeugt haben**. Wurde er per `when` übersprungen oder lief er gar nicht,
wirft `Workflow.run` direkt einen `ValueError` — es fällt nicht stillschweigend auf eine neue Session zurück, denn das würde die Annahme
„zusammenhängendes Gedächtnis" heimlich außer Kraft setzen.

Ein paar Entwurfserfahrungen, die wir uns mehrfach eingehandelt haben:

1. **Ein Schritt, ein abnehmbares Ziel.** Die Schrittgrenze ist die Kontextgrenze: dort, wo `resume_from=None` steht,
   sind die vorherigen Tool-Ergebnisse endgültig nicht mehr dauerhaft präsent. Siehe [Kontextökonomie](context.md).
2. **Im Zweifel erst `clarify_step`.** Im Long-Horizon-Betrieb ist „das Ziel falsch verstanden" der teuerste Fehler,
   und ausgerechnet er gehört zu der Sorte, die die kontextsparenden Schichten nicht wegräumen können. Siehe [Clarify](clarify.md).
3. **Vergebene Aufgaben müssen selbsttragend sein.** Ein Subagent hat einen sauberen Kontext, er weiß nicht, was der
   [Koordinator](../reference/glossary.md#协调者) weiß. Nötiger Hintergrund gehört in den Task Brief, oder du sagst ihm, welches Artefakt er lesen soll.
4. **Lange Ausgaben gehen auf die Platte, nicht in die Antwort.** Das steht bereits in `WORKER_RULES`; deine `instructions` sollten es nicht
   wieder aufheben („kleb mir das komplette Log zurück").
5. **`gate` prüft bevorzugt harte Bedingungen.** Existiert die Datei, ist der Exit-Code 0 — was sich in einer Zeile Python entscheiden lässt,
   dafür schickst du kein Modell los. Soll das Modell entscheiden, nimm das fertige `with_goal` — es ersetzt das Gate durch eine Implementierung,
   die einen eigenständigen [Judge](../reference/glossary.md#判定者) laufen lässt; bastle das nicht selbst im Gate nach.
6. **Parallel am selben Repo arbeiten heißt `worker(isolate=True)`.** Der Abschluss (Merge, Worktree aufräumen, PR öffnen) bleibt derzeit
   deinem Workflow überlassen; die Harness garantiert nur, dass die Änderungen im jeweils eigenen Worktree landen.

### Die Workbench muss am Workflow hängen

Überall dort, wo der Workflow Dateien in die [Workbench](../reference/glossary.md#工作台) schreibt — typisch bei
`clarify_step(brief_path=...)` — musst du selbst eine `Workbench` anlegen und sie **sowohl** an `Workflow.workbench` hängen
**als auch** dem `Runtime` übergeben:

```python
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=1800.0)

主控 = coordinator("协调者", "", {
    "coder": worker("写代码与测试。要动手实现的活派给它。",
                    "你负责实现。每改一处就跑一次验证,别攒到最后。"),
}, channel=ch)

wf = Workflow(
    [
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
    ],
    channel=ch,
    workbench=wb,
)

rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
```

Dass `channel` am Workflow hängt, hat zwei Gründe: `run()` verdrahtet dessen `on_event` mit demselben Event-Ausgang
(nur solange `channel.on_event` noch `None` ist), und das Treiberprogramm erfährt über dieses Feld, wem es antworten soll.

!!! warning "Workbench-Pfade selbst zusammenbauen scheitert stillschweigend"
    Der Default-Ort von `Runtime(workbench=True)` ist `<run_dir>/workbench`, der von `Workbench(ws)` dagegen
    `<ws>/.flower` — **das sind nicht dieselben Verzeichnisse**. Wird der Workflow von der CLI aufgerufen, sieht er `run_dir` nicht; ein selbst
    zusammengebauter Pfad zeigt dann woandershin, der Brief landet in Verzeichnis A, der injizierte Index scannt Verzeichnis B —
    **und es gibt keinen Fehler**. Legst du ein Objekt an und benutzt es auf beiden Seiten, hast du das Problem nicht;
    existiert `Workflow.workbench`, wird das `-W` der Kommandozeile ignoriert und dieses Feld gilt.

### `continuous=True`: derselbe Pfad, noch einmal gelaufen

Die drei obigen Verkettungsarten betreffen Schritte **innerhalb eines Runs**. Prozessübergreifend ist eine andere Achse:

```python
Workflow([...], continuous=True)     # Default
```

Läuft derselbe Workspace ein zweites Mal, spricht jeder Schritt in der Session vom letzten Mal weiter — über die Zuordnung
„Schrittname → session_id" in `<run_dir>/lineage.json`. Beim Laden muss jeder Eintrag durch `runtime.has_session()` prüfen,
ob die Session noch in der Datenbank ist, und nur eine lebende wird benutzt: die Lineage-Datei kann `sessions.db` überleben, und ein Resume auf eine
nicht existierende Session fliegt einem erst um die Ohren, wenn der Subprozess hochgefahren ist.

Drei Konsequenzen:

- **`resume_from=None` heißt nicht „brandneue Session".** Beim ersten Lauf ja, beim zweiten nicht. Soll es jedes Mal eine neue Session sein,
  schreib explizit `Workflow(..., continuous=False)`.
- **Bei [Continuity](../reference/glossary.md#接续) wächst der Kontext stetig.** Willst du beim Fortsetzen etwas anderes sagen, nimm
  `Step.resume_prompt` — was im Kontext der Gegenseite schon steht, soll nicht erneut geschickt werden.
- Schritte mit explizitem `resume_from` sind davon nicht betroffen, es hat Vorrang.

!!! warning "Der Schrittname ist der prozessübergreifende Schlüssel"
    Einen Schrittnamen zu ändern heißt, die Lineage dieses Schritts zu kappen: beim nächsten Lauf wird nicht mehr fortgesetzt, und
    **es gibt keinen Fehler**. Retry-Namen mit den Suffixen `#retry1` / `#round2` **gehen nicht in die Lineage** (vermerkt wird immer der
    Originalname); auch das ist eine der Implementierungen von „der Judge ist immer eine neue Session".

Vollständiger Entwurf und `--new` unter [Continuity](continuity.md).

## Wann man es nicht verwenden sollte

- **Nur ein Agent, kein Verdict nötig** — dann kein `Workflow` drumherum. Direkt `await rt.run(spec, "…")`,
  oder auf der Kommandozeile `flower once "读一眼这个仓库"`.
- **Die Form ist genau „Anforderungen klären → Ziel setzen → arbeiten"** — nimm das fertige
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py),
  statt es selbst zu schreiben:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    Es hat **drei Schritte**: `确认需求` → `设定目标` → `干活` (mit Verdict-Schleife, der Verdict-Schritt heißt `干活·判定#N`).
    Bei `goal=False` entfallen der zweite Schritt und die Verdict-Schleife, bei `clarify_only=True` bleibt nur der erste Schritt.
    Es bringt `HumanChannel` und `Workbench` mit und hängt beide an den Workflow, also nimm
    `Runtime(workbench=wf.workbench)` direkt so — bau keine zweite zusammen.

    Ohne Code geht es auch: im Projektverzeichnis `flower "帮我做一个 X"` startet genau das.
    **Es ist kein „empfohlener Workflow-Entwurf"**, es sorgt nur dafür, dass du ohne Konfiguration loslaufen kannst.

- **Schritte feiner geschnitten als „ein abnehmbares Ziel"** — reiner Verlust. Jeder Schritt startet eine neue Session,
  und eine neue Session hat einen Startboden (beim Koordinator gemessen ca. 34k Kontext), der sich nicht dünner verteilen lässt.
- **Nachträglich auf eine bestimmte Nachricht zurückrollen** — über `Workflow` geht das nicht, es übergibt niemals `resume_at`.
  Ruf direkt `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)` auf.

Wie man Rollen wählt (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) und die feldweise Semantik von `Step` und `Workflow`
steht in der [Python-API](../reference/api.md); die Begriffe im [Glossar](../reference/glossary.md).
