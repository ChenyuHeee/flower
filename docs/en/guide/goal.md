# Goal guard

"Is it done" is not the worker's call. The [judge](../reference/glossary.md#判定者) is a role that
only sets the goal, only renders a verdict, and never touches the work: before the run starts it turns the
[brief](../reference/glossary.md#需求确认书) into a checklist that can actually be judged; after that, at the
end of every round of work it **judges once, independently**, and produces a
[verdict](../reference/glossary.md#判定) — achieved, move on; not achieved, send it back with "what's
missing" and keep going; judged impossible, stop and ask a human.

## What problem it solves {#解决什么问题}

[Clarify](clarify.md) blocks **"it built the wrong thing"**. This layer blocks a different failure:
**"it isn't actually done, but it says it is"**. The two must be kept apart, because they fail differently:

| | What the failure looks like | When it surfaces |
|---|---|---|
| Wrong requirement | Every artifact was built against the wrong requirement | Hours later, all of it wasted |
| Wrong completeness call | Half the tests run, one spot fixed and three missed, "should be fine" | When you go to use it yourself |

Why the second one can't be left to the worker: **it has a systematic optimism bias**.
This isn't dishonesty — it can't see its own blind spots. It knows what it did; it doesn't know what it missed.

So the verdict goes to a role that **did none of the work and runs in its own
[session](../reference/glossary.md#会话)**. All it sees is the goal and the scene; it doesn't know how many
times the worker tried or how hard it was, so it won't make excuses on its behalf. This is the same reasoning
behind running the clarifier in an independent session.

## How to use it (minimum code) {#怎么用最小代码}

### Zero code: the command line {#零代码命令行}

```bash
flower                      # goal guard is on by default
flower --no-goal            # off: the run ends when the work ends
flower --rounds 5           # at most five rounds of work (default 3)
flower --judge-can-run      # let the judge run commands (harder verdicts)
```

### Wiring it yourself {#自己接线}

Two functions each cover half; don't mix them up: `goal_step()` **sets the goal** (a standalone step),
`with_goal()` is the **verdict loop** (it wraps a step that does work).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # unlimited questions by default
goal_path = wb.notes / "目标.md"

work = Step("干活", spec=协调者, prompt=lambda ctx: f"照这个做:\n{ctx['确认需求']}")

wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    goal_step(ch, goal_path=goal_path),
    with_goal(work, ch, goal_path=goal_path, rounds=3),
])
```

`goal_step(channel, *, goal_path, ...)`:

| Parameter | Default | Description |
|---|---|---|
| `goal_path` | — | Where the goal lands. Put it under the [workbench](../reference/glossary.md#工作台)'s `notes/`, same reason as the brief |
| `brief_key` | `"确认需求"` | Which key of `ctx` to read the brief from. **If it isn't there you only get `"(没有确认书)"`** |
| `name` | `"设定目标"` | Step name, and also the key in `ctx` |
| `spec` / `instructions` | `None` / `""` | Bring your own `AgentSpec`, or append domain instructions to the judge |
| `always_set` | `False` | `True` = re-derive every time |
| `on_fail` / `retries` | `"stop"` / `0` | Same as `Step` |
| `**spec_kw` | — | Passed through to `judge()`: `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` wraps a working step into a loop with verdicts:

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` is the total number of rounds, not extra rounds** — it lands as `retries = max(0, rounds - 1)`,
so `rounds=3` means at most three rounds of work, and `rounds=1` means "run once, judge once, fail if it
doesn't pass". For the full signature and field semantics see the [Python API](../reference/api.md).

Three extra keys show up in `ctx`:

```python
ctx[GOAL_KEY]     # "_goal" —— the Goal object; ctx["设定目标"] is its markdown
ctx[VERDICT_KEY]  # "_verdict" —— the most recent Verdict, for the UI
ctx[ROUND_KEY]    # "_goal_rounds" —— how many rounds have run
```

The judge is dispatched through `ctx["_runtime"]` — `Workflow.run` puts both the runtime and the event sink
into `ctx`, so `gate` can start an agent of its own while the judging still streams to your UI
(otherwise the screen goes dark for a dozen seconds and looks stuck).

When it doesn't behave, turn these knobs first:

| Symptom | Which knob |
|---|---|
| Verdicts too lenient, says achieved when it isn't | `--judge-can-run` so it actually runs things; or add domain criteria via `instructions` |
| Verdicts too strict, everything gets sent back | Check whether the checklist in `目标.md` is set higher than the requirement. **Edit that file** |
| Spinning round after round | The judge should have said "unreachable" but said "not yet". Add instructions on what counts as impossible |
| Too expensive | `--rounds 1`, or `--no-goal` to turn it off entirely |
| Don't want to be interrupted | `--timeout 0`: on unreachable it doesn't ask, it just stops (the reason stays on disk) |

## What it actually does {#它实际做了什么}

### What a goal looks like {#目标长什么样}

`goal_step` reads the brief, emits two sections, and freezes them into `.flower/notes/目标.md`:

```markdown
# 目标
Make conv.py turn md into html.

# 判定清单
- Running `python conv.py a.md` produces a.html
- The output contains `<h1>`
- Lists are converted into `<ul><li>`
```

**The checklist is the entire value of this layer.** "Implementation is complete" can't be judged;
"run this, see that" can. The checklist comes from the brief's acceptance criteria, but it has to be rewritten
so every line can be verified on the spot — the judge fills in the vague ones. Both sections must be non-empty
(`statement` says something, `checks` is non-empty) for it to count as complete; otherwise this step doesn't
let you through.

### The length of the checklist is decided by how many ways the task can fail {#清单的长度由有多少种失败方式决定}

Not by how rigorous the judge feels. For a task like `git clone && make && ./app`, **three to five lines are
enough**: it builds, it runs, it works.

**Measured failure** ([HT002](../cases/ht002.md)): a "get this repo installed and running" task got a **15**-line
checklist, of which only **5** verified "does the thing work", **6** verified "did the process follow the rules"
(including checking the mtime of `~/.zshrc` and whether the `.flower/` directory had been modified — that's the
framework's own directory), and **4** were unverifiable in principle.

#### A boundary is not a check item {#边界不是判定项}

That was the main cause that time:

| | What it constrains | How it's honored |
|---|---|---|
| **Boundary** | **How you work** ("install only inside the project directory", "don't touch business code") | By **not crossing it**, not by proving it afterwards |
| **Check item** | **What you hand over** ("does it run", "is the result right") | By verifying on the spot |

Writing "did not run `brew install`" as a check item means every added boundary adds a check —
and boundaries are exactly what the clarify phase encourages you to write plenty of. If you really need an
account of it, one sentence is enough; don't split it into six lines.

### Items that can't be verified are flagged at goal-setting time {#验不了的条目设目标时就会喊}

For items marked `[此环境无法验证:原因]`, `goal_step` fires a warning **at the moment it freezes the goal**:

```text
  # 4/15 items in the goal can't be verified in this environment —— they will necessarily fail at
    judging time and the run will stop to ask you.
    There's still time to edit .flower/notes/目标.md:
      · Screenshot the UI and actually look at the image [此环境无法验证:屏幕录制未授权]
      · ...
```

**Why it has to be early**: the fate of these items is sealed the moment the goal is set; they cannot pass at
judging time. In HT002 this was discovered only after spending **$35.90 on work + $1.40 on judging** —
moving the discovery forward to goal-setting drops the cost of the same information from **$37** to **$0**.

It warns, it doesn't block: a human can choose to run it anyway (HT002 ended up choosing "accept this result").
`Goal.unverifiable` is that list, and the event payload carries structured data for the UI.

### Three outcomes, not two {#三个结论不是两个}

```text
work ──> judge ──achieved────> move on
               ├─not yet─────> send back with "what's missing", resume the same session and continue
               └─unreachable─> stop and ask: accept / change the goal / you judged wrong
```

The third outcome is the crucial one. With only "achieved/not yet", a goal that is **actually impossible** makes
the coordinator spin round after round until the budget is gone — that's the real money burn. So the judge is
explicitly told: unreachable means "another round won't help" (a required external condition is missing, the
requirement contradicts itself, the check item simply can't be verified); "not finished yet" is not yet.

On unreachable, the framework stops and asks:

```text
  ? The goal was judged **unreachable**: dependency X is missing, check item 2 can't be verified
    What now?
     1) Accept this result and move on
     2) Change the goal
     3) You judged wrong, keep going
```

- **Accept** → this step counts as passed, the reason stays in the record
- **Change the goal** → it then asks what the new goal is and **appends** it after the original goal
  (so you can see what changed), then runs another round
- **You judged wrong** (and any free-form answer you type) → your statement goes back with the send-back,
  and another round runs

**If nobody answers, it stops** instead of spinning on — that's deliberate. Judged impossible with nobody to
ask, continuing just burns money round after round, and that's exactly what we most want to avoid. On stopping
it raises `StepAbort`, the reason goes into `ctx["_aborted"]`, the goal file and `runs/manifest.json` are both
there, and a human can pick up the decision later.

!!! warning "'Not done' and 'can't be verified here' are two different verdicts"
    `Verdict` has three values: `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` must never be treated as a pass** — it takes the "stop and ask" path, not the
    "run another round" path. Whatever the judge writes — "无法验证 / 没法验证 / 验证不了 / 无法判定 /
    unverifiable" — **all** of it maps to `UNREACHABLE`. Treating "can't verify here" as "achieved" means
    closing out the work with a "looks like it should work"; treating it as "not yet" means making it redo,
    round after round, something that was never verifiable in the first place.

### An ambiguous verdict = not achieved {#判定含糊--未达成}

The order `Verdict.parse` tries: first take the "结论 / 判定" section by heading; with no heading section,
the whole thing being `1` / `true` counts as achieved and `0` / `false` as not yet (when the judge is told
to "only return 0/1" it may well return exactly one digit); failing that, look for keywords in the conclusion
text (longer words first); finally, look for a lone `1` / `0`.

**When nothing matches, `state` is left empty and `ok` is `False`, and the framework treats it as not
achieved.** This is deliberate: "can't tell" and "done" are two different things, ambiguity always counts as
not achieved, plus a default reason is filled in ("the judge gave no clear conclusion, treated as not achieved").

### It judges the artifact, not the source {#判的是产出物不是源码}

!!! warning "A verdict that only reads source can't judge the deliverable"
    In [HT001](../cases/ht001.md) the acceptance criterion literally read "compile a standalone executable
    that runs directly in a macOS terminal", and the verdict merely read `Makefile:25-38`, saw that a Darwin
    branch was indeed there, and called it a **pass** — the delivered artifact was
    `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **What got it wrong was not the goal guard**: that run didn't have this mechanism yet, and the thing
    judging that item was an independent auditor the coordinator dispatched on its own. But the goal guard
    would have missed it too — the judge defaults to `can_run=False` and only holds `Read` / `Glob` / `Grep`,
    it **can't run `file`**, so it would likewise have had to read the `Makefile` and would likewise have seen
    the Darwin branch and called it achieved. The heart of that failure isn't "who judges", it's
    "on what evidence".

    That lesson is written into `JUDGE_RULES`: what gets judged is the **artifact**; inferences like
    "the source has a macOS branch so it should run" are not accepted.

[HT002](../cases/ht002.md) is the run where `judge_can_run` was on and the judge actually ran `file` / `lsof`,
so it dodged this pit — its first line was "I'm not drawing conclusions from that reply. Go look at the scene."
And then:

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → started at 16:10, still alive at 16:15
```

That's what the line in the judging prompt means: go look at the scene yourself, walk the checklist item by
item, and **a check item with no visible evidence is a fail**.

### "Sent back" means continue, not start over {#打回是接着做不是重头做}

Sending back uses `Step.on_reject`: the next round **`resume`s the very session that was just rejected**, with
the prompt replaced by the judge's feedback (`Verdict.feedback()` gives only "what's missing", not a solution).
So the work already done, the files already read, the dead ends already walked are still in context; it only
has to close the gap.

The difference is written into the step name, visible at a glance in `runs/manifest.json`:

```text
干活            round 1
干活#round2     sent back, continues from there   ← on_reject in effect, resumes the previous round
干活#retry1     plain retry (starts over)         ← the old behavior when there's no on_reject
```

The judge itself is **always a fresh session**: `with_goal`'s gate calls `Runtime.run` directly with no
`resume`; the step name carries the round number (`干活·判定#1`), and suffixed names don't enter cross-process
[lineage](../reference/glossary.md#血缘). When the gate can't get `ctx["_runtime"]` it raises `StepAbort` —
**it does not fake a pass**.

### Skipping and re-deriving {#跳过与重设}

When the goal file already exists and is complete, this step is **skipped** (same as the brief) — restarting
after a [long-horizon](../reference/glossary.md#长程) run crashes shouldn't re-derive conclusions already
reached. To re-derive, delete the file, or set `always_set=True`.

**Exception: you said something else at wake time.** That sentence is appended to the brief, so this step
**re-derives** (`always_set=True`). Without re-deriving, the judge would still be reading the frozen old
checklist, and whether the new thing you added got done wouldn't enter the verdict at all — it would judge
"achieved" against the old checklist. The measured cost of re-deriving is **$0.41 / 3 minutes**.
See [continuity](continuity.md).

### Whether the judge can run commands {#判定者能不能跑命令}

By default it **can't**. `judge()`'s pre-approved list is the ask tools plus `Read` / `Glob` / `Grep`;
`Bash` is added only when `can_run=True`. The tradeoff:

- Give it `Bash` (the CLI's `--judge-can-run`) → it can actually run the acceptance commands, harder verdicts
- But then it can modify the workspace → it might "just fix this quickly" and then pass itself, which makes
  the verdict meaningless

Like the clarifier, it has **no `Write` / `Edit` / `Agent`**. What enforces this is the `whitelist_guard` hook,
**not `allowed_tools`** — the latter is a **pre-approval list, not an exclusive whitelist**, and the model can
still call tools that aren't on it. Two pieces of measured evidence that this still holds: in HT002 the judge
in "设定目标" ran `Bash` **11 times** while `Bash` wasn't on its pre-approval list at all; and in the
**$0.1 probe**, an agent with `allowed_tools=["Read"]` still issued `Write` and `Bash` calls, which were
stopped by the permission layer and path safety
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Today both of those calls get `deny`d on the spot by the hook —
**what stops it is the hook, not the list**.

!!! warning "The judge that sets the goal gets no `Bash` by default"
    `goal_step()` **has no `can_run` parameter**; you have to go through `**spec_kw`:
    `goal_step(ch, goal_path=…, can_run=True)`. Without passing it explicitly it has no `Bash`, and the
    `JUDGE_RULES` line "run `uname -a` first to see where you are" can't be executed — so it may write you
    a checklist that simply can't be verified on this machine. `with_goal()` is a different matter: it has its
    own `can_run` parameter (default `False`).

### Why rounds are capped but questions aren't {#为什么轮数有上限而提问次数没有}

Asking costs almost nothing; a round of work costs real money. So:

- **Unlimited questions** (`max_asks=None`) — ask until it's clear, the clarifier decides for itself
- **Capped rounds** (`rounds=3`) — but the real backstop isn't that number, it's the third outcome,
  "unreachable": the moment it appears the run stops and asks a human, instead of waiting for the rounds
  to run out

## When not to use it {#什么时候不该用它}

**The task is small enough that judging is more verbose than doing.** This layer turns simple problems into
complicated ones, and that's been measured: in HT002's "clone a repo, install and run it on macOS", the
checklist came out at 15 lines, of which 6 verified process compliance and 4 were unverifiable in principle;
that round of judging alone cost **$1.4037 / 37 turns / 0.09h**, and the whole run **$38.2409 / 0.97h**.
When a task only has two or three ways to fail, `--no-goal` is the better deal.

**The goal can't be written as a judgeable checklist.** Exploratory work ("take a look at what's going on in
this repo") has no criterion for "done"; forcing a goal onto it only produces a pretty checklist that can't be
judged. Use `flower once` for that, or `--no-goal`.

**The critical check item can't be verified in this environment.** The judge defaults to `can_run=False` with
only `Read` / `Glob` / `Grep` — **it can't run `file`**, it can only read source. In
[HT001](../cases/ht001.md), the acceptance criterion "runs directly in a macOS terminal" met a run that lived
entirely in a Linux container: **no judge can verify a macOS binary from inside that container**, self-review
or independent. `--judge-can-run` saves part of it (at least `file` becomes runnable); the part it can't save
should be marked `[此环境无法验证:…]` at goal-setting time so it takes the "stop and ask" path, rather than
hoping the judge gets smarter.

**Unattended and interruptions not allowed.** When it judges unreachable and nobody answers, this step
**stops**, and the whole [workflow](../reference/glossary.md#流程) ends there. If what you want is "just finish
the run", use `--no-goal`; if what you want is "stop but don't wait", use `--timeout 0` — the question fails
immediately and the reason goes to disk.

**It doesn't care whether the requirement is right.** The checklist is derived from the brief; if the brief is
wrong, the verdict will precisely verify the wrong thing. That's the [clarify](clarify.md) layer's job.
