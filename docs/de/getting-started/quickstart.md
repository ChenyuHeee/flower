# Schnellstart

Drei Befehle genügen: installieren, ins Projektverzeichnis wechseln, `flower` eintippen. Diese Seite
stellt diese drei nach vorn und erklärt dann, was nach dem Enter auf dem Bildschirm passiert, wie du
antwortest, wenn es dich etwas fragt, und was du zuerst prüfst, wenn es nicht läuft.

## Installieren, ins Verzeichnis, `flower` tippen {#跑起来}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
cd /path/to/your/project
flower
```

Das erste Skript sucht automatisch nach `uv` / `pipx` / `pip` und installiert damit den Befehl
`flower`; nötig ist nur Python ≥ 3.10, kein Node und kein Claude Code CLI. Der dritte Befehl nimmt
keinerlei Argumente und **braucht keine Anführungszeichen in der Shell**.

Wenn du anders installieren willst (pipx / pip / aus dem Quelltext) oder das Skript auf deiner
Maschine nicht funktioniert, siehe [Installation](install.md) — du musst diese Seite aber nicht erst
zu Ende lesen, bevor du hierher zurückkommst.

## Nach dem Enter {#回车之后}

Beim ersten Lauf auf dieser Maschine fragt es zuerst nach den Zugangsdaten: API-Key oder
Gateway-Adresse. Einmal konfiguriert, landet das in `~/.config/flower/.env` und gilt danach überall.
Ist auf der Maschine bereits Claude Code installiert und eingerichtet, borgt es sich dessen Token und
fragt gar nicht erst.

Sind die Zugangsdaten da, steht der Cursor auf `>`:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Diese Zeile liest von der Standardeingabe, **ohne Shell-Parsing** — chinesische Anführungszeichen,
Leerzeichen, Ausrufezeichen kannst du direkt eintippen.

Vor dem Start gibt es eine Zeile `- 验一下凭证…` aus, das ist eine echte API-Sonde. Werden die
Zugangsdaten abgelehnt, kommt `! 凭证被拒:…` und es fragt dich sofort, ob du neu konfigurieren
willst; kommt keine Verbindung zustande, kommt
`(探针没打通:… —— 当作网络问题,照常开跑)` — es schickt dich **nicht** dazu, ein völlig
intaktes Token neu einzurichten.

Geht die Sonde durch, fängt die Arbeit an, und zwar in drei Schritten. Jede `==`-Trennlinie auf dem
Bildschirm ist eine [Schritt](../reference/glossary.md#步骤)-Grenze, das `1/3` rechts ist der
Fortschritt:

```text
== 确认需求 ======================================================== 1/3

  ? X 要跑在什么环境上?
     1) 只在我这台 macOS 上
     2) Linux 服务器
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
  + 只在我这台 macOS 上

  ? 「做完了」以什么为准?
你的回答 (回车=跳过,让它自己判断) > 能跑起来,并且 pytest 全绿
  + 能跑起来,并且 pytest 全绿

  + 完成 9 轮 · $0.53 · 用时 6:02

== 设定目标 ======================================================== 2/3

  ~ 把这份需求拆成能当场验证的条目
  + 完成 12 轮 · $0.41 · 用时 9:06

== 干活 ============================================================ 3/3

  ~ 先看一眼现在有什么,再决定第一刀切哪
  * Read README.md
  > 派人 coder 实现 X 的第一版,带最小测试
  先让 coder 把骨架搭起来,我再看要不要拆第二个人。
  - 上下文 36.8K · 累计 $0.94 · 12:44
  + 完成 12 轮 · $12.34 · 用时 52:53
  + 完成 37 轮 · $1.40 · 用时 58:19

