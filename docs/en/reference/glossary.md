# Glossary

This page is the terminology baseline for the flower documentation. Each concept has exactly one
name across the whole site, and the Chinese/English pairing is fixed here — the translated
versions follow this same table.

Each entry gives you three things: **what the term refers to**, **what it is in the code**, and
**what it is not**. The third is usually the most useful, because most confusion comes from
mistaking one of these terms for another.

---

## Framework and execution

### long-horizon {#long-horizon}

*Chinese: 长程*

A single run that spans hours to days, spans multiple sessions, and survives process restarts —
as opposed to a single question and answer. Every mechanism in flower exists to keep that kind of
run from falling apart halfway through.

For reference: [HT001](../cases/ht001.md) ran continuously for 10.4 hours.

### run {#run}

*Chinese: 运行*

One `Runtime` from start to finish. A single run can contain several [steps](#step) and burn
through several [sessions](#session), and it can be interrupted and [continued](#continuity)
later. Runs are recorded in `runs/manifest.json` and `runs/sessions.db`.

**Not**: a single API call, and not a session.

### session {#session}

*Chinese: 会话*

One context on the model's side. It has its own `session_id` and can be resumed or forked. A
single [run](#run) may consume several sessions — every [handoff](#handoff) starts a fresh one.

### step {#step}

*Chinese: 步骤* · `Step`

One executable unit inside a [workflow](#workflow). It receives a context dictionary, runs an
agent, and writes its result back into that dictionary. `Step` is a class; see the
[Python API](api.md#step).

### workflow {#workflow}

*Chinese: 流程* · `Workflow`

An ordered set of [steps](#step), plus the rules for how state passes between them and when to
exit early.

!!! note "The framework ships no ready-made workflows"
    flower provides mechanisms only. **The workflow is yours to write.** See
    [Designing a workflow](../guide/workflow.md).

---

## Roles

A role is how flower divides labour between agents. Each role is a block of injected rule text
plus a tool set plus a set of hooks. All five roles are factory functions; see the
[Python API](api.md#role-factories).

### coordinator {#coordinator}

*Chinese: 协调者* · `coordinator()`

The agent on the [main thread](#main-thread). It decomposes the task, delegates, reads reports and
makes decisions — but it never does the work itself: it has no `Bash`, `Write` or `Edit`. Its
only tools are `Agent`, `TodoWrite` and `Read`.

Its brief is to act like *a person who is good at using Claude Code*, not like an executor.

**Not**: a smarter agent. It runs at the same model tier as its [workers](#worker) by default.
What you save is context, not model quality.

### worker {#worker}

*Chinese: 执行者* · `worker()`

The [subagent](#subagent) that actually does the work: writing code, running tests, looking things
up. Its tools are `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `WebFetch` and `WebSearch`.

Its rule text constrains every report to four sections — **conclusion / evidence / output /
unverified** — capped at 30 lines, with file contents, command output, logs and raw diffs banned.

### clarifier {#clarifier}

*Chinese: 确认者* · `clarify()`

The role that pins the requirements down before any work starts. It does nothing but ask
questions, and it keeps asking until things are clear (**there is no turn limit**), then produces
a [brief](#brief). See [Clarify first](../guide/clarify.md).

### judge {#judge}

*Chinese: 判定者* · `judge()`

The role that decides whether the work is actually done. It does one of two jobs: **setting the
goal** before the run (producing a goal plus a checklist), or **judging a round** at the end of
each one (producing a [verdict](#verdict)). See [Goal guard](../guide/goal.md).

**The critical part**: a judge assesses the **artifact**, not the source. See the failure in
[HT002](../cases/ht002.md) — it read the macOS branch of a Makefile, passed the round, and what
had actually been delivered was a Linux ELF binary.

### oracle {#oracle}

*Chinese: 旁路顾问* · `oracle()`

A read-only side channel. While a run is still going, you can ask it where things stand; it looks
at recent events and the [workbench](#workbench) and answers. **Nothing it says enters the run's
context** — asking costs the run nothing, and the answer is discarded.

### subagent {#subagent}

A Claude Agent SDK concept: a child agent dispatched by the main agent through the `Agent` tool.
It gets **its own transcript**, so its tool calls and dead ends are recorded there while the main
thread receives only the final report.

This is flower's first and largest context saving. See
[The economics of context](../guide/context.md).

---

## The four mechanisms

### clarify {#clarify}

*Chinese: 前置确认*

Pin the requirements down before starting, freeze them into a [brief](#brief), then execute.
Guards against *building the wrong thing*. See [Clarify first](../guide/clarify.md).

### brief {#brief}

*Chinese: 需求确认书* · `Brief`

The document a [clarifier](#clarifier) produces once questioning is over, in **exactly four
sections**. Later steps read it instead of guessing at the requirements again.

**Do not confuse** this with a [task brief](#task-brief). A brief is *what the human wants*; a
task brief is *what this subagent is doing this time*.

### task brief {#task-brief}

*Chinese: 任务书*

The instructions a [coordinator](#coordinator) writes when delegating to a [worker](#worker). It
should contain **only what is specific to this task** — never restate discipline the worker
already knows.

Measured: 8 out of 8 task briefs restated rules the recipient already had. In the shortest one,
roughly 120 characters out of 521 were task-specific; a single round wasted about 4.8k of
permanent context.

### goal guard {#goal-guard}

*Chinese: 目标看守*

A [judge](#judge) independently decides at the end of each round whether the goal has been met,
and sends the work back if it has not. Guards against *claiming done when it isn't*. See
[Goal guard](../guide/goal.md).

### verdict {#verdict}

*Chinese: 判定* · `Verdict`

The result of one round of judging, in **exactly three sections**: conclusion / reasoning /
what failed.

There are three possible conclusions: `ACHIEVED`, `NOT_YET`, and `UNREACHABLE` (this environment
cannot verify it). **The last two are different conclusions** — "can't be verified here" is never
allowed to pass.

### continuity {#continuity}

*Chinese: 接续*

Running again in the same directory picks up where the last run left off — including after the
process was killed or the machine rebooted. Guards against *losing hours of work to a crash*. See
[Continuity](../guide/continuity.md).

**Do not confuse** this with [handoff](#handoff): continuity resumes a previous run **across
processes**; a handoff swaps in a new session **inside one run**.

### handoff {#handoff}

*Chinese: 换代*

When the context is nearly full, the current session writes a document a human can read and edit,
and a fresh session takes over from it. Guards against *the context being crushed into a
summary*. See [Handoff](../guide/handoff.md).

**Not** a compact. See [compact](#compact).

### handoff document {#handoff-document}

*Chinese: 交接书* · `Handoff`

The document written at handoff time, in five sections: `doing`, `decided`, `deadends`, `next`
and `scene`.

**Only `doing` and `next` are required** — mandating a non-empty "dead ends" section pushes the
model into inventing them.

### compact {#compact}

*Chinese: 压缩*

Claude Code's native behaviour: when the context fills up, summarize the earlier conversation
into a single block.

flower **does not use it**, and does [handoff](#handoff) instead. The difference: a summary is
model-generated, unreadable, uneditable, and gives you no idea what was dropped; a handoff
document is structured, written to disk, and you can open it, change a line and let the run
continue.

---

## Context management

### main thread {#main-thread}

*Chinese: 主线程*

The session context the [coordinator](#coordinator) lives on. It is the only context that spans
the whole run, which is exactly why it is the one worth economizing.

How the code identifies it: the hook payload has **no** `agent_id`. Subagent hooks carry one.

### workbench {#workbench}

*Chinese: 工作台* · `Workbench`

The on-disk working directory, `.flower/` by default, with three subdirectories:

| Directory | Holds |
|---|---|
| `scripts/` | Scripts worth running twice, with `# desc: one line` on the first line |
| `artifacts/` | Any output longer than 2000 characters |
| `notes/` | Key decisions, one decision per file |

`INDEX.md` indexes all three and is **injected into the system prompt**, so the agent knows every
round what it already has on hand.

!!! warning "Subagents do not inherit the index"
    The index goes in via a session-level `system_prompt.append`, which **subagents never see**.
    So the rule *put long output in `artifacts/`* has to be restated by the
    [coordinator](#coordinator) in the [task brief](#task-brief) — that is the only channel.

### spill {#spill}

*Chinese: 落盘*

When a tool result exceeds a threshold (4000 characters by default), a `PostToolUse` hook writes
it to `.flower/spill/` and leaves a single path in the context.

**Pruned on the spot**, rather than [compacted](#compact) after the context is already full.

### ephemeral command {#ephemeral-command}

*Chinese: 一次性命令*

A command whose result goes stale and is not worth keeping — `ls`, `git status`, `ps` and the
like. Their results never reach the persisted session record. The same function decides both
*may the main thread run this for a quick look* and *will this result be trimmed*, so the two
sets are always identical.

### trim {#trim}

*Chinese: 裁剪* · `TrimmingSessionStore`

On write to the session store, drop messages not worth keeping: results of
[ephemeral commands](#ephemeral-command), oversized tool output.

### prune {#prune}

*Chinese: 剪除* · `PruningSessionStore`

Keep **error messages** out of the context. A pile of failures produced while retrying through a
network outage should not occupy context after the resume.

**Do not confuse** with [trim](#trim): trim drops by size and value, prune drops by *is this an
error*.

---

## Runtime

### isolation {#isolation}

*Chinese: 隔离*

Roles marked for it are automatically given their own git worktree, enforced by a hook rather
than by prompting. Parallel work on one repository stops colliding.

!!! warning "Turning on isolation means moving the workbench out of the repo"
    With worktree isolation on, the [workbench](#workbench) must be pointed outside the
    repository with `home=`, or the isolated agent cannot write into the shared checkout.

### resilience {#resilience}

*Chinese: 韧性* · `Resilience`

When the network drops, wait it out instead of exiting: DNS and TCP probes watch for recovery,
then the run resumes. Errors produced while waiting are kept out of the context by
[prune](#prune).

### lineage {#lineage}

*Chinese: 血缘* · `Lineage`

A cross-process record of which session this run was forked from. [Continuity](#continuity)
relies on it to find where the last run got to.

### event {#event}

*Chinese: 事件* · `Event`

The SDK's message stream flattened into a stable shape. **The [interaction layer](#interaction-layer)
sees only `Event` and imports no SDK types** — that is the boundary that lets you swap the UI
without touching the core.

### interaction layer {#interaction-layer}

*Chinese: 交互层*

The UI between a human and a run. The default is a terminal; it can be replaced with a web UI, a
TUI, HTTP, or nothing at all for unattended runs. See
[Swapping the interaction layer](../guide/interaction.md).

### session store {#session-store}

*Chinese: 会话存储* · `SessionStore`

The persistence backend for session messages. The default `SqliteSessionStore` writes to
`runs/sessions.db`, and can be wrapped in the [trim](#trim) and [prune](#prune) layers.

### budget {#budget}

*Chinese: 预算* · `max_budget_usd`

A spending ceiling for one run; the run stops when it is hit. Long-horizon runs get expensive
without one — [HT001](../cases/ht001.md) cost $171.62.

---

## Portability

### portable {#portable}

*Chinese: 可移植*

Same behaviour on a different machine. The mechanism is `setting_sources=[]`: flower reads
neither the host's `~/.claude/` nor the project's `.claude/`. Domain capability travels with the
repository as a [plugin](#plugin); credentials travel in `.env`.

The price: **you must bring your own credentials**. Nothing is inherited from the host's setup.

### append {#append}

*Chinese: 叠加*

Domain instructions are appended **after** Claude Code's native system prompt rather than
replacing it:

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

So specialization does not cost you general capability.

### plugin {#plugin}

*Chinese: plugin*

A domain-capability package that travels with the repository. Loaded through `plugins=[local]`;
the directory can hold `skills/`, `agents/`, `hooks/` and `.mcp.json`. See
[Deployment](deploy.md#plugin).
