"""插话与行编辑 —— 离线验证。**不打网络,不花钱**(真 pty,不发请求)。

中途插话是核心能力(issue #3),但实测一直插不进,原因有三层,逐层修:

  1. **看不到哪里能打字** —— 提示符只在文字变化时打一次,之后每条事件输出
     都把它冲到屏幕上方。用户只好 Ctrl+C,而打断会撕断在飞的工具调用(#9)。
  2. **打了一半的字被重绘擦掉** —— 加了"输出后重画提示符"之后引入的。
     内容其实没丢(还在终端行缓冲里,回车照样发出去,实测确认),
     但**看不见 = 不敢确定 = 重打一遍**,和丢了一样糟。
  3. **退格删半个中文、方向键失灵** —— 行模式下终端按字节删;而第一版自管
     缓冲时只忽略 `\\x1b` 却放行后面的字节,方向键会把 "[A" 插进输入里。

所以自己接管输入(cbreak 逐字符),缓冲是 str、光标按字符走。
拿不到 raw 模式就**退化**成按行读 —— 输入是唯一入口,写坏了整个工具没法用。
"""

from __future__ import annotations

import os
import pty
import re
import select
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
ok = True


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


CHILD = '''
import sys, time, threading
sys.path.insert(0, {root!r})
from flower.cli import answer_from_stdin, _say
from flower.core.human import HumanChannel
class Ch(HumanChannel):
    def send(self, text):
        print(f"\\n[[R:{{text!r}}]]", flush=True); return None
ch = Ch(timeout_s=0)
stop = answer_from_stdin(ch)
{extra}
time.sleep(600)          # 不自己结束:父进程拿到结果就杀。见 run() 的注释
'''


def run(actions, *, wait=3.0, extra="", gap=0.18):
    """在真 pty 里跑一次输入交互,返回 (最终提交的内容, 屏幕文本)。"""
    pid, fd = pty.fork()
    if pid == 0:
        # **-u 无缓冲**:不加的话子进程 print 的结果卡在 stdio 缓冲里,
        # 测试读不到就误判"输入丢了" —— 这个测试自己抖过,查了半天才发现是它的错。
        os.execv(sys.executable, ["python", "-u", "-c",
                                  CHILD.format(root=str(ROOT), extra=extra, wait=wait)])
    time.sleep(0.9)          # 等 stdin 线程把提示符画出来再开始打字
    for a in actions:
        os.write(fd, a if isinstance(a, bytes) else a.encode())
        time.sleep(gap)
    os.write(fd, b"\n")
    # **等标记出现,不要死等固定时间**。固定 sleep 在机器忙的时候会来不及,
    # 测试就时好时坏 —— 会哭狼的测试比没有测试更糟。
    buf, t0 = b"", time.time()
    while time.time() - t0 < wait + 8:
        if re.search(r"\[\[R:.*?\]\]", buf.decode("utf-8", "replace")):
            break                     # 拿到结果就走,不用等子进程自然结束
        # **必须 select 带超时**:子进程是长驻的(不自己退出),裸 os.read 在没数据时
        # 会永久阻塞,while 的截止条件根本轮不到检查 —— 整个测试就挂死。
        if not select.select([fd], [], [], 0.3)[0]:
            continue
        try:
            d = os.read(fd, 4096)
        except OSError:
            break
        if not d:
            break
        buf += d
    try:
        os.kill(pid, 9)               # 结果已到手,别等它 sleep 完
    except OSError:
        pass
    os.waitpid(pid, 0)
    txt = buf.decode("utf-8", "replace")
    m = re.search(r"\[\[R:(.*?)\]\]", txt)
    return (m.group(1) if m else None), txt


def screen(txt):
    """把带 \\r 和清行的原始字节还原成"屏幕上看到的样子"。"""
    out = []
    for chunk in txt.split("\n"):
        cur = ""
        for part in chunk.split("\r"):
            part = re.sub(r"\x1b\[K", "", part)
            cur = part if part else cur
        out.append(re.sub(r"\x1b\[[0-9;]*[mD]", "", cur))
    return out


