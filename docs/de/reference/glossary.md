# Glossar

Diese Seite ist die Terminologie-Referenz der flower-Dokumentation. Eine Sache heißt auf der
ganzen Site genau eines; die Zuordnung ist hier festgeschrieben — die Übersetzungen folgen
derselben Tabelle.

Jeder Eintrag liefert drei Dinge: **wofür der Begriff steht**, **was er im Code ist**, **was er
nicht ist**. Das dritte ist meist das nützlichste, denn die meisten Missverständnisse entstehen,
weil ein Begriff für einen anderen gehalten wird.

---

## Framework und Run

### Long-Horizon {#长程}

**long-horizon**

Ein Run zieht sich über Stunden bis Tage, über mehrere Sessions und über Prozess-Neustarts hinweg
— und ist eben kein Frage-Antwort-Spiel. Alle Mechanismen von flower existieren, damit ein solcher
Run nicht auf halber Strecke auseinanderfällt.

Messwert zum Vergleich: [HT001](../cases/ht001.md) lief 10.4 Stunden am Stück.

### Run {#运行}

**run**

Der vollständige Ablauf einer `Runtime` von Anfang bis Ende. Ein Run kann intern mehrere
[Steps](#步骤) und mehrere [Sessions](#会话) enthalten und nach einem Abbruch
[fortgesetzt](#接续) werden. Die Aufzeichnungen liegen in `runs/manifest.json` und
`runs/sessions.db`.

**Nicht**: ein API-Aufruf, und auch keine Session.

### Session {#会话}

**session**

Ein Kontext auf Modellseite. Hat eine eigene `session_id`, kann per resume fortgesetzt und
geforkt werden. Ein [Run](#运行) verbrennt unter Umständen mehrere Sessions — bei jedem
[Handoff](#换代) kommt eine neue.

### Step {#步骤}

**step** · `Step`

Eine ausführbare Einheit innerhalb eines [Workflows](#流程). Nimmt ein Kontext-Dict entgegen,
führt einen Agent aus und schreibt das Ergebnis zurück ins Dict. `Step` ist eine Klasse, siehe
[Python API](api.md#step).

### Workflow {#流程}

**workflow** · `Workflow`

Eine Reihe von [Steps](#步骤) in fester Reihenfolge, plus die Regeln, wie Zustand zwischen den
Steps weitergegeben wird und wann vorzeitig abgebrochen wird.

!!! note "Das Framework liefert keine fertigen Workflows"
    flower liefert nur Mechanismen. **Den Workflow schreibst du.** Siehe
    [Workflow entwerfen](../guide/workflow.md).

---

## Rollen

Rollen sind flowers Arbeitsteilung unter den Agents. Jede Rolle = ein Stück injizierter Regeltext
+ ein Satz Tools + ein Satz Hooks. Alle fünf Rollen sind Factory-Funktionen, siehe
[Python API](api.md#角色工厂).

### Koordinator {#协调者}

**coordinator** · `coordinator()`

Der Agent auf dem [Main Thread](#主线程). Er zerlegt Aufgaben, verteilt Arbeit, liest Berichte,
trifft Entscheidungen — **fasst aber selbst nichts an**: `Bash` / `Write` / `Edit` bekommt er
nicht. Seine Tools sind nur `Agent`, `TodoWrite`, `Read`.

Die Rollenvorgabe ist „ein Mensch, der Claude Code bedienen kann“, kein Worker.

**Nicht**: ein klügerer Agent. Er läuft standardmäßig auf derselben Modellklasse wie der
[Worker](#执行者); gespart wird Kontext, nicht Modell.

### Worker {#执行者}

**worker** · `worker()`

Der [Subagent](#subagent), der tatsächlich arbeitet: Code schreiben, Tests laufen lassen,
recherchieren. Tools sind `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch`.

Das Antwortformat ist durch den Regeltext auf vier Abschnitte festgelegt — **Fazit / Belege /
Ergebnisse / Ungeprüftes**, nicht mehr als 30 Zeilen, und es ist verboten, Dateiinhalte,
Kommandoausgaben, Logs oder Roh-Diffs einzukleben.

### Clarifier {#确认者}

**clarifier** · `clarify()`

Die Rolle, die vor dem Anfangen die Anforderung klärt. Sie erledigt nichts, sie fragt nur — so
lange, bis es klar ist (**kein Rundenlimit**) — und gibt am Ende ein [Brief](#需求确认书) aus.
Siehe [Clarify](../guide/clarify.md).

### Judge {#判定者}

**judge** · `judge()`

Die Rolle, die entscheidet, ob etwas fertig ist. Sie tut eines von zwei Dingen: vor dem Start
**das Ziel setzen** (Ziel + Prüfliste) oder nach jeder Runde **diese Runde beurteilen**
(Ausgabe: ein [Verdict](#判定)). Siehe [Goal Guard](../guide/goal.md).

**Entscheidend**: Der Judge beurteilt das **Artefakt**, nicht den Quellcode.

In [HT001](../cases/ht001.md) ist genau das einmal schiefgegangen: Das Abnahmekriterium lautete
„läuft direkt im macOS-Terminal“, ein `file` auf das gelieferte Artefakt ergab
`ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux` — und das Verdict lautete trotzdem
„bestanden“.

Zwei Dinge müssen dazu klar gesagt werden, sonst wird das Beispiel falsch gelesen:

1. **Die Fehlbeurteilung kam damals nicht vom Goal Guard** — HT001 hatte diesen Mechanismus noch
   nicht; falsch beurteilt hat ein Auditor, den der Koordinator von sich aus losgeschickt hatte.
2. **Ein Judge in Standardkonfiguration hätte es mit hoher Wahrscheinlichkeit ebenfalls
   übersehen.** `judge()` setzt `can_run=False` als Default, die Tools sind nur `Read/Glob/Grep`
   — **er kann `file` gar nicht ausführen** und liest stattdessen das `Makefile`, sieht dort den
   Darwin-Zweig und beurteilt das Ziel als erreicht.

Was wirklich hilft, zeigt [HT002](../cases/ht002.md): Dort hatte der Judge `judge_can_run` aktiv,
hat `file` und `lsof` selbst laufen lassen, sich die Lage vor Ort angesehen und die Falle
ausdrücklich umgangen. **Der Satz „beurteile das Artefakt“ trägt also erst mit `can_run=True`.**

### Oracle {#旁路顾问}

**oracle** · `oracle()`

Ein Nur-Lese-Nebenweg. Während der Run noch läuft, kannst du es fragen „wo stehen wir gerade“;
es wirft einen Blick auf die letzten Events und die [Workbench](#工作台) und antwortet dann.
**Was es sagt, gelangt nicht in den Kontext dieses Runs** — die Frage beeinflusst den Run nicht,
die Antwort wird nach dem Lesen verworfen.

### subagent {#subagent}

Ein Konzept des Claude Agent SDK: ein Sub-Agent, den der Haupt-Agent über das Tool `Agent`
losschickt. Er hat **ein eigenes Transcript**; Tool-Aufrufe und Irrwege landen dort, der Main
Thread bekommt nur den Abschlussbericht.

Das ist flowers erste Schicht der Kontexteinsparung — und die mit dem größten Effekt. Siehe
[Kontextökonomie](../guide/context.md).

---

## Die vier Mechanismen

### Clarify {#前置确认}

**clarify**

Vor dem Anfangen die Anforderung klären, sie in einem [Brief](#需求确认书) einfrieren und erst
dann ausführen. Verhindert wird: „gebaut, aber nicht das Gewünschte“. Siehe
[Clarify](../guide/clarify.md).

### Brief {#需求确认书}

**brief** · `Brief`

Das Dokument, das der [Clarifier](#确认者) nach dem Fragen ausgibt, **genau vier Abschnitte**.
Nachfolgende Steps lesen es und raten die Anforderung nicht erneut.

**Nicht** mit dem [Task Brief](#任务书) verwechseln. Das Brief ist „was der Mensch will“, das
Task Brief ist „was dieser Subagent diesmal tut“.

### Task Brief {#任务书}

**task brief**

Der Text, den der [Koordinator](#协调者) beim Verteilen der Arbeit an den [Worker](#执行者)
schreibt. **Nur das, was für genau diese Aufgabe spezifisch ist** — Disziplin, die das Gegenüber
schon kennt, wird nicht wiederholt.

Messung: 8/8 Task Briefs wiederholten Disziplin, die das Gegenüber bereits kannte; im kürzesten
davon waren von 521 Zeichen nur etwa 120 Zeichen aufgabenspezifisch — pro Runde rund 4.8k
dauerhaft belegter Kontext für nichts.

### Goal Guard {#目标看守}

**goal guard**

Der [Judge](#判定者) beurteilt nach jeder Runde unabhängig, ob das Ziel erreicht ist; ist es das
nicht, geht die Arbeit zurück. Verhindert wird: „fertig gemeldet, in Wahrheit nicht fertig“.
Siehe [Goal Guard](../guide/goal.md).

### Verdict {#判定}

**verdict** · `Verdict`

Das Ergebnis einer Beurteilungsrunde des [Judge](#判定者), **genau drei Abschnitte**: Fazit /
Begründung / Nicht erfüllt.

Es gibt drei Fazits: `ACHIEVED` (erreicht), `NOT_YET` (noch nicht), `UNREACHABLE` (in dieser
Umgebung nicht prüfbar). **Die letzten beiden sind verschiedene Fazits** — „hier nicht prüfbar“
wird niemals als bestanden gewertet.

### Continuity {#接续}

**continuity**

Im selben Verzeichnis noch einmal starten und automatisch am Stand des letzten Mals anknüpfen —
auch nach getötetem Prozess oder Maschinen-Neustart. Verhindert wird: „nach Stunden abgestürzt,
alles von vorn“. Siehe [Continuity](../guide/continuity.md).

**Nicht** mit [Handoff](#换代) verwechseln: Continuity knüpft **prozessübergreifend** an den
letzten Run an; Handoff wechselt **innerhalb desselben Runs** auf eine neue Session.

### Handoff {#换代}

**handoff**

Wenn der Kontext fast voll ist, schreibt die laufende Session ein für Menschen lesbares und
änderbares [Handoff-Dokument](#交接书), und eine neue Session übernimmt. Verhindert wird:
„Kontext voll, alles zu einer Zusammenfassung zerquetscht“. Siehe [Handoff](../guide/handoff.md).

**Kein** compact. Siehe [Compact](#压缩).

### Handoff-Dokument {#交接书}

**handoff document** · `Handoff`

Das beim Handoff geschriebene Dokument, fünf Abschnitte: `doing` (woran gerade gearbeitet wird),
`decided` (was entschieden ist), `deadends` (Wege, die nicht funktionieren), `next` (nächster
Schritt), `scene` (Lage vor Ort).

**Nur `doing` und `next` sind Pflicht** — die harte Forderung, dass „Wege, die nicht
funktionieren“ nicht leer sein darf, zwingt das Modell zum Erfinden.

### Compact {#压缩}

**compact**

Claude Codes natives Vorgehen: Kontext ist voll, also wird der bisherige Dialog zu einer
Zusammenfassung eingedampft.

flower **benutzt das nicht**, sondern ersetzt es durch [Handoff](#换代). Der Unterschied: Die
Zusammenfassung ist modellgeneriert, weder lesbar noch änderbar, und du weißt nicht, was
verloren geht; das Handoff-Dokument ist strukturiert, auf Platte geschrieben, und du kannst es
öffnen, eine Zeile ändern und dann weiterlaufen lassen.

---

## Kontextverwaltung

### Main Thread {#主线程}

**main thread**

Der Session-Kontext, in dem der [Koordinator](#协调者) sitzt. Er ist der einzige Kontext, der
den gesamten Run durchzieht — deshalb muss dort am meisten gespart werden.

So erkennt der Code den Main Thread: In den Hook-Daten fehlt `agent_id`. Hooks von Subagents
tragen `agent_id`.

### Workbench {#工作台}

**workbench** · `Workbench`

Das auf Platte liegende Arbeitsverzeichnis, drei Unterverzeichnisse:

| Verzeichnis | Inhalt |
|---|---|
| `scripts/` | Skripte, die ein zweites Mal laufen sollen; erste Zeile `# desc: ein Satz` |
| `artifacts/` | Lange Ergebnisse über 2000 Zeichen |
| `notes/` | Wichtige Entscheidungen, eine Entscheidung pro Datei |

`INDEX.md` ist der Index dieser drei Verzeichnisse und wird **in den System-Prompt injiziert**,
damit der Agent in jeder Runde weiß, was er zur Hand hat.

!!! warning "Zwei Einstiege, zwei Default-Orte"
    Wo die Workbench liegt, hängt davon ab, wie sie erzeugt wird — eine leicht übersehene Falle:

    | Erzeugungsweg | Workbench-Wurzelverzeichnis |
    |---|---|
    | `Workbench(workspace)` — auch der Weg von `starter_flow()` / `wake_state()` | `<workspace>/.flower` |
    | `Runtime(workbench=True)` | `<run_dir>/workbench` (Default `runs/workbench`) |

    Die Kommandozeile geht den ersten Weg, deshalb erzeugt `flower` ein `.flower/`; wer in Python
    direkt `Runtime(workbench=True)` schreibt, bekommt dagegen `runs/workbench`. Wenn du den Ort
    festlegen willst, übergib eine fertig gebaute `Workbench`-Instanz und verlass dich nicht auf
    den Default.

!!! warning "Den Index erben Subagents nicht"
    Der Index läuft über `system_prompt.append` auf Session-Ebene, **Subagents bekommen ihn
    nicht**. Die Regel „lange Ergebnisse nach `artifacts/` schreiben“ muss deshalb der
    [Koordinator](#协调者) im [Task Brief](#任务书) weitergeben — das ist der einzige Kanal.

### Spill {#落盘}

**spill**

Überschreitet ein Tool-Ergebnis den Schwellwert (Default 4000 Zeichen), schreibt der
`PostToolUse`-Hook es nach `<Workbench-Wurzel>/spill/`, und im Kontext bleibt nur eine Zeile mit
dem Pfad.

Der Pfad **folgt der [Workbench](#工作台)**, er ist nicht fest verdrahtet — nur wenn die
Workbench am Default-Ort `<workspace>/.flower` liegt, ist es genau `.flower/spill/`. Ist
[Isolation](#隔离) aktiv und die Workbench per `home=` aus dem Repo heraus verlegt, wandert der
Spill mit.

**Gekürzt wird sofort**, nicht erst per [Compact](#压缩), wenn der Kontext schon voll ist.

### Ephemeral Command {#一次性命令}

**ephemeral command**

Kommandos, deren Ergebnis verfällt und keinen Aufbewahrungswert hat — `ls`, `git status`, `ps`
und dergleichen. Ihre Ergebnisse gehen nicht in die persistierte Session-Aufzeichnung. Für
„darf der Main Thread das kurz selbst laufen lassen“ und „wird das Ergebnis wegtrimmt“ wird
dieselbe Funktion benutzt, deshalb sind die beiden Mengen immer identisch.

### Trim {#裁剪}

**trim** · `TrimmingSessionStore`

Schreibt **vor dem resume** die Nachrichten um, die dem Modell zurückgegeben werden (Ergebnisse
von [Ephemeral Commands](#一次性命令), überlange Tool-Ausgaben).

Es überschreibt nur `load()`: **Der Originaltext in SQLite bleibt unangetastet**, gekürzt wird
nur die Fassung, die bei diesem resume in den Kontext geht. Trim ist damit umkehrbar — mit einer
anderen Strategie noch einmal resumen, und man hat wieder die vollständige Aufzeichnung.

### Prune {#剪除}

**prune** · `PruningSessionStore`

Hält **Fehlermeldungen** aus dem Kontext heraus. Der Haufen Fehler, der während der Retries bei
Netzausfall entsteht, hat im Kontext nach dem resume nichts verloren.

**Nicht** mit [Trim](#裁剪) verwechseln: Trim wirft nach Volumen und Wert weg, Prune nach „ist
das ein Fehler“.

---

## Laufzeit

### Isolation {#隔离}

**isolation**

Markierte Rollen bekommen automatisch ein eigenes git worktree, erzwungen per Hook, nicht per
Prompt. So kollidieren parallele Änderungen am selben Repo nicht.

!!! warning "Mit Isolation muss die Workbench aus dem Repo heraus"
    Bei aktiver worktree-Isolation muss die [Workbench](#工作台) per `home=` außerhalb des Repos
    liegen, sonst kann der isolierte Agent nicht in den gemeinsamen Checkout schreiben.

### Resilience {#韧性}

**resilience** · `Resilience`

Bei Netzausfall wartend hängen bleiben statt mit Fehler abzubrechen: DNS- und TCP-Proben
beobachten die Lage, nach Rückkehr des Netzes läuft es per resume weiter. Die während des
Wartens entstehenden Fehlermeldungen hält [Prune](#剪除) aus dem Kontext heraus.

### Lineage {#血缘}

**lineage** · `Lineage`

Hält prozessübergreifend fest, aus welcher Session dieser Run geforkt wurde; liegt in
`lineage.json`. [Continuity](#接续) findet darüber, wo der letzte Lauf stehen geblieben ist.

**Nicht** mit dem [Run-Manifest](#运行清单) verwechseln — das ist `runs/manifest.json` und führt
die Abrechnung jedes Runs.

### Run-Manifest {#运行清单}

**run manifest** · `runs/manifest.json`

Die Abrechnung jedes [Runs](#运行): wie viel Geld, wie lange, wie groß der Kontext. Alle Zahlen
auf den Fallseiten lassen sich hier nachrechnen.

### Wake {#唤醒}

**wake** · `wake_state()`

Die **lesende Sondierung** vor dem Start: Prüft, ob dieser Workspace bereits ein
[Brief](#需求确认书) und ein Ziel hat, und entscheidet daraufhin, ob neu begonnen oder
[fortgesetzt](#接续) wird. **Es wird kein einziges Byte geschrieben.**

`wake_state()` ist der einzige Ort, an dem der Workbench-Pfad definiert ist — auch ein
Treiberprogramm, das wissen will, wo das Brief liegt, muss darüber gehen. Ein selbst
zusammengebauter, falscher Pfad wirft keinen Fehler, er versagt still.

### Event {#事件}

**event** · `Event`

Der Nachrichtenstrom des SDK, flachgeklopft zu einer stabilen Struktur. **Die
[Interaktionsschicht](#交互层) kennt nur `Event` und importiert keinen einzigen SDK-Typ** — das
ist die Grenze, dank der ein UI-Wechsel den Kern nicht anfasst.

### Interaktionsschicht {#交互层}

**interaction layer**

Die UI-Schicht zwischen Mensch und Run. Default ist das Terminal; ersetzbar durch Web, TUI, HTTP
oder vollautomatisch unbeaufsichtigt. Siehe
[Interaktionsschicht wechseln](../guide/interaction.md).

### Session Store {#会话存储}

**session store** · `SessionStore`

Das Persistenz-Backend für Session-Nachrichten. Der Default `SqliteSessionStore` schreibt nach
`runs/sessions.db` und lässt sich mit den beiden Wrappern [Trim](#裁剪) und [Prune](#剪除)
umhüllen.

### Budget {#预算}

**budget** · `max_budget_usd`

Die Kostenobergrenze eines Runs; wird sie überschritten, wird gestoppt. Ohne das wird ein
Long-Horizon-Run schnell teuer — [HT001](../cases/ht001.md) hat $171.62 gekostet.

---

## Portabilität

### portabel {#可移植}

**portable**

Andere Maschine, gleiches Verhalten. Erreicht durch `setting_sources=[]` — weder das `~/.claude/`
des Hosts noch das `.claude/` des Projekts wird gelesen. Domänenfähigkeiten reisen als
[Plugin](#plugin) mit dem Repo, Credentials bringt `.env` selbst mit.

Der Preis: **Credentials müssen selbst mitgebracht werden**, die Host-Konfiguration wird nicht
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
im Verzeichnis können `skills/`, `agents/`, `hooks/`, `.mcp.json` liegen. Siehe
[Deployment](deploy.md#plugin).
