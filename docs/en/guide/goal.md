# Goal guard

Whether something is "done" is not for the worker to say. The [judge](../reference/glossary.md#判定者) is a role that only sets the goal,
only rules on it, and never does the work itself: before the run starts it turns the [brief](../reference/glossary.md#需求确认书) into a decidable
checklist, and after every round of work it **rules once, independently**, producing a [verdict](../reference/glossary.md#判定) —
achieved means move on, not yet means bounce it back with "here's what's missing" and keep going,
unreachable means stop and ask a human.

## What problem it solves {#解决什么问题}

[Clarify](clarify.md) blocks **"it built the wrong thing"**. This layer blocks a different class:
**"it isn't actually done, but it says it is"**. The two must stay separate, because they fail differently:

| | What the failure looks like | When it surfaces |
|---|---|---|
| Wrong requirement | Every artifact is built against the wrong requirement | Hours later, all output wasted |
| Wrong completeness judgment | Half the tests run, one spot fixed and three missed, "should be fine" | When you go to use it yourself |

Why the second class can't be left to the worker itself: **it has a systematic optimism bias**.
That isn't dishonesty — it can't see its own blind spots. It knows what it did; it doesn't know what it missed.

So the verdict goes to a role that **did none of the work and runs in its own [session](../reference/glossary.md#会话)**.
All it sees is the goal and the actual state, not how many times the worker tried or how hard it worked, so it won't make excuses for it.
Same reasoning as running the clarifier in a separate session.

## How to use it (minimum code) {#怎么用最小代码}

### Zero code: command line {#零代码命令行}

```bash
flower                      # 默认就带目标看守
flower --no-goal            # 关掉:干活跑完就算完
flower --rounds 5           # 最多五轮活(默认 3)
flower --judge-can-run      # 让判定者能跑命令(判定更硬)
```

### Wiring it yourself {#自己接线}

Two functions each own half; don't mix them up: `goal_step()` **sets the goal** (a standalone step),
`with_goal()` is the **verdict loop** (it wraps a step that does work).

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step, goal_step, with_goal

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # 默认不限提问次数
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
| `brief_key` | `"确认需求"` | Which key of `ctx` to read the brief from. **If it's missing you only get `"(没有确认书)"`** |
| `name` | `"设定目标"` | Step name, and also the key name in `ctx` |
| `spec` / `instructions` | `None` / `""` | Bring your own `AgentSpec`, or append domain instructions to the judge |
| `always_set` | `False` | `True` = re-set every time |
| `on_fail` / `retries` | `"stop"` / `0` | Same as `Step` |
| `**spec_kw` | — | Passed through to `judge()`: `can_run` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`with_goal()` wraps a working step into a loop with a verdict:

```python
with_goal(step, channel, *, goal_path, spec=None, rounds=3,
          instructions="", can_run=False, name=None, **spec_kw)
```

**`rounds` is the total number of rounds, not extra rounds** — it lands as `retries = max(0, rounds - 1)`,
so `rounds=3` means at most three rounds of work, and `rounds=1` means "run once, rule once, fail if it doesn't pass".
For the full signature and field semantics see the [Python API](../reference/api.md).

Three extra keys appear in `ctx`:

```python
ctx[GOAL_KEY]     # "_goal" —— Goal 对象;ctx["设定目标"] 是它的 markdown
ctx[VERDICT_KEY]  # "_verdict" —— 最近一次 Verdict,给 UI 用
ctx[ROUND_KEY]    # "_goal_rounds" —— 跑了几轮
```

The judge is dispatched through `ctx["_runtime"]` — `Workflow.run` puts both the runtime and the event sink into `ctx`,
so `gate` can spin up an agent itself while the ruling still streams to your UI
(otherwise the interface goes dark for a dozen-odd seconds and looks stuck).

When it isn't behaving, reach for these knobs first:

| Symptom | Which knob |
|---|---|
| Verdict too lax — says achieved when it isn't | `--judge-can-run` so it actually runs things; or add domain criteria via `instructions` |
| Verdict too strict — keeps bouncing back | Check whether the checklist in `目标.md` is pitched higher than the requirement itself. **Edit that file** |
| Spinning round after round | The judge should have said "unreachable" but said "not yet". Add instructions explaining what counts as impossible |
| Too expensive | `--rounds 1`, or `--no-goal` to turn it off entirely |
| Don't want to be interrupted | `--timeout 0`: on unreachable it doesn't ask, it just stops (the reason stays on disk) |

## What it actually does {#它实际做了什么}

### What a goal looks like {#目标长什么样}

`goal_step` reads the brief, emits two sections, and freezes them into `.flower/notes/目标.md`:

```markdown
# 目标
让 conv.py 能把 md 转成 html。

# 判定清单
- 跑 `python conv.py a.md` 产出 a.html
- 输出里含 `<h1>`
- 列表被转成 `<ul><li>`
```

**The checklist is the entire value of this layer.** "Implementation complete" can't be ruled on; "run this, see that" can.
The checklist comes from the brief's "acceptance criteria", but each item has to be rewritten into a form verifiable on the spot — the judge fills in the vague ones.
Both sections must be non-empty (`statement` says something, `checks` is non-empty) for the goal to count as complete; otherwise this step doesn't pass.

### The length of the checklist is decided by "how many ways it can fail" {#清单的长度由有多少种失败方式决定}

Not by how rigorous the judge is. For a task like `git clone && make && ./app`, **three to five items are enough**:
it builds, it runs, it works.

**Measured failure** ([HT002](../cases/ht002.md)): a "get this repo installed and running" task got a **15**-item checklist,
of which only **5** verified "does the thing work", **6** verified "was the process followed"
(including checking the mtime of `~/.zshrc` and whether the `.flower/` directory had been modified — that's the framework's own directory),
and **4** were unverifiable in principle.

#### A boundary is not a check item {#边界不是判定项}

This was the main cause that time:

| | What it constrains | How it's honored |
|---|---|---|
| **Boundary** | **How you work** ("install only inside the project directory", "don't touch business code") | By **not crossing it**, not by proving it afterwards |
| **Check item** | **What you hand over** ("does it run", "is the result right") | By verification on the spot |

Writing "never ran `brew install`" as a check item means every added boundary adds a check —
and boundaries are exactly what the clarify stage encourages you to fill in. If you really need an accounting, one sentence covers it; don't split it into six items.

### Unverifiable items get flagged when the goal is set {#验不了的条目设目标时就会喊}

For items marked `[此环境无法验证:原因]`, `goal_step` fires a warning **the moment the goal is frozen**:

```text
  # 目标里有 4/15 条在这个环境里验不了 —— 判定时它们必然过不去,会停下来问你。
    现在改 .flower/notes/目标.md 还来得及:
      · 界面截图并实际看图 [此环境无法验证:屏幕录制未授权]
      · ...
```

**Why up front**: the fate of these items is sealed the moment the goal is set — they can never pass at verdict time.
HT002 spent **$35.90 on work + $1.40 on the verdict** before discovering this —
moving the discovery up to the goal-setting step drops the cost of the same information from **$37** to **$0**.

It warns, it doesn't block: you can choose to run anyway (HT002 ended up choosing "accept this result").
`Goal.unverifiable` is that list, and the event payload carries structured data for the UI.

### Three verdicts, not two {#三个结论不是两个}

```text
干活 ──> 判定 ──达成────> 往下走
              ├─未达成──> 打回,带上“差在哪”,续跑同一个会话接着做
              └─无法达成─> 停下来问人:接受 / 改目标 / 你判断错了
```

The third verdict is the key one. With only "achieved / not yet", a goal that is **actually impossible** makes the coordinator
spin round after round until the budget is gone — that's the real money burner. So the judge is explicitly told:
only "another round won't help" counts as unreachable (a required external condition is missing, the requirement contradicts itself, a check item simply can't be verified);
"not finished yet" uses not yet.

On unreachable, the framework stops and asks:

```text
  ? 目标被判为**无法达成**:缺少 X 依赖,判定项 2 无法验证
    怎么办?
     1) 接受这个结果,就这样往下走
     2) 修改目标
     3) 你判断错了,继续做
```

- **Accept** → this step counts as passed, the reason stays in the record
- **Modify the goal** → you're asked what the new goal is, it's **appended** after the original goal (so you can see what changed), and another round runs
- **You judged wrong** (and any free-form answer you type) → your statement is sent back with the bounce, and another round runs

**If nobody answers, it stops** rather than spinning on — deliberately. Ruled impossible and nobody to ask,
continuing just burns money round after round, and that's exactly what to avoid. On stopping it raises `StepAbort`, the reason goes into
`ctx["_aborted"]`, the goal file and `runs/manifest.json` are both there, and you decide when you're back.

!!! warning ""Not done" and "can't be verified here" are two different verdicts"
    `Verdict` has three values: `ACHIEVED` / `NOT_YET` / `UNREACHABLE`.
    **`UNREACHABLE` must never be treated as a pass** — it takes the "stop and ask a human" path, not the "one more round" path.
    Anything the judge writes as "无法验证 / 没法验证 / 验证不了 / 无法判定 / unverifiable" maps to
    `UNREACHABLE` **in all cases**. Treating "can't verify here" as "achieved" means closing out the work on a "looks like it should work";
    treating it as "not yet" means making it redo, round after round, something that was never verifiable in the first place.

### An ambiguous verdict = not yet {#判定含糊--未达成}

`Verdict.parse` recognition order: first take the "结论 / 判定" section by heading; if there is no heading section,
a whole body of `1` / `true` counts as achieved and `0` / `false` as not yet (when the judge is told to "return only 0/1",
it may well return literally a single digit); failing that, look for keywords in the conclusion text (longer words first); finally, look for an isolated `1` / `0`.

**When nothing matches, `state` is left empty, `ok` is `False`, and the framework treats it as not yet.** This is deliberate:
"can't tell" and "done" are two different things; ambiguity always counts as not yet, plus a default reason
("判定者没给出明确结论,按未达成处理").

### It rules on the artifact, not the source {#判的是产出物不是源码}

!!! warning "A verdict that only reads source can't rule on a deliverable"
    In [HT001](../cases/ht001.md), the acceptance criterion read "compile a standalone executable that runs directly in the macOS
    terminal", and the verdict only read `Makefile:25-38`, saw there was indeed a Darwin branch, and ruled **pass** —
    the delivered artifact was `ELF 64-bit LSB pie executable, ARM aarch64, GNU/Linux`.

    **The goal guard is not what got it wrong**: that run didn't have this mechanism yet; the thing ruling on that item was an
    independent auditor the coordinator dispatched ad hoc. But the goal guard would have missed it too — the judge defaults to `can_run=False`, holding only
    `Read` / `Glob` / `Grep`, so it **can't run `file`**, and would likewise have had to read the `Makefile` and would likewise have
    seen the Darwin branch and ruled achieved. The crux of that failure isn't "who rules", it's "on what evidence".

    That lesson was written into `JUDGE_RULES`: rule on the **artifact**, and don't accept inferences like "the source has a macOS branch so
    it should run".

[HT002](../cases/ht002.md) is the run where `judge_can_run` was on and the judge actually ran `file` / `lsof`,
which is how it dodged this pit — its first line was "I won't draw conclusions from that reply. Go look at the actual state." And then:

```text
file cppide        → Mach-O 64-bit executable arm64
lsof -p 96040      → 起于 16:10,16:15 仍活着
```

The line in the verdict prompt means the same thing: go look at the actual state yourself, walk the checklist item by item, and **a check item with no visible evidence
is a fail**.

### A "bounce" resumes the work, it doesn't restart it {#打回是接着做不是重头做}

The bounce uses `Step.on_reject`: the next round **`resume`s the session that was just rejected**, with the prompt replaced by the verdict feedback
(`Verdict.feedback()` gives only "what's missing", not a solution). So the work already done, the files already read, the dead ends already walked
are all still in context; it only has to close the gap.

The distinction is written into the step name, visible at a glance in `runs/manifest.json`:

```text
干活            第一轮
干活#round2     被打回后接着做      ← on_reject 生效,resume 上一轮
干活#retry1     普通重试(重头跑)    ← 没有 on_reject 时的老行为
```

The judge itself is **always a fresh session**: `with_goal`'s gate calls `Runtime.run` directly and passes no `resume`;
the step name carries the round (`干活·判定#1`), and suffixed names don't enter cross-process [lineage](../reference/glossary.md#血缘).
If the gate can't get `ctx["_runtime"]` it raises `StepAbort` — it **doesn't fake a pass**.

### Skipping and re-setting {#跳过与重设}

When the goal file already exists and is complete, this step is **skipped** (same as the brief) — when a [long-horizon](../reference/glossary.md#长程)
run crashes and restarts, the earlier conclusions shouldn't be recomputed. To re-set it, delete that file, or use `always_set=True`.

**Exception: you said something more at wake time.** That sentence is appended to the brief, so this step **re-derives**
(`always_set=True`). Without re-deriving, the judge is still reading the frozen old checklist, and whether the thing you just added got done
never enters the verdict at all — it will rule "achieved" against the old checklist. The measured cost of re-deriving is **$0.41 / 3 minutes**.
See [continuity](continuity.md).

### Can the judge run commands {#判定者能不能跑命令}

By default **no**. `judge()`'s pre-approved list is the ask tools plus `Read` / `Glob` / `Grep`;
`Bash` is only added when `can_run=True`. The tradeoff:

- Give it `Bash` (the CLI's `--judge-can-run`) → it can actually run the acceptance commands, and the verdict is harder
- But then it can modify the workspace → it might "just fix this quickly" and then rule pass, which makes the verdict meaningless

Like the clarifier, it has **no `Write` / `Edit` / `Agent`**. What enforces this is the `whitelist_guard` hook,
**not `allowed_tools`** — the latter is a **pre-approval list, not an exclusive whitelist**, and the model can still call tools that aren't on it.
Two pieces of measured evidence that this still holds: in HT002 the "设定目标" judge ran `Bash` **11 times**
while `Bash` wasn't on its pre-approval list at all; and in the **$0.1 probe**,
an agent with `allowed_tools=["Read"]` still emitted `Write` and `Bash` calls, which were stopped by the permission layer and path safety
(`"requested permissions to write ... but you haven't granted it yet"` /
`"Output redirection was blocked..."`). Today both calls get `deny`d on the spot by the hook —
**it's the hook that stops it, not the list**.

!!! warning "The judge that sets the goal has no `Bash` by default"
    `goal_step()` **has no `can_run` parameter**; you have to go through `**spec_kw`: `goal_step(ch, goal_path=…, can_run=True)`.
    Without passing it explicitly it has no `Bash`, and the `JUDGE_RULES` line "run `uname -a` first to see where you are" can't execute —
    so it may write you a checklist that simply can't be verified on this machine. `with_goal()` is a different matter:
    it has its own `can_run` parameter (default `False`).

### Why rounds are capped but asks aren't {#为什么轮数有上限而提问次数没有}

Asking costs almost nothing; a round of work costs real money. So:

- **Asks are unlimited** (`max_asks=None`) — ask until it's clear, judged by the clarifier itself
- **Rounds are capped** (`rounds=3`) — but the real backstop isn't that number, it's the third verdict, "unreachable":
  the moment it appears it stops and asks a human, instead of waiting for rounds to run out

## When you shouldn't use it {#什么时候不该用它}

**The task is so small that ruling on it is wordier than doing it.** This layer will over-complicate a simple problem, and that's been measured:
in HT002's "clone a repo, install it on macOS and get it running", the checklist came out at 15 items,
6 of which verified process compliance and 4 of which were unverifiable in principle; that round of ruling alone cost **$1.4037 / 37 turns / 0.09h**,
against **$38.2409 / 0.97h** for the whole run. When a task only has two or three ways to fail, `--no-goal` is the better deal.

**The goal can't be written as a decidable checklist.** Exploratory work ("go see roughly what this repo is about") has no criterion for "done";
forcing a goal onto it just yields a pretty checklist nobody can rule on. Use `flower once` for that, or `--no-goal`.

**The one check item that matters can't be verified in this environment.** The judge defaults to `can_run=False`, with only
`Read` / `Glob` / `Grep` — **it can't run `file`**, only read source. In [HT001](../cases/ht001.md),
the acceptance criterion "runs directly in the macOS terminal" was up against a run that lived entirely in a Linux container:
**no judge whatsoever can verify a macOS binary from inside that container**, self-review or independent.
`--judge-can-run` rescues part of it (at least `file` becomes runnable); the part it can't rescue should be marked
`[此环境无法验证:…]` at goal-setting time so it takes the "stop and ask a human" path, rather than hoping the judge gets smarter.

**Unattended and interruption not allowed.** Ruled unreachable with nobody answering, this step **stops**, and the whole [workflow](../reference/glossary.md#流程) ends there.
If what you want is "just finish the run", use `--no-goal`; if what you want is "stop but don't wait", use `--timeout 0` —
the ask fails immediately and the reason goes to disk.

**It doesn't care whether the requirement is right.** The checklist is derived from the brief; if the brief is wrong, the verdict will only verify a wrong thing precisely.
That's [clarify](clarify.md)'s layer.
