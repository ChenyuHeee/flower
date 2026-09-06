"""目标看守 —— 离线验证。**不打网络,不花钱。**

判定这一层的语义全部和模型无关:判定者说什么由假 Runtime 决定,
框架怎么反应才是要钉住的东西。覆盖:

  1. Goal / Verdict 的解析(含"只回一个 0/1"和"话说得含糊")
  2. 达成 → 往下走;未达成 → **续跑同一个 session**、prompt 换成 feedback
  3. 判定含糊(``ok=False``)**一律按未达成** —— 不能让"看起来可以"把活收掉
  4. 无法达成 → 问人;三种回答分别对应 通过 / 改目标 / 再来一轮
  5. 无法达成 + 没人应答 → ``StepAbort``:**立刻停,不消耗剩余轮数**
  6. rounds 是总轮数(``rounds=3`` → 最多三轮活)
  7. goal_step:已有目标就跳过,但照样灌 ctx
  8. gate 拿不到 Runtime 时不许假装通过
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.agent import AgentSpec                      # noqa: E402
from flower.core.goal import (ACHIEVED, NOT_YET, UNREACHABLE,  # noqa: E402
                              Goal, Verdict)
from flower.core.human import HumanChannel                    # noqa: E402
from flower.core.runtime import StepResult                    # noqa: E402
from flower.workflow.base import Step, StepAbort, Workflow    # noqa: E402
from flower.workflow.goal import (GOAL_KEY, ROUND_KEY, VERDICT_KEY,  # noqa: E402
                                  goal_step, with_goal)

ok = True


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


SPEC = AgentSpec(name="fake", instructions="")

GOAL_MD = """\
# 目标
让 conv.py 把 md 转成 html。
# 判定清单
- 跑 `python conv.py a.md` 产出 a.html
- 输出含 <h1>
"""


class FakeRuntime:
    """按脚本回答。判定者和干活的人共用这一个,靠 step_name 区分。"""

    def __init__(self, script=None):
        self.script = list(script or [])       # [(step_name_子串, ok, text), ...]
        self.calls = []                        # [(step_name, prompt, resume), ...]

    async def run(self, spec, prompt, *, step_name=None, resume=None,
                  fork=False, on_event=None):
        self.calls.append((step_name or "", prompt, resume))
        for i, (frag, good, text) in enumerate(self.script):
            if frag in (step_name or ""):
                self.script.pop(i)
                return StepResult(step=step_name or "", ok=good, text=text,
                                  session_id=f"sid{len(self.calls)}" if good else None)
        return StepResult(step=step_name or "", ok=True, text="(默认产出)",
                          session_id=f"sid{len(self.calls)}")


def work_step():
    return Step("干活", spec=SPEC, prompt="做吧")


async def test_parse():
    print("\n[1] Goal / Verdict 解析")
    g = Goal.parse(GOAL_MD)
    check(g.complete() and len(g.checks) == 2, f"目标齐全,清单 {len(g.checks)} 条")
    check(not Goal.parse("# 目标\n只有目标").complete(), "缺判定清单 → 不齐全")
    for text, want in [("结论:达成", ACHIEVED), ("结论:未达成", NOT_YET),
                       ("# 结论\n无法达成", UNREACHABLE), ("1", ACHIEVED), ("0", NOT_YET)]:
        check(Verdict.parse(text).state == want, f"{text[:12]!r} → {want}")
    v = Verdict.parse("看起来应该可以吧")
    check(not v.ok and not v.achieved, "话说得含糊 → ok=False 且不算达成")
    check("差在哪" not in Verdict.parse("结论:未达成\n理由:少了列表\n未通过:- 输出含 <h1>"
                                       ).feedback() or True, "feedback 能生成")
    fb = Verdict.parse("结论:未达成\n理由:少了列表\n未通过:\n- 输出含 <h1>").feedback()
    check("少了列表" in fb and "<h1>" in fb and "接着做" in fb,
          "feedback 带上理由、没通过项、以及「接着做」")


async def test_achieved():
    print("\n[2] 判定达成 → 一轮就走")
    rt = FakeRuntime([("干活·判定", True, "结论:达成")])
    wf = Workflow([with_goal(work_step(), HumanChannel(timeout_s=0),
                             goal_path="/tmp/_nonexistent_goal.md", rounds=3)],
                  context={GOAL_KEY: Goal.parse(GOAL_MD)})
    ctx = await wf.run(rt)
    work = [c for c in rt.calls if c[0] == "干活"]
    check(len(work) == 1, f"干活只跑了 {len(work)} 轮")
    check(ctx.get("干活") is not None and "_failed_at" not in ctx, "步骤通过,workflow 未中止")
    check(ctx[VERDICT_KEY].achieved and ctx[ROUND_KEY] == 1, "verdict 与轮数记进了 ctx")


async def test_not_yet_resumes():
    print("\n[3] 未达成 → 续跑同一个 session,prompt 换成 feedback")
    rt = FakeRuntime([
        ("干活·判定", True, "结论:未达成\n理由:列表没处理\n未通过:\n- 输出含 <h1>"),
        ("干活·判定", True, "结论:达成"),
    ])
    wf = Workflow([with_goal(work_step(), HumanChannel(timeout_s=0),
                             goal_path="/tmp/_nonexistent_goal.md", rounds=3)],
                  context={GOAL_KEY: Goal.parse(GOAL_MD)})
    ctx = await wf.run(rt)
    work = [c for c in rt.calls if c[0].startswith("干活") and "判定" not in c[0]]
    check(len(work) == 2, f"干活跑了 {len(work)} 轮")
    check(work[1][0] == "干活#round2", f"第二轮命名是 round 而不是 retry:{work[1][0]}")
    check(work[1][2] is not None, f"第二轮 resume={work[1][2]} —— 续跑,不是重头来")
    check("列表没处理" in work[1][1] and "接着做" in work[1][1],
          "第二轮的 prompt 是判定反馈(差在哪),不是原始任务")
    check("_failed_at" not in ctx and ctx[ROUND_KEY] == 2, "第二轮达成,整步通过")


async def test_vague_counts_as_not_yet():
    print("\n[4] 判定含糊一律按未达成(不能让「看起来可以」收活)")
    rt = FakeRuntime([("干活·判定", True, "嗯,我觉得差不多了")])
    wf = Workflow([with_goal(work_step(), HumanChannel(timeout_s=0),
                             goal_path="/tmp/_nonexistent_goal.md", rounds=1)],
                  context={GOAL_KEY: Goal.parse(GOAL_MD)})
    ctx = await wf.run(rt)
    check(ctx.get("_failed_at") == "干活", "含糊 → 未达成 → 轮数用完 → 中止")
    check("没给出明确结论" in (ctx[VERDICT_KEY].reason or ""), "理由里说明了是判定不明")


async def test_unreachable_asks():
    print("\n[5] 无法达成 → 问人,三种回答三种走向")

    async def run_with(answer_seq, rounds=2):
        ch = HumanChannel(timeout_s=30)
        rt = FakeRuntime([("干活·判定", True, "结论:无法达成\n理由:缺了外部依赖"),
                          ("干活·判定", True, "结论:达成")])
        seq = list(answer_seq)

        async def answerer():
            while seq:
                await asyncio.sleep(0.02)
                pend = ch.pending()
                if pend:
                    ch.answer(pend[0].id, seq.pop(0))

        wf = Workflow([with_goal(work_step(), ch, goal_path=gp, rounds=rounds)],
                      context={GOAL_KEY: Goal.parse(GOAL_MD)})
        task = asyncio.create_task(answerer())
        ctx = await wf.run(rt)
        task.cancel()
        return ctx, rt, ch

    gp = Path("/tmp/_goal_amend_test.md")
    gp.unlink(missing_ok=True)

    ctx, rt, _ = await run_with(["接受这个结果,就这样往下走"])
    work = [c for c in rt.calls if c[0].startswith("干活") and "判定" not in c[0]]
    check("_failed_at" not in ctx and len(work) == 1, "选「接受」→ 通过,不再跑一轮")

    ctx, rt, _ = await run_with(["你判断错了,继续做"])
    work = [c for c in rt.calls if c[0].startswith("干活") and "判定" not in c[0]]
    check(len(work) == 2 and "_failed_at" not in ctx, "选「你判断错了」→ 再来一轮")
    # 断言要落在**第二轮的 prompt** 上:ctx[VERDICT_KEY] 会被第二轮判定覆盖,
    # 而"人的推翻有没有真的传到干活那个人"才是这条分支的意义所在。
    check("判断有误" in work[1][1] and "继续做" in work[1][1],
          "人的推翻传到了下一轮的 prompt 里")

    ctx, rt, _ = await run_with(["修改目标", "改成只支持标题"])
    check(gp.is_file(), "选「修改目标」→ 新目标落盘")
    txt = gp.read_text(encoding="utf-8")
    check("已修改" in txt and "只支持标题" in txt, "改动是**追加**,原目标还在(看得见改了什么)")
    gp.unlink(missing_ok=True)


async def test_unreachable_nobody():
    print("\n[6] 无法达成 + 没人应答 → 立刻停,不消耗剩余轮数")
    rt = FakeRuntime([("干活·判定", True, "结论:无法达成\n理由:需求自相矛盾")])
    wf = Workflow([with_goal(work_step(), HumanChannel(timeout_s=0),   # 0 = 不等人
                             goal_path="/tmp/_nonexistent_goal.md", rounds=5)],
                  context={GOAL_KEY: Goal.parse(GOAL_MD)})
    ctx = await wf.run(rt)
    work = [c for c in rt.calls if c[0].startswith("干活") and "判定" not in c[0]]
    check(len(work) == 1, f"rounds=5 但只跑了 {len(work)} 轮 —— 没空转")
    check(ctx.get("_failed_at") == "干活", "整步失败")
    check("无人应答" in ctx.get("_aborted", ""), f"_aborted 记了原因:{ctx.get('_aborted','')[:26]}…")


async def test_rounds_bound():
    print("\n[7] rounds 是总轮数")
    for rounds, want in ((1, 1), (3, 3)):
        rt = FakeRuntime([("干活·判定", True, "结论:未达成\n理由:还差")] * 6)
        wf = Workflow([with_goal(work_step(), HumanChannel(timeout_s=0),
                                 goal_path="/tmp/_nonexistent_goal.md", rounds=rounds)],
                      context={GOAL_KEY: Goal.parse(GOAL_MD)})
        ctx = await wf.run(rt)
        work = [c for c in rt.calls if c[0].startswith("干活") and "判定" not in c[0]]
        check(len(work) == want, f"rounds={rounds} → 干活 {len(work)} 轮(期望 {want})")
        check(ctx.get("_failed_at") == "干活", f"rounds={rounds} 用完仍未达成 → 中止")


async def test_goal_step():
    print("\n[8] goal_step:设定、冻结、跳过")
    gp = Path("/tmp/_goal_step_test.md")
    gp.unlink(missing_ok=True)
    ch = HumanChannel(timeout_s=0)

    rt = FakeRuntime([("设定目标", True, GOAL_MD)])
    wf = Workflow([goal_step(ch, goal_path=gp)], context={"确认需求": "## 目标\n做个 X"})
    ctx = await wf.run(rt)
    check(gp.is_file(), "目标冻结到磁盘")
    check(isinstance(ctx.get(GOAL_KEY), Goal) and ctx[GOAL_KEY].complete(),
          "ctx 里是解析好的 Goal")
    check("判定清单" in ctx.get("设定目标", ""), "ctx[name] 是可插进 prompt 的块")
    check("做个 X" in rt.calls[0][1], "prompt 里带上了确认书")

    rt2 = FakeRuntime()
    wf2 = Workflow([goal_step(ch, goal_path=gp)])
    ctx2 = await wf2.run(rt2)
    check(not [c for c in rt2.calls if "设定目标" in c[0]], "目标已存在 → 跳过,不再设一遍")
    check(isinstance(ctx2.get(GOAL_KEY), Goal), "跳过时仍把目标灌进 ctx")

    rt3 = FakeRuntime([("设定目标", True, "# 目标\n只有目标没有清单")])
    wf3 = Workflow([goal_step(ch, goal_path=gp, always_set=True)],
                   context={"确认需求": "x"})
    ctx3 = await wf3.run(rt3)
    check(ctx3.get("_failed_at") == "设定目标", "清单缺失 → gate 不放行")
    gp.unlink(missing_ok=True)


async def test_no_runtime():
    print("\n[9] gate 拿不到 Runtime 时不许假装通过")
    step = with_goal(work_step(), HumanChannel(timeout_s=0),
                     goal_path="/tmp/_nonexistent_goal.md")
    try:
        await step.gate(StepResult(step="干活", ok=True, text="做完了"), {})
        check(False, "应当抛 StepAbort")
    except StepAbort as e:
        check("Runtime" in str(e), f"抛 StepAbort 并说明原因({str(e)[:24]}…)")


async def main():
    for t in (test_parse, test_achieved, test_not_yet_resumes,
              test_vague_counts_as_not_yet, test_unreachable_asks,
              test_unreachable_nobody, test_rounds_bound, test_goal_step,
              test_no_runtime):
        await t()
    print(f"\n{'✓ 目标看守全部通过' if ok else '✗ 有失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
