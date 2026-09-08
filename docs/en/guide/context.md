# Context economics

The context of the [main thread](../reference/glossary.md#主线程) is the only thing that runs
end to end through a [long-horizon](../reference/glossary.md#长程) run; what it holds and what it
does not decides how far that run gets. The shape of flower — a
[coordinator](../reference/glossary.md#协调者) that never does the work itself, long outputs
spilled to disk, hooks pruning on the spot — all follows from that one fact. This page is the why.

## What problem it solves {#解决什么问题}

[Compaction](../reference/glossary.md#压缩) waits until the context is full and then summarizes in
hindsight; it treats the symptom. The real problem is:
**trivia should never have entered the main thread in the first place.**

The difference is timing. One `pytest` run easily emits tens of thousands of characters; the model
glances at it, takes one conclusion, and the remaining characters are re-sent on every subsequent
turn. Once the window fills, compaction summarizes them together with the decisions sitting next to
them into a single paragraph — what is saved is volume, what is lost is "why we decided this in the
first place." The auto-compact trigger threshold is **window − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)); by that
moment, what should be dropped and what should not are already lying side by side.

flower solves it in four layers; the order is the priority — ranked by how much each saves:

| Layer | What it does | Where |
|---|---|---|
| 1. Division of labor | Hands-on work goes to a [subagent](../reference/glossary.md#subagent); trial and error goes into its own transcript | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 2. Workbench | Scripts / long outputs / decisions spill to disk; the index is injected into the system prompt | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 3. Spill on the spot | A `PostToolUse` hook spills over-threshold tool results to disk, leaving a single path line in context | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 4. Trim and prune | Rewrite the session before resume: stale results, denied calls and disconnect debris are not fed back | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py), [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

The first two layers govern **whether things get in**; the last two govern **whether what got in
stays**. The order cannot be reversed: however aggressive layer four is, it cannot claw back the
volume layer one let through.

## How to use it (minimal code) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model defaults to "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

These few lines install the first three layers: `coordinator()` always sets `delegate_only=True`
(layer one); `workbench=True` creates the [workbench](../reference/glossary.md#工作台) and injects
the index into the coordinator's system prompt (layer two), and at the same time makes `Runtime`
install `spill_guard` (layer three). Layer four is on by default — `Runtime`'s
[session store](../reference/glossary.md#会话存储) is hard-wired to `PruningSessionStore`, and the
constructor exposes no way to swap it.

!!! warning "`workbench=True` is not optional"
    `delegate_guard`, the hook that stops the coordinator from doing the work itself, lives in
    `workbench_hooks`, and `workbench_hooks` is only installed when `Runtime` has a workbench;
    `whitelist_guard` is meanwhile skipped because of `delegate_only=True`.
    Conclusion: **with `Runtime(workbench=False)` plus `coordinator()`, there is not a single wall
    in front of Bash / Write / Edit on the main thread.**

## What it actually does {#它实际做了什么}

### Layer one: division of labor (saves the most) {#第一层分工省得最多}

The coordinator plays "a person who knows how to use Claude Code": decompose, delegate, read
reports, decide. It does not get Bash / Write / Edit — its tools are only `Agent`, `TodoWrite`,
`Read` (plus one restricted `Bash` when `glance=True`, see below). All hands-on work is delegated to
a [worker](../reference/glossary.md#执行者).

**When it fires**: every time the main thread calls `Bash|Write|Edit|NotebookEdit`, the
`PreToolUse` hook `delegate_guard` denies it on the spot and points the way — "use the Agent tool to
dispatch a subagent, state the goal and acceptance criteria in the task, and require it to write
long outputs into `.flower/artifacts/` and reply with only paths and conclusions." Subagents are
always let through. The test is whether the hook payload carries an `agent_id`: **no `agent_id`
means the main thread**.

**How much it saves**: a subagent's tool calls and trial and error **go into its own transcript**
(distinguished in the session store by `subpath`); the main thread keeps only that one `Agent` call
and the final report. The trial-and-error process is not compacted away — it **never entered the
main thread at all**.

- Measured (a task that produces a lot of tool output): 83% of the transcript landed in the
  subagent; main thread 13 entries, 21K characters; subagent 105K characters.
- Measured (real scale, a 10.4-hour run, see [HT001](../cases/ht001.md)): subagents carried
  **97.7%** of turns and **94.8%** of body characters; 1,893 hands-on tool calls vs 32 on the main
  thread (**59:1**). Early compaction is no longer the main story.

The two bullets are two different measurements: the first is an earlier small-scale test, the second
a re-measurement at real scale. Same mechanism; the bigger the scale, the more it saves.

What is saved is context, not model tier: `worker()` defaults to `model="inherit"` — workers should
not be downgraded.

The only reverse cost of division of labor is the [task brief](../reference/glossary.md#任务书) —
the block of text the coordinator writes when delegating. It enters the main thread and stays there
forever. Measured: 8/8 task briefs restated discipline the other side already knew; in the shortest
one, only about 120 characters out of 521 were task-specific, wasting about 4.8k of permanent
context per turn. So `COORDINATOR_RULES` hard-codes one line: **a task brief states only what is
specific to this task**. The one rule still worth spelling out is "where the workbench is + write
long outputs to `artifacts/` + reply with only paths and conclusions" — because the workbench index
cannot reach subagents, and the task brief is the only channel.

### Layer two: the workbench (cures "rewriting every time") {#第二层工作台治每次重写}

Three directories under `.flower/` travel with the workspace:

| Directory | What goes in | What it solves |
|---|---|---|
| `scripts/` | Verification / reproduction scripts that will run a second time, first line `# desc: 一句话` | Write once, then just run it. No more "lost after compaction, rewritten every time" |
| `artifacts/` | Long outputs over 2000 characters: logs, data, reports, diffs | Only the path and the conclusion appear in the conversation |
| `notes/` | Key decisions and their reasons, one file per decision | After compaction, after a restart, on another machine, the conclusions are still there |

**When it fires**: `INDEX.md` is generated automatically (at most 40 entries by default);
`refresh()` is called by the `PostToolUse` hook `index_guard` when a `Write` / `Edit` lands inside
the workbench, and it is also refreshed once before each step starts. The three rules above are
injected into the coordinator's system prompt by `prompt_block()` — so it knows from turn one which
scripts already exist, without spending a tool call to discover them.

**How much it saves**: measured on a 10.4-hour run, **61 scripts were written 95 times and executed
331 times; 92% were executed more than once, and 0 were written but never run**. Qualitatively,
`audit-fake-ai-server.py` was reused by 7 scripts.

This layer works because of one difference: compaction can clear the context, but it **cannot clear
the disk, and it cannot clear the index inside the system prompt**.

!!! warning "Subagents do not inherit the index"
    The index goes through the session-level `system_prompt.append`; a subagent has its own system
    prompt and **does not inherit it** (measured, $0.2461, `tests/prelude_live.py`). So "where the
    workbench is + write long outputs to `artifacts/`" must be restated by the coordinator in the
    task brief — that is the only channel, not redundancy.

### Layer three: spill on the spot {#第三层当场落盘}

`spill_guard` is a `PostToolUse` hook that takes a look at tool results **before they reach the
model**: anything over `threshold` (default **4000** characters) is
[spilled](../reference/glossary.md#落盘) to the workbench's `spill/` directory and replaced in
context by a one-line pointer plus the **first 400 characters**. Nothing is lost; it just no longer
lives in context.

**When it fires**: the matcher is `Bash|Read|Grep|Glob|WebFetch|WebSearch`; `main_only=False` by
default, so subagent results are spilled too. It only replaces over-long **string fields** in the
tool output structure and never touches lists (they may contain image blocks), because
`updatedToolOutput` must preserve the original tool's output structure.

**Reading a spill file is itself let through and never spilled again.** Otherwise the "use Read to
get the full text" in that pointer line would be empty words: read it back, exceed the threshold
again, get spilled again, get another pointer line — an infinite loop. We hit this for real
(`tests/handoff_live.py`, first live run): the model tried five different phrasings to work around
it, said "The spill read loops back on itself" itself, and finally ground through it 40 lines at a
time, burning seven or eight turns for nothing. The point of spilling is "do **not automatically**
stuff big things into context"; if it decides it wants the full text, that is its choice.

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None or 0 = do not install this hook
```

**How much it saves**: in the [HT001](../cases/ht001.md) run, 103 spills turned 791.4K characters
into path pointers, with no residency in context.

### Layer four: trim and prune {#第四层裁剪与剪除}

This layer lives in the [session store](../reference/glossary.md#会话存储). `Runtime`'s store is
always `PruningSessionStore` (inheritance chain `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`), and in `load()` — that is, **before resume** — it rewrites the history that
is about to be fed back. Not one character of the original in SQLite is touched. Four things:

**① Staleness expiry** (`ephemeral`, on by default). Results of
[ephemeral commands](../reference/glossary.md#一次性命令) like `git status`, `ls`, `cat` have their
body replaced by a note after a few turns, keeping the most recent 6. Expired content is **not
spilled** — archiving an old `git status` is pointless, one rerun gets you a fresh one:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

A live resume measured `expired: 2`; on a real transcript with `keep_recent` set to 2, 5 entries
expired.

**② [Trim](../reference/glossary.md#裁剪)** (`trim`, **off by default**). tool_result bodies of
`>= 2000` characters are spilled to `<workspace>/.flower/spill/`, the block content is replaced by a
file pointer, and the most recent 20 bodies are kept verbatim. Note this directory is **not the
same** as layer three's `spill_guard` directory: the latter writes under the workbench root, while
this one must land inside the workspace, otherwise the agent's `Read` cannot reach it.

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True works too
```

**③ [Prune](../reference/glossary.md#剪除) denied calls** (`keep_denials`, default 1). The act of
blocking itself pollutes context: the denial message is a `tool_result`, and it stays forever
together with the command **that was never executed**. Measured at 273 characters once (93
characters of denial text + 180 characters of dead command) — the dead command costs more than the
denial.

More important than the tokens is that it **misleads**: measured, after reading a few "do not use
Bash directly" messages, the coordinator stopped even attempting an allowed `git status` and just
said "Bash is restricted, send an agent to look" — learned helplessness, which then cost an extra
subagent startup. The default keeps 1 rather than 0: the most recent denial is a useful signal that
stops the model from retrying the same blocked command over and over within one turn. Detection
relies on the structural marker the harness itself writes, `toolDenialKind: "permission-rule"`, not
on matching the wording — wording changes at any time, the marker does not. Measured live: 2
denials → prune 1, keep 1; the chain stayed intact, resume worked, and the model still knew what had
happened.

**④ Prune disconnect debris**. Synthetic API error messages produced during network-retry are not
fed back; a `tool_result` left behind by an interruption is replaced with a neutral note
(`[上一轮在此处被中断,该工具结果未产生]`), while the entry itself is kept.

**The red line when removing**: a `tool_use` and its `tool_result` must be removed **together**
(missing one gives `Missing Tool Result Block`), other calls in the same assistant message must not
be hit by accident, and the `parentUuid` chain must be re-linked.

`Runtime(trim=False)` (the default) **does not mean nothing is cleaned**: it only turns off
large-result trimming; expiry, denied calls, and disconnect debris are still handled.

### Counterexample: do the glance work yourself {#反例看一眼的活自己干}

The first three layers all say "delegate it," but there is a counterexample: commands like
`git status`, `ls`, `cat` produce results of a few dozen characters, while **dispatching a subagent
costs about 4.3k of context just to start** (measured, cannot be amortized). Paying that price for
one `ls` is a net loss.

So the coordinator gets a restricted Bash back (`coordinator(..., glance=True)`, on by default). The
test is not "the command is short" but **whether the result goes stale**, and "let through" and
"goes stale" are decided by the same function, `is_ephemeral()`:

| | Let through to run itself | Result gets marked stale |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ delegate | — |

Both sides must be the same table, because either side holding alone is harmful: **let through but
not trimmed**, and a stale `git status` occupies context forever and misleads decisions as if it
were the current state; **trimmed but not let through**, and the coordinator pays 4.3k for one `ls`.
`tests/glance.py` nails this invariant down as an assertion — measured across 46 commands, the two
sides agreed completely, including 10 adversarial samples.

**Pitfall (hit twice)**: the model does not write single commands, it writes
`git status -s && echo "--- LOG ---" && git log --oneline -10`. The first version bluntly rejected
every command containing `&&` / `|` / `2>&1`, and **glance stopped working entirely** — measured, all
three coordinator attempts were blocked and it went back to dispatching subagents. Now each segment
is split and checked separately: only if every segment is on the whitelist is it let through, and
`git status && rm -rf x` is still blocked (the second half is not on the table).

### Append, don't replace {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

When `build_options()` compiles an `AgentSpec` into SDK options, `instructions` goes through
[`append`](../reference/glossary.md#叠加) — appended **after** Claude Code's native system prompt,
not replacing it. So the discipline text above (`COORDINATOR_RULES`, `WORKER_RULES`, etc.) is
additive: **specialization does not cost general capability.**

The workbench index goes through the same channel. It is present on every turn, but it is part of
the system prompt, so it does not occupy conversation history and compaction cannot clear it — the
cost is the one stated above: **it reaches the coordinator only**.

!!! warning "Do not use `disallowed_tools` to keep the coordinator hands-off"
    `disallowed_tools` is **session-scoped** and disables the tool for subagents too. The measured
    error text:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    The correct approach has two steps: leave it out of `allowed_tools`, then use a `PreToolUse`
    hook to block only the main thread, keyed on `agent_id`. `coordinator()` already does this — it
    sets `delegate_only=True`, and `delegate_guard` blocks the main thread while letting subagents
    through.

    `allowed_tools` alone is not enough either: it is an **auto-approval list, not an exclusive
    whitelist**. Measured, the model can call tools that are not on it — in a $0.1 probe, an agent
    with `allowed_tools=["Read"]` could still call Write / Bash. What actually blocks is the hook.

    **`allowed_tools` is session-scoped as well — the same lesson, learned twice.** A tool not on
    this list still goes through permission approval when a **subagent** calls it. Unattended, no
    one approves, so it neither errors out nor stops: the model retries the same call over and over
    (`toolDenialKind=user-rejected`). Measured: `WebFetch`/`WebSearch` were added to a worker but
    written only into `AgentDefinition.tools`; that run produced twenty-odd user-rejected events and
    not a single character of output (`roles.py:513-518`). The symptom is harder to diagnose than
    `disallowed_tools` — the latter errors on the spot, the former looks like nothing wrong on
    screen. So `coordinator()` now merges its workers' read-only web tools into its own
    `allowed_tools` (`roles.py:523-526`), while `Write`/`Edit`/`Bash` are **deliberately not
    merged** — merging them would be the same as dismantling the hook above.

## When not to use it {#什么时候不该用它}

All four layers save **raw detail**. They do not solve the problems below, and some of those become
harder to see because of them:

1. **The goal was misunderstood — these four layers make it worse.** Once the raw detail is
   discarded, what remains is precisely the decision built on the wrong premise, and it **looks
   exactly like a correct decision**. Long-horizon amplifies it to the worst case: the wrong premise
   runs for hours first, dispatches a dozen subagents, drops a pile of outputs on disk, and only
   then gets exposed. By then the expensive part is not the tokens; it is that every output was
   built to the wrong requirement. What blocks this is [clarify](clarify.md), not any layer on this
   page.
2. **The main thread still grows monotonically.** The four layers flatten the slope, not the
   direction. Measured: over 70 turns the main thread grew from 28.7K to 185.9K, a slope of
   2.2K/turn, never compacted, consuming 18.6% of a 1M window, **extrapolating to hitting the wall
   at about 440 turns**. Crossing that wall relies on [handoff](handoff.md).
3. **There is no fallback once full compaction is off.** With handoff enabled, `Runtime` forces
   `CompactPolicy(mode="no_summary")` onto the spec, which turns auto-compact off (it is respected
   only if the spec explicitly supplies `compact`). Hitting the limit is a hard error, so these four
   layers must be used together with handoff — you cannot just switch compaction off and call it
   done.
4. **Layer four only takes effect on resume.** Trim and prune both happen in `load()`; a session
   that keeps running continuously will not shrink because of them. Once the division of labor above
   is in place, this layer is mostly unnecessary anyway — the main thread never holds many tool
   results to begin with.
5. **Delegating glance work is a net loss.** A subagent costs about 4.3k to start; see the glance
   section above.
6. **Do the cache math before rearranging context.** Measured, one run took 299.4M input tokens with
   **96.1% cache hits**; $171 only works because of that. Any optimization that rewrites history
   must account for this first.
7. **Image and document tool results are not spilled.** `spill_guard` only modifies string fields in
   the output structure and never touches lists.

For the full defaults and signatures of the parameters see the [Python API](../reference/api.md);
for terminology see the [glossary](../reference/glossary.md).