def main() -> int:
    print("\n[1] 行编辑:按**字符**编辑,不是按字节(直接测状态机,不走 pty)")
    # 抽成 LineEditor 之后可以直接喂字节 —— 确定性的,不受机器负载影响。
    # 之前靠 pty 端到端测,机器一忙就时好时坏,那种测试会哭狼。
    from flower.cli import LineEditor

    def typed(*chunks) -> str | None:
        ed = LineEditor()
        out = None
        for c in chunks:
            out = ed.feed(c if isinstance(c, bytes) else c.encode())
        return out

    for chunks, want, why in [
        (("你好世界", b"\n"), "你好世界", "纯中文原样收到"),
        (("你好世界", b"\x7f", b"\n"), "你好世", "退格删掉**整个**中文字(不是半个)"),
        (("abc", b"\x7f\x7f", b"\n"), "a", "退格删英文"),
        (("世界", b"\x1b[D", "新", b"\n"), "世新界", "← 之后在中间插入"),
        (("abc", b"\x1b[D\x1b[D", b"\x1b[C", "X", b"\n"), "abXc", "← ← → 光标真的在动"),
        (("abc", b"\x01", "Z", b"\n"), "Zabc", "Ctrl+A 行首"),
        (("abc", b"\x01", b"\x05", "Z", b"\n"), "abcZ", "Ctrl+E 行尾"),
        (("丢掉", b"\x15", "留这个", b"\n"), "留这个", "Ctrl+U 清空重打"),
        (("ab", b"\x1b[A", b"\x1b[B", "c", b"\n"), "abc",
         "**↑↓ 整段吃掉**,不会把 [A 插进输入(第一版就是这么坏的)"),
        (("ab", b"\x1b[3~", b"\n"), "ab", "Delete 在行尾无害"),
        (("abc", b"\x01", b"\x1b[3~", b"\n"), "bc", "Home 之后 Delete 删掉第一个"),
    ]:
        got = typed(*chunks)
        check(got == want, f"{why} → {got!r}")

    # UTF-8 被从中间切开也不能解出乱码(os.read 真会这样切)
    ed = LineEditor()
    raw = "中".encode()
    ed.feed(raw[:1]); ed.feed(raw[1:2])
    check(ed.buf == "", "中文只喂了两个字节 → 还不吐字符(增量解码攒着)")
    ed.feed(raw[2:])
    check(ed.buf == "中", "第三个字节到齐 → 吐出完整的「中」,不是乱码")

    print("\n[2] 打字期间来了输出:重绘之后**字还在,而且看得见**")
    spam = ('def s():\n'
            '    for i in range(3):\n'
            '        time.sleep(0.4); _say(f"  agent 输出 {i}")\n'
            'threading.Thread(target=s, daemon=True).start()')
    # 这一项**必须**走真 pty(测的是"输出重绘之后字还在"这个端到端性质),
    # 而 pty 时序在机器忙时会抖 —— 所以重试三次,全败才算失败。
    # [1] 那 11 项已经被抽成状态机直接测了,不依赖时序。
    got, txt = None, ""
    for _ in range(3):
        got, txt = run(["我正在打一句很长的话", "还没打完"], wait=3.4, extra=spam, gap=1.2)
        if got == "'我正在打一句很长的话还没打完'":
            break
    check(got == "'我正在打一句很长的话还没打完'", f"被打断多次后一个字没丢 → {got}")
    check(any("我正在打" in l for l in screen(txt)), "重绘后屏幕上仍然看得见输入")

    print("\n[3] 最后一行永远是可输入的那行(否则用户以为插不进)")
    got, txt = run([], wait=2.2, extra='_say("  agent 输出一条")')
    tail = [l for l in screen(txt) if l.strip()]
    check(any(l.rstrip().endswith(">") for l in tail[-3:]),
          "输出之后提示符被重画回最下面")

    print("\n[4] 退化路径还在 —— 输入是唯一入口,拿不到 raw 模式也必须能用")
    src = (ROOT / "flower" / "cli.py").read_text(encoding="utf-8")
    check("def raw_mode()" in src and "return None" in src, "raw_mode 拿不到就返回 None")
    check("if char_mode:" in src and "sys.stdin.readline()" in src,
          "按行读的老路完整保留")
    check("tcsetattr" in src and "TCSADRAIN" in src,
          "**退出时还原终端** —— 不还原的话 shell 会不回显")
    check("tty.setcbreak" in src,
          "用 cbreak 不是 raw —— Ctrl+C 仍产生 SIGINT,打断功能照常")

    print(f"\n{'✓ 插话与行编辑全部通过' if ok else '✗ 有失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
