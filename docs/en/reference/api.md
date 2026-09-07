# Python API

This page exhaustively covers the **62 public symbols** in `flower`'s top-level `__all__`: signatures, parameters, defaults, semantics, public attributes and methods. Once you've read it you shouldn't need to open the source to look up a parameter.

It is organised by **what you care about**, not by module file — if you want to know "how do I stop the [coordinator](glossary.md#协调者) from doing the work itself", go to the [hook layer](#hook); if you want to know "how does the result of one step reach the next", go to [workflow](#流程). Terminology follows the [glossary](glossary.md) throughout.

Version `0.1.0`, depends on `claude-agent-sdk>=0.2.152`. Every signature corresponds verbatim to the source.

```python
from flower import Runtime, Workflow, Step, coordinator, worker   # 顶层一次导入
```

## What's on this page {#索引}

| What you care about | Symbols |
|---|---|
| [Running an agent](#运行时) | `Runtime` `StepResult` |
| [Chaining steps together](#流程) | `Step` `Workflow` `StepAbort` `clarify_step` `goal_step` `with_goal` `starter_flow` `wake_state` `BRIEF_KEY` `MISSING_KEY` `CLARIFY_RESUME` `GOAL_KEY` `VERDICT_KEY` `ROUND_KEY` |
| [Building a role](#角色工厂) | `coordinator` `worker` `clarify` `judge` `oracle` `COORDINATOR_RULES` `WORKER_RULES` `CLARIFIER_RULES` `JUDGE_RULES` `ORACLE_RULES` |
| [Hand-writing an agent definition](#agent-定义) | `AgentSpec` `build_options` `CompactPolicy` `HandoffPolicy` `default_window` |
| [Structured documents](#文书) | `Brief` `Handoff` `Goal` `Verdict` |
| [Intercepting tools, trimming results, splitting isolation](#hook) | `whitelist_guard` `delegate_guard` `spill_guard` `index_guard` `isolate_guard` `isolated` `wants_isolation` `workbench_hooks` `merge_hooks` |
| [The spill working directory](#工作台) | `Workbench` |
| [How sessions are stored, and what](#会话存储) | `SqliteSessionStore` `TrimmingSessionStore` `PruningSessionStore` `TrimPolicy` `EphemeralPolicy` `PrunePolicy` `is_ephemeral` `trim_report` |
| [What to do when the network drops](#韧性) | `Resilience` `classify` `endpoint` `reachable` |
| [Swapping out the UI](#事件与交互) | `Event` `normalize` `Ask` `HumanChannel` |
| [Picking up where you left off across processes](#血缘) | `Lineage` |

## Six defaults that will bite you {#危险默认值}

These six are not trivia — they are the six most common ways to crash. Each has a full explanation in its own section.

| Default | Consequence | See |
|---|---|---|
| `Runtime(workbench=False)` + `coordinator()` | The main thread's `Bash`/`Write`/`Edit` have **not a single hook** on them | [Runtime](#runtime) |
| `Runtime(handoff=True)` | Forces `CompactPolicy(mode="no_summary")` onto the spec, i.e. `DISABLE_AUTO_COMPACT=1` | [Runtime](#runtime) |
| `Workflow(continuous=True)` | A step with `resume_from=None` still picks up that previous session across processes | [Workflow](#workflow) |
| `build_options(fork=True)` without `resume` | Silently does nothing, no error | [build_options](#build-options) |
| `clarify(max_turns=<small number>)` | Turns "ask as many questions as you like" into an empty promise — each question is one turn | [clarify()](#clarify-role) |
| `AgentSpec.disallowed_tools` | Session-scoped; it bans the tool for subagents too | [AgentSpec](#agentspec) |

---

## Runtime {#运行时}

Source: [`flower/core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)

`Runtime` is the execution core. It holds the workspace, the [session store](glossary.md#会话存储), the [workbench](glossary.md#工作台), the [resilience](glossary.md#韧性) policy and the [handoff](glossary.md#换代) policy, and exposes exactly one verb: `run` one step. Retry, resuming after an interruption, and handing off when the context fills up all happen inside that single call.

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

Constructor parameters are **all keyword-only** (`*` comes first); `workspace` is required.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `workspace` | `str \| Path` | required | The agent's `cwd`. Resolved and `mkdir(parents=True, exist_ok=True)` at construction. The SDK's `project_key` is derived from it — move the directory elsewhere and the old `session_id` is no longer findable |
| `run_dir` | `str \| Path` | `"runs"` | Holds `sessions.db`, `manifest.json`, `lineage.json`, and the default workbench when `workbench=True`. Also resolved and mkdir'd |
| `portable` | `bool` | `True` | Passed through to `build_options(portable=)`, i.e. `setting_sources=[]`: does not read the host's `~/.claude/`, nor the project's `.claude/`. See [portable](glossary.md#可移植) |
| `trim` | `TrimPolicy \| bool` | `False` | An instance is used as-is; a `bool` becomes `TrimPolicy(enabled=bool(trim))`. **Turning it off only stops trimming large results; pruning still happens** |
| `ephemeral` | `EphemeralPolicy \| bool` | `True` | Same conversion rule. Pairs with `coordinator(glance=True)` — if you let the main thread run `git status`, you'd better make sure that result expires |
| `keep_denials` | `int` | `1` | Passed to `PrunePolicy(keep_denials=)`. Keeps the last N denied tool calls; earlier ones have both call and result removed |
| `workbench` | `Workbench \| bool` | `False` | An instance is used as-is; `True` builds `Workbench(workspace, home=run_dir / "workbench")` (**outside the workspace by default**). `refresh()` is then called immediately |
| `spill_threshold` | `int \| None` | `4000` | How many characters a tool result must exceed before it [spills](glossary.md#落盘). `None` or `0` = no `spill_guard` installed |
| `resilience` | `Resilience \| bool` | `True` | Same conversion rule |
| `handoff` | `HandoffPolicy \| bool` | `True` | Same conversion rule |

**The session store is hard-wired**: always
`PruningSessionStore(run_dir/"sessions.db", workspace=..., policy=<TrimPolicy>, ephemeral=<EphemeralPolicy>, prune=PrunePolicy(keep_denials=...))`.
The constructor offers **no** entry point for swapping the backend — to swap it, build your own `AgentSpec` + `build_options(session_store=...)`, or overwrite `rt.store` after construction.

The last two steps of construction are `load_dotenv()` and `check_credentials()`, and **the latter raises `RuntimeError` on failure**. With no credentials it blows up at construction time, not at `run()`.

!!! warning "`workbench=False` + `coordinator()` = not a single wall on the main thread"
    `delegate_guard` is only installed inside `workbench_hooks`, and `workbench_hooks` is only called when `self.workbench is not None`; `whitelist_guard` is in turn skipped by `if not spec.delegate_only`. And `coordinator()` always sets `delegate_only=True`, with `glance=True` by default granting `Bash`.

    **Conclusion: a coordinator paired with `Runtime(workbench=False)` has no hook whatsoever intercepting its `Bash`/`Write`/`Edit`.**
    If you use `coordinator()`, turn the workbench on — `Runtime(..., workbench=True)` or pass a `Workbench` instance.

!!! warning "`handoff=True` (the default) forcibly disables auto-compact"
    In `_attempt`: `handoff.enabled and spec.compact is None` → `spec = replace(spec, compact=CompactPolicy(mode="no_summary"))`, which reaches the subprocess as `DISABLE_AUTO_COMPACT=1`. The reason is that with both mechanisms on at once, you can't tell which one caused the context to drop.

    **The price: the step that writes the handoff must have a degraded path** (`handoff.degraded`), because there's no compact as a fallback any more.
    To keep auto-compact, set `AgentSpec.compact` explicitly (if the spec sets it, that's respected and not overwritten).

#### Public attributes {#runtime-属性}

| Attribute | Type | Description |
|---|---|---|
| `workspace` | `Path` | The resolved workspace |
| `run_dir` | `Path` | The resolved run directory |
| `portable` | `bool` | Stored as given |
| `store` | `PruningSessionStore` | The session store. Swapping the backend is only possible by overwriting it after construction |
| `resilience` | `Resilience` | The normalised instance |
| `handoff` | `HandoffPolicy` | The normalised instance |
| `workbench` | `Workbench \| None` | `None` when `workbench=False` |
| `spill_threshold` | `int \| None` | Stored as given; passed to `workbench_hooks` in `_attempt` |
| `results` | `list[StepResult]` | Every step this process has run, appended in order |
| `run_id` | `str` | `"%Y%m%d-%H%M%S" + "-" + uuid4().hex[:6]`. **Must be unique per instance** — `manifest.json` deduplicates on the `run` field, so if two ids collide the later writer will delete the other's row believing it to be its own previous write |
| `on_session` | `Callable[[str], None] \| None` | Called back **immediately** when a new `session_id` arrives; default `None`. **Should only wrap the single `runtime.run` call** — the [judge](glossary.md#判定者) uses the same `Runtime`, and leaving it attached during the gate would write the judge's session into the [lineage](glossary.md#血缘) of the working step |

Class constants: `INTERRUPTED = "interrupted-by-human"`, `HANDOFF_DUE = "context-full-handoff"`, and `INTERRUPT_NOTE` (a paragraph appended after the human's words when resuming from an interruption, explaining that "tool calls in flight returning interrupted is a normal side effect of the interruption, not an environment failure").

#### Public methods {#runtime-方法}

| Method | Signature | Description |
|---|---|---|
| `run` | `async (spec, prompt, *, step_name=None, resume=None, fork=False, resume_at=None, on_event=None) -> StepResult` | Run one step. See below |
| `interrupt` | `(message: str = "") -> None` | Request an interruption of the current turn. **Callable from any thread**. Cooperative: it breaks cleanly at a **message boundary**, no hard cancel. Empty string = interrupt without saying anything |
| `rescue` | `() -> None` | Get the books as complete as possible before being hard-killed; called by the `SIGHUP`/`SIGTERM` handlers. The in-flight step is also written to the manifest with `error="killed-by-signal"`. Only does small synchronous writes |
| `manifest_path` | `@property -> Path` | `run_dir / "manifest.json"` |
| `project_key` | `@property -> str` | `str(workspace.resolve())` with every `/`, `_` and `.` replaced by `-`. **The SDK derives it from cwd; the caller cannot specify it** |
| `has_session` | `(session_id: str) -> bool` | Is this id still findable **under this workspace**? Synchronous, does not read the payload |
| `context_of` | `(session_id: str) -> int` | The context size of a session's last turn; delegates to `store.last_context` |
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

| Parameter | Type | Default | Description |
|---|---|---|---|
| `spec` | `AgentSpec` | required, positional | The agent declaration to run |
| `prompt` | `str` | required, positional | What is said this turn |
| `step_name` | `str \| None` | `None` | The key recorded in `StepResult.step`, the manifest and the lineage. `None` → `spec.name` |
| `resume` | `str \| None` | `None` | Resume this `session_id` |
| `fork` | `bool` | `False` | Fork off a new session without polluting the original. **Only effective when `resume` is truthy** |
| `resume_at` | `str \| None` | `None` | Resume from a particular message (rollback). Also **only effective when `resume` is truthy** |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Event outlet, see [`Event`](#event) |

Each step starts by zeroing the context watermark (`self._ctx, self._warned = 0, False`). What follows is a loop with four exits:

1. **Success** → break out.
2. **Human interruption** (`result.error == INTERRUPTED`) → **not bound by `max_attempts`**, does not wait for the network.
   `resume` the same session carrying the human's words, `attempt -= 1` (an interruption doesn't count as a failed attempt), prompt = the human's words + `INTERRUPT_NOTE`.
   **If no `session_id` was obtained, there's nothing to do but stop.**
3. **Context full** (`result.error == HANDOFF_DUE`, or `handoff.enabled` and a `session_id` was obtained and `is_overflow(...)` fires) → **also not bound by `max_attempts`**. First check `len(result.retired) >= handoff.max_generations`; if exceeded, replace the error with a diagnostic line and break out; otherwise write the [handoff document](glossary.md#交接书) → `resume=None, fork=False` (**a brand-new session**) → replace the prompt with `h.prompt_block()` → zero the watermark → `attempt -= 1`.
4. **Retryable failure** → break out if `not resilience.enabled or attempt >= max_attempts`; break out if `classify(error)` says it shouldn't be retried; otherwise emit `Event("retry")`, hang on `wait_online()` waiting for the network, `sleep(delay_for(attempt))`; **if a `session_id` was ever obtained, `resume` it** (with the prompt replaced by `resilience.resume_prompt`) and set `result.resumed` to `True`.

Wrap-up: write `ended_at`, append to `self.results`, write `manifest.json`.

`manifest.json` has **append** semantics: every write re-reads the file from disk and deduplicates on the `run` field (its own row is replaced, other rows are left alone), so running two flowers in parallel under the same `run_dir` is safe — provided the `run_id`s don't collide.

**Three observation points for handoff** (all `Event("handoff")`, distinguished by `payload["phase"]`):
`near` (approaching `warn_at`, emitted once per generation), `writing` (the handoff is being written, takes a dozen or so seconds), `done` (payload carries `degraded` / `path` / `sections`). The turn that writes the handoff runs with `replace(spec, max_budget_usd=None)` — the handoff must be writable, it cannot be blocked by the budget; and `on_event=None`, so that turn does not stream to the UI.

The handoff is spilled to `<workbench.notes>/交接-<步骤名>.md`; **with no workbench there is no spill**, the document still reaches the successor through the prompt, you just can't look it up afterwards. The old handoff is moved to `notes/archive/交接/<名>-<时间戳>.md`.

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

The complete books for one finished step.

| Field | Type | Default | Description |
|---|---|---|---|
| `step` | `str` | required | Step name (`step_name` or `spec.name`) |
| `session_id` | `str \| None` | `None` | **Always the last session to take over** — the ones burned by handoffs along the way are in `retired` |
| `ok` | `bool` | `False` | Whether this step succeeded |
| `cost_usd` | `float` | `0.0` | US dollars. **Accumulated** across retries and handoffs |
| `num_turns` | `int` | `0` | Turn count, likewise accumulated |
| `text` | `str` | `""` | **Contains only the main thread's prose**. A subagent's output stays in its own transcript, and the task brief dispatched to it is `kind="prompt"`; neither is included |
| `error` | `str \| None` | `None` | Failure reason. For special values see `Runtime.INTERRUPTED` / `Runtime.HANDOFF_DUE` |
| `started_at` / `ended_at` | `float` | `0.0` | Unix timestamps |
| `attempts` | `int` | `1` | Actual number of attempts. Interruptions and handoffs are **not counted** |
| `errors` | `list[str]` | `[]` | Collected synthetic API error messages, **not merged into `text`** |
| `resumed` | `bool` | `False` | Whether a resume happened partway through |
| `retired` | `list[str]` | `[]` | The `session_id`s burned by handoffs in this step, in order |
| `context` | `int` | `0` | The context size the main thread actually saw on the last turn, i.e. the handoff criterion |

| Property | Type | Description |
|---|---|---|
| `duration_s` | `@property -> float` | `round(ended_at - started_at, 2)`, `0.0` if it never finished |

---

## Workflow {#流程}

Source: [`flower/workflow/`](https://github.com/ChenyuHeee/flower/tree/main/flower/workflow)

A [workflow](glossary.md#流程) is a set of [steps](glossary.md#步骤) strung together in order, plus how state passes between them and when to exit early. **The framework ships no ready-made workflow — you write the workflow.** `starter_flow` is just a working sample.

Type alias `Ctx = dict[str, Any]` (`flower.workflow.base.Ctx`, listed in `flower.workflow.__all__`, not in the top-level `__all__`).

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

The **declaration** of a step. `Step` itself is not a function — what actually executes is `Runtime.run(step.spec, prompt, ...)`. The first three fields are positional, so `Step("取词", terse, "读 seed.txt …")` is legal.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Step name. **A key that is stable across processes** — it lands in `ctx[name]`, `ctx["_results"]`, the manifest and the lineage. Rename it = break the lineage |
| `spec` | `AgentSpec` | required | Which agent to run |
| `prompt` | `str \| Callable[[Ctx], str]` | required | What to say. Can be a closure that computes from `ctx` on the spot |
| `resume_from` | `str \| None` | `None` | Which step's session to resume. If the referenced step produced no session, **raises `ValueError`** — it is not silently skipped |
| `fork` | `bool` | `False` | Fork on top of `resume_from`. **Has no effect without `resume_from`** |
| `retries` | `int` | `0` | How many extra attempts when the gate fails. `retries=0` = a single round |
| `gate` | `Callable[[StepResult, Ctx], bool] \| None` | `None` | Decide whether this attempt passes. **May be async.** Returning `False` counts as failure. **Called exactly once per attempt** — it may have side effects (e.g. spilling the brief to disk) and must not be triggered repeatedly |
| `on_fail` | `str` | `"stop"` | `"stop"` / `"skip"` / `"continue"`, see below |
| `when` | `Callable[[Ctx], bool] \| None` | `None` | Returning `False` **skips the whole step**: no result is produced, nothing enters `ctx["_results"]`. **May be async** |
| `on_reject` | `Callable[[StepResult, Ctx], str] \| None` | `None` | **What to say next round** when the gate fails. **May be async.** Providing it changes retry semantics, see below |
| `resume_prompt` | `str \| Callable[[Ctx], str] \| None` | `None` | The prompt used when continuing (instead of starting over) |
| `reduce` | `Callable[[StepResult, Ctx], str] \| None` | `None` | Decides what goes into `ctx[name]`. Defaults to `result.text` verbatim. **Must be a synchronous function** |

| Method | Signature | Description |
|---|---|---|
| `render` | `(ctx: Ctx, *, resuming: bool = False) -> str` | Uses `resume_prompt` when `resuming` and it exists, otherwise `prompt`; if it is callable, calls it with `ctx` |

**Three ways to wire sessions** (within one run):

| Form | Effect |
|---|---|
| `resume_from=None` (default) | New session, relying only on the context passed in the prompt. Cheap, isolated. **But with `Workflow(continuous=True)` it picks up the session of the same-named step from the cross-process lineage** |
| `resume_from="previous step name"` | Continue the same session, full context. Expensive, coherent |
| `resume_from="previous step name", fork=True` | Fork without polluting the original session. Used for review / parallel alternatives |

**`on_reject` changes retry semantics**:

- Not given → the next attempt **starts over** (same prompt, same `resume_from`).
- Given → the next attempt **continues the session that was just rejected**, with the prompt replaced by its return value, and `fork` forced to `False`.
- Returns an empty string → no push-back; degrades to starting over.
- `result.session_id` is `None` → also degrades to starting over.

**The three values of `on_fail`**:

| Value | Behavior |
|---|---|
| `"stop"` (default) | Writes `ctx["_failed_at"] = name` and **aborts the whole workflow** |
| `"skip"` | Jumps to the next step, **`ctx[name]` is not written** — a downstream `lambda ctx: ctx["某步"]` will raise `KeyError` |
| `"continue"` | `ctx[name] = result.text`, carrying the incomplete result forward |

Pass or fail, `ctx["_results"][name] = result` is always written; when `result.session_id` is non-empty it is also written into `ctx["_sessions"]` and `lineage.remember(...)` is called.

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

Runs a list of `Step`s in order and returns the final `ctx`. `steps` is positional, so `Workflow([...])` is legal.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `steps` | `list[Step]` | required | Executed in order |
| `name` | `str` | `"workflow"` | Workflow name |
| `context` | `Ctx` | `{}` | Initial context dict. **Running the same `Workflow` a second time reuses the same dict** |
| `channel` | `HumanChannel \| None` | `None` | Attach here when you need to stop and ask a human. `run()` automatically wires its `on_event` to the same outlet, **only when `channel.on_event is None`**; the driver program also relies on this field to know who to answer |
| `workbench` | `Workbench \| None` | `None` | The workbench designated by the workflow, so the driver program can find it |
| `continuous` | `bool` | `True` | Same path = same conversation. Implemented by [`Lineage`](#lineage) |

| `run()` parameter | Type | Default | Description |
|---|---|---|---|
| `runtime` | `Runtime` | required, positional | Which runtime to run on |
| `on_event` | `Callable[[Event], None] \| None` | `None` | Event outlet, passed through to every `Runtime.run` |
| `on_step` | `Callable[[Step, StepResult], None] \| None` | `None` | Called once after each step finishes |

!!! warning "`continuous=True` is the default, and `resume_from=None` does not mean a fresh session"
    With continuity on, `run()` first calls `Lineage.open(run_dir, workspace)`, then verifies each record with `runtime.has_session(sid)` to check it is still in the store, and only pours the live ones into `ctx["_sessions"]`. So **even a step with `resume_from=None` will keep talking in last time's session** — the same holds after the process is killed or the machine reboots.

    To get a fresh session every time, write `Workflow(..., continuous=False)` explicitly.
    Also: **the step name is a key stable across processes; renaming a step breaks the lineage.**

The **private keys** `run()` writes into ctx (all start with `_`, so they never collide with step names):

| Key | Contents |
|---|---|
| `_runtime` | The `Runtime` passed in. **Dispatching an agent inside a gate depends on it** |
| `_on_event` | The event outlet. The agent inside a gate also has to reach the UI, otherwise the interface goes dark |
| `_sessions` | `dict[step name, session_id]`, read with `setdefault` |
| `_results` | `dict[step name, StepResult]` |
| `_lineage` | The `Lineage` object. Present only when `continuous=True` and the runtime has `run_dir` + `workspace` |
| `_woke` | The return value of `lineage.bump()` — which wake this is |
| `_aborted` | The message of a `StepAbort` |
| `_failed_at` | The name of the step that failed under `on_fail="stop"` |

Payload of `Event("step")`: `{"index": i, "total": len(steps), "resumed": bool, "woke": int}`.

**Retry labels**: attempt 0 uses `step.name`; afterwards, with `on_reject` it is `f"{name}#round{attempt+1}"`, without it `f"{name}#retry{attempt}"`. The manifest shows at a glance how the step played out.
**Suffixed names do not enter the cross-process lineage** — `Lineage.remember` uses the original name.

`runtime.on_session` covers only the `runtime.run` call, with `try/finally` guaranteeing it is detached before the gate. `prompt_cur` / `resume_cur` / `fork_cur` are local variables and are not written back onto `step` — the same `Step` object may be run a second time.

### `StepAbort` {#stepabort}

```python
class StepAbort(Exception): ...
```

Raised by `gate` = **stop immediately, do not retry**. The difference from returning `False`: `False` means "not this time, try another round"; `StepAbort` means "another round won't help".

After it is raised: `ctx["_aborted"] = str(exc)`, `passed = False`, **the retry loop is exited (remaining `retries` are not consumed)**, then it follows `on_fail` like an ordinary failure (default `"stop"`).

`with_goal` raises it in two places: when `ctx["_runtime"]` is unavailable, and when the verdict is `unreachable` and nobody answers.

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

Produces a `Step` that performs [clarify](glossary.md#前置确认): ask until the requirement is clear → parse into a [`Brief`](#brief) → freeze and spill to disk once all four sections are present.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `channel` | `HumanChannel` | required, positional | The asking channel |
| `brief_path` | `str \| Path` | required | Where the [brief](glossary.md#需求确认书) lands. **It must land in the workbench that is actually injected into the index** |
| `prompt` | `str \| Callable[[Ctx], str]` | required | The human's original ask |
| `name` | `str` | `"确认需求"` | Step name, and also the key in `ctx` |
| `spec` | `AgentSpec \| None` | `None` | If omitted, uses `clarify(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Extra instructions appended for the [clarifier](glossary.md#确认者) |
| `always_ask` | `bool` | `False` | `True` = ask again every time, regardless of whether the brief exists |
| `on_fail` | `str` | `"stop"` | Same as `Step.on_fail` |
| `retries` | `int` | `0` | How many more times to ask when the four sections are incomplete |
| `**spec_kw` | | | Passed straight to [`clarify()`](#clarify-role), so you can write `can_read=False`, `max_budget_usd=...` |

The fields of the produced `Step` are filled like this:

- `resume_prompt = CLARIFY_RESUME`.
- `when`: `always_ask=True` → always `True`; otherwise, if `Brief.load(brief_path)` is complete, pour it into ctx **and then return `False` (skip)** — it must be poured even when skipping, otherwise downstream has no requirement.
- `gate`: `Brief.parse(result.text)`; incomplete → write `ctx[MISSING_KEY]` and return `False`; complete → freeze with `b.write(brief_path)`, pour into ctx, return `True`.
- `reduce`: returns `ctx[BRIEF_KEY].prompt_block()`, **not the model's raw text** — the raw text may carry extra material it wrote.
- `resume_from` **stays at the default `None`**: the next step is a new session that gets only the brief, not the Q&A. The clarify Q&A **never entered** the coordinator's context; it was not trimmed out after the fact.

Three places poured into ctx: `ctx[BRIEF_KEY] = b`, `ctx[name] = b.prompt_block()`, `ctx.pop(MISSING_KEY, None)`.

| Constant | Value | Description |
|---|---|---|
| `BRIEF_KEY` | `"_brief"` | `ctx[BRIEF_KEY]` is the `Brief` object; `ctx[step.name]` is its `prompt_block()` |
| `MISSING_KEY` | `"_brief_missing"` | Which sections are missing when clarification fails (Chinese section names), for the UI to display |
| `CLARIFY_RESUME` | a Chinese prompt | "Continue the clarification you didn't finish just now — **do not start over**…". Without this line, resuming resends the original ask as a new task and the clarifier may re-ask questions it already asked |

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

Produces a `Step` that **sets the goal**: the [judge](glossary.md#判定者) reads the brief, writes the goal plus a verdict checklist, and after parsing into a [`Goal`](#goal) freezes it to disk. Same shape as `clarify_step`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `channel` | `HumanChannel` | required, positional | The asking channel |
| `goal_path` | `str \| Path` | required | Where the goal file lands |
| `brief_key` | `str` | `"确认需求"` | Takes the brief text from `ctx[brief_key]` and puts it into the prompt. **If unavailable it becomes `"(没有确认书)"`** |
| `name` | `str` | `"设定目标"` | Step name |
| `spec` | `AgentSpec \| None` | `None` | If omitted, uses `judge(name, channel, instructions=instructions, **spec_kw)` |
| `instructions` | `str` | `""` | Extra instructions |
| `always_set` | `bool` | `False` | `True` = redo the checklist regardless of whether the goal file exists |
| `on_fail` | `str` | `"stop"` | As above |
| `retries` | `int` | `0` | As above |
| `**spec_kw` | | | Passed through to [`judge()`](#judge-role) |

**There is no `can_run` parameter** — to let the goal-setting judge run commands, you must pass `can_run=True` through `**spec_kw`. Without it the judge gets no `Bash`, and the "first look carefully at what environment you are in" rule in `JUDGE_RULES` cannot be carried out.

Beyond parsing and freezing, the `gate` does one extra thing: when the goal contains `[此环境无法验证:…]` entries, it **immediately** emits an `Event("task", payload={"unverifiable", "total", "path"})` through `ctx["_on_event"]` as a warning — the fate of those entries is decided at goal-setting time, and by verdict time you have already spent a whole round of work.

**No `resume_prompt` is set** — goal setting should resend the full brief anyway.

| Constant | Value | Description |
|---|---|---|
| `GOAL_KEY` | `"_goal"` | `ctx[GOAL_KEY]` is the `Goal` object; `ctx[step.name]` is markdown |
| `VERDICT_KEY` | `"_verdict"` | The most recent [`Verdict`](#verdict), for the UI |
| `ROUND_KEY` | `"_goal_rounds"` | How many verdict rounds have run |

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

Wraps an existing `Step` in a [goal guard](glossary.md#目标看守): after each round the judge rules independently, and if the goal is not achieved it is pushed back for more work.

The result is `replace(step, retries=max(0, rounds - 1), gate=<new gate>, on_reject=<new on_reject>)` — using `dataclasses.replace` rather than rebuilding field by field; a rebuild once dropped `resume_prompt`, **and did not raise**, it merely resent the entire brief on resume.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `step` | `Step` | required, positional | The step being guarded |
| `channel` | `HumanChannel` | required, positional | The channel used to ask a human when the verdict is stuck |
| `goal_path` | `str \| Path` | required | The goal file, read from here when `ctx[GOAL_KEY]` is incomplete |
| `spec` | `AgentSpec \| None` | `None` | If omitted, uses `judge(label, channel, instructions=..., can_run=can_run, **spec_kw)` |
| `rounds` | `int` | `3` | **Total rounds, not extra rounds**: `rounds=3` → `retries=2` → at most three rounds of work. `rounds=1` = run once, judge once, fail if it doesn't pass |
| `instructions` | `str` | `""` | Extra instructions for the judge |
| `can_run` | `bool` | `False` | Whether the judge can run `Bash` |
| `name` | `str \| None` | `None` | The judge's name, default `f"{step.name}·判定"` |
| `**spec_kw` | | | Passed through to `judge()` |

The `gate` is **async**, and goes like this:

1. `ctx["_runtime"]` missing → **raise `StepAbort`** ("拿不到 Runtime,无法判定目标"). **Do not fake a pass.**
2. `ctx[ROUND_KEY] += 1`.
3. Get the goal: prefer a complete `Goal` in `ctx[GOAL_KEY]`, otherwise `Goal.load(goal_path)`, otherwise an empty `Goal()`.
4. `await rt.run(judger, VERIFY_PROMPT..., step_name=f"{label}#{轮次}", on_event=...)`.
   **The judge is an independent `Runtime.run` with `resume` always `None` — always a new session**; `step_name` carries the round number, so it does not enter the cross-process lineage.
5. `Verdict.parse(vr.text)` is written into `ctx[VERDICT_KEY]`.
6. `v.achieved` → return `True`.
7. Not `unreachable` (including the vague case where `v.ok=False`) → add a default reason when vague, return `False`.
   **Vagueness always counts as not achieved** — a "looks fine" must not be allowed to close out the work.
8. `unreachable` → `await channel.ask(...)` to ask the human, with three options:
   - Nobody answers (`a.state != "answered"`) → **raise `StepAbort`**. Continuing to spin is the most expensive choice.
   - "Accept this result and move on" → return `True`.
   - "Amend the goal" → ask once more for the new goal, `g.amend(...).write(goal_path)`, update `ctx[GOAL_KEY]`, return `False`.
   - Anything else (including free-form answers typed by the human) → treated as "you judged wrong": record what the human said into `v.reason` and return `False`.

`on_reject` is **synchronous**: it returns `ctx[VERDICT_KEY].feedback()`, or `""` when there is no `Verdict` (degrading to starting over).

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

Assembles a three-step workflow that runs out of the box: **clarify the requirement → set the goal → do the work** (with a goal guard). This is what the `flower` command line uses.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `ask` | `str` | required, positional | One sentence of ask. **On a wake it is not a new task, it is "one more thing said"** |
| `workspace` | `str \| Path` | `"."` | Workspace |
| `run_dir` | `str \| Path` | `"runs"` | Run directory |
| `new` | `bool` | `False` | `True` = archive lineage + brief + goal (all three together) and start over |
| `isolate` | `bool` | `False` | Give the worker a worktree [isolation](glossary.md#隔离). The workbench moves to `<ws>.parent/.flower-<ws.name>` accordingly |
| `clarify_only` | `bool` | `False` | Return only the Workflow containing the clarify step |
| `goal` | `bool` | `True` | Whether to install the [goal guard](glossary.md#目标看守). `False` = the work step is done when it finishes |
| `rounds` | `int` | `3` | Passed through to `with_goal(rounds=)`, total rounds |
| `judge_can_run` | `bool` | `False` | Passed through to `with_goal(can_run=)` |
| `max_asks` | `int \| None` | `None` | Passed through to `HumanChannel`, `None` = unlimited |
| `timeout_s` | `float \| None` | `1800.0` | Passed through to `HumanChannel`. `0` = fully automatic, every question falls through immediately |
| `instructions` | `str` | `""` | Extra instructions for the clarifier |
| `worker_prompt` | `str` | see signature | The worker's system prompt |
| `brief_name` | `str` | `"需求.md"` | Brief file name, landing in `<workbench.notes>/` |
| `goal_name` | `str` | `"目标.md"` | Goal file name, same place |
| `log_name` | `str` | `"问答记录.md"` | Q&A log file name, same place |

Fixed assembly:

```python
Workflow(name="starter", channel=ch, workbench=wb, steps=[...])
# ch = HumanChannel(log_path=<notes>/问答记录.md, amend_path=<brief_path>,
#                   max_asks=max_asks, timeout_s=timeout_s)
# 协调者 = coordinator("协调者", "", {"coder": worker(..., isolate=isolate)}, channel=ch)
```

Behavioral branches:

- `isolate=True` and the workspace is not a git repository → **raise `ValueError`**, rather than discovering it when the `Agent` tool errors out (by which point the money is spent).
- **Wake detection**: it counts as a wake when `Brief.load(brief_path)` exists and is `complete()`. If it is not a wake and `ask` is empty → **raise `ValueError("要给一句诉求,例如 flower '帮我做一个 X'")`**.
- On a wake, that sentence lands in **three places** at once, and missing any one of them fails silently: appended to the brief (`ch.amend(said, label="唤醒时追加")`, not rewritten if it is already in the file); `goal_step(always_set=True)` redoes the checklist (without redoing it, the judge still reads the old goal); and it is delivered directly to the coordinator (whose context holds the **old** goal — without it, it works to the old standard and is then judged by the new one).

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

**A read-only probe before the run starts; it writes not one byte.** Used to tell the human, before anything actually runs, whether this continues last time or starts from scratch.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `workspace` | `str \| Path` | `"."` | Workspace, positional |
| `run_dir` | `str \| Path` | `"runs"` | Run directory |
| `isolate` | `bool` | `False` | Determines the workbench location; must be the same value you pass to `starter_flow` |
| `brief_name` | `str` | `"需求.md"` | Brief file name |
| `goal_name` | `str` | `"目标.md"` | Goal file name |

The returned dict:

| Key | Type | Description |
|---|---|---|
| `waking` | `bool` | The brief exists and all four sections are present |
| `brief` | `Path` | `<workbench.notes>/需求.md` |
| `goal` | `Path` | `<workbench.notes>/目标.md` |
| `checks` | `int` | Number of checklist entries in the goal, `0` when there is no goal |
| `woke` | `int` | `Lineage.woke` — how many times it has already woken |
| `steps` | `dict` | A copy of `Lineage.steps`, step name → `session_id` |

The workbench location is **defined exactly once here and in `starter_flow`**: `isolate=True` → `<ws>.parent/.flower-<ws.name>` (outside the repository); otherwise `<ws>/.flower`. A driver program that wants to know where the brief is goes through this function too — building the path yourself doesn't raise if you get it wrong, it just fails silently.

---

## Role factories {#角色工厂}

Source: [`flower/core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py)

All five roles are factory functions. Each role = **a block of injected rule text + a set of tools + a set of hooks**.
`worker()` produces the SDK's `AgentDefinition` (to be dispatched to a subagent); the other four produce an [`AgentSpec`](#agentspec)
(they start a session of their own).

The roles themselves **carry no hooks** — intercepting tools is done by `Runtime._attempt`, which installs them
automatically based on `spec.delegate_only`; see [the hook layer](#hook).

Internal tool-set constants (not exported, but they determine the defaults):

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

Builds the [coordinator](glossary.md#主线程) that sits on the [main thread](glossary.md#协调者): it decomposes tasks, dispatches work, reads reports, makes decisions,
**but does not do the work itself**. The first three parameters are positional.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Role name; also the default step name |
| `instructions` | `str` | required | Domain instructions. Ends up as `f"{COORDINATOR_RULES}\n{instructions}".strip()` |
| `workers` | `dict[str, AgentDefinition]` | required | Which roles it has under it; lands in `AgentSpec.agents` |
| `channel` | `HumanChannel \| None` | `None` | If given, appends **both** the `inbox` **and** the `ask` tools, and sets `mcp_servers` |
| `can_read` | `bool` | `True` | `True` → `["Agent", "TodoWrite", "Read"]`; `False` → drops `Read` |
| `glance` | `bool` | `True` | Appends `"Bash"` and sets `AgentSpec.glance`. **What can actually run is gated by `delegate_guard`**, not by this flag |
| `model` | `str \| None` | `None` | Model |
| `effort` | `str \| None` | `None` | Thinking effort |
| `max_turns` | `int \| None` | `None` | Turn cap |
| `max_budget_usd` | `float \| None` | `None` | [Budget](glossary.md#预算) cap |
| `permission_mode` | `str` | **`"acceptEdits"`** | Permission mode. **Watch this default** — passing it to `clarify()`/`judge()` tears down the protection on those two roles |
| `compact` | `CompactPolicy \| None` | `None` | If given, `Runtime` will not force it to `no_summary` |
| `hooks` | `dict[str, Any] \| None` | `None` | Extra hooks, merged with `workbench_hooks` |
| `env` | `dict[str, str] \| None` | `None` | Extra environment variables |

Three fields are fixed in the resulting `AgentSpec`: `delegate_only=True`, `agents=workers`, and
`workbench` keeps `AgentSpec`'s default of `True`.

The source says explicitly: **do not use `disallowed_tools` to implement "coordinate only, hands off"** — that setting is
session-level and will disable `Bash`/`Write` for subagents too; see the warning under [`AgentSpec`](#agentspec).
The correct approach is what's done here: `delegate_only=True` with no `allowed_tools`,
and then [`delegate_guard`](#delegate-guard) blocks only the main thread, by `agent_id`.

Passing `channel` gives you **both tools together**, not a choice: once the MCP server is mounted both are present, and
`allowed_tools` is not exclusive — listing them or not, the model can still call them. Unattended, every `ask` will burn the
full `timeout_s` — for that situation use `HumanChannel(timeout_s=0)`.

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

Builds the definition of the [subagent](glossary.md#subagent) that actually does the work. The first two parameters are positional.
The return value is the SDK's `AgentDefinition`, to be dropped straight into `coordinator(workers={...})`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `description` | `str` | required | **What the coordinator picks a worker on** — spell out "what kind of work goes to it" |
| `prompt` | `str` | required | Its system prompt. With `discipline=True` it becomes `f"{prompt}\n\n{WORKER_RULES}"` |
| `tools` | `list[str] \| None` | `None` | `None` → `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str` | **`"inherit"`** | Workers should not be downgraded |
| `effort` | `str \| int \| None` | `None` | Thinking effort |
| `max_turns` | `int \| None` | `None` | Maps to the SDK's **`maxTurns`** (camelCase) |
| `permission_mode` | `str \| None` | `None` | Maps to the SDK's **`permissionMode`** (camelCase) |
| `skills` | `list[str] \| None` | `None` | Which skills it is allowed to use |
| `discipline` | `bool` | `True` | Whether to append the reporting discipline in `WORKER_RULES` |
| `isolate` | `bool` | `False` | Sets the [isolation](glossary.md#隔离) marker, routing through `isolated()`. **Not a field of `AgentDefinition`** |

`isolate=True` requires the workspace to be a git repository; otherwise the `Agent` tool errors out with `"not in a git repository"` —
it **does not silently degrade**. And since the marker is a Python attribute, running `dataclasses.replace()` on an `AgentDefinition`
drops it, and isolation silently stops working.

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

Builds the [clarifier](glossary.md#确认者): before anything is built, it pins down the requirement — it does no work, only asks questions, and finally emits exactly four sections.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Role name, positional |
| `channel` | `HumanChannel` | required | Question channel, positional |
| `instructions` | `str` | `""` | Extra instructions, appended after `CLARIFIER_RULES` |
| `can_read` | `bool` | `True` | When `True`, appends `Read` `Glob` `Grep` `WebFetch` `WebSearch` |
| `model` | `str \| None` | `None` | Model |
| `effort` | `str \| None` | `None` | Thinking effort |
| `max_turns` | `int \| None` | `None` | **No turn cap** |
| `max_budget_usd` | `float \| None` | `None` | Budget cap |

The resulting `AgentSpec`: `allowed_tools = [channel.tool_name] + (those five when readable)`,
`mcp_servers = channel.mcp_servers()`, `workbench=False` (it has no write tools, so the index means nothing to it),
and `permission_mode` inherits `AgentSpec`'s default of `"default"`.
**No `Write` / `Edit` / `Bash` / `Agent`, and no `inbox`** (unlike the coordinator).

!!! warning "A small `max_turns` turns unlimited questioning into an empty promise"
    Every question is one turn. `max_turns=16` means "ask a dozen or so at most", and the channel's claim of "no turn cap" is void on the spot.

    To really open up questioning you must open **both**: `HumanChannel.max_asks` (already `None` = unlimited by default)
    and `max_turns` (already `None` by default).

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

Builds the [judge](glossary.md#判定者): it either sets the goal before the run starts, or renders a verdict on each round after it ends.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Role name, positional |
| `channel` | `HumanChannel` | required | Question channel, positional |
| `instructions` | `str` | `""` | Extra instructions, appended after `JUDGE_RULES` |
| `can_run` | `bool` | `False` | When `True`, adds `Bash` to the whitelist; `whitelist_guard` then lets `Bash` through while still blocking `Write`/`Edit` |
| `model` | `str \| None` | `None` | Model |
| `effort` | `str \| None` | `None` | Thinking effort |
| `max_turns` | `int \| None` | `None` | Turn cap |
| `max_budget_usd` | `float \| None` | `None` | Budget cap |

The resulting `AgentSpec`: `allowed_tools = [channel.tool_name, "Read", "Glob", "Grep"]` + (when `can_run`) `["Bash"]`,
`workbench=False`, everything else as in `clarify()`. **No `Write` / `Edit` / `Agent`, and no `inbox`.**

**The trade-off**: `can_run=True` makes verdicts harder (it can actually run acceptance commands), at the cost that the judge can now
modify the workspace — `Bash` alone can write files. If you want an absolutely neutral verdict, leave it off.

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

Builds the [oracle](glossary.md#旁路顾问): while a run is still going, you ask it "where are we now", and it takes a look at recent events and the workbench
before answering. **Nothing it says enters the context of that run.**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | `"旁路问答"` | Role name, positional |
| `instructions` | `str` | `""` | Extra instructions, appended after `ORACLE_RULES` |
| `model` | `str \| None` | `None` | Model |
| `effort` | `str \| None` | `None` | Thinking effort |
| `max_turns` | `int \| None` | **`12`** | Braked by default |
| `max_budget_usd` | `float \| None` | **`0.5`** | Braked by default. This is a "quick question on the side"; it should not run away |

The resulting `AgentSpec`: `allowed_tools = ["Read", "Glob", "Grep"]` (**no channel** — it does not ask questions,
it only answers), `workbench=True` (**the only non-coordinator of the five with the workbench on** — reading those artifacts and notes is exactly its job).

### The five rule texts {#rules}

All five constants are in `__all__`; you can `import` them directly to read, splice, or modify.

| Constant | Injected into | How | Key points |
|---|---|---|---|
| `COORDINATOR_RULES` | `coordinator()` | `f"{RULES}\n{instructions}".strip()` | You are "a person who knows how to use Claude Code", not a worker; you may not write files, change code, or run tests; `Bash` is only enough for "a glance" and its results go stale; **a [task brief](glossary.md#任务书) states only what is specific to this task**; the only remaining convention worth stating is "where the workbench is + long artifacts go in `artifacts/` + reply with paths only"; check `inbox` once after every milestone action; `ask` blocks, so use it only at a real fork in the road |
| `WORKER_RULES` | `worker()` | Appended **after** the subagent's `prompt` | Reply format **conclusion / evidence / artifacts / unverified**, at most 30 lines; no pasting file contents, command output, logs, or raw diffs; no recounting trial and error; check `.flower/scripts/` before starting. **Deliberately does not say "long artifacts go in `artifacts/`"** — the real path is generated by `Workbench`, so hardcoding it would be wrong |
| `CLARIFIER_RULES` | `clarify()` | `f"{RULES}\n{instructions}".strip()` | Do no work, only clarify the requirement; **no cap on the number of questions, ask until it is clear**; the human may be away, so on timeout decide for yourself and record it under 「未知与假设」; output **exactly four sections**; don't write code, don't paste file contents |
| `JUDGE_RULES` | `judge()` | `f"{RULES}\n{instructions}".strip()` | One of two jobs. **Setting the goal**: every checklist item must be verifiable on the spot, the length of the checklist is determined by the number of ways it can fail, **boundaries are not check items**, and any item that cannot be verified gets `[此环境无法验证:原因]` appended. **Rendering the verdict on a round**: output **exactly three sections**, judge the **artifacts, not the source**, disbelieve "it's done" by default, and "didn't achieve it" and "can't be verified here" are two different conclusions — the latter **must never be passed** |
| `ORACLE_RULES` | `oracle()` | `f"{RULES}\n{instructions}".strip()` | You are a side channel; that run is still going, you neither interrupt nor participate; **read-only**; discarded after answering, nothing you say enters that run's context; all you have is the "recent event window" and the "workbench"; look before you answer, say so if you can't, keep it short |

---

## Agent definition {#agent-定义}

Source: [`flower/core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)

`AgentSpec` is the complete declaration of a single-purpose agent; `build_options` compiles it into the SDK's `ClaudeAgentOptions`.
[Role factories](#角色工厂) produce `AgentSpec` — when you need a combination outside the factories, construct it directly.

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

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Role name. Also the default `step_name` for `Runtime.run`, and how it refers to itself in `whitelist_guard` rejection messages |
| `instructions` | `str` | required | Domain instructions. **[Appended](glossary.md#叠加) after Claude Code's native system prompt, not a replacement** |
| `allowed_tools` | `list[str]` | `["Read", "Glob", "Grep"]` | **An auto-approve list, not an exclusive whitelist** — the model can still call tools not on it. Exclusivity comes from [`whitelist_guard`](#whitelist-guard) |
| `disallowed_tools` | `list[str]` | `[]` | **Session-level.** See the warning below |
| `model` | `str \| None` | `None` | Model |
| `effort` | `str \| None` | `None` | Thinking effort |
| `max_turns` | `int \| None` | `None` | Turn cap |
| `max_budget_usd` | `float \| None` | `None` | [Budget](glossary.md#预算) cap |
| `permission_mode` | `str` | `"default"` | Permission mode |
| `agents` | `dict[str, Any] \| None` | `None` | Table of subagent definitions; values are `AgentDefinition` |
| `mcp_servers` | `dict[str, Any]` | `{}` | MCP server table. `HumanChannel.mcp_servers()` fills this directly |
| `hooks` | `dict[str, Any] \| None` | `None` | Extra hooks; `Runtime` merges them with its own via `merge_hooks` |
| `compact` | `CompactPolicy \| None` | `None` | If given, `Runtime` will not force it to `no_summary` |
| `env` | `dict[str, str]` | `{}` | Environment variables injected into the subprocess. `compact.env()` is `update`d on top |
| `glance` | `bool` | `False` | Lets the coordinator run "just a glance" `Bash` itself. What gets through is decided by [`is_ephemeral`](#is-ephemeral), and the result is marked stale by `EphemeralPolicy` |
| `workbench` | `bool` | `True` | Whether to inject the workbench index into this agent's system prompt. **Roles with no write tools should turn it off** (`clarify()` / `judge()` default to `False`) |
| `delegate_only` | `bool` | `False` | Coordinate only, hands off. When `True`, `Runtime` installs `delegate_guard` and **does not install** `whitelist_guard` |

!!! warning "`disallowed_tools` is session-level and disables subagents too"
    The verbatim error observed: `"Bash is disabled for this session, in subagents as well as here"`.
    In other words, if you set `disallowed_tools=["Bash"]` to keep the coordinator hands-off, the workers you dispatch can't run commands either —
    the whole run is dead.

    For "coordinate only, hands off", use `delegate_only=True` with no `allowed_tools`, and let
    [`delegate_guard`](#delegate-guard) block only the main thread, by `agent_id`.

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

Compiles an `AgentSpec` into the SDK's `ClaudeAgentOptions`. This is what `Runtime._attempt` calls internally;
it is also the entry point when you drive the SDK yourself (without `Runtime`).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `spec` | `AgentSpec` | required, positional | The declaration to compile |
| `cwd` | `str \| Path \| None` | `None` | Only written into `cwd` when not `None` |
| `session_store` | `SessionStore \| None` | `None` | Only writes `session_store` and `session_store_flush` when not `None` |
| `resume` | `str \| None` | `None` | Which session to resume |
| `fork` | `bool` | `False` | Maps to `fork_session`. **Nested inside `if resume:`** |
| `resume_at` | `str \| None` | `None` | Maps to `resume_session_at`. **Also nested inside `if resume:`** |
| `use_plugin` | `bool` | `True` | `True` and `PLUGIN_DIR` exists → `plugins=[{"type": "local", "path": ...}]` |
| `portable` | `bool` | `True` | `True` → `setting_sources=[]`; `False` → `["project"]` |
| `add_dirs` | `list[str] \| None` | `None` | Extra authorized directories. **Required when the workbench lives outside the workspace** |
| `flush` | `str` | `"eager"` | Maps to `session_store_flush` |
| `prelude` | `str` | `""` | A block appended after `instructions` (the workbench index goes here) |

The mapping:

| Resulting option key | Value |
|---|---|
| `system_prompt` | `{"type": "preset", "preset": "claude_code", "append": spec.instructions [+ "\n\n" + prelude]}` |
| `allowed_tools` / `disallowed_tools` / `permission_mode` | Taken straight from `spec` |
| `setting_sources` | `[]` (portable) or `["project"]` |
| `plugins` | Present only when the repo root's `plugin/` directory exists |
| `cwd` / `add_dirs` | Written only when non-empty |
| `session_store` / `session_store_flush` | Written only when `session_store` is not `None` |
| `model` `effort` `max_turns` `max_budget_usd` `agents` `mcp_servers` `hooks` | Each written only when non-empty |
| `env` | `dict(spec.env)` then `update(spec.compact.env())` |
| `resume` / `fork_session` / `resume_session_at` | **Only take effect when `resume` is truthy** |

`PLUGIN_DIR` is the repo root's `plugin/` (three levels up from `flower/core/agent.py`). After a pip install that directory may not exist;
the code checks with `is_dir()`.

!!! warning "`fork=True` silently does nothing without `resume`"
    Both `fork_session` and `resume_session_at` are nested inside `if resume:` — without `resume` they have no effect at all,
    **and no error is raised**. Likewise `Runtime.run(resume_at=...)` only takes effect when `resume` is given,
    and **`Workflow` never passes `resume_at`**: to roll back to a message you must call `Runtime.run` directly.

### `CompactPolicy` {#compactpolicy}

```python
@dataclass
class CompactPolicy:
    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]: ...
```

The control panel for auto-[compact](glossary.md#压缩); its output is a set of environment variables to inject into the subprocess.
The compaction algorithm itself lives inside the harness binary and can't be changed — all you can change is whether it fires.

| Field | Type | Default | Description |
|---|---|---|---|
| `mode` | `str` | `"auto"` | `"auto"` = set nothing, threshold = window − 33k; `"no_summary"` → `DISABLE_AUTO_COMPACT=1`; `"off"` → `DISABLE_COMPACT=1` (turns off `/compact` as well). **Any other value raises `ValueError`**, it is not silently ignored |
| `window` | `int \| None` | `None` | Not `None` → `CLAUDE_CODE_AUTO_COMPACT_WINDOW=<str(window)>`. The CLI side clamps to 100k–1M; anything below 100k is raised to 100k |

| Method | Signature | Description |
|---|---|---|
| `env` | `() -> dict[str, str]` | Produces the environment variables. **An illegal `mode` raises `ValueError` here, not at construction** — and since it's called by `build_options`, the error surfaces inside `Runtime.run` |

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

The policy object for "write a [handoff document](glossary.md#交接书) and start a new session" instead of compacting when the context is nearly full.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | Turn it off and you fall back to auto-compact |
| `window` | `int` | `default_window()` | How large the model's context window is assumed to be |
| `headroom` | `int` | `50_000` | How much slack to keep. Rationale: auto-compact fires at window − 33k, the handoff must beat it, and "writing the handoff" itself costs a turn |
| `max_generations` | `int` | `8` | Maximum generations per step. **This is a runaway brake, not capacity planning** |

| Property | Type | Description |
|---|---|---|
| `at` | `@property -> int` | Handoff threshold, `max(10_000, window - headroom)`. **There is a 10k floor** — any lower and it couldn't even write the handoff |
| `warn_at` | `@property -> int` | Where the approach warning fires, `max(1_000, at - 20_000)`; emitted once per generation |

!!! warning "Setting `window` too small burns money on endless handoffs"
    If `at` falls below that role's **startup floor** (measured at roughly 34k for the coordinator), every new session crosses the line the moment it opens; and since
    **handoffs don't consume retry budget** (`attempt -= 1`), it spins forever. The only brake is `max_generations=8`;
    once it's hit, `error` is replaced with a diagnostic suggesting you raise `window` or disable handoffs.

### `default_window()` {#default-window}

```python
def default_window() -> int
```

Guesses the context window from the **model name string** in the `ANTHROPIC_MODEL` or `ANTHROPIC_DEFAULT_OPUS_MODEL` environment variable:

| Condition | Returns |
|---|---|
| The name contains a standalone `1m` token (regex `(?:^\|[^a-z0-9])1m(?:[^a-z0-9]\|$)`) | `1_000_000` |
| The name contains `haiku` | `200_000` |
| Everything else (**including neither variable being set**) | `1_000_000` |

**The default is the optimistic value.** Guessing high is not a hard error: the API bounces the request with `prompt is too long`, and `Runtime` recognizes that signal
(internally `is_overflow`) and hands off on the spot — but that generation's handoff is the degraded version.

---

## Documents {#文书}

Source: [`brief.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/brief.py) ·
[`handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
[`goal.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/goal.py)

Four dataclasses, all of the form "parse one model reply into a fixed set of sections, then spill it to disk". The shared shape:
`parse()` to parse, `missing()` / `complete()` to check completeness, `to_markdown()` for humans,
`prompt_block()` for the downstream model, `write()` / `load()` to spill and read back.

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

The [brief](glossary.md#需求确认书), **exactly four sections**, in the fixed order
`goal` → `accept` → `bounds` → `unknowns`; the Chinese section names are 「目标」, 「验收标准」, 「边界」, 「未知与假设」 respectively.

| Field | Type | Default | Description |
|---|---|---|---|
| `goal` | `str` | `""` | Goal |
| `accept` | `str` | `""` | Acceptance criteria |
| `bounds` | `str` | `""` | Boundaries |
| `unknowns` | `str` | `""` | Unknowns and assumptions |
| `path` | `Path \| None` | `None` | Where it spills to disk. `compare=False`, so it takes no part in equality |

| Method | Signature | Description |
|---|---|---|
| `missing` | `() -> list[str]` | The **Chinese names** of the missing sections, ready to display |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Brief` | Parses the four sections out of a model reply. **Strips fenced code blocks first**; anything not found stays empty |
| `to_markdown` | `() -> str` | The full document with a metadata header; empty sections get `"(未填)"` |
| `prompt_block` | `() -> str` | A compact version for feeding downstream, **non-empty sections only**, no metadata |
| `write` | `(path: str \| Path) -> Path` | Creates parent directories, writes, sets `self.path` to the resolved path, and returns it |
| `load` | `@classmethod (path: str \| Path) -> Brief \| None` | Returns `None` if the file is missing or on `OSError`. **Restores the `"(未填)"` placeholder back to an empty string** |

Parsing rules (where the traps cluster):

- When stripping fences, **an unclosed ``` or `~~~` causes everything from there on to be discarded** — in practice clarifiers do paste
  entire source files into their replies. When model output is truncated, none of the later sections parse, so `complete()` is `False` and the gate sends it back.
- The heading regex tolerates `## 目标` / `**目标**` / `目标:` / `3. 边界`, and also body text immediately following the heading.
- The alias table is compiled longest-first, otherwise "未知" would swallow "未知与假设".
- When a section name appears more than once, **the first one with content wins**.
- If you hand-edit a brief and copy `to_markdown()`'s `"(未填)"` placeholder verbatim, that section still counts as missing.

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

The [handoff document](glossary.md#换代) written at [handoff](glossary.md#交接书) time, five sections.

| Field | Type | Default | Description |
|---|---|---|---|
| `doing` | `str` | `""` | What is being done. **Required** |
| `decided` | `str` | `""` | What has been decided |
| `deadends` | `str` | `""` | Dead ends |
| `next` | `str` | `""` | Next step. **Required** |
| `scene` | `str` | `""` | The scene |
| `step` | `str` | `""` | Used only in the document header; **takes no part in parsing** |
| `path` | `Path \| None` | `None` | Where it spills to disk |

**Only `doing` and `next` are required** — insisting that "dead ends" be non-empty would push the model into making things up.

| Member | Signature | Description |
|---|---|---|
| `missing` | `() -> list[str]` | **Checks only the two required sections** |
| `complete` | `() -> bool` | `not missing()` |
| `degraded` | `@property -> bool` | Whether the body carries the degradation marker `[降级:交接没写成]` |
| `parse` | `@classmethod (text: str, *, step: str = "") -> Handoff` | Reuses `Brief`'s section splitter |
| `to_markdown` | `() -> str` | Empty sections get `"(空)"` |
| `prompt_block` | `() -> str` | **The header states plainly that you are taking over**, so the successor doesn't turn around and ask a human for background |
| `write` | `(path) -> Path` | Same as `Brief.write` |
| `load` | `@classmethod (path) -> Handoff \| None` | Same as `Brief.load` |

Three members in the same module that are **not exported but semantically critical**: `is_overflow(*texts)` matches `prompt is too long`,
`context length exceeded`, `maximum context length`, `too many total text bytes`,
`input length and max_tokens exceed` and friends, turning a "hard error" into "hand off right now"; `HANDOFF_PROMPT` is the prompt that makes
**the current session itself** write the handoff (it holds two placeholders, `{used}` and `{window}`; **it is not a new role** —
only that session has that context); `degraded(step, prompt, *, why="")` mechanically assembles one when the handoff can't be written,
stuffing the first **1200** characters of the original task into `scene`.

### `Goal` {#goal}

```python
@dataclass
class Goal:
    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None
```

The goal plus verdict checklist used by the [goal guard](glossary.md#目标看守).

| Field | Type | Default | Description |
|---|---|---|---|
| `statement` | `str` | `""` | The goal statement |
| `checks` | `list[str]` | `[]` | The verdict checklist, one item per line |
| `path` | `Path \| None` | `None` | Where it spills to disk |

| Member | Signature | Description |
|---|---|---|
| `unverifiable` | `@property -> list[str]` | The items in `checks` marked `[此环境无法验证:…]`. **Doomed to fail the verdict from the moment the goal was set** |
| `missing` | `() -> list[str]` | Requires `statement` non-empty **and** `checks` non-empty |
| `complete` | `() -> bool` | `not missing()` |
| `parse` | `@classmethod (text: str) -> Goal` | `checks` one per line, with `-` / `*` / `1.` markers stripped automatically |
| `to_markdown` | `() -> str` | An empty checklist is written as `"(空)"` |
| `prompt_block` | `() -> str` | The compact version for feeding downstream |
| `write` / `load` | Same as `Brief` | Spill and read back |
| `amend` | `(extra: str) -> Goal` | **Appends, does not overwrite**: `"\n\n(已修改)" + extra` is spliced after `statement`; returns `self` |

### `Verdict` {#verdict}

```python
@dataclass
class Verdict:
    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)
```

The result of one round of judging by the [judge](glossary.md#判定者), **exactly three sections**: conclusion / reason / not passed.

| Field | Type | Default | Description |
|---|---|---|---|
| `state` | `str` | `""` | `"achieved"` / `"not_yet"` / `"unreachable"`; `""` when it can't be parsed |
| `reason` | `str` | `""` | The reason |
| `failed` | `list[str]` | `[]` | Checklist items that did not pass |

| Member | Signature | Description |
|---|---|---|
| `achieved` | `@property -> bool` | `state == "achieved"` |
| `unreachable` | `@property -> bool` | `state == "unreachable"` |
| `ok` | `@property -> bool` | Whether a conclusion was parsed at all. **`ok=False` must be treated as "not achieved", never as achieved** |
| `parse` | `@classmethod (text) -> Verdict` | See below |
| `feedback` | `() -> str` | What gets sent back to the worker: what's short, not how to fix it |

The order in which `parse` recognizes things:

1. First, take the 「结论」/「判定」 heading section.
2. With no heading section, strip the whole text and `fullmatch(r"1|true")` → achieved; `fullmatch(r"0|false")` → not yet.
3. Otherwise, search the conclusion text against the state-word table (**longer words first**) for the first hit.
   **「无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable」 all map to `unreachable`** —
   we got burned by this: the target platform was macOS, the run was in a Linux container, and the judge read a source branch and passed it.
4. Still nothing → look for a standalone `\b1\b` → achieved, `\b0\b` → not yet.
5. Nothing matches at all → `state=""`, `ok=False`.

`unreachable` and `not_yet` **are two different conclusions**: the former takes the "stop and ask a human" path, not "one more round".

---

## hook layer {#hook}

Source: [`flower/core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py)

This layer is flower's **execution boundary**: which tools the main thread may not touch, how
over-long results get trimmed, which role goes into its own worktree — all of it enforced by SDK
hooks, **not by prompts**. The reason is blunt: a prompt is a suggestion, and the model can ignore
it. Measured: even with the system prompt explicitly saying "do not use worktree",
`isolate_guard`'s injection still took effect (the model passed `None`, what landed was `'worktree'`).

Nine exports: five guard factories that return a `HookMatcher` (`whitelist_guard` may return
`None`), one assembler, one merger, two isolation-marking functions.
You don't need to wire them by hand — [`Runtime`](#runtime) assembles them automatically from the
`AgentSpec`. Manual wiring is only needed when you drive the SDK yourself (bypassing `Runtime`).

**Main-thread detection goes through one function**: `_is_main_thread(data) = not data.get("agent_id")` —
a subagent's tool-lifecycle hook data carries `agent_id`, the [main thread](glossary.md#主线程) doesn't.
Every "main thread only" guard rests on this one line.

Tool-group constants (module level, not exported, but they determine the default matchers):

```python
HANDS_ON   = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY      = "Bash|Read|Grep|Glob|WebFetch|WebSearch"
```

### Quick reference: which guard hangs on which SDK event {#hook-速查表}

| Function | SDK hook event | matcher | What it intercepts | What it returns | Who installs it |
|---|---|---|---|---|---|
| `whitelist_guard` | `PreToolUse` | those of `Bash\|Write\|Edit\|NotebookEdit` **not in `allowed_tools`** | **main thread only** calling a banned tool | `permissionDecision: "deny"` + reason | `Runtime._attempt`, **only when `spec.delegate_only is False`** |
| `delegate_guard` | `PreToolUse` | `Bash\|Write\|Edit\|NotebookEdit` (changeable via `tools=`) | **main thread only** doing hands-on work; with `allow_glance=True`, `Bash` calls that pass `is_ephemeral()` go through | `deny` + "go dispatch a subagent" | `workbench_hooks(delegate_only=True)`, **only when `Runtime` has a workbench** |
| `isolate_guard` | `PreToolUse` | `Agent` | `tool_input` has neither `cwd` nor `isolation`, and the `subagent_type` has been marked by `isolated()` | `permissionDecision: "allow"` + `updatedInput` (injects `isolation="worktree"`) | `workbench_hooks`, **only when some role in `agents` is marked** |
| `index_guard` | `PostToolUse` | `Write\|Edit` | `tool_input.file_path` falls inside `workbench.root` | `{}` (the side effect is `workbench.refresh()`) | `workbench_hooks`, always installed |
| `spill_guard` | `PostToolUse` | `Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch` | **string fields** in `tool_response` of ≥ `threshold` characters; reading the spill directory itself is let through | `updatedToolOutput` (spill + one pointer line + the first 400 characters) | `workbench_hooks`, **only when `spill_threshold` is truthy** |

**The key inference to draw from this table**: with `Runtime(workbench=False)`, `workbench_hooks`
is not installed at all; and for a coordinator with `delegate_only=True`, `whitelist_guard` is
skipped too — **the main thread has no wall whatsoever**.
See the warning under [Runtime](#runtime).

### `whitelist_guard()` {#whitelist-guard}

```python
def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None
```

**Makes `allowed_tools` genuinely exclusive for the four hands-on tools.**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `allowed` | `list[str] \| None` | required, positional | usually just pass `spec.allowed_tools` |
| `role` | `str` | `"这个角色"` | how the refusal text refers to itself. `Runtime` passes `spec.name` |

- **Hangs on `PreToolUse`**, matcher is `"|".join(banned)`, where `banned` = whichever of
  `Bash` `Write` `Edit` `NotebookEdit` are not in `allowed`.
- A hit is `permissionDecision: "deny"`, with text along the lines of: "XX does not have YY.
  **This is deliberate, not a missing config.** Write the conclusion into the body of your reply,
  the framework picks it up from there — don't try other spellings to get around this."
- **Intercepts only this session's main thread**; subagents pass — a subagent's tools are
  determined by `AgentDefinition.tools`.
- Returns **`None`** when there is nothing to block (e.g. a role like `worker()` with the full tool
  set), so the caller can decide whether to install it.

**Why it has to exist**: `allowed_tools` is an **approval-exemption list, not an exclusive
whitelist**. Two pieces of measured evidence — a judge that was supposed to be read-only ran
`Bash` 11 times; in a $0.1 probe an agent with `allowed_tools=["Read"]` still managed to call
`Write`/`Bash`.
So the "no write tools" property of `clarify()` / `judge()` **rests on this hook**, not on the
whitelist itself.

The upside is that it derives from `allowed_tools`, so `judge(can_run=True)` automatically keeps
`Bash` while still blocking `Write`/`Edit` — no extra switch needed.

### `delegate_guard()` {#delegate-guard}

```python
def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher
```

**Main thread does hands-on work → refuse, and point the way.**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `tools` | `str` | `"Bash\|Write\|Edit\|NotebookEdit"` | the matcher. A regex string, not a list |
| `allow_glance` | `bool` | `False` | when `True`, `tool_name == "Bash"` with [`is_ephemeral(command)`](#is-ephemeral) true is let through |

- **Hangs on `PreToolUse`**, matcher is exactly `tools`.
- Main thread calling one of these four tools → deny, and the reason **states the next step**:
  use the `Agent` tool to dispatch a subagent, spell out the goal and acceptance criteria in the
  task, and require it to write long output into `.flower/artifacts/` and reply with only paths
  and conclusions.
- Subagents always pass.

The difference from `whitelist_guard` is **wording**: both block the same set of tools, but this
one says "go dispatch someone", which is the right instruction here.
That's why a role with `delegate_only=True` installs only this one — installing both would give
the model two contradictory instructions.

The pass condition for `allow_glance=True` and the "will this result be trimmed" condition are the
**same function** ([`is_ephemeral`](#is-ephemeral)) — the pass set must equal the expiry set;
change one side and you must change the other.

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

Tool results over the threshold are **[spilled](glossary.md#落盘) on the spot**, leaving only one
pointer line in the context — rather than waiting for the context to fill up and compacting
afterwards.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `workbench` | `Workbench` | required, positional | the spill directory is `<workbench.root>/spill/` |
| `threshold` | `int` | `4000` | how many characters before spilling |
| `tools` | `str` | `"Bash\|Read\|Grep\|Glob\|WebFetch\|WebSearch"` | the matcher |
| `main_only` | `bool` | `False` | `False` (default) = subagent results are spilled too |

- **Hangs on `PostToolUse`**, returns
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": <trimmed>}}`.
- The spill filename is the first 16 hex digits of the content's `sha256` + `.txt`; the context
  gets one pointer line + **the first 400 characters**.
- `updatedToolOutput` **must preserve the original tool's output structure**, so only over-long
  **string fields** in the dict are replaced; **lists are never touched** (they may contain image
  blocks). A wrong structure is rejected (original passes through unchanged, no error).

- **Reading the spill files themselves must be let through** — otherwise "use `Read` on it" is an
  empty promise: the full text read back gets spilled again, forever. Hit in practice; the model
  tried five different spellings to get around it.

### `index_guard()` {#index-guard}

```python
def index_guard(workbench: Workbench) -> HookMatcher
```

Anything written into the [workbench](glossary.md#工作台) refreshes `INDEX.md`, so the next agent
knows it exists from its first turn.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `workbench` | `Workbench` | required, positional | the scope to check and the object to refresh |

**Hangs on `PostToolUse`**, matcher `"Write|Edit"`. If `tool_input["file_path"]`, once resolved,
falls inside `workbench.root`, it calls `workbench.refresh()`. **Always returns `{}`** — it changes
nothing, it only has a side effect.

### `isolate_guard()` {#isolate-guard}

```python
def isolate_guard(agents: dict[str, AgentDefinition], *, on_inject: Any = None) -> HookMatcher
```

Assigns each subagent its own git worktree by role, implementing [isolation](glossary.md#隔离).

| Parameter | Type | Default | Description |
|---|---|---|---|
| `agents` | `dict[str, AgentDefinition]` | required, positional | the role table, used to check whether a `subagent_type` is marked |
| `on_inject` | `Any` | `None` | optional callback, invoked as `on_inject(subagent_type, description)` |

**Hangs on `PreToolUse`**, matcher `"Agent"`. Injection happens only when three conditions hold at
once: `tool_name == "Agent"`, `tool_input` has **neither `cwd` nor `isolation`**, and the role for
`subagent_type` has been marked by `isolated()`. If so it returns `permissionDecision: "allow"` +
`updatedInput` (setting `isolation` to `"worktree"`).

`isolation` and `cwd` are **mutually exclusive** in the `Agent` tool — if the model specified `cwd`
itself, respect it.
"Should this be isolated" is **a property of the role**, not a global switch, and not a decision
made on every dispatch; a role that doesn't need isolation gets not a single byte added.

**Turning on isolation means moving the [workbench](glossary.md#工作台) out of the repo.** An
isolated agent cannot write into the shared checkout, so the workbench must be pointed outside the
repo with `home=`. `starter_flow(isolate=True)` uses `<ws>.parent/.flower-<ws.name>`,
`Runtime(workbench=True)` uses `<run_dir>/workbench` — both outside the repo, **but not the same
directory**; don't mix them.

### `isolated()` / `wants_isolation()` {#isolated}

```python
def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition
def wants_isolation(agent: AgentDefinition | None) -> bool
```

Mark a subagent definition as "needs its own workspace", and read that mark back.

| Function | Parameter | Default | Description |
|---|---|---|---|
| `isolated` | `agent: AgentDefinition` | required | the definition to mark. **Returns the same object** |
| | `flag: bool` | `True` | positional. `False` = remove the mark |
| `wants_isolation` | `agent: AgentDefinition \| None` | required | accepts `None` too, returns `False` |

The mark is a Python-side attribute `_flower_isolate` set via `object.__setattr__`, **not a
dataclass field** — the SDK serializes with `asdict()`, which only sees declared fields, so the
mark never leaks through to the CLI side (measured).

**The cost**: running `dataclasses.replace()` on an `AgentDefinition` drops the mark, and isolation
silently stops working.

`worker(isolate=True)` goes through `isolated()` internally.

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

Installs, in one call, the hooks a workbench needs. This is what `Runtime._attempt` calls.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `workbench` | `Workbench` | required, positional | passed to `index_guard` and `spill_guard` |
| `delegate_only` | `bool` | `True` | `delegate_guard` is installed only when `True` |
| `spill_threshold` | `int \| None` | `4000` | `spill_guard` is installed only when truthy |
| `agents` | `dict[str, AgentDefinition] \| None` | `None` | `isolate_guard` is appended only if **any** of them is marked by `isolated()` |
| `allow_glance` | `bool` | `False` | passed through to `delegate_guard(allow_glance=)` |

Output:

- `PreToolUse`: `delegate_only=True` → `[delegate_guard(allow_glance=allow_glance)]`;
  if any role is marked → append `isolate_guard(agents)`.
- `PostToolUse`: always `[index_guard(workbench)]`; if `spill_threshold` is truthy → append
  `spill_guard(workbench, threshold=spill_threshold)`.
- **Event keys with empty lists are dropped**; no empty lists are returned.

### `merge_hooks()` {#merge-hooks}

```python
def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]
```

**Concatenates** several hook configs by event name.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `*groups` | `dict[str, list[Any]] \| None` | varargs | any number of groups. `None` groups are skipped |

Uses `extend`, **no deduplication** — pass the same guard twice and it gets installed twice.
`Runtime` uses it to merge `spec.hooks`, `workbench_hooks(...)` and `whitelist_guard`.

---

## Workbench {#工作台}

Source: [`flower/core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py)

### `Workbench` {#workbench}

```python
@dataclass
class Workbench:
    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
```

The on-disk working directory: three subdirectories plus an index. The index is **injected into the
system prompt**, so the agent knows every turn what it has on hand.

| Field | Type | Default | Description |
|---|---|---|---|
| `workspace` | `Path` | required, positional | the workspace. `__post_init__` resolves it |
| `dirname` | `str` | `".flower"` | workbench directory name, relative to `workspace` |
| `max_index_entries` | `int` | `40` | **only affects `prompt_block()`**: how many entries per category the system-prompt block lists at most, with the rest collapsed into a single "… and N more" line. `INDEX.md` itself is unbounded and lists everything |
| `home` | `Path \| None` | `None` | if given, it is used as `root` and **`dirname` is ignored**. Also resolved when not `None` |

| Member | Signature | Description |
|---|---|---|
| `root` | `@property -> Path` | `home` if given, otherwise `workspace / dirname` |
| `external` | `@property -> bool` | whether `root` is **outside** `workspace`. Should be `True` in isolation mode |
| `scripts` | `@property -> Path` | `root / "scripts"`, scripts you'll run a second time |
| `artifacts` | `@property -> Path` | `root / "artifacts"`, long output over 2000 characters |
| `notes` | `@property -> Path` | `root / "notes"`, key decisions, one file per decision |
| `index_path` | `@property -> Path` | `root / "INDEX.md"` |
| `show` | `(p: Path) -> str` | the path shown to the model: relative inside the workspace, absolute outside |
| `ensure` | `() -> Workbench` | mkdir the three directories, return `self` (chainable: `Workbench(ws).ensure()`) |
| `scan` | `(d: Path) -> list[tuple[str, str, int]]` | `(display path, description, byte count)`. Recursive `rglob("*")`, skipping files starting with `.` |
| `refresh` | `() -> str` | rewrite `INDEX.md` and return its content |
| `prompt_block` | `() -> str` | **the block injected into the system prompt**. Deliberately short — it's there every turn |

Script self-description format: `# desc: one sentence` within the first 8 lines (`//` and `--`
comment markers are also recognized), falling back to the first non-empty comment line or the first
line of the docstring (truncated to 100 characters).

The three rules injected by `prompt_block()`:

1. Scripts you'll run a second time go in `scripts/`, with `# desc:` on the first line.
2. Output over **2000 characters** goes in `artifacts/`; the conversation gets only the path and the
   conclusion.
3. Key decisions go in `notes/`, one file per decision.

When `external=True`, `prompt_block()` adds a line saying to access it with absolute paths.

**Subagents do not inherit the index.** It goes through the session-level `system_prompt.append`,
and a subagent has its own system prompt (measured at $0.2461). So "long output goes in
`artifacts/`, and here's where the workbench is" must be relayed by the
[coordinator](glossary.md#协调者) in the [task brief](glossary.md#任务书) — **that is the only
channel**, not redundancy.
`WORKER_RULES` **deliberately omits** this rule: the real path is generated by `Workbench`, and
hardcoding it would be wrong.

---

## Session store {#会话存储}

Source: [`sqlite.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/sqlite.py) ·
[`trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py) ·
[`prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py)

Three inheritance layers: `SqliteSessionStore` ← `TrimmingSessionStore` ← `PruningSessionStore`.
`Runtime` **always uses the outermost one**; the policy of each layer is controlled by constructor
arguments.

Each layer handles one thing: persistence, [trimming](glossary.md#裁剪) by size and value, and
[pruning](glossary.md#剪除) by "is this an error".
Both trimming and pruning happen at **`load()`** (i.e. the moment resume feeds history back to the
model); not a byte of the raw records in SQLite is touched.

### `SqliteSessionStore` {#sqlitesessionstore}

```python
class SqliteSessionStore(SessionStore):
    def __init__(self, path: str | Path) -> None
```

Implements the SDK's `SessionStore` protocol, with three tables `entries` / `meta` / `summaries`.
The store key is `project_key/session_id[/subpath]` — **subagent transcripts are distinguished by
subpath**.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path` | required, positional | the database file. The connection uses `check_same_thread=False` |

| Method | Signature | Description |
|---|---|---|
| `append` | `async (key, entries) -> None` | idempotent dedup by uuid (first against rows already stored, then within the batch). On a full-batch replay it **does not advance mtime and does not re-fold the summary**; only the main transcript (`subpath is None`) participates in summaries |
| `projects` | `() -> list[str]` | the `project_key`s actually present in the database. **The SDK derives it from cwd; confirm with this before querying, don't guess** |
| `has_session` | `(project_key: str, session_id: str) -> bool` | **synchronous, does not read payloads**, just one row of meta. For "continue at the same path" — resuming a session that doesn't exist only blows up once the subprocess has started |
| `last_context` | `(project_key: str, session_id: str, *, scan: int = 60) -> int` | how large a context the model actually saw on the last turn; returns `0` if not found. Scans backwards over only the last `scan` entries; counts all three of `input + cache_read + cache_creation` (looking at `input_tokens` alone badly underestimates) |
| `load` | `async (key) -> list[SessionStoreEntry] \| None` | ordered by seq; returns `None` if there are no rows |
| `list_sessions` | `async (project_key) -> list[SessionStoreListEntry]` | main transcripts only |
| `list_session_summaries` | `async (project_key) -> list[SessionSummaryEntry]` | list session summaries |
| `delete` | `async (key) -> None` | deleting a main transcript **cascades to its subagent transcripts**, avoiding orphans |
| `list_subkeys` | `async (key) -> list[str]` | list the sub-transcripts under this session |
| `close` | `() -> None` | close the connection |

The internal `_next_mtime` guarantees **strict monotonicity** — `list_sessions` and the summary
sidecar share this clock, otherwise the SDK's staleness fast path misjudges.

### `TrimPolicy` {#trimpolicy}

```python
@dataclass
class TrimPolicy:
    keep_recent: int = 20
    min_chars: int = 2000
    spill_dirname: str = ".flower/spill"
    enabled: bool = True
```

| Field | Type | Default | Description |
|---|---|---|---|
| `keep_recent` | `int` | `20` | the most recent N `tool_result`s keep their full text |
| `min_chars` | `int` | `2000` | short results aren't worth trimming |
| `spill_dirname` | `str` | `".flower/spill"` | **relative to `workspace`, must be inside the workspace** — otherwise the agent's `Read` can't reach it |
| `enabled` | `bool` | `True` | this is `False` under `Runtime(trim=False)` |

| Method | Signature | Description |
|---|---|---|
| `placeholder` | `(path: str, n: int) -> str` | produce the pointer line that replaces the body |

**The two spill directories are not the same one.** `spill_guard` writes to
`<workbench.root>/spill/` (which may be outside the workspace);
`TrimPolicy.spill_dirname` writes to `<workspace>/.flower/spill/` (**must be inside the
workspace**).
They correspond to "trim on the spot" and "trim at resume" respectively; the different directories
are deliberate, don't collapse them into one.

### `EphemeralPolicy` {#ephemeralpolicy}

```python
@dataclass
class EphemeralPolicy:
    enabled: bool = True
    keep_recent: int = 6
    max_chars: int = 2000
    text: str = "[{cmd} 的结果已过期(第 {age} 轮前),当前状态可能已变。需要请重新执行]"
```

The expiry policy for [ephemeral command](glossary.md#一次性命令) results.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | turn it off and no expiry marking happens at all |
| `keep_recent` | `int` | `6` | the most recent N are exempt. **Much smaller than `TrimPolicy`'s 20** |
| `max_chars` | `int` | `2000` | anything larger is skipped, left to `TrimPolicy` to archive |
| `text` | `str` | see signature | replacement text, with the two placeholders `{cmd}` and `{age}` |

| Method | Signature | Description |
|---|---|---|
| `placeholder` | `(cmd: str, age: int) -> str` | fill in `text` to produce the replacement body |

**Applies only to `Bash` tool results**, and only when the command matches the ephemeral-command
whitelist. **`Read` is not included** — file contents don't degrade with time to the point of being
misleading. Expired content is **not spilled**, it's simply discarded.

### `is_ephemeral()` {#is-ephemeral}

```python
def is_ephemeral(cmd: str) -> bool
```

Decides whether a Bash command is an [ephemeral command](glossary.md#一次性命令).
**`delegate_guard`'s pass decision and trimming's expiry decision share this single function** —
the set of commands the coordinator may run itself must equal the set whose results get marked
expired. Pass without trimming, and an expired `git status` occupies context forever and misleads;
trim without passing, and the coordinator dispatches a subagent for one `ls`, paying 4.3k of
startup cost for a few dozen characters.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `cmd` | `str` | required, positional | the full command line |

Decision order:

1. Empty / all whitespace → `False`.
2. Command substitution (`$(`, backticks, `<(`, `>(`) or a state-changing form matches → `False`.
3. After stripping safe redirections (`2>&1`, `&> /dev/null` and the like), still contains `>` or
   `<` → `False`.
4. After stripping `&&` / `||` / `;` / `|`, a lone `&` remains (background execution) → `False`.
5. Split on `&&` / `||` / `;` / `|`, and **every segment must match the whitelist**.

Whitelisted verb categories: read-only `git` subcommands (`status` `diff` `log` `show` `branch`
`rev-parse` etc.), directory and system information (`ls` `pwd` `df` `du` `date` `whoami` `env`
etc.), processes and containers (`ps` `top` `lsof` `docker ps` `kubectl get` etc.), looking at files
(`cat` `head` `tail` `wc` `stat` `find` `tree`), path lookup (`which` `whereis` `command -v`
`type`), text processing (`grep` `rg` `sort` `uniq` `awk` `sed` `jq` `diff` etc.).

Even when the verb is whitelisted, these forms are still blocked: `xargs`, `exec`, `eval`,
`source`, `tee`, `find -delete` / `-ok` / `-fprint`, `sed -i`, `sort -o`, `system(` and `print >`
inside `awk`, `git branch -D/-d/-m`, `git * --force/--hard/--prune`.

The first version rejected all compound commands outright, which **measurably broke glance
entirely** (all three of the coordinator's attempts were blocked), so it was changed to
segment-by-segment judgement.

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

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path` | required | the database file |
| `workspace` | `str \| Path` | required | the base for the spill directory |
| `policy` | `TrimPolicy \| None` | `None` | falls back to the default `TrimPolicy()` |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | falls back to the default `EphemeralPolicy()` |

Public attributes: `workspace`, `policy`, `ephemeral`, `last_report: dict[str, int]`.

The order in `load()`: `super().load()` → clear `last_report` → if `ephemeral.enabled`, `expire()` →
if `policy.enabled`, `trim()`. **With `enabled=False` the step is skipped entirely.**

| Method | Description |
|---|---|
| `expire(entries)` | Replaces **only the body** of expired time-sensitive `Bash` results, **keeping the block**. The command is found in the `tool_use` of the preceding assistant message; skips `isCompactSummary` / `isMeta`; anything over `max_chars` is skipped (left to `trim`); the last `keep_recent` are exempt. Writes `last_report["expired"]` |
| `trim(entries)` | `tool_result` bodies `>= min_chars` are spilled to `<workspace>/<spill_dirname>/<first 16 of sha256>.txt` and the block content is replaced with a pointer; the last `keep_recent` are exempt. Writes `cleared` / `kept` / `chars_saved` into `last_report` |

**Only plain text is trimmed**: `image` / `document` blocks are left untouched.

**Two structural red lines**: the `tool_result` **block itself must remain**, only its content may
be replaced (one missing block means "Missing Tool Result Block"); `isCompactSummary` entries must
not be touched.

### `trim_report()` {#trim-report}

```python
def trim_report(store: TrimmingSessionStore) -> str
```

Renders `store.last_report` into a single line for the UI to log.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `store` | `TrimmingSessionStore` | required, positional | the subclass `PruningSessionStore` is accepted too |

Three outputs: nothing happened → `"未裁剪"`; expiry only → `"N 个时效性结果标记为过期"`;
otherwise `"裁掉 N 个工具结果(保留最近 M 个),省下 ~X tokens"`, where X = `chars_saved // 4`.

### `PrunePolicy` {#prunepolicy}

```python
@dataclass
class PrunePolicy:
    drop_api_errors: bool = True
    neutralize_interrupts: bool = True
    interrupt_text: str = "[上一轮在此处被中断,该工具结果未产生]"
    keep_denials: int = 1
```

| Field | Type | Default | Description |
|---|---|---|---|
| `drop_api_errors` | `bool` | `True` | drop synthetic API error messages (disconnection debris) |
| `neutralize_interrupts` | `bool` | `True` | replace `tool_result`s left over from an interrupt with a neutral note |
| `interrupt_text` | `str` | see signature | the text of that neutral note |
| `keep_denials` | `int` | `1` | keep the most recent N denied tool calls |

The reasoning behind `keep_denials`: a denied call never executed, so its result carries no
information, but it takes up real space (measured once at 273 characters = 93 characters of refusal
text + 180 characters of **the dead command verbatim**). More importantly **it misleads** — measured:
after reading a few "do not use Bash directly" entries, the coordinator stopped even attempting the
`git status` that would have been let through, having learned helplessness.
**The default is 1, not 0**: the most recent denial keeps the model from retrying the same blocked
command over and over within a single turn.

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

**`Runtime`'s default store.**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `path` | `str \| Path` | required | the database file |
| `workspace` | `str \| Path` | required | the base for the spill directory |
| `policy` | `TrimPolicy \| None` | `None` | trim policy |
| `prune` | `PrunePolicy \| None` | `None` | prune policy |
| `ephemeral` | `EphemeralPolicy \| None` | `None` | expiry policy |

Beyond the parent's, three more public attributes: `prune_policy`, `pruned`, `denials_dropped`.

`load()` = `super().load()` (first `expire` + `trim`) → `self.prune(entries)`. `prune` does three
things:

1. **Drops denied calls that are too old**: decided by the harness's structural marker
   `toolDenialKind == "permission-rule"` (more reliable than matching refusal text), keeping the
   last `keep_denials`, and dropping the rest's `tool_use` **and** `tool_result` blocks together.
   When one assistant message contains several `tool_use` blocks, **only the matching ones are
   dropped**, otherwise you get "Missing Tool Result Block"; text and thinking blocks are kept.
2. **Drops synthetic API error messages.** They stay in SQLite untouched, they're just not fed back.
3. **Replaces `tool_result`s left over from an interrupt with a neutral note** — body only, the
   entry is not dropped.

**The one structural red line**: the transcript is a single `parentUuid` chain, so dropping an entry
means reattaching its children to the nearest surviving ancestor.
The internal `relink`'s `entries` **must be the complete list (including the ones to be dropped)**,
with the filtering done inside it — if the caller filters first and then passes the result in, the
chain breaks there and all the earlier history is lost (**already stepped on: it doesn't show when
the dropped entries are at the tail, and blows up when they're in the middle**).

**The parameter order differs from the parent's**: the parent is
`(path, workspace, policy, ephemeral)`, the subclass is `(path, workspace, policy, prune, ephemeral)` —
**the fourth positional parameter changed from `ephemeral` to `prune`**, so passing positionally
silently misaligns. Always pass by keyword.

---

## Resilience {#韧性}

Source: [`flower/core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py)

When the network drops, hang and wait rather than failing out. Four exports: one policy dataclass +
three probe functions usable on their own.

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

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `True` | turn it off and no failure is ever retried |
| `max_attempts` | `int` | `6` | **including the first attempt** |
| `base_delay` | `float` | `4.0` | backoff base, seconds |
| `max_delay` | `float` | `120.0` | backoff ceiling, seconds |
| `probe_timeout` | `float` | `5.0` | timeout for a single probe |
| `probe_interval` | `float` | `15.0` | how long to wait between two probes |
| `max_offline_wait` | `float` | `3600.0` | how long to hang and wait at most, 1 hour by default |
| `retry_unknown` | `bool` | `True` | whether to retry errors that can't be classified |
| `resume_prompt` | `str` | see signature | what to say when continuing. **Deliberately contains no error detail** — the model needs to know "you were interrupted, carry on", not whether it was `ENOTFOUND` or a 503 |

| Method | Signature | Description |
|---|---|---|
| `delay_for` | `(attempt: int) -> float` | `min(base_delay * 2**(attempt-1), max_delay)` times `0.75 + random()*0.5` (±25% jitter) |
| `should_retry` | `(kind: str) -> bool` | `kind == "transient"`, or `kind == "unknown"` with `retry_unknown` |
| `wait_online` | `async (notify=None) -> bool` | hang until the network comes back. Returns `True` when it does, `False` past `max_offline_wait`. `notify` is a `(str) -> None` callback, fired once **on first unreachability** and once **on recovery** |

### `classify()` {#classify}

```python
def classify(text: str | None) -> str
```

Sorts error text into three classes: `"transient"` / `"fatal"` / `"unknown"`.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `text` | `str \| None` | required, positional | the raw error message. Empty returns `"unknown"` |

**Fatal is checked before transient** — text for things like a 401 often contains the word
`connection`, and with the order reversed you'd wait forever.

| Class | What matches |
|---|---|
| `fatal` | `400` `401` `403` `404`, `invalid api key`, `authentication`, `unauthorized`, `permission denied`, `invalid_request`, `credit balance`, `quota exceeded`, `budget`, `max_turns`, `CLINotFound` |
| `transient` | `ENOTFOUND` `EAI_AGAIN` `ECONNRESET` `ECONNREFUSED` `ETIMEDOUT` `EPIPE` `EHOSTUNREACH` `ENETDOWN`, `socket hang up`, `fetch failed`, `network error`, `Connection error`, `Can't reach the API server`, `429` `500` `502` `503` `504` `529`, `overloaded`, `rate limit`, `too many requests`, `timeout` / `timed out`, `temporarily unavailable`, `service unavailable`, `internal server error` |

### `endpoint()` {#endpoint}

```python
def endpoint() -> tuple[str, int]
```

The host and port to probe, following `ANTHROPIC_BASE_URL`, defaulting to
`https://api.anthropic.com`; port defaults to `80` (http) or `443`.

**When probing a self-hosted gateway you must probe that gateway** — `api.anthropic.com` being
reachable says nothing about the gateway.

### `reachable()` {#reachable}

```python
async def reachable(host: str, port: int, timeout: float = 5.0) -> bool
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `host` | `str` | required, positional | hostname |
| `port` | `int` | required, positional | port |
| `timeout` | `float` | `5.0` | seconds |

**Only DNS (`getaddrinfo`) + a TCP handshake**: no HTTP request, no credentials, **no cost**. Any
exception counts as unreachable.

---

## Events and interaction {#事件与交互}

Source: [`events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py) ·
[`human.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/human.py)

An [event](glossary.md#事件) is the SDK message stream flattened into a stable structure. **The [interaction layer](glossary.md#交互层) only knows
`Event`; it imports no SDK types** — that is the boundary that lets you swap the UI without touching the core. See [Swapping the interaction layer](../guide/interaction.md).

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

| Field | Type | Default | Notes |
|---|---|---|---|
| `kind` | `EventKind` | required | see table below |
| `text` | `str` | `""` | body |
| `tool` | `str` | `""` | tool name, only on `tool_call` |
| `payload` | `dict[str, Any]` | `{}` | structured extras |
| `raw` | `Any` | `None` | the raw SDK object, for when you need to dig |

`__str__`: for `tool_call` it is `f"[{tool}] {text}"`, otherwise `text`, and if `text` is empty, `f"<{kind}>"`.
So `print(ev)` is directly readable.

There are **15** `EventKind` values in total:

| kind | Emitted by | Notes |
|---|---|---|
| `text` | `normalize` | assistant body |
| `thinking` | `normalize` | thinking block |
| `tool_call` | `normalize` | tool call. `text` is a `file_path` / `command` / `pattern` summary, truncated to 200 chars |
| `tool_result` | `normalize` | tool result. `text` truncated to 500 chars, payload carries `tool_use_id` / `is_error` |
| `task` | `normalize` | the three Task messages; `text` is the message class name |
| `system` | `normalize` | all other system messages; `text` is the subtype |
| `reset` | `normalize` | `compact_boundary` / `microcompact_boundary` / `ConversationResetMessage` |
| `result` | `normalize` | `ResultMessage`, payload carries `session_id` / `cost_usd` / `num_turns` / `is_error` |
| `error` | `normalize` | synthetic API error message, payload carries `{"synthetic": True}` |
| `prompt` | `normalize` | `UserMessage`. **The body is input, not model output**, so it never enters `StepResult.text` |
| `unknown` | `normalize` | unrecognized |
| `retry` | `Runtime` | retry notification |
| `step` | `Workflow.run` | payload: `{"index", "total", "resumed", "woke"}` |
| `handoff` | `Runtime` | payload `phase` ∈ `{"near", "writing", "done"}` |
| `ask` | `HumanChannel` | a question — **also carries "something the human said unprompted"** |

**The last four are not produced by `normalize()`.**

Every assistant / user event carries in `payload`:

| Key | Type | Notes |
|---|---|---|
| `subagent` | `bool` | `bool(parent_tool_use_id)` |
| `parent_tool_use_id` | `str` | present only when `subagent` is true |
| `context` | `int` | `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. **This is the sole source for the [handoff](glossary.md#换代) criterion**, and the number a long-horizon run most deserves to show |

**The `ask` kind carries both "a question" and "something the human said unprompted".** The latter has
`payload["kind"] == "mail"` and **no `options` / `remaining`**. A UI must check `payload.get("kind")` first before
deciding how to render, or it will hang a plain sentence on screen as an unanswered question.

### `normalize()` {#normalize}

```python
def normalize(message: Any) -> list[Event]
```

Flattens one SDK message into 0 to N `Event`s.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `message` | `Any` | required, positional | any SDK message object |

Key branches:

- **Synthetic API error message** (`isApiErrorMessage=True` or `model == "<synthetic>"`) → a single
  `Event("error", payload={"synthetic": True})`. **This one is deliberate** — otherwise the disconnect boilerplate
  would be treated as body text, enter `StepResult.text`, and be passed to the next step.
- `AssistantMessage` → `kind="text"`; `UserMessage` → `kind="prompt"`.
- `ToolUseBlock` → `Event("tool_call", text=<summary>, tool=block.name, payload={"id", "input"})`.
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

One question put to a human.

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | `str` | required | used to locate it when answering |
| `question` | `str` | required | question body |
| `options` | `list[str]` | `[]` | choices. The human may also ignore them and type freely |
| `asked_at` | `float` | `time.time()` | moment the question was asked |
| `state` | `str` | `"asked"` | `asked` → `answered` / `timeout` / `declined` / `over_budget` / `invalid` |
| `answer` | `str` | `""` | answer body |

| Member | Signature | Notes |
|---|---|---|
| `waited_s` | `@property -> float` | how long it has been waiting |
| `event` | `(remaining: int = 0) -> Event` | produces `Event("ask", text=question, payload={"id", "options", "state", "answer", "remaining", "asked_at"}, raw=self)` |

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

An **in-process MCP server** (two tools) plus a set of methods for the UI. The model side only sees
`mcp__human__ask` and `mcp__human__inbox`. All constructor parameters are keyword-only.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `on_event` | `Callable[[Event], None] \| None` | `None` | the outlet for **push** mode. If you supply it, `Workflow.run` will not wire anything up |
| `max_asks` | `int \| None` | `None` | **unlimited**. A number is a hard quota; `0` = no questions allowed (fully automatic / CI). Over quota, the tool **refuses immediately and does not block** |
| `timeout_s` | `float \| None` | `1800.0` | 30 minutes. `None` = wait forever; **`<= 0` = do not wait, every question falls through immediately** |
| `log_path` | `str \| Path \| None` | `None` | Q&A is **appended** to disk, taking no context |
| `amend_path` | `str \| Path \| None` | `None` | things the human says mid-run are appended to this file (usually the brief itself). **Without spilling it, it will not survive a step boundary** — the next step is a new session that only reads frozen artifacts |
| `over_budget_text` | `str` | module constant | what is returned to the model when over quota |
| `timeout_text` | `str` | module constant | what is returned to the model on timeout |
| `declined_text` | `str` | module constant | what is returned to the model when skipped |

Public attributes: the eight named after the constructor parameters, plus `asks: list[Ask]`, `mail: list[Mail]`,
and `ui_errors: list[str]` (**exceptions thrown by UI callbacks are collected here and do not interrupt the run**).

| Member | Signature | Notes |
|---|---|---|
| `tool_name` | `@property -> str` | `"mcp__human__ask"` |
| `inbox_name` | `@property -> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict[str, Any]` | hand it straight to `AgentSpec.mcp_servers`. **The key must match the server name**, so it hands out both together |
| `ask` | `async (question: str, options: list[str] \| None = None) -> Ask` | blocks waiting for a human. **Never raises except `CancelledError`** — nobody answering is also an answer; distinguish via `ask.state` |
| `send` | `(text: str) -> Mail \| None` | the human says something unprompted. **Callable from any thread.** Does not interrupt the agent; internally calls `amend()` automatically |
| `amend` | `(text: str, *, label: str = "运行中补充") -> bool` | appends to `amend_path`. Returns whether it actually wrote (no path configured, empty text, or `OSError` all give `False`) |
| `pending_mail` | `() -> list[Mail]` | mail not yet picked up |
| `remaining` | `@property -> int` | how many questions are left. **Returns `-1` when `max_asks=None`**, not 0 and not infinity |
| `pending` | `() -> list[Ask]` | questions currently waiting for an answer |
| `next_ask` | `async (timeout: float \| None = None) -> Ask \| None` | for **pull** mode. Returns `None` on timeout, raises if cancelled |
| `answer` | `(ask_id: str, text: str) -> bool` | answer. `False` = this question is no longer waiting (timed out / already answered) |
| `decline` | `(ask_id: str, reason: str = "") -> bool` | skip it, let the model decide for itself |
| `transcript` | `() -> str` | the Q&A record as markdown |

**Pick one of the two retrieval modes**: **push** — construct `HumanChannel(on_event=...)`; **pull** — `await channel.next_ask()`.
`Workflow.run` only wires things up when `channel.on_event is None`, so if you passed your own it will not be overwritten.

**Cross-thread**: `answer` / `decline` / `send` go through `loop.call_soon_threadsafe` internally; calling them
directly from a web backend or a TUI input thread is the normal case.

The three "0 / None" semantics all differ — do not mix them up: `max_asks=None` = unlimited, `max_asks=0` = no questions;
`timeout_s=None` = wait forever, `timeout_s<=0` = time out immediately; `remaining` is `-1` when `max_asks=None`.

`Mail`, which is not exported but appears in return values, is a dataclass with fields `id` / `text` / `sent_at` / `taken`.

---

## Lineage {#血缘}

Source: [`flower/core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py)

### `Lineage` {#lineage}

```python
@dataclass
class Lineage:
    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0
```

Records, across processes, which step used which session; [continuity](glossary.md#接续) relies on it to find where the last run got to.
The file is `<run_dir>/lineage.json`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `path` | `Path` | required | path to the lineage file |
| `workspace` | `Path` | required | the workspace. `__post_init__` resolves it |
| `steps` | `dict[str, str]` | `{}` | step name → `session_id` |
| `woke` | `int` | `0` | how many times it has woken |

| Member | Signature | Notes |
|---|---|---|
| `open` | `@classmethod (run_dir: str \| Path, workspace: str \| Path) -> Lineage` | reads `<run_dir>/lineage.json`. **If the file is missing, unreadable, or its `workspace` field does not match, it returns an empty one without raising** |
| `remember` | `(step: str, session_id: str) -> None` | records the mapping and **spills immediately**. An empty step or empty sid returns at once |
| `bump` | `() -> int` | wake counter +1, spill, return the new value (`1` on the first run) |
| `archive` | `(into: str \| Path, *, extra: list[Path] \| None = None) -> Path` | **moves** the lineage file plus `extra` into `<into>/<YYYYmmdd-HHMMSS>/` and zeroes `steps` / `woke`. **Moves, does not delete** |

Spilling goes through the atomic `tmp.replace(path)`; `OSError` is swallowed silently — a failed spill should not take the run down with it.

**`workspace` is the guard**: the SDK derives `project_key` from the workspace path, so after the directory is copied elsewhere
old `session_id`s cannot be found; if the path does not match, treat it as absent.

When `Workflow.run` loads lineage, it validates each record with `runtime.has_session(sid)` to check it is still in the store,
and only uses live ones — the lineage file can outlive `sessions.db`.

---

## Minimal working examples {#示例}

All five run as-is. Prerequisites: `claude-agent-sdk` installed and `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` available
(otherwise `Runtime(...)` raises `RuntimeError` at construction).

### One agent, one step {#示例-单-agent}

The minimal skeleton: declare an `AgentSpec`, build a `Runtime`, `await rt.run(...)`, read the `StepResult`.

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

`Runtime`'s parameters are **all keyword-only**; `rt.run()` takes `spec` and `prompt` positionally, the rest keyword-only.
`AgentSpec` defaults to `allowed_tools=["Read", "Glob", "Grep"]` and `delegate_only=False`,
so `Runtime` automatically installs [`whitelist_guard`](#whitelist-guard) for it, blocking `Bash`/`Write`/`Edit`/`NotebookEdit` entirely.

### Coordinator + worker {#示例-协调}

A hands-off [coordinator](glossary.md#协调者) with one [worker](glossary.md#执行者) doing the work.
This is flower's first layer of context savings.

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

    # workbench=True is mandatory: delegate_guard lives in workbench_hooks,
    # so without the workbench the coordinator's Bash/Write have no hook blocking them.
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

`worker()`'s first two parameters are positional: `description` (what the coordinator uses to pick a worker) and `prompt`
(its system prompt, with `WORKER_RULES` appended automatically). `coordinator()`'s first three are positional: `name`, `instructions`, `workers`.

### Writing your own Workflow {#示例-workflow}

Two steps, where the second injects the first's result into its own prompt — cheap, isolated, no shared session.

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
        # New session: it only eats what is in the prompt
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # New session + previous result injected into the prompt (cheap, contamination-proof)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
        # To keep talking in the same session, write resume_from="造句"; to branch, add fork=True
    ])

    rt = Runtime(workspace=Path("."), run_dir="runs")
    try:
        ctx = await wf.run(rt, on_step=lambda s, r: print(f"{s.name} ok={r.ok} {r.text[:40]!r}"))
    finally:
        rt.close()

    print(ctx["造句"])                 # ctx[step.name] = result.text (when no reduce is given)
    print(ctx["_sessions"])            # step name -> session_id
    print(ctx.get("_failed_at"))       # which step failed, when on_fail="stop"


asyncio.run(main())
```

`Step`'s first three fields (`name` / `spec` / `prompt`) are positional, as is `Workflow`'s `steps`.
`Workflow.run(runtime, *, on_event=None, on_step=None)` — `runtime` positional, both callbacks keyword-only.
**Note that `continuous=True` is the default**: on a second run with the same `run_dir` + same `workspace`,
even steps with `resume_from=None` will continue the session from last time.

### Adding a goal guard {#示例-目标}

First let the [judge](glossary.md#判定者) pin down the goal and the verdict checklist, then make the working step subject to a verdict —
if it fails, retry with the feedback, up to three rounds.

```python
import asyncio
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    coordinator, goal_step, with_goal, worker)


async def main() -> None:
    wb = Workbench(Path.cwd()).ensure()
    # timeout_s=0 = fully automatic: every question falls through at once, no pretending to wait for a human
    ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=0)
    goal_path = wb.notes / "目标.md"

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        "你负责实现。每改一处就跑一次验证,别攒到最后。"),
    }, channel=ch)

    work = Step("干活", spec=coord, prompt="把 hello.py 写出来,跑 `python hello.py` 要打印 hello。")
    # rounds is the **total** number of rounds: rounds=3 → retries=2 → at most three working rounds
    work = with_goal(work, ch, goal_path=goal_path, rounds=3, can_run=True)

    wf = Workflow(
        [goal_step(ch, goal_path=goal_path), work],
        channel=ch,
        workbench=wb,
        # goal_step's prompt reads ctx["确认需求"] (the brief_key default).
        # With no clarify_step, feed one in yourself, or it will only ever see "(没有确认书)".
        context={"确认需求": "## 目标\n写一个打印 hello 的 python 脚本\n\n## 验收标准\n跑 `python hello.py` 输出 hello"},
    )

    rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()

    print(ctx["_goal"])        # GOAL_KEY: the Goal object
    print(ctx["_verdict"])     # VERDICT_KEY: the most recent Verdict
    print(ctx["_goal_rounds"]) # ROUND_KEY: how many rounds were run
    print(ctx.get("_aborted")) # the StepAbort reason (unreachable and nobody answered)


asyncio.run(main())
```

`with_goal` only replaces `gate` / `on_reject` / `retries`; every other field is carried over verbatim via `dataclasses.replace`.
The judge runs in an **independent session**: inside `gate` it calls `rt.run(judger, ..., step_name=f"{label}#{轮次}")` on its own,
with `resume` always `None`.

### Swapping the interaction layer {#示例-交互层}

To move from a terminal to web / TUI / HTTP you only need to change two things: the function that renders `Event`s,
and the coroutine that picks up questions.

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Render an Event into your own UI — this is the only thing you must replace."""
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
    # kind == "ask" that is not mail is handled by the answerer below (pull mode)


async def answerer(ch: HumanChannel) -> None:
    """Pull questions. When moving to a web backend / HTTP service, this coroutine is the only thing to change."""
    while True:
        ask = await ch.next_ask()          # with no timeout it waits indefinitely
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")   # or ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime uses the workbench the workflow already built — do not assemble another one
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()


asyncio.run(main())
```

Push and pull: **pick one**. Push is constructing `HumanChannel(on_event=...)`; pull is `await channel.next_ask()`.
`Workflow.run` only wires things up when `channel.on_event is None`, so passing your own `on_event` will not be overwritten.
`answer()` / `decline()` / `send()` / `interrupt()` **can all be called from another thread**.

---

## Traps and easy mistakes {#陷阱}

Ordered by the order you will hit them, not by module. Every item comes from something actually observed.

### Assembly {#陷阱-装配}

1. **`Runtime(workbench=False)` + `coordinator()` = not a single wall on the main thread.**
   `delegate_guard` is installed only when a workbench exists, and `whitelist_guard` is skipped because of `delegate_only=True`.
   If you use a coordinator, turn the workbench on. See [Runtime](#runtime).
2. **There are two possible workbench locations; do not assemble the wrong one.** `Runtime(workbench=True)` lands at `<run_dir>/workbench`;
   `Workbench(ws)` defaults to `<ws>/.flower`. If you assemble `brief_path` yourself, write it against the latter, or
   **the brief gets written to directory A while the injected index scans directory B — with no error reported**.
   The correct approach: have the workflow itself do `Workbench(...).ensure()`, attach it to `Workflow.workbench`,
   and hand **the same object** to `Runtime(workbench=wb)`.
3. **`allowed_tools` is not an exclusive whitelist; it is an approval-free list.** The model can still call tools not in it.
   The "no write tools" property of `clarify()` / `judge()` rests on the [`whitelist_guard`](#whitelist-guard) hook.
   And `coordinator()` defaults to `permission_mode="acceptEdits"` — pass that value into
   `clarify()` / `judge()` and the protection is gone.
4. **`disallowed_tools` is session-scoped**, so it also disables the same-named tools inside subagents.
5. **The workbench index does not reach subagents.** "Write long output to `artifacts/`" must be restated by the coordinator
   in the task brief; that is the only channel.
6. **`Runtime(...)` raises `RuntimeError` at construction time when credentials are missing**, not at `run()`.
7. **`Runtime.run_id` must be unique per instance.** `manifest.json` deduplicates on the `run` field, so if two ids collide
   the later writer will treat the other's rows as "its own from last time" and delete them.

### Workflow {#陷阱-流程}

8. **`Workflow.continuous=True` is the default**, so `resume_from=None` does not mean "a brand new session".
   To always start fresh, set `continuous=False` explicitly. **Renaming a step severs its lineage.**
9. **`with_goal(rounds=N)` is the total number of rounds, not extra rounds**: `retries = max(0, rounds - 1)`.
10. **`on_fail="skip"` does not write `ctx[step.name]`** — a downstream `lambda ctx: ctx["某步"]` will `KeyError`.
    To carry a partial result forward, use `on_fail="continue"`.
11. **`resume_from` pointing at a step that never ran or already failed raises `ValueError`**, it is not silently skipped.
12. **`Step.reduce` must be synchronous; `gate` / `when` / `on_reject` may be async.**
13. **`fork=True` is silently a no-op without `resume`.** `Workflow` never passes `resume_at`;
    to roll back by message you must call `Runtime.run` directly.
14. **When driving `Runtime` yourself, `on_session` must be detached before the gate**, otherwise the judge's session
    gets written into the working step's lineage. `Workflow` guarantees this with `try/finally`.
15. **`step_name` determines the keys in the manifest and in lineage.** `Workflow` appends `#retryN` / `#roundN`,
    the judge appends `#轮次` — **suffixed names never enter cross-process lineage**, which is one of the ways
    "the judge is always a new session" is implemented.

### Roles {#陷阱-角色}

16. **`clarify(max_turns=<small number>)` makes "unlimited questions" meaningless** — each question is one turn.
17. **`goal_step()` has no `can_run` parameter**; you must pass `can_run=True` through `**spec_kw`.
    Without it the goal-setting judge gets no `Bash`, and the "first get a clear picture of the environment you are in"
    rule in `JUDGE_RULES` cannot be carried out.
18. **`judge(can_run=True)` lets the judge modify the workspace** — `whitelist_guard` is derived from `allowed_tools`,
    so granting `Bash` permits `Bash` (it still blocks `Write`/`Edit`, but `Bash` itself can write files). For absolute neutrality, leave it off.
19. **`worker(isolate=True)` requires the workspace to be a git repository**, otherwise the `Agent` tool reports
    `"not in a git repository"` outright — it does not silently degrade. Also, the isolation marker is a Python attribute,
    so **`dataclasses.replace()` on an `AgentDefinition` will drop it**.
20. **When constructing `AgentDefinition` directly the parameters are camelCase**: `maxTurns`, `permissionMode`.
    `worker()` already converts them for you.

### Handoff and context {#陷阱-换代}

21. **With handoff on, auto-compact is forcibly disabled, with no fallback.** So the step that writes the handoff document
    must have a degraded path. To keep auto-compact, set `AgentSpec.compact` explicitly.
22. **A too-small `HandoffPolicy.window` will hand off endlessly and burn money.** The only brake is `max_generations=8`.
    On the other side, **`default_window()` also returns `1_000_000` when neither environment variable is set** —
    an over-large estimate is caught by `is_overflow()` (turning into one degraded handoff); not a hard error, but that generation's handoff is degraded.
23. **Without a workbench, handoffs are not spilled.** The document still reaches the successor through the prompt,
    but a human cannot go back and read it afterwards.

### Storage {#陷阱-存储}

24. **`Runtime(trim=False)` (the default) does not mean "nothing gets cleaned".** The store is always a `PruningSessionStore`;
    `trim=False` only disables large-result trimming. **Disconnect residue is plucked out, rejected calls are plucked out,
    interruption leftovers are neutralized, and time-sensitive content still expires.**
25. **The two spill directories are not the same**: `spill_guard` lands in `<workbench.root>/spill/`,
    `TrimPolicy.spill_dirname` lands in `<workspace>/.flower/spill/` (which must be inside the workspace).
26. **`PruningSessionStore.__init__`'s fourth positional parameter is `prune`, not `ephemeral`**,
    unlike the parent class. Passing positionally will silently misalign.

### Documents and interaction {#陷阱-文书}

27. **When `Verdict` cannot parse a conclusion, `state=""` and `ok=False`; this must never be read as achieved.**
    Also "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" all map to `unreachable`,
    which takes the "stop and ask a human" path, not "run another round".
28. **`Brief.parse` discards everything after an unclosed code fence** — when model output is truncated,
    none of the later sections parse, `complete()` is `False`, and the gate sends it back.
29. **`Brief.load` treats `"(未填)"` as empty.** If you edit the brief by hand and copy the placeholder text along,
    that section still counts as missing.
30. **`HumanChannel`'s three "0 / None" semantics all differ**: `max_asks=None` unlimited, `max_asks=0` no questions;
    `timeout_s=None` wait forever, `timeout_s<=0` time out immediately; `remaining` returns **`-1`** when `max_asks=None`.
31. **`Event("ask")` carries both questions and things the human said unprompted**, the latter with `payload["kind"] == "mail"`. The UI must check that first.
32. **`Workflow.run` only wires things up when `channel.on_event is None`** —
    if you construct `HumanChannel(on_event=...)` yourself, question events will not also reach the workflow's `on_event` outlet.
