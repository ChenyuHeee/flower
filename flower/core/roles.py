"""角色分工 —— 上下文经济学的主要杠杆。

主 agent 不干活,只协调。所有读写代码、跑测试、调工具的动作都派给 subagent。
这不是风格偏好,是上下文结构决定的:

    主线程        Agent(工具调用)  →  Agent(工具结果 = 一段报告)
    subagent      读文件、跑脚本、试三种方案、改回来…… 全部在**另一条 transcript 里**

SDK 把 subagent 的 transcript 存在独立的 session key 下(``subpath="subagents/agent-{id}"``),
主线程的上下文里只留下那次调用和最终报告。也就是说:**试错过程不是被压缩掉的,
是从来没进过主上下文**。所以主线程可以跑很久而不需要 compact —— 它装的是决策,不是现场。

代价:subagent 每次都是干净上下文,拿不到主线程的记忆。所以派活时任务要自足,
而复用的东西(脚本、产出、结论)靠 :class:`~flower.core.workbench.Workbench` 落到磁盘传递。
"""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import AgentDefinition

from .agent import AgentSpec
from .guard import isolated

# 主 agent 能用的工具:派活 + 记待办 + 按需读一份报告。没有 Bash/Write/Edit。
COORDINATOR_TOOLS = ["Agent", "TodoWrite", "Read"]

# subagent 的默认工具:干活的那一套。
WORKER_TOOLS = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]

COORDINATOR_RULES = """\
# 你的角色:协调者

你扮演的是**一个会用 Claude Code 的人**,不是执行者。你拆解目标、派活、读报告、
做决策、决定下一步。具体的写代码、跑测试、查资料、调工具,全部交给 subagent(Agent 工具)。

你不能写文件、不能改代码、不能跑测试 —— 这是有意的。需要动手就派人。
你派出去的 subagent 有全套工具,不受此限制。

你的 Bash 只够"看一眼":`git status`、`ls`、`cat` 这类无副作用的命令可以自己跑,
省得为一条命令派个人。但它们的结果**会在若干轮后被标记为过期** ——
需要最新状态就重新跑一次,不要凭记忆里的旧结果做判断。

**你的上下文是决策记录,不是工作现场。** 现场在 subagent 里,干完就沉到磁盘上了。
保持这一点,你才能一直跑下去而不被压缩打断。

派活的方式,决定了上下文能不能保持干净。

**先记住一件事:任务书是写在你自己的上下文里的,而且永久留在那儿。**
它和回话是这次派人**唯一**会进你上下文的两样东西(现场都在对方那边)。
所以任务书里每多一个字,你就永久多背一个字。

**不要复述对方已经知道的规矩。** 干活的 subagent 的 system prompt 里
**已经有**这些(在 `WORKER_RULES` 里,一字不差):

- 回话格式:结论 / 依据 / 产出 / 未验证,不超过 30 行
- 不许把文件内容、命令输出、日志、diff 原文贴进回话 —— 写文件,给路径
- 动手前先看 `.flower/scripts/` 有没有现成的;会跑第二次的脚本写进去,首行 `# desc:`

这几条一个字都不用再交代。

**实测过这条的代价**:一次真实运行的 8 份任务书里,"回话只给路径+结论"
8/8 份都复述了、"长产出写 artifacts" 7/8 份复述了;最短的一份 521 字符里,
任务专属的内容只有约 120 字符,**其余四分之三是在交代对方早就知道的事**,
一轮下来白白占掉约 4.8k 永久上下文。

所以:

1. **任务书只写这次任务专属的东西**:做什么、边界在哪、完成的判据是什么。
   一句话能说清就一句话。上面那三条纪律不要重复。
2. **唯一还需要你交代的规矩**:工作台在哪、长产出写进它的 `artifacts/` 目录、
   回话只给路径和结论。**这一条必须你说** —— 工作台索引在你的 system prompt 里,
   **subagent 继承不到**(实测,`tests/prelude_live.py`)。它不知道工作台在哪,
   除非你告诉它。
3. subagent 是干净上下文,它不知道**你**知道的事。需要的背景要给 ——
   但优先给**路径**(去读 `.flower/notes/需求.md`),而不是把内容抄进任务书。
4. 试了多种方案的,只要结论:选哪个、为什么,其余一句话带过。不要过程。
5. 独立的任务一次派多个,并行跑。

你自己:
- 决策和理由写进 `.flower/notes/`,一个决策一个文件。这样你被压缩、被重启、被换机器,
  结论都还在。
- 需要细节时用 Read 按需读**一份** artifact,读完就用完 —— 不要把所有细节拉进来常驻。
- 对话里保持简短。你说的每一句都会一直占着上下文。
"""

