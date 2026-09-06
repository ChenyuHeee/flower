# HANDOFF

> 写给下一个接手 flower 的 session。**读完这一份就能接着干**,不必翻上游 transcript。
> 上次更新:2026-09-07(第四轮:去掉提问次数限制 + 加目标看守;git init + 首次 commit)。
> 第三轮:一键入口 `flower` + 容器化,并**第一次验证了可移植性**。
> 要更细的原始细节时再翻:
> `~/.claude/projects/-Users-hechenyu-projects-flower/aede8e90-c1f2-4aaa-8e55-451852543032.jsonl`

---

## 0. 一句话现状

框架主体已成型且大部分跑过真实请求验证(见 `README.md` 的「已验证 / 未验证」)。
**最近一个增量是「前置确认 flow」**:代码写完、离线测试全绿、CLI 路径离线跑通,
但**没有跑过真实 API —— 用户明确要求这一步由他自己试**。

`docs/` 四篇齐了(上一轮)。**本轮的活是把入口做成一键式的** ——
他先让搭试用环境,我给的是 `cp trial.py . && ASK=... python -m flower.cli -T run trial.py:main`,
他的反馈是:**"这个脚本太复杂了吧……agent工具启动的方式我觉得应该是一键式的启动。比如flower"**。
于是现在是:

```bash
cd /他的项目 && flower "帮我做一个 X"
```

路上还撞出一个真 bug 并修掉了:文档里的 `flows.py` 和 `-W` 用的**不是同一个工作台**,
于是确认书从来没进过被注入的索引,而且不报错(详见 §6 第一条)。

之后他说"我们测试我应该搞一个小容器吧",于是又做了容器化(`docker/`)。
**这一步顺带把约束 #1「可移植、脱离 claude CLI」第一次验证了** ——
Linux/arm64 容器里跑通真实请求($0.1741),镜像里没有 claude CLI、没有 node。
见 §10。

第四轮他提了两点架构意见(**都已实现**,见 §11):

1. 提问不该有次数限制 —— "如果一直没问清楚需求那就一直问呗,用户不会嫌烦"
2. 确认完需求后要有 **goal 设定 + 每轮验证**,没达成就打回主 agent;
   判不了就跟用户交互(接受 / 改目标 / 你判断错了)

**用户在等的下一件事:他自己跑(容器里),带体验反馈回来。**
除此之外没有别的活 —— 别自己找活干,**尤其别替他设计领域 workflow**(见 §1.5)。

---

## 1. 用户定的死约束 —— 不要重新讨论,不要"优化"掉

1. **可移植的、专门的 agent**。不是针对这台机器的定制改造。
2. **必须脱离 claude CLI**。只靠 SDK wheel 内置二进制发请求。
3. **交互方式可定制**。不绑终端 TUI。
4. **长程 agent workflow**。
5. **workflow 的领域设计是用户的活,不是你的活。** 原话:
   > "我想要的是一个长程的agent workflow,我在你确定好了框架之后可以开始设计。"

   **你负责机制(Step/Workflow/角色/剪枝/隔离/确认),他负责流程。**
   不要替他设计领域工作流,不要问他做什么项目、用什么语言 —— 之前问过,他没答,
   等于回答了:框架不该知道这些。

动机前提(所有取舍的依据):
> "别的专项agent或者通用agent都没有claude code强大"

**可移植性不能拿能力换。** 所以是"在 Claude Code 原生能力之上叠加",不是重写一个 agent。

另一条贯穿全局的原则(用户自己提的,是整套上下文经济学的来源):
> "我想要把所有的具体写代码、测试、调用工具这些能力都丢给subagent……主agent来扮演正常
> 使用Claude code的使用者,来协调不同的subagent……上下文就只剩下决策。"

---

## 2. 用户现在在等什么(按优先级)

### (1) 用户自己试用 clarify → 会带体验反馈回来

原话:
> "这个测试我觉得可以让我自己来,试用一下,我做一个小项目然后给你分析一下。我也好反馈体验"

**所以:不要替他跑 clarify 的真实 API 测试,别花他的钱。** 离线验证已经做完了。
入口现在是 `flower "诉求"`(见 §8),`--clarify-only` 是省钱档。
他后来明确说过 **"我不用省token。直接全量跑"**,所以别再往省钱方向劝。
你要做的是**等反馈、按反馈改**。

他回来时大概率是带体验问题的(提问太多/太少、问得不对、四段填得敷衍、CLI 手感),
那时候的改动重点在**提示词纪律和额度默认值,不在架构**。
`docs/clarify.md` 末尾那张「症状 → 拧哪个旋钮」的表就是按这几类症状排的,先照它调,
调完记得把表本身也更新。

### (2) `docs/` —— 已完成

原话:
> "这个workflow的设计你不光要实现,还要有文档写好啊。专门开一个docs,方便以后开源别人阅读吧。"

关键词是**开源别人阅读** —— 读者不是他,是陌生人。所以四篇都是先讲为什么,再讲怎么用:

