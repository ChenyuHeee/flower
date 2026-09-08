# Command-Line Reference

Once installed, `flower` gives you a single executable, 4 subcommands, and 23 switches. This page
lists them all: for each switch its type, default, and exact semantics, plus how to interject
mid-run, what it asks the first time you run it, the exit codes, and which files it drops into your
directory. After reading this page you shouldn't need to open the source again.

Source: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcommand | What it does | Positional args | Own switches |
|---|---|---|---|
| `go` | The whole pipeline: clarify the requirement → set goals → dispatch workers → judge each round. The default when no subcommand is written | `ask` (optional) | 11 |
| `run` | Run a [workflow](glossary.md#流程) you wrote yourself | `target` (required) | 0 |
| `once` | Run a single agent once, no workflow, no verdict | `prompt` (required) | 6 |
| `setup` | Configure credentials, write them to `~/.config/flower/.env` | none | 0 |

Total switches 23 = 5 global + 11 `go`-only + 6 `once`-only + `-h/--help`. `run` and `setup` have
no switches of their own.

---

## Invocation forms {#调用形式}

Every argv to `flower` first passes through `_with_default_cmd()` to fill in a default subcommand,
then goes to argparse (`cli.py:1437-1439`). This is why `flower "help me build an X"` runs — it gets
rewritten to `flower go "help me build an X"`.

The rules for filling in the default subcommand (`cli.py:940-976`):

1. The set of global switches is **derived from the main parser itself**, not a hardcoded list.
   Ones with `nargs == 0` count as pure switches, the rest as value-taking switches.
2. Scan left to right, skipping global switches. Value-taking ones skip their value too, and the
   `--workspace=/tmp` `=` form is recognized.
3. Stop at the first token that isn't a global switch. If it's one of `go`, `run`, `once`, pass it
   to argparse as-is; **otherwise insert a `go` in front of it**, so it becomes the ask body for
   `go`.
4. If the scan finishes without hitting a positional (empty argv, or only global switches) → append
   `go` at the end and go into interactive input.
5. Exception: if argv contains `-h` or `--help`, return it as-is and let argparse print help.

The constant used for the check is `_CMDS = ("go", "run", "once")` (`cli.py:937`) — **`setup` is not
in it**; for the consequence see [`setup`](#setup).

### The actual rewrite results {#实际的改写结果}

| What you type | Actually parsed as | Effect |
|---|---|---|
| `flower` | `["go"]` | Interactively asks "What should I do?" |
| `flower -v` | `["-v", "go"]` | Same, with verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Runs directly |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Global switches can come first |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | The `=` form is recognized too |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Subcommand switches can come after the ask |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | Or before |
| `flower --new` | `["go", "--new"]` | Only a switch, no ask → interactive input |
| `flower once "hi"` | `["once", "hi"]` | As-is |
| `flower run flows:main` | `["run", "flows:main"]` | As-is |
| `flower run` | `["run"]` | argparse reports missing `target`; **not** treated as an ask |
| `flower go run` | `["go", "run"]` | Explicit disambiguation: the ask body is literally `run` |
| `flower setup` | `["go", "setup"]` | Runs `go`, the ask becomes the string `setup`, see [`setup`](#setup) |
| `flower --help` | as-is | argparse prints help |

The two words `run` and `once` **cannot** be used directly as an ask body; this is a deliberately
preserved ambiguity (`cli.py:949-950`). To use them as an ask, write `flower go run`.

### The six usable forms {#六种能用的写法}

```bash
flower                                    # 1. Bare run: interactively asks "What should I do?" or "Continue from last time?"
flower "帮我做一个 X"                       # 2. Positional arg gives the ask
echo "帮我做一个 X" | flower --timeout 0    # 3. Feed the ask via stdin pipe
flower once "读一眼这个仓库"                 # 4. Single agent
flower run flows.py:main                  # 5. Run a custom workflow
flower go setup                           # 6. Explicit go, treating setup as the ask body
```

The module form `python -m flower.cli` is equivalent to `flower` (`cli.py:1451-1452`). The container
wrapper `docker/flowerbox` takes exactly the same arguments as `flower`.

### Feeding the ask via stdin pipe {#管道喂-stdin}

`ask_for_prompt()` **doesn't print a prompt header** when `sys.stdin.isatty()` is false; it just
reads one line with `input("> ")` (`cli.py:993-1001`). So `echo "..." | flower` works.

But it then prints a warning line, and the stdin thread immediately reads EOF and exits:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

A piped run should come with `--timeout 0`: questions no longer pretend to wait 30 minutes, they
fall through immediately, and the agent judges for itself and writes its assumptions into the
"unknowns and assumptions" section of the brief.

---

## Subcommands {#子命令}

### `go` {#go}

Help text: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1275-1307`).

Positional arg `ask`, `nargs="?"` — omit it to go into interactive input. This is the most-used
entry point; `flower "做 X"` goes through it.

What it does (`cli.py:1190-1221`):

1. `ensure_credentials()` — check credentials, and actually fire an API probe, see
   [The first-run configuration flow](#首次运行的配置流程).
2. [Wake](glossary.md#唤醒) detection: read-only glance at whether this directory has been used
   before, without writing a single byte.
3. If no `ask` was given, print a prompt and ask once; entering `/new` is equivalent to `--new`, and
   then it **asks the ask again**.
4. If this is a [continuity](glossary.md#接续), print a one-line wake banner.
5. Build a three-step [workflow](glossary.md#流程): `确认需求` → `设定目标` → `干活`, with a
   `干活·判定#N` following each round of work. `--clarify-only` keeps only the first step.
6. Run.

The wake banner looks like this (the home directory in the path is replaced with `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` is always present; `目标 N 条` only appears when there's a verdict checklist;
`干活上下文 X` requires being able to look up the last-round context of that
[session](glossary.md#会话) from `sessions.db` — if it can't be found, it's not shown.

!!! warning "`-W` and `-T` are silently overridden on the `go` path"
    These two global switches do nothing on `go` even if you write them, with no error and no notice:

    - `-W/--workbench`: the workflow `go` builds always comes with its own
      [workbench](glossary.md#工作台), and the code takes
      `getattr(wf, "workbench", None) or args.workbench` (`cli.py:1038`) — the workflow's own always
      wins. So the workbench is always `<workspace>/.flower/`
      (with `--isolate`, `<workspace>.parent/.flower-<name>/`), and `-W` can't change it.
    - `-T/--trim`: `go` runs `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1221`), using the
      inverse of `--no-trim` directly and **never looking at `args.trim`**. That is, on the `go` path
      [trim](glossary.md#裁剪) is on by default, and the only way to turn it off is `--no-trim`.

    These two switches only take effect on `run` (when the workflow has no workbench of its own) and
    `once`.

#### The 11 switches of `go` {#go-的-11-个开关}

| Switch | Type | Default | Description |
|---|---|---|---|
| `--asks N` | int | `-1` | Question quota. `-1` or any negative = **unlimited**; `0` = no questions allowed, the first question is `over_budget`; `N` = a hard quota. When over quota the tool refuses directly, without blocking the run |
| `--rounds N` | int | `3` | The **total round** cap on work, not extra rounds. At the end of each round an independent [judge](glossary.md#判定者) rules on "is it done", and if not met, it's kicked back to continue the same session |
| `--no-goal` | switch | `False` | Turn off the [goal guard](glossary.md#目标看守): don't generate `目标.md`, don't [verdict](glossary.md#判定); work finishes when work finishes |
| `--judge-can-run` | switch | `False` | Let the judge run commands. The verdict is harder, at the cost that it can then modify the workspace |
| `--timeout SECONDS` | float | `1800.0` | How long to wait for an answer. `0` or negative = fully automatic, all questions **immediately** fall through instead of pretending to wait. Semantics see [Timeout](#超时) |
| `--isolate` | switch | `False` | Give each [subagent](glossary.md#subagent) its own git worktree, i.e. [isolation](glossary.md#隔离). **Requires workspace to be a git repo**, otherwise exit code 1. Also moves the workbench outside the repo |
| `--window N` | int | none (inferred from model name) | Model context window. When omitted: model name contains `1m` or doesn't contain `haiku` → 1,000,000; contains `haiku` → 200,000. At `window − 50000` it writes a [handoff document](glossary.md#交接书) to [hand off](glossary.md#换代) |
| `--no-handoff` | switch | `False` | Turn off handoff, fall back to the SDK's built-in [compact](glossary.md#压缩) |
| `--new` | switch | `False` | Don't continue from last time. **Move** (not delete) the previous run's `lineage.json` + `需求.md` + `目标.md` into `notes/archive/<YYYYmmdd-HHMMSS>/`, then start from scratch |
| `--clarify-only` | switch | `False` | Only do the [clarify](../guide/clarify.md), don't proceed to work — the workflow keeps only the `确认需求` step |
| `--no-trim` | switch | `False` | Turn off trim. On the `go` path trim is **on** by default; this is the only way to turn it off |

Edge cases on values, none of which error or warn:

- `--rounds 0` and `--rounds 1` are equivalent — internally it's `retries = max(0, rounds - 1)`,
  both run 1 round.
- Any negative `--asks` means unlimited, not just `-1`.
- Any negative `--timeout` equals `0`, i.e. fully automatic.
- `--window 0` is **silently ignored** (`0` is falsy, it's simply not passed down), falling back to
  the default inferred from the model name. A negative value is passed down and then clamped to
  `10000`.
- `--clarify-only` is a **no-op** on an already-clarified directory — the `确认需求` step sees a
  complete `需求.md` and skips, and since that's the only step in the workflow, nothing happens
  (except wake count +1). To re-clarify, pair it with `--new`.
- The `--help` for `go` ends with "全局开关(-v/-w/-r/-T)见 `flower --help`", and this line
  **omits `-W`**.

### `run` {#run}

Help text: `运行一个 workflow` (`cli.py:1309-1312`).

Positional arg `target`, written as `module:attribute`. Both forms are supported (`cli.py:1010-1031`):

```bash
flower run mypkg.flows:build     # import by module name
flower run flows.py:build        # file path; stuffs the parent dir into sys.path then imports by file name
```

If the attribute obtained is callable it's called once and its return value is used as the
[workflow](glossary.md#流程); if it's already a workflow object it's used directly.

**`run` has no switches of its own**, only the 5 global switches. So `--window`, `--no-handoff`, and
the like all take their defaults on this path (the code uses `getattr` as a fallback,
`cli.py:1041-1043`). To adjust them, write the arguments into your own workflow.

### `once` {#once}

Help text: `跑一次单 agent` (`cli.py:1314-1324`). Positional arg `prompt` is required.

It constructs an `AgentSpec(name="ad-hoc", …)` and runs it directly, **not going through `_drive`**.
So `once` has none of:

- Ctrl-C interrupt with a chance to speak (pressing it is a plain `KeyboardInterrupt`)
- The stdin answering thread, the persistent bottom input prompt
- Oracle Q&A
- SIGHUP / SIGTERM rescue accounting
- The closing `总花费 … · 清单 …` line
- Automatic reconfiguration guidance after a credential failure

The name of this step in the [run manifest](glossary.md#运行清单) is fixed as `ad-hoc`.

| Switch | Type | Default | Description |
|---|---|---|---|
| `-i`, `--instructions` | str | empty | Domain instructions, [appended](glossary.md#叠加) **after** Claude Code's native system prompt, not replacing it |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Comma-separated tool allowlist. When omitted it's these three read-only tools |
| `-p`, `--permission-mode` | str | `default` | Value can only be one of `default`, `acceptEdits`, `plan`, `bypassPermissions`; any other value has argparse error out with exit code 2 |
| `-b`, `--budget` | float | no cap | Dollar [budget](glossary.md#预算) cap; stops when exceeded |
| `--resume SESSION_ID` | str | none | Continue an existing session |
| `--fork` | switch | `False` | Fork rather than continue, used together with `--resume` |

!!! warning "The elapsed time and cumulative cost shown by `once` are always 0"
    `once` creates a new renderer instance for every event it receives (`cli.py:688-690`,
    `cli.py:1239`), while the timing origin and cumulative cost are stored on the instance
    (`cli.py:500-501`). So:

    - The `用时` on the closing line is always `0:00`
    - The `累计 $0.00` in the status line is always 0, and `上下文` never accumulates either

    The true cost of a single step must be read from the `cost_usd` field in `runs/manifest.json`.
    The `go` and `run` paths hold the same renderer instance and don't have this problem.

### `setup` {#setup}

Help text: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1326-1328`). No
switches at all.

What it does: read `.env` once → determine whether it's been configured → start the interactive
configuration flow, with `reason` being `重新配置。` or `还没配过凭证。`. For the screen contents see
[The first-run configuration flow](#首次运行的配置流程).

!!! warning "`flower setup` currently can't reach this subcommand"
    The constant for the default-subcommand check, `_CMDS = ("go", "run", "once")` (`cli.py:937`),
    **omits `"setup"`**, yet `setup` is indeed registered in the parser (`cli.py:1326`). So
    `flower setup` gets rewritten to `flower go setup` — **it runs the full `go` pipeline, with the
    ask body being the string `setup`**: first verify credentials, then ask the requirement, then
    actually start dispatching workers. Adding global switches is the same, `flower -v setup` →
    `["-v", "go", "setup"]`.

    **No argv whatsoever can reach the `setup` subcommand.**

    To configure credentials, you now only have these two paths, both of which reach the same
    interactive interface:

    - Just run `flower "some ask"`; if credentials aren't configured it'll ask first;
    - Or hand-write `~/.config/flower/.env`; for the key names see [The keys written](#写出来的键).

    A few other bits of copy are affected too: the ``跑 `flower setup` 重配。`` printed when
    credentials are rejected, and the comment ``由 `flower setup` 写`` on the first line of `.env`,
    both point at this unreachable command.

---

## Global switches {#全局开关}

The 5 global switches are attached to both the main parser and every subcommand (`cli.py:1250-1266`).
The copies on subcommands use `argparse.SUPPRESS`, not writing the attribute when absent, so they can
be written **before or after the subcommand**, without overriding each other. A side effect is that
they don't appear in a subcommand's `--help` — to see them, run `flower --help`.

| Switch | Type | Default | Description |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | The agent's working directory. It's `resolve()`d to an absolute path and `mkdir -p`'d. The [workbench](glossary.md#工作台) `.flower/` is built inside it |
| `-r`, `--run-dir` | str | `runs` | The directory for the [session store](glossary.md#会话存储) and run manifest. **Relative to the current CWD, not to workspace** |
| `-v`, `--verbose` | switch | `False` | Print more, see below |
| `-W`, `--workbench` | switch | `False` | Enable the workbench. **No effect on `go`**, only takes effect on `run` (when the workflow has no workbench of its own) and `once`, in which case the workbench lands at `<run_dir>/workbench/` |
| `-T`, `--trim` | switch | `False` | On resume, replace old large tool results with file pointers, i.e. [trim](glossary.md#裁剪). **No effect on `go`**, that path is controlled inversely with `--no-trim` |
| `-h`, `--help` | switch | — | Every parser has it. When it appears in argv, the default-subcommand rewrite is skipped and help is printed directly |

The rule that `-r/--run-dir` is relative to CWD will bite: `flower -w /other/proj "做 X"` builds
`runs/` in **the directory where you typed the command**, while `.flower/` is built under
`/other/proj/` — the two pieces of state split apart. To keep them together, give `-r /other/proj/runs`
explicitly.

The help for `-v` says "显示思考与工具结果", but the [main thread](glossary.md#主线程)'s thinking is
**shown by default**. What `-v` actually additionally turns on is:

- subagent bodies (not shown by default, only their tool calls are)
- normal tool results (only failing ones are shown by default)
- `prompt` events
- printing the currently effective credential configuration once before startup, with tokens masked
  to leave only the first 4 characters

That last one goes through a bare `print()`, **not passing through output sanitization, no wrapping,
not protected by the terminal write lock**, so when running several `flower` in parallel these lines
may get torn apart.

---

## How to talk to it while it's running {#运行中怎么和它说话}

Once a run is going, the terminal **is always reading your input**. You don't need to wait for it to
ask, and you don't need to press any key to enter input mode — the last line is always the line you
can type on.

### The input prompt that stays at the bottom {#常驻在最下面的输入提示符}

There's a daemon thread `flower-stdin` reading stdin the whole time (`cli.py:764-934`), using
`select` to poll every 0.2 seconds rather than a blocking read (so a stop signal can wake it; streams
that don't support `select`, like on Windows, degrade to a blocking read).

**It's always reading, not just when there's a question.** The reason: if it only read while asking,
whatever you typed during those hours of work would sit in the terminal buffer and get eaten as the
answer to the next question — the question would be answered before you even saw it.

For display, `_say()` is the sole output port; before each output it erases the prompt and redraws
it afterward (`cli.py:309-315`), so the prompt won't get pushed up the screen by event output. **On
redraw it even paints back the half-typed characters you haven't pressed Enter on** — they're stored
in `_PROMPT["buf"]` (`cli.py:183-192`). Without this, the content isn't actually lost (it's still in
the terminal's line buffer, and Enter still sends it), but you can't see it, so you get unsure and
retype it.

The prompt has two texts, switching by "is there a pending question":

| State | Last line on screen |
|---|---|
| Pending question | `你的回答 (回车=跳过,让它自己判断) > ` |
| No pending question | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Character-by-character input mode and keybindings {#逐字符输入}

To paint back the "half-typed characters", flower has to take over input itself. When stdin is a
terminal and `import termios` works, **before** starting the `flower-stdin` thread it first sets the
terminal to `cbreak` (`cli.py:793-807`) — using `cbreak` rather than `raw` so that Ctrl+C still
produces `SIGINT` and the whole [Ctrl-C](#ctrl-c) machinery still works. It must be set before
starting the thread: putting it inside the thread has a real race, and characters typed in the
instant before the thread grabs the CPU get eaten by line mode, showing up as "input lost" (in
testing it reliably reproduces once in three, `cli.py:928-934`).

If it can't be set, it falls back to the old whole-line `readline()` (non-terminal, `termios`
unavailable, `tcgetattr` failure); both paths work, only in line mode none of the keys below exist
(`cli.py:883-899`).

The editing logic is in `LineEditor` (`cli.py:320-414`), a pure state machine that doesn't touch the
terminal:

| Key | Effect |
|---|---|
| Printable character | Inserted at the cursor. UTF-8 uses an incremental decoder that accumulates a full character before entering the buffer |
| Backspace / Ctrl+H | Delete **one character** before the cursor. In line mode the terminal deletes by byte, so one CJK character takes three presses and even then produces garbage; not here |
| ← / → | Actually move the cursor. Whole escape sequences are swallowed, so `[A` and the like don't get inserted into input |
| Home / End (or `[1~` / `[4~`) | Jump to start / end of line |
| Delete (`[3~`) | Delete one character forward |
| Ctrl+A / Ctrl+E | Start / end of line |
| Ctrl+U | Clear the whole line |
| Ctrl+D | EOF only when the buffer is empty; ignored when there's content |
| ↑ / ↓ | **Do nothing**. There's no history, and moving would just make people think they lost something (`cli.py:335`) |
| Other control characters | Ignored |

Enter hands off the buffer and clears it, and moves to a new line on screen — what you said stays
above (`cli.py:811-827`).

### Where what you type goes {#你敲的东西去哪了}

| What you input | With a pending question | With no pending question |
|---|---|---|
| **Empty line (just Enter)** | Skip this question, let it judge for itself | Do nothing |
| **Starts with `?`** | Oracle Q&A, see below | Same as left |
| **Pure digits**, within the option range | Replaced with the corresponding option, then answered | Handled as plain text |
| Other text | Sent as the answer to the asking agent | Into the inbox, treated as an appended requirement |
| EOF (Ctrl-D or pipe close) | Refuse this question, remove the prompt, thread exits | Remove the prompt, thread exits |

When it goes into the inbox, a receipt line is printed:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

When there's no [brief](glossary.md#需求确认书) to spill to, the second half becomes
`没有确认书可落盘 —— 它可能活不过下一个步骤`. The inbox **does not interrupt** the worker currently
working; it only gets picked up the next time the worker proactively checks the inbox. The same line
is also appended into `notes/需求.md`, and without spilling it won't survive the step boundary — the
next step is a new session that only reads the frozen file.

### Starting with `?` = oracle Q&A {#旁路问答}

A line starting with `?` isn't sent to the running agent but handed to the
[oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

It starts an **independent** Runtime with `run_dir` at `<run_dir>/aside/`, so its cost and session
lineage don't mix into the main `manifest.json`. Its role is read-only, its tools are only `Read`,
`Glob`, `Grep`, with at most 12 rounds and a cost cap of **$0.5**. The context it sees is the most
recent **60** events (`thinking` and `prompt` events don't enter this window), each truncated to 200
characters, plus a description of the workbench paths.

It runs **concurrently**; the ongoing run doesn't have to wait a single second. The answer looks like
this:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

On failure it prints a red line `# 旁路问答失败:<类型>: <消息>`, **not affecting the main flow**.
On exit it waits at most **120 seconds** for the oracle to wrap up, printing a
`(等 N 条旁路问答收尾…)` line before waiting.

What it says never enters that run's context — asking doesn't affect the run, and the answer is
discarded once given.

!!! warning "The full-width `？` doesn't trigger oracle Q&A — CJK IME users will trip on this"
    The line of code deciding oracle Q&A is (`cli.py:907`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Both characters are **half-width ASCII `?`** (`0x3f`) — verified byte by byte. From the writing
    the intent is clearly to accept both the half-width `?` and the full-width `？` (U+FF1F) that a
    CJK IME produces, but it was actually written as the same character.

    Consequence: **a line starting with the full-width `？` is not treated as an oracle question**,
    but silently sent into the inbox as an "appended requirement", and further appended into
    `notes/需求.md`. The receipt you see is `+ 收到`, not `# 旁路`.

    To ask the oracle, **you must use the half-width `?`** — switch the IME to English before typing,
    or type just the first character as half-width.

### What's on the screen {#屏幕上都是什么}

The icons are **all ASCII**, not emoji (`cli.py:51-69`). The reason is in a code comment: emoji and
box-drawing, geometric, and arrow characters trigger terminal glyph fallback, which has caused two
terminal crashes.

| Icon | Meaning | Icon | Meaning |
|---|---|---|---|
| `=` | Step separator | `+` | Done / answered / received |
| `~` | Thinking, retry | `x` | Failed / errored |
| `>` | Dispatch | `#` | Handoff, oracle, task |
| `*` | Tool call | `-` | Status line, list item |
| `?` | Question | `<-` | Continue from last time, handoff landing |
| `!` | Warning / interrupt | `.` | Skipped |
| `\| ` | subagent indentation bar | | |

!!! warning "The `❓` and `↩` in old docs don't exist in a real terminal"
    Early docs used `❓` for questions and `↩` for the wake line. **The code was never these two
    characters** — the question icon is a half-width `?`, and the wake and handoff-landing icon is
    the two ASCII characters `<-`.

    So what a real terminal prints is:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    Not `❓ 这个工具……`, nor `↩ 在 ~/proj 接上上次`. grepping logs based on the old docs will turn
    up nothing.

The five states of a question, on screen respectively:

| State | Screen output |
|---|---|
| Asked | `  ? <问题>`, followed by options listed one per line `     1) 选项一`, and if there's quota, `     (还能问 N 次)` |
| Answered | `  + <答案>` |
| Timed out | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Quota exhausted | `  ! 提问额度用完` |
| You skipped | `  . 已跳过` |

When `--asks` is unlimited (the default), the "还能问 N 次" line isn't shown.

When a [handoff](glossary.md#换代) writes its handoff document, it's a whole block:

```text
# 上下文 950.0K/1000K —— 写交接准备换代
  - 现在在做    …
  - 已定的事    …
  - 走不通的    …
  - 下一步      …
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 950.0K 重新开始
```

When the handoff document is downgraded, an extra red line is inserted:
`交接没写成,用了降级版本 —— 接手的人会自己去现场看`.

Output also does two things you can't see: every output line first passes through sanitization,
**letting through only flower's own SGR color codes**, and the clear-screen and cursor-move sequences
that models or tools spit out are swallowed whole; the width is taken as `max(40, min(terminal columns, 110))`,
so on a wide terminal it doesn't fill the whole line — this is deliberate.

### The prompt at startup {#起跑时的提示符}

On a bare `flower` run (no ask), it asks first. Two texts:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

The second only appears when this directory has been run before and `需求.md` has all four sections.

This prompt reads via `input()`, **not passing through shell parsing**. CJK quotes, spaces,
exclamation marks can all be typed directly — that's the entire reason it exists. On zsh, a CJK
closing quote goes into a `dquote>` continuation, which looks like a hang but never actually started.

- Empty input + first time → exit, printing ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Empty input + wake → **valid**, meaning "continue"
- Input `/new` → equivalent to `--new`; after archiving the previous run it **asks the ask again**
- Ctrl-C / Ctrl-D → exit, printing `已取消`

### Timeout {#超时}

`--timeout` is a float in seconds, default `1800.0`. Three kinds of values:

| Value | Behavior |
|---|---|
| `> 0` | Wait this many seconds. On timeout the question settles as `timeout`, and the agent judges for itself |
| `0` or negative | **Fully automatic**. Questions don't enter the wait queue, don't emit an `asked` event, don't appear on screen, and immediately settle as `timeout` |
| Wait forever | **Not doable from the command line**. Internally "wait forever" is supported, but `--timeout` is a float with a default value, and no way of writing it can produce it. The cap is just to give a very large number of seconds |

`--timeout 0` and `--timeout -1` are exactly equivalent. Piped runs, CI runs, unattended runs all use
this.

When a question gets no answer, the tool result fed back to the model is fixed copy, four kinds:

| Result | Copy fed back to the model |
|---|---|
| Quota exhausted | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| You skipped | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| Question is empty | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**Ctrl-C in two places has completely different semantics.**

**Pressed at the startup prompt `> `** — exit the program directly, printing `已取消`.

**Pressed mid-run** — interrupt the current round and give you a chance to speak:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Here, just pressing Enter means only interrupt without speaking, then continue. If there was a
pending question at the time, an extra line is printed:
`  (有 N 个提问还等着,打断不影响它们)`.

**Pressing Ctrl+C once more is a true exit**, and it's an uncaught `KeyboardInterrupt` — there'll be
a Python traceback on screen, not a clean exit.

The interrupt is cooperative: it disconnects cleanly at a message boundary, without hard-canceling
tasks. It **doesn't count as a failed attempt** and doesn't consume a retry. On continuation a note is
attached telling the model that "an in-flight tool call returning interrupted is a normal side effect
of the interrupt, not an environment fault".

This custom Ctrl-C is only installed when `sys.stdin.isatty()` (`cli.py:1097`). When run in a pipe it
keeps Python's default behavior, meaning it exits on the first press. The `once` path doesn't go
through here, so Ctrl-C on `once` also exits on the first press.

### SIGHUP / SIGTERM {#sighup-sigterm}

The `go` and `run` paths install handlers for both `SIGHUP` and `SIGTERM`: first write **the
in-flight step** into `manifest.json` too and mark it `killed-by-signal`, then restore the default
action and actually leave.

The cause is that when a terminal crashes the kernel sends SIGHUP, whose default action terminates
the process outright — the `finally` doesn't run, the manifest isn't written, and a run's accounting
is lost. When not on the OS main thread or the platform doesn't support it, this is silently skipped.

---

## The first-run configuration flow {#首次运行的配置流程}

All three entry points `go`, `run`, `once` call `ensure_credentials()` at the start
(`cli.py:1392-1428`), **two gates**.

### First gate: are there credentials {#第一道-有没有凭证}

It looks through credentials in priority order. If it can't find `ANTHROPIC_API_KEY` or
`ANTHROPIC_AUTH_TOKEN` it starts interactive configuration; non-interactively (stdin isn't a
terminal) it doesn't block, printing this and then exiting:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

This copy has two spots that don't match the implementation: the `flower setup` on the second line
currently can't be reached (see [`setup`](#setup)); and the fourth line is **the opposite of the
code** — flower does treat the `env` blocks of `~/.claude/settings.json` and `settings.local.json` as
the **last-level fallback**, borrowing only 9 credential keys from them and not taking over any other
setting. The place that prints this line is `env.py:192` (the function `check_credentials()` is
defined at `env.py:184`), while what actually reads those two files is `env.py:56-75` and `:109-111`;
recorded in [issue #13](https://github.com/ChenyuHeee/flower/issues/13). **Trust the code: it reads
them.** For the full lookup priority and those 9 keys, see [Configuration reference](config.md#借用).

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

- Question 1 is **required**. Leaving it blank prints a red line `没给 token,取消。` and abandons
  configuration.
- Questions 2 and 3 can be left blank.
- When stdin isn't a terminal the whole flow is skipped directly, without blocking.

### The keys written {#写出来的键}

| What you input | The key written |
|---|---|
| Token starts with `sk-ant-` | `ANTHROPIC_API_KEY` |
| Other token | `ANTHROPIC_AUTH_TOKEN` |
| Gateway address non-empty | `ANTHROPIC_BASE_URL` |
| Model name non-empty | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` all three written together |

The file path is `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, and the parent directory is created
automatically. The write is **a full overwrite**, keys with empty values are skipped, `chmod 0600` is
applied after writing, and it's loaded and effective immediately — no need to reopen the shell. The
first line is always a comment reminding you not to commit it into version control.

### Second gate: do the credentials work {#第二道-凭证能不能用}

Once configuration is complete, it prints a `- 验一下凭证…` line, then **actually fires an API call**.

The probe's details: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, default timeout 20 seconds, over
the stdlib `urllib`, no dependencies pulled in. The model is taken in the order
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. With an
`ANTHROPIC_API_KEY` it uses the `x-api-key` header, otherwise
`authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` is deliberately set to 16 rather than 1: in testing, models forced into chain-of-thought
can't even fit the thinking, and the server struggles until 30 seconds to return; setting 16 takes
only 3.6 seconds.

The probe's conclusion is handled in three categories, and **the differences matter**:

| Conclusion | Trigger | What flower does |
|---|---|---|
| `auth` | HTTP 401 / 403, or no credentials at all | Print `! 凭证被拒:<响应体前 160 字>`, start interactive reconfiguration, verify again after configuring. Non-interactive means exit code 1 |
| `config` | HTTP 404, or 400 **and** the response body explicitly says not found / doesn't exist (one of `not_found`, `not found`, `does not exist`, `unknown model`, `no such model`, `invalid model`) | Print `! 网关地址或模型名不对:<…>`, same as above |
| `net` | Can't connect / timeout / DNS failure / TLS failure / 5xx | Print `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **doesn't make you reconfigure, runs straight away** |
| `ok` | Less than 400, or anything indeterminate is let through | Continue silently |

The criterion for `config` is **tightened**: Anthropic-style error JSON almost always contains the
word `model`, so using that as "model name is wrong" would misclassify a transient 400 as a
configuration error and then force a reconfiguration — it must explicitly say "not found / doesn't
exist" to count (`env.py:176-182`).

The `net` case is deliberate: a network hiccup shouldn't force you to retype your token, and flower
itself has a mechanism to suspend and reconnect when disconnected. If you see "probe didn't get
through", don't mind it, just keep running.

The reconfiguration chance is given **at most once**. A second failure exits.

**The probe only fires in an interactive terminal.** `ensure_credentials()` returns directly without
firing this one API call if any of the following holds (`cli.py:1413`): the caller passed
`probe=False`, [`FLOWER_NO_PROBE`](config.md#行为开关) is set, or **stdin isn't a terminal** (pipe /
CI / offline test). The reason is that non-interactively you can't fix a problem you probe out, and
the only effect is "failing early" — and failing early on a **misclassification** is worse than not
probing. If credentials really are bad, the run will naturally blow up, and that path is caught by
[Automatic reconfiguration after a run blows up](#跑挂了之后的自动重配).

### Automatic reconfiguration after a run blows up {#跑挂了之后的自动重配}

When a workflow fails, flower takes the error message of the failing step and matches it against a
regex (401, `invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). On a match
with stdin being a terminal, it prints `! 看起来是凭证不对:<前 120 字>` on the spot and starts
interactive configuration; once configured, it prints:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

Then, no matter what, it exits with exit code 1. The `once` path doesn't have this section.

---

## Exit codes {#退出码}

| Code | When |
|---|---|
| `0` | Ran to completion normally |
| `1` | All deliberate exits. The message is printed to **stderr**, no traceback. See the list below |
| `2` | argparse argument error: unknown switch, missing positional, `-p` given a value outside choices |
| `130` | Ctrl+C pressed twice mid-run. An uncaught `KeyboardInterrupt`, **with a Python traceback** |
| Killed by signal | SIGHUP / SIGTERM: first write the in-flight step into the manifest, then leave per the default action |

All the messages for exit code 1:

| Message | When |
|---|---|
| `已取消` | Ctrl-C or Ctrl-D at the startup prompt |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Brand-new directory + just Enter |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 lines total) | Non-interactive + no credentials |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe ruled `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe ruled `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` used on a non-git directory |
| `要给一句诉求,例如 flower '帮我做一个 X'` | The ask is empty and the directory has no wake |
| `在步骤 '<步骤名>' 中止` | A step in the workflow fails and the policy is to stop |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, missing the colon |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | The target module fails to import |
| `'<模块>' 里没有 '<属性>'` | The attribute can't be found in the module |

On completion (`go` / `run` paths) it prints a final line:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

This amount counts only **this process's** cost, not the previous run's — even though the manifest
file itself accumulates across processes.

---

## What it creates in the project {#它在项目里创建了什么}

Two trees: `<run_dir>/` (default `./runs/`, relative to CWD) holds accounting and sessions;
`<workspace>/.flower/` holds the [workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Path | Holds |
|---|---|
| `runs/sessions.db` | SQLite, full transcript. This is the material basis for [continuity](glossary.md#接续) being able to continue |
| `runs/manifest.json` | The [run manifest](glossary.md#运行清单). A JSON array, **accumulated across processes**; the numbers on the case pages can all be recomputed here |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Written with atomic replace |
| `runs/aside/` | The oracle Q&A's independent Runtime, with its own `sessions.db` and `manifest.json`. **Cost and lineage don't mix into the main manifest** |
| `runs/workbench/` | Only appears when `-W` is used and the workflow has no workbench of its own (`run` / `once` paths) |

The fields of each record in `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` is this process's marker, in the format `YYYYmmdd-HHMMSS-<6-hex>`. The spill policy is
**append, not overwrite**: before each write it re-reads the file, dedups by `run` — lines belonging
to this process are replaced with the latest, other processes' lines stay as-is.

Step names come in four forms:

| Form | When |
|---|---|
| `<步骤名>` | First attempt |
| `<步骤名>#retry<N>` | Ordinary retry |
| `<步骤名>#round<N>` | Kicked back to continue after a verdict didn't pass |
| `<步骤名>·判定#<N>` | The [judge](glossary.md#判定者) step |

When killed by a signal, the in-flight step is also written in, with the `error` field being
`killed-by-signal`.

**Running several flower in parallel in the same directory**: `manifest.json` is safe (re-read +
merge by `run`), but `lineage.json` is a full overwrite, and two processes will clobber each other's
lineage for same-named steps. To run in parallel, use different `-r`.

`lineage.json` stores the workspace's absolute path. If it doesn't match, it's treated as absent and
**silently** falls back to a new session, no error — after the directory is copied away, the old
`session_id` couldn't be looked up anyway.

### `.flower/` {#flower-目录}

| Path | Holds |
|---|---|
| `.flower/scripts/` | Scripts to run a second time. The first line writes `# desc: 一句话`, and this sentence appears in the index |
| `.flower/artifacts/` | Long outputs over 2000 characters: reports, data, logs. Only the path appears in the conversation |
| `.flower/notes/` | Cross-step decision records |
| `.flower/spill/` | [Spill](glossary.md#落盘): tool results over 4000 characters land here, and the context keeps only one line of pointer plus the first 400 characters. The file name is the first 16 of the content sha256 plus `.txt` |
| `.flower/INDEX.md` | An index of the directories above, **injected into the coordinator's system prompt** (subagents don't inherit it) |

The `go` path always generates these under `notes/`:

| File | Content |
|---|---|
| `notes/需求.md` | The frozen [brief](glossary.md#需求确认书), four sections: goals / acceptance criteria / boundaries / unknowns and assumptions |
| `notes/目标.md` | The frozen goals, two sections: goals / verdict checklist |
| `notes/问答记录.md` | An append record of all questions and answers (with status), including things you proactively said. **Doesn't enter context, kept only for the record** |
| `notes/交接-<步骤名>.md` | The [handoff document](glossary.md#交接书) written on handoff; the previous generation is collected into `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | The `lineage.json`, `需求.md`, `目标.md` archived by `--new` or `/new`. A **move**, not a delete |

With `--isolate` the workbench moves outside the repo: `<workspace>.parent/.flower-<workspace name>/`.
A worktree is each agent's private copy, and the workbench is the cross-agent shared layer; shared
things can't go inside a private fence. In this case the workbench path given to the model is an
absolute path.
