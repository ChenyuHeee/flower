"""最小驱动 —— 一个"参考 UI",不是框架的一部分。

它只做一件事:把 Event 流打到终端。整个文件两百行出头,
你要换成 Web / TUI / HTTP 服务,照抄 render() 换个出口即可 ——
框架层不知道 UI 的存在。
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import importlib
import os
import re
import select
import shutil
import signal
import sys
import tempfile
import textwrap
import threading
import time
import unicodedata
from pathlib import Path

from .core.agent import AgentSpec, HandoffPolicy
from .core.env import (PROBE_AUTH, PROBE_CONFIG, PROBE_NET, check_credentials,
                       describe, load_dotenv, probe_credentials, user_env_path)
from .core.events import Event
from .core.roles import oracle
from .core.runtime import Runtime
from .workflow.starter import starter_flow, wake_state

# 配色的规则:**色相表示"谁在说话",不是装饰**。
# 不用亮暗区分角色 —— dim 在某些终端配色下接近不可读,而"这句话是谁说的"
# 是这个界面要回答的第一个问题(实测:一次运行里 subagent 的工具调用是主 agent 的
# 59 倍,混在一起就完全看不出结构,见 docs/case-ht001.md)。
C = {
    "off": "\033[0m", "dim": "\033[2m", "bold": "\033[1m",
    "red": "\033[31m", "grn": "\033[32m", "ylw": "\033[33m",
    "blu": "\033[34m", "mag": "\033[35m", "cyn": "\033[36m",
}

# 图标一律用 ASCII。emoji(💭 ❓ ✉)和框线/几何/箭头字符(━ │ └ ◆ ● ⏺ ↩ …)
# 会走终端的字形回退和彩色字形渲染 —— 两次终端崩溃的栈都落在那条路上
# (CGContextClipToRect / CoreText 字形布局)。**颜色留着**(SGR 转义是每个终端
# 都验了几十年的东西,不在崩溃栈上),只把"图标"换成 ASCII。见 issue #7。
G = {
    "rule": "=",        # 步骤分隔线的填充
    "gutter": "| ",     # subagent 缩进竖线
    "think": "~",       # 主 agent 思考(青)
    "dispatch": ">",    # 派人(洋红)
    "tool": "*",        # 工具调用
    "status": "-",      # 上下文/花费状态行
    "ask": "?",         # 提问(黄)
    "yes": "+",         # 答复 / 完成(绿)
    "no": "x",          # 错误 / 失败(红)
    "handoff": "#",     # 换代(黄)
    "item": "-",        # 交接分段项
    "resume": "<-",     # 接上次
    "warn": "!",        # 告警
    "mail": "+",        # 收件箱
    "retry": "~",       # 重试
    "skip": ".",        # 跳过
    "wait": "!",        # 无人应答 / 超时
}

# 一把锁管住所有输出。**stdin 线程和事件流是两个线程**,不加锁会在半行中间
# 交错(这是加了"一直读 stdin"之后引入的真 bug)。
_OUT = threading.Lock()


def _tty_lock_path() -> str | None:
    """同一个终端上的所有 flower 进程共用的锁文件路径。

    键取自 tty 设备名(``/dev/ttys003``)—— 同一个 tab 的进程拿到同一把锁,
    不同 tab 各锁各的,**不会互相拖慢**。
    """
    try:
        name = os.ttyname(sys.stdout.fileno())
    except (OSError, AttributeError, ValueError):
        return None                     # 不是终端(管道/重定向):不需要跨进程锁
    safe = "".join(c if c.isalnum() else "-" for c in name)
    return os.path.join(tempfile.gettempdir(), f".flower-tty{safe}.lock")


class _TtyGuard:
    """跨进程的终端写锁。**并行跑多个 flower 是正常用法,不该靠"别开两个"回避。**

    为什么需要它:``_OUT`` 是 ``threading.Lock``,只在**进程内**有效。两个 flower
    往同一个 tty 写时,写边界落在任意字节位置 —— 实测(120 轮 × 6 行 × 2 进程)
    **51 行两进程混进同一物理行、73 处 UTF-8 被拦腰切断、6 个畸形转义**。
    半个 UTF-8 字符和残缺的转义序列正是能让终端字形渲染出错的东西。

    用 ``flock`` 而不是别的:进程死了内核自动释放,不会留下卡住所有人的僵尸锁。
    拿不到锁(平台不支持、文件建不了)就退化成只有进程内锁 —— 功能不变,
    只是回到"可能交错"的老状态,**绝不因为锁失败就不输出**。

    **惰性获取**,不在导入时定死:导入那一刻 stdout 未必已经是终端
    (被重定向、在子进程里、测试环境),定死的话锁就永久失效了 ——
    这是实测栽过的:测试里 fork 出的子进程继承了"当时不是终端"的判断,
    加了锁却照样撕裂。每次按当前 tty 名解析,变了就重开。
    """

    def __init__(self) -> None:
        self._fd = None
        self._key = object()          # 当前 fd 对应哪个 tty;和 _tty_lock_path() 比对
        self._flock = None
        try:
            import fcntl                                  # noqa: PLC0415
            self._flock = fcntl.flock
            self._nb = fcntl.LOCK_EX | fcntl.LOCK_NB
            self._un = fcntl.LOCK_UN
        except Exception:                                 # noqa: BLE001
            self._flock = None                            # Windows / 无 fcntl

    WAIT = 0.25
    """最多为抢锁等多久(秒)。

    **并行不该有上限,所以这把锁绝不能是阻塞的。** 阻塞版实测:一个进程攥着锁
    (比如它正卡在往终端写 —— 终端不读了、被 Ctrl+S 挂起、或者正在崩),
    同一终端上**所有**别的 flower 跟着一起冻住,一个卡住会传染给全部。
    改之前一个卡住只卡它自己,那是退步。

    所以改成限时抢:正常情况锁持有时间是微秒级,0.25 秒抢不到说明有进程卡死了 ——
    这时候**宁可交错也要写出去**。交错只是难看,冻住是真的没法用。
    """

    def _ensure(self) -> None:
        """按**当前** stdout 的 tty 解析锁文件。tty 变了就换一把。"""
        if self._flock is None:
            return
        path = _tty_lock_path()
        if path == self._key:
            return                                        # 没变,沿用
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        self._key = path
        if path:
            try:
                self._fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            except OSError:
                self._fd = None                           # 建不了就退化,不报错

    def __enter__(self):
        self._ensure()
        self._held = False
        if self._fd is None:
            return self
        deadline = time.monotonic() + self.WAIT
        while True:
            try:
                self._flock(self._fd, self._nb)
                self._held = True
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    return self                # 抢不到就照写 —— 绝不拖住这个进程
                time.sleep(0.002)

    def __exit__(self, *exc) -> None:
        if self._fd is not None and getattr(self, "_held", False):
            try:
                self._flock(self._fd, self._un)
            except OSError:
                pass
            self._held = False


_TTY = _TtyGuard()

# 最下面那一行输入提示符。**这是"能不能插话"的全部关键**:
# 提示符原来只在文字变化时打一次,之后每条事件输出都把它冲到屏幕上方 ——
# 于是最后一行永远是 agent 的输出,用户根本看不到哪里能打字,只好 Ctrl+C。
# 现在 _say 输出前擦掉它、输出后重画,让最后一行永远是 "> "。
_PROMPT = {"text": ""}          # 空 = 当前没有输入提示符(比如非交互)
_ERASE = "\r\x1b[K"             # 回到行首 + 清到行尾。最基础的两个光标操作,
                                # 每个进度条都在用,比 alternate screen 安全得多。


def set_prompt(text: str) -> None:
    """挂/摘最下面那行输入提示符。``""`` = 摘掉。"""
    _PROMPT["text"] = text or ""


def _draw_prompt() -> None:
    """把提示符画在最下面(不换行,光标停在它后面等你打字)。"""
    if _PROMPT["text"]:
        sys.stdout.write(_PROMPT["text"])
        sys.stdout.flush()

# flower 自己的颜色码。消毒时**只放行它**,别的转义序列(清屏、移光标、OSC)
# 和裸控制字节一律清掉 —— 模型或工具吐的字节不该直接驱动你的终端。
_SGR = re.compile("\x1b\\[[0-9;]*m")

# 任意转义序列。非 SGR 的**整段吞掉**,不能只删 ESC —— 只删 ESC 会把
# "[2J"、"]0;title" 这种残骸留在屏幕上当普通文字显示,又脏又看不懂。
_ESC_ANY = re.compile(
    "\x1b\\][^\x07\x1b]*(?:\x07|\x1b\\\\)?"      # OSC ... BEL / ST
    "|\x1b\\[[0-?]*[ -/]*[@-~]"                  # CSI(移光标、清屏 …)
    "|\x1b[P X^_][^\x1b]*(?:\x1b\\\\)?"          # DCS / SOS / PM / APC
    "|\x1b[@-Z\\\\-_]"                           # 双字符转义
    "|\x1b"                                      # 落单的 ESC
)


def _sanitize(line: str) -> str:
    """清掉一行里除 SGR 颜色码之外的所有转义和控制字节。

    这是**唯一输出口的最后一道闸**(见 :func:`_say`)。模型/工具/用户吐进来的
    `\\r`、`\\x1b[2J`(清屏)、光标移动、DCS/OSC 序列会在这里整段消失,
    而 flower 自己插的 `\\x1b[36m` 这类 SGR 原样通过。**危险的转义即便来自模型
    也拦得住** —— 判据是"是不是 `\\x1b[...m`",别的转义整段吞掉。"""
    out, i, n = [], 0, len(line)
    while i < n:
        if m := _SGR.match(line, i):
            out.append(m.group())               # 自己的颜色,放行
            i = m.end()
            continue
        if m := _ESC_ANY.match(line, i):
            i = m.end()                         # 别的转义,整段吞掉
            continue
        ch = line[i]
        if ch == "\t":
            out.append(" ")                     # 制表符转空格,免得列宽算不准
        elif ch < " " or ch == "\x7f" or "\x80" <= ch <= "\x9f":
            pass                                # C0 / DEL / C1 → 丢
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _width() -> int:
    try:
        return max(40, min(shutil.get_terminal_size().columns, 110))
    except Exception:
        return 80


def _cols(text: str) -> int:
    """字符串占几列。SGR 颜色码不占列;**中日韩双宽字符占两列**。

    歧义宽度(East Asian ``A`` 类,如 — … · 以及框线字符)按 **2** 算 ——
    保守取宽:宁可折早一点,也绝不让终端把它渲成双宽而我们以为是单宽,
    从而生成一条超出屏幕的行(第一次崩溃的栈正在 ``CGContextClipToRect``,
    宽度算错正是那条路的诱因)。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WFA" else 1
               for c in _SGR.sub("", text))


