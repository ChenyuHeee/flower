# Command-line reference

Once installed, `flower` is a single executable with 4 subcommands and 23 flags. This page lists
all of them: each flag's type, default, and exact semantics, plus how to talk to a run in flight,
what the first run asks you, what the exit codes are, and which files it puts in your directory.
After this page you shouldn't need to open the source.

Source: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcommand | What it does | Positional | Own flags |
|---|---|---|---|
| `go` | End to end: clarify the ask → set goals → dispatch workers → judge every round. The default when no subcommand is written | `ask` (optional) | 11 |
| `run` | Run a [workflow](glossary.md#流程) you wrote yourself | `target` (required) | 0 |
| `once` | Run a single agent once, no workflow, no verdict | `prompt` (required) | 6 |
| `setup` | Configure credentials, written to `~/.config/flower/.env` | none | 0 |

23 flags total = 5 global + 11 `go`-only + 6 `once`-only + `-h/--help`. `run` and `setup` have no
flags of their own.

---

## Invocation forms {#调用形式}

All of `flower`'s argv goes through `_with_default_cmd()` first to fill in the default subcommand,
then is handed to argparse (`cli.py:1437-1439`). That is why `flower "帮我做一个 X"` works — it gets
rewritten into `flower go "帮我做一个 X"`.

The rules for filling in the default subcommand (`cli.py:940-976`):

1. The set of global flags is **derived from the main parser itself**, not a hardcoded list. Those
   with `nargs == 0` count as bare flags; the rest count as value-taking flags.
2. Scan left to right, skipping global flags. Value-taking ones skip their value too, and the
   `--workspace=/tmp` form with `=` is recognized as well.
3. Stop at the first token that isn't a global flag. If it's one of `go`, `run`, `once`, hand argv
   to argparse unchanged; **otherwise insert a `go` in front of it**, so it becomes the ask body
   for `go`.
4. If the scan finishes without hitting a positional (empty argv, or only global flags) → append
   `go` at the end and go to interactive input.
5. Exception: when argv contains `-h` or `--help`, return it unchanged and let argparse print help.

The constant used for the decision is `_CMDS = ("go", "run", "once")` (`cli.py:937`) — **`setup`
is not in it**; for the consequences see [`setup`](#setup).

### What the rewrite actually produces {#实际的改写结果}

| What you typed | What it actually parses as | Effect |
|---|---|---|
| `flower` | `["go"]` | Interactively asks “要做什么?” |
| `flower -v` | `["-v", "go"]` | Same, with verbose |
| `flower "帮我做一个 X"` | `["go", "帮我做一个 X"]` | Starts running right away |
| `flower -w /tmp "做 X"` | `["-w", "/tmp", "go", "做 X"]` | Global flags may come first |
| `flower --workspace=/tmp "做 X"` | `["--workspace=/tmp", "go", "做 X"]` | The `=` form is recognized too |
| `flower "做 X" --timeout 0` | `["go", "做 X", "--timeout", "0"]` | Subcommand flags may come after the ask |
| `flower --timeout 0 "做 X"` | `["go", "--timeout", "0", "做 X"]` | Or before it |
| `flower --new` | `["go", "--new"]` | Flags only, no ask → interactive input |
| `flower once "hi"` | `["once", "hi"]` | Unchanged |
| `flower run flows:main` | `["run", "flows:main"]` | Unchanged |
| `flower run` | `["run"]` | argparse reports the missing `target`; it will **not** be treated as an ask |
| `flower go run` | `["go", "run"]` | Explicit disambiguation: the ask body is literally `run` |
| `flower setup` | `["go", "setup"]` | Runs `go`, with the ask being the string `setup`; see [`setup`](#setup) |
| `flower --help` | unchanged | argparse prints help |

The two words `run` and `once` **cannot** be used directly as an ask body; that ambiguity is
deliberately preserved (`cli.py:949-950`). To use them as an ask, write `flower go run`.

### Six forms that work {#六种能用的写法}

```bash
flower                                    # 1. Bare: interactively asks “要做什么?” or “接着上次?”
flower "帮我做一个 X"                       # 2. Ask as a positional argument
echo "帮我做一个 X" | flower --timeout 0    # 3. Feed stdin through a pipe
flower once "读一眼这个仓库"                 # 4. Single agent
flower run flows.py:main                  # 5. Run a custom workflow
flower go setup                           # 6. Explicit go, with setup as the ask body
```

The module form `python -m flower.cli` is equivalent to `flower` (`cli.py:1451-1452`).
The container wrapper `docker/flowerbox` takes exactly the same arguments as `flower`.

### Feeding stdin through a pipe {#管道喂-stdin}

When `sys.stdin.isatty()` is false, `ask_for_prompt()` **does not print the prompt header** and
reads a line directly with `input("> ")` (`cli.py:993-1001`). That's why `echo "..." | flower`
works.

But right after that it prints a warning, and the stdin thread immediately hits EOF and exits:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

A piped run should be paired with `--timeout 0`: questions stop pretending to wait 30 minutes,
they fall through immediately, and the agent decides for itself and records the assumption in the
"未知与假设" section of the brief.

---

## Subcommands {#子命令}

### `go` {#go}

Help text: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1275-1307`).

Positional `ask`, `nargs="?"` — omit it and you get interactive input. This is the most common
entry point; `flower "做 X"` goes through it.

What it does (`cli.py:1190-1221`):

1. `ensure_credentials()` — check credentials, and actually fire one API probe; see
   [First-run configuration flow](#首次运行的配置流程).
2. [Wake](glossary.md#唤醒) detection: a read-only look at whether this directory has been used
   before, without writing a single byte.
3. If no `ask` was given, print a prompt and ask; typing `/new` is equivalent to `--new`, and then
   it **asks again** for the ask.
4. If this is a [continuity](glossary.md#接续), print a one-line wake banner.
5. Build the three-step [workflow](glossary.md#流程): `确认需求` → `设定目标` → `干活`, with a
   `干活·判定#N` after each work round. `--clarify-only` keeps only the first step.
6. Run.

The wake banner looks like this (the home directory in the path is replaced with `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` is always present; `目标 N 条` appears only when there's a verdict checklist;
`干活上下文 X` requires that the last round's context for that [session](glossary.md#会话) can be
looked up in `sessions.db` — if not, it isn't shown.

!!! warning "`-W` and `-T` are silently overridden on the `go` path"
    Writing these two global flags on `go` does nothing, with no error and no notice:

    - `-W/--workbench`: the workflow `go` builds always brings its own
      [workbench](glossary.md#工作台), and the code takes
      `getattr(wf, "workbench", None) or args.workbench` (`cli.py:1038`) — the workflow's own copy
      always wins. So the workbench is always `<workspace>/.flower/`
      (with `--isolate`, `<workspace>.parent/.flower-<名字>/`), and `-W` can't change it.
    - `-T/--trim`: `go` goes through `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1221`),
      using the inverse of `--no-trim` directly and **never looking at `args.trim`**. In other
      words, on the `go` path [trimming](glossary.md#裁剪) is on by default and the only way to
      turn it off is `--no-trim`.

    These two flags only take effect on `run` (when the workflow doesn't bring its own workbench)
    and `once`.

#### `go`'s 11 flags {#go-的-11-个开关}

| Flag | Type | Default | Description |
|---|---|---|---|
| `--asks N` | int | `-1` | Question budget. `-1` or any negative = **unlimited**; `0` = no questions allowed, the first one returns `over_budget`; `N` = a hard budget. When over budget the tool simply refuses, without blocking the run |
| `--rounds N` | int | `3` | Cap on the **total** number of work rounds, not extra rounds. At the end of each round an independent [judge](glossary.md#判定者) decides "is it done"; if not, it's sent back to continue the same session |
| `--no-goal` | flag | `False` | Turn off the [goal guard](glossary.md#目标看守): no `目标.md` is generated, no [verdict](glossary.md#判定) is made, and the run is done when the work step finishes |
| `--judge-can-run` | flag | `False` | Let the judge run commands. A harder verdict, at the price of letting it modify the workspace too |
| `--timeout 秒` | float | `1800.0` | How long to wait for a human answer. `0` or negative = fully automatic, every question falls through **immediately** with no pretend waiting. Semantics in [Timeout](#超时) |
| `--isolate` | flag | `False` | Give each [subagent](glossary.md#subagent) its own git worktree, i.e. [isolation](glossary.md#隔离). **Requires the workspace to be a git repo**, otherwise exit code 1. Also moves the workbench outside the repo |
| `--window N` | int | none (inferred from model name) | Model context window. When not given: model name contains `1m` or doesn't contain `haiku` → 1,000,000; contains `haiku` → 200,000. At `窗口 − 50000` it writes a [handoff document](glossary.md#交接书) and does a [handoff](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Turn off handoff, falling back to the SDK's own [compact](glossary.md#压缩) |
| `--new` | flag | `False` | Don't continue from last time. **Moves** (not deletes) the previous segment's `lineage.json` + `需求.md` + `目标.md` into `notes/archive/<YYYYmmdd-HHMMSS>/`, then starts from scratch |
| `--clarify-only` | flag | `False` | Do only the [clarify](../guide/clarify.md) step, don't go on to work — the workflow keeps just the `确认需求` step |
| `--no-trim` | flag | `False` | Turn off trimming. On the `go` path trimming is **on** by default; this is the only way to turn it off |

Edge cases in the values — none of them error, none of them warn:

- `--rounds 0` and `--rounds 1` are equivalent — internally it's `retries = max(0, rounds - 1)`,
  and both run 1 round.
- Any negative `--asks` means unlimited, not just `-1`.
- Any negative `--timeout` means `0`, i.e. fully automatic.
- `--window 0` is **silently ignored** (`0` is falsy and never gets passed down), falling back to
  the default inferred from the model name. A negative value does get passed down, and is then
  floored to `10000`.
- `--clarify-only` is a **no-op** on an already-clarified directory — the `确认需求` step sees a
  complete `需求.md` and skips, and since it's the only step in the workflow, nothing happens
  (except the wake count going up by 1). To re-clarify you need `--new` as well.
- The tail of `go`'s `--help` says "全局开关(-v/-w/-r/-T)见 `flower --help`", and that line
  **is missing `-W`**.

### `run` {#run}

Help text: `运行一个 workflow` (`cli.py:1309-1312`).

Positional `target`, written as `module:attribute`. Both forms are supported (`cli.py:1010-1031`):

```bash
flower run mypkg.flows:build     # import by module name
flower run flows.py:build        # file path; the parent dir is put on sys.path and it imports by file name
```

If the attribute obtained is callable it is called once and the return value is used as the
[workflow](glossary.md#流程); if it's already a workflow object it's used directly.

**`run` has no flags of its own**, only the 5 global ones. So `--window`, `--no-handoff` and the
rest all take their defaults on this path (the code falls back with `getattr`,
`cli.py:1041-1043`). To tune them, put the parameters into your own workflow.

### `once` {#once}

Help text: `跑一次单 agent` (`cli.py:1314-1324`). The positional `prompt` is required.

It builds an `AgentSpec(name="ad-hoc", …)` and runs it directly, **without going through
`_drive`**. So `once` does not have:

- Ctrl-C to interrupt and say something (pressing it is a plain `KeyboardInterrupt`)
- the stdin answering thread, or the input prompt pinned to the bottom
- oracle Q&A
- SIGHUP / SIGTERM rescue accounting
- the closing `总花费 … · 清单 …` line
- the automatic reconfiguration prompt after a credential failure

In the [run manifest](glossary.md#运行清单), this step's name is always `ad-hoc`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-i`, `--instructions` | str | empty | Domain instructions, [appended](glossary.md#叠加) **after** Claude Code's native system prompt, not replacing it |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Comma-separated tool allowlist. When not given, these three read-only tools |
| `-p`, `--permission-mode` | str | `default` | Must be one of `default`, `acceptEdits`, `plan`, `bypassPermissions`; anything else makes argparse error out with exit code 2 |
| `-b`, `--budget` | float | no cap | Dollar [budget](glossary.md#预算) cap; stops when exceeded |
| `--resume SESSION_ID` | str | none | Continue an existing session |
| `--fork` | flag | `False` | Fork instead of continue, used with `--resume` |

!!! warning "The elapsed time and cumulative cost `once` shows are always 0"
    `once` creates a new renderer instance for every event it receives (`cli.py:688-690`,
    `cli.py:1239`), while the timing origin and cumulative cost live on the instance
    (`cli.py:500-501`). So:

    - the `用时` on the closing line is always `0:00`
    - the `累计 $0.00` in the status line is always 0, and `上下文` never accumulates either

    For the real cost of the single step, look at the `cost_usd` field in `runs/manifest.json`.
    The `go` and `run` paths hold a single renderer instance and don't have this problem.

### `setup` {#setup}

Help text: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1326-1328`).
No flags at all.

What it does: read `.env` → decide whether it's been configured → start the interactive
configuration flow, with `reason` being `重新配置。` or `还没配过凭证。`. For what appears on
screen see [First-run configuration flow](#首次运行的配置流程).

!!! warning "`flower setup` currently cannot reach this subcommand"
    The constant used to decide the default subcommand, `_CMDS = ("go", "run", "once")`
    (`cli.py:937`), **is missing `"setup"`**, even though `setup` really is registered on the
    parser (`cli.py:1326`). So `flower setup` gets rewritten into `flower go setup` — **it runs
    the full `go` workflow with the string `setup` as the ask body**: first it verifies
    credentials, then it clarifies the ask, then it really starts dispatching workers. Adding
    global flags changes nothing: `flower -v setup` → `["-v", "go", "setup"]`.

    **No argv whatsoever can reach the `setup` subcommand.**

    To configure credentials, there are only these two routes right now, and both land on the same
    interactive screen:

    - just run `flower "随便一句诉求"`; if credentials aren't configured it asks first;
    - or hand-write `~/.config/flower/.env`; for the key names see [Keys written](#写出来的键).

    A few pieces of copy are collateral damage too: the ``跑 `flower setup` 重配。`` printed when
    credentials are rejected, and the comment on the first line of `.env`, ``由 `flower setup` 写``,
    both point at this unreachable command.

---

## Global flags {#全局开关}

The 5 global flags are attached to the main parser and to every subcommand simultaneously
(`cli.py:1250-1266`). The copy on the subcommands uses `argparse.SUPPRESS`, so no attribute is
written when they're absent, which means **you can write them before or after the subcommand**
without either overriding the other. The side effect is that they don't show up in a
subcommand's `--help` — for those you have to run `flower --help`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | The agent's working directory. It gets `resolve()`d to an absolute path and `mkdir -p`'d. The [workbench](glossary.md#工作台) `.flower/` is created inside it |
| `-r`, `--run-dir` | str | `runs` | Directory for the [session store](glossary.md#会话存储) and the run manifest. **Relative to the current CWD, not to the workspace** |
| `-v`, `--verbose` | flag | `False` | Print more; see below |
| `-W`, `--workbench` | flag | `False` | Enable the workbench. **Has no effect on `go`**; only applies to `run` (when the workflow doesn't bring its own workbench) and `once`, in which case the workbench lands in `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | On resume, replace old large tool results with file pointers, i.e. [trimming](glossary.md#裁剪). **Has no effect on `go`**; that path is controlled inversely by `--no-trim` |
| `-h`, `--help` | flag | — | Present on every parser. When it appears in argv, the default-subcommand rewrite is skipped and help is printed directly |

The "`-r/--run-dir` is relative to CWD" rule will bite you: `flower -w /other/proj "做 X"` creates
`runs/` in **the directory you typed the command in**, while `.flower/` goes under `/other/proj/`
— two separate piles of state. To keep them together, pass `-r /other/proj/runs` explicitly.

`-v`'s help says "显示思考与工具结果", but [main thread](glossary.md#主线程) thinking **is shown by
default**. What `-v` actually turns on additionally:

- subagent body text (not shown by default; only its tool calls are)
- normal tool results (only failing ones are shown by default)
- `prompt` events
- printing the currently effective credential configuration once before starting, with the token
  masked down to its first 4 characters

That last one goes through a bare `print()`, **bypassing output sanitization, without wrapping and
without the terminal write lock**, so when running several `flower` processes in parallel these
lines can get torn apart.

---

## Talking to it mid-run {#运行中怎么和它说话}

Once a run is going, the terminal **is reading your input the whole time**. You don't have to wait
for it to ask, and you don't press any key to enter an input mode — the last line is always the
line you can type on.

### The input prompt pinned to the bottom {#常驻在最下面的输入提示符}

A daemon thread `flower-stdin` reads stdin the entire time (`cli.py:764-934`), polling with
`select` every 0.2 seconds rather than doing a blocking read (so the stop signal can wake it;
on streams that don't support `select`, such as on Windows, it degrades to a blocking read).

**It reads all the time, not just when there's a question.** The reason: if it only read while a
question was pending, whatever you typed during those hours of work would sit in the terminal
buffer and get eaten as the answer to the next question — the question would be answered before
you ever saw it.

On the display side, `_say()` is the only output path; before each output it erases the prompt and
redraws it afterwards (`cli.py:309-315`), so the prompt never gets pushed up the screen by event
output. **The redraw brings back the half-typed characters you haven't hit Enter on yet** — they
live in `_PROMPT["buf"]` (`cli.py:183-192`). Without this, the content wouldn't actually be lost
(it's still in the terminal's line buffer and Enter still sends it), but you couldn't see it, so
you wouldn't trust it and you'd type it again.

The prompt has two texts, switching on "is there a pending question":

| State | Last line on screen |
|---|---|
| Question pending | `你的回答 (回车=跳过,让它自己判断) > ` |
| No question pending | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Character-at-a-time input mode and key bindings {#逐字符输入}

To redraw "half-typed characters", flower has to take over input itself. When stdin is a terminal
and `import termios` works, the terminal is put into `cbreak` **before** the `flower-stdin` thread
starts (`cli.py:793-807`) — `cbreak` rather than `raw`, so that Ctrl+C still produces `SIGINT` and
the whole [Ctrl-C](#ctrl-c) mechanism survives.

It has to be set before the thread starts: putting it inside the thread is a real race, and the
characters typed in the instant before the thread gets CPU are eaten by line mode, which looks
like "my input got lost" (reproduced reliably one time in three in testing, `cli.py:928-934`).

If it can't be set, it falls back to whole-line `readline()` (not a terminal, `termios`
unavailable, `tcgetattr` failed). Both paths work; line mode just doesn't have the key bindings
below (`cli.py:883-899`).

The editing logic lives in `LineEditor` (`cli.py:320-414`), a pure state machine that never
touches the terminal:

| Key | Effect |
|---|---|
| Printable characters | Inserted at the cursor. UTF-8 uses an incremental decoder and only enters the buffer once a full character is assembled |
| Backspace / Ctrl+H | Delete **one character** before the cursor. In line mode the terminal deletes by byte, so a Chinese character takes three presses and leaves garbage; not here |
| ← / → | Really move the cursor. The whole escape sequence is consumed, so things like `[A` don't get inserted into the input |
| Home / End (or `[1~` / `[4~`) | Jump to start / end of line |
| Delete (`[3~`) | Delete one character forward |
| Ctrl+A / Ctrl+E | Start / end of line |
| Ctrl+U | Clear the whole line |
| Ctrl+D | EOF only when the buffer is empty; ignored when there's content |
| ↑ / ↓ | **Do nothing.** There is no history, and doing something would make people think they'd lost something (`cli.py:335`) |
| Other control characters | Ignored |

Enter hands the buffer over and clears it, and moves down a line on screen — what you said stays
visible above (`cli.py:811-827`).

### Where what you type goes {#你敲的东西去哪了}

| What you type | With a question pending | With no question pending |
|---|---|---|
| **Empty line (just Enter)** | Skip this question, let it decide for itself | Nothing |
| **Starting with `?`** | Oracle Q&A, see below | Same as left |
| **Pure digits**, within the option range | Replaced by the corresponding option and submitted as the answer | Treated as ordinary text |
| Other text | Sent as the answer to the agent that asked | Goes into the inbox as an added requirement |
| EOF (Ctrl-D or pipe closed) | Refuse this question, remove the prompt, thread exits | Remove the prompt, thread exits |

Going into the inbox prints a receipt line:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

When there's no [brief](glossary.md#需求确认书) to spill to, the second half becomes
`没有确认书可落盘 —— 它可能活不过下一个步骤`. The inbox **does not interrupt** the worker at work;
it only picks it up the next time it checks the inbox itself. The same sentence is also appended
to `notes/需求.md` — without spilling it wouldn't survive a step boundary, since the next step is
a new session that only reads frozen artifacts.

### Starting with `?` = oracle Q&A {#旁路问答}

A line starting with `?` isn't sent to the running agent; it goes to the
[oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

It starts an **independent** Runtime with `run_dir` set to `<run_dir>/aside/`, so its cost and
session lineage never mix into the main `manifest.json`. The role is read-only, its tools are only
`Read`, `Glob`, `Grep`, it gets at most 12 turns, and a cost cap of **$0.5**. The context it sees
is the most recent **60** events (`thinking` and `prompt` events don't enter this window), each
truncated to 200 characters, plus a description of the workbench paths.

It runs **concurrently**; the running run doesn't wait a second. The answer looks like this:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

On failure it prints one red line, `# 旁路问答失败:<类型>: <消息>`, and **the main workflow is
unaffected**. On exit it waits at most **120 seconds** for the oracle to finish, printing
`(等 N 条旁路问答收尾…)` before waiting.

What it says never enters that run's context — asking doesn't affect the run, and the answer is
discarded once given.

!!! warning "A full-width `？` does not trigger oracle Q&A — Chinese IME users will hit this"
    The line of code that decides on oracle Q&A is (`cli.py:907`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Both characters are **half-width ASCII `?`** (`0x3f`) — verified byte by byte. From the way
    it's written the intent is obviously to accept both a half-width `?` and the full-width `？`
    (U+FF1F) that a Chinese IME produces, but it ended up as the same character twice.

    The consequence: **a line starting with a full-width `？` is not treated as an oracle
    question**, but is silently sent to the inbox as an "added requirement", and from there
    appended to `notes/需求.md`. The receipt you see is `+ 收到`, not `# 旁路`.

    To ask the oracle you **must use a half-width `?`** — switch the IME to English first, or at
    least type the first character half-width.

### What's on the screen {#屏幕上都是什么}

The icons are **all ASCII**, not emoji (`cli.py:51-69`). The reason is written in a code comment:
emoji plus box-drawing, geometric and arrow characters trigger terminal glyph fallback, which
crashed a terminal twice.

| Icon | Meaning | Icon | Meaning |
|---|---|---|---|
| `=` | Step separator | `+` | Done / answered / received |
| `~` | Thinking, retry | `x` | Failed / error |
| `>` | Dispatch | `#` | Handoff, oracle, task |
| `*` | Tool call | `-` | Status line, list item |
| `?` | Question | `<-` | Continued from last time, handoff landing |
| `!` | Warning / interrupt | `.` | Skipped |
| `\| ` | Subagent indent bar | | |

!!! warning "The `❓` and `↩` in older docs don't exist in a real terminal"
    Early docs used `❓` for questions and `↩` for the wake line. **The code never used those two
    characters** — the question icon is a half-width `?`, and the icon for wake and handoff
    landing is the two ASCII characters `<-`.

    So what a real terminal prints is:

    ```text
      ? 这个工具要做成 CLI 还是库?
         1) CLI
         2) 库
         (还能问 5 次)
    <- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 第 3 次唤醒
    ```

    Not `❓ 这个工具……`, and not `↩ 在 ~/proj 接上上次`. Grepping logs based on the old docs will
    find nothing.

The five question states, as they appear on screen:

| State | Screen output |
|---|---|
| Asked | `  ? <问题>`, followed by each option as `     1) 选项一`, plus `     (还能问 N 次)` when there's a budget |
| Answered | `  + <答案>` |
| Timed out | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Budget exhausted | `  ! 提问额度用完` |
| You skipped | `  . 已跳过` |

When `--asks` is unlimited (the default), the trailing "还能问 N 次" line isn't shown.

When [handoff](glossary.md#换代) writes the handoff document, it's a whole block:

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

Output does two more things you can't see: every output line is sanitized first, **letting through
only flower's own SGR color codes**, so clear-screen and cursor-move sequences emitted by the
model or a tool are swallowed whole; and the width is `max(40, min(终端列数, 110))`, so it doesn't
fill the whole line on a wide terminal — that's deliberate.

### The startup prompt {#起跑时的提示符}

A bare `flower` (with no ask) asks a question first. Two texts:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

The second only appears when this directory has been run before and all four sections of
`需求.md` are present.

This prompt reads via `input()`, **not through shell parsing**. Chinese quotes, spaces, exclamation
marks can all be typed directly — that is the entire reason it exists. zsh, on hitting a Chinese
closing quote, drops into `dquote>` continuation, which looks like a hang; in fact nothing ever
started.

- Empty input + first time → exit, printing ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Empty input + wake → **valid**, means "keep going"
- Typing `/new` → equivalent to `--new`; after archiving the previous segment it **asks again** for
  the ask
- Ctrl-C / Ctrl-D → exit, printing `已取消`

### Timeout {#超时}

`--timeout` is a float in seconds, default `1800.0`. Three kinds of value:

| Value | Behavior |
|---|---|
| `> 0` | Wait that many seconds. On timeout the question settles as `timeout` and the agent decides for itself |
| `0` or negative | **Fully automatic.** The question never enters the wait queue, no `asked` event is emitted, nothing appears on screen, and it settles as `timeout` immediately |
| Wait forever | **Not reachable from the command line.** Internally "wait forever" is supported, but `--timeout` is a float with a default, and no invocation can produce it. The upper limit is passing a very large number of seconds |

`--timeout 0` and `--timeout -1` are exactly equivalent. Piped runs, CI runs and unattended runs
all use this.

When a question gets no answer, the tool result fed back to the model is fixed text, of four kinds:

| Outcome | Text fed back to the model |
|---|---|
| Budget exhausted | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| You skipped | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| Empty question | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**Ctrl-C means completely different things in two places.**

**Pressed at the startup prompt `> `** — exits the program immediately, printing `已取消`.

**Pressed mid-run** — interrupts the current round and gives you one chance to say something:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Pressing Enter here means interrupt without saying anything, and keep going. If there were pending
questions at the time, an extra line is printed:
`  (有 N 个提问还等着,打断不影响它们)`.

**Pressing Ctrl+C a second time really exits**, and it's an uncaught `KeyboardInterrupt` — you'll
get a Python traceback on screen, not a clean exit.

The interrupt is cooperative: it breaks cleanly at a message boundary, without hard-cancelling
tasks. It **does not count as a failed attempt** and doesn't consume a retry. On resume a note is
attached telling the model that in-flight tool calls returning interrupted are a normal side
effect of the interrupt, not an environment failure.

This custom Ctrl-C is only installed when `sys.stdin.isatty()` (`cli.py:1097`). In a pipe, Python's
default behavior is kept, i.e. it exits on the first press. The `once` path doesn't go through
here, so Ctrl-C on `once` also exits on the first press.

### SIGHUP / SIGTERM {#sighup-sigterm}

The `go` and `run` paths install handlers for both `SIGHUP` and `SIGTERM`: they first write **the
in-flight step** into `manifest.json` marked `killed-by-signal`, then restore the default action
and actually go away.

The cause: when a terminal crashes the kernel sends SIGHUP, whose default action terminates the
process outright, so `finally` never runs and the manifest never gets written — and a run's
accounting is lost. On a non-OS-main thread, or on platforms that don't support it, this is
silently skipped.

---

## First-run configuration flow {#首次运行的配置流程}

All three entry points `go`, `run`, `once` call `ensure_credentials()` at the top
(`cli.py:1392-1428`), which has **two gates**.

### Gate one: are there credentials {#第一道-有没有凭证}

Look for credentials in priority order. If neither `ANTHROPIC_API_KEY` nor
`ANTHROPIC_AUTH_TOKEN` is found, start the interactive configuration; when non-interactive (stdin
isn't a terminal) it doesn't block, it just prints this and exits:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Two parts of this text don't match the implementation: the `flower setup` on the second line is
currently unreachable (see [`setup`](#setup)); and the fourth line **contradicts the code** —
flower does treat the `env` block of `~/.claude/settings.json` and `settings.local.json` as the
**last fallback level**, borrowing only 9 credential keys from it and taking over no other
settings. The place that prints this line is `env.py:192` (the function `check_credentials()` is
defined at `env.py:184`), while the code that actually reads those two files is `env.py:56-75` and
`:109-111`; recorded as [issue #13](https://github.com/ChenyuHeee/flower/issues/13).
**The code is authoritative: it reads them.** The full lookup order and those 9 keys are in the
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

- Question 1 is **required**. Leave it empty and it prints the red line `没给 token,取消。` and
  abandons configuration.
- Questions 2 and 3 may be left empty.
- When stdin isn't a terminal the whole flow is skipped without blocking.

### Keys written {#写出来的键}

| What you entered | Key written |
|---|---|
| Token starting with `sk-ant-` | `ANTHROPIC_API_KEY` |
| Any other token | `ANTHROPIC_AUTH_TOKEN` |
| Non-empty gateway address | `ANTHROPIC_BASE_URL` |
| Non-empty model name | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` all three |

The file path is `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, and the parent directory is created
automatically. It's written as a **full overwrite**, keys with empty values are skipped, it's
`chmod 0600`'d afterwards, and then loaded immediately — no need to reopen your shell.
The first line is always a comment reminding you not to commit it to version control.

### Gate two: do the credentials work {#第二道-凭证能不能用}

Once configuration is complete, it prints `- 验一下凭证…` and then **actually fires one API call**.

Probe details: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, default timeout 20 seconds, using
stdlib `urllib`, no dependencies. The model is taken in the order
`ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. With
`ANTHROPIC_API_KEY` it uses the `x-api-key` header, otherwise
`authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` is deliberately 16 rather than 1: in testing, models with forced chain-of-thought
couldn't even fit their thinking, and the server struggled for 30 seconds before returning;
with 16 it takes only 3.6 seconds.

The probe's conclusion is handled in three classes, and **the differences matter**:

| Conclusion | Trigger | What flower does |
|---|---|---|
| `auth` | HTTP 401 / 403, or no credentials at all | Prints `! 凭证被拒:<响应体前 160 字>`, starts interactive reconfiguration, and re-verifies afterwards. Non-interactive: exit code 1 |
| `config` | HTTP 404, or 400 **and** the body explicitly says not found / doesn't exist (one of `not_found`, `not found`, `does not exist`, `unknown model`, `no such model`, `invalid model`) | Prints `! 网关地址或模型名不对:<…>`, same as above |
| `net` | Can't connect / timeout / DNS failure / TLS failure / 5xx | Prints `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **doesn't make you reconfigure, just starts the run** |
| `ok` | Less than 400, or anything that can't be judged | Silently continues |

The criterion for `config` has been **tightened**: the word `model` appears in almost every
Anthropic-style error JSON, and using it to mean "wrong model name" would misclassify a transient
400 as a configuration error and force people to reconfigure — it only counts if it explicitly
says "not found / doesn't exist" (`env.py:176-182`).

The `net` case is deliberate: a network hiccup shouldn't force you to retype your token, and
flower itself has a mechanism to suspend and reconnect when the network drops. Seeing
"探针没打通" is nothing to act on; just keep going.

You get **at most one** reconfiguration chance. A second failure exits.

**The probe only fires in an interactive terminal.** `ensure_credentials()` returns immediately,
without making that API call, if any of the following holds (`cli.py:1413`): the caller passed
`probe=False`, [`FLOWER_NO_PROBE`](config.md#行为开关) is set, or **stdin isn't a terminal**
(pipe / CI / offline tests). The reasoning is that in a non-interactive context you couldn't fix
what the probe found anyway, so the only effect would be "failing early" — and failing early is
worse than not probing when the probe is **wrong**. If the credentials really are bad, the run
will blow up on its own, and that path is caught by
[automatic reconfiguration after a crash](#跑挂了之后的自动重配).

### Automatic reconfiguration after a crash {#跑挂了之后的自动重配}

When the workflow fails, flower matches the failing step's error message against a regex (401,
`invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). On a match, and when
stdin is a terminal, it prints `! 看起来是凭证不对:<前 120 字>` right there and starts interactive
configuration; once configured it prints:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

and then exits with code 1 regardless. The `once` path doesn't have this.

---

## Exit codes {#退出码}

| Code | When |
|---|---|
| `0` | Finished normally |
| `1` | Every deliberate exit. The message goes to **stderr**, with no traceback. Full list below |
| `2` | argparse argument error: unknown flag, missing positional, `-p` given a value outside its choices |
| `130` | Two Ctrl+C presses in a row mid-run. It's an uncaught `KeyboardInterrupt`, **with a Python traceback** |
| Killed by signal | SIGHUP / SIGTERM: writes the in-flight step into the manifest first, then leaves via the default action |

All the exit-code-1 messages:

| Message | When |
|---|---|
| `已取消` | Ctrl-C or Ctrl-D at the startup prompt |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Brand-new directory + plain Enter |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 lines total) | Non-interactive + no credentials |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe says `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe says `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` used in a non-git directory |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Empty ask and the directory has no wake |
| `在步骤 '<步骤名>' 中止` | A workflow step failed and the policy is to stop |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, missing the colon |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | The target module failed to import |
| `'<模块>' 里没有 '<属性>'` | The attribute isn't in the module |

At the end of a run (`go` / `run` paths) one final line is printed:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

That figure counts **this process's** cost only, not the previous run's — even though the manifest
file itself accumulates across processes.

---

## What it creates in your project {#它在项目里创建了什么}

Two trees: `<run_dir>/` (default `./runs/`, relative to CWD) holds accounting and sessions;
`<workspace>/.flower/` holds the [workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Path | Contents |
|---|---|
| `runs/sessions.db` | SQLite, the full transcript. This is the material basis that makes [continuity](glossary.md#接续) possible |
| `runs/manifest.json` | The [run manifest](glossary.md#运行清单). A JSON array, **accumulated across processes**; all the numbers on the case pages can be recomputed from here |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Written by atomic replace |
| `runs/aside/` | The oracle's independent Runtime, with its own `sessions.db` and `manifest.json`. **Cost and lineage don't mix into the main manifest** |
| `runs/workbench/` | Only appears when `-W` was used and the workflow doesn't bring its own workbench (`run` / `once` paths) |

The fields of each record in `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` is this process's marker, formatted `YYYYmmdd-HHMMSS-<6 位 hex>`. The write strategy is
**append, don't overwrite**: before each write it re-reads the file and dedupes by `run` — rows
belonging to this process are replaced with the latest, rows from other processes are left as they
are.

Step names come in four shapes:

| Shape | When |
|---|---|
| `<步骤名>` | First attempt |
| `<步骤名>#retry<N>` | Ordinary retry |
| `<步骤名>#round<N>` | Sent back by a failed verdict to keep working |
| `<步骤名>·判定#<N>` | The [judge](glossary.md#判定者) step |

When killed by a signal, the in-flight step is written in too, with `error` set to
`killed-by-signal`.

**Running several flowers in parallel in the same directory**: `manifest.json` is safe (re-read +
merge by `run`), but `lineage.json` is a full overwrite, so two processes will clobber each other's
lineage for same-named steps. To run in parallel, use different `-r`.

`lineage.json` stores the workspace's absolute path. If it doesn't match, it's treated as absent
and it **silently** falls back to a new session without an error — after the directory has been
copied elsewhere, the old `session_id` wouldn't be findable anyway.

### `.flower/` {#flower-目录}

| Path | Contents |
|---|---|
| `.flower/scripts/` | Scripts meant to be run a second time. The first line reads `# desc: 一句话`, and that sentence shows up in the index |
| `.flower/artifacts/` | Long output over 2000 characters: reports, data, logs. Only the path appears in the conversation |
| `.flower/notes/` | Decision records that cross steps |
| `.flower/spill/` | [Spill](glossary.md#落盘): tool results over 4000 characters land here, leaving only a one-line pointer plus the first 400 characters in context. The filename is the first 16 characters of the content's sha256 plus `.txt` |
| `.flower/INDEX.md` | An index of the directories above, **injected into the coordinator's system prompt** (subagents don't inherit it) |

The `go` path always generates these under `notes/`:

| File | Contents |
|---|---|
| `notes/需求.md` | The frozen [brief](glossary.md#需求确认书), four sections: goal / acceptance criteria / boundaries / unknowns and assumptions |
| `notes/目标.md` | The frozen goals, two sections: goals / verdict checklist |
| `notes/问答记录.md` | An appended record of every question and answer (including status), and of everything you said unprompted. **Not in context, archival only** |
| `notes/交接-<步骤名>.md` | The [handoff document](glossary.md#交接书) written at handoff time; the previous generation is filed into `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | The `lineage.json`, `需求.md`, `目标.md` archived by `--new` or `/new`. It's a **move**, not a delete |

With `--isolate` the workbench moves outside the repo: `<workspace>.parent/.flower-<workspace 名>/`.
A worktree is each agent's private copy, while the workbench is a shared layer across agents, and
shared things can't live inside a private fence. In that case the workbench path given to the model
is absolute.
