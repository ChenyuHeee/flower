# Installation

Für flower braucht es nur Python ≥ 3.10. Es gibt genau eine Laufzeitabhängigkeit, `claude-agent-sdk` — das native Binary, das die Requests verschickt, steckt in dessen Wheel. Also **kein Node und kein Claude Code CLI nötig**. Diese Seite geht einmal bei null los: Ein-Zeilen-Installation, Installation aus dem Quellcode, das erste Einrichten der Credentials und ein Befehl, der beweist, dass es „wirklich richtig installiert" ist. Wenn das läuft, weiter zum [Schnellstart](quickstart.md).

## Vorher: Python prüfen

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Eine Ausgabe wie `True 3.13.7` reicht. Kommt `False` heraus oder gibt es gar kein `python3`, erst eins installieren (`brew install python` / `apt install python3`) — sonst bricht das Installationsskript sofort ab.

| Gebraucht | Nicht gebraucht |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31` prüft es noch einmal selbst) | Node.js |
| Netzwerkzugang zum API-Endpunkt | Claude Code CLI |
| Ein API-Key oder Gateway-Token (kommt nach der Installation) | Einstellungen in `~/.claude/` auf dem Host (Credentials sind die einzige Ausnahme, siehe unten) |

Paketname `flower`, Version `0.1.0`, einzige Laufzeitabhängigkeit `claude-agent-sdk>=0.2.152` (`pyproject.toml:2-6`). `mkdocs-material` wird nur benutzt, wenn die CI die Doku-Site baut; zum Betrieb von flower braucht man es nicht.

## Installation in einer Zeile

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Danach sieht das Terminal ungefähr so aus (Farben weggelassen):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

Entscheidend ist die Zeile `== 装好了 <absoluter Pfad>` — sie ist das Ergebnis eines `command -v flower`, das das Skript selbst ausführt (`install.sh:60-61`). Wird ein Pfad ausgegeben, liegt `flower` bereits im PATH.

### Was der Installer tatsächlich tut

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) macht genau drei Dinge: einen Python-Installer auswählen, von GitHub installieren, dir den nächsten Schritt nennen. **An deine Credentials rührt es kein Stück** (`install.sh:7-8`). Die Installationsquelle ist fest `git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

Der Installer probiert der Reihe nach durch und hört beim ersten Erfolg auf (`install.sh:33-57`):

| Reihenfolge | Bedingung | Tatsächlicher Befehl | Wo die ausführbare Datei landet |
|---|---|---|---|
| 1 | `uv` liegt im PATH | `uv tool install --force <REPO>` | uv-Tool-Bin-Verzeichnis, meist `~/.local/bin/flower` |
| 2 | Kein `uv`, aber `pipx` | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | Weder noch | Erst `curl -LsSf https://astral.sh/uv/install.sh \| sh` für uv; klappt das, zurück zu Fall 1 | wie Fall 1 |
| 4 | uv ließ sich auch in Fall 3 nicht installieren | `python3 -m pip install --user --upgrade <REPO>` | Skriptverzeichnis des Benutzers — **auf macOS nicht `~/.local/bin`** |

Alle vier Wege installieren dasselbe Console Script: `flower = "flower.cli:main"` (`pyproject.toml:12`). Danach lässt es sich genauso über `python -m flower.cli` aufrufen (`cli.py:1263-1264`).

!!! warning "Ein erneuter Lauf des Skripts überschreibt erzwungenermaßen, ohne Rückfrage"
    Die drei Installationsbefehle tragen `--force`, `--force` bzw. `--upgrade` (`install.sh:37`, `:40`, `:54`). Ein zweiter Lauf überbügelt eine bestehende Installation einfach — genau so aktualisiert man, aber erwarte keine Nachfrage.

### Wie der Befehl `flower` in den PATH kommt

