# Designing a workflow

The framework only handles mechanism: how a step runs, how sessions connect, what happens on failure, how context is saved.
**[The workflow](../reference/glossary.md#流程) is yours to write** — the framework doesn't know what project you're on or what language you use,
and it shouldn't. This page is about designing one; the full field tables for `Step` and `Workflow` are in the
[Python API](../reference/api.md).

## What problem it solves

A [long-horizon](../reference/glossary.md#长程) run isn't something a single prompt can express: first clarify the requirement,
then research, then implement, then review — each segment has its own role, its own context, its own acceptance condition.
Cram it all into one prompt and the model decides for itself which segments to skip; write it as a workflow and
**order, exit conditions and state passing become Python code** — readable, testable, and you can rerun only the step that broke.

`Workflow` does exactly three things:

- Runs a sequence of [steps](../reference/glossary.md#步骤) in order
- Decides what each step can see of what came before (three ways to connect sessions + one `ctx` dict)
- Decides when to retry and when to exit early

It carries no domain assumptions. Where to cut, what each step accepts, what to do on rejection — those four things *are* "designing a workflow".

## How to use it (minimal code)

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

The argument to `flower run` is `module:attribute` or `path/to/file:attribute`. If the resolved object is callable it gets called once,
and the resulting `Workflow` is run; when it finishes the terminal prints the total cost and the path to the run manifest.

Writing your own driver works too — the first argument to `Workflow.run` is a `Runtime`:

```python
ctx = await wf.run(rt, on_step=lambda step, r: print(f"{step.name} ok={r.ok} ${r.cost_usd:.4f}"))
```

## What it actually does

### What a Step receives, and what it must return

A `Step` is not a function, it's a **declaration**. What actually executes is `Runtime.run(step.spec, the_rendered_prompt, ...)` —
**one step = one `Runtime.run` = one [session](../reference/glossary.md#会话)**.

The first three fields are positional, `Step(name, spec, prompt)`:

- `name` — the step name. It is simultaneously the key in `ctx`, the row name in `runs/manifest.json`,
  and the key for cross-process [lineage](../reference/glossary.md#血缘).
- `spec` — which `AgentSpec` to run with. It determines this step's tool allowlist, model and budget.
- `prompt` — a `str`, or `(ctx) -> str`. When callable it receives the current `ctx`;
  **this is the cheapest way to feed the previous step's output in** (the other way is connecting sessions, see below).

What a step "returns" is a `StepResult`, but in the workflow you get two things:

- `ctx[step.name]` — `result.text` by default, replaced by the return value of `reduce` if you gave one;
- `ctx["_results"][step.name]` — the full `StepResult` (cost, turns, attempts, `session_id`).

`result.text` **collects main-thread prose only**: a subagent's utterances live in its own transcript, the
[task brief](../reference/glossary.md#任务书) dispatched to it is `kind="prompt"`, a synthesized disconnect error is `kind="error"`
— none of the three get in.

### reduce: not sugar

By default what flows downstream is the model's literal words. Some steps' literal words **shouldn't** flow downstream as-is:

```python
Step("确认需求", spec=确认者, prompt="帮我做一个 X",
     reduce=lambda r, ctx: ctx["_brief"].prompt_block())
```

In practice the clarify step will **paste the entire codebase in** on top of the four sections. What goes downstream must be the four parsed sections,
otherwise that pile of code lands in the next step's prompt. `clarify_step` is held together by this field.

`reduce` **must be synchronous**; `gate` / `when` / `on_reject` may be async.

### How state flows through ctx

`ctx` is a `dict[str, Any]` — it *is* `Workflow.context`. After each step it's written per this table:

| Case | `ctx[step name]` | Other |
|---|---|---|
| `when(ctx)` returns False | **not written**, whole step skipped | no result produced, nothing in `_results` |
| Passed | `reduce(result, ctx)`, or `result.text` if not given | |
| Failed + `on_fail="stop"` (default) | **not written** | writes `ctx["_failed_at"]`, the whole workflow stops here |
| Failed + `on_fail="skip"` | **not written** | continues on |
| Failed + `on_fail="continue"` | `result.text` (the partial one, **not passed through `reduce`**) | continues on |

Pass or fail, `ctx["_results"][step name]` is always written; if `result.session_id` is non-empty it is also written into
`ctx["_sessions"]` and recorded in lineage.

**To judge whether the workflow succeeded, look at `ctx.get("_failed_at")`**, not at whether the last step produced output.

Keys starting with an underscore are placed by `Workflow.run` itself: `_runtime`, `_on_event`, `_sessions`, `_results`,
`_lineage`, `_woke`, `_aborted`, `_failed_at` — don't use them as your own step names. Individual mechanisms add their own
(`_brief` / `_goal` / `_verdict`, etc.); the full list is in the [Python API](../reference/api.md).

Of these, `_runtime` and `_on_event` are for `gate`: a gate can dispatch its own agent to make a verdict,
and that verdict process still renders to the UI — otherwise the interface goes black for a dozen-odd seconds and looks hung.
[The goal guard](goal.md) is implemented exactly this way.

`ctx` is one and the same dict: **run the same `Workflow` object a second time and the previous run's keys are still there**.
For a clean restart, build a new one, or pass `context={}` explicitly.

!!! warning "on_fail=skip does not write `ctx[step name]`"
    A downstream `lambda ctx: ctx["某步"]` will raise `KeyError` outright. To carry a partial result forward use
    `on_fail="continue"`; if you really want to skip, downstream code must fall back with `ctx.get(...)`.

### Verdict and rejection: gate, on_reject, StepAbort

`gate(result, ctx) -> bool` judges "it ran, but is it acceptable?". Two details you must know:

- **When `result.ok` is false, `gate` is never called at all** (short-circuit).
- **It is called exactly once per attempt**, and the conclusion is kept for later use — it may have side effects. `clarify_step`'s gate
  spills the [brief](../reference/glossary.md#需求确认书) to disk; triggering it repeatedly writes the disk repeatedly.

How a rerun happens after a gate rejection depends on whether you gave `on_reject`:

| | How the next round runs | Name in the manifest |
|---|---|---|
| `retries` only | from scratch, original prompt, original `resume_from` | `X#retry1` |
| plus `on_reject` | **resumes the very session that was just rejected**, prompt replaced by `on_reject`'s return value, `fork` forced to False | `X#round2` |

The second is "send it back, say what's missing, let it keep working" — the work already done and the context are still there.
If `on_reject` returns an empty string, or that attempt never got a `session_id`, it degrades to a from-scratch rerun.

`gate` may also raise `StepAbort`, meaning **trying again won't help, don't burn the remaining rounds**:

```python
from flower import StepAbort

def gate(result, ctx):
    if "这个环境装不了依赖" in result.text:
        raise StepAbort("环境缺依赖,再跑几轮也一样")
    return "验收通过" in result.text
```

After it's raised: the reason is recorded in `ctx["_aborted"]`, the step is treated as failed and follows `on_fail` (default `"stop"`),
**the retry loop breaks immediately**, and none of the remaining `retries` are consumed.

Keep the distinction: **returning False means "not this time, go another round"; `StepAbort` means "another round won't help".**
The typical case is a goal judged impossible in this environment with nobody to ask — spinning on is the most expensive option.

### Don't conflate the two retry layers

| | `Step.retries` | `Runtime(resilience=...)` |
|---|---|---|
| Covers | business failure: gate rejected, `result.ok` false | infrastructure: network flapping, disconnection, 5xx |
| How it reruns | **whole step from scratch**, same prompt and `resume_from` | **resumes from the interruption point**, prior cost isn't wasted |
| What it does meanwhile | nothing | DNS + TCP probes waiting for the network to come back (no HTTP, no credentials — probes must be free) |
| Non-retryable | — | bad credentials or bad arguments stop immediately, no waiting |

The prompt used for resuming **deliberately contains no error detail** — the model needs to know "you were interrupted, carry on",
not whether it was ENOTFOUND or 503.

### Connecting steps

There are three ways to pass state between steps, and the choice determines what the next step can see:

| Form | What the next step sees | Where to use it |
|---|---|---|
| `resume_from=None` (default) + injection via prompt | only the text you injected | independent steps. Cheap, no contamination |
| `resume_from="previous step name"` | the full session history | when coherent memory is needed |
| `resume_from="previous step name"` + `fork=True` | the full history, but on a separate branch | review / parallel alternatives / retries that don't dirty the original line |

The step that `resume_from` points at **must actually have produced a session**. If it was skipped by `when`, or never ran,
`Workflow.run` raises `ValueError` outright — it does not silently degrade to a new session, because that would quietly
invalidate the "coherent memory" assumption.

A few design lessons paid for repeatedly:

1. **One acceptable goal per step.** Step boundaries are context boundaries: wherever `resume_from=None`,
   the earlier tool results stop being resident for good. See [context economics](context.md).
2. **When unsure, `clarify_step` first.** In long-horizon runs "misunderstood the goal" is the most expensive error,
   and it happens to be exactly the kind that none of the context-saving layers can clear. See [clarify](clarify.md).
3. **A dispatched task must be self-sufficient.** A subagent has clean context; it doesn't know what the
   [coordinator](../reference/glossary.md#协调者) knows. Put the needed background in the task brief, or tell it which artifact to read.
4. **Long output goes to disk, not back through the reply.** This is already in `WORKER_RULES`; don't have your `instructions`
   cancel it out ("paste the full log back for me to see").
5. **Prefer hard conditions in `gate`.** Whether a file exists, whether the exit code is 0 — if one line of Python can decide it, don't dispatch a model.
   If you do need a model to decide, use the ready-made `with_goal` — it swaps the gate for an implementation that runs an independent
   [judge](../reference/glossary.md#判定者); don't hand-roll one inside a gate.
6. **Parallel edits to the same repo mean `worker(isolate=True)`.** Wrap-up (merging, cleaning worktrees, opening a PR) is currently left to
   your workflow; the harness only guarantees changes land in their own worktrees.

### The workbench must be attached to the Workflow

Any time the workflow writes files into the [workbench](../reference/glossary.md#工作台) — typically
`clarify_step(brief_path=...)` — you must build a `Workbench` yourself and attach it **both** to `Workflow.workbench`
and to the `Runtime`:

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

There are two reasons `channel` hangs off the workflow: `run()` wires its `on_event` to the same event outlet
(only when `channel.on_event` is still `None`), and the driver program relies on this field to know who to answer.

!!! warning "Hand-assembling the workbench path fails silently"
    The default location for `Runtime(workbench=True)` is `<run_dir>/workbench`, whereas `Workbench(ws)` defaults to
    `<ws>/.flower` — **these are not the same directory**. When a workflow is invoked by the CLI it can't see `run_dir`, so assembling
    the path yourself only assembles a different one: the brief is written into directory A while the injected index scans directory B,
    **and nothing raises an error**. Build one object and share it on both sides and the problem disappears; when `Workflow.workbench` exists,
    the command line's `-W` is ignored in its favour.

### `continuous=True`: running the same path again

The three connection forms above are about steps **within one run**. Across processes is a different axis:

```python
Workflow([...], continuous=True)     # 默认值
```

Run the same workspace again and every step continues the session it had last time — via the
"step name → session_id" map in `<run_dir>/lineage.json`. On load, each record is validated with `runtime.has_session()` to check the session
is still in the store, and only used if alive: the lineage file can outlive `sessions.db`, and resuming a session that doesn't exist
won't blow up until the subprocess starts.

Three consequences:

- **`resume_from=None` does not mean "a brand-new session".** It does on the first run, not on the second. If you want a new session every time,
  write `Workflow(..., continuous=False)` explicitly.
- **Context keeps growing across [continuity](../reference/glossary.md#接续).** If you want to say something different on continuation, give
  `Step.resume_prompt` — what's already in the other side's context shouldn't be resent.
- Steps with an explicit `resume_from` are unaffected; it takes priority.

!!! warning "Step names are cross-process keys"
    Renaming a step severs that step's lineage: the next run no longer continues, **and nothing raises an error**. Retry names carrying
    `#retry1` / `#round2` suffixes **do not enter lineage** (what's recorded is always the original name), which is one of the ways
    "the judge is always a new session" is implemented.

For the full design and `--new`, see [continuity](continuity.md).

## When not to use it

- **A single agent, no verdict needed** — don't wrap it in a `Workflow`. Just `await rt.run(spec, "…")`,
  or on the command line `flower once "读一眼这个仓库"`.
- **The shape is exactly "clarify → set goal → work"** — use the ready-made
  [`starter_flow()`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py)
  instead of writing your own:

    ```python
    from flower import starter_flow

    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs",
                      rounds=3, timeout_s=1800.0, isolate=False)
    ```

    It is **three steps**: `确认需求` → `设定目标` → `干活` (with a verdict loop; the verdict step is called `干活·判定#N`).
    With `goal=False` there is no second step and no verdict loop; with `clarify_only=True` only the first step remains.
    It brings its own `HumanChannel` and `Workbench` attached to the workflow, so
    `Runtime(workbench=wf.workbench)` can be used directly — don't assemble another one.

    You don't have to write code at all: `flower "帮我做一个 X"` inside a project directory runs exactly this.
    **It is not "the recommended workflow design"**, it just gets you running with zero configuration.

- **Steps cut finer than "one acceptable goal"** — a net loss. Every step starts a new session, and a new session has a
  startup floor (measured at roughly 34k context for a coordinator) that can't be amortized away.
- **You want to roll back to a specific message after the fact** — `Workflow` can't get you there; it never passes `resume_at`.
  Call `Runtime.run(spec, "从这里重来", resume=sid, resume_at=uuid)` directly.

For how to choose a role (`coordinator` / `worker` / `clarify` / `judge` / `oracle`) and the field-by-field semantics of
`Step` and `Workflow`, see the [Python API](../reference/api.md); for the terms, see the [glossary](../reference/glossary.md).
