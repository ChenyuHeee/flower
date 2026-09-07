# Schnellstart

Diese Seite führt von „installiert" zu „einmal wirklich durchgelaufen — und du verstehst, was auf dem Bildschirm steht". Vier Abschnitte, der Reihe nach abzuarbeiten:
erst mit dem billigsten Schuss beweisen, dass Credentials und Binary beide funktionieren, dann ohne eine Zeile Code einen kompletten Workflow fahren,
danach lernen, ihm während des Laufs dazwischenzureden, und zuletzt das Ganze unbeaufsichtigt in ein Skript stecken.

Es gibt genau eine Voraussetzung: `flower` ist installiert, liegt im PATH, Credentials sind konfiguriert. Wer noch nicht installiert hat, liest zuerst [Installation](install.md).

## Schritt 1: Mit dem billigsten Schuss prüfen {#冒烟}

Fang nicht sofort mit dem kompletten Workflow an. Setz erst einen Schuss mit einem einzelnen Agent und nur lesenden Tools ab, um zu beweisen, dass Credentials und Binary auf beiden Seiten durchgehen:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| Dieses Stück | Was es ist |
|---|---|
| `once` | Ein einzelner Agent-Lauf: keine Anforderungsklärung, kein Ziel, keine Delegation |
| `-w PATH` | Arbeitsverzeichnis des Agents. Ohne Angabe das aktuelle Verzeichnis |
| `-v` | Gibt vor dem Start die wirksame Credential-Konfiguration aus, vom Token bleiben nur die ersten 4 Stellen |

`once` gibt standardmäßig nur drei Tools frei — `Read`, `Glob`, `Grep`. Es kann nichts schreiben, deshalb ist dieser Schuss billig.
Messwert zur Orientierung: Opus 5 mit 1-Millionen-Fenster über ein Drittanbieter-Gateway, **Bodenpreis pro Runde $0.1741**, billigere Modelle liegen darunter.

!!! tip "Wer von der Installationsseite kommt, kann das überspringen"
    Der Abschnitt „Prüfen, ob die Installation sitzt" auf der Seite [Installation](install.md) fährt genau diesen Befehl. Wenn er durchgelaufen ist, geh weiter;
    das Folgende zeigt dir nur, wie du seine Ausgabe liest.

Nach der Ausführung solltest du diese Form sehen — Zahlen und Fließtext werden anders aussehen, **die Icons nicht**:

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

Vier Dinge musst du wiedererkennen, die folgenden Schritte hängen alle daran:

- Die ersten Zeilen sind die von `-v` ausgegebene wirksame Konfiguration. **Ein falsch verbundenes Gateway siehst du auf einen Blick** — das ist der Hauptgrund, warum es diesen Schalter gibt.
- `- 验一下凭证…` ist eine echte API-Sonde vor dem Start. Werden die Credentials abgelehnt, kommt `! 凭证被拒:…` und du wirst sofort gefragt, ob du neu konfigurieren willst;
  kommt keine Verbindung zustande, kommt `(探针没打通:… —— 当作网络问题,照常开跑)` — es schickt dich **nicht** los, ein völlig intaktes Token neu einzurichten.
- Die Icons sind durchgängig ASCII: `~` Denken, `*` Tool-Aufruf, `>` Delegation, `+` Erfolg, `x` Fehlschlag, `?` Frage, `<-` Anknüpfen an letztes Mal.
  Keine Emojis — Emojis und Rahmenzeichen lösen Glyph-Fallback im Terminal aus, im Test hat das zweimal das Terminal abgeschossen. **Alle Terminal-Beispiele in dieser Dokumentation
  verwenden dieses ASCII-Set, exakt so wie auf deinem Bildschirm.**
- Das `$` in der Zeile `+ 完成` ist echt; `累计` und `用时` sind auf dem `once`-Pfad konstant 0
  (pro Event wird ein neuer Renderer angelegt, der Zustand sammelt sich nicht an).

Läuft dieser Schuss durch, stimmen Credentials, Gateway, Modellname und mitgeliefertes Binary. Läuft er nicht durch, gehört das zur Installation — zurück zu [Installation](install.md).

## Schritt 2: Ohne eine Zeile Code einen kompletten Workflow fahren {#跑一次}

Du musst keinen Code schreiben und **musst in der Shell keine Anführungszeichen tippen**. Geh in dein Projektverzeichnis und tipp einfach:

