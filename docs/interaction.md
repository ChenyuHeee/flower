# 换掉交互层

> 框架层不知道 UI 存在。所有对外的动静都压平成一种数据结构 —— `Event`。
> 换终端为 Web / TUI / HTTP 服务 / 全自动无人值守,换的是 `Event` 的消费者。

```python
async for ...:                      # Runtime / Workflow 的 on_event 回调
    await ws.send_json({"kind": ev.kind, "text": ev.text, "tool": ev.tool})
```

---

## 为什么有这一层

SDK 的消息流是**内部类型**(`AssistantMessage`、`ToolUseBlock`、`ResultMessage`…)。
UI 直接依赖它们的话,SDK 一升级前端就得跟着改;而且每种消息的形状不一样,
每个 UI 都得重写一遍"这是正文还是工具调用"的判断。

`normalize()` 把消息流压平成一组稳定的 `Event`,UI 只认 `Event`。代价是一次转换,
换来的是:**UI 层一行 SDK 的 import 都没有**。

这一层还顺手解决了三件不那么显然的事:

1. **subagent 的发言被标出来**(`payload["subagent"]`)。否则派活的任务书和 subagent 的
   中间发言会混进主线程正文,再顺着 workflow 污染下一步的 prompt。
2. **断线时的合成错误消息被分流成 `kind="error"`**。harness 会把 `API Error: ...`
   当成一条 assistant 消息写进 transcript,它长得像模型说的话(`model` 是 `"<synthetic>"`)。
   不在这里拦掉,它就进了 `StepResult.text`。
3. **压缩边界被显式报出来**(`kind="reset"`)。边界之后模型"记得"的只有摘要,
   prompt 缓存也从这里断开 —— 长程运行必须能看见它。

## `Event`

```python
@dataclass
class Event:
    kind: EventKind          # 见下表
    text: str = ""
    tool: str = ""           # 只有 tool_call 有
    payload: dict = {}
    raw: Any = None          # 原始 SDK 对象 / Ask。要细节时才碰,碰了就绑定了 SDK
```

| `kind` | 什么时候出现 | `text` | `payload` |
|---|---|---|---|
| `text` | 模型正文 | 正文 | `subagent: bool`,`parent_tool_use_id?` |
| `prompt` | **输入**:你的 prompt、派给 subagent 的任务书 | 输入文本 | 同上 |
| `thinking` | 思考块 | 思考内容 | 同上 |
| `tool_call` | 模型发起工具调用 | 摘要(`file_path`/`command`/`pattern`,≤200 字符) | `id`,`input` + 同上;`tool` = 工具名 |
| `tool_result` | 工具返回 | 前 500 字符 | `tool_use_id`,`is_error` + 同上 |
| `ask` | **要人回答**,或某次提问有了结局 | 问题 | `id`,`options`,`state`,`answer`,`remaining`,`asked_at`;`raw` 是 `Ask` |
| `result` | 一次运行结束 | subtype | `session_id`,`cost_usd`,`num_turns`,`is_error` |
| `error` | 断线时的合成消息 | 错误文本 | `synthetic: True` |
| `retry` | 正在重试 / 挂着等网络 | 一句说明 | `step`,`attempt` |
| `reset` | 压缩边界或会话重置 | `压缩(trigger) 167000 → 42000 tokens` | `trigger`,`pre_tokens`,`post_tokens`,`micro`,`subtype` |
| `system` | SDK 系统消息 | subtype | 原样透传 |
| `task` | 任务进度消息 | 消息类名 | — |
| `unknown` | 没认出来的消息类型 | 类名 | — |

两个 kind **不由 `normalize()` 产生**:`ask` 来自 `HumanChannel`,`retry` 来自 `Runtime`。
放在同一个 `EventKind` 里是有意的 —— **UI 只认一套 `Event`,不必为"要人回答"另开一条路**。

> 写 UI 时留一个 `else` 分支。`EventKind` 会加新成员,老 UI 不该因此崩掉。

## 事件从哪来

三个出口,同一种 `Event`:

```python
# 1. 单个 agent
await rt.run(spec, "…", on_event=render)

# 2. 整个 workflow(它会把 on_event 转交给每一步)
await wf.run(rt, on_event=render, on_step=lambda step, result: ...)

# 3. 提问通道 —— 挂在 Workflow 上时自动接到同一个出口
wf = Workflow(channel=ch, steps=[...])
```

第三条的接法在 `Workflow.run` 里:**只有 `channel.on_event` 还是 `None` 时才自动接**。
自己接过就不会被覆盖:

```python
ch = HumanChannel(on_event=my_own_sink)   # 自己接,Workflow 不动它
```

`on_step(step, result)` 是另一个回调,每步跑完(**含失败**)调一次,拿到的是完整的
`StepResult` —— 进度条、落盘、报警挂这里,不要为了这个去 `Event` 流里拼。

