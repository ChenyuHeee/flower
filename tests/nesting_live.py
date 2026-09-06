"""**会花钱的探针**:subagent 到底能不能再派 subagent?

这是三层架构(主agent → sub主agent → 小subagent)的地基。地基不成立,
sub主agent 就不能是一个 ``AgentDefinition``,得落到 workflow 层去(每个并行流
一个独立 ``Runtime`` session)—— 两套完全不同的实现。

已知的事实(离线查得):
  * ``AgentDefinition`` **没有 agents 字段**;agent 注册表只在 session 级
    (``opts["agents"]``)。所以下级能不能被看见,只能实测。
  * ``delegate_guard`` 只拦主线程(判据是 data 里有没有 ``agent_id``),
    所以 sub主agent 目前拿到的是全套工具。

同一次运行顺便回答第二个未知:**PreToolUse 的 data 里到底有什么** ——
能不能建立"agent_id → 角色"的映射。能建立,按角色限制工具才做得到。

跑法(不要在容器里跑,也不要在 flower 仓库里跑):

    .venv/bin/python tests/nesting_live.py

约 $0.3–0.8。工作目录用 ~/.flower-probe-nesting,与任何真实项目无关。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_agent_sdk import AgentDefinition, HookMatcher   # noqa: E402

from flower.core.roles import coordinator, worker           # noqa: E402
from flower.core.runtime import Runtime                     # noqa: E402

WS = Path.home() / ".flower-probe-nesting"
PROBE = "probe.txt"

# 每次 PreToolUse 的原始 data,用来回答"hook 能看到什么"
seen: list[dict] = []


def observer() -> HookMatcher:
    """只看不拦。记下每次 PreToolUse 的 data 键和关键值。"""

    async def hook(data: dict, tool_use_id: str | None, context) -> dict:
        inp = data.get("tool_input") or {}
        seen.append({
            "keys": sorted(data.keys()),
            "tool": data.get("tool_name"),
            # agent_id 是不透明 id;agent_type 才是角色名 —— 决定"能不能按角色限制工具"
            "agent_id": data.get("agent_id"),
            "agent_type": data.get("agent_type"),
            "subagent_type": inp.get("subagent_type"),   # 这次要派谁
            "permission_mode": data.get("permission_mode"),
        })
        return {}

    return HookMatcher(matcher=None, hooks=[hook])


async def main() -> int:
    shutil.rmtree(WS, ignore_errors=True)
    WS.mkdir(parents=True)

    # 小subagent:动手的那一层,有写工具
    hand = worker(
        "动手干一步的活。写文件、跑命令都找它。",
        f"你负责动手。任务给你什么就做什么,做完一句话回报。",
        tools=["Read", "Write", "Bash"],
    )

    # sub主agent:**没有写工具,只有 Agent** —— 它必须派 hand 才能完成任务。
    # 这正是要验的:它手里的 Agent 工具到底能不能用。
    lead = AgentDefinition(
        description="领队。拿到大任务,自己不动手,拆开派给 hand。",
        prompt=(
            "你是领队。**你没有写文件和跑命令的工具,这是有意的。**\n"
            "要动手就用 Agent 工具派 `subagent_type=\"hand\"` 去做,任务写清楚。\n"
            "如果你发现自己根本没有 Agent 工具可用,就直接在回话里说"
            "「我没有 Agent 工具」,不要试别的办法,也不要假装做完了。"
        ),
        tools=["Agent", "Read"],
        model="inherit",
    )

    # QUICK=1:只跑一层(主 → hand),用来便宜地取 agent_type 的值。
    # 嵌套那条结论已经由完整模式验过,不必每次都花那份钱。
    import os
    quick = os.environ.get("QUICK") == "1"
    roles = {"hand": hand} if quick else {"lead": lead, "hand": hand}
    coord = coordinator(
        "主控", "", roles,
        max_budget_usd=1.5, max_turns=12,
        hooks={"PreToolUse": [observer()]},
    )

    rt = Runtime(workspace=WS, run_dir=WS / "runs", workbench=True)
    try:
        task = (f"派 `hand` 去把 ok 两个字写进 {PROBE},然后回报。你自己不要动手。"
                if quick else
                f"派 `lead` 去把 ok 两个字写进 {PROBE}。"
                f"**你自己不要动手,也不要直接派 hand** —— 必须经过 lead。"
                f"最后告诉我 lead 说了什么。")
        r = await rt.run(
            coord,
            task,
            on_event=lambda e: print(
                f"  [{e.kind}] {(e.tool or '')} {(e.text or '')[:100]}", flush=True)
            if e.kind in ("tool_call", "text", "error") else None,
        )
    finally:
        rt.close()

    print("\n" + "=" * 66)
    print(f"花费 ${r.cost_usd:.4f} / {r.num_turns} 轮 / ok={r.ok}")

    # --- 结论 1:嵌套成立吗 --------------------------------------------
    made = (WS / PROBE).is_file()
    nested = [s for s in seen if s["tool"] == "Agent" and s["agent_id"]]
    keys = [r[0] for r in __import__("sqlite3").connect(
        WS / "runs" / "sessions.db").execute(
        "select distinct store_key from entries")]
    subs = [k for k in keys if "subagent" in k]

    print(f"\n【结论 1:subagent 能再派人吗】")
    print(f"  {PROBE} 被创建了吗          : {made}")
    print(f"  带 agent_id 的 Agent 调用   : {len(nested)} 次  ← >0 就是嵌套成立")
    print(f"  subagent 级 store_key       : {len(subs)} 个  ← 2 个说明 lead 和 hand 都跑了")
    for k in subs:
        print(f"      {k}")
    verdict = "成立" if nested else ("不成立" if made else "未定(看下面正文)")
    print(f"  → **嵌套{verdict}**")
    if not nested and made:
        print("     (文件建好了但没有嵌套调用 —— 说明是别人动的手,不是 lead 派的)")

    # --- 结论 2:hook 能看到角色吗 --------------------------------------
    print(f"\n【结论 2:PreToolUse 的 data 里有什么】")
    allkeys = sorted({k for s in seen for k in s["keys"]})
    print(f"  出现过的键:{allkeys}")
    with_id = [s for s in seen if s["agent_id"]]
    print(f"  {len(seen)} 次调用里 {len(with_id)} 次带 agent_id")
    if with_id:
        print(f"  样例:{json.dumps(with_id[0], ensure_ascii=False)}")
    print(f"  → agent_id 能直接看出角色吗:"
          f"{'能' if any('type' in k or 'name' in k for k in allkeys if k != 'tool_name') else '不能(只有不透明 id)'}")

    (WS / "probe-result.json").write_text(
        json.dumps({"seen": seen, "made": made, "subs": subs,
                    "cost": r.cost_usd, "text": r.text}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n原始记录:{WS / 'probe-result.json'}")
    print(f"lead/主控的回话:\n{(r.text or '')[:600]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