| 文件 | 内容 |
|---|---|
| `docs/README.md` | 索引 + 装/跑/概念速查/花费/排错表。陌生人从这里进 |
| `docs/clarify.md` | 前置确认深讲:动机、四段、两条"必须是机制"、API、试用、旋钮表 |
| `docs/interaction.md` | `Event` 全表 + 三个出口 + 跨线程回答 + 终端/Web/全自动三个形状 |
| `docs/workflow.md` | `Step`/`Workflow` 参考,含精确执行顺序、两层重试的分工、设计建议 |

顶层 `README.md` 同时补了:文档入口、「先把需求问清楚」一节、布局补上 human/brief/clarify、
已验证表补一行($0.8908 那次反面实测)、未验证补一条(clarify 真实 API)、测试清单补两条。
**顶层 README 讲"为什么是这些设计",docs/ 讲"怎么用"** —— 这条分工别混掉。

### (3) 悬着没答的一个提议

`plugin/agents/` 目前是空的。问过他"要不要放一个带注释的 worker 模板",没回。
别追问,他要就会说。

---

## 3. 建成了什么:需求 → 机制 → 文件

| 需求 | 机制 | 主要文件 |
|---|---|---|
| 脱离 CLI | SDK wheel 内置二进制 | `flower/core/env.py`, `core/runtime.py` |
| 叠加不替换 | `instructions` 追加在原生提示词之后 | `core/agent.py` |
| 只装决策的上下文 | 协调者无 Bash/Write,一切派给 subagent | `core/roles.py` |
| 看一眼不必派人 | 受限 Bash 白名单(分号/`&&`/管道按段判定) | `core/guard.py` |
| 短时效内容自动过期 | `is_ephemeral()` —— **和放行白名单同一张表** | `stores/trim.py` |
| 被拒调用不常驻 | 摘 `tool_use`+`tool_result` 并重接 `parentUuid` 链 | `stores/prune.py` |
| 大结果不进上下文 | 落盘 + 只回路径 | `core/workbench.py` |
| 断网不丢活 | 探针挂着等 → 恢复 resume;错误不进上下文 | `core/resilience.py`, `stores/prune.py` |
| 并行改同一仓库不串分支 | 按角色标记自动分 git worktree(hook 强制,不写提示词) | `core/guard.py` (`isolate_guard`) |
| **前置确认需求** | **提问通道 + 冻结四段确认书 + 只提问的角色** | **`core/human.py`, `core/brief.py`, `workflow/clarify.py`** |
| workflow 层 | `Step`/`Workflow`,三种会话接法 + gate/retries/when/reduce | `workflow/base.py` |
| 换交互层 | 一切经 `Event`,UI 只认 kind | `core/events.py`, `cli.py` |

**本轮(第四轮:提问不限 + 目标看守)动过的:**

```
新增  flower/core/goal.py         Goal(目标 + 可判定清单)/ Verdict(三态判定)
                                  解析沿用 brief.py 的严格路子;**含糊 = 未达成**
新增  flower/workflow/goal.py     goal_step() 设目标 + with_goal() 判定循环
新增  tests/goal_offline.py       假 Runtime,零花费,钉住三态/打回/空转兜底
新增  docs/goal.md                为什么判定不能由干活的人下 + API + 旋钮表
改    flower/core/human.py        max_asks 默认 6 → None(不限);
                                  抽出**公开的 ask()**,MCP 工具改成它的薄包装 ——
                                  框架自己也要能问人(无法达成时那个决策是框架的)
改    flower/core/roles.py        clarify 的 max_turns 16 → None(**必须一起放开**);
                                  + JUDGE_RULES / judge()
改    flower/workflow/base.py     + StepAbort(再试也没用,不消耗剩余轮数);
                                  + Step.on_reject(打回=续跑被否的 session);
                                  gate/when/on_reject 可 async;
                                  ctx["_runtime"] / ctx["_on_event"](让 gate 能派 agent)
改    flower/workflow/starter.py  默认流程变三步:确认 → 设目标 → 干活(带判定)
改    flower/cli.py               --rounds / --no-goal / --judge-can-run;
                                  --asks 默认改成不限
改    flower/__init__.py          53 个导出
改    docker/flowerbox            FLOWER_HOME 从脚本位置推,不再写死我的路径
改    README.md / docs/*          文档同步
```

**上一轮(一键入口)动过的:**

