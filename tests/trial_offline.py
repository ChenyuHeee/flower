"""一键入口与模板的离线验证 —— **不发任何请求,零花费**。

钉住两件事。

**一、那个静默失效的 bug(已修)。**
``Runtime(workbench=True)``(即 CLI 的 ``-W``)把工作台放在 ``<run_dir>/workbench``,
而早先文档里的 ``flows.py`` 用 ``Path(".flower/notes")``(相对进程 cwd)——
**两个不同目录**。确认书写进 A,注入 system prompt 的索引扫的是 B,于是
"每个 subagent 开局就知道需求文件在哪"这条承诺从来没成立过,**而且不报错**。
修法:``Workflow.workbench`` + ``cli.py`` 自动发现(和 ``wf.channel`` 同一个先例)。
第 3 节是那条承诺的直接断言,第 6 节确认这条断言抓得到回归。

**二、一键入口的参数解析。**
``flower "帮我做一个 X"`` 不写子命令时自动补 ``go``。隐形子命令意味着用户不会有
"开关要写在子命令前面"的心理模型,所以两个位置都得能用 —— 第 7 节把各种写法钉住。

零花费怎么做到的:预置一份**完整**确认书 → ``clarify_step.when`` 返 False → 那一步跳过;
再加 ``--clarify-only`` / 单步模板 → 没有别的步骤 → 整条路径跑完一次 API 都没发。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

from flower import Brief, Workbench                                      # noqa: E402
from flower.cli import (_run_workflow, _with_default_cmd, ask_for_prompt,   # noqa: E402
                         build_parser)
from flower.core.human import HumanChannel                               # noqa: E402
from flower.core.runtime import Runtime                                  # noqa: E402
from flower.workflow.clarify import clarify_step                         # noqa: E402
from flower.workflow.starter import starter_flow                         # noqa: E402

ok = fail = 0


def check(cond: bool, msg: str) -> None:
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {msg}")
    else:
        fail += 1
        print(f"  ✗ {msg}")


def fresh(tmp: Path, name: str) -> Path:
    d = tmp / name
    subprocess.run(["rm", "-rf", str(d)], check=False)
    d.mkdir(parents=True)
    return d


COMPLETE_BRIEF = """\
# 目标
做一个能把 markdown 转成 html 的小工具。

# 验收标准
`python conv.py a.md` 产出 a.html;标题/列表/代码块三类都对。

# 边界
只做这三类语法;不做插件、不做主题、不做 watch 模式。

