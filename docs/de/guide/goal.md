# Goal Guard

Ob etwas fertig ist, entscheidet nicht der Worker. Der [Judge](../reference/glossary.md#判定者) ist eine Rolle,
die nur Ziele setzt, nur urteilt und selbst nichts anfasst: Vor dem Start macht er aus dem
[Brief](../reference/glossary.md#需求确认书) eine entscheidbare Prüfliste, danach urteilt er nach jeder
Arbeitsrunde **einmal unabhängig** und liefert ein [Verdict](../reference/glossary.md#判定) —
erreicht heißt weiter, nicht erreicht heißt zurück in die Arbeit mit der Angabe „woran es fehlt",
und lautet das Urteil „nicht machbar", wird angehalten und der Mensch gefragt.

## Welches Problem das löst {#解决什么问题}

[Clarify](clarify.md) fängt ab: **„gebaut wird nicht das, was gewollt war"**. Diese Schicht fängt etwas anderes ab:
**„eigentlich ist es nicht fertig, aber es sagt selbst, es sei fertig"**. Beides muss getrennt bleiben, weil die Fehlermodi verschieden sind:

| | Wie der Fehler aussieht | Wann er auffliegt |
|---|---|---|
| Falsche Anforderung | Jedes Artefakt ist auf der falschen Anforderung gebaut | Stunden später, alles Ausgelieferte ist Müll |
| Falsche Fertigstellungs-Einschätzung | Halb durchgelaufene Tests, an einer Stelle geändert und drei übersehen, „müsste passen" | Wenn du es selbst benutzt |

Warum der zweite Fall nicht vom Worker selbst kontrolliert werden kann: **er hat einen systematischen Optimismus-Bias**.
Das ist keine Unehrlichkeit — er sieht seinen eigenen blinden Fleck nicht. Er weiß, was er getan hat, nicht, was er ausgelassen hat.

Deshalb geht das Verdict an eine Rolle, die **nicht mitgearbeitet hat und in einer eigenen [Session](../reference/glossary.md#会话) läuft**.
Sie sieht nur das Ziel und den Ist-Zustand, weiß nicht, wie oft der Worker es versucht hat und wie mühsam es war — und sucht deshalb auch keine Entschuldigungen für ihn.
Das ist derselbe Grund, aus dem der Clarifier in einer eigenen Session läuft.

## Benutzung (minimaler Code) {#怎么用最小代码}

### Ohne Code: Kommandozeile {#零代码命令行}

```bash
flower                      # Goal Guard ist standardmäßig dabei
flower --no-goal            # aus: fertig ist, wenn die Arbeit durchgelaufen ist
flower --rounds 5           # höchstens fünf Arbeitsrunden (Default 3)
flower --judge-can-run      # Judge darf Kommandos ausführen (härteres Verdict)
```

### Selbst verdrahten {#自己接线}

Zwei Funktionen, je eine Hälfte, nicht vermischen: `goal_step()` **setzt das Ziel** (ein eigener Schritt),
`with_goal()` ist die **Verdict-Schleife** (legt sich um einen Arbeitsschritt).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # ohne Limit für Rückfragen (Default)
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
| `goal_path` | — | Wohin das Ziel geschrieben wird. Unter `notes/` der [Workbench](../reference/glossary.md#工作台), aus demselben Grund wie der Brief |
| `brief_key` | `"确认需求"` | Aus welchem Schlüssel in `ctx` der Brief gelesen wird. **Fehlt er, kommt nur `"(没有确认书)"` an** |
| `name` | `"设定目标"` | Schrittname, zugleich Schlüsselname in `ctx` |
| `spec` / `instructions` | `None` / `""` | Eigene `AgentSpec` oder zusätzliche Domänen-Anweisungen für den Judge |
| `always_set` | `False` | `True` = jedes Mal neu setzen |
| `on_fail` / `retries` | `"stop"` / `0` | Wie bei `Step` |
| `**spec_kw` | — | Wird an `judge()` durchgereicht: `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` verpackt einen Arbeitsschritt in eine Schleife mit Verdict:

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` ist die Gesamtzahl der Runden, nicht die Zahl der Zusatzrunden** — es landet als `retries = max(0, rounds - 1)`,
also läuft `rounds=3` höchstens drei Arbeitsrunden, und `rounds=1` heißt „eine Runde laufen, einmal urteilen, bei Nichtbestehen fehlgeschlagen".
Vollständige Signatur und Feldsemantik siehe [Python API](../reference/api.md).

In `ctx` kommen drei Schlüssel dazu:

```python
ctx[GOAL_KEY]     # "_goal" —— Goal-Objekt; ctx["设定目标"] ist dessen Markdown
ctx[VERDICT_KEY]  # "_verdict" —— das letzte Verdict, für die UI
ctx[ROUND_KEY]    # "_goal_rounds" —— wie viele Runden gelaufen sind
```

Der Judge wird über `ctx["_runtime"]` losgeschickt — `Workflow.run` legt Runtime und Event-Ausgang in `ctx`,
damit `gate` selbst einen Agent starten kann und der Verdict-Vorgang trotzdem in deiner UI ankommt
(sonst wäre die Oberfläche für ein Dutzend Sekunden schwarz und sähe aus wie ein Hänger).

Wenn es nicht rundläuft, zuerst an diesen Stellschrauben drehen:

| Symptom | Was drehen |
|---|---|
| Verdict zu lasch, sagt „erreicht", ist es aber nicht | `--judge-can-run`, damit es wirklich durchläuft; oder Domänenkriterien in `instructions` |
| Verdict zu streng, schickt ständig zurück | Prüfen, ob die Prüfliste in `目标.md` höher gesteckt ist als die Anforderung. **Diese Datei ändern** |
| Runde um Runde Leerlauf | Der Judge hätte „nicht machbar" geben müssen, gab aber „noch nicht erreicht". Ihm per Anweisung sagen, was als nicht machbar gilt |
| Zu teuer | `--rounds 1`, oder mit `--no-goal` ganz abschalten |
| Keine Unterbrechungen erwünscht | `--timeout 0`: bei „nicht machbar" wird niemand gefragt, es wird direkt gestoppt (Begründung bleibt auf der Platte) |

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

**Die Prüfliste ist der gesamte Wert dieser Schicht.** „Vollständig implementiert" ist nicht entscheidbar, „was ausführen, was sehen" schon.
Die Liste kommt aus den Abnahmekriterien des Briefs, muss aber so umgeschrieben werden, dass jeder Punkt an Ort und Stelle überprüfbar ist — unscharfe Punkte ergänzt der Judge.
Erst wenn beide Abschnitte nicht leer sind (`statement` hat Inhalt, `checks` ist nicht leer), gilt das Ziel als vollständig, sonst lässt dieser Schritt nicht durch.

### Die Länge der Liste bestimmt sich danach, wie viele Fehlermodi es gibt {#清单的长度由有多少种失败方式决定}

Nicht danach, wie gründlich der Judge ist. Für eine Aufgabe wie `git clone && make && ./app` reichen **drei bis fünf Punkte**:
Build erfolgreich, läuft an, benutzbar.

**In der Praxis reingefallen** ([HT002](../cases/ht002.md)): Für die Aufgabe „das Repo installieren und zum Laufen bringen" wurde eine Prüfliste mit **15 Punkten** geschrieben,
davon prüften nur **5**, „ob das Ding benutzbar ist", **6** prüften „ob der Prozess die Regeln eingehalten hat"
(inklusive Prüfung der mtime von `~/.zshrc` und ob das Verzeichnis `.flower/` verändert wurde — das ist das Verzeichnis des Frameworks selbst),
und **4** waren prinzipiell nicht prüfbar.

#### Grenzen sind keine Prüfpunkte {#边界不是判定项}

Das war damals die Hauptursache:

| | Was eingeschränkt wird | Wie man sich daran hält |
|---|---|---|
| **Grenze** | **Wie du arbeitest** („nur innerhalb des Projektverzeichnisses installieren", „Geschäftscode nicht anfassen") | Durch **Nicht-Überschreiten**, nicht durch nachträglichen Selbstbeweis |
| **Prüfpunkt** | **Das abgelieferte Artefakt** („läuft es", „ist das Ergebnis richtig") | Durch Verifikation an Ort und Stelle |

„Es wurde kein `brew install` ausgeführt" als Prüfpunkt zu schreiben heißt: jede zusätzliche Grenze erzeugt einen weiteren Check —
und Grenzen werden in der Clarify-Phase gerade dazu ermutigt, ausführlich aufgeschrieben zu werden. Wenn wirklich Rechenschaft nötig ist, ein Satz, nicht sechs Punkte.

### Nicht prüfbare Punkte werden schon beim Zielsetzen gemeldet {#验不了的条目设目标时就会喊}

Punkte, die in der Liste mit `[此环境无法验证:原因]` markiert sind, meldet `goal_step` **im Moment des Einfrierens des Ziels**:

```text
  # 目标里有 4/15 条在这个环境里验不了 —— 判定时它们必然过不去,会停下来问你。
    现在改 .flower/notes/目标.md 还来得及:
      · 界面截图并实际看图 [此环境无法验证:屏幕录制未授权]
      · ...
```

**Warum vorab**: Das Schicksal dieser Punkte steht im Moment des Zielsetzens fest, beim Verdict fallen sie zwangsläufig durch.
Bei HT002 wurden erst **$35.90 für Arbeit + $1.40 für Verdicts** ausgegeben, bevor das auffiel —
verlegt man die Erkenntnis auf den Schritt des Zielsetzens, sinken die Kosten für dieselbe Information von **$37** auf **$0**.

Nur ein Hinweis, keine Blockade: Man kann sich entscheiden, trotzdem so zu laufen (bei HT002 wurde am Ende genau „dieses Ergebnis akzeptieren" gewählt).
`Goal.unverifiable` ist diese Liste, im Event-Payload liegen strukturierte Daten für die UI.

### Drei Ergebnisse, nicht zwei {#三个结论不是两个}

```text
干活 ──> 判定 ──达成────> 往下走
              ├─未达成──> 打回,带上“差在哪”,续跑同一个会话接着做
              └─无法达成─> 停下来问人:接受 / 改目标 / 你判断错了
```

Das dritte Ergebnis ist der Schlüssel. Gäbe es nur „erreicht/nicht erreicht", würde ein Ziel, das **tatsächlich nicht erreichbar ist**, den Koordinator
Runde um Runde leerlaufen lassen, bis das Budget aufgebraucht ist — das ist echtes Geldverbrennen. Deshalb ist der Judge ausdrücklich angewiesen:
„nicht machbar" ist nur, was auch mit einer weiteren Runde nichts bringt (notwendige externe Voraussetzung fehlt, Anforderung widerspricht sich selbst, Prüfpunkt ist schlicht nicht verifizierbar);
„noch nicht fertig" ist „nicht erreicht".

Bei „nicht machbar" hält das Framework an und fragt den Menschen:

```text
  ? 目标被判为**无法达成**:缺少 X 依赖,判定项 2 无法验证
    怎么办?
     1) 接受这个结果,就这样往下走
     2) 修改目标
     3) 你判断错了,继续做
```

- **Akzeptieren** → dieser Schritt gilt als bestanden, die Begründung bleibt im Protokoll
- **Ziel ändern** → du wirst nach dem neuen Ziel gefragt, es wird an das alte Ziel **angehängt** (man sieht, was geändert wurde), dann eine weitere Runde
- **Du hast falsch geurteilt** (sowie jede beliebige Freitextantwort von dir) → mit deiner Aussage zurück in die Arbeit, eine weitere Runde

**Antwortet niemand, wird gestoppt**, es läuft nicht weiter leer — das ist Absicht. Wenn als nicht machbar geurteilt wurde und niemand da ist, den man fragen kann,
heißt Weiterlaufen: Runde um Runde Geld verbrennen, und genau das soll vermieden werden. Beim Stoppen wird `StepAbort` geworfen, der Grund landet in
`ctx["_aborted"]`, Zieldatei und `runs/manifest.json` liegen vor, der Mensch entscheidet weiter, wenn er zurück ist.

!!! warning "„Nicht geschafft" und „hier nicht prüfbar" sind zwei verschiedene Verdicts"
    Die drei Werte von `Verdict` sind `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` darf niemals als bestanden gewertet werden** — es geht den Weg „anhalten und den Menschen fragen", nicht „noch eine Runde".
    Schreibt der Judge „无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable", fällt das **ausnahmslos** unter
    `UNREACHABLE`. „Hier nicht prüfbar" als „erreicht" zu werten heißt, die Arbeit mit einem „sieht so aus, als ginge es" abzuschließen;
    als „nicht erreicht" zu werten heißt, es Runde um Runde etwas wiederholen zu lassen, das von vornherein nicht prüfbar war.

### Unklares Verdict = nicht erreicht {#判定含糊--未达成}

Die Erkennungsreihenfolge von `Verdict.parse`: zuerst wird über die Überschriften der Abschnitt „结论 / 判定" genommen; gibt es keine Überschriften,
zählt ein ganzer Abschnitt `1` / `true` als erreicht, `0` / `false` als nicht erreicht (wenn der Judge angewiesen ist, „nur 0/1 zu liefern",
kommt sehr wahrscheinlich tatsächlich nur eine Zahl zurück); trifft das nicht zu, wird im Ergebnistext nach Schlüsselwörtern gesucht (längere Wörter zuerst); zuletzt nach einer isolierten `1` / `0`.

**Trifft nichts davon, bleibt `state` leer, `ok` ist `False`, und das Framework behandelt es als nicht erreicht.** Das ist Absicht:
„lässt sich nicht beurteilen" und „ist fertig" sind zwei verschiedene Dinge, Unklarheit gilt durchweg als nicht erreicht, plus eine Standardbegründung
(„der Judge hat kein klares Ergebnis geliefert, wird als nicht erreicht behandelt").

### Geurteilt wird über das Artefakt, nicht über den Quellcode {#判的是产出物不是源码}

!!! warning "Ein Verdict, das nur Quellcode liest, prüft nicht das Artefakt"
    In [HT001](../cases/ht001.md) lautete das Abnahmekriterium im Original „eine eigenständige ausführbare Datei kompilieren, die direkt im macOS-Terminal läuft",
    und das Verdict las lediglich `Makefile:25-38`, fand dort tatsächlich einen Darwin-Zweig und urteilte auf **bestanden** —
    ausgeliefert wurde ein `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **Fehlgeurteilt hat nicht der Goal Guard**: In diesem Run gab es diesen Mechanismus noch nicht, geurteilt hat ein
    unabhängiger Auditor, den der Koordinator selbst ad hoc losgeschickt hatte. Aber mit Goal Guard wäre es genauso durchgerutscht — der Judge hat per Default `can_run=False`,
    ihm stehen nur `Read` / `Glob` / `Grep` zur Verfügung, er **kann `file` nicht ausführen**, hätte also ebenfalls nur das `Makefile` lesen können und
    beim Anblick des Darwin-Zweigs ebenfalls auf „erreicht" geurteilt. Der Kern dieses Fehlschlags liegt nicht bei „wer urteilt", sondern bei „mit welchen Belegen geurteilt wird".

    Diese Lehre steht jetzt in `JUDGE_RULES`: geurteilt wird über das **Artefakt**, Schlüsse wie „im Quellcode gibt es einen macOS-Zweig, also
    müsste es laufen" werden nicht akzeptiert.

[HT002](../cases/ht002.md) ist der Run, in dem `judge_can_run` eingeschaltet war und der Judge tatsächlich `file` / `lsof` ausgeführt hat,
deshalb ist er in diese Falle nicht getappt — sein erster Satz war „Ich urteile nicht anhand dieser Antwort. Ich gehe hin und sehe nach." Und dann:

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → 起于 16:10,16:15 仍活着
```

Der entsprechende Satz im Verdict-Prompt meint genau das: selbst nachsehen, Punkt für Punkt gegen die Prüfliste, und **ein Prüfpunkt, für den kein Beleg zu sehen ist,
ist nicht bestanden**.

### „Zurückschicken" heißt weiterarbeiten, nicht von vorn anfangen {#打回是接着做不是重头做}

Das Zurückschicken nutzt `Step.on_reject`: die nächste Runde macht **`resume` auf genau der Session, die gerade abgelehnt wurde**, der Prompt wird durch das Verdict-Feedback ersetzt
(`Verdict.feedback()` gibt nur „woran es fehlt", keine Lösung). Also stehen die bereits erledigte Arbeit, die gelesenen Dateien und die Umwege
weiterhin im Kontext, es muss nur die Lücke geschlossen werden.

Der Unterschied steht im Schrittnamen und ist in `runs/manifest.json` auf einen Blick sichtbar:

```text
干活            erste Runde
干活#round2     nach Ablehnung weitergearbeitet   ← on_reject greift, resume der Vorrunde
干活#retry1     normaler Retry (von vorn)         ← altes Verhalten ohne on_reject
```

Der Judge selbst läuft dagegen **immer in einer neuen Session**: das gate von `with_goal` ruft direkt `Runtime.run` auf, ohne `resume`;
der Schrittname trägt die Rundennummer (`干活·判定#1`), und Namen mit Suffix gehen nicht in die prozessübergreifende [Lineage](../reference/glossary.md#血缘) ein.
Ist im gate kein `ctx["_runtime"]` verfügbar, wird `StepAbort` geworfen, **es wird kein Bestehen vorgetäuscht**.

### Überspringen und Neusetzen {#跳过与重设}

Existiert die Zieldatei bereits und ist vollständig, wird dieser Schritt **übersprungen** (wie beim Brief) — wenn ein
[Long-Horizon](../reference/glossary.md#长程)-Run abgestürzt ist und neu startet, sollen die früheren Schlüsse nicht noch einmal berechnet werden. Zum Neusetzen die Datei löschen oder `always_set=True`.

**Ausnahme: beim Wake hast du noch etwas gesagt.** Dieser Satz wird an den Brief angehängt, also wird dieser Schritt **neu abgeleitet**
(`always_set=True`). Ohne Neuableitung liest der Judge weiter die eingefrorene alte Liste, und ob das von dir neu Hinzugefügte erledigt ist,
geht gar nicht ins Verdict ein — er würde nach der alten Liste auf „erreicht" urteilen. Die Kosten der Neuableitung liegen gemessen bei **$0.41 / 3 Minuten**.
Siehe [Continuity](continuity.md).

### Darf der Judge Kommandos ausführen {#判定者能不能跑命令}

Per Default **nein**. Die genehmigungsfreie Liste von `judge()` besteht aus den Frage-Tools plus `Read` / `Glob` / `Grep`,
`Bash` kommt erst bei `can_run=True` dazu. Der Trade-off:

- Mit `Bash` (`--judge-can-run` im CLI) → die Abnahmekommandos können wirklich ausgeführt werden, das Verdict wird härter
- Aber damit kann er den Arbeitsbereich verändern → er könnte „schnell noch etwas reparieren" und dann auf bestanden urteilen, womit dieses Verdict wertlos wäre

Wie beim Clarifier gilt: **kein `Write` / `Edit` / `Agent`**. Durchgesetzt wird das vom Hook `whitelist_guard`,
**nicht von `allowed_tools`** — Letzteres ist eine **genehmigungsfreie Liste, keine exklusive Whitelist**, das Modell kann Tools, die nicht darin stehen, weiterhin aufrufen.
Zwei weiterhin gültige Messbelege: In HT002 hat der Judge im Schritt „设定目标" **11-mal `Bash`** ausgeführt,
obwohl `Bash` damals in seiner genehmigungsfreien Liste überhaupt nicht stand; in der **$0.1-Sonde** hat ein Agent mit
`allowed_tools=["Read"]` trotzdem `Write`- und `Bash`-Aufrufe abgesetzt, und es waren die Berechtigungsschicht und die Pfadsicherheit, die sie abgefangen haben
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Heute werden diese beiden Aufrufe vom Hook sofort mit `deny` beantwortet —
**gestoppt wird er vom Hook, nicht von der Liste**.

!!! warning "Der Judge beim Zielsetzen bekommt per Default kein `Bash`"
    `goal_step()` **hat keinen Parameter `can_run`**, es geht nur über `**spec_kw`: `goal_step(ch, goal_path=…, can_run=True)`.
    Ohne explizite Angabe hat er kein `Bash`, und die Regel aus `JUDGE_RULES` „erst `uname -a`, um zu sehen, wo du bist" lässt sich nicht ausführen —
    also schreibt er dir womöglich eine Prüfliste, die auf dieser Maschine gar nicht verifizierbar ist. `with_goal()` ist eine andere Sache,
    es hat einen eigenen Parameter `can_run` (Default `False`).

### Warum die Rundenzahl begrenzt ist, die Zahl der Rückfragen aber nicht {#为什么轮数有上限而提问次数没有}

Fragen kostet fast nichts, eine Arbeitsrunde kostet echtes Geld. Also:

- **Fragen ohne Limit** (`max_asks=None`) — so lange fragen, bis es klar ist, das entscheidet der Clarifier selbst
- **Runden mit Obergrenze** (`rounds=3`) — aber die eigentliche Absicherung ist nicht diese Zahl, sondern das dritte Ergebnis „nicht machbar":
  sobald es auftritt, wird angehalten und der Mensch gefragt, statt auf das Ablaufen der Runden zu warten

## Wann man es nicht einsetzen sollte {#什么时候不该用它}

**Die Aufgabe ist so klein, dass das Verdict umständlicher ist als die Arbeit.** Diese Schicht macht einfache Probleme kompliziert, und das ist gemessen:
Bei HT002 — „ein Repo klonen, unter macOS installieren und starten" — wurde die Prüfliste auf 15 Punkte aufgebläht,
davon prüften 6 die Prozessregeln und 4 waren prinzipiell nicht prüfbar; jene Verdict-Runde allein kostete **$1.4037 / 37 Turns / 0.09h**,
der gesamte Run **$38.2409 / 0.97h**. Wenn eine Aufgabe ohnehin nur zwei oder drei Fehlermodi hat, ist `--no-goal` günstiger.

**Das Ziel lässt sich nicht in eine entscheidbare Liste fassen.** Explorative Arbeit („mal schauen, was es mit diesem Repo auf sich hat") hat kein Kriterium für „fertig",
ein erzwungenes Ziel liefert nur eine schöne, aber nicht entscheidbare Liste. Für solche Arbeit `flower once` oder `--no-goal`.

**Der entscheidende Prüfpunkt ist in dieser Umgebung nicht verifizierbar.** Der Judge hat per Default `can_run=False`, als Tools nur
`Read` / `Glob` / `Grep` — **er kann `file` nicht ausführen** und kann nur den Quellcode lesen. Das Abnahmekriterium aus [HT001](../cases/ht001.md),
„läuft direkt im macOS-Terminal", stand einem Run gegenüber, der komplett in einem Linux-Container lief:
**kein Judge kann innerhalb des Containers ein macOS-Binary verifizieren**, egal ob er selbst prüft oder unabhängig ist.
`--judge-can-run` rettet einen Teil (zumindest lässt sich `file` ausführen); der Rest sollte schon beim Zielsetzen
als `[此环境无法验证:…]` markiert werden, damit er den Weg „anhalten und den Menschen fragen" nimmt, statt darauf zu hoffen, dass der Judge schlauer wird.

**Unbeaufsichtigt und ohne erlaubte Unterbrechung.** Wird auf „nicht machbar" geurteilt und antwortet niemand, **stoppt** dieser Schritt, und der gesamte [Workflow](../reference/glossary.md#流程) endet hier.
Wer „erst mal durchlaufen lassen" will, nimmt `--no-goal`; wer „anhalten, aber nicht warten" will, nimmt `--timeout 0` —
die Frage läuft sofort ins Leere, der Grund wird auf die Platte geschrieben.

**Es kümmert sich nicht darum, ob die Anforderung richtig ist.** Die Prüfliste wird aus dem Brief abgeleitet; ist der Brief falsch, verifiziert das Verdict nur präzise etwas Falsches.
Das ist Sache der Schicht [Clarify](clarify.md).
