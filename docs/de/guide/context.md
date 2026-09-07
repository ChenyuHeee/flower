# Kontextökonomie

Der Kontext des [Main Thread](../reference/glossary.md#主线程) ist das Einzige, was einen [Long-Horizon](../reference/glossary.md#长程)-Lauf von Anfang bis Ende durchzieht; was darin liegt und was nicht, entscheidet, wie weit dieser Lauf kommt. Die Form von flower — der [Koordinator](../reference/glossary.md#协调者) legt nicht selbst Hand an, lange Ausgaben landen auf Platte, Hooks schneiden sofort weg — folgt vollständig aus diesem einen Satz. Diese Seite erklärt, warum.

## Welches Problem das löst

[Compact](../reference/glossary.md#压缩) wartet, bis der Kontext voll ist, und fasst dann rückblickend zusammen — Symptombehandlung. Das eigentliche Problem lautet:
**Kleinkram hat im Main Thread von Anfang an nichts zu suchen.**

Der Unterschied liegt im Zeitpunkt. Die Ausgabe eines `pytest`-Laufs hat schnell zehntausende Zeichen; das Modell schaut einmal hin, zieht eine Schlussfolgerung, und die restlichen Zeichen werden von da an in jeder Runde erneut mitgeschickt; ist das Fenster voll, fasst der Compact sie zusammen mit den daneben liegenden Entscheidungen zu einer Zusammenfassung — gespart wird Volumen, verloren geht „warum wurde das damals so entschieden". Die Auslöseschwelle von auto-compact ist **Fenster − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)),
und in diesem Moment liegen das Wegwerfbare und das Nicht-Wegwerfbare bereits nebeneinander.

flower löst das in vier Schichten, die Reihenfolge ist zugleich die Priorität — sortiert nach Ersparnis:

| Schicht | Was sie tut | Wo |
|---|---|---|
| 1. Arbeitsteilung | Alles Handanlegen geht an [subagent](../reference/glossary.md#subagent), Versuch und Irrtum landen in dessen eigenem Transcript | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. Workbench | Skripte / lange Ausgaben / Entscheidungen auf Platte, Index in den System Prompt injiziert | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. Sofortiges Spill | `PostToolUse`-Hook spillt Tool-Ergebnisse über der Schwelle auf Platte, im Kontext bleibt nur eine Pfadzeile | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. Trim und Prune | Session vor dem resume umschreiben: abgelaufene Ergebnisse, abgelehnte Aufrufe, Verbindungsabbruch-Reste werden nicht mehr zurückgefüttert | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

Die ersten beiden Schichten regeln, **ob etwas überhaupt hereinkommt**, die letzten beiden, **ob das bereits Hereingekommene bleibt**. Die Reihenfolge lässt sich nicht umkehren: Schicht vier kann noch so hart sein, sie holt die Menge nicht wieder ein, die Schicht eins durchgelassen hat.

## Wie man es benutzt (minimaler Code)

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model ist standardmäßig "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

Diese paar Zeilen installieren die ersten drei Schichten: `coordinator()` setzt immer `delegate_only=True` (Schicht eins); `workbench=True` legt die [Workbench](../reference/glossary.md#工作台) an und injiziert den Index in den System Prompt des Koordinators (Schicht zwei) und lässt `Runtime` gleichzeitig `spill_guard` installieren (Schicht drei). Schicht vier ist per Default da — der [Session-Store](../reference/glossary.md#会话存储) von `Runtime` ist fest auf `PruningSessionStore` verdrahtet, die Konstruktorparameter bieten keinen Einstiegspunkt, das zu tauschen.

!!! warning "`workbench=True` ist keine Option"
    Der `delegate_guard`, der den Koordinator vom Handanlegen abhält, hängt in `workbench_hooks`, und `workbench_hooks` wird nur installiert, wenn `Runtime` eine Workbench hat; `whitelist_guard` wiederum wird wegen `delegate_only=True` übersprungen.
    Fazit: **Bei `Runtime(workbench=False)` zusammen mit `coordinator()` steht vor Bash / Write / Edit im Main Thread keine einzige Mauer.**

## Was es tatsächlich tut

### Schicht eins: Arbeitsteilung (spart am meisten)

Der Koordinator spielt „einen Menschen, der Claude Code bedienen kann": zerlegen, delegieren, Berichte lesen, entscheiden. Er bekommt kein Bash / Write / Edit — die Tools sind nur `Agent`, `TodoWrite`, `Read`
(bei `glance=True` zusätzlich ein eingeschränktes `Bash`, siehe unten). Alles Handanlegen geht an
[Worker](../reference/glossary.md#执行者).

**Wann es auslöst**: Jedes Mal, wenn der Main Thread `Bash|Write|Edit|NotebookEdit` aufruft, verweigert der `PreToolUse`-Hook
`delegate_guard` sofort und weist zugleich den Weg — „schick über das Agent-Tool einen subagent los, schreib Ziel und Abnahmekriterien in die Aufgabe und verlang, dass lange Ausgaben nach `.flower/artifacts/` geschrieben werden und die Antwort nur Pfad und Schlussfolgerung enthält". subagents werden ausnahmslos durchgelassen.
Kriterium ist, ob in den Hook-Daten eine `agent_id` steht: **wo keine ist, ist der Main Thread.**

**Wie viel es spart**: Tool-Aufrufe und Versuch und Irrtum eines subagent **landen in dessen eigenem Transcript** (im Session-Store über `subpath` getrennt), im Main Thread bleiben nur dieser eine `Agent`-Aufruf und der Abschlussbericht. Der Trial-and-Error-Verlauf wird nicht wegkompaktiert, er **war nie im Main Thread**.

- Gemessen (eine Aufgabe, die viel Tool-Ausgabe produziert): 83 % des Transcripts liegen im subagent,
  Main Thread 13 Einträge, 21K Zeichen, subagent 105K Zeichen.
- Gemessen (reale Größenordnung, ein Lauf über 10.4 Stunden, siehe [HT001](../cases/ht001.md)): subagents tragen
  **97.7 %** der Runden und **94.8 %** der Fließtextzeichen; 1,893 handanlegende Tool-Aufrufe gegenüber 32 im Main Thread (**59:1**).
  Früher Compact ist damit nicht mehr das Hauptthema.

Die beiden Zeilen sind zwei verschiedene Messungen: oben ein früherer Test in kleinem Maßstab, unten die Nachmessung in realer Größenordnung. Derselbe Mechanismus; je größer der Maßstab, desto mehr spart er.

Gespart wird Kontext, nicht Modellklasse: `worker()` setzt standardmäßig `model="inherit"` — Worker sollen nicht heruntergestuft werden.

Der einzige Gegenposten der Arbeitsteilung ist der [Task Brief](../reference/glossary.md#任务书) — der Text, den der Koordinator beim Delegieren schreibt; er geht in den Main Thread und bleibt dort dauerhaft. Gemessen wiederholten 8/8 Task Briefs Disziplinregeln, die der Gegenseite längst bekannt sind; im kürzesten mit 521 Zeichen waren nur rund 120 Zeichen aufgabenspezifisch, eine Runde verschenkt so etwa 4.8k dauerhaften Kontext. Deshalb steht in `COORDINATOR_RULES` fest verdrahtet:
**Ein Task Brief enthält nur das, was für diese Aufgabe spezifisch ist.** Die einzige Regel, die trotzdem mitgegeben werden muss, ist „wo die Workbench liegt + lange Ausgaben nach `artifacts/` + Antwort nur mit Pfad und Schlussfolgerung" — denn der Workbench-Index erreicht den subagent nicht, der Task Brief ist der einzige Kanal.

### Schicht zwei: Workbench (behebt das „jedes Mal neu schreiben")

Drei Verzeichnisse unter `.flower/` wandern mit dem Workspace mit:

| Verzeichnis | Was hineinkommt | Was es löst |
|---|---|---|
| `scripts/` | Verifikations- / Reproduktionsskripte, die ein zweites Mal laufen, erste Zeile `# desc: ein Satz` | Einmal schreiben, danach direkt ausführen. Kein „nach dem Compact verloren, jedes Mal neu schreiben" mehr |
| `artifacts/` | Lange Ausgaben über 2000 Zeichen: Logs, Daten, Berichte, Diffs | Im Dialog erscheinen nur Pfad und Schlussfolgerung |
| `notes/` | Wichtige Entscheidungen und Begründungen, eine Datei pro Entscheidung | Nach Compact, Neustart oder Maschinenwechsel sind die Schlüsse noch da |

**Wann es auslöst**: `INDEX.md` wird automatisch erzeugt (per Default maximal 40 Einträge), `refresh()` wird vom
`index_guard` in `PostToolUse` aufgerufen, wenn `Write` / `Edit` innerhalb der Workbench landen; außerdem wird vor jedem Schritt einmal aufgefrischt. Die drei obigen Regeln injiziert `prompt_block()` in den System Prompt des Koordinators — er weiß von Anfang an, welche Skripte schon existieren, und muss das nicht erst mit einem Tool-Aufruf herausfinden.

**Wie viel es spart**: Gemessen an einem Lauf über 10.4 Stunden: **61 Skripte wurden 95-mal geschrieben und 331-mal ausgeführt; 92 % liefen mehr als einmal, 0 wurden geschrieben, ohne je zu laufen.** Qualitativ wurde `audit-fake-ai-server.py` von 7 Skripten wiederverwendet.

Diese Schicht wirkt wegen eines Unterschieds: Der Compact räumt den Kontext ab, **aber nicht die Platte und nicht den Index im System Prompt**.

!!! warning "Den Index erbt der subagent nicht"
    Der Index läuft über `system_prompt.append` auf Session-Ebene; ein subagent hat seinen eigenen System Prompt und
    **erbt ihn nicht** (gemessen $0.2461, `tests/prelude_live.py`). Deshalb muss „wo die Workbench liegt + lange Ausgaben nach
    `artifacts/`" vom Koordinator im Task Brief weitergegeben werden — das ist der einzige Kanal, keine Redundanz.

### Schicht drei: Sofortiges Spill

`spill_guard` ist ein `PostToolUse`-Hook, der Tool-Ergebnisse **bevor sie ins Modell gehen** einmal ansieht: Alles über `threshold`
(Default **4000** Zeichen) wird in das `spill/`-Verzeichnis der Workbench [gespillt](../reference/glossary.md#落盘),
im Kontext ersetzt durch eine Zeigerzeile + die **ersten 400 Zeichen**. Der Inhalt ist nicht weg, er ist nur nicht dauerhaft präsent.

**Wann es auslöst**: Der Matcher ist `Bash|Read|Grep|Glob|WebFetch|WebSearch`; `main_only=False` ist Default,
also werden auch Ergebnisse von subagents gespillt. Ersetzt werden nur zu lange **String-Felder** in der Ausgabestruktur des Tools, Listen bleiben ausnahmslos unangetastet
(darin können Bildblöcke stecken), denn `updatedToolOutput` muss die Ausgabestruktur des Originaltools beibehalten.

**Das Lesen der Spill-Datei selbst wird durchgelassen und nicht erneut gespillt.** Sonst wäre der Hinweis in jener Zeile, „für den Volltext mit Read lesen", eine leere Phrase: zurückgelesen, wieder über der Schwelle, wieder gespillt, wieder eine Zeigerzeile — Endlosschleife. Gemessen tatsächlich passiert (`tests/handoff_live.py`, beim ersten echten Lauf); das Modell probierte fünf Schreibweisen zum Umgehen, sagte selbst „The spill read loops back on itself" und quälte sich am Ende in 40-Zeilen-Häppchen durch — sieben, acht Runden verbrannt. Der Sinn des Spill ist, große Dinge **nicht automatisch** in den Kontext zu schieben;
wenn es selbst entscheidet, den Volltext zu lesen, ist das seine Entscheidung.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None oder 0 = Hook wird nicht installiert
```

**Wie viel es spart**: In dem Lauf aus [HT001](../cases/ht001.md) wurden 103-mal gespillt, 791.4K Zeichen durch Pfadzeiger ersetzt, ohne dauerhaft im Kontext zu liegen.

### Schicht vier: Trim und Prune

Diese Schicht sitzt im [Session-Store](../reference/glossary.md#会话存储). Der Store von `Runtime` ist immer ein
`PruningSessionStore` (Vererbungskette `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`); er schreibt in `load()` — also **vor dem resume** — die zurückzufütternde Historie einmal um.
Am Original in SQLite wird kein Zeichen geändert. Vier Dinge:

**① Zeitliche Alterung** (`ephemeral`, Default an). Ergebnisse von [Ephemeral-Kommandos](../reference/glossary.md#一次性命令)
wie `git status`, `ls`, `cat` werden nach ein paar Runden im Fließtext durch einen Hinweis ersetzt,
die letzten 6 bleiben erhalten. Abgelaufene Inhalte werden **nicht gespillt** — ein altes `git status` zu archivieren ist sinnlos, ein erneuter Lauf liefert es wieder:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

Live-Resume gemessen `expired: 2`; auf einem echten Transcript mit `keep_recent` auf 2 laufen 5 Einträge ab.

**② [Trim](../reference/glossary.md#裁剪)** (`trim`, **Default aus**). tool_result-Fließtext ab `>= 2000` Zeichen wird nach `<workspace>/.flower/spill/` gespillt, der Blockinhalt durch einen Dateizeiger ersetzt, die letzten 20 bleiben im Original. Achtung: Dieses Verzeichnis
**ist nicht dasselbe** wie das Spill-Verzeichnis von `spill_guard` aus Schicht drei: Letzteres liegt unter dem Wurzelverzeichnis der Workbench, dieses hier muss im Workspace liegen, sonst kommt das `Read` des Agent nicht daran.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True geht auch
```

**③ [Prune](../reference/glossary.md#剪除) abgelehnter Aufrufe** (`keep_denials`, Default 1). Das Abfangen selbst verschmutzt den Kontext ebenfalls: Die Ablehnungsnachricht ist ein `tool_result` und bleibt zusammen mit dem **nie ausgeführten Kommando** dauerhaft liegen. Gemessen einmal 273 Zeichen (93 Zeichen Ablehnungstext + 180 Zeichen totes Kommando) — das tote Kommando ist teurer als die Ablehnung.

Wichtiger als Token ist, dass es **in die Irre führt**: Gemessen las der Koordinator ein paar Mal „Bash nicht direkt verwenden" und versuchte danach nicht einmal mehr das durchgelassene `git status`, sondern sagte direkt „Bash ist eingeschränkt, schick einen Agent zum Nachsehen" — erlernte Hilflosigkeit, die zusätzlich einen subagent-Start kostet. Default ist 1 statt 0: Die jüngste Ablehnung ist ein nützliches Signal und verhindert, dass das Modell in derselben Runde dasselbe abgefangene Kommando immer wieder probiert. Erkannt wird das an der strukturellen Markierung `toolDenialKind: "permission-rule"`, die die Harness selbst setzt, nicht über Textabgleich — Texte ändern sich jederzeit, Markierungen nicht. Live gemessen: 2 Ablehnungen → 1 entfernt, 1 behalten, Kette intakt, resume normal, und das Modell weiß weiterhin, was passiert ist.

**④ Prune von Verbindungsabbruch-Resten.** Synthetische API-Fehlermeldungen, die während Retries bei Netzabbruch entstehen, werden nicht zurückgefüttert; ein durch Abbruch hinterlassenes `tool_result` wird durch einen neutralen Hinweis ersetzt (`[上一轮在此处被中断,该工具结果未产生]`), der Eintrag selbst bleibt erhalten.

**Rote Linie beim Entfernen**: `tool_use` und sein `tool_result` müssen **zusammen** entfernt werden (fehlt eins, gibt es
`Missing Tool Result Block`), andere Aufrufe in derselben assistant-Nachricht dürfen nicht mitgerissen werden, und die `parentUuid`-Kette muss wieder zusammengefügt werden.

`Runtime(trim=False)` (Default) **heißt nicht, dass gar nichts geräumt wird**: Es schaltet nur das Trimmen großer Ergebnisse ab; Alterung, abgelehnte Aufrufe und Verbindungsabbruch-Reste werden weiterhin bearbeitet.

### Gegenbeispiel: kurz hinschauen macht man selbst

Die ersten drei Schichten sagen alle „delegieren", aber es gibt ein Gegenbeispiel: Kommandos wie `git status`, `ls`, `cat` liefern ein paar Dutzend Zeichen Ergebnis, während **allein der Start eines subagent rund 4.3k Kontext kostet** (gemessen, nicht amortisierbar). Für ein einzelnes `ls` diesen Preis zu zahlen, ist ein Nettoverlust.

Deshalb bekommt der Koordinator ein eingeschränktes Bash zurück (`coordinator(..., glance=True)`, Default an). Das Kriterium ist nicht „das Kommando ist kurz", sondern **ob das Ergebnis altert**, und über „durchlassen" und „altern" entscheidet dieselbe Funktion `is_ephemeral()`:

| | Selbst ausführen erlaubt | Ergebnis wird als abgelaufen markiert |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ delegieren | — |

Beide Seiten müssen dieselbe Tabelle sein, sonst schadet jede für sich allein: **durchgelassen, aber nicht getrimmt** — dann belegt ein abgelaufenes `git status` dauerhaft Kontext und führt als vermeintlicher Ist-Zustand Entscheidungen in die Irre; **getrimmt, aber nicht durchgelassen** — dann zahlt der Koordinator für ein `ls` 4.3k.
`tests/glance.py` nagelt diese Invariante als Assertion fest — gemessen an 46 Kommandos stimmen beide Seiten vollständig überein, inklusive 10 adversarialer Fälle.

**Falle (zweimal hineingetappt)**: Das Modell schreibt keine einzelnen Kommandos, es schreibt
`git status -s && echo "--- LOG ---" && git log --oneline -10`. Die erste Version lehnte pauschal alles ab, was
`&&` / `|` / `2>&1` enthielt, Ergebnis: **glance war komplett wirkungslos** — gemessen wurden alle drei Versuche des Koordinators abgefangen, er musste doch wieder einen subagent schicken. Jetzt wird segmentweise zerlegt und geprüft: Nur wenn jedes Segment auf der Whitelist steht, wird durchgelassen; `git status && rm -rf x` wird weiterhin abgefangen
(die hintere Hälfte steht nicht in der Tabelle).

### Append, nicht ersetzen

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Wenn `build_options()` eine `AgentSpec` in SDK-Optionen kompiliert, läuft `instructions` über
[`append`](../reference/glossary.md#叠加) — angehängt **hinter** den nativen System Prompt von Claude Code,
nicht als Ersatz. Die Disziplintexte oben (`COORDINATOR_RULES`, `WORKER_RULES` usw.) sind also additiv:
**Spezialisierung geht nicht auf Kosten der Allgemeinfähigkeiten.**

Der Workbench-Index läuft über denselben Kanal. Er ist in jeder Runde da, aber als Teil des System Prompt belegt er keine Dialoghistorie, und der Compact räumt ihn auch nicht ab — der Preis ist der oben genannte: **nur bis zum Koordinator**.

!!! warning "Nicht `disallowed_tools` benutzen, um den Koordinator vom Handanlegen abzuhalten"
    `disallowed_tools` ist **session-weit** und sperrt subagents mit aus. Gemessene Fehlermeldung im Original:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    Richtig geht es in zwei Schritten: in `allowed_tools` nicht aufnehmen und dann per `PreToolUse`-Hook anhand der `agent_id` nur den Main Thread abfangen.
    `coordinator()` macht genau das — es setzt `delegate_only=True`, der `delegate_guard` fängt den Main Thread ab und lässt subagents durch.

    Nur auf `allowed_tools` zu setzen reicht ebenfalls nicht: Das ist eine **Freigabeliste ohne Nachfrage, keine exklusive Whitelist**. Gemessen kann das Modell Tools aufrufen, die nicht darin stehen — in einer Sonde für $0.1 rief ein Agent mit `allowed_tools=["Read"]` problemlos Write / Bash auf.
    Was tatsächlich abfängt, ist der Hook.

## Wann man es nicht benutzen sollte

Was diese vier Schichten sparen, ist immer das **Rohmaterial**. Die folgenden Probleme lösen sie nicht, manche werden durch sie sogar schwerer sichtbar:

1. **Ein falsch verstandenes Ziel — diese vier Schichten machen es schlimmer.** Nachdem das Rohmaterial weggeworfen ist, bleibt genau die Entscheidung übrig, die auf der falschen Prämisse aufbaut, und sie **sieht exakt aus wie eine richtige Entscheidung**. Long-Horizon vergrößert das aufs Schlimmste: Die falsche Prämisse läuft erst ein paar Stunden, schickt ein Dutzend subagents los, legt einen Haufen Artefakte auf Platte, und erst danach fliegt sie auf. Dann sind nicht die Token teuer, sondern dass jedes Artefakt gegen die falschen Anforderungen gebaut wurde. Dagegen hilft die [Vorab-Klärung](clarify.md), keine der Schichten auf dieser Seite.
2. **Der Main Thread wächst weiterhin monoton.** Die vier Schichten drücken die Steigung, nicht die Richtung. Gemessen: Der Main Thread wuchs über 70 Runden von 28.7K auf 185.9K, Steigung 2.2K/Runde, durchgehend ohne Compact, 18.6 % eines 1M-Fensters verbraucht, **extrapoliert rund 440 Runden bis zur Wand**. Über diese Wand kommt man mit [Handoff](handoff.md).
3. **Nach dem Abschalten des vollen Compact gibt es kein Netz.** Bei aktivem Handoff setzt `Runtime` der Spec zwingend
   `CompactPolicy(mode="no_summary")`, womit auto-compact aus ist (gibt die Spec `compact` selbst explizit an, wird das respektiert). Ans Limit zu laufen ist ein harter Fehler, deshalb müssen diese vier Schichten zusammen mit dem Handoff eingesetzt werden — Compact einfach nur abzuschalten reicht nicht.
4. **Schicht vier wirkt nur beim resume.** Trim und Prune passieren beide in `load()`; eine durchlaufende Session wird dadurch nicht kleiner. Wenn die Arbeitsteilung oben umgesetzt ist, braucht man diese Schicht meist ohnehin nicht — im Main Thread landen von vornherein kaum Tool-Ergebnisse.
5. **Kurz hinschauen zu delegieren ist ein Nettoverlust.** subagent-Start rund 4.3k, siehe den glance-Abschnitt oben.
6. **Vor dem Umbau von Kontext erst die Cache-Rechnung machen.** Gemessen an einem Lauf mit 299.4M Input-Token: **96.1 % Cache-Treffer**; dass $171 ausreichen, hängt vollständig daran. Jede Optimierung, die Historie umschreibt, muss diese Rechnung zuerst aufmachen.
7. **Ergebnisse von Bild- und Dokument-Tools werden nicht gespillt.** `spill_guard` ändert nur String-Felder in der Ausgabestruktur, Listen bleiben ausnahmslos unangetastet.

Vollständige Defaults und Signaturen der Parameter siehe [Python API](../reference/api.md); Begriffe siehe [Glossar](../reference/glossary.md).
