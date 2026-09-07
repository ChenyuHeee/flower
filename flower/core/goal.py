"""目标与判定 —— 长程运行的"这一轮算不算做完了"。

需求确认(:mod:`~flower.core.brief`)挡的是"做的是不是对的东西";
这一层挡的是**"做完了没有"**。两件事分开,因为它们的失败方式不同:

* 需求错 → 每一个产出都是照错的需求建的,越跑越贵。所以要在开工前一次性问清。
* 完成度判断错 → 主 agent 自己说"做完了"就收工。**它有系统性的乐观偏差** ——
  跑了一半的测试、改了一处漏了三处、"应该没问题"。所以判定不能由干活的人自己下。

所以判定交给一个**独立 session 的角色**:它没写工具、拿到的只有目标和现场,
不知道干活那个人有多辛苦,也就不会替它找理由。

三个结论,不是两个:

    达成      → 往下走
    未达成    → 打回干活的人,带上"差在哪",让它**接着做**(不是重头做)
    无法达成  → 这一轮再试也没用。停下来问人:接受 / 改目标 / 你判断错了

第三个结论是关键。只有"达成/未达成"的话,一个其实做不到的目标会让主 agent
一轮一轮空转到额度用完 —— 那才是真的烧钱。

**解析只认那几段,别的一律丢掉** —— 和 :class:`~flower.core.brief.Brief` 同一个理由:
模型会在结论之外多写东西,不能让它污染下游。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .brief import _clean, _strip_code

# --- 目标 -------------------------------------------------------------

_GOAL_ALIASES: dict[str, str] = {
    "判定清单": "checks",
    "判定条件": "checks",
    "验收清单": "checks",
    "检查项": "checks",
    "判定": "checks",
    "目标": "statement",
    "完成标志": "statement",
}
GOAL_CANON = {"statement": "目标", "checks": "判定清单"}
GOAL_ORDER = ("statement", "checks")

# --- 判定 -------------------------------------------------------------

_V_ALIASES: dict[str, str] = {
    "未通过": "failed",
    "结论": "state",
    "理由": "reason",
    "依据": "reason",
    "判定": "state",
}
V_CANON = {"state": "结论", "reason": "理由", "failed": "未通过"}
V_ORDER = ("state", "reason", "failed")

ACHIEVED, NOT_YET, UNREACHABLE = "achieved", "not_yet", "unreachable"

# 结论那一段里认什么算什么。**长的排前面**,否则"达成"会先吃掉"无法达成"。
_STATE_WORDS: tuple[tuple[str, str], ...] = (
    # "在这个环境里验不了"也归到 unreachable —— 再来一轮同样验不了,
    # 而且它**绝不能**被判成通过。实测栽过:目标平台 macOS、运行在 Linux 容器里,
    # 判定者看了源码里的 Darwin 分支就判了通过,而交付的二进制是 Linux ELF。
    ("无法验证", UNREACHABLE), ("没法验证", UNREACHABLE), ("验证不了", UNREACHABLE),
    ("无法判定", UNREACHABLE), ("unverifiable", UNREACHABLE),
    ("无法达成", UNREACHABLE), ("不可达成", UNREACHABLE), ("做不到", UNREACHABLE),
    ("unreachable", UNREACHABLE), ("impossible", UNREACHABLE),
    ("未达成", NOT_YET), ("没达成", NOT_YET), ("尚未达成", NOT_YET),
    ("not_yet", NOT_YET), ("not yet", NOT_YET), ("no", NOT_YET),
    ("已达成", ACHIEVED), ("达成", ACHIEVED), ("achieved", ACHIEVED), ("yes", ACHIEVED),
)


def _head_re(aliases: dict[str, str]) -> re.Pattern[str]:
    """和 brief.py 同一个形状的标题行匹配:容忍 `## X` / `**X**` / `X:` / `1. X`。"""
    labels = "|".join(sorted(aliases, key=len, reverse=True))
    return re.compile(
        r"^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*|__)?[ \t]*(?:\d+[.、)][ \t]*)?"
        rf"({labels})"
        r"(?:\*\*|__)?[ \t]*[:：]?[ \t]*(.*)$",
        re.MULTILINE,
    )


_GOAL_HEAD = _head_re(_GOAL_ALIASES)
_V_HEAD = _head_re(_V_ALIASES)


def _sections(text: str, head: re.Pattern[str], aliases: dict[str, str]) -> dict[str, str]:
    body = _strip_code(text or "")
    hits = list(head.finditer(body))
    out: dict[str, str] = {}
    for i, m in enumerate(hits):
        key = aliases[m.group(1)]
        end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
        chunk = _clean(f"{m.group(2) or ''}\n{body[m.end():end]}")
        if chunk and key not in out:      # 同名段重复出现时取第一个
            out[key] = chunk
    return out


def _bullets(text: str) -> list[str]:
    """一条一行。去掉 `-` / `*` / `1.` 这些记号。"""
    items = []
    for ln in (text or "").splitlines():
        s = re.sub(r"^[ \t]*(?:[-*+]|\d+[.、)])[ \t]*", "", ln).strip()
        if s:
            items.append(s)
    return items


@dataclass
class Goal:
    """冻结的目标:一句话 + 一份可判定的清单。

    ``checks`` 是这层的关键。"做好了"没法判定,"跑 `python conv.py a.md` 产出
    `a.html` 且含 `<h1>`"才能判定。清单从确认书的「验收标准」来,
    但要被改写成**每条都能当场验证**的形式。
    """

    statement: str = ""
    checks: list[str] = field(default_factory=list)
    path: Path | None = None

    UNVERIFIABLE = re.compile(r"\[\s*(?:此环境)?无法验证\s*[::]?")
    """判定清单里"这条在当前环境验不了"的标记。见 ``JUDGE_RULES`` 的设定目标一节。"""

    @property
    def unverifiable(self) -> list[str]:
        """标了"此环境无法验证"的条目。

        **为什么要单独拿出来**:这些条目的命运在**设目标那一刻**就定了 ——
        判定的时候必然过不去。实测栽过:HT002 花了 $35.90 干活 + $1.40 判定
        之后才发现清单里有 4/15 条原理上验不了,而那件事在设目标时就已成立。
        把发现提前到设目标那一步,成本从 $37 降到 $0。
        """
        return [c for c in self.checks if self.UNVERIFIABLE.search(c)]

    def missing(self) -> list[str]:
        return [GOAL_CANON[k] for k in GOAL_ORDER
                if not (self.checks if k == "checks" else self.statement.strip())]

    def complete(self) -> bool:
        return not self.missing()

    @classmethod
    def parse(cls, text: str) -> Goal:
        sec = _sections(text, _GOAL_HEAD, _GOAL_ALIASES)
        return cls(statement=sec.get("statement", "").strip(),
                   checks=_bullets(sec.get("checks", "")))

    def to_markdown(self) -> str:
        lines = [f"# {GOAL_CANON['statement']}", self.statement.strip(), "",
                 f"# {GOAL_CANON['checks']}"]
        lines += [f"- {c}" for c in self.checks] or ["(空)"]
        return "\n".join(lines) + "\n"

    def prompt_block(self) -> str:
        """喂给下游的那一段。"""
        out = [f"## {GOAL_CANON['statement']}", self.statement.strip()]
        if self.checks:
            out += ["", f"## {GOAL_CANON['checks']}"] + [f"- {c}" for c in self.checks]
        return "\n".join(out)

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_markdown(), encoding="utf-8")
        self.path = p.resolve()
        return self.path

    @classmethod
    def load(cls, path: str | Path) -> Goal | None:
        p = Path(path)
        if not p.is_file():
            return None
        try:
            g = cls.parse(p.read_text(encoding="utf-8"))
        except OSError:
            return None
        g.path = p.resolve()
        return g

    def amend(self, extra: str) -> Goal:
        """人说"改目标"时用。**追加**而不是覆盖 —— 原来的目标是历史,
        看得见改了什么比看不见好。"""
        extra = (extra or "").strip()
        if extra:
            self.statement = f"{self.statement.strip()}\n\n(已修改){extra}"
        return self


@dataclass
class Verdict:
    """一次判定的结果。``state`` 只有三个取值。"""

    state: str = ""
    reason: str = ""
    failed: list[str] = field(default_factory=list)

    @property
    def achieved(self) -> bool:
        return self.state == ACHIEVED

    @property
    def unreachable(self) -> bool:
        return self.state == UNREACHABLE

    @property
    def ok(self) -> bool:
        """解析出结论了吗。**解析不出不能当成达成** —— 见 :meth:`parse`。"""
        return self.state in (ACHIEVED, NOT_YET, UNREACHABLE)

    @classmethod
    def parse(cls, text: str) -> Verdict:
        """从判定者的回话里取结论。

        取不到结论时 ``state`` 留空,:attr:`ok` 为 False —— 调用方必须当成
        **未达成**处理,不能当成达成。"判定不出来"和"做完了"是两件事,
        把前者当后者就等于让一句含糊的话把活收了。

        除了 `结论:` 那一段,也认光秃秃的 `1` / `0` —— 判定者被要求"只传 0/1"时
        很可能就真的只回一个数字。
        """
        sec = _sections(text, _V_HEAD, _V_ALIASES)
        raw = sec.get("state", "")
        if not raw:
            # 没有标题段:整段拿来找结论词,或者认一个孤零零的 0/1
            stripped = _strip_code(text or "").strip()
            if re.fullmatch(r"1|true", stripped, re.I):
                return cls(state=ACHIEVED, reason="")
            if re.fullmatch(r"0|false", stripped, re.I):
                return cls(state=NOT_YET, reason="")
            raw = stripped
        low = raw.lower()
        state = ""
        for word, st in _STATE_WORDS:
            if word in low:
                state = st
                break
        if not state and re.search(r"\b1\b", raw):
            state = ACHIEVED
        elif not state and re.search(r"\b0\b", raw):
            state = NOT_YET
        return cls(state=state,
                   reason=sec.get("reason", "").strip(),
                   failed=_bullets(sec.get("failed", "")))

    def feedback(self) -> str:
        """打回给干活那个人的话。只给"差在哪",不给方案 —— 怎么补是它的活。"""
        parts = ["上一轮的产出**没有达成目标**。判定者给的理由:", "",
                 self.reason or "(没给理由)"]
        if self.failed:
            parts += ["", "没通过的判定项:"] + [f"- {f}" for f in self.failed]
        parts += ["", "接着做 —— 只处理上面这些差距,不要重头开始,也不要扩大范围。"]
        return "\n".join(parts)
