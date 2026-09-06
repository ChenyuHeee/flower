# 前置确认:先把需求问清楚,再开工

> 一个只提问、不动手的角色,问完输出一份**冻结的四段确认书**;下游从这份文书开局,
> 拿不到那段问答。

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md", max_asks=6, timeout_s=1800)
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=主控, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

---

## 为什么需要它

这套框架清理上下文的手段有四种 —— 时效过期、被拒调用摘除、错误消息摘除、大结果落盘 ——
清的都是**现场**。现场丢掉不要紧,重跑一次就有。

但有一类错误不是这样:**目标理解错了**。它是唯一一类**剪枝会让它变严重**的错误。
现场被丢掉之后,留下来的恰恰是那条建在错误前提上的决策,而且它**看起来和正确决策
一模一样** —— 没有任何痕迹表明它的前提可疑。

长程会把它放大到最坏:错误前提先跑几个小时、派十几个 subagent、在磁盘上落一堆产出,
之后才暴露。到那时贵的不是 token,是**每一个产出都是照错的需求建的**。

所以要有一个能"停下来问"的通道,而且它必须在开工**之前**。

## 结构规则:问答是现场,不是决策

澄清的来回问答和 subagent 的试错是同一性质的东西 —— 有价值的是结论,过程不该常驻。
所以处理方式也一样:**沉到磁盘,不进协调者的上下文**。

落地方式是三件事的组合,一个新机制都没加:

```
clarify 步骤          独立 session ──→ 磁盘上一份冻结的四段确认书
                                              │
下游第一步            新 session(resume_from=None)◄┘  只拿到确认书
```

于是那段问答**从来没进过**协调者的上下文 —— 不是"进去之后被剪掉"。差别是实质性的:
剪掉的东西在 SQLite 里还在、还可能被 resume 带回来;从没进过的东西不存在这个问题。

问答本身**追加到 `log_path`**。这一份不占上下文、不受压缩影响、换台机器也还在 ——
和工作台是同一个思路。

## 四段各挡一类失败

| 段 | 写什么 | 不写会怎样 |
|---|---|---|
| **目标** | 一句话:做什么,给谁用 | 做出来的是另一个东西 |
| **验收标准** | 可判定的条件,一条一行。"做好了"不算,"跑 `x` 输出 `y`"才算 | 没人能判定"做完了" |
| **边界** | **明确不做什么** | 范围蔓延。这一段管住后面**每一个** subagent |
| **未知与假设** | 没问到的、超时落空的、自己猜的,一条一行 | **错误前提被静默埋掉** |

第四段是长程运行的保险丝。前三段任何一段写错,只要假设显式写在第四段,后面的人读到
就有机会拦住;埋掉了就只能等几小时后产出全废时才发现。错误前提没法完全避免,
但可以让它**显式**。

四段齐全才放行 —— 缺哪一段由 `Brief.missing()` 报出来,`gate` 不让往下走。

## 两条"必须是机制,不能是提示词"

这不是洁癖,是实测出来的。跑过一个**不受约束**的确认者(`/tmp/probe_ask.py`,
$0.8908 / 230 秒):它问完两个问题**直接开始写代码**;被权限拦下之后,
**把整份代码贴进了回话正文**。

提示词里写"不要写代码"挡不住这个 —— 它当时的系统提示里就有类似的话。所以:

**一、工具白名单里没有写工具。** `clarify()` 只给 `mcp__human__ask` 加只读的
`Read`/`Glob`/`Grep`。**没有 Write / Edit / Bash / Agent**。它不是"被要求不开工",
是**没法开工**。

给读是划算的:读一眼仓库能省下好几个问题,而这个 session 用完就扔,读脏了无所谓
(`can_read=False` 可以连读也不给)。

**二、框架只解析那四段,别的一律丢掉。** `Brief.parse()` 先摘掉围栏代码块再找标题 ——
贴了也进不了下游。这是"它污染下游"的最后一道闸。

第三条隐含的是**额度在通道里数**:`max_asks` 由 `HumanChannel` 计数,超了工具直接
回绝(返回一句"额度已用完,把剩下的不确定项写进「未知与假设」"),不阻塞、不报错。
额度写在提示词里是建议,数在通道里是保证。

## 没人在的时候怎么活下去

长程 agent 的常态是**没人看着**。所以"停下来等人"必须能优雅地失败:

| 设置 | 行为 |
|---|---|
| `timeout_s=1800`(默认) | 等半小时;到点返回一句说明,**不是报错** |
| `timeout_s=None` | 永远等。只在确定有人值守时用 |
| `timeout_s=0` | **全自动模式**:所有提问立刻落空,不假装等 |
| `max_asks=6`(默认) | 最多放行 6 次;超出的提问立刻被回绝 |
| `max_asks=None` | 不限次 |

超时返回的原话是:

> 无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。
> 不要重复提问,也不要停在这里。

