# Quickstart

This page takes you from "it's installed" to "I ran a real one, and I understand what's on screen."
Four sections, in order: first prove credentials and binary both work with the cheapest possible
call, then run a full workflow with zero code, then learn how to talk to it while it's running,
and finally put it in a script and let it run unattended.

There is exactly one prerequisite: `flower` is installed, on your PATH, credentials configured.
If not, start with [Install](install.md).

## Step 1: Verify with the cheapest possible shot {#冒烟}

Don't start with a full workflow. Fire one single-agent, read-only call first, to prove that both
ends — credentials and binary — work:

```bash
flower -v -w /path/to/any/repo once "读一眼这个仓库,一句话说它是干什么的"
```

| This bit | What it is |
|---|---|
| `once` | Run a single agent once: no clarify, no goal, no dispatch |
| `-w PATH` | The agent's working directory. Defaults to the current directory |
| `-v` | Print the effective credential config before starting; only the first 4 characters of the token are shown |

`once` gives the agent only three tools — `Read`, `Glob`, `Grep`. It can't write anything, so this
call is cheap. Measured reference: Opus 5 with a 1M window through a third-party gateway,
**the floor price for a single round is $0.1741**; cheaper models go lower.

!!! tip "If you came from the install page, skip ahead"
    The "verify the install" section of [Install](install.md) runs exactly this command. If it
    already worked, move on — the rest of this section just teaches you how to read the output.

When it finishes you should see this shape — the numbers and the prose will differ,
**the icons will not**:

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

Four things to recognize — the rest of this page depends on them:

- The first few lines are the effective config printed by `-v`. **Pointing at the wrong gateway is
  visible at a glance** — that's the main reason this flag exists.
- `- 验一下凭证…` is a real API probe before the run starts. If the credentials are rejected it
  prints `! 凭证被拒:…` and asks you on the spot whether to reconfigure; if it can't connect it
  prints `(探针没打通:… —— 当作网络问题,照常开跑)` and **does not** send you off to reconfigure a
  token that was fine all along.
- The icons are always ASCII: `~` thinking, `*` tool call, `>` dispatch, `+` success, `x` failure,
  `?` question, `<-` resuming from last time. Not emoji — emoji and box-drawing characters trigger
  glyph fallback in terminals, and that crashed a terminal twice in practice. **Every terminal
  sample in this documentation uses this same ASCII set, identical to what's on your screen.**
- The `$` on the `+ 完成` line is real; `累计` and `用时` are permanently 0 on the `once` path
  (a new renderer is created per event, so state never accumulates).

If this call works, credentials, gateway, model name, and the bundled binary are all correct. If it
doesn't, that's an install problem — back to [Install](install.md).

## Step 2: Run a full workflow with zero code {#跑一次}

You don't need to write any code, and **you don't need to quote anything in the shell**. Go to your
project directory and type:

```bash
cd /path/to/your/project
flower
```

It asks what you want done, cursor sitting on `>`:

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

That line is read from standard input and **does not go through shell parsing** — full-width quotes,
spaces, exclamation marks all type through fine.

After you hit enter it goes through three steps. Every `==` rule on screen is one
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

Three places worth a second look:

