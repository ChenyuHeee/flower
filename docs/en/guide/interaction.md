# Swapping the interaction layer

flower's core does not know a UI exists. Everything that happens during a run — the model
speaking, a tool call, the context filling up, a question for the human — is flattened into one
data structure, [`Event`](../reference/glossary.md#事件).
**The [interaction layer](../reference/glossary.md#交互层) sees only `Event`; it imports no SDK types.**
That is the boundary that lets you swap the UI without touching the core: terminal, web, HTTP
service, fully unattended — what changes is the consumer of `Event`, and nothing else.

## What problem it solves {#解决什么问题}

The SDK's message stream is made of **internal types**: `AssistantMessage`, `ToolUseBlock`,
`ToolResultBlock`, `ResultMessage`, `SystemMessage`… Consuming them directly in a UI has two
consequences: every SDK upgrade drags the frontend along; and since every message has a different
shape, every UI has to re-implement the "is this prose or a tool call" decision from scratch.

`normalize(message)` turns one SDK message into 0 to N `Event`s
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py)).
The price is one conversion; what you get is no type dependency between the interaction layer and
the SDK.

This boundary also handles four less obvious things along the way, all inside `normalize()`:

1. **[subagent](../reference/glossary.md#subagent) speech is marked** (`payload["subagent"]`).
   Otherwise the [task brief](../reference/glossary.md#任务书) handed out and the subagent's
   intermediate chatter get mixed into [main thread](../reference/glossary.md#主线程) prose, and
   then flow down the [workflow](../reference/glossary.md#流程) to pollute the next step's prompt.
2. **Synthetic error messages from a dropped connection are routed to `kind="error"`.** On a
   disconnect the SDK side writes `API Error: …` into the transcript as an assistant message; it
   looks exactly like something the model said (`model` is `"<synthetic>"`). If you don't stop it
   here it lands in `StepResult.text` and gets passed to the next
   [step](../reference/glossary.md#步骤).
3. **Compact boundaries are reported explicitly** (`kind="reset"`). After the boundary, all the
   model "remembers" is the summary, and the prompt cache breaks there too — a
   [long-horizon](../reference/glossary.md#长程) run has to be able to see it.
4. **The context level comes out with every message** (`payload["context"]` = `input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`). It is the only source for the
   [handoff](../reference/glossary.md#换代) decision.

## How to use it (minimal code) {#怎么用最小代码}

An interaction layer has to hook up three things: an **event sink** (where to render), a
**question channel** (who answers), and **interrupts** (how to call a halt). The snippet below
wires all three and runs as-is:

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """Render Event into your own UI —— this is the only thing you need to replace."""
    if ev.kind == "step":
        print(f"\n=== {ev.text} ({ev.payload['index']}/{ev.payload['total']}) ===")
    elif ev.kind == "text" and not ev.payload.get("subagent"):
        print(ev.text)
    elif ev.kind == "tool_call":
        print(f"  [{ev.tool}] {ev.text}")
    elif ev.kind == "handoff":
        print(f"  ~ handoff/{ev.payload.get('phase')}: {ev.text}")
    elif ev.kind == "retry":
        print(f"  ~ retry: {ev.text}")
    elif ev.kind == "ask" and ev.payload.get("kind") == "mail":
        print(f"  ~ human spoke up: {ev.text}")
    # kind == "ask" that is not mail is handled by the answerer below (pull mode)


async def answerer(ch: HumanChannel) -> None:
    """Pull questions. Moving to Web / HTTP, this coroutine is the other place you change."""
    while True:
        ask = await ch.next_ask()           # no timeout means wait forever
        if ask is None:
            continue
        print(f"\n?? {ask.question} options={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # or ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime uses the workbench the workflow already built —— don't assemble another one
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

Two easy-to-miss bits of cleanup: `rt.close()` must go in `finally`; and if `ctx["_failed_at"]`
has a value the run stopped part way (`on_fail="stop"`) — don't treat that as success.

!!! note "There is only one workbench — don't assemble another"
    The [workbench](../reference/glossary.md#工作台) built by `Runtime(workbench=True)` lives at
    `<run_dir>/workbench`, while `Workbench(ws)` defaults to `<ws>/.flower` —
    they are not the same directory. If your driver assembles a path itself to find `需求.md`,
    you get "the brief written to directory A, the injected index scanning directory B" — with no
    error raised. Either hand the workflow's workbench to `Runtime` (as above),
    or ask where it is with the read-only probe `wake_state()`.

### Three event sinks {#三个事件出口}

```python
await rt.run(spec, "…", on_event=sink)                  # 1. a single agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. the whole workflow, forwarded to every step
wf = Workflow(steps=[...], channel=ch)                  # 3. the question channel, into the same sink
```

The third hookup happens inside `Workflow.run`: **it is wired automatically only when `on_event`
is not `None` and `channel.on_event` is still `None`.** If you wired it yourself it will not be
overwritten:

```python
ch = HumanChannel(on_event=my_own_sink)     # wired by you, Workflow leaves it alone
```

`on_step(step, result)` is a separate callback, called once after every step finishes
(**including failures**), receiving the full `StepResult`. Hang progress bars, persistence and
alerting here; don't try to assemble them out of the `Event` stream — prose gets chopped into
several pieces by handoffs and retries.

### Terminal: the default one {#终端默认的那个}

There is one even if you write no code. `flower "帮我做一个 X"` goes through
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py),
which is a **reference implementation of the interaction layer, not part of the framework**; you
can replace it wholesale. For its switches see the [CLI reference](../reference/cli.md).

To be honest about the size: all of `cli.py` is 1264 lines, 57KB — but **the part you replace is
not all of it**. The actual replacement point is `class Render` inside it (`cli.py:382-578`, 197
lines), whose docstring says exactly that: "Event → terminal. Swapping the UI means swapping this
one class." The other thousand-odd lines are interrupts, the oracle, inbox receipts and signal
rescue — **terminal-specific** scaffolding that a web or HTTP layer would not carry over anyway.

So "roughly 200 lines, replaceable as a unit" holds — provided it refers to `Render`, not to
`cli.py`.

If you write your own terminal UI, the crux is the thread reading standard input:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """Read stdin continuously: if a question is pending this is the answer, otherwise it goes to the inbox. Returns the stop flag."""
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

- **Use a daemon thread, not `asyncio.to_thread(input, ...)`.** A blocked `input()` cannot be
  cancelled, and `asyncio.run` joins the default executor's threads before exiting — the result is
  that after the work is done you still have to press Enter once more to quit.
- **Poll with `select`, don't call `input()` straight in the loop.** Same reason — it can't be
  cancelled: a thread blocked on `input()` will never be woken by `stop.set()`.
- **Read continuously, not only when there is a question.** If you only read when a question is
  pending, anything typed during those hours of work sits in the terminal buffer and gets eaten as
  the answer to the next question — the question is "answered" before the human has even seen it.

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


@app.post("/answer")                    # request handler thread —— a different thread, and that is normal
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` is the raw SDK object (an `Ask` in `ask` events); it is **not JSON-serializable, and
don't send it to the frontend** — touching `raw` binds the frontend back to SDK types and this
whole layer was for nothing. The four fields `kind` / `text` / `tool` / `payload` are enough.

### HTTP: sequence numbers + polling {#http序号--轮询}

Without a long-lived connection, number the events and let the client pull:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # keep only the recent ones, so memory does not grow with run length


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

Two limits to be aware of: once `maxlen` is full the oldest entries are dropped, so a client
coming back with a very old `after` will not get everything — the polling interval has to match
that length. And **you must give `timeout_s` a finite value** — with nobody polling, a question
will never end on its own, and `timeout_s=None` leaves the entire run hanging forever. The default
of `1800.0` seconds is a good one.

### Fully unattended: nobody there {#全自动无人值守没有人}

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # all events discarded
```

The command-line equivalent is `flower "帮我做一个 X" --timeout 0`.

`timeout_s=0` (and any negative value) is unattended mode: a question **does not enter the wait
queue and emits no `asked` event**; it settles immediately as `state="timeout"` and the tool
returns this fixed text —

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

— and the run carries on. The exchange is still appended to `HumanChannel(log_path=...)`
(`starter_flow` wires it to `<workbench>/notes/问答记录.md` by default), so afterwards you can see
what it asked and what it assumed on its own.

If you don't want it to speak at all, use `max_asks=0`: questions are declined outright
(`state="over_budget"`), again without blocking. Note this is **not** "removing the tool" —
`allowed_tools` is not exclusive; the moment a `channel` is attached the
[coordinator](../reference/glossary.md#协调者) gets both `mcp__human__ask` and
`mcp__human__inbox`, and can call them whether or not they are listed. The only things that can
block a question are the quota and the timeout.

!!! warning "Never let a question wait forever when unattended"
    `timeout_s=None` means "wait forever". With nobody watching, a single question can freeze a
    ten-hour run in place — with no error, no timeout, and nothing in the logs to distinguish it.
    Unattended has only two correct values: `0` (fall through immediately)
    or a finite number of seconds.

## What it actually does {#它实际做了什么}

### The shape of `Event` {#event-的形状}

```python
@dataclass
class Event:
    kind: EventKind                     # 15 values, see table below
    text: str = ""
    tool: str = ""                      # only set for tool_call
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # raw SDK object / Ask; touch it and you are bound back to the SDK
```

`str(ev)`: for `tool_call` it is `[tool name] summary`, otherwise `text`; when `text` is empty it
is `<kind>`.

### The 15 `EventKind`s {#15-个-eventkind}

| `kind` | Emitted by | When it appears | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | Model prose | the prose | `subagent`, `parent_tool_use_id?`, `context?` |
| `thinking` | `normalize()` | Thinking block | the thinking content | same as above |
| `prompt` | `normalize()` | **Input**: your prompt, the task brief handed to a subagent | the input text | same as above |
| `tool_call` | `normalize()` | Model initiates a tool call | summary (`file_path` / `command` / `pattern`, cut at 200 characters) | `id`, `input` + same as above; `tool` is the tool name |
| `tool_result` | `normalize()` | Tool returns | first 500 characters (empty when the content is not a string) | `tool_use_id`, `is_error` + same as above |
| `result` | `normalize()` | One SDK query ends | subtype | `session_id`, `cost_usd`, `num_turns`, `is_error` |
| `error` | `normalize()` | Synthetic message on a disconnect | the error text | `synthetic: True` |
| `reset` | `normalize()` | Compact boundary or session reset | `压缩(trigger) 167000 → 42000 tokens`; on session reset it is `conversation reset` | `trigger`, `pre_tokens`, `post_tokens`, `micro`, `subtype` (empty on session reset) |
| `system` | `normalize()` | Any other SDK system message | subtype | `data` passed through as-is |
| `task` | `normalize()` | Task progress message | the message class name | — |
| `unknown` | `normalize()` | Unrecognized message type | the class name | — |
| `ask` | `HumanChannel` | A question for the human, a question reaching an outcome, or the human speaking up | the question / what the human said | two identities, see below |
| `retry` | `Runtime` | Retrying / waiting on the network | one line of explanation | `step`, `attempt` |
| `step` | `Workflow.run` | Step boundary | step name | `index`, `total`, `resumed`, `woke` |
| `handoff` | `Runtime` | Handoff: approaching / writing / done | one line including the level | `phase`, `step`, `context`, `window` + see below |

**Four kinds are not produced by `normalize()`**: `ask` comes from `HumanChannel`, `retry` and
`handoff` from `Runtime`, `step` from `Workflow.run`. Putting them in the same `EventKind` is
deliberate — **the UI knows one `Event` type and needs no separate path for "a question for the
human" or "a step boundary".**

Leave an `else` branch when writing a UI. `EventKind` will gain new members, and an older UI
should not crash because of it.

### The three `handoff` phases {#handoff-的三个-phase}

| `phase` | When it fires | Extra `payload` |
|---|---|---|
| `near` | The level passed `warn_at`. **Once per generation**, no spam | `at` (the handoff threshold) |
| `writing` | Starting to write the [handoff document](../reference/glossary.md#交接书). It takes a dozen-odd seconds; without this event the UI looks stuck | — |
| `done` | Handoff written, new session started | `degraded` (whether it is the degraded version), `path` (where it was written; empty string when there is no workbench), `sections` |

For the mechanism itself see [handoff](handoff.md).

### The two identities of `ask` {#ask-的两种身份}

`Event("ask")` carries both "a question" and "something the human said", so the **UI must check
`payload["kind"]` first**:

| Identity | How to tell | `payload` |
|---|---|---|
| A question | no `kind` key | `id`, `options`, `state`, `answer`, `remaining`, `asked_at`; `raw` is the `Ask` |
| The human speaking up | `payload["kind"] == "mail"` | `kind`, `state` (`queued` on the way in / `delivered` once taken), `id`, `amended` (which file it was appended to; empty string if unconfigured). **No `options` and no `remaining`** |

A single question emits **at least two** events: one when asked (`state="asked"`), and one when it
reaches an outcome (`answered` / `timeout` / `declined` / `over_budget` / `invalid`). The UI can
just update the same entry keyed by `payload["id"]`.

### Asking a human: `Ask` and `HumanChannel` {#问人ask-与-humanchannel}

```python
@dataclass
class Ask:
    id: str                                             # "q1", "q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # the five outcomes above
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # seconds waited, one decimal place
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` is an in-process MCP server plus a set of methods for the UI. The model side sees
only two tools: `mcp__human__ask` (ask, and block waiting) and `mcp__human__inbox` (check the
inbox, **non-blocking**; when empty it returns a note immediately). The full constructor:

```python
HumanChannel(
    *,                                  # all keyword-only
    on_event=None,                      # push sink. Workflow only wires it automatically when this is None
    max_asks=None,                      # None = unlimited; 0 = asking not allowed. Over quota is declined immediately, no blocking
    timeout_s=1800.0,                   # None = wait forever; <= 0 = fall through immediately
    log_path=None,                      # the Q&A is appended to this file, costing no context
    amend_path=None,                    # what the human says mid-run is appended to this file, usually the brief
    over_budget_text=OVER_BUDGET,       # three fixed replies, replaceable with your own
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` is the easiest one to miss, and it decides whether requirement changes made mid-run
survive a step boundary. Every step is a new [session](../reference/glossary.md#会话) over a
read-only frozen snapshot: what you say during the run only enters the context of the agent
running at the time. The next step (a [verdict](../reference/glossary.md#判定), say) is a brand new
session reading `需求.md` and `目标.md`, and **cannot see what you said** — so it judges against the
old boundary and rules the corrected work out of scope. `amend_path` **appends** every message
into the [brief](../reference/glossary.md#需求确认书) — appends, not overwrites; the original
requirement is history, and seeing what changed beats not seeing it. `starter_flow` wires it to
`<workbench>/notes/需求.md` by default.

Measured ($0.6767), this works even better than expected: the human said "report the total byte
count while you're at it", and after checking the inbox the coordinator reported —
"hand already read it from the run-time addendum in `.flower/notes/需求.md` and computed it, no need
to dispatch again." **The subagent read it from the file, not from anyone relaying it.**

Public members:

| Member | Signature | Semantics |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | Pass straight to `AgentSpec.mcp_servers`. The key must match the server name, which is why it hands both out together |
| `ask` | `async (question, options=None) -> Ask` | Block waiting on the human. **Never raises except `CancelledError`** — no answer is also an answer, distinguish via `ask.state` |
| `pending` | `() -> list[Ask]` | Questions currently waiting for an answer |
| `next_ask` | `async (timeout=None) -> Ask \| None` | For pull-style UIs. Returns `None` on timeout, raises if cancelled |
| `answer` | `(ask_id, text) -> bool` | Answer. `False` = this question is no longer waiting (timed out / already answered) |
| `decline` | `(ask_id, reason="") -> bool` | Skip; let the model judge for itself and write the assumption into "Unknowns and Assumptions" |
| `send` | `(text) -> Mail \| None` | The human speaks up, into the inbox. Does not interrupt the agent; internally calls `amend()` |
| `amend` | `(text, *, label="运行中补充") -> bool` | Append to `amend_path`. Returns whether it actually wrote (no path configured / empty text / `OSError` all give `False`) |
| `pending_mail` | `() -> list[Mail]` | Messages not yet taken |
| `remaining` | `-> int` | How many questions are left. With `max_asks=None` it returns **`-1`**, not 0 |
| `transcript` | `() -> str` | The Q&A record as markdown |
| `asks` / `mail` / `ui_errors` | `list` | All questions / everything the human said / exceptions raised by UI callbacks |

`answer`, `decline` and `send` **may be called from any thread**. A web backend's request handler
thread and a TUI's input thread are both other threads — that is the normal case, not an edge
case. Internally it goes through `loop.call_soon_threadsafe`, because `asyncio.Future.set_result`
is not thread-safe.

Push and pull: **pick one**:

| | How you get it | Suits |
|---|---|---|
| **Push** | `HumanChannel(on_event=…)`, react to `kind == "ask"` with `payload["state"] == "asked"` | Event-driven UIs (web push, TUI redraw) |
| **Pull** | `await channel.next_ask()` | A separate input task |

Three "0 / None" semantics that differ from each other; mixing them up means either a deadlock
when unattended or not a single question asked:

| Written as | Meaning |
|---|---|
| `max_asks=None` | Unlimited (default) |
| `max_asks=0` | Asking not allowed, declined outright |
| `timeout_s=None` | Wait forever |
| `timeout_s<=0` | Don't wait, the question falls through immediately |
| `remaining` returns `-1` | The value when `max_asks=None`, not 0 |

### Interrupts: any thread can call a halt {#打断任何线程都能喊停}

`rt.interrupt("别改 Makefile,那两行直接改")`; an empty string means interrupt without saying
anything. Three properties:

- **It resumes the same session** (`resume`), it does not start over — the work already done and
  the context are still there. It reuses the existing path built for network-failure retries,
  merely swapping "failure reason" for "the human interrupted" and `resume_prompt` for what the
  human said.
- **It does not consume `max_attempts`.** That quota is for faults, not for people.
- **It is cooperative**: it breaks at a message boundary and does not hard-cancel the task. The
  price is a delay until the next message (if a subagent is running you wait for it to come back);
  what you get is that state is never torn apart mid-way.

Being honest about the cost: an interrupt makes a **subagent in flight lose its half-finished
work** (measured during the HT001 disconnect, see
[issue #2](https://github.com/ChenyuHeee/flower/issues/2)). The terminal reference implementation
spells this out in its prompt so people know before they press the key; your own UI should do the
same.

If you don't want to interrupt but just want to add a requirement, use the inbox (`ch.send(...)`)
— it interrupts nothing, and the delay is until the agent's next checkpoint.

### The oracle: asking a question without disturbing the run {#旁路顾问问一句而不打扰运行}

To find out "where are we now", you don't need to interrupt, and you shouldn't ask the
coordinator: that exchange would **permanently occupy main thread context** (which holds
decisions, not Q&A records), and it would have to stop what it is doing. Over a ten-hour run,
casually asking three questions pays both costs.

The [oracle](../reference/glossary.md#旁路顾问) is a read-only side channel. Its only tools are
`Read` / `Glob` / `Grep`, it has the workbench, and it comes with a default brake:
`max_turns=12`, `max_budget_usd=0.5`. In the terminal it is triggered by a line starting with `?`,
and it answers from two things: the recent event window (a fixed 60 entries) and the brief, goal,
notes and artifacts in the workbench. It uses its own `Runtime` (`<run_dir>/aside`), so its cost
and session [lineage](../reference/glossary.md#血缘) **do not mix into the main manifest** — that
manifest records "which steps this run performed", and a passing question is not a step.

Measured: two questions for $0.5190 in total, and the main run's manifest did not grow by a single
byte.

### Two hard rules {#两条硬规矩}

!!! warning "on_event must neither block nor let exceptions escape"
    **One: `on_event` is a synchronous function, called on the event loop's thread.** So
    `asyncio.Queue.put_nowait()` is safe, `await` is not (it is not a coroutine), and **blocking
    it blocks the entire run**. For slow work, drop it in a queue and let another task do it.

    **Two: raising inside `on_event` damages the run itself.** Prose-class events are emitted
    inside the `try` block of `Runtime._attempt`, where the exception is recorded as
    `result.error` — that step is then judged a failure; `retry` events are emitted outside it, so
    the exception propagates straight out of `Runtime.run`. A frontend should not take down three
    hours of work — **wrap your own callback in a try**.

    Exception: the `ask` events emitted by `HumanChannel` itself are already wrapped; exceptions
    are collected into `channel.ui_errors` and do not interrupt the run.

## When not to use it {#什么时候不该用它}

### What not to do in the interaction layer {#交互层里不该做的事}

| Don't | Why | Do instead |
|---|---|---|
| `from claude_agent_sdk import ...` | Once the interaction layer depends on SDK types, every SDK upgrade drags the frontend along and this layer was for nothing | Use only `Event`'s `kind` / `text` / `tool` / `payload` |
| Read `ev.raw` | Same as above, plus it is not JSON-serializable | Whatever detail is missing, add it to `payload` in `normalize()`; don't bypass the boundary |
| `await`, make network calls, or write to slow disk inside `on_event` | It is synchronous and called on the event loop thread; blocking it blocks the entire run | `put_nowait()` into a queue, consume it in another task |
| Let `on_event` raise | An exception on a prose event becomes `result.error` and the step is judged failed | Wrap the whole callback body in `try` |
| Use `disallowed_tools` to turn off asking | It is **session-level** and disables the same-named tool for subagents too (measured error text: `"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` or `timeout_s=0` |
| Remove `mcp__human__ask` from `allowed_tools` as a way to forbid asking | `allowed_tools` is not exclusive; it is a no-approval list, not a whitelist. Attaching a `channel` hands over both tools | Same as above |
| Assemble your own path to find `需求.md` / `目标.md` | The workbench has two possible locations; getting it wrong raises no error, it just silently does nothing | `wake_state()` or `wf.workbench` |
| Assemble progress and results out of the `Event` stream | Prose gets chopped into several pieces by handoffs and retries | `on_step(step, result)` gives you the full `StepResult` |
| `timeout_s=None` when unattended | With nobody to answer, the run hangs forever, with no error and no timeout | `0`, or a finite number of seconds |

### When you don't need to swap it at all {#什么时候根本不用换}

- **You just want different colours, or one more/one fewer printed line** — change the render
  function. The interrupts, oracle, inbox receipts, SIGHUP / SIGTERM rescue and waiting for the
  side channel to finish before exit in the terminal reference implementation are not cheap to
  rewrite.
- **You just want to run one step with no interaction** — use `flower once`. It does not go
  through the interactive driver at all, so it has no Ctrl+C interrupt, no stdin answering thread,
  no oracle and no signal rescue.
- **What you actually want to change is the workflow, not the UI** — see
  [designing a workflow](workflow.md). The interaction layer only decides who watches and who
  answers; how many steps run, how they are judged and when to exit early is `Workflow`.
- **What you want to change is the session store, the model or the budget** — none of those sit on
  this boundary, see the [Python API reference](../reference/api.md).
