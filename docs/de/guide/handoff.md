# Handoff

Wenn der Kontext fast voll ist, lässt du **diese Session selbst** ein [Handoff-Dokument](../reference/glossary.md#交接书) schreiben, das ein Mensch lesen und ändern kann, und öffnest dann eine neue Session, die übernimmt. Ohne compact. Der ganze Vorgang ist im Terminal sichtbar, das Dokument liegt auf der Platte, du kannst es jederzeit ändern — die übernehmende Session liest genau diese Datei.

!!! note "Handoff ist nicht Continuity"
    [Handoff](../reference/glossary.md#换代) heißt: **innerhalb desselben Laufs** auf eine neue [Session](../reference/glossary.md#会话) wechseln;
    [Continuity](../reference/glossary.md#接续) heißt: **prozessübergreifend** an den vorigen [Lauf](../reference/glossary.md#运行) anknüpfen,
    siehe [Continuity](continuity.md).

    Beides greift automatisch ineinander, ohne zusätzliche Verdrahtung: die [Lineage](../reference/glossary.md#血缘) hält die **letzte** `session_id` dieses Schritts fest, und genau die ist der Nachfolger — der nächste Wake knüpft also am Nachfolger an, nicht an der verbrannten Generation.

## Welches Problem das löst {#解决什么问题}

Der eingebaute auto-compact des SDK löst bei **Fenster −33k** aus (gemessen: bei Fenster `200000` liegt die Schwelle bei `167000`; der Kompressionsalgorithmus selbst steckt im Harness-Binary, daran lässt sich nichts ändern, nur ob er auslöst), und was er tut, ist **die Historie zu einem Absatz zusammenzufassen**. Das steht quer zum Rest dieses Frameworks:

| | Wann wird entschieden | Was bleibt übrig |
|---|---|---|
| `spill_guard` | in dem Moment, in dem das Tool zurückkommt | großes Ergebnis wird [gespillt](../reference/glossary.md#落盘), im Kontext bleibt eine Zeile mit dem Pfad |
| Gefrorenes Artefakt (Brief / Ziel) | am Ende des jeweiligen Schritts | ein Dokument, der nächste Schritt liest nur dieses |
| **auto-compact** | **erst wenn der Kontext voll ist, im Rückblick** | **ein vom Modell selbst geschriebener Absatz** |

Was flower von vorn bis hinten tut, ist **an Ort und Stelle zu entscheiden, was bleibt**. [Compact](../reference/glossary.md#压缩) ist die einzige Stelle mit „nachträglicher Reparatur", und sein Ergebnis hat vier Mängel:

- **vom Modell erzeugt** — was in der Zusammenfassung steht, entscheidet die momentane Einschätzung des Modells, du bist nicht beteiligt
- **nicht lesbar** — sie ist für das Modell der nächsten Runde geschrieben, nicht für Menschen
- **nicht änderbar** — sie steckt im Harness, es gibt keine Datei, die du öffnen könntest
- **du weißt nicht, was verloren ging** — du siehst weder, was fehlt, noch kannst du vorher sagen „das da bitte nicht"

Der Handoff holt die Sache zurück in dieselbe Bauart: **noch ein gefrorenes Artefakt**, in derselben Form wie Brief und Ziel — strukturiert, auf der Platte, **du kannst es öffnen, eine Zeile ändern und weiterlaufen lassen**. Und genau so arbeitet dieses Projekt selbst — die `HANDOFF.md` im Repo-Root ist dasselbe Ding, nur von Hand geschrieben.

## Wie man es benutzt (minimaler Code) {#怎么用最小代码}

Auf der Kommandozeile ist der Handoff per Default an:

```bash
flower                       # Handoff ist per Default an
flower --window 200000       # nur nötig, wenn die Schätzung danebenliegt (Default 1 Million)
flower --no-handoff          # aus — zurück zum auto-compact des SDK
```

Im eigenen Code steuert `Runtime(handoff=…)` den Handoff, Default `True`:

```python
from flower import HandoffPolicy, Runtime

# Default: HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# Fenster explizit setzen (der wichtigste Knopf beim Wechsel von Gateway oder Modell)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # aus, zurück zu auto-compact
```

`Runtime.__init__` ist durchgehend keyword-only, `workspace` ist Pflicht. `handoff` nimmt eine `HandoffPolicy`-Instanz oder einen `bool`; ein `bool` ist äquivalent zu `HandoffPolicy(enabled=…)`.

!!! warning "Handoff an = auto-compact wird zwangsweise abgeschaltet"
    `Runtime(handoff=True)` ist der **Default**, und bei jedem Zusammenbau eines Versuchs passiert Folgendes: sobald `handoff.enabled` gilt und `spec.compact is None`, wird die Spec durch
    `CompactPolicy(mode="no_summary")` ersetzt — also **`DISABLE_AUTO_COMPACT=1`** in den Subprozess injiziert.

    Der Grund: laufen beide Mechanismen gleichzeitig, lässt sich bei einem Kontextabfall nicht mehr sagen, wer ihn verursacht hat. Der Preis ist, dass es **kein Sicherheitsnetz** gibt: schlägt die Runde fehl, in der der Handoff geschrieben wird, darf man weder anhalten noch so tun, als wäre nichts, und bis ans harte Limit weiterlaufen — es braucht also einen Degradationspfad (siehe unten).

    Wer auto-compact als Auffangnetz behalten will, muss **explizit** `AgentSpec(compact=CompactPolicy(mode="auto"))` setzen — gibt die Spec selbst etwas vor, wird das respektiert und nicht überschrieben. Achtung: das **gewinnt still** gegen die Annahmen der Handoff-Seite.

## Was es tatsächlich tut {#它实际做了什么}

### Auslöser: zwei Wege in den Handoff {#触发时机两条路进换代}

**Erstens: der Pegel erreicht die Schwelle.** Das Kriterium ist `_handoff_due`: `handoff.enabled` und **nicht in der Runde, in der der Handoff geschrieben wird** und `_ctx >= handoff.at` und dieser Schritt hat bereits eine `session_id` bekommen. `_ctx` ist die Kontextgröße, die der **Hauptthread** in seiner letzten Runde tatsächlich gesehen hat — nur der [Hauptthread](../reference/glossary.md#主线程) zählt, der Kontext eines [subagent](../reference/glossary.md#subagent) ist Sache seiner eigenen transcript, löst sich nach dem Lauf auf und sollte den Hauptthread nicht zum Handoff zwingen.

Bei `warn_at` kommt zunächst eine Annäherungswarnung, einmal pro Generation, ohne Spam.

**Zweitens: die API meldet direkt „passt nicht mehr rein".** Siehe den Abschnitt zu `is_overflow` weiter unten.

Beide Wege sind **nicht durch `max_attempts` begrenzt** und **verbrauchen kein Retry-Kontingent** (intern `attempt -= 1`) — ein Handoff ist kein Fehlschlag.

### Das Handoff-Dokument: fünf Abschnitte, nur zwei davon Pflicht {#交接书五段必填只有两段}

Jeder Abschnitt blockt einen Fehler, den der Nachfolger sonst macht:

| Abschnitt | Feld | Blockt was |
|---|---|---|
| Was gerade läuft | `doing` **Pflicht** | nicht wissen, wo man steht |
| Was schon entschieden ist | `decided` | schon Entschiedenes neu diskutieren (mit **Begründung**) |
| Sackgassen | `deadends` | **der teuerste Abschnitt** — siehe unten |
| Nächster Schritt | `next` **Pflicht** | erst eine halbe Stunde damit verbringen, zu entscheiden, was zu tun ist |
| Schauplatz | `scene` | **Pfade** zu den wichtigen Dateien und Artefakten. Zeiger, nicht Inhalt |

`Handoff.missing()` prüft nur die beiden Abschnitte `REQUIRED = ("doing", "next")`, `complete()` ist die Negation davon.
**Sackgassen zwingend nicht-leer zu fordern, provoziert Erfindungen** — am Anfang einer Aufgabe gehört das Feld schlicht leer.
Und die Entscheidung von `complete()` hat Folgen: fehlt ein Pflichtabschnitt, wird der **gesamte** Handoff durch ein mechanisch zusammengesetztes Degradationsartefakt ersetzt (siehe unten), und das ist deutlich schlechter als ein echter Handoff mit einem fehlenden Abschnitt. Deshalb sind die anderen drei optional — geschrieben nützen sie, ungeschrieben blockieren sie den Handoff nicht.

In `to_markdown()` steht bei leeren Abschnitten `(空)`; der Kopf von `prompt_block()` sagt dem Nachfolger ausdrücklich „du übernimmst", damit er nicht zurückfragt und nach Hintergrund verlangt. Das Feld `step` dient nur der Dokumentüberschrift und geht nicht ins Parsing ein.

#### Warum die Sackgassen am teuersten sind {#走不通的路为什么最贵}

Weil sie das sind, **was der Nachfolger am teuersten neu entdecken muss**, und der Schreibende sie am ehesten weglässt.

Worker haben einen systematischen Optimismus-Bias (der [Goal Guard](goal.md) argumentiert dasselbe): sie schreiben auf, was sie geschafft haben, und vergessen, was sie erfolglos versucht haben. Genau letzteres ist aber das Teure — in [HT002](../cases/ht002.md) wurde eine Stunde um ein Compile-Problem herumgeirrt; wäre das Ergebnis dieser Stunde nicht aufgeschrieben worden, würde der Nachfolger denselben Irrweg noch einmal gehen.

Deshalb widmet `HANDOFF_PROMPT` dieser Sache einen eigenen Absatz — samt dem gemessenen Preis.

### Wie ein echtes Handoff-Dokument aussieht {#长什么样}

```text
# 上下文 130.0K/200K · 还有约 20K 到换代

# 上下文 152.0K/200K —— 写交接准备换代
  - 现在在做  在给 Makefile 加 macOS 垫片头,让 sigemptyset 宏不再展开成语法错误。
  - 已定的事  不改业务源码 —— 用户明确说过边界,所以走 Makefile 生成 shim 这条路。
  - 走不通的  -D_ANSI_SOURCE 会把别的宏一起关掉;改 include 顺序无效。
  - 下一步    在干净 clone 上跑一次 make 验证 shim 成立。
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 152.0K 重新开始
```

**Vollautomatisch, es hält nicht an, um auf dich zu warten** — ein Long-Horizon-Lauf soll nicht blockieren, weil jemand essen gegangen ist.

Das Event ist `Event("handoff")`, `payload["phase"]` hat **drei** Werte: `near` (Annäherung), `writing` (wird geschrieben — das dauert gut zehn Sekunden, ohne dieses Event sähe die Oberfläche aus, als hinge sie) und `done` (Wechsel erfolgt). Der Payload von `done` enthält zusätzlich `context`, `window`, `degraded`, `path`, `sections`.

### Wie die Schwelle berechnet wird {#阈值怎么算}

```python
at      = max(10_000, window - headroom)   # Handoff-Linie, Untergrenze 10k
warn_at = max(1_000, at - 20_000)          # Vorwarnlinie
```

Die 10k-Untergrenze von `at` ist zwingend — darunter lässt sich nicht einmal mehr ein Handoff schreiben.

Die folgende Skala nimmt `--window 200000` als Beispiel, **der Default ist 1 Million**:

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                   Warnung  Handoff     Hartes Limit
```

Wird `window` nicht gesetzt, entscheidet `default_window()` anhand des **Modellnamen-Strings**, und zwar nur über die beiden Umgebungsvariablen `ANTHROPIC_MODEL` oder `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Modellname | wird gewertet als |
|---|---|
| Name enthält `1m` als eigenständiges Wort | `1_000_000` |
| Name enthält `haiku` | `200_000` |
| alles andere **sowie beide Variablen nicht gesetzt** | `1_000_000` |

Auf die Reihenfolge achten: `1m` matcht zuerst, `claude-haiku[1m]` wird also als 1 Million gewertet, nicht als 200 000.

Warum `headroom` bei `50_000` liegt: auto-compact löst bei Fenster −33k aus, der Handoff muss ihm zuvorkommen; und „den Handoff schreiben" kostet selbst noch eine Runde. 50k erfüllt beides gleichzeitig.

**`--window` ist der wichtigste Schalter beim Wechsel von Modell oder Gateway.** Über das SDK ist die Fenstergröße nicht zuverlässig zu erfahren, es bleibt nur Raten anhand des Namens. Ist das echte Fenster größer → Handoff zu früh (Verschwendung, aber kein Fehler); ist es kleiner → zu spät, dann muss nachjustiert werden. Ein Messwert, der das illustriert: das Gateway auf der Entwicklungsmaschine ist auf `claude-opus-5[1m]` konfiguriert. Hätte man früher mit 200 000 gerechnet, gäbe es alle 150 000 eine neue Generation, obwohl tatsächlich bis 950 000 gelaufen werden kann — **Faktor 5 daneben**, Long-Horizon-Arbeit würde in Fetzen zerschnitten.

Mit `flower -v` sieht man vor dem Start die gerade wirksame Credential-Konfiguration (Endpoint, Modellname, Token maskiert bis auf die ersten 4 Stellen).

### `is_overflow`: harten Fehler in einen sofortigen Handoff verwandeln {#is_overflow把硬错变成当场换代}

Das ist die Voraussetzung dafür, dass man sich **traut, als Default von `default_window()` 1 Million zu nehmen**.

Ist das Fenster zu groß geschätzt, wird die Schwelle nie erreicht, und auto-compact ist abgeschaltet — dann knallt es hart gegen die API. `is_overflow(*texts)` erkennt dieses Signal: `prompt is too long`, `context length exceeded`, `maximum context length`, `too many total text bytes`, `input length and max_tokens exceed` und weitere.

Nach dem Erkennen läuft **derselbe Handoff-Pfad**, nur ist der Handoff dieser Generation zwangsläufig degradiert — diese Session schafft keine weitere Runde „Handoff schreiben" mehr, also wird direkt das mechanisch zusammengesetzte Degradationsartefakt genommen, die neue Session übernimmt wie gewohnt, **dieser Schritt schlägt nicht fehl**.

Damit sinkt der Preis einer zu großen Schätzung von „dieser Schritt schlägt fehl" auf „der Handoff dieser Generation ist degradiert".

`is_overflow` ist eine **Funktion auf Modulebene**, keine Methode von `Handoff`, und nimmt variabel viele Argumente.

### Wenn der Handoff nicht geschrieben werden kann: degradieren, nicht anhalten {#交接写不出来时降级不是停下}

Auch die Runde, die den Handoff schreibt, kann fehlschlagen — Netz weg, Modell dreht durch, oder beim Parsen fehlt ein Pflichtabschnitt. Da auto-compact bereits abgeschaltet ist, gibt es **kein Auffangnetz**, und hier stehenzubleiben heißt, gegen das Fenster zu fahren.

Das Vorgehen: aus dem, was bekannt ist, mechanisch einen **unvollständigen Handoff** zusammensetzen, in `doing` die Markierung `[降级:交接没写成]` setzen (Konstante `DEGRADED`), in `scene` die ersten **1200** Zeichen der ursprünglichen Aufgabe stecken und trotzdem wechseln. Der Nachfolger wird ausdrücklich darauf hingewiesen, dass er etwas Unvollständiges bekommt und selbst am Schauplatz nachsehen soll. Gleichzeitig kommt in `StepResult.errors` ein Eintrag „交接降级(…)" dazu, und in `manifest.json` ist der Grund nachlesbar.

Dahinter steht die Funktion auf Modulebene `degraded(step, prompt, *, why="")`; `Handoff.degraded` ist eine read-only Property, die prüft, ob diese Markierung in `doing` steht.

> **Ein unvollständiger Handoff ist weit besser, als gegen das Fenster zu fahren.**

Für die Runde, die den Handoff schreibt, gibt es zwei weitere bewusste Festlegungen: sie läuft mit `max_budget_usd=None` — **der Handoff muss geschrieben werden können und darf nicht am Budget hängenbleiben**; und mit `on_event=None` — diese Runde schreibt nichts in die UI.

### Eine Mine: die Handoff-Runde muss von der Schwelle ausgenommen sein {#一颗地雷写交接那一轮必须豁免阈值}

Der Handoff wird geschrieben, **nachdem** die Linie überschritten wurde — der Pegel liegt zu diesem Zeitpunkt naturgemäß immer noch über der Schwelle. Ohne Ausnahme würde schon die erste Nachricht dieser Runde wieder als „Handoff fällig" gewertet, sie würde also unterbrochen, bevor sie ein einziges Wort geschrieben hat, **jede Generation produziert ein Degradationsartefakt** — und es sieht dabei völlig normal aus (der Degradationspfad funktioniert bestens).

Genau darauf sind wir gemessen hereingefallen: beim ersten echten Lauf von `tests/handoff_live.py` waren **beide Generationen degradierte Handoffs**. Die Offline-Tests haben das nicht gefangen — dort wird `_attempt` komplett ersetzt, das Fake durchläuft dieses Kriterium gar nicht. Inzwischen ist das Kriterium zu `Runtime._handoff_due()` herausgezogen und wird offline direkt geprüft.

### Eine Sperre gegen Weglaufen {#一道防跑飞的闸}

`max_generations=8`.

!!! danger "Ein zu klein konfiguriertes `window` verbrennt Geld in einer Handoff-Endlosschleife"
    Die Gefahr: **liegt die Schwelle unter dem Startboden dieser Rolle** (beim [Koordinator](../reference/glossary.md#协调者) gemessen etwa 34k, allein Systemprompt und [Workbench](../reference/glossary.md#工作台)-Index verbrauchen das), dann überschreitet jede neue Session sie mit dem ersten Wort → Handoff schreiben, wechseln, wieder überschreiten, **endlos**. Und da ein Handoff kein Retry-Kontingent verbraucht — was Absicht ist — ist `max_generations=8` die einzige Sperre.

    Ein normaler Langlauf braucht keine 8 Generationen; wenn es doch dazu kommt, ist fast sicher `window` zu klein konfiguriert — die Fehlermeldung beim Erreichen des Limits sagt genau das („die Schwelle liegt sehr wahrscheinlich unter dem Startboden dieser Rolle, window vergrößern oder `--no-handoff`").

### Der vollständige Ablauf eines Handoffs {#一次换代的完整过程}

```text
Arbeit (session A)
  |  Hauptthread-Kontext überschreitet die Schwelle
  |                     <- Nur der Hauptthread zählt. Der Kontext eines subagent
  |                        ist Sache seiner eigenen transcript, löst sich nach
  |                        dem Lauf auf und darf die Haupt-Session nicht zum
  |                        Handoff zwingen
  |- Abbruch auf einer Nachrichtengrenze
  |                     <- dasselbe Prinzip wie Ctrl-C: sauber trennen, ohne den
  |                        Zustand zu zerreißen (gleicher Preis: fliegende
  |                        subagents gehen verloren. Dafür sind die 50k da)
  |- Dieselbe session laeuft noch eine Runde: Handoff schreiben
  |     Warum sie selbst schreibt — nur sie hat diesen Kontext. Wer sonst
  |     schriebe, muesste erst alles lesen, dann waere nichts gewonnen
  |- Eingefroren nach <Workbench>/notes/交接-<Schrittname>.md,
  |  die Vorgaengergeneration wandert nach notes/archive/交接/
  |- Neue Session (resume=None, fork=False), prompt = prompt_block() des Handoffs
Arbeit (session B) macht weiter
```

`HANDOFF_PROMPT` ist der Prompt, der die aktuelle Session den Handoff schreiben lässt, mit den beiden Platzhaltern `{used}` und `{window}`.
**Es ist keine neue Rolle** — nur diese eine Session hat den Kontext.

### Ein Handoff ist kein Retry — wie wird abgerechnet {#换代不算重试账怎么记}

| Feld | Was beim Handoff passiert |
|---|---|
| `attempts` | **steigt nicht** — es zählt fehlgeschlagene Versuche |
| `retired[]` | die in diesem Schritt verbrannten session_id, **in Reihenfolge** |
| `session_id` | immer **die zuletzt übernehmende**, nicht die verbrannte |
| `context` | Kontextgröße, die der Hauptthread in der letzten Runde tatsächlich gesehen hat |
| `cost_usd` / `num_turns` | **kumulieren** über Retries und Handoffs hinweg |

All diese Felder gehen in `manifest.json`, im Nachhinein lässt sich vollständig rekonstruieren, „wie viele Generationen dieser Schritt verbrannt hat und was jede gekostet hat".

### Wo der Handoff landet {#交接落在哪}

`<Workbench>/notes/交接-<Schrittname ohne unzulässige Zeichen>.md`; eine bereits vorhandene Vorgängergeneration wird nach
`notes/archive/交接/<Schrittname>-<Zeitstempel>.md` verschoben.

**Ohne Workbench wird nichts auf die Platte geschrieben** — dann liefert `_handoff_path` `None`, das Dokument geht trotzdem per Prompt an den Nachfolger, der Handoff läuft wie gewohnt, nur **findet man die Datei hinterher nicht mehr**. Wer sie hinterher lesen können will, muss die Workbench einschalten (`Runtime(workbench=True)`, oder der [Workflow](../reference/glossary.md#流程) hängt sich selbst eine an).

## Wann man es nicht benutzen sollte {#什么时候不该用它}

- **Du willst genau compact.** `flower --no-handoff`, oder `Runtime(handoff=False)`.
  Der Handoff schaltet auto-compact mit ab; wer diesen Nebeneffekt nicht will, lässt ihn aus.
- **Du willst beides gleichzeitig laufen lassen.** Explizites `AgentSpec(compact=CompactPolicy(mode="auto"))` erhält auto-compact, aber danach lässt sich bei einem Kontextabfall nicht mehr sagen, wer ihn verursacht hat, und die Fehlersuche wird schwerer. Entweder dem Handoff trauen oder compact, nicht beidem.
- **Kurze Aufgaben, einzelne Runden.** Der Handoff löst nie aus, ihn zu konfigurieren ist sinnlos — nur daran denken, dass `Runtime` per Default `handoff=True` setzt und damit auto-compact trotzdem abschaltet.
- **Keine Workbench, aber die Erwartung, den Handoff hinterher zu lesen.** Erst die Workbench einschalten, sonst existiert das Dokument nur im Kontext dieses einen Laufs.
- **Langlauf starten, bevor `window` stimmt.** Ist das echte Fenster kleiner als der Default, sind die ersten Generationen durchweg Degradationsartefakte — und genau die sind die nutzloseste Sorte Handoff. Erst mit `--window` einstellen, oder erst einen kurzen Lauf machen und in `-v` den Modellnamen ansehen.
- **Den Handoff für die gesamte Kontextverwaltung halten.** Er ist die letzte Instanz. Die Schichten, die sofort schneiden (Spill, [Trim](../reference/glossary.md#裁剪), [Prune](../reference/glossary.md#剪除)), sind billiger, siehe [Kontextökonomie](context.md).

## Symptomtabelle: an welchem Knopf drehen {#旋钮}

| Symptom | Welcher Knopf |
|---|---|
| Handoff zu häufig, die Arbeit wird ständig unterbrochen | `--window` auf das echte Fenster des Modells setzen (`-v` zeigt den wirksamen Modellnamen) |
| Handoff direkt zu Beginn, mit Meldung „Startboden" | dasselbe, `window` ist zu klein |
| Handoff ist immer degradiert | `errors` in `runs/manifest.json` ansehen, dort steht der Degradationsgrund |
| Der Nachfolger wiederholt ständig Arbeit der Vorgängergeneration | die Sackgassen im Handoff sind zu dünn geschrieben. Die Datei kann direkt geändert werden |
| Handoff soll hinterher gelesen werden, Datei nicht auffindbar | Workbench nicht eingeschaltet. Der Handoff wurde nicht geschrieben, nur per Prompt übergeben |
| Du willst einfach compact | `--no-handoff` |

## Was als Nächstes lesen {#相关}

- [Continuity](continuity.md) — prozessübergreifend an den vorigen Lauf anknüpfen, dieselbe Sache aus der anderen Richtung
- [Kontextökonomie](context.md) — die Schichten, die sofort schneiden
- [Goal Guard](goal.md) — die Argumentation zu „Worker haben einen systematischen Optimismus-Bias"
- [Python API](../reference/api.md) — `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [Kommandozeile](../reference/cli.md) — `--window`, `--no-handoff`
- Quellcode: [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
