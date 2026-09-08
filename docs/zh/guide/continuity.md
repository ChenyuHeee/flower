# 接续

在同一个目录再跑一次 `flower`,它接着上次那段对话往下说 —— 进程被 kill、终端崩了、
机器重启,都一样。你不需要知道 session 这个词,也不需要记住任何 id。这一页讲它靠什么成立、
什么时候会静默失效、以及怎么故意不接续。

!!! note "接续不是换代"
    [接续](../reference/glossary.md#接续)是**跨进程**的:下一个进程接上上一次[运行](../reference/glossary.md#运行)。
    [换代](../reference/glossary.md#换代)是**同一次运行内部**的:上下文快满了,当前[会话](../reference/glossary.md#会话)
    写一份[交接书](../reference/glossary.md#交接书),换一条新会话接手 —— 见[换代](handoff.md)。

    两者自动咬合,不需要额外接线:[血缘](../reference/glossary.md#血缘)记的永远是那一步**最后**
    接班的那条会话,所以下次唤醒接的就是接班人。

## 解决什么问题

磁盘上其实什么都在。`runs/sessions.db` 有每条历史会话的**完整** transcript,`需求.md` / `目标.md`
是冻结件,代码就在工作区。

**丢的只有一行映射** —— "哪一步用了哪个 session"。它以前只活在内存的 `ctx["_sessions"]` 里,
进程一退就没了。于是新进程起来,[协调者](../reference/glossary.md#协调者)是个失忆的新人:它派过谁、
试过哪些死路、为什么否掉某个方案,统统重来一遍。

[HT002](../cases/ht002.md) 里它绕了一小时去试编译 flag。换个进程,那一小时白走。

## 怎么用(最小代码)

命令行什么都不用配,`flower` 这条路径默认开着接续:

```bash
cd ~/proj && flower "写个 md 转 html 的脚本"     # 第一次
# …跑完,或者你按 Ctrl-C 走人,或者机器重启了

cd ~/proj && flower "顺便支持代码块高亮"          # 接着上次那段对话
cd ~/proj && flower                              # 什么都不说 = 接着做
cd ~/proj && flower --new "另一件事"              # 这次别接上次
```

自己写[流程](../reference/glossary.md#流程)时,接续也是默认开的 —— `Workflow.continuous` 的默认值就是
`True`:

```python
import asyncio

from flower import AgentSpec, Runtime, Step, Workflow

terse = AgentSpec(
    name="terse",
    instructions="回答极简,一行以内,不解释不寒暄。",
    allowed_tools=["Read", "Glob"],
    max_turns=4,
)


async def main() -> None:
    wf = Workflow([Step("取词", terse, "读 seed.txt,只回文件里那个词。")])   # continuous 默认 True
    rt = Runtime(workspace=".", run_dir="runs")
    try:
        ctx = await wf.run(rt)
    finally:
        rt.close()
    print(ctx["_woke"])                  # 第几次唤醒,第一次跑是 1
    print(ctx["_sessions"])              # {"取词": "<session_id>"}


asyncio.run(main())
```

在同一个目录第二次执行这段代码,`ctx["_woke"]` 是 `2`,而 `ctx["_sessions"]["取词"]` 和第一次
**是同一个 id** —— "取词"这一步续跑了上次那条会话,而不是开了新的。

!!! tip "只想知道这个目录接不接得上"
    `wake_state()` 是只读探测,**一个字节都不写**:

    ```python
    from flower import wake_state

    st = wake_state(".", run_dir="runs")
    print(st["waking"], st["checks"], st["woke"], st["steps"])
    ```

    返回 `{"waking", "brief", "goal", "checks", "woke", "steps"}`。`waking` = 需求确认书存在且四段齐全;
    `checks` = 判定清单几条;`woke` = 已经唤醒过几次;`steps` = 步骤名到 session_id 的映射。
    命令行就是靠它决定提示符该问"要做什么"还是"接着上次"。

## 它实际做了什么

### 落在磁盘上的三个文件

`run_dir` 默认是 `./runs`,**相对当前工作目录,不是相对 workspace**。

| 路径 | 放什么 |
|---|---|
| `runs/lineage.json` | 血缘:`{"workspace": "…", "woke": N, "steps": {"步骤名": "session_id"}}`。接续全靠它 |
| `runs/sessions.db` | SQLite,全量 transcript。表是 `entries` / `meta` / `summaries`,key 是 `project_key/session_id[/subpath]` —— subagent 的 transcript 用 subpath 分开存 |
| `runs/manifest.json` | JSON 数组,**跨进程累积**的运行清单。每步一行,是事后查 session_id 的唯一去处 |

血缘文件长这样:

```json
{
  "workspace": "/Users/you/proj",
  "woke": 3,
  "steps": {"干活": "47395075-bec7-466e-80cd-f4d60b360235"}
}
```

`manifest.json` 每行是 `StepResult` 的全部字段 —— `step`、`session_id`、`ok`、`cost_usd`、
`num_turns`、`text`、`error`、`started_at`、`ended_at`、`attempts`、`errors[]`、`resumed`、
`retired[]`、`context` —— 外加手工补的 `duration_s`(它是 `@property`,`asdict()` 收不到)和
`run`(进程标记,`YYYYmmdd-HHMMSS-<6 位 hex>`)。

步骤名在里面有四种形态,一眼能看出这一步是怎么走完的:`<步骤名>`(第一次尝试)、
`<步骤名>#retry<N>`(普通重试)、`<步骤名>#round<N>`(判定没过、打回来接着做)、
`<步骤名>·判定#<N>`([判定者](../reference/glossary.md#判定者)那一轮)。

写盘是**追加不覆盖**:每次落盘都重读一遍文件,按 `run` 字段去重 —— 属于本进程的行换成最新的,
别人的行原样留着。所以同一个目录并行跑多个 flower 是安全的。

### `continuous=True` 改变了 `resume_from` 的语义

这是最容易被漏掉的一条:`Workflow.continuous` 默认 `True`,于是 `resume_from=None`
**不等于"全新会话"**。

| 写法 | 同一次运行内 | 跨进程(`continuous=True`) |
|---|---|---|
| `resume_from=None`(默认) | 新会话,只靠 prompt 里传入的上下文 | **取血缘里同名步骤的 session 续跑** |
| `resume_from="上一步名"` | 续跑同一会话,完整上下文 | 同左 |
| `resume_from=…, fork=True` | 分叉,不污染原会话 | 同左 |

要每次进程都是干净的新会话,得显式写 `Workflow(..., continuous=False)`。

装载血缘时还有一道验证:读回来的每个 `(步骤名, session_id)` 都先用 `runtime.has_session(sid)`
确认它还在 `sessions.db` 里,活着才用。理由是血缘文件可能比 `sessions.db` 活得久,
而 resume 一个不存在的 session 要等子进程起来才炸。

!!! warning "步骤名是跨进程稳定的键"
    血缘按 `Step.name` 索引。**改了步骤名就等于断了血缘** —— 不会报错,只是下次跑变成全新会话。
    带后缀的名字(`#retry`、`#round`、`·判定#`)不进血缘,`Lineage.remember` 用的永远是原名。

### 两条不变式

**一、拿到 session_id 就立刻写盘,不等步骤跑完。**

进程被硬杀正是要防的场景。实测栽过:2026-09-07 Terminal.app 崩了两次,内核发 SIGHUP,
而 SIGHUP 的默认动作是直接终止,`finally` 一行都不跑。当时血缘是在**步骤边界**写的,
于是死在第一步之内的那次运行 `steps` 是空的,人被要求重答一遍已经答过的问题(见 issue #6)。

现在 `Runtime.on_session` 在拿到 id 的那一刻就落盘 —— 实际最早是第一条 assistant 消息,
init 系统消息在 Python SDK 里不带 `session_id`。写的时候先写 `.tmp` 再原子替换,
半途被杀不会留下半份文件;落盘失败(`OSError`)被静默吞掉,不带走这次运行。

这个钩子**只罩 `runtime.run` 这一句**,gate 之前用 `try/finally` 摘掉。判定者用的是同一个
`Runtime`,还挂着的话它的 session 会被写进干活那一步的血缘。

**二、对不上就当没有,不报错。**

三种对不上:工作区路径变了(目录被拷走 —— [HT001](../cases/ht001.md) 就是从容器里拷出来的)、
session 已经不在库里(删过 `sessions.db`)、血缘文件坏了。任何一种都静默退回"从头开始"。

`workspace` 那个字段是守卫:SDK 的 `project_key` 从工作区路径推导(`/`、`_`、`.` 全换成 `-`),
目录被拷走之后旧 session_id 在新位置根本查不到,所以路径对不上就当没有。

**接续是锦上添花,它失效不该拦住人干活。**

### 进程被杀,和机器重启

两件事的结果一样 —— 都接得上 —— 但过程不同:

| 情况 | 发生了什么 | 下次跑 |
|---|---|---|
| `Ctrl-C` 一次 | 协作式打断,在**消息边界**干净断开。可以顺便说一句话,同一进程内 resume 同一条会话接着跑。打断不算失败尝试,不吃重试额度 | 不涉及接续 |
| `Ctrl-C` 两次 | 直接抛 `KeyboardInterrupt` 退出。收尾只做到关存储,**在飞的那一步不进 `manifest.json`** | 血缘早就落盘了,接得上 |
| `SIGTERM` / `SIGHUP` | 处理器先调 `rescue()`,把在飞的那一步也写进 `manifest.json`(标 `error="killed-by-signal"`),再恢复默认动作真的走掉 | 同上,接得上 |
| `SIGKILL`、断电、机器重启 | 什么收尾都没有 | 一样接得上 —— 三个文件都在磁盘上,血缘是拿到 id 那一刻就写的 |

前提只有一条:**同一个 `workspace` 加同一个 `run_dir`**。`run_dir` 相对当前工作目录,
所以从别的目录敲 `flower` 会去找另一个 `runs/`,接不上。

### 判定者永远是新会话

这一条是**构造上保证**的,不是靠记得。

判定者不是一个 `Step` —— 它是 `with_goal` 的 gate 里直接 `rt.run()` 派出去的
(见[目标看守](goal.md)),从来不经过血缘那条路。所以它每一轮、每一次唤醒都是全新的一双眼睛。

那正是它的全部价值:**它不知道执行者试了多少次、有多辛苦,也就不会替它找理由。**
让它跟着接续,目标看守就退化成了自我审计。

`tests/lineage_offline.py` 第 4 节把这条钉死了。

### 唤醒时说的那句话,要落到三个地方

`flower "顺便支持代码块高亮"` 在用过的目录里,**不是新任务,是又说了一句话**。
它同时做三件事 —— 少一件都会静默失效:

| 落到哪 | 少了会怎样 |
|---|---|
| 追加进 `需求.md`(`## 唤醒时追加`) | 活不过步骤边界。下一步是新 session,只读冻结件 |
| 当作干活那步的 prompt | 协调者根本收不到 |
| **触发重新推导 `目标.md`** | 判定者读的还是老清单,**新加的事做没做完根本不进判定** |

第三条最容易漏。判定者只读冻结的 `目标.md`,你中途加的东西它看不见 —— 不重推的话它会按老清单
判"达成",而你要的那件事压根没验。代价是每次追加多跑一次设目标([HT002](../cases/ht002.md) 实测
$0.41 / 3 分钟)。

**什么都不说地唤醒**(直接回车)则不追加、不重推,一分钱不多花。

### 崩在第一步(确认需求)之内也能接上

`clarify_step` 带了 `resume_prompt`(常量 `CLARIFY_RESUME`):崩在确认途中再启动,
对[确认者](../reference/glossary.md#确认者)说的是"接着刚才那次没问完的需求确认继续 ——
不是重新开始",而不是把原始诉求当新任务重发一遍。配合上面那条"拿到 session_id 立刻写盘",
死在第一步、`需求.md` 还没冻结的那次现在也接得上,不用重答。

反过来,已经冻结的前置步骤会被**整步跳过**:`需求.md` 四段齐全就跳过确认需求(但内容仍灌进 ctx),
`目标.md` 齐全就跳过设定目标。

### 接续时发的不是同一句话

`Step.resume_prompt` 管这个。对方的上下文里**已经有**确认书、目标、上次干到哪了,再把
"照这份需求做:<整份确认书>"原样发一遍是纯噪音,更糟的是它会被读成"需求变了,重新看一遍"。

不给 `resume_prompt` 就沿用 `prompt` —— 有些步骤本来就该重发全文(设定目标重推清单时,
它要的正是那份完整确认书)。

### 唤醒时先报一行

```text
<- 在 ~/explore/test-ide 接上上次  需求已确认 · 目标 15 条 · 干活上下文 80.2K · 第 3 次唤醒

== 干活 ==============================  3/3  <- 接上次 · 第 3 次唤醒
```

不报的话"它到底记不记得"完全不可感知,而那正是这一层的全部价值。横幅里
`需求已确认` 恒有,`目标 N 条` 仅当判定清单非空,`干活上下文 X` 需要能从 `sessions.db`
查到那条会话最后一轮的上下文规模。

**上下文那个数字是刻意摆出来的** —— 理由见下面"代价"那节。

### 韧性:断网时挂着等,而且错误不进接续后的上下文

[韧性](../reference/glossary.md#韧性)和接续是配套的:一次跑几小时,网络必然断一次,而默认行为很糟 ——
断线那一刻 harness 会往 transcript 里塞一条**合成 assistant 消息**(`isApiErrorMessage=true`、
`model="<synthetic>"`),正文是 "API Error: Can't reach the API server …"。这条消息成了会话的叶子,
之后 resume 就被当成"模型上一句说的话"喂回去,模型会以为自己在讨论网络故障。

`Resilience` 做三件事:

**一、探针只做 DNS + TCP。** `reachable(host, port, timeout=5.0)` 只跑 `getaddrinfo` 加一次 TCP 握手,
**不发 HTTP、不带凭证、不花钱**,任何异常都算不可达。探哪个地址由 `endpoint()` 决定,它跟着
`ANTHROPIC_BASE_URL` 走,默认 `https://api.anthropic.com`,端口默认 `443`(http 是 `80`)。
**用自建网关就必须探网关** —— `api.anthropic.com` 通说明不了网关通。

**二、分清该等的和该停的。** `classify(text)` 返回 `"transient"` / `"fatal"` / `"unknown"`,
**先判 fatal 再判 transient** —— 401 之类的文本常带 "connection" 字样,顺序反了会死等。
默认值:`max_attempts=6`(含首次)、`base_delay=4.0`、`max_delay=120.0`、`probe_timeout=5.0`、
`probe_interval=15.0`、`max_offline_wait=3600.0`(1 小时)、`retry_unknown=True`。
退避是 `min(base_delay * 2**(attempt-1), max_delay)` 再乘 ±25% 抖动。

拿到过 session_id 就 **resume 续跑而不是重来**,之前的花费不白费。续跑时发的是
`Resilience.resume_prompt`:"上一轮在中途被打断,没有跑完。检查一下工作台里已经落盘的东西,
从中断处接着做,不要重头来过。"它**有意不含任何错误细节** —— 模型需要知道"被打断了、接着做",
不需要知道是 ENOTFOUND 还是 503。

**三、重试风暴产生的报错不进 resume 之后的上下文。** 这是[剪除](../reference/glossary.md#剪除)干的活。
`Runtime` 的会话存储写死是 `PruningSessionStore`,它在 `load()` 时做三件事:

- 摘掉合成 API 错误消息。**SQLite 里原样保留**,只是不喂回去
- 摘掉过早的被拒调用,只留最近 `keep_denials=1` 条
- 把中断残留的 `tool_result` 换成中性说明"[上一轮在此处被中断,该工具结果未产生]",只换正文不摘条目

留 1 条而不是 0 条是有理由的:被拒调用从没执行过,结果里没信息,却占位不小
(实测一次 273 字符 = 93 字拒绝语 + 180 字**死命令原文**),而且**它会误导** ——
实测协调者读到几条"不直接使用 Bash"之后,连放行的 `git status` 都不再尝试,学成了习得性无助。
但最新那一条留着有用:能防止模型在同一轮里反复重试同一条被拦的命令。

摘除有一条结构性红线:transcript 是 `parentUuid` 单链,摘掉一条就必须把它的孩子接到最近的存活祖先,
否则链断在那儿、前面的历史全丢。

[HT001](../cases/ht001.md) 实测撞上过一次:断网时间线 01:52:40 → 01:55:41,`manifest.json` 里那一步是
`attempts=2` / `resumed=True` / `ok=True`,续跑之后又跑了 8 个多小时到完成。

最后一条容易误会:**`Runtime(trim=False)` 不等于"什么都不清"**。`trim` 默认就是 `False`,
但它只关掉**大工具结果[裁剪](../reference/glossary.md#裁剪)**那一层。摘断线残渣、摘被拒调用、
中断残留中性化、[一次性命令](../reference/glossary.md#一次性命令)结果标过期 —— 这四件照做
(`ephemeral` 默认 `True`,`keep_denials` 默认 `1`)。

### 代价:上下文会一直涨,而且没有尽头

这是接续的固有代价,不是 bug。

[HT001](../cases/ht001.md) 的"干活"一步连跑 10.44 小时,[主线程](../reference/glossary.md#主线程)上下文
第 1 轮 **28.7K**、第 20 轮 **35.2K**、第 35 轮 **108.6K**、第 50 轮 **158.2K**、第 70 轮 **185.9K**,
单调涨,斜率约 **2.2K/轮**;全程未压缩,用掉 1M 窗口的 **18.6%**。按这个斜率外推,
撞墙在约 **440 轮** —— 当前形态"长程"的上限大约是那次的 **6 倍**。永久接续意味着某天会撞窗口。

两层机制在管它:

1. **裁剪**(`flower --no-trim` 可关,`flower` 这条路径默认开)—— resume 时把旧的大工具结果换成
   文件指针,内容没丢,只是不常驻
2. **[换代](handoff.md)** —— 到阈值就写一份交接换新会话。**不是[压缩](../reference/glossary.md#压缩)**:
   文书可读可改,你看得见丢了什么。上下文因此会周期性回落,而不是一路涨到撞墙

**所以唤醒那行必须报上下文数字**:人看得见,才有机会在撞墙之前自己决定重开。

顺带一条:`--rounds`(干活总轮数)**每次唤醒重置**。这是有意的 —— 新的一次唤醒是新的意图,
不该继承上次用掉的轮数。

### 重开一件事

```bash
flower --new "另一件事"
```

或者在唤醒提示符里直接打 `/new`:

```text
接着上次? 直接回车 = 接着做;也可以说点新的;/new = 重开一件事(Ctrl-C 退出)
> /new
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> …
```

**归档,不删。** `lineage.json`、`需求.md`、`目标.md` 一起**移进** `notes/archive/<YYYYmmdd-HHMMSS>/`,
血缘的 `steps` 和 `woke` 同时清零。三样是同一段历史的三个面,只收其中一部分会留下"目标还在但对话没了"
这种半截状态。

`sessions.db` 不动 —— 它是档案,里面每一段 transcript 都还能查。

写代码时对应的是 `Lineage.archive(into, extra=[...])`。

## 什么时候不该用它

- **要求每次都是干净起点的场景。** 批量跑同一个流程、做对照评测、给别人复现一个 bug ——
  这些都不该带上上次的上下文。写 `Workflow(..., continuous=False)`,或者每次换一个 `run_dir`。
- **目录会被搬走、拷走,或者 `run_dir` 不持久。** 在容器里跑而 `runs/` 落在容器内层文件系统上,
  或者把工作区 rsync 到另一台机器 —— 接续会**静默失效**(路径守卫会拒掉对不上的血缘),
  别把它当成一个保证。
- **这次是新意图,而上下文已经很大。** 接续会把无关的历史一起背上,每一轮都在为它付 token。
  与其忍着,不如 `--new` 归档重开。
- **一次性单 agent。** `flower once` 不走 `Workflow`,没有血缘;要续跑得自己给 `--resume <session_id>`。
- **拿接续当备份。** 它只记"哪一步用了哪个 session"。代码、产出、决策该落在工作区和
  [工作台](../reference/glossary.md#工作台)里,不该指望从 transcript 里刨回来。

## 接着读什么 {#相关}

- [换代](handoff.md) —— 同一次运行内部上下文满了怎么办,和这一页是同一件事的两个方向
- [目标看守](goal.md) —— 判定者为什么不接续
- [上下文经济学](context.md) —— 裁剪、剪除、落盘各自管什么
- [Python API](../reference/api.md) —— `Lineage`、`Workflow.continuous`、`Step.resume_prompt`、`wake_state`
- [命令行](../reference/cli.md) —— `--new`、`--no-trim`、`--rounds`、`-r/--run-dir`
- 源码:[`core/lineage.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/lineage.py) ·
  [`core/resilience.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/core/resilience.py) ·
  [`stores/prune.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/stores/prune.py) ·
  [`workflow/base.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/base.py)
