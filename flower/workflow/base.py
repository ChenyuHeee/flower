"""Workflow 抽象 —— 这是留给你设计的那一层。

框架只规定"一步怎么跑、步与步之间怎么接",不规定你的领域逻辑。
设计一个 workflow 就是写一串 Step:

    Workflow([
        Step("调研", spec=researcher, prompt="…"),
        Step("方案", spec=architect, prompt=lambda ctx: f"基于:\\n{ctx['调研']}"),
        Step("实现", spec=coder,     prompt="…", resume_from="方案"),
        Step("复核", spec=reviewer,  prompt="…", resume_from="实现", fork=True),
    ])

三种接法(**同一次运行内**,步与步之间):
  resume_from=None          新会话,只靠 prompt 里传入的上下文(便宜、隔离)
  resume_from="上一步"       续跑同一会话,完整上下文(贵、连贯)
  resume_from=… fork=True   分叉,不污染原会话(用于复核/多方案并行)

**跨进程**是另一个轴,由 ``continuous``(默认开)管:同一个工作区再跑一次,
每一步接着上次那个 session 说 —— 用户不需要知道 session 这个词,
也不需要记住任何 id。见 :mod:`~flower.core.lineage`。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.agent import AgentSpec
from ..core.events import Event
from ..core.lineage import Lineage
from ..core.runtime import Runtime, StepResult

Ctx = dict[str, Any]


class StepAbort(Exception):
    """``gate`` 抛它 = **立刻停,不要再重试**。

    和"返回 False"的区别:False 是"这次不行,再来一轮";``StepAbort`` 是
    "再来也没用"。典型场合是目标被判为**无法达成**而且没人可问 ——
    这时候继续重试就是一轮一轮空转烧钱,而那正是最该避免的事。

    抛出后本步按失败处理,并走 ``on_fail``(默认 ``stop``)。原因记在
    ``ctx["_aborted"]`` 里给 UI 用。
    """


def _lineage_for(runtime: Runtime) -> Lineage | None:
    """给这个运行时开血缘 —— **它得有个磁盘位置**。

    真的 :class:`~flower.core.runtime.Runtime` 一定有 ``run_dir`` 和 ``workspace``。
    没有的(测试里的假运行时、别人自己实现的驱动)就不接血缘:接续是锦上添花,
    缺了它照样能跑,而硬要求这两个属性会把 Workflow 和某一个运行时实现焊死。
    """
    rd, ws = getattr(runtime, "run_dir", None), getattr(runtime, "workspace", None)
    return Lineage.open(rd, ws) if rd and ws else None


async def _settle(value: Any) -> Any:
    """gate / when / on_reject 可以是同步的,也可以是 async 的。

    async 是为了让它们能**调 agent** —— 目标判定就是一个 agent 的活
    (见 :mod:`~flower.workflow.goal`)。同步回调照旧,不用改。
    """
    return await value if inspect.isawaitable(value) else value


@dataclass
class Step:
    name: str
    spec: AgentSpec
    prompt: str | Callable[[Ctx], str]

    # —— 会话血缘 ——
    resume_from: str | None = None
    fork: bool = False

    # —— 长程控制 ——
    retries: int = 0
    gate: Callable[[StepResult, Ctx], bool] | None = None   # 返回 False 则视为失败
    on_fail: str = "stop"                                    # stop | skip | continue
    when: Callable[[Ctx], bool] | None = None                # 返回 False 则跳过本步
    on_reject: Callable[[StepResult, Ctx], str] | None = None
    """``gate`` 没通过时,**下一轮说什么**。给了它,重试的语义就变了:

    * 不给(默认):下一次尝试**重头跑** —— 同样的 prompt、同样的 ``resume_from``。
      适合"这次失败是偶然"的情况。
    * 给了:下一次尝试**续跑刚被否掉的那个 session**,prompt 换成它的返回值。
      也就是"打回去、带上差在哪、让它接着做" —— 上下文和已经干完的活都还在,
      不是从零重来。目标未达成时要的是这个。

    返回空字符串 = 不打回(退化成重头跑)。可以是 async。
    """
    resume_prompt: str | Callable[[Ctx], str] | None = None
    """**接上次**的时候说什么(``prompt`` 说的是"从头开始"的时候说什么)。

    为什么要分开:接续时对方的上下文里**已经有**确认书、目标、上次干到哪了。
    再把 "照这份需求做:<整份确认书>" 原样发一遍是纯噪音,更糟的是它会读成
    "需求变了,重新看一遍" —— 实际什么都没变。

    不给就沿用 ``prompt``。有些步骤本来就该重发全文(设定目标要重新推导清单时,
    它要的正是那份完整确认书),那就别给。
    """

    reduce: Callable[[StepResult, Ctx], str] | None = None
    """决定 ``ctx[step.name]`` 里放什么。默认放 ``result.text`` 原文。

    有些步骤的原文**不该**原样往下传 —— 确认需求那一步就是:模型可能在四段之外
    多写一堆东西(实测它会贴整份代码),往下游传的必须是解析后的四段。
    见 :func:`~flower.workflow.clarify.clarify_step`。
    """

    def render(self, ctx: Ctx, *, resuming: bool = False) -> str:
        p = self.resume_prompt if (resuming and self.resume_prompt) else self.prompt
        return p(ctx) if callable(p) else p


@dataclass
class Workflow:
    steps: list[Step]
    name: str = "workflow"
    context: Ctx = field(default_factory=dict)
    channel: Any = None
    """:class:`~flower.core.human.HumanChannel` —— 需要停下来问人时挂在这里。

    放在 workflow 上而不是让 UI 自己去找,是为了两件事:
      * :meth:`run` 会自动把它的 ``on_event`` 接到同一个事件出口 ——
        UI 只需要认 ``Event("ask")``,不必额外接线
      * 驱动程序(``cli.py``)能找到它,从而知道该向谁回答
    """

    workbench: Any = None
    """:class:`~flower.core.workbench.Workbench` —— 由 workflow 指定的工作台。

    和 ``channel`` 同一个道理:**驱动程序能找到它**。``cli.py`` 发现这个字段后
    会把它交给 :class:`~flower.core.runtime.Runtime`,而不是自己按 ``-W`` 造一个。

    为什么必须这样,而不是让 workflow 自己拼一个路径:``brief_path`` /
    ``log_path`` 这类文件**必须落在真正被注入索引的那个工作台里** ——
    索引进的是**主 agent** 的 system prompt(subagent 继承不到,见
    `tests/prelude_live.py`),协调者据此知道
    需求文件在哪。而 ``Runtime(workbench=True)`` 的默认位置是 ``<run_dir>/workbench``,
    workflow 在被 CLI 调用时**看不到** ``run_dir``,自己拼只会拼到别处去:
    确认书写在 A 目录,注入的索引扫的是 B 目录,那条承诺就静默失效了。
    让 workflow 建好工作台再交出去,两边用的就是同一个对象。

    ``None`` = 沿用驱动程序自己的选择(``cli.py`` 的 ``-W``)。
    """

    continuous: bool = True
    """**同一个路径 = 同一段对话。** 在同一个工作区再跑一次,每个步骤接着上次
    那个 session 说,而不是从零开会话 —— 哪怕上次是被 kill 掉的。

    实现是 :class:`~flower.core.lineage.Lineage`:步骤名 → session_id 落在
    ``<run_dir>/lineage.json``,每步跑完立刻写。步骤名是跨进程稳定的键,
    这是整件事成立的前提。

    ``False`` = 老行为,每次进程都是全新会话。
    """

    async def run(
        self,
        runtime: Runtime,
        *,
        on_event: Callable[[Event], None] | None = None,
        on_step: Callable[[Step, StepResult], None] | None = None,
    ) -> Ctx:
        ctx = self.context
        # gate/when/on_reject 里可能要派 agent(目标判定就是),它们只拿到 ctx ——
        # 所以运行时和事件出口都从这里给。和 _sessions / _results 一样是私有键。
        # on_event 尤其重要:gate 里那个 agent 也要能把过程打到 UI 上,
        # 否则判定的那十几秒界面全黑,看起来就像卡住了。
        ctx["_runtime"] = runtime
        ctx["_on_event"] = on_event
        if self.channel is not None and on_event is not None and self.channel.on_event is None:
            # 提问和别的事件走同一个出口。UI 不用为"要人回答"另接一条线。
            self.channel.on_event = on_event
        # step name → session_id。取 ctx 里那一份:同一个 Workflow 对象跑第二次时
        # ctx 是同一个 dict,各持一份的话 ctx["_sessions"] 会停在上一次的值。
        sessions: dict[str, str] = ctx.setdefault("_sessions", {})
        ctx.setdefault("_results", {})

        # 上一次(或者更早)留在磁盘上的血缘。**逐个验证 session 还在库里** ——
        # 血缘文件可能比 sessions.db 活得久(删过库、换过机器),而 resume 一个
        # 不存在的 session 要等子进程起来才炸,那时候钱和时间都花了。
        lin = _lineage_for(runtime) if self.continuous else None
        if lin is not None:
            ctx["_lineage"] = lin
            ctx["_woke"] = lin.bump()
            alive = getattr(runtime, "has_session", None)
            for name, sid in lin.steps.items():
                if alive is None or alive(sid):
                    sessions.setdefault(name, sid)

        for i, step in enumerate(self.steps, 1):
            if step.when and not await _settle(step.when(ctx)):
                continue

            if step.resume_from:
                # 本次运行内的血缘:显式声明"接着哪一步说"。语义一字未变。
                resume = sessions.get(step.resume_from)
                if resume is None:
                    raise ValueError(
                        f"步骤 {step.name!r} 要求 resume_from={step.resume_from!r},"
                        " 但那一步没有产生 session(未运行或已失败)"
                    )
                carried = False
            else:
                # 跨进程的血缘:同一个目录、同一步 —— 接着上次那段对话。
                # sessions[step.name] 是**步骤跑完才写**的(见下面),
                # 所以本次运行内不会自己 resume 自己,不需要额外的标记位。
                resume = sessions.get(step.name)
                carried = resume is not None

            if on_event:
                # 步骤边界是这次运行的骨架。UI 靠它分段 —— 否则几小时的输出
                # 是一条看不出结构的流。carried 让人看得见"它记不记得"。
                on_event(Event("step", text=step.name, payload={
                    "index": i, "total": len(self.steps),
                    "resumed": carried, "woke": ctx.get("_woke", 1)}))

            result, passed = None, False
            # 这三个会随"打回"而变,所以是局部变量 —— **不要写回 step**,
            # 同一个 Step 对象可能被跑第二次。
            prompt_cur, resume_cur, fork_cur = (
                step.render(ctx, resuming=carried), resume, step.fork)
            for attempt in range(step.retries + 1):
                if attempt == 0:
                    label = step.name
                else:
                    # 打回重来是"接着做"(round),普通重试是"再试一次"(retry)。
                    # 名字不同,manifest 里一眼能看出这一步是怎么走完的。
                    label = (f"{step.name}#round{attempt + 1}" if step.on_reject
                             else f"{step.name}#retry{attempt}")
                result = await runtime.run(
                    step.spec,
                    prompt_cur,
                    step_name=label,
                    resume=resume_cur,
                    fork=fork_cur,
                    on_event=on_event,
                )
                # gate 每次尝试只调一次,并把结论留到后面用 ——
                # 它可能有副作用(比如把需求确认书落盘),不该被重复触发。
                try:
                    passed = result.ok and (
                        step.gate is None or await _settle(step.gate(result, ctx)))
                except StepAbort as exc:
                    # "再试也没用" —— 不消耗剩余的 retries
                    ctx["_aborted"] = str(exc)
                    passed = False
                    break
                if passed:
                    break
                # 打回:续跑刚被否掉的那个 session,带上"差在哪"。
                # 没有 session_id(整轮都没跑起来)就退化成重头跑。
                if step.on_reject is not None and result.session_id:
                    nxt = await _settle(step.on_reject(result, ctx))
                    if nxt:
                        prompt_cur, resume_cur, fork_cur = nxt, result.session_id, False

            assert result is not None
            ctx["_results"][step.name] = result
            if on_step:
                on_step(step, result)

            if result.session_id:
                sessions[step.name] = result.session_id
                if lin is not None:
                    # **立刻**写盘,不是等跑完 —— 进程被 kill 正是要防的场景。
                    lin.remember(step.name, result.session_id)

            if passed:
                ctx[step.name] = step.reduce(result, ctx) if step.reduce else result.text
                continue

            if step.on_fail == "stop":
                ctx["_failed_at"] = step.name
                break
            if step.on_fail == "skip":
                continue
            ctx[step.name] = result.text   # continue: 带着残缺结果往下走

        return ctx