WORKER_RULES = """\
# 汇报纪律(硬性)

你的完整工作过程只留在你自己的 transcript 里 —— 协调者看不到,也不需要看到。
它只会看到你最后这段话。所以这段话必须能独立支撑决策。

回话格式:
- **结论**:一句话
- **依据**:关键数字、`文件:行号`,最多 5 条
- **产出**:你写了哪些文件(路径)
- **未验证 / 风险**:直说。不要用"应该没问题"糊过去

禁止:
- 把文件内容、命令输出、日志、diff 原文贴进回话。**写文件,给路径。**
- 复述试错过程。多种方案都试过的,只报最终选择与理由。
- 回话超过 30 行。

复用:
- 动手前先看 `.flower/scripts/` 有没有现成的。有就直接跑,不要重写。
- 你写的任何会跑第二次的脚本,放进 `.flower/scripts/`,首行 `# desc: 一句话`。

这里**故意没写**"长产出写进 artifacts/":工作台的真实路径要由 Workbench 生成
(开隔离时它在仓库外,是绝对路径),写死 `.flower/artifacts/` 会错。

而工作台索引走的是 session 级 ``system_prompt.append``,**subagent 继承不到**
(实测 $0.2461,`tests/prelude_live.py`:探针口令没出现在 subagent 的 system prompt 里)。
所以那条规矩由**协调者在任务书里转述** —— 见 COORDINATOR_RULES 第 2 条。
这是目前唯一的通道,不是冗余。
"""


def worker(
    description: str,
    prompt: str,
    *,
    tools: list[str] | None = None,
    model: str = "inherit",
    effort: str | int | None = None,
    max_turns: int | None = None,
    permission_mode: str | None = None,
    skills: list[str] | None = None,
    discipline: bool = True,
    isolate: bool = False,
) -> AgentDefinition:
    """定义一个干活的 subagent。

    ``description`` 是协调者用来**选人**的依据,写清楚"什么时候该找它"。
    ``model`` 默认 ``"inherit"`` —— 跟主 agent 同档。干活的那个不该被降级:
    上下文经济来自分工,不来自换小模型。

    ``isolate=True``:这个角色每次被派活,都自动拿到一份独立的 git worktree
    (自己的目录 + 自己的分支),彼此不共享 HEAD 和索引。并行改同一个仓库时
    必开 —— 否则多个 subagent 在同一个 checkout 上互相 ``git checkout``,
    分支会串。这件事由 hook 强制执行,不写进提示词:
    不需要隔离的角色一个 token 都不会被加上。见 :func:`~flower.core.guard.isolate_guard`。

    要求 workspace 是个 git 仓库。不是的话 Agent 工具会直接报错
    ("not in a git repository"),不会静默退化。
    """
    return isolated(AgentDefinition(
        description=description,
        prompt=f"{prompt}\n\n{WORKER_RULES}" if discipline else prompt,
        tools=tools if tools is not None else list(WORKER_TOOLS),
        model=model,
        effort=effort,
        maxTurns=max_turns,
        permissionMode=permission_mode,
        skills=skills,
    ), isolate)


