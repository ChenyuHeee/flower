# 上下文经济学

[主线程](../reference/glossary.md#主线程)的上下文是一次[长程](../reference/glossary.md#长程)运行里
唯一贯穿始终的东西,它装什么、不装什么,决定了这次运行能跑多远。flower 的形状 ——
[协调者](../reference/glossary.md#协调者)不动手、长产出落盘、hook 当场剪枝 —— 全是从这一条推出来的。
这一页讲的是为什么。

## 解决什么问题 {#解决什么问题}

[压缩](../reference/glossary.md#压缩)是等上下文满了再回头总结,治的是标。真正的问题是:
**琐碎的东西一开始就不该进主线程。**

差别在时机。一次 `pytest` 的输出动辄几万字符,模型看一眼、拿一个结论,剩下的字符从此
每一轮都重新发一遍;等窗口撑满,压缩把它连同旁边的决策一起总结成一段摘要 —— 省下的是体积,
丢掉的是"当初为什么这么定"。auto-compact 的触发阈值是**窗口 − 33k**
([`core/agent.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/agent.py)),
到那一刻,该丢的和不该丢的已经躺在一起了。

flower 用四层解决,顺序就是优先级 —— 按省得多少排:

| 层 | 做什么 | 在哪 |
|---|---|---|
| 一、分工 | 动手的活派给 [subagent](../reference/glossary.md#subagent),试错进它自己的 transcript | [`core/roles.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/roles.py) |
| 二、工作台 | 脚本 / 长产出 / 决策落盘,索引注入 system prompt | [`core/workbench.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/workbench.py) |
| 三、当场落盘 | `PostToolUse` hook 把超阈值的工具结果落盘,上下文里只留一行路径 | [`core/guard.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/guard.py) |
| 四、裁剪与剪除 | resume 之前重写会话:过期结果、被拒调用、断线残渣不再喂回去 | [`stores/trim.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/trim.py)、[`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) |

前两层管**东西进不进来**,后两层管**已经进来的留不留**。顺序不能倒:第四层再狠,
也追不回第一层漏进来的量。

## 怎么用(最小代码) {#怎么用最小代码}

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件:统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成,不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model 默认 "inherit"

主控 = coordinator("主控", "目标:摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

这几行装上了前三层:`coordinator()` 恒设 `delegate_only=True`(第一层);`workbench=True` 建
[工作台](../reference/glossary.md#工作台)并把索引注入协调者的 system prompt(第二层),
同时让 `Runtime` 装上 `spill_guard`(第三层)。第四层默认就在 —— `Runtime` 的
[会话存储](../reference/glossary.md#会话存储)写死是 `PruningSessionStore`,构造参数里没有换它的入口。

!!! warning "`workbench=True` 不是可选项"
    拦住协调者动手的 `delegate_guard` 挂在 `workbench_hooks` 里,而 `workbench_hooks` 只在
    `Runtime` 有工作台时才装;`whitelist_guard` 又因为 `delegate_only=True` 被跳过。
    结论:**`Runtime(workbench=False)` 配 `coordinator()` 时,主线程的 Bash / Write / Edit
    一道墙都没有。**

## 它实际做了什么 {#它实际做了什么}

### 第一层:分工(省得最多) {#第一层分工省得最多}

协调者扮演"一个会用 Claude Code 的人":拆解、派活、读报告、决策。它拿不到
Bash / Write / Edit —— 工具只有 `Agent`、`TodoWrite`、`Read`
(`glance=True` 时另加一个受限的 `Bash`,见下)。动手的活全派给
[执行者](../reference/glossary.md#执行者)。

**什么时候触发**:主线程每次调 `Bash|Write|Edit|NotebookEdit`,`PreToolUse` hook
`delegate_guard` 当场 deny,并且指路 —— "用 Agent 工具派一个 subagent 去做,任务里写清目标与
验收标准,并要求它把长产出写进 `.flower/artifacts/`、回话只给路径与结论"。subagent 一律放行。
判据是 hook 数据里有没有 `agent_id`:**没有的就是主线程**。

**省多少**:subagent 的工具调用与试错**进的是它自己的 transcript**(会话存储里用 `subpath`
区分),主线程只留下那一次 `Agent` 调用和最终报告。试错过程不是被压缩掉的,是**从来没进过
主线程**。

- 实测(一个会产生大量工具输出的任务):83% 的 transcript 落在 subagent 里,
  主线程 13 条、21K 字符,subagent 105K 字符。
- 实测(真实规模,一次 10.4 小时的运行,见 [HT001](../cases/ht001.md)):subagent 承担
  **97.7%** 轮次、**94.8%** 正文字符;1,893 次动手工具调用 vs 主线程 32 次(**59:1**)。
  早期压缩不再是主线。

两行是两次不同的测量:上面是早先的小规模测试,下面是真实规模下的复测。同一个机制,
规模越大省得越多。

省的是上下文,不是模型档次:`worker()` 默认 `model="inherit"` —— 执行者不该被降级。

分工唯一的反向成本是[任务书](../reference/glossary.md#任务书) —— 协调者派活时写的那段话,
它进主线程,而且永久留着。实测 8/8 份任务书都在复述对方已知的纪律,最短一份 521 字符里
只有约 120 字符是任务专属的,一轮白占约 4.8k 永久上下文。所以 `COORDINATOR_RULES` 里写死了
一条:**任务书只写这次任务专属的东西**。唯一还需要交代的规矩是"工作台在哪 + 长产出写
`artifacts/` + 回话只给路径与结论" —— 因为工作台索引进不了 subagent,任务书是唯一通道。

### 第二层:工作台(治"每次重写") {#第二层工作台治每次重写}

`.flower/` 下三个目录随工作区走:

| 目录 | 放什么 | 解决什么 |
|---|---|---|
| `scripts/` | 会跑第二次的验证 / 复现脚本,首行写 `# desc: 一句话` | 写一次,以后直接跑。不再"压缩后丢失,每次重新编写" |
| `artifacts/` | 超过 2000 字符的长产出:日志、数据、报告、diff | 对话里只出现路径和结论 |
| `notes/` | 关键决策与理由,一个决策一个文件 | 被压缩、被重启、换机器,结论都还在 |

**什么时候触发**:`INDEX.md` 自动生成(默认最多 40 条),`refresh()` 由 `PostToolUse` 的
`index_guard` 在 `Write` / `Edit` 落在工作台内时调用,每一步开跑前也会刷一次。上面这三条规矩
由 `prompt_block()` 注入协调者的 system prompt —— 它开局就知道有哪些现成脚本,
不用先花一次工具调用去发现。

**省多少**:实测一次 10.4 小时的运行,**61 个脚本被写 95 次、被执行 331 次;92% 执行过不止
一次,写了没跑的 0 个**。定性上 `audit-fake-ai-server.py` 被 7 个脚本复用。

这一层之所以有效,靠的是一个差别:压缩清得掉上下文,**清不掉磁盘,也清不掉 system prompt
里的索引**。

!!! warning "索引 subagent 继承不到"
    索引走的是会话级的 `system_prompt.append`,subagent 有自己的 system prompt,
    **继承不到**(实测 $0.2461,`tests/prelude_live.py`)。所以"工作台在哪 + 长产出写
    `artifacts/`"必须由协调者在任务书里转述 —— 那是唯一通道,不是冗余。

### 第三层:当场落盘 {#第三层当场落盘}

`spill_guard` 是一个 `PostToolUse` hook,在工具结果**进模型之前**看一眼:超过 `threshold`
(默认 **4000** 字符)的,[落盘](../reference/glossary.md#落盘)到工作台的 `spill/` 目录,
上下文里换成一行指针 + **开头 400 字符**。内容没丢,只是不常驻。

**什么时候触发**:matcher 是 `Bash|Read|Grep|Glob|WebFetch|WebSearch`;默认 `main_only=False`,
所以 subagent 的结果也落盘。它只替换工具输出结构里过长的**字符串字段**,list 一律不碰
(里面可能是图片块),因为 `updatedToolOutput` 必须保持原工具的输出结构。

**读落盘文件本身放行,不再落盘。** 否则那行提示里的"需要全文用 Read 读它"是句空话:
读回来又超阈值、又被落盘、又给它一行指针,无限循环。实测撞到过(`tests/handoff_live.py`
头一次真跑),模型连试五种写法绕,自己说 "The spill read loops back on itself",
最后靠 40 行一段硬啃,白烧七八轮。落盘的意义是"**不自动**把大东西塞进上下文";
它自己决定要看全文,那是它的选择。

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None 或 0 = 不装这个 hook
```

**省多少**:[HT001](../cases/ht001.md) 那次运行里,103 次 spill、791.4K 字符换成了路径指针,
没有常驻上下文。

### 第四层:裁剪与剪除 {#第四层裁剪与剪除}

这一层在[会话存储](../reference/glossary.md#会话存储)里。`Runtime` 的 store 永远是
`PruningSessionStore`(继承链 `SqliteSessionStore` ← `TrimmingSessionStore` ←
`PruningSessionStore`),它在 `load()` —— 也就是 **resume 之前** —— 把要喂回去的历史重写一遍。
SQLite 里的原文一个字都不动。四件事:

**① 时效性过期**(`ephemeral`,默认开)。`git status`、`ls`、`cat` 这类
[一次性命令](../reference/glossary.md#一次性命令)的结果,几轮之后正文换成一句说明,
保留最近 6 个。过期内容**不落盘** —— 归档一份旧的 `git status` 没有意义,重跑一次就有:

```text
[`git status -s` 的结果已过期(第 7 轮前),当前状态可能已变。需要请重新执行]
```

活体 resume 实测 `expired: 2`;真实 transcript 上把 `keep_recent` 调到 2,过期 5 条。

**② [裁剪](../reference/glossary.md#裁剪)**(`trim`,**默认关**)。`>= 2000` 字符的 tool_result
正文落盘到 `<workspace>/.flower/spill/`,块内容换成文件指针,保留最近 20 个原文。注意这个目录
和第三层 `spill_guard` 的落盘目录**不是同一个**:后者写在工作台根目录下,而这里的必须落在
工作区内,否则 agent 的 `Read` 够不到。

```python
from flower import Runtime, TrimPolicy

Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))   # True 也行
```

**③ [剪除](../reference/glossary.md#剪除)被拒的调用**(`keep_denials`,默认 1)。拦下来这个
动作本身也会污染上下文:拒绝消息是一条 `tool_result`,和那条**从来没执行过的命令**一起永久
留着。实测一次 273 字符(93 字拒绝语 + 180 字死命令),死命令比拒绝语还贵。

比 token 更要紧的是它**会误导**:实测协调者读到几条"不直接使用 Bash"之后,连放行的
`git status` 都不再尝试,直接说"Bash 被限制了,派个 agent 去看" —— 学成了习得性无助,
反而多花一次 subagent 启动。默认留 1 条而不是 0:最新那次拒绝是有效信号,能防止模型在同一轮里
反复重试同一条被拦的命令。识别靠 harness 自己打的结构性标记 `toolDenialKind: "permission-rule"`,
不是匹配文案 —— 文案随时会改,标记不会。活体实测:2 次被拒 → 摘 1 留 1,链未断,resume 正常
且模型仍知道发生过什么。

**④ 剪除断线残渣**。断网重试期间产生的合成 API 错误消息不喂回去;被中断留下的 `tool_result`
换成一句中性说明(`[上一轮在此处被中断,该工具结果未产生]`),条目本身保留。

**摘除时的红线**:`tool_use` 和它的 `tool_result` 必须**一起**摘(少一个就是
`Missing Tool Result Block`),同一条 assistant 消息里的其它调用不能误伤,`parentUuid` 链必须
重新接上。

`Runtime(trim=False)`(默认)**不等于什么都不清**:它只关掉大结果裁剪,过期、被拒调用、
断线残渣照做。

### 反例:看一眼的活自己干 {#反例看一眼的活自己干}

前三层都在说"派出去",但有个反例:`git status`、`ls`、`cat` 这种命令,结果几十个字符,
而**派一个 subagent 光启动就要约 4.3k 上下文**(实测,不可摊薄)。为一条 `ls` 付这个价钱是净亏。

所以协调者拿回一个受限的 Bash(`coordinator(..., glance=True)`,默认开)。判据不是"命令短",
而是**结果会不会过期**,并且"放行"和"过期"由同一个函数 `is_ephemeral()` 决定:

| | 放行自己跑 | 结果会被标记过期 |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ | ✓ |
| `git commit` / `pytest` / `pip install` | ✗ 派人 | — |

两边必须是同一张表,否则任一边单独成立都有害:**放行了不裁剪**,过期的 `git status` 就永久
占着上下文,还会被当成现状误导决策;**裁剪了不放行**,协调者就得为一条 `ls` 付 4.3k。
`tests/glance.py` 把这条不变式钉成断言 —— 实测 46 条命令两边判定完全一致,含 10 条对抗样本。

**坑(踩过两次)**:模型不会写单条命令,它写的是
`git status -s && echo "--- LOG ---" && git log --oneline -10`。第一版一刀切拒绝所有含
`&&` / `|` / `2>&1` 的命令,结果 **glance 完全失效** —— 实测协调者三次尝试全被拦,只好回去派
subagent。现在是逐段拆开检查:每一段都在白名单里才放行,`git status && rm -rf x` 照样拦
(后半段不在表里)。

### 叠加,不替换 {#叠加不替换}

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

`build_options()` 把 `AgentSpec` 编译成 SDK 选项时,`instructions` 走的是
[`append`](../reference/glossary.md#叠加) —— 追加在 Claude Code 原生系统提示词**之后**,
不是替换。所以上面那些纪律文本(`COORDINATOR_RULES`、`WORKER_RULES` 等)是加法:
**专门化不以损失通用能力为代价。**

工作台索引也走这条通道。它每一轮都在,但它是 system prompt 的一部分,不占对话历史,
压缩也清不掉它 —— 代价就是上面那条:**只到协调者**。

!!! warning "不要用 `disallowed_tools` 让协调者不动手"
    `disallowed_tools` 是**会话级**的,会把 subagent 一起禁掉。实测报错原文:

    ```text
    Bash is disabled for this session, in subagents as well as here
    ```

    正确做法是两步:`allowed_tools` 里不给,再用 `PreToolUse` hook 按 `agent_id` 只拦主线程。
    `coordinator()` 已经这么做了 —— 它设 `delegate_only=True`,由 `delegate_guard` 拦主线程、
    放行 subagent。

    只靠 `allowed_tools` 也不够:它是**免审批清单,不是排他白名单**。实测模型能调用不在里面的
    工具 —— 一个 $0.1 的探针里,`allowed_tools=["Read"]` 的 agent 照样调得动 Write / Bash。
    真正拦住的是 hook。

    **`allowed_tools` 也是会话级的,同一课上了两遍。** 不在这份清单里的工具,**subagent**
    调用时同样要走权限审批。无人值守时没人批,于是既不报错也不停下,模型反复重试同一个调用
    (`toolDenialKind=user-rejected`)。实测:给执行者加了 `WebFetch`/`WebSearch` 却只写进
    `AgentDefinition.tools`,那次运行二十多次 user-rejected、一个字都没产出(`roles.py:513-518`)。
    症状比 `disallowed_tools` 难查 —— 后者当场报错,前者屏幕上什么都不像出错。
    所以 `coordinator()` 现在会把手下执行者的只读 web 工具并进自己的 `allowed_tools`
    (`roles.py:523-526`),而 `Write`/`Edit`/`Bash` **故意不并** —— 并了就等于把上面那道
    hook 拆掉。

## 什么时候不该用它 {#什么时候不该用它}

这四层省的都是**现场**。下面这些问题它们不解决,有的还会因为它们更难被看见:

1. **目标理解错了 —— 这四层会让它变严重。** 现场被丢掉之后,留下来的恰恰是那条建在错误前提上的
   决策,而且它**看起来和正确决策一模一样**。长程把它放大到最坏:错误前提先跑几小时、派十几个
   subagent、在磁盘落一堆产出,之后才暴露。到那时贵的不是 token,是每一个产出都是照错的需求
   建的。挡这个的是[前置确认](clarify.md),不是这一页的任何一层。
2. **主线程仍然单调增长。** 四层压的是斜率,不是方向。实测:主线程 70 轮从 28.7K 涨到 185.9K,
   斜率 2.2K/轮,全程未压缩,用掉 1M 窗口 18.6%,**外推约 440 轮撞墙**。要跨过那道墙靠的是
   [换代](handoff.md)。
3. **关掉全量压缩之后没有兜底。** 换代开着时,`Runtime` 会强制给 spec 设
   `CompactPolicy(mode="no_summary")`,auto-compact 就此关闭(spec 自己显式给了 `compact` 才
   尊重它)。撞上限是硬错,所以这四层必须和换代配套用,不能只是把压缩关掉了事。
4. **第四层只在 resume 时生效。** 裁剪与剪除都发生在 `load()`,一次连续跑着的会话不会因为它
   变小。按上面的分工做之后,这一层多半也用不上 —— 主线程本来就装不下多少工具结果。
5. **看一眼的活派出去是净亏。** subagent 启动约 4.3k,见上面 glance 那节。
6. **重排上下文之前先算缓存账。** 实测一次运行输入 299.4M token,**96.1% 命中缓存**,
   $171 能成立全靠它。任何改写历史的优化都要先算这笔账。
7. **图片、文档类工具结果不落盘。** `spill_guard` 只改输出结构里的字符串字段,list 一律不碰。

参数的完整默认值与签名见 [Python API](../reference/api.md);术语见[术语表](../reference/glossary.md)。
