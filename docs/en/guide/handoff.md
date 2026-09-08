# Handoff

When the context is nearly full, have **the current session itself** write a [handoff document](../reference/glossary.md#交接书) that a human can read and edit, then start a new session to take over. No compact needed. You can watch the whole thing happen in the terminal, and the document lands on disk — edit it whenever you like, because the session taking over reads exactly that file.

!!! note "Handoff is not continuity"
    [Handoff](../reference/glossary.md#换代) swaps in a new [session](../reference/glossary.md#会话) **inside the same run**;
    [continuity](../reference/glossary.md#接续) picks up the previous [run](../reference/glossary.md#运行) **across processes**,
    see [Continuity](continuity.md).

    The two mesh automatically, no extra wiring: [lineage](../reference/glossary.md#血缘) records the **last**
    `session_id` of that step, and that is the successor — so the next wake attaches to the successor, not to the generation that was burned.

## What problem it solves {#解决什么问题}

The SDK's built-in auto-compact fires at **window −33k** (measured: with a window of `200000` the threshold is `167000`; the compaction algorithm itself lives in the harness binary and cannot be changed — all you can change is whether it fires), and what it does is **summarize the history into a paragraph**. It runs against the grain of everything else in this framework:

| | When it decides | What it leaves behind |
|---|---|---|
| `spill_guard` | the moment the tool returns | large results [spill](../reference/glossary.md#落盘) to disk, one line of path stays in context |
| Frozen artifacts (brief / goal) | at the end of that step | one document; the next step reads only it |
| **auto-compact** | **only looks back once the context is full** | **a summary the model wrote itself** |

What flower does from end to end is **decide on the spot what should be kept**. [Compact](../reference/glossary.md#压缩) is the one place where it is "patching things up afterwards", and its product has four defects:

- **Model-generated** — what goes into the summary is decided by the model's judgment at that moment; you had no part in it
- **Unreadable** — it is written for the next round's model, not for a human
- **Uneditable** — it lives inside the harness; there is no file for you to open
- **You don't know what was lost** — you can neither see what was dropped nor say "not that one" before it goes

Handoff pulls this back into the same practice: **another frozen artifact**, the same shape as the brief and the goal — structured, written to disk, **you can open it, change a line, and let it keep running**. And this is exactly what this project itself does — the `HANDOFF.md` at the repo root is the same kind of thing, written by a human.

## How to use it (minimal code) {#怎么用最小代码}

The command line ships with handoff on by default:

```bash
flower                       # handoff is on by default
flower --window 200000       # only needed when the guess is wrong (default is 1,000,000)
flower --no-handoff          # off -- falls back to the SDK's auto-compact
```

In your own code, handoff is controlled by `Runtime(handoff=…)`, defaulting to `True`:

```python
from flower import HandoffPolicy, Runtime

# default: HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# set the window explicitly (this is the first thing to tune when switching gateway or model)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # off, falls back to auto-compact
```

`Runtime.__init__` is entirely keyword-only, and `workspace` is required. `handoff` takes a `HandoffPolicy` instance or a `bool`; a `bool` is equivalent to `HandoffPolicy(enabled=…)`.

!!! warning "Handoff on = auto-compact forcibly off"
    `Runtime(handoff=True)` is the **default**, and when assembling every attempt it does this: as long as
    `handoff.enabled` and `spec.compact is None`, it replaces the spec with
    `CompactPolicy(mode="no_summary")` — that is, it injects **`DISABLE_AUTO_COMPACT=1`** into the subprocess.

    The reason is that if both mechanisms run at once, you can no longer say who caused a given drop in context. The price is **no safety net**: the turn that writes the handoff cannot stop when it fails, and cannot pretend nothing happened and coast into the hard limit, so there must be a degraded path (see below).

    To keep auto-compact as a backstop you must **explicitly** pass `AgentSpec(compact=CompactPolicy(mode="auto"))` — if the spec supplies its own, it is respected and not overridden. Note that this **silently wins** over the assumptions on the handoff side.

## What it actually does {#它实际做了什么}

### When it fires: two routes into handoff {#触发时机两条路进换代}

**One: the watermark reaches the threshold.** The criterion is `_handoff_due`: `handoff.enabled`, **not in the turn that writes the handoff**, `_ctx >= handoff.at`, and this step has already obtained a `session_id`. `_ctx` is the context size the **main thread** actually saw on its last turn — only the [main thread](../reference/glossary.md#主线程); a [subagent](../reference/glossary.md#subagent)'s context is its own transcript's business, it dissolves when the subagent finishes, and it should not force the main thread into a handoff.

At `warn_at` an approach warning is emitted once, once per generation, so it does not flood the screen.

**Two: the API says outright that it doesn't fit.** See the `is_overflow` section below.

Neither route is **bound by `max_attempts`**, and neither **consumes retry budget** (internally `attempt -= 1`) — a handoff is not a failure.

### The handoff document: five sections, only two required {#交接书五段必填只有两段}

Each section blocks one class of mistake the person taking over would make:

| Section | Field | What it blocks |
|---|---|---|
| What's being done now | `doing` **required** | not knowing where you stand |
| Already decided | `decided` | re-litigating what has already been settled (must include the **why**) |
| Dead ends | `deadends` | **the most expensive section** — see below |
| Next step | `next` **required** | burning half an hour deciding what to do |
| The scene | `scene` | **paths** to key files and outputs. Pointers, not content |

`Handoff.missing()` only checks `REQUIRED = ("doing", "next")`, and `complete()` is its negation.
**Hard-requiring "dead ends" to be non-empty would force fabrication** — at the start of a task it should legitimately be empty.
And the `complete()` verdict has consequences: if a required section is missing, the whole handoff is **replaced by a mechanically assembled degraded artifact** (see below), which is far worse than a real handoff missing one section. So the other three are optional — useful when written, and their absence does not block the handoff.

In `to_markdown()` an empty section is written as `(空)`; the header of `prompt_block()` tells the successor explicitly that it is taking over, so it doesn't turn around and ask a human for background. The `step` field is used only in the document header and takes no part in parsing.

#### Why "dead ends" is the most expensive {#走不通的路为什么最贵}

Because it is **what the person taking over pays the most to rediscover**, and what the writer is most likely to omit.

Workers have a systematic optimism bias ([Goal guard](goal.md) argues the same point): they write down what they got done and forget to write down what they tried that didn't work. And the latter is what is genuinely expensive — in [HT002](../cases/ht002.md) an hour was spent going in circles on a compilation problem, and had the conclusion of that hour not been written down, the successor would have gone around exactly the same circle.

That is why `HANDOFF_PROMPT` devotes a paragraph to this specifically, with that measured cost attached.

### What a real handoff document looks like {#长什么样}

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

**Fully automatic, it does not stop and wait for you** — a long-horizon run should not stall because a human went to lunch.

The event is `Event("handoff")`, and `payload["phase"]` has **three** values: `near` (approaching), `writing` (in progress — writing a handoff takes a dozen-odd seconds, and without this event the UI would look frozen), and `done` (handoff complete). The `done` payload also carries `context`, `window`, `degraded`, `path` and `sections`.

### How the thresholds are computed {#阈值怎么算}

```python
at      = max(10_000, window - headroom)   # handoff line, floored at 10k
warn_at = max(1_000, at - 20_000)          # approach-warning line
```

The 10k floor on `at` is mandatory — any lower and it cannot even write the handoff.

The scale below uses `--window 200000` as the example; the **default window is 1,000,000**:

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                       warn  handoff     hard cap
```

When `window` is not supplied, `default_window()` decides from the **model name string**, looking only at the two environment variables `ANTHROPIC_MODEL` and `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Model name | Resolves to |
|---|---|
| name contains a standalone `1m` token | `1_000_000` |
| name contains `haiku` | `200_000` |
| everything else, **and when neither variable is set** | `1_000_000` |

Note the order: `1m` matches first, so `claude-haiku[1m]` resolves to 1,000,000, not 200,000.

Why `headroom` is `50_000`: auto-compact fires at window −33k, and the handoff must get ahead of it; and "writing the handoff" itself costs another turn. 50k satisfies both.

**`--window` is the first switch to reach for when changing model or gateway.** The SDK side gives no reliable window size, so it can only guess from the name. If the real window is larger → handoffs come early (wasteful, not wrong); smaller → too late, and you must adjust. A measured case worth mentioning: the gateway on the development machine is configured with `claude-opus-5[1m]`. Counting it as 200,000 would mean a new generation every 150,000, when it can actually run to 950,000 — **5× off**, and long-horizon work gets chopped to pieces.

`flower -v` shows the credential configuration in effect before the run starts (endpoint, model name, token masked to the first 4 characters).

### `is_overflow`: turning a hard error into an on-the-spot handoff {#is_overflow把硬错变成当场换代}

This is the precondition for **daring to default `default_window()` to 1,000,000**.

If the window is guessed too large, the threshold is never reached, and auto-compact is off — so you slam straight into the API. `is_overflow(*texts)` recognizes that signal: `prompt is too long`, `context length exceeded`, `maximum context length`, `too many total text bytes`, `input length and max_tokens exceed`, and so on.

Once recognized, it takes **the same handoff path**, except that this generation's handoff is necessarily degraded — that session can no longer run "one more turn to write a handoff", so it uses the mechanically assembled degraded artifact, swaps in a new session as usual, and keeps working: **this step does not fail**.

So the cost of guessing too large drops from "this step fails" to "this generation's handoff is degraded".

`is_overflow` is a **module-level function**, not a method on `Handoff`, and it is variadic.

### When the handoff can't be written: degrade, don't stop {#交接写不出来时降级不是停下}

The turn that writes the handoff can also fail — the network drops, the model glitches, the parse comes back missing a required section. Because auto-compact is already off, there is **no backstop**, and stopping here means hitting the window.

What it does: mechanically assemble a **partial handoff** from what is already known, tag `doing` with `[降级:交接没写成]` (the constant `DEGRADED`), stuff the first **1200** characters of the original task into `scene`, and hand off anyway. The successor is told explicitly that what it received is incomplete and that it should go look at the scene itself. At the same time `StepResult.errors` gains an entry "交接降级(…)", and the reason is findable in `manifest.json`.

The corresponding module-level function is `degraded(step, prompt, *, why="")`; `Handoff.degraded` is a read-only property that checks whether `doing` carries that marker.

> **A partial handoff beats hitting the window.**

The turn that writes the handoff has two more deliberate arrangements: it runs with `max_budget_usd=None` — **the handoff must get written, it cannot stall on budget**; and `on_event=None` — this turn does not push to the UI.

### One landmine: the handoff turn must be exempt from the threshold {#一颗地雷写交接那一轮必须豁免阈值}

The handoff is written **after the line has been crossed** — at that moment the watermark is by definition still above the threshold. Without the exemption, the first message of the handoff turn would again decide "time to hand off", so it gets interrupted before writing a single word, **every generation produces a degraded artifact**, and everything looks fine (the degraded path works well).

This was hit for real: the first live run of `tests/handoff_live.py` produced **two generations of handoffs, both degraded**. The offline tests did not catch it — they replaced `_attempt` wholesale, so the fake never exercised this criterion. The criterion is now lifted into `Runtime._handoff_due()`, and offline tests verify it directly.

### One gate against runaway {#一道防跑飞的闸}

`max_generations=8`.

!!! danger "A `window` set too small burns money in an endless handoff loop"
    The danger: **the threshold sits below that role's startup floor** (measured at about 34k for the [coordinator](../reference/glossary.md#协调者), consumed by the system prompt plus the [workbench](../reference/glossary.md#工作台) index alone), so every new session crosses the line the moment it opens its mouth → write handoff, hand off, cross again, **forever**. And handoffs deliberately don't consume retry budget, so the only gate is `max_generations=8`.

    A normal long run never reaches 8; if you do hit it, it is almost certainly a `window` set too small — the error message at the cap says exactly that ("阈值很可能低于这个角色的启动地板,把 window 调大,或 `--no-handoff`").

### One full handoff, end to end {#一次换代的完整过程}

```text
work (session A)
  |  main-thread context crosses the threshold  <- main thread only. A subagent's context is its own
  |                                               transcript's business; it dissolves when done and
  |                                               shouldn't force the main session into a handoff
  |- break at a message boundary                <- same idea as a Ctrl-C interrupt: cut cleanly, don't
  |                                               tear state (same cost: in-flight subagents are lost.
  |                                               The 50k headroom exists for this)
  |- run one more turn in the same session: write the handoff
  |     why it writes it itself -- only it has that context. Anyone else would have to read it all
  |     first, which defeats the point
  |- freeze to <workbench>/notes/交接-<step name>.md, previous generation moved to notes/archive/交接/
  |- new session (resume=None, fork=False), prompt = the handoff's prompt_block()
work (session B) continues
```

`HANDOFF_PROMPT` is the prompt that makes the current session write the handoff; it contains two placeholders, `{used}` and `{window}`.
**It is not a new role** — only the current session has that context.

### A handoff is not a retry — how the books are kept {#换代不算重试账怎么记}

| Field | What changes on handoff |
|---|---|
| `attempts` | **does not increase** — it counts failed attempts |
| `retired[]` | the session_ids burned by this step, recorded here **in order** |
| `session_id` | always **the last successor**, never a burned one |
| `context` | the context size the main thread actually saw on the last turn |
| `cost_usd` / `num_turns` | **accumulate** across retries and handoffs |

All of these go into `manifest.json`, so afterwards you can fully reconstruct "how many generations this step burned and what each one cost".

### Where the handoff lands {#交接落在哪}

`<workbench>/notes/交接-<step name with illegal characters stripped>.md`; an existing previous generation is moved to
`notes/archive/交接/<step name>-<timestamp>.md`.

**Without a workbench nothing is written to disk** — `_handoff_path` returns `None`, the document is still passed to the successor via the prompt, and the handoff proceeds as usual; you simply **cannot go back and find that file afterwards**. To be able to, turn the workbench on (`Runtime(workbench=True)`, or have the [workflow](../reference/glossary.md#流程) mount one itself).

## When not to use it {#什么时候不该用它}

- **You genuinely want compact.** `flower --no-handoff`, or `Runtime(handoff=False)`. Handoff turns auto-compact off as a side effect; if you don't want that side effect, don't turn it on.
- **You want both running.** Explicitly passing `AgentSpec(compact=CompactPolicy(mode="auto"))` preserves auto-compact, but after that you can no longer say who caused a given drop in context, and debugging gets harder. Trust the handoff or trust compact, not both.
- **Short tasks, single-turn work.** The handoff will never fire, so configuring it is pointless — but remember that `Runtime` still defaults to `handoff=True` and therefore still turns auto-compact off.
- **No workbench, but you expect to read the handoff later.** Turn the workbench on first, otherwise the document only ever existed inside that one run's context.
- **Starting a long run before `window` is matched.** When the real window is smaller than the default, the first few generations' handoffs will all be degraded artifacts — and degraded artifacts are exactly the least useful kind of handoff. Match it with `--window` first, or do a short run and check the model name under `-v`.
- **Treating handoff as the whole of context governance.** It is the last line. The layers that trim on the spot (spill, [trim](../reference/glossary.md#裁剪), [prune](../reference/glossary.md#剪除)) are cheaper — see [Context economics](context.md).

## Symptom table: which knob to turn {#旋钮}

| Symptom | Which knob |
|---|---|
| Handoffs too frequent, work constantly interrupted | set `--window` to the model's real window (`-v` shows the model name in effect) |
| Handoff right at the start, with a "startup floor" message | same as above, `window` is set too small |
| Handoffs are always degraded | check `errors` in `runs/manifest.json`, the degradation reason is written there |
| The successor keeps redoing what the previous generation did | the "dead ends" section of the handoff is too thin. You can edit that file directly |
| Want to read the handoff afterwards but can't find the file | no workbench. The handoff was never written to disk, only passed through the prompt |
| You just want compact | `--no-handoff` |

## What to read next {#相关}

- [Continuity](continuity.md) — picking up the previous run across processes; the same thing as this page, from the other direction
- [Context economics](context.md) — the layers that trim on the spot
- [Goal guard](goal.md) — the argument that "workers have a systematic optimism bias"
- [Python API](../reference/api.md) — `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [Command line](../reference/cli.md) — `--window`, `--no-handoff`
- Source: [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
