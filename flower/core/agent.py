"""Agent 构建 —— 框架层的核心决策都固化在这里。

三条设计原则:

1. **叠加,不替换**。system_prompt 用 preset "claude_code" + append。
   大多数专项 agent 之所以比 Claude Code 弱,是因为它们把系统提示整个换掉了,
   于是连带丢掉了工具使用纪律、错误恢复、上下文管理这些被训练过的行为。
   这里只在其后追加领域知识。

2. **可移植**。setting_sources=[] 表示完全不读宿主机的 ~/.claude/ 与项目
   .claude/ —— 换台机器行为一致。领域能力全部来自随仓库分发的 plugin/ 目录。

3. **长程**。session_store 可插拔;resume / fork 由 workflow 层驱动。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, SessionStore

PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent / "plugin"


@dataclass
class CompactPolicy:
    """compact 的控制面。算法本身在二进制里改不了,但触发与否可以。

    mode:
      "auto"       默认。阈值 = 窗口 - 33k(实测 200k→167k、100k→67k)。
      "no_summary" DISABLE_AUTO_COMPACT=1。不再把历史总结成一段话。
                   微压缩(清工具结果)走的是 server context_hint / 流式回退路径,
                   与这个开关不同源 —— 读代码看是独立的,但未实测,别当保证。
                   风险:没有全量压缩兜底,撞到窗口上限就是硬错。
                   配 Runtime(trim=True) 一起用,自己控制历史大小。
      "off"        DISABLE_COMPACT=1。连 /compact 也一起关。慎用。

    window: auto-compact 窗口(tokens)。CLI 侧限制 100k–1M;设小于 100k 会被抬到 100k。
    """

    mode: str = "auto"
    window: int | None = None

    def env(self) -> dict[str, str]:
        e: dict[str, str] = {}
        if self.mode == "no_summary":
            e["DISABLE_AUTO_COMPACT"] = "1"
        elif self.mode == "off":
            e["DISABLE_COMPACT"] = "1"
        elif self.mode != "auto":
            raise ValueError(f"未知 compact mode: {self.mode!r}")
        if self.window is not None:
            e["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(self.window)
        return e


SMALL_WINDOW = ("haiku",)
"""名字里带这些的按 200k 算。其余按 100 万 —— flower 面向的是长程活,
而它实际会用到的那几个模型(Opus 5 / Sonnet 5)都到 100 万。"""


def _env_window() -> int | None:
    """``FLOWER_WINDOW`` 配置键 —— 窗口是网关的属性,和 BASE_URL/MODEL 同类,
    该能写进 ~/.config/flower/.env(装一次处处生效),不该只有命令行 --window。
    非正整数当没设(配错了不该把窗口搞成 0)。"""
    raw = os.environ.get("FLOWER_WINDOW")
    if not raw:
        return None
    try:
        w = int(raw)
    except ValueError:
        return None
    return w if w > 0 else None


def calib_path() -> Path:
    """自校准记录的位置。沿用 update.state_path 的先例(~/.config/flower/ 下)。"""
    from .env import user_env_path                       # 局部 import,避免 env↔agent 环
    return user_env_path().parent / ".windows"


def _calib_key() -> str:
    """按 base_url + model 记 —— 窗口是这条链路的属性,换网关/换模型就该重新学。"""
    base = os.environ.get("ANTHROPIC_BASE_URL") or "default"
    model = (os.environ.get("ANTHROPIC_MODEL")
             or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL") or "")
    return f"{base}|{model}"


def calibrated_window() -> int | None:
    """上次在这条 base_url+model 上撞"prompt 太长"的水位(如果记过)。"""
    try:
        data = json.loads(calib_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    w = data.get(_calib_key()) if isinstance(data, dict) else None
    return int(w) if isinstance(w, (int, float)) and w > 0 else None


def remember_overflow(context: int) -> None:
    """撞到"prompt 太长"时把撞墙水位记下来 —— 之后 :func:`default_window` 按它算
    阈值,用户根本不用知道网关的真实上限(issue #23)。

    取 min:见过更小的溢出点就更保守。这是**兜底**,不是唯一入口 —— FLOWER_WINDOW
    和 --window 都优先于它,网关升级了也能显式盖过这条陈旧记录。best-effort,
    写不动就算了(和 update 的状态文件同一个态度)。"""
    if context <= 0:
        return
    p = calib_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    key = _calib_key()
    prev = data.get(key)
    prev = prev if isinstance(prev, (int, float)) and prev > 0 else None
    data[key] = min(int(prev), context) if prev else context
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def default_window() -> int:
    """推断上下文窗口,按优先级:**FLOWER_WINDOW 配置 > 自校准 > 按模型名猜(默认 100 万)**。

    (``--window`` 命令行更高 —— 它在 cli 里显式传进 HandoffPolicy,不经过这里。)

    为什么要前两条(issue #23):窗口是**网关的属性**,和 BASE_URL/MODEL 同类,
    却一直只能靠 --window,既没有配置文件入口、也不会从撞墙里学。而只按名字猜
    对除 haiku 外一律判 1M —— 网关配 ``claude-opus-5[1m]`` 但实际只给 200K 窗口时,
    就会在 ~174K 溢出、走降级空交接(整个流程里最贵的故障)。

    判错仍不是硬错:真实窗口更小的话请求会被 API 以"prompt 太长"退回,Runtime
    认得这个信号 —— 当场换代(降级交接),同时把撞墙水位记进自校准,下一次就准了。
    """
    if (w := _env_window()) is not None:
        return w
    if (w := calibrated_window()) is not None:
        return w
    name = (os.environ.get("ANTHROPIC_MODEL")
            or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL") or "").lower()
    if re.search(r"(?:^|[^a-z0-9])1m(?:[^a-z0-9]|$)", name):
        return 1_000_000
    return 200_000 if any(k in name for k in SMALL_WINDOW) else 1_000_000


@dataclass
class HandoffPolicy:
    """上下文快满了怎么办:**写交接换新会话**,而不是 compact。

    对照 :class:`CompactPolicy` —— 那是"满了才回头总结成一段话,你看不见也管不着"。
    这里是"到阈值就写一份可读可改的文书,换一个新会话接手"。
    机制和产物都在 :mod:`~flower.core.handoff`。

    ``window`` 默认由 :func:`default_window` 按模型名判,**默认 100 万**。
    判大了不会变成硬错:API 会以"prompt 太长"退回,Runtime 认得这个信号,
    当场换代(降级交接)。判小了只是换代偏早,浪费而已。

    ``headroom`` 为什么默认 50k:auto-compact 在窗口 −33k 触发,换代要赶在它前面;
    而"写交接"本身还要再跑一轮。50k 同时满足这两件事。

    开着它就会强制 ``DISABLE_AUTO_COMPACT=1``:两套机制同时在跑的话,
    你分不清某次上下文回落到底是谁干的。代价是**没有兵底** ——
    所以写交接那一步必须有降级路径,见 :func:`~flower.core.handoff.degraded`。
    """

    enabled: bool = True
    window: int = field(default_factory=default_window)
    headroom: int = 0
    """留给"写交接那一轮"的余量。**0 = 按窗口比例自动算**(见 :attr:`at`)。

    别写死一个数:实测栽过。固定 50k 在 200k 窗口上占 25%,够;到 1M 窗口只占 5% ——
    阈值 950k,而写交接那一轮要在 950k 之上再跑一整轮(系统提示 + 工作台索引 +
    交接提示词 + 输出),放不下,于是**交接每次都降级成空的**。
    接手的新会话拿到空交接,只被告知"自己去现场看",重新摸索一遍,再撞满,再降级 ——
    循环到撞上 max_generations。novel 那次 8 次换代里 7 次是空交接,$3021。"""

    HEADROOM_FRACTION = 0.25
    """余量占窗口的比例。25% 来自 200k 窗口下那个够用的 50k。"""

    HEADROOM_FLOOR = 50_000
    """余量下限。再小的窗口也得给写交接留这么多。"""
    max_generations: int = 8
    """一步最多换几代。**这是防跑飞的闸,不是容量规划。**

    危险在于:``at`` 要是低于这个 agent 的**启动地板**(协调者实测约 34k,
    光是系统提示 + 工作台索引就占掉了),那么每一个新会话一开口就越线 ——
    于是写交接、换代、再越线,一轮一轮空转烧钱,而且**永远不会停**
    (换代不吃重试额度,那是有意的)。

    正常的长跑用不到 8 代:200k 窗口下那是上百万 token 的活。
    真撞到这个数,几乎一定是 ``window`` 配小了。
    """

    @property
    def room(self) -> int:
        """实际余量:显式给了就用给的,否则按窗口比例算(下限 HEADROOM_FLOOR)。"""
        if self.headroom > 0:
            return self.headroom
        return max(self.HEADROOM_FLOOR, int(self.window * self.HEADROOM_FRACTION))

    @property
    def at(self) -> int:
        """越过这个数就换代。下限 10k —— 再小就连交接都写不出来了。"""
        return max(10_000, self.window - self.room)

    @property
    def warn_at(self) -> int:
        """逼近提醒的位置。只发一次,不刷屏。"""
        return max(1_000, self.at - 20_000)


@dataclass
class AgentSpec:
    """一个专项 agent 的完整定义。设计 workflow 时,每个阶段一个 spec。"""

    name: str
    instructions: str
    """追加在 Claude Code 原生 system prompt 之后的领域指令。"""

    allowed_tools: list[str] = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    disallowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    effort: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    permission_mode: str = "default"
    agents: dict[str, Any] | None = None
    """subagent 定义(name -> AgentDefinition)。见 core/roles.py。

    这是上下文经济的主要杠杆:subagent 的工具调用与试错留在**它自己的 transcript**
    里(store 的 subpath="subagents/agent-{id}"),主线程只收到最终报告。
    默认让它们 model="inherit" —— 干活的那个不该降级,省的是上下文不是模型档次。"""
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    hooks: dict[str, Any] | None = None
    compact: CompactPolicy | None = None
    env: dict[str, str] = field(default_factory=dict)

    glance: bool = False
    """允许协调者自己跑"只看一眼"的命令(git status / ls / cat ...)。

    派 subagent 去跑 git status 是净亏:subagent 起步就要约 4.3k 上下文(实测),
    而这条命令结果几十字符。放行它们,结果由 EphemeralPolicy 过若干轮后标记过期。
    会改状态的命令(commit/push/装依赖/跑测试)不在此列,照样拦。"""

    workbench: bool = True
    """是否把工作台索引注入这个 agent 的 system prompt。

    确认需求那种**没有写工具**的角色要关掉 —— 索引里全是"脚本写进 scripts/、
    产出写进 artifacts/"的规矩,它一条都执行不了,纯占 token 还添乱。"""

    delegate_only: bool = False
    """只协调、不动手。**注意不要用 disallowed_tools 来实现这件事** ——
    它是会话级的,会连 subagent 一起禁掉(实测报错:"Bash is disabled for this
    session, in subagents as well as here")。正确做法是 allowed_tools 不给,
    再用 PreToolUse hook 按 agent_id 只拦主线程。见 core/guard.py。"""


def build_options(
    spec: AgentSpec,
    *,
    cwd: str | Path | None = None,
    session_store: SessionStore | None = None,
    resume: str | None = None,
    fork: bool = False,
    resume_at: str | None = None,
    use_plugin: bool = True,
    portable: bool = True,
    add_dirs: list[str] | None = None,
    flush: str = "eager",
) -> ClaudeAgentOptions:
    """把 AgentSpec 编译成 SDK options。

    portable=True 时不读取任何宿主机配置,保证换机行为一致。

    **system_prompt.append 只放静态的领域指令(spec.instructions)。** 工作台索引
    **不**在这里 —— 它每落一个文件就变,坐在缓存前缀(tools→system→messages)里会
    每次作废整段历史(实测同一请求贵 3.7 倍,见 #22)。索引由 Runtime 注入到**每个
    新会话的首条 user 消息**(resume 不重注),在缓存断点之后,只有它自己重算,信息一字不少。
    """
    append = spec.instructions
    opts: dict[str, Any] = {
        # 关键:preset 保留 Claude Code 的全部原生能力,append 叠加专业化。
        "system_prompt": {
            "type": "preset",
            "preset": "claude_code",
            "append": append,
        },
        "allowed_tools": spec.allowed_tools,
        "disallowed_tools": spec.disallowed_tools,
        "permission_mode": spec.permission_mode,
        # 隔绝宿主机 ~/.claude/ 与项目 .claude/ —— 可移植性的关键。
        "setting_sources": [] if portable else ["project"],
    }

    if use_plugin and PLUGIN_DIR.is_dir():
        # 领域能力(skills/agents/hooks/MCP)随仓库走,不依赖宿主机安装。
        opts["plugins"] = [{"type": "local", "path": str(PLUGIN_DIR)}]

    if cwd is not None:
        opts["cwd"] = str(cwd)
    if add_dirs:
        # 工作区外的可写目录。工作台放在仓库外时必须给 —— 否则 agent 往那里写
        # 会被判成越界(实测:subagent 报"写入权限被拒",脚本落不了盘)。
        opts["add_dirs"] = [str(d) for d in add_dirs]
    if session_store is not None:
        opts["session_store"] = session_store
        # 长程默认 eager:一轮可能跑几十分钟,崩在中间不该丢掉整轮 transcript。
        # 本地 SQLite 写入很便宜,换来的是随时可恢复。
        opts["session_store_flush"] = flush
    if spec.model:
        opts["model"] = spec.model
    if spec.effort:
        opts["effort"] = spec.effort
    if spec.max_turns is not None:
        opts["max_turns"] = spec.max_turns
    if spec.max_budget_usd is not None:
        # 硬预算:长程 workflow 跑飞时的熔断闸。
        opts["max_budget_usd"] = spec.max_budget_usd
    if spec.agents:
        opts["agents"] = spec.agents
    if spec.mcp_servers:
        opts["mcp_servers"] = spec.mcp_servers
    if spec.hooks:
        opts["hooks"] = spec.hooks

    env = dict(spec.env)
    if spec.compact:
        env.update(spec.compact.env())
    if env:
        opts["env"] = env

    if resume:
        opts["resume"] = resume
        if fork:
            opts["fork_session"] = True
        if resume_at:
            # 从任意历史 message UUID 分叉 —— 长程 workflow 的回滚能力。
            opts["resume_session_at"] = resume_at

    return ClaudeAgentOptions(**opts)
