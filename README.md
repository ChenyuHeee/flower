# flower

基于 **Claude Agent SDK** 的可移植长程 agent 框架。

不牺牲 Claude Code 的能力，把它变成一个能带走、能定制交互、能跑几天的专用 agent。

## 装

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

然后进任意项目目录 `flower` 就能用。第一次会问你要 API key / 网关，配一次
存到 `~/.config/flower/.env` 处处生效；本机装了 Claude Code 的话直接借它的 token。
从源码跑见 [快速上手](docs/start.md)。**文档站：https://chenyuheee.github.io/flower/**

> **文档在 [`docs/`](docs/)**：[快速上手](docs/start.md) ·
> [设计 workflow](docs/workflow.md) · [前置确认](docs/clarify.md) ·
> [目标看守](docs/goal.md) · [接续](docs/continuity.md) · [换代](docs/handoff.md) ·
> [换交互层](docs/interaction.md) · [容器](docker/README.md) ·
> **真实运行案例：[HT001](docs/case-ht001.md) · [HT002](docs/case-ht002.md)**。
> 本页讲的是**为什么是这些设计** —— 实测数据、对照实验和踩过的坑。

---

## 四条需求 → 四个机制

| 需求 | 机制 | 在哪 |
|---|---|---|
| 上下文只装决策 | 主 agent 只协调、不动手；写码/跑测试/调工具全派给 subagent。subagent 的 transcript 是**另一条**，主线程只收报告 | `core/roles.py` |
| 琐碎沉淀到磁盘 | 工作台：可复用脚本 / 长产出 / 决策笔记落盘，索引注入 system prompt | `core/workbench.py` |
| 当场剪枝，而不是事后压缩 | PostToolUse hook 把超阈值的工具结果落盘，只留一行路径 | `core/guard.py` |
| 并行改同一个仓库不打架 | 标记过的角色自动分到独立 git worktree，hook 强制，零提示词开销 | `core/guard.py` |
| 断网不丢活 | DNS+TCP 探针挂着等，恢复后 resume 续跑；错误消息不进上下文 | `core/resilience.py`、`stores/prune.py` |
| 脱离 claude CLI | Python wheel 内置原生二进制 `claude_agent_sdk/_bundled/claude`，依赖只有 anyio/jsonschema/mcp/sniffio。无 Node、无需装 Claude Code | `pyproject.toml` |
| 可移植 | `setting_sources=[]` 隔离宿主 `~/.claude/` 与项目 `.claude/`；领域能力走 `plugins=[local]` 随仓库走；凭证走 `.env` 自带 | `core/agent.py`、`core/env.py` |
| 定制交互 | SDK 消息流被压平成稳定的 `Event`，UI 层不 import 任何 SDK 类型 | `core/events.py` |
| 长程 workflow | 可插拔 `SessionStore`（SQLite 落盘，`flush="eager"`）+ resume / fork / resume_at + `max_budget_usd` | `stores/sqlite.py`、`core/runtime.py` |

### 关键一条：叠加，不替换

```python
system_prompt = {"type": "preset", "preset": "claude_code", "append": spec.instructions}
```

`append` 是**追加**在 Claude Code 原生提示词之后，不是替换。
所以专门化不以损失通用能力为代价 —— 这是“别的专项 agent 没有 Claude Code 强”的解法。

---

## 上下文经济学：为什么主 agent 不该动手

压缩(compact)是等上下文满了再回头总结 —— 治标。真正的问题是**琐碎的东西一开始就不该进主上下文**。
flower 用四层解决，顺序就是它们的优先级：

**第一层：分工（省得最多）。** 主 agent 扮演“一个会用 Claude Code 的人”：拆解、派活、读报告、
决策。它拿不到 Bash/Write/Edit。所有动手的活派给 subagent，而 subagent 的工具调用与试错
**进的是它自己的 transcript**（store 里 `subpath="subagents/agent-{id}"`），主线程只留下
那一次 Agent 调用和最终报告。

试错过程不是被压缩掉的，是**从来没进过主上下文**。实测：一个会产生大量工具输出的任务，
83% 的 transcript 落在 subagent 里，主线程 13 条、21K 字符。

```python
from flower import Runtime, coordinator, worker

分析员 = worker("分析文件：统计、查找、比对。要真读文件、跑命令的活派给它。",
               "你负责文本分析。用命令行完成，不要手工估算。",
               tools=["Read", "Write", "Bash", "Glob", "Grep"])   # model 默认 "inherit"

主控 = coordinator("主控", "目标：摸清 data/ 的规模。", {"分析员": 分析员})
rt = Runtime(workspace="repo", workbench=True)
```

