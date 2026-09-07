# Python API

Diese Seite erfasst erschöpfend die **62 öffentlichen Symbole** in `flower`s Top-Level-`__all__`:
Signaturen, Parameter, Defaultwerte, Semantik, öffentliche Attribute und Methoden. Nach dem
Lesen musst du den Quellcode nicht mehr öffnen, um Parameter nachzuschlagen.

Gegliedert ist es nach **worum es dir geht**, nicht nach Moduldateien — willst du wissen, „wie
hindere ich den [Coordinator](glossary.md#协调者) daran, selbst Hand anzulegen", geh zur
[Hook-Ebene](#hook); willst du wissen, „wie kommt das Ergebnis des vorigen Schritts in den
nächsten", geh zum [Workflow](#流程). Terminologie durchgehend nach dem
[Glossar](glossary.md).

Version `0.1.0`, Abhängigkeit `claude-agent-sdk>=0.2.152`. Alle Signaturen entsprechen dem
Quellcode wörtlich.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # ein einziger Top-Level-Import
```

## Was auf dieser Seite steht {#索引}

| Worum es geht | Symbole |
|---|---|
| [einen Agent laufen lassen](#运行时) | `Runtime` `StepResult` |
| [mehrere Schritte verketten](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [eine Rolle bauen](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [eine Agent-Definition von Hand schreiben](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [strukturierte Dokumente](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Tools abfangen, Ergebnisse trimmen, Isolation aufteilen](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [das Arbeitsverzeichnis zum Spillen](#工作台) | `Workbench` |
| [wie und was die Session speichert](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [was tun bei Netzausfall](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [die UI austauschen](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [prozessübergreifend an letztes Mal anknüpfen](#血缘) | `Lineage` |

## Sechs Defaultwerte, die beißen {#危险默认值}

Diese sechs sind kein Beiwerk, sondern die sechs häufigsten Ausrutscher. Jeder ist im
zugehörigen Abschnitt vollständig erklärt.

| Defaultwert | Folge | Näheres |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | `Bash`/`Write`/`Edit` im Main-Thread haben **keinen einzigen Hook** | [Runtime](#runtime) |
| `Runtime(handoff=True)` | erzwingt am Spec `CompactPolicy(mode="no_summary")`, also `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | ein Schritt mit `resume_from=None` knüpft dennoch prozessübergreifend an jene letzte Session an | [Workflow](#workflow) |
| `build_options(fork=True)` ohne `resume` | still wirkungslos, kein Fehler | [build_options](#build-options) |
| `clarify(max_turns=<kleine Zahl>)` | macht „unbegrenzt oft fragen" zur leeren Phrase — jede Frage ist eine Runde | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | session-weit, sperrt die Subagents gleich mit | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Quellcode: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` ist der Ausführungskern. Es hält den Workspace, den [Session-Store](glossary.md#会话存储),
die [Workbench](glossary.md#工作台), die [Resilience](glossary.md#韧性)-Strategie und die
[Handoff](glossary.md#换代)-Strategie und bietet nach außen nur ein einziges Verb: `run` einen
Schritt. Wiederholung, Weiterlauf nach Unterbrechung, Handoff bei vollem Kontext — all das
geschieht innerhalb dieses einen Aufrufs.

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

Die Konstruktorparameter sind **allesamt keyword-only** (`*` ganz vorne), `workspace` ist
Pflicht.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workspace` | `str \| Path` | Pflicht | Das `cwd` des Agents. Wird bei der Konstruktion resolved und `mkdir(parents=True, exist_ok=True)`. Der `project_key` des SDK leitet sich daraus ab — ist das Verzeichnis wegkopiert, findet man die alte `session_id` nicht mehr |
| `run_dir` | `str \| Path` | `"runs"` | Ort für `sessions.db`, `manifest.json`, `lineage.json` und, bei `workbench=True`, die Default-Workbench. Wird ebenfalls resolved und ge-mkdir-t |
| `portable` | `bool` | `True` | Durchgereicht an `build_options(portable=)`, also `setting_sources=[]`: liest weder das `~/.claude/` des Hosts noch das `.claude/` des Projekts. Siehe [Portabilität](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | Eine Instanz wird direkt verwendet; bei `bool` dann `TrimPolicy(enabled=bool(trim))`. **Abschalten heißt nur, große Ergebnisse nicht zu trimmen, das Pruning läuft trotzdem** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Gleiche Konvertierungsregel wie oben. Bildet mit `coordinator(glance=True)` ein Paar — lässt du den Main-Thread `git status` fahren, muss gesichert sein, dass dieses Ergebnis verfällt |
| `keep_denials` | `int` | `1` | Wird an `PrunePolicy(keep_denials=)` gereicht. Behält die letzten N abgelehnten Tool-Aufrufe, ältere werden samt Aufruf und Ergebnis entfernt |
| `workbench` | `Workbench \| bool` | `False` | Eine Instanz wird direkt verwendet; bei `True` wird `Workbench(workspace, home=run_dir / "workbench")` gebaut (**liegt per Default außerhalb des Workspace**). Danach sofort `refresh()` |
| `spill_threshold` | `int \| None` | `4000` | Ab wie vielen Zeichen ein Tool-Ergebnis [gespillt](glossary.md#落盘) wird. `None` oder `0` = kein `spill_guard` |
| `resilience` | `Resilience \| bool` | `True` | Gleiche Konvertierungsregel |
| `handoff` | `HandoffPolicy \| bool` | `True` | Gleiche Konvertierungsregel |

**Der Session-Store ist fest verdrahtet**: stets
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
Die Konstruktorparameter **bieten keinen** Einstieg zum Backend-Wechsel — willst du wechseln,
konstruiere selbst `AgentSpec` + `build_options(session_store=...)` oder überschreibe nach der
Konstruktion `rt.store`.

Die letzten beiden Schritte der Konstruktion sind `load_dotenv()` und `check_credentials()`,
**bei einem Fehler in Letzterem `raise RuntimeError`**. Fehlen die Credentials, kracht es schon
in der Konstruktionsphase, nicht erst bei `run()`.

!!! warning "`workbench=False` + `coordinator()` = keine einzige Mauer für den Main-Thread"
    `delegate_guard` wird nur in `workbench_hooks` installiert, und `workbench_hooks` wird nur
    aufgerufen, wenn `self.workbench is not None`; `whitelist_guard` wiederum wird durch
    `if not spec.delegate_only` übersprungen. `coordinator()` aber setzt konstant
    `delegate_only=True` und gibt per Default `glance=True` an `Bash`.

    **Fazit: Kombinierst du den Coordinator mit `Runtime(workbench=False)`, fängt kein einziger
    Hook sein `Bash`/`Write`/`Edit` ab.** Nutzt du `coordinator()`, dann schalte die
    `workbench` ein — `Runtime(..., workbench=True)` oder gib eine `Workbench`-Instanz.

!!! warning "`handoff=True` (Default) schaltet Auto-Compact zwangsweise ab"
    In `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`,
    im Kindprozess ist das `DISABLE_AUTO_COMPACT=1`. Der Grund: sind beide Mechanismen zugleich
    an, lässt sich nicht sagen, wer das Zurückgehen des Kontexts verursacht hat.

    **Der Preis: der Schritt, der das Handoff schreibt, muss einen Degradierungspfad haben**
    (`handoff.degraded`), denn ein Compact als Auffangnetz gibt es nicht mehr. Willst du
    Auto-Compact behalten, gib `AgentSpec.compact` explizit an (hat das Spec es selbst gesetzt,
    wird das respektiert und nicht überschrieben).

#### Öffentliche Attribute {#runtime-属性}

| Attribut | Typ | Beschreibung |
|---|---|---|
| `workspace` | `Path` | Der resolvete Workspace |
| `run_dir` | `Path` | Das resolvete Run-Verzeichnis |
| `portable` | `bool` | Unverändert gespeichert |
| `store` | `PruningSessionStore` | Der Session-Store. Ein Backend-Wechsel geht nur durch Überschreiben nach der Konstruktion |
| `resilience` | `Resilience` | Die normalisierte Instanz |
| `handoff` | `HandoffPolicy` | Die normalisierte Instanz |
| `workbench` | `Workbench \| None` | Bei `workbench=False` ist es `None` |
| `spill_threshold` | `int \| None` | Unverändert gespeichert, in `_attempt` an `workbench_hooks` gereicht |
| `results` | `list[StepResult]` | Jeder in diesem Prozess gelaufene Schritt, der Reihe nach angehängt |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Muss pro Instanz eindeutig sein** — `manifest.json` dedupliziert nach dem Feld `run`; kollidieren zwei ids, hält der später Schreibende die Zeile des anderen für seine eigene vom letzten Mal und löscht sie |
| `on_session` | `Callable[[str], None] \| None` | Ruft **sofort** zurück, sobald eine neue `session_id` da ist, Default `None`. **Sollte nur über die eine Zeile `runtime.run` gelegt werden** — der [Judge](glossary.md#判定者) nutzt dasselbe `Runtime`; hängt es während der Gate-Phase noch dran, schreibt es die Session des Judge in die [Lineage](glossary.md#血缘) des arbeitenden Schritts |

Klassenkonstanten: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`,
`INTERRUPT_NOTE` (ein Absatz, der beim Weiterlauf nach Unterbrechung hinter den Worten des
Menschen angehängt wird und erklärt, dass „ein damals fliegender Tool-Aufruf, der interrupted
zurückgibt, ein normaler Nebeneffekt der Unterbrechung ist, kein Umgebungsfehler").

#### Öffentliche Methoden {#runtime-方法}

| Methode | Signatur | Beschreibung |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Einen Schritt laufen lassen. Siehe unten |
| `interrupt` | `(message: str = "") -> None` | Fordert die Unterbrechung der aktuellen Runde an. **Aus jedem Thread aufrufbar**. Kooperativ: trennt sauber an der **Nachrichtengrenze**, kein hartes Abbrechen. Leerer String = nur unterbrechen, ohne etwas zu sagen |
| `rescue` | `() -> None` | Bringt die Abrechnung vor dem harten Kill so weit wie möglich in Ordnung, wird vom `SIGHUP`/`SIGTERM`-Handler aufgerufen. Schreibt auch den gerade fliegenden Schritt ins Manifest, `error="killed-by-signal"`. Macht nur kleine synchrone Schreibvorgänge |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | In `str(workspace.resolve())` werden `/`, `_`, `.` allesamt durch `-` ersetzt. **Vom SDK aus dem cwd abgeleitet, vom Aufrufer nicht angebbar** |
| `has_session` | `(session_id: str) -> bool` | Ist diese id unter **diesem Workspace** noch auffindbar. Synchron, liest kein Payload |
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
| `spec` | `AgentSpec` | Pflicht, Positionsargument | Die Deklaration des zu laufenden Agents |
| `prompt` | `str` | Pflicht, Positionsargument | Die Worte dieser Runde |
| `step_name` | `str \| None` | `None` | Der Schlüssel, der in `StepResult.step`, Manifest und Lineage landet. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | An dieser `session_id` weiterlaufen |
| `fork` | `bool` | `False` | Zweigt eine neue Session ab, ohne die ursprüngliche zu verschmutzen. **Wirkt nur, wenn `resume` truthy ist** |
| `resume_at` | `str \| None` | `None` | Ab einer bestimmten Nachricht weiterlaufen (Rollback). Ebenfalls **nur wirksam, wenn `resume` truthy ist** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Der Event-Ausgang, siehe [`Event`](#event) |

Zu Beginn jedes Schritts wird der Kontextpegel auf null gesetzt (`self._ctx, self._warned = 0, False`).
Danach folgt eine Schleife mit vier Ausgängen:

1. **Erfolg** → ausbrechen.
2. **Mensch unterbricht** (`result.error == INTERRUPTED`) → **nicht durch `max_attempts` beschränkt**,
   wartet nicht aufs Netz. Knüpft mit den Worten des Menschen per `resume` an dieselbe Session an,
   `attempt -= 1` (eine Unterbrechung zählt nicht als fehlgeschlagener Versuch), prompt = Worte des
   Menschen + `INTERRUPT_NOTE`. **Ohne eine erhaltene `session_id` bleibt nur anhalten**.
3. **Kontext voll** (`result.error == HANDOFF_DUE`, oder `handoff.enabled` und eine `session_id`
   erhalten und `is_overflow(...)` schlägt an) → **ebenfalls nicht durch `max_attempts` beschränkt**.
   Zuerst wird `len(result.retired) >= handoff.max_generations` geprüft; ist es überschritten, wird
   der error durch eine Diagnosezeile ersetzt und ausgebrochen; sonst wird das [Handoff-Dokument](glossary.md#交接书)
   geschrieben → `resume=None, fork=False` (**brandneue Session**) → prompt wird zu `h.prompt_block()`
   → Pegel auf null → `attempt -= 1`.
4. **Wiederholbarer Fehler** → bei `not resilience.enabled or attempt >= max_attempts` ausbrechen;
   entscheidet `classify(error)`, dass nicht wiederholt werden soll, auch ausbrechen; sonst
   `Event("retry")` senden, mit `wait_online()` aufs Netz warten, `sleep(delay_for(attempt))`;
   **wurde je eine `session_id` erhalten, per `resume` weiterlaufen** (prompt wird zu
   `resilience.resume_prompt`) und `result.resumed` auf `True` setzen.

Zum Abschluss: `ended_at` schreiben, an `self.results` anhängen, `manifest.json` schreiben.

`manifest.json` hat **Append**-Semantik: bei jedem Schreiben wird die Platte neu gelesen, nach dem
Feld `run` dedupliziert (die eigene Zeile wird ersetzt, fremde Zeilen bleiben stehen), sodass es
sicher ist, im selben `run_dir` zwei Flower parallel laufen zu lassen — vorausgesetzt, die `run_id`
kollidieren nicht.

**Die drei Beobachtungspunkte des Handoffs** (alle `Event("handoff")`, unterschieden per
`payload["phase"]`): `near` (nähert sich `warn_at`, pro Generation nur einmal gesendet),
`writing` (schreibt gerade das Handoff, dauert gut zehn Sekunden), `done` (payload trägt
`degraded` / `path` / `sections`). Die Runde, die das Handoff schreibt, läuft mit
`replace(spec, max_budget_usd=None)` — das Handoff muss geschrieben werden können, darf nicht am
Budget hängenbleiben; zudem `on_event=None`, diese Runde spielt nichts an die UI.

Das Handoff wird nach `<workbench.notes>/交接-<Schrittname>.md` gespillt; **ohne Workbench kein
Spill**, das Dokument wird trotzdem per prompt an den Nachfolger übergeben, nur ist es hinterher
nicht mehr auffindbar. Ein altes Handoff wird nach `notes/archive/交接/<Name>-<Zeitstempel>.md`
verschoben.

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

Die vollständige Abrechnung eines gelaufenen Schritts.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `step` | `str` | Pflicht | Schrittname (`step_name` oder `spec.name`) |
| `session_id` | `str \| None` | `None` | **Immer jene Session, die zuletzt übernommen hat** — die bei einem zwischenzeitlichen Handoff verbrannten stehen in `retired` |
| `ok` | `bool` | `False` | Ob dieser Schritt geklappt hat |
| `cost_usd` | `float` | `0.0` | US-Dollar. Über Wiederholung und Handoff hinweg **akkumuliert** |
| `num_turns` | `int` | `0` | Rundenzahl, ebenfalls akkumuliert |
| `text` | `str` | `""` | **Enthält nur den Fließtext des Main-Threads**. Die Äußerungen der Subagents bleiben in deren eigenen Transcript, das ihnen zugeteilte Task-Brief ist `kind="prompt"`, beides kommt nicht hinein |
| `error` | `str \| None` | `None` | Grund des Fehlschlags. Für Sonderwerte siehe `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Unix-Zeitstempel |
| `attempts` | `int` | `1` | Tatsächliche Zahl der Versuche. Unterbrechung und Handoff **zählen nicht mit** |
| `errors` | `list[str]` | `[]` | Gesammelte synthetische API-Fehlermeldungen, **kommen nicht in `text`** |
| `resumed` | `bool` | `False` | Ob zwischendurch per resume weitergelaufen wurde |
| `retired` | `list[str]` | `[]` | Die bei den Handoffs dieses Schritts verbrannten `session_id`, der Reihe nach |
| `context` | `int` | `0` | Die Kontextgröße, die der Main-Thread in der letzten Runde tatsächlich gesehen hat, also das Handoff-Kriterium |

| Attribut | Typ | Beschreibung |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`, bei nicht abgeschlossenem Lauf `0.0` |

---

## Workflow {#流程}

Quellcode: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

Ein [Workflow](glossary.md#流程) ist eine der Reihe nach aufgefädelte Menge von [Schritten](glossary.md#步骤),
plus die Regeln, wie Zustand zwischen den Schritten weitergereicht wird und wann vorzeitig abgebrochen wird.
**Das Framework liefert keinen fertigen Workflow, den Workflow schreibst du** — `starter_flow` ist nur eine
lauffähige Vorlage.

Typ-Alias `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, steht in `flower.workflow.__all__`,
nicht im obersten `__all__`).

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

Die **Deklaration** eines Schritts. `Step` selbst ist keine Funktion — ausgeführt wird tatsächlich
`Runtime.run(step.spec, prompt, ...)`. Die ersten drei Felder sind Positionsargumente,
`Step("取词", terse, "读 seed.txt …")` ist gültige Schreibweise.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | Pflicht | Schrittname. **Prozessübergreifend stabiler Schlüssel** — landet in `ctx[name]`, `ctx["_results"]`, im Manifest und in der Lineage. Umbenennen = Lineage gekappt |
| `spec` | `AgentSpec` | Pflicht | Welcher Agent läuft |
| `prompt` | `str \| Callable[[Ctx], str]` | Pflicht | Was gesagt wird. Kann ein Closure sein, das `ctx` bekommt und live rechnet |
| `resume_from` | `str \| None` | `None` | Session welches Schritts fortgesetzt wird. Hat der referenzierte Schritt keine Session erzeugt, **wirft es `ValueError`**, statt still zu überspringen |
| `fork` | `bool` | `False` | Auf Basis von `resume_from` verzweigen. **Ohne `resume_from` wirkungslos** |
| `retries` | `int` | `0` | Wie oft maximal nachgelegt wird, wenn das Gate nicht durchgeht. `retries=0` = nur eine Runde |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Entscheidet, ob dieser Durchgang zählt. **Darf async sein.** `False` gilt als Fehlschlag. **Wird pro Versuch genau einmal aufgerufen** — es kann Seiteneffekte haben (etwa den Brief auf Platte schreiben) und darf nicht mehrfach ausgelöst werden |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, siehe unten |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Bei `False` wird **der ganze Schritt übersprungen**: kein Result, kein Eintrag in `ctx["_results"]`. **Darf async sein** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Was in der **nächsten Runde** gesagt wird, wenn das Gate nicht durchging. **Darf async sein.** Wird es gesetzt, ändert sich die Retry-Semantik, siehe unten |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | Prompt für den Fall der Continuity (statt von vorn zu beginnen) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Bestimmt, was in `ctx[name]` landet. Default ist der Rohtext `result.text`. **Muss eine synchrone Funktion sein** |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Bei `resuming` und vorhandenem `resume_prompt` wird letzteres genommen, sonst `prompt`; ist es aufrufbar, wird es mit `ctx` aufgerufen |

**Drei Arten, Sessions zu verbinden** (innerhalb desselben Runs):

| Schreibweise | Wirkung |
|---|---|
| `resume_from=None` (Default) | Neue Session, nur mit dem im Prompt übergebenen Kontext. Billig, isoliert. **Aber bei `Workflow(continuous=True)` wird die Session des gleichnamigen Schritts aus der prozessübergreifenden Lineage geholt** |
| `resume_from="Name des vorigen Schritts"` | Dieselbe Session wird fortgesetzt, vollständiger Kontext. Teuer, zusammenhängend |
| `resume_from="Name des vorigen Schritts", fork=True` | Verzweigen, ohne die Ursprungs-Session zu verschmutzen. Für Nachprüfung / parallele Varianten |

**`on_reject` ändert die Retry-Semantik**:

- Nicht gesetzt → der nächste Versuch **läuft von vorn** (gleicher Prompt, gleiches `resume_from`).
- Gesetzt → der nächste Versuch **setzt genau die eben abgelehnte Session fort**, der Prompt wird durch den Rückgabewert ersetzt, `fork` wird auf `False` gezwungen.
- Gibt es einen leeren String zurück → kein Zurückweisen, es fällt auf „von vorn“ zurück.
- Ist `result.session_id` gleich `None` → ebenfalls Rückfall auf „von vorn“.

**Die drei Werte von `on_fail`**:

| Wert | Verhalten |
|---|---|
| `"stop"` (Default) | Schreibt `ctx["_failed_at"] = name` und **bricht den gesamten Workflow ab** |
| `"skip"` | Springt zum nächsten Schritt, **`ctx[name]` wird nicht geschrieben** — ein nachgelagertes `lambda ctx: ctx["某步"]` läuft in einen `KeyError` |
| `"continue"` | `ctx[name] = result.text`, es geht mit dem unvollständigen Ergebnis weiter |

Ob bestanden oder nicht, `ctx["_results"][name] = result` wird immer geschrieben; ist `result.session_id`
nicht leer, wird zusätzlich in `ctx["_sessions"]` geschrieben und `lineage.remember(...)` aufgerufen.

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

Führt eine Kette von `Step` der Reihe nach aus und gibt den finalen `ctx` zurück. `steps` ist ein
Positionsargument, `Workflow([...])` ist gültig.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `steps` | `list[Step]` | Pflicht | Wird der Reihe nach ausgeführt |
| `name` | `str` | `"workflow"` | Name des Workflows |
| `context` | `Ctx` | `{}` | Initiales Kontext-Dict. **Läuft derselbe `Workflow` ein zweites Mal, ist ctx dasselbe dict** |
| `channel` | `HumanChannel \| None` | `None` | Hier hängt der Kanal, wenn angehalten und ein Mensch gefragt werden muss. `run()` hängt dessen `on_event` automatisch an denselben Ausgang, **nur wenn `channel.on_event is None`**; auch das Treiberprogramm erfährt über dieses Feld, wem es antworten soll |
| `workbench` | `Workbench \| None` | `None` | Die vom Workflow bestimmte Workbench, damit das Treiberprogramm sie findet |
| `continuous` | `bool` | `True` | Gleicher Pfad = gleiches Gespräch. Umgesetzt über [`Lineage`](#lineage) |

| Parameter von `run()` | Typ | Default | Beschreibung |
|---|---|---|---|
| `runtime` | `Runtime` | Pflicht, Positionsargument | Auf welcher Runtime gelaufen wird |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Event-Ausgang, wird an jedes `Runtime.run` durchgereicht |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Callback nach jedem abgeschlossenen Schritt |

!!! warning "`continuous=True` ist der Default, `resume_from=None` heißt nicht neue Session"
    Ist Continuity an, ruft `run()` zuerst `Lineage.open(run_dir, workspace)` und prüft dann jeden
    Eintrag einzeln per `runtime.has_session(sid)`, ob er noch im Store liegt; nur lebende Einträge
    fließen in `ctx["_sessions"]`. Damit **redet auch ein Schritt mit `resume_from=None` in der Session
    vom letzten Mal weiter** — auch wenn der Prozess getötet oder die Maschine neu gestartet wurde.

    Wer jedes Mal eine frische Session will, schreibt explizit `Workflow(..., continuous=False)`.
    Außerdem: **Schrittnamen sind prozessübergreifend stabile Schlüssel; einen Schrittnamen zu ändern heißt, die Lineage zu kappen.**

Die **privaten Schlüssel**, die `run()` in ctx schreibt (alle mit `_` beginnend, kollidieren also nicht mit Schrittnamen):

| Schlüssel | Inhalt |
|---|---|
| `_runtime` | Die übergebene `Runtime`. **Darüber schickt ein Gate Agents los** |
| `_on_event` | Event-Ausgang. Auch der Agent im Gate muss die UI erreichen, sonst bleibt die Oberfläche schwarz |
| `_sessions` | `dict[Schrittname, session_id]`, wird per `setdefault` gelesen |
| `_results` | `dict[Schrittname, StepResult]` |
| `_lineage` | Das `Lineage`-Objekt. Nur vorhanden, wenn `continuous=True` und die Runtime `run_dir` + `workspace` hat |
| `_woke` | Rückgabewert von `lineage.bump()`, das wievielte Wake dies ist |
| `_aborted` | Die Nachricht des `StepAbort` |
| `_failed_at` | Name des gescheiterten Schritts bei `on_fail="stop"` |

Payload von `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Retry-Labels**: Versuch 0 nutzt `step.name`; danach mit `on_reject` `f"{name}#round{attempt+1}"`,
ohne `on_reject` `f"{name}#retry{attempt}"`. Im Manifest sieht man auf einen Blick, wie dieser Schritt
zu Ende gegangen ist. **Namen mit Suffix gehen nicht in die prozessübergreifende Lineage** —
`Lineage.remember` verwendet den Originalnamen.

`runtime.on_session` umschließt nur die eine Zeile `runtime.run` und wird per `try/finally` garantiert
vor dem Gate wieder abgenommen. `prompt_cur` / `resume_cur` / `fork_cur` sind lokale Variablen und werden
nicht in `step` zurückgeschrieben — dasselbe `Step`-Objekt kann ein zweites Mal laufen.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Vom `gate` geworfen = **sofort stoppen, nicht weiter versuchen**. Unterschied zu „gibt `False` zurück“:
`False` heißt „diesmal nicht, noch eine Runde“; `StepAbort` heißt „noch eine Runde bringt nichts“.

Nach dem Wurf: `ctx["_aborted"] = str(exc)`, `passed = False`, **Ausstieg aus der Retry-Schleife
(die restlichen `retries` werden nicht verbraucht)**, danach geht es wie bei einem normalen Fehlschlag
über `on_fail` weiter (Default `"stop"`).

`with_goal` wirft es an zwei Stellen: wenn `ctx["_runtime"]` nicht zu bekommen ist, und wenn der Verdict
`unreachable` lautet und niemand antwortet.

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

Erzeugt einen `Step`, der [Clarify](glossary.md#前置确认) macht: Anforderung ausfragen → zu einem
[`Brief`](#brief) parsen → sind alle vier Abschnitte da, einfrieren und auf Platte schreiben.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `channel` | `HumanChannel` | Pflicht, Positionsargument | Kanal zum Fragen |
| `brief_path` | `str \| Path` | Pflicht | Wohin der [Brief](glossary.md#需求确认书) fällt. **Muss in genau der Workbench liegen, deren Index tatsächlich injiziert wird** |
| `prompt` | `str \| Callable[[Ctx], str]` | Pflicht | Das ursprüngliche Anliegen des Menschen |
| `name` | `str` | `"确认需求"` | Schrittname, zugleich Schlüssel in `ctx` |
| `spec` | `AgentSpec \| None` | `None` | Ohne Angabe wird `clarify(name, channel, instructions=instructions, **spec_kw)` verwendet |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen an den [Clarifier](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = jedes Mal neu fragen, egal ob ein Brief existiert |
| `on_fail` | `str` | `"stop"` | Wie `Step.on_fail` |
| `retries` | `int` | `0` | Wie oft nachgefragt wird, wenn die vier Abschnitte nicht vollständig sind |
| `**spec_kw` | | | Wird direkt an [`clarify()`](#clarify-role) durchgereicht, also sind `can_read=False`, `max_budget_usd=...` möglich |

So sind die Felder im erzeugten `Step` belegt:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: bei `always_ask=True` → immer `True`; sonst wird bei vollständigem `Brief.load(brief_path)` dieser
  in ctx gefüllt und **dann `False` (überspringen) zurückgegeben** — auch beim Überspringen muss gefüllt
  werden, sonst bekommt das Nachgelagerte die Anforderung nicht.
- `gate`: `Brief.parse(result.text)`, unvollständig → `ctx[MISSING_KEY]` schreiben und `False` zurückgeben;
  vollständig → `b.write(brief_path)` einfrieren, in ctx füllen, `True` zurückgeben.
- `reduce`: gibt `ctx[BRIEF_KEY].prompt_block()` zurück, **nicht den Rohtext des Modells** — im Rohtext
  kann Zusatzgeschriebenes stecken.
- `resume_from` **bleibt auf dem Default `None`**: der nächste Schritt ist eine neue Session, er bekommt nur
  den Brief, nicht das Frage-Antwort-Protokoll.
  Die Fragen und Antworten des Clarify **waren nie** im Kontext des Koordinators; sie wurden nicht erst
  hineingelassen und dann herausgeschnitten.

Drei Stellen, die in ctx gefüllt werden: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`,
`ctx.pop(MISSING_KEY, None)`.

| Konstante | Wert | Beschreibung |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` ist das `Brief`-Objekt; `ctx[step.name]` ist dessen `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Welche Abschnitte bei gescheiterter Klärung fehlen (Abschnittsnamen auf Chinesisch), zur Anzeige in der UI |
| `CLARIFY_RESUME` | Ein Prompt-Text auf Chinesisch | „Mach mit der eben nicht zu Ende geführten Anforderungsklärung weiter — **nicht von vorn anfangen** …“. Ohne diesen Satz schickt die Continuity das ursprüngliche Anliegen als neue Aufgabe erneut, und der Clarifier fragt womöglich schon Gefragtes noch einmal |

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

Erzeugt einen `Step`, der **das Ziel setzt**: Der [Judge](glossary.md#判定者) liest den Brief und schreibt
Ziel + Prüfliste; das wird zu einem [`Goal`](#goal) geparst, eingefroren und auf Platte geschrieben.
Gleiche Form wie `clarify_step`.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `channel` | `HumanChannel` | Pflicht, Positionsargument | Kanal zum Fragen |
| `goal_path` | `str \| Path` | Pflicht | Wohin die Zieldatei fällt |
| `brief_key` | `str` | `"确认需求"` | Aus `ctx[brief_key]` wird der Brief-Rohtext in den Prompt gesteckt. **Ist nichts zu holen, steht dort `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Schrittname |
| `spec` | `AgentSpec \| None` | `None` | Ohne Angabe wird `judge(name, channel, instructions=instructions, **spec_kw)` verwendet |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen |
| `always_set` | `bool` | `False` | `True` = Prüfliste neu herleiten, egal ob eine Zieldatei existiert |
| `on_fail` | `str` | `"stop"` | Wie oben |
| `retries` | `int` | `0` | Wie oben |
| `**spec_kw` | | | Wird an [`judge()`](#judge-role) durchgereicht |

**Es gibt keinen Parameter `can_run`** — soll der zielsetzende Judge Kommandos ausführen dürfen, geht das
nur über `**spec_kw` mit `can_run=True`. Ohne das bekommt er kein `Bash`, und die Regel aus `JUDGE_RULES`
„sieh dir erst genau an, in welcher Umgebung du bist“ lässt sich nicht ausführen.

Das `gate` tut außer Parsen und Einfrieren noch eines: Enthält das Ziel Einträge mit
`[此环境无法验证:…]`, schickt es **an Ort und Stelle** über `ctx["_on_event"]` ein
`Event("task", payload={"unverifiable", "total", "path"})` als Hinweis —
das Schicksal dieser Einträge entscheidet sich im Moment der Zielsetzung; bis zum Verdict ist das Geld
für eine ganze Arbeitsrunde schon ausgegeben.

**Kein `resume_prompt` gesetzt** — beim Zielsetzen soll der Brief ohnehin im Volltext neu geschickt werden.

| Konstante | Wert | Beschreibung |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` ist das `Goal`-Objekt; `ctx[step.name]` ist Markdown |
| `VERDICT_KEY` | `"_verdict"` | Der jüngste [`Verdict`](#verdict), für die UI |
| `ROUND_KEY` | `"_goal_rounds"` | Wie viele Runden der Verdict schon gelaufen ist |

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

Legt einem bestehenden `Step` den [Goal Guard](glossary.md#目标看守) an: Nach jeder Runde beurteilt der
Judge unabhängig; ist das Ziel nicht erreicht, geht es zurück zum Weiterarbeiten.

Das Ergebnis ist `replace(step, retries=max(0, rounds - 1), gate=<neues gate>, on_reject=<neues on_reject>)` —
mit `dataclasses.replace` statt feldweisem Neuaufbau; beim einmaligen Neuaufbau fiel `resume_prompt` unter den
Tisch, **und das ohne Fehlermeldung**, es wurde bei der Continuity nur der ganze Brief noch einmal verschickt.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `step` | `Step` | Pflicht, Positionsargument | Der bewachte Schritt |
| `channel` | `HumanChannel` | Pflicht, Positionsargument | Kanal, um einen Menschen zu fragen, wenn keine Entscheidung möglich ist |
| `goal_path` | `str \| Path` | Pflicht | Zieldatei; von hier wird gelesen, wenn `ctx[GOAL_KEY]` unvollständig ist |
| `spec` | `AgentSpec \| None` | `None` | Ohne Angabe wird `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` verwendet |
| `rounds` | `int` | `3` | **Gesamtzahl der Runden, nicht zusätzliche Runden**: `rounds=3` → `retries=2` → höchstens drei Arbeitsrunden. `rounds=1` = eine Runde arbeiten, einmal beurteilen, bei Nichtbestehen Fehlschlag |
| `instructions` | `str` | `""` | Zusätzliche Anweisungen an den Judge |
| `can_run` | `bool` | `False` | Ob der Judge `Bash` ausführen darf |
| `name` | `str \| None` | `None` | Name des Judge, Default `f"{step.name}·判定"` |
| `**spec_kw` | | | Wird an `judge()` durchgereicht |

Das `gate` ist **async**, Ablauf:

1. `ctx["_runtime"]` fehlt → **`StepAbort` werfen** („Runtime nicht zu bekommen, Ziel nicht beurteilbar“). **Nicht so tun, als wäre bestanden.**
2. `ctx[ROUND_KEY] += 1`.
3. Ziel holen: bevorzugt ein vollständiges `Goal` aus `ctx[GOAL_KEY]`, sonst `Goal.load(goal_path)`, sonst leeres `Goal()`.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **Der Judge ist ein eigener `Runtime.run`, `resume` ist immer `None` — es ist stets eine neue Session**;
   `step_name` trägt die Rundennummer und geht deshalb nicht in die prozessübergreifende Lineage.
5. `Verdict.parse(vr.text)` wird nach `ctx[VERDICT_KEY]` geschrieben.
6. `v.achieved` → `True` zurückgeben.
7. Nicht `unreachable` (einschließlich der unklaren Fälle mit `v.ok=False`) → bei Unklarheit einen
   Default-`reason` ergänzen, `False` zurückgeben.
   **Unklarheit gilt ausnahmslos als nicht erreicht** — ein „sieht okay aus“ darf die Arbeit nicht abschließen.
8. `unreachable` → `await channel.ask(...)` fragt den Menschen, drei Optionen:
   - Niemand antwortet (`a.state != "answered"`) → **`StepAbort` werfen**. Weiter im Leerlauf zu drehen ist die teuerste Option.
   - „Ergebnis akzeptieren und so weitermachen“ → `True` zurückgeben.
   - „Ziel ändern“ → noch einmal nach dem neuen Ziel fragen, `g.amend(...).write(goal_path)`, `ctx[GOAL_KEY]` aktualisieren, `False` zurückgeben.
   - Alles Übrige (inklusive frei getippter Antworten) → gilt als „du hast falsch geurteilt“, die Aussage des Menschen wird in `v.reason` festgehalten, `False` zurückgeben.

`on_reject` ist **synchron**: gibt `ctx[VERDICT_KEY].feedback()` zurück, ohne `Verdict` `""`
(Rückfall auf „von vorn“).

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

Baut einen sofort lauffähigen Drei-Schritt-Workflow zusammen: **Anforderung klären → Ziel setzen → arbeiten**
(mit Goal Guard). Genau den benutzt das Kommandozeilenwerkzeug `flower`.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `ask` | `str` | Pflicht, Positionsargument | Ein Satz Anliegen. **Beim Wake ist er keine neue Aufgabe, sondern „noch ein Satz, der gesagt wurde“** |
| `workspace` | `str \| Path` | `"."` | Arbeitsbereich |
| `run_dir` | `str \| Path` | `"runs"` | Run-Verzeichnis |
| `new` | `bool` | `False` | `True` = Lineage + Brief + Ziel archivieren (alle drei zusammen), von vorn beginnen |
| `isolate` | `bool` | `False` | [Isolation](glossary.md#隔离) per Worktree für den Worker. Die Workbench wandert entsprechend nach `<ws>.parent/.flower-<ws.name>` |
| `clarify_only` | `bool` | `False` | Gibt nur den Workflow mit dem Klärungsschritt zurück |
| `goal` | `bool` | `True` | Ob der [Goal Guard](glossary.md#目标看守) angebaut wird. `False` = der Arbeitsschritt gilt nach seinem Durchlauf als fertig |
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
# Koordinator = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Verhaltensverzweigungen:

- `isolate=True` und der Workspace ist kein Git-Repo → **`ValueError` werfen**, statt es erst am Fehler des
  `Agent`-Tools zu merken (dann ist das Geld schon weg).
- **Wake-Erkennung**: existiert `Brief.load(brief_path)` und ist `complete()`, gilt es als Wake. Kein Wake und
  `ask` leer → **`ValueError("要给一句诉求,例如 flower '帮我做一个 X'")` werfen**.
- Beim Wake landet dieser Satz gleichzeitig an **drei Stellen**, fehlt eine, verpufft er still: er wird an den
  Brief angehängt (`ch.amend(said, label="唤醒时追加")`, steht er schon in der Datei, wird er nicht doppelt
  geschrieben), er lässt `goal_step(always_set=True)` die Prüfliste neu herleiten (ohne Neuherleitung liest der
  Judge weiter das alte Ziel), und er geht direkt an den Koordinator (in dessen Kontext steht das **alte** Ziel;
  ohne diesen Satz arbeitet er nach altem Maßstab und wird nach neuem beurteilt).

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

**Eine reine Lese-Sondierung vor dem Start, es wird kein einziges Byte geschrieben.** Damit lässt sich einem
Menschen vor dem eigentlichen Loslaufen sagen: „Das setzt das letzte Mal fort“ oder „das fängt von vorn an“.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Arbeitsbereich, Positionsargument |
| `run_dir` | `str \| Path` | `"runs"` | Run-Verzeichnis |
| `isolate` | `bool` | `False` | Bestimmt den Ort der Workbench, muss denselben Wert haben wie bei `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Dateiname des Briefs |
| `goal_name` | `str` | `"目标.md"` | Dateiname des Ziels |

Das zurückgegebene dict:

| Schlüssel | Typ | Beschreibung |
|---|---|---|
| `waking` | `bool` | Der Brief existiert und alle vier Abschnitte sind vollständig |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Anzahl der Einträge in der Zielprüfliste, ohne Ziel `0` |
| `woke` | `int` | `Lineage.woke`, wie oft schon aufgeweckt wurde |
| `steps` | `dict` | Kopie von `Lineage.steps`, Schrittname → `session_id` |

Der Ort der Workbench ist **nur hier und in `starter_flow` einmal definiert**: `isolate=True` →
`<ws>.parent/.flower-<ws.name>` (außerhalb des Repos); sonst `<ws>/.flower`. Auch ein Treiberprogramm, das
wissen will, wo der Brief liegt, geht über diese Funktion — ein selbst zusammengebauter falscher Pfad wirft
keinen Fehler, er verpufft nur still.

---

## Rollen-Factories {#角色工厂}

Quelle: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

Alle fünf Rollen sind Factory-Funktionen. Jede Rolle = **ein Stück injizierter Regeltext + eine Menge Tools + eine Menge Hooks**.
`worker()` liefert eine `AgentDefinition` des SDK (zur Verwendung durch einen subagent), die anderen vier liefern [`AgentSpec`](#agentspec)
(starten also eine eigene session).

Die Rollen selbst **hängen keine Hooks ein** — das Abfangen von Tools montiert `Runtime._attempt` anhand von `spec.delegate_only` automatisch,
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

Erzeugt den [Coordinator](glossary.md#主线程) auf dem [Main Thread](glossary.md#协调者): Aufgaben zerlegen, delegieren, Berichte lesen, entscheiden —
**aber nicht selbst Hand anlegen**. Die ersten drei Parameter sind Positionsparameter.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | Pflicht | Rollenname, zugleich der Default-Name des Steps |
| `instructions` | `str` | Pflicht | Domänenanweisung. Ergibt am Ende `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | Pflicht | Welche Rollen ihm unterstehen, landet in `AgentSpec.agents` |
| `channel` | `HumanChannel \| None` | `None` | Wenn gesetzt, werden **beide** Tools `inbox` **und** `ask` angehängt und `mcp_servers` gesetzt |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → ohne `Read` |
| `glance` | `bool` | `True` | Hängt `"Bash"` an und setzt `AgentSpec.glance`. **Was konkret laufen darf, entscheidet `delegate_guard`**, nicht diese Stelle |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | Obergrenze der Runden |
| `max_budget_usd` | `float \| None` | `None` | Obergrenze des [Budgets](glossary.md#预算) |
| `permission_mode` | `str` | **`"acceptEdits"`** | Berechtigungsmodus. **Achtung auf diesen Default** — gibt man ihn an `clarify()`/`judge()` weiter, reißt man den Schutz dieser beiden Rollen ein |
| `compact` | `CompactPolicy \| None` | `None` | Wenn gesetzt, erzwingt `Runtime` kein `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Zusätzliche Hooks, werden mit `workbench_hooks` zusammengeführt |
| `env` | `dict[str, str] \| None` | `None` | Zusätzliche Umgebungsvariablen |

Die drei fixen Einträge der erzeugten `AgentSpec`: `delegate_only=True`, `agents=workers`,
`workbench` behält den `AgentSpec`-Default `True`.

Im Quellcode steht ausdrücklich: **`disallowed_tools` nicht verwenden, um „nur koordinieren, nicht anfassen" umzusetzen** — das gilt auf session-Ebene
und würde `Bash`/`Write` auch für subagents sperren, siehe die Warnung bei [`AgentSpec`](#agentspec).
Der richtige Weg ist genau der hier: `delegate_only=True` + keine `allowed_tools`,
und [`delegate_guard`](#delegate-guard) fängt anhand der `agent_id` nur den Main Thread ab.

Ist `channel` gesetzt, kommen **beide Tools zusammen**, nicht wahlweise: sobald der MCP-Server hängt, sind beide da, und
`allowed_tools` ist nicht exklusiv — ob gelistet oder nicht, aufrufbar sind sie. Unbeaufsichtigt blockiert jedes `ask` bis zum vollen `timeout_s` —
in dem Fall `HumanChannel(timeout_s=0)` verwenden.

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

Erzeugt die Definition des [subagent](glossary.md#subagent), der tatsächlich arbeitet. Die ersten beiden Parameter sind Positionsparameter.
Zurück kommt eine `AgentDefinition` des SDK, die direkt in `coordinator(workers={...})` gesteckt wird.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `description` | `str` | Pflicht | **Grundlage, nach der der Coordinator auswählt** — klar schreiben, „welche Arbeit an ihn geht" |
| `prompt` | `str` | Pflicht | Sein System-Prompt. Bei `discipline=True` zusammengesetzt als `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | Ein Worker soll nicht heruntergestuft werden |
| `effort` | `str \| int \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | Landet im SDK als **`maxTurns`** (CamelCase) |
| `permission_mode` | `str \| None` | `None` | Landet im SDK als **`permissionMode`** (CamelCase) |
| `skills` | `list[str] \| None` | `None` | Welche Skills er benutzen darf |
| `discipline` | `bool` | `True` | Ob die Berichtsdisziplin `WORKER_RULES` angehängt wird |
| `isolate` | `bool` | `False` | Setzt die [Isolations](glossary.md#隔离)-Markierung, läuft über `isolated()`, **ist kein Feld von `AgentDefinition`** |

`isolate=True` verlangt, dass der Workspace ein Git-Repository ist, sonst meldet das `Agent`-Tool direkt `"not in a git repository"` —
**es degradiert nicht stillschweigend**. Außerdem ist die Markierung ein Python-Attribut — ein `dataclasses.replace()` auf die `AgentDefinition`
verliert sie, und die Isolation fällt stillschweigend aus.

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

Erzeugt den [Clarifier](glossary.md#确认者): vor dem Anfangen die Anforderung ausfragen, nichts tun, nur fragen, und am Ende genau vier Abschnitte ausgeben.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | Pflicht | Rollenname, Positionsparameter |
| `channel` | `HumanChannel` | Pflicht | Frage-Kanal, Positionsparameter |
| `instructions` | `str` | `""` | Ergänzende Anweisung, hinter `CLARIFIER_RULES` angehängt |
| `can_read` | `bool` | `True` | Bei `True` werden `Read` `Glob` `Grep` `WebFetch` `WebSearch` angehängt |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | **Keine Rundenbegrenzung** |
| `max_budget_usd` | `float \| None` | `None` | Budgetobergrenze |

Die erzeugte `AgentSpec`: `allowed_tools = [channel.tool_name] + (die fünf, wenn lesend)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (er hat keine Schreib-Tools, der Index bringt ihm nichts),
`permission_mode` erbt den `AgentSpec`-Default `"default"`.
**Kein `Write` / `Edit` / `Bash` / `Agent`, und auch kein `inbox`** (anders als beim Coordinator).

!!! warning "Ein kleines `max_turns` macht das unbegrenzte Fragen zur leeren Behauptung"
    Jede Frage ist eine Runde. `max_turns=16` heißt „höchstens gut ein Dutzend Fragen", und der Satz im Kanal „keine Rundenobergrenze" ist damit auf der Stelle hinfällig.

    Wer das Fragen freigeben will, muss **beides** freigeben: `HumanChannel.max_asks` (Default ist bereits `None` = unbegrenzt)
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

Erzeugt den [Judge](glossary.md#判定者): entweder vor dem Start das Ziel festlegen oder nach jeder Runde diese Runde beurteilen.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | Pflicht | Rollenname, Positionsparameter |
| `channel` | `HumanChannel` | Pflicht | Frage-Kanal, Positionsparameter |
| `instructions` | `str` | `""` | Ergänzende Anweisung, hinter `JUDGE_RULES` angehängt |
| `can_run` | `bool` | `False` | Bei `True` kommt `Bash` in die Whitelist, `whitelist_guard` lässt `Bash` durch und blockt weiterhin `Write`/`Edit` |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | Obergrenze der Runden |
| `max_budget_usd` | `float \| None` | `None` | Budgetobergrenze |

Die erzeugte `AgentSpec`: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (bei `can_run`) `["Bash"]`,
`workbench=False`, der Rest wie bei `clarify()`. **Kein `Write` / `Edit` / `Agent`, und kein `inbox`.**

**Abwägung**: `can_run=True` macht das Urteil härter (er kann Abnahmebefehle wirklich ausführen), um den Preis, dass der Judge damit den Workspace verändern kann —
`Bash` allein kann Dateien schreiben. Wer ein absolut neutrales Urteil will, lässt es aus.

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

Erzeugt den [Oracle](glossary.md#旁路顾问): Während der Run noch läuft, fragt man ihn „wo stehen wir gerade", er sieht sich die letzten Events und die Workbench an
und antwortet. **Was er sagt, gelangt nicht in den Kontext dieses Runs.**

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Rollenname, Positionsparameter |
| `instructions` | `str` | `""` | Ergänzende Anweisung, hinter `ORACLE_RULES` angehängt |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | **`12`** | Standardmäßig mit Bremse |
| `max_budget_usd` | `float \| None` | **`0.5`** | Standardmäßig mit Bremse. Das ist „mal eben nachgefragt" und darf nicht entgleisen |

Die erzeugte `AgentSpec`: `allowed_tools = ["Read", "Glob", "Grep"]` (**kein Channel** — er fragt nicht,
er antwortet nur), `workbench=True` (**der einzige der fünf, der kein Coordinator ist und trotzdem die Workbench anhat** — er soll ja genau diese Artefakte und Notizen lesen).

### Die fünf Regeltexte {#rules}

Alle fünf Konstanten stehen in `__all__` und lassen sich direkt importieren, lesen, zusammensetzen und ändern.

| Konstante | Injiziert an | Art der Injektion | Kernpunkte |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | Du bist „ein Mensch, der Claude Code bedienen kann", kein Worker; keine Dateien schreiben/Code ändern/Tests laufen lassen; `Bash` reicht nur zum „kurz Hinsehen" und das Ergebnis veraltet; **im [Task Brief](glossary.md#任务书) steht nur, was für genau diese Aufgabe spezifisch ist**; die einzige Regel, die noch mitzuteilen ist, lautet „wo die Workbench liegt + lange Artefakte nach `artifacts/` + in der Antwort nur Pfade"; nach jeder abgeschlossenen Etappe einmal `inbox` prüfen; `ask` blockiert, also nur an echten Weggabelungen einsetzen |
| `WORKER_RULES` | `worker()` | **hinter** den `prompt` des subagent gehängt | Antwortformat **Ergebnis / Beleg / Artefakt / Ungeprüft**, höchstens 30 Zeilen; verboten sind eingefügte Dateiinhalte, Kommandoausgaben, Logs, roher Diff; verboten ist das Nacherzählen von Versuch und Irrtum; vor dem Anfangen erst in `.flower/scripts/` schauen. **Bewusst steht dort nicht „lange Artefakte nach `artifacts/`"** — den echten Pfad erzeugt `Workbench`, ein fest verdrahteter wäre falsch |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Nichts tun, nur die Anforderung klären; **keine Mengenbegrenzung, fragen bis es klar ist**; der Mensch ist vielleicht nicht da, bei Timeout selbst entscheiden und es unter „Unbekanntes und Annahmen" schreiben; Ausgabe **genau vier Abschnitte**; keinen Code schreiben, keine Dateiinhalte einfügen |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | Zwei Dinge, eines davon. **Ziel setzen**: Jeder Listenpunkt muss auf der Stelle prüfbar sein, die Länge der Liste ergibt sich aus der Anzahl der Fehlermodi, **Grenzen sind kein Prüfpunkt**, an nicht prüfbare Punkte kommt am Ende `[此环境无法验证:原因]`. **Diese Runde beurteilen**: Ausgabe **genau drei Abschnitte**, beurteilt wird **das Artefakt, nicht der Quellcode**, „ist fertig" wird standardmäßig nicht geglaubt, „nicht erreicht" und „hier nicht prüfbar" sind zwei verschiedene Ergebnisse, und Letzteres **darf auf keinen Fall als bestanden gewertet werden** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | Ein Nebenweg; der Run läuft noch, du unterbrichst nicht und beteiligst dich nicht; **nur lesen**; nach der Antwort verworfen, was du sagst, gelangt nicht in den Kontext dieses Runs; du hast nur das „Fenster der letzten Events" und die „Workbench"; erst schauen, dann antworten, kannst du nicht antworten, sag das, kurz |

---

## Agent-Definition {#agent-定义}

Quelle: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` ist die vollständige Deklaration eines spezialisierten Agents, `build_options` kompiliert sie in `ClaudeAgentOptions` des SDK.
Die [Rollen-Factories](#角色工厂) liefern genau `AgentSpec` — braucht man eine Kombination außerhalb der Factories, konstruiert man sie direkt.

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
| `name` | `str` | Pflicht | Rollenname. Zugleich der Default für `step_name` in `Runtime.run` und die Selbstbezeichnung im Ablehnungstext von `whitelist_guard` |
| `instructions` | `str` | Pflicht | Domänenanweisung. **Wird hinter den nativen System-Prompt von Claude Code [angehängt](glossary.md#叠加), nicht ersetzt** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **Liste ohne Genehmigungspflicht, keine exklusive Whitelist** — das Modell kann weiterhin Tools aufrufen, die nicht darin stehen. Exklusivität kommt von [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Auf session-Ebene**. Siehe Warnung unten |
| `model` | `str \| None` | `None` | Modell |
| `effort` | `str \| None` | `None` | Denkintensität |
| `max_turns` | `int \| None` | `None` | Obergrenze der Runden |
| `max_budget_usd` | `float \| None` | `None` | Obergrenze des [Budgets](glossary.md#预算) |
| `permission_mode` | `str` | `"default"` | Berechtigungsmodus |
| `agents` | `dict[str, Any] \| None` | `None` | Tabelle der subagent-Definitionen, Werte sind `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | Tabelle der MCP-Server. `HumanChannel.mcp_servers()` füllt direkt hierhin |
| `hooks` | `dict[str, Any] \| None` | `None` | Zusätzliche Hooks, `Runtime` führt sie per `merge_hooks` mit den eigenen zusammen |
| `compact` | `CompactPolicy \| None` | `None` | Wenn gesetzt, erzwingt `Runtime` kein `no_summary` |
| `env` | `dict[str, str]` | `{}` | Umgebungsvariablen für den Subprozess. `compact.env()` wird darauf ge-updated |
| `glance` | `bool` | `False` | Erlaubt dem Coordinator eigenes `Bash` zum „kurz Hinsehen". Was durchgelassen wird, entscheidet [`is_ephemeral`](#is-ephemeral), das Ergebnis wird von `EphemeralPolicy` als veraltet markiert |
| `workbench` | `bool` | `True` | Ob der Workbench-Index in den System-Prompt dieses Agents injiziert wird. **Rollen ohne Schreib-Tools sollten das ausschalten** (bei `clarify()` / `judge()` ist es per Default `False`) |
| `delegate_only` | `bool` | `False` | Nur koordinieren, nicht anfassen. Bei `True` montiert `Runtime` `delegate_guard` und **nicht** `whitelist_guard` |

!!! warning "`disallowed_tools` gilt auf session-Ebene und sperrt auch subagents"
    Originaltext der gemessenen Fehlermeldung: `"Bash is disabled for this session, in subagents as well as here"`.
    Wer also `disallowed_tools=["Bash"]` benutzt, damit der Coordinator nicht selbst Hand anlegt, verhindert auch, dass die entsandten Worker Befehle ausführen —
    und der ganze Run ist hin.

    Für „nur koordinieren, nicht anfassen": `delegate_only=True` + keine `allowed_tools`, dann fängt
    [`delegate_guard`](#delegate-guard) anhand der `agent_id` nur den Main Thread ab.

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

Kompiliert eine `AgentSpec` in `ClaudeAgentOptions` des SDK. `Runtime._attempt` ruft intern genau das auf;
wer das SDK selbst steuert (ohne `Runtime`), steigt ebenfalls hier ein.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `spec` | `AgentSpec` | Pflicht, Positionsparameter | Die zu kompilierende Deklaration |
| `cwd` | `str \| Path \| None` | `None` | Nur bei ungleich `None` wird `cwd` geschrieben |
| `session_store` | `SessionStore \| None` | `None` | Nur bei ungleich `None` werden `session_store` und `session_store_flush` geschrieben |
| `resume` | `str \| None` | `None` | Welche session fortgesetzt wird |
| `fork` | `bool` | `False` | Landet als `fork_session`. **Steckt innerhalb von `if resume:`** |
| `resume_at` | `str \| None` | `None` | Landet als `resume_session_at`. **Steckt ebenfalls innerhalb von `if resume:`** |
| `use_plugin` | `bool` | `True` | `True` und `PLUGIN_DIR` existiert → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Zusätzlich freigegebene Verzeichnisse. **Pflicht, wenn die Workbench außerhalb des Workspace liegt** |
| `flush` | `str` | `"eager"` | Landet als `session_store_flush` |
| `prelude` | `str` | `""` | Ein Abschnitt, der hinter `instructions` angehängt wird (der Workbench-Index läuft hierüber) |

Die Zuordnung:

| Erzeugter Options-Key | Wert |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Direkt aus `spec` |
| `setting_sources` | `[]` (portabel) oder `["project"]` |
| `plugins` | Nur vorhanden, wenn das Verzeichnis `plugin/` im Repo-Root existiert |
| `cwd` / `add_dirs` | Nur bei nicht-leer geschrieben |
| `session_store` / `session_store_flush` | Nur wenn `session_store` ungleich `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Jeweils nur bei nicht-leer geschrieben |
| `env` | `dict(spec.env)`, danach `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Nur wirksam, wenn `resume` wahr ist** |

`PLUGIN_DIR` ist `plugin/` im Repo-Root (relativ zu `flower/core/agent.py` drei Ebenen höher). Nach einer pip-Installation existiert dieses Verzeichnis nicht zwangsläufig,
der Code prüft das per `is_dir()`.

!!! warning "`fork=True` ohne `resume` ist stillschweigend wirkungslos"
    `fork_session` und `resume_session_at` stecken beide innerhalb von `if resume:` — ohne `resume` greifen sie überhaupt nicht,
    **und es gibt keinen Fehler**. Genauso wirkt `Runtime.run(resume_at=...)` nur, wenn `resume` gesetzt ist,
    und **`Workflow` übergibt `resume_at` nie**: Wer auf eine Nachricht zurückrollen will, muss `Runtime.run` direkt aufrufen.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

Das Schaltpult für Auto-[Compact](glossary.md#压缩), das Ergebnis ist ein Satz Umgebungsvariablen für den Subprozess.
Der Compact-Algorithmus selbst steckt im Harness-Binary und ist nicht änderbar; änderbar ist nur, „ob ausgelöst wird".

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = nichts setzen, Schwelle = Fenster − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (schaltet auch `/compact` ab). **Andere Werte werfen `ValueError`**, es wird nicht stillschweigend ignoriert |
| `window` | `int \| None` | `None` | Ungleich `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. Die CLI begrenzt auf 100k–1M, Werte unter 100k werden auf 100k angehoben |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `env` | `() -> dict[str, str]` | Erzeugt die Umgebungsvariablen. **Ein unzulässiges `mode` wirft hier den `ValueError`, nicht beim Konstruieren** — aufgerufen wird sie von `build_options`, der Fehler zeigt sich also in `Runtime.run` |

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

Das Policy-Objekt für „bei fast vollem Kontext ein [Handoff-Dokument](glossary.md#交接书) schreiben und eine neue session starten" statt zu compacten.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `enabled` | `bool` | `True` | Ausgeschaltet fällt man auf Auto-Compact zurück |
| `window` | `int` | `default_window()` | Wie groß das Kontextfenster des Modells angenommen wird |
| `headroom` | `int` | `50_000` | Wie viel Reserve bleibt. Begründung: Auto-Compact löst bei Fenster −33k aus, der Handoff muss davor kommen, und „den Handoff schreiben" kostet selbst noch eine Runde |
| `max_generations` | `int` | `8` | Wie viele Generationen ein Step höchstens durchläuft. **Das ist eine Bremse gegen Entgleisen, keine Kapazitätsplanung** |

| Property | Typ | Beschreibung |
|---|---|---|
| `at` | `@property -> int` | Handoff-Schwelle `max(10_000, window - headroom)`. **Mit Untergrenze 10k** — darunter lässt sich nicht einmal mehr der Handoff schreiben |
| `warn_at` | `@property -> int` | Position der Annäherungswarnung `max(1_000, at - 20_000)`, pro Generation nur einmal gesendet |

!!! warning "Ein zu klein konfiguriertes `window` führt zu endlosen Handoffs und verbrennt Geld"
    Liegt `at` unter dem **Startboden** dieser Rolle (beim Coordinator gemessen rund 34k), überschreitet jede neue session schon beim ersten Wort die Linie; und
    **Handoffs verbrauchen kein Retry-Kontingent** (`attempt -= 1`), also dreht sich das endlos leer. Die einzige Bremse ist `max_generations=8`,
    beim Anschlagen wird der `error` durch eine Diagnose ersetzt, die empfiehlt, `window` zu erhöhen oder die Handoffs abzuschalten.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Rät das Kontextfenster anhand des **Modellnamen-Strings** in der Umgebungsvariable `ANTHROPIC_MODEL` oder `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Bedingung | Rückgabe |
|---|---|
| Der Name enthält ein eigenständiges Wort `1m` (Regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| Der Name enthält `haiku` | `200_000` |
| Sonst (**einschließlich: beide Variablen nicht gesetzt**) | `1_000_000` |

**Der Default ist der aggressive Wert.** Zu groß geschätzt ist kein harter Fehler: Die API antwortet mit `prompt is too long`, `Runtime` erkennt dieses Signal
(intern `is_overflow`) und macht auf der Stelle einen Handoff — nur ist der Handoff dieser Generation dann die degradierte Fassung.

---

## Dokumente {#文书}

Quelle: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Vier Dataclasses, allesamt „eine Antwort des Modells in feste Abschnitte parsen und dann auf Platte schreiben". Die gemeinsame Form:
`parse()` parst, `missing()` / `complete()` prüfen auf Vollständigkeit, `to_markdown()` ist für Menschen,
`prompt_block()` für nachgelagerte Modelle, `write()` / `load()` schreiben und lesen zurück.

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

Der [Brief](glossary.md#需求确认书), **genau vier Abschnitte**, feste Reihenfolge
`goal` → `accept` → `bounds` → `unknowns`, die chinesischen Abschnittsnamen sind 「目标」「验收标准」「边界」「未知与假设」.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `goal` | `str` | `""` | Ziel |
| `accept` | `str` | `""` | Abnahmekriterien |
| `bounds` | `str` | `""` | Grenzen |
| `unknowns` | `str` | `""` | Unbekanntes und Annahmen |
| `path` | `Path \| None` | `None` | Ablageort. `compare=False`, geht nicht in den Gleichheitsvergleich ein |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `missing` | `() -> list[str]` | Die **chinesischen Namen** der fehlenden Abschnitte, direkt anzeigbar |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Parst die vier Abschnitte aus der Modellantwort. **Zuerst werden Fenced-Code-Blöcke abgestreift**, nicht Geparstes bleibt leer |
| `to_markdown` | `() -> str` | Vollständiges Dokument mit Kopf-Metadaten, leere Abschnitte werden als `"(未填)"` geschrieben |
| `prompt_block` | `() -> str` | Kompaktfassung für nachgelagerte Modelle, **nur nicht-leere Abschnitte**, ohne Metadaten |
| `write` | `(path: str \| Path) -> Path` | Legt Elternverzeichnisse an, schreibt, setzt `self.path` auf den aufgelösten Pfad und gibt ihn zurück |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Gibt `None` zurück, wenn die Datei nicht existiert oder ein `OSError` auftritt. **Setzt den Platzhalter `"(未填)"` wieder auf einen leeren String zurück** |

Parsing-Regeln (Sammelstelle der Fallstricke):

- Beim Abstreifen der Fences wird **ab einem unabgeschlossenen ``` oder `~~~` alles Folgende verworfen** — gemessen fügt der Clarifier den kompletten Code in die Antwort ein.
  Wird die Modellausgabe abgeschnitten, lassen sich alle folgenden Abschnitte nicht mehr parsen, `complete()` ist also `False`, und das Gate schickt es zurück.
- Der Überschriften-Regex toleriert `## 目标` / `**目标**` / `目标:` / `3. 边界` und auch, dass direkt hinter der Überschrift der Fließtext folgt.
- Die Aliastabelle wird nach Länge absteigend kompiliert, sonst würde „未知" zuerst „未知与假设" schlucken.
- Bei mehrfach vorkommenden gleichnamigen Abschnitten wird **der erste mit Inhalt genommen**.
- Wer den Brief von Hand bearbeitet und dabei den Platzhaltertext `"(未填)"` aus `to_markdown()` übernimmt, hat diesen Abschnitt weiterhin als fehlend markiert.

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
| `doing` | `str` | `""` | Woran gearbeitet wird. **Pflicht** |
| `decided` | `str` | `""` | Was entschieden wurde |
| `deadends` | `str` | `""` | Sackgassen |
| `next` | `str` | `""` | Nächster Schritt. **Pflicht** |
| `scene` | `str` | `""` | Lage vor Ort |
| `step` | `str` | `""` | Nur für den Dokumentkopf, **geht nicht ins Parsing ein** |
| `path` | `Path \| None` | `None` | Ablageort |

**Pflicht sind nur die beiden Abschnitte `doing` und `next`** — würde man „Sackgassen" hart als nicht-leer verlangen, zwänge man das Modell zum Erfinden.

| Member | Signatur | Beschreibung |
|---|---|---|
| `missing` | `() -> list[str]` | **Prüft nur die beiden Pflichtabschnitte** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Ob der Text die Degradierungsmarke `[降级:交接没写成]` trägt |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Nutzt den Abschnitts-Parser von `Brief` wieder |
| `to_markdown` | `() -> str` | Leere Abschnitte werden als `"(空)"` geschrieben |
| `prompt_block` | `() -> str` | **Der Kopf sagt dem Übernehmenden ausdrücklich, dass er übernimmt**, damit er nicht rückwärts nach Hintergrund fragt |
| `write` | `(path) -> Path` | Wie `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Wie `Brief.load` |

Drei im selben Modul **nicht exportierte, aber semantisch entscheidende** Member: `is_overflow(*texts)` matcht `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed` usw. und verwandelt einen „harten Fehler" in „sofort Handoff"; `HANDOFF_PROMPT` ist der Prompt, mit dem
**die laufende session selbst** ihren Handoff schreibt (enthält die beiden Platzhalter `{used}` und `{window}`, **es ist keine neue Rolle** —
nur sie selbst hat diesen Kontext); `degraded(step, prompt, *, why="")` setzt mechanisch eine Fassung zusammen, wenn der Handoff nicht zustande kommt,
und stopft in `scene` die ersten **1200** Zeichen der ursprünglichen Aufgabe.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

Ziel + Prüfliste im [Goal Guard](glossary.md#目标看守).

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `statement` | `str` | `""` | Zielformulierung |
| `checks` | `list[str]` | `[]` | Prüfliste, ein Punkt pro Zeile |
| `path` | `Path \| None` | `None` | Ablageort |

| Member | Signatur | Beschreibung |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | Die Einträge in `checks`, die mit `[此环境无法验证:…]` markiert sind. **Schon im Moment der Zielsetzung dazu verurteilt, nie bestanden zu werden** |
| `missing` | `() -> list[str]` | Verlangt `statement` nicht leer **und** `checks` nicht leer |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` je ein Punkt pro Zeile, Aufzählungszeichen `-` / `*` / `1.` werden automatisch entfernt |
| `to_markdown` | `() -> str` | Bei leerer Liste wird `"(空)"` geschrieben |
| `prompt_block` | `() -> str` | Kompaktfassung für nachgelagerte Modelle |
| `write` / `load` | Wie `Brief` | Schreiben und Zurücklesen |
| `amend` | `(extra: str) -> Goal` | **Anhängen statt Überschreiben**: hinter `statement` wird `"\n\n(已修改)" + extra` gesetzt, Rückgabe ist `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

Das Ergebnis einer Beurteilungsrunde des [Judge](glossary.md#判定者), **genau drei Abschnitte**: Ergebnis / Begründung / Nicht bestanden.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`, bei fehlgeschlagenem Parsing `""` |
| `reason` | `str` | `""` | Begründung |
| `failed` | `list[str]` | `[]` | Die nicht bestandenen Listenpunkte |

| Member | Signatur | Beschreibung |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Ob überhaupt ein Ergebnis geparst wurde. **`ok=False` muss als „nicht erreicht" behandelt werden, niemals als erreicht** |
| `parse` | `@classmethod (text) -> Verdict` | Siehe unten |
| `feedback` | `() -> str` | Der Rückläufer an den Worker: nur „woran es fehlt", keine Lösung |

Die Erkennungsreihenfolge von `parse`:

1. Zuerst über die Überschriftenabschnitte 「结论」/「判定」 holen.
2. Ohne Überschriftenabschnitt: nach `strip()` des ganzen Textes `fullmatch(r"1|true")` → erreicht; `fullmatch(r"0|false")` → nicht erreicht.
3. Sonst im Ergebnistext anhand der Statuswortliste (**längere Wörter zuerst**) das erste Treffer­wort suchen.
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」 fallen allesamt unter `unreachable`** —
   damit sind wir gemessen auf die Nase gefallen: Zielplattform macOS, Lauf in einem Linux-Container, der Judge sah sich die Verzweigung im Quellcode an und wertete es als bestanden.
4. Immer noch nichts → ein isoliertes `\b1\b` suchen → erreicht, `\b0\b` → nicht erreicht.
5. Nichts davon trifft → `state=""`, `ok=False`.

`unreachable` und `not_yet` **sind zwei verschiedene Ergebnisse**: Ersteres geht den Weg „anhalten und den Menschen fragen", nicht „noch eine Runde".

---

## Hook-Schicht {#hook}

Quelle: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

Diese Schicht ist flowers **Durchsetzungsgrenze**: welche Tools der Main Thread nicht anfassen darf, wie
überlange Ergebnisse getrimmt werden, welche Rolle in ein eigenes worktree geht —
alles wird von SDK-Hooks erzwungen, **nicht von Prompts**. Der Grund ist direkt: ein Prompt ist eine Empfehlung,
das Modell kann sie ignorieren. Gemessen: selbst wenn im System-Prompt ausdrücklich „kein worktree benutzen" steht,
greift die Injektion von `isolate_guard` trotzdem (das Modell übergibt `None`, gelandet ist `'worktree'`).

Neun Exporte: fünf Guard-Factories, die einen `HookMatcher` zurückgeben (`whitelist_guard` kann `None` liefern), ein Assembler, ein Merger, zwei Isolations-Markierungsfunktionen.
Sie müssen nicht manuell eingehängt werden — [`Runtime`](#runtime) verdrahtet sie anhand der `AgentSpec` automatisch. Manuelles Einhängen braucht man nur, wenn man das SDK selbst steuert
(also ohne `Runtime`).

**Die Main-Thread-Erkennung läuft überall über eine Funktion**: `_is_main_thread(data) = not data.get("agent_id")` —
in den Tool-Lifecycle-Hook-Daten eines subagent steckt `agent_id`, beim [Main Thread](glossary.md#主线程) nicht.
Alle Guards, die „nur den Main Thread abfangen", hängen an dieser einen Bedingung.

Tool-Gruppen-Konstanten (auf Modulebene, nicht exportiert, bestimmen aber die Default-Matcher):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Kurzreferenz: Welcher Guard hängt an welchem SDK-Event {#hook-速查表}

| Funktion | SDK-Hook-Event | matcher | Was abgefangen wird | Rückgabe | Wer installiert |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | die aus `Bash\|Write\|Edit\|NotebookEdit`, die **nicht in `allowed_tools`** stehen | **nur der Main Thread** ruft ein verbotenes Tool auf | `permissionDecision: "deny"` + Begründung | `Runtime._attempt`, **nur wenn `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (per `tools=` änderbar) | **nur der Main Thread** greift selbst zu; bei `allow_glance=True` wird `Bash` durchgelassen, wenn `is_ephemeral()` zutrifft | `deny` + „schick einen subagent" | `workbench_hooks(delegate_only=True)`, **nur wenn `Runtime` eine Workbench hat** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` hat weder `cwd` noch `isolation`, und `subagent_type` wurde mit `isolated()` markiert | `permissionDecision: "allow"` + `updatedInput` (injiziert `isolation="worktree"`) | `workbench_hooks`, **nur wenn in `agents` eine markierte Rolle steckt** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` liegt innerhalb von `workbench.root` | `{}` (der Seiteneffekt ist `workbench.refresh()`) | `workbench_hooks`, immer installiert |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **String-Felder** in `tool_response` mit ≥ `threshold` Zeichen; das Lesen des Spill-Verzeichnisses selbst wird durchgelassen | `updatedToolOutput` (Spill + einzeiliger Zeiger + erste 400 Zeichen) | `workbench_hooks`, **nur wenn `spill_threshold` truthy ist** |

**Die entscheidende Folgerung aus dieser Tabelle**: bei `Runtime(workbench=False)` wird `workbench_hooks` komplett nicht installiert;
und bei einem Koordinator mit `delegate_only=True` wird auch `whitelist_guard` übersprungen — **der Main Thread hat dann keine einzige Mauer**.
Siehe die Warnung unter [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Macht `allowed_tools` für die vier zugreifenden Tools tatsächlich exklusiv.**

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `allowed` | `list[str] \| None` | Pflicht, Positionsargument | Üblicherweise direkt `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | Die Selbstbezeichnung im Ablehnungstext. `Runtime` übergibt `spec.name` |

- **Hängt an `PreToolUse`**, der matcher ist `"|".join(banned)`, `banned` = die aus `Bash` `Write` `Edit` `NotebookEdit`,
  die nicht in `allowed` stehen.
- Bei Treffer sofort `permissionDecision: "deny"`, Text sinngemäß: „XX hat kein YY. **Das ist Absicht, keine vergessene Konfiguration.**
  Schreib das Ergebnis in den Text deiner Antwort, das Framework holt es von dort — versuch nicht, es mit anderen Schreibweisen zu umgehen."
- **Fängt nur den Main Thread dieser Session ab**, subagents gehen durch — deren Tools bestimmt `AgentDefinition.tools`.
- Gibt **`None`** zurück, wenn es nichts abzufangen gibt (etwa bei einer Rolle mit vollem Tool-Satz wie `worker()`); der Aufrufer entscheidet danach, ob er installiert.

**Warum es existieren muss**: `allowed_tools` ist eine **Liste genehmigungsfreier Tools, keine exklusive Whitelist**. Zwei gemessene Belege —
der Judge, der das Ziel gesetzt hat, hat 11-mal `Bash` ausgeführt; in der Probe für $0.1 konnte ein Agent mit
`allowed_tools=["Read"]` trotzdem `Write`/`Bash` aufrufen.
Dass `clarify()` / `judge()` also „keine Schreib-Tools haben", **liegt an diesem Hook**, nicht an der Whitelist selbst.

Der Vorteil: er wird aus `allowed_tools` abgeleitet, deshalb behält `judge(can_run=True)` automatisch `Bash` und fängt
`Write`/`Edit` weiterhin ab — kein zusätzlicher Schalter nötig.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Der Main Thread greift selbst zu → Ablehnung, mit Wegbeschreibung.**

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | matcher. Ein Regex-String, keine Liste |
| `allow_glance` | `bool` | `False` | Bei `True` durchgelassen, wenn `tool_name == "Bash"` und [`is_ephemeral(command)`](#is-ephemeral) zutrifft |

- **Hängt an `PreToolUse`**, der matcher ist genau `tools`.
- Ruft der Main Thread eines dieser vier Tools auf → deny, und die Begründung **sagt, wie es weitergeht**: mit dem `Agent`-Tool einen subagent schicken,
  im Auftrag Ziel und Abnahmekriterien klar schreiben, und verlangen, dass er lange Ergebnisse nach `.flower/artifacts/` schreibt
  und in der Antwort nur Pfad und Ergebnis liefert.
- subagents gehen ausnahmslos durch.

Der Unterschied zu `whitelist_guard` ist die **Formulierung**: beide fangen dieselbe Tool-Gruppe ab, aber dieser hier sagt „delegiere", was besser passt.
Deshalb bekommt eine Rolle mit `delegate_only=True` nur diesen einen; beide zu installieren gibt dem Modell zwei widersprüchliche Anweisungen.

Das Durchlass-Kriterium bei `allow_glance=True` und die Frage „wird das Ergebnis später getrimmt" sind **dieselbe Funktion** ([`is_ephemeral`](#is-ephemeral)) —
die durchgelassene Menge muss gleich der ablaufenden Menge sein; ändert man eine Seite, muss man die andere mitändern.

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

Tool-Ergebnisse über dem Schwellwert werden **sofort [gespillt](glossary.md#落盘)**, im Kontext bleibt nur ein einzeiliger Zeiger — nicht erst
compact machen, wenn der Kontext voll ist.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workbench` | `Workbench` | Pflicht, Positionsargument | Das Spill-Verzeichnis ist `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | Ab wie vielen Zeichen gespillt wird |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | matcher |
| `main_only` | `bool` | `False` | `False` (Default) = auch Ergebnisse von subagents werden gespillt |

- **Hängt an `PostToolUse`**, gibt
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <getrimmt>}}` zurück.
- Der Spill-Dateiname sind die ersten 16 Stellen des `sha256` des Inhalts + `.txt`; im Kontext steht stattdessen ein einzeiliger Zeiger + die **ersten 400 Zeichen**.
- `updatedToolOutput` **muss die Ausgabestruktur des Original-Tools behalten**, deshalb werden nur die zu langen **String-Felder** im dict ersetzt;
  **Listen werden nie angefasst** (darin können Bild-Blöcke stecken). Eine falsche Struktur wird verworfen (Original bleibt, kein Fehler).
- **Das Lesen der Spill-Datei selbst muss durchgelassen werden** — sonst ist „lies sie mit `Read`" eine leere Aussage: der zurückgelesene Volltext würde wieder gespillt, Endlosschleife.
  Gemessen aufgetreten; das Modell hat fünf Schreibweisen durchprobiert, um daran vorbeizukommen.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Wird etwas in die [Workbench](glossary.md#工作台) geschrieben, wird `INDEX.md` aktualisiert, damit der nächste Agent von Beginn an weiß, dass es existiert.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workbench` | `Workbench` | Pflicht, Positionsargument | Prüfbereich und Refresh-Ziel |

**Hängt an `PostToolUse`**, matcher `"Write|Edit"`. Liegt `tool_input["file_path"]` nach dem resolve innerhalb von
`workbench.root`, wird `workbench.refresh()` gerufen. **Gibt immer `{}` zurück** — es ändert nichts, es hat nur einen Seiteneffekt.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Weist subagents rollenweise ein eigenes git worktree zu und realisiert damit [Isolation](glossary.md#隔离).

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | Pflicht, Positionsargument | Rollentabelle, um zu prüfen, ob `subagent_type` markiert ist |
| `on_inject` | `Any` | `None` | Optionaler Callback, gerufen als `on_inject(subagent_type, description)` |

**Hängt an `PreToolUse`**, matcher `"Agent"`. Injiziert wird nur, wenn drei Bedingungen gleichzeitig gelten: `tool_name == "Agent"`,
`tool_input` hat **weder `cwd` noch `isolation`**, und die zu `subagent_type` gehörende Rolle wurde mit `isolated()` markiert.
Dann kommt `permissionDecision: "allow"` + `updatedInput` (mit `isolation` auf `"worktree"`) zurück.

`isolation` und `cwd` sind im `Agent`-Tool **exklusiv** — hat das Modell selbst ein `cwd` angegeben, wird das respektiert.
„Isolation oder nicht" ist eine **Eigenschaft der Rolle**, kein globaler Schalter und keine Entscheidung pro Delegation; einer Rolle, die keine Isolation braucht, wird kein einziges Byte hinzugefügt.

**Wer Isolation einschaltet, muss die [Workbench](glossary.md#工作台) aus dem Repo herausziehen.** Ein isolierter Agent kann nicht in das gemeinsame checkout schreiben,
also muss die Workbench per `home=` außerhalb des Repos liegen. `starter_flow(isolate=True)` nimmt
`<ws>.parent/.flower-<ws.name>`, `Runtime(workbench=True)` nimmt `<run_dir>/workbench` —
beide liegen außerhalb des Repos, **sind aber nicht dasselbe Verzeichnis**, nicht vermischen.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Markiert eine subagent-Definition als „braucht eigenen Arbeitsbereich" und liest diese Markierung wieder aus.

| Funktion | Parameter | Default | Beschreibung |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | Pflicht | Die zu markierende Definition. **Zurück kommt dasselbe Objekt** |
| | `flag: bool` | `True` | Positionsargument. `False` = Markierung entfernen |
| `wants_isolation` | `agent: AgentDefinition \| None` | Pflicht | `None` ist erlaubt, gibt `False` zurück |

Die Markierung ist ein per `object.__setattr__` gesetztes Python-Attribut `_flower_isolate`, **kein dataclass-Feld** —
das SDK serialisiert mit `asdict()` und kennt nur deklarierte Felder, deshalb sickert die Markierung nicht zur CLI durch (gemessen).

**Der Preis**: ein `dataclasses.replace()` auf `AgentDefinition` verliert die Markierung, die Isolation fällt stillschweigend weg.

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

Installiert in einem Zug die Hooks, die die Workbench braucht. Genau das ruft `Runtime._attempt`.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `workbench` | `Workbench` | Pflicht, Positionsargument | Wird an `index_guard` und `spill_guard` übergeben |
| `delegate_only` | `bool` | `True` | Nur bei `True` wird `delegate_guard` installiert |
| `spill_threshold` | `int \| None` | `4000` | Nur wenn truthy wird `spill_guard` installiert |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | Nur wenn **irgendeine** davon mit `isolated()` markiert ist, wird `isolate_guard` angehängt |
| `allow_glance` | `bool` | `False` | Wird an `delegate_guard(allow_glance=)` durchgereicht |

Ergebnis:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  gibt es eine markierte Rolle → `isolate_guard(agents)` angehängt.
- `PostToolUse`: immer `[index_guard(workbench)]`; ist `spill_threshold` truthy →
  `spill_guard(workbench, threshold=spill_threshold)` angehängt.
- **Event-Keys mit leerer Liste werden entfernt**, es wird keine leere Liste zurückgegeben.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Hängt** mehrere Hook-Konfigurationen pro Event-Name aneinander.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | Variadisch | Beliebig viele Gruppen. `None`-Gruppen werden übersprungen |

Nutzt `extend`, **ohne Deduplizierung** — derselbe Guard zweimal übergeben heißt zweimal installiert. `Runtime` benutzt es, um `spec.hooks`,
`workbench_hooks(...)` und `whitelist_guard` zusammenzuführen.

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

Das Arbeitsverzeichnis für Spills: drei Unterverzeichnisse + ein Index. Der Index wird **in den System-Prompt injiziert**, damit der Agent
in jeder Runde weiß, was er zur Hand hat.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `workspace` | `Path` | Pflicht, Positionsargument | Arbeitsbereich. `__post_init__` macht ein resolve |
| `dirname` | `str` | `".flower"` | Name des Workbench-Verzeichnisses, relativ zu `workspace` |
| `max_index_entries` | `int` | `40` | **Betrifft nur `prompt_block()`**: wie viele Einträge pro Kategorie in dem in den System-Prompt injizierten Abschnitt maximal aufgeführt werden; der Rest wird zu einer Zeile „… und N weitere" zusammengefasst. `INDEX.md` selbst ist unbeschränkt und listet alles |
| `home` | `Path \| None` | `None` | Wenn gesetzt, wird das als `root` benutzt und **`dirname` ignoriert**. Nicht-`None` wird ebenfalls resolved |

| Member | Signatur | Beschreibung |
|---|---|---|
| `root` | `@property -> Path` | Wenn `home` gesetzt, dieses, sonst `workspace / dirname` |
| `external` | `@property -> bool` | Ob `root` **außerhalb** von `workspace` liegt. Im Isolationsmodus sollte das `True` sein |
| `scripts` | `@property -> Path` | `root / "scripts"`, Skripte, die ein zweites Mal laufen sollen |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, lange Ergebnisse über 2000 Zeichen |
| `notes` | `@property -> Path` | `root / "notes"`, wichtige Entscheidungen, eine Datei pro Entscheidung |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | Der Pfad, den das Modell sieht: innerhalb des Arbeitsbereichs relativ, außerhalb absolut |
| `ensure` | `() -> Workbench` | mkdir für die drei Verzeichnisse, gibt `self` zurück (verkettbar: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(Anzeigepfad, Beschreibung, Bytes)`. Rekursiv per `rglob("*")`, Dateien mit `.` am Anfang werden übersprungen |
| `refresh` | `() -> str` | Schreibt `INDEX.md` neu und gibt den Inhalt zurück |
| `prompt_block` | `() -> str` | **Der in den System-Prompt injizierte Abschnitt.** Absichtlich kurz gehalten — er ist in jeder Runde dabei |

Format der Skript-Selbstbeschreibung: ein `# desc: ein Satz` innerhalb der ersten 8 Zeilen (auch `//` und `--` werden als Kommentarzeichen erkannt),
mit Rückfall auf den ersten nichtleeren Kommentar oder die erste Zeile des docstring (auf 100 Zeichen gekürzt).

Die drei Regeln, die `prompt_block()` injiziert:

1. Skripte, die ein zweites Mal laufen sollen, gehen nach `scripts/`, erste Zeile `# desc:`.
2. Ergebnisse über **2000 Zeichen** gehen nach `artifacts/`, im Dialog nur Pfad und Ergebnis.
3. Wichtige Entscheidungen gehen nach `notes/`, eine Datei pro Entscheidung.

Bei `external=True` fügt `prompt_block()` zusätzlich den Satz „greif per absolutem Pfad darauf zu" ein.

**Den Index erben subagents nicht.** Er läuft über das Session-weite `system_prompt.append`, und ein subagent hat seinen eigenen
System-Prompt (gemessen $0.2461). Deshalb müssen die zwei Punkte „lange Ergebnisse nach `artifacts/`" und „wo die Workbench liegt" vom
[Koordinator](glossary.md#协调者) im [Task Brief](glossary.md#任务书) weitergegeben werden — **das ist der einzige Kanal**, keine Redundanz.
In `WORKER_RULES` steht das **absichtlich nicht**: den echten Pfad erzeugt `Workbench`, fest verdrahtet wäre er falsch.

---

## Session Store {#会话存储}

Quelle: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Drei Vererbungsstufen: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime` benutzt **immer die äußerste**, die Strategien aller drei Stufen werden über Konstruktorparameter gesteuert.

Jede Stufe macht eine Sache: persistieren, nach Volumen und Wert [trimmen](glossary.md#裁剪), nach „ist das ein Fehler" [prunen](glossary.md#剪除).
Trim und Prune passieren beide im Moment von **`load()`** (also wenn resume die Historie zurück ins Modell füttert), an den Rohdaten in SQLite ändert sich kein Byte.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implementiert das `SessionStore`-Protokoll des SDK, drei Tabellen `entries` / `meta` / `summaries`.
Der store key ist `project_key/session_id[/subpath]` — **die transcripts von sub-Agents werden per subpath unterschieden**.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `path` | `str \| Path` | Pflicht, Positionsargument | Die Datenbankdatei. Die Verbindung nutzt `check_same_thread=False` |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `append` | `async (key, entries) -> None` | Idempotente Dedup per uuid (zuerst schon Persistiertes weg, dann Duplikate innerhalb des Batches). Beim Replay eines ganzen Batches wird **die mtime nicht vorgerückt und keine fold summary wiederholt**; nur das Haupt-transcript (`subpath is None`) nimmt an der summary teil |
| `projects` | `() -> list[str]` | Die tatsächlich in der DB vorhandenen `project_key`. **Das SDK leitet ihn aus dem cwd ab; vor einer Abfrage damit bestätigen, nicht raten** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **Synchron, liest kein payload**, fragt nur eine meta-Zeile ab. Für „Kontinuität am selben Pfad" — der resume einer nicht existierenden Session fliegt erst auf, wenn der Subprozess hochgekommen ist |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | Wie groß der Kontext war, den das Modell in der letzten Runde tatsächlich gesehen hat; nicht gefunden → `0`. Scannt nur die letzten `scan` Einträge rückwärts; `input + cache_read + cache_creation` werden alle drei gezählt (nur `input_tokens` unterschätzt massiv) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | Nach seq sortiert; keine Zeilen → `None` |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | Nur Haupt-transcripts |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | Listet die Session-Zusammenfassungen |
| `delete` | `async (key) -> None` | Beim Löschen eines Haupt-transcripts werden **die der sub-Agents kaskadierend mitgelöscht**, um Waisen zu vermeiden |
| `list_subkeys` | `async (key) -> list[str]` | Listet die sub-transcripts dieser Session |
| `close` | `() -> None` | Verbindung schließen |

Das interne `_next_mtime` garantiert **strenge Monotonie** — `list_sessions` und die summary-sidecar teilen sich diese Uhr,
sonst fehlurteilt der staleness-Fastpath des SDK.

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
| `keep_recent` | `int` | `20` | Die letzten N `tool_result` behalten den Originaltext |
| `min_chars` | `int` | `2000` | Kurze Ergebnisse sind das Trimmen nicht wert |
| `spill_dirname` | `str` | `".flower/spill"` | **Relativ zu `workspace`, muss innerhalb des Arbeitsbereichs liegen** — sonst kommt das `Read` des Agents nicht daran |
| `enabled` | `bool` | `True` | Bei `Runtime(trim=False)` steht hier `False` |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | Erzeugt die Zeigerzeile, die den Text ersetzt |

**Die zwei Spill-Verzeichnisse sind nicht dasselbe.** `spill_guard` landet in `<workbench.root>/spill/` (darf außerhalb des Arbeitsbereichs liegen);
`TrimPolicy.spill_dirname` landet in `<workspace>/.flower/spill/` (**muss innerhalb des Arbeitsbereichs liegen**).
Die zwei entsprechen „sofort trimmen" und „beim resume trimmen"; die unterschiedlichen Verzeichnisse sind Absicht, nicht zu einem zusammenlegen.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

Die Ablaufstrategie für Ergebnisse von [Ephemeral Commands](glossary.md#一次性命令).

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `enabled` | `bool` | `True` | Abgeschaltet passiert überhaupt keine Ablaufmarkierung |
| `keep_recent` | `int` | `6` | Die letzten N sind befreit. **Deutlich kleiner als die 20 von `TrimPolicy`** |
| `max_chars` | `int` | `2000` | Darüber wird übersprungen und `TrimPolicy` archiviert es |
| `text` | `str` | siehe Signatur | Ersatztext, mit den zwei Platzhaltern `{cmd}` und `{age}` |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | Erzeugt den Ersatztext über `text` |

**Wirkt nur auf Ergebnisse des `Bash`-Tools**, und das Kommando muss auf die Whitelist der Ephemeral Commands passen. **`Read` gehört nicht dazu** —
Dateiinhalte veralten nicht so, dass sie mit der Zeit in die Irre führen. Abgelaufener Inhalt wird **nicht gespillt**, sondern direkt verworfen.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Entscheidet, ob ein Bash-Kommando ein [Ephemeral Command](glossary.md#一次性命令) ist.
**Die Durchlassprüfung von `delegate_guard` und die Ablaufprüfung des Trimmens nutzen dieselbe Funktion** — die Menge der Kommandos, die der Koordinator selbst ausführen darf,
muss gleich der Menge sein, deren Ergebnisse als abgelaufen markiert werden. Durchlassen ohne Trimmen: ein abgelaufenes `git status` belegt dauerhaft Kontext und führt zusätzlich in die Irre;
Trimmen ohne Durchlassen: der Koordinator schickt für ein `ls` einen subagent los, 4.3k Startkosten für ein paar Dutzend Zeichen.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `cmd` | `str` | Pflicht, Positionsargument | Die vollständige Kommandozeile |

Prüfreihenfolge:

1. Leer / nur Whitespace → `False`.
2. Kommandosubstitution (`$(`, Backticks, `<(`, `>(`) oder eine „ändert Zustand"-Schreibweise trifft zu → `False`.
3. Nach Entfernen sicherer Redirects (`2>&1`, `&> /dev/null` und Ähnliches) enthält es weiterhin `>` oder `<` → `False`.
4. Nach Entfernen von `&&` / `||` / `;` / `|` bleibt ein einzelnes `&` übrig (Hintergrundausführung) → `False`.
5. An `&&` / `||` / `;` / `|` aufteilen, **jedes Segment muss die Whitelist treffen**.

Whitelist-Verben, grob nach Kategorie: lesende `git`-Unterkommandos (`status` `diff` `log` `show` `branch` `rev-parse` usw.),
Verzeichnis- und Systeminfos (`ls` `pwd` `df` `du` `date` `whoami` `env` usw.), Prozesse und Container
(`ps` `top` `lsof` `docker ps` `kubectl get` usw.), Dateien ansehen (`cat` `head` `tail` `wc` `stat` `find` `tree`),
Pfade nachschlagen (`which` `whereis` `command -v` `type`), Textverarbeitung (`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` usw.).

Auch wenn das Verb auf der Whitelist steht, werden diese Schreibweisen abgefangen: `xargs`, `exec`, `eval`, `source`, `tee`,
`find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` und `print >` in `awk`,
`git branch -D/-d/-m`, `git * --force/--hard/--prune`.

Die erste Version hat pauschal alle zusammengesetzten Kommandos abgelehnt, was **glance in der Messung komplett wirkungslos machte**
(alle drei Versuche des Koordinators wurden abgefangen), deshalb wurde auf segmentweise Prüfung umgestellt.

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
| `path` | `str \| Path` | Pflicht | Die Datenbankdatei |
| `workspace` | `str \| Path` | Pflicht | Basis für das Spill-Verzeichnis |
| `policy` | `TrimPolicy \| None` | `None` | Ohne Angabe das Default `TrimPolicy()` |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | Ohne Angabe das Default `EphemeralPolicy()` |

Öffentliche Attribute: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

Die Reihenfolge in `load()`: `super().load()` → `last_report` leeren → bei `ephemeral.enabled` `expire()` →
bei `policy.enabled` `trim()`. **Bei `enabled=False` fällt der jeweilige Schritt komplett weg.**

| Methode | Beschreibung |
|---|---|
| `expire(entries)` | Ersetzt bei abgelaufenen zeitkritischen `Bash`-Ergebnissen **nur den Text, der Block bleibt**. Das Kommando wird im `tool_use` der vorangehenden assistant-Nachricht gesucht; `isCompactSummary` / `isMeta` werden übersprungen; alles über `max_chars` wird übersprungen (das übernimmt `trim`); die letzten `keep_recent` sind befreit. Schreibt `last_report["expired"]` |
| `trim(entries)` | Der Text von `tool_result` mit `>= min_chars` wird nach `<workspace>/<spill_dirname>/<sha256 erste 16 Stellen>.txt` gespillt, der Blockinhalt wird durch einen Zeiger ersetzt; die letzten `keep_recent` sind befreit. Schreibt `cleared` / `kept` / `chars_saved` in `last_report` |

**Getrimmt wird nur reiner Text**: `image`- / `document`-Blöcke bleiben unverändert.

**Zwei strukturelle rote Linien**: der `tool_result`-**Block selbst muss bleiben**, nur der content darf ersetzt werden (fehlt einer, heißt es
„Missing Tool Result Block"); `isCompactSummary`-Einträge dürfen nicht angefasst werden.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Rendert `store.last_report` in eine chinesische Zeile für das UI-Log.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | Pflicht, Positionsargument | Nimmt auch die Unterklasse `PruningSessionStore` |

Drei Ausgaben: keine Aktion → `"未裁剪"`; nur Ablauf → `"N 个时效性结果标记为过期"`;
sonst `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, mit X = `chars_saved // 4`.

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    keep_denials: int = 1
```

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | Entfernt synthetische API-Fehlermeldungen (Reste abgerissener Verbindungen) |
| `neutralize_interrupts` | `bool` | `True` | Ersetzt von einem Abbruch übrig gebliebene `tool_result` durch einen neutralen Hinweis |
| `interrupt_text` | `str` | siehe Signatur | Der Text des neutralen Hinweises |
| `keep_denials` | `int` | `1` | Die letzten N abgelehnten Tool-Aufrufe behalten |

Der Grund für `keep_denials`: ein abgelehnter Aufruf wurde nie ausgeführt, im Ergebnis steckt keine Information, aber er belegt nicht wenig Platz (gemessen einmal 273 Zeichen =
93 Zeichen Ablehnungstext + 180 Zeichen **Originaltext des toten Kommandos**). Wichtiger noch: **er führt in die Irre** — gemessen hat der Koordinator, nachdem er ein paar
„Bash nicht direkt benutzen" gelesen hatte, selbst das durchgelassene `git status` nicht mehr versucht und erlernte Hilflosigkeit ausgebildet.
**Default ist 1 und nicht 0**: die jüngste Ablehnung verhindert, dass das Modell in derselben Runde dasselbe abgefangene Kommando immer wieder probiert.

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
| `path` | `str \| Path` | Pflicht | Die Datenbankdatei |
| `workspace` | `str \| Path` | Pflicht | Basis für das Spill-Verzeichnis |
| `policy` | `TrimPolicy \| None` | `None` | Trim-Strategie |
| `prune` | `PrunePolicy \| None` | `None` | Prune-Strategie |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | Ablaufstrategie |

Öffentliche Attribute über die der Elternklasse hinaus: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (erst `expire` + `trim`) → `self.prune(entries)`. `prune` macht drei Dinge:

1. **Entfernt zu alte abgelehnte Aufrufe**: erkannt über die strukturelle Markierung `toolDenialKind == "permission-rule"` der harness
   (zuverlässiger als das Matchen von Ablehnungstexten), die letzten `keep_denials` bleiben, bei den übrigen werden `tool_use` **und** `tool_result`
   gemeinsam entfernt. Stecken in einer assistant-Nachricht mehrere `tool_use`, wird **nur der getroffene entfernt**, sonst wird es
   „Missing Tool Result Block"; Text- und thinking-Blöcke bleiben.
2. **Entfernt synthetische API-Fehlermeldungen.** In SQLite bleiben sie unverändert, sie werden nur nicht zurückgefüttert.
3. **Ersetzt vom Abbruch übrig gebliebene `tool_result` durch einen neutralen Hinweis** — nur der Text wird ersetzt, der Eintrag bleibt.

**Die einzige strukturelle rote Linie**: das transcript ist eine `parentUuid`-Einfachkette; entfernt man einen Eintrag, müssen seine Kinder an den nächsten überlebenden Vorfahren angehängt werden.
Das `entries` des internen `relink` **muss die vollständige Liste sein (inklusive der zu entfernenden)**, das Filtern macht es selbst —
filtert der Aufrufer vorher und übergibt erst danach, reißt die Kette genau dort und die ganze vorangehende Historie ist weg (**bereits reingetreten: solange die entfernten Einträge am Ende liegen, fällt es nicht auf,
in der Mitte fliegt es auf**).

**Die Parameterreihenfolge weicht von der Elternklasse ab**: die Elternklasse hat `(path, workspace, policy, ephemeral)`, die Unterklasse
`(path, workspace, policy, prune, ephemeral)` — **das vierte Positionsargument ist von `ephemeral` zu `prune` geworden**,
positionsbasiert übergeben verschiebt sich das stillschweigend. Grundsätzlich per keyword übergeben.

---

## Resilience {#韧性}

Quelle: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

Bei Netzausfall hängend warten statt mit Fehler aussteigen. Vier Exporte: eine Strategie-dataclass + drei einzeln nutzbare Probe-Funktionen.

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
| `enabled` | `bool` | `True` | Abgeschaltet wird bei keinem Fehler erneut versucht |
| `max_attempts` | `int` | `6` | **inklusive des ersten Versuchs** |
| `base_delay` | `float` | `4.0` | Backoff-Basis, Sekunden |
| `max_delay` | `float` | `120.0` | Backoff-Obergrenze, Sekunden |
| `probe_timeout` | `float` | `5.0` | Timeout einer einzelnen Probe |
| `probe_interval` | `float` | `15.0` | Wartezeit zwischen zwei Proben |
| `max_offline_wait` | `float` | `3600.0` | Wie lange maximal hängend gewartet wird, Default 1 Stunde |
| `retry_unknown` | `bool` | `True` | Ob nicht klassifizierbare Fehler wiederholt werden |
| `resume_prompt` | `str` | siehe Signatur | Was beim Weiterlaufen gesagt wird. **Enthält absichtlich keine Fehlerdetails** — das Modell muss wissen „du wurdest unterbrochen, mach weiter", nicht ob es `ENOTFOUND` oder 503 war |

| Methode | Signatur | Beschreibung |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)`, danach mal `0.75 + random()*0.5` (±25 % Jitter) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, oder `kind == "unknown"` und `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | Hängend warten, bis das Netz zurück ist. Kommt es zurück → `True`, über `max_offline_wait` → `False`. `notify` ist ein `(str) -> None`-Callback, der **beim ersten Nichterreichen** und **bei der Wiederherstellung** je einmal feuert |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Teilt Fehlertexte in die drei Klassen `"transient"` / `"fatal"` / `"unknown"` ein.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `text` | `str \| None` | Pflicht, Positionsargument | Der Originaltext der Fehlermeldung. Leer → `"unknown"` |

**Erst fatal prüfen, dann transient** — Texte wie 401 enthalten häufig das Wort `connection`, in umgekehrter Reihenfolge wartet man sich zu Tode.

| Klasse | Was trifft |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

Host und Port, die geprobt werden; folgt `ANTHROPIC_BASE_URL`, Default `https://api.anthropic.com`;
Port Default `80` (http) oder `443`.

**Bei einem selbst gehosteten Gateway muss man genau dieses proben** — dass `api.anthropic.com` erreichbar ist, sagt nichts über das Gateway.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `host` | `str` | Pflicht, Positionsargument | Hostname |
| `port` | `int` | Pflicht, Positionsargument | Port |
| `timeout` | `float` | `5.0` | Sekunden |

**Macht nur DNS (`getaddrinfo`) + TCP-Handshake**, kein HTTP, keine Credentials, **kostet nichts**. Jede Exception gilt als nicht erreichbar.

---

## Events und Interaktion {#事件与交互}

Quellcode: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

Ein [Event](glossary.md#事件) ist die stabile Struktur, auf die der SDK-Message-Stream flachgeklopft wird.
**Die [Interaktionsschicht](glossary.md#交互层) kennt nur `Event` und importiert keinen einzigen SDK-Typ** —
das ist die Grenze, dank der ein UI-Wechsel den Kern nicht anfasst. Siehe [Interaktionsschicht austauschen](../guide/interaction.md).

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
| `tool` | `str` | `""` | Tool-Name, nur bei `tool_call` gesetzt |
| `payload` | `dict[str, Any]` | `{}` | strukturierte Zusatzinformation |
| `raw` | `Any` | `None` | das rohe SDK-Objekt, für den Fall, dass man tiefer graben will |

`__str__`: bei `tool_call` ist es `f"[{tool}] {text}"`, sonst `text`, und bei leerem `text` `f"<{kind}>"`.
`print(ev)` ist damit direkt lesbar.

`EventKind` hat insgesamt **15** Werte:

| kind | Sender | Beschreibung |
|---|---|---|
| `text` | `normalize` | Assistant-Fließtext |
| `thinking` | `normalize` | Thinking-Block |
| `tool_call` | `normalize` | Tool-Aufruf. `text` ist eine Zusammenfassung aus `file_path` / `command` / `pattern`, auf 200 Zeichen gekürzt |
| `tool_result` | `normalize` | Tool-Ergebnis. `text` auf 500 Zeichen gekürzt, `payload` enthält `tool_use_id` / `is_error` |
| `task` | `normalize` | die drei Task-Messages, `text` ist der Klassenname der Message |
| `system` | `normalize` | alle übrigen System-Messages, `text` ist der Subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, `payload` enthält `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | synthetische API-Fehlermeldung, `payload` enthält `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **Der Text ist Eingabe, nicht Modellausgabe**, landet also nicht in `StepResult.text` |
| `unknown` | `normalize` | nicht erkannt |
| `retry` | `Runtime` | Retry-Benachrichtigung |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | im payload `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | Frage, **trägt auch „was der Mensch von sich aus sagt"** |

**Die letzten vier werden nicht von `normalize()` erzeugt.**

Das `payload` aller Assistant-/User-Events enthält:

| Key | Typ | Beschreibung |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | nur vorhanden, wenn `subagent` wahr ist |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **Das ist die einzige Quelle für das [Handoff](glossary.md#换代)-Kriterium** und zugleich die Zahl, die man bei einem long-horizon Run am dringendsten sehen sollte |

**Der kind `ask` trägt gleichzeitig „Frage" und „was der Mensch von sich aus sagt".** Bei letzterem gilt
`payload["kind"] == "mail"`, und **es gibt kein `options` / `remaining`**. Das UI muss zuerst
`payload.get("kind")` prüfen und dann entscheiden, wie es rendert, sonst hängt es einen Satz als
unbeantwortete Frage auf.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Klopft eine SDK-Message auf 0 bis N `Event` flach.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `message` | `Any` | Pflicht, positional | beliebiges SDK-Message-Objekt |

Die wesentlichen Zweige:

- **Synthetische API-Fehlermeldung** (`isApiErrorMessage=True` oder `model == "<synthetic>"`) → ein einzelnes
  `Event("error", payload={"synthetic": True})`. **Das ist Absicht** — sonst landet der Verbindungsabbruch-Text
  als Fließtext in `StepResult.text` und wird an den nächsten Step weitergegeben.
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
| `id` | `str` | Pflicht | wird beim Antworten zur Zuordnung benutzt |
| `question` | `str` | Pflicht | Text der Frage |
| `options` | `list[str]` | `[]` | Auswahlmöglichkeiten. Der Mensch kann auch nichts auswählen und selbst tippen |
| `asked_at` | `float` | `time.time()` | Zeitpunkt der Frage |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | Text der Antwort |

| Member | Signatur | Beschreibung |
|---|---|---|
| `waited_s` | `@property -> float` | wie lange schon gewartet wurde |
| `event` | `(remaining: int = 0) -> Event` | erzeugt `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

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

Ein **In-Process-MCP-Server** (zwei Tools) plus eine Gruppe von Methoden für das UI. Das Modell sieht nur
`mcp__human__ask` und `mcp__human__inbox`. Alle Konstruktorparameter sind keyword-only.

| Parameter | Typ | Default | Beschreibung |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | Ausgang des **Push**-Modus. Ist er gesetzt, verdrahtet `Workflow.run` nichts mehr |
| `max_asks` | `int \| None` | `None` | **unbegrenzt**. Eine Zahl ist ein hartes Kontingent, `0` = Fragen verboten (vollautomatisch / CI). Bei Überschreitung **weist das Tool direkt ab, ohne zu blockieren** |
| `timeout_s` | `float \| None` | `1800.0` | 30 Minuten. `None` = ewig warten; **`<= 0` = nicht warten, alle Fragen laufen sofort ins Leere** |
| `log_path` | `str \| Path \| None` | `None` | Fragen und Antworten werden **angehängt** auf Platte geschrieben, ohne Kontext zu belegen |
| `amend_path` | `str \| Path \| None` | `None` | Was der Mensch mitten im Run sagt, wird an diese Datei angehängt (üblicherweise der Brief). **Ohne Persistierung überlebt es die Step-Grenze nicht** — der nächste Step ist eine neue Session und liest nur den eingefrorenen Stand |
| `over_budget_text` | `str` | Modulkonstante | was dem Modell bei Kontingentüberschreitung zurückgegeben wird |
| `timeout_text` | `str` | Modulkonstante | was dem Modell bei Timeout zurückgegeben wird |
| `declined_text` | `str` | Modulkonstante | was dem Modell zurückgegeben wird, wenn übersprungen wurde |

Öffentliche Attribute: die acht gleichnamigen Konstruktorparameter, dazu `asks: list[Ask]`, `mail: list[Mail]`
und `ui_errors: list[str]` (**Exceptions aus UI-Callbacks werden hier gesammelt und brechen den Run nicht ab**).

| Member | Signatur | Beschreibung |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | direkt an `AgentSpec.mcp_servers` weitergeben. **Der Key muss mit dem Server-Namen übereinstimmen**, deshalb liefert die Methode beides zusammen |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | hängt und wartet auf den Menschen. **Wirft außer `CancelledError` niemals eine Exception** — dass niemand antwortet, ist auch eine Antwort; unterschieden wird über `ask.state` |
| `send` | `(text: str) -> Mail \| None` | der Mensch sagt von sich aus etwas. **Aus jedem Thread aufrufbar.** Unterbricht den Agent nicht; ruft intern automatisch `amend()` |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | hängt an `amend_path` an. Rückgabe: ob wirklich geschrieben wurde (kein Pfad konfiguriert, leerer Text, `OSError` → alle `False`) |
| `pending_mail` | `() -> list[Mail]` | noch nicht abgeholte Mail |
| `remaining` | `@property -> int` | wie viele Fragen noch möglich sind. **Bei `max_asks=None` wird `-1` zurückgegeben**, nicht 0 und nicht unendlich |
| `pending` | `() -> list[Ask]` | aktuell offene, auf Antwort wartende Fragen |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | für den **Pull**-Modus. Bei Timeout `None`, bei Cancel eine Exception |
| `answer` | `(ask_id: str, text: str) -> bool` | antworten. `False` = diese Frage wartet nicht mehr (Timeout / schon beantwortet) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | überspringen und das Modell selbst entscheiden lassen |
| `transcript` | `() -> str` | Markdown des Frage-Antwort-Protokolls |

**Von den zwei Abholarten genau eine wählen**: **Push** — `HumanChannel(on_event=...)` konstruieren;
**Pull** — `await channel.next_ask()`. `Workflow.run` verdrahtet nur dann automatisch, wenn
`channel.on_event is None` ist; wer selbst etwas übergibt, wird also nicht überschrieben.

**Threadübergreifend**: `answer` / `decline` / `send` gehen intern über `loop.call_soon_threadsafe`,
der Aufruf aus einem Web-Backend oder einem TUI-Eingabethread ist der Normalfall.

Die drei „0 / None"-Semantiken sind jeweils unterschiedlich, nicht verwechseln: `max_asks=None` = unbegrenzt,
`max_asks=0` = Fragen verboten; `timeout_s=None` = ewig warten, `timeout_s<=0` = sofortiger Timeout;
`remaining` ist bei `max_asks=None` gleich `-1`.

`Mail` wird nicht exportiert, erscheint aber in Rückgabewerten: eine Dataclass mit den Feldern
`id` / `text` / `sent_at` / `taken`.

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

Hält prozessübergreifend fest, welcher Step welche Session benutzt hat; die [Kontinuität](glossary.md#接续)
findet darüber, wie weit der letzte Lauf gekommen ist. Die Datei ist `<run_dir>/lineage.json`.

| Feld | Typ | Default | Beschreibung |
|---|---|---|---|
| `path` | `Path` | Pflicht | Pfad der Lineage-Datei |
| `workspace` | `Path` | Pflicht | Workspace. `__post_init__` resolved ihn |
| `steps` | `dict[str, str]` | `{}` | Step-Name → `session_id` |
| `woke` | `int` | `0` | wie oft geweckt wurde |

| Member | Signatur | Beschreibung |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | liest `<run_dir>/lineage.json`. **Existiert die Datei nicht, ist sie nicht lesbar oder passt das Feld `workspace` nicht, wird ausnahmslos ein leeres Objekt zurückgegeben, ohne Fehler** |
| `remember` | `(step: str, session_id: str) -> None` | merkt sich das Mapping und **schreibt es sofort auf Platte**. Leerer Step oder leere sid → sofortiges Return |
| `bump` | `() -> int` | Wake-Zähler +1, auf Platte schreiben, neuen Wert zurückgeben (beim ersten Lauf `1`) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **verschiebt** die Lineage-Datei plus `extra` nach `<into>/<YYYYmmdd-HHMMSS>/` und setzt `steps` / `woke` zurück. **Verschieben, nicht löschen** |

Das Schreiben läuft über den atomaren Austausch `tmp.replace(path)`; `OSError` wird stillschweigend
geschluckt — ein fehlgeschlagener Schreibvorgang darf diesen Run nicht mitnehmen.

**`workspace` ist die Absicherung**: Der `project_key` des SDK wird aus dem Workspace-Pfad abgeleitet;
nach dem Wegkopieren des Verzeichnisses ist die alte `session_id` nicht mehr auffindbar. Passt der Pfad
nicht, gilt der Eintrag also als nicht vorhanden.

Wenn `Workflow.run` die Lineage lädt, prüft es jeden Eintrag einzeln mit `runtime.has_session(sid)`, ob er
noch in der Datenbank liegt, und benutzt ihn nur, wenn er lebt — die Lineage-Datei kann `sessions.db`
überleben.

---

## Minimale lauffähige Beispiele {#示例}

Alle fünf Abschnitte laufen direkt. Voraussetzung: `claude-agent-sdk` installiert, `ANTHROPIC_API_KEY` oder
`ANTHROPIC_AUTH_TOKEN` verfügbar (sonst wirft schon `Runtime(...)` beim Konstruieren einen `RuntimeError`).

### Ein Agent, ein Step {#示例-单-agent}

Minimalgerüst: einen `AgentSpec` deklarieren, ein `Runtime` bauen, `await rt.run(...)`, `StepResult` lesen.

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

Die Parameter von `Runtime` sind **ausnahmslos keyword-only**; bei `rt.run()` sind `spec` und `prompt`
positional, alles Übrige keyword-only. `AgentSpec` hat als Default `allowed_tools=["Read", "Glob", "Grep"]`
und `delegate_only=False`, also hängt `Runtime` automatisch [`whitelist_guard`](#whitelist-guard) an und
blockt `Bash`/`Write`/`Edit`/`NotebookEdit` komplett.

### Koordinator + Worker {#示例-协调}

Ein [Koordinator](glossary.md#协调者), der nicht selbst zupackt, mit einem [Worker](glossary.md#执行者),
der die Arbeit macht. Das ist die erste Schicht, mit der flower Kontext spart.

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
    # ohne Workbench hält kein einzelner Hook das Bash/Write des Koordinators auf.
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

Die ersten zwei Parameter von `worker()` sind positional: `description` (womit der Koordinator auswählt) und
`prompt` (sein System-Prompt, an den anschließend automatisch `WORKER_RULES` angehängt wird). Bei
`coordinator()` sind die ersten drei positional: `name`, `instructions`, `workers`.

### Einen eigenen Workflow schreiben {#示例-workflow}

Zwei Steps, wobei der zweite das Ergebnis des ersten in seinen eigenen Prompt injiziert — billig, isoliert,
ohne gemeinsame Session.

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
        # Neue Session + Ergebnis des vorherigen Steps in den Prompt injiziert (billig, gegen Verunreinigung)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # Wer in derselben Session weiterreden will, schreibt resume_from="造句"; zum Forken zusätzlich fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (wenn kein reduce gesetzt ist)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # bei on_fail="stop": in welchem Step es fehlgeschlagen ist


asyncio.run(main())
```

Die ersten drei Felder von `Step` (`name` / `spec` / `prompt`) sind positional, ebenso `steps` bei `Workflow`.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` positional, die beiden Callbacks
keyword-only. **Achtung: `continuous=True` ist der Default**: Beim zweiten Lauf mit demselben `run_dir` und
demselben `workspace` reden auch Steps mit `resume_from=None` in derselben Session wie beim letzten Mal weiter.

### Einen Zielwächter dazuhängen {#示例-目标}

Zuerst lässt man den [Judge](glossary.md#判定者) Ziel und Prüfliste festschreiben, dann lässt man den
Arbeits-Step ein Verdict akzeptieren — wer nicht durchkommt, läuft mit dem Feedback erneut, maximal drei Runden.

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
    # rounds ist die **Gesamtzahl der Runden**: rounds=3 → retries=2 → maximal drei Arbeitsrunden
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # Der Prompt von goal_step liest ctx["确认需求"] (Default von brief_key).
        # Ohne clarify_step muss man selbst etwas hineingeben, sonst sieht es nur "(没有确认书)".
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY: Goal-Objekt
    print(ctx["_verdict"])     # VERDICT_KEY: das letzte Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY: wie viele Runden gelaufen sind
    print(ctx.get("_aborted")) # Grund des StepAbort (wenn unerreichbar und niemand antwortet)


asyncio.run(main())
```

`with_goal` tauscht nur `gate` / `on_reject` / `retries` aus; alle übrigen Felder werden mit
`dataclasses.replace` unverändert übernommen. Der Judge läuft in einer **eigenen Session**: `gate` ruft intern
separat `rt.run(judger, ..., step_name=f"{label}#{轮次}")` auf, `resume` ist immer `None`.

### Die Interaktionsschicht austauschen {#示例-交互层}

Um das Terminal gegen Web / TUI / HTTP zu tauschen, muss man nur zwei Dinge ändern: die Funktion, die `Event`
rendert, und die Coroutine, die Fragen abholt.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Rendert Event in dein eigenes UI — das ist das Einzige, was ausgetauscht werden muss."""
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
    # kind == "ask" und kein mail: übernimmt der answerer unten (Pull-Modus)


async def answerer(ch: HumanChannel) -> None:
    """Fragen im Pull-Modus abholen. Beim Wechsel auf Web-Backend / HTTP-Service ist diese Coroutine die einzige Stelle, die man ändert."""
    while True:
        ask = await ch.next_ask()          # ohne timeout wird endlos gewartet
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # oder ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime benutzt die Workbench, die der Workflow selbst gebaut hat — keine zweite zusammenstückeln
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push und Pull: **eines von beiden wählen**. Push heißt `HumanChannel(on_event=...)` konstruieren, Pull heißt
`await channel.next_ask()`. `Workflow.run` verdrahtet nur dann automatisch, wenn `channel.on_event is None`
ist; wer selbst ein `on_event` übergibt, wird also nicht überschrieben.
`answer()` / `decline()` / `send()` / `interrupt()` **sind alle aus anderen Threads aufrufbar**.

---

## Fallen und Fehlerquellen {#陷阱}

Sortiert nach der Reihenfolge, in der man hineintritt, nicht nach Modul. Jeder Punkt hat eine gemessene
Herkunft.

### Aufbau {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = im Main Thread steht keine einzige Wand.**
   `delegate_guard` wird nur mit Workbench installiert, und `whitelist_guard` wird durch
   `delegate_only=True` übersprungen. Wer einen Koordinator einsetzt, schaltet die Workbench ein.
   Details unter [Runtime](#runtime).
2. **Es gibt zwei Orte für die Workbench, nicht verwechseln.** `Runtime(workbench=True)` landet in
   `<run_dir>/workbench`; `Workbench(ws)` ist per Default `<ws>/.flower`. Wer `brief_path` selbst
   zusammensetzt, schreibt es nach der zweiten Variante — sonst **wird der Brief in Verzeichnis A geschrieben,
   der injizierte Index scannt Verzeichnis B, und es gibt keinen Fehler.**
   Richtig: Der Workflow macht selbst `Workbench(...).ensure()`, hängt das an `Workflow.workbench` und gibt
   **dasselbe Objekt** an `Runtime(workbench=wb)`.
3. **`allowed_tools` ist keine exklusive Whitelist, sondern eine Liste ohne Genehmigungspflicht.** Das Modell
   kann Tools, die nicht drinstehen, weiterhin aufrufen. Dass `clarify()` / `judge()` „keine Schreibtools"
   haben, hängt am Hook [`whitelist_guard`](#whitelist-guard).
   Und `coordinator()` hat als Default `permission_mode="acceptEdits"` — wer diesen Wert an
   `clarify()` / `judge()` durchreicht, hat den Schutz weg.
4. **`disallowed_tools` gilt sessionweit** und verbietet gleichnamige Tools auch in Subagents.
5. **Der Workbench-Index erreicht keine Subagents.** „Lange Ausgaben nach `artifacts/` schreiben" muss der
   Koordinator im Task Brief weitererzählen, das ist der einzige Kanal.
6. **Ohne Credentials wirft `Runtime(...)` schon in der Konstruktionsphase einen `RuntimeError`**, nicht erst
   bei `run()`.
7. **`Runtime.run_id` muss pro Instanz eindeutig sein.** `manifest.json` dedupliziert über das Feld `run`;
   kollidieren zwei ids, löscht der spätere Schreiber die Zeilen des anderen als „meine letzten Zeilen".

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` ist der Default**, `resume_from=None` heißt nicht „ganz neue Session".
   Wer jedes Mal neu starten will, setzt explizit `continuous=False`. **Ein geänderter Step-Name kappt die
   Lineage.**
9. **`with_goal(rounds=N)` ist die Gesamtzahl der Runden, nicht die Zahl der Zusatzrunden**:
   `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` schreibt `ctx[step.name]` nicht** — ein nachgelagertes `lambda ctx: ctx["某步"]` läuft
    in einen `KeyError`. Wer mit einem unvollständigen Ergebnis weitergehen will, nimmt `on_fail="continue"`.
11. **Ein `resume_from` auf einen nicht gelaufenen oder fehlgeschlagenen Step wirft `ValueError`**, es wird
    nicht stillschweigend übersprungen.
12. **`Step.reduce` muss synchron sein; `gate` / `when` / `on_reject` dürfen async sein.**
13. **`fork=True` ohne `resume` ist stillschweigend wirkungslos.** `Workflow` übergibt nie ein `resume_at`;
    ein Rollback auf Message-Ebene geht nur über den direkten Aufruf von `Runtime.run`.
14. **Wer `Runtime` selbst steuert, muss `on_session` vor dem Gate abhängen**, sonst wird die Session des
    Judge in die Lineage des Arbeits-Steps geschrieben. `Workflow` stellt das per `try/finally` sicher.
15. **`step_name` bestimmt die Keys in Manifest und Lineage.** `Workflow` hängt `#retryN` / `#roundN` an, der
    Judge hängt `#轮次` an — **Namen mit Suffix landen nicht in der prozessübergreifenden Lineage**, und genau
    so ist „der Judge ist immer eine neue Session" unter anderem implementiert.

### Rollen {#陷阱-角色}

16. **`clarify(max_turns=<kleine Zahl>)` macht „unbegrenzt viele Fragen" zu einer leeren Behauptung** — jede
    Frage ist eine Runde.
17. **`goal_step()` hat keinen Parameter `can_run`**, `can_run=True` geht nur über `**spec_kw`.
    Ohne das bekommt der zielsetzende Judge kein `Bash`, und die Regel „schau dir erst genau an, in welcher
    Umgebung du bist" aus `JUDGE_RULES` ist nicht ausführbar.
18. **`judge(can_run=True)` erlaubt dem Judge, den Workspace zu verändern** — `whitelist_guard` leitet sich
    aus `allowed_tools` ab, mit `Bash` wird also `Bash` durchgelassen (`Write`/`Edit` bleiben geblockt, aber
    `Bash` selbst kann Dateien schreiben). Wer absolute Neutralität will, lässt es aus.
19. **`worker(isolate=True)` verlangt, dass der Workspace ein Git-Repository ist**, sonst meldet das Tool
    `Agent` direkt `"not in a git repository"` und degradiert nicht stillschweigend. Außerdem ist die
    Isolation-Markierung ein Python-Attribut: **ein `dataclasses.replace()` auf `AgentDefinition` verliert
    sie.**
20. **Beim direkten Konstruieren von `AgentDefinition` sind die Parameter camelCase**: `maxTurns`,
    `permissionMode`. `worker()` hat die Umwandlung schon für dich gemacht.

### Handoff und Kontext {#陷阱-换代}

21. **Bei aktiviertem Handoff wird Auto-Compact zwangsweise abgeschaltet, ohne Auffangnetz.** Der Step, der
    das Handoff-Dokument schreibt, braucht deshalb zwingend einen Degradationspfad. Wer Auto-Compact behalten
    will, setzt `AgentSpec.compact` explizit.
22. **Ein zu klein konfiguriertes `HandoffPolicy.window` verbrennt Geld mit endlosen Handoffs.** Die einzige
    Bremse ist `max_generations=8`.
    Am anderen Ende gilt: **`default_window()` gibt auch dann `1_000_000` zurück, wenn keine der beiden
    Umgebungsvariablen gesetzt ist** — ein zu großer Wert wird von `is_overflow()` aufgefangen (es wird ein
    degradiertes Handoff), das ist kein harter Fehler, aber das Handoff dieser Generation ist degradiert.
23. **Ohne Workbench wird das Handoff-Dokument nicht auf Platte geschrieben.** Der Text geht trotzdem per
    Prompt an den Nachfolger, aber der Mensch findet ihn hinterher nicht wieder.

### Storage {#陷阱-存储}

24. **`Runtime(trim=False)` (der Default) heißt nicht „es wird nichts aufgeräumt".** Der Store ist immer ein
    `PruningSessionStore`; `trim=False` schaltet nur das Trimmen großer Ergebnisse ab. **Reste von
    Verbindungsabbrüchen entfernen, abgelehnte Aufrufe entfernen, Überreste von Unterbrechungen
    neutralisieren und zeitlich abgelaufene Dinge verfallen lassen passiert weiterhin.**
25. **Die zwei Spill-Verzeichnisse sind nicht dasselbe**: `spill_guard` landet in
    `<workbench.root>/spill/`, `TrimPolicy.spill_dirname` in `<workspace>/.flower/spill/` (muss innerhalb des
    Workspace liegen).
26. **Der vierte positionale Parameter von `PruningSessionStore.__init__` ist `prune`, nicht `ephemeral`** —
    anders als in der Basisklasse. Positionale Übergabe verrutscht stillschweigend.

### Dokumente und Interaktion {#陷阱-文书}

27. **Lässt sich aus einem `Verdict` keine Schlussfolgerung parsen, ist `state=""` und `ok=False`; das darf
    niemals als erreicht gelten.**
    Außerdem fallen „无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" alle unter `unreachable` und
    lösen den Pfad „anhalten und den Menschen fragen" aus, nicht „noch eine Runde".
28. **Trifft `Brief.parse` auf einen nicht geschlossenen Code-Fence, verwirft es alles danach** — bei
    abgeschnittener Modellausgabe lassen sich die folgenden Abschnitte nicht mehr parsen, `complete()` ist
    `False`, und das Gate schickt es zurück.
29. **`Brief.load` behandelt `"(未填)"` als leer.** Wer beim manuellen Editieren des Briefs den
    Platzhaltertext stehen lässt, dessen Abschnitt gilt weiterhin als fehlend.
30. **Die drei „0 / None" in `HumanChannel` haben jeweils andere Semantik**: `max_asks=None` unbegrenzt,
    `max_asks=0` Fragen verboten; `timeout_s=None` ewig warten, `timeout_s<=0` sofortiger Timeout;
    `remaining` gibt bei `max_asks=None` **`-1`** zurück.
31. **`Event("ask")` trägt gleichzeitig Fragen und was der Mensch von sich aus sagt**, letzteres mit
    `payload["kind"] == "mail"`. Das UI muss das zuerst prüfen.
32. **`Workflow.run` verdrahtet nur dann automatisch, wenn `channel.on_event is None` ist** — wer
    `HumanChannel(on_event=...)` selbst konstruiert, bekommt Frage-Events nicht zusätzlich am `on_event`-
    Ausgang des Workflows.
