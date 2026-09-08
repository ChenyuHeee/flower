# Kommandozeilen-Referenz

`flower` installiert sich als eine einzige ausführbare Datei, 4 Unterbefehle, 23 Schalter. Diese Seite listet sie alle auf: für jeden Schalter den Typ,
den Standardwert, die exakte Semantik, dazu, wie man während eines Laufs dazwischenredet, was beim ersten Lauf gefragt wird, welche Exit-Codes es gibt und welche Dateien es in deinem Verzeichnis ablegt.
Nach dieser Seite musst du den Quellcode nicht mehr öffnen.

Quellcode: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Unterbefehl | Was er tut | Positionsargument | Eigene Schalter |
|---|---|---|---|
| `go` | Alles in einem: Bedarf klären → Ziele setzen → Leute an die Arbeit schicken → in jeder Runde ein Verdikt. Der Standard, wenn kein Unterbefehl geschrieben wird | `ask` (optional) | 11 |
| `run` | Führt einen selbstgeschriebenen [Workflow](glossary.md#流程) aus | `target` (erforderlich) | 0 |
| `once` | Führt einmal einen einzelnen Agenten aus, ohne Workflow, ohne Verdikt | `prompt` (erforderlich) | 6 |
| `setup` | Konfiguriert Zugangsdaten, schreibt nach `~/.config/flower/.env` | keins | 0 |

Gesamtzahl der Schalter 23 = 5 global + 11 spezifisch für `go` + 6 spezifisch für `once` + `-h/--help`. `run` und `setup`
haben keine eigenen Schalter.

---

## Aufrufformen {#调用形式}

Alle argv von `flower` laufen zuerst durch `_with_default_cmd()`, um den Standard-Unterbefehl zu ergänzen, und werden dann an argparse übergeben
(`cli.py:1437-1439`). Deshalb funktioniert `flower "mach mir ein X"` — es wird umgeschrieben zu
`flower go "mach mir ein X"`.

Die Regeln zum Ergänzen des Standard-Unterbefehls (`cli.py:940-976`):

1. Die Menge der globalen Schalter **wird aus dem Haupt-Parser selbst abgeleitet**, nicht aus einer fest kodierten Liste. Was `nargs == 0` hat, zählt als reiner Schalter,
   der Rest als Schalter mit Wert.
2. Von links nach rechts durchgehen, globale Schalter überspringen. Bei solchen mit Wert wird der Wert mitübersprungen, auch die `=`-Schreibweise wie `--workspace=/tmp` wird erkannt.
3. Beim ersten Token stehenbleiben, das kein globaler Schalter ist. Ist es eines von `go`, `run`, `once`, wird es unverändert an argparse übergeben;
   **andernfalls wird ein `go` davor eingefügt**, sodass es zum Anliegen-Text von `go` wird.
4. Wenn nach dem vollständigen Durchgang kein Positionsargument angetroffen wurde (leeres argv oder nur globale Schalter) → am Ende `go` ergänzen, in die interaktive Eingabe wechseln.
5. Ausnahme: Enthält argv `-h` oder `--help`, wird es unverändert zurückgegeben und argparse gibt die Hilfe aus.

Die für die Entscheidung verwendete Konstante ist `_CMDS = ("go", "run", "once")` (`cli.py:937`) — **`setup` ist nicht darin enthalten**,
Konsequenzen siehe [`setup`](#setup).

### Die tatsächlichen Umschreibungsergebnisse {#实际的改写结果}

| Was du tippst | Tatsächlich geparst als | Effekt |
|---|---|---|
| `flower` | `["go"]` | Interaktive Frage „Was soll gemacht werden?" |
| `flower -v` | `["-v", "go"]` | Wie oben, mit verbose |
| `flower "mach mir ein X"` | `["go", "mach mir ein X"]` | Legt direkt los |
| `flower -w /tmp "mach X"` | `["-w", "/tmp", "go", "mach X"]` | Globale Schalter dürfen vorne stehen |
| `flower --workspace=/tmp "mach X"` | `["--workspace=/tmp", "go", "mach X"]` | Die `=`-Form wird ebenfalls erkannt |
| `flower "mach X" --timeout 0` | `["go", "mach X", "--timeout", "0"]` | Unterbefehl-Schalter dürfen nach dem Anliegen stehen |
| `flower --timeout 0 "mach X"` | `["go", "--timeout", "0", "mach X"]` | Sie dürfen auch vorne stehen |
| `flower --new` | `["go", "--new"]` | Nur Schalter, kein Anliegen → interaktive Eingabe |
| `flower once "hi"` | `["once", "hi"]` | Unverändert |
| `flower run flows:main` | `["run", "flows:main"]` | Unverändert |
| `flower run` | `["run"]` | argparse meldet fehlendes `target`, wird **nicht** als Anliegen aufgefasst |
| `flower go run` | `["go", "run"]` | Explizite Desambiguierung: der Anliegen-Text ist `run` |
| `flower setup` | `["go", "setup"]` | Ausgeführt wird `go`, das Anliegen wird der String `setup`, siehe [`setup`](#setup) |
| `flower --help` | Unverändert | argparse gibt die Hilfe aus |

Die beiden Wörter `run` und `once` **können nicht** direkt als Anliegen-Text dienen, das ist eine bewusst belassene Mehrdeutigkeit (`cli.py:949-950`).
Um sie doch als Anliegen zu verwenden, schreibt man `flower go run`.

### Sechs verwendbare Schreibweisen {#六种能用的写法}

```bash
flower                                    # 1. Bloßer Lauf: interaktive Frage „Was soll gemacht werden?" oder „Beim letzten Mal weitermachen?"
flower "mach mir ein X"                    # 2. Anliegen als Positionsargument
echo "mach mir ein X" | flower --timeout 0 # 3. Anliegen per Pipe über stdin
flower once "wirf einen Blick auf dieses Repo" # 4. Einzelner Agent
flower run flows.py:main                  # 5. Eigenen Workflow ausführen
flower go setup                           # 6. Explizites go, setup als Anliegen-Text
```

Die Modulform `python -m flower.cli` ist äquivalent zu `flower` (`cli.py:1451-1452`).
Die Argumente des Container-Wrappers `docker/flowerbox` sind exakt dieselben wie bei `flower`.

### Anliegen per Pipe über stdin {#管道喂-stdin}

`ask_for_prompt()` **gibt keinen Prompt-Header aus**, wenn `sys.stdin.isatty()` falsch ist, und liest direkt eine Zeile mit `input("> ")`
(`cli.py:993-1001`). Deshalb funktioniert `echo "..." | flower`.

Anschließend wird aber eine Warnzeile ausgegeben, und der stdin-Thread liest sofort EOF und beendet sich:

```text
! Standardeingabe ist kein Terminal, niemand kann die Fragen beantworten. Wenn es selbst entscheiden soll, füge --timeout 0 hinzu
```

Bei einem Pipe-Lauf sollte man `--timeout 0` setzen: Fragen tun nicht mehr so, als würden sie 30 Minuten warten, sondern fallen sofort ins Leere, der Agent entscheidet selbst und schreibt seine Annahmen in den Abschnitt „Unbekanntes und Annahmen" des Briefs.

---

## Unterbefehle {#子命令}

### `go` {#go}

Hilfetext: `Alles in einem: Bedarf klären → Leute an die Arbeit schicken (Standard, wenn kein Unterbefehl geschrieben wird)` (`cli.py:1275-1307`).

Positionsargument `ask`, `nargs="?"` — wird es nicht angegeben, geht es in die interaktive Eingabe. Das ist der am häufigsten genutzte Einstiegspunkt, `flower "mach X"` geht diesen Weg.

Was es tut (`cli.py:1190-1221`):

1. `ensure_credentials()` — prüft die Zugangsdaten und schickt tatsächlich einmal einen API-Probelauf ab, siehe [Konfigurationsablauf beim ersten Lauf](#首次运行的配置流程).
2. [Wake](glossary.md#唤醒)-Sondierung: schaut nur lesend einmal nach, ob dieses Verzeichnis schon verwendet wurde, schreibt kein einziges Byte.
3. Ist kein `ask` angegeben, wird ein Prompt gestellt; die Eingabe `/new` ist äquivalent zu `--new`, dann wird **erneut** nach dem Anliegen gefragt.
4. Handelt es sich um [Continuity](glossary.md#接续), wird ein Wake-Banner ausgegeben.
5. Es baut den dreistufigen [Workflow](glossary.md#流程) auf: `Bedarf klären` → `Ziele setzen` → `Arbeiten`,
   wobei nach jeder Arbeitsrunde ein `Arbeiten·Verdikt#N` folgt. `--clarify-only` behält nur den ersten Schritt.
6. Legt los.

Das Wake-Banner sieht so aus (das Home-Verzeichnis im Pfad wird durch `~` ersetzt):

```text
<- In ~/proj beim letzten Mal angeknüpft  Bedarf geklärt · 7 Ziele · Arbeitskontext 71.4K · 3. Wake
```

`Bedarf geklärt` ist immer vorhanden; `N Ziele` erscheint nur, wenn eine Verdikt-Liste existiert; `Arbeitskontext X` erfordert, dass der Kontext der letzten Runde jener [Session](glossary.md#会话) aus `sessions.db` abgefragt werden kann, wird er nicht gefunden, wird er nicht angezeigt.

!!! warning "`-W` und `-T` werden auf dem `go`-Pfad still überschrieben"
    Diese beiden globalen Schalter haben auf `go` keine Wirkung, ohne Fehler, ohne Hinweis:

    - `-W/--workbench`: Der von `go` gebaute Workflow bringt immer eine eigene [Workbench](glossary.md#工作台) mit,
      und der Code nimmt `getattr(wf, "workbench", None) or args.workbench` (`cli.py:1038`) —
      die vom Workflow mitgebrachte hat immer Vorrang. Die Workbench ist also stets `<workspace>/.flower/`
      (bei `--isolate` ist es `<workspace>.parent/.flower-<Name>/`), `-W` kann das nicht ändern.
    - `-T/--trim`: `go` geht den Weg `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1221`),
      verwendet direkt den negierten Wert von `--no-trim` und **schaut überhaupt nicht auf `args.trim`**. Das heißt, auf dem `go`-Pfad ist [Trim](glossary.md#裁剪) standardmäßig eingeschaltet, ausschalten geht nur mit `--no-trim`.

    Diese beiden Schalter greifen nur bei `run` (wenn der Workflow keine eigene Workbench mitbringt) und `once`.

#### Die 11 Schalter von `go` {#go-的-11-个开关}

| Schalter | Typ | Standard | Beschreibung |
|---|---|---|---|
| `--asks N` | int | `-1` | Frage-Kontingent. `-1` oder jede negative Zahl = **unbegrenzt**; `0` = keine Fragen erlaubt, die erste Frage ergibt `over_budget`; `N` = hartes Kontingent. Bei Überschreitung lehnt das Tool direkt ab, ohne den Lauf zu blockieren |
| `--rounds N` | int | `3` | Obergrenze der **Gesamtrundenzahl** beim Arbeiten, nicht der zusätzlichen Runden. Am Ende jeder Runde entscheidet ein unabhängiger [Judge](glossary.md#判定者), ob „es fertig ist"; wenn nicht erreicht, wird es zurückgeschickt und dieselbe Session läuft weiter |
| `--no-goal` | Schalter | `False` | Schaltet den [Goal guard](glossary.md#目标看守) aus: keine `目标.md` wird erzeugt, kein [Verdikt](glossary.md#判定), nach dem Arbeiten ist Schluss |
| `--judge-can-run` | Schalter | `False` | Lässt den Judge Befehle ausführen. Das Verdikt wird härter, um den Preis, dass er den Arbeitsbereich auch verändern kann |
| `--timeout Sekunden` | float | `1800.0` | Wie lange auf eine Antwort gewartet wird. `0` oder negativ = vollautomatisch, alle Fragen fallen **sofort** ins Leere, ohne so zu tun, als würde gewartet. Semantik siehe [Timeout](#超时) |
| `--isolate` | Schalter | `False` | Jeder [subagent](glossary.md#subagent) bekommt eine eigene git-worktree, also [Isolation](glossary.md#隔离). **Erfordert, dass der workspace ein git-Repo ist**, sonst Exit-Code 1. Zugleich wird die Workbench aus dem Repo herausverlegt |
| `--window N` | int | keiner (nach Modellname abgeleitet) | Kontextfenster des Modells. Wird es nicht angegeben: Modellname enthält `1m` oder enthält kein `haiku` → 1.000.000; enthält `haiku` → 200.000. Bei `Fenster − 50000` wird ein [Handoff-Dokument](glossary.md#交接书) geschrieben und ein [Handoff](glossary.md#换代) gemacht |
| `--no-handoff` | Schalter | `False` | Schaltet den Handoff aus, fällt zurück auf das vom SDK mitgelieferte [Compact](glossary.md#压缩) |
| `--new` | Schalter | `False` | Diesmal nicht ans letzte Mal anknüpfen. Die `lineage.json` + `需求.md` + `目标.md` des vorherigen Abschnitts werden nach `notes/archive/<YYYYmmdd-HHMMSS>/` **verschoben** (nicht gelöscht), dann wird von vorne begonnen |
| `--clarify-only` | Schalter | `False` | Macht nur das [Clarify](../guide/clarify.md), arbeitet nicht weiter — im Workflow bleibt nur der Schritt `Bedarf klären` |
| `--no-trim` | Schalter | `False` | Schaltet Trim aus. Auf dem `go`-Pfad ist Trim standardmäßig **an**, dies ist die einzige Möglichkeit, es auszuschalten |

Randfälle bei den Werten, alle ohne Fehler, ohne Hinweis:

- `--rounds 0` und `--rounds 1` sind äquivalent — intern gilt `retries = max(0, rounds - 1)`, beide laufen 1 Runde.
- Jede negative Zahl bei `--asks` bedeutet unbegrenzt, nicht nur `-1`.
- Jede negative Zahl bei `--timeout` entspricht `0`, also vollautomatisch.
- `--window 0` wird **still ignoriert** (`0` ist falsy, wird gar nicht weitergereicht), es fällt auf den nach Modellname abgeleiteten Standard zurück.
  Negative Zahlen werden weitergereicht und dann auf `10000` abgefangen.
- `--clarify-only` ist auf einem bereits geklärten Verzeichnis eine **Nulloperation** — der Schritt `Bedarf klären` sieht eine vollständige `需求.md`
  und überspringt sie, und da im Workflow nur dieser Schritt ist, passiert überhaupt nichts (außer dass die Wake-Zahl +1 wird). Um erneut zu klären, braucht man `--new`.
- Am Ende der `--help` von `go` steht „Globale Schalter (-v/-w/-r/-T) siehe `flower --help`", diese Zeile **lässt `-W` aus**.

### `run` {#run}

Hilfetext: `Führt einen Workflow aus` (`cli.py:1309-1312`).

Positionsargument `target`, geschrieben als `Modul:Attribut`. Beide Formen werden unterstützt (`cli.py:1010-1031`):

```bash
flower run mypkg.flows:build     # Import über Modulname
flower run flows.py:build        # Dateipfad; das Elternverzeichnis wird in sys.path gelegt, dann Import über Dateiname
```

Ist das erhaltene Attribut aufrufbar, wird es einmal aufgerufen und der Rückgabewert als [Workflow](glossary.md#流程) verwendet; ist es bereits ein Workflow-Objekt, wird es direkt verwendet.

**`run` hat keinerlei eigene Schalter**, nur die 5 globalen. Deshalb nehmen `--window`, `--no-handoff` usw. auf diesem Weg
durchweg die Standardwerte an (der Code fängt mit `getattr` ab, `cli.py:1041-1043`). Um sie einzustellen, schreibt man die Parameter in den eigenen Workflow.

### `once` {#once}

Hilfetext: `Führt einmal einen einzelnen Agenten aus` (`cli.py:1314-1324`). Positionsargument `prompt` erforderlich.

Es konstruiert ein `AgentSpec(name="ad-hoc", …)` und führt es direkt aus, **ohne durch `_drive` zu gehen**. Deshalb gibt es bei `once` nicht:

- Ctrl-C zum Unterbrechen und Reden (Drücken ergibt einen normalen `KeyboardInterrupt`)
- den stdin-Antwort-Thread, den dauerhaft am unteren Rand sitzenden Eingabe-Prompt
- Oracle-Frage-Antwort
- SIGHUP / SIGTERM-Rettungsbuchung
- die Abschlusszeile `Gesamtkosten … · Manifest …`
- die automatische Neukonfigurationsführung nach fehlgeschlagenen Zugangsdaten

Der Name dieses Schritts im [Run-Manifest](glossary.md#运行清单) ist fest `ad-hoc`.

| Schalter | Typ | Standard | Beschreibung |
|---|---|---|---|
| `-i`, `--instructions` | str | leer | Domänenanweisungen, werden **nach** dem nativen System-Prompt von Claude Code [angehängt](glossary.md#叠加), nicht ersetzt |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Kommagetrennte Tool-Whitelist. Ohne Angabe sind es diese drei Nur-Lese-Tools |
| `-p`, `--permission-mode` | str | `default` | Der Wert kann nur eines von `default`, `acceptEdits`, `plan`, `bypassPermissions` sein, bei anderen Werten meldet argparse einen Fehler mit Exit-Code 2 |
| `-b`, `--budget` | float | keine Obergrenze | Dollar-[Budget](glossary.md#预算)-Obergrenze, bei Überschreitung Stopp |
| `--resume SESSION_ID` | str | keiner | Setzt eine bestehende Session fort |
| `--fork` | Schalter | `False` | Fork statt Fortsetzung, in Verbindung mit `--resume` |

!!! warning "Die von `once` angezeigte Laufzeit und die kumulierten Kosten sind immer 0"
    `once` erstellt bei jedem empfangenen Event eine neue Renderer-Instanz (`cli.py:688-690`, `cli.py:1239`),
    während der Zeitstartpunkt und die kumulierten Kosten in der Instanz gespeichert sind (`cli.py:500-501`). Also:

    - Die `Laufzeit` in der Abschlusszeile ist stets `0:00`
    - Das `kumuliert $0.00` in der Statuszeile ist stets 0, auch der `Kontext` kumuliert nie

    Die echten Kosten eines einzelnen Schritts findet man im Feld `cost_usd` in `runs/manifest.json`. Die Pfade `go` und `run` halten
    dieselbe Renderer-Instanz und haben dieses Problem nicht.

### `setup` {#setup}

Hilfetext: `Konfiguriert Zugangsdaten (API key / Gateway / Modell), schreibt nach ~/.config/flower/.env` (`cli.py:1326-1328`).
Keinerlei Schalter.

Was es tut: liest die `.env` durch → entscheidet, ob schon konfiguriert wurde → startet den interaktiven Konfigurationsablauf, `reason` ist `Neu konfigurieren.` oder
`Noch keine Zugangsdaten konfiguriert.`. Bildschirminhalt siehe [Konfigurationsablauf beim ersten Lauf](#首次运行的配置流程).

!!! warning "`flower setup` erreicht diesen Unterbefehl derzeit nicht"
    Die Entscheidungskonstante für den Standard-Unterbefehl `_CMDS = ("go", "run", "once")` (`cli.py:937`) **lässt `"setup"` aus**,
    aber `setup` ist im Parser tatsächlich registriert (`cli.py:1326`). Also wird `flower setup` umgeschrieben zu
    `flower go setup` — **ausgeführt wird der vollständige `go`-Workflow, der Anliegen-Text ist der String `setup`**: zuerst werden die Zugangsdaten geprüft,
    dann wird nach dem Bedarf gefragt, und dann werden tatsächlich Leute an die Arbeit geschickt. Mit globalen Schaltern ist es genauso, `flower -v setup` → `["-v", "go", "setup"]`.

    **Kein einziges argv kann den Unterbefehl `setup` erreichen.**

    Um Zugangsdaten zu konfigurieren, gibt es derzeit nur diese zwei Wege, beide führen zur selben interaktiven Oberfläche:

    - Direkt `flower "irgendein beliebiges Anliegen"` ausführen, wenn keine Zugangsdaten konfiguriert sind, fragt es zuerst danach;
    - Oder `~/.config/flower/.env` von Hand schreiben, Schlüsselnamen siehe [Die geschriebenen Schlüssel](#写出来的键).

    Betroffen sind auch mehrere Textstellen: das bei abgelehnten Zugangsdaten ausgegebene ``Führe `flower setup` zum Neukonfigurieren aus.``, der Kommentar in der ersten Zeile der
    `.env` ``geschrieben von `flower setup``, beide verweisen auf diesen unerreichbaren Befehl.

---

## Globale Schalter {#全局开关}

Die 5 globalen Schalter hängen gleichzeitig am Haupt-Parser und an jedem Unterbefehl (`cli.py:1250-1266`). Die Version an den Unterbefehlen verwendet
`argparse.SUPPRESS`, ohne Angabe wird das Attribut nicht geschrieben, deshalb **darf man sie vor oder nach dem Unterbefehl schreiben**, sie überschreiben sich nicht gegenseitig.
Nebeneffekt ist, dass man sie in der `--help` des Unterbefehls nicht sieht — um sie zu sehen, muss man `flower --help` ausführen.

| Schalter | Typ | Standard | Beschreibung |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | Das Arbeitsverzeichnis des Agenten. Es wird per `resolve()` zu einem absoluten Pfad aufgelöst und `mkdir -p`. Die [Workbench](glossary.md#工作台) `.flower/` wird hier drin angelegt |
| `-r`, `--run-dir` | str | `runs` | Verzeichnis für [Session-Store](glossary.md#会话存储) und Run-Manifest. **Relativ zum aktuellen CWD, nicht relativ zum workspace** |
| `-v`, `--verbose` | Schalter | `False` | Gibt mehr aus, siehe unten |
| `-W`, `--workbench` | Schalter | `False` | Aktiviert die Workbench. **Wirkungslos bei `go`**, greift nur bei `run` (wenn der Workflow keine eigene Workbench mitbringt) und `once`, dann landet die Workbench in `<run_dir>/workbench/` |
| `-T`, `--trim` | Schalter | `False` | Beim resume alte große Tool-Ergebnisse durch Dateizeiger ersetzen, also [Trim](glossary.md#裁剪). **Wirkungslos bei `go`**, dieser Weg wird über `--no-trim` invers gesteuert |
| `-h`, `--help` | Schalter | — | Jeder Parser hat es. Tritt es in argv auf, wird das Umschreiben des Standard-Unterbefehls übersprungen und direkt die Hilfe ausgegeben |

Die Regel, dass `-r/--run-dir` relativ zum CWD ist, beißt: `flower -w /other/proj "mach X"` legt `runs/` im **Verzeichnis, in dem du den Befehl eingegeben hast**, an,
während `.flower/` unter `/other/proj/` angelegt wird — zwei getrennte Zustände. Sollen sie zusammen sein, gib explizit
`-r /other/proj/runs` an.

Die Hilfe von `-v` schreibt „zeigt Denken und Tool-Ergebnisse", aber das Denken des [Main threads](glossary.md#主线程) **wird standardmäßig ohnehin angezeigt**.
Was `-v` tatsächlich zusätzlich einschaltet, ist:

- den Textkörper der subagents (standardmäßig nicht angezeigt, nur ihre Tool-Aufrufe)
- normale Tool-Ergebnisse (standardmäßig werden nur die fehlerhaften angezeigt)
- `prompt`-Events
- vor dem Start einmal die aktuell wirksame Zugangsdaten-Konfiguration ausgeben, der Token wird maskiert und nur die ersten 4 Stellen bleiben

Der letzte Punkt läuft über ein nacktes `print()`, **ohne Ausgabe-Bereinigung, ohne Umbruch, ohne Schutz durch das Terminal-Schreiblock**,
beim parallelen Ausführen mehrerer `flower` können diese Zeilen zerrissen werden.

---

## Wie man während eines Runs mit ihm spricht {#运行中怎么和它说话}

Sobald der Run läuft, **liest das Terminal die ganze Zeit deine Eingabe**. Du musst nicht warten,
bis es fragt, und keine Taste drücken, um in einen Eingabemodus zu kommen —
die letzte Zeile ist immer die, in die du tippen kannst.

### Die dauerhaft unten stehende Eingabeaufforderung {#常驻在最下面的输入提示符}

Ein Daemon-Thread `flower-stdin` liest durchgehend stdin (`cli.py:764-934`) und pollt mit `select`
alle 0.2 Sekunden, statt blockierend zu lesen (so weckt ihn ein Stoppsignal auf; Streams wie unter
Windows, die `select` nicht unterstützen, fallen auf blockierendes Lesen zurück).

**Er liest immer, nicht nur wenn eine Frage offen ist.** Der Grund: Würde er nur beim Fragen lesen,
bliebe alles, was du in den Stunden Arbeit tippst, im Terminalpuffer liegen und würde bei der
nächsten Frage als Antwort verschluckt — die Frage wäre beantwortet, bevor du sie überhaupt gesehen hast.

Bei der Ausgabe ist `_say()` der einzige Ausgang: Vor jeder Ausgabe wird die Eingabeaufforderung
gelöscht und danach neu gezeichnet (`cli.py:309-315`), damit sie nicht von Event-Ausgaben nach oben
weggeschoben wird. **Beim Neuzeichnen kommen auch die halb getippten, noch nicht abgeschickten
Zeichen zurück** — sie liegen in `_PROMPT["buf"]` (`cli.py:183-192`). Ohne das wäre der Inhalt zwar
nicht verloren (er steckt weiter im Zeilenpuffer des Terminals und geht bei Enter trotzdem raus),
aber du siehst ihn nicht, wirst unsicher und tippst ihn noch einmal.

Die Eingabeaufforderung hat zwei Textvarianten, je nachdem, ob eine Frage offen ist:

| Zustand | Letzte Zeile auf dem Bildschirm |
|---|---|
| Offene Frage | `你的回答 (回车=跳过,让它自己判断) > ` |
| Keine offene Frage | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Zeichenweiser Eingabemodus und Tastenbelegung {#逐字符输入}

Um die „halb getippten Zeichen" zurückzeichnen zu können, muss flower die Eingabe selbst übernehmen.
Wenn stdin ein Terminal ist und `import termios` funktioniert, wird das Terminal **vor** dem Start des
`flower-stdin`-Threads auf `cbreak` gesetzt (`cli.py:793-807`) — `cbreak` statt `raw`, damit Ctrl+C
weiterhin ein `SIGINT` erzeugt und der [Ctrl-C](#ctrl-c)-Mechanismus erhalten bleibt.
Es muss vor dem Thread-Start passieren: Im Thread selbst gibt es eine echte Race Condition —
Zeichen, die in dem Moment getippt werden, in dem der Thread noch keine CPU bekommen hat, werden vom
Zeilenmodus verschluckt und wirken wie „Eingabe verloren" (in Tests reproduzierbar in einem von
drei Fällen, `cli.py:928-934`).

Klappt das nicht, fällt es auf das alte zeilenweise `readline()` zurück (kein Terminal, `termios`
nicht verfügbar, `tcgetattr` schlägt fehl). Beide Wege funktionieren, im Zeilenmodus gibt es nur die
folgenden Tasten nicht (`cli.py:883-899`).

Die Editierlogik steckt in `LineEditor` (`cli.py:320-414`), eine reine Zustandsmaschine, die das
Terminal nicht anfasst:

| Taste | Wirkung |
|---|---|
| Druckbare Zeichen | Einfügen an der Cursorposition. UTF-8 wird über einen inkrementellen Decoder gesammelt und erst als vollständiges Zeichen in den Buffer gelegt |
| Backspace / Ctrl+H | Löscht **ein Zeichen** vor dem Cursor. Im Zeilenmodus löscht das Terminal byteweise — ein chinesisches Zeichen braucht drei Anschläge und hinterlässt Zeichensalat; hier nicht |
| ← / → | Bewegt den Cursor wirklich. Die komplette Escape-Sequenz wird verschluckt, es landet kein `[A` in der Eingabe |
| Home / End (bzw. `[1~` / `[4~`) | Sprung an Zeilenanfang / Zeilenende |
| Delete (`[3~`) | Löscht ein Zeichen nach dem Cursor |
| Ctrl+A / Ctrl+E | Zeilenanfang / Zeilenende |
| Ctrl+U | Ganze Zeile leeren |
| Ctrl+D | Nur bei leerem Buffer EOF; bei Inhalt ignoriert |
| ↑ / ↓ | **Tut nichts.** Es gibt keine History, und eine Reaktion würde den Eindruck erwecken, etwas sei verloren gegangen (`cli.py:335`) |
| Sonstige Steuerzeichen | Ignoriert |

Enter gibt den Buffer heraus, leert ihn und macht auf dem Bildschirm eine neue Zeile —
was du gesagt hast, bleibt oben stehen (`cli.py:811-827`).

### Wohin geht, was du tippst {#你敲的东西去哪了}

| Deine Eingabe | Bei offener Frage | Ohne offene Frage |
|---|---|---|
| **Leerzeile (nur Enter)** | Frage überspringen, es entscheidet selbst | Nichts |
| **Beginnt mit `?`** | Oracle-Frage, siehe unten | Dasselbe |
| **Nur Ziffern**, innerhalb des Optionsbereichs | Wird durch die entsprechende Option ersetzt und so beantwortet | Als normaler Text behandelt |
| Sonstiger Text | Geht als Antwort an den fragenden Agent | Geht in den Posteingang, als nachgereichte Anforderung |
| EOF (Ctrl-D oder Pipe geschlossen) | Frage wird verweigert, Eingabeaufforderung wird entfernt, Thread endet | Eingabeaufforderung wird entfernt, Thread endet |

Beim Eingang im Posteingang wird eine Quittung ausgegeben:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

Gibt es keinen [Anforderungsbrief](glossary.md#需求确认书), in den das geschrieben werden könnte,
wird der zweite Halbsatz zu `没有确认书可落盘 —— 它可能活不过下一个步骤`. Der Posteingang
**unterbricht** den arbeitenden Worker **nicht**; er nimmt die Nachricht erst mit, wenn er von sich
aus in den Posteingang schaut. Derselbe Satz wird zusätzlich an `notes/需求.md` angehängt — ohne
Persistierung überlebt er die Schrittgrenze nicht, denn der nächste Schritt ist eine neue Session,
die nur die eingefrorenen Dateien liest.

### Beginnt mit `?` = Oracle-Frage {#旁路问答}

Eine Zeile, die mit `?` beginnt, geht nicht an den laufenden Agent, sondern an den
[Oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

Er startet eine **eigene** Runtime, `run_dir` ist `<run_dir>/aside/`, damit seine Kosten und seine
Session-Lineage nicht in das Haupt-`manifest.json` geraten. Die Rolle ist read-only, als Tools gibt es
nur `Read`, `Glob`, `Grep`, maximal 12 Runden, Kostenobergrenze **$0.5**. Als Kontext sieht er die
letzten **60** Events (`thinking`- und `prompt`-Events kommen nicht in dieses Fenster), jedes auf
200 Zeichen gekürzt, dazu die Pfadbeschreibung der Workbench.

Er läuft **nebenläufig**, der laufende Run wartet keine Sekunde. Die Antwort sieht so aus:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

Bei Fehlschlag erscheint eine rote Zeile `# 旁路问答失败:<类型>: <消息>`, **ohne Einfluss auf den
Hauptablauf**. Beim Beenden wird höchstens **120 Sekunden** auf den Abschluss der Oracle-Fragen
gewartet; davor wird eine Zeile `(等 N 条旁路问答收尾…)` ausgegeben.

Was er sagt, kommt nicht in den Kontext dieses Runs — Fragen beeinflusst den Run nicht, die Antwort
wird nach der Ausgabe verworfen.

!!! warning "Das vollbreite `？` löst keine Oracle-Frage aus — wer eine chinesische IME benutzt, tritt hier rein"
    Die Codezeile, die über die Oracle-Frage entscheidet, lautet (`cli.py:907`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Beide Zeichen sind **das halbbreite ASCII `?`** (`0x3f`) — byteweise verifiziert. Von der
    Schreibweise her war offensichtlich beabsichtigt, sowohl das halbbreite `?` als auch das von
    chinesischen Eingabemethoden erzeugte vollbreite `？` (U+FF1F) zu akzeptieren, tatsächlich steht
    dort aber zweimal dasselbe Zeichen.

    Folge: **Eine Zeile, die mit dem vollbreiten `？` beginnt, wird nicht als Oracle-Frage erkannt**,
    sondern still als „nachgereichte Anforderung" in den Posteingang gelegt und damit an
    `notes/需求.md` angehängt. Die Quittung, die du siehst, ist `+ 收到`, nicht `# 旁路`.

    Für eine Oracle-Frage **musst du das halbbreite `?` nehmen** — vorher die Eingabemethode auf
    Englisch umschalten oder wenigstens das erste Zeichen halbbreit tippen.

### Was auf dem Bildschirm steht {#屏幕上都是什么}

Die Symbole sind **durchgehend ASCII**, keine Emoji (`cli.py:51-69`). Der Grund steht als Kommentar im
Code: Emoji zusammen mit Rahmen-, Geometrie- und Pfeilzeichen lösen Glyph-Fallbacks im Terminal aus,
was zweimal zu einem Terminal-Absturz geführt hat.

| Symbol | Bedeutung | Symbol | Bedeutung |
|---|---|---|---|
| `=` | Schritt-Trennlinie | `+` | Fertig / beantwortet / empfangen |
| `~` | Denken, Retry | `x` | Fehlgeschlagen / Fehler |
| `>` | Jemanden losschicken | `#` | Handoff, Oracle, Aufgabe |
| `*` | Tool-Aufruf | `-` | Statuszeile, Listenpunkt |
| `?` | Frage | `<-` | Fortsetzung, Landepunkt des Handoffs |
| `!` | Warnung / Unterbrechung | `.` | Übersprungen |
| `\| ` | Einrückungsstrich eines Subagents | | |

!!! warning "Die `❓` und `↩` aus der alten Dokumentation existieren im echten Terminal nicht"
    Frühere Dokumentation benutzte `❓` für Fragen und `↩` für Wake-Zeilen. **Im Code standen diese
    beiden Zeichen nie** — das Symbol für Fragen ist das halbbreite `?`, das Symbol für Wake und
    Handoff-Landepunkt sind die beiden ASCII-Zeichen `<-`.

    Im echten Terminal steht also:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    Nicht `❓ 这个工具……` und auch nicht `↩ 在 ~/proj 接上上次`. Wer nach der alten Doku im Log greppt,
    findet nichts.

Die fünf Zustände einer Frage sehen auf dem Bildschirm so aus:

| Zustand | Bildschirmausgabe |
|---|---|
| Gestellt | `  ? <问题>`, danach zeilenweise `     1) 选项一`, bei vorhandenem Kontingent zusätzlich `     (还能问 N 次)` |
| Beantwortet | `  + <答案>` |
| Timeout | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Kontingent aufgebraucht | `  ! 提问额度用完` |
| Von dir übersprungen | `  . 已跳过` |

Wenn `--asks` auf unbegrenzt steht (Default), wird die Zeile „还能问 N 次" nicht angezeigt.

Beim [Handoff](glossary.md#换代) erscheint nach dem Schreiben des Handoff-Dokuments ein ganzer Block:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

Bei einem Downgrade des Handoff-Dokuments kommt eine rote Zeile dazu:
`交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

Die Ausgabe erledigt außerdem zwei Dinge, die du nicht siehst: Alle Ausgabezeilen laufen durch eine
Desinfektion, die **nur flowers eigene SGR-Farbcodes durchlässt** — Clear-Screen- und
Cursor-Bewegungssequenzen aus Modell oder Tools werden komplett verschluckt. Und die Breite ist
`max(40, min(Terminalspalten, 110))`, deshalb wird auf breiten Terminals nicht die ganze Zeile
gefüllt; das ist Absicht.

### Die Eingabeaufforderung beim Start {#起跑时的提示符}

Wird `flower` nackt gestartet (ohne Anliegen), fragt es zuerst nach. Zwei Textvarianten:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

Die zweite erscheint nur, wenn in diesem Verzeichnis schon einmal gelaufen wurde und `需求.md` alle
vier Abschnitte hat.

Diese Eingabeaufforderung liest über `input()` und geht **nicht durch die Shell-Auswertung**.
Chinesische Anführungszeichen, Leerzeichen, Ausrufezeichen kannst du direkt tippen — das ist der ganze
Grund für ihre Existenz. zsh geht bei einem chinesischen rechten Anführungszeichen in die
Fortsetzungszeile `dquote>`, was aussieht wie ein Hänger, obwohl gar nichts gestartet wurde.

- Leere Eingabe + erster Lauf → Ende, Ausgabe ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Leere Eingabe + Wake → **zulässig**, bedeutet „mach weiter"
- Eingabe `/new` → äquivalent zu `--new`, archiviert den vorigen Abschnitt und fragt **danach noch einmal** nach dem Anliegen
- Ctrl-C / Ctrl-D → Ende, Ausgabe `已取消`

### Timeout {#超时}

`--timeout` ist ein Float in Sekunden, Default `1800.0`. Drei Fälle:

| Wert | Verhalten |
|---|---|
| `> 0` | So viele Sekunden warten. Bei Timeout wird die Frage als `timeout` abgerechnet, der Agent entscheidet selbst |
| `0` oder negativ | **Vollautomatisch.** Die Frage kommt nicht in die Warteschlange, es wird kein `asked`-Event gesendet, sie erscheint nicht auf dem Bildschirm und wird sofort als `timeout` abgerechnet |
| Ewig warten | **Über die Kommandozeile nicht erreichbar.** Intern wird „ewig warten" unterstützt, aber `--timeout` ist ein Float mit Default — es gibt keine Schreibweise, die das erzeugt. Die Obergrenze ist eine sehr große Sekundenzahl |

`--timeout 0` und `--timeout -1` sind völlig äquivalent. In Pipes, in CI, unbeaufsichtigt — überall
wird das benutzt.

Bleibt eine Frage unbeantwortet, ist das Tool-Ergebnis, das an das Modell zurückgeht, fester Text,
in vier Varianten:

| Ergebnis | Text zurück ans Modell |
|---|---|
| Kontingent aufgebraucht | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| Von dir übersprungen | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| Frage war leer | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**Ctrl-C hat an den beiden Stellen völlig unterschiedliche Bedeutung.**

**Auf der Start-Eingabeaufforderung `> ` gedrückt** — beendet das Programm sofort, Ausgabe `已取消`.

**Während des Runs gedrückt** — unterbricht die aktuelle Runde und gibt dir eine Gelegenheit,
etwas zu sagen:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Hier einfach Enter heißt: nur unterbrechen, nichts sagen, weiterlaufen. Gibt es zu diesem Zeitpunkt
offene Fragen, kommt eine Zeile dazu: `  (有 N 个提问还等着,打断不影响它们)`.

**Noch einmal Ctrl+C beendet wirklich**, und zwar als ungefangenes `KeyboardInterrupt` — auf dem
Bildschirm steht dann ein Python-Traceback, kein sauberer Exit.

Die Unterbrechung ist kooperativ: Sie trennt sauber an einer Nachrichtengrenze und bricht Tasks nicht
hart ab. Sie **zählt nicht als fehlgeschlagener Versuch** und verbraucht keinen Retry. Beim
Weiterlaufen wird eine Erklärung angehängt, die dem Modell sagt, dass ein `interrupted` von einem
noch fliegenden Tool-Aufruf eine normale Nebenwirkung der Unterbrechung ist und keine Umgebungsstörung.

Dieses eigene Ctrl-C wird nur installiert, wenn `sys.stdin.isatty()` gilt (`cli.py:1097`). In einer
Pipe bleibt Pythons Default-Verhalten, also Ende schon beim ersten Mal. Der `once`-Pfad geht hier
nicht durch, deshalb beendet Ctrl-C auch bei `once` schon beim ersten Mal.

### SIGHUP / SIGTERM {#sighup-sigterm}

Die Pfade `go` und `run` installieren Handler für `SIGHUP` und `SIGTERM`: Zuerst wird **der gerade
fliegende Schritt** noch in `manifest.json` geschrieben und als `killed-by-signal` markiert, dann wird
die Default-Aktion wiederhergestellt und wirklich beendet.

Auslöser war: Beim Absturz des Terminals schickt der Kernel SIGHUP, die Default-Aktion beendet den
Prozess sofort, `finally` läuft nicht, das Manifest wird nicht geschrieben — und die Abrechnung eines
ganzen Runs ist weg. Ist der Prozess nicht im Haupt-Thread des Betriebssystems oder unterstützt die
Plattform das nicht, wird still übersprungen.

---

## Der Konfigurationsablauf beim ersten Lauf {#首次运行的配置流程}

Die drei Einstiegspunkte `go`, `run` und `once` rufen am Anfang alle `ensure_credentials()` auf
(`cli.py:1392-1428`), **zwei Hürden**.

### Erste Hürde: Gibt es Credentials {#第一道-有没有凭证}

Die Credentials werden nach Priorität durchgesucht. Findet sich weder `ANTHROPIC_API_KEY` noch
`ANTHROPIC_AUTH_TOKEN`, startet die interaktive Konfiguration; nicht-interaktiv (stdin ist kein
Terminal) blockiert nichts, es wird dieser Text ausgegeben und beendet:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Dieser Text stimmt an zwei Stellen nicht mit der Implementierung überein: Das `flower setup` in der
zweiten Zeile ist derzeit nicht erreichbar (siehe [`setup`](#setup)); die vierte Zeile ist
**das Gegenteil des Codes** — flower nimmt den `env`-Block aus `~/.claude/settings.json` und
`settings.local.json` sehr wohl als **letzte Fallback-Ebene** und borgt sich daraus 9 Credential-Keys,
ohne irgendeine andere Einstellung zu übernehmen. Die Stelle, die diese Zeile ausgibt, ist
`env.py:192` (die Funktion `check_credentials()` ist in `env.py:184` definiert), gelesen werden die
beiden Dateien dagegen in `env.py:56-75` und `:109-111`; notiert in
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).
**Maßgeblich ist der Code: Es liest sie.** Die vollständige Suchreihenfolge und die 9 Keys stehen in
der [Konfigurationsreferenz](config.md#借用).

### Was die interaktive Konfiguration fragt {#交互配置问什么}

```text
== 配置 flower ========================================
<为什么要配这一行>
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   > 

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   > 

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   > 

+ 存好了:/Users/you/.config/flower/.env
```

- Frage 1 ist **Pflicht**. Bleibt sie leer, kommt die rote Zeile `没给 token,取消。` und die
  Konfiguration wird abgebrochen.
- Fragen 2 und 3 dürfen leer bleiben.
- Ist stdin kein Terminal, wird der ganze Ablauf übersprungen, ohne zu blockieren.

### Welche Keys geschrieben werden {#写出来的键}

| Deine Eingabe | Geschriebener Key |
|---|---|
| Token beginnt mit `sk-ant-` | `ANTHROPIC_API_KEY` |
| Anderes Token | `ANTHROPIC_AUTH_TOKEN` |
| Gateway-Adresse nicht leer | `ANTHROPIC_BASE_URL` |
| Modellname nicht leer | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` — alle drei zusammen |

Der Dateipfad ist `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, das Elternverzeichnis wird automatisch
angelegt. Geschrieben wird **die ganze Datei neu**, Keys mit leerem Wert werden übersprungen, danach
`chmod 0600`, und die Werte werden sofort geladen — kein Neustart der Shell nötig.
Die erste Zeile ist immer ein Kommentar, der daran erinnert, die Datei nicht ins Repository zu committen.

### Zweite Hürde: Funktionieren die Credentials {#第二道-凭证能不能用}

Sind die Credentials vollständig, wird eine Zeile `- 验一下凭证…` ausgegeben und dann **wirklich
einmal die API aufgerufen**.

Details der Probe: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, Default-Timeout 20 Sekunden, über
`urllib` aus der stdlib, ohne zusätzliche Abhängigkeit. Das Modell wird in der Reihenfolge
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022` gewählt. Gibt es
`ANTHROPIC_API_KEY`, wird der Header `x-api-key` benutzt, sonst
`authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` steht bewusst auf 16 statt auf 1: In Tests passt bei Modellen mit erzwungener
Gedankenkette nicht einmal das Denken hinein, und der Server quält sich 30 Sekunden lang bis zur
Antwort; mit 16 sind es nur 3.6 Sekunden.

Das Ergebnis der Probe wird in drei Klassen behandelt, **die Unterschiede sind wichtig**:

| Ergebnis | Auslöser | Was flower tut |
|---|---|---|
| `auth` | HTTP 401 / 403, oder es gibt schlicht keine Credentials | Gibt `! 凭证被拒:<响应体前 160 字>` aus, startet die interaktive Neukonfiguration und prüft danach erneut. Nicht-interaktiv: Exit-Code 1 |
| `config` | HTTP 404, oder 400 **und** der Response-Body sagt ausdrücklich „nicht gefunden / existiert nicht" (eines von `not_found`, `not found`, `does not exist`, `unknown model`, `no such model`, `invalid model`) | Gibt `! 网关地址或模型名不对:<…>` aus, sonst wie oben |
| `net` | Keine Verbindung / Timeout / DNS-Fehler / TLS-Fehler / 5xx | Gibt `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)` aus, **keine Neukonfiguration, es läuft direkt los** |
| `ok` | Kleiner als 400, oder alles Unentscheidbare wird durchgelassen | Still weiter |

Das Kriterium für `config` ist **nachträglich verengt worden**: In Fehler-JSON im Anthropic-Stil
taucht das Wort `model` fast zwangsläufig auf; nähme man das als „Modellname falsch", würde ein
kurzzeitiges 400 als Konfigurationsfehler fehlgedeutet und jemand zur Neukonfiguration gezwungen —
es muss ausdrücklich „nicht gefunden / existiert nicht" dastehen (`env.py:176-182`).

Die `net`-Zeile ist Absicht: Ein Netzwerkwackler soll niemanden zwingen, das Token neu einzutippen,
und flower hat selbst einen Mechanismus, der bei Netzausfall pausiert und neu verbindet. „Probe kam
nicht durch" kannst du ignorieren, einfach weiterlaufen lassen.

Die Chance zur Neukonfiguration gibt es **höchstens einmal**. Scheitert es beim zweiten Mal, wird beendet.

**Die Probe läuft nur in einem interaktiven Terminal.** `ensure_credentials()` kehrt sofort zurück,
ohne diesen einen API-Aufruf zu machen, sobald eine der folgenden Bedingungen zutrifft
(`cli.py:1413`): Der Aufrufer hat `probe=False` übergeben, [`FLOWER_NO_PROBE`](config.md#行为开关)
ist gesetzt, oder **stdin ist kein Terminal** (Pipe / CI / Offline-Test). Der Grund: Nicht-interaktiv
lässt sich ein gefundenes Problem ohnehin nicht beheben, der einzige Effekt wäre „früher scheitern" —
und früher scheitern ist bei einer **Fehldiagnose** schlimmer als gar nicht prüfen. Sind die
Credentials wirklich kaputt, fliegt es im Lauf ohnehin auf, und dieser Fall wird von der
[automatischen Neukonfiguration nach einem Absturz](#跑挂了之后的自动重配) aufgefangen.

### Automatische Neukonfiguration nach einem Absturz {#跑挂了之后的自动重配}

Scheitert der Workflow, prüft flower die Fehlermeldung des fehlgeschlagenen Schritts gegen einen
regulären Ausdruck (401, `invalid api key`, `authentication`, `unauthorized`,
`无效…key/token/密钥`). Trifft er zu und ist stdin ein Terminal, wird sofort
`! 看起来是凭证不对:<前 120 字>` ausgegeben und die interaktive Konfiguration gestartet; danach:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

Anschließend wird in jedem Fall mit Exit-Code 1 beendet. Der `once`-Pfad hat diesen Abschnitt nicht.

---

## Exit-Codes {#退出码}

| Code | Wann |
|---|---|
| `0` | Normal durchgelaufen |
| `1` | Alle aktiven Abbrüche. Die Meldung geht nach **stderr**, kein Traceback. Liste siehe unten |
| `2` | argparse-Parameterfehler: unbekannter Schalter, fehlendes Positionsargument, `-p` mit einem Wert außerhalb der choices |
| `130` | Zweimal Ctrl+C während des Runs. Ein ungefangenes `KeyboardInterrupt`, **mit Python-Traceback** |
| Durch Signal beendet | SIGHUP / SIGTERM: Erst den fliegenden Schritt ins Manifest schreiben, dann per Default-Aktion beenden |

Alle Meldungen zu Exit-Code 1:

| Meldung | Wann |
|---|---|
| `已取消` | Ctrl-C oder Ctrl-D auf der Start-Eingabeaufforderung |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Ganz neues Verzeichnis + nur Enter |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (insgesamt 4 Zeilen) | Nicht-interaktiv + keine Credentials |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Nicht-interaktiv + Probe ergibt `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Nicht-interaktiv + Probe ergibt `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` in einem Verzeichnis ohne git benutzt |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Anliegen leer und im Verzeichnis gibt es kein Wake |
| `在步骤 '<步骤名>' 中止` | Ein Schritt im Workflow ist gescheitert und die Policy ist „stoppen" |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, Doppelpunkt vergessen |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | Import des Zielmoduls schlägt fehl |
| `'<模块>' 里没有 '<属性>'` | Das Attribut ist im Modul nicht zu finden |

Am Ende (Pfade `go` / `run`) wird eine Zeile ausgegeben:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

Dieser Betrag zählt nur die Kosten **dieses Prozesses**, nicht die des vorigen Runs — obwohl die
Manifest-Datei selbst prozessübergreifend akkumuliert.

---

## Was es im Projekt anlegt {#它在项目里创建了什么}

Zwei Bäume: `<run_dir>/` (Default `./runs/`, relativ zum CWD) enthält Abrechnung und Sessions;
`<workspace>/.flower/` enthält die [Workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Pfad | Inhalt |
|---|---|
| `runs/sessions.db` | SQLite, vollständige Transcripts. Das ist die materielle Grundlage dafür, dass [Kontinuität](glossary.md#接续) überhaupt anschließen kann |
| `runs/manifest.json` | Das [Run-Manifest](glossary.md#运行清单). JSON-Array, **prozessübergreifend akkumuliert**; alle Zahlen aus den Fallseiten lassen sich hier nachrechnen |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Wird atomar ersetzt geschrieben |
| `runs/aside/` | Eigene Runtime der Oracle-Fragen, mit eigener `sessions.db` und eigenem `manifest.json`. **Kosten und Lineage landen nicht im Haupt-Manifest** |
| `runs/workbench/` | Erscheint nur bei `-W` und wenn der Workflow keine eigene Workbench mitbringt (Pfade `run` / `once`) |

Felder eines Eintrags in `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` ist die Markierung dieses Prozesses, Format `YYYYmmdd-HHMMSS-<6 位 hex>`. Geschrieben wird
**anhängend, nicht überschreibend**: Vor jedem Schreiben wird die Datei neu eingelesen und nach `run`
dedupliziert — Zeilen dieses Prozesses werden durch die aktuellen ersetzt, Zeilen anderer Prozesse
bleiben unverändert stehen.

Schrittnamen haben vier Formen:

| Form | Wann |
|---|---|
| `<步骤名>` | Erster Versuch |
| `<步骤名>#retry<N>` | Normaler Retry |
| `<步骤名>#round<N>` | Vom Verdikt zurückgewiesen und weitergearbeitet |
| `<步骤名>·判定#<N>` | Der Schritt des [Judge](glossary.md#判定者) |

Wird der Prozess durch ein Signal beendet, wird auch der fliegende Schritt geschrieben, das Feld
`error` ist dann `killed-by-signal`.

**Mehrere flower-Läufe parallel im selben Verzeichnis**: `manifest.json` ist sicher (Neueinlesen +
Zusammenführen nach `run`), aber `lineage.json` wird ganz überschrieben, zwei Prozesse überschreiben
sich gegenseitig die Lineage gleichnamiger Schritte. Wer parallel laufen lässt, nimmt unterschiedliche `-r`.

In `lineage.json` steht der absolute Pfad des Workspace. Passt er nicht, gilt er als nicht vorhanden
und es wird **still** auf eine neue Session zurückgefallen, ohne Fehler — nach dem Verschieben des
Verzeichnisses wären die alten `session_id` ohnehin nicht auffindbar.

### `.flower/` {#flower-目录}

| Pfad | Inhalt |
|---|---|
| `.flower/scripts/` | Skripte, die ein zweites Mal laufen sollen. Die erste Zeile enthält `# desc: 一句话`, dieser Satz erscheint im Index |
| `.flower/artifacts/` | Lange Ausgaben über 2000 Zeichen: Berichte, Daten, Logs. Im Dialog erscheint nur der Pfad |
| `.flower/notes/` | Schrittübergreifende Entscheidungsnotizen |
| `.flower/spill/` | [Spill](glossary.md#落盘): Tool-Ergebnisse über 4000 Zeichen landen hier, im Kontext bleibt nur eine Zeiger-Zeile plus die ersten 400 Zeichen. Der Dateiname sind die ersten 16 Stellen des sha256 des Inhalts plus `.txt` |
| `.flower/INDEX.md` | Index der obigen Verzeichnisse, wird **in den System-Prompt des Koordinators injiziert** (Subagents erben ihn nicht) |

Der `go`-Pfad erzeugt fest unter `notes/`:

| Datei | Inhalt |
|---|---|
| `notes/需求.md` | Der eingefrorene [Anforderungsbrief](glossary.md#需求确认书), vier Abschnitte: Ziel / Abnahmekriterien / Grenzen / Unbekanntes und Annahmen |
| `notes/目标.md` | Das eingefrorene Ziel, zwei Abschnitte: Ziel / Prüfliste für das Verdikt |
| `notes/问答记录.md` | Anhängendes Protokoll aller Fragen und Antworten (mit Status), inklusive dessen, was du von dir aus gesagt hast. **Kommt nicht in den Kontext, dient nur der Archivierung** |
| `notes/交接-<步骤名>.md` | Das beim Handoff geschriebene [Handoff-Dokument](glossary.md#交接书); die vorige Generation wandert nach `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | Die von `--new` oder `/new` archivierten `lineage.json`, `需求.md`, `目标.md`. Es wird **verschoben**, nicht gelöscht |

Mit `--isolate` wandert die Workbench aus dem Repository heraus:
`<workspace>.parent/.flower-<workspace 名>/`. Ein Worktree ist die private Kopie jedes Agents, die
Workbench ist die agentenübergreifend geteilte Ebene — Geteiltes darf nicht in den privaten Zaun.
Der Workbench-Pfad, den das Modell in diesem Fall bekommt, ist ein absoluter Pfad.
