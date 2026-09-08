# Glossar

Diese Seite ist die Terminologie-Basis der flower-Dokumentation. Dieselbe Sache heißt auf der
gesamten Site genau gleich; die Zuordnung Chinesisch–Englisch ist hier festgeschrieben —
und die Übersetzungen folgen genau dieser Tabelle.

Jeder Eintrag liefert drei Dinge: **worauf der Begriff zeigt**, **was er im Code ist** und
**was er nicht ist**. Das dritte ist oft das nützlichste, denn die meisten Missverständnisse
entstehen dadurch, dass ein Begriff für einen anderen gehalten wird.

---

## Framework und Run {#框架与运行}

### Long-horizon {#长程}

**long-horizon**

Ein Run erstreckt sich über Stunden bis Tage, über mehrere Sessions, über Prozess-Neustarts hinweg
— nicht Frage und Antwort. Alle Mechanismen von flower existieren, damit ein solcher Run
unterwegs nicht auseinanderfällt.

Messwert zum Vergleich: [HT001](../cases/ht001.md) lief 10.4 Stunden am Stück.

### Run {#运行}

**run**

Der vollständige Ablauf einer `Runtime` von Anfang bis Ende. Ein Run kann intern mehrere
[Schritte](#步骤) und mehrere [Sessions](#会话) enthalten und nach einem Abbruch
[fortgesetzt](#接续) werden. Die Aufzeichnung liegt in `runs/manifest.json` und `runs/sessions.db`.

**Nicht**: ein API-Aufruf, und auch keine Session.

### Session {#会话}

**session**

Ein Kontext auf Modellseite. Hat eine eigene `session_id`, lässt sich resumen und forken. Ein
[Run](#运行) verbraucht womöglich mehrere Sessions — bei jedem [Handoff](#换代) kommt eine neue.

### Schritt {#步骤}

**step** · `Step`

Eine ausführbare Einheit im [Workflow](#流程). Bekommt ein Kontext-Dictionary, führt einen Agent
aus und schreibt das Ergebnis in das Dictionary zurück. `Step` ist eine Klasse, siehe
[Python API](api.md#step).

### Workflow {#流程}

**workflow** · `Workflow`

Eine Reihe von [Schritten](#步骤) in fester Reihenfolge, plus die Regeln dafür, wie Zustand
zwischen den Schritten weitergereicht wird und wann vorzeitig abgebrochen wird.

!!! note "Das Framework liefert keine fertigen Workflows"
    flower liefert nur Mechanismen. **Den Workflow schreibst du.** Siehe
    [Workflow entwerfen](../guide/workflow.md).

---

## Rollen {#角色}

Rollen sind die Arbeitsteilung, die flower über Agents legt. Jede Rolle = ein Stück injizierter
Regeltext + ein Satz Tools + ein Satz Hooks. Alle fünf Rollen sind Factory-Funktionen, siehe
[Python API](api.md#角色工厂).

### Koordinator {#协调者}

**coordinator** · `coordinator()`

Der Agent auf dem [Hauptthread](#主线程). Er zerlegt Aufgaben, verteilt Arbeit, liest Berichte und
trifft Entscheidungen, **greift aber nicht selbst zu** — er bekommt kein `Write` / `Edit`. Die
Basis-Tools sind `Agent`, `TodoWrite`, `Read` (`roles.py:27`), aber das ist nicht die endgültige
Liste: je nach Parametern kommen drei weitere Sorten dazu. `glance=True` (Default) fügt ein
eingeschränktes `Bash` hinzu (gerade genug für Befehle vom Typ `git status` / `ls`, die mit einem
Blick erledigt sind; kontrolliert von `delegate_guard`); wird ein Frage-Kanal übergeben, kommen
`inbox` und `ask` dazu; und wenn die untergeordneten [Worker](#执行者) `WebFetch` / `WebSearch`
mitbringen, werden diese beiden ebenfalls mit hineingezogen — `allowed_tools` gilt
**sessionweit**, und ohne das Hineinziehen bliebe der Subagent beim eigenen Aufruf in einer
Berechtigungsfreigabe hängen, die niemand beantwortet (`roles.py:513-526`).

Die Rollenvorgabe lautet „jemand, der Claude Code bedienen kann“, nicht Worker.

**Nicht**: ein schlaueres Agent. Er nutzt standardmäßig dieselbe Modellklasse wie der
[Worker](#执行者); gespart wird Kontext, nicht Modell.

### Worker {#执行者}

**worker** · `worker()`

Der [Subagent](#subagent), der die eigentliche Arbeit macht: Code schreiben, Tests laufen lassen,
recherchieren. Tools sind `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`.

Das Antwortformat wird per Regeltext auf vier Abschnitte festgezurrt —
**Fazit / Belege / Ergebnis / Ungeprüft**, höchstens 30 Zeilen; Dateiinhalte, Kommandoausgaben,
Logs und Roh-Diffs einzufügen ist verboten.

### Clarifier {#确认者}

**clarifier** · `clarify()`

Die Rolle, die vor dem Loslegen die Anforderung klärt. Sie tut nichts, sie fragt nur — so lange,
bis es klar ist (**kein Rundenlimit**), und gibt am Ende einen [Brief](#需求确认书) aus. Siehe
[Vorabklärung](../guide/clarify.md).

### Judge {#判定者}

**judge** · `judge()`

Die Rolle, die entscheidet, ob etwas fertig ist. Sie tut eines von zwei Dingen: vor dem Start
**das Ziel setzen** (Ziel + Prüfliste ausgeben), oder nach jeder Runde **diese Runde bewerten**
(ein [Verdict](#判定) ausgeben). Siehe [Zielwächter](../guide/goal.md).

**Entscheidend**: Der Judge bewertet das **Artefakt**, nicht den Quellcode.

In [HT001](../cases/ht001.md) ist genau das einmal schiefgegangen: Das Abnahmekriterium lautete
„läuft direkt im macOS-Terminal“, das gelieferte Artefakt meldete unter `file`
`ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux` — und das Verdict war trotzdem bestanden.

Zwei Punkte müssen klar sein, sonst wird das Beispiel falsch gelesen:

1. **Das Fehlurteil kam nicht vom Zielwächter** — HT001 hatte diesen Mechanismus noch nicht;
   falsch geurteilt hat ein Auditor, den der Koordinator von sich aus losgeschickt hatte.
2. **Auch ein Judge in Default-Konfiguration würde das mit hoher Wahrscheinlichkeit übersehen.**
   `judge()` setzt standardmäßig `can_run=False`, die Tools sind nur `Read/Glob/Grep` —
   **er kann `file` gar nicht ausführen**, er würde nur das `Makefile` lesen, dort tatsächlich
   einen Darwin-Zweig sehen und auf „erreicht“ entscheiden.

Was wirklich funktioniert, zeigt [HT002](../cases/ht002.md): Dort hatte der Judge
`judge_can_run` aktiviert, führte `file` und `lsof` selbst aus, sah sich die Lage vor Ort an und
umging diese Falle gezielt. **Der Satz „das Artefakt bewerten“ trägt also nur mit
`can_run=True`.**

### Oracle {#旁路顾问}

**oracle** · `oracle()`

Ein reiner Lese-Seitenkanal. Während der Run noch läuft, kannst du ihn fragen „wo stehen wir
gerade“; er wirft einen Blick auf die letzten Events und die [Workbench](#工作台) und antwortet
dann. **Was er sagt, geht nicht in den Kontext dieses Runs ein** — die Frage beeinflusst den Run
nicht, die Antwort wird nach der Ausgabe verworfen.

### subagent {#subagent}

Ein Begriff des Claude Agent SDK: ein Sub-Agent, den das Haupt-Agent über das Tool `Agent`
losschickt. Er hat **ein eigenes Transcript**; Tool-Aufrufe und Fehlversuche landen dort, der
Hauptthread bekommt nur den Abschlussbericht.

Das ist die erste Schicht, mit der flower Kontext spart, und die mit dem größten Effekt. Siehe
[Kontextökonomie](../guide/context.md).

---

## Die vier Mechanismen {#四个机制}

### Vorabklärung {#前置确认}

**clarify**

Vor dem Loslegen die Anforderung klären, sie in einem [Brief](#需求确认书) einfrieren und erst
dann ausführen. Verhindert „gebaut, aber nicht das Gewünschte“. Siehe
[Vorabklärung](../guide/clarify.md).

### Brief {#需求确认书}

**brief** · `Brief`

Das Dokument, das der [Clarifier](#确认者) nach dem Fragen ausgibt, **genau vier Abschnitte**.
Nachfolgende Schritte lesen es und raten die Anforderung nicht erneut.

**Nicht** mit dem [Task Brief](#任务书) verwechseln. Der Brief ist „was der Mensch will“, der
Task Brief ist „was dieser Subagent diesmal tut“.

### Task Brief {#任务书}

**task brief**

Der Text, den der [Koordinator](#协调者) beim Verteilen der Arbeit an den [Worker](#执行者)
schreibt. **Nur das, was für diese Aufgabe spezifisch ist** — Disziplin, die das Gegenüber schon
kennt, nicht wiederholen.

Gemessen: 8/8 Task Briefs wiederholten Disziplin, die das Gegenüber bereits kannte; im kürzesten
mit 521 Zeichen waren nur etwa 120 Zeichen aufgabenspezifisch — eine Runde verschenkte damit rund
4.8k permanenten Kontext.

### Zielwächter {#目标看守}

**goal guard**

Der [Judge](#判定者) entscheidet nach jeder Runde unabhängig, ob das Ziel erreicht ist; ist es das
nicht, geht die Arbeit zurück. Verhindert „sagt fertig, ist es aber nicht“. Siehe
[Zielwächter](../guide/goal.md).

### Verdict {#判定}

**verdict** · `Verdict`

Das Ergebnis einer Judge-Runde, **genau drei Abschnitte**: Fazit / Begründung / Nicht bestanden.

Es gibt drei Fazit-Werte: `ACHIEVED` (erreicht), `NOT_YET` (noch nicht), `UNREACHABLE` (in dieser
Umgebung nicht prüfbar). **Die letzten beiden sind verschiedene Ergebnisse** — „hier nicht
prüfbar“ wird auf keinen Fall als bestanden gewertet.

### Fortsetzung {#接续}

**continuity**

Ein erneuter Lauf im selben Verzeichnis knüpft automatisch am Fortschritt des letzten an — auch
dann, wenn der Prozess getötet oder die Maschine neu gestartet wurde. Verhindert „nach Stunden
abgestürzt, alles von vorn“. Siehe [Fortsetzung](../guide/continuity.md).

**Nicht** mit dem [Handoff](#换代) verwechseln: Fortsetzung knüpft **prozessübergreifend** an den
letzten Run an; ein Handoff wechselt **innerhalb desselben Runs** auf eine neue Session.

### Handoff {#换代}

**handoff**

Wenn der Kontext fast voll ist, schreibt die aktuelle Session ein
[Handoff-Dokument](#交接书), das ein Mensch lesen und ändern kann; dann übernimmt eine neue
Session. Verhindert „Kontext voll, alles zu einer Zusammenfassung zerquetscht“. Siehe
[Handoff](../guide/handoff.md).

**Nicht** Compact. Siehe [Compact](#压缩).

### Handoff-Dokument {#交接书}

**handoff document** · `Handoff`

Das beim Handoff geschriebene Dokument, fünf Abschnitte: `doing` (was gerade läuft), `decided`
(was entschieden wurde), `deadends` (Wege, die nicht funktionieren), `next` (nächster Schritt),
`scene` (Lage vor Ort).

**Nur `doing` und `next` sind Pflicht** — würde man erzwingen, dass „Wege, die nicht
funktionieren“ nicht leer ist, zwingt man das Modell zum Erfinden.

### Compact {#压缩}

**compact**

Das native Vorgehen von Claude Code: Ist der Kontext voll, wird der bisherige Dialog zu einer
Zusammenfassung verdichtet.

flower **benutzt es nicht**, sondern ersetzt es durch den [Handoff](#换代). Der Unterschied: Die
Zusammenfassung ist modellgeneriert, nicht lesbar, nicht änderbar, und was verloren geht, weißt du
nicht; das Handoff-Dokument ist strukturiert, liegt auf der Platte, und du kannst es öffnen, eine
Zeile ändern und weiterlaufen lassen.

---

## Kontextverwaltung {#上下文管理}

### Hauptthread {#主线程}

**main thread**

Der Session-Kontext, in dem der [Koordinator](#协调者) sitzt. Er ist der einzige Kontext, der
durch den gesamten Run trägt, also der, bei dem Sparen am meisten zählt.

So erkennt der Code den Hauptthread: In den Hook-Daten steht **kein** `agent_id`. Hooks von
Subagents tragen ein `agent_id`.

### Workbench {#工作台}

**workbench** · `Workbench`

Das Arbeitsverzeichnis auf der Platte, drei Unterverzeichnisse:

| Verzeichnis | Inhalt |
|---|---|
| `scripts/` | Skripte, die ein zweites Mal laufen sollen; erste Zeile `# desc: ein Satz` |
| `artifacts/` | Lange Ergebnisse über 2000 Zeichen |
| `notes/` | Zentrale Entscheidungen, eine Datei pro Entscheidung |

`INDEX.md` ist der Index dieser drei Verzeichnisse und wird **in den System-Prompt injiziert**,
damit das Agent in jeder Runde weiß, was es zur Hand hat.

!!! warning "Zwei Einstiege, zwei Default-Orte"
    Wo die Workbench liegt, hängt davon ab, wie sie erzeugt wird — hier tritt man leicht daneben:

    | Erzeugungsweg | Workbench-Wurzelverzeichnis |
    |---|---|
    | `Workbench(workspace)` — auch der Weg von `starter_flow()` / `wake_state()` | `<Workspace>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench` (Default `runs/workbench`) |

    Die Kommandozeile geht den ersten Weg, deshalb erzeugt `flower` ein `.flower/`; wer in Python
    direkt `Runtime(workbench=True)` schreibt, bekommt dagegen `runs/workbench`. Willst du den Ort
    festlegen, übergib eine fertig erzeugte `Workbench`-Instanz und verlass dich nicht auf den
    Default.

!!! warning "Den Index erben Subagents nicht"
    Der Index läuft über das sessionweite `system_prompt.append`, **Subagents bekommen ihn
    nicht**. Deshalb muss die Regel „lange Ergebnisse nach `artifacts/` schreiben“ vom
    [Koordinator](#协调者) im [Task Brief](#任务书) weitergegeben werden — das ist der einzige
    Kanal.

### Spill {#落盘}

**spill**

Überschreitet ein Tool-Ergebnis den Schwellwert (Default 4000 Zeichen), schreibt der
`PostToolUse`-Hook es nach `<Workbench-Wurzelverzeichnis>/spill/`; im Kontext bleibt nur eine
Zeile mit dem Pfad.

Der Pfad **folgt der [Workbench](#工作台)**, er ist nicht fest verdrahtet — nur wenn die Workbench
am Default-Ort `<Workspace>/.flower` liegt, ist er genau `.flower/spill/`. Ist
[Isolation](#隔离) aktiv und die Workbench per `home=` außerhalb des Repos, wandert der Spill mit
hinaus.

**Es wird sofort gekürzt**, nicht erst bei vollem Kontext nachträglich [compacted](#压缩).

### Ephemeral Command {#一次性命令}

**ephemeral command**

Ein Befehl, dessen Ergebnis veraltet und keinen Aufbewahrungswert hat — `ls`, `git status`, `ps`
und ähnliche. Ihre Ergebnisse gehen nicht in die persistierte Session-Aufzeichnung. Die
Entscheidungen „darf der Hauptthread damit kurz nachsehen“ und „wird das Ergebnis herausgeschnitten“
laufen über dieselbe Funktion, deshalb sind beide Mengen immer gleich.

### Trim {#裁剪}

**trim** · `TrimmingSessionStore`

Schreibt **vor dem Resume** die Nachrichten um, die dem Modell zurückgefüttert werden (Ergebnisse
von [Ephemeral Commands](#一次性命令), überlange Tool-Ausgaben).

Es überschreibt nur `load()`: **Der Originaltext in SQLite bleibt unangetastet**, gekürzt wird nur
die Fassung, die bei diesem Resume in den Kontext geht. Trim ist damit umkehrbar — mit einer
anderen Strategie noch einmal resumen, und du bekommst wieder die vollständige Aufzeichnung.

### Prune {#剪除}

**prune** · `PruningSessionStore`

Hält **Fehlermeldungen** aus dem Kontext heraus. Der Haufen Fehler, der während der Wiederholungen
bei Netzausfall entsteht, hat nach dem Resume nichts im Kontext zu suchen.

**Nicht** mit [Trim](#裁剪) verwechseln: Trim wirft nach Umfang und Wert weg, Prune nach der Frage
„ist das ein Fehler“.

---

## Laufzeit {#运行时}

### Isolation {#隔离}

**isolation**

Markierte Rollen bekommen automatisch ein eigenes Git-Worktree, erzwungen per Hook, nicht über den
Prompt. So kommen sich parallele Änderungen am selben Repo nicht in die Quere.

!!! warning "Mit Isolation muss die Workbench aus dem Repo heraus"
    Bei aktiver Worktree-Isolation muss die [Workbench](#工作台) per `home=` außerhalb des Repos
    liegen, sonst kann das isolierte Agent nicht in den geteilten Checkout schreiben.

### Resilience {#韧性}

**resilience** · `Resilience`

Bei Netzausfall hängen bleiben und warten statt mit Fehler auszusteigen: DNS- und TCP-Proben
beobachten die Lage, nach Rückkehr des Netzes läuft es per Resume weiter. Die während des Wartens
entstehenden Fehlermeldungen hält [Prune](#剪除) aus dem Kontext heraus.

### Lineage {#血缘}

**lineage** · `Lineage`

Hält prozessübergreifend fest, aus welcher Session dieser Run geforkt wurde; liegt in
`lineage.json`. Die [Fortsetzung](#接续) findet darüber, wo der letzte Lauf stehengeblieben ist.

**Nicht** mit dem [Run-Manifest](#运行清单) verwechseln — das ist `runs/manifest.json` und führt
die Abrechnung jedes Runs.

### Run-Manifest {#运行清单}

**run manifest** · `runs/manifest.json`

Die Abrechnung jedes [Runs](#运行): wie viel Geld, wie lange, wie groß der Kontext. Die Zahlen auf
den Fallseiten lassen sich hier nachrechnen.

### Wake {#唤醒}

**wake** · `wake_state()`

Die **rein lesende Sondierung** vor dem Start: prüfen, ob in diesem Workspace bereits ein
[Brief](#需求确认书) und ein Ziel liegen, und daraus entscheiden, ob es ein Neustart oder eine
[Fortsetzung](#接续) wird. **Es wird kein einziges Byte geschrieben.**

`wake_state()` ist der einzige Ort, an dem der Workbench-Pfad definiert wird — auch ein
Treiberprogramm, das wissen will, wo der Brief liegt, muss dort durch. Ein selbst
zusammengebastelter, falscher Pfad wirft keinen Fehler, er fällt still aus.

### Event {#事件}

**event** · `Event`

Der Nachrichtenstrom des SDK, flachgeklopft zu einer stabilen Struktur. **Die
[Interaktionsschicht](#交互层) kennt nur `Event` und importiert keinerlei SDK-Typen** — das ist
die Grenze, dank der ein UI-Wechsel den Kern nicht anfasst.

### Interaktionsschicht {#交互层}

**interaction layer**

Die UI-Schicht zwischen Mensch und Run. Default ist das Terminal, ersetzbar durch Web, TUI, HTTP
oder vollautomatisch ohne Aufsicht. Siehe [Interaktionsschicht wechseln](../guide/interaction.md).

### Session Store {#会话存储}

**session store** · `SessionStore`

Das Persistenz-Backend für Session-Nachrichten. Der Default `SqliteSessionStore` schreibt nach
`runs/sessions.db` und lässt sich mit den beiden Wrappern [Trim](#裁剪) und [Prune](#剪除)
umhüllen.

### Budget {#预算}

**budget** · `max_budget_usd`

Die Kostenobergrenze eines Runs; wird sie überschritten, hält er an. Ohne das wird ein
Long-horizon-Run teuer — [HT001](../cases/ht001.md) hat $171.62 gekostet.

---

## Portabilität {#可移植性}

### Portabel {#可移植}

**portable**

Auf einer anderen Maschine dasselbe Verhalten. Umgesetzt über `setting_sources=[]` — weder das
`~/.claude/` des Hosts noch das `.claude/` des Projekts wird gelesen. Domänenfähigkeiten reisen als
[plugin](#plugin) mit dem Repo, Credentials bringt `.env` selbst mit.

Der Preis: **Credentials musst du selbst mitbringen**, die Host-Konfiguration wird nicht
automatisch geerbt.

### Append {#叠加}

**append**

Domänenanweisungen werden **hinter** den nativen System-Prompt von Claude Code gehängt, statt ihn
zu ersetzen:

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

Spezialisierung geht damit nicht auf Kosten der allgemeinen Fähigkeiten.

### plugin {#plugin}

Ein Paket mit Domänenfähigkeiten, das mit dem Repo mitreist. Wird über `plugins=[local]` geladen;
im Verzeichnis können `skills/`, `agents/`, `hooks/` und `.mcp.json` liegen. Siehe
[Deployment](deploy.md#plugin).
