# Installation

Für flower braucht es nur Python ≥ 3.10. Die einzige Laufzeit-Abhängigkeit ist `claude-agent-sdk` — die native Binary, die die Requests absetzt, steckt in dessen Wheel. Also **kein Node, kein Claude Code CLI**. Diese Seite geht einmal bei null los: Installation in einer Zeile, Installation aus dem Quellcode, das erste Einrichten der Credentials und ein Kommando, das beweist, dass „es wirklich richtig installiert ist". Danach weiter zum [Schnelleinstieg](quickstart.md).

## Vor der Installation: Python prüfen {#装之前确认-python}

```bash
python3 -c 'import sys; print(sys.version_info >= (3, 10), sys.version.split()[0])'
```

Eine Ausgabe wie `True 3.13.7` reicht. Kommt `False` oder gibt es gar kein `python3`, installiere erst eines (`brew install python` / `apt install python3`), sonst bricht das Installationsskript sofort ab.

| Erforderlich | Nicht erforderlich |
|---|---|
| Python ≥ 3.10 (`pyproject.toml:5`; `install.sh:22-31` prüft es noch einmal selbst) | Node.js |
| Netzwerkzugang zum API-Endpunkt | Claude Code CLI |
| Ein API-Key oder Gateway-Token (kommt nach der Installation) | Einstellungen unter `~/.claude/` auf dem Host (Credentials sind die einzige Ausnahme, siehe unten) |

Paketname `flower`, Version `0.1.0`, einzige Laufzeit-Abhängigkeit `claude-agent-sdk>=0.2.152` (`pyproject.toml:2-6`). `mkdocs-material` wird nur in der CI zum Bauen der Doku-Site gebraucht, für den Betrieb von flower nicht.

## Installation in einer Zeile {#一句话安装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Danach sollte im Terminal ungefähr das stehen (Farben weggelassen):

```text
== 用 uv 安装 flower…

== 装好了 /Users/you/.local/bin/flower

下一步:
  cd 到任意项目目录,然后:  flower
  第一次会问你要 API key / 网关地址,配一次存到 ~/.config/flower/.env,处处生效。
  本机已经装了 Claude Code 并配好的话,flower 会直接借它的 token,连问都不问。

  文档:https://chenyuheee.github.io/flower/
```

Entscheidend ist die Zeile `== 装好了 <absoluter Pfad>` — sie ist das Ergebnis eines `command -v flower`, das das Skript selbst ausgeführt hat (`install.sh:60-61`). Wird ein Pfad ausgegeben, liegt `flower` bereits im PATH.

### Was der Installer tatsächlich tut {#安装器实际做了什么}

