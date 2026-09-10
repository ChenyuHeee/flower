"""终端安全 —— 离线验证。**不打网络,不花钱。**

起因是两次真实事故:2026-09-07 19:53 和 20:16,Terminal.app 各崩了一次
(一次 `libmalloc` 堆损坏在 `CGContextClipToRect`,一次 SwiftUI use-after-free),
把正在跑的 flower 进程一起带走。

**终端的 bug 我们修不了,但"喂给终端什么"完全在我们手里。**
这个文件钉住的就是那条边界上的三个不变式:

  1. **不超宽** —— 任何一行到终端时都不超过屏幕列数。宽度算错会让终端反复
     回绕重排,而第一次崩溃的栈正落在 `CGContextClipToRect`(裁剪矩形)上。
  2. **不带危险转义** —— 模型/工具吐的清屏、移光标、OSC、`\\r` 一律拦掉,
     只放行 flower 自己的 SGR 颜色码。子进程的字节不该直接驱动你的终端。
  3. **不用 emoji / 框线 / 几何字符** —— 它们要走字形回退和彩色字形渲染,
     那正是两次崩溃栈所在的路径。颜色留着(SGR 是安全的),图标一律 ASCII。

历史坑(实测量出来的,别再犯):
  * `answer[:120]` 按 `len()` 截 —— 120 个中文字 = **240 列**,实测打出 200 列
  * 提问原文完全不折行 —— 实测 **225 列**
  * `tool_result[:200]` / `error[:300]` —— 实测 **392 / 593 列**
"""

from __future__ import annotations

import io
import re
import sys
import tempfile as _tf
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flower.cli import (C, G, Render, _cols, _fit,          # noqa: E402
                        _sanitize, _SGR, _width)
from flower.core.events import Event                         # noqa: E402

ok = True


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


def draw(evs, *, verbose=True) -> str:
    """把一串事件渲染成终端会真正收到的文本。"""
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        r = Render(verbose=verbose)
        for e in evs:
            r(e)
    finally:
        sys.stdout = old
    return buf.getvalue()


# 一段带各种脏东西的模型/工具输出
NASTY = ("恶意输出\x1b[2J\x1b[10;10H清屏移光标\r回车覆盖\x1b]0;改标题\x07"
         "\x1bPq#0;2\x1b\\" + "长" * 400)
LONG_CJK = "很长的中文回答" * 60


