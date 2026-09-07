# CLI-Referenz

Nach der Installation gibt es genau eine ausführbare Datei, 4 Subcommands, 23 Schalter. Diese Seite listet
sie alle auf: Typ, Default und exakte Semantik jedes Schalters, dazu wie man mitten im Run dazwischenredet,
was beim ersten Start gefragt wird, welche Exit-Codes es gibt und welche Dateien in deinem Verzeichnis
angelegt werden. Nach dieser Seite musst du den Quelltext nicht mehr aufmachen.

Quelltext: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcommand | Wozu | Positionsargument | Eigene Schalter |
|---|---|---|---|
| `go` | Alles am Stück: Anforderungen klären → Ziele setzen → Arbeit verteilen → jede Runde ein Verdict. Default, wenn kein Subcommand angegeben ist | `ask` (optional) | 11 |
| `run` | Führt einen selbst geschriebenen [Workflow](glossary.md#流程) aus | `target` (erforderlich) | 0 |
| `once` | Einmalig ein einzelner Agent, ohne Workflow, ohne Verdict | `prompt` (erforderlich) | 6 |
| `setup` | Credentials konfigurieren, geschrieben nach `~/.config/flower/.env` | keins | 0 |

23 Schalter insgesamt = 5 globale + 11 für `go` + 6 für `once` + `-h/--help`. `run` und `setup`
haben keine eigenen Schalter.

---

## Aufrufformen {#调用形式}

Alle argv von `flower` laufen zuerst durch `_with_default_cmd()`, das den Default-Subcommand ergänzt, und
gehen erst dann an argparse (`cli.py:1253-1255`). Deshalb funktioniert `flower "帮我做一个 X"` — es wird
umgeschrieben zu `flower go "帮我做一个 X"`.

Die Regeln für das Ergänzen des Default-Subcommands (`cli.py:761-797`):

1. Die Menge der globalen Schalter wird **aus dem Haupt-Parser selbst abgeleitet**, sie ist keine
   hartkodierte Liste. `nargs == 0` gilt als reiner Schalter, alles andere als Schalter mit Wert.
2. Von links nach rechts scannen, globale Schalter überspringen. Bei Schaltern mit Wert wird der Wert
   mitübersprungen; die `=`-Schreibweise wie `--workspace=/tmp` wird ebenfalls erkannt.
3. Beim ersten Token halten, das kein globaler Schalter ist. Ist es `go`, `run` oder `once`, geht alles
   unverändert an argparse; **andernfalls wird ein `go` davor eingefügt**, womit es zum Anliegen für `go` wird.
4. Wurde bis zum Ende kein Positionsargument gefunden (leeres argv, oder nur globale Schalter) → am Ende
   `go` anhängen und in die interaktive Eingabe gehen.
5. Ausnahme: Enthält argv `-h` oder `--help`, wird unverändert zurückgegeben und argparse druckt die Hilfe.

Die Konstante für diese Entscheidung ist `_CMDS = ("go", "run", "once")` (`cli.py:758`) — **`setup` steht
nicht drin**, Konsequenzen siehe [`setup`](#setup).

### Was tatsächlich umgeschrieben wird {#实际的改写结果}

| Was du tippst | Wird tatsächlich geparst als | Wirkung |
|---|---|---|
| `flower` | `["go"]` | Fragt interaktiv „要做什么?" |
| `flower -v` | `["-v", "go"]` | Dasselbe, mit verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Legt direkt los |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Globale Schalter dürfen vorne stehen |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | Die `=`-Form wird auch erkannt |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Subcommand-Schalter dürfen hinter dem Anliegen stehen |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | Oder auch davor |
| `flower --new` | `["go", "--new"]` | Nur Schalter, kein Anliegen → interaktive Eingabe |
| `flower once "hi"` | `["once", "hi"]` | Unverändert |
| `flower run flows:main` | `["run", "flows:main"]` | Unverändert |
| `flower run` | `["run"]` | argparse meldet fehlendes `target`, wird **nicht** als Anliegen gedeutet |
| `flower go run` | `["go", "run"]` | Explizit disambiguiert: das Anliegen ist der Text `run` |
| `flower setup` | `["go", "setup"]` | Es läuft `go`, das Anliegen ist der String `setup`, siehe [`setup`](#setup) |
| `flower --help` | Unverändert | argparse druckt die Hilfe |

Die beiden Wörter `run` und `once` können **nicht** direkt als Anliegen verwendet werden; diese
Mehrdeutigkeit ist absichtlich so belassen (`cli.py:770-771`). Wenn du sie als Anliegen brauchst,
schreib `flower go run`.

### Sechs brauchbare Schreibweisen {#六种能用的写法}

```bash
flower                                    # 1. Nackt: fragt interaktiv „要做什么?" oder „接着上次?"
flower "帮我做一个 X"                       # 2. Anliegen als Positionsargument
echo "帮我做一个 X" | flower --timeout 0    # 3. Über die Pipe in stdin
flower once "读一眼这个仓库"                 # 4. Einzelner Agent
flower run flows.py:main                  # 5. Eigener Workflow
flower go setup                           # 6. Explizites go, setup ist der Anliegentext
```

Die Modulform `python -m flower.cli` ist äquivalent zu `flower` (`cli.py:1263-1264`).
Der Container-Wrapper `docker/flowerbox` nimmt exakt dieselben Argumente wie `flower`.

### Über die Pipe in stdin {#管道喂-stdin}

Wenn `sys.stdin.isatty()` falsch ist, druckt `ask_for_prompt()` **keinen Prompt-Header**, sondern liest
direkt mit `input("> ")` eine Zeile (`cli.py:814-822`). Deshalb funktioniert `echo "..." | flower`.

Danach wird allerdings eine Warnung ausgegeben, und der stdin-Thread liest sofort EOF und beendet sich:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

Für Pipe-Betrieb gehört `--timeout 0` dazu: Fragen tun dann nicht mehr so, als würden sie 30 Minuten warten,
sondern gehen sofort ins Leere, der Agent entscheidet selbst und schreibt seine Annahmen in den Abschnitt
„未知与假设" des Briefs.

---

## Subcommands {#子命令}

### `go` {#go}

Hilfetext: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1096-1128`).

Positionsargument `ask`, `nargs="?"` — ohne Angabe geht es in die interaktive Eingabe. Das ist der am
häufigsten benutzte Einstieg; `flower "做 X"` landet hier.

Was es tut (`cli.py:1011-1042`):

1. `ensure_credentials()` — prüft die Credentials und schickt tatsächlich eine API-Probe los, siehe
   [Konfigurationsablauf beim ersten Start](#首次运行的配置流程).
2. [Wake](glossary.md#唤醒)-Erkennung: schaut nur lesend nach, ob dieses Verzeichnis schon benutzt wurde,
   schreibt kein einziges Byte.
3. Ohne `ask` kommt ein Prompt mit einer Frage; die Eingabe `/new` entspricht `--new`, danach wird
   **noch einmal** nach dem Anliegen gefragt.
4. Bei [Continuity](glossary.md#接续) wird ein Wake-Banner ausgegeben.
5. Baut den dreistufigen [Workflow](glossary.md#流程): `确认需求` → `设定目标` → `干活`,
   nach jeder Arbeitsrunde folgt ein `干活·判定#N`. `--clarify-only` lässt nur den ersten Schritt übrig.
6. Los geht's.

So sieht das Wake-Banner aus (das Home-Verzeichnis im Pfad wird durch `~` ersetzt):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` steht immer da; `目标 N 条` erscheint nur, wenn es eine Verdict-Checkliste gibt;
`干活上下文 X` setzt voraus, dass sich der Kontext der letzten Runde jener [Session](glossary.md#会话) in
`sessions.db` finden lässt — wird sie nicht gefunden, wird nichts angezeigt.

!!! warning "`-W` und `-T` werden auf dem `go`-Pfad stillschweigend überschrieben"
    Diese beiden globalen Schalter haben bei `go` keine Wirkung, ohne Fehler und ohne Hinweis:

    - `-W/--workbench`: Der von `go` gebaute Workflow bringt immer seine eigene
      [Workbench](glossary.md#工作台) mit, und der Code nimmt
      `getattr(wf, "workbench", None) or args.workbench` (`cli.py:859`) — die des Workflows hat also
      immer Vorrang. Die Workbench ist damit fest `<workspace>/.flower/`
      (bei `--isolate` `<workspace>.parent/.flower-<Name>/`), `-W` ändert daran nichts.
    - `-T/--trim`: `go` geht über `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1042`), nutzt also
      direkt die Negation von `--no-trim` und **schaut `args.trim` gar nicht an**. Auf dem `go`-Pfad ist
      [Trim](glossary.md#裁剪) also standardmäßig an und lässt sich nur mit `--no-trim` abschalten.

    Diese beiden Schalter wirken nur bei `run` (wenn der Workflow keine eigene Workbench mitbringt)
    und bei `once`.

#### Die 11 Schalter von `go` {#go-的-11-个开关}

| Schalter | Typ | Default | Beschreibung |
|---|---|---|---|
| `--asks N` | int | `-1` | Frage-Kontingent. `-1` oder jede negative Zahl = **unbegrenzt**; `0` = keine Fragen erlaubt, die erste Frage ergibt sofort `over_budget`; `N` = hartes Kontingent. Bei Überschreitung weist das Tool direkt ab, der Run blockiert nicht |
| `--rounds N` | int | `3` | Obergrenze der **Gesamtrunden** der Arbeit, nicht der zusätzlichen Runden. Am Ende jeder Runde entscheidet ein eigenständiger [Judge](glossary.md#判定者), ob „fertig" ist; wenn nicht, geht es in derselben Session weiter |
| `--no-goal` | Schalter | `False` | Schaltet den [Goal Guard](glossary.md#目标看守) ab: kein `目标.md`, kein [Verdict](glossary.md#判定), nach der Arbeit ist Schluss |
| `--judge-can-run` | Schalter | `False` | Erlaubt dem Judge, Kommandos auszuführen. Das Verdict wird härter, der Preis ist, dass er damit auch den Workspace verändern kann |
| `--timeout Sekunden` | float | `1800.0` | Wie lange auf eine Antwort gewartet wird. `0` oder negativ = vollautomatisch, alle Fragen gehen **sofort** ins Leere, ohne so zu tun, als würde gewartet. Semantik siehe [Timeout](#超时) |
| `--isolate` | Schalter | `False` | Jeder [Subagent](glossary.md#subagent) bekommt ein eigenes git worktree, also [Isolation](glossary.md#隔离). **Setzt voraus, dass der Workspace ein git-Repository ist**, sonst Exit-Code 1. Verschiebt außerdem die Workbench aus dem Repository heraus |
| `--window N` | int | keiner (wird aus dem Modellnamen abgeleitet) | Kontextfenster des Modells. Ohne Angabe: Modellname enthält `1m` oder enthält kein `haiku` → 1.000.000; enthält `haiku` → 200.000. Bei `Fenster − 50000` wird ein [Handoff-Dokument](glossary.md#交接书) geschrieben und ein [Handoff](glossary.md#换代) gemacht |
| `--no-handoff` | Schalter | `False` | Schaltet den Handoff ab, zurück zum SDK-eigenen [Compact](glossary.md#压缩) |
| `--new` | Schalter | `False` | Diesmal nicht an die letzte Runde anknüpfen. `lineage.json` + `需求.md` + `目标.md` des vorigen Abschnitts werden nach `notes/archive/<YYYYmmdd-HHMMSS>/` **verschoben** (nicht gelöscht), dann geht es von vorne los |
| `--clarify-only` | Schalter | `False` | Nur [Clarify](../guide/clarify.md), keine Arbeit danach — im Workflow bleibt nur der Schritt `确认需求` übrig |
| `--no-trim` | Schalter | `False` | Schaltet Trim ab. Auf dem `go`-Pfad ist Trim standardmäßig **an**, dies ist die einzige Möglichkeit, es abzuschalten |

Randfälle bei den Werten, allesamt ohne Fehler und ohne Hinweis:

- `--rounds 0` und `--rounds 1` sind äquivalent — intern gilt `retries = max(0, rounds - 1)`, beide laufen 1 Runde.
- Jede negative Zahl bei `--asks` bedeutet unbegrenzt, nicht nur `-1`.
- Jede negative Zahl bei `--timeout` entspricht `0`, also vollautomatisch.
- `--window 0` wird **stillschweigend ignoriert** (`0` ist falsy und wird gar nicht weitergereicht), es
  gilt wieder der aus dem Modellnamen abgeleitete Default. Negative Werte werden durchgereicht und dann
  auf `10000` hochgezogen.
- `--clarify-only` ist in einem bereits geklärten Verzeichnis eine **No-Op** — der Schritt `确认需求`
  überspringt sich selbst, wenn er ein vollständiges `需求.md` sieht, und da der Workflow nur aus diesem
  Schritt besteht, passiert nichts (außer Wake-Zähler +1). Für eine erneute Klärung braucht es `--new`.
- Am Ende der `--help` von `go` steht „全局开关(-v/-w/-r/-T)见 `flower --help`" — in dieser Zeile
  **fehlt `-W`**.

### `run` {#run}

Hilfetext: `运行一个 workflow` (`cli.py:1130-1133`).

Positionsargument `target` in der Form `Modul:Attribut`. Beide Formen werden unterstützt (`cli.py:831-852`):

```bash
flower run mypkg.flows:build     # Import über den Modulnamen
flower run flows.py:build        # Dateipfad; das Elternverzeichnis wandert in sys.path, dann Import über den Dateinamen
```

Ist das gefundene Attribut aufrufbar, wird es einmal aufgerufen und der Rückgabewert als
[Workflow](glossary.md#流程) genommen; ist es bereits ein Workflow-Objekt, wird es direkt verwendet.

**`run` hat keinerlei eigene Schalter**, nur die 5 globalen. `--window`, `--no-handoff` und Konsorten
haben auf diesem Pfad also immer ihre Default-Werte (der Code fängt das mit `getattr` ab,
`cli.py:862-864`). Wer sie einstellen will, schreibt die Parameter in den eigenen Workflow.

### `once` {#once}

Hilfetext: `跑一次单 agent` (`cli.py:1135-1145`). Das Positionsargument `prompt` ist erforderlich.

Es baut ein `AgentSpec(name="ad-hoc", …)` und führt es direkt aus, **ohne über `_drive` zu gehen**.
Deshalb gibt es bei `once` nichts von alledem:

- Mit Ctrl-C unterbrechen und dazwischenreden (der Tastendruck ist ein ganz normales `KeyboardInterrupt`)
- stdin-Antwort-Thread, dauerhafter Eingabe-Prompt am unteren Rand
- Oracle-Fragen
- SIGHUP / SIGTERM-Notabrechnung
- Die Abschlusszeile `总花费 … · 清单 …`
- Die geführte Neukonfiguration nach fehlgeschlagenen Credentials

Im [Run-Manifest](glossary.md#运行清单) heißt dieser Schritt fest `ad-hoc`.

| Schalter | Typ | Default | Beschreibung |
|---|---|---|---|
| `-i`, `--instructions` | str | leer | Domänenanweisungen, werden **hinter** den nativen System-Prompt von Claude Code [angehängt](glossary.md#叠加), nicht an dessen Stelle |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Komma-getrennte Tool-Whitelist. Ohne Angabe genau diese drei Nur-Lese-Tools |
| `-p`, `--permission-mode` | str | `default` | Erlaubt sind nur `default`, `acceptEdits`, `plan`, `bypassPermissions`; bei anderen Werten meldet argparse einen Fehler mit Exit-Code 2 |
| `-b`, `--budget` | float | unbegrenzt | [Budget](glossary.md#预算)-Obergrenze in Dollar, bei Überschreitung wird gestoppt |
| `--resume SESSION_ID` | str | keiner | Eine bestehende Session fortsetzen |
| `--fork` | Schalter | `False` | Forken statt fortsetzen, in Verbindung mit `--resume` |

!!! warning "Bei `once` sind angezeigte Laufzeit und kumulierte Kosten immer 0"
    `once` legt für jedes eintreffende Event eine neue Renderer-Instanz an (`cli.py:579-581`,
    `cli.py:1060`), während Startzeitpunkt und kumulierte Kosten auf der Instanz liegen
    (`cli.py:393-394`). Also:

    - Die `用时` in der Abschlusszeile ist konstant `0:00`
    - Das `累计 $0.00` in der Statuszeile ist konstant 0, und `上下文` akkumuliert nie

    Die echten Kosten des einen Schritts stehen im Feld `cost_usd` in `runs/manifest.json`. Die Pfade
    `go` und `run` halten dieselbe Renderer-Instanz und haben dieses Problem nicht.

### `setup` {#setup}

Hilfetext: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1147-1149`).
Keine Schalter.

Was es tut: `.env` einlesen → prüfen, ob schon konfiguriert wurde → interaktiven Konfigurationsablauf
starten, mit `reason` = `重新配置。` oder `还没配过凭证。`. Was auf dem Bildschirm passiert, steht unter
[Konfigurationsablauf beim ersten Start](#首次运行的配置流程).

!!! warning "`flower setup` erreicht diesen Subcommand derzeit nicht"
    In der Konstante für den Default-Subcommand, `_CMDS = ("go", "run", "once")` (`cli.py:758`),
    **fehlt `"setup"`**, obwohl `setup` im Parser tatsächlich registriert ist (`cli.py:1147`). `flower setup`
    wird dadurch zu `flower go setup` umgeschrieben — **es läuft der komplette `go`-Workflow mit dem
    Anliegentext `setup`**: erst Credentials prüfen, dann nach den Anforderungen fragen, dann wirklich
    anfangen zu arbeiten. Mit globalen Schaltern ist es dasselbe: `flower -v setup` → `["-v", "go", "setup"]`.

    **Es gibt kein argv, das den `setup`-Subcommand erreicht.**

    Für die Konfiguration der Credentials bleiben derzeit nur diese zwei Wege, beide landen in derselben
    interaktiven Oberfläche:

    - Einfach `flower "随便一句诉求"` starten; ohne konfigurierte Credentials fragt es vorher nach;
    - Oder `~/.config/flower/.env` von Hand schreiben, die Schlüsselnamen stehen unter
      [Welche Schlüssel geschrieben werden](#写出来的键).

    Betroffen sind auch ein paar Texte: das ``跑 `flower setup` 重配。`` bei abgelehnten Credentials und
    der Kommentar ``由 `flower setup` 写`` in der ersten Zeile von `.env` verweisen alle auf dieses
    nicht erreichbare Kommando.

---

## Globale Schalter {#全局开关}

Die 5 globalen Schalter hängen gleichzeitig am Haupt-Parser und an jedem Subcommand (`cli.py:1071-1087`).
Die Variante am Subcommand nutzt `argparse.SUPPRESS`, setzt das Attribut also nicht, wenn sie nicht
angegeben wird — deshalb ist es **egal, ob du sie vor oder hinter den Subcommand schreibst**, sie
überschreiben einander nicht. Nebenwirkung: In der `--help` der Subcommands tauchen sie nicht auf —
dafür braucht es `flower --help`.

| Schalter | Typ | Default | Beschreibung |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | Arbeitsverzeichnis des Agents. Wird per `resolve()` zum absoluten Pfad und mit `mkdir -p` angelegt. Die [Workbench](glossary.md#工作台) `.flower/` entsteht darin |
| `-r`, `--run-dir` | str | `runs` | Verzeichnis für [Session-Store](glossary.md#会话存储) und Run-Manifest. **Relativ zum aktuellen CWD, nicht zum Workspace** |
| `-v`, `--verbose` | Schalter | `False` | Druckt mehr, siehe unten |
| `-W`, `--workbench` | Schalter | `False` | Aktiviert die Workbench. **Bei `go` wirkungslos**, wirkt nur bei `run` (wenn der Workflow keine eigene Workbench mitbringt) und bei `once`; die Workbench liegt dann unter `<run_dir>/workbench/` |
| `-T`, `--trim` | Schalter | `False` | Ersetzt beim Resume alte große Tool-Ergebnisse durch Dateizeiger, also [Trim](glossary.md#裁剪). **Bei `go` wirkungslos**, dieser Pfad steuert es umgekehrt über `--no-trim` |
| `-h`, `--help` | Schalter | — | An jedem Parser vorhanden. Taucht es in argv auf, wird das Umschreiben des Default-Subcommands übersprungen und direkt die Hilfe gedruckt |

Dass `-r/--run-dir` relativ zum CWD ist, beißt gelegentlich: `flower -w /other/proj "做 X"` legt `runs/`
**in dem Verzeichnis an, in dem du das Kommando getippt hast**, während `.flower/` unter `/other/proj/`
entsteht — der Zustand ist damit zweigeteilt. Wer beides zusammen haben will, gibt explizit
`-r /other/proj/runs` an.

Die Hilfe zu `-v` sagt „显示思考与工具结果", aber die Gedanken des [Main-Threads](glossary.md#主线程)
**werden ohnehin standardmäßig angezeigt**. Was `-v` tatsächlich zusätzlich einschaltet:

- Den Fließtext von Subagents (standardmäßig unsichtbar, nur ihre Tool-Aufrufe werden gezeigt)
- Normale Tool-Ergebnisse (standardmäßig nur die fehlerhaften)
- `prompt`-Events
- Vor dem Start einmal die aktuell wirksame Credential-Konfiguration, wobei vom Token nur die ersten
  4 Zeichen sichtbar bleiben

Der letzte Punkt läuft über ein nacktes `print()`, **ohne Ausgabe-Sanitizing, ohne Umbruch und ohne
Schutz durch das Terminal-Schreiblock**; wenn mehrere `flower` parallel laufen, können diese Zeilen
zerrissen werden.

---

## Wie man während des Runs mit ihm redet {#运行中怎么和它说话}

Sobald der Run läuft, **liest das Terminal ununterbrochen deine Eingabe**. Du musst nicht auf eine Frage
warten und keine Taste drücken, um in einen Eingabemodus zu kommen — die letzte Zeile ist immer die,
in die du tippen kannst.

### Der Eingabe-Prompt, der unten kleben bleibt {#常驻在最下面的输入提示符}

Ein Daemon-Thread `flower-stdin` liest durchgehend stdin (`cli.py:655-755`), per `select` alle 0,2 Sekunden
gepollt, nicht blockierend (so weckt ihn das Stoppsignal; Streams ohne `select`-Unterstützung, etwa unter
Windows, fallen auf blockierendes Lesen zurück).

**Er liest immer, nicht nur wenn eine Frage offen ist.** Der Grund: Läse er nur bei offenen Fragen, bliebe
alles, was du in den Arbeitsstunden dazwischen tippst, im Terminalpuffer liegen und würde bei der nächsten
Frage als Antwort verschluckt — die Frage wäre beantwortet, bevor du sie überhaupt gesehen hast.

Auf der Anzeigeseite ist `_say()` der einzige Ausgabekanal; vor jeder Ausgabe wird der Prompt gelöscht und
danach neu gezeichnet (`cli.py:299-305`), sodass er nicht durch Event-Ausgaben nach oben geschoben wird.
Der Prompt hat zwei Formulierungen, je nachdem, ob eine Frage offen ist:

| Zustand | Letzte Bildschirmzeile |
|---|---|
| Offene Frage | `你的回答 (回车=跳过,让它自己判断) > ` |
| Keine offene Frage | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Wohin geht, was du tippst {#你敲的东西去哪了}

| Deine Eingabe | Bei offener Frage | Ohne offene Frage |
|---|---|---|
| **Leerzeile (nur Enter)** | Frage überspringen, es entscheidet selbst | Passiert nichts |
| **Beginnt mit `?`** | Oracle-Frage, siehe unten | Dasselbe |
| **Reine Zahl**, innerhalb des Optionsbereichs | Wird durch die entsprechende Option ersetzt und als Antwort geschickt | Wird als normaler Text behandelt |
| Sonstiger Text | Geht als Antwort an den fragenden Agent | Landet im Posteingang, gilt als nachgereichte Anforderung |
| EOF (Ctrl-D oder geschlossene Pipe) | Frage wird abgelehnt, Prompt verschwindet, Thread beendet sich | Prompt verschwindet, Thread beendet sich |

Beim Eingang im Posteingang wird eine Quittungszeile gedruckt:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

Gibt es keinen [Brief](glossary.md#需求确认书), in den gespillt werden könnte, wird die zweite Hälfte zu
`没有确认书可落盘 —— 它可能活不过下一个步骤`. Der Posteingang **unterbricht** den arbeitenden Worker
**nicht**; er nimmt den Inhalt erst mit, wenn er von sich aus das nächste Mal nachsieht. Derselbe Satz wird
außerdem an `notes/需求.md` angehängt — ohne Spill überlebt er die Schrittgrenze nicht, denn der nächste
Schritt ist eine neue Session, die nur eingefrorene Dateien liest.

### `?` am Anfang = Oracle-Frage {#旁路问答}

Eine Zeile, die mit `?` beginnt, geht nicht an den laufenden Agent, sondern an den
[Oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

Er startet eine **eigenständige** Runtime, mit `run_dir` = `<run_dir>/aside/`, sodass seine Kosten und
seine Session-Lineage nicht in die Haupt-`manifest.json` geraten. Die Rolle ist nur lesend, als Tools gibt
es lediglich `Read`, `Glob`, `Grep`, höchstens 12 Runden, Kostenobergrenze **$0.5**. Als Kontext sieht er
die letzten **60** Events (`thinking`- und `prompt`-Events zählen nicht in dieses Fenster), jedes auf
200 Zeichen gekürzt, dazu eine Beschreibung der Workbench-Pfade.

Er läuft **nebenläufig**, der laufende Run wartet keine Sekunde. Die Antwort sieht so aus:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

Bei Fehlern erscheint eine rote Zeile `# 旁路问答失败:<类型>: <消息>`, **ohne Auswirkung auf den
Hauptablauf**. Beim Beenden wird höchstens **120** Sekunden auf den Abschluss der Oracle-Anfragen
gewartet, davor wird `(等 N 条旁路问答收尾…)` ausgegeben.

Was er sagt, gelangt nicht in den Kontext dieses Runs — Fragen beeinflusst den Run nicht, nach der Antwort
ist es weg.

!!! warning "Ein vollbreites `？` löst keine Oracle-Frage aus — chinesische IME-Nutzer stolpern darüber"
    Die Codezeile, die die Oracle-Frage erkennt, lautet (`cli.py:733`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Beide Zeichen sind **halbbreites ASCII `?`** (`0x3f`) — byteweise verifiziert. Der Schreibweise nach
    war offensichtlich beabsichtigt, sowohl das halbbreite `?` als auch das von chinesischen IMEs
    erzeugte vollbreite `？` (U+FF1F) zu akzeptieren, tatsächlich steht dort aber zweimal dasselbe Zeichen.

    Folge: **Eine Zeile, die mit vollbreitem `？` beginnt, wird nicht als Oracle-Frage erkannt**, sondern
    stillschweigend als „nachgereichte Anforderung" in den Posteingang gelegt und damit auch an
    `notes/需求.md` angehängt. Du siehst als Quittung `+ 收到`, nicht `# 旁路`.

    Für eine Oracle-Frage **muss das halbbreite `?` verwendet werden** — vorher die Eingabemethode auf
    Englisch umschalten, oder wenigstens das erste Zeichen halbbreit tippen.

### Was auf dem Bildschirm steht {#屏幕上都是什么}

Die Symbole sind **durchgehend ASCII**, keine Emoji (`cli.py:49-67`). Der Grund steht als Kommentar im
Code: Emoji sowie Rahmen-, Geometrie- und Pfeilzeichen lösen Glyph-Fallbacks im Terminal aus, was schon
zweimal zum Absturz des Terminals geführt hat.

| Symbol | Bedeutung | Symbol | Bedeutung |
|---|---|---|---|
| `=` | Schritttrenner | `+` | Fertig / beantwortet / empfangen |
| `~` | Denken, Retry | `x` | Fehlgeschlagen / Fehler |
| `>` | Beauftragung | `#` | Handoff, Oracle, Task |
| `*` | Tool-Aufruf | `-` | Statuszeile, Listenpunkt |
| `?` | Frage | `<-` | Anknüpfung, Handoff-Ziel |
| `!` | Warnung / Unterbrechung | `.` | Übersprungen |
| `\| ` | Einrückungsstrich für Subagents | | |

!!! warning "Die `❓` und `↩` aus alter Doku existieren im echten Terminal nicht"
    Frühere Dokumentation nutzte `❓` für Fragen und `↩` für die Wake-Zeile. **Im Code standen diese
    beiden Zeichen nie** — das Symbol für Fragen ist ein halbbreites `?`, das Symbol für Wake und
    Handoff-Ziel sind die beiden ASCII-Zeichen `<-`.

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
| Gestellt | `  ? <问题>`, danach zeilenweise `     1) 选项一`, bei begrenztem Kontingent zusätzlich `     (还能问 N 次)` |
| Beantwortet | `  + <答案>` |
| Timeout | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Kontingent erschöpft | `  ! 提问额度用完` |
| Von dir übersprungen | `  . 已跳过` |

Bei unbegrenztem `--asks` (Default) erscheint die letzte Zeile „还能问 N 次" nicht.

Beim [Handoff](glossary.md#换代) wird nach dem Schreiben des Handoff-Dokuments ein ganzer Block ausgegeben:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

Fällt das Handoff-Dokument auf die Notversion zurück, kommt eine rote Zeile dazu:
`交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

Die Ausgabe erledigt außerdem zwei Dinge, die du nicht siehst: Jede Ausgabezeile läuft durch ein
Sanitizing, das **nur die SGR-Farbcodes von flower selbst durchlässt**; von Modellen oder Tools
ausgespuckte Clear-Screen- und Cursor-Sequenzen werden komplett verschluckt. Die Breite ist
`max(40, min(Terminalspalten, 110))`, auf breiten Terminals wird die Zeile also nicht komplett gefüllt —
das ist Absicht.

### Der Prompt beim Start {#起跑时的提示符}

Beim nackten `flower` (ohne Anliegen) kommt zuerst eine Frage. Zwei Formulierungen:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

Die zweite erscheint nur, wenn in diesem Verzeichnis bereits gelaufen wurde und `需求.md` alle vier
Abschnitte enthält.

Dieser Prompt liest über `input()`, **ohne Shell-Parsing**. Chinesische Anführungszeichen, Leerzeichen,
Ausrufezeichen kann man direkt tippen — das ist der ganze Grund, warum es ihn gibt. zsh geht bei einem
chinesischen schließenden Anführungszeichen in die Fortsetzungszeile `dquote>`, was aussieht wie ein
Hänger, obwohl gar nichts gestartet wurde.

- Leere Eingabe + erster Start → Abbruch mit ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Leere Eingabe + Wake → **gültig**, bedeutet „mach weiter"
- Eingabe `/new` → entspricht `--new`, nach dem Archivieren des vorigen Abschnitts wird **noch einmal**
  nach dem Anliegen gefragt
- Ctrl-C / Ctrl-D → Abbruch mit `已取消`

### Timeout {#超时}

`--timeout` ist ein float in Sekunden, Default `1800.0`. Drei Wertebereiche:

| Wert | Verhalten |
|---|---|
| `> 0` | So viele Sekunden warten. Bei Timeout wird die Frage als `timeout` abgerechnet, der Agent entscheidet selbst |
| `0` oder negativ | **Vollautomatisch**. Fragen kommen nicht in die Warteschlange, es wird kein `asked`-Event gesendet, auf dem Bildschirm erscheint nichts, sofortige Abrechnung als `timeout` |
| Ewig warten | **Von der Kommandozeile aus nicht möglich**. Intern wird „ewig warten" unterstützt, aber `--timeout` ist ein float mit Default-Wert; keine Schreibweise erzeugt diesen Zustand. Die Obergrenze ist, eine sehr große Sekundenzahl anzugeben |

`--timeout 0` und `--timeout -1` sind vollständig äquivalent. Für Pipe-Betrieb, CI und unbeaufsichtigte
Läufe ist genau das gemeint.

Bleibt eine Frage unbeantwortet, ist das an das Modell zurückgegebene Tool-Ergebnis ein fester Text, vier
Varianten:

| Ergebnis | Text zurück ans Modell |
|---|---|
| Kontingent erschöpft | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| Von dir übersprungen | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| Frage ist leer | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**Ctrl-C hat an zwei Stellen völlig unterschiedliche Semantik.**

**Am Start-Prompt `> ` gedrückt** — das Programm beendet sich sofort und druckt `已取消`.

**Mitten im Run gedrückt** — unterbricht die aktuelle Runde und gibt dir eine Gelegenheit, etwas zu sagen:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Hier einfach Enter zu drücken bedeutet nur unterbrechen, nichts sagen und weitermachen. Gab es zu diesem
Zeitpunkt offene Fragen, kommt eine Zeile dazu:
`  (有 N 个提问还等着,打断不影响它们)`.

**Ein zweites Ctrl+C beendet wirklich**, und zwar als nicht abgefangenes `KeyboardInterrupt` — auf dem
Bildschirm steht dann ein Python-Traceback, kein sauberes Ende.

Die Unterbrechung ist kooperativ: Sie trennt an einer Nachrichtengrenze sauber ab und canceled keine Tasks
hart. Sie zählt **nicht als fehlgeschlagener Versuch** und verbraucht keine Retries. Beim Weiterlaufen
wird eine Erläuterung mitgegeben, die dem Modell sagt, dass ein `interrupted` bei in Flight befindlichen
Tool-Aufrufen eine normale Nebenwirkung der Unterbrechung ist und keine Störung der Umgebung.

Dieses eigene Ctrl-C-Verhalten wird nur installiert, wenn `sys.stdin.isatty()` gilt (`cli.py:918`). In
einer Pipe bleibt das Python-Standardverhalten, also Beenden beim ersten Mal. Der `once`-Pfad geht hier
nicht durch, deshalb beendet Ctrl-C auch bei `once` sofort.

### SIGHUP / SIGTERM {#sighup-sigterm}

Die Pfade `go` und `run` installieren Handler für `SIGHUP` und `SIGTERM`: Erst wird der **gerade in Flight
befindliche Schritt** noch in `manifest.json` geschrieben und als `killed-by-signal` markiert, dann wird
die Default-Aktion wiederhergestellt und tatsächlich gegangen.

Anlass: Wenn das Terminal abstürzt, schickt der Kernel SIGHUP, dessen Default-Aktion den Prozess sofort
beendet — `finally` läuft nicht, das Manifest wird nicht geschrieben, und die Abrechnung eines ganzen Runs
ist verloren. Läuft der Code nicht im Haupt-Thread des Betriebssystems oder unterstützt die Plattform das
nicht, wird stillschweigend übersprungen.

---

## Konfigurationsablauf beim ersten Start {#首次运行的配置流程}

Alle drei Einstiege `go`, `run` und `once` rufen zu Beginn `ensure_credentials()` auf (`cli.py:1213-1244`),
**zwei Hürden**.

### Erste Hürde: gibt es überhaupt Credentials {#第一道-有没有凭证}

Die Credentials werden nach Priorität gesucht. Findet sich weder `ANTHROPIC_API_KEY` noch
`ANTHROPIC_AUTH_TOKEN`, startet die interaktive Konfiguration; im nicht-interaktiven Fall (stdin ist kein
Terminal) wird nicht blockiert, sondern dieser Text gedruckt und beendet:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Zwei Stellen dieses Textes stimmen nicht mit der Implementierung überein: Das `flower setup` in Zeile 2
ist derzeit nicht erreichbar (siehe [`setup`](#setup)); Zeile 4 **sagt das Gegenteil des Codes** — flower
zieht den `env`-Block aus `~/.claude/settings.json` und `settings.local.json` tatsächlich als
**letzte Fallback-Stufe** heran, borgt sich daraus aber nur 9 Credential-Schlüssel und übernimmt keine
weiteren Einstellungen. Gedruckt wird diese Zeile in `env.py:192` (die Funktion `check_credentials()` ist
in `env.py:184` definiert), gelesen werden die beiden Dateien in `env.py:56-75` und `:109-111`;
festgehalten in [issue #13](https://github.com/ChenyuHeee/flower/issues/13).
**Maßgeblich ist der Code: es liest sie.** Die vollständige Suchreihenfolge und die 9 Schlüssel stehen in
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

- Frage 1 ist **Pflicht**. Bleibt sie leer, kommt die rote Zeile `没给 token,取消。` und die Konfiguration
  wird abgebrochen.
- Fragen 2 und 3 dürfen leer bleiben.
- Ist stdin kein Terminal, wird der gesamte Ablauf übersprungen, ohne zu blockieren.

### Welche Schlüssel geschrieben werden {#写出来的键}

| Deine Eingabe | Geschriebener Schlüssel |
|---|---|
| Token beginnt mit `sk-ant-` | `ANTHROPIC_API_KEY` |
| Anderes Token | `ANTHROPIC_AUTH_TOKEN` |
| Gateway-Adresse nicht leer | `ANTHROPIC_BASE_URL` |
| Modellname nicht leer | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` werden zusammen geschrieben |

Der Dateipfad ist `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, das Elternverzeichnis wird automatisch
angelegt. Geschrieben wird die **gesamte Datei neu**, Schlüssel mit leerem Wert werden ausgelassen, danach
`chmod 0600`, und anschließend wird sofort geladen — kein Neustart der Shell nötig.
Die erste Zeile ist fest ein Kommentar, der daran erinnert, die Datei nicht einzuchecken.

### Zweite Hürde: funktionieren die Credentials {#第二道-凭证能不能用}

Ist die Konfiguration vollständig, wird `- 验一下凭证…` gedruckt und **tatsächlich ein API-Aufruf**
abgesetzt.

Details der Probe: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, Default-Timeout 20 Sekunden, über
`urllib` aus der stdlib, ohne zusätzliche Abhängigkeit. Das Modell wird in der Reihenfolge
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022` gewählt. Gibt es einen
`ANTHROPIC_API_KEY`, wird der Header `x-api-key` genutzt, sonst
`authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` steht bewusst auf 16 statt auf 1: Gemessen passt bei Modellen mit erzwungener Denkkette nicht
einmal das Denken hinein, und der Server quält sich bis zu 30 Sekunden, bevor er antwortet; mit 16 sind es
nur 3,6 Sekunden.

Das Ergebnis der Probe wird in drei Kategorien behandelt, **die Unterschiede sind wichtig**:

| Ergebnis | Auslöser | Was flower tut |
|---|---|---|
| `auth` | HTTP 401 / 403, oder gar keine Credentials | Druckt `! 凭证被拒:<响应体前 160 字>`, startet die interaktive Neukonfiguration und prüft danach erneut. Nicht-interaktiv: Exit-Code 1 |
| `config` | HTTP 404, oder 400 mit `model` im Response-Body | Druckt `! 网关地址或模型名不对:<…>`, sonst wie oben |
| `net` | Keine Verbindung / Timeout / DNS-Fehler / TLS-Fehler / 5xx | Druckt `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **lässt dich nicht neu konfigurieren, sondern legt direkt los** |
| `ok` | Kleiner als 400, und alles Unklare wird ebenfalls durchgelassen | Fährt stillschweigend fort |

Der `net`-Fall ist Absicht: Ein kurzer Netzausfall soll dich nicht zwingen, das Token neu einzutippen, und
flower selbst hat einen Mechanismus, der bei Netzausfall pausiert und neu verbindet.
Wenn du „探针没打通" siehst, ignorier es einfach und lass laufen.

Eine Neukonfiguration gibt es **höchstens einmal**. Scheitert der zweite Versuch, wird beendet.

### Automatische Neukonfiguration nach einem Absturz {#跑挂了之后的自动重配}

Scheitert der Workflow, gleicht flower die Fehlermeldung des gescheiterten Schritts gegen einen regulären
Ausdruck ab (401, `invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). Bei einem
Treffer und wenn stdin ein Terminal ist, wird an Ort und Stelle `! 看起来是凭证不对:<前 120 字>` gedruckt
und die interaktive Konfiguration gestartet; danach:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

Anschließend wird in jedem Fall mit Exit-Code 1 beendet. Der `once`-Pfad hat diesen Abschnitt nicht.

---

## Exit-Codes {#退出码}

| Code | Wann |
|---|---|
| `0` | Normal durchgelaufen |
| `1` | Jeder aktive Abbruch. Die Meldung geht auf **stderr**, ohne Traceback. Liste siehe unten |
| `2` | argparse-Argumentfehler: unbekannter Schalter, fehlendes Positionsargument, `-p` mit einem Wert außerhalb der choices |
| `130` | Zweimal Ctrl+C hintereinander mitten im Run. Nicht abgefangenes `KeyboardInterrupt`, **mit Python-Traceback** |
| Vom Signal getötet | SIGHUP / SIGTERM: erst den in Flight befindlichen Schritt ins Manifest schreiben, dann per Default-Aktion gehen |

Alle Meldungen zu Exit-Code 1:

| Meldung | Wann |
|---|---|
| `已取消` | Ctrl-C oder Ctrl-D am Start-Prompt |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Frisches Verzeichnis + einfach Enter |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 Zeilen) | Nicht-interaktiv + keine Credentials |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Nicht-interaktiv + Probe ergibt `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Nicht-interaktiv + Probe ergibt `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` in einem Nicht-git-Verzeichnis |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Anliegen leer und das Verzeichnis hat kein Wake |
| `在步骤 '<步骤名>' 中止` | Ein Schritt im Workflow ist fehlgeschlagen und die Strategie ist Stopp |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, Doppelpunkt vergessen |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | Import des Zielmoduls fehlgeschlagen |
| `'<模块>' 里没有 '<属性>'` | Das Attribut findet sich nicht im Modul |

Am Ende (Pfade `go` / `run`) wird eine letzte Zeile gedruckt:

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
| `runs/sessions.db` | SQLite, vollständiges Transcript. Das ist die materielle Grundlage dafür, dass [Continuity](glossary.md#接续) überhaupt funktioniert |
| `runs/manifest.json` | Das [Run-Manifest](glossary.md#运行清单). JSON-Array, **prozessübergreifend akkumuliert**, alle Zahlen der Fallseiten lassen sich hier nachrechnen |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Wird per atomarem Ersetzen geschrieben |
| `runs/aside/` | Eigenständige Runtime der Oracle-Fragen, mit eigener `sessions.db` und `manifest.json`. **Kosten und Lineage vermischen sich nicht mit dem Haupt-Manifest** |
| `runs/workbench/` | Erscheint nur bei `-W` und wenn der Workflow keine eigene Workbench mitbringt (Pfade `run` / `once`) |

Die Felder jedes Eintrags in `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` ist die Kennung dieses Prozesses, Format `YYYYmmdd-HHMMSS-<6 位 hex>`. Die Schreibstrategie ist
**anhängen statt überschreiben**: Vor jedem Schreiben wird die Datei neu eingelesen und nach `run`
dedupliziert — Zeilen dieses Prozesses werden durch die neuesten ersetzt, Zeilen anderer Prozesse bleiben
unverändert stehen.

Schrittnamen haben vier Formen:

| Form | Wann |
|---|---|
| `<步骤名>` | Erster Versuch |
| `<步骤名>#retry<N>` | Normaler Retry |
| `<步骤名>#round<N>` | Verdict nicht bestanden, zurückgeschickt zum Weitermachen |
| `<步骤名>·判定#<N>` | Der Schritt des [Judge](glossary.md#判定者) |

Wird der Prozess von einem Signal getötet, wird auch der in Flight befindliche Schritt geschrieben, mit
`error` = `killed-by-signal`.

**Mehrere flower parallel im selben Verzeichnis**: `manifest.json` ist sicher (Neu-Einlesen + Merge nach
`run`), aber `lineage.json` wird komplett überschrieben, zwei Prozesse überschreiben also gegenseitig die
Lineage gleichnamiger Schritte. Für Parallelbetrieb ein anderes `-r` verwenden.

In `lineage.json` steht der absolute Pfad des Workspace. Passt er nicht, wird so getan, als gäbe es nichts,
und **stillschweigend** auf eine neue Session zurückgefallen, ohne Fehler — nach dem Kopieren des
Verzeichnisses ließe sich die alte `session_id` ohnehin nicht mehr finden.

### `.flower/` {#flower-目录}

| Pfad | Inhalt |
|---|---|
| `.flower/scripts/` | Skripte, die ein zweites Mal laufen sollen. In der ersten Zeile steht `# desc: 一句话`, dieser Satz taucht im Index auf |
| `.flower/artifacts/` | Lange Ergebnisse über 2000 Zeichen: Berichte, Daten, Logs. Im Dialog erscheint nur der Pfad |
| `.flower/notes/` | Schrittübergreifende Entscheidungsprotokolle |
| `.flower/spill/` | [Spill](glossary.md#落盘): Tool-Ergebnisse über 4000 Zeichen landen hier, im Kontext bleibt nur eine Zeiger-Zeile plus die ersten 400 Zeichen. Der Dateiname sind die ersten 16 Stellen des sha256 des Inhalts plus `.txt` |
| `.flower/INDEX.md` | Index der obigen Verzeichnisse, wird **in den System-Prompt des Koordinators injiziert** (Subagents erben ihn nicht) |

Der `go`-Pfad erzeugt fest folgende Dateien unter `notes/`:

| Datei | Inhalt |
|---|---|
| `notes/需求.md` | Der eingefrorene [Brief](glossary.md#需求确认书), vier Abschnitte: Ziel / Abnahmekriterien / Grenzen / Unbekanntes und Annahmen |
| `notes/目标.md` | Die eingefrorenen Ziele, zwei Abschnitte: Ziele / Verdict-Checkliste |
| `notes/问答记录.md` | Fortlaufendes Protokoll aller Fragen und Antworten (inklusive Status), auch dessen, was du von dir aus gesagt hast. **Geht nicht in den Kontext, dient nur der Ablage** |
| `notes/交接-<步骤名>.md` | Das beim Handoff geschriebene [Handoff-Dokument](glossary.md#交接书); die vorige Generation wandert nach `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | Die durch `--new` oder `/new` archivierten `lineage.json`, `需求.md`, `目标.md`. Es wird **verschoben**, nicht gelöscht |

Mit `--isolate` wandert die Workbench aus dem Repository heraus:
`<workspace>.parent/.flower-<workspace 名>/`. Ein worktree ist die private Kopie eines Agents, die
Workbench ist die agentübergreifend geteilte Schicht — Geteiltes gehört nicht in einen privaten Zaun.
Der dem Modell mitgeteilte Workbench-Pfad ist in diesem Fall absolut.
