"""自动更新 —— 离线验证。**不打网络,不花钱**(远端探测全打桩)。

快速迭代期默认开、不给用户选(用户要求)。但更新绝不能变成新的故障源,
钉住三条不变式:

  1. **不阻塞**:后台线程,maybe_update 立刻返回。
  2. **不换掉正在跑的自己**:装新版只在启动时,装完不重启当前进程。
  3. **失败静默**:没网 / 装不上 / 从源码跑 —— 都不拦着人干活。

外加:节流(每天最多一次)、源码开发模式不自动 pip 覆盖、逃生口 FLOWER_NO_UPDATE。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flower.core.update as up          # noqa: E402

ok = True


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    os.environ["XDG_CONFIG_HOME"] = str(tmp / "cfg")
    sys.stdin.isatty = lambda: True       # 假装交互(否则直接不更新)

    print("\n[1] 节流:今天查过了就不再查")
    up.state_path().parent.mkdir(parents=True, exist_ok=True)
    up._write_state({"checked": time.time()})
    check(up.maybe_update() is None, "24 小时内查过 → 直接 None,不起线程")
    up._write_state({"checked": 0})
    check(time.time() - float(up._read_state().get("checked") or 0) > up.INTERVAL,
          "时间戳清零后就该查了")

    print("\n[2] 逃生口 / 非交互不折腾")
    os.environ["FLOWER_NO_UPDATE"] = "1"
    check(up.maybe_update() is None, "FLOWER_NO_UPDATE=1 → 不更新")
    os.environ.pop("FLOWER_NO_UPDATE")
    real_tty = sys.stdin.isatty
    sys.stdin.isatty = lambda: False
    check(up.maybe_update() is None, "非交互(管道/CI)→ 不更新")
    sys.stdin.isatty = real_tty

    print("\n[3] 不阻塞:立刻返回一个线程;远端探测打桩,不打网络")
    calls = {"installed": None}
    real_remote, real_local, real_inst, real_run = (
        up.remote_head, up.local_head, up._installer, up.subprocess.run)
    up.remote_head = lambda timeout=6.0: "newsha1234567"
    up.local_head = lambda: "oldsha7654321"
    up._installer = lambda: ["true"]      # 假装有个装法
    ran = {"n": 0}

    class R:
        returncode = 0
    def fake_run(cmd, **kw):
        ran["n"] += 1
        return R()
    up.subprocess.run = fake_run
    try:
        notes = []
        t0 = time.time()
        up._write_state({"checked": 0})
        t = up.maybe_update(lambda m: notes.append(m))
        dt = time.time() - t0
        check(t is not None and dt < 0.1, f"maybe_update {dt*1000:.0f}ms 内返回(不阻塞)")
        t.join(timeout=5)
        check(ran["n"] == 1, "后台真的调了一次安装命令(远端有新版)")
        check(any("下次" in m or "生效" in m for m in notes),
              "提示里点明**下次生效**,没有重启当前进程")
        check(up._read_state().get("installed") == "newsha1234567",
              "装好后记下新 sha,下次不再重复装")

        print("\n[4] 已是最新 → 不装")
        ran["n"] = 0
        up.local_head = lambda: "newsha1234567"    # 本地==远端
        up._write_state({"checked": 0})
        up.maybe_update(lambda m: None).join(timeout=5)
        check(ran["n"] == 0, "本地已是最新 sha → 一次安装都不跑")
    finally:
        up.remote_head, up.local_head, up._installer, up.subprocess.run = (
            real_remote, real_local, real_inst, real_run)

    print("\n[5] 从源码跑(有 .git)→ 不自动 pip 覆盖")
    # 真实环境:本仓库就是 git,_installer 应返回 None
    import subprocess
    here = Path(up.__file__).resolve().parent.parent.parent
    if (here / ".git").exists():
        check(up._installer() is None, "源码仓库 → _installer 返回 None,交给 git,不碰")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'✓ 自动更新全部通过' if ok else '✗ 有失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
