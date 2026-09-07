# Häufige Probleme und Fehlersuche

Wenn etwas schiefgeht, weiß man nicht, welches Modul kaputt ist — man weiß nur, was man gesehen hat.
Deshalb ist diese Seite nach **dem, was du beobachtest** gruppiert, nicht nach Subsystemen.

Jeder Eintrag hat dieselbe Struktur: **Symptom** (was du tatsächlich siehst) → **Ursache** → **Was tun**.

Fünf der Einträge sind **bekannte Fehler**, kein beabsichtigtes Design. Diese Einträge sagen direkt, dass
es ein Bug ist, verlinken das Issue und nennen einen Workaround — sie werden nicht als Absicht verkauft.

## Installiert nicht / startet nicht {#装不上}

Den vollständigen Installationsablauf findest du in [install.md](../getting-started/install.md#一句话安装).
Dieser Abschnitt sammelt nur die Fälle „installiert, aber das Kommando läuft nicht".

### Python-Version unter 3.10 {#python-版本}

**Symptom**: Während der Installation tauchen Syntaxfehler auf, oder pip sagt direkt, es findet keine
passende Version.

**Ursache**: flower verlangt Python ≥ 3.10. Die einzige Laufzeitabhängigkeit ist `claude-agent-sdk`,
die nativen Binaries stecken in dessen Wheel — wenn die Installation scheitert, liegt es meistens an der
Interpreter-Version, nicht am Netz.

**Was tun**: Zuerst prüfen, in welchen Interpreter installiert werden soll.

```bash
python3 --version
```

Unter 3.10 einen anderen nehmen und erneut installieren. Das systemeigene `python3` ist oft nicht das,
worauf `python` in deinem Terminal zeigt; einmal vorher die Version zu prüfen ist billiger als hinterher
zu suchen (siehe [install.md](../getting-started/install.md#装之前确认-python)).

### Installiert, aber `flower: command not found` {#command-not-found}

**Symptom**:

```text
zsh: command not found: flower
```

**Ursache**: Das Paket ist installiert, aber das Verzeichnis mit dem erzeugten ausführbaren Skript liegt
nicht im `PATH`. Das ist etwas anderes als „nicht installiert" — wenn `python3 -c "import flower"` nicht
fehlschlägt, ist das Paket in Ordnung.

**Was tun**: Der Shebang des `flower`-Skripts ist ein absoluter Pfad, also reicht ein Symlink in ein
Verzeichnis, das bereits im `PATH` liegt; es muss nichts gesourct werden.

```bash
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

### macOS: PATH wie von `install.sh` angewiesen gesetzt, trotzdem command not found {#macos-path}

!!! warning "Bekanntes Problem ([issue #16](https://github.com/ChenyuHeee/flower/issues/16))"

    Dieser Hinweis versagt ausgerechnet auf der Maschine, die ihn braucht.

**Symptom**: Auf macOS `install.sh` durchlaufen lassen, wie im letzten Hinweis `~/.local/bin` in den
`PATH` aufgenommen, Terminal neu geöffnet — `flower` ist immer noch command not found.

**Ursache**: Auf dem pip-Fallback-Pfad installiert macOS' pip die ausführbaren Skripte nach
`~/Library/Python/3.X/bin`, während `install.sh` dazu auffordert, `~/.local/bin` hinzuzufügen. Die beiden
Verzeichnisse passen nicht zusammen, der Hinweis hilft also nicht, auch wenn man ihn befolgt.

??? note "In welcher Reihenfolge `install.sh` den Installationsweg wählt, und der Wortlaut jenes Hinweises"

    Die Priorität hat vier Stufen, nicht zwei (`install.sh:35-56`):

    ```text
    1. uv vorhanden        → uv tool install --force
    2. sonst pipx vorhanden → pipx install --force
    3. sonst                → curl astral.sh/uv/install.sh, uv bootstrappen, bei Erfolg damit installieren
    4. Bootstrap scheitert  → "$PY" -m pip install --user --upgrade    ← hier liegt das Problem
    ```

    Der Wortlaut des PATH-Hinweises am Ende (`install.sh:62-68`, wird nur ausgegeben, wenn
    `command -v flower` nichts findet):

    ```text
    ! 但 flower 不在 PATH 上。
      把这一行加进你的 ~/.zshrc 或 ~/.bashrc:
        export PATH="$HOME/.local/bin:$PATH"
    ```

    `BINDIR` ist fest auf `$HOME/.local/bin` gesetzt (`install.sh:63`). Für Weg 1 und 3 ist das richtig
    — dorthin installiert uv; **nur der pip-Fallback in Weg 4 passt auf macOS nicht**. Die Falle tritt
    also nur auf Maschinen auf, auf denen die ersten drei Wege alle nicht durchkommen.

**Was tun**: Nicht raten, den Interpreter fragen.

```bash
python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))"
```

Das ausgegebene Verzeichnis in den `PATH` aufnehmen, oder von dort einen Symlink nach `~/.local/bin` legen:

```bash
ln -sf "$(python3 -c "import sysconfig; print(sysconfig.get_path('scripts', scheme='posix_user'))")/flower" ~/.local/bin/flower
```

### uv / pipx / pip installieren nicht dasselbe flower {#三种装法}

**Symptom**: `flower` läuft, aber Änderungen am Quellcode wirken nicht; oder nach dem Upgrade ist es
immer noch die alte Version; oder zwei Terminals auf derselben Maschine verhalten sich unterschiedlich.

**Ursache**: Die drei Installationswege legen Paket und ausführbares Skript an verschiedenen Orten ab;
was im `PATH` zuerst trifft, läuft.

??? note "Wo die drei Installationswege landen"

    | Installationsweg | Ausführbares Skript | Wann |
    |---|---|---|
    | `python3 -m venv .venv` + `pip install -e .` | `.venv/bin/flower` | Quellcode ändern. Änderungen wirken sofort |
    | `uv tool install` / `pipx install` | `~/.local/bin/flower` | Nur benutzen, nicht ändern, isolierte Umgebung gewünscht |
    | `pip install --user` | Linux `~/.local/bin`, macOS `~/Library/Python/3.X/bin` | Fallback. Verzeichnis siehe voriger Eintrag |

**Was tun**: Zuerst feststellen, welches gerade läuft, dann entscheiden, welches man ändert.

```bash
which -a flower                      # listet alle gleichnamigen im PATH
head -1 "$(which flower)"            # der Shebang zeigt auf den Interpreter — dort liegt das Paket
```

Wer den Quellcode ändern will, nimmt venv + `-e .` und lässt es nicht neben einer `uv`- / `pipx`-Installation
koexistieren — bei Koexistenz kostet die Fehlersuche weit mehr als eine Neuinstallation
(siehe [install.md](../getting-started/install.md#从源码装)).

## Credentials und Gateways {#凭证}

### `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN` {#缺少凭证}

**Symptom**:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN
```

**Ursache**: flower schottet mit `setting_sources=[]` die Konfiguration des Hostsystems ab, die
Credentials müssen mitgebracht werden. Die vollständige Suchreihenfolge steht in
[config.md](config.md#凭证查找优先级).

**Was tun**: In die `.env` im Repository-Root schreiben oder in die Prozessumgebung.

```bash
cp .env.example .env        # ANTHROPIC_AUTH_TOKEN oder ANTHROPIC_API_KEY eintragen
```

`.env` ist bereits gitignored. Die Variante für Container steht in [deploy.md](deploy.md#凭证).

### Es sagt „flower liest `~/.claude/settings.json` nicht" — dieser Satz ist falsch {#settings-json}

**Symptom**: Wenn die Credentials nicht sitzen, gibt `env.py:192` diesen Satz aus:

```text
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价
```

**Ursache**: Dieser Satz stimmt nicht mit dem Code überein. `env.py:56-75` **liest** `~/.claude/settings.json`
sehr wohl, nimmt daraus nur die Credential-Felder und benutzt sie als letzte Fallback-Stufe — genau damit
wirbt `install.sh` auch. Der Satz wird erst ausgegeben, nachdem auch der Fallback leer ausgegangen ist, er
lässt also nichts fehlschlagen; aber er führt zu dem Schluss „flower kann meinen Claude-Code-Token nicht
benutzen", und das ist falsch. Festgehalten in
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).

**Was tun**: Wer Claude Code lokal installiert hat, braucht keine neuen Credentials zu beantragen, der
Fallback nimmt sie von selbst auf (siehe
[install.md](../getting-started/install.md#本机装过-claude-code-的话可能一个问题都不问)).
Wenn du diesen Satz wirklich siehst, heißt das, dass auch in jener Datei kein brauchbares Credential-Feld
steht — dann wie im vorigen Eintrag eine `.env` schreiben.

### Unklar, welche Credentials und welcher Endpoint tatsächlich greifen {#生效值}

**Symptom**: Die `.env` wurde geändert, die Requests gehen trotzdem ans alte Gateway; oder es lässt sich
nicht sagen, welches Modell gerade benutzt wird.

**Ursache**: Credentials und Endpoint haben mehrere Quellen (Prozessumgebung, `.env`, Fallback); wer
gewinnt, steht nicht in der Konfigurationsdatei, sondern zeigt sich zur Laufzeit.

**Was tun**: Einmal mit `-v` starten. Beim Start wird `describe()` ausgegeben: die wirksame `BASE_URL`
und das Modell-Mapping, der Token maskiert.

```bash
flower -v
```

Die vollständige Schalterliste steht in [cli.md](cli.md#全局开关), die vollständige Variablenliste in
[config.md](config.md#环境变量).

### Ein `KEY=` in der `.env` blockiert alle nachgelagerten Quellen {#空值占位}

**Symptom**: In der Prozessumgebung ist ein Token exportiert, in der `.env` steht außerdem die Zeile
`ANTHROPIC_AUTH_TOKEN=`, und es kommt trotzdem „fehlende Credentials".

**Ursache**: Auch ein leerer Wert ist eine Zuweisung. Ein `KEY=` in einer höherpriorisierten Quelle
**belegt** diesen Schlüssel, niedrigere Quellen füllen ihn nicht mehr; und `check_credentials()`
(definiert in `env.py:184`) prüft auf „Wert nicht leer", meldet also weiterhin fehlend. „Belegt" und
„fehlt" sind zwei verschiedene Dinge, das Symptom ist identisch — das ist bei dieser Klasse von Problemen
das am schwersten selbst Erkennbare.

**Was tun**: Die ganze Zeile löschen, keine leeren Werte stehen lassen.

```bash
grep -n '^[A-Za-z_][A-Za-z0-9_]*=$' .env     # listet alle Zeilen mit leerem Wert
```

Nach dem Löschen mit `-v` die wirksamen Werte noch einmal bestätigen. Die Parse-Regeln stehen in
[config.md](config.md#env-解析).

### Fremdes Gateway: verbunden, aber die erste Runde scheitert {#网关}

**Symptom**: 401 / 403; oder die Meldung, der Modellname existiere nicht; oder gleich zu Beginn ein
[Handoff](glossary.md#换代), zusammen mit der Meldung „Startsockel".

**Ursache**: Drei Arten von Fehlkonfiguration, jede mit eigenem Symptom.

??? note "Drei Arten von Gateway-Fehlkonfiguration und wie man sie erkennt"

    | Symptom | Meistens | Wo ansetzen |
    |---|---|---|
    | 401 / 403 | Die Credentials sind gültig, aber nicht von diesem Gateway ausgestellt; oder der `BASE_URL` fehlt der Pfad bzw. hat einen Slash zu viel | [config.md](config.md#凭证变量) |
    | Modellname existiert nicht | Das Gateway kennt nur seine eigenen Modellnamen, das Mapping fehlt | [config.md](config.md#模型变量) |
    | Handoff direkt beim Start, Meldung „Startsockel" | Fenster zu klein konfiguriert: die Schwelle liegt unter dem Startsockel der Rolle ([Coordinator](glossary.md#协调者) gemessen bei ca. 34k) | `--window`, siehe [handoff.md](../guide/handoff.md#阈值怎么算) |

**Was tun**: Erst mit `-v` die wirksamen Werte ausgeben, dann an der Konfiguration drehen. Besonders das
Fenster lohnt den Abgleich — das Gateway auf der Entwicklungsmaschine ist auf `claude-opus-5[1m]`
konfiguriert; hätte man weiterhin mit 200k gerechnet, gäbe es alle 150k einen Handoff, dabei kommt es
tatsächlich bis 950k — **Faktor 5 Unterschied**, und [long-horizon](glossary.md#长程) Arbeit würde in
Fetzen zerschnitten.

---

## Läuft, verhält sich aber falsch {#行为不对}

Die Symptome dieser Gruppe sind keine Fehlermeldungen, sondern: **das Kommando läuft durch, Exit-Code 0,
aber es tut das Falsche.**
Die ersten vier sind bestätigte Code-Fehler, die Issues sind eingereicht; hier stehen Workarounds, keine
Fixes. Der letzte ist so gewollt.

### `flower setup` startet einen Agenten {#setup-跑成了-agent}

**Symptom**: Du führst `flower setup` aus und erwartest, dass nach Endpoint und Token gefragt wird.
Stattdessen fragt es „was soll getan werden", durchläuft den kompletten go-Ablauf und behandelt das Wort
`setup` als Aufgabenbeschreibung. Danach ist kein einziges Zeichen an Credentials geschrieben.

**Ursache**: Das `_CMDS` in `cli.py:758` listet nur `"go"`, `"run"`, `"once"` — `"setup"` fehlt. Der
Schritt, der das Default-Subkommando ergänzt, schreibt das argv `["setup"]` deshalb zu `["go", "setup"]`
um — `setup` wird vom Subkommando zum ersten Positionsargument von `go` degradiert, also zum Anliegen selbst.
**Es gibt kein argv, das den Konfigurationsassistenten erreicht.** Gemeldet als
[#11](https://github.com/ChenyuHeee/flower/issues/11).

**Was tun**: Mit Ctrl-C abbrechen und die Konfigurationsdatei direkt schreiben. Mehr als in diese Datei zu
schreiben tut `setup` ohnehin nicht:

```bash
mkdir -p ~/.config/flower
cat > ~/.config/flower/.env <<'EOF'
ANTHROPIC_AUTH_TOKEN=sk-...
EOF
```

Die vollständigen Variablennamen und die Suchreihenfolge für Credentials stehen in
[config.md](config.md#凭证变量).
Danach in einem beliebigen Verzeichnis einmal `flower -v` laufen lassen; der beim Start ausgegebene
wirksame Endpoint ist die Gegenprobe.

### Ein `?` in Vollbreite löst die Oracle-Frage nicht aus {#全角问号}

**Symptom**: Du tippst gemäß [Oracle-Frage](cli.md#旁路问答) am Eingabeprompt `?这个目录能删吗`; es
startet keinen [Oracle](glossary.md#旁路顾问), sondern behandelt den Satz als Antwort auf die aktuelle
Frage oder nimmt ihn unverändert in den Posteingang auf.

**Ursache**: `cli.py:733` führt zweimal hintereinander ein `startswith("?")` aus, **beide Male mit
demselben ASCII-Zeichen**. Der Codeabsicht nach hätte die zweite Prüfung das vollbreite `?` prüfen müssen.
Chinesische Eingabemethoden erzeugen standardmäßig genau dieses vollbreite Zeichen — die Hauptnutzer
dieses Features können es also ausnahmslos nicht benutzen. Gemeldet als
[#12](https://github.com/ChenyuHeee/flower/issues/12).

!!! warning "Das verunreinigt die Anforderungen"
    Ein ins Leere laufendes `?` erzeugt keinen Fehler und wird auch nicht verworfen. Es wird als normale
    Eingabe behandelt: in der Clarify-Phase als Antwort auf die gerade gestellte Frage, sonst als
    Posteingangseintrag.
    **Ein Satz, den du nur unter vier Augen fragen wolltest, landet im Brief.** Wenn du den Tippfehler
    bemerkst, korrigiere sofort `.flower/notes/需求.md`; diese Datei ist der Maßstab für alles Nachgelagerte.

**Was tun**: Auf Halbbreite umschalten und `?` tippen, oder erst das halbbreite `?` tippen und dann für
den Text zurück auf Chinesisch schalten.

### Bei `once` sind die kumulierten Kosten immer `$0.00` und die Dauer immer `0:00` {#once-计数为零}

**Symptom**: `flower once` läuft von Anfang bis Ende durch, in der Statuszeile unten stehen die
kumulierten Kosten dauerhaft als `累计 $0.00`, der Timer bleibt bei `0:00` — während dasselbe Modell mit
derselben Arbeit unter `go` Zahlen liefert.

**Ursache**: Das `render()` von `once` **erzeugt bei jedem eintreffenden Event ein neues `Render`**, die
Akkumulatoren werden dabei mit neu aufgebaut und starten jedes Mal bei null. Die Summen werden also
wiederholt auf null gesetzt, nicht etwa nicht erfasst. Gemeldet als
[#14](https://github.com/ChenyuHeee/flower/issues/14).

**Was tun**: Wer korrekte Zahlen braucht, nimmt `go`, dieser Weg ist nicht betroffen. Wer die
Einzelrunden-Form von `once` will und trotzdem die Abrechnung sehen möchte, schaut nach dem Lauf in
`runs/manifest.json` — dort sind die Kosten jedes Schritts festgehalten, und diese Aufzeichnung stimmt.
Details in [config.md](config.md#run-dir).

### Ein Skill in `plugin/` wird nie geladen {#plugin-不加载}

**Symptom**: Du hast gemäß [deploy.md](deploy.md#写一个-skill完整例子) einen Skill geschrieben, die
Verzeichnisstruktur stimmt, aber der Agent verhält sich, als wüsste er nichts davon — **keine Fehlermeldung,
keine einzige Logzeile**.

**Ursache**: `plugin/` ist nicht ins Wheel gepackt. Im installierten Paket zeigt `PLUGIN_DIR` auf
`<site-packages>/plugin`, dieses Verzeichnis existiert nicht, und die Existenzprüfung vor dem Laden
überspringt es still. **Alle drei Wege von `install.sh` sind betroffen**, nur ein aus dem Quellcode
ausgecheckter Repository-Baum kann laden. Gemeldet als
[#15](https://github.com/ChenyuHeee/flower/issues/15).

**Was tun**: Zuerst selbst prüfen, wohin der Pfad tatsächlich aufgelöst wird.

```bash
python3 -c "from flower.core.agent import PLUGIN_DIR; print(PLUGIN_DIR, PLUGIN_DIR.is_dir())"
```

Kommt `False` heraus, ist es dieser Fall. Wer Skills nutzen will, hat derzeit genau eine Möglichkeit:
**aus dem Quellcode-Checkout laufen lassen**.

```bash
git clone https://github.com/ChenyuHeee/flower
cd flower
python3 -m venv .venv && .venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/flower" ~/.local/bin/flower
```

Ein mit `-e` installiertes Paket zeigt zurück ins Checkout-Verzeichnis, `PLUGIN_DIR` landet auf dem echten
`plugin/`, und die Selbstprüfung oben gibt dann `True` aus.

### `-T` zeigt bei `go` keine Wirkung {#trim-与-go}

**Symptom**: Du gibst `flower go` ein `-T` mit; mit und ohne verhält es sich exakt gleich, als wäre der
Schalter kaputt.

**Ursache**: **Das ist so gewollt, kein Fehler.** Der `go`-Pfad hat [Trim](glossary.md#裁剪) ohnehin
standardmäßig an, die von `-T` ausgedrückte Absicht ist bereits erfüllt, also ändert ein weiteres Mal
nichts. Der eigentliche Schalter auf diesem Weg ist das umgekehrte `--no-trim` — explizit angeben muss man
nur, wenn man Trim abschalten will. `-T` ist nur bei `run` und `once` ein sinnvoller Schalter.

**Was tun**: Wenn du bei `go` bestätigen willst, dass Trim wirklich an ist, schau mit `-v` in die
Startausgabe und urteile nicht über An-/Abwesenheit von `-T`; zum Abschalten `--no-trim` geben. Die
vollständige Semantik der Schalter steht in [cli.md](cli.md#全局开关).

## Es sagt, es sei fertig, ist es aber nicht {#没做完}

Der [Goal Guard](../guide/goal.md) existiert genau dafür — Worker haben einen systematischen
Optimismus-Bias, sie wissen, was sie getan haben, nicht, was sie ausgelassen haben. Aber auch der Guard
irrt, und die Richtung der Fehlurteile hat System.
Die folgenden fünf Einträge sind aufgeteilt in „er lässt durch, was nicht durchgehen dürfte" und „er lässt
nie durch".

### Es sagt „hier lässt sich nichts verifizieren", und dann geht es durch {#无法达成不是未达成}

**Symptom**: Im Verdict steht „lässt sich in der aktuellen Umgebung nicht verifizieren, gilt als erreicht",
und der Workflow läuft weiter.

**Ursache**: Der [Judge](glossary.md#判定者) hat „nicht erreichbar" und „nicht erreicht" zu einem Ergebnis
verschmolzen. Das sind **verschiedene Ergebnisse**, genau darum geht es in
[Drei Ergebnisse, nicht zwei](../guide/goal.md#三个结论不是两个):
„nicht erreicht" heißt zurückgeben und weiterarbeiten, „nicht erreichbar" heißt **anhalten und den
Menschen fragen** — akzeptieren, das Ziel ändern, oder feststellen, dass der Judge sich geirrt hat.
Gibt es nur die beiden Ergebnisse „erreicht/nicht erreicht", dreht der Coordinator bei einem in Wahrheit
unerreichbaren Ziel Runde um Runde leer, bis das Budget erschöpft ist.

**Was tun**: **„Lässt sich hier nicht prüfen" darf nie als erreicht gelten.** Sag in den `instructions`
für den Judge namentlich, was in deinem Szenario als nicht machbar gilt, damit er „nicht erreichbar" gibt,
wenn „nicht erreichbar" richtig ist.
Wer wirklich nicht angehalten und gefragt werden will, gibt `--timeout 0`: bei „nicht erreichbar" wird
direkt gestoppt, die Begründung bleibt auf der Platte, statt durchgewinkt zu werden.

### Es liest den Quellcode und erklärt die Sache für erledigt {#判产出物}

**Symptom**: In der Begründung des Verdicts steht „im Code ist X bereits implementiert", „die
Funktionssignatur entspricht den Anforderungen", aber Build-Artefakte, Kommandoausgaben, laufende Dienste
— nichts davon wurde angefasst.

**Ursache**: Der Judge wurde auf den Quellcode gelenkt.
[Beurteilt wird das Artefakt, nicht der Quellcode](../guide/goal.md#判的是产出物不是源码) — ob der
Quellcode richtig aussieht und ob das Abgelieferte benutzbar ist, sind zwei verschiedene Dinge. Ersteres
ist das, wovon der Worker bereits überzeugt ist; es noch einmal zu bestätigen erzeugt keine neue
Information.

**Was tun**: Prüfpunkte müssen als Aussagen über das **Artefakt** formuliert sein. „Die Exportfunktion ist
implementiert" zählt nicht; „`./app export out.csv` ausführen, `out.csv` hat 3 Spaltenüberschriften" zählt.
So sollte schon beim Formulieren des Ziels geschrieben werden, sonst muss der Judge die vagen Punkte selbst
ergänzen.

### Der Judge kann keine Kommandos ausführen, also liest er das Makefile und lässt durch {#判定者不能跑命令}

**Symptom**: Das Ziel ist „ein auf Linux lauffähiges Binary bauen", das Verdict ist bestanden. Du machst
selbst ein `file` — das Artefakt ist Mach-O, gar kein ELF.

**Ursache**: Der Judge ist standardmäßig `judge(can_run=False)`, er hat **nur `Read` / `Glob` / `Grep`**
zur Hand. Diese drei Werkzeuge können Dateien lesen, **aber weder `file` noch `./app --version`
ausführen**. Also weicht er aus, liest das Makefile, sieht im Darwin-Zweig Cross-Compilation stehen und
hält die Bedingung für erfüllt. Er hat nicht gelogen, er hat **im Rahmen seiner Möglichkeiten das
gefunden, was am ehesten nach Beweis aussieht**.

??? note "Wann `can_run` zwingend an muss"
    Das Kriterium ist einfach: **Sobald im Ziel Wörter wie „das Gebaute" vorkommen, muss es an.**

    - Artefakte: Binary, Image, Paket, generierte Daten — an
    - Verhalten: Dienst startet, Kommando gibt 0 zurück, Ausgabe passt auf ein Muster — an
    - Reiner Text: ob ein Dokument geschrieben wurde, ob ein Feld ins Schema aufgenommen wurde — nicht nötig

    Auf der Kommandozeile ist das `--judge-can-run`. Beim eigenen Verdrahten sehen die Einstiegspunkte
    unterschiedlich aus, laufen aber alle auf denselben Parameter von `judge()` hinaus:

    | Einstieg | Wie übergeben | Fundstelle |
    |---|---|---|
    | `judge()` | `can_run=` ist ein regulärer Parameter | `roles.py:361` |
    | `with_goal()` | `can_run=` ist Parameter, wird an `judge()` weitergereicht | `goal.py:155` → `:170` |
    | `goal_step()` | **kein `can_run`-Parameter**, aber es landet in `**spec_kw`, und genau diese Zeile ist `judge(..., **spec_kw)` — kommt an | `goal.py:97` → `:105` |
    | `starter_flow()` | `judge_can_run=`, wird zu `with_goal(can_run=…)`; `--judge-can-run` geht genau diesen Weg | `starter.py:105` → `:196` |

    Der Preis: Der Judge führt tatsächlich Kommandos aus, eine Verdict-Runde wird langsamer und teurer;
    dafür prüft er **den Ort selbst** und nicht dessen Bedienungsanleitung. Siehe
    [Darf der Judge Kommandos ausführen](../guide/goal.md#判定者能不能跑命令).

**Was tun**: Geht es im Ziel um Artefakte, `--judge-can-run` anschalten. Wenn nicht, gilt „muss allein durch
Lesen entscheidbar sein" als harte Randbedingung beim Formulieren der Prüfpunkte — ein Punkt, der sich so
nicht formulieren lässt, braucht ohnehin ein Kommando.

### Die Prüfliste hat über ein Dutzend Punkte und wird nie bestanden {#清单长度}

**Symptom**: Jede Runde wird zurückgegeben, es folgt eine lange Liste dessen, was fehlt, mit jeder
Korrektur wird es mehr, die Arbeit wird nie fertig.

**Ursache**: Die Liste wurde nach „wie gründlich will ich sein" geschrieben, nicht nach „wie viele Arten
des Scheiterns hat diese Arbeit".
[Die Länge der Liste ergibt sich daraus, wie viele Arten des Scheiterns es gibt](../guide/goal.md#清单的长度由有多少种失败方式决定):
Für eine Aufgabe wie `git clone && make && ./app` **reichen drei bis fünf Punkte** — Build erfolgreich,
läuft, benutzbar.
Bei dem realen Absturz in [HT002](../cases/ht002.md#那条查-flower-的清单自己把自己判失败了) wurde die
Aufgabe „das Repository installieren und zum Laufen bringen" zu **15 Punkten** ausformuliert: nur 5 davon
prüften, ob etwas benutzbar ist, 6 prüften, ob der Ablauf Regeln eingehalten hat, und 4 waren
**prinzipiell nicht prüfbar**.

**Was tun**: `.flower/notes/目标.md` ändern, diese Datei ist die Grundlage des Verdicts. Punkt für Punkt
fragen „welcher Art des Scheiterns entspricht dieser Punkt"; was sich nicht beantworten lässt, streichen.
Der Schritt, der das Ziel setzt, meldet sich bei nicht prüfbaren Punkten ohnehin — behalte die
angemahnten Punkte nicht mit Gewalt bei.

### Grenzen wurden als Prüfpunkte formuliert {#边界不是判定项}

**Symptom**: In der Liste tauchen Punkte auf wie „`brew install` wurde nicht ausgeführt", „außerhalb des
Projektverzeichnisses wurde keine Datei geändert"; der Judge prüft zum Selbstfreispruch die mtime von
`~/.zshrc` und schaut nach, ob am `.flower/`-Verzeichnis etwas angefasst wurde.

**Ursache**: Grenzen und Prüfpunkte beschränken verschiedene Dinge; sie zu vermischen war die
Hauptursache jenes HT002-Vorfalls
([Grundursache 1](../cases/ht002.md#根因一边界被当成了判定项)).

| | Beschränkt was | Wie eingehalten |
|---|---|---|
| **Grenze** | **Wie du arbeitest** („nur innerhalb des Projektverzeichnisses installieren", „Geschäftscode nicht anfassen") | Durch **Nicht-Überschreiten**, nicht durch nachträglichen Selbstnachweis |
| **Prüfpunkt** | **Das Abgelieferte** („läuft es", „stimmt das Ergebnis") | Durch Verifikation vor Ort |

Grenzen sind genau der Abschnitt, den man in der Clarify-Phase ausführlich füllen soll. Sie Punkt für
Punkt in die Prüfliste zu übertragen heißt: jede zusätzliche Grenze wird zu einer zusätzlichen Prüfung —
und die meisten dieser Prüfungen sind nicht durchführbar; nicht prüfbare Punkte reißen die ganze
Verdict-Runde mit ins Scheitern.

**Was tun**: Grenzen bleiben im Abschnitt „Grenzen" des Briefs und werden durch Nicht-Überschreiten
eingehalten, nicht durch Aufnahme in die Prüfliste. Wenn wirklich Rechenschaft nötig ist, ein Satz —
**nicht in sechs Punkte zerlegen**.

---

## Kontext und Kosten {#上下文与花费}

In einem long-horizon Run sind Kontext und Geld dasselbe Problem: Läuft der Kontext voll, gibt es
entweder einen Handoff oder dieser Schritt fliegt auf; und jeder Satz, den man in einer Runde wiederholt,
muss in jeder folgenden Runde erneut bezahlt werden.

### Mitten im Lauf öffnet es selbst eine neue Session und sagt „Handoff" {#换代打断}

**Symptom** Im Event-Strom erscheint `handoff`, `payload["phase"]` zuerst `near`, dann `done`, dazwischen
kostet das Schreiben des [Handoff-Dokuments](glossary.md#交接书) eine zusätzliche Runde, danach geht die
Arbeit normal weiter.

**Ursache** Der Kontext nähert sich der Schwelle. flower **compacted nicht** — es schreibt den Zustand der
aktuellen Session in ein fünfteiliges Handoff-Dokument und startet eine neue Session, die es liest und
weiterarbeitet. [Compact](glossary.md#压缩) löscht die teuersten Informationen gleich mit weg, etwa „Wege,
die nicht funktionieren", während das Handoff-Dokument explizit ist, auf der Platte liegt und jederzeit
änderbar bleibt: Die übernehmende Session liest genau diese Datei.

**Was tun** Das ist der normale Pfad, nichts zu tun. Ein Handoff zählt nicht als Retry — `attempts` steigt
nicht (das zählt Fehlschläge), die verbrannte session_id wird in `StepResult.retired` festgehalten, und
die nach außen sichtbare `session_id` ist immer die des noch lebenden Nachfolgers
(siehe [../guide/handoff.md#换代不算重试账怎么记](../guide/handoff.md#换代不算重试账怎么记)).
Wer wirklich zum Auto-Compact des SDK zurück will, nimmt `--no-handoff`.

??? note "Woher die Schwelle kommt und warum der Default so offensiv gewählt ist"
    `at = window - headroom`. `window` ist **standardmäßig 1 Million**, bestimmt über den Modellnamen:
    Namen mit `haiku` zählen als 200k, alle anderen als 1 Million. `headroom` ist standardmäßig 50k —
    Auto-Compact greift bei −33k, der Handoff muss ihm zuvorkommen, und das Schreiben des Handoffs selbst
    braucht noch eine Runde; 50k erfüllt beides zugleich.

    Zu groß zu schätzen ist kein harter Fehler: Ist das echte Fenster kleiner, wird die Schwelle nie
    erreicht, der Request wird von der API mit „Prompt zu lang" abgewiesen, flower erkennt dieses Signal
    (`handoff.is_overflow()`) und macht auf der Stelle einen Handoff mit einem mechanisch
    zusammengesetzten Fallback-Dokument; der Schritt schlägt nicht fehl
    (siehe [../guide/handoff.md#is_overflow把硬错变成当场换代](../guide/handoff.md#is_overflow把硬错变成当场换代)).

    Ein Messwert, der Erwähnung verdient: Das Gateway auf der Entwicklungsmaschine ist auf
    `claude-opus-5[1m]` konfiguriert. Hätte man weiterhin mit 200k gerechnet, gäbe es alle 150k einen
    Handoff, dabei kommt es tatsächlich bis 950k — **Faktor 5 Unterschied**, long-horizon Arbeit würde in
    Fetzen zerschnitten.

### Handoff gleich zu Beginn, und er hört nicht auf {#一开局就换代}

**Symptom** Die Fehlermeldung erwähnt den „Startsockel", oder derselbe Schritt macht wiederholt Handoffs,
bis er gegen `max_generations=8` läuft.

**Ursache** `window` ist zu klein konfiguriert, die Schwelle liegt unter dem Startsockel dieser Rolle —
beim Coordinator gemessen ca. 34k, allein System-Prompt plus [Workbench](glossary.md#工作台)-Index
verbrauchen das. Die neue Session überschreitet die Linie schon beim ersten Wort, also Handoff schreiben,
übergeben, wieder überschreiten, endlos (Handoffs zehren nicht am Retry-Budget, das ist Absicht).

**Was tun** `--window` auf das echte Fenster des Modells stellen; `-v` gibt den wirksamen Endpoint und das
Modell-Mapping aus. Ein normaler langer Lauf kommt nie an 8 Generationen; wer wirklich dagegenläuft, hat
fast sicher diese Ursache, und die Fehlermeldung sagt das auch direkt
(siehe [../guide/handoff.md#一道防跑飞的闸](../guide/handoff.md#一道防跑飞的闸)).
Ein verwandtes Symptom ist „das Handoff-Dokument ist immer die Fallback-Version": Die Ursache steht unter
`errors` in `runs/manifest.json`.

### Bleibt auf halbem Weg stehen mit der Meldung, das Budget sei ausgeschöpft {#预算到顶}

**Symptom** Der [Schritt](glossary.md#步骤) ist nicht fertig und stoppt, Begründung: Kostenlimit
überschritten.

**Ursache** `AgentSpec(max_budget_usd=...)` ist eine **harte Obergrenze**, keine weiche Erinnerung;
`Runtime.total_cost()` ist die Summe des aktuellen Runs.

**Was tun** Bevor du das Limit anhebst, prüfe, ob es nicht im Leerlauf dreht. Runde um Runde zurückgegeben
ohne jeden Fortschritt heißt meist: Der Judge hätte „nicht erreichbar" geben müssen und hat „nicht
erreicht" gegeben — ein in Wahrheit unerreichbares Ziel brennt weiter, bis das Budget leer ist
(siehe [../guide/goal.md#三个结论不是两个](../guide/goal.md#三个结论不是两个)).
Erst sicherstellen, dass normal gearbeitet wird, dann das Limit anheben.

### Warum war dieser Lauf so teuer {#为什么这么贵}

**Symptom** Die Kosten liegen weit über der Erwartung, aber an der Ausgabe sieht man nicht, wohin das Geld
gegangen ist.

**Ursache** Die Abrechnung steht nicht im Kontext des Modells. `session_id`, Kosten, Anzahl der Retries und
Fehlerursache jedes Schritts stehen nur in `runs/manifest.json`, **prozessübergreifend angehängt**. Auch
Retry-Historie und Originalfehler stehen nur dort — das Modell sieht sie nicht, und das ist Absicht:
Häufen sich abgelehnte Aufrufe im Kontext, lernt der Coordinator „Bash wird eh geblockt" und versucht nicht
einmal mehr `git status` (`Runtime(keep_denials=1)` räumt standardmäßig auf, nicht hochdrehen).

**Was tun** `runs/manifest.json` öffnen und die Kosten pro Schritt abgleichen (Disk-Layout siehe
[config.md#磁盘布局](config.md#磁盘布局)). Ein paar gemessene Referenzwerte:

| | Kosten |
|---|---|
| Startsockel eines Subagents (nicht amortisierbar) | ~4.3k tokens |
| Startsockel des Coordinators | ~34k tokens |
| `tests/smoke.py` Einzelagent, ganze Kette | ~$0.21 |
| `tests/flow_demo.py` Workflow, drei Verdrahtungsarten | ~$0.39 |
| `tests/delegation.py` Arbeitsteilung + Messung der Kontextverteilung | ~$0.71 |
| `tests/isolation.py` drei Issues, drei Worktrees | ~$0.9 |

### Der Kontext wächst schneller als die Arbeit vorangeht {#上下文涨得快}

**Symptom** In jedem [Task-Brief](glossary.md#任务书) wird dieselbe Disziplin wiederholt („erst lesen, dann
ändern", „Geschäftscode nicht anfassen", „nach der Änderung Tests laufen lassen"), während der
[Worker](glossary.md#执行者) sich ohnehin daran hält.

**Ursache** Jeder Satz des Coordinators geht in dessen eigenes Transcript, und ein Transcript wächst nur.
Die Disziplin noch einmal aufzusagen kostet in dieser Runde Geld — **und in jeder folgenden Runde muss
dieser Abschnitt erneut mitbezahlt werden**. Was das Gegenüber bereits weiß, bringt beim Wiederholen null
Ertrag, kostet aber dauerhaft.

**Was tun** Disziplin gehört in den Mechanismus, nicht in jede Runde Text: Was sich über `allowed_tools`,
den Abschnitt „Grenzen" des Briefs oder den Workbench-Index ausdrücken lässt, gehört nicht in den
Task-Brief; der Task-Brief enthält nur, was sich in dieser Runde geändert hat. Die Arbeitsteilung selbst
spart die größte Schicht
(siehe [../guide/context.md#第一层分工省得最多](../guide/context.md#第一层分工省得最多)).
Beim Resume lassen sich alte große Tool-Ergebnisse mit `-T` durch Dateizeiger ersetzen.

## Unterbrechung und Kontinuität {#中断与接续}

### Der Prozess wurde gekillt, die Maschine neu gestartet {#进程被杀}

**Symptom** Mitten im Lauf ist alles weg, und im neuen Terminal ist unklar, wie man wieder anknüpft.

**Ursache** Es gibt nichts aufzusammeln. Die [Lineage](glossary.md#血缘) (`runs/lineage.json`) hält
Schrittname → session_id fest, wird am Ende jedes Schritts auf Platte geschrieben, und zwar erst als
`.tmp` und dann atomar ersetzt — ein Kill mittendrin hinterlässt keine halbe Datei.

**Was tun** Ins **selbe Verzeichnis** zurückgehen und erneut `flower` starten; jeder Schritt knüpft an
seine bisherige Session an: Die Anforderungen werden nicht erneut abgefragt, das Ziel nicht erneut gesetzt,
und selbst welche Sackgassen der Coordinator schon probiert hat, ist noch bekannt. Wer nichts sagen will,
drückt einfach Enter
(siehe [../guide/continuity.md#进程被杀和机器重启](../guide/continuity.md#进程被杀和机器重启)).
Der Judge ist die Ausnahme — er ist kein `Step`, sondern wird direkt aus dem Gate heraus entsandt und geht
nie über die Lineage; deshalb ist er in jeder Runde ein frisches Augenpaar.

### Es fängt jedes Mal von vorn an, knüpft überhaupt nicht an {#接不上}

**Symptom** Im selben Verzeichnis erneut gestartet, und es fragt die Anforderungen wieder komplett ab.

**Ursache** Bei drei Arten von „passt nicht" fällt flower **still auf einen Neuanfang zurück, ohne Fehler**
— [Kontinuität](glossary.md#接续) ist ein Bonus, ihr Ausfall darf niemanden an der Arbeit hindern:

- `runs/lineage.json` fehlt, oder der darin stehende `workspace` stimmt nicht mit deinem aktuellen Pfad
  überein (passiert, wenn das Verzeichnis kopiert wurde)
- Die Session ist nicht mehr in `runs/sessions.db` (Datenbank gelöscht)
- Die Lineage-Datei ist beschädigt

**Was tun** Zuerst prüfen, ob `runs/lineage.json` da ist und ob `workspace` stimmt (die Aufgaben der drei
Dateien stehen in
[../guide/continuity.md#落在磁盘上的三个文件](../guide/continuity.md#落在磁盘上的三个文件)).
Dass es nach einem Verzeichniswechsel nicht anknüpft, ist **Absicht**: `project_key` wird aus dem
Workspace-Pfad abgeleitet, die alte Session ist am neuen Ort nicht auffindbar.

### Neu anfangen, aber die Historie nicht verlieren {#想重开}

**Symptom** Die Anforderung hat die Richtung gewechselt, und es soll nicht an der alten Sache weiterreden.

**Ursache** Das Standardverhalten ist Weiterreden. In einem bereits benutzten Verzeichnis ist
`flower "顺便支持代码块高亮"` keine neue Aufgabe, sondern ein weiterer Satz im selben Gespräch.

**Was tun** `--new`. Das ist **Archivieren, nicht Löschen**, das Alte bleibt in `notes/archive/`.
Beim [Wake](glossary.md#唤醒) wird zuerst eine Zeile mit dem aktuellen Kontextumfang gemeldet; wenn dir
der zu groß ist, führt derselbe Weg weiter.

### Netz weg, es meldet nichts und bewegt sich nicht {#断网}

**Symptom** Auf der Oberfläche keine neuen Events, der Prozess lebt noch, sieht aus wie hängengeblieben.

**Ursache** Netzausfall wird als „kurz warten" behandelt, nicht als Fehlschlag. flower hängt und wartet:
erst DNS probieren, dann TCP, und erst wenn es durchgeht, weitermachen
(siehe [../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文](../guide/continuity.md#韧性断网时挂着等而且错误不进接续后的上下文)).
In HT001 wurde das durch einen echten Ausfall verifiziert
(siehe [../cases/ht001.md#六断网续跑第一次被真实故障验证](../cases/ht001.md#六断网续跑第一次被真实故障验证)).

**Was tun** Warten; mit `-v` sieht man die Proben laufen. Die während der Wartezeit angefallenen Fehler
**gehen nicht in den Kontext nach der Fortsetzung** — sie landen nur in `runs/manifest.json`, und die
übernehmende Session sieht einen sauberen Zustand, den keine Reihe von Timeouts in die Irre führt.

### Zweimal Ctrl-C, der Abschluss ist unvollständig {#双重-ctrl-c}

**Symptom** Ein `kill` (SIGTERM) und zweimaliges Ctrl-C hinterlassen unterschiedliche Zustände.

**Ursache** Bekannte Lücke. Doppeltes Ctrl-C wirft `KeyboardInterrupt`: Das `finally` von `_drive` in
`cli.py` ruft `rt.close()`, aber **nicht** `rt.rescue()` — `rescue()` rufen nur die Handler für
SIGHUP/SIGTERM.

**Was tun** Die Lineage bleibt auf beiden Pfaden erhalten (nach jedem Schritt atomar auf Platte), ein
erneuter Start knüpft also trotzdem an, diese Lücke kostet keinen Fortschritt. Für einen vollständigen
Abschluss `kill <pid>` benutzen statt wild Ctrl-C zu drücken.

## Parallelität und Isolation {#并行与隔离}

### `not in a git repository` {#不是-git-仓库}

**Symptom** Mit eingeschalteter Isolation startet es nicht und meldet `not in a git repository`.

**Ursache** `worker(..., isolate=True)` gibt jedem Agenten über git worktree eine private Kopie; ist der
Workspace kein Git-Repository, lässt sich keine anlegen.

**Was tun** Dieser Fall **degradiert nicht still** — entweder wirklich in einem Repository laufen lassen
oder `isolate` abschalten. Isolation garantiert, dass mehrere Agenten gleichzeitig ändern können, ohne die
Arbeitsbäume der anderen zu sehen; sie garantiert dir nicht, dass das Mergen konfliktfrei ist.

### Ein isolierter Agent kann nicht in die Workbench schreiben {#隔离写不进工作台}

**Symptom** Der Subagent meldet „Schreibrecht verweigert", Skripte und Artefakte landen nicht auf der
Platte; oder die Artefakte landen in genau einem Worktree und die anderen Agenten sehen sie nicht.

**Ursache** Ein Worktree ist die **private Kopie** eines Agenten, die Workbench ist die agentübergreifende
**gemeinsame Schicht**. Legt man Gemeinsames in einen privaten Zaun, kommen die anderen naturgemäß nicht
heran.

**Was tun** Bei eingeschalteter Isolation die Workbench **außerhalb des Repositories** ablegen:

```python
wb = Workbench(Path.cwd(), home=Path.cwd().parent / ".flower-proj").ensure()
```

Liegt sie außerhalb des Workspace, erteilt `Runtime` die Freigabe automatisch per `add_dirs`;
`Runtime(workbench=True)` erledigt das bereits, bei einer selbst gebauten `Workbench` musst du die
Freigabe selbst geben.

!!! warning "Die Workbench hat zwei Default-Positionen, und sie sind verschieden"
    `Workbench(workspace)` — den Weg gehen die CLI und `starter_flow()` — legt die Workbench nach
    `<workspace>/.flower`; `Runtime(workbench=True)` (also `-W`) legt sie nach `<run_dir>/workbench`, also
    `runs/workbench`. Ein Lauf von `flower` gibt dir also ein `.flower/`, ein `Runtime(workbench=True)` in
    Python **nicht**.

### Mit flower gibt es ein `.flower/`, im eigenen Skript nicht {#两个工作台默认值}

**Symptom** Der Brief wurde nachweislich nach `.flower/notes/需求.md` geschrieben, der Coordinator tut aber,
als hätte er ihn nie gelesen; **keine Fehlermeldung**.

**Ursache** Du hast zwei Workbench-Objekte in der Hand. Der Brief wird in Verzeichnis A geschrieben, der in
den System-Prompt injizierte Index scannt Verzeichnis B, und das Versprechen „weiß von Anfang an, wo die
Anforderungsdatei liegt" **fällt still aus**. Beide Fehlerarten melden nichts: Ein selbst
zusammengebauter `brief_path` relativ zum Prozess-cwd und die von `-W` erzeugte `<run_dir>/workbench` sind
zwei Verzeichnisse; und sich den Pfad rückwärts aus dem `Runtime` zu holen geht auch nicht — `cli.py` ruft
erst `main()` und baut den `Workflow`, erst danach entsteht das `Runtime`, da ist `brief_path` längst
festgelegt.

**Was tun** Selbst eine `Workbench` bauen und **dasselbe Objekt** sowohl dem `Workflow` als auch dem
`Runtime` mitgeben; damit ist die Position festgenagelt:

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[...])
rt = Runtime(workspace=".", workbench=wb)
```

`tests/trial_offline.py` nagelt das fest: Assertion 5 prüft, dass der Brief in `prompt_block()` auftaucht.
Außerdem wird der Index nur in den System-Prompt des **Coordinators** injiziert, Subagenten erben ihn nicht
(gemessen $0.2461, `tests/prelude_live.py`) — der Pfad muss vom Coordinator weitergegeben werden, nicht
jeder Subagent weiß ihn automatisch
(siehe [../guide/workflow.md#工作台要挂在-workflow-上](../guide/workflow.md#工作台要挂在-workflow-上)).
