"""需求确认书 —— 澄清对话的**唯一**交付物。

澄清的问答是**现场**,不是决策。这和 subagent 的试错是同一性质的东西,
所以处理方式也一样:沉到磁盘,不进协调者的上下文。协调者从这份四段文书开局,
永远看不到那段来回。

四段是刻意选的,每一段都在挡一类具体的失败:

    目标        —— 挡"做出来不是想要的东西"
    验收标准    —— 挡"做完了没人能说它算不算完"
    边界        —— 挡范围蔓延。这一段管住下游每一个 subagent
    未知与假设  —— 挡**沉默的错误前提**。没问到的、超时落空的、自己猜的,
                   全写在这儿。错误前提没法完全避免,但可以让它显式

第四段是长程运行的保险丝。前三段任何一段写错,只要假设写在第四段,
后面的人读到就有机会拦住;埋掉了就只能等几小时后产出全废时才发现。

**解析只认这四段,别的一律丢掉。** 这不是洁癖:实测过澄清者会把整份代码贴进
回话(`/tmp/probe_ask.py`)。丢掉围栏代码块再取标题,是防它污染下游的最后一道。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# 规范名 + 模型爱写的变体。长的排前面,否则"未知"会先吃掉"未知与假设"。
_ALIASES: dict[str, str] = {
    "未知与假设": "unknowns",
    "未知项与假设": "unknowns",
    "范围边界": "bounds",
    "不做什么": "bounds",
    "验收标准": "accept",
    "验收条件": "accept",
    "未知项": "unknowns",
    "已知未知": "unknowns",
    "验收": "accept",
    "边界": "bounds",
    "假设": "unknowns",
    "未知": "unknowns",
    "目标": "goal",
}
CANON = {"goal": "目标", "accept": "验收标准", "bounds": "边界", "unknowns": "未知与假设"}
ORDER = ("goal", "accept", "bounds", "unknowns")

_LABEL_RE = "|".join(sorted(_ALIASES, key=len, reverse=True))

# 标题行。容忍 `## 目标` / `**目标**` / `目标:` / `3. 边界` 各种写法,
# 也容忍标题后面直接跟正文(`目标: 做一个 X`)。
_HEAD = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*|__)?[ \t]*(?:\d+[.、)][ \t]*)?"
    rf"({_LABEL_RE})"
    r"(?:\*\*|__)?[ \t]*[:：]?[ \t]*(.*)$",
    re.MULTILINE,
)

_FENCE = re.compile(r"```.*?```|~~~.*?~~~", re.S)
_BLANKS = re.compile(r"\n{3,}")


def _strip_code(text: str) -> str:
    """摘掉围栏代码块。模型贴进来的代码里可能有假标题,会把解析带偏。"""
    out = _FENCE.sub("\n", text)
    # 没闭合的围栏(输出被截断):从它开始全部不要
    if (i := out.find("```")) >= 0:
        out = out[:i]
    return out


def _clean(body: str) -> str:
    lines = [ln.rstrip() for ln in body.strip().splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    # 去掉分隔线和引用块 —— 都是排版,不是内容
    lines = [ln for ln in lines if not re.fullmatch(r"[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*", ln)]
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


@dataclass
class Brief:
    """冻结下来的需求。四段都非空才算完整。"""

    goal: str = ""
    accept: str = ""
    bounds: str = ""
    unknowns: str = ""
    path: Path | None = field(default=None, compare=False)
    """从哪个文件读出来的(如果是读的)。"""

    # --- 完整性 -------------------------------------------------------
    def missing(self) -> list[str]:
        """缺哪几段(用中文段名,直接可以拿去显示)。"""
        return [CANON[k] for k in ORDER if not getattr(self, k).strip()]

    def complete(self) -> bool:
        return not self.missing()

    # --- 解析与序列化 --------------------------------------------------
    @classmethod
    def parse(cls, text: str) -> Brief:
        """从澄清者的回话里取出四段。取不到的留空,由 :meth:`missing` 报出来。"""
        body = _strip_code(text or "")
        hits = list(_HEAD.finditer(body))
        found: dict[str, str] = {}
        for i, m in enumerate(hits):
            key = _ALIASES[m.group(1)]
            end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
            chunk = _clean(f"{m.group(2) or ''}\n{body[m.end():end]}")
            # 同一段出现多次:第一段有内容就用它
            if chunk and not found.get(key):
                found[key] = chunk
        return cls(**{k: found.get(k, "") for k in ORDER})

    def to_markdown(self) -> str:
        parts = [
            "# 需求确认书",
            "",
            "> 由 clarify 步骤生成并**冻结**。要改需求就改这个文件;",
            "> 想重新确认一遍,删掉它再跑。",
            "",
        ]
        for k in ORDER:
            parts += [f"## {CANON[k]}", "", getattr(self, k).strip() or "(未填)", ""]
        return "\n".join(parts).rstrip() + "\n"

    def prompt_block(self) -> str:
        """喂给下游 agent 的那一段。比 :meth:`to_markdown` 更紧,没有元信息。"""
        return "\n\n".join(
            f"## {CANON[k]}\n{getattr(self, k).strip()}" for k in ORDER if getattr(self, k).strip()
        )

    # --- 磁盘 ---------------------------------------------------------
    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_markdown(), encoding="utf-8")
        self.path = p.resolve()
        return self.path

    @classmethod
    def load(cls, path: str | Path) -> Brief | None:
        """读一份已有的确认书。不存在或读不动返回 ``None``。"""
        p = Path(path)
        if not p.is_file():
            return None
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return None
        b = cls.parse(text)
        # "(未填)" 是 to_markdown 的占位,不算内容
        for k in ORDER:
            if getattr(b, k).strip() == "(未填)":
                setattr(b, k, "")
        b.path = p.resolve()
        return b
