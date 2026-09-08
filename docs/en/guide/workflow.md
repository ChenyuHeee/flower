# Designing a workflow

The framework only handles mechanism: how a step runs, how sessions are joined, what happens on
failure, how context is saved.
**The [workflow](../reference/glossary.md#流程) is yours to write** — the framework does not know
what project you are on or what language you use, and it should not know. This page is about how
to design a workflow; the complete field tables for `Step` and `Workflow` are in the
[Python API](../reference/api.md).

## What problem it solves {#解决什么问题}

A [long-horizon](../reference/glossary.md#长程) run is not something one prompt can express:
first clarify the requirement, then research, then implement, then review — each segment has its
own role, its own context, its own acceptance condition.
Cram it all into one prompt and the model decides on its own which segment to skip; write it as a
workflow and **the ordering, the exit conditions and the state passing become Python code** —
readable, testable, and you can rerun only the step that broke.

`Workflow` does exactly three things:

- Run a sequence of [steps](../reference/glossary.md#步骤) in order
- Decide what each step can see of what came before (three ways of joining sessions, plus a `ctx` dict)
- Decide when to retry and when to exit early

It contains no domain assumptions. Where to cut, what each step must pass, what to do when it
does not — those four things *are* "designing a workflow".

## How to use it (minimal code) {#怎么用最小代码}

```python
# flows.py
from flower import AgentSpec, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


def main() -> Workflow:
    return Workflow([
        # New session: sees only what the prompt passes in
        Step("取词", terse, "读 seed.txt,只回文件里那个词。"),
        # Still a new session; inject the previous step's output into the prompt (cheap, no contamination)
        Step("造句", terse, lambda ctx: f"用「{ctx['取词']}」造一个五字短句,只回短句。"),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo
```

The argument to `flower run` is `module:attribute` or `file path:attribute`. If the object
retrieved is callable it is called once, and the resulting `Workflow` is run; when it finishes the
terminal prints the total cost and the path to the run manifest.

Writing your own driver works too — the first argument to `Workflow.run` is a `Runtime`:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## What it actually does {#它实际做了什么}

### What a Step receives, and what it must return {#一个-step-收到什么必须返回什么}

`Step` is not a function, it is a **declaration**. What actually executes is
`Runtime.run(step.spec, the rendered prompt, ...)` —
**one step = one `Runtime.run` = one [session](../reference/glossary.md#会话)**.

The first three fields are positional: `Step(name, spec, prompt)`.

- `name` — the step name. It is simultaneously the key in `ctx`, the row name in
  `runs/manifest.json`, and the key for cross-process [lineage](../reference/glossary.md#血缘).
- `spec` — which `AgentSpec` runs this step. It determines this step's tool allowlist, model and
  budget.
- `prompt` — a `str`, or `(ctx) -> str`. When callable it receives the current `ctx`;
  **this is the cheapest way to feed the previous step's output in** (the other way is joining
  sessions, see below).

What this step "returns" is a `StepResult`, but inside the workflow you get two things:

- `ctx[step name]` — by default `result.text`; if you gave a `reduce`, the return value of `reduce` instead;
- `ctx["_results"][step name]` — the full `StepResult` (cost, turns, attempt count, `session_id`).

`result.text` **collects only main-thread body text**: a subagent's utterances live in its own
transcript, the [task brief](../reference/glossary.md#任务书) dispatched to it is `kind="prompt"`,
and a synthetic disconnect error is `kind="error"` — none of the three get in.

### reduce: not sugar {#reduce不是糖}

By default what is passed downstream is the model's literal words. For some steps those words
**should not** go downstream verbatim:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

In practice the clarify step will, beyond the four sections, **paste in the entire codebase**.
What goes downstream must be the four parsed sections, otherwise that pile of code lands in the
next step's prompt. `clarify_step` relies on this field to contain it.

`reduce` **must be a synchronous function**; `gate` / `when` / `on_reject` may be async.

### How state flows through ctx {#状态怎么在-ctx-里流动}

`ctx` is a `dict[str, Any]` — it *is* `Workflow.context`. After each step runs, writes follow this table:

| Case | `ctx[step name]` | Other |
|---|---|---|
| `when(ctx)` returns False | **not written**, the whole step is skipped | no result is produced, nothing enters `_results` |
| Passed | `reduce(result, ctx)`, or `result.text` if none given | |
| Failed + `on_fail="stop"` (default) | **not written** | writes `ctx["_failed_at"]`, the whole workflow stops here |
| Failed + `on_fail="skip"` | **not written** | continues on |
| Failed + `on_fail="continue"` | `result.text` (the partial one, **not passed through `reduce`**) | continues on |

Pass or fail, `ctx["_results"][step name]` is always written; if `result.session_id` is non-empty
it is also written into `ctx["_sessions"]` and recorded in lineage.

**To decide whether this workflow succeeded, look at `ctx.get("_failed_at")`**, not at whether the
last step produced output.

Keys beginning with an underscore are placed there by `Workflow.run` itself: `_runtime`,
`_on_event`, `_sessions`, `_results`, `_lineage`, `_woke`, `_aborted`, `_failed_at` — don't use
them as your own step names. Individual mechanisms add their own (`_brief` / `_goal` / `_verdict`
and so on); the full list is in the [Python API](../reference/api.md).

Among those, `_runtime` and `_on_event` exist for `gate`: a gate can dispatch an agent of its own
to render a verdict, and that verdict process still prints to the UI — otherwise the interface
goes dark for a dozen-plus seconds and looks hung.
[Goal guard](goal.md) is implemented exactly this way.

`ctx` is one and the same dict: **run the same `Workflow` object a second time and last run's keys
are still there**. For a clean restart, build a new one, or pass `context={}` explicitly.

!!! warning "With on_fail=skip, `ctx[step name]` is not written"
    Downstream code written as `lambda ctx: ctx["some step"]` will raise `KeyError` outright. To
    carry a partial result forward, use `on_fail="continue"`; if you really want to skip,
    downstream has to fall back with `ctx.get(...)` itself.

### Verdicts and rejections: gate, on_reject, StepAbort {#判定与打回gateon_rejectstepabort}

`gate(result, ctx) -> bool` judges "it finished, but is it acceptable?" Two details you must know:

- **When `result.ok` is false, `gate` is never called at all** (short circuit).
- **It is called exactly once per attempt**, and the conclusion is kept for later use — it may
  have side effects. `clarify_step`'s gate spills the
  [brief](../reference/glossary.md#需求确认书) to disk; triggering it repeatedly writes to disk
  repeatedly.

How the retry proceeds after the gate fails depends on whether you gave an `on_reject`:

| | How the next round runs | Name in the manifest |
|---|---|---|
| `retries` only | Runs from scratch, original prompt, original `resume_from` | `X#retry1` |
| Plus `on_reject` | **Continues the very session that was just rejected**, the prompt becomes `on_reject`'s return value, `fork` is forced to False | `X#round2` |

The second is "send it back, say what was missing, let it keep filling in" — the work already
done and the context are both still there.
If `on_reject` returns an empty string, or that attempt never obtained a `session_id`, it degrades
to running from scratch.

`gate` can also raise `StepAbort`, meaning **trying again won't help, don't burn the remaining rounds**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

After it is raised: the reason is recorded in `ctx["_aborted"]`, the step is treated as a failure
and follows `on_fail` (default `"stop"`), **the retry loop breaks on the spot**, and not one of
the remaining `retries` is consumed.

Keep the difference straight: **returning False is "not this time, one more round"; `StepAbort` is
"another round won't help."**
The typical occasion is a goal judged impossible in this environment with nobody to ask — spinning
on is the most expensive option.

### Don't confuse the two layers of retry {#两层重试别混}

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| Covers what | Business failure: `gate` fails, `result.ok` is false | Infrastructure: network jitter, disconnection, 5xx |
| How it retries | **The whole step over again**, same prompt and `resume_from` | **Resumes from the point of interruption**, prior spend is not wasted |
| What it does meanwhile | Nothing | DNS + TCP probes waiting for the network to come back (no HTTP, no credentials — probes must be free) |
| Non-retryable | — | Bad credentials, bad arguments: stop immediately, no waiting |

The prompt used to resume **deliberately contains no error detail** — the model needs to know "you
were interrupted, carry on", not whether it was ENOTFOUND or 503.

### Stringing steps together {#把步骤串起来}

There are three ways to pass state between steps, and which you pick determines what the next step
can see:

| Form | What the next step sees | Where it's used |
|---|---|---|
| `resume_from=None` (default) + injected into the prompt | Only the words you injected | Independent steps. Cheap, no contamination |
| `resume_from="previous step"` | The full session history | When continuous memory is needed |
| `resume_from="previous step"` + `fork=True` | The full history, but on a separate branch | Review / parallel alternatives / retries that don't dirty the original line |

The step `resume_from` points at **must actually have produced a session**. If it was skipped by
`when`, or never ran, `Workflow.run` raises `ValueError` outright — it does not silently degrade
to a new session, because that would quietly invalidate the "continuous memory" assumption.

A few design lessons paid for repeatedly:

1. **One acceptable goal per step.** The step boundary is the context boundary: wherever
   `resume_from=None`, all those earlier tool results stop being resident for good. See
   [context economics](context.md).
2. **When unsure, `clarify_step` first.** In a long-horizon run, "misunderstood the goal" is the
   most expensive error, and it happens to be exactly the kind those context-saving layers cannot
   clear. See [clarify](clarify.md).
3. **Dispatched tasks must be self-contained.** A subagent has clean context; it does not know what
   the [coordinator](../reference/glossary.md#协调者) knows. Write the needed background into the
   task brief, or tell it which artifact to read.
4. **Long output goes to disk, not back through the conversation.** This is already written into
   `WORKER_RULES`; don't let your `instructions` cancel it out ("paste the full log back for me to
   see").
5. **Have `gate` check hard conditions first.** Whether a file exists, whether the exit code is 0 —
   don't dispatch a model for what one line of Python can decide. If you do need a model to judge,
   use the ready-made `with_goal` — it replaces the gate with an implementation that runs an
   independent [judge](../reference/glossary.md#判定者); don't hand-roll one inside a gate.
6. **Parallel edits to the same repository mean `worker(isolate=True)`.** Wrap-up (merging,
   cleaning up worktrees, opening a PR) is currently left to your own workflow; the harness only
   guarantees the changes land in their respective worktrees.

### The workbench must hang off the Workflow {#工作台要挂在-workflow-上}

Wherever the workflow writes files into the [workbench](../reference/glossary.md#工作台) — the
typical case being `clarify_step(brief_path=...)` — you must build a `Workbench` yourself and
attach it **both** to `Workflow.workbench` and to the `Runtime`:

```python
from pathlib import Path

from flower import (HumanChannel, Runtime, Step, Workbench, Workflow,
                    clarify_step, coordinator, worker)

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md", timeout_s=1800.0)

主控 = coordinator("协调者", "", {
    "coder": worker("写代码与测试。要动手实现的活派给它。",
                    "你负责实现。每改一处就跑一次验证,别攒到最后。"),
}, channel=ch)

wf = Workflow(
    [
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
    ],
    channel=ch,
    workbench=wb,
)

rt = Runtime(workspace=Path.cwd(), run_dir="runs", workbench=wb)
```

There are two reasons `channel` hangs off the workflow: `run()` wires its `on_event` to the same
event outlet (only when `channel.on_event` is still `None`), and the driver program relies on this
field to know whom to answer.

!!! warning "Assembling the workbench path yourself fails silently"
    The default location for `Runtime(workbench=True)` is `<run_dir>/workbench`, while
    `Workbench(ws)` defaults to `<ws>/.flower` — **the two are not the same directory**. When the
    workflow is invoked by the CLI it cannot see `run_dir`, so assembling the path yourself only
    ever points somewhere else: the brief is written into directory A while the injected index
    scans directory B, **and nothing raises**. Build one object and share it on both sides and the
    problem disappears; when `Workflow.workbench` exists, the command line's `-W` is ignored in its
    favour.

### `continuous=True`: running the same path again {#continuoustrue同一个路径再跑一次}

The three joining forms above are about steps **within one run**. Across processes is another axis:

```python
Workflow([...], continuous=True)     # default
```

Run the same workspace again and every step continues the session it had last time — via the
"step name → session_id" map in `<run_dir>/lineage.json`. At load time each record is verified
through `runtime.has_session()` to confirm the session is still in the store, and used only if it
is alive: the lineage file can outlive `sessions.db`, and resuming a session that does not exist
only blows up once the subprocess starts.

Three consequences:

- **`resume_from=None` does not mean "a brand-new session."** It does on the first run, not on the
  second. If you want a new session every time, write `Workflow(..., continuous=False)` explicitly.
- **Context keeps growing across [continuity](../reference/glossary.md#接续).** If you want to say
  something different on resume, use `Step.resume_prompt` — what is already in the other side's
  context should not be resent.
- Steps with an explicit `resume_from` are unaffected; it takes precedence.

!!! warning "The step name is the cross-process key"
    Renaming a step severs that step's lineage: the next run no longer continues it, **and nothing
    raises**. Retry names carrying a `#retry1` / `#round2` suffix **do not enter lineage** (the
    original name is always what gets recorded), which is one of the ways "the judge is always a
    new session" is implemented.

For the full design and `--new`, see [continuity](continuity.md).

## When not to use it {#什么时候不该用它}

- **Only one agent to run and no verdict needed** — don't wrap it in a `Workflow`. Just
  `await rt.run(spec, "…")`, or on the command line `flower once "读一眼这个仓库"`.
- **The shape is exactly "clarify → set goal → work"** — use the ready-made
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py)
  instead of writing your own:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    It is **three steps**: `确认需求` → `设定目标` → `干活` (with a verdict loop; the verdict step
    is called `干活·判定#N`). With `goal=False` there is no second step and no verdict loop; with
    `clarify_only=True` only the first step remains.
    It brings its own `HumanChannel` and `Workbench` and attaches them to the workflow, so
    `Runtime(workbench=wf.workbench)` can be used directly — don't assemble another one.

    You don't have to write code either: `cd` into the project and `flower "帮我做一个 X"` runs
    exactly this. **It is not "the recommended workflow design"**, only a way to get running with
    zero configuration.

- **Steps cut finer than "one acceptable goal"** — a net loss. Every step has to start a new
  session, and a new session has a startup floor (measured at roughly 34k of context for a
  coordinator) that cannot be amortised away.
- **Wanting to roll back to a particular message afterwards** — `Workflow` cannot get you there,
  it never passes `resume_at`. Call `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)`
  directly.

For how to pick a role (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) and the
field-by-field semantics of `Step` and `Workflow`, see the [Python API](../reference/api.md); for
the vocabulary, see the [glossary](../reference/glossary.md).
