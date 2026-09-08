# Häufige Probleme und Fehlersuche

Wenn etwas kaputtgeht, weiß niemand, welches Modul kaputt ist — man weiß nur, was man gesehen hat.
Deshalb ist diese Seite nach **beobachtetem Symptom** gruppiert, nicht nach Subsystem.

Jeder Eintrag hat denselben Aufbau: **Symptom** (was du tatsächlich siehst) → **Ursache** → **Was tun**.

Fünf davon sind **bekannte Defekte**, kein Design. Diese Einträge sagen direkt, dass es ein Bug ist,
verlinken das Issue und nennen den Workaround — sie werden nicht als Absicht verkauft.

## Installation schlägt fehl / startet nicht {#装不上}

Der vollständige Installationsablauf steht in [install.md](../getting-started/install.md#一句话安装).
Dieser Abschnitt sammelt nur die Fälle „installiert, aber der Befehl läuft nicht".

### Python-Version niedriger als 3.10 {#python-版本}

**Symptom**: Während der Installation tauchen Syntaxfehler auf, oder pip sagt direkt, es finde keine
passende Version.

**Ursache**: flower verlangt Python ≥ 3.10. Die einzige Laufzeitabhängigkeit ist `claude-agent-sdk`,
das native Binary steckt in dessen Wheel — eine fehlgeschlagene Installation liegt also meist am
Interpreter, nicht am Netzwerk.

**Was tun**: Erst klären, in welchen Interpreter installiert werden soll.

```bash
python3 --version
```

Unter 3.10 einen anderen nehmen und neu installieren. Das mitgelieferte `python3` des Systems ist oft
nicht das, worauf `python` in deinem Terminal zeigt; die Version einmal vorher zu prüfen ist billiger
als hinterher zu suchen (siehe [install.md](../getting-started/install.md#装之前确认-python)).

### Installiert, aber `flower: command not found` {#command-not-found}

**Symptom**:

```text
zsh: command not found: flower
```

**Ursache**: Das Paket ist installiert, aber das Verzeichnis mit dem erzeugten ausführbaren Skript
liegt nicht im `PATH`. Das ist etwas anderes als „nicht installiert" — wenn
`python3 -c "import flower"` fehlerfrei läuft, ist das Paket in Ordnung.

**Was tun**: Die Shebang des `flower`-Skripts ist ein absoluter Pfad, ein Symlink in ein Verzeichnis,
das bereits im `PATH` liegt, reicht also; es muss nichts gesourct werden.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS: PATH nach dem Hinweis von `install.sh` gesetzt, trotzdem command not found {#macos-path}

!!! warning "Bekanntes Problem ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    Dieser Ratschlag versagt ausgerechnet auf der Maschine, die ihn braucht.

**Symptom**: Auf macOS `install.sh` durchlaufen lassen, dem letzten Hinweis folgend `~/.local/bin` in
den `PATH` aufgenommen, Terminal neu geöffnet — `flower` ist weiterhin command not found.

**Ursache**: Auf dem pip-Fallback-Pfad installiert das pip von macOS die ausführbaren Skripte nach
`~/Library/Python/3.X/bin`, während `install.sh` dazu auffordert, `~/.local/bin` hinzuzufügen. Die
beiden Verzeichnisse passen nicht zusammen, der Hinweis hilft also nicht.

??? note "In welcher Reihenfolge `install.sh` den Installationsweg wählt, und der Wortlaut dieses Hinweises"

    Die Priorität hat vier Stufen, nicht zwei (`install.sh:35-56`):

    ```text
    1. uv vorhanden        → uv tool install --force
    2. sonst pipx vorhanden → pipx install --force
    3. sonst                → curl astral.sh/uv/install.sh, uv bootstrappen, bei Erfolg damit installieren
    4. Bootstrap scheitert  → "$PY" -m pip install --user --upgrade    ← hier liegt das Problem
    ```

    Der Wortlaut des abschließenden PATH-Hinweises (`install.sh:62-68`, wird nur ausgegeben, wenn
    `command -v flower` nichts findet):

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` ist fest auf `$HOME/.local/bin` verdrahtet (`install.sh:63`). Für Weg 1 und 3 stimmt das
    — dort installiert uv; **nur Weg 4, der pip-Fallback, passt auf macOS nicht**. Die Falle tritt
    also nur auf Maschinen auf, auf denen die ersten drei Wege nicht durchkommen.

**Was tun**: Nicht raten, den Interpreter fragen.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Das ausgegebene Verzeichnis in den `PATH` aufnehmen, oder von dort nach `~/.local/bin` symlinken:

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip installieren nicht dasselbe flower {#三种装法}

**Symptom**: `flower` läuft, aber Änderungen am Quellcode wirken nicht; oder nach dem Upgrade läuft
weiterhin die alte Version; oder zwei Terminals auf derselben Maschine verhalten sich unterschiedlich.

**Ursache**: Die drei Installationswege legen Paket und ausführbares Skript an verschiedenen Orten
ab; was im `PATH` zuerst getroffen wird, läuft.

??? note "Wo die drei Installationswege landen"

    | Installationsweg | Ausführbares Skript | Wann |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | Quellcode ändern. Wirkt sofort |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Nur benutzen, isolierte Umgebung gewünscht |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Fallback. Verzeichnis siehe voriger Eintrag |

**Was tun**: Erst feststellen, welches gerade läuft, dann entscheiden, welches geändert wird.

```bash
which -a flower                      # listet alle gleichnamigen im PATH
head -1 "$(which flower)"            # worauf die Shebang zeigt, dort liegt auch das Paket
```

Für Quellcode-Änderungen venv + `-e .` benutzen und nicht parallel zu einer `uv`- / `pipx`-Installation
betreiben — Koexistenz kostet bei der Fehlersuche deutlich mehr als eine Neuinstallation
(siehe [install.md](../getting-started/install.md#从源码装)).

## Credentials und Gateway {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Symptom**:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Ursache**: flower schottet mit `setting_sources=[]` die Host-Konfiguration ab, Credentials müssen
selbst mitgebracht werden. Die vollständige Suchreihenfolge steht in
[config.md](config.md#凭证查找优先级).

**Was tun**: In die `.env` im Repository-Root schreiben, oder in die Prozessumgebung.

```bash
cp .env.example .env        # ANTHROPIC_AUTH_TOKEN oder ANTHROPIC_API_KEY eintragen
```

`.env` ist bereits per gitignore ausgeschlossen. Die Variante im Container steht in
[deploy.md](deploy.md#凭证).

### Es sagt „flower liest `~/.claude/settings.json` nicht" — dieser Satz ist falsch {#settings-json}

**Symptom**: Wenn die Credentials nicht stimmen, gibt `env.py:192` diesen Satz aus:

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Ursache**: Der Satz widerspricht dem Code. `env.py:56-75` **liest** `~/.claude/settings.json`
sehr wohl, greift daraus nur die Credential-Felder ab und benutzt sie als letzten Fallback — genau
damit wirbt auch `install.sh`. Der Satz wird erst gedruckt, nachdem dieser Fallback leer ausgegangen
ist, er lässt also nichts scheitern; aber er verleitet zu dem Schluss „flower kann meinen
Claude-Code-Token nicht benutzen", und der ist falsch. Notiert in
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**Was tun**: Wer Claude Code lokal installiert hat, muss keine neuen Credentials beantragen, der
Fallback greift sie selbst auf
(siehe [install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
Wenn dieser Satz wirklich erscheint, enthält auch diese Datei keine brauchbaren Credential-Felder —
dann nach dem vorigen Eintrag eine `.env` schreiben.

### Unklar, welche Credentials und welcher Endpunkt tatsächlich greifen {#生效值}

**Symptom**: `.env` wurde geändert, die Requests gehen trotzdem an das alte Gateway; oder es ist
unklar, welches Modell gerade benutzt wird.

**Ursache**: Credentials und Endpunkt haben mehrere Quellen (Prozessumgebung, `.env`, Fallback); wer
gewinnt, entscheidet nicht die Konfigurationsdatei, sondern die Laufzeit.

**Was tun**: Einmal mit `-v` starten. Beim Start wird `describe()` gedruckt: die wirksame `BASE_URL`
und das Modell-Mapping, Token maskiert.

```bash
flower -v
```

Die vollständige Schalterliste steht in [cli.md](cli.md#全局开关), die vollständige Variablenliste in
[config.md](config.md#环境变量).

### Ein `KEY=` in der `.env` blockiert alle nachgelagerten Quellen {#空值占位}

**Symptom**: In der Prozessumgebung ist ein Token exportiert, in der `.env` steht außerdem die Zeile
`ANTHROPIC_AUTH_TOKEN=`, und es kommt trotzdem „Credentials fehlen".

**Ursache**: Ein leerer Wert ist auch eine Zuweisung. Das `KEY=` aus der höherpriorisierten Quelle
**belegt** den Schlüssel, niedriger priorisierte Quellen füllen ihn nicht mehr auf; und
`check_credentials()` (definiert in `env.py:184`) prüft auf „Wert nicht leer", meldet also weiterhin
Fehlen. „Belegt" und „fehlt" sind zwei verschiedene Dinge, sehen aber exakt gleich aus — das macht
diese Fehlerklasse am schwersten selbst erkennbar.

**Was tun**: Die ganze Zeile löschen, keine leeren Werte stehen lassen.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # listet alle Zeilen mit leerem Wert
```

Danach mit `-v` die wirksamen Werte noch einmal prüfen. Die Parse-Regeln stehen in
[config.md](config.md#env-解析).

### Drittanbieter-Gateway: Verbindung steht, aber die erste Runde scheitert {#网关}

**Symptom**: 401 / 403; oder die Meldung, der Modellname existiere nicht; oder gleich zu Beginn ein
[Handoff](glossary.md#换代) mit der Meldung „Startup-Floor".

**Ursache**: Drei Arten von Fehlkonfiguration, jede mit eigenem Erscheinungsbild.

??? note "Drei Gateway-Fehlkonfigurationen und wie man sie auseinanderhält"

    | Symptom | Meist | Wo ansetzen |
    |---|---|---|
    | 401 / 403 | Die Credentials stimmen, sind aber nicht von diesem Gateway ausgestellt; oder der `BASE_URL` fehlt ein Pfad bzw. hat einen Slash zu viel | [config.md](config.md#凭证变量) |
    | Modellname existiert nicht | Das Gateway kennt nur seine eigenen Modellnamen, das Mapping fehlt | [config.md](config.md#模型变量) |
    | Handoff direkt zu Beginn, Meldung „Startup-Floor" | Fenster zu klein konfiguriert: die Schwelle liegt unter dem Startup-Floor der Rolle (beim [Coordinator](glossary.md#协调者) gemessen ca. 34k) | `--window`, siehe [handoff.md](../guide/handoff.md#阈值怎么算) |

**Was tun**: Erst mit `-v` die wirksamen Werte ausgeben lassen, dann an der Konfiguration drehen.
Besonders das Fenster lohnt den Abgleich: Das Gateway der Entwicklungsmaschine ist auf
`claude-opus-5[1m]` konfiguriert; hätte man früher mit 200.000 gerechnet, wäre alle 150.000 ein
Handoff fällig gewesen, während es tatsächlich bis 950.000 durchhält — **Faktor 5 Unterschied**,
[long-horizon](glossary.md#长程) Arbeit wird dadurch in Fetzen geschnitten.

---

## Läuft, verhält sich aber falsch {#行为不对}

Die Symptome dieser Gruppe sind keine Fehlermeldungen: **der Befehl läuft durch, Exit-Code 0, und tut
trotzdem das Falsche.** Die ersten vier sind bestätigte Code-Defekte, die Issues sind eingereicht;
was hier steht, ist der Workaround, nicht der Fix. Der letzte Punkt ist so gewollt.

### `flower setup` startet einen Agent {#setup-跑成了-agent}

**Symptom**: Man führt `flower setup` aus und erwartet Fragen nach Endpunkt und Token; stattdessen
fragt es „was soll getan werden", durchläuft den kompletten go-Ablauf und behandelt das Wort `setup`
als Aufgabenbeschreibung. Am Ende ist kein einziges Zeichen an Credentials geschrieben worden.

**Ursache**: `_CMDS` in `cli.py:937` listet nur `"go"`, `"run"`, `"once"` und hat `"setup"`
vergessen. Der Schritt, der das Default-Subkommando ergänzt, schreibt argv `["setup"]` damit zu
`["go", "setup"]` um — `setup` wird vom Subkommando zum ersten Positionsargument von `go`
degradiert, also zum Anliegen selbst. **Es gibt kein argv, das den Konfigurationsassistenten
erreicht.** Gemeldet als [#11](https://github.com/ChenyuHeee/flower/issues/11).

**Was tun**: Mit Ctrl-C abbrechen und die Konfigurationsdatei direkt schreiben. `setup` hätte
ohnehin nichts anderes getan, als in diese Datei zu schreiben:

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Die vollständigen Variablennamen und die Suchreihenfolge für Credentials stehen in
[config.md](config.md#凭证变量).
Danach in einem beliebigen Verzeichnis einmal `flower -v` laufen lassen; der beim Start gedruckte
wirksame Endpunkt ist die Gegenprobe.

### Das Vollbreiten-`？` löst keine Oracle-Frage aus {#全角问号}

**Symptom**: Man tippt gemäß [Oracle-Frage](cli.md#旁路问答) am Eingabeprompt `？这个目录能删吗`,
und statt den [Oracle](glossary.md#旁路顾问) zu starten, wird der Satz als Antwort auf die aktuelle
Frage behandelt oder unverändert in den Posteingang aufgenommen.

**Ursache**: `cli.py:907` macht zweimal hintereinander ein `startswith("?")` und benutzt
**beide Male dasselbe ASCII-Zeichen**. Der Absicht des Codes nach hätte der zweite Test auf das
Vollbreiten-`？` prüfen müssen. Chinesische Eingabemethoden erzeugen standardmäßig genau dieses
Vollbreitenzeichen — die Hauptnutzer dieser Funktion können sie also ausnahmslos nicht benutzen.
Gemeldet als [#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "Das verunreinigt die Anforderung"
    Ein ins Leere laufendes `？` erzeugt keinen Fehler und wird auch nicht verworfen. Es wird als
    normale Eingabe behandelt: in der Clarify-Phase als Antwort auf die aktuelle Frage, sonst
    landet es im Posteingang.
    **Ein Satz, den du nur unter vier Augen fragen wolltest, landet im Brief.** Wenn du den Fehler
    bemerkst, korrigiere sofort `.flower/notes/需求.md`; diese Datei ist der Maßstab für alles
    Nachgelagerte.

**Was tun**: Auf Halbbreite umschalten und `?` tippen, oder erst das halbbreite `?` setzen und dann
für den Fließtext zurück auf Chinesisch wechseln.

### Bei `once` sind die kumulierten Kosten immer `$0.00` und die Dauer immer `0:00` {#once-计数为零}

**Symptom**: `flower once` läuft von Anfang bis Ende durch, die Statuszeile am unteren Rand zeigt
durchgehend `累计 $0.00`, der Timer bleibt auf `0:00` — während dasselbe Modell mit derselben Arbeit
unter `go` Zahlen liefert.

**Ursache**: Das `render()` von `once` **erzeugt bei jedem eingehenden Event ein neues `Render`**,
die Akkumulatoren werden mit neu aufgebaut und starten jedes Mal bei null. Die kumulierten Werte
werden also wiederholt auf null gesetzt, nicht etwa gar nicht erfasst.
Gemeldet als [#14](https://github.com/ChenyuHeee/flower/issues/14).

**Was tun**: Wer korrekte Zahlen braucht, nimmt `go`, dieser Pfad ist nicht betroffen. Wer die
Ein-Runden-Form von `once` will und trotzdem abrechnen möchte, schaut nach dem Lauf in
`runs/manifest.json` — die Kosten jedes Schritts stehen dort, und diese Aufzeichnung stimmt.
Details in [config.md](config.md#run-dir).

### Skills unter `plugin/` werden nie geladen {#plugin-不加载}

**Symptom**: Skill nach [deploy.md](deploy.md#写一个-skill完整例子) geschrieben, Verzeichnisstruktur
stimmt, aber der Agent verhält sich, als wüsste er nichts davon — **keine Fehlermeldung, keine Zeile
Log**.

**Ursache**: `plugin/` ist nicht ins Wheel gepackt. Im installierten Paket zeigt `PLUGIN_DIR` auf
`<site-packages>/plugin`, dieses Verzeichnis existiert nicht, und die Existenzprüfung vor dem Laden
überspringt stillschweigend. **Alle drei Pfade von `install.sh` sind betroffen**, nur ein
Quellcode-Checkout kann laden.
Gemeldet als [#15](https://github.com/ChenyuHeee/flower/issues/15).

**Was tun**: Zuerst selbst prüfen, wohin der Pfad tatsächlich aufgelöst wird.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Wird `False` ausgegeben, ist es dieser Fall. Wer Skills nutzen will, hat derzeit genau eine
Möglichkeit: **aus einem Quellcode-Checkout laufen lassen**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Ein mit `-e` installiertes Paket zeigt zurück auf das Checkout-Verzeichnis, `PLUGIN_DIR` landet auf
dem echten `plugin/`, und dieselbe Prüfung gibt dann `True` aus.

### `-T` zeigt bei `go` keine Wirkung {#trim-与-go}

**Symptom**: `flower go` mit `-T` aufgerufen; mit und ohne verhält es sich exakt gleich, als wäre der
Schalter kaputt.

**Ursache**: **Das ist so gewollt, kein Defekt.** Der `go`-Pfad hat [Trim](glossary.md#裁剪)
ohnehin standardmäßig an, die Absicht hinter `-T` ist bereits erfüllt, ein zweites Mal ändert nichts.
Der eigentliche Schalter auf diesem Pfad ist der umgekehrte `--no-trim` — nur um Trim abzuschalten
muss man ihn explizit setzen. `-T` ist nur bei `run` und `once` ein sinnvoller Schalter.

**Was tun**: Um bei `go` zu bestätigen, dass Trim wirklich an ist, den Startausdruck mit `-v`
anschauen und nicht aus An-/Abwesenheit von `-T` schließen; zum Abschalten `--no-trim` geben. Die
vollständige Semantik der Schalter steht in [cli.md](cli.md#全局开关).

## Es sagt fertig, ist aber nicht fertig {#没做完}

Der [Goal Guard](../guide/goal.md) existiert genau dafür — Worker haben einen systematischen
Optimismus-Bias, sie wissen, was sie getan haben, aber nicht, was sie ausgelassen haben. Aber auch
der Guard urteilt falsch, und die Richtung des Fehlurteils hat System. Die folgenden fünf Punkte
sind getrennt nach „hat durchgewinkt, was nicht durchgehen durfte" und „winkt gar nichts durch".

### Es sagt „hier nicht überprüfbar" und lässt es dann durch {#无法达成不是未达成}

**Symptom**: Im Verdikt steht „in der aktuellen Umgebung nicht überprüfbar, gilt als erreicht", und
der Workflow läuft weiter.

**Ursache**: Der [Judge](glossary.md#判定者) hat „nicht erreichbar" und „nicht erreicht" zu einer
Schlussfolgerung vermischt. Das sind **zwei verschiedene Schlussfolgerungen**, und genau darum geht
es in [Drei Schlussfolgerungen, nicht zwei](../guide/goal.md#三个结论不是两个):
„nicht erreicht" heißt zurückgeben und weiterarbeiten, „nicht erreichbar" heißt **anhalten und
nachfragen** — akzeptieren, Ziel ändern, oder feststellen, dass der Judge falsch lag.
Gibt es nur die zwei Schlussfolgerungen „erreicht/nicht erreicht", dreht ein tatsächlich unmögliches
Ziel den Coordinator Runde um Runde leer, bis das Kontingent aufgebraucht ist.

**Was tun**: **„Hier nicht überprüfbar" darf nie als erreicht gelten.** In den `instructions` für den
Judge namentlich festhalten, was in deinem Szenario als nicht machbar zählt, damit er „nicht
erreichbar" liefert, wenn „nicht erreichbar" angebracht ist.
Wer wirklich nicht angehalten und gefragt werden will, gibt `--timeout 0`: bei „nicht erreichbar"
wird direkt gestoppt und die Begründung bleibt auf Platte, statt durchgemogelt zu werden.

### Es liest den Quellcode und erklärt die Sache für erledigt {#判产出物}

**Symptom**: Die Begründung des Verdikts lautet „im Code ist X bereits implementiert", „die
Funktionssignatur entspricht der Anforderung", aber Build-Artefakt, Kommandoausgabe und laufender
Dienst wurden nicht ein einziges Mal angefasst.

**Ursache**: Der Judge wurde auf den Quellcode gelenkt.
[Beurteilt wird das Artefakt, nicht der Quellcode](../guide/goal.md#判的是产出物不是源码) — ob der
Quellcode richtig aussieht und ob das Abgelieferte benutzbar ist, sind zwei verschiedene Dinge.
Ersteres ist das, wovon der Worker bereits überzeugt ist; es noch einmal zu bestätigen erzeugt keine
neue Information.

**Was tun**: Prüfpunkte müssen als Aussagen über das **Artefakt** formuliert sein. „Export-Funktion
implementiert" zählt nicht, „`./app export out.csv` ausführen, `out.csv` hat 3 Spaltenüberschriften"
zählt. So sollte es schon beim Formulieren des Ziels geschrieben werden, sonst muss der Judge die
vagen Punkte selbst ergänzen.

### Der Judge kann keine Befehle ausführen, also liest er das Makefile und winkt durch {#判定者不能跑命令}

**Symptom**: Das Ziel lautet „ein unter Linux lauffähiges Binary bauen", das Verdikt ist positiv.
Ein eigenes `file` zeigt: das Artefakt ist Mach-O, überhaupt kein ELF.

**Ursache**: Der Judge ist standardmäßig `judge(can_run=False)` und hat **nur `Read` / `Glob` /
`Grep`** zur Hand. Diese drei Werkzeuge können Dateien lesen, aber **weder `file` noch
`./app --version` ausführen**. Also weicht er aus, liest das Makefile, sieht im Darwin-Zweig
Cross-Compilation stehen und hält die Bedingung für erfüllt.
Er hat nicht gelogen, er hat nur **im Rahmen seiner Möglichkeiten das gefunden, was einem Beweis am
ähnlichsten sieht**.

??? note "Wann `can_run` zwingend eingeschaltet werden muss"
    Die Entscheidungsregel ist einfach: **Sobald im Ziel Begriffe wie „das Gebaute" vorkommen,
    einschalten.**

    - Artefakt-Art: Binary, Image, Paketdatei, generierte Daten — einschalten
    - Verhaltens-Art: Dienst startet, Befehl liefert 0, Ausgabe passt auf ein Muster — einschalten
    - Reine Text-Art: Doku geschrieben oder nicht, Feld im Schema ergänzt oder nicht — nicht nötig

    Auf der Kommandozeile ist das `--judge-can-run`. Beim eigenen Verdrahten sehen die Einstiege
    unterschiedlich aus, laufen aber alle auf denselben Parameter von `judge()` hinaus:

    | Einstiegspunkt | Wie übergeben | Fundstelle |
    |---|---|---|
    | `judge()` | `can_run=` ist ein echter Parameter | `roles.py:361` |
    | `with_goal()` | `can_run=` ist Parameter und wird an `judge()` weitergereicht | `goal.py:155` → `:170` |
    | `goal_step()` | **kein `can_run`-Parameter**, aber es landet in `**spec_kw`, und genau diese Zeile lautet `judge(..., **spec_kw)` — kommt also an | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, wird zu `with_goal(can_run=…)`; `--judge-can-run` geht genau diesen Weg | `starter.py:105` → `:196` |

    Der Preis: Der Judge führt tatsächlich Befehle aus, eine Verdikt-Runde wird langsamer und teurer;
    dafür prüft er den **tatsächlichen Zustand** und nicht dessen Beschreibung. Siehe
    [Darf der Judge Befehle ausführen](../guide/goal.md#判定者能不能跑命令).

**Was tun**: Geht es im Ziel um Artefakte, `--judge-can-run` einschalten. Wenn nicht eingeschaltet,
gilt beim Formulieren der Prüfpunkte die harte Nebenbedingung „was lesbar ist, ist beurteilbar" —
ein Punkt, der sich so nicht formulieren lässt, brauchte von vornherein die Ausführung von Befehlen.

### Die Prüfliste hat über ein Dutzend Punkte und geht nie durch {#清单长度}

**Symptom**: Jede Runde wird zurückgewiesen, mit einer langen Liste, woran es fehlt; je mehr
korrigiert wird, desto mehr wird es, die Arbeit wird nie fertig.

**Ursache**: Die Liste wurde nach „wie gründlich will ich sein" geschrieben, nicht nach „wie viele
Arten hat diese Arbeit zu scheitern".
[Die Länge der Liste bestimmt sich aus der Anzahl der Fehlermodi](../guide/goal.md#清单的长度由有多少种失败方式决定):
Für eine Aufgabe wie `git clone && make && ./app` reichen **drei bis fünf Punkte** — Build
erfolgreich, startet, benutzbar.
Bei dem realen Absturz in [HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了) wurde die
Aufgabe „das Repository installieren und laufen lassen" zu **15 Punkten** ausformuliert: nur 5 davon
prüften, ob etwas benutzbar ist, 6 prüften, ob der Prozess eingehalten wurde, und 4 waren
**prinzipiell nicht überprüfbar**.

**Was tun**: `.flower/notes/目标.md` ändern, diese Datei ist die Grundlage des Verdikts. Punkt für
Punkt fragen „welchem Fehlermodus entspricht dieser Punkt"; was sich nicht beantworten lässt, wird
gelöscht. Der Schritt zum Setzen der Ziele schlägt bei nicht überprüfbaren Punkten ohnehin Alarm —
die angemahnten Punkte nicht mit Gewalt drinlassen.

### Grenzen wurden als Prüfpunkte geschrieben {#边界不是判定项}

**Symptom**: In der Liste tauchen Punkte auf wie „`brew install` wurde nicht ausgeführt" oder
„außerhalb des Projektverzeichnisses wurde keine Datei verändert", und der Judge prüft zur eigenen
Entlastung die mtime von `~/.zshrc` und ob am Verzeichnis `.flower/` etwas angefasst wurde.

**Ursache**: Grenzen und Prüfpunkte schränken Verschiedenes ein; sie zu vermischen war die
Hauptursache des Absturzes in HT002
([Ursache eins](../cases/ht002.md#根因一边界被当成了判定项)).

| | Was wird eingeschränkt | Wie einhalten |
|---|---|---|
| **Grenzen** | **Wie du arbeitest** („nur innerhalb des Projektverzeichnisses installieren", „Fachcode nicht anfassen") | Durch **Nicht-Überschreiten**, nicht durch nachträglichen Selbstbeweis |
| **Prüfpunkte** | **Das Abgelieferte** („läuft es", „stimmt das Ergebnis") | Durch Verifikation vor Ort |

Grenzen sind genau der Abschnitt, den man in der Clarify-Phase ausdrücklich vollschreiben soll. Sie
einzeln in die Prüfliste zu übernehmen bedeutet: jede zusätzliche Grenze ist eine zusätzliche
Prüfung, und die meisten dieser Prüfungen sind nicht durchführbar — nicht überprüfbare Punkte reißen
die ganze Verdikt-Runde mit ins Scheitern.

**Was tun**: Grenzen bleiben im Abschnitt „Grenzen" des Briefs und werden durch Nicht-Überschreiten
eingehalten, nicht in die Prüfliste. Wenn wirklich Rechenschaft nötig ist, ein Satz dazu,
**nicht in sechs Punkte aufgespalten**.

---

## Kontext und Kosten {#上下文与花费}

In long-horizon Runs sind Kontext und Geld dasselbe Problem: Der Kontext läuft voll, dann kommt
entweder ein Handoff oder dieser Schritt fliegt; und jeder Satz, der in einer Runde wiederholt wird,
muss in jeder folgenden Runde erneut bezahlt werden.

### Mitten im Lauf öffnet es selbst eine neue Session und sagt „Handoff" {#换代打断}

**Symptom** Im Eventstrom taucht `handoff` auf, `payload["phase"]` erst `near`, dann `done`,
dazwischen eine zusätzliche Runde Zeit für das Schreiben des [Handoff-Dokuments](glossary.md#交接书),
danach geht die Arbeit normal weiter.

**Ursache** Der Kontext nähert sich der Schwelle. flower **macht kein compact** — es schreibt den
Zustand der aktuellen Session als fünfteiliges Handoff-Dokument und startet eine neue Session, die
es liest und weitermacht. [Compact](glossary.md#压缩) löscht die teuersten Informationen gleich mit,
etwa „Wege, die nicht funktionieren"; das Handoff-Dokument dagegen ist explizit, liegt auf Platte und
ist jederzeit änderbar: Die übernehmende Session liest genau diese Datei.

**Was tun** Das ist der Normalpfad, nichts zu tun. Ein Handoff zählt nicht als Retry — `attempts`
steigt nicht (es zählt Fehlschläge), die verbrannte session_id steht in `StepResult.retired`, und die
nach außen sichtbare `session_id` ist immer der noch lebende Nachfolger
(siehe [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
Wer wirklich zum Auto-Compact des SDK zurück will, nimmt `--no-handoff`.

??? note "Woher die Schwelle kommt und warum der Default so aggressiv gewählt ist"
    `at = window - headroom`. `window` ist **standardmäßig 1 Million**, bestimmt nach Modellname: Namen
    mit `haiku` gelten als 200.000, alle anderen als 1 Million. `headroom` ist standardmäßig 50k —
    Auto-Compact greift bei −33k, der Handoff muss davor sein, und das „Handoff schreiben" selbst
    braucht noch eine Runde; 50k erfüllt beides gleichzeitig.

    Zu groß geschätzt ist kein harter Fehler: Ist das echte Fenster kleiner, wird die Schwelle nie
    erreicht, der Request wird von der API mit „prompt zu lang" abgelehnt, flower erkennt dieses
    Signal (`handoff.is_overflow()`) und macht auf der Stelle mit einem mechanisch
    zusammengesetzten Ersatzdokument einen Handoff — der Schritt scheitert nicht
    (siehe [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    Ein Messwert, der Erwähnung verdient: Das Gateway der Entwicklungsmaschine ist auf
    `claude-opus-5[1m]` konfiguriert. Hätte man früher mit 200.000 gerechnet, wäre alle 150.000 ein
    Handoff fällig gewesen, während es tatsächlich bis 950.000 durchhält — **Faktor 5 Unterschied**,
    long-horizon Arbeit wird dadurch in Fetzen geschnitten.

### Handoff gleich zu Beginn, und es hört nicht auf {#一开局就换代}

**Symptom** Die Fehlermeldung erwähnt „Startup-Floor", oder derselbe Schritt macht immer wieder
Handoffs, bis `max_generations=8` erreicht ist.

**Ursache** `window` ist zu klein konfiguriert, die Schwelle liegt unter dem Startup-Floor dieser
Rolle — beim Coordinator gemessen ca. 34k, allein System-Prompt plus [Workbench](glossary.md#工作台)-Index
verbrauchen das. Die neue Session überschreitet die Linie mit dem ersten Wort, also Handoff
schreiben, Generationswechsel, wieder überschreiten, endlos
(Handoffs zehren nicht am Retry-Kontingent, das ist Absicht).

**Was tun** `--window` auf das echte Fenster des Modells setzen; `-v` druckt den wirksamen Endpunkt
und das Modell-Mapping. Ein normaler langer Lauf braucht keine 8 Generationen; wer tatsächlich
dagegenläuft, hat fast sicher diese Ursache, und die Fehlermeldung sagt genau das
(siehe [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
Ein verwandtes Symptom ist „das Handoff-Dokument ist immer die Notvariante": Der Grund steht unter
`errors` in `runs/manifest.json`.

### Bleibt auf halbem Weg stehen mit der Meldung, das Budget sei erschöpft {#预算到顶}

**Symptom** Ein [Schritt](glossary.md#步骤) hört unfertig auf, Begründung: Kostenlimit überschritten.

**Ursache** `AgentSpec(max_budget_usd=...)` ist ein **hartes Limit**, keine sanfte Erinnerung;
`Runtime.total_cost()` ist die Summe dieses Runs.

**Was tun** Vor dem Anheben des Limits sicherstellen, dass es sich nicht im Leerlauf dreht. Runde um
Runde zurückgewiesen ohne Fortschritt heißt meist, dass der Judge „nicht erreichbar" hätte geben
müssen und stattdessen „nicht erreicht" gegeben hat — ein tatsächlich unmögliches Ziel brennt bis
zum Kontingentende weiter
(siehe [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Erst bestätigen, dass wirklich gearbeitet wird, dann das Limit anheben.

### Warum war dieser Lauf so teuer {#为什么这么贵}

**Symptom** Die Kosten liegen weit über der Erwartung, aber an der Ausgabe ist nicht abzulesen, wo
das Geld geblieben ist.

**Ursache** Die Abrechnung steht nicht im Kontext des Modells. `session_id`, Kosten, Anzahl der
Retries und Fehlergründe jedes Schritts stehen nur in `runs/manifest.json`, **prozessübergreifend
angehängt**. Auch die Retry-Historie und die Original-Fehlertexte stehen nur dort — das Modell sieht
sie nicht, und das ist Absicht: Häufen sich abgelehnte Aufrufe im Kontext, lernt der Coordinator
„Bash wird sowieso blockiert" und probiert nicht einmal mehr `git status`
(`Runtime(keep_denials=1)` räumt standardmäßig auf, nicht hochdrehen).

**Was tun** `runs/manifest.json` öffnen und die Kosten pro Schritt abgleichen (das Plattenlayout
steht in [config.md#磁盘布局](config.md#磁盘布局)).
Einige gemessene Referenzwerte:

| | Kosten |
|---|---|
| Startup-Floor eines Subagents (nicht amortisierbar) | ~4.3k tokens |
| Startup-Floor des Coordinators | ~34k tokens |
| `tests/smoke.py` Einzel-Agent über die ganze Kette | ~$0.21 |
| `tests/flow_demo.py` Workflow in drei Verdrahtungen | ~$0.39 |
| `tests/delegation.py` Arbeitsteilung + Vermessung der Kontextverteilung | ~$0.71 |
| `tests/isolation.py` drei Issues, drei Worktrees | ~$0.9 |

### Der Kontext wächst schneller als die Arbeit vorangeht {#上下文涨得快}

**Symptom** In jedem [Task Brief](glossary.md#任务书) wird dieselbe Disziplin wiederholt („erst die
Datei lesen, dann ändern", „Fachcode nicht anfassen", „nach der Änderung Tests laufen lassen"),
obwohl der [Worker](glossary.md#执行者) sich ohnehin daran hält.

**Ursache** Jeder Satz des Coordinators landet in dessen eigenem Transcript, und ein Transcript
wächst nur. Die Disziplin noch einmal aufzusagen kostet in dieser Runde Geld — **und in jeder
folgenden Runde noch einmal für denselben Abschnitt**. Was das Gegenüber schon weiß, bringt bei
Wiederholung null Ertrag und kostet dauerhaft.

**Was tun** Disziplin gehört in den Mechanismus, nicht in jede Runde Text: Was sich über
`allowed_tools`, den Abschnitt „Grenzen" im Brief oder den Workbench-Index ausdrücken lässt, gehört
nicht in den Task Brief; der Task Brief enthält nur, was sich in dieser Runde geändert hat. Die
Arbeitsteilung selbst ist die Schicht, die am meisten spart
(siehe [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
Beim Resume lassen sich alte große Tool-Ergebnisse mit `-T` durch Dateizeiger ersetzen.

## Unterbrechung und Kontinuität {#中断与接续}

### Der Prozess wurde gekillt, die Maschine neu gestartet {#进程被杀}

**Symptom** Mitten im Lauf ist alles weg, und nach dem Neuöffnen des Terminals ist unklar, wie man
wieder anknüpft.

**Ursache** Es gibt nichts aufzusammeln. Die [Lineage](glossary.md#血缘) (`runs/lineage.json`) hält
Schrittname → session_id fest, wird am Ende jedes Schritts auf Platte geschrieben, und zwar erst als
`.tmp` und dann per atomarem Replace — ein Kill mittendrin hinterlässt keine halbe Datei.

**Was tun** In **dasselbe Verzeichnis** zurückkehren und noch einmal `flower` starten; jeder Schritt
knüpft an seine bisherige Session an: Die Anforderung wird nicht erneut abgefragt, die Ziele werden
nicht erneut gesetzt, und selbst welche Sackgassen der Coordinator schon probiert hat, ist noch
bekannt. Wer nichts sagen will, drückt einfach Enter
(siehe [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
Der Judge ist die Ausnahme — er ist kein `Step`, sondern wird direkt aus dem Gate heraus entsandt und
läuft nie über die Lineage, also ist er in jeder Runde ein frisches Paar Augen.

### Es fängt jedes Mal von vorn an, knüpft überhaupt nicht an {#接不上}

**Symptom** Ein erneuter Lauf im selben Verzeichnis fragt die Anforderung wieder komplett ab.

**Ursache** Bei drei Arten von „passt nicht" fällt flower ausnahmslos **still auf Neubeginn zurück
und meldet keinen Fehler** — [Kontinuität](glossary.md#接续) ist Zugabe, ihr Ausfall darf niemanden
an der Arbeit hindern:

- `runs/lineage.json` fehlt, oder das darin stehende `workspace` passt nicht zu deinem aktuellen Pfad (so ist es, wenn das Verzeichnis kopiert wurde)
- Die Session steht nicht mehr in `runs/sessions.db` (Datenbank gelöscht)
- Die Lineage-Datei ist beschädigt

**Was tun** Zuerst schauen, ob `runs/lineage.json` existiert und ob `workspace` stimmt
(die Aufgaben der drei Dateien stehen in [../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
Dass nach einem Verzeichniswechsel nicht angeknüpft wird, ist **Absicht**: `project_key` wird aus dem
Workspace-Pfad abgeleitet, und die alte Session ist am neuen Ort nicht auffindbar.

### Neu anfangen, ohne die Historie zu verlieren {#想重开}

**Symptom** Die Anforderung hat die Richtung gewechselt, und es soll nicht am alten Kram
weitererzählt werden.

**Ursache** Das Standardverhalten ist Weitererzählen. `flower "顺便支持代码块高亮"` in einem bereits
benutzten Verzeichnis ist keine neue Aufgabe, sondern ein weiterer Satz.

**Was tun** `--new`. Das ist **Archivieren, kein Löschen**, das Alte bleibt in `notes/archive/`.
Beim [Wake](glossary.md#唤醒) wird zuerst eine Zeile mit der aktuellen Kontextgröße gemeldet; wem die
zu groß ist, geht ebenfalls diesen Weg.

### Netzwerk weg, es meldet nichts und bewegt sich nicht {#断网}

**Symptom** Auf der Oberfläche kommen keine neuen Events, der Prozess lebt noch, es sieht aus wie
hängengeblieben.

**Ursache** Netzausfall wird als „kurz warten" behandelt, nicht als Fehlschlag. flower wartet:
erst DNS probieren, dann TCP, und erst wenn es durchgeht, weitermachen
(siehe [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
In HT001 wurde das durch einen echten Ausfall bestätigt
(siehe [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**Was tun** Warten; mit `-v` sieht man die Probes laufen. Die während der Wartezeit angefallenen
Fehler **kommen nicht in den Kontext nach der Fortsetzung** — sie landen nur in
`runs/manifest.json`, und die übernehmende Session sieht einen sauberen Zustand und lässt sich nicht
von einer Kette von Timeouts in die Irre führen.

### Zweimal Ctrl-C hintereinander, der Abschluss läuft nicht vollständig {#双重-ctrl-c}

**Symptom** Ein Beenden per `kill` (SIGTERM) und zweimal Ctrl-C hinterlassen unterschiedliche Zustände.

**Ursache** Bekannte Lücke. Doppeltes Ctrl-C wirft ein `KeyboardInterrupt`: das `finally` von
`_drive` in `cli.py` ruft `rt.close()`, aber **nicht** `rt.rescue()` — nur der Handler für
SIGHUP/SIGTERM ruft `rescue()`.

**Was tun** Die Lineage bleibt auf beiden Pfaden erhalten (nach jedem Schritt atomar auf Platte),
ein erneuter Lauf knüpft also trotzdem an, und diese Lücke kostet keinen Fortschritt. Wer den
vollständigen Abschluss will, nimmt `kill <pid>` statt wild auf Ctrl-C zu hämmern.

## Parallelität und Isolation {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Symptom** Mit eingeschalteter Isolation startet es nicht und meldet `not in a git repository`.

**Ursache** `worker(..., isolate=True)` gibt jedem Agent über git worktree eine private Kopie; ist
der Workspace kein git-Repository, lässt sich die nicht anlegen.

**Was tun** Hier gibt es **keine stille Degradierung** — entweder wirklich in einem Repository laufen
lassen, oder `isolate` abschalten. Isolation garantiert, dass mehrere Agents gleichzeitig ändern
können, ohne die Arbeitsbäume der anderen zu sehen; sie garantiert dir keine konfliktfreie
Zusammenführung.

### Ein isolierter Agent kann nicht in die Workbench schreiben {#隔离写不进工作台}

**Symptom** Der Subagent meldet „Schreibrecht verweigert", Skripte und Artefakte landen nicht auf
Platte; oder die Artefakte landen in einem bestimmten Worktree und die anderen Agents sehen sie nicht.

**Ursache** Ein Worktree ist die **private Kopie** je Agent, die Workbench ist die **gemeinsame
Schicht** über Agents hinweg. Wer Gemeinsames in einen privaten Zaun stellt, macht es für die
anderen unerreichbar.

**Was tun** Bei eingeschalteter Isolation die Workbench **außerhalb des Repositories** ansiedeln:

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

Liegt sie außerhalb des Workspace, erteilt `Runtime` die Freigabe automatisch per `add_dirs`;
`Runtime(workbench=True)` erledigt das bereits, bei einer selbst gebauten `Workbench` musst du die
Freigabe selbst geben.

!!! warning "Die Workbench hat zwei Defaultpositionen, und sie sind verschieden"
    `Workbench(workspace)` — den Weg gehen CLI und `starter_flow()` — legt die Workbench nach
    `<workspace>/.flower`;
    `Runtime(workbench=True)` (also `-W`) legt sie dagegen nach `<run_dir>/workbench`, also
    `runs/workbench`.
    Ein `flower`-Lauf liefert dir also ein `.flower/`, ein `Runtime(workbench=True)` in Python
    **nicht**.

### Bei `flower` gibt es `.flower/`, beim eigenen Skript nicht {#两个工作台默认值}

**Symptom** Der Brief wurde nachweislich nach `.flower/notes/需求.md` geschrieben, der Coordinator
verhält sich aber, als hätte er ihn nie gelesen; **kein Fehler**.

**Ursache** Du hast zwei Workbench-Objekte in der Hand. Der Brief wird nach Verzeichnis A
geschrieben, der in den System-Prompt injizierte Index scannt Verzeichnis B, und die Zusage „von
Anfang an weiß es, wo die Anforderungsdatei liegt" **fällt still aus**. Beide Fehlerarten melden
nichts: Ein selbst zusammengebauter `brief_path` relativ zum Prozess-cwd und das von `-W` erzeugte
`<run_dir>/workbench` sind zwei Verzeichnisse; und es rückwärts aus dem `Runtime` zu holen geht auch
nicht — `cli.py` ruft erst `main()` und baut den `Workflow`, das `Runtime` entsteht danach, da ist
`brief_path` längst festgenagelt.

**Was tun** Selbst eine `Workbench` bauen und **dasselbe Objekt** gleichzeitig an `Workflow` und
`Runtime` hängen, dann ist die Position festgenagelt:

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` nagelt das fest: Die 5. Assertion prüft, dass der Brief in `prompt_block()`
auftaucht.
Außerdem wird der Index nur in den System-Prompt des **Coordinators** injiziert, Subagents erben ihn
nicht (gemessen $0.2461, `tests/prelude_live.py`) — die Pfade muss der Coordinator weitergeben, nicht
jeder Subagent weiß sie automatisch
(siehe [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
