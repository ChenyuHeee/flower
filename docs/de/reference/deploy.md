# Deployment und Erweiterung

Wer flower woandershin verpflanzt, hat drei Dinge zu erledigen: den Container (das uneingeschränkte Bash einzäunen — und nebenbei den Satz „ohne CLI" nachprüfen), das
[plugin](glossary.md#plugin) (Domänenfähigkeiten reisen mit dem Repository, unabhängig davon, was auf dem Host installiert ist) und die Dokumentationsseite (Push auf `main` veröffentlicht automatisch, `install.sh` hängt unter der Pages-Domain). Die drei Abschnitte sind voneinander unabhängig; lies, was du brauchst.

## Teil 1 — Container

### Warum ein Container

**Erstens: einzäunen.** Der arbeitende [Worker](glossary.md#执行者) hat **uneingeschränktes Bash** — flowers Bash-Whitelist (`delegate_guard`) gilt nur für den [Main-Thread](glossary.md#主线程); wer rausgeschickt wird, muss Tests laufen lassen können, das ist Absicht.
Im Container ist nur dein Projektverzeichnis gemountet, der Framework-Quellcode liegt im Image unter `/opt/flower`, vom Host ist sonst nichts sichtbar.

**Zweitens ist er selbst die Prüfung der Randbedingung [portabel](glossary.md#可移植).** Im Image gibt es keine Claude Code CLI, kein Node, nur Python und `claude-agent-sdk` — die Requests gehen über das native Binary raus, das im Wheel mitkommt.
Wenn es hier läuft, ist „ohne CLI" keine Behauptung auf dem Papier.

Praktisch verifiziert (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0):

| Was geprüft wurde | Ergebnis |
|---|---|
| Gibt es eine CLI im Image | `claude`, `node`, `npm`, `npx` **existieren alle nicht** |
| Mitgeliefertes Binary | `\177ELF` (207M) |
| Echter Request | über `cloud.infini-ai.com/maas` abgesetzt und Antwort erhalten, `$0.1741 / 1 Runde` (das ist der Bodenpreis einer einzelnen Runde mit Opus 5 + 1M-Fenster) |
| Dateieigentum | im Container nach `/work` geschriebene Dateien gehören auf dem Host `hechenyu:staff`, Mapping stimmt |
| Sichtbarkeit des Hosts | im Container `ls /Users` → `No such file or directory` |

### Was im Image installiert ist

Basis-Image `python:3.13-slim`, darauf installiert apt genau drei Pakete. Jedes hat einen Grund:

| Installiert | Warum |
|---|---|
| `python:3.13-slim` | Es braucht nur Python ≥ 3.10. Kein Node, keine claude CLI |
| `git` | `--isolate` muss jedem [subagent](glossary.md#subagent) ein Worktree geben |
| `ca-certificates` | HTTPS-Gateway |
| `libstdc++6` | Das mitgelieferte SDK-Binary ist eine mit Bun kompilierte Single-File-Datei und braucht sie unter Linux; das slim-Image bringt sie nicht mit |

Der Framework-Quellcode kommt per `COPY` ins Image, **nicht per bind mount** — deshalb kommt der Agent im Container nicht an den Framework-Quellcode auf dem Host:

| Pfad im Image | Inhalt | Woher |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, und hier `pip install .` | `COPY` |
| `/work` | Arbeitsverzeichnis (`WORKDIR`), zur Laufzeit wird das `$PWD` des Hosts hierher gemountet | `docker run -v` |

Der Einstiegspunkt ist `ENTRYPOINT ["flower"]`, `CMD` ist leer — läuft der Container ohne Argumente, landet man in der interaktiven Eingabe
(er fragt, was du willst), statt `--help` zu drucken. So muss man ein deutschsprachiges Anliegen nicht in der Shell in Anführungszeichen setzen.

### Warum sich das `.venv` des Hosts nicht hineinmounten lässt

Das SDK liefert Wheels pro Plattform aus, das mitgelieferte Binary ist plattformspezifisch:

```text
宿主   claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
       → _bundled/claude ist Mach-O 64-bit arm64, 191M
容器   claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Hineingemountet läuft es nicht, das Image muss also selbst `pip install` machen. Umgekehrt ist genau das der Beleg für Portabilität: dieselbe
`pyproject.toml`, bei Plattformwechsel ein anderes natives Binary, und keine Zeile Framework-Code muss sich ändern.

### Die zwei Skripte

| Skript | Was es tut |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | Baut das Image. `cd` in die Repo-Wurzel, `docker build -f docker/Dockerfile -t flower-box .`; bei `FLOWER_MIRRORS=1` (Standard) wird `python:3.13-slim` erst von einem Registry-Mirror geholt und umgetaggt, dazu kommen die `--build-arg` für pip / apt |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | Ein Lauf. Credential-Datei prüfen → prüfen, ob `$PWD` überhaupt gemountet werden kann → prüfen, ob ein TTY da ist → `docker run` |

Die Schalter von `docker/build` laufen ausschließlich über Umgebungsvariablen:

| Variable | Standard | Bedeutung |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | Image-Tag |
| `FLOWER_MIRRORS` | `1` | `0` = kein einziger Mirror wird ersetzt, alles geht upstream |
| `FLOWER_REGISTRY` | `dockerproxy.net` | Von hier das Basis-Image holen und auf `python:3.13-slim` umtaggen, damit `FROM` lokal trifft |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | Geht an `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | Geht an `--build-arg APT_MIRROR` |

Die letzten drei wirken nur bei `FLOWER_MIRRORS=1` — der Zweig `FLOWER_MIRRORS=0` setzt überhaupt kein build-arg.

`docker/flowerbox` kennt zwei:

| Variable | Standard | Bedeutung |
|---|---|---|
| `FLOWER_HOME` | eine Ebene über dem Skript selbst (also die Repo-Wurzel) | Wo `.env` gesucht wird. Fehlt `$FLOWER_HOME/.env`, wird direkt mit 1 beendet |
| `FLOWER_IMAGE` | `flower-box` | Welches Image läuft |

`FLOWER_HOME` wird aus der Position des Skripts abgeleitet, kein fest verdrahteter Pfad — egal wohin das Repository geklont wird, es funktioniert.

### Ausführen

```bash
docker/build                       # einmal reicht
cd ~/任意项目目录                   # muss unterhalb von $HOME liegen, siehe Mount-Grenzen unten
/path/to/flower/docker/flowerbox   # ohne Argumente → er fragt, was du willst, keine Anführungszeichen nötig
```

Wenn die Verbindung zu pypi.org / Docker Hub in Ordnung ist, baut man so:

```bash
FLOWER_MIRRORS=0 docker/build
```

Die Argumente von `flowerbox` sind exakt die von `flower` — es hängt `"$@"` unverändert hinter den `ENTRYPOINT`.
`--clarify-only`, `--asks N`, `--timeout Sekunden`, `--isolate`, `-v` gehen alle durch, die vollständige Tabelle steht unter [Kommandozeile](cli.md):

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "帮我做一个 X"
```

Ausgeführt wird tatsächlich diese eine Zeile (`-t` kommt nur bei vorhandenem TTY dazu, siehe unten):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### Mount-Grenzen und Persistenz

```text
Host $PWD  ──mount──>  /work       ← hier arbeitet der Agent, die Ergebnisse bleiben auf dem Host
im Image               /opt/flower ← Framework-Quellcode, **nicht gemountet**, der Host ist nicht erreichbar
```

Deshalb ist es auch sicher, in einem Unterverzeichnis des Repositorys wie `flower/human-test/HT001` zu laufen: gemountet wird nur `HT001`,
der Framework-Quellcode liegt außerhalb des Mounts.

| Was | Bleibt es nach dem Exit? | Warum |
|---|---|---|
| Alles unter dem `$PWD` des Hosts, inklusive `runs/` und [Workbench](glossary.md#工作台) `.flower/` | Ja | Genau dieses Verzeichnis ist als `/work` gemountet |
| In andere Pfade im Container geschriebene Dinge | Nein | `--rm`, der Container wird beim Exit gelöscht |
| Credentials | Landen nicht in den Image-Layern | Über `--env-file`; `.env` ist in `.dockerignore` ausgeschlossen, selbst `COPY . .` bringt sie nicht hinein |

!!! danger "Das Projektverzeichnis muss unter `$HOME` liegen, sonst gehen die Ergebnisse still verloren"
    **colima mountet standardmäßig nur `$HOME` in die VM** (`mount | grep virtiofs` → `mount0 on /Users/<du>`).
    Läuft man an einem Ort wie `/tmp`, legt `-v` in der VM ein **leeres Verzeichnis** an, und was dort hineingeschrieben wird, sieht der Host nie —
    **und es gibt keine Fehlermeldung** — Ergebnisse, [Brief](glossary.md#需求确认书), `runs/` sind komplett weg. Einmal reingefallen:
    ein `once` lief durch, $0.17 waren ausgegeben, und `runs/` existierte auf dem Host schlicht nicht.

    `flowerbox` blockt diesen Fall jetzt ab: liegt `$PWD` unter `$HOME`, wird direkt durchgelassen; sonst schreibt es eine Probe-Datei nach `$PWD`
    und startet einen Container, der mit `test -f /work/<Probe>` real nachmisst (mit zusätzlich konfigurierten Mounts kommt man also auch durch). Klappt das nicht, wird mit 1 beendet
    und dir `colima start --mount '<Pfad>:w'` genannt. Die Probe braucht einen Container, also muss vorher `docker/build` gelaufen sein.

### Credentials

Über `docker run --env-file`, **nicht in die Image-Layer**. `flowerbox` liest `$FLOWER_HOME/.env`,
standardmäßig also die `.env` in der Repo-Wurzel:

```bash
cp .env.example .env       # Token eintragen; .env ist bereits gitignored
```

Achtung: `flower setup` schreibt nach `~/.config/flower/.env`, **diesen Pfad liest `flowerbox` nicht**.
Wer schon mit `setup` konfiguriert hat und keine zweite Kopie will, zeigt mit `FLOWER_HOME` dorthin:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Schlüsselnamen, Priorität und wie das Gateway einzutragen ist: siehe [Konfiguration](config.md).

!!! warning "Ohne TTY hängen Rückfragen bis zum `--timeout`"
    `flowerbox` setzt `-t` nur bei `[ -t 0 ]` — `docker run -t` meldet in Pipes / CI direkt
    „the input device is not a TTY"; `-i` wird immer gebraucht, sonst kommt stdin gar nicht hinein.

    Antworten auf Rückfragen laufen über stdin. Ohne TTY wirft `input()` schon beim ersten Mal `EOFError` → die aktuelle Frage wird als
    „Eingabe geschlossen" übersprungen, und **der Antwort-Thread beendet sich direkt**, sodass ab der zweiten Frage niemand mehr abnimmt und man nur noch
    den vollen `--timeout` (Standard 1800 Sekunden) abwartet. Für unbeaufsichtigte Läufe explizit `--timeout 0`. Erkennt das Skript, dass kein TTY da ist,
    gibt es vorher eine Hinweiszeile aus.

### git submodule

In `.gitmodules` steht nur ein Eintrag:

| path | url | Was es ist |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | Das Code-Repository, das der Lauf [HT001](../cases/ht001.md) **produziert hat**, zur Archivierung |

Ein normales `git clone` holt es nicht, `human-test/HT001` ist dann ein leeres Verzeichnis (ein `-` vor der Zeile in
`git submodule status` bedeutet genau diesen Zustand). Ob es dich kümmern muss:

| Was du vorhast | Initialisieren? |
|---|---|
| flower laufen lassen, Image bauen | **Nein.** `.dockerignore` schließt `human-test/` aus, und das `Dockerfile` `COPY`t ohnehin nur `pyproject.toml` / `flower` / `examples` |
| Den von HT001 produzierten Code lokal durchsehen | Ja: `git submodule update --init human-test/HT001`, oder von Anfang an `git clone --recurse-submodules` |

### Netz in China: warum dieser ganze Mirror-Ersatz

Wenn man das Ganze hinter der Great Firewall installiert, ist nicht die Bandbreite langsam, sondern die internationale Strecke. Das voreingestellte `docker/build` hat alles Nötige bereits ersetzt,
`FLOWER_MIRRORS=0` schaltet alles mit einem Griff ab. Unten stehen die Messdaten und die Begründung für die vier Ersetzungen — wer das Netzproblem nicht hat, braucht das nicht zu lesen.

??? note "Gemessene Geschwindigkeiten und die vier Ersetzungen (2026-09-06, macOS/arm64)"

    | Quelle | Geschwindigkeit |
    |---|---|
    | `pypi.org` (Index) | 32 KB/s |
    | `files.pythonhosted.org` (Paketdateien) | **284 B/s** |
    | `github.com` (Release-Asset direkt) | 22 KB/s |
    | `cloud-images.ubuntu.com` | 382 B/s |
    | `deb.debian.org` | 32 KB/s |
    | `ports.ubuntu.com` (in der VM) | 26 KB/s |
    | `download.docker.com` | **nicht erreichbar** (HTTP 000); in der VM 4 KB/s |
    | `mirrors.tuna.tsinghua.edu.cn` | **nicht erreichbar** |
    | `mirrors.aliyun.com/pypi` (**Paketdateien**) | 1.4 MB/s (Host) / 152 KB/s (in der VM) |
    | `mirrors.ustc.edu.cn/ubuntu-cloud-images` | **28 MB/s** |
    | `mirrors.ustc.edu.cn/ubuntu-ports` (in der VM) | 1.95 MB/s |
    | `mirrors.ustc.edu.cn/debian` | 435 KB/s |
    | `ghfast.top` (GitHub-Proxy) | **2.5 MB/s** |
    | `gh-proxy.com` (GitHub-Proxy) | 1.5 MB/s |
    | `dockerproxy.net` (Docker-Hub-Proxy) | funktioniert (liefert das Manifest direkt) |

    Beim Messen die **Indexseite** nicht für eine Paketdatei halten: die Seite `mirrors.aliyun.com/pypi/simple/` kommt auf 7.4 MB/s,
    während das eigentliche 95.9 MB große Wheel nur 1.4 MB/s schafft (in der VM 152 KB/s — das User-Space-Netzwerk von colima kostet). 
    Schätz die Zeit nach den Zahlen für Paketdateien.

    **Ersetzung 1 — das VM-Image von colima.** colima nutzt kein normales Ubuntu-Cloud-Image, sondern ein eigenes,
    **mit vorinstalliertem docker** angepasstes Image (Release-Asset von `abiosoft/colima-core`), deshalb muss beim Start der VM docker nicht per
    apt installiert werden — und damit ist das nicht erreichbare `download.docker.com` umgangen. Selbst herunterladen und mit `--disk-image` übergeben:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # Prüfen: den digest über die GitHub-API holen. Nicht überspringen — das Ding läuft nachher als VM
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    Der Proxy bricht zwischendurch ab (gemessen: curl 56); mit `-C -` einfach ein paar Mal neu starten, der Download setzt fort.

    **Ersetzung 2 — apt in der VM.** Selbst mit dem Image, in dem docker vorinstalliert ist, führt limas Boot-Skript
    `30-install-packages.sh` noch einmal ein `apt-get update` aus, nur um `rsync` zu installieren —
    es geht an `ports.ubuntu.com` (26 KB/s) und `download.docker.com` (4 KB/s) und hängt dutzende Minuten.

    Vorgehen (**erst `/mnt/lima-cidata/boot.sh` lesen, dann handeln**: es behandelt fehlgeschlagene Boot-Skripte nur mit `WARNING` +
    `CODE=1` und läuft weiter, und schreibt am Ende **garantiert** `/run/lima-boot-done` — deshalb ist es sicher, diesen Schritt scheitern zu lassen):

    ```bash
    export LIMA_HOME=~/.colima/_lima
    limactl shell colima -- sudo sh -c '
      cat > /etc/apt/sources.list.d/ubuntu.sources <<EOF
    Types: deb
    URIs: https://mirrors.ustc.edu.cn/ubuntu-ports/
    Suites: noble noble-updates noble-backports noble-security
    Components: main restricted universe multiverse
    Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
    EOF
      sed -i "s|https://download.docker.com|https://mirrors.ustc.edu.cn/docker-ce|g" \
          /etc/apt/sources.list.d/docker.list
      pkill -f "apt-get update"          # boot.sh läuft weiter durch und schreibt die Fertig-Markierung
    '
    # colima start beendet sich daraufhin normal; danach rsync nachziehen (jetzt 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    Bei der Gelegenheit `127.0.0.1 lima-colima` in die `/etc/hosts` der VM eintragen, das räumt die Warnungskette
    `sudo: unable to resolve host` weg.

    **Ersetzung 3 — das Basis-Image.** `docker/build` holt `python:3.13-slim` erst von `dockerproxy.net`
    und taggt es um, damit das `FROM` im Dockerfile lokal trifft. Gemessen: `dockerproxy.net` liefert das Manifest direkt
    (HTTP 200); `docker.1ms.run` / `docker.m.daocloud.io` antworten mit 401, `hub.rat.dev` mit 302,
    `docker.xuanyuan.me` mit 403.

    **Ersetzung 4 — apt und pip im Container.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s) und
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Beachte: `PIP_INDEX_URL`
    ist zugleich eine Umgebungsvariable, die pip selbst kennt — sobald das `ARG` deklariert ist, liest das pip im RUN sie also mit,
    auch ohne explizites `--index-url`.

    Die einmalige Vorbereitung dauert (unter den obigen Netzbedingungen) insgesamt etwa 25 Minuten, den Löwenanteil machen das 364 MB große VM-Image und das 95.9 MB große
    SDK-Wheel aus. Danach startet `flowerbox` in Sekunden.

## Teil 2 — plugin {#plugin}

### Was es ist

Ein **Domänen-Fähigkeitspaket**, das mit dem Repository mitreist. Der Framework-Code enthält kein Domänenwissen, das gesamte Domänenwissen liegt im Verzeichnis `plugin/`
in der Repo-Wurzel und wird mit dem Code geklont, mit dem Code reviewt, mit dem Code getaggt.

Die Verdrahtung auf SDK-Seite steht in
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)
in `build_options()`, zwei Zeilen:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Zusammen mit `setting_sources=[]` (dazu weiter unten separat) ist das der Grund, warum flower gleichzeitig „[portabel](glossary.md#可移植)"
sein und „deine Domäne verstehen" kann: es fragt nicht, was auf dem Host installiert ist, es kennt nur dieses eine Verzeichnis, das mit dem Repository kommt.

### Verzeichnislayout

| Pfad | Inhalt | Wann es greift | Wer entscheidet |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | Identität des Pakets: `name`, `description`, `version`, `author` | Einmal beim Laden gelesen | — |
| `plugin/skills/<name>/SKILL.md` | Domänenwissen, bei Bedarf geladen | **probabilistisch** — nur wenn das Modell es für relevant hält | Modell |
| `plugin/agents/<name>.md` | subagent, eigenes Kontextfenster | Das Modell delegiert, oder es wird im [Workflow](glossary.md#流程) explizit angegeben | Modell / du |
| `plugin/hooks/hooks.json` | Tool-Aufrufe abfangen | **deterministisch** — trifft der Match, läuft es | Code |
| `plugin/.mcp.json` | Anbindung externer Tools | Als Tool registriert, genau wie eingebaute Tools | Modell |

**Der Unterschied zwischen probabilistisch und deterministisch entscheidet die Auswahl, es ist kein Unterschied in der Wortwahl:**

- Ein Skill ist **dort abgelegtes Wissen**. Das Modell sieht die `description` und liest es nur dann, wenn es die Sache für relevant zur aktuellen Aufgabe hält.
  Die Relevanzentscheidung trifft das Modell, dieselbe Anweisung zweimal gestartet kann also einmal das Skill nutzen und einmal nicht.
- Ein Hook ist **Code**. Passt das Event, läuft er, unabhängig davon, ob das Modell das will oder überhaupt weiß. Flowers eigenes
  [Spill](glossary.md#落盘) und [Isolation](glossary.md#隔离) sind Hooks, genau weil sie nicht „manchmal greifen" dürfen.

Es gibt also nur ein Kriterium: **Muss das jedes Mal passieren?** Muss es — schreib einen Hook. Ist es nur „gut zu wissen" —
schreib ein Skill. Etwas Zwingendes als Skill zu schreiben heißt, die Disziplin auf ein einzelnes Urteil des Modells zu setzen.

Zurzeit enthält `plugin/` im Repository nur zwei Dinge: `.claude-plugin/plugin.json` und `skills/example/SKILL.md`.
`agents/`, `hooks/` und `.mcp.json` **existieren alle noch nicht** — wer sie braucht, legt sie selbst an, mit den Verzeichnisnamen exakt aus der Tabelle oben.

### Ein Skill schreiben: vollständiges Beispiel

Am Beispiel „Release Notes erzeugen", von null bis zur Bestätigung, dass es greift.

**Schritt 1: Verzeichnis anlegen.** Der Verzeichnisname ist der Skill-Name und muss mit dem `name` im Frontmatter übereinstimmen.

```bash
mkdir -p plugin/skills/release-notes
```

**Schritt 2: `plugin/skills/release-notes/SKILL.md` schreiben.** Der Dateiname muss `SKILL.md` sein, groß geschrieben.
Das Format ist YAML-Frontmatter + Markdown-Fließtext, im Frontmatter zwei Felder:

| Feld | Funktion |
|---|---|
| `name` | Die Kennung des Skills. Identisch mit dem Verzeichnisnamen |
| `description` | **Ob das Modell es wählt, hängt allein an dieser Zeile.** Schreib klar auf, „wann man es verwenden soll", nicht „was es ist" |

Eine minimale, direkt verwendbare Datei:

````markdown
---
name: release-notes
description: Beim Zusammenstellen von Release Notes verwenden. Nutze es, wenn der Nutzer „Release Notes schreiben", „was hat sich in dieser Version geändert" oder „Release" sagt.
---

# Release Notes

## Woher das Material kommt

```bash
git describe --tags --abbrev=0        # letzter Tag
git log --oneline <letzter Tag>..HEAD  # die Commits dieser Version
```

## Ausgabeformat

In drei Abschnitte gegliedert, jeder Abschnitt eine ungeordnete Liste, ein Eintrag pro Zeile; beschreibe Änderungen, die der Nutzer wahrnimmt, kein internes Refactoring:

- **Neu** — was diese Version kann, was vorher nicht ging
- **Behoben** — was repariert wurde, das Symptom in einem Satz
- **Inkompatibel** — was beim Upgrade von Hand geändert werden muss. Gibt es nichts, entfällt der ganze Abschnitt

## Grenzen

- Die Versionsnummer nicht erfinden, sondern aus `version` in `pyproject.toml` lesen.
- Wenn unklar ist, ob ein Commit für den Nutzer wahrnehmbar ist, listet ihn auf und frag nach; entscheide nicht für den Nutzer.
````

Für den Fließtext gibt es kein vorgeschriebenes Format — es ist einfach ein Textstück, das in den Kontext gelesen wird. Orientier dich an
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md):
klar sagen, **wann es verwendet wird**, **welche Schritte**, **wie die Ausgabe aussieht**, **wo die Grenzen liegen** — das bringt mehr, als Hintergrundwissen aufzuhäufen.

**Schritt 3: bestätigen, dass es geladen wurde.** Prüfe nur eine sichere Sache — ob das Verzeichnis überhaupt da ist:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Erst wenn `/path/to/flower/plugin True` erscheint, wird das `if` in `build_options()` betreten.
Steht dort `False`, ist nichts geladen — und **zur Laufzeit gibt es dafür keinen Fehler**, siehe die Warnung unten.

**Nimm nicht „einmal was laufen lassen und schauen, ob das `example`-Skill aufgerufen wurde" als Verifikation.** Skills sind probabilistisch: dass das Modell es nicht aufgerufen hat,
kann daran liegen, dass es nicht installiert ist, oder schlicht daran, dass das Modell es für die aktuelle Aufgabe nicht für nötig hielt — dieses Signal unterscheidet die beiden Fälle nicht. Außerdem
setzt `build_options()` nie die sessionweite Option `skills=` des SDK; ob die Skills aus dem plugin überhaupt in der Auswahlliste des
Koordinators auftauchen, wurde nie praktisch nachgemessen. Das `True`/`False` von `PLUGIN_DIR` oben ist sicher, nimm das.

Um einem bestimmten [Worker](glossary.md#执行者) namentlich bestimmte Skills freizuschalten, gibt es `worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py));
als Namen den `name` aus `SKILL.md` verwenden, das SDK akzeptiert auch die qualifizierte Schreibweise `Pluginname:Skillname`.

!!! warning "Im installierten flower gibt es kein `plugin/` — bei keiner der drei Installationsarten"
    `PLUGIN_DIR` geht von `flower/core/agent.py` drei Ebenen hoch und dann in `plugin/`. Läuft man aus einem Quellcode-Checkout, ist das das `plugin/`
    in der Repo-Wurzel; das Wheel packt aber nur das eine Verzeichnis `flower` ein (in `pyproject.toml`:
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`), nach der Installation in site-packages existiert
    `site-packages/plugin` also nicht, `PLUGIN_DIR.is_dir()` ist falsch — **still übersprungen, kein Fehler, keine Warnung**.

    **Das ist kein Container-Problem, der Umfang ist deutlich größer.** Jeder Pfad von `install.sh` — `uv tool install`,
    `pipx install`, uv erst bootstrappen und dann uv benutzen, sowie der Fallback `pip install --user` — installiert das Wheel.
    Das heißt: **bei einem in einem Befehl installierten flower fällt das Domänen-Fähigkeitspaket durchweg still aus.** Der Container ist nur eine Instanz desselben Problems:
    `docker/Dockerfile` `COPY`t nur `pyproject.toml`, `flower/` und `examples/`, `plugin/` kommt nicht ins Image.

    Notiert in [issue #15](https://github.com/ChenyuHeee/flower/issues/15). Nach der Installation zuerst den `PLUGIN_DIR`-Befehl von oben
    zur Selbstprüfung laufen lassen: erscheint `False`, hat diese Installation kein Domänen-Fähigkeitspaket. Wer eines braucht,
    muss derzeit aus einem Quellcode-Checkout laufen.

### Warum `setting_sources=[]` Domänenfähigkeiten ins plugin zwingt

In derselben Funktion steht noch diese Zeile:

```python
"setting_sources": [] if portable else ["project"],
```

Der Standard des SDK ist `None` = alle drei Quellen werden gelesen: `~/.claude/settings.json` (Nutzer),
`.claude/settings.json` (Projekt), `.claude/settings.local.json` (lokal). flower übergibt standardmäßig `[]`
und schaltet sie **alle ab**.

| | Wird gelesen? | Folge |
|---|---|---|
| `~/.claude/` (Host) | Nein | Auf einer anderen Maschine gleiches Verhalten, das Ergebnis unterscheidet sich nicht, weil „bei mir ist das mal konfiguriert worden" |
| Projekt-`.claude/` | Nein | Was in `.claude/skills/` oder `.claude/agents/` liegt, greift unter flower **kein Stück** |
| `plugin/` | Ja | Der Pfad steht fest im Code, er reist mit dem Repository |
| Credentials | Laufen nicht über diesen Weg | Eigene `.env` ist Pflicht; der `env`-Block in `~/.claude/settings.json` und `settings.local.json` dient nur als letzter Fallback und **liefert nur 9 Credential-Schlüssel**, siehe [Konfiguration](config.md) |

Dass `.claude/` nicht greift, ist **kein vergessener Konfigurationspunkt, sondern die Definition dieser Randbedingung**: sobald auch nur ein Byte vom Host gelesen wird, gilt
„auf einer anderen Maschine gleiches Verhalten" nicht mehr. Für Domänenfähigkeiten bleibt damit genau ein Kanal — das mit dem Repository reisende `plugin/`.

Zwei Schalter (beide an `build_options()`, die Standardwerte sind die portable Variante):

| Parameter | Standard | Was sich ändert |
|---|---|---|
| `portable` | `True` | `False` übergeben → `setting_sources` wird zu `["project"]`, die Projekt-`.claude/` wird gelesen (SDK-Seite: um `CLAUDE.md` zu lesen, muss `"project"` enthalten sein). Damit fällt die Portabilität weg |
| `use_plugin` | `True` | `False` übergeben → `plugin/` wird gar nicht eingehängt, Domänenfähigkeiten hängen komplett an `AgentSpec.instructions` |

Nebenbei: `instructions` läuft über [Append](glossary.md#叠加) (das `append` des `system_prompt`)
und ist ein anderer Kanal als das plugin — Ersteres steht in jeder Runde im Kontext, Letzteres wird bei Bedarf geladen. Kurze und zwingende Disziplin gehört in `instructions`,
langes und nur gelegentlich nützliches Wissen in ein Skill.

## Teil 3 — Dokumentationsseite

Die Seite, die du gerade liest, ist mit mkdocs-material gebaut, die Quelldateien liegen im Repository unter `docs/`, ein Push auf `main` veröffentlicht automatisch.

| Schritt | Was es ist |
|---|---|
| Konfiguration | `mkdocs.yml`, `docs_dir: docs` |
| Mehrsprachigkeit | `mkdocs-static-i18n`, `docs_structure: folder` — `docs/zh/`, `docs/en/` … Standardsprache ist `zh` |
| Abhängigkeiten | `docs-requirements.txt` (Versionen gepinnt). **Nicht** das `docs`-Extra aus `pyproject.toml` — CI installiert Ersteres |
| Build | `mkdocs build --strict`. Kaputte interne Links und nav-Einträge auf nicht existierende Seiten lassen den Build direkt scheitern, es wird kein stiller 404 veröffentlicht |
| Redirects | `hooks/redirects.py` schreibt **nach** dem Build anhand der finalen URLs meta-refresh-Stubs und leitet die alten flachen Adressen (`/start/`, `/workflow/`, `/case-ht001/` …) an die neuen Positionen |
| Deployment | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, veröffentlicht auf GitHub Pages |

Doku lokal ändern:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # lokale Vorschau
mkdocs build --strict         # vor dem Commit einmal laufen lassen, derselbe Befehl wie in CI
```

Die CI wird ausgelöst durch einen Push auf `main` **und** wenn die Änderungen diese Pfade treffen; zusätzlich kann man auf der Actions-Seite manuell
`workflow_dispatch` auslösen:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### Warum `install.sh` von Pages ausgeliefert wird

Am Ende des Build-Schritts steht diese Zeile:

```yaml
- run: cp install.sh site/install.sh
```

Das Installationsskript wird ins Site-Artefakt gelegt und hängt damit unter der Domain der Dokumentationsseite; die Ein-Zeilen-Installation sieht so aus:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Der Grund ist sehr praktisch: **`raw.githubusercontent.com` ist aus China nicht erreichbar, `*.github.io` schon** (nachgemessen).
Das Skript selbst liegt in der Repo-Wurzel, beim Veröffentlichen wird nur eine Kopie mehr abgelegt — es müssen keine zwei Inhalte gepflegt werden und es braucht kein zusätzliches CDN.

Was `install.sh` selbst tut: einen Python-Tool-Installer auswählen (`uv` > `pipx` > `uv` installieren > `pip --user`),
flower von GitHub installieren und dann den nächsten Schritt anzeigen. Es **fasst keine Credentials an** — beim ersten `flower`-Lauf wird gefragt und nach
`~/.config/flower/.env` gespeichert.