```
新增  flower/workflow/starter.py   starter_flow() —— `flower "诉求"` 背后的两步流程。
                                   刻意写清"这不是推荐的 workflow 设计,只是零配置起步"
改    flower/cli.py                + go 子命令(默认);_with_default_cmd 不写子命令时
                                   自动补 go;全局开关同时挂在主 parser 和三个子命令上
                                   (default=SUPPRESS,避开 argparse parents 的覆盖坑)——
                                   因为子命令是隐形的,开关写前写后都得能用;
                                   + build_parser() 便于测试只解析不执行;
                                   + 非 TTY 时警告一句(见 §6)
改    flower/__init__.py           43 个导出(+ starter_flow)
改    .env                         新建。从 ~/.claude/settings.json 的 env 块搬的(见 §9)
改    flower/core/env.py           describe() 的 token 打码从前 7 位收到前 4 位
重写  examples/trial.py            砍掉 ASK/CLARIFY_ONLY/ISOLATE 那套环境变量 ——
                                   一键入口接管了试用,它只剩"照着抄"这一个用途,48 行
新增  ~/.local/bin/flower          软链到 .venv/bin/flower(shebang 是绝对路径,够用)
新增  docker/{Dockerfile,build,flowerbox,README.md}
                                   容器化 + 国内网络的镜像替换(见 §10)
新增  .dockerignore                排掉 .venv(191M mac 二进制)和 .env,上下文 2.6MB
改    README.md                    已验证表补一行:可移植性(换平台)
新增  tests/trial_offline.py       52 项离线断言,零花费。第 3 节钉住"确认书出现在注入
                                   system prompt 的索引里",第 6 节确认它抓得到回归,
                                   第 7 节钉住 13 种命令行写法
改    flower/workflow/base.py      + Workflow.workbench —— 和 channel 同一个先例:
                                   给驱动程序发现用。**这是那个 bug 的修法**
改    flower/cli.py                自动发现 wf.workbench 并交给 Runtime;
                                   _load 的错误信息(路径不存在时原来报的是
                                   "No module named 'trial.py'",完全指不到问题上)
改    README.md                    clarify 例子改成正确写法 + 布局补 examples/ + 测试清单
改    docs/README.md               flows.py 例子改正 + 新增「工作台要挂在 workflow 上」一节
改    docs/clarify.md              开篇例子改正、「brief_path 必须放在挂上去的那个工作台里」
                                   重写(原来给的 rt.workbench 写法经 CLI 根本做不到)、
                                   试用一节改成 trial.py + 可在别的项目目录里跑的命令形式
改    docs/workflow.md             Workflow 参考补 workbench 字段 + 为什么必须挂上去
```

**上一轮(建 docs/)动过的:**

```
新增  docs/{README,clarify,interaction,workflow}.md
新增  tests/flow_offline.py         Workflow.run 语义的离线验证(假 Runtime,24 项)
改    README.md                     文档入口 / clarify 一节 / 布局 / 验证表 / 测试清单
修    flower/cli.py                 tool_call 的摘要取错了地方:payload["summary"] 不存在,
                                    摘要在 ev.text 里 —— 之前工具调用后面一直是空白
修    flower/workflow/base.py       ctx["_sessions"] 和循环实际写的不是同一个 dict:
                                    同一个 Workflow 对象跑第二次时它会停在上一次的值
```

上一轮(前置确认)动过的文件,**这几个最新、风险最高**:

```
新增  flower/core/human.py          提问通道(阻塞等人 / 额度 / 超时 / 跨线程回答 / 落盘)
新增  flower/core/brief.py          四段确认书:解析、冻结、往返
新增  flower/workflow/clarify.py    一行接线(when/gate/reduce)
新增  tests/clarify.py              离线验证,不花钱
改    flower/core/roles.py          + CLARIFIER_RULES / clarify()
改    flower/workflow/base.py       + Step.reduce / Workflow.channel / **gate 只调一次**
改    flower/core/events.py         EventKind + "ask"
改    flower/core/agent.py          + AgentSpec.workbench(是否注入工作台索引)
改    flower/core/runtime.py        spec.workbench=False 时不注入索引(hook 照挂)
改    flower/cli.py                 渲染 ask 事件 + 标准输入回答(daemon 线程) + -W/-T
改    flower/__init__.py            42 个导出(已逐个 hasattr 验过)
```

---

## 4. 验证状态(下面这些是 2026-09-06 亲手跑过的,不是推断)

**离线五套全绿**(本轮末尾重跑过一遍):

```bash
.venv/bin/python tests/clarify.py       # ✓ 52 项(提问通道 / 四段解析 / 角色白名单 / 接线)
.venv/bin/python tests/flow_offline.py  # ✓ 24 项(Workflow.run 语义)
.venv/bin/python tests/glance.py        # ✓ 互补性不变式:46 条命令两边判定一致
.venv/bin/python tests/denial.py        # ✓ 被拒调用清理 + 链完整性
.venv/bin/python tests/trial_offline.py # ✓ 69 项(一键入口解析 + 模板接线 + 工作台一致性)
.venv/bin/python tests/goal_offline.py  # ✓ 目标看守(三态判定 / 打回续跑 / 空转兜底)
```

**本轮另外亲手跑过的(零花费):**

- 真实命令行 `flower "…" --clarify-only`(预置完整确认书让确认那步跳过)→ 退出码 0、
  `总花费 $0`、**没有 manifest.json**(即 `Runtime.run()` 一次都没进)、
  `.flower/INDEX.md` 里确实出现了 `.flower/notes/需求.md`。修好之前那一行不会出现。
  这条已经钉进 `tests/trial_offline.py` 第 9 节。
- `env -i` 清空环境后 `.env` 能独立读到凭证 —— 证明他在**自己的终端**里跑得起来
  (Claude Code 只把 settings.json 的 env 注入自己的子进程,新终端里是空的)。
- 13 种命令行写法的解析(`flower "x" -v` / `-w DIR "x"` / `--workspace=DIR "x"` /
  `"x" --clarify-only` / `-v run f.py:main` …),全部落到对的子命令和字段上。

文档里的例子也**真的构造过**(不发请求):两步都在、通道和工作台都挂上了、
确认者白名单确实没有写工具、`workbench=False`、没有确认书时 `when` 返 True、
有确认书时跳过且 `ctx['确认需求']` 照样被灌好。

