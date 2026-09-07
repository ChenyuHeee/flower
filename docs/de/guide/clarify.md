# Vorabklärung

Bevor gearbeitet wird, wird die Anforderung geklärt. Der [Clarifier](../reference/glossary.md#确认者) ist eine Rolle, die ausschließlich fragt und nichts anfasst; er fragt so lange, bis alles klar ist, und gibt am Ende einen [Brief](../reference/glossary.md#需求确认书) aus genau vier Abschnitten aus, der auf die Platte eingefroren wird. Jeder nachfolgende [Schritt](../reference/glossary.md#步骤) startet mit diesem Dokument und rät die Anforderung nicht erneut — und der Frage-Antwort-Verlauf **gelangt nie** in den Kontext stromabwärts.

## Welches Problem das löst

Alles, was flower beim Aufräumen des Kontexts entfernt, ist **Arbeitsmaterial**: abgelaufene Zeitbezüge, entfernte abgelehnte Aufrufe, entfernte Fehlermeldungen, große Ergebnisse per [Spill](../reference/glossary.md#落盘) auf Platte. Arbeitsmaterial zu verlieren ist unkritisch — ein erneuter Lauf stellt es wieder her.

Eine Fehlerklasse verhält sich anders: **das Ziel wurde falsch verstanden**. Sie ist die einzige Klasse, die durch das Aufräumen des Kontexts **schlimmer** wird. Nachdem das Arbeitsmaterial verschwunden ist, bleibt genau die Entscheidung übrig, die auf der falschen Prämisse aufbaut — und sie sieht exakt aus wie eine richtige Entscheidung; nichts deutet mehr darauf hin, dass ihre Prämisse fragwürdig ist.

Ein [Long-Horizon](../reference/glossary.md#长程)-Lauf verstärkt das bis zum Äußersten: Die falsche Prämisse läuft erst stundenlang, schickt über ein Dutzend [subagents](../reference/glossary.md#subagent) los, legt einen Haufen Artefakte auf der Platte ab — und fliegt erst danach auf. Teuer sind dann nicht die Token, sondern dass **jedes einzelne Artefakt gegen die falsche Anforderung gebaut wurde**. Die Abrechnung von [HT001](../cases/ht001.md) zeigt das Verhältnis: der Klärungsschritt **$0.3704 / 5 Runden / 0.06h**, der eigentliche Arbeitsschritt danach **$171.2476 / 31 Runden / 10.44h**.

Also braucht es einen Kanal, der „anhalten und nachfragen" kann — und der muss **vor** dem Arbeitsbeginn liegen.

## Verwendung (minimaler Code)

### Ohne Code: Kommandozeile

Ins Projektverzeichnis wechseln und direkt starten:

```bash
cd /path/to/your/project
flower
```

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Im Terminal erscheinen dann Rückfragen wie diese:

```text
  ? 这个工具是给命令行用,还是要有 Web 界面?
     1) 纯命令行
     2) Web 界面
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
```

- Eine **Nummer** eingeben, um eine Option zu wählen, oder einfach frei antworten
- **Enter = diese Frage überspringen**; das Modell entscheidet selbst und trägt die Annahme unter „未知与假设" (Unbekanntes und Annahmen) ein
- Erst wenn alle vier Abschnitte vollständig sind, geht es weiter; der Brief wird eingefroren in `.flower/notes/需求.md`
- **Ein erneuter Lauf fragt nicht noch einmal alles ab** — für eine neue Klärung die Datei löschen oder `--new` ergänzen

Nur sehen, was gefragt wird, ohne die Arbeit anzustoßen: `flower --clarify-only`. Ein hartes Kontingent für Rückfragen: `--asks 12` (nur dann erscheint unter den Optionen zusätzlich die Zeile `(还能问 N 次)`; standardmäßig unbegrenzt, dann fehlt diese Zeile). Niemand sitzt davor: `--timeout 0`. Die Implementierung dieses Pfades liegt in [`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "Antworten laufen über stdin — das braucht ein echtes Terminal"
    In Pipes, unter `nohup` oder in CI kann niemand antworten: Sobald stdin EOF liefert, gilt die gerade offene Frage als „Eingabe geschlossen" und wird übersprungen, und jede weitere Frage wartet den vollen `--timeout` ab. In solchen Fällen direkt `--timeout 0` setzen — alle Rückfragen laufen sofort ins Leere, das Modell entscheidet selbst und schreibt die Annahmen unter „未知与假设".

### Selbst verdrahten

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # Rückfragen standardmäßig unbegrenzt, 30 Minuten Wartezeit auf den Menschen
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

In `prompt` steht nur **dein** ursprüngliches Anliegen, ein Satz reicht. Was gefragt wird, entscheidet der Clarifier selbst — welche Fragen in deiner Domäne relevant sind, weiß das Framework nicht und soll es auch nicht wissen. Das `协调者` oben ist ein `AgentSpec`, das du selbst mit `coordinator()` gebaut hast, siehe [Workflow entwerfen](workflow.md).

Die Parameter von `clarify_step()`:

| Parameter | Default | Beschreibung |
|---|---|---|
| `channel` | — | `HumanChannel`. **Dieselbe Instanz** muss auch an `Workflow(channel=...)` hängen |
| `brief_path` | — | Wo der Brief landet. Muss innerhalb der eingehängten [Workbench](../reference/glossary.md#工作台) liegen, siehe unten |
| `prompt` | — | Dein ursprüngliches Anliegen. `str` oder `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Schrittname, zugleich der Schlüssel in `ctx` |
| `spec` | `None` | Eigenes `AgentSpec` mitbringen; wenn gesetzt, wird `clarify()` nicht verwendet |
| `instructions` | `""` | Domänenanweisungen, die hinter `CLARIFIER_RULES` angehängt werden |
| `always_ask` | `False` | `True` = jedes Mal neu klären (beim Ändern der Anforderung) |
| `on_fail` | `"stop"` | Verhalten bei unvollständigen vier Abschnitten, wie `Step.on_fail` |
| `retries` | `0` | Anzahl Wiederholungen bei unvollständigen vier Abschnitten |
| `**spec_kw` | — | Durchgereicht an `clarify()`: `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

Nach dem Durchlauf enthält `ctx` drei Dinge:

```python
ctx["确认需求"]     # str, kompakte Fassung der vier Abschnitte (prompt_block), direkt in nachgelagerte Prompts einsetzbar; Schlüssel = Schrittname
ctx[BRIEF_KEY]     # "_brief" —— das Brief-Objekt, für abschnittsweisen Zugriff
ctx[MISSING_KEY]   # "_brief_missing" —— nur bei unvollständigen vier Abschnitten: welche fehlen, zur Anzeige im UI
```

Wenn es hakt, zuerst an diesen Stellschrauben drehen:

| Symptom | Woran drehen |
|---|---|
| Fragt zu viel, zu kleinteilig | `max_asks` ein hartes Kontingent geben; in `instructions` festhalten, was in deiner Domäne selbstverständlich ist |
| Fängt nach zu wenigen Fragen an | In `instructions` benennen, welche Punkte zwingend geklärt sein müssen (die Anzahl ist ohnehin unbegrenzt, am Kontingent zu drehen bringt nichts) |
| Die vier Abschnitte werden lieblos gefüllt | In `instructions` ein Beispiel aus deiner eigenen Domäne mitgeben |
| Hängt, obwohl niemand davor sitzt | `timeout_s=0` |
| Soll jedes Mal neu klären | `always_ask=True`, oder die Brief-Datei löschen |

## Was es tatsächlich tut

### Auslösezeitpunkte: drei Einhängepunkte, kein einziges neues Feld

Was `clarify_step()` erzeugt, ist ein ganz normaler `Step` — lediglich mit drei ausgefüllten Callbacks:

| Einhängepunkt | Wann er läuft | Was er tut |
|---|---|---|
| `Step.when` | Vor diesem Schritt | Existiert der Brief bereits vollständig mit vier Abschnitten, wird der Schritt **übersprungen** und der Brief in `ctx` gelegt |
| `Step.gate` | Nach dem Schritt, bevor das Ergebnis weitergereicht wird | Sind die vier Abschnitte unvollständig, **geht es nicht weiter**; sind sie vollständig, `write()` — **einfrieren** |
| `Step.reduce` | Nach dem Bestehen | Reicht die **geparsten vier Abschnitte** weiter, nicht den Rohtext des Modells |

**Auch beim Überspringen wird `ctx` gefüllt.** Das übersieht man leicht: Gibt `when` `False` zurück, führt `Workflow` den Schritt nicht aus und schreibt folglich auch kein `ctx[step.name]` — deshalb legt `clarify_step` den vorhandenen Brief schon in `when` hinein. Sonst bekämen nachgelagerte Schritte beim erneuten Lauf einen `KeyError`.

`reduce` reicht `Brief.prompt_block()` weiter und nicht den Rohtext, weil im Rohtext zusätzliches Material stecken kann (in der Praxis klebt das Modell schon mal den kompletten Code in seine Antwort).

Bei der [Fortsetzung](../reference/glossary.md#接续) eröffnet dieser Schritt mit einem anderen Satz — `CLARIFY_RESUME`: „接着刚才那次没问完的需求确认继续 —— **不是重新开始**……". Ohne diesen Satz würde die Fortsetzung das ursprüngliche Anliegen als neue Aufgabe erneut abschicken, und der Clarifier könnte bereits gestellte Fragen wiederholen.

### Grenze: Der Frage-Antwort-Verlauf gelangt nicht in den nachgelagerten Kontext

```text
Klärung           eigene Session  ────→  eingefrorener Brief (4 Abschnitte) auf Platte
                                                             │
Arbeit (nächster Schritt)  neue Session (resume_from=None) ◄─┘   bekommt nur diese vier Abschnitte
```

Das `resume_from` von `clarify_step` bleibt beim Default `None`, der nächste Schritt ist also eine **neue Session** und bekommt nur den Brief. Der Frage-Antwort-Verlauf **war nie** im Kontext des [Koordinators](../reference/glossary.md#协调者) — es ist nicht „erst hinein und dann herausgeschnitten". Der Unterschied ist substanziell: Herausgeschnittenes liegt weiterhin in `sessions.db` und kann durch ein Resume zurückkommen; was nie drin war, hat dieses Problem nicht.

Der Frage-Antwort-Verlauf selbst wird **an `log_path` angehängt**. Diese Kopie belegt keinen Kontext, ist von Compact nicht betroffen und existiert auch noch auf einer anderen Maschine — dieselbe Idee wie bei der Workbench.

### Jeder der vier Abschnitte blockt eine Fehlerklasse

| Abschnitt | Inhalt | Was passiert, wenn er fehlt |
|---|---|---|
| **目标** (Ziel) | Ein Satz: was gebaut wird, für wen | Es entsteht etwas anderes |
| **验收标准** (Abnahmekriterien) | Entscheidbare Bedingungen, eine pro Zeile. „Funktioniert gut" zählt nicht, „`x` ausführen liefert `y`" zählt | Niemand kann entscheiden, ob es fertig ist |
| **边界** (Grenzen) | **Explizit, was nicht gemacht wird** | Scope Creep. Dieser Abschnitt zügelt **jeden einzelnen** nachfolgenden subagent |
| **未知与假设** (Unbekanntes und Annahmen) | Was nicht gefragt wurde, was in einen Timeout lief, was selbst geraten wurde — eine Zeile pro Punkt | **Falsche Prämissen werden still begraben** |

Der vierte Abschnitt ist die Sicherung des Long-Horizon-Runs. Egal welcher der ersten drei Abschnitte falsch ist: Solange die Annahme explizit im vierten Abschnitt steht, hat jeder spätere Leser die Chance, sie zu stoppen. Ist sie begraben, fällt es erst Stunden später auf, wenn alle Artefakte für die Tonne sind. Falsche Prämissen lassen sich nicht vollständig vermeiden, aber man kann sie **explizit** machen.

Erst wenn alle vier Abschnitte vorhanden sind, geht es weiter; welcher fehlt, meldet `Brief.missing()` — es liefert die chinesischen Abschnittsnamen zurück, die direkt angezeigt werden können.

Das Parsen ist bei der Schreibweise sehr nachsichtig: `## 目标` / `**目标**` / `目标:` / `3. 边界` werden alle erkannt, ebenso Text direkt hinter der Überschrift (`目标: 做一个 X`), ebenso gängige Aliasse (`验收条件`→验收标准, `不做什么`→边界, `未知项与假设`→未知与假设); erscheint ein Abschnitt mehrfach, gilt der erste mit Inhalt. Zwei Ausnahmen muss man kennen:

- `Brief.parse()` **entfernt zuerst eingezäunte Codeblöcke**; trifft es auf einen **nicht geschlossenen** Zaun, wird ab dort alles Weitere verworfen. Wird die Modellausgabe abgeschnitten, lassen sich die nachfolgenden Abschnitte nicht mehr parsen → vier Abschnitte unvollständig → `gate` schickt es zurück.
- `Brief.load()` behandelt `"(未填)"` als leer. Wer den Brief von Hand bearbeitet und den Platzhaltertext von `to_markdown()` stehen lässt, hat diesen Abschnitt weiterhin als fehlend.

### Grenze: Was der Clarifier anfassen darf

Es lief einmal ein **unbeschränkter** Clarifier (`/tmp/probe_ask.py`, **$0.8908 / 230 Sekunden**): Nach zwei Fragen **fing er direkt an, Code zu schreiben**; nachdem die Berechtigungsschicht ihn stoppte, **klebte er den kompletten Code in den Antworttext**. Ein „schreib keinen Code" im Prompt hält das nicht auf — genau so etwas stand damals bereits in seinem System-Prompt. Deshalb gibt es zwei Mechanismen:

**Erstens: ein Hook, der seine Schreibwerkzeuge abfängt.** Die genehmigungsfreie Liste von `clarify()` besteht aus `mcp__human__ask` plus (bei `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch`, ohne `Write` / `Edit` / `Bash` / `Agent`. Durchgesetzt wird das vom `whitelist_guard`, den die `Runtime` automatisch installiert: Er leitet aus der genehmigungsfreien Liste ab, welche von `Bash` / `Write` / `Edit` / `NotebookEdit` zu blocken sind, und antwortet bei einem Treffer mit `deny`. Er wird nicht „gebeten, nicht zu arbeiten", er **kann** nicht arbeiten.

Lesen zu erlauben lohnt sich: Ein Blick ins Repository spart mehrere Fragen, und diese Session wird nach Gebrauch weggeworfen, also ist es egal, wenn sie durch Lesen verschmutzt wird (`can_read=False` nimmt ihm auch das Lesen).

**Das muss ein Hook sein, `allowed_tools` allein reicht nicht.** Letzteres ist eine **genehmigungsfreie Liste, keine exklusive Whitelist** — das Modell kann Werkzeuge aufrufen, die nicht darin stehen. Zwei weiterhin gültige Messbelege:

- In [HT002](../cases/ht002.md) hat der [Judge](../reference/glossary.md#判定者) im Schritt „Ziel setzen" tatsächlich **11 Mal `Bash`** ausgeführt, obwohl `judge()` standardmäßig `can_run=False` setzt und `Bash` gar nicht in der Liste steht (dieser Lauf hatte den Hook noch nicht — heute würde derselbe Aufruf vom `whitelist_guard` sofort mit `deny` beantwortet, was genau zeigt, dass der Hook ihn aufhält und nicht die Liste).
- **Eine Sonde für $0.1**: Ein Agent mit `allowed_tools=["Read"]` soll eine Datei schreiben — `Write` wird von der Berechtigungsschicht abgelehnt (`"requested permissions to write ... but you haven't granted it yet"`), `Bash` von der Pfadsicherheit (`"Output redirection was blocked. For security, Claude Code may only write to files in the allowed working directories"`). **Der Aufruf ging raus**, aufgehalten haben ihn andere Schichten.

`clarify()` setzt `permission_mode` nicht explizit und erbt den `AgentSpec`-Default `"default"`. `coordinator()` steht standardmäßig auf `"acceptEdits"` — wer diesen Wert an den Clarifier durchreicht, hat diesen Schutz verloren.

**Zweitens: Das Framework parst nur die vier Abschnitte, alles andere fliegt weg.** `Brief.parse()` entfernt erst eingezäunte Codeblöcke und sucht dann Überschriften — eingeklebter Code gelangt also nicht stromabwärts. Das ist die letzte Schleuse gegen „er verschmutzt den nachgelagerten Kontext".

### Grenze: Der Rückfragekanal

Das Rückfragewerkzeug auf Modellseite heißt `mcp__human__ask` (Parameter `question`, optional `options`). `HumanChannel` ist ein prozessinterner MCP-Server und **registriert zwei Werkzeuge** — `mcp__human__ask` und `mcp__human__inbox`; in der genehmigungsfreien Liste des Clarifiers steht nur das erste (der Posteingang ist für den Koordinator).

```python
HumanChannel(
    on_event=None,        # Callback für Push-UIs. An einem Workflow hängend automatisch von Workflow.run verdrahtet
    max_asks=None,        # standardmäßig unbegrenzt
    timeout_s=1800.0,     # 30 Minuten. None = ewig warten; <= 0 = vollautomatisch
    log_path=None,        # Frage-Antwort-Verlauf wird an diese Datei angehängt, belegt keinen Kontext
    amend_path=None,      # Was der Mensch während des Laufs sagt, wird an diese Datei angehängt (üblicherweise der Brief)
    over_budget_text=..., timeout_text=..., declined_text=...,   # Formulierungen für die drei Arten von Leerlauf
)
```

Der Normalfall eines Long-Horizon-Agents ist, dass **niemand zuschaut** — deshalb muss „anhalten und auf einen Menschen warten" elegant scheitern können:

| Einstellung | Verhalten |
|---|---|
| `timeout_s=1800.0` (Default) | Wartet eine halbe Stunde; danach kommt ein erklärender Satz zurück, **kein Fehler** |
| `timeout_s=None` | Wartet ewig. Nur verwenden, wenn sicher jemand davorsitzt (die CLI kann diesen Wert nicht liefern, `--timeout` ist ein float) |
| `timeout_s=0` (negativ ebenso) | **Vollautomatisch**: Alle Rückfragen laufen sofort ins Leere, es wird nicht so getan, als würde gewartet |
| `max_asks=None` (Default) | **Unbegrenzt** — wie oft gefragt wird, entscheidet der Clarifier selbst |
| `max_asks=N` | Hartes Kontingent. Darüber hinausgehende Rückfragen werden vom Werkzeug **direkt abgelehnt**, ohne Blockieren, ohne Fehler |
| `max_asks=0` | Keine Rückfragen erlaubt (CI / unbeaufsichtigt) |

Bei `max_asks=None` liefert `remaining` `-1` zurück (nicht 0 und nicht unendlich), weshalb das Terminal kein „还能问 N 次" anzeigt.

Der Wortlaut bei Timeout lautet:

> 无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。
> 不要重复提问,也不要停在这里。

Alle drei Arten von Leerlauf (Timeout / Kontingent erschöpft / Mensch überspringt aktiv) zielen auf dieselbe Handlung: **die Annahme in den vierten Abschnitt schreiben**. Genau deshalb hat der vierte Abschnitt auch im unbeaufsichtigten Betrieb Inhalt, und genau deshalb kann der Long-Horizon-Lauf weiterlaufen. Ein Kontingent im Prompt ist eine Empfehlung; **erst die Zählung im Kanal ist eine Garantie**.

Eine nachgemessene Eigenschaft des Mechanismus: In einem prozessinternen MCP-Werkzeug-Handler auf ein externes Future zu `await`en führt **nicht zum Deadlock** — während der Handler hängt, läuft die Event-Loop weiter, und eine andere Task oder **ein anderer Thread** kann die Antwort einspeisen. `answer()` / `decline()` lassen sich also direkt aus einem Web-Backend oder einem TUI-Eingabethread aufrufen (intern über `loop.call_soon_threadsafe`); das ist der Normalfall, kein Randfall. Ausnahmen aus UI-Callbacks werden in `ui_errors` gesammelt und **brechen den Lauf nicht ab** — ein abgestürztes Frontend darf nicht drei Stunden Arbeit mitreißen. Die vollständige Mitgliederliste steht in der [Python-API](../reference/api.md).

!!! warning "Ein zu kleines `max_turns` macht „so lange fragen, bis es klar ist" zur leeren Behauptung"
    Das `max_turns` von `clarify()` ist standardmäßig `None` (unbegrenzt). **Jede gestellte Frage ist eine Runde** — der Wert 16 bedeutet also „höchstens gut ein Dutzend Fragen", und das greift **still**: Auf der Kanalseite steht weiterhin `max_asks=None`, also „unbegrenzt", und niemand sieht, wer die Fragen abgewürgt hat. Um Rückfragen wirklich freizugeben, müssen **beide Defaults auf `None` bleiben**: `HumanChannel.max_asks` und `clarify(max_turns=...)`.

### Wo der Brief landet: zwingend in der eingehängten Workbench

Der Workbench-Index wird in den System-Prompt injiziert; der Koordinator weiß also von Anfang an, wo die Anforderungsdatei liegt, und muss beim Verteilen der Arbeit nur den Pfad weitergeben, statt den Inhalt in den [Task Brief](../reference/glossary.md#任务书) zu kopieren.

!!! warning "Der Index reicht nur bis zum Koordinator"
    Ein subagent hat seinen eigenen System-Prompt und **erbt** den sessionweiten Teil **nicht** (gemessen mit **$0.2461**, `tests/prelude_live.py`). Es heißt also „der Koordinator gibt den Pfad weiter", nicht „jeder subagent weiß es automatisch".

Entscheidend ist, **welche** Workbench. Nur eine Schreibweise ist korrekt: selbst anlegen, dann an den `Workflow` hängen und das Treiberprogramm dasselbe Objekt an die `Runtime` übergeben lassen.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← einhängen
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Zwei falsche Varianten, die beide **keinen Fehler werfen** und deshalb besondere Vorsicht verlangen:

```python
# ✗ Pfad selbst zusammenbauen: relativ zum Prozess-cwd — und das ist ein anderes Verzeichnis als
#   das <run_dir>/workbench, das Runtime(workbench=True) anlegt. Der Brief landet in A,
#   der injizierte Index scannt B —— die obige Zusage fällt still aus.
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ Rückwärts aus der Runtime holen: über cli.py unmöglich. Sie ruft zuerst main() auf,
#   um den Workflow zu bauen, und erzeugt erst danach die Runtime —— zu dem Zeitpunkt
#   ist brief_path längst fixiert.
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

Wer einen eigenen Treiber schreibt (also nicht über `cli.py` geht), legt zuerst die `Workbench` an und gibt **dasselbe Objekt** sowohl an `Workflow(workbench=wb)` als auch an `Runtime(workbench=wb)`. Punkt 5 von `tests/trial_offline.py` assertet direkt, dass der Brief in `prompt_block()` auftaucht; Punkt 11 bestätigt, dass diese Assertion die Regression auch fängt.

### Verifikationsstand

**Offline alles grün** (`tests/clarify.py`, **52 Punkte**, kostenlos): die fünf Semantiken des Rückfragekanals (blockierend auf Antwort warten / Kontingent erschöpft / Timeout ins Leere / Überspringen / threadübergreifend antworten), das Parsen der vier Abschnitte (inklusive einer Probe mit eingeklebtem Code), dass die `clarify()`-Rolle **keine** Schreibwerkzeuge hat, und die drei Einhängepunkte von `clarify_step`.

**Der CLI-Pfad läuft offline durch**: vollständigen Brief vorbelegen → erster Schritt wird übersprungen → Kanal hängt sich automatisch an den stdin-Thread → Brief wird in `ctx` gelegt → sauberer Exit.

**Kein Lauf gegen die echte API.** Die Sonde für $0.8908 war ein **echter Request**, aber sie hat getestet, was ein unbeschränkter Clarifier tut, nicht diesen Pfad in seiner heutigen Form.

## Wann man es nicht verwenden sollte

**Die Anforderung ist bereits eingefroren.** Steht die Anforderung in einer Datei, kommt sie von einem vorgelagerten System, oder ist es ohnehin ein erneuter Lauf derselben Sache — dann gibt es nichts zu fragen. Den Anforderungstext direkt in den Arbeitsschritt geben, oder `clarify_step` stehen lassen und es per `when` überspringen (existiert der Brief, fragt es ohnehin nicht).

**Es ist niemand da, den man fragen könnte, und du willst nicht, dass es rät.** Bei `timeout_s=0` laufen alle Rückfragen sofort ins Leere und der vierte Abschnitt füllt sich mit selbst erfundenen Annahmen — so ist es entworfen, aber die Verlässlichkeit dieses Briefs ist dann exakt die Verlässlichkeit dieser Annahmen. In CI ist `max_asks=0` sauberer (Fragen explizit verboten), und die Anforderung kommt vollständig von außen.

**Kleine Einmalaufgaben.** Der Klärungsschritt kostet selbst Geld: In [HT002](../cases/ht002.md) hat für „ein Repository klonen, unter macOS installieren und zum Laufen bringen" allein die Anforderungsklärung **$0.5306 / 9 Runden / 0.10h** gekostet. Je kleiner die Aufgabe, desto unschöner der Anteil dieses Schritts. Der Einzelagent-Pfad `flower once` enthält ihn nicht.

**Beim Ändern der Anforderung sollte kein neuer Dialog stattfinden.** Der Brief ist ein eingefrorenes Artefakt; ab dem Moment, in dem er auf der Platte liegt, ist die Datei maßgeblich — richtig ist also, **diese Datei zu ändern**. `--clarify-only` ist in einem bereits geklärten Verzeichnis eine **Nulloperation** (dieser Workflow besteht nur aus diesem einen Schritt, und der wird übersprungen); für eine neue Klärung braucht es zusätzlich `--new`, oder beim eigenen Verdrahten `always_ask=True`.

**Es entscheidet nicht, ob etwas fertig ist.** Das ist eine andere Schicht, siehe [Goal Guard](goal.md). Die Vorabklärung blockt „das Gebaute ist nicht das Gewollte", sie blockt nicht „es heißt fertig, ist aber nicht fertig".
