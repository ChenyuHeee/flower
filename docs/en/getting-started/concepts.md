# Core concepts

flower has a vocabulary of its own: run, step, session, coordinator, worker, clarify, goal guard,
continuity, handoff. This page covers all of it in one pass, so the other pages don't have you
guessing as you read. Five minutes.

Concepts only — **no API signatures** here. For signatures see [Python API](../reference/api.md);
for one-line definitions and the Chinese/English mapping see the [glossary](../reference/glossary.md);
for command-line flags see the [CLI reference](../reference/cli.md).

## The shape of a single run {#形状}

Three levels, largest to smallest:

| Term | What it is | Where it's recorded |
|---|---|---|
| [run](../reference/glossary.md#运行) | One complete pass of a `Runtime`, start to finish. On the default path, one run is one time you type `flower` | `runs/manifest.json` |
| [step](../reference/glossary.md#步骤) | One executable unit inside a run: take a context dict, run an agent, write the result back into the dict. Every `==` rule on screen is a step boundary | same file, one line per step |
| [session](../reference/glossary.md#会话) | One context on the model side. Has its own `session_id`, can be resumed, can be forked | `runs/sessions.db` |

The nesting is not one-to-one:

```text
run ── the one time you typed flower
 ├── step clarify ──────── session A
 ├── step set goal ─────── session B
 └── step work ─────────── session C ──[context nearly full]──> session C'
      └── work·verdict#1 ── session D
```

- **One step can burn through several sessions.** When the context is nearly full it does not
  compact; it writes a handoff document and opens a new session to take over — this is
  [handoff](../reference/glossary.md#换代), and it happens **inside a single run**.
- **A new run can pick up old sessions.** Type `flower` again in the same directory and each step
  reattaches to the session it used last time — this is
  [continuity](../reference/glossary.md#接续), and it happens **across processes**. It relies on
  `runs/lineage.json` to remember "which step name maps to which `session_id`".
- **The verdict round is always a fresh session.** It has no continuity and never enters the
  lineage — whoever judges "is this done" cannot be the worker that just did it.

A group of steps chained in order is a [workflow](../reference/glossary.md#流程).
Bare `flower` uses the framework's own three-step workflow: clarify → set goal → work.

## Division of labour: the coordinator doesn't touch anything {#分工}

**This is the one thing the whole framework is built on.**

The [coordinator](../reference/glossary.md#协调者) is the agent on the
[main thread](../reference/glossary.md#主线程). It decomposes tasks, dispatches work, reads
reports, makes decisions — but it **does not get `Write` or `Edit`**, and its `Bash` is only enough
to run [ephemeral commands](../reference/glossary.md#一次性命令) like `ls` or `git status` for a
quick look (enforced by a hook, not by prompt wording — and those results never enter the persisted
session record). Its tool list is exactly `Agent`, `TodoWrite`, `Read`, plus that restricted `Bash`.

The one that actually does the work is the [worker](../reference/glossary.md#执行者) — a
[subagent](../reference/glossary.md#subagent) dispatched via the `Agent` tool.

**Why split it this way.** A subagent has **its own transcript**: how many files it read, how many
times it ran the tests, how many dead ends it backed out of — all of that stays on that transcript;
the main thread only receives the final report. And the main thread is the one context that spans
the entire run, so it is the one that most needs saving.

Measured ([HT001](../cases/ht001.md), a 10.4-hour run):

| | Main thread | Subagents | Share pushed down |
|---|---|---|---|
| Model turns | 70 | 3.0K | 97.7% |
| Body characters | 200.1K | 3.6M | **94.8%** |
| Tool calls | 32 | 1,893 | —— |

On average, every dispatch hides **82 tool calls the main thread never sees**. This is the first
layer of context saving, and the largest one; the full argument is in
[context economics](../guide/context.md).

Two things that are easy to misread:

- **The coordinator is not a smarter agent.** By default it runs the same model tier as the worker.
  What's saved is context, not model.
- **The reply format is constrained.** A worker's reply is exactly four sections — conclusion /
  evidence / output / unverified — no more than 30 lines, and it may not paste file contents,
  command output, logs, or raw diffs. Long material goes into `artifacts/` on the
  [workbench](../reference/glossary.md#工作台); the reply carries only the path.

flower has five roles, all built the same way: a block of injected rule text + a set of tools + a
set of hooks.

| Role | What it does | What it holds |
|---|---|---|
| [coordinator](../reference/glossary.md#协调者) | Decompose, dispatch, decide | `Agent` `TodoWrite` `Read` + restricted `Bash` |
| [worker](../reference/glossary.md#执行者) | Write code, run tests, look things up | `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| [clarifier](../reference/glossary.md#确认者) | Only asks questions before any work starts, until things are clear | Question tools + read-only tools, **no write tools at all** |
| [judge](../reference/glossary.md#判定者) | Sets the goal, or rules on whether this round is done | Question tools + `Read` `Glob` `Grep` (letting it run commands must be enabled explicitly) |
| [oracle](../reference/glossary.md#旁路顾问) | Answers "where are we now" mid-run | `Read` `Glob` `Grep`. **What it says never enters that run's context** |

Factory function parameters and defaults are in [Python API](../reference/api.md#角色工厂).

## Long-horizon breaks in four places {#四个机制}

A [long-horizon](../reference/glossary.md#长程) run spans hours to days, spans multiple sessions,
spans process restarts. It only falls apart in a handful of ways, and each one has a mechanism
against it:

| What you're afraid of | Mechanism | What it does | Details |
|---|---|---|---|
| What comes out isn't what you wanted | [clarify](../reference/glossary.md#前置确认) | Pin the requirement down with questions before any work starts, freeze it into a [brief](../reference/glossary.md#需求确认书); every later step reads it instead of guessing again | [Clarify](../guide/clarify.md) |
| It says it's done, and it isn't | [goal guard](../reference/glossary.md#目标看守) | At the end of each round a judge that did none of the work rules on it independently; if the goal isn't met, it goes back for more | [Goal guard](../guide/goal.md) |
| It runs for hours, crashes, and you start over | [continuity](../reference/glossary.md#接续) | Running again in the same directory picks up where it left off — same after a killed process or a rebooted machine | [Continuity](../guide/continuity.md) |
| The context fills up and gets squashed into a summary | [handoff](../reference/glossary.md#换代) | When it's nearly full, the current session writes a [handoff document](../reference/glossary.md#交接书) a human can read and edit, then a new session takes over | [Handoff](../guide/handoff.md) |

Two points worth remembering on their own:

**A [verdict](../reference/glossary.md#判定) has three outcomes, not two.** Met, not met, and
**can't be verified in this environment**. The last two are different conclusions — "can't be
verified here" is never ruled a pass; it stops and asks a human.
And the judge rules on the **artifact**, not the source: [HT002](../cases/ht002.md) got burned once
— it read only the macOS branch of the Makefile and ruled a pass, while what was actually delivered
was a Linux ELF.

**Handoff is not [compaction](../reference/glossary.md#压缩).** Compaction is the model quietly
summarizing the earlier conversation into a blob: unreadable, uneditable, and you don't know what
was lost. A handoff document is structured, sits on disk, and you can open it, change a line, and
let it keep going. flower turns native auto-compact off by default and uses handoff instead.

Two more layers aren't in that table but run on every run:

- [spill](../reference/glossary.md#落盘) — any tool result over 4000 characters is written to
  `.flower/spill/`, and only a one-line path stays in the context. **Trimmed on the spot**, not
  compacted after the fact.
- [workbench](../reference/glossary.md#工作台) — the three directories `scripts/`, `artifacts/`,
  `notes/` under `.flower/`, plus an `INDEX.md` injected into the system prompt, so the agent knows
  every round what it has on hand. That HT001 run accumulated **61 scripts, executed 331 times**,
  and **92%** of them were executed more than once.

## What flower does not do {#不做什么}

**One: it does not ship ready-made workflows.** The framework covers mechanism only: how a step
runs, how context is saved, how it resumes after a dropped connection, how parallel edits to the
same repository avoid colliding, how it stops when a human needs to be asked. **The workflow is
yours to write.** The three steps bare `flower` uses come from
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py),
generic enough to carry no domain assumptions — they exist to get you started, not to mark the
framework's ceiling. To write your own, see [designing a workflow](../guide/workflow.md).

**Two: it does not inherit host configuration.** flower runs with `setting_sources=[]`: it does not
read the host's `~/.claude/`, nor the project's `.claude/`. That is what
[portable](../reference/glossary.md#可移植) means — the same behaviour on a different machine.
Domain capability comes from [plugins](../reference/glossary.md#plugin) that travel with the
repository, not from whatever happens to be installed on this machine.

**Three: credentials must be brought yourself.** That is the price of point two. flower looks for
credentials in a fixed order (process environment variables → `$FLOWER_ENV` → `.env` in the current
directory → `~/.config/flower/.env` → `.env` at the source repository root), and finally borrows the
9 credential keys from the `env` block of `~/.claude/settings.json` as a fallback —
**it borrows only "where to find the token"**; nothing else in settings.json affects agent
behaviour. The full order and the meaning of each variable are in the
[configuration reference](../reference/config.md).

**Four: it does not replace the system prompt.** Domain instructions are
[appended](../reference/glossary.md#叠加) **after** Claude Code's native system prompt, not
substituted for it. So specialization doesn't cost you general capability.

---

If you've read this far, the output in [quickstart](quickstart.md) should all make sense now.
To learn how each mechanism is tuned and when not to use it, start from
[context economics](../guide/context.md); if you just want commands to copy, go to the
[CLI reference](../reference/cli.md).
