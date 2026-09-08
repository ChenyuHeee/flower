# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">A portable long-horizon agent framework built on the Claude Agent SDK.</p>

<p class="fl-hero__sub">Turn Claude Code into a dedicated agent you can carry with you, customize the interaction of, and run for days — without giving up any of its capability.
The agent on the main thread only makes decisions; all the hands-on work goes to subagents. Requirements get clarified before work starts, and whether the work is actually done is judged by a different role.
Move to another machine and the behavior is identical — it does not read the host's settings, and it brings its own credentials.</p>

[Quickstart](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>cost of one run</span></div>
<div class="fl-stat"><b>10.4 hours</b><span>continuous, reconnected itself after the network dropped</span></div>
<div class="fl-stat"><b>185.9K</b><span>peak main-thread context, never compacted</span></div>
<div class="fl-stat"><b>94.8%</b><span>of body characters landed in subagents</span></div>
</div>

The four numbers come from [HT001](cases/ht001.md) — the run in which an agent wrote a terminal IDE from scratch under flower.

## One command to install, no Node required {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

The script finds `uv` / `pipx` / `pip` on its own and installs the `flower` command. All you need is Python ≥ 3.10 —
the Claude Code CLI is not required either. Once installed, `cd` into any project directory and type `flower`: the first time it asks for an API key
or a gateway address, you configure it once, it is stored in `~/.config/flower/.env`, and it applies everywhere. If Claude Code is already installed and configured on this machine,
it borrows that token directly and does not even ask. Full steps and troubleshooting in [Install](getting-started/install.md).

## It blocks four classes of failure for you {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Clarify](guide/clarify.md) {#前置确认}

Afraid of building the wrong thing — before any work starts, a role that only asks questions and never touches anything keeps asking until things are clear, then freezes the requirements into a document
that every later step reads at the start.
</div>

<div class="fl-card" markdown>
### [Goal guard](guide/goal.md) {#目标看守}

Afraid it will claim done when it is not — at the end of every round of work a separate role judges independently: achieved, move on; not achieved, send it back;
can't be verified in this environment, stop and ask a human.
</div>

<div class="fl-card" markdown>
### [Continuity](guide/continuity.md) {#接续}

Afraid of hours of work crashing and starting over — type `flower` again in the same directory and it picks up where it left off, the same whether the process was killed
or the machine rebooted, and you do not have to remember any id.
</div>

<div class="fl-card" markdown>
### [Handoff](guide/handoff.md) {#换代}

Afraid a full context gets crushed into a summary — the current session writes its own handoff document, readable and editable by a human, and a new session takes over.
No compact needed.
</div>

</div>

## What makes it "long-horizon" {#长程}

The [coordinator](reference/glossary.md#协调者) on the main thread carries only decisions and does not get `Write` or `Edit` —
writing code, running tests, looking things up all go to [subagents](reference/glossary.md#subagent),
and a subagent's trial and error goes into **another** transcript; the main thread only receives a report of no more than 30 lines.
In that 10.4-hour HT001 run, **94.8% of body characters landed in subagents**,
and of 1,893 hands-on tool calls only 32 ever entered the coordinator's view.
That is why the main thread only grew to 185.9K after 70 rounds and never compacted once — how this layer works, and what the other three layers are,
see [Context economics](guide/context.md).

## Raw records of two real long runs {#真的跑过}

- **[HT001](cases/ht001.md)** — writing a terminal IDE from scratch. $171.62 / 10.4 hours /
  main-thread context grew to 185.9K, delivered 12,212 lines of product code, lost the network once mid-run and finished on its own.
- **[HT002](cases/ht002.md)** — getting it installed and running on macOS. $38.24 / about 1 hour, the first run with the goal guard;
  the program did start up, and the verdict was **not achievable**, so it surfaced and asked a human.

Both pages also write down what does not hold up: in HT001 the agent judged one of its own acceptance items wrong,
and HT002 turned `git clone && make && ./cppide` into an hour. Every number can be recomputed from `runs/manifest.json`
and `sessions.db` — these are records, not marketing.

## Where to start reading {#从哪读起}

- **Want to run it right now** — [Quickstart](getting-started/quickstart.md): three commands to get it running,
  then how to read what scrolls past on screen.
- **Want the concepts first** — [Core concepts](getting-started/concepts.md): runs, steps, sessions, the five roles,
  all in five minutes.
- **Want to wire it into your own code** — [Python API](reference/api.md): `Runtime`, `Step`, the five role factories,
  signatures and defaults for all 62 public symbols.