**CLI 路径离线跑通**:`_load` 认文件路径 → 自动发现 `wf.channel`(挂标准输入回答线程)
和 `wf.workbench`(交给 `Runtime`)→ 干净退出(exit 0,`stop.set()` 之后线程确实退出)。
`_load` 的三条错误路径也实测过:路径不存在 / 属性不存在 / 没给 `ASK`,三句话都指得到问题。

**没重跑的花钱测试 —— 这是当前唯一的回归风险:**

- `tests/flow_demo.py`(约 $0.39)仍是唯一**对着真实模型**跑 `Workflow.run` 的测试,
  `base.py` 改过之后一直没重跑。但**主循环的语义现在被 `tests/flow_offline.py` 钉住了**
  (假 Runtime,24 项:when 跳过 / gate 每次尝试只调一次 / retries 的 #retryN 命名 /
  reduce / on_fail 三种去向 / `_sessions` 血缘 / on_step)。
  改 workflow 层先跑这一套 —— 它不花钱,而且**验证过它能抓到回归**:
  把 `_sessions` 那行退回旧写法,对应那一条立刻变红。
  真实模型那条链路(prompt 真的接上、resume 真的续上)还是只有 flow_demo 能验。
- `smoke.py` / `delegation.py` / `isolation.py` 都不经过 `Workflow.run`(直接用 `Runtime`),
  上次全绿,这次的改动不碰它们的路径。

**仍未验证**(不是遗漏,是成本/权限所限,`README.md` 末尾有完整清单):
真断网端到端(要 sudo 改 hosts,`tests/resilience_live.py` 已写好)、
微压缩在 `DISABLE_AUTO_COMPACT=1` 下的行为(**这条是读二进制反汇编推断的,不是实测**)、
压缩相关 beta 参数经该网关的透传、`PreCompact` hook、几十轮以上超长会话、
1M 窗口(`get_context_usage()` 对该网关超时)、
worktree 的收尾(合并/清理/开 PR —— **有意留给用户的 workflow**)。

**已经 git init 并首次 commit**(第四轮),远端是 GitHub 上的私有仓库 `flower`。
名字讨论过一轮:用户先提 `flovver`、又提 `verse`,最后定回 `flower`。
两个查实的事实,以后要开源/发包时记得:

- **PyPI 上 `flower` 已被占**(Celery 的监控工具)。`pyproject.toml` 现在写的正是
  `name = "flower"` —— 真要发包必须另取(比如 `flower-agent`)。仓库名不受影响。
- `flower.ai` / `flwr` 是知名的联邦学习框架 Flower,同为 Python 框架,搜索会撞。

原来这里写的是"仓库没有 git"(`git rev-parse` 报 not a git repository)。所以没有 diff 可看,
改动只靠这份 HANDOFF 和文件头注释记录。要开源的话迟早得 `git init`,
但**这是用户的决定,别自己动手初始化 / 提交**。

---

## 5. 前置确认 flow:设计要点(已展开成 `docs/clarify.md`,这里留骨架备查)

### 为什么要它

这套框架清理上下文的手段(时效过期、拒绝剪枝、错误摘除、大结果落盘)清的都是**现场**。
而"目标理解错了"是唯一一类**剪枝会让它变严重**的错误:现场被丢掉,留下来的恰好是
那条建在错误前提上的决策,而且它看起来和正确决策一模一样。
长程会把它放大:错误前提先跑几小时、派十几个 subagent、在磁盘落一堆产出,之后才暴露。
到那时贵的不是 token,是**每一个产出都是照错的需求建的**。

### 结构规则(和整套框架一致)

澄清问答是**现场,不是决策** —— 和 subagent 的试错同一类,所以它必须沉到磁盘,
不能进协调者的上下文。落地方式:clarify 跑在**独立 session**,唯一交付物是磁盘上
一份**冻结的四段确认书**;下游用 `resume_from=None`,于是那段对话**从来没进过**
协调者的上下文 —— 不是"进去之后被剪掉"。

### 四段各挡一类失败

| 段 | 不写会怎样 |
|---|---|
| 目标 | 做出来的是另一个东西 |
| 验收标准 | 没人能判定"做完了" |
| 边界 | 范围蔓延;这一段管住后面**每一个** subagent |
| 未知与假设 | **错误前提被静默埋掉** —— 长程的保险丝就是这一段 |

### 两条"必须是机制,不能是提示词"

实测过一个不受约束的确认者(`/tmp/probe_ask.py`,$0.8908 / 230s):
它问完两个问题**直接开始写代码**;被权限拦下之后,**把整份代码贴进了回话正文**。
所以:

1. **工具白名单里没有写工具** —— 它没法开工(`clarify()` 只给 ask + Read/Glob/Grep)
2. **框架只解析那四段** —— 贴了也进不了下游(`Brief.parse` 先摘掉围栏代码块)
3. **提问额度在通道里数**(`max_asks`),超了工具直接回绝,不阻塞

### 没人在的时候怎么活下去

`timeout_s` 到了返回的是**一句说明,不是报错**:"无人应答,自己判断,把假设写进
「未知与假设」"。`timeout_s=0` 就是**全自动模式** —— 所有提问立刻落空,不假装等。
这是长程运行在没人看着的时候能继续跑的原因。

