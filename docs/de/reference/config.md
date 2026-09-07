# Konfiguration

flower hat kein Konfigurationsdateiformat und auch kein Konfigurations-Unterkommando, das wirklich etwas bewirkt — alle Konfiguration läuft über **Umgebungsvariablen** plus **`.env`-Dateien**, dazu eine Handvoll Policy-Objekte, die es nur auf der Python-Seite gibt. Diese Seite zieht zusammen, was an fünf Stellen verstreut liegt: jede Variable, in welcher Reihenfolge Credentials gesucht werden, welche Syntax `.env` akzeptiert, was `setting_sources=[]` genau abschottet, was ein Run auf der Platte hinterlässt, was die drei Schichten des Session Store jeweils wegwerfen und wie bei Netzausfall gewartet wird. Begriffe durchgehend nach [Glossar](glossary.md).

| Was du wissen willst | Wohin |
|---|---|
| Welche Umgebungsvariablen flower liest | [Vollständige Variablentabelle](#环境变量) |
| Woher mein Token eigentlich kommt | [Prioritätsreihenfolge der Credential-Suche](#凭证查找优先级) |
| Warum diese Zeile in `.env` nicht greift | [`.env`-Parsingregeln](#env-解析) |
| Was beim Maschinenwechsel mit muss | [Der Preis der Portabilität](#可移植性) |
| Was in `.flower/` und `runs/` liegt | [Layout auf der Platte](#磁盘布局) |
| Welche Nachrichten nicht zurück ins Modell gehen | [Die drei Schichten des Session Store](#会话存储) |
| Worauf es bei Netzausfall wartet | [Resilience bei Netzausfall](#韧性) |

## Vollständige Variablentabelle {#环境变量}

Vier Gruppen: Credentials und Endpoint, die flower direkt liest; Modellauswahl; Pfadsuche; und das, was flower **an** den Agent-Subprozess schreibt. Die letzte Gruppe musst du nicht setzen — wenn du es tust, wird sie überschrieben.

### Credentials und Endpoint {#凭证变量}

| Variable | Wirkung | Default | Pflicht | Fundstelle |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | Offizieller Anthropic-Key. Wenn vorhanden, geht die Anfrage mit `x-api-key`-Header raus | keiner | **Eines von beiden** mit `ANTHROPIC_AUTH_TOKEN` **Pflicht** | `env.py:28`, `:146`, `:157-158` |
| `ANTHROPIC_AUTH_TOKEN` | Vom Gateway ausgestelltes Token. Ohne `ANTHROPIC_API_KEY` wird `authorization: Bearer` verwendet | keiner | wie oben | `env.py:28`, `:147`, `:159-160` |
| `ANTHROPIC_BASE_URL` | Wurzeladresse des API-Endpoints. Ein Drittanbieter-Gateway trägt hier seine eigene Adresse ein, **ohne `/v1`** — die Probe baut `<BASE_URL>/v1/messages` zusammen | `https://api.anthropic.com` | nein | `env.py:151`, `:162`, `:210`; `resilience.py:70` |

Ist keines von beiden gesetzt (oder sind beide leere Strings), gibt `check_credentials()` jene vierzeilige Fehlermeldung zurück, und `Runtime.__init__` wirft einen `RuntimeError` (`env.py:184-194`; `runtime.py:156-158`).

### Modellauswahl {#模型变量}

flower liest davon nur drei für eigene Entscheidungen, der Rest wird geladen und unverändert an das SDK durchgereicht.

| Variable | Wirkung | Default | Pflicht | Fundstelle |
|---|---|---|---|---|
| `ANTHROPIC_MODEL` | Name des Hauptmodells. Bestimmt zugleich den Default für das [Handoff](glossary.md#换代)-Fenster: Name enthält `1m` oder enthält kein `haiku` → 1 Million, enthält `haiku` → 200.000 | keiner (die Gegenseite entscheidet) | nein | `env.py:153`; `agent.py:77-81` |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | Modell-Mapping der Opus-Stufe. Ist `ANTHROPIC_MODEL` leer, fällt die Fensterbestimmung hierauf zurück | keiner | nein | `agent.py:78`; `cli.py:1205` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | Modell-Mapping der Sonnet-Stufe. flower liest sie selbst nicht, lädt und leiht sie nur | keiner | nein | `env.py:34`; `cli.py:1206` |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Modell-Mapping der Haiku-Stufe. **Die Credential-Probe nimmt bevorzugt diese** | Probe fällt zurück auf `ANTHROPIC_MODEL`, dann auf `claude-3-5-haiku-20241022` | nein | `env.py:152-153` |
| `CLAUDE_CODE_SUBAGENT_MODEL` | Welches Modell [subagents](glossary.md#subagent) benutzen. flower interpretiert sie nicht, das SDK konsumiert sie | keiner | nein | `env.py:35`; `.env.example` |
| `CLAUDE_CODE_EFFORT_LEVEL` | Denkstufe. Ebenfalls nur geladen, nicht interpretiert | keiner | nein | `env.py:35` |

Wenn bei `flower setup` ein Modellname eingetragen wurde, werden `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` und `ANTHROPIC_DEFAULT_SONNET_MODEL` **alle drei zusammen geschrieben** (`cli.py:1204-1206`).

### Pfade und Suche {#路径变量}

| Variable | Wirkung | Default | Pflicht | Fundstelle |
|---|---|---|---|---|
| `FLOWER_ENV` | Gibt einen `.env`-Pfad an, der **vor** allen anderen Dateien kommt | keiner | nein | `env.py:48-49` |
| `XDG_CONFIG_HOME` | Bestimmt den Ort der globalen Credential-Datei `$XDG_CONFIG_HOME/flower/.env` | `~/.config` | nein | `env.py:41-42` |
| `HOME` | Quelle für `Path.home()`; sowohl `~/.config` als auch `~/.claude` werden daraus abgeleitet | vom System | nein | `env.py:41`, `:67` |

### Was flower an den Agent-Subprozess schreibt {#写出的变量}

Diese drei erzeugt `CompactPolicy.env()` und steckt sie in `ClaudeAgentOptions.env` (`agent.py:48-58`, `:241-245`); sie steuern den im Harness eingebauten [Compact](glossary.md#压缩). **Sie in der Shell zu setzen ist sinnlos** — wirksam ist die Fassung, die flower an den Subprozess übergibt.

| Variable | Wirkung | Default | Pflicht | Fundstelle |
|---|---|---|---|---|
| `DISABLE_AUTO_COMPACT` | `=1` schaltet Auto-Compact ab. Wenn [Handoff](glossary.md#换代) aktiv ist, wird sie **zwingend geschrieben** — laufen beide Mechanismen gleichzeitig, lässt sich nicht mehr unterscheiden, wer den Kontextabfall verursacht hat | Handoff ist standardmäßig an, also praktisch konstant `1` | nein (flower schreibt sie) | `agent.py:51`; `runtime.py:444-447` |
| `DISABLE_COMPACT` | `=1` schaltet auch `/compact` mit ab. Wird nur bei `CompactPolicy(mode="off")` geschrieben | wird nicht geschrieben | nein (flower schreibt sie) | `agent.py:52-53` |
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW` | Fenster für Auto-Compact (in Tokens). Wird nur bei `CompactPolicy(window=N)` geschrieben | wird nicht geschrieben | nein (flower schreibt sie) | `agent.py:56-57` |

### Was der Container-Wrapper liest {#容器变量}

Diese beiden liest nicht flower selbst, sondern der Shell-Wrapper `docker/flowerbox`. Vollständige Nutzung siehe [Deployment](deploy.md).

| Variable | Wirkung | Default | Pflicht | Fundstelle |
|---|---|---|---|---|
| `FLOWER_HOME` | Wo die `.env` für `--env-file` gesucht wird | das Elternverzeichnis des Skriptorts | nein | `docker/flowerbox:12` |
| `FLOWER_IMAGE` | Welches Image benutzt wird | `flower-box` | nein | `docker/flowerbox:13` |

**Die Schlüssel in `.env` sind nicht auf die obigen beschränkt.** Der Parser lädt **alle** `k=v`-Zeilen nach `os.environ`, ohne Whitelist (`env.py:30`, `:102-107`). Das `KNOWN` aus den obigen 9 Credential-Schlüsseln wirkt nur an zwei Stellen: als Whitelist beim Ausleihen der `~/.claude`-Konfiguration (`env.py:72`) und als Feldumfang der `describe()`-Ausgabe beim Start mit `-v` (`env.py:205`).

## Prioritätsreihenfolge der Credential-Suche {#凭证查找优先级}

Wird `load_dotenv()` ohne Pfad aufgerufen, werden **alle vorhandenen** Dateien in dieser Reihenfolge nacheinander eingelesen (`env.py:45-53`, `:78-112`):

1. **Prozess-Umgebungsvariablen** — immer ganz oben. Keine `.env` überschreibt einen bereits exportierten Wert. (`env.py:91`)
2. **Die Datei hinter `$FLOWER_ENV`** — existiert nur, wenn gesetzt. (`env.py:48-49`)
3. **`$PWD/.env`** — das aktuelle Arbeitsverzeichnis. In welchem Projekt du gerade stehst, dessen Datei wird genommen. (`env.py:50`)
4. **`${XDG_CONFIG_HOME:-~/.config}/flower/.env`** — der globale Ort pro Benutzer; genau dorthin schreibt `flower setup`. (`env.py:51`, `:39-42`)
5. **Die `.env` in der Wurzel des Quell-Repos** — drei Ebenen über `flower/core/env.py`. Existiert nur bei Betrieb aus dem Quellcode; ein per pip / pipx / uv installiertes flower liegt in site-packages, dort gibt es diesen Punkt nicht. (`env.py:52`)
6. **Der `env`-Block aus `~/.claude/settings.json`, danach `~/.claude/settings.local.json`** — der letzte Fallback, **nur die 9 Credential-Schlüssel**. (`env.py:56-75`, `:109-111`)

**Welche Datei gewinnt**: Punkt 3 (Projekt-`.env`) schlägt Punkt 4 (globale `.env`), Punkt 4 schlägt Punkt 5 (`.env` in der Repo-Wurzel), alle drei schlagen Punkt 6 (die Konfiguration von Claude Code), und keiner davon schlägt Punkt 1 (die Prozessumgebung).

Umgesetzt ist das als „**Schlüssel mit vorhandenem Wert werden nicht überschrieben**" (`env.py:90-93`): Wer vorne steht, belegt den Schlüssel zuerst, spätere füllen nur Lücken. Die Priorität gilt also **pro Schlüssel, nicht pro Datei** — steht in der Projekt-`.env` nur `ANTHROPIC_BASE_URL`, darf das Token weiterhin aus der globalen Datei kommen. Der beim ersten Auftreten gesetzte Wert eines Schlüssels gilt endgültig.

Punkt 6 greift nur bei der **automatischen Suche**. Wird ein Pfad explizit angegeben (`load_dotenv("/path/to/.env")`), wird ausschließlich diese eine Datei gelesen, ohne jeden Fallback (`env.py:86-87`, `:109`).

### Punkt 6: das Token von Claude Code ausleihen {#借用}

Nacheinander werden `~/.claude/settings.json` und `~/.claude/settings.local.json` gelesen, das Dict `data["env"]` genommen und daraus diese 9 Schlüssel herausgesucht (`env.py:31-36`, `:65-74`):

```text
ANTHROPIC_API_KEY   ANTHROPIC_AUTH_TOKEN   ANTHROPIC_BASE_URL
ANTHROPIC_MODEL     ANTHROPIC_DEFAULT_OPUS_MODEL    ANTHROPIC_DEFAULT_SONNET_MODEL
ANTHROPIC_DEFAULT_HAIKU_MODEL    CLAUDE_CODE_SUBAGENT_MODEL    CLAUDE_CODE_EFFORT_LEVEL
```

Existiert die Datei nicht, ist sie nicht lesbar oder kein gültiges JSON (`OSError` / `ValueError`), wird ein leeres Dict zurückgegeben und weitergemacht — **ein kaputter Fallback darf den Run nicht mitreißen** (`env.py:62-63`, `:66-69`).

Die Haltung im Code lautet: Geliehen wird nur „wo das Token zu finden ist"; alles andere aus settings.json (Berechtigungsregeln, Hooks, Modelleinstellungen) wird nicht übernommen, deshalb verletzt das nicht das Portabilitätsversprechen von `setting_sources=[]` (`env.py:17-19`, `:59-61`). `install.sh:77` bewirbt es als Feature: Wer Claude Code lokal eingerichtet hat, bekommt die Konfigurationsoberfläche gar nicht erst zu sehen.

!!! warning "Der Fehlertext im Produkt widerspricht dem tatsächlichen Verhalten"
    Wenn überhaupt keine Credentials gefunden werden, lautet die letzte Zeile des Fehlers, den flower ausgibt:

    ```text
    flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
    ```

    (`env.py:184-194`, der Satz steht in `:192`; dieselbe Behauptung findet sich außerdem in `.env.example:2`, `env.py:3-4`, `agent.py:10-12`.) **Maßgeblich ist der Code: es liest sie.** `env.py:56-75` plus `:109-111` lesen diese beiden Dateien ausdrücklich, und `install.sh:77` verkauft das sogar als Vorteil. Dieser Text ist derzeit irreführend — auf einer Maschine, auf der Claude Code eingerichtet ist, kommt dein Token sehr wahrscheinlich genau von dort.

## `.env`-Parsingregeln {#env-解析}

Die Regeln sind kurz genug zum Auswendiglernen (`env.py:95-107`, 13 Zeilen): Zeile für Zeile `strip`, leere Zeilen, mit `#` beginnende Zeilen und Zeilen ohne `=` überspringen; der Rest wird am **ersten** `=` in Key und Value zerlegt, beide Seiten je einmal `strip`, der Value zusätzlich `.strip("'\"")` — führende und abschließende einfache oder doppelte Anführungszeichen werden entfernt, **ohne Paarung zu verlangen**.

**Das wird akzeptiert**:

| Schreibweise | Ergebnis |
|---|---|
| `KEY=VALUE` | normal |
| `KEY = VALUE` | normal — Leerzeichen um das Gleichheitszeichen werden gestrippt |
| `KEY="VALUE"` / `KEY='VALUE'` | normal — äußere Anführungszeichen werden entfernt |
| `KEY=a=b` | Value ist `a=b` — geteilt wird am ersten `=`, weitere Gleichheitszeichen bleiben im Wert |
| `# 注释` | ganze Zeile wird übersprungen |
| Leerzeile | wird übersprungen |

**Das wird nicht akzeptiert.** Es gibt keinen Fehler, du bekommst still einen unerwarteten Wert:

| Schreibweise | Tatsächliches Ergebnis |
|---|---|
| `export KEY=VALUE` | der Key heißt `export KEY`, `KEY` selbst bleibt weiterhin ohne Wert |
| `KEY=value # 说明` | Value ist `value # 说明` — Kommentare am Zeilenende werden nicht abgetrennt |
| `KEY=$OTHER` | das Literal `$OTHER`, keine Variablenexpansion |
| Mehrzeilige Werte (mit Anführungszeichen über Zeilen hinweg) | wird zeilenweise verarbeitet; die zweite Zeile enthält kein `=` und wird komplett übersprungen |

**Leere Werte belegen den Schlüssel.** Steht `ANTHROPIC_AUTH_TOKEN=` in einer Datei mit hoher Priorität, führt `take()` `os.environ["ANTHROPIC_AUTH_TOKEN"] = ""` aus, und spätere Dateien können nichts mehr nachfüllen, weil „der Schlüssel existiert bereits" (`env.py:90-93`); `check_credentials()` prüft dagegen auf Wahrheitswert, ein leerer String gilt als nicht konfiguriert (`env.py:186`). **Ergebnis: weder Credentials noch Fallback.** Willst du einen Schlüssel nicht, lösche die ganze Zeile, statt sie leer stehen zu lassen.

## Der Preis der Portabilität {#可移植性}

Die eine Zeile in `build_options()` ist der ganze Mechanismus (`agent.py:207`):

```python
"setting_sources": [] if portable else ["project"],
```

`portable=True` ist der Default von `Runtime`, und **auf der Kommandozeile gibt es keinen Schalter, der das abschaltet** — abschalten geht nur über die Python-API mit `Runtime(portable=False)`, dann wird daraus `["project"]`, also wird das `.claude/` des Projekts gelesen.

### Was abgeschottet wird

| Abgeschottet | Folge |
|---|---|
| Die Einstellungen aus `~/.claude/` des Hosts | Berechtigungsregeln, Hooks und Modelleinstellungen von dort greifen sämtlich nicht. **Credentials sind die einzige Ausnahme**, siehe [Ausleihen](#借用) |
| Das `.claude/` des Projekts | wie oben; wird nur bei `portable=False` gelesen |

Fachliche Fähigkeiten laufen nicht über diesen Weg — sie werden mit dem Repo ausgeliefert und über `plugins=[{"type": "local", "path": PLUGIN_DIR}]` geladen (`agent.py:26`, `:210-212`), siehe [Deployment](deploy.md). Fachliche Anweisungen werden **hinter** den nativen System-Prompt von Claude Code **angehängt**, nicht ersetzt (`agent.py:198-202`); Spezialisierung geht also nicht auf Kosten allgemeiner Fähigkeiten.

### Was beim Maschinenwechsel mit muss

- **Credentials: eine Datei**. `~/.config/flower/.env` hinüberkopieren, oder auf der neuen Maschine einmal neu einrichten. Ohne sie läuft gar nichts — es wird nichts automatisch geerbt.
- **Kontinuitätszustand: das ganze Verzeichnis**. `runs/` (Session-Datenbank, Manifest, Lineage) und `.flower/` (Workbench).
- **Aber die Pfade müssen übereinstimmen**. In `lineage.json` steht der absolute Pfad des Workspace; passt er nicht, gilt er als nicht vorhanden, es wird still auf eine neue Session zurückgefallen, **ohne Fehler** (`lineage.py:65-66`). Grund: Der `project_key` des SDK wird aus dem Workspace-Pfad abgeleitet (`/`, `_`, `.` werden alle zu `-`, `runtime.py:40-41`); verschiebt sich das Verzeichnis, ist die alte `session_id` nicht mehr auffindbar.

## Layout auf der Platte {#磁盘布局}

Ein flower-Run schreibt zwei Bäume: `<run_dir>/` für Buchführung und Sessions, `<workspace>/.flower/` für die [Workbench](glossary.md#工作台). Beide liegen standardmäßig unter dem aktuellen Verzeichnis, **aber ihre Bezugspunkte sind verschieden**.

!!! warning "`runs/` folgt dem aktuellen Verzeichnis, nicht `-w`"
    `-r/--run-dir` ist standardmäßig `"runs"`, und `Runtime` macht daraus `Path(run_dir).resolve()` (`runtime.py:93-94`) — relativ zum **aktuellen Arbeitsverzeichnis**, nicht relativ zum mit `-w` angegebenen Workspace. Startest du in `~` ein `flower -w /path/to/proj`, landet die Session-Datenbank in `~/runs/`, nicht im Projekt.

### `<run_dir>/` — standardmäßig `./runs/` {#run-dir}

```text
runs/
  sessions.db        SQLite,全量 transcript(含每个 subagent 自己那条)
  manifest.json      运行清单:每一步的 session_id / 花费 / 重试 / 失败原因,跨进程累积
  lineage.json       血缘:步骤名 → session_id,同一个目录再跑一次靠它接上
  aside/             旁路问答的独立 Runtime,自己的 sessions.db + manifest.json
  workbench/         仅当走 run / once 路径且给了 -W
```

| Pfad | Inhalt | Fundstelle |
|---|---|---|
| `runs/sessions.db` | Vollständiges Transcript. Geschrieben von `PruningSessionStore`, die drei Schichten siehe [unten](#会话存储) | `runtime.py:109-112` |
| `runs/manifest.json` | JSON-Array, **prozessübergreifend kumuliertes** [Run-Manifest](glossary.md#运行清单). Felder siehe Tabelle unten | `runtime.py:532-533`, `:564-586` |
| `runs/lineage.json` | `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Erst `.tmp` schreiben, dann `replace`, atomarer Austausch | `lineage.py:31`, `:87-97` |
| `runs/aside/` | Eigenes Runtime des [Oracle](glossary.md#旁路顾问). **Kosten und Lineage vermischen sich nicht mit dem Hauptmanifest** | `cli.py:632-634` |
| `runs/workbench/` | Standardort der Workbench bei `Runtime(workbench=True)`, außerhalb des Workspace. Der `go`-Pfad nutzt ihn nicht | `runtime.py:148-151` |

Jede Zeile in `manifest.json` ist ein `asdict(StepResult)` plus zwei Nachbesserungen (`runtime.py:44-71`, `:579-582`):

| Feld | Typ | Bedeutung |
|---|---|---|
| `step` | `str` | Schrittname. Vier Formen: `<名>`, `<名>#round<N>` (zurückgewiesen und neu gemacht), `<名>#retry<N>` (normaler Retry), `<名>·判定#<N>` ([Judge](glossary.md#判定者)) |
| `session_id` | `str \| None` | Die zuletzt lebende [Session](glossary.md#会话) dieses Schritts |
| `ok` | `bool` | Geklappt oder nicht |
| `cost_usd` | `float` | Was dieser Schritt gekostet hat |
| `num_turns` | `int` | Wie viele Runden gelaufen sind |
| `text` | `str` | Die abschließende Antwort dieses Schritts |
| `error` | `str \| None` | Fehlerursache. Bei Abschuss durch SIGHUP / SIGTERM steht dort `killed-by-signal` (`runtime.py:556-558`) |
| `started_at` / `ended_at` | `float` | Epoch-Sekunden |
| `attempts` | `int` | Tatsächliche Anzahl Versuche. `>1` heißt, es wurde wiederholt |
| `errors` | `list[str]` | Alle bisherigen Fehlerursachen. **Nur hier, das Modell sieht sie nicht** |
| `resumed` | `bool` | Ob per Resume an der Unterbrechungsstelle angeknüpft wurde, statt von vorn zu laufen |
| `retired` | `list[str]` | Die beim [Handoff](glossary.md#换代) dieses Schritts verbrannten session_ids, in Reihenfolge |
| `context` | `int` | Wie groß der Kontext war, den der [Hauptthread](glossary.md#主线程) in der letzten Runde tatsächlich gesehen hat |
| `duration_s` | `float` | Von Hand nachgetragen — es ist ein `@property`, `asdict()` bekommt es nicht mit |
| `run` | `str` | Marke dieses Prozesses, `YYYYmmdd-HHMMSS-<6 位 hex>`. **Muss pro Instanz eindeutig sein** |

Die Schreibstrategie ist **anhängen statt überschreiben**: Vor jedem Schreiben wird die Datei neu eingelesen, die Zeilen mit dem eigenen `run` werden durch die aktuellen ersetzt, fremde Zeilen bleiben unangetastet (`runtime.py:564-586`). Laufen also mehrere flower parallel im selben Verzeichnis, löschen sich die Bücher nicht gegenseitig.

Was in `runs/` liegt, sind reine Daten und jederzeit offline mit sqlite3 oder [`tools/analyze_run.py`](https://github.com/ChenyuHeee/flower/blob/main/tools/analyze_run.py) durchsuchbar.

### `<workspace>/.flower/` — die Workbench {#工作台目录}

```text
.flower/
  INDEX.md      自动生成的索引,注入主 agent 的 system prompt
  scripts/      要跑第二次的脚本。首行 `# desc: 一句话` 会出现在索引里
  artifacts/    超过 2000 字符的长产出:报告、数据、日志
  notes/        跨步骤的决策记录
  spill/        落盘的大工具结果,文件名 = 内容 sha256 前 16 位 + `.txt`
```

Die drei Unterverzeichnisse plus Index legt `Workbench` an (`workbench.py:73-92`). `INDEX.md` geht über den sessionweiten `system_prompt.append`, **subagents erben ihn nicht** — deshalb muss die Regel „lange Ausgaben nach `artifacts/` schreiben" vom [Koordinator](glossary.md#协调者) im [Task Brief](glossary.md#任务书) weitergegeben werden; das ist der einzige Kanal.

Der `go`-Pfad erzeugt unter `notes/` fest diese Dateien:

| Datei | Inhalt | Fundstelle |
|---|---|---|
| `notes/需求.md` | Der eingefrorene [Brief](glossary.md#需求确认书), vier Abschnitte: Ziel / Abnahmekriterien / Grenzen / Unbekanntes und Annahmen | `brief.py:44-45`; `clarify.py:105` |
| `notes/目标.md` | Zwei eingefrorene Abschnitte: Ziel / Prüfliste | `workflow/goal.py:124` |
| `notes/问答记录.md` | Fortlaufendes Protokoll aller Fragen und Antworten, inklusive der Inbox-Einträge, bei denen der Mensch von sich aus etwas sagt. **Geht nicht in den Kontext, dient nur der Ablage** | `human.py:421-433` |
| `notes/交接-<步骤名>.md` | Das [Handoff-Dokument](glossary.md#交接书). Die vorige Generation wandert nach `notes/archive/交接/<步骤名>-<时间戳>.md` | `runtime.py:388-403` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | Von `--new` / `/new` archivierte `lineage.json` + `需求.md` + `目标.md` (**verschoben, nicht gelöscht**) | `lineage.py:100-117` |

**Bei `--isolate` wandert die Workbench aus dem Repo heraus**: `<Elternverzeichnis des Workspace>/.flower-<Workspace-Name>/` (`starter.py:47-55`). Ein Worktree ist die private Kopie je Agent, die Workbench ist die agentübergreifend geteilte Schicht — Geteiltes gehört nicht hinter einen privaten Zaun. In diesem Fall bekommt das Modell absolute Pfade (`workbench.py:69-71`, `:142-145`).

**In `spill/` schreiben zwei Instanzen, mit unterschiedlicher Zielberechnung**:

| Wer schreibt | Wann | Wohin | Schwelle |
|---|---|---|---|
| `spill_guard` (`PostToolUse`-Hook) | **bevor** das Tool-Ergebnis ins Modell geht | `<Workbench-Root>/spill/` (`guard.py:130`) | `spill_threshold`, Default 4000 Zeichen |
| `TrimPolicy` (beim `load`) | beim Wiedereinspielen der Historie vor einem Resume | `<workspace>/.flower/spill/` — ein fester String relativ zum Workspace (`trim.py:49`, `:303`) | `min_chars`, Default 2000 Zeichen |

Im Standardlayout ist das dasselbe Verzeichnis. Sobald die Workbench aber verschoben wird (`-W` lässt sie in `runs/workbench/` landen, `--isolate` außerhalb des Repos), trennen sich die beiden — die Variante der `TrimPolicy` bleibt immer im Workspace, weil das `Read` des Agents sie erreichen muss.

Was `spill_guard` einsetzt, ist keine einzelne Zeile, sondern eine Zeiger-Zeile plus die **ersten 400 Zeichen** (`guard.py:132-140`). Aufrufe, die die Spill-Datei selbst lesen, werden durchgelassen, sonst wäre „lies bei Bedarf den vollen Text mit Read" leeres Gerede — das Gelesene überschreitet erneut die Schwelle, wird erneut gespillt, Endlosschleife (`guard.py:155-170`).

### Das Tabellenschema von `sessions.db` {#sessions-db}

Drei Tabellen, die CREATE-Statements stehen in `stores/sqlite.py:27-51`:

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
| `entries` | Ein Eintrag im Transcript, `payload` ist das rohe JSON | `uid` ist die `uuid` des Eintrags und dient als **Idempotenzschlüssel**: fehlgeschlagene Batches werden bis zu 3-mal wiederholt, das Wiederabspielen darf keine Duplikate erzeugen. Einträge ohne `uuid` (Titel, Labels, Modusmarker) werden nicht dedupliziert, daher trägt der Unique-Index ein `WHERE uid IS NOT NULL` |
| `meta` | Der Cursor einer Session | `next_seq` ist die nächste Sequenznummer, `mtime` ein Millisekunden-Zeitstempel und **streng monoton** (`sqlite.py:72-79`) — `list_sessions` und die Summary teilen sich diese Uhr; ohne Monotonie schlägt das SDK beim Vergleich alt/neu den falschen Schnellpfad ein |
| `summaries` | Das Summary-Sidecar eines Hauptthreads | **Nur Haupt-Transcripts nehmen teil**, die der subagents zählen nicht (`sqlite.py:122-123`) |

Aufbau des `store_key` (`sqlite.py:54-58`): `<project_key>/<session_id>`, bei subagents noch ein `subpath` angehängt. Den `project_key` leitet das SDK aus dem Workspace-Pfad ab — `/`, `_`, `.` werden alle zu `-`.

Ein Blick auf ein echtes Sample ([`human-test/HT002/runs/sessions.db`](https://github.com/ChenyuHeee/flower/blob/main/human-test/HT002/runs/sessions.db)):

```bash
sqlite3 runs/sessions.db "select store_key, next_seq from meta;"
```

```text
-Users-hechenyu-explore-test-ide/601c8c91-6c4b-4525-8a5f-295b99bf9515|37
-Users-hechenyu-explore-test-ide/47395075-bec7-466e-80cd-f4d60b360235|80
-Users-hechenyu-explore-test-ide/47395075-…/subagents/agent-a99a6ce30a5471f44|104
```

Diese Datei enthält 956 `entries`, 10 `meta` und 4 `summaries` — von den 10 Sessions sind 4 Haupt-Transcripts und 6 von subagents, und `summaries` entspricht genau der Anzahl der Haupt-Transcripts.

## Die drei Schichten des Session Store {#会话存储}

!!! note "Die drei Schichten sind eine Vererbungskette, keine wählbare Kombination"
    `PruningSessionStore` erbt von `TrimmingSessionStore`, das von `SqliteSessionStore`. `Runtime` konstruiert **immer** die äußerste Schicht (`runtime.py:109-112`); in den Konstruktorparametern gibt es keinen Einstieg, das Backend zu tauschen. Eine Schicht „abzuschalten" heißt, `enabled` ihres Policy-Objekts auf `False` zu setzen, nicht die Klasse zu wechseln.

`append` (Schreiben) legt immer alles vollständig ab, ohne ein Zeichen zu ändern. Die drei Schichten wirken nur auf `load` (die Fassung, die zurück ins Modell geht). Die tatsächliche Reihenfolge von `load`:

```text
SqliteSessionStore.load     从 entries 表按 seq 读出全部
  → TrimmingSessionStore.expire()   时效性 Bash 结果 → 换成"已过期"
  → TrimmingSessionStore.trim()     旧的大 tool_result → 落盘 + 换成指针
    → PruningSessionStore.prune()   合成错误消息 / 旧的被拒调用 → 整条摘掉并重接链
```

| Schicht | Klasse | Was wegfällt | Kriterium |
|---|---|---|---|
| 1 | `SqliteSessionStore` | nichts | —— |
| 2 | `TrimmingSessionStore` | Rumpf großer Tool-Ergebnisse, abgelaufene Ergebnisse von Ephemeral Commands | Größe + Aktualität |
| 3 | `PruningSessionStore` | Reste abgerissener Verbindungen, alte abgelehnte Aufrufe | ob es ein Fehler ist |

Schicht 2 ist [Trim](glossary.md#裁剪), Schicht 3 ist [Prune](glossary.md#剪除) — **Trim wirft nach Größe und Wert weg, Prune nach „ist es ein Fehler"**, nicht vermischen. Vollständige Signaturen siehe [Python API](api.md).

### `SqliteSessionStore` — das Fundament {#sqlite-store}

```python
SqliteSessionStore(path: str | Path)
```

Eine SQLite-Implementierung ohne externe Abhängigkeiten. Für Postgres / S3 / Redis genügt es, dasselbe Protokoll zu implementieren; das SDK bringt die Konformitäts-Testsuite `claude_agent_sdk.testing.session_store_conformance` mit, mit der sich das direkt prüfen lässt (`sqlite.py:1-8`).

Neben den Protokollmethoden gibt es drei **synchrone** Abfragen für flower selbst:

| Methode | Rückgabe | Zweck |
|---|---|---|
| `projects()` | `list[str]` | Die tatsächlich in der Datenbank vorhandenen `project_key`. Das SDK leitet ihn aus dem cwd ab; vor einer Abfrage damit bestätigen statt raten |
| `has_session(project_key, session_id)` | `bool` | Prüft nur eine Zeile in `meta`, ohne Payload zu lesen. Vor dem Start der [Kontinuität](glossary.md#接续) erst abfragen — der Resume einer nicht existierenden Session fliegt erst, nachdem der Subprozess hochgefahren ist, und dann sind Geld und Zeit schon weg |
| `last_context(project_key, session_id, scan=60)` | `int` | Wie groß der Kontext war, den diese Session zuletzt gesehen hat. Es werden nur die letzten 60 Einträge rückwärts gescannt. `input_tokens` plus die beiden `cache_*` zählen mit — sieht man nur auf Ersteres, liegt es bei Cache-Treffern nahe 0 und unterschätzt massiv |

### `TrimmingSessionStore` + `TrimPolicy` / `EphemeralPolicy` {#trimming-store}

```python
TrimmingSessionStore(path, workspace, policy: TrimPolicy | None = None,
                     ephemeral: EphemeralPolicy | None = None)
```

Zwei orthogonale Regelwerke. `TrimPolicy` regelt die **Größe**:

| Parameter | Typ | Default | Bedeutung |
|---|---|---|---|
| `keep_recent` | `int` | `20` | Die letzten N `tool_result` behalten ihren Originaltext — Kontext, der gerade benutzt wird, darf nicht getrimmt werden |
| `min_chars` | `int` | `2000` | Kürzeres wird nicht getrimmt. Ein Zeiger kostet sonst mehr Tokens |
| `spill_dirname` | `str` | `".flower/spill"` | Archivverzeichnis, **relativ zum workspace**. Muss innerhalb des Workspace liegen, sonst kommt das `Read` des Agents nicht heran |
| `enabled` | `bool` | `True` | Bei `Runtime(trim=False)` (Default) ist es `False` |

Der getrimmte Rumpf wird als `<sha256 前 16 位>.txt` geschrieben, an der alten Stelle steht `[工具结果已归档:N 字符。完整内容在 <路径>,需要时用 Read 读取]` (`trim.py:54-57`, `:308-317`).

`EphemeralPolicy` regelt die **Aktualität**: Ergebnisse wie von `git status`, `ls` oder `ps` sind sehr kurz, nach Größe käme nie ein Trim in Frage — aber ihre Korrektheit zerfällt mit der Zeit. Ein `git status` von vor 20 Runden ist nicht „nutzlos", es ist **irreführend**.

| Parameter | Typ | Default | Bedeutung |
|---|---|---|---|
| `enabled` | `bool` | `True` | Wird aus `Runtime(ephemeral=…)` übersetzt, **standardmäßig an** |
| `keep_recent` | `int` | `6` | Die letzten N Einträge behalten den Originaltext. Deutlich kleiner als die 20 der `TrimPolicy` — bei solchen Dingen ist das Fenster für „kürzlich" von Haus aus kurz |
| `max_chars` | `int` | `2000` | Darüber übernimmt die `TrimPolicy` mit Spill und Archivierung, dieser Weg greift nicht |
| `text` | `str` | `"[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"` | Ersatztext |

Wirkt nur auf Ergebnisse des **Bash**-Tools, und das Kommando muss `EPHEMERAL_CMD` treffen. `Read` gehört nicht dazu: Dateiinhalte werden durch Zeitablauf nicht so verfälscht, dass sie irreführen, und sie sind möglicherweise genau die Grundlage der Modellüberlegung (`trim.py:153-160`). Abgelaufene Inhalte werden **nicht gespillt** — ein archiviertes, veraltetes `git status` ist wertlos, ein erneuter Aufruf liefert es sofort.

Die Prüffunktion ist `is_ephemeral(cmd)`, und sie **ist zugleich die Berechtigungsliste, die dem Koordinator zurückgegeben wird**: `delegate_guard(allow_glance=True)` benutzt dieselbe Funktion (`trim.py:63-68`, `:128-150`). Die beiden Mengen müssen immer identisch sein — erlaubt, aber nicht getrimmt, und ein veraltetes `git status` belegt den Kontext dauerhaft; getrimmt, aber nicht erlaubt, und der Koordinator schickt für ein `ls` einen subagent los, 4.3k Startkosten für ein paar Dutzend Zeichen. Ein Kommando in die Whitelist aufzunehmen heißt, beide Aussagen gleichzeitig zu treffen.

**Wann was**:

- Du willst nur, dass Reste abgerissener Verbindungen nicht in den Kontext kommen → nichts tun, `Runtime` ist standardmäßig ein `PruningSessionStore`. `trim=False` heißt nur, dass große Ergebnisse nicht getrimmt werden; das Prune läuft trotzdem.
- Lange Läufe, sehr große Tool-Ausgaben → `trim=True`. Im CLI des `go`-Pfads ist es bereits standardmäßig an, mit `--no-trim` schaltet man es gegenläufig ab.
- Der [Koordinator](glossary.md#协调者) hat `glance=True` → `ephemeral` muss angeschaltet bleiben, Begründung im Absatz davor.

### `PruningSessionStore` + `PrunePolicy` {#pruning-store}

```python
PruningSessionStore(path, workspace, policy: TrimPolicy | None = None,
                    prune: PrunePolicy | None = None,
                    ephemeral: EphemeralPolicy | None = None)
```

| Parameter | Typ | Default | Bedeutung |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Entfernt synthetische Nachrichten mit `isApiErrorMessage=true` oder `message.model == "<synthetic>"` |
| `neutralize_interrupts` | `bool` | `True` | Bei `tool_result` mit `[Request interrupted …]` wird **der Rumpf ersetzt, der Block nicht entfernt** |
| `interrupt_text` | `str` | `"[上一轮在此处被中断,该工具结果未产生]"` | Ersatztext für den vorigen Punkt |
| `keep_denials` | `int` | `1` | Behält die letzten N vom Permission-Hook abgelehnten Tool-Aufrufe; ältere werden **samt Aufruf und Ergebnis** entfernt |

`keep_denials` ist der einzige Konstruktorparameter von `Runtime`, der bis in diese Schicht durchgereicht wird (`Runtime(keep_denials=N)`). Warum 1 und nicht 0: Die jüngste Ablehnung ist ein nützliches Signal und verhindert, dass das Modell in derselben Runde wiederholt dasselbe blockierte Kommando probiert. **Nicht hochdrehen** — abgelehnte Aufrufe wurden nie ausgeführt, im Ergebnis steht keinerlei Information, gemessen belegt einer 273 Zeichen (93 Zeichen Ablehnungstext plus 180 Zeichen des toten Kommandos), und er **wirkt irreführend**: Gemessen hört der Koordinator, nachdem er einige Male „nicht direkt Bash verwenden" gelesen hat, auf, überhaupt noch ein erlaubtes `git status` zu versuchen, und sagt stattdessen „Bash ist eingeschränkt, ich schicke einen Agent hin" (`prune.py:135-148`).

Drei strukturelle rote Linien; bei Verstoß meldet die API direkt einen Fehler:

1. **Der `tool_result`-Block selbst muss bleiben**, nur `content` darf ersetzt werden. Fehlt einer, gibt es „Missing Tool Result Block" (`trim.py:20-22`; `prune.py:79-92`).
2. **Einträge mit `isCompactSummary` / `isMeta` sind unantastbar** — sie sind die einzige Existenzform des wegkomprimierten Teils der Historie (`trim.py:179-181`).
3. **Wer einen Eintrag entfernt, muss dessen Kinder an dessen Vater hängen.** Das Transcript ist eine einfach verkettete Liste über `parentUuid`, das Harness läuft von den Blättern zurück; wo die Kette reißt, ist die gesamte davorliegende Historie weg (`prune.py:95-122`). Deshalb muss `relink()` die vollständige Liste **inklusive** der zu entfernenden Einträge bekommen und das Filtern selbst erledigen.

**In SQLite wird am Original kein Zeichen geändert** — die drei Schichten betreffen nur „die Fassung, die zurück ins Modell geht" (`trim.py:18`; `prune.py:8`).

## Resilience bei Netzausfall {#韧性}

Ein long-horizon Workflow läuft mehrere Stunden, da reißt das Netz zwangsläufig einmal ab. Das Standardverhalten ist schlecht: Im Moment des Abrisses schiebt das Harness eine synthetische Assistant-Nachricht ins Transcript (`model="<synthetic>"`, `isApiErrorMessage=true`) mit dem Rumpf `API Error: Can't reach the API server …`; sie wird zum Blatt der Session, beim späteren Resume wird sie als „das, was das Modell zuletzt gesagt hat" zurückgefüttert, und das Modell glaubt, es diskutiere über eine Netzstörung; außerdem mischt sie sich in `StepResult.text` und wandert über den Workflow in den Prompt des nächsten Schritts (`resilience.py:1-22`).

Die [Resilience](glossary.md#韧性)-Schicht tut drei Dinge, keines davon entbehrlich: Probe, Weiterlaufen statt Neuanfang, Fehler nicht in den Kontext.

### `Resilience`-Parameter {#resilience}

| Parameter | Typ | Default | Bedeutung |
|---|---|---|---|
| `enabled` | `bool` | `True` | Wird aus `Runtime(resilience=…)` übersetzt |
| `max_attempts` | `int` | `6` | Wie oft ein [Schritt](glossary.md#步骤) höchstens versucht wird, **inklusive des ersten Mals** |
| `base_delay` | `float` | `4.0` | Startwert des exponentiellen Backoff, Sekunden |
| `max_delay` | `float` | `120.0` | Obergrenze des Backoff, Sekunden |
| `probe_timeout` | `float` | `5.0` | Timeout einer einzelnen Probe, Sekunden |
| `probe_interval` | `float` | `15.0` | Abstand zwischen Proben bei Netzausfall, Sekunden |
| `max_offline_wait` | `float` | `3600.0` | Wie lange bei Netzausfall höchstens gewartet wird. Default 1 Stunde — was länger dauert, ist meist kein Zucken, sondern ein echter Schaden |
| `retry_unknown` | `bool` | `True` | Auch nicht klassifizierbare Fehler werden wiederholt. Die meisten unbekannten Fehler sind transient, und fatale Fehler sind bereits separat abgefangen |
| `resume_prompt` | `str` | `"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"` | Was dem Modell beim Weiterlaufen gesagt wird |

Backoff-Formel (`resilience.py:119-121`):

```python
min(base_delay * 2 ** (attempt - 1), max_delay) * (0.75 + random() * 0.5)
```

Also `±25%` Jitter, damit nicht im Moment der Netzwiederherstellung ein Schwung Prozesse gleichzeitig losstürmt. Mit den Defaults: erster Backoff 4 Sekunden (tatsächlich 3~5), zweiter 8 Sekunden (6~10), ab dem fünften gedeckelt bei 120 Sekunden (90~150).

### Probe-Strategie {#探针}

- **Geprüft wird host:port von `ANTHROPIC_BASE_URL`**, nicht `api.anthropic.com` (`resilience.py:67-72`). Bei eigenem Gateway sagt die Erreichbarkeit des Letzteren nichts über die des Ersteren aus.
- **Nur DNS plus TCP-Handshake**: `getaddrinfo`, dann `connect_tcp`, dann sofort schließen. Kein HTTP, keine Credentials, keine Kosten (`resilience.py:75-85`). Eine Probe muss kostenlos sein, sonst wird „bei Netzausfall alle 15 Sekunden proben" selbst zur Störung.
- Jeder Fehlschlag gilt als nicht erreichbar — es wird nicht unterschieden, ob DNS ausgefallen ist oder TCP abgelehnt wurde.
- `wait_online()` wartet blockierend: Bei Erreichbarkeit `True`, nach Ablauf von `max_offline_wait` `False`. Beim ersten Nicht-Erreichen wird eine Zeile gemeldet, `<host>:<port> 不可达,等待恢复(最多 60 分钟)`, bei Wiederherstellung eine weitere, `<host>:<port> 恢复,继续`, **dazwischen kein Geflacker** (`resilience.py:126-140`).

Die Credential-Probe vor dem Start ist etwas anderes: Sie schickt tatsächlich einmal `POST <BASE_URL>/v1/messages` mit `max_tokens=16`, Timeout standardmäßig 20 Sekunden (`env.py:126-181`). `max_tokens` **nicht auf 1 setzen** — gemessen bringen Modelle mit erzwungener Gedankenkette nicht einmal das Denken unter, der Server quält sich 30 Sekunden lang bis zur Antwort; mit 16 sind es nur 3.6 Sekunden (`env.py:120-123`).

### Fehlerklassifikation {#错误分类}

`classify(text)` gibt eines von drei Ergebnissen zurück. **Zuerst auf fatal prüfen**: In Texten wie 401 tauchen oft auch Wörter wie „connection" auf; dreht man die Reihenfolge um, wartet man ewig (`resilience.py:53-64`).

| Klasse | Was trifft (Regex siehe `resilience.py:37-50`) | Verhalten |
|---|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` | Sofort stoppen, kein Retry. Egal wie oft wiederholt, das Ergebnis bleibt gleich, und jedes Mal kostet es Geld |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `timeout`, `service unavailable` | Warten, bis das Netz zurück ist, dann per Resume weiterlaufen |
| `unknown` | trifft nichts davon | Bei `retry_unknown=True` (Default) wird ebenfalls wiederholt |

Wiederholbar von nicht wiederholbar zu trennen ist der Kern dieser Schicht: **Netzzucken soll man abwarten, falsche Credentials sofort abbrechen** — bei Netzausfall zu warten ist richtig, bei falsch geschriebenem Key zu warten heißt Zeit verbrennen.

### Was aus dem Kontext herausgehalten wird {#错误不进上下文}

1. **Synthetische Fehlermeldungen.** `PruningSessionStore` entfernt sie beim `load` komplett und hängt `parentUuid` neu (`prune.py:27-32`, `:191-195`). **In SQLite bleiben sie unverändert erhalten**, sie werden nur nicht zurückgefüttert.
2. **Im Eventstrom haben sie `kind="error"` statt `"text"`**, gehen also nicht in `StepResult.text` und wandern damit auch nicht über den Workflow in den Prompt des nächsten Schritts (`resilience.py:17-18`).
3. **`resume_prompt` enthält bewusst keinerlei Fehlerdetails.** Das Modell muss wissen „du wurdest unterbrochen, mach weiter", nicht ob es `ENOTFOUND` oder `503` war. **Das gehört ins Log, nicht in den Kontext** (`resilience.py:112-113`). Fürs Log siehe das Feld `errors` in `manifest.json`.

Weiterlaufen statt Neuanfang: Wenn der Fehler auftritt, ist die `session_id` bereits vorhanden; per Resume wird an der Unterbrechungsstelle angeknüpft, die bisherigen Kosten sind nicht umsonst.

## Verwandt {#相关}

- [Kommandozeile](cli.md) — wie jeder Schalter auf die Konfiguration dieser Seite abgebildet wird.
- [Python API](api.md) — vollständige Signaturen von `Runtime`, den drei Stores und `Resilience`.
- [Deployment](deploy.md) — im Container laufen lassen, fachliche Fähigkeiten per Plugin ausliefern.
- [Glossar](glossary.md) — die genaue Bedeutung jedes hier verwendeten Begriffs.