> **坑（实测踩过）**：不要用 `disallowed_tools` 来限制主 agent —— 它是**会话级**的，
> 会把 subagent 一起禁掉（报错原文："Bash is disabled for this session, in subagents as
> well as here"）。正确做法是 `allowed_tools` 不给，再用 PreToolUse hook 按 `agent_id`
> 只拦主线程。`coordinator()` 已经这么做了。

subagent 默认 `model="inherit"` —— 干活的那个不该降级。省的是上下文，不是模型档次。

**第二层：工作台（治“每次重写”）。** `.flower/` 下三个目录随工作区走：

| 目录 | 放什么 | 解决什么 |
|---|---|---|
| `scripts/` | 会跑第二次的验证/复现脚本 | 写一次，以后直接跑。不再“微压缩后丢失，每次重新编写” |
| `artifacts/` | 日志、数据、报告、diff | 对话里只出现路径和结论 |
| `notes/` | 决策与理由 | 被压缩、被重启、换机器，结论都还在 |

`INDEX.md` 自动生成，并且**注入进主 agent 的 system prompt** —— 它开局就知道有哪些
现成脚本，不用先花一次工具调用去发现。脚本首行写 `# desc: 一句话` 就会出现在索引里。

压缩清得掉上下文，清不掉磁盘，也清不掉 system prompt 里的索引。这一层就是靠这个差别工作的。

**第三层：当场剪枝。** PostToolUse hook 在工具结果**进模型之前**看一眼：超过 4000 字符的，
落盘到 `.flower/spill/`，上下文里换成一行路径 + 开头 400 字符。内容没丢，只是不常驻。

读落盘件本身**不再落盘** —— 否则那行提示里的“需要全文用 Read 读它”是句空话：
读回来又超阈值、又被落盘、又给它一行指针，无限循环。实测撞到过
（`tests/handoff_live.py` 头一次真跑），模型连试五种写法绕，自己说
“The spill read loops back on itself”，最后靠 40 行一段硬啃，白烧七八轮。
落盘的意义是“**不自动**把大东西塞进上下文”；它自己决定要看全文，那是它的选择。

```python
Runtime(workspace="repo", workbench=True, spill_threshold=4000)   # None 关掉
```

**第四层：看一眼的活自己干（glance）。** 前三层都在说“派出去”，但有个反例：
`git status`、`ls`、`cat` 这种命令，结果几十个字符，而**派一个 subagent 光启动就要
约 4.3k 上下文**（实测，不可摊薄）。为一条 `ls` 付这个价钱是净亏。

所以协调者拿回一个受限的 Bash。判据不是“命令短”，而是**结果会不会过期**：

```python
coordinator("主控", "...", workers, glance=True)    # 默认开
```

关键在于这两件事**由同一个函数决定**（`stores/trim.py: is_ephemeral`）：

| | 放行 | 剪枝 |
|---|---|---|
| `git status` / `ls` / `cat` | ✓ 自己跑 | ✓ 几轮后标记过期 |
| `git commit` / `pytest` / `pip install` | ✗ 派人 | — |

两边必须是同一张表，否则任一边单独成立都有害：**放行了不剪枝**，过期的
`git status` 就永久占着上下文，还会被当成现状误导决策；**剪枝了不放行**，
主 agent 就得为一条 `ls` 付 4.3k。`tests/glance.py` 把这条不变式钉成断言。

过期的结果不落盘 —— 归档一份旧的 `git status` 没有意义，重跑一次就有：

```
[`git status -s` 的结果已过期（第 7 轮前），当前状态可能已变。需要请重新执行]
```

```python
Runtime(workspace="repo", ephemeral=EphemeralPolicy(keep_recent=6))   # False 关掉
```

**被拒的调用同样要清掉。** 拦下来这个动作本身也会污染上下文：拒绝消息是一条
`tool_result`，和那条**从来没执行过的命令**一起永久留着。实测一次 273 字符
（93 字拒绝语 + 180 字死命令），死命令比拒绝语还贵。

比 token 更要紧的是它**会误导**：实测协调者读到几条“ 不直接使用 Bash ”之后，
连放行的 `git status` 都不再尝试，直接说“Bash 被限制了，派个 agent 去看” ——
学成了习得性无助，反而多花一次 subagent 启动。这条规矩 system prompt 里已经写了，
上下文里再留一份是重复。