[`install.sh`](https://github.com/ChenyuHeee/flower/blob/main/install.sh) macht genau drei Dinge: einen Python-Tool-Installer auswählen, von GitHub installieren, den nächsten Schritt nennen. **Deine Credentials fasst es mit keinem Zeichen an** (`install.sh:7-8`). Die Installationsquelle ist fest `git+https://github.com/ChenyuHeee/flower.git` (`install.sh:11`).

Der Installer probiert der Reihe nach durch und hört beim ersten Erfolg auf (`install.sh:33-57`):

| Reihenfolge | Auslöser | Tatsächliches Kommando | Wo die ausführbare Datei landet |
|---|---|---|---|
| 1 | `uv` liegt im PATH | `uv tool install --force <REPO>` | uv-Tool-bin-Verzeichnis, meist `~/.local/bin/flower` |
| 2 | Kein `uv`, aber `pipx` | `pipx install --force <REPO>` | `~/.local/bin/flower` |
| 3 | Weder noch | Erst uv per `curl -LsSf https://astral.sh/uv/install.sh \| sh` installieren, bei Erfolg zurück zu Punkt 1 | wie Punkt 1 |
| 4 | Auch in Punkt 3 klappt die uv-Installation nicht | `python3 -m pip install --user --upgrade <REPO>` | Benutzer-Skriptverzeichnis — **auf macOS nicht `~/.local/bin`** |

Alle vier Fälle installieren dasselbe Console Script: `flower = "flower.cli:main"` (`pyproject.toml:12`). Danach lässt es sich auch über `python -m flower.cli` aufrufen, mit identischer Wirkung (`cli.py:1451-1452`).

!!! warning "Ein erneuter Lauf des Installationsskripts überschreibt erzwungenermaßen, ohne Rückfrage"
    Die drei Installationskommandos tragen `--force`, `--force` bzw. `--upgrade` (`install.sh:37`, `:40`, `:54`). Ein erneuter Lauf überschreibt eine vorhandene Installation direkt — genau so aktualisiert man, aber erwarte keine Rückfrage.

### Wie das Kommando `flower` in den PATH kommt {#flower-命令怎么上-path}

Findet `command -v flower` nichts, weist das Skript darauf hin, `$HOME/.local/bin` in `~/.zshrc` oder `~/.bashrc` einzutragen (`install.sh:62-70`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`uv tool install` und `pipx install` legen beide dorthin ab, für sie stimmt der Hinweis. **Für den vierten Weg (`pip install --user`) aber nicht zwangsläufig** — das Verzeichnis in diesem Hinweis ist fest verdrahtet, während pips Benutzer-Skriptverzeichnis plattformabhängig ist. Auf macOS ist es `~/Library/Python/3.13/bin`. Selbst nachsehen:

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', 'posix_user'))"
```

Ausgabe etwa `/Users/you/Library/Python/3.13/bin` — trage dieses Verzeichnis in den PATH ein, nicht `~/.local/bin`, und öffne danach das Terminal neu oder mache ein `source`.

## Aus dem Quellcode installieren {#从源码装}

Wer den Code lesen, das Framework ändern oder die Offline-Prüfungen in `tests/` laufen lassen will, installiert aus dem Quellcode:

```bash
git clone https://github.com/ChenyuHeee/flower.git
cd flower
python3 -m venv .venv
.venv/bin/pip install -e .
```

Danach sollte `.venv/bin/flower --help` die Usage-Zeilen ausgeben.

Der Shebang der ausführbaren Datei im venv ist ein **absoluter Pfad**, deshalb muss man nicht aktivieren; ein Symlink genügt, um sie in jedem Verzeichnis zu nutzen:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Liegt `~/.local/bin` im PATH, dann laufen bei einem `flower` in einem beliebigen Projektverzeichnis immer der Interpreter aus diesem venv und dieser Quellcode.

Die Quellcode-Installation bietet einen zusätzlichen Ablageort für Credentials: **die `.env` im Repository-Root** (Platz 5 in der Suchreihenfolge, siehe [Konfiguration · Prioritätsreihenfolge der Credential-Suche](../reference/config.md#凭证查找优先级)). Für die Entwicklung:

```bash
cp .env.example .env        # ANTHROPIC_AUTH_TOKEN eintragen
```

`.env` steht bereits in `.gitignore` und landet nicht im Repository. Ein über pip / pipx / uv installiertes flower hat diesen Ort **nicht** — es liegt in site-packages, dort gibt es keinen „Repository-Root". Für diese Installationsart gilt also die globale Credential-Datei weiter unten.

## Automatische Updates {#自动更新}

flower iteriert noch schnell, deshalb **aktualisiert sich die per pip / pipx / uv installierte Variante standardmäßig selbst**: Wer einen Bug aus einer drei Tage alten Version meldet, meldet womöglich etwas längst Behobenes — Zeitverschwendung auf beiden Seiten. Es gibt hier keine Schalterfrage „einschalten oder nicht" — standardmäßig an, abschalten über eine Umgebungsvariable.

Was es tut (`update.py:116-129`):

1. Bei jedem Start von `flower` wird in einem **Hintergrund-Thread** einmal der neueste Commit von `main` auf GitHub abgefragt (`update.py:70-80`). Der Hauptablauf wartet keine Sekunde — das ist die erste Invariante.
2. Weicht er vom lokal installierten Commit ab, läuft ein Update-Kommando passend zur ursprünglichen Installationsart: mit `uv` ein `uv tool install --force`, mit `pipx` ein `pipx install --force`, sonst `pip install --user --upgrade` (`update.py:83-93`).
3. **Auch nach erfolgreicher Installation wird der laufende Prozess nicht ersetzt** — die neue Version greift erst beim nächsten `flower`-Lauf (`update.py:113`). Mitten im Lauf ausgetauscht zu werden ist eine der am schwersten zu diagnostizierenden Fehlerklassen.
4. Drosselung: höchstens eine Abfrage pro 24 Stunden, der Zeitstempel liegt in `~/.config/flower/.update` (`update.py:32`, `:36-37`, `:124`).
5. **Fehler bleiben ausnahmslos still.** Kein Netz, GitHub down, Installation schlägt fehl — nichts davon unterbricht deine Arbeit (`update.py:79`, `:108-110`).

**Aus dem Quellcode (git) betriebene Installationen sind nicht betroffen.** Der Update-Schritt prüft zuerst, ob im Repository ein `.git` liegt; wenn ja, gibt er direkt `None` zurück und tut nichts (`update.py:83-87`) — dein Arbeitsverzeichnis gehört `git`, nicht ihm. Nicht-interaktive Läufe (stdin ist kein Terminal, z. B. Pipe / CI) werden komplett übersprungen (`update.py:121`).

Zum Abschalten:

```bash
export FLOWER_NO_UPDATE=1
```

Jeder nicht-leere Wert zählt (`update.py:33`, `:121`). Nützlich in CI, in Offline-Umgebungen und wenn du das Verhalten einer alten Version reproduzieren willst.

## Der erste Lauf: Credentials einrichten {#第一次跑配凭证}

Die drei Einstiegspunkte für echte Läufe — `go`, `run`, `once` — rufen alle zu Beginn `ensure_credentials()` auf (`cli.py:1192`, `:1160`, `:1225`), mit zwei Hürden:

1. **Vorhanden?** — die Prioritätsreihenfolge wird einmal durchsucht; findet sich nichts, wirst du direkt gefragt.
2. **Funktionieren sie?** — es geht ein echter API-Aufruf raus. Ein minimaler Request mit `max_tokens=16` (`env.py:120-123`), praktisch kostenlos. Abgelaufene Tokens und falsch geschriebene Gateway-Adressen sieht man den Umgebungsvariablen nicht an; ohne diese Probe fliegt es erst Minuten später auseinander.

Ohne Credentials bleibt der erste `flower`-Lauf bei dieser Oberfläche stehen (`cli.py:1358-1388`):

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

Frage 1 ist Pflicht; bleibt sie leer, erscheint rot `没给 token,取消。` und das Programm beendet sich. Bei Frage 2 und 3 genügt Enter. Beim offiziellen Endpunkt lässt du Frage 2 leer; bei einem Drittanbieter-Gateway trägst du dessen Wurzeladresse ein, **ohne `/v1`** — flowers Probe geht an `<BASE_URL>/v1/messages` (`env.py:162`).

Die daraus geschriebenen Schlüssel (`cli.py:1378-1386`):

| Deine Eingabe | Schlüssel in der `.env` |
|---|---|
| Token beginnt mit `sk-ant-` | `ANTHROPIC_API_KEY` |
| Anderes Token | `ANTHROPIC_AUTH_TOKEN` |
| Gateway-Adresse nicht leer | `ANTHROPIC_BASE_URL` |
| Modellname nicht leer | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` — **alle drei zusammen** |

Der Dateipfad ist `${XDG_CONFIG_HOME:-~/.config}/flower/.env` (`env.py:39-42`), die Datei wird **vollständig überschrieben** und danach mit `chmod 0o600` versehen (`cli.py:1336-1347`). Das ist die Datei hinter „einmal einrichten, überall gültig" — beim Wechsel des Projektverzeichnisses ist keine neue Konfiguration nötig. Die Bedeutung der einzelnen Variablen steht unter [Konfiguration](../reference/config.md#环境变量).

### Ist Claude Code lokal installiert, kommt womöglich keine einzige Frage {#本机装过-claude-code-的话可能一个问题都不问}

Die Credential-Suche hat einen **letzten Rückfall**: Sie liest `~/.claude/settings.json` und danach `~/.claude/settings.local.json` und entnimmt deren `env`-Blöcken 9 Credential-Schlüssel (`env.py:56-75`, `:109-111`). Wer Claude Code lokal bereits eingerichtet hat, kann direkt mit `flower` loslegen; die Konfigurationsoberfläche erscheint gar nicht — genau das bewirbt `install.sh:77`.

!!! warning "Die Aussage im Produkt, „flower liest ~/.claude/settings.json nicht", ist falsch"
    Findet sich überhaupt kein Credential, lautet die letzte Zeile der von flower ausgegebenen Fehlermeldung
    `flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。`
    (`env.py:184-194`, der Satz steht in `:192`). **Maßgeblich ist der Code: Es liest sie.**
    `env.py:56-75` liest die `env`-Blöcke dieser beiden Dateien ausdrücklich aus, entnimmt aber nur 9 Credential-Schlüssel und übernimmt sonst keinerlei Einstellungen. Wenn du diesen Satz liest, schließe daraus nicht, deine lokale Claude-Code-Konfiguration werde ignoriert. Die vollständige Kette steht unter [Konfiguration · Prioritätsreihenfolge der Credential-Suche](../reference/config.md#凭证查找优先级).

### Wenn du neu konfigurieren willst {#想重新配的时候}

Das Unterkommando `flower setup` ist zwar registriert (`cli.py:1326-1328`), fehlt aber in `_CMDS` (`cli.py:937`). Deshalb wird `flower setup` zu `flower go setup` umgeschrieben — „setup" wird als Anliegen genommen und einmal der komplette Workflow gefahren. **Derzeit gibt es keine Kommandozeilen-Schreibweise, die dieses Unterkommando erreicht**, obwohl mehrere Fehlermeldungen dich weiterhin dorthin schicken. Zum Ändern der Credentials:

```bash
$EDITOR ~/.config/flower/.env
```

Oder das Token aus dieser Datei löschen und `flower` erneut starten — die Hürde „Credential fehlt" fragt dann neu (vorausgesetzt, es liegt auch an keinem anderen Ort etwas, etwa in `~/.claude/settings.json`). Werden die Credentials abgelehnt (HTTP 401 / 403), erscheint dieselbe Oberfläche ebenfalls sofort zum Neukonfigurieren, mit höchstens einem Versuch (`cli.py:1416-1428`).

## Prüfen, ob die Installation sitzt {#验证装好了没有}

Zwei Stufen, von billig nach teuer.

**Stufe eins — ist das Kommando da (kostet nichts)**:

```bash
flower --help
```

Diese Zeilen bedeuten: Das Console Script ist installiert und liegt im PATH:

```text
usage: flower [-h] [-w WORKSPACE] [-r RUN_DIR] [-v] [-W] [-T]
              {go,run,once,setup} ...

可移植长程 agent 框架
```

**Stufe zwei — Credentials, Endpunkt und native Binary funktionieren (ein paar Cent)**: Der billigste echte Lauf ist `once` — ein einzelner Agent, standardmäßig nur die drei lesenden Werkzeuge `Read` / `Glob` / `Grep`, ohne [Goal Guard](../reference/glossary.md#目标看守), ohne [Workbench](../reference/glossary.md#工作台):

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

`-v` gibt **vor** dem Start die aktuell wirksame Konfiguration aus, vom Token bleiben nur die ersten 4 Stellen (`cli.py:1445-1447`; `env.py:197-211`):

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 108 位)
ANTHROPIC_BASE_URL = https://cloud.infini-ai.com/maas
ANTHROPIC_MODEL = claude-opus-5[1m]
```

Diese Zeilen bestätigen, dass du nicht am falschen Gateway hängst. Danach folgen die Credential-Probe und der eigentliche Lauf:

```text
- 验一下凭证…
  * Read /path/to/any/repo/README.md
  这个仓库是……
  + 完成 1 轮 · $0.1741 · 用时 0:00
```

**Kein Step-Header.** `once` geht über `_run_once` → `rt.run()`, nicht über `_drive` / `Workflow.run`, und `Event("step", …)` wird nur in `workflow/base.py:220` ausgelöst — Trennzeilen wie `== 步骤名 ===== 1/1` tauchen unter `once` also nicht auf, nur bei `go` / `run`.

**Erscheint die Zeile `+ 完成`, hast du bestanden**; sie belegt gleichzeitig dreierlei: Die Credentials funktionieren, der Endpunkt ist erreichbar, und die native Binary im `claude-agent-sdk`-Wheel läuft auf dieser Maschine. Steht unter `- 验一下凭证…` stattdessen `! 凭证被拒` oder `! 网关地址或模型名不对`, siehe die Fehlertabelle weiter unten.

!!! note "Bei `once` werden Laufzeit und kumulierte Kosten als 0 angezeigt"
    `once` legt für jedes Event einen neuen Renderer an (`cli.py:1239`, `:579-581`), deshalb steht `用时` konstant auf `0:00` und das `累计 $` in der Statuszeile summiert sich nie — **die Kosten des einzelnen Schritts sind echt, die Zeit nicht**.

    Das `1 轮 · $0.1741` oben ist eine **belegte Messung**: am 2026-09-06 in einem Linux/arm64-Container, ein echter Request über `cloud.infini-ai.com/maas` (`docker/README.md:24-25`), also der **Bodenpreis einer einzelnen Runde** mit Opus 5 + 1M-Fenster. Wenn du das Kommando oben selbst laufen lässt, wird ein Repository gelesen, es fallen mehr Runden an, und die Kosten liegen etwas über diesem Bodenpreis. Die vollständige Abrechnung steht in `runs/manifest.json`, siehe [Konfiguration · Verzeichnisaufbau auf der Platte](../reference/config.md#磁盘布局).

## Wenn die Installation scheitert {#装不上的时候}

| Symptom | Ursache | Was tun |
|---|---|---|
| `需要 Python 3.10+。先装一个…` | Weder `python3` noch `python` erfüllen 3.10+ (`install.sh:31`) | `brew install python` / `apt install python3`, dann das Skript erneut laufen lassen |
| Skript meldet Erfolg, aber `flower: command not found` | Installation landete in einem Verzeichnis außerhalb des PATH | Siehe oben „Wie das Kommando `flower` in den PATH kommt". Beim Weg über `pip --user` ist es auf macOS `~/Library/Python/3.X/bin` |
| `安装失败。手动试:uv tool install git+https://…` | Alle Wege fehlgeschlagen, meist keine Netzverbindung zu GitHub oder PyPI | Laut Hinweis manuell einmal ausführen und den echten Fehler ansehen |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。` (4 Zeilen) | Keine Credentials in nicht-interaktiver Umgebung (Pipe, CI, `nohup`) — dort erscheint keine Konfigurationsoberfläche, es wird direkt beendet | Erst einmal in einem echten Terminal `flower` laufen lassen und einrichten, oder direkt `~/.config/flower/.env` schreiben |
| `! 凭证被拒:HTTP 401 …` | Token abgelaufen oder falsch geschrieben | Im interaktiven Terminal kannst du sofort neu konfigurieren; nicht-interaktiv wird beendet |
| `! 网关地址或模型名不对:HTTP 404 …` | `ANTHROPIC_BASE_URL` oder Modellname falsch | BASE_URL bis zur Gateway-Wurzel schreiben, ohne `/v1`; als Modellnamen die Namensgebung des Gateways verwenden |
| `(探针没打通:… —— 当作网络问题,照常开跑)` | DNS / TCP / Timeout / 5xx | **Kein Credential-Problem**; flower lässt dich bewusst nicht neu konfigurieren, startet normal und überlässt es der Ebene [Resilienz](../reference/glossary.md#韧性) |
| `! 标准输入不是终端,没人能回答提问` | Lauf in einer Pipe oder in CI | `--timeout 0` ergänzen, damit es selbst entscheidet und nicht auf Menschen wartet |
| `flower setup` startet und fragt „was zu tun ist" | `setup` fehlt in `_CMDS` (`cli.py:937`) | `~/.config/flower/.env` direkt bearbeiten, siehe oben „Wenn du neu konfigurieren willst" |

## Nächste Schritte {#下一步}

- [Schnelleinstieg](quickstart.md) — in ein Projektverzeichnis wechseln und die erste echte Aufgabe durchziehen.
- [Konfiguration](../reference/config.md) — alle Umgebungsvariablen, Credential-Priorität, `.env`-Syntax, was auf der Platte zurückbleibt.
- [Kommandozeile](../reference/cli.md) — alle Unterkommandos und Schalter.
- [Deployment](../reference/deploy.md) — im Container betreiben, Domänenfähigkeiten per Plugin verteilen.
- [Glossar](../reference/glossary.md) — die genaue Bedeutung jedes Begriffs in der Doku.
