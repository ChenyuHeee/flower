# Clarify

Get the requirement straight before touching anything. The [clarifier](../reference/glossary.md#确认者) is a role that only asks questions and never does work; it keeps asking until things are clear, then emits a [brief](../reference/glossary.md#需求确认书) of exactly four sections and freezes it to disk. Every later [step](../reference/glossary.md#步骤) opens by reading that document instead of guessing the requirement again — and the Q&A itself **never enters** any downstream context.

## The problem it solves {#解决什么问题}

Everything flower's context cleanup removes is **scene material**: staleness expiry, denied-call excision, error-message excision, [spilling](../reference/glossary.md#落盘) of large results. Losing scene material is fine — rerun and you have it again.

One class of error is not like that: **misunderstanding the goal**. It is the only class of error that **cleaning up context makes worse**. Once the scene material is gone, what remains is precisely the decision built on the wrong premise, and it looks exactly like a correct decision — nothing marks its premise as suspect.

[Long-horizon](../reference/glossary.md#长程) runs amplify this to the worst case: the wrong premise runs for hours first, dispatches a dozen [subagents](../reference/glossary.md#subagent), lands a pile of artifacts on disk, and only then gets exposed. By then the expensive part isn't the tokens — it's that **every artifact was built against the wrong requirement**. The [HT001](../cases/ht001.md) ledger measures the ratio: the clarify step cost **$0.3704 / 5 turns / 0.06h**, the work step after it cost **$171.2476 / 31 turns / 10.44h**.

So there has to be a channel that can "stop and ask", and it has to sit **before** work starts.

## How to use it (minimal code) {#怎么用最小代码}

### Zero code: command line {#零代码命令行}

Go into the project directory and just run:

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

- Type a **number** to pick an option, or just type an answer in prose
- **Enter = skip** this question; it decides for itself and records the assumption under "Unknowns and assumptions"
- It only proceeds when all four sections are present; the brief is frozen at `.flower/notes/需求.md`
- **Reruns don't interrogate you again** — to re-clarify, delete that file or pass `--new`

Want to see only what it asks, without any work happening afterwards: `flower --clarify-only`. To put a hard quota on questions: `--asks 12` (only when given does an extra line `(还能问 N 次)` appear under the options; there is no limit by default and that line doesn't appear). Nobody watching: `--timeout 0`. This path is implemented in [`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py).

!!! warning "Answers come from standard input — run it in a real terminal"
    In a pipe, under `nohup`, or in CI there is nobody to answer: as soon as stdin hits EOF, the question pending at that moment is treated as "input closed" and skipped, and every question after it waits out the full `--timeout`. In those settings just pass `--timeout 0` — every question falls through immediately, and it decides for itself and writes the assumptions into "Unknowns and assumptions".

### Wiring it yourself {#自己接线}

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # no question limit by default, waits 30 minutes for a human
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

`prompt` carries only **your** original request — one sentence is enough. What to ask is the clarifier's decision: which questions matter in your domain is something the framework does not know and should not know. The `协调者` above is an `AgentSpec` you built yourself with `coordinator()`; see [Designing a workflow](workflow.md).

Parameters of `clarify_step()`:

| Parameter | Default | Meaning |
|---|---|---|
| `channel` | — | A `HumanChannel`. **The same instance** must also be attached to `Workflow(channel=...)` |
| `brief_path` | — | Where the brief lands. Must be inside the [workbench](../reference/glossary.md#工作台) you attached — see below |
| `prompt` | — | Your original request. `str` or `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | Step name, and also the key in `ctx` |
| `spec` | `None` | Bring your own `AgentSpec`; if given, `clarify()` is not used to build one |
| `instructions` | `""` | Domain instructions appended after `CLARIFIER_RULES` |
| `always_ask` | `False` | `True` = re-clarify every time (use this when the requirement changes) |
| `on_fail` | `"stop"` | Where to go when the four sections are incomplete; same as `Step.on_fail` |
| `retries` | `0` | How many retries when the four sections are incomplete |
| `**spec_kw` | — | Passed through to `clarify()`: `can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

After it runs, `ctx` holds three things:

```python
ctx["确认需求"]     # str,四段的紧凑版(prompt_block),直接插进下游 prompt;键名 = 步骤名
ctx[BRIEF_KEY]     # "_brief" —— Brief 对象,想按段取用这个
ctx[MISSING_KEY]   # "_brief_missing" —— 只在四段不齐时有:缺哪几段,给 UI 显示
```

When tuning goes badly, reach for these knobs first:

| Symptom | What to turn |
|---|---|
| Asks too much, too finely | Give `max_asks` a hard quota; spell out in `instructions` what is obvious in your domain |
| Starts working after too few questions | Name in `instructions` the specific things it must nail down (the count is already unlimited by default, so raising the quota does nothing) |
| Fills the four sections perfunctorily | Give an example from your own domain in `instructions` |
| Stalls with nobody on duty | `timeout_s=0` |
| Want to re-clarify every time | `always_ask=True`, or delete the brief file |

## What it actually does {#它实际做了什么}

### Trigger points: three wires, not one new field {#触发时机三处接线一个新字段都没加}

What `clarify_step()` builds is an ordinary `Step` with three callbacks filled in:

| Wired to | When it runs | What it does |
|---|---|---|
| `Step.when` | Before entering this step | **Skips** if the brief already exists with all four sections, and pours it into `ctx` |
| `Step.gate` | After this step runs, before the result goes downstream | **Blocks** if the four sections aren't complete; if complete, `write()` **freezes** it |
| `Step.reduce` | After it passes | Passes **the parsed four sections** downstream, not the model's raw text |

**Skipping also fills `ctx`.** This one is easy to miss: when `when` returns `False`, `Workflow` doesn't execute the step, so it doesn't write `ctx[step.name]` either — which is why `clarify_step` pours the existing brief in from inside `when`. Otherwise downstream would get a `KeyError` on reruns.

`reduce` passes `Brief.prompt_block()` rather than the model's raw text, because the raw text may carry extra material it wrote (measured: it will paste an entire codebase into its reply).

On [continuity](../reference/glossary.md#接续), this step opens with a different sentence — `CLARIFY_RESUME`: "Continue the requirement clarification you didn't finish — **do not start over**…". Without that sentence, continuity resends the original request as a new task, and the clarifier may re-ask what it already asked.

### Boundary: the Q&A does not enter downstream context {#边界问答不进下游的上下文}

```text
确认需求        独立会话  ────→  磁盘上一份冻结的四段确认书
                                          │
干活(下一步)   新会话(resume_from=None)◄─┘   只拿到那四段
```

`clarify_step` leaves `resume_from` at its default `None`, so the next step is a **new session** that gets only the brief. That Q&A **never entered** the [coordinator's](../reference/glossary.md#协调者) context — it isn't "entered and then trimmed". The difference is substantive: trimmed material is still in `sessions.db` and can be brought back by a resume; material that never entered doesn't have that problem.

The Q&A itself is **appended to `log_path`**. That copy costs no context, is unaffected by compaction, and survives a move to another machine — the same idea as the workbench.

### Each of the four sections blocks one class of failure {#四段各挡一类失败}

| Section | What to write | What happens if you don't |
|---|---|---|
| **Goal** | One sentence: what is being built, and for whom | You get a different thing than intended |
| **Acceptance criteria** | Decidable conditions, one per line. "Works well" doesn't count; "running `x` outputs `y`" counts | Nobody can decide that it's done |
| **Boundaries** | **Explicitly what is not being done** | Scope creep. This section constrains **every single** subagent downstream |
| **Unknowns and assumptions** | Everything not asked, timed out, or guessed, one per line | **A wrong premise gets silently buried** |

The fourth section is the fuse of a long-horizon run. If any of the first three is wrong, an assumption written explicitly in the fourth gives whoever reads it a chance to stop things; buried, you only find out hours later when every artifact is scrap. Wrong premises can't be fully avoided, but they can be made **explicit**.

It only proceeds when all four sections are present; `Brief.missing()` reports which are missing — it returns the Chinese section names, so you can display them directly.

Parsing is very forgiving about form: `## 目标` / `**目标**` / `目标:` / `3. 边界` are all recognized, and body text directly after the heading (`目标: 做一个 X`) is recognized too, as are common aliases (`验收条件` → acceptance criteria, `不做什么` → boundaries, `未知项与假设` → unknowns and assumptions); if a section appears more than once, the first non-empty one wins. Two exceptions to know about:

- `Brief.parse()` **strips fenced code blocks first**, and on an **unclosed** fence it discards everything from that point on. When the model's output is truncated, none of the following sections parse → the four sections are incomplete → `gate` sends it back.
- `Brief.load()` treats `"(未填)"` as empty. If you hand-edit the brief and copy `to_markdown()`'s placeholder text verbatim, that section still counts as missing.

### Boundary: what the clarifier can touch {#边界确认者能碰什么}

I ran an **unconstrained** clarifier (`/tmp/probe_ask.py`, **$0.8908 / 230 seconds**): after two questions it **started writing code immediately**; once permissions blocked it, it **pasted the entire codebase into the body of its reply**. Writing "don't write code" in the prompt does not stop this — its system prompt at the time said something like that already. So there are two mechanisms:

**One: a hook blocks its write tools.** `clarify()`'s no-approval list is `mcp__human__ask` plus (when `can_read=True`) `Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch` — no `Write` / `Edit` / `Bash` / `Agent`. What actually enforces this is the `whitelist_guard` that `Runtime` installs automatically: it derives from the no-approval list which of `Bash` / `Write` / `Edit` / `NotebookEdit` should be blocked, and `deny`s on a hit. It isn't "asked not to start work" — it **cannot** start work.

Giving it read access pays off: one look at the repo saves several questions, and this session is thrown away when done, so a dirty read doesn't matter (`can_read=False` withholds even reads).

**This must be a hook; `allowed_tools` alone is not enough.** The latter is a **no-approval list, not an exclusive whitelist** — the model can still call tools that aren't on it. Two pieces of measured evidence that still hold:

- In [HT002](../cases/ht002.md), the [judge](../reference/glossary.md#判定者) for "set the goal" actually ran **`Bash` 11 times**, while `judge()` defaults to `can_run=False` and the list contains no `Bash` at all (that run predates this hook — the same call today would be `deny`ed on the spot by `whitelist_guard`, which is exactly the point: what stops it is the hook, not the list).
- **A $0.1 probe**: give an agent `allowed_tools=["Read"]` and ask it to write a file — `Write` is refused by the permission layer (`"requested permissions to write ... but you haven't granted it yet"`), `Bash` is refused by path safety (`"Output redirection was blocked. For security, Claude Code may only write to files in the allowed working directories"`). **The calls went out**; other layers stopped them.

`clarify()` doesn't set `permission_mode` explicitly, so it inherits `AgentSpec`'s default `"default"`. `coordinator()` defaults to `"acceptEdits"` — whoever passes that value through to the clarifier loses that layer of protection.

**Two: the framework parses only those four sections and drops everything else.** `Brief.parse()` strips fenced code blocks before looking for headings — pasted code can't reach downstream. This is the last gate against "it pollutes downstream".

### Boundary: the question channel {#边界提问通道}

The model-side question tool is `mcp__human__ask` (parameter `question`, optional `options`). `HumanChannel` is an in-process MCP server, and it **registers two tools** — `mcp__human__ask` and `mcp__human__inbox`; the clarifier's no-approval list contains only the former (the inbox is for the coordinator).

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
| `timeout_s=1800.0` (default) | Waits half an hour; on expiry returns an explanatory sentence, **not an error** |
| `timeout_s=None` | Waits forever. Use only when you know someone is on duty (the CLI can't produce this value; `--timeout` is a float) |
| `timeout_s=0` (negatives too) | **Fully automatic**: every question falls through immediately, no pretense of waiting |
| `max_asks=None` (default) | **No limit** — how many questions to ask is the clarifier's own judgment |
| `max_asks=N` | Hard quota. Question tool calls beyond it are **refused outright**: no blocking, no error |
| `max_asks=0` | Questions forbidden (CI / unattended) |

`remaining` returns `-1` when `max_asks=None` (not 0, and not infinity), and the terminal uses that to hide "N questions left".

The literal text returned on timeout is:

> No one answered. Continue on your own judgment, and write this question and the assumption you adopted into the "Unknowns and assumptions" section. Don't repeat the question, and don't stop here.

All three ways a question can fall through (timeout / quota exhausted / human skips) point at the same action: **write the assumption into the fourth section**. That's why the fourth section still has content when unattended, and why a long-horizon run can keep going. A quota written into the prompt is a suggestion; **counting it in the channel is a guarantee**.

One measured mechanical fact: `await`ing an external future inside an in-process MCP tool handler **does not deadlock** — while the handler is suspended the event loop keeps turning, and another task or **another thread** can fill in the answer. So `answer()` / `decline()` can be called directly from a web backend or a TUI input thread (internally via `loop.call_soon_threadsafe`); this is the normal case, not an edge case. Exceptions thrown by UI callbacks are collected in `ui_errors` and **do not interrupt the run** — a crashed frontend shouldn't take three hours of work with it. For the full member list see [Python API](../reference/api.md).

!!! warning "Set `max_turns` too low and "ask until it's clear" becomes empty words"
    `clarify()`'s `max_turns` defaults to `None` (unlimited). **Every question asked is one turn** — setting it to 16 means "at most a dozen or so questions", and it takes effect **silently**: on the channel side `max_asks=None` still says "no limit", and a human can't tell who cut it off. To leave questioning open, **both defaults must stay at `None`**: `HumanChannel.max_asks` and `clarify(max_turns=...)`.

### Where the brief lands: it must be the workbench you attached {#确认书落在哪必须是挂上去的那个工作台}

The workbench index is injected into the system prompt, so the coordinator knows from the start where the requirement file is; when dispatching work it just passes the path down, without copying the content into the [task brief](../reference/glossary.md#任务书).

!!! warning "The index reaches the coordinator only"
    A subagent has its own system prompt and **does not inherit** the session-level one (measured at **$0.2461**, `tests/prelude_live.py`). So it's "the coordinator relays the path", not "every subagent automatically knows".

What matters is **which** workbench. There is only one correct form: build it yourself, attach it to `Workflow`, and have the driver hand the same object to `Runtime`.

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← 挂上去
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

Two wrong forms, neither of which **raises an error**, so be especially careful:

```python
# ✗ 自己拼一个路径:相对进程 cwd,和 Runtime(workbench=True) 造的 <run_dir>/workbench
#   是两个目录。确认书写进 A,注入的索引扫的是 B —— 上面那条承诺静默失效。
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ 想从 Runtime 反着拿:经 cli.py 做不到。它先调 main() 造 Workflow,
#   之后才建 Runtime —— 那时候 brief_path 早就定死了。
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

When writing your own driver (not going through `cli.py`), build the `Workbench` first, then give **the same object** to both `Workflow(workbench=wb)` and `Runtime(workbench=wb)`. Item 5 of `tests/trial_offline.py` asserts directly that "the brief appears in `prompt_block()`", and item 11 confirms that this assertion catches the regression.

### Verification status {#验证状态}

**All green offline** (`tests/clarify.py`, **52 items**, costs nothing): the five semantics of the question channel (blocking wait for an answer / quota exhausted / timeout fall-through / skip / cross-thread answer), four-section parsing (including a "pasted code in" sample), the fact that the `clarify()` role has **no** write tools, and the three wires of `clarify_step`.

**The CLI path runs end-to-end offline**: preload a complete brief → the first step skips → the channel automatically hooks up the stdin thread → the brief is poured into `ctx` → clean exit.

**Not exercised against the real API.** The $0.8908 probe was a **real request**, but what it tested was "what an unconstrained clarifier will do", not this path as it stands.

## When not to use it {#什么时候不该用它}

**The requirement is already a frozen artifact.** The requirement is written in a file, handed down by an upstream system, or this run is just a rerun of the same thing — then there's nothing to ask. Feed the requirement text straight into the work step, or keep `clarify_step` and let `when` skip it (with the brief present it doesn't ask anyway).

**Nobody to ask, and you don't want it guessing.** With `timeout_s=0` every question falls through immediately and the fourth section gets filled with a pile of its own assumptions — that's by design, but the credibility of that brief then equals the credibility of those assumptions. The cleaner move in CI is `max_asks=0` (questions explicitly forbidden), with the requirement supplied in full from outside.

**Small one-off jobs.** The clarify step itself costs money: in [HT002](../cases/ht002.md), for something like "clone a repo, install it on macOS and get it running", clarifying the requirement cost **$0.5306 / 9 turns / 0.10h**. The smaller the job, the worse this step's share looks. The single-agent path `flower once` doesn't include it.

**Don't re-open a dialogue when the requirement changes.** The brief is a frozen artifact; from the moment it lands on disk, the file is the source of truth for the requirement — the correct move is to **edit that file**. `--clarify-only` in an already-clarified directory is a **no-op** (that workflow has only this one step, and this step skips); to re-clarify, pair it with `--new`, or set `always_ask=True` if you're wiring things yourself.

**It does not decide whether the work is done.** That's another layer; see [Goal guard](goal.md). Clarify blocks "what got built isn't what was wanted"; it can't block "it says it's done when it isn't".