总花费 $14.68 · 清单 /path/to/your/project/runs/manifest.json
```

Die Symbole sind durchgehend ASCII: `~` Denken, `*` Werkzeugaufruf, `>` Beauftragen, `+` Erfolg,
`x` Fehlschlag, `?` Frage, `<-` Anknüpfen an den letzten Lauf. Keine Emojis — Emojis und
Rahmenzeichen lösen im Terminal Glyphen-Fallbacks aus, im Test ist das Terminal deswegen zweimal
abgestürzt. **Alle Terminal-Beispiele in dieser Dokumentation benutzen genau dieses ASCII-Set und
sehen exakt so aus wie auf deinem Bildschirm.**

Drei Stellen lohnen einen zweiten Blick:

- Die letzten beiden `+ 完成`-Zeilen sind keine Dopplung. Die erste ist die Arbeitsrunde, die zweite
  die **Verdikt**-Runde — das Verdikt läuft in einer eigenen Session, bekommt aber **keine eigene
  `==`-Trennlinie**, weil es eine Runde innerhalb des Schritts `干活` ist. Im
  [Lauf-Manifest](../reference/glossary.md#运行清单) heißt sie `干活·判定#1`.
- Das `$` in der `+ 完成`-Zeile ist das Geld **dieser einen Runde**, `用时` ist die Gesamtdauer
  **vom Start bis jetzt** — zwei verschiedene Maßstäbe.
