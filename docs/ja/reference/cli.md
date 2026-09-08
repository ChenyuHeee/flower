# CLI reference

Once installed, `flower` is a single executable with 4 subcommands and 23 flags. This page lists them all: the type, default value, and exact semantics of every flag, plus how to talk to it mid-run, what it asks on first launch, what the exit codes are, and which files it puts in your directory. After reading this page you shouldn't need to open the source.

Source: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcommand | What it does | Positional args | Own flags |
|---|---|---|---|
| `go` | The whole chain: clarify the request → set goals → dispatch workers → judge each round. The default when no subcommand is written | `ask` (optional) | 11 |
| `run` | Run a [workflow](glossary.md#流程) you wrote yourself | `target` (required) | 0 |
| `once` | Run a single agent once — no workflow, no verdict | `prompt` (required) | 6 |
| `setup` | Configure credentials, written to `~/.config/flower/.env` | none | 0 |

Total flags 23 = 5 global + 11 specific to `go` + 6 specific to `once` + `-h/--help`. `run` and `setup` have no flags of their own.

---

## Invocation forms {#调用形式}

All of `flower`'s argv first passes through `_with_default_cmd()` to fill in the default subcommand, then goes to argparse (`cli.py:1437-1439`). That's why `flower "帮我做一个 X"` works — it gets rewritten into `flower go "帮我做一个 X"`.

The rules for filling in the default subcommand (`cli.py:940-976`):

1. The set of global flags is **derived from the main parser itself**, not a hardcoded list. Those with `nargs == 0` count as pure flags; the rest count as value-taking flags.
2. Scan left to right, skipping global flags. Value-taking ones skip their value too, and the `=` form such as `--workspace=/tmp` is recognized as well.
3. Stop at the first token that isn't a global flag. If it is one of `go`, `run`, `once`, hand it to argparse as-is; **otherwise insert a `go` before it**, so it becomes the body of `go`'s request.
4. If the scan finishes without hitting a positional (empty argv, or only global flags) → append `go` at the end, and enter interactive input.
5. Exception: when argv contains `-h` or `--help`, return it as-is and let argparse print help.

The constant used for the decision is `_CMDS = ("go", "run", "once")` (`cli.py:937`) — **`setup` is not in it**; see [`setup`](#setup) for the consequences.

### What the rewriting actually produces {#实际的改写结果}

| What you typed | What it actually parses into | Effect |
|---|---|---|
| `flower` | `["go"]` | Interactively asks "要做什么?" |
| `flower -v` | `["-v", "go"]` | Same, with verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Starts right away |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Global flags may go in front |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | The `=` form is recognized too |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Subcommand flags may go after the request |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | Or in front |
| `flower --new` | `["go", "--new"]` | Flag only, no request → interactive input |
| `flower once "hi"` | `["once", "hi"]` | As-is |
| `flower run flows:main` | `["run", "flows:main"]` | As-is |
| `flower run` | `["run"]` | argparse reports missing `target`; it will **not** be treated as a request |
| `flower go run` | `["go", "run"]` | Explicit disambiguation: the request body is literally `run` |
| `flower setup` | `["go", "setup"]` | Runs `go`, with the request becoming the string `setup`; see [`setup`](#setup) |
| `flower --help` | As-is | argparse prints help |

The two words `run` and `once` **cannot** be used directly as a request body; this ambiguity is deliberately preserved (`cli.py:949-950`). To use them as a request, write `flower go run`.

### Six usable forms {#六种能用的写法}

```bash
flower                                    # 1. 裸跑:交互问“要做什么?”或“接着上次?”
flower "帮我做一个 X"                       # 2. 位置参数给诉求
echo "帮我做一个 X" | flower --timeout 0    # 3. 管道喂 stdin
flower once "读一眼这个仓库"                 # 4. 单 agent
flower run flows.py:main                  # 5. 跑自定义流程
flower go setup                           # 6. 显式 go,把 setup 当诉求正文
```

The module form `python -m flower.cli` is equivalent to `flower` (`cli.py:1451-1452`). The container wrapper `docker/flowerbox` takes exactly the same arguments as `flower`.

### Feeding stdin through a pipe {#管道喂-stdin}

When `sys.stdin.isatty()` is false, `ask_for_prompt()` **does not print the prompt header** and directly does `input("> ")` to read one line (`cli.py:993-1001`). So `echo "..." | flower` works.

But a warning line is printed afterwards, and the stdin thread immediately reads EOF and exits:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

A piped run should be paired with `--timeout 0`: questions no longer pretend to wait 30 minutes, they fail immediately, and the agent decides for itself and writes the assumptions into the "未知与假设" section of the brief.

---

## Subcommands {#子命令}

### `go` {#go}

Help text: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1275-1307`).

Positional argument `ask`, `nargs="?"` — omit it and you get interactive input. This is the most common entry point; `flower "做 X"` goes through it.

What it does (`cli.py:1190-1221`):

1. `ensure_credentials()` — check credentials, and actually fire one API probe; see [First-run configuration flow](#首次运行的配置流程).
2. [Wake](glossary.md#唤醒) detection: read-only glance at whether this directory has been used, without writing a single byte.
3. If no `ask` was given, print a prompt and ask; typing `/new` is equivalent to `--new`, and then it **asks again** for the request.
4. If this is a [continuity](glossary.md#接续), print a one-line wake banner.
5. Build a three-step [workflow](glossary.md#流程): `确认需求` → `设定目标` → `干活`, with a `干活·判定#N` following each work round. `--clarify-only` keeps only the first step.
6. Start running.

The wake banner looks like this (the home directory in the path is replaced by `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` is always present; `目标 N 条` only appears when there is a verdict checklist; `干活上下文 X` requires that the last round's context for that [session](glossary.md#会话) can be looked up in `sessions.db` — if not found, it isn't shown.

!!! warning "`-W` and `-T` are silently overridden on the `go` path"
    Writing these two global flags on `go` has no effect — no error, no notice:

    - `-W/--workbench`: the workflow `go` builds always comes with its own [workbench](glossary.md#工作台), and the code takes `getattr(wf, "workbench", None) or args.workbench` (`cli.py:1038`) — the workflow's own always wins. So the workbench is always `<workspace>/.flower/` (or `<workspace>.parent/.flower-<name>/` under `--isolate`), and `-W` cannot change it.
    - `-T/--trim`: `go` goes through `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1221`), directly using the inverse of `--no-trim` and **never looking at `args.trim` at all**. In other words, on the `go` path [trim](glossary.md#裁剪) is on by default, and the only way to turn it off is `--no-trim`.

    These two flags only take effect on `run` (when the workflow doesn't bring its own workbench) and `once`.

#### The 11 flags of `go` {#go-的-11-个开关}

| Flag | Type | Default | Description |
|---|---|---|---|
| `--asks N` | int | `-1` | Question quota. `-1` or any negative number = **unlimited**; `0` = no questions allowed, the first question yields `over_budget`; `N` = a hard quota. When over quota the tool simply refuses, without blocking the run |
| `--rounds N` | int | `3` | Cap on the **total number of rounds** of work, not extra rounds. At the end of each round an independent [judge](glossary.md#判定者) rules on "is it done", and if not it's sent back to continue on the same session |
| `--no-goal` | flag | `False` | Turn off the [goal guard](glossary.md#目标看守): don't generate `目标.md`, don't produce a [verdict](glossary.md#判定); once the work finishes, it's done |
| `--judge-can-run` | flag | `False` | Let the judge run commands. The verdict gets harder, at the cost of the judge also being able to modify the workspace |
| `--timeout SECONDS` | float | `1800.0` | How long to wait for a human answer. `0` or negative = fully automatic, all questions fail **immediately** with no pretense of waiting. See [Timeout](#超时) for semantics |
| `--isolate` | flag | `False` | Give each [subagent](glossary.md#subagent) its own git worktree, i.e. [isolation](glossary.md#隔离). **Requires the workspace to be a git repo**, otherwise exit code 1. Also moves the workbench outside the repo |
| `--window N` | int | none (inferred from model name) | Model context window. When not given: model name containing `1m` or not containing `haiku` → 1,000,000; containing `haiku` → 200,000. At `window − 50000` it writes a [handoff document](glossary.md#交接书) and does a [handoff](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Turn off handoff, falling back to the SDK's own [compact](glossary.md#压缩) |
| `--new` | flag | `False` | Don't continue from last time. **Move** (not delete) the previous segment's `lineage.json` + `需求.md` + `目标.md` into `notes/archive/<YYYYmmdd-HHMMSS>/`, then start over |
| `--clarify-only` | flag | `False` | Only do the [clarify](../guide/clarify.md), no work afterwards — only the `确认需求` step remains in the workflow |
| `--no-trim` | flag | `False` | Turn off trim. On the `go` path trim is **on** by default, and this is the only way to turn it off |

Edge cases in values — none of them error, none of them warn:

- `--rounds 0` and `--rounds 1` are equivalent — internally it's `retries = max(0, rounds - 1)`, both run 1 round.
- Any negative value for `--asks` means unlimited, not just `-1`.
- Any negative value for `--timeout` equals `0`, i.e. fully automatic.
- `--window 0` is **silently ignored** (`0` is falsy and simply isn't passed down), falling back to the default inferred from the model name. Negative values do get passed down, and are then floored to `10000`.
- `--clarify-only` is a **no-op** on an already-clarified directory — the `确认需求` step sees a complete `需求.md` and skips, and since that's the only step in the workflow, nothing happens (other than wake count +1). To re-clarify you need `--new`.
- The end of `go`'s `--help` says "全局开关(-v/-w/-r/-T)见 `flower --help`" — this line **omits `-W`**.

### `run` {#run}

Help text: `运行一个 workflow` (`cli.py:1309-1312`).

Positional argument `target`, written as `module:attribute`. Both forms are supported (`cli.py:1010-1031`):

```bash
flower run mypkg.flows:build     # 按模块名 import
flower run flows.py:build        # 文件路径;会把父目录塞进 sys.path 再按文件名 import
```

If the attribute obtained is callable, it is called once and the return value is used as the [workflow](glossary.md#流程); if it is already a workflow object, it is used directly.

**`run` has no flags of its own**, only the 5 global flags. So on this path things like `--window` and `--no-handoff` all take their default values (the code falls back with `getattr`, `cli.py:1041-1043`). To adjust them, write the parameters into your own workflow.

### `once` {#once}

Help text: `跑一次单 agent` (`cli.py:1314-1324`). The positional argument `prompt` is required.

It constructs an `AgentSpec(name="ad-hoc", …)` and runs it directly, **without going through `_drive`**. So on `once` there is no:

- Ctrl-C interrupt-and-speak (pressing it is just a plain `KeyboardInterrupt`)
- stdin answering thread, or the input prompt pinned to the bottom
- oracle Q&A
- SIGHUP / SIGTERM rescue accounting
- closing line `总花费 … · 清单 …`
- automatic reconfiguration guidance after credential failure

In the [run manifest](glossary.md#运行清单), the name of this step is fixed as `ad-hoc`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-i`, `--instructions` | str | empty | Domain instructions, [appended](glossary.md#叠加) **after** Claude Code's native system prompt, not replacing it |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Comma-separated tool allowlist. When not given, it's these three read-only tools |
| `-p`, `--permission-mode` | str | `default` | The value must be one of `default`, `acceptEdits`, `plan`, `bypassPermissions`; anything else makes argparse error out with exit code 2 |
| `-b`, `--budget` | float | no cap | Dollar [budget](glossary.md#预算) cap; stops when exceeded |
| `--resume SESSION_ID` | str | none | Continue an existing session |
| `--fork` | flag | `False` | Fork instead of continue; used together with `--resume` |

!!! warning "The elapsed time and cumulative cost shown by `once` are always 0"
    `once` creates a new renderer instance for every event it receives (`cli.py:688-690`, `cli.py:1239`), while the timing origin and cumulative cost live on the instance (`cli.py:500-501`). Therefore:

    - The `用时` on the closing line is always `0:00`
    - The `累计 $0.00` in the status line is always 0, and `上下文` never accumulates either

    The real cost of the single step must be read from the `cost_usd` field in `runs/manifest.json`. The `go` and `run` paths hold the same renderer instance and don't have this problem.

### `setup` {#setup}

Help text: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1326-1328`). It has no flags.

What it does: read `.env` → determine whether it's been configured → launch the interactive configuration flow, with `reason` being `重新配置。` or `还没配过凭证。`. For the screen contents see [First-run configuration flow](#首次运行的配置流程).

!!! warning "`flower setup` currently cannot reach this subcommand"
    The constant used to decide the default subcommand, `_CMDS = ("go", "run", "once")` (`cli.py:937`), **omits `"setup"`**, even though `setup` is indeed registered in the parser (`cli.py:1326`). So `flower setup` gets rewritten into `flower go setup` — **it runs the full `go` workflow with the request body being the string `setup`**: first verify credentials, then clarify the request, then actually start dispatching workers. Adding global flags doesn't help either: `flower -v setup` → `["-v", "go", "setup"]`.

    **No argv whatsoever can reach the `setup` subcommand.**

    To configure credentials, there are currently only two routes, both of which reach the same interactive interface:

    - Just run `flower "随便一句诉求"`; if credentials haven't been configured it will ask first;
    - Or hand-write `~/.config/flower/.env`; for the key names see [The keys it writes](#写出来的键).

    A few pieces of copy are affected too: the ``跑 `flower setup` 重配。`` printed when credentials are rejected, and the comment on the first line of `.env`, ``由 `flower setup` 写``, both point at this unreachable command.

---

## Global flags {#全局开关}

The 5 global flags are attached to the main parser and to every subcommand at the same time (`cli.py:1250-1266`). The copies on subcommands use `argparse.SUPPRESS`, so when not given they don't write an attribute — which means **they can be written before or after the subcommand**, without overriding each other. The side effect is that they don't appear in a subcommand's `--help` — to see them run `flower --help`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | The agent's working directory. It gets `resolve()`d into an absolute path and `mkdir -p`'d. The [workbench](glossary.md#工作台) `.flower/` is created inside it |
| `-r`, `--run-dir` | str | `runs` | Directory for the [session store](glossary.md#会话存储) and the run manifest. **Relative to the current CWD, not to the workspace** |
| `-v`, `--verbose` | flag | `False` | Print more; see below |
| `-W`, `--workbench` | flag | `False` | Enable the workbench. **No effect on `go`**; only takes effect on `run` (when the workflow doesn't bring its own workbench) and `once`, in which case the workbench lands at `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | On resume, replace old large tool results with file pointers, i.e. [trim](glossary.md#裁剪). **No effect on `go`**; that path controls it inversely via `--no-trim` |
| `-h`, `--help` | flag | — | Every parser has it. When it appears in argv, the default-subcommand rewriting is skipped and help is printed directly |

The fact that `-r/--run-dir` is relative to CWD will bite you: `flower -w /other/proj "做 X"` creates `runs/` in **the directory where you typed the command**, while `.flower/` is created under `/other/proj/` — two pieces of state split apart. To keep them together, pass `-r /other/proj/runs` explicitly.

The help for `-v` says "显示思考与工具结果", but the [main thread](glossary.md#主线程)'s thinking is **shown by default**. What `-v` actually additionally enables is:

- subagent body text (not shown by default, only its tool calls are)
- normal tool results (by default only failing ones are shown)
- `prompt` events
- printing the currently effective credential configuration before startup, with tokens masked to the first 4 characters

That last one uses a bare `print()`, **bypassing output sanitization, without wrapping, and unprotected by the terminal write lock**; when running several `flower` processes in parallel these lines may get torn apart.

---

## How to talk to it mid-run {#运行中怎么和它说话}

Once the run has started, the terminal is **continuously reading your input**. You don't need to wait for it to ask, and you don't need to press anything to enter input mode — the last line is always the one you can type on.

### The input prompt pinned to the bottom {#常驻在最下面的输入提示符}

There is a daemon thread `flower-stdin` reading stdin the whole time (`cli.py:764-934`), polling with `select` every 0.2 seconds rather than doing a blocking read (so a stop signal can wake it; on streams that don't support `select`, such as on Windows, it degrades to a blocking read).

**It reads all the time, not only when there's a question.** The reason: if it only read while a question is pending, whatever you typed during those hours of work would sit in the terminal buffer and be swallowed as the answer to the next question — the question would be answered before you'd even seen it.

On the display side, `_say()` is the only output path; before each output it erases the prompt and redraws it afterwards (`cli.py:309-315`), so the prompt never gets pushed up the screen by event output. **On redraw, even the few characters you typed but haven't hit Enter on are drawn back** — they're kept in `_PROMPT["buf"]` (`cli.py:183-192`). Without this the content wouldn't actually be lost (it's still in the terminal's line buffer, and Enter still sends it), but you couldn't see it, so you'd be unsure and retype it.

The prompt has two wordings, switching on whether there's a pending question:

| State | Last line on screen |
|---|---|
| Question pending | `你的回答 (回车=跳过,让它自己判断) > ` |
| No question pending | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Character-by-character input mode and keybindings {#逐字符输入}

To draw "the half-typed characters" back, flower has to take over input itself. When stdin is a terminal and `termios` can be imported, the terminal is set to `cbreak` **before** the `flower-stdin` thread is started (`cli.py:793-807`) — `cbreak` rather than `raw`, so that Ctrl+C still produces `SIGINT` and the whole [Ctrl-C](#ctrl-c) mechanism still exists. It must be set before the thread starts: doing it inside the thread is a genuine race, and characters typed in the instant before the thread gets CPU would be swallowed by line mode, showing up as "input lost" (reproduced reliably once in three tries in testing, `cli.py:928-934`).

If it can't be set, it falls back to the original whole-line `readline()` (non-terminal, `termios` unavailable, `tcgetattr` failure). Both paths work; line mode just doesn't have the keybindings below (`cli.py:883-899`).

The editing logic lives in `LineEditor` (`cli.py:320-414`) — a pure state machine that never touches the terminal:

| Key | Effect |
|---|---|
| Printable characters | Inserted at the cursor. UTF-8 uses an incremental decoder, entering the buffer only once a full character is assembled |
| Backspace / Ctrl+H | Delete **one character** before the cursor. In line mode the terminal deletes by byte, so a Chinese character takes three presses and leaves garbage; not here |
| ← / → | Actually move the cursor. The whole escape sequence is consumed, so things like `[A` don't get inserted into the input |
| Home / End (or `[1~` / `[4~`) | Jump to line start / line end |
| Delete (`[3~`) | Delete one character forward |
| Ctrl+A / Ctrl+E | Line start / line end |
| Ctrl+U | Clear the whole line |
| Ctrl+D | EOF only when the buffer is empty; ignored when there's content |
| ↑ / ↓ | **Do nothing.** There is no history, and moving would make people think something was lost (`cli.py:335`) |
| Other control characters | Ignored |

Enter hands the buffer over and clears it, while moving down a line on screen — what you said stays above (`cli.py:811-827`).

### Where what you typed goes {#你敲的东西去哪了}

| Your input | With a question pending | With no question pending |
|---|---|---|
| **Empty line (just Enter)** | Skip this question, let it decide for itself | Nothing happens |
| **Starting with `?`** | Oracle Q&A, see below | Same as left |
| **Pure digits**, within the option range | Substituted with the corresponding option and answered | Treated as ordinary text |
| Other text | Sent as the answer to the asking agent | Goes to the inbox as an additional requirement |
| EOF (Ctrl-D or pipe closed) | Refuse this question, remove the prompt, thread exits | Remove the prompt, thread exits |

When it goes to the inbox, a receipt line is printed:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

When there is no [brief](glossary.md#需求确认书) to spill to, the second half becomes `没有确认书可落盘 —— 它可能活不过下一个步骤`. The inbox **does not interrupt** the worker currently working; it's picked up only the next time the worker checks the inbox on its own. The same sentence is also appended to `notes/需求.md`; without spilling it wouldn't survive a step boundary — the next step is a new session that only reads frozen artifacts.

### Starting with `?` = oracle Q&A {#旁路问答}

A line starting with `?` is not sent to the running agent, but handed to the [oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

It starts a **separate** Runtime with `run_dir` at `<run_dir>/aside/`, so its cost and session lineage don't get mixed into the main `manifest.json`. The role is read-only, its tools are only `Read`, `Glob`, `Grep`, at most 12 turns, with a cost cap of **$0.5**. The context it sees is the most recent **60** events (`thinking` and `prompt` events don't enter this window), each truncated to 200 characters, plus a description of the workbench paths.

It runs **concurrently**; the ongoing run doesn't wait a single second. The answer looks like this:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

On failure it prints a red line `# 旁路问答失败:<类型>: <消息>`, which **does not affect the main workflow**. On exit it waits at most **120 seconds** for the oracle to finish, printing `(等 N 条旁路问答收尾…)` before waiting.

What it says never enters that run's context — asking doesn't affect the run, and the answer is discarded once given.

!!! warning "A full-width `？` does not trigger oracle Q&A — Chinese IME users will hit this"
    The line of code deciding oracle Q&A is (`cli.py:907`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Both characters are **half-width ASCII `?`** (`0x3f`) — verified byte by byte. From the way it's written the intent was clearly to accept both the half-width `?` and the full-width `？` (U+FF1F) produced by a Chinese IME, but it ended up as the same character twice.

    Consequence: **a line starting with a full-width `？` is not treated as an oracle question**, but is silently sent to the inbox as an "additional requirement", and thereby appended to `notes/需求.md`. The receipt you see is `+ 收到`, not `# 旁路`.

    To ask the oracle you **must use the half-width `?`** — switch your IME to English before typing, or at least type the first character half-width.

### What's on the screen {#屏幕上都是什么}

The icons are **all ASCII**, not emoji (`cli.py:51-69`). The reason is written in a code comment: emoji together with box-drawing, geometric, and arrow characters trigger terminal glyph fallback, which once caused two terminal crashes.

| Icon | Meaning | Icon | Meaning |
|---|---|---|---|
| `=` | Step separator | `+` | Done / answered / received |
| `~` | Thinking, retry | `x` | Failure / error |
| `>` | Dispatch | `#` | Handoff, oracle, task |
| `*` | Tool call | `-` | Status line, list item |
| `?` | Question | `<-` | Continue from last time, handoff landing point |
| `!` | Warning / interrupt | `.` | Skipped |
| `\| ` | Indentation bar for subagents | | |

!!! warning "The `❓` and `↩` in the old docs don't exist in a real terminal"
    Early documentation used `❓` for questions and `↩` for the wake line. **The code never used those two characters** — the question icon is a half-width `?`, and the icon for wake and handoff landing points is the two ASCII characters `<-`.

    So what a real terminal prints is:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    Not `❓ 这个工具……`, and not `↩ 在 ~/proj 接上上次`. Grepping logs based on the old docs will find nothing.

The five states of a question appear on screen as:

| State | Screen output |
|---|---|
| Asked | `  ? <问题>`, followed by options listed one per line as `     1) 选项一`, plus `     (还能问 N 次)` when there's a quota |
| Answered | `  + <答案>` |
| Timed out | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Quota exhausted | `  ! 提问额度用完` |
| You skipped | `  . 已跳过` |

When `--asks` is unlimited (the default), the trailing "还能问 N 次" line is not shown.

When [handoff](glossary.md#换代) finishes writing the handoff document, it's a whole block:

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

The output also does two things you don't see: every output line passes through sanitization that **only lets through flower's own SGR color codes**, while screen-clearing and cursor-moving sequences emitted by the model or tools are swallowed whole; and the width is taken as `max(40, min(terminal columns, 110))`, so on a wide terminal it doesn't fill the whole line — that's intentional.

### The prompt at launch {#起跑时的提示符}

Running bare `flower` (without a request) asks first. Two wordings:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

The second only appears when this directory has already been run in and `需求.md` has all four sections.

This prompt reads via `input()`, **without going through shell parsing**. Chinese quotation marks, spaces, and exclamation marks can all be typed directly — that's the entire reason it exists. zsh, on hitting a Chinese closing quotation mark, drops into a `dquote>` continuation line, which looks like a hang, when in fact it never launched at all.

- Empty input + first time → exit, printing ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Empty input + wake → **valid**, meaning "keep going"
- Typing `/new` → equivalent to `--new`; archives the previous segment and then **asks again** for the request
- Ctrl-C / Ctrl-D → exit, printing `已取消`

### Timeout {#超时}

`--timeout` is a float in seconds, defaulting to `1800.0`. Three kinds of values:

| Value | Behavior |
|---|---|
| `> 0` | Wait this many seconds. On timeout the question settles as `timeout` and the agent decides for itself |
| `0` or negative | **Fully automatic.** The question doesn't enter the wait queue, doesn't emit an `asked` event, doesn't appear on screen, and settles as `timeout` immediately |
| Wait forever | **Not achievable from the command line.** Internally "wait forever" is supported, but `--timeout` is a float with a default value, and no way of writing it produces that. The ceiling is just passing a very large number of seconds |

`--timeout 0` and `--timeout -1` are exactly equivalent. Piped runs, CI runs, and unattended runs all use this.

When a question gets no answer, the tool result fed back to the model is fixed copy, of four kinds:

| Result | Copy fed back to the model |
|---|---|
| Quota exhausted | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| You skipped | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| Question was empty | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**Ctrl-C means completely different things in two places.**

**Pressed at the launch prompt `> `** — exits the program immediately, printing `已取消`.

**Pressed mid-run** — interrupts the current round and gives you one chance to speak:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Just hitting Enter here means interrupt without saying anything, and keep going. If there were pending questions at the time, an extra line is printed: `  (有 N 个提问还等着,打断不影响它们)`.

**Pressing Ctrl+C a second time really exits**, and it's an uncaught `KeyboardInterrupt` — you'll get a Python traceback on screen, not a clean exit.

The interrupt is cooperative: it breaks cleanly at a message boundary, without hard-cancelling tasks. It **does not count as a failed attempt** and doesn't consume a retry. On resume a note is attached telling the model that "in-flight tool calls returning interrupted is a normal side effect of the interrupt, not an environment failure".

This custom Ctrl-C is installed only when `sys.stdin.isatty()` (`cli.py:1097`). When running in a pipe, Python's default behavior is kept, i.e. it exits on the first press. The `once` path doesn't go through here, so Ctrl-C on `once` also exits on the first press.

### SIGHUP / SIGTERM {#sighup-sigterm}

The `go` and `run` paths install handlers for both `SIGHUP` and `SIGTERM`: first write **the in-flight step** into `manifest.json` too, marked as `killed-by-signal`, then restore the default action and really leave.

The cause was that when the terminal crashes the kernel sends SIGHUP, whose default action terminates the process outright — `finally` doesn't run, the manifest isn't written, and a whole run's accounting is lost. On a non-main OS thread, or on platforms without support, it's silently skipped.

---

## First-run configuration flow {#首次运行的配置流程}

All three entry points `go`, `run`, `once` call `ensure_credentials()` at the start (`cli.py:1392-1428`), with **two gates**.

### Gate one: are there credentials {#第一道-有没有凭证}

It searches for credentials in priority order. If neither `ANTHROPIC_API_KEY` nor `ANTHROPIC_AUTH_TOKEN` is found, it launches the interactive configuration; when non-interactive (stdin is not a terminal) it doesn't block, and simply prints this and exits:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Two things in this copy don't match the implementation: the `flower setup` on the second line currently can't be reached (see [`setup`](#setup)); and the fourth line is **the opposite of the code** — flower does treat the `env` block of `~/.claude/settings.json` and `settings.local.json` as a **last-level fallback**, borrowing only 9 credential keys from it and taking over no other settings. The place that prints this line is `env.py:192` (the function `check_credentials()` is defined at `env.py:184`), while the code that actually reads those two files is `env.py:56-75` and `:109-111`; recorded as [issue #13](https://github.com/ChenyuHeee/flower/issues/13). **The code is authoritative: it does read them.** For the full lookup priority and those 9 keys, see the [configuration reference](config.md#借用).

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
- When stdin is not a terminal the whole flow is skipped outright, without blocking.

### The keys it writes {#写出来的键}

| What you entered | The key it's written as |
|---|---|
| Token starting with `sk-ant-` | `ANTHROPIC_API_KEY` |
| Any other token | `ANTHROPIC_AUTH_TOKEN` |
| Non-empty gateway address | `ANTHROPIC_BASE_URL` |
| Non-empty model name | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` — all three written together |

The file path is `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, and the parent directory is created automatically. The write is a **full overwrite**, keys with empty values are skipped, `chmod 0600` follows, and it's loaded into effect immediately — no need to reopen the shell. The first line is always a comment reminding you not to commit it into version control.

### Gate two: do the credentials work {#第二道-凭证能不能用}

Once configuration is complete, it prints `- 验一下凭证…` and then **actually fires one API call**.

Probe details: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, default timeout 20 seconds, using stdlib `urllib`, no dependencies pulled in. The model is taken in the order `ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. If `ANTHROPIC_API_KEY` is present it uses the `x-api-key` header, otherwise `authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` is deliberately 16 rather than 1: in testing, models with forced chain-of-thought can't even fit their thinking in, and the server struggles for 30 seconds before returning; with 16 it takes only 3.6 seconds.

The probe's conclusion is handled in three categories, and **the differences matter**:

| Conclusion | Trigger condition | What flower does |
|---|---|---|
| `auth` | HTTP 401 / 403, or no credentials at all | Prints `! 凭证被拒:<响应体前 160 字>`, launches interactive reconfiguration, and verifies once more afterwards. Non-interactive → exit code 1 |
| `config` | HTTP 404, or 400 **and** the response body explicitly says not found / doesn't exist (one of `not_found`, `not found`, `does not exist`, `unknown model`, `no such model`, `invalid model`) | Prints `! 网关地址或模型名不对:<…>`, then as above |
| `net` | Can't connect / timeout / DNS failure / TLS failure / 5xx | Prints `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **doesn't make you reconfigure, just starts running** |
| `ok` | Less than 400, or anything undecidable, is let through | Silently continues |

The criterion for `config` has been **tightened**: the word `model` almost inevitably appears in Anthropic-style error JSON, so using it as "wrong model name" would misjudge a transient 400 as a configuration error and then force a reconfiguration — it has to explicitly say "not found / doesn't exist" to count (`env.py:176-182`).

The `net` case is deliberate: a network hiccup shouldn't force you to retype your token, and flower itself has a mechanism for hanging and reconnecting when the network goes down. If you see "探针没打通", ignore it and keep running.

The chance to reconfigure is given **at most once**. A second failure exits.

**The probe is only fired in an interactive terminal.** `ensure_credentials()` returns immediately without making that one API call if any of the following holds (`cli.py:1413`): the caller passed `probe=False`, [`FLOWER_NO_PROBE`](config.md#行为开关) is set, or **stdin is not a terminal** (pipe / CI / offline tests). The reason is that in a non-interactive setting you can't fix what the probe finds anyway, so its only effect is "failing early" — and failing early is worse than not probing when the probe **misjudges**. If the credentials really are bad, the run will blow up on its own, and that path is caught by [automatic reconfiguration after a crash](#跑挂了之后的自动重配).

### Automatic reconfiguration after a crash {#跑挂了之后的自动重配}

When the workflow fails, flower matches the error message of the failing step against a regex (401, `invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). On a match, and when stdin is a terminal, it prints `! 看起来是凭证不对:<前 120 字>` on the spot and launches interactive configuration; once configured it prints:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

Then it exits with code 1 regardless. The `once` path doesn't have this.

---

## Exit codes {#退出码}

| Code | When |
|---|---|
| `0` | Ran to completion normally |
| `1` | All deliberate exits. The message goes to **stderr**, with no traceback. Full list below |
| `2` | argparse argument error: unknown flag, missing positional, `-p` given a value outside its choices |
| `130` | Two consecutive Ctrl+C presses mid-run. It's an uncaught `KeyboardInterrupt`, **with a Python traceback** |
| Killed by signal | SIGHUP / SIGTERM: first write the in-flight step into the manifest, then leave via the default action |

All exit-code-1 messages:

| Message | When |
|---|---|
| `已取消` | Ctrl-C or Ctrl-D at the launch prompt |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Brand-new directory + plain Enter |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 lines total) | Non-interactive + no credentials |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe ruled `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe ruled `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` used in a non-git directory |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Request empty and the directory has no wake |
| `在步骤 '<步骤名>' 中止` | A step in the workflow failed and the policy is to stop |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, missing the colon |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | Importing the target module failed |
| `'<模块>' 里没有 '<属性>'` | The attribute isn't found in the module |

When it finishes (the `go` / `run` paths), the last line printed is:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

This amount only counts **this process's** cost, not the previous run's — even though the manifest file itself accumulates across processes.

---

## What it creates in your project {#它在项目里创建了什么}

Two trees: `<run_dir>/` (default `./runs/`, relative to CWD) holds accounting and sessions; `<workspace>/.flower/` holds the [workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Path | What's in it |
|---|---|
| `runs/sessions.db` | SQLite, the full transcript. This is the material basis that makes [continuity](glossary.md#接续) possible |
| `runs/manifest.json` | The [run manifest](glossary.md#运行清单). A JSON array, **accumulated across processes**; all the numbers on the case pages can be recomputed from here |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Written by atomic replacement |
| `runs/aside/` | The oracle Q&A's separate Runtime, with its own `sessions.db` and `manifest.json`. **Cost and lineage don't mix into the main manifest** |
| `runs/workbench/` | Only appears when `-W` is used and the workflow doesn't bring its own workbench (`run` / `once` paths) |

The fields of each record in `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` is this process's marker, formatted as `YYYYmmdd-HHMMSS-<6 位 hex>`. The spill policy is **append, don't overwrite**: before each write it re-reads the file and deduplicates by `run` — rows belonging to this process are replaced with the latest, rows from other processes are left as they are.

Step names come in four shapes:

| Shape | When |
|---|---|
| `<步骤名>` | First attempt |
| `<步骤名>#retry<N>` | Ordinary retry |
| `<步骤名>#round<N>` | The verdict didn't pass, sent back to continue |
| `<步骤名>·判定#<N>` | The [judge](glossary.md#判定者)'s step |

When killed by a signal, the in-flight step is written too, with the `error` field being `killed-by-signal`.

**Running several flowers in parallel in the same directory**: `manifest.json` is safe (re-read + merge by `run`), but `lineage.json` is a full overwrite, and two processes will clobber each other's lineage for steps of the same name. To run in parallel, use different `-r`.

`lineage.json` stores the absolute path of the workspace. If it doesn't match, it's treated as absent and **silently** falls back to a new session without an error — after a directory has been copied elsewhere, the old `session_id` couldn't be looked up anyway.

### `.flower/` {#flower-目录}

| Path | What's in it |
|---|---|
| `.flower/scripts/` | Scripts meant to be run a second time. The first line reads `# desc: 一句话`, and that sentence appears in the index |
| `.flower/artifacts/` | Long outputs over 2000 characters: reports, data, logs. Only the path appears in the conversation |
| `.flower/notes/` | Cross-step decision records |
| `.flower/spill/` | [Spill](glossary.md#落盘): tool results over 4000 characters land here, and the context keeps only a one-line pointer plus the first 400 characters. The file name is the first 16 digits of the content's sha256 plus `.txt` |
| `.flower/INDEX.md` | An index of the directories above, **injected into the coordinator's system prompt** (subagents don't inherit it) |

The `go` path always generates these under `notes/`:

| File | Contents |
|---|---|
| `notes/需求.md` | The frozen [brief](glossary.md#需求确认书), four sections: 目标 / 验收标准 / 边界 / 未知与假设 |
| `notes/目标.md` | The frozen goals, two sections: 目标 / 判定清单 |
| `notes/问答记录.md` | An appended record of all questions and answers (including status), also covering things you said on your own initiative. **Doesn't enter context, purely for the record** |
| `notes/交接-<步骤名>.md` | The [handoff document](glossary.md#交接书) written at handoff time; the previous generation is filed into `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | The `lineage.json`, `需求.md`, `目标.md` archived by `--new` or `/new`. It's a **move**, not a delete |

With `--isolate` the workbench moves outside the repo: `<workspace>.parent/.flower-<workspace 名>/`. A worktree is each agent's private copy, while the workbench is a shared layer across agents, and shared things can't be put inside a private fence. In this case the workbench path given to the model is an absolute path.
