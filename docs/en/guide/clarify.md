# Clarify

Get the requirement straight before touching anything. The [clarifier](../reference/glossary.md#确认者) is a role that only asks questions and never acts;
it keeps asking until things are clear, then emits a [brief](../reference/glossary.md#需求确认书) of exactly four sections and
freezes it to disk. Every later [step](../reference/glossary.md#步骤) opens by reading that document instead of guessing the requirement again —
and that Q&A **never enters** any downstream context.

## What problem this solves {#解决什么问题}

Everything flower's context cleanup removes is **scaffolding**: expired freshness, denied calls stripped, error messages stripped,
large results [spilled](../reference/glossary.md#落盘). Losing scaffolding is fine; rerun and you have it again.

One class of error is not like that: **misunderstanding the goal**. It is the only class of error that **cleanup makes worse**. Once the scaffolding is gone,
what remains is exactly the decision built on the wrong premise, and it looks identical to a correct decision —
nothing marks its premise as suspect.

[Long-horizon](../reference/glossary.md#长程) amplifies it to the worst case: the wrong premise runs for hours,
dispatches a dozen [subagents](../reference/glossary.md#subagent), leaves a pile of artifacts on disk, and only then surfaces.
By then the expensive part isn't tokens, it's that **every artifact was built to the wrong requirement**.
The [HT001](../cases/ht001.md) ledger gives you the ratio: the requirement-clarification step cost **$0.3704 / 5 turns / 0.06h**,
the actual work step **$171.2476 / 31 turns / 10.44h**.

So there has to be a channel that can "stop and ask" — and it has to sit **before** work starts.

## How to use it (minimal code) {#怎么用最小代码}

### Zero code: command line {#零代码命令行}

Go into the project directory and run:

```bash
cd /path/to/your/project
flower
```

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

In the terminal you'll see questions like this:

```text
  ? 这个工具是给命令行用,还是要有 Web 界面?
     1) 纯命令行
     2) Web 界面
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
```

- Type a **number** to pick an option, or just type an answer freely
- **Enter = skip** this question; it decides for itself and records the assumption under "Unknowns & assumptions"
- Only a complete set of four sections passes; the brief is frozen at `.flower/notes/需求.md`
- **A rerun will not interrogate you again** — to re-clarify, delete that file or pass `--new`

Want to see only what it asks, without letting it proceed: `flower --clarify-only`. Give questions a hard quota: `--asks 12`
(only then does an extra line `(还能问 N 次)` appear under the options; the default is unlimited and that line does not appear). Nobody watching: `--timeout 0`.
This path is implemented in
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "Answers come from standard input — run it in a real terminal"
    In a pipe, under `nohup`, or in CI nobody can answer: as soon as stdin hits EOF, the question pending at that moment is treated as "input closed" and skipped,
    and every question after that waits out the full `--timeout`. In that situation just pass `--timeout 0` —
    every question falls through immediately, and it decides for itself and writes the assumptions into "Unknowns & assumptions".

### Wiring it yourself {#自己接线}

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # 默认不限提问次数,等人 30 分钟
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

`prompt` carries only **your** raw request; one sentence is enough. What to ask is the clarifier's decision —
which questions matter in your domain is something the framework doesn't know and shouldn't. The `协调者` above is an `AgentSpec` you build yourself with `coordinator()`;
see [Designing a workflow](workflow.md).

Parameters of `clarify_step()`:

| Parameter | Default | Meaning |
|---|---|---|
| `channel` | — | A `HumanChannel`. **The same instance** must also be attached via `Workflow(channel=...)` |
| `brief_path` | — | Where the brief lands. Must be inside the [workbench](../reference/glossary.md#工作台) you attached; see below |
| `prompt` | — | Your raw request. `str` or `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Step name, and also the key in `ctx` |
| `spec` | `None` | Bring your own `AgentSpec`; if given, `clarify()` is not used to build one |
| `instructions` | `""` | Domain instructions appended after `CLARIFIER_RULES` |
| `always_ask` | `False` | `True` = re-clarify every time (use when the requirement changes) |
| `on_fail` | `"stop"` | Where to go when the four sections are incomplete; same as `Step.on_fail` |
| `retries` | `0` | How many retries when the four sections are incomplete |
| `**spec_kw` | — | Passed through to `clarify()`: `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

After it runs, `ctx` holds three things:

```python
ctx["确认需求"]     # str,四段的紧凑版(prompt_block),直接插进下游 prompt;键名 = 步骤名
ctx[BRIEF_KEY]     # "_brief" —— Brief 对象,想按段取用这个
ctx[MISSING_KEY]   # "_brief_missing" —— 只在四段不齐时有:缺哪几段,给 UI 显示
```

When it misbehaves, reach for these knobs first:

| Symptom | Which knob |
|---|---|
| Asks too much, too finely | Give `max_asks` a hard quota; spell out in `instructions` what is obvious in your domain |
| Starts work after asking too little | Name in `instructions` the things it must pin down (the count is already unlimited by default, so raising the quota does nothing) |
| Fills the four sections perfunctorily | Put an example from your own domain in `instructions` |
| Stalls with nobody watching | `timeout_s=0` |
| Want to re-clarify every time | `always_ask=True`, or delete the brief file |

## What it actually does {#它实际做了什么}

### Trigger points: three hooks, not one new field {#触发时机三处接线一个新字段都没加}

What `clarify_step()` builds is an ordinary `Step`, with three callbacks filled in:

| Wired to | When it runs | What it does |
|---|---|---|
| `Step.when` | Before entering this step | If the brief already exists and has all four sections, **skip**, and load it into `ctx` |
| `Step.gate` | After this step runs, before the result goes downstream | If the four sections are incomplete, **block**; if complete, `write()` to **freeze** |
| `Step.reduce` | After it passes | Pass **the parsed four sections** downstream, not the model's raw text |

**Skipping also fills `ctx`.** This one is easy to miss: when `when` returns `False`, `Workflow` does not execute the step,
so it does not write `ctx[step.name]` — which is why `clarify_step` loads the existing brief inside `when`.
Otherwise a rerun would hand downstream a `KeyError`.

`reduce` passes `Brief.prompt_block()` rather than the model's raw text, because the raw text may carry extra material
(measured: it will paste an entire codebase into its reply).

On [continuity](../reference/glossary.md#接续) this step opens with a different line — `CLARIFY_RESUME`:
"pick up the requirement clarification that was left unfinished — **not a restart**…". Without that line,
continuity would resend the raw request as a new task, and the clarifier might re-ask questions it already asked.

### Boundary: the Q&A does not enter downstream context {#边界问答不进下游的上下文}

```text
确认需求        独立会话  ────→  磁盘上一份冻结的四段确认书
                                          │
干活(下一步)   新会话(resume_from=None)◄─┘   只拿到那四段
```

`clarify_step` leaves `resume_from` at its default `None`, so the next step is a **new session** that gets only the brief.
That Q&A **never enters** the [coordinator's](../reference/glossary.md#协调者) context —
it isn't "let in and then trimmed". The difference is substantive: trimmed material is still in `sessions.db`
and can be dragged back by a resume; material that never entered doesn't have that problem.

The Q&A itself is **appended to `log_path`**. That copy costs no context, is unaffected by compaction, and survives a move to another machine —
same idea as the workbench.

### Each of the four sections blocks one class of failure {#四段各挡一类失败}

| Section | What goes in it | What happens if it's missing |
|---|---|---|
| **Goal** | One sentence: what is built, for whom | You build something else |
| **Acceptance criteria** | Decidable conditions, one per line. "It works" doesn't count; "running `x` prints `y`" does | Nobody can decide "it's done" |
| **Boundaries** | **Explicitly what is not done** | Scope creep. This section governs **every** subagent that follows |
| **Unknowns & assumptions** | What wasn't asked, what timed out, what it guessed — one per line | **Wrong premises get silently buried** |

The fourth section is the fuse for a long-horizon run. If any of the first three is wrong, an assumption written explicitly in the fourth gives whoever reads it a chance to stop things;
buried, you only find out hours later when the artifacts are all worthless. Wrong premises can't be fully avoided, but they can be made **explicit**.

Only a complete set of four passes; which one is missing is reported by `Brief.missing()` — it returns the Chinese section names, which can be displayed directly.

Parsing is very forgiving about form: `## 目标` / `**目标**` / `目标:` / `3. 边界` are all recognized, body text directly after the heading
(`目标: 做一个 X`) is recognized, and common aliases are recognized (`验收条件`→acceptance criteria, `不做什么`→boundaries,
`未知项与假设`→unknowns & assumptions); if a section appears more than once, the first non-empty one wins. Two exceptions to know:

- `Brief.parse()` **strips fenced code blocks first**, and on an **unclosed** fence it discards everything from there on.
  When model output is truncated, none of the later sections parse → four sections incomplete → `gate` sends it back.
- `Brief.load()` treats `"(未填)"` as empty. If you hand-edit the brief and copy the placeholder text from `to_markdown()`,
  that section still counts as missing.

### Boundary: what the clarifier may touch {#边界确认者能碰什么}

An **unconstrained** clarifier was run once (`/tmp/probe_ask.py`, **$0.8908 / 230 seconds**):
after two questions it **started writing code**; blocked by permissions, it **pasted the entire codebase into the body of its reply**.
Writing "do not write code" in the prompt does not stop this — its system prompt at the time already said something like that. So there are two mechanisms:

**One: a hook that blocks its write tools.** The no-approval list of `clarify()` is
`mcp__human__ask` plus (when `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch`,
with no `Write` / `Edit` / `Bash` / `Agent`. What actually enforces this is the `whitelist_guard` that `Runtime` installs automatically:
it infers from the no-approval list which of `Bash` / `Write` / `Edit` / `NotebookEdit` must be blocked,
and `deny`s on a match. It isn't "asked not to start work", it **cannot** start work.

Giving it read access pays off: one look at the repo saves several questions, and this session is thrown away when done, so a dirty read doesn't matter
(`can_read=False` withholds reading too).

**This has to be a hook, not just `allowed_tools`.** The latter is a **no-approval list, not an exclusive whitelist** —
the model can still call tools that aren't in it. Two measured pieces of evidence still standing:

- In [HT002](../cases/ht002.md), the [judge](../reference/glossary.md#判定者) for "set the goal"
  actually ran **`Bash` 11 times**, while `judge()` defaults to `can_run=False` and its list contains no `Bash` at all
  (that run predates the hook — today the same call would be `deny`ed on the spot by `whitelist_guard`,
  which is exactly the point: what stops it is the hook, not the list).
- **A $0.1 probe**: give an agent `allowed_tools=["Read"]` and tell it to write a file —
  `Write` is refused by the permission layer (`"requested permissions to write ... but you haven't granted it yet"`),
  `Bash` is refused by path safety (`"Output redirection was blocked. For security, Claude Code may
  only write to files in the allowed working directories"`). **The calls went out**;
  other layers stopped them.

`clarify()` does not set `permission_mode` explicitly and inherits the `AgentSpec` default `"default"`.
`coordinator()` defaults to `"acceptEdits"` — whoever passes that value through to the clarifier removes that layer of protection.

**Two: the framework parses only those four sections and drops everything else.** `Brief.parse()` strips fenced code blocks before looking for headings —
pasting it in still doesn't get it downstream. This is the last gate against "it pollutes downstream".

### Boundary: the question channel {#边界提问通道}

The model-side question tool is called `mcp__human__ask` (parameter `question`, optional `options`).
`HumanChannel` is an in-process MCP server that **registers two tools** —
`mcp__human__ask` and `mcp__human__inbox`; the clarifier's no-approval list contains only the former
(the inbox is for the coordinator).

```python
HumanChannel(
    on_event=None,        # 推式 UI 的回调。挂在 Workflow 上时由 Workflow.run 自动接
    max_asks=None,        # 默认不限次数
    timeout_s=1800.0,     # 30 分钟。None = 永远等;<= 0 = 全自动
    log_path=None,        # 问答追加到这个文件,不占上下文
    amend_path=None,      # 人在运行途中说的话追加到这个文件(通常就是确认书)
    over_budget_text=..., timeout_text=..., declined_text=...,   # 三种落空的措辞
)
```

The normal state of a long-horizon agent is that **nobody is watching**, so "stop and wait for a human" must fail gracefully:

| Setting | Behavior |
|---|---|
| `timeout_s=1800.0` (default) | Wait half an hour; on expiry return an explanatory sentence — **not an error** |
| `timeout_s=None` | Wait forever. Only when you're sure someone is on duty (the CLI can't produce this value; `--timeout` is a float) |
| `timeout_s=0` (negative too) | **Fully automatic**: every question falls through immediately, no pretense of waiting |
| `max_asks=None` (default) | **Unlimited** — how many questions to ask is the clarifier's own judgment |
| `max_asks=N` | Hard quota. Questions beyond it are **refused outright** by the tool; no blocking, no error |
| `max_asks=0` | No questions allowed (CI / unattended) |

`remaining` returns `-1` when `max_asks=None` (not 0, not infinity), and the terminal uses that to omit the "N questions left" line.

The exact text returned on timeout:

> No one answered. Continue on your own judgment, and write this question and the assumption you adopted into the "Unknowns & assumptions" section.
> Do not repeat the question, and do not stop here.

All three fall-through cases (timeout / quota exhausted / person skipped deliberately) point at the same action: **write the assumption into the fourth section**.
That is why the fourth section still has content in an unattended run, and why a long-horizon run can keep going.
A quota written in the prompt is a suggestion; **the count in the channel is the guarantee**.

One measured mechanical fact: `await`ing an external future inside an in-process MCP tool handler **does not deadlock** —
while the handler is suspended the event loop keeps turning, and another task or **another thread** can fill in the answer.
So `answer()` / `decline()` can be called directly from a web backend or a TUI input thread (internally via
`loop.call_soon_threadsafe`); this is the normal case, not an edge case. Exceptions thrown by UI callbacks are collected in `ui_errors` and
**do not interrupt the run** — a crashed frontend shouldn't take three hours of work with it. The full member list is in the [Python API](../reference/api.md).

!!! warning "Set `max_turns` too low and "ask until it's clear" becomes empty talk"
    `clarify()` defaults `max_turns` to `None` (unlimited). **Every question is one turn** —
    setting it to 16 means "at most a dozen or so questions", and it takes effect **silently**: the channel side still says
    `max_asks=None`, unlimited, and no one can tell who cut it off. To keep questions open, both `HumanChannel.max_asks`
    and `clarify(max_turns=...)` **must keep their `None` defaults**.

### Where the brief lands: it must be the workbench you attached {#确认书落在哪必须是挂上去的那个工作台}

The workbench index is injected into the system prompt, so the coordinator knows from the start where the requirement file is; when dispatching work it just passes the path down,
without copying the content into the [task brief](../reference/glossary.md#任务书).

!!! warning "The index reaches the coordinator only"
    A subagent has its own system prompt and **does not inherit** the session-level one (measured at **$0.2461**,
    `tests/prelude_live.py`). So it's "the coordinator relays the path", not "every subagent automatically knows".

The key is **which** workbench. Only one way is correct: build it yourself, attach it to `Workflow`,
and have the driver hand the same object to `Runtime`.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← 挂上去
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Two wrong ways, both of which **raise no error**, so be especially careful:

```python
# ✗ 自己拼一个路径:相对进程 cwd,和 Runtime(workbench=True) 造的 <run_dir>/workbench
#   是两个目录。确认书写进 A,注入的索引扫的是 B —— 上面那条承诺静默失效。
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ 想从 Runtime 反着拿:经 cli.py 做不到。它先调 main() 造 Workflow,
#   之后才建 Runtime —— 那时候 brief_path 早就定死了。
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

When you write your own driver (not going through `cli.py`), build the `Workbench` first, then give **the same object** to both
`Workflow(workbench=wb)` and `Runtime(workbench=wb)`. Item 5 of `tests/trial_offline.py`
asserts directly that "the brief appears in `prompt_block()`", and item 11 confirms that assertion catches the regression.

### What has been verified and what hasn't {#验证状态}

**Offline all green** (`tests/clarify.py`, **52 items**, no cost): the five semantics of the question channel (block for an answer /
quota exhausted / timeout fall-through / skip / cross-thread answer), four-section parsing (including a "pasted code in" sample),
that the `clarify()` role has **no** write tools, and the three hook points of `clarify_step`.

**The CLI path runs offline end to end**: preload a complete brief → first step skips → the channel automatically attaches the stdin thread →
the brief is loaded into `ctx` → clean exit.

**Not run against the real API.** The $0.8908 probe was a **real request**, but it tested "what an unconstrained clarifier does",
not this path as it stands.

## When not to use it {#什么时候不该用它}

**The requirement is already frozen.** Written in a file, handed down by an upstream system, or this run is just a rerun of the same thing —
then there is nothing to ask. Feed the requirement text straight into the work step, or keep `clarify_step` and let `when` skip it
(with the brief present, it doesn't ask anyway).

**There is nobody to ask, and you don't want it guessing.** With `timeout_s=0` every question falls through immediately,
and the fourth section fills up with its own assumptions — that is by design, but the brief's credibility then equals the credibility of those assumptions.
The cleaner approach in CI is `max_asks=0` (explicitly no questions), with the requirement supplied in full from outside.

**Small one-off jobs.** The clarification step itself costs money: in [HT002](../cases/ht002.md),
for something like "clone a repo, install and run it on macOS", clarification cost **$0.5306 / 9 turns / 0.10h**.
The smaller the job, the uglier that share looks. The single-agent path `flower once` does not include this step.

**Changing the requirement should not mean a new conversation.** The brief is a frozen artifact; from the moment it lands, the file is authoritative —
the correct move is to **edit that file**. In a directory that has already been clarified, `--clarify-only` is a **no-op**
(that workflow has only this step, and this step skips); to re-clarify, add `--new`,
or set `always_ask=True` in your own wiring.

**It does not decide "is it done".** That is another layer; see [Goal guard](goal.md). Clarify blocks
"what got built isn't what was wanted"; it does not block "it says it's done but it isn't".
