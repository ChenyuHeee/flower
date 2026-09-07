# 换代

上下文快满的时候,让**当前这条会话自己**写一份人能读、能改的[交接书](../reference/glossary.md#交接书),
然后开一条新会话接手。不用 compact。整个过程你在终端里看得见,文书就落在磁盘上,
想改随时改 —— 接手的那条会话读的就是那个文件。

!!! note "换代不是接续"
    [换代](../reference/glossary.md#换代)是**同一次运行内部**换一条新[会话](../reference/glossary.md#会话);
    [接续](../reference/glossary.md#接续)是**跨进程**接上上一次[运行](../reference/glossary.md#运行),
    见[接续](continuity.md)。

    两者自动咬合,不需要额外接线:[血缘](../reference/glossary.md#血缘)记的是那一步**最后**的
    `session_id`,而那正是接班人 —— 所以下次唤醒接在接班人身上,不是接在被烧掉的那一代上。

## 解决什么问题

SDK 自带的 auto-compact 在**窗口 −33k** 处触发(实测:窗口 `200000` 时阈值是 `167000`;
压缩算法本身在 harness 二进制里,改不了,能改的只有触不触发),做的事是**把历史总结成一段话**。
它和这个框架其余部分是拧着的:

| | 什么时候决定 | 留下什么 |
|---|---|---|
| `spill_guard` | 工具返回的那一刻 | 大结果[落盘](../reference/glossary.md#落盘),上下文里留一行路径 |
| 冻结件(需求 / 目标) | 那一步结束时 | 一份文书,下一步只读它 |
| **auto-compact** | **上下文满了才回头** | **一段模型自己写的摘要** |

flower 从头到尾在做的是**当场决定什么该留**。[压缩](../reference/glossary.md#压缩)是唯一一处“事后补救”,
而且它的产物有四个毛病:

- **模型生成的** —— 摘要里写什么由模型当时的判断决定,你没有参与
- **不可读** —— 它为下一轮的模型而写,不是为人而写
- **不可改** —— 它在 harness 里面,没有一个文件让你打开
- **丢了什么你不知道** —— 既看不见丢的是哪些,也没法在它丢之前说一句“那个别丢”

换代把这件事拉回同一套做法:**又一个冻结件**,和需求确认书、目标是同一个形状 ——
结构化的、落盘的,**你能打开改一行,再让它接着跑**。而这正是这个项目自己的做法 ——
仓库根的 `HANDOFF.md` 就是人写的同一种东西。

## 怎么用(最小代码)

命令行默认就带换代:

```bash
flower                       # 默认就带换代
flower --window 200000       # 判错了才需要给(默认 100 万)
flower --no-handoff          # 关掉 —— 退回 SDK 自带的 auto-compact
```

自己写代码时,换代由 `Runtime(handoff=…)` 控制,默认 `True`:

```python
from flower import HandoffPolicy, Runtime

# 默认:HandoffPolicy(enabled=True, window=default_window(), headroom=50_000, max_generations=8)
rt = Runtime(workspace=".", run_dir="runs", workbench=True)

# 显式配窗口(换网关、换模型时最该调的就是这个)
rt = Runtime(
    workspace=".",
    run_dir="runs",
    workbench=True,
    handoff=HandoffPolicy(window=200_000, headroom=50_000, max_generations=8),
)

rt = Runtime(workspace=".", run_dir="runs", handoff=False)   # 关掉,退回 auto-compact
```

`Runtime.__init__` 全部是 keyword-only,`workspace` 必填。`handoff` 收 `HandoffPolicy` 实例或
`bool`,给 `bool` 时等价于 `HandoffPolicy(enabled=…)`。

!!! warning "开着换代 = auto-compact 被强制关掉"
    `Runtime(handoff=True)` 是**默认值**,而它会在装配每一次尝试时做这件事:只要
    `handoff.enabled` 且 `spec.compact is None`,就把 spec 换成
    `CompactPolicy(mode="no_summary")` —— 也就是往子进程注入 **`DISABLE_AUTO_COMPACT=1`**。

    理由是两套机制同时跑的话,某次上下文回落到底是谁干的就说不清了。代价是**没有安全网**:
    写交接那一轮失败时不能停,也不能装作没事撑到硬上限,所以必须有降级路径(见下文)。

    要保留 auto-compact 做兜底,得**显式**给 `AgentSpec(compact=CompactPolicy(mode="auto"))` ——
    spec 自己给了就尊重它,不覆盖。注意这会**静默赢过**换代那半边的假设。

## 它实际做了什么

### 触发时机:两条路进换代

**一、水位到阈值。** 判据是 `_handoff_due`:`handoff.enabled` 且**不在写交接的那一轮**
且 `_ctx >= handoff.at` 且这一步已经拿到过 `session_id`。`_ctx` 是**主线程**最后一轮实际看到的
上下文规模 —— 只看[主线程](../reference/glossary.md#主线程),[subagent](../reference/glossary.md#subagent)
的上下文是它自己那条 transcript 的事,跑完就散,不该逼主会话换代。

在 `warn_at` 处会先发一次逼近提醒,每代只发一次,不刷屏。

**二、API 直接报“装不下了”。** 见下面 `is_overflow` 那一节。

两条路都**不受 `max_attempts` 约束**,而且**不吃重试额度**(内部 `attempt -= 1`)——
换代不是失败。

### 交接书:五段,必填只有两段

每一段挡一类“接手的人会犯的错”:

| 段 | 字段 | 挡什么 |
|---|---|---|
| 现在在做什么 | `doing` **必填** | 不知道自己站在哪 |
| 已经定下的 | `decided` | 重新讨论已经定过的事(要带**为什么**) |
| 走不通的路 | `deadends` | **最贵的一段** —— 见下 |
| 下一步 | `next` **必填** | 先花半小时决定干什么 |
| 现场 | `scene` | 关键文件与产出的**路径**。指针,不是内容 |

`Handoff.missing()` 只检查 `REQUIRED = ("doing", "next")` 这两段,`complete()` 是它的取反。
**硬性要求“走不通的路”非空会逼出编造** —— 任务刚开头时它本来就该是空的。
而且 `complete()` 的判定是有后果的:缺了必填段,这份交接会被**整个换成机械拼的降级件**
(见下文),那比一份少写一段的真交接差得多。所以另外三段是可选的 —— 写了就有用,没写不挡换代。

`to_markdown()` 里空段写 `(空)`;`prompt_block()` 的抬头明确告诉接手者“你在接手”,
防它回头找人要背景。`step` 字段只用于文书抬头,不参与解析。

#### “走不通的路”为什么最贵

因为它是**接手的人最花钱重新发现的东西**,而写的人最容易漏掉。

干活的人有系统性乐观偏差([目标看守](goal.md)论证过同一件事):它会写自己做成了什么,
忘记写试过什么不行。而后者才是真正贵的 —— [HT002](../cases/ht002.md) 里为一个编译问题绕了一小时,
那一小时的结论要是没写下来,接手的人会原样再绕一遍。

所以 `HANDOFF_PROMPT` 里专门用一段话点这件事,还带上了那个实测代价。

### 长什么样

```text
# 上下文 130.0K/200K · 还有约 20K 到换代

# 上下文 152.0K/200K —— 写交接准备换代
  - 现在在做  在给 Makefile 加 macOS 垫片头,让 sigemptyset 宏不再展开成语法错误。
  - 已定的事  不改业务源码 —— 用户明确说过边界,所以走 Makefile 生成 shim 这条路。
  - 走不通的  -D_ANSI_SOURCE 会把别的宏一起关掉;改 include 顺序无效。
  - 下一步    在干净 clone 上跑一次 make 验证 shim 成立。
<- 交接写在 ~/proj/.flower/notes/交接-干活.md
<- 新会话接手,上下文从 152.0K 重新开始
```

**全自动,不停下来等你** —— 长程跑不该因为人去吃饭而卡住。

事件是 `Event("handoff")`,`payload["phase"]` 有**三个**值:`near`(逼近)、`writing`(正在写,
写交接要十几秒,不发这一条界面看起来像卡住)、`done`(换完了)。`done` 的 payload 还带
`context`、`window`、`degraded`、`path`、`sections`。

### 阈值怎么算

```python
at      = max(10_000, window - headroom)   # 换代线,有 10k 下限
warn_at = max(1_000, at - 20_000)          # 逼近提醒线
```

`at` 的 10k 下限是必须的 —— 再低连交接都写不出来。

下面这张刻度图用 `--window 200000` 举例,**默认窗口是 100 万**:

```text
  0--------------------------------------|-----|--------------|
                                       130K  150K           200K
                                       提醒  换代          硬上限
```

`window` 不给时由 `default_window()` 按**模型名字符串**判,只看 `ANTHROPIC_MODEL` 或
`ANTHROPIC_DEFAULT_OPUS_MODEL` 这两个环境变量:

| 模型名 | 判成 |
|---|---|
| 名字里有独立的 `1m` 词 | `1_000_000` |
| 名字里含 `haiku` | `200_000` |
| 其余,**以及两个变量都没设** | `1_000_000` |

注意顺序:`1m` 先匹配,所以 `claude-haiku[1m]` 会被判成 100 万,不是 20 万。

`headroom` 为什么是 `50_000`:auto-compact 在窗口 −33k 触发,换代必须赶在它前面;
而“写交接”本身还要再跑一轮。50k 同时满足这两件事。

**`--window` 是换模型 / 换网关时最该调的开关。** SDK 那边拿不到可靠的窗口大小,只能按名字猜。
真实窗口更大 → 换代偏早(浪费,不出错);更小 → 来不及,必须调。实测值得一提:
开发这台机器的网关配的是 `claude-opus-5[1m]`。早先按 20 万算的话每 15 万就换一代,
而它其实能跑到 95 万 —— **差 5 倍**,长程活会被切得稀碎。

用 `flower -v` 能在开跑前看到当前生效的凭证配置(端点、模型名,token 打码只留前 4 位)。

### `is_overflow`:把硬错变成当场换代

这是**敢把 `default_window()` 的默认值取 100 万**的前提。

窗口判大了的话,阈值永远够不着,而 auto-compact 又被关掉了 —— 那就会硬撞在 API 上。
`is_overflow(*texts)` 认这个信号:`prompt is too long`、`context length exceeded`、
`maximum context length`、`too many total text bytes`、`input length and max_tokens exceed` 等等。

认出来之后走的是**同一条换代路径**,只是这一代的交接必然是降级的 —— 那条会话已经跑不动
“再写一轮交接”了,所以直接用机械拼的降级件,照常换新会话接着做,**这一步不失败**。

于是判大了的代价从“这一步失败”降到“这一代的交接是降级的”。

`is_overflow` 是**模块级函数**,不是 `Handoff` 的方法,而且是变长参数。

### 交接写不出来时:降级,不是停下

写交接那一轮也可能失败 —— 网络断了、模型抽风、解析出来缺了必填段。因为
auto-compact 已经被关掉,**没有兜底**,停在这里等于撞窗口。

做法:用手上已知的东西机械拼一份**残缺交接**,`doing` 里标上 `[降级:交接没写成]`
(常量 `DEGRADED`),`scene` 里塞原始任务的前 **1200** 字符,照样换代。接手的人被明确告知
它拿到的东西不完整,该自己去现场看。同时 `StepResult.errors` 里会多一条“交接降级(…)”,
`manifest.json` 里查得到原因。

对应的是模块级函数 `degraded(step, prompt, *, why="")`;`Handoff.degraded` 是个只读 property,
判的是 `doing` 里有没有那个标记。

> **残缺的交接远胜于撞窗口。**

写交接那一轮还有两个刻意的安排:用 `max_budget_usd=None` 跑 —— **交接必须写得出来,
不能卡在预算上**;`on_event=None` —— 这一轮不往 UI 刷。

### 一颗地雷:写交接那一轮必须豁免阈值

写交接是在**越线之后**跑的 —— 那时水位本来就还挂在阈值之上。不豁免的话,交接那一轮的
第一条消息又判“该换代了”,于是它一个字都没写出来就被打断,**每一代都产出降级件**,
而且看起来一切正常(降级路径工作得很好)。

实测栽过:`tests/handoff_live.py` 头一次真跑,**两代交接全是降级版本**。离线测试没抓到 ——
那里把 `_attempt` 整个换掉了,假的没跑这条判据。现在判据提成了 `Runtime._handoff_due()`,
离线直接验它。

### 一道防跑飞的闸

`max_generations=8`。

!!! danger "`window` 配小了会无限换代烧钱"
    危险在于:**阈值低于这个角色的启动地板**([协调者](../reference/glossary.md#协调者)实测约 34k,
    光系统提示加[工作台](../reference/glossary.md#工作台)索引就占掉了),那么每个新会话一开口就越线
    → 写交接、换代、再越线,**永远不停**。而换代不吃重试额度,那是有意的,于是唯一的闸就是
    `max_generations=8`。

    正常长跑用不到 8 代;真撞上了,几乎一定是 `window` 配小了 —— 到达上限时错误信息里直接这么说
    (“阈值很可能低于这个角色的启动地板,把 window 调大,或 `--no-handoff`”)。

### 一次换代的完整过程

```text
干活(session A)
  |  主线程上下文越过阈值   <- 只看主线程。subagent 的上下文是它自己那条
  |                            transcript 的事,跑完就散,不该逼主会话换代
  |- 在消息边界上断开       <- 和 Ctrl-C 打断同一个道理:干净地断,不撕裂状态
  |                            (代价一样:在飞的 subagent 会丢。50k 余量为此而留)
  |- 同一个 session 再跑一轮:写交接
  |     为什么是它自己写 —— 只有它有那段上下文。换谁来写都得先读一遍,那就白换了
  |- 冻结到 <工作台>/notes/交接-<步骤名>.md,上一代移进 notes/archive/交接/
  |- 新会话(resume=None、fork=False),prompt = 交接书的 prompt_block()
干活(session B)接着做
```

`HANDOFF_PROMPT` 是让当前会话写交接的那段提示词,含 `{used}` 和 `{window}` 两个占位符。
**它不是一个新角色** —— 只有当前这条会话有那段上下文。

### 换代不算重试,账怎么记

| 字段 | 换代时怎么变 |
|---|---|
| `attempts` | **不涨** —— 它数的是失败尝试 |
| `retired[]` | 这一步烧掉的 session_id **按序**记在这里 |
| `session_id` | 永远是**最后接班的那个**,不是被烧掉的 |
| `context` | 最后一轮主线程实际看到的上下文规模 |
| `cost_usd` / `num_turns` | 在重试与换代中**累加** |

这几个字段都进 `manifest.json`,事后能完整复原“这一步烧了几代、每代花了多少”。

### 交接落在哪

`<工作台>/notes/交接-<步骤名去掉非法字符>.md`;已存在的上一代被移到
`notes/archive/交接/<步骤名>-<时间戳>.md`。

**没有工作台就不落盘** —— 那时 `_handoff_path` 返回 `None`,文书照样通过 prompt 交给接手者,
换代照常进行,只是**人事后翻不到那份文件**。要事后能翻,就得开工作台
(`Runtime(workbench=True)`,或者由[流程](../reference/glossary.md#流程)自己挂一个)。

## 什么时候不该用它

- **就是想用 compact。** `flower --no-handoff`,或者 `Runtime(handoff=False)`。
  换代会连带关掉 auto-compact,不想要这个连带效果就别开。
- **想让两套同时在。** 显式给 `AgentSpec(compact=CompactPolicy(mode="auto"))` 能保住 auto-compact,
  但那之后“某次上下文回落是谁干的”就说不清了,排查会变难。要么信换代,要么信 compact,别都信。
- **短任务、单轮活。** 换代永远不会触发,配置它没有意义 —— 但要记得 `Runtime` 默认
  `handoff=True` 仍然把 auto-compact 关了。
- **没有工作台又指望事后读交接。** 先开工作台,否则文书只在那一次运行的上下文里出现过。
- **`window` 还没配对就开始长跑。** 真实窗口比默认值小时,前几代交接会全是降级件,
  而降级件恰恰是最没用的那种交接。先用 `--window` 配对,或者先跑一轮短的看 `-v` 里的模型名。
- **拿换代当上下文治理的全部。** 它是最后一道。当场就剪的那几层
  (落盘、[裁剪](../reference/glossary.md#裁剪)、[剪除](../reference/glossary.md#剪除))更便宜,
  见[上下文经济学](context.md)。

## 旋钮

| 症状 | 拧哪个 |
|---|---|
| 换代太频繁,活总被打断 | `--window` 调到模型真实窗口(`-v` 能看到生效的模型名) |
| 一开局就换代,还报“启动地板” | 同上,`window` 配小了 |
| 交接总是降级 | 看 `runs/manifest.json` 的 `errors`,里面写了降级原因 |
| 接手的人老是重复上一代干过的活 | 交接的“走不通的路”写得太薄。可以直接改那个文件 |
| 想事后读交接却找不到文件 | 没开工作台。交接不落盘,只走了 prompt |
| 就想用 compact | `--no-handoff` |

## 相关

- [接续](continuity.md) —— 跨进程接上上一次运行,和这一页是同一件事的两个方向
- [上下文经济学](context.md) —— 当场就剪的那几层
- [目标看守](goal.md) —— “干活的人有系统性乐观偏差”那条论证
- [Python API](../reference/api.md) —— `HandoffPolicy`、`Handoff`、`CompactPolicy`、`default_window`、`StepResult`
- [命令行](../reference/cli.md) —— `--window`、`--no-handoff`
- 源码:[`core/handoff.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/handoff.py) ·
  [`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py) ·
  [`core/runtime.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/runtime.py)