### 已实测的一个机制事实

进程内 MCP 工具处理器里 `await` 一个外部 future **不会死锁**:处理器挂着的时候
事件循环照转,另一个任务或**另一个线程**都能把答案填进来。所以"停下来等人"是可行的。

---

## 6. 地雷 —— 重新踩一次很贵

**架构级:**

- **工作台必须挂在 `Workflow.workbench` 上,不能只拼一个路径。** 本轮修的就是这个:
  `Runtime(workbench=True)`(CLI 的 `-W`)把工作台放在 `<run_dir>/workbench`,
  而文档里的 `flows.py` 用的是 `Path(".flower/notes")`(相对**进程 cwd**)——
  **两个不同目录**。确认书写进 A,注入 system prompt 的索引扫的是 B,于是
  "每个 subagent 开局就知道需求文件在哪"这条承诺**从来没成立过,并且不报错**。
  另一个方向也堵死:`docs/clarify.md` 原来教的是 `wb = rt.workbench`,
  但 `cli.py` 先调 `main()` 造 `Workflow`、之后才建 `Runtime` —— 那时 `brief_path`
  早定死了,**经 CLI 根本拿不到**。所以只有"自己建 `Workbench` → 挂到 `Workflow` 上
  → 驱动交给 `Runtime`"这一条路。`tests/trial_offline.py` 第 5/11 项钉住了它。
- `disallowed_tools` 是**会话级**的。给协调者写它会把 subagent 的 Bash/Write
  一起禁掉(实测报错原文:"Bash is disabled for this session, in subagents as well as here")。
  约束主线程只能用 `allowed_tools` + 按 `agent_id` 过滤的 PreToolUse hook。
- **放行白名单和过期剪枝必须共用一个判定函数**(`is_ephemeral()`)。
  只放行不剪枝 → 过期状态永久占上下文还误导决策;只剪枝不放行 → 为一条 `ls`
  付一次 subagent 启动成本(实测约 4.3k token;协调者启动地板约 34k)。
- 摘 `tool_use` **必须同时**摘它的 `tool_result`(反之亦然),
  且 `relink()` 要收到**包含待摘条目的完整列表** —— 链断了会丢掉断点之前的**全部**历史。
- 工作台放在 workspace 之外时,必须 `add_dirs` 授权,否则 subagent 写不进去(实测被拒两次)。
- `worker(isolate=True)` 要求 workspace 是 git 仓库,否则 Agent 工具直接报
  "not in a git repository"(不会静默退化)。

**这次新增的:**

- **回答提问要真 TTY。** `cli.answer_from_stdin` 用 `input()`,非交互时(管道 /
  `nohup` / CI)第一次就抛 `EOFError` → 它 `decline` 掉当前问题然后**整个线程 return**。
  于是**第二个问题起没人接**,只能干等满 `timeout_s`(默认 1800s)。
  实测过(`timeout_s=3`:第 1 题 0.2s 被跳过,第 2 题等满 3.0s)。
  无人值守要显式 `--timeout 0`。`_drive` 会在 `not sys.stdin.isatty()` 时警告一句,但不拦。
- **argparse 的 `parents` 覆盖坑。** 一键入口的子命令是隐形的(`flower "诉求"` 自动补
  `go`),所以全局开关写在诉求前后都必须能用 → 同一份定义既加在主 parser 也加在子命令上。
  但子命令那份**必须 `default=argparse.SUPPRESS`**,否则没给该开关时它会用默认值
  把主 parser 已经解析出的值盖掉(`flower -v run x` 的 `-v` 会丢)。
- **`max_asks` 和 `max_turns` 必须一起放开。** 每次提问就是一轮:通道里写"不限次数"
  而 `clarify(max_turns=16)` 还在,等于"最多问十几个" —— 那句"不限"就是空话。
  两个都改成 `None` 了。以后加任何"轮数/次数"上限时想一遍这条。
- **判定含糊一律按未达成。** `Verdict.parse` 取不到明确结论时 `state` 留空、
  `ok=False`,框架当未达成处理。反过来(当成达成)就等于让一句
  "看起来应该可以"把活收掉 —— 这正是要防的那个乐观偏差。
- **"无法达成 + 没人应答"必须停,不能重试。** 这就是 `StepAbort` 存在的理由:
  判定为做不到又没人可问,继续跑就是一轮一轮空转烧钱。返回 False 会消耗剩余轮数,
  抛 `StepAbort` 才是立刻停。
- **`with_goal` 里的 gate 是 async 且要派 agent**,所以 `Workflow.run` 把
  `ctx["_runtime"]` 和 `ctx["_on_event"]` 都灌进去了。`on_event` 不能漏 ——
  判定那十几秒如果不打事件,界面全黑,看起来就像卡住(这个项目已经有一次
  "看起来卡住其实没事"的教训了,见下一条)。
- **命令行让人打引号就是设计缺陷。** 用户第一次跑把右引号打成了中文 `”`,
  zsh 卡在 `dquote>` 续行上,他以为程序挂了 —— 而实际一次都没启动。
  现在 `flower` 不带参数就进交互输入(`cli.ask_for_prompt`),诉求走标准输入。
  容器侧对应改动:Dockerfile 的 `CMD` 清空(原来是 `["--help"]`,
  否则 `flowerbox` 不带参数会打印帮助而不是提问)。
