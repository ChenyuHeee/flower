# Kontinuität

Führe `flower` im selben Verzeichnis noch einmal aus, und es spricht dort weiter, wo das letzte Gespräch aufgehört hat — egal ob der Prozess gekillt wurde, das Terminal abgestürzt ist oder die Maschine neu gestartet hat. Du musst das Wort session nicht kennen und dir keine id merken. Diese Seite erklärt, worauf das beruht, wann es stillschweigend ausfällt und wie man Kontinuität absichtlich vermeidet.

!!! note "Kontinuität ist kein Handoff"
    [Kontinuität](../reference/glossary.md#接续) ist **prozessübergreifend**: der nächste Prozess knüpft an den letzten [Lauf](../reference/glossary.md#运行) an.
    Der [Handoff](../reference/glossary.md#换代) ist **innerhalb desselben Laufs**: der Kontext läuft voll, die aktuelle [Session](../reference/glossary.md#会话)
    schreibt ein [Handoff-Dokument](../reference/glossary.md#交接书), eine neue Session übernimmt — siehe [Handoff](handoff.md).

    Beides greift automatisch ineinander, es ist keine zusätzliche Verdrahtung nötig: die [Lineage](../reference/glossary.md#血缘) merkt sich immer die Session, die diesen Schritt **zuletzt** übernommen hat — der nächste Weckvorgang knüpft also an den Nachfolger an.

## Welches Problem das löst {#解决什么问题}

Auf der Platte ist eigentlich alles da. `runs/sessions.db` enthält das **vollständige** Transcript jeder historischen Session, `需求.md` / `目标.md` sind eingefrorene Dokumente, der Code liegt im Arbeitsbereich.

**Verloren geht nur eine einzige Zuordnungszeile** — „welcher Schritt hat welche Session benutzt“. Die lebte bisher nur im Speicher in `ctx["_sessions"]` und war mit dem Prozessende weg. Also startet der neue Prozess, und der [Koordinator](../reference/glossary.md#协调者) ist ein Neuling mit Gedächtnisverlust: wen er beauftragt hat, welche Sackgassen er schon durchprobiert hat, warum er einen Ansatz verworfen hat — alles noch einmal von vorn.

In [HT002](../cases/ht002.md) hat er eine Stunde lang mit Compiler-Flags herumprobiert. Ein anderer Prozess, und diese Stunde war umsonst.

## Wie man es benutzt (minimaler Code) {#怎么用最小代码}

Auf der Kommandozeile ist nichts zu konfigurieren, auf dem Pfad `flower` ist Kontinuität standardmäßig an:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # Das erste Mal
# …fertig gelaufen, oder du gehst mit Ctrl-C, oder die Maschine startet neu

cd ~/proj && flower "顺便支持代码块高亮"          # Setzt das letzte Gespräch fort
cd ~/proj && flower                              # Gar nichts sagen = einfach weitermachen
cd ~/proj && flower --new "另一件事"              # Diesmal nicht anknüpfen
```

Auch in eigenen [Workflows](../reference/glossary.md#流程) ist Kontinuität voreingestellt — der Default von `Workflow.continuous` ist
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
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous ist per Default True
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # Der wievielte Weckvorgang; beim ersten Lauf 1
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

Führst du diesen Code im selben Verzeichnis ein zweites Mal aus, ist `ctx["_woke"]` gleich `2`, und `ctx["_sessions"]["取词"]` ist **dieselbe id** wie beim ersten Mal — der Schritt „取词“ hat die letzte Session fortgesetzt statt eine neue zu öffnen.

!!! tip "Nur wissen wollen, ob dieses Verzeichnis anknüpfen kann"
    `wake_state()` ist eine Nur-Lese-Sonde und schreibt **kein einziges Byte**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    Zurück kommt `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = das Anforderungsdokument existiert und alle vier Abschnitte sind vollständig;
    `checks` = wie viele Einträge die Prüfliste hat; `woke` = wie oft schon aufgeweckt wurde; `steps` = Zuordnung von Schrittnamen zu session_id.
    Die Kommandozeile entscheidet damit, ob der Prompt „Was soll getan werden?“ oder „Weiter wie zuletzt?“ fragt.

## Was es tatsächlich tut {#它实际做了什么}

### Die drei Dateien auf der Platte {#落在磁盘上的三个文件}

`run_dir` ist per Default `./runs`, **relativ zum aktuellen Arbeitsverzeichnis, nicht relativ zum workspace**.

| Pfad | Inhalt |
|---|---|
| `runs/lineage.json` | Lineage: `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Die Kontinuität hängt vollständig daran |
| `runs/sessions.db` | SQLite, vollständige Transcripts. Tabellen sind `entries` / `meta` / `summaries`, der key ist `project_key/session_id[/subpath]` — Subagent-Transcripts werden über subpath getrennt abgelegt |
| `runs/manifest.json` | JSON-Array, das **prozessübergreifend akkumulierte** Run-Manifest. Eine Zeile pro Schritt; die einzige Stelle, an der man im Nachhinein eine session_id findet |

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
`retired[]`, `context` — plus die manuell ergänzten `duration_s` (ist ein `@property`, `asdict()` bekommt es nicht mit) und
`run` (Prozessmarke, `YYYYmmdd-HHMMSS-<6 位 hex>`).

Schrittnamen treten dort in vier Formen auf, an denen man sofort sieht, wie der Schritt zu Ende gegangen ist: `<步骤名>` (erster Versuch),
`<步骤名>#retry<N>` (normaler Retry), `<步骤名>#round<N>` (Verdikt nicht bestanden, zurückgeschickt und weitergearbeitet),
`<步骤名>·判定#<N>` (die Runde des [Judge](../reference/glossary.md#判定者)).

Geschrieben wird **anhängend, nicht überschreibend**: bei jedem Schreiben wird die Datei neu eingelesen und über das Feld `run` dedupliziert — Zeilen dieses Prozesses werden durch die aktuellen ersetzt, fremde Zeilen bleiben unangetastet. Mehrere flower-Instanzen parallel im selben Verzeichnis sind damit sicher.

### `continuous=True` ändert die Semantik von `resume_from` {#continuoustrue-改变了-resume_from-的语义}

Das wird am leichtesten übersehen: `Workflow.continuous` ist per Default `True`, also bedeutet `resume_from=None`
**nicht „ganz neue Session“**.

| Schreibweise | Innerhalb desselben Laufs | Prozessübergreifend (`continuous=True`) |
|---|---|---|
| `resume_from=None` (Default) | Neue Session, nur mit dem im Prompt übergebenen Kontext | **Nimmt die Session des gleichnamigen Schritts aus der Lineage und setzt sie fort** |
| `resume_from="上一步名"` | Setzt dieselbe Session fort, voller Kontext | wie links |
| `resume_from=…, fork=True` | Fork, verschmutzt die Originalsession nicht | wie links |

Wenn jeder Prozess mit einer sauberen neuen Session starten soll, muss man `Workflow(..., continuous=False)` explizit hinschreiben.

Beim Laden der Lineage gibt es noch eine Prüfung: für jedes eingelesene `(Schrittname, session_id)` wird zuerst per `runtime.has_session(sid)` bestätigt, dass es noch in `sessions.db` liegt; nur was lebt, wird benutzt. Grund: die Lineage-Datei kann `sessions.db` überleben, und ein resume auf eine nicht existierende Session fliegt einem erst um die Ohren, wenn der Subprozess schon läuft.

!!! warning "Der Schrittname ist der prozessübergreifend stabile Schlüssel"
    Die Lineage indiziert nach `Step.name`. **Den Schrittnamen zu ändern heißt, die Lineage zu kappen** — es gibt keinen Fehler, der nächste Lauf ist einfach eine ganz neue Session.
    Namen mit Suffix (`#retry`, `#round`, `·判定#`) landen nicht in der Lineage, `Lineage.remember` benutzt immer den Originalnamen.

### Zwei Invarianten {#两条不变式}

**Erstens: Sobald die session_id da ist, wird sofort auf Platte geschrieben — nicht erst, wenn der Schritt fertig ist.**

Ein hart gekillter Prozess ist genau das Szenario, gegen das das schützt. In der Praxis ist es schiefgegangen: am 2026-09-07 ist Terminal.app zweimal abgestürzt, der Kernel schickte SIGHUP, und die Default-Aktion von SIGHUP ist sofortiges Beenden — kein einziges `finally` läuft. Damals wurde die Lineage an **Schrittgrenzen** geschrieben, also war `steps` bei einem Lauf, der innerhalb des ersten Schritts starb, leer, und der Mensch musste Fragen erneut beantworten, die er längst beantwortet hatte (siehe issue #6).

Heute schreibt `Runtime.on_session` in dem Moment auf Platte, in dem die id da ist — faktisch frühestens bei der ersten assistant-Nachricht, denn die init-Systemnachricht trägt im Python-SDK keine `session_id`. Geschrieben wird erst nach `.tmp` und dann atomar ersetzt; ein Kill auf halber Strecke hinterlässt keine halbe Datei. Schlägt das Schreiben fehl (`OSError`), wird das still geschluckt und reißt den Lauf nicht mit.

Dieser Hook deckt **nur die eine Zeile `runtime.run`** ab, vor dem Gate wird er per `try/finally` abgehängt. Der Judge benutzt dasselbe `Runtime`; hinge der Hook noch, würde seine Session in die Lineage des Arbeitsschritts geschrieben.

**Zweitens: Passt etwas nicht zusammen, gilt es als nicht vorhanden — kein Fehler.**

Drei Arten von Nichtzusammenpassen: der Pfad des Arbeitsbereichs hat sich geändert (Verzeichnis wurde weggekopiert — [HT001](../cases/ht001.md) wurde genau so aus einem Container herauskopiert), die Session ist nicht mehr in der Datenbank (`sessions.db` gelöscht), oder die Lineage-Datei ist kaputt. Jeder dieser Fälle fällt still auf „von vorn anfangen“ zurück.

Das Feld `workspace` ist die Wache: der `project_key` des SDK wird aus dem Pfad des Arbeitsbereichs abgeleitet (`/`, `_`, `.` werden alle zu `-`); nachdem das Verzeichnis weggekopiert wurde, ist die alte session_id am neuen Ort schlicht nicht auffindbar — passt der Pfad nicht, gilt sie als nicht vorhanden.

**Kontinuität ist das Sahnehäubchen; wenn sie ausfällt, darf sie niemanden bei der Arbeit aufhalten.**

### Prozess gekillt, und Maschine neu gestartet {#进程被杀和机器重启}

Das Ergebnis ist dasselbe — beides lässt sich fortsetzen — der Ablauf unterscheidet sich:

| Situation | Was passiert | Nächster Lauf |
|---|---|---|
| `Ctrl-C` einmal | Kooperativer Abbruch, sauberer Schnitt an der **Nachrichtengrenze**. Man kann bei der Gelegenheit noch etwas sagen und im selben Prozess dieselbe Session resumen. Ein Abbruch zählt nicht als fehlgeschlagener Versuch und verbraucht kein Retry-Kontingent | Kontinuität nicht betroffen |
| `Ctrl-C` zweimal | Wirft direkt `KeyboardInterrupt` und beendet. Es wird nur noch der Store geschlossen, **der fliegende Schritt landet nicht in `manifest.json`** | Die Lineage war längst auf Platte, es knüpft an |
| `SIGTERM` / `SIGHUP` | Der Handler ruft zuerst `rescue()` und schreibt auch den fliegenden Schritt in `manifest.json` (markiert mit `error="killed-by-signal"`), stellt dann die Default-Aktion wieder her und geht wirklich | wie oben, es knüpft an |
| `SIGKILL`, Stromausfall, Neustart der Maschine | Überhaupt kein Aufräumen | Knüpft genauso an — alle drei Dateien liegen auf der Platte, und die Lineage wurde in dem Moment geschrieben, in dem die id da war |

Es gibt nur eine Voraussetzung: **derselbe `workspace` plus dasselbe `run_dir`**. `run_dir` ist relativ zum aktuellen Arbeitsverzeichnis, ein `flower` aus einem anderen Verzeichnis sucht also ein anderes `runs/` und knüpft nicht an.

### Der Judge ist immer eine neue Session {#判定者永远是新会话}

Das ist **konstruktiv garantiert**, nicht Sache der Disziplin.

Der Judge ist kein `Step` — er wird im Gate von `with_goal` direkt per `rt.run()` losgeschickt
(siehe [Zielwächter](goal.md)) und läuft nie über den Lineage-Pfad. Deshalb ist er in jeder Runde und bei jedem Weckvorgang ein frisches Paar Augen.

Genau darin liegt sein ganzer Wert: **Er weiß nicht, wie oft der Worker es versucht hat und wie mühsam es war — also sucht er auch keine Ausreden für ihn.**
Ließe man ihn an der Kontinuität teilnehmen, verkäme der Zielwächter zur Selbstprüfung.

Abschnitt 4 von `tests/lineage_offline.py` nagelt das fest.

### Der Satz beim Aufwecken muss an drei Stellen ankommen {#唤醒时说的那句话要落到三个地方}

`flower "顺便支持代码块高亮"` in einem schon benutzten Verzeichnis ist **keine neue Aufgabe, sondern ein weiterer gesagter Satz**.
Es tut drei Dinge gleichzeitig — fehlt eines davon, fällt es still aus:

| Wohin es geht | Was passiert, wenn es fehlt |
|---|---|
| Wird an `需求.md` angehängt (`## 唤醒时追加`) | Überlebt die Schrittgrenze nicht. Der nächste Schritt ist eine neue Session und liest nur das eingefrorene Dokument |
| Wird als Prompt des Arbeitsschritts benutzt | Der Koordinator bekommt es überhaupt nicht zu sehen |
| **Löst eine Neuableitung von `目标.md` aus** | Der Judge liest weiter die alte Prüfliste, **ob das neu Hinzugefügte erledigt ist, wird gar nicht erst geprüft** |

Der dritte Punkt wird am leichtesten übersehen. Der Judge liest nur das eingefrorene `目标.md`; was du unterwegs hinzugefügt hast, sieht er nicht — ohne Neuableitung urteilt er nach der alten Liste „erreicht“, während genau die Sache, die du wolltest, nie verifiziert wurde. Der Preis ist ein zusätzlicher Lauf von Ziele setzen pro Anhängen ([HT002](../cases/ht002.md) gemessen: $0.41 / 3 Minuten).

**Aufwecken, ohne etwas zu sagen** (einfach Enter), hängt nichts an und leitet nichts neu ab — es kostet keinen Cent extra.

### Auch ein Absturz innerhalb des ersten Schritts (Bedarf klären) lässt sich fortsetzen {#崩在第一步确认需求之内也能接上}

`clarify_step` trägt einen `resume_prompt` (Konstante `CLARIFY_RESUME`): startet man nach einem Absturz mitten in der Klärung neu, sagt er dem [Klärer](../reference/glossary.md#确认者) „Setze die eben nicht zu Ende geführte Bedarfsklärung fort — fang nicht von vorn an“, statt das ursprüngliche Anliegen erneut als neue Aufgabe zu schicken. Zusammen mit der obigen Regel „session_id sofort auf Platte“ lässt sich damit auch ein Lauf fortsetzen, der im ersten Schritt gestorben ist, bevor `需求.md` eingefroren war — ohne dass jemand noch einmal antworten muss.

Umgekehrt werden bereits eingefrorene Vorstufen **komplett übersprungen**: sind die vier Abschnitte von `需求.md` vollständig, entfällt Bedarf klären (der Inhalt wird trotzdem in den ctx gespeist); ist `目标.md` vollständig, entfällt Ziele setzen.

### Beim Anknüpfen wird nicht derselbe Satz geschickt {#接续时发的不是同一句话}

Dafür ist `Step.resume_prompt` da. Das Gegenüber **hat** das Anforderungsdokument, die Ziele und den letzten Stand bereits im Kontext; „Arbeite nach diesem Bedarf: <ganzes Anforderungsdokument>“ noch einmal wortgleich zu schicken ist reines Rauschen — schlimmer noch, es wird gelesen als „der Bedarf hat sich geändert, schau es dir neu an“.

Ohne `resume_prompt` wird `prompt` weiterverwendet — manche Schritte sollen ohnehin den vollen Text erneut schicken (beim Neuableiten der Prüfliste in Ziele setzen ist genau das vollständige Anforderungsdokument gefragt).

### Beim Aufwecken zuerst eine Zeile melden {#唤醒时先报一行}

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Ohne diese Meldung wäre „erinnert es sich nun oder nicht“ völlig unspürbar — und genau das ist der ganze Wert dieser Schicht. Im Banner steht `需求已确认` immer, `目标 N 条` nur bei nicht leerer Prüfliste, und `干活上下文 X` setzt voraus, dass sich aus `sessions.db` die Kontextgröße der letzten Runde dieser Session ermitteln lässt.

**Die Kontextzahl steht dort mit Absicht** — der Grund folgt im Abschnitt „Der Preis“.

### Resilienz: bei Netzausfall wartend hängen bleiben, und Fehler landen nicht im Kontext nach dem Anknüpfen {#韧性断网时挂着等而且错误不进接续后的上下文}

[Resilienz](../reference/glossary.md#韧性) und Kontinuität gehören zusammen: läuft etwas stundenlang, bricht das Netz zwangsläufig einmal weg, und das Default-Verhalten ist übel — im Moment des Abbruchs schiebt der Harness eine **synthetische assistant-Nachricht** ins Transcript (`isApiErrorMessage=true`, `model="<synthetic>"`), im Text steht „API Error: Can't reach the API server …“. Diese Nachricht wird zum Blatt der Session, beim späteren resume wird sie als „das hat das Modell zuletzt gesagt“ zurückgefüttert, und das Modell glaubt, es diskutiere gerade eine Netzstörung.

`Resilience` tut drei Dinge:

**Erstens: die Sonde macht nur DNS + TCP.** `reachable(host, port, timeout=5.0)` führt nur `getaddrinfo` und einen TCP-Handshake aus, **schickt kein HTTP, trägt keine Credentials, kostet nichts**; jede Exception gilt als nicht erreichbar. Welche Adresse gesondet wird, entscheidet `endpoint()`, das sich nach `ANTHROPIC_BASE_URL` richtet, Default `https://api.anthropic.com`, Port per Default `443` (bei http `80`).
**Mit einem eigenen Gateway muss man das Gateway sonden** — dass `api.anthropic.com` erreichbar ist, sagt nichts über das Gateway.

**Zweitens: unterscheiden, worauf man wartet und wobei man aufhört.** `classify(text)` liefert `"transient"` / `"fatal"` / `"unknown"`,
**erst fatal, dann transient prüfen** — Texte zu 401 und Ähnlichem enthalten oft das Wort „connection“; in umgekehrter Reihenfolge wartet man endlos.
Defaults: `max_attempts=6` (inklusive erstem Versuch), `base_delay=4.0`, `max_delay=120.0`, `probe_timeout=5.0`,
`probe_interval=15.0`, `max_offline_wait=3600.0` (1 Stunde), `retry_unknown=True`.
Das Backoff ist `min(base_delay * 2**(attempt-1), max_delay)`, multipliziert mit ±25 % Jitter.

Wenn schon eine session_id vorliegt, wird **per resume fortgesetzt statt neu begonnen**, die bisherigen Kosten sind nicht umsonst. Beim Fortsetzen wird `Resilience.resume_prompt` geschickt: „Die letzte Runde wurde mitten drin unterbrochen und nicht zu Ende geführt. Sieh nach, was in der Workbench bereits auf Platte liegt, und mach an der Unterbrechungsstelle weiter, fang nicht von vorn an.“ Er enthält **absichtlich keinerlei Fehlerdetails** — das Modell muss wissen „ich wurde unterbrochen, mach weiter“, nicht, ob es ENOTFOUND oder 503 war.

**Drittens: die Fehlermeldungen aus dem Retry-Sturm landen nicht im Kontext nach dem resume.** Das erledigt [Prune](../reference/glossary.md#剪除).
Der Session Store von `Runtime` ist fest auf `PruningSessionStore` verdrahtet, der beim `load()` drei Dinge tut:

- Synthetische API-Fehlermeldungen entfernen. **In SQLite bleiben sie unverändert erhalten**, sie werden nur nicht zurückgefüttert
- Zu alte abgelehnte Aufrufe entfernen, nur die letzten `keep_denials=1` bleiben
- Verwaiste `tool_result`-Einträge aus Unterbrechungen durch den neutralen Hinweis „[上一轮在此处被中断,该工具结果未产生]“ ersetzen — nur der Text wird ersetzt, der Eintrag bleibt

Dass 1 statt 0 behalten wird, hat einen Grund: ein abgelehnter Aufruf wurde nie ausgeführt, im Ergebnis steckt keine Information, er belegt aber durchaus Platz (gemessen einmal 273 Zeichen = 93 Zeichen Ablehnungstext + 180 Zeichen **Originalwortlaut des verbotenen Kommandos**), und **er ist irreführend** — gemessen: nachdem der Koordinator ein paar Mal „Bash nicht direkt verwenden“ gelesen hatte, versuchte er nicht einmal mehr das erlaubte `git status` — erlernte Hilflosigkeit. Der jeweils neueste Eintrag ist aber nützlich: er verhindert, dass das Modell in derselben Runde immer wieder dasselbe blockierte Kommando probiert.

Beim Entfernen gibt es eine strukturelle rote Linie: das Transcript ist eine einfache `parentUuid`-Kette; wer einen Eintrag entfernt, muss dessen Kinder an den nächsten überlebenden Vorfahren hängen, sonst reißt die Kette dort ab und die gesamte vorangehende Historie ist weg.

In [HT001](../cases/ht001.md) ist das einmal real aufgetreten: Netzausfall-Zeitachse 01:52:40 → 01:55:41, der Schritt steht in `manifest.json` mit
`attempts=2` / `resumed=True` / `ok=True`, und nach dem Fortsetzen lief er noch über 8 Stunden bis zur Fertigstellung.

Ein letzter leicht misszuverstehender Punkt: **`Runtime(trim=False)` heißt nicht „es wird gar nichts bereinigt“**. `trim` ist per Default ohnehin `False`,
schaltet aber nur die Schicht **[Trim](../reference/glossary.md#裁剪) großer Tool-Ergebnisse** ab. Abbruchreste entfernen, abgelehnte Aufrufe entfernen,
Unterbrechungsreste neutralisieren, Ergebnisse von [Ephemeral-Kommandos](../reference/glossary.md#一次性命令) als veraltet markieren — diese vier laufen weiterhin
(`ephemeral` per Default `True`, `keep_denials` per Default `1`).

### Der Preis: der Kontext wächst immer weiter, ohne Ende {#代价上下文会一直涨而且没有尽头}

Das ist der inhärente Preis der Kontinuität, kein Bug.

Der Schritt „干活“ in [HT001](../cases/ht001.md) lief 10.44 Stunden am Stück; der Kontext im [Hauptthread](../reference/glossary.md#主线程) betrug in Runde 1 **28.7K**, in Runde 20 **35.2K**, in Runde 35 **108.6K**, in Runde 50 **158.2K**, in Runde 70 **185.9K** —
monoton steigend, Steigung etwa **2.2K/Runde**; durchgehend kein Compact, verbraucht wurden **18.6 %** des 1M-Fensters. Mit dieser Steigung extrapoliert liegt die Wand bei etwa **440 Runden** — die Obergrenze von „long-horizon“ in der aktuellen Form ist ungefähr das **6-fache** jenes Laufs. Permanente Kontinuität heißt: irgendwann trifft man das Fenster.

Zwei Mechanismen halten das im Zaum:

1. **Trim** (`flower --no-trim` schaltet es ab, auf dem Pfad `flower` ist es an) — beim resume werden alte große Tool-Ergebnisse durch Dateizeiger ersetzt; der Inhalt ist nicht weg, er sitzt nur nicht mehr dauerhaft im Kontext
2. **[Handoff](handoff.md)** — am Schwellwert wird ein Handoff-Dokument geschrieben und auf eine neue Session gewechselt. **Das ist kein [Compact](../reference/glossary.md#压缩)**: das Dokument ist lesbar und änderbar, du siehst, was verloren geht. Der Kontext fällt dadurch periodisch zurück, statt bis zur Wand hochzulaufen

**Deshalb muss die Weckzeile die Kontextzahl melden**: nur was der Mensch sieht, gibt ihm die Chance, vor der Wand selbst zu entscheiden, neu anzufangen.

Nebenbei: `--rounds` (Gesamtzahl der Arbeitsrunden) **wird bei jedem Weckvorgang zurückgesetzt**. Das ist Absicht — ein neuer Weckvorgang ist eine neue Absicht und sollte die verbrauchten Runden des letzten nicht erben.

### Etwas Neues anfangen {#重开一件事}

```bash
flower --new "另一件事"
```

Oder im Weck-Prompt direkt `/new` eingeben:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> /new
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> …
```

**Archivieren, nicht löschen.** `lineage.json`, `需求.md` und `目标.md` werden zusammen nach `notes/archive/<YYYYmmdd-HHMMSS>/` **verschoben**,
gleichzeitig werden `steps` und `woke` der Lineage auf null gesetzt. Die drei sind drei Seiten derselben Historie; nur einen Teil davon einzusammeln hinterlässt einen halben Zustand nach dem Muster „Ziele noch da, aber das Gespräch weg“.

`sessions.db` bleibt unangetastet — es ist das Archiv, jedes Transcript darin lässt sich weiterhin nachschlagen.

Im Code entspricht das `Lineage.archive(into, extra=[...])`.

## Wann man es nicht einsetzen sollte {#什么时候不该用它}

- **Szenarien, die jedes Mal einen sauberen Startpunkt verlangen.** Denselben Workflow im Batch fahren, Vergleichsevaluationen, jemandem einen Bug reproduzierbar machen — nichts davon sollte den Kontext des letzten Laufs mitschleppen. Schreib `Workflow(..., continuous=False)` oder nimm jedes Mal ein anderes `run_dir`.
- **Das Verzeichnis wird verschoben oder kopiert, oder `run_dir` ist nicht persistent.** Im Container laufen lassen, während `runs/` im inneren Dateisystem des Containers liegt, oder den Arbeitsbereich per rsync auf eine andere Maschine bringen — die Kontinuität fällt dann **still aus** (die Pfadwache verwirft eine nicht passende Lineage). Verlass dich nicht darauf als Garantie.
- **Diesmal ist es eine neue Absicht, und der Kontext ist bereits groß.** Kontinuität schleppt die irrelevante Historie mit, und du zahlst in jeder Runde Token dafür. Statt es auszuhalten: mit `--new` archivieren und neu anfangen.
- **Einmaliger Einzel-Agent.** `flower once` läuft nicht über `Workflow`, es gibt keine Lineage; zum Fortsetzen musst du selbst `--resume <session_id>` angeben.
- **Kontinuität als Backup missverstehen.** Sie merkt sich nur, „welcher Schritt welche Session benutzt hat“. Code, Artefakte und Entscheidungen gehören in den Arbeitsbereich und in die [Workbench](../reference/glossary.md#工作台) und sollten nicht aus dem Transcript zurückgegraben werden müssen.

## Verwandtes {#相关}

- [Handoff](handoff.md) — was passiert, wenn der Kontext innerhalb eines Laufs voll wird; zwei Richtungen derselben Sache wie diese Seite
- [Zielwächter](goal.md) — warum der Judge nicht an der Kontinuität teilnimmt
- [Kontextökonomie](context.md) — wofür Trim, Prune und Spill jeweils zuständig sind
- [Python API](../reference/api.md) — `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Kommandozeile](../reference/cli.md) — `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Quellcode: [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
