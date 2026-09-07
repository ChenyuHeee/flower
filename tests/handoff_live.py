"""换代 —— **真实 API**。约 $0.3–0.8。

离线(`tests/handoff_offline.py`)钉的是框架把交接传对了没有。它证明不了
最要紧的那一步:**接手的会话只靠一份交接书,真的接得住吗?**

做法是"记忆探针",和 `tests/wake_live.py` 同源,但这次换代发生在
**同一个进程、同一个步骤内**:

    第 1 步「干活」  任务里埋一个只在对话里出现、磁盘上没有的约定(构建标签)
                    让它读文件把上下文顶过阈值 → 触发换代
    第 2 步「报告」  resume_from="干活" —— 续的是**接班的那个 session**
                    问它构建标签是什么。答得出 = 交接真的把决策带过去了

阈值**自校准**:先跑一轮量出这个角色的启动地板(协调者实测约 34k),
再把阈值设在地板之上。写死一个数会在换模型/网关之后变成"一开局就越线"。

    .venv/bin/python tests/handoff_live.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.agent import AgentSpec, HandoffPolicy          # noqa: E402
from flower.core.handoff import Handoff                         # noqa: E402
from flower.core.runtime import Runtime                         # noqa: E402
from flower.core.workbench import Workbench                     # noqa: E402
from flower.workflow.base import Step, Workflow                 # noqa: E402
from flower.cli import Render                                   # noqa: E402

TAG = "K7Q3"
ROOT = Path(__file__).resolve().parent.parent

READER = AgentSpec(
    name="调研",
    instructions="你在做代码调研。读到什么就说什么,别猜。",
    allowed_tools=["Read", "Glob", "Grep"],
    max_turns=40,          # 闸:这个测试是验机制,不是验耐力
)

SURVEY = f"""\
这次调研的**构建标签是 {TAG}** —— 记住它,后面每份产出都要带上这个标签,
这是已经定下的事,不要改。

现在逐个通读下面这些文件,每读完一个用两三句话说它是干什么的:

{chr(10).join(f'- {p}' for p in [
    'flower/core/runtime.py', 'flower/core/roles.py', 'flower/core/human.py',
    'flower/stores/trim.py', 'flower/workflow/base.py', 'flower/cli.py',
])}

**每个文件整份读完**(不要只读开头),读完用一句话说它是干什么的,然后读下一个。
"""


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


ok = True


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="flower-handoff-live-"))
    wb = Workbench(ROOT, home=tmp / "bench").ensure()
    show = Render()

    # ---- 校准:先量这个角色的启动地板 ---------------------------------
    print("\n[0] 量启动地板(阈值必须设在它之上,否则一开局就越线)")
    cal = Runtime(workspace=ROOT, run_dir=tmp / "cal", handoff=False)
    r0 = await cal.run(READER, "只回两个字:就绪", step_name="校准")
    floor = r0.context
    cal.close()
    print(f"    地板 {floor/1000:.1f}K · 花费 ${r0.cost_usd:.4f}")
    check(floor > 0, "拿到了上下文读数")

    at = floor + 15_000
    policy = HandoffPolicy(window=at + 15_000, headroom=15_000)
    print(f"    → 阈值定在 {policy.at/1000:.1f}K(地板 + 15K)")

    # ---- 真跑 ----------------------------------------------------------
    rt = Runtime(workspace=ROOT, run_dir=tmp / "runs", workbench=wb, handoff=policy)
    wf = Workflow(steps=[
        Step("干活", spec=READER, prompt=SURVEY),
        Step("报告", spec=READER, resume_from="干活",
             prompt="不用再读文件了。一句话回答:这次调研的构建标签是什么?"),
    ])
    try:
        ctx = await wf.run(rt, on_event=show)
        work = ctx["_results"]["干活"]
        report = ctx["_results"]["报告"]
    finally:
        rt.close()

    print("\n[1] 换代确实发生了")
    check(bool(work.retired), f"烧掉了 {len(work.retired)} 代:{work.retired}")
    check(work.session_id not in work.retired,
          f"对外的 session_id 是接班人 {work.session_id}")

    print("\n[2] 交接书落盘,而且是可读的文书 —— 不是一段看不见的摘要")
    path = wb.notes / "交接-干活.md"
    h = Handoff.load(path)
    check(h is not None, f"交接在 {path}")
    if h is not None:
        check(h.complete(), f"必填两段齐全(缺:{h.missing()})")
        check(not h.degraded, "不是降级版本 —— 模型真的写出来了")
        for k, label in (("doing", "现在在做什么"), ("decided", "已经定下的"),
                         ("deadends", "走不通的路"), ("next", "下一步"),
                         ("scene", "现场")):
            v = getattr(h, k).strip()
            print(f"    {label}: {' '.join(v.split())[:90] or '(空)'}")
        check(TAG in h.to_markdown(),
              f"**{TAG} 出现在交接里** —— 「已经定下的」那一段起作用了")

    print("\n[3] 接班的会话答得出那个标签(它只可能来自交接)")
    said = (report.text or "").strip()
    print(f"    回话:{' '.join(said.split())[:120]}")
    check(TAG in said, f"**{TAG}** —— 交接真的把决策带过去了")

    total = work.cost_usd + report.cost_usd + r0.cost_usd
    print(f"\n{'✓ 换代在真实 API 上跑通' if ok else '✗ 有失败'} · "
          f"合计 ${total:.4f} · 记录 {tmp}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
