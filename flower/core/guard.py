"""Hook 层 —— 在事情发生的那一刻剪枝,而不是事后压缩。

三个 hook,各管一件事:

* :func:`delegate_guard`   主线程想自己动手时拦下来,并告诉它去派活。
* :func:`spill_guard`      工具结果太大时,**在进模型之前**换成文件指针。
* :func:`index_guard`      有人往工作台写了东西,刷新索引。
* :func:`isolate_guard`    会写代码的 subagent,自动塞进各自的 git worktree。

``spill_guard`` 是和 compact 最本质的区别:compact 是等上下文满了再回头总结,
这里是每一次工具调用当场决定"这坨东西该不该进上下文"。大的当场落盘,
上下文里只留一行路径 —— 内容没丢,只是不常驻。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from claude_agent_sdk import AgentDefinition, HookMatcher

from .workbench import Workbench

HANDS_ON = "Bash|Write|Edit|NotebookEdit"
WRITE_ONLY = "Write|Edit|NotebookEdit"
BULKY = "Bash|Read|Grep|Glob|WebFetch|WebSearch"


def _is_main_thread(data: dict[str, Any]) -> bool:
    """subagent 里的 tool-lifecycle hook 会带 agent_id;主线程不带。"""
    return not data.get("agent_id")


def _deny(reason: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}


def whitelist_guard(allowed: list[str] | None, *, role: str = "这个角色") -> HookMatcher | None:
    """让 ``allowed_tools`` 对**动手的那四个工具**真正排他。

    **为什么需要它**:``allowed_tools`` 不是排他白名单,是**免审批清单** ——
    模型照样能调用不在里面的工具。实测两处(见 `docs/case-ht002.md` 第三节):

      * 确认者用了 ``WebFetch``,而 ``clarify()`` 的白名单里没有它
      * 设目标那个 ``judge()`` 跑了 11 次 ``Bash``,而 ``goal_step``
        **根本没有传 can_run 的代码路径**
      * $0.1 探针:``allowed_tools=["Read"]`` 的 agent 能调 Write 和 Bash,
        挡住它们的是**权限层和路径安全**,不是白名单

    后果:``clarify()`` / ``judge()`` 这类"不该动手"的角色,保护完全来自
    继承来的 ``permission_mode="default"``,**不是 flower 的任何机制**。
    一旦谁把它设成 ``acceptEdits``(``coordinator()`` 默认就是这个值),
    确认者就能开始写代码 —— 而那正是 `$0.8908` 那次反面实测要防的事。

    这道 hook 把差额补上:**白名单里没有的动手工具,一律拒绝**。
    从 ``allowed_tools`` 派生,所以 ``judge(can_run=True)`` 自动保留 Bash、
    仍然拦掉 Write/Edit —— 不需要额外的开关。

    只管**本会话的主线程**:subagent 就是来干活的,它的工具由
    ``AgentDefinition.tools`` 决定,不受这里约束。

    没有需要拦的工具时返回 ``None``(比如 worker 那种全套工具的角色),
    调用方据此决定装不装 —— 不需要拦的角色一个 hook 都不装。
    """
    have = set(allowed or [])
    banned = [t for t in ("Bash", "Write", "Edit", "NotebookEdit") if t not in have]
    if not banned:
        return None

    async def hook(data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        if not _is_main_thread(data):
            return {}
        name = data.get("tool_name", "?")
        return _deny(
            f"{role}没有 {name}。**这是有意的,不是配置漏了。**"
            "把结论写进你的回话正文里,框架会从那里取 —— 不要试别的写法绕过去。"
        )

    return HookMatcher(matcher="|".join(banned), hooks=[hook])


def delegate_guard(*, tools: str = HANDS_ON, allow_glance: bool = False) -> HookMatcher:
    """主线程自己动手 → 拒绝,并指路。

    allowed_tools 已经不给这些工具了,但模型看到的只是"工具不存在",容易卡住或绕路。
    这里把它变成一句明确的指令:派 subagent 去。

    ``allow_glance=True``:放行 ``git status`` / ``ls`` 这类**只看一眼**的命令。
    派个 subagent 去跑 ``git status`` 是净亏的 —— subagent 起步就要 4.3k 上下文
    (实测),而这条命令的结果几十个字符,还会过期。放行它们,再由
    :class:`~flower.stores.trim.EphemeralPolicy` 在若干轮后把结果换成"已过期"。
    真正会改状态的命令(commit / push / 装依赖 / 跑测试)照样拦。
    """
    async def hook(data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        if not _is_main_thread(data):
            return {}          # subagent 就是来干活的,放行
        name = data.get("tool_name", "?")
        if allow_glance and name == "Bash":
            # 判据和"结果会不会被剪枝"是同一个函数 —— 放行集合必须等于过期集合。
            from ..stores.trim import is_ephemeral
            if is_ephemeral((data.get("tool_input") or {}).get("command", "")):
                return {}
        return _deny(
            f"协调者不直接使用 {name}。用 Agent 工具派一个 subagent 去做,"
            "任务里写清目标与验收标准,并要求它把长产出写进 .flower/artifacts/、"
            "回话只给路径与结论。"
        )

    return HookMatcher(matcher=tools, hooks=[hook])


def spill_guard(
    workbench: Workbench,
    *,
    threshold: int = 4000,
    tools: str = BULKY,
    main_only: bool = False,
) -> HookMatcher:
    """超过 threshold 字符的工具结果,落盘 + 换成一行指针。

    ``updatedToolOutput`` 必须保持原工具的输出结构,否则会被拒绝(原文照旧,不会出错)。
    所以这里只替换 dict 里过长的**字符串字段**,键和其它类型一律不动。
    list 不碰 —— 里面可能是图片块。
    """
    spill_dir = workbench.root / "spill"

    def stash(text: str) -> str:
        spill_dir.mkdir(parents=True, exist_ok=True)
        f = spill_dir / f"{hashlib.sha256(text.encode()).hexdigest()[:16]}.txt"
        if not f.exists():
            f.write_text(text, encoding="utf-8")
        rel = workbench.show(f)
        head = text[:400].replace("\n", " ")
        return (f"[输出 {len(text)} 字符,已落盘到 {rel} —— 需要全文用 Read 读它,"
                f"需要找东西用 Grep 搜它]\n开头 400 字符:{head}")

    def shrink(resp: Any) -> Any | None:
        if isinstance(resp, str):
            return stash(resp) if len(resp) >= threshold else None
        if isinstance(resp, dict):
            out, changed = dict(resp), False
            for k, v in resp.items():
                if isinstance(v, str) and len(v) >= threshold:
                    out[k], changed = stash(v), True
                elif isinstance(v, dict) and (nested := shrink(v)) is not None:
                    out[k], changed = nested, True
            return out if changed else None
        return None

    async def hook(data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        if main_only and not _is_main_thread(data):
            return {}
        shrunk = shrink(data.get("tool_response"))
        if shrunk is None:
            return {}
        return {"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": shrunk,
        }}

    return HookMatcher(matcher=tools, hooks=[hook])


def index_guard(workbench: Workbench) -> HookMatcher:
    """往工作台写了东西就刷新 INDEX.md。下一个 agent 开局就知道它存在。"""

    async def hook(data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        p = (data.get("tool_input") or {}).get("file_path")
        if p and str(workbench.root) in str(Path(p).resolve()):
            workbench.refresh()
        return {}

    return HookMatcher(matcher="Write|Edit", hooks=[hook])


ISOLATE_ATTR = "_flower_isolate"


def isolated(agent: AgentDefinition, flag: bool = True) -> AgentDefinition:
    """给一个 subagent 定义打上"需要独立工作区"的标记。

    标记走 Python 侧属性,不是 dataclass 字段 —— SDK 用 ``asdict()`` 序列化,
    只认已声明的字段,所以这个标记不会漏到 CLI 那边去(已实测)。
    """
    object.__setattr__(agent, ISOLATE_ATTR, bool(flag))
    return agent


def wants_isolation(agent: AgentDefinition | None) -> bool:
    return bool(getattr(agent, ISOLATE_ATTR, False))


def isolate_guard(
    agents: dict[str, AgentDefinition],
    *,
    on_inject: Any = None,
) -> HookMatcher:
    """按角色给 subagent 分配独立 git worktree。

    为什么是 hook 而不是提示词:提示词是**建议**,模型可以不听,而且不管用不用得上
    都要常驻占 token。这里是**框架保证** —— 已实测:即便系统提示明确写着
    "不要用 worktree",注入照样生效(模型传的是 None,落地的是 'worktree')。
    而不需要隔离的角色(只读的调研、审查)一个字节都不会被加上。

    触发条件是 ``subagent_type`` 对应的角色被 :func:`isolated` 标记过 ——
    所以"要不要隔离"是**角色的属性**,不是全局开关,也不是每次派活都判断。

    注意 ``isolation`` 与 ``cwd`` 在 Agent 工具里是互斥的:模型自己指定了 cwd
    (比如它就是要去某个已有目录干活),就尊重它,不注入。
    """

    async def hook(data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        if data.get("tool_name") != "Agent":
            return {}
        inp = dict(data.get("tool_input") or {})
        # 已经有 cwd 或已经指定了 isolation —— 不覆盖模型的明确选择。
        if inp.get("cwd") or inp.get("isolation"):
            return {}
        if not wants_isolation(agents.get(inp.get("subagent_type", ""))):
            return {}
        inp["isolation"] = "worktree"
        if on_inject:
            on_inject(inp.get("subagent_type"), inp.get("description"))
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": inp,
        }}

    return HookMatcher(matcher="Agent", hooks=[hook])


def merge_hooks(*groups: dict[str, list[Any]] | None) -> dict[str, list[Any]]:
    """按事件名合并多组 hook 配置。"""
    out: dict[str, list[Any]] = {}
    for g in groups:
        for event, matchers in (g or {}).items():
            out.setdefault(event, []).extend(matchers)
    return out


def workbench_hooks(
    workbench: Workbench,
    *,
    delegate_only: bool = True,
    spill_threshold: int | None = 4000,
    agents: dict[str, AgentDefinition] | None = None,
    allow_glance: bool = False,
) -> dict[str, list[HookMatcher]]:
    """一次装好工作台需要的那几个 hook。

    ``agents`` 里有被 :func:`isolated` 标记过的角色时,才挂 isolate_guard ——
    没有标记就一个 hook 都不装,零开销。
    """
    pre = [delegate_guard(allow_glance=allow_glance)] if delegate_only else []
    if agents and any(wants_isolation(a) for a in agents.values()):
        pre.append(isolate_guard(agents))
    post = [index_guard(workbench)]
    if spill_threshold:
        post.append(spill_guard(workbench, threshold=spill_threshold))
    return {k: v for k, v in {"PreToolUse": pre, "PostToolUse": post}.items() if v}