- `_with_default_cmd` 判断"要不要补 go"时,**全局开关集合是从 `parser._actions` 派生的**,
  不是硬编码。以后加全局开关不用改那里。也**不能**用"argv 里出现过 run/once 吗"来判断 ——
  诉求正文可能刚好就是那个词;只看第一个非开关 token。
- `Workflow.run` 原本**每步调 `step.gate` 两次**(重试循环里一次、循环后一次)。
  已改成只调一次并复用结论 —— gate 可能有副作用(确认书落盘),不能重复触发。
  **以后改这个循环时留意这一点。**
- `ctx[step.name] = result.text` 会把解析好的四段**覆盖成模型原文**(含它贴的代码)。
  这是 `Step.reduce` 存在的原因,不是可有可无的糖。
- **`ctx` 就是 `Workflow.context` 本身**(同一个对象,不是拷贝)。同一个 `Workflow`
  跑第二次,上一次的键全都还在 —— 包括 `_failed_at`。要干净重来就新建一个 `Workflow`,
  或者显式传 `context={}`。本轮顺带修掉的那个:`_sessions` 以前和循环实际写的
  **不是同一个 dict**,于是第二次运行时它会停在上一次的 session_id 上。
- MCP 工具要数组参数(`options`)时,`input_schema` 必须给**完整 JSON Schema dict**。
  SDK 的 `_build_input_schema` 只有在 dict 同时含 `type`(str)和 `properties` 时才原样上线,
  否则会把它当成 name→type 的简写。
- `channel.answer()` 常常**来自别的线程**(Web 后端 / TUI 输入线程)——
  这是常态不是边缘情况。`asyncio.Future.set_result` 不是线程安全的,
  必须走 `loop.call_soon_threadsafe`。
- 别用 `asyncio.to_thread(input, ...)` 读标准输入:`input()` 取消不掉,
  而 `asyncio.run` 退出前会 join 默认执行器的线程 → 活干完了还得按一次回车才能退出。
  用 daemon 线程(`cli.py:answer_from_stdin` 就是参考实现)。
- `next_ask()` **不要吞 `asyncio.CancelledError`** —— 吞了调用方的循环就停不下来。
  只接 `TimeoutError`。
- 没有写工具的角色要 `AgentSpec.workbench=False`:工作台索引全是"把东西写进哪个目录",
  它一条都执行不了,纯占 token 还添乱。(hook 照挂 —— spill 对它的 Read 仍有用。)

**环境:**

- `flower/core/workflow.py` **不存在**。workflow 层是 `flower/workflow/` 包(`base.py`)。
- zsh 会把 `grep --include=*.py` 的参数当 glob 展开并报 `no matches found`。加引号或换写法。
- macOS 没有 `timeout` 命令。

**方法:**

这个项目一路的做法是**先量再说**:每条结论后面都有一次实测(花费、token 数、
被拒原文、反汇编读出的默认值)。文件头注释里记的是"为什么这样",别当废话删掉 ——
那是这套东西唯一的设计文档,直到 `docs/` 写出来。

---

## 7. 代码地图

```
flower/
  core/
    env.py         内置二进制定位、凭证(脱离 CLI 的那一层)
    agent.py       AgentSpec —— 一个 agent 的完整声明(含 workbench 开关)
    runtime.py     跑一次 = 一个 session;落盘、重试、hook 装配
    roles.py       coordinator / worker / clarify + 三套角色纪律提示词
    guard.py       PreToolUse hooks:delegate_guard(按段判定的 Bash 白名单)、isolate_guard
    workbench.py   .flower/{scripts,artifacts,notes} + 索引注入
    human.py       提问通道(唯一一处"停下来等人")
    brief.py       四段确认书
    goal.py        Goal(可判定目标)+ Verdict(达成/未达成/无法达成)
    events.py      Event / EventKind —— 交互层的唯一边界
    resilience.py  错误分类、探针、重试
  stores/
    sqlite.py      transcript 落盘(原文永不动)
    prune.py       断线残渣 + 被拒调用摘除 + 链重接
    trim.py        时效过期 + 大结果换文件指针 + is_ephemeral()
  workflow/
    base.py        Step / Workflow(三种会话接法 + gate/when/reduce/retries)
    clarify.py     前置确认接线
    goal.py        目标看守:goal_step(设目标) + with_goal(判定循环)
    starter.py     starter_flow —— `flower` 的三步默认流程(不是"推荐设计")
  cli.py           参考交互层:渲染 Event、标准输入回答、go/run/once
                   (会自动发现 wf.channel 和 wf.workbench)
docker/            容器化 + 国内网络的镜像替换(见 §10)
docs/              给陌生读者的四篇(见 §2.2)。改了行为记得同步它
examples/trial.py  模板,48 行 —— 照它写自己的 flows.py(试用不需要它)
tests/             见 §4;README 末尾有每套的花费
plugin/            Claude Code 插件形态(agents/ 还空着)
```

---

## 8. 让用户试用:一条命令

```bash
cd ~/他的项目          # 用容器的话必须在 $HOME 下,见 §10
flower                # 不带参数 → 光标等着,输一句要做什么
```