```bash
cd /path/to/your/project
flower
```

Es fragt dich, was zu tun ist, der Cursor steht auf dem `>`:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

Diese Zeile wird von der Standardeingabe gelesen und **geht nicht durch die Shell-Auswertung** — chinesische Anführungszeichen, Leerzeichen, Ausrufezeichen kannst du direkt eintippen.

Nach Enter geht es in drei Schritten weiter. Jede `==`-Trennlinie auf dem Bildschirm ist eine [Schritt](../reference/glossary.md#步骤)-Grenze,
das `1/3` rechts ist der Fortschritt:

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

Drei Stellen lohnen einen zweiten Blick:

- Die letzten beiden `+ 完成`-Zeilen sind keine Dopplung. Die erste ist die Arbeitsrunde, die zweite ist die **Urteilsrunde** —
  das Urteil läuft in einer eigenen Session, bekommt aber **keine eigene `==`-Trennlinie**, weil es eine Runde innerhalb des Schritts `干活` ist.
  Im [Run-Manifest](../reference/glossary.md#运行清单) heißt sie `干活·判定#1`.
- Das `$` in einer `+ 完成`-Zeile ist das Geld **dieser einen Runde**, `用时` ist die Gesamtdauer **seit dem Start** — zwei verschiedene Maße.
- Statuszeilen der Art `- 上下文 … · 累计 … · …` folgen nur dem [Hauptthread](../reference/glossary.md#主线程),
  der Kontext von Subagents steckt nicht darin. Tool-Aufrufe von Subagents werden standardmäßig angezeigt, eingerückt hinter einem `|`-Strich;
  was sie **sagen**, siehst du nur mit `-v` — das ist das Geschehen vor Ort, nicht die Entscheidung.

### Was diese drei Schritte sind, die du da siehst {#三步}

| Schritt auf dem Bildschirm | Wer läuft | Was er tut | Eingefroren als | Details |
|---|---|---|---|---|
| `确认需求` | [Klärer](../reference/glossary.md#确认者) | Fragt nur, fasst nichts an, **fragt so lange, bis es klar ist, ohne Rundenobergrenze**; am Ende ein vierteiliges [Anforderungsdokument](../reference/glossary.md#需求确认书) | `.flower/notes/需求.md` | [Vorab-Klärung](../guide/clarify.md) |
| `设定目标` | [Judge](../reference/glossary.md#判定者) | Übersetzt das Anforderungsdokument in „Ziel + Urteilsliste", jeder Punkt muss auf der Stelle prüfbar sein | `.flower/notes/目标.md` | [Zielwächter](../guide/goal.md) |
| `干活` | [Koordinator](../reference/glossary.md#协调者) delegiert an [Subagents](../reference/glossary.md#subagent) | Der Koordinator zerlegt die Arbeit, delegiert, liest Berichte, trifft Entscheidungen; am Ende jeder Runde urteilt ein Judge, der **nicht mitgearbeitet hat**, unabhängig darüber, ob es fertig ist — ist es nicht erreicht, geht es zurück in die Arbeit | der Code selbst | [Zielwächter](../guide/goal.md) |

Die ersten beiden Schritte sind die konkrete Umsetzung der Mechanismen [Vorab-Klärung](../reference/glossary.md#前置确认) und [Zielwächter](../reference/glossary.md#目标看守);
der dritte Schritt ist die Strecke, die beide zusammen verwalten. Standardmäßig laufen höchstens 3 Urteilsrunden (`--rounds`),
mit `--no-goal` lässt sich das komplett abschalten — danach gilt „es sagt, es sei fertig" tatsächlich als fertig.

Ein Urteil kennt nur drei Ausgänge: erreicht, nicht erreicht, **in dieser Umgebung nicht prüfbar**. Die letzten beiden sind unterschiedliche Ergebnisse —
„hier nicht prüfbar" wird auf keinen Fall als bestanden gewertet, sondern hält an und fragt dich.

Ein kompletter Lauf ist nicht billig. Messwerte zur Orientierung: [HT002](../cases/ht002.md) hat ein bestehendes Projekt auf macOS installiert und zum Laufen gebracht,
4 Schritte, rund 1 Stunde, **$38.24**; [HT001](../cases/ht001.md) hat von null eine Terminal-IDE geschrieben,
**10.4 Stunden, $171.62**. Wer erst sehen will, was es fragt, bevor er sich zum Weiterlaufen entscheidet, nimmt `--clarify-only`.

### Wie man auf Fragen antwortet {#答提问}

Der Abschnitt, der mit `?` beginnt, ist eine Frage an dich, drei Antwortarten:

- **Nummer tippen** (`1` / `2` / `3`) — wählt diesen Punkt, der Bildschirm antwortet mit einer Zeile `+ <ausgewählter Punkt>`.
- **Direkt tippen** — freie Antwort, sie muss nicht aus den Optionen stammen.
- **Nur Enter** — überspringen, es entscheidet selbst, der Bildschirm antwortet mit einer Zeile `. 已跳过`.

Standardmäßig wartet es 1800 Sekunden auf dich (`--timeout`). Kommt niemand, schreibt es
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` und läuft weiter, ohne hängenzubleiben.
Die Zahl der Fragen ist **standardmäßig unbegrenzt** (`--asks` steht auf `-1`); ein positiver Wert ist ein hartes Kontingent, ist es aufgebraucht, kommt `! 提问额度用完`.

### Nochmal starten heißt: da weitermachen, wo es aufhörte {#再跑一次}

Tippst du im selben Verzeichnis erneut `flower`, lautet der erste Satz anders:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

Die `<-`-Zeile ist das [Wake](../reference/glossary.md#唤醒)-Banner, es meldet den aktuellen Zustand dieses Verzeichnisses.
Es verhört dich nicht noch einmal zu den Anforderungen und setzt die Ziele nicht neu; ob der Prozess gekillt wurde oder die Maschine neu gestartet ist, macht keinen Unterschied.
Der Satz, den du jetzt sagst, wird an `需求.md` angehängt und **löst eine Neuableitung der Urteilsliste aus** —
ohne Neuableitung läse der Judge weiter die alte Liste, und was du neu ergänzt hast, käme im Urteil überhaupt nicht vor.
Details und Kosten (der Kontext wächst dauerhaft) siehe [Kontinuität](../guide/continuity.md).

Wer nicht anknüpfen will, tippt `/new`: Anforderungen, Ziele und [Lineage](../reference/glossary.md#血缘) der letzten Strecke
werden nach `notes/archive/<时间戳>/` **verschoben** (nicht gelöscht), dann geht es von vorn los.

## Schritt 3: Auch während es läuft, kannst du reden {#插话}

Ganz unten auf dem Bildschirm steht immer ein Prompt, in den du tippen kannst. Das ist keine Dekoration — vor jeder Ausgabe wird er gelöscht, danach neu gezeichnet,
deshalb **wird er nicht von Logzeilen nach oben weggeschoben**. Zwei Varianten, je nachdem, ob eine Frage offen ist:

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

Wenn keine Frage offen ist, kannst du zwei Dinge tun.

**Einfach einen Satz tippen = Anforderung ergänzen.** Es wird nicht unterbrochen, sondern sieht ihn erst beim nächsten Blick in den Posteingang. Die Quittung sieht so aus:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

„已追加进确认书" ist wichtig: Der Satz landet gleichzeitig in `需求.md` und überlebt damit die Schrittgrenze —
der nächste Schritt ist eine neue Session, die nur die eingefrorenen Artefakte liest; ohne Persistieren wäre der Satz so gut wie nie gesagt.

**Mit `?` beginnen = mal eben nachfragen.** Es startet eine separate, nur lesende Session, um dir zu antworten, mit nichts weiter als den letzten 60 Events und dem,
was in der [Werkbank](../reference/glossary.md#工作台) liegt. Dieser Seitenkanal läuft über das
[Oracle](../reference/glossary.md#旁路顾问), standardmäßig gedeckelt auf 12 Runden / $0.5:

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Nach der Antwort weggeworfen** — dieser Frage-Antwort-Block kommt nicht in den Kontext dieses Runs, die Kosten nicht ins Haupt-Run-Manifest,
sie werden in einem eigenen Manifest unter `runs/aside/` festgehalten. Fragen stört den Run also nicht, und um das Geld auf der Hauptrechnung musst du dich nicht sorgen.

!!! warning "Vollbreites `？` zählt nicht, es muss ein halbbreites `?` sein"
    Der Seitenkanal wird nur am **halbbreiten** `?` (ASCII `0x3f`) erkannt. Das vollbreite `？`, das chinesische Eingabemethoden standardmäßig erzeugen, wird nicht erkannt —
    die Zeile wandert dann als „Anforderung ergänzen" in den Posteingang, **ohne Fehlermeldung**, und die Antwort, auf die du wartest, kommt nie.
    Das ist ein Tippfehler im Code, er steht auf der Bugliste; bis er behoben ist, schalte vor dem `?` die Eingabemethode auf Englisch.

Nebenbei zu Ctrl+C: Während des Laufs **unterbricht** das erste Drücken diese Runde und lässt dich etwas sagen, es beendet nicht.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

Erst ein zweites Drücken beendet wirklich. (Am allerersten Prompt `要做什么?` beendet Ctrl-C direkt und gibt `已取消` aus.)

## Schritt 4: Ins Skript schreiben {#脚本}

Das Anliegen kann auch direkt als Argument übergeben werden, die Schalter dürfen davor oder dahinter stehen:

```bash
flower "帮我做一个 X"                      # Anliegen als Argument
flower --rounds 5 "帮我做一个 X"           # Schalter davor
flower "帮我做一个 X" --rounds 5           # Schalter dahinter, gleichwertig
echo "帮我做一个 X" | flower --timeout 0   # Per Pipe in die Standardeingabe, vollautomatisch
```

Nur Schalter ohne Anliegen geht auch — `flower --clarify-only` fragt dich erst, was zu tun ist, und läuft dann weiter.

**Warum der Weg „erst Enter, dann tippen" erhalten bleibt.** Das Anführungszeichenpaar auf der Kommandozeile ist reine Last. Im Praxistest passiert: Das schließende
Anführungszeichen wurde als chinesisches `”` getippt, zsh wartete daraufhin endlos auf das echte schließende Zeichen (landete im Fortsetzungs-Prompt `dquote>`),
es sah aus, als hinge das Programm — dabei war es kein einziges Mal gestartet. Läuft `flower` nackt, liest es von der Standardeingabe, ohne Shell-Auswertung,
chinesische Anführungszeichen, Leerzeichen, Ausrufezeichen, Zeilenumbrüche kannst du alle direkt eingeben. Der Pipe-Weg nutzt denselben Eingang —
ist die Standardeingabe kein Terminal, druckt es keinen Prompt-Kopf, sondern liest direkt eine Zeile.

!!! danger "Unbeaufsichtigt muss `--timeout 0` explizit gesetzt werden"
    In einer Pipe, unter `nohup` oder in CI kann niemand Fragen beantworten. Ohne `--timeout 0` passiert: Die erste Frage wird wegen
    „Eingabe geschlossen" übersprungen, **danach wartet jede weitere Frage die vollen 1800 Sekunden ab** — ein paar Fragen sind ein paar Stunden Leerlauf,
    und in dieser Zeit wird Geld verbrannt.
    `--timeout 0` lässt jede Frage sofort mit „keine Antwort" zurückkommen, es entscheidet selbst und läuft weiter.
    Ist die Standardeingabe kein Terminal, gibt flower zuerst eine Warnzeile aus:
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## Was als Nächstes lesen {#接下来}

| Du willst wissen | Lies |
|---|---|
| Was die Wörter auf dem Bildschirm eigentlich bedeuten | [Kernkonzepte](concepts.md) |
| Alle Unterbefehle und Schalter, lückenlos | [CLI-Referenz](../reference/cli.md) |
| Warum es erst einen Haufen Fragen stellt und wie es weniger fragt | [Vorab-Klärung](../guide/clarify.md) |
| Wer urteilt, ob es fertig ist, und wie eine Urteilsliste geschrieben wird | [Zielwächter](../guide/goal.md) |
| Warum ein zweiter Lauf im selben Verzeichnis anknüpft | [Kontinuität](../guide/continuity.md) |
| Was passiert, wenn der Kontext voll ist (kein compact) | [Handoff](../guide/handoff.md) |
| Credentials, Gateway, Modellname, Umgebungsvariablen | [Konfigurationsreferenz](../reference/config.md) |
| Das Terminal austauschen, an Web / TUI / Vollautomatik anschließen | [Interaktionsschicht](../guide/interaction.md) |
| Statt der mitgelieferten drei Schritte einen eigenen Workflow schreiben | [Workflow entwerfen](../guide/workflow.md) · [Python-API](../reference/api.md) |
| Was in einem echten Langlauf tatsächlich passiert ist | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| Die exakte Definition eines Begriffs | [Glossar](../reference/glossary.md) |
