"""交接书 —— 上下文要满了的时候,写一份文书换一个新会话,而不是 compact。

SDK 自带的 auto-compact 是**把历史总结成一段话**(窗口 −33k 触发,见
:class:`~flower.core.agent.CompactPolicy`)。它和这个框架其余部分是拧着的:

    spill_guard   工具返回的那一刻      大结果落盘,上下文留一行路径
    冻结件        那一步结束时          一份文书,下一步只读它
    auto-compact  上下文满了才回头      一段模型自己写的摘要,你看不见也管不着

flower 从头到尾在做的是**当场决定什么该留**,compact 是唯一一处"事后补救",
而且过程不可见、结果不可读、不可干预。

换成:到阈值就让它写一份交接,然后**换一个新会话接手**。这和确认书、目标
是同一件事的第三个实例 —— 而且这正是这个项目自己的做法(仓库根的 `HANDOFF.md`)。

五段,每一段挡一类"接手的人会犯的错":

    现在在做什么   挡"接手的人不知道自己站在哪"
    已经定下的     挡"重新讨论已经定过的事"(要写**为什么**)
    走不通的路     **最贵的一段** —— HT002 花一小时试编译 flag,不写就再试一遍
    下一步         挡"接手的人先花半小时决定干什么"
    现场           关键文件与产出的**路径**。指针,不是内容

``complete()`` 只要求「现在在做什么」+「下一步」。硬性要求"走不通的路"非空
会逼出编造 —— 任务刚开头时它本来就该是空的。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .brief import _head_re, _sections

_ALIASES: dict[str, str] = {
    # 长的排前面,否则短的会先吃掉长的(见 _head_re)
    "现在在做什么": "doing",
    "走不通的路": "deadends",
    "已经定下的": "decided",
    "试过不行的": "deadends",
    "已定的事": "decided",
    "当前进度": "doing",
    "排除的路": "deadends",
    "现在在做": "doing",
    "下一步": "next",
    "现场": "scene",
    "进度": "doing",
    "决策": "decided",
    "文件": "scene",
}
CANON = {"doing": "现在在做什么", "decided": "已经定下的", "deadends": "走不通的路",
         "next": "下一步", "scene": "现场"}
ORDER = ("doing", "decided", "deadends", "next", "scene")
REQUIRED = ("doing", "next")
"""必填的两段。缺了它们,接手的人既不知道在哪也不知道往哪走。"""

_HEAD = _head_re(_ALIASES)

_OVERFLOW = re.compile(
    r"prompt is too long"
    r"|context[ _-]?length[ _-]?exceeded"
    r"|maximum context length"
    r"|exceed(?:s)? (?:the )?context (?:window|limit)"
    r"|too many total text bytes"
    r"|input length and `?max_tokens`? exceed",
    re.I,
)


def is_overflow(*texts: str | None) -> bool:
    """这条报错是不是"上下文装不下了"。

    **为什么需要认它**:窗口大小只能按模型名判,判大了的话换代阈值永远够不着,
    而 auto-compact 又是关掉的 —— 那就撞死在 API 上了。认出这个信号,
    就能把"硬错"变成"当场换代",于是判大了的代价从"这一步失败"降到
    "这一代的交接是降级的"。默认值因此可以取积极的一侧(见
    :func:`~flower.core.agent.default_window`)。
    """
    return any(t and _OVERFLOW.search(t) for t in texts)


DEGRADED = "[降级:交接没写成]"
"""机械拼出来的残缺交接的标记。见 :func:`degraded`。"""


@dataclass
class Handoff:
    """一次换代留下的全部东西。接手的会话**只有它和磁盘**。"""

    doing: str = ""
    decided: str = ""
    deadends: str = ""
    next: str = ""
    scene: str = ""
    step: str = ""
    """哪个步骤换的代。只用于文书抬头,不参与解析。"""
    path: Path | None = field(default=None, compare=False)

    # --- 完整性 -------------------------------------------------------
    def missing(self) -> list[str]:
        return [CANON[k] for k in REQUIRED if not getattr(self, k).strip()]

    def complete(self) -> bool:
        return not self.missing()

    @property
    def degraded(self) -> bool:
        return DEGRADED in self.doing

    # --- 解析与序列化 --------------------------------------------------
    @classmethod
    def parse(cls, text: str, *, step: str = "") -> Handoff:
        sec = _sections(text, _HEAD, _ALIASES)
        return cls(step=step, **{k: sec.get(k, "").strip() for k in ORDER})

    def to_markdown(self) -> str:
        head = f"# 交接书{f'({self.step})' if self.step else ''}"
        parts = [head, "",
                 "> 上一段会话的上下文快满了,写下这份交接换新会话接手。",
                 "> **这个文件是可读可改的** —— 觉得它漏了什么,直接改,接手的人读的就是它。",
                 ""]
        for k in ORDER:
            parts += [f"## {CANON[k]}", "", getattr(self, k).strip() or "(空)", ""]
        return "\n".join(parts).rstrip() + "\n"

    def prompt_block(self) -> str:
        """交给接手那个会话的开场白。

        抬头那句话是有用的:**明确告诉它自己是接手的人**,否则它容易以为
        对话刚开始,回头找人要背景 —— 而人可能不在。
        """
        body = "\n\n".join(f"## {CANON[k]}\n{getattr(self, k).strip()}"
                           for k in ORDER if getattr(self, k).strip())
        return (
            "你在接手一段还没干完的活。上一个会话的上下文满了,它留下了这份交接。\n"
            "**你没有它的记忆,只有这份文书和磁盘上的东西。** 需求和目标是冻结件,"
            "在工作台的 notes/ 里,自己去读。\n\n"
            f"{body}\n\n---\n\n照「下一步」接着做。别重头开始,也别回头问人要背景。"
        )

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_markdown(), encoding="utf-8")
        self.path = p.resolve()
        return self.path

    @classmethod
    def load(cls, path: str | Path) -> Handoff | None:
        p = Path(path)
        if not p.is_file():
            return None
        try:
            h = cls.parse(p.read_text(encoding="utf-8"))
        except OSError:
            return None
        h.path = p.resolve()
        return h


HANDOFF_PROMPT = """\
停一下。你这个会话的上下文快满了({used} / 窗口 {window}),**要换一个新会话接着干**。