```
要做什么? 一句话就够,回车开始(Ctrl-C 退出)
> 帮我做一个 X
```

**为什么是交互输入而不是命令行参数**:他第一次跑就栽在引号上 —— 右引号打成了
中文的 `”`,zsh 一直在等真正的右引号(`dquote>` 续行提示符),看起来像程序卡住,
其实**一次都没启动**(`docker ps -a` 空、工作目录空、`$HOME` 下无任何新产物)。
他的原话:**"我觉得这样不方便,应该直接一个flower启动……然后闪烁光标等待输入prompt。
就不用自己打引号了"**。诉求现在走标准输入,不经过 shell 解析。
参数形式仍然保留(脚本/一行式用):`flower "…"`、`echo "…" | flower --timeout 0`。

`flower` 已软链到 `~/.local/bin/flower`(在他 PATH 里),指向
`/Users/hechenyu/projects/flower/.venv/bin/flower`,shebang 是绝对路径所以到哪都能跑。
凭证走仓库根的 `.env`(见 §9),`env -i` 验证过不依赖任何继承的环境变量。

不写子命令时自动补 `go`。开关写在诉求前面或后面都行:

| 开关 | 作用 |
|---|---|
| `--clarify-only` | 只问清需求,不往下干活 |
| `--asks N` | 提问额度,默认 6;`-1` 不限,`0` 不许提问 |
| `--timeout 秒` | 等他多久,默认 1800;**`0` = 全自动,没人时不阻塞** |
| `--isolate` | 每个 subagent 分一份 git worktree(要求是 git 仓库,工作台自动移到仓库外) |
| `-v` | 显示思考与工具结果 |

只给开关不给诉求也行(`flower --clarify-only` 会先问要做什么)。
`flower --help` 不会被截走 —— `_with_default_cmd` 见到 `-h/--help` 就原样交给 argparse。

另两个子命令没动:`flower run flows.py:main`(他自己设计的 workflow)、
`flower once "…"`(单 agent)。

跑完让他看:`.flower/notes/需求.md`(冻结的四段)、`.flower/notes/问答记录.md`、
`.flower/INDEX.md`(注入 system prompt 的索引 —— 需求文件应当出现在里面)、
`runs/manifest.json`(每步 session_id / 花费)。

**必须在真终端里跑。** 回答走标准输入,非 TTY 时(管道 / `nohup` / CI)第一个问题会被当成
"输入已关闭"跳过,之后每个问题都要干等满 `--timeout`(默认 1800s = 每题 30 分钟)。
实测过,见 §6。`_drive` 现在会在非 TTY 时先警告一句,但不拦。

**写自己的 flows.py 时唯一容易错的地方**:工作台要自己建、然后挂到
`Workflow(workbench=wb)` 上,`brief_path` 用 `wb.notes / "需求.md"`。
别自己拼路径,也别想从 `Runtime` 反着拿 —— 两个错法都不报错。理由见 §6 第一条。
`examples/trial.py`(48 行)就是照抄的模板,三处易漏的接线标了 ① ② ③。

## 9. 安全

- `~/.claude/settings.json` 里有明文 `ANTHROPIC_AUTH_TOKEN`。已提醒用户:
  那个文件若曾被同步或提交过,应当轮换。
- 本仓库:`.env.example` 只有占位符。**`.env` 现在存在了**(第三轮建的,`chmod 600`,
  已 gitignore):内容是从 `~/.claude/settings.json` 的 `env` 块搬过来的
  token / BASE_URL / 模型映射 / `DISABLE_AUTO_COMPACT=1`。
  为什么必须建:`flower` 用 `setting_sources=[]`,**不读** `~/.claude/settings.json` ——
  而 Claude Code 只把那些变量注入自己的子进程,用户在自己的终端里跑时环境是空的。
  换机器时单独拷这个文件,别提交。
- `describe()`(`-v` 会打印它)的 token 打码只留前 4 位 —— 原来留 7 位,
  而这个网关签发的 token 只有 19 位,截图或粘贴日志就漏掉三分之一了。
- 读过 `~/.claude/projects/*.jsonl` 但**只看结构,没看对话内容**。保持这条。
---

## 10. 容器(`docker/`)—— 也是可移植性的检验

```bash
docker/build                                    # 一次
cd ~/项目目录                                    # 必须在 $HOME 下,见下
/Users/hechenyu/projects/flower/docker/flowerbox "帮我做一个 X"
```

参数和 `flower` 完全一样。**已实测**(2026-09-06,colima + docker 28.4.0,arm64):

- 镜像里 `claude` / `node` / `npm` / `npx` **都不存在**;自带二进制是 `\177ELF`(207M),
  不是宿主那份 Mach-O arm64(191M)
- 经 `cloud.infini-ai.com/maas` 跑通真实请求:**$0.1741 / 1 轮**
  (Opus 5 + 1M 窗口的单轮地板价 —— 我先前估"几分钱"是估低了)
- 容器内写 `/work` 的文件在宿主是 `hechenyu:staff`;容器里 `ls /Users` → 不存在
- 零花费端到端(预置确认书 → 跳过)在容器里也通,`.flower/` 和 `runs/` 落在宿主

### 地雷(都踩过)

