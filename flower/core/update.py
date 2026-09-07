"""自动更新 —— 快速迭代期,朋友必须跑在最新版上。

**默认开,不给选择**(用户明确要求):还在快速迭代,一个装了三天前版本的人
报回来的 bug 可能早就修了,双方都在浪费时间。

三条不变式,每条都是"别把更新变成新的故障源":

  1. **绝不阻塞干活**。检查在后台线程做,主流程一秒都不等。
  2. **绝不在跑到一半时换掉自己**。装新版只在**进程启动时**做,
     而且装完不重启当前进程 —— 下一次 `flower` 才用新版。
     跑到一半被换掉是最难查的一类故障。
  3. **失败一律静默**。没网、GitHub 挂了、装不上 —— 都不该拦住你干活。

节流:每天最多查一次(时间戳记在 ~/.config/flower/.update)。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .env import user_env_path

REPO = "ChenyuHeee/flower"
SPEC = f"git+https://github.com/{REPO}.git"
INTERVAL = 24 * 3600          # 每天最多查一次
DISABLE = "FLOWER_NO_UPDATE"  # 逃生口:CI / 离线环境 / 调试时用


def state_path() -> Path:
    return user_env_path().parent / ".update"


def _read_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(d: dict) -> None:
    try:
        p = state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass


def local_head() -> str | None:
    """当前装的是哪个 commit。从源码跑时用 git,pip 装的用记录下来的。"""
    here = Path(__file__).resolve().parent.parent.parent
    if (here / ".git").exists():
        try:
            r = subprocess.run(["git", "-C", str(here), "rev-parse", "HEAD"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception:                          # noqa: BLE001
            pass
    return _read_state().get("installed")


def remote_head(timeout: float = 6.0) -> str | None:
    """GitHub 上 main 的最新 commit。用 API,不需要 git。"""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/commits/main",
            headers={"Accept": "application/vnd.github.sha",
                     "User-Agent": "flower-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode().strip() or None
    except Exception:                              # noqa: BLE001 —— 没网就算了
        return None


def _installer() -> list[str] | None:
    """按当初的装法选更新命令。从 git 源码跑的**不动**(那是开发者)。"""
    here = Path(__file__).resolve().parent.parent.parent
    if (here / ".git").exists():
        return None                                # 源码开发:交给 git,别碰
    import shutil                                  # noqa: PLC0415
    if shutil.which("uv"):
        return ["uv", "tool", "install", "--force", SPEC]
    if shutil.which("pipx"):
        return ["pipx", "install", "--force", SPEC]
    return [sys.executable, "-m", "pip", "install", "--user", "--upgrade", SPEC]


def _do_update(note) -> None:
    remote = remote_head()
    if not remote:
        return
    _write_state({**_read_state(), "checked": time.time()})
    if remote == local_head():
        return                                     # 已经是最新
    cmd = _installer()
    if not cmd:
        return
    note(f"发现新版本({remote[:7]}),后台更新中…")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception:                              # noqa: BLE001
        return
    if r.returncode == 0:
        _write_state({"checked": time.time(), "installed": remote})
        note(f"已更新到 {remote[:7]} —— **下次跑 flower 生效**(这次继续用当前版本)")


def maybe_update(note=None) -> threading.Thread | None:
    """在后台查一次并更新。**立刻返回,绝不阻塞。**

    返回那个线程(测试用);不该更新时返回 ``None``。
    """
    if os.environ.get(DISABLE) or not sys.stdin.isatty():
        return None                                # CI/管道:不折腾
    st = _read_state()
    if time.time() - float(st.get("checked") or 0) < INTERVAL:
        return None                                # 今天查过了
    say = note or (lambda _m: None)
    t = threading.Thread(target=lambda: _do_update(say), daemon=True)
    t.start()                                      # daemon:它绝不拖住退出
    return t
