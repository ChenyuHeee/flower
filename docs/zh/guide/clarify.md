# 前置确认

动手之前先把需求问清楚。[确认者](../reference/glossary.md#确认者)是一个只提问、不动手的角色,
问到清楚为止,最后输出一份恰好四段的[需求确认书](../reference/glossary.md#需求确认书),
冻结到磁盘。后面每一个[步骤](../reference/glossary.md#步骤)读这份文书开局,不再重新猜需求 ——
而那段问答**从来没进过**下游的上下文。

## 解决什么问题

flower 清理上下文的手段清的都是**现场**:时效过期、被拒调用摘除、错误消息摘除、
大结果[落盘](../reference/glossary.md#落盘)。现场丢掉不要紧,重跑一次就有。

有一类错误不是这样:**目标理解错了**。它是唯一一类**剪枝会让它变严重**的错误。现场被丢掉之后,
留下来的恰恰是那条建在错误前提上的决策,而且它看起来和正确决策一模一样 ——
没有任何痕迹表明它的前提可疑。

[长程](../reference/glossary.md#长程)会把它放大到最坏:错误前提先跑几个小时、
派十几个 [subagent](../reference/glossary.md#subagent)、在磁盘上落一堆产出,之后才暴露。
到那时贵的不是 token,是**每一个产出都是照错的需求建的**。
[HT001](../cases/ht001.md) 的账能量出这个比例:确认需求那一步 **$0.3704 / 5 轮 / 0.06h**,
后面干活那一步 **$171.2476 / 31 轮 / 10.44h**。

所以要有一个能"停下来问"的通道,而且它必须在开工**之前**。

## 怎么用(最小代码)

### 零代码:命令行

进项目目录,直接跑:

```bash
cd /path/to/your/project
flower
```

```text
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

终端里会看到这样的提问:

```text
  ? 这个工具是给命令行用,还是要有 Web 界面?
     1) 纯命令行
     2) Web 界面
     3) 两个都要
你的回答 (回车=跳过,让它自己判断) > 1
```

- 输**序号**选选项,或者直接打字回答
- **回车 = 跳过**这个问题,让它自己判断并把假设记进「未知与假设」
- 四段齐全才放行,确认书冻结在 `.flower/notes/需求.md`
- **重跑不会再盘问一遍** —— 要重新确认就删掉那个文件,或者加 `--new`

只想看它问什么、不往下干活:`flower --clarify-only`。给提问设硬额度:`--asks 12`
(给了才会在选项下面多一行 `(还能问 N 次)`;默认不限次数,那一行不出现)。没人守着:`--timeout 0`。
这条路径的实现在
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py)。

!!! warning "回答走标准输入,要在真终端里跑"
    管道、`nohup`、CI 里没人能答:stdin 一读到 EOF,当时挂着的那个提问被当成"输入已关闭"跳过,
    之后每个提问都要干等满 `--timeout`。这种场合直接给 `--timeout 0` ——
    所有提问立刻落空,它自己判断并把假设写进「未知与假设」。

### 自己接线

```python
from pathlib import Path
from flower import HumanChannel, Step, Workbench, Workflow, clarify_step

wb = Workbench(Path.cwd()).ensure()
ch = HumanChannel(log_path=wb.notes / "问答记录.md")   # 默认不限提问次数,等人 30 分钟
wf = Workflow(channel=ch, workbench=wb, steps=[
    clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
    Step("干活", spec=协调者, prompt=lambda ctx: f"照这份需求做:\n\n{ctx['确认需求']}"),
])
```

`prompt` 只写**你的**原始诉求,一句话就够。要问什么由确认者自己决定 ——
它该问你这个领域里的哪些问题,框架不知道也不该知道。上面的 `协调者` 是你自己用 `coordinator()`
造的 `AgentSpec`,见[设计流程](workflow.md)。

`clarify_step()` 的参数:

| 参数 | 默认 | 说明 |
|---|---|---|
| `channel` | — | `HumanChannel`。**同一个实例**也要挂到 `Workflow(channel=...)` 上 |
| `brief_path` | — | 确认书落在哪。必须在挂上去的那个[工作台](../reference/glossary.md#工作台)里,见下 |
| `prompt` | — | 你的原始诉求。`str` 或 `Callable[[Ctx], str]` |
| `name` | `"确认需求"` | 步骤名,也是 `ctx` 里的键名 |
| `spec` | `None` | 自带一个 `AgentSpec`;给了就不再用 `clarify()` 造 |
| `instructions` | `""` | 追加在 `CLARIFIER_RULES` 之后的领域指令 |
| `always_ask` | `False` | `True` = 每次都重新确认(改需求时用) |
| `on_fail` | `"stop"` | 四段不齐时的去向,同 `Step.on_fail` |
| `retries` | `0` | 四段不齐时重试几次 |
| `**spec_kw` | — | 透传给 `clarify()`:`can_read` / `model` / `effort` / `max_turns` / `max_budget_usd` |

跑完之后 `ctx` 里有三样东西:

```python
ctx["确认需求"]     # str,四段的紧凑版(prompt_block),直接插进下游 prompt;键名 = 步骤名
ctx[BRIEF_KEY]     # "_brief" —— Brief 对象,想按段取用这个
ctx[MISSING_KEY]   # "_brief_missing" —— 只在四段不齐时有:缺哪几段,给 UI 显示
```

调不顺的时候先动这几个旋钮:

| 症状 | 拧哪个 |
|---|---|
| 问得太多、太碎 | 给 `max_asks` 一个硬额度;在 `instructions` 里写清你的领域里什么是显然的 |
| 问得太少就开工 | `instructions` 里点名它必须搞清哪几件事(次数默认已经不限,调额度没用) |
| 四段填得敷衍 | `instructions` 里给一个你自己领域里的范例 |
| 没人值守却卡住 | `timeout_s=0` |
| 想每次都重新确认 | `always_ask=True`,或者删掉确认书文件 |

## 它实际做了什么

### 触发时机:三处接线,一个新字段都没加

`clarify_step()` 造出来的是一个普通的 `Step`,只是把三个回调填好了:

| 接到哪 | 什么时候跑 | 干什么 |
|---|---|---|
| `Step.when` | 进这一步之前 | 确认书已存在且四段齐全就**跳过**,并把它灌进 `ctx` |
| `Step.gate` | 这一步跑完、结果交给下游之前 | 四段没写全就**不许往下走**;齐全就 `write()` **冻结** |
| `Step.reduce` | 通过之后 | 往下游传**解析后的四段**,不是模型原文 |

**跳过也会灌 `ctx`。** 这一条容易漏:`when` 返回 `False` 时 `Workflow` 不执行这一步,
自然也不会写 `ctx[step.name]` —— 所以 `clarify_step` 在 `when` 里就把已有的确认书灌进去了。
否则重跑时下游会拿到 `KeyError`。

`reduce` 传的是 `Brief.prompt_block()` 而不是模型原文,因为原文里可能夹着它多写的东西
(实测它会把整份代码贴进回话)。

[接续](../reference/glossary.md#接续)时这一步换一句话开口 —— `CLARIFY_RESUME`:
"接着刚才那次没问完的需求确认继续 —— **不是重新开始**……"。不给这句,
接续会把原始诉求当成新任务重发,确认者可能把已经问过的重问一遍。

### 边界:问答不进下游的上下文

```text
确认需求        独立会话  ────→  磁盘上一份冻结的四段确认书
                                          │
干活(下一步)   新会话(resume_from=None)◄─┘   只拿到那四段
```

`clarify_step` 的 `resume_from` 保持默认 `None`,所以下一步是**新会话**,只拿到确认书。
那段问答**从来没进过**[协调者](../reference/glossary.md#协调者)的上下文 ——
不是"进去之后被剪掉"。差别是实质性的:剪掉的东西在 `sessions.db` 里还在、
还可能被 resume 带回来;从没进过的不存在这个问题。

问答本身**追加到 `log_path`**。这一份不占上下文、不受压缩影响、换台机器也还在 ——
和工作台是同一个思路。

### 四段各挡一类失败

| 段 | 写什么 | 不写会怎样 |
|---|---|---|
| **目标** | 一句话:做什么,给谁用 | 做出来的是另一个东西 |
| **验收标准** | 可判定的条件,一条一行。"做好了"不算,"跑 `x` 输出 `y`"才算 | 没人能判定"做完了" |
| **边界** | **明确不做什么** | 范围蔓延。这一段管住后面**每一个** subagent |
| **未知与假设** | 没问到的、超时落空的、自己猜的,一条一行 | **错误前提被静默埋掉** |

第四段是长程运行的保险丝。前三段任何一段写错,只要假设显式写在第四段,后面的人读到就有机会拦住;
埋掉了就只能等几小时后产出全废时才发现。错误前提没法完全避免,但可以让它**显式**。

四段齐全才放行,缺哪一段由 `Brief.missing()` 报出来 —— 它返回的是中文段名,可以直接显示。

解析对写法很宽容:`## 目标` / `**目标**` / `目标:` / `3. 边界` 都认,标题后面直接跟正文
(`目标: 做一个 X`)也认,常见别名也认(`验收条件`→验收标准、`不做什么`→边界、
`未知项与假设`→未知与假设);同一段出现多次,取第一个有内容的。两个例外要知道:

- `Brief.parse()` **先剥围栏代码块**,遇到**未闭合**的围栏就从它开始把后面整段丢掉。
  模型输出被截断时,后面的段全部解析不出来 → 四段不齐 → `gate` 打回重来。
- `Brief.load()` 把 `"(未填)"` 当空。手工编辑确认书时照抄了 `to_markdown()` 的占位文字,
  那一段仍然算缺失。

### 边界:确认者能碰什么

跑过一个**不受约束**的确认者(`/tmp/probe_ask.py`,**$0.8908 / 230 秒**):
它问完两个问题**直接开始写代码**;被权限拦下之后,**把整份代码贴进了回话正文**。
提示词里写"不要写代码"挡不住这个 —— 它当时的系统提示里就有类似的话。所以有两道机制:

**一、一道 hook 拦掉它的写工具。** `clarify()` 的免审批清单是
`mcp__human__ask` 加上(`can_read=True` 时)`Read` / `Glob` / `Grep` / `WebFetch` / `WebSearch`,
没有 `Write` / `Edit` / `Bash` / `Agent`。真正执行这条的是 `Runtime` 自动装的 `whitelist_guard`:
它按免审批清单反推出 `Bash` / `Write` / `Edit` / `NotebookEdit` 里该拦的那几个,
命中就 `deny`。它不是"被要求不开工",是**没法开工**。

给它读是划算的:读一眼仓库能省下好几个问题,而这个会话用完就扔,读脏了无所谓
(`can_read=False` 可以连读也不给)。

**这必须是 hook,不能只靠 `allowed_tools`。** 后者是**免审批清单,不是排他白名单** ——
模型照样调得动不在里面的工具。两条还成立的实测证据:

- [HT002](../cases/ht002.md) 里"设定目标"那个[判定者](../reference/glossary.md#判定者)
  实际跑了 **11 次 `Bash`**,而 `judge()` 默认 `can_run=False`、清单里根本没有 `Bash`
  (那次运行还没有这道 hook —— 今天同样的调用会被 `whitelist_guard` 当场 `deny`,
  这正说明拦住它的是 hook 而不是清单)。
- **$0.1 的探针**:给一个 `allowed_tools=["Read"]` 的 agent 让它写文件 ——
  `Write` 被权限层拒(`"requested permissions to write ... but you haven't granted it yet"`),
  `Bash` 被路径安全拒(`"Output redirection was blocked. For security, Claude Code may
  only write to files in the allowed working directories"`)。**调用发出去了**,
  是别的层挡下的。

`clarify()` 不显式设 `permission_mode`,继承 `AgentSpec` 默认的 `"default"`。
`coordinator()` 默认是 `"acceptEdits"` —— 谁把这个值透传给确认者,那层保护就没了。

**二、框架只解析那四段,别的一律丢掉。** `Brief.parse()` 先摘围栏代码块再找标题 ——
贴了也进不了下游。这是"它污染下游"的最后一道闸。

### 边界:提问通道

模型侧的提问工具叫 `mcp__human__ask`(参数 `question`,可选 `options`)。
`HumanChannel` 是一个进程内 MCP server,**注册的是两个工具** ——
`mcp__human__ask` 和 `mcp__human__inbox`;确认者的免审批清单里只有前一个
(收件箱是给协调者用的)。

```python
HumanChannel(
    on_event=None,        # 推式 UI 的回调。挂在 Workflow 上时由 Workflow.run 自动接
    max_asks=None,        # 默认不限次数
    timeout_s=1800.0,     # 30 分钟。None = 永远等;<= 0 = 全自动
    log_path=None,        # 问答追加到这个文件,不占上下文
    amend_path=None,      # 人在运行途中说的话追加到这个文件(通常就是确认书)
    over_budget_text=..., timeout_text=..., declined_text=...,   # 三种落空的措辞
)
```

长程 agent 的常态是**没人看着**,所以"停下来等人"必须能优雅地失败:

| 设置 | 行为 |
|---|---|
| `timeout_s=1800.0`(默认) | 等半小时;到点返回一句说明,**不是报错** |
| `timeout_s=None` | 永远等。只在确定有人值守时用(CLI 给不出这个值,`--timeout` 是 float) |
| `timeout_s=0`(负数同) | **全自动**:所有提问立刻落空,不假装等 |
| `max_asks=None`(默认) | **不限次数** —— 问几次由确认者自己判断 |
| `max_asks=N` | 硬额度。超出的提问工具**直接回绝**,不阻塞、不报错 |
| `max_asks=0` | 不许提问(CI / 无人值守) |

`remaining` 在 `max_asks=None` 时返回 `-1`(不是 0,也不是无穷),终端据此不显示"还能问 N 次"。

超时返回的原话是:

> 无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进「未知与假设」那一段。
> 不要重复提问,也不要停在这里。

三种落空(超时 / 额度用尽 / 人主动跳过)的措辞都指向同一个动作:**把假设写进第四段**。
这就是无人值守时第四段仍然有内容的原因,也是长程运行能继续跑下去的原因。
额度写在提示词里是建议,**数在通道里才是保证**。

一个实测过的机制事实:进程内 MCP 工具处理器里 `await` 一个外部 future **不会死锁** ——
处理器挂着的时候事件循环照转,另一个任务或**另一个线程**都能把答案填进来。
所以 `answer()` / `decline()` 可以从 Web 后端、TUI 输入线程里直接调(内部走
`loop.call_soon_threadsafe`),这是常态不是边缘情况。UI 回调抛的异常收在 `ui_errors` 里,
**不中断运行** —— 前端崩了不该带走三小时的活。完整成员表见 [Python API](../reference/api.md)。

!!! warning "`max_turns` 设小了,"问到清楚为止"就成了空话"
    `clarify()` 的 `max_turns` 默认是 `None`(不限)。**每提一个问题就是一轮** ——
    设成 16 就等于"最多问十几个",而且它是**静默**生效的:通道那边 `max_asks=None`
    照样写着"不限次数",人看不出来是谁把它掐了。要放开提问,`HumanChannel.max_asks`
    和 `clarify(max_turns=...)` **两个默认值都得留在 `None`**。

### 确认书落在哪:必须是挂上去的那个工作台

工作台索引会注入 system prompt,协调者开局就知道需求文件在哪,派活时把路径给下去即可,
不必把内容抄进[任务书](../reference/glossary.md#任务书)。

!!! warning "索引只到主 agent"
    subagent 有自己的 system prompt,**继承不到**会话级的那一段(实测 **$0.2461**,
    `tests/prelude_live.py`)。所以是"协调者转述路径",不是"每个 subagent 自动知道"。

关键是**哪一个**工作台。写法只有一种是对的:自己建,然后挂到 `Workflow` 上,
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
# ✗ 自己拼一个路径:相对进程 cwd,和 Runtime(workbench=True) 造的 <run_dir>/workbench
#   是两个目录。确认书写进 A,注入的索引扫的是 B —— 上面那条承诺静默失效。
clarify_step(ch, brief_path=Path(".flower/notes/需求.md"), prompt="…")

# ✗ 想从 Runtime 反着拿:经 cli.py 做不到。它先调 main() 造 Workflow,
#   之后才建 Runtime —— 那时候 brief_path 早就定死了。
rt = Runtime(workspace="repo", workbench=True); wb = rt.workbench
```

自己写驱动(不走 `cli.py`)时,先建 `Workbench`,再把**同一个对象**同时给
`Workflow(workbench=wb)` 和 `Runtime(workbench=wb)`。`tests/trial_offline.py`
第 5 项直接断言"确认书出现在 `prompt_block()` 里",第 11 项确认这条断言抓得到回归。

### 验证状态

**离线全绿**(`tests/clarify.py`,**52 项**,不花钱):提问通道的五种语义(阻塞等答案 /
额度用尽 / 超时落空 / 跳过 / 跨线程回答)、四段解析(含"贴了代码进来"的样本)、
`clarify()` 角色**没有**写工具、`clarify_step` 的三处接线。

**CLI 路径离线跑通**:预置一份完整确认书 → 第一步跳过 → 通道自动接上标准输入线程 →
确认书灌进 `ctx` → 干净退出。

**没跑过真实 API。** $0.8908 那次探针是**真实请求**,但它测的是"不受约束的确认者会干什么",
不是现在这条路径。

## 什么时候不该用它

**需求已经是冻结件了。** 需求写在文件里、由上游系统给定、或者这次就是重跑同一件事 ——
那就没有可问的。直接把需求文本喂给干活那一步,或者留着 `clarify_step` 让它 `when` 跳过
(确认书在,它本来就不问)。

**没人可问,而且你不想让它自己猜。** `timeout_s=0` 时所有提问立刻落空,
第四段会被填上一堆它自己的假设 —— 这是设计如此,但那份确认书的可信度就等于那些假设的可信度。
CI 里更干净的做法是 `max_asks=0`(明确不许问),需求由外部给全。

**一次性小活。** 确认这一步本身是要花钱的:[HT002](../cases/ht002.md) 里
"clone 一个仓库,在 macOS 上装好跑起来"这样一件事,确认需求花了 **$0.5306 / 9 轮 / 0.10h**。
活越小,这一步占的比例越难看。`flower once` 那种单 agent 路径不带这一步。

**改需求的时候不该重新对话。** 确认书是冻结件,从落盘那一刻起需求以文件为准 ——
正确做法是**改那个文件**。`--clarify-only` 在已经确认过的目录上是**空操作**
(那条 workflow 只有这一步,而这一步会跳过),要重新确认得配 `--new`,
或者在自己接线时给 `always_ask=True`。

**它不判定"做完了没有"。** 那是另一层,见[目标看守](goal.md)。前置确认挡的是
"做出来不是想要的",挡不住"说做完了其实没做完"。