- The last two `+ 完成` lines are not a duplicate. The first is the work round, the second is the
  **verdict** round — the verdict runs in its own session, but **does not get its own `==` rule**,
  because it's a round inside the `干活` step. Its name in the
  [run manifest](../reference/glossary.md#运行清单) is `干活·判定#1`.
- The `$` on a `+ 完成` line is the cost of **that round**; `用时` is the total elapsed time **from
  the start of the run to now**. Two different measures.
- Status lines like `- 上下文 … · 累计 … · …` track the [main thread](../reference/glossary.md#主线程)
  only; subagent context is not in there. Subagent tool calls are shown by default, indented behind
  a `|` bar; **what they say** requires `-v` to see — that's the shop floor, not the decision.

### What those three steps are {#三步}

| Step on screen | Who runs it | What it does | Frozen into | Details |
|---|---|---|---|---|
| `确认需求` | [Clarifier](../reference/glossary.md#确认者) | Only asks questions, touches nothing, **keeps asking until it's clear, with no round cap**; finally emits a four-section [brief](../reference/glossary.md#需求确认书) | `.flower/notes/需求.md` | [Clarify](../guide/clarify.md) |
| `设定目标` | [Judge](../reference/glossary.md#判定者) | Translates the brief into "goal + verdict checklist", where every item must be verifiable on the spot | `.flower/notes/目标.md` | [Goal guard](../guide/goal.md) |
| `干活` | [Coordinator](../reference/glossary.md#协调者) dispatching [subagents](../reference/glossary.md#subagent) | The coordinator splits the work, dispatches, reads reports, decides; at the end of each round a judge that **did not participate in the work** independently rules on "is it done", and sends it back if not | The code itself | [Goal guard](../guide/goal.md) |

The first two steps are where the [clarify](../reference/glossary.md#前置确认) and
[goal guard](../reference/glossary.md#目标看守) mechanisms land; the third step is the stretch they
jointly govern. By default it runs at most 3 verdict rounds (`--rounds`), and `--no-goal` turns the
whole thing off — with it off, "it says it's done" really does mean done.

A verdict has exactly three outcomes: met, not met, **cannot be verified in this environment**. The
last two are different conclusions — "can't verify here" never passes; it stops and asks you.

A full run is not cheap. Measured reference: [HT002](../cases/ht002.md) installed and got an
existing project running on macOS — 4 steps, about 1 hour, **$38.24**;
[HT001](../cases/ht001.md) wrote a terminal IDE from scratch — **10.4 hours, $171.62**. If you want
to see what it will ask before committing to a full run, use `--clarify-only`.

### How to answer questions {#答提问}

A block starting with `?` is it asking you. Three ways to answer:

- **Type a number** (`1` / `2` / `3`) — picks that option; the screen echoes a `+ <the option you picked>` line.
- **Just type** — free-form answer, doesn't have to be one of the options.
- **Just hit enter** — skip and let it decide; the screen echoes `. 已跳过`.

It waits 1800 seconds by default (`--timeout`). If nobody answers it prints
`! 无人应答 —— 它会自己判断,把假设记进「未知与假设」` and keeps going; it never hangs.
The number of questions is **unlimited by default** (`--asks` defaults to `-1`); a positive number
is a hard quota, and running out prints `! 提问额度用完`.

### Running again resumes the last one {#再跑一次}

Type `flower` again in the same directory and the first line changes:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> 顺便支持代码块高亮
<- 在 ~/proj 接上上次  需求已确认 · 目标 7 条 · 干活上下文 71.4K · 第 3 次唤醒
```

The `<-` line is the [wake](../reference/glossary.md#唤醒) banner; it reports the current state of
this directory. It won't interrogate you about the requirements again, and it won't re-derive the
goal; same after the process is killed or the machine reboots.
Whatever you say here is appended to `需求.md` and **triggers re-derivation of the verdict
checklist** — without the re-derivation the judge would still be reading the old checklist, and the
thing you just added would never make it into a verdict.
Details and cost (context keeps growing) in [Continuity](../guide/continuity.md).

If you don't want to resume, type `/new`: the previous requirements, goal, and
[lineage](../reference/glossary.md#血缘) are **moved** into `notes/archive/<timestamp>/` (not
deleted), and it starts over.

## Step 3: You can still talk to it once it's running {#插话}

There is always a typable prompt at the bottom of the screen. It's not decoration — it is erased
before each output line and redrawn after, so it **never scrolls away with the log**. Two variants,
switching on whether there's a pending question:

```text
你的回答 (回车=跳过,让它自己判断) >
(直接说 = 加需求,下个检查点送达;? 开头 = 顺便问一句,不打扰它干活) >
```

When there is no pending question, you can do two things.

**Just type a sentence = add a requirement.** It is not interrupted; it sees it the next time it
checks the inbox. The receipt looks like this:

```text
+ 收到 (它下次查收件箱时会看到;已追加进确认书)
```

"Appended to the brief" matters: that sentence also lands in `需求.md`, so it survives step
boundaries — the next step is a new session that only reads the frozen artifacts, and anything not
spilled to disk might as well not have been said.

**Start with `?` = ask a side question.** It spins up a separate read-only session to answer you,
holding only the last 60 events and whatever is on the [workbench](../reference/glossary.md#工作台).
This side path is run by the [oracle](../reference/glossary.md#旁路顾问), capped at 12 rounds /
$0.5 by default:

```text
? 现在到哪了
# 旁路
  在干活第二轮,coder 刚补完 parser 的测试,正在跑第三次验证。
  ($0.0123,没有打扰正在跑的运行)
```

**Answered and discarded** — that exchange does not enter the context of this run, and its cost does
not enter the main run manifest; it's recorded in its own manifest under `runs/aside/`. So asking
neither disturbs the run nor pollutes its books.

!!! warning "Full-width `？` doesn't count — it must be half-width `?`"
    Side questions are recognized only by the **half-width** `?` (ASCII `0x3f`). The full-width `？`
    that Chinese IMEs produce by default is not recognized — that line gets treated as "add a
    requirement" and goes into the inbox, **with no error**; the answer you're waiting for simply
    never arrives. This is a typo in the code, already on the defect list; until it's fixed, switch
    your IME to English before typing `?`.

While we're here, Ctrl+C: pressing it once mid-run **interrupts the current round and lets you say
something**, it does not exit.

```text
! 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
>
```

A second press actually exits. (Pressing Ctrl-C at the initial `要做什么?` prompt exits immediately
and prints `已取消`.)

## Step 4: Put it in a script {#脚本}

The request can also be passed as an argument, with flags before or after it:

```bash
flower "帮我做一个 X"                      # request as an argument
flower --rounds 5 "帮我做一个 X"           # flags first
flower "帮我做一个 X" --rounds 5           # flags last, equivalent
echo "帮我做一个 X" | flower --timeout 0   # piped to stdin, fully unattended
```

Flags with no request works too — `flower --clarify-only` asks you what you want first, then
continues.

**Why the "type it after the enter" path still exists.** Those quotes on the command line are pure
overhead. Seen in practice: the closing quote was typed as a Chinese `”`, zsh kept waiting for a
real closing quote (dropping into the `dquote>` continuation prompt), and it looked like the program
had hung — when in fact it had never started. Bare `flower` reads standard input, with no shell
parsing, so full-width quotes, spaces, exclamation marks, and newlines all type through fine. The
pipe case goes through the same entry point — when standard input isn't a terminal, it prints no
prompt header and just reads a line.

!!! danger "Unattended runs must pass `--timeout 0` explicitly"
    In a pipe, under `nohup`, or in CI there is nobody to answer questions. Without `--timeout 0`:
    the first question is skipped because "input is closed", and **every question after that waits
    out the full 1800 seconds** — a few questions is a few hours of spinning, and that time is
    burning money.
    `--timeout 0` makes every question return "nobody answered" immediately, and it decides for
    itself and moves on.
    When standard input isn't a terminal, flower prints a reminder first:
    `! 标准输入不是终端,没人能回答提问。想让它自己判断就加 --timeout 0`

## What to read next {#接下来}

| If you want to know | Read |
|---|---|
| What all those words on screen actually mean | [Core concepts](concepts.md) |
| Every subcommand and flag, with nothing left out | [CLI reference](../reference/cli.md) |
| Why it asks a pile of questions first, and how to make it ask less | [Clarify](../guide/clarify.md) |
| Who rules on "is it done", and how to write a verdict checklist | [Goal guard](../guide/goal.md) |
| Why running again in the same directory picks up where it left off | [Continuity](../guide/continuity.md) |
| What it does when the context fills up (it is not compact) | [Handoff](../guide/handoff.md) |
| Credentials, gateways, model names, environment variables | [Config reference](../reference/config.md) |
| Replacing the terminal — wiring up Web / TUI / fully automated | [Interaction layer](../guide/interaction.md) |
| Skipping the built-in three steps and writing your own workflow | [Designing a workflow](../guide/workflow.md) · [Python API](../reference/api.md) |
| What actually happened in a real long run | [HT001](../cases/ht001.md) · [HT002](../cases/ht002.md) |
| The exact definition of some term | [Glossary](../reference/glossary.md) |
