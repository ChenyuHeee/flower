"""前置确认 flow —— 离线验证。不打网络,不花钱。

覆盖四件事:
  1. 提问通道的语义:阻塞等答案 / 额度用尽 / 超时落空 / 跳过 / 跨线程回答
  2. Brief 只保留四段 —— 模型贴进来的代码不能漏到下游
  3. clarify 角色**没有**写工具(这是"它没法开工"的唯一保证)
  4. clarify_step 接线:已有确认书就跳过、四段不全不许过、往下传的是解析后的四段
"""
import asyncio, sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.core.brief import Brief
from flower.core.human import HumanChannel
from flower.core.roles import clarify
from flower.core.runtime import StepResult
from flower.workflow.clarify import BRIEF_KEY, MISSING_KEY, clarify_step

ok = True


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


FULL = """\
好的，我明白了。

## 目标
做一个统计目录体积的 CLI，给我自己用。

## 验收标准
- `python dirstat.py .` 输出每个子目录的体积
- 不依赖第三方库

## 边界
不做 GUI。不做远程目录。不管 Windows。

## 未知与假设
- 没问排序方式，假设按体积降序
"""

DIRTY = """\
我先说结论，然后把代码贴给你。

## 目标
做个小工具。

## 验收标准
跑起来不报错。

## 边界
只做 macOS。

## 未知与假设
无。

```python
# 目标
# 这一段是代码里的假注释，不该被解析成段落
def main():
    print("边界: 不该出现在 bounds 里")
```
"""


async def channel_tests():
    print("\n[1] 提问通道")

    # 正常路径:处理器阻塞,另一个任务回答
    ch = HumanChannel(max_asks=3, timeout_s=5)
    events = []
    ch.on_event = events.append

    async def answerer():
        a = await ch.next_ask()
        await asyncio.sleep(0.2)
        ch.answer(a.id, "Python")

    t0 = time.time()
    task = asyncio.create_task(answerer())
    res = await ch._handle({"question": "用什么语言?", "options": ["Python", "Go"]})
    await task
    waited = time.time() - t0
    check(res["content"][0]["text"] == "Python", "答案原样回到模型")
    check(waited >= 0.15, f"处理器确实阻塞等待({waited:.2f}s)")
    check(ch.asks[0].state == "answered", "状态标为 answered")
    check([e.payload["state"] for e in events] == ["asked", "answered"],
          "事件流:asked → answered")
    check(events[0].payload["options"] == ["Python", "Go"], "选项随事件带给 UI")

    # 跳过
    ch2 = HumanChannel(timeout_s=5)

    async def decliner():
        a = await ch2.next_ask()
        ch2.decline(a.id)

    task = asyncio.create_task(decliner())
    res = await ch2._handle({"question": "要不要?"})
    await task
    check("跳过" in res["content"][0]["text"], "跳过 → 让模型自己判断")
    check(ch2.asks[0].state == "declined", "状态标为 declined")

    # 超时:不报错,给一句说明
    ch3 = HumanChannel(timeout_s=0.3)
    t0 = time.time()
    res = await ch3._handle({"question": "有人吗?"})
    check("无人应答" in res["content"][0]["text"], "超时 → 无人应答,不是报错")
    check(0.25 < time.time() - t0 < 2, "超时按 timeout_s 生效")
    check(ch3.asks[0].state == "timeout", "状态标为 timeout")

    # 全自动模式:不等
    ch4 = HumanChannel(timeout_s=0)
    t0 = time.time()
    res = await ch4._handle({"question": "有人吗?"})
    check(time.time() - t0 < 0.1, "timeout_s=0 立刻落空,不假装等")
    check("无人应答" in res["content"][0]["text"], "全自动模式给的也是说明")

    # 额度:第 3 次之后回绝,且不阻塞
    ch5 = HumanChannel(max_asks=2, timeout_s=None)   # timeout=None 会永远等

    async def two():
        for _ in range(2):
            a = await ch5.next_ask()
            ch5.answer(a.id, "好")

    task = asyncio.create_task(two())
    await ch5._handle({"question": "一"})
    await ch5._handle({"question": "二"})
    await task
    t0 = time.time()
    res = await ch5._handle({"question": "三"})      # 超额:必须立刻返回,不能挂死
    check(time.time() - t0 < 0.1, "超额提问立刻回绝(没有阻塞)")
    check("额度已用完" in res["content"][0]["text"], "回绝语指向「未知与假设」")
    check(ch5.remaining == 0, "remaining 归零")

    # 跨线程回答 —— Web 后端 / TUI 输入线程的真实形状
    ch6 = HumanChannel(timeout_s=5)

    def from_thread():
        while not ch6.pending():
            time.sleep(0.02)
        ch6.answer(ch6.pending()[0].id, "从别的线程答的")

    threading.Thread(target=from_thread, daemon=True).start()
    res = await ch6._handle({"question": "线程安全吗?"})
    check(res["content"][0]["text"] == "从别的线程答的", "别的线程也能回答")

    # UI 回调抛异常不该带走这次运行
    ch7 = HumanChannel(timeout_s=0)
    ch7.on_event = lambda e: (_ for _ in ()).throw(RuntimeError("前端崩了"))
    res = await ch7._handle({"question": "?"})
    check(res["content"][0]["text"], "UI 崩了运行照走")
    check(ch7.ui_errors and "前端崩了" in ch7.ui_errors[0], "异常记进 ui_errors")

    # 落盘留档
    log = Path("/tmp/flower_ask_log.md")
    log.unlink(missing_ok=True)
    ch8 = HumanChannel(timeout_s=0, log_path=log)
    await ch8._handle({"question": "记下来了吗?"})
    text = log.read_text()
    check("记下来了吗?" in text and "timeout" in text, "问答追加到磁盘")


