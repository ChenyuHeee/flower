"""向人提问 —— 长程 workflow 里唯一一处"停下来等人"的地方。

为什么需要它:这套框架清理上下文的手段(过期剪枝、拒绝剪枝、大结果落盘)清的都是
**现场**。但"目标理解错了"是唯一一类**剪枝会让它变严重**的错误 —— 现场被丢掉了,
留下来的恰恰是那条基于错误前提的决策,而且它看起来和正确决策一模一样。
长程会让它烂得更彻底:错误前提先跑几小时、派十几个 subagent、在磁盘上落一堆产出,
之后才暴露。到那时贵的不是 token,是每一个产出都是照错的需求建的。

所以要有一个能"停下来问"的通道。它的形状由三件事决定:

* **不绑 UI**。提问以 :class:`~flower.core.events.Event` (kind=``"ask"``)浮出,
  谁来答、答得快慢都无所谓 —— 3 毫秒和 3 小时对处理器是一回事。终端、Web、
  HTTP 服务只要认这一个 kind。
* **能在没人的时候活下去**。``timeout_s`` 到了就返回"无人应答",让模型自己判断并把
  假设记下来,**不是报错**。``timeout_s=0`` 就是全自动模式:所有提问立刻落空。
* **默认不限次数**(``max_asks=None``)。理由:一次提问几乎不花钱,而"需求没问清"
  是唯一一类**剪枝会让它变严重**的错误(见 ``core/brief.py``)。用固定额度去掐它,
  等于为了省一件便宜的东西去冒一件很贵的风险。问几次该由确认者自己判断 ——
  提示词里管的是"只问答案会改变做法的问题",不是"最多问 N 个"。
  ``max_asks`` 参数留着,给全自动/CI 用(``0`` = 不许提问);超了工具直接回绝,不阻塞。

  注意:真正约束不受控确认者的是**工具白名单里没有写工具**(实测过一个没有约束的:
  `/tmp/probe_ask.py`,$0.89,问完两个问题就开写代码)—— 那一条没动,额度从来不是它。

问答内容还会**追加到磁盘**(``log_path``)。这一份不占上下文、不受压缩影响、
换台机器也还在 —— 和工作台是同一个思路。
"""

from __future__ import annotations

import asyncio
import itertools
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from .events import Event

SERVER = "human"
TOOL = "ask"
TOOL_NAME = f"mcp__{SERVER}__{TOOL}"

# 完整 JSON Schema —— SDK 认出 type+properties 后原样上线(不走 name->type 那条简化路径),
# 所以 options 这种数组参数只能这么写。
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "要问人的问题。一次只问一个,写具体。",
        },
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选项。给得出来就给 —— 人选一下比打字快,答案也更好解析。",
        },
    },
    "required": ["question"],
}

OVER_BUDGET = (
    "提问额度已用完。不要再问了 —— 把剩下的不确定项写进"
    "「未知与假设」那一段,按你自己的判断继续。"
)
TIMEOUT = (
    "无人应答。按你自己的判断继续,并把这个问题和你采用的假设写进"
    "「未知与假设」那一段。不要重复提问,也不要停在这里。"
)
DECLINED = (
    "对方跳过了这个问题。按你自己的判断继续,并把假设写进「未知与假设」。"
)


@dataclass
class Ask:
    """一次提问的完整记录。UI 拿到的就是这个东西。"""

    id: str
    question: str
    options: list[str] = field(default_factory=list)
    asked_at: float = field(default_factory=time.time)
    state: str = "asked"
    """asked → answered | timeout | declined | over_budget | invalid"""
    answer: str = ""

    @property
    def waited_s(self) -> float:
        return round(time.time() - self.asked_at, 1)

    def event(self, remaining: int = 0) -> Event:
        return Event(
            "ask",
            text=self.question,
            payload={
                "id": self.id,
                "options": list(self.options),
                "state": self.state,
                "answer": self.answer,
                "remaining": remaining,
                "asked_at": self.asked_at,
            },
            raw=self,
        )