- Statuszeilen der Form `- 上下文 … · 累计 … · …` folgen nur dem
  [Haupt-Thread](../reference/glossary.md#主线程), der Kontext der Subagents steckt nicht darin.
  Werkzeugaufrufe der Subagents werden standardmäßig angezeigt, eingerückt hinter einem senkrechten
  Strich `|`; **was sie sagen**, siehst du erst mit `-v` — das ist das Geschehen vor Ort, nicht die
  Entscheidung.

## Wer diese drei Schritte jeweils ausführt {#三步}

| Schritt auf dem Bildschirm | Wer läuft | Was er tut | Eingefroren als | Details |
|---|---|---|---|---|
| `确认需求` | [Clarifier](../reference/glossary.md#确认者) | Stellt nur Fragen, fasst nichts an, **fragt so lange, bis es klar ist, ohne Rundenobergrenze**; gibt am Ende ein vierteiliges [Briefing](../reference/glossary.md#需求确认书) aus | `.flower/notes/需求.md` | [Vorab-Klärung](../guide/clarify.md) |
| `设定目标` | [Judge](../reference/glossary.md#判定者) | Übersetzt das Briefing in „Ziel + Prüfliste", jeder Punkt muss an Ort und Stelle verifizierbar sein | `.flower/notes/目标.md` | [Zielwächter](../guide/goal.md) |
| `干活` | [Koordinator](../reference/glossary.md#协调者) beauftragt [Subagents](../reference/glossary.md#subagent) | Der Koordinator zerlegt die Arbeit, beauftragt, liest Berichte, entscheidet; am Ende jeder Runde urteilt ein Judge, der **nicht mitgearbeitet hat**, unabhängig darüber, ob es fertig ist — wenn nicht, geht es zurück und weiter | der Code selbst | [Zielwächter](../guide/goal.md) |

Die ersten beiden Schritte sind die Umsetzung der beiden Mechanismen
[Vorab-Klärung](../reference/glossary.md#前置确认) und
[Zielwächter](../reference/glossary.md#目标看守); der dritte ist der Abschnitt, den beide zusammen
bewachen. Standardmäßig laufen höchstens 3 Verdikt-Runden (`--rounds`), mit `--no-goal` lässt sich
das komplett abschalten — danach gilt „es sagt, es ist fertig" tatsächlich als fertig.

Ein Verdikt hat nur drei mögliche Ergebnisse: erreicht, nicht erreicht, **in dieser Umgebung nicht
prüfbar**. Die letzten beiden sind verschiedene Ergebnisse — „hier nicht prüfbar" wird niemals als
bestanden gewertet, sondern hält an und fragt dich.

Ein vollständiger Lauf ist nicht billig. Gemessene Referenzwerte: [HT002](../cases/ht002.md) hat ein
bestehendes Projekt auf macOS installiert und zum Laufen gebracht — 4 Schritte, rund 1 Stunde,
**$38.24**; [HT001](../cases/ht001.md) hat eine Terminal-IDE von null geschrieben — **10.4 Stunden,
$171.62**. Wenn du erst sehen willst, was es fragt, bevor du weitermachst, nimm `--clarify-only`.

## Wie man auf Fragen antwortet {#答提问}

Der Abschnitt, der mit `?` beginnt, ist eine Frage an dich; es gibt drei Antwortarten:

- **Nummer eintippen** (`1` / `2` / `3`) — wählt diesen Punkt, der Bildschirm antwortet mit einer
  Zeile `+ <选中的那条>`.
- **Einfach tippen** — freie Antwort, sie muss keine der Optionen sein.
- **Nur Enter** — überspringen, es entscheidet selbst, der Bildschirm antwortet mit `. 已跳过`.

Standardmäßig wartet es 1800 Sekunden auf dich (`--timeout`). Kommt niemand, gibt es
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` aus und läuft weiter, es hängt sich
nicht auf. Die Zahl der Fragen ist **standardmäßig unbegrenzt** (`--asks` steht auf `-1`); eine
positive Zahl ist ein hartes Kontingent, ist es aufgebraucht, kommt `! 提问额度用完`.

## Während es läuft, kannst du weiter reden {#插话}

Ganz unten am Bildschirm steht immer eine Eingabezeile. Die ist kein Dekor — vor jeder Ausgabe wird
sie gelöscht und danach neu gezeichnet, sie **wird also nicht von den Logs nach oben weggespült**.
Es gibt zwei Varianten, je nachdem, ob eine Frage offen ist:

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

Wenn keine Frage offen ist, kannst du zwei Dinge tun.

**Einfach einen Satz tippen = Anforderung ergänzen.** Es wird nicht unterbrochen und sieht das erst,
wenn es das nächste Mal den Posteingang prüft. Die Bestätigung sieht so aus:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

„已追加进确认书" ist wichtig: Der Satz landet gleichzeitig in `需求.md` und überlebt damit die
Schrittgrenze — der nächste Schritt ist eine neue Session, die nur die eingefrorenen Dateien liest;
was nicht auf die Platte kommt, ist so gut wie nie gesagt worden.

**Mit `?` beginnen = eine Frage nebenbei.** Es startet dafür eine separate, nur lesende Session, die
nur die letzten 60 Events und den Inhalt der [Workbench](../reference/glossary.md#工作台) zur
Verfügung hat. Dieser Seitenkanal läuft über den [Oracle](../reference/glossary.md#旁路顾问),
standardmäßig gedeckelt auf 12 Runden / $0.5:

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Nach der Antwort wird es verworfen** — dieser Frage-Antwort-Abschnitt geht nicht in den Kontext des
laufenden Laufs ein, und die Kosten gehen nicht ins Haupt-Lauf-Manifest, sondern in ein eigenes unter
`runs/aside/`. Fragen stört den Lauf also nicht, und du musst dem Geld auch nicht nachtrauern.

!!! warning "Vollbreites `？` zählt nicht, es muss ein halbbreites `?` sein"
    Als Seitenkanal-Frage erkannt wird nur das **halbbreite** `?` (ASCII `0x3f`). Das vollbreite `？`,
    das chinesische Eingabemethoden standardmäßig produzieren, wird nicht erkannt — die Zeile landet
    als „Anforderung ergänzen" im Posteingang, **ohne Fehlermeldung**, nur kommt die Antwort, auf die
    du wartest, nie. Das ist ein Tippfehler im Code und steht auf der Fehlerliste; bis er behoben
    ist, stell die Eingabemethode auf Englisch, bevor du `?` tippst.

Nebenbei zu Ctrl+C: Ein erstes Drücken mitten im Lauf **unterbricht diese Runde und lässt dich etwas
sagen**, es beendet nicht.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

Erst ein zweites Drücken beendet wirklich. (Auf dem allerersten Prompt `要做什么?` beendet Ctrl-C
sofort und gibt `已取消` aus.)

## Ein zweiter Lauf knüpft an den letzten an {#再跑一次}

Tippst du im selben Verzeichnis erneut `flower`, ändert sich schon der erste Satz:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

Die `<-`-Zeile ist das [Wake](../reference/glossary.md#唤醒)-Banner und meldet den aktuellen Zustand
dieses Verzeichnisses. Es fragt die Anforderungen nicht noch einmal ab und setzt das Ziel nicht neu;
das gilt auch, wenn der Prozess gekillt oder die Maschine neu gestartet wurde. Der Satz, den du jetzt
sagst, wird an `需求.md` angehängt und **löst eine Neuableitung der Prüfliste aus** — ohne
Neuableitung liest der Judge weiter die alte Liste, und was du ergänzt hast, käme im Verdikt gar
nicht vor. Details und Kosten (der Kontext wächst dabei stetig) siehe
[Kontinuität](../guide/continuity.md).

Willst du nicht anknüpfen, tippe `/new`: Anforderungen, Ziel und
[Lineage](../reference/glossary.md#血缘) des vorigen Abschnitts werden nach
`notes/archive/<时间戳>/` **verschoben** (nicht gelöscht), dann geht es von vorn los.

## In Skripte schreiben, unbeaufsichtigt {#脚本}

Das Anliegen kann auch direkt als Argument mitgegeben werden, die Flags dürfen davor oder dahinter
stehen:

```bash
flower "帮我做一个 X"                      # Anliegen als Argument
flower --rounds 5 "帮我做一个 X"           # Flags davor
flower "帮我做一个 X" --rounds 5           # Flags dahinter, äquivalent
echo "帮我做一个 X" | flower --timeout 0   # per Pipe in die Standardeingabe, vollautomatisch
```

Nur Flags ohne Anliegen geht auch — `flower --clarify-only` fragt dich zuerst, was zu tun ist, und
macht dann weiter.

**Warum der Weg „nach dem Enter tippen" trotzdem bleibt.** Das Anführungszeichenpaar auf der
Kommandozeile ist reine Last. Selbst erlebt: Das schließende Anführungszeichen wurde als chinesisches
`”` getippt, zsh wartete endlos auf das echte schließende Zeichen (und fiel in den
Fortsetzungsprompt `dquote>`), es sah aus, als hinge das Programm — dabei war es kein einziges Mal
gestartet. Bei nacktem `flower` wird von der Standardeingabe gelesen, ohne Shell-Parsing, chinesische
Anführungszeichen, Leerzeichen, Ausrufezeichen und Zeilenumbrüche kannst du alle direkt tippen. Der
Pipe-Weg benutzt denselben Eingang — wenn die Standardeingabe kein Terminal ist, gibt es keinen
Prompt-Kopf aus, sondern liest direkt eine Zeile.

!!! danger "Unbeaufsichtigt muss `--timeout 0` explizit gesetzt werden"
    In einer Pipe, unter `nohup` oder in CI kann niemand Fragen beantworten. Ohne `--timeout 0`
    passiert Folgendes: Die erste Frage wird wegen „Eingabe geschlossen" übersprungen, **danach
    wartet jede weitere Frage volle 1800 Sekunden ab** — ein paar Fragen sind ein paar Stunden
    Leerlauf, und in dieser Zeit wird Geld verbrannt.
    `--timeout 0` sorgt dafür, dass jede Frage sofort mit „niemand antwortet" zurückkommt und es
    selbst entscheidend weitermacht.
    Ist die Standardeingabe kein Terminal, gibt flower zuerst eine Warnzeile aus:
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## Wenn es nicht läuft {#冒烟}

Wenn `flower` nichts tut, ein Zugangsdaten-Fehler kommt oder die Ausgabe auf den ersten Blick falsch
aussieht, prüfe Zugangsdaten und Binary zuerst mit dem billigsten möglichen Schuss separat. Ein
einzelner Agent, nur lesende Werkzeuge, ein Schuss, um beide Enden zu testen:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| Teil | Was er ist |
|---|---|
| `once` | Führt einen einzelnen Agent einmal aus: keine Anforderungsklärung, kein Ziel, keine Beauftragung |
| `-w PATH` | Arbeitsverzeichnis des Agents. Ohne Angabe das aktuelle Verzeichnis |
| `-v` | Gibt vor dem Start die wirksame Zugangsdaten-Konfiguration aus, vom Token nur die ersten 4 Stellen |

`once` gibt standardmäßig nur drei Werkzeuge frei — `Read`, `Glob`, `Grep`; es kann nichts schreiben,
deshalb ist dieser Schuss sehr billig. Gemessene Referenz: Opus 5 mit 1-Millionen-Fenster über ein
Drittanbieter-Gateway, **Bodenpreis pro Runde $0.1741**, billigere Modelle liegen darunter. Der
Abschnitt „Prüfen, ob die Installation geklappt hat" auf der Seite [Installation](install.md) führt
genau diesen Befehl aus.

Läuft es durch, sieht es so aus — Zahlen und Fließtext werden abweichen, **die Symbole nicht**:

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 19 位)
ANTHROPIC_BASE_URL = https://your-gateway.example.com
ANTHROPIC_MODEL = claude-opus-5[1m]
- 验一下凭证…
  ~ 先看目录结构,再挑一两个文件读
  * Glob **/*.py
  * Read README.md
  这是一个用 Rust 写的命令行 HTTP 压测工具。
  - 累计 $0.00 · 0:00
  + 完成 4 轮 · $0.0932 · 用时 0:00
```

Zwei Dinge sollte man erkennen:

- Die ersten Zeilen sind die von `-v` ausgegebene wirksame Konfiguration. **Ein falsches Gateway
  sieht man sofort** — das ist der Hauptgrund, warum es dieses Flag gibt.
- Das `$` in der `+ 完成`-Zeile ist echt, `累计` und `用时` sind auf dem `once`-Pfad konstant 0
  (für jedes Event wird ein neuer Renderer erzeugt, der Zustand sammelt sich nicht an).

Läuft dieser Schuss durch, stimmen Zugangsdaten, Gateway, Modellname und mitgeliefertes Binary alle,
das Problem liegt woanders. Läuft er nicht durch, gehört das zur Installation — zurück zu
[Installation](install.md).

## Was als Nächstes {#接下来}

| Du willst wissen | Lies |
|---|---|
| Was die Wörter auf dem Bildschirm eigentlich bedeuten | [Kernkonzepte](concepts.md) |
| Alle Unterbefehle und Flags, lückenlos | [CLI-Referenz](../reference/cli.md) |
| Warum es erst einen Haufen Fragen stellt und wie es weniger fragt | [Vorab-Klärung](../guide/clarify.md) |
| Wer urteilt, ob es fertig ist, und wie man die Prüfliste schreibt | [Zielwächter](../guide/goal.md) |
| Warum ein zweiter Lauf im selben Verzeichnis anknüpft | [Kontinuität](../guide/continuity.md) |
| Was es tut, wenn der Kontext voll ist (kein Compact) | [Handoff](../guide/handoff.md) |
| Zugangsdaten, Gateway, Modellname, Umgebungsvariablen | [Konfigurationsreferenz](../reference/config.md) |
| Das Terminal ersetzen, Web / TUI / vollautomatisch anbinden | [Interaktionsschicht](../guide/interaction.md) |
| Statt der mitgelieferten drei Schritte einen eigenen Workflow schreiben | [Workflows entwerfen](../guide/workflow.md) · [Python-API](../reference/api.md) |
| Was in einem echten Langlauf tatsächlich passiert ist | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| Die exakte Definition eines Begriffs | [Glossar](../reference/glossary.md) |
