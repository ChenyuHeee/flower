# 核心概念

flower 有一批自己的词:运行、步骤、会话、协调者、执行者、前置确认、目标看守、接续、换代。
这一页把它们一次说完,读完之后别的页就不用一边读一边猜。五分钟能读完。

这里只讲概念,**不给 API 签名** —— 要签名去 [Python API](../reference/api.md),
要一句话定义和中英对照去[术语表](../reference/glossary.md),要命令行开关去
[命令行参考](../reference/cli.md)。

## 一次运行是什么形状 {#形状}

三个层级,从大到小:

| 词 | 是什么 | 记在哪 |
|---|---|---|
| [运行](../reference/glossary.md#运行) run | 一次 `Runtime` 从开始到结束的完整过程。走默认路径时,一次运行就是你敲一次 `flower` | `runs/manifest.json` |
| [步骤](../reference/glossary.md#步骤) step | 运行内部的一个可执行单元:拿到一个上下文字典,跑一个 agent,把结果写回字典。屏幕上每一行 `==` 横杠就是一个步骤边界 | 同上,每步一行 |
| [会话](../reference/glossary.md#会话) session | 模型侧的一条上下文。有自己的 `session_id`,可以 resume、可以 fork | `runs/sessions.db` |

它们的嵌套关系不是一一对应:

```text
运行 ── 你敲的这一次 flower
 ├── 步骤 确认需求 ──── 会话 A
 ├── 步骤 设定目标 ──── 会话 B
 └── 步骤 干活 ──────── 会话 C ──[上下文快满]──> 会话 C'
      └── 干活·判定#1 ─ 会话 D
```

- **一个步骤可能烧掉好几条会话。** 上下文快满时它不压缩,而是写一份交接书、开一条新会话接手 ——
  这叫[换代](../reference/glossary.md#换代),发生在**同一次运行内部**。
- **一次新的运行可以接上旧会话。** 同一个目录再敲一次 `flower`,每个步骤会接回上次那条会话 ——
  这叫[接续](../reference/glossary.md#接续),发生在**跨进程**之间。靠 `runs/lineage.json`
  记住"哪个步骤名对应哪条 `session_id`"。
- **判定那一轮永远是一条新会话。** 它不接续、不进血缘 —— 判"做完了没有"的人不能是刚才干活的人。

按顺序串起来的一组步骤叫[流程](../reference/glossary.md#流程)。
`flower` 裸跑时用的是框架自带的三步流程:确认需求 → 设定目标 → 干活。

## 分工:协调者不动手 {#分工}

**这是整套框架建立在上面的那一条。**

[协调者](../reference/glossary.md#协调者)是[主线程](../reference/glossary.md#主线程)上那个 agent。
它拆解任务、派活、读报告、做决策 —— 但它**拿不到 `Write` 和 `Edit`**,
`Bash` 也只够跑 `ls`、`git status` 这类[一次性命令](../reference/glossary.md#一次性命令)看一眼
(由 hook 把关,不靠提示词约束,而且这类结果不进持久化的会话记录)。
它的工具表就是 `Agent`、`TodoWrite`、`Read` 加那个受限的 `Bash`。

真正干活的是[执行者](../reference/glossary.md#执行者) —— 一个由 `Agent` 工具派出去的
[subagent](../reference/glossary.md#subagent)。

**为什么这么分。** subagent 有**自己的一条 transcript**:它读了多少文件、跑了多少次测试、
试错绕了多少弯,全记在那条上;主线程只收到最终报告。而主线程是唯一贯穿整次运行的上下文,
所以它是最需要省的那条。

实测([HT001](../cases/ht001.md),10.4 小时一次运行):

| | 主线程 | subagent | 沉下去的比例 |
|---|---|---|---|
| 模型轮次 | 70 | 3.0K | 97.7% |
| 正文字符 | 200.1K | 3.6M | **94.8%** |
| 工具调用 | 32 | 1,893 | —— |

平均每派一次人,**82 个工具调用主线程根本看不见**。这是省上下文的第一层,也是省得最多的一层;
完整论证见[上下文经济学](../guide/context.md)。

两点容易误解:

- **协调者不是一个更聪明的 agent。** 它和执行者默认用同一个模型档次,省的是上下文,不是模型。
- **回话格式是被约束住的。** 执行者的回话恰好四段 —— 结论 / 依据 / 产出 / 未验证,不超过 30 行,
  禁止贴文件内容、命令输出、日志和 diff 原文。长东西写进[工作台](../reference/glossary.md#工作台)
  的 `artifacts/`,回话里只给路径。

flower 一共五个角色,都是同一套做法:一段注入的规则文本 + 一组工具 + 一组 hook。

| 角色 | 干什么 | 手上有什么 |
|---|---|---|
| [协调者](../reference/glossary.md#协调者) coordinator | 拆活、派人、做决策 | `Agent` `TodoWrite` `Read` + 受限 `Bash` |
| [执行者](../reference/glossary.md#执行者) worker | 写代码、跑测试、查资料 | `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| [确认者](../reference/glossary.md#确认者) clarify | 动手之前只提问,问到清楚为止 | 提问工具 + 只读工具,**没有任何写工具** |
| [判定者](../reference/glossary.md#判定者) judge | 设目标,或者判"这一轮做完了没有" | 提问工具 + `Read` `Glob` `Grep`(要它能跑命令得显式开) |
| [旁路顾问](../reference/glossary.md#旁路顾问) oracle | 运行途中回答"现在到哪了" | `Read` `Glob` `Grep`。**说的话不进那次运行的上下文** |

工厂函数的参数和默认值见 [Python API](../reference/api.md#角色工厂)。

## 长程会坏在四个地方 {#四个机制}

一次[长程](../reference/glossary.md#长程)运行跨越数小时到数天、跨越多次会话、跨越进程重启。
它散架的方式就那么几种,每种对着一个机制:

| 你怕的事 | 机制 | 它做什么 | 详情 |
|---|---|---|---|
| 做出来的不是你想要的 | [前置确认](../reference/glossary.md#前置确认) | 动手之前先把需求问清楚,冻结成一份[需求确认书](../reference/glossary.md#需求确认书);后面每一步读它,不再重新猜 | [前置确认](../guide/clarify.md) |
| 它说做完了,其实没做完 | [目标看守](../reference/glossary.md#目标看守) | 每轮结束由一个没参与干活的判定者独立判一次,没达成就打回去接着做 | [目标看守](../guide/goal.md) |
| 跑了几小时崩了,从头再来 | [接续](../reference/glossary.md#接续) | 同一个目录再跑一次自动接上上次的进度 —— 进程被杀、机器重启也一样 | [接续](../guide/continuity.md) |
| 上下文满了被压成一段摘要 | [换代](../reference/glossary.md#换代) | 快满时让当前会话写一份人能读、能改的[交接书](../reference/glossary.md#交接书),再开一条新会话接手 | [换代](../guide/handoff.md) |

两条值得单独记住:

**[判定](../reference/glossary.md#判定)有三种结论,不是两种。** 达成、没到、**这个环境验不了**。
后两种是不同的结论 —— "这里没法验"绝对不判通过,而是停下来问人。
而且判定者判的是**产出物**,不是源码:[HT002](../cases/ht002.md) 里栽过一次,
只看了 Makefile 的 macOS 分支就判通过,实际交付的是 Linux ELF。

**换代不是[压缩](../reference/glossary.md#压缩)。** 压缩是模型自己在暗处把前面的对话总结成一段摘要:
不可读、不可改、丢了什么你不知道。交接书是结构化的、落在磁盘上的,你能打开改一行再让它接着跑。
flower 默认关掉原生的 auto-compact,用换代顶上。

还有两层不在这张表里,但每次运行都在跑:

- [落盘](../reference/glossary.md#落盘) spill —— 工具结果超过 4000 字符就写进 `.flower/spill/`,
  上下文里只留一行路径。**当场就剪**,不是等满了再回头压缩。
- [工作台](../reference/glossary.md#工作台) workbench —— `.flower/` 下的 `scripts/`、`artifacts/`、
  `notes/` 三个目录,外加一份 `INDEX.md` 索引注入 system prompt,所以 agent 每轮都知道手上有什么。
  HT001 那次攒了 **61 个脚本、被执行 331 次**,其中 **92%** 被执行过不止一次。

## flower 不做什么 {#不做什么}

**一、它不提供现成的流程。** 框架只管机制:一步怎么跑、上下文怎么省、断网怎么续、
并行改同一个仓库怎么不打架、需要问人的时候怎么停下来。**流程是你写的。**
`flower` 裸跑时那三步来自
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py),
通用到不含任何领域假设 —— 它是给你起步用的,不是框架的能力边界。
要写自己的见[设计流程](../guide/workflow.md)。

**二、它不继承宿主机配置。** flower 用 `setting_sources=[]` 跑:不读宿主机的 `~/.claude/`,
也不读项目的 `.claude/`。这就是[可移植](../reference/glossary.md#可移植) —— 换一台机器行为一致。
领域能力靠随仓库走的 [plugin](../reference/glossary.md#plugin) 带,不靠这台机器上碰巧装了什么。

**三、凭证必须自带。** 这是第二条的代价。flower 按固定优先级找凭证(进程环境变量 →
`$FLOWER_ENV` → 当前目录 `.env` → `~/.config/flower/.env` → 源码仓库根 `.env`),
最后会去 `~/.claude/settings.json` 的 `env` 块里借那 9 个凭证键当兜底 ——
**只借"去哪找 token"这一件事**,settings.json 里的其它任何东西都不影响 agent 行为。
完整顺序和每个变量的语义见[配置参考](../reference/config.md)。

**四、它不替换系统提示词。** 领域指令是[叠加](../reference/glossary.md#叠加)在
Claude Code 原生系统提示词**之后**的,不是把它换掉。所以专门化不以损失通用能力为代价。

---

读到这里,[快速上手](quickstart.md)里那些输出应该都能读懂了。
想知道这些机制各自怎么调、什么时候不该用,从[上下文经济学](../guide/context.md)往下读;
只想抄命令,去[命令行参考](../reference/cli.md)。
