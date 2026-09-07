# CLI reference

Once installed, `flower` is a single executable with 4 subcommands and 23 flags. This page lists them all: the type, default and exact semantics of every flag, plus how to talk to it mid-run, what it asks the first time, what the exit codes are, and which files it puts in your directory. After reading this page you shouldn't need to open the source.

Source: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcommand | What it does | Positional | Own flags |
|---|---|---|---|
| `go` | The whole chain: clarify the request → set goals → dispatch workers → verdict every round. The default when no subcommand is written | `ask` (optional) | 11 |
| `run` | Runs a [workflow](glossary.md#流程) you wrote yourself | `target` (required) | 0 |
| `once` | Runs a single agent once — no workflow, no verdict | `prompt` (required) | 6 |
| `setup` | Configures credentials, writes to `~/.config/flower/.env` | none | 0 |

Total flag count 23 = 5 global + 11 for `go` + 6 for `once` + `-h/--help`. `run` and `setup` have no flags of their own.

---

## Invocation forms {#调用形式}

All of `flower`'s argv passes through `_with_default_cmd()` first to fill in the default subcommand, then goes to argparse (`cli.py:1253-1255`). That's why `flower "帮我做一个 X"` works — it gets rewritten into `flower go "帮我做一个 X"`.

The rules for filling in the default subcommand (`cli.py:761-797`):

1. The set of global flags is **derived from the main parser itself**, not a hardcoded list. Those with `nargs == 0` count as pure flags; the rest take a value.
2. Scan left to right, skipping global flags. Value-taking ones are skipped together with their value; the `=` form such as `--workspace=/tmp` is recognized too.
3. Stop at the first token that isn't a global flag. If it's one of `go`, `run`, `once`, hand it to argparse as is; **otherwise insert a `go` before it**, so it becomes the request body of `go`.
4. If the scan ends without hitting a positional (empty argv, or only global flags) → append `go` at the end and go to interactive input.
5. Exception: if argv contains `-h` or `--help`, return it unchanged and let argparse print help.

The constant used for the check is `_CMDS = ("go", "run", "once")` (`cli.py:758`) — **`setup` is not in it**; for the consequences see [`setup`](#setup).

### What the rewriting actually produces {#实际的改写结果}

| What you typed | What it actually parses as | Effect |
|---|---|---|
| `flower` | `["go"]` | Interactively asks "What do you want done?" |
| `flower -v` | `["-v", "go"]` | Same, with verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Starts right away |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Global flags can go in front |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | The `=` form works too |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Subcommand flags can go after the request |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | Or in front |
| `flower --new` | `["go", "--new"]` | Flags but no request → interactive input |
| `flower once "hi"` | `["once", "hi"]` | Unchanged |
| `flower run flows:main` | `["run", "flows:main"]` | Unchanged |
| `flower run` | `["run"]` | argparse reports missing `target`, does **not** treat it as a request |
| `flower go run` | `["go", "run"]` | Explicit disambiguation: the request body is literally `run` |
| `flower setup` | `["go", "setup"]` | Runs `go`, with the string `setup` as the request; see [`setup`](#setup) |
| `flower --help` | Unchanged | argparse prints help |

The two words `run` and `once` **cannot** be used directly as a request body; this ambiguity is kept deliberately (`cli.py:770-771`). To use them as a request, write `flower go run`.

### Six usable forms {#六种能用的写法}

```bash
flower                                    # 1. Bare: asks "What do you want done?" or "Continue from last time?"
flower "帮我做一个 X"                       # 2. Request as positional argument
echo "帮我做一个 X" | flower --timeout 0    # 3. Feed stdin through a pipe
flower once "读一眼这个仓库"                 # 4. Single agent
flower run flows.py:main                  # 5. Run a custom workflow
flower go setup                           # 6. Explicit go, with setup as the request body
```

The module form `python -m flower.cli` is equivalent to `flower` (`cli.py:1263-1264`). The container wrapper `docker/flowerbox` takes exactly the same arguments as `flower`.

### Feeding stdin through a pipe {#管道喂-stdin}

When `sys.stdin.isatty()` is false, `ask_for_prompt()` **doesn't print the prompt header** and just does `input("> ")` to read a line (`cli.py:814-822`). So `echo "..." | flower` works.

But right after, it prints a warning, and the stdin thread immediately hits EOF and exits:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

A piped run should be paired with `--timeout 0`: questions no longer pretend to wait 30 minutes, they fall through immediately, the agent decides on its own and writes the assumptions into the "unknowns and assumptions" section of the brief.

---

## Subcommands {#子命令}

### `go` {#go}

Help text: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1096-1128`).

Positional `ask`, `nargs="?"` — omit it and you get interactive input. This is the most-used entry point; `flower "做 X"` goes through it.

What it does (`cli.py:1011-1042`):

1. `ensure_credentials()` — checks credentials and actually fires one API probe; see [First-run configuration flow](#首次运行的配置流程).
2. [Wake](glossary.md#唤醒) detection: read-only look at whether this directory has been used, without writing a single byte.
3. If `ask` wasn't given, print a prompt and ask; typing `/new` is equivalent to `--new`, and then it **asks for the request again**.
4. If this is a [continuity](glossary.md#接续), print a wake banner.
5. Build the three-step [workflow](glossary.md#流程): `确认需求` → `设定目标` → `干活`, with a `干活·判定#N` after each work round. `--clarify-only` keeps only the first step.
6. Start.

The wake banner looks like this (the home directory in the path is replaced with `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` is always there; `目标 N 条` appears only when there is a verdict checklist; `干活上下文 X` requires that the last-round context of that [session](glossary.md#会话) can be found in `sessions.db` — if it can't, it isn't shown.

!!! warning "`-W` and `-T` are silently overridden on the `go` path"
    Writing these two global flags on `go` has no effect — no error, no notice:

    - `-W/--workbench`: the workflow `go` builds always comes with its own [workbench](glossary.md#工作台), and the code takes `getattr(wf, "workbench", None) or args.workbench` (`cli.py:859`) — the workflow's own always wins. So the workbench is always `<workspace>/.flower/` (with `--isolate`, `<workspace>.parent/.flower-<name>/`), and `-W` can't change it.
    - `-T/--trim`: `go` goes through `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1042`), which uses the negation of `--no-trim` directly and **never looks at `args.trim`**. That means [trimming](glossary.md#裁剪) is on by default on the `go` path, and the only way to turn it off is `--no-trim`.

    These two flags only take effect on `run` (when the workflow doesn't bring its own workbench) and `once`.

#### The 11 flags of `go` {#go-的-11-个开关}

| Flag | Type | Default | Description |
|---|---|---|---|
| `--asks N` | int | `-1` | Question quota. `-1` or any negative = **unlimited**; `0` = no questions allowed, the first question gets `over_budget`; `N` = hard quota. When over quota the tool refuses outright without blocking the run |
| `--rounds N` | int | `3` | Cap on the **total number** of work rounds, not extra rounds. At the end of each round an independent [judge](glossary.md#判定者) rules on "is it done", and if not it's sent back to continue the same session |
| `--no-goal` | flag | `False` | Turns off the [goal guard](glossary.md#目标看守): no `目标.md` is generated, no [verdict](glossary.md#判定) is made, and the run is done once the work finishes |
| `--judge-can-run` | flag | `False` | Lets the judge run commands. The verdict is harder, at the cost of it also being able to modify the workspace |
| `--timeout SECONDS` | float | `1800.0` | How long to wait for a human answer. `0` or negative = fully automatic, all questions fall through **immediately** without pretending to wait. Semantics in [Timeout](#超时) |
| `--isolate` | flag | `False` | Gives each [subagent](glossary.md#subagent) its own git worktree, i.e. [isolation](glossary.md#隔离). **Requires the workspace to be a git repo**, otherwise exit code 1. Also moves the workbench outside the repo |
| `--window N` | int | none (inferred from model name) | Model context window. When not given: model name contains `1m` or doesn't contain `haiku` → 1,000,000; contains `haiku` → 200,000. At `window − 50000` it writes a [handoff document](glossary.md#交接书) and does a [handoff](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Turns off handoff, falling back to the SDK's built-in [compact](glossary.md#压缩) |
| `--new` | flag | `False` | Don't continue from last time. **Moves** (does not delete) the previous segment's `lineage.json` + `需求.md` + `目标.md` into `notes/archive/<YYYYmmdd-HHMMSS>/`, then starts over |
| `--clarify-only` | flag | `False` | Only does [clarify](../guide/clarify.md), no work afterwards — the workflow keeps only the `确认需求` step |
| `--no-trim` | flag | `False` | Turns off trimming. On the `go` path trimming is **on** by default; this is the only way to turn it off |

Edge cases in the values, none of which error or warn:

- `--rounds 0` and `--rounds 1` are equivalent — internally it's `retries = max(0, rounds - 1)`, both run 1 round.
- Any negative `--asks` means unlimited, not just `-1`.
- Any negative `--timeout` equals `0`, i.e. fully automatic.
- `--window 0` is **silently ignored** (`0` is falsy and simply isn't passed down), falling back to the default inferred from the model name. Negative values do get passed down and are then floored to `10000`.
- `--clarify-only` is a **no-op** in a directory that has already been clarified — the `确认需求` step sees a complete `需求.md` and skips, and since that's the only step in the workflow, nothing happens at all (except the wake count going +1). To re-clarify, pair it with `--new`.
- The end of `go`'s `--help` says "全局开关(-v/-w/-r/-T)见 `flower --help`" — that line **omits `-W`**.

### `run` {#run}

Help text: `运行一个 workflow` (`cli.py:1130-1133`).

Positional `target`, written as `module:attribute`. Both forms are supported (`cli.py:831-852`):

```bash
flower run mypkg.flows:build     # import by module name
flower run flows.py:build        # file path; the parent dir is put on sys.path and it's imported by file name
```

If the attribute obtained is callable it's called once and the return value is used as the [workflow](glossary.md#流程); if it's already a workflow object it's used directly.

**`run` has no flags of its own**, only the 5 global flags. So `--window`, `--no-handoff` and the like always take their defaults on this path (the code falls back with `getattr`, `cli.py:862-864`). To tune them, write the parameters into your own workflow.

### `once` {#once}

Help text: `跑一次单 agent` (`cli.py:1135-1145`). The positional `prompt` is required.

It constructs an `AgentSpec(name="ad-hoc", …)` and runs it directly, **without going through `_drive`**. So `once` has none of:

- Ctrl-C to interrupt and speak (pressing it is a plain `KeyboardInterrupt`)
- the stdin answering thread, the input prompt pinned to the bottom
- oracle Q&A
- SIGHUP / SIGTERM salvage bookkeeping
- the closing `总花费 … · 清单 …` line
- the auto-reconfigure guidance after a credentials failure

The name of this step in the [run manifest](glossary.md#运行清单) is always `ad-hoc`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-i`, `--instructions` | str | empty | Domain instructions, [appended](glossary.md#叠加) **after** Claude Code's native system prompt, not replacing it |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Comma-separated tool whitelist. When not given, these three read-only tools |
| `-p`, `--permission-mode` | str | `default` | Value must be one of `default`, `acceptEdits`, `plan`, `bypassPermissions`; anything else makes argparse error out with exit code 2 |
| `-b`, `--budget` | float | unlimited | Dollar [budget](glossary.md#预算) cap; stops when exceeded |
| `--resume SESSION_ID` | str | none | Continue an existing session |
| `--fork` | flag | `False` | Fork instead of continuing; used with `--resume` |

!!! warning "The elapsed time and cumulative cost shown by `once` are always 0"
    `once` creates a new renderer instance for every event it receives (`cli.py:579-581`, `cli.py:1060`), while the timing origin and cumulative cost live on the instance (`cli.py:393-394`). So:

    - the `用时` on the closing line is always `0:00`
    - the `累计 $0.00` in the status line is always 0, and `上下文` never accumulates either

    The real cost of the single step is in the `cost_usd` field of `runs/manifest.json`. The `go` and `run` paths hold a single renderer instance and don't have this problem.

### `setup` {#setup}

Help text: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1147-1149`). No flags at all.

What it does: read `.env` → decide whether it has been configured → start the interactive configuration flow, with `reason` being `重新配置。` or `还没配过凭证。`. For the screen content see [First-run configuration flow](#首次运行的配置流程).

!!! warning "`flower setup` currently cannot reach this subcommand"
    The constant used to detect the default subcommand, `_CMDS = ("go", "run", "once")` (`cli.py:758`), **omits `"setup"`**, even though `setup` is genuinely registered on the parser (`cli.py:1147`). So `flower setup` is rewritten into `flower go setup` — **it runs the full `go` workflow with the string `setup` as the request body**: it verifies credentials, then clarifies the request, then actually starts dispatching workers. Adding global flags changes nothing: `flower -v setup` → `["-v", "go", "setup"]`.

    **No argv whatsoever can reach the `setup` subcommand.**

    To configure credentials, there are currently only these two routes, both of which reach the same interactive interface:

    - Just run `flower "随便一句诉求"`; if credentials haven't been configured it will ask first;
    - Or hand-write `~/.config/flower/.env`; for the key names see [The keys it writes](#写出来的键).

    A few pieces of copy are collateral damage: the ``跑 `flower setup` 重配。`` printed when credentials are rejected, and the comment on the first line of `.env`, ``由 `flower setup` 写``, both point at this unreachable command.

---

## Global flags {#全局开关}

The 5 global flags are attached both to the main parser and to every subcommand (`cli.py:1071-1087`). The copies on subcommands use `argparse.SUPPRESS`, so no attribute is written when they aren't given — which means **they can go before or after the subcommand** without overriding each other. The side effect is that they don't show up in a subcommand's `--help`; to see them, run `flower --help`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | The agent's working directory. It gets `resolve()`d to an absolute path and `mkdir -p`'d. The [workbench](glossary.md#工作台) `.flower/` is created inside it |
| `-r`, `--run-dir` | str | `runs` | Directory for the [session store](glossary.md#会话存储) and run manifest. **Relative to the current CWD, not to the workspace** |
| `-v`, `--verbose` | flag | `False` | Prints more; see below |
| `-W`, `--workbench` | flag | `False` | Enables the workbench. **No effect on `go`**; only takes effect on `run` (when the workflow doesn't bring its own workbench) and `once`, in which case the workbench lands at `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | On resume, replaces old large tool results with file pointers, i.e. [trimming](glossary.md#裁剪). **No effect on `go`**; that path is controlled inversely via `--no-trim` |
| `-h`, `--help` | flag | — | Present on every parser. When it appears in argv, the default-subcommand rewriting is skipped and help is printed directly |

The fact that `-r/--run-dir` is relative to CWD will bite you: `flower -w /other/proj "做 X"` creates `runs/` in **the directory you typed the command in**, while `.flower/` is created under `/other/proj/` — the two pieces of state get separated. To keep them together, pass `-r /other/proj/runs` explicitly.

The help for `-v` says "显示思考与工具结果", but the [main thread](glossary.md#主线程)'s thinking **is shown by default**. What `-v` actually turns on additionally is:

- subagent body text (not shown by default; only its tool calls are)
- normal tool results (by default only failing ones are shown)
- `prompt` events
- printing the currently effective credential configuration before starting, with the token masked down to its first 4 characters

That last one goes through a bare `print()`, **bypassing output sanitization, without wrapping, unprotected by the terminal write lock** — when several `flower`s run in parallel these lines can get torn apart.

---

## How to talk to it mid-run {#运行中怎么和它说话}

Once a run is going, the terminal **is reading your input the whole time**. You don't have to wait for it to ask, and you don't have to press anything to enter input mode — the last line is always the one you can type on.

### The input prompt pinned to the bottom {#常驻在最下面的输入提示符}

A daemon thread `flower-stdin` reads stdin throughout (`cli.py:655-755`), polling with `select` every 0.2 seconds rather than blocking (so the stop signal can wake it; streams that don't support `select`, such as on Windows, degrade to a blocking read).

**It reads all the time, not just when there's a question.** The reason: if it only read while asking, whatever you typed during those hours of work would sit in the terminal buffer and get eaten as the answer to the next question — the question would be answered before you'd even seen it.

On the display side, `_say()` is the only output path; before each output it erases the prompt and redraws it afterwards (`cli.py:299-305`), so the prompt never gets pushed up the screen by event output. The prompt has two variants, switching on whether there's an unanswered question:

| State | Last line on screen |
|---|---|
| Question pending | `你的回答 (回车=跳过,让它自己判断) > ` |
| No question pending | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Where what you type goes {#你敲的东西去哪了}

| What you type | With a question pending | With no question pending |
|---|---|---|
| **Empty line (just Enter)** | Skip this question, let it decide on its own | Nothing |
| **Starting with `?`** | Oracle Q&A, see below | Same as left |
| **Digits only**, within the option range | Converted into the corresponding option and submitted as the answer | Treated as ordinary text |
| Any other text | Sent as the answer to the asking agent | Goes into the inbox as an additional requirement |
| EOF (Ctrl-D or pipe closed) | Refuses this question, removes the prompt, thread exits | Removes the prompt, thread exits |

When it goes into the inbox, a receipt line is printed:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

When there's no [brief](glossary.md#需求确认书) to spill into, the second half becomes `没有确认书可落盘 —— 它可能活不过下一个步骤`. The inbox does **not** interrupt the worker that's working; it only picks things up the next time it checks the inbox on its own. The same sentence is also appended to `notes/需求.md`; without spilling it wouldn't survive a step boundary — the next step is a new session that only reads frozen artifacts.

### Starting with `?` = oracle Q&A {#旁路问答}

A line starting with `?` isn't sent to the running agent but to the [oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

It starts a **separate** Runtime with `run_dir` at `<run_dir>/aside/`, so its cost and session lineage don't get mixed into the main `manifest.json`. The role is read-only, with only `Read`, `Glob`, `Grep` as tools, at most 12 turns, and a cost cap of **$0.5**. The context it sees is the most recent **60** events (`thinking` and `prompt` events don't enter this window), each truncated to 200 characters, plus a description of the workbench paths.

It runs **concurrently**; the ongoing run doesn't wait a second. The answer looks like this:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

On failure a red line `# 旁路问答失败:<类型>: <消息>` is printed, **without affecting the main workflow**. On exit it waits at most **120** seconds for oracles to finish, printing `(等 N 条旁路问答收尾…)` before waiting.

What it says never enters that run's context — asking doesn't affect the run, and the answer is discarded once given.

!!! warning "The full-width `?` doesn't trigger oracle Q&A — Chinese IME users will hit this"
    The line of code deciding on oracle Q&A is (`cli.py:733`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Both characters are **half-width ASCII `?`** (`0x3f`) — verified byte by byte. From the way it's written the intent is obviously to accept both the half-width `?` and the full-width `？` (U+FF1F) produced by Chinese IMEs, but it actually ended up being the same character twice.

    Consequence: **a line starting with the full-width `？` is not treated as an oracle question**, but is silently sent to the inbox as an "additional requirement" and thence appended to `notes/需求.md`. The receipt you see is `+ 收到`, not `# 旁路`.

    To ask the oracle you **must use the half-width `?`** — switch your IME to English first, or at least type the first character half-width.

### What's on screen {#屏幕上都是什么}

The icons are **all ASCII**, not emoji (`cli.py:49-67`). The reason is written in a code comment: emoji together with box-drawing, geometric and arrow characters trigger terminal glyph fallback, which crashed a terminal twice.

| Icon | Meaning | Icon | Meaning |
|---|---|---|---|
| `=` | Step separator | `+` | Done / answered / received |
| `~` | Thinking, retry | `x` | Failure / error |
| `>` | Dispatch | `#` | Handoff, oracle, task |
| `*` | Tool call | `-` | Status line, list item |
| `?` | Question | `<-` | Continue from last time, handoff landing point |
| `!` | Warning / interrupt | `.` | Skipped |
| `\| ` | Subagent indentation bar | | |

!!! warning "The `❓` and `↩` in older docs don't exist in a real terminal"
    Early docs used `❓` for questions and `↩` for the wake line. **The code has never used these two characters** — the question icon is a half-width `?`, and the icon for wake and handoff landing points is the two ASCII characters `<-`.

    So what a real terminal prints is:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    Not `❓ 这个工具……`, and not `↩ 在 ~/proj 接上上次`. Grepping logs based on the old docs will find nothing.

The five question states appear on screen as:

| State | Screen output |
|---|---|
| Asked | `  ? <问题>`, followed by options one per line as `     1) 选项一`, plus `     (还能问 N 次)` when there's a quota |
| Answered | `  + <答案>` |
| Timed out | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Quota exhausted | `  ! 提问额度用完` |
| You skipped | `  . 已跳过` |

When `--asks` is unlimited (the default), the trailing "还能问 N 次" line isn't shown.

When a [handoff](glossary.md#换代) writes the handoff document, it's a whole block:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

When the handoff document degrades, an extra red line is inserted: `交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

Output also does two things you can't see: every output line goes through sanitization that **only lets through flower's own SGR color codes**, so clear-screen and cursor-movement sequences emitted by the model or tools are swallowed whole; and the width is `max(40, min(terminal columns, 110))`, so on a wide terminal it doesn't fill the whole line — that's deliberate.

### The prompt at startup {#起跑时的提示符}

Running bare `flower` (with no request) asks first. Two variants:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

The second only appears when this directory has been run before and `需求.md` has all four sections.

This prompt reads via `input()`, **without going through shell parsing**. Chinese quotes, spaces, exclamation marks can all be typed directly — that's the entire reason it exists. zsh, upon seeing a Chinese closing quote, enters a `dquote>` continuation and looks like it hung, when in fact nothing ever started.

- Empty input + first time → exit, printing ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Empty input + wake → **valid**, means "keep going"
- Typing `/new` → equivalent to `--new`; after archiving the previous segment it **asks for the request again**
- Ctrl-C / Ctrl-D → exit, printing `已取消`

### Timeout {#超时}

`--timeout` is a float in seconds, defaulting to `1800.0`. Three kinds of value:

| Value | Behavior |
|---|---|
| `> 0` | Wait that many seconds. On timeout the question settles as `timeout` and the agent decides on its own |
| `0` or negative | **Fully automatic**. Questions don't enter the waiting queue, no `asked` event is emitted, nothing appears on screen, and they settle as `timeout` immediately |
| Wait forever | **Not possible from the command line.** "Wait forever" is supported internally, but `--timeout` is a float with a default, and no invocation can produce it. The ceiling is passing a very large number of seconds |

`--timeout 0` and `--timeout -1` are exactly equivalent. Piped runs, CI runs and unattended runs all use this.

When a question gets no answer, the tool result fed back to the model is fixed copy, in four variants:

| Result | Copy fed back to the model |
|---|---|
| Quota exhausted | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| You skipped | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| Question was empty | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**Ctrl-C means completely different things in two places.**

**Pressed at the startup prompt `> `** — exits the program immediately, printing `已取消`.

**Pressed mid-run** — interrupts the current round and gives you one chance to speak:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Pressing Enter here means interrupt without saying anything and continue. If there were questions pending at the time, an extra line is printed: `  (有 N 个提问还等着,打断不影响它们)`.

**Pressing Ctrl+C a second time really does exit**, and as an uncaught `KeyboardInterrupt` — you get a Python traceback on screen, not a clean exit.

The interrupt is cooperative: it breaks cleanly at a message boundary rather than hard-cancelling the task. It **does not count as a failed attempt** and doesn't consume a retry. On continuation, a note is attached telling the model that "in-flight tool calls returning interrupted is a normal side effect of the interrupt, not an environment failure".

This custom Ctrl-C is only installed when `sys.stdin.isatty()` (`cli.py:918`). In a pipe, Python's default behavior is kept, i.e. it exits on the first press. The `once` path doesn't go through here, so Ctrl-C on `once` also exits on the first press.

### SIGHUP / SIGTERM {#sighup-sigterm}

The `go` and `run` paths install handlers for both `SIGHUP` and `SIGTERM`: they first write **the in-flight step** into `manifest.json` marked `killed-by-signal`, then restore the default action and actually leave.

The cause: when a terminal crashes the kernel sends SIGHUP, whose default action terminates the process outright — `finally` doesn't run, the manifest isn't written, and a run's bookkeeping is lost. On a non-OS-main thread or an unsupported platform, this is silently skipped.

---

## First-run configuration flow {#首次运行的配置流程}

All three entry points `go`, `run` and `once` call `ensure_credentials()` at the start (`cli.py:1213-1244`), which has **two gates**.

### Gate one: are there credentials {#第一道-有没有凭证}

It looks for credentials in priority order. If neither `ANTHROPIC_API_KEY` nor `ANTHROPIC_AUTH_TOKEN` is found, it starts interactive configuration; when non-interactive (stdin isn't a terminal) it doesn't block, and just prints this and exits:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Two parts of this copy don't match the implementation: the `flower setup` on the second line currently can't be reached (see [`setup`](#setup)); and the fourth line is **the opposite of the code** — flower does treat the `env` block of `~/.claude/settings.json` and `settings.local.json` as a **last-resort fallback**, borrowing only 9 credential keys from it and taking over no other setting. The place that prints this line is `env.py:192` (the function `check_credentials()` is defined at `env.py:184`), while the code that actually reads those two files is `env.py:56-75` and `:109-111`; tracked in [issue #13](https://github.com/ChenyuHeee/flower/issues/13). **The code is authoritative: it reads them.** The full lookup priority and those 9 keys are in the [configuration reference](config.md#借用).

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

- Question 1 is **required**. Leaving it blank prints the red line `没给 token,取消。` and abandons configuration.
- Questions 2 and 3 may be left blank.
- When stdin isn't a terminal, the whole flow is skipped without blocking.

### The keys it writes {#写出来的键}

| What you entered | Key written |
|---|---|
| Token starting with `sk-ant-` | `ANTHROPIC_API_KEY` |
| Any other token | `ANTHROPIC_AUTH_TOKEN` |
| Non-empty gateway address | `ANTHROPIC_BASE_URL` |
| Non-empty model name | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` written together |

The file path is `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, and the parent directory is created automatically. It's written as a **full overwrite**, skipping keys with empty values, followed by `chmod 0600`, and then loaded into effect immediately — no need to reopen your shell. The first line is always a comment reminding you not to commit it into version control.

### Gate two: do the credentials work {#第二道-凭证能不能用}

Once the configuration is complete, it prints `- 验一下凭证…` and then **actually fires one API call**.

Probe details: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, 20-second default timeout, using stdlib `urllib` so no dependency is pulled in. The model is taken in the order `ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. If `ANTHROPIC_API_KEY` is present it uses the `x-api-key` header, otherwise `authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` is deliberately set to 16 rather than 1: in practice, models with forced chain-of-thought can't even fit their thinking, and the server struggles for 30 seconds before returning; with 16 it takes only 3.6 seconds.

The probe's conclusion is handled in three classes, and **the differences matter**:

| Conclusion | Trigger | What flower does |
|---|---|---|
| `auth` | HTTP 401 / 403, or no credentials at all | Prints `! 凭证被拒:<响应体前 160 字>`, starts interactive reconfiguration, and verifies again afterwards. Non-interactive → exit code 1 |
| `config` | HTTP 404, or 400 with `model` mentioned in the body | Prints `! 网关地址或模型名不对:<…>`, same as above |
| `net` | Can't connect / timeout / DNS failure / TLS failure / 5xx | Prints `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **doesn't make you reconfigure, just starts** |
| `ok` | Under 400, or anything undeterminable, is let through | Silently continues |

The `net` case is deliberate: a network hiccup shouldn't force you to retype your token, and flower itself has a mechanism for suspending and reconnecting when the network drops. Don't worry when you see "探针没打通" — just keep going.

The reconfiguration chance is given **at most once**. A second failure exits.

### Auto-reconfiguration after a crash {#跑挂了之后的自动重配}

When the workflow fails, flower matches the error message of the failing step against a regex (401, `invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). On a hit, and when stdin is a terminal, it prints `! 看起来是凭证不对:<前 120 字>` on the spot and starts interactive configuration; once configured it prints:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

Then it exits with code 1 regardless. The `once` path doesn't have this.

---

## Exit codes {#退出码}

| Code | When |
|---|---|
| `0` | Finished normally |
| `1` | Every deliberate exit. The message goes to **stderr**, with no traceback. Full list below |
| `2` | argparse argument error: unknown flag, missing positional, `-p` given a value outside its choices |
| `130` | Ctrl+C pressed twice in a row mid-run. An uncaught `KeyboardInterrupt`, **with a Python traceback** |
| Killed by signal | SIGHUP / SIGTERM: first writes the in-flight step into the manifest, then leaves via the default action |

All the exit-code-1 messages:

| Message | When |
|---|---|
| `已取消` | Ctrl-C or Ctrl-D at the startup prompt |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Fresh directory + plain Enter |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 lines total) | Non-interactive + no credentials |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe verdict `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe verdict `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` used in a non-git directory |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Empty request and the directory has no wake state |
| `在步骤 '<步骤名>' 中止` | A step in the workflow failed and the policy is to stop |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, colon missing |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | Import of the target module failed |
| `'<模块>' 里没有 '<属性>'` | The attribute isn't in the module |

At the end (on the `go` / `run` paths) it prints one last line:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

This amount only counts **this process's** cost, not the previous run's — even though the manifest file itself accumulates across processes.

---

## What it creates in your project {#它在项目里创建了什么}

Two trees: `<run_dir>/` (default `./runs/`, relative to CWD) holds bookkeeping and sessions; `<workspace>/.flower/` holds the [workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Path | Contents |
|---|---|
| `runs/sessions.db` | SQLite, the full transcript. This is the physical basis for [continuity](glossary.md#接续) working at all |
| `runs/manifest.json` | The [run manifest](glossary.md#运行清单). A JSON array, **accumulating across processes**; every number on the case-study pages can be recomputed from here |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Written by atomic replace |
| `runs/aside/` | The oracle Q&A's separate Runtime, with its own `sessions.db` and `manifest.json`. **Cost and lineage don't mix into the main manifest** |
| `runs/workbench/` | Only appears when `-W` was used and the workflow doesn't bring its own workbench (`run` / `once` paths) |

The fields of each record in `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` is this process's marker, formatted `YYYYmmdd-HHMMSS-<6 hex digits>`. The spill policy is **append, not overwrite**: before each write it re-reads the file and dedupes by `run` — rows belonging to this process are replaced with the latest, rows from other processes are left as they are.

Step names take four forms:

| Form | When |
|---|---|
| `<步骤名>` | First attempt |
| `<步骤名>#retry<N>` | Ordinary retry |
| `<步骤名>#round<N>` | Sent back by a failed verdict to keep going |
| `<步骤名>·判定#<N>` | The [judge](glossary.md#判定者)'s step |

When killed by a signal, the in-flight step is written in too, with the `error` field set to `killed-by-signal`.

**Running several flowers in parallel in the same directory**: `manifest.json` is safe (re-read + merge by `run`), but `lineage.json` is a full overwrite, so two processes will clobber each other's lineage for identically named steps. If you want parallelism, use different `-r`.

`lineage.json` stores the workspace's absolute path. If it doesn't match, it's treated as absent and **silently** falls back to a new session without erroring — after the directory has been copied elsewhere, the old `session_id` wouldn't be findable anyway.

### `.flower/` {#flower-目录}

| Path | Contents |
|---|---|
| `.flower/scripts/` | Scripts meant to be run a second time. The first line says `# desc: 一句话`, and that sentence shows up in the index |
| `.flower/artifacts/` | Long outputs over 2000 characters: reports, data, logs. Only the path appears in the conversation |
| `.flower/notes/` | Cross-step decision records |
| `.flower/spill/` | [Spill](glossary.md#落盘): tool results over 4000 characters land here, and the context keeps only a one-line pointer plus the first 400 characters. The file name is the first 16 digits of the content's sha256 plus `.txt` |
| `.flower/INDEX.md` | An index of the directories above, **injected into the coordinator's system prompt** (subagents don't inherit it) |

The `go` path always generates these under `notes/`:

| File | Contents |
|---|---|
| `notes/需求.md` | The frozen [brief](glossary.md#需求确认书), four sections: goals / acceptance criteria / boundaries / unknowns and assumptions |
| `notes/目标.md` | The frozen goals, two sections: goals / verdict checklist |
| `notes/问答记录.md` | An appended record of every question and answer (with status), including things you said on your own initiative. **Doesn't enter the context, kept purely as a record** |
| `notes/交接-<步骤名>.md` | The [handoff document](glossary.md#交接书) written at handoff; the previous generation is filed into `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | The `lineage.json`, `需求.md`, `目标.md` archived by `--new` or `/new`. A **move**, not a delete |

With `--isolate` the workbench moves outside the repo: `<workspace>.parent/.flower-<workspace name>/`. A worktree is each agent's private copy, while the workbench is a shared layer across agents, and shared things can't live inside a private fence. In this case the workbench path given to the model is absolute.