def _fit(line: str, limit: int) -> str:
    """把一行截到 limit 显示列以内,保住颜色码、补上重置。

    **最后一道兜底**:哪条渲染路径万一漏了折行,也不会有超宽行真的到达终端。
    正常情况下每条路径都已按列折过,这里几乎不触发。"""
    if _cols(line) <= limit:
        return line
    out, w, i = [], 0, 0
    while i < len(line):
        m = _SGR.match(line, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        ch = line[i]
        cw = 2 if unicodedata.east_asian_width(ch) in "WFA" else 1
        if w + cw > limit - 3:
            break
        out.append(ch)
        w += cw
        i += 1
    return "".join(out) + "..." + C["off"]


def _say(text: str = "") -> None:
    """唯一输出口。每一行都过消毒 + 硬性不超宽,再打出去。

    把安全性收在这一个函数里:无论上游哪条路径生成的行,到这里都保证
    (1) 不含能驱动终端的转义/控制字节,(2) 不超过屏幕宽度。"""
    limit = _width()
    lines = []
    for ln in str(text).split("\n"):
        ln = _sanitize(ln)
        if _cols(ln) > limit:
            ln = _fit(ln, limit)
        lines.append(ln)
    blob = "\n".join(lines) + "\n"
    # 两把锁:_OUT 管本进程的线程,_TTY 管同一个终端上的**别的 flower 进程**。
    # 并行跑多个 flower 是正常用法 —— 不该靠"别开两个"回避(实测不加跨进程锁,
    # 两个进程会把彼此的行拦腰切开,连 UTF-8 字符都断成半个)。
    with _OUT, _TTY:
        try:
            # 有提示符挂在最下面就先擦掉,免得输出和它挤在同一行(实测就是这样),
            # 输出完再把它画回来 —— 于是最后一行永远是可输入的那行。
            if _PROMPT["text"]:
                sys.stdout.write(_ERASE)
            sys.stdout.write(blob)      # 一次写完,不让 print 拆成多次系统调用
            _draw_prompt()
            sys.stdout.flush()
        except (OSError, ValueError):
            pass                        # 终端已经没了(SIGHUP 之后)—— 别因此抛


def _tokens(text: str):
    """切成可断行的块。CJK 一字一块,西文一词一块(含尾随空白)。"""
    buf = ""
    for ch in text:
        if unicodedata.east_asian_width(ch) in "WF":
            if buf:
                yield buf
                buf = ""
            yield ch
        elif ch.isspace():
            buf += ch
            yield buf
            buf = ""
        else:
            buf += ch
    if buf:
        yield buf


# 避头尾:这些不能出现在行首。中文排版里一个句号被挤到下一行独占一行,
# 看起来就像段落断了 —— 实测在换代那段里就是这么歪的。
_NO_LEAD = "。,、;:!?」』）】》〉,.;:!?)]}%…"


def _wrap(text: str, indent: str = "", hang: str | None = None,
          width: int | None = None) -> str:
    """按**显示列数**折行。模型正文常是几百字一段,不折就是一堵墙。

    ``hang`` 是续行的前缀:标记(~ / #)只该出现在首行,
    每行都带一个的话读起来像列表,不像一段话。
    """
    limit = (width or _width())
    cont = indent if hang is None else hang
    out, first = [], True
    for para in (text or "").split("\n"):
        if not para.strip():
            continue
        pre = indent if first else cont
        line, cur = pre, _cols(pre)
        # 按**词块**推进,不是按字符:CJK 每字自成一块(哪里都能断),
        # 西文按空白切成词(只在词边界断)—— 否则会出现 "working tre / e" 这种截断。
        for tok in _tokens(para):
            w = _cols(tok)
            # 宁可超一两列,也不让收尾标点独自换行(避头尾)
            if (cur + w > limit and line.strip() != pre.strip()
                    and not (len(tok) == 1 and tok in _NO_LEAD)):
                out.append(line.rstrip())
                first = False
                pre = cont
                line, cur = pre, _cols(pre)
                if tok.isspace():
                    continue                 # 折行处不留悬空的空格
            line += tok
            cur += w
        out.append(line.rstrip())
        first = False
    return "\n".join(out) or indent.rstrip()


def _human(n: float) -> str:
    return f"{n/1000:.1f}K" if n >= 1000 else str(int(n))


def _short(path: str | Path) -> str:
    """把家目录换成 ~。绝对路径在终端里又长又抢眼,而它几乎从不是重点。"""
    p = Path(path).resolve()
    try:
        return f"~/{p.relative_to(Path.home())}"
    except ValueError:
        return str(p)


class Render:
    """Event → 终端。换 UI 就是换这一个类。

    它维护一点状态,因为**好的输出需要上下文**:现在是第几步、主 agent 的上下文
    涨到多少、累计花了多少、subagent 是不是正在干活(决定缩进)。
    """

    GUTTER = "  " + G["gutter"]   # subagent 的活缩进到这条竖线后面

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.started = time.time()
        self.cost = 0.0
        self.context = 0
        self.in_sub = False      # 上一条事件是不是 subagent 发的
        self.step = ""
        self.quiet = time.time()  # 上一次"主线程说话"的时刻,用来判断是不是太久没动静

    # ---- 小工具 ----------------------------------------------------
    def _elapsed(self) -> str:
        m, s = divmod(int(time.time() - self.started), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _status(self) -> str:
        ctx = f"上下文 {_human(self.context)}" if self.context else ""
        return " · ".join(x for x in (ctx, f"累计 ${self.cost:.2f}", self._elapsed()) if x)

    def _enter(self, sub: bool) -> None:
        """subagent 段落的开合。缩进本身就是"谁在干活"的答案。"""
        if sub and not self.in_sub:
            self.in_sub = True
        elif not sub and self.in_sub:
            # 不再打收尾符号:下一条输出本来就不带缩进,视觉上已经分开了,
            # 少一个字形就少一份让终端去做字形回退的机会。
            self.in_sub = False

    # ---- 主入口 ----------------------------------------------------
    def __call__(self, ev: Event) -> None:
        fn = getattr(self, f"_on_{ev.kind}", None)
        if fn is not None:
            fn(ev)

    def _on_step(self, ev: Event) -> None:
        self._enter(False)
        i, total = ev.payload.get("index", 0), ev.payload.get("total", 0)
        # 「接上次」必须看得见:否则"它到底记不记得上次"完全不可感知,
        # 而那正是这一层的全部价值。
        tail = f"{i}/{total}"
        if ev.payload.get("resumed"):
            tail += f"  {G['resume']} 接上次 · 第 {ev.payload.get('woke', 1)} 次唤醒"
        bar = G["rule"] * max(4, _width() - _cols(ev.text) - _cols(tail) - 6)
        _say(f"\n{C['bold']}{C['cyn']}{G['rule'] * 2} {ev.text} {bar}{C['off']}"
             f" {C['dim']}{tail}{C['off']}\n")

    LABEL = {"doing": "现在在做", "decided": "已定的事",
             "deadends": "走不通的", "next": "下一步"}

    def _on_handoff(self, ev: Event) -> None:
        """换代。**这件事必须看得见** —— 用户明确要求知道这个过程,

        而且这正是和 compact 的分别所在:compact 是模型自己在暗处总结一段话,
        换代是一份写在磁盘上、你能读能改的文书。
        """
        self._enter(False)
        p = ev.payload
        if p.get("phase") in ("near", "writing"):
            _say(f"{C['ylw']}{G['handoff']} {ev.text}{C['off']}")
            return
        ctx, win = p.get("context", 0), p.get("window", 0)
        _say(f"\n{C['bold']}{C['ylw']}{G['handoff']} 上下文 {_human(ctx)}/{win // 1000}K"
             f" —— 写交接准备换代{C['off']}")
        if p.get("degraded"):
            _say(f"{C['red']}  交接没写成,用了降级版本 —— 接手的人会自己去现场看{C['off']}")
        # 标签按**显示列数**对齐:"下一步" 比 "现在在做" 窄两列,用 len() 补齐
        # 会让换行后的续行对不上第一行(实测就是这么歪的)。
        pad = max(_cols(v) for v in self.LABEL.values())
        gut = " " * (4 + pad + 2)
        for k, label in self.LABEL.items():
            if body := (p.get("sections") or {}).get(k, "").strip():
                label += " " * (pad - _cols(label))
                _say(f"  {C['ylw']}{G['item']}{C['off']} {label}  "
                     f"{_wrap(' '.join(body.split()), gut).lstrip()}")
        if path := p.get("path"):
            _say(f"{C['dim']}{G['resume']} 交接写在 {_short(path)}{C['off']}")
        # 水位归零,状态行才不会一直挂着旧峰值
        self.context = 0
        _say(f"{C['dim']}{G['resume']} 新会话接手,上下文从 {_human(ctx)} 重新开始{C['off']}\n")

    def _on_text(self, ev: Event) -> None:
        sub = bool(ev.payload.get("subagent"))
        if ctx := ev.payload.get("context"):
            if not sub:
                self.context = ctx        # 只跟踪主线程的上下文
        self._enter(sub)
        if sub:
            if self.verbose:
                _say(f"{C['dim']}{_wrap(ev.text, self.GUTTER)}{C['off']}")
            return
        # 主 agent 的正文 = 决策。最高对比度,它是这次运行的主线。
        _say(_wrap(ev.text, "  "))
        _say(f"  {C['dim']}{G['status']} {self._status()}{C['off']}")
        self.quiet = time.time()

    def _on_thinking(self, ev: Event) -> None:
        if ev.payload.get("subagent"):
            return                        # subagent 的思考不看,那是现场
        self._enter(False)
        # 主 agent 的思考:青色。**默认就显示** —— 它是"为什么这么决定"的唯一线索,
        # 藏在 -v 后面等于把这次运行最有信息量的部分默认关掉。
        _say(f"{C['cyn']}{_wrap(ev.text, '  ' + G['think'] + ' ', hang='    ')}{C['off']}")

    def _on_tool_call(self, ev: Event) -> None:
        sub = bool(ev.payload.get("subagent"))
        self._enter(sub)
        pad = self.GUTTER if sub else "  "
        arg = (ev.text or "")[:_width() - len(pad) - 16]
        if ev.tool == "Agent":
            inp = ev.payload.get("input") or {}
            who = inp.get("subagent_type", "?")
            what = (inp.get("description") or inp.get("prompt") or "")[:60].replace("\n", " ")
            _say(f"{pad}{C['mag']}{G['dispatch']} 派人{C['off']} {C['bold']}{who}{C['off']} "
                 f"{C['dim']}{what}{C['off']}")
            return
        color = C["dim"] if sub else C["blu"]
        _say(f"{pad}{color}{G['tool']} {ev.tool}{C['off']} {C['dim']}{arg}{C['off']}")

    def _on_tool_result(self, ev: Event) -> None:
        sub = bool(ev.payload.get("subagent"))
        if ev.payload.get("is_error"):
            self._enter(sub)
            pad = self.GUTTER if sub else "  "
            _say(f"{C['red']}{_wrap(ev.text, pad + G['no'] + ' ', hang=pad)}{C['off']}")
        elif self.verbose:
            self._enter(sub)
            pad = self.GUTTER if sub else "  "
            _say(f"{C['dim']}{_wrap(ev.text, pad)}{C['off']}")

    def _on_prompt(self, ev: Event) -> None:
        if self.verbose:
            self._enter(bool(ev.payload.get("subagent")))
            _say(f"{C['dim']}{_wrap(ev.text, '  ' + G['dispatch'] + ' ', hang='    ')}{C['off']}")

    def _on_ask(self, ev: Event) -> None:
        self._enter(False)
        p = ev.payload
        if p.get("kind") == "mail":                    # 收件箱,不是提问
            tag = "收到" if p.get("state") == "queued" else "已送达"
            _say(f"  {C['grn']}{G['mail']} {tag}{C['off']} "
                 f"{C['dim']}{_fit(ev.text, _width() - 12)}{C['off']}")
            return
        state = p.get("state")
        if state == "asked":
            _say(f"\n{C['ylw']}{C['bold']}"
                 f"{_wrap(ev.text, '  ' + G['ask'] + ' ', hang='    ')}{C['off']}")
            for i, opt in enumerate(p.get("options") or [], 1):
                _say(f"{C['ylw']}{_wrap(opt, f'     {i}) ', hang='        ')}{C['off']}")
            if (left := p.get("remaining", -1)) >= 0:
                _say(f"     {C['dim']}(还能问 {left} 次){C['off']}")
        elif state == "answered":
            _say(f"{C['grn']}"
                 f"{_wrap(ev.payload.get('answer', ''), '  ' + G['yes'] + ' ', hang='    ')}"
                 f"{C['off']}")
        elif state == "timeout":
            _say(f"  {C['ylw']}{G['wait']} 无人应答 —— 它会自己判断,把假设记进「未知与假设」{C['off']}")
        elif state == "over_budget":
            _say(f"  {C['ylw']}{G['warn']} 提问额度用完{C['off']}")
        elif state == "declined":
            _say(f"  {C['dim']}{G['skip']} 已跳过{C['off']}")

    def _on_task(self, ev: Event) -> None:
        self._enter(False)
        _say(f"{C['mag']}{_wrap(ev.text, '  ' + G['handoff'] + ' ', hang='    ')}{C['off']}")

    def _on_error(self, ev: Event) -> None:
        self._enter(False)
        _say(f"{C['red']}{_wrap(ev.text, '  ' + G['warn'] + ' ', hang='    ')}{C['off']}")

    def _on_retry(self, ev: Event) -> None:
        self._enter(False)
        _say(f"{C['ylw']}{_wrap(ev.text, '  ' + G['retry'] + ' ', hang='    ')}{C['off']}")

    def _on_reset(self, ev: Event) -> None:
        self._enter(False)
        _say(f"{C['ylw']}{_wrap(ev.text, '  ' + G['retry'] + ' ', hang='    ')}{C['off']}")

    def _on_result(self, ev: Event) -> None:
        self._enter(False)
        p = ev.payload
        self.cost += p.get("cost_usd") or 0.0
        bad = p.get("is_error")
        _say(f"  {C['red'] if bad else C['grn']}"
             f"{G['no'] + ' 失败' if bad else G['yes'] + ' 完成'}{C['off']}"
             f" {C['dim']}{p.get('num_turns', 0)} 轮 · ${p.get('cost_usd', 0):.4f}"
             f" · 用时 {self._elapsed()}{C['off']}")


def render(ev: Event, *, verbose: bool = False) -> None:
    """向后兼容的单发入口。长跑请用 :class:`Render`(它维护状态)。"""
    Render(verbose=verbose)(ev)


class Recent:
    """最近发生了什么 —— 一个固定长度的事件窗口。

    给旁路问答(`?` 前缀)当上下文用:人在运行途中问"现在在干嘛",
    答案主要就在这里面。做成固定长度是因为它常驻内存,而一次长程运行
    的事件是几万条 —— 只留最后这些,够回答"刚刚"就行。

    更早的事情不靠它,靠工作台上的冻结件和产出报告(旁路能自己去读)。
    """

    def __init__(self, size: int = 60) -> None:
        self.buf: collections.deque = collections.deque(maxlen=size)

    def add(self, ev: Event) -> None:
        if ev.kind in ("thinking", "prompt"):
            return                       # 噪音,不进窗口
        who = "subagent" if ev.payload.get("subagent") else "主线程"
        text = (ev.text or "")[:200].replace("\n", " ")
        self.buf.append(f"[{ev.kind}{'/' + ev.tool if ev.tool else ''}·{who}] {text}")

    def render(self) -> str:
        return "\n".join(self.buf) or "(还没有事件)"


ASIDE_PROMPT = """\
有人在一次正在进行的运行旁边问你一句话。看现场,回答他。

# 他问的
{question}

# 最近发生了什么(事件窗口,新的在下面)
{recent}

# 工作台
{workbench}

需要来龙去脉就去读工作台里的确认书、目标、笔记和产出报告。
"""


async def ask_aside(question: str, rt: Runtime, recent: Recent, *, verbose: bool = False) -> None:
    """旁路问答:起一条只读 session 回答,**不碰正在跑的那次运行**。

    独立的 ``Runtime``(自己的 run_dir),所以它的花费和 session 血缘不会
    混进主 manifest —— 那份清单记的是"这次运行做了哪些步骤",
    顺口问一句不是一个步骤。
    """
    wb = rt.workbench
    side = Runtime(workspace=rt.workspace, run_dir=rt.run_dir / "aside",
                   workbench=wb if wb is not None else False,
                   resilience=False)
    try:
        r = await side.run(
            oracle(),
            ASIDE_PROMPT.format(
                question=question,
                recent=recent.render(),
                workbench=(f"{wb.show(wb.root)}/ —— 里面有 notes/(确认书、目标、决策)、"
                           f"artifacts/(产出报告)、scripts/" if wb else "(这次运行没开工作台)"),
            ),
            step_name="旁路问答",
            on_event=Render(verbose=True) if verbose else None,
        )
        _say(f"\n{C['mag']}{G['handoff']} 旁路{C['off']}\n{_wrap(r.text or '(没有回答)', '  ')}"
             f"\n{C['dim']}  (${r.cost_usd:.4f},没有打扰正在跑的运行){C['off']}")
    except Exception as exc:             # noqa: BLE001 —— 旁路失败不该带走主流程
        _say(f"\n{C['red']}{G['handoff']} 旁路问答失败:{type(exc).__name__}: {exc}{C['off']}")
    finally:
        side.close()


def answer_from_stdin(channel, *, on_aside=None) -> threading.Event:
    """参考实现:另起一个 daemon 线程读标准输入。

    **它一直在读**,不只在有提问时读。这一条是有意的:

    * 旧行为是"没有待答提问时不读 stdin",于是用户在干活那几小时里敲的东西
      留在终端缓冲里,**下一次提问时 `input()` 会把那行陈货当成答案吃掉** ——
      用户还没看见问题,问题就被"回答"了。一直读就没有陈货,这个 bug
      **由构造消失**(此前那个 `termios.tcflush` 补丁因此可以撤掉)。
    * 而且这是"人主动说话"的前提 —— 见 issue #3。

    按状态和前缀路由:

        有待答提问   → 这一行是**答案**
        `?` 开头     → **旁路提问**,交给 on_aside(不打扰正在跑的活)
        其它         → 暂时只提示,收件箱还没做(issue #3 的第二件)

    为什么是线程而不是 ``asyncio.to_thread``:``input()`` 阻塞时取消不掉,
    用 to_thread 的话进程退出前 asyncio 会 join 它 —— 活干完了还得按一次回车
    才能退出。daemon 线程不挡退出。

    ``channel.answer()`` 内部走 ``call_soon_threadsafe``,所以从哪个线程调都行;
    ``on_aside`` 同理,由调用方负责跨线程调度。
    """
    stop = threading.Event()

    def readable(timeout: float) -> bool:
        """stdin 上有没有一行在等着读。

        **不能用 `input()`** —— 它一阻塞就取消不掉,于是 ``stop.set()``
        再也叫不醒这个线程(实测:改成"一直读"之后线程不退出了)。
        select 轮询既保证一直在读,又保留对停止位的响应。
        """
        try:
            return bool(select.select([sys.stdin], [], [], timeout)[0])
        except Exception:      # select 对某些流不适用(比如 Windows 的 stdin)
            return True        # 退化成阻塞读 —— 功能对,只是退出时要等一行

    def loop() -> None:
        shown = None
        try:
            _loop_body()
        finally:
            set_prompt("")                 # 无论怎么退出,都别留下提示符

    def _loop_body() -> None:
        shown = None
        while not stop.is_set():
            pend = channel.pending()
            ask = pend[0] if pend else None
            hint = (f"{C['ylw']}你的回答{C['off']} {C['dim']}(回车=跳过,让它自己判断){C['off']} > "
                    if ask else
                    f"{C['dim']}(直接说 = 加需求,下个检查点送达;"
                    f"? 开头 = 顺便问一句,不打扰它干活){C['off']} > ")
            if hint != shown:
                # 交给 _say 去画:它会在**每条输出之后**把提示符重新放到最下面。
                # 自己 print 一次的话,第一条事件输出就把它冲走了(实测)。
                set_prompt(hint)
                with _OUT, _TTY:
                    sys.stdout.write(_ERASE)
                    _draw_prompt()
                    sys.stdout.flush()
                shown = hint
            if not readable(0.2):
                continue
            line = sys.stdin.readline()
            if not line:                   # EOF
                if ask:
                    channel.decline(ask.id, "输入已关闭")
                set_prompt("")             # 摘掉,别在收尾输出后留个孤零零的 >
                return
            raw = line.strip()
            shown = None                   # 处理完这一行,下一轮重画提示符
            if not raw:
                if ask:
                    channel.decline(ask.id)
                continue

            if raw.startswith("?") or raw.startswith("?"):
                q = raw[1:].strip()
                if q and on_aside:
                    on_aside(q)
                elif q:
                    _say(f"{C['dim']}(旁路问答没接上){C['off']}")
                continue

            if ask is not None:
                # 输了个序号就当选项处理
                if ask.options and raw.isdigit() and 1 <= int(raw) <= len(ask.options):
                    raw = ask.options[int(raw) - 1]
                channel.answer(ask.id, raw)
            else:
                m = channel.send(raw)
                if m is not None:
                    extra = ("已追加进确认书" if getattr(channel, "amend_path", None)
                             else "没有确认书可落盘 —— 它可能活不过下一个步骤")
                    _say(f"{C['grn']}{G['yes']} 收到{C['off']} {C['dim']}"
                         f"(它下次查收件箱时会看到;{extra}){C['off']}")

    threading.Thread(target=loop, daemon=True, name="flower-stdin").start()
    return stop


_CMDS = ("go", "run", "once")


def _with_default_cmd(argv: list[str], parser: argparse.ArgumentParser) -> list[str]:
    """`flower "帮我做一个 X"` —— 不写子命令时补上 ``go``。

    做法:从**左往右**跳过所有全局开关(以及带值开关的那个值),
    停在第一个"不属于全局开关"的 token 上 —— 它要么是子命令,要么已经是
    ``go`` 的参数,后者就在它前面插 ``go``。

    两个坑:

    * 不能用"argv 里出现过 run/once 吗"来判断 —— 诉求正文可能刚好就是那个词
      (``flower run`` 这种真歧义留给显式 ``flower go run``)。
    * 全局开关的集合**从 parser 自己派生**,不硬编码。否则以后加一个全局开关、
      忘了同步这张表,`flower --新开关 "诉求"` 就会把 ``go`` 插错位置。
      ``nargs == 0`` 的是纯开关,其余的要连值一起跳。
    """
    flags, valued = set(), set()
    for act in parser._actions:                    # argparse 没给公开 API
        for opt in act.option_strings:
            (flags if act.nargs == 0 else valued).add(opt)

    i = 0
    while i < len(argv):
        a = argv[i]
        head = a.split("=", 1)[0]
        if a in valued:
            i += 2                                  # --workspace DIR
            continue
        if a in flags or head in valued:
            i += 1                                  # -v / --workspace=DIR
            continue
        return argv if a in _CMDS else argv[:i] + ["go"] + argv[i:]
    # 走到这儿说明没有位置参数:要么空(`flower`),要么只有全局开关(`flower -v`)。
    # 补上 go,让它进交互输入 —— `ask` 是 nargs="?"。
    # 但 -h/--help 要留给 argparse,否则 `flower --help` 会变成 `flower go --help`。
    if any(a in ("-h", "--help") for a in argv):
        return argv
    return argv + ["go"]


NEW_CMD = "/new"


def ask_for_prompt(*, waking: bool = False) -> str:
    """没在命令行给诉求时,问一句。

    为什么值得单独做:命令行里那对引号是纯负担。**实测踩过** ——
    右引号打成了中文的 `”`,zsh 一直在等真正的右引号(`dquote>` 续行提示符),
    看起来就像程序卡住了,而其实一次都没启动。这里读的是标准输入,
    不经过 shell 解析:中文引号、空格、感叹号、换行都能直接打。

    ``waking=True``(这个目录用过)时**空回车是合法的** —— 那就是"接着做"。
    打 ``/new`` 则是"这次别接上次"。
    """
    if sys.stdin.isatty():
        head = (f"{C['ylw']}接着上次?{C['off']} {C['dim']}直接回车 = 接着做;"
                f"也可以说点新的;{NEW_CMD} = 重开一件事(Ctrl-C 退出){C['off']}"
                if waking else
                f"{C['ylw']}要做什么?{C['off']} "
                f"{C['dim']}一句话就够,回车开始(Ctrl-C 退出){C['off']}")
        print(head, flush=True)
    try:
        ask = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print(flush=True)
        sys.exit("已取消")
    if not ask and not waking:
        sys.exit('诉求是空的。直接 `flower` 然后按提示输入,或者 flower "帮我做一个 X"。')
    return ask


def _load(ref: str):
    """'mypkg.flows:build' 或 'flows.py:build' → 对象"""
    mod_ref, _, attr = ref.partition(":")
    if not attr:
        sys.exit("需要 模块:属性 形式,例如 flows:main")
    p = Path(mod_ref)
    if p.suffix == ".py":
        # 写了文件路径就必须真有这个文件。不然会掉进下面按模块名 import 的分支,
        # 报出来是 "No module named 'flows.py'; 'flows' is not a package" ——
        # 路径打错或在别的目录里跑的时候,这句话完全指不到问题上。
        if not p.exists():
            sys.exit(f"找不到 {p}(当前目录 {Path.cwd()})。"
                     "给的是文件路径就要能对上;要按模块名导入就别带 .py")
        sys.path.insert(0, str(p.resolve().parent))
        mod_ref = p.stem
    try:
        mod = importlib.import_module(mod_ref)
    except ModuleNotFoundError as e:
        sys.exit(f"导入 {mod_ref!r} 失败:{e}")
    if not hasattr(mod, attr):
        sys.exit(f"{mod_ref!r} 里没有 {attr!r}")
    return getattr(mod, attr)


async def _drive(wf, args, *, trim: bool | None = None) -> None:
    """跑一个 Workflow 对象。`run` 和 `go` 共用这一段。"""
    # workflow 自带工作台就用它的 —— 它把 brief/log 落在那里面,两边必须是同一个,
    # 否则确认书写在一处、注入索引扫的是另一处。见 Workflow.workbench。
    bench = getattr(wf, "workbench", None) or args.workbench
    # 换代:上下文到阈值就写交接换新会话。`run` 这条路径上没有这两个开关
    # (自己写的 workflow 自己给 Runtime),所以用 getattr 取默认。
    win = getattr(args, "window", None)
    hp = HandoffPolicy(enabled=not getattr(args, "no_handoff", False),
                       **({"window": win} if win else {}))
    rt = Runtime(workspace=args.workspace, run_dir=args.run_dir,
                 workbench=bench, trim=args.trim if trim is None else trim,
                 handoff=hp)
    stop = None
    recent = Recent()
    loop = asyncio.get_running_loop()

    show = Render(verbose=args.verbose)

    def sink(ev: Event) -> None:
        recent.add(ev)                    # 旁路问答要靠它回答"刚刚在干嘛"
        show(ev)

    asides: set[asyncio.Task] = set()

    def on_aside(q: str) -> None:
        """从 stdin 线程被调用 —— 必须跨线程调度回事件循环。

        用 create_task 而不是 await:旁路是**并发**跑的,
        正在跑的那次运行一秒都不用等它。

        任务存进 ``asides``:**问完就结束的话不能把答案丢掉**(实测踩过 ——
        工作流瞬间完成时,刚调度的旁路随进程一起没了,人什么都没看到)。
        退出前会等它们。
        """
        def spawn() -> None:
            t = asyncio.create_task(ask_aside(q, rt, recent, verbose=args.verbose))
            asides.add(t)
            t.add_done_callback(asides.discard)
        loop.call_soon_threadsafe(spawn)

    # ---- Ctrl+C = 打断这一轮,不是杀进程 ----------------------------
    # 在此之前 Ctrl+C 直接杀掉一切 —— 一次十小时的运行会被肌肉记忆干掉,
    # 那比"没有打断功能"更糟。现在第一次打断、第二次才退出(和常见 TUI 一致)。
    armed = {"quit": False}

    def on_sigint(signum, frame) -> None:                      # noqa: ARG001
        if armed["quit"]:
            raise KeyboardInterrupt                            # 第二次:真退出
        armed["quit"] = True
        pend = len(wf.channel.pending()) if getattr(wf, "channel", None) else 0
        _say(f"\n{C['ylw']}{G['warn']} 已打断这一轮。正在跑的 subagent 会丢掉半成品。{C['off']}\n"
             f"{C['dim']}  要说什么?(直接回车 = 什么都不说,接着跑;"
             f"再按一次 Ctrl+C = 退出){C['off']}")
        try:
            said = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            raise KeyboardInterrupt from None
        armed["quit"] = False
        rt.interrupt(said)
        if pend:
            _say(f"{C['dim']}  (有 {pend} 个提问还等着,打断不影响它们){C['off']}")

    prev_sigint = signal.signal(signal.SIGINT, on_sigint) if sys.stdin.isatty() else None

    # ---- 终端死了(SIGHUP)/ 被 kill(SIGTERM):抢救账本再走 -------------
    # 实测起因:2026-09-07 Terminal.app 崩了两次,内核给 flower 发 SIGHUP,
    # 默认动作是**直接终止** —— `finally` 不跑、manifest 不写、血缘不落。
    # novel 那次连 manifest.json 都没有,整次运行花了多少钱无账可查。见 issue #6。
    #
    # 这里只做同步的小写盘,**不试图接着跑**:pty 已经没了,再 print 会 EIO。
    def on_hangup(signum, frame) -> None:                      # noqa: ARG001
        try:
            rt.rescue()                    # 在飞的那一步也记进 manifest,标 killed
        finally:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)   # 按默认动作真的走掉,别赖着不死

    prev_hup = {}
    for _sig in (getattr(signal, "SIGHUP", None), getattr(signal, "SIGTERM", None)):
        if _sig is not None:
            try:
                prev_hup[_sig] = signal.signal(_sig, on_hangup)
            except (ValueError, OSError):
                pass                       # 非主线程 / 平台不支持 —— 不装就是了

    try:
        # workflow 自己挂了提问通道 → 给它接上标准输入。
        # 通道的 on_event 由 Workflow.run 自动接到同一个出口,这里只管"谁来答"。
        if getattr(wf, "channel", None) is not None:
            if not sys.stdin.isatty():
                # 非交互(管道、nohup、CI)。不拦,但要说清楚 ——
                # 否则第一个问题被当成"输入已关闭"跳过,之后每个问题都要干等满超时。
                print(f"{C['ylw']}{G['warn']} 标准输入不是终端,没人能回答提问。"
                      f"想让它自己判断就加 --timeout 0{C['off']}", flush=True)
            stop = answer_from_stdin(wf.channel, on_aside=on_aside)
        ctx = await wf.run(rt, on_event=sink)
    finally:
        if prev_sigint is not None:
            signal.signal(signal.SIGINT, prev_sigint)
        for _sig, _old in prev_hup.items():
            try:
                signal.signal(_sig, _old)
            except (ValueError, OSError):
                pass
        if stop is not None:
            stop.set()
        if asides:
            # 人问了就该收到答案,哪怕活刚好干完了。给个上限,别让一条旁路
            # 卡住整个退出。
            _say(f"{C['dim']}(等 {len(asides)} 条旁路问答收尾…){C['off']}")
            await asyncio.wait(set(asides), timeout=120)
        rt.close()
    _say(f"\n{C['dim']}总花费 ${rt.total_cost()} · 清单 {rt.run_dir/'manifest.json'}{C['off']}")
    if failed := ctx.get("_failed_at"):
        # 配错了(token 无效 / 401)—— 当场提出帮忙重配,而不是甩个报错让人自己查。
        res = (ctx.get("_results") or {}).get(failed)
        err = " ".join(filter(None, [getattr(res, "error", ""), *getattr(res, "errors", [])]))
        if err and AUTH_FAIL.search(err) and sys.stdin.isatty():
            _say(f"\n{C['ylw']}{G['warn']} 看起来是凭证不对:{err[:120]}{C['off']}")
            if run_setup(reason="重新配一下凭证,然后再跑一次同样的命令就接着上次继续。"):
                _say(f"{C['dim']}配好了。再跑一次刚才的命令 —— 同一目录会接着上次。{C['off']}")
        sys.exit(f"在步骤 {failed!r} 中止")


async def _run_workflow(args) -> None:
    ensure_credentials()
    obj = _load(args.target)
    await _drive(obj() if callable(obj) else obj, args)


def _wake_banner(st: dict, args) -> None:
    """唤醒时先报一行现状。

    不报的话"它到底记不记得上次"完全不可感知 —— 而那正是这一层的全部价值。
    上下文数字尤其要报:接续是无止境的,它只会一直涨,人得看得见才有机会
    在撞窗口之前自己决定 ``/new``。
    """
    bits = ["需求已确认"]
    if st["checks"]:
        bits.append(f"目标 {st['checks']} 条")
    if sid := st["steps"].get("干活"):
        try:
            rt = Runtime(workspace=args.workspace, run_dir=args.run_dir)
        except Exception:                                  # noqa: BLE001
            rt = None
        if rt is not None:
            try:
                if n := rt.context_of(sid):
                    bits.append(f"干活上下文 {_human(n)}")
            finally:
                rt.close()
    _say(f"{C['cyn']}{G['resume']} 在 {_short(args.workspace)} 接上上次{C['off']} "
         f"{C['dim']}{' · '.join(bits)} · 第 {st['woke'] + 1} 次唤醒{C['off']}")


async def _run_go(args) -> None:
    """零配置入口:`flower "帮我做一个 X"`。流程见 workflow/starter.py。"""
    ensure_credentials()
    fresh = bool(getattr(args, "new", False))
    st = wake_state(args.workspace, run_dir=args.run_dir, isolate=args.isolate)
    waking = st["waking"] and not fresh

    ask = (args.ask or "").strip()
    if not ask:
        ask = ask_for_prompt(waking=waking)
    if ask == NEW_CMD:              # 在提示符里改主意了 —— 和 --new 同一条路
        fresh, waking, ask = True, False, ask_for_prompt()
    if waking:
        _wake_banner(st, args)

    try:
        wf = starter_flow(
            ask,
            workspace=args.workspace,
            run_dir=args.run_dir,
            new=fresh,
            isolate=args.isolate,
            clarify_only=args.clarify_only,
            max_asks=None if args.asks < 0 else args.asks,
            timeout_s=args.timeout,
            goal=not args.no_goal,
            rounds=args.rounds,
            judge_can_run=args.judge_can_run,
        )
    except ValueError as e:
        sys.exit(str(e))
    await _drive(wf, args, trim=not args.no_trim)


async def _run_once(args) -> None:
    ensure_credentials()
    spec = AgentSpec(
        name="ad-hoc",
        instructions=args.instructions or "",
        allowed_tools=args.tools.split(",") if args.tools else ["Read", "Glob", "Grep"],
        permission_mode=args.permission_mode,
        max_budget_usd=args.budget,
    )
    rt = Runtime(workspace=args.workspace, run_dir=args.run_dir,
                 workbench=args.workbench, trim=args.trim)
    try:
        await rt.run(
            spec, args.prompt,
            resume=args.resume, fork=args.fork,
            on_event=lambda e: render(e, verbose=args.verbose),
        )
    finally:
        rt.close()


# 全局开关。子命令是**隐形**的(`flower "诉求"` 自动补 go),所以用户不会有
# "开关要写在子命令前面"这个心理模型 —— 两个位置都得能用。做法:同一份定义
# 既加在主 parser 上,也加在每个子命令上;子命令那份 default=SUPPRESS,
# 没给就不写属性,于是不会用默认值把主 parser 已经解析出的值盖掉
# (这是 argparse 用 parents 时的经典坑)。
_GLOBALS = (
    (("-w", "--workspace"), {"default": ".", "help": "agent 的工作目录"}),
    (("-r", "--run-dir"), {"default": "runs", "help": "会话存储与运行清单"}),
    (("-v", "--verbose"), {"action": "store_true", "help": "显示思考与工具结果"}),
    (("-W", "--workbench"), {"action": "store_true",
                             "help": "启用工作台(脚本/产出/笔记落盘 + 索引注入)。"
                                     "workflow 自带 workbench 时以它为准,不必给这个"}),
    (("-T", "--trim"), {"action": "store_true",
                        "help": "resume 时把旧的大工具结果换成文件指针"}),
)


def _add_globals(parser: argparse.ArgumentParser, *, suppress: bool) -> None:
    for names, kw in _GLOBALS:
        if suppress:
            kw = {**kw, "default": argparse.SUPPRESS, "help": argparse.SUPPRESS}
        parser.add_argument(*names, **kw)


def build_parser() -> argparse.ArgumentParser:
    """单独拿出来是为了能在测试里解析而不执行(`tests/trial_offline.py`)。"""
    ap = argparse.ArgumentParser(prog="flower", description="可移植长程 agent 框架")
    _add_globals(ap, suppress=False)
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser(
        "go", help="一键跑:问清需求 → 派人干活(不写子命令时的默认)",
        epilog="全局开关(-v/-w/-r/-T)见 `flower --help`;写在诉求前面或后面都行。")
    _add_globals(g, suppress=True)
    g.add_argument("ask", nargs="?",
                   help="你的原始诉求,一句话就够。**不给就进交互输入** —— "
                        "这样不用在 shell 里加引号")
    g.add_argument("--asks", type=int, default=-1, metavar="N",
                   help="提问额度:**默认不限**(问到清楚为止)。"
                        "给个数字就是硬额度,0 = 不许提问")
    g.add_argument("--rounds", type=int, default=3, metavar="N",
                   help="干活的总轮数上限:每轮结束由独立判定者判"
                        "「做完了没有」,没达成就打回来接着做(默认 3)")
    g.add_argument("--no-goal", action="store_true",
                   help="关掉目标看守 —— 干活跑完就算完,不做判定(便宜但没有兜底)")
    g.add_argument("--judge-can-run", action="store_true",
                   help="让判定者能跑命令(判定更硬,但它就能改动工作区了)")
    g.add_argument("--timeout", type=float, default=1800.0, metavar="秒",
                   help="等你多久回答:默认 1800;0 = 全自动,不等人")
    g.add_argument("--isolate", action="store_true",
                   help="每个 subagent 分一份 git worktree(要求工作区是 git 仓库)")
    g.add_argument("--window", type=int, default=None, metavar="N",
                   help="模型上下文窗口,**默认 100 万**(名字带 haiku 的按 20 万)。"
                        "判大了也不是硬错:API 退回「prompt 太长」时会当场换代。"
                        "到 窗口−50000 就写交接换新会话,而不是 compact")
    g.add_argument("--no-handoff", action="store_true",
                   help="关掉换代 —— 退回 SDK 自带的 auto-compact(把历史总结成一段话)")
    g.add_argument("--new", action="store_true",
                   help="这次别接上次:把上一段的需求/目标/血缘收进 "
                        "notes/archive/ 再从头开始(不删,只是移开)")
    g.add_argument("--clarify-only", action="store_true", help="只问清需求,不往下干活")
    g.add_argument("--no-trim", action="store_true", help="关掉 trim(这条路径默认开)")
    g.set_defaults(fn=_run_go)

    r = sub.add_parser("run", help="运行一个 workflow")
    _add_globals(r, suppress=True)
    r.add_argument("target", help="模块:属性,例如 flows:main")
    r.set_defaults(fn=_run_workflow)

    o = sub.add_parser("once", help="跑一次单 agent")
    _add_globals(o, suppress=True)
    o.add_argument("prompt")
    o.add_argument("-i", "--instructions", help="追加在 Claude Code 原生提示词之后")
    o.add_argument("-t", "--tools", help="逗号分隔的工具白名单")
    o.add_argument("-p", "--permission-mode", default="default",
                   choices=["default", "acceptEdits", "plan", "bypassPermissions"])
    o.add_argument("-b", "--budget", type=float, help="美元预算上限")
    o.add_argument("--resume", help="续跑某个 session_id")
    o.add_argument("--fork", action="store_true", help="分叉而非续跑")
    o.set_defaults(fn=_run_once)

    st = sub.add_parser("setup", help="配置凭证(API key / 网关 / 模型),写到 ~/.config/flower/.env")
    _add_globals(st, suppress=True)
    st.set_defaults(fn=_run_setup_cmd)

    return ap


AUTH_FAIL = re.compile(r"401|invalid[_ ]?api[_ ]?key|authentication|unauthorized|无效.*(?:key|token|密钥)", re.I)


def _write_user_env(vals: dict[str, str]) -> Path:
    """把配置写到 ~/.config/flower/.env(chmod 600 —— 里面有 token)。"""
    path = user_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# flower 凭证 —— 由 `flower setup` 写。别提交进版本库。", ""]
    lines += [f"{k}={v}" for k, v in vals.items() if v]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def run_setup(*, reason: str = "") -> bool:
    """交互式问凭证,写盘,重新加载。返回是否配好了。

    这是"第一次跑自动弹、配错了再弹"的那个流程 —— 用户不用自己去碰配置文件。
    非交互(管道/CI)下不能问,返回 False,让调用方打印指引后退出。
    """
    if not sys.stdin.isatty():
        return False
    _say(f"\n{C['bold']}{C['cyn']}== 配置 flower {'=' * 40}{C['off']}")
    if reason:
        _say(f"{C['ylw']}{reason}{C['off']}")
    _say(f"{C['dim']}凭证会存到 {user_env_path()}(只你可读)。装一次,处处生效。{C['off']}\n")

    _say(f"{C['ylw']}1. 你的 API key 或网关 token{C['off']} "
         f"{C['dim']}(Anthropic 官方的 sk-ant-… 或第三方网关签发的){C['off']}")
    token = input("   > ").strip()
    if not token:
        _say(f"{C['red']}没给 token,取消。{C['off']}")
        return False

    _say(f"\n{C['ylw']}2. 网关地址{C['off']} "
         f"{C['dim']}(直接回车 = Anthropic 官方;第三方网关填它的 BASE_URL){C['off']}")
    base = input("   > ").strip()

    _say(f"\n{C['ylw']}3. 模型名{C['off']} "
         f"{C['dim']}(直接回车 = 默认;网关有自己的模型名就填,如 claude-opus-5[1m]){C['off']}")
    model = input("   > ").strip()

    key = "ANTHROPIC_API_KEY" if token.startswith("sk-ant-") else "ANTHROPIC_AUTH_TOKEN"
    vals = {key: token}
    if base:
        vals["ANTHROPIC_BASE_URL"] = base
    if model:
        vals["ANTHROPIC_MODEL"] = model
        vals["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model
        vals["ANTHROPIC_DEFAULT_SONNET_MODEL"] = model
    path = _write_user_env(vals)
    load_dotenv(str(path), override=True)               # 立刻生效
    _say(f"\n{C['grn']}{G['yes']} 存好了:{path}{C['off']}\n")
    return True


def ensure_credentials(*, probe: bool = True) -> None:
    """跑活之前保证凭证**存在且真的能用**。

    两道:
      1. 有没有 —— 缺了当场问(交互),非交互打印指引退出。
      2. **能不能用** —— 真打一次 API。过期/写错/网关地址不对的 token
         光看环境变量是查不出来的,不探的话要跑到几分钟后才炸。

    探针失败**分类处理**,这是关键:只有认证被拒(auth)和配置不对(config)
    才去重配;网络不通(net)属于环境问题,**不能让人重配一个本来好好的 token**,
    照常往下跑,交给断网重试那一层。
    """
    load_dotenv()
    if check_credentials() is not None:
        if not run_setup(reason="第一次用?给一次凭证就行。"):
            sys.exit(check_credentials())               # 非交互:打印指引
    if not probe:
        return

    for _ in range(2):                                  # 最多给一次重配机会
        _say(f"{C['dim']}{G['status']} 验一下凭证…{C['off']}")
        verdict, why = probe_credentials()
        if verdict in (PROBE_AUTH, PROBE_CONFIG):
            bad = "凭证被拒" if verdict == PROBE_AUTH else "网关地址或模型名不对"
            _say(f"{C['ylw']}{G['warn']} {bad}:{why[:160]}{C['off']}")
            if not run_setup(reason="重新配一下,配完立刻再验。"):
                sys.exit(f"{bad},且无法交互配置。跑 `flower setup` 重配。")
            continue                                    # 配完再验一遍
        if verdict == PROBE_NET:
            # **不是凭证的问题** —— 别让人瞎重配。往下跑,断网重试那层会处理。
            _say(f"{C['dim']}  (探针没打通:{why[:80]} —— 当作网络问题,照常开跑){C['off']}")
        return


async def _run_setup_cmd(args) -> None:                 # `flower setup`
    load_dotenv()
    have = check_credentials() is None
    run_setup(reason="重新配置。" if have else "还没配过凭证。")


def main() -> None:
    ap = build_parser()
    args = ap.parse_args(_with_default_cmd(sys.argv[1:], ap))
    load_dotenv()
    if args.verbose:
        for k, v in describe().items():
            print(f"{C['dim']}{k} = {v}{C['off']}")
    asyncio.run(args.fn(args))


if __name__ == "__main__":
    main()
