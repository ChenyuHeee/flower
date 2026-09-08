# Python API

Diese Seite arbeitet die **62 öffentlichen Symbole** von `flower`s Top-Level-`__all__` erschöpfend durch: Signaturen, Parameter, Defaults, Semantik,
öffentliche Attribute und Methoden. Nach dem Lesen musst du für Parameter nicht mehr in den Quellcode schauen.

Gegliedert ist sie nach **dem, was dich interessiert**, nicht nach Moduldateien — willst du wissen, "wie halte ich den [Coordinator](glossary.md#协调者)
davon ab, selbst Hand anzulegen", geh zur [Hook-Schicht](#hook); willst du wissen, "wie kommt das Ergebnis des vorigen Schritts in den nächsten", geh zum [Workflow](#流程).
Terminologie durchgehend nach dem [Glossar](glossary.md).

Version `0.1.0`, Abhängigkeit `claude-agent-sdk>=0.2.152`. Alle Signaturen entsprechen wörtlich dem Quellcode.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## Was auf dieser Seite steht {#索引}

| Worum es geht | Symbole |
|---|---|
| [Einen Agent laufen lassen](#运行时) | `Runtime` `StepResult` |
| [Mehrere Schritte verketten](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Eine Rolle bauen](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Agent-Definitionen von Hand schreiben](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Strukturierte Dokumente](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Tools abfangen, Ergebnisse trimmen, Isolation trennen](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [Das Arbeitsverzeichnis fürs Spilling](#工作台) | `Workbench` |
| [Wie und was Sessions speichern](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [Was tun bei Netzausfall](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Das UI austauschen](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Prozessübergreifend anknüpfen](#血缘) | `Lineage` |

## Sechs Defaults, die beißen {#危险默认值}

Diese sechs Punkte sind kein Randmaterial, sondern die sechs häufigsten Unfälle. Jeder ist im zugehörigen Abschnitt vollständig erklärt.

| Default | Folge | Details |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | `Bash`/`Write`/`Edit` im Main Thread haben **keinen einzigen Hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Erzwingt `CompactPolicy(mode="no_summary")` auf der Spec, also `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | Schritte mit `resume_from=None` knüpfen trotzdem prozessübergreifend an die letzte Session an | [Workflow](#workflow) |
| `build_options(fork=True)` ohne `resume` | Wirkungslos, ohne Fehlermeldung | [build_options](#build-options) |
| `clarify(max_turns=<kleine Zahl>)` | Macht "unbegrenzt nachfragen" zur leeren Behauptung — jede Rückfrage ist eine Runde | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | Gilt sessionweit, sperrt Subagents gleich mit aus | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Quellcode: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` ist der Ausführungskern. Er hält Workspace, [Session Store](glossary.md#会话存储), [Workbench](glossary.md#工作台),
[Resilience](glossary.md#韧性)-Strategie und [Handoff](glossary.md#换代)-Strategie und hat nach außen nur ein Verb: einen Schritt `run`.
Retry, Weiterlaufen nach einer Unterbrechung, Handoff bei vollem Kontext — alles passiert innerhalb dieses einen Aufrufs.

### `Runtime` {#runtime}

```python
Runtime(
    *,
    workspace: str | Path,
    run_dir: str | Path = "runs",
    portable: bool = True,
    trim: TrimPolicy | bool = False,
    ephemeral: EphemeralPolicy | bool = True,
    keep_denials: int = 1,
    workbench: Workbench | bool = False,
    spill_threshold: int | None = 4000,
    resilience: Resilience | bool = True,
    handoff: HandoffPolicy | bool = True,
)
```

Die Konstruktorparameter sind **allesamt keyword-only** (`*` ganz vorne), `workspace` ist Pflicht.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workspace` | `str \| Path` | Pflicht | Das `cwd` des Agents. Wird beim Konstruieren resolved und `mkdir(parents=True, exist_ok=True)`. Der `project_key` des SDK wird daraus abgeleitet — wird das Verzeichnis wegkopiert, ist die alte `session_id` nicht mehr auffindbar |
| `run_dir` | `str \| Path` | `"runs"` | Enthält `sessions.db`, `manifest.json`, `lineage.json` sowie die Default-Workbench bei `workbench=True`. Wird ebenfalls resolved und angelegt |
| `portable` | `bool` | `True` | Wird an `build_options(portable=)` durchgereicht, also `setting_sources=[]`: liest weder das `~/.claude/` des Hosts noch das `.claude/` des Projekts. Siehe [portabel](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Eine Instanz wird direkt verwendet; bei `bool` wird `TrimPolicy(enabled=bool(trim))` gebaut. **Ausschalten heißt nur, dass große Ergebnisse nicht getrimmt werden — geprunt wird trotzdem** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Gleiche Umwandlungsregel. Gehört mit `coordinator(glance=True)` zusammen — wer den Main Thread `git status` laufen lässt, muss dafür sorgen, dass dieses Ergebnis verfällt |
| `keep_denials` | `int` | `1` | Geht an `PrunePolicy(keep_denials=)`. Behält die letzten N abgelehnten Tool-Aufrufe, ältere werden samt Aufruf und Ergebnis entfernt |
| `workbench` | `Workbench \| bool` | `False` | Eine Instanz wird direkt verwendet; bei `True` wird `Workbench(workspace, home=run_dir / "workbench")` gebaut (**liegt per Default außerhalb des Workspace**). Danach sofort `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | Ab wie vielen Zeichen ein Tool-Ergebnis [gespillt](glossary.md#落盘) wird. `None` oder `0` = kein `spill_guard` |
| `resilience` | `Resilience \| bool` | `True` | Gleiche Umwandlungsregel |
| `handoff` | `HandoffPolicy \| bool` | `True` | Gleiche Umwandlungsregel |

**Der Session Store ist fest verdrahtet**: immer
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Die Konstruktorparameter bieten **keinen** Einstiegspunkt zum Wechseln des Backends — wer wechseln will, baut sich selbst `AgentSpec` + `build_options(session_store=...)`
oder überschreibt nach dem Konstruieren `rt.store`.

Die letzten beiden Schritte des Konstruktors sind `load_dotenv()` und `check_credentials()`, **letzteres wirft bei Fehler `RuntimeError`**.
Ohne Credentials fliegt es also schon beim Konstruieren, nicht erst bei `run()`.

!!! warning "`workbench=False` + `coordinator()` = keine einzige Mauer im Main Thread"
    `delegate_guard` wird nur in `workbench_hooks` installiert, und `workbench_hooks` wird nur aufgerufen, wenn `self.workbench is not None`;
    `whitelist_guard` wiederum wird durch `if not spec.delegate_only` übersprungen. Und `coordinator()` setzt konstant
    `delegate_only=True` und gibt per Default `glance=True` für `Bash`.

    **Fazit: Kombiniert man den Coordinator mit `Runtime(workbench=False)`, fängt kein einziger Hook seine `Bash`/`Write`/`Edit` ab.**
    Wer `coordinator()` benutzt, schaltet die `workbench` ein — `Runtime(..., workbench=True)` oder eine
    `Workbench`-Instanz übergeben.

!!! warning "`handoff=True` (Default) schaltet Auto-Compact zwangsweise ab"
    In `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`,
    im Subprozess also `DISABLE_AUTO_COMPACT=1`. Der Grund: Laufen beide Mechanismen gleichzeitig, lässt sich nicht mehr sagen, wer den Kontextabfall verursacht hat.

    **Der Preis: Der Schritt, der das Handoff-Dokument schreibt, braucht zwingend einen Degradationspfad** (`handoff.degraded`), weil kein Compact mehr auffängt.
    Wer Auto-Compact behalten will, setzt `AgentSpec.compact` explizit (gibt die Spec selbst etwas an, wird das respektiert und nicht überschrieben).

#### Öffentliche Attribute {#runtime-属性}

| Attribut | Typ | Beschreibung |
|---|---|---|
| `workspace` | `Path` | Der resolvte Workspace |
| `run_dir` | `Path` | Das resolvte Run-Verzeichnis |
| `portable` | `bool` | Unverändert gespeichert |
| `store` | `PruningSessionStore` | Der Session Store. Ein Backend-Wechsel geht nur durch Überschreiben nach dem Konstruieren |
| `resilience` | `Resilience` | Die normalisierte Instanz |
| `handoff` | `HandoffPolicy` | Die normalisierte Instanz |
| `workbench` | `Workbench \| None` | Bei `workbench=False` gleich `None` |
| `spill_threshold` | `int \| None` | Unverändert gespeichert, in `_attempt` an `workbench_hooks` durchgereicht |
| `results` | `list[StepResult]` | Jeder in diesem Prozess gelaufene Schritt, in Reihenfolge angehängt |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Muss pro Instanz eindeutig sein** — `manifest.json` dedupliziert nach dem Feld `run`, bei kollidierenden IDs hält der später Schreibende die Zeilen des anderen für seine eigenen vom letzten Mal und löscht sie |
| `on_session` | `Callable[[str], None] \| None` | Callback **sofort** beim Erhalt einer neuen `session_id`, Default `None`. **Sollte nur die eine Zeile `runtime.run` umschließen** — der [Judge](glossary.md#判定者) benutzt dasselbe `Runtime`, hängt der Callback während des Gates noch dran, landet die Session des Judge in der [Lineage](glossary.md#血缘) des arbeitenden Schritts |

Klassenkonstanten: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`,
`INTERRUPT_NOTE` (ein Absatz, der beim Weiterlaufen nach einer Unterbrechung an die Worte des Menschen angehängt wird und erklärt, dass "ein damals fliegender Tool-Aufruf, der interrupted zurückgibt, eine normale Nebenwirkung der Unterbrechung ist, kein Umgebungsfehler").

#### Öffentliche Methoden {#runtime-方法}

| Methode | Signatur | Beschreibung |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Einen Schritt laufen lassen. Siehe unten |
| `interrupt` | `(message: str = "") -> None` | Fordert die Unterbrechung der aktuellen Runde an. **Aus jedem Thread aufrufbar**. Kooperativ: bricht sauber an einer **Nachrichtengrenze** ab, kein hartes Abwürgen. Leerer String = nur unterbrechen, nichts sagen |
| `rescue` | `() -> None` | Schreibt vor dem harten Abschuss möglichst alle Buchungen weg, aufgerufen vom `SIGHUP`/`SIGTERM`-Handler. Auch der fliegende Schritt landet im Manifest, mit `error="killed-by-signal"`. Macht nur kleine synchrone Schreibvorgänge |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | In `str(workspace.resolve())` werden `/`, `_` und `.` allesamt durch `-` ersetzt. **Das SDK leitet es aus dem cwd ab, der Aufrufer kann es nicht vorgeben** |
| `has_session` | `(session_id: str) -> bool` | Ist diese ID unter **diesem Workspace** noch auffindbar? Synchron, liest kein Payload |
| `context_of` | `(session_id: str) -> int` | Die Kontextgröße der letzten Runde einer Session, delegiert an `store.last_context` |
| `total_cost` | `() -> float` | `round(sum(r.cost_usd for r in self.results), 4)` |
| `close` | `() -> None` | `self.store.close()` |

#### `Runtime.run(...)` {#runtime-run}

```python
async def run(
    self,
    spec: AgentSpec,
    prompt: str,
    *,
    step_name: str | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> StepResult
```

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `spec` | `AgentSpec` | Pflicht, positional | Die Deklaration des laufenden Agents |
| `prompt` | `str` | Pflicht, positional | Was in dieser Runde gesagt wird |
| `step_name` | `str \| None` | `None` | Der Schlüssel in `StepResult.step`, im Manifest und in der Lineage. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Diese `session_id` fortsetzen |
| `fork` | `bool` | `False` | Eine neue Session abzweigen, ohne die ursprüngliche zu verschmutzen. **Wirkt nur, wenn `resume` gesetzt ist** |
| `resume_at` | `str \| None` | `None` | Ab einer bestimmten Nachricht fortsetzen (Rollback). Ebenfalls **nur wirksam, wenn `resume` gesetzt ist** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Der Event-Ausgang, siehe [`Event`](#event) |

Zu Beginn jedes Schritts wird der Kontextpegel auf null gesetzt (`self._ctx, self._warned = 0, False`). Danach folgt eine Schleife mit vier Ausgängen:

1. **Erfolg** → raus.
2. **Mensch unterbricht** (`result.error == INTERRUPTED`) → **nicht durch `max_attempts` begrenzt**, wartet nicht aufs Netz.
   Mit den Worten des Menschen wird dieselbe Session `resume`t, `attempt -= 1` (eine Unterbrechung zählt nicht als fehlgeschlagener Versuch), Prompt = Worte des Menschen + `INTERRUPT_NOTE`.
   **Ohne `session_id` bleibt nur anhalten.**
3. **Kontext voll** (`result.error == HANDOFF_DUE`, oder `handoff.enabled` und eine `session_id` liegt vor und
   `is_overflow(...)` greift) → **ebenfalls nicht durch `max_attempts` begrenzt**. Zuerst wird `len(result.retired) >= handoff.max_generations` geprüft,
   bei Überschreitung wird der Fehler durch eine Diagnosemeldung ersetzt und die Schleife verlassen; sonst [Handoff-Dokument](glossary.md#交接书) schreiben → `resume=None, fork=False`
   (**ganz neue Session**) → Prompt wird zu `h.prompt_block()` → Pegel auf null → `attempt -= 1`.
4. **Wiederholbarer Fehler** → bei `not resilience.enabled or attempt >= max_attempts` raus;
   ergibt `classify(error)`, dass nicht wiederholt werden soll, ebenfalls raus; sonst `Event("retry")` senden, mit `wait_online()` aufs Netz warten,
   `sleep(delay_for(attempt))`; **lag jemals eine `session_id` vor, wird mit `resume` fortgesetzt** (Prompt wird zu
   `resilience.resume_prompt`) und `result.resumed` auf `True` gesetzt.

Zum Abschluss: `ended_at` schreiben, an `self.results` anhängen, `manifest.json` schreiben.

`manifest.json` hat **Append**-Semantik: bei jedem Schreiben wird die Platte neu gelesen und nach dem Feld `run` dedupliziert (die eigene Zeile wird ersetzt, fremde bleiben stehen),
deshalb ist es sicher, zwei flower parallel im selben `run_dir` laufen zu lassen — vorausgesetzt, die `run_id`s kollidieren nicht.

**Die drei Beobachtungspunkte des Handoffs** (alle `Event("handoff")`, unterschieden durch `payload["phase"]`):
`near` (nähert sich `warn_at`, wird pro Generation nur einmal gesendet), `writing` (das Handoff-Dokument wird geschrieben, dauert gut zehn Sekunden),
`done` (Payload enthält `degraded` / `path` / `sections`). Die Runde, die das Handoff-Dokument schreibt, läuft mit
`replace(spec, max_budget_usd=None)` — das Handoff muss geschrieben werden können und darf nicht am Budget hängenbleiben;
außerdem `on_event=None`, diese Runde erscheint nicht im UI.

Das Handoff-Dokument landet unter `<workbench.notes>/交接-<步骤名>.md`; **ohne Workbench wird nichts geschrieben**, das Dokument geht trotzdem per Prompt
an den Nachfolger, es lässt sich hinterher nur nicht mehr nachschlagen. Alte Handoffs werden nach `notes/archive/交接/<名>-<时间戳>.md` verschoben.

### `StepResult` {#stepresult}

```python
@dataclass
class StepResult:
    step: str
    session_id: str | None = None
    ok: bool = False
    cost_usd: float = 0.0
    num_turns: int = 0
    text: str = ""
    error: str | None = None
    started_at: float = 0.0
    ended_at: float = 0.0
    attempts: int = 1
    errors: list[str] = field(default_factory=list)
    resumed: bool = False
    retired: list[str] = field(default_factory=list)
    context: int = 0
```

Die komplette Abrechnung eines gelaufenen Schritts.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `step` | `str` | Pflicht | Schrittname (`step_name` oder `spec.name`) |
| `session_id` | `str \| None` | `None` | **Immer die zuletzt übernehmende Session** — die unterwegs beim Handoff verbrannten stehen in `retired` |
| `ok` | `bool` | `False` | Ob dieser Schritt geklappt hat |
| `cost_usd` | `float` | `0.0` | In Dollar. Über Retries und Handoffs hinweg **kumuliert** |
| `num_turns` | `int` | `0` | Anzahl Runden, ebenfalls kumuliert |
| `text` | `str` | `""` | **Enthält nur den Fließtext des Main Thread**. Was ein Subagent sagt, bleibt in seinem eigenen Transcript, das an ihn vergebene Task Brief ist `kind="prompt"` — beides landet hier nicht |
| `error` | `str \| None` | `None` | Fehlerursache. Spezialwerte siehe `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Unix-Zeitstempel |
| `attempts` | `int` | `1` | Tatsächliche Anzahl Versuche. Unterbrechungen und Handoffs **zählen nicht mit** |
| `errors` | `list[str]` | `[]` | Gesammelte synthetische API-Fehlermeldungen, **landen nicht in `text`** |
| `resumed` | `bool` | `False` | Ob unterwegs per Resume fortgesetzt wurde |
| `retired` | `list[str]` | `[]` | Die bei Handoffs dieses Schritts verbrannten `session_id`s, in Reihenfolge |
| `context` | `int` | `0` | Die Kontextgröße, die der Main Thread in der letzten Runde tatsächlich gesehen hat, also das Handoff-Kriterium |

| Attribut | Typ | Beschreibung |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`, `0.0` solange nicht fertig |

---

## Workflow {#流程}

Quellcode: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Ein [Workflow](glossary.md#流程) ist eine Reihe hintereinandergehängter [Schritte](glossary.md#步骤), plus die Regeln, wie Zustand zwischen den Schritten weitergereicht wird und wann vorzeitig abgebrochen wird. **Das Framework liefert keine fertigen Workflows, den Workflow schreibst du** — `starter_flow` ist nur eine lauffähige Vorlage.

Typ-Alias `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, steht in `flower.workflow.__all__`, nicht im obersten `__all__`).

### `Step` {#step}

```python
@dataclass
class Step:
    name: str
    spec: AgentSpec
    prompt: str | Callable[[Ctx], str]

    resume_from: str | None = None
    fork: bool = False

    retries: int = 0
    gate: Callable[[StepResult, Ctx], bool] | None = None
    on_fail: str = "stop"
    when: Callable[[Ctx], bool] | None = None
    on_reject: Callable[[StepResult, Ctx], str] | None = None
    resume_prompt: str | Callable[[Ctx], str] | None = None
    reduce: Callable[[StepResult, Ctx], str] | None = None
```

Die **Deklaration** eines Schritts. `Step` selbst ist keine Funktion — ausgeführt wird tatsächlich `Runtime.run(step.spec, prompt, ...)`. Die ersten drei Felder sind positional, `Step("取词", terse, "读 seed.txt …")` ist eine gültige Schreibweise.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | Pflicht | Schrittname. **Prozessübergreifend stabiler Schlüssel** — landet in `ctx[name]`, `ctx["_results"]`, im Manifest und in der Lineage. Umbenennen = Lineage gekappt |
| `spec` | `AgentSpec` | Pflicht | Welcher Agent läuft |
| `prompt` | `str \| Callable[[Ctx], str]` | Pflicht | Was gesagt wird. Darf ein Closure sein, das mit `ctx` gerechnet wird |
| `resume_from` | `str \| None` | `None` | Die Session welchen Schritts fortgesetzt wird. Hat der referenzierte Schritt keine Session erzeugt, **wird `ValueError` geworfen**, nicht still übersprungen |
| `fork` | `bool` | `False` | Forkt auf Basis von `resume_from`. **Ohne `resume_from` wirkungslos** |
| `retries` | `int` | `0` | Wie oft nach nicht bestandenem gate maximal erneut versucht wird. `retries=0` = nur eine Runde |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Entscheidet, ob dieser Durchlauf als bestanden gilt. **Darf async sein**. `False` gilt als Fehlschlag. **Wird pro Versuch genau einmal aufgerufen** — es kann Seiteneffekte haben (etwa den Brief auf Platte schreiben) und darf nicht mehrfach ausgelöst werden |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, siehe unten |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Bei `False` wird **der ganze Schritt übersprungen**: kein Result, kein Eintrag in `ctx["_results"]`. **Darf async sein** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Was in der **nächsten Runde** gesagt wird, wenn das gate nicht bestanden wurde. **Darf async sein**. Wird es gesetzt, ändert sich die Retry-Semantik, siehe unten |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt für den Fall der Continuity (statt von vorn zu beginnen) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Bestimmt, was in `ctx[name]` landet. Default ist der Originaltext `result.text`. **Muss synchron sein** |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Bei `resuming` und vorhandenem `resume_prompt` wird dieses genommen, sonst `prompt`; ist es aufrufbar, wird es mit `ctx` aufgerufen |

**Drei Arten, Sessions zu verbinden** (innerhalb desselben Runs):

| Schreibweise | Effekt |
|---|---|
| `resume_from=None` (Default) | Neue Session, nur mit dem im Prompt übergebenen Kontext. Billig, isoliert. **Aber bei `Workflow(continuous=True)` wird die Session des gleichnamigen Schritts aus der prozessübergreifenden Lineage geholt** |
| `resume_from="Name des vorigen Schritts"` | Dieselbe Session wird fortgesetzt, vollständiger Kontext. Teuer, zusammenhängend |
| `resume_from="Name des vorigen Schritts", fork=True` | Fork, verschmutzt die Originalsession nicht. Für Nachprüfung / parallele Varianten |

**`on_reject` ändert die Retry-Semantik**:

- Nicht gesetzt → der nächste Versuch **läuft von vorn** (gleicher Prompt, gleiches `resume_from`).
- Gesetzt → der nächste Versuch **setzt genau die eben abgelehnte Session fort**, der Prompt wird durch den Rückgabewert ersetzt, `fork` wird auf `False` gezwungen.
- Rückgabe leerer String → keine Rückweisung, degradiert zum Lauf von vorn.
- `result.session_id` ist `None` → degradiert ebenfalls zum Lauf von vorn.

**Die drei Werte von `on_fail`**:

| Wert | Verhalten |
|---|---|
| `"stop"` (Default) | Schreibt `ctx["_failed_at"] = name` und **bricht den gesamten Workflow ab** |
| `"skip"` | Springt zum nächsten Schritt, **`ctx[name]` wird nicht geschrieben** — nachgelagertes `lambda ctx: ctx["某步"]` läuft in einen `KeyError` |
| `"continue"` | `ctx[name] = result.text`, es geht mit dem unvollständigen Ergebnis weiter |

Ob bestanden oder nicht: `ctx["_results"][name] = result` wird immer geschrieben; ist `result.session_id` nicht leer, wird zusätzlich `ctx["_sessions"]` geschrieben und `lineage.remember(...)` aufgerufen.

### `Workflow` {#workflow}

```python
@dataclass
class Workflow:
    steps: list[Step]
    name: str = "workflow"
    context: Ctx = field(default_factory=dict)
    channel: Any = None
    workbench: Any = None
    continuous: bool = True

    async def run(
        self,
        runtime: Runtime,
        *,
        on_event: Callable[[Event], None] | None = None,
        on_step: Callable[[Step, StepResult], None] | None = None,
    ) -> Ctx
```

Führt eine Reihe von `Step` der Reihe nach aus und gibt das finale `ctx` zurück. `steps` ist positional, `Workflow([...])` ist gültig.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `steps` | `list[Step]` | Pflicht | Werden der Reihe nach ausgeführt |
| `name` | `str` | `"workflow"` | Name des Workflows |
| `context` | `Ctx` | `{}` | Initiales Kontext-Dict. **Läuft derselbe `Workflow` ein zweites Mal, ist ctx dasselbe dict** |
| `channel` | `HumanChannel \| None` | `None` | Hier wird eingehängt, wenn angehalten und ein Mensch gefragt werden muss. `run()` hängt dessen `on_event` automatisch an denselben Ausgang, **nur wenn `channel.on_event is None`**; auch das Treiberprogramm erfährt über dieses Feld, wem es antworten soll |
| `workbench` | `Workbench \| None` | `None` | Die vom Workflow vorgegebene Workbench, damit das Treiberprogramm sie findet |
| `continuous` | `bool` | `True` | Gleicher Pfad = dasselbe Gespräch. Umgesetzt über [`Lineage`](#lineage) |

| Parameter von `run()` | Typ | Default | Beschreibung |
|---|---|---|---|
| `runtime` | `Runtime` | Pflicht, positional | Mit welcher Runtime gelaufen wird |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Event-Ausgang, wird an jedes `Runtime.run` durchgereicht |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Callback nach jedem abgeschlossenen Schritt |

!!! warning "`continuous=True` ist der Default, `resume_from=None` heißt nicht neue Session"
    Ist Continuity an, ruft `run()` zuerst `Lineage.open(run_dir, workspace)` auf und prüft dann jeden Eintrag einzeln mit `runtime.has_session(sid)`, ob er noch in der Datenbank ist; nur die lebenden werden in `ctx["_sessions"]` eingespielt. Damit **spricht auch ein Schritt mit `resume_from=None` in der Session von letztem Mal weiter** — auch wenn der Prozess gekillt oder die Maschine neu gestartet wurde.

    Wer jedes Mal eine ganz neue Session will, schreibt explizit `Workflow(..., continuous=False)`.
    Außerdem: **Der Schrittname ist ein prozessübergreifend stabiler Schlüssel; wer ihn ändert, kappt die Lineage.**

Die **privaten Schlüssel**, die `run()` in ctx schreibt (alle mit `_` beginnend, kollidieren also nicht mit Schrittnamen):

| Schlüssel | Inhalt |
|---|---|
| `_runtime` | Die übergebene `Runtime`. **Darüber werden im gate Agents losgeschickt** |
| `_on_event` | Event-Ausgang. Auch der Agent im gate muss ans UI durchkommen, sonst bleibt die Oberfläche schwarz |
| `_sessions` | `dict[Schrittname, session_id]`, wird per `setdefault` gelesen |
| `_results` | `dict[Schrittname, StepResult]` |
| `_lineage` | Das `Lineage`-Objekt. Nur vorhanden bei `continuous=True` und wenn die Runtime `run_dir` + `workspace` hat |
| `_woke` | Rückgabewert von `lineage.bump()`, das wievielte Wake das ist |
| `_aborted` | Die Nachricht von `StepAbort` |
| `_failed_at` | Bei `on_fail="stop"` der Name des fehlgeschlagenen Schritts |

Payload von `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Retry-Labels**: Beim 0. Versuch `step.name`; danach mit `on_reject` `f"{name}#round{attempt+1}"`, ohne `on_reject` `f"{name}#retry{attempt}"`. Im Manifest sieht man auf einen Blick, wie dieser Schritt zu Ende gegangen ist. **Namen mit Suffix gehen nicht in die prozessübergreifende Lineage** — `Lineage.remember` verwendet den Originalnamen.

`runtime.on_session` umschließt nur die eine Zeile `runtime.run`; `try/finally` stellt sicher, dass es vor dem gate garantiert wieder abgenommen wird. `prompt_cur` / `resume_cur` / `fork_cur` sind lokale Variablen und werden nicht nach `step` zurückgeschrieben — dasselbe `Step`-Objekt kann ein zweites Mal laufen.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Aus dem `gate` geworfen = **sofort stoppen, nicht weiter versuchen**. Unterschied zu „`False` zurückgeben": `False` heißt „diesmal nicht, noch eine Runde"; `StepAbort` heißt „noch eine Runde bringt auch nichts".

Nach dem Wurf: `ctx["_aborted"] = str(exc)`, `passed = False`, **Ausstieg aus der Retry-Schleife (die restlichen `retries` werden nicht verbraucht)**, danach geht es wie bei einem normalen Fehlschlag über `on_fail` weiter (Default `"stop"`).

`with_goal` wirft es an zwei Stellen: wenn `ctx["_runtime"]` nicht zu bekommen ist, und wenn das Verdict `unreachable` lautet und niemand antwortet.

### `clarify_step()` {#clarify-step}

```python
def clarify_step(
    channel: HumanChannel,
    *,
    brief_path: str | Path,
    prompt: str | Callable[[Ctx], str],
    name: str = "确认需求",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_ask: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw,
) -> Step
```

Erzeugt einen `Step`, der [Clarify](glossary.md#前置确认) durchführt: Bedarf klären → in einen [`Brief`](#brief) parsen → wenn alle vier Abschnitte vollständig sind, einfrieren und auf Platte schreiben.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `channel` | `HumanChannel` | Pflicht, positional | Kanal zum Nachfragen |
| `brief_path` | `str \| Path` | Pflicht | Wohin der [Brief](glossary.md#需求确认书) geschrieben wird. **Muss in genau die Workbench fallen, deren Index tatsächlich injiziert wird** |
| `prompt` | `str \| Callable[[Ctx], str]` | Pflicht | Das ursprüngliche Anliegen des Menschen |
| `name` | `str` | `"确认需求"` | Schrittname, zugleich Schlüssel in `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Ohne Angabe wird `clarify(name, channel, instructions=instructions, **spec_kw)` benutzt |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen an den [Clarifier](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = jedes Mal neu fragen, egal ob ein Brief existiert |
| `on_fail` | `str` | `"stop"` | Wie `Step.on_fail` |
| `retries` | `int` | `0` | Wie oft nachgefragt wird, wenn die vier Abschnitte nicht zusammenkommen |
| `**spec_kw` | | | Wird direkt an [`clarify()`](#clarify-role) durchgereicht, man kann also `can_read=False`, `max_budget_usd=...` schreiben |

So sind die Felder im erzeugten `Step` gefüllt:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: bei `always_ask=True` → immer `True`; sonst wird `Brief.load(brief_path)` bei Vollständigkeit in ctx eingespielt **und dann `False` zurückgegeben (übersprungen)** — auch beim Überspringen muss eingespielt werden, sonst bekommt die nachgelagerte Stufe den Bedarf nicht.
- `gate`: `Brief.parse(result.text)`, unvollständig → `ctx[MISSING_KEY]` schreiben und `False` zurückgeben; vollständig → `b.write(brief_path)` einfrieren, in ctx einspielen, `True` zurückgeben.
- `reduce`: gibt `ctx[BRIEF_KEY].prompt_block()` zurück, **nicht den Originaltext des Modells** — im Originaltext kann Zusatzgeschriebenes stecken.
- `resume_from` **bleibt beim Default `None`**: Der nächste Schritt ist eine neue Session, bekommt nur den Brief, nicht das Frage-Antwort-Protokoll.
  Die Fragen und Antworten des Clarify **waren nie** im Kontext des Koordinators, sie wurden nicht nachträglich herausgeschnitten.

Drei Stellen, an denen in ctx eingespielt wird: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`, `ctx.pop(MISSING_KEY, None)`.

| Konstante | Wert | Beschreibung |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` ist ein `Brief`-Objekt; `ctx[step.name]` ist dessen `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Welche Abschnitte bei fehlgeschlagenem Clarify fehlen (chinesische Abschnittsnamen), zur Anzeige im UI |
| `CLARIFY_RESUME` | Ein chinesischer Prompt-Text | „Mach mit dem eben nicht zu Ende gebrachten Clarify weiter — **nicht von vorn anfangen** …". Ohne diesen Satz schickt die Continuity das ursprüngliche Anliegen als neue Aufgabe erneut los, und der Clarifier fragt womöglich bereits Gefragtes noch einmal |

### `goal_step()` {#goal-step}

```python
def goal_step(
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    brief_key: str = "确认需求",
    name: str = "设定目标",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_set: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw: Any,
) -> Step
```

Erzeugt einen `Step`, der **das Ziel setzt**: Der [Judge](glossary.md#判定者) liest den Brief, schreibt Ziel + Prüfliste, das Ganze wird in ein [`Goal`](#goal) geparst, eingefroren und auf Platte geschrieben. Gleiche Form wie `clarify_step`.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `channel` | `HumanChannel` | Pflicht, positional | Kanal zum Nachfragen |
| `goal_path` | `str \| Path` | Pflicht | Wohin die Zieldatei geschrieben wird |
| `brief_key` | `str` | `"确认需求"` | Aus `ctx[brief_key]` wird der Originaltext des Briefs geholt und in den Prompt gesteckt. **Ist da nichts, steht dort `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Schrittname |
| `spec` | `AgentSpec \| None` | `None` | Ohne Angabe wird `judge(name, channel, instructions=instructions, **spec_kw)` benutzt |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen |
| `always_set` | `bool` | `False` | `True` = Prüfliste neu herleiten, egal ob die Zieldatei existiert |
| `on_fail` | `str` | `"stop"` | Wie oben |
| `retries` | `int` | `0` | Wie oben |
| `**spec_kw` | | | Wird an [`judge()`](#judge-role) durchgereicht |

**Es gibt keinen `can_run`-Parameter** — wer will, dass der zielsetzende Judge Kommandos ausführen kann, muss `can_run=True` über `**spec_kw` durchreichen. Ohne das bekommt er kein `Bash`, und die Regel aus `JUDGE_RULES` „verschaffe dir zuerst Klarheit, in welcher Umgebung du bist" ist nicht ausführbar.

Das `gate` tut neben Parsen und Einfrieren noch eines: Enthält das Ziel Einträge `[此环境无法验证:…]`, wird **sofort** über `ctx["_on_event"]` ein `Event("task", payload={"unverifiable", "total", "path"})` als Hinweis gesendet — das Schicksal dieser Einträge entscheidet sich genau in diesem Moment des Zielsetzens; bis zum Verdict ist bereits das Geld einer ganzen Arbeitsrunde ausgegeben.

**Es ist kein `resume_prompt` gesetzt** — beim Zielsetzen soll der Brief ohnehin im Volltext neu geschickt werden.

| Konstante | Wert | Beschreibung |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` ist ein `Goal`-Objekt; `ctx[step.name]` ist Markdown |
| `VERDICT_KEY` | `"_verdict"` | Das letzte [`Verdict`](#verdict), fürs UI |
| `ROUND_KEY` | `"_goal_rounds"` | Wie viele Runden das Verdict gelaufen ist |

### `with_goal()` {#with-goal}

```python
def with_goal(
    step: Step,
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    spec: AgentSpec | None = None,
    rounds: int = 3,
    instructions: str = "",
    can_run: bool = False,
    name: str | None = None,
    **spec_kw: Any,
) -> Step
```

Legt einem vorhandenen `Step` den [Goal Guard](glossary.md#目标看守) um: Nach jeder Runde beurteilt der Judge unabhängig; ist das Ziel nicht erreicht, wird zurückgewiesen und weitergearbeitet.

Das Ergebnis ist `replace(step, retries=max(0, rounds - 1), gate=<neues gate>, on_reject=<neues on_reject>)` — mit `dataclasses.replace` statt feldweisem Neubau; beim Neubau ging einmal `resume_prompt` verloren, **und zwar ohne Fehlermeldung**, es wurde bei der Continuity nur der ganze Brief noch einmal verschickt.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `step` | `Step` | Pflicht, positional | Der bewachte Schritt |
| `channel` | `HumanChannel` | Pflicht, positional | Kanal, um bei Nicht-Entscheidbarkeit den Menschen um Hilfe zu bitten |
| `goal_path` | `str \| Path` | Pflicht | Zieldatei, aus der gelesen wird, wenn `ctx[GOAL_KEY]` unvollständig ist |
| `spec` | `AgentSpec \| None` | `None` | Ohne Angabe wird `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` benutzt |
| `rounds` | `int` | `3` | **Gesamtzahl der Runden, nicht Zusatzrunden**: `rounds=3` → `retries=2` → höchstens drei Arbeitsrunden. `rounds=1` = eine Runde arbeiten, einmal beurteilen, bei Nichtbestehen Fehlschlag |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen an den Judge |
| `can_run` | `bool` | `False` | Ob der Judge `Bash` ausführen darf |
| `name` | `str \| None` | `None` | Name des Judge, Default `f"{step.name}·判定"` |
| `**spec_kw` | | | Wird an `judge()` durchgereicht |

Das `gate` ist **async**, Ablauf:

1. `ctx["_runtime"]` fehlt → **`StepAbort` werfen** („Runtime nicht verfügbar, Ziel kann nicht beurteilt werden"). **Nicht so tun, als sei es bestanden.**
2. `ctx[ROUND_KEY] += 1`.
3. Ziel holen: bevorzugt ein vollständiges `Goal` aus `ctx[GOAL_KEY]`, sonst `Goal.load(goal_path)`, sonst ein leeres `Goal()`.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **Der Judge ist ein eigenständiges `Runtime.run`, `resume` ist immer `None` — es ist immer eine neue Session**; `step_name` trägt die Rundennummer und geht damit nicht in die prozessübergreifende Lineage.
5. `Verdict.parse(vr.text)` wird nach `ctx[VERDICT_KEY]` geschrieben.
6. `v.achieved` → `True` zurückgeben.
7. Nicht `unreachable` (einschließlich unklarer Fälle mit `v.ok=False`) → bei Unklarheit wird ein Default-Reason ergänzt, Rückgabe `False`.
   **Unklarheit zählt ausnahmslos als nicht erreicht** — ein „sieht ok aus" darf die Arbeit nicht abschließen.
8. `unreachable` → `await channel.ask(...)` fragt den Menschen, drei Optionen:
   - Niemand antwortet (`a.state != "answered"`) → **`StepAbort` werfen**. Weiter leerzudrehen ist die teuerste Option.
   - „Ergebnis akzeptieren und so weitermachen" → `True` zurückgeben.
   - „Ziel ändern" → noch einmal nach dem neuen Ziel fragen, `g.amend(...).write(goal_path)`, `ctx[GOAL_KEY]` aktualisieren, `False` zurückgeben.
   - Alles andere (einschließlich frei getippter Antworten) → gilt als „du hast falsch beurteilt", die Aussage des Menschen wird in `v.reason` festgehalten, Rückgabe `False`.

`on_reject` ist **synchron**: gibt `ctx[VERDICT_KEY].feedback()` zurück, ohne `Verdict` `""` (degradiert zum Lauf von vorn).

### `starter_flow()` {#starter-flow}

```python
def starter_flow(
    ask: str,
    *,
    workspace: str | Path = ".",
    run_dir: str | Path = "runs",
    new: bool = False,
    isolate: bool = False,
    clarify_only: bool = False,
    goal: bool = True,
    rounds: int = 3,
    judge_can_run: bool = False,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    instructions: str = "",
    worker_prompt: str = "你负责实现。每改一处就跑一次验证,别攒到最后。",
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
    log_name: str = "问答记录.md",
) -> Workflow
```

Baut einen sofort lauffähigen Drei-Schritt-Workflow zusammen: **Bedarf klären → Ziel setzen → arbeiten** (mit Goal Guard). Genau das benutzt die Kommandozeile `flower`.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `ask` | `str` | Pflicht, positional | Ein Satz mit dem Anliegen. **Beim Wake ist er keine neue Aufgabe, sondern „noch ein Satz, den jemand gesagt hat"** |
| `workspace` | `str \| Path` | `"."` | Workspace |
| `run_dir` | `str \| Path` | `"runs"` | Run-Verzeichnis |
| `new` | `bool` | `False` | `True` = Lineage + Brief + Ziel archivieren (alle drei zusammen), von vorn beginnen |
| `isolate` | `bool` | `False` | Öffnet für den Worker eine Worktree-[Isolation](glossary.md#隔离). Die Workbench wandert entsprechend nach `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Gibt nur den Workflow mit dem Clarify-Schritt zurück |
| `goal` | `bool` | `True` | Ob der [Goal Guard](glossary.md#目标看守) angebaut wird. `False` = nach der Arbeitsstufe ist Schluss |
| `rounds` | `int` | `3` | Wird an `with_goal(rounds=)` durchgereicht, Gesamtzahl der Runden |
| `judge_can_run` | `bool` | `False` | Wird an `with_goal(can_run=)` durchgereicht |
| `max_asks` | `int \| None` | `None` | Wird an `HumanChannel` durchgereicht, `None` = unbegrenzt |
| `timeout_s` | `float \| None` | `1800.0` | Wird an `HumanChannel` durchgereicht. `0` = vollautomatisch, jede Frage läuft sofort ins Leere |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen an den Clarifier |
| `worker_prompt` | `str` | siehe Signatur | System-Prompt des Workers |
| `brief_name` | `str` | `"需求.md"` | Dateiname des Briefs, landet in `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Dateiname des Ziels, ebenda |
| `log_name` | `str` | `"问答记录.md"` | Dateiname des Frage-Antwort-Protokolls, ebenda |

Feste Verdrahtung:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Verhaltensverzweigungen:

- `isolate=True` und der Workspace ist kein Git-Repo → **`ValueError` werfen**, nicht erst warten, bis das `Agent`-Tool einen Fehler meldet (dann ist das Geld schon ausgegeben).
- **Wake-Erkennung**: Existiert `Brief.load(brief_path)` und ist `complete()`, gilt es als Wake. Kein Wake und `ask` leer → **`ValueError("要给一句诉求,例如 flower '帮我做一个 X'")` werfen**.
- Beim Wake landet dieser Satz gleichzeitig an **drei Stellen**, fehlt eine davon, verpufft er still: angehängt an den Brief (`ch.amend(said, label="唤醒时追加")`, steht er schon in der Datei, wird er nicht doppelt geschrieben), `goal_step(always_set=True)` leitet die Prüfliste neu her (ohne Neuherleitung liest der Judge weiter das alte Ziel), und er geht direkt an den Koordinator (in dessen Kontext steht das **alte** Ziel; ohne diesen Schritt arbeitet er nach altem Maßstab und wird nach neuem beurteilt).

### `wake_state()` {#wake-state}

```python
def wake_state(
    workspace: str | Path = ".",
    *,
    run_dir: str | Path = "runs",
    isolate: bool = False,
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
) -> dict
```

**Eine nur lesende Sondierung vor dem Start, es wird kein einziges Byte geschrieben.** Damit man dem Menschen vor dem eigentlichen Lauf sagen kann: „Das ist eine Fortsetzung" oder „das fängt von vorn an".

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Workspace, positional |
| `run_dir` | `str \| Path` | `"runs"` | Run-Verzeichnis |
| `isolate` | `bool` | `False` | Bestimmt die Lage der Workbench, muss denselben Wert haben wie bei `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Dateiname des Briefs |
| `goal_name` | `str` | `"目标.md"` | Dateiname des Ziels |

Das zurückgegebene dict:

| Schlüssel | Typ | Beschreibung |
|---|---|---|
| `waking` | `bool` | Brief existiert und alle vier Abschnitte sind vollständig |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Anzahl der Einträge in der Zielprüfliste, ohne Ziel `0` |
| `woke` | `int` | `Lineage.woke`, wie oft schon geweckt wurde |
| `steps` | `dict` | Kopie von `Lineage.steps`, Schrittname → `session_id` |

Die Lage der Workbench wird **nur hier und in `starter_flow` je einmal definiert**: `isolate=True` → `<ws>.parent/.flower-<ws.name>` (außerhalb des Repos); sonst `<ws>/.flower`. Auch ein Treiberprogramm, das wissen will, wo der Brief liegt, geht über diese Funktion — wer den Pfad selbst zusammensetzt und sich vertut, bekommt keinen Fehler, es verpufft nur still.

---

## Rollen-Factories {#角色工厂}

Quelle: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Alle fünf Rollen sind Factory-Funktionen. Jede Rolle = **ein Stück injizierter Regeltext + ein Satz Tools + ein Satz Hooks**.
`worker()` liefert eine `AgentDefinition` des SDK (für Subagents gedacht), die anderen vier liefern [`AgentSpec`](#agentspec)
(startet jeweils eine eigene Session).

Die Rollen selbst **hängen keine Hooks ein** — das Abfangen von Tools montiert `Runtime._attempt` automatisch anhand von `spec.delegate_only`,
siehe [Hook-Schicht](#hook).

Interne Tool-Gruppenkonstanten (nicht exportiert, bestimmen aber die Defaults):

```python
COORDINATOR_TOOLS = ["Agent", "TodoWrite", "Read"]
WEB_TOOLS         = ["WebFetch", "WebSearch"]
WORKER_TOOLS      = ["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch"]
```

### `coordinator()` {#coordinator}

```python
def coordinator(
    name: str,
    instructions: str,
    workers: dict[str, AgentDefinition],
    *,
    channel: Any = None,
    can_read: bool = True,
    glance: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    permission_mode: str = "acceptEdits",
    compact: Any = None,
    hooks: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> AgentSpec
```

Baut den [Koordinator](glossary.md#协调者) auf dem [Haupt-Thread](glossary.md#主线程): Aufgabe zerlegen, delegieren, Berichte lesen, entscheiden,
**aber nicht selbst Hand anlegen**. Die ersten drei Parameter sind Positionsargumente.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | Pflicht | Rollenname, zugleich der Default-Schrittname |
| `instructions` | `str` | Pflicht | Fachliche Anweisungen. Ergibt am Ende `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | Pflicht | Welche Rollen ihm unterstehen, landet in `AgentSpec.agents`. **Deren nur lesende Web-Tools werden zusätzlich in die `allowed_tools` des Koordinators selbst gemischt**, siehe unten |
| `channel` | `HumanChannel \| None` | `None` | Wenn gesetzt, werden gleichzeitig die beiden Tools `inbox` **und** `ask` angehängt und `mcp_servers` gesetzt |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → ohne `Read` |
| `glance` | `bool` | `True` | Hängt `"Bash"` an und setzt `AgentSpec.glance`. **Was konkret laufen darf, entscheidet `delegate_guard`**, nicht diese Stelle |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | Obergrenze für Runden |
| `max_budget_usd` | `float \| None` | `None` | Obergrenze des [Budgets](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Berechtigungsmodus. **Achtung auf diesen Default** — an `clarify()`/`judge()` weitergereicht, reißt er den Schutz dieser beiden Rollen ein |
| `compact` | `CompactPolicy \| None` | `None` | Wenn gesetzt, wird es von `Runtime` nicht zwangsweise auf `no_summary` gestellt |
| `hooks` | `dict[str, Any] \| None` | `None` | Zusätzliche Hooks, werden mit `workbench_hooks` gemerged |
| `env` | `dict[str, str] \| None` | `None` | Zusätzliche Umgebungsvariablen |

Drei Dinge stehen in der erzeugten `AgentSpec` fest: `delegate_only=True`, `agents=workers`,
und `workbench` behält den `AgentSpec`-Default `True`.

#### Die Web-Tools aus `workers` werden mit eingemischt {#coordinator-web-merge}

Nachdem die Liste gebaut ist, geht `coordinator()` jede `AgentDefinition.tools` durch; alles, was in
`WEB_TOOLS` (`WebFetch`, `WebSearch`, `roles.py:33`) liegt, wird zusätzlich in die eigenen
`allowed_tools` des Koordinators aufgenommen (`roles.py:523-526`).

**Grund: `allowed_tools` ist genau wie `disallowed_tools` session-weit.** Das ist der härteste Beleg im ganzen Text für diesen Punkt —
es betrifft nicht nur den Haupt-Thread. Ein Tool, das nicht in dieser session-weiten Liste steht, muss auch beim Aufruf durch einen
**Subagent** durch die Berechtigungsfreigabe; im unbeaufsichtigten Betrieb gibt es niemanden, der freigibt, und die Harness antwortet mit
`Claude requested permissions to use X, but you haven't granted it yet`
(`toolDenialKind=user-rejected`), während das Modell denselben Aufruf immer wieder wiederholt. In der Praxis reingefallen: dem Worker
`WebFetch`/`WebSearch` gegeben, aber nur in `AgentDefinition.tools` geschrieben — in jenem Novel-Run gab es über zwanzig
user-rejected und kein einziges geschriebenes Wort (`roles.py:513-518`).

Beide Felder sind gleichermaßen session-weit, die **Symptome unterscheiden sich**: `disallowed_tools` wirft sofort einen Fehler,
`allowed_tools` führt zu stillem Wiederholen bis zum Ende. Letzteres ist schwerer zu finden, weil auf dem Bildschirm nichts nach Fehler aussieht.

**Eingemischt wird nur, was lesend und nebenwirkungsfrei ist.** `Write`/`Edit`/`Bash` werden **absichtlich nicht** eingemischt: Sobald der Haupt-Thread
dafür freigabefrei ist, ist die Mauer „der Koordinator legt nicht selbst Hand an" von `delegate_guard` sinnlos; und `Bash`/`Write` im Subagent
funktionieren ohnehin (gemessen 462-mal durchgelassen, `roles.py:520-522`).

Im Quellcode steht ausdrücklich, dass man **„nur koordinieren, nicht selbst Hand anlegen" nicht über `disallowed_tools` umsetzen soll** — das ist session-weit
und sperrt `Bash`/`Write` der Subagents gleich mit, siehe die Warnung bei [`AgentSpec`](#agentspec).
Der richtige Weg ist genau der hier: `delegate_only=True` + nichts in `allowed_tools`,
und [`delegate_guard`](#delegate-guard) blockt anhand der `agent_id` nur den Haupt-Thread.

Ist `channel` gesetzt, kommen **beide Tools zusammen**, das ist nicht optional: Hängt der MCP-Server dran, sind beide da, und
`allowed_tools` ist nicht exklusiv — aufrufbar sind sie so oder so. Im unbeaufsichtigten Betrieb blockiert jedes `ask` die volle `timeout_s` —
für solche Fälle `HumanChannel(timeout_s=0)` verwenden.

### `worker()` {#worker}

```python
def worker(
    description: str,
    prompt: str,
    *,
    tools: list[str] | None = None,
    model: str = "inherit",
    effort: str | int | None = None,
    max_turns: int | None = None,
    permission_mode: str | None = None,
    skills: list[str] | None = None,
    discipline: bool = True,
    isolate: bool = False,
) -> AgentDefinition
```

Baut die Definition des [Subagents](glossary.md#subagent), der die eigentliche Arbeit macht. Die ersten beiden Parameter sind Positionsargumente.
Zurück kommt eine `AgentDefinition` des SDK, die direkt in `coordinator(workers={...})` gesteckt wird.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `description` | `str` | Pflicht | **Grundlage, nach der der Koordinator auswählt** — klar schreiben, „welche Arbeit an ihn geht" |
| `prompt` | `str` | Pflicht | Sein System-Prompt. Bei `discipline=True` zusammengesetzt zu `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | Der Worker soll nicht heruntergestuft werden |
| `effort` | `str \| int \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | Wird zu **`maxTurns`** im SDK (CamelCase) |
| `permission_mode` | `str \| None` | `None` | Wird zu **`permissionMode`** im SDK (CamelCase) |
| `skills` | `list[str] \| None` | `None` | Welche Skills er benutzen darf |
| `discipline` | `bool` | `True` | Ob die Berichtsdisziplin aus `WORKER_RULES` angehängt wird |
| `isolate` | `bool` | `False` | Setzt die [Isolations](glossary.md#隔离)-Markierung, geht über `isolated()`, **kein Feld von `AgentDefinition`** |

`isolate=True` verlangt, dass der Workspace ein Git-Repository ist, sonst meldet das `Agent`-Tool direkt `"not in a git repository"` —
**es degradiert nicht still**. Und die Markierung ist ein Python-Attribut — ein `dataclasses.replace()` auf der `AgentDefinition`
verliert sie, die Isolation fällt still aus.

### `clarify()` {#clarify-role}

```python
def clarify(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_read: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

Baut den [Clarifier](glossary.md#确认者): vor dem Loslegen die Anforderungen klären, nichts tun, nur fragen, am Ende genau vier Abschnitte ausgeben.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | Pflicht | Rollenname, Positionsargument |
| `channel` | `HumanChannel` | Pflicht | Fragekanal, Positionsargument |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen, hinter `CLARIFIER_RULES` gehängt |
| `can_read` | `bool` | `True` | Bei `True` werden `Read` `Glob` `Grep` `WebFetch` `WebSearch` angehängt |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | **Keine Rundenbegrenzung** |
| `max_budget_usd` | `float \| None` | `None` | Budgetobergrenze |

Die erzeugte `AgentSpec`: `allowed_tools = [channel.tool_name] + (die fünf, wenn lesend)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (er hat keine Schreib-Tools, der Index bringt ihm nichts),
`permission_mode` erbt den `AgentSpec`-Default `"default"`.
**Kein `Write` / `Edit` / `Bash` / `Agent`, und auch kein `inbox`** (anders als beim Koordinator).

!!! warning "`max_turns` klein zu setzen macht das unbegrenzte Nachfragen zur leeren Behauptung"
    Jede Frage ist eine Runde. `max_turns=16` heißt „höchstens gut ein Dutzend Fragen", und der Satz „es gibt keine Rundenobergrenze" im Kanal ist auf der Stelle hinfällig.

    Wer das Fragen wirklich freigeben will, muss **beides** freigeben: `HumanChannel.max_asks` (Default ist bereits `None` = unbegrenzt)
    und `max_turns` (Default ist bereits `None`).

### `judge()` {#judge-role}

```python
def judge(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_run: bool = False,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec
```

Baut den [Judge](glossary.md#判定者): entweder vor dem Start das Ziel festlegen oder nach jeder Runde diese Runde beurteilen.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | Pflicht | Rollenname, Positionsargument |
| `channel` | `HumanChannel` | Pflicht | Fragekanal, Positionsargument |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen, hinter `JUDGE_RULES` gehängt |
| `can_run` | `bool` | `False` | Bei `True` kommt `Bash` in die Whitelist, `whitelist_guard` lässt `Bash` entsprechend durch, blockt `Write`/`Edit` weiterhin |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | Obergrenze für Runden |
| `max_budget_usd` | `float \| None` | `None` | Budgetobergrenze |

Die erzeugte `AgentSpec`: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (bei `can_run`) `["Bash"]`,
`workbench=False`, der Rest wie bei `clarify()`. **Kein `Write` / `Edit` / `Agent`, und auch kein `inbox`.**

**Abwägung**: `can_run=True` macht die Beurteilung härter (Abnahmebefehle können wirklich laufen), der Preis ist, dass der Judge damit
den Arbeitsbereich verändern kann — `Bash` allein kann schon Dateien schreiben. Wer absolut neutrale Beurteilung will, lässt es aus.

### `oracle()` {#oracle}

```python
def oracle(
    name: str = "旁路问答",
    *,
    instructions: str = "",
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = 12,
    max_budget_usd: float | None = 0.5,
) -> AgentSpec
```

Baut den [Oracle](glossary.md#旁路顾问): Während der Run noch läuft, fragt man ihn „wo stehen wir gerade", er sieht sich die letzten Events und die Workbench an
und antwortet dann. **Was er sagt, gelangt nicht in den Kontext dieses Runs.**

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Rollenname, Positionsargument |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen, hinter `ORACLE_RULES` gehängt |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | **`12`** | Standardmäßig mit Bremse |
| `max_budget_usd` | `float \| None` | **`0.5`** | Standardmäßig mit Bremse. Das ist „mal eben nachfragen" und darf nicht entgleisen |

Die erzeugte `AgentSpec`: `allowed_tools = ["Read", "Glob", "Grep"]` (**kein Channel** — er fragt nicht,
er antwortet nur), `workbench=True` (**der einzige der fünf Rollen, der kein Koordinator ist und trotzdem die Workbench anhat** — er soll ja genau die Ergebnisse und Notizen lesen).

### Die fünf Regeltexte {#rules}

Alle fünf Konstanten stehen in `__all__`, man kann sie direkt importieren, lesen, zusammensetzen und ändern.

| Konstante | Injiziert in | Injektionsart | Kernpunkte |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Du bist „ein Mensch, der Claude Code bedienen kann", kein Worker; keine Dateien schreiben / keinen Code ändern / keine Tests laufen lassen; `Bash` reicht nur für „einen Blick", und das Ergebnis veraltet; **im [Task Brief](glossary.md#任务书) steht nur, was für genau diese Aufgabe spezifisch ist**; die einzige Regel, die noch mitzugeben ist, lautet „wo die Workbench liegt + lange Ergebnisse nach `artifacts/` + in der Antwort nur den Pfad"; nach jeder abgeschlossenen Zwischenaktion einmal `inbox` prüfen; `ask` blockiert, nur an echten Weggabelungen einsetzen |
| `WORKER_RULES` | `worker()` | **hinter** den `prompt` des Subagents gehängt | Antwortformat 结论 / 依据 / 产出 / 未验证, höchstens 30 Zeilen; verboten sind Dateiinhalte, Kommandoausgaben, Logs, roher Diff; verboten ist das Nacherzählen von Versuch und Irrtum; vor dem Loslegen erst in `.flower/scripts/` schauen. **Bewusst steht dort nicht „lange Ergebnisse nach `artifacts/`"** — den echten Pfad erzeugt die `Workbench`, fest verdrahtet wäre er falsch |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Nichts tun, nur die Anforderungen klarfragen; **keine Mengenbegrenzung, fragen bis es klar ist**; der Mensch ist womöglich nicht da, bei Timeout selbst entscheiden und es unter 「未知与假设」 schreiben; Ausgabe **genau vier Abschnitte**; keinen Code schreiben, keine Dateiinhalte einfügen |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Zwei Dinge, eins davon. **Ziel festlegen**: Jeder Listenpunkt muss auf der Stelle überprüfbar sein, die Länge der Liste ergibt sich aus der Zahl der Fehlerarten, **Grenzen sind kein Prüfpunkt**, an nicht prüfbare Punkte am Ende `[此环境无法验证:原因]` anhängen. **Diese Runde beurteilen**: Ausgabe **genau drei Abschnitte**, beurteilt wird **das Ergebnis, nicht der Quellcode**, „ist fertig" wird per Default nicht geglaubt, „nicht geschafft" und „lässt sich hier nicht prüfen" sind zwei verschiedene Schlüsse, letzterer darf **auf keinen Fall als bestanden gewertet werden** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Ein Nebenweg; jener Run läuft noch, du unterbrichst ihn nicht und nimmst nicht teil; **nur lesend**; nach der Antwort wird alles verworfen, was du sagst, gelangt nicht in den Kontext jenes Runs; du hast nur das „Fenster der letzten Events" und die „Workbench"; erst schauen, dann antworten, wenn du nicht antworten kannst, sag das, kurz |

---

## Agent-Definition {#agent-定义}

Quelle: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` ist die vollständige Deklaration eines spezialisierten Agents, `build_options` kompiliert sie zu den `ClaudeAgentOptions` des SDK.
Die [Rollen-Factories](#角色工厂) liefern genau eine `AgentSpec` — wer eine Kombination außerhalb der Factories braucht, konstruiert sie direkt.

### `AgentSpec` {#agentspec}

```python
@dataclass
class AgentSpec:
    name: str
    instructions: str
    allowed_tools: list[str] = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    permission_mode: str = "default"
    agents: dict[str, Any] | None = None
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, Any] | None = None
    compact: CompactPolicy | None = None
    env: dict[str, str] = field(default_factory=dict)
    glance: bool = False
    workbench: bool = True
    delegate_only: bool = False
```

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | Pflicht | Rollenname. Zugleich der Default-`step_name` von `Runtime.run` und die Selbstbezeichnung im Ablehnungstext von `whitelist_guard` |
| `instructions` | `str` | Pflicht | Fachliche Anweisungen. **Wird hinter den nativen System-Prompt von Claude Code [angehängt](glossary.md#叠加), nicht ersetzt** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Liste ohne Freigabepflicht, keine exklusive Whitelist** — das Modell kann weiterhin Tools aufrufen, die nicht drinstehen. Exklusivität macht [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Session-weit.** Siehe die Warnung unten |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | Obergrenze für Runden |
| `max_budget_usd` | `float \| None` | `None` | Obergrenze des [Budgets](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Berechtigungsmodus |
| `agents` | `dict[str, Any] \| None` | `None` | Tabelle der Subagent-Definitionen, Werte sind `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | MCP-Server-Tabelle. `HumanChannel.mcp_servers()` füllt direkt hier hinein |
| `hooks` | `dict[str, Any] \| None` | `None` | Zusätzliche Hooks, `Runtime` merged sie per `merge_hooks` mit seinen eigenen |
| `compact` | `CompactPolicy \| None` | `None` | Wenn gesetzt, wird es von `Runtime` nicht zwangsweise auf `no_summary` gestellt |
| `env` | `dict[str, str]` | `{}` | Umgebungsvariablen für den Subprozess. `compact.env()` wird darauf per update angewandt |
| `glance` | `bool` | `False` | Erlaubt dem Koordinator, selbst „nur mal schauen"-`Bash` laufen zu lassen. Was durchgelassen wird, entscheidet [`is_ephemeral`](#is-ephemeral), das Ergebnis wird von der `EphemeralPolicy` als veraltet markiert |
| `workbench` | `bool` | `True` | Ob der Workbench-Index in den System-Prompt dieses Agents injiziert wird. **Rollen ohne Schreib-Tools schalten das ab** (`clarify()` / `judge()` haben per Default `False`) |
| `delegate_only` | `bool` | `False` | Nur koordinieren, nicht selbst Hand anlegen. Bei `True` montiert `Runtime` den `delegate_guard` und **montiert keinen** `whitelist_guard` |

!!! warning "`disallowed_tools` ist session-weit und sperrt Subagents mit"
    Wortlaut des gemessenen Fehlers: `"Bash is disabled for this session, in subagents as well as here"`.
    Das heißt: Wer den Koordinator vom Selbermachen abhalten will und dafür `disallowed_tools=["Bash"]` verwendet, nimmt auch dem
    ausgesandten Worker die Möglichkeit, Befehle auszuführen — der ganze Run ist hin.

    Für „nur koordinieren, nicht selbst Hand anlegen" nimmt man `delegate_only=True` + nichts in `allowed_tools` und lässt
    [`delegate_guard`](#delegate-guard) anhand der `agent_id` nur den Haupt-Thread blocken.

### `build_options()` {#build-options}

```python
def build_options(
    spec: AgentSpec,
    *,
    cwd: str | Path | None = None,
    session_store: SessionStore | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    use_plugin: bool = True,
    portable: bool = True,
    add_dirs: list[str] | None = None,
    flush: str = "eager",
    prelude: str = "",
) -> ClaudeAgentOptions
```

Kompiliert eine `AgentSpec` zu den `ClaudeAgentOptions` des SDK. Genau das ruft `Runtime._attempt` intern auf;
wer das SDK selbst steuert (ohne `Runtime`), steigt ebenfalls hier ein.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `spec` | `AgentSpec` | Pflicht, Positionsargument | Die zu kompilierende Deklaration |
| `cwd` | `str \| Path \| None` | `None` | Nur wenn nicht `None`, wird `cwd` geschrieben |
| `session_store` | `SessionStore \| None` | `None` | Nur wenn nicht `None`, werden `session_store` und `session_store_flush` geschrieben |
| `resume` | `str \| None` | `None` | Welche Session fortgesetzt wird |
| `fork` | `bool` | `False` | Wird zu `fork_session`. **Steckt in `if resume:`** |
| `resume_at` | `str \| None` | `None` | Wird zu `resume_session_at`. **Steckt ebenfalls in `if resume:`** |
| `use_plugin` | `bool` | `True` | `True` und `PLUGIN_DIR` existiert → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Zusätzlich freigegebene Verzeichnisse. **Pflicht, wenn die Workbench außerhalb des Arbeitsbereichs liegt** |
| `flush` | `str` | `"eager"` | Wird zu `session_store_flush` |
| `prelude` | `str` | `""` | Abschnitt, der hinter `instructions` angehängt wird (der Workbench-Index läuft hier durch) |

Zuordnung:

| Erzeugter Options-Schlüssel | Wert |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Direkt aus `spec` |
| `setting_sources` | `[]` (portabel) oder `["project"]` |
| `plugins` | Nur vorhanden, wenn das Verzeichnis `plugin/` in der Repo-Wurzel existiert |
| `cwd` / `add_dirs` | Nur geschrieben, wenn nicht leer |
| `session_store` / `session_store_flush` | Nur geschrieben, wenn `session_store` nicht `None` ist |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Jeweils nur geschrieben, wenn nicht leer |
| `env` | `dict(spec.env)`, danach `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Nur wirksam, wenn `resume` wahr ist** |

`PLUGIN_DIR` ist das `plugin/` in der Repo-Wurzel (relativ zu `flower/core/agent.py` drei Ebenen nach oben). Nach einer pip-Installation existiert dieses Verzeichnis nicht zwingend,
der Code prüft es mit `is_dir()`.

!!! warning "`fork=True` ist ohne `resume` still wirkungslos"
    `fork_session` und `resume_session_at` stecken beide in `if resume:` — ohne `resume` wirken sie überhaupt nicht,
    **und es gibt auch keinen Fehler**. Ebenso greift `Runtime.run(resume_at=...)` nur, wenn `resume` gegeben ist,
    und **`Workflow` übergibt `resume_at` nie**: Wer auf eine Nachricht zurückrollen will, muss `Runtime.run` direkt aufrufen.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

Das Schaltbrett für den Auto-[Compact](glossary.md#压缩), Ergebnis ist ein Satz Umgebungsvariablen für den Subprozess.
Der Compact-Algorithmus selbst steckt im Harness-Binary und ist nicht änderbar, änderbar ist nur, „ob er auslöst".

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = nichts setzen, Schwelle = Fenster − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (schaltet auch `/compact` ab). **Andere Werte werfen `ValueError`**, sie werden nicht still ignoriert |
| `window` | `int \| None` | `None` | Nicht `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. Die CLI-Seite begrenzt auf 100k–1M, weniger als 100k wird auf 100k angehoben |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `env` | `() -> dict[str, str]` | Erzeugt die Umgebungsvariablen. **Ein unzulässiger `mode` wirft hier den `ValueError`, nicht bei der Konstruktion** — aufgerufen wird sie von `build_options`, der Fehler taucht also in `Runtime.run` auf |

### `HandoffPolicy` {#handoffpolicy}

```python
@dataclass
class HandoffPolicy:
    enabled: bool = True
    window: int = field(default_factory=default_window)
    headroom: int = 50_000
    max_generations: int = 8

    @property
    def at(self) -> int: ...        # max(10_000, window - headroom)
    @property
    def warn_at(self) -> int: ...   # max(1_000, at - 20_000)
```

Das Policy-Objekt für „bei vollem Kontext ein [Handoff-Dokument](glossary.md#交接书) schreiben und eine neue Session starten" statt zu komprimieren.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `enabled` | `bool` | `True` | Abgeschaltet fällt man auf Auto-Compact zurück |
| `window` | `int` | `default_window()` | Wie groß man das Kontextfenster des Modells annimmt |
| `headroom` | `int` | `50_000` | Wie viel Reserve bleibt. Grund: Auto-Compact löst bei Fenster −33k aus, der Handoff muss davor stattfinden, und das „Schreiben des Handoffs" braucht selbst noch eine Runde |
| `max_generations` | `int` | `8` | Wie viele Generationen ein Schritt maximal durchläuft. **Das ist eine Bremse gegen Entgleisen, keine Kapazitätsplanung** |

| Property | Typ | Beschreibung |
|---|---|---|
| `at` | `@property -> int` | Handoff-Schwelle `max(10_000, window - headroom)`. **Untergrenze 10k** — darunter lässt sich nicht einmal mehr ein Handoff schreiben |
| `warn_at` | `@property -> int` | Position der Annäherungswarnung `max(1_000, at - 20_000)`, pro Generation nur einmal gesendet |

!!! warning "Ein zu kleines `window` führt zu endlosen Handoffs und verbrennt Geld"
    Liegt `at` unter dem **Startboden** der jeweiligen Rolle (beim Koordinator gemessen etwa 34k), überschreitet jede neue Session schon beim ersten Wort die Grenze; und
    **ein Handoff verbraucht kein Retry-Kontingent** (`attempt -= 1`), also dreht sich das Ganze endlos leer. Die einzige Bremse ist `max_generations=8`,
    beim Anschlagen wird `error` durch eine Diagnose ersetzt, die empfiehlt, `window` zu erhöhen oder den Handoff abzuschalten.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Schätzt das Kontextfenster anhand des **Modellnamen-Strings** in den Umgebungsvariablen `ANTHROPIC_MODEL` oder `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Bedingung | Rückgabe |
|---|---|
| Der Name enthält ein eigenständiges Wort `1m` (Regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| Der Name enthält `haiku` | `200_000` |
| Sonst (**inklusive: keine der beiden Variablen gesetzt**) | `1_000_000` |

**Der Default ist aggressiv.** Zu groß geschätzt ist kein harter Fehler: Die API weist mit `prompt is too long` zurück, `Runtime` erkennt dieses Signal
(intern `is_overflow`) und macht auf der Stelle einen Handoff — aber der Handoff dieser Generation ist die degradierte Fassung.

---

## Dokumente {#文书}

Quelle: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Vier Dataclasses, alle nach dem Muster „eine Antwort des Modells in fest definierte Abschnitte parsen und auf Platte schreiben". Gemeinsame Form:
`parse()` parst, `missing()` / `complete()` prüft auf Vollständigkeit, `to_markdown()` ist für Menschen,
`prompt_block()` für nachgelagerte Modelle, `write()` / `load()` schreibt auf Platte und liest zurück.

### `Brief` {#brief}

```python
@dataclass
class Brief:
    goal: str = ""
    accept: str = ""
    bounds: str = ""
    unknowns: str = ""
    path: Path | None = field(default=None, compare=False)
```

Das [Brief](glossary.md#需求确认书), **genau vier Abschnitte**, feste Reihenfolge
`goal` → `accept` → `bounds` → `unknowns`, die chinesischen Abschnittsnamen lauten 「目标」「验收标准」「边界」「未知与假设」.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `goal` | `str` | `""` | Ziel |
| `accept` | `str` | `""` | Abnahmekriterien |
| `bounds` | `str` | `""` | Grenzen |
| `unknowns` | `str` | `""` | Unbekanntes und Annahmen |
| `path` | `Path \| None` | `None` | Ablageort auf der Platte. `compare=False`, geht nicht in den Gleichheitsvergleich ein |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `missing` | `() -> list[str]` | Die **chinesischen Namen** der fehlenden Abschnitte, direkt anzeigbar |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Parst die vier Abschnitte aus der Modellantwort. **Entfernt zuerst umzäunte Codeblöcke**, nicht Erkanntes bleibt leer |
| `to_markdown` | `() -> str` | Vollständiges Dokument mit Metadaten im Kopf, leere Abschnitte bekommen `"(未填)"` |
| `prompt_block` | `() -> str` | Kompakte Fassung für nachgelagerte Modelle, **nur nicht leere Abschnitte**, ohne Metadaten |
| `write` | `(path: str \| Path) -> Path` | Legt das Elternverzeichnis an, schreibt, setzt `self.path` auf den aufgelösten Pfad und gibt ihn zurück |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Gibt `None` zurück, wenn die Datei nicht existiert oder ein `OSError` auftritt. **Stellt Platzhalter `"(未填)"` wieder als leeren String her** |

Parse-Regeln (hier ballen sich die Fehlerquellen):

- Beim Entfernen der Umzäunung wird **ab einem nicht geschlossenen ``` oder `~~~` alles Folgende verworfen** — gemessen: der Clarifier klebt ganzen Code in die Antwort.
  Ist die Modellausgabe abgeschnitten, lassen sich die folgenden Abschnitte gar nicht parsen, also ist `complete()` gleich `False` und das Gate schickt es zurück.
- Die Überschriften-Regex toleriert `## 目标` / `**目标**` / `目标:` / `3. 边界` und auch, dass direkt hinter der Überschrift der Fließtext beginnt.
- Die Alias-Tabelle wird nach Länge absteigend kompiliert, sonst schluckt „未知" zuerst „未知与假设".
- Kommt derselbe Abschnittsname mehrfach vor, wird **der erste mit Inhalt genommen**.
- Wer das Brief von Hand bearbeitet und dabei den Platzhaltertext `"(未填)"` aus `to_markdown()` mitkopiert, hat diesen Abschnitt weiterhin als fehlend.

### `Handoff` {#handoff}

```python
@dataclass
class Handoff:
    doing: str = ""
    decided: str = ""
    deadends: str = ""
    next: str = ""
    scene: str = ""
    step: str = ""
    path: Path | None = field(default=None, compare=False)
```

Das beim [Handoff](glossary.md#换代) geschriebene [Handoff-Dokument](glossary.md#交接书), fünf Abschnitte.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `doing` | `str` | `""` | Woran gerade gearbeitet wird. **Pflicht** |
| `decided` | `str` | `""` | Was entschieden wurde |
| `deadends` | `str` | `""` | Wege, die nicht funktionieren |
| `next` | `str` | `""` | Nächster Schritt. **Pflicht** |
| `scene` | `str` | `""` | Lage vor Ort |
| `step` | `str` | `""` | Nur für den Dokumentkopf, **geht nicht ins Parsen ein** |
| `path` | `Path \| None` | `None` | Ablageort auf der Platte |

**Pflicht sind nur die zwei Abschnitte `doing` und `next`** — hart zu fordern, dass „Wege, die nicht funktionieren" nicht leer ist, würde das Modell zum Erfinden zwingen.

| Member | Signatur | Beschreibung |
|---|---|---|
| `missing` | `() -> list[str]` | **Prüft nur die beiden Pflichtabschnitte** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Ob der Text die Degradierungsmarkierung `[降级:交接没写成]` trägt |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Nutzt den Abschnittsparser von `Brief` mit |
| `to_markdown` | `() -> str` | Leere Abschnitte bekommen `"(空)"` |
| `prompt_block` | `() -> str` | **Der Kopf sagt dem Übernehmenden ausdrücklich, dass er übernimmt**, damit er nicht rückwärts nach Hintergrund fragt |
| `write` | `(path) -> Path` | Wie `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Wie `Brief.load` |

Drei **nicht exportierte, aber semantisch entscheidende** Member im selben Modul: `is_overflow(*texts)` matcht `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed` und andere und verwandelt einen „harten Fehler" in ein „sofort Handoff"; `HANDOFF_PROMPT` ist der Prompt, mit dem
**die aktuelle Session selbst** ihren Handoff schreibt (enthält die beiden Platzhalter `{used}` und `{window}`, **das ist keine neue Rolle** —
nur sie selbst hat diesen Kontext); `degraded(step, prompt, *, why="")` setzt mechanisch einen Handoff zusammen, wenn keiner geschrieben werden konnte,
und stopft in `scene` die ersten **1200** Zeichen der ursprünglichen Aufgabe.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

Das Ziel plus Prüfliste im [Goal Guard](glossary.md#目标看守).

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `statement` | `str` | `""` | Zielformulierung |
| `checks` | `list[str]` | `[]` | Prüfliste, ein Punkt pro Zeile |
| `path` | `Path \| None` | `None` | Ablageort auf der Platte |

| Member | Signatur | Beschreibung |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Die Einträge in `checks`, die mit `[此环境无法验证:…]` markiert sind. **Schon im Moment der Zielsetzung steht fest, dass sie nie bestehen werden** |
| `missing` | `() -> list[str]` | Verlangt, dass `statement` nicht leer ist **und** `checks` nicht leer ist |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` ein Punkt pro Zeile, Marker `-` / `*` / `1.` werden automatisch entfernt |
| `to_markdown` | `() -> str` | Bei leerer Liste wird `"(空)"` geschrieben |
| `prompt_block` | `() -> str` | Kompakte Fassung für nachgelagerte Modelle |
| `write` / `load` | Wie bei `Brief` | Auf Platte schreiben und zurücklesen |
| `amend` | `(extra: str) -> Goal` | **Anhängen statt Überschreiben**: hinter `statement` wird `"\n\n(已修改)" + extra` gesetzt, Rückgabe ist `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

Das Ergebnis einer Beurteilungsrunde des [Judge](glossary.md#判定者), **genau drei Abschnitte**: 结论 / 理由 / 未通过.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`, `""` wenn nichts geparst werden konnte |
| `reason` | `str` | `""` | Begründung |
| `failed` | `list[str]` | `[]` | Die nicht bestandenen Listenpunkte |

| Member | Signatur | Beschreibung |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Ob überhaupt ein Ergebnis geparst wurde. **`ok=False` muss als „nicht erreicht" behandelt werden, niemals als erreicht** |
| `parse` | `@classmethod (text) -> Verdict` | Siehe unten |
| `feedback` | `() -> str` | Der Rücklauf an den Worker: nur „woran es fehlt", keine Lösung |

Erkennungsreihenfolge von `parse`:

1. Zuerst über die Überschriftenabschnitte 「结论」/「判定」 holen.
2. Gibt es keine Überschriftenabschnitte, wird der ganze Text nach strip mit `fullmatch(r"1|true")` → erreicht; `fullmatch(r"0|false")` → noch nicht.
3. Sonst im Ergebnistext anhand der Statuswortliste (**längere Wörter zuerst**) das erste Treffer-Wort suchen.
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」 fallen alle unter `unreachable`** —
   in der Praxis reingefallen: Zielplattform macOS, gelaufen im Linux-Container, der Judge sah sich den Quellcode-Zweig an und wertete es als bestanden.
4. Weiterhin nichts → ein isoliertes `\b1\b` suchen → erreicht, `\b0\b` → noch nicht.
5. Nichts davon trifft → `state=""`, `ok=False`.

`unreachable` und `not_yet` **sind zwei verschiedene Schlüsse**: Ersteres geht den Weg „anhalten und den Menschen fragen", nicht „noch eine Runde".

---

## hook-Ebene {#hook}

Quelle: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Diese Ebene ist die **Ausführungsgrenze** von flower: welche Tools der Main Thread nicht anfassen darf, wie überlange Ergebnisse gekürzt werden, welche Rolle in ein eigenes worktree geht —
alles wird per SDK-hook erzwungen, **nicht über den prompt**. Der Grund ist schlicht: ein prompt ist ein Vorschlag, das Modell kann ihn ignorieren. Gemessen: selbst wenn im System-prompt ausdrücklich steht „kein worktree benutzen", greift die Injektion von `isolate_guard` trotzdem (das Modell übergibt `None`, gelandet ist `'worktree'`).

Neun Exporte: fünf guard-Fabriken, die einen `HookMatcher` zurückgeben (`whitelist_guard` kann `None` liefern), ein Zusammenbauer, ein Merger, zwei Isolations-Markierungsfunktionen.
Man muss sie nicht von Hand einhängen — [`Runtime`](#runtime) montiert sie anhand der `AgentSpec` automatisch. Von Hand einhängen ist nur nötig, wenn man das SDK selbst treibt (ohne `Runtime`).

**Die Erkennung des Main Threads läuft einheitlich über eine Funktion**: `_is_main_thread(data) = not data.get("agent_id")` —
in den tool-lifecycle-hook-Daten eines subagent steckt `agent_id`, beim [Main Thread](glossary.md#主线程) nicht.
Alle guards, die „nur den Main Thread abfangen", hängen an dieser einen Bedingung.

Tool-Gruppen-Konstanten (Modulebene, nicht exportiert, bestimmen aber die Default-matcher):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Schnellübersicht: welcher guard hängt an welchem SDK-Event {#hook-速查表}

| Funktion | SDK-hook-Event | matcher | Abgefangen wird | Rückgabe | Wer installiert es |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | diejenigen aus `Bash\|Write\|Edit\|NotebookEdit`, die **nicht in `allowed_tools`** stehen | **nur der Main Thread** ruft ein verbotenes Tool auf | `permissionDecision: "deny"` + Begründung | `Runtime._attempt`, **nur wenn `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (über `tools=` änderbar) | **nur der Main Thread** legt selbst Hand an; bei `allow_glance=True` wird `Bash` durchgelassen, wenn `is_ephemeral()` zutrifft | `deny` + „schick einen subagent" | `workbench_hooks(delegate_only=True)`, **nur wenn `Runtime` einen Workbench hat** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` hat weder `cwd` noch `isolation`, und `subagent_type` wurde mit `isolated()` markiert | `permissionDecision: "allow"` + `updatedInput` (injiziert `isolation="worktree"`) | `workbench_hooks`, **nur wenn in `agents` eine markierte Rolle steckt** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` liegt innerhalb von `workbench.root` | `{}` (Seiteneffekt ist `workbench.refresh()`) | `workbench_hooks`, immer |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **String-Felder** in `tool_response` mit ≥ `threshold` Zeichen; das Lesen des spill-Verzeichnisses selbst wird durchgelassen | `updatedToolOutput` (spill + eine Zeiger-Zeile + die ersten 400 Zeichen) | `workbench_hooks`, **nur wenn `spill_threshold` truthy ist** |

**Die zentrale Folgerung aus dieser Tabelle**: bei `Runtime(workbench=False)` wird `workbench_hooks` komplett nicht installiert;
und bei einem Coordinator mit `delegate_only=True` wird auch `whitelist_guard` übersprungen — **der Main Thread hat dann keine einzige Mauer**.
Siehe die Warnung unter [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Macht `allowed_tools` für die vier handanlegenden Tools tatsächlich exklusiv.**

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `allowed` | `list[str] \| None` | Pflicht, positional | üblicherweise direkt `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | Selbstbezeichnung im Ablehnungstext. `Runtime` übergibt `spec.name` |

- **Hängt an `PreToolUse`**, matcher ist `"|".join(banned)`, `banned` = diejenigen aus `Bash` `Write` `Edit` `NotebookEdit`, die nicht in `allowed` stehen.
- Treffer heißt `permissionDecision: "deny"`, Text sinngemäß: „XX hat kein YY. **Das ist Absicht, keine vergessene Konfiguration.** Schreib das Ergebnis in den Fließtext deiner Antwort, das Framework holt es dort ab — versuch nicht, es über eine andere Schreibweise zu umgehen."
- **Fängt nur den Main Thread dieser session ab**, subagents gehen durch — deren Tools bestimmt `AgentDefinition.tools`.
- Gibt **`None`** zurück, wenn es nichts abzufangen gibt (etwa bei einer Rolle wie `worker()` mit vollem Tool-Satz); der Aufrufer entscheidet danach, ob er installiert.

**Warum es das geben muss**: `allowed_tools` ist eine **Freigabeliste ohne Nachfrage, keine exklusive Whitelist**. Zwei gemessene Belege — der Judge im Ziel-Setzen-Lauf hat 11-mal `Bash` ausgeführt; in der $0.1-Sonde konnte ein agent mit `allowed_tools=["Read"]` trotzdem `Write`/`Bash` aufrufen.
Dass `clarify()` / `judge()` „keine Schreibtools haben", **liegt also an diesem hook**, nicht an der Whitelist selbst.

Der Vorteil: er leitet sich aus `allowed_tools` ab, deshalb behält `judge(can_run=True)` automatisch `Bash` und blockt weiterhin `Write`/`Edit` — kein zusätzlicher Schalter nötig.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Main Thread legt selbst Hand an → Ablehnung, mit Wegweiser.**

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. Ein Regex-String, keine Liste |
| `allow_glance` | `bool` | `False` | bei `True` wird durchgelassen, wenn `tool_name == "Bash"` und [`is_ephemeral(command)`](#is-ephemeral) wahr ist |

- **Hängt an `PreToolUse`**, matcher ist genau `tools`.
- Ruft der Main Thread eines dieser vier Tools auf → deny, und die Begründung **sagt, was als Nächstes zu tun ist**: mit dem `Agent`-Tool einen subagent schicken, in der Aufgabe Ziel und Abnahmekriterien klar benennen und verlangen, dass lange Ergebnisse nach `.flower/artifacts/` geschrieben werden und die Antwort nur Pfad und Schlussfolgerung enthält.
- subagents gehen ausnahmslos durch.

Der Unterschied zu `whitelist_guard` ist die **Formulierung**: beide fangen dieselben Tools ab, aber dieser hier sagt „delegier das", was hier passender ist.
Deshalb bekommt eine Rolle mit `delegate_only=True` nur diesen einen; beide zusammen würden dem Modell zwei widersprüchliche Anweisungen liefern.

Das Durchlasskriterium von `allow_glance=True` und die Frage „wird das Ergebnis später gekürzt" sind **dieselbe Funktion** ([`is_ephemeral`](#is-ephemeral)) — die durchgelassene Menge muss der veralteten Menge entsprechen; ändert man die eine Seite, muss man die andere mitändern.

### `spill_guard()` {#spill-guard}

```python
def spill_guard(
    workbench: Workbench,
    *,
    threshold: int = 4000,
    tools: str = BULKY,
    main_only: bool = False,
) -> HookMatcher
```

Tool-Ergebnisse über dem Schwellwert werden **sofort ge[spillt](glossary.md#落盘)**, im Kontext bleibt nur eine Zeiger-Zeile — nicht erst compacten, wenn der Kontext voll ist.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workbench` | `Workbench` | Pflicht, positional | spill-Verzeichnis ist `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | ab wie vielen Zeichen gespillt wird |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (Default) = auch Ergebnisse von subagents werden gespillt |

- **Hängt an `PostToolUse`**, liefert `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <gekürzt>}}`.
- Der spill-Dateiname sind die ersten 16 Stellen des `sha256` des Inhalts + `.txt`; im Kontext steht stattdessen eine Zeiger-Zeile + die **ersten 400 Zeichen**.
- `updatedToolOutput` **muss die Ausgabestruktur des Originaltools beibehalten**, deshalb werden nur die zu langen **String-Felder** im dict ersetzt; **Listen werden nie angefasst** (darin können Bildblöcke stecken). Eine falsche Struktur wird abgelehnt (Original bleibt, kein Fehler).
- **Das Lesen der spill-Datei selbst muss durchgelassen werden** — sonst ist „lies sie mit `Read`" eine leere Aussage: der zurückgelesene Volltext würde erneut gespillt, Endlosschleife. Gemessen aufgetreten; das Modell hat fünf Schreibweisen durchprobiert, um es zu umgehen.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Wird etwas in den [Workbench](glossary.md#工作台) geschrieben, wird `INDEX.md` aufgefrischt; der nächste agent weiß gleich zu Beginn, dass es das gibt.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workbench` | `Workbench` | Pflicht, positional | Prüfbereich und Auffrischungsziel |

**Hängt an `PostToolUse`**, matcher `"Write|Edit"`. Liegt `tool_input["file_path"]` nach resolve innerhalb von `workbench.root`, wird `workbench.refresh()` aufgerufen. **Gibt immer `{}` zurück** — er ändert nichts, er hat nur einen Seiteneffekt.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Weist subagents je nach Rolle ein eigenes git-worktree zu und realisiert damit die [Isolation](glossary.md#隔离).

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | Pflicht, positional | Rollentabelle, um nachzusehen, ob `subagent_type` markiert ist |
| `on_inject` | `Any` | `None` | optionaler callback, aufgerufen als `on_inject(subagent_type, description)` |

**Hängt an `PreToolUse`**, matcher `"Agent"`. Injiziert wird nur, wenn drei Bedingungen gleichzeitig gelten: `tool_name == "Agent"`, `tool_input` hat **weder `cwd` noch `isolation`**, und die zu `subagent_type` gehörende Rolle wurde mit `isolated()` markiert. Dann kommt `permissionDecision: "allow"` + `updatedInput` zurück (`isolation` wird auf `"worktree"` gesetzt).

`isolation` und `cwd` schließen sich im `Agent`-Tool **gegenseitig aus** — hat das Modell selbst ein `cwd` angegeben, wird das respektiert.
„Isolieren oder nicht" ist eine **Eigenschaft der Rolle**, kein globaler Schalter und keine Entscheidung pro Delegation; einer Rolle, die keine Isolation braucht, wird kein einziges Byte hinzugefügt.

**Wer Isolation einschaltet, muss den [Workbench](glossary.md#工作台) aus dem Repo herausziehen.** Ein isolierter agent kann nicht in den geteilten checkout schreiben, also muss der Workbench per `home=` außerhalb des Repos liegen. `starter_flow(isolate=True)` nimmt `<ws>.parent/.flower-<ws.name>`, `Runtime(workbench=True)` nimmt `<run_dir>/workbench` — beide liegen außerhalb des Repos, **sind aber nicht dasselbe Verzeichnis**; nicht mischen.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Markiert eine subagent-Definition als „braucht eigenen Arbeitsbereich" und liest die Markierung wieder aus.

| Funktion | Parameter | Default | Beschreibung |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | Pflicht | die zu markierende Definition. **Zurück kommt dasselbe Objekt** |
| | `flag: bool` | `True` | positional. `False` = Markierung entfernen |
| `wants_isolation` | `agent: AgentDefinition \| None` | Pflicht | akzeptiert auch `None`, gibt dann `False` zurück |

Die Markierung ist ein per `object.__setattr__` gesetztes Python-Attribut `_flower_isolate`, **kein dataclass-Feld** — das SDK serialisiert mit `asdict()` und kennt nur deklarierte Felder, die Markierung leckt also nicht zur CLI durch (gemessen).

**Der Preis**: ein `dataclasses.replace()` auf `AgentDefinition` verliert diese Markierung, die Isolation fällt still aus.

`worker(isolate=True)` geht intern genau über `isolated()`.

### `workbench_hooks()` {#workbench-hooks}

```python
def workbench_hooks(
    workbench: Workbench,
    *,
    delegate_only: bool = True,
    spill_threshold: int | None = 4000,
    agents: dict[str, AgentDefinition] | None = None,
    allow_glance: bool = False,
) -> dict[str, list[HookMatcher]]
```

Installiert in einem Zug die hooks, die ein Workbench braucht. `Runtime._attempt` ruft genau das auf.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workbench` | `Workbench` | Pflicht, positional | wird an `index_guard` und `spill_guard` weitergereicht |
| `delegate_only` | `bool` | `True` | nur bei `True` wird `delegate_guard` installiert |
| `spill_threshold` | `int \| None` | `4000` | nur wenn truthy wird `spill_guard` installiert |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | ist **irgendeine** davon mit `isolated()` markiert, kommt `isolate_guard` dazu |
| `allow_glance` | `bool` | `False` | wird an `delegate_guard(allow_glance=)` durchgereicht |

Ergebnis:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`; gibt es markierte Rollen → zusätzlich `isolate_guard(agents)`.
- `PostToolUse`: immer `[index_guard(workbench)]`; ist `spill_threshold` truthy → zusätzlich `spill_guard(workbench, threshold=spill_threshold)`.
- **Event-Schlüssel mit leerer Liste werden entfernt**, es wird keine leere list zurückgegeben.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

Fügt mehrere hook-Konfigurationen pro Event-Name **aneinander**.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | variadisch | beliebig viele Gruppen. `None`-Gruppen werden übersprungen |

Nutzt `extend` und **dedupliziert nicht** — derselbe guard zweimal übergeben wird zweimal installiert. `Runtime` fügt damit `spec.hooks`, `workbench_hooks(...)` und `whitelist_guard` zusammen.

---

## Workbench {#工作台}

Quelle: [`flower/core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py)

### `Workbench` {#workbench}

```python
@dataclass
class Workbench:
    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
```

Das Arbeitsverzeichnis fürs Spillen: drei Unterverzeichnisse + ein Index. Der Index wird **in den System-prompt injiziert**, der agent weiß also in jeder Runde, was er zur Hand hat.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `workspace` | `Path` | Pflicht, positional | Arbeitsbereich. `__post_init__` macht resolve |
| `dirname` | `str` | `".flower"` | Name des Workbench-Verzeichnisses, relativ zu `workspace` |
| `max_index_entries` | `int` | `40` | **betrifft nur `prompt_block()`**: wie viele Einträge pro Kategorie in dem in den System-prompt injizierten Abschnitt maximal aufgelistet werden; der Rest wird zu einer Zeile „… weitere N" zusammengefasst. `INDEX.md` selbst ist nicht begrenzt und listet alles |
| `home` | `Path \| None` | `None` | wenn gesetzt, ist das der `root`, **`dirname` wird ignoriert**. Wird bei nicht-`None` ebenfalls resolved |

| Member | Signatur | Beschreibung |
|---|---|---|
| `root` | `@property -> Path` | `home`, falls gesetzt, sonst `workspace / dirname` |
| `external` | `@property -> bool` | ob `root` **außerhalb** von `workspace` liegt. Im Isolationsmodus sollte das `True` sein |
| `scripts` | `@property -> Path` | `root / "scripts"`, Skripte, die ein zweites Mal laufen sollen |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, lange Ergebnisse über 2000 Zeichen |
| `notes` | `@property -> Path` | `root / "notes"`, zentrale Entscheidungen, eine Datei pro Entscheidung |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | der Pfad, den das Modell sieht: relativ innerhalb des Arbeitsbereichs, absolut außerhalb |
| `ensure` | `() -> Workbench` | mkdir für die drei Verzeichnisse, gibt `self` zurück (verkettbar: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(Anzeigepfad, Beschreibung, Bytes)`. Rekursiv per `rglob("*")`, Dateien mit `.` am Anfang werden übersprungen |
| `refresh` | `() -> str` | schreibt `INDEX.md` neu und gibt den Inhalt zurück |
| `prompt_block` | `() -> str` | **der Abschnitt, der in den System-prompt injiziert wird**. Bewusst kurz gehalten — er ist in jeder Runde dabei |

Selbstbeschreibungsformat der Skripte: `# desc: ein Satz` innerhalb der ersten 8 Zeilen (auch `//` und `--` als Kommentarzeichen), Rückfall auf den ersten nicht-leeren Kommentar oder die erste Zeile des docstring (auf 100 Zeichen gekürzt).

Die drei Regeln, die `prompt_block()` injiziert:

1. Skripte, die ein zweites Mal laufen sollen, kommen nach `scripts/`, erste Zeile `# desc:`.
2. Ergebnisse über **2000 Zeichen** kommen nach `artifacts/`, im Dialog stehen nur Pfad und Schlussfolgerung.
3. Zentrale Entscheidungen kommen nach `notes/`, eine Datei pro Entscheidung.

Bei `external=True` ergänzt `prompt_block()` zusätzlich den Satz „greif mit absolutem Pfad darauf zu".

**Den Index erben subagents nicht.** Er läuft über das session-weite `system_prompt.append`, subagents haben aber ihren eigenen System-prompt (gemessen $0.2461). Die beiden Punkte „lange Ergebnisse nach `artifacts/`" und „wo der Workbench liegt" muss der [Coordinator](glossary.md#协调者) deshalb im [Task Brief](glossary.md#任务书) weitergeben — **das ist der einzige Kanal**, keine Redundanz.
In `WORKER_RULES` steht das **absichtlich nicht**: der echte Pfad wird von `Workbench` erzeugt, fest verdrahtet wäre er falsch.

---

## Session Store {#会话存储}

Quelle: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Drei Vererbungsstufen: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime` benutzt **immer die äußerste**, die Strategien aller drei Schichten werden über Konstruktorparameter gesteuert.

Jede Schicht macht eine Sache: Persistieren, [Trimmen](glossary.md#裁剪) nach Größe und Wert, [Prunen](glossary.md#剪除) nach „ist das ein Fehler". Trimmen und Prunen passieren beide im Moment von **`load()`** (also wenn resume die Historie zurück ins Modell füttert); an den Rohdaten in SQLite ändert sich kein Byte.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implementiert das `SessionStore`-Protokoll des SDK, drei Tabellen `entries` / `meta` / `summaries`.
Der store key ist `project_key/session_id[/subpath]` — **die transcripts von sub-agents werden über subpath unterschieden**.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `path` | `str \| Path` | Pflicht, positional | Datenbankdatei. Verbindung mit `check_same_thread=False` |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `append` | `async (key, entries) -> None` | idempotente Deduplizierung nach uuid (erst bereits Gespeichertes, dann Dubletten innerhalb des Batches). Beim Replay eines ganzen Batches **wird mtime nicht vorangetrieben und keine summary doppelt gefaltet**; nur das Haupt-transcript (`subpath is None`) nimmt an der summary teil |
| `projects` | `() -> list[str]` | die tatsächlich in der DB vorhandenen `project_key`. **Das SDK leitet ihn aus cwd ab; vor einer Abfrage damit prüfen, nicht raten** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **synchron, liest kein payload**, fragt nur eine meta-Zeile ab. Für die „Continuity am selben Pfad" — der resume einer nicht existierenden session fliegt sonst erst auf, wenn der Subprozess hochgekommen ist |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | wie groß der Kontext war, den das Modell in der letzten Runde tatsächlich gesehen hat; nichts gefunden → `0`. Scannt nur die letzten `scan` Einträge rückwärts; `input + cache_read + cache_creation` zählen alle drei (nur `input_tokens` unterschätzt massiv) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | sortiert nach seq; keine Zeilen → `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | nur Haupt-transcripts |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | listet die session-Zusammenfassungen |
| `delete` | `async (key) -> None` | beim Löschen eines Haupt-transcripts werden **die der sub-agents kaskadierend mitgelöscht**, um Waisen zu vermeiden |
| `list_subkeys` | `async (key) -> list[str]` | listet die sub-transcripts dieser session |
| `close` | `() -> None` | Verbindung schließen |

Das interne `_next_mtime` garantiert **strenge Monotonie** — `list_sessions` und die summary-sidecar teilen sich diese Uhr, sonst urteilt der staleness-Schnellpfad des SDK falsch.

### `TrimPolicy` {#trimpolicy}

```python
@dataclass
class TrimPolicy:
    keep_recent: int = 20
    min_chars: int = 2000
    spill_dirname: str = ".flower/spill"
    enabled: bool = True
```

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `keep_recent` | `int` | `20` | die letzten N `tool_result` behalten den Originaltext |
| `min_chars` | `int` | `2000` | kurze Ergebnisse lohnen das Trimmen nicht |
| `spill_dirname` | `str` | `".flower/spill"` | **relativ zu `workspace`, muss innerhalb des Arbeitsbereichs liegen** — sonst kommt das `Read` des agent nicht heran |
| `enabled` | `bool` | `True` | bei `Runtime(trim=False)` steht hier `False` |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | erzeugt die Zeiger-Zeile, die den Fließtext ersetzt |

**Die beiden spill-Verzeichnisse sind nicht dasselbe.** `spill_guard` landet in `<workbench.root>/spill/` (darf außerhalb des Arbeitsbereichs liegen); `TrimPolicy.spill_dirname` landet in `<workspace>/.flower/spill/` (**muss innerhalb des Arbeitsbereichs liegen**).
Die beiden entsprechen „sofort kürzen" und „beim resume kürzen"; die Trennung ist Absicht, nicht zusammenlegen.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Die Verfallsstrategie für Ergebnisse von [ephemeral commands](glossary.md#一次性命令).

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `enabled` | `bool` | `True` | ausgeschaltet wird gar nicht als veraltet markiert |
| `keep_recent` | `int` | `6` | die letzten N sind ausgenommen. **Deutlich kleiner als die 20 der `TrimPolicy`** |
| `max_chars` | `int` | `2000` | darüber wird übersprungen und der `TrimPolicy` zur Archivierung überlassen |
| `text` | `str` | siehe Signatur | Ersatztext, zwei Platzhalter `{cmd}` und `{age}` |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | erzeugt den Ersatztext aus `text` |

**Wirkt nur auf Ergebnisse des `Bash`-Tools**, und das Kommando muss der Whitelist der ephemeral commands entsprechen. **`Read` gehört nicht dazu** — Dateiinhalte veralten nicht in einem Maß, das in die Irre führt. Veralteter Inhalt wird **nicht gespillt**, sondern direkt weggeworfen.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Entscheidet, ob ein Bash-Kommando ein [ephemeral command](glossary.md#一次性命令) ist.
**Die Durchlassentscheidung von `delegate_guard` und die Verfallsentscheidung beim Trimmen teilen sich diese eine Funktion** — die Menge der Kommandos, die der Coordinator selbst ausführen darf, muss der Menge entsprechen, deren Ergebnisse als veraltet markiert werden. Durchlassen ohne Trimmen: ein veraltetes `git status` besetzt dauerhaft Kontext und führt zusätzlich in die Irre; Trimmen ohne Durchlassen: der Coordinator schickt für ein `ls` einen subagent, 4.3k Startkosten für ein paar Dutzend Zeichen.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `cmd` | `str` | Pflicht, positional | die vollständige Kommandozeile |

Prüfreihenfolge:

1. leer / nur Whitespace → `False`.
2. Kommandosubstitution (`$(`, Backticks, `<(`, `>(`) oder eine zustandsändernde Schreibweise trifft zu → `False`.
3. nach Abzug sicherer Umleitungen (`2>&1`, `&> /dev/null` u. ä.) immer noch `>` oder `<` enthalten → `False`.
4. nach Abzug von `&&` / `||` / `;` / `|` bleibt ein einzelnes `&` übrig (Hintergrundausführung) → `False`.
5. an `&&` / `||` / `;` / `|` zerlegen, **jedes Segment muss die Whitelist treffen**.

Die Verbgruppen der Whitelist: nur lesende `git`-Subkommandos (`status` `diff` `log` `show` `branch` `rev-parse` usw.), Verzeichnis- und Systeminfos (`ls` `pwd` `df` `du` `date` `whoami` `env` usw.), Prozesse und Container (`ps` `top` `lsof` `docker ps` `kubectl get` usw.), Dateien ansehen (`cat` `head` `tail` `wc` `stat` `find` `tree`), Pfade suchen (`which` `whereis` `command -v` `type`), Textverarbeitung (`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` usw.).

Auch wenn das Verb auf der Whitelist steht, werden diese Schreibweisen abgefangen: `xargs`, `exec`, `eval`, `source`, `tee`, `find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` und `print >` innerhalb von `awk`, `git branch -D/-d/-m`, `git * --force/--hard/--prune`.

Die erste Version hat pauschal alle zusammengesetzten Kommandos abgelehnt, **damit fiel glance in der Messung komplett aus** (alle drei Versuche des Coordinators wurden geblockt), deshalb die segmentweise Prüfung.

### `TrimmingSessionStore` {#trimmingsessionstore}

```python
class TrimmingSessionStore(SqliteSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `path` | `str \| Path` | Pflicht | Datenbankdatei |
| `workspace` | `str \| Path` | Pflicht | Bezugspunkt für das spill-Verzeichnis |
| `policy` | `TrimPolicy \| None` | `None` | ohne Angabe wird `TrimPolicy()` benutzt |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | ohne Angabe wird `EphemeralPolicy()` benutzt |

Öffentliche Attribute: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Reihenfolge in `load()`: `super().load()` → `last_report` leeren → bei `ephemeral.enabled` `expire()` → bei `policy.enabled` `trim()`. **Bei `enabled=False` entfällt der jeweilige Schritt komplett.**

| Methode | Beschreibung |
|---|---|
| `expire(entries)` | ersetzt bei veralteten zeitkritischen `Bash`-Ergebnissen **nur den Fließtext, der Block bleibt**. Das Kommando wird im `tool_use` der vorangehenden assistant-Nachricht gesucht; `isCompactSummary` / `isMeta` werden übersprungen; alles über `max_chars` wird übersprungen (übernimmt `trim`); die letzten `keep_recent` sind ausgenommen. Schreibt `last_report["expired"]` |
| `trim(entries)` | `tool_result`-Fließtexte `>= min_chars` werden nach `<workspace>/<spill_dirname>/<sha256 erste 16 Stellen>.txt` gespillt, der Blockinhalt wird durch einen Zeiger ersetzt; die letzten `keep_recent` sind ausgenommen. Schreibt `cleared` / `kept` / `chars_saved` in `last_report` |

**Getrimmt wird nur reiner Text**: `image`- / `document`-Blöcke bleiben unverändert stehen.

**Zwei strukturelle rote Linien**: der `tool_result`-**Block selbst muss bleiben**, nur der content darf ersetzt werden (fehlt einer, gibt es „Missing Tool Result Block"); `isCompactSummary`-Einträge dürfen nicht angefasst werden.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Rendert `store.last_report` zu einer chinesischen Zeile fürs UI-Log.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | Pflicht, positional | akzeptiert auch die Subklasse `PruningSessionStore` |

Drei Ausgaben: nichts passiert → `"未裁剪"`; nur Verfall → `"N 个时效性结果标记为过期"`;
sonst `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, wobei X = `chars_saved // 4`.

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    heal_orphans: bool = True
    orphan_text: str = "[这一步被打断了,没有结果。需要的话重做。]"
    keep_denials: int = 1
```

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | entfernt synthetische API-Fehlermeldungen (Reste abgerissener Verbindungen) |
| `neutralize_interrupts` | `bool` | `True` | ersetzt beim Abbruch übrig gebliebene `tool_result` durch einen neutralen Hinweis |
| `interrupt_text` | `str` | siehe Signatur | Text des neutralen Hinweises |
| `heal_orphans` | `bool` | `True` | ergänzt für verwaiste Aufrufe („`tool_use` ohne `tool_result`") ein synthetisches Ergebnis |
| `orphan_text` | `str` | siehe Signatur | Fließtext des ergänzten `tool_result` |
| `keep_denials` | `int` | `1` | behält die letzten N abgelehnten Tool-Aufrufe |

`heal_orphans` behebt, dass **nach einem Abbruch jeder resume mit 400 fehlschlägt**: der Abbruch trennt an einer Nachrichtengrenze, hinter dem gerade fliegenden `tool_use` steht dann womöglich überhaupt kein `tool_result`, die API verlangt aber Paare — diese kaputte Historie bleibt im transcript liegen und wirft danach **jeden einzelnen** resume zurück. `heal_orphans()` fügt nach der assistant-Nachricht mit dem Waisen einen `user`-Eintrag ein, der das fehlende Ergebnis nachliefert, und biegt die `parentUuid`, die vorher auf jene assistant-Nachricht zeigten, auf den eingefügten Eintrag um, damit die Kette zusammenhängend bleibt (`prune.py:95-147`). **Ergänzen statt löschen**: Waisen zu löschen erfordert ein Umhängen der Eltern-Kind-Kette der assistant-Nachricht, in derselben Nachricht können auch normale Blöcke, Text und thinking stecken — das reißt leicht etwas mit (`prune.py:195-204`).

Die Begründung für `keep_denials`: ein abgelehnter Aufruf wurde nie ausgeführt, im Ergebnis steckt keine Information, aber er belegt einiges an Platz (gemessen einmal 273 Zeichen = 93 Zeichen Ablehnungstext + 180 Zeichen **Originaltext des toten Kommandos**). Wichtiger noch: **er führt in die Irre** — gemessen hat der Coordinator, nachdem er ein paar „nicht direkt Bash verwenden" gelesen hatte, selbst das durchgelassene `git status` nicht mehr versucht; erlernte Hilflosigkeit.
**Default 1 statt 0**: die jüngste Ablehnung hindert das Modell daran, in derselben Runde dasselbe geblockte Kommando immer wieder zu versuchen.

### `PruningSessionStore` {#pruningsessionstore}

```python
class PruningSessionStore(TrimmingSessionStore):
    def __init__(
        self,
        path: str | Path,
        workspace: str | Path,
        policy: TrimPolicy | None = None,
        prune: PrunePolicy | None = None,
        ephemeral: EphemeralPolicy | None = None,
    ) -> None
```

**Der Default-store von `Runtime`.**

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `path` | `str \| Path` | Pflicht | Datenbankdatei |
| `workspace` | `str \| Path` | Pflicht | Bezugspunkt für das spill-Verzeichnis |
| `policy` | `TrimPolicy \| None` | `None` | Trim-Strategie |
| `prune` | `PrunePolicy \| None` | `None` | Prune-Strategie |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | Verfallsstrategie |

Gegenüber der Elternklasse drei zusätzliche öffentliche Attribute: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (zuerst `expire` + `trim`) → `self.prune(entries)`. `prune` macht drei Dinge:

1. **Zu alte abgelehnte Aufrufe entfernen**: erkannt über die strukturelle Markierung `toolDenialKind == "permission-rule"` der harness (zuverlässiger als das Matchen von Ablehnungstexten), die letzten `keep_denials` bleiben, bei den übrigen werden `tool_use` **und** `tool_result` gemeinsam entfernt. Stecken mehrere `tool_use` in derselben assistant-Nachricht, **wird nur der getroffene entfernt**, sonst entsteht ein „Missing Tool Result Block"; Text- und thinking-Blöcke bleiben.
2. **Synthetische API-Fehlermeldungen entfernen.** In SQLite bleiben sie unverändert erhalten, sie werden nur nicht zurückgefüttert.
3. **Beim Abbruch übrig gebliebene `tool_result` durch einen neutralen Hinweis ersetzen** — nur der Fließtext, der Eintrag bleibt.

**Die einzige strukturelle rote Linie**: das transcript ist eine einfach verkettete `parentUuid`-Liste; entfernt man einen Eintrag, müssen seine Kinder an den nächsten überlebenden Vorfahren gehängt werden.
Das interne `relink` **braucht in `entries` die vollständige Liste (inklusive der zu entfernenden)**, das Filtern erledigt es selbst — filtert der Aufrufer vorher und übergibt erst dann, reißt die Kette genau dort und die gesamte vorherige Historie ist weg (**schon passiert: fällt nicht auf, wenn die entfernten Einträge am Ende stehen, fliegt aber in der Mitte auf**).

**Die Parameterreihenfolge weicht von der Elternklasse ab**: die Elternklasse hat `(path, workspace, policy, ephemeral)`, die Subklasse `(path, workspace, policy, prune, ephemeral)` — **der vierte positionale Parameter wird von `ephemeral` zu `prune`**, positional übergeben verrutscht das still. Grundsätzlich mit Keyword übergeben.

---

## Resilienz {#韧性}

Quelle: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

Bei Netzausfall hängen bleiben und warten, statt mit Fehler auszusteigen. Vier Exporte: eine Strategie-dataclass + drei einzeln nutzbare Prüffunktionen.

### `Resilience` {#resilience}

```python
@dataclass
class Resilience:
    enabled: bool = True
    max_attempts: int = 6
    base_delay: float = 4.0
    max_delay: float = 120.0
    probe_timeout: float = 5.0
    probe_interval: float = 15.0
    max_offline_wait: float = 3600.0
    retry_unknown: bool = True
    resume_prompt: str = "上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,从中断处接着做,不要重头来过。"
```

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `enabled` | `bool` | `True` | ausgeschaltet wird kein Fehler wiederholt |
| `max_attempts` | `int` | `6` | **einschließlich des ersten Versuchs** |
| `base_delay` | `float` | `4.0` | Backoff-Basis, Sekunden |
| `max_delay` | `float` | `120.0` | Backoff-Obergrenze, Sekunden |
| `probe_timeout` | `float` | `5.0` | Timeout einer einzelnen Sonde |
| `probe_interval` | `float` | `15.0` | Wartezeit zwischen zwei Sonden |
| `max_offline_wait` | `float` | `3600.0` | maximale Wartezeit im Hängen, Default 1 Stunde |
| `retry_unknown` | `bool` | `True` | ob nicht klassifizierbare Fehler wiederholt werden |
| `resume_prompt` | `str` | siehe Signatur | was beim Weiterlaufen gesagt wird. **Enthält absichtlich keinerlei Fehlerdetails** — das Modell muss wissen „wurde unterbrochen, mach weiter", nicht ob es `ENOTFOUND` oder 503 war |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)`, multipliziert mit `0.75 + random()*0.5` (±25% Jitter) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, oder `kind == "unknown"` und `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | hängt und wartet, bis das Netz wieder da ist. Zurück → `True`, über `max_offline_wait` → `False`. `notify` ist ein `(str) -> None`-callback, wird **beim ersten Unerreichbar** und **bei der Wiederherstellung** je einmal gefeuert |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Teilt einen Fehlertext in die drei Klassen `"transient"` / `"fatal"` / `"unknown"` ein.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `text` | `str \| None` | Pflicht, positional | Originaltext der Fehlermeldung. Leer → `"unknown"` |

**Erst fatal prüfen, dann transient** — Texte wie bei 401 enthalten oft das Wort `connection`; in umgekehrter Reihenfolge wartet man sich zu Tode.

| Klasse | Was trifft |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

Host und Port, die gesondet werden; richtet sich nach `ANTHROPIC_BASE_URL`, Default `https://api.anthropic.com`;
Port default `80` (http) oder `443`.

**Bei einem selbst betriebenen Gateway muss genau dieses gesondet werden** — dass `api.anthropic.com` erreichbar ist, sagt nichts über das Gateway aus.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `host` | `str` | Pflicht, positional | Hostname |
| `port` | `int` | Pflicht, positional | Port |
| `timeout` | `float` | `5.0` | Sekunden |

**Macht nur DNS (`getaddrinfo`) + TCP-Handshake**, schickt kein HTTP, führt keine Credentials mit, **kostet nichts**. Jede Exception gilt als unerreichbar.

---

## Events und Interaktion {#事件与交互}

Quellcode: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

Ein [Event](glossary.md#事件) ist die stabile Struktur, zu der der SDK-Nachrichtenstrom flachgeklopft wird.
**Die [Interaktionsschicht](glossary.md#交互层) kennt nur `Event` und importiert keinen einzigen SDK-Typ** — das ist die Grenze, die es erlaubt, die UI zu tauschen, ohne den Kern anzufassen. Siehe [Interaktionsschicht tauschen](../guide/interaction.md).

### `Event` {#event}

```python
@dataclass
class Event:
    kind: EventKind
    text: str = ""
    tool: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def __str__(self) -> str: ...
```

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `kind` | `EventKind` | Pflicht | siehe Tabelle unten |
| `text` | `str` | `""` | Fließtext |
| `tool` | `str` | `""` | Werkzeugname, nur bei `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | strukturierte Zusatzinformation |
| `raw` | `Any` | `None` | das rohe SDK-Objekt, für den Fall, dass man tiefer graben will |

`__str__`: bei `tool_call` ist es `f"[{tool}] {text}"`, sonst `text`, und bei leerem `text` `f"<{kind}>"`.
`print(ev)` ist also direkt lesbar.

`EventKind` hat insgesamt **15** Werte:

| kind | Wer sendet | Beschreibung |
|---|---|---|
| `text` | `normalize` | Assistant-Fließtext |
| `thinking` | `normalize` | Denkblock |
| `tool_call` | `normalize` | Werkzeugaufruf. `text` ist eine Zusammenfassung aus `file_path` / `command` / `pattern`, auf 200 Zeichen gekürzt |
| `tool_result` | `normalize` | Werkzeugergebnis. `text` auf 500 Zeichen gekürzt, `payload` enthält `tool_use_id` / `is_error` |
| `task` | `normalize` | drei Arten von Task-Nachrichten. `text` ist **leer**, der Klassenname steckt in `payload["kind"]` |
| `system` | `normalize` | übrige Systemnachrichten, `text` ist der Subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, `payload` enthält `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | synthetische API-Fehlermeldung, `payload` enthält `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **Der Text ist Eingabe, nicht Modellausgabe**, geht also nicht in `StepResult.text` |
| `unknown` | `normalize` | nicht erkannt |
| `retry` | `Runtime` | Retry-Benachrichtigung |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | im payload `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | Frage, **transportiert außerdem "was der Mensch von sich aus sagt"** |

**Die letzten vier entstehen nicht in `normalize()`.**

Im `payload` aller Assistant-/User-Events steckt:

| Schlüssel | Typ | Beschreibung |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | nur vorhanden, wenn `subagent` wahr ist |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **Das ist die einzige Quelle für das [Handoff](glossary.md#换代)-Kriterium** und zugleich die Zahl, die man bei einem long-horizon Run am dringendsten sehen sollte |

**Der kind `ask` transportiert gleichzeitig "Frage" und "was der Mensch von sich aus sagt".** Bei Letzterem ist
`payload["kind"] == "mail"`, und **es gibt kein `options` / `remaining`**. Die UI muss also erst
`payload.get("kind")` prüfen und dann entscheiden, wie sie rendert, sonst hängt ein bloßer Satz als
unbeantwortete Frage fest.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Klopft eine SDK-Nachricht zu 0 bis N `Event`s flach.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `message` | `Any` | Pflicht, positional | beliebiges SDK-Nachrichtenobjekt |

Die entscheidenden Zweige:

- **Synthetische API-Fehlermeldung** (`isApiErrorMessage=True` oder `model == "<synthetic>"`) → ein einzelnes
  `Event("error", payload={"synthetic": True})`. **Das ist Absicht** — sonst landet der Abbruchtext als
  Fließtext in `StepResult.text` und wird an den nächsten Schritt weitergereicht.
- `AssistantMessage` → `kind="text"`; `UserMessage` → `kind="prompt"`.
- `ToolUseBlock` → `Event("tool_call", text=<Zusammenfassung>, tool=block.name, payload={"id", "input"})`.
- `ToolResultBlock` → `Event("tool_result", text=content[:500], payload={"tool_use_id", "is_error"})`.
- `ResultMessage` → `Event("result", text=subtype, payload={"session_id", "cost_usd", "num_turns", "is_error"})`.
- `compact_boundary` / `microcompact_boundary` → `Event("reset", payload={"trigger", "pre_tokens", "post_tokens", "micro", "subtype"})`.

### `Ask` {#ask}

```python
@dataclass
class Ask:
    id: str
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"
    answer: str = ""
```

Eine Frage an den Menschen.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `id` | `str` | Pflicht | dient beim Antworten der Zuordnung |
| `question` | `str` | Pflicht | Fragetext |
| `options` | `list[str]` | `[]` | Auswahlmöglichkeiten. Der Mensch darf auch nichts auswählen und selbst tippen |
| `asked_at` | `float` | `time.time()` | Zeitpunkt der Frage |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | Antworttext |

| Member | Signatur | Beschreibung |
|---|---|---|
| `waited_s` | `@property -> float` | wie lange schon gewartet wird |
| `event` | `(remaining: int = 0) -> Event` | liefert `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

### `HumanChannel` {#humanchannel}

```python
HumanChannel(
    *,
    on_event: Callable[[Event], None] | None = None,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    log_path: str | Path | None = None,
    amend_path: str | Path | None = None,
    over_budget_text: str = OVER_BUDGET,
    timeout_text: str = TIMEOUT,
    declined_text: str = DECLINED,
)
```

Ein **In-Process-MCP-Server** (zwei Werkzeuge) plus eine Reihe von Methoden für die UI. Das Modell sieht nur
`mcp__human__ask` und `mcp__human__inbox`. Alle Konstruktorparameter sind keyword-only.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | der Ausgang im **Push**-Modus. Wird er gesetzt, verdrahtet `Workflow.run` nichts mehr |
| `max_asks` | `int \| None` | `None` | **unbegrenzt viele Fragen**. Eine Zahl ist ein hartes Kontingent, `0` = keine Fragen erlaubt (vollautomatisch / CI). Bei Überschreitung **weist das Werkzeug direkt ab, ohne zu blockieren** |
| `timeout_s` | `float \| None` | `1800.0` | 30 Minuten. `None` = ewig warten; **`<= 0` = gar nicht warten, alle Fragen laufen sofort ins Leere** |
| `log_path` | `str \| Path \| None` | `None` | Fragen und Antworten werden **angehängt** auf Platte geschrieben, belegen also keinen Kontext |
| `amend_path` | `str \| Path \| None` | `None` | Was der Mensch während des Runs sagt, wird an diese Datei angehängt (üblicherweise der Brief). **Ohne Persistierung überlebt es die Schrittgrenze nicht** — der nächste Schritt ist eine neue Session und liest nur das eingefrorene Dokument |
| `over_budget_text` | `str` | Modulkonstante | Text, der bei Überschreitung an das Modell zurückgeht |
| `timeout_text` | `str` | Modulkonstante | Text, der bei Timeout an das Modell zurückgeht |
| `declined_text` | `str` | Modulkonstante | Text, der beim Überspringen an das Modell zurückgeht |

Öffentliche Attribute: die acht gleichnamigen Konstruktorparameter, dazu `asks: list[Ask]`, `mail: list[Mail]`,
`ui_errors: list[str]` (**hier landen Exceptions aus UI-Callbacks, ohne den Run abzubrechen**).

| Member | Signatur | Beschreibung |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | direkt an `AgentSpec.mcp_servers` weiterreichen. **Der Schlüsselname muss mit dem Servernamen übereinstimmen**, deshalb liefert die Methode beides zusammen |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | wartet auf den Menschen. **Wirft außer `CancelledError` nie eine Exception** — dass niemand antwortet, ist auch eine Antwort, unterschieden über `ask.state` |
| `send` | `(text: str) -> Mail \| None` | der Mensch sagt von sich aus etwas. **Aus jedem Thread aufrufbar.** Unterbricht den Agent nicht; ruft intern automatisch `amend()` |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | hängt an `amend_path` an. Rückgabe: ob tatsächlich geschrieben wurde (kein Pfad konfiguriert, leerer Text oder `OSError` ergeben `False`) |
| `pending_mail` | `() -> list[Mail]` | noch nicht abgeholte Mails |
| `remaining` | `@property -> int` | wie viele Fragen noch möglich sind. **Bei `max_asks=None` ist der Rückgabewert `-1`**, weder 0 noch unendlich |
| `pending` | `() -> list[Ask]` | aktuell auf Antwort wartende Fragen |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | für den **Pull**-Modus. Bei Timeout `None`, bei Cancel wird geworfen |
| `answer` | `(ask_id: str, text: str) -> bool` | antworten. `False` = diese Frage wartet nicht mehr (Timeout / bereits beantwortet) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | überspringen, das Modell entscheidet selbst |
| `transcript` | `() -> str` | das Frage-Antwort-Protokoll als Markdown |

**Eine der beiden Abholarten wählen**: **Push** — `HumanChannel(on_event=...)` konstruieren; **Pull** — `await channel.next_ask()`.
`Workflow.run` verdrahtet nur automatisch, wenn `channel.on_event is None` ist; wer selbst etwas übergibt, wird also nicht überschrieben.

**Thread-übergreifend**: `answer` / `decline` / `send` laufen intern über `loop.call_soon_threadsafe`;
ein Aufruf direkt aus dem Web-Backend oder dem TUI-Eingabethread ist der Normalfall.

Die drei "0 / None"-Bedeutungen sind jeweils verschieden, nicht verwechseln: `max_asks=None` = unbegrenzt, `max_asks=0` = keine Fragen erlaubt;
`timeout_s=None` = ewig warten, `timeout_s<=0` = sofortiger Timeout; `remaining` ist bei `max_asks=None` gleich `-1`.

`Mail` wird nicht exportiert, taucht aber in Rückgabewerten auf: ein Dataclass mit den Feldern `id` / `text` / `sent_at` / `taken`.

---

## Lineage {#血缘}

Quellcode: [`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

Hält prozessübergreifend fest, welcher Schritt welche Session verwendet hat; die [Continuity](glossary.md#接续) findet darüber, wie weit der letzte Lauf gekommen ist.
Die Datei ist `<run_dir>/lineage.json`.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `path` | `Path` | Pflicht | Pfad der Lineage-Datei |
| `workspace` | `Path` | Pflicht | Workspace. `__post_init__` löst ihn auf |
| `steps` | `dict[str, str]` | `{}` | Schrittname → `session_id` |
| `woke` | `int` | `0` | wie oft geweckt wurde |

| Member | Signatur | Beschreibung |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | liest `<run_dir>/lineage.json`. **Existiert die Datei nicht, ist sie unlesbar oder passt das Feld `workspace` nicht, kommt ausnahmslos ein leeres Objekt zurück, kein Fehler** |
| `remember` | `(step: str, session_id: str) -> None` | merkt sich die Zuordnung und **schreibt sofort auf Platte**. Leerer step oder leere sid: sofortiger Rücksprung |
| `bump` | `() -> int` | Weckzähler +1, auf Platte schreiben, neuen Wert zurückgeben (beim ersten Lauf `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **verschiebt** die Lineage-Datei plus `extra` nach `<into>/<YYYYmmdd-HHMMSS>/` und setzt `steps` / `woke` zurück. **Verschieben, nicht löschen** |

Das Schreiben läuft über atomares `tmp.replace(path)`; `OSError` wird still geschluckt — ein fehlgeschlagener Schreibvorgang darf den Run nicht mitreißen.

**`workspace` ist eine Wache**: Der `project_key` des SDK wird aus dem Workspace-Pfad abgeleitet; ist das Verzeichnis wegkopiert worden, findet man die alte `session_id` nicht mehr,
also gilt ein nicht passender Pfad als nicht vorhanden.

Wenn `Workflow.run` die Lineage lädt, prüft es jeden Eintrag einzeln mit `runtime.has_session(sid)` darauf, ob er noch in der Datenbank liegt, und benutzt nur die lebenden —
die Lineage-Datei kann `sessions.db` überleben.

---

## Minimale lauffähige Beispiele {#示例}

Alle fünf Abschnitte laufen direkt. Voraussetzung: `claude-agent-sdk` installiert, `ANTHROPIC_API_KEY` oder `ANTHROPIC_AUTH_TOKEN` verfügbar
(sonst wirft bereits `Runtime(...)` beim Konstruieren ein `RuntimeError`).

### Ein Agent, ein Schritt {#示例-单-agent}

Minimalgerüst: einen `AgentSpec` deklarieren, ein `Runtime` bauen, `await rt.run(...)`, `StepResult` auslesen.

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime

spec = AgentSpec(
    name="reader",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob", "Grep"],
    max_turns=4,
)


async def main() -> None:
    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        r = await rt.run(spec, "读 README.md,一句话说它是干什么的。",
                         on_event=lambda ev: print(ev))
        print(f"ok={r.ok} session={r.session_id} ${r.cost_usd:.4f} {r.duration_s}s")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

Die Parameter von `Runtime` sind **allesamt keyword-only**; bei `rt.run()` sind `spec` und `prompt` positional, der Rest keyword-only.
`AgentSpec` hat als Default `allowed_tools=["Read", "Glob", "Grep"]` und `delegate_only=False`,
also hängt `Runtime` automatisch [`whitelist_guard`](#whitelist-guard) davor und blockt `Bash`/`Write`/`Edit`/`NotebookEdit` komplett.

### Coordinator + Worker {#示例-协调}

Ein [Coordinator](glossary.md#协调者), der nicht selbst Hand anlegt, mit einem [Worker](glossary.md#执行者), der arbeitet.
Das ist die erste Ebene, auf der flower Kontext spart.

```python
import asyncio
from pathlib import Path

from flower import Runtime, coordinator, worker


async def main() -> None:
    analyst = worker(
        "分析文件内容:统计、查找、比对。要真读文件、跑命令的活派给它。",
        "你负责在 data/ 下做文本分析。用命令行完成,不要手工估算。",
        tools=["Read", "Write", "Bash", "Glob", "Grep"],
    )
    boss = coordinator(
        "主控",
        "目标:摸清 data/ 下几个文件的规模。做完给一句话结论。",
        {"分析员": analyst},
        max_turns=14,
        max_budget_usd=1.5,
    )

    # workbench=True ist Pflicht: delegate_guard hängt in workbench_hooks,
    # ohne Workbench hält kein einziger Hook das Bash/Write des Coordinators auf.
    rt = Runtime(workspace=Path("."), run_dir="runs", workbench=True)
    try:
        r = await rt.run(boss, "统计 data/ 下每个 .txt 的行数和总字符数,告诉我哪个最大。",
                         on_event=lambda ev: None)
        print(f"ok={r.ok} turns={r.num_turns} ${r.cost_usd:.4f}")
        print(r.text)
    finally:
        rt.close()


asyncio.run(main())
```

Die ersten beiden Parameter von `worker()` sind positional: `description` (damit der Coordinator auswählt) und `prompt` (dessen System-Prompt,
an den `WORKER_RULES` automatisch angehängt werden). Bei `coordinator()` sind die ersten drei positional: `name`, `instructions`, `workers`.

### Einen eigenen Workflow schreiben {#示例-workflow}

Zwei Schritte, wobei der zweite das Ergebnis des ersten in seinen eigenen Prompt injiziert — billig, isoliert, keine geteilte Session.

```python
import asyncio
from pathlib import Path

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([
        # Neue Session: bekommt nur, was im Prompt steht
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Neue Session + Ergebnis des vorigen Schritts im Prompt (billig, verhindert Verschmutzung)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Wer in derselben Session weiterreden will, schreibt resume_from="造句"; zum Verzweigen zusätzlich fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (wenn kein reduce gesetzt ist)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # bei on_fail="stop": in welchem Schritt es scheiterte


asyncio.run(main())
```

Die ersten drei Felder von `Step` (`name` / `spec` / `prompt`) sind positional, `steps` bei `Workflow` ebenfalls.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` positional, die beiden Callbacks keyword-only.
**Achtung: `continuous=True` ist der Default**: Läuft dieselbe Kombination aus `run_dir` und `workspace` ein zweites Mal,
reden auch Schritte mit `resume_from=None` in der Session des letzten Laufs weiter.

### Eine Goal Guard einziehen {#示例-目标}

Erst lässt man den [Judge](glossary.md#判定者) Ziel und Prüfliste festlegen, dann lässt man den arbeitenden Schritt das Verdict akzeptieren —
wer durchfällt, macht mit dem Feedback eine neue Runde, höchstens drei.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = vollautomatisch: alle Fragen laufen sofort ins Leere, kein vorgetäuschtes Warten
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds ist die **Gesamtzahl der Runden**: rounds=3 → retries=2 → höchstens drei Arbeitsrunden
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # Der Prompt von goal_step liest ctx["确认需求"] (Default von brief_key).
        # Ohne clarify_step muss man selbst etwas hineingeben, sonst sieht er nur "(没有确认书)".
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY: Goal-Objekt
    print(ctx["_verdict"])     # VERDICT_KEY: letztes Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY: wie viele Runden gelaufen sind
    print(ctx.get("_aborted")) # Grund des StepAbort (unerreichbar und niemand antwortet)


asyncio.run(main())
```

`with_goal` ersetzt nur `gate` / `on_reject` / `retries`, alle übrigen Felder werden per `dataclasses.replace` unverändert übernommen.
Der Judge läuft in einer **eigenen Session**: `gate` ruft intern separat `rt.run(judger, ..., step_name=f"{label}#{轮次}")` auf,
`resume` ist immer `None`.

### Die Interaktionsschicht austauschen {#示例-交互层}

Um das Terminal gegen Web / TUI / HTTP zu tauschen, muss man genau zwei Dinge ändern: die Funktion, die `Event` rendert, und die Coroutine, die Fragen abholt.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """把 Event 渲染成你自己的 UI —— 这是唯一需要换的东西。"""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ handoff/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ retry: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # kind == "ask" und kein mail: übernimmt der answerer weiter unten (Pull-Modus)


async def answerer(ch: HumanChannel) -> None:
    """拉式取提问。换成 Web 后端 / HTTP 服务时,这个协程是唯一要改的地方。"""
    while True:
        ask = await ch.next_ask()          # ohne timeout wird endlos gewartet
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # oder ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime benutzt die Workbench, die der Workflow schon gebaut hat — keine zweite zusammenbasteln
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push und Pull: **eines von beiden wählen**. Push heißt `HumanChannel(on_event=...)` konstruieren, Pull heißt `await channel.next_ask()`.
`Workflow.run` verdrahtet nur automatisch, wenn `channel.on_event is None` ist; wer selbst ein `on_event` übergibt, wird also nicht überschrieben.
`answer()` / `decline()` / `send()` / `interrupt()` **sind alle aus anderen Threads aufrufbar**.

---

## Fallstricke und häufige Fehler {#陷阱}

Sortiert nach der Reihenfolge, in der man hineintritt, nicht nach Modul. Jeder Punkt hat eine gemessene Quelle.

### Aufbau {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = im Main Thread steht keine einzige Wand.**
   `delegate_guard` wird nur mit Workbench installiert, und `whitelist_guard` wird durch `delegate_only=True` übersprungen.
   Wer einen Coordinator benutzt, schaltet die Workbench ein. Siehe [Runtime](#runtime).
2. **Es gibt zwei Orte für die Workbench, nicht falsch zusammensetzen.** `Runtime(workbench=True)` landet in `<run_dir>/workbench`;
   `Workbench(ws)` liegt per Default in `<ws>/.flower`. Wer `brief_path` selbst zusammenbaut, hält sich an das Zweite,
   sonst **wird der Brief in Verzeichnis A geschrieben, während der injizierte Index Verzeichnis B scannt — ohne jede Fehlermeldung.**
   Richtig: Der Workflow macht selbst `Workbench(...).ensure()`, hängt das an `Workflow.workbench`
   und übergibt **dasselbe Objekt** an `Runtime(workbench=wb)`.
3. **`allowed_tools` ist keine exklusive Whitelist, sondern eine Liste ohne Freigabepflicht.** Das Modell kann weiterhin Werkzeuge aufrufen, die nicht darin stehen.
   Dass `clarify()` / `judge()` "keine Schreibwerkzeuge haben", beruht auf dem Hook [`whitelist_guard`](#whitelist-guard).
   Und `coordinator()` hat per Default `permission_mode="acceptEdits"` — wer diesen Wert an
   `clarify()` / `judge()` durchreicht, hat den Schutz verloren.
4. **`disallowed_tools` gilt sessionweit** und sperrt gleichnamige Werkzeuge auch in Subagents.
5. **Der Workbench-Index erreicht keine Subagents.** "Lange Ausgaben nach `artifacts/` schreiben" muss der Coordinator im Task Brief weitergeben,
   das ist der einzige Kanal.
6. **`Runtime(...)` wirft ohne Credentials schon in der Konstruktionsphase ein `RuntimeError`**, nicht erst bei `run()`.
7. **`Runtime.run_id` muss pro Instanz eindeutig sein.** Die `manifest.json` dedupliziert über das Feld `run`; kollidieren zwei ids,
   löscht der später Schreibende die Zeilen des anderen, weil er sie für "meine letzten" hält.

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` ist der Default**, `resume_from=None` bedeutet nicht "brandneue Session".
   Wer jedes Mal neu anfangen will, setzt explizit `continuous=False`. **Einen Schrittnamen zu ändern, kappt die Lineage.**
9. **`with_goal(rounds=N)` ist die Gesamtzahl der Runden, nicht die Zahl zusätzlicher Runden**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` schreibt kein `ctx[step.name]`** — ein nachgelagertes `lambda ctx: ctx["某步"]` läuft in einen `KeyError`.
    Wer mit unvollständigem Ergebnis weitergehen will, nimmt `on_fail="continue"`.
11. **Zeigt `resume_from` auf einen nicht gelaufenen oder gescheiterten Schritt, wird ein `ValueError` geworfen**, es wird nicht still übersprungen.
12. **`Step.reduce` muss synchron sein; `gate` / `when` / `on_reject` dürfen async sein.**
13. **`fork=True` ohne `resume` ist still wirkungslos.** `Workflow` übergibt nie ein `resume_at`;
    wer nach Nachrichten zurückrollen will, muss `Runtime.run` direkt aufrufen.
14. **Wer `Runtime` selbst steuert, muss `on_session` vor dem gate abhängen**, sonst wird die Session des Judge in die Lineage
    des Arbeitsschritts geschrieben. `Workflow` sichert das mit `try/finally` ab.
15. **`step_name` bestimmt die Schlüssel im Manifest und in der Lineage.** `Workflow` hängt `#retryN` / `#roundN` an,
    der Judge hängt `#轮次` an — **Namen mit Suffix gehen nicht in die prozessübergreifende Lineage**, und genau so wird unter anderem umgesetzt, dass "der Judge immer eine neue Session ist".

### Rollen {#陷阱-角色}

16. **`clarify(max_turns=<kleine Zahl>)` macht "unbegrenzt viele Fragen" zur leeren Behauptung** — jede Frage ist eine Runde.
17. **`goal_step()` hat keinen Parameter `can_run`**, `can_run=True` geht nur über `**spec_kw`.
    Ohne ihn bekommt der zielsetzende Judge kein `Bash`, und die Regel aus `JUDGE_RULES`, sich erst klar zu machen, in welcher Umgebung man ist, lässt sich nicht ausführen.
18. **`judge(can_run=True)` erlaubt dem Judge, den Workspace zu verändern** — `whitelist_guard` leitet sich aus `allowed_tools` ab,
    wer `Bash` gibt, lässt `Bash` durch (`Write`/`Edit` bleiben geblockt, aber `Bash` selbst kann Dateien schreiben). Wer absolute Neutralität will, lässt es aus.
19. **`worker(isolate=True)` setzt voraus, dass der Workspace ein git-Repository ist**, sonst meldet das `Agent`-Werkzeug direkt
    `"not in a git repository"` und degradiert nicht still. Außerdem ist die Isolationsmarkierung ein Python-Attribut:
    **ein `dataclasses.replace()` auf `AgentDefinition` verliert sie.**
20. **Konstruiert man `AgentDefinition` direkt, sind die Parameter in camelCase**: `maxTurns`, `permissionMode`.
    `worker()` hat die Umsetzung bereits erledigt.

### Handoff und Kontext {#陷阱-换代}

21. **Ist Handoff eingeschaltet, wird auto-compact zwangsweise abgeschaltet, ohne Auffangnetz.** Der Schritt, der das Handoff-Dokument schreibt, braucht also einen Degradationspfad.
    Wer auto-compact behalten will, setzt `AgentSpec.compact` explizit.
22. **Ein zu klein konfiguriertes `HandoffPolicy.window` führt zu endlosen Handoffs und verbrennt Geld.** Die einzige Bremse ist `max_generations=8`.
    Am anderen Ende gibt **`default_window()` auch dann `1_000_000` zurück, wenn beide Umgebungsvariablen ungesetzt sind** —
    ist der Wert zu groß geschätzt, fängt `is_overflow()` das ab (es wird ein degradiertes Handoff), das ist kein harter Fehler, aber das Handoff dieser Generation ist degradiert.
23. **Ohne Workbench wird das Handoff nicht auf Platte geschrieben.** Das Dokument geht trotzdem per Prompt an den Nachfolger, aber der Mensch findet es hinterher nicht mehr.

### Speicher {#陷阱-存储}

24. **`Runtime(trim=False)` (Default) heißt nicht "es wird nichts aufgeräumt".** Der Store ist immer ein `PruningSessionStore`,
    `trim=False` schaltet nur das Kürzen großer Ergebnisse ab; **Abbruchreste entfernen, abgelehnte Aufrufe entfernen, Unterbrechungsreste neutralisieren und Zeitkritisches ablaufen lassen passieren weiterhin.**
25. **Die beiden Spill-Verzeichnisse sind nicht dasselbe**: `spill_guard` landet in `<workbench.root>/spill/`,
    `TrimPolicy.spill_dirname` in `<workspace>/.flower/spill/` (muss innerhalb des Workspace liegen).
26. **Der vierte positionale Parameter von `PruningSessionStore.__init__` ist `prune`, nicht `ephemeral`**,
    anders als in der Basisklasse. Positional übergeben verschiebt still alles um eins.

### Dokumente und Interaktion {#陷阱-文书}

27. **Lässt sich aus einem `Verdict` kein Schluss parsen, ist `state=""` und `ok=False` — das darf niemals als erreicht gewertet werden.**
    Außerdem fallen "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" alle unter `unreachable`
    und lösen den Pfad "anhalten und den Menschen fragen" aus, nicht "noch eine Runde".
28. **`Brief.parse` verwirft bei einem nicht geschlossenen Code-Fence den gesamten Inhalt danach** — wird die Modellausgabe abgeschnitten,
    lassen sich alle folgenden Abschnitte nicht mehr parsen, `complete()` ist `False`, und das gate schickt es zurück.
29. **`Brief.load` behandelt `"(未填)"` als leer.** Wer beim manuellen Editieren des Briefs den Platzhaltertext stehen lässt, dessen Abschnitt gilt weiterhin als fehlend.
30. **Die drei "0 / None" im `HumanChannel` bedeuten jeweils Verschiedenes**: `max_asks=None` unbegrenzt, `max_asks=0` keine Fragen erlaubt;
    `timeout_s=None` ewig warten, `timeout_s<=0` sofortiger Timeout; `remaining` gibt bei `max_asks=None` **`-1`** zurück.
31. **`Event("ask")` transportiert zugleich Fragen und das, was der Mensch von sich aus sagt**, Letzteres mit `payload["kind"] == "mail"`. Die UI muss das zuerst prüfen.
32. **`Workflow.run` verdrahtet nur, wenn `channel.on_event is None` ist** —
    wer `HumanChannel(on_event=...)` selbst konstruiert, bekommt die Frage-Events nicht zusätzlich am `on_event`-Ausgang des Workflows.
