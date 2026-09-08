# Clarify

Vor dem Anfangen erst die Anforderung klären. Der [Clarifier](../reference/glossary.md#确认者) ist eine Rolle, die nur fragt und nichts anfasst — sie fragt so lange, bis es klar ist, und gibt am Ende einen [Brief](../reference/glossary.md#需求确认书) aus, der aus genau vier Abschnitten besteht und auf Platte eingefroren wird. Jeder nachfolgende [Schritt](../reference/glossary.md#步骤) beginnt mit dem Lesen dieses Dokuments und rät die Anforderung nicht neu — und dieser Frage-Antwort-Verlauf ist **nie** in den Kontext der nachgelagerten Schritte gelangt.

## Welches Problem das löst {#解决什么问题}

Alle Mittel, mit denen flower Kontext aufräumt, räumen nur den **Arbeitsstand** auf: abgelaufene Aktualität, entfernte abgelehnte Aufrufe, entfernte Fehlermeldungen, große Ergebnisse per [Spill](../reference/glossary.md#落盘) auf Platte. Arbeitsstand zu verlieren ist unkritisch — ein erneuter Lauf erzeugt ihn wieder.

Eine Fehlerklasse ist anders: **das Ziel falsch verstanden**. Es ist die einzige Fehlerklasse, die durch das Aufräumen des Kontexts **schlimmer** wird. Nachdem der Arbeitsstand weg ist, bleibt genau die Entscheidung übrig, die auf der falschen Prämisse steht — und sie sieht exakt aus wie eine richtige Entscheidung. Nichts deutet darauf hin, dass ihre Prämisse fragwürdig ist.

[Long-horizon](../reference/glossary.md#长程) verstärkt das bis zum Schlimmsten: Die falsche Prämisse läuft erst mehrere Stunden, schickt ein Dutzend [Subagents](../reference/glossary.md#subagent) los, legt einen Haufen Artefakte auf Platte ab — und fliegt erst danach auf. Teuer sind zu diesem Zeitpunkt nicht die Token, sondern dass **jedes einzelne Artefakt auf die falsche Anforderung gebaut wurde**. Die Abrechnung von [HT001](../cases/ht001.md) gibt dieses Verhältnis her: der Schritt, der die Anforderung klärt, **$0.3704 / 5 Runden / 0.06h**, der Schritt, der danach arbeitet, **$171.2476 / 31 Runden / 10.44h**.

Also braucht es einen Kanal, über den das System „anhalten und fragen" kann — und der muss **vor** dem Arbeitsbeginn liegen.

## Wie man es benutzt (minimaler Code) {#怎么用最小代码}

### Ohne Code: Kommandozeile {#零代码命令行}

Ins Projektverzeichnis wechseln und direkt starten:

```bash
cd /path/to/your/project
flower
```

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Im Terminal sehen die Fragen so aus:

```text
  ? 这个工具是给命令行用,还是要有 Web 界面?
     1) 纯命令行
     2) Web 界面
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
```

- **Nummer** eingeben, um eine Option zu wählen, oder frei antworten
- **Enter = überspringen**; das Modell entscheidet selbst und schreibt die Annahme in „Unbekanntes und Annahmen"
- Nur mit allen vier Abschnitten geht es weiter; der Brief wird in `.flower/notes/需求.md` eingefroren
- **Ein erneuter Lauf fragt nicht noch einmal alles ab** — für eine erneute Klärung die Datei löschen oder `--new` ergänzen

Nur sehen, was es fragt, ohne weiterzuarbeiten: `flower --clarify-only`. Hartes Kontingent für Fragen: `--asks 12` (nur wenn gesetzt, erscheint unter den Optionen eine zusätzliche Zeile `(还能问 N 次)`; per Default gibt es kein Limit und die Zeile fehlt). Niemand sitzt davor: `--timeout 0`. Die Implementierung dieses Pfads steht in [`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "Antworten laufen über stdin — in einem echten Terminal ausführen"
    In Pipes, unter `nohup` oder in CI kann niemand antworten: Sobald stdin EOF liest, gilt die gerade wartende Frage als „Eingabe geschlossen" und wird übersprungen; jede weitere Frage wartet danach das volle `--timeout` ab. In solchen Fällen direkt `--timeout 0` setzen — alle Fragen laufen sofort ins Leere, das Modell entscheidet selbst und schreibt die Annahmen in „Unbekanntes und Annahmen".

### Selbst verdrahten {#自己接线}

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # per Default keine Obergrenze für Fragen, wartet 30 Minuten auf Menschen
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

In `prompt` steht nur **dein** ursprüngliches Anliegen, ein Satz reicht. Was gefragt wird, entscheidet der Clarifier selbst — welche Fragen in deiner Domäne zu stellen sind, weiß das Framework nicht und soll es auch nicht wissen. Das `协调者` oben ist ein `AgentSpec`, das du selbst mit `coordinator()` gebaut hast, siehe [Workflow entwerfen](workflow.md).

Die Parameter von `clarify_step()`:

| Parameter | Default | Bedeutung |
|---|---|---|
| `channel` | — | `HumanChannel`. **Dieselbe Instanz** muss auch an `Workflow(channel=...)` hängen |
| `brief_path` | — | Wohin der Brief geschrieben wird. Muss in der [Workbench](../reference/glossary.md#工作台) liegen, die eingehängt ist, siehe unten |
| `prompt` | — | Dein ursprüngliches Anliegen. `str` oder `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Schrittname, zugleich Schlüsselname in `ctx` |
| `spec` | `None` | Eigenes `AgentSpec`; wenn gesetzt, wird `clarify()` nicht mehr verwendet |
| `instructions` | `""` | Domänenanweisungen, die hinter `CLARIFIER_RULES` angehängt werden |
| `always_ask` | `False` | `True` = jedes Mal neu klären (beim Ändern der Anforderung) |
| `on_fail` | `"stop"` | Verhalten bei unvollständigen vier Abschnitten, wie `Step.on_fail` |
| `retries` | `0` | Anzahl der Wiederholungen bei unvollständigen vier Abschnitten |
| `**spec_kw` | — | Durchgereicht an `clarify()`: `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

Nach dem Lauf stehen drei Dinge in `ctx`:

```python
ctx["确认需求"]     # str, kompakte Fassung der vier Abschnitte (prompt_block), direkt in den Downstream-Prompt einsetzbar; Schlüsselname = Schrittname
ctx[BRIEF_KEY]     # "_brief" —— Brief-Objekt, für den abschnittsweisen Zugriff
ctx[MISSING_KEY]   # "_brief_missing" —— nur vorhanden, wenn die vier Abschnitte unvollständig sind: welche fehlen, zur Anzeige in der UI
```

Wenn es nicht rund läuft, zuerst an diesen Stellschrauben drehen:

| Symptom | Woran drehen |
|---|---|
| Fragt zu viel, zu kleinteilig | `max_asks` ein hartes Kontingent geben; in `instructions` schreiben, was in deiner Domäne selbstverständlich ist |
| Fängt nach zu wenigen Fragen an | In `instructions` benennen, welche Punkte es zwingend klären muss (die Anzahl ist per Default ohnehin unbegrenzt, am Kontingent zu drehen bringt nichts) |
| Die vier Abschnitte werden lieblos gefüllt | In `instructions` ein Beispiel aus deiner eigenen Domäne geben |
| Niemand sitzt davor, es hängt trotzdem | `timeout_s=0` |
| Jedes Mal neu klären | `always_ask=True`, oder die Brief-Datei löschen |

## Was es tatsächlich tut {#它实际做了什么}

### Auslösezeitpunkt: drei Einhängepunkte, kein einziges neues Feld {#触发时机三处接线一个新字段都没加}

Was `clarify_step()` baut, ist ein ganz normaler `Step` — nur mit drei ausgefüllten Callbacks:

| Wo eingehängt | Wann es läuft | Was es tut |
|---|---|---|
| `Step.when` | Vor dem Betreten dieses Schritts | Existiert der Brief bereits vollständig mit vier Abschnitten, wird der Schritt **übersprungen** und der Brief in `ctx` gelegt |
| `Step.gate` | Nach Ablauf dieses Schritts, bevor das Ergebnis nach unten geht | Sind die vier Abschnitte unvollständig, **geht es nicht weiter**; sind sie vollständig, `write()` — **einfrieren** |
| `Step.reduce` | Nach dem Bestehen | Gibt die **geparsten vier Abschnitte** nach unten weiter, nicht den Originaltext des Modells |

**Auch beim Überspringen wird `ctx` gefüllt.** Das wird leicht übersehen: Gibt `when` `False` zurück, führt `Workflow` diesen Schritt nicht aus und schreibt entsprechend auch kein `ctx[step.name]` — deshalb legt `clarify_step` den vorhandenen Brief bereits in `when` hinein. Sonst bekämen die nachgelagerten Schritte beim erneuten Lauf einen `KeyError`.

`reduce` reicht `Brief.prompt_block()` weiter und nicht den Originaltext des Modells, weil im Originaltext zusätzliches Zeug stecken kann (in der Praxis klebt es schon mal den kompletten Code in die Antwort).

Bei [Continuity](../reference/glossary.md#接续) beginnt dieser Schritt mit einem anderen Satz — `CLARIFY_RESUME`: „Mach mit der eben abgebrochenen Anforderungsklärung weiter — **fang nicht von vorn an** …". Ohne diesen Satz schickt die Fortsetzung das ursprüngliche Anliegen als neue Aufgabe erneut los, und der Clarifier stellt womöglich bereits gestellte Fragen noch einmal.

### Abgrenzung: Der Frage-Antwort-Verlauf kommt nicht in den nachgelagerten Kontext {#边界问答不进下游的上下文}

```text
确认需求        独立会话  ────→  磁盘上一份冻结的四段确认书
                                          │
干活(下一步)   新会话(resume_from=None)◄─┘   只拿到那四段
```

Das `resume_from` von `clarify_step` bleibt auf dem Default `None`, deshalb ist der nächste Schritt eine **neue Session**, die nur den Brief bekommt. Dieser Frage-Antwort-Verlauf ist **nie** in den Kontext des [Koordinators](../reference/glossary.md#协调者) gelangt — nicht „hineingekommen und dann weggeschnitten". Der Unterschied ist substanziell: Weggeschnittenes liegt weiterhin in `sessions.db` und kann per Resume zurückkommen; was nie drin war, hat dieses Problem nicht.

Der Frage-Antwort-Verlauf selbst wird **an `log_path` angehängt**. Diese Kopie belegt keinen Kontext, ist von Compact nicht betroffen und existiert auch auf einer anderen Maschine noch — dieselbe Idee wie bei der Workbench.

### Jeder der vier Abschnitte hält eine Fehlerklasse auf {#四段各挡一类失败}

| Abschnitt | Was drinsteht | Was passiert, wenn er fehlt |
|---|---|---|
| **Ziel** | Ein Satz: was gebaut wird, für wen | Es entsteht etwas anderes |
| **Abnahmekriterien** | Entscheidbare Bedingungen, eine pro Zeile. „Fertig" zählt nicht, „`x` ausführen ergibt `y`" zählt | Niemand kann entscheiden, ob es „fertig" ist |
| **Abgrenzung** | **Was ausdrücklich nicht gemacht wird** | Scope Creep. Dieser Abschnitt hält später **jeden einzelnen** Subagent im Zaum |
| **Unbekanntes und Annahmen** | Was nicht gefragt wurde, was ins Timeout lief, was geraten wurde — eine pro Zeile | **Falsche Prämissen werden stillschweigend zugeschüttet** |

Der vierte Abschnitt ist die Sicherung für den Long-horizon-Lauf. Egal welcher der ersten drei Abschnitte falsch ist: Solange die Annahme explizit im vierten Abschnitt steht, hat, wer sie liest, die Chance einzugreifen. Ist sie zugeschüttet, merkt man es erst Stunden später, wenn alle Artefakte für die Tonne sind. Falsche Prämissen lassen sich nicht vollständig vermeiden, aber man kann sie **explizit** machen.

Nur mit allen vier Abschnitten geht es weiter; welcher fehlt, meldet `Brief.missing()` — es liefert die chinesischen Abschnittsnamen zurück, die sich direkt anzeigen lassen.

Das Parsen ist sehr tolerant gegenüber der Schreibweise: `## 目标` / `**目标**` / `目标:` / `3. 边界` werden alle erkannt, ebenso Text direkt hinter der Überschrift (`目标: 做一个 X`) und die üblichen Aliasse (`验收条件`→验收标准、`不做什么`→边界、`未知项与假设`→未知与假设); kommt ein Abschnitt mehrfach vor, gilt der erste mit Inhalt. Zwei Ausnahmen muss man kennen:

- `Brief.parse()` **entfernt zuerst umzäunte Codeblöcke** und wirft ab einem **nicht geschlossenen** Zaun den kompletten Rest weg. Wird die Modellausgabe abgeschnitten, lassen sich alle folgenden Abschnitte nicht mehr parsen → vier Abschnitte unvollständig → `gate` schickt es zurück.
- `Brief.load()` behandelt `"(未填)"` als leer. Wer beim manuellen Editieren des Briefs den Platzhaltertext aus `to_markdown()` stehen lässt, hat diesen Abschnitt weiterhin als fehlend.

### Abgrenzung: Was der Clarifier anfassen darf {#边界确认者能碰什么}

Ein **unbeschränkter** Clarifier ist einmal gelaufen (`/tmp/probe_ask.py`, **$0.8908 / 230 Sekunden**): Nach zwei Fragen **fing er direkt an, Code zu schreiben**; als die Berechtigungsschicht ihn stoppte, **klebte er den kompletten Code in den Antworttext**. „Schreib keinen Code" im Prompt hält das nicht auf — genau so etwas stand damals in seinem System-Prompt. Deshalb gibt es zwei Mechanismen:

**Erstens: ein Hook, der seine Schreibwerkzeuge abfängt.** Die Freigabeliste von `clarify()` ist `mcp__human__ask` plus (bei `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch`, ohne `Write` / `Edit` / `Bash` / `Agent`. Durchgesetzt wird das vom `whitelist_guard`, den die `Runtime` automatisch installiert: Er leitet aus der Freigabeliste ab, welche der Werkzeuge `Bash` / `Write` / `Edit` / `NotebookEdit` zu blockieren sind, und antwortet bei einem Treffer mit `deny`. Es ist nicht „gebeten, nicht zu arbeiten", sondern **es kann nicht arbeiten**.

Lesen zu erlauben lohnt sich: Ein Blick ins Repo spart mehrere Fragen, und diese Session wird nach Gebrauch weggeworfen — dass sie sich beim Lesen zumüllt, ist egal (`can_read=False` nimmt ihr auch das Lesen).

**Das muss ein Hook sein, `allowed_tools` allein reicht nicht.** Letzteres ist eine **Freigabeliste, keine exklusive Whitelist** — das Modell kann Werkzeuge, die nicht darin stehen, trotzdem aufrufen. Zwei weiterhin gültige Messbelege:

- In [HT002](../cases/ht002.md) hat der [Judge](../reference/glossary.md#判定者) im Schritt „Ziel setzen" tatsächlich **11-mal `Bash`** ausgeführt, obwohl `judge()` per Default `can_run=False` setzt und `Bash` gar nicht auf der Liste steht (in jenem Lauf gab es diesen Hook noch nicht — heute würde derselbe Aufruf vom `whitelist_guard` auf der Stelle mit `deny` beantwortet, was genau zeigt, dass ihn der Hook stoppt und nicht die Liste).
- **Die $0.1-Sonde**: Ein Agent mit `allowed_tools=["Read"]` soll eine Datei schreiben — `Write` wird von der Berechtigungsschicht abgelehnt (`"requested permissions to write ... but you haven't granted it yet"`), `Bash` von der Pfadsicherheit (`"Output redirection was blocked. For security, Claude Code may only write to files in the allowed working directories"`). **Der Aufruf ging raus**, andere Schichten haben ihn gestoppt.

`clarify()` setzt `permission_mode` nicht explizit und erbt den `AgentSpec`-Default `"default"`. `coordinator()` steht per Default auf `"acceptEdits"` — wer diesen Wert an den Clarifier durchreicht, hat diesen Schutz verloren.

**Zweitens: Das Framework parst nur diese vier Abschnitte und wirft alles andere weg.** `Brief.parse()` entfernt erst umzäunte Codeblöcke und sucht dann die Überschriften — eingeklebter Code kommt also nicht nach unten durch. Das ist die letzte Schleuse gegen „es verschmutzt die nachgelagerten Schritte".

### Abgrenzung: der Frage-Kanal {#边界提问通道}

Das Frage-Werkzeug auf Modellseite heißt `mcp__human__ask` (Parameter `question`, optional `options`). `HumanChannel` ist ein prozessinterner MCP-Server und **registriert zwei Werkzeuge** — `mcp__human__ask` und `mcp__human__inbox`; in der Freigabeliste des Clarifiers steht nur das erste (der Posteingang ist für den Koordinator).

```python
HumanChannel(
    on_event=None,        # Callback für Push-UIs. Am Workflow eingehängt, verbindet Workflow.run es automatisch
    max_asks=None,        # per Default keine Obergrenze
    timeout_s=1800.0,     # 30 Minuten. None = ewig warten; <= 0 = vollautomatisch
    log_path=None,        # Fragen und Antworten werden an diese Datei angehängt, ohne Kontext zu belegen
    amend_path=None,      # Was der Mensch während des Laufs sagt, wird an diese Datei angehängt (üblicherweise der Brief)
    over_budget_text=..., timeout_text=..., declined_text=...,   # Formulierungen für die drei Arten des Ins-Leere-Laufens
)
```

Der Normalfall für Long-horizon-Agents ist, dass **niemand zusieht** — deshalb muss „anhalten und auf einen Menschen warten" elegant scheitern können:

| Einstellung | Verhalten |
|---|---|
| `timeout_s=1800.0` (Default) | Wartet eine halbe Stunde; danach kommt ein erklärender Satz zurück, **kein Fehler** |
| `timeout_s=None` | Wartet ewig. Nur benutzen, wenn sicher jemand davorsitzt (die CLI kann diesen Wert nicht setzen, `--timeout` ist ein float) |
| `timeout_s=0` (negativ ebenso) | **Vollautomatisch**: Alle Fragen laufen sofort ins Leere, es wird kein Warten vorgetäuscht |
| `max_asks=None` (Default) | **Keine Obergrenze** — wie oft gefragt wird, entscheidet der Clarifier selbst |
| `max_asks=N` | Hartes Kontingent. Darüber hinausgehende Fragen werden vom Werkzeug **direkt abgelehnt**, ohne zu blockieren und ohne Fehler |
| `max_asks=0` | Fragen verboten (CI / unbeaufsichtigt) |

`remaining` liefert bei `max_asks=None` den Wert `-1` (nicht 0 und nicht unendlich); das Terminal blendet daraufhin „noch N Fragen möglich" nicht ein.

Der Wortlaut, der beim Timeout zurückkommt:

> Niemand hat geantwortet. Mach nach eigenem Ermessen weiter und schreibe diese Frage samt der von dir gewählten Annahme in den Abschnitt „Unbekanntes und Annahmen". Frage nicht noch einmal und bleib hier nicht stehen.

Alle drei Arten des Ins-Leere-Laufens (Timeout / Kontingent aufgebraucht / Mensch überspringt aktiv) zielen auf dieselbe Handlung: **die Annahme in den vierten Abschnitt schreiben**. Genau deshalb steht im unbeaufsichtigten Betrieb trotzdem etwas im vierten Abschnitt, und genau deshalb kann der Long-horizon-Lauf weiterlaufen. Ein Kontingent im Prompt ist eine Empfehlung, **erst das Zählen im Kanal ist eine Garantie**.

Eine in der Praxis überprüfte Eigenschaft des Mechanismus: In einem prozessinternen MCP-Tool-Handler auf ein externes Future zu `await`en **führt nicht zum Deadlock** — während der Handler hängt, dreht sich der Event-Loop weiter, und eine andere Task oder **ein anderer Thread** kann die Antwort einspeisen. Deshalb lassen sich `answer()` / `decline()` direkt aus einem Web-Backend oder einem TUI-Eingabethread aufrufen (intern über `loop.call_soon_threadsafe`); das ist der Normalfall, kein Randfall. Ausnahmen aus UI-Callbacks werden in `ui_errors` gesammelt und **unterbrechen den Lauf nicht** — ein abgestürztes Frontend soll nicht drei Stunden Arbeit mitreißen. Die vollständige Mitgliederliste steht in der [Python-API](../reference/api.md).

!!! warning "`max_turns` zu klein gesetzt, und »fragen, bis es klar ist« wird zur leeren Phrase"
    Der Default von `max_turns` in `clarify()` ist `None` (unbegrenzt). **Jede gestellte Frage ist eine Runde** — 16 bedeutet also „höchstens gut ein Dutzend Fragen", und es greift **still**: Auf der Kanalseite steht `max_asks=None` weiterhin auf „keine Obergrenze", man sieht nicht, wer abgewürgt hat. Wer das Fragen freigeben will, muss **beide Defaults auf `None` lassen**: `HumanChannel.max_asks` und `clarify(max_turns=...)`.

### Wo der Brief landet: zwingend in der eingehängten Workbench {#确认书落在哪必须是挂上去的那个工作台}

Der Workbench-Index wird in den System-Prompt injiziert; der Koordinator weiß von Anfang an, wo die Anforderungsdatei liegt, und muss beim Verteilen von Arbeit nur den Pfad weitergeben, statt den Inhalt in den [Task Brief](../reference/glossary.md#任务书) zu kopieren.

!!! warning "Der Index reicht nur bis zum Koordinator"
    Subagents haben ihren eigenen System-Prompt und **erben** den sessionweiten Teil **nicht** (gemessen: **$0.2461**, `tests/prelude_live.py`). Es heißt also „der Koordinator gibt den Pfad weiter", nicht „jeder Subagent weiß es automatisch".

Entscheidend ist, **welche** Workbench. Nur eine Schreibweise ist richtig: selbst anlegen, dann an den `Workflow` hängen und das Treiberprogramm dasselbe Objekt an die `Runtime` geben lassen.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← eingehängt
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Zwei falsche Varianten, beide **ohne Fehlermeldung** — deshalb besondere Vorsicht:

```python
# ✗ Pfad selbst zusammenbauen: relativ zum cwd des Prozesses; das ist ein anderes Verzeichnis
#   als das <run_dir>/workbench, das Runtime(workbench=True) anlegt. Der Brief landet in A,
#   der injizierte Index scannt B —— die Zusage von oben verpufft still.
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ Sie rückwärts aus der Runtime holen wollen: über cli.py unmöglich. Es ruft erst main()
#   auf, um den Workflow zu bauen, und erzeugt danach erst die Runtime —— zu dem Zeitpunkt
#   steht brief_path längst fest.
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

Wer den Treiber selbst schreibt (also nicht über `cli.py` geht), legt zuerst die `Workbench` an und gibt **dasselbe Objekt** an `Workflow(workbench=wb)` und `Runtime(workbench=wb)`. Punkt 5 in `tests/trial_offline.py` prüft direkt per Assertion, dass „der Brief in `prompt_block()` auftaucht", Punkt 11 bestätigt, dass diese Assertion die Regression tatsächlich fängt.

### Welche Prüfungen gelaufen sind und welche nicht {#验证状态}

**Offline alles grün** (`tests/clarify.py`, **52 Punkte**, kostenlos): die fünf Semantiken des Frage-Kanals (blockierend auf Antwort warten / Kontingent aufgebraucht / Timeout ins Leere / überspringen / Antwort über Threadgrenzen), das Parsen der vier Abschnitte (inklusive eines Samples mit „hat Code hineingeklebt"), dass die `clarify()`-Rolle **keine** Schreibwerkzeuge hat, sowie die drei Einhängepunkte von `clarify_step`.

**Der CLI-Pfad läuft offline durch**: einen vollständigen Brief vorlegen → erster Schritt wird übersprungen → der Kanal verbindet sich automatisch mit dem stdin-Thread → der Brief landet in `ctx` → sauberer Exit.

**Gegen die echte API nicht gelaufen.** Die Sonde für $0.8908 war ein **echter Request**, sie hat aber getestet, was ein unbeschränkter Clarifier tut, nicht diesen Pfad in seiner heutigen Form.

## Wann man es nicht benutzen sollte {#什么时候不该用它}

**Die Anforderung ist bereits eingefroren.** Steht die Anforderung in einer Datei, kommt sie von einem vorgelagerten System, oder ist dieser Lauf schlicht die Wiederholung derselben Sache — dann gibt es nichts zu fragen. Den Anforderungstext direkt in den Arbeitsschritt geben, oder `clarify_step` stehen lassen und über `when` überspringen lassen (existiert der Brief, fragt es ohnehin nicht).

**Es ist niemand da, den man fragen könnte, und du willst nicht, dass es rät.** Bei `timeout_s=0` laufen alle Fragen sofort ins Leere, und der vierte Abschnitt füllt sich mit lauter eigenen Annahmen — so ist es entworfen, aber die Glaubwürdigkeit dieses Briefs entspricht dann genau der Glaubwürdigkeit dieser Annahmen. In CI ist `max_asks=0` (Fragen ausdrücklich verboten) die sauberere Variante, mit vollständig von außen gegebener Anforderung.

**Kleine Einmalaufgaben.** Der Klärungsschritt selbst kostet Geld: In [HT002](../cases/ht002.md) hat für eine Sache wie „ein Repo clonen, unter macOS installieren und zum Laufen bringen" die Anforderungsklärung **$0.5306 / 9 Runden / 0.10h** gekostet. Je kleiner die Aufgabe, desto schlechter sieht der Anteil dieses Schritts aus. Der Einzel-Agent-Pfad `flower once` enthält diesen Schritt nicht.

**Beim Ändern der Anforderung soll man nicht neu dialogisieren.** Der Brief ist ein eingefrorenes Artefakt; ab dem Moment des Ablegens ist die Datei maßgeblich — richtig ist, **diese Datei zu ändern**. `--clarify-only` ist in einem bereits geklärten Verzeichnis eine **Nulloperation** (dieser Workflow besteht nur aus diesem Schritt, und der wird übersprungen); für eine erneute Klärung braucht es `--new`, oder beim Selbstverdrahten `always_ask=True`.

**Es entscheidet nicht, ob etwas „fertig" ist.** Das ist eine andere Schicht, siehe [Goal Guard](goal.md). Clarify hält „es ist nicht das Gewünschte geworden" auf, aber nicht „es behauptet, fertig zu sein, ist es aber nicht".
