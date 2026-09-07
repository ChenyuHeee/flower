"""前置确认 —— 一行接上 workflow 的第一步。

它把三件事接在一起,一个新字段都不用加:

    Step.when    确认书已经在了就**跳过**,顺手把它灌进 ctx
                 —— 长程重启不重新盘问人,这一条比看起来重要
    Step.gate    四段没写全就**不许往下走**,并把它落盘冻结
    Step.reduce  往下游传的是**解析后的四段**,不是模型原文
                 —— 原文里可能夹着它多写的东西(实测会贴整份代码)

再加上 ``resume_from=None``(默认):下一步是**新会话**,只拿到确认书,
拿不到那段问答。这就是"问答是现场,不是决策"落地的地方 ——
澄清对话从来没进过协调者的上下文,不是进去之后被剪掉的。

    ch = HumanChannel(log_path=wb.notes / "问答记录.md")
    wf = Workflow(channel=ch, steps=[
        clarify_step(ch, brief_path=wb.notes / "需求.md", prompt="帮我做一个 X"),
        Step("干活", spec=coord, prompt=lambda ctx: f"照这份需求做:\\n{ctx['确认需求']}"),
    ])

把 ``brief_path`` 放进 :attr:`~flower.core.workbench.Workbench.notes`
是推荐做法:工作台索引会自动注入**主 agent** 的 system prompt,
于是协调者开局就知道需求文件在哪,派活时把路径给下去即可。

(索引**不会**到 subagent —— 它有自己的 system prompt,继承不到 session 级的
append。实测见 `tests/prelude_live.py`。所以是"协调者转述路径",
不是"每个 subagent 自动知道"。)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..core.agent import AgentSpec
from ..core.brief import Brief
from ..core.human import HumanChannel
from ..core.roles import clarify
from ..core.runtime import StepResult
from .base import Ctx, Step

BRIEF_KEY = "_brief"
"""``ctx[BRIEF_KEY]`` 是 :class:`~flower.core.brief.Brief` 对象。
``ctx[step.name]`` 是它的 markdown(可以直接插进下游 prompt)。"""

MISSING_KEY = "_brief_missing"

CLARIFY_RESUME = """\
接着刚才那次没问完的需求确认继续 —— **不是重新开始**。

你这个会话里已经问过的、人已经答过的,都还在上文里,别再问一遍。看一下还差什么:
四段(目标 / 验收标准 / 边界 / 未知与假设)哪几段还没敲定,就只补那几段。
问清楚了就直接把完整的四段确认书交出来。

(上一次是被中途打断的 —— 可能是进程被杀、终端崩了。不用管为什么,接着做就行。)
"""
"""确认途中崩了、再接续时对确认者说的话。见 issue #6 第 2 条:
不给这句,接续会把原始诉求当新任务重发,确认者可能把已问过的重问一遍。"""
"""确认失败时,缺哪几段。给 UI 显示用。"""


def clarify_step(
    channel: HumanChannel,
    *,
    brief_path: str | Path,
    prompt: str | Callable[[Ctx], str],
    name: str = "确认需求",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_ask: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw,
) -> Step:
    """造一个"先把需求问清楚"的步骤。

    ``prompt`` 是**你的**原始诉求 —— 一句话就够("帮我做个 X")。要问什么
    由确认者自己决定;它该问你领域里的哪些问题,框架不知道也不该知道。

    ``always_ask=True`` 每次都重新确认(改需求时用)。默认是:确认书已存在
    且四段齐全就跳过 —— 一次长程运行崩了重跑,不该再问你一遍。
    """
    path = Path(brief_path)
    agent = spec or clarify(name, channel, instructions=instructions, **spec_kw)

    def hydrate(ctx: Ctx, b: Brief) -> None:
        ctx[BRIEF_KEY] = b
        ctx[name] = b.prompt_block()
        ctx.pop(MISSING_KEY, None)

    def when(ctx: Ctx) -> bool:
        if always_ask:
            return True
        b = Brief.load(path)
        if b is not None and b.complete():
            hydrate(ctx, b)      # 跳过也要把需求灌进 ctx,否则下游拿不到
            return False
        return True

    def gate(result: StepResult, ctx: Ctx) -> bool:
        b = Brief.parse(result.text or "")
        if not b.complete():
            ctx[MISSING_KEY] = b.missing()
            return False
        b.write(path)            # 冻结:从这里往后,需求以文件为准
        hydrate(ctx, b)
        return True

    def reduce(result: StepResult, ctx: Ctx) -> str:
        b = ctx.get(BRIEF_KEY)
        return b.prompt_block() if isinstance(b, Brief) else (result.text or "")

    return Step(
        name=name,
        spec=agent,
        prompt=prompt,
        resume_prompt=CLARIFY_RESUME,   # 崩在确认途中再接续,别把原始诉求当新任务重发
        when=when,
        gate=gate,
        reduce=reduce,
        on_fail=on_fail,
        retries=retries,
    )