三种落空(超时 / 额度用尽 / 人主动跳过)的措辞都指向同一个动作:**把假设写进第四段**。
这就是无人值守时第四段仍然有内容的原因,也是长程运行能继续跑下去的原因。

一个实测过的机制事实:进程内 MCP 工具处理器里 `await` 一个外部 future **不会死锁** ——
处理器挂着的时候事件循环照转,另一个任务或**另一个线程**都能把答案填进来。
所以"停下来等人"在这个架构里是可行的,不需要轮询或者子进程。

## API

### `clarify_step(channel, *, brief_path, prompt, ...)`

造一个"先把需求问清楚"的 `Step`。它把三件事接在一起,一个新字段都没加:

| 接到哪 | 干什么 |
|---|---|
| `Step.when` | 确认书已存在且四段齐全就**跳过**,顺手把它灌进 `ctx` |
| `Step.gate` | 四段没写全就**不许往下走**;齐全则落盘**冻结** |
| `Step.reduce` | 往下游传**解析后的四段**,不是模型原文 |

| 参数 | 默认 | 说明 |
|---|---|---|
| `channel` | — | `HumanChannel`。同一个实例也要挂到 `Workflow(channel=...)` 上 |
| `brief_path` | — | 确认书落在哪。**推荐放 `Workbench.notes` 下**,见下 |
| `prompt` | — | **你的**原始诉求,一句话就够("帮我做个 X")。可以是 `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | 也是 `ctx` 里的键名 |
| `spec` | `None` | 自带一个 `AgentSpec`;给了就不再用 `clarify()` 造 |
| `instructions` | `""` | 追加在 `CLARIFIER_RULES` 之后的领域指令 |
| `always_ask` | `False` | `True` = 每次都重新确认(改需求时用) |
| `on_fail` | `"stop"` | 四段不齐时的去向,同 `Step.on_fail` |
| `retries` | `0` | 不齐时重试几次 |
| `**spec_kw` | — | 透传给 `clarify()`:`can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

`prompt` 只写你的诉求就行。**要问什么由确认者自己决定** —— 它该问你领域里的哪些问题,
框架不知道也不该知道。

跑完之后 `ctx` 里有三样东西:

```python
ctx["确认需求"]        # str,四段的 markdown,直接插进下游 prompt
ctx[BRIEF_KEY]        # "_brief" —— Brief 对象,想按段取用这个
ctx[MISSING_KEY]      # "_brief_missing" —— 只在失败时有:缺哪几段,给 UI 显示
```

**跳过也会灌 `ctx`。** 这一条容易漏:`when` 返回 `False` 时,`Workflow` 不会执行这一步,
自然也不会写 `ctx[step.name]` —— 所以 `clarify_step` 在 `when` 里就把已有的确认书
灌进去了。否则重跑时下游会拿到 `KeyError`。

### `brief_path` 必须放在**挂上去的那个** `Workbench.notes` 下

工作台索引会自动注入**每个** agent 的 system prompt。确认书放在那里,
后面每一个 subagent 开局就知道需求文件在哪,不用谁转述、也不占谁的正文。

关键是"哪一个工作台"。写法只有一种是对的:**自己建,然后挂到 `Workflow` 上**,
让驱动程序把同一个对象交给 `Runtime`。

```python
wb = Workbench(Path.cwd()).ensure()
wf = Workflow(channel=ch, workbench=wb, steps=[            # ← 挂上去
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="…"),
    ...,
])
```

两种错法,都**不报错**,所以格外要小心:

```python
# ✗ 自己拼一个路径:相对进程 cwd,和 -W 造的 <run_dir>/workbench 是两个目录。
#   确认书写进 A,注入的索引扫 B —— 上面那条承诺静默失效。
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ 想从 Runtime 反着拿:经 cli.py 做不到。它先调 main() 造 Workflow,
#   之后才建 Runtime —— 那时候 brief_path 早就定死了。
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

自己写驱动(不走 `cli.py`)时,先建 `Workbench`,再把**同一个对象**同时给
`Workflow(workbench=wb)` 和 `Runtime(workbench=wb)`。`tests/trial_offline.py`
第 5 项直接断言"确认书出现在 `prompt_block()` 里",第 11 项确认这条断言抓得到回归。

### `HumanChannel`

模型侧只看见一个工具 `mcp__human__ask`(参数:`question`,可选 `options`)。
UI 侧的用法见 [interaction.md](interaction.md)。

```python
HumanChannel(
    on_event=None,        # 推式 UI 的回调。挂在 Workflow 上时由 Workflow.run 自动接
    max_asks=None,        # **默认不限** —— 问几次由确认者自己判断
    timeout_s=1800.0,     # None = 永远等;0 = 全自动
    log_path=None,        # 问答追加到这个文件
    over_budget_text=..., timeout_text=..., declined_text=...,   # 三种落空的措辞
)
```

| 成员 | 作用 |
|---|---|
| `tool_name` | `"mcp__human__ask"` —— 给工具白名单用 |
| `mcp_servers()` | 交给 `AgentSpec.mcp_servers`(`clarify()` 已经接好) |
| `pending()` | 当前在等答案的 `Ask` 列表 |
| `await next_ask(timeout=None)` | 拉式:等下一个提问。超时返回 `None`,被取消则抛出 |
| `answer(ask_id, text)` | 回答。返回 `False` = 这个提问已经不在等了 |
| `decline(ask_id, reason="")` | 跳过,让模型自己判断 |
| `remaining` | 还能问几次(`max_asks=None` 时为 `-1`) |
| `asks` | 全部提问记录,含被回绝和超时的 |
| `transcript()` | 问答记录的 markdown |
| `ui_errors` | UI 回调抛出的异常。**不中断运行** —— 前端崩了不该带走三小时的活 |

`answer()` / `decline()` **可以从别的线程调** —— Web 后端、TUI 输入线程都在别的线程里,
这是常态不是边缘情况。内部走 `loop.call_soon_threadsafe`(`asyncio.Future.set_result`
不是线程安全的)。

### `Brief`

```python
Brief(goal="", accept="", bounds="", unknowns="", path=None)
```

| 方法 | 作用 |
|---|---|
| `Brief.parse(text)` | 从回话里取四段。先摘围栏代码块,再按标题切 |
| `Brief.load(path)` | 读一份已有的确认书。不存在或读不动返回 `None` |
| `.missing()` | 缺哪几段(中文段名,可直接显示) |
| `.complete()` | 四段都非空 |
| `.write(path)` | 落盘冻结,返回绝对路径 |
| `.to_markdown()` | 完整文书(带标题与说明) |
| `.prompt_block()` | 喂给下游的紧凑版,没有元信息 |

解析对写法很宽容:`## 目标` / `**目标**` / `目标:` / `3. 边界` 都认,标题后面直接跟正文
(`目标: 做一个 X`)也认。段名的常见变体也认(`验收条件`→验收标准、`不做什么`→边界、
`未知项与假设`→未知与假设)。同一段出现多次,取第一个有内容的。

## 试用

不用写代码,也不用打引号。进你的项目目录:

```bash
cd /path/to/your/project
flower
```

```
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

只想看它问什么、不往下干活(便宜):

```bash
flower --clarify-only
```

想让它多问几轮:`--asks 12`。没人守着的时候:`--timeout 0`(所有提问立刻落空,
它自己判断并把假设写进「未知与假设」)。这条路径的流程实现在
[`flower/workflow/starter.py`](../flower/workflow/starter.py)。

> **要在真终端里跑。** 回答走标准输入,管道 / `nohup` / CI 里没人能答:
> 第一个问题会被当成"输入已关闭"跳过,之后每个问题都要干等满 `--timeout`。

终端里会看到:

```
❓ 这个工具是给命令行用,还是要有 Web 界面?
   1) 纯命令行
   2) Web 界面
   3) 两个都要
   (还能问 5 次)
你的回答 (回车=跳过,让它自己判断) > 1
```

- 输**序号**选选项,或者**直接打字**回答
- **回车 = 跳过**这个问题,让它自己判断并把假设记进「未知与假设」
- 四段齐全才放行,确认书冻结在 `<工作台>/notes/需求.md`
- **重跑不会再盘问一遍**(要重新确认就 `always_ask=True`,或者删掉那个文件)

改需求的正确做法是**改那个文件**,不是重新对话 —— 它是冻结件,从落盘那一刻起,
需求以文件为准。

调不顺的时候先动这几个旋钮:

| 症状 | 拧哪个 |
|---|---|
| 问得太多、太碎 | 调小 `max_asks`;在 `instructions` 里写清你的领域里什么是显然的 |
| 问得太少就开工 | 调大 `max_asks`;`instructions` 里点名它必须搞清哪几件事 |
| 四段填得敷衍 | `instructions` 里给一个你自己领域的范例 |
| 没人值守却卡住 | `timeout_s=0` |
| 想每次都重新确认 | `always_ask=True` |

## 验证状态

**离线全绿**(`tests/clarify.py`,52 项,不花钱):提问通道的五种语义(阻塞等答案 /
额度用尽 / 超时落空 / 跳过 / 跨线程回答)、四段解析(含"贴了代码进来"的样本)、
`clarify()` 角色**没有**写工具、`clarify_step` 的三处接线。

**CLI 路径离线跑通**:预置一份完整确认书 → 第一步跳过 → 通道自动接上标准输入线程 →
确认书灌进 `ctx` → 干净退出。

**没跑过真实 API。** 这一段留给使用者自己试(见上一节)。$0.8908 那次探针是**真实请求**,
但它测的是"不受约束的确认者会干什么",不是现在这条路径。
