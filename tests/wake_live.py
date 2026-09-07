"""接续 —— **真实 API,两个进程**。实测 $0.235。

(第一程 $0.186 是 Claude Code 预置系统提示的启动地板,和这个测试无关;
第二程只花 $0.049 —— 接续本身很便宜,缓存命中把重复的那一大段吃掉了。)

离线测试(`tests/lineage_offline.py`)钉的是框架把 resume 传对了没有。
它证明不了最后那一步:**SDK 真的能跨进程恢复那段对话吗?**
只有真跑才知道 —— 而这正是整个特性成立与否的地方。

做法是"记忆探针":

    进程 1   记住 4271 —— 只在那次对话里说过,磁盘上任何文书都没有
    进程 2   问它记得什么。答得出来 = 上下文真的接上了

两个**真正独立的 OS 进程**(subprocess 自调用),不是同一进程跑两遍 ——
后者证明不了任何东西,内存里的 ctx 本来就还在。

    .venv/bin/python tests/wake_live.py
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.agent import AgentSpec              # noqa: E402
from flower.core.lineage import Lineage              # noqa: E402
from flower.core.runtime import Runtime              # noqa: E402
from flower.workflow.base import Step, Workflow      # noqa: E402

TOKEN = "4271"
SPEC = AgentSpec(
    name="记事的",
    instructions="你只回一句话,不用工具,不解释。",
    allowed_tools=[],
    max_budget_usd=0.20,
)


def flow() -> Workflow:
    return Workflow(steps=[Step(
        "记事",
        spec=SPEC,
        prompt=f"记住这个数字:{TOKEN}。只回两个字:记住",
        # 接续时说的话:**不重复那个数字**,否则这个测试就自己作弊了
        resume_prompt="我刚才让你记的那个数字是多少?只回数字本身。",
    )])


async def leg(run_dir: Path, ws: Path) -> str:
    rt = Runtime(workspace=ws, run_dir=run_dir)
    try:
        ctx = await flow().run(rt)
        r = ctx["_results"]["记事"]
        print(f"    session={r.session_id} 花费=${r.cost_usd:.4f}")
        return (r.text or "").strip()
    finally:
        rt.close()


async def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--leg":
        print(await leg(Path(sys.argv[2]) / "runs", Path(sys.argv[2]) / "ws"))
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="flower-wake-"))
    (tmp / "ws").mkdir(parents=True, exist_ok=True)
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(f"  {'✓' if cond else '✗'} {msg}")
        ok = ok and bool(cond)

    def spawn() -> str:
        r = subprocess.run([sys.executable, __file__, "--leg", str(tmp)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode:
            print(r.stdout, r.stderr[-800:])
            raise SystemExit("子进程失败")
        print("   ", "\n    ".join(r.stdout.strip().splitlines()[:-1]))
        return r.stdout.strip().splitlines()[-1]

    print(f"\n[1] 进程 1:记住 {TOKEN}")
    first = spawn()
    print(f"    回话:{first!r}")
    lin = Lineage.open(tmp / "runs", tmp / "ws")
    sid1 = lin.steps.get("记事")
    check(bool(sid1), f"血缘落盘:记事 → {sid1}")

    print("\n[2] 进程 2(全新 OS 进程):你刚才记的数字是多少?")
    second = spawn()
    print(f"    回话:{second!r}")
    check(TOKEN in second,
          f"答得出 {TOKEN} —— **上下文真的跨进程接上了**(这句话在磁盘上任何地方都没有)")
    lin2 = Lineage.open(tmp / "runs", tmp / "ws")
    check(lin2.steps.get("记事") == sid1, "还是同一个 session,没有开新的")
    check(lin2.woke == 2, f"唤醒计数 = {lin2.woke}")

    man = (tmp / "runs" / "manifest.json").read_text(encoding="utf-8")
    check(man.count('"step"') == 2, "manifest 两行都在(跨进程追加,没被冲掉)")

    print(f"\n{'✓ 接续在真实 API 上跑通' if ok else '✗ 有失败'} —— 临时目录 {tmp}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
