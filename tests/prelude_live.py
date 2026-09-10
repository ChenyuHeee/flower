"""**会花钱的探针**($0.1–0.3):subagent 能看见 session 级的 system_prompt.append 吗?

这是工作台机制的承重问题。工作台索引此前放进 ``system_prompt.append``(session 级),
而 README 和 workbench.py 的说法是"索引被注入**每个** agent 的 system prompt"。
(#22 之后索引改注入**首条 user 消息** —— 但 append 这条通道本身仍在,spec.instructions
走它;"subagent 到底看不看得见主线程的 system prompt"这个承重问题不变。)

如果 subagent 拿不到它,那么:
  * "后面每一个 subagent 开局就知道需求文件在哪"是错的
  * 长产出写 artifacts 这条规矩,唯一来源就是协调者在任务书里转述 ——
    而那正是我们想删掉的重复(见 COORDINATOR_RULES 的实测:一轮浪费约 4.8k 上下文)

验法:在 append 里放一个**只可能来自那里**的口令,然后派一个 subagent,
问它 system prompt 里有没有这个口令。它没有别的渠道能知道。

    .venv/bin/python tests/prelude_live.py

工作目录 ~/.flower-probe-prelude,与任何真实项目无关。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.agent import AgentSpec                    # noqa: E402
from flower.core.roles import worker                       # noqa: E402
from flower.core.runtime import Runtime                    # noqa: E402

WS = Path.home() / ".flower-probe-prelude"
TOKEN = "XYZZY-PRELUDE-7Q4W"          # 只可能来自 system_prompt.append


async def main() -> int:
    shutil.rmtree(WS, ignore_errors=True)
    WS.mkdir(parents=True)

    hand = worker(
        "回答关于自己 system prompt 的问题。",
        "有人会问你 system prompt 里有没有某个口令。"
        "**如实回答**:有就把那句话原样引出来,没有就明确说没有。"
        "不要猜、不要客气、不要为了让对方满意而说有。",
        tools=["Read"],
        discipline=False,          # 关掉汇报纪律,免得它把答案压缩掉
    )

    coord = AgentSpec(
        name="主控",
        # 口令直接放进 instructions —— 它进 system_prompt.append(session 级)。
        # #22 之后工作台索引不再走 append(改注入首条 user 消息),但 append 这条
        # 通道本身仍在(spec.instructions 走它),要验的就是它到不到 subagent。
        instructions=("你负责派活。用 Agent 工具派 subagent_type='hand'。\n\n"
                      f"# 工作台口令\n\n本次运行的口令是 {TOKEN}。"),
        allowed_tools=["Agent"],
        agents={"hand": hand},
        permission_mode="acceptEdits",
        max_budget_usd=1.0,
        max_turns=8,
    )
    rt = Runtime(workspace=WS, run_dir=WS / "runs")
    try:
        r = await rt.run(
            coord,
            "派 hand 去回答:它自己的 system prompt 里有没有出现一个形如 "
            "XYZZY-... 的口令?让它如实回答,有就原样引出来,没有就说没有。"
            "把它的原话转述给我。",
            on_event=lambda e: print(f"  [{e.kind}] {(e.text or '')[:120]}", flush=True)
            if e.kind in ("text", "error") else None,
        )
    finally:
        rt.close()

    text = r.text or ""
    print("\n" + "=" * 66)
    print(f"花费 ${r.cost_usd:.4f} / {r.num_turns} 轮")
    saw = TOKEN in text
    print(f"\n口令 {TOKEN} 出现在最终回话里:{saw}")
    print("**结论**:" + (
        "subagent **能**看见 session 级的 append —— 工作台索引确实注入了每个 agent"
        if saw else
        "subagent **看不见** session 级的 append —— 工作台索引只到主线程。\n"
        "  → workbench.py 与 README 里「注入每个 agent」的说法要改;\n"
        "  → artifacts 那条规矩必须由 WORKER_RULES 或任务书承担"))
    print(f"\n主控转述的原话:\n{text[:700]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
