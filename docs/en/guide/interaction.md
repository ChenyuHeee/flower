# Swapping the interaction layer

flower's core does not know a UI exists. Everything that happens during a run — the model speaking,
a tool call, the context filling up, a question for a human — is flattened into the same data
structure, [`Event`](../reference/glossary.md#事件).
**The [interaction layer](../reference/glossary.md#交互层) only knows `Event`; it imports no SDK types.**
That is the boundary that lets you swap the UI without touching the core: terminal, Web, HTTP service,
fully unattended — what changes is the consumer of `Event`, and nothing else needs a single line changed.

## What problem it solves {#解决什么问题}

The SDK's message stream is made of **internal types**: `AssistantMessage`, `ToolUseBlock`, `ToolResultBlock`,
`ResultMessage`, `SystemMessage`… Consuming them directly in the UI has two consequences: every SDK upgrade
forces a frontend change; and since every message has a different shape, every UI has to reimplement the
"is this body text or a tool call" decision from scratch.

`normalize(message)` turns one SDK message into 0 to N `Event`s
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
The cost is one conversion; what you get is no type dependency between the interaction layer and the SDK.

This boundary also handles four less obvious things along the way, all of them inside `normalize()`:

1. **[subagent](../reference/glossary.md#subagent) output is labelled** (`payload["subagent"]`).
   Otherwise the dispatched [task brief](../reference/glossary.md#任务书) and the subagent's intermediate
   output would blend into the [main thread](../reference/glossary.md#主线程) body text, and then flow
   down the [workflow](../reference/glossary.md#流程) to pollute the next step's prompt.
2. **The synthetic error message emitted on a dropped connection is routed to `kind="error"`.** When the
   connection drops, the SDK side writes `API Error: …` into the transcript as an assistant message; it
   looks like something the model said (`model` is `"<synthetic>"`).
   If it is not intercepted here, it lands in `StepResult.text` and gets passed on to the next
   [step](../reference/glossary.md#步骤).
3. **Compact boundaries are reported explicitly** (`kind="reset"`). After the boundary, all the model
   "remembers" is the summary, and the prompt cache is broken there too — a
   [long-horizon](../reference/glossary.md#长程) run must be able to see it.
4. **The context level comes out with every message** (`payload["context"]` = `input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`). It is the sole source for the
   [handoff](../reference/glossary.md#换代) criterion.

## How to use it (minimal code) {#怎么用最小代码}

An interaction layer wires up three things: an **event sink** (where to render), a **question channel**
(who answers), and **interrupts** (how to call a halt). The snippet below wires up all of them and runs as is:

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Render the Event into your own UI — this is the only thing you need to swap."""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ 换代/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ 重试: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ 人主动说:{ev.text}")
    # kind == "ask" that is not mail is handled by the answerer below (pull style)


async def answerer(ch: HumanChannel) -> None:
    """Pull questions. When moving to Web / HTTP, this coroutine is the other place to change."""
    while True:
        ask = await ch.next_ask()           # no timeout means wait forever
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # or ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime uses the workbench the workflow already built — do not assemble another one
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        ctx = await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()                          # close the SQLite connection
    print(rt.total_cost(), ctx.get("_failed_at"))


asyncio.run(main())
```

Two easily missed pieces of cleanup: `rt.close()` must go in `finally`; and if `ctx["_failed_at"]` has a
value the run stopped midway (`on_fail="stop"`) — don't treat it as success.

!!! note "There is only one workbench — do not assemble another one"
    The [workbench](../reference/glossary.md#工作台) that `Runtime(workbench=True)` builds lives at
    `<run_dir>/workbench`, whereas `Workbench(ws)` defaults to `<ws>/.flower` —
    they are not the same directory. If the driver program assembles its own path to find `需求.md`,
    you get "the brief is written into directory A while the injected index scans directory B", and
    nothing reports an error.
    Either hand the one the workflow built to `Runtime` (as above),
    or use the read-only probe `wake_state()` to ask where it is.

### Three event sinks {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. a single agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. the whole workflow, forwarded to every step
wf = Workflow(steps=[...], channel=ch)                  # 3. the question channel, wired to the same sink
```

The third wiring happens inside `Workflow.run`: **it is wired automatically only when `on_event` is not
`None` and `channel.on_event` is still `None`.** If you wired it yourself, it will not be overwritten:

```python
ch = HumanChannel(on_event=my_own_sink)     # wired by you, Workflow leaves it alone
```

`on_step(step, result)` is a separate callback, invoked once per finished step (**including failures**),
receiving the complete `StepResult`. Hang progress bars, persistence and alerting off it; do not try to
reassemble that from the `Event` stream — body text gets broken into several pieces by handoffs and retries.

### Terminal: the default one {#终端默认的那个}

There is one even without writing code. `flower "帮我做一个 X"` goes through
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py),
which is a **reference implementation of the interaction layer, not part of the framework**, and can be
replaced wholesale; for the switches see the [CLI reference](../reference/cli.md).
Let's be honest about size. All of `cli.py` is 1264 lines, 57KB — but **what you replace is not all of it**.
The actual replacement point is `class Render` inside it (`cli.py:489-687`, 197 lines), whose docstring says
exactly that: "Event → terminal. Swapping the UI means swapping this one class." The other thousand-odd lines
are interrupts, the oracle, inbox receipts and signal rescue — **terminal-specific** plumbing that you would
not carry over to a Web or HTTP layer anyway.

So the claim "about 200 lines, replaceable as a whole" holds — provided it refers to `Render`, not to `cli.py`.

If you write your own terminal UI, the key part is the thread that reads standard input:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Keep reading stdin: if a question is pending it is the answer, otherwise it goes to the inbox. Returns the stop flag."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # poll, so the stop flag can be honoured
            line = sys.stdin.readline()
            if not line:                        # EOF
                return
            raw = line.strip()
            if not raw:
                continue
            pend = ch.pending()
            if pend:
                ch.answer(pend[0].id, raw)      # safe across threads
            else:
                ch.send(raw)                    # into the inbox, does not interrupt work in flight

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

All three points were learned the hard way:

- **Use a daemon thread, not `asyncio.to_thread(input, ...)`.** A blocked `input()` cannot be cancelled, and
  `asyncio.run` joins the default executor's threads before exiting — the result is that after the work is
  done you still have to press Enter once more to quit.
- **Poll with `select`; do not call `input()` directly in the loop.** Same cancellation problem: a thread
  blocked in `input()` can never be woken by `stop.set()`.
- **Read continuously, not only when there is a question.** If you only read while a question is pending,
  anything typed during those hours of work sits in the terminal buffer and gets swallowed as the answer to
  the next question — the question is "answered" before the human has even seen it.

### Web: queue + WebSocket {#web队列--websocket}

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # synchronous, on the event loop's thread, must not block
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # a frontend error should not take down three hours of work
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # request-handling thread — another thread, and that is normal
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` is the raw SDK object (an `Ask` for `ask` events); it is **not JSON-serializable, and should not be
sent to the frontend** — using `raw` binds the frontend back to SDK types, which defeats the entire layer.
The four fields `kind` / `text` / `tool` / `payload` are enough.

### HTTP: sequence numbers + polling {#http序号--轮询}

Without a long-lived connection, number the events so the client can pull:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # keep only the most recent, so memory does not grow with run length


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # what is currently waiting for an answer
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = this question is no longer waiting
```

Two limits to be aware of: once `maxlen` is full the oldest entries are dropped, so a client returning with a
very old `after` cannot get everything — the polling interval has to match that length; and **you must give
`timeout_s` a finite value** — with nobody polling, a question never resolves on its own, and
`timeout_s=None` will hang the entire run forever. The default `1800.0` seconds is a reasonable value.

### Fully unattended: nobody there {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # all events discarded
```

The command-line equivalent is `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (and any negative value) is fully unattended mode: questions **do not enter the wait queue and
do not emit an `asked` event**; they settle immediately as `state="timeout"`, and the tool returns this fixed
text —

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

— so the run continues unimpeded. Questions and answers are still appended to `HumanChannel(log_path=...)`
(`starter_flow` wires it by default to `<workbench>/notes/问答记录.md`), so afterwards you can see what it
asked and what it assumed on its own.

If you don't want it to speak at all, use `max_asks=0`: questions are declined outright
(`state="over_budget"`), likewise without blocking.
Note this is **not** the same as "removing the tool" — `allowed_tools` is not exclusive; the moment a
[coordinator](../reference/glossary.md#协调者) has a `channel` attached, both `mcp__human__ask` and
`mcp__human__inbox` are handed over together, and they are callable whether or not they are listed. Only the
quota and the timeout can actually block a question.

!!! warning "When unattended, never let a question wait forever"
    `timeout_s=None` means "wait forever". With nobody watching, a single question can freeze a ten-hour run
    in place — with no error, no timeout, and nothing in the logs to distinguish it. Unattended runs have only
    two correct values: `0` (settle immediately) or a finite number of seconds.

## What it actually does {#它实际做了什么}

### The shape of `Event` {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15 values, see the table below
    text: str = ""
    tool: str = ""                      # only set for tool_call
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # raw SDK object / Ask; touch it and you are bound back to the SDK
```

`str(ev)`: for `tool_call` it is `[tool name] summary`, otherwise it is `text`; when `text` is empty it is `<kind>`.

### The 15 `EventKind`s {#15-个-eventkind}

| `kind` | Emitted by | When it appears | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | model body text | the text | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | thinking block | thinking content | same as above |
| `prompt` | `normalize()` | **input**: your prompt, the task brief dispatched to a subagent | the input text | same as above |
| `tool_call` | `normalize()` | model initiates a tool call | summary (`file_path` / `command` / `pattern`, truncated to 200 characters) | `id`, `input` + the above; `tool` is the tool name |
| `tool_result` | `normalize()` | tool returns | first 500 characters (empty when the content is not a string) | `tool_use_id`, `is_error` + the above |
| `result` | `normalize()` | one SDK query finishes | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | synthetic message on a dropped connection | error text | `synthetic: True` |
| `reset` | `normalize()` | compact boundary or session reset | `压缩(trigger) 167000 → 42000 tokens`; on session reset it is `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (empty on session reset) |
| `system` | `normalize()` | any other SDK system message | subtype | `data` passed through verbatim |
| `task` | `normalize()` | task progress message | **empty** | `kind` = the SDK's message class name |
| `unknown` | `normalize()` | unrecognized message type | class name | — |

!!! note "`task` has no body text — do not print it directly"
    `TaskProgressMessage` and its kin are internal SDK message types. `normalize()` used to emit the class
    name as body text; on screen that is pure noise, and mixed in with the agent's own output it looks like
    something went wrong (observed in practice). Now it is classified as an event **without body text**, with
    the class name placed in `payload["kind"]` — whether to show it is up to the interaction layer
    (`events.py`).
| `ask` | `HumanChannel` | a human is needed, a question has been resolved, or a human spoke unprompted | the question / what the human said | two identities, see below |
| `retry` | `Runtime` | retrying / waiting on the network | one line of explanation | `step`, `attempt` |
| `step` | `Workflow.run` | step boundary | step name | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | handoff: approaching / writing / done | one line including the context level | `phase`, `step`, `context`, `window` + see below |

**Four kinds are not produced by `normalize()`**: `ask` comes from `HumanChannel`, `retry` and `handoff` come
from `Runtime`, and `step` comes from `Workflow.run`. Putting them in the same `EventKind` is deliberate —
**the UI knows one set of `Event`s and needs no separate path for "a human is needed" or "step boundary".**

When writing a UI, leave an `else` branch. `EventKind` will gain new members, and an old UI should not crash
because of that.

### The three `handoff` phases {#handoff-的三个-phase}

| `phase` | When it fires | Extra `payload` |
|---|---|---|
| `near` | the context level passed `warn_at`. **Fires once per generation**, no flooding | `at` (the handoff threshold) |
| `writing` | starting to write the [handoff document](../reference/glossary.md#交接书). Writing takes a dozen-odd seconds; without this event the UI looks stuck | — |
| `done` | the handoff is written and a new session has begun | `degraded` (whether it is the degraded version), `path` (where it was written; empty string when there is no workbench), `sections` |

For the mechanism itself see [handoff](handoff.md).

### The two identities of `ask` {#ask-的两种身份}

`Event("ask")` carries both "a question" and "something a human said unprompted", so **the UI must check
`payload["kind"]` first**:

| Identity | How to tell | `payload` |
|---|---|---|
| a question | no `kind` key | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`; `raw` is that `Ask` |
| something a human said | `payload["kind"] == "mail"` | `kind`, `state` (`queued` = put in / `delivered` = taken out), `id`, `amended` (which file it was appended to; empty string if unconfigured). **No `options` and no `remaining`** |

A single question emits **two or more** events: one when asked (`state="asked"`), and one when it resolves
(`answered` / `timeout` / `declined` / `over_budget` / `invalid`). The UI can just update the same entry
by `payload["id"]`.

### Asking a human: `Ask` and `HumanChannel` {#问人ask-与-humanchannel}

```python
@dataclass
class Ask:
    id: str                                             # "q1", "q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # one of the five outcomes above
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # seconds waited, one decimal place
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` is an in-process MCP server plus a set of methods for the UI. The model side sees only two
tools: `mcp__human__ask` (ask a question, blocks and waits) and `mcp__human__inbox` (check the inbox,
**non-blocking**; if empty it returns an explanatory line immediately). The full constructor:

```python
HumanChannel(
    *,                                  # all keyword-only
    on_event=None,                      # push sink. Workflow wires it automatically only when it is None
    max_asks=None,                      # None = unlimited; 0 = asking not allowed. Over quota is declined outright, no blocking
    timeout_s=1800.0,                   # None = wait forever; <= 0 = settle immediately
    log_path=None,                      # Q&A appended to this file, costs no context
    amend_path=None,                    # what a human says mid-run is appended to this file, usually the brief
    over_budget_text=OVER_BUDGET,       # three fixed replies, replaceable with your own
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` is the one most easily missed, and it decides whether "a requirement the human changed mid-run"
survives a step boundary. Every step is a new [session](../reference/glossary.md#会话) over read-only frozen
artifacts: something said during the run entered only that agent's context, and the next step (a
[verdict](../reference/glossary.md#判定), say) is a brand-new session reading `需求.md` and `目标.md`, which
**does not see what you said** — so it judges against the old boundary and rules the corrected work
out of scope. `amend_path` **appends** each message into the
[brief](../reference/glossary.md#需求确认书) — appending, not overwriting; the original requirement is
history, and seeing what changed beats not seeing it. `starter_flow` wires it by default to
`<workbench>/notes/需求.md`.

Observed in practice ($0.6767), this works better than expected: a human said "also report the total byte
count", and after seeing it in the inbox the coordinator reported —
"hand has already read it from the mid-run addendum in `.flower/notes/需求.md` and computed it; no need to
dispatch again."
**The subagent read it from the file; it did not depend on anyone relaying it.**

Public members:

| Member | Signature | Semantics |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | Feed directly into `AgentSpec.mcp_servers`. The key must match the server name, which is why it is provided together |
| `ask` | `async (question, options=None) -> Ask` | Block and wait for a human. **Never raises except `CancelledError`** — no answer is also an answer; distinguish via `ask.state` |
| `pending` | `() -> list[Ask]` | Questions currently waiting for an answer |
| `next_ask` | `async (timeout=None) -> Ask \| None` | For pull-style UIs. Returns `None` on timeout, raises if cancelled |
| `answer` | `(ask_id, text) -> bool` | Answer. `False` = this question is no longer waiting (timed out / already answered) |
| `decline` | `(ask_id, reason="") -> bool` | Skip; let the model decide for itself and write the assumption into "Unknowns and assumptions" |
| `send` | `(text) -> Mail \| None` | A human says something unprompted, into the inbox. Does not interrupt the agent; internally calls `amend()` automatically |
| `amend` | `(text, *, label="运行中补充") -> bool` | Append to `amend_path`. Returns whether it actually wrote (unconfigured path / empty text / `OSError` all give `False`) |
| `pending_mail` | `() -> list[Mail]` | Messages not yet taken out |
| `remaining` | `-> int` | How many questions are left. With `max_asks=None` it returns **`-1`**, not 0 |
| `transcript` | `() -> str` | The Q&A record as markdown |
| `asks` / `mail` / `ui_errors` | `list` | All questions / everything the human said / exceptions raised by the UI callback |

`answer`, `decline` and `send` **may be called from any thread**. A Web backend's request-handling thread and
a TUI's input thread are both other threads — that is the norm, not an edge case. Internally they go through
`loop.call_soon_threadsafe`, because `asyncio.Future.set_result` is not thread-safe.

Push and pull are two ways of getting them; **pick one**:

| | How to get them | Suits |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, receiving `kind == "ask"` with `payload["state"] == "asked"` | event-driven UIs (Web push, TUI redraw) |
| **Pull** | `await channel.next_ask()` | a separate input task |

The three "0 / None" semantics all differ; mix them up and you get either a hang or a run that never asks
anything while unattended:

| Form | Meaning |
|---|---|
| `max_asks=None` | unlimited (default) |
| `max_asks=0` | asking not allowed, declined outright |
| `timeout_s=None` | wait forever |
| `timeout_s<=0` | do not wait; questions settle immediately |
| `remaining` returns `-1` | the value when `max_asks=None`, not 0 |

### Interrupts: any thread can call a halt {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")`; an empty string just interrupts without saying anything.
Three properties:

- **It continues the same session** (`resume`), not from scratch — the work already done and the context are
  still there. It reuses the existing path for network-failure retries, only swapping "the failure reason"
  for "a human interrupted" and `resume_prompt` for what the human said.
- **It does not consume `max_attempts`.** That quota is for faults, not for humans.
- **It is cooperative**: it breaks at a message boundary and does not hard-cancel the task. The cost is a
  delay until the next message (if a subagent is running you wait for it to come back); what you get is that
  state is never torn apart midway.

The cost, stated plainly: an interrupt makes **a subagent in flight lose its half-finished work** (observed
during the HT001 network drop, see
[issue #2](https://github.com/ChenyuHeee/flower/issues/2)). The terminal reference implementation spells this
out in the prompt so the human knows before pressing; your own UI should do the same.

If you don't want to interrupt and just want to add a requirement, use the inbox (`ch.send(...)`) — it
interrupts nothing, and the delay is until the agent's next checkpoint.

### Oracle: ask a question without disturbing the run {#旁路顾问问一句而不打扰运行}

If you want to know "where are we now", you don't have to interrupt, and you should not ask the coordinator:
that exchange would **permanently occupy main-thread context** (which holds decisions, not Q&A records), and
it would have to stop what it is doing. Over a ten-hour run, three casual questions pay both costs.

The [oracle](../reference/glossary.md#旁路顾问) is a read-only side path. Its only tools are `Read` / `Glob` /
`Grep`, it has the workbench open, and it comes with brakes by default: `max_turns=12`,
`max_budget_usd=0.5`. In the terminal it is triggered by a line starting with `?`, and it answers from two
things: a recent event window (fixed at 60 entries) and the brief, goal, notes and artifacts in the
workbench. It uses its own `Runtime` (`<run_dir>/aside`), so its cost and session
[lineage](../reference/glossary.md#血缘) **do not get mixed into the main manifest** — that manifest records
"which steps this run performed", and a passing question is not a step.

Measured: two questions cost $0.5190 in total, and the main run's manifest did not grow by a single byte.

### Two hard rules {#两条硬规矩}

!!! warning "on_event must neither block nor let exceptions escape"
    **One: `on_event` is a synchronous function, called on the event loop's thread.** So
    `asyncio.Queue.put_nowait()` is safe, `await` is not (it is not a coroutine), and **blocking it blocks the
    entire run**. If there is slow work to do, put it on a queue and let another task do it.

    **Two: raising inside `on_event` damages the run itself.** Body-text events are emitted inside the `try`
    block of `Runtime._attempt`, so the exception is recorded as `result.error` — that step is judged failed;
    `retry` events are emitted outside that block, so the exception propagates straight out of `Runtime.run`.
    The frontend should not take down three hours of work — **wrap it in your own try**.

    Exception: the `ask` events that `HumanChannel` emits itself are already wrapped; exceptions go into
    `channel.ui_errors` and do not interrupt the run.

## When not to use it {#什么时候不该用它}

### Things the interaction layer should not do {#交互层里不该做的事}

| Don't | Why | Do instead |
|---|---|---|
| `from claude_agent_sdk import ...` | once the interaction layer depends on SDK types, every SDK upgrade drags the frontend along and the layer is pointless | use only `Event`'s `kind` / `text` / `tool` / `payload` |
| read `ev.raw` | same as above, plus it is not JSON-serializable | whatever detail is missing, add it to `normalize()`'s `payload`; do not go around the boundary |
| `await`, issue network requests, or write to slow disks inside `on_event` | it is synchronous and called on the event loop thread; blocking it blocks the whole run | `put_nowait()` onto a queue and consume it in another task |
| let `on_event` raise | an exception on a body-text event turns into `result.error` and fails the step | wrap the whole callback body in `try` |
| use `disallowed_tools` to turn off asking | it is **session-level** and will also disable the same-named tool in subagents (observed error text: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` or `timeout_s=0` |
| remove `mcp__human__ask` from `allowed_tools` as a way to forbid asking | `allowed_tools` is not exclusive; it is a no-approval list, not a whitelist — attaching a `channel` hands over both tools together | same as above |
| assemble your own path to find `需求.md` / `目标.md` | the workbench has two possible locations; getting it wrong raises no error, it just silently does nothing | `wake_state()` or `wf.workbench` |
| reassemble progress and results from the `Event` stream | body text is broken into several pieces by handoffs and retries | `on_step(step, result)` gives you the complete `StepResult` |
| use `timeout_s=None` when unattended | nobody answers, the run hangs forever, with no error and no timeout | `0`, or a finite number of seconds |

### When you don't need to swap anything at all {#什么时候根本不用换}

- **You only want to change colours, or print one more or one fewer line** — just change the rendering
  function. Rewriting the interrupts, oracle, inbox receipts, SIGHUP / SIGTERM rescue and waiting for the
  side path to finish before exit, all present in the terminal reference implementation, is not cheap.
- **You only want to run one step, without interaction** — use `flower once`. It does not go through the
  interactive driver path, so it never had Ctrl+C interrupts, the stdin answering thread, the oracle or
  signal rescue in the first place.
- **What you actually want to change is the workflow, not the UI** — see [designing a workflow](workflow.md).
  The interaction layer only decides who watches and who answers; how many steps run, how they are judged,
  and when to exit early is decided by `Workflow`.
- **What you want to change is the session store, the model or the budget** — none of those three sit on this
  boundary; see the [Python API reference](../reference/api.md).
