# 换交互层

flower 的核心不知道 UI 存在。运行里发生的每一件事——模型说话、调工具、上下文快满了、要问人一句
——都被压平成同一种数据结构 [`Event`](../reference/glossary.md#事件)。
**[交互层](../reference/glossary.md#交互层)只认 `Event`,不 import 任何 SDK 类型。**
这是换 UI 不用动核心的那条边界:终端、Web、HTTP 服务、全自动无人值守,换掉的是 `Event`
的消费者,别的一行都不用改。

## 解决什么问题

SDK 的消息流是**内部类型**:`AssistantMessage`、`ToolUseBlock`、`ToolResultBlock`、
`ResultMessage`、`SystemMessage`……UI 直接消费它们有两个后果:SDK 一升级前端就得跟着改;
每种消息形状不一样,每个 UI 都要重写一遍"这是正文还是工具调用"的判断。

`normalize(message)` 把一条 SDK 消息转成 0 到 N 个 `Event`
([`core/events.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/events.py))。
代价是一次转换,换来的是交互层和 SDK 之间没有类型依赖。

这条边界还顺手解决了四件不那么显然的事,四件都在 `normalize()` 里:

1. **[subagent](../reference/glossary.md#subagent) 的发言被标出来**(`payload["subagent"]`)。
   否则派活的[任务书](../reference/glossary.md#任务书)和 subagent 的中间发言会混进
   [主线程](../reference/glossary.md#主线程)正文,再顺着[流程](../reference/glossary.md#流程)
   污染下一步的 prompt。
2. **断线时的合成错误消息被分流成 `kind="error"`**。断线时 SDK 侧会把 `API Error: …`
   当成一条 assistant 消息写进 transcript,它长得像模型说的话(`model` 是 `"<synthetic>"`)。
   不在这里拦掉,它就进了 `StepResult.text`,再传给下一个[步骤](../reference/glossary.md#步骤)。
3. **压缩边界被显式报出来**(`kind="reset"`)。边界之后模型"记得"的只有摘要,prompt 缓存
   也从这里断开——[长程](../reference/glossary.md#长程)运行必须能看见它。
4. **上下文水位跟着每条消息出来**(`payload["context"]` = `input_tokens` +
   `cache_read_input_tokens` + `cache_creation_input_tokens`)。它是
   [换代](../reference/glossary.md#换代)判据的唯一来源。

## 怎么用(最小代码)

一个交互层要接三样东西:**事件出口**(往哪渲染)、**提问通道**(谁来答)、**打断**(怎么喊停)。
下面这段全接上了,可以直接跑:

```python
import asyncio

from flower import Event, HumanChannel, Runtime, starter_flow


def sink(ev: Event) -> None:
    """把 Event 渲染成你自己的 UI —— 这是唯一需要换的东西。"""
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
    # kind == "ask" 且不是 mail 的,交给下面的 answerer 处理(拉式)


async def answerer(ch: HumanChannel) -> None:
    """拉式取提问。换成 Web / HTTP 时,这个协程是另一处要改的地方。"""
    while True:
        ask = await ch.next_ask()           # 不给 timeout 就一直等
        if ask is None:
            continue
        print(f"\n?? {ask.question} 选项={ask.options}")
        ch.answer(ask.id, "按你的判断来")     # 或 ch.decline(ask.id, "先跳过")


async def main() -> None:
    wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=60)
    # Runtime 用 workflow 自己建好的工作台 —— 别另拼一个
    rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
    task = asyncio.create_task(answerer(wf.channel))
    try:
        ctx = await wf.run(rt, on_event=sink)
    finally:
        task.cancel()
        rt.close()                          # 关 SQLite 连接
    print(rt.total_cost(), ctx.get("_failed_at"))


asyncio.run(main())
```

两件容易漏的收尾:`rt.close()` 一定放 `finally`;`ctx["_failed_at"]` 有值说明中途停了
(`on_fail="stop"`),别当成功。

!!! note "工作台只有一个,别另拼一个"
    `Runtime(workbench=True)` 建的[工作台](../reference/glossary.md#工作台)在
    `<run_dir>/workbench`,而 `Workbench(ws)` 默认在 `<ws>/.flower` ——
    两个不是同一个目录。驱动程序自己拼路径去找 `需求.md`,会出现
    "确认书写进 A 目录、注入的索引扫的是 B 目录"而且不报错。
    要么把 workflow 建好的那个交给 `Runtime`(上面的写法),
    要么用只读探测 `wake_state()` 问它在哪。

### 三个事件出口

```python
await rt.run(spec, "…", on_event=sink)                  # 1. 单个 agent
await wf.run(rt, on_event=sink, on_step=progress)       # 2. 整个流程,转交给每一步
wf = Workflow(steps=[...], channel=ch)                  # 3. 提问通道,接到同一个出口
```

第三条的接法在 `Workflow.run` 里:**只有 `on_event` 非 `None`、且 `channel.on_event` 还是
`None` 时才自动接**。自己接过就不会被覆盖:

```python
ch = HumanChannel(on_event=my_own_sink)     # 自己接,Workflow 不动它
```

`on_step(step, result)` 是另一条回调,每步跑完(**含失败**)调一次,拿到的是完整的
`StepResult`。进度条、写盘、报警挂这里,不要为了这个去 `Event` 流里拼——正文会被换代和
重试打断成好几段。

### 终端:默认的那个

不写代码也有一个。`flower "帮我做一个 X"` 走的是
[`flower/cli.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/cli.py),
它是交互层的**参考实现,不是框架的一部分**,可以整份换掉;开关见 [CLI 参考](../reference/cli.md)。
照实说规模。整份 `cli.py` 是 1264 行、57KB —— 但**要换的不是整份**。
真正的替换点是里面的 `class Render`(`cli.py:382-578`,197 行),它的 docstring 就写着
"Event → 终端。换 UI 就是换这一个类。"其余一千多行是打断、旁路顾问、收件箱回执、
信号抢救这些**终端特有**的配套,换成 Web 或 HTTP 时本来就不需要照搬。

所以"约 200 行可整体替换"这个说法成立 —— 前提是它指 `Render`,不是指 `cli.py`。

自己写终端 UI,要点是读标准输入的那个线程:

```python
import select
import sys
import threading


def start_input(ch: HumanChannel) -> threading.Event:
    """一直读标准输入:有待答提问就是答案,否则进收件箱。返回停止位。"""
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue                        # 轮询,才能响应停止位
            line = sys.stdin.readline()
            if not line:                        # EOF
                return
            raw = line.strip()
            if not raw:
                continue
            pend = ch.pending()
            if pend:
                ch.answer(pend[0].id, raw)      # 跨线程安全
            else:
                ch.send(raw)                    # 进收件箱,不打断在飞的活

    threading.Thread(target=loop, daemon=True, name="stdin").start()
    return stop
```

三条都是踩出来的:

- **用 daemon 线程,不用 `asyncio.to_thread(input, ...)`。** `input()` 阻塞时取消不掉,而
  `asyncio.run` 退出前要 join 默认执行器的线程——结果是活干完了还得再按一次回车才能退出。
- **用 `select` 轮询,不在循环里直接 `input()`。** 同样是取消不掉:阻塞在 `input()` 上的线程,
  `stop.set()` 再也叫不醒。
- **一直读,不是只在有提问时读。** 只在有提问时读的话,干活那几小时里敲的东西留在终端缓冲里,
  下一次提问时会被当成答案吃掉——人还没看见问题,问题就被"回答"了。

### Web:队列 + WebSocket

```python
events: asyncio.Queue[dict] = asyncio.Queue()


def sink(ev: Event) -> None:            # 同步、在事件循环所在的线程里、不能阻塞
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text,
                           "tool": ev.tool, "payload": ev.payload})
    except Exception:                   # 前端出错不该带走三小时的活
        pass


async def pump(ws) -> None:
    while True:
        await ws.send_json(await events.get())


@app.post("/answer")                    # 请求处理线程 —— 别的线程,这是常态
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` 是原始 SDK 对象(`ask` 事件里是 `Ask`),**不可 JSON 序列化,也别往前端传** ——
用到 `raw` 就等于把前端绑回了 SDK 类型,这一层就白做了。`kind` / `text` / `tool` / `payload`
四个字段够用。

### HTTP:序号 + 轮询

没有长连接的时候,给事件编号让客户端拉:

```python
import itertools
from collections import deque

seq = itertools.count(1)
log: deque[dict] = deque(maxlen=2000)   # 只留最近的,内存不跟着运行时长涨


def sink(ev: Event) -> None:
    log.append({"seq": next(seq), "kind": ev.kind, "text": ev.text,
                "tool": ev.tool, "payload": ev.payload})


@app.get("/events")                     # GET /events?after=128
def events(after: int = 0) -> list[dict]:
    return [e for e in log if e["seq"] > after]


@app.get("/asks")                       # 现在挂着等谁回答
def asks() -> list[dict]:
    return [{"id": a.id, "question": a.question, "options": a.options,
             "waited_s": a.waited_s} for a in ch.pending()]


@app.post("/answer")
def answer(ask_id: str, text: str) -> dict:
    return {"ok": ch.answer(ask_id, text)}      # False = 这个提问已经不在等了
```

两条边界要认:`maxlen` 满了会丢最旧的,客户端拿着很旧的 `after` 回来就查不全了,轮询间隔要
配得上这个长度;还有**必须给 `timeout_s` 一个有限值** —— 没人轮询的时候提问不会自己结束,
`timeout_s=None` 会把整次运行永远挂在那里。默认的 `1800.0` 秒是合适的。

### 全自动无人值守:没有人

```python
wf = starter_flow("帮我做一个 X", workspace=".", run_dir="runs", timeout_s=0)
rt = Runtime(workspace=".", run_dir="runs", workbench=wf.workbench)
ctx = await wf.run(rt, on_event=None)       # 事件全丢弃
```

命令行等价写法是 `flower "帮我做一个 X" --timeout 0`。

`timeout_s=0`(负数同理)是全自动模式:提问**不进等待队列、不发 `asked` 事件**,立刻结算成
`state="timeout"`,工具返回这句固定文案——

```text
无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。不要重复提问,也不要停在这里。
```

——于是运行照跑不误。问答仍然追加进 `HumanChannel(log_path=...)`(`starter_flow` 默认接的是
`<工作台>/notes/问答记录.md`),事后能看它问过什么、自己假设了什么。

不想让它开口就用 `max_asks=0`:提问直接被回绝(`state="over_budget"`),同样不阻塞。
注意这**不是**"把工具拿掉"——`allowed_tools` 不排他,
[协调者](../reference/glossary.md#协调者)一挂上 `channel` 就是 `mcp__human__ask` 和
`mcp__human__inbox` 两个工具一起给,列不列都调得动。能挡住提问的只有额度和超时。

!!! warning "无人值守时别让提问永远等"
    `timeout_s=None` 是"永远等"。没人看着的时候,一次提问就能让十小时的运行原地停住,
    而且不报错、不超时、日志上看不出区别。无人值守只有两个正确取值:`0`(立刻落空)
    或者一个有限秒数。

## 它实际做了什么

### `Event` 的形状

```python
@dataclass
class Event:
    kind: EventKind                     # 15 个取值,见下表
    text: str = ""
    tool: str = ""                      # 只有 tool_call 有值
    payload: dict[str, Any] = field(default_factory=dict)
    raw: Any = None                     # 原始 SDK 对象 / Ask,碰了就绑回了 SDK
```

`str(ev)`:`tool_call` 是 `[工具名] 摘要`,其余是 `text`;`text` 为空时是 `<kind>`。

### 15 个 `EventKind`

| `kind` | 谁发的 | 什么时候出现 | `text` | `payload` |
|---|---|---|---|---|
| `text` | `normalize()` | 模型正文 | 正文 | `subagent`、`parent_tool_use_id?`、`context?` |
| `thinking` | `normalize()` | 思考块 | 思考内容 | 同上 |
| `prompt` | `normalize()` | **输入**:你的 prompt、派给 subagent 的任务书 | 输入文本 | 同上 |
| `tool_call` | `normalize()` | 模型发起工具调用 | 摘要(`file_path` / `command` / `pattern`,截 200 字符) | `id`、`input` + 同上;`tool` 是工具名 |
| `tool_result` | `normalize()` | 工具返回 | 前 500 字符(内容不是字符串时为空) | `tool_use_id`、`is_error` + 同上 |
| `result` | `normalize()` | 一次 SDK 查询结束 | subtype | `session_id`、`cost_usd`、`num_turns`、`is_error` |
| `error` | `normalize()` | 断线时的合成消息 | 错误文本 | `synthetic: True` |
| `reset` | `normalize()` | 压缩边界或会话重置 | `压缩(trigger) 167000 → 42000 tokens`;会话重置时是 `conversation reset` | `trigger`、`pre_tokens`、`post_tokens`、`micro`、`subtype`(会话重置时为空) |
| `system` | `normalize()` | 其余 SDK 系统消息 | subtype | `data` 原样透传 |
| `task` | `normalize()` | 任务进度消息 | 消息类名 | — |
| `unknown` | `normalize()` | 没认出来的消息类型 | 类名 | — |
| `ask` | `HumanChannel` | 要人回答、某次提问有了结局,或者人主动说了句话 | 问题 / 人说的话 | 两种身份,见下 |
| `retry` | `Runtime` | 正在重试 / 挂着等网络 | 一句说明 | `step`、`attempt` |
| `step` | `Workflow.run` | 步骤边界 | 步骤名 | `index`、`total`、`resumed`、`woke` |
| `handoff` | `Runtime` | 换代:逼近 / 正在写 / 换完了 | 一句带水位的说明 | `phase`、`step`、`context`、`window` + 见下 |

**四个 kind 不由 `normalize()` 产生**:`ask` 来自 `HumanChannel`,`retry` 和 `handoff` 来自
`Runtime`,`step` 来自 `Workflow.run`。放在同一个 `EventKind` 里是有意的——
**UI 只认一套 `Event`,不必为"要人回答"或者"步骤边界"另开一条路。**

写 UI 时留一个 `else` 分支。`EventKind` 还会加新成员,老 UI 不该因此崩掉。

### `handoff` 的三个 phase

| `phase` | 什么时候发 | `payload` 额外带 |
|---|---|---|
| `near` | 水位过了 `warn_at`。**每代只发一次**,不刷屏 | `at`(换代阈值) |
| `writing` | 开始写[交接书](../reference/glossary.md#交接书)。写要十几秒,不发这一条界面看起来像卡住 | — |
| `done` | 交接写完、换新会话 | `degraded`(是不是降级版本)、`path`(写到哪,没有工作台时是空串)、`sections` |

机制本身见[换代](handoff.md)。

### `ask` 的两种身份

`Event("ask")` 同时承载"提问"和"人主动说的话",**UI 必须先看 `payload["kind"]`**:

| 身份 | 怎么认 | `payload` |
|---|---|---|
| 一次提问 | 没有 `kind` 键 | `id`、`options`、`state`、`answer`、`remaining`、`asked_at`;`raw` 是那个 `Ask` |
| 人主动说的话 | `payload["kind"] == "mail"` | `kind`、`state`(`queued` 放进去 / `delivered` 被取走)、`id`、`amended`(追加进了哪个文件,没配就是空串)。**没有 `options` 和 `remaining`** |

一次提问会发**两次以上**事件:提问时一次(`state="asked"`),有结局时再一次
(`answered` / `timeout` / `declined` / `over_budget` / `invalid`)。UI 按 `payload["id"]`
更新同一条即可。

### 问人:`Ask` 与 `HumanChannel`

```python
@dataclass
class Ask:
    id: str                                             # "q1"、"q2"…
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"                                # 见上面五种结局
    answer: str = ""

    @property
    def waited_s(self) -> float: ...                    # 等了多少秒,一位小数
    def event(self, remaining: int = 0) -> Event: ...
```

`HumanChannel` 是一个进程内 MCP server 加一组给 UI 用的方法。模型侧只看见两个工具:
`mcp__human__ask`(提问,会挂住等)和 `mcp__human__inbox`(查收件箱,**不阻塞**,空了就立刻
返回一句说明)。完整构造:

```python
HumanChannel(
    *,                                  # 全部 keyword-only
    on_event=None,                      # 推式出口。Workflow 只在它是 None 时才自动接
    max_asks=None,                      # None = 不限;0 = 不许问。超额直接回绝,不阻塞
    timeout_s=1800.0,                   # None = 永远等;<= 0 = 立刻落空
    log_path=None,                      # 问答追加进这个文件,不占上下文
    amend_path=None,                    # 人在运行途中说的话追加进这个文件,通常是需求确认书
    over_budget_text=OVER_BUDGET,       # 三句固定回复,可以换成自己的
    timeout_text=TIMEOUT,
    declined_text=DECLINED,
)
```

`amend_path` 是最容易漏的一个,而它决定了"人中途改的需求活不活得过步骤边界"。
每一步是新[会话](../reference/glossary.md#会话)、只读冻结件:运行途中说的话只进了当时那个
agent 的上下文,下一步(比如[判定](../reference/glossary.md#判定))是全新会话,读的是
`需求.md` 和 `目标.md`,**看不见你说过那句话**,于是仍按旧边界判,把改好的东西判成越界。
`amend_path` 把每条消息**追加**进[需求确认书](../reference/glossary.md#需求确认书)——追加
不覆盖,原来的需求是历史,看得见改了什么比看不见好。`starter_flow` 默认接的就是
`<工作台>/notes/需求.md`。

实测($0.6767)这条比预期还管用:人说"顺便报告总字节数",协调者查收件箱看到后报告说——
"hand 已经从 `.flower/notes/需求.md` 的运行中补充里读到并算了,不用再派一次"。
**subagent 是从文件里读到的,不靠谁转述。**

公开成员:

| 成员 | 签名 | 语义 |
|---|---|---|
| `tool_name` | `-> str` | `"mcp__human__ask"` |
| `inbox_name` | `-> str` | `"mcp__human__inbox"` |
| `mcp_servers` | `() -> dict` | 直接塞给 `AgentSpec.mcp_servers`。键名必须和 server 名一致,所以由它一起给出 |
| `ask` | `async (question, options=None) -> Ask` | 挂住等人。**除 `CancelledError` 外永不抛异常**——没人应答也是一种答案,用 `ask.state` 区分 |
| `pending` | `() -> list[Ask]` | 当前挂着等答的提问 |
| `next_ask` | `async (timeout=None) -> Ask \| None` | 拉式 UI 用。超时返回 `None`,被取消则抛 |
| `answer` | `(ask_id, text) -> bool` | 回答。`False` = 这个提问已经不在等了(超时 / 已答) |
| `decline` | `(ask_id, reason="") -> bool` | 跳过,让模型自己判断并把假设写进「未知与假设」 |
| `send` | `(text) -> Mail \| None` | 人主动说一句话,进收件箱。不打断 agent;内部自动调 `amend()` |
| `amend` | `(text, *, label="运行中补充") -> bool` | 追加进 `amend_path`。返回是否真写了(没配路径 / 空文本 / `OSError` 都是 `False`) |
| `pending_mail` | `() -> list[Mail]` | 还没被取走的话 |
| `remaining` | `-> int` | 还能问几次。`max_asks=None` 时返回 **`-1`**,不是 0 |
| `transcript` | `() -> str` | 问答记录的 markdown |
| `asks` / `mail` / `ui_errors` | `list` | 全部提问 / 全部人说的话 / UI 回调抛出的异常 |

`answer`、`decline`、`send` **可以从任意线程调**。Web 后端的请求处理线程、TUI 的输入线程都在
别的线程里——这是常态,不是边缘情况。内部走 `loop.call_soon_threadsafe`,因为
`asyncio.Future.set_result` 不是线程安全的。

推和拉两种取法**选一种**:

| | 怎么拿 | 适合 |
|---|---|---|
| **推** | `HumanChannel(on_event=…)`,收到 `kind == "ask"` 且 `payload["state"] == "asked"` | 事件驱动的 UI(Web 推送、TUI 重绘) |
| **拉** | `await channel.next_ask()` | 一个独立的输入任务 |

三个"0 / None"语义各不相同,记混了就是无人值守时挂死或者一句都不问:

| 写法 | 意思 |
|---|---|
| `max_asks=None` | 不限次数(默认) |
| `max_asks=0` | 不许提问,直接回绝 |
| `timeout_s=None` | 永远等 |
| `timeout_s<=0` | 不等,提问立刻落空 |
| `remaining` 返回 `-1` | `max_asks=None` 时的取值,不是 0 |

### 打断:任何线程都能喊停

`rt.interrupt("别改 Makefile,那两行直接改")`,空串就是只打断不说话。三条性质:

- **续跑同一个会话**(`resume`),不是重头来——已经干完的活和上下文都在。复用的是断网重试
  那条现成的路,只把"失败原因"换成"人打断了"、把 `resume_prompt` 换成人说的话。
- **不消耗 `max_attempts`**。那是给故障的额度,不是给人的。
- **协作式**:在消息边界断开,不硬取消任务。代价是延迟到下一条消息(subagent 正跑着的话要等
  它回来),换来的是不会在半路撕裂状态。

代价照实说:打断会让**在飞的 subagent 丢掉半成品**(HT001 断网那次实测过,见
[issue #2](https://github.com/ChenyuHeee/flower/issues/2))。终端参考实现在提示里写明了这一条,
让人在按之前就知道;自己写 UI 也该照做。

不想打断、只是想加个要求的话用收件箱(`ch.send(...)`)——它不打断任何东西,延迟是 agent 的
下一个检查点。

### 旁路顾问:问一句而不打扰运行

想知道"现在到哪了",不必打断,也不该问协调者:那段问答会**永久占住主线程上下文**
(它装的是决策,不是问答记录),而且它得停下手里的活。对一次十小时的运行,顺手问三句就把这
两样代价都付了。

[旁路顾问](../reference/glossary.md#旁路顾问)是一条只读旁路。它工具只有 `Read` / `Glob` /
`Grep`,开着工作台,默认带闸:`max_turns=12`、`max_budget_usd=0.5`。终端里用 `?` 开头的一行
触发,它拿两样东西作答:最近的事件窗口(固定 60 条)和工作台里的确认书、目标、笔记、产出。
它用独立的 `Runtime`(`<run_dir>/aside`),所以花费和会话[血缘](../reference/glossary.md#血缘)
**不会混进主 manifest**——那份清单记的是"这次运行做了哪些步骤",顺口问一句不是一个步骤。

实测两问共 $0.5190,主运行的 manifest 一个字节都没多。

### 两条硬规矩

!!! warning "on_event 既不能阻塞,也不能把异常放出来"
    **一、`on_event` 是同步函数,在事件循环所在的线程里被调用。** 所以
    `asyncio.Queue.put_nowait()` 安全,`await` 不行(它不是协程),**阻塞它就是阻塞整次运行**。
    要做慢活就丢进队列,让另一个任务去做。

    **二、`on_event` 里抛异常会伤到运行本身。** 正文类事件在 `Runtime._attempt` 的 `try` 块里
    发出,异常被记成 `result.error` —— 这一步就判失败了;`retry` 事件在那之外发出,异常直接
    冒出 `Runtime.run`。前端不该带走三小时的活,**自己包一层 try**。

    例外:`HumanChannel` 自己发的 `ask` 事件已经包过了,异常收进 `channel.ui_errors`,
    不中断运行。

## 什么时候不该用它

### 交互层里不该做的事

| 不该做 | 为什么 | 该怎么做 |
|---|---|---|
| `from claude_agent_sdk import ...` | 交互层一旦依赖 SDK 类型,SDK 升级前端就跟着改,这一层白做 | 只用 `Event` 的 `kind` / `text` / `tool` / `payload` |
| 读 `ev.raw` | 同上,而且它不可 JSON 序列化 | 缺什么细节,补进 `normalize()` 的 `payload`,不要绕过边界 |
| 在 `on_event` 里 `await`、发网络请求、写慢盘 | 它是同步的,在事件循环线程上调用,阻塞它就是阻塞整次运行 | `put_nowait()` 丢队列,另起任务消费 |
| 让 `on_event` 抛异常出去 | 正文事件的异常会变成 `result.error`,这一步判失败 | 回调体整个包 `try` |
| 用 `disallowed_tools` 关掉提问 | 它是**会话级**的,会把 subagent 的同名工具一起禁掉(实测报错原文:`"Bash is disabled for this session, in subagents as well as here"`) | `max_asks=0` 或 `timeout_s=0` |
| 从 `allowed_tools` 里拿掉 `mcp__human__ask` 当作禁止提问 | `allowed_tools` 不排他,是免审批清单不是白名单;挂上 `channel` 就是两个工具一起给 | 同上 |
| 自己拼路径去找 `需求.md` / `目标.md` | 工作台位置有两种,拼错了不报错,只是静默失效 | `wake_state()` 或 `wf.workbench` |
| 用 `Event` 流拼进度和结果 | 正文会被换代、重试打断成好几段 | `on_step(step, result)` 拿完整的 `StepResult` |
| 无人值守时用 `timeout_s=None` | 没人回答,运行永远挂着,不报错也不超时 | `0`,或者一个有限秒数 |

### 什么时候根本不用换

- **只想改颜色、多打一行少打一行** —— 改渲染函数就行。终端参考实现里的打断、旁路顾问、
  收件箱回执、SIGHUP / SIGTERM 抢救、退出前等旁路收尾,重写一遍代价不小。
- **只想跑一步、不要交互** —— 用 `flower once`。它不走交互驱动那条路,本来就没有 Ctrl+C 打断、
  标准输入应答线程、旁路顾问和信号抢救。
- **想换的其实是流程,不是 UI** —— 见[设计流程](workflow.md)。交互层只决定谁来看、谁来答;
  决定跑几步、怎么判、什么时候提前退出的是 `Workflow`。
- **想换的是会话存储、模型或者预算** —— 那三样都不在这条边界上,见
  [Python API 参考](../reference/api.md)。
