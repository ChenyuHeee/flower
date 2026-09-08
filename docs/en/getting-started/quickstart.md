# Quickstart

Three commands and it runs: install it, cd into the project, type `flower`. This page puts
those three first, then covers what happens on screen after you hit Enter, how to answer when it
asks you something, and what to check first when it won't run.

## Install it, cd in, type flower {#跑起来}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
cd /path/to/your/project
flower
```

The first line finds `uv` / `pipx` / `pip` on its own and installs the `flower` command; all you
need is Python ≥ 3.10 — no Node, no Claude Code CLI. The third takes no arguments at all, and
**needs no shell quoting**.

If you want a different install path (pipx / pip / from source), or that script doesn't work on
your machine, see [Install](install.md) — but you don't have to read that page before coming back
here.

## After you hit Enter {#回车之后}

The first time you run it on a machine, it asks for credentials: an API key or a gateway URL.
Configure it once, it lands in `~/.config/flower/.env`, and it applies everywhere from then on.
If Claude Code is already installed and configured on the machine, it borrows that token and
doesn't ask at all.

With credentials in hand, the cursor sits on `>`:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

That line reads standard input; it **does not go through the shell** — curly quotes, spaces,
exclamation marks all type straight through.

Before starting it prints one line, `- 验一下凭证…`, which is a real API probe. If the
credentials are rejected it prints `! 凭证被拒:…` and asks on the spot whether you want to
reconfigure; if it can't connect it prints `(探针没打通:… —— 当作网络问题,照常开跑)` and
**will not** send you off to reconfigure a token that was fine all along.

Once the probe passes it gets to work, in three steps. Every `==` rule on screen is a
[step](../reference/glossary.md#步骤) boundary; the `1/3` on the right is progress:

```text
== 确认需求 ======================================================== 1/3

  ? X 要跑在什么环境上?
     1) 只在我这台 macOS 上
     2) Linux 服务器
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
  + 只在我这台 macOS 上

  ? 「做完了」以什么为准?
你的回答 (回车=跳过,让它自己判断) > 能跑起来,并且 pytest 全绿
  + 能跑起来,并且 pytest 全绿

  + 完成 9 轮 · $0.53 · 用时 6:02

== 设定目标 ======================================================== 2/3

  ~ 把这份需求拆成能当场验证的条目
  + 完成 12 轮 · $0.41 · 用时 9:06

== 干活 ============================================================ 3/3

  ~ 先看一眼现在有什么,再决定第一刀切哪
  * Read README.md
  > 派人 coder 实现 X 的第一版,带最小测试
  先让 coder 把骨架搭起来,我再看要不要拆第二个人。
  - 上下文 36.8K · 累计 $0.94 · 12:44
  + 完成 12 轮 · $12.34 · 用时 52:53
  + 完成 37 轮 · $1.40 · 用时 58:19

总花费 $14.68 · 清单 /path/to/your/project/runs/manifest.json
```

The icons are all ASCII: `~` thinking, `*` tool call, `>` dispatch, `+` success, `x` failure,
`?` question, `<-` resuming. Not emoji — emoji and box-drawing characters trigger terminal glyph
fallback, and that crashed a terminal twice in testing. **Every terminal sample in this
documentation uses this same ASCII set, identical to what's on your screen.**

Three more spots are worth a second look:

- The two trailing `+ 完成` lines are not a duplicate. The first is the work round, the second is
  the **verdict** round — the verdict runs in its own session, but **does not open a new `==`
  rule**, because it is a round inside the `干活` step. Its name in the
  [run manifest](../reference/glossary.md#运行清单) is `干活·判定#1`.
- The `$` on a `+ 完成` line is the money for **that round**; `用时` is the total elapsed time
  **from the start of the run to now**. Two different measures.
