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
    prelude: str = "",
) -> ClaudeAgentOptions:
    """把 AgentSpec 编译成 SDK options。

    portable=True 时不读取任何宿主机配置,保证换机行为一致。
    prelude 追加在领域指令之后(工作台索引走这里)—— 它每轮都在,所以要短。
    """
    append = spec.instructions if not prelude else f"{spec.instructions}\n\n{prelude}"
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
