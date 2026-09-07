"""凭证配置 —— 离线验证。**不打网络,不花钱。**

分发要成立,凭证这一关必须顺:朋友 curl 一句装完,`flower` 得能引导他配好,
而不是甩个"缺少凭证"让他自己去翻文档、编辑 site-packages 里够不着的 .env。

钉住:
  1. .env 查找按 项目本地 → 每人全局 → 源码根 → Claude Code 回退,先到先赢
  2. Claude Code 回退只取 KNOWN 那几个凭证键,不接管别的
  3. run_setup 交互问 → chmod 600 写 ~/.config/flower/.env → 立即生效
  4. flower setup 是个子命令;缺凭证时三个跑活入口都会先 ensure_credentials
  5. token 前缀决定写 API_KEY 还是 AUTH_TOKEN
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flower.core.env as env                      # noqa: E402
import flower.cli as cli                            # noqa: E402

ok = True


def check(cond, msg):
    global ok
    print(f"  {'✓' if cond else '✗'} {msg}")
    if not cond:
        ok = False


def clean_env():
    for k in list(env.KNOWN) + ["FLOWER_ENV"]:
        os.environ.pop(k, None)


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    os.environ["XDG_CONFIG_HOME"] = str(tmp / "cfg")

    print("\n[1] .env 查找优先级:项目本地盖过每人全局,进程环境盖过一切")
    clean_env()
    (tmp / "cfg" / "flower").mkdir(parents=True, exist_ok=True)
    env.user_env_path().write_text(
        "ANTHROPIC_AUTH_TOKEN=global-tok\nANTHROPIC_BASE_URL=https://global\n", encoding="utf-8")
    proj = tmp / "proj"
    proj.mkdir()
    (proj / ".env").write_text("ANTHROPIC_BASE_URL=https://project\n", encoding="utf-8")
    cwd = os.getcwd()
    os.chdir(proj)
    try:
        env.load_dotenv()
        check(os.environ.get("ANTHROPIC_BASE_URL") == "https://project",
              "cwd/.env 的 BASE_URL 盖过 ~/.config 的")
        check(os.environ.get("ANTHROPIC_AUTH_TOKEN") == "global-tok",
              "cwd 没给 token → 从 ~/.config 补上(先到先赢,不是二选一)")
        clean_env()
        os.environ["ANTHROPIC_BASE_URL"] = "https://from-process"
        env.load_dotenv()
        check(os.environ.get("ANTHROPIC_BASE_URL") == "https://from-process",
              "进程环境盖过所有文件(不被覆盖)")
    finally:
        os.chdir(cwd)

    print("\n[2] Claude Code 回退只取凭证键,读不动不炸")
    fake_home = tmp / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "settings.json").write_text(
        '{"env": {"ANTHROPIC_AUTH_TOKEN": "cc-tok", "ANTHROPIC_BASE_URL": "https://cc",'
        ' "SOME_OTHER_THING": "should-not-be-taken"}, "model": "x"}', encoding="utf-8")
    real_home = os.environ.get("HOME")
    os.environ["HOME"] = str(fake_home)
    try:
        cc = env._claude_code_env()
        check(cc.get("ANTHROPIC_AUTH_TOKEN") == "cc-tok", "取到了 token")
        check("SOME_OTHER_THING" not in cc, "env 块里的非凭证键**不取**(只借去哪找 token)")
        (fake_home / ".claude" / "settings.json").write_text("不是 json{{", encoding="utf-8")
        check(env._claude_code_env() == {}, "settings.json 坏了 → 返回空,不抛")
    finally:
        if real_home:
            os.environ["HOME"] = real_home

    print("\n[3] run_setup:交互问 → chmod 600 写盘 → 立即生效")
    clean_env()
    os.environ["XDG_CONFIG_HOME"] = str(tmp / "cfg2")
    answers = iter(["sk-ant-realkey", "", ""])           # 官方 key,网关/模型都回车
    import builtins, io
    real_input, builtins.input = builtins.input, lambda *a: next(answers)
    real_tty, sys.stdin.isatty = sys.stdin.isatty, lambda: True
    try:
        real_out, sys.stdout = sys.stdout, io.StringIO()   # 吞掉设置界面的输出
        try:
            done = cli.run_setup(reason="测试")
        finally:
            sys.stdout = real_out
        check(done is True, "配好了返回 True")
        p = env.user_env_path()
        check(p.is_file() and oct(p.stat().st_mode)[-3:] == "600",
              f"写到 {p.name} 且 chmod 600(里面有 token)")
        body = p.read_text(encoding="utf-8")
        check("ANTHROPIC_API_KEY=sk-ant-realkey" in body,
              "sk-ant- 前缀 → 写 API_KEY(不是 AUTH_TOKEN)")
        check("ANTHROPIC_BASE_URL" not in body, "网关留空 → 不写 BASE_URL(用官方默认)")
        check(env.check_credentials() is None, "写完立即生效")
    finally:
        builtins.input, sys.stdin.isatty = real_input, real_tty

    print("\n[4] 非交互(管道/CI)下 run_setup 不阻塞,返回 False")
    sys.stdin.isatty = lambda: False
    try:
        check(cli.run_setup(reason="x") is False, "不是终端 → 直接 False,让调用方打印指引退出")
    finally:
        sys.stdin.isatty = real_tty

    print("\n[5] setup 是子命令;跑活入口会先 ensure_credentials")
    ap = cli.build_parser()
    check(ap.parse_args(["setup"]).fn.__name__ == "_run_setup_cmd", "flower setup 存在")
    src = Path("flower/cli.py").read_text(encoding="utf-8")
    for fn in ("_run_go", "_run_workflow", "_run_once"):
        block = src.split(f"async def {fn}(args)", 1)[1][:200]
        check("ensure_credentials()" in block, f"{fn} 开头调用了 ensure_credentials")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'✓ 凭证配置全部通过' if ok else '✗ 有失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
