# Deployment und Erweiterung

flower woanders hinzubringen heißt, drei Dinge zu regeln: Container (das unbeschränkte Bash einzäunen und nebenbei die Aussage „ohne CLI" prüfen),
[plugin](glossary.md#plugin) (Domänenfähigkeiten reisen mit dem Repository, unabhängig davon, was auf dem Host installiert ist), Doku-Site (Push auf `main`
veröffentlicht automatisch, `install.sh` hängt an der Pages-Domain). Die drei Abschnitte sind voneinander unabhängig, lies nach Bedarf.

## 1. Container {#一容器}

### Warum ein Container {#为什么要容器}

**Erstens: einzäunen.** Der arbeitende [Worker](glossary.md#执行者) hat **unbeschränktes Bash** — die Bash-Whitelist von flower
(`delegate_guard`) gilt nur für den [Main Thread](glossary.md#主线程); wer rausgeschickt wird, muss Tests laufen lassen können, das ist Absicht.
Im Container wird nur dein Projektverzeichnis gemountet, der Framework-Quellcode liegt im Image unter `/opt/flower`, vom Rest des Hosts ist nichts sichtbar.

**Zweitens: der Container ist selbst die Prüfung der Randbedingung [Portabilität](glossary.md#可移植).** Im Image gibt es keine Claude Code CLI,
kein Node, nur Python und `claude-agent-sdk` — die Requests gehen über das native Binary, das im Wheel steckt.
Läuft es hier, ist „ohne CLI" keine Behauptung auf dem Papier.

Praktisch verifiziert (2026-09-06, macOS 15 / arm64 / colima + docker 28.4.0):

| Was geprüft wurde | Ergebnis |
|---|---|
| Gibt es im Image eine CLI | `claude`, `node`, `npm`, `npx` **existieren alle nicht** |
| Mitgeliefertes Binary | `\177ELF` (207M) |
| Echter Request | über `cloud.infini-ai.com/maas` abgesetzt und Antwort erhalten, `$0.1741 / 1 Runde` (das ist der Boden für eine einzelne Runde mit Opus 5 + 1M-Fenster) |
| Dateibesitz | Dateien, die im Container nach `/work` geschrieben werden, gehören auf dem Host `hechenyu:staff`, Mapping korrekt |
| Sichtbarkeit des Hosts | im Container `ls /Users` → `No such file or directory` |

### Was im Image installiert ist {#镜像里装了什么}

Basis-Image `python:3.13-slim`, darauf installiert apt genau drei Pakete. Jedes davon hat einen Grund:

| Installiert | Warum |
|---|---|
| `python:3.13-slim` | Es braucht nur Python ≥ 3.10. Kein Node, keine claude-CLI |
| `git` | `--isolate` gibt jedem [subagent](glossary.md#subagent) ein eigenes worktree |
| `ca-certificates` | HTTPS-Gateway |
| `libstdc++6` | Das mitgelieferte SDK-Binary ist eine mit Bun kompilierte Single-File-Binary, unter Linux braucht sie das; im slim-Image fehlt es |

Der Framework-Quellcode kommt per `COPY` ins Image, **nicht per bind mount** — der Agent im Container kommt damit an den Framework-Quellcode auf dem Host nicht heran:

| Pfad im Image | Inhalt | Woher |
|---|---|---|
| `/opt/flower` | `pyproject.toml`, `flower/`, `examples/`, und dort `pip install .` | `COPY` |
| `/work` | Arbeitsverzeichnis (`WORKDIR`), zur Laufzeit wird das `$PWD` des Hosts gemountet | `docker run -v` |

Einstiegspunkt ist `ENTRYPOINT ["flower"]`, `CMD` ist leer — läuft der Container ohne Argumente, landet man in der interaktiven Eingabe
(er fragt, was du machen willst), statt `--help` auszugeben. Damit muss man eine Anforderung in Prosa in der Shell nicht quoten.

### Warum man das `.venv` des Hosts nicht hineinmounten kann {#为什么不能把宿主的-venv-挂进去}

Das SDK liefert Wheels pro Plattform aus, das mitgelieferte Binary ist plattformspezifisch:

```text
Host       claude_agent_sdk-0.2.152-py3-none-macosx_11_0_arm64.whl
           → _bundled/claude ist Mach-O 64-bit arm64, 191M
Container  claude_agent_sdk-0.2.152-py3-none-manylinux_2_17_aarch64.whl
```

Hineingemountet läuft es nicht, das Image muss also selbst `pip install` machen. Umgekehrt ist genau das der Beleg für Portabilität: dieselbe
`pyproject.toml`, andere Plattform, anderes natives Binary — und keine Zeile Framework-Code ändert sich.

### Die beiden Skripte {#两个脚本}

| Skript | Was es tut |
|---|---|
| [`docker/build`](https://github.com/ChenyuHeee/flower/blob/main/docker/build) | Baut das Image. `cd` in die Repo-Wurzel, `docker build -f docker/Dockerfile -t flower-box .`; bei `FLOWER_MIRRORS=1` (Default) wird `python:3.13-slim` zuerst von einem Registry-Mirror geholt und umgetaggt, dazu kommen die `--build-arg` für pip / apt |
| [`docker/flowerbox`](https://github.com/ChenyuHeee/flower/blob/main/docker/flowerbox) | Ein Lauf. Credential-Datei prüfen → prüfen, ob `$PWD` überhaupt gemountet werden kann → prüfen, ob ein TTY da ist → `docker run` |

Die Schalter von `docker/build` laufen alle über Umgebungsvariablen:

| Variable | Default | Bedeutung |
|---|---|---|
| `FLOWER_IMAGE` | `flower-box` | Image-Tag |
| `FLOWER_MIRRORS` | `1` | `0` = kein einziger Mirror wird getauscht, alles geht upstream |
| `FLOWER_REGISTRY` | `dockerproxy.net` | Von hier wird das Basis-Image geholt und auf `python:3.13-slim` umgetaggt, damit `FROM` lokal trifft |
| `FLOWER_PIP_INDEX` | `https://mirrors.aliyun.com/pypi/simple/` | Geht an `--build-arg PIP_INDEX_URL` |
| `FLOWER_APT_MIRROR` | `mirrors.ustc.edu.cn` | Geht an `--build-arg APT_MIRROR` |

Die letzten drei wirken nur bei `FLOWER_MIRRORS=1` — der Zweig für `FLOWER_MIRRORS=0` setzt überhaupt kein build-arg.

`docker/flowerbox` kennt zwei:

| Variable | Default | Bedeutung |
|---|---|---|
| `FLOWER_HOME` | eine Ebene über dem Skript selbst (also die Repo-Wurzel) | Wo `.env` gesucht wird. Fehlt `$FLOWER_HOME/.env`, sofort Exit 1 |
| `FLOWER_IMAGE` | `flower-box` | Welches Image gestartet wird |

`FLOWER_HOME` wird aus der Position des Skripts abgeleitet, kein fest verdrahteter Pfad — das Repository funktioniert also, egal wohin es geklont wurde.

### Image bauen und Container starten {#跑起来}

```bash
docker/build                       # einmal reicht
cd ~/beliebiges-projekt            # muss unterhalb von $HOME liegen, siehe Mount-Grenzen unten
/path/to/flower/docker/flowerbox   # ohne Argumente → er fragt, was du willst, kein Quoting nötig
```

Wenn die Verbindung zu pypi.org / Docker Hub in Ordnung ist, baut man so:

```bash
FLOWER_MIRRORS=0 docker/build
```

Die Argumente von `flowerbox` sind exakt die von `flower` — es hängt `"$@"` unverändert hinter das `ENTRYPOINT`.
`--clarify-only`, `--asks N`, `--timeout Sekunden`, `--isolate`, `-v` gehen alle durch, die vollständige Tabelle steht unter [Kommandozeile](cli.md):

```bash
cd ~/proj
/path/to/flower/docker/flowerbox --clarify-only -v
/path/to/flower/docker/flowerbox "Bau mir ein X"
```

Tatsächlich ausgeführt wird diese Zeile (`-t` kommt nur dazu, wenn ein TTY da ist, siehe unten):

```bash
docker run -i $TTY --rm \
    --env-file "$FLOWER_HOME/.env" \
    -v "$PWD:/work" \
    -w /work \
    "$IMAGE" "$@"
```

### Mount-Grenzen und Persistenz {#挂载边界与持久化}

```text
Host $PWD  ──mount──>  /work       ← hier arbeitet der Agent, die Ergebnisse bleiben auf dem Host
im Image               /opt/flower ← Framework-Quellcode, **nicht gemountet**, der Host ist unerreichbar
```

Deshalb ist es auch sicher, in einem Unterverzeichnis des Repositories wie `flower/human-test/HT001` zu laufen: gemountet wird nur `HT001`,
der Framework-Quellcode liegt außerhalb des Mounts.

| Was | Bleibt es nach dem Beenden | Warum |
|---|---|---|
| Alles unter `$PWD` auf dem Host, inklusive `runs/` und [Workbench](glossary.md#工作台) `.flower/` | Ja | Genau dieses Verzeichnis ist als `/work` gemountet |
| Was auf andere Pfade im Container geschrieben wurde | Nein | `--rm`, der Container ist beim Beenden weg |
| Credentials | Landen nicht in einer Image-Schicht | Gehen über `--env-file`; `.env` ist in `.dockerignore` ausgeschlossen, selbst `COPY . .` bekäme sie nicht hinein |

!!! danger "Das Projektverzeichnis muss unterhalb von `$HOME` liegen, sonst gehen die Ergebnisse still verloren"
    **colima mountet per Default nur `$HOME` in die VM** (`mount | grep virtiofs` → `mount0 on /Users/<dein-user>`).
    Läuft man an einer Stelle wie `/tmp`, legt `-v` in der VM ein **leeres Verzeichnis** an, das dort Geschriebene sieht der Host nie,
    **und es gibt keinen Fehler** — Ergebnisse, [Brief](glossary.md#需求确认书), `runs/` sind komplett weg. Einmal reingetreten:
    ein `once`-Lauf war durch, $0.17 ausgegeben, `runs/` existierte auf dem Host schlicht nicht.

    `flowerbox` fängt diesen Fall inzwischen ab: liegt `$PWD` unter `$HOME`, geht es direkt durch; sonst schreibt es eine Sondendatei nach `$PWD`
    und startet einen Container, der mit `test -f /work/<sonde>` real nachmisst (auch zusätzliche Mounts kommen so durch). Klappt das nicht, Exit 1,
    mit dem Hinweis auf `colima start --mount '<pfad>:w'`. Die Sonde braucht einen Container, also muss vorher `docker/build` gelaufen sein.

### Wie Credentials in den Container kommen {#凭证}

Über `docker run --env-file`, **nicht in eine Image-Schicht**. `flowerbox` liest `$FLOWER_HOME/.env`,
per Default also die `.env` in der Repo-Wurzel:

```bash
cp .env.example .env       # Token eintragen; .env steht bereits in .gitignore
```

Beachte: `flower setup` schreibt nach `~/.config/flower/.env`, **diesen Pfad schaut `flowerbox` nicht an**.
Wer schon mit `setup` konfiguriert hat und keine zweite Kopie will, zeigt mit `FLOWER_HOME` dorthin:

```bash
FLOWER_HOME=~/.config/flower /path/to/flower/docker/flowerbox
```

Schlüsselnamen, Vorrangregeln und wie das Gateway einzutragen ist, stehen unter [Konfiguration](config.md).

!!! warning "Ohne TTY hängen Rückfragen bis zum `--timeout`"
    `flowerbox` setzt `-t` nur bei `[ -t 0 ]` — `docker run -t` meldet in einer Pipe oder in CI direkt
    „the input device is not a TTY"; `-i` wird immer gebraucht, sonst kommt stdin gar nicht erst hinein.

    Antworten auf Rückfragen laufen über stdin. Ohne TTY wirft `input()` schon beim ersten Mal `EOFError` → die aktuelle Frage wird als
    „Eingabe geschlossen" übersprungen, und **der Antwort-Thread beendet sich sofort**, also nimmt ab der zweiten Frage niemand mehr etwas entgegen
    und man wartet den vollen `--timeout` ab (Default 1800 Sekunden). Unbeaufsichtigt braucht es explizit `--timeout 0`. Erkennt das Skript, dass kein TTY da ist,
    gibt es vorher eine Zeile Hinweis aus.

### git submodule {#git-submodule}

In `.gitmodules` steht genau ein Eintrag:

| path | url | Was es ist |
|---|---|---|
| `human-test/HT001` | `https://github.com/ChenyuHeee/cppide.git` | Das von jenem [HT001](../cases/ht001.md)-Run **erzeugte** Code-Repository, zur Archivierung |

Ein normales `git clone` holt es nicht, `human-test/HT001` ist dann ein leeres Verzeichnis (das `-` vor dem Eintrag in `git submodule status`
ist genau dieser Zustand). Ob man sich darum kümmern muss:

| Was du vorhast | Initialisieren nötig |
|---|---|
| flower laufen lassen, Image bauen | **Nein**. `.dockerignore` schließt `human-test/` aus, und das `Dockerfile` kopiert ohnehin nur `pyproject.toml` / `flower` / `examples` |
| Lokal im erzeugten Code von HT001 stöbern | Ja: `git submodule update --init human-test/HT001`, oder gleich von Anfang an `git clone --recurse-submodules` |

### Netzwerk in China: warum diese ganzen Mirror-Ersetzungen {#国内网络为什么有那一堆镜像替换}

Wenn man das hinter der Firewall installiert, ist nicht die Bandbreite langsam, sondern die internationalen Strecken. Das Default-`docker/build` hat
alles Nötige bereits getauscht, `FLOWER_MIRRORS=0` schaltet alles mit einem Handgriff ab. Unten stehen die gemessenen Zahlen und die Begründung für die vier
Ersetzungen — wer dieses Netzwerkproblem nicht hat, muss das nicht lesen.

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
    | `dockerproxy.net` (Docker-Hub-Proxy) | nutzbar (liefert das Manifest direkt) |

    Beim Messen darf man die **Indexseite** nicht für eine Paketdatei halten: die Seite `mirrors.aliyun.com/pypi/simple/` kommt auf 7.4 MB/s,
    das eigentliche 95.9 MB große Wheel aber nur auf 1.4 MB/s (in der VM 152 KB/s — das User-Space-Netzwerk von colima kostet). Die Zeit
    schätzt man nach den Zahlen für Paketdateien.

    **Ersetzung 1 — das VM-Image von colima.** colima verwendet kein normales Ubuntu-Cloud-Image, sondern ein eigenes,
    **mit vorinstalliertem docker** (ein Release-Asset von `abiosoft/colima-core`), deshalb muss beim VM-Start docker nicht per apt
    installiert werden — womit das nicht erreichbare `download.docker.com` umgangen ist. Man lädt es selbst herunter und übergibt es mit `--disk-image`:

    ```bash
    A=https://github.com/abiosoft/colima-core/releases/download/v0.9.0-2/ubuntu-24.04-minimal-cloudimg-arm64-docker.qcow2
    mkdir -p ~/.colima/images
    curl -sSL -C - -o ~/.colima/images/colima-arm64-docker.qcow2 "https://ghfast.top/$A"
    # Prüfen: den Digest über die GitHub-API holen. Nicht überspringen — das Ding läuft nachher als VM
    curl -sSL https://api.github.com/repos/abiosoft/colima-core/releases/tags/v0.9.0-2 \
      | python3 -c "import json,sys;[print(a['digest'],a['name']) for a in json.load(sys.stdin)['assets'] if a['name'].endswith('arm64-docker.qcow2')]"
    shasum -a 256 ~/.colima/images/colima-arm64-docker.qcow2

    colima start --disk-image ~/.colima/images/colima-arm64-docker.qcow2 \
                 --cpu 4 --memory 6 --disk 20
    ```

    Der Proxy bricht den Stream mittendrin ab (gemessen: curl 56), mit `-C -` einfach ein paar Mal wieder aufsetzen.

    **Ersetzung 2 — apt in der VM.** Selbst mit dem Image mit vorinstalliertem docker fährt das Boot-Skript von lima,
    `30-install-packages.sh`, noch ein `apt-get update`, nur um `rsync` zu installieren —
    es greift auf `ports.ubuntu.com` (26 KB/s) und `download.docker.com` (4 KB/s) zu und hängt dann mehrere zehn Minuten.

    Vorgehen (**erst `/mnt/lima-cidata/boot.sh` lesen, dann handeln**: bei fehlgeschlagenen Boot-Skripten gibt es nur `WARNING` +
    `CODE=1` und es geht weiter, und am Ende wird **auf jeden Fall** `/run/lima-boot-done` geschrieben — diesen Schritt scheitern zu lassen ist also sicher):

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
      pkill -f "apt-get update"          # boot.sh läuft trotzdem durch und schreibt die Fertig-Markierung
    '
    # colima start endet danach normal; anschließend rsync nachziehen (jetzt 1.95 MB/s)
    limactl shell colima -- sudo sh -c 'apt-get update -q && apt-get install -y -q rsync'
    ```

    Bei der Gelegenheit `127.0.0.1 lima-colima` in die `/etc/hosts` der VM eintragen, das räumt die Warnkette
    `sudo: unable to resolve host` weg.

    **Ersetzung 3 — das Basis-Image.** `docker/build` holt `python:3.13-slim` zuerst von `dockerproxy.net`
    und taggt es um, damit das `FROM` im Dockerfile lokal trifft. Gemessen liefert `dockerproxy.net` das Manifest direkt
    (HTTP 200); `docker.1ms.run` / `docker.m.daocloud.io` antworten mit 401, `hub.rat.dev` mit 302,
    `docker.xuanyuan.me` mit 403.

    **Ersetzung 4 — apt und pip im Container.** `--build-arg APT_MIRROR=mirrors.ustc.edu.cn`
    (`deb.debian.org` 32 KB/s → USTC 435 KB/s),
    `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`. Beachte: `PIP_INDEX_URL`
    ist zugleich eine Umgebungsvariable, die pip selbst kennt — sobald das `ARG` deklariert ist, liest pip im RUN sie also mit,
    auch ohne explizites `--index-url`.

    Die einmalige Vorbereitung dauert (unter den obigen Netzwerkbedingungen) etwa 25 Minuten, den Löwenanteil machen das 364 MB große
    VM-Image und das 95.9 MB große SDK-Wheel aus. Danach startet `flowerbox` im Sekundenbereich.

## 2. plugin {#plugin}

### Was ein plugin ist und wie das SDK es lädt {#它是什么}

Ein **Domänenfähigkeits-Paket**, das mit dem Repository reist. Der Framework-Code enthält kein Domänenwissen, das gesamte Domänenwissen liegt im
Verzeichnis `plugin/` in der Repo-Wurzel und wird zusammen mit dem Code geklont, reviewt und getaggt.

Die Verdrahtung auf SDK-Seite steht in
[`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)
in `build_options()`, zwei Zeilen:

```python
PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"
...
if use_plugin and PLUGIN_DIR.is_dir():
    opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]
```

Zusammen mit `setting_sources=[]` (dazu unten separat) ist das der Grund, warum flower gleichzeitig „[portabel](glossary.md#可移植)"
und „auf deine Domäne eingestellt" sein kann: es fragt nicht, was auf dem Host installiert ist, es kennt nur dieses eine Verzeichnis aus dem Repository.

### Verzeichnisaufbau {#目录布局}

| Pfad | Inhalt | Wann es wirkt | Wer entscheidet |
|---|---|---|---|
| `plugin/.claude-plugin/plugin.json` | Identität des Pakets: `name`, `description`, `version`, `author` | Wird beim Laden einmal gelesen | — |
| `plugin/skills/<name>/SKILL.md` | Domänenwissen, bei Bedarf geladen | **Probabilistisch** — nur wenn das Modell es für relevant hält | Modell |
| `plugin/agents/<name>.md` | subagent, eigenes Kontextfenster | Vom Modell delegiert oder im [Workflow](glossary.md#流程) explizit benannt | Modell / du |
| `plugin/hooks/hooks.json` | Werkzeugaufrufe abfangen | **Deterministisch** — passt es, läuft es | Code |
| `plugin/.mcp.json` | Anbindung externer Werkzeuge | Wird als Werkzeug registriert, wie die eingebauten | Modell |

**Der Unterschied zwischen probabilistisch und deterministisch ist der Kern der Auswahl, keine Frage der Formulierung:**

- Ein skill ist **hingelegtes Wissen**. Das Modell sieht die `description` und liest es nur, wenn es die Sache für relevant zur aktuellen Aufgabe hält.
  Die Relevanzentscheidung trifft das Modell, dieselbe Anforderung zweimal gestellt kann also einmal darauf zugreifen und einmal nicht.
- Ein hook ist **Code**. Passt das Event, läuft er, unabhängig davon, ob das Modell will oder überhaupt davon weiß. [Spill](glossary.md#落盘) und
  [Isolation](glossary.md#隔离) von flower sind hooks, genau weil sie nicht „manchmal" wirken dürfen.

Das Kriterium ist deshalb ein einziges: **Muss das jedes Mal passieren?** Muss es — hook schreiben. Ist es nur „gut zu wissen" —
skill schreiben. Etwas Zwingendes als skill zu schreiben heißt, die Disziplin auf eine einzelne Entscheidung des Modells zu setzen.

Im Repository enthält `plugin/` derzeit nur zwei Dinge: `.claude-plugin/plugin.json` und `skills/example/SKILL.md`.
`agents/`, `hooks/` und `.mcp.json` **existieren noch nicht** — wer sie braucht, legt sie selbst an, mit exakt den Verzeichnisnamen aus der Tabelle oben.

### Einen skill schreiben: vollständiges Beispiel {#写一个-skill完整例子}

Am Beispiel „Release Notes erzeugen", von null bis zur Bestätigung, dass es wirkt.

**Schritt 1: Verzeichnis anlegen.** Der Verzeichnisname ist der Name des skills und muss mit dem `name` im Frontmatter übereinstimmen.

```bash
mkdir -p plugin/skills/release-notes
```

**Schritt 2: `plugin/skills/release-notes/SKILL.md` schreiben.** Der Dateiname muss `SKILL.md` sein, in Großbuchstaben.
Das Format ist YAML-Frontmatter + Markdown-Text, das Frontmatter hat zwei Felder:

| Feld | Zweck |
|---|---|
| `name` | Kennung des skills. Identisch mit dem Verzeichnisnamen |
| `description` | **Ob das Modell ihn wählt, hängt allein an dieser Zeile.** Schreib hin, „wann man ihn benutzt", nicht „was er ist" |

Eine minimale, direkt benutzbare Datei:

````markdown
---
name: release-notes
description: Beim Zusammenstellen von Release Notes verwenden. Nutze ihn, wenn der Nutzer „schreib die Release Notes", „was hat sich in dieser Version geändert" oder „Release" sagt.
---

# Release Notes

## Wie man das Material holt

```bash
git describe --tags --abbrev=0        # letzter Tag
git log --oneline <letzter Tag>..HEAD  # die Commits dieser Version
```

## Ausgabeformat

Drei Abschnitte, jeder eine ungeordnete Liste, ein Eintrag pro Zeile, beschrieben werden vom Nutzer wahrnehmbare Änderungen, kein internes Refactoring:

- **Neu** — was diese Version kann, was vorher nicht ging
- **Behoben** — was repariert wurde, das Symptom in einem Satz
- **Inkompatibel** — was beim Upgrade von Hand geändert werden muss. Gibt es nichts, entfällt der ganze Abschnitt

## Grenzen

- Die Versionsnummer nicht selbst erfinden, sondern aus `version` in `pyproject.toml` lesen.
- Ist unklar, ob ein Commit für den Nutzer wahrnehmbar ist, aufführen und nachfragen, nicht für den Nutzer entscheiden.
````

Für den Fließtext gibt es kein vorgeschriebenes Format — er ist einfach ein Stück Text, das in den Kontext gelesen wird. Orientiere dich an
[`plugin/skills/example/SKILL.md`](https://github.com/ChenyuHeee/flower/blob/main/plugin/skills/example/SKILL.md):
klar sagen, **wann man ihn benutzt**, **welche Schritte**, **wie die Ausgabe aussieht**, **wo die Grenzen liegen** — das nützt mehr als angehäuftes Hintergrundwissen.

**Schritt 3: bestätigen, dass er geladen wird.** Prüfe nur die eine sichere Sache — ob das Verzeichnis überhaupt da ist:

```bash
cd /path/to/flower
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Erst wenn `/path/to/flower/plugin True` erscheint, wird das `if` in `build_options()` betreten.
Kommt `False`, ist nichts geladen, und **zur Laufzeit gibt es keinen Fehler**, siehe die Warnung unten.

**Nimm nicht „einmal etwas laufen lassen und schauen, ob der `example`-skill aufgerufen wurde" als Verifikation.** skills sind probabilistisch: dass das Modell ihn nicht aufgerufen hat,
kann heißen, dass er nicht installiert ist — oder dass das Modell ihn für die aktuelle Aufgabe schlicht nicht für nötig hielt. Dieses Signal unterscheidet die beiden Fälle nicht. Außerdem setzt
`build_options()` nie die Session-Option `skills=` des SDK; ob die skills aus dem plugin in der Auswahlliste des
Koordinators überhaupt auftauchen, ist nicht praktisch geprüft. Das `True`/`False` aus dem `PLUGIN_DIR`-Aufruf oben ist eindeutig, nimm das.

Um einem bestimmten [Worker](glossary.md#执行者) namentlich bestimmte skills freizuschalten, nutze `worker(..., skills=[...])`
([`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py));
als Name den `name` aus `SKILL.md` verwenden, das SDK akzeptiert auch die qualifizierte Schreibweise `pluginname:skillname`.

!!! warning "In einer installierten flower gibt es kein `plugin/` — bei keiner der drei Installationsarten"
    `PLUGIN_DIR` geht von `flower/core/agent.py` drei Ebenen hoch und dann in `plugin/`. Läuft man aus einem Quellcode-Checkout, ist das das
    `plugin/` in der Repo-Wurzel; das Wheel packt aber nur das eine Verzeichnis `flower` ein (in `pyproject.toml`:
    `[tool.hatch.build.targets.wheel] packages = ["flower"]`), nach der Installation in site-packages
    existiert `site-packages/plugin` nicht, `PLUGIN_DIR.is_dir()` ist falsch — **still übersprungen, kein Fehler, keine Warnung**.

    **Das ist kein Container-Problem, der Umfang ist viel größer.** Jeder Pfad in `install.sh` — `uv tool install`,
    `pipx install`, uv selbst hochziehen und dann uv benutzen, sowie der `pip install --user`-Fallback — installiert ein Wheel.
    Das heißt: **bei einer flower, die mit einer Zeile installiert wurde, fällt das Domänenfähigkeits-Paket ausnahmslos still aus.** Der Container ist nur eine Instanz desselben Problems:
    `docker/Dockerfile` kopiert nur `pyproject.toml`, `flower/` und `examples/`, `plugin/` kommt nicht ins Image.

    Notiert in [issue #15](https://github.com/ChenyuHeee/flower/issues/15). Nach der Installation zuerst den
    `PLUGIN_DIR`-Befehl von oben zur Selbstprüfung laufen lassen: kommt `False`, hat diese Installation kein Domänenfähigkeits-Paket. Wer eines braucht,
    muss derzeit aus einem Quellcode-Checkout laufen.

### Warum `setting_sources=[]` Domänenfähigkeiten in das plugin zwingt {#setting_sources-为什么逼着领域能力走-plugin}

In derselben Funktion steht außerdem diese Zeile:

```python
"setting_sources": [] if portable else ["project"],
```

Der Default des SDK ist `None` = alle drei Quellen werden gelesen: `~/.claude/settings.json` (Nutzer),
`.claude/settings.json` (Projekt), `.claude/settings.local.json` (lokal). flower übergibt per Default `[]`
und schaltet sie **allesamt ab**.

| | Wird gelesen | Folge |
|---|---|---|
| `~/.claude/` (Host) | Nein | Auf einer anderen Maschine gleiches Verhalten, kein anderes Ergebnis, „weil ich auf dieser Maschine mal etwas konfiguriert habe" |
| Projekt-`.claude/` | Nein | Was in `.claude/skills/` oder `.claude/agents/` liegt, wirkt unter flower **kein einziges Stück** |
| `plugin/` | Ja | Der Pfad steht fest im Code und reist mit dem Repository |
| Credentials | Laufen nicht über diesen Weg | Es braucht eine eigene `.env`; die `env`-Blöcke in `~/.claude/settings.json` und `settings.local.json` dienen nur als letzter Fallback und liefern **nur 9 Credential-Schlüssel**, siehe [Konfiguration](config.md) |

Dass `.claude/` nicht wirkt, **ist keine vergessene Konfiguration, sondern die Definition dieser Randbedingung**: sobald auch nur ein Byte vom Host gelesen wird, gilt
„auf einer anderen Maschine gleiches Verhalten" nicht mehr. Für Domänenfähigkeiten bleibt damit genau ein Kanal — das mit dem Repository reisende `plugin/`.

Zwei Schalter (beide an `build_options()`, die Defaults sind der portable Satz):

| Parameter | Default | Was eine Änderung bewirkt |
|---|---|---|
| `portable` | `True` | `False` übergeben → `setting_sources` wird `["project"]`, das Projekt-`.claude/` wird gelesen (SDK-Seite: um `CLAUDE.md` zu lesen, muss `"project"` enthalten sein). Die Portabilität fällt damit weg |
| `use_plugin` | `True` | `False` übergeben → `plugin/` wird gar nicht eingehängt, Domänenfähigkeiten hängen komplett an `AgentSpec.instructions` |

Nebenbei: `instructions` läuft über [Append](glossary.md#叠加) (der `append` des `system_prompt`),
das ist ein anderer Kanal als das plugin — Ersteres steht in jeder Runde im Kontext, Letzteres wird bei Bedarf geladen. Kurze und zwingende Disziplin gehört in `instructions`,
langes, nur gelegentlich nützliches Wissen in einen skill.

## 3. Doku-Site {#三文档站}

Die Site, die du gerade liest, ist mit mkdocs-material gebaut, die Quelldateien liegen im Repository unter `docs/`, ein Push auf `main` veröffentlicht automatisch.

| Baustein | Was es ist |
|---|---|
| Konfiguration | `mkdocs.yml`, `docs_dir: docs` |
| Mehrsprachigkeit | `mkdocs-static-i18n`, `docs_structure: folder` — `docs/zh/`, `docs/en/` … Standardsprache ist `zh` |
| Abhängigkeiten | `docs-requirements.txt` (Versionen festgenagelt). **Nicht** das `docs`-Extra aus `pyproject.toml` — die CI installiert Ersteres |
| Build | `mkdocs build --strict`. Kaputte interne Links oder nav-Einträge auf nicht existierende Seiten lassen den Build fehlschlagen, statt still eine 404 zu veröffentlichen |
| Redirects | `hooks/redirects.py`, schreibt **nach** dem Build anhand der finalen URLs meta-refresh-Stubs, die die alten flachen Adressen (`/start/`, `/workflow/`, `/case-ht001/` …) an die neuen Orte hängen |
| Deployment | `.github/workflows/docs.yml` → `actions/upload-pages-artifact@v3` + `actions/deploy-pages@v4`, veröffentlicht auf GitHub Pages |

Dokumentation lokal ändern:

```bash
pip install -r docs-requirements.txt
mkdocs serve                  # lokale Vorschau
mkdocs build --strict         # vor dem Commit einmal laufen lassen, derselbe Befehl wie in der CI
```

Die CI löst bei einem Push auf `main` aus **und** nur, wenn die Änderung einen dieser Pfade trifft; zusätzlich lässt sie sich auf der Actions-Seite manuell per
`workflow_dispatch` starten:

```text
docs/**  mkdocs.yml  hooks/**  docs-requirements.txt  install.sh  .github/workflows/docs.yml
```

### Warum `install.sh` über Pages ausgeliefert wird {#installsh-为什么从-pages-发}

Am Ende des Build-Schritts steht eine Zeile:

```yaml
- run: cp install.sh site/install.sh
```

Das Installationsskript wandert in das Site-Artefakt und hängt damit an der Domain der Doku-Site; die Ein-Zeilen-Installation sieht so aus:

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Der Grund ist ganz praktisch: **`raw.githubusercontent.com` ist in China nicht erreichbar, `*.github.io` schon** (gemessen).
Das Skript selbst liegt in der Repo-Wurzel, beim Veröffentlichen wird lediglich eine Kopie mitgenommen — es gibt nichts doppelt zu pflegen und kein zusätzliches CDN.

Was `install.sh` selbst tut: einen Python-Werkzeuginstaller auswählen (`uv` > `pipx` > `uv` installieren > `pip --user`),
flower von GitHub installieren und dann auf den nächsten Schritt hinweisen. Es **fasst keine Credentials an** — der erste `flower`-Lauf fragt danach und legt sie in
`~/.config/flower/.env` ab.
