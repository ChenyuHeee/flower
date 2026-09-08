# Workflow entwerfen

Das Framework kümmert sich nur um Mechanik: wie ein Schritt läuft, wie Sessions aneinander anschließen, was bei Fehlern passiert, wie Kontext gespart wird.
**Den [Workflow](../reference/glossary.md#流程) schreibst du** — das Framework weiß nicht, an welchem Projekt du arbeitest oder welche Sprache du benutzt, und soll es auch nicht wissen. Diese Seite erklärt, wie man einen Workflow entwirft; die vollständigen Feldtabellen von `Step` und `Workflow` stehen in der [Python-API](../reference/api.md).

## Welches Problem das löst {#解决什么问题}

Ein [long-horizon](../reference/glossary.md#长程) Run ist nichts, was sich in einem einzigen Prompt sagen ließe: erst die Anforderung klären, dann recherchieren, dann implementieren, dann prüfen — jeder Abschnitt hat seine eigene Rolle, seinen eigenen Kontext, seine eigenen Abnahmekriterien.
Schreibt man alles in einen Prompt, entscheidet das Modell selbst, welchen Abschnitt es überspringt; schreibt man einen Workflow, **werden Reihenfolge, Abbruchbedingungen und Zustandsübergabe zu Python-Code** — lesbar, testbar, und man kann nur den kaputten Schritt neu laufen lassen.

`Workflow` macht genau drei Dinge:

- eine Reihe von [Schritten](../reference/glossary.md#步骤) der Reihe nach ausführen
- entscheiden, was jeder Schritt vom Vorangegangenen sieht (drei Arten der Session-Verkettung + ein `ctx`-Dictionary)
- entscheiden, wann wiederholt und wann vorzeitig abgebrochen wird

Es enthält keinerlei Domänenannahmen. Wo geschnitten wird, was jeder Schritt abnimmt, was bei Nichtbestehen passiert — genau diese vier Dinge sind „Workflow entwerfen".

## Wie man es benutzt (Minimalcode) {#怎么用最小代码}

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
        # Neue Session: sieht nur, was im Prompt übergeben wurde
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Wieder eine neue Session, das Ergebnis des vorigen Schritts wird in den Prompt injiziert (billig, verhindert Verschmutzung)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

Das Argument von `flower run` ist `Modul:Attribut` oder `Dateipfad:Attribut`. Ist das aufgelöste Objekt aufrufbar, wird es einmal aufgerufen; das resultierende `Workflow` wird dann ausgeführt. Am Ende gibt das Terminal die Gesamtkosten und den Pfad des Run-Manifests aus.

Ein eigenes Treiberprogramm geht auch, das erste Argument von `Workflow.run` ist ein `Runtime`:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## Was tatsächlich passiert {#它实际做了什么}

### Was ein Step bekommt und was er zurückgeben muss {#一个-step-收到什么必须返回什么}

`Step` ist keine Funktion, sondern eine **Deklaration**. Ausgeführt wird tatsächlich `Runtime.run(step.spec, gerenderter Prompt, ...)` —
**ein Schritt = ein `Runtime.run` = eine [Session](../reference/glossary.md#会话)**.

Die ersten drei Felder sind Positionsargumente, `Step(name, spec, prompt)`:

- `name` — der Schrittname. Er ist gleichzeitig der Schlüssel in `ctx`, der Zeilenname in `runs/manifest.json` und der Schlüssel der prozessübergreifenden [Lineage](../reference/glossary.md#血缘).
- `spec` — mit welchem `AgentSpec` gelaufen wird. Bestimmt Tool-Whitelist, Modell und Budget dieses Schritts.
- `prompt` — ein `str` oder `(ctx) -> str`. Ist es aufrufbar, bekommt es das aktuelle `ctx`; **das ist der billigste Weg, das Ergebnis des vorherigen Schritts einzuspeisen** (der andere ist Session-Verkettung, siehe unten).

„Zurückgegeben" wird ein `StepResult`, aber im Workflow bekommst du zwei Dinge:

- `ctx[step.name]` — standardmäßig `result.text`, mit `reduce` stattdessen dessen Rückgabewert;
- `ctx["_results"][step.name]` — das vollständige `StepResult` (Kosten, Turns, Anzahl Versuche, `session_id`).

`result.text` **nimmt nur den Fließtext des Main Threads auf**: Äußerungen eines Subagents liegen in dessen eigenem Transcript, das an ihn übergebene [Task Brief](../reference/glossary.md#任务书) ist `kind="prompt"`, der synthetische Fehler bei Verbindungsabbruch ist `kind="error"` — keines der drei geht ein.

### reduce: kein Syntaxzucker {#reduce不是糖}

Standardmäßig wird der Wortlaut des Modells weitergereicht. Bei manchen Schritten **darf** der Wortlaut nicht unverändert weitergereicht werden:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

In der Praxis klebt der Schritt zur Anforderungsklärung **den kompletten Code** zusätzlich zu den vier Abschnitten mit hinein. Weitergereicht werden dürfen nur die geparsten vier Abschnitte, sonst landet dieser ganze Code im Prompt des nächsten Schritts. `clarify_step` fängt genau das über dieses Feld ab.

`reduce` **muss eine synchrone Funktion sein**; `gate` / `when` / `on_reject` dürfen async sein.

### Wie Zustand durch ctx fließt {#状态怎么在-ctx-里流动}

`ctx` ist ein `dict[str, Any]`, nämlich `Workflow.context` selbst. Nach jedem Schritt wird nach dieser Tabelle geschrieben:

| Fall | `ctx[Schrittname]` | Sonstiges |
|---|---|---|
| `when(ctx)` liefert False | **wird nicht geschrieben**, ganzer Schritt übersprungen | erzeugt kein Result, kommt auch nicht in `_results` |
| bestanden | `reduce(result, ctx)`, ohne Angabe `result.text` | |
| fehlgeschlagen + `on_fail="stop"` (Default) | **wird nicht geschrieben** | schreibt `ctx["_failed_at"]`, der gesamte Workflow stoppt bei diesem Schritt |
| fehlgeschlagen + `on_fail="skip"` | **wird nicht geschrieben** | läuft weiter |
| fehlgeschlagen + `on_fail="continue"` | `result.text` (unvollständig, **ohne `reduce`**) | läuft weiter |

Ob bestanden oder nicht, `ctx["_results"][Schrittname]` wird immer geschrieben; ist `result.session_id` nicht leer, wird sie zusätzlich in `ctx["_sessions"]` geschrieben und in der Lineage vermerkt.

**Ob dieser Workflow erfolgreich war, entscheidet `ctx.get("_failed_at")`** — nicht, ob der letzte Schritt eine Ausgabe hatte.

Alle Schlüssel mit führendem Unterstrich setzt `Workflow.run` selbst: `_runtime`, `_on_event`, `_sessions`, `_results`, `_lineage`, `_woke`, `_aborted`, `_failed_at` — benutze sie nicht als eigene Schrittnamen. Die einzelnen Mechanismen legen zusätzlich eigene ab (`_brief` / `_goal` / `_verdict` usw.); die vollständige Liste steht in der [Python-API](../reference/api.md).

Davon sind `_runtime` und `_on_event` für `gate` gedacht: ein Gate kann selbst einen Agent zur Beurteilung losschicken, und dieser Beurteilungsvorgang wird trotzdem an die UI gemeldet — sonst wäre die Oberfläche für die zehn, fünfzehn Sekunden schwarz und sähe aus wie eingefroren. Der [Goal Guard](goal.md) ist genau so implementiert.

`ctx` ist dasselbe Dict: **läuft dasselbe `Workflow`-Objekt ein zweites Mal, sind die Schlüssel des ersten Laufs noch da**. Für einen sauberen Neustart ein neues Objekt anlegen oder explizit `context={}` übergeben.

!!! warning "Bei on_fail=skip wird `ctx[Schrittname]` nicht geschrieben"
    Ein nachgelagertes `lambda ctx: ctx["某步"]` läuft direkt in einen `KeyError`. Willst du mit dem unvollständigen Ergebnis weiterlaufen, nimm `on_fail="continue"`; willst du wirklich überspringen, muss der nachgelagerte Schritt selbst per `ctx.get(...)` absichern.

### Beurteilen und zurückweisen: gate, on_reject, StepAbort {#判定与打回gateon_rejectstepabort}

`gate(result, ctx) -> bool` beurteilt „ist durchgelaufen, aber taugt es?". Zwei Details, die man kennen muss:

- **Ist `result.ok` falsch, wird `gate` gar nicht erst aufgerufen** (Kurzschluss).
- **Pro Versuch wird es genau einmal aufgerufen**, das Ergebnis wird für später aufgehoben — es kann Seiteneffekte haben. Das Gate von `clarify_step` schreibt das [Brief](../reference/glossary.md#需求确认书) auf Platte; mehrfaches Auslösen heißt mehrfaches Schreiben.

Wie nach einem nicht bestandenen Gate wiederholt wird, hängt davon ab, ob `on_reject` gesetzt ist:

| | Wie die nächste Runde läuft | Name im Manifest |
|---|---|---|
| nur `retries` | von vorn, originaler Prompt, originales `resume_from` | `X#retry1` |
| plus `on_reject` | **die gerade abgelehnte Session wird fortgesetzt**, der Prompt ist der Rückgabewert von `on_reject`, `fork` wird auf False gezwungen | `X#round2` |

Der zweite Fall ist „zurückgeben, sagen, was fehlt, und nachbessern lassen" — die bereits geleistete Arbeit und der Kontext sind noch da. Gibt `on_reject` einen leeren String zurück, oder hat dieser Versuch gar keine `session_id` erhalten, degradiert es zum Lauf von vorn.

`gate` kann außerdem `StepAbort` werfen, was bedeutet: **weitere Versuche bringen nichts, verbrauche die restlichen Runden nicht**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

Nach dem Wurf: der Grund landet in `ctx["_aborted"]`, der Schritt gilt als fehlgeschlagen und folgt `on_fail` (Default `"stop"`), **die Retry-Schleife bricht sofort ab**, und von den verbleibenden `retries` wird keiner verbraucht.

Merke den Unterschied: **False zurückgeben heißt „diesmal nicht, noch eine Runde"; `StepAbort` heißt „noch eine Runde bringt nichts".** Der typische Fall ist ein Ziel, das in dieser Umgebung als nicht machbar beurteilt wurde und bei dem niemand zum Fragen da ist — weiterzudrehen ist dann die teuerste Option.

### Die zwei Retry-Ebenen nicht verwechseln {#两层重试别混}

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| Wofür | fachliches Scheitern: `gate` nicht bestanden, `result.ok` falsch | Infrastruktur: Netzwerkzucken, Verbindungsabbruch, 5xx |
| Wie wiederholt wird | **ganzer Schritt von vorn**, gleicher Prompt und gleiches `resume_from` | **Resume ab der Abbruchstelle**, die bisherigen Kosten sind nicht umsonst |
| Was vorher passiert | nichts | DNS- + TCP-Probe warten, bis das Netz zurück ist (kein HTTP, keine Credentials, die Probe muss kostenlos sein) |
| Nicht wiederholbar | — | falsche Credentials, falsche Parameter stoppen sofort, kein endloses Warten |

Der Prompt für das Fortsetzen **enthält absichtlich keinerlei Fehlerdetails** — das Modell muss wissen „du wurdest unterbrochen, mach weiter", nicht, ob es ENOTFOUND oder 503 war.

### Schritte verketten {#把步骤串起来}

Für die Zustandsübergabe zwischen Schritten gibt es drei Verkettungsarten; die Wahl bestimmt, was der nächste Schritt sieht:

| Schreibweise | Was der nächste Schritt sieht | Wofür |
|---|---|---|
| `resume_from=None` (Default) + Injektion im Prompt | nur die von dir injizierten Worte | unabhängige Schritte. Billig, verhindert Verschmutzung |
| `resume_from="Name des vorherigen Schritts"` | die vollständige Session-Historie | wenn zusammenhängendes Gedächtnis nötig ist |
| `resume_from="Name des vorherigen Schritts"` + `fork=True` | vollständige Historie, aber in einem neuen Zweig | Review / parallele Varianten / Retries, die den Originalstrang nicht verschmutzen |

Der von `resume_from` referenzierte Schritt **muss tatsächlich eine Session erzeugt haben**. Wurde er per `when` übersprungen oder lief gar nicht, wirft `Workflow.run` direkt einen `ValueError` — es degradiert nicht stillschweigend zu einer neuen Session, weil damit die Annahme „zusammenhängendes Gedächtnis" heimlich verfiele.

Ein paar Entwurfserfahrungen, für die wiederholt bezahlt wurde:

1. **Ein Schritt, ein abnehmbares Ziel.** Schrittgrenzen sind Kontextgrenzen: dort, wo `resume_from=None` steht, sind die vorherigen Tool-Ergebnisse endgültig nicht mehr dauerhaft präsent. Siehe [Kontextökonomie](context.md).
2. **Im Zweifel erst `clarify_step`.** In long-horizon Runs ist „das Ziel falsch verstanden" der teuerste Fehler, und ausgerechnet er gehört zu der Sorte, die die kontextsparenden Schichten nicht wegräumen können. Siehe [Clarify](clarify.md).
3. **Delegierte Aufgaben müssen selbsttragend sein.** Ein Subagent hat einen sauberen Kontext, er weiß nicht, was der [Koordinator](../reference/glossary.md#协调者) weiß. Nötiger Hintergrund gehört ins Task Brief, oder sag ihm, welches Artefakt er lesen soll.
4. **Lange Ausgaben gehen auf die Platte, nicht in die Antwort.** Das steht bereits in `WORKER_RULES`; deine `instructions` sollen es nicht wieder aufheben („zeig mir das komplette Log hier in der Antwort").
5. **`gate` prüft vorrangig harte Bedingungen.** Ob eine Datei existiert, ob der Exit-Code 0 ist — was sich in einer Zeile Python entscheiden lässt, dafür schickt man kein Modell los. Soll ein Modell urteilen, nimm das fertige `with_goal` — es ersetzt das Gate durch eine Implementierung, die einen eigenständigen [Judge](../reference/glossary.md#判定者) laufen lässt; bastle das nicht selbst im Gate nach.
6. **Parallele Änderungen am selben Repo bekommen `worker(isolate=True)`.** Der Abschluss (Merge, Worktrees aufräumen, PR öffnen) bleibt derzeit deinem Workflow überlassen; die Harness garantiert nur, dass die Änderungen im jeweils eigenen Worktree landen.

### Die Workbench muss am Workflow hängen {#工作台要挂在-workflow-上}

Überall, wo der Workflow Dateien in die [Workbench](../reference/glossary.md#工作台) schreibt — typischerweise `clarify_step(brief_path=...)` — musst du selbst eine `Workbench` anlegen und sie **gleichzeitig** an `Workflow.workbench` hängen und dem `Runtime` übergeben:

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

Dass `channel` am Workflow hängt, hat zwei Gründe: `run()` verbindet dessen `on_event` mit demselben Event-Ausgang (nur solange `channel.on_event` noch `None` ist), und das Treiberprogramm erfährt über dieses Feld, wem es antworten soll.

!!! warning "Selbst zusammengebaute Workbench-Pfade fallen stillschweigend aus"
    Die Standardposition bei `Runtime(workbench=True)` ist `<run_dir>/workbench`, die von `Workbench(ws)` dagegen `<ws>/.flower` — **das sind nicht dieselben Verzeichnisse**. Wird der Workflow von der CLI aufgerufen, sieht er `run_dir` nicht; ein selbst zusammengebauter Pfad zeigt dann einfach woandershin, das Brief wird nach Verzeichnis A geschrieben, der injizierte Index scannt Verzeichnis B — **und es gibt keinen Fehler**. Legt man ein Objekt an und benutzt es auf beiden Seiten, existiert das Problem nicht; ist `Workflow.workbench` gesetzt, wird `-W` auf der Kommandozeile ignoriert und dieses Feld gilt.

### `continuous=True`: derselbe Pfad ein zweites Mal {#continuoustrue同一个路径再跑一次}

Die drei Verkettungsarten oben betreffen Schritte **innerhalb eines Runs**. Prozessübergreifend ist eine andere Achse:

```python
Workflow([...], continuous=True)     # Default
```

Läuft derselbe Workspace ein zweites Mal, setzt jeder Schritt die Session vom letzten Mal fort — über die Zuordnung „Schrittname → session_id" in `<run_dir>/lineage.json`. Beim Laden geht jeder Eintrag durch `runtime.has_session()`, um zu prüfen, ob die Session noch in der Datenbank ist; nur lebende werden benutzt: die Lineage-Datei kann `sessions.db` überleben, und ein Resume auf eine nicht existierende Session fliegt einem erst um die Ohren, wenn der Subprozess gestartet ist.

Drei Konsequenzen:

- **`resume_from=None` heißt nicht „ganz neue Session".** Beim ersten Lauf schon, beim zweiten nicht. Soll es jedes Mal eine neue Session sein, schreib explizit `Workflow(..., continuous=False)`.
- **Bei [Continuity](../reference/glossary.md#接续) wächst der Kontext stetig.** Willst du beim Fortsetzen etwas anderes sagen, nimm `Step.resume_prompt` — was im Kontext der Gegenseite schon steht, sollte man nicht erneut schicken.
- Schritte mit explizitem `resume_from` sind nicht betroffen, das hat Vorrang.

!!! warning "Der Schrittname ist der prozessübergreifende Schlüssel"
    Einen Schrittnamen zu ändern heißt, die Lineage dieses Schritts zu kappen: beim nächsten Lauf wird nicht mehr fortgesetzt, und **es gibt keinen Fehler**. Retry-Namen mit den Suffixen `#retry1` / `#round2` **gehen nicht in die Lineage** (vermerkt wird immer der Originalname); das ist auch einer der Gründe, warum „der Judge ist immer eine neue Session" funktioniert.

Vollständiger Entwurf und `--new` siehe [Continuity](continuity.md).

## Wann man es nicht benutzen sollte {#什么时候不该用它}

- **Nur ein Agent, und keine Beurteilung nötig** — kein `Workflow` drumherum. Direkt `await rt.run(spec, "…")`, oder auf der Kommandozeile `flower once "读一眼这个仓库"`.
- **Die Form ist genau „Anforderung klären → Ziel setzen → arbeiten"** — nimm das fertige
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py), statt es selbst zu schreiben:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    Es sind **drei Schritte**: `确认需求` → `设定目标` → `干活` (mit Beurteilungsschleife, der Beurteilungsschritt heißt `干活·判定#N`). Mit `goal=False` entfallen zweiter Schritt und Beurteilungsschleife, mit `clarify_only=True` bleibt nur der erste Schritt. Es bringt eigenen `HumanChannel` und eigene `Workbench` mit und hängt sie an den Workflow, also nimm `Runtime(workbench=wf.workbench)` direkt so und bau nicht noch eine zweite zusammen.

    Ohne Code geht es auch: im Projektverzeichnis `flower "帮我做一个 X"` startet genau das.
    **Es ist keine „empfohlene Workflow-Gestaltung"**, sondern nur der Weg, ohne Konfiguration loszulaufen.

- **Schritte feiner geschnitten als „ein abnehmbares Ziel"** — reiner Verlust. Jeder Schritt startet eine neue Session, und eine neue Session hat eine Startuntergrenze (beim Koordinator gemessen rund 34k Kontext), die sich nicht wegamortisieren lässt.
- **Nachträglich auf eine bestimmte Nachricht zurückrollen** — über `Workflow` geht das nicht, es übergibt nie `resume_at`. Ruf direkt `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)` auf.

Wie man die Rolle wählt (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) und die feldweise Semantik von `Step` und `Workflow` stehen in der [Python-API](../reference/api.md); die Begriffe im [Glossar](../reference/glossary.md).
