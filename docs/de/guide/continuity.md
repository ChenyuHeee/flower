# Continuity

Führe `flower` im selben Verzeichnis noch einmal aus, und es redet dort weiter, wo das letzte Gespräch aufgehört hat — egal ob der Prozess gekillt wurde, das Terminal abgestürzt ist oder die Maschine neu gestartet hat. Du musst das Wort Session nicht kennen und dir keine ID merken. Diese Seite erklärt, worauf das beruht, wann es still ausfällt und wie man Continuity absichtlich abschaltet.

!!! note "Continuity ist nicht Handoff"
    [Continuity](../reference/glossary.md#接续) ist **prozessübergreifend**: Der nächste Prozess knüpft an den letzten [Run](../reference/glossary.md#运行) an.
    [Handoff](../reference/glossary.md#换代) passiert **innerhalb eines Runs**: Der Kontext ist fast voll, die aktuelle [Session](../reference/glossary.md#会话)
    schreibt ein [Handoff-Dokument](../reference/glossary.md#交接书), eine neue Session übernimmt — siehe [Handoff](handoff.md).

    Beides greift automatisch ineinander, ohne zusätzliche Verdrahtung: Die [Lineage](../reference/glossary.md#血缘) merkt sich immer die **letzte**
    Session, die den Schritt übernommen hat — beim nächsten Aufwachen wird also genau bei diesem Nachfolger angesetzt.

## Welches Problem das löst {#解决什么问题}

Auf der Platte liegt eigentlich alles. `runs/sessions.db` enthält das **vollständige** Transcript jeder historischen Session, `需求.md` / `目标.md`
sind eingefrorene Artefakte, der Code liegt im Workspace.

**Verloren geht nur eine einzige Zeile Mapping** — „welcher Schritt hat welche Session benutzt“. Die lebte früher nur im Speicher in `ctx["_sessions"]`,
und mit dem Prozess war sie weg. Der neue Prozess startet, und der [Coordinator](../reference/glossary.md#协调者) ist ein Neuling mit Gedächtnisverlust: Wen er beauftragt hat,
welche Sackgassen er schon probiert hat, warum er einen Ansatz verworfen hat — alles noch einmal von vorn.

In [HT002](../cases/ht002.md) hat er eine Stunde lang Compiler-Flags durchprobiert. Anderer Prozess, und diese Stunde ist umsonst.

## Wie man es benutzt (minimaler Code) {#怎么用最小代码}

Auf der Kommandozeile ist nichts zu konfigurieren, auf dem Pfad `flower` ist Continuity standardmäßig an:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # das erste Mal
# …fertig, oder du steigst mit Ctrl-C aus, oder die Maschine startet neu

cd ~/proj && flower "顺便支持代码块高亮"          # macht beim letzten Gespräch weiter
cd ~/proj && flower                              # nichts sagen = einfach weitermachen
cd ~/proj && flower --new "另一件事"              # diesmal nicht anknüpfen
```

Auch in eigenen [Workflows](../reference/glossary.md#流程) ist Continuity standardmäßig an — der Default von `Workflow.continuous` ist
`True`:

```python
import asyncio

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous ist standardmäßig True
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # das wievielte Aufwachen; beim ersten Lauf 1
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

Führst du denselben Code im selben Verzeichnis ein zweites Mal aus, ist `ctx["_woke"]` gleich `2`, und `ctx["_sessions"]["取词"]` ist
**dieselbe ID** wie beim ersten Mal — der Schritt `取词` hat die letzte Session fortgesetzt, statt eine neue zu eröffnen.

!!! tip "Nur wissen, ob dieses Verzeichnis anknüpfen kann"
    `wake_state()` ist eine reine Lese-Sonde und schreibt **kein einziges Byte**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    Zurück kommt `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = Brief existiert und alle vier Abschnitte sind vorhanden;
    `checks` = Anzahl der Einträge in der Prüfliste; `woke` = wie oft schon aufgewacht wurde; `steps` = Mapping von Schrittname auf session_id.
    Die Kommandozeile entscheidet damit, ob der Prompt „was soll getan werden“ fragt oder „weitermachen“.

## Was es tatsächlich tut {#它实际做了什么}

### Die drei Dateien auf der Platte {#落在磁盘上的三个文件}

`run_dir` ist standardmäßig `./runs`, **relativ zum aktuellen Arbeitsverzeichnis, nicht relativ zum Workspace**.

| Pfad | Inhalt |
|---|---|
| `runs/lineage.json` | Lineage: `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Continuity hängt komplett daran |
| `runs/sessions.db` | SQLite, vollständige Transcripts. Tabellen sind `entries` / `meta` / `summaries`, Key ist `project_key/session_id[/subpath]` — Subagent-Transcripts werden über den subpath getrennt abgelegt |
| `runs/manifest.json` | JSON-Array, **prozessübergreifend akkumulierendes** Run-Manifest. Eine Zeile pro Schritt, die einzige Stelle, um im Nachhinein eine session_id nachzuschlagen |

Die Lineage-Datei sieht so aus:

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

Jede Zeile in `manifest.json` enthält alle Felder von `StepResult` — `step`, `session_id`, `ok`, `cost_usd`,
`num_turns`, `text`, `error`, `started_at`, `ended_at`, `attempts`, `errors[]`, `resumed`,
`retired[]`, `context` — plus manuell ergänzt `duration_s` (eine `@property`, die `asdict()` nicht erfasst) und
`run` (Prozessmarke, `YYYYmmdd-HHMMSS-<6 Stellen hex>`).

Der Schrittname kommt darin in vier Formen vor, an denen man sofort sieht, wie dieser Schritt zu Ende gegangen ist: `<步骤名>` (erster Versuch),
`<步骤名>#retry<N>` (normaler Retry), `<步骤名>#round<N>` (Verdict nicht bestanden, zurückgeschickt und weitergemacht),
`<步骤名>·判定#<N>` (die Runde des [Judge](../reference/glossary.md#判定者)).

Geschrieben wird **anhängend, nicht überschreibend**: Vor jedem Schreiben wird die Datei neu eingelesen und anhand des Feldes `run` dedupliziert — die Zeilen dieses Prozesses werden durch die aktuellen ersetzt,
fremde Zeilen bleiben unverändert stehen. Mehrere flower-Instanzen parallel im selben Verzeichnis sind daher sicher.

### `continuous=True` ändert die Semantik von `resume_from` {#continuoustrue-改变了-resume_from-的语义}

Das wird am leichtesten übersehen: `Workflow.continuous` ist standardmäßig `True`, und damit bedeutet `resume_from=None`
**nicht „frische Session“**.

| Schreibweise | Innerhalb eines Runs | Prozessübergreifend (`continuous=True`) |
|---|---|---|
| `resume_from=None` (Default) | Neue Session, nur mit dem im Prompt übergebenen Kontext | **Setzt die Session des gleichnamigen Schritts aus der Lineage fort** |
| `resume_from="上一步名"` | Setzt dieselbe Session fort, voller Kontext | wie links |
| `resume_from=…, fork=True` | Fork, verschmutzt die Originalsession nicht | wie links |

Damit jeder Prozess mit einer sauberen neuen Session startet, muss man explizit `Workflow(..., continuous=False)` schreiben.

Beim Laden der Lineage gibt es zusätzlich eine Prüfung: Für jedes eingelesene `(步骤名, session_id)` wird zuerst per `runtime.has_session(sid)`
bestätigt, dass es noch in `sessions.db` liegt; nur was lebt, wird benutzt. Grund: Die Lineage-Datei kann `sessions.db` überleben,
und ein Resume auf eine nicht existierende Session fliegt erst auf, wenn der Subprozess hochgekommen ist.

!!! warning "Der Schrittname ist der prozessübergreifend stabile Schlüssel"
    Die Lineage indiziert nach `Step.name`. **Einen Schrittnamen ändern heißt die Lineage kappen** — es gibt keinen Fehler, der nächste Lauf ist einfach eine frische Session.
    Namen mit Suffix (`#retry`, `#round`, `·判定#`) landen nicht in der Lineage, `Lineage.remember` benutzt immer den Originalnamen.

### Zwei Invarianten {#两条不变式}

**Erstens: Sobald die session_id da ist, wird sofort auf Platte geschrieben — nicht erst, wenn der Schritt fertig ist.**

Der hart gekillte Prozess ist genau das Szenario, gegen das man sich absichert. In der Praxis reingefallen: Am 2026-09-07 ist Terminal.app zweimal abgestürzt, der Kernel schickt SIGHUP,
und die Default-Aktion von SIGHUP ist sofortiges Beenden — `finally` läuft keine Zeile. Damals wurde die Lineage an **Schrittgrenzen** geschrieben,
also war bei dem Lauf, der noch im ersten Schritt starb, `steps` leer, und der Mensch musste Fragen erneut beantworten, die er längst beantwortet hatte (siehe Issue #6).

Heute schreibt `Runtime.on_session` in dem Moment auf Platte, in dem die ID vorliegt — faktisch frühestens bei der ersten Assistant-Nachricht,
denn die init-Systemnachricht trägt im Python-SDK keine `session_id`. Geschrieben wird erst nach `.tmp` und dann atomar ersetzt,
ein Kill mittendrin hinterlässt also keine halbe Datei; schlägt das Schreiben fehl (`OSError`), wird das still geschluckt und reißt den Lauf nicht mit.

Dieser Hook **umschließt nur die eine Zeile `runtime.run`**, vor dem Gate wird er per `try/finally` wieder abgehängt. Der Judge benutzt dasselbe
`Runtime`; hinge der Hook noch dran, würde seine Session in die Lineage des Arbeitsschritts geschrieben.

**Zweitens: Passt es nicht zusammen, gilt es als nicht vorhanden — kein Fehler.**

Drei Arten von Nichtübereinstimmung: Der Workspace-Pfad hat sich geändert (Verzeichnis wurde weggeschoben — [HT001](../cases/ht001.md) wurde genau so aus einem Container herauskopiert),
die Session liegt nicht mehr in der Datenbank (`sessions.db` gelöscht), oder die Lineage-Datei ist kaputt. Jeder dieser Fälle fällt still auf „von vorn anfangen“ zurück.

Das Feld `workspace` ist die Wache: Der `project_key` des SDK wird aus dem Workspace-Pfad abgeleitet (`/`, `_`, `.` werden alle zu `-`),
nach dem Verschieben des Verzeichnisses ist die alte session_id am neuen Ort schlicht nicht auffindbar — passt der Pfad nicht, gilt sie als nicht vorhanden.

**Continuity ist Kür; wenn sie ausfällt, darf sie niemanden an der Arbeit hindern.**

### Prozess gekillt, und Maschine neu gestartet {#进程被杀和机器重启}

Das Ergebnis ist in beiden Fällen dasselbe — es wird angeknüpft — aber der Weg dorthin unterscheidet sich:

| Fall | Was passiert | Nächster Lauf |
|---|---|---|
| `Ctrl-C` einmal | Kooperativer Abbruch, sauberer Ausstieg an einer **Nachrichtengrenze**. Man kann dabei etwas sagen und im selben Prozess dieselbe Session per Resume weiterlaufen lassen. Ein Abbruch zählt nicht als fehlgeschlagener Versuch und verbraucht kein Retry-Kontingent | Continuity nicht betroffen |
| `Ctrl-C` zweimal | Wirft direkt `KeyboardInterrupt` und beendet. Das Aufräumen kommt nur bis zum Schließen des Stores, **der laufende Schritt landet nicht in `manifest.json`** | Die Lineage war längst geschrieben, es wird angeknüpft |
| `SIGTERM` / `SIGHUP` | Der Handler ruft zuerst `rescue()` auf, schreibt den laufenden Schritt ebenfalls in `manifest.json` (mit `error="killed-by-signal"`), stellt dann die Default-Aktion wieder her und geht wirklich | wie oben, es wird angeknüpft |
| `SIGKILL`, Stromausfall, Neustart | Gar kein Aufräumen | Wird genauso angeknüpft — alle drei Dateien liegen auf der Platte, die Lineage wurde in dem Moment geschrieben, in dem die ID da war |

Es gibt nur eine Voraussetzung: **derselbe `workspace` plus derselbe `run_dir`**. `run_dir` ist relativ zum aktuellen Arbeitsverzeichnis,
ein `flower` aus einem anderen Verzeichnis sucht also ein anderes `runs/` und knüpft nicht an.

### Der Judge ist immer eine neue Session {#判定者永远是新会话}

Das ist **konstruktiv garantiert**, nicht eine Frage des Daran-Denkens.

Der Judge ist kein `Step` — er wird im Gate von `with_goal` direkt per `rt.run()` beauftragt
(siehe [Goal guard](goal.md)) und geht nie über den Lineage-Pfad. Deshalb ist er in jeder Runde und bei jedem Aufwachen ein frisches Augenpaar.

Genau darin liegt sein ganzer Wert: **Er weiß nicht, wie oft und wie mühsam der Worker es versucht hat, und findet deshalb keine Entschuldigungen für ihn.**
Ließe man ihn an der Continuity teilhaben, würde der Goal guard zur Selbstauditierung verkommen.

Abschnitt 4 von `tests/lineage_offline.py` nagelt das fest.

### Der Satz beim Aufwachen muss an drei Stellen landen {#唤醒时说的那句话要落到三个地方}

`flower "顺便支持代码块高亮"` in einem bereits benutzten Verzeichnis ist **keine neue Aufgabe, sondern ein weiterer Satz**.
Es tut drei Dinge gleichzeitig — fehlt eines davon, fällt es still aus:

| Wohin | Was passiert, wenn es fehlt |
|---|---|
| Angehängt an `需求.md` (`## 唤醒时追加`) | Überlebt die Schrittgrenze nicht. Der nächste Schritt ist eine neue Session und liest nur die eingefrorenen Artefakte |
| Als Prompt des Arbeitsschritts | Der Coordinator bekommt es überhaupt nicht mit |
| **Löst eine Neuableitung von `目标.md` aus** | Der Judge liest weiter die alte Prüfliste, **ob das Neue erledigt wurde, kommt gar nicht erst ins Verdict** |

Der dritte Punkt wird am leichtesten vergessen. Der Judge liest nur das eingefrorene `目标.md`, was du mittendrin ergänzt hast, sieht er nicht — ohne Neuableitung urteilt er anhand der alten Liste
„erreicht“, während genau das, was du wolltest, nie geprüft wurde. Der Preis ist ein zusätzlicher Durchlauf des Zielsetzungsschritts pro Ergänzung (in [HT002](../cases/ht002.md) gemessen:
$0.41 / 3 Minuten).

**Aufwachen ohne etwas zu sagen** (einfach Enter) hängt nichts an, leitet nichts neu ab und kostet keinen Cent extra.

### Auch ein Absturz innerhalb des ersten Schritts (确认需求) knüpft an {#崩在第一步确认需求之内也能接上}

`clarify_step` hat einen `resume_prompt` (Konstante `CLARIFY_RESUME`): Startet man nach einem Absturz mitten in der Klärung neu,
sagt es dem [Clarifier](../reference/glossary.md#确认者) „mach mit der eben nicht zu Ende geführten Bedarfsklärung weiter —
fang nicht von vorn an“, statt das ursprüngliche Anliegen als neue Aufgabe erneut zu schicken. Zusammen mit der Regel oben („session_id da, sofort auf Platte“)
knüpft nun auch der Lauf an, der im ersten Schritt gestorben ist, bevor `需求.md` eingefroren war — ohne erneutes Beantworten.

Umgekehrt werden bereits eingefrorene Vorstufen **als ganzer Schritt übersprungen**: Sind alle vier Abschnitte von `需求.md` vorhanden, entfällt 确认需求 (der Inhalt fließt trotzdem in ctx),
ist `目标.md` vollständig, entfällt 设定目标.

### Beim Anknüpfen wird nicht derselbe Satz geschickt {#接续时发的不是同一句话}

Dafür ist `Step.resume_prompt` da. Im Kontext des Gegenübers **stehen bereits** Brief, Ziel und der Stand der letzten Arbeit; ein erneutes wörtliches
„Arbeite nach diesem Bedarf: <ganzer Brief>“ ist reines Rauschen, und schlimmer noch: Es wird als „der Bedarf hat sich geändert, sieh es dir noch mal an“ gelesen.

Ohne `resume_prompt` wird `prompt` weiterverwendet — manche Schritte sollen den Volltext ohnehin erneut schicken (wenn 设定目标 die Liste neu ableitet,
braucht es genau den vollständigen Brief).

### Beim Aufwachen erst eine Zeile melden {#唤醒时先报一行}

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Ohne diese Meldung ist „erinnert es sich denn nun oder nicht“ völlig unspürbar — und genau darin liegt der ganze Wert dieser Schicht. Im Banner steht
`需求已确认` immer, `目标 N 条` nur bei nicht leerer Prüfliste, und `干活上下文 X` setzt voraus, dass sich aus `sessions.db`
die Kontextgröße der letzten Runde jener Session ermitteln lässt.

**Diese Kontextzahl steht bewusst da** — der Grund folgt im Abschnitt „Preis“.

### Resilience: Bei Netzausfall warten, und Fehler kommen nicht in den Kontext nach dem Resume {#韧性断网时挂着等而且错误不进接续后的上下文}

[Resilience](../reference/glossary.md#韧性) und Continuity gehören zusammen: Wer stundenlang läuft, verliert zwangsläufig einmal die Verbindung, und das Default-Verhalten ist übel —
im Moment des Abrisses schiebt die Harness eine **synthetische Assistant-Nachricht** ins Transcript (`isApiErrorMessage=true`,
`model="<synthetic>"`) mit dem Text „API Error: Can't reach the API server …“. Diese Nachricht wird zum Blatt der Session,
und beim späteren Resume wird sie als „was das Modell zuletzt gesagt hat“ zurückgefüttert — das Modell glaubt dann, es diskutiere gerade einen Netzwerkfehler.

`Resilience` tut drei Dinge:

**Erstens: Die Sonde macht nur DNS + TCP.** `reachable(host, port, timeout=5.0)` führt nur `getaddrinfo` und einen TCP-Handshake aus,
**kein HTTP, keine Credentials, keine Kosten**; jede Exception zählt als nicht erreichbar. Welche Adresse gesondet wird, bestimmt `endpoint()`, das sich nach
`ANTHROPIC_BASE_URL` richtet, Default `https://api.anthropic.com`, Port standardmäßig `443` (bei http `80`).
**Mit eigenem Gateway muss zwingend das Gateway gesondet werden** — dass `api.anthropic.com` erreichbar ist, sagt nichts über das Gateway.

**Zweitens: Trennen, was Warten verdient, und was Abbruch verdient.** `classify(text)` liefert `"transient"` / `"fatal"` / `"unknown"`,
**erst fatal prüfen, dann transient** — Texte wie bei 401 enthalten oft das Wort „connection“, in umgekehrter Reihenfolge wartet man ewig.
Defaults: `max_attempts=6` (inkl. erstem Versuch), `base_delay=4.0`, `max_delay=120.0`, `probe_timeout=5.0`,
`probe_interval=15.0`, `max_offline_wait=3600.0` (1 Stunde), `retry_unknown=True`.
Das Backoff ist `min(base_delay * 2**(attempt-1), max_delay)`, multipliziert mit ±25% Jitter.

Liegt bereits eine session_id vor, wird **per Resume fortgesetzt statt neu begonnen**, die bisherigen Kosten sind nicht umsonst. Beim Fortsetzen wird
`Resilience.resume_prompt` geschickt: „Die letzte Runde wurde mittendrin unterbrochen und nicht zu Ende geführt. Sieh nach, was in der Workbench bereits auf Platte liegt,
und mach an der Abbruchstelle weiter, fang nicht von vorn an.“ Er enthält **absichtlich keinerlei Fehlerdetails** — das Modell muss wissen „unterbrochen, weitermachen“,
nicht ob es ENOTFOUND oder 503 war.

**Drittens: Die Fehlermeldungen aus dem Retry-Sturm kommen nicht in den Kontext nach dem Resume.** Das ist die Aufgabe von [Prune](../reference/glossary.md#剪除).
Der Session Store von `Runtime` ist fest auf `PruningSessionStore` verdrahtet, der beim `load()` drei Dinge tut:

- Synthetische API-Fehlermeldungen entfernen. **In SQLite bleiben sie unverändert erhalten**, sie werden nur nicht zurückgefüttert
- Zu alte abgelehnte Aufrufe entfernen, nur die letzten `keep_denials=1` bleiben
- Bei Abbruch übrig gebliebene `tool_result` durch den neutralen Hinweis „[上一轮在此处被中断,该工具结果未产生]“ ersetzen; nur der Text wird ersetzt, der Eintrag bleibt

Dass 1 statt 0 behalten wird, hat einen Grund: Ein abgelehnter Aufruf wurde nie ausgeführt, im Ergebnis steht keine Information, aber er belegt einiges an Platz
(gemessen einmal 273 Zeichen = 93 Zeichen Ablehnungstext + 180 Zeichen **Originaltext des abgelehnten Befehls**), und **er führt in die Irre** —
gemessen: Nachdem der Coordinator ein paar Mal „Bash nicht direkt verwenden“ gelesen hatte, versuchte er nicht einmal mehr das freigegebene `git status` — erlernte Hilflosigkeit.
Der jüngste Eintrag ist aber nützlich: Er verhindert, dass das Modell in derselben Runde wieder und wieder denselben geblockten Befehl versucht.

Beim Entfernen gibt es eine strukturelle rote Linie: Das Transcript ist eine einfach verkettete `parentUuid`-Liste; wer einen Eintrag entfernt, muss dessen Kinder an den nächsten überlebenden Vorfahren hängen,
sonst reißt die Kette dort ab und die gesamte vorherige Historie ist weg.

In [HT001](../cases/ht001.md) ist das einmal real eingetreten: Netzausfall-Zeitachse 01:52:40 → 01:55:41, der Schritt steht in `manifest.json` mit
`attempts=2` / `resumed=True` / `ok=True`, und lief nach dem Resume noch über 8 Stunden bis zur Fertigstellung.

Ein letzter, leicht misszuverstehender Punkt: **`Runtime(trim=False)` heißt nicht „es wird nichts bereinigt“**. `trim` ist standardmäßig `False`,
aber es schaltet nur die Schicht **[Trim](../reference/glossary.md#裁剪) großer Tool-Ergebnisse** ab. Abrissreste entfernen, abgelehnte Aufrufe entfernen,
Abbruchreste neutralisieren, Ergebnisse von [Ephemeral commands](../reference/glossary.md#一次性命令) als veraltet markieren — diese vier passieren weiterhin
(`ephemeral` ist standardmäßig `True`, `keep_denials` standardmäßig `1`).

### Preis: Der Kontext wächst immer weiter, und zwar ohne Ende {#代价上下文会一直涨而且没有尽头}

Das ist der inhärente Preis von Continuity, kein Bug.

Der Schritt „干活“ in [HT001](../cases/ht001.md) lief 10.44 Stunden am Stück, der Kontext auf dem [Main thread](../reference/glossary.md#主线程) lag
in Runde 1 bei **28.7K**, in Runde 20 bei **35.2K**, in Runde 35 bei **108.6K**, in Runde 50 bei **158.2K**, in Runde 70 bei **185.9K**,
monoton steigend, Steigung etwa **2.2K/Runde**; durchgehend nicht komprimiert, verbraucht wurden **18.6%** des 1M-Fensters. Extrapoliert man diese Steigung,
kommt die Wand bei etwa **440 Runden** — die Obergrenze von „long-horizon“ in der aktuellen Form liegt etwa beim **6-fachen** jenes Laufs. Dauerhafte Continuity heißt: Irgendwann trifft man das Fenster.

Zwei Schichten halten das im Griff:

1. **Trim** (`flower --no-trim` schaltet es ab, auf dem Pfad `flower` ist es standardmäßig an) — beim Resume werden alte große Tool-Ergebnisse durch
   Dateizeiger ersetzt, der Inhalt ist nicht weg, er liegt nur nicht mehr dauerhaft im Kontext
2. **[Handoff](handoff.md)** — am Schwellwert wird ein Handoff-Dokument geschrieben und auf eine neue Session gewechselt. **Das ist kein [Compact](../reference/glossary.md#压缩)**:
   Das Dokument ist lesbar und änderbar, du siehst, was verloren geht. Der Kontext fällt dadurch periodisch zurück, statt bis zur Wand durchzusteigen

**Deshalb muss die Aufwachzeile die Kontextzahl melden**: Nur wer sie sieht, kann vor der Wand selbst entscheiden, neu zu beginnen.

Nebenbei: `--rounds` (Gesamtrundenzahl der Arbeit) **wird bei jedem Aufwachen zurückgesetzt**. Das ist Absicht — ein neues Aufwachen ist eine neue Absicht
und soll die letzte verbrauchte Rundenzahl nicht erben.

### Eine Sache neu beginnen {#重开一件事}

```bash
flower --new "另一件事"
```

Oder im Aufwach-Prompt direkt `/new` tippen:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> /new
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> …
```

**Archivieren, nicht löschen.** `lineage.json`, `需求.md` und `目标.md` werden gemeinsam nach `notes/archive/<YYYYmmdd-HHMMSS>/` **verschoben**,
und `steps` sowie `woke` der Lineage werden gleichzeitig zurückgesetzt. Die drei sind drei Seiten derselben Historie; nur einen Teil davon einzusammeln hinterlässt einen halben Zustand
nach dem Muster „das Ziel ist noch da, aber das Gespräch ist weg“.

`sessions.db` bleibt unangetastet — es ist das Archiv, jedes Transcript darin ist weiterhin abfragbar.

Im Code entspricht dem `Lineage.archive(into, extra=[...])`.

## Wann man es nicht benutzen sollte {#什么时候不该用它}

- **Szenarien, die jedes Mal einen sauberen Start verlangen.** Denselben Workflow im Batch fahren, Vergleichsevaluationen, jemandem einen Bug reproduzierbar machen —
  nichts davon sollte den Kontext des letzten Laufs mitschleppen. Schreibe `Workflow(..., continuous=False)` oder benutze jedes Mal ein anderes `run_dir`.
- **Das Verzeichnis wird verschoben oder kopiert, oder `run_dir` ist nicht persistent.** Läuft es in einem Container und liegt `runs/` auf dessen innerem Dateisystem,
  oder wird der Workspace per rsync auf eine andere Maschine gebracht — dann **fällt Continuity still aus** (die Pfadwache verwirft die nicht passende Lineage),
  behandle es nicht als Garantie.
- **Diesmal ist es eine neue Absicht, und der Kontext ist schon groß.** Continuity schleppt die irrelevante Historie mit, und du zahlst in jeder Runde Token dafür.
  Statt es auszuhalten, lieber mit `--new` archivieren und neu beginnen.
- **Einmaliger Single-Agent-Lauf.** `flower once` geht nicht über `Workflow` und hat keine Lineage; zum Fortsetzen musst du selbst `--resume <session_id>` angeben.
- **Continuity als Backup missbrauchen.** Sie merkt sich nur, „welcher Schritt welche Session benutzt hat“. Code, Ergebnisse und Entscheidungen gehören in den Workspace und
  die [Workbench](../reference/glossary.md#工作台) und sollten nicht aus dem Transcript ausgegraben werden müssen.

## Was als Nächstes lesen {#相关}

- [Handoff](handoff.md) — was zu tun ist, wenn der Kontext innerhalb eines Runs voll wird; dieselbe Sache aus der anderen Richtung
- [Goal guard](goal.md) — warum der Judge nicht an der Continuity teilnimmt
- [Kontextökonomie](context.md) — wofür Trim, Prune und Spill jeweils zuständig sind
- [Python API](../reference/api.md) — `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Kommandozeile](../reference/cli.md) — `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Quellcode: [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
