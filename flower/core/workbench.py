"""工作台 —— 让琐碎沉淀到磁盘,而不是堆在上下文里。

三个目录,都在工作区内(agent 的 Read/Bash 够得到):

    .flower/scripts/    可复用的验证脚本。写一次,以后直接跑,不再重写
    .flower/artifacts/  长产出:报告、数据、日志。对话里只出现路径
    .flower/notes/      跨 step 的决策记录

工作台默认落在工作区里(`<workspace>/.flower/`)。但**开了 worktree 隔离时必须放到
仓库外面** —— 被隔离的 agent 会被围栏挡住,写不进共享 checkout(实测原文:
"This agent is isolated in the worktree ..., Edit the worktree copy of this file
instead of the shared-checkout path")。工作台是**跨 agent 共享**的沉淀层,
worktree 是**每个 agent 私有**的工作副本,两者正交:共享的东西不能放进私有围栏里。
用 ``home=`` 指定仓库外的位置即可(实测:隔离 agent 写仓库外路径不受限)。

`INDEX.md` 是它们的目录页,并且**被注入进每个 agent 的 system prompt**。
这一条是关键:agent 开局就知道有哪些现成脚本,不用先花一次工具调用去发现。
压缩能清掉工具结果,但清不掉磁盘上的文件,也清不掉 system prompt 里的索引 ——
所以"微压缩后丢失、每次重写"这个问题在这一层被解决,而不是在压缩策略里。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_DESC = re.compile(r"^\s*(?:#|//|--)\s*desc\s*[::]\s*(.+)$", re.IGNORECASE)


def _human(n: int) -> str:
    return f"{n}B" if n < 1024 else (f"{n/1024:.1f}K" if n < 1024**2 else f"{n/1024**2:.1f}M")


@dataclass
class Workbench:
    """工作区内的沉淀层。目录 + 索引 + 注入 system prompt 的那段文字。"""

    workspace: Path
    dirname: str = ".flower"
    max_index_entries: int = 40
    home: Path | None = None
    """工作台根目录。None = ``<workspace>/.flower``。
    开 worktree 隔离时要指到仓库外面,否则被隔离的 agent 写不进来。"""

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        if self.home is not None:
            self.home = Path(self.home).resolve()

    # --- 路径 ---------------------------------------------------------
    @property
    def root(self) -> Path:
        return self.home if self.home is not None else self.workspace / self.dirname

    @property
    def external(self) -> bool:
        """工作台是否在工作区之外(隔离模式下应当如此)。"""
        return not self.root.is_relative_to(self.workspace)

    def show(self, p: Path) -> str:
        """给模型看的路径:在工作区内就用相对路径,在外面必须给绝对路径。"""
        return str(p) if self.external else str(p.relative_to(self.workspace))

    @property
    def scripts(self) -> Path:
        return self.root / "scripts"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def notes(self) -> Path:
        return self.root / "notes"

    @property
    def index_path(self) -> Path:
        return self.root / "INDEX.md"

    def ensure(self) -> Workbench:
        for d in (self.scripts, self.artifacts, self.notes):
            d.mkdir(parents=True, exist_ok=True)
        return self

    # --- 扫描 ---------------------------------------------------------
    def _describe(self, f: Path) -> str:
        """脚本自述:首几行里的 `# desc: ...`,退化到第一行非空注释。"""
        try:
            head = f.read_text(encoding="utf-8", errors="replace").splitlines()[:8]
        except OSError:
            return ""
        for line in head:
            if m := _DESC.match(line):
                return m.group(1).strip()
        for line in head:
            s = line.strip()
            if s.startswith(("#", "//", "--")) and len(s) > 3:
                return s.lstrip("#/- ").strip()[:100]
            if s.startswith(('"""', "'''")):
                return s.strip("\"' ")[:100]
        return ""

    def scan(self, d: Path) -> list[tuple[str, str, int]]:
        if not d.is_dir():
            return []
        out = []
        for f in sorted(d.rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            out.append((self.show(f), self._describe(f), f.stat().st_size))
        return out

    # --- 索引 ---------------------------------------------------------
    def refresh(self) -> str:
        """把当前磁盘状态写成 INDEX.md,并返回内容。"""
        self.ensure()
        lines = ["# 工作台索引", "", "> 自动生成,勿手改。scripts 首行写 `# desc: 一句话` 会出现在这里。", ""]
        for title, d in (("可复用脚本", self.scripts), ("产出", self.artifacts), ("决策记录", self.notes)):
            items = self.scan(d)
            lines.append(f"## {title}({len(items)})")
            lines.extend(
                [f"- `{p}` — {desc or '(无说明)'} ({_human(n)})" for p, desc, n in items] or ["- (空)"]
            )
            lines.append("")
        text = "\n".join(lines)
        self.index_path.write_text(text, encoding="utf-8")
        return text

    def prompt_block(self) -> str:
        """注入 system prompt 的那一段。有意做短 —— 它每轮都在。"""
        self.ensure()
        parts = [f"# 工作台 {self.show(self.root)}/", ""]
        if self.external:
            # 隔离模式:agent 在自己的 worktree 里,工作台在仓库外,必须走绝对路径。
            parts += [f"它在**仓库外**(`{self.root}`)—— 这是有意的,这样每个 agent "
                      "不管在哪个工作副本里都能读写同一份。**用绝对路径访问它。**", ""]
        parts.append("已经存在的东西,**先用,不要重写**:")
        empty = True
        for title, d in (("脚本", self.scripts), ("产出", self.artifacts), ("笔记", self.notes)):
            items = self.scan(d)
            if not items:
                continue
            empty = False
            parts.append(f"\n{title}:")
            for p, desc, n in items[: self.max_index_entries]:
                parts.append(f"- `{p}`{f' — {desc}' if desc else ''} ({_human(n)})")
            if len(items) > self.max_index_entries:
                parts.append(f"- …另有 {len(items) - self.max_index_entries} 个,`ls {d.relative_to(self.workspace)}/` 查看")
        if empty:
            parts.append("(目前为空)")
        parts += [
            "",
            "规则:",
            f"1. 任何要跑第二次的脚本 —— 验证、复现、检查 —— 写进 `{self.show(self.scripts)}/`,"
            "文件名说明用途,首行写 `# desc: 一句话`。下次直接跑,别重写。",
            f"2. 超过 2000 字符的产出 —— 日志、数据、报告、diff —— 写进 "
            f"`{self.show(self.artifacts)}/`,对话里只给路径和结论。",
            f"3. 关键决策与理由写进 `{self.show(self.notes)}/`,一个决策一个文件。",
        ]
        return "\n".join(parts)
