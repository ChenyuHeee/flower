"""给下一个工具的交接 —— 一次长程运行跑完后,在项目根写一份 CLAUDE.md / AGENTS.md,
让接手的 Claude Code / Codex 不用靠猜。

flower 会给**自己的接班会话**写 交接-<步骤>.md(见 :mod:`handoff`)。但一次运行
跑完之后,最终的接手者不是另一个 flower 会话 —— 是拿着 Claude Code 或 Codex 来
微调的用户本人。那一份交接此前不存在:新开的工具落进项目目录只能靠猜,而
「正文.md 是生成物,别直接改」这种知识只写在脚本 docstring 里,没人告诉它去读
(见 issue #24 的 novel 现场)。

和换代交接同一个模式(parse / complete / degraded / 模型写 + 机械兜底),只是:

  * 段落不同(这是什么 / 验收 / 生成物 / 走不通的路 / 工作台)
  * 落点不同:项目根的 ``CLAUDE.md`` + ``AGENTS.md``,不是 notes/交接-*.md
  * **绝不覆盖用户已有的 CLAUDE.md** —— 用带标记的受管块,重跑只替换块内(安全项)

尺寸纪律:这份文件会被下一个工具**每次会话**加载进缓存前缀(和 #22 同一笔账)。
指针不是内容,几十行封顶。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .brief import _head_re, _sections

_ALIASES: dict[str, str] = {
    # _head_re 会自动按长度排序,长的先匹配 —— 这里不必手排
    "哪些文件是生成的": "generated",
    "生成物与来源": "generated",
    "哪些是生成的": "generated",
    "达成与未达成": "acceptance",
    "走不通的路": "deadends",
    "试过不行的": "deadends",
    "工作台在哪": "workbench",
    "这是什么": "what",
    "生成物": "generated",
    "工作台": "workbench",
    "验收": "acceptance",
    "还差什么": "acceptance",
    "怎么读": "workbench",
    "任务": "what",
}
CANON = {
    "what": "这是什么",
    "acceptance": "验收:达成与未达成",
    "generated": "哪些文件是生成的、由什么生成",
    "deadends": "走不通的路",
    "workbench": "工作台在哪、怎么读",
}
ORDER = ("what", "acceptance", "generated", "deadends", "workbench")
REQUIRED = ("what", "workbench")
"""必填:接手的人至少要知道「这是什么」和「去哪看」。其余段落可能真的为空
(没有生成物 / 没试过死路),硬要求非空会逼出编造。"""

_HEAD = _head_re(_ALIASES)

# 受管块的边界标记。重跑只替换标记之间 —— 标记之外(用户自己的内容)一字不动。
BEGIN = "<!-- flower:begin 这块由 flower 收尾自动生成,重跑会覆盖;你的内容写在标记外面 -->"
END = "<!-- flower:end -->"

DEGRADED = "[降级:收尾交接没写成]"
"""机械拼出来的残缺交接的标记。见 :func:`mechanical`。"""


@dataclass
class Bequest:
    """给下一个工具的交接。接手的会话**只有它和磁盘**,没有这次运行的记忆。"""

    what: str = ""
    acceptance: str = ""
    generated: str = ""
    deadends: str = ""
    workbench: str = ""

    def missing(self) -> list[str]:
        return [CANON[k] for k in REQUIRED if not getattr(self, k).strip()]

    def complete(self) -> bool:
        return not self.missing()

    @property
    def degraded(self) -> bool:
        return DEGRADED in self.what

    @classmethod
    def parse(cls, text: str) -> "Bequest":
        sec = _sections(text, _HEAD, _ALIASES)
        return cls(**{k: sec.get(k, "").strip() for k in ORDER})

    def block_body(self) -> str:
        """受管块**里面**的正文(不含 BEGIN/END 标记)。"""
        parts = [
            "## flower 运行留下的交接",
            "",
            "> 这是一次 flower 长程运行跑完后留下的指针。你没有它的记忆,但需要的一切都",
            "> 在磁盘上 —— 下面告诉你去哪看。**别直接改被标成「生成物」的文件**,改它们的源头。",
            "",
        ]
        for k in ORDER:
            body = getattr(self, k).strip()
            if body:
                parts += [f"### {CANON[k]}", "", body, ""]
        return "\n".join(parts).rstrip()


def _wrap(body: str) -> str:
    return f"{BEGIN}\n{body.strip()}\n{END}"


def write_managed(path: str | Path, body: str) -> Path:
    """把受管块写进 ``path``,**绝不动用户已有的内容**。三种情形:

      * 文件里已有 begin/end 标记 → 只替换标记之间(重跑幂等)
      * 文件存在但没标记(用户自己的 CLAUDE.md)→ 末尾追加受管块,原内容一字不动
      * 文件不存在 → 新建,只有受管块

    这条是**安全项不是体验项**:静默吃掉别人的仓库约定是真实伤害。
    """
    p = Path(path)
    block = _wrap(body)
    p.parent.mkdir(parents=True, exist_ok=True)
    old = p.read_text(encoding="utf-8") if p.is_file() else ""
    # **只在恰好一对、且顺序正确时做外科替换。** 用户手删了一个标记(孤儿 BEGIN/
    # 或 END)、或标记错序 / 出现多对时,split(...,1) 那套会把标记之间的用户内容
    # 一并删掉 —— 那正是这条要防的"静默吃掉别人的仓库约定"(审查 #24 MEDIUM)。
    # 认不出干净的一对就退回安全追加:多堆一个块很难看,但绝不删用户的东西。
    clean_pair = (old.count(BEGIN) == 1 and old.count(END) == 1
                  and old.find(BEGIN) < old.find(END))
    if clean_pair:
        pre = old.split(BEGIN, 1)[0].rstrip()
        post = old.split(END, 1)[1].lstrip()
        new = "\n\n".join(c for c in (pre, block, post) if c).strip() + "\n"
    elif old.strip():
        new = old.rstrip() + "\n\n" + block + "\n"
    else:
        new = block + "\n"
    p.write_text(new, encoding="utf-8")
    return p.resolve()


def write_both(root: str | Path, body: str) -> list[Path]:
    """一份内容,两个名字:CLAUDE.md(Claude Code 自动加载)+ AGENTS.md(Codex 约定)。"""
    root = Path(root)
    return [write_managed(root / name, body) for name in ("CLAUDE.md", "AGENTS.md")]


def mechanical(*, what: str = "", workbench_hint: str = "", why: str = "") -> Bequest:
    """模型没写成时,用手上已知的东西机械拼一份 —— 和 :func:`handoff.degraded` 同一个模式。

    照样落盘、明确标注降级:残缺的指针也好过"什么都没有,自己猜"。生成物那条最值钱
    的它给不出(要模型看过现场才知道),但至少把接手的人指向工作台。
    """
    return Bequest(
        what=(f"{DEGRADED} 收尾时没能自动写出交接{f'({why})' if why else ''}。"
              f"{(what or '').strip() or '需求见工作台 notes/需求.md。'}"),
        workbench=(workbench_hint
                   or ".flower/ 工作台:notes/(需求、目标、决策、交接)、"
                      "artifacts/(产出)、scripts/(脚本 —— 有的产出是这里的脚本生成的,"
                      "别直接改生成物)。先读 notes/ 里的需求和交接。"),
    )


BEQUEST_PROMPT = """\
这次长程运行到此结束。写一份**给下一个工具的交接** —— 接手的不是另一个 flower,
是拿着 Claude Code 或 Codex 来微调的人。他落进这个项目目录,除了你这份交接,对这里
发生过什么一无所知。