- **项目目录必须在 `$HOME` 下。** colima 默认只挂 `$HOME`。在 `/tmp` 下跑,
  `-v` 会在 VM 里建个**空目录**,写进去的东西宿主永远看不到,**而且不报错** ——
  产出/确认书/`runs/` 全部静默丢失。第一次 smoke test 就这么丢的($0.17 白花)。
  `flowerbox` 现在会挡:`$HOME` 下直接过,否则用探针实测,过不了退出 1。
- **`docker run -t` 在非 TTY 下直接报错**("the input device is not a TTY")。
  `flowerbox` 只在 `[ -t 0 ]` 时加 `-t`;`-i` 一直要。
- **宿主的 `.venv` 挂不进去** —— macOS arm64 的 Mach-O 二进制在 Linux 里跑不了。
  镜像必须自己 `pip install` 拿 `manylinux_2_17_aarch64` 那个 wheel。
- **`libstdc++6`**:SDK 自带的二进制是 Bun 编译的单文件,Linux 上要它,slim 镜像不带。
- **colima 的 VM 会卡在 cloud-init**:lima 的 `30-install-packages.sh` 为了装 `rsync`
  跑 `apt-get update`,打 `ports.ubuntu.com`(VM 内 26 KB/s)和
  `download.docker.com`(4 KB/s)。处置前**先读 `/mnt/lima-cidata/boot.sh`**:
  它对失败的 boot 脚本只 `WARNING` + `CODE=1` 然后继续,末尾**一定**会写
  `/run/lima-boot-done` —— 所以"换源 + `pkill apt-get update`"是安全的,
  boot 会自己走完,`colima start` 正常退出。细节和命令在 `docker/README.md`。
- **colima 用的不是普通 Ubuntu cloud image**,而是 `abiosoft/colima-core` 那个
  **预装 docker** 的定制镜像。我先下错过一个 593MB 的普通 cloud image。
  正确的用 `--disk-image` 喂进去,digest 从 GitHub API 拿来校验。

### 国内网络

慢的不是带宽是国际线路:`pypi.org` 32 KB/s、包文件 284 B/s、
`deb.debian.org` 32 KB/s、`cloud-images.ubuntu.com` 382 B/s、
`download.docker.com` **连不上**、tuna **连不上**;而
USTC 28 MB/s、`ghfast.top` 2.5 MB/s、阿里云包文件 1.4 MB/s。
四处替换都在 `docker/build` 里,`FLOWER_MIRRORS=0` 全关。

**量的时候别把索引页当包文件**:`mirrors.aliyun.com/pypi/simple/` 有 7.4 MB/s,
真正 95.9 MB 的 wheel 只有 1.4 MB/s(VM 内 152 KB/s)。我先前就报错过一次。

一次性准备约 25 分钟(大头是 364MB VM 镜像 + 95.9MB wheel),之后启动秒级。

---

## 11. 目标看守(第四轮)—— 做完了没有,不由干活的人说

用户原话(两点,都实现了):

> 需求提问为什么还有次数限制,这个应该让那个负责的agent来决定啊,如果一直没问清楚
> 需求那就一直问呗,用户不会嫌烦。
>
> 在第一轮需求确认完之后应该有一个goal的设定,这个也可以单独一个agent来管理,
> 任务是设定goal和每一轮交互结束之后验证goal是否achieve,如果没有就应该直接打回主agent,
> 让主agent继续。(这里这个goal agent应该只需要传0/1参数即可,或者 goal could not be
> achieved 需要向用户说明情况,然后跟用户交互,是接受这个结果还是修改goal还是觉得goal
> 可以achieve只是agent判断失误)

### 落成了什么

```
确认需求 ──> 设定目标 ──> 干活 ──> 判定 ──达成────> 往下走
                                    ├─未达成──> 打回,续跑同一个 session 接着做
                                    └─无法达成─> 问人:接受 / 改目标 / 你判断错了
```

- **判定跑在独立 session**(`roles.judge`):没写工具,看到的只有目标和现场。
  理由和确认者一样 —— 判定不能由干活的人自己下,它有系统性的乐观偏差。
- **三态而不是 0/1**。他说"只需要传 0/1",但他括号里那段("goal could not be
  achieved 需要向用户说明")其实描述了第三种状态,所以做成三态。
  `Verdict.parse` **同时认**光秃秃的 `1`/`0` —— 判定者真只回一个数字时也能用。
- **打回 = 续跑**(`Step.on_reject`),不是重头跑。步骤名 `#round2` vs `#retry1`
  在 manifest 里区分得出来。
- **轮数有上限(默认 3),提问没有上限。** 依据:提问几乎不花钱,一轮活是真金白银。
  真正的兜底不是那个数字,而是第三态 —— 它一出现就停下来问人。

### 留给他决定的两个取舍(我选了保守的默认)

1. **`rounds` 默认 3**,不是无限。他对提问说了"一直问呗",但没对干活轮数表态;
   一轮活会真花钱,所以我设了上限。他要改就 `--rounds N`。
2. **判定者默认不能跑命令**(`--judge-can-run` 才给 Bash)。取舍写在
   `docs/goal.md`:能跑命令判定更硬,但它就能改工作区 —— 可能"顺手修一下"
   然后判定通过,那这次判定就没意义了。
