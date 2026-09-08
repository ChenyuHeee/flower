# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">A portable long-horizon agent framework built on the Claude Agent SDK.</p>

<p class="fl-hero__sub">Turn Claude Code into a purpose-built agent you can take with you, customize the interaction of, and run for days — without giving up any of its capability.
The agent on the main thread only makes decisions; everything hands-on is delegated to subagents. Requirements get pinned down before work starts, and whether the work is actually done is decided by a different role.
Move to another machine and the behavior is identical — it does not read the host's settings, and it carries its own credentials.</p>

[Quickstart](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>cost of one run</span></div>
<div class="fl-stat"><b>10.4 hours</b><span>continuous; network dropped mid-run and it resumed itself</span></div>
<div class="fl-stat"><b>185.9K</b><span>peak main-thread context, never compacted</span></div>
<div class="fl-stat"><b>94.8%</b><span>of body characters landed in subagents</span></div>
</div>

The four numbers come from [HT001](cases/ht001.md) — the run in which an agent wrote a terminal IDE from scratch under flower.

## Install {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

It finds `uv` / `pipx` / `pip` automatically and installs the `flower` command. All you need is Python ≥ 3.10 — no Node,
no Claude Code CLI. Once installed, `cd` into any project directory and type `flower`: the first time it will ask you for an API key
or a gateway address; configure it once, it is stored in `~/.config/flower/.env`, and it applies everywhere. If Claude Code is already installed and configured on this machine,
it borrows that token directly and does not ask at all. For the full steps and troubleshooting, see [Install](getting-started/install.md).

## It blocks four classes of failure for you {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Clarify](guide/clarify.md) {#前置确认}

Afraid of building the wrong thing — before any work starts, a role that only asks questions and never touches code keeps asking until things are clear, then freezes the requirements into a document
that every later step reads to open with.
</div>

<div class="fl-card" markdown>
### [Goal guard](guide/goal.md) {#目标看守}

Afraid it says "done" when it isn't — at the end of every round of work, a different role judges once, independently. Met: move on. Not met: send it back.
Can't be verified in this environment: stop and ask a human.
</div>

<div class="fl-card" markdown>
### [Continuity](guide/continuity.md) {#接续}

Afraid of a crash after hours of running and starting over — type `flower` again in the same directory and it picks up where it left off, the same whether the process was killed
or the machine rebooted. You don't have to remember any id.
</div>

<div class="fl-card" markdown>
### [Handoff](guide/handoff.md) {#换代}

Afraid a full context gets squashed into one summary — the current session writes its own handoff document that a human can read and edit, and a new session takes over.
No compact needed.
</div>

</div>

## What makes it "long-horizon" {#长程}

The [coordinator](reference/glossary.md#协调者) on the main thread carries decisions only; it has no `Write` and no `Edit` —
writing code, running tests, looking things up all go to [subagents](reference/glossary.md#subagent),
and a subagent's trial and error goes into **another** transcript. The main thread receives only a report of no more than 30 lines.
Across that 10.4-hour HT001 run, **94.8% of body characters landed in subagents**;
of 1,893 hands-on tool calls, only 32 ever entered the coordinator's field of view.
That's why the main thread only climbed to 185.9K over 70 turns and never compacted once — how this layer works, and what the other three layers are,
see [Context economics](guide/context.md).

## It has actually been run {#真的跑过}

- **[HT001](cases/ht001.md)** — writing a terminal IDE from scratch. $171.62 / 10.4 hours /
  main-thread context climbed to 185.9K, delivered 12,212 lines of product code, lost the network once mid-run and finished on its own.
- **[HT002](cases/ht002.md)** — getting it installed and running on macOS. $38.24 / about 1 hour, the first run with the goal guard;
  the program did come up, and the verdict was **not met**, surfacing a question to a human.

Both pages also write down what doesn't hold up: in HT001 the agent got one item of its own acceptance check wrong,
and HT002 turned `git clone && make && ./cppide` into an hour. Every number can be recomputed from `runs/manifest.json`
and `sessions.db` — these are raw records, not promotion.

## Where to start reading {#从哪读起}

- **Want to run it right now** — [Quickstart](getting-started/quickstart.md): spend twenty cents verifying credentials first,
  then run a full three-step workflow with zero code.
- **Want the concepts first** — [Core concepts](getting-started/concepts.md): runs, steps, sessions, the five roles,
  all in five minutes.
- **Want to wire it into your own code** — [Python API](reference/api.md): `Runtime`, `Step`, the five role factories,
  signatures and defaults for 62 public symbols.
