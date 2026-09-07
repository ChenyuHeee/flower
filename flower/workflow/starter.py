"""开箱即用的起步流程 —— `flower "帮我做一个 X"` 背后就是它。

**这不是"推荐的 workflow 设计",是让你零配置就能跑起来的最小形状。**
三步,通用到不含任何领域假设:

    1. 确认需求   只提问、不动手,问完冻结成四段确认书(clarify_step)
    2. 设定目标   把确认书变成可判定的清单,冻结(goal_step)
    3. 干活       协调者读确认书和目标,派 subagent 实现;
                  **每一轮结束由独立的判定者判"做完了没有"**,
                  没达成就打回来接着做(with_goal)

第 2、3 步挡的是和第 1 步不同的失败:第 1 步挡"做的不是想要的东西",
这两步挡"其实没做完,但它自己说做完了"。见 :mod:`~flower.workflow.goal`。

领域设计是**你的**活:自己写 `Step`/`Workflow`,用 `flower run flows.py:main` 跑。
`examples/trial.py` 是照着抄的模板。这里只负责"还没设计之前也能立刻试"。

它替你接好的三件事,自己写的时候容易漏:

  * **工作台挂在 `Workflow.workbench` 上**,`brief_path` 落在它的 `notes/` 里 ——
    索引会注入**主 agent** 的 system prompt(subagent 继承不到,实测见
    `tests/prelude_live.py`),协调者据此在派活时把路径转述下去。
    自己拼路径会拼到别处,而且不报错。见 `docs/workflow.md`。
  * **开隔离时工作台移到仓库外** —— worktree 是每个 agent 的私有副本,
    工作台是跨 agent 的共享层,共享的东西不能放进私有围栏里。
  * **提问通道同时挂在 channel 上**,驱动程序才知道该向谁回答。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..core.brief import Brief
from ..core.goal import Goal
from ..core.human import HumanChannel
from ..core.lineage import Lineage
from ..core.roles import coordinator, worker
from ..core.workbench import Workbench
from .base import Ctx, Step, Workflow
from .clarify import clarify_step
from .goal import GOAL_KEY, goal_step, with_goal

DEFAULT_WORKER_PROMPT = "你负责实现。每改一处就跑一次验证,别攒到最后。"


def _bench(ws: Path, isolate: bool) -> Workbench:
    """工作台放哪 —— **只此一处定义**。

    开隔离时必须在仓库外:worktree 是每个 agent 的私有副本,工作台是跨 agent
    的共享层,共享的东西不能放进私有围栏里。驱动程序想知道确认书在哪,
    也走这个函数,不要自己拼路径(拼错了不报错,只是静默失效)。
    """
    home = (ws.parent / f".flower-{ws.name}") if isolate else None
    return Workbench(ws, home=home)


def wake_state(
    workspace: str | Path = ".",
    *,
    run_dir: str | Path = "runs",
    isolate: bool = False,
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
) -> dict:
    """**起跑之前**问一句:这个目录用过没有?

    给驱动程序用的只读探测 —— 它决定命令行上该提示"要做什么"还是"接着上次"。
    一个字节都不写,叫它是安全的。

    返回 ``{"waking", "brief", "goal", "checks", "woke", "steps"}``。
    """
    ws = Path(workspace).resolve()
    wb = _bench(ws, isolate)
    brief_path, goal_path = wb.notes / brief_name, wb.notes / goal_name
    b = Brief.load(brief_path)
    g = Goal.load(goal_path)
    lin = Lineage.open(run_dir, ws)
    return {
        "waking": b is not None and b.complete(),
        "brief": brief_path,
        "goal": goal_path,
        "checks": len(g.checks) if g is not None else 0,
        "woke": lin.woke,
        "steps": dict(lin.steps),
    }


def _is_git_repo(p: Path) -> bool:
    r = subprocess.run(["git", "-C", str(p), "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def starter_flow(
    ask: str,
    *,
    workspace: str | Path = ".",
    run_dir: str | Path = "runs",
    new: bool = False,
    isolate: bool = False,
    clarify_only: bool = False,
    goal: bool = True,
    rounds: int = 3,
    judge_can_run: bool = False,
    max_asks: int | None = None,
    timeout_s: float | None = 1800.0,
    instructions: str = "",
    worker_prompt: str = DEFAULT_WORKER_PROMPT,
    brief_name: str = "需求.md",
    goal_name: str = "目标.md",
    log_name: str = "问答记录.md",
) -> Workflow:
    """造那个两步流程。

    ``ask`` 是**你的**原始诉求,一句话就够("帮我做个 X")。要问你什么由确认者
    自己决定 —— 它该问你领域里的哪些问题,框架不知道也不该知道。

    ``isolate=True`` 要求 ``workspace`` 是 git 仓库;不是的话抛 ``ValueError``
    (Agent 工具自己会报 "not in a git repository",但那时候钱已经花了)。

    ``timeout_s=0`` 是全自动模式:所有提问立刻落空,不假装等人。
    ``max_asks`` 默认 ``None``(不限)—— 问几次由确认者自己判断。

    ``goal=False`` 关掉目标看守:干活那一步不再被判定,跑完就算完
    (便宜、快,但"它说做完了"就真的算做完了)。
    ``rounds`` 是干活的**总轮数**上限;``judge_can_run=True`` 让判定者能跑命令。

    **唤醒**:这个工作区已经有确认书时,``ask`` 不是新任务,是**又说的一句话**。
    它会同时落到三个地方(少一个都会静默失效,见 :func:`_wake_prompt`)。
    ``ask`` 这时可以是空的 —— 什么都不说就是"接着做"。

    ``new=True`` 把上一段收进 ``notes/archive/<时间戳>/`` 再从头开始。
    """
    ask = (ask or "").strip()

    ws = Path(workspace).resolve()
    if isolate and not _is_git_repo(ws):
        raise ValueError(
            f"--isolate 要求 {ws} 是 git 仓库(每个 subagent 要分一份 worktree)。"
            "先 git init,或者去掉 --isolate。"
        )

    wb = _bench(ws, isolate).ensure()
    brief_path, goal_path = wb.notes / brief_name, wb.notes / goal_name

    if new:
        # 确认书、目标、血缘是同一段历史的三个面 —— 只收其中一部分会留下
        # "目标还在但对话没了"这种半截状态。移动而不是删除。
        Lineage.open(run_dir, ws).archive(wb.notes / "archive",
                                          extra=[brief_path, goal_path])

    # 用过的目录 + 你又说了一句话 = 唤醒,不是新任务。
    prior = Brief.load(brief_path)
    waking = prior is not None and prior.complete()
    if not waking and not ask:
        raise ValueError("要给一句诉求,例如 flower '帮我做一个 X'")

    # amend_path:人在运行途中说的话追加到确认书里。
    # 不落盘的话它活不过步骤边界 —— 下一步是新 session,只读冻结件。
    ch = HumanChannel(log_path=wb.notes / log_name,
                      amend_path=brief_path,
                      max_asks=max_asks, timeout_s=timeout_s)

    # 落地之一:追加进确认书。没有这一步,你这句话活不过步骤边界。
    # 已经在里面就不重复写(重跑同一条命令时常见)。
    said = ask if waking else ""
    amended = bool(said) and said not in brief_path.read_text(encoding="utf-8") \
        and ch.amend(said, label="唤醒时追加")

    brief_step = clarify_step(ch, brief_path=brief_path, prompt=ask,
                              instructions=instructions)
    steps = [brief_step]
    if clarify_only:
        return Workflow(name="starter", channel=ch, workbench=wb, steps=steps)

    if goal:
        # 落地之二:确认书变了就重推清单。不重推的话,判定者读的还是冻结的老目标,
        # 你新加的那件事**做没做完根本不进判定** —— 它会按老清单判通过。
        steps.append(goal_step(ch, goal_path=goal_path, brief_key=brief_step.name,
                               always_set=amended))

    # channel 给协调者 = 它能查收件箱(人主动说的话),也能中途提问。
    # 不给的话,人在干活那几小时里说什么它都收不到 —— 见 issue #3。
    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        worker_prompt, isolate=isolate),
    }, channel=ch)
    # 落地之三:接续时直接把这句话送到协调者面前。它的上下文里已经有确认书和
    # 上次干到哪了,重发全文是噪音,还会被读成"需求变了,重新看一遍"。
    work = Step("干活", spec=coord,
                prompt=lambda ctx: _work_prompt(ctx, brief_step.name),
                resume_prompt=lambda ctx: _wake_prompt(said, ctx, regoal=amended))
    if goal:
        work = with_goal(work, ch, goal_path=goal_path,
                         rounds=rounds, can_run=judge_can_run)
    steps.append(work)

    return Workflow(name="starter", channel=ch, workbench=wb, steps=steps)


def _wake_prompt(said: str, ctx: Ctx, *, regoal: bool) -> str:
    """接着上次说什么。

    空的 ``said`` = 你什么都没说,那就是"接着做"。
    ``regoal`` 时把新清单一并给它:它的上下文里是**旧**目标,不给的话它会
    照旧标准干,然后被按新标准判 —— 那是最冤的一种打回。
    """
    parts = [said or "接着做。上次干到哪就从哪接着,先说一句你打算先动什么。"]
    if regoal and (g := ctx.get(GOAL_KEY)) is not None:
        parts.append("判定标准已经按这句话重新推导过,**以这份为准**:\n\n"
                     f"{g.prompt_block()}")
    return "\n\n---\n\n".join(parts)


def _work_prompt(ctx: Ctx, brief_key: str) -> str:
    parts = [f"照这份需求做:\n\n{ctx[brief_key]}"]
    g = ctx.get(GOAL_KEY)
    if g is not None:
        # 目标和判定清单也给它 —— 让它知道会按什么标准被判,而不是事后才知道
        parts.append("做完的判定标准(会有独立的判定者逐条对):\n\n"
                     f"{g.prompt_block()}")
    return "\n\n---\n\n".join(parts)