def main() -> int:
    W = _width()
    print(f"\n[1] 消毒:只放行 SGR,别的转义整段吞掉")
    cases = [
        ("a\rb", "ab", "回车(会覆盖整行)"),
        ("a\x1b[2Jb", "ab", "清屏"),
        ("a\x1b[10;10Hb", "ab", "移光标"),
        ("a\x1b]0;title\x07b", "ab", "OSC 改标题"),
        ("a\x1b[?25lb", "ab", "隐藏光标"),
        ("a\x1bPq#0;2\x1b\\b", "ab", "DCS / Sixel"),
        ("a\x07b", "ab", "响铃"),
        ("a\tb", "a b", "制表符 → 空格(免得列宽算不准)"),
        (f"{C['cyn']}青{C['off']}", f"{C['cyn']}青{C['off']}", "**自己的颜色原样通过**"),
    ]
    for src, want, why in cases:
        check(_sanitize(src) == want, f"{why}:{src!r} → {_sanitize(src)!r}")
    check(_sanitize("\x1b[31m红\x1b[0m\x1b[2J") == f"{C['red']}红{C['off']}",
          "混在颜色后面的清屏也拦得住(模型学会吐 ANSI 也没用)")

    print("\n[2] 列宽:颜色码不占列,CJK 和歧义宽度都按 2 算")
    check(_cols("abc") == 3, "ascii 三个字符 = 3 列")
    check(_cols("中文") == 4, "中文两个字 = 4 列")
    check(_cols(f"{C['red']}abc{C['off']}") == 3, "SGR 不计入列宽")
    check(_cols("—") == 2 and _cols("…") == 2 and _cols("·") == 2,
          "歧义宽度(— … ·)**保守按 2 列** —— 宁可折早,绝不让终端渲成双宽而我们算成单宽")

    print("\n[3] 兜底截断:保住颜色、补上重置、绝不超宽")
    cut = _fit(f"{C['red']}{'很长' * 40}{C['off']}", 20)
    check(_cols(cut) <= 20, f"截到 {_cols(cut)} 列(上限 20)")
    check(cut.startswith(C["red"]) and cut.endswith(C["off"]), "颜色开头保住、结尾补了重置")
    check(_fit("短", 20) == "短", "没超宽就原样返回,不做无谓改动")

    print("\n[4] 图标全是 ASCII —— emoji/框线/几何字符要走字形回退,那是崩溃栈所在")
    bad = {k: v for k, v in G.items() if any(ord(c) > 127 for c in v)}
    check(not bad, f"G 里全是 ASCII(违规:{bad})")
    check(all(ord(c) < 128 for c in Render.GUTTER), f"缩进竖线是 ASCII:{Render.GUTTER!r}")

    print("\n[5] 端到端:一串脏事件渲染出来,三条不变式都不许破")
    evs = [
        Event("step", text="确认需求", payload={"index": 1, "total": 3,
                                            "resumed": True, "woke": 3}),
        Event("thinking", text=LONG_CJK, payload={}),
        # 这两条是历史上超宽最狠的:提问原文 225 列、回显回答 200 列
        Event("ask", text=LONG_CJK, payload={"state": "asked",
                                             "options": [LONG_CJK, "短选项"]}),
        Event("ask", text="", payload={"state": "answered", "answer": LONG_CJK}),
        Event("text", text=LONG_CJK, payload={"context": 34010}),
        Event("tool_call", text="git status", payload={"subagent": True}, tool="Bash"),
        Event("tool_result", text=NASTY, payload={"is_error": True, "subagent": True}),
        Event("tool_result", text=NASTY, payload={"is_error": False}),
        Event("prompt", text=LONG_CJK, payload={"subagent": True}),
        Event("error", text="API Error: " + LONG_CJK, payload={}),
        Event("ask", text="", payload={"kind": "mail", "state": "queued", "text": LONG_CJK}),
        Event("handoff", text="", payload={
            "phase": "done", "context": 152000, "window": 200000,
            "path": "/tmp/交接-干活.md", "degraded": False,
            "sections": {k: LONG_CJK for k in ("doing", "decided", "deadends", "next")}}),
        Event("retry", text=LONG_CJK, payload={}),
        Event("task", text=LONG_CJK, payload={}),
        Event("result", text="", payload={"num_turns": 9, "cost_usd": 0.53}),
    ]
    out = draw(evs)
    plain = _SGR.sub("", out)

    over = [ln for ln in out.split("\n") if _cols(ln) > W]
    check(not over, f"没有超宽行(屏宽 {W},最宽 {max((_cols(l) for l in out.split(chr(10))), default=0)})")

    esc = re.findall("\x1b.", plain)
    check(not esc, f"没有非 SGR 转义(残留:{esc[:3]})")

    ctrl = sorted({repr(c) for c in plain if c != "\n" and c < " "})
    check(not ctrl, f"没有控制字节(残留:{ctrl})")

    icons = sorted({c for c in plain if unicodedata.category(c) in ("So", "Sk")
                    or ord(c) > 0x1F000})
    check(not icons, f"没有 emoji / 几何 / 框线字符(残留:{icons})")

    check("清屏移光标" in plain and "回车覆盖" in plain,
          "**正文没被消毒吃掉** —— 拦的是转义,不是内容")

    print("\n[6] 窄屏也不破(40 列是 _width 的下限)")
    narrow = draw(evs)
    import flower.cli as cli
    real, cli._width = cli._width, lambda: 40
    try:
        narrow = draw(evs)
        over40 = [ln for ln in narrow.split("\n") if cli._cols(ln) > 40]
        check(not over40, f"40 列屏幕下也没有超宽行(超宽 {len(over40)} 条)")
    finally:
        cli._width = real

    print("\n[7] 并行:两个 flower 进程往同一个 tty 写,不许把彼此的行切开")
    # 并行跑多个 flower 是正常用法。不加跨进程锁的话,写边界落在任意字节位置 ——
    # 实测能把 UTF-8 字符和转义序列拦腰切断。这里在**同一个 pty** 上真起两个
    # 子进程复现,验证加锁后归零。
    import os as _os, pty, re as _re, time as _t
    # **只探能力,不要真 fork** —— 早先这里写成 `_os.forkpty()` 来"检测可用性",
    # 那一句本身就会分出一个子进程,凭空多一份跑完整个测试的副本。
    has_pty = hasattr(pty, "fork") and hasattr(_os, "fork")

    def _child():
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from flower.cli import _say as say, C as CC
        blk = "\n".join(f"{CC['cyn']}A 很长的一行中文内容撑满宽度触发多次写 {i:02d}{CC['off']}"
                         for i in range(6))
        blk2 = blk.replace("A ", "B ").replace(CC['cyn'], CC['red'])
        a = _os.fork()
        if a == 0:
            for _ in range(80):
                say(blk)
            _os._exit(0)
        for _ in range(80):
            say(blk2)
        _os.waitpid(a, 0)
        _os._exit(0)

    if not has_pty:
        check(True, "本平台没有 pty,跳过(锁本身在 [7b] 验)")
    else:
        pid, fd = pty.fork()
        if pid == 0:
            _child()
        buf = b""
        while True:
            try:
                d = _os.read(fd, 64)
            except OSError:
                break
            if not d:
                break
            buf += d
            _t.sleep(0.0003)
        _os.waitpid(pid, 0)
        txt = buf.decode("utf-8", "replace")
        rows = txt.replace("\r", "").split("\n")
        mixed = [l for l in rows if "A " in l and "B " in l]
        torn = _re.findall("\x1b\\[[0-9;]*[^0-9;m\x1b]", _SGR.sub("", txt))
        check(not mixed, f"没有两进程混进同一行(实测 {len(mixed)})")
        check(txt.count(chr(0xFFFD)) == 0, f"没有 UTF-8 被切断(实测 {txt.count(chr(0xFFFD))})")
        check(not torn, f"没有畸形转义(实测 {len(torn)})")

    print("\n[7b] 锁惰性获取:按当前 tty 解析,非终端下退化不报错")
    import flower.cli as _cli
    g = _cli._TtyGuard()
    with g:                                        # 非终端(测试环境)→ 解析不到 tty
        pass
    check(g._fd is None, "管道/重定向下 guard 退化成无操作(不在导入时定死)")
    # 惰性是关键:换成"当前是终端"后,再进一次就该真的拿到锁 ——
    # 早先在导入时定死,fork 出的子进程永远停在"不是终端",加了锁也白加。
    _real = _cli._tty_lock_path
    _cli._tty_lock_path = lambda: str(Path(_tf.gettempdir()) / ".flower-fake-tty.lock")
    try:
        with g:
            check(g._fd is not None, "一旦当前 stdout 是终端,下一次进入就拿到了锁")
    finally:
        _cli._tty_lock_path = _real
        if g._fd is not None:
            import os as _o
            _o.close(g._fd)

    print("\n[7c] 锁绝不能阻塞 —— 一个卡住不许拖死同终端上所有 flower")
    # 这是"并行无上限"的关键:阻塞版实测过,一个进程攥着锁(它正卡在写终端),
    # 别人全部冻住,一个卡住传染给全部。改之前一个卡住只卡它自己,那是退步。
    import fcntl as _fc, os as _o2, time as _t2
    lockp = str(Path(_tf.gettempdir()) / ".flower-nb-test.lock")
    _cli._tty_lock_path = lambda: lockp
    try:
        g2 = _cli._TtyGuard()
        hog = _o2.open(lockp, _o2.O_CREAT | _o2.O_RDWR, 0o600)
        _fc.flock(hog, _fc.LOCK_EX)                    # 别人攥着不放
        t0 = _t2.monotonic()
        with g2:
            held = g2._held
        waited = _t2.monotonic() - t0
        check(not held and waited < g2.WAIT + 0.2,
              f"抢不到锁 {waited:.2f}s 就放行(上限 {g2.WAIT}s),照样写出去")
        _fc.flock(hog, _fc.LOCK_UN)
        _o2.close(hog)
        with g2:
            check(g2._held, "没人抢时正常拿到锁")
        if g2._fd is not None:
            _o2.close(g2._fd)
    finally:
        _cli._tty_lock_path = _real
        try:
            _o2.unlink(lockp)
        except OSError:
            pass

    print("\n[7d] 同一目录并行:账本互相追加,不许冲掉对方")
    from flower.core.runtime import Runtime as _RT, StepResult as _SR
    d = Path(_tf.mkdtemp())
    ra, rb = _RT(workspace=d / "ws", run_dir=d / "runs"), _RT(workspace=d / "ws", run_dir=d / "runs")
    check(ra.run_id != rb.run_id,
          "两个 Runtime 的 run_id 不同 —— 只用秒级时间戳会撞,撞了就互删")
    for r, tag in ((ra, "A"), (rb, "B"), (ra, "A2"), (rb, "B2")):
        r.results.append(_SR(step=tag, session_id="s" + tag, ok=True))
        r._persist()
    import json as _j
    steps = {x["step"] for x in _j.loads((d / "runs" / "manifest.json").read_text())}
    check(steps == {"A", "B", "A2", "B2"}, f"四条都在(实际 {sorted(steps)})")
    ra.close()
    rb.close()

    print("\n[7e] 慢读端:一次正常的大块写入就持锁超过 0.25s → 撕裂;提到 2.0 归零")
    # 现有 [7] 读端太快(0.3ms/64B),0.25s 下也报 0/0/0,测不出这个问题(issue #21)。
    # 真因:慢终端下 write() 阻塞数秒是**正常**的(终端消化不过来,不是进程卡死),
    # 0.25 把它误判成卡死、放弃锁照写 → 两进程字节交错。这里用慢读端(8ms/512B)
    # 逼出阻塞,把 WAIT 设进 fork 前的类属性(子进程继承),对比 0.25 与 2.0。
    def _slow_pty(wait, *, rd=512, slp=0.008, lines=300, rounds=3):
        save = _cli._TtyGuard.WAIT
        _cli._TtyGuard.WAIT = wait                     # fork 前设好,两个 writer 才继承得到
        pid, fd = pty.fork()
        if pid == 0:
            blk = "\n".join(
                f"{C['cyn']}A 很长的中文行撑满宽度触发长时间持锁 {i:03d}{C['off']}"
                for i in range(lines))
            blk2 = blk.replace("A ", "B ").replace(C['cyn'], C['red'])
            a = _os.fork()
            if a == 0:
                for _ in range(rounds):
                    _cli._say(blk)                     # _say 一次写完整块 → 慢读端下这一次 write 就阻塞很久
                _os._exit(0)
            for _ in range(rounds):
                _cli._say(blk2)
            _os.waitpid(a, 0)
            _os._exit(0)
        buf = b""
        while True:
            try:
                d = _os.read(fd, rd)
            except OSError:
                break
            if not d:
                break
            buf += d
            _t.sleep(slp)                              # 慢读端:小口读 + 睡,逼 write() 阻塞
        _os.waitpid(pid, 0)
        _cli._TtyGuard.WAIT = save
        t = buf.decode("utf-8", "replace")
        rows = t.replace("\r", "").split("\n")
        mixed = sum(1 for l in rows if "A " in l and "B " in l)
        cut = t.count(chr(0xFFFD))
        torn = len(_re.findall("\x1b\\[[0-9;]*[^0-9;m\x1b]", _SGR.sub("", t)))
        return mixed, cut, torn

    if not has_pty:
        check(True, "本平台没有 pty,跳过慢读端测试(锁本身在 [7c] 验)")
    else:
        m0, c0, t0 = _slow_pty(0.25)
        m2, c2, t2 = _slow_pty(2.0)
        check(m0 + c0 + t0 > 0,
              f"WAIT=0.25 慢读端下复现撕裂(混行 {m0} / 截断 {c0} / 畸形 {t0})")
        check(m2 + c2 + t2 == 0,
              f"WAIT=2.0 慢读端下归零(混行 {m2} / 截断 {c2} / 畸形 {t2})")

    print(f"\n{'✓ 终端安全全部通过' if ok else '✗ 有失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
