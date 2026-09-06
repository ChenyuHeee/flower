"""目标看守 —— 设目标,然后每一轮判定"做完了没有"。

接在前置确认(:mod:`~flower.workflow.clarify`)后面,补的是另一类失败:

    确认需求  挡"做的不是想要的东西"
    目标看守  挡"其实没做完,但它自己说做完了"

第二类为什么需要独立角色:**干活的人有系统性的乐观偏差**。它跑了一半的测试、
改了一处漏了三处、用"应该没问题"收尾 —— 这不是它不老实,是它看不见自己的盲区。
判定必须由一个**没参与干活、跑在自己 session 里**的角色下,理由和确认者一样
(见 :mod:`~flower.core.roles` 的 ``judge``)。

两个东西:

``goal_step()``
    一个步骤:读确认书 → 输出「目标 + 可判定清单」→ 冻结到磁盘。
    和 ``clarify_step`` 同一个形状(when 跳过 / gate 冻结 / reduce 只传解析结果)。

``with_goal()``
    包住干活那一步,把它变成一个**带判定的循环**:

        干活 → 判定 ─达成─→ 往下走
                 └─未达成─→ 打回,带上"差在哪",**续跑同一个 session 接着做**
                 └─无法达成─→ 停下来问人:接受 / 改目标 / 你判断错了

"打回"用的是 ``Step.on_reject``:下一轮 ``resume`` 刚被否掉的那个 session,
所以已经干完的活和上下文都在,不是从零重来。

**为什么轮数是有上限的**(``rounds``,默认 3),而提问次数没有上限:
提问几乎不花钱,而一轮活是真金白银。不设上限,一个判不过的目标会让主 agent
一轮一轮空转到额度见底。真正的兜底是第三个结论「无法达成」——
它一出现就停下来问人,不再靠轮数耗完。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.agent import AgentSpec
from ..core.goal import Goal, Verdict
from ..core.human import HumanChannel
from ..core.roles import judge
from ..core.runtime import StepResult
from .base import Ctx, Step, StepAbort

GOAL_KEY = "_goal"
"""``ctx[GOAL_KEY]`` 是 :class:`~flower.core.goal.Goal` 对象。
``ctx[step.name]`` 是它的 markdown(可直接插进下游 prompt)。"""

VERDICT_KEY = "_verdict"
"""``ctx[VERDICT_KEY]`` 是最近一次 :class:`~flower.core.goal.Verdict`。给 UI 用。"""

ROUND_KEY = "_goal_rounds"
"""跑了几轮。给 UI 和事后分析用。"""

SET_PROMPT = """\
把下面这份需求确认书变成可判定的目标。照「设定目标」那一节的格式输出。

{brief}
"""

VERIFY_PROMPT = """\
判定这一轮做完了没有。照「判定这一轮」那一节的格式输出。

# 目标
{goal}

# 干活的人这一轮的回话
{report}

