# Command-line reference

Once installed, `flower` is a single executable with 4 subcommands and 23 flags. This page lists
all of them: the type, default and exact semantics of every flag, plus how to talk to a run in
progress, what it asks you the first time, what the exit codes are, and which files it puts in
your directory. After reading this page you should not need to open the source.

Source: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcommand | What it does | Positional args | Own flags |
|---|---|---|---|
| `go` | The whole chain: clarify the request → set goals → dispatch workers → judge every round. The default when no subcommand is written | `ask` (optional) | 11 |
| `run` | Run a [workflow](glossary.md#流程) you wrote yourself | `target` (required) | 0 |
| `once` | Run a single agent once, no workflow, no verdict | `prompt` (required) | 6 |
| `setup` | Configure credentials, written to `~/.config/flower/.env` | none | 0 |

23 flags total = 5 global + 11 specific to `go` + 6 specific to `once` + `-h/--help`. `run` and
`setup` have no flags of their own.

---

## Invocation forms {#调用形式}

Every argv passed to `flower` goes through `_with_default_cmd()` first to fill in the default
subcommand, and is only then handed to argparse (`cli.py:1253-1255`). That is why
`flower "help me build an X"` works — it gets rewritten into `flower go "help me build an X"`.

The rules for filling in the default subcommand (`cli.py:761-797`):

1. The set of global flags is **derived from the main parser itself**, not a hard-coded list.
   `nargs == 0` means a bare flag; everything else takes a value.
2. Scan left to right, skipping global flags. Flags that take a value skip their value too, and
   the `=` form such as `--workspace=/tmp` is recognized.
3. Stop at the first token that is not a global flag. If it is one of `go`, `run`, `once`, hand it
   to argparse as is; **otherwise insert a `go` in front of it**, so it becomes the request text
   for `go`.
4. If the scan finishes without hitting a positional (empty argv, or only global flags) → append
   `go` at the end and go to interactive input.
5. Exception: if argv contains `-h` or `--help`, return it unchanged and let argparse print help.

The constant used for this decision is `_CMDS = ("go", "run", "once")` (`cli.py:758`) —
**`setup` is not in it**; see [`setup`](#setup) for the consequences.

### What the rewrite actually produces {#实际的改写结果}

| What you type | What it parses as | Effect |
|---|---|---|
| `flower` | `["go"]` | Interactively asks "What do you want done?" |
| `flower -v` | `["-v", "go"]` | Same, with verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Starts immediately |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Global flags may come first |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | The `=` form is recognized too |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Subcommand flags may come after the request |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | Or before it |
| `flower --new` | `["go", "--new"]` | Flags only, no request → interactive input |
| `flower once "hi"` | `["once", "hi"]` | Unchanged |
| `flower run flows:main` | `["run", "flows:main"]` | Unchanged |
| `flower run` | `["run"]` | argparse reports the missing `target`; it is **not** treated as a request |
| `flower go run` | `["go", "run"]` | Explicit disambiguation: the request text is literally `run` |
| `flower setup` | `["go", "setup"]` | Runs `go` with the request string `setup`; see [`setup`](#setup) |
| `flower --help` | Unchanged | argparse prints help |

The two words `run` and `once` **cannot** be used directly as request text; that ambiguity is
deliberately preserved (`cli.py:770-771`). To use them as a request, write `flower go run`.

### Six usable forms {#六种能用的写法}

```bash
flower                                    # 1. Bare: asks "What do you want done?" or "Continue from last time?"
flower "帮我做一个 X"                       # 2. Request as a positional argument
echo "帮我做一个 X" | flower --timeout 0    # 3. Feed stdin through a pipe
flower once "读一眼这个仓库"                 # 4. Single agent
flower run flows.py:main                  # 5. Run a custom workflow
flower go setup                           # 6. Explicit go, with setup as the request text
```

The module form `python -m flower.cli` is equivalent to `flower` (`cli.py:1263-1264`).
The container wrapper `docker/flowerbox` takes exactly the same arguments as `flower`.

### Feeding stdin through a pipe {#管道喂-stdin}

When `sys.stdin.isatty()` is false, `ask_for_prompt()` **prints no prompt header** and simply
reads one line with `input("> ")` (`cli.py:814-822`). That is why `echo "..." | flower` works.

But right afterwards it prints a warning, and the stdin thread immediately hits EOF and exits:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

A piped run should set `--timeout 0`: questions then stop pretending to wait 30 minutes, they fall
through immediately, and the agent decides for itself and writes the assumptions into the
"Unknowns and assumptions" section of the brief.

---

## Subcommands {#子命令}

### `go` {#go}

Help text: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1096-1128`).

Positional argument `ask`, `nargs="?"` — omit it and you get interactive input. This is the most
common entry point; `flower "做 X"` goes through it.

What it does (`cli.py:1011-1042`):

1. `ensure_credentials()` — checks credentials and actually fires one API probe; see
   [First-run configuration flow](#首次运行的配置流程).
2. [Wake](glossary.md#唤醒) detection: a read-only look at whether this directory has been used
   before, without writing a single byte.
3. If no `ask` was given, print a prompt and ask; entering `/new` is equivalent to `--new`, and
   then it **asks again** for the request.
4. If this is a [continuity](glossary.md#接续), print a one-line wake banner.
5. Build a three-step [workflow](glossary.md#流程): `确认需求` → `设定目标` → `干活`, with a
   `干活·判定#N` after each work round. `--clarify-only` keeps only the first step.
6. Start the run.

The wake banner looks like this (the home directory in the path is replaced with `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` is always there; `目标 N 条` appears only when a verdict checklist exists;
`干活上下文 X` requires the last-round context of that [session](glossary.md#会话) to be findable
in `sessions.db` — if it is not, it is not shown.

!!! warning "`-W` and `-T` are silently overridden on the `go` path"
    Setting these two global flags on `go` does nothing, with no error and no notice:

    - `-W/--workbench`: the workflow that `go` builds always carries its own
      [workbench](glossary.md#工作台), and the code reads
      `getattr(wf, "workbench", None) or args.workbench` (`cli.py:859`) — the workflow's own one
      always wins. So the workbench is always `<workspace>/.flower/`
      (or `<workspace>.parent/.flower-<name>/` under `--isolate`), and `-W` cannot change it.
    - `-T/--trim`: `go` calls `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1042`), using the
      negation of `--no-trim` directly and **never looking at `args.trim`**. In other words,
      [trim](glossary.md#裁剪) is on by default on the `go` path, and the only way to turn it off
      is `--no-trim`.

    These two flags take effect only on `run` (when the workflow does not carry its own workbench)
    and on `once`.

#### The 11 flags of `go` {#go-的-11-个开关}

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `--asks N` | int | `-1` | Question quota. `-1` or any negative = **unlimited**; `0` = no questions allowed, the first question becomes `over_budget`; `N` = a hard quota. Over quota the tool simply refuses; it does not block the run |
| `--rounds N` | int | `3` | Upper bound on the **total number** of work rounds, not extra rounds. At the end of each round an independent [judge](glossary.md#判定者) decides "is it done", and if not it is sent back to continue on the same session |
| `--no-goal` | flag | `False` | Turn off the [goal guard](glossary.md#目标看守): no `目标.md` is generated, no [verdict](glossary.md#判定) is made, and the run is finished as soon as the work step finishes |
| `--judge-can-run` | flag | `False` | Let the judge run commands. The verdict gets tougher, at the price that it can now also modify the workspace |
| `--timeout SECONDS` | float | `1800.0` | How long to wait for a human answer. `0` or negative = fully automatic, every question falls through **immediately** without pretending to wait. See [Timeout](#超时) for the semantics |
| `--isolate` | flag | `False` | Give each [subagent](glossary.md#subagent) its own git worktree, i.e. [isolation](glossary.md#隔离). **Requires the workspace to be a git repo**, otherwise exit code 1. Also moves the workbench outside the repo |
| `--window N` | int | none (inferred from the model name) | Model context window. If not given: model name contains `1m` or does not contain `haiku` → 1,000,000; contains `haiku` → 200,000. At `window − 50000` it writes a [handoff document](glossary.md#交接书) and does a [handoff](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Turn off handoff and fall back to the SDK's own [compact](glossary.md#压缩) |
| `--new` | flag | `False` | Do not continue from last time. **Move** (not delete) the previous段's `lineage.json` + `需求.md` + `目标.md` into `notes/archive/<YYYYmmdd-HHMMSS>/`, then start from scratch |
| `--clarify-only` | flag | `False` | Only do the [clarify](../guide/clarify.md) step, no work afterwards — the workflow keeps only the `确认需求` step |
| `--no-trim` | flag | `False` | Turn off trim. On the `go` path trim is **on** by default, and this is the only way to disable it |

Edge cases in the values — none of which produce an error or a notice:

- `--rounds 0` and `--rounds 1` are equivalent — internally it is `retries = max(0, rounds - 1)`,
  so both run 1 round.
- Any negative value of `--asks` means unlimited, not just `-1`.
- Any negative value of `--timeout` is the same as `0`, i.e. fully automatic.
- `--window 0` is **silently ignored** (`0` is falsy and is never passed down), falling back to the
  default inferred from the model name. Negative values are passed down and then floored to `10000`.
- `--clarify-only` is a **no-op** in a directory that has already been clarified — the `确认需求`
  step sees a complete `需求.md` and skips itself, and since that is the only step in the workflow,
  nothing happens at all (except the wake count going up by 1). To re-clarify, combine it with
  `--new`.
- The `--help` of `go` ends with "全局开关(-v/-w/-r/-T)见 `flower --help`" — that line **omits
  `-W`**.

### `run` {#run}

Help text: `运行一个 workflow` (`cli.py:1130-1133`).

Positional argument `target`, written as `module:attribute`. Both forms are supported
(`cli.py:831-852`):

```bash
flower run mypkg.flows:build     # import by module name
flower run flows.py:build        # file path; the parent directory is put on sys.path and it is imported by file name
```

If the resulting attribute is callable it is called once and the return value is used as the
[workflow](glossary.md#流程); if it is already a workflow object it is used directly.

**`run` has no flags of its own**, only the 5 global ones. So `--window`, `--no-handoff` and the
rest all take their defaults on this path (the code falls back with `getattr`, `cli.py:862-864`).
To adjust them, put the parameters into your own workflow.

### `once` {#once}

Help text: `跑一次单 agent` (`cli.py:1135-1145`). The positional argument `prompt` is required.

It builds an `AgentSpec(name="ad-hoc", …)` and runs it directly, **without going through
`_drive`**. So on `once` there is no:

- Ctrl-C to interrupt and speak (pressing it is a plain `KeyboardInterrupt`)
- stdin answering thread, no persistent input prompt at the bottom
- oracle Q&A
- SIGHUP / SIGTERM rescue accounting
- closing line `总花费 … · 清单 …`
- automatic reconfiguration guidance after a credential failure

In the [run manifest](glossary.md#运行清单), the name of this step is always `ad-hoc`.

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `-i`, `--instructions` | str | empty | Domain instructions, [appended](glossary.md#叠加) **after** Claude Code's native system prompt, not replacing it |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Comma-separated tool allowlist. If not given, these three read-only tools |
| `-p`, `--permission-mode` | str | `default` | Must be one of `default`, `acceptEdits`, `plan`, `bypassPermissions`; any other value makes argparse fail with exit code 2 |
| `-b`, `--budget` | float | no limit | Dollar [budget](glossary.md#预算) cap; the run stops when exceeded |
| `--resume SESSION_ID` | str | none | Continue an existing session |
| `--fork` | flag | `False` | Fork instead of continue, used together with `--resume` |

!!! warning "The elapsed time and cumulative cost shown by `once` are always 0"
    `once` creates a new renderer instance for every event it receives (`cli.py:579-581`,
    `cli.py:1060`), while the timing origin and cumulative cost live on the instance
    (`cli.py:393-394`). Therefore:

    - The `用时` on the closing line is always `0:00`
    - The `累计 $0.00` in the status line is always 0, and `上下文` never accumulates either

    The real cost of the single step has to be read from the `cost_usd` field in
    `runs/manifest.json`. The `go` and `run` paths hold a single renderer instance and do not have
    this problem.

### `setup` {#setup}

Help text: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1147-1149`).
It has no flags.

What it does: read `.env` → decide whether it has been configured → start the interactive
configuration flow, with `reason` being either `重新配置。` or `还没配过凭证。`. For what appears on
screen, see [First-run configuration flow](#首次运行的配置流程).

!!! warning "`flower setup` currently cannot reach this subcommand"
    The constant used to decide the default subcommand, `_CMDS = ("go", "run", "once")`
    (`cli.py:758`), **omits `"setup"`**, even though `setup` really is registered on the parser
    (`cli.py:1147`). So `flower setup` gets rewritten into `flower go setup` — **it runs the full
    `go` workflow with the request text being the string `setup`**: first credentials are
    validated, then it clarifies the request, and then it genuinely starts dispatching workers.
    Global flags make no difference: `flower -v setup` → `["-v", "go", "setup"]`.

    **No argv whatsoever can reach the `setup` subcommand.**

    To configure credentials there are only these two routes today, both of which reach the same
    interactive screen:

    - Just run `flower "some request"`; if credentials have never been configured it will ask first;
    - Or hand-write `~/.config/flower/.env`; for the key names see [The keys it writes](#写出来的键).

    A few pieces of copy are affected too: the ``跑 `flower setup` 重配。`` printed when credentials
    are rejected, and the first-line comment of `.env`, ``由 `flower setup` 写``, both point at this
    unreachable command.

---

## Global flags {#全局开关}

The 5 global flags are attached both to the main parser and to every subcommand
(`cli.py:1071-1087`). The copies on the subcommands use `argparse.SUPPRESS`, so if not given they
write no attribute — which means **they can be written before or after the subcommand** without
overriding each other. The side effect is that they do not show up in a subcommand's `--help`; for
that you have to run `flower --help`.

| Flag | Type | Default | Meaning |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | The agent's working directory. It is `resolve()`d to an absolute path and `mkdir -p`ed. The [workbench](glossary.md#工作台) `.flower/` is created inside it |
| `-r`, `--run-dir` | str | `runs` | Directory for the [session store](glossary.md#会话存储) and the run manifest. **Relative to the current CWD, not to the workspace** |
| `-v`, `--verbose` | flag | `False` | Print more; see below |
| `-W`, `--workbench` | flag | `False` | Enable the workbench. **Has no effect on `go`**; it only applies to `run` (when the workflow does not carry its own workbench) and `once`, where the workbench lands in `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | On resume, replace old large tool results with file pointers, i.e. [trim](glossary.md#裁剪). **Has no effect on `go`**; that path is controlled inversely with `--no-trim` |
| `-h`, `--help` | flag | — | Present on every parser. When it appears in argv, the default-subcommand rewrite is skipped and help is printed directly |

The fact that `-r/--run-dir` is relative to CWD will bite: `flower -w /other/proj "做 X"` creates
`runs/` in **the directory you typed the command in**, while `.flower/` is created under
`/other/proj/` — two halves of the state, split apart. To keep them together, pass
`-r /other/proj/runs` explicitly.

The help for `-v` says "显示思考与工具结果", but the [main thread](glossary.md#主线程)'s thinking is
**shown by default**. What `-v` actually turns on in addition is:

- subagent body text (hidden by default; only its tool calls are shown)
- normal tool results (by default only failing ones are shown)
- `prompt` events
- a dump of the currently effective credential configuration before starting, with the token masked
  to its first 4 characters

That last one goes through a bare `print()`, **bypassing output sanitization, without wrapping and
unprotected by the terminal write lock** — running several `flower`s in parallel can tear these
lines apart.

---

## How to talk to it while it runs {#运行中怎么和它说话}

Once a run has started, the terminal **is reading your input the whole time**. You do not have to
wait for it to ask you something, and you do not have to press any key to enter an input mode — the
last line is always the one you can type on.

### The input prompt that stays at the bottom {#常驻在最下面的输入提示符}

A daemon thread `flower-stdin` reads stdin for the entire run (`cli.py:655-755`), polling with
`select` every 0.2 seconds rather than blocking (so a stop signal can wake it; on streams that do
not support `select`, such as on Windows, it degrades to a blocking read).

**It reads all the time, not only when there is a question.** The reason: if it only read while a
question was pending, whatever you typed during those hours of work would sit in the terminal
buffer and be eaten as the answer to the next question — the question would be answered before you
had even seen it.

For display, `_say()` is the single output channel; before each write it erases the prompt and
redraws it afterwards (`cli.py:299-305`), so the prompt never gets pushed up the screen by event
output. The prompt has two variants, switching on whether a question is pending:

| State | Last line on screen |
|---|---|
| A question is pending | `你的回答 (回车=跳过,让它自己判断) > ` |
| No question pending | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Where what you type goes {#你敲的东西去哪了}

| You type | With a question pending | With no question pending |
|---|---|---|
| **Empty line (bare Enter)** | Skip this question, let it decide for itself | Nothing |
| **Starting with `?`** | Oracle Q&A, see below | Same |
| **Pure digits**, within the option range | Replaced with the corresponding option, then submitted as the answer | Treated as plain text |
| Any other text | Delivered as the answer to the asking agent | Goes to the inbox as an appended requirement |
| EOF (Ctrl-D or the pipe closing) | Refuse this question, remove the prompt, thread exits | Remove the prompt, thread exits |

When it goes to the inbox, a receipt line is printed:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

When there is no [brief](glossary.md#需求确认书) to spill to, the second half becomes
`没有确认书可落盘 —— 它可能活不过下一个步骤`. The inbox **does not interrupt** the worker that is
running; it is only picked up the next time the worker checks the inbox on its own. The same
sentence is also appended to `notes/需求.md`; without being spilled it would not survive the step
boundary — the next step is a new session that only reads the frozen files.

### Starting with `?` = oracle Q&A {#旁路问答}

A line starting with `?` is not delivered to the running agent but handed to the
[oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

It starts an **independent** Runtime whose `run_dir` is `<run_dir>/aside/`, so its cost and session
lineage never mix into the main `manifest.json`. The role is read-only, its tools are only `Read`,
`Glob`, `Grep`, at most 12 turns, with a cost cap of **$0.5**. The context it sees is the most
recent **60** events (`thinking` and `prompt` events do not enter this window), each truncated to
200 characters, plus a description of the workbench paths.

It runs **concurrently**; the running run does not wait a single second. The answer looks like this:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

On failure it prints one red line `# 旁路问答失败:<类型>: <消息>`, **without affecting the main
workflow**. On exit it waits at most **120** seconds for oracles to finish, printing
`(等 N 条旁路问答收尾…)` before it waits.

What it says never enters the context of that run — asking does not affect the run, and the answer
is discarded once given.

!!! warning "A full-width `？` does not trigger oracle Q&A — Chinese IME users will hit this"
    The line of code that decides on oracle Q&A is (`cli.py:733`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Both characters are **the half-width ASCII `?`** (`0x3f`) — verified byte by byte. From the way
    it is written the intent was obviously to accept both a half-width `?` and the full-width `？`
    (U+FF1F) produced by a Chinese IME, but it was actually written as the same character twice.

    Consequence: **a line starting with a full-width `？` is not treated as an oracle question**;
    it is silently treated as an "appended requirement", sent to the inbox and then appended to
    `notes/需求.md`. The receipt you see is `+ 收到`, not `# 旁路`.

    To ask the oracle you **must use the half-width `?`** — switch your IME to English first, or at
    least type that first character half-width.

### What is on the screen {#屏幕上都是什么}

The icons are **all ASCII**, not emoji (`cli.py:49-67`). The reason is in a code comment: emoji
together with box-drawing, geometric and arrow characters trigger terminal glyph fallback, which
once crashed the terminal twice.

| Icon | Meaning | Icon | Meaning |
|---|---|---|---|
| `=` | Step separator | `+` | Done / answered / received |
| `~` | Thinking, retry | `x` | Failure / error |
| `>` | Dispatch | `#` | Handoff, oracle, task |
| `*` | Tool call | `-` | Status line, list item |
| `?` | Question | `<-` | Continuity, handoff landing point |
| `!` | Warning / interrupt | `.` | Skipped |
| `\| ` | Indent bar for a subagent | | |

!!! warning "The `❓` and `↩` in older docs do not exist in a real terminal"
    Early documentation used `❓` for questions and `↩` for the wake line. **The code never used
    those two characters** — the question icon is the half-width `?`, and the icon for wake and for
    handoff landing points is the two ASCII characters `<-`.

    So what a real terminal prints is:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    Not `❓ 这个工具……`, and not `↩ 在 ~/proj 接上上次`. Grepping your logs based on the old docs
    will find nothing.

The five states of a question, as they appear on screen:

| State | Screen output |
|---|---|
| Asked | `  ? <问题>`, followed by one line per option, `     1) 选项一`, plus `     (还能问 N 次)` when there is a quota |
| Answered | `  + <答案>` |
| Timed out | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Quota exhausted | `  ! 提问额度用完` |
| You skipped it | `  . 已跳过` |

When `--asks` is unlimited (the default), the trailing "还能问 N 次" line is not shown.

When a [handoff](glossary.md#换代) writes the handoff document, it is one whole block:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

When the handoff document degrades, an extra red line is inserted:
`交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

Output also does two things you never see: every output line is sanitized first, **letting through
only flower's own SGR color codes**, so screen-clearing and cursor-moving sequences emitted by the
model or a tool are swallowed whole; and the width is `max(40, min(terminal columns, 110))`, so on
a wide terminal it does not fill the entire line — that is deliberate.

### The prompt at startup {#起跑时的提示符}

Running `flower` bare (with no request) asks you first. Two variants:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

The second only appears when this directory has already been run in and `需求.md` has all four
sections.

This prompt reads via `input()`, **without going through shell parsing**. Chinese quotation marks,
spaces and exclamation marks can all be typed directly — that is the entire reason it exists. zsh,
faced with a Chinese closing quotation mark, drops into a `dquote>` continuation and looks like it
is stuck, when in fact it never started at all.

- Empty input + first time → exit, printing ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Empty input + wake → **legal**, it means "keep going"
- Entering `/new` → equivalent to `--new`; after archiving the previous段 it **asks again** for the request
- Ctrl-C / Ctrl-D → exit, printing `已取消`

### Timeout {#超时}

`--timeout` is a float in seconds, defaulting to `1800.0`. Three kinds of value:

| Value | Behavior |
|---|---|
| `> 0` | Wait that many seconds. On timeout the question settles as `timeout` and the agent decides for itself |
| `0` or negative | **Fully automatic**. Questions do not enter the wait queue, no `asked` event is emitted, nothing appears on screen, and they settle as `timeout` immediately |
| Wait forever | **Not reachable from the command line.** Internally "wait forever" is supported, but `--timeout` is a float with a default, and no spelling can produce it. The ceiling is simply to pass a very large number of seconds |

`--timeout 0` and `--timeout -1` are exactly equivalent. Piped runs, CI runs, unattended runs all
use this.

When a question gets no answer, the tool result fed back to the model is fixed copy, of four kinds:

| Result | Copy fed back to the model |
|---|---|
| Quota exhausted | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| You skipped | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| Question was empty | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**Ctrl-C means two completely different things in two places.**

**Pressed at the startup prompt `> `** — exits the program immediately, printing `已取消`.

**Pressed during a run** — interrupts the current round and gives you a chance to say something:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Pressing Enter here means interrupt without saying anything, and keep going. If a question was
pending at the time, an extra line is printed: `  (有 N 个提问还等着,打断不影响它们)`.

**Pressing Ctrl+C a second time really does exit**, and as an uncaught `KeyboardInterrupt` — you
will get a Python traceback on screen, not a clean exit.

The interrupt is cooperative: it cuts cleanly at a message boundary and does not hard-cancel tasks.
It **does not count as a failed attempt** and does not consume a retry. On resume a note is
attached telling the model that "an in-flight tool call returning interrupted is a normal side
effect of the interrupt, not an environment failure".

This custom Ctrl-C handling is only installed when `sys.stdin.isatty()` (`cli.py:918`). In a pipe,
Python's default behavior is kept, i.e. the first press exits. The `once` path does not go through
here, so Ctrl-C on `once` also exits on the first press.

### SIGHUP / SIGTERM {#sighup-sigterm}

The `go` and `run` paths install handlers for both `SIGHUP` and `SIGTERM`: first the
**in-flight step** is also written into `manifest.json`, marked `killed-by-signal`, and then the
default action is restored and the process really does leave.

The reason: when a terminal crashes the kernel sends SIGHUP, whose default action terminates the
process outright — `finally` never runs, the manifest is never written, and the accounting for a
whole run is lost. On a non-main OS thread or a platform that does not support it, this is silently
skipped.

---

## First-run configuration flow {#首次运行的配置流程}

All three entry points `go`, `run` and `once` call `ensure_credentials()` at the start
(`cli.py:1213-1244`), which is **two gates**.

### Gate one: are there credentials {#第一道-有没有凭证}

It looks for credentials in priority order. If neither `ANTHROPIC_API_KEY` nor
`ANTHROPIC_AUTH_TOKEN` is found, it starts interactive configuration; in a non-interactive context
(stdin is not a terminal) it does not block, and simply prints this and exits:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Two parts of this copy do not match the implementation: the `flower setup` on the second line is
currently unreachable (see [`setup`](#setup)); and the fourth line **says the opposite of the
code** — flower really does treat the `env` block of `~/.claude/settings.json` and
`settings.local.json` as a **last-level fallback**, borrowing only 9 credential keys from it and
taking over no other setting. The place that prints this line is `env.py:192` (the function
`check_credentials()` is defined at `env.py:184`), while the code that actually reads those two
files is `env.py:56-75` and `:109-111`; recorded as
[issue #13](https://github.com/ChenyuHeee/flower/issues/13).
**The code is authoritative: it does read them.** The full lookup priority and those 9 keys are in
the [configuration reference](config.md#借用).

### What interactive configuration asks {#交互配置问什么}

```text
== 配置 flower ========================================
<为什么要配这一行>
凭证会存到 /Users/you/.config/flower/.env(只你可读)。装一次,处处生效。

1. 你的 API key 或网关 token (Anthropic 官方的 sk-ant-… 或第三方网关签发的)
   > 

2. 网关地址 (直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL)
   > 

3. 模型名 (直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m])
   > 

+ 存好了:/Users/you/.config/flower/.env
```

- Question 1 is **mandatory**. Leaving it blank prints the red line `没给 token,取消。` and gives
  up on configuration.
- Questions 2 and 3 may be left blank.
- When stdin is not a terminal the whole flow is skipped without blocking.

### The keys it writes {#写出来的键}

| What you entered | Key it is written as |
|---|---|
| Token starting with `sk-ant-` | `ANTHROPIC_API_KEY` |
| Any other token | `ANTHROPIC_AUTH_TOKEN` |
| Non-empty gateway address | `ANTHROPIC_BASE_URL` |
| Non-empty model name | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, all three at once |

The file path is `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, and the parent directory is created
automatically. It is written as a **full overwrite**, keys with empty values are skipped, it is
`chmod 0600`ed afterwards, and it takes effect immediately — no need to restart your shell. The
first line is always a comment reminding you not to commit it to version control.

### Gate two: do the credentials work {#第二道-凭证能不能用}

Once configuration is complete, it prints `- 验一下凭证…` and then **actually fires one API call**.

Details of the probe: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, default timeout 20 seconds,
using stdlib `urllib` so it pulls in no dependency. The model is taken in the order
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. If
`ANTHROPIC_API_KEY` is present it uses the `x-api-key` header, otherwise
`authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` is deliberately 16 rather than 1: in practice a model with forced chain-of-thought
cannot even fit its thinking into that, and the server struggles for 30 seconds before returning;
with 16 it takes only 3.6 seconds.

The probe's conclusions are handled in three classes, and **the differences matter**:

| Conclusion | Trigger | What flower does |
|---|---|---|
| `auth` | HTTP 401 / 403, or no credentials at all | Prints `! 凭证被拒:<first 160 chars of the body>`, starts interactive reconfiguration, and probes again afterwards. Non-interactive: exit code 1 |
| `config` | HTTP 404, or 400 with `model` mentioned in the body | Prints `! 网关地址或模型名不对:<…>`, then as above |
| `net` | Cannot connect / timeout / DNS failure / TLS failure / 5xx | Prints `  (探针没打通:<first 80 chars> —— 当作网络问题,照常开跑)`, **does not make you reconfigure, just starts the run** |
| `ok` | Below 400, or anything undecidable, which is let through | Silently continues |

The `net` case is deliberate: a network blip should not force you to retype your token, and flower
itself has a mechanism to suspend and reconnect when the network drops. Seeing "探针没打通" needs no
action; just keep going.

You get **at most one** reconfiguration chance. A second failure exits.

### Automatic reconfiguration after a crash {#跑挂了之后的自动重配}

When a workflow fails, flower matches the error message of the failing step against a regex (401,
`invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). On a match, and if
stdin is a terminal, it prints `! 看起来是凭证不对:<first 120 chars>` right there and starts
interactive configuration; once configured it prints:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

and then exits with code 1 regardless. The `once` path does not have this.

---

## Exit codes {#退出码}

| Code | When |
|---|---|
| `0` | Finished normally |
| `1` | Every deliberate exit. The message goes to **stderr**, with no traceback. Full list below |
| `2` | argparse argument error: unknown flag, missing positional, or a value for `-p` outside its choices |
| `130` | Two Ctrl+C presses in a row during a run. An uncaught `KeyboardInterrupt`, **with a Python traceback** |
| Killed by signal | SIGHUP / SIGTERM: the in-flight step is written to the manifest first, then the default action is taken |

All the messages behind exit code 1:

| Message | When |
|---|---|
| `已取消` | Ctrl-C or Ctrl-D at the startup prompt |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Brand new directory + bare Enter |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 lines total) | Non-interactive + no credentials |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe verdict `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe verdict `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` used in a non-git directory |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Request is empty and the directory has no wake state |
| `在步骤 '<步骤名>' 中止` | A step in the workflow failed and the policy is to stop |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, missing the colon |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | The target module failed to import |
| `'<模块>' 里没有 '<属性>'` | The attribute was not found in the module |

At the end of a run (the `go` / `run` paths) a final line is printed:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

This amount counts only **this process's** cost, not the previous run's — even though the manifest
file itself accumulates across processes.

---

## What it creates in your project {#它在项目里创建了什么}

Two trees: `<run_dir>/` (default `./runs/`, relative to CWD) holds accounting and sessions;
`<workspace>/.flower/` holds the [workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Path | What it holds |
|---|---|
| `runs/sessions.db` | SQLite, the full transcript. This is the material basis that makes [continuity](glossary.md#接续) possible |
| `runs/manifest.json` | The [run manifest](glossary.md#运行清单). A JSON array, **accumulated across processes**; every number on the case-study pages can be recomputed from here |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Written by atomic replace |
| `runs/aside/` | The oracle's independent Runtime, with its own `sessions.db` and `manifest.json`. **Its cost and lineage never mix into the main manifest** |
| `runs/workbench/` | Only appears when `-W` was used and the workflow does not carry its own workbench (the `run` / `once` paths) |

The fields of each record in `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` marks this process, in the format `YYYYmmdd-HHMMSS-<6 hex digits>`. The write strategy is
**append, never overwrite**: before each write the file is re-read and deduplicated by `run` — rows
belonging to this process are replaced with the latest ones, rows from other processes are left
untouched.

Step names come in four shapes:

| Shape | When |
|---|---|
| `<步骤名>` | First attempt |
| `<步骤名>#retry<N>` | Ordinary retry |
| `<步骤名>#round<N>` | Sent back by a failed verdict to keep going |
| `<步骤名>·判定#<N>` | The [judge](glossary.md#判定者) step |

When killed by a signal, the in-flight step is written too, with `error` set to `killed-by-signal`.

**Running several flowers in parallel in the same directory**: `manifest.json` is safe (re-read
plus merge by `run`), but `lineage.json` is a full overwrite, so two processes will clobber each
other's lineage for steps with the same name. To run in parallel, use different `-r`.

`lineage.json` stores the absolute path of the workspace. If it does not match, it is treated as
absent and it **silently** falls back to a new session, with no error — after a directory has been
copied elsewhere, the old `session_id` could not be looked up anyway.

### `.flower/` {#flower-目录}

| Path | What it holds |
|---|---|
| `.flower/scripts/` | Scripts that will be run a second time. The first line reads `# desc: one sentence`, and that sentence appears in the index |
| `.flower/artifacts/` | Long outputs over 2000 characters: reports, data, logs. Only the path appears in the conversation |
| `.flower/notes/` | Cross-step decision records |
| `.flower/spill/` | [Spill](glossary.md#落盘): tool results over 4000 characters land here, and only a one-line pointer plus the first 400 characters remain in context. The file name is the first 16 digits of the content's sha256 plus `.txt` |
| `.flower/INDEX.md` | An index of the directories above, **injected into the coordinator's system prompt** (subagents do not inherit it) |

The `go` path always generates these under `notes/`:

| File | Contents |
|---|---|
| `notes/需求.md` | The frozen [brief](glossary.md#需求确认书), four sections: goal / acceptance criteria / boundaries / unknowns and assumptions |
| `notes/目标.md` | The frozen goals, two sections: goals / verdict checklist |
| `notes/问答记录.md` | An append-only record of every question and answer (including status), and of anything you said on your own initiative. **Not part of the context, kept purely as a record** |
| `notes/交接-<步骤名>.md` | The [handoff document](glossary.md#交接书) written at handoff time; the previous generation is filed into `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | The `lineage.json`, `需求.md` and `目标.md` archived by `--new` or `/new`. They are **moved**, not deleted |

With `--isolate` the workbench moves outside the repo: `<workspace>.parent/.flower-<workspace name>/`.
A worktree is each agent's private copy while the workbench is a shared layer across agents, and
shared things cannot live inside a private fence. In this case the workbench path given to the
model is absolute.