现在写一份交接书。照下面五段输出,别写别的。

## 现在在做什么
一两句。接手的人要先知道自己站在哪。

## 已经定下的
已经拍板、不该再讨论的东西,**每条都带上为什么**。
只写"是什么"的话,接手的人下次照样会把它推翻重来。

## 走不通的路
试过并且排除掉的路,**以及为什么不行**。

**这一段最贵,也最容易被你漏掉。** 你会自然地写你做成了什么,
而忘记写你试过什么不行 —— 但后者恰恰是接手的人最花钱重新发现的东西。
实测代价:有一次为一个编译问题绕了一小时,那一小时的结论要是没写下来,
接手的人会原样再绕一遍。

真的还没排除过任何路,就写"(暂无)"。**别编。**

## 下一步
具体到接手的人能直接动手。不是"继续完善",是"跑 X,如果 Y 就改 Z"。

## 现场
关键文件、产出物、分支的**路径**。

---

三条纪律:

1. **自足。** 接手的人只有这份文书和磁盘,**没有你的记忆**。
   你觉得"这还用说吗"的东西,正是它不知道的。
2. **指针不是内容。** 别把代码、日志、命令输出贴进来 —— 写路径。
   贴进来等于把省下的上下文又花回去。
3. **不要复述需求和目标。** 它们是冻结件,在工作台的 notes/ 里,接手的人自己会读。
"""
"""让当前会话写交接的那句话。**不是一个新角色** —— 只有它自己有那段上下文,
换谁来写都得先把上下文读一遍,那就白费了。"""


def degraded(step: str, prompt: str, *, why: str = "") -> Handoff:
    """交接没写成时,用手上已知的东西机械拼一份。

    **为什么必须有它**:换代开着的时候 auto-compact 是关掉的,没有兵底。
    写交接那一轮要是失败了(网络、模型抽风、五段一段都没解析出来),
    既不能停在这里,也不能装作没事继续撑到硬上限 —— 那是真的会炸。

    残缺的交接远胜于撞窗口。标记 :data:`DEGRADED` 让接手的人知道
    它拿到的东西不完整,该自己去现场看。
    """
    return Handoff(
        step=step,
        doing=f"{DEGRADED} 上一个会话在步骤「{step}」里上下文满了,"
              f"但交接没能写出来{f'({why})' if why else ''}。",
        next="先去现场看清楚已经做到哪一步(读工作台的 notes/ 和产出物、"
             "看 git status / git log),再接着做。不要假设前面什么都没做。",
        scene=f"这一步最初拿到的任务是:\n\n{(prompt or '').strip()[:1200]}",
    )