先读工作台:notes/(需求、目标、决策、交接)、artifacts/(产出)、scripts/(脚本)。
然后照下面五段输出,别写别的。**指针不是内容,几十行封顶** —— 这份文件会被下一个
工具每次会话加载,写长了就是持续烧钱。

## 这是什么
一两句:这个项目是什么、当初要做的是什么。别复述整份需求。

## 验收:达成与未达成
判定的结论:哪些验收标准达成了,**哪几条没达成**。没达成的最要紧 —— 接手的人最
可能就是来补这些的。

## 哪些文件是生成的、由什么生成
**这一段最值钱。** 哪些文件是脚本 / 合并 / 导出生成的产物,由哪个脚本、从什么源头
生成。接手的人一旦直接改了生成物,下次一重新生成就被静默覆盖 —— 这正是这份交接要
防的事。没有生成物就写"(无)"。

## 走不通的路
试过并排除掉的路,以及为什么不行。**最贵也最容易失传** —— 不写下来,接手的人会原样
再绕一遍。没有就写"(无)"。

## 工作台在哪、怎么读
notes/ / artifacts/ / scripts/ 各放什么,接手的人该先读哪几个文件。给路径。

---

只输出这五段。每段**正文别以段名起行**(比如生成物那段,别用"生成物…"另起一行 ——
会被解析成新标题、把这段最值钱的内容丢掉)。**不要真去创建 CLAUDE.md 或 AGENTS.md**
—— 那两个文件由框架带着安全的受管块写(绝不覆盖别人已有的),你只负责内容。
"""
"""让**当前收尾会话**写这份交接的那句话。read-only 角色(见 :func:`roles.oracle`):
它读工作台、输出五段,框架负责安全落盘 —— managed-block 的安全逻辑不能交给模型。"""