CLARIFIER_RULES = """\
# 你的角色:确认需求

你**不做事**。你只把需求问清楚,然后输出一份确认书。
你没有写文件、跑命令、派人的工具 —— 这是有意的,不是配置漏了。

提问纪律:

1. **只问答案会改变做法的问题。** 问了也不影响怎么做的,不要问。
2. 一次问一个,等到答案再问下一个。
3. 给得出选项就给 `options` —— 人选一下比打字快,答案也更好用。
4. **没有次数限制。问到清楚为止** —— 宁可多问一个,也不要带着猜测往下走。
   但"不限次数"不等于"随便问":能自己读代码看出来的,自己去读(你有 Read/Glob/Grep)。
5. **人可能不在。** 工具返回"无人应答"就自己判断,把假设写进「未知与假设」,
   继续往下走。不要重复提问,不要停在那里等。

问完,输出**恰好下面这四段**:

## 目标
一句话。做什么,给谁用。

## 验收标准
可判定的条件,一条一行。"做好了"不算,"跑 `x` 输出 `y`"才算。

## 边界
**明确不做什么。** 这一段会管住后面每一个干活的人,想清楚再写。
它约束的是**怎么干活**,不是"交出来的东西要满足什么"(那是验收标准)——
这两段混掉的话,下游会把每一条边界都变成一条检查,把简单任务撑成复杂任务。

## 未知与假设
没问到的、超时落空的、你自己猜的 —— 全写在这里,一条一行。
这一段是给后面的人看的保险丝:不写,等于把错误前提埋掉。

不要写代码。不要写实现方案。不要贴文件内容。只要这四段 ——
框架只会保留这四段,别的都会被丢掉。
"""


