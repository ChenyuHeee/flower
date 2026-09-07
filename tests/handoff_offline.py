"""换代 —— 离线验证。**不打网络,不花钱。**

钉住的是"上下文快满了写交接换新会话,而不是 compact"这件事的机制:

    到阈值 → 同一个 session 写一份交接 → 冻结到磁盘 → **新会话**接手

用户选的两条,都在这里钉死:
  * **全自动**:不停下来等人
  * **关掉 auto-compact**:换代是唯一机制 —— 所以**降级路径是命**,没有兵底

覆盖:

  1. Handoff 解析:五段、别名、围栏里的假标题、complete() 只认必填那两段
  2. 阈值只看**主线程**:subagent 的上下文再大也不逼主会话换代
  3. 换代一轮 = 同一 session 写交接 → 新会话(resume=None),prompt 是交接
  4. 换代不吃重试额度
  5. **写交接失败 → 降级交接,照样换代**(停在这里就等于撞窗口)
  6. retired 记下烧掉的 session;对外的 session_id 是**接班人**
  7. 水位每一步归零 —— 上一步在 150K 收尾,下一步不能一开局就换代
  8. 开着换代 → 强制 DISABLE_AUTO_COMPACT;spec 显式给了 compact 就不覆盖
  9. 上一代的交接进 notes/archive/交接/
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.agent import (AgentSpec, CompactPolicy,          # noqa: E402
                               HandoffPolicy, default_window)
from flower.core.events import Event                                    # noqa: E402
from flower.core.guard import spill_guard                               # noqa: E402
from flower.core.handoff import (DEGRADED, Handoff, degraded,   # noqa: E402
                                 is_overflow)
from flower.core.runtime import Runtime, StepResult                     # noqa: E402
from flower.core.workbench import Workbench                             # noqa: E402

ok = True
SPEC = AgentSpec(name="fake", instructions="")

FULL = """\
先说点无关的。
## 现在在做什么
给 Makefile 加 macOS 垫片头。
## 已经定下的
不改业务源码 —— 用户说过边界。
```make
## 下一步 这是代码块里的假标题,不该被解析走
```
## 走不通的路
- -D_ANSI_SOURCE:会把别的宏一起关掉
- 改 include 顺序:宏在原型之后定义,无效
## 下一步
在干净 clone 上跑 make 验证 shim。
## 现场
src/proc.cpp, Makefile
"""


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


class Fake:
    """按脚本回答。``ctx`` 是每一轮报出来的上下文规模。"""

    def __init__(self, script):
        self.script = list(script)   # [(text, ctx, sub), ...] sub=True 表示 subagent
        self.turns = 0

    def messages(self):
        for text, ctx, sub in self.script:
            yield text, ctx, sub


async def drive(rt: Runtime, spec, prompt, plan, *, on_event=None, step="干活"):
    """替掉 Runtime._attempt:按 plan 逐轮喂事件,不打网络。

    plan 是 [(轮次事件列表, 结束方式), ...],每次 _attempt 消耗一项。
    """
    calls = []
    it = iter(plan)

    async def fake_attempt(sp, pr, result, *, resume, fork, resume_at, on_event):
        calls.append({"prompt": pr, "resume": resume, "step": result.step})
        try:
            evs, text, sid, ok_ = next(it)
        except StopIteration:
            result.ok, result.text = True, "收工"
            return
        result.session_id = sid
        for ev in evs:
            if oe := on_event:
                oe(ev)
            if (n := ev.payload.get("context")) and not ev.payload.get("subagent"):
                rt._ctx = max(rt._ctx, int(n))
                result.context = rt._ctx
                rt._maybe_warn(on_event, result.step)
            # 阈值判定:真实代码在下一条消息的边界上做,这里等价地在每轮末尾做
            if rt.handoff.enabled and rt._ctx >= rt.handoff.at and result.session_id:
                result.error, result.ok = rt.HANDOFF_DUE, False
                return
        result.text, result.ok = text, ok_
        result.error = None if ok_ else "boom"

    rt._attempt = fake_attempt                       # type: ignore[method-assign]
    res = await rt.run(spec, prompt, step_name=step, on_event=on_event)
    return res, calls


def ctx_ev(n: int, *, sub: bool = False) -> Event:
    return Event("text", text="…", payload={"context": n, "subagent": sub})


def runtime(tmp: Path, *, window=40_000, headroom=25_000, bench=True) -> Runtime:
    wb = Workbench(tmp / "ws", home=tmp / "bench").ensure() if bench else False
    return Runtime(workspace=tmp / "ws", run_dir=tmp / "runs", workbench=wb,
                   handoff=HandoffPolicy(window=window, headroom=headroom))


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="flower-handoff-"))

    print("\n[1] Handoff 解析")
    h = Handoff.parse(FULL, step="干活")
    check(h.complete(), f"五段解析齐全(缺:{h.missing()})")
    check("干净 clone" in h.next, "下一步取到了")
    check("假标题" not in h.decided and "假标题" not in h.next,
          "围栏代码块里的假标题没有把解析带偏")
    check(len([x for x in h.deadends.splitlines() if x.strip()]) == 2, "走不通的路两条")
    check(not Handoff.parse("## 现在在做什么\n在跑测试").complete(),
          "只有「现在在做什么」→ 不完整(还缺下一步)")
    check(Handoff.parse("## 现在在做什么\n在跑\n## 下一步\n跑完看结果").complete(),
          "必填只有那两段 —— 硬要求「走不通的路」非空会逼出编造")
    check("你在接手一段还没干完的活" in h.prompt_block(),
          "prompt_block 开门见山说明「你是接手的人」")

    print("\n[2] 阈值只看主线程")
    rt = runtime(tmp / "a")
    at = rt.handoff.at
    res, calls = await drive(rt, SPEC, "干活去", [
        ([ctx_ev(at + 5_000, sub=True)], "做完了", "s1", True),   # subagent 报的,不算
    ])
    check(res.retired == [], f"subagent 上下文 {at + 5000} 也不触发换代(retired={res.retired})")
    check(len(calls) == 1, "只跑了一轮")

    print("\n[3] 换代:同一 session 写交接 → 新会话接手")
    rt = runtime(tmp / "b")
    seen: list[Event] = []
    res, calls = await drive(rt, SPEC, "原始任务书", [
        ([ctx_ev(rt.handoff.at + 1)], "", "old-sid", False),     # 越线
        ([], FULL, "old-sid", True),                             # 写交接那一轮
        ([ctx_ev(3_000)], "接着干完了", "new-sid", True),          # 接班的新会话
    ], on_event=seen.append)
    check([c["resume"] for c in calls] == [None, "old-sid", None],
          f"三轮的 resume:{[c['resume'] for c in calls]} —— 写交接续老的,接班开新的")
    check("你在接手一段还没干完的活" in calls[2]["prompt"],
          "接班那轮的 prompt 是交接书,不是原始任务书")
    check("原始任务书" not in calls[2]["prompt"],
          "**没有**把原始任务书再发一遍(交接必须自足)")
    check(res.session_id == "new-sid", f"对外的 session_id 是接班人:{res.session_id}")
    check(res.retired == ["old-sid"], f"烧掉的记在 retired:{res.retired}")
    check(res.ok and res.text == "接着干完了", "整步照常算成功")
    done = [e for e in seen if e.kind == "handoff" and e.payload.get("phase") == "done"]
    check(len(done) == 1 and done[0].payload["sections"]["next"].startswith("在干净"),
          "发了一条 handoff/done 事件,带着五段给 UI 画")

    print("\n[4] 换代不吃重试额度 —— 它不是失败")
    check(res.attempts == 1,
          f"跑了两轮活但 attempts={res.attempts} —— 换代不是重试,代数看 retired")
    check(len(res.retired) == 1, "代数记在 retired 里")

    print("\n[4b] 但不能无限换代:阈值低于启动地板时要有闸")
    rt = runtime(tmp / "b2")
    n = rt.handoff.max_generations
    # 每个新会话一开口就越线 —— 正是 window 配小了的那种情形
    plan = []
    for i in range(n + 4):
        plan += [([ctx_ev(rt.handoff.at + 1)], "", f"s{i}", False),
                 ([], FULL, f"s{i}", True)]
    res4, calls4 = await drive(rt, SPEC, "任务", plan)
    check(len(res4.retired) == n, f"换到第 {n} 代就停(实际 {len(res4.retired)}),不是烧到天荒地老")
    check("启动地板" in (res4.error or ""), f"错误里点明最可能的原因:{(res4.error or '')[:60]}")

    print("\n[4c] 写交接那一轮豁免阈值 —— 漏掉它整套机制就只会产出降级件")
    rt = runtime(tmp / "b3")
    rt._ctx = rt.handoff.at + 1
    live = StepResult(step="干活", session_id="s")
    check(rt._handoff_due(live) is True, "越线且有 session → 该换代")
    rt._writing_handoff = True
    check(rt._handoff_due(live) is False,
          "**写交接那一轮不判换代** —— 那时水位本来就还挂在阈值之上,"
          "不豁免的话交接一个字都写不出来(实测:头一次真跑两代全降级)")
    rt._writing_handoff = False
    check(rt._handoff_due(StepResult(step="干活")) is False,
          "还没拿到 session → 不换代(没东西可续)")
    src = Path("flower/core/runtime.py").read_text(encoding="utf-8")
    check("self._writing_handoff = True" in src and "finally:" in src,
          "豁免是 try/finally 保护的(交接写崩了也要复位)")

    print("\n[5] 写交接失败 → 降级,照样换代(没有兵底,这条是命)")
    rt = runtime(tmp / "c")
    res, calls = await drive(rt, SPEC, "原始任务书", [
        ([ctx_ev(rt.handoff.at + 1)], "", "old2", False),
        ([], "我不知道该写什么", "old2", True),        # 五段一段都解析不出来
        ([ctx_ev(2_000)], "接着干完了", "new2", True),
    ])
    check(len(calls) == 3 and calls[2]["resume"] is None, "照样换到了新会话,没有停在这里")
    check(DEGRADED in calls[2]["prompt"], "接班的人被明确告知拿到的是降级交接")
    check(any("交接降级" in e for e in res.errors), f"降级记进 errors 供排查:{res.errors}")
    d = degraded("干活", "照这份需求做:……")
    check(d.complete() and d.degraded, "降级件本身是完整的(能当 prompt 用)")

    print("\n[6] 水位每一步归零")
    rt = runtime(tmp / "d")
    await drive(rt, SPEC, "第一步", [([ctx_ev(rt.handoff.at - 1)], "完", "s1", True)],
                step="第一步")
    check(rt._ctx == rt.handoff.at - 1, f"第一步收尾水位 {rt._ctx}")
    res2, calls2 = await drive(rt, SPEC, "第二步", [([ctx_ev(500)], "完", "s2", True)],
                               step="第二步")
    check(res2.retired == [] and len(calls2) == 1,
          "第二步开局没有被上一步的读数逼着换代")

    print("\n[7] 开着换代就关掉 auto-compact")
    rt = runtime(tmp / "e")
    check(rt.handoff.enabled and rt.handoff.at == 15_000, f"阈值 {rt.handoff.at}")
    plain = AgentSpec(name="x", instructions="")
    check(plain.compact is None, "spec 默认不带 compact")
    src = Path("flower/core/runtime.py").read_text(encoding="utf-8")
    check('spec = replace(spec, compact=CompactPolicy(mode="no_summary"))' in src
          and "spec.compact is None" in src,
          "runtime 在 spec 没给 compact 时才注入 no_summary(显式给的不覆盖)")
    check(CompactPolicy(mode="no_summary").env() == {"DISABLE_AUTO_COMPACT": "1"},
          "no_summary → DISABLE_AUTO_COMPACT=1")
    off = Runtime(workspace=tmp / "f" / "ws", run_dir=tmp / "f" / "runs", handoff=False)
    check(off.handoff.enabled is False, "handoff=False 关得掉(退回 auto-compact)")
    off.close()

    print("\n[7b] 窗口按模型名判,**默认 100 万**(判大了有安全网,见 [11])")
    import os
    keep = {k: os.environ.get(k) for k in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL")}
    try:
        for m, want in (("claude-opus-5[1m]", 1_000_000), ("claude-sonnet-5-1m", 1_000_000),
                        ("claude-opus-5", 1_000_000), ("claude-sonnet-5", 1_000_000),
                        ("claude-haiku-4-5-20251001", 200_000), ("", 1_000_000)):
            os.environ["ANTHROPIC_MODEL"] = m
            os.environ.pop("ANTHROPIC_DEFAULT_OPUS_MODEL", None)
            got = default_window()
            check(got == want, f"{m or '(没配)':<28} → {got:,}")
        os.environ["ANTHROPIC_MODEL"] = ""
        os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "claude-opus-5[1m]"
        os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "claude-haiku-4-5-20251001"
        check(default_window() == 200_000, "ANTHROPIC_MODEL 空时退到 OPUS 默认那一项")
        os.environ["ANTHROPIC_MODEL"] = "claude-opus-5[1m]"
        os.environ.pop("ANTHROPIC_DEFAULT_OPUS_MODEL", None)
        check(HandoffPolicy().window == 1_000_000 and HandoffPolicy(window=200_000).window == 200_000,
              "HandoffPolicy 默认用推断值,显式给了就用给的")
    finally:
        for k, v in keep.items():
            os.environ[k] = v if v is not None else ""

    print("\n[8] 上一代的交接进档案")
    rt = runtime(tmp / "g")
    notes = rt.workbench.notes
    p1 = rt._handoff_path("干活")
    Handoff.parse(FULL).write(p1)
    p2 = rt._handoff_path("干活")
    check(p2 == p1, "当前那份永远叫 交接-干活.md")
    arch = list((notes / "archive" / "交接").glob("干活-*.md"))
    check(len(arch) == 1, f"旧的那代进了 archive/交接/:{[a.name for a in arch]}")
    check(rt._handoff_path("干活/带斜杠:的名字") is not None, "步骤名里的路径字符不会炸")

    print("\n[9] 没有工作台时不落盘,但照样换代")
    rt = runtime(tmp / "h", bench=False)
    check(rt._handoff_path("干活") is None, "没工作台 → 不落盘(文书仍走 prompt 交出去)")

    print("\n[10] 读落盘件不再自我落盘(handoff_live 头一次真跑挖出来的)")
    rt = runtime(tmp / "i")
    g = spill_guard(rt.workbench, threshold=100)
    big = "x" * 500

    async def fire(inp):
        return await g.hooks[0](
            {"tool_name": "Read", "tool_input": inp, "tool_response": big}, None, None)

    check(bool(await fire({"file_path": str(tmp / "i" / "ws" / "a.txt")})),
          "普通文件的大结果照旧落盘")
    spill = rt.workbench.root / "spill" / "deadbeef.txt"
    check(not await fire({"file_path": str(spill)}),
          "**读落盘件原样放行** —— 否则提示里那句「需要全文用 Read 读它」是空话:"
          "读回来又超阈值、又落盘、又给一行指针,无限循环")
    check(not await fire({"pattern": "^", "path": str(spill)}),
          "Grep 落盘件同理(判据看的是 tool_input 里所有字符串)")

    print("\n[11] 装不下了 → 当场换代,不是硬错(这是默认取 100 万的底气)")
    for t, want in (("prompt is too long: 1049000 tokens > 1000000 maximum", True),
                    ("API Error: context_length_exceeded", True),
                    ("input length and max_tokens exceed context limit", True),
                    ("Connection reset by peer", False), (None, False)):
        check(is_overflow(t) is want, f"{str(t)[:46]:<48} → {is_overflow(t)}")

    rt = runtime(tmp / "j", window=1_000_000, headroom=50_000)
    calls_seen = []

    async def overflow_then_ok(sp, pr, result, *, resume, fork, resume_at, on_event):
        calls_seen.append((pr, resume))
        if len(calls_seen) == 1:
            # 阈值 950K 永远够不着(判大了),API 直接退回
            result.ok, result.error = False, "prompt is too long: 1049000 tokens > 1000000"
        else:
            result.ok, result.text, result.session_id = True, "接着干完了", "new"

    rt._attempt = overflow_then_ok                   # type: ignore[method-assign]
    r = StepResult(step="干活")

    async def seed(sp, pr, result, *, resume, fork, resume_at, on_event):
        calls_seen.append((pr, resume))
        result.session_id = "old"
        if len(calls_seen) == 1:
            result.ok, result.error = False, "prompt is too long: 1049000 tokens > 1000000"
        else:
            result.ok, result.text = True, "接着干完了"

    rt._attempt = seed                               # type: ignore[method-assign]
    res = await rt.run(SPEC, "任务", step_name="干活")
    check(res.retired == ["old"], f"装不下 → 换代,而不是这一步失败(retired={res.retired})")
    check(DEGRADED in calls_seen[1][0], "用的是机械拼的降级件 —— 装不下的会话跑不动写交接那一轮")
    check(calls_seen[1][1] is None, "接班的是新会话")
    check(res.ok, "整步照常算成功")

    print(f"\n{'✓ 换代全部通过' if ok else '✗ 有失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
