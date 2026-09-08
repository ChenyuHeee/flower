# Handoff

Wenn der Kontext fast voll ist, lässt du **die aktuelle Session selbst** ein [Handoff-Dokument](../reference/glossary.md#交接书) schreiben, das ein Mensch lesen und ändern kann, und startest dann eine neue Session, die übernimmt. Kein Compact. Der ganze Vorgang ist im Terminal sichtbar, das Dokument liegt auf der Platte, du kannst es jederzeit ändern — die übernehmende Session liest genau diese Datei.

!!! note "Handoff ist nicht Continuity"
    [Handoff](../reference/glossary.md#换代) bedeutet, **innerhalb desselben Runs** auf eine neue [Session](../reference/glossary.md#会话) zu wechseln;
    [Continuity](../reference/glossary.md#接续) bedeutet, **prozessübergreifend** an den vorigen [Run](../reference/glossary.md#运行) anzuknüpfen,
    siehe [Continuity](continuity.md).

    Beides greift automatisch ineinander, es ist keine zusätzliche Verdrahtung nötig: Die [Lineage](../reference/glossary.md#血缘) hält die **letzte**
    `session_id` dieses Schritts fest, und genau das ist der Nachfolger — der nächste Wake knüpft also am Nachfolger an, nicht an der verbrannten Generation.

## Welches Problem das löst {#解决什么问题}

Das mitgelieferte Auto-Compact des SDK löst bei **Fenster −33k** aus (gemessen: bei Fenster `200000` liegt die Schwelle bei `167000`;
der Compact-Algorithmus selbst steckt in der Harness-Binary, er lässt sich nicht ändern, änderbar ist nur, ob er auslöst), und was es tut, ist: **die Historie zu einem Absatz zusammenfassen**.
Das steht quer zum Rest dieses Frameworks:

| | Wann entschieden wird | Was bleibt |
|---|---|---|
| `spill_guard` | In dem Moment, in dem das Tool zurückkehrt | Großes Ergebnis wird [gespillt](../reference/glossary.md#落盘), im Kontext bleibt eine Zeile mit dem Pfad |
| Eingefrorene Artefakte (Brief / Ziel) | Am Ende dieses Schritts | Ein Dokument, der nächste Schritt liest nur dieses |
| **auto-compact** | **Erst wenn der Kontext voll ist, wird zurückgeblickt** | **Eine vom Modell selbst geschriebene Zusammenfassung** |

Was flower von Anfang bis Ende tut, ist **an Ort und Stelle zu entscheiden, was bleiben soll**. [Compact](../reference/glossary.md#压缩) ist die einzige Stelle mit „nachträglicher Reparatur",
und sein Produkt hat vier Mängel:

- **Vom Modell generiert** — was in der Zusammenfassung steht, entscheidet das Modell im Moment nach eigenem Ermessen, du bist nicht beteiligt
- **Nicht lesbar** — sie ist für das Modell der nächsten Runde geschrieben, nicht für Menschen
- **Nicht änderbar** — sie steckt in der Harness, es gibt keine Datei, die du öffnen könntest
- **Du weißt nicht, was verloren ging** — du siehst weder, was weggefallen ist, noch kannst du vorher sagen „das bitte nicht"

Der Handoff holt die Sache zurück in dieselbe Methodik: **noch ein eingefrorenes Artefakt**, in derselben Form wie Brief und Ziel —
strukturiert, auf Platte geschrieben, **du kannst es öffnen, eine Zeile ändern und es weiterlaufen lassen**. Und genau so macht es dieses Projekt selbst —
die `HANDOFF.md` im Repo-Root ist dasselbe, nur von Hand geschrieben.

## Verwendung (minimaler Code) {#怎么用最小代码}

Die Kommandozeile bringt den Handoff standardmäßig mit:

```bash
flower                       # Handoff ist standardmäßig an
flower --window 200000       # nur nötig, wenn falsch geraten wurde (Standard: 1 Million)
flower --no-handoff          # aus — zurück zum mitgelieferten Auto-Compact des SDK
```

Im eigenen Code steuert `Runtime(handoff=…)` den Handoff, Standard ist `True`:

```python
from flower import HandoffPolicy, Runtime

# Standard: HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
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

`Runtime.__init__` ist durchgehend keyword-only, `workspace` ist Pflicht. `handoff` nimmt eine `HandoffPolicy`-Instanz oder
einen `bool`; ein `bool` entspricht `HandoffPolicy(enabled=…)`.

!!! warning "Handoff an = Auto-Compact wird zwangsweise abgeschaltet"
    `Runtime(handoff=True)` ist der **Standardwert**, und er tut beim Zusammenbau jedes Versuchs Folgendes: Sobald
    `handoff.enabled` gilt und `spec.compact is None` ist, wird die Spec durch
    `CompactPolicy(mode="no_summary")` ersetzt — also **`DISABLE_AUTO_COMPACT=1`** in den Subprozess injiziert.

    Der Grund: Laufen beide Mechanismen gleichzeitig, lässt sich nicht mehr sagen, wer für einen Rückgang des Kontexts verantwortlich war.
    Der Preis ist, dass es **kein Sicherheitsnetz** gibt: Scheitert die Runde, die den Handoff schreibt, darf man nicht anhalten
    und auch nicht so tun, als sei nichts, und bis zum harten Limit durchhalten — deshalb braucht es einen Degradationspfad (siehe unten).

    Wer Auto-Compact als Auffangnetz behalten will, muss **explizit** `AgentSpec(compact=CompactPolicy(mode="auto"))` angeben —
    gibt die Spec selbst etwas vor, wird das respektiert und nicht überschrieben. Beachte: Das **gewinnt still** gegen die Annahmen der Handoff-Seite.

## Was es tatsächlich tut {#它实际做了什么}

### Auslösezeitpunkt: zwei Wege in den Handoff {#触发时机两条路进换代}

**Erstens: Der Pegel erreicht die Schwelle.** Das Kriterium ist `_handoff_due`: `handoff.enabled`, **nicht in der Runde, die den Handoff schreibt**,
`_ctx >= handoff.at`, und dieser Schritt hat bereits eine `session_id` erhalten. `_ctx` ist die Kontextgröße, die die letzte Runde des
**Main Thread** tatsächlich gesehen hat — es zählt nur der [Main Thread](../reference/glossary.md#主线程); der Kontext eines
[subagent](../reference/glossary.md#subagent) ist Sache seines eigenen Transcripts, er löst sich nach dem Lauf auf und sollte den Main Thread nicht zum Handoff zwingen.

Bei `warn_at` wird zunächst eine Annäherungswarnung gesendet, einmal pro Generation, damit der Bildschirm nicht zugespammt wird.

**Zweitens: Die API meldet direkt „passt nicht mehr rein".** Siehe den Abschnitt zu `is_overflow` weiter unten.

Beide Wege sind **nicht durch `max_attempts` begrenzt** und **verbrauchen kein Retry-Kontingent** (intern `attempt -= 1`) —
ein Handoff ist kein Fehlschlag.

### Das Handoff-Dokument: fünf Abschnitte, nur zwei sind Pflicht {#交接书五段必填只有两段}

Jeder Abschnitt verhindert einen typischen Fehler dessen, der übernimmt:

| Abschnitt | Feld | Was er verhindert |
|---|---|---|
| Was gerade getan wird | `doing` **Pflicht** | Nicht zu wissen, wo man steht |
| Bereits Entschiedenes | `decided` | Schon Entschiedenes erneut diskutieren (mit **Warum**) |
| Sackgassen | `deadends` | **Der teuerste Abschnitt** — siehe unten |
| Nächster Schritt | `next` **Pflicht** | Erst eine halbe Stunde damit zu verbringen, zu entscheiden, was zu tun ist |
| Schauplatz | `scene` | **Pfade** zu wichtigen Dateien und Artefakten. Zeiger, kein Inhalt |

`Handoff.missing()` prüft nur die beiden Abschnitte `REQUIRED = ("doing", "next")`, `complete()` ist die Negation davon.
**Sackgassen zwingend nicht-leer zu fordern, provoziert Erfindungen** — am Anfang einer Aufgabe gehört der Abschnitt schlicht leer.
Und die Entscheidung von `complete()` hat Folgen: Fehlt ein Pflichtabschnitt, wird dieses Handoff-Dokument **komplett durch ein mechanisch zusammengesetztes Degradationsartefakt ersetzt**
(siehe unten), und das ist weit schlechter als ein echtes Handoff-Dokument, in dem ein Abschnitt fehlt. Deshalb sind die anderen drei optional — geschrieben nützen sie, ungeschrieben blockieren sie den Handoff nicht.

In `to_markdown()` wird für leere Abschnitte `(空)` geschrieben; der Kopf von `prompt_block()` sagt dem Übernehmer ausdrücklich „du übernimmst",
damit er nicht zurückfragt und Hintergrund einfordert. Das Feld `step` dient nur dem Dokumentkopf und geht nicht ins Parsing ein.

#### Warum „Sackgassen" der teuerste Abschnitt ist {#走不通的路为什么最贵}

Weil es das ist, dessen Wiederentdeckung den Übernehmer **am meisten kostet**, und weil der Schreibende es am leichtesten auslässt.

Der Worker hat einen systematischen Optimismus-Bias (der [Goal Guard](goal.md) argumentiert dasselbe): Er schreibt auf, was er geschafft hat,
und vergisst aufzuschreiben, was er ohne Erfolg versucht hat. Doch Letzteres ist das wirklich Teure — in [HT002](../cases/ht002.md) wurde eine Stunde lang um ein Compile-Problem herumgeirrt;
wäre das Ergebnis dieser Stunde nicht aufgeschrieben worden, würde der Übernehmer denselben Umweg noch einmal genau so gehen.

Deshalb greift `HANDOFF_PROMPT` diesen Punkt in einem eigenen Absatz auf und nennt sogar diesen gemessenen Preis.

### Wie das aussieht {#长什么样}

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

**Vollautomatisch, es hält nicht an, um auf dich zu warten** — ein Long-Horizon-Run sollte nicht blockieren, weil jemand essen gegangen ist.

Das Event ist `Event("handoff")`, `payload["phase"]` hat **drei** Werte: `near` (Annäherung), `writing` (wird geschrieben —
das Schreiben dauert gut zehn Sekunden, ohne dieses Event sähe die Oberfläche wie eingefroren aus) und `done` (Wechsel erledigt). Das Payload von `done` enthält zusätzlich
`context`, `window`, `degraded`, `path` und `sections`.

### Wie die Schwelle berechnet wird {#阈值怎么算}

```python
at      = max(10_000, window - headroom)   # Handoff-Linie, Untergrenze 10k
warn_at = max(1_000, at - 20_000)          # Linie für die Annäherungswarnung
```

Die Untergrenze von 10k für `at` ist notwendig — darunter lässt sich nicht einmal mehr das Handoff-Dokument schreiben.

Die folgende Skala nimmt `--window 200000` als Beispiel, **das Standardfenster ist 1 Million**:

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                     Warnung Handoff  Limit
```

Wird `window` nicht angegeben, entscheidet `default_window()` anhand des **Modellnamens als String** und schaut nur auf die beiden Umgebungsvariablen
`ANTHROPIC_MODEL` und `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Modellname | Erkannt als |
|---|---|
| Name enthält `1m` als eigenständiges Wort | `1_000_000` |
| Name enthält `haiku` | `200_000` |
| Alles andere, **sowie wenn beide Variablen nicht gesetzt sind** | `1_000_000` |

Reihenfolge beachten: `1m` matcht zuerst, deshalb wird `claude-haiku[1m]` als 1 Million erkannt, nicht als 200.000.

Warum `headroom` bei `50_000` liegt: Auto-Compact löst bei Fenster −33k aus, der Handoff muss ihm zuvorkommen;
und „das Handoff-Dokument schreiben" kostet selbst noch eine Runde. 50k erfüllt beides gleichzeitig.

**`--window` ist der Schalter, den man beim Wechsel von Modell oder Gateway zuerst anfassen sollte.** Auf der SDK-Seite ist die Fenstergröße nicht zuverlässig abrufbar, es bleibt nur, sie am Namen zu raten.
Ist das echte Fenster größer → der Handoff kommt zu früh (Verschwendung, kein Fehler); ist es kleiner → er kommt zu spät und muss angepasst werden. Ein gemessener Wert dazu:
Das Gateway auf der Entwicklungsmaschine ist auf `claude-opus-5[1m]` konfiguriert. Rechnete man wie früher mit 200.000, würde alle 150.000 eine Generation gewechselt,
obwohl sie tatsächlich bis 950.000 laufen kann — **Faktor 5**; Long-Horizon-Arbeit wird dadurch in Fetzen zerschnitten.

Mit `flower -v` siehst du vor dem Start die aktuell wirksame Credential-Konfiguration (Endpoint, Modellname; der Token ist maskiert, nur die ersten 4 Stellen bleiben stehen).

### `is_overflow`: harte Fehler in einen sofortigen Handoff verwandeln {#is_overflow把硬错变成当场换代}

Das ist die Voraussetzung dafür, dass man **den Standardwert von `default_window()` überhaupt auf 1 Million setzen darf**.

Wird das Fenster zu groß geschätzt, ist die Schwelle nie erreichbar, und Auto-Compact ist abgeschaltet — dann knallt es hart gegen die API.
`is_overflow(*texts)` erkennt dieses Signal: `prompt is too long`, `context length exceeded`,
`maximum context length`, `too many total text bytes`, `input length and max_tokens exceed` und so weiter.

Nach der Erkennung wird **derselbe Handoff-Pfad** gegangen, nur ist das Handoff-Dokument dieser Generation zwangsläufig degradiert — jene Session schafft
„noch eine Runde Handoff schreiben" nicht mehr, also wird direkt das mechanisch zusammengesetzte Degradationsartefakt genommen, wie üblich auf eine neue Session gewechselt und weitergearbeitet: **dieser Schritt scheitert nicht**.

Damit sinkt der Preis einer Überschätzung von „dieser Schritt scheitert" auf „das Handoff-Dokument dieser Generation ist degradiert".

`is_overflow` ist eine **Funktion auf Modulebene**, keine Methode von `Handoff`, und nimmt variabel viele Argumente.

### Wenn sich das Handoff-Dokument nicht schreiben lässt: degradieren, nicht anhalten {#交接写不出来时降级不是停下}

Auch die Runde, die den Handoff schreibt, kann scheitern — Netz weg, Modell dreht durch, oder beim Parsen fehlt ein Pflichtabschnitt. Weil
Auto-Compact bereits abgeschaltet ist, gibt es **kein Auffangnetz**; hier anzuhalten hieße, gegen das Fenster zu knallen.

Das Vorgehen: Aus dem bereits Bekannten wird mechanisch ein **unvollständiges Handoff-Dokument** zusammengesetzt, in `doing` wird `[降级:交接没写成]` vermerkt
(Konstante `DEGRADED`), in `scene` kommen die ersten **1200** Zeichen der ursprünglichen Aufgabe, und der Handoff läuft trotzdem. Dem Übernehmer wird ausdrücklich gesagt,
dass das, was er bekommt, unvollständig ist und er sich den Schauplatz selbst ansehen soll. Gleichzeitig kommt in `StepResult.errors` ein Eintrag „Handoff degradiert (…)" dazu,
und in `manifest.json` ist der Grund nachlesbar.

Dazu gehört die Funktion auf Modulebene `degraded(step, prompt, *, why="")`; `Handoff.degraded` ist eine Read-only-Property,
die prüft, ob in `doing` diese Markierung steht.

> **Ein unvollständiges Handoff-Dokument ist weit besser, als gegen das Fenster zu knallen.**

Die Runde, die den Handoff schreibt, hat noch zwei bewusste Besonderheiten: Sie läuft mit `max_budget_usd=None` — **das Handoff-Dokument muss geschrieben werden können
und darf nicht am Budget hängen bleiben**; und `on_event=None` — diese Runde geht nicht ans UI.

### Eine Tretmine: Die Runde, die den Handoff schreibt, muss von der Schwelle ausgenommen sein {#一颗地雷写交接那一轮必须豁免阈值}

Das Handoff-Dokument wird **nach dem Überschreiten der Linie** geschrieben — der Pegel liegt zu diesem Zeitpunkt naturgemäß noch über der Schwelle. Ohne Ausnahme würde
die erste Nachricht dieser Runde erneut als „Handoff fällig" gewertet, sie würde also abgebrochen, bevor sie ein einziges Wort geschrieben hat, **jede Generation produzierte ein Degradationsartefakt**,
und es sähe dabei alles normal aus (der Degradationspfad funktioniert nämlich gut).

Genau darauf sind wir gemessen hereingefallen: Beim ersten echten Lauf von `tests/handoff_live.py` waren **beide Generationen von Handoff-Dokumenten degradiert**. Die Offline-Tests haben es nicht gefangen —
dort wurde `_attempt` komplett ersetzt, die Attrappe hat dieses Kriterium nie ausgeführt. Inzwischen ist das Kriterium nach `Runtime._handoff_due()` hochgezogen,
offline wird es direkt geprüft.

### Eine Bremse gegen Weglaufen {#一道防跑飞的闸}

`max_generations=8`.

!!! danger "Ein zu klein konfiguriertes `window` führt zu endlosem Handoff und verbrennt Geld"
    Die Gefahr: Liegt **die Schwelle unter dem Startboden dieser Rolle** (beim [Koordinator](../reference/glossary.md#协调者) gemessen etwa 34k,
    allein System-Prompt plus [Workbench](../reference/glossary.md#工作台)-Index fressen das auf), dann überschreitet jede neue Session sie schon mit dem ersten Wort
    → Handoff schreiben, Generation wechseln, wieder überschreiten, **endlos**. Und da der Handoff kein Retry-Kontingent verbraucht — was Absicht ist —, ist die einzige Bremse
    `max_generations=8`.

    Ein normaler langer Lauf braucht keine 8 Generationen; wenn du wirklich dagegen läufst, ist fast sicher `window` zu klein konfiguriert — beim Erreichen des Limits sagt die Fehlermeldung genau das
    („die Schwelle liegt sehr wahrscheinlich unter dem Startboden dieser Rolle, erhöhe window oder nutze `--no-handoff`").

### Der vollständige Ablauf eines Handoffs {#一次换代的完整过程}

```text
Arbeit (session A)
  |  Kontext des Main Thread überschreitet die Schwelle   <- nur der Main Thread zählt. Der Kontext eines
  |                            subagent ist Sache seines eigenen Transcripts, er löst sich nach dem Lauf
  |                            auf und darf die Hauptsession nicht zum Handoff zwingen
  |- Abbruch an einer Message-Grenze  <- dasselbe Prinzip wie ein Ctrl-C-Abbruch: sauber trennen,
  |                            den Zustand nicht zerreißen (gleicher Preis: fliegende subagents gehen
  |                            verloren. Dafür sind die 50k Headroom da)
  |- dieselbe session läuft noch eine Runde: Handoff schreiben
  |     warum sie selbst schreibt — nur sie hat diesen Kontext. Wer sonst schriebe, müsste ihn erst
  |     lesen, dann wäre nichts gewonnen
  |- eingefroren nach <Workbench>/notes/交接-<Schrittname>.md, die Vorgängergeneration wandert
  |  nach notes/archive/交接/
  |- neue Session (resume=None, fork=False), prompt = prompt_block() des Handoff-Dokuments
Arbeit (session B) macht weiter
```

`HANDOFF_PROMPT` ist der Prompt, mit dem die aktuelle Session ihr Handoff-Dokument schreibt; er enthält die beiden Platzhalter `{used}` und `{window}`.
**Es ist keine neue Rolle** — nur diese eine Session hat diesen Kontext.

### Handoff zählt nicht als Retry — wie abgerechnet wird {#换代不算重试账怎么记}

| Feld | Wie es sich beim Handoff verändert |
|---|---|
| `attempts` | **Steigt nicht** — es zählt gescheiterte Versuche |
| `retired[]` | Die in diesem Schritt verbrannten session_id **in Reihenfolge** |
| `session_id` | Immer **die zuletzt übernehmende**, nicht die verbrannte |
| `context` | Die Kontextgröße, die der Main Thread in der letzten Runde tatsächlich gesehen hat |
| `cost_usd` / `num_turns` | Werden über Retries und Handoffs hinweg **aufsummiert** |

Diese Felder gehen alle ins `manifest.json`, so lässt sich im Nachhinein vollständig rekonstruieren, „wie viele Generationen dieser Schritt verbrannt hat und was jede gekostet hat".

### Wo das Handoff-Dokument landet {#交接落在哪}

`<Workbench>/notes/交接-<Schrittname ohne unzulässige Zeichen>.md`; eine bereits vorhandene Vorgängergeneration wandert nach
`notes/archive/交接/<Schrittname>-<Zeitstempel>.md`.

**Ohne Workbench wird nichts auf Platte geschrieben** — dann gibt `_handoff_path` `None` zurück, das Dokument wird trotzdem per Prompt an den Übernehmer gegeben,
der Handoff läuft normal, nur **findet man die Datei hinterher nicht**. Wer sie hinterher lesen können will, muss die Workbench einschalten
(`Runtime(workbench=True)`, oder der [Workflow](../reference/glossary.md#流程) hängt selbst eine ein).

## Wann man es nicht verwenden sollte {#什么时候不该用它}

- **Du willst genau Compact.** `flower --no-handoff`, oder `Runtime(handoff=False)`.
  Der Handoff schaltet Auto-Compact als Nebenwirkung ab; wer diese Nebenwirkung nicht will, schaltet ihn nicht ein.
- **Du willst beides gleichzeitig.** Explizit `AgentSpec(compact=CompactPolicy(mode="auto"))` erhält Auto-Compact,
  aber danach lässt sich nicht mehr sagen, wer einen Rückgang des Kontexts verursacht hat, und die Fehlersuche wird schwerer. Entweder du vertraust dem Handoff oder dem Compact, nicht beidem.
- **Kurze Aufgaben, Ein-Runden-Arbeit.** Der Handoff löst nie aus, ihn zu konfigurieren ist sinnlos — aber denk daran, dass `Runtime` mit dem Standard
  `handoff=True` Auto-Compact trotzdem abschaltet.
- **Keine Workbench, aber die Erwartung, das Handoff-Dokument später zu lesen.** Schalte erst die Workbench ein, sonst existiert das Dokument nur im Kontext dieses einen Runs.
- **Langer Lauf, bevor `window` richtig gesetzt ist.** Ist das echte Fenster kleiner als der Standardwert, sind die ersten Generationen durchweg Degradationsartefakte,
  und gerade die sind die nutzloseste Sorte Handoff-Dokument. Setze erst `--window` passend, oder lass einen kurzen Lauf durch und sieh dir den Modellnamen in `-v` an.
- **Den Handoff als gesamte Kontextverwaltung zu nehmen.** Er ist die letzte Instanz. Die Schichten, die sofort schneiden
  (Spill, [Trim](../reference/glossary.md#裁剪), [Prune](../reference/glossary.md#剪除)), sind billiger,
  siehe [Kontextökonomie](context.md).

## Stellschrauben {#旋钮}

| Symptom | Woran drehen |
|---|---|
| Handoff zu häufig, die Arbeit wird ständig unterbrochen | `--window` auf das echte Fenster des Modells setzen (`-v` zeigt den wirksamen Modellnamen) |
| Schon zu Beginn ein Handoff, dazu die Meldung „Startboden" | Dasselbe, `window` ist zu klein konfiguriert |
| Das Handoff-Dokument ist immer degradiert | Sieh in `errors` in `runs/manifest.json`, dort steht der Grund der Degradation |
| Der Übernehmer wiederholt ständig Arbeit der Vorgängergeneration | Die „Sackgassen" im Handoff-Dokument sind zu dünn geschrieben. Du kannst die Datei direkt ändern |
| Du willst das Handoff-Dokument hinterher lesen, findest aber keine Datei | Keine Workbench eingeschaltet. Das Dokument landet nicht auf Platte, es ging nur durch den Prompt |
| Du willst einfach Compact | `--no-handoff` |

## Verwandt {#相关}

- [Continuity](continuity.md) — prozessübergreifend an den vorigen Run anknüpfen; dieselbe Sache aus der anderen Richtung
- [Kontextökonomie](context.md) — die Schichten, die sofort schneiden
- [Goal Guard](goal.md) — die Argumentation zu „der Worker hat einen systematischen Optimismus-Bias"
- [Python API](../reference/api.md) — `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [Kommandozeile](../reference/cli.md) — `--window`, `--no-handoff`
- Quellcode: [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