```python
Runtime(workspace="repo", keep_denials=1)   # 默认留最近 1 次；0 = 全摘
```

默认留 1 条：最新那次拒绝是有效信号，能防止模型在同一轮里反复重试同一条被拦的命令。
识别靠 harness 自己打的结构性标记 `toolDenialKind: "permission-rule"`，不是匹配文案
—— 文案随时会改，标记不会。

**摘除时的红线**：`tool_use` 和它的 `tool_result` 必须**一起**摘（少一个就是
`Missing Tool Result Block`），同一条 assistant 消息里的其它调用不能误伤，
`toolUseResult` 里那份副本也要清，而且 `parentUuid` 链必须重新接上。

**坑（踩过两次）**：模型不会写单条命令，它写的是
`git status -s && echo "--- LOG ---" && git log --oneline -10`。
第一版一刀切拒绝所有含 `&&` / `|` / `2>&1` 的命令，结果**glance 完全失效** ——
实测协调者三次尝试全被拦，只好回去派 subagent。现在是逐段拆开检查：
每一段都在白名单里才放行，`git status && rm -rf x` 照样拦（后半段不在表里）。

白名单里的动词也可能带上会改状态的选项，这些单独拦：`awk 'BEGIN{system(...)}'`、
`find -execdir`、`git branch -D`、`sed -i`、`sort -o`、`tee`、`--force/--hard`。
命令替换（`$(...)`、反引号）和真正的重定向一律不放行 —— 但 `2>&1`、`>/dev/null`
是无害的，得先摘掉再判，否则又把模型最常写的形式误伤了。

---

## 先把需求问清楚：前置确认

上面四层清掉的都是**现场**。但有一类错误，剪枝会让它**变严重** —— 目标理解错了。
现场被丢掉之后，留下来的恰恰是那条建在错误前提上的决策，而且它**看起来和正确决策
一模一样**。长程把它放大到最坏：错误前提先跑几小时、派十几个 subagent、在磁盘落一堆产出，
之后才暴露。到那时贵的不是 token，是**每一个产出都是照错的需求建的**。

所以第一步先问清楚，再开工。不用写代码 —— 进项目目录说一句就行：

```bash
flower                  # 光标等着，输一句你要做什么 —— 不用打引号
flower --clarify-only   # 只看它问什么，不往下干
```

自己设计流程时是这个形状：

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

确认书要落在**挂在 workflow 上的那个工作台**里 —— 工作台索引会注入主 agent 的
system prompt，它才知道需求文件在哪、才能在派活时把路径转述给 subagent。

