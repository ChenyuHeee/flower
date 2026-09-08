# Goal Guard

Ob die Arbeit fertig ist, sagt nicht der Worker. Der [Judge](../reference/glossary.md#判定者) ist eine Rolle,
die nur Ziele setzt, nur beurteilt und selbst nichts anfasst: Vor dem Start macht er aus dem
[Brief](../reference/glossary.md#需求确认书) eine beurteilbare Liste, danach beurteilt er nach jeder Arbeitsrunde
**einmal unabhängig** und liefert ein [Verdict](../reference/glossary.md#判定) —
erreicht heißt weiter, nicht erreicht heißt zurückschicken mit „woran es fehlt",
und lautet das Urteil „nicht machbar", wird angehalten und der Mensch gefragt.

## Welches Problem das löst {#解决什么问题}

[Clarify](clarify.md) fängt ab: **„gebaut wurde nicht das, was gewollt war"**. Diese Schicht fängt etwas anderes ab:
**„eigentlich nicht fertig, aber es sagt selbst, es sei fertig"**. Die zwei Dinge müssen getrennt bleiben, weil die Art des Scheiterns verschieden ist:

| | Wie das Scheitern aussieht | Wann es auffliegt |
|---|---|---|
| Falsche Anforderung | Jedes Artefakt ist nach der falschen Anforderung gebaut | Stunden später, alles für die Tonne |
| Falsche Einschätzung der Fertigstellung | Halb durchgelaufene Tests, eine Stelle geändert und drei übersehen, „sollte passen" | Wenn du es selbst benutzt |

Warum die zweite Sorte nicht der Worker selbst abfangen kann: **Er hat einen systematischen Optimismus-Bias.**
Das ist keine Unehrlichkeit — er sieht seinen blinden Fleck nicht. Er weiß, was er getan hat, nicht, was er ausgelassen hat.

Deshalb geht das Verdict an eine Rolle, die **nicht mitgearbeitet hat und in einer eigenen [Session](../reference/glossary.md#会话) läuft**.
Sie sieht nur Ziel und Zustand vor Ort, weiß nicht, wie oft der Worker es versucht hat und wie mühsam es war,
und sucht ihm deshalb auch keine Ausreden. Das ist derselbe Grund, aus dem der Clarifier in einer eigenen Session läuft.

## Anwendung (minimaler Code) {#怎么用最小代码}

### Ohne Code: Kommandozeile {#零代码命令行}

```bash
flower                      # Goal Guard ist standardmäßig dabei
flower --no-goal            # abschalten: fertig ist, wenn die Arbeit durchgelaufen ist
flower --rounds 5           # höchstens fünf Arbeitsrunden (Default 3)
flower --judge-can-run      # Judge darf Befehle ausführen (härteres Verdict)
```

### Selbst verdrahten {#自己接线}

Zwei Funktionen, je eine Hälfte, nicht vermischen: `goal_step()` **setzt das Ziel** (ein eigener Schritt),
`with_goal()` ist die **Beurteilungsschleife** (umschließt einen Arbeitsschritt).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # standardmäßig unbegrenzt viele Rückfragen
goal_path = wb.notes / "目标.md"

work = Step("干活", spec=协调者, prompt=lambda ctx: f"照这个做:\n{ctx['确认需求']}")

wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    goal_step(ch, goal_path=goal_path),
    with_goal(work, ch, goal_path=goal_path, rounds=3),
])
```

`goal_step(channel, *, goal_path, ...)`:

| Parameter | Default | Bedeutung |
|---|---|---|
| `goal_path` | — | Wohin das Ziel geschrieben wird. Unter `notes/` der [Workbench](../reference/glossary.md#工作台), Begründung wie beim Brief |
| `brief_key` | `"确认需求"` | Aus welchem Key von `ctx` der Brief gelesen wird. **Wird er nicht gefunden, kommt nur `"(没有确认书)"` an** |
| `name` | `"设定目标"` | Schrittname, zugleich Key in `ctx` |
| `spec` / `instructions` | `None` / `""` | Eigenes `AgentSpec`, oder zusätzliche Domänenanweisungen für den Judge |
| `always_set` | `False` | `True` = jedes Mal neu setzen |
| `on_fail` / `retries` | `"stop"` / `0` | wie bei `Step` |
| `**spec_kw` | — | Durchgereicht an `judge()`: `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` verpackt einen Arbeitsschritt in eine Schleife mit Verdict:

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` ist die Gesamtzahl der Runden, nicht die Zahl zusätzlicher Runden** — es landet als `retries = max(0, rounds - 1)`,
also läuft `rounds=3` höchstens drei Arbeitsrunden, und `rounds=1` heißt „eine Runde laufen, einmal beurteilen, bei negativem Verdict scheitern".
Vollständige Signatur und Feldsemantik siehe [Python API](../reference/api.md).

In `ctx` kommen drei Keys dazu:

```python
ctx[GOAL_KEY]     # "_goal" —— Goal-Objekt; ctx["设定目标"] ist dessen Markdown
ctx[VERDICT_KEY]  # "_verdict" —— das letzte Verdict, für die UI
ctx[ROUND_KEY]    # "_goal_rounds" —— wie viele Runden gelaufen sind
```

Der Judge wird über `ctx["_runtime"]` losgeschickt — `Workflow.run` legt Runtime und Event-Ausgang in `ctx`,
damit `gate` selbst einen Agent starten kann und der Beurteilungsvorgang trotzdem in deiner UI ankommt
(sonst bleibt die Oberfläche die zehn, fünfzehn Sekunden schwarz und sieht aus wie ein Hänger).

Wenn es nicht rundläuft, zuerst an diesen Reglern drehen:

| Symptom | Welcher Regler |
|---|---|
| Verdict zu lasch, meldet erreicht, obwohl nicht erreicht | `--judge-can-run`, damit er es wirklich einmal ausführt; oder `instructions` um Domänenkriterien ergänzen |
| Verdict zu streng, schickt ständig zurück | Prüfen, ob die Prüfliste in `目标.md` höher greift als die Anforderung. **Diese Datei ändern** |
| Runde um Runde Leerlauf | Der Judge hätte „nicht machbar" geben müssen, gab aber „noch nicht erreicht". Ihm per Anweisung erklären, was als nicht machbar gilt |
| Zu teuer | `--rounds 1`, oder mit `--no-goal` ganz abschalten |
| Keine Unterbrechungen erwünscht | `--timeout 0`: bei „nicht machbar" wird niemand gefragt, es wird direkt gestoppt (die Begründung bleibt auf der Platte) |

## Was es tatsächlich tut {#它实际做了什么}

### Wie ein Ziel aussieht {#目标长什么样}

`goal_step` liest den Brief, gibt zwei Abschnitte aus und friert sie in `.flower/notes/目标.md` ein:

```markdown
# 目标
让 conv.py 能把 md 转成 html。

# 判定清单
- 跑 `python conv.py a.md` 产出 a.html
- 输出里含 `<h1>`
- 列表被转成 `<ul><li>`
```

**Die Prüfliste ist der gesamte Wert dieser Schicht.** „Vollständig implementiert" lässt sich nicht beurteilen,
„was ausführen, was sehen" schon. Die Liste kommt aus den „Abnahmekriterien" des Briefs, muss aber so umgeschrieben werden,
dass sich jeder Punkt an Ort und Stelle verifizieren lässt — was vage bleibt, ergänzt der Judge.
Vollständig ist es erst, wenn beide Abschnitte nicht leer sind (`statement` hat Inhalt, `checks` ist nicht leer), sonst lässt dieser Schritt nicht durch.

### Die Länge der Liste bestimmt sich danach, wie viele Arten des Scheiterns es gibt {#清单的长度由有多少种失败方式决定}

Nicht danach, wie gründlich der Judge ist. Für eine Aufgabe wie `git clone && make && ./app` reichen **drei bis fünf Punkte**:
Build läuft durch, es startet, es ist benutzbar.

**In der Praxis reingefallen** ([HT002](../cases/ht002.md)): Eine Aufgabe „Repo installieren und zum Laufen bringen" wurde zu einer Prüfliste mit **15 Punkten**,
davon prüften nur **5**, ob das Ding benutzbar ist, **6** prüften, ob der Prozess die Regeln eingehalten hat
(inklusive mtime von `~/.zshrc` und ob am Verzeichnis `.flower/` etwas geändert wurde — das ist das Verzeichnis des Frameworks selbst),
und **4** waren prinzipiell nicht prüfbar.

#### Grenzen sind keine Prüfpunkte {#边界不是判定项}

Das war damals die Hauptursache:

| | Was es einschränkt | Wie man es einhält |
|---|---|---|
| **Grenze** | **Wie du arbeitest** („nur innerhalb des Projektverzeichnisses installieren", „Fachcode nicht anfassen") | Indem man sie **nicht überschreitet**, nicht durch nachträglichen Selbstnachweis |
| **Prüfpunkt** | **Was abgeliefert wird** („läuft es", „stimmt das Ergebnis") | Durch Verifikation an Ort und Stelle |

„Hat kein `brew install` ausgeführt" als Prüfpunkt zu schreiben heißt: Jede zusätzliche Grenze erzeugt einen zusätzlichen Check —
und Grenzen sind genau das, was in der Clarify-Phase ausdrücklich vollständig aufgeschrieben werden soll.
Wenn es wirklich einen Nachweis braucht, dann in einem Satz, nicht aufgesplittet in sechs Punkte.

### Nicht prüfbare Punkte werden schon beim Zielsetzen gemeldet {#验不了的条目设目标时就会喊}

Für Punkte, die in der Liste mit `[此环境无法验证:原因]` markiert sind, gibt `goal_step` **in dem Moment, in dem das Ziel eingefroren wird**, einen Hinweis aus:

```text
  # 目标里有 4/15 条在这个环境里验不了 —— 判定时它们必然过不去,会停下来问你。
    现在改 .flower/notes/目标.md 还来得及:
      · 界面截图并实际看图 [此环境无法验证:屏幕录制未授权]
      · ...
```

**Warum vorab**: Das Schicksal dieser Punkte steht in dem Moment fest, in dem das Ziel gesetzt wird — beim Verdict fallen sie zwangsläufig durch.
Bei HT002 wurden erst **$35.90 für die Arbeit + $1.40 für das Verdict** ausgegeben und danach erst gemerkt —
verschiebt man die Erkenntnis auf den Schritt des Zielsetzens, sinken die Kosten für dieselbe Information von **$37** auf **$0**.

Es wird nur gewarnt, nicht blockiert: Man kann sich entscheiden, trotzdem so zu laufen (bei HT002 wurde am Ende genau „dieses Ergebnis akzeptieren" gewählt).
`Goal.unverifiable` ist diese Liste, und im Event-Payload liegen strukturierte Daten für die UI.

### Drei Ergebnisse, nicht zwei {#三个结论不是两个}

```text
干活 ──> 判定 ──达成────> 往下走
              ├─未达成──> 打回,带上“差在哪”,续跑同一个会话接着做
              └─无法达成─> 停下来问人:接受 / 改目标 / 你判断错了
```

Das dritte Ergebnis ist der entscheidende Punkt. Gäbe es nur „erreicht/nicht erreicht", würde ein Ziel, das **tatsächlich nicht machbar ist**,
den Koordinator Runde um Runde im Leerlauf drehen lassen, bis das Budget leer ist — und genau das verbrennt wirklich Geld.
Deshalb ist der Judge ausdrücklich angewiesen: „Nicht machbar" heißt „noch eine Runde bringt nichts"
(nötige externe Voraussetzung fehlt, die Anforderung widerspricht sich selbst, der Prüfpunkt ist grundsätzlich nicht verifizierbar);
bloßes „noch nicht fertig" ist „nicht erreicht".

Bei „nicht machbar" hält das Framework an und fragt den Menschen:

```text
  ? 目标被判为**无法达成**:缺少 X 依赖,判定项 2 无法验证
    怎么办?
     1) 接受这个结果,就这样往下走
     2) 修改目标
     3) 你判断错了,继续做
```

- **Akzeptieren** → der Schritt gilt als bestanden, die Begründung bleibt im Protokoll
- **Ziel ändern** → du wirst nach dem neuen Ziel gefragt, es wird an das alte Ziel **angehängt** (man sieht, was geändert wurde), dann noch eine Runde
- **Du liegst falsch** (und jede andere freie Antwort von dir) → mit deiner Aussage zurückschicken, noch eine Runde

**Antwortet niemand, wird angehalten**, statt weiter leerzulaufen — das ist Absicht. Wenn etwas als nicht machbar beurteilt wird und niemand da ist, den man fragen kann,
heißt Weiterlaufen Runde um Runde Geld verbrennen, und genau das gilt es zu vermeiden. Beim Anhalten wird `StepAbort` geworfen, der Grund landet in
`ctx["_aborted"]`, Zieldatei und `runs/manifest.json` liegen vor, der Mensch entscheidet weiter, wenn er zurück ist.

!!! warning "„Nicht geschafft" und „hier nicht prüfbar" sind zwei verschiedene Ergebnisse"
    Die drei Werte von `Verdict` sind `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` darf auf keinen Fall als bestanden gewertet werden** — es geht den Weg „anhalten und fragen", nicht „noch eine Runde".
    Was der Judge als „无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" schreibt, wird **ausnahmslos** auf
    `UNREACHABLE` abgebildet. „Hier nicht prüfbar" als „erreicht" zu werten heißt, die Arbeit mit einem „sieht aus, als sollte es gehen" abzuschließen;
    als „nicht erreicht" zu werten heißt, es Runde um Runde etwas wiederholen zu lassen, das ohnehin nicht prüfbar ist.

### Unklares Verdict = nicht erreicht {#判定含糊--未达成}

Erkennungsreihenfolge von `Verdict.parse`: zuerst wird über die Überschriften der Abschnitt „结论 / 判定" genommen; gibt es keine Überschriften,
gilt ein Text, der ganz aus `1` / `true` besteht, als erreicht, `0` / `false` als nicht erreicht (wenn der Judge angewiesen ist, „nur 0/1 zu liefern",
schickt er sehr wahrscheinlich wirklich nur eine Zahl); trifft das auch nicht, wird im Ergebnistext nach Schlüsselwörtern gesucht (längere zuerst); zuletzt nach einer alleinstehenden `1` / `0`.

**Trifft gar nichts, bleibt `state` leer, `ok` ist `False`, und das Framework behandelt es als nicht erreicht.** Das ist Absicht:
„nicht beurteilbar" und „fertig" sind zwei verschiedene Dinge, Unklarheit gilt ausnahmslos als nicht erreicht, plus eine Standardbegründung
(„Der Judge hat kein klares Ergebnis geliefert, wird als nicht erreicht behandelt").

### Beurteilt wird das Artefakt, nicht der Quellcode {#判的是产出物不是源码}

!!! warning "Ein Verdict, das nur den Quellcode liest, kann das Artefakt nicht beurteilen"
    In [HT001](../cases/ht001.md) lautete das Abnahmekriterium wörtlich „ein eigenständiges Executable kompilieren, das im macOS-Terminal
    direkt läuft", und das Verdict las nur, dass in `Makefile:25-38` tatsächlich ein Darwin-Zweig existiert, und wertete es als **bestanden** —
    das ausgelieferte Artefakt war ein `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **Falsch beurteilt hat nicht der Goal Guard**: In diesem Run gab es den Mechanismus noch nicht, diesen Punkt beurteilte ein
    unabhängiger Auditor, den der Koordinator selbst ad hoc losgeschickt hatte. Aber mit Goal Guard wäre es genauso durchgerutscht — der Judge hat per Default `can_run=False`,
    in der Hand nur `Read` / `Glob` / `Grep`, er **kann `file` nicht ausführen**, hätte also ebenfalls nur das `Makefile` lesen können und
    beim Anblick des Darwin-Zweigs ebenfalls auf erreicht erkannt. Der Kern dieses Fehlschlags liegt nicht bei „wer beurteilt", sondern bei „mit welchen Belegen beurteilt wird".

    Diese Lehre steht jetzt in `JUDGE_RULES`: Beurteilt wird das **Artefakt**, Schlüsse wie „im Quellcode gibt es einen macOS-Zweig, also
    sollte es laufen" werden nicht akzeptiert.

[HT002](../cases/ht002.md) ist der Run, in dem `judge_can_run` eingeschaltet war und der Judge tatsächlich `file` / `lsof` ausgeführt hat,
deshalb ist er dieser Falle entgangen — sein erster Satz war „Ich ziehe keinen Schluss aus dieser Antwort. Ich gehe hin und schaue nach." Und dann:

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → 起于 16:10,16:15 仍活着
```

Der Satz im Verdict-Prompt meint genau das: Selbst hingehen und nachsehen, Punkt für Punkt gegen die Prüfliste, und **ein Prüfpunkt, für den kein Beleg sichtbar ist,
ist nicht bestanden**.

### „Zurückschicken" heißt weitermachen, nicht neu anfangen {#打回是接着做不是重头做}

Das Zurückschicken nutzt `Step.on_reject`: In der nächsten Runde wird **genau die eben abgelehnte Session per `resume` fortgesetzt**, der Prompt wird durch das Verdict-Feedback ersetzt
(`Verdict.feedback()` gibt nur „woran es fehlt", keine Lösung). Damit sind die schon erledigte Arbeit, die gelesenen Dateien und die Umwege
noch im Kontext, und es muss nur die Lücke schließen.

Der Unterschied steht im Schrittnamen, in `runs/manifest.json` auf einen Blick zu sehen:

```text
干活            第一轮
干活#round2     被打回后接着做      ← on_reject 生效,resume 上一轮
干活#retry1     普通重试(重头跑)    ← 没有 on_reject 时的老行为
```

Der Judge selbst läuft dagegen **immer in einer neuen Session**: Das Gate von `with_goal` ruft direkt `Runtime.run` auf, ohne `resume`;
der Schrittname enthält die Runde (`干活·判定#1`), und Namen mit Suffix gehen nicht in die prozessübergreifende [Lineage](../reference/glossary.md#血缘) ein.
Kommt im Gate kein `ctx["_runtime"]` an, wird `StepAbort` geworfen — es wird **kein Bestehen vorgetäuscht**.

### Überspringen und Neusetzen {#跳过与重设}

Existiert die Zieldatei bereits und ist vollständig, wird dieser Schritt **übersprungen** (wie beim Brief) — wenn ein
[long-horizon](../reference/glossary.md#长程) Lauf abstürzt und neu gestartet wird, sollen die vorherigen Ergebnisse nicht noch einmal berechnet werden.
Zum Neusetzen die Datei löschen oder `always_set=True`.

**Ausnahme: Beim Wake hast du noch etwas gesagt.** Dieser Satz wird an den Brief angehängt, deshalb wird dieser Schritt **neu abgeleitet**
(`always_set=True`). Ohne Neuableitung liest der Judge weiterhin die eingefrorene alte Liste, und ob das neu Hinzugefügte erledigt ist,
kommt im Verdict überhaupt nicht vor — er würde nach der alten Liste auf „erreicht" erkennen. Die gemessenen Kosten der Neuableitung: **$0.41 / 3 Minuten**.
Siehe [Continuity](continuity.md).

### Darf der Judge Befehle ausführen {#判定者能不能跑命令}

Per Default **nein**. Die genehmigungsfreie Liste von `judge()` besteht aus den Rückfrage-Tools plus `Read` / `Glob` / `Grep`,
`Bash` kommt erst bei `can_run=True` dazu. Die Abwägung:

- Mit `Bash` (`--judge-can-run` im CLI) → er kann die Abnahmebefehle wirklich ausführen, das Verdict wird härter
- Aber er kann damit auch den Workspace verändern → er könnte „schnell noch etwas reparieren" und dann auf bestanden erkennen, womit dieses Verdict wertlos wäre

Wie beim Clarifier gilt: **kein `Write` / `Edit` / `Agent`**. Durchgesetzt wird das vom Hook `whitelist_guard`,
**nicht von `allowed_tools`** — letzteres ist eine **genehmigungsfreie Liste, keine exklusive Whitelist**, das Modell kann Tools aufrufen, die nicht darin stehen.
Zwei weiterhin gültige Messbelege: In HT002 hat der Judge im Schritt „设定目标" **11-mal `Bash`** ausgeführt,
obwohl `Bash` damals überhaupt nicht in seiner genehmigungsfreien Liste stand; in der **$0.1-Sonde** hat ein Agent mit
`allowed_tools=["Read"]` trotzdem `Write`- und `Bash`-Aufrufe abgesetzt, aufgehalten wurden sie von der Permission-Schicht und der Pfadsicherung
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Heute werden solche Aufrufe vom Hook sofort mit `deny` beantwortet —
**gestoppt wird es vom Hook, nicht von der Liste**.

!!! warning "Der Judge beim Zielsetzen bekommt per Default kein `Bash`"
    `goal_step()` **hat keinen `can_run`-Parameter**, es geht nur über `**spec_kw`: `goal_step(ch, goal_path=…, can_run=True)`.
    Ohne explizite Angabe hat er kein `Bash`, und die Regel aus `JUDGE_RULES` „erst mit `uname -a` klären, wo du bist" lässt sich nicht ausführen —
    er schreibt dir dann möglicherweise eine Prüfliste, die auf dieser Maschine gar nicht prüfbar ist. `with_goal()` ist eine andere Sache,
    es hat einen eigenen `can_run`-Parameter (Default `False`).

### Warum die Rundenzahl begrenzt ist, die Zahl der Rückfragen aber nicht {#为什么轮数有上限而提问次数没有}

Fragen kostet fast nichts, eine Arbeitsrunde kostet echtes Geld. Also:

- **Rückfragen unbegrenzt** (`max_asks=None`) — so lange fragen, bis es klar ist, entschieden vom Clarifier selbst
- **Rundenzahl begrenzt** (`rounds=3`) — aber die eigentliche Absicherung ist nicht diese Zahl, sondern das dritte Ergebnis „nicht machbar":
  Sobald es auftritt, wird angehalten und der Mensch gefragt, statt auf das Aufbrauchen der Runden zu warten

## Wann man es nicht einsetzen sollte {#什么时候不该用它}

**Die Aufgabe ist so klein, dass das Verdict umständlicher ist als die Arbeit.** Diese Schicht macht einfache Probleme kompliziert, und das ist gemessen:
Bei HT002, „ein Repo klonen, auf macOS installieren und zum Laufen bringen", wurde die Prüfliste 15 Punkte lang,
davon prüften 6 die Prozessdisziplin und 4 waren prinzipiell nicht prüfbar; dieses eine Verdict kostete **$1.4037 / 37 Runden / 0.09h**,
der gesamte Run **$38.2409 / 0.97h**. Wenn eine Aufgabe ohnehin nur zwei, drei Arten des Scheiterns hat, lohnt sich `--no-goal` mehr.

**Das Ziel lässt sich nicht in eine beurteilbare Liste fassen.** Explorative Arbeit („schau dir mal an, was in diesem Repo ungefähr los ist") hat kein Kriterium für „fertig",
und ein erzwungenes Ziel liefert nur eine hübsche, aber nicht beurteilbare Liste. Für so etwas `flower once` oder `--no-goal`.

**Der entscheidende Prüfpunkt ist in dieser Umgebung nicht prüfbar.** Der Judge hat per Default `can_run=False`, als Tools nur
`Read` / `Glob` / `Grep` — **er kann `file` nicht ausführen** und kann nur den Quellcode lesen. Das Abnahmekriterium „läuft direkt im macOS-Terminal"
aus [HT001](../cases/ht001.md) traf auf einen Run, der komplett in einem Linux-Container lief:
**Kein Judge kann im Container ein macOS-Binary verifizieren**, egal ob Selbstprüfung oder unabhängig.
`--judge-can-run` rettet einen Teil (zumindest lässt sich `file` ausführen); der Rest sollte schon beim Zielsetzen
als `[此环境无法验证:…]` markiert werden, damit er den Weg „anhalten und fragen" geht, statt darauf zu hoffen, dass der Judge schlauer wird.

**Unbeaufsichtigt und ohne erlaubte Unterbrechung.** Wird auf „nicht machbar" erkannt und antwortet niemand, **hält** dieser Schritt an, und der ganze [Workflow](../reference/glossary.md#流程) endet hier.
Wenn du „erst mal durchlaufen" willst, dann `--no-goal`; wenn du „anhalten, aber nicht warten" willst, dann `--timeout 0` —
die Rückfrage läuft sofort ins Leere, der Grund wird auf die Platte geschrieben.

**Es kümmert sich nicht darum, ob die Anforderung richtig ist.** Die Prüfliste wird aus dem Brief abgeleitet; ist der Brief falsch, verifiziert das Verdict nur präzise die falsche Sache.
Das ist Sache der Schicht [Clarify](clarify.md).
