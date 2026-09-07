# Continuity

Run `flower` a second time in the same directory and it picks up the conversation where it left off — process killed, terminal crashed, machine rebooted, all the same. You don't need to know the word session, and you don't need to remember any id. This page covers what makes that work, when it silently fails, and how to deliberately not continue.

!!! note "Continuity is not handoff"
    [Continuity](../reference/glossary.md#接续) is **across processes**: the next process picks up the previous [run](../reference/glossary.md#运行).
    [Handoff](../reference/glossary.md#换代) happens **inside a single run**: context is nearly full, the current [session](../reference/glossary.md#会话)
    writes a [handoff document](../reference/glossary.md#交接书), and a fresh session takes over — see [Handoff](handoff.md).

    The two mesh automatically, no extra wiring needed: [lineage](../reference/glossary.md#血缘) always records the **last**
    session that took over that step, so the next wake resumes the successor.

## What it solves

Everything is already on disk. `runs/sessions.db` holds the **complete** transcript of every historical session, `需求.md` / `目标.md`
are frozen artifacts, and the code is right there in the workspace.

**The only thing lost is one line of mapping** — "which step used which session". It used to live only in the in-memory `ctx["_sessions"]`,
and vanished the moment the process exited. So the new process starts up and the [coordinator](../reference/glossary.md#协调者) is an amnesiac newcomer: who it dispatched,
which dead ends it already tried, why it rejected some approach — all of it done over again.

In [HT002](../cases/ht002.md) it spent an hour going around in circles on compiler flags. Change process, and that hour is thrown away.

## How to use it (minimal code)

Nothing to configure on the command line; the `flower` path has continuity on by default:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # first time
# …it finishes, or you Ctrl-C and walk away, or the machine reboots

cd ~/proj && flower "顺便支持代码块高亮"          # picks up that conversation
cd ~/proj && flower                              # say nothing = keep going
cd ~/proj && flower --new "另一件事"              # don't continue this time
```

When you write your own [workflow](../reference/glossary.md#流程), continuity is on by default too — `Workflow.continuous` defaults to
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
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous defaults to True
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # which wake this is; 1 on the first run
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

Run this same code a second time in the same directory and `ctx["_woke"]` is `2`, while `ctx["_sessions"]["取词"]`
**is the same id** as the first time — the "取词" step resumed the previous session instead of starting a new one.

!!! tip "Just want to know whether this directory can continue"
    `wake_state()` is a read-only probe that **writes not a single byte**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    It returns `{"waking", "brief", "goal", "checks", "woke", "steps"}`. `waking` = the brief exists and all four sections are present;
    `checks` = how many items in the verdict checklist; `woke` = how many wakes have happened; `steps` = the mapping from step name to session_id.
    The command line uses exactly this to decide whether the prompt should ask "what do you want to do" or "keep going".

## What it actually does

### The three files it puts on disk

`run_dir` defaults to `./runs`, **relative to the current working directory, not to the workspace**.

| Path | What's in it |
|---|---|
| `runs/lineage.json` | Lineage: `{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`. Continuity rests entirely on this |
| `runs/sessions.db` | SQLite, full transcripts. Tables are `entries` / `meta` / `summaries`, keyed by `project_key/session_id[/subpath]` — subagent transcripts are stored separately under subpath |
| `runs/manifest.json` | A JSON array, the run manifest **accumulated across processes**. One row per step; the only place to look up a session_id after the fact |

The lineage file looks like this:

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

Each row of `manifest.json` is every field of `StepResult` — `step`, `session_id`, `ok`, `cost_usd`,
`num_turns`, `text`, `error`, `started_at`, `ended_at`, `attempts`, `errors[]`, `resumed`,
`retired[]`, `context` — plus two hand-added fields: `duration_s` (it's a `@property`, so `asdict()` misses it) and
`run` (a process marker, `YYYYmmdd-HHMMSS-<6 hex digits>`).

Step names appear in four shapes there, so you can see at a glance how the step played out: `<步骤名>` (first attempt),
`<步骤名>#retry<N>` (ordinary retry), `<步骤名>#round<N>` (verdict failed, sent back to keep working),
`<步骤名>·判定#<N>` (the [judge](../reference/glossary.md#判定者) round).

Writes **append rather than overwrite**: every write re-reads the file first and dedupes on the `run` field — rows belonging to this process are replaced with the latest,
everyone else's rows are left untouched. So running several flowers in parallel in the same directory is safe.

### `continuous=True` changes the meaning of `resume_from`

This is the easiest thing to miss: `Workflow.continuous` defaults to `True`, so `resume_from=None`
**does not mean "brand-new session"**.

| Form | Within one run | Across processes (`continuous=True`) |
|---|---|---|
| `resume_from=None` (default) | New session, only the context passed in the prompt | **Resumes the session recorded in lineage for the step with the same name** |
| `resume_from="上一步名"` | Resumes the same session, full context | Same as left |
| `resume_from=…, fork=True` | Forks, doesn't pollute the original session | Same as left |

If you want every process to start a clean new session, write `Workflow(..., continuous=False)` explicitly.

There's one more check when lineage is loaded: every `(step name, session_id)` read back is first verified with `runtime.has_session(sid)`
to confirm it's still in `sessions.db`, and only used if it's alive. The reason is that the lineage file can outlive `sessions.db`,
and resuming a session that doesn't exist only blows up once the subprocess comes up.

!!! warning "The step name is the key that's stable across processes"
    Lineage is indexed by `Step.name`. **Renaming a step severs the lineage** — no error, the next run is simply a brand-new session.
    Suffixed names (`#retry`, `#round`, `·判定#`) never enter lineage; `Lineage.remember` always uses the original name.

### Two invariants

**One: write to disk the moment you get a session_id, don't wait for the step to finish.**

A hard-killed process is exactly the scenario this defends against. It has burned us for real: on 2026-09-07 Terminal.app crashed twice, the kernel sent SIGHUP,
and the default action for SIGHUP is immediate termination — not a line of `finally` runs. Back then lineage was written at **step boundaries**,
so a run that died inside the first step had an empty `steps`, and the human was asked to answer questions they had already answered (see issue #6).

Now `Runtime.on_session` writes to disk the instant it has the id — in practice the earliest point is the first assistant message,
since the init system message carries no `session_id` in the Python SDK. Writing goes to `.tmp` first and then atomically replaces, so being killed halfway
never leaves half a file; a write failure (`OSError`) is swallowed silently and doesn't take the run down with it.

This hook **covers only the `runtime.run` call**; it's detached with `try/finally` before the gate. The judge uses the same
`Runtime`, and if the hook were still attached its session would be written into the lineage of the work step.

**Two: if it doesn't match, treat it as absent — don't error.**

Three ways it fails to match: the workspace path changed (the directory was copied elsewhere — [HT001](../cases/ht001.md) was copied out of a container),
the session is no longer in the store (`sessions.db` was deleted), or the lineage file is corrupt. Any of them silently falls back to "start from scratch".

That `workspace` field is the guard: the SDK's `project_key` is derived from the workspace path (`/`, `_`, `.` all become `-`),
and after a directory is copied elsewhere the old session_id simply isn't findable at the new location, so a mismatched path is treated as absent.

**Continuity is a bonus; its failure must never stop someone from working.**

### Process killed, versus machine rebooted

The outcome is the same for both — it continues — but the path differs:

| Situation | What happens | Next run |
|---|---|---|
| `Ctrl-C` once | Cooperative interrupt, clean break at a **message boundary**. You can add a remark and resume the same session in the same process. An interrupt doesn't count as a failed attempt and doesn't eat retry budget | Continuity not involved |
| `Ctrl-C` twice | Raises `KeyboardInterrupt` and exits. Cleanup gets as far as closing the store; **the in-flight step doesn't make it into `manifest.json`** | Lineage was written long ago, it continues |
| `SIGTERM` / `SIGHUP` | The handler calls `rescue()` first, writing the in-flight step into `manifest.json` too (marked `error="killed-by-signal"`), then restores the default action and really leaves | Same as above, it continues |
| `SIGKILL`, power loss, reboot | No cleanup at all | It still continues — all three files are on disk, and lineage was written the moment the id arrived |

One precondition only: **the same `workspace` plus the same `run_dir`**. `run_dir` is relative to the current working directory,
so typing `flower` from a different directory looks for a different `runs/` and won't continue.

### The judge is always a new session

This is **guaranteed by construction**, not by remembering.

The judge is not a `Step` — it's dispatched directly by `rt.run()` inside the `with_goal` gate
(see [Goal guard](goal.md)), and never goes through the lineage path. So every round, every wake, it's a fresh pair of eyes.

That is its entire value: **it doesn't know how many times the worker tried or how hard it worked, so it won't make excuses on its behalf.**
Let it follow continuity and the goal guard degrades into self-audit.

Section 4 of `tests/lineage_offline.py` nails this down.

### What you say at wake time has to land in three places

`flower "顺便支持代码块高亮"` in a directory you've used before is **not a new task, it's one more remark**.
It does three things at once — miss any one and it silently fails:

| Where it lands | What happens if it's missing |
|---|---|
| Appended to `需求.md` (`## 唤醒时追加`) | It doesn't survive a step boundary. The next step is a new session that only reads the frozen artifacts |
| Used as the prompt for the work step | The coordinator never receives it at all |
| **Triggers re-derivation of `目标.md`** | The judge is still reading the old checklist, and **whether the newly added thing was finished never enters the verdict** |

The third is the easiest to miss. The judge only reads the frozen `目标.md`; it can't see what you added midway — without re-deriving it will rule "achieved"
against the old checklist while the thing you actually wanted was never verified. The cost is one extra set-goals run per append ([HT002](../cases/ht002.md) measured
$0.41 / 3 minutes).

**Waking without saying anything** (just pressing Enter) neither appends nor re-derives, and costs nothing extra.

### Crashing inside the first step (clarify requirements) still continues

`clarify_step` carries a `resume_prompt` (the constant `CLARIFY_RESUME`): if you crash mid-clarification and start again,
what the [clarifier](../reference/glossary.md#确认者) is told is "continue the clarification you didn't finish just now —
not start over", rather than resending the original request as a new task. Combined with "write to disk the moment you get a session_id" above,
a run that died in the first step before `需求.md` was frozen now continues too, with no need to answer again.

Conversely, already-frozen preceding steps are **skipped entirely**: if `需求.md` has all four sections, clarify requirements is skipped (but its content is still fed into ctx),
and if `目标.md` is complete, set goals is skipped.

### On continuation it doesn't send the same words

`Step.resume_prompt` handles this. The other side's context **already has** the brief, the goals, and where it got to last time; resending
"do it according to this brief: <the whole brief>" verbatim is pure noise, and worse, it reads as "the requirements changed, take another look".

If you don't give a `resume_prompt`, `prompt` is reused — some steps genuinely should resend the full text (when set-goals re-derives the checklist,
the complete brief is exactly what it needs).

### It prints a line on wake

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

Without it, "does it actually remember" is completely imperceptible — and that's the entire value of this layer. In the banner,
`需求已确认` is always present, `目标 N 条` only when the verdict checklist is non-empty, and `干活上下文 X` requires that the last-round context size of that session can be
looked up in `sessions.db`.

**The context number is put there on purpose** — the reason is in the "Cost" section below.

### Resilience: hang and wait when the network is down, and keep errors out of the resumed context

[Resilience](../reference/glossary.md#韧性) and continuity go together: a run that lasts hours will hit a network drop, and the default behavior is bad —
the moment the connection drops, the harness stuffs a **synthetic assistant message** into the transcript (`isApiErrorMessage=true`,
`model="<synthetic>"`) whose body is "API Error: Can't reach the API server …". That message becomes the leaf of the session,
and every later resume feeds it back as "what the model said last", so the model thinks it's discussing a network failure.

`Resilience` does three things:

**One: the probe does DNS + TCP only.** `reachable(host, port, timeout=5.0)` runs `getaddrinfo` plus one TCP handshake,
**no HTTP, no credentials, no cost**; any exception counts as unreachable. Which address it probes is decided by `endpoint()`, which follows
`ANTHROPIC_BASE_URL`, defaulting to `https://api.anthropic.com` with port `443` (`80` for http).
**With a self-hosted gateway you must probe the gateway** — `api.anthropic.com` being reachable says nothing about the gateway.

**Two: separate what deserves waiting from what deserves stopping.** `classify(text)` returns `"transient"` / `"fatal"` / `"unknown"`,
and **checks fatal before transient** — 401-type text often contains the word "connection", and the wrong order means waiting forever.
Defaults: `max_attempts=6` (including the first), `base_delay=4.0`, `max_delay=120.0`, `probe_timeout=5.0`,
`probe_interval=15.0`, `max_offline_wait=3600.0` (1 hour), `retry_unknown=True`.
Backoff is `min(base_delay * 2**(attempt-1), max_delay)` times ±25% jitter.

Once a session_id has been obtained it **resumes rather than restarts**, so the earlier spend isn't wasted. On resume it sends
`Resilience.resume_prompt`: "the previous round was interrupted midway and didn't finish. Check what has already been spilled into the workbench,
pick up from where it stopped, don't start over." It **deliberately contains no error detail** — the model needs to know "you were interrupted, keep going",
not whether it was ENOTFOUND or 503.

**Three: the errors produced by a retry storm don't enter the post-resume context.** That's [pruning](../reference/glossary.md#剪除)'s job.
`Runtime`'s session store is hardcoded to `PruningSessionStore`, which does three things in `load()`:

- strips synthetic API error messages. **They're kept verbatim in SQLite**, just not fed back
- strips older denied calls, keeping only the most recent `keep_denials=1`
- replaces `tool_result` leftovers from an interruption with a neutral note "[上一轮在此处被中断,该工具结果未产生]", changing only the body without removing the entry

Keeping 1 instead of 0 has a reason: a denied call never executed, so its result carries no information, yet it takes up real space
(measured once at 273 characters = 93 characters of refusal + 180 characters of **the original dead command**), and **it misleads** —
in practice, after reading a few "don't use Bash directly" entries the coordinator stopped even attempting a permitted `git status`; it had learned helplessness.
But keeping the most recent one is useful: it stops the model from retrying the same blocked command over and over within a round.

Stripping has one structural red line: the transcript is a `parentUuid` single chain, so removing an entry means reattaching its children to the nearest surviving ancestor,
otherwise the chain breaks there and all prior history is lost.

[HT001](../cases/ht001.md) hit this once for real: the outage timeline was 01:52:40 → 01:55:41, and in `manifest.json` that step is
`attempts=2` / `resumed=True` / `ok=True`; after resuming it ran another 8-plus hours to completion.

One last thing that's easy to misread: **`Runtime(trim=False)` does not mean "nothing is cleaned"**. `trim` defaults to `False` anyway,
but it only turns off the **large tool result [trimming](../reference/glossary.md#裁剪)** layer. Stripping disconnect debris, stripping denied calls,
neutralizing interruption leftovers, marking [ephemeral command](../reference/glossary.md#一次性命令) results stale — those four still happen
(`ephemeral` defaults to `True`, `keep_denials` defaults to `1`).

### Cost: context keeps growing, with no end

This is an inherent cost of continuity, not a bug.

The "work" step in [HT001](../cases/ht001.md) ran 10.44 hours straight, and [main thread](../reference/glossary.md#主线程) context was
**28.7K** at round 1, **35.2K** at round 20, **108.6K** at round 35, **158.2K** at round 50, **185.9K** at round 70 —
monotonically rising, slope about **2.2K/round**; never compacted, using **18.6%** of the 1M window. Extrapolating at that slope,
the wall arrives around **440 rounds** — the ceiling of "long-horizon" in its current form is roughly **6 times** that run. Permanent continuity means hitting the window some day.

Two mechanisms manage it:

1. **Trimming** (`flower --no-trim` turns it off; the `flower` path has it on by default) — on resume, old large tool results are replaced with
   file pointers; the content isn't lost, it just doesn't stay resident
2. **[Handoff](handoff.md)** — at the threshold, write a handoff document and switch to a new session. **This is not [compaction](../reference/glossary.md#压缩)**:
   the document is readable and editable, so you can see what was dropped. Context therefore falls back periodically instead of climbing all the way into the wall

**Which is why the wake line must print the context number**: if people can see it, they have the chance to decide to start over before hitting the wall.

An aside: `--rounds` (total work rounds) **resets on every wake**. That's intentional — a new wake is a new intent,
and it shouldn't inherit the rounds spent last time.

### Starting something new

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
and lineage's `steps` and `woke` are zeroed at the same time. The three are three faces of the same stretch of history; taking only part of them leaves a half state like
"the goals are still there but the conversation is gone".

`sessions.db` is untouched — it's the archive, and every transcript in it is still queryable.

In code this is `Lineage.archive(into, extra=[...])`.

## When not to use it

- **Scenarios that require a clean start every time.** Batch-running the same workflow, running controlled evaluations, reproducing a bug for someone else —
  none of these should carry the previous context. Write `Workflow(..., continuous=False)`, or use a different `run_dir` each time.
- **The directory will be moved or copied, or `run_dir` isn't persistent.** Running in a container with `runs/` on the container's inner filesystem,
  or rsyncing the workspace to another machine — continuity will **silently fail** (the path guard rejects lineage that doesn't match).
  Don't treat it as a guarantee.
- **This is a new intent and the context is already large.** Continuity carries the irrelevant history along, and you pay tokens for it every round.
  Rather than putting up with that, `--new` to archive and start over.
- **One-off single agents.** `flower once` doesn't go through `Workflow` and has no lineage; to resume you supply `--resume <session_id>` yourself.
- **Treating continuity as a backup.** It only records "which step used which session". Code, artifacts, and decisions belong in the workspace and the
  [workbench](../reference/glossary.md#工作台), not something to dig back out of a transcript.

## Related

- [Handoff](handoff.md) — what to do when context fills up inside a single run; the same thing as this page from the other direction
- [Goal guard](goal.md) — why the judge doesn't continue
- [Context economics](context.md) — what trimming, pruning, and spilling each handle
- [Python API](../reference/api.md) — `Lineage`, `Workflow.continuous`, `Step.resume_prompt`, `wake_state`
- [Command line](../reference/cli.md) — `--new`, `--no-trim`, `--rounds`, `-r/--run-dir`
- Source: [`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