### 两条硬规矩

**一、`on_event` 是同步函数,而且在事件循环所在的线程里被调用。**
所以 `asyncio.Queue.put_nowait()` 安全,`await` 不行(它不是协程),
**阻塞它就是阻塞整次运行**。要做慢活就丢进队列,让另一个任务去做。

**二、`on_event` 里抛异常会伤到运行本身。**
正文类事件在 `Runtime._attempt` 的 try 块里发出,异常被记成 `result.error` ——
这一步就判失败了;`retry` 事件在那之外发出,异常直接冒出 `Runtime.run`。
前端不该带走三小时的活 —— **自己包一层 try**:

```python
def render(ev):
    try:
        ...
    except Exception as exc:
        log.warning("UI 出错但不影响运行: %s", exc)
```

(例外:`HumanChannel` 自己发的 `ask` 事件已经包过了,异常收进 `channel.ui_errors`。)

## 怎么回答提问

`ask` 事件只是**通知**。回答走 `HumanChannel`,两种取法选一种:

| | 怎么拿 | 适合 |
|---|---|---|
| **推** | `on_event` 收到 `kind == "ask"` 且 `payload["state"] == "asked"` | 事件驱动的 UI(Web 推送、TUI 重绘) |
| **拉** | `await channel.next_ask()` | 一个独立的输入任务 |

## 人主动说话:`?` 旁路提问

标准输入**一直在读**(不只在有提问时读)。按状态和前缀路由:

```
有待答提问   → 这一行是答案
? 开头       → 旁路提问 —— 起一条只读 session 去答,**不打扰正在跑的活**
其它         → 收件箱(还没做,见 issue #3)
```

旁路问答(`cli.ask_aside`)拿两样东西作答:**最近的事件窗口**(`cli.Recent`,
固定长度,答"刚刚在干嘛"靠它)和**工作台**(确认书/目标/笔记/产出,答来龙去脉靠它)。
它用独立的 `Runtime`(`<run_dir>/aside`),所以花费和 session 血缘
**不会混进主 manifest** —— 那份清单记的是"这次运行做了哪些步骤",顺口问一句不是一个步骤。

为什么不让协调者来答:那段问答会**永久占住主上下文**(它装的是决策,不是问答记录),
而且它得停下手里的活。对一次十小时的运行,顺手问三句就把这两样代价都付了。

实测两问共 $0.5190,主运行的 manifest 一个字节都没多。角色见 `roles.oracle`。

## 人主动说话:收件箱

无前缀的输入进**收件箱**(`HumanChannel.send`),协调者用非阻塞的
`mcp__human__inbox` 取走。不打断在飞的活,延迟是它下一个检查点
(`COORDINATOR_RULES` 要求每次派活回来查一次)。

**改变需求的话必须落盘,否则活不过步骤边界。** 每一步是新 session、只读冻结件 ——
你在"干活"中途说的话只进了协调者的上下文,下一步(比如判定)是全新 session,
读的是 `需求.md`,**看不见你说过什么**,于是仍按旧边界判。

所以 `HumanChannel(amend_path=...)` 把每条消息**追加**进确认书(追加不覆盖,
和 `Goal.amend` 同一个道理)。`starter_flow` 默认接的就是 `需求.md`。

实测($0.6767)这条落盘比预期还管用:人说"顺便报告总字节数",协调者查收件箱看到后
报告说 —— "hand 已经从 `.flower/notes/需求.md` 的运行中补充里读到并算了,
不用再派一次"。**subagent 是从文件里读到的,不靠谁转述。**

### 协调者因此也能提问

`coordinator(channel=...)` 挂上 MCP server 就是 `inbox` 和 `ask` **两个工具一起给** ——
`allowed_tools` 不排他(见 [case-ht002.md](case-ht002.md) 第三节),列不列都调得动。
与其假装限制了,不如明说并在纪律里管住用法:真正的岔路口才问、不要把人当搜索引擎、
无人值守时每问一次会卡满 `timeout_s`(那种场合用 `--timeout 0`)。

HT002 里"业务代码别动 —— 那三行可移植性修复算不算"就是典型的该问而没问,
绕了一小时(见 [case-ht002.md](case-ht002.md) 第一节)。

## 打断:Ctrl+C

```
^C
⚠ 已打断这一轮。正在跑的 subagent 会丢掉半成品。
  要说什么?(直接回车 = 什么都不说,接着跑;再按一次 Ctrl+C = 退出)
> 别改 Makefile,那两行直接改
⟳ 已打断,带着你的话续跑
```

**为什么是 Ctrl+C 而不是某个前缀**:在此之前 Ctrl+C 直接杀进程 ——
一次十小时的运行会被肌肉记忆干掉,那比"没有打断功能"更糟。而前缀还要求你
**在想清楚要打断之前**就先按对键。

