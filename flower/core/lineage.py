"""血缘 —— 让「同一个路径」等于同一段对话。

**用户不需要知道 session 这个词。** 在同一个目录再跑一次 flower,它应该接着
上次说,而不是从零开会话 —— 哪怕上次是被 kill 掉的。

在此之前,step → session_id 的映射只活在 ``ctx["_sessions"]`` 里,进程一退就没了。
磁盘上其实什么都在(``sessions.db`` 有全量 transcript、确认书和目标是冻结件、
代码就在工作区),**丢的只是那一行映射** —— 于是上次那个协调者派过谁、
试过哪些死路、为什么否掉某个方案,全部重来一遍。实测代价:HT002 里
绕了一小时去试编译 flag,新进程会不知道那些路走不通。

这个文件就是把那一行映射落到盘上,别的什么都不做。

两条不变式:

* **每一步跑完立刻写盘**,不是退出时写 —— 进程被 kill 正是要防的场景。
* **路径对不上就当没有。** ``workspace`` 存在文件里做守卫:SDK 的 project_key
  从工作区路径推导,目录被拷走(HT001 就是从容器拷出来的)之后那些 session_id
  在新位置根本查不到。这时候静默退回新会话,**不报错** —— 接续是锦上添花,
  它失效不该拦住人干活。
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

FILENAME = "lineage.json"


@dataclass
class Lineage:
    """``<run_dir>/lineage.json``:步骤名 → session_id,外加唤醒次数。

    步骤名是**跨进程稳定**的键 —— 这是整个设计成立的前提。判定者那种带轮次的
    名字(``干活·判定#1``)不走这里,见 :mod:`~flower.workflow.goal`。
    """

    path: Path
    workspace: Path
    steps: dict[str, str] = field(default_factory=dict)
    woke: int = 0

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.workspace = Path(self.workspace).resolve()

    # ---- 读 ------------------------------------------------------------
    @classmethod
    def open(cls, run_dir: str | Path, workspace: str | Path) -> Lineage:
        """读已有的血缘。文件不存在、读不动、或**工作区对不上**都返回空的。

        对不上时不是错误:换目录跑就是"另一件事",本来就该从头开始。
        """
        ws = Path(workspace).resolve()
        p = Path(run_dir) / FILENAME
        lin = cls(path=p, workspace=ws)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return lin
        if not isinstance(data, dict) or data.get("workspace") != str(ws):
            return lin                       # 目录被拷走/换了位置 —— 当没有
        steps = data.get("steps")
        if isinstance(steps, dict):
            lin.steps = {str(k): str(v) for k, v in steps.items() if v}
        lin.woke = int(data.get("woke") or 0)
        return lin

    # ---- 写 ------------------------------------------------------------
    def remember(self, step: str, session_id: str) -> None:
        """记住这一步用了哪个 session,**立刻落盘**。"""
        if not step or not session_id:
            return
        self.steps[step] = session_id
        self._flush()

    def bump(self) -> int:
        """第几次唤醒(第一次跑是 1)。落盘,给 UI 显示。"""
        self.woke += 1
        self._flush()
        return self.woke

    def _flush(self) -> None:
        payload = {"workspace": str(self.workspace), "woke": self.woke,
                   "steps": self.steps}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(self.path)          # 原子替换:被 kill 也不会留半份
        except OSError:
            pass                            # 落盘失败不该带走这次运行

    # ---- 归档 ----------------------------------------------------------
    def archive(self, into: str | Path, *, extra: list[Path] | None = None) -> Path:
        """``--new`` / ``/new``:把这一段收进档案,下次从头开始。

        **移动而不是删除**,和"追加不覆盖"同一个道理:看得见改了什么比看不见好。
        ``extra`` 里通常是确认书和目标 —— 它们和血缘是同一段历史的三个面,
        只归档其中一部分会留下"目标还在但对话没了"这种半截状态。
        """
        dest = Path(into) / time.strftime("%Y%m%d-%H%M%S")
        dest.mkdir(parents=True, exist_ok=True)
        for f in [self.path, *(extra or [])]:
            f = Path(f)
            if f.is_file():
                try:
                    shutil.move(str(f), str(dest / f.name))
                except OSError:
                    pass
        self.steps, self.woke = {}, 0
        return dest
