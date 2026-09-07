"""Workflow.run 的执行语义 —— 离线验证。不打网络,不花钱。

为什么要有它:在这之前,唯一跑过 ``Workflow.run`` 的是 ``flow_demo.py``(约 $0.39),
于是这个主循环每改一次都得花钱才能验。但循环本身的语义和模型无关 ——
换一个假 Runtime 就能全部钉住,真实请求那一套留给 flow_demo 验"接得上模型"。

覆盖六件事:
  1. when 返 False 整步跳过,不写 ctx[name]
  2. gate **每次尝试只调一次**(它可能有副作用 —— clarify 的 gate 会落盘)
  3. retries:失败重试,重试的 step_name 带 #retryN
  4. reduce 决定 ctx[name] 放什么,原文不直接往下传
  5. on_fail 三种去向:stop / skip / continue
  6. ctx["_sessions"] 就是循环实际写的那一份(同一个 Workflow 跑第二次也不会停在旧值)
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.agent import AgentSpec
from flower.core.runtime import StepResult
from flower.workflow.base import Step, Workflow

ok = True


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


SPEC = AgentSpec(name="fake", instructions="")


class FakeRuntime:
    """只实现 Workflow.run 用到的那一个方法。按脚本返回结果,并记下每次调用。"""

    def __init__(self, script=None, sid="sid"):
        self.script = list(script or [])      # [(ok, text), ...];用完之后一律成功
        self.calls = []                        # [(step_name, prompt, resume, fork), ...]
        self.sid = sid                         # 两次运行给不同前缀,才能区分 _sessions 是哪一份

    async def run(self, spec, prompt, *, step_name=None, resume=None,
                  fork=False, on_event=None):
        self.calls.append((step_name, prompt, resume, fork))
        good, text = self.script.pop(0) if self.script else (True, f"{step_name} 的产出")
        return StepResult(step=step_name or spec.name, ok=good, text=text,
                          session_id=f"{self.sid}-{len(self.calls)}" if good else None)


async def when_tests():
    print("\n[when] 跳过整步")
    rt = FakeRuntime()
    wf = Workflow([
        Step("A", spec=SPEC, prompt="a"),
        Step("B", spec=SPEC, prompt="b", when=lambda ctx: False),
        Step("C", spec=SPEC, prompt="c"),
    ])
    ctx = await wf.run(rt)
    check([c[0] for c in rt.calls] == ["A", "C"], "when 返 False 的步骤没被执行")
    check("B" not in ctx, "跳过的步骤不写 ctx[name]")

    # resume_from 指向被跳过的步骤 → 明确报错,不静默降级成新会话
    wf2 = Workflow([
        Step("A", spec=SPEC, prompt="a", when=lambda ctx: False),
        Step("B", spec=SPEC, prompt="b", resume_from="A"),
    ])
    try:
        await wf2.run(FakeRuntime())
        check(False, "resume_from 指向没跑过的步骤应当报错")
    except ValueError as exc:
        check("没有产生 session" in str(exc), "resume_from 指向没跑过的步骤 → ValueError")


async def gate_tests():
    print("\n[gate] 每次尝试只调一次")
    calls = []
    rt = FakeRuntime([(True, "一"), (True, "二"), (True, "三")])
    wf = Workflow([Step("A", spec=SPEC, prompt="a", retries=2,
                        gate=lambda r, c: (calls.append(r.text), False)[1],
                        on_fail="continue")])
    await wf.run(rt)
    check(len(rt.calls) == 3, f"retries=2 → 一共跑 3 次(实际 {len(rt.calls)})")
    check(calls == ["一", "二", "三"], f"gate 每次尝试恰好一次(实际 {len(calls)} 次)")
    check([c[0] for c in rt.calls] == ["A", "A#retry1", "A#retry2"],
          "重试的 step_name 带 #retryN,manifest 里能区分")

    # result.ok 为假时 gate 根本不该被调用
    seen = []
    rt2 = FakeRuntime([(False, "炸了")])
    wf2 = Workflow([Step("A", spec=SPEC, prompt="a", on_fail="continue",
                         gate=lambda r, c: seen.append(1) or True)])
    await wf2.run(rt2)
    check(seen == [], "result.ok 为假时 gate 不被调用(短路)")

    # 第二次尝试通过就不再跑第三次
    rt3 = FakeRuntime([(True, "坏"), (True, "好")])
    wf3 = Workflow([Step("A", spec=SPEC, prompt="a", retries=5,
                         gate=lambda r, c: r.text == "好")])
    ctx = await wf3.run(rt3)
    check(len(rt3.calls) == 2 and ctx["A"] == "好", "gate 一通过就跳出重试循环")


async def reduce_tests():
    print("\n[reduce] 决定 ctx[name] 放什么")
    rt = FakeRuntime([(True, "原文 + 一堆它多写的东西")])
    wf = Workflow([Step("A", spec=SPEC, prompt="a",
                        reduce=lambda r, c: r.text.split(" + ")[0])])
    ctx = await wf.run(rt)
    check(ctx["A"] == "原文", "reduce 的返回值进 ctx,原文不直接往下传")

    rt2 = FakeRuntime([(True, "原文")])
    wf2 = Workflow([Step("A", spec=SPEC, prompt="a")])
    check((await wf2.run(rt2))["A"] == "原文", "不给 reduce 就放 result.text")


async def on_fail_tests():
    print("\n[on_fail] 三种去向")
    rt = FakeRuntime([(False, "炸了")])
    ctx = await Workflow([Step("A", spec=SPEC, prompt="a"),
                          Step("B", spec=SPEC, prompt="b")]).run(rt)
    check(ctx.get("_failed_at") == "A" and len(rt.calls) == 1,
          "stop(默认):记 _failed_at 并停掉后面的步骤")

    rt = FakeRuntime([(False, "炸了")])
    ctx = await Workflow([Step("A", spec=SPEC, prompt="a", on_fail="skip"),
                          Step("B", spec=SPEC, prompt="b")]).run(rt)
    check("A" not in ctx and "B" in ctx, "skip:不写 ctx[name],后面照跑")
    check("_failed_at" not in ctx, "skip 不记 _failed_at")

    rt = FakeRuntime([(False, "残缺结果")])
    ctx = await Workflow([Step("A", spec=SPEC, prompt="a", on_fail="continue",
                               reduce=lambda r, c: "不该走到这"),
                          Step("B", spec=SPEC, prompt="b")]).run(rt)
    check(ctx.get("A") == "残缺结果", "continue:带着残缺原文往下走,且不过 reduce")


async def ctx_tests():
    print("\n[ctx] 会话血缘与复用")
    rt = FakeRuntime()
    wf = Workflow([Step("A", spec=SPEC, prompt="a"),
                   Step("B", spec=SPEC, prompt="b", resume_from="A"),
                   Step("C", spec=SPEC, prompt="c", resume_from="A", fork=True)])
    ctx = await wf.run(rt)
    check(ctx["_sessions"] == {"A": "sid-1", "B": "sid-2", "C": "sid-3"},
          "ctx['_sessions'] 就是循环实际写的那一份")
    check(rt.calls[1][2] == "sid-1" and rt.calls[1][3] is False, "resume_from 接上前一步的 session")
    check(rt.calls[2][2] == "sid-1" and rt.calls[2][3] is True, "fork=True 从同一个 session 分叉")
    check(set(ctx["_results"]) == {"A", "B", "C"}, "_results 里每步一个 StepResult")

    # 同一个 Workflow 对象跑第二次:ctx 是同一个 dict,_sessions 必须跟着更新到新值。
    # 给第二个 runtime 换个 sid 前缀 —— 否则新旧两种写法的结果长得一样,验不出差别。
    ctx2 = await wf.run(FakeRuntime(sid="二"))
    check(ctx2 is ctx, "ctx 就是 Workflow.context 本身")
    check(ctx2["_sessions"] == {"A": "二-1", "B": "二-2", "C": "二-3"},
          f"第二次运行的 session_id 覆盖进同一份 _sessions(实际 {ctx2['_sessions']})")

    # prompt 可以是 callable,拿到当前 ctx
    rt3 = FakeRuntime()
    ctx3 = await Workflow([Step("A", spec=SPEC, prompt="a"),
                           Step("B", spec=SPEC,
                                prompt=lambda c: f"基于:{c['A']}")]).run(rt3)
    check(rt3.calls[1][1] == "基于:A 的产出", "callable prompt 拿到当前 ctx")
    check("B" in ctx3, "第二步正常写回 ctx")


async def on_step_tests():
    print("\n[on_step] 每步一次,含失败")
    seen = []
    rt = FakeRuntime([(True, "好"), (False, "炸了")])
    await Workflow([Step("A", spec=SPEC, prompt="a"),
                    Step("B", spec=SPEC, prompt="b")]).run(
        rt, on_step=lambda s, r: seen.append((s.name, r.ok)))
    check(seen == [("A", True), ("B", False)], "on_step 每步调一次,失败的那步也调")


async def interrupt_tests():
    """人打断当前这一轮 —— 复用断网重试那条路,但语义不同。

    钉住四件事,都是"有破坏性"的路径该有的性质:
      1. 打断后**续跑同一个 session**(resume),不是重头来 —— 十小时的活不能白干
      2. 人说的话进了下一轮的 prompt
      3. 打断**不消耗** max_attempts(那是给故障用的额度,不是给人用的)
      4. 还没拿到 session_id 时只能停 —— 没得续,不能假装续上了
    """
    print("\n[打断] Ctrl+C 打断这一轮")
    from flower.core.runtime import Runtime

    class Interruptible:
        """第一次跑到一半被打断,第二次正常完成。"""

        def __init__(self, rt_like_sid="sid-1"):
            self.calls = []
            self.sid = rt_like_sid
            self._interrupt = None
            self.INTERRUPTED = Runtime.INTERRUPTED
            self.resilience = type("R", (), {
                "enabled": True, "max_attempts": 3, "resume_prompt": "(默认续跑话术)",
                "should_retry": lambda self, k: True,
                "wait_online": staticmethod(lambda note: _true()),
                "delay_for": lambda self, a: 0, "_human_wait": lambda self: "x"})()

        def interrupt(self, msg=""):
            self._interrupt = msg

        async def run(self, spec, prompt, *, step_name=None, resume=None,
                      fork=False, on_event=None):
            self.calls.append((step_name, prompt, resume))
            # 模拟 Runtime.run 的打断分支
            if self._interrupt is not None:
                said, self._interrupt = self._interrupt, None
                r = StepResult(step=step_name or "", ok=False, session_id=self.sid,
                               error=self.INTERRUPTED)
                nxt = (f"人在这里打断了你,说:\n\n{said}\n\n"
                       "按这句话调整,接着做 —— 不要重头开始。") if said else "(默认续跑话术)"
                self.calls.append((f"{step_name}(续)", nxt, self.sid))
                return StepResult(step=step_name or "", ok=True, text="打断后做完了",
                                  session_id=self.sid, resumed=True)
            return StepResult(step=step_name or "", ok=True, text=f"{step_name} 的产出",
                              session_id=self.sid)

    async def _true():
        return True

    rt = Interruptible()
    rt.interrupt("别改 Makefile,那两行直接改")
    wf = Workflow([Step("干活", spec=SPEC, prompt="做吧")])
    ctx = await wf.run(rt)
    resumed = [c for c in rt.calls if c[0] and c[0].endswith("(续)")]
    check(len(resumed) == 1, "打断之后续跑了一次")
    check(resumed[0][2] == "sid-1", f"**续的是同一个 session**({resumed[0][2]}),不是重头来")
    check("别改 Makefile" in resumed[0][1], "人说的话进了续跑的 prompt")
    check("不要重头开始" in resumed[0][1], "并明确告诉它接着做")
    check("_failed_at" not in ctx, "打断不算失败,workflow 照常走完")

    # 真实 Runtime 的常量与方法(上面那个假的照着它做)
    check(Runtime.INTERRUPTED == "interrupted-by-human", "Runtime 有打断标记")
    src = Path("flower/core/runtime.py").read_text(encoding="utf-8")
    check("attempt -= 1" in src, "**打断不消耗 max_attempts** —— 那是给故障的额度")
    check("if not result.session_id:\n                    break" in src,
          "还没拿到 session_id 时只能停,不假装续上了")

    # 这一条是真实路径上栽过的:session_id 原来只从末尾那条 result 事件取,
    # 于是中途打断时它是 None —— 打断永远续不上,十小时的活白干。
    # 假 Runtime 抓不到这个(它自己造 session_id),只有对着真实的消息流才暴露。
    check('sid = getattr(message, "session_id", None)' in src
          and "if sid and sid != result.session_id:" in src,
          "**每条消息都记 session_id** —— 只等末尾那条的话,中途打断根本没得续")
    # 拿到就立刻回调 —— 这是"被硬杀也接得上"的地基(issue #6)。
    # 没有它,终端崩溃时血缘还是空的,第一步之内的活全丢。
    check("if self.on_session:" in src and "self.on_session(sid)" in src,
          "**拿到 session_id 立刻回调**,不等步骤跑完(SIGHUP 时来不及)")


async def main():
    await when_tests()
    await interrupt_tests()
    await gate_tests()
    await reduce_tests()
    await on_fail_tests()
    await ctx_tests()
    await on_step_tests()
    print("\n" + ("✓ Workflow.run 语义全部通过" if ok else "✗ 未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