自己去看现场(Read/Glob/Grep),逐条对判定清单。不要只凭上面那段回话 ——
它可能漏报也可能乐观。看不到证据的判定项,就是没通过。
"""

UNREACHABLE_Q = "目标被判为**无法达成**:{reason}\n怎么办?"
_ACCEPT, _AMEND, _MISJUDGED = "接受这个结果,就这样往下走", "修改目标", "你判断错了,继续做"
AMEND_Q = "新的目标是什么?(一句话,会追加到原目标后面)"

NO_ONE = ("目标被判为无法达成,而且无人应答 —— 已停下。"
          "理由:{reason}\n看 {path} 和 runs/manifest.json,人来决定下一步。")


def goal_step(
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    brief_key: str = "确认需求",
    name: str = "设定目标",
    spec: AgentSpec | None = None,
    instructions: str = "",
    always_set: bool = False,
    on_fail: str = "stop",
    retries: int = 0,
    **spec_kw: Any,
) -> Step:
    """造"把确认书变成可判定目标"那一步。

    ``always_set=True`` 每次重设。默认:目标文件已存在且齐全就跳过 ——
    和确认书同一个道理,长程跑崩了重启不该把前面的结论再算一遍。
    """
    path = Path(goal_path)
    agent = spec or judge(name, channel, instructions=instructions, **spec_kw)

    def hydrate(ctx: Ctx, g: Goal) -> None:
        ctx[GOAL_KEY] = g
        ctx[name] = g.prompt_block()

    def when(ctx: Ctx) -> bool:
        if always_set:
            return True
        g = Goal.load(path)
        if g is not None and g.complete():
            hydrate(ctx, g)      # 跳过也要灌进 ctx,否则下游拿不到
            return False
        return True

    def gate(result: StepResult, ctx: Ctx) -> bool:
        g = Goal.parse(result.text or "")
        if not g.complete():
            return False
        g.write(path)            # 冻结:从这里往后,目标以文件为准
        hydrate(ctx, g)
        return True

    def reduce(result: StepResult, ctx: Ctx) -> str:
        g = ctx.get(GOAL_KEY)
        return g.prompt_block() if isinstance(g, Goal) else (result.text or "")

    def prompt(ctx: Ctx) -> str:
        return SET_PROMPT.format(brief=ctx.get(brief_key, "(没有确认书)"))

    return Step(name=name, spec=agent, prompt=prompt,
                when=when, gate=gate, reduce=reduce, on_fail=on_fail, retries=retries)


def with_goal(
    step: Step,
    channel: HumanChannel,
    *,
    goal_path: str | Path,
    spec: AgentSpec | None = None,
    rounds: int = 3,
    instructions: str = "",
    can_run: bool = False,
    name: str | None = None,
    **spec_kw: Any,
) -> Step:
    """把一个干活的步骤包成"带目标判定的循环"。

    每一轮结束后由判定者(独立 session)判一次:达成就往下走;未达成就打回去
    接着做;无法达成就停下来问人。

    ``rounds`` 是**总轮数**(不是额外轮数):``rounds=3`` 最多跑三轮活。
    ``can_run=True`` 让判定者能跑命令(判定更硬,但它就能改动工作区了)。
    """
    path = Path(goal_path)
    label = name or f"{step.name}·判定"
    judger = spec or judge(label, channel, instructions=instructions,
                           can_run=can_run, **spec_kw)

    def goal_of(ctx: Ctx) -> Goal:
        g = ctx.get(GOAL_KEY)
        if isinstance(g, Goal) and g.complete():
            return g
        return Goal.load(path) or Goal()

    async def gate(result: StepResult, ctx: Ctx) -> bool:
        rt, on_event = ctx.get("_runtime"), ctx.get("_on_event")
        if rt is None:                    # 没有运行时就没法判定 —— 别假装通过
            raise StepAbort("拿不到 Runtime,无法判定目标(ctx['_runtime'] 缺失)")
        ctx[ROUND_KEY] = ctx.get(ROUND_KEY, 0) + 1
        g = goal_of(ctx)

        vr = await rt.run(
            judger,
            VERIFY_PROMPT.format(goal=g.prompt_block() or "(没有目标)",
                                 report=result.text or "(这一轮没有回话)"),
            step_name=f"{label}#{ctx[ROUND_KEY]}",
            on_event=on_event,            # 判定过程也要打到 UI 上,否则界面全黑
        )
        v = Verdict.parse(vr.text or "")
        ctx[VERDICT_KEY] = v

        if v.achieved:
            return True
        if not v.unreachable:
            # 未达成,或者判定者话说得含糊(v.ok 为 False)。
            # **含糊一律按未达成** —— 不能让一句"看起来可以"把活收掉。
            if not v.ok:
                v.reason = (v.reason or "").strip() or "判定者没给出明确结论,按未达成处理"
            return False

        # 无法达成:这是框架的决策点,不是哪个 agent 的 —— 停下来问人。
        a = await channel.ask(UNREACHABLE_Q.format(reason=v.reason or "(没给理由)"),
                              [_ACCEPT, _AMEND, _MISJUDGED])
        if a.state != "answered":
            # 没人在。继续空转是最贵的选择,所以停 —— 理由已经落在目标文件旁边。
            raise StepAbort(NO_ONE.format(reason=v.reason or "(没给理由)", path=path))

        answer = (a.answer or "").strip()
        if answer.startswith(_ACCEPT[:4]) or answer == _ACCEPT:
            return True                                   # 人接受了,往下走
        if answer.startswith(_AMEND[:2]) or answer == _AMEND:
            b = await channel.ask(AMEND_Q)
            if b.state == "answered" and (b.answer or "").strip():
                g.amend(b.answer).write(path)
                ctx[GOAL_KEY] = g
                v.reason = f"目标已被人修改。新目标:\n{g.prompt_block()}"
            return False                                  # 带着新目标再来一轮
        # 剩下的都当"你判断错了,继续做"(包括人自己打的自由回答)
        v.reason = f"人认为这个目标是能达成的,判定者判断有误。人的说法:{answer}"
        return False

    def on_reject(result: StepResult, ctx: Ctx) -> str:
        v = ctx.get(VERDICT_KEY)
        return v.feedback() if isinstance(v, Verdict) else ""

    return Step(
        name=step.name, spec=step.spec, prompt=step.prompt,
        resume_from=step.resume_from, fork=step.fork,
        retries=max(0, rounds - 1),        # rounds 是总轮数,retries 是额外轮数
        gate=gate, on_fail=step.on_fail, when=step.when,
        on_reject=on_reject, reduce=step.reduce,
    )