# 未知与假设
假设输入一定是 UTF-8。
"""


def main() -> int:                                          # noqa: C901
    tmp = ROOT / "tests" / "_ws_trial"
    tmp.mkdir(parents=True, exist_ok=True)
    trial = importlib.import_module("trial")
    cwd0 = Path.cwd()

    # ---------------------------------------------------------------
    print("\n[1] 模板 examples/trial.py 的接线")
    ws = fresh(tmp, "p1")
    os.chdir(ws)
    try:
        wf = trial.main()
        wb = wf.workbench
        check(wf.channel is not None, "wf.channel 挂上了(驱动靠它知道向谁回答)")
        check(isinstance(wb, Workbench), "wf.workbench 挂上了(驱动交给 Runtime)")
        bp = wb.notes / "需求.md"
        check(bp.parent == wb.notes, f"brief 在 wb.notes 下({wb.show(bp)})")
        check(bp.resolve().is_relative_to(wb.root), "brief 在 workbench.root 之内")
        check(not wb.external, "不开隔离时工作台在工作区内,不需要 add_dirs")
        check(len(wf.steps) == 2, "确认 + 干活 两步")
        check(wf.steps[1].resume_from is None,
              "干活那步 resume_from=None —— 那段问答从来没进过它的上下文")
        spec = wf.steps[0].spec
        check(not ({"Write", "Edit", "Bash", "Agent"} & set(spec.allowed_tools or [])),
              f"确认者白名单没有写工具:{spec.allowed_tools}")
        check(spec.workbench is False,
              "确认者 workbench=False(它执行不了那些'写进哪个目录'的规矩)")

        # -----------------------------------------------------------
        print("\n[2] cli 用的就是 wf.workbench 那个对象,不是自己另造一个")
        rt = Runtime(workspace=ws, run_dir=ws / "runs", workbench=(wf.workbench or False))
        check(rt.workbench is wf.workbench, "Runtime.workbench is wf.workbench(同一对象)")
        rt2 = Runtime(workspace=ws, run_dir=ws / "runs", workbench=True)
        check(rt2.workbench.root != wf.workbench.root,
              f"旧的 -W 指向别处({rt2.workbench.root.name}/),证明两者确实不同")
        rt2.close()

        # -----------------------------------------------------------
        print("\n[3] 那条承诺的直接断言:确认书出现在注入 system prompt 的索引里")
        Brief.parse(COMPLETE_BRIEF).write(bp)
        check("需求.md" in rt.workbench.prompt_block(),
              "prompt_block()(进 system prompt 的那段)里有 需求.md")
        check("需求.md" in rt.workbench.refresh(), "INDEX.md 里也有")
        rt.close()
        rt3 = Runtime(workspace=ws, run_dir=ws / "runs2", workbench=True)
        check("需求.md" not in rt3.workbench.prompt_block(),
              "旧写法的工作台索引里**没有** 需求.md(bug 的原貌)")
        rt3.close()

        # -----------------------------------------------------------
        print("\n[4] 已有完整确认书 → 跳过盘问,但需求照样灌进 ctx")
        ctx: dict = {}
        check(not wf.steps[0].when(ctx), "when() 返 False → 跳过,不再问一遍")
        got = ctx.get("确认需求", "")
        check("markdown" in got or "md" in got,
              "跳过时仍把四段灌进 ctx['确认需求'](否则下游拿到 KeyError)")
    finally:
        os.chdir(cwd0)

    # ---------------------------------------------------------------
    print("\n[5] 整条 CLI 路径 `run trial.py:main`:自动发现 → 跳过 → 干净退出(零请求)")
    ws = fresh(tmp, "p2")
    os.chdir(ws)
    try:
        (ws / "trial.py").write_bytes((ROOT / "examples" / "trial.py").read_bytes())
        Brief.parse(COMPLETE_BRIEF).write(ws / ".flower" / "notes" / "需求.md")
        # 只留确认那一步,免得第二步真的去派人干活(那才花钱)
        mod = importlib.import_module("trial")
        orig = mod.main
        mod.main = lambda: (lambda w: (w.steps.pop(), w)[1])(orig())
        args = argparse.Namespace(
            target="trial.py:main", workspace=str(ws), run_dir=str(ws / "runs"),
            verbose=False, workbench=False, trim=True,
        )
        asyncio.run(_run_workflow(args))
        mod.main = orig
        check(True, "_run_workflow 跑完,没有抛异常也没 sys.exit")
        check(not (ws / "runs" / "manifest.json").exists(),
              "没有 manifest —— Runtime.run() 一次都没进,零花费")
        check((ws / "runs" / "sessions.db").is_file(), "但库建好了(存储层照常装配)")
        check((ws / ".flower" / "INDEX.md").is_file(), "工作台索引已生成在项目内")
        # stop.set() 之后线程要退出,但它有 0.15s 轮询间隔 —— 给它一点时间。
        for _ in range(40):
            if not [t for t in threading.enumerate() if "flower" in t.name]:
                break
            time.sleep(0.05)
        check(not [t for t in threading.enumerate() if "flower" in t.name],
              "stop.set() 之后标准输入线程退出了")
    finally:
        os.chdir(cwd0)

    # ---------------------------------------------------------------
    print("\n[6] 这套断言抓得到回归吗:把 brief 挪回 cwd 相对路径试试")
    ws = fresh(tmp, "p3")
    os.chdir(ws)
    try:
        ch = HumanChannel(log_path=None, max_asks=1, timeout_s=0)
        bad = Path(".flower/notes/需求.md")          # 旧写法:相对 cwd,不在工作台里
        Brief.parse(COMPLETE_BRIEF).write(bad)
        _ = clarify_step(ch, brief_path=bad, prompt="x")
        rt4 = Runtime(workspace=ws, run_dir=ws / "runs", workbench=True)   # -W 的默认
        check("需求.md" not in rt4.workbench.prompt_block(),
              "旧写法下索引里确实没有 需求.md —— 第 3 节那条断言不是空转")
        rt4.close()
    finally:
        os.chdir(cwd0)

    # ---------------------------------------------------------------
    print("\n[7] 一键入口:`flower \"诉求\"` 的参数解析(不写子命令时自动补 go)")
    ap = build_parser()
    forms = [
        (["帮我做个 X"],                  {"cmd": "go", "ask": "帮我做个 X"}),
        (["go", "x"],                    {"cmd": "go", "ask": "x"}),
        (["run", "flows.py:main"],       {"cmd": "run", "target": "flows.py:main"}),
        (["once", "看一眼"],              {"cmd": "once", "prompt": "看一眼"}),
        (["-v", "x"],                    {"cmd": "go", "verbose": True}),
        (["x", "-v"],                    {"cmd": "go", "verbose": True}),
        (["-w", "/tmp/p", "x"],          {"cmd": "go", "workspace": "/tmp/p"}),
        (["x", "-w", "/tmp/p"],          {"cmd": "go", "workspace": "/tmp/p"}),
        (["--workspace=/tmp/p", "x"],    {"cmd": "go", "workspace": "/tmp/p"}),
        (["--clarify-only", "x"],        {"cmd": "go", "clarify_only": True}),
        (["x", "--clarify-only"],        {"cmd": "go", "clarify_only": True}),
        (["--asks", "12", "x", "--isolate"], {"cmd": "go", "asks": 12, "isolate": True}),
        (["-v", "run", "f.py:main"],     {"cmd": "run", "verbose": True}),
        # 光秃秃的 flower / 只有全局开关 → 也进 go,ask 留空走交互输入。
        # 命令行那对引号是纯负担:右引号打成中文 ” 的话 zsh 会一直等右引号
        # (dquote> 续行),看起来像卡住,其实一次都没启动。踩过。
        ([],                             {"cmd": "go", "ask": None}),
        (["-v"],                         {"cmd": "go", "ask": None, "verbose": True}),
        (["--clarify-only"],             {"cmd": "go", "ask": None, "clarify_only": True}),
        (["-w", "/tmp/p"],               {"cmd": "go", "ask": None, "workspace": "/tmp/p"}),
    ]
    for argv, want in forms:
        try:
            a = ap.parse_args(_with_default_cmd(argv, ap))
            bad_f = {k: (getattr(a, k, None), v) for k, v in want.items()
                     if getattr(a, k, None) != v}
            check(not bad_f, f"{argv} → {want.get('cmd')}" + (f" 但 {bad_f}" if bad_f else ""))
        except SystemExit:
            check(False, f"{argv} 解析失败")

    names = {o for act in ap._actions for o in act.option_strings}
    check({"-w", "--workspace", "-v", "-T", "-W", "-r"} <= names,
          "全局开关从 parser._actions 派生(以后新增开关不会漏同步)")

    # --help 不能被 go 截走
    for h in (["--help"], ["-h"], ["-v", "--help"]):
        check(_with_default_cmd(h, ap) == h, f"{h} 原样交给 argparse(不注入 go)")

    print("\n[7b] 交互输入诉求(不用在 shell 里打引号)")
    import io
    real = sys.stdin
    try:
        sys.stdin = io.StringIO("帮我做个 md→html 小工具\n")
        check(ask_for_prompt() == "帮我做个 md→html 小工具", "读一行标准输入当诉求")
        # 中文引号照样能进去 —— 它不经过 shell 解析,这正是这条路径的意义
        sys.stdin = io.StringIO('做个"带引号"的东西!\n')
        check(ask_for_prompt() == '做个"带引号"的东西!', "中文引号/感叹号原样进入,不经 shell")
        sys.stdin = io.StringIO("   \n")
        try:
            ask_for_prompt()
            check(False, "空输入应当退出")
        except SystemExit as e:
            check("空" in str(e), f"空输入有明确报错({str(e)[:24]}…)")
        sys.stdin = io.StringIO("")          # EOF
        try:
            ask_for_prompt()
            check(False, "EOF 应当退出")
        except SystemExit as e:
            check("取消" in str(e) or "空" in str(e), "EOF 干净退出,不抛栈")
    finally:
        sys.stdin = real

    # ---------------------------------------------------------------
    print("\n[8] starter_flow 的接线(`flower go` 背后那个流程)")
    ws = fresh(tmp, "p4")
    wf6 = starter_flow("帮我做个 md→html 小工具", workspace=ws, clarify_only=True)
    check(isinstance(wf6.workbench, Workbench), "workbench 挂上了")
    check(wf6.channel is not None, "channel 挂上了")
    check((wf6.workbench.notes / "需求.md").parent == wf6.workbench.notes,
          "brief 落在 wb.notes 下(和手写模板同一条保证)")
    check(len(wf6.steps) == 1, "clarify_only=True → 一步")
    full = starter_flow("x", workspace=ws)
    check([st.name for st in full.steps] == ["确认需求", "设定目标", "干活"],
          f"默认 → 三步:{[st.name for st in full.steps]}")
    work = full.steps[-1]
    check(work.gate is not None and work.on_reject is not None,
          "干活那步被目标看守包住了(gate 判定 + on_reject 打回)")
    check(work.retries == 2, f"rounds 默认 3 → retries=2(总轮数 3),实际 {work.retries}")
    check(starter_flow("x", workspace=ws, rounds=5).steps[-1].retries == 4,
          "--rounds 5 → retries=4")
    nogoal = starter_flow("x", workspace=ws, goal=False)
    check([st.name for st in nogoal.steps] == ["确认需求", "干活"],
          "goal=False → 回到两步")
    check(nogoal.steps[-1].gate is None and nogoal.steps[-1].on_reject is None,
          "goal=False 时干活那步没有判定")
    spec6 = wf6.steps[0].spec
    check(not ({"Write", "Edit", "Bash", "Agent"} & set(spec6.allowed_tools or [])),
          f"确认者白名单没有写工具:{spec6.allowed_tools}")
    ch6 = starter_flow("x", workspace=ws, max_asks=12, timeout_s=0).channel
    check(ch6.max_asks == 12 and ch6.timeout_s == 0, "--asks / --timeout 透传到通道")
    check(starter_flow("x", workspace=ws).channel.max_asks is None,
          "**默认不限提问次数** —— 问几次由确认者自己判断")
    check(wf6.steps[0].spec.max_turns is None,
          "确认者 max_turns 也是不限 —— 每次提问就是一轮,设小了「不限次数」就是空话")
    # 这一段要一个**不在任何 git 仓库里**的目录。tests/_ws_trial 在 flower 仓库内部,
    # 而 `git rev-parse --is-inside-work-tree` 对子目录也返回 true ——
    # 所以仓库 git init 之后这条断言会失效。用系统临时目录躲开。
    import tempfile
    outside = Path(tempfile.mkdtemp(prefix="flower-nogit-"))
    for bad_ask, why in (("", "空诉求"), ("   ", "只有空白")):
        try:
            starter_flow(bad_ask, workspace=ws)
            check(False, f"{why}应当报错")
        except ValueError as e:
            check("诉求" in str(e), f"{why}有明确报错")
    try:
        starter_flow("x", workspace=outside, isolate=True)   # 系统临时目录,不在任何仓库里
        check(False, "isolate 在非 git 仓库应当报错")
    except ValueError as e:
        check("git" in str(e), f"--isolate 非 git 仓库明确报错({str(e)[:30]}…)")
    subprocess.run(["git", "init", "-q", str(outside)], check=True, capture_output=True)
    check(starter_flow("x", workspace=outside, isolate=True).workbench.external,
          "isolate 时工作台自动移到仓库外(worktree 是私有副本,工作台是共享层)")
    subprocess.run(["rm", "-rf", str(outside)], check=False)

    # ---------------------------------------------------------------
    print("\n[9] 真实命令行 `flower \"…\" --clarify-only`(预置确认书 → 跳过 → 零请求)")
    ws = fresh(tmp, "p5")
    Brief.parse(COMPLETE_BRIEF).write(ws / ".flower" / "notes" / "需求.md")
    exe = ROOT / ".venv" / "bin" / "flower"
    r = subprocess.run([str(exe), "帮我做个 md→html 小工具", "--clarify-only"],
                       cwd=ws, capture_output=True, text=True, timeout=120)
    check(r.returncode == 0, f"退出码 0(实际 {r.returncode}){r.stderr[-160:] if r.returncode else ''}")
    check("总花费 $0" in r.stdout, "花费 $0 —— 一步都没跑")
    check(not (ws / "runs" / "manifest.json").exists(),
          "没有 manifest —— Runtime.run() 一次都没进")
    check((ws / ".flower" / "INDEX.md").is_file(), "工作台索引生成在项目内")

    print(f"\n{'✓ 一键入口与模板验证全部通过' if not fail else f'✗ {fail} 项失败'}"
          f"(共 {ok + fail} 项)")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
