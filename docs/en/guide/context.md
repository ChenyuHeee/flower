# Context Economics

The [main thread](../reference/glossary.md#主线程)'s context is the only thing that runs end to end
through a [long-horizon](../reference/glossary.md#长程) run; what it holds and what it doesn't decides how
far that run gets. The shape of flower — the [coordinator](../reference/glossary.md#协调者) never touches
anything, long outputs go to disk, hooks prune on the spot — all follows from this one fact.
This page explains why.

## What problem it solves

[Compaction](../reference/glossary.md#压缩) waits until the context is full and then summarizes in
hindsight; it treats the symptom. The real problem is: **trivia should never have entered the main
thread in the first place.**

The difference is timing. One `pytest` run easily emits tens of thousands of characters; the model
glances at it, takes one conclusion, and the remaining characters get re-sent every single turn from
then on. Once the window fills, compaction summarizes them together with the decisions sitting next
to them into a single paragraph — what you save is volume, what you lose is "why we decided this in
the first place." Auto-compact fires at **window − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)); by that
moment, what should be dropped and what shouldn't are already lying side by side.

flower solves it in four layers; the order is the priority order — sorted by how much each saves:

| Layer | What it does | Where |
|---|---|---|
| 1. Division of labor | Hands-on work is delegated to [subagents](../reference/glossary.md#subagent); trial and error goes into their own transcript | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. Workbench | Scripts / long outputs / decisions go to disk, the index is injected into the system prompt | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. Spill on the spot | A `PostToolUse` hook spills over-threshold tool results to disk, leaving one line of path in context | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. Trim and prune | Rewrite the session before resume: stale results, denied calls, disconnect residue are not fed back | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

The first two layers govern **whether things get in**; the last two govern **whether what got in
stays**. The order can't be reversed: no matter how aggressive layer four is, it can't claw back the
volume that layer one let slip through.

## How to use it (minimal code)

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model defaults to "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

These few lines install the first three layers: `coordinator()` always sets `delegate_only=True`
(layer one); `workbench=True` creates the [workbench](../reference/glossary.md#工作台) and injects the
index into the coordinator's system prompt (layer two), and at the same time makes `Runtime` install
`spill_guard` (layer three). Layer four is on by default — `Runtime`'s
[session store](../reference/glossary.md#会话存储) is hard-wired to `PruningSessionStore`, and there is no
constructor parameter to swap it out.

!!! warning "`workbench=True` is not optional"
    `delegate_guard`, which stops the coordinator from doing the work itself, hangs off
    `workbench_hooks`, and `workbench_hooks` is only installed when `Runtime` has a workbench;
    `whitelist_guard` is skipped because of `delegate_only=True`.
    Conclusion: **with `Runtime(workbench=False)` plus `coordinator()`, there is not a single wall in
    front of the main thread's Bash / Write / Edit.**

## What it actually does

### Layer one: division of labor (saves the most)

The coordinator plays "a person who knows how to use Claude Code": decompose, delegate, read
reports, decide. It does not get Bash / Write / Edit — its tools are only `Agent`, `TodoWrite`, `Read`
(plus a restricted `Bash` when `glance=True`, see below). All hands-on work is delegated to
[workers](../reference/glossary.md#执行者).

**When it fires**: every time the main thread calls `Bash|Write|Edit|NotebookEdit`, the `PreToolUse`
hook `delegate_guard` denies it on the spot and points the way — "use the Agent tool to dispatch a
subagent, state the goal and acceptance criteria in the task, and require it to write long outputs
into `.flower/artifacts/` and report back only paths and conclusions." Subagents are always let
through. The test is whether the hook data carries an `agent_id`: **no `agent_id` means main thread.**

**How much it saves**: a subagent's tool calls and trial and error **go into its own transcript**
(distinguished by `subpath` in the session store); the main thread keeps only that one `Agent` call
and the final report. The trial-and-error process wasn't compacted away — it **never entered the main
thread at all**.

- Measured (a task that produces a lot of tool output): 83% of the transcript lands in the subagent;
  main thread 13 entries, 21K characters, subagent 105K characters.
- Measured (real scale, a 10.4-hour run, see [HT001](../cases/ht001.md)): subagents carry
  **97.7%** of turns and **94.8%** of body characters; 1,893 hands-on tool calls vs 32 in the main
  thread (**59:1**). Early compaction is no longer the main storyline.

The two lines are two different measurements: the first is an earlier small-scale test, the second a
re-measurement at real scale. Same mechanism; the larger the scale, the more it saves.

What it saves is context, not model tier: `worker()` defaults to `model="inherit"` — workers should
not be downgraded.

The only reverse cost of the division of labor is the [task brief](../reference/glossary.md#任务书) —
the paragraph the coordinator writes when delegating. It enters the main thread and stays there
forever. Measured: 8 out of 8 task briefs restated discipline the other side already knew; the
shortest one, 521 characters, had only about 120 characters that were task-specific — about 4.8k of
permanent context wasted per round. So `COORDINATOR_RULES` hard-codes one line: **a task brief
contains only what is specific to this task**. The one convention still worth stating is "where the
workbench is + write long outputs to `artifacts/` + report back only paths and conclusions" — because
the workbench index cannot reach subagents, the task brief is the only channel.

### Layer two: the workbench (fixes "rewriting it every time")

Three directories under `.flower/` travel with the workspace:

| Directory | What goes in | What it solves |
|---|---|---|
| `scripts/` | Verification / reproduction scripts that will be run a second time, first line `# desc: one sentence` | Write once, just run it later. No more "lost after compaction, rewritten every time" |
| `artifacts/` | Long outputs over 2000 characters: logs, data, reports, diffs | Only paths and conclusions appear in the conversation |
| `notes/` | Key decisions and their rationale, one file per decision | Compacted, restarted, moved to another machine — the conclusions are still there |

**When it fires**: `INDEX.md` is generated automatically (at most 40 entries by default); `refresh()`
is called by the `PostToolUse` hook `index_guard` whenever a `Write` / `Edit` lands inside the
workbench, and it also refreshes before each step starts. The three rules above are injected into the
coordinator's system prompt by `prompt_block()` — it knows from the first turn which scripts already
exist, without spending a tool call to discover them.

**How much it saves**: measured over a 10.4-hour run, **61 scripts were written 95 times and executed
331 times; 92% were executed more than once, and 0 were written but never run**. Qualitatively,
`audit-fake-ai-server.py` was reused by 7 scripts.

This layer works because of one distinction: compaction can clear the context, but it **can't clear
the disk, and it can't clear the index in the system prompt**.

!!! warning "Subagents don't inherit the index"
    The index goes through the session-level `system_prompt.append`; a subagent has its own system
    prompt and **does not inherit it** (measured, $0.2461, `tests/prelude_live.py`). So "where the
    workbench is + write long outputs to `artifacts/`" must be relayed by the coordinator in the task
    brief — that's the only channel, not redundancy.

### Layer three: spill on the spot

`spill_guard` is a `PostToolUse` hook that takes a look at the tool result **before it reaches the
model**: anything over `threshold` (default **4000** characters) is
[spilled](../reference/glossary.md#落盘) to the workbench's `spill/` directory and replaced in context
by one line of pointer plus the **first 400 characters**. Nothing is lost; it just doesn't stay
resident.

**When it fires**: the matcher is `Bash|Read|Grep|Glob|WebFetch|WebSearch`; `main_only=False` by
default, so subagent results spill too. It only replaces over-long **string fields** in the tool
output structure and never touches lists (they may contain image blocks), because `updatedToolOutput`
must preserve the original tool's output structure.

**Reading a spill file itself is let through and not spilled again.** Otherwise the "use Read to get
the full text" line in that pointer is empty talk: you read it back, it's over threshold again, it's
spilled again, and you get another pointer — an infinite loop. We hit it in practice (the first real
run of `tests/handoff_live.py`): the model tried five different ways around it, said itself "The
spill read loops back on itself," and finally ground through it 40 lines at a time, burning seven or
eight turns for nothing. The point of spilling is to **not automatically** stuff large things into
context; if the model decides it wants the full text, that's its choice.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None or 0 = don't install this hook
```

**How much it saves**: in the [HT001](../cases/ht001.md) run, 103 spills replaced 791.4K characters
with path pointers, none of them resident in context.

### Layer four: trim and prune

This layer lives in the [session store](../reference/glossary.md#会话存储). `Runtime`'s store is always
`PruningSessionStore` (inheritance chain `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`), and in `load()` — that is, **before resume** — it rewrites the history that
would be fed back. Not one character of the original in SQLite is touched. Four things:

**① Time-based expiry** (`ephemeral`, on by default). Results of
[ephemeral commands](../reference/glossary.md#一次性命令) like `git status`, `ls`, `cat` have their body
replaced by a note after a few turns, keeping the most recent 6. Expired content is **not spilled** —
archiving an old `git status` is pointless, just run it again:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

Live resume measured `expired: 2`; on a real transcript with `keep_recent` set to 2, 5 entries
expired.

**② [Trim](../reference/glossary.md#裁剪)** (`trim`, **off by default**). tool_result bodies `>= 2000`
characters are spilled to `<workspace>/.flower/spill/` and the block content is replaced by a file
pointer, keeping the last 20 originals. Note this directory is **not the same** as layer three's
`spill_guard` directory: the latter writes under the workbench root, whereas this one must land
inside the workspace, or the agent's `Read` can't reach it.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True works too
```

**③ [Prune](../reference/glossary.md#剪除) denied calls** (`keep_denials`, default 1). The act of
blocking something pollutes the context too: the denial message is a `tool_result`, and it stays
forever together with **the command that was never executed**. Measured once at 273 characters (93
characters of denial text + 180 characters of dead command) — the dead command costs more than the
denial.

More important than tokens is that it **misleads**: measured, after the coordinator read a few "don't
use Bash directly" messages, it stopped even attempting a `git status` that would have been allowed,
and simply said "Bash is restricted, dispatch an agent to look" — learned helplessness, which costs
an extra subagent launch. The default keeps 1 rather than 0: the most recent denial is a valid signal
and stops the model from retrying the same blocked command over and over in the same turn.
Identification relies on the structural marker the harness itself writes,
`toolDenialKind: "permission-rule"`, not on matching wording — wording changes at any time, markers
don't. Live measurement: 2 denials → drop 1, keep 1, chain intact, resume normal, and the model still
knows what happened.

**④ Prune disconnect residue**. Synthetic API error messages produced during network-retry are not
fed back; a `tool_result` left behind by an interruption is replaced by a neutral note
(`[上一轮在此处被中断,该工具结果未产生]`), while the entry itself is kept.

**The red line when removing entries**: a `tool_use` and its `tool_result` must be removed
**together** (missing one gives `Missing Tool Result Block`), other calls in the same assistant
message must not be hit by accident, and the `parentUuid` chain must be reconnected.

`Runtime(trim=False)` (the default) **does not mean nothing is cleaned**: it only turns off large-result
trimming; expiry, denied calls, and disconnect residue are still handled.

### Counter-example: do the quick-glance work yourself

The first three layers all say "delegate it out," but there is a counter-example: commands like
`git status`, `ls`, `cat` produce results of a few dozen characters, while **launching a subagent
alone costs about 4.3k of context** (measured, not amortizable). Paying that price for one `ls` is a
net loss.

So the coordinator gets a restricted Bash back (`coordinator(..., glance=True)`, on by default). The
criterion is not "the command is short" but **whether the result will go stale**, and "allow" and
"expire" are decided by the same function, `is_ephemeral()`:

| | Allowed to run itself | Result will be marked stale |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ delegate | — |

Both sides must be the same table, because either one alone is harmful: **allowed but not trimmed**
means an expired `git status` occupies context forever and misleads decisions as if it were the
current state; **trimmed but not allowed** means the coordinator has to pay 4.3k for one `ls`.
`tests/glance.py` nails this invariant down as an assertion — measured over 46 commands, both sides
agree completely, including 10 adversarial samples.

**Pitfall (hit twice)**: the model doesn't write single commands; it writes
`git status -s && echo "--- LOG ---" && git log --oneline -10`. The first version bluntly rejected
every command containing `&&` / `|` / `2>&1`, and the result was **glance failed completely** —
measured, all three of the coordinator's attempts were blocked, so it went back to dispatching
subagents. Now each segment is split out and checked: it's allowed only if every segment is on the
whitelist, and `git status && rm -rf x` is still blocked (the second half isn't on the list).

### Append, don't replace

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

When `build_options()` compiles an `AgentSpec` into SDK options, `instructions` goes through
[`append`](../reference/glossary.md#叠加) — appended **after** Claude Code's native system prompt, not
replacing it. So all those discipline texts above (`COORDINATOR_RULES`, `WORKER_RULES`, etc.) are
additive: **specialization does not come at the cost of general capability.**

The workbench index goes through the same channel. It is present every turn, but it's part of the
system prompt, takes no conversation history, and compaction can't clear it — the price is the one
above: **it only reaches the coordinator.**

!!! warning "Don't use `disallowed_tools` to keep the coordinator hands-off"
    `disallowed_tools` is **session-level**; it disables the tool for subagents too. The measured
    error text:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    The right approach has two steps: don't grant it in `allowed_tools`, then use a `PreToolUse` hook
    to block only the main thread by `agent_id`. `coordinator()` already does this — it sets
    `delegate_only=True`, and `delegate_guard` blocks the main thread while letting subagents through.

    `allowed_tools` alone isn't enough either: it is an **auto-approve list, not an exclusive
    whitelist**. Measured, the model can call tools that aren't in it — in a $0.1 probe, an agent with
    `allowed_tools=["Read"]` still managed to call Write / Bash. What actually blocks is the hook.

## When not to use it

All four layers save the **working material**. The following problems they don't solve, and some
become harder to see because of them:

1. **The goal was misunderstood — these four layers make it worse.** Once the working material is
   dropped, what remains is exactly the decision built on the wrong premise, and it **looks identical
   to a correct decision**. Long-horizon amplifies this to the worst case: the wrong premise runs for
   hours first, dispatches a dozen subagents, drops a pile of outputs on disk, and only then gets
   exposed. By then, what's expensive isn't tokens — it's that every output was built to the wrong
   requirement. What stops this is [clarify](clarify.md), not any layer on this page.
2. **The main thread still grows monotonically.** The four layers flatten the slope, not the
   direction. Measured: the main thread went from 28.7K to 185.9K over 70 turns, a slope of 2.2K per
   turn, never compacted, using 18.6% of a 1M window — **extrapolating to about 440 turns before
   hitting the wall**. Getting past that wall relies on [handoff](handoff.md).
3. **No fallback once full compaction is off.** When handoff is on, `Runtime` force-sets
   `CompactPolicy(mode="no_summary")` on the spec, which turns auto-compact off (if the spec sets
   `compact` explicitly, that is respected). Hitting the limit is a hard error, so these four layers
   must be used together with handoff — you can't just switch compaction off and call it done.
4. **Layer four only takes effect on resume.** Trim and prune both happen in `load()`; a session that
   keeps running continuously won't shrink because of them. Once the division of labor above is in
   place, this layer is mostly unnecessary anyway — the main thread never holds many tool results to
   begin with.
5. **Delegating quick-glance work is a net loss.** A subagent launch is about 4.3k; see the glance
   section above.
6. **Do the cache math before rearranging context.** Measured, one run took in 299.4M input tokens
   with a **96.1% cache hit rate**; $171 only works because of that. Any optimization that rewrites
   history has to account for this first.
7. **Image and document tool results are not spilled.** `spill_guard` only modifies string fields in
   the output structure and never touches lists.

For complete parameter defaults and signatures see the [Python API](../reference/api.md); for terms
see the [glossary](../reference/glossary.md).