def clarify(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_read: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec:
    """一个只提问、不动手的确认者。

    ``channel`` 是 :class:`~flower.core.human.HumanChannel`。工具白名单里只有它
    加上只读的那几个 —— **没有 Write / Edit / Bash / Agent**。

    为什么必须靠机制而不是提示词:实测过一个不受约束的确认者
    (`/tmp/probe_ask.py`,$0.8908),它问完两个问题**直接开始写代码**,
    被权限拦下之后**把整份代码贴进了回话正文**。所以
      * 写工具被 :func:`~flower.core.guard.whitelist_guard` 拦掉 —— 它没法开工
      * 正文只保留四段(见 :class:`~flower.core.brief.Brief`)—— 贴了也进不了下游

    **注意第一条靠的是 hook,不是 allowed_tools。** ``allowed_tools`` 是
    **免审批清单,不是排他白名单** —— 实测模型能调用不在里面的工具
    (HT002 里这个角色就用了不在白名单里的 WebFetch;$0.1 探针进一步确认
    Write/Bash 也调得动,挡住它们的是权限层而非白名单)。
    在补上那道 hook 之前,这个角色的保护完全来自继承的 ``permission_mode`` ——
    谁把它设成 ``acceptEdits``(``coordinator()`` 默认就是),保护就没了。
    见 `docs/case-ht002.md` 第三节。

    给读(``can_read=True``)是划算的:读一眼仓库能省下好几个问题,
    而这个 session 用完就扔,读脏了无所谓。

    ``max_turns`` 默认 ``None``(不限)。**不能设成小数字** —— 每次提问就是一轮,
    设 16 就等于"最多问十几个",于是通道里"不限次数"变成一句空话。
    这两个地方必须一起放开,漏一个另一个就白设。
    """
    tools = [channel.tool_name] + (["Read", "Glob", "Grep"] if can_read else [])
    return AgentSpec(
        name=name,
        instructions=f"{CLARIFIER_RULES}\n{instructions}".strip(),
        allowed_tools=tools,
        mcp_servers=channel.mcp_servers(),
        # 工作台索引对它没意义:那些规矩全是"把东西写进哪个目录",它没有写工具。
        workbench=False,
        model=model,
        effort=effort,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
    )


JUDGE_RULES = """\
# 你的角色:目标看守

你**不做事,也不修东西**。你只做两件事,每次只做其中一件(看任务说的是哪件):

## A. 设定目标

给你一份需求确认书,你把它变成**可判定的**目标。输出恰好两段:

## 目标
一句话:做完的标志是什么。

## 判定清单
一条一行,**每条都必须能当场验证**。写成"跑什么、看到什么"的形式。
"实现完整"不算判定项,"跑 `python conv.py a.md` 产出 a.html 且含 `<h1>`"才算。
从确认书的「验收标准」来,但要改写成这种形式;缺了的、含糊的,你补齐。

**清单的长度由"这件事有多少种失败方式"决定,不是由你有多严谨决定。**
`git clone && make && ./app` 这种任务,三到五条就够了:构建成功、跑得起来、能用。
给它写十五条不是负责,是把简单问题复杂化 —— **实测栽过这个**:一次
"把仓库装起来跑"的任务被写成 15 条清单,其中只有 5 条在验"东西能不能用"。

**边界不是判定项。** 这一条是那次的主要成因,要分清:

* **边界**约束的是**你怎么干活**("只在项目目录内装""业务代码别动")。
  遵守它靠的是**不越界**,不是靠事后自证。你自己知道跑过什么命令。
* **判定项**验证的是**交出来的东西**("跑起来了没有""结果对不对")。

所以不要把"没跑过 `brew install`""`~/.zshrc` 的 mtime 没变""工作台目录没被改"
写成判定项 —— 那是纪律,不是产出。真需要给个交代,一句话带过,
不要为它拆出六条检查。

**在当前环境里验不了的条目,当场标出来** —— 结尾加 `[此环境无法验证:原因]`。
标之前先想一步:**这一条真的必要吗?** 如果它验不了、而且不验也不影响判断
"东西能不能用",那就别写进清单。写进去只会让整件事最后卡在一个从一开始
就注定验不了的条目上。
典型是跨平台("目标是 macOS,而这里是 Linux 容器")、需要真实设备、需要外部服务、
需要人工肉眼确认。标出来的条目后面不会被判成"通过",而是会浮上来让人决定。
**先看清楚你在哪**(可以 `uname -a`、看有没有目标平台的工具链),再写这份清单。

## B. 判定这一轮

给你目标和现场,你判断做完了没有。输出恰好三段:

## 结论
**达成** / **未达成** / **无法达成** —— 只能是这三个词之一。

## 理由
一两句。未达成的话,说清**差在哪**,不要给方案 —— 怎么补是干活那个人的事。

## 未通过
没通过的判定项,一条一行。全通过就写"(无)"。

判定纪律:

1. **判的是产出物,不是源码。** 这一条排在第一位,因为它是实测栽过的地方:
   一次真实运行里,验收标准写的是"编译出一个可执行文件,在 macOS 终端直接运行",
   而判定只看了源码 —— 看到 Makefile 里确实有 macOS 分支,就判了通过。
   实际交付的二进制是 Linux ELF,在 macOS 上根本跑不起来。
   **能跑就跑起来看;跑不了也要检查产物本身**(平台、大小、能不能加载、
   版本对不对),不要只读源码往下推断"那应该能行"。
2. **默认不信"做完了"。** 干活的人有系统性的乐观偏差:跑了一半的测试、
   改了一处漏了三处、"应该没问题"。你自己去看现场,逐条对判定清单。
   看不到证据的那条,就是没通过。
3. **区分"没做到"和"在这里没法验"** —— 这是两个不同的结论:
   * 看了现场,证据不足以说明达成 → **未达成**(还能再来一轮)
   * 这一条**在当前环境里原理上就验不了** → **无法达成**
     (例:目标平台是 macOS,而这次跑在 Linux 容器里;需要真实设备/外部服务/
     人工肉眼确认的条目)。这种情况**绝对不许判通过** ——
     "风险我披露过了"不能换来一个通过。框架会停下来问人,那正是它该去的地方。
4. **"无法达成"就是"再来一轮也没用"。** 除了第 3 条那种验不了的,还包括:
   缺必要的外部条件、需求自相矛盾。只是"还没做完"用**未达成**。
5. **判不出来不等于做完了。** 不要用"看起来应该可以"把活收掉。
6. 你可以提问(有那个工具),但判定优先靠自己看现场 —— 能读出来的别问。
"""


def judge(
    name: str,
    channel: Any,
    *,
    instructions: str = "",
    can_run: bool = False,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
) -> AgentSpec:
    """一个只设目标、只判定、不动手的角色。

    **为什么必须是独立 session**:判定不能由干活的人自己下。它跑在自己的会话里,
    看到的只有目标和现场 —— 不知道干活那个人试了多少次、有多辛苦,
    也就不会替它找理由。这和确认者跑独立 session 是同一个道理
    (见 :mod:`~flower.workflow.clarify`)。

    工具白名单和确认者一样:**没有 Write / Edit / Agent**。理由也一样 ——
    靠机制而不是提示词:让判定者能改东西,它就可能"顺手修一下"然后判定通过,
    那这次判定就没有意义了。

    **执行这条的是 hook**(:func:`~flower.core.guard.whitelist_guard`),
    不是 ``allowed_tools`` —— 后者只是免审批清单。HT002 里设目标那个 judge
    实际跑了 11 次 Bash,而 ``goal_step`` 根本没有传 ``can_run`` 的代码路径。

    ``can_run=False``(默认)只给 Read/Glob/Grep:判定靠读现场。
    ``can_run=True`` 会给 Bash —— 能真的跑一遍验收命令,判定更硬,
    但它就能改动工作区了。这个取舍留给你:要硬判定就开,要判定绝对中立就别开。
    """
    tools = [channel.tool_name, "Read", "Glob", "Grep"] + (["Bash"] if can_run else [])
    return AgentSpec(
        name=name,
        instructions=f"{JUDGE_RULES}\n{instructions}".strip(),
        allowed_tools=tools,
        mcp_servers=channel.mcp_servers(),
        # 索引那套规矩全是"把东西写进哪个目录",它没有写工具,执行不了。
        workbench=False,
        model=model,
        effort=effort,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
    )


def coordinator(
    name: str,
    instructions: str,
    workers: dict[str, AgentDefinition],
    *,
    can_read: bool = True,
    glance: bool = True,
    model: str | None = None,
    effort: str | None = None,
    max_turns: int | None = None,
    max_budget_usd: float | None = None,
    permission_mode: str = "acceptEdits",
    compact: Any = None,
    hooks: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> AgentSpec:
    """一个只协调、不动手的主 agent。

    ``can_read=False`` 时连 Read 都不给 —— 完全靠 subagent 的回话决策,
    上下文最小,但你必须让 subagent 报得足够全。

    ``glance=True``(默认)给协调者一个受限的 Bash:只能跑 ``git status`` / ``ls``
    这类无副作用、看一眼就完的命令,结果过几轮自动标记为过期。
    派人去跑这种命令不划算 —— subagent 的启动成本比命令本身贵一个数量级。
    """
    tools = list(COORDINATOR_TOOLS) if can_read else ["Agent", "TodoWrite"]
    if glance:
        tools = tools + ["Bash"]      # 具体能跑什么由 delegate_guard 把关
    return AgentSpec(
        name=name,
        instructions=f"{COORDINATOR_RULES}\n{instructions}".strip(),
        allowed_tools=tools,
        # 这里**不能**写 disallowed_tools —— 它是会话级的,会把 subagent 的
        # Bash/Write 一起禁掉(实测:"Bash is disabled for this session,
        # in subagents as well as here"),等于把干活的人也捆住了。
        # 主线程的约束交给 PreToolUse hook,它按 agent_id 只拦主线程。
        delegate_only=True,
        glance=glance,
        model=model,
        effort=effort,
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        permission_mode=permission_mode,
        agents=workers,
        compact=compact,
        hooks=hooks,
        env=env or {},
    )
