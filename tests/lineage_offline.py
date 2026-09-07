"""同一个路径 = 同一段对话 —— 离线验证。**不打网络,不花钱。**

钉住的是"用户不需要知道 session 这个词"这件事的机制:

    在同一个工作区再跑一次 flower,每一步接着上次那个 session 说,
    哪怕上次是被 kill 掉的。

在此之前 step → session_id 只活在 ``ctx["_sessions"]`` 里,进程一退就没了 ——
磁盘上什么都在(全量 transcript、冻结的确认书和目标、代码),**丢的只是那一行映射**。

覆盖:

  1. 跑完写盘;**新进程**(新 ctx、新 Workflow、新 Runtime)读回来 → resume 同一个 session
  2. 工作区对不上(目录被拷走)→ 当没有血缘,**不报错**
  3. session 已经不在库里(删过 sessions.db)→ 同上退回,**不报错**
  4. **判定者永远是新会话** —— 这条最关键,它是目标看守的全部价值
  5. ``resume_prompt``:接续时说的话和从头开始时说的话不是同一句
  6. 显式 ``resume_from`` 的步骤,行为一字未变
  7. ``manifest.json`` 跨进程**追加**,第一次的账还在
  8. ``--new``:需求/目标/血缘一起进 archive,下一跑从头开始
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.agent import AgentSpec                        # noqa: E402
from flower.core.lineage import Lineage                        # noqa: E402
from flower.core.runtime import Runtime, StepResult            # noqa: E402
from flower.workflow.base import Step, Workflow                # noqa: E402
from flower.workflow.goal import with_goal                     # noqa: E402
from flower.core.human import HumanChannel                     # noqa: E402
from flower.workflow.starter import starter_flow, wake_state   # noqa: E402

ok = True
SPEC = AgentSpec(name="fake", instructions="")


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


class FakeRuntime:
    """有磁盘位置、但不打网络。``known`` 是"库里存在哪些 session"。"""

    def __init__(self, run_dir, workspace, known=None, script=None):
        self.run_dir, self.workspace = Path(run_dir), Path(workspace)
        self.known = set(known or [])
        self.script = list(script or [])      # [(step 名子串, text), ...]
        self.calls = []                       # [(step_name, prompt, resume), ...]
        self.on_session = None                # 真 Runtime 有它,假的也必须有

    def has_session(self, sid: str) -> bool:
        return sid in self.known

    async def run(self, spec, prompt, *, step_name=None, resume=None,
                  fork=False, on_event=None):
        name = step_name or ""
        self.calls.append((name, prompt, resume))
        text = "做完了"
        for frag, out in self.script:
            if frag in name:
                text = out
                break
        sid = resume or f"sid-{name}"
        self.known.add(sid)
        if self.on_session:               # 和真 Runtime 一样:拿到就立刻回调
            self.on_session(sid)
        return StepResult(step=name, session_id=sid, ok=True, text=text)

    def _hit(self, name: str, frag: str, exact: bool) -> bool:
        # "干活" 是 "干活·判定#1" 的**子串** —— 松匹配会把判定者算进干活,
        # 于是这个测试自己会说谎。默认精确匹配。
        return name == frag if exact else frag in name

    def resume_of(self, frag: str, *, exact: bool = True):
        return [r for (n, _, r) in self.calls if self._hit(n, frag, exact)]

    def prompt_of(self, frag: str, *, exact: bool = True):
        return [p for (n, p, _) in self.calls if self._hit(n, frag, exact)]


def flow(**kw) -> Workflow:
    return Workflow(steps=[
        Step("调研", spec=SPEC, prompt="查一下"),
        Step("干活", spec=SPEC, prompt="照需求做:全文……",
             resume_prompt="接着做。"),
    ], **kw)


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="flower-lineage-"))
    rd, ws = tmp / "runs", tmp / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------
    print("\n[1] 新进程在同一个路径接上上次")
    rt1 = FakeRuntime(rd, ws)
    await flow().run(rt1)
    check(rt1.resume_of("干活") == [None], "第一次跑:全新会话(resume=None)")

    lin = Lineage.open(rd, ws)
    check(lin.steps.get("干活") == "sid-干活", f"血缘落盘了:{lin.steps}")
    check(lin.woke == 1, f"唤醒计数 = {lin.woke}")

    # 新进程 = 新 Workflow 对象 + 新 ctx + 新 Runtime。**只有磁盘是共享的。**
    rt2 = FakeRuntime(rd, ws, known={"sid-干活", "sid-调研"})
    await flow().run(rt2)
    check(rt2.resume_of("干活") == ["sid-干活"],
          f"第二次跑:接上上次那个 session({rt2.resume_of('干活')})")
    check(Lineage.open(rd, ws).woke == 2, "唤醒计数涨到 2")

    # -----------------------------------------------------------------
    print("\n[2] 目录被拷走(工作区对不上)→ 当没有血缘,不报错")
    ws2 = tmp / "ws-copied"
    ws2.mkdir(exist_ok=True)
    shutil.copy(rd / "lineage.json", rd / "lineage.json.bak")   # 血缘文件原样在
    rt3 = FakeRuntime(rd, ws2, known={"sid-干活"})
    await flow().run(rt3)
    check(rt3.resume_of("干活") == [None],
          "路径不同 → 从头开始(那些 session_id 在新位置本来也查不到)")
    shutil.move(str(rd / "lineage.json.bak"), str(rd / "lineage.json"))

    # -----------------------------------------------------------------
    print("\n[3] session 已经不在库里 → 退回新会话,不报错")
    rt4 = FakeRuntime(rd, ws, known=set())        # 库空了(比如删过 sessions.db)
    await flow().run(rt4)
    check(rt4.resume_of("干活") == [None], "查不到就当没有,不是崩")

    # -----------------------------------------------------------------
    print("\n[4] 判定者永远是新会话 —— 这条退化了目标看守就没意义了")
    rd2 = tmp / "runs-goal"
    gp = tmp / "目标.md"
    gp.write_text("# 目标\n跑起来\n# 判定清单\n- 能跑\n", encoding="utf-8")
    ch = HumanChannel(timeout_s=0)
    work = Step("干活", spec=SPEC, prompt="做", resume_prompt="接着做")
    wf = Workflow(steps=[with_goal(work, ch, goal_path=gp, rounds=1)])

    for i in (1, 2):
        rt = FakeRuntime(rd2, ws, known={"sid-干活"},
                         script=[("判定", "结论:达成\n理由:能跑")])
        await wf.__class__(steps=wf.steps).run(rt)
        check(rt.resume_of("判定", exact=False) == [None],
              f"第 {i} 次运行:判定者 resume=None(它不该记得干活的人试了多少次)")
        if i == 1:
            check(rt.resume_of("干活") == [None], "  第 1 次:干活也是新会话")
        else:
            check(rt.resume_of("干活") == ["sid-干活"], "  第 2 次:干活接上了")
    lin2 = Lineage.open(rd2, ws)
    check("判定" not in lin2.steps,
          f"血缘里根本没有判定者({list(lin2.steps)})—— 它不是 Step")
    check(lin2.steps.get("干活") == "sid-干活",
          f"**干活的血缘没被判定者顶掉**(={lin2.steps.get('干活')})—— "
          "钩子必须在 gate 之前摘掉,否则判定者用同一个 Runtime 会把自己写进去")

    # -----------------------------------------------------------------
    print("\n[4b] 血缘钩子只罩 runtime.run,gate 期间必须摘掉")
    rd_h = tmp / "hook"
    seen_in_gate = []
    hook_rt = FakeRuntime(rd_h, ws)

    def gate_peek(result, ctx):
        seen_in_gate.append(hook_rt.on_session)
        return True

    await Workflow(steps=[Step("干活", spec=SPEC, prompt="做", gate=gate_peek)]).run(hook_rt)
    check(seen_in_gate == [None],
          f"gate 里看到的 on_session 是 {seen_in_gate} —— 必须是 None")
    check(hook_rt.on_session is None, "跑完也摘干净了")
    check(Lineage.open(rd_h, ws).steps.get("干活") == "sid-干活",
          "而血缘照样写上了(拿到 session_id 的那一刻就写,不等步骤跑完)")

    print("\n[5] resume_prompt:接续时说的不是从头开始那句")
    check("照需求做" in rt1.prompt_of("干活")[0], "第一次:发的是完整 prompt")
    check(rt2.prompt_of("干活")[0] == "接着做。", "接续:发的是 resume_prompt")
    rd3 = tmp / "runs-noresume"
    plain = Workflow(steps=[Step("干活", spec=SPEC, prompt="照需求做:全文……")])
    await plain.run(FakeRuntime(rd3, ws))
    rtp = FakeRuntime(rd3, ws, known={"sid-干活"})
    await Workflow(steps=[Step("干活", spec=SPEC, prompt="照需求做:全文……")]).run(rtp)
    check(rtp.prompt_of("干活")[0].startswith("照需求做"),
          "没给 resume_prompt 就沿用 prompt(不是发空串)")

    # -----------------------------------------------------------------
    print("\n[6] 显式 resume_from 的步骤,行为一字未变")
    rd4 = tmp / "runs-chain"
    chain = lambda: Workflow(steps=[                                    # noqa: E731
        Step("方案", spec=SPEC, prompt="想"),
        Step("实现", spec=SPEC, prompt="做", resume_from="方案"),
    ])
    rtc = FakeRuntime(rd4, ws)
    await chain().run(rtc)
    check(rtc.resume_of("实现") == ["sid-方案"], "实现 resume 的是本次运行的方案")
    rtc2 = FakeRuntime(rd4, ws, known={"sid-方案", "sid-实现"})
    await chain().run(rtc2)
    check(rtc2.resume_of("实现") == ["sid-方案"],
          "第二次跑仍然跟着方案走,不被血缘里的「实现」抢过去")

    # -----------------------------------------------------------------
    print("\n[7] manifest 跨进程追加(以前第二次跑会把第一次冲掉)")
    rd5 = tmp / "runs-manifest"
    a = Runtime(workspace=ws, run_dir=rd5)
    a.results.append(StepResult(step="第一次", session_id="s1", ok=True, cost_usd=1.0))
    a._persist()
    a.close()
    b = Runtime(workspace=ws, run_dir=rd5)
    b.results.append(StepResult(step="第二次", session_id="s2", ok=True, cost_usd=2.0))
    b._persist()
    b._persist()                     # 同一进程内重复写不该翻倍
    b.close()
    rows = json.loads((rd5 / "manifest.json").read_text(encoding="utf-8"))
    check([r["step"] for r in rows] == ["第一次", "第二次"],
          f"两次运行的行都在:{[r['step'] for r in rows]}")
    check(len({r["run"] for r in rows}) >= 1 and all("run" in r for r in rows),
          "每行带 run 字段,能按运行分组")

    # -----------------------------------------------------------------
    print("\n[8] --new:上一段收进 archive,下一跑从头开始")
    ws3 = tmp / "ws-new"
    ws3.mkdir(exist_ok=True)
    rd6 = tmp / "runs-new"
    wf1 = starter_flow("做个 X", workspace=ws3, run_dir=rd6, timeout_s=0)
    notes = wf1.workbench.notes
    (notes / "需求.md").write_text(
        "# 目标\n做个 X\n# 验收标准\n跑得起来\n# 边界\n无\n# 未知与假设\n无\n",
        encoding="utf-8")
    (notes / "目标.md").write_text("# 目标\n做个 X\n# 判定清单\n- 跑得起来\n",
                                   encoding="utf-8")
    Lineage.open(rd6, ws3).remember("干活", "sid-old")
    check(wake_state(ws3, run_dir=rd6)["waking"] is True, "确认书在 → 认得出是唤醒")

    starter_flow("另一件完全不同的事", workspace=ws3, run_dir=rd6,
                 new=True, timeout_s=0)
    st = wake_state(ws3, run_dir=rd6)
    check(st["waking"] is False, "--new 之后:不再是唤醒,从头开始")
    check(st["steps"] == {}, "血缘清空")
    arch = sorted((notes / "archive").glob("*/*"))
    check({p.name for p in arch} == {"需求.md", "目标.md", "lineage.json"},
          f"三样都进了档案(移动,不是删除):{[p.name for p in arch]}")

    # -----------------------------------------------------------------
    print("\n[9] 唤醒时说的新需求 → 追加进确认书 + 触发重推目标")
    ws4 = tmp / "ws-wake"
    ws4.mkdir(exist_ok=True)
    rd7 = tmp / "runs-wake"
    w = starter_flow("做个 X", workspace=ws4, run_dir=rd7, timeout_s=0)
    brief = w.workbench.notes / "需求.md"
    brief.write_text("# 目标\n做个 X\n# 验收标准\n跑\n# 边界\n无\n# 未知与假设\n无\n",
                     encoding="utf-8")
    (w.workbench.notes / "目标.md").write_text(
        "# 目标\n做个 X\n# 判定清单\n- 跑得起来\n", encoding="utf-8")
    w2 = starter_flow("顺便支持配置文件", workspace=ws4, run_dir=rd7, timeout_s=0)
    check("顺便支持配置文件" in brief.read_text(encoding="utf-8"),
          "这句话追加进了确认书(不落盘就活不过步骤边界)")
    goal_names = [s.name for s in w2.steps]
    check(goal_names == ["确认需求", "设定目标", "干活"], f"步骤齐全:{goal_names}")
    check(w2.steps[1].when({}) is True,
          "确认书变了 → 设定目标 always_set,重新推清单(否则新需求不进判定)")
    w3 = starter_flow("", workspace=ws4, run_dir=rd7, timeout_s=0)
    check(w3.steps[1].when({}) is False,
          "什么都不说地唤醒 → 目标照旧,不白花那一次钱")
    check(w2.steps[-1].resume_prompt is not None, "干活那步带着 resume_prompt")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'✓ 接续全部通过' if ok else '✗ 有失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
