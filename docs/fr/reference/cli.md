# Command-line reference

Once installed, `flower` is a single executable with 4 subcommands and 23 flags. This page lists
them all: the type, default value and exact semantics of every flag, plus how to talk to a run
while it is going, what the first run asks you, what the exit codes are, and which files it puts
in your directory. After reading this page you should not need to open the source.

Source: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcommand | What it does | Positional args | Own flags |
|---|---|---|---|
| `go` | The whole chain: clarify the request → set goals → dispatch workers → judge every round. The default when no subcommand is written | `ask` (optional) | 11 |
| `run` | Runs a [workflow](glossary.md#流程) you wrote yourself | `target` (required) | 0 |
| `once` | Runs a single agent once, no workflow, no verdict | `prompt` (required) | 6 |
| `setup` | Configures credentials, writes to `~/.config/flower/.env` | none | 0 |

Total of 23 flags = 5 global + 11 specific to `go` + 6 specific to `once` + `-h/--help`. `run` and
`setup` have no flags of their own.

---

## Invocation forms {#调用形式}

All of `flower`'s argv goes through `_with_default_cmd()` first to fill in the default subcommand,
then to argparse (`cli.py:1253-1255`). That is why `flower "build me an X"` works — it gets
rewritten into `flower go "build me an X"`.

The rules for filling in the default subcommand (`cli.py:761-797`):

1. The set of global flags is **derived from the main parser itself**, not a hardcoded list.
   Those with `nargs == 0` count as pure flags, the rest as flags that take a value.
2. Scan left to right, skipping global flags. Those that take a value are skipped together with
   the value; the `--workspace=/tmp` form with `=` is also recognised.
3. Stop at the first token that is not a global flag. If it is one of `go`, `run`, `once`, hand it
   to argparse as is; **otherwise insert a `go` in front of it**, so it becomes the body of `go`'s
   request.
4. Scanned everything without hitting a positional (empty argv, or global flags only) → append
   `go` at the end and go to interactive input.
5. Exception: if argv contains `-h` or `--help`, return it unchanged and let argparse print help.

The constant used for the check is `_CMDS = ("go", "run", "once")` (`cli.py:758`) — **`setup` is
not in it**; for the consequences see [`setup`](#setup).

### What the rewrite actually produces {#实际的改写结果}

| What you type | What it actually parses as | Effect |
|---|---|---|
| `flower` | `["go"]` | Asks interactively "What do you want done?" |
| `flower -v` | `["-v", "go"]` | Same, with verbose |
| `flower "build me an X"` | `["go", "build me an X"]` | Starts right away |
| `flower -w /tmp "do X"` | `["-w", "/tmp", "go", "do X"]` | Global flags may go in front |
| `flower --workspace=/tmp "do X"` | `["--workspace=/tmp", "go", "do X"]` | The `=` form is recognised too |
| `flower "do X" --timeout 0` | `["go", "do X", "--timeout", "0"]` | Subcommand flags may go after the request |
| `flower --timeout 0 "do X"` | `["go", "--timeout", "0", "do X"]` | Or in front |
| `flower --new` | `["go", "--new"]` | Flags only, no request → interactive input |
| `flower once "hi"` | `["once", "hi"]` | Unchanged |
| `flower run flows:main` | `["run", "flows:main"]` | Unchanged |
| `flower run` | `["run"]` | argparse reports the missing `target`; it will **not** be treated as a request |
| `flower go run` | `["go", "run"]` | Explicit disambiguation: the request body is literally `run` |
| `flower setup` | `["go", "setup"]` | It runs `go`, and the request becomes the string `setup`; see [`setup`](#setup) |
| `flower --help` | Unchanged | argparse prints help |

The two words `run` and `once` **cannot** be used directly as a request body; this is a deliberately
preserved ambiguity (`cli.py:770-771`). To use them as a request, write `flower go run`.

### Six usable forms {#六种能用的写法}

```bash
flower                                    # 1. Bare: asks "What do you want done?" or "Continue from last time?"
flower "build me an X"                     # 2. Request as positional argument
echo "build me an X" | flower --timeout 0  # 3. Feed stdin through a pipe
flower once "take a look at this repo"     # 4. Single agent
flower run flows.py:main                  # 5. Run a custom workflow
flower go setup                           # 6. Explicit go, with setup as the request body
```

The module form `python -m flower.cli` is equivalent to `flower` (`cli.py:1263-1264`).
The container wrapper `docker/flowerbox` takes exactly the same arguments as `flower`.

### Feeding stdin through a pipe {#管道喂-stdin}

When `sys.stdin.isatty()` is false, `ask_for_prompt()` **does not print the prompt header** and
just does `input("> ")` to read a line (`cli.py:814-822`). So `echo "..." | flower` works.

But it then prints a warning, and the stdin thread immediately hits EOF and exits:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

Piped runs should use `--timeout 0`: questions no longer pretend to wait 30 minutes, they fall
through immediately, the agent decides on its own and writes its assumptions into the "unknowns and
assumptions" section of the brief.

---

## Subcommands {#子命令}

### `go` {#go}

Help text: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1096-1128`).

Positional argument `ask`, `nargs="?"` — omit it and you get interactive input. This is the most
common entry point; `flower "do X"` goes through it.

What it does (`cli.py:1011-1042`):

1. `ensure_credentials()` — checks credentials, and actually fires an API probe; see
   [First-run configuration flow](#首次运行的配置流程).
2. [Wake](glossary.md#唤醒) detection: read-only look at whether this directory has been used
   before, without writing a single byte.
3. If no `ask` was given, print a prompt and ask; entering `/new` is equivalent to `--new`, and then
   it **asks again** for the request.
4. If this is a [continuity](glossary.md#接续), print a wake banner.
5. Build a three-step [workflow](glossary.md#流程): `确认需求` → `设定目标` → `干活`, with a
   `干活·判定#N` after each work round. `--clarify-only` keeps only the first step.
6. Start running.

The wake banner looks like this (the home directory in paths is replaced with `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` is always there; `目标 N 条` appears only when there is a verdict checklist;
`干活上下文 X` requires that the last-round context of that [session](glossary.md#会话) can be found
in `sessions.db` — if not, it is not shown.

!!! warning "`-W` and `-T` are silently overridden on the `go` path"
    Writing these two global flags on `go` does nothing; no error, no notice:

    - `-W/--workbench`: the workflow `go` builds always comes with its own
      [workbench](glossary.md#工作台), and the code reads
      `getattr(wf, "workbench", None) or args.workbench` (`cli.py:859`) — the workflow's own copy
      always wins. So the workbench is always `<workspace>/.flower/`
      (or `<workspace>.parent/.flower-<name>/` with `--isolate`), and `-W` cannot change it.
    - `-T/--trim`: `go` goes through `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1042`),
      using the negation of `--no-trim` directly and **never looking at `args.trim`**. That is,
      [trim](glossary.md#裁剪) is on by default on the `go` path, and the only way to turn it off is
      `--no-trim`.

    These two flags only take effect on `run` (when the workflow does not carry its own workbench)
    and `once`.

#### The 11 flags of `go` {#go-的-11-个开关}

| Flag | Type | Default | Description |
|---|---|---|---|
| `--asks N` | int | `-1` | Question quota. `-1` or any negative = **unlimited**; `0` = no questions allowed, the first question is `over_budget`; `N` = hard quota. When over quota the tool refuses outright, without blocking the run |
| `--rounds N` | int | `3` | Upper bound on the **total number** of work rounds, not extra rounds. At the end of each round an independent [judge](glossary.md#判定者) decides "is it done"; if not, it is sent back to continue on the same session |
| `--no-goal` | flag | `False` | Turns off the [goal guard](glossary.md#目标看守): no `目标.md` is generated, no [verdict](glossary.md#判定) is made, and the run is done once the work finishes |
| `--judge-can-run` | flag | `False` | Lets the judge run commands. Verdicts get harder, at the cost of it also being able to modify the workspace |
| `--timeout SECONDS` | float | `1800.0` | How long to wait for a human answer. `0` or negative = fully automatic, all questions fall through **immediately** without pretending to wait. Semantics in [Timeout](#超时) |
| `--isolate` | flag | `False` | Gives each [subagent](glossary.md#subagent) its own git worktree, i.e. [isolation](glossary.md#隔离). **Requires the workspace to be a git repo**, otherwise exit code 1. Also moves the workbench outside the repo |
| `--window N` | int | none (inferred from model name) | Model context window. When not given: model name contains `1m` or does not contain `haiku` → 1,000,000; contains `haiku` → 200,000. At `window − 50000` it writes a [handoff document](glossary.md#交接书) and does a [handoff](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Turns off handoff, falling back to the SDK's built-in [compact](glossary.md#压缩) |
| `--new` | flag | `False` | Do not continue from last time. **Moves** (not deletes) the previous segment's `lineage.json` + `需求.md` + `目标.md` into `notes/archive/<YYYYmmdd-HHMMSS>/`, then starts fresh |
| `--clarify-only` | flag | `False` | Only do [clarify](../guide/clarify.md), do not proceed to work — the workflow keeps only the `确认需求` step |
| `--no-trim` | flag | `False` | Turns off trim. On the `go` path trim is **on** by default, and this is the only way to turn it off |

Edge cases in the values, none of which produce an error or a notice:

- `--rounds 0` and `--rounds 1` are equivalent — internally it is `retries = max(0, rounds - 1)`,
  both run 1 round.
- Any negative value of `--asks` means unlimited, not just `-1`.
- Any negative value of `--timeout` equals `0`, i.e. fully automatic.
- `--window 0` is **silently ignored** (`0` is falsy and is never passed down), falling back to the
  default inferred from the model name. Negative values are passed down, then floored at `10000`.
- `--clarify-only` is a **no-op** in a directory that has already been clarified — the `确认需求`
  step sees a complete `需求.md` and skips itself, and since it is the only step in the workflow,
  nothing happens at all (except the wake count going up by 1). To re-clarify, combine it with
  `--new`.
- The end of `go`'s `--help` says "全局开关(-v/-w/-r/-T)见 `flower --help`" — that line
  **omits `-W`**.

### `run` {#run}

Help text: `运行一个 workflow` (`cli.py:1130-1133`).

Positional argument `target`, written as `module:attribute`. Both forms are supported
(`cli.py:831-852`):

```bash
flower run mypkg.flows:build     # Import by module name
flower run flows.py:build        # File path; the parent directory is put on sys.path and it is imported by file name
```

If the resolved attribute is callable it is called once and the return value is used as the
[workflow](glossary.md#流程); if it already is a workflow object it is used directly.

**`run` has no flags of its own**, only the 5 global ones. So `--window`, `--no-handoff` and friends
always take their default values on this path (the code falls back with `getattr`,
`cli.py:862-864`). To adjust them, put the parameters into your own workflow.

### `once` {#once}

Help text: `跑一次单 agent` (`cli.py:1135-1145`). The positional argument `prompt` is required.

It builds an `AgentSpec(name="ad-hoc", …)` and runs it directly, **without going through `_drive`**.
So `once` does not have:

- Ctrl-C interrupt-and-speak (pressing it is a plain `KeyboardInterrupt`)
- The stdin answering thread, or the input prompt permanently at the bottom
- Oracle Q&A
- SIGHUP / SIGTERM rescue accounting
- The closing line `总花费 … · 清单 …`
- The automatic reconfiguration guidance after a credential failure

In the [run manifest](glossary.md#运行清单), this step's name is always `ad-hoc`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-i`, `--instructions` | str | empty | Domain instructions, [appended](glossary.md#叠加) **after** Claude Code's native system prompt, not replacing it |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Comma-separated tool allowlist. When not given, these three read-only tools |
| `-p`, `--permission-mode` | str | `default` | Value must be one of `default`, `acceptEdits`, `plan`, `bypassPermissions`; anything else makes argparse error out with exit code 2 |
| `-b`, `--budget` | float | unlimited | Dollar [budget](glossary.md#预算) cap; stops when exceeded |
| `--resume SESSION_ID` | str | none | Continue an existing session |
| `--fork` | flag | `False` | Fork instead of continuing, used together with `--resume` |

!!! warning "The elapsed time and cumulative cost shown by `once` are always 0"
    `once` creates a new renderer instance for every event it receives (`cli.py:579-581`,
    `cli.py:1060`), while the timing origin and the cumulative cost live on the instance
    (`cli.py:393-394`). Hence:

    - The `用时` on the closing line is always `0:00`
    - `累计 $0.00` on the status line is always 0, and `上下文` never accumulates either

    The real cost of the single step is in the `cost_usd` field in `runs/manifest.json`. The `go` and
    `run` paths hold a single renderer instance and do not have this problem.

### `setup` {#setup}

Help text: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1147-1149`).
No flags at all.

What it does: read `.env` → decide whether it has been configured → start the interactive
configuration flow, with `reason` being `重新配置。` or `还没配过凭证。`. For the screen contents see
[First-run configuration flow](#首次运行的配置流程).

!!! warning "`flower setup` currently cannot reach this subcommand"
    The constant used to detect a default subcommand, `_CMDS = ("go", "run", "once")`
    (`cli.py:758`), **omits `"setup"`**, even though `setup` really is registered in the parser
    (`cli.py:1147`). So `flower setup` is rewritten into `flower go setup` — **it runs the full `go`
    workflow with the request body being the string `setup`**: first it verifies credentials, then
    it asks about the request, and then it genuinely starts dispatching workers. Adding global flags
    changes nothing: `flower -v setup` → `["-v", "go", "setup"]`.

    **No argv whatsoever can reach the `setup` subcommand.**

    To configure credentials, there are currently only these two routes, both of which reach the same
    interactive interface:

    - Just run `flower "some request"`; if credentials have never been configured it will ask first;
    - Or hand-write `~/.config/flower/.env`; for key names see [The keys it writes](#写出来的键).

    A few pieces of copy are collateral damage: the ``跑 `flower setup` 重配。`` printed when
    credentials are rejected, and the comment on the first line of `.env`, ``由 `flower setup` 写``,
    both point at this unreachable command.

---

## Global flags {#全局开关}

The 5 global flags are attached both to the main parser and to every subcommand
(`cli.py:1071-1087`). The copies on the subcommands use `argparse.SUPPRESS`, so if you do not give
them no attribute is written, which means **they can go before or after the subcommand** without
overriding each other. The side effect is that they do not show up in a subcommand's `--help` — for
that you have to run `flower --help`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | The agent's working directory. It is `resolve()`d to an absolute path and `mkdir -p`'d. The [workbench](glossary.md#工作台) `.flower/` is created inside it |
| `-r`, `--run-dir` | str | `runs` | The directory for the [session store](glossary.md#会话存储) and the run manifest. **Relative to the current CWD, not to the workspace** |
| `-v`, `--verbose` | flag | `False` | Prints more; see below |
| `-W`, `--workbench` | flag | `False` | Enables the workbench. **Has no effect on `go`**; only takes effect for `run` (when the workflow does not carry its own workbench) and `once`, in which case the workbench lands in `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | On resume, replaces old large tool results with file pointers, i.e. [trim](glossary.md#裁剪). **Has no effect on `go`**; that path is controlled inversely by `--no-trim` |
| `-h`, `--help` | flag | — | Present on every parser. When it appears in argv, the default-subcommand rewrite is skipped and help is printed directly |

The fact that `-r/--run-dir` is relative to CWD will bite you: `flower -w /other/proj "do X"` creates
`runs/` in **the directory where you typed the command**, while `.flower/` is created under
`/other/proj/` — the two pieces of state get split. To keep them together, pass
`-r /other/proj/runs` explicitly.

The help for `-v` says "显示思考与工具结果", but the [main thread](glossary.md#主线程)'s thinking
**is shown by default**. What `-v` actually additionally turns on is:

- The body text of subagents (not shown by default, only their tool calls)
- Normal tool results (by default only the failing ones are shown)
- `prompt` events
- Printing the currently effective credential configuration before starting, with the token masked to
  its first 4 characters

That last one uses a bare `print()`, so it **does not go through output sanitisation, is not wrapped,
and is not protected by the terminal write lock**; when several `flower` runs go in parallel these
lines may get torn apart.

---

## How to talk to it while it runs {#运行中怎么和它说话}

Once a run has started, the terminal **is reading your input the whole time**. You do not need to
wait for it to ask, and you do not need to press anything to enter input mode — the last line is
always the one you can type on.

### The input prompt permanently at the bottom {#常驻在最下面的输入提示符}

A daemon thread `flower-stdin` reads stdin throughout (`cli.py:655-755`), polling with `select` every
0.2 seconds rather than doing a blocking read (so a stop signal can wake it up; streams that do not
support `select`, such as on Windows, degrade to a blocking read).

**It reads all the time, not only when there is a question.** The reason: if it only read while a
question was pending, whatever you typed during the hours of work would sit in the terminal buffer
and be swallowed as the answer to the next question — the question would be answered before you even
saw it.

On the display side, `_say()` is the only output channel; before every output it erases the prompt
and redraws it afterwards (`cli.py:299-305`), so the prompt never gets pushed up the screen by event
output. The prompt has two wordings, switching on whether a question is pending:

| State | Last line on screen |
|---|---|
| Question pending | `你的回答 (回车=跳过,让它自己判断) > ` |
| No question pending | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Where what you type goes {#你敲的东西去哪了}

| What you type | With a question pending | With no question pending |
|---|---|---|
| **Empty line (just Enter)** | Skip this question, let it decide for itself | Nothing |
| **Starting with `?`** | Oracle Q&A, see below | Same as left |
| **Digits only**, within the option range | Replaced by the matching option, then answered | Treated as plain text |
| Any other text | Sent as the answer to the asking agent | Goes into the inbox as an additional requirement |
| EOF (Ctrl-D or the pipe closing) | Refuses this question, removes the prompt, thread exits | Removes the prompt, thread exits |

When it goes into the inbox, a receipt line is printed:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

When there is no [brief](glossary.md#需求确认书) to spill to, the second half becomes
`没有确认书可落盘 —— 它可能活不过下一个步骤`. The inbox **does not interrupt** the worker that is
running; it only picks things up the next time it checks the inbox itself. The same sentence is also
appended to `notes/需求.md`; without spilling it would not survive a step boundary — the next step is
a new session that only reads the frozen files.

### Starting with `?` = oracle Q&A {#旁路问答}

A line starting with `?` is not sent to the running agent but handed to the
[oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

It starts a **separate** Runtime whose `run_dir` is `<run_dir>/aside/`, so its cost and session
lineage do not get mixed into the main `manifest.json`. The role is read-only, its tools are only
`Read`, `Glob`, `Grep`, at most 12 turns, with a cost cap of **$0.5**. The context it sees is the
most recent **60** events (`thinking` and `prompt` events do not enter this window), each truncated
to 200 characters, plus a description of the workbench paths.

It runs **concurrently**; the running run does not wait a single second. An answer looks like this:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

On failure it prints a red line `# 旁路问答失败:<类型>: <消息>`, which **does not affect the main
workflow**. On exit it waits at most **120** seconds for oracle calls to finish, printing
`(等 N 条旁路问答收尾…)` before waiting.

What it says never enters the run's context — asking does not affect the run, and the answer is
discarded once given.

!!! warning "A full-width `?` does not trigger oracle Q&A — Chinese IME users will hit this"
    The line of code that detects an oracle question is (`cli.py:733`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Both characters are **the half-width ASCII `?`** (`0x3f`) — verified byte by byte. From the way
    it is written the intent is obviously to accept both the half-width `?` and the full-width `?`
    (U+FF1F) produced by a Chinese IME, but in practice the same character was written twice.

    Consequence: **a line starting with the full-width `?` is not treated as an oracle question**, it
    is silently sent into the inbox as an "additional requirement" and then appended to
    `notes/需求.md`. The receipt you see is `+ 收到`, not `# 旁路`.

    To ask the oracle you **must use the half-width `?`** — switch your IME to English first, or at
    least type the first character half-width.

### What is on the screen {#屏幕上都是什么}

The icons are **all ASCII**, not emoji (`cli.py:49-67`). The reason is written in a code comment:
emoji together with box-drawing, geometric and arrow characters trigger terminal glyph fallback, which
crashed a terminal twice.

| Icon | Meaning | Icon | Meaning |
|---|---|---|---|
| `=` | Step separator | `+` | Done / answered / received |
| `~` | Thinking, retry | `x` | Failure / error |
| `>` | Dispatch | `#` | Handoff, oracle, task |
| `*` | Tool call | `-` | Status line, list item |
| `?` | Question | `<-` | Continuity, handoff landing point |
| `!` | Warning / interrupt | `.` | Skipped |
| `\| ` | Subagent indentation bar | | |

!!! warning "The `❓` and `↩` in older docs do not exist in a real terminal"
    Early documentation used `❓` for questions and `↩` for the wake line. **The code has never used
    those two characters** — the question icon is the half-width `?`, and the icon for wake and
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

The five question states appear on screen as:

| State | Screen output |
|---|---|
| Asked | `  ? <问题>`, followed by the options one per line as `     1) 选项一`, plus `     (还能问 N 次)` when there is a quota |
| Answered | `  + <答案>` |
| Timed out | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Quota exhausted | `  ! 提问额度用完` |
| You skipped it | `  . 已跳过` |

When `--asks` is unlimited (the default), the trailing "还能问 N 次" line is not shown.

When a [handoff](glossary.md#换代) finishes writing the handoff document, it comes out as one block:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

When the handoff document is degraded, an extra red line is inserted:
`交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

The output also does two things you cannot see: every output line goes through sanitisation that
**only lets flower's own SGR colour codes through**, so screen-clearing and cursor-movement sequences
emitted by the model or tools are swallowed wholesale; and the width is
`max(40, min(terminal columns, 110))`, so on a wide terminal it does not fill the whole line — that
is deliberate.

### The prompt at start {#起跑时的提示符}

Running `flower` bare (with no request) asks first. Two wordings:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

The second only appears when this directory has been run before and `需求.md` has all four sections.

This prompt reads via `input()`, **without going through shell parsing**. Chinese quotes, spaces and
exclamation marks can be typed directly — that is the entire reason it exists. zsh hitting a Chinese
closing quote drops into `dquote>` continuation, which looks like a hang while in fact nothing was
ever started.

- Empty input + first time → exit, printing ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Empty input + wake → **valid**, meaning "continue"
- Entering `/new` → equivalent to `--new`; after archiving the previous segment it **asks again** for
  the request
- Ctrl-C / Ctrl-D → exit, printing `已取消`

### Timeout {#超时}

`--timeout` is a float in seconds, default `1800.0`. Three kinds of value:

| Value | Behaviour |
|---|---|
| `> 0` | Wait that many seconds. On timeout the question settles as `timeout` and the agent decides for itself |
| `0` or negative | **Fully automatic**. Questions do not enter the waiting queue, no `asked` event is emitted, nothing appears on screen, and they settle as `timeout` immediately |
| Wait forever | **Not possible from the command line**. Internally "wait forever" is supported, but `--timeout` is a float with a default value, and no spelling can produce it. The ceiling is just passing a very large number of seconds |

`--timeout 0` and `--timeout -1` are exactly equivalent. Piped runs, CI runs and unattended runs all
use this.

When a question gets no answer, the tool result fed back to the model is fixed copy, of four kinds:

| Result | Copy fed back to the model |
|---|---|
| Quota exhausted | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| You skipped it | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| The question is empty | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**Ctrl-C means completely different things in two places.**

**Pressed at the start prompt `> `** — exits the program directly, printing `已取消`.

**Pressed mid-run** — interrupts the current round and gives you one chance to speak:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Just pressing Enter here means interrupting without saying anything and carrying on. If a question was
pending at the time, an extra line is printed:
`  (有 N 个提问还等着,打断不影响它们)`.

**Pressing Ctrl+C a second time really does exit**, and as an uncaught `KeyboardInterrupt` — you get
a Python traceback on screen, not a clean exit.

The interrupt is cooperative: it breaks cleanly at a message boundary and does not hard-cancel tasks.
It **does not count as a failed attempt** and consumes no retries. On resume a note is attached telling
the model that in-flight tool calls returning interrupted is a normal side effect of the interrupt, not
an environment failure.

This custom Ctrl-C is only installed when `sys.stdin.isatty()` (`cli.py:918`). When running in a pipe,
Python's default behaviour is kept, i.e. the first press exits. The `once` path does not go through
here, so Ctrl-C on `once` also exits on the first press.

### SIGHUP / SIGTERM {#sighup-sigterm}

The `go` and `run` paths install handlers for both `SIGHUP` and `SIGTERM`: first they write **the
in-flight step** into `manifest.json` too, marked `killed-by-signal`, then restore the default action
and really leave.

The cause was that when a terminal crashes the kernel sends SIGHUP, whose default action terminates
the process outright, so `finally` never runs and the manifest is never written — and a run's accounts
are lost. When not on the OS main thread, or on platforms that do not support it, this is silently
skipped.

---

## First-run configuration flow {#首次运行的配置流程}

All three entry points `go`, `run` and `once` call `ensure_credentials()` at the top
(`cli.py:1213-1244`), which is **two gates**.

### Gate one: are there credentials {#第一道-有没有凭证}

It looks for credentials in priority order. If it finds neither `ANTHROPIC_API_KEY` nor
`ANTHROPIC_AUTH_TOKEN` it starts the interactive configuration; when non-interactive (stdin is not a
terminal) it does not block, it just prints this and exits:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Two parts of this copy do not match the implementation: the `flower setup` on the second line cannot
currently be reached (see [`setup`](#setup)); and the fourth line **contradicts the code** — flower
really does treat the `env` block of `~/.claude/settings.json` and `settings.local.json` as the
**last fallback level**, borrowing only 9 credential keys from it and taking over no other setting.
The place that prints this line is `env.py:192` (the function `check_credentials()` is defined at
`env.py:184`), while the code that actually reads those two files is `env.py:56-75` and `:109-111`;
tracked in [issue #13](https://github.com/ChenyuHeee/flower/issues/13).
**The code is authoritative: it reads them.** The full lookup priority and those 9 keys are in the
[configuration reference](config.md#借用).

### What the interactive configuration asks {#交互配置问什么}

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

- Question 1 is **mandatory**. Leaving it blank prints the red line `没给 token,取消。` and abandons
  the configuration.
- Questions 2 and 3 may be left blank.
- When stdin is not a terminal the whole flow is skipped without blocking.

### The keys it writes {#写出来的键}

| What you entered | Key it becomes |
|---|---|
| Token starting with `sk-ant-` | `ANTHROPIC_API_KEY` |
| Any other token | `ANTHROPIC_AUTH_TOKEN` |
| Non-empty gateway address | `ANTHROPIC_BASE_URL` |
| Non-empty model name | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` and `ANTHROPIC_DEFAULT_SONNET_MODEL`, all three at once |

The file path is `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, and the parent directory is created
automatically. Writing is a **full overwrite**, keys with empty values are skipped, `chmod 0600` is
applied afterwards, and it then takes effect immediately — no need to restart your shell.
The first line is always a comment reminding you not to commit it to version control.

### Gate two: do the credentials work {#第二道-凭证能不能用}

Once the configuration is complete, it prints `- 验一下凭证…` and then **actually calls the API**.

Probe details: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, default timeout 20 seconds, over
stdlib `urllib`, no dependency pulled in. The model is taken in the order
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. If
`ANTHROPIC_API_KEY` is present it uses the `x-api-key` header, otherwise
`authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` is deliberately 16 rather than 1: in practice, models with forced chain-of-thought cannot
even fit their thinking in, and the server struggles for 30 seconds before returning; with 16 it takes
only 3.6 seconds.

The probe's conclusions are handled in three classes, and **the differences matter**:

| Conclusion | Trigger | What flower does |
|---|---|---|
| `auth` | HTTP 401 / 403, or no credentials at all | Prints `! 凭证被拒:<响应体前 160 字>`, starts interactive reconfiguration, and verifies again afterwards. Non-interactive means exit code 1 |
| `config` | HTTP 404, or 400 with `model` mentioned in the body | Prints `! 网关地址或模型名不对:<…>`, same as above |
| `net` | Cannot connect / timeout / DNS failure / TLS failure / 5xx | Prints `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **does not make you reconfigure, just starts running** |
| `ok` | Below 400, or anything undecidable, is let through | Silently continues |

The `net` case is deliberate: a network hiccup should not force you to retype your token, and flower
itself has a mechanism for suspending and reconnecting when the network drops. Seeing "探针没打通" is
nothing to worry about; just carry on.

You get **at most one** reconfiguration chance. A second failure exits.

### Automatic reconfiguration after a failed run {#跑挂了之后的自动重配}

When the workflow fails, flower matches the error message of the failing step against a regex (401,
`invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). On a hit, and when stdin
is a terminal, it prints `! 看起来是凭证不对:<前 120 字>` on the spot and starts the interactive
configuration; once configured it prints:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

and then exits with code 1 regardless. The `once` path does not have this part.

---

## Exit codes {#退出码}

| Code | When |
|---|---|
| `0` | Ran to completion normally |
| `1` | Every deliberate exit. The message goes to **stderr**, with no traceback. Full list below |
| `2` | argparse argument error: unknown flag, missing positional, `-p` given a value outside its choices |
| `130` | Two Ctrl+C presses in a row mid-run. An uncaught `KeyboardInterrupt`, **with a Python traceback** |
| Killed by signal | SIGHUP / SIGTERM: first writes the in-flight step into the manifest, then leaves via the default action |

All the messages for exit code 1:

| Message | When |
|---|---|
| `已取消` | Ctrl-C or Ctrl-D at the start prompt |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Brand-new directory + plain Enter |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 lines total) | Non-interactive + no credentials |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe verdict `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe verdict `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` used in a non-git directory |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Empty request and the directory has no wake |
| `在步骤 '<步骤名>' 中止` | A step in the workflow failed and the policy is to stop |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, missing the colon |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | The target module failed to import |
| `'<模块>' 里没有 '<属性>'` | The attribute was not found in the module |

At the end (`go` / `run` paths) it prints one last line:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

This amount only counts **this process's** cost, not the previous run's — even though the manifest
file itself accumulates across processes.

---

## What it creates in your project {#它在项目里创建了什么}

Two trees: `<run_dir>/` (default `./runs/`, relative to CWD) holds accounts and sessions;
`<workspace>/.flower/` holds the [workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Path | Contents |
|---|---|
| `runs/sessions.db` | SQLite, the full transcript. This is the material basis that makes [continuity](glossary.md#接续) possible |
| `runs/manifest.json` | The [run manifest](glossary.md#运行清单). A JSON array, **accumulated across processes**; all the numbers on the case pages can be recomputed from here |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Written by atomic replace |
| `runs/aside/` | The oracle Q&A's separate Runtime, with its own `sessions.db` and `manifest.json`. **Its cost and lineage are not mixed into the main manifest** |
| `runs/workbench/` | Only appears when `-W` is used and the workflow does not carry its own workbench (the `run` / `once` paths) |

The fields of each record in `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` is this process's marker, in the format `YYYYmmdd-HHMMSS-<6 hex digits>`. The spill policy is
**append, do not overwrite**: before each write the file is re-read and deduplicated by `run` — rows
belonging to this process are replaced with the latest ones, rows from other processes are left as
they are.

Step names have four shapes:

| Shape | When |
|---|---|
| `<步骤名>` | First attempt |
| `<步骤名>#retry<N>` | Ordinary retry |
| `<步骤名>#round<N>` | Sent back to continue after failing a verdict |
| `<步骤名>·判定#<N>` | The [judge](glossary.md#判定者)'s step |

When killed by a signal, the in-flight step is written in too, with the `error` field being
`killed-by-signal`.

**Running several flowers in parallel in the same directory**: `manifest.json` is safe (re-read +
merged by `run`), but `lineage.json` is a full overwrite, so two processes will clobber each other's
lineage for steps with the same name. To run in parallel, use different `-r`.

`lineage.json` stores the absolute path of the workspace. If it does not match, it is treated as
absent and it **silently** falls back to a new session, with no error — after a directory has been
copied elsewhere the old `session_id` could not be looked up anyway.

### `.flower/` {#flower-目录}

| Path | Contents |
|---|---|
| `.flower/scripts/` | Scripts that will be run a second time. Put `# desc: one sentence` on the first line and that sentence appears in the index |
| `.flower/artifacts/` | Long outputs over 2000 characters: reports, data, logs. Only paths appear in the conversation |
| `.flower/notes/` | Cross-step decision records |
| `.flower/spill/` | [Spill](glossary.md#落盘): tool results over 4000 characters land here, and the context keeps only a one-line pointer plus the first 400 characters. The file name is the first 16 digits of the content's sha256 plus `.txt` |
| `.flower/INDEX.md` | An index of the directories above, **injected into the coordinator's system prompt** (subagents do not inherit it) |

The `go` path always generates these under `notes/`:

| File | Contents |
|---|---|
| `notes/需求.md` | The frozen [brief](glossary.md#需求确认书), four sections: goal / acceptance criteria / boundaries / unknowns and assumptions |
| `notes/目标.md` | The frozen goals, two sections: goals / verdict checklist |
| `notes/问答记录.md` | An appended record of every question and answer (including their state), also including what you said unprompted. **Does not enter the context, kept purely as a record** |
| `notes/交接-<步骤名>.md` | The [handoff document](glossary.md#交接书) written during handoff; the previous generation is filed away into `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | The `lineage.json`, `需求.md` and `目标.md` archived away by `--new` or `/new`. This is a **move**, not a delete |

With `--isolate` the workbench moves outside the repo: `<workspace>.parent/.flower-<workspace name>/`.
The worktree is each agent's private copy while the workbench is a shared layer across agents, and
shared things cannot live inside a private fence. In that case the workbench path given to the model
is absolute.
