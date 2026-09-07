"""工具墙 —— 离线验证。**不打网络,不花钱。**

钉住的是 HT002 挖出来的那个安全问题(issue #5):

    ``allowed_tools`` **不是排他白名单,是免审批清单**。
    实测三处:确认者用了不在白名单里的 WebFetch;设目标的 judge 跑了 11 次 Bash,
    而 goal_step 根本没有传 can_run 的代码路径;$0.1 探针里
    ``allowed_tools=["Read"]`` 的 agent 能调 Write 和 Bash ——
    挡住它们的是权限层和路径安全,**不是白名单**。

后果:``clarify()`` / ``judge()`` 的保护完全来自继承的 ``permission_mode``,
不是 flower 的任何机制。``whitelist_guard`` 把这个差额补上。

覆盖:
  1. 从 allowed_tools 派生要拦哪些 —— judge(can_run=True) 自动保留 Bash
  2. 拦主线程,放行 subagent(它的工具由 AgentDefinition.tools 决定)
  3. 不需要拦的角色一个 hook 都不装(返回 None)
  4. **不依赖工作台** —— 没开 -W 时照样装(原来 hook 整体只在有工作台时才装)
  5. 协调者不装它(delegate_guard 已经拦了同一批,措辞更对路)
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.guard import whitelist_guard                 # noqa: E402
from flower.core.human import HumanChannel                    # noqa: E402
from flower.core.roles import clarify, coordinator, judge, worker   # noqa: E402

ok = True


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


def decide(guard, tool, *, agent_id=None):
    """跑一次 hook,返回 'deny' / 'allow'。"""
    data = {"tool_name": tool, "tool_input": {}}
    if agent_id:
        data["agent_id"] = agent_id
    out = asyncio.run(guard.hooks[0](data, None, None))
    return (out.get("hookSpecificOutput") or {}).get("permissionDecision", "allow")


def main() -> int:
    ch = HumanChannel()

    print("\n[1] 从 allowed_tools 派生:拦的正是白名单里没有的那些")
    cases = [
        ("确认者", clarify("确认者", ch).allowed_tools,
         {"Bash", "Write", "Edit", "NotebookEdit"}),
        ("判定者(默认)", judge("判定者", ch).allowed_tools,
         {"Bash", "Write", "Edit", "NotebookEdit"}),
        # can_run=True 把 Bash 放进白名单 —— 于是它自动不再被拦,不需要额外开关
        ("判定者(can_run)", judge("判定者", ch, can_run=True).allowed_tools,
         {"Write", "Edit", "NotebookEdit"}),
    ]
    for name, allowed, want in cases:
        g = whitelist_guard(allowed, role=name)
        got = set(g.matcher.split("|")) if g else set()
        check(got == want, f"{name}: 拦 {sorted(got)}")

    print("\n[2] 判定者开了 can_run 就真的能跑 Bash,但仍然不能写")
    g = whitelist_guard(judge("判定者", ch, can_run=True).allowed_tools, role="判定者")
    check("Bash" not in g.matcher, "Bash 不在拦截名单里")
    check(decide(g, "Write") == "deny", "Write 仍被拒 —— 判定者改了东西,判定就没意义了")
    check(decide(g, "Edit") == "deny", "Edit 仍被拒")

    print("\n[3] 拦主线程,放行 subagent")
    g = whitelist_guard(clarify("确认者", ch).allowed_tools, role="确认者")
    check(decide(g, "Write") == "deny", "主线程 Write → 拒绝")
    check(decide(g, "Bash") == "deny", "主线程 Bash → 拒绝")
    check(decide(g, "Write", agent_id="a1b2") == "allow",
          "subagent Write → 放行(它的工具由 AgentDefinition.tools 决定)")

    print("\n[4] 拒绝时说清楚这是有意的")
    data = {"tool_name": "Write", "tool_input": {}}
    out = asyncio.run(g.hooks[0](data, None, None))
    reason = (out.get("hookSpecificOutput") or {}).get("permissionDecisionReason", "")
    check("有意的" in reason, "措辞点明「这是有意的,不是配置漏了」")
    check("确认者" in reason, "带上角色名,模型知道是谁被限制了")

    print("\n[5] 不需要拦的角色不装 hook(零开销)")
    full = worker("干活", "", tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep",
                                     "NotebookEdit"])
    check(whitelist_guard(list(full.tools or []), role="worker") is None,
          "全套工具的角色 → 返回 None,一个 hook 都不装")

    print("\n[6] 协调者不装它 —— delegate_guard 已经拦了同一批")
    coord = coordinator("协调者", "", {})
    check(coord.delegate_only is True,
          "协调者 delegate_only=True → Runtime 据此跳过 whitelist_guard")
    check(clarify("c", ch).delegate_only is False and judge("j", ch).delegate_only is False,
          "确认者/判定者 delegate_only=False → 它们才是这道墙的服务对象")

    print("\n[7] 不依赖工作台(这是原来的洞:hook 整体只在有工作台时才装)")
    src = Path("flower/core/runtime.py").read_text(encoding="utf-8")
    wall_at = src.index("whitelist_guard(spec.allowed_tools")
    wb_block = src.index("if self.workbench is not None:")
    wb_end = src.index("if not spec.delegate_only:")
    check(not (wb_block < wall_at < wb_end),
          "whitelist_guard 的调用不在 `if self.workbench is not None` 那个块里")

    print("\n[8] 上网是只读的,不该要人逐个确认;但给了它也不能削弱那道墙")
    from flower.core.roles import WEB_TOOLS                      # noqa: PLC0415
    w = set(worker("干活", "").tools or [])
    check(set(WEB_TOOLS) <= w, f"worker 有上网能力(调研/查文档本来就该能){sorted(WEB_TOOLS)}")
    c = set(clarify("确认者", ch).allowed_tools or [])
    check(set(WEB_TOOLS) <= c, "确认者也有 —— 问需求时常要查'官方怎么说'")
    check(not ({"Write", "Edit", "Bash"} & c), "**但确认者仍然没有任何写工具**")
    g = whitelist_guard(clarify("确认者", ch).allowed_tools, role="确认者")
    check(decide(g, "Write") == "deny" and decide(g, "Bash") == "deny",
          "加了 Web 之后,那道墙照样拦住 Write/Bash(墙是从白名单派生的,没被削弱)")
    j = set(judge("判定者", ch).allowed_tools or [])
    check(not (set(WEB_TOOLS) & j), "判定者**不给** —— 判定该看现场,不该看网页")
    co = set(coordinator("协调者", "", {}).allowed_tools or [])
    check(not (set(WEB_TOOLS) & co), "协调者**不给** —— 它只协调,查资料派人去")

    print(f"\n{'✓ 工具墙全部通过' if ok else '✗ 有失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
