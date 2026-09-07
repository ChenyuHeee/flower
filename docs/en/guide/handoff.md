# Handoff

When the context is nearly full, have **the current session itself** write a [handoff document](../reference/glossary.md#交接书) that a human can read and edit,
then start a new session to take over. No compact involved. You can watch the whole thing in the terminal, and the document lands on disk —
edit it whenever you like; that file is exactly what the taking-over session reads.

!!! note "Handoff is not continuity"
    [Handoff](../reference/glossary.md#换代) swaps in a new [session](../reference/glossary.md#会话) **inside the same run**;
    [continuity](../reference/glossary.md#接续) picks up the previous [run](../reference/glossary.md#运行) **across processes**,
    see [Continuity](continuity.md).

    The two mesh automatically, no extra wiring needed: [lineage](../reference/glossary.md#血缘) records the **last**
    `session_id` of that step, and that is the successor — so the next wake attaches to the successor, not to the generation that was burned.

## What problem it solves

The SDK's built-in auto-compact fires at **window − 33k** (measured: with a `200000` window the threshold is `167000`;
the compaction algorithm itself lives in the harness binary and can't be changed — all you can change is whether it fires),
and what it does is **summarize history into a paragraph**.
That is at odds with the rest of this framework:

| | When it decides | What it leaves behind |
|---|---|---|
| `spill_guard` | The moment a tool returns | Large results [spill](../reference/glossary.md#落盘) to disk, one line of path stays in context |
| Frozen artifacts (brief / goal) | At the end of that step | A document; the next step reads only it |
| **auto-compact** | **Only looks back once the context is full** | **A summary the model wrote itself** |

What flower does end to end is **decide on the spot what should be kept**. [Compact](../reference/glossary.md#压缩) is the one place that is "after-the-fact repair,"
and its output has four defects:

- **Model-generated** — what goes into the summary is decided by the model's judgment at that moment; you had no part in it
- **Unreadable** — it is written for the next round's model, not for a human
- **Uneditable** — it lives inside the harness; there is no file for you to open
- **You don't know what was lost** — you can't see what was dropped, and you can't say "not that one" before it gets dropped

Handoff pulls this back into the same practice: **one more frozen artifact**, the same shape as the brief and the goal —
structured, written to disk, **something you can open, change a line in, and let it keep running**. And this is exactly what this project does for itself —
`HANDOFF.md` at the repo root is the same kind of thing, written by a human.

## How to use it (minimal code)

The command line ships with handoff on by default:

```bash
flower                       # 默认就带换代
flower --window 200000       # 判错了才需要给(默认 100 万)
flower --no-handoff          # 关掉 —— 退回 SDK 自带的 auto-compact
```

In your own code, handoff is controlled by `Runtime(handoff=…)`, default `True`:

```python
from flower import HandoffPolicy, Runtime

# 默认:HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# 显式配窗口(换网关、换模型时最该调的就是这个)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # 关掉,退回 auto-compact
```

`Runtime.__init__` is entirely keyword-only, and `workspace` is required. `handoff` takes a `HandoffPolicy` instance or a
`bool`; passing a `bool` is equivalent to `HandoffPolicy(enabled=…)`.

!!! warning "Handoff on = auto-compact forcibly off"
    `Runtime(handoff=True)` is the **default**, and while assembling every attempt it does this: whenever
    `handoff.enabled` and `spec.compact is None`, it replaces the spec with
    `CompactPolicy(mode="no_summary")` — that is, it injects **`DISABLE_AUTO_COMPACT=1`** into the subprocess.

    The reason: if both mechanisms run at once, you can no longer tell who caused any given context drop. The price is **no safety net**:
    when the round that writes the handoff fails, you can't stop, and you can't pretend nothing happened and coast to the hard limit — so a degraded path is mandatory (see below).

    To keep auto-compact as a fallback you must **explicitly** pass `AgentSpec(compact=CompactPolicy(mode="auto"))` —
    if the spec supplies its own, that is respected and not overridden. Note that this **silently wins** over the assumptions on the handoff side.

## What it actually does

### Trigger points: two roads into handoff

**One: the water level reaches the threshold.** The criterion is `_handoff_due`: `handoff.enabled`, **not currently in the round that writes the handoff**,
`_ctx >= handoff.at`, and this step has already obtained a `session_id`. `_ctx` is the context size the **main thread** actually saw on its last round —
only the [main thread](../reference/glossary.md#主线程) counts; a [subagent](../reference/glossary.md#subagent)'s
context is a matter for its own transcript, it dissolves when it finishes, and it should not force the main thread to hand off.

At `warn_at` an approaching-threshold notice fires once, once per generation, so it doesn't flood the screen.

**Two: the API says outright "it doesn't fit."** See the `is_overflow` section below.

Neither road is **bound by `max_attempts`**, and neither **consumes retry budget** (internally `attempt -= 1`) —
a handoff is not a failure.

### The handoff document: five sections, only two required

Each section blocks one class of mistake the successor would make:

| Section | Field | What it blocks |
|---|---|---|
| What's being done now | `doing` **required** | Not knowing where you stand |
| Already decided | `decided` | Re-litigating settled matters (must include **why**) |
| Dead ends | `deadends` | **The most expensive section** — see below |
| Next step | `next` **required** | Spending the first half hour deciding what to do |
| Scene | `scene` | **Paths** to key files and outputs. Pointers, not contents |

`Handoff.missing()` checks only `REQUIRED = ("doing", "next")`, and `complete()` is its negation.
**Hard-requiring a non-empty "dead ends" would force fabrication** — at the start of a task it is supposed to be empty.
And the `complete()` verdict has consequences: if a required section is missing, the whole handoff is **replaced by the mechanically assembled degraded artifact**
(see below), which is far worse than a real handoff missing one section. So the other three are optional — useful when written, not a blocker when absent.

`to_markdown()` writes `(空)` for empty sections; the header of `prompt_block()` tells the successor plainly "you are taking over,"
to keep it from turning around and asking a human for background. The `step` field is used only in the document header and takes no part in parsing.

#### Why "dead ends" is the most expensive

Because it is **what costs the successor the most to rediscover**, and it is the section the writer is most likely to skip.

Workers have a systematic optimism bias (the [goal guard](goal.md) argues the same point): they write down what they accomplished
and forget to write down what they tried that didn't work. And the latter is what is actually expensive — in [HT002](../cases/ht002.md) an hour went into circling a compilation problem;
if the conclusion of that hour isn't written down, the successor will circle it again exactly the same way.

So `HANDOFF_PROMPT` devotes a paragraph to this specifically, with that measured cost attached.

### What it looks like

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

The event is `Event("handoff")`, and `payload["phase"]` has **three** values: `near` (approaching), `writing` (in progress —
writing a handoff takes a dozen-odd seconds, and without this event the UI looks frozen), and `done` (handoff complete). The `done` payload also carries
`context`, `window`, `degraded`, `path`, and `sections`.

### How the thresholds are computed

```python
at      = max(10_000, window - headroom)   # 换代线,有 10k 下限
warn_at = max(1_000, at - 20_000)          # 逼近提醒线
```

The 10k floor on `at` is necessary — below that you can't even write the handoff.

The scale below uses `--window 200000` as the example; **the default window is 1,000,000**:

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                       warn  handoff       hard limit
```

When `window` is not given, `default_window()` decides from the **model name string**, looking only at the two environment variables
`ANTHROPIC_MODEL` and `ANTHROPIC_DEFAULT_OPUS_MODEL`:

| Model name | Judged as |
|---|---|
| Contains `1m` as a standalone word | `1_000_000` |
| Contains `haiku` | `200_000` |
| Everything else, **and when neither variable is set** | `1_000_000` |

Note the order: `1m` matches first, so `claude-haiku[1m]` is judged as 1,000,000, not 200,000.

Why `headroom` is `50_000`: auto-compact fires at window − 33k, and handoff has to get ahead of it;
plus "writing the handoff" itself needs another round. 50k satisfies both.

**`--window` is the switch you should reach for first when changing models or gateways.** The SDK side can't give a reliable window size, so it can only guess from the name.
If the real window is larger → handoff comes early (wasteful, not wrong); if smaller → it's too late, and you must adjust. One measurement worth mentioning:
the gateway on the development machine is configured with `claude-opus-5[1m]`. Computing against 200,000 would have meant a new generation every 150,000,
when it can actually run to 950,000 — **a factor of 5**, and long-horizon work gets chopped to pieces.

`flower -v` shows the effective credential configuration before the run starts (endpoint, model name, token masked to the first 4 characters).

### `is_overflow`: turning a hard error into an on-the-spot handoff

This is the precondition for **daring to default `default_window()` to 1,000,000**.

If the window is judged too large, the threshold is never reached, and auto-compact is off — so you slam straight into the API.
`is_overflow(*texts)` recognizes that signal: `prompt is too long`, `context length exceeded`,
`maximum context length`, `too many total text bytes`, `input length and max_tokens exceed`, and so on.

Once recognized, it takes **the same handoff path**, except this generation's handoff is necessarily degraded — that session can no longer run
"one more round to write a handoff," so the mechanically assembled degraded artifact is used directly, a new session takes over as usual, and **this step does not fail**.

So the cost of judging the window too large drops from "this step fails" to "this generation's handoff is degraded."

`is_overflow` is a **module-level function**, not a method on `Handoff`, and it is variadic.

### When the handoff can't be written: degrade, don't stop

The round that writes the handoff can also fail — the network drops, the model glitches, or parsing comes back missing a required section. Because
auto-compact is already off, **there is no fallback**, and stopping here means hitting the window.

What it does: mechanically assemble a **partial handoff** from what is already known, mark `doing` with `[降级:交接没写成]`
(constant `DEGRADED`), stuff the first **1200** characters of the original task into `scene`, and hand off anyway. The successor is told plainly
that what it received is incomplete and it should go look at the scene itself. At the same time an extra `交接降级(…)` entry appears in `StepResult.errors`,
and the reason is findable in `manifest.json`.

The corresponding module-level function is `degraded(step, prompt, *, why="")`; `Handoff.degraded` is a read-only property
that checks whether `doing` carries that marker.

> **A partial handoff beats hitting the window by a mile.**

The handoff-writing round has two more deliberate arrangements: it runs with `max_budget_usd=None` — **the handoff must be writable,
it cannot be blocked on budget**; and `on_event=None` — this round does not push to the UI.

### One landmine: the handoff-writing round must be exempt from the threshold

The handoff is written **after the line has been crossed** — at which point the water level is of course still above the threshold. Without the exemption, the first message of
the handoff round is judged "time to hand off" again, so it gets interrupted before writing a single word, **every generation produces a degraded artifact**,
and everything looks fine (the degraded path works very well).

This was hit for real: the first live run of `tests/handoff_live.py` produced **degraded handoffs for both generations**. The offline tests missed it —
there `_attempt` was replaced wholesale, so the fake never exercised this criterion. The criterion is now lifted into `Runtime._handoff_due()`, which offline tests verify directly.

### A brake against runaway

`max_generations=8`.

!!! danger "A `window` set too small burns money in an endless handoff loop"
    The danger: **the threshold sits below that role's startup floor** (measured at roughly 34k for the [coordinator](../reference/glossary.md#协调者) —
    the system prompt plus the [workbench](../reference/glossary.md#工作台) index alone eat that), so every new session crosses the line the moment it opens its mouth
    → write handoff, hand off, cross again, **forever**. And handoffs don't consume retry budget — that is intentional — so the only brake is
    `max_generations=8`.

    A normal long run never reaches 8; if you do hit it, it is almost certainly a `window` set too small — and the error message at the limit says exactly that
    ("the threshold is probably below this role's startup floor; raise window, or use `--no-handoff`").

### One handoff, end to end

```text
work (session A)
  |  main-thread context crosses the threshold   <- only the main thread counts. A subagent's context
  |                                                is a matter for its own transcript; it dissolves when
  |                                                done and should not force the main session to hand off
  |- break at a message boundary                 <- same principle as a Ctrl-C interrupt: break cleanly,
  |                                                don't tear the state (same price too: in-flight subagents
  |                                                are lost. The 50k headroom exists for this)
  |- run one more round on the same session: write the handoff
  |     why it writes it itself — only it has that context. Anyone else would have to read it all first,
  |     which defeats the purpose
  |- freeze to <workbench>/notes/交接-<step name>.md, previous generation moved to notes/archive/交接/
  |- new session (resume=None, fork=False), prompt = the handoff's prompt_block()
work (session B) continues
```

`HANDOFF_PROMPT` is the prompt that makes the current session write the handoff; it contains the two placeholders `{used}` and `{window}`.
**It is not a new role** — only this session has that context.

### A handoff is not a retry; how the books are kept

| Field | What happens on handoff |
|---|---|
| `attempts` | **Does not increase** — it counts failed attempts |
| `retired[]` | The session_ids burned by this step, recorded **in order** |
| `session_id` | Always **the last successor**, never one that was burned |
| `context` | The context size the main thread actually saw on its last round |
| `cost_usd` / `num_turns` | **Accumulated** across retries and handoffs |

All of these go into `manifest.json`, so afterwards you can fully reconstruct "how many generations this step burned, and what each one cost."

### Where the handoff lands

`<workbench>/notes/交接-<step name with illegal characters stripped>.md`; an existing previous generation is moved to
`notes/archive/交接/<step name>-<timestamp>.md`.

**With no workbench, nothing is written to disk** — `_handoff_path` returns `None`, the document still reaches the successor through the prompt,
the handoff proceeds as usual, and only **the human can't dig up that file afterwards**. To be able to, turn the workbench on
(`Runtime(workbench=True)`, or let the [workflow](../reference/glossary.md#流程) mount one itself).

## When you shouldn't use it

- **You actually want compact.** `flower --no-handoff`, or `Runtime(handoff=False)`.
  Handoff turns auto-compact off as a side effect; if you don't want that side effect, don't turn it on.
- **You want both mechanisms live.** Explicitly passing `AgentSpec(compact=CompactPolicy(mode="auto"))` preserves auto-compact,
  but after that you can no longer tell who caused any given context drop, and debugging gets harder. Trust handoff or trust compact, not both.
- **Short tasks, single-round work.** Handoff will never fire and configuring it is pointless — but remember that `Runtime` defaults to
  `handoff=True` and still turns auto-compact off.
- **No workbench but you expect to read the handoff later.** Turn the workbench on first, otherwise the document only ever existed in that run's context.
- **Starting a long run before `window` is matched.** When the real window is smaller than the default, the first several generations of handoffs will all be degraded,
  and a degraded handoff is precisely the least useful kind. Match it with `--window` first, or run something short first and check the model name in `-v`.
- **Treating handoff as the whole of context governance.** It is the last line. The layers that trim on the spot
  (spill, [trim](../reference/glossary.md#裁剪), [prune](../reference/glossary.md#剪除)) are cheaper —
  see [Context economics](context.md).

## Knobs

| Symptom | Which one to turn |
|---|---|
| Handoffs too frequent, work keeps getting interrupted | Set `--window` to the model's real window (`-v` shows the effective model name) |
| Hands off right at the start, reports "startup floor" | Same as above; `window` is set too small |
| Handoffs are always degraded | Check `errors` in `runs/manifest.json`; the degradation reason is written there |
| The successor keeps redoing what the previous generation did | The "dead ends" section is too thin. You can edit that file directly |
| Want to read the handoff afterwards but can't find the file | No workbench. The handoff isn't written to disk, it only went through the prompt |
| You just want compact | `--no-handoff` |

## Related

- [Continuity](continuity.md) — picking up the previous run across processes; the other direction of the same thing as this page
- [Context economics](context.md) — the layers that trim on the spot
- [Goal guard](goal.md) — the argument for "workers have a systematic optimism bias"
- [Python API](../reference/api.md) — `HandoffPolicy`, `Handoff`, `CompactPolicy`, `default_window`, `StepResult`
- [Command line](../reference/cli.md) — `--window`, `--no-handoff`
- Source: [`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
