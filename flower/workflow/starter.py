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
    索引会注入每个 agent 的 system prompt,后面每个 subagent 开局就知道需求文件在哪。
    自己拼路径会拼到别处,而且不报错。见 `docs/workflow.md`。
  * **开隔离时工作台移到仓库外** —— worktree 是每个 agent 的私有副本,
    工作台是跨 agent 的共享层,共享的东西不能放进私有围栏里。
  * **提问通道同时挂在 channel 上**,驱动程序才知道该向谁回答。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..core.human import HumanChannel
from ..core.roles import coordinator, worker
from ..core.workbench import Workbench
from .base import Ctx, Step, Workflow
from .clarify import clarify_step
from .goal import GOAL_KEY, goal_step, with_goal

DEFAULT_WORKER_PROMPT = "你负责实现。每改一处就跑一次验证,别攒到最后。"


def _is_git_repo(p: Path) -> bool:
    r = subprocess.run(["git", "-C", str(p), "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def starter_flow(
    ask: str,
    *,
    workspace: str | Path = ".",
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
    """
    ask = (ask or "").strip()
    if not ask:
        raise ValueError("要给一句诉求,例如 flower '帮我做一个 X'")

    ws = Path(workspace).resolve()
    if isolate and not _is_git_repo(ws):
        raise ValueError(
            f"--isolate 要求 {ws} 是 git 仓库(每个 subagent 要分一份 worktree)。"
            "先 git init,或者去掉 --isolate。"
        )

    # 开隔离时工作台必须在仓库外,否则被隔离的 agent 写不进来(围栏会挡)。
    # 放外面时 Runtime 会自动 add_dirs 授权。
    home = (ws.parent / f".flower-{ws.name}") if isolate else None
    wb = Workbench(ws, home=home).ensure()

    ch = HumanChannel(log_path=wb.notes / log_name,
                      max_asks=max_asks, timeout_s=timeout_s)

    brief_step = clarify_step(ch, brief_path=wb.notes / brief_name, prompt=ask,
                              instructions=instructions)
    steps = [brief_step]
    if clarify_only:
        return Workflow(name="starter", channel=ch, workbench=wb, steps=steps)

    goal_path = wb.notes / goal_name
    if goal:
        steps.append(goal_step(ch, goal_path=goal_path, brief_key=brief_step.name))

    coord = coordinator("协调者", "", {
        "coder": worker("写代码与测试。要动手实现的活派给它。",
                        worker_prompt, isolate=isolate),
    })
    work = Step("干活", spec=coord,
                prompt=lambda ctx: _work_prompt(ctx, brief_step.name))
    if goal:
        work = with_goal(work, ch, goal_path=goal_path,
                         rounds=rounds, can_run=judge_can_run)
    steps.append(work)

    return Workflow(name="starter", channel=ch, workbench=wb, steps=steps)


def _work_prompt(ctx: Ctx, brief_key: str) -> str:
    parts = [f"照这份需求做:\n\n{ctx[brief_key]}"]
    g = ctx.get(GOAL_KEY)
    if g is not None:
        # 目标和判定清单也给它 —— 让它知道会按什么标准被判,而不是事后才知道
        parts.append("做完的判定标准(会有独立的判定者逐条对):\n\n"
                     f"{g.prompt_block()}")
    return "\n\n---\n\n".join(parts)