三条性质:

- **续跑同一个 session**(`resume`),不是重头来 —— 已经干完的活和上下文都在。
  复用的是断网重试那条现成的路,只是把"失败原因"换成"人打断了"、
  把 `resume_prompt` 换成人说的话。
- **不消耗 `max_attempts`** —— 那是给故障的额度,不是给人的。
- **协作式**:在消息边界断开,不硬取消任务。代价是延迟到下一条消息
  (subagent 正跑着的话要等它回来),换来的是不会在半路撕裂状态。

代价照实说:打断会让**在飞的 subagent 丢掉半成品**(HT001 断网那次实测过,
见 [issue #2](https://github.com/ChenyuHeee/flower/issues/2))。所以提示里写明了,
让人在按之前知道。

不想打断、只是加个要求的话用收件箱(直接说,不按 Ctrl+C)——
它不打断任何东西,延迟是下一个检查点。

回答:

```python
channel.answer(ask_id, "纯命令行")     # 返回 False = 这个提问已经不在等了(超时/已答)
channel.decline(ask_id)               # 跳过,让它自己判断并把假设写进「未知与假设」
channel.pending()                     # 当前在等答案的 Ask 列表
```

**可以从任意线程调。** Web 后端的请求处理线程、TUI 的输入线程都在别的线程里 ——
这是常态,不是边缘情况。内部走 `loop.call_soon_threadsafe`,
因为 `asyncio.Future.set_result` 不是线程安全的。

`ask` 事件会发**两次以上**:提问时一次(`state="asked"`),有结局时再一次
(`answered` / `timeout` / `declined` / `over_budget` / `invalid`)。
UI 按 `payload["id"]` 更新同一条即可。

## 三个形状

### 终端:daemon 线程读标准输入

`cli.py` 的完整做法(约 200 行,可整体替换)。要点只有一个:

```python
threading.Thread(target=loop, daemon=True).start()    # ← 不是 asyncio.to_thread
```

**别用 `asyncio.to_thread(input, ...)`**:`input()` 阻塞时取消不掉,而 `asyncio.run`
退出前会 join 默认执行器的线程 —— 结果是活干完了还得**再按一次回车**才能退出。
daemon 线程不挡退出。

### Web:队列 + WebSocket

```python
events: asyncio.Queue[dict] = asyncio.Queue()

def sink(ev):                              # 同步、在循环线程里、不能阻塞
    try:
        events.put_nowait({"kind": ev.kind, "text": ev.text, "tool": ev.tool,
                           "payload": ev.payload})     # 注意:别塞 ev.raw,它不可序列化
    except Exception:
        pass

async def pump(ws):
    while True:
        await ws.send_json(await events.get())

# 浏览器把答案 POST 回来 —— 哪个线程都行
@app.post("/answer")
def answer(ask_id: str, text: str):
    return {"ok": ch.answer(ask_id, text)}
```

`ev.raw` 是原始 SDK 对象(`ask` 事件里是 `Ask`),**不可 JSON 序列化**。
UI 只用 `kind` / `text` / `tool` / `payload` 就够了 —— 用到 `raw` 就等于把前端
绑回了 SDK 类型,这一层就白做了。

### 全自动:没有 UI

```python
ch = HumanChannel(timeout_s=0, log_path="notes/问答记录.md")   # 提问立刻落空
ctx = await wf.run(rt, on_event=None)                          # 事件全丢弃
```

`timeout_s=0` 是**全自动模式**:所有提问立刻返回"无人应答,自己判断,把假设写进
「未知与假设」",不假装等。问答仍然会追加到 `log_path`,事后能看它问过什么、
自己假设了什么。这就是无人值守时长程运行不会卡死的原因。

## 写一个自己的驱动

`cli.py` 不是框架的一部分,是参考实现。一个最小驱动就这么多:

```python
import asyncio
from flower import Runtime
from flower.core.env import load_dotenv

async def main():
    load_dotenv()                       # 凭证:进程环境 > 仓库根 .env
    wf = build_workflow()               # 你的 flows.py
    rt = Runtime(workspace="/path/to/repo", run_dir="runs", workbench=True)
    try:
        if wf.channel is not None:
            start_answering(wf.channel)         # 你的回答通道
        ctx = await wf.run(rt, on_event=your_sink)
    finally:
        rt.close()                              # 关 SQLite
    print(rt.total_cost(), ctx.get("_failed_at"))

asyncio.run(main())
```

三件容易漏的收尾:

- `rt.close()` 放 `finally` —— 它关的是 SQLite 连接
- `ctx["_failed_at"]` 有值说明中途停了(`on_fail="stop"`),别当成功
- 回答用的线程要能被停掉(`cli.py` 用一个 `threading.Event` 做停止位)