Findet `command -v flower` nichts, weist das Skript darauf hin, `$HOME/.local/bin` in `~/.zshrc` oder `~/.bashrc` einzutragen (`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`uv tool install` und `pipx install` legen beide dort ab, für sie stimmt der Hinweis. **Für den vierten Weg (`pip install --user`) aber nicht zwingend** — das Verzeichnis in diesem Hinweis ist hart codiert, während pips Benutzer-Skriptverzeichnis plattformabhängig ist. Auf macOS ist es `~/Library/Python/3.13/bin`. Selbst nachsehen:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

Ausgabe etwa `/Users/you/Library/Python/3.13/bin` — dieses Verzeichnis in den PATH aufnehmen, nicht `~/.local/bin`, dann Terminal neu öffnen oder `source` ausführen.

## Installation aus dem Quellcode

Wer den Code lesen, das Framework ändern oder die Offline-Prüfungen unter `tests/` laufen lassen will, installiert aus dem Quellcode:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

Danach sollte `.venv/bin/flower --help` die Usage-Zeilen ausgeben.

Der Shebang der ausführbaren Datei im venv ist ein **absoluter Pfad**; man muss also nichts aktivieren, ein Symlink genügt, und der Befehl funktioniert aus jedem Verzeichnis:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Liegt `~/.local/bin` im PATH, führt ein `flower` aus einem beliebigen Projektverzeichnis stets diesen venv-Interpreter und diesen Quellcode aus.

Die Quellcode-Installation bringt einen zusätzlichen Ablageort für Credentials mit: **die `.env` im Repo-Wurzelverzeichnis** (Platz 5 in der Suchreihenfolge, siehe [Konfiguration · Suchreihenfolge der Credentials](../reference/config.md#凭证查找优先级)). Beim Entwickeln:

```bash
cp .env.example .env        # ANTHROPIC_AUTH_TOKEN eintragen
```

`.env` steht bereits in `.gitignore` und landet nicht im Versionsverwaltungssystem. Ein über pip / pipx / uv installiertes flower hat diesen Ort **nicht** — es liegt in site-packages, es gibt keine „Repo-Wurzel". Für diese Installationsart also die globale Credentials-Datei unten benutzen.

## Erster Lauf: Credentials einrichten

Die drei Einstiegspunkte `go`, `run` und `once` rufen alle zu Beginn `ensure_credentials()` auf (`cli.py:1013`, `:981`, `:1046`), zwei Prüfungen:

1. **Gibt es welche?** — Suche nach Priorität; wird nichts gefunden, wird sofort gefragt.
2. **Funktionieren sie?** — Ein echter API-Aufruf. Ein Minimal-Request mit `max_tokens=16` (`env.py:120-123`), praktisch kostenlos. Ein abgelaufener Token oder eine falsch geschriebene Gateway-Adresse lässt sich an Umgebungsvariablen allein nicht erkennen; ohne Probe fliegt es einem erst Minuten später um die Ohren.

Ohne Credentials bleibt der erste `flower`-Lauf an dieser Oberfläche stehen (`cli.py:1179-1209`):

```text
== 配置 flower ========================================
第一次用?给一次凭证就行。
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   >

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   >

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   >

+ 存好了:/Users/you/.config/flower/.env
```

Frage 1 ist Pflicht; bleibt sie leer, erscheint rot `没给 token,取消。` und das Programm beendet sich. Fragen 2 und 3 lassen sich mit Enter überspringen. Beim offiziellen Endpunkt Frage 2 leer lassen; bei einem Drittanbieter-Gateway dessen Wurzeladresse eintragen, **ohne `/v1`** — flowers Probe geht an `<BASE_URL>/v1/messages` (`env.py:162`).

Die nach dem Ausfüllen geschriebenen Schlüssel (`cli.py:1199-1207`):

| Deine Eingabe | Geschriebener Schlüssel in `.env` |
|---|---|
| Token beginnt mit `sk-ant-` | `ANTHROPIC_API_KEY` |
| Anderer Token | `ANTHROPIC_AUTH_TOKEN` |
| Gateway-Adresse nicht leer | `ANTHROPIC_BASE_URL` |
| Modellname nicht leer | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` — **alle drei zusammen** |

Der Dateiort ist `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), die Datei wird **komplett überschrieben** und anschließend mit `chmod 0o600` versehen (`cli.py:1157-1168`). Das ist die Datei hinter „einmal einrichten, überall wirksam" — beim Wechsel des Projektverzeichnisses ist keine Neukonfiguration nötig. Die Bedeutung jeder Variablen steht unter [Konfiguration](../reference/config.md#环境变量).

### Ist Claude Code lokal installiert, kommt womöglich gar keine Frage

Die Credential-Suche hat einen **letzten Rückfall**: Sie liest `~/.claude/settings.json`, danach `~/.claude/settings.local.json` und entnimmt deren `env`-Blöcken 9 Credential-Schlüssel (`env.py:56-75`, `:109-111`). Wer Claude Code lokal bereits eingerichtet hat, kann direkt `flower` starten und loslegen; die Konfigurationsoberfläche erscheint gar nicht — genau damit wirbt `install.sh:77`.

!!! warning "Die Aussage im Produkt, „flower liest ~/.claude/settings.json nicht", ist falsch"
    Findet flower überhaupt keine Credentials, lautet die letzte Zeile der ausgegebenen Fehlermeldung
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`, der Satz steht in `:192`). **Maßgeblich ist der Code: Es liest sie.**
    `env.py:56-75` liest ausdrücklich die `env`-Blöcke dieser beiden Dateien, nimmt daraus aber nur 9 Credential-Schlüssel und übernimmt keine sonstigen Einstellungen. Schließe aus diesem Satz nicht, die lokale Claude-Code-Konfiguration werde ignoriert. Die vollständige Kette steht unter [Konfiguration · Suchreihenfolge der Credentials](../reference/config.md#凭证查找优先级).

### Wenn du neu konfigurieren willst

Das Unterkommando `flower setup` ist registriert (`cli.py:1147-1149`), fehlt aber in `_CMDS` (`cli.py:758`). Deshalb wird `flower setup` zu `flower go setup` umgeschrieben — „setup" wird als Anliegen behandelt und der komplette Workflow einmal durchlaufen. **Derzeit erreicht keine Kommandozeilenform dieses Unterkommando**, obwohl mehrere Fehlermeldungen weiterhin dazu auffordern. Zum Ändern der Credentials:

```bash
$EDITOR ~/.config/flower/.env
```

Oder den Token in dieser Datei löschen und `flower` erneut starten — die Prüfung auf fehlende Credentials fragt dann wieder nach (vorausgesetzt, an den anderen Orten liegt auch nichts, etwa in `~/.claude/settings.json`). Werden die Credentials abgelehnt (HTTP 401 / 403), erscheint dieselbe Oberfläche sofort zur Neukonfiguration, höchstens einmal (`cli.py:1229-1244`).

## Prüfen, ob die Installation sitzt

Zwei Stufen, von billig nach teuer.

**Stufe eins — ist der Befehl da (kostenlos)**:

```bash
flower --help
```

Erscheinen diese Zeilen, ist das Console Script installiert und liegt im PATH:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Stufe zwei — Credentials, Endpunkt und natives Binary funktionieren (ein paar Cent)**: Der billigste echte Lauf ist `once` — ein einzelner Agent, standardmäßig nur mit den drei lesenden Tools `Read` / `Glob` / `Grep`, ohne [Goal guard](../reference/glossary.md#目标看守), ohne [Workbench](../reference/glossary.md#工作台):

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` gibt **vor** dem Start die aktuell wirksame Konfiguration aus, vom Token bleiben nur die ersten 4 Zeichen (`cli.py:1257-1259`; `env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

Diese Zeilen bestätigen, dass kein falsches Gateway angesprochen wird. Dann folgen die Credential-Probe und der eigentliche Lauf:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**Kein Step-Header.** `once` geht über `_run_once` → `rt.run()`, nicht über `_drive` / `Workflow.run`, und `Event("step", …)` wird nur in `workflow/base.py:220` ausgelöst — Trennzeilen wie `== 步骤名 ===== 1/1` tauchen unter `once` also nicht auf, sondern nur bei `go` / `run`.

**Erscheint die Zeile `+ 完成`, ist der Test bestanden.** Sie belegt zugleich drei Dinge: Die Credentials funktionieren, der Endpunkt ist erreichbar, und das native Binary im `claude-agent-sdk`-Wheel läuft auf dieser Maschine. Steht unter `- 验一下凭证…` stattdessen `! 凭证被拒` oder `! 网关地址或模型名不对`, weiter zur Fehlertabelle unten.

!!! note "Bei `once` werden Dauer und kumulierte Kosten als 0 angezeigt"
    `once` erzeugt für jedes Event einen neuen Renderer (`cli.py:1060`, `:579-581`), deshalb ist `用时` konstant `0:00` und das `累计 $` in der Statuszeile summiert sich nie — **die Kosten des einzelnen Schritts stimmen, die Zeit nicht**.

    Das `1 轮 · $0.1741` oben ist eine **belegte Messung**: am 2026-09-06 in einem Linux/arm64-Container, ein echter Request über `cloud.infini-ai.com/maas` (`docker/README.md:24-25`), also der **Bodenpreis einer einzelnen Runde** mit Opus 5 + 1M-Fenster. Führst du den Befehl oben selbst aus, wird das Repo gelesen, es fallen mehr Runden an, und die Kosten liegen etwas über diesem Bodenpreis. Die vollständige Abrechnung steht in `runs/manifest.json`, siehe [Konfiguration · Verzeichnisstruktur](../reference/config.md#磁盘布局).

## Wenn die Installation scheitert

| Symptom | Ursache | Was tun |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Weder `python3` noch `python` erfüllen 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3`, dann das Skript erneut ausführen |
| Skript meldet Erfolg, aber `flower: command not found` | Installation in ein Verzeichnis außerhalb des PATH | Siehe oben „Wie der Befehl `flower` in den PATH kommt". Beim Weg über `pip --user` ist es auf macOS `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | Alle Wege fehlgeschlagen, meist keine Netzwerkverbindung zu GitHub oder PyPI | Den Befehl wie vorgeschlagen manuell ausführen und den echten Fehler ansehen |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 Zeilen) | Keine Credentials in einer nicht-interaktiven Umgebung (Pipe, CI, `nohup`) — dort erscheint keine Konfigurationsoberfläche, es wird direkt beendet | Zuerst einmal in einem echten Terminal `flower` ausführen und einrichten, oder `~/.config/flower/.env` direkt schreiben |
| `! 凭证被拒:HTTP 401 …` | Token abgelaufen oder falsch | Im interaktiven Terminal folgt sofort die Neukonfiguration; nicht-interaktiv wird beendet |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` oder Modellname falsch | BASE_URL bis zur Gateway-Wurzel, ohne `/v1`; als Modellname den des Gateways verwenden |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / Timeout / 5xx | **Kein Credential-Problem**; flower verlangt hier bewusst keine Neukonfiguration, startet normal und überlässt es der [Resilienz](../reference/glossary.md#韧性)-Schicht |
| `! 标准输入不是终端,没人能回答提问` | Lauf in einer Pipe oder in der CI | `--timeout 0` ergänzen, damit selbst entschieden wird, statt auf jemanden zu warten |
| `flower setup` startet und fragt „was soll getan werden" | `setup` fehlt in `_CMDS` (`cli.py:758`) | `~/.config/flower/.env` direkt bearbeiten, siehe oben „Wenn du neu konfigurieren willst" |

## Nächste Schritte

- [Schnellstart](quickstart.md) — in ein Projektverzeichnis wechseln und die erste echte Aufgabe durchziehen.
- [Konfiguration](../reference/config.md) — alle Umgebungsvariablen, Credential-Priorität, `.env`-Syntax, was auf der Platte zurückbleibt.
- [Kommandozeile](../reference/cli.md) — alle Unterkommandos und Schalter.
- [Deployment](../reference/deploy.md) — im Container laufen lassen, Domänenfähigkeiten per Plugin verteilen.
- [Glossar](../reference/glossary.md) — die genaue Bedeutung jedes Begriffs in dieser Doku.