def brief_tests():
    print("\n[2] 需求确认书")
    b = Brief.parse(FULL)
    check(b.complete(), "四段齐全 → complete")
    check(b.goal.startswith("做一个统计目录体积"), "目标解析正确")
    check("不做 GUI" in b.bounds, "边界解析正确")
    check("按体积降序" in b.unknowns, "未知与假设解析正确")
    check("好的，我明白了" not in b.prompt_block(), "四段之外的话被丢掉")

    d = Brief.parse(DIRTY)
    check(d.complete(), "夹了代码块也能解析出四段")
    check("def main" not in d.prompt_block(), "**贴进来的代码没漏到下游**")
    check("不该出现在 bounds" not in d.bounds, "代码里的假标题不影响解析")

    part = Brief.parse("## 目标\n做个东西\n\n## 边界\n不做 X")
    check(not part.complete(), "缺段 → 不完整")
    check(part.missing() == ["验收标准", "未知与假设"], f"缺的段名可读:{part.missing()}")

    # 变体写法
    alt = Brief.parse("**目标**：A\n1. 验收条件: B\n### 不做什么\nC\n未知与假设:\nD")
    check(alt.complete(), f"容忍标题变体(得到 {alt.missing() or '四段齐全'})")

    # 落盘往返
    p = Path("/tmp/flower_brief_test.md")
    p.unlink(missing_ok=True)
    b.write(p)
    back = Brief.load(p)
    check(back is not None and back.complete(), "写出去再读回来仍完整")
    check(back.bounds.strip() == b.bounds.strip(), "往返内容一致")
    check(Brief.load("/tmp/does_not_exist_xyz.md") is None, "文件不存在返回 None")
    empty = Brief(goal="A", accept="B", bounds="C")
    empty.write(p)
    check(Brief.load(p).unknowns == "", "占位符 (未填) 不算内容")


def role_tests():
    print("\n[3] clarify 角色")
    ch = HumanChannel()
    spec = clarify("确认", ch)
    check(ch.tool_name in spec.allowed_tools, "提问工具在白名单里")
    banned = {"Write", "Edit", "NotebookEdit", "Bash", "Agent", "TodoWrite"}
    got = banned & set(spec.allowed_tools)
    check(not got, f"**没有写/跑/派人的工具**(白名单:{spec.allowed_tools})")
    check(spec.workbench is False, "不注入工作台索引(它没有写工具)")
    check("human" in spec.mcp_servers, "MCP server 名与工具名同源")
    check(clarify("x", ch, can_read=False).allowed_tools == [ch.tool_name],
          "can_read=False 时只剩提问工具")


def step_tests():
    print("\n[4] clarify_step 接线")
    path = Path("/tmp/flower_step_brief.md")
    path.unlink(missing_ok=True)
    ch = HumanChannel()
    step = clarify_step(ch, brief_path=path, prompt="帮我做个 X")

    ctx = {}
    check(step.when(ctx) is True, "没有确认书 → 要问")

    bad = StepResult(step="确认需求", ok=True, text="## 目标\n只写了一段")
    check(step.gate(bad, ctx) is False, "四段不全 → gate 不放行")
    check(ctx[MISSING_KEY] == ["验收标准", "边界", "未知与假设"], "缺的段名进 ctx 供 UI 显示")
    check(not path.exists(), "不完整不落盘")

    good = StepResult(step="确认需求", ok=True, text=DIRTY)
    check(step.gate(good, ctx) is True, "四段齐全 → 放行")
    check(path.exists(), "确认书落盘冻结")
    check(MISSING_KEY not in ctx, "缺段记录被清掉")
    check(isinstance(ctx[BRIEF_KEY], Brief), f"ctx['{BRIEF_KEY}'] 是 Brief 对象")

    passed_down = step.reduce(good, ctx)
    check("def main" not in passed_down, "**往下游传的是四段,不是原文**")
    check("## 目标" in passed_down, "下游拿到的是可直接插进 prompt 的块")

    ctx2 = {}
    check(step.when(ctx2) is False, "确认书已存在 → 跳过,不重新盘问")
    check(ctx2.get("确认需求") and isinstance(ctx2.get(BRIEF_KEY), Brief),
          "跳过时仍然把需求灌进 ctx(否则下游拿不到)")

    always = clarify_step(ch, brief_path=path, prompt="x", always_ask=True)
    check(always.when({}) is True, "always_ask=True 每次都重新确认")


async def main():
    await channel_tests()
    brief_tests()
    role_tests()
    step_tests()
    print("\n" + ("✓ 前置确认 flow 全部通过" if ok else "✗ 未通过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