class HumanChannel:
    """一个进程内 MCP 工具 + 一组给 UI 用的方法。

    模型侧只看见一个工具 ``mcp__human__ask``。UI 侧有两种取法,选一种:

    * **推**:构造时给 ``on_event``,提问以 ``Event("ask")`` 推过来
      (:class:`~flower.workflow.base.Workflow` 会自动把它接到 workflow 的
      ``on_event`` 上,不用自己接)
    * **拉**:``await channel.next_ask()``,适合独立的输入任务(见 ``cli.py``)

    答的时候调 :meth:`answer` / :meth:`decline`。**可以从别的线程调** ——
    Web 后端、TUI 的输入线程都在别的线程里,这是常态,不是边缘情况。
    """

    def __init__(
        self,
        *,
        on_event: Callable[[Event], None] | None = None,
        max_asks: int | None = None,
        timeout_s: float | None = 1800.0,
        log_path: str | Path | None = None,
        over_budget_text: str = OVER_BUDGET,
        timeout_text: str = TIMEOUT,
        declined_text: str = DECLINED,
    ) -> None:
        self.on_event = on_event
        self.max_asks = max_asks
        """最多放行几次提问。**默认 ``None`` = 不限** —— 问几次由 agent 自己判断。
        给个数字就是硬额度(``0`` = 不许提问,配合全自动)。超了工具直接回绝,不阻塞。"""
        self.timeout_s = timeout_s
        """等多久。``None`` = 永远等;``0`` = 不等(全自动模式,所有提问立刻落空)。"""
        self.log_path = Path(log_path).resolve() if log_path else None
        self.over_budget_text = over_budget_text
        self.timeout_text = timeout_text
        self.declined_text = declined_text

        self.asks: list[Ask] = []
        """全部提问记录,含被回绝和超时的。"""
        self.ui_errors: list[str] = []
        """UI 回调抛出的异常。**不让它中断运行** —— 前端崩了不该带走三小时的活。"""

        self._waiting: dict[str, tuple[Ask, asyncio.Future]] = {}
        self._queue: asyncio.Queue[Ask] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._tool = tool(
            TOOL,
            "向人类提问并等待回答。一次问一个。答案作为工具结果返回。"
            "对方可能不在 —— 那时会返回一句说明,自己判断着继续,别卡住。",
            _SCHEMA,
        )(self._handle)

    # ---- 装配 -------------------------------------------------------
    @property
    def tool_name(self) -> str:
        return TOOL_NAME

    def mcp_servers(self) -> dict[str, Any]:
        """交给 ``AgentSpec.mcp_servers``。

        键名必须和 :func:`create_sdk_mcp_server` 的名字一致,否则工具名对不上 ——
        所以这里一起给出,不留给调用方拼。
        """
        return {SERVER: create_sdk_mcp_server(SERVER, tools=[self._tool])}

    # ---- 提问(模型侧和框架侧共用同一条路)-----------------------------
    async def ask(self, question: str, options: list[str] | None = None) -> Ask:
        """问一个问题,挂住等人,返回那个 :class:`Ask`(含 ``state`` 和 ``answer``)。

        **模型侧的 MCP 工具和框架自己都走这一条路。** 为什么要框架也能问:
        目标被判为"无法达成"时,得停下来问人是接受、改目标、还是"你判断错了"——
        那是**框架**的决策点,不是某个 agent 的。走同一条路,于是日志、事件、
        额度、超时、跨线程回答这些行为完全一致,UI 也不用为它另认一种事件。

        永远不抛异常给调用方(除了 ``CancelledError``)—— 没人应答就是一种答案。
        用 ``ask.state`` 区分:``answered`` / ``timeout`` / ``declined`` /
        ``over_budget`` / ``invalid``。
        """
        self._loop = asyncio.get_running_loop()
        question = str(question or "").strip()
        opts = [str(o).strip() for o in (options or []) if str(o).strip()]

        a = Ask(id=f"q{next(self._ids)}", question=question, options=opts)
        self.asks.append(a)

        if not question:
            return self._settle_ask(a, "问题是空的。把问题写清楚再问。", "invalid")
        if self.max_asks is not None and len(self.asks) > self.max_asks:
            return self._settle_ask(a, self.over_budget_text, "over_budget")
        if self.timeout_s is not None and self.timeout_s <= 0:
            # 全自动模式:没人看着,不必假装等。
            return self._settle_ask(a, self.timeout_text, "timeout")

        fut: asyncio.Future = self._loop.create_future()
        with self._lock:
            self._waiting[a.id] = (a, fut)
        self._emit(a)
        self._queue.put_nowait(a)

        try:
            answer = await asyncio.wait_for(fut, self.timeout_s)
        except (asyncio.TimeoutError, TimeoutError):
            with self._lock:
                self._waiting.pop(a.id, None)
            return self._settle_ask(a, self.timeout_text, "timeout")
        except asyncio.CancelledError:
            with self._lock:
                self._waiting.pop(a.id, None)
            raise
        return self._settle_ask(a, answer, a.state or "answered")

    async def _handle(self, args: dict[str, Any]) -> dict[str, Any]:
        """MCP 工具处理器。**它会挂住等人**,这是有意的。

        实测过不会死锁:处理器 ``await`` 的时候事件循环照转,
        另一个任务(或**另一个线程**)照样能把答案填进来。
        """
        a = await self.ask(str(args.get("question") or ""), args.get("options") or [])
        return {"content": [{"type": "text", "text": a.answer or ""}]}

    def _settle_ask(self, ask: Ask, text: str, state: str) -> Ask:
        ask.state, ask.answer = state, text
        self._emit(ask)
        self._log(ask)
        return ask

    # ---- UI 侧 ------------------------------------------------------
    @property
    def remaining(self) -> int:
        """还能问几次。``max_asks=None`` 时返回 -1。"""
        return -1 if self.max_asks is None else max(0, self.max_asks - len(self.asks))

    def pending(self) -> list[Ask]:
        with self._lock:
            return [a for a, _ in self._waiting.values()]

    async def next_ask(self, timeout: float | None = None) -> Ask | None:
        """等下一个待答提问。超时返回 ``None``;被取消则抛出。

        给"拉"式 UI 用:一个独立任务循环调它,不必自己管回调。
        """
        try:
            if timeout is None:
                return await self._queue.get()
            return await asyncio.wait_for(self._queue.get(), timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return None
        # CancelledError 不接:吞掉它的话调用方的循环停不下来。

    def answer(self, ask_id: str, text: str) -> bool:
        """回答。返回 ``False`` 表示这个提问已经不在等了(超时/已答)。"""
        return self._settle(ask_id, str(text), "answered")

    def decline(self, ask_id: str, reason: str = "") -> bool:
        """跳过这个问题,让模型自己判断。"""
        return self._settle(
            ask_id, f"{self.declined_text}{f'(对方说:{reason})' if reason else ''}", "declined"
        )

    def _settle(self, ask_id: str, text: str, state: str) -> bool:
        with self._lock:
            item = self._waiting.pop(ask_id, None)
        if item is None:
            return False
        ask, fut = item
        ask.state = state
        loop = self._loop
        if loop is None or fut.done():
            return False
        # 可能来自别的线程(Web 后端 / TUI 输入线程)—— set_result 不是线程安全的,
        # 必须走 call_soon_threadsafe。从循环自己的线程调它也是合法的。
        loop.call_soon_threadsafe(lambda: None if fut.done() else fut.set_result(text))
        return True

    # ---- 落盘与广播 -------------------------------------------------
    def _emit(self, ask: Ask) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(ask.event(self.remaining))
        except Exception as exc:  # noqa: BLE001 - 前端崩了不该带走这次运行
            self.ui_errors.append(f"{type(exc).__name__}: {exc}")

    def _log(self, ask: Ask) -> None:
        """问答追加到磁盘。不占上下文、压缩清不掉、换机器还在。"""
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.log_path.exists()
        with self.log_path.open("a", encoding="utf-8") as f:
            if new:
                f.write("# 需求问答记录\n\n> 自动追加。这一份不进上下文,只作留档。\n\n")
            f.write(f"- **Q**({ask.id}) {ask.question}\n")
            if ask.options:
                f.write(f"  - 选项:{' / '.join(ask.options)}\n")
            f.write(f"  - **A**[{ask.state}] {ask.answer}\n")

    def transcript(self) -> str:
        """问答记录的 markdown。想把它并进需求确认书时用。"""
        lines = []
        for a in self.asks:
            lines.append(f"- Q: {a.question}")
            lines.append(f"  A: [{a.state}] {a.answer}")
        return "\n".join(lines)
