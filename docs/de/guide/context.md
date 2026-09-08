# Kontext-Ökonomie

Der Kontext des [Main Threads](../reference/glossary.md#主线程) ist das Einzige, was einen
[long-horizon](../reference/glossary.md#长程) Lauf von Anfang bis Ende durchzieht; was darin liegt
und was nicht, entscheidet, wie weit dieser Lauf kommt. Die Form von flower — der
[Koordinator](../reference/glossary.md#协调者) fasst nichts selbst an, lange Ausgaben landen auf der
Platte, Hooks schneiden an Ort und Stelle weg — folgt vollständig aus diesem einen Punkt.
Diese Seite erklärt, warum.

## Welches Problem es löst {#解决什么问题}

[Compact](../reference/glossary.md#压缩) wartet, bis der Kontext voll ist, und fasst dann rückwirkend
zusammen — das kuriert Symptome. Das eigentliche Problem ist:
**Belangloses hätte von vornherein nicht in den Main Thread gehört.**

Der Unterschied liegt im Zeitpunkt. Die Ausgabe eines einzigen `pytest`-Laufs hat schnell
Zehntausende Zeichen, das Modell sieht einmal hin, zieht eine Schlussfolgerung, und die restlichen
Zeichen werden von da an in jeder Runde erneut mitgeschickt; ist das Fenster voll, fasst Compact sie
zusammen mit den danebenliegenden Entscheidungen zu einer Zusammenfassung — gespart wird Volumen,
verloren geht das »warum wurde das damals so entschieden«. Die Auslöseschwelle für auto-compact ist
**Fenster − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py));
in diesem Moment liegen das, was weg soll, und das, was bleiben soll, längst nebeneinander.

flower löst das in vier Ebenen, die Reihenfolge ist zugleich die Priorität — sortiert danach, wie
viel sie sparen:

| Ebene | Was sie tut | Wo |
|---|---|---|
| 1. Arbeitsteilung | Handarbeit geht an [Subagents](../reference/glossary.md#subagent), Trial-and-Error landet in deren eigenem Transcript | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. Workbench | Skripte / lange Ausgaben / Entscheidungen auf die Platte, Index in den System Prompt injiziert | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. Sofort-Spill | `PostToolUse`-Hook spillt Tool-Ergebnisse über der Schwelle, im Kontext bleibt nur eine Zeile mit dem Pfad | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. Trim und Prune | Session wird vor dem Resume umgeschrieben: abgelaufene Ergebnisse, abgelehnte Aufrufe, Verbindungsabbruch-Reste werden nicht mehr zurückgefüttert | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py)、[`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

Die ersten beiden Ebenen entscheiden, **ob etwas überhaupt hereinkommt**, die letzten beiden,
**ob das bereits Hereingekommene bleibt**. Die Reihenfolge lässt sich nicht umdrehen: Ebene vier
kann noch so hart zuschlagen, sie holt die Menge nicht zurück, die Ebene eins durchgelassen hat.

## Wie man es benutzt (Minimalcode) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model ist standardmäßig "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

Diese paar Zeilen installieren die ersten drei Ebenen: `coordinator()` setzt immer
`delegate_only=True` (Ebene eins); `workbench=True` legt die
[Workbench](../reference/glossary.md#工作台) an und injiziert den Index in den System Prompt des
Koordinators (Ebene zwei) und lässt `Runtime` zugleich `spill_guard` installieren (Ebene drei).
Ebene vier ist per Default ohnehin da — der
[Session Store](../reference/glossary.md#会话存储) von `Runtime` ist fest auf `PruningSessionStore`
verdrahtet, in den Konstruktorparametern gibt es keinen Einstiegspunkt, ihn auszutauschen.

!!! warning "`workbench=True` ist keine Option"
    Der `delegate_guard`, der den Koordinator vom Selbermachen abhält, hängt in `workbench_hooks`,
    und `workbench_hooks` wird nur installiert, wenn `Runtime` eine Workbench hat; `whitelist_guard`
    wiederum wird wegen `delegate_only=True` übersprungen.
    Fazit: **Bei `Runtime(workbench=False)` zusammen mit `coordinator()` steht vor Bash / Write /
    Edit im Main Thread keine einzige Wand.**

## Was es tatsächlich tut {#它实际做了什么}

### Ebene eins: Arbeitsteilung (spart am meisten) {#第一层分工省得最多}

Der Koordinator spielt »einen Menschen, der Claude Code bedienen kann«: zerlegen, verteilen,
Berichte lesen, entscheiden. Er bekommt kein Bash / Write / Edit — die Tools sind nur `Agent`,
`TodoWrite`, `Read` (bei `glance=True` zusätzlich ein eingeschränktes `Bash`, siehe unten).
Alle Handarbeit geht an [Worker](../reference/glossary.md#执行者).

**Wann es auslöst**: Jedes Mal, wenn der Main Thread `Bash|Write|Edit|NotebookEdit` aufruft,
verweigert der `PreToolUse`-Hook `delegate_guard` sofort und weist den Weg — »schick per Agent-Tool
einen Subagent los, schreib Ziel und Abnahmekriterien in die Aufgabe und verlang, dass er lange
Ausgaben nach `.flower/artifacts/` schreibt und in der Antwort nur Pfad und Schlussfolgerung
liefert«. Subagents werden ausnahmslos durchgelassen. Kriterium ist, ob in den Hook-Daten eine
`agent_id` steht: **wer keine hat, ist der Main Thread**.

**Wie viel es spart**: Tool-Aufrufe und Trial-and-Error eines Subagents **landen in dessen eigenem
Transcript** (im Session Store per `subpath` unterschieden), im Main Thread bleibt nur dieser eine
`Agent`-Aufruf und der Abschlussbericht. Der Trial-and-Error-Verlauf wird nicht wegkomprimiert, er
**war nie im Main Thread**.

- Gemessen (eine Aufgabe, die viel Tool-Ausgabe erzeugt): 83% des Transcripts liegen im Subagent,
  Main Thread 13 Einträge, 21K Zeichen, Subagent 105K Zeichen.
- Gemessen (reale Größenordnung, ein Lauf über 10.4 Stunden, siehe [HT001](../cases/ht001.md)):
  Subagents tragen **97.7%** der Runden und **94.8%** der Fließtextzeichen; 1,893 handanlegende
  Tool-Aufrufe gegen 32 im Main Thread (**59:1**). Frühes Compact ist damit nicht mehr die
  Hauptlinie.

Die zwei Zeilen sind zwei verschiedene Messungen: oben ein früherer Kleintest, unten die Nachmessung
bei realer Größenordnung. Gleicher Mechanismus, je größer die Skala, desto mehr spart er.

Gespart wird Kontext, nicht Modellklasse: `worker()` setzt per Default `model="inherit"` — Worker
sollen nicht heruntergestuft werden.

Der einzige Gegenposten der Arbeitsteilung ist das [Task Brief](../reference/glossary.md#任务书) —
der Text, den der Koordinator beim Verteilen schreibt; er geht in den Main Thread und bleibt dort
dauerhaft. Gemessen wiederholten 8/8 Task Briefs Disziplinregeln, die der Gegenseite bereits bekannt
waren; im kürzesten mit 521 Zeichen waren nur rund 120 Zeichen aufgabenspezifisch, eine Runde
verschenkt so rund 4.8k dauerhaften Kontext. Deshalb steht in `COORDINATOR_RULES` fest verdrahtet:
**ins Task Brief kommt nur, was für diese eine Aufgabe spezifisch ist**. Die einzige Regel, die
trotzdem mitgeteilt werden muss, ist »wo die Workbench liegt + lange Ausgaben nach `artifacts/` +
in der Antwort nur Pfad und Schlussfolgerung« — denn der Workbench-Index erreicht Subagents nicht,
das Task Brief ist der einzige Kanal.

### Ebene zwei: Workbench (kuriert das »jedes Mal neu schreiben«) {#第二层工作台治每次重写}

Drei Verzeichnisse unter `.flower/`, die mit dem Workspace mitwandern:

| Verzeichnis | Was hineingehört | Was es löst |
|---|---|---|
| `scripts/` | Verifikations- / Reproduktionsskripte, die ein zweites Mal laufen, erste Zeile `# desc: 一句话` | Einmal schreiben, danach direkt ausführen. Kein »nach dem Compact verloren, jedes Mal neu geschrieben« mehr |
| `artifacts/` | Lange Ausgaben über 2000 Zeichen: Logs, Daten, Berichte, Diffs | Im Dialog erscheinen nur Pfad und Schlussfolgerung |
| `notes/` | Zentrale Entscheidungen samt Begründung, eine Datei pro Entscheidung | Nach Compact, Neustart, Maschinenwechsel sind die Schlüsse noch da |

**Wann es auslöst**: `INDEX.md` wird automatisch erzeugt (per Default höchstens 40 Einträge),
`refresh()` ruft der `index_guard` im `PostToolUse` auf, wenn `Write` / `Edit` innerhalb der
Workbench landen; vor jedem Schritt wird ebenfalls einmal aufgefrischt. Die drei obigen Regeln
injiziert `prompt_block()` in den System Prompt des Koordinators — er weiß von Anfang an, welche
Skripte es schon gibt, und muss keinen Tool-Aufruf zum Entdecken verbrauchen.

**Wie viel es spart**: Gemessen an einem Lauf über 10.4 Stunden wurden **61 Skripte 95-mal
geschrieben und 331-mal ausgeführt; 92% liefen mehr als einmal, 0 wurden geschrieben, ohne je zu
laufen**. Qualitativ: `audit-fake-ai-server.py` wird von 7 Skripten wiederverwendet.

Diese Ebene funktioniert wegen eines Unterschieds: Compact räumt den Kontext ab, **aber nicht die
Platte und nicht den Index im System Prompt**.

!!! warning "Den Index erben Subagents nicht"
    Der Index läuft über `system_prompt.append` auf Session-Ebene, Subagents haben ihren eigenen
    System Prompt und **erben ihn nicht** (gemessen $0.2461, `tests/prelude_live.py`). Deshalb muss
    »wo die Workbench liegt + lange Ausgaben nach `artifacts/`« der Koordinator im Task Brief
    weitergeben — das ist der einzige Kanal, keine Redundanz.

### Ebene drei: Sofort-Spill {#第三层当场落盘}

`spill_guard` ist ein `PostToolUse`-Hook, der sich Tool-Ergebnisse ansieht, **bevor sie ins Modell
gehen**: Alles über `threshold` (Default **4000** Zeichen) wird in das Verzeichnis `spill/` der
Workbench [gespillt](../reference/glossary.md#落盘) und im Kontext durch eine Zeile Pointer +
die **ersten 400 Zeichen** ersetzt. Der Inhalt ist nicht verloren, er ist nur nicht dauerhaft
präsent.

**Wann es auslöst**: Der Matcher ist `Bash|Read|Grep|Glob|WebFetch|WebSearch`; `main_only=False` ist
Default, also werden auch Ergebnisse von Subagents gespillt. Ersetzt werden nur zu lange
**String-Felder** in der Ausgabestruktur des Tools, Listen bleiben grundsätzlich unangetastet
(darin können Bildblöcke stecken), denn `updatedToolOutput` muss die Ausgabestruktur des
ursprünglichen Tools behalten.

**Das Lesen der Spill-Datei selbst wird durchgelassen und nicht erneut gespillt.** Sonst wäre der
Hinweis in jener Zeile — »für den Volltext lies sie mit Read« — eine leere Phrase: zurückgelesen,
wieder über der Schwelle, wieder gespillt, wieder nur ein Pointer, Endlosschleife. Gemessen
aufgetreten (`tests/handoff_live.py`, beim ersten echten Lauf): Das Modell probierte fünf
Schreibweisen zum Umgehen, sagte selbst "The spill read loops back on itself", und quälte sich am
Ende in 40-Zeilen-Häppchen durch — sieben, acht Runden verbrannt. Der Sinn von Spill ist, große
Dinge **nicht automatisch** in den Kontext zu schieben; wenn es selbst entscheidet, den Volltext zu
sehen, ist das seine Entscheidung.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None 或 0 = 不装这个 hook
```

**Wie viel es spart**: In jenem Lauf von [HT001](../cases/ht001.md) wurden 103 Spills, 791.4K
Zeichen, durch Pfad-Pointer ersetzt und belegten keinen dauerhaften Kontext.

### Ebene vier: Trim und Prune {#第四层裁剪与剪除}

Diese Ebene sitzt im [Session Store](../reference/glossary.md#会话存储). Der Store von `Runtime` ist
immer `PruningSessionStore` (Vererbungskette `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`); er schreibt in `load()` — also **vor dem Resume** — die zurückzufütternde
Historie um. Am Original in SQLite wird kein Zeichen angefasst. Vier Dinge:

**① Ablauf nach Aktualität** (`ephemeral`, per Default an). Ergebnisse von
[Ephemeral-Kommandos](../reference/glossary.md#一次性命令) wie `git status`, `ls`, `cat` werden nach
ein paar Runden im Fließtext durch einen Hinweis ersetzt, die letzten 6 bleiben erhalten.
Abgelaufene Inhalte werden **nicht gespillt** — ein altes `git status` zu archivieren ist sinnlos,
ein erneuter Lauf liefert es:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

Live-Resume gemessen: `expired: 2`; auf einem echten Transcript mit `keep_recent` auf 2 liefen
5 Einträge ab.

**② [Trim](../reference/glossary.md#裁剪)** (`trim`, **per Default aus**). tool_result-Texte
mit `>= 2000` Zeichen werden nach `<workspace>/.flower/spill/` gespillt, der Blockinhalt wird durch
einen Dateipointer ersetzt, die letzten 20 Originale bleiben. Achtung: Dieses Verzeichnis ist
**nicht dasselbe** wie das Spill-Verzeichnis des `spill_guard` aus Ebene drei: Letzteres schreibt in
das Wurzelverzeichnis der Workbench, während dieses hier zwingend im Workspace liegen muss, sonst
kommt das `Read` des Agents nicht heran.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True 也行
```

**③ [Prune](../reference/glossary.md#剪除) abgelehnter Aufrufe** (`keep_denials`, Default 1).
Das Abfangen selbst verschmutzt ebenfalls den Kontext: Die Ablehnungsmeldung ist ein `tool_result`
und bleibt zusammen mit dem **nie ausgeführten Kommando** dauerhaft liegen. Gemessen einmal
273 Zeichen (93 Zeichen Ablehnungstext + 180 Zeichen totes Kommando) — das tote Kommando ist teurer
als die Ablehnung.

Wichtiger als Token ist, dass es **in die Irre führt**: Gemessen las der Koordinator ein paar
»Bash nicht direkt verwenden« und versuchte danach nicht einmal mehr das durchgelassene
`git status`, sondern sagte direkt »Bash ist eingeschränkt, ich schicke einen Agent zum Nachsehen« —
erlernte Hilflosigkeit, die zusätzlich einen Subagent-Start kostet. Per Default bleibt 1 Eintrag
statt 0: Die neueste Ablehnung ist ein gültiges Signal und verhindert, dass das Modell in derselben
Runde dasselbe abgefangene Kommando immer wieder versucht. Erkannt wird das an der strukturellen
Markierung `toolDenialKind: "permission-rule"`, die die Harness selbst setzt, nicht am Textabgleich
— Texte ändern sich jederzeit, Markierungen nicht. Live gemessen: 2 Ablehnungen → 1 entfernt,
1 behalten, Kette intakt, Resume normal, und das Modell weiß weiterhin, dass etwas passiert ist.

**④ Verbindungsabbruch-Reste prunen**. Synthetische API-Fehlermeldungen aus Retry-Phasen bei
Netzabbruch werden nicht zurückgefüttert; ein durch Unterbrechung hinterlassenes `tool_result` wird
durch einen neutralen Hinweis ersetzt (`[上一轮在此处被中断,该工具结果未产生]`), der Eintrag selbst
bleibt.

**Die rote Linie beim Entfernen**: `tool_use` und sein `tool_result` müssen **gemeinsam** entfernt
werden (fehlt eines, gibt es `Missing Tool Result Block`), andere Aufrufe in derselben
Assistant-Nachricht dürfen nicht mit getroffen werden, und die `parentUuid`-Kette muss wieder
zusammengefügt werden.

`Runtime(trim=False)` (Default) **heißt nicht, dass nichts aufgeräumt wird**: Es schaltet nur das
Trimmen großer Ergebnisse ab; Ablauf, abgelehnte Aufrufe und Verbindungsabbruch-Reste laufen
weiter.

### Gegenbeispiel: Was nur einen Blick kostet, macht er selbst {#反例看一眼的活自己干}

Die ersten drei Ebenen sagen alle »gib es nach außen«, aber es gibt ein Gegenbeispiel: Kommandos wie
`git status`, `ls`, `cat` liefern Ergebnisse von einigen Dutzend Zeichen, während **allein der Start
eines Subagents rund 4.3k Kontext kostet** (gemessen, nicht amortisierbar). Diesen Preis für ein
`ls` zu zahlen ist ein Nettoverlust.

Deshalb bekommt der Koordinator ein eingeschränktes Bash zurück (`coordinator(..., glance=True)`,
per Default an). Das Kriterium ist nicht »das Kommando ist kurz«, sondern **ob das Ergebnis
veraltet**, und »durchlassen« wie »ablaufen« entscheidet dieselbe Funktion `is_ephemeral()`:

| | Selbst ausführen erlaubt | Ergebnis wird als abgelaufen markiert |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ delegieren | — |

Beide Seiten müssen dieselbe Tabelle sein, sonst schadet jede Seite für sich allein:
**durchgelassen, aber nicht getrimmt** — dann belegt ein abgelaufenes `git status` dauerhaft Kontext
und wird obendrein als aktueller Stand missverstanden; **getrimmt, aber nicht durchgelassen** —
dann zahlt der Koordinator für ein `ls` 4.3k. `tests/glance.py` nagelt diese Invariante als
Assertion fest — gemessen stimmen bei 46 Kommandos beide Seiten vollständig überein, inklusive
10 Adversarial-Fällen.

**Falle (zweimal hineingetreten)**: Das Modell schreibt keine Einzelkommandos, es schreibt
`git status -s && echo "--- LOG ---" && git log --oneline -10`. Die erste Version lehnte pauschal
alles ab, was `&&` / `|` / `2>&1` enthielt, mit dem Ergebnis, dass **glance völlig wirkungslos**
war — gemessen wurden alle drei Versuche des Koordinators abgefangen, er musste doch wieder einen
Subagent schicken. Jetzt wird segmentweise zerlegt und geprüft: Nur wenn jedes Segment auf der
Whitelist steht, wird durchgelassen; `git status && rm -rf x` wird weiterhin abgefangen (die hintere
Hälfte steht nicht in der Tabelle).

### Append, nicht ersetzen {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Wenn `build_options()` ein `AgentSpec` in SDK-Optionen kompiliert, läuft `instructions` über
[`append`](../reference/glossary.md#叠加) — angehängt **hinter** den nativen System Prompt von
Claude Code, nicht als Ersatz. Die obigen Disziplintexte (`COORDINATOR_RULES`, `WORKER_RULES` usw.)
sind also additiv: **Spezialisierung geht nicht auf Kosten der allgemeinen Fähigkeiten.**

Der Workbench-Index läuft über denselben Kanal. Er ist in jeder Runde da, aber als Teil des System
Prompts belegt er keine Dialoghistorie, und Compact räumt ihn nicht weg — der Preis ist der oben
genannte: **nur bis zum Koordinator**.

!!! warning "Nicht `disallowed_tools` benutzen, um den Koordinator vom Selbermachen abzuhalten"
    `disallowed_tools` wirkt **auf Session-Ebene** und sperrt Subagents mit aus. Gemessene
    Fehlermeldung im Original:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    Richtig ist es in zwei Schritten: in `allowed_tools` nicht aufführen und dann per
    `PreToolUse`-Hook anhand der `agent_id` nur den Main Thread abfangen. `coordinator()` macht
    genau das — es setzt `delegate_only=True`, und `delegate_guard` fängt den Main Thread ab und
    lässt Subagents durch.

    Nur auf `allowed_tools` zu setzen reicht ebenfalls nicht: Das ist eine **Liste ohne
    Genehmigungspflicht, keine exklusive Whitelist**. Gemessen kann das Modell Tools aufrufen, die
    nicht darin stehen — in einer Sonde für $0.1 rief ein Agent mit `allowed_tools=["Read"]`
    problemlos Write / Bash auf. Was tatsächlich abfängt, ist der Hook.

    **`allowed_tools` ist ebenfalls session-weit, dieselbe Lektion zweimal gelernt.** Tools, die
    nicht auf dieser Liste stehen, müssen auch beim Aufruf durch einen **Subagent** durch die
    Genehmigung. Unbeaufsichtigt genehmigt niemand, also gibt es weder Fehler noch Stopp, und das
    Modell versucht denselben Aufruf immer wieder (`toolDenialKind=user-rejected`). Gemessen: Dem
    Worker wurden `WebFetch`/`WebSearch` gegeben, aber nur in `AgentDefinition.tools` eingetragen —
    jener Lauf hatte über zwanzig user-rejected und produzierte kein einziges Zeichen
    (`roles.py:513-518`). Das Symptom ist schwerer zu finden als bei `disallowed_tools` — dort gibt
    es sofort einen Fehler, hier sieht auf dem Bildschirm nichts nach Fehler aus.
    Deshalb zieht `coordinator()` inzwischen die Read-only-Web-Tools der unterstellten Worker in die
    eigenen `allowed_tools` (`roles.py:523-526`), während `Write`/`Edit`/`Bash` **absichtlich nicht**
    übernommen werden — sie zu übernehmen hieße, den obigen Hook abzubauen.

## Wann man es nicht verwenden sollte {#什么时候不该用它}

Diese vier Ebenen sparen alle am **Arbeitsmaterial**. Die folgenden Probleme lösen sie nicht, manche
werden durch sie sogar schwerer sichtbar:

1. **Das Ziel wurde falsch verstanden — diese vier Ebenen machen das schlimmer.** Nachdem das
   Material weggeworfen ist, bleibt genau jene Entscheidung übrig, die auf der falschen Prämisse
   steht, und sie **sieht exakt aus wie eine richtige Entscheidung**. Long-horizon verstärkt das bis
   zum Schlimmstfall: Die falsche Prämisse läuft erst stundenlang, schickt ein Dutzend Subagents
   los, legt einen Haufen Artefakte auf die Platte, und erst danach fliegt sie auf. Dann sind nicht
   die Token teuer, sondern dass jedes Artefakt gegen die falsche Anforderung gebaut wurde. Dagegen
   hilft die [Vorab-Klärung](clarify.md), nicht irgendeine Ebene dieser Seite.
2. **Der Main Thread wächst weiterhin monoton.** Die vier Ebenen drücken die Steigung, nicht die
   Richtung. Gemessen: Der Main Thread wuchs über 70 Runden von 28.7K auf 185.9K, Steigung
   2.2K/Runde, durchgehend ohne Compact, 18.6% eines 1M-Fensters verbraucht, **extrapoliert rund
   440 Runden bis zur Wand**. Über diese Wand kommt man mit [Handoff](handoff.md).
3. **Nach dem Abschalten des vollen Compacts gibt es kein Auffangnetz.** Ist Handoff an, setzt
   `Runtime` dem Spec zwingend `CompactPolicy(mode="no_summary")`, womit auto-compact abgeschaltet
   ist (hat das Spec selbst explizit ein `compact` gesetzt, wird das respektiert). An die Obergrenze
   zu stoßen ist ein harter Fehler, deshalb müssen diese vier Ebenen zusammen mit Handoff eingesetzt
   werden; Compact einfach nur abzuschalten genügt nicht.
4. **Ebene vier wirkt nur beim Resume.** Trim und Prune passieren in `load()`, eine durchgehend
   laufende Session wird dadurch nicht kleiner. Wenn die Arbeitsteilung wie oben umgesetzt ist,
   braucht man diese Ebene meist ohnehin nicht — in den Main Thread passen von vornherein kaum
   Tool-Ergebnisse.
5. **Was nur einen Blick kostet, nach außen zu geben, ist ein Nettoverlust.** Subagent-Start rund
   4.3k, siehe den Abschnitt zu glance oben.
6. **Vor dem Umbauen des Kontexts erst die Cache-Rechnung aufmachen.** Gemessen hatte ein Lauf
   299.4M Input-Token, **96.1% Cache-Treffer**; dass $171 reichen, hängt komplett daran. Jede
   Optimierung, die Historie umschreibt, muss diese Rechnung zuerst machen.
7. **Ergebnisse von Bild- und Dokument-Tools werden nicht gespillt.** `spill_guard` ändert nur
   String-Felder in der Ausgabestruktur, Listen bleiben grundsätzlich unangetastet.

Vollständige Defaults und Signaturen der Parameter stehen in der [Python API](../reference/api.md);
Begriffe im [Glossar](../reference/glossary.md).
