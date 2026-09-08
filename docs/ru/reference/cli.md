# CLI reference

`flower` installs a single executable with 4 subcommands and 23 flags. This page lists all of them: the type, default value and exact semantics of every flag, plus how to interject mid-run, what it asks you on first launch, what the exit codes are, and which files it drops into your directory. After this page you should never need to open the source.

Source: [`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py).

| Subcommand | What it does | Positional args | Own flags |
|---|---|---|---|
| `go` | Everything at once: clarify the request → set goals → dispatch workers → judge each round. The default when no subcommand is given | `ask` (optional) | 11 |
| `run` | Runs a [workflow](glossary.md#流程) you wrote yourself | `target` (required) | 0 |
| `once` | Runs a single agent once, with no workflow and no verdict | `prompt` (required) | 6 |
| `setup` | Configures credentials, writes to `~/.config/flower/.env` | none | 0 |

Total flags 23 = 5 global + 11 specific to `go` + 6 specific to `once` + `-h/--help`. `run` and `setup` have no flags of their own.

---

## Invocation forms {#调用形式}

Every argv `flower` sees first passes through `_with_default_cmd()`, which fills in the default subcommand, and only then goes to argparse (`cli.py:1437-1439`). That is why `flower "build me an X"` works — it gets rewritten into `flower go "build me an X"`.

The rules for filling in the default subcommand (`cli.py:940-976`):

1. The set of global flags is **derived from the main parser itself**, not from a hardcoded list. Anything with `nargs == 0` counts as a bare flag; everything else takes a value.
2. Scan left to right, skipping global flags. Value-taking flags skip their value too, and the `=` form such as `--workspace=/tmp` is recognized.
3. Stop at the first token that is not a global flag. If it is one of `go`, `run`, `once`, hand argv to argparse unchanged; **otherwise insert a `go` in front of it**, so it becomes the body of `go`'s request.
4. If the scan ends without hitting a positional (empty argv, or only global flags) → append `go` at the end and go to interactive input.
5. Exception: if argv contains `-h` or `--help`, return it unchanged and let argparse print help.

The constant used for this decision is `_CMDS = ("go", "run", "once")` (`cli.py:937`) — **`setup` is not in it**; for the consequences see [`setup`](#setup).

### What the rewrite actually produces {#实际的改写结果}

| What you typed | What it parses as | Effect |
|---|---|---|
| `flower` | `["go"]` | Interactively asks "what do you want done?" |
| `flower -v` | `["-v", "go"]` | Same, verbose |
| `flower "build me an X"` | `["go", "build me an X"]` | Starts right away |
| `flower -w /tmp "do X"` | `["-w", "/tmp", "go", "do X"]` | Global flags may come first |
| `flower --workspace=/tmp "do X"` | `["--workspace=/tmp", "go", "do X"]` | The `=` form is recognized too |
| `flower "do X" --timeout 0` | `["go", "do X", "--timeout", "0"]` | Subcommand flags may follow the request |
| `flower --timeout 0 "do X"` | `["go", "--timeout", "0", "do X"]` | Or precede it |
| `flower --new` | `["go", "--new"]` | Flags only, no request → interactive input |
| `flower once "hi"` | `["once", "hi"]` | Unchanged |
| `flower run flows:main` | `["run", "flows:main"]` | Unchanged |
| `flower run` | `["run"]` | argparse reports the missing `target`; it will **not** be treated as a request |
| `flower go run` | `["go", "run"]` | Explicit disambiguation: the request body is literally `run` |
| `flower setup` | `["go", "setup"]` | Runs `go` with the string `setup` as the request; see [`setup`](#setup) |
| `flower --help` | Unchanged | argparse prints help |

The two words `run` and `once` **cannot** be used directly as a request body; that ambiguity is preserved deliberately (`cli.py:949-950`). To use them as a request, write `flower go run`.

### Six usable forms {#六种能用的写法}

```bash
flower                                    # 1. Bare: asks "what do you want done?" or "continue from last time?"
flower "帮我做一个 X"                       # 2. Request as a positional argument
echo "帮我做一个 X" | flower --timeout 0    # 3. Feed stdin through a pipe
flower once "读一眼这个仓库"                 # 4. Single agent
flower run flows.py:main                  # 5. Run a custom workflow
flower go setup                           # 6. Explicit go, with setup as the request body
```

The module form `python -m flower.cli` is equivalent to `flower` (`cli.py:1451-1452`). The container wrapper `docker/flowerbox` takes exactly the same arguments as `flower`.

### Feeding stdin through a pipe {#管道喂-stdin}

When `sys.stdin.isatty()` is false, `ask_for_prompt()` **prints no prompt header** and just does `input("> ")` to read one line (`cli.py:993-1001`). That is why `echo "..." | flower` works.

But a warning line follows, and the stdin thread immediately hits EOF and exits:

```text
! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0
```

Piped runs should set `--timeout 0`: questions no longer pretend to wait 30 minutes, they fail immediately, the agent decides for itself and writes its assumptions into the "unknowns and assumptions" section of the brief.

---

## Subcommands {#子命令}

### `go` {#go}

Help text: `一键跑:问清需求 → 派人干活(不写子命令时的默认)` (`cli.py:1275-1307`).

Positional argument `ask`, `nargs="?"` — omit it and you get interactive input. This is the most common entry point; `flower "do X"` goes through it.

What it does (`cli.py:1190-1221`):

1. `ensure_credentials()` — checks credentials and actually fires one API probe, see [First-run configuration flow](#首次运行的配置流程).
2. [Wake](glossary.md#唤醒) detection: a read-only glance at whether this directory has been used before, without writing a single byte.
3. If no `ask` was given, print a prompt and ask; entering `/new` is equivalent to `--new`, and then it **asks again** for the request.
4. If this is a [continuity](glossary.md#接续), print a wake banner line.
5. Build the three-step [workflow](glossary.md#流程): `确认需求` → `设定目标` → `干活`, with a `干活·判定#N` after each work round. `--clarify-only` keeps only the first step.
6. Start running.

The wake banner looks like this (the home directory in paths is replaced by `~`):

```text
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

`需求已确认` is always there; `目标 N 条` appears only when there is a verdict checklist; `干活上下文 X` requires that the last round's context of that [session](glossary.md#会话) can be looked up in `sessions.db` — if not, it is not shown.

!!! warning "`-W` and `-T` are silently overridden on the `go` path"
    These two global flags do nothing on `go`; no error, no notice:

    - `-W/--workbench`: the workflow `go` builds always brings its own [workbench](glossary.md#工作台), and the code reads `getattr(wf, "workbench", None) or args.workbench` (`cli.py:1038`) — the workflow's own copy always wins. So the workbench is always `<workspace>/.flower/` (or `<workspace>.parent/.flower-<name>/` under `--isolate`), and `-W` cannot change it.
    - `-T/--trim`: `go` goes through `_drive(wf, args, trim=not args.no_trim)` (`cli.py:1221`), using the negation of `--no-trim` directly and **never looking at `args.trim`**. In other words, on the `go` path [trimming](glossary.md#裁剪) is on by default and `--no-trim` is the only way to turn it off.

    These two flags take effect only on `run` (when the workflow does not bring its own workbench) and `once`.

#### The 11 flags of `go` {#go-的-11-个开关}

| Flag | Type | Default | Description |
|---|---|---|---|
| `--asks N` | int | `-1` | Question quota. `-1` or any negative value = **unlimited**; `0` = questions forbidden, the first question yields `over_budget`; `N` = a hard quota. Over quota, the tool simply refuses without blocking the run |
| `--rounds N` | int | `3` | Upper bound on the **total number** of work rounds, not extra rounds. At the end of each round an independent [judge](glossary.md#判定者) decides "is this done", and if not it is sent back to continue on the same session |
| `--no-goal` | flag | `False` | Turns off the [goal guard](glossary.md#目标看守): no `目标.md` is generated, no [verdict](glossary.md#判定) is made, and finishing the work is finishing |
| `--judge-can-run` | flag | `False` | Lets the judge run commands. Verdicts get harder, at the cost that it can now also modify the workspace |
| `--timeout SECONDS` | float | `1800.0` | How long to wait for a human answer. `0` or negative = fully automatic, every question fails **immediately** with no pretend waiting. Semantics in [Timeout](#超时) |
| `--isolate` | flag | `False` | Gives each [subagent](glossary.md#subagent) its own git worktree, i.e. [isolation](glossary.md#隔离). **Requires the workspace to be a git repository**, otherwise exit code 1. Also moves the workbench outside the repo |
| `--window N` | int | none (inferred from model name) | Model context window. When not given: the model name contains `1m` or does not contain `haiku` → 1,000,000; contains `haiku` → 200,000. At `window − 50000` it writes a [handoff document](glossary.md#交接书) and [hands off](glossary.md#换代) |
| `--no-handoff` | flag | `False` | Turns off handoff, falling back to the SDK's built-in [compaction](glossary.md#压缩) |
| `--new` | flag | `False` | Do not continue from last time. The previous segment's `lineage.json` + `需求.md` + `目标.md` are **moved** (not deleted) into `notes/archive/<YYYYmmdd-HHMMSS>/`, then it starts from scratch |
| `--clarify-only` | flag | `False` | Only do the [clarify](../guide/clarify.md) phase, no work afterwards — the workflow keeps only the `确认需求` step |
| `--no-trim` | flag | `False` | Turns off trimming. On the `go` path trimming is **on** by default, and this is the only way to turn it off |

Edge cases in the values, none of which error or warn:

- `--rounds 0` and `--rounds 1` are equivalent — internally it is `retries = max(0, rounds - 1)`, both run 1 round.
- Any negative `--asks` means unlimited, not just `-1`.
- Any negative `--timeout` equals `0`, i.e. fully automatic.
- `--window 0` is **silently ignored** (`0` is falsy and never gets passed down), falling back to the default inferred from the model name. A negative value does get passed down and is then floored to `10000`.
- `--clarify-only` is a **no-op** in a directory that has already been clarified — the `确认需求` step sees a complete `需求.md` and skips, and since that is the only step in the workflow, nothing happens at all (except the wake count going up by 1). To re-clarify, combine it with `--new`.
- The `--help` of `go` ends with "全局开关(-v/-w/-r/-T)见 `flower --help`", and that line **omits `-W`**.

### `run` {#run}

Help text: `运行一个 workflow` (`cli.py:1309-1312`).

Positional argument `target`, written as `module:attribute`. Both forms are supported (`cli.py:1010-1031`):

```bash
flower run mypkg.flows:build     # import by module name
flower run flows.py:build        # file path; the parent directory is put on sys.path and imported by file name
```

If the attribute obtained is callable, it is called once and the return value is used as the [workflow](glossary.md#流程); if it is already a workflow object, it is used directly.

**`run` has no flags of its own**, only the 5 global ones. So `--window`, `--no-handoff` and friends always take their defaults on this path (the code falls back with `getattr`, `cli.py:1041-1043`). To adjust them, put the parameters into your own workflow.

### `once` {#once}

Help text: `跑一次单 agent` (`cli.py:1314-1324`). Positional argument `prompt` is required.

It builds an `AgentSpec(name="ad-hoc", …)` and runs it directly, **without going through `_drive`**. So `once` has none of:

- Ctrl-C to interrupt and say something (pressing it is a plain `KeyboardInterrupt`)
- the stdin answering thread and the persistent bottom input prompt
- oracle Q&A
- SIGHUP / SIGTERM rescue accounting
- the closing line `总花费 … · 清单 …`
- the automatic reconfiguration guidance after a credential failure

In the [run manifest](glossary.md#运行清单) this step is always named `ad-hoc`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-i`, `--instructions` | str | empty | Domain instructions, [appended](glossary.md#叠加) **after** Claude Code's native system prompt, not replacing it |
| `-t`, `--tools` | str | `Read,Glob,Grep` | Comma-separated tool whitelist. When not given, those three read-only tools |
| `-p`, `--permission-mode` | str | `default` | The value must be one of `default`, `acceptEdits`, `plan`, `bypassPermissions`; anything else makes argparse error out with exit code 2 |
| `-b`, `--budget` | float | no limit | [Budget](glossary.md#预算) cap in dollars; it stops when exceeded |
| `--resume SESSION_ID` | str | none | Continue an existing session |
| `--fork` | flag | `False` | Fork instead of continuing; used together with `--resume` |

!!! warning "The elapsed time and cumulative cost shown by `once` are always 0"
    `once` creates a new renderer instance for every event it receives (`cli.py:688-690`, `cli.py:1239`), while the timing origin and the cumulative cost live on the instance (`cli.py:500-501`). Hence:

    - `用时` on the closing line is always `0:00`
    - `累计 $0.00` in the status line is always 0, and `上下文` never accumulates either

    The real cost of the single step must be read from the `cost_usd` field in `runs/manifest.json`. The `go` and `run` paths hold a single renderer instance and do not have this problem.

### `setup` {#setup}

Help text: `配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env` (`cli.py:1326-1328`). It has no flags.

What it does: read `.env` → decide whether it has been configured → start the interactive configuration flow, with `reason` being either `重新配置。` or `还没配过凭证。`. For the screen contents see [First-run configuration flow](#首次运行的配置流程).

!!! warning "`flower setup` currently cannot reach this subcommand"
    The constant used to decide the default subcommand, `_CMDS = ("go", "run", "once")` (`cli.py:937`), **omits `"setup"`**, even though `setup` really is registered on the parser (`cli.py:1326`). So `flower setup` gets rewritten into `flower go setup` — **it runs the full `go` workflow with the string `setup` as the request body**: first it verifies credentials, then it asks about the requirements, and then it actually starts dispatching workers. Global flags change nothing: `flower -v setup` → `["-v", "go", "setup"]`.

    **There is no argv that reaches the `setup` subcommand.**

    To configure credentials, only these two routes remain, and both lead to the same interactive screen:

    - just run `flower "some request"`; if credentials have never been configured it asks first;
    - or hand-write `~/.config/flower/.env`, with key names listed in [Keys written out](#写出来的键).

    A few pieces of copy are affected as well: the ``跑 `flower setup` 重配。`` printed when credentials are rejected, and the comment on the first line of `.env`, ``由 `flower setup` 写`` — both point at this unreachable command.

---

## Global flags {#全局开关}

The 5 global flags are attached both to the main parser and to every subcommand (`cli.py:1250-1266`). The copies on the subcommands use `argparse.SUPPRESS`, so they write no attribute when absent — which means **they can be written before or after the subcommand**, without overriding each other. The side effect is that they do not appear in a subcommand's `--help`; to see them, run `flower --help`.

| Flag | Type | Default | Description |
|---|---|---|---|
| `-w`, `--workspace` | str | `.` | The agent's working directory. It is `resolve()`d to an absolute path and `mkdir -p`'d. The [workbench](glossary.md#工作台) `.flower/` is created inside it |
| `-r`, `--run-dir` | str | `runs` | Directory for the [session store](glossary.md#会话存储) and the run manifest. **Relative to the current CWD, not to the workspace** |
| `-v`, `--verbose` | flag | `False` | Prints more, see below |
| `-W`, `--workbench` | flag | `False` | Enables the workbench. **No effect on `go`**; it only applies to `run` (when the workflow does not bring its own workbench) and `once`, in which case the workbench lands in `<run_dir>/workbench/` |
| `-T`, `--trim` | flag | `False` | On resume, replaces old large tool results with file pointers, i.e. [trimming](glossary.md#裁剪). **No effect on `go`**, where `--no-trim` controls it in the opposite direction |
| `-h`, `--help` | flag | — | Present on every parser. When it appears in argv, the default-subcommand rewrite is skipped and help is printed directly |

The fact that `-r/--run-dir` is relative to CWD will bite: `flower -w /other/proj "do X"` creates `runs/` in **the directory you typed the command in**, while `.flower/` is created under `/other/proj/` — the two pieces of state get separated. To keep them together, pass `-r /other/proj/runs` explicitly.

The help for `-v` says "显示思考与工具结果", but the [main thread](glossary.md#主线程)'s thinking is **shown by default**. What `-v` actually enables in addition is:

- subagent body text (hidden by default, only its tool calls are shown)
- normal tool results (by default only the failing ones are shown)
- `prompt` events
- a dump of the effective credential configuration before startup, with tokens masked down to their first 4 characters

That last one goes through a bare `print()`, **bypassing output sanitization, without wrapping, and unprotected by the terminal write lock** — when several `flower` processes run in parallel these lines may be torn apart.

---

## Talking to it while it runs {#运行中怎么和它说话}

Once a run is going, the terminal is **continuously reading your input**. You do not have to wait for it to ask, and you do not have to press anything to enter an input mode — the last line is always the one you can type on.

### The input prompt pinned to the bottom {#常驻在最下面的输入提示符}

A daemon thread `flower-stdin` reads stdin the whole time (`cli.py:764-934`), polling with `select` every 0.2 seconds rather than blocking (so the stop signal can wake it; on streams that do not support `select`, such as Windows, it degrades to a blocking read).

**It reads all the time, not just when a question is pending.** The reason: if it only read while asking, whatever you typed during those hours of work would sit in the terminal buffer and get swallowed as the answer to the next question — the question would be answered before you had even seen it.

On the display side, `_say()` is the single output channel; before each output it erases the prompt and redraws it afterwards (`cli.py:309-315`), so the prompt never gets pushed up the screen by event output. **The redraw also brings back the half-typed characters you have not yet entered** — they live in `_PROMPT["buf"]` (`cli.py:183-192`). Without this the content would not actually be lost (it is still in the terminal's line buffer and Enter still sends it), but you could not see it, so you would doubt yourself and type it again.

The prompt has two texts, switching on whether a question is pending:

| State | Last line on the screen |
|---|---|
| A question is pending | `你的回答 (回车=跳过,让它自己判断) > ` |
| No question pending | `(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) > ` |

### Character-by-character input mode and key bindings {#逐字符输入}

To redraw the "half-typed characters", flower has to take over input itself. When stdin is a terminal and `import termios` works, the terminal is put into `cbreak` **before** the `flower-stdin` thread starts (`cli.py:793-807`) — `cbreak` rather than `raw`, so that Ctrl+C still produces `SIGINT` and the whole [Ctrl-C](#ctrl-c) machinery remains. It must be set before the thread starts: putting it inside the thread creates a real race, and characters typed in the instant before the thread gets the CPU are swallowed by line mode, which looks like "my input got lost" (reproduced reliably one time in three in testing, `cli.py:928-934`).

If it cannot be set, it falls back to the original whole-line `readline()` (non-terminal, `termios` unavailable, `tcgetattr` failure). Both paths work; line mode just lacks the key bindings below (`cli.py:883-899`).

The editing logic lives in `LineEditor` (`cli.py:320-414`), a pure state machine that never touches the terminal:

| Key | Effect |
|---|---|
| Printable characters | Inserted at the cursor. UTF-8 uses an incremental decoder and only enters the buffer once a full character is assembled |
| Backspace / Ctrl+H | Deletes **one character** before the cursor. In line mode the terminal deletes by byte, so a Chinese character takes three presses and leaves garbage; not here |
| ← / → | Actually move the cursor. The whole escape sequence is consumed, so things like `[A` never get inserted into the input |
| Home / End (or `[1~` / `[4~`) | Jump to start / end of line |
| Delete (`[3~`) | Deletes one character forward |
| Ctrl+A / Ctrl+E | Start / end of line |
| Ctrl+U | Clears the whole line |
| Ctrl+D | EOF only when the buffer is empty; ignored when there is content |
| ↑ / ↓ | **Do nothing.** There is no history, and moving would make people think something was lost (`cli.py:335`) |
| Other control characters | Ignored |

Enter hands the buffer over and clears it, while moving to a new line on screen — what you said stays above (`cli.py:811-827`).

### Where what you type goes {#你敲的东西去哪了}

| What you type | With a question pending | With no question pending |
|---|---|---|
| **Empty line (just Enter)** | Skips this question, lets it decide for itself | Does nothing |
| **Starting with `?`** | Oracle Q&A, see below | Same as left |
| **Digits only**, within the option range | Substitutes the corresponding option and answers with it | Treated as ordinary text |
| Any other text | Sent as the answer to the asking agent | Goes into the inbox as an appended requirement |
| EOF (Ctrl-D or a closed pipe) | Refuses this question, removes the prompt, thread exits | Removes the prompt, thread exits |

When it goes into the inbox, a receipt line is printed:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

When there is no [brief](glossary.md#需求确认书) to spill to, the second half becomes `没有确认书可落盘 —— 它可能活不过下一个步骤`. The inbox **does not interrupt** the worker currently working; it only picks things up when it next checks the inbox on its own. The same sentence is also appended to `notes/需求.md`, since without spilling it would not survive a step boundary — the next step is a new session that only reads frozen artifacts.

### A leading `?` = oracle Q&A {#旁路问答}

A line starting with `?` is not sent to the running agent but handed to the [oracle](glossary.md#旁路顾问):

```text
? 现在到哪一步了
```

It starts a **separate** Runtime with `run_dir` set to `<run_dir>/aside/`, so its cost and session lineage never get mixed into the main `manifest.json`. The role is read-only, its tools are only `Read`, `Glob`, `Grep`, at most 12 turns, with a cost cap of **$0.5**. The context it sees is the most recent **60** events (`thinking` and `prompt` events do not enter this window), each truncated to 200 characters, plus a description of the workbench paths.

It runs **concurrently**; the running run does not wait a single second. The answer looks like this:

```text
# 旁路
  <回答正文>
  ($0.0123,没有打扰正在跑的运行)
```

On failure it prints a red line `# 旁路问答失败:<类型>: <消息>`, **without affecting the main workflow**. On exit it waits at most **120** seconds for oracle queries to finish, printing `(等 N 条旁路问答收尾…)` before waiting.

What it says never enters the run's context — asking does not affect the run, and the answer is discarded right after.

!!! warning "A full-width `?` does not trigger oracle Q&A — Chinese IME users will hit this"
    The line of code that detects an oracle question is (`cli.py:907`):

    ```python
    if raw.startswith("?") or raw.startswith("?"):
    ```

    Both characters are **half-width ASCII `?`** (`0x3f`) — verified byte by byte. The intent is obviously to accept both the half-width `?` and the full-width `?` (U+FF1F) produced by a Chinese IME, but it was actually written as the same character twice.

    Consequence: **a line beginning with the full-width `?` is not treated as an oracle question**, but silently sent into the inbox as an "appended requirement", and from there appended to `notes/需求.md`. The receipt you see is `+ 收到`, not `# 旁路`.

    To ask the oracle you **must use the half-width `?`** — switch your IME to English first, or at least type the first character half-width.

### What is on the screen {#屏幕上都是什么}

The icons are **all ASCII**, not emoji (`cli.py:51-69`). The reason is written in a code comment: emoji together with box-drawing, geometric and arrow characters trigger terminal glyph fallback, which has crashed terminals twice.

| Icon | Meaning | Icon | Meaning |
|---|---|---|---|
| `=` | Step separator | `+` | Done / answered / received |
| `~` | Thinking, retry | `x` | Failure / error |
| `>` | Dispatch | `#` | Handoff, oracle, task |
| `*` | Tool call | `-` | Status line, list item |
| `?` | Question | `<-` | Continue from last time, handoff landing point |
| `!` | Warning / interruption | `.` | Skipped |
| `\| ` | Subagent indent bar | | |

!!! warning "The `❓` and `↩` in older docs do not exist in a real terminal"
    Early documentation used `❓` for questions and `↩` for the wake line. **The code never used those characters** — the question icon is a half-width `?`, and the icon for wake and handoff landing points is the two ASCII characters `<-`.

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
| Asked | `  ? <问题>`, followed by items such as `     1) 选项一`, plus `     (还能问 N 次)` when there is a quota |
| Answered | `  + <答案>` |
| Timed out | `  ! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` |
| Quota exhausted | `  ! 提问额度用完` |
| You skipped it | `  . 已跳过` |

When `--asks` is unlimited (the default), the final "还能问 N 次" line is not shown.

When a [handoff](glossary.md#换代) writes the handoff document, it comes as a whole block:

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

The output also does two things you cannot see: every output line passes through sanitization that **only lets flower's own SGR color codes through**, while clear-screen and cursor-move sequences emitted by the model or tools are swallowed whole; and the width is `max(40, min(terminal columns, 110))`, so on wide terminals it deliberately does not fill the line.

### The startup prompt {#起跑时的提示符}

Running bare `flower` (with no request) asks first. Two texts:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 
```

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 
```

The second only appears when this directory has been run in before and `需求.md` has all four sections.

This prompt reads via `input()`, **without shell parsing**. Chinese quotation marks, spaces and exclamation marks can be typed directly — that is the entire reason it exists. zsh, on hitting a Chinese closing quote, drops into `dquote>` continuation, which looks like a hang, when in fact nothing ever started.

- Empty input + first time → exit, printing ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。``
- Empty input + wake → **valid**, it means "continue"
- Entering `/new` → equivalent to `--new`; after archiving the previous segment it **asks again** for the request
- Ctrl-C / Ctrl-D → exit, printing `已取消`

### Timeout {#超时}

`--timeout` is a float in seconds, default `1800.0`. Three kinds of value:

| Value | Behavior |
|---|---|
| `> 0` | Wait that many seconds. On timeout the question settles as `timeout` and the agent decides for itself |
| `0` or negative | **Fully automatic.** The question does not enter the waiting queue, no `asked` event is emitted, nothing appears on screen, and it settles as `timeout` immediately |
| Wait forever | **Not achievable from the command line.** "Wait forever" is supported internally, but `--timeout` is a float with a default value, and no spelling can produce it. The best you can do is a very large number of seconds |

`--timeout 0` and `--timeout -1` are completely equivalent. Piped runs, CI runs and unattended runs all use this.

When a question gets no answer, the tool result fed back to the model is fixed text, in four variants:

| Result | Text fed back to the model |
|---|---|
| Quota exhausted | `提问额度已用完。不要再问了 —— 把剩下的不确定项写进「未知与假设」那一段,按你自己的判断继续。` |
| Timeout | `无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。` |
| You skipped it | `对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。` |
| The question was empty | `问题是空的。把问题写清楚再问。` |

### Ctrl-C {#ctrl-c}

**Ctrl-C means completely different things in two places.**

**Pressed at the startup prompt `> `** — exits the program immediately, printing `已取消`.

**Pressed mid-run** — interrupts the current round and gives you one chance to speak:

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 
```

Pressing Enter here means interrupt without saying anything, and continue. If a question was pending at the time, an extra line is printed: `  (有 N 个提问还等着,打断不影响它们)`.

**Pressing Ctrl+C again really exits**, and as an uncaught `KeyboardInterrupt` — the screen will carry a Python traceback; it is not a clean exit.

Interruption is cooperative: it breaks cleanly at a message boundary and does not hard-cancel tasks. It **does not count as a failed attempt** and consumes no retries. On resume it attaches a note telling the model that "in-flight tool calls returning interrupted is a normal side effect of the interruption, not an environment failure".

This custom Ctrl-C handling is only installed when `sys.stdin.isatty()` (`cli.py:1097`). In a pipe, Python's default behavior remains, i.e. the first press exits. The `once` path does not go through here, so Ctrl-C on `once` also exits on the first press.

### SIGHUP / SIGTERM {#sighup-sigterm}

The `go` and `run` paths install handlers for both `SIGHUP` and `SIGTERM`: they first write **the in-flight step** into `manifest.json` marked `killed-by-signal`, then restore the default action and actually leave.

The reason: when a terminal crashes, the kernel sends SIGHUP, whose default action terminates the process outright — `finally` never runs, the manifest is never written, and a whole run's accounting is lost. On a non-OS main thread, or on a platform that does not support it, this is silently skipped.

---

## First-run configuration flow {#首次运行的配置流程}

All three entry points `go`, `run` and `once` call `ensure_credentials()` at the start (`cli.py:1392-1428`), which has **two gates**.

### Gate one: are there credentials {#第一道-有没有凭证}

It looks for credentials in priority order. If neither `ANTHROPIC_API_KEY` nor `ANTHROPIC_AUTH_TOKEN` is found, the interactive configuration starts; in non-interactive mode (stdin is not a terminal) it does not block, and simply prints this and exits:

```text
缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。
最省事:跑一次 `flower setup`,把 token 存到 /Users/you/.config/flower/.env(装一次,处处生效)。
或者:在当前目录建 `.env`,或 export 进进程环境。
flower 不读 ~/.claude/settings.json —— 那是可移植性的代价。
```

Two parts of this text do not match the implementation: the `flower setup` on the second line is currently unreachable (see [`setup`](#setup)); and the fourth line is **the opposite of the code** — flower does treat the `env` blocks of `~/.claude/settings.json` and `settings.local.json` as a **last-level fallback**, borrowing only 9 credential keys from them and taking over no other setting. The place that prints this line is `env.py:192` (the function `check_credentials()` is defined at `env.py:184`), while the code that actually reads those two files is `env.py:56-75` and `:109-111`; recorded as [issue #13](https://github.com/ChenyuHeee/flower/issues/13). **The code wins: it does read them.** The full lookup priority and those 9 keys are in the [configuration reference](config.md#借用).

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

- Question 1 is **mandatory**. Leave it blank and it prints the red line `没给 token,取消。` and gives up on configuring.
- Questions 2 and 3 may be left blank.
- When stdin is not a terminal, the whole flow is skipped without blocking.

### Keys written out {#写出来的键}

| What you entered | Key it becomes |
|---|---|
| Token starting with `sk-ant-` | `ANTHROPIC_API_KEY` |
| Any other token | `ANTHROPIC_AUTH_TOKEN` |
| Non-empty gateway address | `ANTHROPIC_BASE_URL` |
| Non-empty model name | `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL` and `ANTHROPIC_DEFAULT_SONNET_MODEL`, all three written together |

The file path is `${XDG_CONFIG_HOME:-~/.config}/flower/.env`, and the parent directory is created automatically. It is written as a **full overwrite**, keys with empty values are skipped, `chmod 0600` follows the write, and it is loaded immediately — no need to reopen the shell. The first line is always a comment reminding you not to commit it to version control.

### Gate two: do the credentials work {#第二道-凭证能不能用}

Once the configuration is complete, it prints a line `- 验一下凭证…` and then **actually fires one API call**.

Probe details: `POST {BASE_URL}/v1/messages`, `max_tokens=16`, default timeout 20 seconds, over stdlib `urllib`, with no dependencies pulled in. The model is taken in the order `ANTHROPIC_DEFAULT_HAIKU_MODEL` → `ANTHROPIC_MODEL` → `claude-3-5-haiku-20241022`. If `ANTHROPIC_API_KEY` is present it uses the `x-api-key` header, otherwise `authorization: Bearer <ANTHROPIC_AUTH_TOKEN>`.

`max_tokens` is deliberately 16 rather than 1: in testing, models with forced chain-of-thought could not even fit their thinking in, and the server struggled for 30 seconds before returning; with 16 it takes only 3.6 seconds.

The probe's conclusions fall into three categories of handling, and **the differences matter**:

| Conclusion | Trigger | What flower does |
|---|---|---|
| `auth` | HTTP 401 / 403, or no credentials at all | Prints `! 凭证被拒:<响应体前 160 字>`, starts interactive reconfiguration, and verifies once more afterwards. Non-interactive: exit code 1 |
| `config` | HTTP 404, or 400 **and** the body explicitly says not found / does not exist (one of `not_found`, `not found`, `does not exist`, `unknown model`, `no such model`, `invalid model`) | Prints `! 网关地址或模型名不对:<…>`, same as above |
| `net` | Cannot connect / timeout / DNS failure / TLS failure / 5xx | Prints `  (探针没打通:<前 80 字> —— 当作网络问题,照常开跑)`, **does not make you reconfigure, just starts running** |
| `ok` | Below 400, or anything undecidable, is let through | Silently continues |

The criteria for `config` have been **tightened**: Anthropic-style error JSON almost always contains the word `model`, so using that as "wrong model name" would misclassify a transient 400 as a configuration error and force a reconfiguration — it must explicitly say "not found / does not exist" to count (`env.py:176-182`).

The `net` rule is deliberate: a network hiccup should not force you to retype your token, and flower itself has machinery to suspend and reconnect when the network drops. Seeing "probe did not get through" needs no action; just keep running.

You get **at most one** reconfiguration chance. Failing a second time exits.

**The probe only fires in an interactive terminal.** `ensure_credentials()` returns immediately without making that API call if any of the following holds (`cli.py:1413`): the caller passed `probe=False`, [`FLOWER_NO_PROBE`](config.md#行为开关) is set, or **stdin is not a terminal** (pipe / CI / offline tests). The reasoning is that in non-interactive mode a detected problem cannot be fixed anyway, and the only effect would be "failing early" — and failing early is worse than not probing when it **misjudges**. If the credentials really are bad, the run will blow up on its own, and that path is caught by [automatic reconfiguration after a crash](#跑挂了之后的自动重配).

### Automatic reconfiguration after a crash {#跑挂了之后的自动重配}

When a workflow fails, flower matches the error message of the failing step against a regex (401, `invalid api key`, `authentication`, `unauthorized`, `无效…key/token/密钥`). On a match, and when stdin is a terminal, it prints `! 看起来是凭证不对:<前 120 字>` on the spot and starts the interactive configuration; once configured it prints:

```text
配好了。再跑一次刚才的命令 —— 同一目录会接着上次。
```

Then it exits with code 1 regardless. The `once` path has none of this.

---

## Exit codes {#退出码}

| Code | When |
|---|---|
| `0` | Finished normally |
| `1` | All deliberate exits. The message goes to **stderr**, with no traceback. Full list below |
| `2` | argparse argument error: unknown flag, missing positional, `-p` given a value outside its choices |
| `130` | Two consecutive Ctrl+C presses mid-run. An uncaught `KeyboardInterrupt`, **with a Python traceback** |
| Killed by signal | SIGHUP / SIGTERM: writes the in-flight step into the manifest first, then leaves via the default action |

All the messages behind exit code 1:

| Message | When |
|---|---|
| `已取消` | Ctrl-C or Ctrl-D at the startup prompt |
| ``诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。`` | Brand-new directory + plain Enter |
| `缺少凭证:需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN。…` (4 lines total) | Non-interactive + no credentials |
| ``凭证被拒,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe verdict `auth` |
| ``网关地址或模型名不对,且无法交互配置。跑 `flower setup` 重配。`` | Non-interactive + probe verdict `config` |
| `--isolate 要求 <路径> 是 git 仓库(每个 subagent 要分一份 worktree)。先 git init,或者去掉 --isolate。` | `--isolate` used in a non-git directory |
| `要给一句诉求,例如 flower '帮我做一个 X'` | Empty request and the directory has no wake state |
| `在步骤 '<步骤名>' 中止` | A step in the workflow failed and the policy is to stop |
| `需要 模块:属性 形式,例如 flows:main` | `flower run flows`, colon missing |
| `找不到 <路径>(当前目录 <cwd>)。给的是文件路径就要能对上;要按模块名导入就别带 .py` | `flower run missing.py:main` |
| `导入 '<模块>' 失败:<原始消息>` | The target module failed to import |
| `'<模块>' 里没有 '<属性>'` | That attribute is not in the module |

At the end of a run (the `go` / `run` paths) a final line is printed:

```text
总花费 $1.2345 · 清单 /abs/path/runs/manifest.json
```

This amount covers **this process only**, not the previous run — even though the manifest file itself accumulates across processes.

---

## What it creates in your project {#它在项目里创建了什么}

Two trees: `<run_dir>/` (default `./runs/`, relative to CWD) holds accounting and sessions; `<workspace>/.flower/` holds the [workbench](glossary.md#工作台).

### `runs/` {#runs-目录}

| Path | Contents |
|---|---|
| `runs/sessions.db` | SQLite, the full transcript. This is the material basis that makes [continuity](glossary.md#接续) possible |
| `runs/manifest.json` | The [run manifest](glossary.md#运行清单). A JSON array, **accumulated across processes**; every number on the case pages can be recomputed from here |
| `runs/lineage.json` | [Lineage](glossary.md#血缘): `{"workspace": …, "woke": N, "steps": {"步骤名": "session_id"}}`. Written by atomic replacement |
| `runs/aside/` | The separate Runtime for oracle Q&A, with its own `sessions.db` and `manifest.json`. **Cost and lineage never mix into the main manifest** |
| `runs/workbench/` | Only appears when `-W` was used and the workflow does not bring its own workbench (`run` / `once` paths) |

Fields of each record in `manifest.json`:

```text
step  session_id  ok  cost_usd  num_turns  text  error  started_at  ended_at
attempts  errors[]  resumed  retired[]  context  duration_s  run
```

`run` marks this process, in the format `YYYYmmdd-HHMMSS-<6 hex digits>`. The spill policy is **append, do not overwrite**: before every write it re-reads the file and deduplicates by `run` — rows belonging to this process are replaced by the latest ones, rows from other processes are left as they are.

Step names have four shapes:

| Shape | When |
|---|---|
| `<步骤名>` | First attempt |
| `<步骤名>#retry<N>` | Ordinary retry |
| `<步骤名>#round<N>` | Sent back by a failed verdict to continue |
| `<步骤名>·判定#<N>` | The [judge](glossary.md#判定者) step |

When killed by a signal, the in-flight step is written in as well, with the `error` field set to `killed-by-signal`.

**Running several flowers in parallel in the same directory**: `manifest.json` is safe (re-read + merge by `run`), but `lineage.json` is a full overwrite, so two processes will clobber each other's lineage for identically named steps. To run in parallel, use different `-r`.

`lineage.json` stores the absolute path of the workspace. If it does not match, it is treated as absent and **silently** falls back to a new session, with no error — after the directory has been copied elsewhere, the old `session_id` could not be looked up anyway.

### `.flower/` {#flower-目录}

| Path | Contents |
|---|---|
| `.flower/scripts/` | Scripts meant to be run a second time. The first line reads `# desc: one sentence`, and that sentence shows up in the index |
| `.flower/artifacts/` | Long outputs over 2000 characters: reports, data, logs. Only the path appears in the conversation |
| `.flower/notes/` | Cross-step decision records |
| `.flower/spill/` | [Spill](glossary.md#落盘): tool results over 4000 characters land here, and the context keeps only a one-line pointer plus the first 400 characters. The file name is the first 16 digits of the content's sha256 plus `.txt` |
| `.flower/INDEX.md` | An index of the directories above, **injected into the coordinator's system prompt** (subagents do not inherit it) |

The `go` path always generates these under `notes/`:

| File | Contents |
|---|---|
| `notes/需求.md` | The frozen [brief](glossary.md#需求确认书), four sections: goals / acceptance criteria / boundaries / unknowns and assumptions |
| `notes/目标.md` | The frozen goals, two sections: goals / verdict checklist |
| `notes/问答记录.md` | An append-only record of all questions and answers (including status), also covering what you said on your own initiative. **Does not enter the context, kept purely as an archive** |
| `notes/交接-<步骤名>.md` | The [handoff document](glossary.md#交接书) written at handoff time; the previous generation is filed into `notes/archive/交接/<步骤名>-<时间戳>.md` |
| `notes/archive/<YYYYmmdd-HHMMSS>/` | The `lineage.json`, `需求.md` and `目标.md` archived by `--new` or `/new`. They are **moved**, not deleted |

With `--isolate` the workbench moves outside the repository: `<workspace>.parent/.flower-<workspace name>/`. A worktree is each agent's private copy, while the workbench is a layer shared across agents, and shared things cannot live inside a private fence. In this case the workbench path given to the model is absolute.
