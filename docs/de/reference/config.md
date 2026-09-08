# Konfiguration

flower hat kein Konfigurationsdateiformat, und auch kein Konfigurations-Unterkommando greift wirklich —
alle Konfiguration besteht aus **Umgebungsvariablen** plus **`.env`-Datei**, dazu ein Satz von
Policy-Objekten, die nur von der Python-Seite gesetzt werden können. Diese Seite fasst zusammen, was
über fünf Stellen verstreut liegt: jede Variable, in welcher Reihenfolge Credentials gesucht werden,
welche Syntax `.env` akzeptiert, was `setting_sources=[]` genau isoliert, was ein run auf der Platte
hinterlässt, was jede der drei Schichten des session store wegwirft, und wie bei Netzausfall gewartet
wird. Terminologie durchgängig nach dem [Glossar](glossary.md).

| Was du wissen willst | Wohin |
|---|---|
| Welche Umgebungsvariablen flower kennt | [Vollständige Tabelle der Umgebungsvariablen](#环境变量) |
| Woher mein token eigentlich kommt | [Credential-Suchpriorität](#凭证查找优先级) |
| Warum die Zeile in `.env` nicht greift | [`.env`-Parsing-Regeln](#env-解析) |
| Was auf eine andere Maschine mitmuss | [Der Preis der Portabilität](#可移植性) |
| Was in `.flower/` und `runs/` steckt | [Plattenlayout](#磁盘布局) |
| Welche Nachrichten nicht zurück ins Modell gehen | [Die drei Schichten des session store](#会话存储) |
| Worauf es bei Netzausfall wartet | [Resilienz bei Netzausfall](#韧性) |

## Vollständige Tabelle der Umgebungsvariablen {#环境变量}

Fünf Gruppen: Credentials und Endpunkte, die flower direkt liest; Modellauswahl; Pfadsuche;
Verhaltensschalter; und das, was flower **an** den Agent-Subprozess **schreibt**. Die letzte Gruppe
musst du nicht setzen — setzt du sie doch, wird sie überschrieben.

### Credentials und Endpunkte {#凭证变量}

| Variable | Wirkung | Default | Erforderlich | Herkunft |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Offizieller Anthropic-Key. Wenn vorhanden, wird mit dem Header `x-api-key` gesendet | keiner | **Eins von beiden mit `ANTHROPIC_AUTH_TOKEN` erforderlich** | `env.py:28`、`:146`、`:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Vom Gateway ausgestelltes token. Ohne `ANTHROPIC_API_KEY` wird `authorization: Bearer` verwendet | keiner | wie oben | `env.py:28`、`:147`、`:159-160` |
| `ANTHROPIC_BASE_URL` | Root-Adresse des API-Endpunkts. Drittanbieter-Gateways tragen hier ihre eigene Adresse ein, **ohne `/v1`** — die Sonde baut `<BASE_URL>/v1/messages` zusammen | `https://api.anthropic.com` | nein | `env.py:151`、`:162`、`:210`;`resilience.py:70` |

Ist keine der beiden gesetzt (oder beide leerer String), gibt `check_credentials()` jene vierzeilige
Fehlermeldung zurück, und `Runtime.__init__` wirft einen `RuntimeError` (`env.py:184-194`;
`runtime.py:156-158`).

### Modellauswahl {#模型变量}

flower liest davon nur drei für eigene Entscheidungen; der Rest wird eingeladen und an das SDK
durchgereicht.

| Variable | Wirkung | Default | Erforderlich | Herkunft |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | Name des Hauptmodells. Bestimmt zugleich den Default des [handoff](glossary.md#换代)-Fensters: enthält der Name `1m` oder nicht `haiku` → 1 Million, enthält er `haiku` → 200.000 | keiner (endseitig entschieden) | nein | `env.py:153`;`agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Modell-Mapping der opus-Stufe. Ist `ANTHROPIC_MODEL` leer, fällt die Fensterentscheidung darauf zurück | keiner | nein | `agent.py:78`;`cli.py:1384` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Modell-Mapping der sonnet-Stufe. flower liest es selbst nicht, lädt und leiht es nur | keiner | nein | `env.py:34`;`cli.py:1385` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Modell-Mapping der haiku-Stufe. **Die Credential-Sonde nimmt es zuerst** | Sonde fällt auf `ANTHROPIC_MODEL` zurück, dann auf `claude-3-5-haiku-20241022` | nein | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Welches Modell der [subagent](glossary.md#subagent) verwendet. flower interpretiert es nicht, es wird vom SDK verbraucht | keiner | nein | `env.py:35`;`.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Thinking-Stufe. Wie oben, wird nur geladen, nicht interpretiert | keiner | nein | `env.py:35` |

Trägt `flower setup` einen Modellnamen ein, werden `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`
und `ANTHROPIC_DEFAULT_SONNET_MODEL` **alle drei zusammen geschrieben** (`cli.py:1383-1385`).

### Pfade und Suche {#路径变量}

| Variable | Wirkung | Default | Erforderlich | Herkunft |
|---|---|---|---|---|
| `FLOWER_ENV` | Gibt den Pfad einer `.env`-Datei an, die **vor** allen anderen Dateien einsortiert wird | keiner | nein | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Bestimmt den Ort der globalen Credential-Datei `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | nein | `env.py:41-42` |
| `HOME` | Quelle von `Path.home()`, aus der die beiden Pfade `~/.config` und `~/.claude` abgeleitet werden | vom System | nein | `env.py:41`、`:67` |

### Verhaltensschalter {#行为开关}

Beide sind Fluchtwege: nicht setzen ist der Normalfall, setzen ist dafür da, flower eine Sache
weniger tun zu lassen. **Auf einen beliebigen nichtleeren Wert gesetzt greift es**, der Wert selbst
wird nicht geparst (`update.py:121`;`cli.py:1413`).

| Variable | Wirkung | Default | Erforderlich | Herkunft |
|---|---|---|---|---|
| `FLOWER_NO_UPDATE` | Schaltet die [automatische Aktualisierung](../getting-started/install.md#自动更新) ab. Ohne Setzung startet ein via pip / pipx / uv installiertes flower beim Start einen Hintergrund-Thread, der auf eine neue Version prüft und diese bei Fund installiert — **wirksam erst beim nächsten `flower`-Lauf**; höchstens alle 24 Stunden eine Prüfung, der Zeitstempel steht in `~/.config/flower/.update` | keiner (automatische Aktualisierung an) | nein | `update.py:32-33`、`:121-124` |
| `FLOWER_NO_PROBE` | Überspringt die [Credential-Sonde](cli.md#第二道-凭证能不能用) beim Start. Nicht-interaktiv (Pipe / CI / umgeleitetes stdin) wird ohnehin nicht sondiert, diese Variable ist der Ausweg für das interaktive Terminal | keiner (interaktiv wird sondiert) | nein | `cli.py:1413` |

Ein aus dem git-Quellcode laufendes flower ist von der automatischen Aktualisierung nicht betroffen,
`FLOWER_NO_UPDATE` ist für es ein no-op — der Aktualisierungsschritt erkennt ein `.git` im Repository
und gibt direkt `None` zurück (`update.py:83-87`).

### Was flower an den Agent-Subprozess schreibt {#写出的变量}

Diese drei werden von `CompactPolicy.env()` erzeugt und dann in `ClaudeAgentOptions.env` gesteckt
(`agent.py:48-58`、`:241-245`), sie steuern den in die Harness eingebauten [compact](glossary.md#压缩).
**Sie in der Shell zu setzen ist bedeutungslos** — was wirklich greift, ist die Fassung, die flower an
den Subprozess übergibt.

| Variable | Wirkung | Default | Erforderlich | Herkunft |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` schaltet den automatischen compact ab. Bei aktivem [handoff](glossary.md#换代) **erzwungen geschrieben** — laufen beide Mechanismen zugleich, lässt sich nicht mehr unterscheiden, wer den Kontextrückfall verursacht hat | handoff standardmäßig an, also faktisch konstant `1` | nein (flower schreibt) | `agent.py:51`;`runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` schaltet auch `/compact` mit ab. Nur `CompactPolicy(mode="off")` schreibt es | wird nicht geschrieben | nein (flower schreibt) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Fenster des automatischen compact (tokens). Nur `CompactPolicy(window=N)` schreibt es | wird nicht geschrieben | nein (flower schreibt) | `agent.py:56-57` |

### Was der Container-Wrapper liest {#容器变量}

Diese beiden liest nicht flower selbst, sondern der Shell-Wrapper `docker/flowerbox`. Vollständige
Verwendung siehe [Deployment](deploy.md).

| Variable | Wirkung | Default | Erforderlich | Herkunft |
|---|---|---|---|---|
| `FLOWER_HOME` | Wo die für `--env-file` benötigte `.env` gesucht wird | das übergeordnete Verzeichnis des Skripts selbst | nein | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Welches Image verwendet wird | `flower-box` | nein | `docker/flowerbox:13` |

**Die Schlüssel in `.env` sind nicht auf die oben genannten beschränkt.** Der Parser lädt **alle**
`k=v`-Zeilen in `os.environ`, ohne Whitelist (`env.py:30`、`:102-107`). Die aus den 9 oben genannten
Credential-Schlüsseln bestehende Menge `KNOWN` wirkt nur an zwei Stellen: als Whitelist beim Leihen der
`~/.claude`-Konfiguration (`env.py:72`) und als Feldumfang, wenn `-v` beim Start `describe()` ausgibt
(`env.py:205`).

## Credential-Suchpriorität {#凭证查找优先级}

Wird `load_dotenv()` ohne Pfad aufgerufen, liest es **alle vorhandenen** Dateien in der folgenden
Reihenfolge nacheinander ein (`env.py:45-53`、`:78-112`):

1. **Prozess-Umgebungsvariablen** — immer höchste Priorität. Kein `.env` überschreibt einen bereits exportierten Wert. (`env.py:91`)
2. **Die von `$FLOWER_ENV` referenzierte Datei** — nur vorhanden, wenn gesetzt. (`env.py:48-49`)
3. **`$PWD/.env`** — das aktuelle Arbeitsverzeichnis. In welches Projekt du auch `cd`st, das dortige wird genommen. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — die globale Stelle pro Benutzer, das schreibt `flower setup`. (`env.py:51`、`:39-42`)
5. **`.env` in der Wurzel des Quellcode-Repositories** — drei Ebenen über `flower/core/env.py`. Nur vorhanden, wenn aus dem Quellcode gelaufen; ein via pip / pipx / uv installiertes flower liegt in site-packages und hat diesen Eintrag nicht. (`env.py:52`)
6. **`~/.claude/settings.json`, dann der `env`-Block von `~/.claude/settings.local.json`** — der letzte Rückfall, **nimmt nur die 9 Credential-Schlüssel**. (`env.py:56-75`、`:109-111`)

**Welche Datei gewinnt**: Punkt 3 (Projekt-`.env`) gewinnt gegen Punkt 4 (globale `.env`), Punkt 4
gewinnt gegen Punkt 5 (Repository-Wurzel-`.env`), alle drei gewinnen gegen Punkt 6 (die Konfiguration
von Claude Code), und alle verlieren gegen Punkt 1 (Prozess-Umgebung).

Umgesetzt ist das als „**ein Schlüssel mit bereits vorhandenem Wert wird nicht überschrieben**"
(`env.py:90-93`): die weiter vorne stehenden besetzen die Schlüssel zuerst, die späteren füllen nur
Lücken. Die Priorität wird also **pro Schlüssel gerechnet, nicht pro Datei** — steht in der
Projekt-`.env` nur `ANTHROPIC_BASE_URL`, kann das token trotzdem aus der globalen Fassung kommen. Der
beim ersten Auftreten eines gleichnamigen Schlüssels gesetzte Wert gilt für immer.

Punkt 6 ist nur bei der **automatischen Suche** aktiv. Ein explizit angegebener Pfad
(`load_dotenv("/path/to/.env")`) liest nur diese eine Datei und geht durch keinen Rückfall
(`env.py:86-87`、`:109`).

### Punkt 6: das token von Claude Code leihen {#借用}

Nacheinander werden `~/.claude/settings.json` und `~/.claude/settings.local.json` gelesen, das dict
`data["env"]` genommen und daraus diese 9 Schlüssel herausgepickt (`env.py:31-36`、`:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

Existiert die Datei nicht, ist sie nicht lesbar oder kein gültiges JSON (`OSError` / `ValueError`),
wird ein leeres dict zurückgegeben und weitergemacht — **ein fehlgeschlagener Rückfall soll diesen run
nicht mitreißen** (`env.py:62-63`、`:66-69`).

Die Haltung im Code lautet: geliehen wird nur „wo das token zu finden ist", nichts anderes aus
settings.json (Berechtigungsregeln, hooks, Modelleinstellungen) wird übernommen, deshalb verletzt das
das Portabilitätsversprechen von `setting_sources=[]` nicht (`env.py:17-19`、`:59-61`). `install.sh:77`
bewirbt es als Feature: wer Claude Code lokal eingerichtet hat, bekommt nicht einmal einen
Konfigurationsdialog zu sehen.

!!! warning "Die Fehlermeldung im Produkt widerspricht dem tatsächlichen Verhalten"
    Werden gar keine Credentials gefunden, lautet die letzte Zeile des von flower ausgegebenen Fehlers:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, jene Zeile bei `:192`; dieselbe Aussage taucht auch in `.env.example:2`、
    `env.py:3-4`、`agent.py:10-12` auf.) **Maßgeblich ist der Code: es liest.** `env.py:56-75` plus
    `:109-111` lesen jene beiden Dateien ausdrücklich, und `install.sh:77` bewirbt es sogar als
    Verkaufsargument. Diese Meldung ist derzeit irreführend — auf einer Maschine, auf der Claude Code
    eingerichtet wurde, kommt dein token sehr wahrscheinlich genau von dort.

## `.env`-Parsing-Regeln {#env-解析}

Die Parsing-Regeln sind kurz genug zum Auswendiglernen (`env.py:95-107`, 13 Zeilen): jede Zeile
`strip`en, leere Zeilen überspringen, mit `#` beginnende Zeilen überspringen, Zeilen ohne `=`
überspringen; die restlichen am **ersten** `=` in key und value schneiden, beide Seiten je `strip`en,
und value läuft nochmals durch `.strip("'\"")` — führende und schließende einfache und doppelte
Anführungszeichen werden immer abgestreift, **ohne dass sie paarig sein müssen**.

**Diese Schreibweisen werden akzeptiert**:

| Schreibweise | Ergebnis |
|---|---|
| `KEY=VALUE` | normal |
| `KEY = VALUE` | normal — die Leerzeichen um das Gleichheitszeichen werden gestrippt |
| `KEY="VALUE"` / `KEY='VALUE'` | normal — die führenden/schließenden Anführungszeichen werden abgestreift |
| `KEY=a=b` | value ist `a=b` — am ersten `=` geschnitten, das folgende Gleichheitszeichen bleibt im Wert |
| `# 注释` | ganze Zeile übersprungen |
| Leere Zeile | übersprungen |

**Diese werden nicht akzeptiert.** Sie schreiben, gibt keinen Fehler, ergibt nur stillschweigend einen
unerwarteten Wert:

| Schreibweise | Tatsächliches Ergebnis |
|---|---|
| `export KEY=VALUE` | key wird zu `export KEY`, `KEY` selbst hat weiterhin keinen Wert |
| `KEY=value # 说明` | value ist `value # 说明` — Kommentare am Zeilenende werden nicht abgestreift |
| `KEY=$OTHER` | Literal `$OTHER`, keine Variablensubstitution |
| Mehrzeiliger Wert (mit Anführungszeichen über Zeilen) | zeilenweise verarbeitet, die zweite Zeile enthält kein `=` und wird als ganze Zeile übersprungen |

**Ein leerer Wert besetzt den Schlüssel.** Taucht `ANTHROPIC_AUTH_TOKEN=` in einer höherpriorisierten
Datei auf, führt `take()` `os.environ["ANTHROPIC_AUTH_TOKEN"] = ""` aus, sodass die späteren Dateien
wegen „Schlüssel existiert bereits" nicht nachfüllen können (`env.py:90-93`); und `check_credentials()`
prüft auf Wahrheitswert, ein leerer String zählt trotzdem als nicht konfiguriert (`env.py:186`).
**Das Ergebnis: weder Credential noch Rückfall.** Willst du einen Schlüssel nicht, lösche die ganze
Zeile, lass keinen leeren stehen.

## Der Preis der Portabilität {#可移植性}

Jene eine Zeile in `build_options()` ist der ganze Mechanismus (`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` ist der Default von `Runtime`, und **auf der Kommandozeile gibt es keinen Schalter, um
es abzuschalten** — abschalten geht nur über die Python-API mit `Runtime(portable=False)`, was zu
`["project"]` wird, also das `.claude/` des Projekts liest.

### Was isoliert wird {#被隔绝的东西}

| Was isoliert wird | Folge |
|---|---|
| Die Einstellungen von `~/.claude/` der Host-Maschine | Berechtigungsregeln, hooks und Modelleinstellungen dort greifen alle nicht. **Credentials sind die einzige Ausnahme**, siehe [Leihen](#借用) |
| Das `.claude/` des Projekts | wie oben, wird nur bei `portable=False` gelesen |

Domänenfähigkeiten laufen nicht über diesen Weg — sie werden mit dem Repository ausgeliefert und über
`plugins=[{"type": "local", "path": PLUGIN_DIR}]` geladen (`agent.py:26`、`:210-212`), siehe
[Deployment](deploy.md). Domänenanweisungen werden dagegen **angehängt** hinter dem nativen
System-Prompt von Claude Code, nicht ersetzt (`agent.py:198-202`), sodass Spezialisierung nicht auf
Kosten allgemeiner Fähigkeit geht.

### Was auf eine andere Maschine mitmuss {#换台机器要带什么}

- **Credentials: eine Datei**. `~/.config/flower/.env` einfach hinüberkopieren, oder auf der neuen
  Maschine einmal neu einrichten. Ohne läuft gar nichts — nichts wird automatisch geerbt.
- **Continuity-Zustand: das ganze Verzeichnis**. `runs/` (session store, manifest, lineage) und
  `.flower/` (workbench).
- **Aber die Pfade müssen übereinstimmen**. In `lineage.json` ist der absolute Pfad des Arbeitsbereichs
  gespeichert; stimmt er nicht überein, wird es als nicht vorhanden behandelt und still auf eine neue
  session zurückgefallen, **ohne Fehler** (`lineage.py:65-66`). Der Grund: der `project_key` des SDK
  wird aus dem Pfad des Arbeitsbereichs abgeleitet (`/`、`_`、`.` alle durch `-` ersetzt,
  `runtime.py:40-41`), verschiebt sich das Verzeichnis, ist die alte `session_id` nicht mehr auffindbar.

## Plattenlayout {#磁盘布局}

Ein flower-run schreibt zwei Bäume: `<run_dir>/` für Buchführung und sessions, `<workspace>/.flower/`
für die [workbench](glossary.md#工作台). Beide liegen standardmäßig unter dem aktuellen Verzeichnis,
aber **ihre Basen sind verschieden**.

!!! warning "`runs/` folgt dem aktuellen Verzeichnis, nicht `-w`"
    `-r/--run-dir` ist standardmäßig `"runs"`, und `Runtime` macht damit `Path(run_dir).resolve()`
    (`runtime.py:93-94`) — relativ zum **aktuellen Arbeitsverzeichnis**, nicht relativ zu dem mit `-w`
    angegebenen Arbeitsbereich. Läuft man unter `~` `flower -w /path/to/proj`, landet der session store
    in `~/runs/`, nicht im Projekt.

### `<run_dir>/` — standardmäßig `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite,全量 transcript(含每个 subagent 自己那条)
  manifest.json      运行清单:每一步的 session_id / 花费 / 重试 / 失败原因,跨进程累积
  lineage.json       血缘:步骤名 → session_id,同一个目录再跑一次靠它接上
  aside/             旁路问答的独立 Runtime,自己的 sessions.db + manifest.json
  workbench/         仅当走 run / once 路径且给了 -W
```

| Pfad | Inhalt | Herkunft |
|---|---|---|
| `runs/sessions.db` | Vollständige transcript. Geschrieben von `PruningSessionStore`, die drei Schichten der Policy siehe [unten](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | JSON-Array, das **prozessübergreifend akkumulierte** [run manifest](glossary.md#运行清单). Felder siehe Tabelle unten | `runtime.py:532-533`、`:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Zuerst `.tmp` schreiben, dann `replace`, atomarer Austausch | `lineage.py:31`、`:87-97` |
| `runs/aside/` | Separate Runtime des [oracle](glossary.md#旁路顾问). **Kosten und lineage mischen sich nicht ins Haupt-manifest** | `cli.py:741-743` |
| `runs/workbench/` | Default-Ort der workbench von `Runtime(workbench=True)`, außerhalb des Arbeitsbereichs. Der `go`-Pfad nutzt ihn nicht | `runtime.py:148-151` |

Jede Zeile in `manifest.json` ist `asdict(StepResult)` plus zwei Patches (`runtime.py:44-71`、
`:579-582`):

| Feld | Typ | Bedeutung |
|---|---|---|
| `step` | `str` | Schrittname. Vier Formen: `<名>`、`<名>#round<N>`(zurückgeworfen zur Neubearbeitung)、`<名>#retry<N>`(gewöhnlicher retry)、`<名>·判定#<N>`([judge](glossary.md#判定者)) |
| `session_id` | `str \| None` | die zuletzt lebende [session](glossary.md#会话) dieses Schritts |
| `ok` | `bool` | ob erfolgreich |
| `cost_usd` | `float` | wie viel dieser Schritt gekostet hat |
| `num_turns` | `int` | wie viele Runden gelaufen sind |
| `text` | `str` | die abschließende Antwort dieses Schritts |
| `error` | `str \| None` | Grund des Fehlschlags. Wenn von SIGHUP / SIGTERM getötet, ist es `killed-by-signal`(`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | epoch-Sekunden |
| `attempts` | `int` | tatsächliche Anzahl der Versuche. `>1` bedeutet, es wurde erneut versucht |
| `errors` | `list[str]` | Gründe aller bisherigen Fehlschläge. **Nur hier, das Modell sieht es nicht** |
| `resumed` | `bool` | ob per resume von der Unterbrechungsstelle fortgesetzt statt von vorn |
| `retired` | `list[str]` | die beim [handoff](glossary.md#换代) dieses Schritts verbrannten session_id, in Reihenfolge |
| `context` | `int` | tatsächliche Kontextgröße, die der [main thread](glossary.md#主线程) in der letzten Runde gesehen hat |
| `duration_s` | `float` | manuell nachgetragen — es ist eine `@property`, `asdict()` erfasst es nicht |
| `run` | `str` | Marke dieses Prozesses `YYYYmmdd-HHMMSS-<6 位 hex>`. **Muss pro Instanz eindeutig sein** |

Die Schreibstrategie ist **anhängen, nicht überschreiben**: bei jedem spill wird die Datei zuerst neu
eingelesen, die Zeilen mit dem eigenen `run` durch die aktuellsten ersetzt, die Zeilen anderer bleiben
unverändert (`runtime.py:564-586`). Laufen also mehrere flower parallel im selben Verzeichnis,
überschreiben sich die Bücher nicht gegenseitig.

Was in `runs/` liegt, sind reine Daten, jederzeit offline mit sqlite3 oder
[`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py)
durchsehbar.

### `<workspace>/.flower/` — die workbench {#工作台目录}

```text
.flower/
  INDEX.md      自动生成的索引,注入主 agent 的 system prompt
  scripts/      要跑第二次的脚本。首行 `# desc: 一句话` 会出现在索引里
  artifacts/    超过 2000 字符的长产出:报告、数据、日志
  notes/        跨步骤的决策记录
  spill/        落盘的大工具结果,文件名 = 内容 sha256 前 16 位 + `.txt`
```

Die drei Unterverzeichnisse plus Index werden von `Workbench` angelegt (`workbench.py:73-92`).
`INDEX.md` läuft über den sessioneigenen `system_prompt.append`, **der subagent erbt es nicht** — daher
muss die Regel „lange Ausgaben in `artifacts/` schreiben" vom [coordinator](glossary.md#协调者) im
[task brief](glossary.md#任务书) weitergegeben werden, das ist der einzige Kanal.

Der `go`-Pfad erzeugt fest diese unter `notes/`:

| Datei | Inhalt | Herkunft |
|---|---|---|
| `notes/需求.md` | Der eingefrorene [brief](glossary.md#需求确认书), vier Abschnitte: Ziel / Abnahmekriterien / Grenzen / Unbekanntes und Annahmen | `brief.py:44-45`;`clarify.py:105` |
| `notes/目标.md` | Zwei eingefrorene Abschnitte: Ziel / Prüfliste des verdict | `workflow/goal.py:124` |
| `notes/问答记录.md` | Angehängte Aufzeichnung aller Fragen und Antworten, inklusive der Inbox-Einträge, die „der Mensch aktiv gesagt" hat. **Kommt nicht in den Kontext, dient nur als Archiv** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | Das [handoff document](glossary.md#交接书). Die Vorgängergeneration wird in `notes/archive/交接/<步骤名>-<时间戳>.md` abgelegt | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | Von `--new` / `/new` archivierte `lineage.json` + `需求.md` + `目标.md`(**verschoben, nicht gelöscht**) | `lineage.py:100-117` |

**Bei `--isolate` wird die workbench nach außerhalb des Repositories verschoben**: nach
`<übergeordnetes Verzeichnis des workspace>/.flower-<workspace-Name>/` (`starter.py:47-55`). Ein
worktree ist eine private Kopie jedes Agents, die workbench ist die agent-übergreifende gemeinsame
Schicht; Gemeinsames darf nicht in einen privaten Zaun. In diesem Fall ist der ans Modell gegebene Pfad
ein absoluter Pfad (`workbench.py:69-71`、`:142-145`).

**`spill/` hat zwei Schreiber mit unterschiedlichem Landepunkt-Algorithmus**:

| Wer schreibt | Wann | Wohin | Schwelle |
|---|---|---|---|
| `spill_guard`(`PostToolUse` hook) | **bevor** das Werkzeugergebnis ins Modell geht | `<workbench root>/spill/`(`guard.py:130`) | `spill_threshold`,default 4000 Zeichen |
| `TrimPolicy`(bei `load`) | vor dem resume beim Wiederholen der Historie | `<workspace>/.flower/spill/` — ein fixer String relativ zum Arbeitsbereich(`trim.py:49`、`:303`) | `min_chars`,default 2000 Zeichen |

Beim Default-Layout ist das dasselbe Verzeichnis. Wird die workbench aber verschoben (`-W` lässt sie in
`runs/workbench/` landen, oder `--isolate` außerhalb des Repositories), trennen sich beide — die Fassung
von `TrimPolicy` liegt immer im Arbeitsbereich, weil das `Read` des Agents sie erreichen können muss.

Was `spill_guard` einsetzt, ist nicht eine Zeile, sondern eine Zeile Zeiger plus die **ersten 400
Zeichen** (`guard.py:132-140`). Der Aufruf zum Lesen der spill-Datei selbst wird durchgelassen, sonst
wäre „bei Bedarf mit Read den Volltext lesen" leeres Gerede — beim Zurücklesen überschreitet es wieder
die Schwelle, wird wieder spilled, Endlosschleife (`guard.py:155-170`).

### Tabellenstruktur von `sessions.db` {#sessions-db}

Drei Tabellen, die CREATE-Statements in `stores/sqlite.py:27-51`:

```sql
CREATE TABLE entries (
    store_key TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    uid       TEXT,
    payload   TEXT NOT NULL,
    PRIMARY KEY (store_key, seq)
);
CREATE UNIQUE INDEX entries_uid
    ON entries(store_key, uid) WHERE uid IS NOT NULL;
CREATE TABLE meta (
    store_key TEXT PRIMARY KEY,
    mtime     INTEGER NOT NULL,
    next_seq  INTEGER NOT NULL
);
CREATE TABLE summaries (
    project_key TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    mtime       INTEGER NOT NULL,
    data        TEXT NOT NULL,
    PRIMARY KEY (project_key, session_id)
);
```

| Tabelle | Was eine Zeile ist | Kernpunkt |
|---|---|---|
| `entries` | ein Eintrag der transcript, `payload` ist das rohe JSON | `uid` ist gerade die `uuid` des Eintrags, dient als **Idempotenzschlüssel**: eine fehlgeschlagene Charge wird bis zu 3-mal wiederholt, das Wiederholen darf keine doppelten Zeilen erzeugen. Einträge ohne `uuid`(Titel, Tags, Modusmarken) werden nicht dedupliziert, daher trägt der unique index das `WHERE uid IS NOT NULL` |
| `meta` | der Cursor einer session | `next_seq` ist die nächste Sequenznummer, `mtime` ist ein Millisekunden-Zeitstempel und **strikt monoton**(`sqlite.py:72-79`)— `list_sessions` und summary teilen sich diese Uhr, nicht-monoton lässt die Alt/Neu-Beurteilung des SDK den falschen Schnellpfad nehmen |
| `summaries` | eine Zusammenfassungs-Sidecar des main thread | **nur die Haupt-transcript nimmt teil**, die des subagent nicht(`sqlite.py:122-123`) |

Der Aufbau von `store_key`(`sqlite.py:54-58`): `<project_key>/<session_id>`, ein subagent hängt noch
ein Stück `subpath` an. `project_key` wird vom SDK aus dem Pfad des Arbeitsbereichs abgeleitet — `/`、
`_`、`.` alle durch `-` ersetzt.

Ein Blick auf eine echte Stichprobe
([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

Jene Fassung hat 956 `entries`, 10 `meta`, 4 `summaries` — von 10 sessions sind 4 Haupt-transcripts,
6 sind subagents, und `summaries` entspricht genau der Anzahl der Haupt-transcripts.

## Die drei Schichten des session store {#会话存储}

!!! note "Die drei Schichten sind eine Vererbungskette, keine wählbare Kombination"
    `PruningSessionStore` erbt von `TrimmingSessionStore`, das von `SqliteSessionStore` erbt.
    `Runtime` konstruiert **immer** die äußerste (`runtime.py:109-112`), in den Konstruktorparametern
    gibt es keinen Einstieg zum Backend-Wechsel. Der Weg, „eine Schicht abzuschalten", ist, das
    `enabled` ihres Policy-Objekts auf `False` zu setzen, nicht die Klasse zu wechseln.

`append`(Schreiben) ist immer vollständiger spill, ohne ein einziges Zeichen zu ändern. Die drei
Schichten beeinflussen nur `load`(die Fassung, die zurück ins Modell gelesen wird). Die tatsächliche
Reihenfolge von `load` ist:

```text
SqliteSessionStore.load     从 entries 表按 seq 读出全部
  → TrimmingSessionStore.expire()   时效性 Bash 结果 → 换成"已过期"
  → TrimmingSessionStore.trim()     旧的大 tool_result → 落盘 + 换成指针
    → PruningSessionStore.prune()   合成错误消息 / 旧的被拒调用 → 整条摘掉并重接链
```

| Schicht | Klasse | Was weggeworfen wird | Kriterium |
|---|---|---|---|
| 1 | `SqliteSessionStore` | wirft nichts weg | —— |
| 2 | `TrimmingSessionStore` | Rumpf großer Werkzeugergebnisse, abgelaufene Ergebnisse von ephemeral commands | Größe + Zeitlichkeit |
| 3 | `PruningSessionStore` | Abtrennungs-Rückstände, alte abgelehnte Aufrufe | ob es ein Fehler ist |

Schicht 2 ist [trim](glossary.md#裁剪), Schicht 3 ist [prune](glossary.md#剪除) — **trim wirft nach
Größe und Wert weg, prune wirft nach „ist es ein Fehler" weg**, nicht verwechseln. Vollständige
Signaturen siehe [Python API](api.md).

### `SqliteSessionStore` — das Fundament {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

Eine SQLite-Implementierung ohne externe Abhängigkeiten. Um auf Postgres / S3 / Redis zu wechseln,
implementiere einfach dasselbe Protokoll; das SDK bringt eine Konsistenz-Testsuite
`claude_agent_sdk.testing.session_store_conformance` mit, mit der sich das direkt verifizieren lässt
(`sqlite.py:1-8`).

Neben den Protokollmethoden gibt es drei **synchrone** Abfragen für flower selbst:

| Methode | Rückgabe | Zweck |
|---|---|---|
| `projects()` | `list[str]` | die tatsächlich in der Datenbank vorhandenen `project_key`. Das SDK leitet ihn aus cwd ab, vor einer Abfrage damit bestätigen, nicht raten |
| `has_session(project_key, session_id)` | `bool` | fragt nur eine Zeile aus `meta` ab, liest kein payload. Vor dem Start der [continuity](glossary.md#接续) zuerst abfragen — ein resume auf eine nicht existierende session fliegt erst auf, nachdem der Subprozess gestartet ist, dann sind Geld und Zeit schon ausgegeben |
| `last_context(project_key, session_id, scan=60)` | `int` | wie großen Kontext diese session in der letzten Runde gesehen hat. Scannt nur die letzten 60 Einträge rückwärts. `input_tokens` plus zwei `cache_*` zählen alle — schaut man nur auf ersteres, ist es bei cache-Treffern nahe 0 und unterschätzt schwer |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Zwei orthogonale Regeln. `TrimPolicy` regelt die **Größe**:

| Parameter | Typ | Default | Semantik |
|---|---|---|---|
| `keep_recent` | `int` | `20` | die letzten N `tool_result` behalten den Originaltext — der gerade benutzte Kontext soll nicht getrimmt werden |
| `min_chars` | `int` | `2000` | kürzer als dies wird nicht getrimmt. In einen Zeiger umzusetzen kostet eher mehr token |
| `spill_dirname` | `str` | `".flower/spill"` | Archivverzeichnis, **relativ zu workspace**. Muss im Arbeitsbereich liegen, sonst erreicht das `Read` des Agents es nicht |
| `enabled` | `bool` | `True` | bei `Runtime(trim=False)`(default) ist es `False` |

Der getrimmte Rumpf wird als `<sha256 erste 16 Stellen>.txt` geschrieben, die ursprüngliche Stelle
durch `[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` ersetzt (`trim.py:54-57`、
`:308-317`).

`EphemeralPolicy` regelt die **Zeitlichkeit**: Ergebnisse wie `git status`, `ls`, `ps` sind sehr kurz,
nach Größe kämen sie nie zum Trimmen dran, aber ihre Korrektheit verfällt mit der Zeit — jener
`git status` von vor 20 Runden ist nicht „nutzlos", er **führt in die Irre**.

| Parameter | Typ | Default | Semantik |
|---|---|---|---|
| `enabled` | `bool` | `True` | aus `Runtime(ephemeral=…)` umgewandelt, **standardmäßig an** |
| `keep_recent` | `int` | `6` | die letzten N Einträge behalten den Originaltext. Viel kleiner als die 20 von `TrimPolicy` — das „letzte" Fenster für solche Dinge ist von Haus aus kurz |
| `max_chars` | `int` | `2000` | überschreitet es dies, wird es an `TrimPolicy` zum spill/Archivieren übergeben, geht nicht diesen Weg |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Ersatztext |

Wirkt nur auf die Ergebnisse des **Bash**-Werkzeugs, und der Befehl muss auf `EPHEMERAL_CMD` passen.
`Read` gehört nicht dazu: Dateiinhalte verfälschen sich nicht durch Zeitablauf bis zur Irreführung, und
sie könnten gerade die Grundlage der Schlussfolgerung des Modells sein (`trim.py:153-160`). Abgelaufene
Inhalte werden **nicht gespilled** — einen abgelaufenen `git status` zu archivieren hat keinen Sinn, ein
erneuter Lauf beschafft ihn wieder.

Die Beurteilungsfunktion ist `is_ephemeral(cmd)`, und sie **ist zugleich die dem coordinator
zurückgegebene Berechtigungsliste**: `delegate_guard(allow_glance=True)` verwendet dieselbe Funktion
(`trim.py:63-68`、`:128-150`). Die beiden Mengen müssen immer gleich sein — durchgelassen, aber nicht
getrimmt, besetzt ein abgelaufener `git status` den Kontext für immer; getrimmt, aber nicht
durchgelassen, schickt der coordinator für ein `ls` einen subagent los, 4,3k Startkosten für ein paar
Dutzend Zeichen. Eine Zeile zur Whitelist hinzuzufügen heißt, beide Sätze zugleich zu sagen.

**Wann welchen verwenden**:

- Willst du nur, dass Abtrennungs-Rückstände nicht in den Kontext kommen → nichts tun, `Runtime` ist
  standardmäßig `PruningSessionStore`. `trim=False` trimmt nur große Ergebnisse nicht, das prune läuft
  weiter.
- Lange Läufe, sehr große Werkzeugausgabe → `trim=True`. Das CLI des `go`-Pfads hat es standardmäßig an,
  mit `--no-trim` gegenteilig abschalten.
- Der [coordinator](glossary.md#协调者) hat `glance=True` an → `ephemeral` muss an bleiben, Begründung
  siehe voriger Absatz.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Parameter | Typ | Default | Semantik |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | entfernt synthetische Nachrichten mit `isApiErrorMessage=true` oder `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | beim `tool_result` von `[Request interrupted …]` **den Rumpf ersetzen, nicht den Block entfernen** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Ersatztext des vorigen |
| `heal_orphans` | `bool` | `True` | einem verwaisten Aufruf mit „`tool_use` aber ohne `tool_result`" ein synthetisches Ergebnis **nachtragen** |
| `orphan_text` | `str` | `"[这一步被打断了,没有结果。需要的话重做。]"` | der Rumpf des nachgetragenen `tool_result` |
| `keep_denials` | `int` | `1` | die letzten N vom permission hook abgelehnten Werkzeugaufrufe behalten, frühere **samt Aufruf und Ergebnis** entfernen |

`keep_denials` ist der einzige Runtime-Konstruktorparameter, der bis in diese Schicht durchgereicht
wird (`Runtime(keep_denials=N)`). Der Grund für Default 1 statt 0: die neueste Ablehnung ist ein
gültiges Signal und verhindert, dass das Modell in derselben Runde denselben abgefangenen Befehl
wiederholt versucht. **Nicht hochdrehen** — ein abgelehnter Aufruf wurde nie ausgeführt, im Ergebnis
steckt keinerlei Information, gemessen belegt einer 273 Zeichen (93 Zeichen Ablehnungssatz plus 180
Zeichen des toten Befehlsoriginals), und er **führt in die Irre**: gemessen liest der coordinator ein
paar „Bash nicht direkt verwenden", und danach versucht er selbst den durchgelassenen `git status` nicht
mehr, sondern sagt direkt „Bash ist eingeschränkt, schick einen agent zum Nachsehen"
(`prune.py:135-148`).

`heal_orphans` heilt das **jedes resume nach einer Abtrennung mit 400**: die Abtrennung reißt an der
Nachrichtengrenze ab, hinter dem damals fliegenden `tool_use` könnte gar kein `tool_result` stehen, aber
die API verlangt beide paarig. Diese kaputte Historie in der transcript verschwindet nicht von selbst,
sodass danach jedes resume von ihr zurückgeworfen wird. Das Nachtragen geschieht, indem nach jener
verwaisten assistant-Nachricht ein `user`-Eintrag eingefügt wird, der die Ergebnisse aller Waisen in
diesem Eintrag auf einmal nachträgt, und dann die ursprünglich auf jene assistant-Nachricht zeigende
`parentUuid` auf den nachgetragenen Eintrag umgelenkt wird (`prune.py:95-147`). **Nachtragen, nicht
löschen**: eine Waise zu löschen erfordert das Neuverketten der Eltern-Kind-Kette, dieselbe
assistant-Nachricht könnte noch normale Blöcke, Text und thinking enthalten, leicht mitreißt es die
(`prune.py:195-204`).

Drei strukturelle rote Linien, verletzt liefert die API direkt einen Fehler:

1. **Der `tool_result`-Block selbst muss da sein**, nur `content` darf ersetzt werden. Fehlt einer, ist
   das „Missing Tool Result Block"(`trim.py:20-22`;`prune.py:79-92`).
2. **`isCompactSummary` / `isMeta`-Einträge dürfen nicht angetastet werden** — das ist die einzige
   Existenzform jenes weggecompacteten Stücks Historie(`trim.py:179-181`).
3. **Entfernt man einen Eintrag, muss man seine Kinder an seinen Elternteil hängen**. Die transcript ist
   eine einfache `parentUuid`-Kette, die Harness geht von den Blättern zurück, wo die Kette reißt, ist
   die davorliegende Historie ganz verloren(`prune.py:95-122`). Deshalb muss `relink()` die vollständige
   Liste **inklusive** des zu entfernenden Eintrags bekommen, das Filtern macht es selbst.

**In SQLite wird am Original kein Zeichen geändert** — die drei Schichten beeinflussen nur „die Fassung,
die zurück ins Modell gefüttert wird"(`trim.py:18`;`prune.py:8`).

## Resilienz bei Netzausfall {#韧性}

Ein long-horizon workflow läuft schon einmal mehrere Stunden, das Netz reißt zwangsläufig einmal ab. Das
Default-Verhalten ist sehr schlecht: im Moment der Abtrennung stopft die Harness eine synthetische
assistant-Nachricht in die transcript (`model="<synthetic>"`、`isApiErrorMessage=true`), Rumpf ist
`API Error: Can't reach the API server …`; sie wird zum Blatt der session, und danach wird sie beim
resume als „das, was das Modell zuletzt gesagt hat" zurückgefüttert, das Modell glaubt, es diskutiere
über einen Netzfehler; sie mischt sich außerdem in `StepResult.text` und wird entlang des workflow an
den prompt des nächsten Schritts weitergegeben (`resilience.py:1-22`).

Die [resilience](glossary.md#韧性)-Schicht tut drei Dinge, keins entbehrlich: sondieren, fortsetzen statt
neu starten, Fehler nicht in den Kontext.

### `Resilience`-Parameter {#resilience}

| Parameter | Typ | Default | Semantik |
|---|---|---|---|
| `enabled` | `bool` | `True` | aus `Runtime(resilience=…)` umgewandelt |
| `max_attempts` | `int` | `6` | wie oft ein [Schritt](glossary.md#步骤) höchstens versucht wird, **einschließlich des ersten Mals** |
| `base_delay` | `float` | `4.0` | Startpunkt des exponentiellen Backoff, Sekunden |
| `max_delay` | `float` | `120.0` | Obergrenze des Backoff, Sekunden |
| `probe_timeout` | `float` | `5.0` | Timeout einer einzelnen Sonde, Sekunden |
| `probe_interval` | `float` | `15.0` | bei Netzausfall wie oft sondiert wird, Sekunden |
| `max_offline_wait` | `float` | `3600.0` | wie lange bei Netzausfall höchstens gewartet wird. Default 1 Stunde — länger als dies ist meist kein Flackern, sondern ein echtes Problem |
| `retry_unknown` | `bool` | `True` | auch nicht klassifizierbare Fehler werden erneut versucht. Die meisten unbekannten Fehler sind transient, und fatale Fehler wurden bereits separat abgefangen |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | was beim Fortsetzen zum Modell gesagt wird |

Die Backoff-Formel (`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

also `±25%` Jitter, um zu vermeiden, dass im Moment der Netzwiederherstellung ein Haufen Prozesse
zugleich losstürmt. Nach den Defaults: der 1. Backoff 4 Sekunden (tatsächlich 3~5), der 2. 8 Sekunden
(6~10), ab dem 5. bei 120 Sekunden gedeckelt (90~150).

### Sondierungsstrategie {#探针}

- **Sondiert wird das host:port von `ANTHROPIC_BASE_URL`**, nicht `api.anthropic.com`
  (`resilience.py:67-72`). Bei einem selbstgehosteten Gateway sagt die Erreichbarkeit von letzterem
  nichts über ersteres aus.
- **Nur DNS plus TCP-Handshake**: `getaddrinfo`, dann `connect_tcp`, dann sofort schließen. Kein HTTP,
  keine Credentials, kostet nichts (`resilience.py:75-85`). Die Sonde muss kostenlos sein, sonst wird
  „bei Netzausfall alle 15 Sekunden sondieren" selbst zur Störung.
- Jeder Fehlschlag gilt als unerreichbar — es wird nicht unterschieden, ob DNS ausgefallen ist oder TCP
  abgelehnt hat.
- `wait_online()` hängt dort und wartet: durchgekommen gibt `True` zurück, `max_offline_wait` voll
  gewartet gibt `False` zurück. Beim ersten Unerreichbar wird eine Zeile
  `<host>:<port> 不可达,等待恢复(最多 60 分钟)` gemeldet, bei Wiederherstellung nochmals eine Zeile
  `<host>:<port> 恢复,继续`, **dazwischen kein Fluten des Bildschirms**(`resilience.py:126-140`).

Die Credential-Sonde vor dem Start ist eine andere Sache: sie schlägt tatsächlich einmal
`POST <BASE_URL>/v1/messages` an, `max_tokens=16`, Default-Timeout 20 Sekunden (`env.py:126-181`).
`max_tokens` **nicht auf 1 setzen** — gemessen kann ein Modell mit erzwungener Gedankenkette nicht
einmal das Denken unterbringen, der Server ringt bis 30 Sekunden, bevor er zurückkommt; auf 16 gesetzt
braucht es nur 3,6 Sekunden (`env.py:120-123`).

### Fehlerklassifikation {#错误分类}

`classify(text)` gibt eins von drei zurück. **Zuerst fatal beurteilen**: in Texten wie 401 steckt oft
auch ein Wort wie „connection", in falscher Reihenfolge wartet es sich zu Tode (`resilience.py:53-64`).

| Klasse | Was getroffen wird (Regex siehe `resilience.py:37-50`) | Verhalten |
|---|---|---|
| `fatal` | `400` `401` `403` `404`、`invalid api key`、`authentication`、`unauthorized`、`permission denied`、`invalid_request`、`credit balance`、`quota exceeded`、`budget`、`max_turns`、`CLINotFound` | sofort stoppen, kein retry. Egal wie oft erneut versucht, das Ergebnis bleibt gleich, und jedes Mal kostet es Geld |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`、`socket hang up`、`fetch failed`、`Can't reach the API server`、`429` `500` `502` `503` `504` `529`、`overloaded`、`rate limit`、`timeout`、`service unavailable` | warten, bis das Netz zurück ist, dann per resume fortsetzen |
| `unknown` | passt auf keins | bei `retry_unknown=True`(default) ebenfalls erneut versuchen |

Wiederholbares von nicht Wiederholbarem zu unterscheiden ist der Kern dieser Schicht: **Netzflackern
soll gewartet, ein Credential-Fehler sofort gestoppt werden** — bei Netzausfall totzuwarten ist richtig,
bei falsch geschriebenem Key totzuwarten ist Zeitverbrennen.

### Was außerhalb des Kontexts gehalten wird {#错误不进上下文}

1. **Die synthetische Fehlermeldung.** `PruningSessionStore` entfernt sie bei `load` als ganzen Eintrag
   und verkettet die `parentUuid` neu (`prune.py:27-32`、`:191-195`). **In SQLite bleibt sie original
   erhalten**, nur wird sie nicht zurückgefüttert.
2. **Im Eventstrom ist sie `kind="error"` und nicht `"text"`**, kommt daher nicht in `StepResult.text`
   und wird also nicht entlang des workflow an den prompt des nächsten Schritts weitergegeben
   (`resilience.py:17-18`).
3. **`resume_prompt` enthält bewusst keinerlei Fehlerdetails.** Das Modell muss wissen „wurde
   unterbrochen, mach weiter", muss nicht wissen, ob es `ENOTFOUND` oder `503` war. **Das gehört ins
   Log, nicht in den Kontext**(`resilience.py:112-113`). Fürs Log siehe das Feld `errors` in
   `manifest.json`.

Fortsetzen statt neu starten: wenn der Fehlschlag passiert, ist die `session_id` schon da, per resume
von der Unterbrechungsstelle fortsetzen, die vorherigen Kosten sind nicht umsonst.

## Verwandtes {#相关}

- [Kommandozeile](cli.md) — wie jeder Schalter auf die Konfiguration dieser Seite abbildet.
- [Python API](api.md) — die vollständigen Signaturen von `Runtime`, den drei stores und `Resilience`.
- [Deployment](deploy.md) — im Container laufen, Domänenfähigkeiten per plugin ausliefern.
- [Glossar](glossary.md) — die genaue Bedeutung jedes auf dieser Seite verwendeten Begriffs.