**注意**：索引只到主 agent。subagent 有自己的 system prompt，**继承不到**
session 级的那一段（实测 $0.2461，`tests/prelude_live.py`）——
所以工作台位置必须由协调者在任务书里说，这是唯一通道。自己另拼一个路径的话，
确认书写进一处、注入的索引扫的是另一处，那条承诺会**静默失效**。
见 [docs/start.md](docs/start.md#工作台要挂在-workflow-上不能只拼路径)。

澄清的问答是**现场，不是决策** —— 和 subagent 的试错同一性质。所以它跑在**独立 session**
里，唯一交付物是磁盘上一份**冻结的四段确认书**：

| 段 | 不写会怎样 |
|---|---|
| 目标 | 做出来的是另一个东西 |
| 验收标准 | 没人能判定“做完了” |
| 边界 | 范围蔓延；这一段管住后面**每一个** subagent |
| 未知与假设 | **错误前提被静默埋掉** —— 长程的保险丝就是这一段 |

下游 `resume_from=None`，于是那段问答**从来没进过**协调者的上下文 ——
不是“进去之后被剪掉”。

**两条必须是机制、不能是提示词的**，是实测出来的：跑过一个不受约束的确认者
（$0.8908 / 230s），它问完两个问题**直接开始写代码**；被权限拦下之后，
**把整份代码贴进了回话正文**。所以 ① 一道 hook 拦掉它的写工具 —— 它没法开工；
② 框架只解析那四段 —— 贴了也进不了下游。

①**必须是 hook，不能只靠 `allowed_tools`** —— 后者是免审批清单不是排他白名单，
实测模型能调用不在里面的工具（见 [docs/case-ht002.md](docs/case-ht002.md) 第三节）。提问额度同理：`max_asks` 在通道里数，
超了工具直接回绝，不写在提示词里。

没人看着的时候也得能跑下去：`timeout_s` 到了返回的是**一句说明，不是报错**
（"无人应答，自己判断，把假设写进「未知与假设」"）；`timeout_s=0` 就是全自动模式，
所有提问立刻落空，不假装等。

细节、API 与试用方法见 **[docs/clarify.md](docs/clarify.md)**。

### 再问一次：做完了没有

需求问清楚了，还有第二类失败：**它其实没做完，但自己说做完了**。
跑了一半的测试、改了一处漏了三处、“应该没问题”—— 这不是不老实，
是**干活的人看不见自己的盲区**。它知道自己做了什么，不知道自己漏了什么。

所以判定不能由它自己下。目标看守是个独立 session 的角色：没写工具，
看到的只有目标和现场，不知道干活那个人试了多少次，也就不会替它找理由。

三个结论，不是两个：

```
干活 ──> 判定 ──达成────> 往下走
              ├─未达成──> 打回，带上"差在哪"，**续跑同一个 session 接着做**
              └─无法达成─> 停下来问人：接受 / 改目标 / 你判断错了
```

第三个是关键：只有“达成/未达成”的话，一个**其实做不到**的目标会让主 agent
一轮一轮空转到额度见底。没人应答时它会**停**，而不是接着烧钱。

打回是“接着做”不是“重头做”—— 下一轮 `resume` 刚被否掉的那个 session，
已经干完的活还在。`runs/manifest.json` 里看得出区别：`干活#round2` 是打回续跑，
`干活#retry1` 是重头重试。

细节见 **[docs/goal.md](docs/goal.md)**。

---

## 断网：探针、续跑、错误不进上下文

长程跑几小时，网络必然断一次。默认行为很糟 —— 这是实测断线后从库里挖出来的：

```json
{"type": "assistant", "isApiErrorMessage": true,
 "message": {"model": "<synthetic>",
             "content": [{"type": "text", "text": "API Error: Can't reach the API server ... (ENOTFOUND)"}]}}
```

harness 把错误当成一条 **assistant 消息**写进 transcript。它成了会话的叶子，之后 resume
就被当作“模型上一句说的话”喂回去 —— 模型会以为自己在讨论网络故障。它还会混进
`StepResult.text`，顺着 workflow 传给下一步的 prompt。

flower 三件事一起做：

1. **探针**：只做 DNS + TCP 握手，不发 HTTP、不带凭证 —— 探针必须免费，否则“断网时每 15 秒
   探一次”本身就成了故障。探的是 `ANTHROPIC_BASE_URL` 指向的那个网关，不是 api.anthropic.com。
2. **续跑而不是重来**：失败时 session_id 已经拿到了，用 resume 从中断处接上，之前的花费不白费。
   重试 prompt 有意不含任何错误细节 —— 模型需要知道“被打断了、接着做”，不需要知道是 ENOTFOUND 还是 503。
3. **错误不进上下文**：合成错误消息在 `load` 时摘掉，并**重接 parentUuid** —— transcript 是
   单链，摘一条不重接就断在那里，前面的历史全丢。SQLite 里原文一个字不改，只是不喂回去。

   > 踩过的坑：`relink()` 必须拿到**含被摘条目**的完整列表 —— 调用方先过滤再传进来的话，
   > 被摘条目的父亲就查不到了，只能接成 `None`，链照样断。这个 bug 在错误出现在**末尾**时
   > 不暴露（后面没人引用它），一旦出现在中间就丢掉断点之前的全部历史。

可重试与不可重试分开判：网络抖动该等，凭证错该立刻停。`401 unauthorized: connection error`
这种文本里带 "connection" 的必须判成 fatal，否则死等烧时间。

```python
from flower import Resilience
Runtime(workspace="repo", resilience=Resilience(
    max_attempts=6, probe_interval=15, max_offline_wait=3600))   # 默认值
```

重试历史记在 `StepResult.attempts` / `.errors` / `.resumed` 和 `manifest.json` 里 ——
排查故障看那里，模型看不到。

---

## 并行改同一个仓库：每人一个工作副本

fan out 几个 subagent 分别修不同的 issue，它们**共用一个 checkout**。给它们分了不同分支
也没用 —— 分支是仓库的全局状态，谁 `git checkout` 一下所有人都跟着切了，提交就串。

harness 其实自带解法：Agent 工具接受 `isolation: "worktree"`，给 subagent 一份独立的
git worktree（自己的目录 + 自己的分支 + 自己的索引）。问题是怎么用上它 ——
写进系统提示词的话，不需要隔离的场景（只读调研、单个 agent 干活）白白常驻 token，
而且提示词是**建议**，��型可以不听。

flower 的做法：**隔离是角色的属性，由 hook 强制执行。**

```python
workers = {
    "改代码": worker("修 bug 并提交", "改代码、跑验证、commit。", isolate=True),
    "调研":   worker("只读地看代码",   "你只读。",  tools=["Read", "Grep"]),
}
```

只有这一处出现“隔离”两个字。`改代码` 每次被派活都自动拿到独立 worktree；`调研`
不加任何东西 —— 连 hook 都不装（`agents` 里没有标记过的角色时，`isolate_guard` 根本不挂）。
系统提示词里一个字都不提 worktree、分支、目录。

实测（`tests/isolation.py`，三个 bug 三个 issue）：

```
/private/tmp/iso_ws                                    dad36f7 [main]        ← 没被碰过
.../.claude/worktrees/agent-a6348d10be5cc80bb  115efbe [fix/add-subtraction]
.../.claude/worktrees/agent-afeaf46ac96617362  4be8800 [fix/mul-addition]
.../.claude/worktrees/agent-a6c97f202cab84336  394691c [fix/div-zero]
```

每个分支只含自己那一行改动，互不污染 —— 三个 PR 直接可开。

**为什么是 hook 而不是提示词**，做了对照实验：系统提示明确写着“不要使用 worktree 隔离，
让 subagent 直接在当前目录切分支”，��型照做了（传的 `isolation=None`），hook 照样注入成功，
两个 subagent 还是落进了各自的 worktree。提示词是建议，hook 是保证。

不覆盖模型的明确选择：它自己给了 `cwd`（两者互斥）或已经指定了 `isolation`，一律不动。

**一个必须知道的坑**：被隔离的 agent 写不进共享 checkout ——

```
This agent is isolated in the worktree ..., Edit the worktree copy of this file
instead of the shared-checkout path.
```

而工作台恰恰是要**跨 agent 共享**的：worktree 是每人私有的工作副本，工作台是公共沉淀层，
两者正交。所以工作台默认落在 `run_dir/workbench`（仓库外），用绝对路径注入 ——
实测隔离 agent 写仓库外路径不受限。这样开不开隔离都不用改配置。

前提：workspace 得是 git 仓库。不是的话 Agent 工具直接报错（`not in a git repository`），
不会静默退化成共用目录。

---

## 布局

```
flower/
  core/agent.py       AgentSpec + build_options  ← 框架决定，设计 workflow 时不用动
  core/roles.py       coordinator/worker/clarify ← 分工，上下文经济的主杠杆
  core/workbench.py   Workbench                  ← 脚本/产出/笔记落盘 + 索引注入
  core/guard.py       PreToolUse / PostToolUse   ← 当场拦截、剪枝、worktree 隔离
  core/resilience.py  Resilience + 探针           ← 断网重试
  core/events.py      Event + normalize          ← UI 解耦边界
  core/human.py       HumanChannel               ← 唯一一处“停下来等人”
  core/brief.py       Brief                      ← 冻结的四段需求确认书
  core/goal.py        Goal + Verdict             ← 可判定的目标 + 三态判定
  core/runtime.py     Runtime + StepResult       ← 执行核心，会话血缘
  stores/prune.py     PruningSessionStore        ← 断线残渣不喂回模型（默认启用）
  stores/trim.py      TrimmingSessionStore       ← 旧工具结果换成文件指针
  stores/sqlite.py    SqliteSessionStore         ← 落盘，长程的地基
  workflow/base.py    Step + Workflow            ← 你要设计的那一层
  workflow/clarify.py clarify_step               ← 前置确认的一行接线
  workflow/goal.py    goal_step + with_goal      ← 目标看守：判定 + 打回接着做
  workflow/starter.py starter_flow               ← `flower` 的三步默认流程
  cli.py              参考 UI，~200 行，可整体替换
 docs/               给读者的文档（开源入口）
 examples/trial.py   模板 —— 照它写自己的 flows.py（直接试用不需要它）
 plugin/             领域能力包（skills/agents/hooks/mcp），随仓库走
 runs/               sessions.db + manifest.json
```

---

## 设计一个 workflow

```python
# flows.py
from flower import AgentSpec, Step, Workflow

researcher = AgentSpec(
    name="researcher",
    instructions="你只做调研：读代码、查资料、列事实。不写代码，不下结论。",
    allowed_tools=["Read", "Glob", "Grep", "WebSearch", "WebFetch"],
)
coder = AgentSpec(
    name="coder",
    instructions="按方案实现。每改一处就跑一次测试。",
    allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    permission_mode="acceptEdits",
    max_budget_usd=5.0,
)

def main():
    return Workflow([
        Step("调研", researcher, "梳理 X 模块的现状与约束"),
        Step("方案", researcher, lambda c: f"基于以下调研给出方案:\n{c['调研']}"),
        Step("实现", coder, "按上面的方案实现", resume_from="方案"),
        Step("复核", coder, "以审查者视角找问题", resume_from="实现", fork=True,
             retries=1, gate=lambda r, c: "阻断" not in r.text),
    ])
```

```bash
flower run flows.py:main -w /path/to/repo -v
```

### 步与步之间的三种接法

| 写法 | 上下文 | 用在哪 |
|---|---|---|
| `resume_from=None` | 只有 prompt 里传的 | 各步独立，便宜，防污染 |
| `resume_from="上一步"` | 完整会话 | 需要连贯记忆 |
| `resume_from=… , fork=True` | 完整会话，但另开分支 | 复核 / 多方案并行 / 重试不脏原线 |

每一步的 `session_id` 都写进 `runs/manifest.json`，所以**事后任意一步都能续跑或分叉**。

完整字段参考（`when` / `gate` / `reduce` / `retries` / `on_fail`、`ctx` 的形状、
两层重试的分工）见 **[docs/workflow.md](docs/workflow.md)**。

### 查库

`project_key` 由 SDK 从 **cwd** 推导（`/`、`_`、`.` 都换成 `-`），调用方指定不了。
用 `rt.project_key` 拿推导值，`rt.store.projects()` 看库里实际有什么：

```python
rt = Runtime(workspace="/path/to/repo", run_dir="runs")
await rt.store.list_sessions(rt.project_key)     # [{session_id, mtime}, ...]
await rt.store.load({"project_key": rt.project_key, "session_id": sid})
await rt.store.list_subkeys({"project_key": ..., "session_id": sid})   # 子 agent 的 transcript
```

落盘用 `flush="eager"`：一轮可能跑几十分钟，崩在中间不该丢整轮记录。

---

## 换掉交互层

`cli.py` 的 `render(ev)` 是唯一的出口。要做 Web/TUI/HTTP，把它换成你的写法：

```python
async for ... :   # Runtime.run 的 on_event 回调
    await websocket.send_json({"kind": ev.kind, "text": ev.text, "tool": ev.tool})
```

框架层不知道 UI 存在。`Event` 的全部 kind、跨线程回答提问、Web/全自动的写法，
见 **[docs/interaction.md](docs/interaction.md)**。

---

## 凭证：可移植的代价

`setting_sources=[]` 意味着 flower **不读** `~/.claude/settings.json` —— 连里面的 `env` 块也不读。
你的 `ANTHROPIC_BASE_URL` 和 token 就在那里，所以必须由 flower 自己带：

```bash
cp .env.example .env   # 填 token；.env 已被 gitignore
```

优先级：进程环境 > 仓库根 `.env`。`flower -v` 启动时会打印生效端点（token 打码），
避免连错网关还不自知。

> 顺带：`~/.claude/settings.json` 里 token 是明文。那个文件若同步或提交过，建议换掉这个 token。

---

## 已验证 / 未验证

跑过真实请求验证过的：

| 项 | 结果 |
|---|---|
| 脱离 claude CLI | ✓ 仅靠 wheel 内置二进制发起真实请求 |
| 叠加式提示词 | ✓ append 指令生效，同时保留原生工具能力 |
| 工具链 | ✓ Read/Glob 正常调用 |
| SQLite 落盘 | ✓ eager 模式，transcript 逐条入库 |
| resume | ✓ 跨调用续上上下文 |
| fork | ✓ 分出新 session，原线不动 |
| Workflow 三种接法 | ✓ 新会话 / 续跑 / 分叉，gate + retries + when 均生效 |
| 网关透传 `effort` | ✓ `cloud.infini-ai.com/maas` 接受，且花费随 effort 变化（low $0.185 / high $0.297），不是静默丢弃 |

| 主/subagent 上下文分离 | ✓ 一次重活：主线程 13 条 / 21K 字符，subagent 105K 字符，**83% 沉到 subagent** |
| 协调者不动手 | ✓ 主线程只用了 `Agent` 一个工具 |
| 工作台复用 | ✓ subagent 自发写下 `# desc:` 脚本 + artifact，下一步 system prompt 里就有了 |
| compact 开关 | ✓ `CompactPolicy` 经 `opts["env"]` 到达子进程，`get_context_usage()` 读出 autoCompact 已关 |
| 断线残渣清理 | ✓ 拿**真实断网**留下的 transcript 验证：摘掉合成错误、链未断、tool_result 块保留、SQLite 原文完整 |
| 重试与探针 | ✓ 注入故障序列全通过：transient 重试并 resume 续跑 / fatal 立刻停 / 断网挂着等且有上限 |
| worktree 隔离 | ✓ 三个 issue 三个 worktree 三个单一改动的分支，主 checkout 未被碰；并行无 index.lock 冲突 |
| hook 注入优先于模型意愿 | ✓ 对照实验：系统提示明确禁用 worktree，模型传 `None`，hook 注入照样生效 |
| 隔离的零开销 | ✓ 未标记的角色不注入、不装 hook；模型自带 `cwd`/`isolation` 时不覆盖 |
| 工作台可外置 | ✓ 隔离 agent 写仓库外路径不受围栏限制（仓库内则被拒，错误原文已记录） |
| 外置工作台可写 | ✓ `add_dirs` 授权后 subagent 的脚本落盘成功并进了 INDEX；不加则被拒（实测两次） |
| glance 放行复合命令 | ✓ 活体：协调者 4 条 `&&`/管道命令全部放行，0 次被拦，0 次为看一眼派人 |
| 互补性不变式 | ✓ 46 条命令两边判定完全一致；含 10 条对抗样本（`awk system()`/`-execdir`/`git branch -D` 等） |
| 时效性剪枝 | ✓ 活体 resume：`expired: 2`；真实 transcript 上 keep_recent=2 → 过期 5 条 |
| 被拒调用清理 | ✓ 活体：2 次被拒 → 摘 1 留 1，链未断，resume 正常且模型仍知道发生了什么 |
| 摘除不破坏结构 | ✓ tool_use/tool_result 配对、同消息内不误伤、`toolUseResult` 副本清掉、链重接 |
| 确认者必须被机制约束 | ✓ 反面实测（$0.8908 / 230s）：不受约束的确认者问两个问题就开写，被拦后把整份代码贴进回话 —— 拦写工具的 hook、只解析四段 |
| **`allowed_tools` 不是排他白名单** | ✓ 实测三处：确认者用了不在白名单里的 WebFetch；设目标的 judge 跑了 11 次 Bash 而无 `can_run` 路径；$0.1 探针确认 `allowed_tools` 不是排他白名单 |
| **上下文经济学（真实规模）** | ✓ 一次 10.4 小时的运行：subagent 承担 **97.7%** 轮次、**94.8%** 正文字符；1,893 次动手工具调用 vs 主线程 32 次（**59:1**）。早期压缩不再是主线 |
| **长程的真实上限** | ✓ 主线程 70 轮从 28.7K 涨到 185.9K，斜率 2.2K/轮，全程未压缩，用掉 1M 窗口 18.6%。**外推约 440 轮撞墙** —— 这个数字以前只能猜 |
| **缓存是长程经济性的支点** | ✓ 输入 299.4M token，**96.1% 命中缓存**。$171 能成立全靠它；任何重排上下文的优化都要先算缓存账 |
| **工作台复用** | ✓ 61 个脚本被写 95 次、被执行 331 次；**92% 执行过不止一次，写了没跑的 0 个**。定性上 `audit-fake-ai-server.py` 被 7 个脚本复用，驱动器里复用最强 |
| **断网自动续跑（端到端）** | ✓ **真实故障验证**：跑到一半 DNS 挂了，探针挂着等 → `resumed=True` 续跑同一 session → 又跑 8 小时到完成。10 小时的活没丢 |
| **可移植性（换平台）** | ✓ **Linux/arm64 容器里跑通真实请求**（$0.1741 / 1 轮，经 `cloud.infini-ai.com/maas`）。镜像里**没有 claude CLI、没有 node/npm/npx**，自带二进制可直接发请求 |

仍未验证：

- **前置确认 flow 的真实 API 端到端**。离线 52 项全绿（`tests/clarify.py`）、CLI 路径
  离线跑通，但没跑过真实请求 —— 这一步有意留给使用者自己试，见 [docs/clarify.md](docs/clarify.md)。
- **断网重试的端到端实测**。分类、探针、清理都单独验过，但“真断网 → 自动恢复 → 续跑完成”
  这一整条没跑通过 —— 掐网需要改 `/etc/hosts`（要 sudo）。`tests/resilience_live.py` 写好了，
  有 sudo 时可以直接跑。
- **微压缩在 `DISABLE_AUTO_COMPACT=1` 下是否仍然工作**。这是**读二进制反汇编推断的，不是实测**。
  真要验证得填满 167k 上下文，很贵。
- 压缩相关 beta 参数经该网关的透传、`PreCompact` hook、几十轮以上的超长会话。
- **worktree 的收尾**：合并回 main、清理 worktree、从分支开 PR，目前都留给你的 workflow 自己做。
  harness 只保证“改动落在各自的 worktree 里，agent 无改动时自动清理”。
- **非 git 仓库**下的隔离：harness 支持配 `WorktreeCreate`/`WorktreeRemove` hook 走其它 VCS，
  flower 没有封装，也没测过。

关于 compact 的三层结论（问过的那个问题）：

1. **算法本身改不了** —— 在 wheel 内置的二进制里，没有 hook 也没有 option 暴露它。
2. **触发与否可以关**，实测过：

   | 设置 | autoCompact | 阈值 | 窗口 |
   |---|---|---|---|
   | 默认 | True | 167000 | 200000 |
   | `CompactPolicy(mode="no_summary")` | False | — | 200000 |
   | `CompactPolicy(mode="off")` | False | — | 200000 |
   | `window=60000` | True | 67000 | 100000 |

   阈值 = 窗口 − 33k。`window` 只能**调小**，调大无效（受模型真实窗口封顶）。
   关掉全量压缩就没有兜底了，撞上限是硬错 —— 必须配合前面三层一起用。
3. **真正能改写规则的那一层是 `SessionStore.load()`**。它是 resume 前唯一的改写点：
   SDK 拿它的返回值物化成临时 jsonl，子进程从那里恢复。`stores/trim.py` 就写在这里 ——
   保留全部交互历史，只把旧的大 tool_result 正文换成文件指针，SQLite 原���不动。

   ```python
   Runtime(workspace="repo", trim=TrimPolicy(keep_recent=20, min_chars=2000))
   ```

   不过按上面的分工做之后，这一层多半用不上 —— 主线程本来就装不下多少工具结果。

跑测试：

```bash
.venv/bin/python tests/smoke.py           # 单 agent 全链路（约 $0.21）
.venv/bin/python tests/flow_demo.py       # workflow 三种接法（约 $0.39）
.venv/bin/python tests/delegation.py      # 协调者/执行者分工 + 量上下文分布（约 $0.71）
.venv/bin/python tests/isolation.py       # 三个 issue 三个 worktree（约 $0.9）
.venv/bin/python tests/wake_live.py       # 跨进程接续：两个 OS 进程，记忆探针（约 $0.24）
.venv/bin/python tests/handoff_live.py    # 换代：真触发一次，验接手的人接不接得住
.venv/bin/python tests/clarify.py         # 前置确认：通道/四段/白名单/接线，不花钱
.venv/bin/python tests/flow_offline.py    # Workflow.run 语义（when/gate/reduce/on_fail），不花钱
.venv/bin/python tests/glance.py          # 互补性不变式，不花钱
.venv/bin/python tests/denial.py          # 被拒调用清理 + 链完整性，不花钱
.venv/bin/python tests/trial_offline.py   # 一键入口解析 + 模板接线 + 工作台一致性，不花钱
.venv/bin/python tests/goal_offline.py    # 目标看守：三态判定 / 打回续跑 / 空转兜底，不花钱
.venv/bin/python tests/toolwall.py        # 工具墙：allowed_tools 不是排他白名单，hook 补差额，不花钱
.venv/bin/python tests/lineage_offline.py # 接续：同一路径接上上次 / 判定者永远新会话，不花钱
.venv/bin/python tests/handoff_offline.py # 换代：写交接换新会话 / 降级路径 / 防跑飞闸，不花钱
.venv/bin/python tests/termsafe_offline.py # 终端安全：不超宽 / 不带危险转义 / 图标全 ASCII，不花钱
.venv/bin/python tools/analyze_run.py <run_dir>   # 从 sessions.db 量一次运行（上下文曲线/缓存/复用），不花钱
sudo -v && .venv/bin/python tests/resilience_live.py   # 真掐网，需要 sudo
```