- Status lines like `- 上下文 … · 累计 … · …` track only the
  [main thread](../reference/glossary.md#主线程); subagent context is not in them. Subagent tool
  calls are shown by default, indented behind a `|` bar; **what they say** needs `-v` to be
  visible — that's the shop floor, not the decision.

## Who runs each of those three steps {#三步}

| Step on screen | Who runs it | What it does | Frozen into | Details |
|---|---|---|---|---|
| `确认需求` | [Clarifier](../reference/glossary.md#确认者) | Only asks, never touches anything; **keeps asking until it's clear, with no round limit**; finally emits a four-section [brief](../reference/glossary.md#需求确认书) | `.flower/notes/需求.md` | [Clarify](../guide/clarify.md) |
| `设定目标` | [Judge](../reference/glossary.md#判定者) | Translates the brief into "goal + verdict checklist", every item verifiable on the spot | `.flower/notes/目标.md` | [Goal guard](../guide/goal.md) |
| `干活` | [Coordinator](../reference/glossary.md#协调者) dispatching [subagents](../reference/glossary.md#subagent) | The coordinator splits the work, dispatches, reads reports, decides; at the end of each round a judge that **did not take part in the work** independently rules on "is it done"; if not, it goes back for another round | The code itself | [Goal guard](../guide/goal.md) |

The first two steps are where the [clarify](../reference/glossary.md#前置确认) and
[goal guard](../reference/glossary.md#目标看守) mechanisms land; the third is the stretch they
govern together. By default at most 3 verdict rounds (`--rounds`), and `--no-goal` turns the whole
thing off — with it off, "it says it's done" really does mean done.

A verdict has exactly three outcomes: met, not met, and **can't be verified in this environment**.
The last two are different conclusions — "can't be verified here" never passes; it stops and asks
you.

A full run is not cheap. Measured references: [HT002](../cases/ht002.md) installed an existing
project on macOS and got it running — 4 steps, about an hour, **$38.24**;
[HT001](../cases/ht001.md) wrote a terminal IDE from scratch — **10.4 hours, $171.62**. If you
want to see what it will ask before deciding whether to go further, use `--clarify-only`.

## How to answer questions {#答提问}

A block starting with `?` is it asking you. Three ways to answer:

- **Type a number** (`1` / `2` / `3`) — picks that option; the screen echoes a line
  `+ <the option you picked>`.
- **Just type** — a free answer, doesn't have to be one of the options.
- **Just press Enter** — skip it, let it decide for itself; the screen echoes `. 已跳过`.

It waits 1800 seconds by default (`--timeout`). If nobody answers it prints
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` and carries on; it never hangs.
The number of questions is **unlimited by default** (`--asks` defaults to `-1`); give it a
positive number and that's a hard quota, and when it runs out it prints `! 提问额度用完`.

## You can still talk to it while it runs {#插话}

There's always a typeable prompt at the bottom of the screen. It's not decorative — it's erased
before each output line and redrawn after, so it **never gets scrolled away by the log**. Two
variants, switching on whether a question is pending:

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

With no question pending, you can do two things.

**Type a sentence = add a requirement.** It isn't interrupted; it sees it the next time it checks
the inbox. The receipt looks like this:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

"Appended to the brief" matters: that sentence also landed in `需求.md`, so it survives step
boundaries — the next step is a new session that reads only the frozen artifacts, and anything not
written to disk might as well not have been said.

**Starting with `?` = a quick aside.** It opens a separate read-only session to answer you, holding
only the last 60 events and whatever is in the [workbench](../reference/glossary.md#工作台). That
side channel is run by the [oracle](../reference/glossary.md#旁路顾问), capped at 12 rounds / $0.5
by default:

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Answered and discarded** — that exchange does not enter the run's context, and its cost does not
enter the main run manifest; it's recorded in its own file under `runs/aside/`. So asking doesn't
affect the run, and you don't have to wince at the money landing on the bill.

!!! warning "A fullwidth `？` doesn't count — it must be a halfwidth `?`"
    Aside questions are recognized only by the **halfwidth** `?` (ASCII `0x3f`). The fullwidth
    `？` that a Chinese IME produces by default is not recognized — that line goes into the inbox
    as "add a requirement", with **no error**, and the answer you're waiting for simply never
    comes. This is a typo in the code, already on the defect list; until it's fixed, switch your
    IME to English before typing `?`.

While we're here, Ctrl+C: pressing it once mid-run **interrupts the current round and lets you say
something**; it does not exit.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

Press it again to actually exit. (At the initial `要做什么?` prompt, Ctrl-C exits immediately and
prints `已取消`.)

## Running it again means continuing {#再跑一次}

Type `flower` again in the same directory and the first line changes:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

That `<-` line is the [wake](../reference/glossary.md#唤醒) banner, reporting this directory's
current state. It does not re-interrogate you about the requirements, and does not re-set the
goal; same after the process is killed, same after a machine reboot. Whatever you say at that
prompt is appended to `需求.md` and **triggers a re-derivation of the verdict checklist** —
without the re-derivation, the judge would still read the old checklist and your addition would
never reach a verdict. For the details and the cost (context keeps growing), see
[Continuity](../guide/continuity.md).

If you don't want to continue, type `/new`: the previous stretch's brief, goal, and
[lineage](../reference/glossary.md#血缘) are **moved** into `notes/archive/<时间戳>/` (not
deleted), and it starts over.

## In scripts, unattended {#脚本}

The request can also be passed as an argument, with flags before or after it:

```bash
flower "帮我做一个 X"                      # request as an argument
flower --rounds 5 "帮我做一个 X"           # flags first
flower "帮我做一个 X" --rounds 5           # flags last, equivalent
echo "帮我做一个 X" | flower --timeout 0   # pipe into stdin, fully automatic
```

Flags with no request work too — `flower --clarify-only` asks you what to do first, then carries
on.

**Why the "type it after Enter" path still exists.** Those quotes on the command line are pure
overhead. Observed in practice: the closing quote got typed as a Chinese `”`, zsh sat waiting for
a real closing quote (dropping into the `dquote>` continuation prompt), and it looked like the
program had hung — when in fact it had never started. Running bare `flower` reads standard input
without shell parsing, so curly quotes, spaces, exclamation marks and newlines all type straight
through. The pipe form goes through the same entry point — when standard input isn't a terminal it
skips the prompt header and just reads a line.

!!! danger "Unattended runs must pass `--timeout 0` explicitly"
    In a pipe, under `nohup`, or in CI there is nobody to answer questions. Without
    `--timeout 0`: the first question is skipped because "input is closed", and **every question
    after that waits out the full 1800 seconds** — a few questions is a few hours of idling, and
    that time is burning money.
    `--timeout 0` makes every question return "nobody answered" immediately, and it decides for
    itself and moves on.
    When standard input isn't a terminal, flower prints a reminder first:
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## If it won't run {#冒烟}

If typing `flower` does nothing, throws a credential error, or produces output that's obviously
wrong, verify the credentials and the binary on their own with the cheapest possible shot. Single
agent, read-only tools, one shot to see whether both ends connect:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| This piece | What it is |
|---|---|
| `once` | Run a single agent once: no clarify, no goal, no dispatch |
| `-w PATH` | The agent's working directory. Defaults to the current directory |
| `-v` | Print the effective credential configuration before starting; only the first 4 characters of the token are kept |

`once` gives it only three tools by default — `Read`, `Glob`, `Grep` — so it can't write anything,
which makes this shot cheap. Measured reference: Opus 5 with a 1M window through a third-party
gateway has a **single-round floor price of $0.1741**; cheaper models go lower. The "check that
it's installed" section on the [Install](install.md) page runs exactly this command.

A successful run has this shape — the numbers and the prose will differ, **the icons won't**:

```text
ANTHROPIC_AUTH_TOKEN = sk-1***(共 19 位)
ANTHROPIC_BASE_URL = https://your-gateway.example.com
ANTHROPIC_MODEL = claude-opus-5[1m]
- 验一下凭证…
  ~ 先看目录结构,再挑一两个文件读
  * Glob **/*.py
  * Read README.md
  这是一个用 Rust 写的命令行 HTTP 压测工具。
  - 累计 $0.00 · 0:00
  + 完成 4 轮 · $0.0932 · 用时 0:00
```

Two things to recognize:

- The first few lines are the effective configuration printed by `-v`. **A wrong gateway is
  visible at a glance** — that's the main reason this flag exists.
- The `$` on the `+ 完成` line is real; `累计` and `用时` are always 0 on the `once` path
  (each event constructs a new renderer, so state never accumulates).

If this shot works, credentials, gateway, model name and the bundled binary are all correct, and
the problem is elsewhere. If it doesn't, that's an install issue — go back to
[Install](install.md).

## What to read next {#接下来}

| If you want to know | Read |
|---|---|
| What all those words on screen actually mean | [Core concepts](concepts.md) |
| Every subcommand and flag, exhaustively | [CLI reference](../reference/cli.md) |
| Why it asks a pile of questions first, and how to make it ask less | [Clarify](../guide/clarify.md) |
| Who rules on "is it done", and how to write the verdict checklist | [Goal guard](../guide/goal.md) |
| Why running again in the same directory picks up where it left off | [Continuity](../guide/continuity.md) |
| What it does when context fills up (not compact) | [Handoff](../guide/handoff.md) |
| Credentials, gateways, model names, environment variables | [Config reference](../reference/config.md) |
| Replacing the terminal — Web / TUI / fully automatic | [Interaction layer](../guide/interaction.md) |
| Skipping the built-in three steps and writing your own workflow | [Designing workflows](../guide/workflow.md) · [Python API](../reference/api.md) |
| What actually happened in a real long run | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| The precise definition of a term | [Glossary](../reference/glossary.md) |
