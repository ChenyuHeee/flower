# Continuity

Run `flower` again in the same directory and it picks up the conversation where it left off — killed process, crashed terminal, rebooted machine, all the same. You don't need to know the word session, and you don't need to remember any id. This page covers what makes it work, when it silently fails, and how to deliberately not continue.

!!! note "Continuity is not handoff"
    [Continuity](../reference/glossary.md#接续) is **across processes**: the next process picks up the previous [run](../reference/glossary.md#运行).
    [Handoff](../reference/glossary.md#换代) is **inside a single run**: context is nearly full, the current [session](../reference/glossary.md#会话)
    writes a [handoff document](../reference/glossary.md#交接书), and a fresh session takes over — see [Handoff](handoff.md).

    The two mesh automatically, no extra wiring: [lineage](../reference/glossary.md#血缘) always records the **last** session
    that took over that step, so the next wake resumes the successor.

## What problem it solves {#解决什么问题}

Everything is already on disk. `runs/sessions.db` holds the **complete** transcript of every historical session, `需求.md` / `目标.md`
are frozen artifacts, and the code is right there in the workspace.

**The only thing lost is one line of mapping** — "which step used which session". It used to live only in the in-memory `ctx["_sessions"]`,
and vanished the moment the process exited. So the new process starts up and the [coordinator](../reference/glossary.md#协调者) is an amnesiac newcomer: who it dispatched,
which dead ends it tried, why it rejected some approach — all of it done over again.

In [HT002](../cases/ht002.md) it spent an hour trying compile flags. Switch processes and that hour is wasted.

## How to use it (minimal code) {#怎么用最小代码}

Nothing to configure on the command line; the `flower` path has continuity on by default:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # 第一次
# …跑完,或者你按 Ctrl-C 走人,或者机器重启了

cd ~/proj && flower "顺便支持代码块高亮"          # 接着上次那段对话
cd ~/proj && flower                              # 什么都不说 = 接着做
cd ~/proj && flower --new "另一件事"              # 这次别接上次
```

When writing your own [workflow](../reference/glossary.md#流程), continuity is also on by default — `Workflow.continuous` defaults to
`True`:

```python
import asyncio

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous 默认 True
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # 第几次唤醒,第一次跑是 1
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

Run this code a second time in the same directory and `ctx["_woke"]` is `2`, while `ctx["_sessions"]["取词"]` is
**the same id** as the first time — the "取词" step resumed the previous session instead of opening a new one.

!!! tip "You just want to know whether this directory can be continued"
    `wake_state()` is a read-only probe that **writes not a single byte**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    It returns `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = the brief exists and all four sections are present;
    `checks` = how many verdict checks there are; `woke` = how many times it has already woken; `steps` = the mapping from step name to session_id.
    The command line uses this to decide whether the prompt should ask "what do you want to do" or "continue from last time".

## What it actually does {#它实际做了什么}

### The three files that land on disk {#落在磁盘上的三个文件}

`run_dir` defaults to `./runs`, **relative to the current working directory, not to the workspace**.

| Path | What it holds |
|---|---|
| `runs/lineage.json` | Lineage: `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Continuity rests entirely on this |
| `runs/sessions.db` | SQLite, full transcripts. Tables are `entries` / `meta` / `summaries`, key is `project_key/session_id[/subpath]` — subagent transcripts are stored separately under subpath |
| `runs/manifest.json` | A JSON array, the run manifest **accumulated across processes**. One row per step; the only place to look up a session_id after the fact |

The lineage file looks like this:

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

Every row of `manifest.json` carries all the fields of `StepResult` — `step`, `session_id`, `ok`, `cost_usd`,
`num_turns`, `text`, `error`, `started_at`, `ended_at`, `attempts`, `errors[]`, `resumed`,
`retired[]`, `context` — plus a manually added `duration_s` (it's a `@property`, so `asdict()` misses it) and
`run` (a process marker, `YYYYmmdd-HHMMSS-<6 位 hex>`).

Step names appear in four shapes there, so you can see at a glance how the step played out: `<步骤名>` (first attempt),
`<步骤名>#retry<N>` (ordinary retry), `<步骤名>#round<N>` (verdict failed, sent back to keep working),
`<步骤名>·判定#<N>` (the [judge](../reference/glossary.md#判定者)'s round).

Writes are **append, not overwrite**: each spill re-reads the file and deduplicates by the `run` field — rows belonging to this process are replaced with the latest,
everyone else's rows are left alone. So running several flowers in parallel in the same directory is safe.

### `continuous=True` changes the meaning of `resume_from` {#continuoustrue-改变了-resume_from-的语义}

This is the easiest thing to miss: `Workflow.continuous` defaults to `True`, so `resume_from=None`
**does not mean "a brand-new session"**.

| Form | Within one run | Across processes (`continuous=True`) |
|---|---|---|
| `resume_from=None` (default) | New session, only the context passed in the prompt | **Resumes the session of the same-named step from lineage** |
| `resume_from="上一步名"` | Resumes the same session, full context | Same as left |
| `resume_from=…, fork=True` | Forks, without polluting the original session | Same as left |

To get a clean new session on every process, write `Workflow(..., continuous=False)` explicitly.

Loading lineage adds one more validation: every `(步骤名, session_id)` read back is first checked with `runtime.has_session(sid)`
to confirm it is still in `sessions.db`, and only used if it is alive. The reason is that the lineage file can outlive `sessions.db`,
and resuming a session that doesn't exist only blows up once the subprocess comes up.

!!! warning "The step name is the key that stays stable across processes"
    Lineage is indexed by `Step.name`. **Renaming a step means severing the lineage** — no error, the next run just becomes a brand-new session.
    Suffixed names (`#retry`, `#round`, `·判定#`) never enter lineage; `Lineage.remember` always uses the original name.

### Two invariants {#两条不变式}

**One: spill the moment a session_id arrives, don't wait for the step to finish.**

A hard-killed process is exactly the scenario being defended against. This bit us in practice: on 2026-09-07 Terminal.app crashed twice, the kernel sent SIGHUP,
and SIGHUP's default action is immediate termination — `finally` doesn't run a single line. Back then lineage was written at **step boundaries**,
so the run that died inside the first step had an empty `steps`, and the human was asked to answer questions they had already answered (see issue #6).

Now `Runtime.on_session` spills the instant the id arrives — in practice the earliest point is the first assistant message,
since the init system message carries no `session_id` in the Python SDK. Writing goes to `.tmp` first, then an atomic replace,
so being killed midway never leaves half a file; a failed spill (`OSError`) is swallowed silently and doesn't take the run down with it.

This hook **covers only the `runtime.run` call**; it is detached with `try/finally` before the gate. The judge uses the same
`Runtime`, and if the hook were still attached its session would be written into the work step's lineage.

**Two: if it doesn't match, act as if it isn't there — don't error.**

Three ways it can fail to match: the workspace path changed (the directory was copied elsewhere — [HT001](../cases/ht001.md) was copied out of a container),
the session is no longer in the store (`sessions.db` was deleted), or the lineage file is corrupt. Any of them silently falls back to "start from scratch".

The `workspace` field is the guard: the SDK's `project_key` is derived from the workspace path (`/`, `_`, `.` all replaced with `-`),
and after the directory is copied elsewhere the old session_id simply can't be found at the new location, so a path mismatch means treating it as absent.

**Continuity is a bonus; its failure must never block a person from working.**

### Killed processes, and machine reboots {#进程被杀和机器重启}

Both end the same way — both continue — but the paths differ:

| Situation | What happens | Next run |
|---|---|---|
| `Ctrl-C` once | Cooperative interrupt, clean break at a **message boundary**. You can add a remark and resume the same session in the same process. An interrupt doesn't count as a failed attempt and doesn't consume retry budget | Continuity not involved |
| `Ctrl-C` twice | Raises `KeyboardInterrupt` and exits. Cleanup only gets as far as closing the store, and **the in-flight step does not enter `manifest.json`** | Lineage was spilled long ago, so it continues |
| `SIGTERM` / `SIGHUP` | The handler calls `rescue()` first, writing the in-flight step into `manifest.json` too (marked `error="killed-by-signal"`), then restores the default action and really leaves | Same as above, it continues |
| `SIGKILL`, power loss, reboot | No cleanup at all | It continues just the same — all three files are on disk, and lineage was written the instant the id arrived |

There is exactly one precondition: **the same `workspace` plus the same `run_dir`**. `run_dir` is relative to the current working directory,
so typing `flower` from another directory looks for a different `runs/` and won't continue.

### The judge is always a new session {#判定者永远是新会话}

This one is **guaranteed by construction**, not by remembering.

The judge is not a `Step` — it is dispatched directly by `rt.run()` inside `with_goal`'s gate
(see [Goal guard](goal.md)) and never goes through the lineage path. So every round and every wake gives it a fresh pair of eyes.

That is its entire value: **it doesn't know how many times the worker tried or how hard it was, so it won't make excuses for it.**
Let it follow continuity and the goal guard degenerates into self-audit.

Section 4 of `tests/lineage_offline.py` nails this down.

### The sentence you say at wake must land in three places {#唤醒时说的那句话要落到三个地方}

`flower "顺便支持代码块高亮"` in an already-used directory is **not a new task, it's another remark**.
It does three things at once — miss one and it silently fails:

| Where it lands | What happens if it's missing |
|---|---|
| Appended to `需求.md` (`## 唤醒时追加`) | It doesn't survive the step boundary. The next step is a new session that only reads the frozen artifact |
| Used as the prompt of the work step | The coordinator never receives it |
| **Triggers re-derivation of `目标.md`** | The judge still reads the old checklist, and **whether the newly added thing got done never enters the verdict** |

The third is the easiest to miss. The judge only reads the frozen `目标.md`; anything you add midway is invisible to it — without re-derivation it will rule "achieved" against the old checklist while the thing you actually wanted was never verified. The cost is one extra goal-setting run per append ([HT002](../cases/ht002.md) measured
$0.41 / 3 minutes).

**Waking without saying anything** (just pressing Enter) appends nothing, re-derives nothing, and costs not a cent extra.

### Crashing inside the first step (clarify) still continues {#崩在第一步确认需求之内也能接上}

`clarify_step` carries a `resume_prompt` (the constant `CLARIFY_RESUME`): if it crashed mid-clarification and you start again,
what the [clarifier](../reference/glossary.md#确认者) is told is "continue the clarification we didn't finish —
not start over", rather than resending the original request as a new task. Combined with "spill the moment a session_id arrives" above,
a run that died in the first step with `需求.md` not yet frozen now continues too, with no re-answering.

Conversely, already-frozen preceding steps are **skipped entirely**: if `需求.md` has all four sections, clarify is skipped (its content is still poured into ctx);
if `目标.md` is complete, goal-setting is skipped.

### What's sent on continuation isn't the same sentence {#接续时发的不是同一句话}

`Step.resume_prompt` governs this. The other side **already has** the brief, the goal, and where it got to last time in its context; resending
"do it per this brief: <the whole brief>" verbatim is pure noise, and worse, it reads as "the requirements changed, look again".

Without a `resume_prompt` the `prompt` is reused — some steps genuinely should resend the full text (when goal-setting re-derives the checklist,
the complete brief is exactly what it needs).

### One line reported at wake {#唤醒时先报一行}

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Without it, "does it actually remember" is completely imperceptible — and that is the entire value of this layer. In the banner,
`需求已确认` is always present, `目标 N 条` only when the verdict checklist is non-empty, and `干活上下文 X` requires that the last round's context size for that session can be looked up in `sessions.db`.

**That context number is deliberately on display** — the reason is in the "Cost" section below.

### Resilience: wait it out when the network drops, and keep errors out of the resumed context {#韧性断网时挂着等而且错误不进接续后的上下文}

[Resilience](../reference/glossary.md#韧性) and continuity go together: a run lasting hours will inevitably lose the network once, and the default behaviour is bad —
at the moment of disconnection the harness stuffs a **synthetic assistant message** into the transcript (`isApiErrorMessage=true`,
`model="<synthetic>"`) whose body is "API Error: Can't reach the API server …". That message becomes the leaf of the session,
and any later resume feeds it back as "what the model said last", so the model thinks it is discussing a network fault.

`Resilience` does three things:

**One: the probe does DNS + TCP only.** `reachable(host, port, timeout=5.0)` runs just `getaddrinfo` plus one TCP handshake —
**no HTTP, no credentials, no cost** — and any exception counts as unreachable. Which address to probe is decided by `endpoint()`, which follows
`ANTHROPIC_BASE_URL`, defaulting to `https://api.anthropic.com` with port `443` (`80` for http).
**With a self-hosted gateway you must probe the gateway** — `api.anthropic.com` being reachable says nothing about the gateway.

**Two: separate what to wait out from what to stop on.** `classify(text)` returns `"transient"` / `"fatal"` / `"unknown"`,
and **checks fatal before transient** — text for things like 401 often contains the word "connection", and reversing the order means waiting forever.
Defaults: `max_attempts=6` (including the first), `base_delay=4.0`, `max_delay=120.0`, `probe_timeout=5.0`,
`probe_interval=15.0`, `max_offline_wait=3600.0` (1 hour), `retry_unknown=True`.
Backoff is `min(base_delay * 2**(attempt-1), max_delay)` times ±25% jitter.

Once a session_id has been obtained it **resumes rather than restarts**, so the spend so far isn't wasted. On resume it sends
`Resilience.resume_prompt`: "上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,
从中断处接着做,不要重头来过。" It **deliberately contains no error detail** — the model needs to know "you were interrupted, keep going",
not whether it was ENOTFOUND or 503.

**Three: the errors produced by a retry storm never enter the post-resume context.** That is the job of [pruning](../reference/glossary.md#剪除).
`Runtime`'s session store is hard-wired to `PruningSessionStore`, which does three things on `load()`:

- Drops synthetic API error messages. **They stay in SQLite as-is**, they're just not fed back
- Drops older denied calls, keeping only the most recent `keep_denials=1`
- Replaces leftover interrupted `tool_result`s with the neutral note "[上一轮在此处被中断,该工具结果未产生]" — replacing the body only, not dropping the entry

Keeping 1 instead of 0 has a reason: a denied call was never executed, so its result carries no information, yet it takes up real space
(one measured case was 273 characters = 93 characters of refusal text + 180 characters of **the original blocked command**), and **it misleads** —
in practice, after reading a few "don't use Bash directly" entries the coordinator stopped even attempting a permitted `git status`, having learned helplessness.
But keeping the most recent one is useful: it prevents the model from retrying the same blocked command over and over within a round.

Dropping has one structural red line: the transcript is a `parentUuid` single chain, so dropping an entry means reattaching its children to the nearest surviving ancestor,
otherwise the chain breaks there and all preceding history is lost.

[HT001](../cases/ht001.md) hit this once in practice: the disconnection timeline was 01:52:40 → 01:55:41, and that step in `manifest.json` shows
`attempts=2` / `resumed=True` / `ok=True`; after resuming it ran another 8-plus hours to completion.

One last easy misreading: **`Runtime(trim=False)` does not mean "nothing gets cleaned"**. `trim` defaults to `False`,
but it only turns off the **large-tool-result [trimming](../reference/glossary.md#裁剪)** layer. Dropping disconnection residue, dropping denied calls,
neutralizing interruption leftovers, marking [ephemeral command](../reference/glossary.md#一次性命令) results as stale — those four still happen
(`ephemeral` defaults to `True`, `keep_denials` defaults to `1`).

### Cost: context grows forever, with no end in sight {#代价上下文会一直涨而且没有尽头}

This is an inherent cost of continuity, not a bug.

The "work" step of [HT001](../cases/ht001.md) ran 10.44 hours straight, and [main thread](../reference/glossary.md#主线程) context was
**28.7K** at round 1, **35.2K** at round 20, **108.6K** at round 35, **158.2K** at round 50, **185.9K** at round 70 —
monotonically rising, slope about **2.2K/round**; never compacted, using **18.6%** of the 1M window. Extrapolating at that slope,
the wall arrives at roughly **440 rounds** — the ceiling of "long-horizon" in its current shape is about **6 times** that run. Permanent continuity means hitting the window someday.

Two mechanisms manage it:

1. **Trimming** (`flower --no-trim` disables it; the `flower` path has it on by default) — on resume, old large tool results are replaced with
   file pointers; the content isn't lost, it just doesn't stay resident
2. **[Handoff](handoff.md)** — at the threshold, write a handoff and switch to a new session. **This is not [compaction](../reference/glossary.md#压缩)**:
   the document is readable and editable, so you can see what was dropped. Context therefore falls back periodically instead of climbing straight into the wall

**Which is why the wake line must report the context number**: only if a person can see it do they get the chance to decide to restart before hitting the wall.

While we're here: `--rounds` (total work rounds) **resets on every wake**. That's intentional — a new wake is a new intent,
and it shouldn't inherit the rounds consumed last time.

### Starting a new thing {#重开一件事}

```bash
flower --new "另一件事"
```

Or type `/new` straight into the wake prompt:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> /new
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> …
```

**Archive, don't delete.** `lineage.json`, `需求.md`, and `目标.md` are **moved together** into `notes/archive/<YYYYmmdd-HHMMSS>/`,
and lineage's `steps` and `woke` are zeroed at the same time. The three are three faces of the same stretch of history; collecting only part of them leaves a half-state like "the goal is still there but the conversation is gone".

`sessions.db` is untouched — it's the archive, and every transcript in it remains queryable.

In code this corresponds to `Lineage.archive(into, extra=[...])`.

## When not to use it {#什么时候不该用它}

- **Scenarios that require a clean start every time.** Batch-running the same workflow, doing controlled evaluations, reproducing a bug for someone else —
  none of these should carry last time's context. Write `Workflow(..., continuous=False)`, or use a different `run_dir` each time.
- **The directory will be moved or copied, or `run_dir` isn't durable.** Running inside a container with `runs/` on the container's inner filesystem,
  or rsyncing the workspace to another machine — continuity **silently fails** (the path guard rejects mismatched lineage);
  don't treat it as a guarantee.
- **This is a new intent and the context is already large.** Continuity drags all the irrelevant history along, and you pay tokens for it every round.
  Rather than putting up with it, `--new` to archive and start over.
- **One-shot single agent.** `flower once` doesn't go through `Workflow` and has no lineage; to resume you must pass `--resume <session_id>` yourself.
- **Using continuity as a backup.** It only records "which step used which session". Code, outputs, and decisions belong in the workspace and the
  [workbench](../reference/glossary.md#工作台), not something to dig back out of a transcript.

## What to read next {#相关}

- [Handoff](handoff.md) — what to do when context fills up inside a single run; the other direction of the same thing as this page
- [Goal guard](goal.md) — why the judge doesn't continue
- [Context economics](context.md) — what trimming, pruning, and spilling each handle
- [Python API](../reference/api.md) — `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Command line](../reference/cli.md) — `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Source: [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
